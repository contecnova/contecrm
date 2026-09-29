"""«Hoy» es el del cliente, no el del servidor (`CRM-00.01.04.07`).

**Veinticinco sitios calculaban la fecha en UTC** mientras el producto guarda la
zona horaria de cada tenant. Entre medianoche y las dos de la mañana en Madrid
—y durante **trece horas** en Auckland— «hoy» era ayer para el servidor y hoy
para el cliente: los días que quedaban de una garantía salían con uno de más, y
un plazo que vencía hoy se seguía admitiendo.

**Y el huso que el cliente configuraba no lo leía nadie.** `Tenant.zona_horaria`
se ponía en el perfil y era un campo de **sólo escritura**: el formateo y las
fechas van por el ajuste `zona_horaria`, que nadie rellenaba desde el perfil, así
que caía a UTC.

Se descubrió por accidente, y ése es el detalle que más dice: una tanda de
pruebas cruzó la medianoche y empezó a fallar. A las once de la noche del mismo
día habría pasado en verde, que es lo que llevaba pasando.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest

pytestmark = pytest.mark.db


def _fijar_zona(db: Any, tenant_id: UUID, zona: str) -> None:
    from crmcore.runtime import settings as rt

    rt.fijar(db, "zona_horaria", zona, ambito="tenant", ambito_id=str(tenant_id))
    db.commit()


def test_sin_zona_configurada_se_usa_utc(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """No se adivina. Un valor inventado escondería el problema en vez de
    dejarlo igual que estaba."""
    from crmcore.fechas import hoy

    assert hoy(db) == datetime.now(timezone.utc).date()


def test_con_zona_configurada_hoy_es_el_de_alli(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """La prueba que decide.

    Se compara contra dos husos que casi nunca comparten día: cuando en Auckland
    es martes, en Honolulu suele ser lunes. Si «hoy» fuera el mismo para los dos,
    es que no se está mirando la zona de nadie.
    """
    from crmcore.fechas import hoy

    _fijar_zona(db, tenant_id, "Pacific/Auckland")
    en_auckland = hoy(db)

    _fijar_zona(db, tenant_id, "Pacific/Honolulu")
    en_honolulu = hoy(db)

    assert en_auckland == datetime.now(ZoneInfo("Pacific/Auckland")).date()
    assert en_honolulu == datetime.now(ZoneInfo("Pacific/Honolulu")).date()
    # Veintitrés horas de diferencia: sólo coinciden una hora al día.
    assert en_auckland != en_honolulu or datetime.now(timezone.utc).hour == 10


def test_una_zona_mal_escrita_no_tumba_la_peticion(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Un ajuste con una errata no puede dejar el servicio sin contestar: se
    avisa y se cae a UTC, que es el comportamiento de siempre."""
    from crmcore.fechas import hoy

    _fijar_zona(db, tenant_id, "Marte/Olympus_Mons")
    assert hoy(db) == datetime.now(timezone.utc).date()


# ── Y que el perfil del tenant llegue al ajuste ───────────────────────────


def test_el_huso_del_perfil_llega_al_ajuste_que_se_lee(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Era un campo de sólo escritura.

    El administrador ponía la zona en el perfil del tenant y **nadie la leía**:
    las fechas y el formateo van por el ajuste, que se quedaba vacío. Configurar
    el huso no cambiaba nada en ninguna pantalla.
    """
    from crmcore.fechas import hoy

    from services.tenancy import servicio as svc
    from services.tenancy.modelos import Tenant

    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        tenant = Tenant(id=tenant_id, slug="cliente", nombre="Cliente S.A.")
        db.add(tenant)
        db.flush()

    svc.propagar_localizacion(db, tenant, {"zona_horaria": "Pacific/Auckland"})
    db.commit()

    assert (
        hoy(db) == datetime.now(ZoneInfo("Pacific/Auckland")).date()
    ), "el huso configurado en el perfil no llega a las fechas"


def test_lo_que_no_se_toca_no_se_propaga(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """Editar el nombre de una empresa no puede rescribirle el idioma."""
    from crmcore.runtime import settings as rt

    from services.tenancy import servicio as svc
    from services.tenancy.modelos import Tenant

    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        tenant = Tenant(id=tenant_id, slug="cliente", nombre="Cliente S.A.")
        db.add(tenant)
        db.flush()

    _fijar_zona(db, tenant_id, "Europe/Madrid")
    svc.propagar_localizacion(db, tenant, {"nombre": "Otro nombre"})
    db.commit()

    assert rt.efectivo("zona_horaria", db) == "Europe/Madrid"
