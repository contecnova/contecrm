"""Cuántos listados raíz NO paginan, y que esa cifra solo pueda bajar.

**Un listado sin cursor no devuelve la tabla: devuelve su primera página.** Y
quien la lee no tiene forma de saberlo, porque una lista pelada no dice si hay
más. Medido cuando la explotación empezó a dar cifras: la métrica
`casos_abiertos` contestaba **50 habiendo 153**, con su unidad y su cara de cifra
buena. Un número así es peor que un error — nadie lo comprueba.

Los veintidós que había ya paginan. El tope es **cero** y de aquí no sube: un
listado nuevo que devuelva una lista pelada pone este gate en rojo antes de que
nadie construya una cifra encima.

Que cero sea alcanzable importa. Un tope «histórico» que se queda en veintidós
para siempre acaba siendo un permiso: lo que estaba mal se queda mal, con la
bendición de una prueba en verde.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[2]

SERVICIOS = sorted(
    p.name
    for p in (RAIZ / "services").iterdir()
    if p.is_dir() and not p.name.startswith("_") and (p / "main.py").exists()
)

# Ninguno. Eran 22 el 25-09-2026 y se arreglaron todos el 27.
TOPE_SIN_CURSOR = 0


def _app(servicio: str) -> Any:
    import os

    os.environ["SERVICE_NAME"] = servicio
    os.environ["BUS_BACKEND"] = "memoria"
    return importlib.import_module(f"services.{servicio}.main").app


def _pagina(esquema: dict[str, Any], contrato: dict[str, Any]) -> bool:
    """¿El esquema de respuesta es una página con cursor?"""
    ref = esquema.get("$ref")
    if ref and ref.startswith("#/components/schemas/"):
        nombre = ref.rsplit("/", 1)[-1]
        esquema = (contrato.get("components", {}).get("schemas", {}) or {}).get(nombre, {})
    return "items" in (esquema.get("properties") or {})


def test_los_listados_raiz_paginan() -> None:
    sin_cursor: list[str] = []

    for servicio in SERVICIOS:
        if servicio == "gateway":
            continue
        contrato = _app(servicio).openapi()
        for ruta, metodos in (contrato.get("paths") or {}).items():
            if "{" in ruta or ruta.count("/") != 3 or not ruta.startswith("/api/v1/"):
                continue
            operacion = metodos.get("get")
            if not operacion:
                continue
            contenido = (
                ((operacion.get("responses") or {}).get("200") or {}).get("content") or {}
            ).get("application/json") or {}
            esquema = contenido.get("schema") or {}
            # Sin esquema declarado no se puede saber estáticamente; esos se
            # miden al registrar la fuente, que es donde se ven de verdad.
            if not esquema:
                continue
            if esquema.get("type") == "array" or (
                esquema.get("items") and not _pagina(esquema, contrato)
            ):
                sin_cursor.append(f"{servicio}: {ruta}")

    assert len(sin_cursor) <= TOPE_SIN_CURSOR, (
        f"Hay {len(sin_cursor)} listados raíz sin cursor y el tope es "
        f"{TOPE_SIN_CURSOR}. Un listado sin cursor devuelve su primera página y "
        "quien la lee cree que es la tabla:\n  " + "\n  ".join(sorted(sin_cursor))
    )
