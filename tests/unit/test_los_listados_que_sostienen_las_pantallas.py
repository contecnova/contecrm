"""Los cuatro listados de los que viven las pantallas principales, por la ruta.

Oportunidades, sus líneas, pipelines y casos: de estos cuatro cuelgan la
portada, el tablero de embudo, la ficha de cliente y la ficha de una venta, y
el 29-10-2026 **ninguno tenía una prueba que entrara por su ruta**. Se
recorrían por el ORM, que es por donde no entra ni una pantalla ni un cliente.

Lo destapó ampliar el guardián de contratos para que viera también las
llamadas `listar<T>()`: con ellas a la vista, estas cuatro rutas salieron como
«forma declarada por una pantalla que ninguna prueba de servidor pide».

Cada prueba comprueba **los campos que la pantalla lee**, no todos: fijar el
esquema entero convierte cualquier añadido en una prueba roja y acaba en que
se borra la comprobación.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from starlette.testclient import TestClient

pytestmark = pytest.mark.db


def _cliente(modulo: str) -> Any:
    import importlib
    import os

    from crmcore.config import get_settings

    previo = os.environ.get("OUTBOX_ENABLED")
    os.environ["OUTBOX_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        app = importlib.import_module(modulo).app
        with TestClient(app) as cli:
            yield cli
    finally:
        if previo is None:
            os.environ.pop("OUTBOX_ENABLED", None)
        else:
            os.environ["OUTBOX_ENABLED"] = previo
        get_settings.cache_clear()


@pytest.fixture
def ventas(db: Any, contexto_tenant: UUID) -> Any:
    yield from _cliente("services.sales.main")


@pytest.fixture
def servicio(db: Any, contexto_tenant: UUID) -> Any:
    yield from _cliente("services.service.main")


@pytest.fixture
def cabeceras(tenant_id: UUID) -> dict[str, str]:
    from crmcore.config import get_settings
    from crmcore.http.deps import (
        H_PERMISOS,
        H_ROLES,
        H_TENANT,
        H_USER,
        firmar_cabeceras_internas,
    )

    # Con rol: el enmascarado por sensibilidad se resuelve por rol, y un
    # principal sin ninguno recibe los campos con puntos — la prueba parecería
    # decir que el dato no se puede leer.
    return firmar_cabeceras_internas(
        {
            H_TENANT: str(tenant_id),
            H_USER: str(uuid4()),
            H_PERMISOS: "*:*",
            H_ROLES: "admin",
        },
        get_settings().secret_key.get_secret_value(),
    )


def _pipeline(ventas: TestClient, cabeceras: dict[str, str]) -> dict[str, Any]:
    clave = f"p{uuid4().hex[:8]}"
    creado = ventas.post(
        "/api/v1/pipelines",
        headers=cabeceras,
        json={"clave": clave, "nombre": "Ventas", "por_defecto": True},
    )
    assert creado.status_code in (200, 201), creado.text
    pipeline = dict(creado.json())
    etapa = ventas.post(
        f"/api/v1/pipelines/{pipeline['id']}/etapas",
        headers=cabeceras,
        json={"clave": "nueva", "nombre": "Nueva", "orden": 1, "probabilidad": 10},
    )
    assert etapa.status_code in (200, 201), etapa.text
    return pipeline


def _oportunidad(ventas: TestClient, cabeceras: dict[str, str], **extra: Any) -> dict[str, Any]:
    creada = ventas.post(
        "/api/v1/opportunities",
        headers=cabeceras,
        json={"nombre": "Renovación Acme", "importe": "1000.00", **extra},
    )
    assert creada.status_code in (200, 201), creada.text
    return dict(creada.json())


# ── Pipelines: de aquí salen las columnas del tablero ─────────────────────


def test_el_listado_de_pipelines_trae_sus_etapas(
    ventas: TestClient, cabeceras: dict[str, str]
) -> None:
    """Sin las etapas dentro, el tablero de embudo no tiene columnas."""
    _pipeline(ventas, cabeceras)

    respuesta = ventas.get("/api/v1/pipelines", headers=cabeceras)
    assert respuesta.status_code == 200, respuesta.text
    filas = respuesta.json()["items"]
    assert filas, "el listado de pipelines sale vacío"
    uno = filas[0]
    for campo in ("id", "nombre", "por_defecto", "etapas"):
        assert campo in uno, f"el listado no manda «{campo}», y el tablero lo lee"
    assert uno["etapas"], "un pipeline sin etapas deja el tablero sin columnas"
    for campo in ("id", "clave", "nombre", "orden", "probabilidad", "terminal", "ganada"):
        assert campo in uno["etapas"][0], f"la etapa no manda «{campo}»"


# ── Oportunidades: la portada, el tablero y la ficha de cliente ───────────


def test_el_listado_de_oportunidades_manda_lo_que_pintan_las_tres_pantallas(
    ventas: TestClient, cabeceras: dict[str, str]
) -> None:
    _pipeline(ventas, cabeceras)
    _oportunidad(ventas, cabeceras)

    respuesta = ventas.get("/api/v1/opportunities?limite=50", headers=cabeceras)
    assert respuesta.status_code == 200, respuesta.text
    filas = respuesta.json()["items"]
    assert filas, "el listado de oportunidades sale vacío"
    una = filas[0]
    # La unión de lo que leen portada, tablero y ficha de cliente.
    for campo in (
        "id",
        "nombre",
        "codigo",
        "importe",
        "moneda",
        "probabilidad",
        "etapa_id",
        "estado",
        "fecha_cierre",
        "cuenta_id",
        "owner_id",
    ):
        assert campo in una, f"el listado no manda «{campo}»"


def test_las_lineas_de_una_oportunidad_traen_su_importe(
    ventas: TestClient, cabeceras: dict[str, str]
) -> None:
    """La ficha de una venta suma por línea: sin `total` la suma sale a cero."""
    _pipeline(ventas, cabeceras)
    oportunidad = _oportunidad(ventas, cabeceras)

    alta = ventas.post(
        f"/api/v1/opportunities/{oportunidad['id']}/lineas",
        headers=cabeceras,
        json={"descripcion": "Licencias", "cantidad": "2", "precio_unitario": "500.00"},
    )
    assert alta.status_code in (200, 201), alta.text

    respuesta = ventas.get(f"/api/v1/opportunities/{oportunidad['id']}/lineas", headers=cabeceras)
    assert respuesta.status_code == 200, respuesta.text
    lineas = respuesta.json()
    assert len(lineas) == 1
    for campo in ("id", "descripcion", "cantidad", "precio_unitario", "descuento_pct", "total"):
        assert campo in lineas[0], f"la línea no manda «{campo}»"
    # Y el tipo se llama `tipo_ingreso`: la ficha lo declaraba como `tipo`, que
    # no existe. Declarado y nunca leído, así que no se veía.
    assert "tipo_ingreso" in lineas[0]
    assert "tipo" not in lineas[0]


# ── Casos: la ficha de cliente los lista ──────────────────────────────────


def test_el_listado_de_casos_manda_lo_que_lee_la_ficha_de_cliente(
    servicio: TestClient, cabeceras: dict[str, str]
) -> None:
    cuenta_id = uuid4()
    abierto = servicio.post(
        "/api/v1/casos",
        headers=cabeceras,
        json={"asunto": "No arranca", "cuenta_id": str(cuenta_id)},
    )
    assert abierto.status_code in (200, 201), abierto.text

    respuesta = servicio.get(f"/api/v1/casos?cuenta_id={cuenta_id}&limite=20", headers=cabeceras)
    assert respuesta.status_code == 200, respuesta.text
    filas = respuesta.json()["items"]
    assert filas, "el listado de casos del cliente sale vacío"
    for campo in ("id", "codigo", "asunto", "estado", "prioridad"):
        assert campo in filas[0], f"el listado no manda «{campo}»"


# ── El segmento, por su ruta (CRM-02.01.01.03, .04, .07) ──────────────────
#
# El tamaño y el solapamiento se recorrían por el módulo y no por la ruta, que
# es por donde entra la pantalla. Lo pidió el guardián de contratos en cuanto
# la ficha de un segmento declaró su forma.


@pytest.fixture
def marketing(db: Any, contexto_tenant: UUID) -> Any:
    yield from _cliente("services.marketing.main")


def _segmento(marketing: TestClient, cabeceras: dict[str, str], **extra: Any) -> str:
    creado = marketing.post(
        "/api/v1/segmentos",
        headers=cabeceras,
        json={
            "clave": f"s{uuid4().hex[:8]}",
            "nombre": "Segmento de prueba",
            "objeto": "contacto",
            "definicion": {"atributo": "contacto.estado", "operador": "=", "valor": "activo"},
            **extra,
        },
    )
    assert creado.status_code in (200, 201), creado.text
    return str(creado.json()["id"])


def test_el_tamano_llega_con_su_fecha_y_con_lo_suprimido(
    marketing: TestClient, cabeceras: dict[str, str]
) -> None:
    """Los tres campos que la ficha necesita para no mentir con el número."""
    segmento_id = _segmento(marketing, cabeceras)

    respuesta = marketing.get(f"/api/v1/segmentos/{segmento_id}/tamano", headers=cabeceras)
    assert respuesta.status_code == 200, respuesta.text
    datos = respuesta.json()
    for campo in ("bruto", "alcanzables", "suprimidos", "calculado_at", "es_foto_congelada"):
        assert campo in datos, f"el recuento no manda «{campo}»"
    # El bruto nunca es menor que los alcanzables: entre uno y otro sólo se
    # resta, nunca se suma.
    assert datos["bruto"] >= datos["alcanzables"]
    assert datos["es_foto_congelada"] is False


def test_un_segmento_congelado_se_declara_como_foto(
    marketing: TestClient, cabeceras: dict[str, str]
) -> None:
    """Enseñar una foto igual que un dinámico es sobre lo que se manda un
    correo creyendo que es la gente de hoy."""
    segmento_id = _segmento(marketing, cabeceras)
    congelado = marketing.post(f"/api/v1/segmentos/{segmento_id}/congelar", headers=cabeceras)
    assert congelado.status_code in (200, 201), congelado.text

    datos = marketing.get(f"/api/v1/segmentos/{segmento_id}/tamano", headers=cabeceras).json()
    assert datos["es_foto_congelada"] is True
    assert datos["dinamico"] is False


def test_el_solapamiento_llega_con_el_porcentaje_sobre_cada_uno(
    marketing: TestClient, cabeceras: dict[str, str]
) -> None:
    """Con un solo porcentaje la decisión sale al revés."""
    a = _segmento(marketing, cabeceras)
    b = _segmento(marketing, cabeceras)

    respuesta = marketing.get(f"/api/v1/segmentos/solapamiento?a={a}&b={b}", headers=cabeceras)
    assert respuesta.status_code == 200, respuesta.text
    datos = respuesta.json()
    for campo in (
        "a",
        "b",
        "tamano_a",
        "tamano_b",
        "comunes",
        "pct_de_a",
        "pct_de_b",
        "solo_a",
        "solo_b",
    ):
        assert campo in datos, f"el solapamiento no manda «{campo}»"


def test_la_ficha_de_un_segmento_devuelve_su_definicion(
    marketing: TestClient, cabeceras: dict[str, str]
) -> None:
    """Un segmento es una definición, no una lista: sin ella la ficha no puede
    decir por qué alguien está dentro."""
    segmento_id = _segmento(marketing, cabeceras)

    respuesta = marketing.get(f"/api/v1/segmentos/{segmento_id}", headers=cabeceras)
    assert respuesta.status_code == 200, respuesta.text
    datos = respuesta.json()
    for campo in ("id", "clave", "nombre", "objeto", "dinamico", "definicion", "excluye"):
        assert campo in datos, f"la ficha no manda «{campo}»"
    assert datos["definicion"]["atributo"] == "contacto.estado"


# ── Los canales de entrada, por su ruta (CRM-04.02.01.01) ─────────────────


@pytest.fixture
def servicio_http(db: Any, contexto_tenant: UUID) -> Any:
    yield from _cliente("services.service.main")


def test_el_listado_de_canales_trae_el_motivo_de_cada_descarte(
    servicio_http: TestClient, cabeceras: dict[str, str], db: Any, tenant_id: UUID
) -> None:
    """El total no se puede accionar; el desglose sí.

    Se entra por la ruta porque es por donde entra la pantalla: comprobar el
    contador en la tabla no diría nada de lo que llega al front, que es donde
    el dato se usa para decidir si la trampa se está comiendo clientes.
    """
    from crmcore.db.uow import UnidadDeTrabajo

    from services.service import omnicanal as omni

    _, secreto = omni.crear_canal(
        db,
        tenant_id=tenant_id,
        clave="soporte-http",
        nombre="Soporte por correo",
        tipo="correo",
        mapeo={"asunto": "subject", "cuerpo": "body"},
        fijos={"linea": "soporte"},
        campo_trampa="web_site",
        direccion_propia="soporte@nosotros.com",
    )
    db.flush()
    uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
    omni.recibir(
        uow,
        canal_clave="soporte-http",
        secreto=secreto,
        entrada={"subject": "spam", "body": "…", "remitente": "bot@x.test", "web_site": "x"},
    )
    db.flush()

    respuesta = servicio_http.get("/api/v1/canales-servicio?limite=50", headers=cabeceras)
    assert respuesta.status_code == 200, respuesta.text
    filas = respuesta.json()["items"]
    suyo = next(f for f in filas if f["clave"] == "soporte-http")
    # Lo que la pantalla lee de cada canal.
    for campo in (
        "id",
        "clave",
        "nombre",
        "tipo",
        "activo",
        "recibidos",
        "descartados",
        "descartados_por",
        "mapeo",
        "obligatorios",
        "campo_trampa",
        "max_por_hora",
        "direccion_propia",
    ):
        assert campo in suyo, f"el listado no manda «{campo}»"
    assert suyo["descartados"] == 1
    assert suyo["descartados_por"] == {"trampa": 1}
    # Y el secreto NO sale: está hasheado y no es un campo de pantalla.
    assert "secreto_hash" not in suyo or suyo["secreto_hash"] != secreto


# ── El ciclo de vida de un cliente (CRM-00.01.03.03, CRM-00.01.03.10) ─────
#
# Un clonado, una fusión y una escisión guardan su plan y sus conflictos —«lo
# que alguien tiene que leer ANTES de aprobar», dice el modelo— y no había
# ninguna ruta que los listara: se leían por identificador y nada más. Lo mismo
# con las migraciones de modalidad.


@pytest.fixture
def tenancy(db: Any, contexto_tenant: UUID) -> Any:
    yield from _cliente("services.tenancy.main")


def test_las_operaciones_sobre_un_cliente_se_pueden_recorrer(
    tenancy: TestClient, cabeceras: dict[str, str], db: Any, tenant_id: UUID
) -> None:
    """Simular un clonado y poder volver a él sin haberse guardado el id."""
    simulada = tenancy.post(
        "/api/v1/ciclo-vida/clonado/simular",
        headers=cabeceras,
        json={
            "origen_id": str(tenant_id),
            "uso": "sandbox",
            "bloques": ["configuracion"],
            "recuentos": {"cuentas": 12},
        },
    )
    assert simulada.status_code in (200, 201), simulada.text
    operacion_id = simulada.json()["operacion_id"]

    listado = tenancy.get("/api/v1/ciclo-vida/operaciones?limite=50", headers=cabeceras)
    assert listado.status_code == 200, listado.text
    filas = listado.json()["items"]
    suya = next(f for f in filas if f["id"] == operacion_id)
    # Lo que la pantalla lee: sin `plan` y `conflictos` no se puede aprobar
    # nada, que es justo para lo que el modelo dice que se guardan.
    for campo in (
        "id",
        "tipo",
        "uso",
        "estado",
        "bloques",
        "plan",
        "conflictos",
        "motivo_fin",
        "created_at",
    ):
        assert campo in suya, f"el listado no manda «{campo}»"
    # Y nace SIMULADA: si naciera ejecutada, la pantalla enseñaría como hecho
    # algo que no ha movido una fila.
    assert suya["estado"] == "simulada"
    assert suya["plan"]["recuentos"] == {"cuentas": 12}


def test_las_migraciones_de_modalidad_se_pueden_recorrer(
    tenancy: TestClient, cabeceras: dict[str, str], db: Any, tenant_id: UUID
) -> None:
    """La ventana de solo lectura es lo único de esta familia que pasa ahora
    mismo, y la pantalla la lee de aquí."""
    listado = tenancy.get("/api/v1/aislamiento/migraciones?limite=50", headers=cabeceras)
    assert listado.status_code == 200, listado.text
    assert "items" in listado.json()


def test_los_perfiles_de_industria_se_listan(
    tenancy: TestClient, cabeceras: dict[str, str]
) -> None:
    """Lo que se le deja montado a un cliente nuevo, con su clave y su nombre."""
    respuesta = tenancy.get("/api/v1/ciclo-vida/perfiles", headers=cabeceras)
    assert respuesta.status_code == 200, respuesta.text
    filas = respuesta.json()
    assert isinstance(filas, list)
    for fila in filas:
        for campo in ("clave", "nombre", "descripcion"):
            assert campo in fila, f"el perfil no manda «{campo}»"


# ── El artículo de conocimiento (CRM-04.03.01.03, CRM-04.03.01.06) ───────


@pytest.fixture
def servicio_kb(db: Any, contexto_tenant: UUID) -> Any:
    yield from _cliente("services.service.main")


def _articulo_publicado(db: Any, tenant_id: UUID) -> Any:
    from datetime import timedelta

    from crmcore.db.uow import UnidadDeTrabajo
    from crmcore.fechas import hoy

    from services.service import conocimiento as kb

    uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
    articulo, _ = kb.crear_articulo(
        uow,
        clave=f"art-{uuid4().hex[:8]}",
        titulo="Cómo reiniciar",
        cuerpo="Pulsa el botón",
        revisar_el=hoy() + timedelta(days=90),
    )
    kb.publicar(uow, articulo.id, aprobada_por=uuid4(), audiencia="cliente")
    db.flush()
    return articulo


def test_el_estado_de_las_traducciones_dice_cuantas_versiones_por_detras(
    servicio_kb: TestClient, cabeceras: dict[str, str], db: Any, tenant_id: UUID
) -> None:
    """«Desincronizada» a secas no distingue una errata de otro artículo."""
    from crmcore.db.uow import UnidadDeTrabajo

    from services.service import conocimiento as kb

    articulo = _articulo_publicado(db, tenant_id)
    uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
    kb.traducir(uow, articulo.id, idioma="fr", titulo="Redémarrer", cuerpo="Appuyez")
    db.flush()
    # Y el original avanza: la traducción se queda atrás sin que nadie la toque.
    kb.nueva_version(uow, articulo.id, titulo="Cómo reiniciar (v2)", cuerpo="…")
    kb.publicar(uow, articulo.id, aprobada_por=uuid4(), audiencia="cliente")
    db.flush()

    r = servicio_kb.get(f"/api/v1/conocimiento/{articulo.id}/traducciones", headers=cabeceras)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    for campo in ("idioma_original", "version_publicada", "traducciones", "desincronizadas"):
        assert campo in cuerpo, f"no manda «{campo}»"
    fr = next(x for x in cuerpo["traducciones"] if x["idioma"] == "fr")
    for campo in ("idioma", "estado", "sincronizada", "versiones_por_detras"):
        assert campo in fr, f"la traducción no manda «{campo}»"
    assert fr["sincronizada"] is False
    assert fr["versiones_por_detras"] >= 1, "no dice cuánto se ha quedado atrás"
    assert "fr" in cuerpo["desincronizadas"]


def test_la_eficacia_separa_los_daninos_de_los_huerfanos(
    servicio_kb: TestClient, cabeceras: dict[str, str], db: Any, tenant_id: UUID
) -> None:
    """Los dos se ven igual en una lista por vistas y se arreglan al revés."""
    _articulo_publicado(db, tenant_id)

    r = servicio_kb.get("/api/v1/conocimiento/eficacia", headers=cabeceras)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    for campo in (
        "articulos",
        "publicados",
        "dañinos",
        "huerfanos",
        "caducados",
        "vistas",
        "usos_en_caso",
        "deflexion_aproximada_pct",
        "aviso_deflexion",
    ):
        assert campo in cuerpo, f"la eficacia no manda «{campo}»"
    # Las dos listas son listas distintas: si fueran la misma, la pantalla no
    # podría decir cuál de los dos arreglos toca.
    assert isinstance(cuerpo["dañinos"], list)
    assert isinstance(cuerpo["huerfanos"], list)


# ── El presupuesto (CRM-03.03.02.04, .05, .06) ───────────────────────────
#
# Lo que decide si se manda son tres objetos: la política de descuento con sus
# motivos, la comparación con la versión anterior y el documento tal y como va
# a salir. Ninguno se recorría por su ruta.


@pytest.fixture
def ventas_cpq(db: Any, contexto_tenant: UUID) -> Any:
    yield from _cliente("services.sales.main")


def _presupuesto(ventas_cpq: TestClient, cabeceras: dict[str, str], **extra: Any) -> dict[str, Any]:
    creado = ventas_cpq.post(
        "/api/v1/presupuestos",
        headers=cabeceras,
        json={
            "titulo": "Renovación",
            "lineas": [
                {
                    "descripcion": "Licencias",
                    "cantidad": "10",
                    "precio_unitario": "100.00",
                    "coste_unitario": "60.00",
                    **extra,
                }
            ],
        },
    )
    assert creado.status_code in (200, 201), creado.text
    return dict(creado.json())


def test_la_politica_de_descuento_dice_por_que_y_contra_que(
    ventas_cpq: TestClient, cabeceras: dict[str, str]
) -> None:
    """«Necesita aprobación» a secas se lee como burocracia."""
    presupuesto = _presupuesto(ventas_cpq, cabeceras, descuento_pct="40")

    r = ventas_cpq.get(
        f"/api/v1/presupuestos/{presupuesto['id']}/politica-descuento", headers=cabeceras
    )
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    for campo in (
        "necesita_aprobacion",
        "motivos",
        "descuento_maximo",
        "margen_pct",
        "umbral_descuento",
        "margen_minimo",
    ):
        assert campo in cuerpo, f"la política no manda «{campo}»"
    # Y los motivos son texto que se puede leer, no un código.
    assert isinstance(cuerpo["motivos"], list)


def test_una_primera_version_dice_que_no_hay_con_que_comparar(
    ventas_cpq: TestClient, cabeceras: dict[str, str]
) -> None:
    """Sin `primera`, la pantalla enseñaría una comparación vacía, que se lee
    como «no ha cambiado nada» — que es lo contrario."""
    presupuesto = _presupuesto(ventas_cpq, cabeceras)

    r = ventas_cpq.get(f"/api/v1/presupuestos/{presupuesto['id']}/cambios", headers=cabeceras)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["primera"] is True
    assert cuerpo["cambios"] == []


def test_la_segunda_version_dice_linea_a_linea_que_cambio(
    ventas_cpq: TestClient, cabeceras: dict[str, str]
) -> None:
    presupuesto = _presupuesto(ventas_cpq, cabeceras)
    nueva = ventas_cpq.post(
        f"/api/v1/presupuestos/{presupuesto['id']}/versiones",
        headers=cabeceras,
        json={
            "lineas": [{"descripcion": "Licencias", "cantidad": "7", "precio_unitario": "100.00"}]
        },
    )
    assert nueva.status_code in (200, 201), nueva.text

    r = ventas_cpq.get(f"/api/v1/presupuestos/{nueva.json()['id']}/cambios", headers=cabeceras)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["primera"] is False
    for campo in ("total_antes", "total_ahora", "cambios"):
        assert campo in cuerpo, f"la comparación no manda «{campo}»"
    assert cuerpo["cambios"], "no dice qué cambió"


def test_el_documento_dice_con_que_marca_e_idioma_sale(
    ventas_cpq: TestClient, cabeceras: dict[str, str]
) -> None:
    """Descubrirlo en el correo del cliente no tiene arreglo."""
    presupuesto = _presupuesto(ventas_cpq, cabeceras)

    r = ventas_cpq.get(f"/api/v1/presupuestos/{presupuesto['id']}/documento", headers=cabeceras)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    for campo in (
        "plantilla",
        "marca",
        "idioma",
        "numero",
        "version",
        "lineas",
        "subtotal",
        "descuento_total",
        "total",
        "condiciones",
    ):
        assert campo in cuerpo, f"el documento no manda «{campo}»"


def test_la_ficha_de_un_presupuesto_trae_su_margen(
    ventas_cpq: TestClient, cabeceras: dict[str, str]
) -> None:
    """El margen va pegado al descuento: sin él, un 30 % no se puede valorar."""
    presupuesto = _presupuesto(ventas_cpq, cabeceras)

    r = ventas_cpq.get(f"/api/v1/presupuestos/{presupuesto['id']}", headers=cabeceras)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    for campo in (
        "id",
        "numero",
        "version",
        "estado",
        "moneda",
        "subtotal",
        "descuento_total",
        "total",
        "margen_pct",
    ):
        assert campo in cuerpo, f"la ficha no manda «{campo}»"


# ── Los entornos (CRM-07.02.01.01, .06, .07) ────────────────────────────


@pytest.fixture
def metadata_http(db: Any, contexto_tenant: UUID) -> Any:
    yield from _cliente("services.metadata.main")


def test_un_entorno_sin_desplegar_lo_dice_y_no_sale_vacio(
    metadata_http: TestClient, cabeceras: dict[str, str]
) -> None:
    """Un hueco en blanco se lee como «no hay nada raro»; «nunca se desplegó»
    se lee como lo que es."""
    r = metadata_http.get("/api/v1/entornos/produccion/desplegado", headers=cabeceras)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["hay"] is False
    assert cuerpo["porque"], "no dice por qué no hay nada"


def test_el_drift_sin_paquete_NO_sale_limpio(
    metadata_http: TestClient, cabeceras: dict[str, str]
) -> None:
    """Un entorno limpio y uno que no se ha podido comparar se ven igual de
    bien y significan lo contrario. Es la razón de que exista `medible`."""
    r = metadata_http.get("/api/v1/entornos/produccion/drift", headers=cabeceras)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["medible"] is False
    assert cuerpo.get("limpio") is not True, (
        "sin paquete con el que comparar, decir «limpio» es afirmar algo que " "no se ha mirado"
    )
    assert cuerpo["porque"], "no dice por qué no se puede medir"


def test_un_entorno_que_no_existe_dice_cuales_hay(
    metadata_http: TestClient, cabeceras: dict[str, str]
) -> None:
    """Y enumera los que sí: un «entorno desconocido» a secas deja a quien
    integra probando nombres."""
    r = metadata_http.get("/api/v1/entornos/inventado/desplegado", headers=cabeceras)
    assert r.status_code == 422, r.text
    assert r.json()["detalle"]["admitidos"] == [
        "desarrollo",
        "pruebas",
        "preproduccion",
        "produccion",
    ]


# ── Los canales de salida (CRM-02.03.02.01, .02) ────────────────────────


@pytest.fixture
def marketing_canales(db: Any, contexto_tenant: UUID) -> Any:
    yield from _cliente("services.marketing.main")


def test_el_listado_de_canales_trae_su_palabra_de_baja(
    marketing_canales: TestClient, cabeceras: dict[str, str]
) -> None:
    """Va en la lista y no escondida: quien escribe el mensaje tiene que
    poner esa palabra dentro."""
    creado = marketing_canales.post(
        "/api/v1/canales-marketing",
        headers=cabeceras,
        json={"clave": f"c{uuid4().hex[:8]}", "nombre": "Boletín", "tipo": "email"},
    )
    assert creado.status_code in (200, 201), creado.text

    r = marketing_canales.get("/api/v1/canales-marketing", headers=cabeceras)
    assert r.status_code == 200, r.text
    filas = r.json()
    assert filas, "el listado de canales sale vacío"
    for campo in ("id", "clave", "nombre", "tipo", "activo", "como_se_da_de_baja"):
        assert campo in filas[0], f"el canal no manda «{campo}»"


def test_comprobar_un_envio_dice_por_que_no(
    marketing_canales: TestClient, cabeceras: dict[str, str]
) -> None:
    """«No se puede» a secas deja a quien escribe el mensaje sin saber qué
    arreglar."""
    clave = f"c{uuid4().hex[:8]}"
    creado = marketing_canales.post(
        "/api/v1/canales-marketing",
        headers=cabeceras,
        json={"clave": clave, "nombre": "Boletín", "tipo": "email"},
    )
    assert creado.status_code in (200, 201), creado.text

    r = marketing_canales.get(
        f"/api/v1/canales-marketing/comprobar?canal={clave}&destino=ana@cliente.test",
        headers=cabeceras,
    )
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    for campo in (
        "se_puede_mandar",
        "motivos",
        "canal",
        "necesita_plantilla",
        "ventana_abierta",
        "como_se_da_de_baja",
        "calentamiento",
    ):
        assert campo in cuerpo, f"la comprobación no manda «{campo}»"
    # Sin consentimiento no se puede, y se dice con cuántos motivos.
    assert cuerpo["se_puede_mandar"] is False
    assert cuerpo["motivos"], "no dice por qué no se puede"
    # Y `calentamiento` es None cuando ese dominio no calienta: un 0 se
    # leería como «hoy no puedes mandar nada», que es lo contrario.
    assert cuerpo["calentamiento"] is None


# ── Las menciones, juntadas por el gateway (CRM-06.02.01.01) ────────────


def test_un_servicio_publica_sus_menciones_sin_pedir_el_tipo(
    servicio_http: TestClient, cabeceras: dict[str, str]
) -> None:
    """La ruta que había calculaba TODAS las menciones y tiraba las de los
    demás tipos, así que para verlas había que preguntar una vez por tipo y
    saberse el reparto por servicios."""
    r = servicio_http.get("/api/v1/comentarios/mis-menciones", headers=cabeceras)
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)


def test_la_de_un_tipo_sigue_funcionando(
    servicio_http: TestClient, cabeceras: dict[str, str]
) -> None:
    """La nueva no sustituye a la de siempre: la ficha de un registro sigue
    pidiendo las suyas por tipo."""
    r = servicio_http.get("/api/v1/comentarios/caso/mis-menciones", headers=cabeceras)
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)
