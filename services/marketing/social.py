"""Redes sociales: escucha, respuesta y conversión a caso (CRM-04.02.01.06).

Una queja en público no es un caso más: es un caso **con testigos**. Y ahí está
todo lo que hace distinto este canal, porque lo demás —recoger mensajes, abrir un
caso, contestar— ya lo hace la omnicanalidad.

Las decisiones:

**No todo lo que menciona a la marca es un caso.** Convertir cada mención en un
caso llena la cola de comentarios que no piden nada y hace que se dejen de mirar
todos, incluidos los cuatro que sí eran una queja.

**Lo público se contesta en público, y lo demás en privado.** Contestar un
problema concreto en un hilo abierto obliga al cliente a dar datos suyos delante
de todo el mundo; no contestar nada en público deja la queja sola en el hilo, que
es lo que la gente lee.

**El tiempo aquí se mide en minutos.** Una respuesta a las veinticuatro horas en
correo es normal y en una red social es una captura de pantalla circulando.

**Y lo que se publica en nombre de la marca lo escribe una persona.** Una
respuesta automática a una queja pública es lo que convierte un cliente enfadado
en un hilo viral.

Una última, menos obvia: **el contenido de las redes no se copia al CRM más allá
de lo necesario**. Un perfil público sigue siendo dato personal, y traerse su
historial entero «por contexto» es crear una ficha de alguien que nunca nos dio
nada.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from crmcore.errors import ErrorValidacion, Prohibido
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Qué puede ser una mención. Cerrada porque cada una se trata distinto, y con
# texto libre todo acaba siendo «mención» y se trata igual: mal.
TIPOS = ("queja", "pregunta", "elogio", "mencion_neutra", "spam", "crisis")

# Lo que obliga a abrir caso. El elogio y la mención neutra no: convertirlos en
# casos llena la cola de cosas que no piden nada y hace que se dejen de mirar
# todas.
ABREN_CASO = ("queja", "pregunta", "crisis")

# Minutos para la primera respuesta, por tipo. Aquí el tiempo no se mide en
# horas: una respuesta a las veinticuatro horas es una captura de pantalla
# circulando.
MINUTOS_OBJETIVO = {"crisis": 15, "queja": 60, "pregunta": 120}

# Qué se guarda de un perfil público. Corto a propósito: un perfil público sigue
# siendo dato personal, y traerse su historial entero «por contexto» es crear una
# ficha de alguien que nunca nos dio nada.
CAMPOS_DEL_PERFIL = ("usuario", "red", "url_del_mensaje")


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def clasificar(
    *, mencion: dict[str, Any], palabras_de_crisis: list[str] | None = None
) -> dict[str, Any]:
    """Qué es esta mención y si hay que abrir un caso.

    Lo importante no es acertar siempre: es **no convertir todo en un caso**. Un
    «gracias por el envío rápido» no necesita un expediente con SLA, y meterlo en
    la cola hace que el agente aprenda a cerrar sin leer.

    Lo que sí escala solo es lo que se parece a una crisis: no por el volumen de
    una mención, sino porque una sola con las palabras equivocadas ya es un
    problema distinto.
    """
    texto = str(mencion.get("texto") or "").lower()
    tipo = str(mencion.get("tipo") or "")
    if tipo and tipo not in TIPOS:
        raise ErrorValidacion(
            f"Tipo de mención «{tipo}» desconocido",
            error_code="social.tipo_invalido",
            detalle={"admitidos": list(TIPOS)},
        )

    disparadores = [p for p in (palabras_de_crisis or []) if p.lower() in texto]
    if disparadores:
        tipo = "crisis"
    elif not tipo:
        tipo = "mencion_neutra"

    abre = tipo in ABREN_CASO
    # Del autor se guarda LO JUSTO, y se decide aquí y no donde se escriba en la
    # base: `perfil_minimo` estaba escrita, probada y sin que la llamara nadie,
    # así que clasificar una mención devolvía el perfil tal cual venía de la red
    # —biografía, foto, historial— y lo que se guardaba era la ficha completa de
    # alguien que nunca nos dio nada. Esa ficha hay que protegerla, conservarla
    # y borrarla como cualquier otra.
    recorte = perfil_minimo(perfil=dict(mencion.get("autor") or {}))
    return {
        "tipo": tipo,
        "abre_caso": abre,
        "autor": recorte["perfil"],
        "descartado_del_autor": recorte["descartado"],
        "disparadores_de_crisis": disparadores,
        "minutos_objetivo": MINUTOS_OBJETIVO.get(tipo),
        "porque": (
            f"Contiene {', '.join(disparadores)}: esto no es una queja más, y una sola "
            "con esas palabras ya es un problema distinto."
            if disparadores
            else (
                f"Es «{tipo}» y abre caso."
                if abre
                else f"Es «{tipo}»: no abre caso. Convertir cada mención en un caso llena "
                "la cola de cosas que no piden nada y hace que se dejen de mirar todas."
            )
        ),
    }


def responder(
    *,
    tipo: str,
    en_publico: bool,
    texto: str,
    escrito_por_persona: bool,
    pide_datos_personales: bool = False,
) -> dict[str, Any]:
    """Comprueba una respuesta antes de publicarla.

    **Lo que sale en nombre de la marca lo escribe una persona.** Una respuesta
    automática a una queja pública es lo que convierte un cliente enfadado en un
    hilo viral — y la frase «entendemos tu frustración» generada por una máquina se
    reconoce a la primera.

    **Y no se piden datos personales en público.** Obligar a alguien a dar su
    número de pedido delante de todo el mundo es un problema de privacidad y una
    mala respuesta a la vez: lo que se hace es contestar en el hilo que se está
    atendiendo y seguir por privado.
    """
    if not escrito_por_persona and tipo in ("queja", "crisis"):
        raise Prohibido(
            "Una respuesta automática a una queja pública es lo que convierte a un "
            "cliente enfadado en un hilo viral. Esto lo escribe una persona.",
            error_code="social.respuesta_automatica",
        )
    if en_publico and pide_datos_personales:
        raise ErrorValidacion(
            "No se piden datos personales en un hilo público: obligar a alguien a dar su "
            "número de pedido delante de todo el mundo es un problema de privacidad y una "
            "mala respuesta a la vez.",
            error_code="social.datos_en_publico",
        )
    return {
        "texto": texto.strip(),
        "en_publico": en_publico,
        "la_escribio_una_persona": escrito_por_persona,
        "recomendacion": (
            "Contestar en público que se está atendiendo y seguir por privado. Lo "
            "público deja la queja sin respuesta a la vista, y lo privado a secas deja "
            "el hilo solo con la queja, que es lo que la gente lee."
            if en_publico
            else "Seguir por privado, después de haber dicho algo en el hilo."
        ),
    }


def perfil_minimo(*, perfil: dict[str, Any]) -> dict[str, Any]:
    """Qué se guarda del autor de una mención.

    Lo justo para poder contestarle y encontrar el hilo. Un perfil público sigue
    siendo dato personal: traerse su biografía, su foto y su historial «por
    contexto» es crear la ficha de alguien que nunca nos dio nada, y esa ficha hay
    que protegerla, conservarla y borrarla como cualquier otra.
    """
    guardado = {c: perfil.get(c) for c in CAMPOS_DEL_PERFIL if perfil.get(c)}
    descartado = sorted(set(perfil) - set(CAMPOS_DEL_PERFIL))
    return {
        "perfil": guardado,
        "descartado": descartado,
        "porque": (
            "Lo justo para contestar y encontrar el hilo. Un perfil público sigue siendo "
            "dato personal, y traerse su historial entero crea la ficha de alguien que "
            "nunca nos dio nada — y esa ficha hay que protegerla y borrarla como "
            "cualquier otra."
        ),
    }


def tiempos(*, menciones: list[dict[str, Any]], ahora: datetime | None = None) -> dict[str, Any]:
    """Cuánto se está tardando en contestar, por tipo.

    Aquí el tiempo se mide en **minutos**. Una respuesta a las veinticuatro horas
    es normal en correo y en una red social es una captura de pantalla circulando
    con el reloj al lado.

    Y las que **siguen sin contestar** se cuentan aparte de las que tardaron: una
    media de treinta minutos calculada solo sobre las contestadas esconde las
    cinco que nadie ha mirado.
    """
    momento = ahora or _ahora()
    contestadas: list[dict[str, Any]] = []
    sin_contestar: list[dict[str, Any]] = []

    for mencion in menciones:
        recibida = mencion.get("recibida_at")
        if not isinstance(recibida, datetime):
            continue
        respondida = mencion.get("respondida_at")
        tipo = str(mencion.get("tipo") or "mencion_neutra")
        objetivo = MINUTOS_OBJETIVO.get(tipo)
        if isinstance(respondida, datetime):
            minutos = (respondida - recibida).total_seconds() / 60
            contestadas.append(
                {
                    "tipo": tipo,
                    "minutos": round(minutos, 1),
                    "dentro": objetivo is None or minutos <= objetivo,
                }
            )
        elif objetivo is not None:
            esperando = (momento - recibida).total_seconds() / 60
            sin_contestar.append(
                {"tipo": tipo, "esperando_min": round(esperando, 1), "objetivo": objetivo}
            )

    fuera = [c for c in contestadas if not c["dentro"]]
    return {
        "contestadas": len(contestadas),
        "fuera_de_objetivo": len(fuera),
        "sin_contestar": sin_contestar,
        "medible": bool(contestadas or sin_contestar),
        "que_significa": (
            "No hay menciones que exijan respuesta en este periodo."
            if not contestadas and not sin_contestar
            else " ".join(
                filter(
                    None,
                    [
                        f"{len(fuera)} respuestas fuera de objetivo." if fuera else "",
                        f"{len(sin_contestar)} menciones siguen sin contestar: la media "
                        "de las contestadas no las enseña, y son las que acaban en una "
                        "captura de pantalla."
                        if sin_contestar
                        else "",
                    ],
                )
            )
            or "Todo contestado dentro de objetivo.",
        ),
    }


def escalar_crisis(
    *, menciones_por_hora: list[int], umbral_multiplicador: float = 5.0
) -> dict[str, Any]:
    """Si esto ha dejado de ser una queja y es otra cosa.

    Se mira el **cambio de ritmo**, no el número absoluto: veinte menciones a la
    hora pueden ser normales para una marca grande y una señal de incendio para
    una pequeña. Un umbral fijo solo funciona para el tamaño con el que se
    escribió.

    Con pocas horas de historial **no se concluye**: un pico un martes por la
    mañana puede ser un anuncio que salió bien.
    """
    if len(menciones_por_hora) < 6:
        return {
            "hay_crisis": False,
            "medible": False,
            "porque": (
                "Con menos de seis horas de historial no se puede distinguir un incendio "
                "de un anuncio que salió bien."
            ),
        }
    ultima = menciones_por_hora[-1]
    previas = menciones_por_hora[:-1]
    media = sum(previas) / len(previas) if previas else 0
    disparado = media > 0 and ultima >= media * umbral_multiplicador

    return {
        "hay_crisis": disparado,
        "medible": True,
        "ultima_hora": ultima,
        "media_previa": round(media, 1),
        "porque": (
            f"La última hora trae {ultima} menciones frente a una media de "
            f"{round(media, 1)}: es un cambio de ritmo, y eso es lo que importa. Veinte "
            "menciones a la hora son normales para una marca grande y un incendio para "
            "una pequeña, así que el umbral no puede ser un número fijo."
            if disparado
            else "El ritmo está dentro de lo normal para esta marca."
        ),
    }
