"""Motor externo de compensación (CRM-03.02.03.04).

Calcular comisiones dentro del CRM funciona hasta el primer plan de verdad:
aceleradores por tramo, topes, garantías los primeros meses, clawback si el
cliente se va antes de un año, repartos entre equipos y reglas que cambian a
mitad de año con efecto retroactivo. Eso no es un cálculo, es un producto — y hay
empresas que lo fabrican.

Lo que tiene que hacer bien el CRM no es calcular: es **dar los hechos y aceptar
el resultado sin discutirlo**. Y ahí están los tres problemas:

**Lo que se manda es el hecho, no la comisión.** Si el CRM envía un importe ya
calculado «para ayudar», acaba habiendo dos cálculos y la nómina se hace con el
que no es. Se manda qué se cerró, cuándo, de quién y con qué reparto.

**El cálculo llega de vuelta y no se recalcula aquí.** Enseñar en el CRM una
comisión distinta de la que va a cobrar es la forma más rápida de que nadie se
crea ninguna de las dos.

**Y un cierre que cambia después obliga a decirlo, no a corregirlo en silencio.**
Un importe que baja o un pedido que se anula pueden cambiar una comisión ya
pagada: eso se llama clawback y es una conversación, no un ajuste.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from crmcore.errors import Conflicto, ErrorValidacion
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Qué hechos se le mandan al motor. Cerrada porque cada uno tiene su tratamiento
# allí, y mandar un tipo que no conoce hace que lo ignore en silencio — y la
# comisión sale de menos sin que nadie vea un error.
HECHOS = ("cierre", "anulacion", "modificacion_importe", "cobro", "devolucion")

# Lo que NO se manda: el importe de la comisión. Si se mandara, habría dos
# cálculos y la nómina se haría con el que no es.
NO_SE_MANDA = ("comision", "porcentaje_comision", "importe_a_pagar")

ESTADOS = ("pendiente", "enviado", "calculado", "pagado", "revertido")


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def componer_hecho(
    *,
    tipo: str,
    referencia: str,
    fecha: date,
    importe: Decimal,
    moneda: str,
    reparto: list[dict[str, Any]],
    datos: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Prepara el hecho que se manda al motor, **sin la comisión dentro**.

    El reparto sí va —es información del CRM, que es quien sabe quién vendió qué—
    y el cálculo no. Mandar un importe ya calculado «para ayudar» produce dos
    cifras, y la nómina se hace con la que no es.
    """
    if tipo not in HECHOS:
        raise ErrorValidacion(
            f"Hecho «{tipo}» desconocido",
            error_code="compensacion.hecho_invalido",
            detalle={"admitidos": list(HECHOS)},
        )
    colados = sorted(set(datos or {}) & set(NO_SE_MANDA))
    if colados:
        raise ErrorValidacion(
            f"No se manda el cálculo de la comisión: {', '.join(colados)}. Si va dentro, "
            "habrá dos cálculos y la nómina se hará con el que no es.",
            error_code="compensacion.no_se_manda_el_calculo",
        )
    suma = sum(Decimal(str(r.get("porcentaje") or 0)) for r in reparto)
    if reparto and suma != Decimal(100):
        raise ErrorValidacion(
            f"El reparto suma {suma} y tiene que sumar 100: un descuadre aquí se "
            "convierte en una nómina mal calculada.",
            error_code="compensacion.reparto_descuadrado",
        )

    return {
        "tipo": tipo,
        "referencia": referencia,
        "fecha": fecha.isoformat(),
        "importe": str(importe),
        "moneda": moneda,
        "reparto": [
            {"usuario_id": str(r.get("usuario_id")), "porcentaje": str(r.get("porcentaje"))}
            for r in reparto
        ],
        "datos": dict(datos or {}),
        "lleva_comision": False,
        "porque": (
            "El CRM manda los hechos —qué se cerró, cuándo, de quién y con qué reparto— "
            "y el motor calcula. Dos cálculos es peor que ninguno."
        ),
        "compuesto_at": _ahora().isoformat(),
    }


def recibir_calculo(
    *, referencia: str, lineas: list[dict[str, Any]], periodo: str, cerrado: bool
) -> dict[str, Any]:
    """Recoge lo que ha calculado el motor, **tal cual**.

    No se recalcula ni se redondea: enseñar en el CRM una comisión distinta de la
    que se va a cobrar es la forma más rápida de que nadie se crea ninguna de las
    dos, y de que el comercial se haga su propia hoja de cálculo — que es donde
    empieza cualquier discusión de comisiones.

    Un periodo **no cerrado** se enseña como provisional. Es lo que evita la
    conversación de «pero si el CRM decía otra cosa» a final de mes.
    """
    if not lineas:
        return {
            "referencia": referencia,
            "medible": False,
            "porque": (
                "El motor no ha devuelto ninguna línea para esta referencia. No es cero: "
                "es que no consta cálculo, y puede ser que el hecho no le llegara."
            ),
        }
    total = sum(Decimal(str(x.get("importe") or 0)) for x in lineas)
    return {
        "referencia": referencia,
        "periodo": periodo,
        "lineas": lineas,
        "total": str(total),
        "provisional": not cerrado,
        "se_recalcula_aqui": False,
        "porque": (
            "Es el número del motor, tal cual. Enseñar aquí otro distinto del que se va "
            "a cobrar hace que nadie se crea ninguno de los dos."
            + (" El periodo no está cerrado, así que esto puede cambiar." if not cerrado else "")
        ),
    }


def cambio_despues_de_pagar(
    *,
    referencia: str,
    importe_original: Decimal,
    importe_nuevo: Decimal,
    ya_pagada: bool,
    motivo: str,
) -> dict[str, Any]:
    """Qué hacer cuando un cierre cambia después de haberse pagado la comisión.

    Se llama **clawback** y es una conversación, no un ajuste automático. Quitarle
    dinero a alguien de la próxima nómina sin decírselo es lo que hace que un
    equipo comercial deje de confiar en el sistema — y con razón.

    Lo que hace el CRM es **avisar con los números delante**: qué cambió, cuánto y
    por qué. Quién decide es otra persona.
    """
    if not motivo.strip():
        raise ErrorValidacion(
            "Un cambio que afecta a una comisión pagada necesita motivo: sin él, la "
            "conversación con el comercial empieza sin nada que enseñar.",
            error_code="compensacion.cambio_sin_motivo",
        )
    diferencia = Decimal(str(importe_nuevo)) - Decimal(str(importe_original))
    if ya_pagada and diferencia < 0:
        return {
            "hay_clawback": True,
            "referencia": referencia,
            "diferencia": str(diferencia),
            "motivo": motivo.strip(),
            "se_ajusta_solo": False,
            "que_hacer": (
                "Avisar y hablarlo. Quitarle dinero a alguien de la próxima nómina sin "
                "decírselo es lo que hace que un equipo deje de confiar en el sistema — "
                "y con razón."
            ),
        }
    return {
        "hay_clawback": False,
        "referencia": referencia,
        "diferencia": str(diferencia),
        "se_ajusta_solo": False,
        "que_hacer": (
            "Se manda el hecho al motor y él recalcula en el periodo que toque."
            if diferencia
            else "No cambia nada."
        ),
    }


def conciliar(
    *, hechos_enviados: list[dict[str, Any]], calculos_recibidos: list[dict[str, Any]]
) -> dict[str, Any]:
    """Qué se mandó y no ha vuelto, que es donde está el problema de verdad.

    Un hecho que se pierde por el camino no da ningún error: simplemente esa venta
    no aparece en la comisión de nadie, y lo descubre el comercial al mirar su
    nómina. Se comprueba antes de cerrar el periodo, que es el único momento en el
    que todavía se puede arreglar sin que duela.
    """
    enviadas = {str(h.get("referencia")) for h in hechos_enviados}
    calculadas = {str(c.get("referencia")) for c in calculos_recibidos}
    sin_volver = sorted(enviadas - calculadas)
    de_mas = sorted(calculadas - enviadas)

    return {
        "enviados": len(enviadas),
        "calculados": len(calculadas),
        "sin_calculo": sin_volver,
        "calculados_sin_hecho": de_mas,
        "cuadra": not sin_volver and not de_mas,
        "que_significa": (
            "Todo lo enviado ha vuelto calculado."
            if not sin_volver and not de_mas
            else " ".join(
                filter(
                    None,
                    [
                        f"{len(sin_volver)} ventas enviadas no han vuelto con cálculo: "
                        "no dan ningún error, simplemente no aparecen en la comisión de "
                        "nadie, y lo descubre el comercial en su nómina."
                        if sin_volver
                        else "",
                        f"{len(de_mas)} cálculos que no corresponden a nada que hayamos "
                        "mandado: alguien los ha metido a mano en el motor, y eso hay "
                        "que saberlo."
                        if de_mas
                        else "",
                    ],
                )
            )
        ),
    }


def exigir_periodo_abierto(*, periodo_cerrado: bool, referencia: str) -> None:
    """No se mandan hechos a un periodo ya cerrado.

    El motor los aceptaría y los metería en el siguiente, o los descartaría según
    cómo esté configurado: las dos cosas pasan en silencio y las dos acaban en una
    comisión que no cuadra con lo que el comercial cree que vendió.
    """
    if periodo_cerrado:
        raise Conflicto(
            f"El periodo de «{referencia}» está cerrado. Mandarlo igual haría que el "
            "motor lo metiera en el siguiente o lo descartara —según cómo esté "
            "configurado—, y las dos cosas pasan en silencio.",
            error_code="compensacion.periodo_cerrado",
        )
