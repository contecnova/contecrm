"""Contratos del servicio de metadatos."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

TIPOS_CAMPO = Literal[
    "texto", "texto_largo", "numero", "moneda", "porcentaje", "fecha", "fecha_hora",
    "booleano", "lista", "lista_multiple", "formula", "lookup", "geolocalizacion",
    "json", "fichero", "cifrado", "email", "telefono", "url",
]


class CrearObjeto(BaseModel):
    nombre: str = Field(
        ...,
        pattern=r"^[a-z][a-z0-9_]{1,79}$",
        description=(
            "Nombre de API. Inmutable: aparece en URLs e integraciones de "
            "terceros, así que cambiarlo rompería código ajeno"
        ),
        examples=["proyecto_obra"],
    )
    etiqueta: str = Field(..., min_length=1, max_length=200, examples=["Proyecto de obra"])
    etiqueta_plural: str = Field("", max_length=200, examples=["Proyectos de obra"])
    descripcion: str = ""
    icono: str = ""
    papelera: bool = True
    estados: dict[str, Any] = Field(
        default_factory=dict,
        description="Máquina de estados: {estado: [transiciones permitidas]}",
        examples=[{"borrador": ["activo"], "activo": ["cerrado"], "cerrado": []}],
    )


class ObjetoOut(BaseModel):
    id: UUID
    nombre: str
    etiqueta: str
    etiqueta_plural: str
    descripcion: str
    origen: str
    icono: str
    activo: bool
    papelera: bool
    estados: dict[str, Any] = {}

    model_config = {"from_attributes": True}


class CrearCampo(BaseModel):
    nombre: str = Field(..., pattern=r"^[a-z][a-z0-9_]{1,79}$", examples=["importe_obra"])
    etiqueta: str = Field(..., min_length=1, max_length=200)
    tipo: TIPOS_CAMPO
    ayuda: str = ""
    obligatorio: bool = False
    unico: bool = False
    solo_lectura: bool = False
    valor_defecto: Any = None
    restricciones: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Restricciones del tipo: min/max, min_longitud/max_longitud, patrón, "
            "decimales, opciones, objeto destino del lookup"
        ),
        examples=[{"min": 0, "max": 1000000, "decimales": 2}],
    )
    sensibilidad: Literal["publico", "interno", "confidencial", "personal", "especial"] = "interno"
    orden: int = 100


class CampoOut(BaseModel):
    id: UUID
    nombre: str
    etiqueta: str
    tipo: str
    ayuda: str
    obligatorio: bool
    unico: bool
    solo_lectura: bool
    valor_defecto: Any = None
    restricciones: dict[str, Any] = {}
    sensibilidad: str
    orden: int
    activo: bool
    deprecado: bool

    model_config = {"from_attributes": True}


class CrearRegla(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=120)
    mensaje: str = Field(
        ...,
        min_length=1,
        description=(
            "Lo que verá quien la incumpla. Escríbelo pensando en esa persona: "
            "«validación 14 fallida» obliga a llamar a soporte"
        ),
    )
    condiciones: list[dict[str, Any]] = Field(
        ...,
        description=(
            "Describen la situación PROHIBIDA, no la válida. Así el mensaje y "
            "la condición se leen igual"
        ),
        examples=[[{"atributo": "fecha_cierre", "op": "<", "valor": "@fecha_alta"}]],
    )
    combinacion: Literal["todas", "alguna"] = "todas"
    momento: Literal["siempre", "crear", "actualizar", "transicion"] = "siempre"
    estado_desde: str | None = None
    estado_hasta: str | None = None


class ReglaOut(BaseModel):
    id: UUID
    nombre: str
    mensaje: str
    condiciones: list[dict[str, Any]] = []
    combinacion: str
    momento: str
    activa: bool

    model_config = {"from_attributes": True}


class ValidarRegistro(BaseModel):
    """Dry-run de validación (CRM-00.02.03.07)."""

    datos: dict[str, Any]
    parcial: bool = Field(
        False, description="True para simular un PATCH: no exige los obligatorios ausentes"
    )


class ResultadoValidacion(BaseModel):
    valido: bool
    errores: list[dict[str, Any]] = []
    valores: dict[str, Any] = {}


class CrearValorLista(BaseModel):
    valor: str = Field(..., min_length=1, max_length=120)
    etiqueta: str = Field(..., min_length=1, max_length=200)
    orden: int = 100
    extra: dict[str, Any] = Field(default_factory=dict)


class ValorListaOut(BaseModel):
    id: UUID
    lista: str
    valor: str
    etiqueta: str
    orden: int
    activo: bool
    extra: dict[str, Any] = {}

    model_config = {"from_attributes": True}


class DescribeOut(BaseModel):
    """Lo que necesita un frontend headless para renderizar sin saber del CRM."""

    objeto: ObjetoOut
    campos: list[CampoOut]
    reglas: list[ReglaOut]
    layouts: list[dict[str, Any]]
    # Permisos del que pregunta sobre este objeto, para que el cliente pueda
    # decidir qué enseña sin reimplementar la resolución de roles.
    permisos: dict[str, bool]
