"""Punto de entrada del servicio de inteligencia."""

from __future__ import annotations

from crmcore.service import crear_servicio

from services.intelligence import eventos  # noqa: F401  (registra los tipos de evento)
from services.intelligence.api import ROUTERS


def _al_arrancar() -> None:
    """Conecta los puertos hacia el modelo, si este despliegue tiene alguno.

    Los tres —generar, responder y extraer— se **registran**, no se importan: así
    el núcleo no sabe de ningún proveedor, y un despliegue sin modelo configurado
    arranca igual y dice que no puede generar, en vez de fallar al abrir la
    primera pantalla.
    """
    from services.intelligence.puerto import conectar

    conectar()


app = crear_servicio(
    nombre="intelligence",
    descripcion=(
        "IA generativa sobre los datos del CRM, con las garantías delante: el "
        "modelo se elige por tenant con su región y su opt-out, los permisos se "
        "comprueban antes de recuperar el contexto, lo generado se propone y no "
        "se escribe, lo que responde cita sus fuentes, y cada llamada queda "
        "registrada con su coste y su resultado."
    ),
    routers=ROUTERS,
    al_arrancar=_al_arrancar,
)
