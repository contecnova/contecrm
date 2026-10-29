"""Las tres herramientas de rescate de un proceso parado (CRM-00.03.02.12).

La capacidad dice tres cosas —**reintento, salto de paso y edición de
variables**— y estaban dos. Medido el 29-10-2026: `reintentar` y
`PATCH /variables` existían; **saltar un paso no existía en ninguna parte**, y
la capacidad constaba hecha citando el esquema de la edición de variables.

Por qué importa la que faltaba. Reintentar vuelve a ejecutar lo mismo: sirve
cuando el fallo fue pasajero. Editar las variables corrige el dato: sirve
cuando el proceso se atascó por una entrada mala. Ninguna de las dos sirve
cuando el paso **no se puede completar nunca** —el servicio de un tercero que
ya no existe, la tarea humana de alguien que se fue de la empresa—, y ahí el
proceso se queda parado para siempre con todo lo que venía detrás sin hacer.

Lo que esta prueba fija, y es lo que hace que un salto no sea una puerta
trasera:

  · sólo se salta a un destino que **el propio paso declara**. Saltar a
    cualquiera dejaría meter una instancia en la rama de aprobado sin pasar
    por la aprobación, y el histórico diría que el proceso se siguió;
  · una instancia terminada no se salta: reabrirla así no la reabre, la
    falsea;
  · y queda el apunte con los DOS extremos, de dónde y a dónde. Sólo con el
    destino no se puede saber qué se saltó.

Y la otra mitad del bloque: el simulador decía por qué pasos iría un caso y no
**por cuántas manos ni en cuánto tiempo**, que es lo que decide alguien antes
de publicar (CRM-00.03.05.04).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from starlette.testclient import TestClient

pytestmark = pytest.mark.db


DEFINICION: dict[str, Any] = {
    "inicio": "pedir_visto_bueno",
    "pasos": {
        "pedir_visto_bueno": {
            "tipo": "humano",
            "asignada_rol": "responsable_ventas",
            "vence_en_horas": 48,
            "rutas": {"aprobar": "enviar", "rechazar": "fin_no"},
        },
        "enviar": {"tipo": "servicio", "operacion": "erp.enviar", "siguiente": "fin_si"},
        "fin_si": {"tipo": "fin", "resultado": "enviado"},
        "fin_no": {"tipo": "fin", "resultado": "rechazado"},
    },
}


@pytest.fixture
def cliente(db: Any) -> Any:
    import importlib
    import os

    from crmcore.config import get_settings

    previo = os.environ.get("OUTBOX_ENABLED")
    os.environ["OUTBOX_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        with TestClient(importlib.import_module("services.orchestrator.main").app) as cli:
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
    from crmcore.http.deps import H_PERMISOS, H_ROLES, H_TENANT, H_USER, firmar_cabeceras_internas

    return firmar_cabeceras_internas(
        {
            H_TENANT: str(tenant_id),
            H_USER: str(uuid4()),
            H_PERMISOS: "*:*",
            H_ROLES: "admin",
        },
        get_settings().secret_key.get_secret_value(),
    )


@pytest.fixture
def instancia_atascada(db: Any, tenant_id: UUID) -> Any:
    """Parada en la tarea humana, que es el caso real: el aprobador se fue."""
    from services.orchestrator.modelos import DefinicionProceso, InstanciaProceso

    definicion = DefinicionProceso(
        tenant_id=tenant_id,
        clave="pedido_grande",
        version=1,
        nombre="Pedido grande",
        definicion=DEFINICION,
        estado="publicada",
    )
    db.add(definicion)
    db.flush()
    instancia = InstanciaProceso(
        tenant_id=tenant_id,
        definicion_id=definicion.id,
        clave="pedido_grande",
        version=1,
        estado="esperando",
        paso_actual="pedir_visto_bueno",
        variables={"importe": 30000},
    )
    db.add(instancia)
    db.flush()
    return instancia


# ── Saltar un paso ────────────────────────────────────────────────────────


def test_se_salta_a_un_destino_que_el_paso_declara(
    cliente: Any, cabeceras: dict[str, str], instancia_atascada: Any, db: Any
) -> None:
    r = cliente.post(
        f"/api/v1/instancias/{instancia_atascada.id}/saltar-paso",
        headers=cabeceras,
        json={"destino": "fin_no", "motivo": "el aprobador ya no está en la empresa"},
    )
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["paso_actual"] == "fin_no", cuerpo
    assert cuerpo["estado"] == "ejecutando", cuerpo


def test_no_se_salta_a_un_paso_que_el_actual_no_enlaza(
    cliente: Any, cabeceras: dict[str, str], instancia_atascada: Any
) -> None:
    """El que hace que esto no sea una puerta trasera.

    «enviar» existe en la definición y **no es un destino de la tarea humana**
    por la vía corta: se llega a él aprobando. Dejar saltar ahí sería meter el
    pedido en la rama de aprobado sin que nadie lo aprobara, y el histórico
    diría que el proceso se siguió.
    """
    r = cliente.post(
        f"/api/v1/instancias/{instancia_atascada.id}/saltar-paso",
        headers=cabeceras,
        json={"destino": "fin_si", "motivo": "a ver si cuela por la puerta de atrás"},
    )
    assert r.status_code == 409, r.text
    cuerpo = r.json()
    assert "destino_no_declarado" in str(cuerpo), cuerpo
    # Y dice cuáles SÍ: un rechazo que no dice la alternativa obliga a abrir
    # la definición a mano.
    assert "enviar" in str(cuerpo) and "fin_no" in str(cuerpo), cuerpo


def test_una_instancia_terminada_no_se_salta(
    cliente: Any, cabeceras: dict[str, str], instancia_atascada: Any, db: Any
) -> None:
    instancia_atascada.estado = "terminada"
    db.flush()
    r = cliente.post(
        f"/api/v1/instancias/{instancia_atascada.id}/saltar-paso",
        headers=cabeceras,
        json={"destino": "fin_no", "motivo": "reabrir un proceso cerrado a mano"},
    )
    assert r.status_code == 409, r.text


def test_el_salto_queda_apuntado_con_los_dos_extremos(
    cliente: Any, cabeceras: dict[str, str], instancia_atascada: Any, db: Any
) -> None:
    """De dónde y a dónde. Con sólo el destino no se sabe qué se saltó."""
    from crmcore.audit.modelos import ApunteAuditoria
    from sqlalchemy import select

    cliente.post(
        f"/api/v1/instancias/{instancia_atascada.id}/saltar-paso",
        headers=cabeceras,
        json={"destino": "fin_no", "motivo": "el aprobador ya no está en la empresa"},
    )
    apunte = db.execute(
        select(ApunteAuditoria).where(ApunteAuditoria.accion == "proceso.paso_saltado")
    ).scalar_one_or_none()
    assert apunte is not None, "un salto sin apunte es una puerta trasera con permiso"
    assert apunte.datos["desde"] == "pedir_visto_bueno", apunte.datos
    assert apunte.datos["hasta"] == "fin_no", apunte.datos
    assert apunte.motivo


# ── Quién aprobaría y cuánto tardaría ─────────────────────────────────────


def test_la_simulacion_dice_quien_aprobaria_y_cuanto_tardaria(
    cliente: Any, cabeceras: dict[str, str]
) -> None:
    """La otra mitad de «¿qué le pasa a un pedido de 30.000 € si publico esto?».

    El recorrido decía por qué pasos iría. Por cuántas manos y en cuánto
    tiempo —las dos cosas que decide alguien— no las decía nadie.
    """
    r = cliente.post(
        "/api/v1/procesos/definiciones/simular",
        headers=cabeceras,
        json={
            "clave": "pedido_grande",
            "nombre": "Pedido grande",
            "definicion": DEFINICION,
            "variables": {"importe": 30000},
            "respuestas_humanas": {"pedir_visto_bueno": "aprobar"},
        },
    )
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["valida"] is True, cuerpo
    assert cuerpo["quien_aprobaria"] == [
        {"paso": "pedir_visto_bueno", "quien": "responsable_ventas", "horas": 48}
    ], cuerpo["quien_aprobaria"]
    assert cuerpo["horas_declaradas"] == 48, cuerpo
    assert cuerpo["pasos_sin_plazo"] == [], cuerpo


def test_un_paso_humano_sin_plazo_no_suma_cero_y_se_dice(
    cliente: Any, cabeceras: dict[str, str]
) -> None:
    """Un proceso que espera a una persona sin fecha no tarda cero: tarda lo
    que tarde. Callarlo convierte el total en un número que engaña."""
    definicion = {
        "inicio": "pedir_visto_bueno",
        "pasos": {
            **DEFINICION["pasos"],
            "pedir_visto_bueno": {
                "tipo": "humano",
                "asignada_rol": "responsable_ventas",
                "rutas": {"aprobar": "enviar", "rechazar": "fin_no"},
            },
        },
    }
    r = cliente.post(
        "/api/v1/procesos/definiciones/simular",
        headers=cabeceras,
        json={
            "clave": "sin_plazo",
            "nombre": "Sin plazo",
            "definicion": definicion,
            "variables": {},
            "respuestas_humanas": {"pedir_visto_bueno": "aprobar"},
        },
    )
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["horas_declaradas"] == 0, cuerpo
    assert cuerpo["pasos_sin_plazo"] == ["pedir_visto_bueno"], cuerpo
    assert "no tarda cero" in cuerpo["que_significa"], cuerpo["que_significa"]


# ── Lo que lee la pantalla de la instancia ────────────────────────────────
#
# El trinquete de `test_la_pantalla_no_lee_campos_que_nadie_envia.py` las pidió
# el mismo día que se escribió la pantalla: dos rutas de las que declara la
# forma de la respuesta. Recorrerlas por HTTP es lo único que impide que un
# campo que el servidor deja de mandar deje el panel vacío sin que falle nada.


def test_el_grafico_de_la_instancia_trae_lo_que_pinta_la_pantalla(
    cliente: Any, cabeceras: dict[str, str], instancia_atascada: Any
) -> None:
    """Cada nodo con su estado, y la VERSIÓN.

    La versión no es un adorno: sin ella, quien mira el gráfico no sabe si está
    viendo el proceso que se ejecutó o el que se publicó después. La pantalla
    pide la definición de esa versión exacta para pintar encima.
    """
    r = cliente.get(
        f"/api/v1/analitica-procesos/instancias/{instancia_atascada.id}/grafico",
        headers=cabeceras,
    )
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    for clave in (
        "instancia_id",
        "proceso",
        "version",
        "estado",
        "paso_actual",
        "nodos",
        "recorrido",
    ):
        assert clave in cuerpo, f"falta «{clave}»: llegan {sorted(cuerpo)}"
    assert cuerpo["version"] == 1, cuerpo
    assert isinstance(cuerpo["nodos"], list) and cuerpo["nodos"], cuerpo
    nodo = next(n for n in cuerpo["nodos"] if n["paso"] == "pedir_visto_bueno")
    # Lo que decide el color del borde Y el texto de debajo. Un nodo sin
    # `estado` se pintaría como pendiente y diría que falta hacer algo que
    # quizá ya pasó.
    assert nodo["estado"] == "actual", nodo
    assert "tipo" in nodo and "veces" in nodo, nodo


def test_la_analitica_del_proceso_dice_si_es_concluyente(
    cliente: Any, cabeceras: dict[str, str], instancia_atascada: Any
) -> None:
    """Con una sola ejecución, el dato NO es concluyente y hay que decirlo.

    Un cuello de botella deducido de tres ejecuciones lleva a rediseñar un
    flujo que funcionaba. La pantalla pinta el aviso en ámbar; sin el campo, lo
    pintaría como un dato firme.
    """
    r = cliente.get("/api/v1/analitica-procesos/pedido_grande", headers=cabeceras)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    for clave in ("proceso", "instancias", "pasos", "cuello_de_botella"):
        assert clave in cuerpo, f"falta «{clave}»: llegan {sorted(cuerpo)}"
    assert cuerpo["instancias"] >= 1, cuerpo
    # La mediana al lado de la media: con una espera de tres días entre veinte,
    # la media dice que todo va bien.
    assert "ciclo_horas_medio" in cuerpo and "ciclo_horas_mediana" in cuerpo, sorted(cuerpo)
    assert cuerpo.get("concluyente") is False, cuerpo
    assert str(cuerpo.get("aviso") or "").strip(), cuerpo
