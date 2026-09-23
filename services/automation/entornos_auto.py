"""Probar y promocionar automatizaciones, y plantillas por industria
(CRM-00.03.03.08, CRM-00.03.03.09).

Una automatización se escribe en producción porque es donde están los datos de
verdad, y se prueba **activándola**. Eso funciona hasta el día en que la regla
que debía avisar a una persona manda cuatro mil correos, o la que debía cambiar
un campo lo cambia en veinte mil registros.

Lo que evita eso no es prohibir escribir en producción: es poder **ejecutarla
sobre datos reales sin que haga nada**, y ver qué habría hecho.

Las decisiones:

**La prueba en seco es contra datos de verdad.** Contra datos inventados, la
regla siempre funciona: los casos raros que la rompen son los que tiene el
cliente, no los que a uno se le ocurren.

**Y dice a CUÁNTOS habría afectado.** Es el número que para una mano: nadie
activa una regla cuando ve «afectaría a 19.480 registros» — y casi todo el mundo
la activa si solo ve «la regla es válida».

**Promocionar no copia el estado, copia la definición.** Lo que lleva dentro una
automatización en marcha —qué registros ya procesó, qué tiene pendiente— es de su
entorno. Copiarlo haría que la de producción creyera haber hecho ya el trabajo
que hizo la de pruebas.

**Y una plantilla llega apagada.** Una biblioteca que instala reglas activas es
una biblioteca que empieza a mandar correos en cuanto alguien la mira.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from crmcore.errors import Conflicto, ErrorValidacion
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Cuántos registros afectados hacen que la prueba exija confirmación aparte. No
# es un límite técnico: es el número a partir del cual un error deja de ser un
# error y pasa a ser un incidente que se cuenta a los clientes.
UMBRAL_MASIVO = 500


def probar_en_seco(
    *,
    nombre: str,
    afectados: list[dict[str, Any]],
    acciones: list[dict[str, Any]],
    limite_muestra: int = 20,
) -> dict[str, Any]:
    """Ejecuta la automatización **sin hacer nada** y cuenta qué habría hecho.

    Sobre datos reales: contra datos inventados la regla siempre funciona, porque
    los casos raros que la rompen son los que tiene el cliente y no los que a uno
    se le ocurren.

    Devuelve una **muestra** además del recuento. El número asusta; la muestra es
    lo que hace que alguien diga «espera, ese no debería estar ahí» — que es el
    momento en que la prueba en seco ha servido para algo.
    """
    if not acciones:
        raise ErrorValidacion(
            "Una automatización sin acciones no hace nada, ni en seco ni de verdad",
            error_code="automatizacion.sin_acciones",
        )

    total = len(afectados)
    envios = [a for a in acciones if str(a.get("tipo") or "") in ("notificar", "enviar_correo")]
    escrituras = [a for a in acciones if str(a.get("tipo") or "") in ("actualizar", "crear")]

    return {
        "automatizacion": nombre,
        "en_seco": True,
        # El número que para una mano. Nadie activa una regla cuando ve esto;
        # casi todo el mundo la activa si solo ve «la regla es válida».
        "afectaria_a": total,
        "muestra": [
            {"objeto": a.get("objeto"), "id": str(a.get("id") or ""), "porque": a.get("porque")}
            for a in afectados[:limite_muestra]
        ],
        "hay_mas": total > limite_muestra,
        # Las dos consecuencias que no se deshacen igual: un campo mal puesto se
        # arregla; cuatro mil correos enviados, no.
        "correos_que_saldrian": total * len(envios),
        "registros_que_cambiarian": total * len(escrituras),
        "es_masiva": total >= UMBRAL_MASIVO,
        "aviso": (
            ""
            if total < UMBRAL_MASIVO
            else f"Esto tocaría {total} registros. A partir de ahí, un error deja de "
            "ser un error y pasa a ser un incidente que hay que contarle a los "
            "clientes: activarla exige confirmarlo aparte."
        ),
        "porque_datos_reales": (
            "Se prueba contra los datos del tenant y no contra unos inventados: los "
            "casos raros que rompen una regla son los que tiene el cliente."
        ),
    }


def promocionar(
    *,
    definicion: dict[str, Any],
    desde: str,
    hacia: str,
    probada_en_seco: bool,
    afectados_en_pruebas: int = 0,
) -> dict[str, Any]:
    """Lleva una automatización de un entorno a otro (CRM-00.03.03.08).

    **Copia la definición, no el estado.** Lo que lleva dentro una automatización
    en marcha —qué registros ya procesó, qué tiene pendiente, cuándo se ejecutó
    por última vez— es de su entorno. Copiarlo haría que la de producción creyera
    haber hecho ya el trabajo que hizo la de pruebas, y se saltaría justo los
    registros que tenía que tocar.

    Y **llega apagada**. Una automatización que se enciende sola al promocionarse
    empieza a actuar sobre datos reales en el momento en que alguien pulsa
    «desplegar», que no es el momento en que alguien ha decidido que actúe.
    """
    if hacia == "produccion" and not probada_en_seco:
        raise Conflicto(
            "No se promociona a producción una automatización que no se ha probado "
            "en seco. La prueba cuesta un minuto; la regla que manda cuatro mil "
            "correos cuesta una semana de explicaciones.",
            error_code="automatizacion.sin_prueba",
        )

    limpia = {
        k: v
        for k, v in (definicion or {}).items()
        # El estado se queda: es del entorno de origen y no significa nada en el
        # destino.
        if k not in ("ultima_ejecucion", "procesados", "pendientes", "estado_interno")
    }
    return {
        "desde": desde,
        "hacia": hacia,
        "definicion": limpia,
        "llega_activa": False,
        "estado_descartado": sorted(set(definicion or {}) - set(limpia)),
        "porque_apagada": (
            "Una automatización que se enciende sola al promocionarse empieza a "
            "actuar en el momento en que alguien pulsa «desplegar», que no es el "
            "momento en que alguien ha decidido que actúe."
        ),
        "porque_sin_estado": (
            "Lo que ya procesó en pruebas no lo ha procesado en producción: "
            "copiarlo haría que se saltara justo los registros que tiene que tocar."
        ),
        "recordatorio": (
            f"En pruebas afectó a {afectados_en_pruebas} registros. En producción "
            "serán otros: conviene volver a probar en seco antes de encenderla."
            if afectados_en_pruebas
            else ""
        ),
    }


def instalar_plantilla(
    *,
    plantilla: dict[str, Any],
    existentes: list[str],
) -> dict[str, Any]:
    """Instala una plantilla de automatización por industria (CRM-00.03.03.09).

    **Todo llega apagado.** Una biblioteca que instala reglas activas es una
    biblioteca que empieza a mandar correos en cuanto alguien la mira por
    curiosidad — y la primera vez que eso pasa, nadie vuelve a abrir la
    biblioteca.

    Lo que ya existe **no se pisa**: se salta y se cuenta. Y se devuelve lo que
    la plantilla **da por supuesto** —que existe un campo, que hay un pipeline
    con ciertas etapas—, porque una regla que se apoya en algo que este tenant no
    tiene no falla al instalarse: falla la primera vez que se dispara, semanas
    después.
    """
    reglas = list(plantilla.get("reglas") or [])
    if not reglas:
        raise ErrorValidacion(
            "Una plantilla sin reglas no instala nada", error_code="plantilla.vacia"
        )

    ya = set(existentes)
    instaladas = [r for r in reglas if str(r.get("clave")) not in ya]
    saltadas = [str(r.get("clave")) for r in reglas if str(r.get("clave")) in ya]

    return {
        "plantilla": plantilla.get("clave"),
        "instaladas": [str(r.get("clave")) for r in instaladas],
        "saltadas": saltadas,
        "todas_apagadas": True,
        # Lo que la plantilla necesita y puede no estar. No falla al instalar:
        # falla la primera vez que se dispara, semanas después.
        "da_por_supuesto": list(plantilla.get("requiere") or []),
        "instalado_at": datetime.now(timezone.utc).isoformat(),
        "que_hacer_ahora": (
            "Probar cada una en seco y encenderlas de una en una. Encenderlas todas "
            "de golpe hace imposible saber cuál mandó el correo raro."
        ),
    }
