"""Lo que el servidor tiene que dar a una aplicación móvil y a un modo sin
conexión (CRM-06.02.01.03, CRM-06.02.01.04).

Las aplicaciones móviles de CRM fallan casi siempre por lo mismo, y no es la
interfaz: es que **el servidor no está pensado para un cliente que se desconecta**.
Un comercial en una nave sin cobertura anota tres visitas, y cuando vuelve la
señal el CRM tiene que decidir qué hacer con lo que él escribió hace dos horas y
con lo que otra persona cambió mientras tanto.

Lo que aquí se resuelve es la parte del servidor. La aplicación es otra cosa —se
construye con el SDK y las vistas servidas—, pero sin esto, cualquier aplicación
que se escriba encima va a perder datos.

Las decisiones:

**Nada se sincroniza sin identificador del cliente.** El móvil genera el
identificador antes de mandar nada, y por eso un reintento después de un timeout
no crea una visita duplicada. Dejar que lo genere el servidor obliga a adivinar si
la petición que no contestó llegó o no, y la respuesta correcta a esa duda no
existe.

**El conflicto se detecta, no se evita.** Dos personas van a tocar el mismo
registro: lo que no puede pasar es que gane el último en llegar sin que nadie se
entere, porque el otro cambio desaparece y no queda rastro.

**Y cuando se detecta, se guardan las dos versiones.** Descartar una para «no
molestar al usuario» es descartar trabajo de alguien. Que lo decida una persona
cuesta un minuto; reconstruir lo perdido cuesta una mañana y a veces no se puede.

**Lo que no se puede resolver se queda en la cola, no se pierde.** Una cola que
descarta lo que falla convierte un problema de sincronización en una pérdida
silenciosa de datos.

**Y la notificación push no lleva el dato dentro.** Llega a una pantalla bloqueada
que puede ver cualquiera que coja el teléfono: lleva qué ha pasado y dónde
mirarlo, no el nombre del cliente ni el importe.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.errors import Conflicto, ErrorValidacion
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Cómo se resuelve un choque. Lista cerrada porque cada una pierde algo distinto,
# y la que se elige por defecto decide qué trabajo se tira.
ESTRATEGIAS = (
    "manual",  # lo decide una persona: lo normal cuando hay dos ediciones reales
    "gana_servidor",  # para catálogos y configuración: el móvil no manda ahí
    "gana_cliente",  # para lo que solo existe en el móvil: una firma, una foto
    "fusionar_campos",  # cuando tocaron campos distintos y no se pisan
)

# Cuánto aguanta un cambio en la cola antes de que haya que mirarlo. No se
# descarta nunca: se avisa. Una cola que tira lo viejo convierte un problema de
# sincronización en una pérdida silenciosa.
DIAS_AVISO_COLA = 7


def preparar_envio(
    *,
    operaciones: list[dict[str, Any]],
) -> dict[str, Any]:
    """Valida lo que el móvil va a mandar antes de mandarlo.

    **Cada operación necesita su identificador de cliente.** Es lo que hace que
    un reintento tras un timeout no cree una visita duplicada: sin él, el móvil
    tiene que adivinar si la petición que no contestó llegó o no, y esa duda no
    tiene respuesta correcta.
    """
    sin_id = [i for i, op in enumerate(operaciones) if not op.get("id_cliente")]
    if sin_id:
        raise ErrorValidacion(
            f"{len(sin_id)} operaciones sin identificador de cliente. Sin él, un "
            "reintento tras un corte crea duplicados y nadie sabe cuál es el bueno.",
            error_code="movil.operacion_sin_id",
            detalle={"posiciones": sin_id[:10]},
        )
    # `is None` y no `not`: la versión **cero es una versión**, la del registro
    # que nadie ha tocado todavía. Con la comprobación por falsedad, toda
    # actualización sobre un registro recién creado se rechazaba diciendo que no
    # declaraba su versión base — y la declaraba. Se vio al enchufar la ruta,
    # que es para lo que sirve enchufarla.
    sin_base = [
        op.get("id_cliente")
        for op in operaciones
        if op.get("tipo") == "actualizar" and op.get("version_base") is None
    ]
    if sin_base:
        raise ErrorValidacion(
            "Hay actualizaciones sin decir sobre qué versión se hicieron. Sin eso no "
            "se puede detectar un conflicto: se aplicaría encima de lo que haya y el "
            "cambio de otra persona desaparecería sin rastro.",
            error_code="movil.actualizacion_sin_version",
            detalle={"operaciones": [str(x) for x in sin_base[:10]]},
        )
    return {
        "operaciones": len(operaciones),
        "listo": True,
        "porque": (
            "Cada operación lleva su identificador de cliente y su versión base: con "
            "eso, un reintento es idempotente y un conflicto se ve."
        ),
    }


def detectar_conflicto(
    *,
    version_base: int,
    version_servidor: int,
    campos_cliente: dict[str, Any],
    campos_servidor: dict[str, Any],
) -> dict[str, Any]:
    """Si lo que llega del móvil choca con lo que hay, y en qué.

    **Se detecta y no se evita.** Dos personas van a tocar el mismo registro; lo
    que no puede pasar es que gane el último en llegar sin que nadie se entere,
    porque entonces el otro cambio desaparece y no queda rastro de que existió.

    Y se distingue el choque de verdad —los dos tocaron **el mismo campo**— del
    que no lo es. Tratar como conflicto que uno cambiara el teléfono y otro la
    dirección hace que la gente aprenda a pulsar «quedarme con lo mío», que es
    como se pierde el trabajo del otro de todas formas.
    """
    if version_base == version_servidor:
        return {"hay_conflicto": False, "porque": "Nadie ha tocado el registro mientras tanto."}

    tocados_por_los_dos = sorted(
        campo
        for campo, valor in campos_cliente.items()
        if campo in campos_servidor and campos_servidor[campo] != valor
    )
    if not tocados_por_los_dos:
        return {
            "hay_conflicto": False,
            "fusionable": True,
            "porque": (
                "El registro cambió, pero en otros campos: se pueden aplicar los dos. "
                "Tratar esto como conflicto enseña a la gente a pulsar «quedarme con "
                "lo mío», que es como se pierde el trabajo del otro igualmente."
            ),
        }
    return {
        "hay_conflicto": True,
        "campos": tocados_por_los_dos,
        "version_base": version_base,
        "version_servidor": version_servidor,
        "porque": (
            f"Los dos han tocado {', '.join(tocados_por_los_dos)} desde la versión "
            f"{version_base}."
        ),
    }


def resolver(
    *,
    estrategia: str,
    campos_cliente: dict[str, Any],
    campos_servidor: dict[str, Any],
    campos_en_conflicto: list[str],
) -> dict[str, Any]:
    """Aplica la estrategia de resolución, guardando **las dos versiones**.

    Descartar una para «no molestar al usuario» es descartar trabajo de alguien.
    Que lo decida una persona cuesta un minuto; reconstruir lo que se perdió
    cuesta una mañana, y a veces no se puede porque nadie recuerda qué había.
    """
    if estrategia not in ESTRATEGIAS:
        raise ErrorValidacion(
            f"Estrategia desconocida: «{estrategia}»",
            error_code="movil.estrategia_invalida",
            detalle={"admitidas": list(ESTRATEGIAS)},
        )
    if estrategia == "manual":
        return {
            "resuelto": False,
            "espera_a_una_persona": True,
            # Las dos versiones, enteras. Es lo que permite decidir sin tener que
            # acordarse de qué había.
            "version_del_movil": dict(campos_cliente),
            "version_del_servidor": {c: campos_servidor.get(c) for c in campos_en_conflicto},
            "porque": (
                "Hay dos ediciones reales del mismo campo. Elegir una automáticamente "
                "tira el trabajo de alguien sin que se entere."
            ),
        }
    if estrategia == "fusionar_campos":
        if campos_en_conflicto:
            raise Conflicto(
                "No se pueden fusionar campos que los dos han tocado: fusionar aquí "
                "sería elegir uno y llamarlo fusión.",
                error_code="movil.fusion_imposible",
                detalle={"campos": campos_en_conflicto},
            )
        return {
            "resuelto": True,
            "resultado": {**campos_servidor, **campos_cliente},
            "porque": "Tocaron campos distintos: caben los dos.",
        }

    gana_el_movil = estrategia == "gana_cliente"
    return {
        "resuelto": True,
        "resultado": dict(campos_cliente) if gana_el_movil else dict(campos_servidor),
        # Lo que se descarta se devuelve igual: descartarlo en silencio es lo que
        # hace que nadie pueda reconstruirlo después.
        "descartado": (
            {c: campos_servidor.get(c) for c in campos_en_conflicto}
            if gana_el_movil
            else {c: campos_cliente.get(c) for c in campos_en_conflicto}
        ),
        "porque": (
            "El móvil manda en esto: es dato que solo existe ahí —una firma, una foto, "
            "una visita— y el servidor no tiene con qué contradecirlo."
            if gana_el_movil
            else "El servidor manda en esto: es catálogo o configuración, y el móvil "
            "trabaja con una copia que puede llevar días sin refrescarse."
        ),
    }


def estado_de_la_cola(
    *, pendientes: list[dict[str, Any]], ahora: datetime | None = None
) -> dict[str, Any]:
    """Qué hay sin sincronizar y desde cuándo.

    **Nada se descarta.** Una cola que tira lo que falla convierte un problema de
    sincronización en una pérdida silenciosa de datos: el comercial cree que
    anotó la visita y no está, y lo descubre el día que alguien pregunta por ese
    cliente.

    Lo viejo **se avisa**, que es distinto: alguien tiene que mirar por qué lleva
    una semana sin subir.
    """
    momento = ahora or datetime.now(timezone.utc)
    viejos: list[dict[str, Any]] = []
    en_conflicto = [p for p in pendientes if p.get("en_conflicto")]

    for pendiente in pendientes:
        creado = pendiente.get("creado_at")
        if not isinstance(creado, datetime):
            continue
        dias = (momento - (creado if creado.tzinfo else creado.replace(tzinfo=timezone.utc))).days
        if dias >= DIAS_AVISO_COLA:
            viejos.append({"id_cliente": pendiente.get("id_cliente"), "dias": dias})

    return {
        "pendientes": len(pendientes),
        "en_conflicto": len(en_conflicto),
        "esperando_demasiado": viejos,
        "se_descarta_algo": False,
        "que_significa": (
            "No hay nada pendiente."
            if not pendientes
            else f"{len(pendientes)} cambios sin subir. Ninguno se descarta: lo que "
            "falla se queda, porque tirarlo convierte un problema de red en una "
            "pérdida de datos que el usuario descubre semanas después."
        ),
        "aviso": (
            ""
            if not viejos
            else f"{len(viejos)} cambios llevan más de {DIAS_AVISO_COLA} días en la "
            "cola. Alguien tiene que mirar por qué no suben: el usuario cree que ya "
            "están guardados."
        ),
    }


def preparar_push(
    *,
    tipo: str,
    objeto: str,
    objeto_id: UUID,
    titulo_corto: str,
) -> dict[str, Any]:
    """Compone una notificación push **sin el dato dentro**.

    Llega a una pantalla bloqueada que puede ver cualquiera que coja el teléfono,
    y se queda en los servidores de push por el camino. Lleva **qué ha pasado y
    dónde mirarlo**, no el nombre del cliente ni el importe: para eso está la
    aplicación, que pide identidad antes de enseñar nada.
    """
    if len(titulo_corto) > 60:
        raise ErrorValidacion(
            "El título de un push se corta en la pantalla: más de 60 caracteres "
            "llegan truncados a media palabra.",
            error_code="movil.push_largo",
        )
    return {
        "titulo": titulo_corto,
        "tipo": tipo,
        # Solo la referencia. La aplicación la resuelve pidiendo identidad, que es
        # lo que hace que el dato no viaje hasta una pantalla bloqueada.
        "referencia": {"objeto": objeto, "objeto_id": str(objeto_id)},
        "sin_datos_dentro": True,
        "porque": (
            "Un push llega a una pantalla bloqueada y pasa por servidores de "
            "terceros. Lo que lleva es dónde mirar; el dato lo enseña la aplicación "
            "después de identificar a quien la abre."
        ),
    }
