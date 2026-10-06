"""Multi-tenancy: resolución, jerarquía, cuotas y residencia."""

from __future__ import annotations

from typing import Literal

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

    # ── Alta de tenants ───────────────────────────────────────────────────
    # Alta autoservicio. Apagada por defecto: un despliegue empresarial da de
    # alta a sus tenants por API o por consola, y dejar abierto el alta pública
    # en una instalación privada es una superficie regalada.
    # `ONBOARDING_ENABLED` estuvo aquí y SE QUITA (06-10-2026). Prometía abrir
    # el alta **autoservicio**, y en este producto el alta de un tenant es una
    # operación de plataforma: `POST /tenants` exige administrador de la
    # plataforma y no hay ninguna otra vía. Medido: ningún sitio crea un tenant
    # sin esa puerta.
    #
    # Ponerlo a `true` no abría nada, así que tampoco era peligroso — era peor
    # que eso: hacía creer que el alta pública estaba disponible y que apagarla
    # era lo que la cerraba. Lo que la cierra es que no existe.
    #
    # El autoservicio es la mitad que falta de CRM-00.01.03.01 («API +
    # autoservicio»). Cuando se construya, su interruptor vuelve con él, y con
    # lo que un alta pública necesita además: límite por IP, verificación del
    # correo y qué pasa con un slug ocupado.
