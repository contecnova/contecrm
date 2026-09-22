"""Por dónde va una instancia y dónde se atasca un proceso
(CRM-00.03.05.14, CRM-00.03.05.16).

Dos preguntas distintas y se responden con los mismos datos:

  * **«¿por dónde va ESTE expediente?»** — la hace quien tiene al cliente
    delante, y la respuesta tiene que caber en una pantalla sobre el propio
    gráfico que alguien dibujó, no en una lista de filas.
  * **«¿dónde se atasca ESTE proceso?»** — la hace quien lo diseñó, y la
    respuesta es lo único que convierte un flujo en algo que se puede mejorar.

Las dos salen del historial que ya se guarda paso a paso. Medir con una tabla
aparte las habría dejado contando cosas distintas en cuanto alguien tocara una.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from crmcore.errors import NoEncontrado
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.orchestrator.modelos import (
    DefinicionProceso,
    InstanciaProceso,
    PasoEjecutado,
    TareaHumana,
)


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _con_tz(v: datetime | None) -> datetime | None:
    if v is None:
        return None
    return v if v.tzinfo else v.replace(tzinfo=timezone.utc)


def vista_de_instancia(db: Session, tenant_id: UUID, instancia_id: UUID) -> dict[str, Any]:
    """El estado de una instancia **sobre su propio gráfico** (CRM-00.03.05.14).

    Devuelve cada nodo de la definición con su estado —`recorrido`, `actual`,
    `fallido`, `pendiente`— para que el lienzo lo pinte encima. No devuelve
    colores ni posiciones: eso es del front, y si viniera de aquí, cambiar la
    paleta sería un despliegue del backend.

    **Se pinta la versión con la que arrancó la instancia, no la publicada.** Una
    instancia en vuelo termina con su versión, así que enseñarla sobre el gráfico
    nuevo señalaría nodos que esa instancia no tiene y escondería los que sí
    está ejecutando.
    """
    instancia = db.execute(
        select(InstanciaProceso).where(
            InstanciaProceso.id == instancia_id, InstanciaProceso.tenant_id == tenant_id
        )
    ).scalar_one_or_none()
    if instancia is None:
        raise NoEncontrado("La instancia no existe", error_code="proceso.no_encontrado")

    definicion = db.get(DefinicionProceso, instancia.definicion_id)
    pasos = (definicion.definicion.get("pasos") or {}) if definicion else {}

    historial = (
        db.execute(
            select(PasoEjecutado)
            .where(PasoEjecutado.instancia_id == instancia.id)
            .order_by(PasoEjecutado.created_at)
        )
        .scalars()
        .all()
    )
    por_paso: dict[str, list[PasoEjecutado]] = {}
    for fila in historial:
        por_paso.setdefault(fila.paso, []).append(fila)

    tareas = {
        t.paso: t
        for t in db.execute(
            select(TareaHumana).where(TareaHumana.instancia_id == instancia.id)
        ).scalars()
    }

    nodos: list[dict[str, Any]] = []
    for nombre, definicion_paso in pasos.items():
        ejecuciones = por_paso.get(nombre, [])
        ultima = ejecuciones[-1] if ejecuciones else None
        if nombre == instancia.paso_actual:
            estado = "actual"
        elif ultima is None:
            # Un nodo sin ejecutar no es «pendiente» sin más: si la instancia ya
            # terminó, es un camino que NO se tomó, y decir «pendiente» haría
            # pensar que falta hacerlo.
            estado = (
                "pendiente" if instancia.estado not in ("completada", "fallida") else "no_recorrido"
            )
        elif ultima.resultado == "fallido":
            estado = "fallido"
        elif ultima.resultado == "compensado":
            estado = "compensado"
        else:
            estado = "recorrido"

        nodos.append(
            {
                "paso": nombre,
                "tipo": str(definicion_paso.get("tipo") or ""),
                "estado": estado,
                "veces": len(ejecuciones),
                "intentos": max((e.intento for e in ejecuciones), default=0),
                "duracion_ms": sum(e.duracion_ms for e in ejecuciones),
                "error": ultima.error if ultima else None,
                "tarea_pendiente": (
                    {
                        "id": str(tareas[nombre].id),
                        "titulo": tareas[nombre].titulo,
                        "estado": tareas[nombre].estado,
                        "vence_at": _con_tz(tareas[nombre].vence_at).isoformat()
                        if tareas[nombre].vence_at
                        else None,
                    }
                    if nombre in tareas
                    else None
                ),
            }
        )

    return {
        "instancia_id": str(instancia.id),
        "proceso": instancia.clave,
        # La versión se dice siempre: sin ella, quien mira el gráfico no sabe si
        # está viendo el proceso que se ejecutó o el que se publicó después.
        "version": instancia.version,
        "estado": instancia.estado,
        "paso_actual": instancia.paso_actual,
        "error": instancia.error,
        "arrancada_at": _con_tz(instancia.created_at).isoformat() if instancia.created_at else None,
        "finalizada_at": _con_tz(instancia.finalizada_at).isoformat()
        if instancia.finalizada_at
        else None,
        "nodos": nodos,
        # El camino real, en orden. Es lo que se lee cuando el gráfico tiene
        # bucles y el estado por nodo ya no basta para saber qué pasó antes.
        "recorrido": [
            {
                "paso": e.paso,
                "resultado": e.resultado,
                "at": _con_tz(e.created_at).isoformat() if e.created_at else None,
                "ms": e.duracion_ms,
            }
            for e in historial
        ],
    }


def analitica_de_proceso(
    db: Session, tenant_id: UUID, clave: str, *, dias: int = 30
) -> dict[str, Any]:
    """Dónde se atasca un proceso, cuánto tarda cada paso y quién lo frena
    (CRM-00.03.05.16).

    Tres decisiones sobre cómo se mide:

    **El tiempo de un paso humano se cuenta desde que se creó la tarea hasta que
    alguien respondió**, no lo que tardó el motor. Medir el motor da milisegundos
    en todos los pasos y esconde los tres días que esperó la firma, que es el
    único número que importa.

    **La mediana va junto a la media.** Un proceso con una instancia de treinta
    días y cien de una hora tiene una media que no describe a ninguna, y con solo
    la media se optimiza el paso equivocado.

    **Con pocas instancias se dice que no es concluyente**, no se calla el aviso.
    Un cuello de botella deducido de tres ejecuciones lleva a rediseñar un flujo
    que funcionaba.
    """
    desde = _ahora() - timedelta(days=dias)
    instancias = (
        db.execute(
            select(InstanciaProceso).where(
                InstanciaProceso.tenant_id == tenant_id,
                InstanciaProceso.clave == clave,
                InstanciaProceso.created_at >= desde,
            )
        )
        .scalars()
        .all()
    )
    if not instancias:
        return {
            "proceso": clave,
            "instancias": 0,
            "concluyente": False,
            "aviso": "No hay ninguna ejecución en el periodo: no hay nada que medir.",
            "pasos": [],
        }

    ids = [i.id for i in instancias]
    filas = (
        db.execute(select(PasoEjecutado).where(PasoEjecutado.instancia_id.in_(ids))).scalars().all()
    )
    tareas = (
        db.execute(select(TareaHumana).where(TareaHumana.instancia_id.in_(ids))).scalars().all()
    )

    duraciones: dict[str, list[float]] = {}
    fallos: dict[str, int] = {}
    reintentos: dict[str, int] = {}
    tipos: dict[str, str] = {}
    for f in filas:
        tipos[f.paso] = f.tipo
        duraciones.setdefault(f.paso, []).append(float(f.duracion_ms))
        if f.resultado == "fallido":
            fallos[f.paso] = fallos.get(f.paso, 0) + 1
        if f.intento > 1:
            reintentos[f.paso] = reintentos.get(f.paso, 0) + 1

    # Los pasos humanos se miden por la espera real, no por el motor.
    espera_humana: dict[str, list[float]] = {}
    quien_frena: dict[str, list[float]] = {}
    pendientes_humanas: dict[str, int] = {}
    for t in tareas:
        if t.completada_at and t.created_at:
            horas = (_con_tz(t.completada_at) - _con_tz(t.created_at)).total_seconds() / 3600
            espera_humana.setdefault(t.paso, []).append(horas)
            if t.completada_por:
                quien_frena.setdefault(str(t.completada_por), []).append(horas)
        elif t.estado == "pendiente":
            pendientes_humanas[t.paso] = pendientes_humanas.get(t.paso, 0) + 1

    def _mediana(valores: list[float]) -> float:
        if not valores:
            return 0.0
        orden = sorted(valores)
        n = len(orden)
        return orden[n // 2] if n % 2 else (orden[n // 2 - 1] + orden[n // 2]) / 2

    pasos = []
    for paso in sorted(set(duraciones) | set(espera_humana) | set(pendientes_humanas)):
        espera = espera_humana.get(paso, [])
        motor = duraciones.get(paso, [])
        pasos.append(
            {
                "paso": paso,
                "tipo": tipos.get(paso, "humano" if espera or paso in pendientes_humanas else ""),
                "veces": len(motor),
                "fallos": fallos.get(paso, 0),
                "con_reintento": reintentos.get(paso, 0),
                "motor_ms_medio": round(sum(motor) / len(motor), 1) if motor else 0,
                "espera_horas_media": round(sum(espera) / len(espera), 1) if espera else None,
                "espera_horas_mediana": round(_mediana(espera), 1) if espera else None,
                "pendientes_ahora": pendientes_humanas.get(paso, 0),
            }
        )

    # El cuello de botella es el paso con más espera humana acumulada. Se elige
    # por acumulado y no por media: un paso lentísimo que ocurre una vez al año
    # no es el problema del proceso.
    con_espera = [p for p in pasos if p["espera_horas_media"] is not None]
    cuello = max(
        con_espera,
        key=lambda p: (p["espera_horas_media"] or 0) * len(espera_humana.get(p["paso"], [])),
        default=None,
    )

    terminadas = [i for i in instancias if i.finalizada_at]
    ciclos = [
        (_con_tz(i.finalizada_at) - _con_tz(i.created_at)).total_seconds() / 3600
        for i in terminadas
    ]
    concluyente = len(instancias) >= 10

    return {
        "proceso": clave,
        "periodo_dias": dias,
        "instancias": len(instancias),
        "terminadas": len(terminadas),
        "en_vuelo": len(
            [i for i in instancias if i.estado in ("ejecutando", "esperando", "esperando_humano")]
        ),
        "falladas": len([i for i in instancias if i.estado == "fallida"]),
        "ciclo_horas_medio": round(sum(ciclos) / len(ciclos), 1) if ciclos else None,
        "ciclo_horas_mediana": round(_mediana(ciclos), 1) if ciclos else None,
        "pasos": pasos,
        "cuello_de_botella": cuello["paso"] if cuello else None,
        "personas_mas_lentas": sorted(
            (
                {
                    "usuario_id": usuario,
                    "tareas": len(horas),
                    "horas_medias": round(sum(horas) / len(horas), 1),
                }
                for usuario, horas in quien_frena.items()
                # Con menos de tres tareas el número no dice nada de nadie, y
                # publicarlo es señalar a una persona por una casualidad.
                if len(horas) >= 3
            ),
            key=lambda p: -p["horas_medias"],
        )[:10],
        "concluyente": concluyente,
        "aviso": (
            ""
            if concluyente
            else f"Solo {len(instancias)} ejecuciones en el periodo: el dato orienta, "
            "pero no basta para rediseñar el flujo."
        ),
    }
