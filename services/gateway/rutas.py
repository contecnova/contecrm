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
    "party-admin": "party",
    "leads": "sales",
    "opportunities": "sales",
    "pipelines": "sales",
    "pipeline": "sales",
    "lead-routing": "sales",
    "origen": "sales",
    "sharing-rules": "identity",
    "notificaciones": "identity",
    "seguimientos": "identity",
    "plantillas": "tenancy",
    "calendarios": "tenancy",
    "monedas": "tenancy",
}

# Los adjuntos los guarda el servicio dueño del objeto, y `party` y `sales`
# publican los dos el mismo prefijo `/adjuntos`. La ruta lleva el tipo de objeto
# justo después (`/api/v1/adjuntos/<tipo>/...`), así que el destino se decide
# por él. Sin esto, todos los adjuntos irían al primer servicio que casara y los
# de oportunidad se pedirían a `party`, que no los tiene.
# Lo mismo pasa con los comentarios: la conversación la guarda el servicio dueño
# del registro, y el tipo va en la ruta por eso.
OBJETOS_COMENTARIO: dict[str, str] = {
    "cuenta": "party",
    "contacto": "party",
    "actividad": "party",
    "lead": "sales",
    "oportunidad": "sales",
}

OBJETOS_ADJUNTO: dict[str, str] = {
    "cuenta": "party",
    "contacto": "party",
    "actividad": "party",
    "lead": "sales",
    "oportunidad": "sales",
    "linea_oportunidad": "sales",
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
        if partes[2] == "comentarios":
            return OBJETOS_COMENTARIO.get(partes[3]) if len(partes) >= 4 else None
        if partes[2] == "adjuntos":
            # Un tipo de objeto desconocido devuelve `None` y el gateway
            # responde 404, que es lo correcto: no hay servicio que lo tenga.
            return OBJETOS_ADJUNTO.get(partes[3]) if len(partes) >= 4 else None
        return PREFIJOS.get(partes[2])
    return None
