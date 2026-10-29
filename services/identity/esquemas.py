"""Contratos del servicio de identidad."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, model_validator


class Credenciales(BaseModel):
    email: EmailStr
    contrasena: str = Field(..., min_length=1, max_length=256)
    tenant: str = Field(
        ...,
        description=(
            "Slug o identificador del tenant. Es obligatorio porque la misma "
            "persona puede pertenecer a varios y sus permisos son distintos en "
            "cada uno"
        ),
    )
    codigo_mfa: str = Field(
        "",
        max_length=16,
        description="TOTP, código enviado por SMS o correo, o código de recuperación",
    )
    huella_dispositivo: str = Field(
        "",
        max_length=200,
        description=(
            "Huella del equipo. Si es un dispositivo de confianza vigente "
            "(CRM-00.05.01.20), no se pide el segundo factor. **Nunca** salta la "
            "contraseña: recordar el equipo ahorra el factor, no la credencial"
        ),
    )
    recordar_dispositivo: bool = Field(
        False,
        description=(
            "Marcar este equipo como de confianza tras superar el segundo "
            "factor. Solo tiene efecto si la instalación lo permite"
        ),
    )


class Tokens(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int = Field(..., description="Segundos de validez del token de acceso")
    riesgo: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Qué ha cambiado del contexto de esta entrada y **qué no se ha "
            "podido mirar**. Vacío cuando la sesión no nace de un login "
            "—renovación, suplantación—, donde no hay contexto nuevo que evaluar"
        ),
    )


class Renovar(BaseModel):
    refresh_token: str


class CrearUsuario(BaseModel):
    email: EmailStr
    nombre: str = Field(..., min_length=1, max_length=200)
    roles: list[str] = Field(default_factory=lambda: ["usuario"])
    contrasena: str | None = Field(
        None,
        min_length=12,
        description=(
            "Opcional. Sin contraseña, el usuario solo puede entrar por el "
            "proveedor de identidad del tenant — que es como se fuerza el SSO"
        ),
    )


class UsuarioOut(BaseModel):
    id: UUID
    email: str
    nombre: str
    activo: bool
    mfa_activo: bool
    es_plataforma: bool
    ultimo_acceso_at: datetime | None = None
    # Por qué no entra: cuántos intentos fallidos lleva y hasta cuándo está
    # bloqueado. Sin esto, «no puedo entrar» se contesta mirando los registros
    # del servidor. El secreto de MFA, sus códigos de recuperación y el hash
    # de la contraseña NO salen, y no es un olvido.
    intentos_fallidos: int = 0
    bloqueado_hasta: datetime | None = None
    preferencias: dict[str, Any] = {}
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class MembresiaOut(BaseModel):
    tenant_id: UUID
    roles: list[str] = []
    business_unit_id: UUID | None = None
    superior_id: UUID | None = None
    activa: bool

    model_config = {"from_attributes": True}


class YoOut(BaseModel):
    """Identidad efectiva del portador del token.

    Devuelve los permisos ya resueltos para que un frontend headless pueda
    decidir qué enseña sin reimplementar la resolución de roles — que es como se
    acaba enseñando un botón que el backend luego rechaza.
    """

    usuario: UsuarioOut
    tenant_id: UUID | None
    roles: list[str] = []
    permisos: list[str] = []
    suplantado_por: UUID | None = None


class ActivarMfa(BaseModel):
    codigo: str = Field(..., min_length=6, max_length=6)


class MfaIniciada(BaseModel):
    secreto: str
    uri_otpauth: str = Field(..., description="Para generar el código QR en el cliente")
    codigos_recuperacion: list[str] = Field(
        ..., description="Se enseñan UNA vez. Después solo se guarda su hash"
    )


class CrearClaveApi(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=120)
    scopes: list[str] = Field(default_factory=list, examples=[["account:read", "opportunity:read"]])
    rol: str = "integracion"
    dias: int | None = Field(None, ge=0, le=3650, description="0 = sin caducidad (desaconsejado)")
    ips_permitidas: list[str] = Field(default_factory=list)


class ClaveApiCreada(BaseModel):
    id: UUID
    nombre: str
    prefijo: str
    secreto: str = Field(..., description="Se muestra UNA sola vez. Guárdalo ahora")
    expira_at: datetime | None = None


class ClaveApiOut(BaseModel):
    id: UUID
    nombre: str
    prefijo: str
    rol: str
    scopes: list[str] = []
    expira_at: datetime | None = None
    revocada_at: datetime | None = None
    ultimo_uso_at: datetime | None = None

    model_config = {"from_attributes": True}


class SesionOut(BaseModel):
    id: UUID
    ip: str | None = None
    user_agent: str | None = None
    creada_at: datetime
    ultima_actividad_at: datetime
    expira_at: datetime
    revocada_at: datetime | None = None
    actor_real_id: UUID | None = None
    # **El motivo de la suplantación, que se guardaba y no se devolvía.**
    # Entrar como otra persona exige escribir por qué —y hace bien— pero ese
    # porqué no se podía leer desde ninguna parte: quedaba un identificador en
    # una columna y nadie sabe de quién es un UUID. Una exigencia que no se
    # puede revisar es papeleo.
    motivo_suplantacion: str | None = None
    # Derivado para que la lista se pueda leer de un vistazo. Un `actor_real_id`
    # con valor ya lo dice, pero lo dice en un formato que nadie lee.
    suplantada: bool = False
    # **Si al salir se cerrará también en el proveedor** (CRM-00.05.01.12).
    #
    # La correspondencia entre esta sesión y la del IdP se guarda —es la que
    # hace que el aviso de cierre del proveedor sepa a quién aplicarse— y **no
    # la devolvía nadie**. Sin ella, salir cierra aquí y deja la sesión del
    # proveedor viva: volver a entrar no pide credenciales y, para quien lo
    # hace, el botón de salir no ha hecho nada.
    #
    # Que no esté enlazada no es un fallo de aquí: hay proveedores que no
    # mandan índice de sesión. Pero es una carencia que hay que poder ver, y
    # el propio código ya la anotaba en la auditoría sin que nadie pudiera
    # consultarla.
    enlazada_al_idp: bool = False

    model_config = {"from_attributes": True}

    @model_validator(mode="after")
    def _marcar_suplantada(self) -> "SesionOut":
        # Se calcula aquí y no en cada consulta: si lo pusiera cada ruta, la
        # que se olvidara devolvería una suplantación disfrazada de sesión
        # normal, que es justo lo que no puede pasar.
        object.__setattr__(self, "suplantada", self.actor_real_id is not None)
        return self


class Suplantar(BaseModel):
    usuario_id: UUID
    motivo: str = Field(
        ...,
        min_length=10,
        description=(
            "Queda en la auditoría del tenant y es lo que hace defendible el "
            "acceso. Diez caracteres mínimo: «ticket 4312, el cliente no puede "
            "cerrar una oportunidad»"
        ),
    )


class CrearRol(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=80)
    descripcion: str = ""
    permisos: list[str] = Field(default_factory=list, examples=[["opportunity:read"]])
    hereda_de: str | None = None


class RolOut(BaseModel):
    id: UUID
    nombre: str
    descripcion: str
    permisos: list[str] = []
    hereda_de: str | None = None

    model_config = {"from_attributes": True}


class ExplicarPermiso(BaseModel):
    """Entrada del explicador de permisos (CRM-00.05.02.11)."""

    usuario_id: UUID
    objeto: str = Field(..., examples=["opportunity"])
    accion: str = Field(..., examples=["write"])
    registro: dict[str, Any] = Field(
        default_factory=dict,
        description="Campos del registro concreto, para evaluar las políticas ABAC",
    )
