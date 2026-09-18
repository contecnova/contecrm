#!/usr/bin/env python3
"""Siembra un tenant de demostración con datos coherentes.

    python scripts/sembrar_demo.py

Crea un tenant, un plan, un administrador, un proceso de ejemplo y una
automatización, de modo que un desarrollador o un comercial pueda abrir el
sistema y ver algo en vez de una instalación vacía.

**Se niega a ejecutarse en producción.** Sembrar datos de ejemplo en la base de
un cliente no es un fallo recuperable con un `DELETE`: los eventos ya se han
publicado, la auditoría ya lo ha registrado y los webhooks ya han salido.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "packages" / "crmcore"))

SLUG = "demo"
# `.local` NO vale: es un dominio de uso especial reservado (RFC 6762) y el
# validador de correo lo rechaza, así que el usuario de demostración no podía
# iniciar sesión. `example.com` está reservado justo para esto (RFC 2606).
EMAIL_ADMIN = "admin@demo.example.com"
# Contraseña de demostración. Es larga porque el propio sistema exige 12
# caracteres, y es pública a propósito: esto solo corre fuera de producción.
CONTRASENA = "demo-contecrm-2026"


def main() -> int:
    from crmcore.config import get_settings

    os.environ.setdefault("SERVICE_NAME", "tenancy")
    s = get_settings()
    if s.es_produccion:
        print(
            "Este script no se ejecuta en producción (ENV=prod).\n"
            "Sembrar datos de ejemplo en la base de un cliente no se deshace "
            "con un DELETE: los eventos ya se han publicado y la auditoría ya "
            "lo ha registrado.",
            file=sys.stderr,
        )
        return 2

    from crmcore.db.uow import unidad_de_trabajo
    from crmcore.tenancy.context import contexto_sistema
    from sqlalchemy import select

    from services.tenancy.modelos import Plan, Tenant

    with contexto_sistema(origen="cli"), unidad_de_trabajo(sistema=True) as uow:
        from services.tenancy import servicio as svc_tenancy

        existente = uow.db.execute(select(Tenant).where(Tenant.slug == SLUG)).scalar_one_or_none()
        if existente:
            print(f"El tenant «{SLUG}» ya existe ({existente.id}). No se toca nada.")
            return 0

        if not uow.db.execute(select(Plan).where(Plan.codigo == "demo")).scalar_one_or_none():
            uow.db.add(
                Plan(
                    codigo="demo",
                    nombre="Demostración",
                    descripcion="Todo activo, con topes bajos para poder ver los avisos de cuota",
                    capacidades={
                        "procesos": True,
                        "automatizaciones": True,
                        "integraciones": True,
                        "webhooks": True,
                        "ia_generativa": False,
                    },
                    cuotas={"quota_registros": 10_000, "quota_api_calls_por_minuto": 600},
                )
            )
            uow.db.flush()

        tenant = svc_tenancy.crear_tenant(
            uow,
            slug=SLUG,
            nombre="Demostración, S.L.",
            plan="demo",
        )
        print(f"Tenant «{SLUG}» creado: {tenant.id}")

    # El usuario se crea en el servicio de identidad, que tiene su propio
    # esquema: se abre una sesión aparte a propósito, porque escribir en el
    # esquema de otro servicio desde aquí es justo lo que el modelo prohíbe.
    os.environ["SERVICE_NAME"] = "identity"
    from crmcore.config import limpiar_cache_settings
    from crmcore.db.session import reset_engine

    limpiar_cache_settings()
    reset_engine()

    from crmcore.tenancy.context import con_contexto

    from services.identity import servicio as svc_identity

    with con_contexto(tenant_id=tenant.id, origen="cli"), unidad_de_trabajo(tenant.id) as uow:
        svc_identity.crear_usuario(
            uow,
            email=EMAIL_ADMIN,
            nombre="Administrador de la demo",
            tenant_id=tenant.id,
            roles=["admin"],
            contrasena=CONTRASENA,
            via="semilla",
        )

    print(
        "\nListo:\n"
        f"  tenant      {SLUG} ({tenant.id})\n"
        f"  usuario     {EMAIL_ADMIN}\n"
        f"  contraseña  {CONTRASENA}\n\n"
        "Entrar:\n"
        "  curl -sX POST http://localhost:8080/api/v1/auth/login \\\n"
        '    -H "Content-Type: application/json" \\\n'
        f'    -d \'{{"email":"{EMAIL_ADMIN}","contrasena":"{CONTRASENA}",'
        f'"tenant":"{tenant.id}"}}\''
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
