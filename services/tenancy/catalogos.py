"""Catálogos de configuración del tenant: plantillas, calendarios y monedas.

Van en `tenancy` y no en cada servicio porque son **transversales**: la misma
plantilla de correo la usan ventas y soporte, el mismo calendario laboral decide
los relojes de SLA y las fechas de vencimiento de una tarea, y la misma tabla de
cambio convierte importes de oportunidades y de facturas. Repartirlos
garantizaría tres calendarios ligeramente distintos y una conversación sobre
cuál es el bueno.

Cubre CRM-07.01.01.04 (plantillas), CRM-07.01.01.05 (calendarios laborales,
festivos y husos) y CRM-07.01.01.06 (monedas y tipos de cambio con histórico).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.db.base import Base, TimestampMixin
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import (
    Boolean,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

logger = get_logger(__name__)


# ── Plantillas (CRM-07.01.01.04) ──────────────────────────────────────────


class Plantilla(Base, TimestampMixin):
    """Plantilla de correo, documento o notificación.

    Versionada y con **idioma**: un tenant que opera en tres países necesita la
    misma plantilla en tres idiomas, y tenerlas como tres plantillas distintas
    hace que se desincronicen en cuanto alguien cambia una.
    """

    __tablename__ = "plantillas"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    clave: Mapped[str] = mapped_column(String(120), nullable=False)
    idioma: Mapped[str] = mapped_column(String(10), nullable=False, default="es")
    # correo | documento | notificacion | sms
    tipo: Mapped[str] = mapped_column(String(20), nullable=False, default="correo")
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)

    asunto: Mapped[str | None] = mapped_column(String(300), nullable=True)
    cuerpo: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Variables que la plantilla espera, declaradas. Sirven para dos cosas:
    # enseñar al editor qué puede usar, y avisar al guardar si la plantilla usa
    # una que no existe — que es como se manda un correo con «Hola {{nombre}}».
    variables: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Bloqueada: la marca el tenant para que nadie la edite sin pasar por
    # aprobación (cumplimiento por marca y país).
    bloqueada: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "clave", "idioma", name="uq_plantilla_clave_idioma"),
        Index("ix_plantillas_tenant", "tenant_id", "tipo", "activa"),
    )


def render(plantilla: Plantilla, datos: dict[str, Any], *, db: Any = None) -> tuple[str, str]:
    """Sustituye `{{variable}}` en asunto y cuerpo, con los formatos del tenant.

    Las fechas y los importes se localizan ANTES de sustituir (CRM-00.01.04.07).
    Sin eso, un correo generado desde una plantilla enseña
    `2026-09-19 07:00:00+00:00` en mitad de una frase — que es la forma más
    rápida de que un cliente deje de confiar en los avisos automáticos. El
    idioma de la plantilla manda sobre el del contexto cuando lo declara: quien
    eligió la plantilla en portugués quiere las fechas en portugués.

    Sustitución de texto y **nada más**: sin condicionales, bucles ni expresiones.
    Una plantilla es dato del tenant, y un motor con lógica sería ejecutar código
    del cliente dentro del servidor de correo. Para lo que necesita lógica está
    la automatización, que sí está acotada y auditada.

    Lo que falta se deja **visible** (`{{variable}}`) en vez de vaciarse: un
    hueco vacío en un correo pasa desapercibido y se manda; un `{{nombre}}` en
    mitad del texto se ve y se corrige.
    """
    import re

    from crmcore import i18n

    loc = i18n.resolver(db)
    if plantilla.idioma and plantilla.idioma != loc.idioma:
        loc = i18n.Localizacion(
            idioma=plantilla.idioma,
            zona=str(loc.zona),
            formato_fecha=_clave_formato(loc),
            moneda=loc.moneda,
            primer_dia=loc.primer_dia,
        )
    datos = i18n.formatear_valores(datos, loc)

    def _sustituir(texto: str) -> str:
        def _uno(m: "re.Match[str]") -> str:
            clave = m.group(1).strip()
            valor = datos
            for parte in clave.split("."):
                if isinstance(valor, dict):
                    valor = valor.get(parte)
                else:
                    valor = getattr(valor, parte, None)
                if valor is None:
                    return m.group(0)
            return str(valor)

        return re.sub(r"\{\{\s*([\w.]+)\s*\}\}", _uno, texto)

    return _sustituir(plantilla.asunto or ""), _sustituir(plantilla.cuerpo or "")


def _clave_formato(loc: Any) -> str:
    """La clave de ajuste que corresponde al patrón ya resuelto.

    Se necesita para reconstruir una localización con otro idioma sin perder el
    formato de fecha que eligió el tenant: cambiar de idioma no debe cambiar
    cómo se escribe una fecha, que es una decisión aparte.
    """
    from crmcore.i18n import FORMATO_FECHA_POR_DEFECTO, FORMATOS_FECHA

    for clave, patron in FORMATOS_FECHA.items():
        if patron == loc.formato_fecha:
            return clave
    return FORMATO_FECHA_POR_DEFECTO


def variables_sin_resolver(texto: str, datos: dict[str, Any]) -> list[str]:
    """Variables que quedarían sin sustituir. Para avisar ANTES de enviar."""
    import re

    faltan: list[str] = []
    for coincidencia in re.finditer(r"\{\{\s*([\w.]+)\s*\}\}", texto or ""):
        clave = coincidencia.group(1).strip()
        valor: Any = datos
        for parte in clave.split("."):
            valor = valor.get(parte) if isinstance(valor, dict) else getattr(valor, parte, None)
            if valor is None:
                faltan.append(clave)
                break
    return sorted(set(faltan))


# ── Calendarios laborales (CRM-07.01.01.05) ───────────────────────────────
#
# El modelo y el cálculo de horas laborables viven en el núcleo y NO aquí. Se
# movieron al montar los relojes de SLA (CRM-04.01.02.04): `service` no puede
# leer el esquema de `tenancy`, y un reloj que preguntara por HTTP en cada paso
# del cálculo pondría el vencimiento de un caso a depender de otro servicio. La
# tabla vive en el esquema de cada servicio y se replica por evento; se
# administra aquí y se lee en todos.
from crmcore.datos.calendario import (  # noqa: E402,F401
    CALENDARIO_CAMBIADO,
    CalendarioLaboral,
    Festivo,
    es_laborable,
    sumar_horas_laborables,
)

# ── Monedas y tipos de cambio (CRM-07.01.01.06) ───────────────────────────
#
# El modelo y la conversión viven en el núcleo y NO aquí. Se movieron al montar
# la previsión multi-moneda (CRM-03.02.01.07): `sales` no puede leer el esquema
# de `tenancy` —lo impide el gate de arquitectura— así que la tabla vive en el
# esquema de cada servicio y se replica por evento, igual que los ajustes en
# caliente. Esto se reexporta para que la API de administración de aquí siga
# siendo la misma: los tipos se administran en un sitio aunque se lean en todos.
from crmcore.datos.cambio import (  # noqa: E402,F401
    TIPO_CAMBIO_FIJADO,
    TipoCambio,
    convertir,
    fijar_tipo_cambio,
)
