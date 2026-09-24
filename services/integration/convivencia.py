"""Convivencia con el CRM heredado durante la migración: strangler
(CRM-00.03.01.07).

Nadie apaga su CRM un viernes y enciende otro el lunes. La migración real dura
meses y durante esos meses **los dos sistemas están vivos**: unas cosas ya se
hacen aquí y otras siguen allí. El patrón strangler consiste en ir rodeando al
viejo objeto a objeto hasta que se queda sin nada que hacer.

Lo que hace falta para que eso no sea un caos es una sola cosa: **que en todo
momento se sepa quién manda sobre cada objeto**. De ahí las decisiones:

**El dueño se declara por objeto, no por sistema.** Las cuentas ya son nuestras y
los pedidos siguen siendo del viejo: esa es la situación normal durante meses, y
un interruptor global no la representa.

**Se puede cortar por criterio, no solo por objeto entero.** «Los clientes nuevos
aquí, los antiguos allí» es como se migra de verdad. Se usa la gramática de
condiciones de siempre, no una nueva.

**Doble escritura solo con un dueño declarado.** Escribir en los dos lados es
necesario un tiempo, pero si nadie manda, cuando los dos cambien el mismo dato no
habrá forma de decidir — y se decidirá por orden de llegada, que es como se pierde
información sin que nadie se entere.

**Se mide qué queda por migrar.** Un strangler sin medida no termina: se queda
años «en migración» porque nadie sabe cuánto falta. Aquí, cada objeto dice qué
porcentaje ya vive aquí.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.audit import registrar
from crmcore.authz.abac import Condicion
from crmcore.db.base import Base, SoftDeleteMixin, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import ErrorValidacion
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

# Quién manda sobre un objeto durante la migración.
#
#   heredado  manda el sistema viejo; aquí se lee y no se escribe
#   nuevo     manda este CRM; el viejo ya no toca ese objeto
#   ambos     los dos escriben, con un dueño declarado para el desempate
DUENOS = ("heredado", "nuevo", "ambos")


class ReglaConvivencia(Base, TimestampMixin, SoftDeleteMixin):
    """Quién manda sobre qué objeto, y con qué condición (CRM-00.03.01.07)."""

    __tablename__ = "reglas_convivencia"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    objeto: Mapped[str] = mapped_column(String(60), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    dueno: Mapped[str] = mapped_column(
        String(20), nullable=False, default="heredado", info={"opciones": DUENOS}
    )
    # Con `ambos`, quién gana si los dos han cambiado lo mismo. Obligatorio: sin
    # él se decidiría por orden de llegada, que es perder datos en silencio.
    manda_en_empate: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # A qué registros se aplica. Vacío = a todos los de ese objeto.
    condiciones: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Cuando dos reglas encajan gana la de prioridad más baja, declarada. Con
    # desempate implícito, el dueño de un registro cambiaría al restaurar una
    # copia de seguridad.
    prioridad: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    # Si lo escrito aquí se propaga al heredado mientras conviven.
    replicar_al_heredado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Cuándo se dio por migrado ese objeto. Es lo que permite decir que la
    # migración terminó, en vez de dejarla «en curso» para siempre.
    migrado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "objeto", "nombre", name="uq_regla_convivencia"),
        Index("ix_reglas_convivencia", "tenant_id", "objeto", "activa", "prioridad"),
    )


class ProgresoMigracion(Base, TimestampMixin):
    """Cuánto queda por migrar de cada objeto.

    Los números **los trae quien migra**: contar registros del sistema viejo desde
    aquí exigiría leer su base de datos, que es justo lo que el strangler evita.
    Lo que se guarda es la medida declarada y **cuándo** se declaró, porque una
    medida de hace tres meses presentada como actual hace creer que la migración
    va bien.
    """

    __tablename__ = "progreso_migracion"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    objeto: Mapped[str] = mapped_column(String(60), nullable=False)
    en_heredado: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    en_nuevo: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    medido_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    nota: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (UniqueConstraint("tenant_id", "objeto", name="uq_progreso_migracion"),)


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def declarar(
    uow: UnidadDeTrabajo,
    *,
    objeto: str,
    dueno: str,
    nombre: str = "",
    condiciones: list[dict[str, Any]] | None = None,
    prioridad: int = 100,
    manda_en_empate: str | None = None,
    replicar_al_heredado: bool = False,
) -> tuple[ReglaConvivencia, list[str]]:
    """Declara quién manda sobre un objeto, o sobre parte de él."""
    if dueno not in DUENOS:
        raise ErrorValidacion(
            f"Dueño «{dueno}» no válido.",
            error_code="convivencia.dueno_no_valido",
            detalle={"validos": list(DUENOS)},
        )
    if dueno == "ambos" and manda_en_empate not in ("heredado", "nuevo"):
        raise ErrorValidacion(
            "Con los dos escribiendo hace falta decir quién manda en un empate. "
            "Sin eso se decidiría por orden de llegada, que es perder datos sin "
            "que nadie se entere.",
            error_code="convivencia.sin_desempate",
        )
    from crmcore.authz.abac import OPERADORES

    for i, cruda in enumerate(condiciones or [], 1):
        if not isinstance(cruda, dict) or not cruda.get("atributo"):
            raise ErrorValidacion(
                f"La condición {i} no dice sobre qué atributo compara.",
                error_code="convivencia.condicion_invalida",
            )
        if cruda.get("operador") not in OPERADORES:
            raise ErrorValidacion(
                f"Operador «{cruda.get('operador')}» no válido en la condición {i}.",
                error_code="convivencia.operador_no_valido",
                detalle={"validos": sorted(OPERADORES)},
            )

    avisos: list[str] = []
    if dueno == "ambos" and not replicar_al_heredado:
        avisos.append(
            "Los dos escriben pero lo de aquí no se replica al heredado: el viejo "
            "se irá quedando atrás sin que nadie lo vea hasta que alguien lo mire allí."
        )
    existentes = (
        uow.db.execute(
            select(ReglaConvivencia).where(
                ReglaConvivencia.tenant_id == uow.tenant_id,
                ReglaConvivencia.objeto == objeto,
                ReglaConvivencia.activa.is_(True),
            )
        )
        .scalars()
        .all()
    )
    if any(r.prioridad == prioridad for r in existentes):
        avisos.append(
            f"Ya hay otra regla de «{objeto}» con prioridad {prioridad}: con empate, "
            "el dueño dependería del orden de inserción."
        )

    fila = ReglaConvivencia(
        tenant_id=uow.tenant_id,
        objeto=objeto.strip(),
        nombre=nombre.strip() or f"{objeto}-{dueno}",
        dueno=dueno,
        manda_en_empate=manda_en_empate,
        condiciones=list(condiciones or []),
        prioridad=prioridad,
        replicar_al_heredado=replicar_al_heredado,
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila, avisos


def quien_manda(
    db: Session, tenant_id: UUID, *, objeto: str, registro: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Quién manda sobre este registro, **y por qué** (CRM-00.03.01.07).

    Devuelve siempre el porqué: durante una migración, «¿por qué este pedido no me
    deja editarlo?» es la pregunta de cada día, y sin respuesta la gente acaba
    editándolo en el sistema viejo «por si acaso» — que es como se duplica todo.

    Sin ninguna regla declarada **manda el heredado**. Es el valor seguro: al
    principio de una migración todo es suyo, y equivocarse hacia el viejo produce
    un dato que hay que traer, mientras que equivocarse hacia el nuevo produce dos
    verdades.
    """
    reglas = (
        db.execute(
            select(ReglaConvivencia)
            .where(
                ReglaConvivencia.tenant_id == tenant_id,
                ReglaConvivencia.objeto == objeto,
                ReglaConvivencia.activa.is_(True),
            )
            .order_by(ReglaConvivencia.prioridad, ReglaConvivencia.nombre)
        )
        .scalars()
        .all()
    )
    if not reglas:
        return {
            "objeto": objeto,
            "dueno": "heredado",
            "escribible_aqui": False,
            "porque": (
                "No hay ninguna regla declarada para este objeto: durante una "
                "migración, lo no declarado sigue siendo del sistema viejo."
            ),
            "por_defecto": True,
        }

    ambito = {"registro": registro or {}, **(registro or {})}
    for regla in reglas:
        if regla.condiciones:
            cumple = True
            for cruda in regla.condiciones:
                try:
                    condicion = Condicion(**cruda)
                except TypeError:
                    logger.warning("convivencia.condicion_ilegible", regla=str(regla.id))
                    cumple = False
                    break
                if not condicion.evaluar(ambito):
                    cumple = False
                    break
            if not cumple:
                continue
        detalle = f"Regla «{regla.nombre}» (prioridad {regla.prioridad})" + (
            ": aplica a todos los registros de este objeto" if not regla.condiciones else ""
        )
        return {
            "objeto": objeto,
            "regla": regla.nombre,
            "dueno": regla.dueno,
            "escribible_aqui": regla.dueno in ("nuevo", "ambos"),
            "replicar_al_heredado": regla.replicar_al_heredado,
            "manda_en_empate": regla.manda_en_empate,
            "porque": detalle,
            "por_defecto": False,
        }

    return {
        "objeto": objeto,
        "dueno": "heredado",
        "escribible_aqui": False,
        "porque": (
            "Hay reglas para este objeto, pero ninguna encaja con este registro: "
            "sigue siendo del sistema viejo."
        ),
        "por_defecto": True,
    }


def medir(
    uow: UnidadDeTrabajo,
    *,
    objeto: str,
    en_heredado: int,
    en_nuevo: int,
    nota: str = "",
) -> ProgresoMigracion:
    """Anota cuántos registros hay en cada lado.

    Los números los trae quien migra: contarlos en el sistema viejo desde aquí
    exigiría leer su base de datos, que es lo que este patrón evita.
    """
    fila = uow.db.execute(
        select(ProgresoMigracion).where(
            ProgresoMigracion.tenant_id == uow.tenant_id, ProgresoMigracion.objeto == objeto
        )
    ).scalar_one_or_none()
    if fila is None:
        fila = ProgresoMigracion(tenant_id=uow.tenant_id, objeto=objeto)
        uow.db.add(fila)
    fila.en_heredado = max(0, int(en_heredado))
    fila.en_nuevo = max(0, int(en_nuevo))
    fila.medido_at = _ahora()
    fila.nota = nota
    uow.db.flush()
    return fila


def progreso(db: Session, tenant_id: UUID) -> dict[str, Any]:
    """Cuánto queda, objeto a objeto, **y de cuándo es la medida**.

    Un strangler sin medida no termina: se queda años «en migración» porque nadie
    sabe cuánto falta. Y una medida de hace tres meses presentada como actual hace
    creer que va bien, así que la edad va delante.
    """
    filas = (
        db.execute(select(ProgresoMigracion).where(ProgresoMigracion.tenant_id == tenant_id))
        .scalars()
        .all()
    )
    reglas = (
        db.execute(
            select(ReglaConvivencia).where(
                ReglaConvivencia.tenant_id == tenant_id, ReglaConvivencia.activa.is_(True)
            )
        )
        .scalars()
        .all()
    )
    objetos_con_regla = {r.objeto for r in reglas}
    salida = []
    for fila in filas:
        total = fila.en_heredado + fila.en_nuevo
        edad = (
            _ahora()
            - (
                fila.medido_at
                if fila.medido_at.tzinfo
                else fila.medido_at.replace(tzinfo=timezone.utc)
            )
        ).days
        salida.append(
            {
                "objeto": fila.objeto,
                "en_heredado": fila.en_heredado,
                "en_nuevo": fila.en_nuevo,
                "pct_migrado": round(100 * fila.en_nuevo / total, 1) if total else None,
                "medido_hace_dias": edad,
                # Una medida vieja no vale: se marca en vez de presentarla como
                # actual.
                "medida_fresca": edad <= 30,
                "terminado": fila.en_heredado == 0 and total > 0,
            }
        )
    sin_medir = sorted(objetos_con_regla - {f.objeto for f in filas})
    return {
        "objetos": sorted(salida, key=lambda o: o["pct_migrado"] or 0),
        # Objetos con regla de convivencia y sin ninguna medida: son los que
        # llevan la migración a no terminar nunca, porque nadie sabe cuánto falta.
        "con_regla_sin_medir": sin_medir,
        "terminados": len([o for o in salida if o["terminado"]]),
        "concluyente": not sin_medir and all(o["medida_fresca"] for o in salida),
    }


def dar_por_migrado(
    uow: UnidadDeTrabajo, *, objeto: str, forzar: bool = False, motivo: str = ""
) -> dict[str, Any]:
    """Cierra la convivencia de un objeto: a partir de aquí manda este CRM.

    Con registros aún en el viejo **no se cierra**, salvo que se fuerce con
    motivo: cerrarlo dejaría fuera lo que queda allí, y nadie volvería a mirarlo
    porque el objeto ya constaría migrado.
    """
    medida = uow.db.execute(
        select(ProgresoMigracion).where(
            ProgresoMigracion.tenant_id == uow.tenant_id, ProgresoMigracion.objeto == objeto
        )
    ).scalar_one_or_none()
    quedan = medida.en_heredado if medida is not None else None

    if quedan is None and not forzar:
        raise ErrorValidacion(
            "No hay ninguna medida de este objeto: no se puede dar por migrado algo "
            "que nadie ha contado.",
            error_code="convivencia.sin_medida",
        )
    if quedan and not forzar:
        raise ErrorValidacion(
            f"Quedan {quedan} registros en el sistema heredado.",
            error_code="convivencia.quedan_registros",
            detalle={"en_heredado": quedan},
        )
    if forzar and not motivo.strip():
        raise ErrorValidacion(
            "Forzar el cierre exige motivo.", error_code="convivencia.motivo_obligatorio"
        )

    reglas = (
        uow.db.execute(
            select(ReglaConvivencia).where(
                ReglaConvivencia.tenant_id == uow.tenant_id, ReglaConvivencia.objeto == objeto
            )
        )
        .scalars()
        .all()
    )
    for regla in reglas:
        regla.dueno = "nuevo"
        regla.replicar_al_heredado = False
        regla.migrado_at = _ahora()
    uow.db.flush()
    registrar(
        uow.db,
        accion="convivencia.objeto_migrado",
        objeto="regla_convivencia",
        objeto_id=reglas[0].id if reglas else None,
        datos={"objeto": objeto, "quedaban": quedan, "forzado": forzar, "motivo": motivo},
        tenant_id=uow.tenant_id,
    )
    return {
        "objeto": objeto,
        "reglas_actualizadas": len(reglas),
        "quedaban_en_heredado": quedan,
        "forzado": bool(forzar),
    }
