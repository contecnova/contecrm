"""Contratos del motor de procesos."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
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
    estado: str = Field(
        "publicada",
        description=(
            "`borrador` para guardar sin que nadie la pueda instanciar, "
            "`publicada` para dejarla en uso. Un borrador se puede validar y "
            "simular; lo que no puede es arrancar contra datos reales"
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
    # De quién cuelga, cuando es un subproceso (CRM-00.03.02.08). La fila lo
    # guardaba desde el principio y **la respuesta no lo decía**: una instancia
    # fallida aparecía suelta y no había forma de llegar al proceso de negocio
    # al que pertenece, que es justo para lo que sirve poder encadenarlos.
    # Medido el 26-10-2026 recorriendo la familia.
    padre_id: UUID | None = None
    profundidad: int = 0
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


class CambioDeEstado(BaseModel):
    """El estado al que se lleva una versión de la definición.

    Con esquema y no como `dict` libre: el formulario de cada acción sale del
    contrato, y un cuerpo sin esquema se pinta como un formulario vacío. Quien
    abría «Publicar o archivar» no tenía dónde decir a qué estado.
    """

    estado: Literal["borrador", "publicada", "archivada"]


class ColumnaTabla(BaseModel):
    """Una columna de una tabla de decisión: de dónde sale su valor y de qué tipo es."""

    clave: str = Field(..., max_length=120, examples=["importe"])
    etiqueta: str = Field("", max_length=200)
    expresion: str = Field(
        "",
        max_length=300,
        description="De dónde sale el valor. Obligatoria en las entradas.",
        examples=["oportunidad.importe"],
    )
    tipo: Literal["numero", "texto", "booleano", "lista", "fecha"] | None = None


class CondicionRegla(BaseModel):
    entrada: str = Field(..., max_length=120, description="Columna de entrada que se compara")
    op: str = Field("=", max_length=20, examples=["<="])
    valor: Any = None


class ReglaTabla(BaseModel):
    nombre: str = Field("", max_length=200)
    condiciones: list[CondicionRegla] = Field(default_factory=list)
    salidas: dict[str, Any] = Field(default_factory=dict)
    prioridad: int | None = None


class TablaEditada(BaseModel):
    """La tabla de decisión entera, que se reemplaza de una pieza.

    Con esquema por la misma razón que arriba, y aquí más: esta tabla la edita
    negocio —es su razón de ser, sacar la política fuera del proceso para que
    cambie sin republicar el flujo— y sin contrato el front no puede ofrecer
    más que una caja de JSON, que es justo lo que esta pantalla evita.
    """

    nombre: str = Field("", max_length=200)
    politica: Literal["unica", "primera", "prioridad", "cualquiera", "todas"] = Field(
        "primera",
        description=(
            "Qué pasa cuando casan varias reglas: `unica` exige que solo case "
            "una, `primera` gana la primera escrita, `prioridad` la de mayor "
            "prioridad, `cualquiera` admite varias si coinciden en la salida y "
            "`todas` las acumula"
        ),
    )
    entradas: list[ColumnaTabla] = Field(default_factory=list)
    salidas: list[ColumnaTabla] = Field(default_factory=list)
    reglas: list[ReglaTabla] = Field(default_factory=list)
    activa: bool = True
