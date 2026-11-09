"""El webhook que dispara una automatización desde fuera (CRM-00.03.03.02).

«Webhook» se podía elegir como disparador y no había ninguna dirección a la que
llamar: la regla se guardaba y no la disparaba nadie. Aquí está esa dirección y
lo que la protege.

**Lo que autoriza es la firma, no un usuario.** Quien llama es otro sistema
—una tienda, un formulario, un ERP— que no tiene sesión en el CRM. Cada
automatización tiene su propio secreto, y el cuerpo llega firmado con él.

**La firma es la de la casa**, la misma con la que el CRM firma sus webhooks
salientes (`crmcore.security.firma`): HMAC-SHA256 de `<momento>.<cuerpo>`, con
el instante dentro y una ventana contra reenvíos. Quien ya verifica lo que el
CRM le manda sabe firmar lo que le manda al CRM, y un mensaje capturado no se
puede repetir pasada la ventana — lo que hay al otro lado son acciones sobre
datos de clientes.

**Todo fallo de autorización contesta lo mismo.** Regla que no existe, sin
secreto o firma mala: una respuesta distinta para cada caso le dice a quien
prueba qué le falta.
"""

from __future__ import annotations

import json
import secrets
from typing import Any
from uuid import UUID

from crmcore.errors import ErrorValidacion, NoAutenticado, NoEncontrado
from crmcore.logging import get_logger
from crmcore.security.cifrado import cifrar, descifrar
from sqlalchemy import select

from services.automation.modelos import Automatizacion, SecretoWebhookAutomatizacion

logger = get_logger(__name__)

# El propósito con el que se cifra el secreto. Distinto del de otros secretos:
# así una clave de un propósito no abre los de otro.
PROPOSITO = "automatizacion_webhook"


def _rechazo() -> NoAutenticado:
    return NoAutenticado(
        "La firma no es válida, ha caducado o esa automatización no admite webhooks",
        error_code="automatizacion.webhook_no_autorizado",
    )


def ruta(tenant_id: UUID, regla_id: UUID) -> str:
    """La dirección a la que llama el otro sistema, a partir de la raíz pública."""
    return f"/api/v1/automatizaciones/webhook/{tenant_id}/{regla_id}"


def generar_secreto(uow: Any, *, regla_id: UUID, por: UUID | None) -> dict[str, Any]:
    """Crea —o cambia— el secreto y lo devuelve **una sola vez**."""
    from crmcore.audit.chain import registrar
    from crmcore.security.firma import H_FIRMA, H_MOMENTO

    regla = uow.db.get(Automatizacion, regla_id)
    if regla is None or regla.tenant_id != uow.tenant_id or regla.deleted_at is not None:
        raise NoEncontrado("La automatización no existe", error_code="automatizacion.no_encontrada")
    if regla.disparador != "webhook":
        raise ErrorValidacion(
            "Sólo las automatizaciones con disparador «webhook» tienen secreto: a las "
            "demás no las dispara nadie desde fuera",
            error_code="automatizacion.no_es_webhook",
        )
    secreto = secrets.token_urlsafe(32)
    fila = (
        uow.db.execute(
            select(SecretoWebhookAutomatizacion).where(
                SecretoWebhookAutomatizacion.automatizacion_id == regla.id
            )
        )
        .scalars()
        .first()
    )
    cambiado = fila is not None
    if fila is None:
        fila = SecretoWebhookAutomatizacion(tenant_id=uow.tenant_id, automatizacion_id=regla.id)
        uow.db.add(fila)
    fila.secreto = cifrar(secreto, proposito=PROPOSITO, db=uow.db)
    fila.generado_por = por
    uow.db.flush()
    # Consta quién lo generó, nunca el secreto.
    registrar(
        uow.db,
        accion="automatizacion.secreto_webhook",
        objeto="automatizacion",
        objeto_id=regla.id,
        datos={"nombre": regla.nombre, "cambiado": cambiado},
    )
    return {
        "url": ruta(uow.tenant_id, regla.id),
        "secreto": secreto,
        "cabecera_firma": H_FIRMA,
        "cabecera_momento": H_MOMENTO,
        "como_firmar": (
            "HMAC-SHA256 con este secreto de «<momento>.<cuerpo>», en hexadecimal; "
            "el momento son los segundos desde 1970 y va también en su cabecera."
        ),
        "aviso": (
            "Guárdalo ahora: no se vuelve a enseñar."
            + (" El anterior ya no vale." if cambiado else "")
        ),
    }


def recibir(uow: Any, *, regla_id: UUID, cuerpo: bytes, firma: str, momento: str) -> dict[str, Any]:
    """Comprueba la firma y dispara la regla, en su momento."""
    from crmcore.security.firma import verificar_firma

    from services.automation import planificador

    regla = uow.db.get(Automatizacion, regla_id)
    fila = (
        uow.db.execute(
            select(SecretoWebhookAutomatizacion).where(
                SecretoWebhookAutomatizacion.automatizacion_id == regla_id,
                SecretoWebhookAutomatizacion.tenant_id == uow.tenant_id,
            )
        )
        .scalars()
        .first()
    )
    if (
        regla is None
        or regla.tenant_id != uow.tenant_id
        or regla.deleted_at is not None
        or regla.disparador != "webhook"
        or fila is None
        or not firma
    ):
        raise _rechazo()
    try:
        instante = int(momento)
    except (TypeError, ValueError):
        raise _rechazo() from None
    if not verificar_firma(
        cuerpo,
        descifrar(fila.secreto, proposito=PROPOSITO, db=uow.db),
        firma.strip().lower(),
        instante,
    ):
        logger.warning("automatizacion.webhook_firma_mala", regla=str(regla_id))
        raise _rechazo()

    # El cuerpo se lee DESPUÉS de comprobar la firma: hasta ahí no se cree nada.
    try:
        entrada = json.loads(cuerpo or b"{}")
    except (ValueError, UnicodeDecodeError):
        raise ErrorValidacion(
            "El cuerpo no es JSON válido", error_code="peticion.cuerpo_no_json"
        ) from None
    valores = entrada if isinstance(entrada, dict) else {"cuerpo": entrada}

    if not regla.activa:
        # Firmado y bien: se acepta y se dice que no corre, para que el otro
        # lado no lo reintente como si fuera un fallo.
        return {"recibido": True, "disparada": False, "motivo": "La automatización está apagada"}

    registro_id = str(valores.get("registro_id") or "") or None
    resultado = planificador.ejecutar_o_encolar(
        uow,
        regla,
        origen="webhook",
        # La firma es única por mensaje: el mismo mensaje reenviado dentro de la
        # ventana choca con la clave y no encola dos veces.
        clave=f"webhook:{instante}:{firma.strip().lower()[:64]}",
        objeto=regla.objetivo,
        registro_id=registro_id,
        valores={**valores, "_webhook": True},
    )
    return {"recibido": True, "disparada": True, **resultado}
