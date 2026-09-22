"""Problemas e incidentes masivos: varios casos, una causa
(CRM-04.01.01.11).

Un caso maestro ya permitía colgar cien llamadas de una caída y cerrarlas juntas.
Lo que faltaba es lo que viene después: **la caída se arregla y la causa sigue
ahí**. El problema es el objeto que guarda la causa, y vive más que el incidente.

Tres decisiones:

**Problema e incidente son cosas distintas.** El incidente es «está caído ahora»;
el problema es «se cae cada tres semanas». Fundirlos hace que, al restablecer el
servicio, se cierre también la investigación — y la siguiente caída empieza de
cero, con la misma gente buscando lo mismo.

**Un apaño se declara apaño.** Reiniciar el servicio es una solución temporal, y
apuntarla como solución definitiva es cómo un problema desaparece de la lista sin
haberse resuelto. Aquí van separados, y el problema no se cierra con un apaño.

**Detectar que varios casos son lo mismo se propone, no se decide.** La
correlación mira coincidencias —misma categoría, mismo producto, misma ventana de
tiempo— y **sugiere**. Agrupar automáticamente cien casos que no eran lo mismo le
da a cien clientes una respuesta que no tiene que ver con su problema, y eso no se
deshace.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from crmcore.audit import registrar
from crmcore.db.base import Base, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

logger = get_logger(__name__)

# Estados de un problema.
#
#   investigando  se está buscando la causa
#   conocido      hay causa identificada y, normalmente, un apaño
#   resuelto      hay solución definitiva aplicada
#   cerrado       revisado y archivado
#   descartado    no era un problema (con motivo)
ESTADOS = ("investigando", "conocido", "resuelto", "cerrado", "descartado")


class Problema(Base, TimestampMixin):
    """Una causa que produce casos (CRM-04.01.01.11)."""

    __tablename__ = "problemas"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    codigo: Mapped[str | None] = mapped_column(String(30), nullable=True)
    titulo: Mapped[str] = mapped_column(String(300), nullable=False)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Sin `index=True`: lo cubre el compuesto de abajo, y los dos se llamarían
    # igual.
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="investigando")
    severidad: Mapped[str] = mapped_column(String(20), nullable=False, default="media")
    categoria_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    producto_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    responsable_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    # El caso maestro del incidente, si esto empezó como una caída. Puede no
    # haberlo: hay problemas que se detectan por patrón y no por una caída.
    caso_maestro_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    causa_raiz: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # El apaño va **separado** de la solución: apuntar un reinicio como solución
    # definitiva es cómo un problema desaparece de la lista sin resolverse.
    solucion_temporal: Mapped[str] = mapped_column(Text, nullable=False, default="")
    solucion_definitiva: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Error conocido: la causa está identificada aunque no se haya arreglado. Es
    # lo que permite que el agente que coge la llamada 101 sepa qué contestar.
    error_conocido: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    articulo_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    detectado_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    resuelto_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cerrado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    motivo_cierre: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (
        UniqueConstraint("tenant_id", "codigo", name="uq_problema_codigo"),
        Index("ix_problemas_estado", "tenant_id", "estado", "severidad"),
    )


class CasoDeProblema(Base):
    """Qué casos se atribuyen a un problema.

    Tabla propia y no un campo en el caso: un caso puede dejar de atribuirse a un
    problema cuando se descubre que era otra cosa, y con un campo esa corrección
    borraría el rastro de que alguna vez se creyó que sí.
    """

    __tablename__ = "casos_de_problema"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    problema_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("problemas.id", ondelete="CASCADE"), nullable=False
    )
    caso_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    # Quién lo enlazó: una persona o la correlación automática. Sirve para poder
    # medir si la correlación acierta, en vez de suponerlo.
    origen: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    desvinculado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    motivo_desvinculacion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "problema_id", "caso_id", name="uq_caso_de_problema"),
        Index("ix_casos_de_problema", "tenant_id", "problema_id"),
    )


class ComunicacionProblema(Base, TimestampMixin):
    """Lo que se les ha dicho a los afectados, y cuándo.

    Se guarda para que la comunicación de una caída **se pueda auditar**: en un
    incidente grande, «ya avisamos» sin fecha ni destinatarios es lo mismo que no
    haber avisado.
    """

    __tablename__ = "comunicaciones_problema"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    problema_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("problemas.id", ondelete="CASCADE"), nullable=False
    )
    # inicial | actualizacion | restablecido | postmortem
    tipo: Mapped[str] = mapped_column(String(20), nullable=False, default="actualizacion")
    mensaje: Mapped[str] = mapped_column(Text, nullable=False)
    casos_alcanzados: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    publicada_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    publicada_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    __table_args__ = (Index("ix_comunicaciones_problema", "tenant_id", "problema_id"),)


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _problema(db: Session, tenant_id: UUID, problema_id: UUID) -> Problema:
    fila = db.get(Problema, problema_id)
    if fila is None or fila.tenant_id != tenant_id:
        raise NoEncontrado("El problema no existe", error_code="problemas.no_encontrado")
    return fila


def abrir(
    uow: UnidadDeTrabajo,
    *,
    titulo: str,
    descripcion: str = "",
    severidad: str = "media",
    categoria_id: UUID | None = None,
    producto_id: UUID | None = None,
    responsable_id: UUID | None = None,
    caso_maestro_id: UUID | None = None,
    casos: list[UUID] | None = None,
) -> Problema:
    """Abre un problema, opcionalmente con los casos que ya se le atribuyen."""
    fila = Problema(
        tenant_id=uow.tenant_id,
        titulo=titulo.strip(),
        descripcion=descripcion,
        severidad=severidad,
        categoria_id=categoria_id,
        producto_id=producto_id,
        responsable_id=responsable_id,
        caso_maestro_id=caso_maestro_id,
    )
    uow.db.add(fila)
    uow.db.flush()
    cuantos = (
        uow.db.execute(
            select(func.count()).select_from(Problema).where(Problema.tenant_id == uow.tenant_id)
        )
    ).scalar_one()
    fila.codigo = f"PRB-{int(cuantos):05d}"
    for caso_id in casos or []:
        vincular(uow, fila.id, caso_id=caso_id)
    uow.emitir(
        "problem.opened",
        subject=("problema", fila.id),
        data={"problema_id": str(fila.id), "severidad": fila.severidad},
    )
    return fila


def vincular(
    uow: UnidadDeTrabajo, problema_id: UUID, *, caso_id: UUID, origen: str = "manual"
) -> CasoDeProblema:
    """Atribuye un caso a un problema."""
    # Importación diferida: `modelos` importa este módulo para que alembic vea sus
    # tablas, así que hacerlo arriba cerraría el círculo.
    from services.service.modelos import Caso

    problema = _problema(uow.db, uow.tenant_id, problema_id)
    caso = uow.db.get(Caso, caso_id)
    if caso is None or caso.tenant_id != uow.tenant_id:
        raise NoEncontrado("El caso no existe", error_code="problemas.caso_no_encontrado")
    ya = uow.db.execute(
        select(CasoDeProblema).where(
            CasoDeProblema.tenant_id == uow.tenant_id,
            CasoDeProblema.problema_id == problema.id,
            CasoDeProblema.caso_id == caso_id,
        )
    ).scalar_one_or_none()
    if ya is not None:
        if ya.desvinculado_at is None:
            return ya
        # Se vuelve a vincular lo que se desvinculó: el rastro de la
        # desvinculación se conserva, porque explica por qué se dudó.
        ya.desvinculado_at = None
        ya.motivo_desvinculacion = ""
        return ya
    fila = CasoDeProblema(
        tenant_id=uow.tenant_id, problema_id=problema.id, caso_id=caso_id, origen=origen
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila


def desvincular(
    uow: UnidadDeTrabajo, problema_id: UUID, *, caso_id: UUID, motivo: str
) -> CasoDeProblema:
    """Quita un caso del problema. Con motivo: normalmente significa que era otra
    cosa, y eso es información sobre la causa."""
    if not motivo.strip():
        raise ErrorValidacion(
            "Desvincular un caso exige motivo: casi siempre significa que era otra "
            "cosa, y eso es un dato sobre la causa.",
            error_code="problemas.motivo_obligatorio",
        )
    fila = uow.db.execute(
        select(CasoDeProblema).where(
            CasoDeProblema.tenant_id == uow.tenant_id,
            CasoDeProblema.problema_id == problema_id,
            CasoDeProblema.caso_id == caso_id,
        )
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado("Ese caso no está vinculado", error_code="problemas.no_vinculado")
    fila.desvinculado_at = _ahora()
    fila.motivo_desvinculacion = motivo.strip()
    return fila


def correlacionar(
    db: Session,
    tenant_id: UUID,
    *,
    ventana_horas: int = 4,
    minimo: int = 3,
    ahora: datetime | None = None,
) -> dict[str, Any]:
    """Propone grupos de casos que parecen la misma causa.

    **Propone, no agrupa.** Agrupar solo cien casos que no eran lo mismo le da a
    cien clientes una respuesta que no tiene que ver con su problema, y eso no se
    deshace: el cliente ya la ha leído.

    La coincidencia se mira por **categoría y producto dentro de una ventana de
    tiempo**. Es deliberadamente tosca: una correlación más lista acierta más y se
    explica peor, y aquí lo que hace falta es que quien la lea entienda en un
    segundo por qué se le propone eso.
    """
    from services.service.modelos import Caso

    momento = ahora or _ahora()
    desde = momento - timedelta(hours=ventana_horas)
    casos = (
        db.execute(
            select(Caso).where(
                Caso.tenant_id == tenant_id,
                Caso.created_at >= desde,
                Caso.estado.notin_(("cerrado",)),
                Caso.deleted_at.is_(None),
                Caso.maestro_id.is_(None),
            )
        )
        .scalars()
        .all()
    )
    ya_vinculados = {
        fila.caso_id
        for fila in db.execute(
            select(CasoDeProblema).where(
                CasoDeProblema.tenant_id == tenant_id,
                CasoDeProblema.desvinculado_at.is_(None),
            )
        ).scalars()
    }

    grupos: dict[tuple[str, str], list[Caso]] = {}
    for caso in casos:
        if caso.id in ya_vinculados:
            continue
        clave = (str(caso.categoria_id or ""), str(caso.linea or ""))
        grupos.setdefault(clave, []).append(caso)

    propuestas = []
    for (categoria, linea), miembros in grupos.items():
        if len(miembros) < minimo:
            continue
        propuestas.append(
            {
                "categoria_id": categoria or None,
                "linea": linea,
                "casos": [str(c.id) for c in miembros],
                "cuantos": len(miembros),
                "desde": min(c.created_at for c in miembros).isoformat(),
                "porque": (
                    f"{len(miembros)} casos de la misma categoría y línea en las "
                    f"últimas {ventana_horas} h"
                ),
            }
        )
    propuestas.sort(key=lambda p: -p["cuantos"])
    return {
        "ventana_horas": ventana_horas,
        "minimo": minimo,
        "propuestas": propuestas,
        "revisados": len(casos),
        # Sin casos que mirar no se dice que no haya incidentes: se dice que no
        # había nada abierto en la ventana.
        "medible": bool(casos),
    }


def registrar_causa(
    uow: UnidadDeTrabajo,
    problema_id: UUID,
    *,
    causa_raiz: str = "",
    solucion_temporal: str = "",
    solucion_definitiva: str = "",
    error_conocido: bool | None = None,
    articulo_id: UUID | None = None,
) -> Problema:
    """Anota lo que se sabe. El apaño y la solución van por separado."""
    fila = _problema(uow.db, uow.tenant_id, problema_id)
    if causa_raiz:
        fila.causa_raiz = causa_raiz
    if solucion_temporal:
        fila.solucion_temporal = solucion_temporal
    if solucion_definitiva:
        fila.solucion_definitiva = solucion_definitiva
    if articulo_id is not None:
        fila.articulo_id = articulo_id
    if error_conocido is not None:
        fila.error_conocido = error_conocido
    elif fila.causa_raiz and fila.solucion_temporal:
        # Con causa identificada y apaño, es un error conocido aunque no esté
        # arreglado: es lo que permite que quien coge la llamada 101 sepa qué
        # contestar.
        fila.error_conocido = True
    if fila.causa_raiz and fila.estado == "investigando":
        fila.estado = "conocido"
    return fila


def resolver(
    uow: UnidadDeTrabajo,
    problema_id: UUID,
    *,
    solucion_definitiva: str,
    cerrar_casos: bool = False,
    motivo_cierre: str = "",
) -> dict[str, Any]:
    """Da el problema por resuelto. **Exige solución definitiva, no un apaño.**

    Un problema que se cierra con «reiniciamos el servicio» desaparece de la lista
    y vuelve dentro de tres semanas con otro nombre. Si solo hay apaño, el
    problema se queda en `conocido`, que es la verdad.
    """
    if not solucion_definitiva.strip():
        raise ErrorValidacion(
            "Resolver un problema exige la solución definitiva. Si solo hay un "
            "apaño, el problema sigue abierto como error conocido.",
            error_code="problemas.solucion_obligatoria",
        )
    fila = _problema(uow.db, uow.tenant_id, problema_id)
    fila.solucion_definitiva = solucion_definitiva.strip()
    fila.estado = "resuelto"
    fila.resuelto_at = _ahora()

    cerrados: list[str] = []
    if cerrar_casos:
        from services.service.modelos import Caso
        from services.service.servicio import cerrar_caso

        for vinculo in uow.db.execute(
            select(CasoDeProblema).where(
                CasoDeProblema.tenant_id == uow.tenant_id,
                CasoDeProblema.problema_id == fila.id,
                CasoDeProblema.desvinculado_at.is_(None),
            )
        ).scalars():
            caso = uow.db.get(Caso, vinculo.caso_id)
            if caso is None or caso.estado == "cerrado":
                continue
            cerrar_caso(
                uow,
                caso.id,
                motivo=motivo_cierre or "resuelto_por_problema",
                resolucion=solucion_definitiva.strip(),
            )
            cerrados.append(str(caso.id))
    uow.db.flush()
    registrar(
        uow.db,
        accion="problema.resuelto",
        objeto="problema",
        objeto_id=fila.id,
        datos={"casos_cerrados": len(cerrados)},
        tenant_id=uow.tenant_id,
    )
    uow.emitir(
        "problem.resolved",
        subject=("problema", fila.id),
        data={"problema_id": str(fila.id), "casos_cerrados": len(cerrados)},
    )
    return {"problema_id": str(fila.id), "casos_cerrados": cerrados, "cuantos": len(cerrados)}


def comunicar(
    uow: UnidadDeTrabajo,
    problema_id: UUID,
    *,
    mensaje: str,
    tipo: str = "actualizacion",
    por: UUID | None = None,
) -> ComunicacionProblema:
    """Registra lo que se ha comunicado a los afectados, y a cuántos.

    En un incidente grande, «ya avisamos» sin fecha ni alcance es lo mismo que no
    haber avisado — y es lo primero que pregunta un cliente grande al día
    siguiente.
    """
    if not mensaje.strip():
        raise ErrorValidacion(
            "Una comunicación vacía no comunica nada.",
            error_code="problemas.mensaje_obligatorio",
        )
    fila = _problema(uow.db, uow.tenant_id, problema_id)
    alcanzados = (
        uow.db.execute(
            select(func.count())
            .select_from(CasoDeProblema)
            .where(
                CasoDeProblema.tenant_id == uow.tenant_id,
                CasoDeProblema.problema_id == fila.id,
                CasoDeProblema.desvinculado_at.is_(None),
            )
        )
    ).scalar_one()
    comunicacion = ComunicacionProblema(
        tenant_id=uow.tenant_id,
        problema_id=fila.id,
        tipo=tipo,
        mensaje=mensaje.strip(),
        casos_alcanzados=int(alcanzados),
        publicada_por=por,
    )
    uow.db.add(comunicacion)
    uow.db.flush()
    uow.emitir(
        "problem.communicated",
        subject=("problema", fila.id),
        data={
            "problema_id": str(fila.id),
            "tipo": tipo,
            "casos_alcanzados": int(alcanzados),
        },
    )
    return comunicacion


def impacto(db: Session, tenant_id: UUID, problema_id: UUID) -> dict[str, Any]:
    """A cuánta gente le ha pasado esto, y desde cuándo.

    Es el número con el que se prioriza. Se cuentan **los casos vinculados vivos**
    y aparte los que se desvincularon: si los desvinculados no se vieran, nadie
    sabría que la correlación se equivocó veinte veces.
    """
    from services.service.modelos import Caso

    problema = _problema(db, tenant_id, problema_id)
    vinculos = (
        db.execute(
            select(CasoDeProblema).where(
                CasoDeProblema.tenant_id == tenant_id,
                CasoDeProblema.problema_id == problema_id,
            )
        )
        .scalars()
        .all()
    )
    vivos = [v for v in vinculos if v.desvinculado_at is None]
    casos = (
        db.execute(select(Caso).where(Caso.id.in_([v.caso_id for v in vivos]))).scalars().all()
        if vivos
        else []
    )
    cuentas = {str(c.cuenta_id) for c in casos if c.cuenta_id}
    abiertos = [c for c in casos if c.estado != "cerrado"]
    comunicaciones = (
        db.execute(
            select(func.count())
            .select_from(ComunicacionProblema)
            .where(
                ComunicacionProblema.tenant_id == tenant_id,
                ComunicacionProblema.problema_id == problema_id,
            )
        )
    ).scalar_one()
    return {
        "problema_id": str(problema.id),
        "codigo": problema.codigo,
        "estado": problema.estado,
        "error_conocido": problema.error_conocido,
        "casos": len(vivos),
        "casos_abiertos": len(abiertos),
        "clientes": len(cuentas),
        "desvinculados": len(vinculos) - len(vivos),
        "automaticos": len([v for v in vivos if v.origen == "automatico"]),
        "comunicaciones": int(comunicaciones),
        "primer_caso": min((c.created_at for c in casos), default=None),
        # Un problema sin comunicaciones y con clientes afectados es el que
        # produce la llamada del día siguiente.
        "sin_comunicar": int(comunicaciones) == 0 and bool(cuentas),
        "solo_apano": bool(problema.solucion_temporal and not problema.solucion_definitiva),
    }
