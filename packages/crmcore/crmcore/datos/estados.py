"""Máquinas de estado: qué transiciones son legales (CRM-00.04.01.07).

Un campo `estado` sin máquina es una cadena de texto con nombres bonitos.
Funciona mientras todo el mundo use la interfaz; el día que alguien escribe por
API —una integración, una importación, un script de migración— aparecen
oportunidades «ganadas» que nunca pasaron por negociación, y los informes de
conversión dejan de significar nada sin que nada haya fallado.

**La máquina se declara en el código del servicio dueño del objeto.** No en la
base, y el motivo es concreto: el código tiene un `if estado == "ganada"` en
quince sitios, así que la lista de estados posibles **es** parte del código. Si
un tenant pudiera inventarse un estado, la mitad de esas comparaciones dejarían
de acertar y el registro se quedaría en un limbo que nadie programó.

**Lo que un tenant sí puede es restringir.** Quitar una transición que el código
admite es seguro —el código sabe manejar los dos estados, simplemente no se va a
llegar de uno al otro— y es lo que de verdad piden: «aquí una oportunidad
perdida no se reabre». Añadir, no. Esa asimetría es la que hace configurable la
máquina sin hacerla frágil.

Los objetos **propios del tenant** son el caso distinto: no tienen código detrás,
así que ahí la declaración de metadatos **es** la máquina entera y sí define los
estados. Lo maneja `services.metadata`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from crmcore.errors import Conflicto, ErrorValidacion
from crmcore.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Maquina:
    """Las transiciones legales de un objeto."""

    objeto: str
    # `{estado: {estados a los que se puede ir}}`.
    transiciones: dict[str, frozenset[str]]
    inicial: str
    # Estados de los que no se sale. Se declaran **explícitamente** y no se
    # deducen de «no aparece como clave»: deducirlos hacía la validación
    # circular —cualquier destino pasaba a ser un estado válido por el hecho de
    # ser destino—, así que una errata en un nombre creaba un estado nuevo en
    # vez de fallar. Declararlos, además, obliga a pensar cuáles lo son.
    finales: frozenset[str] = field(default_factory=frozenset)
    # Transiciones que exigen motivo escrito. No es burocracia: son las que
    # alguien va a preguntar meses después —por qué se perdió, por qué se
    # suspendió— y la respuesta se pierde con quien la tomó.
    exigen_motivo: frozenset[str] = field(default_factory=frozenset)

    @property
    def estados(self) -> frozenset[str]:
        """Todos los estados declarados: los que tienen salida y los finales."""
        return frozenset(set(self.transiciones) | set(self.finales) | {self.inicial})

    def terminales(self) -> frozenset[str]:
        return frozenset(self.finales)


MAQUINAS: dict[str, Maquina] = {}


def registrar_maquina(maquina: Maquina) -> Maquina:
    """Declara la máquina de un objeto. Lo hace el servicio que lo posee.

    Se valida al declararla: una máquina con un estado inicial que no aparece en
    ninguna transición, o con un destino que no es estado, es un error que hay
    que ver al arrancar y no cuando alguien intente moverse.
    """
    for origen, destinos in maquina.transiciones.items():
        desconocidos = [d for d in destinos if d not in maquina.estados]
        if desconocidos:
            raise ValueError(
                f"La máquina de «{maquina.objeto}» lleva de «{origen}» a estados "
                f"que no declara: {desconocidos}"
            )
    if maquina.inicial not in maquina.estados:
        raise ValueError(
            f"El estado inicial «{maquina.inicial}» no está entre los de «{maquina.objeto}»"
        )
    MAQUINAS[maquina.objeto] = maquina
    return maquina


def _restricciones(db: Session | None, objeto: str) -> dict[str, set[str]]:
    """Transiciones que este tenant ha quitado.

    Formato: `{"perdida": ["abierta"]}` significa «de perdida ya no se puede ir
    a abierta». Solo quita; lo que no aparezca sigue como lo declara el código.
    """
    from crmcore.runtime import settings as rt

    crudo = rt.efectivo("transiciones_prohibidas", db) or {}
    if not isinstance(crudo, dict):
        return {}
    del_objeto = crudo.get(objeto) or {}
    if not isinstance(del_objeto, dict):
        return {}
    return {str(k): {str(v) for v in (vs or [])} for k, vs in del_objeto.items()}


def transiciones_de(objeto: str, estado: str, db: Session | None = None) -> frozenset[str]:
    """A dónde se puede ir desde aquí, ya con las restricciones del tenant."""
    maquina = MAQUINAS.get(objeto)
    if maquina is None:
        return frozenset()
    permitidas = set(maquina.transiciones.get(estado, frozenset()))
    return frozenset(permitidas - _restricciones(db, objeto).get(estado, set()))


def comprobar(
    objeto: str,
    *,
    desde: str,
    hasta: str,
    motivo: str = "",
    db: Session | None = None,
) -> None:
    """Valida una transición. Lanza si no es legal.

    Un objeto sin máquina declarada **no se bloquea**: hay objetos cuyo estado
    es una etiqueta libre, y exigirles una máquina obligaría a inventar una para
    callar a esta función. Lo que impide que eso se convierta en el agujero es el
    gate, que exige declararla o eximir el objeto con su motivo.
    """
    maquina = MAQUINAS.get(objeto)
    if maquina is None:
        return
    if desde == hasta:
        return

    if hasta not in maquina.estados:
        # Se distingue de «no puedes ir ahí»: un estado que no existe casi
        # siempre es una errata o una integración desactualizada, y decir
        # «desconocido» ahorra media hora de buscar un permiso que no falta.
        raise ErrorValidacion(
            f"«{hasta}» no es un estado de {objeto}",
            error_code="estados.estado_desconocido",
            detalle={"estados": sorted(maquina.estados)},
        )

    permitidas = transiciones_de(objeto, desde, db)
    if hasta not in permitidas:
        declaradas = maquina.transiciones.get(desde, frozenset())
        restringida = hasta in declaradas
        raise Conflicto(
            f"No se puede pasar de «{desde}» a «{hasta}»"
            + (" en esta configuración" if restringida else ""),
            error_code="estados.transicion_no_permitida",
            detalle={
                "desde": desde,
                "permitidas": sorted(permitidas),
                # Se dice si la transición existe pero está desactivada por
                # configuración: sin eso, quien administra el tenant no sabe si
                # tiene que cambiar un ajuste o pedir un cambio de producto.
                "restringida_por_configuracion": restringida,
            },
        )

    if hasta in maquina.exigen_motivo and not (motivo or "").strip():
        raise ErrorValidacion(
            f"Pasar a «{hasta}» exige un motivo escrito",
            error_code="estados.motivo_requerido",
        )


def aplicar(
    db: Session,
    fila: Any,
    *,
    objeto: str,
    nuevo: str,
    motivo: str = "",
    por: UUID | None = None,
    campo: str = "estado",
) -> str:
    """Comprueba la transición, la aplica y la audita. Devuelve el estado anterior.

    Auditar aquí y no en cada sitio es lo que hace que el histórico de estados
    esté completo: una transición sin apunte es un cambio que nadie puede
    explicar, y son justo los que se preguntan.
    """
    from crmcore.audit.chain import registrar

    anterior = getattr(fila, campo)
    comprobar(objeto, desde=anterior, hasta=nuevo, motivo=motivo, db=db)
    if anterior == nuevo:
        return anterior

    setattr(fila, campo, nuevo)
    registrar(
        db,
        accion=f"{objeto}.estado_cambiado",
        objeto=objeto,
        objeto_id=getattr(fila, "id", None),
        datos={"desde": anterior, "hasta": nuevo},
        motivo=motivo or None,
        tenant_id=getattr(fila, "tenant_id", None),
    )
    logger.info("estados.transicion", objeto=objeto, desde=anterior, hasta=nuevo)
    return anterior
