"""Lo que un componente incrustado en una web ajena puede leer de sales.

Sin identificador en la ruta: el del token (CRM-00.02.03.05). El estado y las
fechas, **no las líneas ni los importes**: un componente de seguimiento se
incrusta en una web pública, y el precio al que se vendió no se enseña ahí.
"""

from __future__ import annotations

from typing import Annotated, Any

from crmcore.errors import NoEncontrado
from crmcore.http.deps import AccesoComponente, DbDep, UowDep, exige_componente
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from services.sales.presupuestos import Pedido

router_embebido = APIRouter(prefix="/embebido", tags=["componentes embebibles"])


@router_embebido.get(
    "/estado-pedido",
    summary="En qué va el pedido del token",
    description=(
        "El número, el estado y las fechas. Ni las líneas ni los importes: "
        "esto se pinta en una web pública."
    ),
)
def estado_pedido(
    db: DbDep,
    acceso: Annotated[
        AccesoComponente,
        Depends(exige_componente("estado-pedido")),
    ],
) -> Any:
    fila = db.execute(
        select(Pedido).where(Pedido.id == acceso.objeto_id, Pedido.tenant_id == acceso.tenant_id)
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado("No existe ese pedido", error_code="embebido.no_encontrado")
    return {
        "numero": fila.numero,
        "estado": fila.estado,
        "confirmado_at": fila.confirmado_at.isoformat() if fila.confirmado_at else None,
        "enviado_at": fila.enviado_at.isoformat() if fila.enviado_at else None,
    }


class AltaEmbebida(BaseModel):
    """Lo que un formulario incrustado puede mandar.

    **Campos declarados y no un diccionario suelto.** Con un diccionario
    abierto, el formulario que genera el contrato sale vacío —no hay nada que
    pintar— y además cualquiera puede mandar cualquier cosa desde una página
    pública. Lo que el formulario del cliente pregunte de más va en `extra`, y
    de ahí a los campos libres del lead: tirarlo obligaría a mirar el correo de
    aviso para saber qué pidió el interesado.
    """

    nombre: str = Field("", max_length=200)
    apellidos: str = Field("", max_length=200)
    empresa: str = Field("", max_length=200)
    email: str = Field("", max_length=320)
    telefono: str = Field("", max_length=40)
    mensaje: str = Field("", max_length=2000)
    extra: dict[str, Any] = Field(default_factory=dict)
    # El campo trampa del canal: un humano no lo ve y no lo rellena.
    trampa: str = Field("", max_length=200)


@router_embebido.post(
    "/formulario-alta",
    summary="Recoger un alta desde una web ajena",
    description=(
        "El único componente que ESCRIBE, y por eso el más acotado: **no "
        "devuelve nada del CRM**. Un formulario incrustado que contestara con "
        "datos de dentro sería una puerta de lectura disfrazada de "
        "formulario.\n\n"
        "Pasa por el MISMO canal de captura que un formulario web normal —con "
        "su campo trampa, su tope por hora y sus obligatorios—, porque un "
        "segundo camino de entrada es un segundo sitio donde un robot puede "
        "colar leads. Lo que cambia es cómo se prueba que se puede escribir: "
        "el token acotado en vez de la clave y el secreto, que no pueden vivir "
        "en el HTML de una página ajena."
    ),
)
def formulario_alta(
    datos: AltaEmbebida,
    uow: UowDep,
    acceso: Annotated[
        AccesoComponente,
        Depends(exige_componente("formulario-alta")),
    ],
) -> Any:
    from services.sales.captura import CanalCaptura, recibir_por_canal

    canal = uow.db.execute(
        select(CanalCaptura).where(
            CanalCaptura.id == acceso.objeto_id,
            CanalCaptura.tenant_id == acceso.tenant_id,
            # Un canal apagado no recibe, tampoco por aquí: por la puerta
            # pública ya era así, y un segundo camino con otra regla es el
            # camino por el que entra lo que se quiso cortar.
            CanalCaptura.activo.is_(True),
            CanalCaptura.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if canal is None:
        raise NoEncontrado("No existe ese formulario", error_code="embebido.no_encontrado")

    entrada: dict[str, Any] = {
        k: v for k, v in datos.model_dump(exclude={"extra", "trampa"}).items() if v
    }
    entrada.update(datos.extra)
    if canal.campo_trampa and datos.trampa:
        entrada[canal.campo_trampa] = datos.trampa

    recibir_por_canal(uow, canal, entrada)
    # Se contesta SIEMPRE lo mismo, se haya creado o descartado: una respuesta
    # distinta por motivo le enseña a un robot qué cambiar para la próxima. Y
    # no se devuelve el identificador de lo creado: con él, quien tenga el
    # token del formulario podría recorrer los leads.
    return {"recibido": True}
