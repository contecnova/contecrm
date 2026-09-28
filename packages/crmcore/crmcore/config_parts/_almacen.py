"""Almacenamiento de ficheros y política de adjuntos (CRM-06.01.01.05)."""

from __future__ import annotations

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings


class _AlmacenSettings(BaseSettings):
    # ── Backend ───────────────────────────────────────────────────────────
    # `local` o `s3`. `s3` vale para cualquier compatible —AWS, MinIO, Ceph,
    # Backblaze— porque lo que se configura es el endpoint, no el proveedor.
    storage_backend: str = Field("local", pattern="^(local|s3)$")
    storage_local_path: str = "./datos/adjuntos"

    storage_s3_bucket: str = ""
    storage_s3_prefijo: str = ""
    storage_s3_region: str = ""
    storage_s3_endpoint: str = ""
    storage_s3_access_key: str = ""
    storage_s3_secret_key: SecretStr | None = None
    storage_s3_ssl: bool = True
    # Estilo de ruta (`bucket` en el path y no en el host). Hace falta con MinIO
    # y con casi todos los compatibles, que no montan DNS comodín.
    storage_s3_estilo_ruta: bool = False

    # ── Política de adjuntos ──────────────────────────────────────────────
    # Tamaño máximo por fichero, en MB. 25 es el límite práctico del correo, que
    # es de donde llega la mayoría de adjuntos.
    adjunto_max_mb: int = Field(25, ge=1, le=5_000)

    # Tope de espacio por tenant EN ESTE MÓDULO. Cero es sin límite, y es el
    # valor por defecto a propósito: un despliegue que no ha configurado cuotas
    # no puede quedarse sin poder subir nada porque a alguien se le olvidara
    # declararlas. La omisión abre, nunca cierra.
    cuota_almacenamiento_mb: int = Field(0, ge=0, le=10_000_000)
    # Extensiones admitidas. **Lista blanca, no negra**: una lista negra siempre
    # se queda corta —basta una extensión nueva o una mayúscula— y lo que está
    # en juego es ejecutar algo en el navegador de quien lo descargue.
    adjunto_extensiones: list[str] = Field(
        default_factory=lambda: [
            "pdf",
            "doc",
            "docx",
            "xls",
            "xlsx",
            "ppt",
            "pptx",
            "odt",
            "ods",
            "txt",
            "csv",
            "rtf",
            "md",
            "png",
            "jpg",
            "jpeg",
            "gif",
            "webp",
            "svg",
            "bmp",
            "tiff",
            "zip",
            "7z",
            "gz",
            "tar",
            "eml",
            "msg",
            "vcf",
            "ics",
            "mp3",
            "mp4",
            "wav",
            "mov",
            "avi",
            "webm",
            "dwg",
            "dxf",
            "step",
            "stp",
            "iges",
            "igs",
        ]
    )
    # Guardar una sola copia de dos ficheros idénticos (mismo SHA-256). Ahorra
    # mucho en un CRM, donde el mismo PDF de condiciones se adjunta a cien
    # oportunidades.
    adjunto_deduplicar: bool = True
    # Cuántas versiones de un documento se conservan. 0 = todas.
    adjunto_max_versiones: int = Field(0, ge=0, le=1_000)
    # Segundos que vive un enlace de descarga firmado. Corto a propósito: el
    # enlace lleva la autorización dentro y viaja por correo y por chat.
    adjunto_enlace_ttl_s: int = Field(300, ge=30, le=86_400)
    # Exigir que el antivirus haya dado el visto bueno antes de poder descargar.
    # Apagado por defecto porque no todas las instalaciones tienen uno; cuando
    # se enciende sin analizador configurado, el arranque avisa.
    adjunto_exigir_analisis: bool = False
    # URL del analizador (ICAP, clamd HTTP o el que sea). Vacío = sin análisis.
    adjunto_analizador_url: str = ""
