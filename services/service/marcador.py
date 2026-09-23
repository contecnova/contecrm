"""Marcador integrado, grabación y registro automático (CRM-03.03.01.05).

Pulsar un número y que llame es la funcionalidad que más se usa de un CRM
comercial, y la que peor implementada está casi siempre — porque lo difícil no es
lanzar la llamada: es **lo que pasa al colgar**.

Las decisiones:

**La llamada se registra sola al colgar, con su duración y su resultado.** Pedirle
al comercial que anote cada llamada es pedirle que dedique el 20 % de su día a
teclear: no lo hace, y entonces el CRM dice que ese cliente lleva tres meses sin
contacto cuando se habló con él el martes.

**Pero lo que pasó lo escribe una persona.** «Contestada, 3 minutos» no es
información comercial. Se pide una nota corta y se hace fácil; lo que no se hace
es inventarla.

**Grabar exige avisar, siempre, y poder no grabar.** Es un requisito legal en casi
todas partes y, más importante, es lo que hace que una conversación siga siendo
una conversación. Una llamada que no se puede grabar no se bloquea: se hace sin
grabar y se anota por qué.

**Y el marcado automático tiene un límite que no se negocia.** Marcar a más gente
de la que hay para atender produce llamadas que suenan y cuelgan —el *abandono*—,
y eso está regulado y además es lo que hace que un número acabe marcado como spam
en el teléfono de todo el mundo.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.errors import ErrorValidacion, Prohibido
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Cómo terminó la llamada, desde el punto de vista comercial. Cerrada porque de
# esto sale el siguiente paso, y «otros» acaba siendo el 40 % y no dice nada.
RESULTADOS = (
    "hablado",
    "buzon",
    "no_contesta",
    "numero_erroneo",
    "persona_equivocada",
    "pide_que_no_le_llamen",
    "reprogramar",
)

# Resultados que obligan a hacer algo más que anotar. `pide_que_no_le_llamen` no
# es un resultado cualquiera: es una instrucción con efectos legales.
EXIGEN_ACCION = {
    "pide_que_no_le_llamen": "Se apunta la exclusión ese mismo día, en todos los canales que dijo",
    "numero_erroneo": "Se marca el teléfono como malo para que no vuelva a la cola",
    "reprogramar": "Se crea la siguiente llamada con fecha, o se pierde",
}

# Tope de abandono en marcado automático. Es el porcentaje de llamadas que suenan
# y se cuelgan porque no había nadie libre. Está regulado en varios países y,
# además de la multa, es lo que hace que el número acabe marcado como spam.
ABANDONO_MAXIMO_PCT = 3.0


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def preparar_llamada(
    *,
    contacto_id: UUID,
    numero: str,
    consiente_grabacion: bool,
    grabar_por_politica: bool,
    en_lista_de_exclusion: bool = False,
) -> dict[str, Any]:
    """Comprueba lo que hay que comprobar **antes** de que suene.

    Llamar a alguien que pidió no ser llamado no es un descuido: es una sanción y
    una conversación desagradable. Se comprueba aquí, no al registrar.

    Y si la política dice grabar pero la persona no consiente, **la llamada se
    hace igual sin grabar**: bloquearla convierte una cuestión de privacidad en
    un cliente que no puede hablar con nadie.
    """
    if en_lista_de_exclusion:
        raise Prohibido(
            "Esta persona pidió no ser llamada. Hacerlo igual no es un descuido: es una "
            "sanción y una conversación desagradable.",
            error_code="marcador.en_exclusion",
        )
    graba = grabar_por_politica and consiente_grabacion
    return {
        "contacto_id": str(contacto_id),
        "numero": numero,
        "se_graba": graba,
        "hay_que_avisar": graba,
        "porque": (
            "Se graba y hay que decirlo al empezar: es un requisito legal casi en todas "
            "partes y es lo que hace que la conversación siga siendo una conversación."
            if graba
            else (
                "No se graba porque la persona no lo consiente. La llamada se hace igual: "
                "bloquearla convertiría una cuestión de privacidad en un cliente que no "
                "puede hablar con nadie."
                if grabar_por_politica
                else "La política de este tenant no graba estas llamadas."
            )
        ),
    }


def registrar_al_colgar(
    *,
    contacto_id: UUID,
    duracion_s: int,
    resultado: str,
    nota: str = "",
    grabacion_ref: str = "",
    proxima_fecha: Any = None,
) -> dict[str, Any]:
    """Registra la llamada **sola**, y pide lo que solo sabe una persona.

    La actividad se crea al colgar con lo que el sistema sabe: a quién, cuánto y
    cómo terminó. Lo que **no** se inventa es qué se dijo: «contestada, 3 minutos»
    no es información comercial, y rellenar la nota automáticamente con una frase
    genérica es peor que dejarla vacía — parece que hay contenido.

    Y hay resultados que **obligan a algo más**: quien pide que no le llamen
    entra en la exclusión ese mismo día, y un «reprogramar» sin fecha es una
    llamada que se pierde.
    """
    if resultado not in RESULTADOS:
        raise ErrorValidacion(
            f"Resultado «{resultado}» desconocido",
            error_code="marcador.resultado_invalido",
            detalle={"admitidos": list(RESULTADOS)},
        )
    if resultado == "reprogramar" and not proxima_fecha:
        raise ErrorValidacion(
            "Un «reprogramar» sin fecha es una llamada que se pierde: nadie vuelve a una "
            "lista de pendientes sin fecha.",
            error_code="marcador.sin_proxima_fecha",
        )

    acciones = [EXIGEN_ACCION[resultado]] if resultado in EXIGEN_ACCION else []
    return {
        "contacto_id": str(contacto_id),
        "duracion_s": duracion_s,
        "resultado": resultado,
        "nota": nota.strip(),
        "grabacion": grabacion_ref,
        "registrada_at": _ahora().isoformat(),
        "acciones_obligadas": acciones,
        "falta_la_nota": not nota.strip() and resultado == "hablado",
        "porque": (
            "La actividad se crea sola con lo que el sistema sabe. Pedirle al comercial "
            "que anote cada llamada es pedirle el 20 % de su día: no lo hace, y entonces "
            "el CRM dice que ese cliente lleva tres meses sin contacto."
        ),
        "que_falta": (
            "Falta la nota de qué se habló. No se inventa: «contestada, 3 minutos» no es "
            "información comercial, y rellenarla con una frase genérica es peor que "
            "dejarla vacía porque parece que hay contenido."
            if not nota.strip() and resultado == "hablado"
            else ""
        ),
    }


def ritmo_de_marcado(
    *, agentes_libres: int, llamadas_lanzadas: int, abandonadas: int, contestadas: int
) -> dict[str, Any]:
    """Cuántas llamadas se pueden lanzar a la vez sin pasarse.

    El marcado automático marca a más gente de la que hay para atender a propósito
    —porque muchos no cogen— y ahí está el riesgo: las que sí cogen y no tienen
    agente libre suenan y se cuelgan. Eso es el **abandono**, está regulado, y
    además es lo que hace que el número acabe marcado como spam en el teléfono de
    todo el mundo, que no se arregla pagando una multa.
    """
    total = abandonadas + contestadas
    pct = (abandonadas / total * 100) if total else 0.0
    dentro = pct <= ABANDONO_MAXIMO_PCT

    if not dentro:
        recomendado = max(1, agentes_libres)
    else:
        # Un poco por encima de los agentes libres, no el triple: pasarse es lo
        # que produce el abandono que se acaba de medir.
        recomendado = max(1, int(agentes_libres * 1.3))

    return {
        "abandono_pct": round(pct, 2),
        "tope": ABANDONO_MAXIMO_PCT,
        "dentro_del_limite": dentro,
        "lanzar_como_mucho": recomendado,
        "medible": total >= 50,
        "que_significa": (
            f"Con {total} llamadas todavía no se puede decir nada del abandono: dos "
            "colgadas seguidas darían un porcentaje enorme."
            if total < 50
            else (
                f"El abandono está en {round(pct, 2)} % y el tope es "
                f"{ABANDONO_MAXIMO_PCT} %. Hay que bajar el ritmo: además de la multa, "
                "es lo que hace que el número acabe marcado como spam, y eso no se "
                "arregla pagando."
                if not dentro
                else f"Abandono en {round(pct, 2)} %, dentro del límite."
            )
        ),
    }


def politica_de_grabacion(*, grabar: bool, avisar: bool, dias_conservacion: int) -> dict[str, Any]:
    """Comprueba que la política de grabación se sostiene.

    Grabar sin avisar no es una opción que se pueda ofrecer, ni siquiera como
    ajuste: no es una preferencia del cliente, es un requisito legal. Y una
    grabación sin plazo de borrado es un archivo de voz que crece para siempre —
    con la voz de gente que no sabe que sigue ahí.
    """
    problemas: list[str] = []
    if grabar and not avisar:
        problemas.append(
            "Grabar sin avisar no es una opción configurable: es ilegal en casi todas "
            "partes y rompe la confianza en el resto."
        )
    if grabar and dias_conservacion <= 0:
        problemas.append(
            "No hay plazo de borrado. Una grabación sin plazo es un archivo de voz que "
            "crece para siempre, con gente que no sabe que sigue ahí."
        )
    if grabar and dias_conservacion > 3650:
        problemas.append(
            "Más de diez años de conservación de voz necesita una justificación que casi "
            "nunca existe."
        )
    return {"valido": not problemas, "problemas": problemas}
