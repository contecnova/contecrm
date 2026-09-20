"""Correo por SMTP. Un solo transporte para todos los proveedores.

SMTP y no la API de un proveedor concreto, y conviene entender por qué: lo
hablan todos —SendGrid, SES, Mailgun, Postmark— y también el servidor
corporativo del cliente que no quiere que su correo salga de su red. Con un
conector por proveedor, cada cliente con uno distinto es una versión del
producto; con SMTP, es una fila del `.env`.

El precio, dicho: no hay estadísticas de apertura ni de rebote, que sí dan las
APIs propietarias. Cuando eso haga falta se añade un transporte aparte para
quien lo quiera, y se dirá que ata la instalación a ese proveedor.
"""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from typing import Any

from crmcore.logging import get_logger
from crmcore.notificaciones.base import Destino, Mensaje, Resultado

logger = get_logger(__name__)

# Errores de SMTP que NO se reintentan: son definitivos y reintentarlos llena la
# cola de algo que nunca va a salir. El 5xx es permanente por definición del
# protocolo; el 550 y el 553 son «esa dirección no existe o no la acepto».
CODIGOS_DEFINITIVOS = (550, 551, 553, 554)


class TransporteSMTP:
    canal = "correo"

    def entregar(self, destino: Destino, mensaje: Mensaje, config: dict[str, Any]) -> Resultado:
        from crmcore.config import get_settings

        if not destino.direccion:
            # No es un fallo del sistema: es un dato incompleto. No se reintenta.
            return Resultado(False, "el destinatario no tiene correo", reintentar=False)

        s = get_settings()
        host = str(config.get("host") or s.smtp_host)
        if not host:
            # Sin servidor configurado no se puede entregar, pero SÍ se
            # reintenta: es un fallo de configuración que alguien va a arreglar,
            # y descartar los avisos entretanto perdería lo que se quería mandar.
            return Resultado(False, "no hay servidor SMTP configurado", reintentar=True)

        correo = EmailMessage()
        correo["Subject"] = mensaje.titulo
        correo["From"] = self._remitente(config, s)
        correo["To"] = (
            f"{destino.nombre} <{destino.direccion}>" if destino.nombre else destino.direccion
        )
        # Cabeceras que evitan que una respuesta automática de vacaciones genere
        # otro aviso, y ese aviso otra respuesta. Es el bucle clásico de los
        # sistemas que mandan correo, y cuesta una línea evitarlo.
        correo["Auto-Submitted"] = "auto-generated"
        correo["X-Auto-Response-Suppress"] = "All"
        if mensaje.objeto_tipo and mensaje.objeto_id:
            # Agrupa en el hilo del registro: todos los avisos de la misma
            # oportunidad caen juntos en el cliente de correo en vez de
            # convertirse en veinte mensajes sueltos.
            correo["References"] = f"<{mensaje.objeto_tipo}.{mensaje.objeto_id}@contecrm>"
        correo.set_content(mensaje.cuerpo)

        try:
            self._enviar(correo, host, config, s)
        except smtplib.SMTPResponseException as exc:
            definitivo = exc.smtp_code in CODIGOS_DEFINITIVOS or 500 <= exc.smtp_code < 600
            return Resultado(
                False,
                f"SMTP {exc.smtp_code}: {exc.smtp_error!r}"[:300],
                reintentar=not definitivo,
            )
        except Exception as exc:  # noqa: BLE001 — un transporte nunca lanza
            # Red, DNS, TLS: casi siempre transitorio, así que se reintenta.
            return Resultado(False, f"{type(exc).__name__}: {exc}"[:300], reintentar=True)

        return Resultado(True, "entregado")

    def _remitente(self, config: dict[str, Any], s: Any) -> str:
        """El «De», con la marca del tenant si la tiene.

        Va por configuración del tenant y no fijo porque un aviso que llega
        desde `no-reply@contecrm.dev` a un cliente del cliente no lo abre nadie
        (CRM-00.01.04.06, marca blanca).
        """
        direccion = str(config.get("remitente") or s.smtp_remitente or "no-reply@localhost")
        nombre = str(config.get("remitente_nombre") or s.app_name)
        return f"{nombre} <{direccion}>" if nombre else direccion

    def _enviar(self, correo: EmailMessage, host: str, config: dict[str, Any], s: Any) -> None:
        puerto = int(config.get("puerto") or s.smtp_puerto)
        usuario = str(config.get("usuario") or s.smtp_usuario)
        clave = str(
            config.get("clave") or (s.smtp_clave.get_secret_value() if s.smtp_clave else "")
        )
        modo = str(config.get("tls") or s.smtp_tls)

        # Contexto por defecto: verifica el certificado y el nombre. Desactivar
        # la verificación «porque el certificado del servidor interno es
        # autofirmado» convierte el TLS en un adorno, así que si hace falta se
        # añade la CA al sistema, no se apaga la comprobación.
        contexto = ssl.create_default_context()
        if modo == "ssl":
            with smtplib.SMTP_SSL(host, puerto, timeout=s.smtp_timeout_s, context=contexto) as smtp:
                self._autenticar_y_mandar(smtp, correo, usuario, clave)
            return

        with smtplib.SMTP(host, puerto, timeout=s.smtp_timeout_s) as smtp:
            if modo == "starttls":
                smtp.starttls(context=contexto)
            elif modo == "ninguno" and (usuario or clave):
                # Mandar la contraseña por un canal en claro es peor que no
                # tener contraseña: la regala a quien mire la red.
                raise RuntimeError(
                    "SMTP_TLS=ninguno con credenciales: la contraseña viajaría en claro"
                )
            self._autenticar_y_mandar(smtp, correo, usuario, clave)

    def _autenticar_y_mandar(
        self, smtp: Any, correo: EmailMessage, usuario: str, clave: str
    ) -> None:
        if usuario:
            smtp.login(usuario, clave)
        smtp.send_message(correo)
