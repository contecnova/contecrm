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
    # El chat interno vive en identidad porque es quien conoce a las personas,
    # sus permisos y por dónde quieren que se les avise (CRM-06.02.02).
    "chat": "identity",
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
    # El compromiso que se puede firmar con un proveedor detrás: lo calcula
    # `service`, que es quien conoce los SLA y las colas.
    "sla-proveedores": "service",
    "comunidad": "service",
    "segmentos": "marketing",
    "supresiones": "marketing",
    "puntuacion": "marketing",
    "campanas": "marketing",
    "atribucion": "marketing",
    "presion": "marketing",
    "rebotes": "marketing",
    "recorridos": "marketing",
    "canales-marketing": "marketing",
    "landings": "marketing",
    "dominios-envio": "marketing",
    "correo": "marketing",
    "preferencias": "marketing",
    # Aislamiento y residencia del dato por tenant (CRM-00.01.01, CRM-00.01.05).
    "aislamiento": "tenancy",
    "residencia": "tenancy",
    # Correo, calendario, chat, plantillas documentales y firma presencial
    # (CRM-06.01.01, CRM-06.01.02.09).
    "buzones": "integration",
    "canales-chat": "integration",
    # Suites de productividad (CRM-06.01.03): perfiles, consentimiento,
    # suscripciones y reuniones en línea.
    "suites": "integration",
    # Motor externo de compensación (CRM-03.02.03.04).
    "compensacion": "integration",
    # Telefonía conectada: screen pop y transferencia con contexto
    # (CRM-04.02.01.05).
    "telefonia": "integration",
    "plantillas-documento": "integration",
    "firma-presencial": "integration",
    # Consentimiento: el doble opt-in, las cookies y las reglas de contenido
    # (CRM-02.04.02.02, CRM-07.03.01.08, CRM-02.04.01.03).
    "optin": "marketing",
    "cookies": "marketing",
    "reglas-contenido": "marketing",
    # Lo que se le encarga a un tercero y hay que seguir. `proveedores-servicio`
    # se llama así y no `proveedores` porque en el CRM un proveedor es también
    # una cuenta: dos rutas parecidas apuntando a servicios distintos es cómo se
    # enruta mal una llamada y nadie entiende el 404.
    "productos": "sales",
    "listas-precio": "sales",
    "presupuestos": "sales",
    "cadencias": "sales",
    "territorios": "sales",
    "plantillas-actividad": "party",
    "visitas": "party",
    "recurrencias": "party",
    "cuotas": "sales",
    "partners": "sales",
    "niveles-partner": "sales",
    "registros-oportunidad": "sales",
    "portal-partner": "sales",
    "planes-comision": "sales",
    "liquidaciones": "sales",
    "fondos-mdf": "marketing",
    "solicitudes-mdf": "marketing",
    # Fase 6 — servicio de campo y activos instalados
    "ordenes-trabajo": "service",
    "tecnicos-campo": "service",
    "repuestos": "service",
    "planes-preventivos": "service",
    "sincronizacion-campo": "service",
    "activos": "service",
    "devoluciones": "service",
    "expedientes": "service",
    "problemas": "service",
    "dispositivos": "integration",
    "modelo-canonico": "integration",
    "sincronizacion": "integration",
    "conectores": "integration",
    "agentes-ia": "integration",
    "canales-entrada": "integration",
    "federacion": "integration",
    "convivencia": "integration",
    "mi-cola": "sales",
    "plantillas-correo": "sales",
    "agenda": "sales",
    "metodologias": "sales",
    "contratos": "sales",
    "suscripciones": "sales",
    "pedidos": "sales",
    "aprobaciones": "orchestrator",
    "analitica-procesos": "orchestrator",
    "encargos": "integration",
    "firma": "integration",
    "informes": "analytics",
    "almacen": "analytics",
    "metricas": "analytics",
    "analisis": "analytics",
    "ia": "intelligence",
    "cuadros-mando": "analytics",
    "explotacion": "analytics",
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
    # Calidad y gobierno del dato de cliente (CRM-01.01.04): golden record,
    # linaje, cola de excepciones y enriquecimiento.
    "calidad-dato": "party",
    "planes-cuenta": "party",
    "mapa-personas": "party",
    # El contacto que cambia de empresa: la sospecha, su confirmación y su
    # descarte. Lo lleva `party` porque la ficha es suya.
    "cambios-de-empresa": "party",
    # Clonar, escindir, fusionar y perfilar un tenant: lo más caro de deshacer
    # que tiene el producto, y por eso se simula antes.
    "ciclo-vida": "tenancy",
    # El proveedor es una cuenta con rol (CRM-09.01.01.01); esto es lo que se
    # le añade encima: homologación, papeles y contactos.
    "proveedores": "party",
    "oportunidades": "sales",
    # Coste, tarifas de proveedor y capacidad (CRM-09.02.01).
    "coste": "sales",
    # El contrato con el proveedor y su alcance comercial: va a `sales` y no a
    # `party` porque las dos cosas deciden qué se puede vender
    # (CRM-09.01.01.07, CRM-09.01.01.09).
    "proveedores-comerciales": "sales",
    # Ingresos recurrentes, reparto, grupo de compra y plan conjunto
    # (CRM-03.01.01, CRM-03.01.02).
    "ingresos": "sales",
    "planes-conjuntos": "sales",
    # Modelos entrenados, transcripción, variantes y sugerencia en el caso
    # (CRM-02.01.02, CRM-01.02.01.05, CRM-02.04.01.04, CRM-04.03.01.04).
    "modelos": "intelligence",
    "transcripciones": "intelligence",
    "variantes": "intelligence",
    "sugerencias-caso": "intelligence",
    # Voz y asistentes conversacionales (CRM-04.02.01.08).
    "voz": "intelligence",
    # Marcador integrado, grabación y registro automático (CRM-03.03.01.05).
    "marcador": "service",
    # Entornos de pruebas con datos del cliente (CRM-07.02.01.02).
    "sandboxes": "tenancy",
    # Configuración como código: paquetes, promoción, desvío y vuelta atrás
    # (CRM-07.02.01).
    "entornos": "metadata",
    # Hora y canal por destinatario (CRM-02.02.02.05).
    "momento": "marketing",
    # Publicidad, biblioteca de activos y redes sociales (CRM-02.03, CRM-02.04,
    # CRM-04.02.01.06).
    "audiencias-externas": "marketing",
    "activos-marketing": "marketing",
    "social": "marketing",
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
    "presupuesto": "sales",
    "pedido": "sales",
    "contrato": "sales",
    # En un caso el comentario interno es medio trabajo: sin él se acaba
    # escribiendo en la descripción, que es lo que se le enseña al cliente.
    "caso": "service",
    "orden_trabajo": "service",
}

OBJETOS_ADJUNTO: dict[str, str] = {
    "cuenta": "party",
    "contacto": "party",
    "actividad": "party",
    "lead": "sales",
    "oportunidad": "sales",
    "linea_oportunidad": "sales",
    "presupuesto": "sales",
    "pedido": "sales",
    "contrato": "sales",
    # Un caso sin poder colgar la foto de la pieza rota obliga a mandarla por
    # correo aparte, y entonces la mitad de lo que lo explica no está en él.
    "caso": "service",
    "orden_trabajo": "service",
}

# Y lo mismo con los documentos del corpus (RT-5): el enlace lo guarda el
# servicio dueño del registro, así que el tipo de objeto vuelve a decidir.
OBJETOS_DOCUMENTO: dict[str, str] = {
    "cuenta": "party",
    "contacto": "party",
    "actividad": "party",
    "lead": "sales",
    "oportunidad": "sales",
    "presupuesto": "sales",
    "pedido": "sales",
    "contrato": "sales",
    "caso": "service",
}

# Recursos TRANSVERSALES: los monta la misma fábrica en varios servicios, así
# que el prefijo solo no dice a cuál va. `/api/v1/trabajos/{id}` es ambiguo
# —party y sales tienen trabajos, y el identificador no delata al dueño—, y por
# eso van bajo el nombre del servicio: `/api/v1/party/trabajos/{id}`.
#
# La alternativa era que el gateway preguntara a todos hasta que uno no
# respondiera 404: dobla la latencia de cada llamada y convierte un identificador
# equivocado en una ronda por toda la instalación. Un camino explícito no tiene
# ese problema y además se lee.
# Las rutas con las que se CONSIGUE una sesión.
#
# Una cookie caducada no puede hacerlas fallar: son justamente por donde se sale
# de tener la sesión caducada. El resto de la API sí responde «el token ha
# caducado», que es lo que el navegador necesita oír para renovar.
RUTAS_DE_SESION = frozenset(
    {
        "/api/v1/auth/login",
        "/api/v1/auth/refresh",
        "/api/v1/auth/sso",
    }
)

# El portal es **un solo espacio de direcciones** y lo sirven varios servicios.
#
# `/api/v1/portal/mi/<seccion>`: los casos, el conocimiento, la comunidad y los
# activos los sirve `service`, que es quien tiene la tabla de accesos; los
# contratos y los pedidos son de `sales` y los contactos de `party`. Traerlos
# todos a `service` obligaría a copiar sus tablas, y la copia es siempre la que
# se queda vieja.
#
# Va por sección y no por un prefijo distinto para cada servicio porque quien
# monta el portal no tiene por qué saber de qué servicio es cada cosa: eso es
# justo lo que el gateway existe para esconder.
#
# Lo que NO lleva sección —`/portal/entrar`, `/portal/mi/resumen`— lo sigue
# atendiendo `service` por la tabla de prefijos.
SECCIONES_PORTAL = {
    "casos": "service",
    "conocimiento": "service",
    "comunidad": "service",
    "activos": "service",
    "contratos": "sales",
    "pedidos": "sales",
    "contactos": "party",
}

RECURSOS_TRANSVERSALES = {
    # Los vocabularios de negocio: los publica cada servicio en su prefijo, como
    # la papelera, y por lo mismo — los valida él, en su esquema.
    "vocabularios",
    "trabajos",
    "retencion",
    "buscar",
    # Cada servicio restaura lo suyo y declara lo suyo (CRM-00.06.02.03,
    # CRM-07.03.01.04): la ruta lleva el nombre del servicio porque los doce
    # publican la misma, y sin él no habría a quién mandarla.
    "restauracion",
    # La cola del móvil sin conexión: cada servicio resuelve los objetos que
    # guarda él, contra sus propios registros.
    "movil",
    # La papelera también es de cada servicio: cada uno guarda la suya en su
    # esquema, que es lo que impide que un servicio lea las tablas de otro.
    "papelera",
    "cumplimiento",
}

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
        if partes[2] == "portal" and len(partes) >= 5 and partes[3] == "mi":
            # La sección decide el servicio. Una desconocida cae a `service`,
            # que es el dueño del portal y contesta qué secciones hay — mejor
            # error que el 404 del gateway, que no dice si te equivocaste de
            # sección o si el portal no existe.
            return SECCIONES_PORTAL.get(partes[4], "service")
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

    El tipo va justo detrás del recurso —`/documentos/cuenta/{id}`— salvo cuando
    ahí hay un segmento que no es un tipo, y entonces puede ir uno más allá
    (`/adjuntos/carpetas/cuenta`) o no ir en absoluto
    (`/documentos/carpetas/{id}/permisos`, que no es de ningún registro).

    **Se mira si el segmento ES un tipo conocido, no si está en una lista de
    palabras.** Había una lista —`carpetas`, `estado`, `buscar`…— y hacía dos
    cosas mal a la vez: cada ruta nueva con un segmento literal quedaba
    inalcanzable hasta que alguien se acordaba de añadir la palabra, y la misma
    palabra significaba cosas distintas en dos recursos —en `/adjuntos` a
    `carpetas` le sigue un tipo de objeto y en `/documentos` le sigue un
    identificador de carpeta—, así que la lista no podía acertar en los dos.
    Preguntar por el tipo no tiene ninguno de los dos problemas.

    Cuando la ruta no habla de un registro concreto la atiende cualquiera de los
    dueños, y se manda al primero en orden estable para que dos peticiones
    iguales no acaben en servicios distintos.

    Un tipo mal escrito llega así a un servicio que sí publica el recurso, y este
    contesta qué tipos admite. Es mejor error que el 404 del gateway: «no existe
    ese camino» no dice si te equivocaste de tipo o si el recurso no existe.
    """
    if len(partes) < 4:
        return None
    if partes[3] in tabla:
        return tabla[partes[3]]
    if len(partes) >= 5 and partes[4] in tabla:
        return tabla[partes[4]]
    return sorted(set(tabla.values()))[0] if tabla else None
