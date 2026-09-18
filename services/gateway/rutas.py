"""Tabla de enrutado: qué prefijo va a qué servicio.

Se declara en configuración (`RUTAS_SERVICIOS`) y no en código para que añadir
un servicio o cambiar su dirección no exija reconstruir la imagen del gateway.
"""

from __future__ import annotations

from dataclasses import dataclass

from crmcore.logging import get_logger

logger = get_logger(__name__)

# Prefijo de la API pública → servicio que lo atiende. Es la ÚNICA lista de
# acoplamiento del sistema, y por eso está aquí y no repartida.
PREFIJOS: dict[str, str] = {
    "tenants": "tenancy",
    "planes": "tenancy",
    "flags": "tenancy",
    "ajustes": "tenancy",
    "auth": "identity",
    "usuarios": "identity",
    "roles": "identity",
    "sesiones": "identity",
    "claves-api": "identity",
    "metadata": "metadata",
    "procesos": "orchestrator",
    "instancias": "orchestrator",
    "tareas": "orchestrator",
    "automatizaciones": "automation",
    "integraciones": "integration",
    "webhooks": "eventing",
    "eventos": "eventing",
    # Fase 1 — núcleo de datos de cliente y ventas
    "accounts": "party",
    "contacts": "party",
    "activities": "party",
    "data-quality": "party",
    "data-subject-requests": "party",
    "leads": "sales",
    "opportunities": "sales",
    "pipelines": "sales",
    "pipeline": "sales",
}


@dataclass(frozen=True, slots=True)
class Destino:
    servicio: str
    url_base: str


def cargar_destinos(config: str) -> dict[str, Destino]:
    """Lee `RUTAS_SERVICIOS`: `tenancy=http://tenancy:8000,identity=...`.

    Un servicio que no aparezca aquí simplemente no es alcanzable, y el gateway
    responde 503 diciendo cuál falta. Es mejor que un 404 genérico: el 404 hace
    pensar que la ruta no existe, cuando lo que pasa es que el servicio no está
    desplegado.
    """
    destinos: dict[str, Destino] = {}
    for trozo in config.replace("\n", "").split(","):
        if "=" not in trozo:
            continue
        nombre, _, url = trozo.partition("=")
        nombre, url = nombre.strip(), url.strip().rstrip("/")
        if nombre and url:
            destinos[nombre] = Destino(servicio=nombre, url_base=url)
    return destinos


def servicio_de(ruta: str) -> str | None:
    """Servicio que atiende una ruta de la API. `None` si ninguna lo hace."""
    partes = [p for p in ruta.split("/") if p]
    # `/api/v1/<recurso>/...` → el recurso es el tercer segmento.
    if len(partes) >= 3 and partes[0] == "api":
        return PREFIJOS.get(partes[2])
    return None
