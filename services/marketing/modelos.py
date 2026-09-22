"""Modelo de datos de marketing: segmentos, supresiones y puntuación.

Cubre CRM-02.01.01 (segmentación) y CRM-02.01.02 (calificación de leads).

La decisión que gobierna todo: **un segmento es una definición, no una lista**.
Guardar la lista de quién está dentro parece más rápido y es lo que hace que a la
semana esté desfasada sin que nadie lo sepa. La lista se calcula cuando se pide, y
solo se congela cuando alguien decide congelarla — porque un envío ya hecho tiene
que poder decir a quién se mandó.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from crmcore.db.base import Base, TimestampMixin
from crmcore.ids import nuevo_id
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column


class PerfilMarketing(Base, TimestampMixin):
    """Proyección local de a quién se puede segmentar.

    **Por qué existe.** `marketing` no puede leer el esquema de `party` ni el de
    `sales` —lo impide el gate de arquitectura, y con razón—, y las otras dos
    salidas eran peores: pedirle a `party` cien mil contactos por HTTP cada vez
    que alguien calcula el tamaño de un segmento, o saltarse la regla. Así que la
    tabla vive aquí y se rellena por evento, igual que los ajustes en caliente,
    los tipos de cambio, los calendarios y el esquema del tenant.

    Lo que se replica es **lo que sirve para segmentar**, no la ficha entera:
    identidad, atributos de calificación, marcas de actividad y los campos
    propios del tenant. Copiar la ficha completa convertiría esta tabla en una
    segunda base de clientes, con su propia deriva y su propio problema de
    borrado.

    El precio, y se dice: un segmento se calcula sobre lo replicado, así que un
    contacto creado hace dos segundos puede no estar todavía. Para marketing eso
    es aceptable —una campaña no se lanza en el mismo segundo en que entra un
    lead— y a cambio el cálculo no depende de que otro servicio esté en pie.
    """

    __tablename__ = "perfiles_marketing"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    # contacto | lead | cuenta
    objeto: Mapped[str] = mapped_column(String(20), nullable=False)
    objeto_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)

    email: Mapped[str | None] = mapped_column(
        String(320), nullable=True, index=True, info={"sensibilidad": "personal"}
    )
    telefono: Mapped[str | None] = mapped_column(
        String(40), nullable=True, info={"sensibilidad": "personal"}
    )
    nombre: Mapped[str | None] = mapped_column(String(300), nullable=True)
    pais: Mapped[str | None] = mapped_column(String(2), nullable=True)
    sector: Mapped[str | None] = mapped_column(String(120), nullable=True)
    cargo: Mapped[str | None] = mapped_column(String(150), nullable=True)
    origen: Mapped[str | None] = mapped_column(String(60), nullable=True)
    estado: Mapped[str | None] = mapped_column(String(40), nullable=True)
    cuenta_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True, index=True)
    owner_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    empleados: Mapped[int | None] = mapped_column(Integer, nullable=True)
    facturacion: Mapped[Any] = mapped_column(Numeric(18, 2), nullable=True)

    # Marcas de tiempo para los operadores temporales. Van como columnas y no
    # dentro del JSONB porque son por las que más se filtra —«creados en los
    # últimos 30 días», «sin actividad en 6 meses»— y en JSONB cada una de esas
    # consultas recorrería la tabla entera.
    alta_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ultima_actividad_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ultima_compra_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Campos propios del tenant (CRM-00.04.03.03): el campo que un consultor
    # añadió en la implantación tiene que poder usarse para segmentar sin
    # escribir código, o la promesa de la extensión sin código se queda a medias
    # justo donde más se nota.
    campos: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # Fuera del alcance: borrado en origen. Se marca en vez de borrarse aquí para
    # que un segmento congelado siga pudiendo explicar a quién incluía.
    baja: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sincronizado_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "objeto", "objeto_id", name="uq_perfil_marketing"),
        Index("ix_perfiles_objeto", "tenant_id", "objeto", "baja"),
        Index("ix_perfiles_alta", "tenant_id", "objeto", "alta_at"),
    )


class Segmento(Base, TimestampMixin):
    """Una audiencia definida por condiciones (CRM-02.01.01.01, .03).

    `dinamico` decide lo único que importa de verdad aquí: un segmento dinámico
    se recalcula al consultarlo y uno estático se congela. Los dos hacen falta y
    por motivos opuestos — el dinámico para que «clientes activos» signifique lo
    que significa hoy, y el estático para que «a quién se le mandó la campaña de
    marzo» siga siendo cierto en junio.
    """

    __tablename__ = "segmentos"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(80), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Sobre qué objeto se segmenta: contacto, lead, cuenta.
    objeto: Mapped[str] = mapped_column(String(40), nullable=False, default="contacto")
    # Árbol de condiciones. Anidado (CRM-02.01.01.02): {"op":"y","hijos":[…]}.
    # Anidado y no una lista plana porque «(A o B) y no C» es la consulta normal
    # en marketing, y con una lista plana solo se puede expresar «todo y» o «todo
    # o» — y entonces el segmento se parte en tres que nadie mantiene iguales.
    definicion: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    dinamico: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Segmentos cuyos miembros se restan de este. Es distinto de una condición
    # negada: excluir «clientes» de «prospectos» es una operación entre
    # audiencias y se lee así; meterlo como condición obliga a duplicar la
    # definición del otro segmento dentro de este.
    excluye: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )

    # Último recuento, con su momento. Se guarda para poder enseñar el tamaño sin
    # recalcular en cada listado, **y se enseña con la fecha**: un número sin
    # fecha al lado se lee como actual aunque sea de hace tres semanas.
    tamano: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tamano_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "clave", name="uq_segmento_clave"),
        Index("ix_segmentos_objeto", "tenant_id", "objeto", "activo"),
    )


class MiembroSegmento(Base):
    """Miembro congelado de un segmento estático (CRM-02.01.01.03).

    Solo existe para los estáticos. Guardar los miembros de un dinámico sería
    tener dos verdades: la definición y la lista, que divergen al primer cambio
    de datos y nadie sabe cuál mirar.
    """

    __tablename__ = "miembros_segmento"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    segmento_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("segmentos.id", ondelete="CASCADE"), nullable=False
    )
    objeto_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    congelado_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("segmento_id", "objeto_id", name="uq_miembro_segmento"),
        Index("ix_miembros_segmento", "tenant_id", "segmento_id"),
    )


class Supresion(Base, TimestampMixin):
    """Alguien a quien no se le manda nada, pase lo que pase
    (CRM-02.01.01.06).

    Es una tabla aparte y **se aplica siempre**, por encima de cualquier
    segmento. Si fuera una condición más, bastaría con que alguien montara un
    segmento sin acordarse de ponerla para escribirle a quien pidió que no se le
    escribiera — y eso, además de una multa, es la clase de error que el cliente
    cuenta a los demás.

    El motivo se guarda porque los tres tipos se tratan distinto: quien se dio de
    baja puede volver a suscribirse, quien rebotó duro puede corregir su correo,
    y quien se quejó por spam no debe recibir nada nunca más.
    """

    __tablename__ = "supresiones"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    # Se suprime por dirección y no por identificador: la misma persona puede
    # estar en tres fichas duplicadas, y suprimir una sola dejaría que las otras
    # dos le siguieran escribiendo.
    canal: Mapped[str] = mapped_column(String(20), nullable=False, default="email")
    direccion: Mapped[str] = mapped_column(
        String(320), nullable=False, info={"sensibilidad": "personal"}
    )
    # baja | rebote_duro | queja | manual | lista_negra
    motivo: Mapped[str] = mapped_column(String(30), nullable=False, default="baja")
    detalle: Mapped[str | None] = mapped_column(Text, nullable=True)
    contacto_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    # Ámbito: global o solo para un tipo de comunicación. La baja selectiva
    # —«no quiero la newsletter pero sí los avisos de servicio»— es lo que evita
    # que alguien se dé de baja de todo por no poder darse de baja de una cosa.
    ambito: Mapped[str] = mapped_column(String(40), nullable=False, default="global")
    # Irreversible desde la API: una queja por spam no se deshace con un clic.
    permanente: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "canal", "direccion", "ambito", name="uq_supresion"),
        Index("ix_supresiones_direccion", "tenant_id", "canal", "direccion"),
    )


class ModeloPuntuacion(Base, TimestampMixin):
    """Cómo se puntúa un lead (CRM-02.01.02.01, .03, .04, .05).

    Dos ejes y no uno: **encaje** (¿es el cliente que buscamos?) e **interés**
    (¿nos está haciendo caso?). Fundirlos en un número es el error clásico del
    lead scoring: un estudiante que abre diez correos suma lo mismo que un
    director de compras que abrió uno, y ventas deja de fiarse de la lista a la
    tercera vez que le pasan un lead que no compra nunca.
    """

    __tablename__ = "modelos_puntuacion"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(80), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Reglas de interés: [{"condicion": {...}, "puntos": 10, "nombre": "…"}]
    reglas_interes: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Reglas de encaje con el perfil de cliente ideal.
    reglas_encaje: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )

    # Decaimiento (CRM-02.01.02.04): puntos que se pierden por cada periodo sin
    # actividad. Solo afecta al interés: el encaje no decae —que alguien sea
    # director de compras de una empresa de 500 personas no deja de ser cierto
    # porque lleve dos meses sin abrir un correo—.
    decaimiento_puntos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    decaimiento_dias: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    interes_minimo: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Umbrales (CRM-02.01.02.05). Se exigen **los dos ejes** para pasar a MQL:
    # con uno solo, o se pasan estudiantes muy activos o directores que no han
    # mostrado ningún interés.
    umbral_mql_interes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    umbral_mql_encaje: Mapped[int | None] = mapped_column(Integer, nullable=True)
    umbral_sql_interes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    umbral_sql_encaje: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Letra de grado por tramo de encaje: [{"desde": 80, "grado": "A"}, …]
    grados: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "clave", "version", name="uq_modelo_puntuacion"),
    )


class PuntuacionLead(Base):
    """La puntuación calculada de un lead, con su desglose.

    Se guarda **el desglose y no solo el número**. «Este lead tiene 87» no le
    sirve a nadie: lo que hace que un comercial llame es saber que descargó el
    comparativo de precios y visitó la página de contratación dos veces. Sin el
    porqué, el número es un adorno y la lista deja de mirarse.
    """

    __tablename__ = "puntuaciones_lead"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    lead_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    modelo: Mapped[str] = mapped_column(String(80), nullable=False)
    modelo_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    interes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    encaje: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    grado: Mapped[str | None] = mapped_column(String(4), nullable=True)
    # ninguno | mql | sql
    calificacion: Mapped[str] = mapped_column(String(10), nullable=False, default="ninguno")
    # [{"regla": "…", "eje": "interes", "puntos": 10}]
    desglose: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    decaido: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ultima_actividad_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    calculado_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "lead_id", name="uq_puntuacion_lead"),
        Index("ix_puntuaciones_calificacion", "tenant_id", "calificacion", "interes"),
    )


# ── Tablas compartidas que viven en ESTE esquema ──────────────────────────
from crmcore.authz.comparticion import ComparticionManual, ReglaComparticion  # noqa: E402
from crmcore.authz.politicas import PoliticaAbac, VersionPoliticaAbac  # noqa: E402
from crmcore.authz.proyeccion import PoliticaCampo  # noqa: E402
from crmcore.datos.calendario import CalendarioLaboral, Festivo  # noqa: E402
from crmcore.datos.cambio import TipoCambio  # noqa: E402
from crmcore.datos.papelera import EntradaPapelera  # noqa: E402
from crmcore.datos.retencion import BloqueoLegal, PoliticaRetencion  # noqa: E402
from crmcore.datos.trabajos import Trabajo  # noqa: E402
from crmcore.metamodelo import EsquemaTenant, UsoCampo  # noqa: E402
from crmcore.runtime.versiones import VersionAjuste  # noqa: E402
from crmcore.security.byok import ClaveTenant  # noqa: E402

from services.marketing.campanas import (  # noqa: E402
    Campana,
    ContactoEnviado,
    MiembroCampana,
    Rebote,
    ReglaFatiga,
    ToqueCampana,
)

__all__ = [
    "Campana",
    "ContactoEnviado",
    "MiembroCampana",
    "Rebote",
    "ReglaFatiga",
    "ToqueCampana",
    "BloqueoLegal",
    "PerfilMarketing",
    "CalendarioLaboral",
    "ClaveTenant",
    "ComparticionManual",
    "EntradaPapelera",
    "EsquemaTenant",
    "Festivo",
    "MiembroSegmento",
    "ModeloPuntuacion",
    "PoliticaAbac",
    "PoliticaCampo",
    "PoliticaRetencion",
    "PuntuacionLead",
    "ReglaComparticion",
    "Segmento",
    "Supresion",
    "TipoCambio",
    "Trabajo",
    "UsoCampo",
    "VersionAjuste",
    "VersionPoliticaAbac",
]

# Los recorridos y el correo viven en sus propios módulos —cada uno con su
# lógica— pero sus tablas son de este esquema y tienen que importarse aquí.
# Las actividades de tratamiento de este servicio (CRM-07.03.01.04). Se importa
# al final y solo por su efecto: declararlas al cargar los modelos es lo que
# garantiza que el RAT y los objetos no puedan separarse.
from services.marketing import tratamientos  # noqa: E402,F401
from services.marketing.canales import (  # noqa: E402,F401
    Canal,
    ConsentimientoCanal,
    DominioEnvio,
    Landing,
    PlantillaCanal,
)
from services.marketing.correo import (  # noqa: E402,F401
    BloqueCorreo,
    CategoriaPreferencia,
    PlantillaMarketing,
    Preferencia,
)
from services.marketing.fondos import (  # noqa: E402,F401
    FondoMdf,
    JustificacionMdf,
    PartnerConocido,
    SolicitudMdf,
)
from services.marketing.recorridos import (  # noqa: E402,F401
    EnRecorrido,
    PasoRecorrido,
    Recorrido,
)
