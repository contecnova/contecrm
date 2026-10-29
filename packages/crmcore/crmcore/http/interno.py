"""Llamadas entre servicios de la casa, firmadas.

Un servicio necesita a veces preguntar algo a otro. No lee su base —los
permisos de Postgres no se lo permiten, y ese es justo el punto—, así que lo
pregunta por HTTP. Aquí está lo común: dónde vive cada servicio y cómo se firma
la llamada.

La dirección sale de `RUTAS_SERVICIOS`, la misma variable que usa el gateway
para enrutar. Tenerla en un solo sitio es lo que evita que un despliegue mueva
un servicio y la mitad del sistema siga hablando con la dirección vieja.
"""

from __future__ import annotations

from typing import Any

from crmcore.errors import NoDisponible
from crmcore.logging import get_logger

logger = get_logger(__name__)


def direccion_de(servicio: str) -> str:
    """Dónde escucha un servicio, según `RUTAS_SERVICIOS`. Cadena vacía si no consta."""
    from crmcore.config import get_settings

    for trozo in get_settings().rutas_servicios.replace("\n", "").split(","):
        nombre, _, url = trozo.strip().partition("=")
        if nombre.strip() == servicio:
            return url.strip().rstrip("/")
    return ""


def cabeceras_firmadas() -> dict[str, str]:
    """Firma una llamada interna SIN identidad de usuario.

    Todos los valores van vacíos a propósito: esto no suplanta a nadie. Es el
    servicio diciendo «soy de la casa», y solo sirve para rutas que no deciden
    nada sobre datos de un usuario concreto.
    """
    from crmcore.config import get_settings
    from crmcore.http.deps import (
        H_ACTOR_REAL,
        H_PERMISOS,
        H_PLATAFORMA,
        H_ROLES,
        H_SCOPES,
        H_TENANT,
        H_USER,
        firmar_cabeceras_internas,
    )

    vacias = dict.fromkeys(
        (H_TENANT, H_USER, H_PERMISOS, H_ROLES, H_SCOPES, H_ACTOR_REAL, H_PLATAFORMA), ""
    )
    return firmar_cabeceras_internas(vacias, get_settings().secret_key.get_secret_value())


# Con qué tipo firma el agente autónomo sus llamadas. Del vocabulario común,
# que es el único sitio donde las dos mitades —quien lo escribe y quien lo
# mira— pueden coincidir por construcción.
TIPO_DEL_AGENTE = "agente"


def cabeceras_de(
    *,
    tenant_id: Any,
    principal_id: Any,
    permisos: list[str] | None = None,
    roles: list[str] | None = None,
) -> dict[str, str]:
    """Firma una llamada interna CON una identidad concreta.

    Lo contrario de `cabeceras_firmadas`, y la diferencia importa: aquella dice
    «soy de la casa» y no puede tocar datos de nadie; ésta dice **quién** hace la
    llamada, así que el servicio de destino aplica sus permisos, su compartición
    y su rastro de auditoría como con cualquier persona.

    Se usa para el agente autónomo, que es un principal de máquina con permisos
    propios —normalmente un subconjunto de los de quien lo puso en marcha—. Un
    agente que llamara con las cabeceras vacías tendría el poder de «la casa»,
    que no es acotable y no aparece en el rastro como nadie.
    """
    from crmcore.config import get_settings
    from crmcore.http.deps import (
        H_ACTOR_REAL,
        H_PERMISOS,
        H_PLATAFORMA,
        H_ROLES,
        H_SCOPES,
        H_TENANT,
        H_TIPO,
        H_USER,
        firmar_cabeceras_internas,
    )

    valores = {
        H_TENANT: str(tenant_id or ""),
        H_USER: str(principal_id or ""),
        # Máquina, no persona: a una credencial de máquina no se le aplica la
        # compartición entre usuarios, porque no posee registros.
        #
        # El valor sale del vocabulario y no de una cadena suelta. Aquí ponía
        # «maquina», que no casaba con ninguna de las dos palabras que miran
        # los consumidores, así que el agente llamaba como si fuera una
        # persona: la compartición le aplicaba su filtro, esa persona no posee
        # registros, y `GET /accounts` devolvía cero filas con un 200.
        H_TIPO: TIPO_DEL_AGENTE,
        H_PERMISOS: ",".join(sorted(permisos or [])),
        H_ROLES: ",".join(sorted(roles or [])),
        H_SCOPES: "",
        H_ACTOR_REAL: "",
        # Nunca admin de plataforma. Un agente actúa dentro de un tenant; si
        # pudiera marcarse como plataforma, cualquier error suyo sería un error
        # con alcance de todos los clientes.
        H_PLATAFORMA: "",
    }
    return firmar_cabeceras_internas(valores, get_settings().secret_key.get_secret_value())


def invocar(
    *,
    metodo: str,
    ruta: str,
    parametros: dict[str, Any] | None = None,
    cuerpo: dict[str, Any] | None = None,
    tenant_id: Any,
    principal_id: Any,
    permisos: list[str] | None = None,
    roles: list[str] | None = None,
    timeout_s: float = 30.0,
) -> dict[str, Any]:
    """Llama a una ruta de la API del CRM con una identidad concreta.

    El servicio de destino **se resuelve de la ruta**, con la misma tabla que
    usa el gateway (`crmcore.rutas_de_api`). No se pasa como argumento a
    propósito: quien llama —el agente— conoce la ruta porque la sacó del
    contrato publicado, y no tiene por qué saber cómo está repartido el sistema
    por dentro.

    Devuelve siempre un diccionario con `estado` y `datos`, también cuando el
    destino contesta 4xx. Un error del destino es **información para el
    agente**: si se convirtiera en excepción, el paso se marcaría como caído y
    el modelo no podría leer el porqué ni corregir en el paso siguiente. Lo que
    sí lanza es no poder llamar —ruta sin dueño, servicio sin dirección, red
    caída—, porque eso no es una respuesta y tratarlo como tal haría que el
    agente informara de un «no hay nada» que nadie ha comprobado.
    """
    import httpx

    from crmcore.rutas_de_api import servicio_de

    servicio = servicio_de(ruta.lstrip("/"))
    if not servicio:
        raise NoDisponible(
            f"Ningún servicio atiende «{ruta}»",
            error_code="interno.ruta_sin_dueno",
            detalle={"ruta": ruta},
        )
    base = direccion_de(servicio)
    if not base:
        raise NoDisponible(
            f"No hay dirección configurada para el servicio «{servicio}»",
            error_code="interno.servicio_sin_direccion",
            detalle={"servicio": servicio, "ruta": ruta},
        )

    cabeceras = cabeceras_de(
        tenant_id=tenant_id, principal_id=principal_id, permisos=permisos, roles=roles
    )
    try:
        salida = httpx.request(
            metodo.upper(),
            f"{base}{ruta}",
            params=parametros or None,
            json=cuerpo if cuerpo is not None else None,
            headers=cabeceras,
            timeout=timeout_s,
        )
    except httpx.HTTPError as exc:
        logger.error(
            "interno.invocacion_sin_respuesta", servicio=servicio, ruta=ruta, error=str(exc)[:200]
        )
        raise NoDisponible(
            f"El servicio «{servicio}» no responde",
            error_code="interno.servicio_no_responde",
            detalle={"servicio": servicio, "ruta": ruta},
        ) from exc

    try:
        datos: Any = salida.json()
    except ValueError:
        # Una descarga, un 204 o un error en HTML. El texto recortado vale más
        # que un diccionario vacío: con el vacío, el agente no distingue «no hay
        # nada» de «no he sabido leer la respuesta».
        datos = {"texto": salida.text[:2000]}
    # **Lo que el destino ha tapado o retenido viaja con la respuesta.**
    #
    # Va en cabeceras, y leer sólo el cuerpo las tiraba. Medido el 29-10-2026:
    # el agente autónomo preguntó por tres cuentas y contestó que se llamaban
    # «··············tora», «··cosa» y «·············elta» — con seguridad,
    # porque un valor enmascarado tiene la forma de un dato y nada en el cuerpo
    # decía lo contrario. Con esto, el modelo recibe que esos campos están
    # tapados y puede decir que no los ve en vez de inventárselos.
    sin_dar = [c for c in (salida.headers.get("x-campos-retenidos") or "").split(",") if c]
    tapados = [c for c in (salida.headers.get("x-campos-enmascarados") or "").split(",") if c]
    respuesta: dict[str, Any] = {
        "estado": salida.status_code,
        "ok": salida.status_code < 400,
        "datos": datos,
    }
    if sin_dar:
        respuesta["campos_no_entregados"] = sin_dar
    if tapados:
        respuesta["campos_tapados"] = tapados
        respuesta["aviso"] = (
            "Estos campos vienen TAPADOS, no en claro: "
            f"{', '.join(tapados)}. Lo que se ve en ellos no es su valor y no "
            "se puede citar como tal."
        )
    return respuesta


def pedir(servicio: str, ruta: str, *, timeout_s: float = 5.0) -> dict[str, Any] | None:
    """GET firmado a otro servicio. `None` si contesta 404.

    Un fallo de red se convierte en `NoDisponible` y no en un error genérico:
    quien llama tiene que poder distinguir «no existe» de «no he podido
    preguntar», porque la respuesta al usuario es distinta —y tratar lo segundo
    como lo primero es cómo se acaba diciendo «no existe» de algo que sí existe.
    """
    import httpx

    base = direccion_de(servicio)
    if not base:
        raise NoDisponible(
            f"No hay dirección configurada para el servicio «{servicio}»",
            error_code="interno.servicio_sin_direccion",
        )
    try:
        salida = httpx.get(f"{base}{ruta}", headers=cabeceras_firmadas(), timeout=timeout_s)
    except httpx.HTTPError as exc:
        logger.error("interno.sin_respuesta", servicio=servicio, ruta=ruta, error=str(exc)[:200])
        raise NoDisponible(
            f"El servicio «{servicio}» no responde",
            error_code="interno.servicio_no_responde",
        ) from exc
    if salida.status_code == 404:
        return None
    if salida.status_code >= 400:
        raise NoDisponible(
            f"El servicio «{servicio}» ha contestado {salida.status_code}",
            error_code="interno.respuesta_inesperada",
        )
    return dict(salida.json())


def avisar(servicio: str, ruta: str, datos: dict[str, Any], *, timeout_s: float = 3.0) -> bool:
    """POST firmado a otro servicio, **sin romper al que llama**.

    Devuelve si llegó. Es para avisos que no son el trabajo principal de quien
    llama —empujar un evento a los clientes conectados, por ejemplo—: si el
    destino no está configurado o no responde, lo que no puede pasar es que se
    caiga la entrega que sí importa. Se registra y se sigue.

    Es lo contrario de `pedir`, y a propósito: allí no poder preguntar cambia la
    respuesta al usuario, y aquí no.
    """
    import httpx

    base = direccion_de(servicio)
    if not base:
        return False
    try:
        salida = httpx.post(
            f"{base}{ruta}", json=datos, headers=cabeceras_firmadas(), timeout=timeout_s
        )
    except httpx.HTTPError as exc:
        logger.warning("interno.aviso_sin_respuesta", servicio=servicio, error=str(exc)[:200])
        return False
    if salida.status_code >= 400:
        logger.warning("interno.aviso_rechazado", servicio=servicio, estado=salida.status_code)
        return False
    return True


def resolver_tenant(valor: str) -> Any:
    """Traduce el identificador o el slug del tenant a UUID.

    Vive aquí y no en un servicio porque lo necesitan **todas las puertas de
    entrada**, y hay más de una: el inicio de sesión del CRM, el portal del
    partner, el del cliente. A esas rutas se llega sin credencial —es donde se
    consigue la primera— así que el tenant no puede venir del principal: llega
    en el cuerpo, como una pista sin firmar, y lo que concede acceso es lo que
    venga detrás.

    Se pregunta a `tenancy` por HTTP en vez de leer su tabla: la propiedad
    exclusiva de datos por servicio es justo lo que hace que esa consulta ni
    siquiera esté permitida a nivel de permisos de base de datos.

    **El error es el mismo que una credencial mal puesta**, y a propósito: decir
    «esa organización no existe» convierte cualquier pantalla de acceso en un
    buscador de clientes, que es media lista de la competencia.
    """
    from crmcore.errors import ErrorValidacion
    from crmcore.ids import es_id_valido, sin_prefijo

    if es_id_valido(valor):
        return sin_prefijo(valor)

    datos = pedir("tenancy", f"/api/v1/interno/tenants/por-slug/{valor}")
    if datos is None:
        raise ErrorValidacion(
            "Credenciales no válidas",
            error_code="auth.credenciales_invalidas",
        )
    return sin_prefijo(str(datos["tenant_id"]))
