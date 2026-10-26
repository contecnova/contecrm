"""Lo que la IA le sugiere a una persona mientras trabaja
(CRM-04.02.02.05, CRM-04.03.02.02, CRM-01.01.05.05, CRM-03.01.02.04).

Todo lo de aquí acaba delante de alguien que está en mitad de otra cosa: un
agente de soporte con el cliente esperando, un comercial abriendo una ficha. Eso
cambia lo que hay que cuidar: no es la calidad media de la sugerencia, es **qué
pasa con la mala**. Una sugerencia mala que parece buena se manda tal cual,
porque quien la lee está ocupado.

Las decisiones:

**Se sugiere, no se manda.** Todo sale como propuesta, con el mismo mecanismo que
el resto de lo generado: lo aplica una persona y queda contado si lo usó o lo
tiró — que es el número con el que se decide si esto sirve.

**Lo que se apoya en datos cita, y si no puede citar no contesta.** Un párrafo
perfecto sin fuente es exactamente lo que produce un modelo cuando no encontró
nada.

**El resumen de cuenta separa lo que consta de lo que interpreta.** Un riesgo
inventado en un resumen de cuenta acaba en una reunión con el cliente.

**Lo que aún no se sabe se dice.** Sin señales suficientes, la salud y los
próximos pasos salen como «no concluyente» en vez de como una recomendación
tibia que nadie sabe si seguir.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import ErrorValidacion
from crmcore.logging import get_logger

from services.intelligence import generacion, rag

logger = get_logger(__name__)


# Mínimo de señales para que una recomendación de próximos pasos signifique algo.
# Con menos, lo que sale es el orden por defecto del producto disfrazado de
# consejo — y eso es peor que no recomendar, porque parece que alguien lo pensó.
def _ia_minimo_senales(db: Any) -> int:
    """Señales mínimas para dar una recomendación. Con menos, la recomendación
    sería el orden por defecto con otro nombre.

    Se lee **una vez por llamada** y nunca dentro de un bucle: `efectivo()` va
    a la base, y ahí dentro sería una consulta por vuelta.
    """
    from crmcore.runtime import settings as rt

    from services.intelligence.ajustes import ajustes

    return int(rt.efectivo("ia_minimo_senales", db) or ajustes().ia_minimo_senales)


def sugerir_respuesta(
    uow: UnidadDeTrabajo,
    *,
    caso_id: UUID,
    pregunta: str,
    fragmentos: list[dict[str, Any]],
    principal: Any = None,
) -> dict[str, Any]:
    """Propone una respuesta al agente de soporte y los artículos en que se apoya
    (CRM-04.02.02.05).

    Se apoya en el mecanismo de respuesta con citación: si no hay con qué
    contestar, **no contesta**. Un agente que recibe una sugerencia sin fuentes la
    manda igual, porque tiene al cliente esperando, y el que responde de la
    respuesta es él.
    """
    if not fragmentos:
        return {
            "hay_sugerencia": False,
            "porque": (
                "No hay ningún artículo ni caso parecido con el que contestar. "
                "Inventar una respuesta aquí es peor que no dar ninguna: el agente "
                "la mandaría tal cual."
            ),
            "articulos": [],
        }

    salida = rag.responder(
        uow,
        pregunta=pregunta,
        fragmentos=fragmentos,
        principal=principal,
        objeto="caso",
        objeto_id=caso_id,
    )
    citados = salida.get("fuentes") or []
    return {
        "hay_sugerencia": bool(salida.get("texto")) and bool(citados),
        "texto": salida.get("texto", ""),
        # Los artículos van aparte del texto a propósito: muchas veces lo que el
        # agente necesita no es el párrafo, es el enlace que puede leer y juzgar.
        "articulos": citados,
        "se_manda_sola": False,
        "porque": (
            "Propuesta para que la revise el agente. Lo que se manda al cliente lo "
            "decide él, y por eso se cuenta aparte si la usó o la descartó."
        ),
        **{k: v for k, v in salida.items() if k in ("aviso", "completo")},
    }


def conversar(
    uow: UnidadDeTrabajo,
    *,
    conversacion_id: UUID,
    pregunta: str,
    fragmentos: list[dict[str, Any]],
    acciones_posibles: list[dict[str, Any]] | None = None,
    principal: Any = None,
) -> dict[str, Any]:
    """Asistente conversacional con conocimiento **y** acciones (CRM-04.03.02.02).

    La parte de conocimiento es la de siempre: contesta citando o no contesta.

    La parte transaccional **no se ejecuta aquí**. Lo que devuelve es qué acción
    propone y con qué argumentos, para que la ejecute el agente —con sus
    herramientas, su tope, su aprobación y su reversión—. Un chatbot que escribe
    directamente en el CRM es un chatbot sin ninguno de esos cuatro controles.
    """
    respuesta = rag.responder(
        uow,
        pregunta=pregunta,
        fragmentos=fragmentos,
        principal=principal,
        objeto="conversacion",
        objeto_id=conversacion_id,
    )
    propuestas = []
    for accion in acciones_posibles or []:
        nombre = str(accion.get("nombre") or "")
        if nombre and nombre.lower() in (respuesta.get("texto") or "").lower():
            propuestas.append(accion)

    return {
        "texto": respuesta.get("texto", ""),
        "fuentes": respuesta.get("fuentes") or [],
        "acciones_propuestas": propuestas,
        # Dicho explícitamente: nadie tiene que deducir del JSON que esto no ha
        # tocado nada.
        "ejecutado": False,
        "quien_ejecuta": (
            "El agente de IA con sus herramientas, su tope de acciones, su "
            "aprobación humana y su reversión. Escribir desde aquí se saltaría "
            "los cuatro controles."
        ),
    }


def resumen_de_cuenta(
    uow: UnidadDeTrabajo,
    *,
    cuenta_id: UUID,
    hechos: dict[str, Any],
    principal: Any = None,
) -> dict[str, Any]:
    """Resume una cuenta separando **lo que consta de lo que se interpreta**
    (CRM-01.01.05.05).

    Un riesgo inventado en un resumen de cuenta acaba en una reunión con el
    cliente, así que los dos bloques van separados y etiquetados: los hechos son
    del CRM y los riesgos son una lectura, con el dato en el que se apoyan al
    lado.
    """
    if not hechos:
        raise ErrorValidacion(
            "No hay nada que resumir de esta cuenta: un resumen sin datos sería "
            "texto inventado sobre un cliente.",
            error_code="asistencia.sin_hechos",
        )

    salida = generacion.generar(
        uow,
        plantilla="resumen_cuenta",
        datos=hechos,
        objeto="cuenta",
        objeto_id=cuenta_id,
        principal=principal,
    )
    if not salida.get("generado"):
        return salida

    return {
        **salida,
        # Lo que el CRM sabe, sin pasar por el modelo. Es lo que permite a quien
        # lo lea comprobar el resumen en vez de creérselo.
        "hechos": hechos,
        "como_leerlo": (
            "Los hechos son del CRM. El texto es una lectura del modelo sobre "
            "esos hechos: si algo del texto no está en los hechos, no está "
            "comprobado."
        ),
    }


def proximos_pasos(
    db: Any,
    tenant_id: UUID,
    *,
    senales: dict[str, Any],
    contenido_disponible: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Qué hacer ahora con esta oportunidad, y con qué contenido
    (CRM-03.01.02.04).

    Sale de **señales del propio negocio** —etapa, días sin contacto, presupuesto
    abierto— y no de una plantilla de manual de ventas. Con menos de tres señales
    no se recomienda nada: lo que saldría es el orden por defecto del producto
    disfrazado de consejo, que es peor que callar porque parece que alguien lo
    pensó.
    """
    utiles = {k: v for k, v in (senales or {}).items() if v is not None}
    # Una vez: se usa dos veces en esta función, y dos lecturas son dos
    # consultas para el mismo número.
    minimo = _ia_minimo_senales(db)
    if len(utiles) < minimo:
        return {
            "concluyente": False,
            "senales": len(utiles),
            "porque": (
                f"Solo hay {len(utiles)} señales de esta oportunidad y hacen falta "
                f"{minimo}. Con menos, la recomendación sería el orden por "
                "defecto del producto con otro nombre."
            ),
            "pasos": [],
        }

    pasos: list[dict[str, Any]] = []
    dias = int(utiles.get("dias_sin_contacto") or 0)
    if dias >= 14:
        pasos.append(
            {
                "que": "Retomar el contacto",
                "porque": f"Llevan {dias} días sin ninguna interacción",
                "urgencia": "alta" if dias >= 30 else "media",
            }
        )
    if utiles.get("presupuesto_abierto") and not utiles.get("reunion_de_cierre"):
        pasos.append(
            {
                "que": "Pedir una reunión de cierre",
                "porque": "Hay presupuesto enviado y ninguna reunión para decidirlo",
                "urgencia": "alta",
            }
        )
    if not utiles.get("patrocinador_identificado"):
        pasos.append(
            {
                "que": "Identificar a quién firma",
                "porque": "No consta quién decide, y sin eso el cierre depende de la suerte",
                "urgencia": "media",
            }
        )

    # El contenido se sugiere solo si encaja con el paso. Adjuntar «el material
    # más reciente» a cualquier recomendación es lo que hace que el comercial
    # deje de mirar lo que se le adjunta.
    for paso in pasos:
        paso["contenido"] = [
            c
            for c in (contenido_disponible or [])
            if str(c.get("para") or "").lower() in paso["que"].lower()
        ]

    return {
        "concluyente": True,
        "senales": len(utiles),
        "pasos": sorted(pasos, key=lambda p: 0 if p["urgencia"] == "alta" else 1),
        "sin_contenido_asociado": [p["que"] for p in pasos if not p["contenido"]],
        "porque": (
            "Sale de las señales de esta oportunidad, no de una plantilla: por eso "
            "cada paso lleva el dato que lo justifica."
        ),
    }
