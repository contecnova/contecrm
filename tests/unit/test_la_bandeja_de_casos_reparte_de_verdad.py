"""La bandeja repartía en el navegador, con un umbral a fuego y cuentas falsas.

Tres cosas estaban mal a la vez, y las tres se ven sólo cuando hay volumen:

  · **el corte entre «en riesgo» y «el resto» eran cuatro horas escritas a
    mano** en una expresión del front (`4 * 3600_000`). Cuatro horas en un
    soporte con SLA de cuatro horas pone la bandeja entera en rojo; en uno de
    cinco días avisa cuando ya no da tiempo a nada;
  · **los totales se contaban sobre la página traída.** El listado pagina de
    cincuenta en cincuenta, así que la bandeja decía «3 incumplidos» habiendo
    cincuenta, con su cara de cifra buena;
  · y la pantalla leía campos que la API **no devuelve** —`vence_at`,
    `numero`, `escalado`—, así que todos los casos caían en «el resto» y el
    reloj decía siempre «sin SLA».

Ahora reparte el servidor, con el umbral del tenant y contando sobre todo.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from starlette.testclient import TestClient

pytestmark = pytest.mark.db


@pytest.fixture
def cliente(db: Any) -> Any:
    import importlib
    import os

    from crmcore.config import get_settings

    previo = os.environ.get("OUTBOX_ENABLED")
    os.environ["OUTBOX_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        modulo = importlib.import_module("services.service.main")
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
            H_USER: str(uuid4()),
            H_PERMISOS: "*:*",
            H_ROLES: "agente",
            H_FACTOR_FUERTE: datetime.now(timezone.utc).isoformat(),
        },
        get_settings().secret_key.get_secret_value(),
    )


def _caso(db: Any, tenant_id: UUID, asunto: str, *, horas: float | None, incumplio: bool = False):
    from services.service.modelos import Caso

    fila = Caso(
        tenant_id=tenant_id,
        asunto=asunto,
        codigo=asunto.upper(),
        estado="nuevo",
        vence_resolucion_at=(
            datetime.now(timezone.utc) + timedelta(hours=horas) if horas is not None else None
        ),
        incumplio_resolucion=incumplio,
    )
    db.add(fila)
    return fila


@pytest.fixture
def una_bandeja(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    _caso(db, tenant_id, "tarde", horas=-3)  # ya incumplió por fecha
    _caso(db, tenant_id, "marcado", horas=48, incumplio=True)  # marcado por el motor
    _caso(db, tenant_id, "justo", horas=2)  # dentro de las 4 h por defecto
    _caso(db, tenant_id, "holgado", horas=30)  # fuera
    _caso(db, tenant_id, "sin_plazo", horas=None)  # sin SLA
    db.flush()


def _montones(respuesta: Any) -> dict[str, set[str]]:
    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    return {
        k: {c["asunto"] for c in cuerpo[k]["casos"]} for k in ("incumplidos", "en_riesgo", "resto")
    }


# ── El reparto ────────────────────────────────────────────────────────────


def test_los_tres_montones_son_tres_trabajos_distintos(
    cliente: Any, cabeceras: dict[str, str], una_bandeja: None
) -> None:
    """Lo que ya incumplió se explica; lo que va a incumplir se salva. Una
    bandeja que los mezcla hace que se atienda por orden de llegada, que es el
    único orden que garantiza incumplir los dos."""
    m = _montones(cliente.get("/api/v1/casos/bandeja", headers=cabeceras))
    assert m["incumplidos"] == {"tarde", "marcado"}
    assert m["en_riesgo"] == {"justo"}
    assert m["resto"] == {"holgado", "sin_plazo"}


def test_lo_marcado_por_el_motor_cuenta_aunque_su_fecha_se_haya_movido(
    cliente: Any, cabeceras: dict[str, str], una_bandeja: None
) -> None:
    """«marcado» vence dentro de 48 h y aun así incumplió: el incumplimiento ya
    ocurrió, y moverle la fecha después no lo borra."""
    m = _montones(cliente.get("/api/v1/casos/bandeja", headers=cabeceras))
    assert "marcado" in m["incumplidos"]
    assert "marcado" not in m["resto"]


def test_un_caso_sin_plazo_no_se_esconde(
    cliente: Any, cabeceras: dict[str, str], una_bandeja: None
) -> None:
    """«Sin plazo» no es «urgente» ni «tranquilo»: es un caso que nadie ha
    clasificado. Dejarlo fuera de los tres montones lo deja sin atender para
    siempre."""
    m = _montones(cliente.get("/api/v1/casos/bandeja", headers=cabeceras))
    assert "sin_plazo" in m["resto"]


def test_lo_cerrado_no_es_trabajo_pendiente(
    cliente: Any, cabeceras: dict[str, str], una_bandeja: None, db: Any, tenant_id: UUID
) -> None:
    """Si entrara, la bandeja crecería para siempre y dejaría de abrirse."""
    _caso(db, tenant_id, "ya_resuelto", horas=-10).estado = "resuelto"
    db.flush()
    todos = set().union(
        *_montones(cliente.get("/api/v1/casos/bandeja", headers=cabeceras)).values()
    )
    assert "ya_resuelto" not in todos


# ── El umbral ─────────────────────────────────────────────────────────────


def test_el_umbral_es_un_ajuste_y_se_puede_mover(
    cliente: Any, cabeceras: dict[str, str], una_bandeja: None, db: Any, tenant_id: UUID
) -> None:
    """**El fallo original.** Eran cuatro horas escritas en una expresión del
    navegador, iguales para todos los clientes del despliegue."""
    from crmcore.runtime import settings as rt

    # Con el defecto, «holgado» (30 h) está tranquilo.
    assert "holgado" in _montones(cliente.get("/api/v1/casos/bandeja", headers=cabeceras))["resto"]

    # Un soporte con SLA de días quiere avisar con más antelación.
    rt.fijar(db, "sla_riesgo_horas", 48, ambito="tenant", ambito_id=str(tenant_id))
    db.flush()

    m = _montones(cliente.get("/api/v1/casos/bandeja", headers=cabeceras))
    assert "holgado" in m["en_riesgo"], "el umbral del tenant no se está aplicando"
    assert "sin_plazo" in m["resto"], "lo que no tiene plazo no entra en riesgo al subir el umbral"


def test_la_respuesta_dice_con_qué_umbral_se_repartió(
    cliente: Any, cabeceras: dict[str, str], una_bandeja: None
) -> None:
    """Sin eso, quien ve un caso en «en riesgo» y otro parecido fuera no puede
    saber por qué, y acaba preguntando."""
    cuerpo = cliente.get("/api/v1/casos/bandeja", headers=cabeceras).json()
    assert cuerpo["riesgo_horas"] == 4.0
    assert cuerpo["ahora"]


# ── Las cuentas ───────────────────────────────────────────────────────────


def test_el_total_es_de_TODO_y_no_de_lo_que_se_devuelve(
    cliente: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Es la mitad que más engaña: una bandeja que dice «3 incumplidos»
    habiendo cincuenta se mira una vez."""
    for n in range(12):
        _caso(db, tenant_id, f"viejo_{n}", horas=-1)
    db.flush()

    cuerpo = cliente.get("/api/v1/casos/bandeja?por_monton=5", headers=cabeceras).json()
    assert cuerpo["incumplidos"]["total"] == 12
    assert len(cuerpo["incumplidos"]["casos"]) == 5


def test_salen_primero_los_que_vencen_antes(
    cliente: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Si se recorta a los primeros, los primeros tienen que ser los urgentes.
    Por orden de creación, el recorte deja fuera justo los que más corren."""
    _caso(db, tenant_id, "menos_tarde", horas=-1)
    _caso(db, tenant_id, "mas_tarde", horas=-20)
    db.flush()

    casos = cliente.get("/api/v1/casos/bandeja?por_monton=1", headers=cabeceras).json()[
        "incumplidos"
    ]["casos"]
    assert [c["asunto"] for c in casos] == ["mas_tarde"]


# ── Lo que devuelve ───────────────────────────────────────────────────────


def test_devuelve_los_campos_que_la_pantalla_necesita(
    cliente: Any, cabeceras: dict[str, str], una_bandeja: None
) -> None:
    """La pantalla leía `vence_at`, `numero` y `escalado`, que la API no
    devolvía: todos los casos caían en «el resto» y el reloj decía siempre «sin
    SLA». Se fija aquí el contrato para que no vuelva a separarse."""
    caso = cliente.get("/api/v1/casos/bandeja", headers=cabeceras).json()["incumplidos"]["casos"][0]
    for campo in (
        "id",
        "codigo",
        "asunto",
        "estado",
        "prioridad",
        "severidad",
        "vence_resolucion_at",
        "incumplio_resolucion",
    ):
        assert campo in caso, f"falta «{campo}»: {sorted(caso)}"
