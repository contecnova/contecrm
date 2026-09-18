#!/usr/bin/env python3
"""Siembra un tenant de demostración con datos coherentes.

    python scripts/sembrar_demo.py                  # todo (desarrollo local)
    python scripts/sembrar_demo.py --parte tenant   # desde el contenedor tenancy
    python scripts/sembrar_demo.py --parte usuario  # desde el contenedor identity

**Por qué se puede partir en dos.** En desarrollo local un solo proceso llega a
todos los esquemas y siembra de una vez. En un despliegue real **no**, y eso es
exactamente lo que se busca: el contenedor de `tenancy` conecta con un rol que
no tiene permisos sobre el esquema de `identity`, así que intentarlo falla con
«relation "usuarios" does not exist». No es un fallo del sembrador: es el
aislamiento entre servicios funcionando, y se comprobó levantando la pila con
Docker. Por eso cada parte se ejecuta donde tiene permisos.

**Se niega a ejecutarse en producción.** Sembrar datos de ejemplo en la base de
un cliente no es un fallo recuperable con un `DELETE`: los eventos ya se han
publicado, la auditoría ya lo ha registrado y los webhooks ya han salido.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from uuid import UUID

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "packages" / "crmcore"))

SLUG = "demo"
# `.local` NO vale: es un dominio de uso especial reservado (RFC 6762) y el
# validador de correo lo rechaza, así que el usuario de demostración no podría
# iniciar sesión. `example.com` está reservado justo para esto (RFC 2606).
EMAIL_ADMIN = "admin@demo.example.com"
# Contraseña de demostración. Larga porque el sistema exige 12 caracteres, y
# pública a propósito: esto solo corre fuera de producción.
CONTRASENA = "demo-contecrm-2026"


def _parte_pedida() -> str:
    if "--parte" in sys.argv:
        i = sys.argv.index("--parte")
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return "todo"


def _sembrar_tenant() -> UUID:
    """Crea el plan y el tenant. Necesita permisos sobre el esquema `tenancy`."""
    from crmcore.db.uow import unidad_de_trabajo
    from crmcore.tenancy.context import contexto_sistema
    from sqlalchemy import select

    from services.tenancy import servicio as svc_tenancy
    from services.tenancy.modelos import Plan, Tenant

    with contexto_sistema(origen="cli"), unidad_de_trabajo(sistema=True) as uow:
        existente = uow.db.execute(select(Tenant).where(Tenant.slug == SLUG)).scalar_one_or_none()
        if existente:
            print(f"El tenant «{SLUG}» ya existe ({existente.id}). No se toca nada.")
            return existente.id

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

        tenant = svc_tenancy.crear_tenant(uow, slug=SLUG, nombre="Demostración, S.L.", plan="demo")
        print(f"Tenant «{SLUG}» creado: {tenant.id}")
        return tenant.id


def _sembrar_usuario(tenant_id: UUID) -> None:
    """Crea el administrador. Necesita permisos sobre el esquema `identity`."""
    os.environ["SERVICE_NAME"] = "identity"
    from crmcore.config import limpiar_cache_settings
    from crmcore.db.session import reset_engine

    # La configuración y el engine se cachean por proceso: sin limpiarlos, esta
    # parte seguiría apuntando al esquema de `tenancy`.
    limpiar_cache_settings()
    reset_engine()

    from crmcore.db.uow import unidad_de_trabajo
    from crmcore.tenancy.context import con_contexto

    from services.identity import servicio as svc_identity

    with con_contexto(tenant_id=tenant_id, origen="cli"), unidad_de_trabajo(tenant_id) as uow:
        svc_identity.crear_usuario(
            uow,
            email=EMAIL_ADMIN,
            nombre="Administrador de la demo",
            tenant_id=tenant_id,
            roles=["admin"],
            contrasena=CONTRASENA,
            via="semilla",
        )
    print(f"Usuario «{EMAIL_ADMIN}» creado")


def main() -> int:
    from crmcore.config import get_settings

    parte = _parte_pedida()
    if parte not in ("tenant", "usuario", "todo"):
        print(f"Parte desconocida: «{parte}» (usa tenant|usuario|todo)", file=sys.stderr)
        return 2

    os.environ.setdefault("SERVICE_NAME", "tenancy" if parte != "usuario" else "identity")
    if get_settings().es_produccion:
        print(
            "Este script no se ejecuta en producción (ENV=prod).\n"
            "Sembrar datos de ejemplo en la base de un cliente no se deshace con "
            "un DELETE: los eventos ya se han publicado y la auditoría ya lo ha "
            "registrado.",
            file=sys.stderr,
        )
        return 2

    if parte == "tenant":
        tenant_id = _sembrar_tenant()
        print(
            "\nTenant sembrado. Ahora, desde el servicio de identidad:\n"
            f"  TENANT_DEMO={tenant_id} python scripts/sembrar_demo.py --parte usuario"
        )
        return 0

    if parte == "usuario":
        valor = os.environ.get("TENANT_DEMO", "")
        if not valor:
            print(
                "Falta TENANT_DEMO con el identificador del tenant. Lo imprime "
                "`--parte tenant`.",
                file=sys.stderr,
            )
            return 2
        tenant_id = UUID(valor)
        _sembrar_usuario(tenant_id)
    else:
        tenant_id = _sembrar_tenant()
        _sembrar_usuario(tenant_id)

    print(
        "\nListo:\n"
        f"  tenant      {SLUG} ({tenant_id})\n"
        f"  usuario     {EMAIL_ADMIN}\n"
        f"  contraseña  {CONTRASENA}\n\n"
        "Entrar:\n"
        "  curl -sX POST http://localhost:8080/api/v1/auth/login \\\n"
        '    -H "Content-Type: application/json" \\\n'
        f'    -d \'{{"email":"{EMAIL_ADMIN}","contrasena":"{CONTRASENA}",'
        f'"tenant":"{tenant_id}"}}\''
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
