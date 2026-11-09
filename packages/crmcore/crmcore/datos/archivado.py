"""Archivado de datos históricos con acceso consultable (CRM-07.03.01.02).

Entre «tenerlo todo en las tablas vivas» y «purgarlo» hay un hueco donde cae casi
todo el dato viejo de un CRM: actividades de hace cuatro años, oportunidades
perdidas de un producto que ya no se vende, casos cerrados de clientes que se
fueron. No se puede borrar —hace falta para una reclamación, para una auditoría o
simplemente para entender la historia de una cuenta— y tenerlo en la tabla viva
hace lento todo lo demás.

Lo que suele pasar en su lugar: se sube la retención a «nunca» y las tablas
crecen hasta que alguien, un viernes, borra a mano lo que le parece viejo.

Cuatro decisiones:

**Archivar no es borrar, y el archivo se consulta.** Si el dato archivado no se
pudiera leer, esto sería una purga con otro nombre — y la primera vez que alguien
lo necesitara y no estuviera, nadie volvería a archivar nada.

**La fila archivada conserva su identificador.** Es lo que permite que una
solicitud de acceso encuentre lo archivado: si el archivo fuese anónimo, el
derecho de acceso devolvería un expediente incompleto sin saberlo.

**Se simula por defecto**, como la purga y la importación masiva, y por el mismo
motivo: lo que va a mover diez mil filas hay que poder verlo antes.

**Un bloqueo legal no impide archivar.** Lo que prohíbe es destruir, y esto no
destruye: el dato sigue entero y consultable. Se deja anotado que lo había, para
que quien audite vea que se tuvo en cuenta.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import (
    DateTime,
    Index,
    String,
    func,
    or_,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from crmcore.datos.guard_borrados import con_borrados
from crmcore.db.base import Base
from crmcore.errors import ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger

logger = get_logger(__name__)


class FilaArchivada(Base):
    """Una fila sacada de su tabla viva y guardada entera.

    Vive en el **esquema del servicio dueño**, como todo lo demás: archivar en un
    sitio común obligaría a que un servicio leyera datos de otro, que es la
    regla que sostiene el despliegue independiente.
    """

    __tablename__ = "filas_archivadas"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clase: Mapped[str] = mapped_column(String(60), nullable=False)
    tabla: Mapped[str] = mapped_column(String(80), nullable=False)
    # El identificador ORIGINAL. Es lo que hace que una solicitud de acceso
    # encuentre lo archivado: con un id nuevo, el expediente saldría incompleto
    # y nadie se daría cuenta.
    registro_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    contenido: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # La fecha por la que se archivó —la que manda la clase de dato—, para poder
    # consultar el archivo por el mismo criterio que la tabla viva.
    fecha_original: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archivada_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    archivada_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    __table_args__ = (
        Index("ix_archivadas", "tenant_id", "clase", "fecha_original"),
        Index("ix_archivadas_registro", "tenant_id", "registro_id"),
    )


@dataclass
class InformeArchivado:
    """Qué se archivaría o se archivó."""

    clase: str
    candidatas: int = 0
    archivadas: int = 0
    simulado: bool = True
    bajo_bloqueo_legal: int = 0
    motivos: list[str] = field(default_factory=list)

    def a_dict(self) -> dict[str, Any]:
        return {
            "clase": self.clase,
            "candidatas": self.candidatas,
            "archivadas": self.archivadas,
            "simulado": self.simulado,
            # Se dice, aunque no cambie nada: quien audite tiene que ver que el
            # bloqueo se tuvo en cuenta y por qué no impidió archivar.
            "bajo_bloqueo_legal": self.bajo_bloqueo_legal,
            "el_bloqueo_no_impide_archivar": (
                "Un bloqueo legal prohíbe destruir, no archivar: el dato sigue "
                "entero y consultable."
            ),
            "motivos": self.motivos,
        }


def archivar(
    db: Session,
    *,
    tenant_id: UUID,
    clase: str,
    antes_de: datetime,
    simular: bool = True,
    tope: int = 5_000,
    por: UUID | None = None,
) -> InformeArchivado:
    """Mueve al archivo lo anterior a una fecha, dejándolo consultable.

    **Simula por defecto.** Lo que va a mover diez mil filas hay que poder verlo
    antes, no después.

    El `tope` acota cada pasada por la misma razón que en la purga: mover cien
    mil filas en una transacción la mantiene abierta minutos y, si falla a la
    mitad, revierte entera.
    """
    from crmcore.audit.chain import registrar
    from crmcore.datos.retencion import CLASES, bajo_bloqueo

    declarada = CLASES.get(clase)
    if declarada is None:
        raise ErrorValidacion(
            f"«{clase}» no es una clase de dato declarada. Archivar por nombre de "
            "tabla dejaría fuera el criterio de fecha, que no siempre es la de "
            "creación: una actividad se cuenta desde que se completó.",
            error_code="archivado.clase_desconocida",
            detalle={"declaradas": sorted(CLASES)},
        )

    modelo = declarada.modelo
    campo = getattr(modelo, declarada.campo_fecha)
    consulta = select(modelo).where(
        modelo.tenant_id == tenant_id,
        campo.is_not(None),
        campo < antes_de,
    )
    if declarada.solo_si_borrado and hasattr(modelo, "deleted_at"):
        consulta = consulta.where(modelo.deleted_at.is_not(None))

    # Lo archivable incluye lo borrado, así que hay que poder verlo.
    with con_borrados(db):
        filas = list(db.execute(consulta.limit(max(1, int(tope)))).scalars().all())
    informe = InformeArchivado(clase=clase, candidatas=len(filas), simulado=simular)

    bloqueadas = 0
    for fila in filas:
        if bajo_bloqueo(db, tenant_id=tenant_id, objeto=declarada.clave, objeto_id=fila.id):
            bloqueadas += 1
    informe.bajo_bloqueo_legal = bloqueadas

    if simular:
        informe.motivos.append(
            f"Simulación: se archivarían {len(filas)} filas anteriores a "
            f"{antes_de.date()}. Nada se ha movido."
        )
        return informe

    for fila in filas:
        contenido = fila.a_dict(json_seguro=True) if hasattr(fila, "a_dict") else {}
        db.add(
            FilaArchivada(
                tenant_id=tenant_id,
                clase=clase,
                tabla=modelo.__tablename__,
                registro_id=fila.id,
                contenido=contenido,
                fecha_original=getattr(fila, declarada.campo_fecha, None),
                archivada_por=por,
            )
        )
        db.delete(fila)
        informe.archivadas += 1

    db.flush()
    registrar(
        db,
        accion="datos.archivados",
        objeto=clase,
        datos={"archivadas": informe.archivadas, "antes_de": antes_de.isoformat()},
        motivo="Archivado de histórico",
        tenant_id=tenant_id,
    )
    logger.info("datos.archivados", clase=clase, filas=informe.archivadas)
    return informe


def consultar(
    db: Session,
    tenant_id: UUID,
    *,
    clase: str = "",
    registro_id: UUID | None = None,
    relacionado_con: UUID | None = None,
    desde: datetime | None = None,
    hasta: datetime | None = None,
    limite: int = 200,
) -> dict[str, Any]:
    """Lee el archivo. Es lo que separa archivar de purgar.

    Si el dato archivado no se pudiera consultar, esto sería una purga con otro
    nombre — y la primera vez que alguien lo necesitara y no estuviera, nadie
    volvería a archivar nada.
    """
    consulta = select(FilaArchivada).where(FilaArchivada.tenant_id == tenant_id)
    if clase:
        consulta = consulta.where(FilaArchivada.clase == clase)
    if registro_id is not None:
        consulta = consulta.where(FilaArchivada.registro_id == registro_id)
    if relacionado_con is not None:
        # «Lo archivado de esta cuenta»: las filas que la nombran en alguna
        # columna —`cuenta_id`, `contacto_id`, `relacionado_id`…—. Se mira el
        # valor y no el nombre de la columna, porque cada objeto llama a su
        # padre de una forma y una lista de nombres se queda corta el primer
        # día que alguien añade un objeto. O la fila misma, si el registro es
        # el archivado.
        consulta = consulta.where(
            or_(
                FilaArchivada.registro_id == relacionado_con,
                func.jsonb_path_exists(
                    FilaArchivada.contenido,
                    text("'$.* ? (@ == $id)'::jsonpath"),
                    func.jsonb_build_object("id", str(relacionado_con)),
                ),
            )
        )
    if desde is not None:
        consulta = consulta.where(FilaArchivada.fecha_original >= desde)
    if hasta is not None:
        consulta = consulta.where(FilaArchivada.fecha_original <= hasta)

    filas = list(
        db.execute(
            consulta.order_by(FilaArchivada.fecha_original.desc()).limit(max(1, int(limite)))
        )
        .scalars()
        .all()
    )
    return {
        "filas": [
            {
                "clase": f.clase,
                "tabla": f.tabla,
                "registro_id": str(f.registro_id),
                "fecha_original": f.fecha_original.isoformat() if f.fecha_original else None,
                "archivada_at": f.archivada_at.isoformat(),
                "contenido": f.contenido,
            }
            for f in filas
        ],
        "cuantas": len(filas),
        # Si se ha llegado al límite hay más, y decir el número sin avisarlo
        # haría creer que eso es todo lo que hay archivado.
        "hay_mas": len(filas) >= limite,
        "alcance": (
            "Solo el archivo de este servicio: cada uno archiva lo suyo, porque "
            "ninguno lee el esquema de otro."
        ),
    }


def desarchivar(
    db: Session, tenant_id: UUID, *, registro_id: UUID, por: UUID | None = None
) -> dict[str, Any]:
    """Devuelve una fila archivada a su tabla viva.

    Hace falta porque el archivo se consulta pero no se trabaja: cuando una
    cuenta que se fue vuelve, lo que se quiere no es leer su historia, es poder
    seguir escribiendo en ella.
    """
    from crmcore.audit.chain import registrar
    from crmcore.datos.retencion import CLASES

    fila = (
        db.execute(
            select(FilaArchivada).where(
                FilaArchivada.tenant_id == tenant_id,
                FilaArchivada.registro_id == registro_id,
            )
        )
        .scalars()
        .first()
    )
    if fila is None:
        raise NoEncontrado(
            "Ese registro no está en el archivo", error_code="archivado.no_encontrado"
        )
    declarada = CLASES.get(fila.clase)
    if declarada is None:
        raise ErrorValidacion(
            f"La clase «{fila.clase}» ya no está declarada: no se sabe a qué tabla "
            "devolver la fila. El contenido sigue en el archivo y se puede leer.",
            error_code="archivado.clase_retirada",
        )

    modelo = declarada.modelo
    columnas = {c.name for c in modelo.__table__.columns}
    viva = modelo(**{k: v for k, v in (fila.contenido or {}).items() if k in columnas})
    db.add(viva)
    db.delete(fila)
    db.flush()
    registrar(
        db,
        accion="datos.desarchivado",
        objeto=fila.clase,
        objeto_id=registro_id,
        datos={"tabla": fila.tabla},
        tenant_id=tenant_id,
    )
    return {"registro_id": str(registro_id), "clase": fila.clase, "devuelto_a": fila.tabla}


def resumen(db: Session, tenant_id: UUID) -> dict[str, Any]:
    """Cuánto hay archivado y de cuándo.

    Sin esto, el archivo es un agujero donde entran cosas: nadie sabe si guarda
    diez filas o diez millones, ni desde cuándo, y entonces nadie se atreve a
    consultarlo cuando hace falta.
    """
    filas = (
        db.execute(
            select(
                FilaArchivada.clase,
                func.count(FilaArchivada.id),
                func.min(FilaArchivada.fecha_original),
                func.max(FilaArchivada.fecha_original),
            )
            .where(FilaArchivada.tenant_id == tenant_id)
            .group_by(FilaArchivada.clase)
        )
    ).all()
    return {
        "por_clase": [
            {
                "clase": c,
                "filas": n,
                "desde": d.isoformat() if d else None,
                "hasta": h.isoformat() if h else None,
            }
            for c, n, d, h in filas
        ],
        "total": sum(n for _, n, _, _ in filas),
        "generado_at": datetime.now(timezone.utc).isoformat(),
    }


# ── Archivar por criterio (CRM-07.03.01.02) ──────────────────────────────
#
# `archivar` pedía la fecha de corte a quien llamaba, y la única ruta que había
# —`POST /{servicio}/volumen/archivar`— ni siquiera la llamaba: planificaba
# sobre filas tecleadas en el cuerpo. O sea, nada se archivaba nunca. Aquí está
# el criterio que faltaba: la antigüedad por clase de dato, como ajuste del
# tenant, y el corte calculado con el día del cliente.


def hay_archivo(db: Session) -> bool:
    """Si este servicio tiene tabla de archivo.

    No todos la tienen: sólo los que guardan histórico que crece. Preguntar a
    uno que no la tiene no es un error del usuario, y un 500 por «la tabla no
    existe» lo parecería; se contesta que aquí no hay archivo.
    """
    return db.execute(text("select to_regclass('filas_archivadas') is not null")).scalar() is True


def dias_de_antiguedad(db: Session, clase: str) -> int:
    """A partir de cuántos días se archiva una clase: la suya o la de todas."""
    from crmcore.runtime import settings as rt

    por_clase = rt.efectivo("archivado_antiguedad_por_clase", db) or {}
    propio = por_clase.get(clase) if isinstance(por_clase, dict) else None
    if propio:
        return int(propio)
    return int(rt.efectivo("archivado_dias_por_defecto", db))


def corte_de(db: Session, clase: str) -> datetime:
    """La fecha antes de la cual una fila de esa clase se archiva.

    Contada desde el día del cliente, no desde el UTC: dos años contados en
    UTC archivan un día antes de tiempo para media Europa de madrugada.
    """
    from datetime import time, timedelta

    from crmcore import fechas

    dia = fechas.hoy(db) - timedelta(days=dias_de_antiguedad(db, clase))
    return datetime.combine(dia, time.min, tzinfo=timezone.utc)


def clases_archivables(db: Session, tenant_id: UUID) -> list[dict[str, Any]]:
    """Las clases de dato de este servicio, con su criterio y lo que movería.

    Con el recuento de candidatas: «se archiva lo de hace dos años» sin decir
    cuánto es deja a quien lo decide sin saber si va a mover diez filas o diez
    millones.
    """
    from crmcore.datos.retencion import CLASES

    salida: list[dict[str, Any]] = []
    for clave in sorted(CLASES):
        declarada = CLASES[clave]
        corte = corte_de(db, clave)
        modelo = declarada.modelo
        campo = getattr(modelo, declarada.campo_fecha)
        consulta = (
            select(func.count())
            .select_from(modelo)
            .where(modelo.tenant_id == tenant_id, campo.is_not(None), campo < corte)
        )
        if declarada.solo_si_borrado and hasattr(modelo, "deleted_at"):
            consulta = consulta.where(modelo.deleted_at.is_not(None))
        with con_borrados(db):
            candidatas = int(db.execute(consulta).scalar_one())
        salida.append(
            {
                "clase": clave,
                "descripcion": declarada.descripcion,
                "tabla": modelo.__tablename__,
                "campo_fecha": declarada.campo_fecha,
                "dias": dias_de_antiguedad(db, clave),
                "corte": corte.date().isoformat(),
                "candidatas": candidatas,
            }
        )
    return salida


def archivar_por_criterio(
    db: Session,
    *,
    tenant_id: UUID,
    clase: str,
    simular: bool = True,
    por: UUID | None = None,
) -> dict[str, Any]:
    """Archiva lo que el criterio del tenant dice que ya es histórico."""
    from crmcore.runtime import settings as rt

    corte = corte_de(db, clase)
    informe = archivar(
        db,
        tenant_id=tenant_id,
        clase=clase,
        antes_de=corte,
        simular=simular,
        tope=int(rt.efectivo("archivado_tope_por_pasada", db)),
        por=por,
    )
    return {
        **informe.a_dict(),
        "corte": corte.date().isoformat(),
        "dias": dias_de_antiguedad(db, clase),
    }
