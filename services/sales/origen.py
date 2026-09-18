"""Trazabilidad de origen: de dónde salió cada lead (CRM-01.01.03.06).

La pregunta que responde es «¿qué campaña trajo a este cliente?», y se contesta
mal casi siempre por el mismo motivo: se guarda **un** origen, el de la última
visita, porque es el que viene en la petición donde el formulario se envió. Con
eso, todo el mérito se lo lleva la búsqueda de marca —la última visita antes de
convertir casi siempre es «buscó nuestro nombre en Google»— y las campañas que
de verdad descubrieron al cliente parecen no servir para nada.

Por eso aquí se guardan **todos los toques** y se conservan explícitamente el
**primero y el último**. El primero explica cómo llegó; el último, qué lo cerró.
Los dos hacen falta, y ninguno de los dos se puede reconstruir después.

**Alcance**: esto es la **trazabilidad**, no los modelos de atribución. Repartir
el mérito entre los toques —lineal, en U, en W, por decaimiento— es
CRM-02.02.01.06 y llega con marketing en la fase 4. Lo que se hace ahora es
guardar el dato con la forma que esos modelos van a necesitar; sin el recorrido
completo, en la fase 4 no habría nada que repartir y se empezaría a contar desde
cero.

**Nada por proveedor.** Los parámetros son los `utm_*`, que son un estándar de
hecho y no de una casa. Los identificadores de clic —los que añade cada red al
volver de un anuncio— se guardan en un diccionario abierto: no hay una lista de
nombres conocidos que haya que ampliar cada vez que aparece una red nueva.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from crmcore.db.base import Base
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import (
    DateTime,
    Index,
    String,
    Text,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

logger = get_logger(__name__)

# Los cinco parámetros `utm_*`. Se nombran aquí para traducirlos a las columnas
# sin depender de que quien llama use un nombre u otro: llega tanto
# `utm_source` como `source`, porque el formulario de un cliente manda lo que
# manda y rechazarlo por el prefijo sería perder el dato entero.
CAMPOS_UTM = {
    "source": "fuente",
    "medium": "medio",
    "campaign": "campana",
    "term": "termino",
    "content": "contenido",
}


class Toque(Base):
    """Una interacción atribuible: una visita, un clic, una apertura, una feria.

    Append-only. Un toque es un hecho que ocurrió en un instante; editarlo sería
    reescribir el pasado, y corregir el recorrido de un lead a mano es
    exactamente como se fabrica un informe de marketing que no se sostiene.
    """

    __tablename__ = "toques"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)

    # A quién pertenece. `lead_id` se rellena al identificar al visitante, así
    # que **es nulo al principio y eso es normal**: el toque que de verdad
    # importa —el primero— ocurre antes de que nadie sepa quién es.
    lead_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    # Identificador de primera parte del visitante (una cookie propia, no de un
    # tercero). Es el hilo que une lo que pasó antes de identificarse con lo que
    # pasó después. Sin él, el primer toque se pierde siempre.
    visitante_id: Mapped[str | None] = mapped_column(String(80), nullable=True)

    # web | correo | evento | telefono | referido | social | anuncio | otro
    canal: Mapped[str] = mapped_column(String(40), nullable=False, default="web")
    fuente: Mapped[str | None] = mapped_column(String(120), nullable=True)
    medio: Mapped[str | None] = mapped_column(String(120), nullable=True)
    campana: Mapped[str | None] = mapped_column(String(200), nullable=True)
    termino: Mapped[str | None] = mapped_column(String(300), nullable=True)
    contenido: Mapped[str | None] = mapped_column(String(300), nullable=True)

    campana_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    referrer: Mapped[str | None] = mapped_column(Text, nullable=True)
    landing: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Identificadores de clic, abiertos: `{"gclid": "...", "cualquiera": "..."}`.
    # Sin lista cerrada de redes conocidas, que habría que ampliar cada vez.
    identificadores_clic: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    ocurrio_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_toques_lead", "tenant_id", "lead_id", "ocurrio_at"),
        Index("ix_toques_visitante", "tenant_id", "visitante_id", "ocurrio_at"),
        Index("ix_toques_campana", "tenant_id", "campana", "ocurrio_at"),
    )


def normalizar(datos: dict[str, Any]) -> dict[str, Any]:
    """Traduce los parámetros de entrada a los campos del toque.

    Admite `utm_source` y `source` indistintamente. Rechazar la forma sin
    prefijo sería perder el dato entero por un detalle de cómo lo manda el
    formulario del cliente, y el dato perdido no se recupera.

    Lo que no se reconoce **no se descarta**: se queda en `identificadores_clic`.
    Ahí van los identificadores de clic de cualquier red, incluidas las que no
    existían cuando se escribió esto.
    """
    salida: dict[str, Any] = {}
    sobrantes: dict[str, Any] = {}

    for clave, valor in (datos or {}).items():
        if valor in (None, ""):
            continue
        limpia = str(clave).strip().lower()
        corta = limpia[4:] if limpia.startswith("utm_") else limpia
        campo = CAMPOS_UTM.get(corta)
        if campo:
            salida[campo] = str(valor)[:300]
        elif corta in ("canal", "referrer", "landing"):
            salida[corta] = str(valor)
        else:
            sobrantes[limpia] = str(valor)[:300]

    if sobrantes:
        salida["identificadores_clic"] = sobrantes
    return salida


def registrar_toque(
    db: Session,
    *,
    tenant_id: UUID,
    lead_id: UUID | None = None,
    visitante_id: str | None = None,
    ocurrio_at: datetime | None = None,
    **datos: Any,
) -> Toque:
    """Anota un toque. Necesita lead o visitante: sin ninguno, no es de nadie."""
    if lead_id is None and not visitante_id:
        raise ValueError("Un toque necesita un lead o un identificador de visitante")

    campos = normalizar(datos)
    toque = Toque(
        tenant_id=tenant_id,
        lead_id=lead_id,
        visitante_id=visitante_id,
        ocurrio_at=ocurrio_at or datetime.now(timezone.utc),
        canal=campos.pop("canal", "web"),
        campana_id=datos.get("campana_id"),
        **campos,
    )
    db.add(toque)
    db.flush()
    return toque


def adoptar_toques(db: Session, lead: Any, *, tenant_id: UUID) -> int:
    """Asocia al lead los toques anónimos de su visitante.

    Es el momento en que una visita anónima se convierte en alguien con nombre,
    y el único en que el recorrido anterior se puede recuperar. Se hace al crear
    el lead: un minuto después ya se perdió, porque nadie vuelve a mirar los
    toques huérfanos.

    La ventana la fija un ajuste y no una constante: treinta días vale para una
    venta de ciclo corto y se queda cortísima para una de obra, donde entre la
    primera visita y el formulario pasan meses.
    """
    from crmcore.runtime import settings as rt

    visitante = (lead.utm or {}).get("visitante_id") or getattr(lead, "_visitante_id", None)
    if not visitante:
        return 0

    dias = int(rt.efectivo("origen_ventana_dias", db) or 90)
    desde = datetime.now(timezone.utc) - timedelta(days=dias)
    huerfanos = (
        db.execute(
            select(Toque)
            .where(
                Toque.tenant_id == tenant_id,
                Toque.visitante_id == str(visitante),
                Toque.lead_id.is_(None),
                Toque.ocurrio_at >= desde,
            )
            .order_by(Toque.ocurrio_at)
        )
        .scalars()
        .all()
    )
    for toque in huerfanos:
        toque.lead_id = lead.id
    if huerfanos:
        db.flush()
        logger.info("origen.toques_adoptados", lead=str(lead.id), toques=len(huerfanos))
    return len(huerfanos)


def _resumen(toque: Toque) -> dict[str, Any]:
    return {
        "canal": toque.canal,
        "fuente": toque.fuente,
        "medio": toque.medio,
        "campana": toque.campana,
        "termino": toque.termino,
        "contenido": toque.contenido,
        "campana_id": str(toque.campana_id) if toque.campana_id else None,
        "referrer": toque.referrer,
        "landing": toque.landing,
        "identificadores_clic": toque.identificadores_clic or {},
        "cuando": toque.ocurrio_at.isoformat() if toque.ocurrio_at else None,
    }


def recorrido(db: Session, *, tenant_id: UUID, lead_id: UUID) -> list[dict[str, Any]]:
    """Todos los toques del lead, del más antiguo al más reciente.

    En orden cronológico y no inverso: esto se lee como una historia —«llegó por
    un anuncio, volvió por un correo, cerró buscando la marca»— y al revés no se
    entiende.
    """
    filas = (
        db.execute(
            select(Toque)
            .where(Toque.tenant_id == tenant_id, Toque.lead_id == lead_id)
            .order_by(Toque.ocurrio_at)
        )
        .scalars()
        .all()
    )
    return [_resumen(t) for t in filas]


def fijar_primer_y_ultimo(db: Session, lead: Any, *, tenant_id: UUID) -> None:
    """Rellena `primer_toque` y `ultimo_toque` del lead desde sus toques.

    **El primero solo se escribe si está vacío.** Es lo que lo hace inmutable:
    un toque posterior no puede reescribir cómo llegó el cliente, por mucho que
    llegue más tarde con mejor información. El último, en cambio, se actualiza
    siempre — para eso está.

    Se guarda **desnormalizado en el lead** además de en la tabla de toques, y
    no es redundancia gratuita: los listados de leads enseñan el origen, y
    resolverlo con una subconsulta por fila convierte una lista de mil leads en
    mil consultas.
    """
    filas = (
        db.execute(
            select(Toque)
            .where(Toque.tenant_id == tenant_id, Toque.lead_id == lead.id)
            .order_by(Toque.ocurrio_at)
        )
        .scalars()
        .all()
    )
    if not filas:
        return

    if not lead.primer_toque:
        lead.primer_toque = _resumen(filas[0])
    lead.ultimo_toque = _resumen(filas[-1])

    # `origen` y `campana_id` del lead salen del PRIMER toque: son la respuesta
    # a «¿de dónde salió este cliente?», que es una pregunta sobre el origen y
    # no sobre lo último que hizo.
    if not lead.origen and filas[0].fuente:
        lead.origen = filas[0].fuente[:80]
    if lead.campana_id is None and filas[0].campana_id is not None:
        lead.campana_id = filas[0].campana_id


def por_campana(
    db: Session, *, tenant_id: UUID, desde: datetime | None = None
) -> list[dict[str, Any]]:
    """Cuántos leads trajo cada campaña, por primer y por último toque.

    Se dan **las dos cifras**, y esa es la gracia. Con solo la del último toque,
    la búsqueda de marca se lleva todo el mérito y las campañas que descubrieron
    al cliente parecen no servir. Con solo la del primero, no se ve qué cerró.
    Enseñarlas juntas es lo que hace visible la diferencia.

    No es un modelo de atribución: no reparte el mérito, lo cuenta dos veces
    desde dos puntos de vista. Los modelos llegan con marketing (CRM-02.02.01.06).
    """
    from services.sales.modelos import Lead

    consulta = select(Lead).where(Lead.tenant_id == tenant_id, Lead.deleted_at.is_(None))
    if desde is not None:
        consulta = consulta.where(Lead.created_at >= desde)

    primeros: dict[str, int] = {}
    ultimos: dict[str, int] = {}
    for lead in db.execute(consulta).scalars().all():
        clave_p = (lead.primer_toque or {}).get("campana") or "(sin campaña)"
        clave_u = (lead.ultimo_toque or {}).get("campana") or "(sin campaña)"
        primeros[clave_p] = primeros.get(clave_p, 0) + 1
        ultimos[clave_u] = ultimos.get(clave_u, 0) + 1

    return sorted(
        (
            {
                "campana": campana,
                "primer_toque": primeros.get(campana, 0),
                "ultimo_toque": ultimos.get(campana, 0),
            }
            for campana in set(primeros) | set(ultimos)
        ),
        key=lambda f: (-f["primer_toque"], f["campana"]),
    )


def _huella(datos: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(datos.get(k) for k in ("fuente", "medio", "campana", "termino", "contenido"))


def registrar_alta(db: Session, lead: Any, *, tenant_id: UUID) -> int:
    """Registra el origen que llega con el alta del lead y adopta lo anterior.

    Devuelve cuántos toques tiene el lead al terminar.

    El envío del formulario **también es un toque**, pero si el cliente ya envió
    la visita a esa misma página con los mismos parámetros, sería el mismo hecho
    contado dos veces — y con eso la campaña aparecería con el doble de leads
    que trajo. Por eso solo se crea si su huella difiere de la del último toque
    adoptado.
    """
    utm = dict(lead.utm or {})
    visitante = utm.pop("visitante_id", None)
    if visitante:
        # Se guarda aparte para que `adoptar_toques` lo encuentre, y se deja
        # también en `utm`: perderlo impediría enlazar los toques posteriores.
        lead._visitante_id = str(visitante)

    adoptados = adoptar_toques(db, lead, tenant_id=tenant_id)

    campos = normalizar(utm)
    if campos:
        ultimo = (
            db.execute(
                select(Toque)
                .where(Toque.tenant_id == tenant_id, Toque.lead_id == lead.id)
                .order_by(Toque.ocurrio_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            if adoptados
            else None
        )
        if ultimo is None or _huella(campos) != _huella(_resumen(ultimo)):
            registrar_toque(
                db,
                tenant_id=tenant_id,
                lead_id=lead.id,
                visitante_id=str(visitante) if visitante else None,
                **utm,
            )

    fijar_primer_y_ultimo(db, lead, tenant_id=tenant_id)
    return int(
        db.execute(
            select(func.count())
            .select_from(Toque)
            .where(Toque.tenant_id == tenant_id, Toque.lead_id == lead.id)
        ).scalar_one()
    )
