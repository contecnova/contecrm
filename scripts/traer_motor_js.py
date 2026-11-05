#!/usr/bin/env python3
"""Trae el motor de JavaScript de las extensiones y comprueba su huella.

    python scripts/traer_motor_js.py [destino]

El motor es QuickJS (quickjs-ng) compilado a WebAssembly por su propio proyecto,
y lo ejecuta wasmtime. No va en el repositorio —pesa 1,5 MB y el gancho de
ficheros grandes corta en 512 KB— sino fijado en
`services/automation/motor_js.lock.json`: versión, dirección y SHA-256. Esto lo
descarga y **se niega a dejarlo si la huella no coincide**: un motor cambiado es
justo lo que no puede ejecutar código ajeno.

El destino por defecto es `EXTENSIONES_MOTOR_RUTA` o, sin ella,
`var/motor/qjs-wasi.wasm`. Lo llaman `setup.sh` y la etapa de construcción de la
imagen. Si ya está y cuadra, no descarga nada.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
CANDADO = RAIZ / "services" / "automation" / "motor_js.lock.json"


def huella(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def main() -> int:
    candado = json.loads(CANDADO.read_text())
    destino = Path(
        sys.argv[1]
        if len(sys.argv) > 1
        else os.environ.get("EXTENSIONES_MOTOR_RUTA") or RAIZ / "var" / "motor" / candado["fichero"]
    )
    if destino.exists() and huella(destino) == candado["sha256"]:
        print(f"motor {candado['version']} ya está en {destino}")
        return 0
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_suffix(".descarga")
    # Con httpx y no con urllib: trae sus certificados raíz, y el Python de
    # python.org en macOS no los tiene cargados —urllib fallaba al verificar—.
    import httpx

    respuesta = httpx.get(candado["url"], follow_redirects=True, timeout=120)
    respuesta.raise_for_status()
    temporal.write_bytes(respuesta.content)
    obtenida = huella(temporal)
    if obtenida != candado["sha256"]:
        temporal.unlink(missing_ok=True)
        print(
            f"La huella del motor no coincide: {obtenida} y el candado dice "
            f"{candado['sha256']}. No se deja.",
            file=sys.stderr,
        )
        return 1
    temporal.replace(destino)
    print(f"motor {candado['version']} en {destino}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
