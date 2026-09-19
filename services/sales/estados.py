"""Las máquinas de estado de `sales` (CRM-00.04.01.07).

Se declaran en el código porque el código las usa: hay comparaciones contra
estos estados en el enrutamiento, en el pipeline y en la previsión, así que la
lista de estados posibles **es** parte del programa. Un tenant puede quitar
transiciones —«aquí una oportunidad perdida no se reabre»—, pero no añadir
estados que ningún `if` de aquí sabría manejar.
"""

from __future__ import annotations

from crmcore.datos.estados import Maquina, registrar_maquina

# Un lead no vuelve de «convertido»: ya existe una cuenta y una oportunidad
# apuntando a él, y devolverlo al circuito crearía un duplicado del cliente que
# acaba de darse de alta.
#
# **Se puede convertir desde cualquier estado vivo**, incluido «nuevo». La
# primera versión de esta máquina exigía pasar por «cualificado», y las pruebas
# lo cazaron: un lead que llega de una feria con el pedido firmado se convierte
# en el momento. Obligar a marcarlo antes como contactado y cualificado no
# mejora el dato — produce dos clics de mentira y un histórico que dice que se
# hizo un seguimiento que no existió.
#
# La máquina codifica lo que es LEGÍTIMO, no el proceso ideal. Forzar el proceso
# ideal es la forma más rápida de que la gente lo falsee, y entonces el dato
# deja de servir para lo que se recogía.
LEAD = registrar_maquina(
    Maquina(
        objeto="lead",
        inicial="nuevo",
        transiciones={
            "nuevo": frozenset({"contactado", "cualificado", "convertido", "descartado"}),
            "contactado": frozenset({"cualificado", "convertido", "descartado"}),
            # De cualificado se convierte o se descarta; volver a «contactado»
            # borraría que ya se cualificó, que es el hito que mide el equipo.
            "cualificado": frozenset({"convertido", "descartado"}),
            # Un descarte no es un no para siempre: el reciclaje lo devuelve.
            "descartado": frozenset({"reciclado"}),
            "reciclado": frozenset({"contactado", "cualificado", "convertido", "descartado"}),
        },
        finales=frozenset({"convertido"}),
        exigen_motivo=frozenset({"descartado"}),
    )
)

# Una oportunidad cerrada se puede reabrir, y por eso «cerrada» no es terminal:
# pasa de verdad —el cliente vuelve, el pedido se recupera— y prohibirlo obliga
# a crear una oportunidad nueva que rompe el histórico. Lo que sí exige es
# motivo, porque sus números ya están en un informe que alguien miró.
OPORTUNIDAD = registrar_maquina(
    Maquina(
        objeto="oportunidad",
        inicial="abierta",
        transiciones={
            "abierta": frozenset({"ganada", "perdida", "cancelada"}),
            "ganada": frozenset({"abierta"}),
            "perdida": frozenset({"abierta"}),
            "cancelada": frozenset({"abierta"}),
        },
        exigen_motivo=frozenset({"perdida", "cancelada", "abierta"}),
    )
)
