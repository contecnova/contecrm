"""Punto de entrada del servicio de identidad."""

from __future__ import annotations

from typing import Any

from crmcore.service import crear_servicio

from services.identity.api import ROUTERS
from services.identity.notificaciones import consumir_evento

_relevo: Any = None
_tarea_relevo: Any = None


def _tareas() -> list[Any]:
    """Las tres purgas de este servicio, que no ejecutaba nadie.

    Ninguna rompe hoy y las tres rompen solas dentro de un año: estados de SSO,
    aserciones SAML y desafíos de MFA caducados acumulándose para siempre. Y
    `purgar_estados` lo decía en su propia documentación —«La ejecuta una tarea
    periódica»— cuando no había ninguna.

    Van por separado y no en una sola tarea «purgas» para que un fallo diga
    **cuál** falló: un contador no sirve para arreglar nada.
    """
    from crmcore.config import get_settings
    from crmcore.db.session import sesion
    from crmcore.tareas import Tarea

    from services.identity.factores import purgar_desafios
    from services.identity.sso import purgar_estados
    from services.identity.sso_gobierno import purgar_aserciones

    cada = get_settings().tarea_purgas_intervalo_s

    # LAS FUNCIONES SE RESUELVEN AQUÍ, no dentro del `_correr` por su nombre.
    #
    # La primera versión las buscaba con `getattr(modulo, "purgar_estados")`, y
    # eso no se comprueba al arrancar: si alguien renombra una, el servicio
    # levanta tan contento, la purga revienta en la primera vuelta, cae en el
    # `except` del relevo y se registra como aviso. Harían falta **tres** vueltas
    # para marcarla averiada, y con el intervalo por defecto eso son **tres
    # horas** de tablas creciendo con el sistema en verde.
    #
    # O sea: el módulo escrito para que nada falle en silencio, fallando en
    # silencio en su propio cableado. Importándolas, un renombrado revienta el
    # arranque, que es cuando hay alguien mirando.
    def _purga(funcion: Any, clave: str) -> Any:
        def _correr() -> dict[str, Any]:
            with sesion(sistema=True) as db:
                return {clave: funcion(db)}

        return _correr

    return [
        Tarea("identity.estados_sso", cada, _purga(purgar_estados, "borrados")),
        Tarea("identity.aserciones_saml", cada, _purga(purgar_aserciones, "borradas")),
        Tarea("identity.desafios_mfa", cada, _purga(purgar_desafios, "borrados")),
    ]


async def _al_arrancar() -> None:
    global _relevo, _tarea_relevo
    import asyncio

    from crmcore.tareas import RelevoDeTareas

    _relevo = RelevoDeTareas(_tareas())
    _tarea_relevo = asyncio.create_task(_relevo.correr(), name="identity-tareas")


async def _al_parar() -> None:
    if _relevo is not None:
        _relevo.parar()
    if _tarea_relevo is not None:
        _tarea_relevo.cancel()


app = crear_servicio(
    nombre="identity",
    descripcion=(
        "Usuarios, membresías por tenant, roles y permisos, sesiones "
        "revocables, MFA, claves de API, federación y suplantación auditada."
    ),
    routers=ROUTERS,
    al_arrancar=_al_arrancar,
    al_parar=_al_parar,
    # Las notificaciones se alimentan de eventos, no de escrituras cruzadas: los
    # servicios dueños de cada objeto no tienen permiso sobre este esquema, y no
    # tenerlo es lo que garantiza la propiedad exclusiva del dato. El patrón es
    # ancho a propósito —la tabla `AVISOS` filtra— para que añadir un aviso no
    # obligue a redesplegar con una suscripción nueva.
    consumidores=[("*", consumir_evento, "identity-notificaciones")],
)
