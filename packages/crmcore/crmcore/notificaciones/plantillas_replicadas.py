"""Plantillas de notificación replicadas al servicio que reparte
(CRM-06.02.01.07).

Cierra otro de los huecos que el manual declaraba: el repartidor **no
renderizaba plantillas** porque son de `tenancy` y ningún servicio lee el esquema
de otro, así que el mismo texto iba al correo y al SMS —recortado a 160 en el
segundo—. La consecuencia la sufría el destinatario: un aviso pensado para correo
llegaba al móvil cortado a mitad de frase.

La solución es la misma que para la jerarquía de mando y los ajustes en caliente:
**replicar lo justo**. Aquí, la plantilla por clave, idioma y canal.

Las decisiones:

**Se replica por canal, que es el punto.** Una plantilla de correo y una de SMS
no son la misma con menos letras: la de SMS dice lo imprescindible y pone un
enlace, y la de correo puede explicarse. Replicar solo el cuerpo del correo y
recortarlo habría sido el mismo problema con más pasos.

**Si no hay plantilla, se compone como antes y se dice.** Un aviso sin plantilla
tiene que salir igual: el mecanismo de plantillas existe para que se vea mejor,
no para que el aviso dependa de que alguien la haya creado.

**Una plantilla que pide una variable que no llega no se manda a medias.** «Hola
{{nombre}}» llegando así es peor que un texto genérico, porque el genérico no
parece roto.

**Y el idioma cae hacia atrás con orden**, no a cualquiera: el del destinatario,
el del tenant y el de la instalación. Elegir «la primera que haya» manda un aviso
en alemán a alguien que pidió español.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
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

from crmcore.db.base import Base
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger

logger = get_logger(__name__)

RE_VARIABLE = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")

CANALES = ("correo", "sms", "push", "chat")


class PlantillaNotificacion(Base):
    """Una plantilla de aviso, copiada al esquema del servicio que reparte."""

    __tablename__ = "plantillas_notificacion_replicadas"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(120), nullable=False)
    idioma: Mapped[str] = mapped_column(String(10), nullable=False, default="es")
    canal: Mapped[str] = mapped_column(String(20), nullable=False, default="correo")
    asunto: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    cuerpo: Mapped[str] = mapped_column(Text, nullable=False, default="")
    variables: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    actualizado_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "clave", "idioma", "canal", name="uq_plantilla_notificacion_replicada"
        ),
        Index("ix_plantillas_replicadas", "tenant_id", "clave", "canal"),
    )


def aplicar(
    db: Session,
    *,
    tenant_id: UUID,
    clave: str,
    idioma: str,
    canal: str,
    asunto: str = "",
    cuerpo: str = "",
    variables: list[str] | None = None,
    activa: bool = True,
) -> PlantillaNotificacion:
    """Anota una plantilla que llega por evento desde su servicio dueño."""
    fila = (
        db.execute(
            select(PlantillaNotificacion).where(
                PlantillaNotificacion.tenant_id == tenant_id,
                PlantillaNotificacion.clave == clave,
                PlantillaNotificacion.idioma == idioma,
                PlantillaNotificacion.canal == canal,
            )
        )
        .scalars()
        .first()
    )
    if fila is None:
        fila = PlantillaNotificacion(tenant_id=tenant_id, clave=clave, idioma=idioma, canal=canal)
        db.add(fila)
    fila.asunto = asunto
    fila.cuerpo = cuerpo
    fila.variables = list(variables or [])
    fila.activa = activa
    fila.actualizado_at = datetime.now(timezone.utc)
    db.flush()
    return fila


def elegir(
    db: Session,
    tenant_id: UUID,
    *,
    clave: str,
    canal: str,
    idiomas: list[str],
) -> PlantillaNotificacion | None:
    """La plantilla que toca, cayendo hacia atrás **con orden**.

    `idiomas` llega ordenado por quien sabe: el del destinatario, el del tenant y
    el de la instalación. Elegir «la primera que haya» mandaría un aviso en
    alemán a alguien que pidió español, y eso se lee como un error del sistema.
    """
    for idioma in idiomas:
        fila = (
            db.execute(
                select(PlantillaNotificacion).where(
                    PlantillaNotificacion.tenant_id == tenant_id,
                    PlantillaNotificacion.clave == clave,
                    PlantillaNotificacion.canal == canal,
                    PlantillaNotificacion.idioma == idioma,
                    PlantillaNotificacion.activa.is_(True),
                )
            )
            .scalars()
            .first()
        )
        if fila is not None:
            return fila
    return None


def render(plantilla: PlantillaNotificacion, datos: dict[str, Any]) -> dict[str, Any]:
    """Rellena la plantilla, o dice por qué no se puede.

    **No se manda a medias.** «Hola {{nombre}}» llegando así es peor que un texto
    genérico, porque el genérico no parece roto y este sí — y quien lo recibe
    deduce que el sistema del que viene está mal cuidado.
    """
    pedidas = sorted(set(RE_VARIABLE.findall(plantilla.cuerpo + " " + (plantilla.asunto or ""))))
    faltan = [v for v in pedidas if _leer(datos, v) in (None, "")]
    if faltan:
        return {
            "sirve": False,
            "faltan": faltan,
            "porque": (
                f"La plantilla «{plantilla.clave}» pide {faltan} y no han llegado. "
                "Se compone el aviso sin plantilla: mandarlo con los marcadores "
                "sin sustituir es peor que un texto genérico, porque parece roto."
            ),
        }

    def _sustituir(texto: str) -> str:
        for variable in pedidas:
            texto = RE_VARIABLE.sub(
                lambda m, v=variable: str(_leer(datos, m.group(1)) or ""), texto
            )
        return texto

    return {
        "sirve": True,
        "asunto": _sustituir(plantilla.asunto or ""),
        "cuerpo": _sustituir(plantilla.cuerpo),
        "idioma": plantilla.idioma,
        "canal": plantilla.canal,
    }


def _leer(datos: dict[str, Any], camino: str) -> Any:
    actual: Any = datos
    for parte in camino.split("."):
        if not isinstance(actual, dict):
            return None
        actual = actual.get(parte)
    return actual
