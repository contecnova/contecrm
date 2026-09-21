"""Configuración de un servicio de contecrm.

Toda la configuración viene de variables de entorno (cargadas de `.env` si
existe). Los campos viven en los mixins de `config_parts/`, uno por dominio;
aquí solo se componen y se añaden las comprobaciones que cruzan dominios.

**Cero hardcodeado.** Cualquier número que cambie el comportamiento es un campo
de `Settings` con rango y con un comentario que explique de dónde sale su
default, y los que además se pueden cambiar en caliente por tenant están en
`crmcore.runtime.keys`. Una constante de módulo solo se puede cambiar
redesplegando, y cada instalación es distinta.

**Un `Settings` por servicio, no uno global.** Cada servicio instancia el suyo,
con los mixins que necesita más sus campos propios. Así el catálogo de ajustes
de un servicio es el de su dominio y no el de todo el producto.
"""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

from crmcore.config_parts import (
    _AbacSettings,
    _AlmacenSettings,
    _AppSettings,
    _AuthSettings,
    _BusSettings,
    _DbSettings,
    _DlpSettings,
    _DocumentalSettings,
    _IntelligenceSettings,
    _LimitsSettings,
    _ObsSettings,
    _SecuritySettings,
    _ServicioSettings,
    _TenancySettings,
)

# Valores que se distribuyen en el código como marcadores "válidos para
# desarrollo". Si alguno sobrevive a un despliegue de producción, la instalación
# está comprometida de forma trivial, así que el arranque los rechaza.
PLACEHOLDERS_INSEGUROS: frozenset[str] = frozenset(
    {
        "",
        "CHANGE_ME_SECRET_KEY",
        "change-me",
        "changeme",
        "contecrm_dev_only",
        "desarrollo-local",
    }
)


class Settings(
    _AppSettings,
    _AlmacenSettings,
    _IntelligenceSettings,
    _DocumentalSettings,
    _AbacSettings,
    _DlpSettings,
    _DbSettings,
    _TenancySettings,
    _BusSettings,
    _AuthSettings,
    _LimitsSettings,
    _ObsSettings,
    _SecuritySettings,
    _ServicioSettings,
    BaseSettings,
):
    """Ajustes comunes a todos los servicios.

    Un servicio que necesite ajustes propios hereda de esta clase y añade sus
    campos; no se crea un `Settings` paralelo, para que `.env` siga siendo el
    único sitio donde se configura nada.
    """

    # La clase hoja es la que carga el entorno. Los mixins heredan de
    # BaseSettings solo para que pydantic recoja sus campos.
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Derivados ─────────────────────────────────────────────────────────

    @computed_field  # type: ignore[prop-decorator]
    @property
    def es_produccion(self) -> bool:
        return self.env == "prod"

    @property
    def formato_log_resuelto(self) -> str:
        """`auto` = json fuera de desarrollo, consola en desarrollo."""
        if self.log_format != "auto":
            return self.log_format
        return "consola" if self.env == "dev" else "json"

    @property
    def redactar_pii_resuelto(self) -> bool:
        """Sin decisión explícita: se redacta salvo en desarrollo.

        En desarrollo poder buscar un correo concreto en el log es justo lo que
        hace falta para depurar; en cualquier otro entorno ese mismo correo es
        un dato personal en un sistema que no está pensado para guardarlo.
        """
        if self.log_redact_pii is not None:
            return self.log_redact_pii
        return self.env != "dev"

    @property
    def esquema_resuelto(self) -> str:
        """Esquema de base de datos del servicio.

        Vacío ⇒ se deriva del nombre del servicio. Que cada servicio tenga el
        suyo es lo que permite darle un rol sin permisos sobre los demás, y con
        ello convertir "no leas la base de otro servicio" de norma en
        imposibilidad (CRM-00.03.01.02).
        """
        return self.db_schema or (self.service_name or "public").replace("-", "_")

    @property
    def origenes_cors(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def proxies_de_confianza(self) -> list[str]:
        return [p.strip() for p in self.trusted_proxies.split(",") if p.strip()]

    @property
    def tls_efectivo(self) -> bool:
        """Si hay que exigir HTTPS. `None` = encendido salvo en desarrollo.

        El defecto va por entorno y no a `True` fijo porque en desarrollo se
        trabaja contra `http://localhost` y un `True` fijo haría imposible el
        ciclo local — que es exactamente cómo acaban desactivándose estas cosas
        en el `.env` de producción por copiar el de alguien.
        """
        if self.tls_exigido is not None:
            return bool(self.tls_exigido)
        return self.env not in ("dev", "test")

    # ── Comprobaciones de arranque ────────────────────────────────────────

    def verificar_para_produccion(self) -> list[str]:
        """Devuelve los problemas que impiden arrancar en producción.

        Devolver la lista en vez de lanzar en el primer fallo es deliberado: a
        quien despliega le sirve mucho más ver los cuatro secretos que le
        faltan de una vez que descubrirlos de uno en uno, arranque tras
        arranque.
        """
        if not self.es_produccion:
            return []

        problemas: list[str] = []
        if self.secret_key.get_secret_value() in PLACEHOLDERS_INSEGUROS:
            problemas.append(
                "SECRET_KEY sigue con el valor de ejemplo: firma todos los tokens, "
                "así que cualquiera podría emitirse uno de administrador"
            )
        for marcador in PLACEHOLDERS_INSEGUROS:
            if marcador and marcador in self.database_url:
                problemas.append(f"DATABASE_URL contiene la credencial de desarrollo «{marcador}»")
                break
        if self.api_docs_enabled and not self.origenes_cors and self.service_name == "gateway":
            # Aviso, no error: hay despliegues donde el gateway solo atiende a
            # integraciones máquina-a-máquina y no necesita ningún origen.
            pass
        if self.ci_enabled:
            # RT-4: la explotación la resuelve contecintelligence, así que es
            # una dependencia de despliegue. Sin dirección no hay informes, y
            # eso tiene que decirse al arrancar y no cuando alguien abra el
            # primero.
            if not self.ci_base_url:
                problemas.append(
                    "CI_ENABLED está activo y falta CI_BASE_URL: la explotación del "
                    "dato la resuelve contecintelligence (RT-4), así que hay que "
                    "levantarlo con la pila o dar la dirección de uno ya en marcha. "
                    "Si esta instalación no va a usar informes, pon CI_ENABLED=false."
                )
            if not self.ci_client_id or not (
                self.ci_client_secret.get_secret_value() if self.ci_client_secret else ""
            ):
                problemas.append(
                    "Faltan CI_CLIENT_ID o CI_CLIENT_SECRET: sin credencial de "
                    "aplicación no se puede canjear el token de usuario final, y "
                    "sin ese canje la única alternativa sería bajar la credencial "
                    "al navegador, que es la llave de todos los tenants"
                )
        if self.cache_backend == "memoria":
            problemas.append(
                "CACHE_BACKEND=memoria en producción: cada réplica tendría su "
                "propia caché y purgar la de un tenant no alcanzaría a las demás, "
                "así que seguirían sirviendo dato invalidado. Usa redis."
            )
        if self.cache_backend == "redis" and not self.cache_url:
            problemas.append("CACHE_BACKEND=redis sin CACHE_URL: no hay a dónde conectar")
        if self.storage_backend == "local":
            problemas.append(
                "STORAGE_BACKEND=local en producción: los adjuntos irían al disco "
                "del contenedor, así que cada réplica vería solo los suyos y un "
                "redespliegue los perdería. Usa s3 (vale cualquier compatible)."
            )
        if self.storage_backend == "s3" and not self.storage_s3_bucket:
            problemas.append("STORAGE_BACKEND=s3 sin STORAGE_S3_BUCKET: no hay dónde escribir")
        if self.adjunto_exigir_analisis and not self.adjunto_analizador_url:
            problemas.append(
                "ADJUNTO_EXIGIR_ANALISIS activo sin ADJUNTO_ANALIZADOR_URL: ningún "
                "adjunto pasaría el análisis y no se podría descargar ninguno"
            )
        if self.byok_enabled and not self.encryption_key.get_secret_value():
            problemas.append(
                "BYOK activo sin ENCRYPTION_KEY: la clave del tenant se guarda "
                "cifrada con la maestra, y no hay maestra"
            )
        # ── Cifrado en tránsito y en reposo (CRM-00.05.03.01) ─────────────
        # Se falla al arrancar y no se avisa: un despliegue que habla con la
        # base en claro no es «menos seguro», es un despliegue en el que
        # cualquiera con acceso a la red lee y modifica los datos de todos los
        # clientes. Y eso no se nota nunca desde dentro.
        if self.db_sslmode in ("disable", "allow", "prefer"):
            problemas.append(
                f"DB_SSLMODE={self.db_sslmode} en producción: la conexión con Postgres "
                "puede acabar en claro. Usa `require` como mínimo, y `verify-full` "
                "si el certificado es verificable — es lo único que impide un "
                "intermediario dentro de la propia red"
            )
        if not self.encryption_key.get_secret_value():
            problemas.append(
                "Falta ENCRYPTION_KEY en producción: los campos que el modelo declara "
                "sensibles no se pueden cifrar, así que no se pueden ni escribir"
            )
        if self.hsts_max_age == 0:
            problemas.append(
                "HSTS_MAX_AGE=0 en producción: sin HSTS, la primera petición de cada "
                "navegador puede ir por HTTP y ser interceptada antes de que exista "
                "la sesión"
            )
        if self.tls_exigido is False:
            problemas.append(
                "TLS_EXIGIDO=false en producción: se aceptarían peticiones por HTTP, "
                "con las credenciales y los datos del cliente en claro"
            )
        if self.storage_backend == "s3" and not self.storage_s3_ssl:
            problemas.append(
                "STORAGE_S3_SSL=false en producción: los adjuntos viajarían en claro "
                "hacia el almacén, y ahí es donde están los contratos"
            )
        if self.trust_proxy_headers and not self.proxies_de_confianza:
            problemas.append(
                "TRUST_PROXY_HEADERS activo sin TRUSTED_PROXIES: cualquiera podría "
                "falsear su IP y saltarse el rate limiting y las listas de permitidos"
            )
        return problemas


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Instancia cacheada. El proceso lee el entorno una sola vez.

    Lo que cambia en caliente NO pasa por aquí: va por `crmcore.runtime`, que
    resuelve el valor efectivo para el tenant en curso. Esto es la foto del
    entorno al arrancar.
    """
    return Settings()


def limpiar_cache_settings() -> None:
    """Olvida la instancia cacheada. Solo para pruebas.

    Se expone con nombre propio en vez de que cada prueba llame a
    `get_settings.cache_clear()` porque así hay un único sitio al que añadir lo
    que haya que limpiar además en el futuro.
    """
    get_settings.cache_clear()


def es_entorno_de_pruebas() -> bool:
    """Si el proceso corre bajo pytest.

    Se usa para negarse a hacer cosas peligrosas contra datos de verdad (borrar
    esquemas, sembrar demo) y NUNCA para cambiar la lógica de negocio: un
    sistema que se comporta distinto bajo pruebas no está probado.
    """
    return "PYTEST_CURRENT_TEST" in os.environ
