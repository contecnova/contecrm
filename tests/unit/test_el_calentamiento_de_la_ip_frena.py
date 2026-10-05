"""El tope de calentamiento salía en pantalla y no frenaba nada
(`CRM-02.03.01.03`).

Auditado el 05-10-2026. `estado_dominio` calculaba el tope del día —«hoy como
mucho N envíos»— y lo devolvía con su aviso, y **ninguna comprobación previa lo
miraba**. Es el mismo patrón que el tope de frecuencia: un control que existe en
la pantalla de ajustes y no frena ni un correo.

Lo que cuesta: una IP nueva que manda cien mil el primer día se quema. Y quemar
una IP cuesta semanas en las que no llega **nada** por ese dominio — ni las
campañas ni las facturas, que comparten reputación.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import pytest
from crmcore.db.uow import UnidadDeTrabajo

from services.marketing import canales as can


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


def _canal_y_dominio(uow: UnidadDeTrabajo, *, dias_calentando: int | None = 0) -> str:
    uow.db.add(
        can.Canal(
            tenant_id=uow.tenant_id,
            clave="correo",
            nombre="Correo",
            tipo="email",
            activo=True,
            # Sin franja de silencio: el que se mide aquí es el tope de
            # calentamiento, y una hora de silencio a medias daría el mismo rojo
            # por otro motivo.
            silencio_desde=0,
            silencio_hasta=0,
        )
    )
    uow.db.add(
        can.ConsentimientoCanal(
            tenant_id=uow.tenant_id, canal="email", destino="ana@cliente.com", acepta=True
        )
    )
    dominio = can.DominioEnvio(
        tenant_id=uow.tenant_id,
        dominio="micrm.com",
        uso="promocional",
        spf=True,
        dkim=True,
        dmarc=True,
        calentamiento_desde=(
            None
            if dias_calentando is None
            else datetime.now(timezone.utc) - timedelta(days=dias_calentando)
        ),
    )
    uow.db.add(dominio)
    uow.db.flush()
    return "micrm.com"


def test_pasado_el_tope_del_dia_no_se_manda(uow: UnidadDeTrabajo) -> None:
    """**Esta es la del agujero.**"""
    dominio = _canal_y_dominio(uow, dias_calentando=0)
    estado = can.estado_dominio(uow.db, uow.tenant_id, dominio)
    tope = int(estado["tope_hoy"])

    salida = can.comprobar_envio(
        uow.db,
        uow.tenant_id,
        canal_clave="correo",
        destino="ana@cliente.com",
        dominio=dominio,
        enviados_hoy=tope,
    )
    assert salida["se_puede_mandar"] is False
    assert any("calentamiento" in m for m in salida["motivos"])


def test_por_debajo_del_tope_se_manda_y_se_dice_cuánto_queda(uow: UnidadDeTrabajo) -> None:
    """Avisar sólo al cortar convierte el tope en una sorpresa a mitad de
    campaña."""
    dominio = _canal_y_dominio(uow, dias_calentando=0)
    salida = can.comprobar_envio(
        uow.db,
        uow.tenant_id,
        canal_clave="correo",
        destino="ana@cliente.com",
        dominio=dominio,
        enviados_hoy=0,
    )
    assert salida["se_puede_mandar"] is True
    assert salida["calentamiento"]["tope_hoy"]
    assert salida["calentamiento"]["enviados_hoy"] == 0


def test_un_dominio_que_no_calienta_no_frena_nada(uow: UnidadDeTrabajo) -> None:
    """El tope es de la IP nueva. Aplicarlo a una asentada pararía campañas que
    llevan años saliendo bien."""
    dominio = _canal_y_dominio(uow, dias_calentando=None)
    salida = can.comprobar_envio(
        uow.db,
        uow.tenant_id,
        canal_clave="correo",
        destino="ana@cliente.com",
        dominio=dominio,
        enviados_hoy=1_000_000,
    )
    assert salida["se_puede_mandar"] is True
    assert salida["calentamiento"] is None


def test_sin_decir_el_dominio_no_se_inventa_un_tope(uow: UnidadDeTrabajo) -> None:
    """Suponer el dominio del remitente aquí haría que la comprobación frenara
    envíos por una IP que no es la que se va a usar."""
    _canal_y_dominio(uow, dias_calentando=0)
    salida = can.comprobar_envio(
        uow.db, uow.tenant_id, canal_clave="correo", destino="ana@cliente.com"
    )
    assert salida["calentamiento"] is None
    assert salida["se_puede_mandar"] is True
