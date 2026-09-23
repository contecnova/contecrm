"""Audiencias en plataformas publicitarias, retargeting, canales offline y
personalización web (CRM-02.01.01.09, CRM-02.03.02.04, CRM-02.03.02.05,
CRM-02.03.02.07).

Sincronizar una audiencia con una plataforma de anuncios es de las cosas más
fáciles de hacer y de las que más problemas legales dan en un CRM, porque lo que
se manda es **una lista de personas a un tercero que la usa para perfilar**. Y
casi siempre se hace sin mirar nada: se filtra un segmento, se pulsa «sincronizar»
y a partir de ahí esa lista vive fuera, se actualiza sola y nadie sabe quién está
dentro.

Las decisiones:

**Sin base legal para publicidad no sale nadie.** Y no vale el consentimiento de
recibir el boletín: aceptar correos comerciales no es aceptar que tu dirección se
suba a una plataforma de anuncios. Se comprueba por persona, no por segmento.

**Lo que sale va troceado (hash) y nunca en claro.** No es una formalidad: es la
diferencia entre mandar una lista de correos y mandar identificadores que solo
sirven para cruzar.

**Una baja aquí es una baja allí, y el mismo día.** Es el punto donde todas estas
integraciones fallan: dar de baja en el CRM y seguir apareciendo en los anuncios
es exactamente lo que la gente denuncia, y con razón.

**Las audiencias pequeñas no se mandan.** Con veinte personas, la plataforma no
puede anonimizar nada y el segmento se convierte en señalar a alguien con el dedo.

**Y el canal offline —correo postal, telemarketing— es un paso del recorrido como
los demás**, con una diferencia que hay que respetar: no se puede cancelar. Una
carta impresa ya está impresa, y una llamada hecha no se deshace.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone
from typing import Any

from crmcore.errors import ErrorValidacion, Prohibido
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Bases que permiten mandar a alguien a una plataforma publicitaria. Cerrada y
# corta: el consentimiento del boletín NO está, porque aceptar correos
# comerciales no es aceptar que tu dirección se suba a una red de anuncios.
BASES_PUBLICIDAD = ("consentimiento_publicidad", "interes_legitimo_documentado")

# Mínimo de personas para mandar una audiencia. Con menos, la plataforma no puede
# anonimizar nada y el segmento se convierte en señalar a alguien con el dedo.
MINIMO_AUDIENCIA = 100

# Canales que no se pueden cancelar una vez lanzados. No es un detalle técnico:
# cambia cómo se diseña el recorrido, porque un paso irreversible en medio obliga
# a poner la comprobación antes y no después.
IRREVERSIBLES = ("correo_postal", "telemarketing")

CANALES_OFFLINE = ("correo_postal", "telemarketing", "sms_certificado")


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _trocear(valor: str) -> str:
    """SHA-256 en minúsculas y sin espacios, que es lo que esperan las
    plataformas. No es una formalidad: es la diferencia entre mandar una lista de
    correos y mandar identificadores que solo sirven para cruzar."""
    return hashlib.sha256(valor.strip().lower().encode()).hexdigest()


def preparar_audiencia(
    *, personas: list[dict[str, Any]], plataforma: str, finalidad: str
) -> dict[str, Any]:
    """Prepara lo que se le manda a la plataforma, **quitando a quien no puede ir**.

    Se comprueba **persona a persona**, no por segmento: un segmento «clientes
    activos» tiene dentro gente que nunca aceptó publicidad, y mandarlo entero
    porque el segmento parece inocuo es exactamente como pasa.

    Y lo que sale va troceado. Mandar correos en claro a un tercero es una cesión
    de datos personales sin ninguna necesidad técnica.
    """
    fuera_sin_base: list[str] = []
    fuera_bajas: list[str] = []
    dentro: list[dict[str, str]] = []

    for persona in personas:
        correo = str(persona.get("email") or "").strip().lower()
        if not correo:
            continue
        if persona.get("baja_publicidad"):
            fuera_bajas.append(correo)
            continue
        if str(persona.get("base_legal") or "") not in BASES_PUBLICIDAD:
            fuera_sin_base.append(correo)
            continue
        dentro.append({"hash": _trocear(correo)})

    demasiado_pequena = len(dentro) < MINIMO_AUDIENCIA
    return {
        "plataforma": plataforma,
        "finalidad": finalidad,
        "cuantos_salen": len(dentro),
        "identificadores": [] if demasiado_pequena else dentro,
        "fuera_por_falta_de_base": len(fuera_sin_base),
        "fuera_por_baja": len(fuera_bajas),
        "se_puede_mandar": not demasiado_pequena,
        "van_en_claro": False,
        "porque": (
            f"Solo {len(dentro)} personas. Por debajo de {MINIMO_AUDIENCIA} la "
            "plataforma no puede anonimizar nada y el segmento se convierte en señalar "
            "a alguien con el dedo."
            if demasiado_pequena
            else "Cada dirección va troceada: lo que sale son identificadores para "
            "cruzar, no una lista de correos."
        ),
        "aviso": (
            ""
            if not fuera_sin_base
            else f"{len(fuera_sin_base)} personas se quedan fuera por no tener base "
            "legal para publicidad. Aceptar el boletín no es aceptar que tu dirección "
            "se suba a una red de anuncios, y esa distinción es la que se salta todo "
            "el mundo."
        ),
    }


def exigir_base_publicitaria(*, base: str) -> None:
    """Se comprueba antes de mandar nada, no al configurar la integración."""
    if base not in BASES_PUBLICIDAD:
        raise Prohibido(
            f"«{base}» no habilita mandar a alguien a una plataforma publicitaria. "
            "Aceptar recibir el boletín no es aceptar que tu dirección se suba a una "
            "red de anuncios.",
            error_code="audiencia.sin_base_publicitaria",
            detalle={"admitidas": list(BASES_PUBLICIDAD)},
        )


def bajas_a_propagar(
    *, bajas_en_el_crm: list[dict[str, Any]], ultimo_envio: datetime | None
) -> dict[str, Any]:
    """Quién se ha dado de baja y todavía está en las audiencias de fuera.

    Este es el punto donde **todas** estas integraciones fallan: alguien se da de
    baja en el CRM, la audiencia de la plataforma se actualiza «cuando toque», y
    mientras tanto sigue viendo anuncios. Es exactamente lo que la gente denuncia,
    y tiene razón.

    Por eso la baja no espera al ciclo normal: sale en su propia lista y con
    prioridad.
    """
    pendientes = [
        b
        for b in bajas_en_el_crm
        if ultimo_envio is None
        or not isinstance(b.get("baja_at"), datetime)
        or b["baja_at"] > ultimo_envio
    ]
    return {
        "bajas_pendientes": len(pendientes),
        "identificadores": [_trocear(str(b.get("email") or "")) for b in pendientes],
        "urgente": bool(pendientes),
        "porque": (
            "Una baja en el CRM que no llega a la plataforma deja a alguien viendo "
            "anuncios después de haber dicho que no. No espera al ciclo normal."
        ),
    }


def retargeting(*, visitas: list[dict[str, Any]], excluir_clientes: bool = True) -> dict[str, Any]:
    """Prepara una audiencia de retargeting a partir de comportamiento.

    Con dos exclusiones que casi nadie pone y que se notan enseguida:

    **A quien ya ha comprado no se le persigue con el anuncio de lo que compró.**
    Es la queja más habitual de cualquier campaña y da imagen de no tener ni idea
    de con quién se habla.

    **Y a quien se dio de baja tampoco.** Un anuncio no es un correo, pero para la
    persona es lo mismo: la empresa que le sigue después de haberle dicho que no.
    """
    dentro: list[dict[str, Any]] = []
    fuera_clientes = 0
    fuera_bajas = 0
    for visita in visitas:
        if visita.get("baja_publicidad"):
            fuera_bajas += 1
            continue
        if excluir_clientes and visita.get("ya_cliente"):
            fuera_clientes += 1
            continue
        dentro.append({"hash": _trocear(str(visita.get("email") or ""))})

    return {
        "audiencia": dentro,
        "excluidos_por_ser_clientes": fuera_clientes,
        "excluidos_por_baja": fuera_bajas,
        "porque_se_excluye_a_los_clientes": (
            "Perseguir con un anuncio a quien ya compró es la queja más habitual de "
            "cualquier campaña, y da imagen de no saber con quién se está hablando."
        ),
    }


# ── Canales offline en el recorrido (CRM-02.03.02.05) ─────────────────────


def preparar_paso_offline(
    *,
    canal: str,
    destinatarios: list[dict[str, Any]],
    coste_unitario: float,
    fecha_lanzamiento: date,
    hoy: date | None = None,
) -> dict[str, Any]:
    """Prepara un paso de correo postal o telemarketing dentro de un recorrido.

    Con la diferencia que lo cambia todo: **no se puede cancelar**. Una carta
    impresa ya está impresa y una llamada hecha no se deshace, así que la
    comprobación va antes del lanzamiento y no después — y el recorrido tiene que
    poder pararse en el paso anterior.

    Además cuesta dinero por unidad, y a diferencia de un correo, mucho: mandar
    diez mil cartas por error no es un incidente, es una factura.
    """
    if canal not in CANALES_OFFLINE:
        raise ErrorValidacion(
            f"Canal «{canal}» no es de los que salen del CRM hacia fuera del digital",
            error_code="offline.canal_invalido",
            detalle={"admitidos": list(CANALES_OFFLINE)},
        )
    momento = hoy or _ahora().date()
    if fecha_lanzamiento < momento:
        raise ErrorValidacion(
            "La fecha de lanzamiento ya ha pasado", error_code="offline.fecha_pasada"
        )

    sin_direccion = [
        d
        for d in destinatarios
        if canal == "correo_postal" and not str(d.get("direccion_postal") or "").strip()
    ]
    sin_telefono = [
        d
        for d in destinatarios
        if canal in ("telemarketing", "sms_certificado")
        and not str(d.get("telefono") or "").strip()
    ]
    en_lista_robinson = [d for d in destinatarios if d.get("excluido_por_lista")]

    validos = [
        d
        for d in destinatarios
        if d not in sin_direccion and d not in sin_telefono and d not in en_lista_robinson
    ]

    return {
        "canal": canal,
        "destinatarios": len(validos),
        "sin_datos_de_contacto": len(sin_direccion) + len(sin_telefono),
        "excluidos_por_lista_de_exclusion": len(en_lista_robinson),
        "coste_estimado": round(len(validos) * coste_unitario, 2),
        "irreversible": canal in IRREVERSIBLES,
        "se_lanza_ya": False,
        "que_hacer": (
            "Revisar el coste y confirmar. Este paso **no se puede cancelar**: una "
            "carta impresa ya está impresa y una llamada hecha no se deshace, así que "
            "la comprobación va antes."
            if canal in IRREVERSIBLES
            else "Revisar y confirmar."
        ),
        "aviso": (
            ""
            if not en_lista_robinson
            else f"{len(en_lista_robinson)} personas están en una lista de exclusión "
            "publicitaria. No entran: llamar a alguien que está en Robinson es una "
            "sanción, no un descuido."
        ),
    }


def resultado_offline(*, envios: list[dict[str, Any]]) -> dict[str, Any]:
    """Qué ha pasado con un paso offline, **sabiendo lo poco que se puede saber**.

    Una carta no tiene apertura ni clic. Lo único medible es lo que vuelve: una
    devolución, una llamada al número de la campaña, un código usado. Fingir
    métricas de digital en un canal que no las tiene es lo que hace que las
    comparaciones entre canales no valgan nada.
    """
    devueltos = [e for e in envios if e.get("devuelto")]
    respuestas = [e for e in envios if e.get("respondio")]
    return {
        "enviados": len(envios),
        "devueltos": len(devueltos),
        "respuestas": len(respuestas),
        "tasa_respuesta": (round(len(respuestas) / len(envios) * 100, 2) if envios else 0.0),
        "no_hay_apertura_ni_clic": True,
        "porque": (
            "Una carta no tiene apertura ni clic. Lo único medible es lo que vuelve, y "
            "fingir métricas de digital aquí hace que las comparaciones entre canales "
            "no valgan nada."
        ),
        "las_devoluciones_importan": (
            f"{len(devueltos)} devoluciones: además de coste perdido, son direcciones "
            "malas que conviene corregir antes del siguiente envío."
            if devueltos
            else ""
        ),
    }


# ── Personalización web (CRM-02.03.02.07) ─────────────────────────────────


def contenido_para(
    *, visitante: dict[str, Any], reglas: list[dict[str, Any]], anonimo_por_defecto: str = ""
) -> dict[str, Any]:
    """Qué contenido servir a este visitante, por API, desde el sitio del cliente.

    Dos cosas que hacen falta y que se olvidan:

    **Un visitante que no se ha identificado no es «uno cualquiera» al que se le
    puede enseñar todo**: es alguien de quien no se sabe nada, y lo que se le
    sirve es lo genérico. Adivinar por IP o por el dispositivo produce
    personalizaciones que dan entre risa y susto.

    **Y la regla que se aplica se devuelve.** Cuando el cliente pregunte por qué a
    su director le salió el bloque de «pymes», tiene que haber una respuesta que no
    sea «lo decide el algoritmo».
    """
    identificado = bool(visitante.get("contacto_id"))
    if not identificado:
        return {
            "contenido": anonimo_por_defecto,
            "personalizado": False,
            "porque": (
                "El visitante no está identificado. No se adivina por IP ni por el "
                "dispositivo: eso produce personalizaciones que dan entre risa y susto."
            ),
        }

    for regla in sorted(reglas, key=lambda r: int(r.get("prioridad") or 100)):
        campo = str(regla.get("campo") or "")
        esperado = regla.get("valor")
        if campo and str(visitante.get(campo)) == str(esperado):
            return {
                "contenido": regla.get("contenido"),
                "personalizado": True,
                "regla": regla.get("nombre"),
                "porque": (
                    f"Se ha aplicado «{regla.get('nombre')}»: {campo} = {esperado}. La "
                    "regla se devuelve para que la respuesta a «¿por qué le salió "
                    "esto?» no sea «lo decide el algoritmo»."
                ),
            }

    return {
        "contenido": anonimo_por_defecto,
        "personalizado": False,
        "porque": "Ninguna regla encaja con este visitante: se sirve lo genérico.",
    }


def comprobar_reglas_web(*, reglas: list[dict[str, Any]]) -> dict[str, Any]:
    """Qué le pasa a un conjunto de reglas de personalización.

    Lo que rompe una personalización web no es una regla mal escrita: son **dos
    reglas que encajan a la vez** sin prioridad declarada. Entonces el contenido
    depende del orden en que lleguen de la base, cambia solo, y nadie puede
    reproducirlo.
    """
    problemas: list[dict[str, str]] = []
    prioridades: dict[int, list[str]] = {}
    for regla in reglas:
        nombre = str(regla.get("nombre") or "(sin nombre)")
        if not regla.get("contenido"):
            problemas.append({"regla": nombre, "problema": "no dice qué contenido servir"})
        prioridad = int(regla.get("prioridad") or 100)
        prioridades.setdefault(prioridad, []).append(nombre)

    empates = {p: n for p, n in prioridades.items() if len(n) > 1}
    return {
        "valido": not problemas and not empates,
        "problemas": problemas,
        "empates_de_prioridad": empates,
        "porque": (
            "Dos reglas con la misma prioridad hacen que el contenido dependa del orden "
            "en que lleguen de la base: cambia solo y nadie puede reproducirlo."
            if empates
            else "Las prioridades están declaradas y no hay empates."
        ),
    }
