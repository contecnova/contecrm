"""«O está todo o no está nada» es la única promesa de una petición compuesta.

Y no la cumplía para las rutas de escritura, que son casi todas.

El mecanismo está bien pensado y lleva tiempo escrito: el router compuesto abre
UNA sesión, la marca como compartida (`compartir_sesion`) y cada sub-petición la
reutiliza en vez de abrir la suya. Si algo falla, un solo `rollback()` deshace
el conjunto.

Pero sólo **una** de las dos puertas lo miraba. `get_db` sí; `get_uow` —la que
usan las escrituras que emiten eventos, o sea casi todas— abría su propia
sesión, la confirmaba al acabar la sub-petición y se iba. O sea que lo escrito
por las operaciones que ya habían pasado estaba **confirmado de verdad** antes
de que fallara la siguiente, y el `rollback()` del conjunto no lo tocaba.

Quien mandaba «crea la cuenta y luego el contacto» y fallaba en el contacto se
quedaba con la cuenta creada y un error diciendo que se había deshecho todo.
Que es peor que no tener la función: se limpia a mano lo que el sistema dice
que ya está limpio.

Nadie lo vio porque **la promesa no tenía prueba**. Había pruebas de las
referencias entre operaciones, del tope, de la petición vacía y de las redes;
ninguna de lo único que hace falta que sea cierto.
"""

from __future__ import annotations

from datetime import datetime, timezone
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
        modulo = importlib.import_module("services.party.main")
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
            H_ROLES: "admin",
            H_FACTOR_FUERTE: datetime.now(timezone.utc).isoformat(),
        },
        get_settings().secret_key.get_secret_value(),
    )


def _cuentas(db: Any, tenant_id: UUID, nombre: str) -> int:
    from sqlalchemy import func, select

    from services.party.modelos import Cuenta

    return int(
        db.execute(
            select(func.count())
            .select_from(Cuenta)
            .where(Cuenta.tenant_id == tenant_id, Cuenta.nombre == nombre)
        ).scalar_one()
    )


def test_las_dos_puertas_miran_la_sesion_compartida() -> None:
    """La comprobación de arriba: media docena de rutas usan `DbDep` y el resto
    `UowDep`, y si sólo una de las dos respeta la sesión compartida, la
    transacción del conjunto depende de qué dependencia eligió quien escribió
    la ruta. Eso no es una garantía, es una lotería."""
    import inspect

    from crmcore.http import deps

    for puerta in (deps.get_db, deps.get_uow):
        fuente = inspect.getsource(puerta)
        assert "_sesion_compartida" in fuente, (
            f"«{puerta.__name__}» no mira la sesión compartida: una petición "
            "compuesta que pase por ella abre su propia transacción y confirma "
            "por su cuenta, así que «todo o nada» deja de ser cierto."
        )


@pytest.mark.db
def test_si_falla_una_operacion_no_queda_nada_de_las_anteriores(
    cliente: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """**La prueba que faltaba.** Dos operaciones: la primera crea una cuenta y
    la segunda falla. La cuenta no puede quedarse."""
    nombre = f"Compuesta {uuid4().hex[:8]}"
    respuesta = cliente.post(
        "/api/v1/party/compuesto",
        headers=cabeceras,
        json={
            "operaciones": [
                {"metodo": "POST", "ruta": "/api/v1/accounts", "cuerpo": {"nombre": nombre}},
                # Falla a propósito: sin nombre, que es obligatorio.
                {"metodo": "POST", "ruta": "/api/v1/accounts", "cuerpo": {}},
            ]
        },
    )

    assert respuesta.status_code >= 400, respuesta.text
    assert "compuesto.operacion_fallida" in respuesta.text

    # Y lo que importa: la primera no se quedó.
    db.expire_all()
    assert _cuentas(db, tenant_id, nombre) == 0, (
        "La cuenta de la primera operación ha sobrevivido al fallo de la "
        "segunda: «todo o nada» no se cumple."
    )


@pytest.mark.db
def test_si_van_todas_bien_se_queda_todo(
    cliente: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """El control. Sin esto, un compuesto que no escribiera NADA nunca pasaría
    la prueba de arriba con matrícula de honor."""
    nombre = f"Compuesta ok {uuid4().hex[:8]}"
    respuesta = cliente.post(
        "/api/v1/party/compuesto",
        headers=cabeceras,
        json={
            "operaciones": [
                {"metodo": "POST", "ruta": "/api/v1/accounts", "cuerpo": {"nombre": nombre}},
            ]
        },
    )
    assert respuesta.status_code < 400, respuesta.text
    db.expire_all()
    assert _cuentas(db, tenant_id, nombre) == 1
