"""Marca blanca: el producto con la cara del cliente (CRM-00.01.04.06).

Poner un logo es fácil; lo que cuesta es que **no se escape la marca del
fabricante por ningún sitio**. Se escapa siempre por los mismos cuatro: el
remitente de los correos, el dominio de los enlaces, el pie de las plantillas y
el título de la pestaña del navegador. Con uno solo de los cuatro mal, el cliente
descubre a su proveedor en el peor momento — delante de su propio cliente.

Las decisiones:

**Se valida que el conjunto esté completo antes de activarla.** Una marca blanca
a medias es peor que ninguna: si se anuncia y el correo sale con el dominio del
fabricante, la conversación que sigue no es sobre el correo.

**El dominio propio no se da por bueno hasta que se comprueba.** Un dominio sin
verificar hace que los correos acaben en spam o que los enlaces no lleven a
ninguna parte, y las dos cosas parecen un fallo del producto.

**Los colores se guardan con su contraste comprobado.** Una paleta corporativa
preciosa con texto gris sobre blanco deja media aplicación ilegible, y quien la
eligió no lo ve porque la mira en su pantalla buena.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.db.base import Base, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
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

RE_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")

# Por dónde se escapa la marca del fabricante. Esta lista ES la capacidad: poner
# el logo es lo fácil, y lo que descubre al proveedor son estos cuatro.
PUNTOS_DE_FUGA = (
    "remitente_correo",
    "dominio_enlaces",
    "pie_plantillas",
    "titulo_navegador",
)

# Contraste mínimo de texto sobre fondo. 4.5 es el de WCAG AA para texto normal:
# por debajo, media aplicación es ilegible para bastante gente y quien eligió la
# paleta no lo ve porque la mira en su pantalla buena.
CONTRASTE_MINIMO = 4.5


class MarcaTenant(Base, TimestampMixin):
    """La identidad visual y de correo de un tenant."""

    __tablename__ = "marca_tenants"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    nombre_producto: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    logo_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    favicon_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    color_principal: Mapped[str] = mapped_column(String(7), nullable=False, default="")
    color_texto: Mapped[str] = mapped_column(String(7), nullable=False, default="")
    color_fondo: Mapped[str] = mapped_column(String(7), nullable=False, default="")

    dominio_propio: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    dominio_verificado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    dominio_envio: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    dominio_envio_verificado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    remitente: Mapped[str] = mapped_column(String(320), nullable=False, default="")
    pie_correo: Mapped[str] = mapped_column(Text, nullable=False, default="")

    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    activada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    extra: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_marca_tenant"),
        Index("ix_marca_activa", "activa"),
    )


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _luminancia(color: str) -> float:
    """Luminancia relativa de un color, según la fórmula de WCAG."""
    valores = []
    for i in (1, 3, 5):
        canal = int(color[i : i + 2], 16) / 255
        valores.append(canal / 12.92 if canal <= 0.03928 else ((canal + 0.055) / 1.055) ** 2.4)
    return 0.2126 * valores[0] + 0.7152 * valores[1] + 0.0722 * valores[2]


def contraste(texto: str, fondo: str) -> float:
    """Relación de contraste entre dos colores.

    Se calcula y no se estima a ojo: la paleta la elige alguien mirando su
    pantalla buena, y quien sufre el resultado es quien tiene una mala o ve peor.
    """
    if not RE_COLOR.match(texto) or not RE_COLOR.match(fondo):
        raise ErrorValidacion(
            "Los colores tienen que ser hexadecimales de seis dígitos (#RRGGBB)",
            error_code="marca.color_invalido",
        )
    a, b = _luminancia(texto), _luminancia(fondo)
    claro, oscuro = max(a, b), min(a, b)
    return (claro + 0.05) / (oscuro + 0.05)


def guardar(
    uow: UnidadDeTrabajo,
    *,
    tenant_id: UUID,
    nombre_producto: str = "",
    logo_url: str = "",
    favicon_url: str = "",
    color_principal: str = "",
    color_texto: str = "",
    color_fondo: str = "",
    dominio_propio: str = "",
    dominio_envio: str = "",
    remitente: str = "",
    pie_correo: str = "",
) -> MarcaTenant:
    """Guarda la marca del tenant, **sin activarla**.

    Guardar y activar van separados a propósito: se configura por partes, en
    varias sesiones, y activar a medias es lo que hace que el primer correo salga
    con el dominio del fabricante.
    """
    for nombre, color in (
        ("color_principal", color_principal),
        ("color_texto", color_texto),
        ("color_fondo", color_fondo),
    ):
        if color and not RE_COLOR.match(color):
            raise ErrorValidacion(
                f"«{nombre}» no es un color hexadecimal de seis dígitos",
                error_code="marca.color_invalido",
            )

    fila = (
        uow.db.execute(select(MarcaTenant).where(MarcaTenant.tenant_id == tenant_id))
        .scalars()
        .first()
    )
    if fila is None:
        fila = MarcaTenant(tenant_id=tenant_id)
        uow.db.add(fila)

    anterior_dominio = fila.dominio_propio
    anterior_envio = fila.dominio_envio
    fila.nombre_producto = nombre_producto or fila.nombre_producto
    fila.logo_url = logo_url or fila.logo_url
    fila.favicon_url = favicon_url or fila.favicon_url
    fila.color_principal = color_principal or fila.color_principal
    fila.color_texto = color_texto or fila.color_texto
    fila.color_fondo = color_fondo or fila.color_fondo
    fila.dominio_propio = dominio_propio or fila.dominio_propio
    fila.dominio_envio = dominio_envio or fila.dominio_envio
    fila.remitente = remitente or fila.remitente
    fila.pie_correo = pie_correo or fila.pie_correo

    # Cambiar un dominio lo deja SIN verificar: el anterior estaba comprobado y
    # este no, y arrastrar la marca de verificado haría que los correos salieran
    # por un dominio que nadie ha comprobado.
    if dominio_propio and dominio_propio != anterior_dominio:
        fila.dominio_verificado = False
    if dominio_envio and dominio_envio != anterior_envio:
        fila.dominio_envio_verificado = False
    uow.db.flush()
    return fila


def comprobar(db: Session, tenant_id: UUID) -> dict[str, Any]:
    """Qué falta para poder activar la marca blanca.

    Los cuatro puntos de fuga, uno a uno. Con cualquiera mal, el cliente descubre
    a su proveedor en el peor momento; y el peor momento es siempre delante de su
    propio cliente.
    """
    fila = (
        db.execute(select(MarcaTenant).where(MarcaTenant.tenant_id == tenant_id)).scalars().first()
    )
    if fila is None:
        raise NoEncontrado("Este tenant no tiene marca configurada", error_code="marca.no_existe")

    faltan: list[dict[str, str]] = []
    if not fila.remitente or not fila.dominio_envio:
        faltan.append(
            {
                "punto": "remitente_correo",
                "porque": "Sin remitente propio, cada correo lleva la dirección del fabricante",
            }
        )
    elif not fila.dominio_envio_verificado:
        faltan.append(
            {
                "punto": "remitente_correo",
                "porque": (
                    "El dominio de envío no está verificado: los correos acabarán en "
                    "spam, y eso parece un fallo del producto"
                ),
            }
        )
    if not fila.dominio_propio:
        faltan.append(
            {
                "punto": "dominio_enlaces",
                "porque": "Los enlaces de los correos llevarían al dominio del fabricante",
            }
        )
    elif not fila.dominio_verificado:
        faltan.append(
            {
                "punto": "dominio_enlaces",
                "porque": "El dominio no está verificado: los enlaces no llevarían a ninguna parte",
            }
        )
    if not fila.pie_correo:
        faltan.append(
            {
                "punto": "pie_plantillas",
                "porque": "El pie por defecto nombra al fabricante",
            }
        )
    if not fila.nombre_producto:
        faltan.append(
            {
                "punto": "titulo_navegador",
                "porque": "La pestaña del navegador enseñaría el nombre del producto original",
            }
        )

    aviso_contraste = ""
    if fila.color_texto and fila.color_fondo:
        ratio = contraste(fila.color_texto, fila.color_fondo)
        if ratio < CONTRASTE_MINIMO:
            aviso_contraste = (
                f"El contraste del texto sobre el fondo es {ratio:.1f}:1 y el mínimo "
                f"legible es {CONTRASTE_MINIMO}:1. La paleta se elige mirando una "
                "pantalla buena; quien sufre el resultado es quien tiene una mala."
            )

    return {
        "tenant_id": str(tenant_id),
        "puntos_de_fuga": list(PUNTOS_DE_FUGA),
        "faltan": faltan,
        "se_puede_activar": not faltan,
        "aviso_contraste": aviso_contraste,
        # **Lo que la interfaz tiene que pintar**, y no sólo el diagnóstico.
        #
        # Esta respuesta decía qué FALTA para poder activar la marca y no decía
        # cuál es, así que el front no tenía de dónde leerla: sacaba el nombre,
        # el color y el logotipo de `config.json`, que es del DESPLIEGUE. Dos
        # tenants en la misma instalación compartían marca, y la capacidad dice
        # «por tenant». Medido el 26-10-2026.
        #
        # Sólo cuando está ACTIVA: una marca a medias pisando la del despliegue
        # es exactamente lo que esta misma función existe para evitar.
        "aplicable": (
            {
                "nombre_producto": fila.nombre_producto,
                "logo_url": fila.logo_url,
                "favicon_url": fila.favicon_url,
                "color_principal": fila.color_principal,
                "color_texto": fila.color_texto,
                "color_fondo": fila.color_fondo,
            }
            if fila.activa
            else {}
        ),
        "que_significa": (
            "No se escapa la marca del fabricante por ninguno de los cuatro puntos."
            if not faltan
            else "Activarla ahora dejaría escapar la marca del fabricante. Una marca "
            "blanca a medias es peor que ninguna: si se anuncia y el correo sale con "
            "el dominio de origen, la conversación que sigue no es sobre el correo."
        ),
    }


def verificar_dominio(
    uow: UnidadDeTrabajo, *, tenant_id: UUID, cual: str, verificado: bool, detalle: str = ""
) -> MarcaTenant:
    """Anota el resultado de comprobar un dominio.

    La comprobación de DNS la hace quien sabe hacerla; aquí se guarda el
    resultado, porque es lo que decide si se puede activar la marca.
    """
    if cual not in ("propio", "envio"):
        raise ErrorValidacion(
            "Solo hay dos dominios: «propio» y «envio»", error_code="marca.dominio_invalido"
        )
    fila = (
        uow.db.execute(select(MarcaTenant).where(MarcaTenant.tenant_id == tenant_id))
        .scalars()
        .first()
    )
    if fila is None:
        raise NoEncontrado("Este tenant no tiene marca configurada", error_code="marca.no_existe")
    if cual == "propio":
        fila.dominio_verificado = verificado
    else:
        fila.dominio_envio_verificado = verificado
    fila.extra = {**(fila.extra or {}), f"verificacion_{cual}": detalle}
    uow.db.flush()
    return fila


def activar(uow: UnidadDeTrabajo, *, tenant_id: UUID) -> dict[str, Any]:
    """Enciende la marca blanca, **solo si está completa**."""
    estado = comprobar(uow.db, tenant_id)
    if not estado["se_puede_activar"]:
        from crmcore.errors import Conflicto

        raise Conflicto(
            "No se puede activar la marca blanca: faltan piezas y el producto "
            "seguiría enseñando la marca del fabricante.",
            error_code="marca.incompleta",
            detalle={"faltan": estado["faltan"]},
        )
    fila = (
        uow.db.execute(select(MarcaTenant).where(MarcaTenant.tenant_id == tenant_id))
        .scalars()
        .first()
    )
    fila.activa = True
    fila.activada_at = _ahora()
    uow.db.flush()
    logger.info("marca.activada", tenant=str(tenant_id))
    return {
        "tenant_id": str(tenant_id),
        "activa": True,
        "aviso_contraste": estado["aviso_contraste"],
    }
