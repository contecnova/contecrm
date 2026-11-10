"""Las plantillas con las que viene el producto (CRM-05.02.02.01, .02, .06).

`generar` exige una plantilla por clave, y un tenant recién dado de alta no
tenía ninguna: todo lo que la IA hace desde una ficha contestaba «No hay
plantilla». Medido el 05-11-2026 con el proveedor ya declarado.

Aquí están las de serie. **No se usan desde aquí**: la primera vez que un tenant
pide una que no tiene, se le guarda como su versión 1, con el motivo «de
serie», y a partir de ahí es suya —se ve, se versiona y se cambia en
«Plantillas de IA» como cualquier otra—. Usarlas en caliente desde el código
haría que el día que un resumen salga raro no se pudiera contestar con qué
texto se pidió.

El idioma no va aquí: es el del tenant (`idioma`), que es el de su gente.
"""

from __future__ import annotations

from typing import Any

# Lo común a todas: lo que el modelo NO puede hacer en un CRM.
_SISTEMA = (
    "Trabajas dentro de un CRM y ayudas a una persona de la empresa. Usa SOLO los "
    "datos que se te dan: si algo no está en ellos, no lo supongas ni lo "
    "completes. No inventes cifras, fechas, nombres ni compromisos. Escribe claro "
    "y breve, sin fórmulas de relleno."
)

DE_SERIE: dict[str, dict[str, Any]] = {
    "resumen_cuenta": {
        "tarea": "resumen",
        "nombre": "Resumen de una cuenta",
        "sistema": _SISTEMA,
        "cuerpo": (
            "Resume la cuenta {{nombre}} para alguien que va a hablar hoy con ella. "
            "Primero tres a cinco puntos clave; después los riesgos, cada uno con el "
            "dato concreto en que se apoya. Si no hay riesgos que los datos "
            "sostengan, dilo así."
        ),
    },
    "resumen_caso": {
        "tarea": "resumen",
        "nombre": "Resumen de un caso",
        "sistema": _SISTEMA,
        "cuerpo": (
            "Resume el caso «{{asunto}}» para el agente que lo recoge: qué pide el "
            "cliente, qué se ha hecho ya y qué queda pendiente. Lo pendiente, en una "
            "lista aparte."
        ),
    },
    "redactar_correo": {
        "tarea": "redaccion",
        "nombre": "Redactar un correo a un contacto",
        "sistema": _SISTEMA,
        "cuerpo": (
            "Redacta un correo para {{destinatario}} con este propósito: {{proposito}}. "
            "Tono profesional y cercano, sin promesas que los datos no sostengan. "
            "Devuelve el asunto en la primera línea y el cuerpo después."
        ),
    },
    "leccion_oportunidad": {
        "tarea": "resumen",
        "nombre": "Post-mortem de una oportunidad cerrada",
        "sistema": _SISTEMA,
        "cuerpo": (
            "Con el expediente de «{{nombre}}» ({{resultado}}), redacta el post-mortem "
            "para que lo firme el comercial. Devuelve SOLO un JSON con: `que_paso` "
            "(qué pasó, con los datos que lo muestran), `senal_temprana` (qué señal "
            "se vio antes y no se atendió, o vacío si no la hubo), "
            "`que_hariamos_distinto` (qué haríamos distinto, concreto) y `factores` "
            "(lista con los que apliquen de: {{factores}}). Apóyate en las "
            "`senales` y en la comparación con las ganadas; no supongas nada que "
            "el expediente no diga."
        ),
    },
    "consejos_lecciones": {
        "tarea": "resumen",
        "nombre": "Consejos de las lecciones para una oportunidad abierta",
        "sistema": _SISTEMA,
        "cuerpo": (
            "Para la oportunidad abierta «{{nombre}}», lee las lecciones firmadas que "
            "se te dan —cada una con su `id`, si se ganó o se perdió, qué pasó y qué "
            "se haría distinto— y escribe consejos concretos. Devuelve SOLO un JSON: "
            "una lista de objetos con `tipo` («haz» o «no_hagas»), `texto` (el "
            "consejo, en una frase, diciendo por qué) y `leccion_id` (el `id` de la "
            "lección de la que sale). Cada consejo sale de UNA lección de las que se "
            "te dan; no escribas ninguno que no puedas atribuir. Si no hay nada útil, "
            "devuelve una lista vacía."
        ),
    },
    "traducir": {
        "tarea": "traduccion",
        "nombre": "Traducir un texto",
        "sistema": (
            "Traduce el texto que se te da al idioma pedido. Conserva el sentido, los "
            "nombres propios, las cifras y el tono. Devuelve sólo la traducción."
        ),
        "cuerpo": "Traduce al {{idioma_destino}} este texto:\n\n{{texto}}",
    },
}


def de_serie(clave: str) -> dict[str, Any] | None:
    return DE_SERIE.get(clave)
