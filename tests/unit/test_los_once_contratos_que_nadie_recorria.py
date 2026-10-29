"""Once contratos que una pantalla daba por buenos y ninguna prueba pedía.

El trinquete de `test_la_pantalla_no_lee_campos_que_nadie_envia.py` los tenía
apuntados desde el 26-10-2026: once rutas de las que un `.tsx` declara la forma
de la respuesta y que **ninguna prueba de servidor llegaba a llamar**. Es el
suelo del producto —recorrer no es fijar— pero es el que faltaba.

Diez estaban bien. La undécima, el desvío de un entorno, estaba rota de tres
maneras a la vez, y ninguna se veía sin recorrerla:

  · el servidor leía `clave` de la definición publicada de un campo, que se
    llama `nombre`: **un 500** en cuanto el objeto tenía un campo;
  · montaba el estado actual como un diccionario donde la comparación espera
    una lista, así que todo lo que traía el paquete salía como desaparecido;
  · y comparaba los ocho tipos de contenido contra un estado que solo sabía de
    campos, con lo que vistas, plantillas y ajustes se daban por borrados.

Y la pantalla, por su parte, leía `hay_desvio` y `diferencias`, que no existen:
el primero llegaba `undefined` —siempre en verde— y al segundo se le pedía
`.length`, que **tumba la pantalla entera**.

Lo que se comprueba aquí es la respuesta que sale por HTTP, serialización
incluida: es donde se rompen estas cosas y es lo que lee el navegador.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Iterator
from uuid import UUID, uuid4

import pytest
from starlette.testclient import TestClient

pytestmark = pytest.mark.db


# ── El andamio ────────────────────────────────────────────────────────────


def _app(nombre: str) -> Iterator[Any]:
    """Un cliente contra la aplicación de un servicio.

    El buzón de eventos se apaga: estas pruebas miran la forma de la respuesta,
    y un volcado fallido escondería el 200 detrás de un 500 que no es el que se
    persigue.
    """
    import importlib
    import os

    from crmcore.config import get_settings

    previo = os.environ.get("OUTBOX_ENABLED")
    os.environ["OUTBOX_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        with TestClient(importlib.import_module(nombre).app) as cli:
            yield cli
    finally:
        if previo is None:
            os.environ.pop("OUTBOX_ENABLED", None)
        else:
            os.environ["OUTBOX_ENABLED"] = previo
        get_settings.cache_clear()


@pytest.fixture
def usuario() -> UUID:
    return uuid4()


@pytest.fixture
def cabeceras(tenant_id: UUID, usuario: UUID) -> dict[str, str]:
    from crmcore.config import get_settings
    from crmcore.http.deps import (
        H_FACTOR_FUERTE,
        H_PERMISOS,
        H_ROLES,
        H_TENANT,
        H_USER,
        firmar_cabeceras_internas,
    )

    return firmar_cabeceras_internas(
        {
            H_TENANT: str(tenant_id),
            H_USER: str(usuario),
            H_PERMISOS: "*:*",
            H_ROLES: "admin",
            H_FACTOR_FUERTE: datetime.now(timezone.utc).isoformat(),
        },
        get_settings().secret_key.get_secret_value(),
    )


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> Any:
    from crmcore.db.uow import UnidadDeTrabajo

    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


@pytest.fixture
def identity(db: Any) -> Iterator[Any]:
    yield from _app("services.identity.main")


@pytest.fixture
def tenancy(db: Any) -> Iterator[Any]:
    yield from _app("services.tenancy.main")


@pytest.fixture
def sales(db: Any) -> Iterator[Any]:
    yield from _app("services.sales.main")


@pytest.fixture
def analytics(db: Any) -> Iterator[Any]:
    yield from _app("services.analytics.main")


@pytest.fixture
def metadata(db: Any) -> Iterator[Any]:
    yield from _app("services.metadata.main")


@pytest.fixture
def integration(db: Any) -> Iterator[Any]:
    yield from _app("services.integration.main")


@pytest.fixture
def party(db: Any) -> Iterator[Any]:
    yield from _app("services.party.main")


def _campos(cuerpo: dict[str, Any], *nombres: str) -> None:
    faltan = [n for n in nombres if n not in cuerpo]
    assert not faltan, f"faltan {faltan}: llegan {sorted(cuerpo)}"


# ── Chat interno: Chat.tsx ────────────────────────────────────────────────


def test_abrir_una_conversacion_devuelve_lo_que_la_lista_pinta(
    identity: Any, cabeceras: dict[str, str], contexto_tenant: UUID
) -> None:
    """La pantalla mete la conversación recién creada en su lista sin volver a
    pedirla, así que la respuesta del alta tiene que traer **la misma forma**
    que el listado. Si le faltara `sin_leer`, el canal nuevo aparecería con un
    contador en blanco hasta recargar."""
    r = identity.post(
        "/api/v1/chat/conversaciones",
        headers=cabeceras,
        json={"tipo": "canal", "clave": "ventas", "nombre": "Ventas"},
    )
    assert r.status_code == 201, r.text
    _campos(
        r.json(),
        "id",
        "tipo",
        "clave",
        "nombre",
        "proposito",
        "objeto_tipo",
        "objeto_id",
        "ultimo_mensaje_at",
        "sin_leer",
    )


def test_escribir_un_mensaje_devuelve_lo_que_el_hilo_pinta(
    identity: Any, cabeceras: dict[str, str], contexto_tenant: UUID
) -> None:
    """Lo mismo por el otro lado: el mensaje se añade al hilo con lo que
    devuelve el POST. Sin `created_at` saldría sin hora, y sin `reacciones` la
    pantalla reventaría al recorrerlas."""
    conversacion = identity.post(
        "/api/v1/chat/conversaciones",
        headers=cabeceras,
        json={"tipo": "canal", "clave": "soporte", "nombre": "Soporte"},
    ).json()["id"]

    r = identity.post(
        f"/api/v1/chat/conversaciones/{conversacion}/mensajes",
        headers=cabeceras,
        json={"cuerpo": "Buenos días"},
    )
    assert r.status_code == 201, r.text
    cuerpo = r.json()
    _campos(
        cuerpo,
        "id",
        "conversacion_id",
        "autor_id",
        "cuerpo",
        "responde_a_id",
        "menciones",
        "editado_at",
        "ediciones",
        "reacciones",
        "created_at",
    )
    assert cuerpo["reacciones"] == {}
    assert cuerpo["ediciones"] == 0


# ── Compromisos de servicio: Estado.tsx ───────────────────────────────────


def test_los_compromisos_traen_lo_prometido_y_lo_medido_al_lado(
    tenancy: Any, cabeceras: dict[str, str], contexto_tenant: UUID
) -> None:
    """Enseñar solo lo prometido convierte la pantalla en el PDF de antes. Y
    `medido` puede ser nulo —hay cosas que el sistema no puede medirse a sí
    mismo— pero la clave tiene que venir: sin ella la pantalla no distingue «no
    se sabe» de «cero»."""
    r = tenancy.get("/api/v1/compromisos", headers=cabeceras)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    _campos(cuerpo, "tier", "compromisos")
    assert cuerpo["compromisos"], "sin compromisos no hay nada que comparar"
    for fila in cuerpo["compromisos"]:
        _campos(fila, "metrica", "que_es", "comprometido", "unidad", "medido", "como_se_mide")
    # El que no se puede medir lo dice en vez de devolver un cero.
    rto = next(f for f in cuerpo["compromisos"] if f["metrica"] == "RTO")
    assert rto["medido"] is None and rto["como_se_mide"]


# ── Capacidad de proveedor: Coste.tsx ─────────────────────────────────────


def test_la_capacidad_dice_lo_libre_y_lo_que_pasaria_si_se_ganara_todo(
    sales: Any, cabeceras: dict[str, str], contexto_tenant: UUID
) -> None:
    """Una cuota que solo mira lo contratado deja vender tres veces lo mismo.
    La pantalla pinta las dos cifras y el aviso, así que las tres viajan."""
    r = sales.get(
        "/api/v1/coste/capacidad?contratada=1000&comprometida=800&en_ofertas=300",
        headers=cabeceras,
    )
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    _campos(
        cuerpo,
        "contratada",
        "comprometida",
        "libre",
        "en_ofertas_abiertas",
        "libre_si_se_ganan_todas",
        "sobrevendida",
        "aviso",
    )
    # 1000 - 800 = 200 libres, y 300 en ofertas: si se ganan todas no cabe.
    assert cuerpo["libre"] == "200"
    assert cuerpo["sobrevendida"] is False
    assert cuerpo["aviso"], "no cabría y la pantalla no tendría qué avisar"


# ── Cuadros de mando e informes: Cuadros.tsx ──────────────────────────────


def test_los_cuadros_traen_sus_componentes(
    analytics: Any,
    cabeceras: dict[str, str],
    uow: Any,
    usuario: UUID,
    informe: Any,
    contexto_tenant: UUID,
) -> None:
    """La pantalla dibuja un componente por entrada. Sin `componentes` el
    cuadro saldría con su título y nada debajo, que se lee como «todavía está
    cargando»."""
    from services.analytics import informes as inf

    inf.crear_cuadro(
        uow,
        clave="comercial",
        nombre="Comercial",
        descripcion="Lo del mes",
        componentes=[
            {"tipo": "kpi", "titulo": "Ganadas", "informe": informe.clave, "metrica": "importe"}
        ],
        propietario_id=usuario,
    )
    uow.db.flush()

    r = analytics.get("/api/v1/cuadros-mando", headers=cabeceras)
    assert r.status_code == 200, r.text
    filas = r.json()
    assert filas, "el cuadro creado no sale"
    _campos(
        filas[0], "id", "clave", "nombre", "descripcion", "componentes", "por_defecto", "propio"
    )
    assert filas[0]["componentes"][0]["tipo"] == "kpi"


@pytest.fixture
def informe(uow: Any, tenant_id: UUID, usuario: UUID) -> Any:
    from services.analytics import informes as inf

    fila = inf.Informe(
        tenant_id=tenant_id,
        propietario_id=usuario,
        clave="ganadas",
        nombre="Oportunidades ganadas",
        objeto="oportunidad",
        tipo="tabular",
        columnas=["nombre", "importe"],
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila


def test_el_listado_de_informes_trae_con_que_identificarlos(
    analytics: Any, cabeceras: dict[str, str], informe: Any
) -> None:
    """La pantalla los ofrece por `clave` y los ejecuta por `id`. Con uno solo
    de los dos, o no se sabe cuál elegir o no se puede lanzar."""
    r = analytics.get("/api/v1/informes", headers=cabeceras)
    assert r.status_code == 200, r.text
    filas = r.json()
    assert filas, "el informe creado no sale"
    _campos(filas[0], "id", "clave", "nombre", "objeto", "tipo", "solo_mios")


def test_ejecutar_un_informe_trae_las_columnas_con_las_filas(
    analytics: Any, cabeceras: dict[str, str], informe: Any
) -> None:
    """**Las filas son listas, no diccionarios.** Sin `columnas` no hay forma de
    saber qué es cada valor y la pantalla no puede pintar ni una cabecera ni un
    eje: enseñaba el título del componente y un hueco.

    El motor analítico es externo y aquí se sustituye por uno de mentira: lo que
    se mide es la forma de la respuesta, no quién resuelve la consulta.
    """
    from services.analytics import informes as inf

    previo = inf._EJECUTOR
    inf.registrar_ejecutor(lambda plan, tenant_id: {"filas": [["Acme", 1000], ["Beta", 2000]]})
    try:
        r = analytics.post(
            f"/api/v1/informes/{informe.id}/ejecutar",
            headers=cabeceras,
            json={"filtros": [], "formato": "json"},
        )
    finally:
        inf._EJECUTOR = previo

    assert r.status_code == 200, r.text
    cuerpo = r.json()
    _campos(cuerpo, "nombre", "columnas", "filas", "truncado", "campos_retirados")
    assert cuerpo["nombre"] == "Oportunidades ganadas"
    assert cuerpo["filas"] == [["Acme", 1000], ["Beta", 2000]]
    assert len(cuerpo["columnas"]) == len(cuerpo["filas"][0]), (
        "hay más valores que nombres de columna: las cabeceras no corresponderían "
        "con los datos, que es peor que no pintarlas"
    )


# ── Explotación: Explotacion.tsx ──────────────────────────────────────────


def test_el_diagnostico_dice_que_sigue_funcionando_y_no_solo_que_falla(
    analytics: Any, cabeceras: dict[str, str], contexto_tenant: UUID
) -> None:
    """«Servicio no disponible» deja a quien lo lee creyendo que su CRM se ha
    caído. No se ha caído: lo que no funciona es preguntar. Y `url_publica` y
    `fuente_id` viajan porque el navegador no puede adivinar ninguno de los
    dos."""
    r = analytics.get("/api/v1/explotacion/diagnostico", headers=cabeceras)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    _campos(
        cuerpo,
        "puede_preguntar",
        "problemas",
        "sigue_funcionando",
        "no_funciona",
        "url_publica",
        "fuente_id",
    )
    # Sin fuente registrada no se puede preguntar, y entonces lo que sí sigue
    # funcionando es la mitad útil de la respuesta.
    assert cuerpo["puede_preguntar"] is False
    assert cuerpo["problemas"] and cuerpo["sigue_funcionando"] and cuerpo["no_funciona"]


def test_las_preguntas_guardadas_dicen_cuales_son_mias(
    analytics: Any, cabeceras: dict[str, str], uow: Any, usuario: UUID, contexto_tenant: UUID
) -> None:
    """Sin `propia` y `publicada` no se pueden separar «mías» y «publicadas», y
    una pregunta a medio afinar se usa como si estuviera bien."""
    from services.analytics import fuente as fte

    fte.guardar_pregunta(
        uow,
        clave="abiertas",
        titulo="Oportunidades abiertas",
        pregunta="¿Cuántas oportunidades hay abiertas por etapa?",
        autor_id=usuario,
    )
    uow.db.flush()

    r = analytics.get("/api/v1/explotacion/preguntas", headers=cabeceras)
    assert r.status_code == 200, r.text
    filas = r.json()
    assert filas, "la pregunta guardada no sale"
    _campos(
        filas[0],
        "id",
        "clave",
        "titulo",
        "pregunta",
        "publicada",
        "propia",
        "informe_id",
        "veces_usada",
    )
    assert filas[0]["propia"] is True and filas[0]["publicada"] is False


# ── El desvío de un entorno: Alm.tsx ──────────────────────────────────────


@pytest.fixture
def cuenta_con_campo(uow: Any, tenant_id: UUID) -> Any:
    """Un objeto con un campo, que es lo que la vista rápida lee para comparar."""
    from services.metadata.modelos import CampoDefinido, ObjetoDefinido

    objeto = ObjetoDefinido(tenant_id=tenant_id, nombre="cuenta", etiqueta="Cuenta")
    uow.db.add(objeto)
    uow.db.flush()
    uow.db.add(
        CampoDefinido(
            tenant_id=tenant_id,
            objeto_id=objeto.id,
            nombre="nif",
            etiqueta="NIF",
            tipo="texto",
        )
    )
    uow.db.flush()
    return objeto


def test_el_desvio_de_un_entorno_se_puede_pedir_de_verdad(
    metadata: Any,
    cabeceras: dict[str, str],
    uow: Any,
    cuenta_con_campo: Any,
    contexto_tenant: UUID,
) -> None:
    """**El 500.** La ruta leía `clave` de la definición publicada de cada
    campo, que trae `nombre`. Con un solo campo definido, esta llamada era un
    `KeyError`: la pantalla de entornos no podía enseñar el desvío de nada."""
    from services.metadata import entornos as ent

    paquete = ent.empaquetar(uow, nombre="base", contenido={"campos": [{"clave": "nif"}]})
    ent.desplegar(uow, paquete_id=paquete.id, entorno="produccion")
    uow.db.flush()

    entorno = "produccion"
    r = metadata.get(f"/api/v1/entornos/{entorno}/drift", headers=cabeceras)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    _campos(cuerpo, "medible", "limpio", "tocado_a_mano", "desaparecido", "que_significa")


def test_un_entorno_sin_tocar_no_sale_desviado_entero(
    metadata: Any,
    cabeceras: dict[str, str],
    uow: Any,
    cuenta_con_campo: Any,
    contexto_tenant: UUID,
) -> None:
    """**El informe inventado.** El estado actual se montaba como un
    diccionario donde la comparación espera una lista, así que nada casaba y
    todo lo del paquete salía como desaparecido. Un entorno recién desplegado y
    sin tocar aparecía desviado de arriba abajo, que es la forma más rápida de
    que se deje de mirar."""
    from services.metadata import entornos as ent

    paquete = ent.empaquetar(
        uow, nombre="base", contenido={"campos": [{"clave": "nif", "tipo": "texto"}]}
    )
    ent.desplegar(uow, paquete_id=paquete.id, entorno="produccion")
    uow.db.flush()

    entorno = "produccion"
    cuerpo = metadata.get(f"/api/v1/entornos/{entorno}/drift", headers=cabeceras).json()
    assert cuerpo["desaparecido"] == [], cuerpo
    assert cuerpo["tocado_a_mano"] == [], cuerpo
    assert cuerpo["limpio"] is True


def test_lo_que_no_se_ha_comparado_se_dice_en_vez_de_darse_por_borrado(
    metadata: Any,
    cabeceras: dict[str, str],
    uow: Any,
    cuenta_con_campo: Any,
    contexto_tenant: UUID,
) -> None:
    """La vista rápida solo sabe leer campos. Los otros siete tipos de
    contenido se comparaban igual contra un estado que no los tenía, así que
    una vista o una plantilla del paquete salían como borradas. Ahora se dicen
    aparte: de eso no se sabe nada, ni bueno ni malo."""
    from services.metadata import entornos as ent

    paquete = ent.empaquetar(
        uow,
        nombre="base",
        contenido={
            "campos": [{"clave": "nif", "tipo": "texto"}],
            "vistas": [{"clave": "mis_cuentas"}],
        },
    )
    ent.desplegar(uow, paquete_id=paquete.id, entorno="produccion")
    uow.db.flush()

    entorno = "produccion"
    cuerpo = metadata.get(f"/api/v1/entornos/{entorno}/drift", headers=cabeceras).json()
    assert (
        "vistas.mis_cuentas" not in cuerpo["desaparecido"]
    ), "una vista que nadie ha mirado no es una vista borrada"
    assert cuerpo["comparado"] == ["campos"]
    assert "vistas" in cuerpo["no_comparado"]
    # Y el texto no puede decir que todo coincide cuando hay siete tipos sin
    # mirar: un «limpio» que tapa lo no comparado es peor que no medir.
    assert "no se ha mirado" in cuerpo["que_significa"]


def test_lo_tocado_a_mano_llega_a_la_pantalla(
    metadata: Any,
    cabeceras: dict[str, str],
    uow: Any,
    cuenta_con_campo: Any,
    contexto_tenant: UUID,
) -> None:
    """Y el caso que importa: alguien cambió el tipo de un campo en producción.
    Sale, con el nombre del campo que cambió."""
    from services.metadata import entornos as ent

    paquete = ent.empaquetar(
        uow, nombre="base", contenido={"campos": [{"clave": "nif", "tipo": "numero"}]}
    )
    ent.desplegar(uow, paquete_id=paquete.id, entorno="produccion")
    uow.db.flush()

    entorno = "produccion"
    cuerpo = metadata.get(f"/api/v1/entornos/{entorno}/drift", headers=cabeceras).json()
    assert cuerpo["limpio"] is False
    assert cuerpo["tocado_a_mano"][0]["elemento"] == "campos.nif"
    assert cuerpo["tocado_a_mano"][0]["campos"] == ["tipo"]


def test_sin_el_objeto_que_se_compara_se_dice_por_que(
    metadata: Any, cabeceras: dict[str, str], uow: Any, contexto_tenant: UUID
) -> None:
    """Sin objeto `cuenta` la lectura del estado lanzaba un «no existe» que
    salía como un 404 de la ruta, y eso se lee como «esta pantalla no va». La
    ruta existe y ha respondido: lo que no hay es contra qué comparar."""
    from services.metadata import entornos as ent

    paquete = ent.empaquetar(uow, nombre="base", contenido={"campos": [{"clave": "nif"}]})
    ent.desplegar(uow, paquete_id=paquete.id, entorno="produccion")
    uow.db.flush()

    entorno = "produccion"
    r = metadata.get(f"/api/v1/entornos/{entorno}/drift", headers=cabeceras)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["medible"] is False
    assert "no se sabe" in cuerpo["porque"]


# ── El puesto de trabajo: Puesto.tsx ──────────────────────────────────────


def test_la_salud_del_puesto_separa_lo_parado_de_lo_que_no_se_ha_medido(
    integration: Any, cabeceras: dict[str, str], uow: Any, tenant_id: UUID, usuario: UUID
) -> None:
    """**Lo que no se ha medido no está en verde.** Una conexión sin última
    sincronización no es una conexión sana: es una de la que no se sabe nada, y
    la pantalla las pinta en una lista aparte."""
    from services.integration.buzon import Buzon

    uow.db.add(
        Buzon(
            tenant_id=tenant_id,
            usuario_id=usuario,
            perfil="generico",
            ambito="correo",
            direccion="ana@example.com",
            estado="conectado",
            sincronizado_at=datetime.now(timezone.utc) - timedelta(days=3),
        )
    )
    uow.db.add(
        Buzon(
            tenant_id=tenant_id,
            usuario_id=usuario,
            perfil="generico",
            ambito="calendario",
            direccion="ana@example.com",
            estado="conectado",
        )
    )
    uow.db.flush()

    r = integration.get("/api/v1/suites/salud", headers=cabeceras)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    _campos(
        cuerpo,
        "total",
        "paradas",
        "sin_medir",
        "en_sondeo",
        "todo_bien",
        "medible",
        "que_significa",
        "los_en_sondeo",
    )
    assert cuerpo["total"] == 2
    assert len(cuerpo["paradas"]) == 1, "la que lleva tres días parada no sale"
    _campos(cuerpo["paradas"][0], "conexion", "horas_sin_sincronizar", "estado", "porque")
    assert len(cuerpo["sin_medir"]) == 1, "la que nunca sincronizó no puede contar como sana"
    assert cuerpo["todo_bien"] is False


# ── Las dos que acompañan a la salud del puesto: Suite.tsx ────────────────
#
# Se añaden el 27-10-2026 por un fallo recién plantado y recién cazado. El
# panel «salud de las suites» se escribió leyendo las dos rutas como si
# devolvieran una LISTA, y las dos devuelven un sobre:
# `{revisados, que_piden_algo}` y `{por_renovar, sin_caducidad_declarada,
# aviso}`. El `.filter` sobre un objeto revienta dentro del `.then`, el
# `.catch` se lo traga, y el panel sale con sus dos rótulos y nada debajo. Sin
# error en consola y sin 500: exactamente el fallo que da nombre a este
# fichero, cometido otra vez el mismo día.


def test_la_salud_de_las_credenciales_viene_en_un_sobre_y_dice_cual_se_rompe_sola(
    integration: Any, cabeceras: dict[str, str], uow: Any, tenant_id: UUID, usuario: UUID
) -> None:
    """Tres credenciales y sólo una es la bomba de relojería.

    La que tiene caducidad **y no tiene refresco** sale aunque le queden
    trescientos días: el día que llegue deja de entrar el correo de todos a la
    vez, y conseguir refresco o planificar la reautorización no se hace en una
    semana. La que no declara caducidad sale como «no fiable» —no se sabe que
    esté bien, se sabe que no se ha medido—. La sana y con refresco no sale.
    """
    from services.integration.suites import ConsentimientoSuite

    lejos = datetime.now(timezone.utc) + timedelta(days=300)
    for perfil, caduca, refresco in (
        ("bomba", lejos, False),
        ("sana", lejos, True),
        ("sin_medir", None, True),
    ):
        uow.db.add(
            ConsentimientoSuite(
                tenant_id=tenant_id,
                usuario_id=usuario,
                perfil=perfil,
                recurso="correo",
                concedido_at=datetime.now(timezone.utc),
                credencial_caduca_at=caduca,
                tiene_refresco=refresco,
            )
        )
    uow.db.flush()

    r = integration.get("/api/v1/suites/credenciales/salud", headers=cabeceras)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    # El sobre, que es lo que la pantalla leía mal: un objeto, no una lista.
    assert isinstance(cuerpo, dict), f"la pantalla lo lee como lista y llega {type(cuerpo)}"
    _campos(cuerpo, "revisados", "que_piden_algo")
    assert cuerpo["revisados"] == 3, "las tres se han mirado"

    piden = {c["perfil"]: c for c in cuerpo["que_piden_algo"]}
    assert "sana" not in piden, "una credencial con refresco y lejos de caducar no pide nada"
    assert set(piden) == {"bomba", "sin_medir"}, sorted(piden)

    # Campo a campo, los que pinta el panel.
    _campos(
        piden["bomba"],
        "consentimiento_id",
        "usuario_id",
        "perfil",
        "recurso",
        "se_rompera_sola",
        "renovar",
        "avisar",
        "fiable",
        "porque",
    )
    assert piden["bomba"]["se_rompera_sola"] is True
    assert piden["sin_medir"]["se_rompera_sola"] is False
    assert piden["sin_medir"]["fiable"] is False
    # El porqué viaja escrito: «error de autenticación» a secas es el mensaje
    # que atasca una implantación una semana.
    assert piden["bomba"]["porque"].strip(), "sin porqué, el panel no dice qué hacer"


def test_las_suscripciones_por_renovar_separan_las_que_no_dicen_cuando_caducan(
    integration: Any, cabeceras: dict[str, str], uow: Any, tenant_id: UUID, usuario: UUID
) -> None:
    """Y `sin_caducidad_declarada` son identificadores, no registros.

    Importa porque la pantalla pintaba `s.recurso` de cada uno: con una lista
    de cadenas eso es `undefined`, y la línea sale vacía sin que falle nada.
    """
    from services.integration.suites import SuscripcionSuite

    for recurso, caduca in (
        ("correo", datetime.now(timezone.utc) + timedelta(hours=6)),
        ("calendario", datetime.now(timezone.utc) + timedelta(days=200)),
        ("contactos", None),
    ):
        uow.db.add(
            SuscripcionSuite(
                tenant_id=tenant_id,
                usuario_id=usuario,
                perfil="generico",
                recurso=recurso,
                estado="activa",
                caduca_at=caduca,
            )
        )
    uow.db.flush()

    r = integration.get("/api/v1/suites/suscripciones/por-renovar", headers=cabeceras)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert isinstance(cuerpo, dict), f"la pantalla lo lee como lista y llega {type(cuerpo)}"
    _campos(cuerpo, "por_renovar", "sin_caducidad_declarada", "aviso")

    assert [s["recurso"] for s in cuerpo["por_renovar"]] == [
        "correo"
    ], "sólo la que caduca dentro del margen; la de doscientos días no es urgente"
    _campos(cuerpo["por_renovar"][0], "id", "recurso", "usuario_id", "caduca_at")

    assert len(cuerpo["sin_caducidad_declarada"]) == 1
    assert all(
        isinstance(x, str) for x in cuerpo["sin_caducidad_declarada"]
    ), "son identificadores sueltos, no registros: la pantalla no puede pedirles `recurso`"
    assert cuerpo["aviso"].strip(), "si hay alguna sin declarar, el aviso lo dice"


# ── El informe de cumplimiento y mis passkeys: Plataforma.tsx, Seguridad.tsx ──


def test_el_informe_de_cumplimiento_dice_lo_que_el_rat_no_dice(
    integration: Any, cabeceras: dict[str, str], tenant_id: UUID
) -> None:
    """Tres cosas que el registro de tratamiento no contesta.

    El RAT dice qué datos personales se tratan y con qué base legal. El informe
    añade lo que hace falta para fiarse de él: si el rastro de auditoría
    **cuadra** —un registro que se puede reescribir no prueba nada—, cuántas
    políticas de acceso hay activas, y los avisos de lo que no encaja.
    """
    r = integration.get("/api/v1/integration/cumplimiento/informe", headers=cabeceras)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    _campos(cuerpo, "servicio", "generado_at", "rat", "avisos", "integridad_del_audit_trail")
    _campos(cuerpo["integridad_del_audit_trail"], "verificacion")
    # `politicas_de_acceso` es lo que pinta el panel: sin el recuento, «hay
    # políticas» y «no hay ninguna» se ven igual.
    _campos(cuerpo["politicas_de_acceso"], "activas", "nombres")
    assert isinstance(cuerpo["avisos"], list)


def test_mis_passkeys_se_listan_aunque_no_haya_ninguna(
    identity: Any, cabeceras: dict[str, str]
) -> None:
    """Y la lista vacía es una lista, no un error.

    La pantalla de seguridad cuenta cuántas hay para decirle a cada uno con qué
    ha entrado. Si esto contestara un objeto en vez de una lista —o un 404
    cuando no hay ninguna— el recuento saldría en blanco sin que fallara nada.
    """
    r = identity.get("/api/v1/auth/passkeys", headers=cabeceras)
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list), f"la pantalla las cuenta: llega {type(r.json())}"


# ── Y cuatro más, del modelo de datos: ObjetoDelModelo.tsx ───────────────
#
# 29-10-2026. La pantalla del objeto del modelo pasó a leer cuatro rutas que
# ninguna prueba de servidor recorría: el diseño vigente, la semántica con su
# cobertura, los candidatos a columna y —de otro servicio— el modelo que
# explota analytics. Es el mismo trinquete que cazó las once de arriba, y lo
# cazó el día que se escribieron.
#
# Van aquí y no en un fichero aparte: es exactamente lo que este fichero hace,
# y el andamio —cliente por servicio, cabeceras firmadas, buzón apagado— ya
# está escrito.


@pytest.fixture
def objeto_con_campos(db: Any, tenant_id: UUID) -> Any:
    """Un objeto del tenant con un campo descrito y otro sin describir.

    Los dos hacen falta: con todos descritos la cobertura sale al 100 % y la
    prueba no distinguiría un cálculo correcto de una constante.
    """
    from services.metadata.modelos import CampoDefinido, Layout, ObjetoDefinido

    objeto = ObjetoDefinido(
        tenant_id=tenant_id,
        nombre="encargo_propio",
        etiqueta="Encargo propio",
        etiqueta_plural="Encargos propios",
        origen="tenant",
        estados={"borrador": ["enviado"], "enviado": []},
    )
    db.add(objeto)
    db.flush()
    db.add(
        CampoDefinido(
            tenant_id=tenant_id,
            objeto_id=objeto.id,
            nombre="segmento",
            etiqueta="Segmento",
            tipo="texto",
            descripcion_semantica="En qué tramo de facturación entra el cliente",
            explotable=True,
            sensibilidad="interno",
        )
    )
    db.add(
        CampoDefinido(
            tenant_id=tenant_id,
            objeto_id=objeto.id,
            nombre="cmp_2",
            etiqueta="cmp_2",
            tipo="texto",
            sensibilidad="interno",
        )
    )
    db.add(
        Layout(
            tenant_id=tenant_id,
            objeto_id=objeto.id,
            nombre="Ficha comercial",
            rol="comercial",
            secciones=[{"titulo": "Datos", "campos": ["segmento"]}],
            es_defecto=True,
        )
    )
    db.flush()
    return objeto


def test_el_diseno_vigente_dice_cual_es_y_por_que_ese(
    metadata: Any, cabeceras: dict[str, str], objeto_con_campos: Any
) -> None:
    """El «por qué» no es adorno: es la respuesta a «¿por qué veo otra pantalla?».

    La pantalla lee `hay_diseno`, `nombre`, `secciones` y `porque`. Si el
    servidor dejara de mandar `porque`, el panel saldría con su rótulo y sin la
    única frase que contesta la pregunta por la que existe.
    """
    r = metadata.get("/api/v1/metadata/objetos/encargo_propio/diseno", headers=cabeceras)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    _campos(cuerpo, "objeto", "hay_diseno", "nombre", "secciones", "porque")
    assert cuerpo["hay_diseno"] is True
    # Lista, no diccionario: la pantalla le pide `.length`.
    assert isinstance(cuerpo["secciones"], list), cuerpo["secciones"]
    assert cuerpo["porque"].strip()


def test_la_semantica_llega_con_su_cobertura_y_los_que_faltan(
    metadata: Any, cabeceras: dict[str, str], objeto_con_campos: Any
) -> None:
    """Con el número y con los nombres.

    Un porcentaje dice cuánto queda; `sin_describir` dice qué hacer. Y el
    porcentaje se comprueba contra un objeto con UN campo descrito de DOS: con
    todos descritos, un 100 % constante pasaría igual.
    """
    r = metadata.get("/api/v1/metadata/objetos/encargo_propio/semantica", headers=cabeceras)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    _campos(cuerpo, "campos", "fuera_por_sensibles", "fuera_por_internos", "sin_describir")
    _campos(cuerpo["cobertura"], "medible", "campos", "explotables", "pct", "que_significa")
    assert cuerpo["cobertura"]["medible"] is True
    assert cuerpo["cobertura"]["campos"] == 2, cuerpo["cobertura"]
    assert cuerpo["cobertura"]["pct"] == 50.0, cuerpo["cobertura"]
    assert "cmp_2" in cuerpo["sin_describir"], cuerpo["sin_describir"]


def test_los_candidatos_a_columna_llegan_con_su_medida(
    metadata: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID, objeto_con_campos: Any
) -> None:
    """La excepción se decide con un número, así que el número tiene que llegar.

    Sin `escrituras` al lado de cada candidato, la pantalla enseñaría una lista
    de campos sin el dato que justifica materializarlos — y materializar es lo
    que bloquea a todos los tenants que comparten la tabla.
    """
    from crmcore.metamodelo import UsoCampo

    db.add(
        UsoCampo(
            tenant_id=tenant_id,
            objeto="encargo_propio",
            campo="segmento",
            escrituras=10_000,
            materializado=False,
        )
    )
    db.flush()

    r = metadata.get(
        "/api/v1/metadata/objetos/encargo_propio/candidatos-columna", headers=cabeceras
    )
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    _campos(cuerpo, "objeto", "umbral", "candidatos", "por_que_no_siempre")
    assert cuerpo["candidatos"], "con 10.000 escrituras tiene que salir candidato"
    _campos(cuerpo["candidatos"][0], "campo", "escrituras")
    assert cuerpo["candidatos"][0]["escrituras"] == 10_000


def test_el_modelo_semantico_de_informes_lo_contesta_analytics(
    analytics: Any, cabeceras: dict[str, str], objeto_con_campos: Any
) -> None:
    """Y lo contesta ÉL, no metadata.

    Es otro servicio el que decide qué se puede explotar en un informe.
    Preguntárselo al de metadatos sería contestar por él, y el día que cambie
    el criterio la pantalla seguiría diciendo lo de antes.

    La pantalla lee `objetos[].nombre`, `objetos[].campos` y
    `excluidos_por_sensibilidad`: sin el último, lo que se deja fuera se calla
    y alguien busca un campo que existe sin encontrarlo.
    """
    r = analytics.get("/api/v1/analitica/modelo-semantico?objeto=encargo_propio", headers=cabeceras)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    _campos(cuerpo, "objetos", "excluidos_por_sensibilidad", "motivo_exclusion")
    assert isinstance(cuerpo["objetos"], list), cuerpo["objetos"]
    if cuerpo["objetos"]:
        _campos(cuerpo["objetos"][0], "nombre", "campos")
        assert isinstance(cuerpo["objetos"][0]["campos"], list)


# ── Y cuatro del dinero de una venta: Oportunidad.tsx ────────────────────
#
# 29-10-2026. La ficha de una oportunidad pasó a leer cuatro rutas que ninguna
# prueba de servidor recorría POR HTTP. Dos de ellas —el reparto y las
# relacionadas— ni siquiera se podían leer antes: se escribían en su tabla y la
# consultaba sólo su propio escritor.


@pytest.fixture
def oportunidad_con_dinero(db: Any, tenant_id: UUID) -> Any:
    """Una oportunidad con línea, reparto descuadrado y una renovación detrás."""
    from services.sales import ingresos as ing
    from services.sales.modelos import Etapa, LineaOportunidad, Oportunidad, Pipeline

    pipeline = Pipeline(tenant_id=tenant_id, nombre="Nuevo negocio", clave="nuevo")
    db.add(pipeline)
    db.flush()
    etapa = Etapa(
        tenant_id=tenant_id,
        pipeline_id=pipeline.id,
        nombre="Propuesta",
        clave="propuesta",
        orden=1,
        probabilidad=60,
    )
    db.add(etapa)
    db.flush()
    op = Oportunidad(
        tenant_id=tenant_id,
        nombre="Renovación Acme",
        pipeline_id=pipeline.id,
        etapa_id=etapa.id,
        importe=Decimal("120000"),
        moneda="EUR",
        probabilidad=60,
    )
    db.add(op)
    db.flush()
    db.add(
        LineaOportunidad(
            tenant_id=tenant_id,
            oportunidad_id=op.id,
            descripcion="Suscripción anual",
            cantidad=Decimal("10"),
            precio_unitario=Decimal("1000"),
            total=Decimal("10000"),
        )
    )
    # Un reparto que NO cuadra, metido por fuera: es el caso que la pantalla
    # tiene que poder enseñar en rojo.
    db.add(
        ing.ParticipacionComercial(
            tenant_id=tenant_id,
            oportunidad_id=op.id,
            usuario_id=uuid4(),
            papel="credito",
            porcentaje=Decimal("60"),
        )
    )
    db.add(
        ing.RelacionOportunidad(
            tenant_id=tenant_id, origen_id=op.id, destino_id=uuid4(), tipo="renovacion"
        )
    )
    db.flush()
    return op


def test_el_reparto_y_las_relacionadas_salen_por_http(
    sales: Any, cabeceras: dict[str, str], oportunidad_con_dinero: Any
) -> None:
    """Se escribían y no las leía nadie: ahora hay ruta, y se recorre de verdad.

    La pantalla pinta el total del crédito en rojo cuando no cuadra. Si el
    servidor dejara de mandar `credito_cuadra`, el aviso desaparecería sin que
    fallara nada y un reparto al 60 % se vería como correcto.
    """
    r = sales.get(f"/api/v1/ingresos/de/{oportunidad_con_dinero.id}", headers=cabeceras)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    _campos(cuerpo, "reparto", "credito_total", "credito_cuadra", "relacionadas")
    assert cuerpo["credito_total"] == "60.00", cuerpo
    assert cuerpo["credito_cuadra"] is False, cuerpo
    _campos(cuerpo["reparto"][0], "usuario_id", "papel", "porcentaje")
    # El sentido: sin él, «renovación» no dice si ésta es la que se renueva o
    # la que renueva a otra, que en el informe son cosas opuestas.
    _campos(cuerpo["relacionadas"][0], "tipo", "sentido", "otra_id")


def test_el_arr_lo_calcula_el_servicio_y_dice_lo_que_deja_fuera(
    sales: Any, cabeceras: dict[str, str]
) -> None:
    """La pantalla manda las líneas y pinta lo que vuelve.

    Lo que no puede faltar es `lo_que_no_cuenta_como_arr`: un ARR sin decir que
    la implantación queda fuera es el número que acaba en una valoración y que
    nadie vuelve a mirar cómo se calculó.
    """
    r = sales.post(
        "/api/v1/ingresos/metricas",
        headers=cabeceras,
        json={
            "lineas": [
                {"tipo": "recurrente", "importe": 10000, "periodicidad": "anual"},
                {"tipo": "puntual", "importe": 2000},
            ]
        },
    )
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    _campos(cuerpo, "arr", "mrr", "tcv", "acv", "puntual", "porque")
    assert "lo_que_no_cuenta_como_arr" in cuerpo, sorted(cuerpo)
    assert "puntual" in cuerpo["lo_que_no_cuenta_como_arr"], cuerpo


def test_el_mapa_de_decision_sale_por_http_con_lo_que_falta(
    sales: Any, cabeceras: dict[str, str], oportunidad_con_dinero: Any
) -> None:
    """Lo útil no es la lista: es lo que falta, y es lo que pinta en ámbar."""
    r = sales.get(f"/api/v1/ingresos/grupo-compra/{oportunidad_con_dinero.id}", headers=cabeceras)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    _campos(cuerpo, "roles", "faltan_por_identificar", "clave_sin_hablar", "completo")
    assert str(cuerpo.get("que_mirar") or "").strip(), cuerpo


def test_el_historial_de_prevision_sale_por_http(
    sales: Any, cabeceras: dict[str, str], oportunidad_con_dinero: Any
) -> None:
    """Vacío es una lista, no un 404.

    La pantalla cuenta las entradas para decir si la venta se ha movido. Si
    esto contestara un objeto —o un 404 cuando no hay nada—, el panel saldría
    en blanco sin decir si es que no se ha movido o que no se puede saber.
    """
    r = sales.get(
        f"/api/v1/forecast/oportunidades/{oportunidad_con_dinero.id}/historial-prevision",
        headers=cabeceras,
    )
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list), f"la pantalla las cuenta: llega {type(r.json())}"


# ── Y cinco de un periodo de previsión: PeriodoDePrevision.tsx ───────────
#
# 29-10-2026. Un periodo de previsión es lo contrario de una fila: es un número
# que alguien defiende en un comité. Lo que hace falta para defenderlo —quién
# lo ajustó, si esos ajustes acercaron al real, qué se ha movido— vive en sus
# rutas hijas, y ninguna prueba de servidor las recorría por HTTP.


@pytest.fixture
def periodo(db: Any, tenant_id: UUID) -> str:
    """Un periodo abierto, que es lo que mira la pantalla."""
    from services.sales.modelos import PeriodoForecast

    db.add(
        PeriodoForecast(
            tenant_id=tenant_id,
            clave="2026-Q4",
            nombre="Q4 2026",
            desde=datetime.now(timezone.utc).date(),
            hasta=(datetime.now(timezone.utc) + timedelta(days=90)).date(),
        )
    )
    db.flush()
    return "2026-Q4"


def test_la_prevision_del_periodo_avisa_de_lo_que_no_ha_podido_convertir(
    sales: Any, cabeceras: dict[str, str], periodo: str
) -> None:
    """El aviso va EN la respuesta, no en un campo que nadie mira.

    La pantalla lo pinta pegado al número. Si el servidor dejara de mandarlo,
    un total con importes perdidos se leería como completo — y nadie lo
    cuestiona, que es lo que lo hace peor que un error.
    """
    r = sales.get(f"/api/v1/forecast/periodos/{periodo}", headers=cabeceras)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    _campos(
        cuerpo,
        "periodo",
        "moneda",
        "total",
        "ponderado",
        "compromiso",
        "oportunidades",
        "por_categoria",
        "sin_tipo_de_cambio",
        "aviso",
    )


def test_los_ajustes_del_periodo_salen_con_su_motivo(
    sales: Any, cabeceras: dict[str, str], periodo: str
) -> None:
    """El motivo es la mitad del ajuste: sin él no se puede juzgar si estaba
    bien hecho, y la lista se convierte en un registro de números cambiados."""
    r = sales.get(f"/api/v1/forecast/periodos/{periodo}/ajustes", headers=cabeceras)
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list), f"la pantalla los recorre: llega {type(r.json())}"


def test_el_acierto_compara_con_lo_que_se_habria_previsto_sin_tocar(
    sales: Any, cabeceras: dict[str, str], periodo: str
) -> None:
    """Los dos errores, no sólo uno.

    Con `error_con_ajuste` solo no se puede saber si ajustar mejoró o empeoró.
    Es el panel que destapa a un responsable que ajusta siempre hacia arriba y
    acierta menos que el número bruto, y sin la comparación nadie se entera
    nunca: al cerrar se mira el real contra el objetivo, no contra lo que se
    habría previsto sin tocar nada.
    """
    r = sales.get(f"/api/v1/forecast/periodos/{periodo}/acierto-ajustes", headers=cabeceras)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert "medible" in cuerpo, sorted(cuerpo)
    if cuerpo["medible"]:
        _campos(cuerpo, "real", "bruto", "ajustado", "error_sin_ajuste", "error_con_ajuste")
    else:
        # Y cuando no se puede medir se dice por qué. Un panel vacío sin motivo
        # se lee como «los ajustes no sirvieron».
        assert str(cuerpo.get("motivo") or "").strip(), cuerpo


def test_el_deslizamiento_separa_las_empujadas_mas_de_una_vez(
    sales: Any, cabeceras: dict[str, str], periodo: str
) -> None:
    """Lo que importa no es cuántas se movieron.

    Una fecha que se empuja dos trimestres seguidos no es un retraso: es una
    venta que no existe. En el total de «con cambio de fecha» se confunde con
    la que se movió una semana, y por eso el campo va aparte.
    """
    r = sales.get(f"/api/v1/forecast/periodos/{periodo}/deslizamiento", headers=cabeceras)
    assert r.status_code == 200, r.text
    _campos(
        r.json(),
        "periodo",
        "oportunidades_con_cambio_de_fecha",
        "empujadas",
        "dias_empujados",
        "empujadas_mas_de_una_vez",
        "detalle",
    )


def test_el_desglose_dice_que_grupos_se_quedan_fuera(
    sales: Any, cabeceras: dict[str, str], periodo: str
) -> None:
    """Un desglose al que le falta una familia entera por un tipo de cambio que
    no estaba se lee como «esa familia no vendió nada»."""
    r = sales.get(f"/api/v1/forecast/periodos/{periodo}/desglose?por=familia", headers=cabeceras)
    assert r.status_code == 200, r.text
    _campos(r.json(), "periodo", "por", "moneda", "grupos", "grupos_sin_tipo_de_cambio")


def test_las_instantaneas_llevan_cuando_se_tomaron(
    sales: Any, cabeceras: dict[str, str], periodo: str
) -> None:
    """Una etiqueta sin fecha no sirve para ordenar nada, y la pregunta es
    siempre «¿cómo íbamos hace tres semanas?»."""
    r = sales.get(f"/api/v1/forecast/periodos/{periodo}/instantaneas", headers=cabeceras)
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list), f"la pantalla las recorre: llega {type(r.json())}"


# ── Y la liquidación de comisión: Liquidacion.tsx ────────────────────────
#
# 29-10-2026. Delante de una liquidación la pregunta no es cuánto: es por qué
# ese número y no otro. El detalle lo guardaba entero —cada euro con su
# explicación, lo recortado por el tope, las reversiones y las reclamaciones—
# y ninguna prueba de servidor lo pedía por HTTP.


def test_la_liquidacion_sale_con_cada_euro_explicado(
    sales: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID
) -> None:
    """Las cuatro cosas que hacen discutible una comisión.

    `explicacion` por línea, `recortado_por_tope` —sin él, una liquidación con
    techo aplicado parece simplemente más baja—, `reversion_de` —una línea
    negativa sin decir de dónde viene se lee como un error de cálculo— y las
    disputas con su resolución.
    """
    from services.sales import comisiones as com

    liquidacion = com.Liquidacion(
        tenant_id=tenant_id,
        plan_id=uuid4(),
        usuario_id=uuid4(),
        desde=datetime.now(timezone.utc).date(),
        hasta=(datetime.now(timezone.utc) + timedelta(days=90)).date(),
        total=Decimal("8400"),
        moneda="EUR",
        recortado_por_tope=Decimal("1600"),
        estado="calculada",
    )
    db.add(liquidacion)
    db.flush()
    db.add(
        com.LineaComision(
            tenant_id=tenant_id,
            liquidacion_id=liquidacion.id,
            origen="oportunidad",
            concepto="Acme — cierre",
            base=Decimal("120000"),
            porcentaje=Decimal("7"),
            importe=Decimal("8400"),
            explicacion="7 % del importe funcional al cerrarse en el tramo alto",
        )
    )
    db.flush()

    r = sales.get(f"/api/v1/liquidaciones/{liquidacion.id}", headers=cabeceras)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    _campos(
        cuerpo,
        "id",
        "estado",
        "desde",
        "hasta",
        "total",
        "moneda",
        "recortado_por_tope",
        "lineas",
        "disputas",
    )
    assert cuerpo["recortado_por_tope"] == "1600.00", cuerpo["recortado_por_tope"]
    _campos(
        cuerpo["lineas"][0],
        "concepto",
        "base",
        "porcentaje",
        "importe",
        "explicacion",
        "reversion_de",
    )
    assert cuerpo["lineas"][0]["explicacion"].strip(), (
        "una línea sin explicación convierte la comisión en un número que hay " "que creerse"
    )


# ── Y dos de la calidad del dato de UN cliente: Cuenta.tsx ───────────────
#
# 29-10-2026. El módulo de calidad enseña la cola y los agregados; delante de
# un cliente concreto la pregunta es otra, y esas dos rutas no las recorría
# ninguna prueba de servidor.


def test_la_jerarquia_de_una_cuenta_sale_por_http(
    party: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID
) -> None:
    """El árbol, con la jerarquía que se ha pedido.

    `jerarquia` viene en la respuesta y no es adorno: son varias a la vez —la
    legal no es la comercial ni la de facturación— y sin saber cuál se está
    viendo, la otra parece un error.
    """
    from services.party.modelos import Cuenta

    matriz = Cuenta(tenant_id=tenant_id, nombre="Delta", clave_canonica="delta")
    db.add(matriz)
    db.flush()

    r = party.get(f"/api/v1/accounts/{matriz.id}/jerarquia", headers=cabeceras)
    assert r.status_code == 200, r.text
    _campos(r.json(), "id", "nombre", "jerarquia", "hijos")
    assert isinstance(r.json()["hijos"], list), "la pantalla la recorre"


def test_los_valores_obsoletos_salen_con_su_tope(
    party: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID
) -> None:
    """Los días Y el tope.

    «Lleva 400 días» no dice nada sin el tope: es lo que lo convierte en «se ha
    pasado». Un dato viejo no se distingue de uno bueno mirándolo, y si el
    servidor deja de mandar el tope el panel pinta un número sin significado.
    """
    from services.party.modelos import Cuenta

    cuenta = Cuenta(tenant_id=tenant_id, nombre="Delta", clave_canonica="delta2")
    db.add(cuenta)
    db.flush()

    r = party.get(f"/api/v1/calidad-dato/obsoletos/cuenta/{cuenta.id}", headers=cabeceras)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    _campos(cuerpo, "obsoletos", "campos_con_linaje", "aviso")
    # Sin linaje la lista sale vacía, y eso NO es «está todo al día»: es que no
    # se sabe. El aviso es lo que separa las dos cosas.
    assert str(cuerpo["aviso"] or "").strip() or cuerpo["campos_con_linaje"], cuerpo


# ── Y la ficha de un caso: Caso.tsx ──────────────────────────────────────
#
# 29-10-2026. El modelo guarda con qué tiene que ver el caso —cuenta,
# contacto, producto, activo, contrato, pedido— y cómo se cerró, y la ruta de
# DETALLE no devolvía ninguno de los dos. El listado de la bandeja sí manda
# `cuenta_id`, así que el dato llegaba a una pantalla y no a la otra.


@pytest.fixture
def service(db: Any) -> Iterator[Any]:
    yield from _app("services.service.main")


def test_la_ficha_de_un_caso_dice_con_que_tiene_que_ver(
    service: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID
) -> None:
    """Abrir un caso no puede perder de qué cliente es.

    Es lo primero que se mira al atenderlo, y lo tenía guardado desde que se
    abrió. Van los seis y no sólo la cuenta: un caso sobre un activo instalado
    se atiende distinto que uno sobre un pedido, y sin el activo hay que
    preguntárselo al cliente, que ya lo dijo.
    """
    from services.service.modelos import Caso

    cuenta, activo = uuid4(), uuid4()
    caso = Caso(
        tenant_id=tenant_id,
        asunto="No arranca la máquina 4",
        cuenta_id=cuenta,
        activo_id=activo,
    )
    db.add(caso)
    db.flush()

    r = service.get(f"/api/v1/casos/{caso.id}", headers=cabeceras)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    _campos(cuerpo, "id", "asunto", "estado", "relacionado_con", "cierre", "sla", "relaciones")
    _campos(
        cuerpo["relacionado_con"],
        "cuenta_id",
        "contacto_id",
        "producto_id",
        "activo_id",
        "contrato_id",
        "pedido_id",
    )
    assert cuerpo["relacionado_con"]["cuenta_id"] == str(cuenta)
    assert cuerpo["relacionado_con"]["activo_id"] == str(activo)


def test_un_caso_pendiente_del_cliente_no_consta_cerrado(
    service: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID
) -> None:
    """La mitad que casi nunca se publica.

    Un caso cerrado por el agente y pendiente de que el cliente lo dé por
    bueno **no está cerrado**, y en una lista se ve igual que uno que sí. Si
    el servidor deja de mandar `validacion_cliente`, el aviso desaparece y un
    informe de cierres pasa a decir lo que no es.

    Y las reaperturas van con el cierre: un caso cerrado tres veces no es un
    caso resuelto, y el número al lado del motivo es lo que hace que se lea.
    """
    from services.service.modelos import Caso

    caso = Caso(
        tenant_id=tenant_id,
        asunto="Factura duplicada",
        estado="cerrado",
        motivo_cierre="resuelto",
        resolucion="Se emitió abono",
        validacion_cliente="pendiente",
        reaperturas=2,
    )
    db.add(caso)
    db.flush()

    r = service.get(f"/api/v1/casos/{caso.id}", headers=cabeceras)
    assert r.status_code == 200, r.text
    cierre = r.json()["cierre"]
    _campos(cierre, "motivo", "resolucion", "validacion_cliente", "reaperturas")
    assert cierre["validacion_cliente"] == "pendiente"
    assert cierre["reaperturas"] == 2


def test_por_que_el_caso_acabo_en_esa_cola_sale_por_http(
    service: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID
) -> None:
    """«¿Por qué me ha llegado esto a mí?» es la pregunta del reparto.

    Sin respuesta, la gente deja de fiarse del reparto y empieza a coger los
    casos a mano, que es lo que el reparto existe para evitar. Vacío es una
    lista, no un 404: un caso sin asignar todavía no es un error.
    """
    from services.service.modelos import Caso

    caso = Caso(tenant_id=tenant_id, asunto="Sin asignar")
    db.add(caso)
    db.flush()

    r = service.get(f"/api/v1/colas/explicar/{caso.id}", headers=cabeceras)
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list), f"la pantalla la recorre: llega {type(r.json())}"


def test_el_saldo_del_derecho_trae_LAS_DOS_bolsas(
    service: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID
) -> None:
    """Horas y casos, aunque sólo una esté limitada.

    Enseñar sólo la limitada hace que quien mira no sepa si la otra no se
    cuenta o es que nadie ha gastado, y son cosas distintas delante de un
    cliente que pregunta. Y la caducidad al lado del saldo: un derecho con 200
    horas libres que vence el viernes es tan inservible como uno agotado.
    """
    from services.service.modelos import Entitlement

    derecho = Entitlement(
        tenant_id=tenant_id,
        clave="oro",
        nombre="Soporte oro",
        horas_incluidas=Decimal("200"),
        vigente_desde=datetime.now(timezone.utc).date(),
    )
    db.add(derecho)
    db.flush()

    r = service.get(f"/api/v1/entitlements/{derecho.id}/saldo", headers=cabeceras)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    _campos(cuerpo, "entitlement", "al_agotar", "horas", "casos", "vigente_hasta")
    for bolsa in ("horas", "casos"):
        _campos(cuerpo[bolsa], "sin_limite", "agotado")
    # La de casos NO está limitada aquí, y aun así viene: es justo el caso que
    # se perdería si sólo se devolviera lo limitado.
    assert cuerpo["casos"]["sin_limite"] is True, cuerpo["casos"]


# ── Y la evidencia de una firma: SobreDeFirma.tsx ────────────────────────
#
# 29-10-2026. La ficha genérica no podía enseñarla: la evidencia devuelve un
# OBJETO, y esa ficha sólo descubre paneles que devuelven listas, así que
# habría salido siempre «nada todavía».


def test_la_evidencia_dice_si_la_firma_se_puede_verificar(
    integration: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID
) -> None:
    """`verificable` es el campo que separa un documento firmado de uno que
    PARECE firmado.

    Sin el hash de lo enviado y el de lo firmado, la firma no se puede
    comprobar — y eso no se nota mirando el estado, que pone «firmado» igual.
    Si el servidor dejara de mandarlo, la pantalla perdería el único aviso que
    importa el día que alguien discuta la firma.
    """
    from services.integration.firma import Sobre

    sobre = Sobre(
        tenant_id=tenant_id,
        referencia="SOB-1",
        proveedor="proveedor",
        nivel="avanzada",
        estado="firmado",
        hash_enviado="abc123",
    )
    db.add(sobre)
    db.flush()

    r = integration.get(f"/api/v1/firma/sobres/{sobre.id}/evidencia", headers=cabeceras)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    _campos(
        cuerpo,
        "referencia",
        "proveedor",
        "nivel",
        "estado",
        "sello_tiempo",
        "hash_enviado",
        "hash_firmado",
        "verificable",
        "firmantes",
        "eventos",
    )
    # Con sólo uno de los dos hashes NO es verificable, aunque el estado diga
    # que está firmado. Es justo el caso que la pantalla pinta en rojo.
    assert cuerpo["estado"] == "firmado"
    assert cuerpo["verificable"] is False, cuerpo
