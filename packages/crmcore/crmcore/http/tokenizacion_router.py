"""Tokenizar y recuperar, servido por servicio (CRM-00.05.03.04).

Cifrar un número de tarjeta lo protege de quien lea la base. **Tokenizarlo lo
saca de la base**: lo que queda en el CRM es una referencia sin valor, y el
número vive donde sabe guardarlo quien tiene el certificado para hacerlo. La
diferencia importa el día de la auditoría — un sistema que cifra tarjetas sigue
dentro del alcance de PCI; uno que no las tiene, no.

El módulo que lo resuelve estaba entero: los tipos admitidos, la pista que se
conserva de cada uno, el rechazo a tokenizar en falso cuando no hay bóveda, el
rastro al recuperar. **Y no había forma de pedirlo.** Lo único que llegaba a
ejecutarse era el detector de números colados por texto libre, que avisa de que
este despliegue no tiene bóveda — un aviso sobre una capacidad que, además, no se
podía usar.

Va **por servicio** y no en un sitio central: lo que se tokeniza son datos de
registros que viven en el esquema de cada servicio, y un punto central tendría
que leer los esquemas de los demás.

**Recuperar es una operación sensible.** Lleva permiso propio, segundo factor
reciente, motivo obligatorio y queda en la auditoría con quién y para qué. Si
fuera transparente —que el ORM lo resolviera al leer— el número volvería a estar
en todas partes: en los registros, en las cachés, en las respuestas de la API, y
la tokenización no habría servido de nada. Tiene que costar pedirlo.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from crmcore.audit.chain import registrar
from crmcore.http.deps import AutenticadoDep, DbDep, exige_permiso
from crmcore.http.reverificacion import exige_reverificacion
from crmcore.security.tokenizacion import TIPOS, destokenizar, hay_boveda, tokenizar


class TokenizarIn(BaseModel):
    valor: str = Field(..., min_length=1, description="El número que NO se queda en el CRM")
    tipo: str = Field(..., description=f"Uno de: {', '.join(TIPOS)}")


class ResolverIn(BaseModel):
    tipo: str = Field(..., description=f"Uno de: {', '.join(TIPOS)}")
    motivo: str = Field(
        ...,
        min_length=3,
        description=(
            "Para qué se recupera. **Obligatorio**: sin motivo, la lista de accesos "
            "es una lista de nombres sin nada que decidir"
        ),
    )


def crear_router_tokenizacion(servicio: str) -> APIRouter:
    router = APIRouter(prefix=f"/{servicio}/tokenizacion", tags=["tokenización"])

    @router.get(
        "",
        dependencies=[Depends(exige_permiso("tokenizacion:read"))],
        summary="Si este despliegue puede tokenizar, y qué",
        description=(
            "**Se pregunta antes de ofrecer el campo.** Sin bóveda no se tokeniza en "
            "falso: guardar el número «hasta que haya bóveda» mete el sistema en el "
            "alcance de PCI sin que nadie lo haya decidido. Una pantalla que ofrece "
            "guardar la tarjeta en un despliegue sin bóveda promete algo que va a "
            "fallar al guardar, con el cliente delante."
        ),
    )
    def estado_tokenizacion() -> Any:
        return {
            "hay_boveda": hay_boveda(),
            "tipos": list(TIPOS),
            "que_significa": (
                "Con bóveda, el número sale del CRM y queda una referencia sin valor."
                if hay_boveda()
                else "Sin bóveda, este despliegue NO puede guardar estos datos: ni "
                "tokenizados ni en claro. Va en el sistema de pagos, no en el CRM."
            ),
        }

    @router.post(
        "",
        dependencies=[Depends(exige_permiso("tokenizacion:write"))],
        summary="Sacar un número del CRM y quedarse con la referencia",
        description=(
            "Devuelve el token y una **pista** —los cuatro últimos de una tarjeta, "
            "nada de un identificador fiscal, porque con la letra y dos dígitos se "
            "adivina el resto—. La pista es para que una persona reconozca lo suyo, "
            "no para operar con ella.\n\n"
            "Sin bóveda configurada **falla y lo dice**, en vez de guardar el número "
            "mientras tanto."
        ),
    )
    def tokenizar_valor(cuerpo: TokenizarIn, principal: AutenticadoDep, db: DbDep) -> Any:
        salida = tokenizar(cuerpo.valor, tipo=cuerpo.tipo, tenant_id=principal.tenant_id)
        # Queda apuntado QUE se tokenizó, nunca el valor: una auditoría con el
        # número dentro devuelve el dato a la base por la puerta de atrás.
        registrar(
            db,
            accion="tokenizacion.creada",
            objeto="token",
            objeto_id=None,
            datos={"tipo": cuerpo.tipo, "pista": salida.get("pista", "")},
            tenant_id=principal.tenant_id,
        )
        return salida

    @router.post(
        "/{token}/resolver",
        dependencies=[
            Depends(exige_permiso("tokenizacion:resolver")),
            Depends(exige_reverificacion("destokenizacion")),
        ],
        summary="Recuperar el número, con motivo y rastro",
        description=(
            "**Operación sensible**: exige permiso propio, segundo factor reciente y "
            "un motivo. Queda en la auditoría con quién lo pidió y para qué.\n\n"
            "No es transparente a propósito. Si el CRM lo resolviera solo al leer, el "
            "número volvería a estar en los registros, en las cachés y en las "
            "respuestas de la API — y tokenizarlo no habría servido de nada."
        ),
    )
    def resolver_token(token: str, cuerpo: ResolverIn, principal: AutenticadoDep, db: DbDep) -> Any:
        valor = destokenizar(
            token,
            tipo=cuerpo.tipo,
            tenant_id=principal.tenant_id,
            motivo=cuerpo.motivo,
            por=principal.id,
        )
        registrar(
            db,
            accion="tokenizacion.resuelta",
            objeto="token",
            objeto_id=None,
            datos={"tipo": cuerpo.tipo},
            motivo=cuerpo.motivo[:200],
            tenant_id=principal.tenant_id,
        )
        return {
            "valor": valor,
            "queda_registrado": (
                "Esta recuperación queda en la auditoría con tu nombre y el motivo "
                "que has dado. Es lo que hace que tokenizar sirva de algo."
            ),
        }

    return router
