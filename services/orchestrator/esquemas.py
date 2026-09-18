"""Contratos del motor de procesos."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class PublicarDefinicion(BaseModel):
    clave: str = Field(..., min_length=1, max_length=120, examples=["order_to_cash"])
    nombre: str = Field(..., min_length=1, max_length=200)
    descripcion: str = ""
    definicion: dict[str, Any] = Field(
        ...,
        description=(
            "Grafo del proceso: `inicio` y `pasos`. Se valida antes de publicar; "
            "ver la referencia de tipos de paso en el manual técnico"
        ),
    )
    disparadores: list[str] = Field(
        default_factory=list,
        description="Eventos que arrancan el proceso automáticamente",
        examples=[["opportunity.won"]],
    )


class DefinicionOut(BaseModel):
    id: UUID
    clave: str
    version: int
    nombre: str
    descripcion: str
    estado: str
    disparadores: list[str] = []
    definicion: dict[str, Any] = {}

    model_config = {"from_attributes": True}


class ArrancarProceso(BaseModel):
    clave: str
    variables: dict[str, Any] = Field(default_factory=dict)
    origen_tipo: str | None = Field(None, examples=["opportunity"])
    origen_id: str | None = None


class InstanciaOut(BaseModel):
    id: UUID
    clave: str
    version: int
    estado: str
    paso_actual: str | None = None
    variables: dict[str, Any] = {}
    pasos_ejecutados: int
    despertar_at: datetime | None = None
    error: str | None = None
    created_at: datetime
    finalizada_at: datetime | None = None

    model_config = {"from_attributes": True}


class PasoOut(BaseModel):
    paso: str
    tipo: str
    resultado: str
    intento: int
    entrada: dict[str, Any] = {}
    salida: dict[str, Any] = {}
    error: str | None = None
    duracion_ms: int
    created_at: datetime

    model_config = {"from_attributes": True}


class TareaOut(BaseModel):
    id: UUID
    instancia_id: UUID
    paso: str
    titulo: str
    descripcion: str
    estado: str
    opciones: list[str] = []
    asignada_a: UUID | None = None
    asignada_rol: str | None = None
    vence_at: datetime | None = None
    datos: dict[str, Any] = {}
    created_at: datetime

    model_config = {"from_attributes": True}


class ResponderTarea(BaseModel):
    respuesta: str = Field(..., examples=["aprobar"])
    comentario: str = Field("", max_length=4000)


class EditarVariables(BaseModel):
    """Edición en caliente de las variables de una instancia (CRM-00.03.02.12).

    Es una herramienta de rescate: un proceso atascado por un dato mal cargado
    se arregla corrigiendo el dato, no relanzándolo entero. Queda auditado con
    quién lo tocó, porque es una operación que cambia el curso de un proceso ya
    en marcha.
    """

    variables: dict[str, Any]
    motivo: str = Field(..., min_length=10)


class SimularProceso(BaseModel):
    """Simulación con datos de ejemplo antes de publicar (CRM-00.03.02.14)."""

    definicion: dict[str, Any]
    variables: dict[str, Any] = Field(default_factory=dict)
    # Respuestas que se darán a las tareas humanas, para poder recorrer el
    # proceso entero sin esperar a nadie.
    respuestas_humanas: dict[str, str] = Field(default_factory=dict)
