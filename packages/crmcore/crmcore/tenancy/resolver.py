"""Resolución del tenant de una petición (CRM-00.02.04.02).

Cuatro vías, y la diferencia entre ellas es la única idea importante de este
módulo:

  **Vías autoritativas** — van firmadas, así que por sí solas conceden acceso:
    1. `tenant` dentro del JWT (lo puso quien emitió el token).
    2. La clave de API, que pertenece a un tenant concreto en la base.

  **Vías de enrutado** — son PISTAS, y por sí solas no conceden nada:
    3. La cabecera `X-Tenant`.
    4. El subdominio (`acme.contecrm.app`).

Si llega una pista y además hay identidad autoritativa, tienen que coincidir; si
no coinciden, se rechaza. Ese es el punto: sin esta comprobación, bastaría
cambiar una cabecera para operar sobre otro tenant con un token legítimo.

Una pista SOLA sirve únicamente para lo que no necesita identidad: elegir la
marca de la pantalla de login, o saber a qué proveedor de identidad mandar a
alguien que todavía no se ha autenticado.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from crmcore.errors import Prohibido
from crmcore.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class TenantResuelto:
    """Resultado de la resolución."""

    tenant_id: UUID | None
    slug: str = ""
    # token | api_key | cabecera | subdominio | ninguno
    via: str = "ninguno"

    @property
    def es_autoritativa(self) -> bool:
        """Si la vía basta por sí sola para conceder acceso."""
        return self.via in ("token", "api_key")


def pista_por_cabecera(valor: str | None, nombre_cabecera: str = "X-Tenant") -> str:
    """Slug que viene en la cabecera, normalizado. Cadena vacía si no hay."""
    return (valor or "").strip().lower()


def pista_por_host(host: str | None, dominio_raiz: str) -> str:
    """Slug que viene del subdominio: `acme.contecrm.app` → `acme`.

    Sin dominio raíz configurado no se deduce nada. Es deliberado: deducir un
    tenant de un `Host` arbitrario en un despliegue que no usa subdominios
    convertiría cualquier cabecera `Host` en una vía de enrutado no prevista.
    """
    if not host or not dominio_raiz:
        return ""
    host = host.split(":")[0].strip().lower()
    sufijo = f".{dominio_raiz.strip().lower()}"
    if not host.endswith(sufijo):
        return ""
    slug = host[: -len(sufijo)]
    # `www` y `api` son subdominios de servicio, no tenants. Sin esta guarda,
    # `www.contecrm.app` buscaría un tenant llamado «www».
    return "" if slug in ("", "www", "api", "app") else slug


def conciliar(
    *,
    del_token: UUID | None,
    de_api_key: UUID | None,
    pista_slug: str,
    resolver_slug: object,
) -> TenantResuelto:
    """Combina las vías y comprueba que no se contradigan.

    `resolver_slug` es un invocable `slug -> UUID | None`, que se pasa desde
    fuera para que este módulo no dependa de la base de datos y se pueda probar
    sin ella.

    Lanza `Prohibido` si una pista contradice a la identidad autoritativa. La
    respuesta es deliberadamente escueta: confirmar «ese tenant existe pero no
    es el tuyo» ya sería decir de más.
    """
    autoritativo = del_token or de_api_key
    via = "token" if del_token else ("api_key" if de_api_key else "ninguno")

    if autoritativo is not None:
        if pista_slug:
            de_pista = resolver_slug(pista_slug)  # type: ignore[operator]
            if de_pista is not None and de_pista != autoritativo:
                logger.warning(
                    "tenancy.pista_contradice_identidad",
                    via=via,
                    pista=pista_slug,
                )
                raise Prohibido(
                    "El tenant indicado no corresponde a la identidad de la petición",
                    error_code="tenancy.pista_contradictoria",
                )
        return TenantResuelto(tenant_id=autoritativo, slug=pista_slug, via=via)

    if pista_slug:
        de_pista = resolver_slug(pista_slug)  # type: ignore[operator]
        if de_pista is not None:
            # Solo enrutado: quien lo reciba NO debe conceder acceso con esto.
            # Lo comprueba `es_autoritativa` en la capa de autenticación.
            return TenantResuelto(tenant_id=de_pista, slug=pista_slug, via="cabecera")

    return TenantResuelto(tenant_id=None)
