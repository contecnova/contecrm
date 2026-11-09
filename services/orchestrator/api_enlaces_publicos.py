"""La puerta pública del enlace de decisión (CRM-00.03.05.12).

Dos rutas **sin sesión**: quien abre el correo no tiene por qué haber entrado al
CRM, y ésa es la gracia. Por eso cuidan lo que una ruta interna no necesita:

  · el token va en el CUERPO, no en la dirección: una URL acaba en los registros
    de acceso del balanceador y del gateway, y el token es una firma;
  · inexistente, usado, caducado o de una etapa que ya no se vota responden lo
    mismo —401 «ese enlace no sirve»—;
  · ver devuelve lo justo para decidir: ni identificadores, ni quién más vota,
    ni lo interno del contexto;
  · el límite de intentos por IP lo pone el gateway (`TOPES_POR_IP`), que es el
    único que ve la IP de quien llama.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from services.orchestrator import enlaces_publicos as enl

router_enlace_publico = APIRouter(prefix="/enlace-de-aprobacion", tags=["aprobaciones"])


class ConToken(BaseModel):
    token: str = Field(..., min_length=10, max_length=200, description="El del enlace del correo")


class DecidirPorEnlace(ConToken):
    decision: Literal["aprobar", "rechazar", "pedir_cambios"]
    comentario: str = Field("", max_length=2_000)


@router_enlace_publico.post(
    "/ver",
    summary="Qué se decide con este enlace (sin sesión)",
    description=(
        "Lo mínimo para decidir: el título, la etapa, los datos que la "
        "acompañan y hasta cuándo vale el enlace. **No lo gasta**: mirar no es "
        "decidir, y el escáner del correo que abre los enlaces no puede "
        "quemarlo. Un enlace que no sirve, por la razón que sea, da siempre el "
        "mismo 401."
    ),
)
def ver_con_enlace_publico(datos: ConToken) -> Any:
    return enl.ver(datos.token)


@router_enlace_publico.post(
    "/decidir",
    summary="Aprobar, rechazar o pedir cambios con el enlace (sin sesión)",
    description=(
        "Gasta el enlace —un solo uso— y vota como su titular, con la decisión "
        "registrada `via=correo`. Devuelve sólo el desenlace: el estado entero "
        "de la aprobación lleva quién más vota, y eso no es de quien tiene el "
        "enlace."
    ),
)
def decidir_con_enlace_publico(datos: DecidirPorEnlace) -> Any:
    return enl.decidir(datos.token, decision=datos.decision, comentario=datos.comentario)
