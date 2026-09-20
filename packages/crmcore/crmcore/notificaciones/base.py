"""Contrato de un transporte de notificación.

Un transporte sabe entregar por **un** canal y no sabe nada más: ni quién sigue
qué, ni cómo se agrupan los avisos, ni cuándo es de noche para el destinatario.
Todo eso lo decide `crmcore.datos.seguimiento` antes de llamar.

Que la frontera esté justo aquí es lo que permite añadir un canal nuevo sin
tocar nada de la lógica de notificación, y probar la lógica de notificación sin
mandar un solo correo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

from crmcore.logging import get_logger

logger = get_logger(__name__)

# Canales conocidos. `app` no tiene transporte: la bandeja se lee de la tabla, y
# «entregarla» sería escribir en la fila que ya está escrita.
CANALES = ("app", "correo", "sms", "push")


@dataclass(frozen=True)
class Destino:
    """A quién se entrega, ya resuelto.

    La dirección la resuelve quien llama, porque está en las tablas del servicio
    que conoce a las personas. Un transporte que fuera a buscarla necesitaría
    leer el esquema de `identity`, y ningún servicio lee el de otro.
    """

    usuario_id: UUID
    direccion: str
    nombre: str = ""
    idioma: str = "es"


@dataclass(frozen=True)
class Mensaje:
    """Lo que se entrega, ya compuesto y localizado."""

    titulo: str
    cuerpo: str
    tipo: str = ""
    prioridad: str = "normal"
    objeto_tipo: str = ""
    objeto_id: str = ""
    datos: dict[str, Any] = field(default_factory=dict)


@dataclass
class Resultado:
    """Qué pasó al intentar entregar.

    `reintentar` y `entregado` son independientes a propósito: hay fallos que no
    se deben reintentar —un destinatario sin dirección, un número mal formado— y
    tratarlos como reintentables llena la cola de algo que nunca va a salir.
    """

    entregado: bool
    detalle: str = ""
    reintentar: bool = False
    # Identificador que devuelve el proveedor, cuando lo devuelve. Sirve para
    # buscar del lado de ellos cuando alguien pregunta por un envío concreto.
    referencia: str = ""


class Transporte(Protocol):
    """Lo que tiene que saber hacer un canal."""

    canal: str

    def entregar(self, destino: Destino, mensaje: Mensaje, config: dict[str, Any]) -> Resultado:
        """Entrega, o explica por qué no. **Nunca lanza.**

        Que no lance es parte del contrato: el repartidor procesa un lote, y una
        excepción que suba desde un transporte detendría los avisos de todos los
        demás destinatarios del lote por culpa de uno.
        """
        ...


_TRANSPORTES: dict[str, Transporte] = {}


def registrar_transporte(transporte: Transporte) -> Transporte:
    """Declara el transporte de un canal. Idempotente para el mismo objeto."""
    canal = transporte.canal
    if canal not in CANALES:
        raise ValueError(f"Canal desconocido: «{canal}». Conocidos: {CANALES}")
    anterior = _TRANSPORTES.get(canal)
    if anterior is not None and anterior is not transporte:
        raise RuntimeError(f"El canal «{canal}» ya tiene transporte: {type(anterior).__name__}")
    _TRANSPORTES[canal] = transporte
    return transporte


def transporte_de(canal: str) -> Transporte | None:
    return _TRANSPORTES.get(canal)


def transportes_registrados() -> list[str]:
    return sorted(_TRANSPORTES)
