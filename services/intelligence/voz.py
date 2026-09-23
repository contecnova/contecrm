"""Voz y asistentes conversacionales (CRM-04.02.01.08).

Un asistente que atiende por voz es la funcionalidad que mejor demo tiene y la que
peor sale en producción, y siempre por lo mismo: **en una demo el que habla
colabora**. En una llamada real la gente se interrumpe, habla con acento, tiene la
tele puesta y dice «sí, bueno, es que...» antes de cada frase.

Las decisiones:

**Cuando no se entiende, se dice y se pasa a una persona.** Lo que no se puede
hacer es pedir que lo repita tres veces: al tercer «no te he entendido» el cliente
ya ha decidido que esta empresa no vale, y eso no lo arregla que a la cuarta
acierte.

**La confianza decide, no el texto.** Un reconocimiento con poca confianza no es
una frase con erratas: es una frase que puede significar lo contrario — «no quiero
cancelar» y «quiero cancelar» se parecen mucho a bajo volumen.

**Y lo irreversible no lo hace una voz.** Cancelar un contrato, devolver un cobro
o cambiar unos datos bancarios por teléfono, con reconocimiento de por medio y sin
que nadie más lo mire, es la clase de decisión que solo se toma porque es fácil de
programar.

**Se avisa de que es una máquina.** No por trámite: porque la gente habla distinto
—más corto y más claro— cuando lo sabe, y porque descubrirlo a los tres minutos
sienta francamente mal.

**Y la grabación de voz es un dato biométrico en potencia.** Guardar audio para
«mejorar el sistema» sin decirlo es exactamente lo que está prohibido sin
consentimiento explícito.
"""

from __future__ import annotations

from typing import Any

from crmcore.errors import ErrorValidacion, Prohibido
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Por debajo de esta confianza no se actúa: se repregunta una vez y, si sigue sin
# entenderse, pasa a una persona.
CONFIANZA_MINIMA = 0.7

# Cuántas veces se puede pedir que lo repita. Dos. Al tercer «no te he entendido»
# el cliente ya ha decidido que esta empresa no vale.
REINTENTOS_MAXIMOS = 2

# Lo que no hace un asistente de voz por su cuenta, diga lo que diga el usuario.
# No es una lista de permisos configurable: es lo que se decide una vez.
NO_POR_VOZ = {
    "cancelar_contrato": "Se confirma con una persona o por un canal donde quede constancia escrita",
    "devolver_cobro": "Mueve dinero: lo confirma alguien",
    "cambiar_datos_bancarios": "Es el fraude telefónico más común que existe",
    "cambiar_direccion_de_envio": "Mismo fraude, otra forma",
    "dar_de_baja_datos": "Es un derecho, y se ejerce por el camino que deja prueba",
}

# Qué puede hacer un asistente de voz sin más. Cosas que se deshacen solas o que
# no cambian nada.
PUEDE_SOLO = (
    "consultar_estado",
    "consultar_horario",
    "dar_referencia",
    "tomar_recado",
    "enrutar",
    "confirmar_cita",
)


def entender(*, texto: str, confianza: float, intento: int) -> dict[str, Any]:
    """Qué hacer con lo que ha entendido el reconocedor.

    **La confianza decide, no el texto.** Un reconocimiento flojo no es una frase
    con erratas: puede significar lo contrario —«no quiero cancelar» y «quiero
    cancelar» se parecen mucho a bajo volumen—, y actuar sobre eso es peor que no
    entender nada.

    Y a la tercera **se pasa a una persona**. Pedir que lo repita otra vez no
    mejora el reconocimiento: solo confirma al cliente que está hablando con una
    máquina que no funciona.
    """
    if confianza >= CONFIANZA_MINIMA:
        return {"entendido": True, "texto": texto, "confianza": round(confianza, 2)}
    if intento >= REINTENTOS_MAXIMOS:
        return {
            "entendido": False,
            "pasar_a_persona": True,
            "porque": (
                "Dos intentos sin entender. Pedirlo otra vez no mejora el "
                "reconocimiento: solo confirma que se está hablando con una máquina que "
                "no funciona, y al tercer «no te he entendido» el cliente ya ha decidido "
                "que esta empresa no vale."
            ),
        }
    return {
        "entendido": False,
        "pasar_a_persona": False,
        "repreguntar": True,
        "confianza": round(confianza, 2),
        "porque": (
            "Reconocimiento con poca confianza. No es una frase con erratas: puede "
            "significar lo contrario, y actuar sobre eso es peor que no entender nada."
        ),
    }


def exigir_que_se_puede_hacer_por_voz(*, accion: str) -> None:
    """Corta lo irreversible antes de intentarlo.

    Cambiar unos datos bancarios por teléfono, con reconocimiento de voz de por
    medio y sin que nadie más lo mire, es el fraude telefónico más común que
    existe. No es una limitación técnica: es una decisión que se toma una vez y no
    se deja configurable, porque configurable significa que alguien la va a abrir.
    """
    if accion in NO_POR_VOZ:
        raise Prohibido(
            f"«{accion}» no se hace por voz: {NO_POR_VOZ[accion]}.",
            error_code="voz.accion_no_permitida",
            detalle={"lo_que_si": list(PUEDE_SOLO)},
        )


def guion_de_apertura(
    *, nombre_asistente: str, es_maquina: bool = True, graba: bool = False
) -> dict[str, Any]:
    """Lo que se dice al empezar, que no es un trámite.

    **Se avisa de que es una máquina** porque la gente habla distinto —más corto y
    más claro— cuando lo sabe, así que el sistema funciona mejor; y porque
    descubrirlo a los tres minutos sienta francamente mal.

    Y si se graba, se dice. Una grabación de voz es un dato biométrico en
    potencia: guardarla para «mejorar el sistema» sin decirlo es exactamente lo
    que está prohibido sin consentimiento explícito.
    """
    partes = [f"Le atiende {nombre_asistente}"]
    if es_maquina:
        partes.append("un asistente automático")
    if graba:
        partes.append("esta llamada se graba")
    return {
        "texto": ", ".join(partes) + ".",
        "dice_que_es_maquina": es_maquina,
        "dice_que_graba": graba,
        "porque": (
            "La gente habla más corto y más claro cuando sabe que es una máquina, así "
            "que el sistema funciona mejor. Y descubrirlo a los tres minutos sienta "
            "francamente mal."
        ),
        "aviso": (
            ""
            if not graba
            else "La grabación de voz es un dato biométrico en potencia: guardarla para "
            "entrenar exige consentimiento explícito, no basta con avisar de que se "
            "graba."
        ),
    }


def usar_audio_para_entrenar(*, consentimiento_explicito: bool) -> dict[str, Any]:
    """Si el audio de esta llamada puede usarse para mejorar el modelo.

    Avisar de que se graba **no es** consentimiento para entrenar: son dos cosas
    distintas, y confundirlas es lo más frecuente en cualquier proyecto de voz.
    Una es conservar una prueba de lo que se dijo y otra es usar la voz de alguien
    para construir un producto.
    """
    if not consentimiento_explicito:
        return {
            "puede": False,
            "porque": (
                "Avisar de que se graba no es consentimiento para entrenar. Una cosa es "
                "conservar prueba de lo que se dijo y otra usar la voz de alguien para "
                "construir un producto: son dos permisos distintos."
            ),
        }
    return {"puede": True, "porque": "Hay consentimiento explícito para ese uso concreto."}


def traspaso_a_persona(
    *, motivo: str, lo_ya_dicho: list[str], datos_recogidos: dict[str, Any]
) -> dict[str, Any]:
    """Pasa la llamada a una persona **con todo lo que ya se habló**.

    Si el asistente estuvo tres minutos preguntando y la persona empieza de cero,
    lo que hizo el asistente fue perder tres minutos del cliente — y eso es peor
    que no haber tenido asistente.
    """
    if not motivo.strip():
        raise ErrorValidacion(
            "Un traspaso sin motivo deja a la persona sin saber por qué le llega esto, y "
            "acaba preguntando otra vez desde el principio.",
            error_code="voz.traspaso_sin_motivo",
        )
    return {
        "motivo": motivo.strip(),
        "lo_ya_dicho": lo_ya_dicho,
        "datos_recogidos": datos_recogidos,
        "el_cliente_no_repite": True,
        "porque": (
            "Si el asistente estuvo tres minutos preguntando y la persona empieza de "
            "cero, lo que hizo el asistente fue perder tres minutos del cliente — peor "
            "que no haberlo tenido."
        ),
    }


def rendimiento(*, conversaciones: list[dict[str, Any]]) -> dict[str, Any]:
    """Si el asistente sirve, medido como se mide de verdad.

    No por «llamadas atendidas» —eso lo hace una locución— sino por **resueltas
    sin persona y sin que el cliente vuelva a llamar en 48 horas**. Una llamada
    que el asistente «resolvió» y que el cliente repite al día siguiente no se
    resolvió: se aplazó, y encima con el cliente ya molesto.
    """
    if not conversaciones:
        return {
            "medible": False,
            "porque": "No hay conversaciones todavía: no se puede decir si sirve.",
        }
    resueltas = [
        c
        for c in conversaciones
        if c.get("resuelta_sin_persona") and not c.get("volvio_a_llamar_48h")
    ]
    falsas = [
        c for c in conversaciones if c.get("resuelta_sin_persona") and c.get("volvio_a_llamar_48h")
    ]
    abandonos = [c for c in conversaciones if c.get("colgo_sin_resolver")]
    pct = round(len(resueltas) / len(conversaciones) * 100, 1)

    return {
        "medible": True,
        "conversaciones": len(conversaciones),
        "resueltas_de_verdad": len(resueltas),
        "falsos_resueltos": len(falsas),
        "colgaron": len(abandonos),
        "pct_resueltas": pct,
        "que_significa": (
            f"El {pct} % se resuelve sin persona y sin que el cliente vuelva."
            + (
                f" Hay {len(falsas)} que constaban como resueltas y volvieron a llamar: "
                "esas no se resolvieron, se aplazaron — y con el cliente ya molesto."
                if falsas
                else ""
            )
            + (
                f" Y {len(abandonos)} colgaron sin resolver nada, que es la métrica que "
                "nadie enseña en las demos."
                if abandonos
                else ""
            )
        ),
    }
