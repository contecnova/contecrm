"""Coste real frente a coste ofertado (CRM-09.02.01.10).

El margen de una oferta es una previsión. El margen de verdad se sabe cuando llega
la factura del proveedor, y casi nadie vuelve a mirarlo — por eso las empresas
descubren que un tipo de trabajo pierde dinero después de haberlo vendido veinte
veces.

Las decisiones:

**Se compara por pedido, no en agregado.** Una media que dice «desviación del 3 %»
esconde diez pedidos clavados y uno que se fue al 40 %, y el que se fue es el
único que enseña algo.

**Y se dice dónde se fue la diferencia**, no solo cuánta fue. «El coste subió»
no sirve para nada; «subió en el transporte de las entregas fuera de la
península» cambia la próxima oferta.

**Lo que no se ha facturado todavía no cuenta como acertado.** Es el error que
hace que estos informes mientan siempre en la misma dirección: los pedidos que
todavía no han cerrado se cuentan por su coste previsto y bajan la desviación
media justo cuando aún puede empeorar.

**Vive en `crmcore` y no en un servicio porque no lee nada**: recibe los
pedidos y devuelve la cuenta. Estuvo en `analytics`, que es donde se escribió,
y ahí se quedó sin poder usarse — quien tiene los encargos es `integration`, y
un servicio no lee la base de otro. Era una calculadora que publicaba su ruta
y a la que **nadie podía alimentar**: la ofrecía justo quien no tenía los
datos.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from crmcore.logging import get_logger

logger = get_logger(__name__)

# A partir de qué desviación se mira un pedido de cerca. No es un umbral de
# alarma: es el corte que separa el ruido de lo que merece una conversación.
DESVIACION_RELEVANTE_PCT = Decimal("10")


def _pct(numerador: Decimal, denominador: Decimal) -> Decimal:
    if denominador == 0:
        return Decimal(0)
    return (numerador / denominador * Decimal(100)).quantize(Decimal("0.01"))


def desviacion(*, pedidos: list[dict[str, Any]]) -> dict[str, Any]:
    """Coste ofertado contra coste real, pedido a pedido.

    Los que **aún no tienen coste real se apartan**, no se cuentan como acertados.
    Contarlos por su coste previsto es lo que hace que estos informes mientan
    siempre hacia el mismo lado: la desviación media sale baja justo mientras
    todavía puede empeorar.
    """
    cerrados = [p for p in pedidos if p.get("coste_real") is not None]
    abiertos = [p for p in pedidos if p.get("coste_real") is None]

    if not cerrados:
        return {
            "medible": False,
            "pedidos_sin_coste_real": len(abiertos),
            "porque": (
                "Ningún pedido tiene todavía coste real. Eso no es que no haya "
                "desviación: es que aún no se sabe, y contarlos por el previsto haría "
                "que el informe dijera que todo va bien."
            ),
        }

    filas: list[dict[str, Any]] = []
    for pedido in cerrados:
        ofertado = Decimal(str(pedido.get("coste_ofertado") or 0))
        real = Decimal(str(pedido.get("coste_real")))
        diferencia = real - ofertado
        filas.append(
            {
                "pedido": pedido.get("referencia"),
                "proveedor_id": str(pedido.get("proveedor_id"))
                if pedido.get("proveedor_id")
                else None,
                "coste_ofertado": str(ofertado),
                "coste_real": str(real),
                "desviacion": str(diferencia),
                "desviacion_pct": str(_pct(diferencia, ofertado)),
                "donde": pedido.get("concepto_de_la_desviacion") or "",
            }
        )

    total_ofertado = sum((Decimal(f["coste_ofertado"]) for f in filas), Decimal(0))
    total_real = sum((Decimal(f["coste_real"]) for f in filas), Decimal(0))
    relevantes = [f for f in filas if abs(Decimal(f["desviacion_pct"])) >= DESVIACION_RELEVANTE_PCT]
    sin_explicar = [f for f in relevantes if not f["donde"]]

    return {
        "medible": True,
        "pedidos": len(filas),
        "pedidos_sin_coste_real": len(abiertos),
        "coste_ofertado": str(total_ofertado),
        "coste_real": str(total_real),
        "desviacion_total": str(total_real - total_ofertado),
        "desviacion_pct": str(_pct(total_real - total_ofertado, total_ofertado)),
        # Los individuales, que es donde está la información: una media del 3 %
        # esconde diez pedidos clavados y uno que se fue al 40 %.
        "los_que_se_fueron": sorted(relevantes, key=lambda f: -abs(Decimal(f["desviacion_pct"]))),
        "sin_explicacion": [f["pedido"] for f in sin_explicar],
        "que_mirar": (
            "Ningún pedido se ha desviado de forma llamativa."
            if not relevantes
            else f"{len(relevantes)} pedidos se han desviado más del "
            f"{DESVIACION_RELEVANTE_PCT} %. La media no los enseña, y son los únicos que "
            "cambian la próxima oferta."
        ),
        "aviso": (
            ""
            if not sin_explicar
            else f"{len(sin_explicar)} desviaciones no dicen dónde se fue la diferencia. "
            "«El coste subió» no sirve para nada: «subió en el transporte de las "
            "entregas fuera de la península» cambia lo que se oferta la próxima vez."
        ),
    }


def por_proveedor(*, pedidos: list[dict[str, Any]]) -> dict[str, Any]:
    """Qué proveedor se desvía sistemáticamente de lo que presupuesta.

    Uno que siempre acaba costando un 15 % más no es caro: es **impreciso**, y eso
    es peor, porque sus ofertas no sirven para decidir. Es una conversación
    distinta de la del precio y hay que poder tenerla con números.

    Con menos de tres pedidos **no se concluye**: dos desviaciones seguidas pueden
    ser dos casualidades, y colgarle a alguien la etiqueta de impreciso por eso es
    injusto y además hace que nadie se crea el informe.
    """
    por_id: dict[str, list[dict[str, Any]]] = {}
    for pedido in pedidos:
        if pedido.get("coste_real") is None or not pedido.get("proveedor_id"):
            continue
        por_id.setdefault(str(pedido["proveedor_id"]), []).append(pedido)

    salida: list[dict[str, Any]] = []
    for proveedor_id, suyos in por_id.items():
        ofertado = sum((Decimal(str(p.get("coste_ofertado") or 0)) for p in suyos), Decimal(0))
        real = sum((Decimal(str(p["coste_real"])) for p in suyos), Decimal(0))
        salida.append(
            {
                "proveedor_id": proveedor_id,
                "pedidos": len(suyos),
                "desviacion_pct": str(_pct(real - ofertado, ofertado)),
                "concluyente": len(suyos) >= 3,
                "porque": (
                    f"Solo {len(suyos)} pedidos medidos: dos desviaciones seguidas "
                    "pueden ser dos casualidades."
                    if len(suyos) < 3
                    else f"{len(suyos)} pedidos medidos."
                ),
            }
        )

    concluyentes = [s for s in salida if s["concluyente"]]
    return {
        "proveedores": sorted(salida, key=lambda s: -abs(Decimal(s["desviacion_pct"]))),
        "medible": bool(concluyentes),
        "que_significa": (
            "Todavía no hay suficientes pedidos medidos de ningún proveedor para " "concluir nada."
            if not concluyentes
            else "Un proveedor que siempre acaba costando más no es caro: es impreciso, "
            "y sus ofertas no sirven para decidir. Es otra conversación, y con números."
        ),
    }
