"""Audiencias sincronizadas con una plataforma publicitaria (CRM-02.01.01.09).

Hasta el 09-11-2026 `POST /audiencias-externas` sólo **preparaba** una lista
troceada y la devolvía: no se creaba nada en ninguna plataforma, no se guardaba
quién había salido y, por tanto, una baja en el CRM no podía llegar nunca a la
audiencia de fuera. Era la mitad que no compromete a nada.

Aquí está la otra mitad, y sin código de ningún proveedor: la plataforma es una
**conexión de `integration`** con tres operaciones declaradas —crear la
audiencia, añadir miembros y quitar miembros—. Cambiar de Meta a Google o a
LinkedIn es declarar otras tres operaciones, no escribir otro módulo. Marketing
habla con `integration` por HTTP; ningún servicio lee la base de otro.

Las reglas, las mismas que ya decidía `audiencias_externas` y que ahora se
cumplen de verdad:

* **sin consentimiento para esa finalidad no sale nadie** —se pregunta a `party`
  persona a persona, no por segmento—;
* **una supresión o una baja aquí es una baja allí en la siguiente
  sincronización**, y se manda primero;
* **lo que sale va troceado**, nunca en claro;
* **por debajo del mínimo no se sube nada** — ni siquiera la primera vez.

Cada sincronización queda en el historial con sus altas, sus bajas, cuántos se
quedaron fuera y por qué, y el error si lo hubo. Una audiencia que «a veces no
se actualiza» sin historial se investiga en la plataforma, donde todo está bien.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable
from uuid import UUID

from crmcore.db.base import Base, SoftDeleteMixin, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import ErrorValidacion, NoDisponible, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from services.marketing.audiencias_externas import _trocear

logger = get_logger(__name__)

ESTADOS = ("borrador", "sincronizada", "pequena", "error", "pausada")


class AudienciaPublicitaria(Base, TimestampMixin, SoftDeleteMixin):
    """Una audiencia que vive en una plataforma de anuncios."""

    __tablename__ = "audiencias_publicitarias"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    segmento_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    # La plataforma es una conexión de `integration`, no un nombre de proveedor.
    conexion_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    finalidad: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # El identificador que le dio la plataforma al crearla.
    id_externo: Mapped[str | None] = mapped_column(String(200), nullable=True)
    estado: Mapped[str] = mapped_column(
        String(20), nullable=False, default="borrador", info={"opciones": ESTADOS}
    )
    miembros: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ultima_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ultimo_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_audiencias_pub_tenant", "tenant_id", "estado"),)


class MiembroAudiencia(Base):
    """Quién está DENTRO de la audiencia de fuera, según lo último que se mandó.

    Es lo que permite mandar bajas: sin saber quién subió, no se sabe a quién
    hay que quitar, y la baja se queda en el CRM.
    """

    __tablename__ = "miembros_audiencia_publicitaria"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    audiencia_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("audiencias_publicitarias.id", ondelete="CASCADE"),
        nullable=False,
    )
    objeto_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    # Sólo el troceado: la dirección en claro no se guarda aquí.
    hash: Mapped[str] = mapped_column(String(64), nullable=False)
    dentro: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    alta_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    baja_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("audiencia_id", "objeto_id", name="uq_miembro_audiencia_pub"),
    )


class SincronizacionAudiencia(Base):
    """Una vuelta de sincronización. Sólo se añade."""

    __tablename__ = "sincronizaciones_audiencia"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    audiencia_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("audiencias_publicitarias.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    altas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bajas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sin_consentimiento: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    suprimidos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    en_el_segmento: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    detalle: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _ajuste(clave: str, db: Session | None) -> Any:
    from services.marketing.ajustes import valor

    return valor(clave, db)


# ── El puerto hacia fuera ────────────────────────────────────────────────
#
# Dos llamadas por HTTP y nada más: preguntar a `party` por el consentimiento y
# pedir a `integration` que invoque una operación de la conexión. Van en una
# función sustituible para poder probar lo que se decide con un doble, sin red.


def _invocar(**kw: Any) -> dict[str, Any]:
    from crmcore.http.interno import invocar

    return invocar(**kw)


Invocador = Callable[..., dict[str, Any]]


def _operacion(
    invocar: Invocador,
    *,
    tenant_id: UUID,
    principal_id: Any,
    conexion_id: UUID,
    clave: str,
    parametros: dict[str, Any],
) -> dict[str, Any]:
    respuesta = invocar(
        metodo="POST",
        ruta=f"/api/v1/integraciones/conexiones/{conexion_id}/operaciones/{clave}/invocar",
        cuerpo={"parametros": parametros},
        tenant_id=tenant_id,
        principal_id=principal_id,
        permisos=["integracion:invocar"],
        timeout_s=60.0,
    )
    if not respuesta.get("ok"):
        datos = respuesta.get("datos") or {}
        mensaje = datos.get("mensaje") or datos.get("detail") or datos
        raise NoDisponible(
            f"La plataforma no ha aceptado «{clave}» (HTTP {respuesta.get('estado')}): {mensaje}"[
                :500
            ],
            error_code="audiencia.plataforma_rechaza",
        )
    return dict(respuesta.get("datos") or {})


def _consentimiento(
    invocar: Invocador,
    *,
    tenant_id: UUID,
    principal_id: Any,
    contacto_id: UUID,
    finalidad: str,
    canal: str,
) -> bool:
    """Si esta persona consintió ESA finalidad. Lo dice `party`, que es quien lo guarda.

    Sin respuesta no se manda: no poder preguntar no es un «sí».
    """
    respuesta = invocar(
        metodo="GET",
        ruta=f"/api/v1/contacts/{contacto_id}/puede-contactar",
        parametros={"finalidad": finalidad, "canal": canal},
        tenant_id=tenant_id,
        principal_id=principal_id,
        permisos=["contact:read"],
        timeout_s=10.0,
    )
    if respuesta.get("estado") == 404:
        return False
    if not respuesta.get("ok"):
        raise NoDisponible(
            "No se ha podido preguntar a party por el consentimiento: sin respuesta no "
            "se sube a nadie.",
            error_code="audiencia.consentimiento_sin_respuesta",
        )
    return bool((respuesta.get("datos") or {}).get("puede"))


# ── Alta ──────────────────────────────────────────────────────────────────


def crear(
    uow: UnidadDeTrabajo,
    *,
    nombre: str,
    segmento_id: UUID,
    conexion_id: UUID,
    finalidad: str = "",
) -> AudienciaPublicitaria:
    from services.marketing.modelos import Segmento

    segmento = uow.db.get(Segmento, segmento_id)
    if segmento is None or segmento.tenant_id != uow.tenant_id:
        raise NoEncontrado("Ese segmento no existe", error_code="audiencia.segmento_no_existe")
    fila = AudienciaPublicitaria(
        tenant_id=uow.tenant_id,
        nombre=nombre.strip(),
        segmento_id=segmento_id,
        conexion_id=conexion_id,
        finalidad=finalidad.strip(),
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila


def _audiencia(db: Session, tenant_id: UUID, audiencia_id: UUID) -> AudienciaPublicitaria:
    fila = db.get(AudienciaPublicitaria, audiencia_id)
    if fila is None or fila.tenant_id != tenant_id or fila.deleted_at is not None:
        raise NoEncontrado("Esa audiencia no existe", error_code="audiencia.no_existe")
    return fila


# ── Sincronizar ───────────────────────────────────────────────────────────


def _lotes(lista: list[str], tamano: int) -> list[list[str]]:
    return [lista[i : i + tamano] for i in range(0, len(lista), max(1, tamano))]


def sincronizar(
    uow: UnidadDeTrabajo,
    audiencia_id: UUID,
    *,
    principal_id: Any,
    invocar: Invocador | None = None,
) -> dict[str, Any]:
    """Deja la audiencia de fuera igual que el segmento de dentro, con sus reglas.

    En este orden, que importa: **primero las bajas** —quien se dio de baja o
    perdió el consentimiento deja de ver anuncios antes de que se añada a nadie—,
    después la creación si hace falta, y después las altas. Si las altas fallan,
    las bajas ya han salido.
    """
    from services.marketing.modelos import PerfilMarketing
    from services.marketing.segmentos import filtrar_suprimidos, miembros

    llamar = invocar or _invocar
    db = uow.db
    tenant_id = uow.tenant_id
    audiencia = _audiencia(db, tenant_id, audiencia_id)
    finalidad = str(_ajuste("audiencia_finalidad", db) or "perfilado")
    canal = str(_ajuste("audiencia_canal_consentimiento", db) or "email")
    minimo = int(_ajuste("audiencia_minimo", db) or 100)
    lote = int(_ajuste("audiencia_lote", db) or 1000)
    op_crear = str(_ajuste("audiencia_op_crear", db) or "crear_audiencia")
    op_anadir = str(_ajuste("audiencia_op_anadir", db) or "anadir_miembros")
    op_quitar = str(_ajuste("audiencia_op_quitar", db) or "quitar_miembros")

    registro = SincronizacionAudiencia(
        tenant_id=tenant_id, audiencia_id=audiencia.id, por=_uuid_o_nada(principal_id)
    )
    db.add(registro)

    try:
        ids = miembros(db, tenant_id, audiencia.segmento_id)
        registro.en_el_segmento = len(ids)
        alcanzables, suprimidos = filtrar_suprimidos(db, tenant_id, "contacto", ids)
        registro.suprimidos = len(suprimidos)
        correos = dict(
            db.execute(
                select(PerfilMarketing.objeto_id, PerfilMarketing.email).where(
                    PerfilMarketing.tenant_id == tenant_id,
                    PerfilMarketing.objeto_id.in_(alcanzables or [nuevo_id()]),
                )
            ).all()
        )
        deseados: dict[UUID, str] = {}
        sin_consentimiento = 0
        for objeto_id in alcanzables:
            if not _consentimiento(
                llamar,
                tenant_id=tenant_id,
                principal_id=principal_id,
                contacto_id=objeto_id,
                finalidad=finalidad,
                canal=canal,
            ):
                sin_consentimiento += 1
                continue
            deseados[objeto_id] = _trocear(str(correos.get(objeto_id) or ""))
        registro.sin_consentimiento = sin_consentimiento

        actuales = {
            m.objeto_id: m
            for m in db.execute(
                select(MiembroAudiencia).where(
                    MiembroAudiencia.audiencia_id == audiencia.id,
                    MiembroAudiencia.dentro.is_(True),
                )
            ).scalars()
        }
        salen = [m for oid, m in actuales.items() if oid not in deseados]
        entran = {oid: h for oid, h in deseados.items() if oid not in actuales}

        # 1. Las bajas, primero y aunque la audiencia vaya a quedarse pequeña.
        if salen and audiencia.id_externo:
            for trozo in _lotes([m.hash for m in salen], lote):
                _operacion(
                    llamar,
                    tenant_id=tenant_id,
                    principal_id=principal_id,
                    conexion_id=audiencia.conexion_id,
                    clave=op_quitar,
                    parametros={"audiencia_id": audiencia.id_externo, "miembros": trozo},
                )
        for m in salen:
            m.dentro = False
            m.baja_at = _ahora()
        registro.bajas = len(salen) if audiencia.id_externo else 0

        # 2. Pequeña: no se sube nadie más. Lo que había ya salió por las bajas.
        if len(deseados) < minimo:
            audiencia.estado = "pequena"
            audiencia.miembros = len(deseados) - len(entran)
            registro.detalle = {
                "porque": (
                    f"Sólo {len(deseados)} personas pueden ir y el mínimo es {minimo}. Por "
                    "debajo, la plataforma no puede anonimizar nada y la audiencia se "
                    "convierte en señalar a alguien."
                )
            }
            audiencia.ultima_sync_at = _ahora()
            audiencia.ultimo_error = None
            db.flush()
            return _resumen(audiencia, registro)

        # 3. Crear la audiencia fuera, la primera vez.
        if not audiencia.id_externo:
            datos = _operacion(
                llamar,
                tenant_id=tenant_id,
                principal_id=principal_id,
                conexion_id=audiencia.conexion_id,
                clave=op_crear,
                parametros={"nombre": audiencia.nombre, "finalidad": audiencia.finalidad},
            )
            primero = (datos.get("registros") or [{}])[0] or {}
            externo = primero.get("id_externo") or primero.get("id")
            if not externo:
                raise NoDisponible(
                    "La plataforma ha creado la audiencia y no ha devuelto su "
                    "identificador: sin él no se le pueden mandar altas ni bajas. Revisa "
                    f"el mapeo de la operación «{op_crear}» (campo «id_externo»).",
                    error_code="audiencia.sin_id_externo",
                )
            audiencia.id_externo = str(externo)

        # 4. Las altas.
        for trozo in _lotes(list(entran.values()), lote):
            _operacion(
                llamar,
                tenant_id=tenant_id,
                principal_id=principal_id,
                conexion_id=audiencia.conexion_id,
                clave=op_anadir,
                parametros={"audiencia_id": audiencia.id_externo, "miembros": trozo},
            )
        previos = {
            m.objeto_id: m
            for m in db.execute(
                select(MiembroAudiencia).where(
                    MiembroAudiencia.audiencia_id == audiencia.id,
                    MiembroAudiencia.objeto_id.in_(list(entran) or [nuevo_id()]),
                )
            ).scalars()
        }
        for objeto_id, hash_ in entran.items():
            fila = previos.get(objeto_id)
            if fila is None:
                db.add(
                    MiembroAudiencia(
                        tenant_id=tenant_id,
                        audiencia_id=audiencia.id,
                        objeto_id=objeto_id,
                        hash=hash_,
                    )
                )
            else:
                fila.dentro, fila.hash, fila.baja_at, fila.alta_at = True, hash_, None, _ahora()
        registro.altas = len(entran)
        audiencia.miembros = len(deseados)
        audiencia.estado = "sincronizada"
        audiencia.ultimo_error = None
    except (NoDisponible, ErrorValidacion, NoEncontrado) as exc:
        registro.ok = False
        registro.error = str(exc.mensaje)[:2000]
        audiencia.estado = "error"
        audiencia.ultimo_error = registro.error
        logger.warning("audiencia.sincronizacion_fallida", error=registro.error[:200])
    audiencia.ultima_sync_at = _ahora()
    db.flush()
    return _resumen(audiencia, registro)


def _uuid_o_nada(valor: Any) -> UUID | None:
    try:
        return UUID(str(valor))
    except (TypeError, ValueError):
        return None


def _resumen(audiencia: AudienciaPublicitaria, registro: SincronizacionAudiencia) -> dict[str, Any]:
    return {
        "audiencia_id": str(audiencia.id),
        "estado": audiencia.estado,
        "id_externo": audiencia.id_externo,
        "miembros": audiencia.miembros,
        "ok": registro.ok,
        "altas": registro.altas,
        "bajas": registro.bajas,
        "en_el_segmento": registro.en_el_segmento,
        "sin_consentimiento": registro.sin_consentimiento,
        "suprimidos": registro.suprimidos,
        "error": registro.error,
        "porque": (registro.detalle or {}).get("porque", ""),
    }


def ficha(db: Session, tenant_id: UUID, audiencia_id: UUID, *, limite: int = 50) -> dict[str, Any]:
    """La audiencia con su estado y su historial, del más reciente al más viejo."""
    audiencia = _audiencia(db, tenant_id, audiencia_id)
    historial = (
        db.execute(
            select(SincronizacionAudiencia)
            .where(SincronizacionAudiencia.audiencia_id == audiencia.id)
            .order_by(SincronizacionAudiencia.at.desc(), SincronizacionAudiencia.id.desc())
            .limit(limite)
        )
        .scalars()
        .all()
    )
    return {
        "id": str(audiencia.id),
        "nombre": audiencia.nombre,
        "segmento_id": str(audiencia.segmento_id),
        "conexion_id": str(audiencia.conexion_id),
        "finalidad": audiencia.finalidad,
        "id_externo": audiencia.id_externo,
        "estado": audiencia.estado,
        "miembros": audiencia.miembros,
        "ultima_sync_at": audiencia.ultima_sync_at,
        "ultimo_error": audiencia.ultimo_error,
        "minimo": int(_ajuste("audiencia_minimo", db) or 100),
        "finalidad_exigida": str(_ajuste("audiencia_finalidad", db) or ""),
        "historial": [
            {
                "id": str(h.id),
                "at": h.at,
                "ok": h.ok,
                "altas": h.altas,
                "bajas": h.bajas,
                "en_el_segmento": h.en_el_segmento,
                "sin_consentimiento": h.sin_consentimiento,
                "suprimidos": h.suprimidos,
                "error": h.error,
                "porque": (h.detalle or {}).get("porque", ""),
            }
            for h in historial
        ],
    }
