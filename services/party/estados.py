"""La máquina de estados de la actividad (CRM-00.04.01.07).

Configuración de fábrica: la empresa la cambia desde Administrar › Plataforma ›
Estados de los objetos —nombres, orden, colores, estados propios y a cuáles se
puede pasar— y el código pregunta por el **significado**: «pendiente» y «en
curso» son las vivas, «completada» y «cancelada» las cerradas, se llamen como
se llamen. Un estado propio como «Esperando respuesta» que signifique
«en_curso» sigue saliendo en las vencidas y en las abiertas de la cuenta.
"""

from __future__ import annotations

from crmcore.datos.estados import Maquina, con_significado, registrar_maquina
from sqlalchemy.orm import Session

ACTIVIDAD = registrar_maquina(
    Maquina(
        objeto="actividad",
        inicial="pendiente",
        # Lo que hoy permite el producto: se empieza, se termina o se cancela,
        # y lo terminado o cancelado se puede retomar —una llamada «hecha» que
        # hay que repetir no es una actividad nueva—.
        transiciones={
            "pendiente": frozenset({"en_curso", "completada", "cancelada"}),
            "en_curso": frozenset({"pendiente", "completada", "cancelada"}),
            "completada": frozenset({"en_curso"}),
            "cancelada": frozenset({"pendiente"}),
        },
        # Cancelar es lo que alguien pregunta después.
        exigen_motivo=frozenset({"cancelada"}),
        obligatorios=frozenset({"pendiente", "completada", "cancelada"}),
    )
)


def vivas(db: Session | None) -> frozenset[str]:
    """Los estados de una actividad que todavía hay que hacer."""
    return con_significado("actividad", "pendiente", db) | con_significado(
        "actividad", "en_curso", db
    )


def cerradas(db: Session | None) -> frozenset[str]:
    """Los estados de una actividad que ya no se hace: hecha o cancelada."""
    return con_significado("actividad", "completada", db) | con_significado(
        "actividad", "cancelada", db
    )
