"""Los tres últimos ajustes sin lector, y el marcador que los destapó.

Medidos el 06-10-2026 con el barrido de ajustes sin lector.

`TENANT_DEFAULT_REGION` y `TENANT_DEFAULT_ISOLATION` estaban a fuego en **tres**
sitios —el esquema de la API, la firma del servicio y la columna del modelo—
mientras los dos ajustes existían, estaban documentados y no los leía nadie.

En el aislamiento eso era un ajuste decorativo. En la región es peor: el valor se
guarda en el tenant **para poder auditar dónde vive cada dato**, así que una
instalación en otra región daba de alta a todos sus clientes diciendo que sus
datos están en Europa. El de residencia no es un valor por defecto cualquiera: es
el que se enseña cuando alguien pregunta.

`ONBOARDING_ENABLED` se quita: prometía abrir el alta autoservicio, y aquí el
alta de un tenant es una operación de plataforma. Ponerlo a `true` no abría
nada; lo malo no era el riesgo, era hacer creer que el alta pública existía y
que apagarla era lo que la cerraba. Lo que la cierra es que no existe.
"""

from __future__ import annotations

import os
from typing import Any
from uuid import UUID

import pytest

pytestmark = pytest.mark.db


@pytest.fixture
def instalacion(request: Any) -> Any:
    """`(region, aislamiento)` de la instalación, y lo deja como estaba."""
    from crmcore.config import limpiar_cache_settings

    region, aislamiento = request.param
    previo = {k: os.environ.get(k) for k in ("TENANT_DEFAULT_REGION", "TENANT_DEFAULT_ISOLATION")}
    os.environ["TENANT_DEFAULT_REGION"] = region
    os.environ["TENANT_DEFAULT_ISOLATION"] = aislamiento
    limpiar_cache_settings()
    try:
        yield
    finally:
        for k, v in previo.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        limpiar_cache_settings()


@pytest.mark.parametrize("instalacion", [("us", "schema")], indirect=True)
def test_el_alta_toma_la_region_y_el_aislamiento_de_la_instalacion(
    db: Any, tenant_id: UUID, instalacion: Any
) -> None:
    """Es el caso entero: una instalación fuera de Europa daba de alta a todos
    sus clientes diciendo que sus datos están en Europa."""
    from crmcore.db.uow import UnidadDeTrabajo

    from services.tenancy import servicio as svc

    uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
    fila = svc.crear_tenant(uow, slug="acme-us", nombre="ACME US")
    assert fila.region == "us"
    assert fila.aislamiento == "schema"


@pytest.mark.parametrize("instalacion", [("us", "schema")], indirect=True)
def test_lo_que_se_pide_explicito_manda_sobre_el_de_la_instalacion(
    db: Any, tenant_id: UUID, instalacion: Any
) -> None:
    """El ajuste es el valor por defecto, no un techo: un tenant concreto puede
    vivir en otra región, que es de lo que trata el modelo híbrido por tiers."""
    from crmcore.db.uow import UnidadDeTrabajo

    from services.tenancy import servicio as svc

    uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
    fila = svc.crear_tenant(uow, slug="acme-eu", nombre="ACME EU", region="eu", aislamiento="silo")
    assert fila.region == "eu"
    assert fila.aislamiento == "silo"


def test_el_esquema_de_la_api_no_impone_un_valor_por_defecto() -> None:
    """Escribir `"eu"` en el esquema haría que el ajuste no sirviera para nada,
    porque el cuerpo llegaría siempre relleno. Que es como estaba."""
    from services.tenancy.esquemas import CrearTenant

    datos = CrearTenant(slug="xy", nombre="X")
    assert datos.region is None
    assert datos.aislamiento is None


def test_el_alta_autoservicio_no_existe_y_su_interruptor_tampoco() -> None:
    """Un interruptor para algo que no hay hace creer que apagarlo es lo que lo
    cierra. Lo que lo cierra es que no existe."""
    import pathlib

    raiz = pathlib.Path(__file__).resolve().parents[2]
    ajustes = (raiz / "packages/crmcore/crmcore/config_parts/_tenancy.py").read_text(
        encoding="utf-8"
    )
    assert "onboarding_enabled: bool" not in ajustes
    # Y la única puerta de alta sigue siendo de plataforma.
    api = (raiz / "services/tenancy/api.py").read_text(encoding="utf-8")
    cabecera = api.split("def crear_tenant(")[1].split(")")[0]
    assert "PlataformaDep" in cabecera
