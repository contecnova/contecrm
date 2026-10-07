"""Alta autoservicio de un tenant (CRM-00.01.03.01).

El enunciado pide provisioning «API + autoservicio», y hasta hoy sólo existía la
API: `POST /tenants` exige administrador de la plataforma. `ONBOARDING_ENABLED`
estaba en la configuración prometiendo abrir la otra mitad, y no la leía nadie
— ponerlo a `true` no abría nada.

Lo que un alta pública tiene que resolver, y por qué cada decisión:

**Nada existe hasta que alguien demuestra que es suyo ese correo.** No se crea
el tenant al pedirlo: se guarda la SOLICITUD y se manda un enlace. Crear primero
y activar después dejaría el sistema lleno de tenants a medias con los slugs
buenos cogidos, y un slug es permanente — va en subdominios y en URLs.

**El correo no se confirma a sí mismo.** El enlace lleva un token que aquí se
guarda **hasheado**: quien lea la base no puede usar lo que está pendiente. Es
el mismo patrón que los enlaces de restablecer contraseña, y por el mismo
motivo.

**La respuesta es la misma exista o no el slug.** Si se distinguieran, esto sería
un comprobador de qué empresas son clientes — se pide un slug, se mira la
respuesta, y ya se sabe. Lo que sí se hace es anotar el choque para quien vigile
la instalación.

**Un solo uso y con caducidad.** Un enlace que vale siempre es una credencial
permanente en el buzón de alguien.

**No se crea el administrador desde aquí.** Los usuarios son de `identity` y los
servicios no se llaman entre sí: al confirmar se emite un hecho y `identity` lo
recoge. Hacerlo por llamada ataría el alta a que el otro servicio esté en pie
justo en ese segundo, que es el peor momento para que un alta falle.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from crmcore.db.base import Base
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import ErrorValidacion, NoEncontrado, Prohibido

# El hecho que recoge `identity`, declarado en el catálogo común: los dos
# servicios tienen que llamarlo igual, y una cadena escrita dos veces diverge.
from crmcore.events.dominio import ALTA_CONFIRMADA
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import Boolean, DateTime, Index, String, select
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

logger = get_logger(__name__)


class AltaPendiente(Base):
    """Una solicitud de alta esperando a que confirmen el correo."""

    __tablename__ = "altas_pendientes"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    slug: Mapped[str] = mapped_column(String(63), nullable=False, index=True)
    nombre_empresa: Mapped[str] = mapped_column(String(200), nullable=False)
    # Dato personal: es el correo de una persona concreta y dice que quiso dar
    # de alta esta empresa.
    email: Mapped[str] = mapped_column(
        String(320), nullable=False, index=True, info={"sensibilidad": "personal"}
    )
    nombre_persona: Mapped[str] = mapped_column(String(200), nullable=False)
    # Hasheado, nunca el token. Quien lea la base no puede confirmar un alta
    # ajena. Mismo criterio que los enlaces de restablecer.
    hash_token: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True, info={"secreto": True}
    )
    caduca_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    usado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Desde dónde se pidió. Personal por lo mismo que en los restablecimientos:
    # una IP identifica a una persona lo bastante como para tratarla así.
    ip_solicitud: Mapped[str | None] = mapped_column(
        String(64), nullable=True, info={"sensibilidad": "personal"}
    )
    # Si el slug ya estaba cogido. Quien pide no lo sabe —la respuesta es la
    # misma— pero quien vigila la instalación necesita ver que alguien está
    # probando nombres de empresa.
    slug_libre: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # NO se llama `tenant_id` a propósito: no es el discriminador de tenant de
    # esta fila —esta fila es de antes de que exista ninguno— sino a qué tenant
    # acabó dando lugar. Llamarlo `tenant_id` haría que el gate de arquitectura
    # lo tratara como el de las demás tablas y pidiera que no fuera nulo y que
    # encabezara un índice, y las dos cosas serían mentira aquí.
    tenant_creado_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (Index("ix_altas_pendientes_vivas", "slug", "usado_at"),)


def _ahora() -> datetime:
    """El instante, en UTC: una caducidad no es «el día de nadie»."""
    return datetime.now(timezone.utc)


def _hash(valor: str) -> str:
    return hashlib.sha256(valor.encode("utf-8")).hexdigest()


def _exigir_activo() -> None:
    """Corta si esta instalación no ofrece alta autoservicio.

    Apagado de fábrica: un despliegue empresarial da de alta a sus clientes por
    API o por consola, y dejar abierta un alta pública en una instalación
    privada es una superficie regalada.
    """
    from crmcore.config import get_settings

    if get_settings().onboarding_enabled:
        return
    raise Prohibido(
        "Esta instalación no admite altas por autoservicio. " "Se enciende con ONBOARDING_ENABLED.",
        error_code="alta.autoservicio_desactivado",
    )


def solicitar(
    uow: UnidadDeTrabajo,
    *,
    slug: str,
    nombre_empresa: str,
    email: str,
    nombre_persona: str,
    ip: str = "",
) -> str:
    """Apunta la solicitud y devuelve el token del enlace de confirmación.

    **La respuesta de la ruta es la misma exista o no el slug**, y por eso esta
    función no lanza cuando está cogido: anota el choque y devuelve un token que
    al confirmarse dirá que no se pudo. Lanzar aquí convertiría la pantalla de
    alta en un comprobador de qué empresas son clientes.

    El token se **devuelve** para que lo mande quien integre el correo; nunca se
    le enseña a quien lo pide. Mismo trato que los enlaces de restablecer.
    """
    from crmcore.config import get_settings

    from services.tenancy.modelos import Tenant
    from services.tenancy.servicio import RE_SLUG, SLUGS_RESERVADOS

    _exigir_activo()

    slug = slug.strip().lower()
    # La FORMA sí se valida y sí se dice: no filtra nada —no depende de qué haya
    # en la base— y callarla dejaría a alguien escribiendo mayúsculas sin saber
    # por qué no le llega el correo nunca.
    if not RE_SLUG.match(slug):
        raise ErrorValidacion(
            "El identificador debe tener entre 2 y 63 caracteres, en minúsculas, "
            "y solo letras, números o guiones (no al principio ni al final)",
            error_code="tenant.slug_invalido",
        )

    libre = (
        slug not in SLUGS_RESERVADOS
        and not uow.db.execute(select(Tenant.id).where(Tenant.slug == slug)).first()
    )

    token = secrets.token_urlsafe(32)
    horas = int(get_settings().onboarding_enlace_horas)
    uow.db.add(
        AltaPendiente(
            slug=slug,
            nombre_empresa=nombre_empresa.strip(),
            email=email.strip().lower(),
            nombre_persona=nombre_persona.strip(),
            hash_token=_hash(token),
            caduca_at=_ahora() + timedelta(hours=horas),
            ip_solicitud=ip or None,
            slug_libre=libre,
        )
    )
    uow.db.flush()
    # Se anota el choque para quien vigila, no para quien pide: alguien probando
    # nombres de empresa uno detrás de otro se ve aquí y no en la respuesta.
    logger.info("alta.solicitada", slug=slug, slug_libre=libre, ip=ip or None)
    return token


def confirmar(uow: UnidadDeTrabajo, token: str, *, ip: str = "") -> dict[str, Any]:
    """Gasta el token y da de alta el tenant. Devuelve qué ha quedado creado.

    Aquí sí se dice si el slug está cogido: quien llega con un token válido ha
    demostrado ser dueño de ese correo, así que ya no es un desconocido
    preguntando por la lista de clientes.

    El administrador **no se crea aquí**: se emite el hecho y lo recoge
    `identity`. Los usuarios son suyos, y los servicios no se llaman entre sí.
    """
    from services.tenancy.servicio import crear_tenant

    _exigir_activo()

    fila = uow.db.execute(
        select(AltaPendiente).where(AltaPendiente.hash_token == _hash(token))
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado(
            "Ese enlace no vale. Pide el alta otra vez.",
            error_code="alta.enlace_desconocido",
        )
    # Las tres condiciones por separado, con su mensaje: «no vale» a secas deja
    # a alguien reintentando con el mismo enlace caducado toda la mañana.
    if fila.usado_at is not None:
        raise ErrorValidacion(
            "Ese enlace ya se usó. Si no fue usted, pida el alta otra vez.",
            error_code="alta.enlace_usado",
        )
    if fila.caduca_at <= _ahora():
        raise ErrorValidacion(
            "Ese enlace ha caducado. Pida el alta otra vez.",
            error_code="alta.enlace_caducado",
        )

    # El slug se vuelve a comprobar AQUÍ y no vale el de la solicitud: entre
    # pedirlo y confirmarlo pueden pasar horas, y en ese rato puede haberlo
    # cogido otro. Fiarse de `slug_libre` daría dos tenants con el mismo
    # subdominio, que es un estropicio permanente.
    fila.usado_at = _ahora()
    tenant = crear_tenant(uow, slug=fila.slug, nombre=fila.nombre_empresa)
    fila.tenant_creado_id = tenant.id

    uow.emitir(
        ALTA_CONFIRMADA,
        subject=("tenant", tenant.id),
        data={
            "tenant_id": str(tenant.id),
            "slug": tenant.slug,
            "email": fila.email,
            "nombre": fila.nombre_persona,
        },
    )
    logger.info("alta.confirmada", slug=fila.slug, tenant_id=str(tenant.id), ip=ip or None)
    return {"tenant_id": str(tenant.id), "slug": tenant.slug, "nombre": tenant.nombre}


def purgar(db: Session, *, dias: int) -> int:
    """Olvida las solicitudes viejas, usadas o no.

    Una tabla de solicitudes pendientes crece con cada intento, incluidos los de
    quien prueba nombres: sin esto sería la tabla más grande del esquema y llena
    de correos de gente que nunca llegó a ser cliente, que además es dato
    personal que no hay motivo para guardar.
    """
    from sqlalchemy import delete

    corte = _ahora() - timedelta(days=dias)
    res = db.execute(delete(AltaPendiente).where(AltaPendiente.created_at < corte))
    return int(res.rowcount or 0)
