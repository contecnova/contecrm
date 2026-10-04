"""Varios proveedores de identidad a la vez, y el correcto para cada correo
(`CRM-00.05.01.03`, `CRM-00.05.01.14`).

Había **dos** funciones contestando «¿qué proveedor le toca a este correo?», y
no contestaban lo mismo:

    sso.proveedor_para          solo `dominio_email`, sin subdominios
    sso_gobierno.proveedor_por_correo   la lista entera y herencia de subdominios

La del inicio de sesión era la floja. El resultado, medido el 04-10-2026: un
usuario de un dominio añadido —los que acumula una empresa tras una
adquisición— o de un subdominio como `ventas.ejemplo.com` **no podía entrar por
ninguna puerta**. El SSO forzado sí encontraba su proveedor y le bloqueaba la
contraseña; `/sso/iniciar` no lo encontraba y le negaba el SSO. Fuera del CRM,
sin nada en la pantalla que lo explicara.

Dos implementaciones de la misma pregunta divergen siempre, y aquí la que se
quedó atrás era la puerta por la que no se entra.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

pytestmark = pytest.mark.db


def _proveedor(
    db: Any,
    tenant_id: UUID,
    nombre: str,
    *,
    principal: str | None = None,
    extra: list[str] | None = None,
) -> Any:
    from services.identity.modelos import ProveedorIdentidad

    fila = ProveedorIdentidad(
        tenant_id=tenant_id,
        nombre=nombre,
        tipo="oidc",
        config={},
        dominio_email=principal,
        dominios=extra or [],
        activo=True,
    )
    db.add(fila)
    db.flush()
    return fila


def test_el_dominio_principal_elige_su_proveedor(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Lo que ya funcionaba. Sin esta mitad, un cambio que lo rompiera pasaría."""
    from services.identity import sso

    _proveedor(db, tenant_id, "Entra", principal="empleados.com")
    _proveedor(db, tenant_id, "Google", principal="partners.com")

    assert sso.proveedor_para(db, tenant_id, email="ana@partners.com").nombre == "Google"
    assert sso.proveedor_para(db, tenant_id, email="luis@empleados.com").nombre == "Entra"


def test_un_dominio_anadido_tambien_encuentra_su_proveedor(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """La avería. Con uno solo, cada dominio extra obligaba a duplicar el
    proveedor entero: misma configuración, mismo certificado, mismo mapeo de
    roles, mantenidos por separado hasta que divergen."""
    from services.identity import sso

    _proveedor(db, tenant_id, "Entra", principal="empresa.com", extra=["adquirida.com"])

    assert sso.proveedor_para(db, tenant_id, email="ana@adquirida.com").nombre == "Entra", (
        "un correo de un dominio añadido no encuentra su proveedor: con el SSO "
        "forzado, esa persona no puede entrar por ninguna puerta"
    )


def test_un_subdominio_hereda_del_padre(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """Si no heredara, cada filial obligaría a una fila nueva y el día que
    falte una, esa gente se queda fuera."""
    from services.identity import sso

    _proveedor(db, tenant_id, "Entra", principal="ejemplo.com")

    assert sso.proveedor_para(db, tenant_id, email="ana@ventas.ejemplo.com").nombre == "Entra"


def test_el_mas_especifico_gana(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """Quien configura `ventas.ejemplo.com` aparte es porque quiere otra cosa
    para esa gente."""
    from services.identity import sso

    _proveedor(db, tenant_id, "Entra", principal="ejemplo.com")
    _proveedor(db, tenant_id, "Okta", principal="ventas.ejemplo.com")

    assert sso.proveedor_para(db, tenant_id, email="ana@ventas.ejemplo.com").nombre == "Okta"
    assert sso.proveedor_para(db, tenant_id, email="luis@ejemplo.com").nombre == "Entra"


def test_las_dos_resoluciones_contestan_lo_mismo(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Lo que de verdad hay que impedir: que vuelvan a divergir.

    Mientras existan las dos, basta con que una mire un campo que la otra no
    para que alguien quede encerrado entre las dos puertas.
    """
    from services.identity import sso, sso_gobierno

    _proveedor(db, tenant_id, "Entra", principal="ejemplo.com", extra=["adquirida.com"])
    _proveedor(db, tenant_id, "Okta", principal="ventas.ejemplo.com")

    correos = [
        "ana@ejemplo.com",
        "ana@adquirida.com",
        "ana@ventas.ejemplo.com",
        "ana@sub.ventas.ejemplo.com",
    ]
    for correo in correos:
        por_gobierno = sso_gobierno.proveedor_por_correo(db, tenant_id, correo)
        por_inicio = sso.proveedor_para(db, tenant_id, email=correo)
        assert por_gobierno is not None, correo
        assert por_inicio.id == por_gobierno.id, (
            f"«{correo}» va a «{por_inicio.nombre}» al iniciar sesión y a "
            f"«{por_gobierno.nombre}» al comprobar el SSO forzado. Con las dos "
            "en desacuerdo, hay gente que no entra por ninguna puerta."
        )


def test_un_dominio_que_no_cubre_nadie_lo_dice_con_los_que_si(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """«No se puede entrar» sin decir qué dominios valen obliga a adivinar."""
    from crmcore.errors import NoEncontrado

    from services.identity import sso

    _proveedor(db, tenant_id, "Entra", principal="ejemplo.com")

    with pytest.raises(NoEncontrado) as fallo:
        sso.proveedor_para(db, tenant_id, email="ana@otracosa.com")
    assert fallo.value.error_code == "sso.dominio_sin_proveedor"


def test_un_proveedor_sin_dominio_recoge_lo_que_no_encaja(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """El caso de un solo proveedor para todos: no se declara dominio y vale
    para cualquiera. Quitarlo dejaría sin entrar a quien lo tenga así."""
    from services.identity import sso

    _proveedor(db, tenant_id, "Unico")

    assert sso.proveedor_para(db, tenant_id, email="quien@sea.com").nombre == "Unico"
