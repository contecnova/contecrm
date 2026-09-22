"""Respuesta sobre datos propios con citación, y consulta en lenguaje natural
(CRM-05.02.02.03, CRM-05.02.02.04).

Una respuesta generada sobre los datos del cliente **sin decir de dónde sale** no
vale: el que la lee no puede comprobarla, y cuando resulte estar mal —y alguna
estará mal— no habrá forma de saber si el fallo fue del dato o del modelo.

Por eso aquí la citación no es un adorno:

**Sin fuentes citadas, no se devuelve la respuesta.** Aunque el modelo haya
escrito un párrafo perfecto. Un párrafo perfecto sin fuente es exactamente lo que
produce un modelo cuando no encontró nada y rellena el hueco.

**Se comprueba que lo citado existía en el contexto.** Un modelo puede inventarse
una referencia con una forma impecable; si la cita no corresponde a ningún
fragmento de los que se le pasaron, se marca y no se presenta como buena.

**Lo que no está en el contexto se contesta con «no lo sé».** Es la respuesta más
difícil de conseguir de un modelo y la única que hace que alguien se fíe de las
demás.

Y para la consulta en lenguaje natural (`CRM-05.02.02.04`): **el modelo no
consulta la base de datos**. Traduce la pregunta a un **plan** —el mismo formato
que compila el motor de informes— y ese plan lo ejecuta quien tiene el dato, con
los permisos de quien pregunta. Dejar que el modelo escriba SQL contra el CRM es
darle a un generador de texto la capacidad de leer cualquier tabla, y ningún
filtro posterior arregla eso.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import UUID

from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion
from crmcore.logging import get_logger

from services.intelligence import enrutador, guardias, uso

logger = get_logger(__name__)

# Cómo cita el modelo: [1], [2]… Se le pide así porque es lo que menos se
# equivoca y lo más fácil de comprobar contra la lista que se le pasó.
RE_CITA = re.compile(r"\[(\d{1,2})\]")

# Operadores que puede proponer una pregunta en lenguaje natural. Cerrada: el
# plan lo ejecuta otro, y un operador que no sepa traducir sería una consulta que
# falla lejos de aquí.
OPERADORES_PLAN = ("=", "!=", ">", ">=", "<", "<=", "en", "contiene", "entre")

_respondedor: Callable[..., dict[str, Any]] | None = None
_traductor: Callable[..., dict[str, Any]] | None = None


def registrar_respondedor(fn: Callable[..., dict[str, Any]]) -> None:
    """Quién responde con contexto (RAG)."""
    global _respondedor
    _respondedor = fn


def registrar_traductor(fn: Callable[..., dict[str, Any]]) -> None:
    """Quién traduce una pregunta a un plan de consulta."""
    global _traductor
    _traductor = fn


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def responder(
    uow: UnidadDeTrabajo,
    *,
    pregunta: str,
    fragmentos: list[dict[str, Any]],
    principal: Any = None,
    objeto: str = "",
    objeto_id: UUID | None = None,
) -> dict[str, Any]:
    """Responde usando solo el contexto dado, **citando** (CRM-05.02.02.03).

    Tres comprobaciones sobre lo que devuelve el modelo, y ninguna es opcional:

    1. **Que cite.** Sin citas, la respuesta no se presenta como buena: un párrafo
       perfecto sin fuente es lo que produce un modelo cuando no encontró nada.
    2. **Que lo citado exista.** Una cita a `[7]` cuando solo se pasaron cinco
       fragmentos es una referencia inventada, y tiene la misma forma que una
       buena.
    3. **Que se pueda decir que no se sabe.** Si el modelo contesta que no hay
       información, eso se devuelve tal cual: es la respuesta que hace que las
       demás se puedan creer.
    """
    if not pregunta.strip():
        raise ErrorValidacion("No hay pregunta.", error_code="rag.pregunta_vacia")
    filtrado = guardias.filtrar_contexto(
        uow.db, uow.tenant_id, fragmentos=fragmentos, principal=principal
    )
    disponibles = filtrado["fragmentos"]
    if not disponibles:
        guardias.anotar_bloqueo(
            uow,
            motivo="sin_contexto",
            tarea="rag",
            usuario_id=getattr(principal, "id", None),
            detalle={"quitados": len(filtrado["quitados"])},
        )
        return {
            "respondida": False,
            "respuesta": "",
            # Se distingue «no hay datos» de «no puedes verlos»: son dos
            # problemas distintos y solo uno se arregla pidiendo permiso.
            "porque": (
                "No queda contexto que puedas ver para responder."
                if filtrado["quitados"]
                else "No hay contexto con el que responder."
            ),
            "quitados_por_permisos": filtrado["quitados"],
        }

    elegido = enrutador.exigir_disponible(uow.db, uow.tenant_id, uso="consulta")
    if _respondedor is None:
        raise Conflicto(
            "No hay respondedor conectado en este despliegue.",
            error_code="rag.sin_respondedor",
        )

    numerados = [
        {
            "n": i + 1,
            "fuente": str(f.get("fuente") or ""),
            "id": str(f.get("id") or ""),
            "texto": f.get("texto"),
        }
        for i, f in enumerate(disponibles)
    ]
    inicio = _ahora()
    respuesta = _respondedor(
        proveedor=elegido["elegido"],
        modelo=elegido.get("modelo", ""),
        pregunta=pregunta,
        fragmentos=numerados,
        opt_out=bool(elegido.get("opt_out")),
    )
    texto = str(respuesta.get("texto") or "")
    sin_respuesta = bool(respuesta.get("sin_respuesta")) or not texto.strip()

    citados = {int(n) for n in RE_CITA.findall(texto) if n.isdigit()}
    validos = {f["n"] for f in numerados}
    inventadas = sorted(citados - validos)
    usadas = sorted(citados & validos)

    llamada = uso.anotar(
        uow,
        tarea="rag",
        proveedor=str(elegido.get("elegido") or ""),
        modelo=str(respuesta.get("modelo") or elegido.get("modelo") or ""),
        region=str(elegido.get("region") or ""),
        usuario_id=getattr(principal, "id", None),
        objeto=objeto,
        objeto_id=objeto_id,
        prompt=pregunta,
        fuentes=[{"fuente": f["fuente"], "id": f["id"]} for f in numerados if f["n"] in usadas],
        tokens_entrada=int(respuesta.get("tokens_entrada") or 0),
        tokens_salida=int(respuesta.get("tokens_salida") or 0),
        coste=enrutador.coste_estimado(
            uow.db,
            proveedor=str(elegido.get("elegido") or ""),
            tokens_entrada=int(respuesta.get("tokens_entrada") or 0),
            tokens_salida=int(respuesta.get("tokens_salida") or 0),
        ),
        duracion_ms=int((_ahora() - inicio).total_seconds() * 1000),
        resultado="sin_respuesta" if sin_respuesta else "pendiente",
        opt_out=bool(elegido.get("opt_out")),
    )
    enrutador.anotar_gasto(
        uow,
        proveedor=str(elegido.get("elegido") or ""),
        tokens_entrada=llamada.tokens_entrada,
        tokens_salida=llamada.tokens_salida,
        coste=llamada.coste,
    )

    if sin_respuesta:
        return {
            "respondida": False,
            "respuesta": "",
            "llamada_id": str(llamada.id),
            # Que el modelo diga que no sabe es un acierto, no un fallo.
            "porque": "El contexto no contiene la respuesta, y el modelo lo ha dicho.",
            "fiable": True,
        }

    if not usadas:
        return {
            "respondida": False,
            "respuesta": texto,
            "llamada_id": str(llamada.id),
            "citas": [],
            "fiable": False,
            "porque": (
                "La respuesta no cita ninguna fuente del contexto: no se puede "
                "comprobar, y un párrafo sin fuente es lo que escribe un modelo "
                "cuando no encuentra nada."
            ),
        }

    return {
        "respondida": True,
        "respuesta": texto,
        "llamada_id": str(llamada.id),
        "citas": [
            {"n": f["n"], "fuente": f["fuente"], "id": f["id"]}
            for f in numerados
            if f["n"] in usadas
        ],
        # Una cita a un número que no existía es una referencia inventada, con la
        # misma forma que una buena. Se dice.
        "citas_inventadas": inventadas,
        "fiable": not inventadas and filtrado["completo"],
        "contexto_incompleto": not filtrado["completo"],
        "quitados_por_permisos": filtrado["quitados"],
        "aviso": (
            "Hay citas que no corresponden a ningún fragmento del contexto: "
            "compruébalas antes de usar la respuesta."
            if inventadas
            else ""
        ),
    }


def preguntar_a_los_datos(
    uow: UnidadDeTrabajo,
    *,
    pregunta: str,
    modelo_datos: dict[str, Any],
    principal: Any = None,
) -> dict[str, Any]:
    """Traduce una pregunta en lenguaje natural a un **plan** (CRM-05.02.02.04).

    **El modelo no toca la base de datos.** Propone un plan —objeto, campos,
    filtros, agrupación— con el mismo formato que compila el motor de informes, y
    ese plan lo ejecuta quien tiene el dato, con los permisos de quien pregunta.
    Dejar que el modelo escriba SQL sería darle a un generador de texto acceso a
    cualquier tabla, y ningún filtro posterior arregla eso.

    El plan se **valida contra el modelo publicado** antes de devolverlo: un
    objeto o un campo inventado produciría una consulta que falla lejos de aquí, y
    el error que aparece no se parece a la causa.

    Y se devuelve **cómo entendió la pregunta**, en una frase. Es lo que permite
    que alguien vea que preguntó por «este trimestre» y el plan filtró por «este
    año» antes de llevarse el número a una reunión.
    """
    if _traductor is None:
        raise Conflicto(
            "No hay traductor conectado en este despliegue.", error_code="rag.sin_traductor"
        )
    elegido = enrutador.exigir_disponible(uow.db, uow.tenant_id, uso="consulta")

    inicio = _ahora()
    propuesta = _traductor(
        proveedor=elegido["elegido"],
        modelo=elegido.get("modelo", ""),
        pregunta=pregunta,
        modelo_datos=modelo_datos,
        opt_out=bool(elegido.get("opt_out")),
    )
    plan = dict(propuesta.get("plan") or {})
    problemas: list[str] = []

    objetos = {str(o.get("clave") or o.get("nombre")) for o in (modelo_datos.get("objetos") or [])}
    objeto = str(plan.get("objeto") or "")
    if objetos and objeto not in objetos:
        problemas.append(f"El plan pregunta por «{objeto}», que no está en el modelo publicado.")
    campos_validos = {
        str(c.get("nombre"))
        for o in (modelo_datos.get("objetos") or [])
        if str(o.get("clave") or o.get("nombre")) == objeto
        for c in (o.get("campos") or [])
    }
    for campo in plan.get("campos") or []:
        if campos_validos and str(campo) not in campos_validos:
            problemas.append(f"El campo «{campo}» no existe en «{objeto}».")
    for filtro in plan.get("filtros") or []:
        if str(filtro.get("operador")) not in OPERADORES_PLAN:
            problemas.append(f"Operador «{filtro.get('operador')}» no admitido en un plan.")
        if campos_validos and str(filtro.get("campo")) not in campos_validos:
            problemas.append(f"El filtro usa «{filtro.get('campo')}», que no existe.")

    llamada = uso.anotar(
        uow,
        tarea="consulta_natural",
        proveedor=str(elegido.get("elegido") or ""),
        modelo=str(propuesta.get("modelo") or elegido.get("modelo") or ""),
        region=str(elegido.get("region") or ""),
        usuario_id=getattr(principal, "id", None),
        prompt=pregunta,
        tokens_entrada=int(propuesta.get("tokens_entrada") or 0),
        tokens_salida=int(propuesta.get("tokens_salida") or 0),
        coste=enrutador.coste_estimado(
            uow.db,
            proveedor=str(elegido.get("elegido") or ""),
            tokens_entrada=int(propuesta.get("tokens_entrada") or 0),
            tokens_salida=int(propuesta.get("tokens_salida") or 0),
        ),
        duracion_ms=int((_ahora() - inicio).total_seconds() * 1000),
        resultado="error" if problemas else "aceptada",
        error="; ".join(problemas)[:300] if problemas else "",
        opt_out=bool(elegido.get("opt_out")),
    )
    enrutador.anotar_gasto(
        uow,
        proveedor=str(elegido.get("elegido") or ""),
        tokens_entrada=llamada.tokens_entrada,
        tokens_salida=llamada.tokens_salida,
        coste=llamada.coste,
    )

    return {
        "valido": not problemas,
        "plan": plan if not problemas else None,
        "problemas": problemas,
        "llamada_id": str(llamada.id),
        # Cómo entendió la pregunta, en una frase: es lo que permite ver que
        # preguntaste por «este trimestre» y filtró por «este año» **antes** de
        # llevarte el número a una reunión.
        "interpretacion": str(propuesta.get("interpretacion") or ""),
        "ejecutado": False,
        "aviso": (
            "El plan no se ha ejecutado: lo ejecuta quien tiene el dato, con tus " "permisos."
            if not problemas
            else "El plan propuesto no encaja con el modelo publicado y no se ha " "ejecutado."
        ),
    }
