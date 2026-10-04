"""Varias operaciones en una llamada (CRM-00.02.01.13).

Un cliente que crea una cuenta, le añade un contacto y le abre una oportunidad
hace tres llamadas y tres viajes de red. Desde un móvil con mala cobertura, eso
son tres ocasiones de quedarse a medias — y quedarse a medias aquí significa una
cuenta sin contacto que alguien tendrá que limpiar a mano.

**Todo o nada, en una transacción.** Es la diferencia entre esto y mandar tres
peticiones seguidas: si la tercera falla, las dos primeras se deshacen. Sin esa
garantía, agrupar solo ahorra latencia y añade una forma nueva de dejar datos a
medias.

**Las operaciones se refieren entre sí.** La segunda necesita el identificador
que generó la primera, y ese identificador no existe hasta que la primera corre.
Con `$1.id` se apunta al resultado de la operación anterior; sin eso, agrupar no
sirve para el caso que motiva agrupar.

Lo que **no** hace: no es un lenguaje. No hay condiciones ni bucles. Una
secuencia que necesita decidir no es una petición compuesta, es un proceso, y
para eso está el motor que sabe reanudar y compensar.
"""

from __future__ import annotations

import re
from typing import Any

from crmcore.errors import ErrorValidacion
from crmcore.logging import get_logger

logger = get_logger(__name__)


def _tope() -> int:
    """Tope de operaciones por petición, **de la configuración**.

    Veinte cubre cualquier alta compuesta real; más que eso es una carga masiva,
    y para eso está el camino masivo con su trabajo diferido y su informe
    parcial.

    Era un `20` escrito aquí mientras `COMPOSITE_MAX_OPS` existía en los
    ajustes, documentado y editable, **sin que lo leyera nadie** — y además con
    otro valor, 25, así que la pantalla de ajustes decía una cosa y la API
    aplicaba otra. Un integrador que mirara el ajuste y mandara 25 operaciones
    recibía un error que no cuadraba con lo que había leído.
    """
    from crmcore.config import get_settings

    return int(get_settings().composite_max_ops)


# `$3.id`, `$1.cuenta_id`… Referencia al resultado de otra operación.
REFERENCIA = re.compile(r"^\$(\d+)\.([A-Za-z_][A-Za-z0-9_]*)$")


def validar(operaciones: list[dict[str, Any]]) -> None:
    """Comprueba la petición ANTES de ejecutar nada.

    Antes, porque una referencia rota descubierta a mitad deja la transacción
    abortada y al cliente con un error que no dice cuál de sus operaciones
    estaba mal.
    """
    if not operaciones:
        raise ErrorValidacion(
            "Una petición compuesta sin operaciones no hace nada",
            error_code="compuesto.vacia",
        )
    tope = _tope()
    if len(operaciones) > tope:
        raise ErrorValidacion(
            f"Caben {tope} operaciones por petición; para más, el camino masivo",
            error_code="compuesto.demasiadas",
            detalle={"tope": tope, "enviadas": len(operaciones)},
        )

    for indice, operacion in enumerate(operaciones, start=1):
        if not operacion.get("metodo") or not operacion.get("ruta"):
            raise ErrorValidacion(
                f"La operación {indice} no dice método y ruta",
                error_code="compuesto.operacion_incompleta",
            )
        for referencia in _referencias(operacion.get("cuerpo") or {}):
            objetivo = int(referencia.group(1))
            if objetivo >= indice:
                # Hacia atrás y solo hacia atrás: una referencia a una operación
                # posterior no se puede resolver, y una a sí misma es un ciclo.
                # Dejarlo pasar daría un valor nulo silencioso, que es peor que
                # un error: la fila se crearía con el campo vacío.
                raise ErrorValidacion(
                    f"La operación {indice} se refiere a la {objetivo}, que aún no ha corrido",
                    error_code="compuesto.referencia_adelantada",
                )


def _referencias(valor: Any) -> list[re.Match[str]]:
    encontradas: list[re.Match[str]] = []
    if isinstance(valor, str):
        casa = REFERENCIA.match(valor)
        if casa:
            encontradas.append(casa)
    elif isinstance(valor, dict):
        for v in valor.values():
            encontradas.extend(_referencias(v))
    elif isinstance(valor, (list, tuple)):
        for v in valor:
            encontradas.extend(_referencias(v))
    return encontradas


def resolver(valor: Any, resultados: list[dict[str, Any]]) -> Any:
    """Sustituye `$n.campo` por lo que devolvió la operación n.

    Si el campo no está en el resultado se deja el texto tal cual y se registra.
    Poner `None` en su lugar crearía la fila con el campo vacío y nadie lo
    notaría hasta semanas después; dejarlo visible hace que falle la validación
    del recurso, que es donde tiene que fallar.
    """
    if isinstance(valor, str):
        casa = REFERENCIA.match(valor)
        if not casa:
            return valor
        indice, campo = int(casa.group(1)), casa.group(2)
        previo = resultados[indice - 1] if 0 < indice <= len(resultados) else {}
        if campo not in previo:
            logger.warning("compuesto.referencia_sin_campo", referencia=valor, campo=campo)
            return valor
        return previo[campo]
    if isinstance(valor, dict):
        return {k: resolver(v, resultados) for k, v in valor.items()}
    if isinstance(valor, list):
        return [resolver(v, resultados) for v in valor]
    return valor
