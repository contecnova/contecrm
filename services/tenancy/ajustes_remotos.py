"""Las claves de ajuste que declaran los demás servicios, traídas a la consola.

La consola de ajustes vive aquí, y aquí sólo se conocían las claves del núcleo:
las que declara cada servicio en su `ajustes.py` se registran al importarse en
SU proceso, y este no puede importarlo (CRM-00.03.01.02). Medido el 10-11-2026:
166 claves —`salud_dias_vigencia`, `proveedor_dias_preaviso`, `lecciones_*`…—
no salían en la consola y fijarlas daba «clave desconocida». Sólo se cambiaban
por `.env`, y el manual decía otra cosa.

Cada servicio publica las suyas en `/interno/ajustes/catalogo` y se agregan
aquí: se incorporan al catálogo del proceso, con su servicio dueño, y desde ahí
la consola las valida, las fija, las versiona y las replica exactamente igual
que las del núcleo. El valor fijado le llega al dueño por la réplica de siempre
(`configuracion.ajuste_cambiado`), que él sí consume porque la clave es suya.

El valor por defecto lo da el dueño, que es quien tiene su configuración: se
registra como un proveedor de ajustes de servicio más, por el mismo camino que
usa `efectivo()` para cualquier servicio.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from crmcore.logging import get_logger
from crmcore.runtime.keys import CLAVES, de_dict, incorporar_de_otro_servicio
from crmcore.runtime.settings import registrar_ajustes_servicio

logger = get_logger(__name__)

_lock = threading.Lock()
_traido_en: float | None = None
# Servicios que no contestaron en la última vuelta: se reintentan en la
# siguiente, y se dicen en la respuesta de la consola en vez de callarlos.
_sin_respuesta: list[str] = []
# `campo_settings` → valor por defecto según el dueño.
_por_defecto: dict[str, Any] = {}


class _Defectos:
    """Lo que `efectivo()` consulta como si fuera el `Settings` de un servicio."""

    def __getattr__(self, nombre: str) -> Any:
        try:
            return _por_defecto[nombre]
        except KeyError:
            raise AttributeError(nombre) from None


_DEFECTOS = _Defectos()


def _proveedor() -> _Defectos:
    return _DEFECTOS


registrar_ajustes_servicio(_proveedor)


def _preguntar_a_todos() -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    from concurrent.futures import ThreadPoolExecutor

    import httpx
    from crmcore.config import get_settings
    from crmcore.http.interno import cabeceras_firmadas
    from crmcore.rutas_de_api import cargar_destinos

    s = get_settings()
    destinos = {
        n: d
        for n, d in cargar_destinos(s.rutas_servicios).items()
        if n not in ("tenancy", "gateway")
    }
    if not destinos:
        return {}, []

    def _uno(nombre: str) -> tuple[str, list[dict[str, Any]] | None]:
        try:
            r = httpx.get(
                f"{destinos[nombre].url_base}{s.api_prefix}/interno/ajustes/catalogo",
                headers=cabeceras_firmadas(),
                timeout=s.http_interno_timeout_s,
            )
            if r.status_code != 200:
                logger.warning("ajustes.catalogo_rechazado", servicio=nombre, estado=r.status_code)
                return nombre, None
            return nombre, list(r.json().get("claves") or [])
        except Exception as exc:  # noqa: BLE001 — un servicio caído no tumba la consola
            logger.warning("ajustes.catalogo_sin_respuesta", servicio=nombre, error=str(exc)[:200])
            return nombre, None

    with ThreadPoolExecutor(max_workers=len(destinos)) as hilos:
        resultados = list(hilos.map(_uno, sorted(destinos)))
    catalogos = {n: c for n, c in resultados if c is not None}
    return catalogos, sorted(n for n, c in resultados if c is None)


def asegurar(*, forzar: bool = False) -> list[str]:
    """Trae los catálogos si hace falta. Devuelve los servicios que no contestaron.

    Se refresca con la vida de la caché de ajustes: una clave nueva llega con
    un despliegue, no a cada segundo, y la consola no tiene por qué preguntar a
    trece servicios en cada carga. Con algún servicio sin contestar, se vuelve
    a intentar en la siguiente llamada.
    """
    global _traido_en, _sin_respuesta
    from crmcore.config import get_settings

    ttl = get_settings().ajustes_ttl_cache_s
    with _lock:
        fresco = _traido_en is not None and time.monotonic() - _traido_en < ttl
        if fresco and not forzar and not _sin_respuesta:
            return []
        catalogos, faltan = _preguntar_a_todos()
        incorporadas = 0
        for servicio, claves in catalogos.items():
            for datos in claves:
                try:
                    decl = de_dict(datos, servicio)
                except (KeyError, TypeError):
                    logger.warning("ajustes.catalogo_fila_invalida", servicio=servicio)
                    continue
                if incorporar_de_otro_servicio(decl):
                    incorporadas += 1
                    if decl.campo_settings:
                        _por_defecto[decl.campo_settings] = datos.get("por_defecto")
        _traido_en = time.monotonic()
        _sin_respuesta = faltan
        logger.info(
            "ajustes.catalogo_agregado",
            servicios=len(catalogos),
            claves=incorporadas,
            sin_respuesta=faltan,
        )
        return list(faltan)


def asegurar_clave(clave: str) -> None:
    """Antes de fijar: si la clave no se conoce, se pregunta otra vez a todos."""
    asegurar(forzar=clave not in CLAVES)
