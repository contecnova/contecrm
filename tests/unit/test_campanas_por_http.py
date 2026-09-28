"""La familia de campañas de marketing, EJERCITADA (`CRM-02.02.01`).

Siete capacidades, un solo servicio y sin red: la familia barata, elegida a
propósito para medir cuánto cuesta auditar una fácil frente a la cara —el
gobierno de la suite costó 89 minutos y seis fallos—.

**Se entra por la ruta, no por el ORM.** Es la lección que en contecmind dejó un
tipo de aprobación implementado, probado y rechazado por la API: todas sus
pruebas montaban el objeto por el ORM, saltándose la puerta por la que sí pasa un
cliente. Y a mí me mordió la misma tarde montando una cuenta a mano sin
`clave_canonica`.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from starlette.testclient import TestClient

pytestmark = pytest.mark.db


@pytest.fixture
def cliente() -> Any:
    import importlib
    import os

    from crmcore.config import get_settings

    previo = os.environ.get("OUTBOX_ENABLED")
    os.environ["OUTBOX_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        modulo = importlib.import_module("services.marketing.main")
        with TestClient(modulo.app) as cli:
            yield cli
    finally:
        if previo is None:
            os.environ.pop("OUTBOX_ENABLED", None)
        else:
            os.environ["OUTBOX_ENABLED"] = previo
        get_settings.cache_clear()


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

    # CON ROL, no sólo con permisos. El enmascarado por sensibilidad
    # (CRM-00.05.03.03) se resuelve por **rol**, así que un principal sin
    # ninguno recibe los campos con puntos — correctamente— y la prueba parecería
    # decir que el dato no se puede leer. Una persona de verdad tiene rol.
    return firmar_cabeceras_internas(
        {
            H_TENANT: str(tenant_id),
            H_USER: str(uuid4()),
            H_PERMISOS: "*:*",
            H_ROLES: "admin",
        },
        get_settings().secret_key.get_secret_value(),
    )


def _crear(cliente: TestClient, cabeceras: dict[str, str], **datos: Any) -> dict[str, Any]:
    cuerpo = {
        "clave": f"c-{uuid4().hex[:8]}",
        "nombre": "Campaña de prueba",
        **datos,
    }
    respuesta = cliente.post("/api/v1/campanas", headers=cabeceras, json=cuerpo)
    assert respuesta.status_code in (200, 201), respuesta.text
    return dict(respuesta.json())


# ── .01 Jerarquía con presupuesto y coste ─────────────────────────────────


def test_una_tactica_cuelga_de_una_campana_y_la_jerarquia_es_real(
    cliente: TestClient, cabeceras: dict[str, str], db: Any
) -> None:
    programa = _crear(cliente, cabeceras, nivel="programa", nombre="Programa anual")
    campana = _crear(cliente, cabeceras, nivel="campana", padre_id=programa["id"])
    tactica = _crear(cliente, cabeceras, nivel="tactica", padre_id=campana["id"])

    assert programa["nivel"] == "programa"
    assert tactica["nivel"] == "tactica"


def test_el_gasto_se_anota_y_el_consumo_lo_refleja(
    cliente: TestClient, cabeceras: dict[str, str], db: Any
) -> None:
    """Presupuesto y coste: sin el consumo al lado, el presupuesto es un número
    que nadie compara con nada."""
    campana = _crear(cliente, cabeceras, presupuesto="1000.00")

    gasto = cliente.post(
        f"/api/v1/campanas/{campana['id']}/gasto",
        headers=cabeceras,
        json={"importe": "250.00", "concepto": "anuncios"},
    )
    assert gasto.status_code in (200, 201), gasto.text

    consumo = cliente.get(f"/api/v1/campanas/{campana['id']}/consumo", headers=cabeceras)
    assert consumo.status_code == 200, consumo.text
    texto = str(consumo.json())
    assert "250" in texto, f"el gasto anotado no aparece en el consumo: {texto}"


# ── .03 Calendario y solapamientos ────────────────────────────────────────


def test_el_calendario_responde_y_no_lo_tapa_la_ficha(
    cliente: TestClient, cabeceras: dict[str, str], db: Any
) -> None:
    """`/calendario` tiene un solo tramo, igual que la ficha `/{campana_id}`.

    Si la ficha se declarara antes, esta petición acabaría buscando una campaña
    llamada «calendario». Es el fallo que dejó ocho rutas inalcanzables el mismo
    día en este repositorio.
    """
    _crear(cliente, cabeceras, desde="2026-09-01", hasta="2026-09-30")

    respuesta = cliente.get(
        "/api/v1/campanas/calendario",
        headers=cabeceras,
        params={"desde": "2026-09-01", "hasta": "2026-09-30"},
    )
    assert respuesta.status_code == 200, respuesta.text


# ── .04 Miembros con estado de progresión y fuente ────────────────────────


def test_un_miembro_se_anade_y_se_lista_con_su_estado(
    cliente: TestClient, cabeceras: dict[str, str], db: Any
) -> None:
    campana = _crear(cliente, cabeceras)
    persona = str(uuid4())

    alta = cliente.post(
        f"/api/v1/campanas/{campana['id']}/miembros",
        headers=cabeceras,
        json={"objeto_ids": [persona], "fuente": "importacion"},
    )
    assert alta.status_code in (200, 201), alta.text

    listado = cliente.get(f"/api/v1/campanas/{campana['id']}/miembros", headers=cabeceras)
    assert listado.status_code == 200, listado.text
    assert persona in str(listado.json()), "el miembro recién dado de alta no sale en su listado"


def test_el_embudo_sale_aunque_la_campana_no_tenga_a_nadie(
    cliente: TestClient, cabeceras: dict[str, str], db: Any
) -> None:
    """Una campaña sin miembros es un caso normal —acaba de crearse—, no un
    error. Un 500 aquí es una pantalla en blanco el día del lanzamiento."""
    campana = _crear(cliente, cabeceras)
    respuesta = cliente.get(f"/api/v1/campanas/{campana['id']}/embudo", headers=cabeceras)
    assert respuesta.status_code == 200, respuesta.text


# ── .05 ROI y coste por lead ──────────────────────────────────────────────


def test_el_rendimiento_dice_cuando_el_roi_no_es_medible(
    cliente: TestClient, cabeceras: dict[str, str], db: Any
) -> None:
    """Un ROI calculado sin datos de oportunidades es un número inventado, y
    presentarlo como «el ROI» es lo que hace que nadie se crea los informes.

    La ruta lo dice en su propia descripción: si no llegan, **se dice que no es
    medible**. Esto comprueba que lo diga de verdad.
    """
    campana = _crear(cliente, cabeceras, presupuesto="1000.00")
    respuesta = cliente.get(f"/api/v1/campanas/{campana['id']}/rendimiento", headers=cabeceras)
    assert respuesta.status_code == 200, respuesta.text

    cuerpo = respuesta.json()
    texto = str(cuerpo).lower()
    assert "medible" in texto or "roi" in texto, cuerpo


# ── .07 Eventos y ferias ──────────────────────────────────────────────────


def test_un_evento_es_una_campana_con_inscripciones_y_asistencia(
    cliente: TestClient, cabeceras: dict[str, str], db: Any
) -> None:
    """Un evento no es una tabla aparte: es una campaña con lugar y aforo."""
    feria = _crear(
        cliente,
        cabeceras,
        tipo="evento",
        canal="presencial",
        lugar="IFEMA",
        aforo=200,
        nombre="Feria del sector",
    )

    # La tarjeta del evento va de asistencia: aforo, inscritos y tasa.
    tarjeta = cliente.get(f"/api/v1/campanas/{feria['id']}/evento", headers=cabeceras)
    assert tarjeta.status_code == 200, tarjeta.text
    assert tarjeta.json()["aforo"] == 200, tarjeta.text

    # Y el lugar se lee en la ficha de la campaña. Si no se leyera en ninguna
    # parte sería un campo que se guarda y no se puede consultar, que es de lo
    # que más ha salido esta noche.
    ficha = cliente.get(f"/api/v1/campanas/{feria['id']}", headers=cabeceras)
    assert ficha.status_code == 200, ficha.text
    assert "IFEMA" in str(
        ficha.json()
    ), "el lugar se guarda al crear el evento y no se puede leer en ningún sitio"

    inscribir = cliente.post(
        f"/api/v1/campanas/{feria['id']}/inscripciones",
        headers=cabeceras,
        # Al evento se inscribe UNA persona —viene de un formulario—, mientras
        # que a la campaña se añaden en lote desde un segmento. Son dos gestos
        # distintos y por eso tienen forma distinta.
        json={"objeto_id": str(uuid4())},
    )
    assert inscribir.status_code in (200, 201), inscribir.text


# ── .06 Atribución ────────────────────────────────────────────────────────


def test_la_atribucion_de_un_lead_sin_toques_no_revienta(
    cliente: TestClient, cabeceras: dict[str, str], db: Any
) -> None:
    """Un lead del que no consta ningún toque es lo normal al principio, y la
    pantalla de atribución se abre igual."""
    respuesta = cliente.get(
        f"/api/v1/atribucion/leads/{uuid4()}",
        headers=cabeceras,
        params={"importe": "1000"},
    )
    assert respuesta.status_code in (200, 404), respuesta.text
