"""Las puertas de la IA aplicada, EJERCITADAS por HTTP
(CRM-02.01.01.08, CRM-02.01.02.02, CRM-02.01.02.06, CRM-04.02.01.08,
CRM-04.03.01.04, CRM-00.01.05.04).

Once funciones de este servicio estaban **escritas, probadas y sin que las
llamara nadie**: la partición temporal que evita que el modelo vea el futuro, el
recorte de datos personales antes de mandar un caso a un proveedor de inferencia,
el permiso que tiene que declarar cualquier cosa antes de entrar en el índice, el
traspaso de una llamada con lo que ya se habló, la diferencia entre avisar de que
se graba y consentir el entrenamiento, y el modo sin salida de datos.

Ninguna daba error. Un módulo sin llamante no rompe nada: hace que el producto se
comporte como si esa decisión no existiera. El modelo entrena con el futuro y
acierta magníficamente, la ficha entera sale hacia el proveedor, el fragmento se
indexa sin saber quién puede verlo, y la persona que coge el teléfono empieza de
cero. Todo verde.

**Se entra por la ruta, no por el módulo.** Las pruebas que llamaban a las
funciones directamente ya existían y pasaban — por eso el agujero sobrevivió. Lo
que aquí se fija es que hay una puerta y que al otro lado está esa decisión.
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
        modulo = importlib.import_module("services.intelligence.main")
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

    return firmar_cabeceras_internas(
        {
            H_TENANT: str(tenant_id),
            H_USER: str(uuid4()),
            H_PERMISOS: "*:*",
            H_ROLES: "admin",
        },
        get_settings().secret_key.get_secret_value(),
    )


# ── Lo que sale hacia el modelo (CRM-04.03.01.04) ─────────────────────────


def test_el_caso_sale_sin_el_nombre_de_quien_lo_tiene(
    cliente: Any, cabeceras: dict[str, str]
) -> None:
    """El recorte lo hace el servidor, y se puede mirar qué salió.

    La ruta recibía el contexto **ya compuesto** por quien llamaba: la decisión de
    qué datos personales salen hacia un proveedor de inferencia estaba en cada
    pantalla, y basta con que una la tome mal. Ahora entra la ficha y el recorte
    se hace aquí.
    """
    caso_id = uuid4()
    cuerpo = {
        "resultados": [],
        "caso": {
            "asunto": "No sincroniza el correo",
            "descripcion": "Desde la actualización",
            "producto": "Buzón",
            "version": "4.2",
            "contacto": "Marta Ruiz",
            "telefono": "600 000 000",
        },
    }
    r = cliente.post(f"/api/v1/sugerencias-caso/{caso_id}", headers=cabeceras, json=cuerpo)
    assert r.status_code == 200, r.text
    salida = r.json()["lo_que_se_manda"]

    assert salida["lleva_datos_personales"] is False
    assert "contacto" not in salida["contexto"]
    assert "telefono" not in salida["contexto"]
    # Y sigue llevando el problema, que es para lo que sirve.
    assert salida["contexto"]["asunto"] == "No sincroniza el correo"
    assert salida["contexto"]["version"] == "4.2"
    # Y lo que se COMPARÓ es ese recorte, no la ficha. Sin esta comprobación la
    # prueba se contenta con que el recorte exista, y una ruta que lo calcula,
    # lo enseña y luego usa la ficha entera pasa igual de verde.
    assert r.json()["contexto_usado"] == salida["contexto"]


def test_los_datos_personales_salen_solo_si_alguien_lo_pide(
    cliente: Any, cabeceras: dict[str, str]
) -> None:
    caso_id = uuid4()
    cuerpo = {
        "caso": {"asunto": "Avería", "contacto": "Marta Ruiz"},
        "incluir_datos_personales": True,
    }
    r = cliente.post(f"/api/v1/sugerencias-caso/{caso_id}", headers=cabeceras, json=cuerpo)
    assert r.status_code == 200, r.text
    salida = r.json()["lo_que_se_manda"]
    assert salida["lleva_datos_personales"] is True
    assert salida["contexto"]["contacto"] == "Marta Ruiz"


def test_no_se_indexa_lo_que_no_dice_quien_puede_verlo(
    cliente: Any, cabeceras: dict[str, str]
) -> None:
    """Filtrar después de buscar ya es tarde: el fragmento ya está dentro."""
    r = cliente.post(
        "/api/v1/sugerencias-caso/indexables",
        headers=cabeceras,
        json={
            "elementos": [
                {"objeto": "articulo", "permiso": "kb:read"},
                {"objeto": "caso", "permiso": None},
            ]
        },
    )
    assert r.status_code == 422, r.text
    assert r.json()["error_code"] == "semantica.sin_permiso_declarado"

    ok = cliente.post(
        "/api/v1/sugerencias-caso/indexables",
        headers=cabeceras,
        json={"elementos": [{"objeto": "articulo", "permiso": "kb:read"}]},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["indexables"] == 1


def test_el_aprovechamiento_se_mide_por_lo_que_se_usa(
    cliente: Any, cabeceras: dict[str, str]
) -> None:
    """Abrir una sugerencia es mirar si sirve, y casi nunca sirve."""
    sugerencias = [{"abierta": True, "usada": False} for _ in range(9)]
    sugerencias.append({"abierta": True, "usada": True})
    r = cliente.post(
        "/api/v1/sugerencias-caso/aprovechamiento",
        headers=cabeceras,
        json={"sugerencias": sugerencias},
    )
    assert r.status_code == 200, r.text
    salida = r.json()
    assert salida["abiertas"] == 10
    assert salida["usadas"] == 1
    assert salida["pct_usadas"] == 10.0
    assert salida["sirve"] is False


# ── Entrenamiento (CRM-02.01.02.02) ───────────────────────────────────────


def test_la_particion_es_por_fecha_y_no_al_azar(cliente: Any, cabeceras: dict[str, str]) -> None:
    """El modelo se entrena con lo viejo y se comprueba con lo nuevo.

    Repartir al azar mete casos posteriores en el entrenamiento: el modelo ha
    visto cómo acabó lo que tiene que predecir y el acierto no significa nada.
    """
    casos = [{"ref": i, "cerrado_el": f"2026-0{i}-01"} for i in range(1, 9)]
    r = cliente.post(
        "/api/v1/modelos/particion",
        headers=cabeceras,
        json={"casos": list(reversed(casos)), "pct_validacion": 25},
    )
    assert r.status_code == 200, r.text
    salida = r.json()

    # Lo que valida son los DOS últimos por fecha, no dos cualesquiera.
    assert [c["ref"] for c in salida["validacion"]] == [7, 8]
    assert [c["ref"] for c in salida["entrenamiento"]] == [1, 2, 3, 4, 5, 6]
    assert salida["corte"] == "2026-07-01"


def test_un_caso_sin_fecha_para_la_particion(cliente: Any, cabeceras: dict[str, str]) -> None:
    r = cliente.post(
        "/api/v1/modelos/particion",
        headers=cabeceras,
        json={"casos": [{"cerrado_el": "2026-01-01"}, {"ref": "sin fecha"}]},
    )
    assert r.status_code == 422, r.text
    assert r.json()["error_code"] == "modelo.caso_sin_fecha"


# ── Transcripción (CRM-02.01.02.06) ───────────────────────────────────────


def test_el_coste_de_transcribir_se_dice_antes_de_transcribir(
    cliente: Any, cabeceras: dict[str, str]
) -> None:
    """Una biblioteca de tres años de llamadas es una factura, no un botón."""
    r = cliente.post(
        "/api/v1/transcripciones/coste",
        headers=cabeceras,
        json={"minutos_totales": 12000, "coste_por_minuto": 0.02, "presupuesto": 100},
    )
    assert r.status_code == 200, r.text
    salida = r.json()
    assert salida["coste_estimado"] == 240.0
    assert salida["cabe_en_el_presupuesto"] is False
    # Y no ha transcrito nada: dice el importe para que alguien lo confirme.
    assert salida["se_ejecuta_ya"] is False


def test_la_calidad_de_la_extraccion_dice_si_merece_la_pena(
    cliente: Any, cabeceras: dict[str, str]
) -> None:
    confirmadas = [{"hubo_correccion": i < 5} for i in range(10)]
    r = cliente.post(
        "/api/v1/transcripciones/calidad", headers=cabeceras, json={"confirmadas": confirmadas}
    )
    assert r.status_code == 200, r.text
    salida = r.json()
    assert salida["pct_corregidas"] == 50.0
    assert salida["merece_la_pena"] is False


# ── Variantes (CRM-02.01.01.08) ───────────────────────────────────────────


def test_con_pocos_envios_no_hay_ganadora(cliente: Any, cabeceras: dict[str, str]) -> None:
    """La diferencia entre un 4,1 % y un 4,4 % con doscientos envíos es ruido."""
    r = cliente.post(
        "/api/v1/variantes/ganadora",
        headers=cabeceras,
        json={
            "ramas": [
                {"texto": "A", "enviados": 200, "respuestas": 9},
                {"texto": "B", "enviados": 200, "respuestas": 8},
            ]
        },
    )
    assert r.status_code == 200, r.text
    salida = r.json()
    assert salida["hay_ganadora"] is False
    assert "ruido" in salida["porque"]


def test_el_rendimiento_dice_cuanto_se_reescribe(cliente: Any, cabeceras: dict[str, str]) -> None:
    aprobaciones = [{"hubo_reescritura": i < 8} for i in range(10)]
    r = cliente.post(
        "/api/v1/variantes/rendimiento", headers=cabeceras, json={"aprobaciones": aprobaciones}
    )
    assert r.status_code == 200, r.text
    salida = r.json()
    assert salida["pct_reescritas"] == 80.0
    assert "punto de partida" in salida["que_significa"]


# ── Voz (CRM-04.02.01.08) ─────────────────────────────────────────────────


def test_el_traspaso_lleva_lo_que_ya_se_hablo(cliente: Any, cabeceras: dict[str, str]) -> None:
    """Si la persona empieza de cero, el asistente perdió tres minutos del cliente."""
    r = cliente.post(
        "/api/v1/voz/entender",
        headers=cabeceras,
        json={
            "texto": "no te entiendo",
            "confianza": 0.2,
            "intento": 2,
            "lo_ya_dicho": ["Quiero cambiar la cita", "Es la del jueves"],
            "datos_recogidos": {"pedido": "A-1193"},
        },
    )
    assert r.status_code == 200, r.text
    salida = r.json()
    assert salida["pasar_a_persona"] is True
    traspaso = salida["traspaso"]
    assert traspaso["lo_ya_dicho"] == ["Quiero cambiar la cita", "Es la del jueves"]
    assert traspaso["datos_recogidos"] == {"pedido": "A-1193"}
    assert traspaso["el_cliente_no_repite"] is True
    assert traspaso["motivo"]


def test_mientras_se_repregunta_no_hay_traspaso(cliente: Any, cabeceras: dict[str, str]) -> None:
    r = cliente.post(
        "/api/v1/voz/entender",
        headers=cabeceras,
        json={"texto": "...", "confianza": 0.2, "intento": 0},
    )
    assert r.status_code == 200, r.text
    salida = r.json()
    assert salida["repreguntar"] is True
    assert "traspaso" not in salida


def test_avisar_de_que_se_graba_no_es_consentimiento_para_entrenar(
    cliente: Any, cabeceras: dict[str, str]
) -> None:
    """Son dos permisos distintos, y es lo que más se confunde en voz."""
    r = cliente.post(
        "/api/v1/voz/apertura",
        headers=cabeceras,
        json={"nombre_asistente": "Nora", "es_maquina": True, "graba": True},
    )
    assert r.status_code == 200, r.text
    salida = r.json()
    assert salida["entrenar_con_este_audio"]["puede"] is False

    con_permiso = cliente.post(
        "/api/v1/voz/apertura",
        headers=cabeceras,
        json={
            "nombre_asistente": "Nora",
            "graba": True,
            "consentimiento_entrenamiento": True,
        },
    )
    assert con_permiso.status_code == 200, con_permiso.text
    assert con_permiso.json()["entrenar_con_este_audio"]["puede"] is True


# ── Modo sin salida de datos (CRM-00.01.05.04) ────────────────────────────


def test_sin_salida_elige_el_modelo_del_propio_cliente(
    cliente: Any, cabeceras: dict[str, str], db: Any
) -> None:
    """El del cliente gana: es la única opción que no depende de la promesa de nadie."""
    alta = cliente.post(
        "/api/v1/ia/proveedores",
        headers=cabeceras,
        json={
            "clave": "modelo-de-casa",
            "base_url": "https://ia.interna.local",
            "region": "ue",
            "admite_opt_out": True,
            "solo_este_tenant": True,
        },
    )
    assert alta.status_code == 201, alta.text
    politica = cliente.post(
        "/api/v1/ia/politica",
        headers=cabeceras,
        json={"regiones_admitidas": ["ue"], "exigir_opt_out": True},
    )
    assert politica.status_code == 200, politica.text

    r = cliente.get("/api/v1/ia/eleccion-sin-salida?uso=redaccion", headers=cabeceras)
    assert r.status_code == 200, r.text
    salida = r.json()
    assert salida["sin_salida"] is True
    assert salida["propio_del_tenant"] is True


def test_sin_salida_no_elige_la_region_por_el_cliente(
    cliente: Any, cabeceras: dict[str, str], db: Any
) -> None:
    """Con dos regiones admitidas hay que decir cuál, y por eso existe este modo."""
    cliente.post(
        "/api/v1/ia/proveedores",
        headers=cabeceras,
        json={
            "clave": "uno",
            "base_url": "https://ia.ejemplo.test",
            "region": "ue",
            "admite_opt_out": True,
        },
    )
    politica = cliente.post(
        "/api/v1/ia/politica",
        headers=cabeceras,
        json={"regiones_admitidas": ["ue", "suiza"]},
    )
    assert politica.status_code == 200, politica.text

    r = cliente.get("/api/v1/ia/eleccion-sin-salida", headers=cabeceras)
    assert r.status_code == 422, r.text
    assert r.json()["error_code"] == "ia.region_del_tenant_sin_decidir"

    # Y dicha explícitamente, contesta.
    con_region = cliente.get("/api/v1/ia/eleccion-sin-salida?region=ue", headers=cabeceras)
    assert con_region.status_code == 200, con_region.text
    assert con_region.json()["sin_salida"] is True
