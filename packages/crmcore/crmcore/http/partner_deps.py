"""La sesión de quien entra al portal de partner (CRM-03.04.01.03).

Hasta el 14-11-2026 el portal de partner no existía de verdad:
`/portal-partner/canjear` comprobaba el enlace y devolvía el acceso, pero **no
abría ninguna sesión**, y las rutas del partner (`mis-registros`, un registro)
pedían una sesión del CRM con `partner:read`. Un partner no tiene sesión del
CRM, así que nadie de fuera podía usarlas (auditoría 13-11-2026, COB-14).

Es el mismo diseño que el portal de cliente (`crmcore.http.portal_deps`), por
las mismas razones:

* El token **no lleva permisos** y sólo entra en las rutas que dependen de
  `contexto_partner` (marca `admite_partner`, que mira `contexto_autenticado`).
* El **compartimento** —qué partner es— va firmado en el token. Ninguna ruta
  del partner lo lee de la petición: si saliera de un parámetro, entrar en la
  cartera del partner de al lado sería cambiar un número.
* Dura lo mismo que la del portal de cliente y se renueva con otro enlace.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, Request

from crmcore.errors import NoAutenticado
from crmcore.http.portal_deps import MINUTOS

TIPO = "partner"


def emitir_token_partner(
    *, acceso_id: UUID, tenant_id: UUID, partner_id: UUID, nivel: str
) -> tuple[str, int]:
    """El token con el que el partner llama a su portal, y cuánto dura en segundos."""
    from crmcore import tokens

    ahora = datetime.now(timezone.utc)
    carga = {
        "sub": str(acceso_id),
        "tenant": str(tenant_id),
        "tipo": TIPO,
        "partner": str(partner_id),
        "nivel": nivel,
        # Sin `permisos` ni `roles` a propósito: es lo que impide que sirva para
        # nada del CRM aunque una ruta olvidara su puerta.
        "iat": int(ahora.timestamp()),
        "exp": int((ahora + timedelta(minutes=MINUTOS)).timestamp()),
    }
    return tokens.emitir(carga), MINUTOS * 60


class SesionPartner:
    """Quién llama al portal de partner: su acceso, su partner y su nivel."""

    __slots__ = ("acceso_id", "tenant_id", "partner_id", "nivel")

    def __init__(self, *, acceso_id: UUID, tenant_id: UUID, partner_id: UUID, nivel: str) -> None:
        self.acceso_id = acceso_id
        self.tenant_id = tenant_id
        self.partner_id = partner_id
        self.nivel = nivel


def contexto_partner(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> SesionPartner:
    """Valida la sesión del partner y deja su tenant en el contexto."""
    from dataclasses import replace

    import jwt

    from crmcore import tokens
    from crmcore.config import get_settings
    from crmcore.tenancy.context import contexto_actual, fijar_contexto

    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:]
    else:
        # Cookie propia, como la del portal de cliente: en el mismo navegador
        # puede haber una sesión del CRM y no deben pisarse.
        token = request.cookies.get(f"{get_settings().sesion_cookie_nombre}_partner", "")
    if not token:
        raise NoAutenticado("Hace falta entrar en el portal", error_code="partner.sin_sesion")

    try:
        carga = tokens.verificar(token, tipos={TIPO})
    except tokens.TipoNoAdmitido:
        raise NoAutenticado(
            "Esta sesión no es del portal de partner", error_code="partner.sesion_no_es_de_partner"
        )
    except jwt.ExpiredSignatureError:
        raise NoAutenticado(
            "La sesión del portal ha caducado. Pide otro enlace de acceso.",
            error_code="partner.sesion_caducada",
        )
    except jwt.InvalidTokenError:
        raise NoAutenticado("Esta sesión no es válida", error_code="partner.sesion_invalida")

    try:
        acceso_id = UUID(str(carga["sub"]))
        tenant_id = UUID(str(carga["tenant"]))
        partner_id = UUID(str(carga["partner"]))
    except (KeyError, ValueError):
        raise NoAutenticado(
            "Esta sesión no tiene la forma esperada", error_code="partner.sesion_malformada"
        )

    fijar_contexto(replace(contexto_actual(), tenant_id=tenant_id, user_id=None))
    return SesionPartner(
        acceso_id=acceso_id,
        tenant_id=tenant_id,
        partner_id=partner_id,
        nivel=str(carga.get("nivel") or ""),
    )


# La marca que mira `contexto_autenticado` para dejar pasar un token de partner:
# sólo llega a las rutas que dependen de esto, y a ninguna otra.
contexto_partner.admite_partner = True  # type: ignore[attr-defined]

PartnerDep = Annotated[SesionPartner, Depends(contexto_partner)]

__all__ = ["TIPO", "PartnerDep", "SesionPartner", "contexto_partner", "emitir_token_partner"]
