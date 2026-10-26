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
