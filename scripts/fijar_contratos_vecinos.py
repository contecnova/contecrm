"""Fija el contrato PUBLICADO de los servicios de la casa que consumimos.

Por qué existe. Los cinco desajustes que ha tenido esta integración —ruta,
mecanismo de autenticación, número de pasos y dos nombres de campo— eran todos
de CONTRATO, y ninguna prueba con dobles los habría cazado: un doble responde lo
que le dices, así que fija tu suposición, no lo que el otro lado publica.

Lo que sí los caza es comparar contra su OpenAPI. Se guarda REDUCIDO —solo las
rutas que usamos y los campos que declaran— por dos motivos: el de contecmind
tiene 413 rutas y no cabe en el límite de tamaño de los ganchos, y un contrato
recortado a lo que consumimos se lee de un vistazo en la revisión.

    python scripts/fijar_contratos_vecinos.py            # comprueba
    python scripts/fijar_contratos_vecinos.py --refrescar # vuelve a bajarlo

Refrescar exige tener el vecino levantado. Es a propósito: un contrato fijado sin
mirar el servicio de verdad es otra suposición.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parent.parent
DESTINO = RAIZ / "tests" / "fixtures" / "contratos"

# Qué vecino, dónde preguntarle y qué rutas le pedimos. Las rutas se declaran
# aquí y NO se leen del cliente: si se leyeran del cliente, renombrar una ruta
# mal en el cliente renombraría también lo que se comprueba, y el gate diría que
# todo está bien.
VECINOS: dict[str, dict[str, Any]] = {
    "contecintelligence": {
        "openapi": "http://localhost:8100/openapi.json",
        "rutas": ["/api/oauth/token", "/api/tokens/exchange"],
    },
    "contecmind": {
        "openapi": "http://localhost:8200/api/v1/openapi.json",
        "rutas": [
            "/api/v1/oauth/token",
            "/api/v1/tokens/exchange",
            "/api/v1/documents/search",
            "/api/v1/documents/{document_id}",
        ],
    },
}


def _propiedades(doc: dict[str, Any], operacion: dict[str, Any]) -> list[str]:
    """Los campos que el otro lado DECLARA en el cuerpo de esa operación."""
    cuerpo = operacion.get("requestBody") or {}
    esquema = ((cuerpo.get("content") or {}).get("application/json") or {}).get("schema") or {}
    ref = esquema.get("$ref")
    if ref:
        nombre = ref.rsplit("/", 1)[-1]
        esquema = (doc.get("components", {}).get("schemas", {}) or {}).get(nombre, {})
    return sorted((esquema.get("properties") or {}).keys())


def reducir(doc: dict[str, Any], rutas: list[str]) -> dict[str, Any]:
    salida: dict[str, Any] = {}
    for ruta in rutas:
        operaciones = doc.get("paths", {}).get(ruta)
        if operaciones is None:
            # Se guarda el hueco EXPLÍCITO en vez de omitir la ruta: una ruta
            # ausente del fichero se confundiría con una que nadie fijó.
            salida[ruta] = None
            continue
        salida[ruta] = {
            metodo: {"campos": _propiedades(doc, op)}
            for metodo, op in operaciones.items()
            if metodo in ("get", "post", "put", "patch", "delete")
        }
    return salida


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refrescar", action="store_true")
    args = parser.parse_args()

    if not args.refrescar:
        faltan = [n for n in VECINOS if not (DESTINO / f"{n}.json").exists()]
        if faltan:
            print(f"Sin contrato fijado para: {', '.join(faltan)}", file=sys.stderr)
            return 1
        print(f"contratos fijados: {', '.join(sorted(VECINOS))}")
        return 0

    import httpx

    DESTINO.mkdir(parents=True, exist_ok=True)
    for nombre, cfg in VECINOS.items():
        try:
            doc = httpx.get(cfg["openapi"], timeout=10).json()
        except Exception as exc:  # noqa: BLE001
            print(f"{nombre}: no se ha podido bajar su contrato ({exc}).", file=sys.stderr)
            print("  Levántalo y vuelve a intentarlo; fijarlo a ciegas no vale.", file=sys.stderr)
            return 1
        (DESTINO / f"{nombre}.json").write_text(
            json.dumps(reducir(doc, cfg["rutas"]), indent=2, ensure_ascii=False) + "\n"
        )
        print(f"{nombre}: fijado")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
