"""API de la clave propia del cliente — BYOK/CMEK (CRM-00.01.04.09).

Cuatro operaciones y ninguna más: ver el estado, aportar (o rotar) la clave,
generar material si el cliente prefiere que lo hagamos nosotros, y revocar.

**No hay ninguna operación que devuelva el material.** Ni siquiera a un
administrador de plataforma. Una API que puede leer la clave del cliente
convierte todo el BYOK en decoración: quien comprometa esa ruta tiene lo mismo
que tendría sin BYOK. Lo que sí se devuelve es la huella, que permite al cliente
comprobar que subió la que creía sin que nadie pueda reconstruirla.
"""

from __future__ import annotations

import base64
from typing import Any

from crmcore.errors import ErrorValidacion
from crmcore.http.deps import AutenticadoDep, UowDep, exige_permiso
from crmcore.security import byok
from fastapi import APIRouter, Body, Depends, status
from pydantic import BaseModel, Field

router_byok = APIRouter(prefix="/claves-cifrado", tags=["clave de cifrado del cliente"])


class MaterialClave(BaseModel):
    material_base64: str = Field(
        description=(
            "Material de clave en base64, de al menos 32 bytes (256 bits). "
            "No se guarda tal cual: se envuelve con la clave maestra del "
            "despliegue y solo se conserva el sobre."
        )
    )
    origen: str = Field(
        "api",
        max_length=60,
        description="De dónde viene: `api`, o el nombre del gestor externo que la trajo",
    )


class Revocacion(BaseModel):
    motivo: str = Field(
        min_length=3,
        max_length=500,
        description="Por qué se revoca. Dentro de un año alguien preguntará por qué estos datos no se leen",
    )
    confirmo_que_es_irreversible: bool = Field(
        False,
        description=(
            "Hay que ponerlo a `true` explícitamente. Revocar deja ilegibles "
            "los datos cifrados de este tenant y no hay vuelta atrás"
        ),
    )


@router_byok.get(
    "",
    dependencies=[Depends(exige_permiso("tenant:admin"))],
    summary="Estado de la clave de cifrado de este tenant",
    description=(
        "Devuelve el historial de claves con su huella y su estado. **Nunca el "
        "material**: una API que puede leer la clave del cliente convierte todo "
        "el BYOK en decoración."
    ),
)
def estado(uow: UowDep, principal: AutenticadoDep) -> Any:
    from crmcore.config import get_settings

    claves = byok.historial(uow.db, principal.tenant_id)
    return {
        "byok_habilitado": bool(get_settings().byok_enabled),
        "tiene_clave_propia": any(c["estado"] == "activa" for c in claves),
        "revocada": byok.esta_revocada(uow.db, principal.tenant_id),
        "claves": claves,
    }


@router_byok.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("tenant:admin"))],
    summary="Aportar o rotar la clave del cliente",
    description=(
        "Rotar **no invalida la anterior**: la nueva se usa para escribir y la "
        "anterior sigue sirviendo para leer lo que aún no se ha recifrado. Sin "
        "eso, rotar exigiría una ventana de parada del tamaño de la base."
    ),
)
def aportar(uow: UowDep, principal: AutenticadoDep, datos: MaterialClave = Body(...)) -> Any:
    try:
        material = base64.b64decode(datos.material_base64, validate=True)
    except Exception as exc:  # noqa: BLE001 — cualquier base64 mal formado
        raise ErrorValidacion(
            "El material no es base64 válido", error_code="byok.material_no_base64"
        ) from exc

    fila = byok.registrar(
        uow.db,
        tenant_id=principal.tenant_id,
        material=material,
        origen=datos.origen,
        por=principal.id,
    )
    return {"version": fila.version, "huella": fila.huella, "estado": fila.estado}


@router_byok.post(
    "/generar",
    dependencies=[Depends(exige_permiso("tenant:admin"))],
    summary="Generar material de clave, para quien no quiera aportarlo",
    description=(
        "Se devuelve **una sola vez** y no se guarda en claro: si se pierde, se "
        "rota. Ofrecerlo no contradice el BYOK — lo que importa no es quién "
        "teclea los bytes, sino quién puede revocarlos."
    ),
)
def generar(_: AutenticadoDep) -> Any:
    material = byok.generar_material()
    return {
        "material_base64": base64.b64encode(material).decode(),
        "huella": byok.huella_de(material),
        "aviso": (
            "Guárdalo ahora: no se conserva en claro. Súbelo con POST "
            "/claves-cifrado para activarlo."
        ),
    }


@router_byok.post(
    "/revocar",
    dependencies=[Depends(exige_permiso("tenant:admin"))],
    summary="Revocar la clave: borrado criptográfico irreversible",
    description=(
        "Olvida el material del cliente. A partir de aquí los campos cifrados de "
        "este tenant no se pueden leer: ni por nosotros, ni con una copia de "
        "seguridad, ni con la clave maestra.\n\n"
        "**No tiene vuelta atrás.** Es la operación de este sistema que menos la "
        "tiene, y por eso exige confirmación explícita y un motivo escrito."
    ),
)
def revocar(uow: UowDep, principal: AutenticadoDep, datos: Revocacion = Body(...)) -> Any:
    fila = byok.revocar(
        uow.db,
        tenant_id=principal.tenant_id,
        motivo=datos.motivo,
        confirmado=datos.confirmo_que_es_irreversible,
        por=principal.id,
    )
    return {
        "estado": fila.estado,
        "revocada_at": fila.revocada_at.isoformat() if fila.revocada_at else None,
        "huella": fila.huella,
        "aviso": "Los datos cifrados de este tenant ya no se pueden descifrar.",
    }


ROUTERS_BYOK = [router_byok]
