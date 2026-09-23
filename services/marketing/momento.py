"""Cuándo y por dónde escribir a cada persona (CRM-02.02.02.05).

Mandar la campaña «el martes a las diez» es lo que hace todo el mundo porque es lo
que dice un artículo de hace diez años. Optimizar por destinatario suena mejor y
tiene una trampa grande: **con pocos datos, lo que se optimiza es el ruido**. Si
alguien abrió dos correos y los dos por la tarde, concluir que prefiere las tardes
es echar una moneda dos veces.

Las decisiones:

**Por debajo de un mínimo de historial no se personaliza**, y se dice. Se usa la
hora del segmento o la general, que es honesto y funciona.

**El canal preferido se mide por respuesta, no por apertura.** Abrir un correo no
significa nada; contestarlo sí. Optimizar por aperturas lleva a mandar más correos
a quien los abre y nunca responde, que es exactamente el perfil de quien tiene el
correo abierto todo el día.

**Lo que dijo la persona manda sobre lo que dice el modelo.** Si pidió que no se
le llame por teléfono, no hay propensión que valga: eso no es una preferencia
estimada, es una instrucción.

**Y la franja horaria es la suya, no la nuestra.** Es el fallo más tonto y el más
frecuente: la campaña «a las nueve» llega a las tres de la mañana a quien está en
otro huso.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, time, timezone
from typing import Any

from crmcore.errors import ErrorValidacion
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Interacciones mínimas para personalizar. Por debajo, lo que se detecta es azar
# con aspecto de patrón.
MINIMO_INTERACCIONES = 8

# Canales que se pueden elegir. Cerrada porque cada uno tiene su regla de
# consentimiento y su coste, y con texto libre no se comprueba ninguno.
CANALES = ("email", "sms", "whatsapp", "llamada", "push", "postal")

# Qué cuenta como respuesta de verdad, por canal. La apertura no está: abrir un
# correo no significa nada, y optimizar por aperturas lleva a escribir más a quien
# los abre y nunca contesta.
RESPUESTA_DE_VERDAD = ("respondido", "clic", "conversion", "contestada")


def franja_preferida(
    *, interacciones: list[dict[str, Any]], huso_del_destinatario: str = "UTC"
) -> dict[str, Any]:
    """A qué hora contesta esta persona, **si es que se puede saber**.

    Con menos de un puñado de interacciones no se personaliza: se dice y se usa la
    hora del segmento. Concluir que alguien «prefiere las tardes» porque abrió dos
    correos por la tarde es echar una moneda dos veces y creerse el resultado.
    """
    utiles = [
        i
        for i in interacciones
        if str(i.get("resultado")) in RESPUESTA_DE_VERDAD and isinstance(i.get("cuando"), datetime)
    ]
    if len(utiles) < MINIMO_INTERACCIONES:
        return {
            "personalizable": False,
            "interacciones_utiles": len(utiles),
            "porque": (
                f"Solo hay {len(utiles)} respuestas y hacen falta {MINIMO_INTERACCIONES}. "
                "Con menos, lo que se detecta es azar con aspecto de patrón."
            ),
            "que_usar": "La hora del segmento, o la general. Es honesto y funciona.",
        }

    horas = Counter(i["cuando"].hour for i in utiles)
    hora, cuantas = horas.most_common(1)[0]
    return {
        "personalizable": True,
        "hora_local": time(hour=hora).isoformat(timespec="minutes"),
        "huso": huso_del_destinatario,
        "respuestas_en_esa_franja": cuantas,
        "de_un_total": len(utiles),
        "porque": (
            f"De {len(utiles)} respuestas, {cuantas} llegaron alrededor de las {hora}:00 "
            "en su hora local."
        ),
        "aviso_del_huso": (
            "La franja es la suya, no la nuestra. Es el fallo más tonto y el más "
            "frecuente: la campaña «a las nueve» llega a las tres de la mañana a quien "
            "está en otro huso."
        ),
    }


def canal_preferido(
    *, interacciones: list[dict[str, Any]], prohibidos: list[str] | None = None
) -> dict[str, Any]:
    """Por dónde contesta, **y por dónde no se le puede escribir**.

    Lo que la persona dijo manda sobre lo que dice el modelo: si pidió que no se
    le llame, no hay propensión que valga — eso no es una preferencia estimada, es
    una instrucción, y saltársela es lo que hace que alguien se dé de baja de todo.
    """
    vetados = {c.lower() for c in (prohibidos or [])}
    desconocidos = sorted(vetados - set(CANALES))
    if desconocidos:
        raise ErrorValidacion(
            f"Canales desconocidos en la lista de prohibidos: {', '.join(desconocidos)}",
            error_code="momento.canal_invalido",
            detalle={"admitidos": list(CANALES)},
        )

    respuestas = Counter(
        str(i.get("canal"))
        for i in interacciones
        if str(i.get("resultado")) in RESPUESTA_DE_VERDAD and str(i.get("canal")) in CANALES
    )
    disponibles = [(c, n) for c, n in respuestas.most_common() if c not in vetados]

    if not disponibles:
        return {
            "canal": None,
            "medible": False,
            "porque": (
                "No hay ninguna respuesta por un canal permitido. No es que prefiera "
                "otro: es que no se sabe, o que los que responden están vetados."
            ),
            "prohibidos": sorted(vetados),
        }

    canal, cuantas = disponibles[0]
    return {
        "canal": canal,
        "medible": len(interacciones) >= MINIMO_INTERACCIONES,
        "respuestas": cuantas,
        "prohibidos": sorted(vetados),
        "porque": (
            f"Es por donde más ha contestado ({cuantas} veces). Se mide por respuesta y "
            "no por apertura: abrir un correo no significa nada, y optimizar por "
            "aperturas lleva a escribir más a quien los abre y nunca contesta."
        ),
        "aviso": (
            ""
            if len(interacciones) >= MINIMO_INTERACCIONES
            else "Con este historial la preferencia es una suposición: se usa, pero no "
            "se presenta como un dato."
        ),
    }


def planificar_envio(
    *,
    destinatarios: list[dict[str, Any]],
    hora_por_defecto: int = 10,
    ahora: datetime | None = None,
) -> dict[str, Any]:
    """Reparte el envío por destinatario, respetando su hora y su canal.

    Y devuelve **cuántos se envían a la hora general**, que es el número que
    importa: si el 90 % va a la hora por defecto, la personalización no está
    haciendo nada y conviene saberlo antes de contárselo a alguien como una mejora.
    """
    momento = ahora or datetime.now(timezone.utc)
    plan: list[dict[str, Any]] = []
    por_defecto = 0
    for destinatario in destinatarios:
        hora = destinatario.get("hora_preferida")
        if hora is None:
            hora = hora_por_defecto
            por_defecto += 1
        plan.append(
            {
                "id": str(destinatario.get("id")),
                "hora_local": int(hora),
                "canal": destinatario.get("canal") or "email",
                "huso": destinatario.get("huso") or "UTC",
            }
        )

    return {
        "envios": len(plan),
        "a_la_hora_general": por_defecto,
        "personalizados": len(plan) - por_defecto,
        "plan": plan,
        "calculado_at": momento.isoformat(),
        "que_significa": (
            f"{por_defecto} de {len(plan)} van a la hora general."
            + (
                " La personalización casi no está haciendo nada: conviene saberlo antes "
                "de contarlo como una mejora."
                if plan and por_defecto / len(plan) > 0.8
                else ""
            )
        ),
    }


def comparar_con_hora_fija(
    *, con_optimizacion: dict[str, Any], sin_optimizacion: dict[str, Any]
) -> dict[str, Any]:
    """Si personalizar la hora ha servido de algo.

    Se compara contra mandar a una hora fija, que es la alternativa real. Sin esta
    comparación, cualquier resultado se atribuye a la optimización — incluida la
    mejora que venía del asunto del correo.
    """

    def _tasa(datos: dict[str, Any]) -> float:
        enviados = int(datos.get("enviados") or 0)
        return (int(datos.get("respuestas") or 0) / enviados) if enviados else 0.0

    con = _tasa(con_optimizacion)
    sin = _tasa(sin_optimizacion)
    minimo = min(
        int(con_optimizacion.get("enviados") or 0), int(sin_optimizacion.get("enviados") or 0)
    )
    return {
        "tasa_con": round(con * 100, 2),
        "tasa_sin": round(sin * 100, 2),
        "diferencia_pp": round((con - sin) * 100, 2),
        "concluyente": minimo >= 500,
        "que_significa": (
            f"Con solo {minimo} envíos en la rama más pequeña, la diferencia no es "
            "concluyente: cabe entera dentro del ruido."
            if minimo < 500
            else (
                "Personalizar la hora mejora la respuesta."
                if con > sin
                else "Personalizar la hora no mejora nada aquí. Es un resultado válido y "
                "conviene decirlo: mantenerlo por inercia cuesta complejidad para nada."
            )
        ),
    }
