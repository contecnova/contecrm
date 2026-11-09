"""Notas, ficheros y conversaciones de la suite vinculados a un registro
(CRM-06.01.03.08, .09, .12).

Se guarda la referencia, no el contenido, y los permisos se resuelven en el
origen cada vez que alguien la abre.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.errors import NoEncontrado
from crmcore.http.deps import AutenticadoDep, DbDep, exige_permiso
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from services.integration import referencias_suite as ref

router = APIRouter(prefix="/referencias-suite", tags=["suites de productividad"])


class VincularIn(BaseModel):
    tipo: str = Field(..., description=" | ".join(ref.TIPOS))
    objeto: str = Field(..., min_length=1, max_length=60)
    objeto_id: UUID
    referencia: str = Field(
        ..., min_length=1, max_length=2_000, description="Enlace o id en el origen"
    )
    nombre: str = Field("", max_length=300)
    perfil: str = Field("", max_length=200, description="Perfil de suite que sabe abrirla")
    exportable: bool = Field(False, description="Sólo conversaciones: si el canal deja exportar")
    resumen: str = Field(
        "", max_length=2_000, description="Sólo conversaciones, escrito por una persona"
    )


@router.get(
    "",
    dependencies=[Depends(exige_permiso("activity:read"))],
    summary="Lo vinculado a un registro desde la suite",
)
def listar(
    db: DbDep,
    principal: AutenticadoDep,
    objeto: str = Query(..., min_length=1),
    objeto_id: UUID = Query(...),
) -> Any:
    return {
        "referencias": [
            ref.a_dict(f)
            for f in ref.de_registro(db, principal.tenant_id, objeto=objeto, objeto_id=objeto_id)
        ]
    }


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("activity:write"))],
    summary="Vincular una nota, un fichero o una conversación a un registro",
    description=(
        "Se guarda la referencia y nada más: ni el contenido de la nota, ni el "
        "fichero, ni los mensajes. Copiar rompe «bórralo y desaparece» y lo "
        "enseñaría a quien en el origen no tiene acceso."
    ),
)
def vincular(cuerpo: VincularIn, db: DbDep, principal: AutenticadoDep) -> Any:
    fila = ref.vincular(db, principal.tenant_id, por=principal.id, **cuerpo.model_dump())
    return ref.a_dict(fila)


@router.post(
    "/{referencia_suite_id}/abrir",
    dependencies=[Depends(exige_permiso("activity:read"))],
    summary="Abrir la referencia comprobando en el origen si existe y si puedes",
    description=(
        "Pregunta al perfil de suite con la operación del ajuste "
        "«suite_op_resolver_referencia». Distingue «no tienes acceso» de «ya no "
        "existe». Sin esa operación declarada se dice que no se puede comprobar, "
        "nunca que es accesible."
    ),
)
def abrir(referencia_suite_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return ref.abrir(
        db, principal.tenant_id, referencia_id=referencia_suite_id, usuario_id=principal.id
    )


@router.delete(
    "/{referencia_suite_id}",
    dependencies=[Depends(exige_permiso("activity:write"))],
    summary="Quitar el vínculo (en el origen no se toca nada)",
)
def quitar(referencia_suite_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    from datetime import datetime, timezone

    fila = db.get(ref.ReferenciaSuite, referencia_suite_id)
    if fila is None or fila.tenant_id != principal.tenant_id or fila.deleted_at is not None:
        raise NoEncontrado("La referencia no existe", error_code="suite.referencia_no_encontrada")
    fila.deleted_at = datetime.now(timezone.utc)
    fila.deleted_by = principal.id
    db.flush()
    return {"quitada": True}


ROUTERS_REFERENCIAS = [router]
