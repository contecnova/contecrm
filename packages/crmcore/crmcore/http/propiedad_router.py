"""Traspasar todo lo de una persona a otra, en cada servicio (CRM-07.01.01.07).

Es la operación que hace falta cuando alguien deja la empresa o cambia de
cartera. El maestro de clientes es de `party` y las ventas de `sales`, y ningún
servicio escribe en la base de otro: así que cada uno publica **la misma ruta
sobre sus objetos** y la pantalla las llama todas. Esta fábrica es lo común, para
que las dos —y las que vengan— digan lo mismo, simulen igual y auditen igual.

`simular=true` (el valor por defecto) cuenta sin mover nada: quien la ejecuta
necesita ver **cuánto** va a mover —mil cuentas y tres oportunidades es una
cosa, y al revés es otra— antes de moverlo. Sin simular, exige un motivo, que
queda en la auditoría junto con lo movido.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from crmcore.errors import ErrorValidacion
from crmcore.http.deps import AutenticadoDep, DbDep, exige_permiso


class TransferirPropiedad(BaseModel):
    """El traspaso de todo lo de una persona a otra, cuando alguien se va."""

    de_usuario: UUID
    a_usuario: UUID
    motivo: str = Field("", max_length=1000)
    simular: bool = Field(True, description="Cuenta sin mover nada")


def crear_router_transferencia(
    *, prefijo: str, modelos: list[type], permiso: str, que: str
) -> APIRouter:
    """Monta `POST {prefijo}/transferir-propiedad` sobre `modelos`.

    `que` es la frase que dice qué mueve este servicio —«cuentas, contactos y
    actividades»—: va en la descripción del contrato, que es lo que lee quien
    integra y la pantalla que la ofrece.
    """
    router = APIRouter(prefix=prefijo, tags=["administración"])

    @router.post(
        "/transferir-propiedad",
        response_model=dict,
        dependencies=[Depends(exige_permiso(permiso))],
        summary="Traspasar todo lo de una persona a otra",
        description=(
            f"Mueve {que} de un propietario a otro. Con `simular=true` cuenta sin "
            "tocar nada: quien la ejecuta necesita ver cuánto va a mover antes de "
            "moverlo. Sin simular exige un motivo, que queda en la auditoría."
        ),
    )
    def transferir(datos: TransferirPropiedad, db: DbDep, principal: AutenticadoDep) -> Any:
        from crmcore.datos.masivas import transferir_propiedad

        if datos.de_usuario == datos.a_usuario:
            raise ErrorValidacion(
                "El origen y el destino son la misma persona",
                error_code="propiedad.mismo_usuario",
            )
        if not datos.simular and len(datos.motivo.strip()) < 5:
            raise ErrorValidacion(
                "La transferencia exige un motivo escrito",
                error_code="party.transferencia_sin_motivo",
            )
        movidos = transferir_propiedad(
            db,
            tenant_id=principal.tenant_id,
            modelos=modelos,
            de_usuario=datos.de_usuario,
            a_usuario=datos.a_usuario,
            motivo=datos.motivo,
            simular=datos.simular,
        )
        return {"simulado": datos.simular, "movidos": movidos, "total": sum(movidos.values())}

    return router
