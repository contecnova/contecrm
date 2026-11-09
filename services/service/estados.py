"""La máquina de estados del caso (CRM-00.04.01.07).

Es la configuración de fábrica: la empresa la cambia desde Administrar ›
Plataforma › Estados de los objetos —nombres, orden, colores, estados propios
y a cuáles se puede pasar— y el código pregunta por el **significado** de cada
estado, no por su nombre.

El caso que lo pedía estaba escrito en el propio código: qué estados paran el
reloj del SLA «cambia por cliente: hay contratos donde "esperando repuesto"
para el reloj y otros donde no». Con esto, «Esperando repuesto» es un estado
propio que significa «en pausa», y el reloj se para solo.
"""

from __future__ import annotations

from crmcore.datos.estados import Maquina, con_significado, registrar_maquina
from sqlalchemy.orm import Session

# El reloj de resolución no corre en los estados que significan esto.
EN_PAUSA = "en_pausa"

_VIVOS = ("nuevo", "asignado", "en_curso", "esperando_cliente")

CASO = registrar_maquina(
    Maquina(
        objeto="caso",
        inicial="nuevo",
        # Lo que hoy hace el producto, sin endurecerlo: entre los vivos se
        # puede ir y volver —un caso asignado que vuelve a la cola es normal—,
        # de cualquiera se resuelve o se cierra, y de resuelto o cerrado se
        # vuelve a trabajar. Reabrir con su ventana y su contador sigue siendo
        # la acción «Reabrir»; aquí sólo se dice qué movimientos son legales.
        transiciones={
            **{
                e: frozenset(
                    {*(v for v in _VIVOS if v != e and v != "nuevo"), "resuelto", "cerrado"}
                )
                for e in _VIVOS
            },
            "resuelto": frozenset({"en_curso", "cerrado"}),
            "cerrado": frozenset({"en_curso"}),
        },
        # Cerrar o volver a trabajar algo cerrado es lo que se pregunta después.
        exigen_motivo=frozenset({"cerrado"}),
        significados={"esperando_cliente": EN_PAUSA},
        # Sin «nuevo» no entra nada, y sin «resuelto» y «cerrado» no hay SLA de
        # resolución ni informe de cierres.
        obligatorios=frozenset({"nuevo", "resuelto", "cerrado"}),
    )
)


def terminales(db: Session | None) -> frozenset[str]:
    """Los estados en los que el caso ya no se trabaja: resueltos y cerrados."""
    return con_significado("caso", "resuelto", db) | con_significado("caso", "cerrado", db)
