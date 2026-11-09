"""Cada importación hecha, y cómo deshacerla entera (CRM-07.01.01.08).

La importación ya validaba antes y simulaba por defecto. Lo que faltaba es lo
que se pide el día después: «el fichero de ayer venía mal, quita lo que metió».
Sin esto, la respuesta es buscar a mano qué se creó —por fecha, por el nombre
del que lo subió— y devolver uno a uno los campos que pisó, que nadie apuntó.

Así que **cada importación que escribe deja su rastro**: qué registro creó, y
de cada registro que actualizó, cómo estaba antes y cómo lo dejó. Con eso,
revertir es mecánico:

* lo **creado** se borra —a la papelera, como cualquier borrado, para que el
  revertir también tenga vuelta atrás—;
* lo **actualizado** vuelve a su valor anterior, sólo en los campos que la
  importación cambió.

**Lo que se tocó después no se pisa sin preguntar.** Si un registro ya no está
como lo dejó la importación —alguien lo editó, otra carga lo cambió—, revertirlo
borraría o desharía trabajo que no es de la importación. Se informa como
conflicto y se deja; con `forzar` se revierte igual. Y se puede **simular**:
cuántos se borrarían, cuántos se devolverían y cuántos chocan, sin tocar nada.

La tabla es del núcleo y la monta cada servicio que importa (hoy `party`): el
rastro tiene que vivir junto a los registros que describe, en el mismo esquema y
en la misma transacción que la carga.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, Index, Integer, String, func, select, text
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from crmcore.db.base import Base
from crmcore.errors import Conflicto, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Lo que no se guarda en la foto: lo pone la base en cada escritura, y
# compararlo diría que todo registro «se ha tocado después».
_NO_SE_FOTOGRAFIA = frozenset(
    {"id", "tenant_id", "created_at", "updated_at", "created_by", "updated_by", "version"}
)


class Importacion(Base):
    """Una carga hecha: quién, cuándo, de qué fichero y qué tocó."""

    __tablename__ = "importaciones"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    objeto: Mapped[str] = mapped_column(String(80), nullable=False)
    fichero: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    creados: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    actualizados: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fallidos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # [{id, accion: crear|actualizar, antes?, despues}]. Guarda datos del
    # fichero, así que se purga con la retención como cualquier dato personal.
    registros: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    revertida_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revertida_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    reversion: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_importaciones_tenant", "tenant_id", "objeto", "created_at"),)


# ── La foto de un registro ────────────────────────────────────────────────


def _a_json(valor: Any) -> Any:
    if isinstance(valor, UUID):
        return str(valor)
    if isinstance(valor, (datetime, date)):
        return valor.isoformat()
    if isinstance(valor, Decimal):
        return str(valor)
    return valor


def foto(registro: Any) -> dict[str, Any]:
    """Los valores de las columnas del registro, en JSON."""
    mapeo = sa_inspect(type(registro))
    return {
        c.key: _a_json(getattr(registro, c.key))
        for c in mapeo.column_attrs
        if c.key not in _NO_SE_FOTOGRAFIA
    }


def _de_json(modelo: type, campo: str, valor: Any) -> Any:
    """Devuelve a su tipo un valor de la foto, para escribirlo en la columna."""
    if valor is None:
        return None
    columna = sa_inspect(modelo).columns.get(campo)
    if columna is None:
        return valor
    try:
        tipo = columna.type.python_type
    except NotImplementedError:
        return valor
    if tipo is UUID and isinstance(valor, str):
        return UUID(valor)
    if tipo is datetime and isinstance(valor, str):
        return datetime.fromisoformat(valor)
    if tipo is date and isinstance(valor, str):
        return date.fromisoformat(valor)
    if tipo is Decimal and isinstance(valor, str):
        return Decimal(valor)
    return valor


# ── Guardar y listar ──────────────────────────────────────────────────────


def guardar(
    db: Session,
    *,
    tenant_id: UUID,
    objeto: str,
    fichero: str,
    por: UUID | None,
    informe: Any,
    registros: list[dict[str, Any]],
) -> Importacion:
    importacion = Importacion(
        tenant_id=tenant_id,
        objeto=objeto,
        fichero=(fichero or "")[:300],
        por=por,
        creados=int(informe.creados),
        actualizados=int(informe.actualizados),
        fallidos=int(informe.fallidos),
        registros=registros,
    )
    db.add(importacion)
    db.flush()
    return importacion


def a_dict(importacion: Importacion) -> dict[str, Any]:
    return {
        "id": str(importacion.id),
        "objeto": importacion.objeto,
        "fichero": importacion.fichero,
        "por": str(importacion.por) if importacion.por else None,
        "creados": importacion.creados,
        "actualizados": importacion.actualizados,
        "fallidos": importacion.fallidos,
        "created_at": importacion.created_at.isoformat() if importacion.created_at else None,
        "revertida_at": (
            importacion.revertida_at.isoformat() if importacion.revertida_at else None
        ),
        "reversion": dict(importacion.reversion or {}),
    }


def listar(db: Session, tenant_id: UUID, *, limite: int = 50) -> list[dict[str, Any]]:
    filas = (
        db.execute(
            select(Importacion)
            .where(Importacion.tenant_id == tenant_id)
            .order_by(Importacion.created_at.desc())
            .limit(limite)
        )
        .scalars()
        .all()
    )
    return [a_dict(f) for f in filas]


# ── Revertir ──────────────────────────────────────────────────────────────


def revertir(
    db: Session,
    importacion_id: UUID,
    *,
    modelos: dict[str, type],
    borrar: dict[str, Callable[[Session, UUID], Any]] | None = None,
    simular: bool = True,
    forzar: bool = False,
    por: UUID | None = None,
    motivo: str = "",
) -> dict[str, Any]:
    """Deshace una importación entera, o dice qué haría (`simular`).

    `borrar` es el borrado de cada objeto en su servicio —con su cascada y su
    papelera—. Sin él, lo creado se manda a la papelera común sin cascada.
    """
    importacion = db.get(Importacion, importacion_id)
    if importacion is None:
        raise NoEncontrado("Esa importación no existe", error_code="importacion.no_existe")
    if importacion.revertida_at is not None:
        raise Conflicto(
            "Esa importación ya se revirtió",
            error_code="importacion.ya_revertida",
            detalle={"revertida_at": importacion.revertida_at.isoformat()},
        )
    modelo = modelos.get(importacion.objeto)
    if modelo is None:
        raise NoEncontrado(
            f"No se sabe revertir «{importacion.objeto}» en este servicio",
            error_code="importacion.objeto_desconocido",
        )

    resumen: dict[str, Any] = {
        "simulado": simular,
        "borrados": 0,
        "restaurados": 0,
        "ya_no_estaban": 0,
        "conflictos": [],
    }
    # Primero el plan, sin tocar nada; después, si procede, se aplica. Así un
    # conflicto no deja la reversión a medias: o se revierte entera, o no se
    # revierte nada y se dice qué lo impide.
    plan: list[tuple[dict[str, Any], Any]] = []
    # Al revés de como se hizo: si una fila tocó lo que otra creó, se deshace
    # primero lo último.
    for apunte in reversed(list(importacion.registros or [])):
        registro_id = UUID(str(apunte.get("id")))
        fila = db.get(modelo, registro_id)
        if fila is None or getattr(fila, "deleted_at", None) is not None:
            resumen["ya_no_estaban"] += 1
            continue
        despues = dict(apunte.get("despues") or {})
        ahora = foto(fila)
        tocados = sorted(k for k, v in despues.items() if k in ahora and ahora[k] != v)
        if tocados:
            resumen["conflictos"].append(
                {"id": str(registro_id), "accion": apunte.get("accion"), "campos": tocados}
            )
            if not forzar:
                continue
        plan.append((apunte, fila))
        if apunte.get("accion") == "crear":
            resumen["borrados"] += 1
        else:
            resumen["restaurados"] += 1

    if not simular and resumen["conflictos"] and not forzar:
        raise Conflicto(
            "Hay registros que se han cambiado después de importarlos",
            error_code="importacion.cambiados_despues",
            detalle={
                "conflictos": resumen["conflictos"][:100],
                "como_continuar": "revísalos, o repite con forzar=true para revertirlos igual",
            },
        )

    if not simular:
        for apunte, fila in plan:
            registro_id = fila.id
            if apunte.get("accion") == "crear":
                borrador = (borrar or {}).get(importacion.objeto)
                if borrador is not None:
                    borrador(db, registro_id)
                else:
                    from crmcore.datos import papelera

                    papelera.borrar(
                        db,
                        fila,
                        objeto=importacion.objeto,
                        etiqueta=str(getattr(fila, "nombre", "") or ""),
                        por=por,
                    )
            else:
                antes = dict(apunte.get("antes") or {})
                despues = dict(apunte.get("despues") or {})
                for campo, valor in antes.items():
                    if despues.get(campo) != valor:
                        setattr(fila, campo, _de_json(modelo, campo, valor))

    if not simular:
        from crmcore.audit.chain import registrar

        db.flush()
        importacion.revertida_at = datetime.now(timezone.utc)
        importacion.revertida_por = por
        importacion.reversion = {**resumen, "forzada": forzar}
        registrar(
            db,
            accion="datos.importacion_revertida",
            objeto=importacion.objeto,
            objeto_id=importacion.id,
            datos={k: v for k, v in resumen.items() if k != "conflictos"}
            | {"conflictos": len(resumen["conflictos"]), "forzada": forzar},
            motivo=motivo,
        )
        logger.info(
            "datos.importacion_revertida",
            objeto=importacion.objeto,
            borrados=resumen["borrados"],
            restaurados=resumen["restaurados"],
            conflictos=len(resumen["conflictos"]),
        )
    return resumen
