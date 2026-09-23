#!/usr/bin/env python3
"""Siembra un tenant de demostración con datos coherentes.

    python scripts/sembrar_demo.py                  # todo (desarrollo local)
    python scripts/sembrar_demo.py --parte tenant   # desde el contenedor tenancy
    python scripts/sembrar_demo.py --parte usuario  # desde el contenedor identity
    python scripts/sembrar_demo.py --parte party    # desde el contenedor party
    python scripts/sembrar_demo.py --parte sales    # desde el contenedor sales

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


# Datos de la demostración. Coherentes entre sí a propósito (CRM-07.04.05.03):
# los contactos pertenecen a las cuentas, las oportunidades también, y las
# actividades cuelgan de algo. Un tenant de muestra con registros sueltos no
# sirve para enseñar el sistema, porque justo lo que hay que enseñar es cómo se
# relacionan.
CUENTAS_DEMO = [
    {"nombre": "Metalúrgica del Norte, S.A.", "sector_codigo": "2511", "tier": "A"},
    {"nombre": "Distribuciones Levante, S.L.", "sector_codigo": "4690", "tier": "B"},
    {"nombre": "Clínica Sanitas Vallés", "sector_codigo": "8610", "tier": "B"},
    {"nombre": "Transportes Arruti", "sector_codigo": "4941", "tier": "C"},
]

CONTACTOS_DEMO = [
    (
        "Metalúrgica del Norte, S.A.",
        "Ana",
        "Bermúdez",
        "ana.bermudez@metalnorte.example",
        "Directora de compras",
    ),
    (
        "Metalúrgica del Norte, S.A.",
        "Luis",
        "Onaindía",
        "luis.onaindia@metalnorte.example",
        "Jefe de planta",
    ),
    ("Distribuciones Levante, S.L.", "Marta", "Ferrer", "marta.ferrer@dlevante.example", "Gerente"),
    (
        "Clínica Sanitas Vallés",
        "Jordi",
        "Puig",
        "jordi.puig@sanitasvalles.example",
        "Responsable de compras",
    ),
]

OPORTUNIDADES_DEMO = [
    ("Metalúrgica del Norte, S.A.", "Renovación de la línea de corte", 185_000),
    ("Distribuciones Levante, S.L.", "Ampliación de flota refrigerada", 92_500),
    ("Clínica Sanitas Vallés", "Equipamiento de quirófano", 240_000),
]

LEADS_DEMO = [
    ("Bodegas Ribera Alta", "Elena", "Casal", "elena.casal@riberalta.example"),
    ("Talleres Mecánicos Sur", "Paco", "Ramos", "paco.ramos@tmsur.example"),
]


def _sembrar_party(tenant_id: UUID) -> None:
    """Cuentas, contactos y actividades. Corre donde `party` tiene permisos."""
    os.environ["SERVICE_NAME"] = "party"
    from crmcore.config import limpiar_cache_settings
    from crmcore.db.session import reset_engine

    limpiar_cache_settings()
    reset_engine()

    from datetime import datetime, timedelta, timezone

    from crmcore.db.uow import unidad_de_trabajo
    from crmcore.tenancy.context import con_contexto
    from sqlalchemy import select

    from services.party import servicio as svc_party
    from services.party.modelos import Cuenta

    with con_contexto(tenant_id=tenant_id, origen="cli"), unidad_de_trabajo(tenant_id) as uow:
        if uow.db.execute(select(Cuenta).limit(1)).scalar_one_or_none():
            print("Ya hay cuentas en este tenant. No se toca nada.")
            return

        por_nombre: dict[str, UUID] = {}
        for datos in CUENTAS_DEMO:
            cuenta = svc_party.crear_cuenta(uow, **datos)
            por_nombre[str(datos["nombre"])] = cuenta.id
        print(f"{len(CUENTAS_DEMO)} cuentas creadas")

        for empresa, nombre, apellidos, email, cargo in CONTACTOS_DEMO:
            svc_party.crear_contacto(
                uow,
                nombre=nombre,
                apellidos=apellidos,
                email=email,
                cargo=cargo,
                cuenta_id=por_nombre.get(empresa),
            )
        print(f"{len(CONTACTOS_DEMO)} contactos creados")

        # Una vencida y una por vencer: enseñar solo actividades al día esconde
        # justo la mitad del sistema que se nota —los avisos y los vencimientos—.
        ahora = datetime.now(timezone.utc)
        for asunto, dias, cuenta in (
            ("Llamada de seguimiento de la oferta", -3, "Metalúrgica del Norte, S.A."),
            ("Enviar propuesta revisada", 2, "Distribuciones Levante, S.L."),
            ("Visita a planta", 9, "Clínica Sanitas Vallés"),
        ):
            svc_party.crear_actividad(
                uow,
                tipo="tarea",
                asunto=asunto,
                objeto="cuenta",
                objeto_id=por_nombre.get(cuenta),
                vence_at=ahora + timedelta(days=dias),
            )
        print("3 actividades creadas (una ya vencida, para que se vea el aviso)")


# Las etapas del embudo de la demostración: clave, nombre, probabilidad, si es
# terminal y si es ganada. «Terminal» y «ganada» van por separado a propósito —
# perdida también es terminal, y confundirlas falsea cualquier ratio.
ETAPAS_DEMO = [
    ("cualificacion", "Cualificación", 10, False, False),
    ("propuesta", "Propuesta enviada", 40, False, False),
    ("negociacion", "Negociación", 70, False, False),
    ("ganada", "Ganada", 100, True, True),
    ("perdida", "Perdida", 0, True, False),
]


def _sembrar_sales(tenant_id: UUID) -> None:
    """Leads y oportunidades. Corre donde `sales` tiene permisos.

    Las oportunidades se atan a las cuentas **por nombre**, porque `sales` no
    puede leer el esquema de `party` para buscar sus identificadores — que es el
    aislamiento funcionando. Si la cuenta no se encuentra, la oportunidad se
    crea sin ella y se dice: una demo a medias que lo avisa es útil; una que
    finge estar completa, no.
    """
    os.environ["SERVICE_NAME"] = "sales"
    from crmcore.config import limpiar_cache_settings
    from crmcore.db.session import reset_engine

    limpiar_cache_settings()
    reset_engine()

    from decimal import Decimal

    from crmcore.db.uow import unidad_de_trabajo
    from crmcore.tenancy.context import con_contexto
    from sqlalchemy import select

    from services.sales import servicio as svc_sales
    from services.sales.modelos import Etapa, Lead, Oportunidad, Pipeline

    with con_contexto(tenant_id=tenant_id, origen="cli"), unidad_de_trabajo(tenant_id) as uow:
        # El pipeline va PRIMERO. Una oportunidad no se puede crear sin él
        # —`crear_oportunidad_nueva` busca el pipeline por defecto y, si no lo
        # hay, se niega—, y este sembrador no lo creaba: los leads entraban, la
        # primera oportunidad reventaba con «No hay ningún pipeline
        # configurado», y el tenant de demostración se quedaba con la mitad de
        # los datos. Peor todavía: el corte de idempotencia miraba solo si había
        # leads, así que al volver a ejecutarlo decía «ya hay leads, no se toca
        # nada» y la demo se quedaba coja para siempre.
        pipeline = uow.db.execute(
            select(Pipeline).where(Pipeline.tenant_id == tenant_id).limit(1)
        ).scalar_one_or_none()
        if pipeline is None:
            pipeline = Pipeline(
                tenant_id=tenant_id,
                clave="estandar",
                nombre="Venta estándar",
                descripcion="El embudo de la demostración, de cualificación a cierre.",
                activo=True,
                por_defecto=True,
            )
            uow.db.add(pipeline)
            uow.db.flush()
            for orden, (clave, nombre_etapa, prob, terminal, ganada) in enumerate(ETAPAS_DEMO):
                uow.db.add(
                    Etapa(
                        tenant_id=tenant_id,
                        pipeline_id=pipeline.id,
                        clave=clave,
                        nombre=nombre_etapa,
                        orden=orden,
                        probabilidad=prob,
                        terminal=terminal,
                        ganada=ganada,
                    )
                )
            uow.db.flush()
            print(f"Pipeline «{pipeline.nombre}» con {len(ETAPAS_DEMO)} etapas creado")

        # Cada bloque mira lo suyo. Un único corte al principio daba por hecho
        # que si existía lo primero existía todo lo demás, y eso es justo lo que
        # no se cumple cuando una ejecución anterior se quedó a medias.
        if uow.db.execute(select(Lead).limit(1)).scalar_one_or_none():
            print("Ya hay leads en este tenant. No se tocan.")
        else:
            for empresa, nombre, apellidos, email in LEADS_DEMO:
                svc_sales.crear_lead(
                    uow, nombre=nombre, apellidos=apellidos, empresa=empresa, email=email
                )
            print(f"{len(LEADS_DEMO)} leads creados")

        if uow.db.execute(select(Oportunidad).limit(1)).scalar_one_or_none():
            print("Ya hay oportunidades en este tenant. No se tocan.")
        else:
            for _empresa, nombre, importe in OPORTUNIDADES_DEMO:
                svc_sales.crear_oportunidad_nueva(uow, nombre=nombre, importe=Decimal(importe))
            print(f"{len(OPORTUNIDADES_DEMO)} oportunidades creadas")


def main() -> int:
    from crmcore.config import get_settings

    parte = _parte_pedida()
    if parte not in ("tenant", "usuario", "party", "sales", "todo"):
        print(
            f"Parte desconocida: «{parte}» (usa tenant|usuario|party|sales|todo)",
            file=sys.stderr,
        )
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

    if parte in ("usuario", "party", "sales"):
        valor = os.environ.get("TENANT_DEMO", "")
        if not valor:
            print(
                "Falta TENANT_DEMO con el identificador del tenant. Lo imprime "
                "`--parte tenant`.",
                file=sys.stderr,
            )
            return 2
        tenant_id = UUID(valor)
        {"usuario": _sembrar_usuario, "party": _sembrar_party, "sales": _sembrar_sales}[parte](
            tenant_id
        )
        return 0
    tenant_id = _sembrar_tenant()
    _sembrar_usuario(tenant_id)
    # En local un solo proceso llega a todos los esquemas. En un despliegue real
    # no, y por eso cada parte se puede ejecutar por separado donde tiene
    # permisos: no es una comodidad, es el aislamiento entre servicios.
    _sembrar_party(tenant_id)
    _sembrar_sales(tenant_id)

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
