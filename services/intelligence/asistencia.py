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
    # `rag.responder` devuelve `respuesta` y `citas`. Aquí se leían `texto` y
    # `fuentes`, que no existen: la sugerencia salía SIEMPRE vacía, contestara
    # lo que contestara el modelo. Medido el 05-11-2026 con el índice de verdad.
    citados = salida.get("citas") or []
    texto = str(salida.get("respuesta") or "")
    return {
        "hay_sugerencia": bool(salida.get("respondida")) and bool(texto) and bool(citados),
        "texto": texto,
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


def recuperar(db: Any, tenant_id: UUID, *, pregunta: str) -> dict[str, Any]:
    """Lo del índice de conocimiento de la casa que se parece a la pregunta.

    Artículos publicados, casos resueltos y lecciones aprendidas, cada uno con
    el permiso que hace falta para verlo: el guardarraíl lo comprueba contra
    quien pregunta antes de mandárselo al modelo. Lo que se parece poco se
    queda fuera — mandarle al modelo algo que no tiene que ver es invitarle a
    contestar con ello.
    """
    from crmcore.errors import Conflicto, NoEncontrado

    from services.intelligence import indice
    from services.intelligence.ajustes import ajustes

    minimo = float(_ajuste_runtime(db, "ia_asistente_parecido_minimo"))
    try:
        encontrados = indice.buscar(
            db, tenant_id, texto=pregunta, tope=int(ajustes().ia_asistente_fragmentos)
        )
    except (NoEncontrado, Conflicto) as exc:
        return {"fragmentos": [], "buscado": False, "porque": str(exc)}
    utiles = [f for f in encontrados if float(f.get("parecido") or 0) >= minimo]
    return {
        "buscado": True,
        "encontrados": len(encontrados),
        "descartados_por_parecido": len(encontrados) - len(utiles),
        "fragmentos": [
            {
                "texto": f"{f.get('titulo') or ''}\n{f.get('texto') or ''}",
                "fuente": f.get("fuente"),
                "id": f.get("referencia"),
                "titulo": f.get("titulo"),
                "permiso": f.get("permiso"),
                "sensibilidad": "interno",
                "parecido": f.get("parecido"),
            }
            for f in utiles
        ],
    }


def _ajuste_runtime(db: Any, clave: str) -> Any:
    from crmcore.runtime import settings as rt

    from services.intelligence.ajustes import ajustes

    valor = rt.efectivo(clave, db)
    return getattr(ajustes(), clave) if valor is None else valor


def conversar(
    uow: UnidadDeTrabajo,
    *,
    conversacion_id: UUID,
    pregunta: str,
    fragmentos: list[dict[str, Any]] | None = None,
    principal: Any = None,
) -> dict[str, Any]:
    """Asistente conversacional con conocimiento **y** acciones (CRM-04.03.02.02).

    **El conocimiento lo busca él** en el índice de la casa, salvo que se le
    pasen fragmentos. Contesta citando o no contesta.

    **Las acciones salen de una lista cerrada** y se proponen, no se ejecutan:
    `acciones_asistente.ejecutar` lo hace cuando quien preguntó lo confirma,
    con su identidad y sus permisos.
    """
    from services.intelligence import acciones_asistente as acc

    recuperado: dict[str, Any] = {"buscado": False}
    if not fragmentos:
        recuperado = recuperar(uow.db, uow.tenant_id, pregunta=pregunta)
        fragmentos = recuperado["fragmentos"]
    texto = ""
    fuentes: list[dict[str, Any]] = []
    respuesta: dict[str, Any] = {}
    if fragmentos:
        respuesta = rag.responder(
            uow,
            pregunta=pregunta,
            fragmentos=fragmentos,
            principal=principal,
            objeto="conversacion",
            objeto_id=conversacion_id,
        )
        # `respuesta` y `citas`, que es lo que devuelve `rag.responder`.
        texto = str(respuesta.get("respuesta") or "") if respuesta.get("respondida") else ""
        por_id = {str(f.get("id")): f for f in fragmentos}
        fuentes = [
            {**c, "titulo": (por_id.get(str(c.get("id"))) or {}).get("titulo") or ""}
            for c in respuesta.get("citas") or []
        ]
    propuesta = acc.proponer(uow, pregunta=pregunta, respuesta=texto, principal=principal)
    return {
        "texto": texto,
        "respondida": bool(texto),
        "fuentes": fuentes,
        "porque": (
            ""
            if texto
            else str(respuesta.get("porque") or recuperado.get("porque") or "")
            or "No hay nada en el conocimiento de la casa que conteste a esto."
        ),
        "conocimiento": {k: v for k, v in recuperado.items() if k != "fragmentos"},
        "accion_propuesta": propuesta,
        # Dicho explícitamente: nadie tiene que deducir del JSON que esto no ha
        # tocado nada todavía.
        "ejecutado": False,
        "como_se_ejecuta": (
            "La acción propuesta no se hace hasta que la confirmes: "
            "POST /api/v1/ia/asistente/acciones/{id}, con tus permisos."
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

    import json

    # Los hechos van también como CONTEXTO, no sólo como datos de la plantilla:
    # un resumen exige un mínimo de contexto y, sin él, `generar` no llamaba al
    # modelo nunca —«no hay contexto suficiente»— por muchos hechos que hubiera.
    salida = generacion.generar(
        uow,
        plantilla="resumen_cuenta",
        datos=hechos,
        contexto=[
            {
                "texto": json.dumps(hechos, ensure_ascii=False, default=str),
                "fuente": "cuenta",
                "id": str(cuenta_id),
                # Sin permiso declarado el guardarraíl lo descarta («ante la
                # duda no se enseña»): es el de leer la cuenta, y se comprueba
                # contra quien pide el resumen.
                "permiso": "account:read",
                "sensibilidad": "interno",
            }
        ],
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
    # Ajustes `asistencia_dias_sin_contacto` y `…_urgente` (eran 14 y 30).
    dias_aviso = int(_ajuste_runtime(db, "asistencia_dias_sin_contacto"))
    dias_urgente = int(_ajuste_runtime(db, "asistencia_dias_sin_contacto_urgente"))
    if dias >= dias_aviso:
        pasos.append(
            {
                "que": "Retomar el contacto",
                "porque": f"Llevan {dias} días sin ninguna interacción",
                "urgencia": "alta" if dias >= dias_urgente else "media",
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
