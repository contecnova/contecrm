"""Concurrencia optimista con ETag e `If-Match` (CRM-00.02.01.09).

Sin esto, dos usuarios que abren la misma oportunidad y guardan con un minuto de
diferencia producen el clásico «actualización perdida»: el segundo pisa el
cambio del primero y nadie se entera. Es el fallo que más veces acaba en «el
sistema ha borrado lo que escribí».

El ETag es el contador `version` de la fila, que SQLAlchemy incrementa en cada
escritura. El cliente lee (`ETag: "7"`), escribe con `If-Match: "7"`, y si otro
escribió entretanto la fila ya va por 8: se responde 412 y el cliente relee.

`If-Match` **no se exige por defecto**, y es una decisión consciente: exigirlo
rompería a todo integrador que no lo mande y convertiría la protección en una
barrera de entrada. Se puede exigir por recurso donde la escritura concurrente
sea probable y cara (importe de una oportunidad, estado de un caso).
"""

from __future__ import annotations

from typing import Any

from crmcore.errors import ConflictoDeVersion, ErrorValidacion


def etag_de(objeto: Any) -> str:
    """ETag de una entidad con `version`. Débil (`W/`) a propósito.

    Débil porque identifica la versión lógica del recurso, no el byte exacto de
    la representación: dos peticiones con distinta proyección de campos son la
    misma versión del registro.
    """
    version = getattr(objeto, "version", None)
    if version is None:
        raise ErrorValidacion(
            "El recurso no admite control de versión",
            error_code="etag.sin_version",
        )
    return f'W/"{version}"'


def _normalizar(valor: str) -> str:
    return valor.strip().removeprefix("W/").strip('"')


def comprobar_if_match(objeto: Any, if_match: str | None, *, obligatorio: bool = False) -> None:
    """Valida `If-Match` contra la versión actual. Lanza 409 si no coincide.

    `*` significa «solo si existe», que es lo que quiere quien actualiza algo
    que acaba de leer sin haberse quedado la versión.
    """
    if not if_match:
        if obligatorio:
            raise ErrorValidacion(
                "Esta operación exige la cabecera If-Match con el ETag leído",
                error_code="etag.if_match_requerido",
            )
        return

    if if_match.strip() == "*":
        return

    actual = str(getattr(objeto, "version", ""))
    # Un `If-Match` puede traer varias versiones separadas por comas: vale con
    # que una coincida.
    esperadas = {_normalizar(v) for v in if_match.split(",")}
    if actual not in esperadas:
        raise ConflictoDeVersion(
            "El registro ha cambiado desde que lo leíste. Vuelve a leerlo, "
            "reconcilia los cambios y repite la operación.",
            error_code="etag.version_desfasada",
            detalle={"version_actual": actual, "version_enviada": sorted(esperadas)},
        )


def comprobar_if_none_match(objeto: Any, if_none_match: str | None) -> bool:
    """`True` si el cliente ya tiene la versión buena y toca responder 304.

    Ahorra el cuerpo entero en las lecturas repetidas, que en una vista 360 con
    cincuenta campos y relaciones no es poca cosa.
    """
    if not if_none_match:
        return False
    if if_none_match.strip() == "*":
        return True
    actual = str(getattr(objeto, "version", ""))
    return actual in {_normalizar(v) for v in if_none_match.split(",")}


class ETagMiddleware:
    """Cabeceras que se derivan de la respuesta ya generada.

    Dos, y las dos por el mismo motivo: se calculan **después** de tener el
    cuerpo, así que no pueden ponerse en el endpoint sin repetirlo en cien
    sitios.

      * `ETag`, cuando la respuesta lleva versión (CRM-00.02.01.09).
      * `X-Campos-Retenidos`, cuando la proyección ocultó campos
        (CRM-00.05.02.03) — sin ese anuncio, el cliente no distingue «vacío» de
        «no te lo doy», y esa diferencia cambia lo que hace con el campo.

    La mitad automática del control de concurrencia. Se hace aquí porque **la
    cabecera es mecánica**: si la respuesta JSON trae un campo `version`, el
    ETag sale de ahí y no hay decisión que tomar. Dejarlo en cada endpoint
    significaría tenerlo en los que alguien recordó, y un cliente no puede usar
    `If-Match` en un recurso que unas veces devuelve `ETag` y otras no.

    La otra mitad —comprobar el `If-Match` que llega— **no** puede vivir aquí:
    hace falta el objeto cargado para saber su versión actual, y eso solo lo
    sabe el endpoint. Esa parte se llama con `comprobar_if_match`, y hay un gate
    (`test_contratos_arquitectura.py`) que falla si una ruta de actualización
    sobre un recurso versionado no la usa.
    """

    METODOS = frozenset({"GET", "POST", "PUT", "PATCH"})

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http" or scope.get("method", "") not in self.METODOS:
            await self.app(scope, receive, send)
            return

        estado: dict[str, Any] = {"inicio": None, "cuerpo": b"", "json": False}

        async def _interceptar(mensaje: dict[str, Any]) -> None:
            if mensaje["type"] == "http.response.start":
                # Se retiene el inicio para poder añadirle la cabecera cuando se
                # conozca el cuerpo. Mandarlo antes haría imposible añadir nada.
                estado["inicio"] = mensaje
                cabeceras = dict(mensaje.get("headers") or [])
                tipo = cabeceras.get(b"content-type", b"")
                estado["json"] = b"application/json" in tipo
                return

            if mensaje["type"] == "http.response.body":
                estado["cuerpo"] += mensaje.get("body", b"")
                if mensaje.get("more_body", False):
                    return
                inicio = estado["inicio"]
                if inicio is not None:
                    version = _version_del_cuerpo(estado["cuerpo"]) if estado["json"] else None
                    cabeceras = list(inicio.get("headers", []))
                    if version is not None:
                        cabeceras.append((b"etag", f'W/"{version}"'.encode()))
                    from crmcore.authz.proyeccion import limpiar_retenidos, retenidos

                    ocultos = retenidos()
                    if ocultos:
                        cabeceras.append((b"x-campos-retenidos", ",".join(ocultos).encode()))
                    # Se limpia SIEMPRE, no solo cuando hay algo: el contextvar
                    # sobrevive a la petición en el hilo del servidor, y sin
                    # limpiarlo la respuesta siguiente anunciaría campos que no
                    # ha retenido.
                    limpiar_retenidos()
                    inicio["headers"] = cabeceras
                    await send(inicio)
                    estado["inicio"] = None
                await send({"type": "http.response.body", "body": estado["cuerpo"]})
                return

            await send(mensaje)

        await self.app(scope, receive, _interceptar)


def _version_del_cuerpo(cuerpo: bytes) -> int | None:
    """Saca `version` de una respuesta JSON, si la trae.

    Solo del nivel superior: un ETag sacado de la versión de un objeto anidado
    identificaría a otro recurso, y el cliente lo usaría para actualizar el que
    no es. Y solo de un objeto, no de una lista: una lista no tiene una versión.
    """
    import json

    if not cuerpo or len(cuerpo) > 2_000_000:
        # Un cuerpo enorme no se parsea para sacar un entero: el coste de
        # deserializar varios megas en cada respuesta supera con mucho lo que
        # aporta la cabecera.
        return None
    try:
        datos = json.loads(cuerpo)
    except ValueError:
        return None
    if isinstance(datos, dict):
        version = datos.get("version")
        if isinstance(version, int):
            return version
    return None
