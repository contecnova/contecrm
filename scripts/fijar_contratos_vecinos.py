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
import os
import sys
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parent.parent
DESTINO = RAIZ / "tests" / "fixtures" / "contratos"


# Qué vecino, dónde preguntarle y qué rutas le pedimos. Las rutas se declaran
# aquí y NO se leen del cliente: si se leyeran del cliente, renombrar una ruta
# mal en el cliente renombraría también lo que se comprueba, y el gate diría que
# todo está bien.
# La DIRECCIÓN del vecino depende de la instalación, igual que `DMS_BASE_URL` o
# `CI_BASE_URL` en el `.env`: puede ser el de la pila local, uno en otra máquina
# o uno recién levantado a mano para comprobar un cambio antes de desplegarlo.
# Escrita a fuego obligaba a tocar este fichero para refrescar contra otro sitio,
# que es exactamente la clase de edición que nadie recuerda deshacer.
def _openapi_de(nombre: str, defecto: str) -> str:
    return os.environ.get(f"{nombre.upper()}_OPENAPI", defecto)


VECINOS: dict[str, dict[str, Any]] = {
    "contecintelligence": {
        "openapi": _openapi_de("contecintelligence", "http://localhost:8100/openapi.json"),
        "rutas": ["/api/oauth/token", "/api/tokens/exchange"],
    },
    "contecmind": {
        "openapi": _openapi_de("contecmind", "http://localhost:8200/api/v1/openapi.json"),
        "rutas": [
            "/api/v1/oauth/token",
            "/api/v1/tokens/exchange",
            "/api/v1/documents/search",
            "/api/v1/documents/{document_id}",
            # Árbol documental (contecmind bbc9757f). Se fijan porque son las que
            # consume el corpus del CRM: si cambia un nombre de campo al otro lado,
            # esto se pone rojo aquí y no en la pantalla de un cliente.
            # El área se resuelve por su NOMBRE contra esta lista, y no se fija
            # su identificador en la configuración: un id de área es de un
            # tenant y el fichero de configuración es el mismo para todos.
            "/api/v1/areas",
            "/api/v1/folders",
            "/api/v1/folders/{folder_id}/documents",
            "/api/v1/folders/{folder_id}/effective-permissions",
            "/api/v1/folders/{folder_id}/summary",
            "/api/v1/folders/{folder_id}/concepts",
            "/api/v1/documents/{document_id}/move",
            # El aprovisionamiento: dar de alta en el gestor lo que se da de alta
            # en el CRM. Se fijan AUNQUE NO EXISTAN TODAVÍA —el fichero guarda el
            # hueco explícito— porque es justo lo que hace que el día que
            # aparezcan se note, y que si aparecen con otra forma el gate lo diga
            # en vez de descubrirlo al dar de alta un cliente.
            "/api/v1/admin/tenants/by-external/{id_externo}",
            "/api/v1/admin/users/by-external/{id_externo}",
            "/api/v1/admin/departments/by-external/{id_externo}",
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
    # Sin esto, un vecino caído impedía refrescar el otro aunque estuviera
    # levantado — y entonces la tentación es comentar una entrada del diccionario.
    parser.add_argument("--solo", choices=sorted(VECINOS), help="refresca solo ese vecino")
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
        if args.solo and nombre != args.solo:
            continue
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
