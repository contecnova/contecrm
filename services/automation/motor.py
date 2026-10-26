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
# Toda acción de esta lista TIENE ejecutor (`services.automation.ejecutores`), y
# hay un gate que lo comprueba. Declarar una acción sin ejecutor es peor que no
# declararla: la regla se guarda, se valida, se simula y al ejecutarse falla —o,
# antes de esto, no hacía nada en silencio.
#
# `enviar_correo` estuvo fuera mientras no hubo con qué enviar. Vuelve con el
# repartidor de notificaciones (CRM-06.02.01.02), que es lo que hacía falta para
# que la acción se pudiera ejecutar entera y no solo guardarse.
# Acciones de CONTROL: no hacen nada por sí mismas, deciden qué se ejecuta
# (CRM-00.03.03.04). Van aparte de las acciones normales porque el motor las
# interpreta en vez de delegarlas en un ejecutor, y confundirlas llevaría a
# buscar un «ejecutor de si» que no existe ni debe existir.
CONTROL = frozenset({"si", "para_cada", "fijar"})

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
    """Evalúa las condiciones de disparo y devuelve (se cumple, decisiones)."""
    return _evaluar_lista(regla.condiciones or [], valores, combinacion=regla.combinacion)


def _evaluar_lista(
    condiciones: list[Any], valores: dict[str, Any], *, combinacion: str = "todas"
) -> tuple[bool, list[dict[str, Any]]]:
    """La gramática de condiciones, una sola para disparar y para ramificar.

    Una sola a propósito: dos gramáticas en el mismo motor —una para decidir si
    la regla salta y otra para decidir por qué rama va— es garantía de que se
    comportarán distinto ante el mismo dato, y nadie sabrá cuál mira qué.
    """
    from services.orchestrator.motor import OPERADORES, resolver

    decisiones: list[dict[str, Any]] = []
    resultados: list[bool] = []
    for condicion in condiciones:
        if not isinstance(condicion, dict):
            continue
        atributo = str(condicion.get("atributo", "")).strip()
        op_nombre = str(condicion.get("op", "="))
        op = OPERADORES.get(op_nombre)
        izquierda = resolver(f"@{atributo}", valores)
        derecha = resolver(condicion.get("valor"), valores)
        try:
            # Sin atributo **no se cumple**, igual que en el motor de procesos y
            # en los webhooks. `resolver("@", …)` da nulo, el valor por defecto
            # también, y el `=` los daba por iguales: una regla con la condición
            # mal escrita se disparaba con TODO, que en una automatización es
            # mandar correos o cambiar registros que nadie pidió tocar.
            cumple = bool(op(izquierda, derecha)) if (op and atributo) else False
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
    return (all(resultados) if combinacion == "todas" else any(resultados)), decisiones


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

    # El ámbito arranca con los valores del registro y va creciendo con las
    # variables de flujo. Es una copia: escribir sobre `valores` haría que una
    # regla contaminara a la siguiente, y el síntoma —«esta regla funciona sola
    # pero no cuando corre después de aquella»— es de los caros de encontrar.
    ambito = dict(valores)
    ejecutadas: list[dict[str, Any]] = []
    error = _ejecutar_bloque(
        regla.acciones or [],
        ambito=ambito,
        ejecutadas=ejecutadas,
        ejecutores=ejecutores,
        regla=regla,
        contexto=contexto,
        nivel=0,
    )
    if error:
        traza.resultado = "fallida"
        traza.error = error[:2000]
        regla.fallos += 1
        logger.error("automatizacion.accion_fallida", regla=regla.nombre, error=error[:200])

    traza.acciones_ejecutadas = ejecutadas
    # Las variables que quedaron, en la traza: sin ellas, «¿por qué entró por
    # esta rama?» no se puede contestar, y contestarlo es la única razón de que
    # este motor deje traza de todo.
    traza.decisiones = {**(traza.decisiones or {}), "variables": _serializable(ambito)}
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


# ── Control de flujo (CRM-00.03.03.04) ────────────────────────────────────


def _ejecutar_bloque(
    acciones: list[Any],
    *,
    ambito: dict[str, Any],
    ejecutadas: list[dict[str, Any]],
    ejecutores: dict[str, Any],
    regla: Automatizacion,
    contexto: ContextoEjecucion,
    nivel: int,
) -> str | None:
    """Ejecuta una lista de acciones, que puede llevar ramas y bucles dentro.

    Devuelve el error si algo falla, o `None`. Se para en el primer fallo y NO
    se propaga: una automatización rota no puede impedir que se guarde el
    registro que la disparó, o el usuario perdería su trabajo por una regla mal
    configurada.

    El anidamiento tiene tope. Tres niveles cubren todo lo que alguien
    construye en una interfaz; más que eso es un proceso, y para eso está el
    motor de procesos, que sabe reanudar y compensar — cosas que una
    automatización no hace ni debe intentar.
    """
    from crmcore.config import get_settings

    if nivel > get_settings().automatizacion_max_anidamiento:
        return (
            f"Ramas y bucles anidados más de {get_settings().automatizacion_max_anidamiento} "
            "niveles: eso es un proceso, no una automatización"
        )

    for accion in acciones:
        if not isinstance(accion, dict):
            return f"Acción mal formada: {accion!r}"
        tipo = str(accion.get("tipo", ""))

        if tipo == "fijar":
            error = _fijar(accion, ambito, ejecutadas)
            if error:
                return error
            continue

        if tipo == "si":
            error = _rama(
                accion,
                ambito=ambito,
                ejecutadas=ejecutadas,
                ejecutores=ejecutores,
                regla=regla,
                contexto=contexto,
                nivel=nivel,
            )
            if error:
                return error
            continue

        if tipo == "para_cada":
            error = _bucle(
                accion,
                ambito=ambito,
                ejecutadas=ejecutadas,
                ejecutores=ejecutores,
                regla=regla,
                contexto=contexto,
                nivel=nivel,
            )
            if error:
                return error
            continue

        if tipo not in ACCIONES:
            return f"Acción no admitida: «{tipo}»"
        ejecutor = ejecutores.get(tipo)
        if ejecutor is None:
            return f"No hay ejecutor registrado para «{tipo}»"
        try:
            from services.orchestrator.motor import resolver

            salida = ejecutor(
                **resolver(accion.get("parametros") or {}, ambito),
                _contexto=ContextoEjecucion(contexto.profundidad + 1),
                _tenant_id=regla.tenant_id,
            )
            ejecutadas.append({"tipo": tipo, "salida": salida})
            # La salida queda disponible para las acciones siguientes si se le
            # pone nombre. Sin esto, encadenar «crea el registro y luego
            # notifica sobre él» obligaría a volver a buscarlo.
            nombre = accion.get("guardar_en")
            if isinstance(nombre, str) and nombre:
                ambito[nombre] = salida
        except Exception as exc:  # noqa: BLE001 — una acción rota no tumba el flujo
            return str(exc)
    return None


def _fijar(
    accion: dict[str, Any], ambito: dict[str, Any], ejecutadas: list[dict[str, Any]]
) -> str | None:
    """Declara una variable de flujo.

    El nombre se valida: una variable que se llama como un campo del registro lo
    taparía para el resto de la regla, y el efecto —«esta condición mira otro
    valor a partir de aquí»— no se ve leyendo la regla.
    """
    from services.orchestrator.motor import resolver

    nombre = str(accion.get("nombre", "")).strip()
    if not nombre:
        return "Una variable de flujo necesita nombre"
    if nombre.startswith("_"):
        return f"«{nombre}»: los nombres que empiezan por «_» están reservados"
    valor = resolver({"v": accion.get("valor")}, ambito)["v"]
    ambito[nombre] = valor
    ejecutadas.append({"tipo": "fijar", "nombre": nombre})
    return None


def _rama(
    accion: dict[str, Any],
    *,
    ambito: dict[str, Any],
    ejecutadas: list[dict[str, Any]],
    ejecutores: dict[str, Any],
    regla: Automatizacion,
    contexto: ContextoEjecucion,
    nivel: int,
) -> str | None:
    """`si` / `si_no`, con la misma gramática de condiciones que la regla.

    La misma a propósito: dos gramáticas de condición en el mismo motor —una
    para disparar y otra para ramificar— es garantía de que se comportarán
    distinto ante el mismo dato, y nadie sabrá cuál mira qué.
    """
    condiciones = accion.get("condiciones") or []
    cumple, decisiones = _evaluar_lista(condiciones, ambito)
    ejecutadas.append({"tipo": "si", "cumple": cumple, "decisiones": decisiones})
    bloque = accion.get("entonces" if cumple else "si_no") or []
    return _ejecutar_bloque(
        bloque,
        ambito=ambito,
        ejecutadas=ejecutadas,
        ejecutores=ejecutores,
        regla=regla,
        contexto=contexto,
        nivel=nivel + 1,
    )


def _bucle(
    accion: dict[str, Any],
    *,
    ambito: dict[str, Any],
    ejecutadas: list[dict[str, Any]],
    ejecutores: dict[str, Any],
    regla: Automatizacion,
    contexto: ContextoEjecucion,
    nivel: int,
) -> str | None:
    """`para_cada`: recorre una colección del ámbito.

    Con tope de vueltas, y cuando se corta **se dice en la traza**. Una
    iteración que se queda a medias en silencio es peor que no tenerla, porque
    el resultado parcial parece completo: alguien ve «automatización disparada»
    y da por hecho que recorrió las seiscientas líneas.
    """
    from crmcore.config import get_settings

    from services.orchestrator.motor import resolver

    sobre = resolver({"v": accion.get("sobre")}, ambito)["v"]
    if not isinstance(sobre, (list, tuple)):
        return f"«para_cada» esperaba una lista y ha recibido {type(sobre).__name__}"
    como = str(accion.get("como", "elemento")).strip() or "elemento"

    tope = get_settings().automatizacion_max_vueltas
    cortado = len(sobre) > tope
    for elemento in list(sobre)[:tope]:
        ambito[como] = elemento
        error = _ejecutar_bloque(
            accion.get("hacer") or [],
            ambito=ambito,
            ejecutadas=ejecutadas,
            ejecutores=ejecutores,
            regla=regla,
            contexto=contexto,
            nivel=nivel + 1,
        )
        if error:
            return error
    ambito.pop(como, None)
    ejecutadas.append(
        {
            "tipo": "para_cada",
            "vueltas": min(len(sobre), tope),
            "cortado": cortado,
            "de": len(sobre),
        }
    )
    if cortado:
        logger.warning(
            "automatizacion.bucle_cortado", regla=regla.nombre, elementos=len(sobre), tope=tope
        )
    return None


def _serializable(ambito: dict[str, Any]) -> dict[str, Any]:
    """El ámbito, recortado para poder guardarlo en la traza.

    Se recorta porque una variable puede acabar conteniendo la respuesta entera
    de una API, y la traza no es un sitio donde guardar cargas útiles: se
    consulta para entender una decisión, no para recuperar datos.
    """
    salida: dict[str, Any] = {}
    for clave, valor in ambito.items():
        if isinstance(valor, (str, int, float, bool)) or valor is None:
            salida[clave] = valor
        elif isinstance(valor, (list, tuple)):
            salida[clave] = f"[{len(valor)} elementos]"
        else:
            salida[clave] = f"<{type(valor).__name__}>"
    return salida
