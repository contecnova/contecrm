"""Scoring explicable, predicción de cierre y propensión
(CRM-05.02.01.01, CRM-05.02.01.02, CRM-05.02.01.03 y CRM-03.02.01.06).

Una puntuación sin explicación no se usa: el comercial la mira, no coincide con lo
que él sabe de su cliente, y a partir de esa vez ya no la mira más. Y tiene razón
en no mirarla — él estuvo en la reunión y el modelo no.

Por eso todo lo de aquí devuelve **el número y los porqués**, y por eso los porqués
van ordenados por cuánto empujaron: «esto puntúa 78 porque han abierto tres
presupuestos y porque llevan dos semanas sin contestar» es accionable; «esto puntúa
78» es un número de colores.

Las otras cuatro decisiones:

**Una predicción caduca.** Se guarda con la fecha y el modelo que la produjo, y
pasado el plazo deja de enseñarse. Una probabilidad de cierre calculada hace tres
meses, con la oportunidad ya en otra etapa, es peor que ninguna.

**El forecast predictivo no sustituye al humano: se pone al lado.** Se devuelven
los dos y la diferencia. Sustituirlo hace que el comercial deje de comprometerse
con su número, y el compromiso es la mitad del valor de un forecast.

**Sin historia no hay predicción.** Un tenant que lleva dos meses no tiene con qué
entrenar; puntuarle igual con un modelo de otro sería inventarse su negocio.

**Lo que empuja hacia abajo también se dice.** Un scoring que solo enseña lo bueno
convierte a todos los leads en buenos leads.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

from crmcore.db.base import Base
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import ErrorValidacion
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import (
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from services.intelligence import gobierno

logger = get_logger(__name__)

CENTESIMA = Decimal("0.01")


# Cuántos factores se enseñan. Más de cinco no los lee nadie, y menos de tres
# hacen que la explicación parezca una excusa.
def _ia_factores_visibles(db: Any) -> int:
    """Cuántos factores de una predicción se enseñan.

    Se lee **una vez por llamada** y nunca dentro de un bucle: `efectivo()` va
    a la base, y ahí dentro sería una consulta por vuelta.
    """
    from crmcore.runtime import settings as rt

    from services.intelligence.ajustes import ajustes

    return int(rt.efectivo("ia_factores_visibles", db) or ajustes().ia_factores_visibles)


class Prediccion(Base):
    """Lo que dijo un modelo sobre un registro, cuándo y con qué versión."""

    __tablename__ = "predicciones"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    tipo: Mapped[str] = mapped_column(String(30), nullable=False)
    objeto: Mapped[str] = mapped_column(String(60), nullable=False)
    objeto_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    modelo_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    version_modelo: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    valor: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False, default=0)
    # Intervalo, cuando el modelo lo da. Una predicción de importe sin intervalo
    # se lee como una promesa.
    minimo: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    maximo: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    # Por qué sale eso: [{variable, aporta, valor}]. Ordenado por aportación.
    factores: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Hasta cuándo vale. Pasado, no se enseña: una probabilidad de hace tres meses
    # con la oportunidad ya en otra etapa es peor que ninguna.
    caduca_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Lo que pasó de verdad, cuando se sabe. Es lo que permite medir la deriva
    # contra la realidad en vez de contra el entrenamiento.
    real: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    real_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_predicciones", "tenant_id", "objeto", "objeto_id", "tipo"),
        Index("ix_predicciones_vigencia", "tenant_id", "tipo", "caduca_at"),
    )


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _redondear(valor: Decimal) -> Decimal:
    return Decimal(valor).quantize(CENTESIMA, rounding=ROUND_HALF_UP)


def _sigmoide(x: float) -> float:
    import math

    return 1 / (1 + math.exp(-max(-30.0, min(30.0, x))))


def puntuar(
    uow: UnidadDeTrabajo,
    *,
    tipo: str,
    objeto: str,
    objeto_id: UUID,
    rasgos: dict[str, Any],
    vigencia_dias: int = 14,
) -> dict[str, Any]:
    """Puntúa un registro **y explica por qué**.

    Cubre el scoring de leads y oportunidades (CRM-05.02.01.01), la propensión y
    la siguiente mejor oferta (CRM-05.02.01.03) y —con los tipos `cierre`,
    `importe` y `fecha_cierre`— la predicción de cierre, importe y fecha real
    (CRM-05.02.01.02). Es el mismo mecanismo a propósito: dos motores de scoring
    acaban dando dos respuestas distintas a la misma pregunta.

    El modelo lo aporta el gobierno: si no hay uno vigente para este tenant, no se
    puntúa — y se dice por qué, en vez de devolver un 50 % que parece un empate
    cuando en realidad es «no lo sé».

    Los factores salen ordenados por cuánto empujaron, **con los que empujan hacia
    abajo incluidos**: un scoring que solo enseña lo bueno convierte a todos los
    leads en buenos leads.

    Y se guarda con su caducidad: lo que dijo el modelo hace tres semanas sobre
    una oportunidad que ya ha cambiado de etapa no es información, es ruido con
    aspecto de dato.
    """
    # Una vez: se usa tres veces en esta función, y tres lecturas son tres
    # consultas para el mismo número.
    visibles = _ia_factores_visibles(uow.db)
    modelo = gobierno.exigir_activo(uow.db, uow.tenant_id, tipo)
    pesos = {str(k): float(v) for k, v in (modelo.pesos or {}).items()}
    if not pesos:
        raise ErrorValidacion(
            "El modelo activo no declara pesos: podría puntuar, pero no explicar "
            "por qué, y una puntuación sin porqué no la usa nadie.",
            error_code="prediccion.sin_pesos",
        )

    faltan = [v for v in (modelo.variables or []) if str(v) not in rasgos]
    contribuciones: list[dict[str, Any]] = []
    total = 0.0
    for variable, peso in pesos.items():
        if variable == "_sesgo":
            total += peso
            continue
        crudo = rasgos.get(variable)
        try:
            numero = float(crudo) if crudo is not None else 0.0
        except (TypeError, ValueError):
            numero = 1.0 if crudo else 0.0
        aporta = peso * numero
        total += aporta
        if crudo is not None:
            contribuciones.append(
                {"variable": variable, "valor": crudo, "aporta": round(aporta, 4)}
            )

    contribuciones.sort(key=lambda c: -abs(c["aporta"]))
    probabilidad = _sigmoide(total)
    caduca = _ahora() + timedelta(days=max(1, int(vigencia_dias)))

    fila = Prediccion(
        tenant_id=uow.tenant_id,
        tipo=tipo,
        objeto=objeto,
        objeto_id=objeto_id,
        modelo_id=modelo.id,
        version_modelo=modelo.version,
        valor=_redondear(Decimal(str(probabilidad * 100))),
        factores=contribuciones[:visibles],
        caduca_at=caduca,
    )
    uow.db.add(fila)
    uow.db.flush()

    return {
        "tipo": tipo,
        "objeto_id": str(objeto_id),
        "puntuacion": float(fila.valor),
        "modelo": f"{tipo} v{modelo.version}",
        # Los dos sentidos, siempre: lo que empuja arriba y lo que empuja abajo.
        "a_favor": [c for c in contribuciones[:visibles] if c["aporta"] > 0],
        "en_contra": [c for c in contribuciones[:visibles] if c["aporta"] < 0],
        # Lo que el modelo esperaba y no ha recibido: una puntuación calculada sin
        # la mitad de sus variables es una puntuación peor, y quien la lea tiene
        # que saberlo.
        "variables_ausentes": [str(v) for v in faltan],
        "completa": not faltan,
        "caduca_at": caduca.isoformat(),
        "aviso": (
            ""
            if not faltan
            else f"Faltaban {len(faltan)} de las variables del modelo: la puntuación "
            "es menos fiable de lo normal."
        ),
    }


def vigente(
    db: Session,
    tenant_id: UUID,
    *,
    tipo: str,
    objeto_id: UUID,
    ahora: datetime | None = None,
) -> dict[str, Any]:
    """La última predicción **si no ha caducado**.

    Devolver una caducada sería lo fácil y lo peor: nadie mira la fecha de un
    número que aparece en una ficha.
    """
    momento = ahora or _ahora()
    fila = (
        db.execute(
            select(Prediccion)
            .where(
                Prediccion.tenant_id == tenant_id,
                Prediccion.tipo == tipo,
                Prediccion.objeto_id == objeto_id,
            )
            .order_by(Prediccion.created_at.desc())
        )
        .scalars()
        .first()
    )
    if fila is None:
        return {"hay": False, "porque": "Nunca se ha puntuado este registro."}
    caduca = (
        fila.caduca_at if fila.caduca_at.tzinfo else fila.caduca_at.replace(tzinfo=timezone.utc)
    )
    if caduca < momento:
        return {
            "hay": False,
            "caducada": True,
            "porque": (
                f"La última puntuación es del {fila.created_at.date()} y ha caducado: "
                "el registro ha podido cambiar desde entonces."
            ),
        }
    return {
        "hay": True,
        "puntuacion": float(fila.valor),
        "modelo": f"{fila.tipo} v{fila.version_modelo}",
        "factores": fila.factores,
        "calculada_at": fila.created_at.isoformat(),
        "caduca_at": caduca.isoformat(),
    }


def anotar_real(
    uow: UnidadDeTrabajo, *, tipo: str, objeto_id: UUID, real: Decimal | float
) -> Prediccion | None:
    """Anota lo que pasó de verdad (CRM-05.02.01.02).

    Es lo que convierte las predicciones en medibles: sin el resultado real, la
    deriva solo se puede medir contra el entrenamiento, y eso únicamente dice que
    el modelo se acuerda de lo que vio.
    """
    fila = (
        uow.db.execute(
            select(Prediccion)
            .where(
                Prediccion.tenant_id == uow.tenant_id,
                Prediccion.tipo == tipo,
                Prediccion.objeto_id == objeto_id,
            )
            .order_by(Prediccion.created_at.desc())
        )
        .scalars()
        .first()
    )
    if fila is None:
        return None
    fila.real = Decimal(str(real))
    fila.real_at = _ahora()
    uow.db.flush()
    return fila


def acierto(
    db: Session, tenant_id: UUID, *, tipo: str, dias: int = 90, ahora: datetime | None = None
) -> dict[str, Any]:
    """Cómo está acertando el modelo sobre lo que ya se sabe.

    Solo cuenta lo que tiene resultado real: medir sobre lo que aún está abierto
    daría un acierto altísimo, porque lo abierto no ha tenido tiempo de
    desmentirlo.
    """
    momento = ahora or _ahora()
    desde = momento - timedelta(days=dias)
    filas = (
        db.execute(
            select(Prediccion).where(
                Prediccion.tenant_id == tenant_id,
                Prediccion.tipo == tipo,
                Prediccion.created_at >= desde,
                Prediccion.real.is_not(None),
            )
        )
        .scalars()
        .all()
    )
    if len(filas) < 20:
        return {
            "medible": False,
            "con_resultado": len(filas),
            "porque": (
                f"Solo {len(filas)} predicciones tienen resultado conocido: con menos "
                "de 20 el acierto que salga no significa nada."
            ),
        }
    errores = [abs(float(f.valor) - float(f.real or 0)) for f in filas]
    return {
        "medible": True,
        "con_resultado": len(filas),
        "error_medio": round(sum(errores) / len(errores), 2),
        "peor": round(max(errores), 2),
        # Las que fallaron por mucho son las que hay que mirar: el error medio se
        # come los casos graves.
        "muy_falladas": len([e for e in errores if e > 40]),
    }


def forecast_predictivo(
    db: Session,
    tenant_id: UUID,
    *,
    oportunidades: list[dict[str, Any]],
    forecast_humano: Decimal | None = None,
    ahora: datetime | None = None,
) -> dict[str, Any]:
    """Previsión a partir de las probabilidades, **al lado de la humana**
    (CRM-03.02.01.06).

    No la sustituye. Sustituirla hace que el comercial deje de comprometerse con
    su número, y el compromiso es la mitad del valor de un forecast: un modelo no
    puede llamar al cliente para que firme antes de fin de mes.

    Se devuelven los dos, **la diferencia y de dónde viene**. Cuando el humano
    dice mucho más que el modelo, la conversación útil es sobre qué operaciones
    concretas sostienen esa diferencia.
    """
    momento = ahora or _ahora()
    con_prediccion: list[dict[str, Any]] = []
    sin_prediccion: list[str] = []
    esperado = Decimal(0)
    bajo = Decimal(0)
    alto = Decimal(0)

    for oportunidad in oportunidades:
        objeto_id = oportunidad.get("id")
        importe = Decimal(str(oportunidad.get("importe") or 0))
        if objeto_id is None:
            continue
        estado = vigente(
            db, tenant_id, tipo="cierre", objeto_id=UUID(str(objeto_id)), ahora=momento
        )
        if not estado["hay"]:
            sin_prediccion.append(str(objeto_id))
            continue
        probabilidad = Decimal(str(estado["puntuacion"])) / 100
        aporta = _redondear(importe * probabilidad)
        esperado += aporta
        # Banda simple y explicada: las que están por encima del 70 % casi todas
        # entran, y las de menos del 30 % casi ninguna. No es un intervalo
        # estadístico y no se presenta como tal.
        if probabilidad >= Decimal("0.7"):
            bajo += importe
        if probabilidad >= Decimal("0.3"):
            alto += importe
        con_prediccion.append(
            {
                "oportunidad_id": str(objeto_id),
                "importe": str(importe),
                "probabilidad": float(probabilidad * 100),
                "aporta": str(aporta),
            }
        )

    humano = Decimal(forecast_humano) if forecast_humano is not None else None
    diferencia = (humano - esperado) if humano is not None else None
    return {
        "esperado": str(_redondear(esperado)),
        "banda_baja": str(_redondear(bajo)),
        "banda_alta": str(_redondear(alto)),
        "como_se_calcula_la_banda": (
            "Suma de lo que está por encima del 70 % (baja) y por encima del 30 % "
            "(alta). No es un intervalo estadístico: es una referencia explicable."
        ),
        "forecast_humano": str(humano) if humano is not None else None,
        "diferencia": str(_redondear(diferencia)) if diferencia is not None else None,
        "el_humano_es_mas_optimista": bool(diferencia is not None and diferencia > 0),
        "oportunidades": sorted(con_prediccion, key=lambda o: -float(o["aporta"])),
        # Lo que no se ha podido puntuar: un forecast predictivo calculado sobre
        # la mitad del pipeline parece bajo y no lo es.
        "sin_prediccion": sin_prediccion,
        "cobertura_pct": (
            round(100 * len(con_prediccion) / (len(con_prediccion) + len(sin_prediccion)), 1)
            if (con_prediccion or sin_prediccion)
            else None
        ),
        "sustituye_al_humano": False,
        "aviso": (
            ""
            if not sin_prediccion
            else f"{len(sin_prediccion)} oportunidades sin predicción vigente: el "
            "número sale bajo por eso, no porque el pipeline sea peor."
        ),
    }
