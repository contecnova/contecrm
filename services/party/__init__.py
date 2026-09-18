"""Servicio `party`: cuentas, contactos, actividades y calidad del dato.

«Party» y no «clientes» a propósito. En un CRM empresarial la misma entidad es,
según el momento, cliente, prospecto, partner, proveedor o competidor — y
modelarla como «cliente» obliga a duplicarla en cuanto aparece el segundo papel.
Es el mismo error que lleva a tener la misma empresa tres veces con tres fichas
distintas.

Lo que vive aquí:

  * **Cuentas** (organizaciones) y **contactos** (personas), con relación N:M
    entre ellos: una persona puede serlo de varias empresas, y con papeles
    distintos en cada una.
  * **Jerarquías múltiples y simultáneas**: la estructura legal de un grupo no
    es la comercial, ni la de facturación, ni la de entrega. Modelarlas como una
    sola obliga a elegir cuál se pierde.
  * **Actividades**: tareas, llamadas, reuniones, notas y visitas, con relación
    polimórfica a cualquier objeto del CRM.
  * **Calidad del dato**: normalización, detección de duplicados y fusión con
    reparentado de relaciones.
  * **Consentimientos** por finalidad y canal, con su base legal.

Lo que **no** vive aquí: leads y oportunidades, que son de `sales`. La frontera
está en que un lead todavía no es una cuenta —es una pista sin cualificar— y
tratarlo como tal ensucia el maestro de clientes con basura de captación.
"""
