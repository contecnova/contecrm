"""Contratos del servicio `party`."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class IdentificadorEntrada(BaseModel):
    tipo: Literal["nif", "cif", "vat", "ein", "otro"] = "nif"
    pais: str = Field("ES", min_length=2, max_length=2)
    valor: str = Field(..., min_length=3, max_length=40)
    principal: bool = False


class CrearCuenta(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=300, examples=["ACME Ibérica, S.L."])
    nombre_comercial: str | None = Field(None, max_length=300)
    roles: list[str] = Field(
        default_factory=lambda: ["cliente"],
        description=(
            "No son excluyentes: la misma empresa puede ser cliente de una "
            "división y proveedor de otra"
        ),
        examples=[["cliente", "partner"]],
    )
    identificadores: list[IdentificadorEntrada] = Field(default_factory=list)
    sector_esquema: str | None = Field(None, max_length=10, examples=["CNAE"])
    sector_codigo: str | None = Field(None, max_length=20, examples=["4321"])
    tamano: str | None = None
    empleados: int | None = Field(None, ge=0)
    facturacion_anual: Decimal | None = Field(None, ge=0)
    moneda: str = Field("EUR", min_length=3, max_length=3)
    tier: str | None = None
    web: str | None = Field(None, max_length=500)
    telefono: str | None = Field(None, max_length=40)
    email: EmailStr | None = None
    owner_id: UUID | None = None
    campos: dict[str, Any] = Field(
        default_factory=dict, description="Campos propios del tenant, definidos en `metadata`"
    )
    forzar: bool = Field(
        False,
        description=(
            "Crea la cuenta aunque se detecte un duplicado concluyente. La "
            "decisión queda en la auditoría con los candidatos descartados"
        ),
    )


class ActualizarCuenta(BaseModel):
    nombre: str | None = Field(None, min_length=1, max_length=300)
    nombre_comercial: str | None = None
    roles: list[str] | None = None
    estado: Literal["activa", "inactiva", "bloqueada"] | None = None
    ciclo_vida: str | None = None
    sector_esquema: str | None = None
    sector_codigo: str | None = None
    tamano: str | None = None
    empleados: int | None = Field(None, ge=0)
    facturacion_anual: Decimal | None = Field(None, ge=0)
    tier: str | None = None
    clasificacion_abc: str | None = Field(None, max_length=1)
    web: str | None = None
    telefono: str | None = None
    email: EmailStr | None = None
    owner_id: UUID | None = None
    campos: dict[str, Any] | None = None


class CuentaOut(BaseModel):
    id: UUID
    nombre: str
    nombre_comercial: str | None = None
    roles: list[str] = []
    estado: str
    ciclo_vida: str | None = None
    sector_esquema: str | None = None
    sector_codigo: str | None = None
    tamano: str | None = None
    empleados: int | None = None
    facturacion_anual: Decimal | None = None
    moneda: str
    tier: str | None = None
    web: str | None = None
    telefono: str | None = None
    email: str | None = None
    dominio: str | None = None
    owner_id: UUID | None = None
    calidad: int = Field(..., description="Completitud de la ficha, de 0 a 100")
    calidad_faltan: list[str] = []
    campos: dict[str, Any] = {}
    version: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DireccionEntrada(BaseModel):
    tipo: Literal["fiscal", "envio", "facturacion", "visita", "postal"] = "fiscal"
    principal: bool = False
    linea1: str = Field(..., min_length=1, max_length=300)
    linea2: str | None = None
    codigo_postal: str | None = Field(None, max_length=20)
    ciudad: str | None = None
    provincia: str | None = None
    pais: str = Field("ES", min_length=2, max_length=2)


class DireccionOut(DireccionEntrada):
    id: UUID
    latitud: float | None = None
    longitud: float | None = None
    validada: bool | None = None

    model_config = {"from_attributes": True}


class CrearContacto(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=150)
    apellidos: str | None = Field(None, max_length=200)
    tratamiento: str | None = None
    cargo: str | None = Field(None, max_length=150)
    departamento: str | None = None
    email: EmailStr | None = None
    telefono: str | None = None
    movil: str | None = None
    idioma: str | None = Field(None, max_length=10)
    canal_preferido: Literal["email", "telefono", "sms", "whatsapp", "postal"] | None = None
    cuenta_id: UUID | None = Field(None, description="Si se indica, se crea el vínculo")
    rol: str | None = Field(None, examples=["decisor", "prescriptor", "usuario"])
    owner_id: UUID | None = None
    campos: dict[str, Any] = Field(default_factory=dict)
    forzar: bool = False


class ContactoOut(BaseModel):
    id: UUID
    nombre: str
    apellidos: str | None = None
    nombre_completo: str
    tratamiento: str | None = None
    cargo: str | None = None
    departamento: str | None = None
    email: str | None = None
    telefono: str | None = None
    movil: str | None = None
    idioma: str | None = None
    canal_preferido: str | None = None
    no_contactar: bool
    owner_id: UUID | None = None
    calidad: int
    calidad_faltan: list[str] = []
    campos: dict[str, Any] = {}
    version: int
    created_at: datetime

    model_config = {"from_attributes": True}


class VincularContacto(BaseModel):
    cuenta_id: UUID
    rol: str | None = None
    cargo: str | None = None
    principal: bool = False


class EnlazarJerarquia(BaseModel):
    padre_id: UUID
    jerarquia: str = Field(
        "legal",
        description=(
            "Pueden coexistir varias: legal, comercial, facturación, entrega. "
            "La estructura legal de un grupo no es la comercial"
        ),
        examples=["legal", "comercial"],
    )
    rol: str | None = Field(None, examples=["filial", "delegacion", "centro"])


class RegistrarConsentimiento(BaseModel):
    finalidad: str = Field(..., examples=["comercial", "newsletter", "perfilado"])
    canal: Literal["email", "sms", "telefono", "postal", "whatsapp"]
    concedido: bool
    base_legal: Literal["consentimiento", "interes_legitimo", "contrato", "obligacion_legal"] = (
        "consentimiento"
    )
    origen: str | None = Field(None, examples=["formulario web", "alta telefónica"])
    texto_aceptado: str | None = Field(
        None, description="El texto exacto que aceptó. Es la prueba ante una reclamación"
    )
    evidencia: dict[str, Any] = Field(default_factory=dict)


class ConsentimientoOut(BaseModel):
    id: UUID
    finalidad: str
    canal: str
    concedido: bool
    base_legal: str
    origen: str | None = None
    fecha: datetime
    caduca_at: datetime | None = None

    model_config = {"from_attributes": True}


class CrearActividad(BaseModel):
    tipo: Literal["tarea", "llamada", "reunion", "nota", "visita", "email"]
    asunto: str = Field(..., min_length=1, max_length=300)
    cuerpo: str | None = None
    objeto: str | None = Field(
        None,
        description="Objeto al que se cuelga: cuenta, contacto, oportunidad, caso…",
        examples=["cuenta"],
    )
    objeto_id: UUID | None = None
    cuenta_id: UUID | None = None
    contacto_id: UUID | None = None
    prioridad: Literal["baja", "normal", "alta", "urgente"] = "normal"
    asignada_a: UUID | None = None
    vence_at: datetime | None = None
    recordar_at: datetime | None = Field(
        None, description="Si se omite y hay vencimiento, se calcula con la antelación configurada"
    )
    inicio_at: datetime | None = None
    fin_at: datetime | None = None
    detalles: dict[str, Any] = Field(
        default_factory=dict,
        description="Datos propios del tipo: duración, asistentes, coordenadas",
    )


class ActividadOut(BaseModel):
    id: UUID
    tipo: str
    asunto: str
    cuerpo: str | None = None
    objeto: str | None = None
    objeto_id: UUID | None = None
    cuenta_id: UUID | None = None
    contacto_id: UUID | None = None
    estado: str
    prioridad: str
    asignada_a: UUID | None = None
    vence_at: datetime | None = None
    completada_at: datetime | None = None
    resultado: str | None = None
    detalles: dict[str, Any] = {}
    created_at: datetime

    model_config = {"from_attributes": True}


class CompletarActividad(BaseModel):
    resultado: str | None = Field(None, examples=["contactado", "sin respuesta", "reunión fijada"])


class Fusionar(BaseModel):
    absorbido_id: UUID
    campos_ganadores: dict[str, Literal["superviviente", "absorbida"]] = Field(
        default_factory=dict,
        description=(
            "De cuál se queda cada campo. Lo que no se indique se queda del "
            "superviviente, salvo que esté vacío y el otro lo tenga"
        ),
    )
    motivo: str = Field(..., min_length=5, description="Queda en la auditoría")


class CandidatoOut(BaseModel):
    id: UUID
    nombre: str
    similitud: float
    senales: list[str] = Field(
        ..., description="Por qué se propone: identificador_fiscal, dominio, nombre, email"
    )
    concluyente: bool


class SolicitudDerechosEntrada(BaseModel):
    email_solicitante: EmailStr
    tipo: Literal["acceso", "rectificacion", "supresion", "portabilidad", "oposicion", "limitacion"]
    contacto_id: UUID | None = None
    canal_entrada: str | None = None


class SolicitudDerechosOut(BaseModel):
    id: UUID
    email_solicitante: str
    tipo: str
    estado: str
    recibida_at: datetime
    vence_at: datetime
    resuelta_at: datetime | None = None
    dias_restantes: int = Field(..., description="Negativo si ya ha vencido")

    model_config = {"from_attributes": True}


class EntradaTimeline(BaseModel):
    momento: datetime
    tipo: str
    titulo: str
    estado: str | None = None
    objeto: str | None = None
    objeto_id: str | None = None
    actor: str | None = None
    origen: str | None = None
    id: str


class Vista360(BaseModel):
    cuenta: dict[str, Any]
    identificadores: list[dict[str, Any]]
    direcciones: list[dict[str, Any]]
    contactos: list[dict[str, Any]]
    timeline: list[dict[str, Any]]
    metricas: dict[str, Any]
