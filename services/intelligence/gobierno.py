"""Gobierno de modelos: versión, métricas, deriva y reentrenamiento por tenant
(CRM-05.02.01.07, CRM-05.02.01.06).

Un modelo predictivo en un CRM se estropea sin avisar. No falla: **empeora**. Los
datos cambian —un producto nuevo, un mercado nuevo, un equipo nuevo— y el modelo
sigue puntuando con lo que aprendió de un mundo que ya no existe. Nadie lo nota,
porque las puntuaciones siguen saliendo.

De ahí las cuatro decisiones:

**Un modelo sin métricas no se activa.** Ni «ya lo validamos», ni «lo entrenó el
equipo de datos». Si no consta con qué acertaba y sobre qué muestra, no se puede
saber si la versión siguiente mejora o empeora, y la comparación es lo único que
hace que esto sea ingeniería.

**Cada tenant entrena con lo suyo y solo con lo suyo.** Un modelo compartido
aprende de los clientes de uno y puntúa a los de otro: es una fuga que no se ve
porque no viaja ningún dato — viaja lo aprendido de ese dato. Y además funciona
peor, porque el ciclo de venta de una asesoría no se parece al de una ferretería.

**La deriva se mide contra lo que pasó de verdad, no contra el entrenamiento.**
Comparar la distribución de entradas dice que algo cambió; comparar el acierto
dice si eso importa. Lo segundo es lo que decide si hay que reentrenar.

**Un modelo caducado deja de puntuar.** Sigue existiendo y se puede consultar lo
que dijo, pero no produce predicciones nuevas: una puntuación de un modelo
entrenado hace dos años es peor que ninguna, porque nadie duda de ella.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from crmcore.audit import registrar
from crmcore.db.base import Base, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import (
    Date,
    DateTime,
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

# Qué predice cada modelo. Cerrada porque cada uno tiene su métrica de calidad y
# su forma de equivocarse: un clasificador de churn y una regresión de importe no
# se evalúan igual, y darles la misma escala haría que el peor pareciera bueno.
TIPOS = (
    "scoring_lead",
    "scoring_oportunidad",
    "cierre",
    "importe",
    "fecha_cierre",
    "propension",
    "churn",
    "anomalia",
)

# Estados del ciclo de vida de una versión.
#
#   entrenando  en curso
#   evaluada    tiene métricas; todavía no puntúa
#   activa      la que se usa
#   retirada    ya no puntúa; sus predicciones pasadas se conservan
ESTADOS = ("entrenando", "evaluada", "activa", "retirada")

# Métricas mínimas por familia. Sin ellas no se activa: no es burocracia, es que
# sin ellas no se puede comparar con la versión siguiente.
MINIMAS: dict[str, tuple[str, ...]] = {
    "clasificacion": ("auc", "precision", "recall", "muestras"),
    "regresion": ("mae", "muestras"),
}

# A qué familia pertenece cada tipo.
FAMILIA = {
    "scoring_lead": "clasificacion",
    "scoring_oportunidad": "clasificacion",
    "cierre": "clasificacion",
    "propension": "clasificacion",
    "churn": "clasificacion",
    "anomalia": "clasificacion",
    "importe": "regresion",
    "fecha_cierre": "regresion",
}


class ModeloML(Base, TimestampMixin):
    """Una versión entrenada de un modelo predictivo (CRM-05.02.01.07).

    Es del tenant siempre: entrenar con los datos de uno y puntuar a los de otro
    es una fuga que no se ve, porque no viaja el dato sino lo aprendido de él.
    """

    __tablename__ = "modelos_ml"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    tipo: Mapped[str] = mapped_column(String(30), nullable=False, info={"opciones": TIPOS})
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="entrenando")

    # Con qué se entrenó: ventana de datos y número de ejemplos. Sin la ventana,
    # un modelo que aprendió del confinamiento parece igual de bueno que uno
    # entrenado el mes pasado.
    datos_desde: Mapped[date | None] = mapped_column(Date, nullable=True)
    datos_hasta: Mapped[date | None] = mapped_column(Date, nullable=True)
    ejemplos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Qué mira. Se guarda para poder explicar una puntuación y para saber qué se
    # rompe cuando alguien retira un campo del CRM.
    variables: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Cuánto pesa cada variable. Es lo que convierte una puntuación en una
    # explicación (CRM-05.02.01.01).
    pesos: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    metricas: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    entrenado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    activado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Cuántos días vale lo aprendido. Pasado eso deja de puntuar: una puntuación
    # de un modelo de hace dos años es peor que ninguna, porque nadie duda de ella.
    vigencia_dias: Mapped[int] = mapped_column(Integer, nullable=False, default=180)
    notas: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (
        UniqueConstraint("tenant_id", "tipo", "version", name="uq_modelo_ml_version"),
        Index("ix_modelos_ml", "tenant_id", "tipo", "estado"),
    )


class MedicionDeriva(Base):
    """Qué tal va acertando el modelo con el tiempo (CRM-05.02.01.07)."""

    __tablename__ = "derivas_modelo"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    modelo_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    ventana_desde: Mapped[date] = mapped_column(Date, nullable=False)
    ventana_hasta: Mapped[date] = mapped_column(Date, nullable=False)
    # Acierto medido **contra lo que pasó de verdad**, no contra el conjunto de
    # entrenamiento: eso último solo dice que el modelo se acuerda.
    metrica: Mapped[str] = mapped_column(String(30), nullable=False, default="auc")
    valor: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=0)
    referencia: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=0)
    muestras: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("ix_derivas_modelo", "tenant_id", "modelo_id", "created_at"),)


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _hoy() -> date:
    return datetime.now(timezone.utc).date()


def _con_tz(valor: datetime | None) -> datetime | None:
    if valor is None:
        return None
    return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)


def registrar_version(
    uow: UnidadDeTrabajo,
    *,
    tipo: str,
    variables: list[str],
    pesos: dict[str, float] | None = None,
    metricas: dict[str, Any] | None = None,
    datos_desde: date | None = None,
    datos_hasta: date | None = None,
    ejemplos: int = 0,
    vigencia_dias: int = 180,
    notas: str = "",
) -> tuple[ModeloML, list[str]]:
    """Registra una versión entrenada (CRM-05.02.01.06).

    Entrenar con los datos de **este** tenant es lo que se declara aquí: la
    ventana y el número de ejemplos son del tenant, y no hay forma de registrar
    una versión con datos de varios porque no existe el campo.
    """
    if tipo not in TIPOS:
        raise ErrorValidacion(
            f"Tipo de modelo «{tipo}» no reconocido.",
            error_code="gobierno.tipo_no_valido",
            detalle={"validos": list(TIPOS)},
        )
    if not variables:
        raise ErrorValidacion(
            "Un modelo tiene que declarar qué mira: sin eso no se puede explicar "
            "una puntuación ni saber qué se rompe si alguien quita un campo.",
            error_code="gobierno.sin_variables",
        )
    avisos: list[str] = []
    if ejemplos and ejemplos < 200:
        avisos.append(
            f"Entrenado con {ejemplos} ejemplos: con tan pocos, el modelo aprende "
            "el ruido de esos casos y no el patrón. Sus métricas van a parecer "
            "mejores de lo que son."
        )
    if datos_desde is None or datos_hasta is None:
        avisos.append(
            "Sin ventana de datos declarada: un modelo entrenado con datos de hace "
            "tres años parecerá igual de bueno que uno de este mes."
        )

    ultima = (
        uow.db.execute(
            select(ModeloML)
            .where(ModeloML.tenant_id == uow.tenant_id, ModeloML.tipo == tipo)
            .order_by(ModeloML.version.desc())
        )
        .scalars()
        .first()
    )
    fila = ModeloML(
        tenant_id=uow.tenant_id,
        tipo=tipo,
        version=(ultima.version + 1) if ultima else 1,
        estado="evaluada" if metricas else "entrenando",
        variables=list(variables),
        pesos=dict(pesos or {}),
        metricas=dict(metricas or {}),
        datos_desde=datos_desde,
        datos_hasta=datos_hasta,
        ejemplos=max(0, int(ejemplos)),
        vigencia_dias=max(1, int(vigencia_dias)),
        entrenado_at=_ahora(),
        notas=notas,
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila, avisos


def activar(uow: UnidadDeTrabajo, *, tipo: str, version: int) -> dict[str, Any]:
    """Pone una versión a puntuar, **si tiene métricas** (CRM-05.02.01.07).

    Sin ellas no se activa. No es burocracia: sin métricas no se puede decir si la
    versión nueva mejora o empeora, y entonces cada reentrenamiento es un salto de
    fe con las puntuaciones de todo el mundo dentro.

    Y se devuelve **la comparación con la que estaba**: activar algo peor que lo
    anterior pasa, y pasa sin que nadie lo vea.
    """
    fila = uow.db.execute(
        select(ModeloML).where(
            ModeloML.tenant_id == uow.tenant_id,
            ModeloML.tipo == tipo,
            ModeloML.version == version,
        )
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado("Esa versión no existe", error_code="gobierno.no_encontrada")

    familia = FAMILIA.get(tipo, "clasificacion")
    faltan = [m for m in MINIMAS[familia] if m not in (fila.metricas or {})]
    if faltan:
        raise Conflicto(
            "No se activa un modelo sin sus métricas: sin ellas no se puede saber "
            "si la versión siguiente mejora o empeora.",
            error_code="gobierno.sin_metricas",
            detalle={"faltan": faltan},
        )

    anterior = (
        uow.db.execute(
            select(ModeloML).where(
                ModeloML.tenant_id == uow.tenant_id,
                ModeloML.tipo == tipo,
                ModeloML.estado == "activa",
            )
        )
        .scalars()
        .first()
    )
    comparacion: dict[str, Any] = {"habia_anterior": anterior is not None}
    if anterior is not None:
        clave = "auc" if familia == "clasificacion" else "mae"
        antes = float((anterior.metricas or {}).get(clave) or 0)
        ahora = float((fila.metricas or {}).get(clave) or 0)
        # En clasificación más es mejor; en regresión, menos.
        mejora = ahora > antes if familia == "clasificacion" else ahora < antes
        comparacion.update(
            {
                "metrica": clave,
                "anterior": antes,
                "nueva": ahora,
                "mejora": mejora,
                # Activar algo peor es una decisión legítima —a veces se prefiere
                # un modelo más simple— pero tiene que verse.
                "aviso": (
                    "" if mejora else f"La versión nueva no mejora en {clave}: {antes} → {ahora}."
                ),
            }
        )
        anterior.estado = "retirada"

    fila.estado = "activa"
    fila.activado_at = _ahora()
    uow.db.flush()
    registrar(
        uow.db,
        accion="modelo.activado",
        objeto="modelo_ml",
        objeto_id=fila.id,
        datos={"tipo": tipo, "version": version, "comparacion": comparacion},
        tenant_id=uow.tenant_id,
    )
    return {"tipo": tipo, "version": version, "comparacion": comparacion}


def activo(db: Session, tenant_id: UUID, tipo: str, *, hoy: date | None = None) -> ModeloML | None:
    """El modelo que puntúa ahora, **si sigue vigente**.

    Un modelo caducado no puntúa: sigue existiendo y se puede consultar lo que
    dijo, pero no produce predicciones nuevas.
    """
    fila = (
        db.execute(
            select(ModeloML).where(
                ModeloML.tenant_id == tenant_id,
                ModeloML.tipo == tipo,
                ModeloML.estado == "activa",
            )
        )
        .scalars()
        .first()
    )
    if fila is None:
        return None
    entrenado = _con_tz(fila.entrenado_at)
    if entrenado is None:
        return None
    limite = entrenado + timedelta(days=fila.vigencia_dias)
    momento = datetime.combine(hoy, datetime.min.time(), tzinfo=timezone.utc) if hoy else _ahora()
    return fila if momento <= limite else None


def exigir_activo(db: Session, tenant_id: UUID, tipo: str) -> ModeloML:
    """El modelo vigente, o un error que dice qué falta."""
    fila = activo(db, tenant_id, tipo)
    if fila is not None:
        return fila
    cualquiera = (
        db.execute(
            select(ModeloML)
            .where(ModeloML.tenant_id == tenant_id, ModeloML.tipo == tipo)
            .order_by(ModeloML.version.desc())
        )
        .scalars()
        .first()
    )
    if cualquiera is None:
        raise NoEncontrado(
            f"No hay ningún modelo «{tipo}» entrenado para este tenant. Los modelos "
            "se entrenan con los datos de cada cliente: no hay uno compartido que "
            "puntúe mientras tanto.",
            error_code="gobierno.sin_modelo",
        )
    raise Conflicto(
        f"El modelo «{tipo}» está caducado o retirado y ha dejado de puntuar. Una "
        "puntuación de un modelo viejo es peor que ninguna, porque nadie duda de ella.",
        error_code="gobierno.modelo_caducado",
        detalle={"version": cualquiera.version, "estado": cualquiera.estado},
    )


def medir_deriva(
    uow: UnidadDeTrabajo,
    *,
    tipo: str,
    metrica: str,
    valor: float,
    muestras: int,
    desde: date,
    hasta: date,
) -> dict[str, Any]:
    """Anota cómo acertó el modelo en una ventana real (CRM-05.02.01.07).

    Se mide **contra lo que pasó**, no contra el conjunto de entrenamiento: eso
    último solo dice que el modelo se acuerda de lo que vio.

    Con pocas muestras no se concluye: veinte oportunidades cerradas en un mes
    flojo darían una caída que solo es el mes.
    """
    fila = uow.db.execute(
        select(ModeloML).where(
            ModeloML.tenant_id == uow.tenant_id,
            ModeloML.tipo == tipo,
            ModeloML.estado == "activa",
        )
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado("No hay modelo activo de ese tipo", error_code="gobierno.sin_modelo")
    referencia = Decimal(str((fila.metricas or {}).get(metrica) or 0))
    medicion = MedicionDeriva(
        tenant_id=uow.tenant_id,
        modelo_id=fila.id,
        ventana_desde=desde,
        ventana_hasta=hasta,
        metrica=metrica,
        valor=Decimal(str(valor)),
        referencia=referencia,
        muestras=max(0, int(muestras)),
    )
    uow.db.add(medicion)
    uow.db.flush()

    familia = FAMILIA.get(tipo, "clasificacion")
    peor = (
        Decimal(str(valor)) < referencia
        if familia == "clasificacion"
        else Decimal(str(valor)) > referencia
    )
    caida = abs(float(referencia) - float(valor))
    suficientes = muestras >= 100
    return {
        "modelo": f"{tipo} v{fila.version}",
        "metrica": metrica,
        "en_entrenamiento": float(referencia),
        "ahora": float(valor),
        "muestras": muestras,
        "empeora": bool(peor),
        # Con pocas muestras no se concluye: sería confundir un mes flojo con un
        # modelo roto, y reentrenar por eso empeora el modelo.
        "concluyente": suficientes,
        "reentrenar": bool(peor and suficientes and caida > 0.05),
        "porque": (
            f"Con {muestras} muestras no se puede concluir: hacen falta al menos 100."
            if not suficientes
            else (
                f"El acierto ha bajado de {referencia} a {valor}: toca reentrenar."
                if peor and caida > 0.05
                else "El modelo sigue acertando como cuando se entrenó."
            )
        ),
    }


def estado_modelos(db: Session, tenant_id: UUID, *, hoy: date | None = None) -> dict[str, Any]:
    """Qué modelos hay, cuáles puntúan y cuáles han caducado.

    Es la pantalla que evita el problema de siempre: nadie mira los modelos hasta
    que alguien se queja de una puntuación, y para entonces llevan meses
    equivocándose.
    """
    momento = hoy or _hoy()
    filas = db.execute(select(ModeloML).where(ModeloML.tenant_id == tenant_id)).scalars().all()
    salida = []
    for fila in filas:
        entrenado = _con_tz(fila.entrenado_at)
        dias = (momento - entrenado.date()).days if entrenado else None
        caducado = bool(fila.estado == "activa" and dias is not None and dias > fila.vigencia_dias)
        salida.append(
            {
                "tipo": fila.tipo,
                "version": fila.version,
                "estado": fila.estado,
                "entrenado_hace_dias": dias,
                "vigencia_dias": fila.vigencia_dias,
                "caducado": caducado,
                "ejemplos": fila.ejemplos,
                "metricas": fila.metricas,
                "ventana": (
                    f"{fila.datos_desde} → {fila.datos_hasta}"
                    if fila.datos_desde and fila.datos_hasta
                    else ""
                ),
            }
        )
    activos = [s for s in salida if s["estado"] == "activa"]
    return {
        "modelos": sorted(salida, key=lambda m: (m["tipo"], -m["version"])),
        "activos": len(activos),
        # Los caducados que siguen marcados activos son los peligrosos: figuran
        # como buenos y han dejado de puntuar sin que nadie lo note.
        "caducados": [m["tipo"] for m in activos if m["caducado"]],
        "sin_modelo": sorted(set(TIPOS) - {m["tipo"] for m in activos}),
    }
