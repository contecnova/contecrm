"""Procesos de negocio que cruzan servicios: sagas con compensación, migración
de instancias en vuelo y plantillas por sector
(CRM-03.03.02.12, CRM-00.03.02.13, CRM-00.03.05.15).

Un pedido que se cobra toca cuatro servicios y ninguna base de datos los abarca a
todos. No hay transacción que valga: o se orquesta con compensaciones, o el día
que falla el tercer paso queda un pedido confirmado, un stock reservado y un
cobro que no existe — y alguien lo arregla a mano leyendo logs.

Las decisiones:

**Cada paso declara cómo se deshace antes de ejecutarse.** Igual que en el agente
de IA y por lo mismo: calcularlo después obliga a saber qué había antes, y para
entonces ya se cambió.

**Compensar no es deshacer: es hacer lo contrario.** Un cobro no se borra, se
devuelve; un pedido no desaparece, se cancela. Lo primero pierde el rastro de que
pasó, y lo que pasó tiene consecuencias contables aunque se arrepienta.

**Lo que no se puede compensar se declara así desde el principio.** Un correo
enviado al cliente no vuelve. Saberlo antes cambia el orden de los pasos: lo
irreversible va al final, cuando ya no puede fallar nada detrás.

**Una instancia en vuelo no salta a la versión nueva del proceso.** Termina con
la suya. Cambiarle el guion a la mitad deja instancias en un paso que en la nueva
versión no existe, y nadie sabe qué hacer con ellas.

**Y una plantilla de flujo se clona, no se hereda.** Si heredara, mejorar la
plantilla cambiaría los procesos que ya están corriendo en veinte clientes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.audit.chain import registrar
from crmcore.db.base import Base, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

logger = get_logger(__name__)

ESTADOS_SAGA = ("en_curso", "terminada", "compensando", "compensada", "atascada")
ESTADOS_PASO = ("pendiente", "hecho", "fallido", "compensado", "no_compensable")


class Saga(Base, TimestampMixin):
    """Un proceso que cruza servicios y que hay que poder deshacer."""

    __tablename__ = "sagas"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(80), nullable=False)
    objeto: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    objeto_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="en_curso")
    # La versión del proceso con la que nació. Una instancia en vuelo NO salta a
    # la versión nueva: termina con la suya, porque cambiarle el guion a la mitad
    # la deja en un paso que en la nueva no existe.
    version_proceso: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    contexto: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    motivo_fin: Mapped[str] = mapped_column(Text, nullable=False, default="")
    terminada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_sagas", "tenant_id", "clave", "estado"),)


class PasoSaga(Base):
    """Un paso de la saga, con su compensación declarada antes de ejecutarse."""

    __tablename__ = "pasos_saga"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    saga_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    orden: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    nombre: Mapped[str] = mapped_column(String(80), nullable=False)
    servicio: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="pendiente")
    datos: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # Cómo se deshace. Vacío significa que NO se puede, y eso se declara al
    # definir el proceso: un correo enviado no vuelve, y saberlo antes cambia el
    # orden de los pasos.
    compensacion: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    compensable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    ejecutado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    compensado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "saga_id", "orden", name="uq_paso_saga"),
        Index("ix_pasos_saga", "tenant_id", "saga_id", "orden"),
    )


class PlantillaFlujo(Base, TimestampMixin):
    """Un proceso de ejemplo por sector, para clonar (CRM-00.03.05.15)."""

    __tablename__ = "plantillas_flujo"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    clave: Mapped[str] = mapped_column(String(80), nullable=False)
    sector: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    caso_de_uso: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    definicion: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # Lo que la plantilla NO resuelve. Una que promete el proceso entero y deja
    # fuera la aprobación hace que el cliente lo descubra en producción.
    no_resuelve: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("clave", "version", name="uq_plantilla_flujo"),
        Index("ix_plantillas_flujo", "sector", "activa"),
    )


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


# ── Saga con compensaciones (CRM-03.03.02.12) ─────────────────────────────


def iniciar(
    uow: UnidadDeTrabajo,
    *,
    clave: str,
    pasos: list[dict[str, Any]],
    objeto: str = "",
    objeto_id: UUID | None = None,
    contexto: dict[str, Any] | None = None,
    version_proceso: int = 1,
) -> dict[str, Any]:
    """Arranca una saga con todos sus pasos declarados de antemano.

    **Con la compensación de cada paso ya escrita.** Calcularla cuando falle el
    tercero obliga a saber qué había antes del primero, y para entonces ya se
    cambió.

    Y se avisa si hay algo irreversible **antes del final**: lo que no se puede
    deshacer tiene que ir al último, cuando ya no puede fallar nada detrás. Un
    correo al cliente en el paso dos deja una saga que, al compensarse, ha
    avisado a alguien de algo que no ha pasado.
    """
    if not pasos:
        raise ErrorValidacion("Una saga sin pasos no hace nada", error_code="saga.sin_pasos")

    creados: list[PasoSaga] = []
    saga = Saga(
        tenant_id=uow.tenant_id,
        clave=clave,
        objeto=objeto,
        objeto_id=objeto_id,
        contexto=dict(contexto or {}),
        version_proceso=version_proceso,
    )
    uow.db.add(saga)
    uow.db.flush()

    for orden, paso in enumerate(pasos, start=1):
        compensacion = dict(paso.get("compensacion") or {})
        creados.append(
            PasoSaga(
                tenant_id=uow.tenant_id,
                saga_id=saga.id,
                orden=orden,
                nombre=str(paso.get("nombre") or f"paso_{orden}"),
                servicio=str(paso.get("servicio") or ""),
                datos=dict(paso.get("datos") or {}),
                compensacion=compensacion,
                compensable=bool(compensacion),
            )
        )
    for fila in creados:
        uow.db.add(fila)
    uow.db.flush()

    irreversibles = [p.orden for p in creados if not p.compensable]
    mal_colocados = [o for o in irreversibles if o < len(creados)]
    return {
        "saga_id": str(saga.id),
        "pasos": len(creados),
        "irreversibles": irreversibles,
        # El aviso que evita el caso feo: compensar una saga que ya avisó al
        # cliente de algo que al final no ha pasado.
        "irreversibles_antes_del_final": mal_colocados,
        "aviso": (
            ""
            if not mal_colocados
            else f"Los pasos {mal_colocados} no se pueden deshacer y no son los "
            "últimos: si algo falla después, la saga se compensará entera menos "
            "eso. Lo irreversible va al final, cuando ya no puede fallar nada detrás."
        ),
    }


def marcar_hecho(
    uow: UnidadDeTrabajo, *, saga_id: UUID, orden: int, datos: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Anota que un paso salió bien."""
    paso = _paso(uow.db, uow.tenant_id, saga_id, orden)
    paso.estado = "hecho"
    paso.datos = {**(paso.datos or {}), **(datos or {})}
    paso.ejecutado_at = _ahora()
    uow.db.flush()

    pendientes = _pasos(uow.db, uow.tenant_id, saga_id)
    if all(p.estado == "hecho" for p in pendientes):
        saga = uow.db.get(Saga, saga_id)
        saga.estado = "terminada"
        saga.terminada_at = _ahora()
        uow.db.flush()
    return {"orden": orden, "estado": paso.estado}


def fallar(uow: UnidadDeTrabajo, *, saga_id: UUID, orden: int, error: str) -> dict[str, Any]:
    """Anota que un paso falló y **compensa hacia atrás**.

    Hacia atrás y no hacia delante: los pasos se apoyan unos en otros, y deshacer
    el primero antes que el tercero deja el tercero apuntando a algo que ya no
    está.

    Lo que no se puede compensar **se dice y se deja**. Fingir que la saga quedó
    limpia cuando se mandó un correo al cliente es lo que hace que nadie se fíe
    de la palabra «compensada».
    """
    saga = uow.db.get(Saga, saga_id)
    if saga is None or saga.tenant_id != uow.tenant_id:
        raise NoEncontrado("Esa saga no existe", error_code="saga.no_encontrada")

    paso = _paso(uow.db, uow.tenant_id, saga_id, orden)
    paso.estado = "fallido"
    paso.error = error[:400]
    saga.estado = "compensando"
    uow.db.flush()

    compensados: list[int] = []
    sin_compensar: list[dict[str, Any]] = []
    for anterior in sorted(
        (
            p
            for p in _pasos(uow.db, uow.tenant_id, saga_id)
            if p.orden < orden and p.estado == "hecho"
        ),
        key=lambda p: -p.orden,
    ):
        if not anterior.compensable:
            anterior.estado = "no_compensable"
            sin_compensar.append(
                {
                    "orden": anterior.orden,
                    "nombre": anterior.nombre,
                    "porque": "El paso declaró que no se puede deshacer",
                }
            )
            continue
        anterior.estado = "compensado"
        anterior.compensado_at = _ahora()
        compensados.append(anterior.orden)

    saga.estado = "compensada" if not sin_compensar else "atascada"
    saga.motivo_fin = error[:400]
    saga.terminada_at = _ahora()
    uow.db.flush()
    registrar(
        uow.db,
        accion="saga.compensada",
        objeto="saga",
        objeto_id=saga.id,
        datos={"fallo_en": orden, "compensados": compensados, "sin_compensar": len(sin_compensar)},
        motivo=error[:200],
        tenant_id=uow.tenant_id,
    )
    return {
        "saga_id": str(saga.id),
        "estado": saga.estado,
        "compensados": compensados,
        "sin_compensar": sin_compensar,
        "limpia": not sin_compensar,
        "que_significa": (
            "Todo lo que se había hecho se ha deshecho."
            if not sin_compensar
            else "Queda trabajo hecho que NO se puede deshacer. La saga está atascada "
            "a propósito: alguien tiene que decidir qué se hace con eso, y decir que "
            "está compensada haría que nadie se fiara de esa palabra."
        ),
    }


# ── Migración de instancias en vuelo (CRM-00.03.02.13) ────────────────────


def plan_de_migracion(
    db: Session,
    tenant_id: UUID,
    *,
    clave: str,
    version_nueva: int,
    pasos_nuevos: list[str],
) -> dict[str, Any]:
    """Qué pasaría con las instancias en vuelo al publicar una versión nueva.

    **Las que están corriendo terminan con su versión.** Cambiarles el guion a la
    mitad las deja en un paso que en la nueva no existe, y entonces nadie sabe qué
    hacer con ellas: ni avanzan ni se pueden cancelar sin dejar cosas a medias.

    Lo que sí se puede es **decir cuántas hay y en qué paso**, porque de eso
    depende si la versión nueva puede esperar a que terminen o hay que migrarlas a
    mano una a una.
    """
    en_vuelo = (
        db.execute(
            select(Saga).where(
                Saga.tenant_id == tenant_id,
                Saga.clave == clave,
                Saga.estado.in_(("en_curso", "compensando")),
            )
        )
        .scalars()
        .all()
    )
    por_version: dict[int, int] = {}
    en_paso_que_desaparece: list[str] = []
    for saga in en_vuelo:
        por_version[saga.version_proceso] = por_version.get(saga.version_proceso, 0) + 1
        actual = next(
            (
                p.nombre
                for p in sorted(_pasos(db, tenant_id, saga.id), key=lambda p: p.orden)
                if p.estado == "pendiente"
            ),
            "",
        )
        if actual and actual not in pasos_nuevos:
            en_vuelo_id = str(saga.id)
            en_paso_que_desaparece.append(f"{en_vuelo_id} (en «{actual}»)")

    return {
        "clave": clave,
        "version_nueva": version_nueva,
        "en_vuelo": len(en_vuelo),
        "por_version": por_version,
        # Las que no podrían migrarse aunque se quisiera: su paso actual no
        # existe en la versión nueva.
        "en_paso_que_desaparece": en_paso_que_desaparece,
        "se_pueden_migrar_todas": not en_paso_que_desaparece,
        "que_pasa": (
            "Las instancias en vuelo terminan con SU versión. La nueva se aplica a "
            "las que empiecen a partir de ahora."
        ),
        "aviso": (
            ""
            if not en_paso_que_desaparece
            else f"{len(en_paso_que_desaparece)} instancias están en un paso que la "
            "versión nueva no tiene. Migrarlas las dejaría sin sitio: o terminan con "
            "la suya, o hay que decidir una a una."
        ),
    }


# ── Plantillas de flujo por sector (CRM-00.03.05.15) ──────────────────────


def clonar_plantilla(uow: UnidadDeTrabajo, *, clave: str, nombre_destino: str) -> dict[str, Any]:
    """Copia una plantilla de flujo para que el tenant la modifique.

    **Se clona, no se hereda.** Si heredara, mejorar la plantilla cambiaría los
    procesos que ya están corriendo en veinte clientes — incluido uno que la
    ajustó hace seis meses y no espera que le cambie nada.

    Y se devuelve **lo que la plantilla no resuelve**: una que promete el proceso
    entero y deja fuera la aprobación hace que el cliente lo descubra en
    producción, con el proceso ya en marcha.
    """
    plantilla = (
        uow.db.execute(
            select(PlantillaFlujo)
            .where(PlantillaFlujo.clave == clave, PlantillaFlujo.activa.is_(True))
            .order_by(PlantillaFlujo.version.desc())
        )
        .scalars()
        .first()
    )
    if plantilla is None:
        raise NoEncontrado(
            f"No hay plantilla de flujo activa con la clave «{clave}»",
            error_code="flujo.plantilla_no_existe",
        )
    if not nombre_destino.strip():
        raise ErrorValidacion(
            "El clon necesita nombre propio: si se queda con el de la plantilla, "
            "nadie sabe después cuál es el suyo y cuál el de fábrica.",
            error_code="flujo.clon_sin_nombre",
        )

    return {
        "desde": plantilla.clave,
        "version_origen": plantilla.version,
        "nombre": nombre_destino,
        "definicion": plantilla.definicion,
        "es_copia_independiente": True,
        # Lo que el cliente va a tener que resolver por su cuenta, dicho antes de
        # empezar.
        "no_resuelve": plantilla.no_resuelve,
        "porque_copia": (
            "Se clona y no se hereda: si heredara, mejorar la plantilla cambiaría los "
            "procesos que ya están corriendo en otros clientes."
        ),
    }


def _pasos(db: Session, tenant_id: UUID, saga_id: UUID) -> list[PasoSaga]:
    return list(
        db.execute(
            select(PasoSaga)
            .where(PasoSaga.tenant_id == tenant_id, PasoSaga.saga_id == saga_id)
            .order_by(PasoSaga.orden)
        )
        .scalars()
        .all()
    )


def _paso(db: Session, tenant_id: UUID, saga_id: UUID, orden: int) -> PasoSaga:
    fila = (
        db.execute(
            select(PasoSaga).where(
                PasoSaga.tenant_id == tenant_id,
                PasoSaga.saga_id == saga_id,
                PasoSaga.orden == orden,
            )
        )
        .scalars()
        .first()
    )
    if fila is None:
        raise NoEncontrado("Ese paso no existe", error_code="saga.paso_no_existe")
    if fila.estado == "compensado":
        raise Conflicto(
            "Ese paso ya está compensado: volver a tocarlo dejaría la saga contando "
            "dos historias distintas.",
            error_code="saga.paso_compensado",
        )
    return fila
