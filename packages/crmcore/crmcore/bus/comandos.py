"""Órdenes entre servicios: lo que un servicio pide a otro que haga.

Un evento dice **lo que ha pasado** y no espera nada; un comando pide **que pase
algo**. Se separan porque se comportan distinto: un evento lo consume quien
quiera y perderlo degrada una función secundaria; un comando tiene un
destinatario único y perderlo significa que el trabajo no se hizo.

Hacen falta porque una automatización tiene que poder crear una tarea o asignar
un lead, y el servicio de automatizaciones **no puede escribir en el esquema de
ventas** — los permisos de base de datos se lo impiden, y eso es lo que mantiene
la propiedad exclusiva del dato. Así que pide, y el dueño ejecuta.

**Un comando no es una llamada con otro nombre.** Va por el bus, con su entrega
al menos una vez y su deduplicación, y quien lo emite no espera respuesta. Una
automatización que esperara el resultado de tres acciones encadenadas dejaría la
petición del usuario abierta mientras tanto — y el usuario está esperando a que
se guarde su cuenta, no a que terminen las reglas.

**Y lo que un comando puede tocar está acotado por el servicio dueño**, no por
quien lo manda. Sin esa lista blanca, una automatización podría fijar el
`owner_id` de cualquier registro, o su estado, saltándose las reglas que el
servicio aplica a todo el mundo: sería una vía de escalada de privilegios
disfrazada de configuración.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable
from uuid import UUID

from sqlalchemy.orm import Session

from crmcore.errors import ErrorValidacion
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Prefijo de los asuntos de comando en el bus. Separado del de eventos para que
# una suscripción amplia a eventos no acabe consumiendo órdenes por accidente.
PREFIJO = "comando"


@dataclass(frozen=True, slots=True)
class Comando:
    """Una orden dirigida al servicio dueño de un objeto."""

    accion: str
    objeto: str
    tenant_id: UUID
    registro_id: UUID | None = None
    datos: dict[str, Any] = field(default_factory=dict)
    # De dónde viene. No es decorativo: es lo que permite que el registro de
    # auditoría distinga «lo cambió una persona» de «lo cambió la regla X», y
    # esa distinción es la primera que se pregunta cuando un dato aparece
    # modificado y nadie se reconoce.
    origen: str = "automatizacion"
    origen_id: str | None = None

    @property
    def asunto(self) -> str:
        return f"{PREFIJO}.{self.objeto}.{self.accion}"

    def a_data(self) -> dict[str, Any]:
        return {
            "accion": self.accion,
            "objeto": self.objeto,
            "registro_id": str(self.registro_id) if self.registro_id else None,
            "datos": self.datos,
            "origen": self.origen,
            "origen_id": self.origen_id,
        }


@dataclass(frozen=True, slots=True)
class Manejador:
    """Quién ejecuta un comando y qué campos deja tocar.

    `campos_permitidos` lo declara el **servicio dueño**, no quien manda el
    comando. Es la lista blanca que impide que una automatización escriba en
    `owner_id`, en `estado` o en cualquier columna que el servicio gobierna con
    sus propias reglas.
    """

    objeto: str
    accion: str
    ejecutar: Callable[..., Any]
    campos_permitidos: frozenset[str] = field(default_factory=frozenset)


MANEJADORES: dict[str, Manejador] = {}


def registrar_manejador(manejador: Manejador) -> Manejador:
    """Declara quién atiende un comando. Lo hace el servicio dueño del objeto."""
    MANEJADORES[f"{manejador.objeto}.{manejador.accion}"] = manejador
    return manejador


def emitir(uow: Any, comando: Comando) -> None:
    """Encola el comando en la transacción en curso.

    Va por la tabla de salida, como los eventos: si la transacción se deshace,
    la orden no sale. Lo contrario —mandarla al bus directamente— daría el caso
    en que la automatización pide crear una tarea por un registro que al final
    no se guardó.
    """
    uow.emitir(
        comando.asunto,
        subject=(comando.objeto, comando.registro_id or comando.tenant_id),
        data=comando.a_data(),
        # La deduplicación va por el HECHO, no por el envío: la misma regla
        # sobre el mismo registro es la misma orden, y recibirla dos veces no
        # debe crear dos tareas.
        dedup_key=(
            f"{comando.asunto}:{comando.origen_id}:{comando.registro_id}"
            if comando.origen_id
            else None
        ),
    )


def filtrar_campos(objeto: str, accion: str, datos: dict[str, Any]) -> dict[str, Any]:
    """Deja solo los campos que el servicio dueño admite para esa acción.

    Los descartados se registran con nombre. Ignorarlos en silencio haría que
    una automatización mal configurada «funcionara» sin hacer lo que su autor
    cree, y eso se descubre semanas después comparando lo que debería haber
    pasado con lo que pasó.
    """
    manejador = MANEJADORES.get(f"{objeto}.{accion}")
    if manejador is None:
        raise ErrorValidacion(
            f"Nadie atiende «{accion}» sobre «{objeto}»",
            error_code="comandos.sin_manejador",
            detalle={"admitidos": sorted(MANEJADORES)},
        )
    permitidos = {k: v for k, v in datos.items() if k in manejador.campos_permitidos}
    descartados = sorted(set(datos) - set(permitidos))
    if descartados:
        logger.warning(
            "comandos.campos_descartados",
            objeto=objeto,
            accion=accion,
            campos=descartados,
            motivo="el servicio dueño no admite escribirlos por comando",
        )
    return permitidos


async def despachar(db: Session, mensaje: Any) -> bool:
    """Ejecuta un comando recibido del bus. Devuelve si lo atendió.

    Devuelve `False` en vez de fallar cuando el comando no es para este
    servicio: todos los servicios escuchan el mismo bus, y tratar «no es mío»
    como un error llenaría la cola de fallidos con mensajes correctos.
    """
    tipo = getattr(mensaje, "tipo", None) or mensaje.get("tipo", "")
    if not str(tipo).startswith(f"{PREFIJO}."):
        return False

    datos = getattr(mensaje, "data", None) or mensaje.get("data") or {}
    objeto = str(datos.get("objeto", ""))
    accion = str(datos.get("accion", ""))
    manejador = MANEJADORES.get(f"{objeto}.{accion}")
    if manejador is None:
        return False

    manejador.ejecutar(
        db,
        registro_id=datos.get("registro_id"),
        datos=filtrar_campos(objeto, accion, datos.get("datos") or {}),
        origen=str(datos.get("origen") or "desconocido"),
        origen_id=datos.get("origen_id"),
    )
    logger.info("comandos.ejecutado", objeto=objeto, accion=accion, origen=datos.get("origen"))
    return True
