"""Marcador integrado, grabación y registro automático (CRM-03.03.01.05).

Pulsar un número y que llame es la funcionalidad que más se usa de un CRM
comercial, y la que peor implementada está casi siempre — porque lo difícil no es
lanzar la llamada: es **lo que pasa al colgar**.

Las decisiones:

**La llamada se registra sola al colgar, con su duración y su resultado.** Pedirle
al comercial que anote cada llamada es pedirle que dedique el 20 % de su día a
teclear: no lo hace, y entonces el CRM dice que ese cliente lleva tres meses sin
contacto cuando se habló con él el martes.

**Pero lo que pasó lo escribe una persona.** «Contestada, 3 minutos» no es
información comercial. Se pide una nota corta y se hace fácil; lo que no se hace
es inventarla.

**Grabar exige avisar, siempre, y poder no grabar.** Es un requisito legal en casi
todas partes y, más importante, es lo que hace que una conversación siga siendo
una conversación. Una llamada que no se puede grabar no se bloquea: se hace sin
grabar y se anota por qué.

**Y el marcado automático tiene un límite que no se negocia.** Marcar a más gente
de la que hay para atender produce llamadas que suenan y cuelgan —el *abandono*—,
y eso está regulado y además es lo que hace que un número acabe marcado como spam
en el teléfono de todo el mundo.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Callable
from uuid import UUID

from crmcore.errors import ErrorValidacion, Prohibido
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Cómo terminó la llamada, desde el punto de vista comercial. Cerrada porque de
# esto sale el siguiente paso, y «otros» acaba siendo el 40 % y no dice nada.
RESULTADOS = (
    "hablado",
    "buzon",
    "no_contesta",
    "numero_erroneo",
    "persona_equivocada",
    "pide_que_no_le_llamen",
    "reprogramar",
)

# Resultados que obligan a hacer algo más que anotar. `pide_que_no_le_llamen` no
# es un resultado cualquiera: es una instrucción con efectos legales.
EXIGEN_ACCION = {
    "pide_que_no_le_llamen": "Se apunta la exclusión ese mismo día, en todos los canales que dijo",
    "numero_erroneo": "Se marca el teléfono como malo para que no vuelva a la cola",
    "reprogramar": "Se crea la siguiente llamada con fecha, o se pierde",
}


# Tope de abandono en marcado automático. Es el porcentaje de llamadas que suenan
# y se cuelgan porque no había nadie libre. Está regulado en varios países y,
# además de la multa, es lo que hace que el número acabe marcado como spam.
def _marcador_abandono_maximo_pct() -> float:
    """Antes `_marcador_abandono_maximo_pct() = 3.0`.

    Era una constante de módulo. Sale del `.env`, que es donde una instalación
    puede afinarla sin tocar código.
    """
    from crmcore.config import get_settings

    return get_settings().marcador_abandono_maximo_pct


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def preparar_llamada(
    *,
    contacto_id: UUID,
    numero: str,
    consiente_grabacion: bool,
    grabar_por_politica: bool,
    en_lista_de_exclusion: bool = False,
) -> dict[str, Any]:
    """Comprueba lo que hay que comprobar **antes** de que suene.

    Llamar a alguien que pidió no ser llamado no es un descuido: es una sanción y
    una conversación desagradable. Se comprueba aquí, no al registrar.

    Y si la política dice grabar pero la persona no consiente, **la llamada se
    hace igual sin grabar**: bloquearla convierte una cuestión de privacidad en
    un cliente que no puede hablar con nadie.
    """
    if en_lista_de_exclusion:
        raise Prohibido(
            "Esta persona pidió no ser llamada. Hacerlo igual no es un descuido: es una "
            "sanción y una conversación desagradable.",
            error_code="marcador.en_exclusion",
        )
    graba = grabar_por_politica and consiente_grabacion
    return {
        "contacto_id": str(contacto_id),
        "numero": numero,
        "se_graba": graba,
        "hay_que_avisar": graba,
        "porque": (
            "Se graba y hay que decirlo al empezar: es un requisito legal casi en todas "
            "partes y es lo que hace que la conversación siga siendo una conversación."
            if graba
            else (
                "No se graba porque la persona no lo consiente. La llamada se hace igual: "
                "bloquearla convertiría una cuestión de privacidad en un cliente que no "
                "puede hablar con nadie."
                if grabar_por_politica
                else "La política de este tenant no graba estas llamadas."
            )
        ),
    }


def registrar_al_colgar(
    *,
    contacto_id: UUID,
    duracion_s: int,
    resultado: str,
    nota: str = "",
    grabacion_ref: str = "",
    proxima_fecha: Any = None,
) -> dict[str, Any]:
    """Registra la llamada **sola**, y pide lo que solo sabe una persona.

    La actividad se crea al colgar con lo que el sistema sabe: a quién, cuánto y
    cómo terminó. Lo que **no** se inventa es qué se dijo: «contestada, 3 minutos»
    no es información comercial, y rellenar la nota automáticamente con una frase
    genérica es peor que dejarla vacía — parece que hay contenido.

    Y hay resultados que **obligan a algo más**: quien pide que no le llamen
    entra en la exclusión ese mismo día, y un «reprogramar» sin fecha es una
    llamada que se pierde.
    """
    if resultado not in RESULTADOS:
        raise ErrorValidacion(
            f"Resultado «{resultado}» desconocido",
            error_code="marcador.resultado_invalido",
            detalle={"admitidos": list(RESULTADOS)},
        )
    if resultado == "reprogramar" and not proxima_fecha:
        raise ErrorValidacion(
            "Un «reprogramar» sin fecha es una llamada que se pierde: nadie vuelve a una "
            "lista de pendientes sin fecha.",
            error_code="marcador.sin_proxima_fecha",
        )

    acciones = [EXIGEN_ACCION[resultado]] if resultado in EXIGEN_ACCION else []
    return {
        "contacto_id": str(contacto_id),
        "duracion_s": duracion_s,
        "resultado": resultado,
        "nota": nota.strip(),
        "grabacion": grabacion_ref,
        "registrada_at": _ahora().isoformat(),
        "acciones_obligadas": acciones,
        "falta_la_nota": not nota.strip() and resultado == "hablado",
        "porque": (
            "La actividad se crea sola con lo que el sistema sabe. Pedirle al comercial "
            "que anote cada llamada es pedirle el 20 % de su día: no lo hace, y entonces "
            "el CRM dice que ese cliente lleva tres meses sin contacto."
        ),
        "que_falta": (
            "Falta la nota de qué se habló. No se inventa: «contestada, 3 minutos» no es "
            "información comercial, y rellenarla con una frase genérica es peor que "
            "dejarla vacía porque parece que hay contenido."
            if not nota.strip() and resultado == "hablado"
            else ""
        ),
    }


def ritmo_de_marcado(
    *, agentes_libres: int, llamadas_lanzadas: int, abandonadas: int, contestadas: int
) -> dict[str, Any]:
    """Cuántas llamadas se pueden lanzar a la vez sin pasarse.

    El marcado automático marca a más gente de la que hay para atender a propósito
    —porque muchos no cogen— y ahí está el riesgo: las que sí cogen y no tienen
    agente libre suenan y se cuelgan. Eso es el **abandono**, está regulado, y
    además es lo que hace que el número acabe marcado como spam en el teléfono de
    todo el mundo, que no se arregla pagando una multa.
    """
    total = abandonadas + contestadas
    pct = (abandonadas / total * 100) if total else 0.0
    dentro = pct <= _marcador_abandono_maximo_pct()

    if not dentro:
        recomendado = max(1, agentes_libres)
    else:
        # Un poco por encima de los agentes libres, no el triple: pasarse es lo
        # que produce el abandono que se acaba de medir.
        recomendado = max(1, int(agentes_libres * 1.3))

    return {
        "abandono_pct": round(pct, 2),
        "tope": _marcador_abandono_maximo_pct(),
        "dentro_del_limite": dentro,
        "lanzar_como_mucho": recomendado,
        "medible": total >= 50,
        "que_significa": (
            f"Con {total} llamadas todavía no se puede decir nada del abandono: dos "
            "colgadas seguidas darían un porcentaje enorme."
            if total < 50
            else (
                f"El abandono está en {round(pct, 2)} % y el tope es "
                f"{_marcador_abandono_maximo_pct()} %. Hay que bajar el ritmo: además de la multa, "
                "es lo que hace que el número acabe marcado como spam, y eso no se "
                "arregla pagando."
                if not dentro
                else f"Abandono en {round(pct, 2)} %, dentro del límite."
            )
        ),
    }


def politica_de_grabacion(*, grabar: bool, avisar: bool, dias_conservacion: int) -> dict[str, Any]:
    """Comprueba que la política de grabación se sostiene.

    Grabar sin avisar no es una opción que se pueda ofrecer, ni siquiera como
    ajuste: no es una preferencia del cliente, es un requisito legal. Y una
    grabación sin plazo de borrado es un archivo de voz que crece para siempre —
    con la voz de gente que no sabe que sigue ahí.
    """
    problemas: list[str] = []
    if grabar and not avisar:
        problemas.append(
            "Grabar sin avisar no es una opción configurable: es ilegal en casi todas "
            "partes y rompe la confianza en el resto."
        )
    if grabar and dias_conservacion <= 0:
        problemas.append(
            "No hay plazo de borrado. Una grabación sin plazo es un archivo de voz que "
            "crece para siempre, con gente que no sabe que sigue ahí."
        )
    if grabar and dias_conservacion > 3650:
        problemas.append(
            "Más de diez años de conservación de voz necesita una justificación que casi "
            "nunca existe."
        )
    return {"valido": not problemas, "problemas": problemas}


# ══════════════════════════════════════════════════════════════════════════
# El marcador de verdad (09-11-2026)
#
# Hasta aquí, decisiones puras sobre datos tecleados: la exclusión la decía
# quien llamaba (`en_lista_de_exclusion`), la política de grabación también, no
# sonaba ningún teléfono y «registrar al colgar» devolvía un diccionario que no
# se guardaba. Ahora:
#
# * la exclusión **se pregunta a `party`** —el «no contactar» de la ficha y el
#   último consentimiento por teléfono—, con la identidad de quien pulsa;
# * la política de grabación **es un ajuste** del tenant;
# * la llamada **la origina la telefonía conectada** (`integration`), que la
#   guarda y la registra sola como actividad al colgar;
# * y al colgar, lo que obliga a algo **se hace**: quien pide que no le llamen
#   queda marcado en su ficha, y un «reprogramar» crea la siguiente llamada.
# ══════════════════════════════════════════════════════════════════════════

Invocador = Callable[..., dict[str, Any]]


def _invocar(**kw: Any) -> dict[str, Any]:
    from crmcore.http.interno import invocar

    return invocar(**kw)


def _ajuste(clave: str) -> Any:
    from crmcore.config import get_settings
    from crmcore.runtime.settings import efectivo

    return efectivo(clave, default=getattr(get_settings(), clave, None))


def _error_de(r: dict[str, Any]) -> str:
    datos = r.get("datos") or {}
    if isinstance(datos, dict):
        return str(datos.get("mensaje") or datos.get("detail") or datos)[:400]
    return str(datos)[:400]


def excluido_en_party(
    invocar: Invocador, *, identidad: dict[str, Any], contacto_id: UUID
) -> tuple[bool, str]:
    """Si esta persona pidió no ser llamada, según `party`.

    Dos cosas, y basta una: el «no contactar» de la ficha, que manda sobre todo,
    y que su último consentimiento por teléfono sea una negativa. La ausencia de
    consentimiento **no** es exclusión: un B2B llama a quien no ha dicho nada, y
    lo que no se puede es llamar a quien dijo que no.
    """
    r = invocar(metodo="GET", ruta=f"/api/v1/contacts/{contacto_id}", **identidad)
    if r.get("estado") == 404:
        raise ErrorValidacion(
            "Ese contacto no existe o no lo puedes ver.", error_code="marcador.contacto_no_visible"
        )
    if not r.get("ok"):
        # Sin respuesta no se llama: no poder preguntar no es un «no se opone».
        raise Prohibido(
            "No se ha podido comprobar en party si esta persona pidió no ser llamada; "
            "sin esa respuesta no se llama.",
            error_code="marcador.exclusion_sin_respuesta",
        )
    if (r.get("datos") or {}).get("no_contactar"):
        return True, "La ficha está marcada como «no contactar»."
    c = invocar(metodo="GET", ruta=f"/api/v1/contacts/{contacto_id}/consentimientos", **identidad)
    if c.get("ok"):
        datos = c.get("datos")
        filas = datos.get("items") if isinstance(datos, dict) else datos
        por_telefono = [
            x for x in (filas or []) if str(x.get("canal") or "") in ("telefono", "llamada")
        ]
        por_telefono.sort(key=lambda x: str(x.get("fecha") or ""), reverse=True)
        if por_telefono and por_telefono[0].get("concedido") is False:
            return True, "Su último consentimiento por teléfono es una negativa."
    return False, ""


def llamar(
    *,
    identidad: dict[str, Any],
    numero: str,
    contacto_id: UUID | None,
    cuenta_id: UUID | None,
    consiente_grabacion: bool,
    excluido_declarado: bool = False,
    invocar: Invocador | None = None,
) -> dict[str, Any]:
    """Comprueba, y si se puede, pide a la telefonía que marque.

    Lo que se comprueba antes de que suene: la exclusión (en `party`) y la
    grabación (la política del tenant y el consentimiento de la persona). Si la
    telefonía no está conectada se dice, con el porqué, y no se finge una
    llamada.
    """
    invocar = invocar or _invocar
    excluido, porque = (excluido_declarado, "Declarado por quien llama.")
    if contacto_id is not None and not excluido:
        excluido, porque = excluido_en_party(invocar, identidad=identidad, contacto_id=contacto_id)
    if excluido and contacto_id is None:
        raise Prohibido(porque, error_code="marcador.en_exclusion")
    preparada = preparar_llamada(
        contacto_id=contacto_id or cuenta_id or UUID(int=0),
        numero=numero,
        consiente_grabacion=consiente_grabacion,
        grabar_por_politica=bool(_ajuste("marcador_grabar_por_politica")),
        en_lista_de_exclusion=excluido,
    )
    r = invocar(
        metodo="POST",
        ruta="/api/v1/telefonia/llamar",
        cuerpo={
            "numero": numero,
            "contacto_id": str(contacto_id) if contacto_id else None,
            "cuenta_id": str(cuenta_id) if cuenta_id else None,
            "grabar": preparada["se_graba"],
        },
        timeout_s=float(_ajuste("marcador_espera_s") or 20.0),
        **identidad,
    )
    if not r.get("ok"):
        raise ErrorValidacion(
            f"La telefonía no ha podido llamar: {_error_de(r)}",
            error_code="marcador.telefonia_no_llama",
            detalle={"estado": r.get("estado"), "respuesta": r.get("datos")},
        )
    preparada["contacto_id"] = str(contacto_id) if contacto_id else None
    preparada["cuenta_id"] = str(cuenta_id) if cuenta_id else None
    return {"preparada": preparada, "llamada": r.get("datos")}


def colgar(
    *,
    identidad: dict[str, Any],
    llamada_id: UUID,
    resultado: str,
    nota: str,
    proxima_fecha: date | None,
    invocar: Invocador | None = None,
) -> dict[str, Any]:
    """Anota cómo fue y hace lo que el resultado obliga a hacer.

    La actividad la creó la telefonía al colgar (con duración y resultado de la
    centralita). Aquí se le pone lo que sólo sabe la persona —la nota— y se
    aplican las obligaciones: quien pidió que no le llamen queda marcado en su
    ficha ese mismo día, y un «reprogramar» crea la siguiente llamada con fecha.
    """
    invocar = invocar or _invocar
    r = invocar(metodo="GET", ruta=f"/api/v1/telefonia/llamadas/{llamada_id}", **identidad)
    if not r.get("ok"):
        raise ErrorValidacion(
            f"No se encuentra la llamada: {_error_de(r)}",
            error_code="marcador.llamada_no_encontrada",
        )
    llamada = dict(r.get("datos") or {})
    contacto = llamada.get("contacto_id")
    registro = registrar_al_colgar(
        contacto_id=UUID(contacto) if contacto else UUID(int=0),
        duracion_s=int(llamada.get("duracion_s") or 0),
        resultado=resultado,
        nota=nota,
        grabacion_ref=str(llamada.get("grabacion_url") or ""),
        proxima_fecha=proxima_fecha,
    )
    a = invocar(
        metodo="POST",
        ruta=f"/api/v1/telefonia/llamadas/{llamada_id}/resultado",
        cuerpo={"resultado_comercial": resultado, "nota": nota},
        **identidad,
    )
    aplicadas: list[str] = []
    pendientes: list[str] = []
    if not a.get("ok"):
        pendientes.append(f"La nota no se ha guardado: {_error_de(a)}")
    if resultado == "pide_que_no_le_llamen":
        if contacto:
            p = invocar(
                metodo="PATCH",
                ruta=f"/api/v1/contacts/{contacto}",
                cuerpo={"no_contactar": True},
                **identidad,
            )
            (aplicadas if p.get("ok") else pendientes).append(
                "Ficha marcada como «no contactar»"
                if p.get("ok")
                else f"No se ha podido marcar «no contactar»: {_error_de(p)}"
            )
        else:
            pendientes.append("La llamada no está ligada a un contacto: márcalo a mano.")
    if resultado == "reprogramar" and proxima_fecha:
        quien = (llamada.get("identificacion") or {}).get("nombre") or llamada.get("numero")
        s = invocar(
            metodo="POST",
            ruta="/api/v1/activities",
            cuerpo={
                "tipo": "llamada",
                "asunto": f"Volver a llamar a {quien}"[:300],
                "objeto": "contacto" if contacto else None,
                "objeto_id": contacto,
                "contacto_id": contacto,
                "cuenta_id": llamada.get("cuenta_id"),
                "vence_at": datetime.combine(
                    proxima_fecha, datetime.min.time(), tzinfo=timezone.utc
                ).isoformat(),
                "cuerpo": nota or None,
                "detalles": {"numero": llamada.get("numero"), "de_la_llamada": str(llamada_id)},
            },
            **identidad,
        )
        (aplicadas if s.get("ok") else pendientes).append(
            "Siguiente llamada creada con fecha"
            if s.get("ok")
            else f"No se ha podido crear la siguiente llamada: {_error_de(s)}"
        )
    if resultado == "numero_erroneo":
        # Lo marca la telefonía al anotar el resultado (PATCH del contacto en
        # party con `estado_telefono`); aquí se dice si lo hizo o qué falta.
        marcado = ((a.get("datos") or {}) if a.get("ok") else {}).get("telefono_marcado") or {}
        if marcado.get("marcado"):
            aplicadas.append("Teléfono marcado como erróneo en la ficha")
        else:
            pendientes.append(
                marcado.get("porque") or "Marca el teléfono como erróneo en la ficha del contacto."
            )
    return {
        **registro,
        "contacto_id": contacto,
        "llamada_id": str(llamada_id),
        "actividad_id": llamada.get("actividad_id"),
        "aplicadas": aplicadas,
        "pendientes": pendientes,
    }
