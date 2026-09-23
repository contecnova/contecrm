"""Telefonía conectada al CRM: screen pop, transferencia con contexto e IVR
(CRM-04.02.01.05).

Lo que se le pide a una integración de telefonía es que **cuando suene el teléfono
ya esté la ficha abierta**. Suena a comodidad y no lo es: son quince segundos por
llamada buscando quién llama, multiplicados por doscientas llamadas al día, y sobre
todo es el cliente contando otra vez lo mismo.

Las decisiones:

**Se identifica por el número y se dice con qué confianza.** Un número que
coincide con tres fichas no es una ficha: es una lista, y abrir la primera «porque
suele ser esa» hace que el agente salude por el nombre equivocado — que es peor
que no saludar por ninguno.

**La transferencia lleva el contexto o no es una transferencia.** Pasar la llamada
sin lo que ya se ha hablado obliga al cliente a empezar de cero, y esa es
literalmente la queja número uno de cualquier servicio de atención.

**El IVR aporta lo que el cliente ya tecleó.** Si marcó su número de pedido, ese
dato llega con la llamada: volver a pedírselo al descolgar es la forma más rápida
de que alguien se enfade antes de que empiece la conversación.

**Y la llamada se registra pase lo que pase.** Una llamada perdida o que nadie
cogió es información —y de la buena—: las que no constan son justo las que se
pierden en la cola.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.errors import ErrorValidacion
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Eventos que manda una centralita. Cerrada porque de cada uno sale una acción
# distinta en la pantalla, y uno desconocido que se ignore en silencio deja al
# agente esperando algo que no va a pasar.
EVENTOS = ("entrante", "contestada", "colgada", "perdida", "transferida", "en_cola", "saliente")

# Estados con los que puede terminar una llamada. `perdida` y `abandonada` van
# separadas: una la colgó el que llamaba antes de que nadie la cogiera y la otra
# nunca llegó a sonar, y confundirlas oculta un problema de enrutado.
RESULTADOS = ("contestada", "perdida", "abandonada", "desviada", "buzon")

# Longitud mínima para intentar identificar por número. Con menos, media base
# encaja: un «600» coincide con miles de fichas.
MINIMO_DIGITOS = 7

_SOLO_DIGITOS = re.compile(r"\D+")


def _normalizar(numero: str) -> str:
    """Deja solo dígitos y se queda con la cola significativa.

    Se compara por el final a propósito: el mismo teléfono aparece como
    `+34600...`, `0034600...` y `600...` según quién lo escribiera, y comparar
    literalmente hace que el screen pop no salte justo con los clientes de toda la
    vida, que son los que están mal escritos.
    """
    limpio = _SOLO_DIGITOS.sub("", numero or "")
    return limpio[-9:] if len(limpio) > 9 else limpio


def identificar(*, numero: str, candidatos: list[dict[str, Any]]) -> dict[str, Any]:
    """Quién llama, **y con qué confianza**.

    Tres respuestas distintas y ninguna se redondea: **una ficha**, **varias** y
    **ninguna**. Abrir la primera de tres «porque suele ser esa» hace que el
    agente salude por el nombre equivocado, que es peor que no saludar por
    ninguno.

    Y con un número corto no se intenta: con menos de siete dígitos media base
    encaja.
    """
    clave = _normalizar(numero)
    if len(clave) < MINIMO_DIGITOS:
        return {
            "identificado": False,
            "motivo": "numero_corto",
            "que_hacer": (
                "El número es demasiado corto para buscar: con menos de "
                f"{MINIMO_DIGITOS} dígitos media base encaja. Se abre la pantalla en "
                "blanco y se pregunta."
            ),
        }

    encajan = [
        c
        for c in candidatos
        if any(_normalizar(str(t)) == clave for t in (c.get("telefonos") or []))
    ]
    if not encajan:
        return {
            "identificado": False,
            "motivo": "desconocido",
            "numero": clave,
            "que_hacer": (
                "No hay ninguna ficha con ese número. No es basura: puede ser un "
                "contacto que falta por dar de alta, y conviene ofrecerlo al colgar."
            ),
        }
    if len(encajan) > 1:
        return {
            "identificado": False,
            "motivo": "ambiguo",
            "candidatos": [
                {"id": str(c.get("id")), "nombre": c.get("nombre"), "cuenta": c.get("cuenta")}
                for c in encajan
            ],
            "que_hacer": (
                f"{len(encajan)} fichas comparten ese número —suele ser una centralita "
                "de empresa—. Se enseñan las tres y elige el agente: abrir la primera "
                "hace que salude por el nombre equivocado."
            ),
        }
    ficha = encajan[0]
    return {
        "identificado": True,
        "contacto_id": str(ficha.get("id")),
        "nombre": ficha.get("nombre"),
        "cuenta": ficha.get("cuenta"),
    }


def pantalla_al_sonar(
    *,
    identificacion: dict[str, Any],
    datos_del_ivr: dict[str, Any] | None = None,
    ultimo_caso: dict[str, Any] | None = None,
    ultima_interaccion: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Qué se le pone delante al agente antes de descolgar.

    Lo que el cliente **ya tecleó en el IVR viaja con la llamada**. Si marcó su
    número de pedido, volver a pedírselo al descolgar es la forma más rápida de
    que se enfade antes de empezar.

    Y lo que se enseña es **lo último que le pasó**, no su ficha entera: un agente
    tiene cuatro segundos mientras suena, y un panel con veinte campos no se lee
    en cuatro segundos.
    """
    ivr = dict(datos_del_ivr or {})
    return {
        "abrir_ficha": bool(identificacion.get("identificado")),
        "contacto_id": identificacion.get("contacto_id"),
        "lo_que_ya_dijo_en_el_ivr": ivr,
        "ultimo_caso": ultimo_caso,
        "ultima_interaccion": ultima_interaccion,
        "no_volver_a_preguntar": sorted(ivr),
        "porque": (
            "Lo que tecleó en el IVR llega con la llamada: volver a pedírselo es la "
            "forma más rápida de que se enfade antes de empezar."
            if ivr
            else "El IVR no ha recogido nada, así que hay que preguntarlo."
        ),
        "que_se_enseña": (
            "Lo último que le pasó, no la ficha entera: un agente tiene cuatro segundos "
            "mientras suena, y un panel de veinte campos no se lee en cuatro segundos."
        ),
    }


def transferir(
    *,
    a: str,
    resumen: str,
    contacto_id: UUID | None,
    caso_id: UUID | None,
    lo_ya_hablado: list[str],
) -> dict[str, Any]:
    """Prepara una transferencia **con el contexto dentro**.

    Pasar la llamada sin lo que ya se ha hablado obliga al cliente a empezar de
    cero, y esa es literalmente la queja número uno de cualquier servicio de
    atención. Por eso el resumen es obligatorio: una transferencia sin resumen es
    la que se hace por quitarse la llamada de encima.
    """
    if not resumen.strip():
        raise ErrorValidacion(
            "Una transferencia sin resumen obliga al cliente a empezar de cero, y esa es "
            "la queja número uno de cualquier servicio de atención.",
            error_code="cti.transferencia_sin_contexto",
        )
    return {
        "a": a,
        "resumen": resumen.strip(),
        "contacto_id": str(contacto_id) if contacto_id else None,
        "caso_id": str(caso_id) if caso_id else None,
        "lo_ya_hablado": lo_ya_hablado,
        "el_cliente_no_repite": True,
        "porque": (
            "Lo que ya contó viaja con la llamada. Quien la recibe empieza sabiendo, no "
            "preguntando."
        ),
    }


def registrar_llamada(
    *,
    evento: str,
    resultado: str,
    numero: str,
    duracion_s: int,
    contacto_id: UUID | None,
    espera_s: int = 0,
    grabacion_ref: str = "",
) -> dict[str, Any]:
    """Deja constancia de la llamada, **haya hablado alguien o no**.

    Las perdidas y las abandonadas son las que más dicen: una llamada que nadie
    cogió es un cliente que lo intentó, y si no consta, el panel enseña un servicio
    impecable construido con las llamadas que sí se atendieron.

    Se distinguen además **perdida** (sonó y nadie la cogió) de **abandonada** (la
    colgaron en la cola antes de sonar): confundirlas oculta un problema de
    enrutado detrás de uno de plantilla.
    """
    if evento not in EVENTOS:
        raise ErrorValidacion(
            f"Evento de telefonía «{evento}» desconocido",
            error_code="cti.evento_invalido",
            detalle={"admitidos": list(EVENTOS)},
        )
    if resultado not in RESULTADOS:
        raise ErrorValidacion(
            f"Resultado «{resultado}» desconocido",
            error_code="cti.resultado_invalido",
            detalle={"admitidos": list(RESULTADOS)},
        )
    return {
        "evento": evento,
        "resultado": resultado,
        "numero": _normalizar(numero),
        "duracion_s": duracion_s,
        "espera_s": espera_s,
        "contacto_id": str(contacto_id) if contacto_id else None,
        "sin_atender": resultado in ("perdida", "abandonada"),
        "grabacion": grabacion_ref,
        "registrada_at": datetime.now(timezone.utc).isoformat(),
        "porque_se_registra_igual": (
            "Una llamada que nadie cogió es un cliente que lo intentó. Si no consta, el "
            "panel enseña un servicio impecable construido solo con las que se "
            "atendieron."
        ),
    }
