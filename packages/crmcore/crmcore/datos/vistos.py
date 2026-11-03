"""Lo que cada persona ha abierto hace poco (CRM-07.04.01.03).

**Por qué existe.** Comparado con Salesforce el 03-11-2026, era el hueco más
caro de los que quedaban: allí «Recently Viewed» es la vista por defecto de
cada objeto y lo primero que sale al pinchar el buscador, y se apoya en ello
casi toda la navegación del día. Aquí, para volver a la cuenta que se acababa
de mirar había que buscarla otra vez por su nombre.

**No sale de la auditoría, y es deliberado.** La tabla `auditoria` es una
cadena encadenada por hash: es una prueba, no un historial de navegación.
Meterle una fila por cada registro abierto —decenas por persona y día— la
inunda de hechos que no prueban nada, y además hoy **no registra lecturas**:
medido, de las acciones que se auditan ninguna es «abrir una ficha». Derivarlo
de ahí habría sido construir sobre algo que no está.

**Una fila por persona y registro, no una por visita.** Lo que se pregunta es
«¿qué he mirado últimamente?», no «¿cuántas veces?». Con una fila por visita,
abrir diez veces la misma cuenta llenaría la lista con esa cuenta y escondería
las otras nueve — que es exactamente lo que la lista viene a enseñar.

**Aquí sólo se escribe.** Leer la lista es un listado raíz como cualquier
otro —página, cursor y orden— y vive con su router, no aquí: una segunda
función de lectura con su propio orden acabaría diciendo algo distinto que el
extremo, y la que se quedaría corta sería siempre la de abajo.

**Se poda al escribir.** Sin podar, la tabla crece con cada registro que cada
persona haya abierto alguna vez y la lista de los diez últimos acaba
ordenando cien mil filas. Se guardan las `VISTOS_POR_PERSONA` más recientes de
cada persona.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    DateTime,
    Index,
    String,
    UniqueConstraint,
    delete,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from crmcore.db.base import Base
from crmcore.ids import nuevo_id


def _tope() -> int:
    """Cuántas se guardan por persona: `VISTOS_POR_PERSONA` del `.env`.

    Estuvo como constante de módulo, con el argumento de que el tamaño de un
    historial de navegación no es una decisión de nadie. El guardián de
    umbrales lo rechazó y tiene razón: lo que cambia entre un despliegue de
    diez personas y uno de cincuenta mil es exactamente esto, y una constante
    obliga a tocar código para moverlo.
    """
    from crmcore.config import get_settings

    return int(get_settings().vistos_por_persona)


class RegistroVisto(Base):
    """Un registro que alguien abrió, con cuándo fue la última vez."""

    __tablename__ = "registros_vistos"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    usuario_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    objeto_tipo: Mapped[str] = mapped_column(String(60), nullable=False)
    objeto_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    # El nombre con el que se vio, guardado aquí a propósito.
    #
    # Lo alternativo es resolverlo al leer, pidiéndoselo a cada servicio dueño:
    # diez registros de cuatro tipos son cuatro llamadas más cada vez que
    # alguien pincha el buscador, que es lo que más se pincha. Y el registro
    # puede haberse borrado, y entonces no habría nada que enseñar aunque la
    # visita sí ocurrió. Se guarda, y se refresca en cada visita.
    nombre: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    # **`clock_timestamp()` y no `now()`.** En Postgres `now()` es la hora de
    # inicio de la TRANSACCIÓN, así que dos visitas dentro de la misma se
    # apuntan con el mismo instante y la lista no sabe cuál fue antes. Cazado
    # con la prueba de «una fila por registro»: abrir cuenta, caso y cuenta
    # otra vez dejaba el caso delante. `clock_timestamp()` es el reloj de
    # verdad y avanza dentro de la transacción.
    visto_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "usuario_id", "objeto_tipo", "objeto_id", name="uq_registro_visto"
        ),
        # Por donde se lee: las últimas de una persona, en orden.
        Index("ix_vistos_persona", "tenant_id", "usuario_id", "visto_at"),
    )


def anotar_visto(
    db: Session,
    *,
    tenant_id: UUID,
    usuario_id: UUID,
    objeto_tipo: str,
    objeto_id: UUID,
    nombre: str = "",
) -> RegistroVisto:
    """Apunta que alguien ha abierto un registro. Idempotente por registro.

    Si ya estaba, se le **actualiza la hora y el nombre**: el nombre porque la
    cuenta pudo renombrarse desde la última vez, y enseñar el de entonces
    mandaría a buscar algo que ya no se llama así.
    """
    ya = db.execute(
        select(RegistroVisto).where(
            RegistroVisto.tenant_id == tenant_id,
            RegistroVisto.usuario_id == usuario_id,
            RegistroVisto.objeto_tipo == objeto_tipo,
            RegistroVisto.objeto_id == objeto_id,
        )
    ).scalar_one_or_none()
    if ya is not None:
        # Con el reloj de la BASE y no con el de Python: la ordenación la hace
        # ella, y mezclar los dos relojes deja una visita de ahora mismo por
        # detrás de una de hace un minuto cuando no van iguales. Y
        # `clock_timestamp()` y no `now()`, por lo que dice el modelo.
        ya.visto_at = func.clock_timestamp()  # type: ignore[assignment]
        if nombre:
            ya.nombre = nombre[:300]
        # **Y se vuelve a leer.** Hasta que no se escribe, el atributo tiene
        # dentro la EXPRESIÓN de SQL, no una fecha, y quien devuelva esta fila
        # tal cual revienta al serializarla —«Input should be a valid
        # datetime»—. Lo cazó la prueba por HTTP; la de dentro no, porque no
        # llegaba a leer el campo.
        db.flush()
        db.refresh(ya, ["visto_at"])
        return ya

    fila = RegistroVisto(
        tenant_id=tenant_id,
        usuario_id=usuario_id,
        objeto_tipo=objeto_tipo,
        objeto_id=objeto_id,
        nombre=nombre[:300],
    )
    db.add(fila)
    db.flush()
    _podar(db, tenant_id=tenant_id, usuario_id=usuario_id)
    return fila


def _podar(db: Session, *, tenant_id: UUID, usuario_id: UUID) -> int:
    """Deja sólo las más recientes de esa persona. Devuelve cuántas quitó.

    Con subconsulta y no trayéndolas a memoria: lo que se borra puede ser una
    sola fila en el caso normal y miles la primera vez que alguien pasa el tope.
    """
    sobrantes = (
        select(RegistroVisto.id)
        .where(
            RegistroVisto.tenant_id == tenant_id,
            RegistroVisto.usuario_id == usuario_id,
        )
        .order_by(RegistroVisto.visto_at.desc())
        .offset(_tope())
        .scalar_subquery()
    )
    resultado = db.execute(delete(RegistroVisto).where(RegistroVisto.id.in_(sobrantes)))
    return int(resultado.rowcount or 0)
