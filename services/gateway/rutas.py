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
    "analitica": "analytics",
    "sharing-rules": "identity",
    "notificaciones": "identity",
    "seguimientos": "identity",
    "plantillas": "tenancy",
    "calendarios": "tenancy",
    "monedas": "tenancy",
    "claves-cifrado": "tenancy",
    "localizacion": "tenancy",
    "proveedores-identidad": "identity",
    # El SSO entra por aquí desde el navegador del usuario y desde el proveedor
    # de identidad —la vuelta de SAML y de OIDC—, así que si el gateway no lo
    # enruta no hay inicio de sesión federado: no es una ruta de servicio, es
    # LA puerta. Faltaba, y el síntoma habría sido un 404 en mitad del login.
    "sso": "identity",
    "politicas-acceso": "identity",
    "segregacion": "identity",
    # SCIM lo llama el IdP corporativo, no el front: entra por el mismo gateway
    # y con la misma clave de API, que es lo que acota el tenant.
    "scim": "identity",
    "factores": "identity",
    "dispositivos-confianza": "identity",
    "sso-gobierno": "identity",
    "forecast": "sales",
    "suite": "tenancy",
    "casos": "service",
    "categorias-caso": "service",
    "sla": "service",
    "colas": "service",
    "agentes": "service",
    "escalado": "service",
    "entitlements": "service",
    "encuestas": "service",
    "creditos-servicio": "service",
    "canales-servicio": "service",
    "conversaciones": "service",
    "macros": "service",
    "consola-agente": "service",
    "conocimiento": "service",
    "portal": "service",
    "comunidad": "service",
    "segmentos": "marketing",
    "supresiones": "marketing",
    "puntuacion": "marketing",
    "campanas": "marketing",
    "atribucion": "marketing",
    "presion": "marketing",
    "rebotes": "marketing",
    # Lo que se le encarga a un tercero y hay que seguir. `proveedores-servicio`
    # se llama así y no `proveedores` porque en el CRM un proveedor es también
    # una cuenta: dos rutas parecidas apuntando a servicios distintos es cómo se
    # enruta mal una llamada y nadie entiende el 404.
    "aprobaciones": "orchestrator",
    "analitica-procesos": "orchestrator",
    "encargos": "integration",
    "proveedores-servicio": "integration",
    "grc": "tenancy",
    "compromisos": "tenancy",
    "tablas-decision": "orchestrator",
    # Los recursos masivos publican el nombre del recurso en español mientras
    # el CRUD usa el inglés (`/cuentas/masivo` junto a `/accounts`). La
    # incoherencia está anotada; mientras exista, las dos formas se enrutan,
    # porque enrutar solo una deja la mitad inalcanzable.
    "cuentas": "party",
    "contactos": "party",
    "oportunidades": "sales",
    "captura": "sales",
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

# Y lo mismo con los documentos del corpus (RT-5): el enlace lo guarda el
# servicio dueño del registro, así que el tipo de objeto vuelve a decidir.
OBJETOS_DOCUMENTO: dict[str, str] = {
    "cuenta": "party",
    "contacto": "party",
    "lead": "sales",
    "oportunidad": "sales",
}

# Segmentos literales que van DONDE iría el tipo de objeto. Sin esta lista,
# `/api/v1/adjuntos/carpetas/cuenta` se resolvía buscando un objeto llamado
# «carpetas», no lo encontraba y el gateway respondía 404: las carpetas
# existían, estaban probadas y no se podían llamar desde fuera.
SEGMENTOS_LITERALES = {"carpetas", "estado", "buscar", "organizacion", "enlace"}

# Recursos TRANSVERSALES: los monta la misma fábrica en varios servicios, así
# que el prefijo solo no dice a cuál va. `/api/v1/trabajos/{id}` es ambiguo
# —party y sales tienen trabajos, y el identificador no delata al dueño—, y por
# eso van bajo el nombre del servicio: `/api/v1/party/trabajos/{id}`.
#
# La alternativa era que el gateway preguntara a todos hasta que uno no
# respondiera 404: dobla la latencia de cada llamada y convierte un identificador
# equivocado en una ronda por toda la instalación. Un camino explícito no tiene
# ese problema y además se lee.
RECURSOS_TRANSVERSALES = {"trabajos", "retencion", "buscar"}

# Los nombres de servicio salen de la propia tabla de prefijos en vez de
# repetirse: dos listas que tienen que coincidir acaban no coincidiendo.
_NOMBRES_DE_SERVICIO = frozenset(PREFIJOS.values())


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


def servicio_de(ruta: str, servicios: frozenset[str] | None = None) -> str | None:
    """Servicio que atiende una ruta de la API. `None` si ninguna lo hace.

    `servicios` son los nombres desplegados; sirve para el camino
    `/api/v1/<servicio>/<recurso>` de los recursos transversales. Si no se pasa
    se usan los nombres que ya salen de la tabla de prefijos, que son los mismos
    y no hay que declararlos aparte.

    Sin acotarlo a nombres de servicio, `/api/v1/documentos/buscar` se resolvía
    al «servicio documentos», que no existe: el segmento del recurso se colaba
    por el camino del servicio porque detrás iba un nombre transversal.
    """
    conocidos = servicios if servicios is not None else _NOMBRES_DE_SERVICIO
    partes = [p for p in ruta.split("/") if p]
    # `/api/v1/<recurso>/...` → el recurso es el tercer segmento.
    if len(partes) >= 3 and partes[0] == "api":
        # Camino por servicio, para lo transversal. Se comprueba ANTES que los
        # prefijos: si no, un servicio que se llamara como un recurso —hoy
        # ninguno— se resolvería por el otro lado sin avisar.
        if len(partes) >= 4 and partes[3] in RECURSOS_TRANSVERSALES:
            if partes[2] in conocidos:
                return partes[2]
        if partes[2] == "comentarios":
            return OBJETOS_COMENTARIO.get(partes[3]) if len(partes) >= 4 else None
        if partes[2] == "adjuntos":
            # Un tipo de objeto desconocido devuelve `None` y el gateway
            # responde 404, que es lo correcto: no hay servicio que lo tenga.
            return _por_objeto(partes, OBJETOS_ADJUNTO)
        if partes[2] == "documentos":
            return _por_objeto(partes, OBJETOS_DOCUMENTO)
        return PREFIJOS.get(partes[2])
    return None


def _por_objeto(partes: list[str], tabla: dict[str, str]) -> str | None:
    """Resuelve el servicio por el tipo de objeto que lleva la ruta.

    El tipo va justo detrás del recurso, salvo cuando ahí hay un segmento
    literal (`/adjuntos/carpetas/<tipo>`), y entonces va uno más allá. Sin
    contemplarlo, esas rutas se resolvían buscando un objeto llamado «carpetas»
    y devolvían 404 con la funcionalidad entera detrás.

    Un segmento literal sin tipo detrás —como `/documentos/buscar`, que no es de
    ningún registro concreto— lo atiende cualquiera de los dueños; se manda al
    primero en orden estable para que dos peticiones iguales no acaben en
    servicios distintos.
    """
    if len(partes) < 4:
        return None
    if partes[3] in SEGMENTOS_LITERALES:
        if len(partes) >= 5:
            return tabla.get(partes[4])
        return sorted(set(tabla.values()))[0] if tabla else None
    return tabla.get(partes[3])
