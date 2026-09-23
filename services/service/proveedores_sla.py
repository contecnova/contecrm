"""El acuerdo de servicio del proveedor frente al que prometemos
(CRM-09.01.01.08).

Cuando quien da el servicio es un proveedor, el compromiso que se le firma al
cliente **no puede ser mejor que el que sostiene el proveedor**. Parece obvio y se
incumple constantemente: comercial promete cuatro horas de respuesta porque es lo
que pide el pliego, y el proveedor que va a ir tiene contratadas ocho.

Nadie miente. Simplemente **nadie compara los dos documentos**, porque están en
sitios distintos y los firma gente distinta. Eso es lo que hace esto: compararlos
antes de firmar y decir exactamente por cuánto no cuadra.

Y una segunda cosa, menos evidente: **los tiempos se suman**. Si el proveedor
responde en cuatro horas y hacen falta dos más para coordinar y desplazar, lo que
se le puede prometer al cliente son seis. Prometer las cuatro del proveedor es
prometer un tiempo que solo existiría si nosotros no hiciéramos nada.
"""

from __future__ import annotations

from typing import Any

from crmcore.errors import ErrorValidacion
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Qué se compara. Cerrada porque cada métrica se mide distinto, y la que falta en
# la lista es la que nadie compara.
METRICAS = ("respuesta_h", "resolucion_h", "disponibilidad_pct", "cobertura_horaria")

# Lo que tardamos nosotros en medio: coordinar, abrir el parte, desplazar. No es
# un colchón inventado, es tiempo real que hay que sumar.
HORAS_PROPIAS_POR_DEFECTO = 1.0


def comparar(
    *,
    prometido_al_cliente: dict[str, Any],
    del_proveedor: dict[str, Any],
    horas_propias: float = HORAS_PROPIAS_POR_DEFECTO,
) -> dict[str, Any]:
    """Compara lo que se le promete al cliente con lo que sostiene el proveedor.

    Devuelve **todos** los incumplimientos, no el primero: quien está revisando un
    pliego necesita ver las tres cosas que no cuadran de una vez, porque con ellas
    negocia una sola conversación en vez de tres.

    Y lo que no consta **no se da por bueno**: un proveedor que no declara su
    tiempo de resolución no es que lo tenga bien, es que no lo ha dicho — y
    firmarlo así es firmar sin saber.
    """
    problemas: list[dict[str, Any]] = []
    sin_declarar: list[str] = []

    for metrica in METRICAS:
        prometido = prometido_al_cliente.get(metrica)
        if prometido is None:
            continue
        soportado = del_proveedor.get(metrica)
        if soportado is None:
            sin_declarar.append(metrica)
            continue

        if metrica.endswith("_h"):
            # Tiempos: el nuestro tiene que ser MAYOR que el suyo más lo que
            # tardamos en medio. Prometer su mismo tiempo es prometer uno que
            # solo existiría si nosotros no hiciéramos nada.
            necesario = float(soportado) + horas_propias
            if float(prometido) < necesario:
                problemas.append(
                    {
                        "metrica": metrica,
                        "prometido": prometido,
                        "del_proveedor": soportado,
                        "hace_falta_al_menos": necesario,
                        "porque": (
                            f"Se prometen {prometido} h y el proveedor sostiene "
                            f"{soportado} h; sumando {horas_propias} h de coordinación y "
                            f"desplazamiento hacen falta {necesario} h. La diferencia no "
                            "la absorbe nadie: la paga el incumplimiento."
                        ),
                    }
                )
        elif metrica == "disponibilidad_pct":
            if float(prometido) > float(soportado):
                problemas.append(
                    {
                        "metrica": metrica,
                        "prometido": prometido,
                        "del_proveedor": soportado,
                        "porque": (
                            f"Se promete un {prometido} % sobre una infraestructura que "
                            f"garantiza un {soportado} %. La diferencia es optimismo "
                            "contractual."
                        ),
                    }
                )
        elif str(prometido) != str(soportado) and str(soportado) != "24x7":
            problemas.append(
                {
                    "metrica": metrica,
                    "prometido": prometido,
                    "del_proveedor": soportado,
                    "porque": (
                        f"Se promete cobertura «{prometido}» y el proveedor cubre "
                        f"«{soportado}». Lo que pase fuera de su horario lo cubre quien "
                        "lo firmó, que somos nosotros."
                    ),
                }
            )

    return {
        "se_sostiene": not problemas and not sin_declarar,
        "problemas": problemas,
        "sin_declarar_por_el_proveedor": sin_declarar,
        "veredicto": (
            "Lo que se le promete al cliente lo sostiene el proveedor con margen."
            if not problemas and not sin_declarar
            else "Hay compromisos que el proveedor no sostiene. Nadie miente: es que "
            "los dos documentos están en sitios distintos y los firma gente distinta."
        ),
        "aviso": (
            ""
            if not sin_declarar
            else f"El proveedor no declara {', '.join(sin_declarar)}. Eso no es que lo "
            "tenga bien: es que no lo ha dicho, y firmarlo así es firmar sin saber."
        ),
    }


def maximo_que_se_puede_prometer(
    *, del_proveedor: dict[str, Any], horas_propias: float = HORAS_PROPIAS_POR_DEFECTO
) -> dict[str, Any]:
    """Lo mejor que se puede firmar con este proveedor detrás.

    Sirve para la conversación al revés: en vez de comprobar un pliego ya escrito,
    decirle al comercial qué puede ofrecer **antes** de escribirlo. Es más barato
    que descubrirlo en la revisión legal, y mucho más que descubrirlo en la
    primera incidencia.
    """
    if not del_proveedor:
        raise ErrorValidacion(
            "No consta el acuerdo del proveedor. Sin él no se puede decir qué se puede "
            "prometer: se puede adivinar, que es lo que se hace ahora y lo que este "
            "módulo existe para evitar.",
            error_code="sla.proveedor_sin_acuerdo",
        )
    salida: dict[str, Any] = {}
    for metrica, valor in del_proveedor.items():
        if metrica.endswith("_h"):
            salida[metrica] = float(valor) + horas_propias
        else:
            salida[metrica] = valor
    return {
        "maximo": salida,
        "horas_propias_incluidas": horas_propias,
        "porque": (
            "A lo que sostiene el proveedor se le suma lo que tardamos nosotros en "
            "coordinar y desplazar. Prometer su mismo tiempo es prometer uno que solo "
            "existiría si nosotros no hiciéramos nada."
        ),
    }
