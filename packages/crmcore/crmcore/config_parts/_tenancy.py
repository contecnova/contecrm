"""Multi-tenancy: resolución, jerarquía, cuotas y residencia."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field
from pydantic_settings import BaseSettings


class _TenancySettings(BaseSettings):
    # ── Resolución del tenant (CRM-00.02.04.02) ───────────────────────────
    # Cuatro vías, por orden de confianza: el claim del token > la clave de API
    # > la cabecera explícita > el subdominio. Las dos primeras están firmadas;
    # las dos últimas son PISTAS de enrutado y nunca bastan por sí solas para
    # conceder acceso. Esa distinción es la que evita que baste con cambiar una
    # cabecera para entrar en otro tenant.
    #
    # Dominio raíz para el enrutado por subdominio: `<slug>.<raíz>`. Vacío
    # desactiva el subdominio como pista.
    tenant_root_domain: str = ""
    # Nombre de la cabecera que lleva el slug del tenant. Configurable porque un
    # despliegue detrás de un proxy corporativo puede necesitar otra.
    tenant_header: str = "X-Tenant"

    # ── Modelo de aislamiento por defecto para tenants nuevos ─────────────
    # pool   = esquema compartido con discriminador (CRM-00.01.01.01)
    # schema = un esquema por tenant                (CRM-00.01.01.02)
    # silo   = base o clúster dedicado              (CRM-00.01.01.03)
    # El modelo híbrido por tiers (CRM-00.01.01.04) sale de que este valor sea
    # una propiedad DEL TENANT, no del despliegue: esto es solo el default con
    # el que se dan de alta.
    tenant_default_isolation: Literal["pool", "schema", "silo"] = "pool"

    # Región por defecto para el pinning de datos (CRM-00.01.05.01). El valor
    # no significa nada por sí mismo: lo interpreta el despliegue. Se guarda en
    # el tenant para poder auditar dónde vive cada dato.
    tenant_default_region: str = "eu"

    # ── Cuotas por defecto (CRM-00.01.06.02) ──────────────────────────────
    # Son los topes con los que nace un tenant sin plan asignado. El plan los
    # sobrescribe, y el operador puede subirlos por tenant desde Admin. Cero =
    # sin límite, que es lo razonable para un despliegue on-premise de un solo
    # cliente donde las cuotas solo estorban.
    quota_api_calls_por_minuto: int = Field(1_000, ge=0, le=10_000_000)
    quota_registros: int = Field(0, ge=0)
    quota_almacenamiento_mb: int = Field(0, ge=0)
    quota_correos_por_dia: int = Field(0, ge=0)
    quota_workflows_concurrentes: int = Field(100, ge=0, le=1_000_000)
    quota_tokens_ia_por_dia: int = Field(0, ge=0)
    # Usuarios activos que admite el plan. 0 = sin límite, que es lo razonable
    # en un despliegue on-premise de un solo cliente.
    licencias_maximas: int = Field(0, ge=0, le=1_000_000)

    # Porcentaje de consumo a partir del cual se avisa al tenant de que se
    # acerca al límite (CRM-00.01.06.06). Avisar al 100 % es avisar tarde.
    quota_aviso_pct: int = Field(80, ge=1, le=100)

    # ── Baja de un tenant ─────────────────────────────────────────────────
    # Días de recuperación desde que se pide la baja hasta que sus datos se
    # pueden destruir; es también el plazo que tienen los servicios para
    # contestar al inventario documental. Una baja instantánea convierte un
    # error administrativo en una pérdida irreversible. Era un 30 escrito en
    # `cambiar_estado`; es una cláusula de contrato y cada plataforma tiene la
    # suya.
    tenant_baja_dias_recuperacion: int = Field(30, ge=1, le=365)

    # ── Alta de tenants ───────────────────────────────────────────────────
    # Alta autoservicio. Apagada por defecto: un despliegue empresarial da de
    # alta a sus tenants por API o por consola, y dejar abierto el alta pública
    # en una instalación privada es una superficie regalada.
    # ── Alta autoservicio (CRM-00.01.03.01) ───────────────────────────────
    #
    # Apagada de fábrica: un despliegue empresarial da de alta a sus clientes por
    # API o por consola, y dejar abierta un alta pública en una instalación
    # privada es una superficie regalada.
    #
    # Este ajuste estuvo QUITADO entre el 06 y el 07-10-2026, y con razón: hasta
    # entonces prometía abrir una puerta que no existía —ponerlo a `true` no
    # abría nada— y eso hacía creer que apagarlo era lo que la cerraba. Vuelve
    # ahora con la puerta construida, que es lo que decía su propia nota al
    # quitarlo.
    onboarding_enabled: bool = False
    # Cuánto vale el enlace de confirmación. Pocas horas: es una credencial en
    # el buzón de alguien, y quien da de alta su empresa lo hace en el momento.
    onboarding_enlace_horas: int = Field(24, ge=1, le=168)
    # Altas que admite una misma IP por hora. Muy por debajo del límite general
    # de la API porque esto crea tenants: dejarlo en el de una lectura cualquiera
    # permitiría llenar el sistema de empresas inventadas desde un portátil.
    onboarding_altas_por_ip_hora: int = Field(5, ge=1, le=100)
    # Días antes de olvidar una solicitud, usada o no. Son correos de gente que
    # nunca llegó a ser cliente: dato personal que no hay motivo para guardar.
    onboarding_retencion_dias: int = Field(30, ge=1, le=365)

    # ── Consumo a facturación (CRM-00.01.06.07) ───────────────────────────
    #
    # Si el corte de consumo de cada tenant se toma y se manda solo. Apagado de
    # fábrica: mandar números a un sistema de cobro sin que nadie lo haya
    # pedido es la forma más rápida de facturar algo que no estaba acordado.
    facturacion_exportar_periodicamente: bool = False
    # A dónde se manda el corte: el sistema de facturación del cliente, como un
    # webhook de la casa (firmado con HMAC y por el guard de SSRF). Vacío, no se
    # manda y el corte se queda «sin destino», que se ve en la pantalla.
    facturacion_destino_url: str = ""
    # Cabeceras que pide ese sistema (su clave de API, por ejemplo). Sensibles:
    # la consola las enseña tapadas.
    facturacion_destino_cabeceras: dict[str, Any] = Field(default_factory=dict)
    # En qué forma viaja el corte: `json` (una lista de filas) o `csv`.
    facturacion_formato_envio: str = "json"
    # Intentos de envío antes de dejar el corte en «fallido» y dejar de
    # reintentarlo solo. Se puede reenviar a mano.
    facturacion_max_intentos: int = Field(5, ge=1, le=50)
    # Cada cuánto se toma el corte del periodo en curso y se mandan los
    # periodos ya cerrados. El corte de un mes es el ÚLTIMO que se tomó dentro
    # de ese mes, así que el intervalo es también lo que puede faltar del final
    # del periodo.
    tarea_facturacion_intervalo_s: int = Field(3_600, ge=60, le=86_400)

    # ── Jerarquía de empresas (CRM-00.01.03.07) ───────────────────────────
    #
    # Qué indicadores agrega la matriz de las empresas hijas que se los han
    # COMPARTIDO: cada uno es `{nombre, ruta, campo}` — una ruta GET de la API
    # del CRM y el campo numérico de su respuesta que se suma. Sólo cifras, y
    # sólo de las hijas que lo han autorizado.
    jerarquia_indicadores: list[dict[str, Any]] = Field(
        default_factory=lambda: [
            {
                "nombre": "Embudo abierto (importe bruto)",
                "ruta": "/api/v1/pipeline/resumen",
                "campo": "total",
                "permiso": "opportunity:read",
                # Un total del embudo exige ver el importe en claro (un agregado
                # de una etapa con una sola oportunidad ES su importe), y una
                # llamada sin rol no lo ve: medido el 09-11-2026, 403
                # `proyeccion.campo_no_usable`. Sólo se lee el número, y sólo
                # de la hija que lo ha compartido.
                "roles": ["admin"],
            },
            {
                "nombre": "Embudo abierto (ponderado)",
                "ruta": "/api/v1/pipeline/resumen",
                "campo": "total_ponderado",
                "permiso": "opportunity:read",
                # Un total del embudo exige ver el importe en claro (un agregado
                # de una etapa con una sola oportunidad ES su importe), y una
                # llamada sin rol no lo ve: medido el 09-11-2026, 403
                # `proyeccion.campo_no_usable`. Sólo se lee el número, y sólo
                # de la hija que lo ha compartido.
                "roles": ["admin"],
            },
        ]
    )
