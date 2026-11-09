"""Qué hace falta para que una automatización pueda correr, comprobado al guardarla.

Lo que se comprueba aquí es lo que el motor necesita para ejecutarla, no una
opinión sobre si la regla es buena: que cada acción exista y lleve lo que su
ejecutor exige, que las condiciones usen un operador del motor, que una
programada tenga un horario que se cumpla y que un disparador «evento» apunte a
un evento que alguien publica.

**Al guardar y no al ejecutar**, por lo de siempre: una regla mal escrita que se
guarda bien falla la primera vez que se dispara, semanas después y delante de
quien no la escribió. La usan el alta, la instalación de plantillas y la
promoción entre entornos —tres puertas por las que entra una regla— para que
ninguna deje pasar lo que otra rechaza.
"""

from __future__ import annotations

from typing import Any

from crmcore.errors import ErrorValidacion

from services.automation import cron, motor

DISPARADORES = (
    "creacion",
    "modificacion",
    "eliminacion",
    "evento",
    "webhook",
    "programada",
    "manual",
)
MOMENTOS = ("inmediata", "diferida", "programada")

# Lo que cada ejecutor exige sí o sí. Sale de sus propias comprobaciones en
# `ejecutores.py`: lo que aquí falta, allí revienta al ejecutarse.
_OBLIGATORIOS: dict[str, tuple[str, ...]] = {
    "crear_registro": ("objeto",),
    "actualizar_registro": ("objeto", "registro_id"),
    "asignar": ("usuario_id",),
    "notificar": ("titulo",),
    "enviar_correo": ("titulo",),
    "lanzar_proceso": ("proceso",),
    "emitir_evento": ("tipo",),
    "llamar_api": ("url",),
    "calcular": ("campo",),
}


def _acciones(acciones: list[Any], ruta: str, problemas: list[str]) -> None:
    for i, accion in enumerate(acciones or []):
        donde = f"{ruta}[{i}]"
        if not isinstance(accion, dict):
            problemas.append(f"{donde}: una acción es un objeto con «tipo»")
            continue
        tipo = str(accion.get("tipo", ""))
        if tipo not in motor.ACCIONES | motor.CONTROL:
            problemas.append(f"{donde}: acción no admitida «{tipo}»")
            continue
        if tipo == "si":
            _condiciones(accion.get("condiciones") or [], f"{donde}.condiciones", problemas)
            _acciones(accion.get("entonces") or [], f"{donde}.entonces", problemas)
            _acciones(accion.get("si_no") or [], f"{donde}.si_no", problemas)
            continue
        if tipo == "para_cada":
            _acciones(accion.get("hacer") or [], f"{donde}.hacer", problemas)
            continue
        if tipo == "fijar":
            if not str(accion.get("nombre", "")).strip():
                problemas.append(f"{donde}: «fijar» necesita el nombre de la variable")
            continue
        parametros = accion.get("parametros") or {}
        for campo in _OBLIGATORIOS.get(tipo, ()):
            if parametros.get(campo) in (None, "", []):
                problemas.append(f"{donde}: «{tipo}» necesita «{campo}» en sus parámetros")


def _condiciones(condiciones: list[Any], ruta: str, problemas: list[str]) -> None:
    from services.orchestrator.motor import OPERADORES

    for i, condicion in enumerate(condiciones or []):
        donde = f"{ruta}[{i}]"
        if not isinstance(condicion, dict) or not str(condicion.get("atributo", "")).strip():
            # Sin atributo no se cumple nunca (ver `motor._evaluar_lista`): la
            # regla se guardaría y no se dispararía jamás.
            problemas.append(f"{donde}: una condición necesita «atributo»")
            continue
        if str(condicion.get("op", "=")) not in OPERADORES:
            problemas.append(
                f"{donde}: operador «{condicion.get('op')}» desconocido; "
                f"valen {', '.join(sorted(OPERADORES))}"
            )


def problemas_de(definicion: dict[str, Any], *, estricta: bool = False) -> list[str]:
    """Todo lo que impide correr a esta definición, de una vez.

    Todos y no el primero: quien escribe una regla de diez acciones no puede
    descubrir los fallos de uno en uno.

    `estricta` exige además los parámetros obligatorios de cada acción. El alta
    de siempre no la usaba y aceptaba reglas sin ellos; se exige en las puertas
    nuevas —plantillas y promoción— y se deja como estaba en el alta para no
    romper a quien ya crea reglas por API.
    """
    problemas: list[str] = []
    disparador = str(definicion.get("disparador", ""))
    if disparador not in DISPARADORES:
        problemas.append(f"disparador «{disparador}» desconocido")
    momento = str(definicion.get("momento", "inmediata"))
    if momento not in MOMENTOS:
        problemas.append(f"momento «{momento}» desconocido")
    if disparador == "programada" or momento == "programada":
        try:
            cron.leer(definicion.get("programacion"))
        except ErrorValidacion as exc:
            problemas.append(exc.mensaje)
    if disparador == "evento":
        from crmcore.events.catalogo import obtener

        if obtener(str(definicion.get("objetivo", ""))) is None:
            problemas.append(
                f"«{definicion.get('objetivo')}» no es un evento del catálogo: una regla "
                "enganchada a un evento que nadie publica no se dispara nunca"
            )
    if estricta:
        _acciones(definicion.get("acciones") or [], "acciones", problemas)
    else:
        for accion in definicion.get("acciones") or []:
            tipo = str((accion or {}).get("tipo", "")) if isinstance(accion, dict) else ""
            if tipo not in motor.ACCIONES | motor.CONTROL:
                problemas.append(f"acción no admitida «{tipo}»")
    if not definicion.get("acciones"):
        problemas.append("una automatización sin acciones no hace nada")
    _condiciones(definicion.get("condiciones") or [], "condiciones", problemas)
    return problemas


def exigir(definicion: dict[str, Any], *, estricta: bool = False) -> None:
    """Como `problemas_de`, pero corta con un 422 que los lleva todos dentro."""
    problemas = problemas_de(definicion, estricta=estricta)
    if problemas:
        raise ErrorValidacion(
            "La automatización no puede correr así: " + "; ".join(problemas),
            error_code="automatizacion.no_valida",
            detalle={"problemas": problemas, "admitidas": sorted(motor.ACCIONES)},
        )
