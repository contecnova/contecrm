"""Motor de orquestación de procesos: duradero, reanudable y observable.

Es la pieza que hace que la segunda restricción transversal —«los procesos de
negocio son composiciones explícitas y observables de servicios»— sea verdad y
no un deseo. Sin un motor así, un proceso como *presupuesto → aprobación →
pedido → ERP → factura* acaba repartido entre cinco controladores, tres
automatizaciones y un trigger, y nadie puede responder a la pregunta que
importa: «este pedido, ¿por dónde va y por qué se ha parado?».

Lo que lo distingue de una cola de tareas:

  * **Duradero**: el estado de cada instancia vive en la base, no en memoria. Si
    el proceso muere a mitad, otro lo retoma donde estaba (CRM-00.03.02.01).
  * **Con compensación**: cada paso puede declarar cómo se deshace. Cuando el
    quinto paso falla, se deshacen los cuatro anteriores en orden inverso — que
    es la única forma de mantener coherencia entre servicios que no comparten
    transacción (CRM-00.03.02.05).
  * **Con tareas humanas**: una espera de días por una aprobación es un estado
    normal del proceso, no un error de tiempo agotado (CRM-00.03.02.09).
  * **Con límites**: pasos, profundidad y duración están acotados, porque un
    proceso que se llama a sí mismo consume el sistema entero
    (CRM-00.03.02.16).
"""
