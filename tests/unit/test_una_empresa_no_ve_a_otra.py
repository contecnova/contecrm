"""Auditoría del aislamiento entre empresas y de la puerta por la que se entra.

Nueve capacidades sin ninguna prueba que las nombre, de cuatro familias que en
realidad cuentan una sola cosa: **dónde viven los datos de cada cliente, qué
impide que se crucen, y por dónde se entra**.

  · **el aislamiento declarado y comprobado** (CRM-00.01.01.03, .05): un CRM
    multi-tenant se vende con la frase «sus datos están aislados». Lo que pasa
    siempre es que se vende una base dedicada, alguien aprovisiona con la
    plantilla de siempre y el cliente acaba en el pool compartido. Funcionar
    funciona igual, y se descubre el día de la auditoría;
  · **la prohibición estructural** (CRM-00.01.02.03): el filtro de tenant no se
    escribe a mano en cada consulta. Si dependiera de acordarse, el aislamiento
    sería tan bueno como el peor despiste;
  · **el acceso de soporte** (CRM-00.01.02.06): entrar en los datos de un
    cliente es legítimo y tiene que doler un poco — motivo escrito, caducidad
    corta y constancia **en la auditoría del cliente**, no en la nuestra;
  · **los identificadores opacos** (CRM-00.01.02.07): con ids secuenciales, el
    aislamiento depende por entero de que la comprobación de permisos sea
    perfecta en todos y cada uno de los endpoints;
  · **la puerta** (CRM-00.02.04.01, .02, .07): el gateway resuelve el tenant,
    firma la identidad y propaga la traza. Lo que se mide aquí es lo que pasa
    cuando alguien manda a mano las cabeceras que el gateway usa por dentro;
  · y **la propiedad de los datos por servicio** (CRM-00.03.01.02).

Queda fuera, medido y sin construir: **CRM-00.01.01.06**, los pools de cómputo
dedicados. Ver la nota de catálogo de esa capacidad.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

# Su asunto ES el aislamiento, así que corre en cada push y no sólo en el pase
# completo: un fallo aquí no es un detalle que pueda esperar al bloque, es una
# empresa viendo los datos de otra. Mide 3,5 s.
pytestmark = [pytest.mark.db, pytest.mark.despliegue]


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> Any:
    from crmcore.db.uow import UnidadDeTrabajo

    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


# ── CRM-00.01.01.03 · Aislamiento físico, declarado y contrastado ─────────


def test_una_base_dedicada_sin_decir_cual_no_se_declara_crm_00_01_01_03(
    uow: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Declarar no es tener, pero una declaración que ni siquiera dice **dónde**
    no se puede contrastar nunca. Y una declaración que nadie contrasta es una
    promesa comercial dentro de una tabla."""
    from crmcore.errors import ErrorValidacion

    from services.tenancy import aislamiento as ais

    with pytest.raises(ErrorValidacion) as fallo:
        ais.declarar(uow, tenant_id=tenant_id, modalidad="base")
    assert fallo.value.error_code == "aislamiento.sin_base"

    with pytest.raises(ErrorValidacion):
        ais.declarar(uow, tenant_id=tenant_id, modalidad="esquema")


def test_lo_declarado_se_contrasta_con_la_conexion_real_crm_00_01_01_03(
    uow: Any, db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """**Es la función que justifica el módulo entero.** Se le pregunta a la
    propia conexión a qué base está atada y se contrasta con lo declarado. Sin
    esto, «tiene base dedicada» es lo que alguien escribió en una tabla el día
    del alta, y nadie ha vuelto a mirarlo.
    """
    from services.tenancy import aislamiento as ais

    ais.declarar(uow, tenant_id=tenant_id, modalidad="base", base="la-que-no-es")
    db.flush()

    salida = ais.comprobar(uow, tenant_id=tenant_id)
    assert salida["cuadra"] is False, salida
    assert salida["base_declarada"] == "la-que-no-es"
    assert salida["base_real"] and salida["base_real"] != "la-que-no-es"
    assert any("la-que-no-es" in p for p in salida["problemas"]), salida["problemas"]
    # Y dice qué significa, que es lo que convierte el informe en una decisión:
    # esto no se arregla cambiando la declaración.
    assert "NO es lo que hay" in salida["que_significa"]


def test_declarar_de_nuevo_invalida_la_comprobacion_anterior_crm_00_01_01_03(
    uow: Any, db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """**Una comprobación que sobrevive al cambio de lo comprobado es peor que
    ninguna**: sigue diciendo «sí» en verde sobre una declaración que ya no es
    la misma, y quien la mire se quedará tranquilo."""
    from services.tenancy import aislamiento as ais

    fila = ais.declarar(uow, tenant_id=tenant_id, modalidad="compartido")
    db.flush()
    ais.comprobar(uow, tenant_id=tenant_id)
    assert fila.comprobado_at is not None

    ais.declarar(uow, tenant_id=tenant_id, modalidad="base", base="otra")
    db.flush()
    assert fila.comprobado_at is None
    assert fila.comprobado_ok is None


def test_un_tenant_sin_declarar_no_se_da_por_bueno_crm_00_01_01_03(
    uow: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """No se puede comprobar si está donde tenía que estar porque nadie ha dicho
    dónde era. Contestar «cuadra» ahí sería dar por buena la ausencia de
    declaración, que es justo el caso del cliente que se aprovisionó con la
    plantilla de siempre."""
    from crmcore.errors import NoEncontrado

    from services.tenancy import aislamiento as ais

    with pytest.raises(NoEncontrado) as fallo:
        ais.comprobar(uow, tenant_id=tenant_id)
    assert fallo.value.error_code == "aislamiento.no_declarado"


# ── CRM-00.01.01.05 · La base la pone el cliente ──────────────────────────


def test_la_base_del_cliente_hay_que_marcarla_crm_00_01_01_05(
    uow: Any, db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Marcarlo **cambia de quién es la copia de seguridad y a quién se le pide
    el acceso cuando hay una incidencia**. Una base del cliente sin marcar es
    una base que creemos nuestra el día que hay que restaurarla."""
    from crmcore.errors import ErrorValidacion

    from services.tenancy import aislamiento as ais

    with pytest.raises(ErrorValidacion) as fallo:
        ais.declarar(uow, tenant_id=tenant_id, modalidad="cliente", base="la-suya")
    assert fallo.value.error_code == "aislamiento.cliente_sin_marcar"

    fila = ais.declarar(
        uow,
        tenant_id=tenant_id,
        modalidad="cliente",
        base="la-suya",
        infraestructura_del_cliente=True,
    )
    db.flush()
    assert fila.infraestructura_del_cliente is True


def test_el_tier_no_inventa_modalidad_para_uno_desconocido_crm_00_01_01_05() -> None:
    """Un plan que no está en la tabla cae a «compartido», que es lo que de
    verdad tiene: inventarle «base» a un tier desconocido sería prometer por
    defecto lo que más cuesta."""
    from services.tenancy import aislamiento as ais

    assert ais.modalidad_de_tier("enterprise") == "base"
    assert ais.modalidad_de_tier("un-plan-que-no-existe") == "compartido"


# ── CRM-00.01.02.03 · Nada de consultas sin predicado de tenant ───────────


def test_el_filtro_de_tenant_no_se_escribe_a_mano_crm_00_01_02_03(
    db: Any, tenant_id: UUID, otro_tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """La consulta de abajo **no lleva ningún `where tenant_id`** y aun así no
    ve lo del vecino: lo inyecta el guard del ORM. Si dependiera de acordarse,
    el aislamiento sería tan bueno como el peor despiste de la peor tarde.
    """
    from crmcore.tenancy.guard import instalar_guard
    from sqlalchemy import select

    from services.metadata.modelos import ObjetoDefinido

    # Lo instala la factoría de servicio al arrancar cada proceso; aquí se llama
    # a mano porque esta prueba no levanta ninguno. Es idempotente.
    instalar_guard()

    db.add(ObjetoDefinido(tenant_id=otro_tenant_id, nombre="suyo", etiqueta="Suyo"))
    db.add(ObjetoDefinido(tenant_id=tenant_id, nombre="mio", etiqueta="Mio"))
    db.flush()
    db.expire_all()

    # El tenant de la sesión es lo que mira el guard, y lo pone `nueva_sesion`
    # al abrirla. Aquí se pone a mano —y se quita la marca de sistema, que la
    # sesión del arnés lleva puesta— porque lo que se mide es el guard, no
    # quién le da el dato.
    db.info["sistema"] = False
    db.info["tenant_id"] = tenant_id
    try:
        nombres = {o.nombre for o in db.execute(select(ObjetoDefinido)).scalars().all()}
    finally:
        db.info["sistema"] = True
        db.info["tenant_id"] = None
    assert nombres == {"mio"}, nombres

    # Y el camino de sistema sigue abierto, porque alguna consulta cross-tenant
    # legítima hay —una purga, un informe de plataforma—: lo que cambia es que
    # hay que **escribirlo**, y entonces se ve en la revisión.
    todos = {o.nombre for o in db.execute(select(ObjetoDefinido)).scalars().all()}
    assert todos == {"mio", "suyo"}, todos


def test_toda_tabla_con_tenant_queda_dentro_de_la_red_crm_00_01_02_03() -> None:
    """La red sólo vale si no tiene punto ciego. Cada exención es un agujero que
    alguien tendrá que recordar dentro de dos años, así que son una lista
    cerrada y con motivo — y hoy es **una**, el propio tenant, que no se puede
    filtrar por sí mismo sin dejar de poder resolverlo."""
    from crmcore.tenancy.guard import MODELOS_EXENTOS

    assert MODELOS_EXENTOS == frozenset({"Tenant"}), sorted(MODELOS_EXENTOS)


# ── CRM-00.01.02.06 · El acceso de soporte a los datos de un cliente ──────


@pytest.fixture
def soporte_y_cliente(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> Any:
    """Alguien de plataforma y alguien del cliente, los dos en la base."""
    from services.identity.modelos import Usuario

    soporte = Usuario(
        email="soporte@plataforma.example",
        nombre="Soporte",
        es_plataforma=True,
        activo=True,
    )
    cliente = Usuario(
        email="comercial@cliente.example",
        nombre="Comercial",
        activo=True,
    )
    db.add_all([soporte, cliente])
    db.flush()
    return soporte, cliente


def test_soporte_no_entra_sin_motivo_escrito_crm_00_01_02_06(
    db: Any, tenant_id: UUID, soporte_y_cliente: Any, contexto_tenant: UUID
) -> None:
    """**Sin motivo no hay nada que revisar después.** Las tres condiciones
    —motivo, caducidad corta y auditoría— sostienen esto juntas: quitar
    cualquiera lo convierte en una puerta trasera con buena intención."""
    from crmcore.errors import ErrorValidacion, Prohibido

    from services.identity import servicio as svc

    soporte, cliente = soporte_y_cliente

    with pytest.raises(ErrorValidacion) as fallo:
        svc.suplantar(db, soporte=soporte, usuario_id=cliente.id, tenant_id=tenant_id, motivo="  ")
    assert fallo.value.error_code == "auth.suplantacion_sin_motivo"

    # Y no es cosa de cualquier administrador del cliente: sólo personal de
    # plataforma. Un administrador del tenant que pudiera suplantar tendría una
    # forma de leer el correo de su propio equipo sin dejar rastro de persona.
    soporte.es_plataforma = False
    db.flush()
    with pytest.raises(Prohibido):
        svc.suplantar(
            db, soporte=soporte, usuario_id=cliente.id, tenant_id=tenant_id, motivo="ticket 42"
        )


def test_el_acceso_de_soporte_consta_en_la_auditoria_del_cliente_crm_00_01_02_06(
    db: Any, tenant_id: UUID, soporte_y_cliente: Any, contexto_tenant: UUID
) -> None:
    """**En la del cliente, no en la nuestra.** Si constara sólo de nuestro lado,
    el cliente no podría saber quién entró en sus datos, que es exactamente lo
    que hace falta poder contestar cuando lo pregunta."""
    from crmcore.audit.modelos import ApunteAuditoria
    from sqlalchemy import select

    from services.identity import servicio as svc

    soporte, cliente = soporte_y_cliente
    svc.suplantar(
        db,
        soporte=soporte,
        usuario_id=cliente.id,
        tenant_id=tenant_id,
        motivo="incidencia 4711: no le cargan las oportunidades",
    )
    db.flush()

    entradas = (
        db.execute(
            select(ApunteAuditoria).where(
                ApunteAuditoria.tenant_id == tenant_id,
                ApunteAuditoria.accion == "soporte.acceso_tenant",
            )
        )
        .scalars()
        .all()
    )
    assert len(entradas) == 1, "el acceso de soporte no queda en la auditoría del cliente"
    assert "4711" in (entradas[0].motivo or ""), entradas[0].motivo
    assert str(soporte.id) in str(entradas[0].datos), entradas[0].datos


# ── CRM-00.01.02.07 · Identificadores opacos ──────────────────────────────


def test_los_identificadores_no_se_pueden_adivinar_crm_00_01_02_07() -> None:
    """**Quien ve `/accounts/1043` prueba `1044`.** Con un id secuencial, el
    aislamiento entre tenants depende por entero de que la comprobación de
    permisos sea perfecta en todos y cada uno de los endpoints; con uno opaco,
    la comprobación pasa a ser la segunda red en vez de la única.
    """
    from crmcore.ids import nuevo_id

    ids = [nuevo_id() for _ in range(200)]
    assert all(i.version == 7 for i in ids), "hay identificadores que no son UUIDv7"
    assert len(set(ids)) == 200

    # Lo que importa no es que sean distintos —dos enteros seguidos también lo
    # son— sino que del uno no se llegue al siguiente. Entre dos consecutivos
    # hay que recorrer un espacio enorme.
    saltos = [abs(int(b) - int(a)) for a, b in zip(ids, ids[1:], strict=False)]
    assert min(saltos) > 2**40, min(saltos)


def test_el_identificador_ordena_por_antiguedad_crm_00_01_02_07() -> None:
    """La otra mitad, y la razón de v7 en vez de v4: la marca de tiempo va en
    los bits altos, así que ordenan por antigüedad y no fragmentan los índices.
    Un identificador opaco **y** desordenado se paga en cada escritura."""
    import time

    from crmcore.ids import nuevo_id

    antes = nuevo_id()
    time.sleep(0.01)
    despues = nuevo_id()
    assert int(antes) < int(despues)


# ── CRM-00.02.04.02 · Por qué vía se resuelve el tenant ───────────────────


def test_una_pista_que_contradice_al_token_se_rechaza_crm_00_02_04_02() -> None:
    """**Sin esta comprobación bastaría cambiar una cabecera para operar sobre
    otro tenant con un token legítimo.** Es la vía más barata que existe para
    saltarse el aislamiento: no hace falta robar nada, sólo escribir otro
    nombre."""
    from crmcore.errors import Prohibido
    from crmcore.tenancy.resolver import conciliar

    mio, suyo = uuid4(), uuid4()
    with pytest.raises(Prohibido) as fallo:
        conciliar(
            del_token=mio,
            de_api_key=None,
            pista_slug="la-de-al-lado",
            resolver_slug=lambda _s: suyo,
        )
    assert fallo.value.error_code == "tenancy.pista_contradictoria"
    # Y la respuesta no confirma que ese tenant exista: decir «ese tenant existe
    # pero no es el tuyo» ya es decir de más.
    assert str(suyo) not in str(fallo.value)


def test_una_pista_sola_no_concede_acceso_crm_00_02_04_02() -> None:
    """La cabecera y el subdominio son **enrutado**, no identidad: sirven para
    elegir la marca de la pantalla de entrada o saber a qué proveedor mandar a
    quien aún no se ha autenticado. Si bastaran por sí solas, entrar en
    cualquier tenant sería escribir su nombre."""
    from crmcore.tenancy.resolver import conciliar

    suyo = uuid4()
    salida = conciliar(
        del_token=None, de_api_key=None, pista_slug="acme", resolver_slug=lambda _s: suyo
    )
    assert salida.tenant_id == suyo
    assert salida.via == "cabecera"
    assert salida.es_autoritativa is False

    # El token y la clave de API sí, porque van firmadas o pertenecen a un
    # tenant concreto en la base.
    for kw in ({"del_token": suyo}, {"de_api_key": suyo}):
        base = {"del_token": None, "de_api_key": None, **kw}
        assert conciliar(**base, pista_slug="", resolver_slug=lambda _s: None).es_autoritativa


def test_el_subdominio_no_se_deduce_de_un_host_cualquiera_crm_00_02_04_02() -> None:
    """Sin dominio raíz configurado no se deduce nada: deducir un tenant de un
    `Host` arbitrario convertiría **cualquier cabecera `Host`** en una vía de
    enrutado no prevista. Y `www`, `api` y `app` no son tenants."""
    from crmcore.tenancy.resolver import pista_por_host

    assert pista_por_host("acme.contecrm.app", "contecrm.app") == "acme"
    assert pista_por_host("acme.contecrm.app:8443", "contecrm.app") == "acme"
    assert pista_por_host("acme.contecrm.app", "") == ""
    assert pista_por_host("acme.otra-cosa.example", "contecrm.app") == ""
    for servicio in ("www", "api", "app"):
        assert pista_por_host(f"{servicio}.contecrm.app", "contecrm.app") == ""


# ── CRM-00.02.04.01 · La puerta: identidad firmada, no reenviada ──────────


def _captura(destino: list[dict[str, str]]) -> Any:
    """Cliente HTTP que no sale a ninguna parte y anota lo que se le pidió."""
    import httpx

    def _responder(peticion: httpx.Request) -> httpx.Response:
        destino.append({k.lower(): v for k, v in peticion.headers.items()})
        return httpx.Response(200, json={})

    return httpx.AsyncClient(transport=httpx.MockTransport(_responder))


def test_las_cabeceras_de_identidad_que_llegan_de_fuera_no_pasan_crm_00_02_04_01() -> None:
    """**Es el agujero que la firma viene a cerrar.** Quien llama manda
    `x-crm-tenant` con el identificador de otra empresa y `x-crm-permisos` con
    todos los permisos del mundo; lo que llega al servicio de detrás tiene que
    ser lo que el gateway resolvió, no lo que pidió el cliente.
    """
    import asyncio
    from types import SimpleNamespace

    from services.gateway import proxy

    mio, suyo = uuid4(), uuid4()
    principal = SimpleNamespace(
        tenant_id=mio,
        id=uuid4(),
        tipo="persona",
        permisos={"cuentas:read"},
        roles={"comercial"},
        scopes=set(),
        actor_real_id=None,
        es_admin_plataforma=False,
        sesion_id=uuid4(),
        factor_fuerte_at="",
    )
    vistas: list[dict[str, str]] = []

    async def _correr() -> None:
        async with _captura(vistas) as cliente:
            await proxy.reenviar(
                cliente,
                url_base="http://servicio",
                metodo="GET",
                ruta="/api/v1/cuentas",
                query="",
                cabeceras={
                    # Todo lo que un atacante probaría, en minúsculas como las
                    # entrega Starlette.
                    "x-crm-tenant": str(suyo),
                    "x-crm-permisos": "*",
                    "x-crm-plataforma": "1",
                    "x-crm-tipo": "maquina",
                    "x-crm-sesion": str(uuid4()),
                    "x-crm-factor-fuerte": "9999999999",
                    "x-crm-firma": "la-que-sea",
                    "accept": "application/json",
                },
                cuerpo=b"",
                identidad=proxy.cabeceras_de_identidad(principal, "un-secreto"),
                timeout_s=5.0,
            )

    asyncio.run(_correr())
    assert vistas, "no ha salido ninguna petición"
    salieron = vistas[0]
    assert salieron["x-crm-tenant"] == str(mio), "ha pasado el tenant del cliente"
    assert salieron["x-crm-permisos"] == "cuentas:read"
    assert salieron["x-crm-plataforma"] == ""
    assert salieron["x-crm-tipo"] == "persona"
    assert salieron["x-crm-factor-fuerte"] == ""
    assert salieron["x-crm-firma"] != "la-que-sea"
    # Lo que no es de identidad sí pasa: el gateway no es un filtro de la API.
    assert salieron["accept"] == "application/json"


def test_la_firma_interna_no_se_sostiene_sin_el_secreto_crm_00_02_04_01() -> None:
    """La contrapartida dicha en claro: si un servicio interno fuera alcanzable
    desde fuera, cualquiera podría mandarle estas cabeceras. **Lo que lo impide
    sin el secreto es la firma** — cambiar un solo valor la rompe."""
    from crmcore.http.deps import H_FIRMA, H_TENANT, firmar_cabeceras_internas

    uno = firmar_cabeceras_internas({H_TENANT: "a"}, "secreto")
    otro = firmar_cabeceras_internas({H_TENANT: "b"}, "secreto")
    con_otra_clave = firmar_cabeceras_internas({H_TENANT: "a"}, "otro-secreto")

    assert uno[H_FIRMA] != otro[H_FIRMA], "la firma no cubre el tenant"
    assert uno[H_FIRMA] != con_otra_clave[H_FIRMA], "la firma no depende del secreto"


# ── CRM-00.02.04.07 · La traza de punta a punta ───────────────────────────


def test_el_identificador_de_peticion_vuelve_siempre_crm_00_02_04_07() -> None:
    """Sin esto, «me ha fallado algo a las once y diez» no se puede buscar.
    Vuelve en la respuesta **se haya mandado o no**: si sólo volviera cuando el
    cliente lo manda, el soporte dependería de que cada integración se acordara
    de generarlo."""
    from crmcore.service import crear_servicio
    from starlette.testclient import TestClient

    app = crear_servicio(
        nombre="pruebas-traza",
        descripcion="traza de punta a punta",
        routers=[],
        necesita_db=False,
        necesita_bus=False,
    )
    with TestClient(app) as cliente:
        sin_pedir = cliente.get("/health/live")
        assert sin_pedir.headers.get("x-request-id"), sin_pedir.headers

        mio = "el-mio-de-soporte"
        con_el_mio = cliente.get("/health/live", headers={"x-request-id": mio})
        # **El del cliente se respeta.** Generar uno nuevo rompería el único
        # hilo que une lo que él ve con lo que nosotros registramos.
        assert con_el_mio.headers.get("x-request-id") == mio


def test_el_traceparent_del_que_llama_se_conserva_crm_00_02_04_07() -> None:
    """W3C Trace Context, que es lo que entienden las herramientas de todos.
    **Un `trace_id` que se reinicia en nuestra puerta deja la mitad del viaje
    sin unir**: lo que el cliente ve en su herramienta y lo que nosotros vemos
    en la nuestra pasan a ser dos sucesos distintos."""
    from crmcore.service import crear_servicio
    from starlette.testclient import TestClient

    app = crear_servicio(
        nombre="pruebas-traceparent",
        descripcion="traza de punta a punta",
        routers=[],
        necesita_db=False,
        necesita_bus=False,
    )
    suyo = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    with TestClient(app) as cliente:
        salida = cliente.get("/health/live", headers={"traceparent": suyo})
    devuelto = salida.headers.get("traceparent", "")
    assert devuelto, salida.headers
    # El tramo puede ser otro —es otro tramo—, pero la traza es la misma.
    assert devuelto.split("-")[1] == suyo.split("-")[1], devuelto


# ── Quien opera la plataforma tampoco, salvo donde se dice ────────────────


def test_un_admin_de_plataforma_no_ve_lo_de_otro_cliente_en_una_pantalla_normal() -> None:
    """La sesión la decide la RUTA, no quién la pide.

    Hasta el 27-10-2026 era `principal.es_admin_plataforma` a secas, y eso
    convertía todas las pantallas de negocio en una vista global: quien opera
    la plataforma abría «Cuentas» y veía las de ocho clientes mezcladas, sin
    saberlo y sin nada en la pantalla que lo dijera. Medido contra la
    instalación local: **97 de 100 cuentas eran de otro cliente**, 100 de 100
    contactos, 100 de 100 oportunidades.

    No lo cazaba nada: todos los casos de este fichero usan
    `es_admin_plataforma=False`, que es justo el que no tenía el problema. Lo
    destapó el sembrado, al pedir las cuentas, recibir las de otro cliente y
    oír del servidor —con razón— que esa cuenta no existe.
    """
    from types import SimpleNamespace
    from uuid import uuid4

    from crmcore.http.deps import _cruza_tenants, tenant_mirado

    mio = uuid4()
    operador = SimpleNamespace(es_admin_plataforma=True, tenant_id=mio)

    class _Peticion:
        def __init__(self, ruta: Any, cabeceras: dict[str, str] | None = None) -> None:
            self.scope = {"route": ruta}
            self.headers = cabeceras or {}

    # Una ruta de negocio: no cruza, aunque quien la pida opere la plataforma.
    de_negocio = SimpleNamespace(dependant=SimpleNamespace(dependencies=[]))
    assert _cruza_tenants(_Peticion(de_negocio), operador) is False
    assert tenant_mirado(_Peticion(de_negocio), operador) == mio

    # Una que declara `exige_plataforma` —dar de alta un tenant, el panel de
    # aislamiento— sí: es para lo que existe.
    from crmcore.http.deps import exige_plataforma

    de_plataforma = SimpleNamespace(
        dependant=SimpleNamespace(
            dependencies=[SimpleNamespace(call=exige_plataforma, dependencies=[])]
        )
    )
    assert _cruza_tenants(_Peticion(de_plataforma), operador) is True


def test_mirar_los_datos_de_un_cliente_hay_que_pedirlo_y_sólo_puede_la_plataforma() -> None:
    """Y un valor ilegible NO se interpreta como «todos».

    Lo contrario convertiría una cabecera mal escrita en una vista global, que
    es exactamente el fallo del que se viene.
    """
    from types import SimpleNamespace
    from uuid import uuid4

    from crmcore.http.deps import H_TENANT_MIRADO, tenant_mirado

    mio, otro = uuid4(), uuid4()
    operador = SimpleNamespace(es_admin_plataforma=True, tenant_id=mio)
    de_empresa = SimpleNamespace(es_admin_plataforma=False, tenant_id=mio)

    class _Peticion:
        def __init__(self, valor: str) -> None:
            self.scope = {"route": None}
            self.headers = {H_TENANT_MIRADO: valor}

    assert tenant_mirado(_Peticion(str(otro)), operador) == otro
    # A quien no opera la plataforma la cabecera no le concede nada: mandarla
    # no le mueve de su tenant.
    assert tenant_mirado(_Peticion(str(otro)), de_empresa) == mio
    # Y lo ilegible cae a lo suyo, no a todos.
    assert tenant_mirado(_Peticion("no-es-un-uuid"), operador) == mio
    assert tenant_mirado(_Peticion(""), operador) == mio


# ── El caso de verdad: un cliente dado de alta y visto desde fuera ────────
#
# Las dos pruebas de arriba miran las FUNCIONES que deciden —`_cruza_tenants` y
# `tenant_mirado`—, y eso deja un hueco con forma de fallo real: siguen pasando
# aunque `get_db` deje de llamarlas, que es exactamente donde vivía la fuga. Y
# el barrido de `test_fuzzing_tenant` recorre las fichas, no los LISTADOS, que
# es donde se vio: «Cuentas» con las de ocho clientes mezcladas.
#
# Así que aquí se planta el caso entero y se pide por la ruta: una cuenta en el
# tenant A, cuatro formas de pedirla desde el B, y la única que la enseña es la
# que existe para eso.
#
# **Y lo que esto NO prueba, dicho aquí para que nadie lo dé por probado:** la
# RLS. El arnés conecta como SUPERUSER —el propio arranque lo grita:
# `arranque.rls_sin_garantia`— y Postgres se salta Row-Level Security para un
# superusuario pase lo que pase. O sea que lo que se mide aquí es la PRIMERA
# red, la que pone la aplicación. La segunda —la que sigue puesta el día que
# alguien escriba una consulta a mano— no la puede medir ninguna prueba de esta
# suite, y por eso se mide contra el despliegue vivo con
# `scripts/de_quien_son_las_filas.py`, que se pone en el sitio de un cliente y
# cuenta las filas ajenas que ve.


def _cabeceras_de(
    tenant_id: UUID, *, plataforma: bool = False, mirando: UUID | None = None
) -> dict[str, str]:
    from crmcore.config import get_settings
    from crmcore.http.deps import (
        H_PERMISOS,
        H_PLATAFORMA,
        H_TENANT,
        H_TENANT_MIRADO,
        firmar_cabeceras_internas,
    )

    # `*:*` a propósito: con permisos justos, un 403 por falta de permiso
    # taparía un aislamiento roto y la prueba pasaría por el motivo equivocado.
    cabeceras = {H_TENANT: str(tenant_id), "x-crm-user": str(uuid4()), H_PERMISOS: "*:*"}
    if plataforma:
        cabeceras[H_PLATAFORMA] = "1"
    firmadas = firmar_cabeceras_internas(cabeceras, get_settings().secret_key.get_secret_value())
    # La cabecera de «qué cliente estoy mirando» va FUERA de la firma, igual
    # que la manda el navegador: si se firmara aquí, la prueba mediría una
    # petición que nadie hace.
    if mirando is not None:
        firmadas[H_TENANT_MIRADO] = str(mirando)
    return firmadas


# Una sola vez por fichero: arrancar un servicio cuesta un par de segundos y
# aquí se arrancaba por prueba. Lo que se mide no es el arranque.
@pytest.fixture(scope="module")
def cliente_party() -> Any:
    import importlib
    import os

    from crmcore.config import get_settings
    from starlette.testclient import TestClient

    previo = {k: os.environ.get(k) for k in ("OUTBOX_ENABLED", "TAREAS_FONDO_ENABLED")}
    os.environ["OUTBOX_ENABLED"] = "false"
    os.environ["TAREAS_FONDO_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        app = importlib.import_module("services.party.main").app
        with TestClient(app) as cli:
            yield cli
    finally:
        for clave, valor in previo.items():
            if valor is None:
                os.environ.pop(clave, None)
            else:
                os.environ[clave] = valor
        get_settings.cache_clear()


def _ids(respuesta: Any) -> list[str]:
    """Los identificadores, **no los nombres**.

    Medido al escribir esto: el listado devuelve «··cosa» en vez de «Ficosa»
    —lo tapa la política de campo—, así que una comprobación por nombre daba
    «Ficosa no está» en los cuatro casos y la prueba pasaba entera por el
    motivo equivocado, incluido el caso que TIENE que verla. El identificador
    no lo tapa nada.
    """
    datos = respuesta.json()
    filas = datos if isinstance(datos, list) else (datos.get("items") or [])
    return [str(f.get("id") or "") for f in filas]


@pytest.mark.despliegue
def test_una_cuenta_de_un_cliente_no_sale_en_el_listado_de_otro(
    cliente_party: Any, db: Any, tenant_id: UUID, otro_tenant_id: UUID
) -> None:
    """El caso tal cual se dio: una empresa dada de alta en un tenant, buscada
    desde otro. Y en el LISTADO, que es donde se vio y donde el barrido de
    fichas no mira.

    Las cuatro formas de pedirlo, porque el aislamiento se rompe por una sola:

      1. un usuario normal del otro cliente — no la ve;
      2. **quien opera la plataforma**, desde su propio tenant, en una pantalla
         de negocio — tampoco. Éste es el que estaba roto: `get_db` abría la
         sesión con `sistema=True` para cualquier ruta, y eso salta la RLS;
      3. quien opera la plataforma **pidiendo mirar** ese cliente — sí, que es
         para lo que existe la cabecera y por eso la barra lo avisa en ámbar;
      4. un usuario normal mandando esa misma cabecera a mano — no: la
         cabecera no concede nada a quien no opera la plataforma.
    """
    from services.party.modelos import Cuenta

    ficosa = Cuenta(tenant_id=tenant_id, nombre="Ficosa", clave_canonica="ficosa")
    db.add(ficosa)
    db.flush()
    suya = str(ficosa.id)

    # 1. Otro cliente, usuario normal.
    ajeno = cliente_party.get("/api/v1/accounts", headers=_cabeceras_de(otro_tenant_id))
    assert ajeno.status_code == 200, ajeno.text
    assert suya not in _ids(ajeno)

    # 2. Quien opera la plataforma, en una pantalla de negocio. El que se rompió.
    operador = cliente_party.get(
        "/api/v1/accounts", headers=_cabeceras_de(otro_tenant_id, plataforma=True)
    )
    assert operador.status_code == 200, operador.text
    assert suya not in _ids(operador), (
        "La cuenta de otro cliente sale en una pantalla de negocio de quien "
        "opera la plataforma. Es la fuga del 27-10-2026: la sesión la tiene "
        "que decidir la RUTA, no quién la pide."
    )

    # 3. Pidiendo mirar ese cliente, a propósito.
    mirando = cliente_party.get(
        "/api/v1/accounts",
        headers=_cabeceras_de(otro_tenant_id, plataforma=True, mirando=tenant_id),
    )
    assert mirando.status_code == 200, mirando.text
    assert suya in _ids(mirando), (
        "Mirar a un cliente a propósito tiene que funcionar: si no, quien "
        "opera la plataforma no puede dar soporte y acabará pidiendo que se "
        "le devuelva la vista global."
    )

    # 4. Y la misma cabecera en manos de quien no opera la plataforma.
    colado = cliente_party.get(
        "/api/v1/accounts", headers=_cabeceras_de(otro_tenant_id, mirando=tenant_id)
    )
    assert colado.status_code == 200, colado.text
    assert suya not in _ids(
        colado
    ), "Una cabecera que cualquiera puede escribir le ha movido de tenant."


@pytest.mark.despliegue
def test_y_el_de_siempre_sigue_viendo_lo_suyo(cliente_party: Any, db: Any, tenant_id: UUID) -> None:
    """La otra mitad, y no es de adorno: un aislamiento que no deja ver NADA
    también pasa las cuatro comprobaciones de arriba. Sin esto, romper el
    listado entero se leería como aislamiento perfecto."""
    from services.party.modelos import Cuenta

    ficosa = Cuenta(tenant_id=tenant_id, nombre="Ficosa", clave_canonica="ficosa")
    db.add(ficosa)
    db.flush()

    propia = cliente_party.get("/api/v1/accounts", headers=_cabeceras_de(tenant_id))
    assert propia.status_code == 200, propia.text
    assert str(ficosa.id) in _ids(propia)


# ── Y poder preguntárselo al producto (CRM-00.01.02.01 a .05, .07) ────────


def test_el_producto_contesta_que_impide_que_una_empresa_vea_a_otra(db: Any) -> None:
    """La pregunta que abre cualquier auditoría, y que había que responder a mano.

    Todo lo de arriba estaba construido y probado. Lo que no existía es forma
    de preguntarle a una **instalación concreta** si las capas están puestas en
    ella, y esa pregunta no es teórica: el 28-10-2026 se midió contra un
    despliegue vivo que tenía las 623 tablas con `tenant_id` con RLS, FORCE y
    política —esa mitad, completa— y el servicio conectando con un rol
    SUPERUSER, que se salta las políticas aunque estén en FORCE. De las tres
    capas que el manual promete quedaba una. Para enterarse hubo que escribir
    un script y leer `pg_roles` a mano.
    """
    from services.tenancy import aislamiento as ais

    salida = ais.garantias(db)
    claves = {c["clave"] for c in salida["capas"]}
    assert {"motor", "rol", "orm", "contexto"} <= claves, (
        "Faltan capas de las que el manual promete: si una no se mide, la "
        "pantalla tranquiliza sobre algo que nadie ha mirado."
    )
    for capa in salida["capas"]:
        assert capa["detalle"], f"«{capa['clave']}» no dice de dónde sale su número"
        assert capa["porque"], f"«{capa['clave']}» no dice por qué existe"


def test_un_rol_que_se_salta_la_red_no_sale_como_todo_puesto(db: Any) -> None:
    """**El caso que justifica la pantalla.**

    Las pruebas de esta suite corren sobre el Postgres embebido, que es
    superusuario. Eso aquí no es una limitación: es exactamente el caso malo
    que hay que plantar, y por eso se mide contra él. Un veredicto en verde con
    este rol sería una pantalla de garantías que tranquiliza cuando la garantía
    no está, que es peor que no tenerla.
    """
    import sqlalchemy as sa

    from services.tenancy import aislamiento as ais

    se_salta = db.execute(
        sa.text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user")
    ).scalar_one()
    assert se_salta, "Esta prueba necesita el rol que se salta la red para significar algo"

    salida = ais.garantias(db)
    assert salida["rol_se_salta_la_red"] is True
    assert salida["todo_puesto"] is False, (
        "Con un rol que ignora las políticas, contar tablas protegidas da verde "
        "sobre una red desarmada."
    )
    capa = next(c for c in salida["capas"] if c["clave"] == "rol")
    assert capa["ok"] is False
    assert "SUPERUSER" in capa["detalle"] or "BYPASSRLS" in capa["detalle"]
    # Y el motor cae con él: sus políticas no filtran aunque estén todas.
    assert next(c for c in salida["capas"] if c["clave"] == "motor")["ok"] is False


def test_lo_que_no_se_mide_aqui_lo_dice_en_vez_de_darlo_por_bueno(db: Any) -> None:
    """El fuzzing entre tenants es una suite que corre antes de empujar, no algo
    que se pueda consultar en vivo. Pintarlo como comprobado sería inventar una
    medida; decir que es un gate y dónde corre es la respuesta honesta."""
    from services.tenancy import aislamiento as ais

    fuzz = next(c for c in ais.garantias(db)["capas"] if c["clave"] == "fuzzing")
    assert fuzz["medible_aqui"] is False
    assert "pre-push" in fuzz["detalle"]


def test_el_cifrado_se_mide_en_la_conexion_y_no_en_el_ajuste(db: Any) -> None:
    """Un `sslmode` configurado no es un tránsito cifrado.

    La cadena de conexión puede traer el suyo —hay despliegues donde la genera
    el proveedor de la base y no se toca— y entonces el ajuste dice una cosa y
    la conexión hace otra. La que protege es la conexión, así que es la que se
    mide: `pg_stat_ssl` del propio proceso.

    Y un socket de Unix **no sale de la máquina**: exigirle TLS sería pedir
    cifrar una conversación que ocurre dentro de la misma casa, y marcarlo en
    rojo enseñaría a ignorar este panel en todo entorno local — que es como se
    pierde un panel entero.
    """
    import sqlalchemy as sa

    from services.tenancy import aislamiento as ais

    capas = {c["clave"]: c for c in ais.garantias(db)["capas"]}
    assert "transito" in capas, "no se mide el cifrado hasta la base"
    transito = capas["transito"]
    assert transito["detalle"] and transito["porque"]

    # Y que **mira la conexión**: se compara con lo que dice Postgres de este
    # mismo proceso. Si la respuesta saliera del ajuste, estas dos podrían no
    # coincidir y es justo el caso que este panel existe para no tener.
    real = db.execute(
        sa.text("SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()")
    ).scalar_one()
    por_socket = "socket local" in transito["detalle"]
    assert por_socket or (bool(real) is ("TLS activo" in transito["detalle"])), (
        "lo que dice el panel no coincide con lo que dice la conexión: "
        f"panel «{transito['detalle']}», pg_stat_ssl={real}"
    )


def test_el_cifrado_de_campo_distingue_la_clave_del_cliente(db: Any) -> None:
    """Sin clave propia del tenant, los campos sensibles se cifran con la del
    despliegue — que funciona, y hace que revocar sea un problema de todos.
    Decirlo es la diferencia entre «está cifrado» y «está cifrado con la tuya».
    """
    from services.tenancy import aislamiento as ais

    campo = next(c for c in ais.garantias(db)["capas"] if c["clave"] == "campo")
    assert "clave" in campo["detalle"].lower()
    assert "revocar" in campo["porque"] or "revocarla" in campo["porque"]
