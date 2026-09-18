"""Protección del dato: cifrado, secretos y cabeceras."""

from __future__ import annotations

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings


class _SecuritySettings(BaseSettings):
    # ── Cifrado de campo (CRM-00.05.03.02) ────────────────────────────────
    # Clave maestra de la que derivan las claves de cifrado de campo. Si está
    # vacía, los campos marcados como cifrados NO se pueden escribir y el
    # arranque avisa: preferimos un fallo visible a guardar en claro algo que
    # el modelo declaró sensible.
    encryption_key: SecretStr = SecretStr("")
    # Clave anterior, para poder descifrar lo escrito antes de una rotación.
    # Mantenerla mientras dura el recifrado es lo que hace la rotación posible
    # sin ventana de caída.
    encryption_key_previa: SecretStr = SecretStr("")
    # BYOK/CMEK (CRM-00.01.04.09): cuando está activo, la clave la aporta el
    # tenant y se guarda cifrada con la maestra. Revocarla deja sus datos
    # ilegibles a propósito, que es justo lo que el cliente compra.
    byok_enabled: bool = False

    # ── Secretos de integración (CRM-00.01.04.08) ─────────────────────────
    # Backend del almacén de secretos por tenant. `db` los guarda cifrados en
    # la base; `vault` delega en un gestor externo. Genérico a propósito: la
    # configuración decide, no el código.
    secretos_backend: str = "db"
    secretos_vault_url: str = ""

    # ── Enmascaramiento (CRM-00.05.03.03) ─────────────────────────────────
    # Aplicar máscara por rol en las respuestas de API y en las exportaciones.
    # Se hace en la serialización, no en la consulta, para que el mismo dato se
    # vea completo o enmascarado según quién pregunte sin duplicar consultas.
    masking_enabled: bool = True

    # ── DLP (CRM-00.05.03.06) ─────────────────────────────────────────────
    dlp_enabled: bool = True
    # Filas a partir de las cuales una exportación se considera masiva: se
    # audita siempre y, según política, se bloquea o pide aprobación.
    dlp_export_filas_aviso: int = Field(5_000, ge=1, le=10_000_000)
    dlp_export_filas_bloqueo: int = Field(100_000, ge=0, le=100_000_000)

    # ── Papelera (CRM-00.06.02.04) ────────────────────────────────────────
    # Días que un registro borrado se conserva antes de poder destruirse. Un mes
    # es el plazo con el que casi todos los errores humanos se detectan: quien
    # borró algo por error lo echa en falta en la siguiente revisión mensual.
    papelera_dias_retencion: int = Field(30, ge=1, le=3650)

    # ── Cabeceras de seguridad ────────────────────────────────────────────
    # HSTS en segundos. 0 = no se envía. Un año es el valor que piden las
    # listas de precarga.
    hsts_max_age: int = Field(31_536_000, ge=0, le=63_072_000)
    # Confiar en las cabeceras de proxy (X-Forwarded-For). Solo debe activarse
    # si de verdad hay un proxy delante: si no, cualquiera falsea su IP y se
    # salta el rate limiting y las listas de permitidos.
    trust_proxy_headers: bool = False
    # Redes desde las que se aceptan esas cabeceras, separadas por comas.
    trusted_proxies: str = ""
