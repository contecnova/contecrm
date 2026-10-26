"""Transcripción, resumen y compromisos de llamadas y reuniones
(CRM-01.02.01.05, CRM-01.02.01.06).

Lo que hace que un comercial no registre una reunión no es la pereza: es que
escribirla cuesta diez minutos que no tiene. Transcribir y resumir se los ahorra,
y por eso esto es de lo que más se usa cuando funciona.

También es de lo que más problemas da, y ninguno es técnico:

**Grabar a alguien sin decírselo es ilegal en media Europa y una ruptura de
confianza en la otra media.** El consentimiento no es una casilla del proyecto: es
la primera comprobación, antes de mandar nada a transcribir.

**Una transcripción no es una prueba.** El modelo confunde nombres, se pierde con
dos personas hablando a la vez y traduce mal las cifras. Se guarda con su nivel de
confianza y se dice que hay que comprobar lo importante — un importe sacado de una
transcripción y metido en una oportunidad acaba en el forecast.

**Y un compromiso extraído es una propuesta, no una tarea.** «Te mando la oferta
el jueves» y «si me la mandas el jueves, la miro» se parecen mucho en un texto y
significan cosas opuestas. Se propone, lo confirma una persona, y se crea.

Además, lo que cuesta dinero se dice antes: transcribir una hora de audio tiene un
precio, y una biblioteca de tres años de llamadas es una factura, no un botón.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.errors import ErrorValidacion, Prohibido
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Bases por las que se puede grabar. Cerrada: «lo hacemos todos» no está, y es la
# que se usa de hecho cuando no hay lista.
BASES_PARA_GRABAR = (
    "consentimiento_de_todos",  # lo han aceptado todos los participantes
    "aviso_y_no_oposicion",  # se avisa al empezar y nadie se opone (según jurisdicción)
    "obligacion_legal",  # sectores regulados que deben grabar
)


# Por debajo de esta confianza, lo transcrito no se propone como dato: se enseña
# para que alguien lo lea. Un número mal oído entra en el forecast.
def _ia_confianza_transcripcion() -> float:
    """Confianza mínima para dar una transcripción por fiable.

    Sin `db` a propósito: esto se calcula en una función pura y meterle una
    sesión para leer un número sería pagar una consulta por llamada. Sale del
    `.env`, o sea de la configuración del despliegue.
    """
    from services.intelligence.ajustes import ajustes

    return ajustes().ia_confianza_transcripcion


# Lo que se extrae de una reunión. Cerrada porque cada cosa se confirma distinto:
# un compromiso se convierte en tarea y un riesgo en una nota para el jefe.
EXTRAIBLES = ("compromiso", "proximo_paso", "riesgo", "objecion", "dato_del_cliente")


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def exigir_permiso_para_grabar(
    *, base: str, participantes_avisados: bool, participantes_externos: bool
) -> None:
    """Se comprueba **antes de mandar nada a transcribir**.

    No es una formalidad del proyecto: grabar a alguien sin decírselo es ilegal en
    media Europa y una ruptura de confianza en la otra media — y el cliente que se
    entera después no vuelve a hablar con soltura delante de nadie.
    """
    if base not in BASES_PARA_GRABAR:
        raise ErrorValidacion(
            f"Base «{base}» no admitida para grabar",
            error_code="transcripcion.base_invalida",
            detalle={"admitidas": list(BASES_PARA_GRABAR)},
        )
    if not participantes_avisados:
        raise Prohibido(
            "No consta que se haya avisado a los participantes. Grabar sin decirlo es "
            "ilegal en media Europa y una ruptura de confianza en la otra media.",
            error_code="transcripcion.sin_aviso",
        )
    if participantes_externos and base == "aviso_y_no_oposicion":
        logger.warning(
            "transcripcion.base_debil_con_externos",
            extra={"base": base},
        )


def registrar_transcripcion(
    *,
    referencia: str,
    texto: str,
    confianza: float,
    idioma: str,
    minutos: int,
    hablantes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Guarda lo transcrito **con su nivel de confianza**.

    Una transcripción no es un acta: el modelo confunde nombres, se pierde con dos
    personas hablando a la vez y traduce mal las cifras. Guardarla como si fuera
    literal hace que alguien la cite en una discusión con el cliente, y ahí se
    acaba la confianza en todo el sistema.

    La **atribución de quién dijo qué** es lo menos fiable de todo, y se marca
    como tal: en una llamada a tres, atribuir una frase a quien no es puede cambiar
    una negociación.
    """
    if not texto.strip():
        raise ErrorValidacion("No hay texto transcrito", error_code="transcripcion.vacia")
    fiable = confianza >= _ia_confianza_transcripcion()
    return {
        "referencia": referencia,
        "minutos": minutos,
        "idioma": idioma,
        "confianza": round(confianza, 2),
        "fiable": fiable,
        "hablantes": hablantes or [],
        "atribucion_fiable": bool(hablantes) and len(hablantes) <= 2,
        "advertencia": (
            ""
            if fiable
            else f"La transcripción tiene una confianza de {round(confianza, 2)}. No se "
            "propone ningún dato a partir de ella: se enseña para que alguien la lea."
        ),
        "que_no_es": (
            "Esto no es un acta. El modelo confunde nombres, se pierde con dos personas "
            "hablando a la vez y traduce mal las cifras: lo importante se comprueba "
            "antes de citarlo."
        ),
        "atribucion": (
            "Quién dijo qué es lo menos fiable de todo. En una llamada a tres, atribuir "
            "una frase a quien no es puede cambiar una negociación."
            if hablantes and len(hablantes) > 2
            else ""
        ),
        "registrada_at": _ahora().isoformat(),
    }


def coste_de_transcribir(
    *, minutos_totales: int, coste_por_minuto: float, presupuesto: float | None = None
) -> dict[str, Any]:
    """Cuánto cuesta transcribir esto, **antes de hacerlo**.

    Una biblioteca de tres años de llamadas es una factura, no un botón. Y la
    factura llega al mes siguiente, cuando ya no hay nada que decidir.
    """
    coste = round(minutos_totales * coste_por_minuto, 2)
    cabe = presupuesto is None or coste <= presupuesto
    return {
        "minutos": minutos_totales,
        "coste_estimado": coste,
        "cabe_en_el_presupuesto": cabe,
        "se_ejecuta_ya": False,
        "que_hacer": (
            "Revisar el importe y confirmar."
            if cabe
            else f"No cabe: cuesta {coste} y el presupuesto es {presupuesto}. Conviene "
            "elegir qué se transcribe en vez de empezar y quedarse a medias."
        ),
    }


def proponer_extraidos(
    *, elementos: list[dict[str, Any]], confianza_transcripcion: float
) -> dict[str, Any]:
    """Convierte lo extraído en **propuestas**, nunca en tareas creadas.

    «Te mando la oferta el jueves» y «si me la mandas el jueves, la miro» se
    parecen mucho en un texto y significan cosas opuestas. Crear la tarea
    directamente llena la agenda de compromisos que nadie adquirió, y entonces se
    deja de mirar la agenda.

    Lo que viene de una transcripción poco fiable **no se propone siquiera**: una
    propuesta mala también cuesta tiempo, el de leerla y descartarla.
    """
    if confianza_transcripcion < _ia_confianza_transcripcion():
        return {
            "propuestas": [],
            "porque": (
                f"La transcripción tiene una confianza de {round(confianza_transcripcion, 2)} "
                "y no se extrae nada de ella. Una propuesta mala también cuesta tiempo: "
                "el de leerla y descartarla."
            ),
        }

    propuestas: list[dict[str, Any]] = []
    descartados: list[dict[str, Any]] = []
    for elemento in elementos:
        tipo = str(elemento.get("tipo") or "")
        if tipo not in EXTRAIBLES:
            descartados.append(
                {"elemento": elemento.get("texto"), "porque": f"tipo «{tipo}» desconocido"}
            )
            continue
        if not elemento.get("quien"):
            # Un compromiso sin dueño no es un compromiso: es una frase que
            # alguien dijo. Y asignárselo al comercial «por defecto» le llena la
            # agenda de cosas que dijo el cliente.
            descartados.append(
                {
                    "elemento": elemento.get("texto"),
                    "porque": (
                        "no se sabe quién se comprometió, y asignárselo al comercial por "
                        "defecto le llena la agenda de cosas que dijo el cliente"
                    ),
                }
            )
            continue
        propuestas.append(
            {
                "tipo": tipo,
                "texto": elemento.get("texto"),
                "quien": elemento.get("quien"),
                "cuando": elemento.get("cuando"),
                "cita": elemento.get("cita"),
                "estado": "propuesta",
            }
        )

    return {
        "propuestas": propuestas,
        "descartados": descartados,
        "se_crean_solas": False,
        "porque": (
            "Son propuestas. «Te mando la oferta el jueves» y «si me la mandas el "
            "jueves, la miro» se parecen mucho en un texto y significan lo contrario: "
            "lo confirma una persona."
        ),
        "sin_cita": [p["texto"] for p in propuestas if not p.get("cita")],
    }


def confirmar(
    *, propuesta: dict[str, Any], confirmada_por: UUID, corregida: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Una persona confirma —o corrige— la propuesta, y entonces se crea.

    Se guarda **lo que dijo la propuesta y lo que quedó**, porque de las
    correcciones es de donde se aprende si la extracción sirve. Sin ese par, la
    única medida posible de la calidad es la impresión de alguien.
    """
    final = {**propuesta, **(corregida or {})}
    final["estado"] = "confirmada"
    final["confirmada_por"] = str(confirmada_por)
    return {
        "resultado": final,
        "hubo_correccion": bool(corregida),
        "lo_que_propuso_el_modelo": propuesta,
        "porque_se_guardan_las_dos": (
            "De las correcciones se aprende si la extracción sirve. Sin el par, la única "
            "medida de calidad es la impresión de alguien."
        ),
    }


def calidad_de_la_extraccion(*, confirmadas: list[dict[str, Any]]) -> dict[str, Any]:
    """Cuánto hay que corregir de lo que propone el modelo.

    Es el número que decide si esto se sigue usando. Si hay que corregir la mitad,
    no ahorra tiempo: lo cambia de sitio — de escribir a revisar, que cansa más.
    """
    if not confirmadas:
        return {
            "medible": False,
            "porque": (
                "Todavía no se ha confirmado ninguna propuesta. No se puede decir si la "
                "extracción sirve: se puede decir que no se ha usado."
            ),
        }
    corregidas = [c for c in confirmadas if c.get("hubo_correccion")]
    pct = round(len(corregidas) / len(confirmadas) * 100, 1)
    return {
        "medible": True,
        "confirmadas": len(confirmadas),
        "corregidas": len(corregidas),
        "pct_corregidas": pct,
        "merece_la_pena": pct < 40,
        "que_significa": (
            f"Hay que corregir el {pct} % de lo que propone. Por encima del 40 % esto no "
            "ahorra tiempo: lo cambia de sitio, de escribir a revisar, que cansa más."
            if pct >= 40
            else f"Se corrige el {pct} % de las propuestas."
        ),
    }
