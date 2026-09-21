"""Cachear respuestas y tirarlas cuando dejan de valer (CRM-00.02.04.05).

Cachear es fácil; invalidar es el problema. Una caché con caducidad por tiempo
sirve una respuesta vieja durante todo el plazo que le quede, y el usuario que
acaba de cambiar algo ve su propio cambio desaparecer — la queja más difícil de
reproducir que existe, porque a los cinco minutos ya no pasa.

Aquí la invalidación es **por evento** y se apoya en el mecanismo de
generaciones que ya tiene la caché (`crmcore.cache.base`): cada respuesta lleva
en su clave la generación del evento que la invalida, y cuando ese evento pasa
se sube la generación. Todas las claves viejas dejan de encontrarse **de golpe**,
sin recorrer nada y con cualquier backend.

Es la diferencia con llevar un índice de claves: un índice hay que mantenerlo,
puede quedarse desincronizado, y recorrerlo en la ruta caliente de un evento es
justo lo que no se puede hacer. Subir un contador es una escritura.

La caducidad se queda como **red de seguridad** de lo que nadie invalidó, no
como mecanismo principal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from crmcore.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Politica:
    """Qué se cachea, cuánto y qué lo tira.

    `invalida_con` son tipos de evento. Se declaran **al definir la caché** y no
    al emitir el evento, que es lo que permite comprobar que toda caché tiene
    quien la invalide.
    """

    nombre: str
    ttl_s: int
    invalida_con: tuple[str, ...] = ()
    # Si la respuesta depende de quién pregunta. Casi siempre sí: cachear sin el
    # usuario en la clave sirve a uno lo que otro puede ver — la misma fuga que
    # no separar por tenant, pero dentro de casa y por eso más difícil de ver.
    por_usuario: bool = True


def _ambito(tipo_evento: str, tenant_id: UUID) -> str:
    return f"{tenant_id}:evt:{tipo_evento}"


def clave(
    politica: Politica, *, tenant_id: UUID, usuario_id: UUID | None, partes: dict[str, Any]
) -> str:
    """La clave de caché, con la generación de cada evento invalidante dentro.

    Meter la generación en la clave es lo que hace que subirla invalide sin
    tocar ninguna entrada: las viejas siguen ahí hasta que caduquen, pero ya no
    las encuentra nadie.
    """
    from crmcore.cache import clave_de, get_cache

    generaciones = "-".join(
        str(get_cache().generacion(_ambito(e, tenant_id))) for e in politica.invalida_con
    )
    trozos = [politica.nombre, generaciones or "sin-eventos"]
    if politica.por_usuario:
        trozos.append(str(usuario_id))
    trozos.extend(f"{k}={partes[k]}" for k in sorted(partes))
    return clave_de("respuesta", *trozos, tenant_id=tenant_id)


def invalidar_por_evento(tipo_evento: str, tenant_id: UUID) -> int:
    """Sube la generación de este evento. Todo lo que dependía deja de valer.

    Devuelve la generación nueva, no el número de entradas: **no se sabe** cuántas
    había, y devolver un cero haría creer que no se invalidó nada. Decir la
    generación es lo que de verdad ha pasado.
    """
    from crmcore.cache import get_cache

    nueva = get_cache().incrementar_generacion(_ambito(tipo_evento, tenant_id))
    logger.info("cache.invalidada_por_evento", evento=tipo_evento, generacion=nueva)
    return nueva


def politicas_sin_invalidacion(politicas: list[Politica]) -> list[str]:
    """Las que solo caducan por tiempo.

    No es un error y por eso no lanza: hay respuestas que nadie invalida porque
    nada las cambia. Pero tiene que **verse**, porque una caché que se creyó
    invalidada por evento y solo caduca es la que sirve datos viejos sin que
    nadie entienda por qué.
    """
    return sorted(p.nombre for p in politicas if not p.invalida_con)


async def consumir_invalidacion(mensaje: Any) -> None:
    """Sube la generación al recibir cualquier evento del bus.

    Universal y no por política: un consumidor por caché serían N consumidores
    durables compitiendo por el mismo flujo, y el coste de subir una generación
    de un evento que nadie cachea es una escritura que no molesta a nadie.
    """
    if isinstance(mensaje, dict):
        tipo = str(mensaje.get("tipo") or mensaje.get("type") or "")
        datos = mensaje.get("data") if isinstance(mensaje.get("data"), dict) else mensaje
        bruto = (datos or {}).get("tenant_id") or mensaje.get("tenant_id")
    else:
        tipo = str(getattr(mensaje, "tipo", "") or "")
        bruto = getattr(mensaje, "tenant_id", None)
    if not tipo or not bruto:
        return
    try:
        invalidar_por_evento(tipo, UUID(str(bruto)))
    except (TypeError, ValueError):
        logger.warning("cache.evento_sin_tenant_legible", evento=tipo)
