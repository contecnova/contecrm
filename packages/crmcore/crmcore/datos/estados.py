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

**Y desde el 09-11-2026, la empresa la configura entera** (pedido: «todo
superconfigurable por administradores»). Lo que lo hace seguro es el
**significado**: cada estado dice qué es —abierto, ganado, perdido…— y el
código pregunta por el significado, no por el nombre. Así una empresa puede
llamar «Adjudicada» a la ganada, añadir «En pausa» como otro estado abierto u
ordenar y colorear los suyos, y la previsión y las comisiones siguen sabiendo
qué cuenta como ganado. Los estados de fábrica no se borran —el histórico los
usa—: se renombran o se desactivan.

Las restricciones de antes (`transiciones_prohibidas`) siguen aplicando encima.

Los objetos **propios del tenant** son el caso distinto: no tienen código detrás,
así que ahí la declaración de metadatos **es** la máquina entera y sí define los
estados. Lo maneja `services.metadata`.
"""

from __future__ import annotations

import re
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
    # Qué ES cada estado, para que el código pregunte por eso y no por el
    # nombre: `{"ganada": "ganado"}`. Un estado sin significado declarado
    # significa lo mismo que su clave.
    significados: dict[str, str] = field(default_factory=dict)
    # Los significados que la configuración de una empresa no puede quitar: sin
    # un «ganado» no hay previsión ni comisión.
    obligatorios: frozenset[str] = field(default_factory=frozenset)
    # Si la empresa la puede configurar. La del propio tenant es de la
    # plataforma y no lo es.
    configurable: bool = True
    # Lo que pone la configuración: nombre, color y orden de cada estado, y los
    # que se han desactivado. Las de fábrica lo traen vacío.
    presentacion: dict[str, dict[str, Any]] = field(default_factory=dict)
    inactivos: frozenset[str] = field(default_factory=frozenset)

    def significado(self, estado: str) -> str:
        return self.significados.get(estado, estado)

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


_CLAVE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")


def maquina_efectiva(objeto: str, db: Session | None = None) -> Maquina | None:
    """La máquina de este objeto tal como la tiene configurada la empresa.

    Sin configuración, la de fábrica. Una configuración que ya no valida —el
    producto cambió por debajo— no tumba nada: se avisa y se usa la de fábrica,
    que es la que el código sabe manejar.
    """
    fabrica = MAQUINAS.get(objeto)
    if fabrica is None or not fabrica.configurable or db is None:
        return fabrica
    from crmcore.runtime import settings as rt

    crudo = rt.efectivo("maquinas_de_estado", db) or {}
    conf = crudo.get(objeto) if isinstance(crudo, dict) else None
    if not conf:
        return fabrica
    try:
        return construir(fabrica, conf)
    except ErrorValidacion as exc:
        logger.warning("estados.configuracion_invalida", objeto=objeto, motivo=str(exc))
        return fabrica


def construir(fabrica: Maquina, conf: dict[str, Any]) -> Maquina:
    """La máquina que sale de una configuración, validada contra la de fábrica.

    Lo que se exige y por qué:

    - los estados de fábrica siguen ahí —se pueden renombrar o desactivar, no
      borrar—, porque hay registros y un histórico que los usan;
    - un estado nuevo dice qué significa, y significa algo que el producto ya
      sabe tratar;
    - siguen existiendo los significados obligatorios —sin un «ganado» no hay
      previsión—;
    - las transiciones sólo nombran estados que existen.
    """
    estados = conf.get("estados") or []
    if not isinstance(estados, list) or not estados:
        raise ErrorValidacion("La configuración no trae estados", error_code="estados.sin_estados")
    vistos: dict[str, dict[str, Any]] = {}
    for e in estados:
        clave = str((e or {}).get("clave") or "")
        if not _CLAVE.match(clave):
            raise ErrorValidacion(
                f"«{clave}» no vale como clave de estado: minúsculas, números y _",
                error_code="estados.clave_invalida",
            )
        if clave in vistos:
            raise ErrorValidacion(
                f"El estado «{clave}» está dos veces", error_code="estados.repetido"
            )
        vistos[clave] = e
    faltan = sorted(fabrica.estados - set(vistos))
    if faltan:
        raise ErrorValidacion(
            f"Los estados de fábrica no se borran, se desactivan: faltan {', '.join(faltan)}",
            error_code="estados.falta_de_fabrica",
            detalle={"faltan": faltan},
        )
    conocidos = {fabrica.significado(e) for e in fabrica.estados}
    significados: dict[str, str] = {}
    for clave, e in vistos.items():
        sig = str(e.get("significado") or fabrica.significado(clave))
        if clave in fabrica.estados and sig != fabrica.significado(clave):
            raise ErrorValidacion(
                f"«{clave}» es de fábrica y significa «{fabrica.significado(clave)}»: "
                "se le puede cambiar el nombre, no lo que es",
                error_code="estados.significado_de_fabrica",
            )
        if sig not in conocidos:
            raise ErrorValidacion(
                f"«{sig}» no es un significado que el producto sepa tratar",
                error_code="estados.significado_desconocido",
                detalle={"validos": sorted(conocidos)},
            )
        significados[clave] = sig
    inactivos = frozenset(c for c, e in vistos.items() if e.get("activo") is False)
    vivos = {significados[c] for c in vistos if c not in inactivos}
    sin = sorted(fabrica.obligatorios - vivos)
    if sin:
        raise ErrorValidacion(
            f"Tiene que quedar al menos un estado activo que signifique {', '.join(sin)}",
            error_code="estados.falta_significado",
        )
    inicial = str(conf.get("inicial") or fabrica.inicial)
    if inicial not in vistos or inicial in inactivos:
        raise ErrorValidacion(
            f"El estado inicial «{inicial}» no está entre los activos",
            error_code="estados.inicial_invalido",
        )
    transiciones: dict[str, frozenset[str]] = {}
    for origen, destinos in (conf.get("transiciones") or {}).items():
        malos = [d for d in [origen, *(destinos or [])] if d not in vistos]
        if malos:
            raise ErrorValidacion(
                f"Las transiciones nombran estados que no existen: {', '.join(malos)}",
                error_code="estados.transicion_desconocida",
            )
        transiciones[str(origen)] = frozenset(str(d) for d in destinos or [] if d not in inactivos)
    finales = frozenset(c for c, e in vistos.items() if e.get("final"))
    presentacion = {
        c: {
            "nombre": str(e.get("nombre") or ""),
            "color": str(e.get("color") or ""),
            "orden": int(e.get("orden") or 0),
        }
        for c, e in vistos.items()
    }
    return Maquina(
        objeto=fabrica.objeto,
        transiciones=transiciones,
        inicial=inicial,
        finales=finales,
        exigen_motivo=frozenset(str(x) for x in conf.get("exigen_motivo") or [] if x in vistos),
        significados=significados,
        obligatorios=fabrica.obligatorios,
        configurable=True,
        presentacion=presentacion,
        inactivos=inactivos,
    )


def a_configuracion(maquina: Maquina, *, de_fabrica: bool) -> dict[str, Any]:
    """La máquina como la edita la pantalla: una lista de estados ordenada."""
    estados = sorted(
        maquina.estados,
        key=lambda e: (maquina.presentacion.get(e, {}).get("orden", 0), e),
    )
    return {
        "objeto": maquina.objeto,
        "de_fabrica": de_fabrica,
        "inicial": maquina.inicial,
        "estados": [
            {
                "clave": e,
                "nombre": maquina.presentacion.get(e, {}).get("nombre", ""),
                "color": maquina.presentacion.get(e, {}).get("color", ""),
                "orden": maquina.presentacion.get(e, {}).get("orden", i),
                "significado": maquina.significado(e),
                "final": e in maquina.finales,
                "activo": e not in maquina.inactivos,
            }
            for i, e in enumerate(estados)
        ],
        "transiciones": {o: sorted(d) for o, d in maquina.transiciones.items()},
        "exigen_motivo": sorted(maquina.exigen_motivo),
        "significados_obligatorios": sorted(maquina.obligatorios),
    }


def con_significado(objeto: str, significado: str, db: Session | None = None) -> frozenset[str]:
    """Los estados de este objeto que significan esto, con la configuración de la empresa.

    Es lo que el código usa en vez de comparar con un nombre: «las abiertas»
    son todas las que significan «abierto», se llamen como se llamen.
    """
    maquina = maquina_efectiva(objeto, db)
    if maquina is None:
        return frozenset({significado})
    return frozenset(e for e in maquina.estados if maquina.significado(e) == significado)


def significa(objeto: str, estado: str | None, significado: str, db: Session | None = None) -> bool:
    return bool(estado) and estado in con_significado(objeto, significado, db)


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
    maquina = maquina_efectiva(objeto, db)
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
    maquina = maquina_efectiva(objeto, db)
    if maquina is None:
        return
    if desde == hasta:
        return
    if hasta in maquina.inactivos:
        raise ErrorValidacion(
            f"«{hasta}» está desactivado en esta configuración",
            error_code="estados.estado_inactivo",
        )

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
    # Y el rastro completo, si este objeto lo tiene encendido. Va AQUÍ por lo
    # mismo que la auditoría: un hecho anotado en cada sitio donde se cambia un
    # estado es un hecho que falta en el sitio que se olvidó, y la
    # reconstrucción de un agregado al que le falta un hecho no es una prueba
    # de nada — es peor que no tenerla, porque parece una.
    #
    # `anotar` existía, `declarar_agregado` existía, y no los llamaba nadie: la
    # tabla de hechos se creaba en dos servicios y estaba siempre vacía.
    from crmcore.datos.event_sourcing import agregados_declarados, anotar

    if objeto in agregados_declarados():
        anotar(
            db,
            tenant_id=getattr(fila, "tenant_id", None),
            objeto=objeto,
            objeto_id=getattr(fila, "id", None),
            tipo=f"{objeto}.estado_cambiado",
            # Solo el campo del agregado. `reconstruir` FUSIONA `datos` sobre el
            # estado, así que meter aquí el estado anterior o el motivo los
            # convertiría en campos del agregado: la reconstrucción tendría un
            # «estado_anterior» que la tabla viva no tiene, y la comparación con
            # lo vivo saldría en rojo siempre — la señal que importa, ahogada en
            # una diferencia que no significa nada.
            #
            # El porqué no se pierde: va en el apunte de auditoría de aquí
            # arriba, que es donde se pregunta.
            datos={campo: nuevo},
            por=por,
        )

    logger.info("estados.transicion", objeto=objeto, desde=anterior, hasta=nuevo)
    return anterior
