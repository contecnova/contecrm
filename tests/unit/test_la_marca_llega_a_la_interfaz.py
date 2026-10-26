"""La marca del tenant, ¿llega a la interfaz? (CRM-07.04.01.04).

La marca es **por tenant** —lo dice el catálogo— y el servidor la guarda:
nombre del producto, logotipo, favicon y colores. La ruta que la expone
devolvía sólo el **diagnóstico** —qué falta para poder activarla, el aviso de
contraste— y no los valores, así que el front no tenía de dónde leerla: sacaba
el nombre, el color y el logotipo de `config.json`, que es del **despliegue**.
Dos tenants en la misma instalación compartían marca.

Medido el 26-10-2026 auditando la base del front, el mismo día que la
localización, y es el mismo circuito abierto: la mitad del servidor existe, la
del cliente no la lee.

Y sólo cuando está **activa**. Una marca a medias pisando la del despliegue es
justo lo que el diagnóstico de esta misma ruta existe para evitar: si se
anuncia y el correo sale con el dominio del fabricante, la conversación que
sigue no es sobre el correo.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

pytestmark = pytest.mark.db


def test_la_marca_activa_trae_lo_que_la_interfaz_pinta_crm_07_04_01_04(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Nombre, logotipo, favicon y colores: lo que hace falta para que el
    producto tenga la cara del cliente y no la del fabricante."""
    from crmcore.db.uow import UnidadDeTrabajo

    from services.tenancy import marca as mrc

    uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
    mrc.guardar(
        uow,
        tenant_id=tenant_id,
        nombre_producto="CRM de Acme",
        logo_url="https://acme.example/logo.svg",
        favicon_url="https://acme.example/favicon.png",
        color_principal="#1b6ef3",
        color_texto="#111111",
        color_fondo="#ffffff",
        dominio_propio="crm.acme.example",
        dominio_envio="correo.acme.example",
        remitente="no-reply@acme.example",
        pie_correo="Acme, S.A.",
    )
    fila = mrc.comprobar(db, tenant_id)
    # Antes de activarla NO se manda: pisaría la del despliegue con una marca a
    # medias, que es lo que esta misma respuesta existe para evitar.
    assert fila["aplicable"] == {}, fila["aplicable"]

    # Los dos dominios, verificados: activar con uno sin verificar es
    # exactamente lo que la propia función impide, y con razón — los enlaces de
    # los correos no llevarían a ninguna parte.
    for cual in ("propio", "envio"):
        mrc.verificar_dominio(uow, tenant_id=tenant_id, cual=cual, verificado=True)
    mrc.activar(uow, tenant_id=tenant_id)
    db.flush()

    aplicable = mrc.comprobar(db, tenant_id)["aplicable"]
    for campo in (
        "nombre_producto",
        "logo_url",
        "favicon_url",
        "color_principal",
        "color_texto",
        "color_fondo",
    ):
        assert campo in aplicable, f"falta «{campo}»: {sorted(aplicable)}"
    assert aplicable["nombre_producto"] == "CRM de Acme"
    assert aplicable["color_principal"] == "#1b6ef3"


def test_el_diagnostico_sigue_estando_crm_07_04_01_04(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Añadir los valores no puede llevarse por delante lo que ya decía: qué
    falta para poder activarla, y por qué cada cosa. Una marca blanca a medias
    es peor que ninguna."""
    from crmcore.db.uow import UnidadDeTrabajo

    from services.tenancy import marca as mrc

    # Con la marca apenas empezada: sin nada configurado la ruta contesta «este
    # tenant no tiene marca», que es otra respuesta y no la que se mide aquí.
    mrc.guardar(
        UnidadDeTrabajo(db=db, tenant_id=tenant_id),
        tenant_id=tenant_id,
        nombre_producto="A medias",
    )
    fila = mrc.comprobar(db, tenant_id)
    for campo in ("puntos_de_fuga", "faltan", "se_puede_activar", "que_significa"):
        assert campo in fila, f"falta «{campo}»: {sorted(fila)}"
    assert fila["se_puede_activar"] is False
    assert fila["faltan"], "sin nada configurado tiene que faltar algo"
