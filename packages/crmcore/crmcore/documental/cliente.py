"""Hablar con el gestor documental, sin bajarle la credencial al navegador.

Mismo patrón que el cliente de contecintelligence (RT-4) y por las mismas
razones, así que quien entienda uno entiende el otro:

**La credencial de aplicación no baja nunca al navegador.** Con ella se canjea,
en el servidor, un token corto por usuario. La credencial puede representar a
todos los tenants; si llegara al navegador sería la llave de todos.

**El estado se cachea y no se comprueba en cada `/health/ready`.** Una
comprobación de salud que hace una llamada de red a otro sistema convierte la
lentitud de ese sistema en la nuestra — y, si el orquestador la usa para
reiniciar, en un reinicio en cascada.

**Un gestor caído no impide arrancar**, salvo que se pida. El CRM operativo no
puede depender del corpus documental: sin gestor hay CRM y hay adjuntos, lo que
no hay es corpus.
"""

from __future__ import annotations

import time
from typing import Any

from crmcore.errors import NoDisponible
from crmcore.logging import get_logger

logger = get_logger(__name__)

_estado: dict[str, Any] = {
    "alcanzable": None,
    "comprobado_at": None,
    "latencia_ms": None,
    "error": None,
    "version": None,
}


def _config() -> Any:
    from crmcore.config import get_settings

    s = get_settings()
    if not s.dms_enabled:
        raise NoDisponible(
            "El corpus documental está desactivado en este despliegue "
            "(DMS_ENABLED=false). Los adjuntos de los registros siguen "
            "funcionando: son otra cosa",
            error_code="documental.desactivado",
        )
    if not s.dms_base_url:
        raise NoDisponible(
            "No hay gestor documental configurado: el corpus lo resuelve "
            "contecmind (RT-5), así que hay que levantarlo con la pila o dar la "
            "dirección de uno ya en marcha en DMS_BASE_URL",
            error_code="documental.sin_configurar",
        )
    return s


def estado() -> dict[str, Any]:
    """Lo último que se sabe, sin volver a preguntar."""
    from crmcore.config import get_settings

    s = get_settings()
    return {
        **_estado,
        "activo": s.dms_enabled,
        "url": s.dms_base_url or None,
        "obligatorio_para_arrancar": s.dms_exigir_al_arrancar,
        # Se dice qué sigue funcionando sin él. Sin esta línea, un `/health` que
        # dice «documental: no alcanzable» hace pensar que no se puede adjuntar
        # nada, y sí se puede.
        "sin_el": "los adjuntos de los registros funcionan igual; no hay corpus documental",
    }


def comprobar() -> dict[str, Any]:
    """Pregunta si está vivo y guarda el resultado.

    Se consulta su contrato publicado, que no exige autenticación: así una
    credencial mal puesta se distingue de un sistema caído, que son dos
    problemas con dos soluciones distintas.

    **Bajo el prefijo de versión y no en la raíz.** Se pedía `/openapi.json` a
    secas y contecmind lo publica en `/api/v1/openapi.json`, así que el estado
    decía «no alcanzable» con un 404 sobre un gestor perfectamente vivo — y la
    pestaña del corpus aparecía apagada sin que nada estuviera mal. Se prueban
    las dos por orden: el prefijo primero, porque es donde está el contrato de
    la API que de verdad se consume, y la raíz después para un gestor que lo
    publique allí.
    """
    from crmcore.red import cliente_seguro

    s = _config()
    base = s.dms_base_url.rstrip("/")
    candidatas = [f"{base}{RUTA_APLICACION.rsplit('/', 2)[0]}/openapi.json", f"{base}/openapi.json"]
    inicio = time.monotonic()
    exc: Exception | None = None
    contrato: dict[str, Any] = {}
    try:
        with cliente_seguro(timeout=s.dms_timeout_s) as cli:
            for url in candidatas:
                try:
                    respuesta = cli.get(url)
                    respuesta.raise_for_status()
                    contrato = respuesta.json()
                    exc = None
                    break
                except Exception as fallo:  # noqa: BLE001 — se prueba la siguiente
                    exc = fallo
        if exc is not None:
            raise exc
    except Exception as exc:  # noqa: BLE001 — cualquier fallo aquí es «no alcanzable»
        _estado.update(
            alcanzable=False,
            comprobado_at=time.time(),
            latencia_ms=int((time.monotonic() - inicio) * 1000),
            error=str(exc)[:300],
            version=None,
        )
        logger.error("documental.gestor_no_alcanzable", url=s.dms_base_url, error=str(exc)[:200])
        return dict(_estado)

    _estado.update(
        alcanzable=True,
        comprobado_at=time.time(),
        latencia_ms=int((time.monotonic() - inicio) * 1000),
        error=None,
        version=str((contrato.get("info") or {}).get("version") or ""),
    )
    logger.info("documental.gestor_listo", url=s.dms_base_url, version=_estado["version"])
    return dict(_estado)


def comprobar_al_arrancar() -> None:
    """El fallo se dice al desplegar, no al abrir el primer documento."""
    from crmcore.config import get_settings

    s = get_settings()
    if not s.dms_enabled or not s.dms_comprobar_al_arrancar:
        return
    if not s.dms_base_url:
        mensaje = (
            "DMS_ENABLED está activo y falta DMS_BASE_URL: el corpus documental "
            "lo resuelve contecmind (RT-5)"
        )
        if s.dms_exigir_al_arrancar:
            raise RuntimeError(mensaje)
        logger.error("documental.sin_configurar", aviso=mensaje)
        return

    resultado = comprobar()
    if not resultado["alcanzable"] and s.dms_exigir_al_arrancar:
        raise RuntimeError(
            f"El gestor documental no responde en {s.dms_base_url}: "
            f"{resultado['error']}. Con DMS_EXIGIR_AL_ARRANCAR=false el servicio "
            f"arranca igual y el corpus queda degradado"
        )


class TokenUsuario:
    """Token corto, por usuario y por organización. No es la credencial."""

    __slots__ = ("token", "expira_en_s", "organizacion", "alcances")

    def __init__(
        self, token: str, expira_en_s: int, organizacion: str, alcances: tuple[str, ...]
    ) -> None:
        self.token = token
        self.expira_en_s = expira_en_s
        self.organizacion = organizacion
        self.alcances = alcances


# Las dos rutas del canje. Son las mismas que las de contecintelligence salvo el
# prefijo `/api/v1`, que es el que usa contecmind para todo su contrato.
RUTA_APLICACION = "/api/v1/oauth/token"
RUTA_CANJE = "/api/v1/tokens/exchange"

# El token de aplicación del paso 1, guardado mientras dure. Ver el homólogo en
# `services/analytics/cliente.py`: los dos clientes de la casa hacen lo mismo y
# de la misma forma, a propósito.
_aplicacion: dict[str, Any] = {"token": "", "expira_at": 0.0}
_MARGEN_S = 30.0


def _token_de_aplicacion(s: Any) -> str:
    """Paso 1: la credencial se cambia por un token de aplicación.

    Esto faltaba. El cliente iba **directo al canje** mandando la credencial como
    autenticación básica, y eso no es lo que hace el otro cliente de la casa ni
    lo que espera el otro lado.

    Se alinea AHORA, antes de que contecmind implemente su parte, y no aceptando
    también Basic allí. Dos motivos, y el primero no es de gusto: Basic mandaría
    el secreto **largo** en cada canje, y el canje está en el camino de abrir una
    pantalla —o sea, la credencial cruzando proxies y registros decenas de veces
    al día en vez de un token de quince minutos—. El segundo es que el viaje que
    ahorraría no existe: este token se guarda, así que es una llamada cada cuarto
    de hora, no una por canje.
    """
    from crmcore.errors import ErrorDependencia
    from crmcore.red import cliente_seguro

    ahora = time.monotonic()
    if _aplicacion["token"] and float(_aplicacion["expira_at"]) - _MARGEN_S > ahora:
        return str(_aplicacion["token"])

    try:
        with cliente_seguro(timeout=s.dms_timeout_s) as cli:
            respuesta = cli.post(
                s.dms_base_url.rstrip("/") + RUTA_APLICACION,
                json={
                    "client_id": s.dms_client_id,
                    "client_secret": s.dms_client_secret.get_secret_value(),
                    "grant_type": "client_credentials",
                },
            )
    except Exception as exc:  # noqa: BLE001
        raise ErrorDependencia(
            "No se ha podido contactar con el gestor documental",
            error_code="documental.inalcanzable",
            detalle={"error": str(exc)[:200]},
        ) from exc

    if respuesta.status_code >= 400:
        logger.warning("documental.credencial_rechazada", codigo_http=respuesta.status_code)
        raise ErrorDependencia(
            "El gestor documental ha rechazado la credencial de aplicación",
            error_code="documental.credencial_rechazada",
            detalle={"codigo_http": respuesta.status_code},
        )

    datos = respuesta.json()
    token = str(datos.get("access_token") or "")
    if not token:
        raise ErrorDependencia(
            "El gestor documental no ha devuelto token de aplicación",
            error_code="documental.respuesta_invalida",
        )
    _aplicacion["token"] = token
    _aplicacion["expira_at"] = ahora + float(datos.get("expires_in") or 300)
    return token


def canjear_token(
    *, organizacion: str, sujeto: str, rol: str, alcances: list[str] | None = None
) -> TokenUsuario:
    """Cambia la credencial de aplicación por un token de usuario final.

    `organizacion` sale **de la correspondencia guardada**, nunca de lo que
    mande el cliente: el gestor solo acepta nombrar organizaciones mapeadas, y
    ese control se pierde en cuanto el nombre viaja desde el navegador. Es lo
    que hace que esto sea multitenant de verdad y no una confianza en que el de
    enfrente filtre bien.

    El `rol` se traduce de lo que la persona puede ver **aquí**: un corpus
    documental que enseña más que el CRM es una fuga con otro nombre.
    """
    from crmcore.errors import ErrorDependencia, ErrorValidacion
    from crmcore.red import cliente_seguro

    s = _config()
    if not s.dms_client_id or not s.dms_client_secret:
        raise NoDisponible(
            "Falta la credencial de aplicación del gestor documental "
            "(DMS_CLIENT_ID / DMS_CLIENT_SECRET)",
            error_code="documental.sin_credencial",
        )
    if not organizacion:
        raise ErrorValidacion(
            "Este tenant no tiene organización asignada en el gestor documental",
            error_code="documental.sin_organizacion",
        )

    cuerpo = {
        "tenant": organizacion,
        "subject": sujeto,
        "role": rol,
        "scopes": alcances or list(s.dms_scopes),
        # `ttl_s`, el nombre que ya usa el otro cliente de la casa. Aquí decía
        # `ttl`: con el nombre mal, pydantic lo ignora y el token sale con la
        # duración por defecto del otro lado, sin error y sin aviso.
        "ttl_s": int(s.dms_token_ttl_s),
    }
    try:
        aplicacion = _token_de_aplicacion(s)
        with cliente_seguro(timeout=s.dms_timeout_s) as cli:
            respuesta = cli.post(
                s.dms_base_url.rstrip("/") + RUTA_CANJE,
                json=cuerpo,
                headers={"Authorization": f"Bearer {aplicacion}"},
            )
    except ErrorDependencia:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ErrorDependencia(
            "No se ha podido contactar con el gestor documental",
            error_code="documental.inalcanzable",
            detalle={"error": str(exc)[:200]},
        ) from exc

    if respuesta.status_code >= 400:
        # Sin el cuerpo: puede traer detalles de nuestra credencial.
        logger.warning(
            "documental.canje_rechazado",
            codigo_http=respuesta.status_code,
            organizacion=organizacion,
        )
        raise ErrorDependencia(
            "El gestor documental ha rechazado el canje del token",
            error_code="documental.canje_rechazado",
            detalle={"codigo_http": respuesta.status_code},
        )

    datos = respuesta.json()
    token = datos.get("token") or datos.get("access_token")
    if not token:
        raise ErrorDependencia(
            "El gestor documental no ha devuelto token",
            error_code="documental.canje_sin_token",
        )
    return TokenUsuario(
        token=str(token),
        expira_en_s=int(datos.get("expires_in") or s.dms_token_ttl_s),
        organizacion=organizacion,
        alcances=tuple(cuerpo["scopes"]),
    )


def rol_para(permisos: frozenset[str], es_admin: bool) -> str:
    """Traduce los permisos del CRM al rol que entiende el gestor.

    Se manda el rol que corresponde a lo que la persona puede ver aquí. Mandar
    siempre el más alto —o el de la credencial— haría que cualquiera con acceso
    al CRM viera el corpus entero del tenant, incluidos los contratos que no le
    tocan.
    """
    if es_admin or "documento:admin" in permisos or "*:*" in permisos:
        return "admin"
    if "documento:escribir" in permisos or "adjunto:subir" in permisos:
        return "writer"
    return "reader"


def buscar(texto: str, *, token_usuario: str, limite: int = 20) -> list[dict[str, Any]]:
    """Busca en el corpus **con la identidad del usuario**, no con la nuestra.

    Es lo que hace que la integración sea frontless y no un agujero: el gestor
    aplica sus propios permisos sobre ese token, así que un usuario del CRM ve
    en el buscador exactamente lo que vería entrando al gestor. Buscar con la
    credencial de aplicación le enseñaría el corpus entero del tenant.
    """
    from crmcore.red import cliente_seguro

    s = _config()
    with cliente_seguro(timeout=s.dms_timeout_s) as cli:
        respuesta = cli.get(
            s.dms_base_url.rstrip("/") + "/api/v1/documents/search",
            params={"q": texto, "limit": limite},
            headers={"Authorization": f"Bearer {token_usuario}"},
        )
    if respuesta.status_code == 401:
        raise NoDisponible(
            "El gestor documental ha rechazado la identidad del usuario",
            error_code="documental.identidad_rechazada",
        )
    respuesta.raise_for_status()
    cuerpo = respuesta.json()
    return list(cuerpo.get("items") or cuerpo.get("results") or [])


def ficha(documento_id: str, *, token_usuario: str) -> dict[str, Any]:
    """El estado real del documento: versión publicada, si está obsoleto.

    Se pregunta **al abrirlo** y no se cachea en el enlace. Un «aprobado»
    caducado en una pantalla del CRM es peor que no enseñar el estado: alguien
    firmará algo creyendo que la versión vigente es otra.
    """
    from crmcore.red import cliente_seguro

    s = _config()
    with cliente_seguro(timeout=s.dms_timeout_s) as cli:
        respuesta = cli.get(
            s.dms_base_url.rstrip("/") + f"/api/v1/documents/{documento_id}",
            headers={"Authorization": f"Bearer {token_usuario}"},
        )
    if respuesta.status_code == 404:
        from crmcore.errors import NoEncontrado

        # El documento se borró en el gestor y el enlace del CRM se quedó
        # colgando. Se dice tal cual: inventarse un estado sería peor.
        raise NoEncontrado(
            "El documento ya no existe en el gestor documental",
            error_code="documental.documento_no_existe",
        )
    respuesta.raise_for_status()
    return dict(respuesta.json())


# ── El árbol de carpetas (RT-5) ───────────────────────────────────────────
#
# Todo lo de aquí va **con la identidad del usuario**, igual que la búsqueda y
# por lo mismo: contecmind aplica sus permisos sobre ese token, así que el árbol
# que ve alguien desde el CRM es exactamente el que vería entrando al gestor.
# Con la credencial de aplicación vería el corpus entero del tenant.
#
# Y una consecuencia que hay que tener presente al pintar: **una carpeta
# denegada no aparece**, ni ella ni lo que cuelga. Un árbol con huecos no es un
# fallo de paginación ni una lista incompleta: es el filtro haciendo su trabajo.
# Contarlo como error llevaría a «reintentar» eternamente algo que está bien.


def _llamar(
    metodo: str,
    ruta: str,
    *,
    token_usuario: str,
    params: dict[str, Any] | None = None,
    cuerpo: dict[str, Any] | None = None,
    timeout: float | None = None,
) -> Any:
    """Una llamada al gestor con la identidad del usuario, con sus errores."""
    from crmcore.errors import ErrorDependencia, NoEncontrado, Prohibido
    from crmcore.red import cliente_seguro

    s = _config()
    with cliente_seguro(timeout=timeout or s.dms_timeout_s) as cli:
        respuesta = cli.request(
            metodo,
            s.dms_base_url.rstrip("/") + ruta,
            params=params,
            json=cuerpo,
            headers={"Authorization": f"Bearer {token_usuario}"},
        )
    if respuesta.status_code == 401:
        raise NoDisponible(
            "El gestor documental ha rechazado la identidad del usuario",
            error_code="documental.identidad_rechazada",
        )
    if respuesta.status_code == 403:
        raise Prohibido(
            "El gestor documental no deja hacer eso con esta identidad",
            error_code="documental.sin_permiso",
        )
    if respuesta.status_code == 404:
        raise NoEncontrado(
            "Eso ya no existe en el gestor documental",
            error_code="documental.no_existe",
        )
    if respuesta.status_code >= 500:
        # CON EL MOTIVO DEL GESTOR. Antes se dejaba subir el `raise_for_status`
        # y salía como un 500 del CRM —«Error interno, facilita el identificador
        # al soporte»— que es exactamente lo contrario de lo que pasa: el CRM
        # está bien y quien ha fallado es el gestor. Mandaba a mirar los registros
        # de contecrm, donde no hay nada.
        raise NoDisponible(
            f"El gestor documental ha fallado ({respuesta.status_code})"
            + (f": {_motivo(respuesta)}" if _motivo(respuesta) else ""),
            error_code="documental.gestor_fallo",
            detalle={"codigo_http": respuesta.status_code, "motivo": _motivo(respuesta)},
        )
    if respuesta.status_code >= 400:
        raise ErrorDependencia(
            f"El gestor documental ha rechazado la petición ({respuesta.status_code})"
            + (f": {_motivo(respuesta)}" if _motivo(respuesta) else ""),
            error_code="documental.peticion_rechazada",
            detalle={"codigo_http": respuesta.status_code, "motivo": _motivo(respuesta)},
        )
    if respuesta.status_code == 204 or not respuesta.content:
        return None
    return respuesta.json()


def areas(*, token_usuario: str) -> list[dict[str, Any]]:
    """Las áreas del corpus que ESTE usuario puede leer."""
    cuerpo = _llamar("GET", "/api/v1/areas", token_usuario=token_usuario)
    return list((cuerpo or {}).get("items") or [])


def _motivo(respuesta: Any) -> str:
    """Lo que el gestor dice que ha pasado, si lo dice."""
    try:
        cuerpo = respuesta.json()
        return str(cuerpo.get("detail") or cuerpo.get("message") or "")[:300]
    except Exception:  # noqa: BLE001 — si no es JSON, el texto vale igual
        return str(getattr(respuesta, "text", ""))[:300]


def _area(token_usuario: str) -> str:
    """El área donde vive el corpus del CRM, resuelta por su nombre.

    Se resuelve cada vez y no se guarda en la configuración: el identificador de
    un área es de un tenant, y el fichero de configuración es el mismo para
    todos los del despliegue.
    """
    from crmcore.config import get_settings

    nombre = (get_settings().dms_area_nombre or "").strip()
    disponibles = areas(token_usuario=token_usuario)
    if nombre:
        elegida = next(
            (a for a in disponibles if str(a.get("name", "")).strip().lower() == nombre.lower()),
            None,
        )
        if elegida is None:
            raise NoDisponible(
                f"El área «{nombre}» (DMS_AREA_NOMBRE) no está entre las que este "
                "usuario puede leer en el gestor documental",
                error_code="documental.area_no_encontrada",
                detalle={"visibles": [str(a.get("name", "")) for a in disponibles]},
            )
        return str(elegida.get("id") or "")
    if len(disponibles) == 1:
        return str(disponibles[0].get("id") or "")
    if not disponibles:
        raise NoDisponible(
            "Este usuario no ve ninguna área del corpus en el gestor documental",
            error_code="documental.sin_area",
        )
    raise NoDisponible(
        "El gestor documental tiene varias áreas y no hay ninguna elegida: pon "
        "DMS_AREA_NOMBRE con la que guarda el corpus de este CRM. Repartir los "
        "documentos en la que tocara sería peor que no guardarlos",
        error_code="documental.area_ambigua",
        detalle={"visibles": [str(a.get("name", "")) for a in disponibles]},
    )


def carpetas(*, token_usuario: str, padre_id: str | None = None) -> list[dict[str, Any]]:
    """Las carpetas que cuelgan de una, o las de la raíz del área."""
    _config()
    params: dict[str, Any] = {"area_id": _area(token_usuario)}
    if padre_id:
        params["parent_id"] = padre_id
    cuerpo = _llamar("GET", "/api/v1/folders", token_usuario=token_usuario, params=params)
    return list((cuerpo or {}).get("items") or [])


def crear_carpeta(
    nombre: str, *, token_usuario: str, padre_id: str | None = None
) -> dict[str, Any]:
    """Crea una carpeta. `padre_id` nulo la cuelga de la raíz del área."""
    _config()
    cuerpo = {"area_id": _area(token_usuario), "name": nombre, "parent_id": padre_id}
    return dict(_llamar("POST", "/api/v1/folders", token_usuario=token_usuario, cuerpo=cuerpo))


def documentos_de_carpeta(
    carpeta_id: str, *, token_usuario: str, con_subcarpetas: bool = False
) -> list[dict[str, Any]]:
    """Los documentos de una carpeta. Vacío NO es un error.

    Una rama sin documentos visibles devuelve cero, no un 404: distinguir
    «vacía» de «todo denegado» con un código distinto ya sería decirle a quien
    pregunta que ahí hay algo que no puede ver.
    """
    cuerpo = _llamar(
        "GET",
        f"/api/v1/folders/{carpeta_id}/documents",
        token_usuario=token_usuario,
        params={"con_subcarpetas": con_subcarpetas},
    )
    return list((cuerpo or {}).get("items") or [])


def mover_documento(documento_id: str, *, carpeta_id: str | None, token_usuario: str) -> None:
    """Mueve un documento a otra carpeta. `carpeta_id` nulo lo deja en la raíz."""
    _llamar(
        "POST",
        f"/api/v1/documents/{documento_id}/move",
        token_usuario=token_usuario,
        cuerpo={"folder_id": carpeta_id},
    )


# Los motivos que da contecmind al explicar un permiso. Son CÓDIGOS, no frases:
# el gestor no traduce, y una frase suya llegaría en castellano a los otros cinco
# idiomas del CRM. Se listan aquí para que el front tenga qué traducir y para que
# uno nuevo se note —si aparece un motivo que no está, se enseña el código tal
# cual en vez de una cadena vacía, que es lo que haría un diccionario mudo.
MOTIVOS_DE_PERMISO = (
    "area",
    "no_area",
    "grant_here",
    "grant_above",
    "doc_allow",
    "doc_deny",
)


def permisos_de_carpeta(carpeta_id: str, *, token_usuario: str) -> dict[str, Any]:
    """Por qué alguien puede o no puede hacer algo con una carpeta.

    **Para la ficha de una carpeta, nunca por fila de un listado.** El listado de
    documentos ya devuelve solo lo que el usuario puede leer, así que preguntar
    permisos por fila es pedir dos veces lo mismo y además convierte una pantalla
    de cincuenta filas en cincuenta llamadas de red.
    """
    cuerpo = _llamar(
        "GET",
        f"/api/v1/folders/{carpeta_id}/effective-permissions",
        token_usuario=token_usuario,
    )
    return dict((cuerpo or {}).get("permissions") or {})


def buscar_en_rama(
    texto: str,
    *,
    token_usuario: str,
    carpeta_id: str | None = None,
    con_subcarpetas: bool = True,
    limite: int = 20,
) -> list[dict[str, Any]]:
    """Busca acotado a una rama del árbol, o en todo el corpus si no se acota.

    Es la misma búsqueda de `buscar()` con el ámbito puesto. Existe aparte para
    que quien lee una pantalla vea qué está acotando: «buscar en los documentos
    de esta cuenta» y «buscar en el corpus» son dos preguntas distintas aunque
    compartan ruta.
    """
    params: dict[str, Any] = {"q": texto, "limit": limite}
    if carpeta_id:
        params["folder_id"] = carpeta_id
        params["con_subcarpetas"] = con_subcarpetas
    cuerpo = _llamar("GET", "/api/v1/documents/search", token_usuario=token_usuario, params=params)
    return list((cuerpo or {}).get("items") or [])


def analizar_rama(
    carpeta_id: str,
    *,
    token_usuario: str,
    que: str = "resumen",
    pregunta: str = "",
    con_subcarpetas: bool = True,
) -> dict[str, Any]:
    """Resume una rama o saca sus conceptos. **Solo desde un trabajo de fondo.**

    Pasa por el modelo de lenguaje, y en contecmind el de embeddings puede tardar
    minutos en cargar en frío. O sea que esto funciona en caliente y falla en
    frío, y un plazo que depende de si el modelo está cargado no es un plazo: en
    pruebas iría bien y el lunes por la mañana daría 504.

    Por eso lleva su propio plazo (`DMS_TIMEOUT_ANALISIS_S`, minutos, no
    segundos) y por eso no se llama desde una petición de usuario. Quien lo
    quiera en pantalla, que encole un trabajo y consulte su estado.
    """
    if que not in ("resumen", "conceptos"):
        from crmcore.errors import ErrorValidacion

        raise ErrorValidacion(
            "De una rama se puede pedir «resumen» o «conceptos»",
            error_code="documental.analisis_desconocido",
        )
    s = _config()
    sufijo = "summary" if que == "resumen" else "concepts"
    cuerpo = _llamar(
        "POST",
        f"/api/v1/folders/{carpeta_id}/{sufijo}",
        token_usuario=token_usuario,
        cuerpo={"pregunta": pregunta or None, "con_subcarpetas": con_subcarpetas},
        timeout=s.dms_timeout_analisis_s,
    )
    return dict(cuerpo or {})


def documentos_citados(citas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Agrupa las citas por documento, que es como se enseñan.

    Las citas de contecmind son de FRAGMENTO, no de documento: varias pueden
    salir del mismo fichero. Pintarlas tal cual da una lista con el mismo
    documento repetido cuatro veces, que parece un fallo y no lo es.

    Se ordena por `relevance` y no por `score` a propósito: `score` cambia de
    significado a lo largo del recorrido de la búsqueda —coseno, después RRF,
    después una mezcla normalizada— y el propio contecmind avisa de que el único
    comparable entre resultados es `relevance`.

    Las huérfanas (`is_orphan`) se marcan y no se esconden: una cita cuyo
    documento ya no está es información —el resumen se apoyó en algo que ha
    desaparecido— y quitarla en silencio dejaría un resumen sin justificar.
    """
    por_documento: dict[str, dict[str, Any]] = {}
    for cita in citas:
        doc = str(cita.get("document_id") or "")
        if not doc:
            continue
        relevancia = float(cita.get("relevance") or 0.0)
        actual = por_documento.get(doc)
        if actual is None:
            por_documento[doc] = {
                "documento_id": doc,
                "titulo": cita.get("document_title") or "",
                "relevancia": relevancia,
                "fragmentos": 1,
                "huerfano": bool(cita.get("is_orphan")),
            }
            continue
        actual["fragmentos"] += 1
        actual["relevancia"] = max(actual["relevancia"], relevancia)
        actual["huerfano"] = actual["huerfano"] or bool(cita.get("is_orphan"))
    return sorted(por_documento.values(), key=lambda d: -d["relevancia"])


def carpeta_de_registro(
    *,
    objeto: str,
    etiqueta: str,
    token_usuario: str,
    crear: bool = True,
) -> str | None:
    """La carpeta del corpus donde van los documentos de ESTE registro.

    Se resuelve recorriendo la plantilla configurada (`DMS_CARPETA_PLANTILLA`)
    tramo a tramo, creando lo que falte. Y se resuelve **una vez**: el
    identificador se guarda en el enlace, así que si luego alguien mueve o
    renombra la carpeta en contecmind el CRM sigue apuntando a la misma y no
    crea otra al lado con el nombre nuevo.

    Devuelve `None` si algún tramo no existe y no se pide crearlo: un despliegue
    que solo enlaza documentos sueltos es válido y no tiene por qué fallar aquí.
    """
    s = _config()
    tramos = [
        t.strip()
        for t in s.dms_carpeta_plantilla.format(objeto=objeto, registro=etiqueta).split("/")
        if t.strip()
    ]
    padre: str | None = None
    for tramo in tramos:
        hijas = carpetas(token_usuario=token_usuario, padre_id=padre)
        # Se compara sin distinguir mayúsculas: dos carpetas que solo se
        # diferencian en eso son la misma para quien las mira, y crear la
        # segunda deja los documentos repartidos entre las dos.
        encontrada = next(
            (c for c in hijas if str(c.get("name", "")).strip().lower() == tramo.lower()),
            None,
        )
        if encontrada is None:
            if not crear:
                return None
            encontrada = crear_carpeta(tramo, token_usuario=token_usuario, padre_id=padre)
        padre = str(encontrada.get("id") or "")
        if not padre:
            return None
    return padre
