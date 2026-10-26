"""Entrega de webhooks: firma, reintentos y salud del endpoint."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from crmcore.events.envelope import Evento
from crmcore.logging import get_logger
from crmcore.red import cliente_seguro_async
from crmcore.security.firma import H_FIRMA, H_MOMENTO, firmar
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.eventing.modelos import Entrega, Suscripcion

logger = get_logger(__name__)


# Fallos seguidos tras los que se desactiva una suscripción. Un endpoint que
# lleva veinte entregas fallando está caído o ya no existe, y seguir
# intentándolo es tráfico, ruido en los logs y una cola que no se vacía nunca.
def _webhook_fallos_para_desactivar() -> int:
    """Antes `_webhook_fallos_para_desactivar() = 20`.

    Era una constante de módulo. Sale del `.env`, que es donde una instalación
    puede afinarla sin tocar código.
    """
    from crmcore.config import get_settings

    return get_settings().webhook_fallos_para_desactivar


# Cabeceras propias de la entrega de eventos. La firma y el momento vienen de
# `crmcore.security.firma`, que es donde viven desde que el aviso de fin de un
# trabajo asíncrono empezó a usar el mismo esquema: una sola implementación del
# HMAC, y el manual del integrador describe la que corre en los dos sitios.
H_EVENTO = "X-Contecrm-Evento"
H_TIPO = "X-Contecrm-Tipo"
H_DEDUP = "X-Contecrm-Dedup"
H_INTENTO = "X-Contecrm-Intento"


def coincide(suscripcion: Suscripcion, evento: Evento) -> bool:
    """Si la suscripción quiere este evento: por tipo y por condiciones."""
    from services.orchestrator.motor import OPERADORES, resolver

    patrones = suscripcion.eventos or []
    encaja = any(
        evento.type == p or (p.endswith("*") and evento.type.startswith(p[:-1])) for p in patrones
    )
    if not encaja:
        return False

    for condicion in suscripcion.condiciones or []:
        # **Una condición que no se puede evaluar NO encaja.** Es la misma
        # trampa que tenía el motor de procesos y se arregló el mismo día: un
        # operador desconocido se saltaba la condición —`continue`— y una sin
        # atributo comparaba nulo con nulo, que da cierto. Las dos hacían que
        # una suscripción con la condición mal escrita recibiera **todo**, que
        # en un webhook es mandarle al integrador datos que no pidió.
        #
        # Se rechaza también al darla de alta, así que esto es el suelo: cubre
        # las suscripciones guardadas antes de que existiera esa comprobación.
        op = OPERADORES.get(str(condicion.get("op", "=")))
        atributo = str(condicion.get("atributo") or "").strip()
        if op is None or not atributo:
            return False
        izquierda = resolver(f"@{atributo}", evento.data)
        derecha = resolver(condicion.get("valor"), evento.data)
        try:
            if not op(izquierda, derecha):
                return False
        except TypeError:
            return False
    return True


async def entregar(
    db: Session, suscripcion: Suscripcion, evento: Evento, *, intento: int = 1
) -> Entrega:
    """Entrega un evento a un endpoint y registra el resultado."""
    from crmcore.config import get_settings

    s = get_settings()
    cuerpo = evento.a_json().encode()

    # TOPE DE TAMAÑO. `WEBHOOK_MAX_PAYLOAD_KB` existía en los ajustes,
    # documentado —«un payload gigante es casi siempre un error de diseño y
    # además revienta al receptor»— y **no lo leía nadie**: se mandaba lo que
    # hubiera.
    #
    # No se recorta el cuerpo: un JSON cortado por la mitad es peor que no
    # mandarlo, porque el receptor lo parsea, falla, y lo que ve en su registro
    # es «JSON inválido» y no «esto era demasiado grande». Se falla aquí, con el
    # motivo dentro, y el reintento no lo va a arreglar — pero la entrega queda
    # registrada con su causa, que es lo que hace falta para corregir el evento.
    tope = int(s.webhook_max_payload_kb) * 1024
    if len(cuerpo) > tope:
        logger.error(
            "entrega.payload_demasiado_grande",
            evento=str(evento.id),
            tipo=evento.type,
            bytes=len(cuerpo),
            tope=tope,
        )
        descartada = Entrega(
            tenant_id=suscripcion.tenant_id,
            suscripcion_id=suscripcion.id,
            evento_id=evento.id,
            tipo=evento.type,
            dedup_key=evento.dedup_key,
            intento=intento,
            resultado="fallido",
            duracion_ms=0,
            error=(
                f"El evento ocupa {len(cuerpo) // 1024} KB y el tope de entrega son "
                f"{s.webhook_max_payload_kb} KB. Reintentarlo no lo va a arreglar: "
                "hay que reducir lo que el evento lleva dentro."
            ),
        )
        # NO se programa reintento: no es un fallo de red, es un evento que no
        # cabe. Reintentarlo cada pocos minutos para siempre llena la tabla de
        # entregas y tapa los fallos que sí se arreglan solos.
        db.add(descartada)
        db.flush()
        return descartada

    momento = int(time.time())
    cabeceras = {
        "Content-Type": "application/json",
        H_FIRMA: firmar(cuerpo, suscripcion.secreto, momento),
        H_MOMENTO: str(momento),
        H_EVENTO: str(evento.id),
        H_TIPO: evento.type,
        # La clave de deduplicación va en cabecera además de en el cuerpo: así
        # el receptor puede descartar un duplicado sin parsear el JSON.
        H_DEDUP: evento.dedup_key,
        H_INTENTO: str(intento),
        **{str(k): str(v) for k, v in (suscripcion.cabeceras or {}).items()},
    }

    registro = Entrega(
        tenant_id=suscripcion.tenant_id,
        suscripcion_id=suscripcion.id,
        evento_id=evento.id,
        tipo=evento.type,
        dedup_key=evento.dedup_key,
        intento=intento,
    )
    inicio = time.perf_counter()
    try:
        # Cliente con guard de SSRF: la URL la escribe el cliente, así que sin
        # él un webhook contra `169.254.169.254` se lleva las credenciales de la
        # máquina, y uno contra `postgres:5432` escanea la red desde dentro. Se
        # valida en cada entrega y no solo al darla de alta: el DNS del dominio
        # puede cambiar después, y el que se registró apuntando fuera puede
        # apuntar dentro mañana.
        async with cliente_seguro_async(timeout=s.webhook_timeout_s, follow_redirects=False) as cli:
            respuesta = await cli.post(suscripcion.url, content=cuerpo, headers=cabeceras)
        registro.codigo_http = respuesta.status_code
        # Se guarda un recorte de la respuesta: lo justo para depurar con el
        # integrador sin almacenar cuerpos enteros de miles de entregas.
        registro.respuesta = respuesta.text[:2000]
        if 200 <= respuesta.status_code < 300:
            registro.resultado = "entregado"
            suscripcion.fallos_consecutivos = 0
            suscripcion.ultimo_exito_at = datetime.now(timezone.utc)
        else:
            registro.resultado = "fallido"
            registro.error = f"HTTP {respuesta.status_code}"
            _programar_reintento(registro, suscripcion, intento, s)
    except Exception as exc:  # noqa: BLE001 — red, DNS, TLS, timeout: todo es un fallo de entrega
        registro.resultado = "fallido"
        registro.error = f"{type(exc).__name__}: {str(exc)[:500]}"
        _programar_reintento(registro, suscripcion, intento, s)

    registro.duracion_ms = int((time.perf_counter() - inicio) * 1000)
    db.add(registro)

    if registro.resultado == "fallido":
        suscripcion.fallos_consecutivos += 1
        if suscripcion.fallos_consecutivos >= _webhook_fallos_para_desactivar():
            suscripcion.activa = False
            suscripcion.desactivada_at = datetime.now(timezone.utc)
            logger.error(
                "webhook.suscripcion_desactivada",
                suscripcion=str(suscripcion.id),
                fallos=suscripcion.fallos_consecutivos,
            )
    return registro


def _programar_reintento(registro: Entrega, suscripcion: Suscripcion, intento: int, s: Any) -> None:
    """Backoff exponencial, o descarte si se agotaron los intentos."""
    if intento >= s.webhook_max_intentos:
        registro.resultado = "descartado"
        registro.proximo_intento_at = None
        logger.warning(
            "webhook.entrega_descartada",
            suscripcion=str(suscripcion.id),
            tipo=registro.tipo,
            intentos=intento,
        )
        return
    espera = min(s.webhook_backoff_base_s * (2 ** (intento - 1)), 3600)
    registro.proximo_intento_at = datetime.now(timezone.utc) + timedelta(seconds=espera)


def pendientes_de_reintento(db: Session, *, limite: int = 50) -> list[Entrega]:
    """Entregas fallidas cuyo momento de reintento ya ha llegado."""
    return list(
        db.execute(
            select(Entrega)
            .where(
                Entrega.resultado == "fallido",
                Entrega.proximo_intento_at.is_not(None),
                Entrega.proximo_intento_at <= datetime.now(timezone.utc),
            )
            .order_by(Entrega.proximo_intento_at)
            .limit(limite)
            .with_for_update(skip_locked=True)
        )
        .scalars()
        .all()
    )


def suscripciones_interesadas(db: Session, evento: Evento) -> list[Suscripcion]:
    """Suscripciones activas del tenant que quieren este evento."""
    candidatas = (
        db.execute(
            select(Suscripcion).where(
                Suscripcion.tenant_id == evento.tenant_id,
                Suscripcion.activa.is_(True),
            )
        )
        .scalars()
        .all()
    )
    return [s for s in candidatas if coincide(s, evento)]


def _sin_usar(_x: UUID) -> None:  # pragma: no cover
    """Mantiene el import de UUID para las anotaciones."""
