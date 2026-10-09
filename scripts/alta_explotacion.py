#!/usr/bin/env python3
"""Deja contecrm y contecintelligence hablándose, desde una instalación limpia.

Una base de contecintelligence recién creada no conoce a contecrm: ni su
credencial (`CI_CLIENT_ID`), ni los orígenes del navegador, ni la organización
del tenant de plataforma, ni la fuente. Sin eso, la pantalla de Explotación
dice «ahora mismo no se puede preguntar» aunque los dos servicios estén vivos.

Es idempotente: cada paso comprueba antes de hacer, así que se puede repetir.

    python3 scripts/alta_explotacion.py

Solo usa la biblioteca estándar, para no depender de qué entorno la lanza.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
ALCANCES_POR_DEFECTO = ["chat:ask", "sources:read"]


def _leer_env(ruta: Path) -> dict[str, str]:
    valores: dict[str, str] = {}
    if not ruta.is_file():
        return valores
    for linea in ruta.read_text(encoding="utf-8", errors="replace").splitlines():
        limpia = linea.strip()
        if not limpia or limpia.startswith("#") or "=" not in limpia:
            continue
        clave, _, valor = limpia.partition("=")
        valores[clave.strip()] = valor.strip().strip('"').strip("'")
    return valores


def _escribir_env(ruta: Path, cambios: dict[str, str]) -> None:
    texto = ruta.read_text(encoding="utf-8")
    for clave, valor in cambios.items():
        patron = re.compile(rf"^{re.escape(clave)}=.*$", re.M)
        if patron.search(texto):
            texto = patron.sub(lambda _m, c=clave, v=valor: f"{c}={v}", texto, count=1)
        else:
            texto = texto.rstrip("\n") + f"\n{clave}={valor}\n"
    ruta.write_text(texto, encoding="utf-8")


def _http(
    metodo: str, url: str, cuerpo: dict | None = None, token: str = "", timeout: float = 20.0
) -> tuple[int, dict | list | str]:
    cabeceras = {"Content-Type": "application/json"}
    if token:
        cabeceras["Authorization"] = f"Bearer {token}"
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    peticion = urllib.request.Request(url, data=datos, method=metodo, headers=cabeceras)
    try:
        with urllib.request.urlopen(peticion, timeout=timeout) as r:  # noqa: S310 - URL local
            crudo = r.read().decode("utf-8", "replace")
            estado = r.status
    except urllib.error.HTTPError as error:
        crudo = error.read().decode("utf-8", "replace")
        estado = error.code
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return 0, str(error)
    try:
        return estado, json.loads(crudo) if crudo else {}
    except ValueError:
        return estado, crudo


def _mensaje(cuerpo: object) -> str:
    if isinstance(cuerpo, dict):
        return str(cuerpo.get("detail") or cuerpo.get("title") or cuerpo)[:200]
    return str(cuerpo)[:200]


def _ok(texto: str) -> None:
    print(f"  ✓ {texto}")


def _malo(texto: str) -> None:
    print(f"  ✗ {texto}")


def _esperar(url: str, token: str, segundos: int = 90) -> bool:
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        if _http("GET", url, token=token, timeout=5.0)[0] == 200:
            return True
        time.sleep(3)
    return False


def _recrear_analytics() -> bool:
    """Los servicios leen el `.env` al crearse: cambiar la credencial exige recrearlos."""
    ps = subprocess.run(
        ["docker", "compose", "--profile", "app", "--profile", "consola", "ps", "-q", "analytics"],
        cwd=RAIZ,
        capture_output=True,
        text=True,
    )
    if ps.returncode or not ps.stdout.strip():
        return False
    subprocess.run(
        [
            "docker",
            "compose",
            "--profile",
            "app",
            "--profile",
            "consola",
            "up",
            "-d",
            "--force-recreate",
            "analytics",
            "analytics-trabajos",
        ],
        cwd=RAIZ,
        capture_output=True,
        text=True,
        check=False,
    )
    return True


def main() -> int:
    crm = _leer_env(RAIZ / ".env")
    repo_ci = Path(os.environ.get("CONTECINTELLIGENCE_REPO") or RAIZ.parent / "contecintelligence")
    ci_env = _leer_env(repo_ci / ".env")

    admin = ci_env.get("ADMIN_TOKEN", "")
    if not admin:
        _malo(f"Sin ADMIN_TOKEN en {repo_ci / '.env'}: no se puede dar de alta a contecrm allí")
        return 1
    ci = f"http://127.0.0.1:{ci_env.get('API_PORT', '8100')}"
    gateway = f"http://127.0.0.1:{crm.get('GATEWAY_PORT', '18080')}/api/v1"

    front = crm.get("FRONT_PORT", "15173")
    consola = crm.get("CONSOLA_PORT", "13000")
    origenes = [
        f"http://{host}:{puerto}"
        for puerto in (front, consola)
        for host in ("localhost", "127.0.0.1")
    ]
    alcances = ALCANCES_POR_DEFECTO
    if crm.get("CI_SCOPES"):
        try:
            alcances = list(json.loads(crm["CI_SCOPES"]))
        except ValueError:
            pass

    estado, apps = _http("GET", f"{ci}/api/admin/apps", token=admin)
    if estado != 200 or not isinstance(apps, list):
        _malo(f"contecintelligence no deja listar aplicaciones ({estado}): {_mensaje(apps)}")
        return 1

    client_id, secreto = crm.get("CI_CLIENT_ID", ""), crm.get("CI_CLIENT_SECRET", "")
    valida = False
    if client_id and secreto:
        valida = (
            _http(
                "POST", f"{ci}/api/oauth/token", {"client_id": client_id, "client_secret": secreto}
            )[0]
            == 200
        )
    app = next((a for a in apps if a.get("client_id") == client_id), None) if valida else None

    credencial_cambiada = False
    if app is None:
        estado, creada = _http(
            "POST",
            f"{ci}/api/admin/apps",
            {"name": "contecrm", "modo": "exchange", "scopes": alcances, "origins": origenes},
            token=admin,
        )
        if estado != 200 or not isinstance(creada, dict):
            _malo(f"No se pudo dar de alta la aplicación ({estado}): {_mensaje(creada)}")
            return 1
        _escribir_env(
            RAIZ / ".env",
            {"CI_CLIENT_ID": creada["client_id"], "CI_CLIENT_SECRET": creada["client_secret"]},
        )
        app, credencial_cambiada = creada, True
        _ok(f"Aplicación «contecrm» dada de alta en contecintelligence ({creada['client_id']})")
    else:
        faltan = [o for o in origenes if o not in (app.get("origins") or [])]
        if faltan:
            estado, cuerpo = _http(
                "PATCH",
                f"{ci}/api/admin/apps/{app['id']}",
                {"origins": [*(app.get("origins") or []), *faltan]},
                token=admin,
            )
            if estado != 200:
                _malo(
                    f"No se pudieron permitir los orígenes del front ({estado}): {_mensaje(cuerpo)}"
                )
                return 1
            _ok(f"Orígenes del navegador permitidos: {', '.join(faltan)}")
        else:
            _ok("La credencial de contecrm vale y sus orígenes están permitidos")

    if credencial_cambiada:
        if _recrear_analytics():
            _ok("Servicios de explotación recreados con la credencial nueva")
        else:
            _ok("Credencial guardada en .env: reinicia analytics para que la lea")

    email = crm.get("SUPERADMIN_EMAIL", "")
    clave = crm.get("SUPERADMIN_PASSWORD", "")
    empresa = crm.get("SUPERADMIN_TENANT", "plataforma")
    if not email or not clave:
        _malo("Sin SUPERADMIN_EMAIL/SUPERADMIN_PASSWORD: no se puede asignar la organización")
        return 1
    # Recién arrancado, el gateway puede contestar 503 un rato: se reintenta.
    limite = time.monotonic() + 120
    while True:
        estado, sesion = _http(
            "POST",
            f"{gateway}/auth/login",
            {"email": email, "contrasena": clave, "tenant": empresa},
        )
        if estado == 200 or estado in (401, 422) or time.monotonic() > limite:
            break
        time.sleep(3)
    if estado != 200 or not isinstance(sesion, dict) or "access_token" not in sesion:
        _malo(f"No se pudo entrar en el CRM como {email} ({estado}): {_mensaje(sesion)}")
        return 1
    token = sesion["access_token"]
    cuerpo_jwt = token.split(".")[1]
    tenant_id = json.loads(base64.urlsafe_b64decode(cuerpo_jwt + "=" * (-len(cuerpo_jwt) % 4)))[
        "tenant"
    ]

    if not _esperar(f"{gateway}/analitica/estado", token):
        _malo("El servicio de explotación no responde en el gateway")
        return 1

    estado, cuerpo = _http(
        "POST",
        f"{ci}/api/admin/apps/{app['id']}/tenants",
        {"externo": empresa, "tenant_id": empresa, "crear_si_falta": True},
        token=admin,
    )
    if estado != 200:
        _malo(f"No se pudo crear/mapear la organización «{empresa}» ({estado}): {_mensaje(cuerpo)}")
        return 1
    estado, cuerpo = _http(
        "PUT",
        f"{gateway}/analitica/organizaciones",
        {"tenant_id": tenant_id, "organizacion": empresa},
        token=token,
    )
    if estado != 200:
        _malo(f"No se pudo asignar la organización al tenant ({estado}): {_mensaje(cuerpo)}")
        return 1
    _ok(f"Tenant «{empresa}» asignado a la organización «{empresa}»")

    estado, cuerpo = _http(
        "POST", f"{gateway}/explotacion/registrar-fuente", token=token, cuerpo={}
    )
    if estado not in (200, 202, 409):
        _malo(f"No se pudo registrar el CRM como fuente ({estado}): {_mensaje(cuerpo)}")
        return 1
    _ok("CRM registrado como fuente consultable (el alta sigue en segundo plano)")

    # Refresca el último error que la pantalla enseña (guardaba el de antes del alta).
    _http("GET", f"{gateway}/analitica/estado?comprobar=true", token=token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
