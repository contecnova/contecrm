#!/usr/bin/env python3
"""Da de alta el CRM como fuente consultable en contecintelligence (RT-4).

**Por qué hace falta.** El enlace con contecintelligence puede estar verde —canje
de token incluido— y no servir de nada, porque contecintelligence no conoce
ninguna tabla del CRM hasta que alguien se lo dice. Era exactamente el estado de
esta instalación: el enlace funcionaba, no había NINGUNA fuente dada de alta, y
cualquier pregunta no habría tenido de dónde sacar la respuesta.

**Por qué un script y no un botón en la pantalla.** Crear una fuente en
contecintelligence exige `SOURCE_WRITE`, que es un permiso de usuario suyo; sus
alcances delegados solo llegan a `sources:read`. Para que fuera un botón, allí
haría falta un alcance `sources:write` —está anotado en la especificación que
tienen— y hasta entonces esto lo ejecuta quien administra los dos.

Lo que hace, y por lo que no hay que escribir un solo JSON a mano:

  1. Crea en el CRM una clave de API de solo lectura para contecintelligence.
  2. Lee `/api/v1/superficie` y saca de ahí las entidades: **todo listado raíz
     que el propio sistema declara como colección**. No hay lista escrita a mano
     en ningún sitio, así que un módulo nuevo entra solo.
  3. Registra la fuente en contecintelligence con esas entidades, su paginación
     por cursor y la clave.

    python scripts/registrar_fuente_ci.py \\
        --crm http://localhost:18080 --tenant ficosa \\
        --email admin@ficosa.com --contrasena '…' \\
        --ci http://localhost:8100 --ci-tenant contec \\
        --ci-email admin@contecintelligence.local --ci-contrasena '…'
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any

TIEMPO = 30


def _llamar(
    metodo: str, url: str, cuerpo: dict | None = None, *, cabeceras: dict[str, str] | None = None
) -> tuple[int, Any]:
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    pet = urllib.request.Request(url, data=datos, method=metodo)
    pet.add_header("Content-Type", "application/json")
    for k, v in (cabeceras or {}).items():
        pet.add_header(k, v)
    try:
        with urllib.request.urlopen(pet, timeout=TIEMPO) as r:  # noqa: S310
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except Exception:
            return e.code, None


def entidades_desde_la_superficie(
    superficie: dict, *, crm: str, cabeceras: dict[str, str]
) -> tuple[list[dict], list[str]]:
    """Las entidades consultables, sacadas de lo que el propio CRM declara.

    Se cogen los listados RAÍZ (`/api/v1/<recurso>`, sin más tramos) que la
    superficie marca como colección y que no son de administración, ni de
    plataforma, ni exigen datos por la URL. Lo que decide no es una lista escrita
    aquí: es `devuelve_lista`, que sale del modelo de respuesta declarado.

    **Y la forma de cada una se MIDE, no se supone.** No todas son iguales:
    `/accounts` devuelve una página con cursor (`{items, siguiente, hay_mas}`) y
    `/activities` una lista pelada. Dar por hecho que todas paginan hacía que el
    alta fallara entera por la primera que no lo hacía. Se pregunta una vez por
    entidad —es un script de puesta en marcha, no un camino caliente— y de paso
    se descarta la que no conteste: mejor una fuente con cuarenta entidades que
    funcionan que una con cincuenta de las que dos rompen la carga.
    """
    entidades: list[dict] = []
    descartadas: list[str] = []
    for op in superficie.get("operaciones", []):
        ruta = op.get("ruta", "")
        if op.get("metodo") != "GET" or not op.get("devuelve_lista"):
            continue
        if "{" in ruta or ruta.count("/") != 3 or not ruta.startswith("/api/v1/"):
            continue
        if op.get("administracion") or op.get("solo_plataforma") or op.get("exige_datos"):
            continue
        nombre = ruta.rsplit("/", 1)[-1].replace("-", "_")

        estado, muestra = _llamar("GET", f"{crm}{ruta}?limite=1", cabeceras=cabeceras)
        if estado != 200:
            descartadas.append(f"{nombre} ({estado})")
            continue

        entidad: dict[str, Any] = {
            "name": nombre,
            "path": ruta[len("/api/v1") :],
            "primary_key": "id",
        }
        if isinstance(muestra, dict) and "items" in muestra:
            # Página con cursor: los registros bajo `items`, el cursor bajo
            # `siguiente` y `limite` como tamaño.
            entidad["record_path"] = "items"
            entidad["pagination"] = {
                "type": "cursor",
                "cursor_path": "siguiente",
                "cursor_param": "cursor",
                "size_param": "limite",
                "size": 200,
            }
        elif isinstance(muestra, list):
            # Lista pelada: sin `record_path` y sin paginación. El conector la
            # entiende tal cual; inventarle un cursor que no existe la rompería.
            pass
        else:
            descartadas.append(f"{nombre} (forma no reconocida)")
            continue
        entidades.append(entidad)
    return sorted(entidades, key=lambda e: e["name"]), descartadas


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--crm", default="http://localhost:18080")
    p.add_argument("--tenant", required=True)
    p.add_argument("--email", required=True)
    p.add_argument("--contrasena", required=True)
    p.add_argument("--ci", default="http://localhost:8100")
    p.add_argument("--ci-tenant", required=True)
    p.add_argument("--ci-email", required=True)
    p.add_argument("--ci-contrasena", required=True)
    # La dirección con la que contecintelligence verá al CRM. Desde su
    # contenedor, `localhost` es él mismo: por eso no vale el mismo valor que
    # `--crm` y se pregunta aparte.
    p.add_argument("--crm-desde-ci", default="http://gateway:8000")
    p.add_argument("--nombre", default="contecrm")
    a = p.parse_args()

    # ── 1. Entrar en el CRM y crear la clave de lectura ──────────────────────
    estado, _ = _llamar(
        "POST",
        f"{a.crm}/api/v1/sesion/entrar",
        {"email": a.email, "contrasena": a.contrasena, "tenant": a.tenant},
    )
    if estado != 200:
        print(f"No se ha podido entrar en el CRM: {estado}", file=sys.stderr)
        return 1
    # La sesión va por cookie y `urllib` no las guarda solo; se pide un token de
    # API, que es lo que de verdad hace falta después.
    estado, token = _llamar(
        "POST",
        f"{a.crm}/api/v1/auth/login",
        {"email": a.email, "contrasena": a.contrasena, "tenant": a.tenant},
    )
    if estado != 200 or not token:
        print(f"No se ha podido obtener el token del CRM: {estado}", file=sys.stderr)
        return 1
    aut = {"Authorization": f"Bearer {token['access_token']}"}

    estado, clave = _llamar(
        "POST",
        f"{a.crm}/api/v1/claves-api",
        # `solo_lectura` es `*:read`. Sin alcances que acoten: lo que puede ver esta clave
        # es exactamente lo que ve un lector del CRM, ni más ni menos.
        {"nombre": "contecintelligence", "scopes": [], "rol": "solo_lectura", "dias": 365},
        cabeceras=aut,
    )
    if estado != 201 or not clave:
        print(f"No se ha podido crear la clave de API: {estado} {clave}", file=sys.stderr)
        return 1
    secreto = clave["secreto"]
    print(f"clave de API creada: {clave['prefijo']}…")

    # ── 2. Sacar las entidades de la superficie ──────────────────────────────
    estado, superficie = _llamar("GET", f"{a.crm}/api/v1/superficie", cabeceras=aut)
    if estado != 200 or not superficie:
        print(f"No se ha podido leer la superficie: {estado}", file=sys.stderr)
        return 1
    entidades, descartadas = entidades_desde_la_superficie(
        superficie, crm=a.crm, cabeceras={"Authorization": f"Bearer {secreto}"}
    )
    print(f"entidades consultables: {len(entidades)}")
    if descartadas:
        print(f"  descartadas por no contestar: {', '.join(descartadas)}")
    if not entidades:
        print(
            "Ninguna entidad consultable: no tiene sentido dar de alta la fuente.", file=sys.stderr
        )
        return 1

    # ── 3. Registrar la fuente en contecintelligence ─────────────────────────
    estado, sesion = _llamar(
        "POST",
        f"{a.ci}/api/auth/login",
        {"tenant": a.ci_tenant, "email": a.ci_email, "password": a.ci_contrasena},
    )
    if estado != 200 or not sesion:
        print(f"No se ha podido entrar en contecintelligence: {estado}", file=sys.stderr)
        return 1
    aut_ci = {"Authorization": f"Bearer {sesion['access_token']}"}

    config = {
        "base_url": f"{a.crm_desde_ci}/api/v1",
        "auth": {"type": "bearer", "value": secreto},
        "entities": entidades,
    }
    estado, fuente = _llamar(
        "POST",
        f"{a.ci}/api/sources",
        {
            "name": a.nombre,
            "source_type": "api",
            "plantilla_id": "api-paginacion-por-cursor",
            "config": config,
        },
        cabeceras=aut_ci,
    )
    if estado not in (200, 201):
        print(f"contecintelligence ha rechazado el alta: {estado} {fuente}", file=sys.stderr)
        return 1
    print(f"fuente dada de alta: {fuente.get('id')} · {fuente.get('name')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
