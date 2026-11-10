"""Qué valor sobrevive cuando varias fuentes dicen cosas distintas
(CRM-01.01.04.06).

Vivía en `services.party.mdm` y bajó al núcleo el 09-11-2026, cuando el lead
—que vive en `sales`— necesitó la misma ficha buena que la cuenta y el
contacto. Ningún servicio importa a otro, y copiar la decisión habría dejado
dos reglas de supervivencia que dicen cosas distintas el día que una cambie.
Aquí está **la decisión** —qué gana y por qué—; dónde se guardan las reglas y
de dónde salen los candidatos lo pone cada servicio, que es quien conoce sus
fichas.

Las decisiones:

**La regla es por campo y está declarada.** El NIF lo sabe mejor el ERP; el
móvil lo sabe mejor quien acaba de hablar con el cliente.

**«Más reciente» no es cuándo llegó el mensaje, sino cuándo cambió el valor.**
Un ERP que reenvía el maestro entero cada noche trae mil valores «nuevos»
idénticos a los de ayer, y con la fecha de llegada como criterio pisan lo que un
comercial corrigió esta mañana.

**Lo que pierde no se tira: se anota** como discrepancia, porque dos sistemas
que dicen cosas distintas del mismo cliente suelen ser algo que cambió y sólo
uno se enteró.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from crmcore.errors import ErrorValidacion

# Cómo se decide qué valor sobrevive. Lista cerrada: cada una se equivoca de una
# forma distinta, y con texto libre nadie podría decir por qué ganó lo que ganó.
ESTRATEGIAS = (
    "mayor_confianza",  # manda la fuente declarada como más fiable para ese campo
    "mas_reciente",  # el que CAMBIÓ después, no el que llegó después
    "mas_completo",  # entre un valor y un vacío, el valor
    "solo_si_falta",  # la fuente rellena huecos y no pisa nada
    "decide_una_persona",  # para lo que no se puede automatizar sin equivocarse
)

# Lo que escribe una persona no lo pisa ningún proceso automático, salvo que la
# regla diga expresamente lo contrario.
FUENTE_MANUAL = "manual"

# La confianza de una fuente que la regla no nombra.
CONFIANZA_NEUTRA = 50


def momento(candidato: dict[str, Any]) -> datetime:
    """Cuándo cambió el valor **de verdad**; si la fuente no lo dice, cuándo llegó."""
    cambiado = candidato.get("cambiado_at")
    if isinstance(cambiado, datetime):
        return cambiado if cambiado.tzinfo else cambiado.replace(tzinfo=timezone.utc)
    recibido = candidato.get("recibido_at")
    if isinstance(recibido, datetime):
        return recibido if recibido.tzinfo else recibido.replace(tzinfo=timezone.utc)
    return datetime(1970, 1, 1, tzinfo=timezone.utc)


def discrepancias(ganador: dict[str, Any], vivos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Lo que dicen las demás fuentes y no ha ganado."""
    return [
        {
            "fuente": c.get("fuente"),
            "valor": c.get("valor"),
            "porque_importa": (
                "Dos sistemas dicen cosas distintas del mismo cliente. Suele ser que "
                "algo cambió y solo uno se enteró: merece una revisión, no un olvido."
            ),
        }
        for c in vivos
        if str(c.get("valor")) != str(ganador.get("valor"))
    ]


def validar_estrategia(estrategia: str) -> None:
    if estrategia not in ESTRATEGIAS:
        raise ErrorValidacion(
            f"Estrategia de supervivencia «{estrategia}» desconocida",
            error_code="mdm.estrategia_invalida",
            detalle={"admitidas": list(ESTRATEGIAS)},
        )


def validar_confianzas(confianza_por_fuente: dict[str, Any] | None) -> dict[str, int]:
    """`{fuente: 0..100}` limpio, o un error que dice cuál no vale."""
    salida: dict[str, int] = {}
    for fuente, valor in (confianza_por_fuente or {}).items():
        try:
            numero = int(valor)
        except (TypeError, ValueError):
            numero = -1
        if not str(fuente).strip() or not 0 <= numero <= 100:
            raise ErrorValidacion(
                "La confianza de cada fuente va de 0 a 100.",
                error_code="golden.confianza_invalida",
                detalle={"fuente": fuente, "valor": valor},
            )
        salida[str(fuente).strip()] = numero
    return salida


def resolver_valor(
    *,
    campo: str,
    candidatos: list[dict[str, Any]],
    estrategia: str = "mayor_confianza",
    confianza_por_fuente: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Decide qué valor sobrevive para un campo, **y por qué**.

    Cada candidato es `{"fuente", "valor", "cambiado_at", "recibido_at"}`. Lo
    que pierde se devuelve como discrepancia, no se tira.
    """
    validar_estrategia(estrategia)
    vivos = [c for c in candidatos if str(c.get("valor") or "").strip()]
    if not vivos:
        return {
            "valor": None,
            "fuente": None,
            "porque": "Ninguna fuente trae valor para este campo.",
            "discrepancias": [],
            "hay_que_decidir": False,
        }

    confianzas = dict(confianza_por_fuente or {})
    manual = [c for c in vivos if str(c.get("fuente")) == FUENTE_MANUAL]
    if manual and estrategia != "decide_una_persona":
        ganador = max(manual, key=momento)
        return {
            "valor": ganador["valor"],
            "fuente": FUENTE_MANUAL,
            "porque": (
                "Lo escribió una persona. Ningún proceso automático lo pisa: quien "
                "corrige un teléfono a mano está diciendo que el otro estaba mal."
            ),
            "discrepancias": discrepancias(ganador, vivos),
            "hay_que_decidir": False,
        }

    if estrategia == "decide_una_persona":
        distintos = {str(c.get("valor")) for c in vivos}
        return {
            "valor": vivos[0]["valor"] if len(distintos) == 1 else None,
            "fuente": vivos[0].get("fuente") if len(distintos) == 1 else None,
            "hay_que_decidir": len(distintos) > 1,
            "porque": (
                "Todas las fuentes dicen lo mismo."
                if len(distintos) == 1
                else f"«{campo}» está declarado para que lo decida una persona, y hay "
                f"{len(distintos)} valores distintos. Elegir automáticamente aquí es "
                "lo que produce fichas que cambian solas."
            ),
            "opciones": [{"fuente": c.get("fuente"), "valor": c.get("valor")} for c in vivos],
            "discrepancias": [],
        }

    if estrategia == "mas_reciente":
        ganador = max(vivos, key=momento)
        sin_fecha_de_cambio = [c for c in vivos if not isinstance(c.get("cambiado_at"), datetime)]
        porque = f"Es el valor que cambió después ({momento(ganador).date().isoformat()})."
        if sin_fecha_de_cambio:
            porque += (
                " Aviso: hay fuentes que no dicen cuándo cambió el valor, solo cuándo "
                "llegó el mensaje. No es lo mismo: un maestro reenviado cada noche "
                "trae valores idénticos con fecha nueva."
            )
    elif estrategia == "mas_completo":
        ganador = max(vivos, key=lambda c: len(str(c.get("valor") or "")))
        porque = "Entre un valor y uno más pobre, se queda el que trae más información."
    elif estrategia == "solo_si_falta":
        ganador = vivos[0]
        porque = (
            "Esta regla solo rellena huecos: si ya había valor, no se toca. Es la "
            "adecuada para una fuente de enriquecimiento, que sabe de muchos y no "
            "conoce a ninguno."
        )
    else:
        ganador = max(
            vivos,
            key=lambda c: (confianzas.get(str(c.get("fuente")), CONFIANZA_NEUTRA), momento(c)),
        )
        porque = (
            f"«{ganador.get('fuente')}» es la fuente declarada como más fiable para "
            f"«{campo}» (confianza "
            f"{confianzas.get(str(ganador.get('fuente')), CONFIANZA_NEUTRA)})."
        )

    return {
        "valor": ganador["valor"],
        "fuente": ganador.get("fuente"),
        "porque": porque,
        "discrepancias": discrepancias(ganador, vivos),
        "hay_que_decidir": False,
    }


def _serializable(candidato: dict[str, Any]) -> dict[str, Any]:
    cambiado = candidato.get("cambiado_at")
    return {
        "fuente": candidato.get("fuente"),
        "valor": candidato.get("valor"),
        "origen": candidato.get("origen"),
        "cambiado_at": cambiado.isoformat() if isinstance(cambiado, datetime) else None,
    }


def componer_campos(
    campos: dict[str, list[dict[str, Any]]],
    *,
    reglas: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """La ficha buena de un registro con las reglas guardadas del objeto.

    `reglas` es `{campo: {"estrategia", "confianza_por_fuente"}}`, con `*` como
    la regla por defecto del objeto. La confianza del campo se suma encima de
    la del objeto: un tenant dice una vez que el ERP manda y sólo corrige el
    campo que lo desmiente.

    Devuelve `valores`, `procedencia` (qué fuente ganó cada campo, con qué
    regla, por qué y entre qué candidatos), `a_revisar` y `fuentes` (cuántos
    valores aportó cada una).
    """
    por_defecto = reglas.get("*")
    valores: dict[str, Any] = {}
    procedencia: dict[str, Any] = {}
    a_revisar: list[dict[str, Any]] = []
    fuentes: dict[str, int] = {}
    for campo, lista in campos.items():
        regla = reglas.get(campo) or por_defecto
        confianzas = dict((por_defecto or {}).get("confianza_por_fuente") or {})
        if regla is not None:
            confianzas.update(regla.get("confianza_por_fuente") or {})
        estrategia = str((regla or {}).get("estrategia") or "mayor_confianza")
        salida = resolver_valor(
            campo=campo,
            candidatos=lista,
            estrategia=estrategia,
            confianza_por_fuente=confianzas,
        )
        for c in lista:
            fuentes[str(c["fuente"])] = fuentes.get(str(c["fuente"]), 0) + 1
        valores[campo] = salida["valor"]
        procedencia[campo] = {
            "fuente": salida["fuente"],
            "estrategia": estrategia,
            "regla": (
                "propia del campo"
                if campo in reglas and campo != "*"
                else ("por defecto del objeto" if por_defecto else "sin regla: mayor confianza")
            ),
            "porque": salida["porque"],
            "candidatos": [_serializable(c) for c in lista],
        }
        if salida["discrepancias"] or salida["hay_que_decidir"]:
            a_revisar.append(
                {
                    "campo": campo,
                    "hay_que_decidir": salida["hay_que_decidir"],
                    "discrepancias": salida["discrepancias"],
                    "opciones": salida.get("opciones", []),
                }
            )
    return {
        "valores": valores,
        "procedencia": procedencia,
        "a_revisar": a_revisar,
        "fuentes": fuentes,
    }
