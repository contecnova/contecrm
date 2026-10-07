"""El alta autoservicio, servida (CRM-00.01.03.01).

Dos rutas **sin autenticar**, que es lo que las hace autoservicio: quien da de
alta su empresa todavía no tiene cuenta aquí. Eso obliga a cuidar tres cosas que
una ruta interna no necesita, y están cuidadas en `services.tenancy.alta`:

  · el correo se verifica antes de crear nada;
  · la respuesta no distingue si el identificador estaba cogido, para que esto
    no sea un comprobador de qué empresas son clientes;
  · hay límite por IP, y mucho más estrecho que el general de la API, porque
    esto crea tenants.

El token se **devuelve en la respuesta**, igual que en el restablecimiento de
contraseña y por lo mismo: lo manda quien integre el correo. Nunca se le enseña
a quien lo pide.
"""

from __future__ import annotations

from typing import Any

from crmcore.errors import LimiteExcedido
from fastapi import APIRouter, Request
from pydantic import BaseModel, EmailStr, Field

from services.tenancy import alta

router_alta = APIRouter(prefix="/alta", tags=["alta autoservicio"])


class PedirAlta(BaseModel):
    slug: str = Field(
        ...,
        min_length=2,
        max_length=63,
        description="Identificador de la empresa. Va en subdominios y URLs, y es permanente.",
        examples=["acme"],
    )
    nombre_empresa: str = Field(..., min_length=1, max_length=200, examples=["ACME Industrial"])
    email: EmailStr = Field(..., description="El correo de quien será el primer administrador")
    nombre: str = Field(..., min_length=1, max_length=200, examples=["Ana Pérez"])


class ConfirmarAlta(BaseModel):
    token: str = Field(..., min_length=1, description="El del enlace que llegó por correo")


def _ip(request: Request) -> str:
    return getattr(request.client, "host", "") or ""


def _limitar(request: Request) -> None:
    """Tope por IP propio de esta ruta, aparte del general de la API.

    El general está pensado para lecturas; esto crea tenants. Con el mismo
    número, un portátil llenaría el sistema de empresas inventadas en una tarde.
    """
    import time

    from crmcore.config import get_settings

    s = get_settings()
    tope = int(s.onboarding_altas_por_ip_hora)
    ip = _ip(request) or "sin-ip"
    ahora = time.time()
    ventana = 3_600.0
    cubo = _POR_IP.setdefault(ip, [])
    # Se tiran los de la hora anterior antes de contar: sin esto el contador
    # sólo sube y a la segunda hora nadie podría darse de alta nunca más.
    cubo[:] = [t for t in cubo if ahora - t < ventana]
    if len(cubo) >= tope:
        raise LimiteExcedido(
            "Demasiadas altas desde esta conexión. Inténtalo dentro de un rato.",
            error_code="alta.demasiadas_por_ip",
        )
    cubo.append(ahora)


# En memoria y por proceso, a propósito: es una barrera contra el abuso casual,
# no contra un ataque distribuido —eso lo para el balanceador— y meterlo en la
# caché compartida ataría el alta a que Redis esté en pie. Que una réplica
# cuente por su cuenta hace el tope más laxo con N réplicas, y aun así deja el
# abuso desde un portátil en nada.
_POR_IP: dict[str, list[float]] = {}


@router_alta.post(
    "",
    summary="Pedir el alta de una empresa",
    description=(
        "**No crea nada todavía.** Guarda la solicitud y devuelve el token del "
        "enlace de confirmación, que es lo que hay que mandarle por correo a "
        "quien lo pide: hasta que no demuestre que ese buzón es suyo, no se da "
        "de alta ninguna empresa.\n\n"
        "La respuesta es **la misma esté el identificador libre o cogido**. "
        "Distinguirlas convertiría esta pantalla en un comprobador de qué "
        "empresas son clientes: se prueba un nombre, se mira la respuesta, y ya "
        "se sabe. Si estaba cogido, se dirá al confirmar."
    ),
)
def pedir_alta(datos: PedirAlta, request: Request) -> Any:
    from crmcore.db.uow import unidad_de_trabajo

    _limitar(request)
    with unidad_de_trabajo(sistema=True) as uow:
        token = alta.solicitar(
            uow,
            slug=datos.slug,
            nombre_empresa=datos.nombre_empresa,
            email=str(datos.email),
            nombre_persona=datos.nombre,
            ip=_ip(request),
        )
    return {
        "enviado": True,
        "token": token,
        "como_sigue": (
            "Manda este token en el enlace de confirmación al correo indicado. "
            "No se lo enseñes a quien pidió el alta: el enlace es la prueba de "
            "que el buzón es suyo."
        ),
    }


@router_alta.post(
    "/confirmar",
    summary="Confirmar el alta con el token del correo",
    description=(
        "Gasta el token —**un solo uso**— y crea la empresa. Aquí sí se dice si "
        "el identificador está cogido: quien llega con un token válido ya ha "
        "demostrado ser dueño de ese buzón, así que no es un desconocido "
        "preguntando por la lista de clientes.\n\n"
        "El primer administrador no se crea en esta llamada: se emite el hecho "
        "y lo recoge el servicio de identidad, que es el dueño de los usuarios."
    ),
)
def confirmar_alta(datos: ConfirmarAlta, request: Request) -> Any:
    from crmcore.db.uow import unidad_de_trabajo

    with unidad_de_trabajo(sistema=True) as uow:
        return alta.confirmar(uow, datos.token, ip=_ip(request))


ROUTERS_ALTA = [router_alta]
