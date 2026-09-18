"""Entrega de webhooks: firma, reintentos y salud del endpoint."""

from __future__ import annotations

import hashlib
import hmac
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import httpx
from crmcore.events.envelope import Evento
from crmcore.logging import get_logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.eventing.modelos import Entrega, Suscripcion

logger = get_logger(__name__)

# Fallos seguidos tras los que se desactiva una suscripción. Un endpoint que
# lleva veinte entregas fallando está caído o ya no existe, y seguir
# intentándolo es tráfico, ruido en los logs y una cola que no se vacía nunca.
FALLOS_PARA_DESACTIVAR = 20

# Cabeceras del contrato de entrega. Se documentan en el manual del integrador,
# y son las que permiten verificar el mensaje sin confiar en la red.
H_FIRMA = "X-Contecrm-Firma"
H_MOMENTO = "X-Contecrm-Momento"
H_EVENTO = "X-Contecrm-Evento"
H_TIPO = "X-Contecrm-Tipo"
H_DEDUP = "X-Contecrm-Dedup"
H_INTENTO = "X-Contecrm-Intento"


def firmar(cuerpo: bytes, secreto: str, momento: int) -> str:
    """Firma HMAC-SHA256 del cuerpo y el instante.

    El instante entra en la firma, y esa es la parte que impide el replay: sin
    él, un mensaje capturado se podría reenviar tal cual dentro de un año con su
    firma intacta.
    """
    material = f"{momento}.".encode() + cuerpo
    return hmac.new(secreto.encode(), material, hashlib.sha256).hexdigest()


def verificar_firma(
    cuerpo: bytes, secreto: str, firma: str, momento: int, *, ventana_s: int = 300
) -> bool:
    """Verificación de referencia, para que el integrador la copie.

    Se publica en el manual porque la mitad de las integraciones que fallan lo
    hacen por implementar mal esta comprobación: comparando con `==` (que filtra
    por tiempo), olvidando la ventana, o firmando el JSON reserializado en vez
    de los bytes recibidos.
    """
    if abs(time.time() - momento) > ventana_s:
        return False
    return hmac.compare_digest(firmar(cuerpo, secreto, momento), firma)


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
        op = OPERADORES.get(str(condicion.get("op", "=")))
        if op is None:
            continue
        izquierda = resolver(f"@{condicion.get('atributo', '')}", evento.data)
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
        async with httpx.AsyncClient(timeout=s.webhook_timeout_s, follow_redirects=False) as cli:
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
        if suscripcion.fallos_consecutivos >= FALLOS_PARA_DESACTIVAR:
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
