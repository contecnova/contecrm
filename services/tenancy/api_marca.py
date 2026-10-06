"""Marca blanca: el producto con la cara del cliente (CRM-00.01.04.06).

El módulo que la resuelve estaba entero —los cuatro sitios por los que se escapa
la marca del fabricante, el contraste de los colores comprobado, el dominio que
no se da por bueno hasta verificarlo, la activación que exige que esté completa—
y **no tenía ni una ruta**. No era que faltara una pieza: la capacidad entera era
inalcanzable desde fuera.

Guardar y activar van **separados**, igual que en el módulo: la marca se
configura por partes y en varias sesiones, y activarla a medias es lo que hace
que el primer correo salga con el dominio del fabricante — delante del cliente
del cliente.
"""

from __future__ import annotations

from typing import Any

from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from services.tenancy import marca as mrc

router_marca = APIRouter(prefix="/marca", tags=["marca blanca"])


class MarcaIn(BaseModel):
    """Lo que se puede configurar. Todo opcional: se rellena por partes."""

    nombre_producto: str = Field("", max_length=120)
    logo_url: str = Field("", max_length=500)
    favicon_url: str = Field("", max_length=500)
    color_principal: str = Field("", max_length=20, examples=["#1b4fd8"])
    color_texto: str = Field("", max_length=20)
    color_fondo: str = Field("", max_length=20)
    dominio_propio: str = Field("", max_length=200, description="El de los enlaces de los correos")
    dominio_envio: str = Field("", max_length=200, description="Desde el que salen los correos")
    remitente: str = Field("", max_length=200)
    pie_correo: str = Field("", max_length=2000)


class VerificacionIn(BaseModel):
    cual: str = Field(..., pattern="^(propio|envio)$")
    verificado: bool
    detalle: str = Field(
        "",
        max_length=500,
        description="Qué se comprobó y cuándo: el registro DNS encontrado, o por qué no",
    )


@router_marca.get(
    "",
    dependencies=[Depends(exige_permiso("tenant:read"))],
    summary="Qué falta para poder activar la marca blanca",
    description=(
        "**Lo que falta, con el motivo de cada cosa.** Una marca blanca a medias "
        "es peor que ninguna: si se anuncia y el correo sale con el dominio del "
        "fabricante, la conversación que sigue no es sobre el correo.\n\n"
        "La marca del fabricante se escapa siempre por los mismos cuatro sitios "
        "—el remitente de los correos, el dominio de los enlaces, el pie de las "
        "plantillas y el título de la pestaña—, y con uno solo mal el cliente "
        "descubre a su proveedor en el peor momento.\n\n"
        "Trae además el **aviso de contraste**: una paleta corporativa preciosa "
        "con texto gris sobre blanco deja media aplicación ilegible, y quien la "
        "eligió no lo ve porque la mira en su pantalla buena."
    ),
)
def estado_marca(db: DbDep, principal: AutenticadoDep) -> Any:
    return mrc.comprobar(db, principal.tenant_id)


@router_marca.put(
    "",
    dependencies=[Depends(exige_permiso("tenant:write"))],
    summary="Configurar la marca, sin activarla",
    description=(
        "**Guardar no activa.** Se configura por partes y en varias sesiones, y "
        "activar a medias es justo lo que esto evita. Cuando esté completa, se "
        "enciende con una llamada aparte."
    ),
)
def guardar_marca(cuerpo: MarcaIn, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = mrc.guardar(uow, tenant_id=principal.tenant_id, **cuerpo.model_dump())
    return {
        "tenant_id": str(principal.tenant_id),
        "activa": fila.activa,
        # Lo que todavía falta, en la misma respuesta: quien acaba de guardar es
        # quien tiene que enterarse de lo que queda, no el que mire el panel
        # mañana.
        **mrc.comprobar(uow.db, principal.tenant_id),
    }


@router_marca.post(
    "/dominio/verificacion",
    dependencies=[Depends(exige_permiso("tenant:write"))],
    summary="Anotar el resultado de comprobar un dominio",
    description=(
        "**La comprobación de DNS la hace quien sabe hacerla**; aquí se guarda el "
        "resultado, porque es lo que decide si se puede activar la marca.\n\n"
        "Un dominio sin verificar hace que los correos acaben en spam o que los "
        "enlaces no lleven a ninguna parte, y las dos cosas parecen un fallo del "
        "producto. Por eso no se da por bueno solo. El `detalle` se guarda: «lo "
        "verificamos en su momento» no es una respuesta cuando un año después "
        "los correos empiezan a rebotar."
    ),
)
def verificar_dominio(cuerpo: VerificacionIn, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = mrc.verificar_dominio(
        uow,
        tenant_id=principal.tenant_id,
        cual=cuerpo.cual,
        verificado=cuerpo.verificado,
        detalle=cuerpo.detalle,
    )
    return {
        "cual": cuerpo.cual,
        "verificado": cuerpo.verificado,
        "dominio_propio_verificado": fila.dominio_verificado,
        "dominio_envio_verificado": fila.dominio_envio_verificado,
        **mrc.comprobar(uow.db, principal.tenant_id),
    }


@router_marca.post(
    "/activar",
    dependencies=[Depends(exige_permiso("tenant:write"))],
    summary="Encender la marca blanca",
    description=(
        "**Solo si está completa.** Si falta algo contesta 409 con la lista de lo "
        "que falta y por qué: activarla a medias deja el producto enseñando la "
        "marca del fabricante por el hueco que quede."
    ),
)
def activar_marca(uow: UowDep, principal: AutenticadoDep) -> Any:
    return mrc.activar(uow, tenant_id=principal.tenant_id)


ROUTERS_MARCA = [router_marca]
