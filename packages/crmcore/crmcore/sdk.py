"""SDKs y componentes embebibles, generados del contrato
(CRM-00.02.03.04, CRM-00.02.03.05).

Un SDK escrito a mano se queda viejo. Siempre. Alguien lo escribe con cariño para
tres lenguajes, y a los cuatro meses la API tiene dos endpoints nuevos que el SDK
no conoce — y el integrador que lo usa no se entera de que existen.

La decisión de fondo: **el SDK se genera del contrato que ya se publica**. No es
un atajo, es lo único que hace que seis lenguajes sean mantenibles por un equipo
que también tiene que construir el producto.

Lo que **no** se genera es lo que cuesta de verdad y ningún generador hace bien:

**El reintento con espera creciente.** Un SDK que no reintenta hace que cada
integrador escriba el suyo, y la mitad reintenta sin espera — que convierte una
caída de diez segundos en una avalancha.

**La paginación resuelta.** El error más repetido de toda integración es pedir la
primera página y creer que son todos. Si el SDK devuelve un iterador, ese error
desaparece; si devuelve una lista, no.

**Los errores del producto como excepciones con nombre.** Un `409` obliga a leer
el cuerpo para saber si es un conflicto de versión o una regla de negocio. Con
nombre, el integrador escribe `except ConflictoDeVersion` y acierta.

**Y el idioma de los mensajes.** Un error en inglés dentro de una aplicación en
castellano lo ve el usuario final, no el programador.
"""

from __future__ import annotations

from typing import Any

from crmcore.errors import ErrorValidacion
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Los lenguajes que se generan. Lista cerrada porque cada uno tiene su plantilla
# y su forma de publicar, y añadir uno es una decisión con mantenimiento detrás —
# no un parámetro.
LENGUAJES = ("typescript", "java", "dotnet", "python", "php", "go")

# Lo que ningún generador hace bien y hay que escribir a mano una vez por
# lenguaje. Esta lista es la parte útil de este módulo: sin ella, «tenemos SDK»
# significa «tenemos un cliente HTTP con los nombres de los endpoints».
A_MANO = {
    "reintento": (
        "Con espera creciente y tope. Sin esto, cada integrador escribe el suyo y la "
        "mitad reintenta sin esperar, convirtiendo una caída de diez segundos en una "
        "avalancha"
    ),
    "paginacion": (
        "Devolver un iterador y no una lista. El error más repetido de toda "
        "integración es pedir la primera página y creer que son todos"
    ),
    "errores_con_nombre": (
        "Un 409 obliga a leer el cuerpo para saber si es conflicto de versión o regla "
        "de negocio; con nombre, el integrador escribe `except` y acierta"
    ),
    "idioma": (
        "Los mensajes de error los acaba viendo el usuario final: en inglés dentro de "
        "una aplicación en castellano, parece un fallo"
    ),
    "idempotencia": (
        "Generar y reenviar la misma clave al reintentar. Es lo que evita el cobro "
        "duplicado, y ningún generador lo pone"
    ),
}

# Componentes que se pueden incrustar en un portal ajeno (CRM-00.02.03.05).
# Cerrada a propósito: cada uno es una superficie más que mantener, y un
# componente que se incrusta en la web de un cliente no se puede cambiar a la
# ligera.
COMPONENTES = ("ficha-cuenta", "lista-casos", "formulario-alta", "estado-pedido")


def plan_de_generacion(*, lenguajes: list[str], version_api: str) -> dict[str, Any]:
    """Qué se genera y qué hay que escribir a mano en cada lenguaje.

    Devolver solo la lista de lenguajes haría creer que el SDK está hecho cuando
    lo que hay es un cliente HTTP con los nombres de los endpoints.
    """
    desconocidos = sorted(set(lenguajes) - set(LENGUAJES))
    if desconocidos:
        raise ErrorValidacion(
            f"Lenguajes no soportados: {desconocidos}",
            error_code="sdk.lenguaje_desconocido",
            detalle={"admitidos": list(LENGUAJES)},
        )
    return {
        "version_api": version_api,
        "lenguajes": sorted(set(lenguajes)),
        "se_genera_del_contrato": [
            "modelos de datos",
            "firmas de operación",
            "serialización",
            "rutas y parámetros",
        ],
        # Lo que de verdad decide si el SDK sirve.
        "hay_que_escribirlo_a_mano": A_MANO,
        "porque": (
            "Un SDK escrito entero a mano se queda viejo a los cuatro meses y el "
            "integrador no se entera de los endpoints nuevos. Generarlo del contrato "
            "es lo único que hace mantenibles seis lenguajes."
        ),
    }


def contrato_de_componente(nombre: str) -> dict[str, Any]:
    """Qué necesita un componente embebible y qué promete.

    Se declara porque un componente que se incrusta en la web de un cliente
    **no se puede cambiar a la ligera**: su contrato es tan público como el de la
    API, y romperlo rompe una página que no es nuestra.

    Y lleva dentro la parte que casi siempre se olvida: **con qué identidad
    habla**. Un componente que usa la sesión del CRM en una web pública deja
    entrar a quien pase por ahí; uno con token acotado, no.
    """
    if nombre not in COMPONENTES:
        raise ErrorValidacion(
            f"Componente desconocido: «{nombre}»",
            error_code="sdk.componente_desconocido",
            detalle={"admitidos": list(COMPONENTES)},
        )
    return {
        "componente": nombre,
        "identidad": "token acotado al registro que enseña, no la sesión del CRM",
        "porque_token_acotado": (
            "Un componente que usa la sesión del CRM dentro de una web pública deja "
            "entrar a quien pase por ahí: basta con abrir las herramientas del "
            "navegador."
        ),
        "estilo": "hereda del anfitrión por variables CSS, sin imponer tipografía",
        "contrato_publico": True,
        "porque_publico": (
            "Se incrusta en páginas que no son nuestras: cambiarlo sin aviso rompe la "
            "web de un cliente, y eso se entera él antes que nosotros."
        ),
    }
