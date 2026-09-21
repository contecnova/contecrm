"""Vocabularios de negocio que **decide el cliente**, no el código.

    from crmcore import vocabulario

    vocabulario.registrar("motivos_perdida", DEFECTOS, etiqueta="Motivos de pérdida")
    ...
    if motivo not in vocabulario.valores(db, "motivos_perdida"):
        raise ...

Un motivo de pérdida no es un estado de protocolo: es la forma que tiene una
empresa de contar por qué pierde. Escritos como una constante, los nueve que
trae el producto son los nueve que va a tener siempre ese cliente — y el primero
que quiere separar «precio» de «condiciones de pago» descubre que la pantalla
enseña la lista y no deja tocarla. Que es exactamente lo que pasaba.

**Cada servicio guarda el suyo, en su propio esquema.** La tabla es común, como
`ajustes_runtime`, y por el mismo motivo: ventas no puede preguntarle el
vocabulario a otro servicio en mitad de una validación. Los servicios no se
llaman entre sí, y hacerlo aquí ataría el cierre de una oportunidad a que otro
proceso esté vivo.

**Lo que trae el producto son los valores por defecto, no un límite.** Mientras
el tenant no toque nada, valen los de fábrica; en cuanto añade o quita uno, la
lista es suya entera. Sin esa caída, estrenar el vocabulario obligaría a
poblarlo antes de poder cerrar nada, y una instalación nueva no cerraría una
oportunidad hasta que alguien se acordara.

**Y se desactiva, no se borra.** Un valor borrado convierte el histórico en
códigos sin significado: los registros que lo usan tienen que seguir enseñando
su etiqueta.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Index, Integer, String, UniqueConstraint, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from crmcore.db.base import Base
from crmcore.ids import nuevo_id


class ValorVocabulario(Base):
    """Un valor de un vocabulario, tal como lo tiene este tenant."""

    __tablename__ = "valores_vocabulario"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    vocabulario: Mapped[str] = mapped_column(String(80), nullable=False)
    valor: Mapped[str] = mapped_column(String(120), nullable=False)
    etiqueta: Mapped[str] = mapped_column(String(200), nullable=False)
    orden: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Lo que cada vocabulario necesite colgar de un valor: un color, si es
    # terminal, a qué código mapea en el ERP del cliente.
    extra: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "vocabulario", "valor", name="uq_valor_vocabulario"),
        Index("ix_valores_vocabulario", "tenant_id", "vocabulario", "activo"),
    )


@dataclass(frozen=True)
class Vocabulario:
    """Un vocabulario declarado por un servicio."""

    nombre: str
    etiqueta: str
    defectos: tuple[str, ...]
    descripcion: str = ""


_REGISTRO: dict[str, Vocabulario] = {}


def registrar(
    nombre: str,
    defectos: frozenset[str] | set[str] | tuple[str, ...],
    *,
    etiqueta: str,
    descripcion: str = "",
) -> None:
    """Declara un vocabulario y los valores con los que se estrena.

    Se llama al importar el módulo que lo usa, y no en el arranque, para que la
    validación y la pantalla no puedan discrepar: el que valida es el mismo que
    se registra.
    """
    _REGISTRO[nombre] = Vocabulario(
        nombre=nombre,
        etiqueta=etiqueta,
        defectos=tuple(sorted(defectos)),
        descripcion=descripcion,
    )


def registrados() -> dict[str, Vocabulario]:
    """Los vocabularios que declara este servicio."""
    return dict(_REGISTRO)


def definicion(nombre: str) -> Vocabulario | None:
    return _REGISTRO.get(nombre)


def filas(db: Session, nombre: str, *, incluir_inactivos: bool = False) -> list[ValorVocabulario]:
    """Lo que el tenant tiene guardado. Vacío si no ha tocado nada."""
    consulta = select(ValorVocabulario).where(ValorVocabulario.vocabulario == nombre)
    if not incluir_inactivos:
        consulta = consulta.where(ValorVocabulario.activo.is_(True))
    return list(
        db.execute(consulta.order_by(ValorVocabulario.orden, ValorVocabulario.etiqueta))
        .scalars()
        .all()
    )


def valores(db: Session, nombre: str) -> frozenset[str]:
    """Los valores admitidos AHORA: los del tenant, o los de fábrica."""
    propios = {f.valor for f in filas(db, nombre)}
    if propios:
        return frozenset(propios)
    definida = _REGISTRO.get(nombre)
    return frozenset(definida.defectos) if definida else frozenset()


def como_lista(
    db: Session, nombre: str, *, incluir_inactivos: bool = False
) -> list[dict[str, Any]]:
    """El vocabulario para enseñarlo: valor, etiqueta, orden y de dónde sale.

    `de_fabrica` va en cada fila a propósito. Sin él, la pantalla enseña nueve
    motivos y no hay forma de saber si son los que trae el producto o los que
    eligió la empresa — y esa diferencia es justo la que decide si tiene sentido
    tocarlos.
    """
    guardados = filas(db, nombre, incluir_inactivos=incluir_inactivos)
    if guardados:
        return [
            {
                "id": f.valor,
                "valor": f.valor,
                "etiqueta": f.etiqueta,
                "orden": f.orden,
                "activo": f.activo,
                "extra": f.extra,
                "de_fabrica": False,
            }
            for f in guardados
        ]
    definida = _REGISTRO.get(nombre)
    if definida is None:
        return []
    return [
        {
            "id": v,
            "valor": v,
            "etiqueta": _humanizar(v),
            "orden": (i + 1) * 10,
            "activo": True,
            "extra": {},
            "de_fabrica": True,
        }
        for i, v in enumerate(definida.defectos)
    ]


def _humanizar(valor: str) -> str:
    return valor.replace("_", " ").capitalize()


def materializar(db: Session, nombre: str, tenant_id: UUID) -> list[ValorVocabulario]:
    """Copia los valores de fábrica a la tabla, para poder editarlos.

    Se llama la primera vez que alguien toca un vocabulario que aún era el de
    fábrica. Sin esto, añadir un valor dejaría la lista con **uno solo**: el
    recién creado, porque tener algo guardado es lo que apaga los defectos. Es
    el fallo clásico de este patrón y se nota tarde, cuando ya se ha perdido el
    resto de la lista.
    """
    definida = _REGISTRO.get(nombre)
    if definida is None or filas(db, nombre, incluir_inactivos=True):
        return []
    creadas = [
        ValorVocabulario(
            tenant_id=tenant_id,
            vocabulario=nombre,
            valor=v,
            etiqueta=_humanizar(v),
            orden=(i + 1) * 10,
        )
        for i, v in enumerate(definida.defectos)
    ]
    db.add_all(creadas)
    db.flush()
    return creadas
