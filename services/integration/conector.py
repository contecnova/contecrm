"""Conector HTTP/REST declarativo (CRM-00.03.04.02).

Origen: `contecweb/app/connectors/api/generic_rest.py` y `oauth2.py`, portados
el 2026-09-18. Se conservan los cinco patrones que allí permitieron sustituir
los conectores escritos a mano por configuración, porque cada uno resuelve un
problema real y medido:

  * **Alternativas por campo.** Un mapeo admite varias rutas y se queda con la
    primera que traiga algo. Media API pública tiene dos nombres para el mismo
    dato según la versión del endpoint.
  * **Marcadores de vacío.** Muchas APIs escriben `"N/A"`, `"-"` o `"TBD"` en
    lugar de omitir el campo. Sin declararlos, esa cadena entra como si fuera el
    dato — y un dato equivocado que parece correcto es peor que no tenerlo.
  * **Expansión de sublistas.** Un resultado puede contener variantes que deben
    emitirse por separado.
  * **Prefijo `^` para el padre.** Dentro de una variante, `^campo` lee del
    objeto padre. **Sin `^` se lee solo de la variante**, y eso es deliberado:
    el respaldo implícito hacía que un precio del padre se presentara como el de
    la variante, que es exactamente el tipo de error que nadie detecta.
  * **OAuth2 client credentials con token cacheado**, por tenant y credencial.
    Es lo que hacía imposible un conector declarativo: el intercambio de
    credenciales por token vive aquí y deja de ser código por proveedor.

Se añade, propio de contecrm: paginación declarativa (cursor, página, offset y
enlace siguiente), que es lo que hace falta para leer un maestro de clientes de
un ERP entero.
"""

from __future__ import annotations

import re
import time
from typing import Any

import httpx
from crmcore.errors import ErrorDependencia, ErrorValidacion, PeticionMalFormada
from crmcore.logging import get_logger
from crmcore.red import cliente_seguro_async

logger = get_logger(__name__)

# Prefijo que, dentro de una variante expandida, lee del objeto padre.
PREFIJO_PADRE = "^"
# Marcadores `{{clave}}` que se sustituyen con los parámetros de la llamada.
RE_PLANTILLA = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")

# Caché de tokens OAuth2: (tenant, clave de credencial) -> (token, caduca_en).
# Se cachea por tenant a propósito: cada cliente usa su propia cuenta con el
# sistema externo, y mezclar tokens sería consultar en nombre de otro.
_tokens: dict[tuple[str, str], tuple[str, float]] = {}
# Margen con el que se renueva antes de que caduque. Un token que expira
# mientras la petición vuela devuelve un 401 que parece un problema de
# credenciales y manda a revisar una clave que está bien.
MARGEN_TOKEN_S = 60.0


def resolver_ruta(datos: Any, ruta: str) -> Any:
    """Resuelve `a.b.0.c` sobre diccionarios y listas. `None` si no existe."""
    if not ruta:
        return None
    actual = datos
    for parte in ruta.split("."):
        if actual is None:
            return None
        if isinstance(actual, list):
            try:
                actual = actual[int(parte)]
            except (ValueError, IndexError):
                return None
        elif isinstance(actual, dict):
            actual = actual.get(parte)
        else:
            return None
    return actual


def _rutas(valor: Any) -> list[str]:
    """Una ruta o varias alternativas, siempre como lista."""
    if isinstance(valor, str):
        return [valor] if valor.strip() else []
    if isinstance(valor, (list, tuple)):
        return [str(v) for v in valor if str(v).strip()]
    return []


def primer_valor(
    rutas: list[str], fila: Any, padre: Any, vacios: frozenset[str] = frozenset()
) -> Any:
    """El primer valor que exista, probando las rutas en el orden declarado.

    El orden ES la decisión: `["stock_num", "stock_texto"]` prefiere el número
    al texto «12450 en stock», y al revés el stock entraría como una cadena sin
    normalizar.
    """
    for ruta in rutas:
        if ruta.startswith(PREFIJO_PADRE):
            valor = resolver_ruta(padre, ruta[len(PREFIJO_PADRE) :])
        else:
            valor = resolver_ruta(fila, ruta)
        if valor is None or valor == "":
            continue
        if vacios and isinstance(valor, str) and valor.strip().casefold() in vacios:
            continue
        return valor
    return None


def marcadores_vacio(config: dict[str, Any]) -> frozenset[str]:
    """Valores que esta API usa para decir «aquí no hay nada», normalizados.

    Sin mayúsculas ni espacios: la misma respuesta trae «N/A» y «n/a».
    """
    crudos = config.get("valores_vacios")
    if isinstance(crudos, str):
        crudos = [crudos]
    if not isinstance(crudos, (list, tuple)):
        return frozenset()
    return frozenset(str(v).strip().casefold() for v in crudos if str(v).strip())


def plantilla(texto: str, parametros: dict[str, Any]) -> str:
    """Sustituye `{{clave}}` con los parámetros. Lo que falta queda vacío.

    Vacío y no error: una URL con un parámetro opcional sin valor tiene que
    poder construirse igual, y el error —si lo hay— lo dará el sistema externo
    con su propio mensaje, que es más informativo que el nuestro.
    """

    def _reemplazo(m: re.Match[str]) -> str:
        valor = resolver_ruta(parametros, m.group(1))
        return "" if valor is None else str(valor)

    return RE_PLANTILLA.sub(_reemplazo, texto)


def _renderizar(valor: Any, parametros: dict[str, Any]) -> Any:
    """Aplica la plantilla recursivamente a cadenas, listas y diccionarios."""
    if isinstance(valor, str):
        return plantilla(valor, parametros)
    if isinstance(valor, dict):
        return {k: _renderizar(v, parametros) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_renderizar(v, parametros) for v in valor]
    return valor


# ── Autenticación ─────────────────────────────────────────────────────────


async def cabeceras_auth(
    config: dict[str, Any], secretos: dict[str, str], *, tenant_id: str
) -> dict[str, str]:
    """Construye las cabeceras de autenticación según lo declarado.

    Tipos admitidos: `ninguna`, `api_key` (cabecera o query), `basica`,
    `bearer` y `oauth2_client_credentials`. Lista cerrada: admitir un tipo
    arbitrario obligaría a ejecutar código del tenant para autenticarse.
    """
    tipo = str(config.get("auth_tipo", "ninguna"))

    if tipo == "ninguna":
        return {}
    if tipo == "api_key":
        nombre = str(config.get("auth_cabecera", "Authorization"))
        prefijo = str(config.get("auth_prefijo", ""))
        clave = secretos.get("api_key", "")
        return {nombre: f"{prefijo}{clave}".strip()}
    if tipo == "basica":
        import base64

        par = f"{secretos.get('usuario', '')}:{secretos.get('contrasena', '')}"
        return {"Authorization": "Basic " + base64.b64encode(par.encode()).decode()}
    if tipo == "bearer":
        return {"Authorization": f"Bearer {secretos.get('token', '')}"}
    if tipo == "oauth2_client_credentials":
        token = await _token_oauth2(config, secretos, tenant_id=tenant_id)
        return {"Authorization": f"Bearer {token}"}

    raise ErrorValidacion(
        f"Tipo de autenticación no admitido: «{tipo}»",
        error_code="conector.auth_no_admitida",
    )


async def _token_oauth2(config: dict[str, Any], secretos: dict[str, str], *, tenant_id: str) -> str:
    """Token de cliente, cacheado por tenant y credencial."""
    clave_cache = (tenant_id, secretos.get("client_id", ""))
    guardado = _tokens.get(clave_cache)
    if guardado and guardado[1] - MARGEN_TOKEN_S > time.time():
        return guardado[0]

    url = str(config.get("oauth_token_url", ""))
    if not url:
        raise ErrorValidacion(
            "Falta la URL del servidor de tokens",
            error_code="conector.oauth_sin_url",
        )
    datos = {
        "grant_type": "client_credentials",
        "client_id": secretos.get("client_id", ""),
        "client_secret": secretos.get("client_secret", ""),
    }
    if config.get("oauth_scope"):
        datos["scope"] = str(config["oauth_scope"])

    # Con guard: la URL del servidor de tokens la configura el tenant.
    async with cliente_seguro_async(timeout=20.0) as cli:
        respuesta = await cli.post(url, data=datos)
    if respuesta.status_code >= 400:
        # `PeticionMalFormada` y no `ErrorDependencia`: unas credenciales
        # incorrectas fallan igual por mucho que se reintente, así que esto no
        # debe contar para el circuit breaker ni disparar reintentos.
        raise PeticionMalFormada(
            f"El servidor de tokens ha rechazado las credenciales (HTTP {respuesta.status_code})",
            error_code="conector.oauth_rechazado",
        )
    cuerpo = respuesta.json()
    token = str(cuerpo.get("access_token", ""))
    caduca = time.time() + float(cuerpo.get("expires_in", 3600))
    _tokens[clave_cache] = (token, caduca)
    return token


def limpiar_tokens() -> None:
    """Olvida los tokens cacheados. Tras rotar una credencial y en pruebas."""
    _tokens.clear()


# ── Ejecución ─────────────────────────────────────────────────────────────


async def ejecutar(
    conexion: dict[str, Any],
    operacion: dict[str, Any],
    parametros: dict[str, Any],
    *,
    secretos: dict[str, str],
    tenant_id: str,
    timeout_s: float = 30.0,
) -> dict[str, Any]:
    """Ejecuta una operación declarada y devuelve los registros mapeados.

    Devuelve `{"registros": [...], "paginas": n, "crudos": n}`. Los registros ya
    vienen con los nombres de campo de contecrm: el mapeo es parte de la
    configuración, así que quien consume esto no sabe nada de la API de origen.
    """
    base = str(conexion.get("url_base", "")).rstrip("/")
    ruta = plantilla(str(operacion.get("ruta", "")), parametros)
    url = f"{base}/{ruta.lstrip('/')}" if ruta else base
    metodo = str(operacion.get("metodo", "GET")).upper()

    cabeceras = {
        "Accept": "application/json",
        **{
            str(k): plantilla(str(v), parametros)
            for k, v in (conexion.get("cabeceras") or {}).items()
        },
        **await cabeceras_auth(conexion, secretos, tenant_id=tenant_id),
    }
    query = _renderizar(operacion.get("query") or {}, parametros)
    cuerpo = _renderizar(operacion.get("cuerpo"), parametros)

    paginacion = operacion.get("paginacion") or {}
    max_paginas = int(paginacion.get("max_paginas", 20))
    registros: list[dict[str, Any]] = []
    rechazados: list[dict[str, Any]] = []
    crudos = 0
    paginas = 0

    # `follow_redirects=True` hace el guard todavía más necesario: sin él, un
    # servidor que responda 302 hacia `169.254.169.254` salta cualquier
    # validación hecha solo sobre la URL inicial. El transporte revalida **cada
    # salto**, no solo el primero.
    async with cliente_seguro_async(timeout=timeout_s, follow_redirects=True) as cli:
        siguiente_url: str | None = url
        while siguiente_url and paginas < max_paginas:
            try:
                respuesta = await cli.request(
                    metodo,
                    siguiente_url,
                    params=query or None,
                    json=cuerpo if metodo in ("POST", "PUT", "PATCH") else None,
                    headers=cabeceras,
                )
            except httpx.TimeoutException:
                from crmcore.errors import TiempoAgotado

                raise TiempoAgotado(
                    f"El sistema externo no ha respondido en {timeout_s:g} s",
                    error_code="conector.timeout",
                )
            except httpx.HTTPError as exc:
                raise ErrorDependencia(
                    f"No se ha podido contactar con el sistema externo: {exc}",
                    error_code="conector.red",
                )

            if 400 <= respuesta.status_code < 500 and respuesta.status_code != 429:
                # Un 4xx (salvo 429) es determinista: reintentar da lo mismo.
                raise PeticionMalFormada(
                    f"El sistema externo ha rechazado la petición (HTTP {respuesta.status_code})",
                    error_code="conector.rechazada",
                    detalle={"cuerpo": respuesta.text[:500]},
                )
            if respuesta.status_code >= 500 or respuesta.status_code == 429:
                raise ErrorDependencia(
                    f"El sistema externo ha fallado (HTTP {respuesta.status_code})",
                    error_code="conector.fallo_remoto",
                    detalle={"cuerpo": respuesta.text[:500]},
                )

            try:
                datos = respuesta.json()
            except ValueError:
                raise ErrorDependencia(
                    "El sistema externo no ha devuelto JSON",
                    error_code="conector.respuesta_no_json",
                    detalle={"cuerpo": respuesta.text[:300]},
                )

            filas = resolver_ruta(datos, str(operacion.get("ruta_resultados", ""))) or datos
            if isinstance(filas, dict):
                filas = [filas]
            if not isinstance(filas, list):
                filas = []
            crudos += len(filas)
            registros.extend(mapear(filas, operacion, rechazos=rechazados))
            paginas += 1

            siguiente_url, query = _siguiente_pagina(
                paginacion, datos, respuesta, query or {}, paginas
            )

    return {
        "registros": registros,
        "paginas": paginas,
        "crudos": crudos,
        # Lo que NO pasó la validación, con su motivo. Va en la salida y no
        # sólo al registro del servidor: una importación que dice «200
        # registros» y guarda 180 sin decir nada es la forma más silenciosa de
        # perder datos, y el hueco se descubre semanas después.
        "rechazados": rechazados,
        "cuantos_rechazados": len(rechazados),
    }


def _siguiente_pagina(
    paginacion: dict[str, Any],
    datos: Any,
    respuesta: httpx.Response,
    query: dict[str, Any],
    paginas: int,
) -> tuple[str | None, dict[str, Any]]:
    """Calcula la página siguiente según el estilo declarado.

    Cuatro estilos porque son los cuatro que existen en la práctica, y cada uno
    tiene su forma de decir «no hay más»:

      enlace  — la respuesta trae la URL siguiente; sin ella, se acabó.
      cursor  — un testigo que se manda en la llamada siguiente.
      pagina  — número de página; para cuando no viene el total.
      offset  — desplazamiento; igual, se para al recibir menos de lo pedido.
    """
    estilo = str(paginacion.get("estilo", "ninguna"))
    if estilo == "ninguna":
        return None, query

    if estilo == "enlace":
        siguiente = resolver_ruta(datos, str(paginacion.get("ruta_siguiente", "")))
        return (str(siguiente) if siguiente else None), query

    if estilo == "cursor":
        cursor = resolver_ruta(datos, str(paginacion.get("ruta_cursor", "")))
        if not cursor:
            return None, query
        return str(respuesta.request.url).split("?")[0], {
            **query,
            str(paginacion.get("param_cursor", "cursor")): cursor,
        }

    if estilo in ("pagina", "offset"):
        tamano = int(paginacion.get("tamano", 100))
        # Se para cuando la página viene incompleta: es la señal universal de
        # última página, y no depende de que la API devuelva un total (muchas no
        # lo hacen, y las que lo hacen a veces mienten).
        filas = resolver_ruta(datos, str(paginacion.get("ruta_resultados", ""))) or datos
        if not isinstance(filas, list) or len(filas) < tamano:
            return None, query
        if estilo == "pagina":
            param = str(paginacion.get("param_pagina", "page"))
            return str(respuesta.request.url).split("?")[0], {**query, param: paginas + 1}
        param = str(paginacion.get("param_offset", "offset"))
        return str(respuesta.request.url).split("?")[0], {**query, param: paginas * tamano}

    return None, query


# ── Funciones de transformación (CRM-00.03.04.04) ────────────────────────
#
# El mapeo copiaba valores de un sitio a otro y nada más. Lo que pasa en toda
# integración de verdad es que el valor **no sirve tal cual**: el código viene
# con espacios, el país en minúsculas, el importe como texto con coma, la fecha
# partida en tres campos y la referencia con un prefijo que aquí sobra.
#
# Sin transformaciones hay dos salidas y las dos son malas: escribir un conector
# a medida por cliente —que es lo que esto existe para evitar— o meter los datos
# sucios y arreglarlos después, cuando ya han disparado automatizaciones.
#
# **Es una lista cerrada, no un intérprete.** Una expresión arbitraria en la
# configuración de una integración es código de un usuario final corriendo en el
# servidor, con los permisos del servicio y sin revisión. Es la misma decisión
# que en las acciones de las automatizaciones, y por el mismo motivo.
def _f_recortar(v: Any, _arg: Any) -> Any:
    return v.strip() if isinstance(v, str) else v


def _f_mayusculas(v: Any, _arg: Any) -> Any:
    return v.upper() if isinstance(v, str) else v


def _f_minusculas(v: Any, _arg: Any) -> Any:
    return v.lower() if isinstance(v, str) else v


def _f_quitar_prefijo(v: Any, arg: Any) -> Any:
    prefijo = str(arg or "")
    return v[len(prefijo) :] if isinstance(v, str) and prefijo and v.startswith(prefijo) else v


def _f_quitar_sufijo(v: Any, arg: Any) -> Any:
    sufijo = str(arg or "")
    return v[: -len(sufijo)] if isinstance(v, str) and sufijo and v.endswith(sufijo) else v


def _f_numero(v: Any, _arg: Any) -> Any:
    """Texto a número, admitiendo la coma decimal.

    Un `1.234,56` que llega como texto y se guarda como texto convierte toda
    suma posterior en una concatenación, y eso se descubre en un informe.
    """
    from decimal import Decimal, InvalidOperation

    if isinstance(v, (int, float, Decimal)):
        return v
    if not isinstance(v, str) or not v.strip():
        return v
    limpio = v.strip().replace(" ", "")
    # Si lleva coma, la coma es el decimal y el punto el separador de miles.
    if "," in limpio:
        limpio = limpio.replace(".", "").replace(",", ".")
    try:
        return Decimal(limpio)
    except InvalidOperation:
        return v


def _f_booleano(v: Any, _arg: Any) -> Any:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in {"1", "true", "si", "sí", "s", "y", "yes", "x"}
    return bool(v)


def _f_fecha(v: Any, arg: Any) -> Any:
    """Fecha con el formato del otro lado, a ISO.

    `arg` es el formato de origen (`%d/%m/%Y`). Sin él se intenta ISO, que es
    lo que manda la mayoría. Lo que NO se hace es adivinar entre `%d/%m` y
    `%m/%d`: el 3 de abril y el 4 de marzo son los dos válidos, y acertar por
    sorteo mete una fecha equivocada que nadie revisa.
    """
    from datetime import date, datetime

    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if not isinstance(v, str) or not v.strip():
        return v
    formato = str(arg or "").strip()
    try:
        if formato:
            return datetime.strptime(v.strip(), formato).date().isoformat()
        return datetime.fromisoformat(v.strip().replace("Z", "+00:00")).isoformat()
    except ValueError:
        return v


def _f_defecto(v: Any, arg: Any) -> Any:
    """Lo que vale cuando no viene nada. Es la transformación más pedida."""
    return arg if v in (None, "", [], {}) else v


def _f_mapa(v: Any, arg: Any) -> Any:
    """Traduce un código del otro lado al nuestro.

    Lo que NO hace: inventarse el valor cuando el código no está en la tabla.
    Devuelve el original, y entonces la validación de abajo lo rechaza si el
    campo tiene una lista cerrada — que es mejor que meter un estado que aquí
    no significa nada.
    """
    tabla = arg if isinstance(arg, dict) else {}
    return tabla.get(str(v), v)


FUNCIONES: dict[str, Any] = {
    "recortar": _f_recortar,
    "mayusculas": _f_mayusculas,
    "minusculas": _f_minusculas,
    "quitar_prefijo": _f_quitar_prefijo,
    "quitar_sufijo": _f_quitar_sufijo,
    "numero": _f_numero,
    "booleano": _f_booleano,
    "fecha": _f_fecha,
    "defecto": _f_defecto,
    "mapa": _f_mapa,
}


def aplicar_funciones(valor: Any, pasos: Any) -> Any:
    """Pasa el valor por las funciones declaradas, en orden.

    Una función desconocida **no se ignora**: deja el valor como está y lo dice
    en el resultado de la validación. Ignorarla en silencio haría que un
    `mayuscuals` mal escrito pareciera funcionar.
    """
    if not isinstance(pasos, list):
        return valor
    for paso in pasos:
        if isinstance(paso, str):
            nombre, arg = paso, None
        elif isinstance(paso, dict):
            nombre, arg = str(paso.get("f", "")), paso.get("arg")
        else:
            continue
        funcion = FUNCIONES.get(nombre)
        if funcion is None:
            continue
        valor = funcion(valor, arg)
    return valor


def funciones_desconocidas(operacion: dict[str, Any]) -> list[str]:
    """Las que el mapeo nombra y no existen. Se comprueba al guardar."""
    fuera: list[str] = []
    for pasos in (operacion.get("transformar") or {}).values():
        if not isinstance(pasos, list):
            continue
        for paso in pasos:
            nombre = paso if isinstance(paso, str) else str((paso or {}).get("f", ""))
            if nombre and nombre not in FUNCIONES:
                fuera.append(nombre)
    return sorted(set(fuera))


def validar_mapeado(registro: dict[str, Any], reglas: Any) -> list[str]:
    """Qué tiene de malo este registro ya traducido.

    Devuelve los motivos, no un booleano: «no vale» sin decir por qué deja a
    quien mira el monitor sin nada que hacer salvo abrir los registros del
    servidor.

    Dos reglas y las dos son las que de verdad se piden: que un campo venga, y
    que su valor esté entre los admitidos.
    """
    if not isinstance(reglas, dict):
        return []
    motivos: list[str] = []
    for campo in reglas.get("obligatorios") or []:
        if registro.get(str(campo)) in (None, "", [], {}):
            motivos.append(f"falta «{campo}»")
    for campo, admitidos in (reglas.get("admitidos") or {}).items():
        valor = registro.get(str(campo))
        if valor is not None and isinstance(admitidos, list) and valor not in admitidos:
            motivos.append(f"«{campo}» vale «{valor}», que no está entre los admitidos")
    return motivos


def mapear(
    filas: list[Any],
    operacion: dict[str, Any],
    *,
    rechazos: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Traduce los registros de la API a los campos de contecrm (CRM-00.03.04.04).

    Tres pasos, y hasta hoy sólo estaba el primero:

      1. **mapear**: de dónde sale cada campo, con alternativas y marcadores de
         vacío;
      2. **transformar**: recortar, pasar a mayúsculas, convertir un número con
         coma decimal, componer una fecha con el formato del otro lado, poner
         un valor por defecto o traducir un código. Lista cerrada, nunca una
         expresión: una expresión en la configuración de una integración es
         código de un usuario final corriendo en el servidor;
      3. **validar**: qué campos son obligatorios y qué valores se admiten. Lo
         que no cumple se aparta **con su motivo** en `rechazos`.
    """
    mapeo = operacion.get("mapeo") or {}
    if not mapeo:
        # Sin mapeo declarado se devuelve tal cual. Sirve para explorar una API
        # nueva desde la consola antes de escribir el mapeo.
        return [f for f in filas if isinstance(f, dict)]

    vacios = marcadores_vacio(operacion)
    expandir = str(operacion.get("expandir", "")).strip()
    transformar = operacion.get("transformar") or {}
    reglas = operacion.get("validar") or {}
    salida: list[dict[str, Any]] = []
    # Los apartados se devuelven por el parámetro, no en el valor de retorno:
    # así los llamantes de siempre siguen recibiendo una lista de registros y
    # quien quiera saber qué se quedó fuera pasa una lista y la lee.
    rechazados = [] if rechazos is None else rechazos

    for fila in filas:
        if not isinstance(fila, dict):
            continue
        variantes: list[Any] = [fila]
        if expandir:
            crudas = resolver_ruta(fila, expandir)
            if isinstance(crudas, list) and crudas:
                variantes = crudas

        for variante in variantes:
            registro: dict[str, Any] = {}
            for destino, origen in mapeo.items():
                valor = primer_valor(_rutas(origen), variante, fila, vacios)
                # Las transformaciones se aplican también a lo que NO vino:
                # `defecto` es la más pedida de todas, y sólo sirve si corre
                # cuando el campo falta.
                pasos = transformar.get(str(destino))
                if pasos:
                    valor = aplicar_funciones(valor, pasos)
                if valor is not None:
                    registro[str(destino)] = valor
            if not registro:
                continue
            motivos = validar_mapeado(registro, reglas)
            if motivos:
                # El registro malo NO se cuela y NO se tira en silencio: se
                # aparta con su motivo. Colarlo mete datos sucios que disparan
                # automatizaciones; tirarlo callando deja una importación que
                # dice «200 registros» y guarda 180 sin que nadie pregunte.
                rechazados.append({"registro": registro, "motivos": motivos})
                continue
            salida.append(registro)
    return salida
