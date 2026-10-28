"""La gramática de filtros de una consulta, escrita UNA vez.

Había dos listas de operadores, en dos servicios, y no decían lo mismo:

  * `analytics/informes.OPERADORES` —la del que EJECUTA— admite
    `=, !=, >, >=, <, <=, contiene, empieza, en, vacio, no_vacio`;
  * `intelligence/rag.OPERADORES_PLAN` —la del que PROPONE, traduciendo una
    pregunta en lenguaje natural— admitía `entre` y no admitía `empieza`,
    `vacio` ni `no_vacio`.

Las dos consecuencias, medidas el 28-10-2026:

  * **«entre» se aceptaba y no lo ejecuta nadie.** Una pregunta como «clientes
    con facturación entre 10.000 y 50.000» producía un plan que la validación
    daba por bueno y que moría —o se quedaba sin filtro— al ejecutarlo. El
    usuario ve un número, y el número no es el que pidió;
  * **tres operadores que SÍ se ejecutan eran inexpresables en un plan**, así
    que el modelo no podía proponerlos aunque fueran justo lo que la pregunta
    pedía.

Es el mismo caso que la tabla de rutas del gateway: dos listas de acoplamiento
que tienen que coincidir, mantenidas por separado, dejan de coincidir — y el
síntoma aparece lejos de donde está la causa. Por eso vive aquí y no en uno de
los dos servicios: `intelligence` no puede importar de `analytics`, y copiarla
es exactamente lo que ya había.

**Lo que manda es lo que se puede ejecutar.** Proponer algo que nadie sabe
hacer no es una funcionalidad a medias: es una respuesta equivocada con buena
presentación.
"""

from __future__ import annotations

OPERADORES_DE_FILTRO: tuple[str, ...] = (
    "=",
    "!=",
    ">",
    ">=",
    "<",
    "<=",
    "contiene",
    "empieza",
    "en",
    "vacio",
    "no_vacio",
)
