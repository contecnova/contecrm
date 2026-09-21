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

    # ── Cifrado en tránsito (CRM-00.05.03.01) ─────────────────────────────
    # Exigir que la petición haya llegado por HTTPS. Se comprueba con el
    # esquema real o con `X-Forwarded-Proto` cuando hay proxy de confianza.
    # `None` = encendido fuera de desarrollo, que es lo que casi siempre se
    # quiere y nadie se acuerda de activar.
    tls_exigido: bool | None = None
    # Versión mínima de TLS que el despliegue promete. No la aplica este
    # proceso —la termina el proxy o el balanceador— pero SÍ se comprueba con
    # `scripts/verificar_cifrado.py` contra el despliegue real. Declararla sin
    # medirla sería una promesa sin respaldo.
    tls_version_minima: str = Field("1.3", pattern=r"^1\.[23]$")
    # Modo SSL de la conexión con Postgres. `require` cifra; `verify-full`
    # además comprueba el certificado, que es lo que impide un intermediario
    # dentro de la propia red. En producción se exige al menos `require`.
    db_sslmode: str = Field(
        "prefer", pattern="^(disable|allow|prefer|require|verify-ca|verify-full)$"
    )
    # TLS hacia el bus y hacia la caché. Van aparte porque en muchas
    # instalaciones el bus está en la misma red y la caché no, o al revés.
    bus_tls: bool = False
    cache_tls: bool = False

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

    # ── Salidas de red y SSRF ─────────────────────────────────────────────
    # Hosts internos que el operador admite pese a estar en rango privado,
    # separados por comas. Existe porque hay instalaciones con el IdP o el ERP
    # en la red interna, y negarlo obligaría a apagar el guard entero.
    url_guard_hosts_permitidos: str = ""
    # Plazo para resolver el DNS de una URL de salida. `getaddrinfo` no admite
    # tiempo límite, así que se ejecuta en un hilo aparte con este plazo: un DNS
    # que no contesta colgaría el hilo que atiende la petición.
    url_guard_dns_timeout_s: float = Field(3.0, ge=0.1, le=30.0)

    # ── Qué ve cada rol de cada nivel de sensibilidad (CRM-00.05.02.03) ───
    # `ve_hasta` es el nivel máximo que se ve EN CLARO; `enmascara`, hasta dónde
    # se ve con los últimos caracteres. Por encima de eso, no se ve.
    #
    # Los valores por defecto son conservadores a propósito: un rol que no
    # aparezca aquí no ve nada por encima de `interno`. Un rol nuevo sin
    # configurar no puede nacer viendo los datos personales de todos los
    # clientes — equivocarse hacia la discreción se arregla con una línea de
    # configuración; al revés, con una notificación de brecha.
    politica_sensibilidad: dict[str, dict[str, str]] = Field(
        default_factory=lambda: {
            "admin": {"ve_hasta": "especial", "enmascara": "especial"},
            "responsable_ventas": {"ve_hasta": "personal", "enmascara": "especial"},
            "comercial": {"ve_hasta": "confidencial", "enmascara": "personal"},
            "usuario": {"ve_hasta": "interno", "enmascara": "confidencial"},
            "auditor": {"ve_hasta": "interno", "enmascara": "especial"},
            "agente_soporte": {"ve_hasta": "interno", "enmascara": "personal"},
            "solo_lectura": {"ve_hasta": "interno", "enmascara": "confidencial"},
            # Una cuenta de servicio ve lo mismo que un usuario: es lo que hace
            # que una integración pueda sincronizar el maestro. Faltaba, y caía
            # al comodín: toda integración recibía la ficha entera enmascarada.
            "integracion": {"ve_hasta": "interno", "enmascara": "confidencial"},
            "*": {"ve_hasta": "publico", "enmascara": "interno"},
        }
    )


class _AbacSettings(BaseSettings):
    """Motor de políticas externo (CRM-00.05.02.06).

    Apagado de serie: la instalación normal decide dentro, con el motor de
    `crmcore.authz.abac`, que ya tiene la política replicada en cada servicio.
    Esto es para quien ya tiene un motor de decisión corporativo y quiere que
    mande el suyo.

    Genérico y sin cliente por producto: una dirección HTTP a la que se manda
    `{tenant, objeto, accion, ambito}` y que contesta `{permitido, razones}`.
    Quien use OPA o Cedar pone delante su adaptador; escribir aquí un cliente
    de OPA ataría el producto a OPA.
    """

    abac_motor_externo_enabled: bool = False
    abac_motor_externo_url: str = ""
    # Corto a propósito: esto se consulta en la ruta caliente de cada decisión.
    # Un motor lento no puede convertir cada ficha en una espera, y como no
    # contestar significa «decide tú», agotar el plazo es seguro.
    abac_motor_externo_timeout_s: float = Field(2.0, ge=0.1, le=30.0)


class _DlpSettings(BaseSettings):
    """Control de fuga de datos (CRM-00.05.03.06, CRM-00.05.03.08).

    Todo configurable y nada a fuego, porque los números correctos no existen en
    abstracto: cincuenta registros son una exportación normal en un tenant con
    doscientos clientes y un incidente en uno con veinte mil. Por eso el aviso
    se decide **midiendo contra el patrón de cada uno**, y los topes duros son
    solo la red de seguridad de arriba.
    """

    dlp_enabled: bool = True
    # Tope duro por exportación. Alto a propósito: no es el mecanismo principal
    # —ese es la comparación con el patrón— sino el que impide que alguien se
    # lleve la base entera de una sola vez.
    dlp_max_registros_export: int = Field(50_000, ge=100, le=10_000_000)
    # Exportaciones por hora y usuario. Quien de verdad se está llevando datos
    # trocea para no disparar el tope por volumen.
    dlp_max_exports_hora: int = Field(20, ge=1, le=1_000)
    # Si se BLOQUEA o solo se avisa. Apagado de serie, y no por descuido:
    # bloquear una migración legítima cuesta tanto como dejar pasar una fuga, y
    # esa decisión es del cliente. Lo que no es opcional es que quede registrado.
    dlp_bloquear: bool = False
    # Días de historial con los que se calcula lo normal de cada usuario. Dos
    # semanas cubren el ciclo de trabajo de casi cualquiera sin arrastrar el
    # cierre de trimestre, que distorsionaría el patrón durante meses.
    dlp_dias_patron: int = Field(14, ge=1, le=365)
    # Cuántas veces su propia media tiene que superar alguien para que se avise.
    # Tres es holgado a propósito: un umbral ajustado convierte el aviso en ruido
    # y el ruido en «esto siempre salta», que es peor que no tener aviso.
    dlp_factor_anomalia: float = Field(3.0, ge=1.5, le=100.0)
    # Exportaciones mínimas en el historial para fiarse del patrón. Con dos
    # datos, cualquier tercero parece una anomalía.
    dlp_minimo_para_patron: int = Field(5, ge=2, le=1_000)
