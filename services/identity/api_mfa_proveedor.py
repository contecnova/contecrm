"""API del segundo factor por proveedor (CRM-00.05.01.22).

Los perfiles se escriben con `tenant:write` —son la puerta de entrada de la
empresa— y se leen con `user:read`, como el resto de la pantalla de seguridad.
El secreto entra y no sale: la respuesta sólo dice si lo hay.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.http.deps import AutenticadoDep, DbDep, exige_permiso
from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field

from services.identity import mfa_proveedor as mp

router_mfa_proveedor = APIRouter(prefix="/mfa-proveedor", tags=["segundo factor"])


class PerfilEntrada(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=120)
    plantilla: str = Field("", max_length=60)
    activo: bool = False
    url: str = Field(..., min_length=1, max_length=1000)
    metodo: str = "POST"
    formato: str = "json"
    autenticacion: dict[str, Any] = Field(
        default_factory=lambda: {"tipo": "ninguna"},
        description="tipo: ninguna | basica (usuario) | bearer | cabecera (cabecera, valor con {{secreto}})",
    )
    secreto: str = Field(
        "",
        max_length=2000,
        description="Se guarda cifrado y no se devuelve nunca. Vacío conserva el que había.",
    )
    quitar_secreto: bool = False
    cabeceras: dict[str, Any] = Field(default_factory=dict)
    cuerpo: dict[str, Any] = Field(default_factory=dict)
    variables: dict[str, Any] = Field(default_factory=dict)
    campos_persona: list[str] = Field(default_factory=list)
    respuesta: dict[str, Any] = Field(
        default_factory=dict, description="campo (ruta con puntos) y validos (lista)"
    )


class Vincular(BaseModel):
    datos: dict[str, Any] = Field(default_factory=dict)


class Probar(BaseModel):
    usuario_id: UUID
    codigo: str = Field(..., min_length=1, max_length=64)


@router_mfa_proveedor.get(
    "/plantillas",
    summary="Plantillas de perfil de segundo factor por proveedor",
    description=(
        "Datos para rellenar el formulario: Twilio Verify, Okta Verify, Duo y "
        "RSA SecurID. No hay código de ningún proveedor: la plantilla es la "
        "misma forma que el perfil, con sus marcas por rellenar."
    ),
    dependencies=[Depends(exige_permiso("user:read"))],
)
def plantillas(_: AutenticadoDep) -> Any:
    return mp.plantillas()


@router_mfa_proveedor.get(
    "/perfiles",
    summary="Perfiles de segundo factor por proveedor de esta empresa",
    dependencies=[Depends(exige_permiso("user:read"))],
)
def listar(db: DbDep, principal: AutenticadoDep) -> Any:
    return {"items": mp.listar(db, principal.tenant_id)}


@router_mfa_proveedor.post(
    "/perfiles",
    status_code=status.HTTP_201_CREATED,
    summary="Dar de alta un perfil de segundo factor por proveedor",
    dependencies=[Depends(exige_permiso("tenant:write"))],
)
def crear(datos: PerfilEntrada, db: DbDep, principal: AutenticadoDep) -> Any:
    return mp.guardar(db, principal.tenant_id, datos.model_dump())


@router_mfa_proveedor.put(
    "/perfiles/{perfil_id}",
    summary="Cambiar un perfil de segundo factor por proveedor",
    description="Un secreto vacío conserva el guardado; `quitar_secreto` lo borra.",
    dependencies=[Depends(exige_permiso("tenant:write"))],
)
def cambiar(perfil_id: UUID, datos: PerfilEntrada, db: DbDep, principal: AutenticadoDep) -> Any:
    return mp.guardar(db, principal.tenant_id, datos.model_dump(), perfil_id=perfil_id)


@router_mfa_proveedor.delete(
    "/perfiles/{perfil_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Borrar un perfil de segundo factor por proveedor",
    dependencies=[Depends(exige_permiso("tenant:write"))],
)
def borrar(perfil_id: UUID, db: DbDep, principal: AutenticadoDep) -> Response:
    mp.borrar(db, principal.tenant_id, perfil_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router_mfa_proveedor.get(
    "/perfiles/{perfil_id}/personas",
    summary="Quién es cada persona en el proveedor",
    dependencies=[Depends(exige_permiso("user:read"))],
)
def personas(perfil_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return {"items": mp.vinculos(db, principal.tenant_id, perfil_id)}


@router_mfa_proveedor.put(
    "/perfiles/{perfil_id}/personas/{usuario_id}",
    summary="Apuntar los datos de una persona en el proveedor (vacío la quita)",
    dependencies=[Depends(exige_permiso("tenant:write"))],
)
def vincular(
    perfil_id: UUID, usuario_id: UUID, datos: Vincular, db: DbDep, principal: AutenticadoDep
) -> Any:
    return mp.vincular(db, principal.tenant_id, perfil_id, usuario_id, datos.datos)


@router_mfa_proveedor.post(
    "/perfiles/{perfil_id}/probar",
    summary="Probar un código contra el proveedor sin entrar",
    description=(
        "Hace la misma llamada que el login y devuelve si el código vale, qué "
        "contestó el proveedor y la petición que se mandó **con el secreto y el "
        "código tapados**."
    ),
    dependencies=[Depends(exige_permiso("tenant:write"))],
)
def probar(perfil_id: UUID, datos: Probar, db: DbDep, principal: AutenticadoDep) -> Any:
    return mp.probar(
        db, principal.tenant_id, perfil_id, usuario_id=datos.usuario_id, codigo=datos.codigo
    )


ROUTERS_MFA_PROVEEDOR = [router_mfa_proveedor]
