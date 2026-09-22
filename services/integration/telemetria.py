"""Telemetría de dispositivo: lecturas que acaban abriendo casos
(CRM-04.04.02.05).

Un equipo que avisa antes de romperse es la promesa de todo el IoT industrial, y
donde casi siempre se estrella es en el volumen: una máquina manda una lectura
cada diez segundos, mil máquinas son ocho millones de lecturas al día, y un CRM
que abra un caso por cada una deja de servir para atender clientes en una tarde.

De ahí las cinco decisiones de este módulo:

**No se guarda todo.** Se guardan las lecturas que **cruzan un umbral** y un
resumen de las demás. Guardar la serie completa convierte el CRM en una base de
datos de series temporales que no es, y que no puede competir con una de verdad.

**El caso lo abre `service`, no este módulo.** `integration` no escribe en el
esquema de atención: manda un **comando** y el dueño del objeto decide. Saltárselo
daría dos sitios donde se crean casos, y solo uno aplicaría las reglas.

**Un dispositivo que se vuelve loco no abre mil casos.** Hay ventana de silencio
por regla y dispositivo: superado el primer caso, lo siguiente se cuenta y se
adjunta, no se multiplica. Sin eso, la primera avería real de una flota tumba la
cola de soporte.

**Dejar de recibir es una señal, no la ausencia de señal.** Un sensor que calla
lleva tres días averiado y nadie lo mira, porque no hay ninguna alerta que saltar.
Aquí el silencio se detecta explícitamente.

**Lo que no se puede atribuir a un activo se dice.** Una lectura de un
identificador que no corresponde a ningún equipo nuestro no se descarta en
silencio: puede ser un alta que falta o un dispositivo de otro.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from crmcore.authz.abac import Condicion
from crmcore.bus.comandos import Comando
from crmcore.bus.comandos import emitir as emitir_comando
from crmcore.db.base import Base, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import ErrorValidacion
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from crmcore.runtime import settings as rt
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
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

logger = get_logger(__name__)

# Qué hace una regla cuando se cumple. Cerrada porque cada una tiene un coste
# distinto para quien la recibe, y una acción nueva inventada en una pantalla no
# tendría quién la ejecutara.
#
#   caso        pide a `service` que abra un caso
#   preventivo  pide una orden de trabajo preventiva
#   aviso       solo deja el registro y el evento; no molesta a nadie
ACCIONES = ("caso", "preventivo", "aviso")

# Severidades admitidas, que se trasladan tal cual al caso.
SEVERIDADES = ("baja", "media", "alta", "critica")


class Dispositivo(Base, TimestampMixin):
    """Un equipo que manda lecturas (CRM-04.04.02.05).

    `activo_id` apunta al activo instalado de `service` y **no se resuelve desde
    aquí**. Un dispositivo sin activo se admite: llega antes el aparato que el
    alta, y rechazar sus lecturas mientras tanto es perder justo los primeros
    días, que son los que más fallos dan.
    """

    __tablename__ = "dispositivos"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    # Lo que el aparato dice ser. Es la clave con la que llegan las lecturas.
    identificador: Mapped[str] = mapped_column(String(120), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    activo_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True, index=True)
    cuenta_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    modelo: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Cada cuánto debería dar señal. Es lo que permite detectar el silencio: sin
    # esto, un sensor averiado no produce ninguna alerta porque no manda nada.
    cadencia_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ultima_lectura_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "identificador", name="uq_dispositivo_identificador"),
        Index("ix_dispositivos_silencio", "tenant_id", "activo", "ultima_lectura_at"),
    )


class ReglaTelemetria(Base, TimestampMixin):
    """Cuándo una lectura merece abrir algo."""

    __tablename__ = "reglas_telemetria"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(80), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # Condiciones con la gramática ABAC de siempre, sobre la lectura: reinventar
    # un lenguaje de reglas aquí daría dos que se comportan distinto.
    condiciones: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    modelo: Mapped[str | None] = mapped_column(String(120), nullable=True)
    accion: Mapped[str] = mapped_column(String(20), nullable=False, default="aviso")
    severidad: Mapped[str] = mapped_column(String(20), nullable=False, default="media")
    asunto: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    # Cuánto tiempo no se vuelve a abrir nada por lo mismo en el mismo aparato.
    # Es lo que impide que una máquina que se vuelve loca tumbe la cola de
    # soporte con mil casos idénticos.
    silencio_min: Mapped[int] = mapped_column(Integer, nullable=False, default=120)
    # Cuántas veces seguidas tiene que cumplirse antes de disparar. Un pico de un
    # segundo no es una avería, y abrir un caso por cada pico hace que se apague
    # la regla entera.
    repeticiones: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "clave", name="uq_regla_telemetria"),
        Index("ix_reglas_telemetria", "tenant_id", "activa"),
    )


class Lectura(Base):
    """Una lectura **que cruzó un umbral**, no todas.

    Guardar la serie completa convierte este esquema en una base de datos de
    series temporales que no es. Lo que se guarda aquí es lo que alguien va a
    mirar: lo que disparó algo, y el contador de lo que no.
    """

    __tablename__ = "lecturas_telemetria"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    dispositivo_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("dispositivos.id", ondelete="CASCADE"), nullable=False
    )
    regla_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    metrica: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    valor: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    datos: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # El reloj del aparato y el del servidor, por separado, por lo mismo que en
    # el móvil de campo: el del aparato miente y aun así es el que sabe cuándo
    # pasó.
    medido_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recibido_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Qué se hizo con ella: nada, aviso, caso pedido, caso agrupado por silencio.
    resultado: Mapped[str] = mapped_column(String(30), nullable=False, default="ninguno")
    caso_pedido: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    nota: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (
        Index("ix_lecturas_dispositivo", "tenant_id", "dispositivo_id", "recibido_at"),
    )


class EstadoRegla(Base):
    """Lo que hay que recordar entre lecturas: rachas y último disparo."""

    __tablename__ = "estado_regla_telemetria"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    dispositivo_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    regla_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    racha: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ultimo_disparo_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Cuántas lecturas se han agrupado bajo el último disparo. Es el número que
    # dice si una máquina está peor o si simplemente sigue igual.
    agrupadas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "dispositivo_id", "regla_id", name="uq_estado_regla_telemetria"
        ),
    )


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _con_tz(valor: datetime | None) -> datetime | None:
    if valor is None:
        return None
    return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)


def registrar_dispositivo(
    uow: UnidadDeTrabajo,
    *,
    identificador: str,
    nombre: str = "",
    activo_id: UUID | None = None,
    cuenta_id: UUID | None = None,
    modelo: str | None = None,
    cadencia_min: int | None = None,
) -> tuple[Dispositivo, list[str]]:
    """Da de alta un dispositivo."""
    avisos: list[str] = []
    if cadencia_min is None:
        avisos.append(
            "Sin cadencia declarada: no se podrá detectar que este aparato ha dejado "
            "de dar señal, que es la avería que nadie mira."
        )
    if activo_id is None:
        avisos.append(
            "Sin activo asociado: sus avisos no podrán colgarse de una máquina ni " "de un cliente."
        )
    fila = Dispositivo(
        tenant_id=uow.tenant_id,
        identificador=identificador.strip(),
        nombre=nombre.strip(),
        activo_id=activo_id,
        cuenta_id=cuenta_id,
        modelo=modelo,
        cadencia_min=cadencia_min,
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila, avisos


def crear_regla(
    uow: UnidadDeTrabajo,
    *,
    clave: str,
    condiciones: list[dict[str, Any]],
    accion: str = "aviso",
    nombre: str = "",
    severidad: str = "media",
    asunto: str = "",
    modelo: str | None = None,
    silencio_min: int | None = None,
    repeticiones: int = 1,
) -> ReglaTelemetria:
    """Declara cuándo una lectura merece abrir algo.

    Las condiciones se validan al guardarlas: un operador mal escrito no falla,
    deja de disparar en silencio — y de una regla que no salta nunca nadie
    sospecha, porque «no ha habido averías».
    """
    if accion not in ACCIONES:
        raise ErrorValidacion(
            f"Acción «{accion}» no válida.",
            error_code="telemetria.accion_no_valida",
            detalle={"validas": list(ACCIONES)},
        )
    if severidad not in SEVERIDADES:
        raise ErrorValidacion(
            f"Severidad «{severidad}» no válida.",
            error_code="telemetria.severidad_no_valida",
            detalle={"validas": list(SEVERIDADES)},
        )
    if not condiciones:
        raise ErrorValidacion(
            "Una regla sin condiciones se cumpliría con cualquier lectura y abriría "
            "un caso por cada una.",
            error_code="telemetria.sin_condiciones",
        )
    from crmcore.authz.abac import OPERADORES

    for i, cruda in enumerate(condiciones, 1):
        if not isinstance(cruda, dict) or not cruda.get("atributo"):
            raise ErrorValidacion(
                f"La condición {i} no dice sobre qué atributo compara.",
                error_code="telemetria.condicion_invalida",
            )
        if cruda.get("operador") not in OPERADORES:
            raise ErrorValidacion(
                f"Operador «{cruda.get('operador')}» no válido en la condición {i}.",
                error_code="telemetria.operador_no_valido",
                detalle={"validos": sorted(OPERADORES)},
            )

    fila = ReglaTelemetria(
        tenant_id=uow.tenant_id,
        clave=clave.strip(),
        nombre=nombre.strip() or clave.strip(),
        condiciones=list(condiciones),
        accion=accion,
        severidad=severidad,
        asunto=asunto,
        modelo=modelo,
        silencio_min=int(
            silencio_min
            if silencio_min is not None
            else (rt.efectivo("telemetria_silencio_min", uow.db) or 120)
        ),
        repeticiones=max(1, int(repeticiones)),
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila


def _estado(uow: UnidadDeTrabajo, dispositivo_id: UUID, regla_id: UUID) -> EstadoRegla:
    fila = uow.db.execute(
        select(EstadoRegla).where(
            EstadoRegla.tenant_id == uow.tenant_id,
            EstadoRegla.dispositivo_id == dispositivo_id,
            EstadoRegla.regla_id == regla_id,
        )
    ).scalar_one_or_none()
    if fila is None:
        fila = EstadoRegla(
            tenant_id=uow.tenant_id, dispositivo_id=dispositivo_id, regla_id=regla_id
        )
        uow.db.add(fila)
        uow.db.flush()
    return fila


def ingerir(
    uow: UnidadDeTrabajo,
    *,
    identificador: str,
    metrica: str = "",
    valor: Decimal | float | None = None,
    datos: dict[str, Any] | None = None,
    medido_at: datetime | None = None,
) -> dict[str, Any]:
    """Recibe una lectura y decide qué hacer con ella (CRM-04.04.02.05).

    Lo que devuelve dice **qué se hizo y por qué**, no «ok»: quien integra un
    aparato necesita saber si su lectura se descartó por no cruzar ningún umbral,
    si se agrupó bajo un caso ya abierto o si abrió uno nuevo. Un `200 OK` sin
    detalle hace que se integre a ciegas y se descubra a los tres meses que nunca
    saltó nada.
    """
    dispositivo = uow.db.execute(
        select(Dispositivo).where(
            Dispositivo.tenant_id == uow.tenant_id,
            Dispositivo.identificador == identificador.strip(),
        )
    ).scalar_one_or_none()
    if dispositivo is None:
        # No se descarta en silencio: puede ser un alta que falta —lo normal— o un
        # aparato que no es nuestro, y las dos cosas hay que verlas.
        logger.info("telemetria.dispositivo_desconocido", identificador=identificador)
        return {
            "aceptada": False,
            "porque": "El identificador no corresponde a ningún dispositivo dado de alta.",
            "identificador": identificador,
        }
    if not dispositivo.activo:
        return {
            "aceptada": False,
            "porque": "El dispositivo está dado de baja.",
            "dispositivo_id": str(dispositivo.id),
        }

    dispositivo.ultima_lectura_at = _ahora()
    ambito: dict[str, Any] = {
        "metrica": metrica,
        "valor": float(valor) if valor is not None else None,
        "modelo": dispositivo.modelo,
        **(datos or {}),
    }
    ambito["lectura"] = dict(ambito)

    reglas = (
        uow.db.execute(
            select(ReglaTelemetria).where(
                ReglaTelemetria.tenant_id == uow.tenant_id,
                ReglaTelemetria.activa.is_(True),
            )
        )
        .scalars()
        .all()
    )

    disparos: list[dict[str, Any]] = []
    for regla in reglas:
        if regla.modelo and dispositivo.modelo and regla.modelo != dispositivo.modelo:
            continue
        cumple = True
        for cruda in regla.condiciones or []:
            try:
                condicion = Condicion(**cruda)
            except TypeError:
                # Una condición ilegible no dispara: al revés, una regla mal
                # guardada abriría un caso por cada lectura de la flota.
                logger.warning("telemetria.condicion_ilegible", regla=str(regla.id))
                cumple = False
                break
            if not condicion.evaluar(ambito):
                cumple = False
                break
        estado = _estado(uow, dispositivo.id, regla.id)
        if not cumple:
            # La racha se rompe: tres lecturas malas salteadas entre buenas no son
            # una avería sostenida.
            estado.racha = 0
            continue

        estado.racha += 1
        if estado.racha < regla.repeticiones:
            disparos.append(
                {
                    "regla": regla.clave,
                    "resultado": "acumulando",
                    "porque": f"lleva {estado.racha} de {regla.repeticiones} repeticiones",
                }
            )
            continue

        ultimo = _con_tz(estado.ultimo_disparo_at)
        if ultimo is not None and _ahora() - ultimo < timedelta(minutes=regla.silencio_min):
            estado.agrupadas += 1
            disparos.append(
                {
                    "regla": regla.clave,
                    "resultado": "agrupada",
                    "porque": (
                        f"ya se abrió algo por esta regla hace menos de "
                        f"{regla.silencio_min} min; van {estado.agrupadas} lecturas "
                        "agrupadas"
                    ),
                }
            )
            continue

        estado.ultimo_disparo_at = _ahora()
        estado.agrupadas = 0
        estado.racha = 0
        disparos.append(_disparar(uow, dispositivo, regla, ambito))

    lectura = Lectura(
        tenant_id=uow.tenant_id,
        dispositivo_id=dispositivo.id,
        metrica=metrica,
        valor=Decimal(str(valor)) if valor is not None else None,
        datos=datos or {},
        medido_at=_con_tz(medido_at),
        regla_id=None,
        resultado=(disparos[0]["resultado"] if disparos else "ninguno"),
        caso_pedido=any(d["resultado"] == "caso_pedido" for d in disparos),
        nota="; ".join(d.get("porque", "") for d in disparos),
    )
    # Solo se guarda la lectura que hizo algo. Las demás se cuentan y se tiran:
    # ocho millones de filas al día no caben en el esquema de un CRM.
    if disparos:
        uow.db.add(lectura)
    uow.db.flush()
    return {
        "aceptada": True,
        "dispositivo_id": str(dispositivo.id),
        "disparos": disparos,
        "guardada": bool(disparos),
        # Que no dispare nada es lo normal y se dice: quien integra tiene que
        # poder distinguirlo de «no llegó».
        "porque": "" if disparos else "Ninguna regla se ha cumplido con esta lectura.",
    }


def _disparar(
    uow: UnidadDeTrabajo,
    dispositivo: Dispositivo,
    regla: ReglaTelemetria,
    ambito: dict[str, Any],
) -> dict[str, Any]:
    """Ejecuta la acción de la regla.

    El caso lo abre **`service`**, no este módulo: `integration` no escribe en el
    esquema de atención. Se manda un comando por el bus y el dueño del objeto
    aplica sus reglas —SLA, taxonomía, enrutamiento— como con cualquier otro caso.
    """
    asunto = regla.asunto or f"{regla.nombre} en {dispositivo.nombre or dispositivo.identificador}"
    if regla.accion == "aviso":
        uow.emitir(
            "device.alert",
            subject=("dispositivo", dispositivo.id),
            data={
                "dispositivo_id": str(dispositivo.id),
                "regla": regla.clave,
                "severidad": regla.severidad,
            },
        )
        return {"regla": regla.clave, "resultado": "aviso", "porque": asunto}

    objeto = "caso" if regla.accion == "caso" else "orden_trabajo"
    emitir_comando(
        uow,
        Comando(
            accion="crear",
            objeto=objeto,
            tenant_id=uow.tenant_id,
            datos={
                "asunto": asunto,
                "descripcion": (
                    f"Abierto por telemetría. Regla «{regla.clave}». "
                    f"Lectura: {ambito.get('metrica')} = {ambito.get('valor')}."
                ),
                "severidad": regla.severidad,
                "origen": "telemetria",
                "activo_id": str(dispositivo.activo_id) if dispositivo.activo_id else None,
                "cuenta_id": str(dispositivo.cuenta_id) if dispositivo.cuenta_id else None,
            },
            origen="telemetria",
            origen_id=str(dispositivo.id),
        ),
    )
    uow.emitir(
        "device.alert",
        subject=("dispositivo", dispositivo.id),
        data={
            "dispositivo_id": str(dispositivo.id),
            "regla": regla.clave,
            "severidad": regla.severidad,
        },
    )
    return {
        "regla": regla.clave,
        "resultado": "caso_pedido" if regla.accion == "caso" else "preventivo_pedido",
        "porque": asunto,
        # Se dice que se ha **pedido**, no que exista: lo crea el otro servicio y
        # puede rechazarlo. Decir «caso creado» sería afirmar algo que no consta.
        "nota": "pedido por comando al servicio dueño; no consta creado hasta que él lo diga",
    }


def silenciosos(
    db: Session, tenant_id: UUID, *, factor: float = 3.0, ahora: datetime | None = None
) -> dict[str, Any]:
    """Qué aparatos han dejado de dar señal (CRM-04.04.02.05).

    **Dejar de recibir es una señal.** Un sensor averiado no dispara ninguna
    alerta porque no manda nada, y así lleva tres días sin que nadie lo mire. Se
    considera silencioso cuando pasa varias veces su cadencia declarada: una
    lectura perdida es normal, tres seguidas ya no.

    Los que **nunca** han dado señal salen aparte: no es lo mismo un aparato roto
    que uno que no se llegó a instalar.
    """
    momento = ahora or _ahora()
    filas = (
        db.execute(
            select(Dispositivo).where(
                Dispositivo.tenant_id == tenant_id, Dispositivo.activo.is_(True)
            )
        )
        .scalars()
        .all()
    )
    callados, nunca, sin_cadencia = [], [], []
    for fila in filas:
        if fila.cadencia_min is None:
            sin_cadencia.append(str(fila.id))
            continue
        if fila.ultima_lectura_at is None:
            nunca.append(
                {
                    "dispositivo_id": str(fila.id),
                    "identificador": fila.identificador,
                    "activo_id": str(fila.activo_id) if fila.activo_id else None,
                }
            )
            continue
        ultima = _con_tz(fila.ultima_lectura_at) or momento
        limite = timedelta(minutes=fila.cadencia_min * factor)
        if momento - ultima > limite:
            callados.append(
                {
                    "dispositivo_id": str(fila.id),
                    "identificador": fila.identificador,
                    "activo_id": str(fila.activo_id) if fila.activo_id else None,
                    "ultima_lectura_at": ultima.isoformat(),
                    "minutos_sin_señal": round((momento - ultima).total_seconds() / 60),
                    "cadencia_min": fila.cadencia_min,
                }
            )
    callados.sort(key=lambda d: -d["minutos_sin_señal"])
    return {
        "en_fecha": momento.isoformat(),
        "factor": factor,
        "callados": callados,
        "nunca_han_dado_senal": nunca,
        # Sin cadencia declarada no se puede decir si callan: no se cuentan como
        # sanos, se cuentan aparte.
        "sin_cadencia_declarada": sin_cadencia,
        "concluyente": not sin_cadencia,
    }
