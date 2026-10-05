"""El programador de integraciones: qué se ejecuta solo, cuándo y dónde aterriza
(CRM-00.03.04.02, CRM-00.03.04.05, CRM-00.03.04.06).

**Esto era el agujero grande de integración.** El conector declarativo estaba
completo —paginación, OAuth2, mapeo de campos, guard de URL— y lo disparaba
**una sola ruta, a mano**. Una integración que hay que ejecutar pulsando un
botón no es una integración: es una pantalla. Y como no había nada que corriera
en bucle, las decisiones que gobiernan una sincronización quedaron escritas,
probadas y sin que las llamara nadie: cuándo avanzar la marca, cómo reintentar
cuando el proveedor corta, a qué ritmo traer la primera carga.

Las decisiones de este módulo, y por qué:

**La cadencia es de cada operación, no global.** Leer el maestro de clientes una
vez al día y consultar el stock cada cinco minutos son la misma pieza con ritmos
distintos. Un intervalo global obliga al más lento a correr como el más rápido o
al revés, y lo que se hace entonces es apagar el que molesta.

**Con un suelo que no se puede saltar.** El proveedor de enfrente tiene cuota, y
una operación puesta «cada minuto» contra una API que admite sesenta llamadas
por hora acaba con la aplicación bloqueada — a todos los clientes, no sólo al
que se pasó. El suelo es un ajuste (`INTEGRACION_CADENCIA_MINIMA_MINUTOS`), no
una constante: el que convenga a tres tenants no es el de trescientos.

**Lo que entra aterriza en una tabla, no en un contador.** Sin un sitio donde
dejarlo, una ejecución programada sólo podía apuntar «200 registros» y tirarlos,
que es la forma más cara de no integrar nada. Aterriza con el identificador
externo como clave, y eso es lo que la hace idempotente: sin él, el mismo
pedido entra cuatro veces porque el ERP lo reenvía cada vez que alguien lo toca.

**La marca sólo avanza si no ha fallado nada.** Avanzar con un fallo dentro deja
un hueco que no se recupera nunca, y que nadie nota — porque no falta una
pantalla, falta un pedido.

**Cuando el proveedor dice cuánto esperar, se le hace caso.** La operación se
queda en reposo hasta entonces en vez de reintentar en la vuelta siguiente.

**Un tenant con doscientas operaciones vencidas no monopoliza el relevo.** Hay
tope por vuelta, y lo que no entra espera a la siguiente: es preferible que la
integración de uno vaya un minuto tarde a que las de los otros no vayan.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import CrmError, ErrorValidacion
from crmcore.logging import get_logger
from sqlalchemy import select

from services.integration import suites, suites_operacion
from services.integration.modelos import Conexion, Ejecucion, Operacion, RegistroRecibido

logger = get_logger(__name__)

# Protocolos que este programador sabe ejecutar hoy, con qué los ejecuta. Es un
# mapa y no un `if`: añadir un transporte es añadir una entrada, y lo que no
# está se dice en vez de quedarse callado.
TRANSPORTES = ("rest", "soap", "sftp", "fichero", "edi", "amqp")


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _con_tz(v: datetime | None) -> datetime | None:
    if v is None:
        return None
    return v if v.tzinfo else v.replace(tzinfo=timezone.utc)


# ── Declarar la cadencia ──────────────────────────────────────────────────


def programar(
    uow: UnidadDeTrabajo, operacion_id: UUID, *, cada_minutos: int, activa: bool = True
) -> dict[str, Any]:
    """Dice cada cuánto se ejecuta sola una operación. Cero: sólo a mano.

    El suelo se aplica aquí y no al ejecutar: rechazar una cadencia imposible
    cuando se configura es un mensaje; aplicarla en silencio al ejecutar es una
    pantalla que dice «cada minuto» y un sistema que hace otra cosa.
    """
    from crmcore.config import get_settings

    fila = uow.db.get(Operacion, operacion_id)
    if fila is None or fila.tenant_id != uow.tenant_id:
        raise ErrorValidacion(
            "Esa operación no existe", error_code="integracion.operacion_no_encontrada"
        )
    suelo = int(get_settings().integracion_cadencia_minima_minutos)
    if cada_minutos and cada_minutos < suelo:
        raise ErrorValidacion(
            f"La cadencia mínima es de {suelo} minutos. Por debajo, el proveedor "
            "acaba cortando la cuota, y cuando corta lo hace para todos los "
            "clientes, no sólo para el que se pasó.",
            error_code="integracion.cadencia_demasiado_corta",
            detalle={"minimo_minutos": suelo},
        )
    fila.cada_minutos = max(0, int(cada_minutos))
    fila.activa = bool(activa)
    # La primera se programa YA y no dentro de un ciclo: quien acaba de
    # configurarla quiere ver si funciona, no esperar a mañana para enterarse de
    # que la ruta estaba mal escrita.
    fila.proxima_at = _ahora() if fila.cada_minutos and fila.activa else None
    fila.intentos = 0
    fila.pausada_hasta = None
    uow.db.flush()
    return {
        "operacion": fila.clave,
        "cada_minutos": fila.cada_minutos,
        "activa": fila.activa,
        "proxima_at": fila.proxima_at.isoformat() if fila.proxima_at else None,
        "porque": (
            "Sólo a mano: ninguna cadencia declarada."
            if not fila.cada_minutos
            else "La primera vuelta sale ya, para que el fallo de configuración se "
            "vea ahora y no mañana."
        ),
    }


def pendientes(db: Any, tenant_id: UUID, *, ahora: datetime | None = None) -> list[Operacion]:
    """Las operaciones que toca ejecutar, más antigua primero.

    Más antigua primero y no al azar: con un tope por vuelta, el orden decide
    quién se queda fuera siempre. Por fecha, el que se quedó fuera es el
    siguiente en entrar.
    """
    from crmcore.config import get_settings

    momento = ahora or _ahora()
    filas = (
        db.execute(
            select(Operacion)
            .where(
                Operacion.tenant_id == tenant_id,
                Operacion.activa.is_(True),
                Operacion.cada_minutos > 0,
                Operacion.proxima_at.is_not(None),
                Operacion.proxima_at <= momento,
            )
            .order_by(Operacion.proxima_at)
            .limit(int(get_settings().integracion_max_por_vuelta))
        )
        .scalars()
        .all()
    )
    return [
        f for f in filas if not (_con_tz(f.pausada_hasta) and _con_tz(f.pausada_hasta) > momento)
    ]


# ── Ejecutar una ──────────────────────────────────────────────────────────


def _codigo_de(exc: CrmError) -> int:
    """Qué código HTTP devolvió el sistema externo, a partir del error del conector.

    El conector traduce la respuesta a un error del dominio y **pierde el
    número**, que es justo lo que `como_reintentar` necesita para decidir. Se
    recupera del detalle cuando está, y si no se usa el que corresponde a la
    clase — nunca se inventa uno que invite a reintentar.
    """
    detalle = getattr(exc, "detalle", None) or {}
    if isinstance(detalle, dict) and detalle.get("codigo"):
        return int(detalle["codigo"])
    return {
        "conector.rechazada": 400,
        "conector.fallo_remoto": 503,
        "conector.timeout": 504,
        "conector.red": 503,
    }.get(getattr(exc, "error_code", ""), 500)


def _aterrizar(
    uow: UnidadDeTrabajo, operacion: Operacion, registros: list[dict[str, Any]]
) -> dict[str, int]:
    """Guarda lo leído, sin duplicar lo que ya estaba.

    Un registro sin identificador externo **no se guarda y se cuenta aparte**:
    guardarlo con uno inventado lo duplicaría en cada vuelta, y descartarlo en
    silencio haría que faltaran filas sin que nadie supiera por qué.
    """
    sin_id = 0
    nuevos = 0
    repetidos = 0
    ya = {
        e
        for (e,) in uow.db.execute(
            select(RegistroRecibido.externo_id).where(
                RegistroRecibido.tenant_id == uow.tenant_id,
                RegistroRecibido.conexion_id == operacion.conexion_id,
                RegistroRecibido.operacion == operacion.clave,
            )
        ).all()
    }
    vistos: set[str] = set()
    for registro in registros:
        externo = str(registro.get("id_externo") or registro.get("externo_id") or "")
        if not externo:
            sin_id += 1
            continue
        if externo in ya or externo in vistos:
            repetidos += 1
            continue
        vistos.add(externo)
        uow.db.add(
            RegistroRecibido(
                tenant_id=uow.tenant_id,
                conexion_id=operacion.conexion_id,
                operacion=operacion.clave,
                externo_id=externo,
                datos=dict(registro),
            )
        )
        nuevos += 1
    uow.db.flush()
    return {"nuevos": nuevos, "repetidos": repetidos, "sin_identificador": sin_id}


def _parametros(operacion: Operacion) -> dict[str, Any]:
    """Qué se le pide al proveedor esta vuelta.

    Si la operación declara cómo pedir el incremento, se le pide sólo lo
    cambiado; si no lo declara, se trae entera. **No se adivina un parámetro de
    fecha**: pedir `?desde=` a una API que no lo entiende devuelve el catálogo
    completo y parece que funciona.
    """
    definicion = dict(operacion.definicion or {})
    if not (definicion.get("incremento") or definicion.get("recursos")):
        return {"es_completa": True, "parametros": {}, "porque": "No declara incremento."}
    # Se le da la forma que `parametros_de_incremento` espera: la declaración
    # vive en la operación, no en un perfil de suite, pero la decisión es la
    # misma y no se duplica.
    config = (
        {"recursos": dict(definicion["recursos"])}
        if definicion.get("recursos")
        else {"recursos": {operacion.clave: {k: v for k, v in definicion.items()}}}
    )
    return suites.parametros_de_incremento(
        config=config, recurso=operacion.clave, marca_actual=operacion.marca or ""
    )


def _leer(
    conexion: Conexion, operacion: Operacion, parametros: dict[str, Any], secretos: dict[str, str]
) -> dict[str, Any]:
    """Llama al sistema externo por el transporte que declare la conexión.

    `asyncio.run` y no `await`: el relevo ejecuta las tareas en un hilo aparte
    —son de base de datos y son síncronas— así que aquí no hay bucle de eventos
    corriendo y arrancar uno es correcto. Hacerlo al revés, un relevo asíncrono
    que llama a código de base de datos, bloquearía el servicio entero mientras
    sincroniza.
    """
    from services.integration import conector

    protocolo = str(conexion.protocolo or "rest").lower()
    if protocolo not in TRANSPORTES:
        raise ErrorValidacion(
            f"El protocolo «{protocolo}» no lo ejecuta el programador. Los que sí: "
            f"{', '.join(TRANSPORTES)}.",
            error_code="integracion.protocolo_no_programable",
            detalle={"protocolos": list(TRANSPORTES)},
        )
    if protocolo == "rest":
        return asyncio.run(
            conector.ejecutar(
                dict(conexion.config or {}),
                dict(operacion.definicion or {}),
                parametros,
                secretos=secretos,
                tenant_id=str(conexion.tenant_id),
            )
        )
    from services.integration import transportes_legado as legado

    # El contador de ficheros a medio escribir viaja CON la operación y vuelve
    # a ella: en memoria del proceso se perdía al reiniciar, y entonces un
    # fichero atascado desde hace tres días empezaba de cero y el aviso de
    # «esto nunca termina» no saltaba nunca.
    intentos = {str(k): int(v) for k, v in dict(operacion.estado_transporte or {}).items()}
    salida = legado.leer_programado(
        protocolo, dict(conexion.config or {}), dict(operacion.definicion or {}), intentos=intentos
    )
    operacion.estado_transporte = dict(intentos)
    return salida


def ejecutar_programada(uow: UnidadDeTrabajo, operacion: Operacion) -> dict[str, Any]:
    """Una vuelta de una operación: pedir, aterrizar, apuntar y reprogramar.

    Deja traza **pase lo que pase**. Una ejecución que falla y no apunta nada es
    una integración que «a veces no trae datos», y eso se investiga mirando el
    sistema de enfrente, donde está todo bien.
    """
    from services.integration.api import _secretos

    conexion = uow.db.get(Conexion, operacion.conexion_id)
    if conexion is None or not conexion.activa:
        operacion.activa = False
        operacion.ultimo_error = "La conexión no existe o está desactivada"
        uow.db.flush()
        return {
            "operacion": operacion.clave,
            "resultado": "detenida",
            "porque": operacion.ultimo_error,
        }

    incremento = _parametros(operacion)
    inicio = time.perf_counter()
    traza = Ejecucion(
        tenant_id=uow.tenant_id,
        conexion_id=conexion.id,
        operacion=operacion.clave,
        resultado="ok",
        parametros=dict(incremento.get("parametros") or {}),
    )
    try:
        salida = _leer(
            conexion,
            operacion,
            dict(incremento.get("parametros") or {}),
            _secretos(uow.db, conexion.id),
        )
    except CrmError as exc:
        return _apuntar_fallo(uow, operacion, traza, exc, inicio)

    registros = list(salida.get("registros") or [])
    traza.registros = len(registros)
    traza.paginas = int(salida.get("paginas") or 0)
    traza.duracion_ms = int((time.perf_counter() - inicio) * 1000)
    uow.db.add(traza)

    aterrizados = _aterrizar(uow, operacion, registros)

    # El ritmo de la PRIMERA carga se calcula cuando es completa: es la que se
    # come la cuota del tenant entero y deja sin sincronizar a los demás.
    ritmo = None
    if incremento.get("es_completa"):
        ritmo = suites_operacion.ritmo_de_primera_carga(
            elementos=len(registros),
            peticiones_por_minuto=(dict(conexion.config or {}).get("limites") or {}).get(
                "peticiones_por_minuto"
            ),
        )

    avance = suites.avanzar_incremento(
        marca_actual=operacion.marca or "",
        marca_nueva=str(salida.get("marca") or ""),
        hubo_errores=bool(aterrizados["sin_identificador"]),
    )
    operacion.marca = str(avance["marca"])
    operacion.ultima_at = _ahora()
    operacion.intentos = 0
    operacion.ultimo_error = None
    operacion.pausada_hasta = None
    operacion.proxima_at = _ahora() + timedelta(minutes=max(1, operacion.cada_minutos))
    uow.db.flush()

    if aterrizados["nuevos"]:
        uow.emitir(
            "integration.records.received",
            subject=("conexion", conexion.id),
            data={
                "operacion": operacion.clave,
                "nuevos": aterrizados["nuevos"],
                "repetidos": aterrizados["repetidos"],
            },
        )
    return {
        "operacion": operacion.clave,
        "resultado": "ok",
        "leidos": len(registros),
        **aterrizados,
        "marca_avanza": avance["avanza"],
        "ritmo_primera_carga": ritmo,
    }


def _apuntar_fallo(
    uow: UnidadDeTrabajo, operacion: Operacion, traza: Ejecucion, exc: CrmError, inicio: float
) -> dict[str, Any]:
    """Qué se hace con el fallo, según lo que diga el proveedor.

    La decisión no se toma aquí: la toma `como_reintentar`, que es donde está
    escrita y probada. Lo que se hace aquí es **aplicarla**, que es lo que no
    hacía nadie.
    """
    operacion.intentos += 1
    decision = suites_operacion.como_reintentar(
        codigo=_codigo_de(exc),
        cabecera_reintento=(getattr(exc, "detalle", None) or {}).get("reintentar_en"),
        intento=operacion.intentos,
    )
    traza.resultado = "error"
    traza.error = f"{exc.error_code}: {exc.mensaje}"[:2000]
    traza.duracion_ms = int((time.perf_counter() - inicio) * 1000)
    uow.db.add(traza)

    operacion.ultimo_error = traza.error
    if decision["reintentar"]:
        espera = int(decision.get("esperar_s") or 60)
        operacion.pausada_hasta = _ahora() + timedelta(seconds=espera)
        operacion.proxima_at = operacion.pausada_hasta
    else:
        # No se reintenta, pero tampoco se desactiva sola: desactivarla la
        # esconde del panel, y lo que hay que hacer con un permiso que falta es
        # enseñarlo. Se aparta a la cadencia normal y el error queda a la vista.
        operacion.pausada_hasta = None
        operacion.proxima_at = _ahora() + timedelta(minutes=max(1, operacion.cada_minutos))
    uow.db.flush()
    logger.warning(
        "integracion.ejecucion_fallida",
        operacion=operacion.clave,
        intento=operacion.intentos,
        reintentar=decision["reintentar"],
        error=traza.error,
    )
    return {
        "operacion": operacion.clave,
        "resultado": "error",
        "error": traza.error,
        "decision": decision,
    }


# ── La vuelta completa, que es lo que llama el relevo ──────────────────────


def una_vuelta(tenant_id: UUID) -> dict[str, Any]:
    """Todo lo que toca de un tenant, aislando cada operación.

    **Una operación que revienta no puede parar a las demás del mismo tenant.**
    Es la misma razón por la que un tenant que falla no para a los siguientes, un
    escalón más abajo: con una sola transacción para todas, la que falla se
    lleva por delante lo que las otras acababan de traer.
    """
    from crmcore.db.uow import unidad_de_trabajo

    with unidad_de_trabajo(tenant_id, sistema=True) as uow:
        cuales = [o.id for o in pendientes(uow.db, tenant_id)]
    hechas, fallidas = 0, []
    for operacion_id in cuales:
        try:
            with unidad_de_trabajo(tenant_id, sistema=True) as uow:
                fila = uow.db.get(Operacion, operacion_id)
                if fila is None:
                    continue
                ejecutar_programada(uow, fila)
            hechas += 1
        except Exception as exc:  # noqa: BLE001 — aislar y seguir
            fallidas.append(
                {"operacion": str(operacion_id), "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
            )
    if fallidas:
        logger.error("integracion.operaciones_fallidas", cuantas=len(fallidas), detalle=fallidas)
    return {"pendientes": len(cuales), "hechas": hechas, "fallidas": fallidas}


def tenants_con_programacion() -> list[UUID]:
    """Los tenants que tienen algo programado, de **su propia tabla**.

    No se le pide la lista de tenants a `tenancy`: es de otro servicio y no se
    lee desde aquí. Además la lista buena es más corta — la mayoría no tienen
    ninguna operación programada.
    """
    from crmcore.db.session import sesion

    with sesion(sistema=True) as db:
        return [
            t
            for (t,) in db.execute(
                select(Operacion.tenant_id)
                .where(Operacion.activa.is_(True), Operacion.cada_minutos > 0)
                .distinct()
            ).all()
        ]


def purgar_registros(db: Any, *, dias: int) -> int:
    """Tira los registros recibidos ya procesados que han cumplido su plazo.

    Lo que entra por una integración es una copia de datos de un sistema ajeno.
    Guardarla sin plazo es acumular datos personales de los que no somos
    responsables, y es lo que convierte una tabla de paso en un segundo maestro
    que nadie mantiene.
    """
    from sqlalchemy import delete

    corte = _ahora() - timedelta(days=max(1, int(dias)))
    borrados = db.execute(
        delete(RegistroRecibido).where(
            RegistroRecibido.estado != "recibido", RegistroRecibido.created_at < corte
        )
    ).rowcount
    return int(borrados or 0)
