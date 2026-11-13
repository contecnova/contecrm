"""Correo a quien todavía no es usuario: el enlace de confirmar un alta y el de
entrar al portal de partner (auditoría del 13-11-2026, SEC-5 y SEC-6).

Las dos rutas devolvían el token en la respuesta «para que lo mandara quien
integrase el correo». Quien llama a esas rutas es quien pide el enlace, no el
dueño del buzón, así que el token en la respuesta era la llave entregada a
cualquiera: entrar en el portal de un partner sabiendo su correo, o dar de alta
una empresa a nombre de un correo ajeno. Y no había ningún camino por el que
ese correo pudiera salir.

**Por qué no va por la bandeja de avisos.** Los avisos son por usuario: el
repartidor saca la dirección de la ficha del usuario y de su membresía, y
descarta a quien no es miembro activo del tenant —es lo que impide que alguien
que se fue siga recibiendo movimientos de clientes—. Quien pide un alta no es
usuario de nada, y la persona de un partner tampoco: su acceso vive en `sales`.
Meterlos en la bandeja obligaría a inventarles un usuario.

**Por qué lo manda `identity`.** Es el servicio que tiene enchufados los
transportes de la instalación (`transportes.py`) y su configuración por tenant
(`canal_correo`). El servicio dueño del enlace emite un evento **interno** con
la dirección y el texto ya compuesto, y aquí solo se entrega. Ningún servicio
lee el esquema de otro, y ninguno llama a otro para mandar un correo.

**Qué pasa si no sale.** Se dice en el registro con su motivo y no se reintenta
desde aquí. El enlace caduca en minutos (el del portal) o en horas (el del
alta), quien lo pidió está delante de la pantalla y lo vuelve a pedir; y
devolver el evento al bus, que lo reentrega sin espera, convertiría un servidor
de correo caído en un bucle contra ese mismo servidor.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.events.dominio import ALTA_SOLICITADA, PARTNER_PORTAL_ENLACE, PORTAL_CLIENTE_ENLACE
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Qué eventos se convierten en un correo a una dirección y cómo. Tabla de datos,
# como `AVISOS`: lo que el sistema manda a quien no es usuario se lee entero aquí.
#
# `del_tenant` dice si la configuración del canal sale del tenant del evento (la
# marca del remitente de esa empresa) o de la instalación. El alta todavía no
# tiene tenant: el que lleva el sobre es uno de relleno.
CORREOS_EXTERNOS: dict[str, dict[str, Any]] = {
    ALTA_SOLICITADA.tipo: {"del_tenant": False, "objeto_tipo": "alta"},
    PARTNER_PORTAL_ENLACE.tipo: {"del_tenant": True, "objeto_tipo": "acceso_partner"},
    # El cliente del portal tampoco es usuario: su acceso vive en `service`.
    PORTAL_CLIENTE_ENLACE.tipo: {"del_tenant": True, "objeto_tipo": "acceso_portal"},
}


def _config_correo(tenant_id: UUID | None) -> dict[str, Any]:
    """`canal_correo` efectivo: el del tenant si lo hay, si no el global.

    Con la misma función que el repartidor, para que un aviso y un enlace de la
    misma empresa salgan con el mismo remitente.
    """
    from crmcore.db.session import sesion
    from crmcore.tenancy.context import con_contexto

    from services.identity.reparto import config_canal

    if tenant_id is None:
        with sesion(sistema=True) as db:
            return config_canal(db, "correo")
    with con_contexto(tenant_id=tenant_id, origen="correo_externo"), sesion(tenant_id) as db:
        return config_canal(db, "correo")


def entregar(tipo: str, tenant_id: UUID | None, datos: dict[str, Any], sujeto_id: Any) -> bool:
    """Manda el correo de un evento de `CORREOS_EXTERNOS`. Devuelve si salió."""
    from crmcore.notificaciones import Destino, Mensaje, transporte_de

    regla = CORREOS_EXTERNOS.get(tipo)
    if regla is None:
        return False
    direccion = str(datos.get("email") or "").strip()
    titulo = str(datos.get("titulo") or "")
    cuerpo = str(datos.get("cuerpo") or "")
    if not direccion or not cuerpo:
        # Se dice y no se lanza: un hecho mal formado que reviente el consumidor
        # se queda reintentándose y tapa los que vienen detrás.
        logger.warning("correo_externo.hecho_incompleto", tipo=tipo, campos=sorted(datos))
        return False

    transporte = transporte_de("correo")
    if transporte is None:
        logger.error("correo_externo.sin_transporte", tipo=tipo)
        return False

    config = _config_correo(tenant_id if regla["del_tenant"] else None)
    try:
        destinatario = UUID(str(sujeto_id))
    except (TypeError, ValueError):
        # `Destino` pide un identificador; el de quien no es usuario es el del
        # registro que motiva el correo (el acceso, la solicitud de alta).
        destinatario = UUID(int=0)
    resultado = transporte.entregar(
        Destino(
            usuario_id=destinatario, direccion=direccion, nombre=str(datos.get("nombre") or "")
        ),
        Mensaje(
            titulo=titulo,
            cuerpo=cuerpo,
            tipo=tipo,
            # Urgente: quien lo pide está esperándolo delante de la pantalla.
            prioridad="urgente",
            objeto_tipo=str(regla["objeto_tipo"]),
            objeto_id=str(sujeto_id or ""),
        ),
        config,
    )
    if not resultado.entregado:
        # Ni la dirección ni el cuerpo van al registro: la dirección es dato
        # personal y el cuerpo lleva el enlace, que es una credencial.
        logger.error(
            "correo_externo.no_entregado",
            tipo=tipo,
            detalle=resultado.detalle,
            reintentable=resultado.reintentar,
        )
        return False
    logger.info("correo_externo.entregado", tipo=tipo)
    return True


async def consumir_correo_externo(mensaje: Any) -> None:
    """Consumidor del bus para los eventos de `CORREOS_EXTERNOS`."""
    tipo = str(getattr(mensaje, "tipo", "") or "")
    datos = dict(getattr(mensaje, "data", None) or {})
    tenant = getattr(mensaje, "tenant_id", None)
    try:
        tenant_id = UUID(str(tenant)) if tenant else None
    except ValueError:
        tenant_id = None
    # El registro que motiva el correo: la solicitud de alta o el acceso.
    sujeto = getattr(getattr(mensaje, "subject", None), "id", None)
    entregar(tipo, tenant_id, datos, sujeto)
