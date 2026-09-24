"""Colas, agentes, asignación, escalado y derivación
(CRM-04.01.01.05, .06, .07, .08, CRM-04.02.02.03).

Reutiliza el enrutamiento de leads (`services/sales/enrutamiento.py`): las reglas
son datos, se evalúan por prioridad y gana la primera que encaja, y toda
asignación deja escrito por qué. Esa reutilización no es por ahorrar líneas — es
para que el operador aprenda una sola sintaxis de condición en todo el producto.

Lo que cambia respecto a un lead, y por qué hay módulo propio:

**Un caso tiene reloj.** Un lead sin asignar es una oportunidad que se enfría; un
caso sin asignar está consumiendo un SLA que alguien va a incumplir. Por eso la
asignación mira la **capacidad** del agente y no solo su turno: repartir a quien
ya tiene doce casos abiertos no es repartir, es esconder la cola.

**Un agente tiene presencia y canal.** Quien está en una llamada no puede atender
un chat, y quien está de baja no puede atender nada. Repartir a quien no está es
la forma más rápida de que un caso llegue tarde sin que nadie lo vea, porque en
la lista figura como asignado.

**El escalado se decide por lo que queda, no por lo que ha pasado.** Escalar
cuando el SLA ya se ha incumplido llega tarde por definición.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from uuid import UUID

from crmcore.audit import registrar
from crmcore.db.base import Base, EntidadBase, SoftDeleteMixin, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
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

logger = get_logger(__name__)

# `Caso` se importa DENTRO de las funciones y no arriba. El motivo es el orden de
# carga: `modelos.py` importa este módulo al final para que el generador de
# migraciones vea sus tablas, así que importarlo aquí arriba cerraría el círculo
# y el servicio no arrancaría. Anotar con `TYPE_CHECKING` da el tipado sin pagar
# el import en ejecución.
if TYPE_CHECKING:  # pragma: no cover
    from services.service.modelos import Caso

# Estados de presencia. `ausente` y `no_molestar` se distinguen a propósito: el
# primero es «no está» y el segundo es «está pero no puede». Fundirlos hace que
# un supervisor no pueda saber si le falta gente o le falta capacidad, que son
# dos problemas con soluciones opuestas.
PRESENCIAS = ("disponible", "ocupado", "ausente", "no_molestar", "fuera")
PRESENCIAS_ASIGNABLES = ("disponible", "ocupado")

CANALES = ("caso", "chat", "telefono", "correo")


class ColaCasos(Base, TimestampMixin, SoftDeleteMixin):
    """Una cola de trabajo (CRM-04.01.01.05).

    Existe aunque haya asignación automática, y no es redundante: la cola es
    **el sitio donde cae lo que no se ha podido asignar**. Sin ella, un caso que
    ninguna regla sabe repartir se queda sin dueño y sin lista, que es el único
    estado del que nadie se entera.
    """

    __tablename__ = "colas_casos"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(80), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Quién puede coger de esta cola. Lista de usuarios, resuelta aquí y no
    # consultada a identidad en caliente: la asignación corre en el camino de
    # entrada del caso, y una llamada de red ahí convierte una caída de identidad
    # en casos sin repartir.
    miembros: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    canales: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Competencias que exige. Un caso de facturación en alemán no puede caerle a
    # quien no factura ni habla alemán, por mucho turno que le toque.
    competencias: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    nivel: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (UniqueConstraint("tenant_id", "clave", name="uq_cola_casos"),)


class AgenteServicio(Base, TimestampMixin):
    """Presencia, capacidad y competencias de quien atiende
    (CRM-04.02.02.03).

    La capacidad es **por canal** y no un número único: alguien puede llevar tres
    chats a la vez y una sola llamada. Con un número único, o se infradotan los
    chats o se satura el teléfono.
    """

    __tablename__ = "agentes_servicio"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    usuario_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    presencia: Mapped[str] = mapped_column(String(20), nullable=False, default="fuera")
    presencia_desde: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    motivo_presencia: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # {"caso": 10, "chat": 3, "telefono": 1}
    capacidad: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    competencias: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    nivel: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (UniqueConstraint("tenant_id", "usuario_id", name="uq_agente_servicio"),)


class ReglaAsignacion(EntidadBase):
    """Regla de reparto de casos.

    Misma forma que las de leads a propósito: condiciones en el formato de
    `crmcore.authz.abac`, prioridad ascendente y gana la primera que encaja. Con
    varias que puntúan, explicar el resultado deja de ser posible y el supervisor
    pierde el control sobre su propio reparto.
    """

    __tablename__ = "reglas_asignacion_caso"

    nombre: Mapped[str] = mapped_column(String(150), nullable=False)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    prioridad: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    condiciones: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    combinacion: Mapped[str] = mapped_column(String(10), nullable=False, default="todas")
    # round_robin | menos_carga | menos_carga_ponderada | fijo
    estrategia: Mapped[str] = mapped_column(String(30), nullable=False, default="menos_carga")
    cola: Mapped[str | None] = mapped_column(String(80), nullable=True)
    candidatos: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    competencias: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    canal: Mapped[str] = mapped_column(String(20), nullable=False, default="caso")
    # Igual que en leads: el cursor va en la fila y no en memoria, porque el
    # servicio tiene varias réplicas y un contador en proceso repartiría todo al
    # mismo en cuanto escala.
    cursor_turno: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("tenant_id", "nombre", name="uq_regla_asignacion_caso"),
        Index("ix_reglas_asignacion_orden", "tenant_id", "activa", "prioridad"),
    )


class ReglaEscalada(Base, TimestampMixin, SoftDeleteMixin):
    """Cuándo y a quién se escala un caso (CRM-04.01.01.07)."""

    __tablename__ = "reglas_escalada"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    nombre: Mapped[str] = mapped_column(String(150), nullable=False)
    prioridad: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Disparadores. Se declaran por separado y no como una condición genérica
    # porque son los cuatro que se usan de verdad, y tenerlos explícitos es lo
    # que permite explicarle al cliente por qué se escaló su caso.
    # Porcentaje del SLA consumido a partir del cual escala.
    consumido_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    severidad_minima: Mapped[str | None] = mapped_column(String(20), nullable=True)
    solo_vip: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Escalar también cuando ya se ha incumplido: no sirve para llegar a tiempo,
    # pero sí para que alguien con autoridad hable con el cliente antes de que
    # llame él.
    al_incumplir: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Qué hacer. Subir de nivel, cambiar de dueño, avisar, o las tres.
    subir_nivel: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    asignar_a: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    cola_destino: Mapped[str | None] = mapped_column(String(80), nullable=True)
    avisar_a: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    subir_prioridad: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "nombre", name="uq_regla_escalada"),
        Index("ix_reglas_escalada_orden", "tenant_id", "activa", "prioridad"),
    )


class RegistroAsignacion(Base):
    """Por qué este caso acabó en manos de esta persona.

    Append-only y con las reglas descartadas dentro. Es lo que convierte el
    reparto automático en algo que se puede defender en una reunión: sin esto, la
    pregunta «¿por qué me ha caído a mí?» no tiene respuesta y el reparto deja de
    respetarse a la primera discusión.
    """

    __tablename__ = "registro_asignacion_caso"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    caso_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    regla_nombre: Mapped[str | None] = mapped_column(String(150), nullable=True)
    asignado_a: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    cola: Mapped[str | None] = mapped_column(String(80), nullable=True)
    estrategia: Mapped[str | None] = mapped_column(String(30), nullable=True)
    motivo: Mapped[str | None] = mapped_column(Text, nullable=True)
    evaluadas: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("clock_timestamp()"), nullable=False
    )

    __table_args__ = (Index("ix_registro_asignacion", "tenant_id", "caso_id", "created_at"),)


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _con_tz(valor: datetime | None) -> datetime | None:
    if valor is None:
        return None
    return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)


# ── Presencia y capacidad (CRM-04.02.02.03) ───────────────────────────────


def fijar_presencia(
    db: Session,
    tenant_id: UUID,
    usuario_id: UUID,
    *,
    presencia: str,
    motivo: str = "",
) -> AgenteServicio:
    """Cambia el estado del agente.

    Se guarda **desde cuándo**, no solo el estado: «lleva cuarenta minutos en no
    molestar» es una conversación distinta de «acaba de ponerse», y sin la marca
    de tiempo el supervisor no puede distinguirlas.
    """
    if presencia not in PRESENCIAS:
        raise ErrorValidacion(
            f"Presencia «{presencia}» no válida.",
            error_code="service.presencia_no_valida",
            detalle={"validas": list(PRESENCIAS)},
        )
    fila = db.execute(
        select(AgenteServicio).where(
            AgenteServicio.tenant_id == tenant_id, AgenteServicio.usuario_id == usuario_id
        )
    ).scalar_one_or_none()
    if fila is None:
        fila = AgenteServicio(tenant_id=tenant_id, usuario_id=usuario_id)
        db.add(fila)
    if fila.presencia != presencia:
        fila.presencia = presencia
        fila.presencia_desde = _ahora()
    fila.motivo_presencia = motivo or None
    db.flush()
    return fila


def carga_de(db: Session, tenant_id: UUID, usuarios: list[UUID]) -> dict[UUID, int]:
    """Casos abiertos por agente. Solo los abiertos cuentan como carga."""
    from services.service.modelos import Caso

    if not usuarios:
        return {}
    filas = db.execute(
        select(Caso.owner_id, func.count())
        .where(
            Caso.tenant_id == tenant_id,
            Caso.owner_id.in_(usuarios),
            Caso.estado.not_in(("resuelto", "cerrado")),
            Caso.deleted_at.is_(None),
        )
        .group_by(Caso.owner_id)
    ).all()
    return {u: int(c) for u, c in filas if u is not None}


def agentes_disponibles(  # noqa: D417
    db: Session,
    tenant_id: UUID,
    *,
    candidatos: list[UUID] | None = None,
    canal: str = "caso",
    competencias: list[str] | None = None,
) -> list[AgenteServicio]:
    """Quién puede coger un caso ahora mismo, de verdad (CRM-04.01.01.06).

    Es el enrutamiento omnicanal en su parte que importa: la capacidad se mira
    **por canal**, así que quien está al tope de chats puede seguir recibiendo
    correos y al revés. Un cupo único haría que atender tres chats bloqueara la
    bandeja de entrada.

    Filtra por presencia, por competencias y por **capacidad libre en ese canal**.
    Saltarse la capacidad convierte el reparto en un reparto formal: el caso
    figura asignado, nadie lo mira, y el SLA corre igual — que es peor que
    dejarlo en cola, porque en cola al menos se ve.
    """
    consulta = select(AgenteServicio).where(
        AgenteServicio.tenant_id == tenant_id,
        AgenteServicio.activo.is_(True),
        AgenteServicio.presencia.in_(PRESENCIAS_ASIGNABLES),
    )
    if candidatos:
        consulta = consulta.where(AgenteServicio.usuario_id.in_(candidatos))
    filas = list(db.execute(consulta).scalars().all())

    exigidas = set(competencias or [])
    if exigidas:
        filas = [f for f in filas if exigidas.issubset({str(c) for c in (f.competencias or [])})]
    if not filas:
        return []

    carga = carga_de(db, tenant_id, [f.usuario_id for f in filas])
    libres = []
    for agente in filas:
        tope = int((agente.capacidad or {}).get(canal, 0) or 0)
        # Sin tope declarado se considera **sin límite** y no cero: un agente al
        # que nadie configuró la capacidad tiene que poder trabajar, y tratarlo
        # como saturado dejaría la cola llena sin que nadie entendiera por qué.
        if tope and carga.get(agente.usuario_id, 0) >= tope:
            continue
        libres.append(agente)
    return libres


# ── Asignación (CRM-04.01.01.05, .06) ─────────────────────────────────────


def _condiciones_de(regla: ReglaAsignacion) -> list[Any]:
    from crmcore.authz.abac import Condicion

    salida = []
    for bruta in regla.condiciones or []:
        if not isinstance(bruta, dict):
            continue
        salida.append(
            Condicion(
                atributo=str(bruta.get("atributo", "")),
                operador=str(bruta.get("operador", "=")),
                valor=bruta.get("valor"),
            )
        )
    return salida


def _ambito(caso: Caso) -> dict[str, Any]:
    return {
        "caso": {
            "prioridad": caso.prioridad,
            "severidad": caso.severidad,
            "tipo": caso.tipo,
            "linea": caso.linea,
            "origen": caso.origen,
            "estado": caso.estado,
            "cuenta_id": str(caso.cuenta_id) if caso.cuenta_id else None,
            **{k: v for k, v in (caso.campos or {}).items()},
        }
    }


def _encaja(regla: ReglaAsignacion, ambito: dict[str, Any]) -> tuple[bool, str | None]:
    condiciones = _condiciones_de(regla)
    if not condiciones:
        return True, None
    resultados = [(c, c.evaluar(ambito)) for c in condiciones]
    if regla.combinacion == "cualquiera":
        if any(r for _, r in resultados):
            return True, None
        return False, "ninguna condición se cumple"
    for condicion, ok in resultados:
        if not ok:
            return False, f"{condicion.atributo} {condicion.operador}"
    return True, None


def _elegir(
    db: Session, regla: ReglaAsignacion, tenant_id: UUID, disponibles: list[AgenteServicio]
) -> UUID | None:
    if not disponibles:
        return None
    usuarios = [a.usuario_id for a in disponibles]
    declarados = [UUID(str(c)) for c in (regla.candidatos or [])]
    if declarados:
        orden = {u: i for i, u in enumerate(declarados)}
        usuarios = sorted([u for u in usuarios if u in orden], key=lambda u: orden[u])
    if not usuarios:
        return None

    if regla.estrategia == "fijo":
        return usuarios[0]

    if regla.estrategia in ("menos_carga", "menos_carga_ponderada"):
        carga = carga_de(db, tenant_id, usuarios)
        if regla.estrategia == "menos_carga":
            # Desempate por el orden declarado, no al azar: con dos a cero casos,
            # repartir arbitrariamente hace que dos ejecuciones iguales den
            # resultados distintos y el reparto no se pueda reproducir.
            return min(carga_ordenada(usuarios, carga), key=lambda p: p[1])[0]
        # Ponderada: se reparte por **hueco libre** y no por carga absoluta. Con
        # carga absoluta, quien tiene capacidad 20 y lleva 5 casos parece más
        # ocupado que quien tiene capacidad 5 y lleva 4, y el reparto acaba
        # saturando justo al que menos cabe.
        topes = {
            a.usuario_id: int((a.capacidad or {}).get(regla.canal, 0) or 0) for a in disponibles
        }

        def _hueco(usuario: UUID) -> tuple[float, int]:
            tope = topes.get(usuario, 0)
            usados = carga.get(usuario, 0)
            ocupacion = (usados / tope) if tope else 0.0
            return (ocupacion, usuarios.index(usuario))

        return min(usuarios, key=_hueco)

    indice = regla.cursor_turno % len(usuarios)
    regla.cursor_turno = (regla.cursor_turno + 1) % max(len(usuarios), 1)
    return usuarios[indice]


def carga_ordenada(
    usuarios: list[UUID], carga: dict[UUID, int]
) -> list[tuple[UUID, tuple[int, int]]]:
    return [(u, (carga.get(u, 0), i)) for i, u in enumerate(usuarios)]


def asignar(uow: UnidadDeTrabajo, caso: Caso, *, canal: str = "caso") -> RegistroAsignacion:
    """Decide quién atiende el caso y deja la traza de por qué.

    Si ninguna regla encuentra a nadie con hueco, el caso **va a la cola** y se
    dice. Dejarlo sin dueño y sin cola es el único estado del que nadie se
    entera: no sale en la lista de ninguna persona ni en la de ningún equipo, y
    el SLA corre igual.
    """

    tenant_id = caso.tenant_id
    reglas = (
        uow.db.execute(
            select(ReglaAsignacion)
            .where(ReglaAsignacion.tenant_id == tenant_id, ReglaAsignacion.activa.is_(True))
            .order_by(ReglaAsignacion.prioridad, ReglaAsignacion.nombre)
        )
        .scalars()
        .all()
    )
    ambito = _ambito(caso)
    evaluadas: list[dict[str, Any]] = []

    for regla in reglas:
        if regla.canal and regla.canal != canal:
            evaluadas.append({"regla": regla.nombre, "resultado": "otro_canal"})
            continue
        ok, fallo = _encaja(regla, ambito)
        if not ok:
            evaluadas.append(
                {"regla": regla.nombre, "resultado": "no_encaja", "condicion_fallida": fallo}
            )
            continue

        disponibles = agentes_disponibles(
            uow.db,
            tenant_id,
            candidatos=[UUID(str(c)) for c in (regla.candidatos or [])] or None,
            canal=canal,
            competencias=[str(c) for c in (regla.competencias or [])],
        )
        elegido = _elegir(uow.db, regla, tenant_id, disponibles)
        if elegido is None:
            # Encajaba pero no había nadie con hueco. Se anota **la diferencia**
            # entre «no encaja» y «no hay quien»: son dos problemas distintos y
            # confundirlos lleva a reescribir una regla que estaba bien.
            evaluadas.append({"regla": regla.nombre, "resultado": "sin_agente_disponible"})
            if regla.cola:
                return _anotar_asignacion(
                    uow,
                    caso,
                    regla=regla,
                    asignado_a=None,
                    cola=regla.cola,
                    evaluadas=evaluadas,
                    motivo="ningún agente con hueco; va a la cola",
                )
            continue

        caso.owner_id = elegido
        if caso.estado == "nuevo":
            caso.estado = "asignado"
        return _anotar_asignacion(
            uow, caso, regla=regla, asignado_a=elegido, cola=None, evaluadas=evaluadas
        )

    # Ninguna regla: va a la cola general si existe, y si no, se dice.
    general = uow.db.execute(
        select(ColaCasos)
        .where(ColaCasos.tenant_id == tenant_id, ColaCasos.activa.is_(True), ColaCasos.nivel == 1)
        .order_by(ColaCasos.clave)
        .limit(1)
    ).scalar_one_or_none()
    return _anotar_asignacion(
        uow,
        caso,
        regla=None,
        asignado_a=None,
        cola=general.clave if general else None,
        evaluadas=evaluadas,
        motivo=(
            "ninguna regla encajó"
            if general
            else "ninguna regla encajó y no hay cola general: el caso queda SIN DUEÑO"
        ),
    )


def _anotar_asignacion(
    uow: UnidadDeTrabajo,
    caso: Caso,
    *,
    regla: ReglaAsignacion | None,
    asignado_a: UUID | None,
    cola: str | None,
    evaluadas: list[dict[str, Any]],
    motivo: str = "",
) -> RegistroAsignacion:
    from services.service.modelos import EventoCaso

    if cola:
        caso.equipo = cola
    fila = RegistroAsignacion(
        tenant_id=caso.tenant_id,
        caso_id=caso.id,
        regla_nombre=regla.nombre if regla else None,
        asignado_a=asignado_a,
        cola=cola,
        estrategia=regla.estrategia if regla else None,
        motivo=motivo or None,
        evaluadas=evaluadas,
    )
    uow.db.add(fila)
    uow.db.add(
        EventoCaso(
            tenant_id=caso.tenant_id,
            caso_id=caso.id,
            tipo="asignado",
            detalle={
                "a": str(asignado_a) if asignado_a else None,
                "cola": cola,
                "regla": regla.nombre if regla else None,
            },
        )
    )
    uow.db.flush()
    if asignado_a is not None:
        uow.emitir(
            "case.assigned",
            subject=("caso", caso.id),
            data={
                "caso_id": str(caso.id),
                "asignado_a": str(asignado_a),
                "regla": regla.nombre if regla else "",
            },
            dedup_key=f"case.assigned:{caso.id}:{asignado_a}",
        )
    return fila


def explicar_asignacion(db: Session, tenant_id: UUID, caso_id: UUID) -> list[dict[str, Any]]:
    filas = (
        db.execute(
            select(RegistroAsignacion)
            .where(
                RegistroAsignacion.tenant_id == tenant_id,
                RegistroAsignacion.caso_id == caso_id,
            )
            .order_by(RegistroAsignacion.created_at)
        )
        .scalars()
        .all()
    )
    return [
        {
            "at": f.created_at.isoformat(),
            "regla": f.regla_nombre,
            "asignado_a": str(f.asignado_a) if f.asignado_a else None,
            "cola": f.cola,
            "estrategia": f.estrategia,
            "motivo": f.motivo,
            "evaluadas": f.evaluadas,
        }
        for f in filas
    ]


def cola(db: Session, tenant_id: UUID, clave: str, *, limite: int = 100) -> list[dict[str, Any]]:
    """Lo que hay esperando en una cola, ordenado por lo que vence antes.

    No por prioridad ni por antigüedad: la pregunta de quien coge de una cola es
    «qué se me va a incumplir primero», y ordenar por prioridad hace que un caso
    medio a punto de vencer se quede debajo de uno crítico con dos días.
    """
    from services.service.modelos import Caso

    filas = (
        db.execute(
            select(Caso)
            .where(
                Caso.tenant_id == tenant_id,
                Caso.equipo == clave,
                Caso.owner_id.is_(None),
                Caso.estado.not_in(("resuelto", "cerrado")),
                Caso.deleted_at.is_(None),
            )
            .order_by(Caso.vence_resolucion_at.asc().nulls_last(), Caso.created_at)
            .limit(limite)
        )
        .scalars()
        .all()
    )
    ahora = _ahora()
    return [
        {
            "caso_id": str(f.id),
            "codigo": f.codigo,
            "asunto": f.asunto,
            "prioridad": f.prioridad,
            "vence_resolucion_at": (
                f.vence_resolucion_at.isoformat() if f.vence_resolucion_at else None
            ),
            "minutos_restantes": (
                int((_con_tz(f.vence_resolucion_at) - ahora).total_seconds() // 60)
                if f.vence_resolucion_at
                else None
            ),
            # Sin SLA no hay orden por vencimiento, y eso se dice: si no, esos
            # casos quedan al final de la lista y parecen los menos urgentes
            # cuando en realidad son los que nadie ha medido.
            "sin_sla": f.vence_resolucion_at is None,
        }
        for f in filas
    ]


def coger_de_cola(uow: UnidadDeTrabajo, caso_id: UUID, usuario_id: UUID) -> Caso:
    """Un agente se adjudica un caso de la cola.

    Se comprueba que siga libre: dos agentes mirando la misma cola pulsan a la
    vez, y sin esta comprobación el segundo se queda con el caso del primero sin
    que ninguno lo sepa.
    """
    from services.service.modelos import EventoCaso
    from services.service.servicio import exigir_caso

    caso = exigir_caso(uow.db, caso_id)
    if caso.owner_id is not None:
        raise Conflicto(
            "Ese caso ya lo ha cogido alguien.",
            error_code="service.caso_ya_asignado",
            detalle={"owner_id": str(caso.owner_id)},
        )
    caso.owner_id = usuario_id
    if caso.estado == "nuevo":
        caso.estado = "asignado"
    uow.db.add(
        EventoCaso(
            tenant_id=caso.tenant_id,
            caso_id=caso.id,
            tipo="cogido_de_cola",
            detalle={"por": str(usuario_id), "cola": caso.equipo},
            por=usuario_id,
        )
    )
    return caso


# ── Escalado (CRM-04.01.01.07) ────────────────────────────────────────────

ORDEN_SEVERIDAD = {"baja": 0, "media": 1, "alta": 2, "critica": 3}
ORDEN_PRIORIDAD = {"baja": 0, "media": 1, "alta": 2, "critica": 3}


def _consumido_pct(caso: Caso, ahora: datetime) -> float | None:
    vence = _con_tz(caso.vence_resolucion_at)
    if vence is None:
        return None
    inicio = _con_tz(caso.created_at) or ahora
    total = (vence - inicio).total_seconds()
    if total <= 0:
        return None
    return round(100 * (ahora - inicio).total_seconds() / total, 1)


def evaluar_escaladas(
    uow: UnidadDeTrabajo, tenant_id: UUID, *, cuentas_vip: set[UUID] | None = None
) -> dict[str, Any]:
    """Aplica las reglas de escalado a los casos abiertos.

    Se decide por **lo que queda**, no por lo que ha pasado: escalar cuando el
    SLA ya se ha incumplido llega tarde por definición. Por eso el disparador
    normal es el porcentaje consumido, y escalar al incumplir es una opción
    aparte —sirve para que alguien con autoridad hable con el cliente antes de
    que llame él, no para llegar a tiempo—.

    Un caso **no se escala dos veces por la misma regla**: si se escalara en cada
    pasada, el responsable recibiría el mismo aviso cada cinco minutos y dejaría
    de leerlos, que es la forma habitual de que un escalado deje de servir.
    """
    from services.service.modelos import Caso, EventoCaso

    ahora = _ahora()
    cuentas_vip = cuentas_vip or set()
    reglas = (
        uow.db.execute(
            select(ReglaEscalada)
            .where(ReglaEscalada.tenant_id == tenant_id, ReglaEscalada.activa.is_(True))
            .order_by(ReglaEscalada.prioridad, ReglaEscalada.nombre)
        )
        .scalars()
        .all()
    )
    if not reglas:
        return {"reglas": 0, "escalados": [], "medible": False}

    abiertos = (
        uow.db.execute(
            select(Caso).where(
                Caso.tenant_id == tenant_id,
                Caso.estado.not_in(("resuelto", "cerrado")),
                Caso.deleted_at.is_(None),
            )
        )
        .scalars()
        .all()
    )

    escalados: list[dict[str, Any]] = []
    for caso in abiertos:
        ya = {
            str(e.detalle.get("regla"))
            for e in uow.db.execute(
                select(EventoCaso).where(
                    EventoCaso.caso_id == caso.id, EventoCaso.tipo == "escalado"
                )
            ).scalars()
        }
        pct = _consumido_pct(caso, ahora)
        vence = _con_tz(caso.vence_resolucion_at)
        incumplido = vence is not None and ahora > vence

        for regla in reglas:
            if regla.nombre in ya:
                continue
            if regla.solo_vip and caso.cuenta_id not in cuentas_vip:
                continue
            if regla.severidad_minima and ORDEN_SEVERIDAD.get(
                caso.severidad, 0
            ) < ORDEN_SEVERIDAD.get(regla.severidad_minima, 0):
                continue

            dispara = False
            motivo = ""
            if regla.consumido_pct is not None and pct is not None and pct >= regla.consumido_pct:
                dispara, motivo = True, f"{pct}% del SLA consumido"
            if regla.al_incumplir and incumplido:
                dispara, motivo = True, "SLA incumplido"
            if not dispara:
                continue

            _aplicar_escalada(uow, caso, regla, motivo=motivo)
            escalados.append(
                {
                    "caso_id": str(caso.id),
                    "codigo": caso.codigo,
                    "regla": regla.nombre,
                    "motivo": motivo,
                }
            )
            break  # una escalada por pasada y caso: encadenarlas es ruido

    return {"reglas": len(reglas), "escalados": escalados, "medible": True}


def _aplicar_escalada(
    uow: UnidadDeTrabajo, caso: Caso, regla: ReglaEscalada, *, motivo: str
) -> None:
    from services.service.modelos import EventoCaso

    if regla.subir_nivel:
        caso.campos = {
            **(caso.campos or {}),
            "nivel_escalado": int((caso.campos or {}).get("nivel_escalado", 1)) + 1,
        }
    if regla.subir_prioridad:
        actual = ORDEN_PRIORIDAD.get(caso.prioridad, 1)
        siguiente = min(actual + 1, 3)
        caso.prioridad = [k for k, v in ORDEN_PRIORIDAD.items() if v == siguiente][0]
    if regla.asignar_a is not None:
        caso.owner_id = regla.asignar_a
    if regla.cola_destino:
        caso.equipo = regla.cola_destino
        # Cambiar de cola **suelta al dueño**: si no, el caso figura en la cola
        # nueva y sigue asignado al de antes, y los dos equipos creen que lo
        # lleva el otro.
        caso.owner_id = regla.asignar_a

    uow.db.add(
        EventoCaso(
            tenant_id=caso.tenant_id,
            caso_id=caso.id,
            tipo="escalado",
            detalle={"regla": regla.nombre, "motivo": motivo, "prioridad": caso.prioridad},
        )
    )
    registrar(
        uow.db,
        accion="caso.escalado",
        objeto="caso",
        objeto_id=caso.id,
        datos={"regla": regla.nombre, "motivo": motivo},
        tenant_id=caso.tenant_id,
    )
    uow.emitir(
        "case.escalated",
        subject=("caso", caso.id),
        data={
            "caso_id": str(caso.id),
            "regla": regla.nombre,
            "motivo": motivo,
            "avisar_a": [str(u) for u in (regla.avisar_a or [])],
        },
        dedup_key=f"case.escalated:{caso.id}:{regla.nombre}",
    )


# ── Derivación a otro nivel (CRM-04.01.01.08) ─────────────────────────────


def derivar(
    uow: UnidadDeTrabajo,
    caso_id: UUID,
    *,
    cola_destino: str,
    motivo: str,
    interno: bool = False,
) -> Caso:
    """Pasa el caso a segundo nivel, a ingeniería o a una cola interna.

    El motivo es obligatorio. Una derivación sin motivo obliga a quien la recibe
    a leerse el caso entero para averiguar qué se espera de él, y eso es lo que
    hace que las derivaciones reboten.

    **El caso sigue siendo del cliente.** Derivar no crea un caso nuevo ni
    reinicia el reloj: el cliente no tiene por qué esperar otra vez desde cero
    porque nosotros hayamos movido su problema de mesa. Lo interno se marca para
    que no se le enseñe al cliente, no para que cuente distinto.
    """
    from services.service.modelos import EventoCaso
    from services.service.servicio import exigir_caso

    if not (motivo or "").strip():
        raise ErrorValidacion(
            "Derivar exige decir qué se espera del siguiente nivel.",
            error_code="service.derivacion_sin_motivo",
        )
    caso = exigir_caso(uow.db, caso_id)
    destino = uow.db.execute(
        select(ColaCasos).where(
            ColaCasos.tenant_id == caso.tenant_id, ColaCasos.clave == cola_destino
        )
    ).scalar_one_or_none()
    if destino is None:
        raise NoEncontrado(
            f"No existe la cola «{cola_destino}»", error_code="service.cola_no_encontrada"
        )

    anterior = caso.equipo
    caso.equipo = destino.clave
    caso.owner_id = None
    caso.campos = {**(caso.campos or {}), "nivel_escalado": destino.nivel, "interno": interno}
    uow.db.add(
        EventoCaso(
            tenant_id=caso.tenant_id,
            caso_id=caso.id,
            tipo="derivado",
            detalle={
                "desde": anterior,
                "hacia": destino.clave,
                "nivel": destino.nivel,
                "motivo": motivo,
                "interno": interno,
            },
        )
    )
    return caso
