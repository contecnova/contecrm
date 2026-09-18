"""Lógica del servicio de tenancy.

Aquí vive lo que responde a «¿existe, está operativo, qué puede usar y cuánto
lleva gastado?». Los routers de `api.py` solo traducen HTTP; toda la decisión
está en este módulo, que es lo que permite que la misma lógica la use un
consumidor del bus o un trabajo de fondo sin duplicarla.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from crmcore.audit.chain import registrar
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado, Prohibido
from crmcore.logging import get_logger
from services.tenancy.modelos import Consumo, FeatureFlag, Plan, Tenant, UnidadNegocio

logger = get_logger(__name__)

# Un slug va en subdominios y en URLs: se limita a lo que es válido en un nombre
# de host, y se prohíben los que colisionarían con subdominios de servicio.
RE_SLUG = re.compile(r"^[a-z0-9]([a-z0-9-]{1,61}[a-z0-9])?$")
SLUGS_RESERVADOS = frozenset(
    {"www", "api", "app", "admin", "gateway", "status", "docs", "mail", "smtp", "ns"}
)

# Estados y las transiciones permitidas. Se declara la máquina entera en vez de
# comprobar caso por caso: así se puede enseñar, y añadir un estado obliga a
# decir desde dónde se llega a él.
TRANSICIONES: dict[str, frozenset[str]] = {
    "activo": frozenset({"suspendido", "solo_lectura", "en_baja"}),
    "suspendido": frozenset({"activo", "solo_lectura", "en_baja"}),
    "solo_lectura": frozenset({"activo", "suspendido", "en_baja"}),
    # De `en_baja` se puede volver: una baja por error tiene que ser
    # recuperable mientras los datos sigan ahí.
    "en_baja": frozenset({"activo", "archivado"}),
    # `archivado` es terminal: los datos ya se han destruido.
    "archivado": frozenset(),
}


# ── Alta y ciclo de vida ──────────────────────────────────────────────────


def crear_tenant(
    uow: UnidadDeTrabajo,
    *,
    slug: str,
    nombre: str,
    plan: str = "base",
    region: str = "eu",
    aislamiento: str = "pool",
    tenant_padre_id: UUID | None = None,
    idioma: str = "es",
    zona_horaria: str = "Europe/Madrid",
    moneda: str = "EUR",
) -> Tenant:
    """Da de alta un tenant (CRM-00.01.03.01)."""
    slug = slug.strip().lower()
    if not RE_SLUG.match(slug):
        raise ErrorValidacion(
            "El identificador debe tener entre 2 y 63 caracteres, en minúsculas, "
            "y solo letras, números o guiones (no al principio ni al final)",
            error_code="tenant.slug_invalido",
        )
    if slug in SLUGS_RESERVADOS:
        raise ErrorValidacion(
            f"«{slug}» está reservado para uso del sistema",
            error_code="tenant.slug_reservado",
        )
    if uow.db.execute(select(Tenant.id).where(Tenant.slug == slug)).first():
        raise Conflicto(
            "Ya existe un tenant con ese identificador",
            error_code="tenant.slug_duplicado",
        )

    if tenant_padre_id and not uow.db.get(Tenant, tenant_padre_id):
        raise NoEncontrado(
            "El tenant padre indicado no existe", error_code="tenant.padre_no_encontrado"
        )

    tenant = Tenant(
        slug=slug,
        nombre=nombre.strip(),
        plan=plan,
        region=region,
        aislamiento=aislamiento,
        tenant_padre_id=tenant_padre_id,
        idioma=idioma,
        zona_horaria=zona_horaria,
        moneda=moneda,
        estado="activo",
        provisionado_at=datetime.now(timezone.utc),
    )
    uow.db.add(tenant)
    # `flush` para tener el id antes de emitir el evento: el sobre lo lleva como
    # sujeto, y sin id el consumidor no sabría de qué tenant habla.
    uow.db.flush()

    registrar(
        uow.db,
        accion="tenant.provisionado",
        objeto="tenant",
        objeto_id=tenant.id,
        datos={"slug": slug, "plan": plan, "region": region},
        tenant_id=tenant.id,
    )
    uow.emitir(
        "tenant.provisioned",
        subject=("tenant", tenant.id),
        data={
            "tenant_id": str(tenant.id),
            "slug": slug,
            "plan": plan,
            "region": region,
        },
    )
    logger.info("tenant.creado", slug=slug, plan=plan, region=region)
    return tenant


def cambiar_estado(
    uow: UnidadDeTrabajo, tenant_id: UUID, *, nuevo: str, motivo: str = ""
) -> Tenant:
    """Cambia el estado del tenant respetando la máquina de estados.

    Exige motivo para todo lo que degrada el servicio. No es burocracia: seis
    meses después, «¿por qué está suspendido este cliente?» es una pregunta
    real, y sin motivo escrito la respuesta se pierde con quien lo hizo.
    """
    tenant = uow.db.get(Tenant, tenant_id)
    if tenant is None:
        raise NoEncontrado("El tenant no existe", error_code="tenant.no_encontrado")

    if nuevo == tenant.estado:
        return tenant

    permitidos = TRANSICIONES.get(tenant.estado, frozenset())
    if nuevo not in permitidos:
        raise Conflicto(
            f"No se puede pasar de «{tenant.estado}» a «{nuevo}»",
            error_code="tenant.transicion_no_permitida",
            detalle={"desde": tenant.estado, "permitidos": sorted(permitidos)},
        )
    if nuevo in ("suspendido", "solo_lectura", "en_baja") and not motivo.strip():
        raise ErrorValidacion(
            f"Pasar a «{nuevo}» exige un motivo escrito",
            error_code="tenant.motivo_requerido",
        )

    anterior = tenant.estado
    tenant.estado = nuevo
    tenant.motivo_estado = motivo.strip() or None
    ahora = datetime.now(timezone.utc)
    if nuevo == "suspendido":
        tenant.suspendido_at = ahora
    elif nuevo == "en_baja":
        tenant.baja_solicitada_at = ahora
        # Ventana de recuperación antes de que los datos sean destruibles. Una
        # baja instantánea convierte un error administrativo en una pérdida
        # irreversible.
        tenant.datos_borrables_at = ahora + timedelta(days=30)
    elif nuevo == "activo":
        tenant.suspendido_at = None
        tenant.baja_solicitada_at = None
        tenant.datos_borrables_at = None

    registrar(
        uow.db,
        accion="tenant.estado_cambiado",
        objeto="tenant",
        objeto_id=tenant.id,
        datos={"desde": anterior, "hasta": nuevo},
        motivo=motivo or None,
        tenant_id=tenant.id,
    )
    if nuevo == "suspendido":
        uow.emitir(
            "tenant.suspended",
            subject=("tenant", tenant.id),
            data={"tenant_id": str(tenant.id), "motivo": motivo},
        )
    elif nuevo == "activo" and anterior in ("suspendido", "solo_lectura"):
        uow.emitir(
            "tenant.reactivated",
            subject=("tenant", tenant.id),
            data={"tenant_id": str(tenant.id)},
        )
    logger.info("tenant.estado", slug=tenant.slug, desde=anterior, hasta=nuevo)
    return tenant


def exigir_operativo(db: Session, tenant_id: UUID, *, escritura: bool) -> Tenant:
    """Comprueba que el tenant puede operar. Lo llama el gateway en cada petición.

    Se separan lectura y escritura porque el estado `solo_lectura` es la razón
    de ser de esta función: permite cortar las escrituras sin cortar el acceso.
    """
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise NoEncontrado("El tenant no existe", error_code="tenant.no_encontrado")
    if not tenant.puede_leer:
        from crmcore.errors import TenantSuspendido

        raise TenantSuspendido(
            f"El servicio está suspendido: {tenant.motivo_estado or 'contacta con soporte'}",
            error_code="tenant.suspendido",
        )
    if escritura and not tenant.puede_escribir:
        from crmcore.errors import SoloLectura

        raise SoloLectura(
            f"El servicio está en solo lectura: {tenant.motivo_estado or 'contacta con soporte'}",
            error_code="tenant.solo_lectura",
        )
    return tenant


# ── Planes, capacidades y flags ───────────────────────────────────────────


def capacidades_de(db: Session, tenant_id: UUID) -> dict[str, bool]:
    """Capacidades activas del tenant según su plan."""
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise NoEncontrado("El tenant no existe", error_code="tenant.no_encontrado")
    plan = db.execute(select(Plan).where(Plan.codigo == tenant.plan)).scalar_one_or_none()
    return dict(plan.capacidades) if plan else {}


def exigir_capacidad(db: Session, tenant_id: UUID, capacidad: str) -> None:
    """Lanza si el plan del tenant no incluye la capacidad."""
    if not capacidades_de(db, tenant_id).get(capacidad, False):
        raise Prohibido(
            f"Tu plan no incluye «{capacidad}»",
            error_code="plan.capacidad_no_incluida",
            # Se dice qué falta: el usuario ya sabe qué intentó, y sin el nombre
            # de la capacidad no puede ni preguntar por ella a comercial.
            detalle={"capacidad": capacidad},
        )


def flag_activo(
    db: Session, clave: str, *, tenant_id: UUID | None = None, user_id: UUID | None = None
) -> bool:
    """Resuelve un feature flag: usuario > tenant > global.

    El despliegue por porcentaje reparte por **hash** del identificador y no al
    azar: si fuera aleatorio, a un mismo usuario le aparecería y desaparecería la
    funcionalidad entre dos peticiones, que es la peor forma de probar algo.
    """
    candidatos = [
        (FeatureFlag.user_id == user_id) if user_id else None,
        (FeatureFlag.tenant_id == tenant_id) if tenant_id else None,
    ]
    for condicion in [c for c in candidatos if c is not None]:
        flag = db.execute(
            select(FeatureFlag).where(FeatureFlag.clave == clave, condicion)
        ).scalar_one_or_none()
        if flag is not None:
            return _resuelve_flag(flag, tenant_id, user_id)

    global_ = db.execute(
        select(FeatureFlag).where(
            FeatureFlag.clave == clave,
            FeatureFlag.tenant_id.is_(None),
            FeatureFlag.user_id.is_(None),
        )
    ).scalar_one_or_none()
    return _resuelve_flag(global_, tenant_id, user_id) if global_ else False


def _resuelve_flag(flag: FeatureFlag, tenant_id: UUID | None, user_id: UUID | None) -> bool:
    if flag.activo:
        return True
    if flag.porcentaje <= 0:
        return False
    if flag.porcentaje >= 100:
        return True
    semilla = f"{flag.clave}:{user_id or tenant_id or ''}"
    cubeta = int(hashlib.sha256(semilla.encode()).hexdigest()[:8], 16) % 100
    return cubeta < flag.porcentaje


# ── Cuotas y medición ─────────────────────────────────────────────────────


def _periodo(granularidad: str = "mes") -> str:
    ahora = datetime.now(timezone.utc)
    return ahora.strftime("%Y-%m") if granularidad == "mes" else ahora.strftime("%Y-%m-%d")


def medir(
    db: Session,
    tenant_id: UUID,
    metrica: str,
    cantidad: int = 1,
    *,
    granularidad: str = "mes",
) -> int:
    """Suma consumo y devuelve el acumulado del periodo (CRM-00.01.06.07).

    `ON CONFLICT DO UPDATE` en una sola sentencia: leer-y-luego-escribir perdería
    incrementos concurrentes, y con la medición de consumo eso significa facturar
    de menos sin enterarse.
    """
    periodo = _periodo(granularidad)
    fila = db.execute(
        pg_insert(Consumo)
        .values(tenant_id=tenant_id, metrica=metrica, periodo=periodo, valor=cantidad)
        .on_conflict_do_update(
            index_elements=["tenant_id", "metrica", "periodo"],
            set_={"valor": Consumo.__table__.c.valor + cantidad, "updated_at": func.now()},
        )
        .returning(Consumo.valor)
    ).scalar_one()
    return int(fila)


def consumo_actual(
    db: Session, tenant_id: UUID, metrica: str, *, granularidad: str = "mes"
) -> int:
    valor = db.execute(
        select(Consumo.valor).where(
            Consumo.tenant_id == tenant_id,
            Consumo.metrica == metrica,
            Consumo.periodo == _periodo(granularidad),
        )
    ).scalar_one_or_none()
    return int(valor or 0)


def limite_de(db: Session, tenant_id: UUID, clave_cuota: str) -> int:
    """Tope efectivo de una cuota: ajuste del tenant > plan > entorno."""
    from crmcore.runtime import settings as rt

    valor = rt.efectivo(clave_cuota, db)
    if valor is not None:
        return int(valor)
    tenant = db.get(Tenant, tenant_id)
    if tenant:
        plan = db.execute(select(Plan).where(Plan.codigo == tenant.plan)).scalar_one_or_none()
        if plan and clave_cuota in plan.cuotas:
            return int(plan.cuotas[clave_cuota])
    return 0


def comprobar_cuota(
    uow: UnidadDeTrabajo,
    tenant_id: UUID,
    *,
    metrica: str,
    clave_cuota: str,
    incremento: int = 1,
) -> dict[str, Any]:
    """Comprueba la cuota, mide el consumo y avisa al acercarse al tope.

    Mide siempre, incluso cuando no hay tope (0 = sin límite): la medición sirve
    para facturar y para dimensionar, no solo para bloquear. Un despliegue
    on-premise sin cuotas igualmente quiere saber cuánto se usa.
    """
    from crmcore.errors import CuotaAgotada
    from crmcore.runtime import settings as rt

    limite = limite_de(uow.db, tenant_id, clave_cuota)
    consumido = medir(uow.db, tenant_id, metrica, incremento)

    if limite <= 0:
        return {"limite": 0, "consumido": consumido, "pct": 0.0}

    pct = consumido / limite * 100
    if consumido > limite:
        raise CuotaAgotada(
            f"Se ha agotado la cuota de {metrica} ({consumido}/{limite})",
            error_code=f"cuota.{metrica}",
            detalle={"metrica": metrica, "consumido": consumido, "limite": limite},
        )

    umbral = int(rt.efectivo("quota_aviso_pct", uow.db) or 80)
    # El aviso se emite solo al CRUZAR el umbral, no en cada petición por encima
    # de él: si no, un tenant al 85 % generaría un evento por llamada y el aviso
    # dejaría de significar nada.
    anterior_pct = (consumido - incremento) / limite * 100
    if anterior_pct < umbral <= pct:
        uow.emitir(
            "quota.threshold.reached",
            subject=("tenant", tenant_id),
            data={
                "tenant_id": str(tenant_id),
                "cuota": metrica,
                "consumido": consumido,
                "limite": limite,
                "pct": round(pct, 1),
            },
        )
        logger.warning(
            "cuota.umbral_alcanzado", metrica=metrica, pct=round(pct, 1), limite=limite
        )
    return {"limite": limite, "consumido": consumido, "pct": round(pct, 1)}


# ── Unidades de negocio ───────────────────────────────────────────────────


def crear_unidad(
    db: Session, tenant_id: UUID, *, codigo: str, nombre: str, padre_id: UUID | None = None
) -> UnidadNegocio:
    if db.execute(
        select(UnidadNegocio.id).where(
            UnidadNegocio.tenant_id == tenant_id, UnidadNegocio.codigo == codigo
        )
    ).first():
        raise Conflicto(
            "Ya existe una unidad de negocio con ese código",
            error_code="unidad.codigo_duplicado",
        )
    unidad = UnidadNegocio(
        tenant_id=tenant_id, codigo=codigo.strip(), nombre=nombre.strip(), padre_id=padre_id
    )
    db.add(unidad)
    return unidad
