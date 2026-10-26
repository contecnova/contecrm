"""Lo que tres pantallas leen, comprobado por la ruta de verdad.

Una pantalla que lee un campo inexistente **no falla**: el campo llega
`undefined`, la lista sale vacía y la pantalla parece que funciona. Por eso
estos contratos se fijan aquí y no mirando el código: lo que importa es lo que
sale por HTTP, serialización incluida.

Las tres se verificaron a mano el 26-10-2026 y dos tenían deuda:

  · la **vista 360 de una cuenta** estaba bien —se comprobó campo a campo,
    incluido `no_contactar`, que es la marca de no llamar a quien pidió no ser
    contactado—;
  · **lo vencido** alimenta la portada nueva, que es lo primero que se ve al
    entrar;
  · y la **salud de una cuenta** pintaba «lo que suma» y «lo que resta» desde
    un `detalle` que el servidor nunca envía: los dos paneles salían vacíos,
    con sus rótulos puestos, en la pantalla que existe para explicar la
    puntuación. Y no era un olvido: la salud se calcula en inteligencia y aquí
    vive una COPIA que guarda lo justo, a propósito.
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
        with TestClient(importlib.import_module("services.party.main").app) as cli:
            yield cli
    finally:
        if previo is None:
            os.environ.pop("OUTBOX_ENABLED", None)
        else:
            os.environ["OUTBOX_ENABLED"] = previo
        get_settings.cache_clear()


@pytest.fixture
def usuario() -> UUID:
    """Quien pregunta. Se fija para poder asignarle una actividad: `/vencidas`
    devuelve **las suyas**, no las de todos, y con un usuario distinto en cada
    sitio la lista sale vacía y la prueba acusa al endpoint."""
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
def cuenta(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> Any:
    from services.party.modelos import Cuenta

    fila = Cuenta(tenant_id=tenant_id, nombre="Acme", clave_canonica="acme")
    db.add(fila)
    db.flush()
    return fila


# ── La ficha de cliente ───────────────────────────────────────────────────


def test_la_vista_360_trae_lo_que_la_ficha_pinta(
    cliente: Any, cabeceras: dict[str, str], cuenta: Any
) -> None:
    """Seis bloques, y la ficha coloca cada uno en su sitio. Si falta uno, esa
    columna se queda en blanco sin decir por qué."""
    r = cliente.get(f"/api/v1/accounts/{cuenta.id}/360", headers=cabeceras)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert {
        "cuenta",
        "identificadores",
        "direcciones",
        "contactos",
        "timeline",
        "metricas",
    } <= set(cuerpo)
    # Y dentro de la cuenta, lo que la cabecera necesita.
    for campo in ("id", "nombre", "estado", "roles", "sector", "calidad", "owner_id"):
        assert campo in cuerpo["cuenta"], f"falta «{campo}» en la cuenta"
    # Las métricas dicen lo que NO saben: «cero incidencias» y «no tenemos el
    # dato» se pintan igual y significan lo contrario.
    for campo in ("metricas", "sin_dato", "caducadas", "completo", "que_significa"):
        assert campo in cuerpo["metricas"], f"falta «{campo}» en las métricas"


def test_un_contacto_trae_la_marca_de_no_contactar(
    cliente: Any, cabeceras: dict[str, str], cuenta: Any, db: Any, tenant_id: UUID
) -> None:
    """Es una marca legal, no un adorno: llamar a quien pidió no ser
    contactado tiene consecuencias. Si no viajara, la ficha no podría avisar."""
    from services.party.modelos import Contacto, RelacionContactoCuenta

    contacto = Contacto(
        tenant_id=tenant_id,
        nombre="Ana",
        nombre_completo="Ana Pérez",
        clave_canonica="ana-perez",
        no_contactar=True,
    )
    db.add(contacto)
    db.flush()
    db.add(
        RelacionContactoCuenta(tenant_id=tenant_id, cuenta_id=cuenta.id, contacto_id=contacto.id)
    )
    db.flush()

    contactos = cliente.get(f"/api/v1/accounts/{cuenta.id}/360", headers=cabeceras).json()[
        "contactos"
    ]
    assert contactos, "la relación no ha llegado a la vista"
    for campo in ("id", "nombre", "cargo", "email", "rol", "principal", "no_contactar"):
        assert campo in contactos[0], f"falta «{campo}»"
    assert contactos[0]["no_contactar"] is True


# ── Lo vencido, que es lo primero de la portada ───────────────────────────


def test_lo_vencido_trae_lo_que_la_portada_enseña(
    cliente: Any,
    cabeceras: dict[str, str],
    db: Any,
    tenant_id: UUID,
    usuario: UUID,
    contexto_tenant: UUID,
) -> None:
    """Va lo primero en la portada y en rojo: es lo único que no admite
    espera."""
    from services.party.modelos import Actividad

    db.add(
        Actividad(
            tenant_id=tenant_id,
            tipo="llamada",
            asunto="Llamar a Acme",
            asignada_a=usuario,
            vence_at=datetime.now(timezone.utc) - timedelta(days=2),
        )
    )
    db.flush()

    r = cliente.get("/api/v1/activities/vencidas", headers=cabeceras)
    assert r.status_code == 200, r.text
    filas = r.json()
    assert filas, "no sale lo vencido"
    for campo in ("id", "asunto", "tipo", "vence_at"):
        assert campo in filas[0], f"falta «{campo}»: {sorted(filas[0])}"


# ── La salud de una cuenta ────────────────────────────────────────────────


def test_la_salud_trae_lo_que_la_pantalla_puede_enseñar(
    cliente: Any, cabeceras: dict[str, str], cuenta: Any, db: Any, tenant_id: UUID
) -> None:
    """**El contrato que se separó.** La pantalla leía `salud.detalle` —los
    factores que suman y restan— y aquí no hay factores: esto es una copia de
    lo que calcula inteligencia, y guarda lo justo a propósito. El detalle vive
    allí, y la respuesta lo dice en `de_donde_sale`.
    """
    from services.party.salud_replicada import proyectar

    proyectar(
        db,
        tenant_id=tenant_id,
        datos={
            "cuenta_id": str(cuenta.id),
            "puntuacion": 42,
            "nivel": "riesgo",
            "fiable": True,
            "motivo": "Tres incidencias abiertas",
            "medida_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    db.flush()

    r = cliente.get(f"/api/v1/calidad-dato/salud/{cuenta.id}", headers=cabeceras)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["hay"] is True
    for campo in (
        "puntuacion",
        "nivel",
        "fiable",
        "vigente",
        "medida_hace_dias",
        "motivo",
        "sirve_para_actuar",
        "aviso",
        "de_donde_sale",
    ):
        assert campo in cuerpo, f"falta «{campo}»: {sorted(cuerpo)}"
    # Y lo que NO manda, que es lo que la pantalla daba por hecho.
    assert "detalle" not in cuerpo, (
        "si un día llegan los factores, la pantalla puede volver a enseñarlos "
        "— pero entonces hay que quitar este aserto a propósito, no de paso"
    )


def test_sin_medida_se_dice_por_qué_y_qué_hacer(
    cliente: Any, cabeceras: dict[str, str], cuenta: Any
) -> None:
    """«No medido» y «va mal» son cosas distintas, y confundirlas hace que
    alguien llame a un cliente que está bien."""
    cuerpo = cliente.get(f"/api/v1/calidad-dato/salud/{cuenta.id}", headers=cabeceras).json()
    assert cuerpo["hay"] is False
    assert cuerpo["porque"] and cuerpo["que_hacer"]
