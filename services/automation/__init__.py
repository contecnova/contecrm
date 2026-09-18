"""Automatización declarativa: «cuando ocurre X, si Y, entonces Z».

Es la herramienta de quien configura el CRM, no la de quien lo programa. La
diferencia con el motor de procesos importa y se pregunta siempre:

  * Una **automatización** es un disparo corto y sin estado: al crear un lead,
    asígnalo al comercial del territorio y avisa por correo. Empieza y acaba.
  * Un **proceso** tiene estado, dura días, espera a personas y sabe deshacerse.

Confundirlos sale caro en los dos sentidos: montar un ciclo de aprobación con
automatizaciones encadenadas deja un flujo que nadie puede seguir ni reanudar;
y modelar «avisa al crear» como un proceso llena la base de instancias para algo
que son dos líneas.

Por eso una automatización puede **lanzar** un proceso, y ese es el puente.
"""
