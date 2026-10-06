"""Implementación de la caché. El porqué está en `crmcore/cache/__init__.py`."""

from __future__ import annotations

import json
import re
import time
from threading import Lock
from typing import Any, Protocol
from uuid import UUID

from crmcore.errors import ErrorValidacion
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Espacios de nombres admitidos. Lista cerrada a propósito: con el espacio de
# nombres libre, cada sitio inventa el suyo y al mes nadie sabe qué hay en la
# caché ni qué purga cada cosa. Añadir uno es una línea aquí, y esa línea es la
# documentación.
ESPACIOS = {
    "ajustes": "Valores efectivos de la jerarquía de ajustes",
    "permisos": "Permisos resueltos de un principal",
    "metadatos": "Esquema de objetos, campos y layouts",
    "listas": "Valores de listas maestras",
    "consulta": "Resultados de consultas caras de lectura",
    "conteo": "Conteos y agregados",
    "plantilla": "Plantillas renderizadas",
    "tipo_cambio": "Tipos de cambio vigentes",
    "sesion": "Datos de sesión no sensibles",
    # Respuestas cacheadas de la API, invalidadas por evento y no solo por
    # caducidad (CRM-00.02.04.05).
    "respuesta": "Respuestas de la API cacheadas con invalidación por evento",
    "prueba": "Solo para la suite de pruebas",
}

# Las partes de una clave se limpian: un valor con espacios o dos puntos podría
# colisionar con la estructura de la clave y hacer que dos entradas distintas
# compartan sitio.
RE_PARTE = re.compile(r"[^A-Za-z0-9._@-]+")


class Cache(Protocol):
    def obtener(self, clave: str) -> Any: ...
    def fijar(self, clave: str, valor: Any, *, ttl_s: int) -> None: ...
    def borrar(self, clave: str) -> None: ...
    def incrementar_generacion(self, ambito: str) -> int: ...
    def generacion(self, ambito: str) -> int: ...
    def limpiar(self) -> None: ...


def _limpia(parte: Any) -> str:
    return RE_PARTE.sub("-", str(parte))[:120] or "-"


def clave_de(
    espacio: str,
    *partes: Any,
    tenant_id: UUID | None = None,
    global_: bool = False,
) -> str:
    """Construye la clave con el tenant y su generación delante.

    `global_=True` es la única forma de escribir una entrada sin tenant, y existe
    porque hay datos que de verdad son de la plataforma: el catálogo de tipos de
    evento, la tabla de países. Es una llamada distinta y ruidosa a propósito —
    quien la escriba tiene que haber decidido que ese dato no es de nadie.

    Sin tenant y sin `global_` **falla**. No cae a una clave global «por si
    acaso»: ese es justo el fallo que este módulo existe para hacer imposible, y
    un fallo ruidoso al escribir el código es infinitamente más barato que un
    dato cruzado en producción.
    """
    if espacio not in ESPACIOS:
        raise ErrorValidacion(
            f"Espacio de caché desconocido: «{espacio}»",
            error_code="cache.espacio_desconocido",
            detalle={"admitidos": sorted(ESPACIOS)},
        )

    cuerpo = ":".join(_limpia(p) for p in partes) if partes else "-"

    if global_:
        if tenant_id is not None:
            raise ErrorValidacion(
                "Una entrada global no puede llevar tenant: o es de todos o es de uno",
                error_code="cache.global_con_tenant",
            )
        gen = get_cache().generacion("global")
        return f"crm:g{gen}:global:{espacio}:{cuerpo}"

    if tenant_id is None:
        from crmcore.tenancy.context import contexto_actual

        tenant_id = getattr(contexto_actual(), "tenant_id", None)
    if tenant_id is None:
        raise ErrorValidacion(
            "Una entrada de caché necesita tenant. Si el dato es de la "
            "plataforma y no de un cliente, pásalo con global_=True.",
            error_code="cache.sin_tenant",
        )

    gen = get_cache().generacion(str(tenant_id))
    return f"crm:t{tenant_id}:g{gen}:{espacio}:{cuerpo}"


def purgar_tenant(tenant_id: UUID | str) -> int:
    """Invalida TODO lo cacheado de un tenant. Devuelve la generación nueva.

    O(1): incrementa la generación, y con ella todas las claves anteriores dejan
    de ser alcanzables. No borra nada de inmediato; lo hace el TTL. Por eso toda
    entrada tiene que tener TTL, y `fijar` lo exige.
    """
    from crmcore.cache.registro import invalidar_todos

    nueva = get_cache().incrementar_generacion(str(tenant_id))
    # Y las cachés en proceso de quien las tenga. Sin esto, la purga vaciaría la
    # compartida mientras cada réplica sigue sirviendo lo suyo desde memoria.
    invalidados = invalidar_todos(str(tenant_id))
    logger.info(
        "cache.purgada",
        tenant=str(tenant_id),
        generacion=nueva,
        invalidadores=invalidados,
    )
    return nueva


class CacheMemoria:
    """Caché en el proceso. Para desarrollo y pruebas.

    **No vale con más de una réplica**: cada proceso tendría la suya y una purga
    en uno no alcanzaría a los demás. El arranque avisa si se usa en producción.
    """

    def __init__(self) -> None:
        self._datos: dict[str, tuple[float, Any]] = {}
        self._generaciones: dict[str, int] = {}
        self._cerrojo = Lock()

    def obtener(self, clave: str) -> Any:
        with self._cerrojo:
            entrada = self._datos.get(clave)
            if entrada is None:
                return None
            caduca, valor = entrada
            if caduca < time.monotonic():
                # Caducada: se retira al leerla. Sin esto, una clave que nadie
                # vuelve a pedir se queda en memoria hasta que el proceso muere.
                self._datos.pop(clave, None)
                return None
            return valor

    def fijar(self, clave: str, valor: Any, *, ttl_s: int) -> None:
        with self._cerrojo:
            self._datos[clave] = (time.monotonic() + ttl_s, valor)

    def borrar(self, clave: str) -> None:
        with self._cerrojo:
            self._datos.pop(clave, None)

    def generacion(self, ambito: str) -> int:
        with self._cerrojo:
            return self._generaciones.get(ambito, 0)

    def incrementar_generacion(self, ambito: str) -> int:
        with self._cerrojo:
            nueva = self._generaciones.get(ambito, 0) + 1
            self._generaciones[ambito] = nueva
            return nueva

    def limpiar(self) -> None:
        with self._cerrojo:
            self._datos.clear()
            self._generaciones.clear()


class CacheRedis:
    """Caché en Redis, compartida por todas las réplicas.

    La generación de cada tenant se guarda también en Redis y se recuerda aquí
    unos segundos: consultarla en cada lectura duplicaría los viajes de red y
    dejaría la caché costando casi lo mismo que la consulta que evita. La
    ventana es corta y acotada — durante ella, una réplica puede seguir sirviendo
    lo purgado; es el precio explícito de no pagar un viaje por lectura, y por
    eso es configurable.
    """

    def __init__(self, url: str, *, ttl_generacion_s: int = 5) -> None:
        import redis

        self._redis = redis.Redis.from_url(url, decode_responses=True)
        self._ttl_gen = ttl_generacion_s
        self._gen_local: dict[str, tuple[float, int]] = {}
        self._cerrojo = Lock()

    def obtener(self, clave: str) -> Any:
        crudo = self._redis.get(clave)
        if crudo is None:
            return None
        try:
            return json.loads(crudo)
        except (ValueError, TypeError):
            # Un valor ilegible se trata como ausencia, no como error: la caché
            # nunca debe poder tumbar la petición que intentaba acelerar.
            logger.warning("cache.valor_ilegible", clave=clave[:80])
            return None

    def fijar(self, clave: str, valor: Any, *, ttl_s: int) -> None:
        self._redis.set(clave, json.dumps(valor, default=str), ex=ttl_s)

    def borrar(self, clave: str) -> None:
        self._redis.delete(clave)

    def generacion(self, ambito: str) -> int:
        ahora = time.monotonic()
        with self._cerrojo:
            recordada = self._gen_local.get(ambito)
            if recordada and recordada[0] > ahora:
                return recordada[1]
        valor = self._redis.get(f"crm:gen:{ambito}")
        gen = int(valor) if valor else 0
        with self._cerrojo:
            self._gen_local[ambito] = (ahora + self._ttl_gen, gen)
        return gen

    def incrementar_generacion(self, ambito: str) -> int:
        nueva = int(self._redis.incr(f"crm:gen:{ambito}"))
        with self._cerrojo:
            # Se recuerda la nueva de inmediato: quien acaba de purgar no puede
            # seguir leyendo de la generación vieja desde su propio proceso.
            self._gen_local[ambito] = (time.monotonic() + self._ttl_gen, nueva)
        return nueva

    def limpiar(self) -> None:
        with self._cerrojo:
            self._gen_local.clear()


_cache: Cache | None = None
_cerrojo_global = Lock()


def get_cache() -> Cache:
    """La caché configurada, construida una vez por proceso."""
    global _cache
    if _cache is not None:
        return _cache
    with _cerrojo_global:
        if _cache is not None:
            return _cache
        from crmcore.config import get_settings

        s = get_settings()
        if s.cache_backend == "redis" and s.cache_url:
            # ANTES del `try`: una URL en claro cuando se ha exigido cifrado no
            # es una caché caída, es una configuración que miente, y caer a la
            # caché en memoria la dejaría pasar en silencio.
            from crmcore.red import tls_exigido

            tls_exigido.exigir(
                s.cache_url, tramo="la caché", ajuste="CACHE_TLS", exigido=s.cache_tls
            )
            try:
                _cache = CacheRedis(s.cache_url, ttl_generacion_s=s.cache_ttl_generacion_s)
                logger.info("cache.lista", backend="redis")
            except Exception as exc:  # noqa: BLE001
                # Sin Redis se sigue, en memoria: una caché caída no puede
                # impedir que el servicio arranque. Pero se dice, y bien alto,
                # porque en varias réplicas deja de haber purga compartida.
                logger.error(
                    "cache.sin_redis",
                    error=str(exc),
                    aviso="la caché pasa a ser POR PROCESO y la purga no alcanza a las demás réplicas",
                )
                _cache = CacheMemoria()
        else:
            _cache = CacheMemoria()
            logger.info("cache.lista", backend="memoria")
        return _cache


def reset_cache() -> None:
    """Olvida la caché construida. Solo para pruebas."""
    global _cache
    with _cerrojo_global:
        if _cache is not None:
            _cache.limpiar()
        _cache = None


# ── Fachada de uso ────────────────────────────────────────────────────────


def obtener(
    espacio: str, *partes: Any, tenant_id: UUID | None = None, global_: bool = False
) -> Any:
    """Lee de la caché. Devuelve `None` si no está o si caducó."""
    return get_cache().obtener(clave_de(espacio, *partes, tenant_id=tenant_id, global_=global_))


def fijar(
    espacio: str,
    *partes: Any,
    valor: Any,
    ttl_s: int | None = None,
    tenant_id: UUID | None = None,
    global_: bool = False,
) -> None:
    """Guarda en la caché. El TTL es obligatorio, con tope configurado.

    Se capa contra el máximo en vez de aceptar lo que pidan: una entrada con un
    TTL de un año sobrevive a la purga por generación solo si la generación se
    pierde, y sobre todo mantiene ocupada la memoria de lo ya invalidado.
    """
    from crmcore.config import get_settings

    s = get_settings()
    efectivo = min(int(ttl_s or s.cache_ttl_s), int(s.cache_ttl_max_s))
    if efectivo <= 0:
        return
    get_cache().fijar(
        clave_de(espacio, *partes, tenant_id=tenant_id, global_=global_), valor, ttl_s=efectivo
    )


def borrar(
    espacio: str, *partes: Any, tenant_id: UUID | None = None, global_: bool = False
) -> None:
    """Invalida una entrada concreta."""
    get_cache().borrar(clave_de(espacio, *partes, tenant_id=tenant_id, global_=global_))
