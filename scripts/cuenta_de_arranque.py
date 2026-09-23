#!/usr/bin/env python3
"""La cuenta que opera la plataforma, tal y como la dice el `.env`.

`es_plataforma` decide quién puede abrir la consola de plataforma —dar de alta
empresas, mirar su consumo, suspender una, suplantar con motivo—. Existía en el
modelo, lo exigían las operaciones de administración y **nadie lo ponía nunca**:
ni el alta de usuario lo admite, ni el sembrado lo activaba. El resultado es que
una instalación recién levantada no tiene a nadie capaz de administrarla, y la
pantalla de tenants contesta «esto es de quien administra la plataforma» a todo
el mundo, incluido quien administra la plataforma.

Lo resuelve el fichero de entorno y no una pantalla, por lo mismo que en el
resto de la casa: el primer día no hay nadie dentro que pueda crear a nadie.
`SUPERADMIN_EMAIL` y `SUPERADMIN_PASSWORD` se aplican **en cada arranque**,
contraseña incluida —si cambian en el fichero es porque se quieren cambiar— y
la cuenta vive en su propio tenant, para que quien opera no acabe mirando los
datos de un cliente por haberse quedado dentro de su empresa.

Es idempotente: se puede correr en cada despliegue sin mirar si ya está.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from uuid import UUID

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "packages" / "crmcore"))

# Contraseñas de ejemplo. Si alguna llega a un despliegue de verdad, la cuenta
# más poderosa del sistema tiene una contraseña pública.
INSEGURAS = {
    "",
    "CHANGE_ME",
    "CHANGE_ME_SUPERADMIN_PASSWORD",
    "changeme",
    "admin",
    "password",
    "contecrm",
}


def _cambiar_a(servicio: str) -> None:
    """Apunta el proceso al esquema y al rol de ese servicio."""
    from crmcore.config import limpiar_cache_settings
    from crmcore.db.session import reset_engine

    os.environ["SERVICE_NAME"] = servicio
    limpiar_cache_settings()
    reset_engine()


def _tenant_de_plataforma(slug: str, nombre: str) -> UUID:
    """El tenant propio del operador. Se crea si no está."""
    _cambiar_a("tenancy")
    from crmcore.db.uow import unidad_de_trabajo
    from crmcore.tenancy.context import contexto_sistema
    from sqlalchemy import select

    from services.tenancy import servicio as svc
    from services.tenancy.modelos import Plan, Tenant

    with contexto_sistema(origen="arranque"), unidad_de_trabajo(sistema=True) as uow:
        existente = uow.db.execute(select(Tenant).where(Tenant.slug == slug)).scalar_one_or_none()
        if existente:
            return existente.id
        plan = uow.db.execute(select(Plan).where(Plan.codigo == "plataforma")).scalar_one_or_none()
        if plan is None:
            uow.db.add(
                Plan(
                    codigo="plataforma",
                    nombre="Operación de la plataforma",
                    descripcion=(
                        "El tenant de quien explota contecrm. No es un cliente: no "
                        "lleva datos de negocio, solo la cuenta que administra el resto"
                    ),
                    capacidades={},
                    cuotas={},
                )
            )
            uow.db.flush()
        tenant = svc.crear_tenant(uow, slug=slug, nombre=nombre, plan="plataforma")
        print(f"Tenant de plataforma «{slug}» creado: {tenant.id}")
        return tenant.id


def _preguntar_el_tenant(slug: str) -> UUID | None:
    """El identificador del tenant, preguntándoselo a `tenancy` por dentro.

    `identity` no puede leer el esquema de `tenancy` —cada servicio tiene su
    propio rol de base de datos y esa separación es la que sostiene el
    aislamiento—, así que se usa el mismo extremo interno que ya emplea la
    pantalla de acceso para traducir «ficosa» a un identificador. Se reintenta
    porque en un arranque conjunto puede que `tenancy` aún no escuche.
    """
    import time

    from crmcore.errors import NoDisponible
    from crmcore.http.interno import pedir

    for intento in range(1, 11):
        try:
            respuesta = pedir("tenancy", f"/api/v1/interno/tenants/por-slug/{slug}")
        except NoDisponible:
            respuesta = None
        if respuesta and respuesta.get("tenant_id"):
            return UUID(str(respuesta["tenant_id"]))
        if intento < 10:
            print(f"  esperando a que «tenancy» publique el tenant «{slug}» ({intento}/10)…")
            time.sleep(3)
    return None


def _cuenta(tenant_id: UUID, email: str, contrasena: str, nombre: str) -> str:
    """Crea o reajusta la cuenta. Devuelve qué se ha hecho."""
    _cambiar_a("identity")
    from crmcore.db.uow import unidad_de_trabajo
    from crmcore.tenancy.context import con_contexto
    from sqlalchemy import select

    from services.identity import servicio as svc
    from services.identity.modelos import Membresia, Usuario

    with con_contexto(tenant_id=tenant_id, origen="arranque"), unidad_de_trabajo(tenant_id) as uow:
        usuario = uow.db.execute(select(Usuario).where(Usuario.email == email)).scalar_one_or_none()
        if usuario is None:
            usuario = svc.crear_usuario(
                uow,
                email=email,
                nombre=nombre,
                tenant_id=tenant_id,
                roles=["admin"],
                contrasena=contrasena,
                via="arranque",
            )
            hecho = "creada"
        else:
            # El fichero manda: la contraseña se reajusta en cada arranque. Una
            # cuenta con esta potencia no puede quedar con una clave que nadie
            # recuerda haber puesto.
            usuario.hash_contrasena = svc.hashear_contrasena(contrasena)
            usuario.intentos_fallidos = 0
            usuario.bloqueado_hasta = None
            hecho = "actualizada"

        usuario.activo = True
        usuario.nombre = nombre
        usuario.es_plataforma = True

        membresia = uow.db.execute(
            select(Membresia).where(
                Membresia.usuario_id == usuario.id, Membresia.tenant_id == tenant_id
            )
        ).scalar_one_or_none()
        if membresia is None:
            uow.db.add(Membresia(tenant_id=tenant_id, usuario_id=usuario.id, roles=["admin"]))
        elif "admin" not in (membresia.roles or []):
            membresia.roles = [*(membresia.roles or []), "admin"]
        uow.db.flush()
        return hecho


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--comprobar",
        action="store_true",
        help="solo dice si la cuenta está bien configurada; no toca nada",
    )
    # Cada servicio tiene su propio rol de base de datos, así que la parte de
    # `tenancy` y la de `identity` corren donde cada una tiene permisos. Es lo
    # mismo que hace `sembrar_empresa.py` y por la misma razón: un rol capaz de
    # escribir en los dos esquemas sería un rol que se salta el aislamiento.
    parser.add_argument("--parte", default="todo", choices=("todo", "tenant", "cuenta"))
    parser.add_argument("--tenant-id", default="", help="para la parte «cuenta»")
    cfg = parser.parse_args()

    from crmcore.config import get_settings

    ajustes = get_settings()
    email = (ajustes.superadmin_email or "").strip()
    contrasena = ajustes.superadmin_password.get_secret_value()

    if not email:
        print(
            "SUPERADMIN_EMAIL está vacío: esta instalación no tiene a nadie que "
            "pueda administrar la plataforma. Ponlo en el .env."
        )
        return 1
    # El correo se valida aquí con el mismo validador que la pantalla de
    # acceso: sin esto se creaba la cuenta y luego no podía entrar, porque
    # dominios como `.local` son reservados y el validador los rechaza. Una
    # cuenta de administración que existe y no entra es peor que no tenerla.
    try:
        from email_validator import validate_email

        validate_email(email, check_deliverability=False)
    except Exception as error:  # noqa: BLE001 - el motivo se enseña tal cual
        print(f"SUPERADMIN_EMAIL «{email}» no es una dirección con la que se pueda entrar: {error}")
        return 1
    if contrasena in INSEGURAS:
        print(
            "SUPERADMIN_PASSWORD está vacía o es una de ejemplo. Es la cuenta "
            "con más poder del sistema: ponle una de verdad en el .env."
        )
        return 1
    if cfg.comprobar:
        print(f"Cuenta de arranque configurada: {email} (tenant «{ajustes.superadmin_tenant}»)")
        return 0

    if cfg.parte in ("todo", "tenant"):
        tenant_id = _tenant_de_plataforma(ajustes.superadmin_tenant, ajustes.superadmin_nombre)
        if cfg.parte == "tenant":
            # Lo escribe para que quien encadena las dos partes pueda pasarlo.
            print(f"tenant_id={tenant_id}")
            return 0
    elif cfg.tenant_id:
        tenant_id = UUID(cfg.tenant_id)
    else:
        encontrado = _preguntar_el_tenant(ajustes.superadmin_tenant)
        if encontrado is None:
            print(
                f"No se ha podido resolver el tenant «{ajustes.superadmin_tenant}». "
                "Arranca antes «tenancy», o pasa --tenant-id."
            )
            return 1
        tenant_id = encontrado

    hecho = _cuenta(tenant_id, email, contrasena, ajustes.superadmin_nombre)
    print(
        f"Cuenta de plataforma {hecho}: {email} · empresa «{ajustes.superadmin_tenant}» · "
        "entra con esos tres datos en la pantalla de acceso."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
