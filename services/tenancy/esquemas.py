"""Contratos de entrada y salida del servicio de tenancy.

Los esquemas son parte del contrato público: lo que entra aquí aparece en el
OpenAPI y lo consume cualquier cliente. Por eso llevan ejemplos y descripciones
—un contrato sin ejemplos obliga a leer el código para usarlo— y por eso no se
reutiliza el modelo de base de datos como esquema de salida: si se hiciera,
añadir una columna interna la publicaría sin querer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class CrearTenant(BaseModel):
    slug: str = Field(
        ...,
        min_length=2,
        max_length=63,
        description="Identificador legible y permanente. Va en subdominios y URLs.",
        examples=["acme"],
    )
    nombre: str = Field(..., min_length=1, max_length=200, examples=["ACME Industrial, S.A."])
    plan: str = Field("base", examples=["base", "profesional", "corporativo"])
    region: str | None = Field(
        None,
        description=(
            "Región donde residen los datos. Sin valor, el de la instalación "
            "(`TENANT_DEFAULT_REGION`): escribir aquí un valor por defecto haría "
            "que el ajuste no sirviera para nada, que es como estaba"
        ),
        examples=["eu"],
    )
    aislamiento: Literal["pool", "schema", "silo"] | None = Field(
        None,
        description=(
            "pool = esquema compartido con discriminador; schema = un esquema "
            "por tenant; silo = base o clúster dedicado. Sin valor, el de la "
            "instalación (`TENANT_DEFAULT_ISOLATION`)"
        ),
    )
    tenant_padre_id: UUID | None = Field(
        None, description="Para jerarquías matriz–filial o franquicia"
    )
    idioma: str = Field("es", max_length=10)
    zona_horaria: str = Field("Europe/Madrid", max_length=60)
    moneda: str = Field("EUR", min_length=3, max_length=3)


class CambiarEstado(BaseModel):
    estado: Literal["activo", "suspendido", "solo_lectura", "en_baja", "archivado"]
    motivo: str = Field(
        "",
        max_length=2000,
        description=(
            "Obligatorio al suspender, congelar o dar de baja. Queda en la "
            "auditoría: seis meses después, es la única forma de saber por qué"
        ),
    )


class TenantOut(BaseModel):
    id: UUID
    slug: str
    nombre: str
    estado: str
    motivo_estado: str | None = None
    plan: str
    tier: str
    region: str
    aislamiento: str
    tenant_padre_id: UUID | None = None
    idioma: str
    zona_horaria: str
    moneda: str
    marca: dict[str, Any] = {}
    created_at: datetime
    provisionado_at: datetime | None = None

    model_config = {"from_attributes": True}


class UnidadOut(BaseModel):
    id: UUID
    codigo: str
    nombre: str
    padre_id: UUID | None = None
    activa: bool

    model_config = {"from_attributes": True}


class CrearUnidad(BaseModel):
    codigo: str = Field(..., min_length=1, max_length=60, examples=["iberia"])
    nombre: str = Field(..., min_length=1, max_length=200, examples=["División Iberia"])
    padre_id: UUID | None = None


class PlanOut(BaseModel):
    codigo: str
    nombre: str
    descripcion: str | None = None
    capacidades: dict[str, Any] = {}
    cuotas: dict[str, Any] = {}
    activo: bool

    model_config = {"from_attributes": True}


class FijarFlag(BaseModel):
    activo: bool = False
    porcentaje: int = Field(
        0,
        ge=0,
        le=100,
        description=(
            "Despliegue progresivo. El reparto va por hash del identificador, "
            "no al azar: a un mismo usuario le toca siempre lo mismo"
        ),
    )
    descripcion: str | None = None


class FijarAjuste(BaseModel):
    valor: Any = Field(..., description="Se valida contra el tipo y rango declarados")
    ambito: Literal["global", "tier", "tenant", "bu", "usuario"] = "tenant"
    ambito_id: str = Field("", description="Vacío en el ámbito global")


class ConsumoOut(BaseModel):
    metrica: str
    periodo: str
    consumido: int
    limite: int
    pct: float
    # Se devuelve el aviso resuelto y no solo el porcentaje para que el cliente
    # no tenga que reimplementar el umbral —y equivocarse— en cada frontend.
    en_aviso: bool
    # Si esta métrica se ha podido medir. Una que falla se dice en su fila y no
    # tumba el panel entero: una métrica rota no puede dejar sin consumo a las
    # otras cinco. Y «no se ha podido medir» no es «cero», que es exactamente la
    # confusión que este panel tenía cuando leía una tabla vacía.
    medido: bool = True
    porque: str = ""
