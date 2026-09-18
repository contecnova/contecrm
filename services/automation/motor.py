"""Evaluación y ejecución de automatizaciones.

Dos garantías que vienen del catálogo y que aquí se implementan a la vez, porque
una sin la otra no sirve:

**Orden determinista** (CRM-00.03.03.06). Las reglas del mismo disparador se
ejecutan por prioridad y, a igualdad, por fecha de creación. Sin un orden fijo,
dos reglas que tocan el mismo campo dan un resultado u otro según cómo la base
devuelva las filas, y el sistema se vuelve irreproducible.

**Corte de cascada**. Una acción puede modificar un registro y disparar otra
regla, que modifica otro y dispara una tercera. Es útil hasta que dos reglas se
disparan mutuamente: entonces es un bucle infinito que consume el sistema. El
contador de profundidad va en el contexto de ejecución y corta al llegar al
tope configurado.
"""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID

from crmcore.logging import get_logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.automation.modelos import Automatizacion, EjecucionAutomatizacion

logger = get_logger(__name__)

# Acciones admitidas. Lista cerrada: una automatización es dato del tenant, así
# que no puede ejecutar nada que no esté aquí. Añadir una acción es una decisión
# de producto, no algo que se cuele en una configuración.
ACCIONES = frozenset(
    {
        "crear_registro",
        "actualizar_registro",
        "asignar",
        "notificar",
        "enviar_correo",
        "llamar_api",
        "lanzar_proceso",
        "emitir_evento",
        "calcular",
    }
)


class ContextoEjecucion:
    """Estado compartido durante una cadena de automatizaciones.

    Lleva la cuenta de la profundidad y de qué registros ya se han tocado, que
    es lo que permite detener una cascada antes de que se convierta en bucle.
    """

    def __init__(self, profundidad: int = 0) -> None:
        self.profundidad = profundidad
        self.tocados: set[tuple[str, str]] = set()


def aplicables(
    db: Session,
    *,
    tenant_id: UUID,
    disparador: str,
    objetivo: str,
    campos_cambiados: set[str] | None = None,
) -> list[Automatizacion]:
    """Reglas activas para este disparador, en orden determinista."""
    reglas = (
        db.execute(
            select(Automatizacion)
            .where(
                Automatizacion.tenant_id == tenant_id,
                Automatizacion.activa.is_(True),
                Automatizacion.disparador == disparador,
                Automatizacion.objetivo == objetivo,
            )
            .order_by(Automatizacion.prioridad, Automatizacion.created_at)
        )
        .scalars()
        .all()
    )
    if disparador != "modificacion" or campos_cambiados is None:
        return list(reglas)
    # Con campos vigilados declarados, solo entran las que vigilan alguno de los
    # que han cambiado. Es lo que evita que «cuando cambie la etapa» se dispare
    # al corregir un teléfono.
    return [
        r for r in reglas if not r.campos_vigilados or (set(r.campos_vigilados) & campos_cambiados)
    ]


def evaluar_condiciones(
    regla: Automatizacion, valores: dict[str, Any]
) -> tuple[bool, list[dict[str, Any]]]:
    """Evalúa las condiciones y devuelve (se cumple, decisiones explicadas)."""
    from services.orchestrator.motor import OPERADORES, resolver

    decisiones: list[dict[str, Any]] = []
    resultados: list[bool] = []
    for condicion in regla.condiciones or []:
        atributo = str(condicion.get("atributo", ""))
        op_nombre = str(condicion.get("op", "="))
        op = OPERADORES.get(op_nombre)
        izquierda = resolver(f"@{atributo}", valores)
        derecha = resolver(condicion.get("valor"), valores)
        try:
            cumple = bool(op(izquierda, derecha)) if op else False
        except TypeError:
            cumple = False
        resultados.append(cumple)
        decisiones.append(
            {
                "atributo": atributo,
                "operador": op_nombre,
                "valor_actual": izquierda,
                "valor_esperado": derecha,
                "cumple": cumple,
            }
        )

    if not resultados:
        return True, decisiones
    cumple_todo = all(resultados) if regla.combinacion == "todas" else any(resultados)
    return cumple_todo, decisiones


def ejecutar(
    db: Session,
    regla: Automatizacion,
    *,
    valores: dict[str, Any],
    objeto: str,
    registro_id: str | None,
    ejecutores: dict[str, Any],
    contexto: ContextoEjecucion | None = None,
) -> EjecucionAutomatizacion:
    """Evalúa y ejecuta una regla, dejando traza pase lo que pase.

    Se registra también cuando NO se dispara: es la única forma de responder a
    «¿por qué no se ha asignado este lead?», que es la pregunta más frecuente
    sobre cualquier motor de reglas.
    """
    from crmcore.config import get_settings

    contexto = contexto or ContextoEjecucion()
    inicio = time.perf_counter()
    traza = EjecucionAutomatizacion(
        tenant_id=regla.tenant_id,
        automatizacion_id=regla.id,
        objeto=objeto,
        registro_id=registro_id,
        resultado="disparada",
        profundidad_cascada=contexto.profundidad,
    )

    tope = get_settings().automatizacion_max_cascada
    if contexto.profundidad >= tope:
        traza.resultado = "omitida_por_cascada"
        traza.error = (
            f"Cadena de {contexto.profundidad} automatizaciones: se corta en {tope} "
            "para evitar un bucle entre reglas"
        )
        logger.warning(
            "automatizacion.cascada_cortada",
            regla=regla.nombre,
            profundidad=contexto.profundidad,
        )
        db.add(traza)
        return traza

    cumple, decisiones = evaluar_condiciones(regla, valores)
    traza.decisiones = decisiones
    if not cumple:
        traza.resultado = "condiciones_no_cumplidas"
        traza.duracion_ms = int((time.perf_counter() - inicio) * 1000)
        db.add(traza)
        return traza

    ejecutadas: list[dict[str, Any]] = []
    for accion in regla.acciones or []:
        tipo = str(accion.get("tipo", ""))
        if tipo not in ACCIONES:
            traza.resultado = "fallida"
            traza.error = f"Acción no admitida: «{tipo}»"
            break
        ejecutor = ejecutores.get(tipo)
        if ejecutor is None:
            traza.resultado = "fallida"
            traza.error = f"No hay ejecutor registrado para «{tipo}»"
            break
        try:
            from services.orchestrator.motor import resolver

            salida = ejecutor(
                **resolver(accion.get("parametros") or {}, valores),
                _contexto=ContextoEjecucion(contexto.profundidad + 1),
                _tenant_id=regla.tenant_id,
            )
            ejecutadas.append({"tipo": tipo, "salida": salida})
        except Exception as exc:  # noqa: BLE001 — una acción rota no tumba el flujo
            # Se para la regla pero no se propaga: una automatización que falla
            # no puede impedir que se guarde el registro que la disparó. El
            # usuario perdería su trabajo por una regla mal configurada.
            traza.resultado = "fallida"
            traza.error = str(exc)[:2000]
            regla.fallos += 1
            logger.error(
                "automatizacion.accion_fallida",
                regla=regla.nombre,
                accion=tipo,
                error=str(exc)[:200],
            )
            break

    traza.acciones_ejecutadas = ejecutadas
    traza.duracion_ms = int((time.perf_counter() - inicio) * 1000)
    regla.ejecuciones += 1
    from datetime import datetime, timezone

    regla.ultima_ejecucion_at = datetime.now(timezone.utc)
    db.add(traza)
    return traza


def disparar(
    db: Session,
    *,
    tenant_id: UUID,
    disparador: str,
    objetivo: str,
    valores: dict[str, Any],
    registro_id: str | None = None,
    campos_cambiados: set[str] | None = None,
    ejecutores: dict[str, Any] | None = None,
    contexto: ContextoEjecucion | None = None,
) -> list[EjecucionAutomatizacion]:
    """Ejecuta todas las reglas aplicables, en orden."""
    reglas = aplicables(
        db,
        tenant_id=tenant_id,
        disparador=disparador,
        objetivo=objetivo,
        campos_cambiados=campos_cambiados,
    )
    return [
        ejecutar(
            db,
            regla,
            valores=valores,
            objeto=objetivo,
            registro_id=registro_id,
            ejecutores=ejecutores or {},
            contexto=contexto,
        )
        for regla in reglas
    ]
