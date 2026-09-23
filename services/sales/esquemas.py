"""Contratos del servicio de ventas."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class CrearLead(BaseModel):
    nombre: str | None = Field(None, max_length=150)
    apellidos: str | None = Field(None, max_length=200)
    empresa: str | None = Field(None, max_length=300)
    cargo: str | None = None
    email: EmailStr | None = None
    telefono: str | None = None
    web: str | None = None
    pais: str | None = Field(None, min_length=2, max_length=2)
    origen: str | None = Field(None, examples=["formulario web", "feria", "llamada entrante"])
    campana_id: UUID | None = None
    utm: dict[str, Any] = Field(
        default_factory=dict,
        description="Parámetros de campaña tal como llegaron",
        examples=[{"utm_source": "google", "utm_medium": "cpc", "utm_campaign": "obra-2026"}],
    )
    owner_id: UUID | None = Field(
        None, description="Si se omite, queda sin asignar y el SLA corre igual"
    )
    campos: dict[str, Any] = Field(default_factory=dict)


class LeadOut(BaseModel):
    id: UUID
    nombre: str | None = None
    apellidos: str | None = None
    empresa: str | None = None
    cargo: str | None = None
    email: str | None = None
    telefono: str | None = None
    estado: str
    origen: str | None = None
    owner_id: UUID | None = None
    puntuacion: int | None = None
    sla_primera_respuesta_at: datetime | None = None
    primera_respuesta_at: datetime | None = None
    sla_incumplido: bool
    motivo_descarte: str | None = None
    reciclar_at: date | None = None
    cuenta_id: UUID | None = None
    oportunidad_id: UUID | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class DescartarLead(BaseModel):
    motivo: str = Field(
        ...,
        description=(
            "De una lista cerrada: lo que se quiere es contar. «sin presupuesto» "
            "y «fuera de perfil» llevan a acciones distintas, y en texto libre "
            "no se pueden agrupar"
        ),
        examples=["sin_presupuesto", "fuera_de_perfil"],
    )
    nota: str = ""


class ConvertirLead(BaseModel):
    cuenta_id: UUID = Field(
        ...,
        description=(
            "La cuenta la crea antes el servicio `party`: el maestro de clientes "
            "es suyo y ventas no escribe en su esquema"
        ),
    )
    contacto_id: UUID | None = None
    crear_oportunidad: bool = True
    nombre_oportunidad: str | None = None
    importe: Decimal | None = Field(None, ge=0)
    pipeline_id: UUID | None = None
    fecha_cierre: date | None = None


class CrearPipeline(BaseModel):
    clave: str = Field(..., pattern=r"^[a-z][a-z0-9_-]{1,59}$", examples=["proyectos"])
    nombre: str = Field(..., min_length=1, max_length=150)
    descripcion: str = ""
    ambito: str | None = None
    por_defecto: bool = False


class CrearEtapa(BaseModel):
    clave: str = Field(..., pattern=r"^[a-z][a-z0-9_-]{1,59}$", examples=["negociacion"])
    nombre: str = Field(..., min_length=1, max_length=150)
    orden: int = Field(0, ge=0)
    probabilidad: int = Field(50, ge=0, le=100)
    color: str = Field("#6B7280", pattern=r"^#[0-9A-Fa-f]{6}$")
    terminal: bool = False
    ganada: bool = False
    criterios_salida: list[str] = Field(
        default_factory=list,
        description=(
            "Campos obligatorios para SALIR de esta etapa. Son lo que hace que "
            "la previsión signifique algo"
        ),
        examples=[["importe", "fecha_cierre", "contacto_id"]],
    )
    checklist: list[str] = Field(default_factory=list)
    dias_estancamiento: int | None = Field(None, ge=1)


class EtapaOut(BaseModel):
    id: UUID
    clave: str
    nombre: str
    orden: int
    probabilidad: int
    color: str
    terminal: bool
    ganada: bool
    criterios_salida: list[Any] = []
    checklist: list[Any] = []
    dias_estancamiento: int | None = None

    model_config = {"from_attributes": True}


class PipelineOut(BaseModel):
    id: UUID
    clave: str
    nombre: str
    descripcion: str
    ambito: str | None = None
    activo: bool
    por_defecto: bool
    etapas: list[EtapaOut] = []

    model_config = {"from_attributes": True}


class CrearOportunidad(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=300)
    descripcion: str | None = None
    cuenta_id: UUID | None = None
    contacto_id: UUID | None = None
    pipeline_id: UUID | None = Field(None, description="Si se omite, el pipeline por defecto")
    etapa_id: UUID | None = Field(None, description="Si se omite, la primera etapa")
    importe: Decimal = Field(Decimal(0), ge=0)
    moneda: str = Field("EUR", min_length=3, max_length=3)
    fecha_cierre: date | None = None
    owner_id: UUID | None = None
    campos: dict[str, Any] = Field(default_factory=dict)


class ActualizarOportunidad(BaseModel):
    nombre: str | None = Field(None, min_length=1, max_length=300)
    descripcion: str | None = None
    importe: Decimal | None = Field(None, ge=0)
    probabilidad: int | None = Field(None, ge=0, le=100)
    fecha_cierre: date | None = None
    contacto_id: UUID | None = None
    owner_id: UUID | None = None
    motivo_perdida: str | None = None
    competidor_ganador: str | None = None
    campos: dict[str, Any] | None = None


class OportunidadOut(BaseModel):
    id: UUID
    codigo: str | None = None
    nombre: str
    descripcion: str | None = None
    cuenta_id: UUID | None = None
    contacto_id: UUID | None = None
    pipeline_id: UUID
    etapa_id: UUID
    # Los nombres, no solo los identificadores. Un listado de oportunidades con
    # la columna «etapa» vacía y un UUID al lado no dice en qué punto está
    # ninguna venta, que es lo único que se mira en esa pantalla. Se resuelven
    # aquí, en el servicio dueño de las etapas: pedirle al front que cruce dos
    # listados para pintar una columna es cargarle un `join` y garantizar que
    # cada pantalla lo haga distinto.
    pipeline: str | None = None
    etapa: str | None = None
    importe: Decimal
    moneda: str
    probabilidad: int
    importe_ponderado: Decimal = Field(
        ..., description="Importe por probabilidad: lo que suma al pipeline previsto"
    )
    fecha_cierre: date | None = None
    fecha_cierre_real: date | None = None
    estado: str
    motivo_perdida: str | None = None
    bloqueada: bool
    reaperturas: int
    owner_id: UUID | None = None
    lead_id: UUID | None = None
    campos: dict[str, Any] = {}
    version: int
    created_at: datetime

    model_config = {"from_attributes": True}


class CambiarEtapa(BaseModel):
    etapa_id: UUID
    motivo: str = ""
    forzar: bool = Field(
        False,
        description=(
            "Salta los criterios de salida. Para carga de datos históricos, que "
            "nunca los cumplen. Queda constancia de que se saltaron"
        ),
    )


class Reabrir(BaseModel):
    etapa_id: UUID = Field(..., description="Etapa no terminal en la que queda")
    motivo: str = Field(..., min_length=5)


class CrearLinea(BaseModel):
    descripcion: str = Field(..., min_length=1, max_length=300)
    producto_id: UUID | None = None
    cantidad: Decimal = Field(Decimal(1), gt=0)
    precio_unitario: Decimal = Field(Decimal(0), ge=0)
    descuento_pct: Decimal = Field(Decimal(0), ge=0, le=100)
    coste_unitario: Decimal | None = Field(None, ge=0)
    tipo_ingreso: Literal["puntual", "recurrente"] = "puntual"
    periodicidad: Literal["mensual", "trimestral", "anual"] | None = None
    orden: int = 0


class LineaOut(BaseModel):
    id: UUID
    orden: int
    descripcion: str
    producto_id: UUID | None = None
    cantidad: Decimal
    precio_unitario: Decimal
    descuento_pct: Decimal
    total: Decimal
    coste_unitario: Decimal | None = None
    tipo_ingreso: str
    periodicidad: str | None = None

    model_config = {"from_attributes": True}


class CompetidorEntrada(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=150)
    cuenta_id: UUID | None = None
    fortalezas: str | None = None
    debilidades: str | None = None
    ganador: bool = False


class CambioEtapaOut(BaseModel):
    etapa_desde_id: UUID | None = None
    etapa_hasta_id: UUID
    dias_en_etapa: int | None = None
    importe_en_cambio: Decimal | None = None
    fecha_cierre_en_cambio: date | None = None
    motivo: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
