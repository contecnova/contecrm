"""Variantes de texto con revisión humana (CRM-02.04.01.04).

Generar cinco versiones de un asunto de correo es de lo más barato que hace un
modelo y de lo que más se agradece: escribir la sexta variante a mano un viernes
por la tarde no lo hace nadie, y por eso se manda siempre la primera que salió.

Lo que hay que resolver no es generar, es **qué pasa con lo generado**:

**Nada sale sin que una persona lo apruebe.** No por desconfianza en el modelo: es
que un texto comercial lleva el nombre de la empresa, y el que lo firma tiene que
haberlo leído. Además, la responsabilidad de lo que se dice no se delega en una
herramienta.

**Las afirmaciones comprobables se marcan.** «El más rápido del mercado» o «un 40 %
más barato» no son estilo: son afirmaciones que alguien tiene que poder sostener, y
un modelo las inventa con total naturalidad. Se señalan para que el revisor no las
lea por encima.

**La variante ganadora se elige con datos o no se elige.** Con doscientos envíos
por rama, la diferencia entre un 4,1 % y un 4,4 % es ruido: declararla ganadora es
convertir el azar en una decisión de marca.

**Y queda dicho qué generó el modelo y qué escribió la persona.** Sin ese par no
se puede saber si esto ayuda o si todo se reescribe igualmente.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.errors import ErrorValidacion, Prohibido
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Patrones de afirmación comprobable. No pretende ser exhaustivo —ninguna lista lo
# es— y por eso se llama «marcar» y no «validar»: señala lo evidente para que el
# revisor no lo lea por encima.
AFIRMACIONES = (
    (re.compile(r"\b\d+\s?%", re.I), "un porcentaje concreto"),
    (
        re.compile(r"\bel m[áa]s\b|\blíder\b|\bnúmero uno\b|\bmejor del mercado\b", re.I),
        "una superioridad",
    ),
    (re.compile(r"\bgarantiza\w*\b|\basegura\w*\b|\b100\s?%\b", re.I), "una garantía"),
    (re.compile(r"\bcertificad\w+\b|\bhomologad\w+\b|\bISO\s?\d+", re.I), "una certificación"),
    (re.compile(r"\bgratis\b|\bsin coste\b|\bsin compromiso\b", re.I), "una gratuidad"),
)

ESTADOS = ("propuesta", "aprobada", "rechazada", "publicada")


# Envíos mínimos por rama para declarar una ganadora. Por debajo, la diferencia
# cabe entera en el ruido.
def _ia_minimo_por_rama() -> float:
    """Envíos mínimos por rama para dar una prueba A/B por concluyente.

    Sin `db` a propósito: esto se calcula en una función pura y meterle una
    sesión para leer un número sería pagar una consulta por llamada. Sale del
    `.env`, o sea de la configuración del despliegue.
    """
    from services.intelligence.ajustes import ajustes

    return ajustes().ia_minimo_por_rama


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def marcar_afirmaciones(texto: str) -> dict[str, Any]:
    """Señala lo que alguien va a tener que sostener.

    Un modelo escribe «un 40 % más rápido» con la misma naturalidad con la que
    escribe «buenos días», y el revisor que lee deprisa no distingue lo uno de lo
    otro. Marcarlo es lo único que hace que se lea despacio la frase que importa.
    """
    encontradas: list[dict[str, str]] = []
    for patron, que_es in AFIRMACIONES:
        for encaje in patron.finditer(texto):
            encontradas.append({"texto": encaje.group(0), "es": que_es})
    return {
        "afirmaciones": encontradas,
        "hay": bool(encontradas),
        "que_hacer": (
            ""
            if not encontradas
            else "Comprobar cada una antes de aprobar. Un modelo las inventa con total "
            "naturalidad, y quien firma el correo es quien las sostiene."
        ),
    }


def proponer_variantes(*, base: str, textos: list[str], canal: str) -> dict[str, Any]:
    """Registra las variantes generadas **como propuestas**.

    Ninguna sale sin que alguien la apruebe. No es desconfianza en el modelo: es
    que el texto lleva el nombre de la empresa, y la responsabilidad de lo que
    dice no se delega en una herramienta.
    """
    if not textos:
        raise ErrorValidacion("No hay variantes que registrar", error_code="variantes.vacio")
    limpios = [t.strip() for t in textos if t.strip()]
    repetidas = len(limpios) - len({t.lower() for t in limpios})

    return {
        "base": base,
        "canal": canal,
        "variantes": [
            {
                "texto": texto,
                "estado": "propuesta",
                **marcar_afirmaciones(texto),
            }
            for texto in limpios
        ],
        "repetidas": repetidas,
        "ninguna_sale_sin_aprobar": True,
        "aviso": (
            ""
            if not repetidas
            else f"{repetidas} variantes son iguales que otras. Presentar cinco opciones "
            "de las que dos son la misma hace perder el tiempo de quien revisa."
        ),
        "propuestas_at": _ahora().isoformat(),
    }


def aprobar(
    *, texto_propuesto: str, texto_final: str, aprobada_por: UUID, sin_leer: bool = False
) -> dict[str, Any]:
    """Una persona aprueba —o reescribe— la variante.

    `sin_leer` existe para poder rechazarlo: una aprobación masiva sin abrir los
    textos es exactamente lo que este paso existe para impedir, y hacerla posible
    «por comodidad» la convierte en la única que se usa.
    """
    if sin_leer:
        raise Prohibido(
            "No hay aprobación en bloque sin leer. El texto lleva el nombre de la "
            "empresa, y quien lo firma tiene que haberlo leído — permitirlo «por "
            "comodidad» lo convertiría en la única forma que se usa.",
            error_code="variantes.aprobacion_ciega",
        )
    cambiado = texto_propuesto.strip() != texto_final.strip()
    return {
        "texto": texto_final,
        "estado": "aprobada",
        "aprobada_por": str(aprobada_por),
        "hubo_reescritura": cambiado,
        "lo_que_propuso_el_modelo": texto_propuesto,
        "porque_se_guarda": (
            "Sin el par «lo que propuso» y «lo que salió» no se puede saber si esto "
            "ayuda o si se reescribe todo igualmente."
        ),
        **marcar_afirmaciones(texto_final),
    }


def elegir_ganadora(*, ramas: list[dict[str, Any]]) -> dict[str, Any]:
    """Qué variante gana, **o que todavía no se sabe**.

    Con doscientos envíos por rama, la diferencia entre un 4,1 % y un 4,4 % es
    ruido. Declararla ganadora convierte el azar en una decisión de marca que
    luego se repite durante dos años porque «los datos lo decían».
    """
    medibles = [r for r in ramas if int(r.get("enviados") or 0) > 0]
    if not medibles:
        return {"hay_ganadora": False, "porque": "Ninguna variante se ha enviado todavía."}

    for rama in medibles:
        rama["tasa"] = int(rama.get("respuestas") or 0) / int(rama["enviados"])

    menor = min(int(r["enviados"]) for r in medibles)
    ordenadas = sorted(medibles, key=lambda r: -r["tasa"])
    mejor, resto = ordenadas[0], ordenadas[1:]
    diferencia = mejor["tasa"] - resto[0]["tasa"] if resto else mejor["tasa"]

    concluyente = menor >= _ia_minimo_por_rama() and diferencia >= 0.01
    return {
        "hay_ganadora": concluyente,
        "mejor": {"texto": mejor.get("texto"), "tasa": round(mejor["tasa"] * 100, 2)},
        "ramas": [
            {"texto": r.get("texto"), "tasa": round(r["tasa"] * 100, 2), "enviados": r["enviados"]}
            for r in ordenadas
        ],
        "porque": (
            f"La rama más pequeña tiene {menor} envíos y hacen falta {_ia_minimo_por_rama()}: "
            "la diferencia cabe entera dentro del ruido."
            if menor < _ia_minimo_por_rama()
            else (
                f"Gana por {round(diferencia * 100, 2)} puntos con {menor} envíos por " "rama."
                if concluyente
                else "Las variantes empatan dentro del margen. Elegir una es elegir al "
                "azar, y repetirla dos años porque «los datos lo decían» es peor que no "
                "haber probado."
            )
        ),
    }


def rendimiento_de_la_generacion(*, aprobaciones: list[dict[str, Any]]) -> dict[str, Any]:
    """Cuánto se reescribe de lo que propone el modelo.

    Es el número que dice si esto ahorra tiempo. Si se reescribe casi todo, lo que
    hace el modelo es dar un punto de partida —que también vale— pero no es lo que
    se vendió, y conviene no confundirlo.
    """
    if not aprobaciones:
        return {
            "medible": False,
            "porque": "No se ha aprobado ninguna variante todavía.",
        }
    reescritas = [a for a in aprobaciones if a.get("hubo_reescritura")]
    pct = round(len(reescritas) / len(aprobaciones) * 100, 1)
    return {
        "medible": True,
        "aprobadas": len(aprobaciones),
        "reescritas": len(reescritas),
        "pct_reescritas": pct,
        "que_significa": (
            f"Se reescribe el {pct} % de lo que propone el modelo. Sigue sirviendo como "
            "punto de partida, pero no es «escribir por ti»: conviene no confundirlo al "
            "contarlo."
            if pct >= 70
            else f"Se reescribe el {pct} % de lo propuesto."
        ),
    }
