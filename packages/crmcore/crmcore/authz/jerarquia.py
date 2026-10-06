"""La jerarquía de mando y los territorios, replicados a cada servicio
(CRM-00.05.02.12, CRM-00.05.02.07).

Esto cierra un hueco que el propio manual llevaba tiempo declarando: la
compartición por jerarquía **no aplicaba en los listados** de `party` ni de
`sales`. Un responsable veía lo suyo, lo de los equipos de cuenta en los que
estaba y lo que le compartieran, pero no lo de sus subordinados por serlo. El
motivo era arquitectónico y correcto: `superior_id` vive en la membresía, que es
de `identity`, y ningún servicio lee el esquema de otro.

La solución es la misma que ya se usa para los ajustes en caliente y para la
clave del tenant: **replicar**. Cada servicio tiene una copia pequeña de lo que
necesita para decidir, alimentada por evento.

Las decisiones:

**Se replica lo mínimo.** Quién depende de quién y quién está en qué territorio.
Ni nombres, ni correos, ni roles: lo que no hace falta para decidir no se copia,
porque una réplica es otra copia del dato personal que hay que proteger.

**Una réplica vieja se nota y se dice.** Si el evento no llega, la jerarquía se
queda como estaba y un responsable que acaba de heredar un equipo no lo ve. Eso
es molesto; lo que sería grave es lo contrario —que alguien que ya no manda siga
viendo—, y por eso cada fila lleva cuándo se actualizó y hay una consulta que
dice cuánto hace de la última.

**Los ciclos se cortan.** «A depende de B y B depende de A» es un error de datos
que ocurre, y sin cortarlo el cálculo de subordinados no termina nunca.

**Y la profundidad se acota.** Una jerarquía de doce niveles es real; una de mil
es un bucle que alguien creó sin querer.

**El territorio hereda hacia abajo, no hacia arriba.** Quien lleva «Europa» ve lo
de «España»; quien lleva «España» no ve lo del resto de Europa. Al revés es el
error clásico, y se nota tarde: cuando alguien pregunta por qué un comercial veía
la cartera entera.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import (
    DateTime,
    Index,
    String,
    UniqueConstraint,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from crmcore.db.base import Base
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Tope de niveles al recorrer hacia abajo. Doce es una organización real grande;
# mil es un bucle que alguien creó sin querer, y recorrerlo entero deja la
# consulta colgada con todo el mundo esperando.
PROFUNDIDAD_MAXIMA = 12


class MandoReplicado(Base):
    """Quién depende de quién, copiado al esquema de este servicio.

    Es una proyección: la verdad está en la membresía de `identity` y aquí solo
    vive lo justo para decidir una visibilidad sin preguntarle a nadie.
    """

    __tablename__ = "mando_replicado"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    usuario_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    superior_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    # Cuándo llegó el último cambio. Sin esto no se puede distinguir «no tiene
    # subordinados» de «la réplica lleva tres semanas sin actualizarse».
    actualizado_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "usuario_id", name="uq_mando_replicado"),
        Index("ix_mando_superior", "tenant_id", "superior_id"),
    )


class TerritorioReplicado(Base):
    """Quién trabaja en qué territorio, y de quién cuelga cada territorio."""

    __tablename__ = "territorio_replicado"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    territorio_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    padre_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    usuario_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    clave: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    actualizado_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "territorio_id", "usuario_id", name="uq_territorio_replicado"
        ),
        Index("ix_territorio_padre", "tenant_id", "padre_id"),
    )


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def aplicar_mando(
    db: Session, *, tenant_id: UUID, usuario_id: UUID, superior_id: UUID | None
) -> MandoReplicado:
    """Anota un cambio de dependencia que llega por evento.

    Se acepta también `superior_id` nulo: alguien que deja de depender de nadie
    —porque asciende o porque se va— tiene que dejar de contarse como subordinado
    **ese mismo día**. Ignorar el nulo dejaría a su antiguo jefe viendo su cartera
    para siempre.
    """
    fila = (
        db.execute(
            select(MandoReplicado).where(
                MandoReplicado.tenant_id == tenant_id,
                MandoReplicado.usuario_id == usuario_id,
            )
        )
        .scalars()
        .first()
    )
    if fila is None:
        fila = MandoReplicado(tenant_id=tenant_id, usuario_id=usuario_id)
        db.add(fila)
    fila.superior_id = superior_id
    fila.actualizado_at = _ahora()
    db.flush()
    return fila


def aplicar_territorio(
    db: Session,
    *,
    tenant_id: UUID,
    territorio_id: UUID,
    padre_id: UUID | None = None,
    usuario_id: UUID | None = None,
    clave: str = "",
) -> TerritorioReplicado:
    """Anota un territorio o una pertenencia que llega por evento."""
    fila = (
        db.execute(
            select(TerritorioReplicado).where(
                TerritorioReplicado.tenant_id == tenant_id,
                TerritorioReplicado.territorio_id == territorio_id,
                TerritorioReplicado.usuario_id == usuario_id,
            )
        )
        .scalars()
        .first()
    )
    if fila is None:
        fila = TerritorioReplicado(
            tenant_id=tenant_id, territorio_id=territorio_id, usuario_id=usuario_id
        )
        db.add(fila)
    fila.padre_id = padre_id
    fila.clave = clave or fila.clave
    fila.actualizado_at = _ahora()
    db.flush()
    return fila


def quitar_territorio(
    db: Session, *, tenant_id: UUID, territorio_id: UUID, usuario_id: UUID
) -> int:
    """Saca a alguien de un territorio.

    Existe aparte porque salir de un territorio **quita visibilidad**, y eso no
    puede depender de que llegue un evento de alta que lo sustituya: entre los dos
    momentos, la persona seguiría viendo la cartera que ya no lleva.
    """
    filas = (
        db.execute(
            select(TerritorioReplicado).where(
                TerritorioReplicado.tenant_id == tenant_id,
                TerritorioReplicado.territorio_id == territorio_id,
                TerritorioReplicado.usuario_id == usuario_id,
            )
        )
        .scalars()
        .all()
    )
    for fila in filas:
        db.delete(fila)
    db.flush()
    return len(filas)


def aplicar_mapa(
    db: Session,
    *,
    tenant_id: UUID,
    territorio_id: UUID,
    padre_id: UUID | None,
    clave: str,
    usuarios: set[UUID],
) -> dict[str, int]:
    """Deja la copia de un territorio exactamente como dice el mapa publicado.

    Se aplica el mapa **entero**: los que están y, por diferencia, los que ya no.
    Replicar solo las altas dejaría a quien deja un territorio viendo su cartera
    para siempre, que es la mitad que de verdad importa.

    Está aquí y no en el consumidor de cada servicio porque la escriben dos
    sitios: el servicio que publica, en la misma transacción —no va a mandarse un
    evento a sí mismo para enterarse de lo que acaba de hacer—, y el que la
    recibe por el bus. Dos copias de este recorrido es cómo acaban dos servicios
    resolviendo el acceso de forma distinta.
    """
    estan = set(
        db.execute(
            select(TerritorioReplicado.usuario_id).where(
                TerritorioReplicado.tenant_id == tenant_id,
                TerritorioReplicado.territorio_id == territorio_id,
                TerritorioReplicado.usuario_id.is_not(None),
            )
        )
        .scalars()
        .all()
    )
    # El territorio en sí, con su padre: hace falta aunque no tenga a nadie,
    # porque de él cuelgan los de abajo.
    aplicar_territorio(
        db, tenant_id=tenant_id, territorio_id=territorio_id, padre_id=padre_id, clave=clave
    )
    for usuario in usuarios:
        aplicar_territorio(
            db,
            tenant_id=tenant_id,
            territorio_id=territorio_id,
            padre_id=padre_id,
            usuario_id=usuario,
            clave=clave,
        )
    quitados = 0
    for usuario in estan - usuarios:
        quitados += quitar_territorio(
            db, tenant_id=tenant_id, territorio_id=territorio_id, usuario_id=usuario
        )
    return {"con_acceso": len(usuarios), "quitados": quitados}


def subordinados_de(db: Session, tenant_id: UUID, usuario_id: UUID) -> set[UUID]:
    """Quién depende de este usuario, directa o indirectamente.

    Se recorre por niveles con un tope y cortando los ciclos. «A depende de B y B
    depende de A» es un error de datos que ocurre de verdad —dos cambios de
    organigrama el mismo día— y sin cortarlo esto no termina nunca, con todo el
    mundo esperando a que cargue un listado.
    """
    encontrados: set[UUID] = set()
    frontera = {usuario_id}
    for _ in range(PROFUNDIDAD_MAXIMA):
        if not frontera:
            break
        filas = (
            db.execute(
                select(MandoReplicado.usuario_id).where(
                    MandoReplicado.tenant_id == tenant_id,
                    MandoReplicado.superior_id.in_(frontera),
                )
            )
            .scalars()
            .all()
        )
        # Los ya vistos no se vuelven a expandir: eso es lo que corta el ciclo.
        siguiente = {u for u in filas if u not in encontrados and u != usuario_id}
        encontrados |= siguiente
        frontera = siguiente
    else:
        if frontera:
            logger.warning(
                "jerarquia.demasiado_profunda",
                tenant=str(tenant_id),
                usuario=str(usuario_id),
                tope=PROFUNDIDAD_MAXIMA,
            )
    return encontrados


def territorios_de(db: Session, tenant_id: UUID, usuario_id: UUID) -> set[UUID]:
    """Los territorios de esta persona **y los que cuelgan de ellos**.

    Hacia abajo y no hacia arriba: quien lleva «Europa» ve lo de «España», y
    quien lleva «España» no ve lo del resto de Europa. Al revés es el error
    clásico y se nota tarde — cuando alguien pregunta por qué un comercial veía
    la cartera entera.
    """
    propios = set(
        db.execute(
            select(TerritorioReplicado.territorio_id).where(
                TerritorioReplicado.tenant_id == tenant_id,
                TerritorioReplicado.usuario_id == usuario_id,
            )
        )
        .scalars()
        .all()
    )
    if not propios:
        return set()

    todos = set(propios)
    frontera = set(propios)
    for _ in range(PROFUNDIDAD_MAXIMA):
        if not frontera:
            break
        hijos = set(
            db.execute(
                select(TerritorioReplicado.territorio_id).where(
                    TerritorioReplicado.tenant_id == tenant_id,
                    TerritorioReplicado.padre_id.in_(frontera),
                )
            )
            .scalars()
            .all()
        )
        nuevos = hijos - todos
        todos |= nuevos
        frontera = nuevos
    return todos


def frescura(db: Session, tenant_id: UUID, *, horas_aviso: int = 24) -> dict[str, Any]:
    """Cuánto hace que no llega un cambio de organigrama a esta réplica.

    Una réplica vieja no es un fallo visible: todo funciona, y lo que pasa es que
    un responsable que heredó un equipo no lo ve. Sin esta consulta, eso se
    descubre cuando se queja él.
    """
    ultimo_mando = db.execute(
        select(func.max(MandoReplicado.actualizado_at)).where(MandoReplicado.tenant_id == tenant_id)
    ).scalar_one_or_none()
    ultimo_territorio = db.execute(
        select(func.max(TerritorioReplicado.actualizado_at)).where(
            TerritorioReplicado.tenant_id == tenant_id
        )
    ).scalar_one_or_none()
    cuantos = db.execute(
        select(func.count(MandoReplicado.id)).where(MandoReplicado.tenant_id == tenant_id)
    ).scalar_one()

    limite = _ahora() - timedelta(hours=max(1, horas_aviso))
    viejo = ultimo_mando is not None and _con_tz(ultimo_mando) < limite
    return {
        "filas_de_mando": int(cuantos or 0),
        "ultimo_cambio_de_mando": ultimo_mando.isoformat() if ultimo_mando else None,
        "ultimo_cambio_de_territorio": (
            ultimo_territorio.isoformat() if ultimo_territorio else None
        ),
        # Vacía y vieja no son lo mismo, y confundirlas lleva a dar por buena una
        # réplica que nunca se llenó.
        "vacia": not cuantos,
        "desactualizada": bool(viejo),
        "que_significa": (
            "La réplica está vacía: la jerarquía no aplica en este servicio, y eso "
            "no es que nadie tenga subordinados — es que no ha llegado ningún "
            "cambio de organigrama."
            if not cuantos
            else f"Sin cambios desde hace más de {horas_aviso} h. Puede ser normal "
            "—los organigramas no cambian a diario— o puede ser que el evento no "
            "esté llegando."
            if viejo
            else "Al día."
        ),
    }


def _con_tz(valor: datetime) -> datetime:
    return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)


def registrar_resolutores() -> None:
    """Conecta la jerarquía y los territorios replicados a la visibilidad.

    Lo llama cada servicio que tenga la réplica. Sin esto, las tablas estarían
    llenas y los listados seguirían sin aplicar la jerarquía — que es exactamente
    el hueco que este módulo cierra.
    """
    from crmcore.authz.visibilidad import registrar_resolutor

    def _subordinados(db: Session, principal: Any) -> set[UUID]:
        if principal is None or principal.id is None or principal.tenant_id is None:
            return set()
        return subordinados_de(db, principal.tenant_id, principal.id)

    registrar_resolutor("subordinados", _subordinados)
    logger.info("jerarquia.resolutor_registrado")
