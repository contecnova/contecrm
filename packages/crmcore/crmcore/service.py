"""Factoría de servicios: la única forma de crear una aplicación en contecrm.

Un servicio no monta su FastAPI a mano. Llama a `crear_servicio()` y recibe una
aplicación que ya trae, sin poder desactivarlo:

  * el contexto de tenant y la correlación de peticiones,
  * los errores en formato Problem Details,
  * el contrato OpenAPI generado del código (CRM-00.02.01.04),
  * las métricas, la salud y el `/metrics`,
  * el guard de aislamiento en la capa ORM,
  * el bus conectado y el relevo del outbox corriendo,
  * la comprobación de secretos y de rol de base de datos al arrancar.

**Por qué imponerlo desde aquí.** Si cada servicio montara sus middlewares,
tarde o temprano uno se dejaría el de tenant —o lo pondría en el orden que no
es— y el fallo no se vería hasta que dos clientes se vieran los datos. Lo
transversal tiene que ser lo que pasa por defecto, y saltárselo tiene que
costar escribirlo.

    from crmcore.service import crear_servicio

    app = crear_servicio(
        nombre="identity",
        descripcion="Usuarios, roles, sesiones y federación",
        routers=[usuarios.router, roles.router],
    )
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

from crmcore.logging import get_logger, setup_logging

logger = get_logger(__name__)

# Estado del proceso, para que readiness pueda decir POR QUÉ no está listo en
# vez de un "no" sin explicación, que obliga a leer logs para triar.
_estado: dict[str, Any] = {"bus": None, "relevo": None, "listo": False, "motivos": []}


def _barridos_del_nucleo(servicio: str) -> list[Any]:
    """Las purgas de las tablas que tiene TODO servicio.

    Las tres estaban escritas, probadas y **sin llamador**, así que las tres
    tablas crecían sin techo en los catorce servicios a la vez:

        inbox.purgar          claves de deduplicación de eventos entrantes
        outbox.purgar_publicados   eventos ya publicados
        adjuntos.purgar_huerfanos  ficheros subidos que nunca se enlazaron

    Se registran aquí y no en cada `main.py` por lo mismo que la idempotencia se
    monta global: son catorce sitios donde acordarse, y «funciona donde alguien
    se acordó» no es una garantía. Con esto, además, `INBOX_RETENCION_DIAS` y
    `OUTBOX_RETENCION_DIAS` dejan de ser ajustes decorativos.

    Las funciones se importan **aquí y no dentro del `_correr`**: si alguien
    renombra una, el arranque revienta —que es cuando hay alguien mirando— en
    vez de fallar en la primera vuelta y tardar tres en marcarse averiada.
    """
    from crmcore.bus import inbox, outbox
    from crmcore.config import get_settings
    from crmcore.datos import adjuntos
    from crmcore.db.session import sesion
    from crmcore.tareas import Tarea, por_tenant

    s = get_settings()
    cada = int(s.tarea_purgas_intervalo_s)

    def _purga(funcion: Any, clave: str, **kwargs: Any) -> Any:
        def _correr() -> dict[str, Any]:
            with sesion(sistema=True) as db:
                return {clave: funcion(db, **kwargs)}

        return _correr

    def _tenants_con_adjuntos() -> list[Any]:
        """Los tenants que tienen algo que barrer, de SU propia tabla.

        No se pide la lista de tenants a `tenancy`: es de otro servicio y no se
        lee desde aquí. Además, la lista buena es más corta — la mayoría de los
        tenants no tienen adjuntos huérfanos.
        """
        from sqlalchemy import select

        from crmcore.datos.adjuntos import Adjunto

        with sesion(sistema=True) as db:
            return [t for (t,) in db.execute(select(Adjunto.tenant_id).distinct()).all()]

    def _huerfanos_de(tenant_id: Any) -> dict[str, Any]:
        with sesion(sistema=True) as db:
            return {"borrados": adjuntos.purgar_huerfanos(db, tenant_id)}

    return [
        Tarea(
            f"{servicio}.inbox",
            cada,
            _purga(inbox.purgar, "borrados", dias=int(s.inbox_retencion_dias)),
            al_arrancar=False,
        ),
        Tarea(
            f"{servicio}.outbox",
            cada,
            _purga(outbox.purgar_publicados, "borrados", dias=int(s.outbox_retencion_dias)),
            al_arrancar=False,
        ),
        # Por tenant, y aislando cada uno: un fallo en el tenant 40 no puede
        # parar a los 200 siguientes.
        Tarea(
            f"{servicio}.adjuntos_huerfanos",
            cada,
            por_tenant(_tenants_con_adjuntos, _huerfanos_de),
            al_arrancar=False,
        ),
    ]


def crear_servicio(
    *,
    nombre: str,
    descripcion: str = "",
    routers: list[APIRouter] | None = None,
    routers_sin_prefijo: list[APIRouter] | None = None,
    version: str = "0.1.0",
    al_arrancar: Callable[[], Any] | None = None,
    al_parar: Callable[[], Any] | None = None,
    consumidores: list[tuple[str, Any, str]] | None = None,
    necesita_bus: bool = True,
    necesita_db: bool = True,
) -> FastAPI:
    """Construye la aplicación de un servicio.

    `consumidores` son tuplas `(patrón, manejador, grupo)` que se suscriben al
    bus al arrancar. Declararlos aquí y no en el arranque del módulo evita el
    error clásico de suscribirse en tiempo de importación: en las pruebas, eso
    deja consumidores vivos entre casos.

    `routers_sin_prefijo` monta rutas TAL CUAL, sin anteponer `api_prefix`. Lo
    usa el gateway, que reenvía `/api/{ruta}` entera y por tanto no puede
    llevar el prefijo dos veces — con él, el proxy escucharía en
    `/api/v1/api/v1/...` y ninguna petición real llegaría. Es la única
    excepción prevista; cualquier otro servicio que lo necesite debería
    explicar por qué.
    """
    import os

    # El nombre del servicio tiene que estar en el entorno ANTES de leer la
    # configuración, porque de él dependen el esquema de base de datos, la
    # etiqueta de las métricas y el nombre del consumidor durable.
    os.environ.setdefault("SERVICE_NAME", nombre)
    if os.environ.get("SERVICE_NAME") != nombre:
        os.environ["SERVICE_NAME"] = nombre

    from crmcore.config import get_settings, limpiar_cache_settings

    limpiar_cache_settings()
    s = get_settings()
    setup_logging()

    problemas = s.verificar_para_produccion()
    if problemas:
        # Se listan todos y se corta. Arrancar en producción con la clave de
        # firma de ejemplo es peor que no arrancar: parece que funciona.
        for p in problemas:
            logger.error("arranque.config_insegura", problema=p)
        raise RuntimeError(
            "Configuración insegura para producción:\n  - " + "\n  - ".join(problemas)
        )

    @asynccontextmanager
    async def ciclo_de_vida(_app: FastAPI) -> AsyncIterator[None]:
        logger.info("servicio.arranca", servicio=nombre, version=version, env=s.env)

        # Antes que nada, para que el propio arranque se pueda trazar. Si
        # `TRACING_ENABLED` está puesto y OpenTelemetry no está instalado, esto
        # LANZA y el servicio no arranca: ver `crmcore.obs.trazas`.
        from crmcore.obs import trazas

        trazas.configurar(nombre, version)

        if necesita_db:
            from crmcore.datos.guard_borrados import instalar_guard_borrados
            from crmcore.db.session import get_engine, verificar_rol_sin_bypass
            from crmcore.tenancy.guard import instalar_guard

            instalar_guard()
            # Y el de la papelera: lo borrado no sale en los listados sin que
            # cuarenta consultas tengan que acordarse de filtrarlo.
            instalar_guard_borrados()
            # Y el de la cuota de registros. Si no se instalara, la cuota no se
            # aplicaría y **nada fallaría**, que es la avería que más veces ha
            # salido: por eso hay una prueba que comprueba esta línea.
            from crmcore.cuota_registros import instalar_guard_cuota

            instalar_guard_cuota()
            for aviso in verificar_rol_sin_bypass(get_engine()):
                # Error y no excepción: en desarrollo se trabaja a menudo con el
                # rol de administrador, y negarse a arrancar haría imposible el
                # ciclo local. En producción lo convierte en fallo el gate de
                # despliegue, que sí puede exigirlo.
                logger.error("arranque.rls_sin_garantia", problema=aviso)

        if necesita_bus:
            from crmcore.bus.base import crear_bus

            try:
                bus = await crear_bus(nombre)
                _estado["bus"] = bus
                # La réplica de ajustes la escucha TODO servicio, y se
                # suscribe aquí para que ninguno pueda olvidarse: la tabla
                # `ajustes_runtime` vive en el esquema de cada uno, así que un
                # servicio que no consuma este evento se queda con la
                # configuración de su `.env` mientras el resto usa la del
                # cliente. Esa divergencia tarda semanas en atribuirse.
                from crmcore.authz.politicas import (
                    POLITICA_CAMBIADA,
                    consumir_politica,
                )
                from crmcore.datos.calendario import (
                    CALENDARIO_CAMBIADO,
                    consumir_calendario,
                )
                from crmcore.datos.cambio import (
                    TIPO_CAMBIO_FIJADO,
                    consumir_tipo_cambio,
                )
                from crmcore.documental.enlaces import (
                    ORGANIZACION_CAMBIADA,
                    consumir_organizacion,
                )
                from crmcore.documental.inventario import (
                    INVENTARIO_SOLICITADO,
                    consumir_solicitud,
                )
                from crmcore.extensiones import consumidor_de_extensiones
                from crmcore.metamodelo import ESQUEMA_CAMBIADO, consumir_esquema
                from crmcore.runtime.settings import AJUSTE_CAMBIADO, consumir_ajuste
                from crmcore.security.byok import CLAVE_CAMBIADA, consumir_clave

                suscripciones = [
                    (AJUSTE_CAMBIADO, consumir_ajuste, f"{nombre}-ajustes"),
                    # La clave propia del tenant (BYOK) se replica igual y por
                    # la misma razón: si un servicio no la tuviera, seguiría
                    # cifrando con la maestra y revocarla no dejaría ilegible
                    # nada — el único modo de fallo inaceptable de BYOK.
                    (CLAVE_CAMBIADA, consumir_clave, f"{nombre}-byok"),
                    # El inventario del corpus para el certificado de
                    # destrucción (RT-5). También universal, y por el mismo
                    # motivo: `documentos_enlazados` vive en el esquema de cada
                    # servicio, así que un servicio que no contestara dejaría
                    # sus contratos fuera del certificado sin que nadie lo
                    # notara — y el cliente creería que ya no existen.
                    (INVENTARIO_SOLICITADO, consumir_solicitud, f"{nombre}-invdoc"),
                    # El mapeo tenant → organización del gestor documental.
                    # `organizaciones_documentales` vive en el esquema de cada
                    # servicio, y **sin mapeo no se llama al gestor**: si uno no
                    # lo replicara, el corpus de sus registros sería invisible
                    # mientras el de los demás funciona, con el administrador
                    # viendo su mapeo guardado y correcto.
                    (ORGANIZACION_CAMBIADA, consumir_organizacion, f"{nombre}-orgdoc"),
                    # Las políticas ABAC. La decisión se toma DONDE ESTÁ EL
                    # DATO —`party` decide sobre una cuenta— así que la política
                    # tiene que estar en el esquema de cada servicio. Uno que no
                    # la replicara seguiría decidiendo con las de ayer, y en
                    # permisos esa es la divergencia más cara: no falla nada,
                    # simplemente alguien ve lo que ya no debería.
                    (POLITICA_CAMBIADA, consumir_politica, f"{nombre}-abac"),
                    # Los tipos de cambio con fecha (CRM-03.02.01.07). Van aquí
                    # y no en una llamada a `tenancy` porque sumar un pipeline
                    # de diez mil oportunidades en cuatro monedas serían diez
                    # mil llamadas de red, y porque una previsión no puede
                    # depender de que otro servicio esté en pie.
                    (TIPO_CAMBIO_FIJADO, consumir_tipo_cambio, f"{nombre}-fx"),
                    # Los calendarios laborales (CRM-04.01.02.04). Un servicio
                    # que no los replicara calcularía los vencimientos con el
                    # horario de fábrica mientras el resto usa el del cliente, y
                    # el incumplimiento que reportara no coincidiría con el que
                    # ve el cliente.
                    (CALENDARIO_CAMBIADO, consumir_calendario, f"{nombre}-cal"),
                    # El esquema que el tenant se define (CRM-00.04.03.02). Un
                    # servicio que no lo replicara seguiría validando con los
                    # campos de ayer: rechazaría el campo que el consultor acaba
                    # de crear —con el cliente delante— o aceptaría uno retirado.
                    (ESQUEMA_CAMBIADO, consumir_esquema, f"{nombre}-esquema"),
                    # Y lo que las extensiones del tenant hayan pedido oír
                    # (CRM-06.03). `consumidor_de_extensiones` estaba escrito,
                    # probado y **sin que lo registrara nadie**: una extensión
                    # podía suscribirse a un evento y no recibía ninguno. El
                    # mecanismo existía entero y no llegaba al bus.
                    #
                    # UNA sola suscripción para todas, y no una por extensión:
                    # cada suscripción es un consumidor durable, y un tenant con
                    # cincuenta extensiones tendría cincuenta compitiendo por el
                    # mismo flujo. El patrón es ancho porque el reparto ya filtra
                    # por tipo, y una extensión rota no para el bus.
                    ("*", consumidor_de_extensiones(), f"{nombre}-extensiones"),
                    *(consumidores or []),
                ]
                for patron, manejador, grupo in suscripciones:
                    await bus.suscribir(patron, manejador, grupo=grupo)

                if s.outbox_enabled:
                    from crmcore.bus.outbox import Relevo

                    relevo = Relevo(bus)
                    _estado["relevo"] = asyncio.create_task(
                        relevo.correr(), name=f"outbox-{nombre}"
                    )
                    _estado["relevo_obj"] = relevo
            except Exception as exc:  # noqa: BLE001 — sin bus se sirve degradado
                # El servicio arranca igual: las lecturas siguen funcionando y
                # las escrituras dejan el evento en la tabla de salida, que se
                # publicará cuando el bus vuelva. Caerse aquí convertiría una
                # avería del bus en una caída total del CRM.
                _estado["motivos"].append(f"bus no disponible: {exc}")
                logger.error("arranque.bus_no_disponible", error=str(exc)[:300])

        # ── Los barridos del núcleo, en TODOS los servicios ───────────────
        #
        # Tres tablas del núcleo crecían sin techo porque su función de purga no
        # la llamaba nadie: la bandeja de entrada de eventos, la de salida y los
        # adjuntos huérfanos. Las tres existen en los catorce servicios, así que
        # colgarlas del `main.py` de cada uno sería «funciona en los que alguien
        # se acordó» — que es exactamente lo que ya pasó.
        #
        # Van aquí, en el arranque común, y con ellas los ajustes que las
        # gobiernan dejan de ser decorativos: `INBOX_RETENCION_DIAS` existía,
        # estaba documentado y no lo leía nadie.
        if necesita_db:
            from crmcore.tareas import RelevoDeTareas

            _base = RelevoDeTareas(_barridos_del_nucleo(nombre))
            _estado["relevo_base_obj"] = _base
            _estado["relevo_base"] = asyncio.create_task(
                _base.correr(), name=f"{nombre}-barridos-nucleo"
            )

        if al_arrancar:
            resultado = al_arrancar()
            if asyncio.iscoroutine(resultado):
                await resultado

        _estado["listo"] = True
        logger.info("servicio.listo", servicio=nombre, puerto=s.service_port)
        try:
            yield
        finally:
            _estado["listo"] = False
            logger.info("servicio.para", servicio=nombre)
            if al_parar:
                resultado = al_parar()
                if asyncio.iscoroutine(resultado):
                    await resultado
            base_obj = _estado.get("relevo_base_obj")
            if base_obj:
                base_obj.parar()
            base = _estado.get("relevo_base")
            if base:
                base.cancel()
            relevo_obj = _estado.get("relevo_obj")
            if relevo_obj:
                relevo_obj.parar()
            tarea = _estado.get("relevo")
            if tarea:
                tarea.cancel()
            bus = _estado.get("bus")
            if bus:
                await bus.cerrar()

    from crmcore.http.idempotency import dependencia as dep_idempotencia

    app = FastAPI(
        title=f"{s.app_name} · {nombre}",
        # Global, no ruta a ruta: son más de cien rutas de escritura, y
        # engancharla una a una significa que funciona en las que alguien se
        # acordó. Va como dependencia y no como middleware porque necesita la
        # identidad ya autenticada — ver el porqué en `crmcore.http.idempotency`.
        dependencies=[Depends(dep_idempotencia)],
        description=descripcion,
        version=version,
        lifespan=ciclo_de_vida,
        # La documentación cuelga del prefijo de versión para que `v1` y `v2`
        # puedan convivir con sus esquemas separados.
        docs_url=f"{s.api_prefix}/docs" if s.api_docs_enabled else None,
        redoc_url=None,
        openapi_url=f"{s.api_prefix}/openapi.json" if s.api_docs_enabled else None,
    )

    _montar_middlewares(app, s, nombre)
    from crmcore.http.problems import registrar_manejadores

    registrar_manejadores(app)
    _montar_salud(app, nombre, version)

    if necesita_db:
        # La página de estado del tenant (CRM-00.06.01.06) la publica TODO
        # servicio con base de datos, y se monta aquí para que ninguno pueda
        # olvidarse: si faltara en uno, la página del cliente tendría un agujero
        # sin decirlo, que es peor que no tener página.
        from crmcore.http.estado_router import crear_router_estado

        app.include_router(crear_router_estado(nombre), prefix=s.api_prefix)

        # Igual con la restauración selectiva (CRM-00.06.02.03) y con el RAT y
        # el informe de cumplimiento (CRM-07.03.01.04, CRM-07.03.01.07): cada
        # servicio restaura lo suyo y declara lo suyo, y montarlo aquí es lo que
        # impide que un servicio se quede sin ello sin que nadie lo note.
        from crmcore.http.cumplimiento_router import crear_router_cumplimiento
        from crmcore.http.papelera_router import crear_router_papelera
        from crmcore.http.restauracion_router import crear_router_restauracion

        app.include_router(crear_router_restauracion(nombre), prefix=s.api_prefix)
        # Y su papelera: cada servicio guarda la suya en su propio esquema, así
        # que cada uno tiene que poder enseñarla. Sin esto, borrar una plantilla
        # la mandaba a una papelera sin pantalla.
        app.include_router(crear_router_papelera(nombre), prefix=s.api_prefix)
        app.include_router(crear_router_cumplimiento(nombre), prefix=s.api_prefix)

        # Y la sincronización del móvil sin conexión. Va por servicio, como la
        # papelera: la cola del móvil lleva operaciones sobre objetos de varios,
        # y cada uno resuelve los suyos contra sus propios registros. Un punto
        # central tendría que leer las tablas de los catorce.
        #
        # Montarlo aquí y no en cada `main.py` es lo que impide que un servicio
        # se quede sin ello sin que nadie lo note — que es como `crmcore.movil`
        # acabó resolviendo lo difícil sin que lo alcanzara ninguna ruta.
        from crmcore.http.movil_router import crear_router_movil

        app.include_router(crear_router_movil(nombre), prefix=s.api_prefix)

        # Y el volumen: qué tabla va camino de dar problemas, cómo se particiona
        # y qué se puede mover a frío. También por servicio, porque las tablas
        # que crecen están repartidas por catorce esquemas y cada uno sabe de
        # las suyas. Montarlo aquí es lo que impide que un servicio se quede sin
        # ello — que es exactamente como `crmcore.datos.particionado` acabó
        # resolviéndolo entero sin que lo importara nadie.
        from crmcore.http.volumen_router import crear_router_volumen

        app.include_router(crear_router_volumen(nombre), prefix=s.api_prefix)

        # Y el rastro completo de los agregados que lo tengan encendido. Estaba
        # entero y apagado: la tabla de hechos se creaba en dos servicios y
        # nadie declaraba ningún agregado, así que estaba siempre vacía — y un
        # rastro vacío contesta lo mismo que si todo fuera bien.
        from crmcore.http.rastro_router import crear_router_rastro

        app.include_router(crear_router_rastro(nombre), prefix=s.api_prefix)

        # Y sus vocabularios, si declara alguno. Solo entonces: en un servicio
        # que no valida contra ninguna lista, estas rutas serían tres pantallas
        # vacías más en la superficie.
        from crmcore import vocabulario as _voc
        from crmcore.http.vocabulario_router import crear_router_vocabulario

        if _voc.registrados():
            app.include_router(crear_router_vocabulario(nombre), prefix=s.api_prefix)

    for router in routers or []:
        app.include_router(router, prefix=s.api_prefix)
    for router in routers_sin_prefijo or []:
        app.include_router(router)

    # Al final, cuando ya están todos los routers: la superficie se calcula
    # sobre las rutas montadas, así que montarla antes devolvería una lista
    # vacía (CRM-07.01.01.01).
    from crmcore.http.superficie import montar_superficie

    montar_superficie(app, nombre, s.api_prefix)

    return app


def _montar_middlewares(app: FastAPI, s: Any, nombre: str = "") -> None:
    """Monta los middlewares en el orden correcto.

    Starlette ejecuta el ÚLTIMO añadido como el más externo, así que se añaden
    del más interno al más externo: límites → tiempos → contexto. El contexto
    tiene que ser el más externo porque todo lo demás necesita el `request_id`.
    """
    # El más interno: cuando llega aquí, la petición ya pasó los límites y tiene
    # contexto con tenant, que es lo que la clave de idempotencia necesita.
    from crmcore.http.etag import ETagMiddleware
    from crmcore.http.middleware import (
        CifradoEnTransitoMiddleware,
        ContextoMiddleware,
        IdempotenciaMiddleware,
        LimitesMiddleware,
        TiempoMaximoMiddleware,
        TiemposMiddleware,
    )

    app.add_middleware(IdempotenciaMiddleware)
    # Por dentro de la idempotencia: la respuesta que se guarda para el
    # reintento es la del endpoint, y la cabecera se recalcula al repetirla.
    app.add_middleware(ETagMiddleware)
    app.add_middleware(LimitesMiddleware)
    app.add_middleware(TiemposMiddleware, servicio=nombre)
    # Va POR FUERA de los tiempos y por dentro del contexto: lo que corta tiene
    # que quedar medido como petición cortada, y el corte necesita el contexto
    # puesto para que el registro diga de qué tenant era.
    app.add_middleware(TiempoMaximoMiddleware)
    # El más externo después del contexto: una respuesta que no pase por aquí
    # sale sin HSTS, y una petición en claro que no pase por aquí ya ha viajado.
    app.add_middleware(CifradoEnTransitoMiddleware)
    app.add_middleware(ContextoMiddleware)

    if s.origenes_cors:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=s.origenes_cors,
            allow_credentials=True,
            allow_methods=["*"],
            # Las cabeceras del contrato se listan para que un navegador pueda
            # leerlas: sin `expose_headers`, el JavaScript del cliente no ve ni
            # el ETag ni el identificador de petición, y se queda sin poder
            # hacer concurrencia optimista ni citar el id en un soporte.
            allow_headers=["*"],
            expose_headers=["ETag", "X-Request-Id", "Retry-After", "Sunset", "Location"],
        )


def _montar_salud(app: FastAPI, nombre: str, version: str) -> None:
    """Endpoints de salud y métricas.

    `/health/live` y `/health/ready` son cosas distintas y confundirlas cuesta
    caro: si el liveness comprobara la base de datos, una caída de Postgres
    haría que el orquestador matara y recreara todos los servicios sanos, y al
    volver se encontrarían la base igual de caída pero ya sin caché ni
    conexiones. El liveness dice «este proceso no está colgado»; el readiness
    dice «puede atender ahora mismo».
    """

    @app.get("/health/live", tags=["salud"], summary="El proceso responde")
    async def live() -> dict[str, str]:
        return {"estado": "vivo", "servicio": nombre, "version": version}

    @app.get("/health/ready", tags=["salud"], summary="Puede atender peticiones")
    async def ready(response: Response) -> dict[str, Any]:
        from crmcore.config import get_settings

        s = get_settings()
        comprobaciones: dict[str, Any] = {}
        ok = True

        # CADA COMPROBACIÓN, ACOTADA EN TIEMPO. `HEALTH_CHECK_TIMEOUT_S` existía
        # en los ajustes, documentado —«un readiness lento hace que el
        # orquestador crea que el servicio está caído»— y **no lo leía nadie**:
        # una base colgada dejaba colgado el propio readiness, y entonces el que
        # decide es el tiempo de espera del orquestador, que mata el proceso sin
        # dejar ni un diagnóstico. Decir «no listo» en tres segundos es
        # infinitamente más útil que no decir nada en treinta.
        espera = float(s.health_check_timeout_s)

        def _ping_db() -> None:
            from sqlalchemy import text

            from crmcore.db.session import get_engine

            with get_engine().connect() as conn:
                conn.execute(text("SELECT 1"))

        try:
            # En un hilo porque la comprobación es síncrona. Y con un límite:
            # `wait_for` deja de ESPERAR al hilo, pero **no lo interrumpe** —la
            # conexión colgada sigue colgada hasta que el driver se rinda—. Lo
            # que se gana es que el readiness contesta a tiempo en vez de
            # colgarse con ella, que es lo que hace falta para que el
            # orquestador sepa qué pasa en vez de matar el proceso a ciegas.
            await asyncio.wait_for(asyncio.to_thread(_ping_db), timeout=espera)
            comprobaciones["db"] = "ok"
        except TimeoutError:
            comprobaciones["db"] = f"no contesta en {espera:g} s"
            ok = False
        except Exception as exc:  # noqa: BLE001 — el readiness informa, no lanza
            comprobaciones["db"] = f"error: {str(exc)[:160]}"
            ok = False

        bus = _estado.get("bus")
        if bus is not None:
            try:
                vivo = await asyncio.wait_for(bus.ping(), timeout=espera)
                comprobaciones["bus"] = "ok" if vivo else "sin conexión"
                ok = ok and comprobaciones["bus"] == "ok"
            except TimeoutError:
                comprobaciones["bus"] = f"no contesta en {espera:g} s"
                ok = False
            except Exception as exc:  # noqa: BLE001 — el readiness informa, no lanza
                comprobaciones["bus"] = f"error: {str(exc)[:160]}"
                ok = False
        elif s.outbox_enabled:
            # Sin bus el servicio atiende igual, pero los eventos se acumulan.
            # Se dice, sin marcarlo como no listo: sacarlo del balanceo no
            # arreglaría nada y dejaría al cliente sin servicio.
            comprobaciones["bus"] = "no conectado (los eventos esperan en la tabla de salida)"

        if not _estado["listo"]:
            ok = False
            comprobaciones["arranque"] = "en curso"

        response.status_code = 200 if ok else 503
        return {"estado": "listo" if ok else "no listo", "comprobaciones": comprobaciones}

    @app.get("/health", tags=["salud"], summary="Alias de readiness")
    async def health(response: Response) -> dict[str, Any]:
        return await ready(response)

    from crmcore.config import get_settings

    if get_settings().metrics_enabled:

        @app.get(get_settings().metrics_path, include_in_schema=False)
        async def metricas() -> Response:
            from crmcore.obs.metrics import exportar

            return Response(
                content=exportar(), media_type="text/plain; version=0.0.4; charset=utf-8"
            )


def bus_actual() -> Any:
    """Bus del proceso, para quien necesite publicar fuera de una petición."""
    return _estado.get("bus")
