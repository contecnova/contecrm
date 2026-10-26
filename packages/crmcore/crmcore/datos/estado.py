"""Página de estado privada del tenant (CRM-00.06.01.06).

El cliente no puede depender de que le llamemos para saber si su CRM va bien.
Cuando algo va lento, la primera pregunta es «¿somos nosotros o sois vosotros?»,
y sin una respuesta el cliente abre un ticket, espera y desconfía.

Esto contesta esa pregunta **con sus datos, no con los de la plataforma**:

  * Qué componentes hay y si responden ahora mismo.
  * Su consumo frente a sus límites, que es la causa más frecuente de lentitud
    percibida sin que nada esté averiado.
  * Qué tiene en cola: eventos sin publicar, trabajos sin terminar, entregas de
    webhook fallando.

Tres decisiones que la hacen honesta:

**Se consulta en vivo, no se cachea.** El valor de una página de estado es decir
la verdad en el momento en que se pregunta. Una cacheada cinco minutos enseña
«todo bien» mientras el cliente mira una pantalla que no carga, y eso destruye
más confianza que no tener página.

**Degradado no es caído, y se distinguen.** Un componente lento o una cola que
crece es `degradado`; uno que no responde es `caido`. Meterlo todo en «con
incidencias» obliga al cliente a llamar igual para saber cuál de las dos cosas
le está pasando.

**Solo lo suyo.** No dice cuántos tenants hay, ni cómo van los demás, ni qué
versión corre cada réplica. Una página de estado que filtra la forma de la
plataforma es un mapa para quien quiera atacarla.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from crmcore.logging import get_logger

logger = get_logger(__name__)

# Un componente devuelve su ficha, o `None` si este tenant no lo usa: una lista
# con cosas que no le importan hace que deje de mirarla.
Componente = Callable[[Session, UUID], "dict[str, Any] | None"]

# Estados posibles de un componente y del conjunto. En este orden de gravedad:
# el estado global es el peor de sus componentes.
ESTADOS = ("operativo", "degradado", "caido")

# A partir de cuántos eventos sin publicar se considera que la cola va con
# retraso. No es un umbral de alarma —de eso se encarga Prometheus— sino el
# punto en que el cliente ya lo nota, porque sus integraciones van detrás.
COLA_DEGRADADA = 100


# Y el punto en el que ya no es un retraso, es que el relevo no está corriendo.
def _cola_caida_desde() -> int:
    """Tope del núcleo, antes `_cola_caida_desde() = 5_000`.

    Era una constante de módulo. Sale del `.env`, no de los ajustes en
    caliente: es un tope operativo del despliegue y «por cliente» no
    significaría nada.
    """
    from crmcore.config import get_settings

    return get_settings().cola_caida_desde


# Minutos sin publicar nada con cola pendiente: eso ya no es carga, es que nadie
# la está vaciando.
def _relevo_parado_min() -> int:
    """Tope del núcleo, antes `_relevo_parado_min() = 15`.

    Era una constante de módulo. Sale del `.env`, no de los ajustes en
    caliente: es un tope operativo del despliegue y «por cliente» no
    significaría nada.
    """
    from crmcore.config import get_settings

    return get_settings().relevo_parado_min


def _peor(estados: list[str]) -> str:
    for nivel in reversed(ESTADOS):
        if nivel in estados:
            return nivel
    return "operativo"


def _cola_saliente(db: Session, tenant_id: UUID) -> dict[str, Any]:
    """Eventos de este tenant esperando a salir.

    Es el componente que más veces explica un «no me ha llegado nada a mi
    sistema» sin que nada esté roto: la cola va con retraso.
    """
    from crmcore.bus.modelos import EventoSaliente

    pendientes = db.execute(
        select(func.count())
        .select_from(EventoSaliente)
        .where(EventoSaliente.tenant_id == tenant_id, EventoSaliente.publicado_at.is_(None))
    ).scalar_one()

    ultimo = db.execute(
        select(func.max(EventoSaliente.publicado_at)).where(EventoSaliente.tenant_id == tenant_id)
    ).scalar()

    estado = "operativo"
    detalle = "Al día"
    if pendientes >= _cola_caida_desde():
        estado, detalle = "caido", f"{pendientes} eventos sin publicar"
    elif pendientes >= COLA_DEGRADADA:
        estado, detalle = "degradado", f"{pendientes} eventos esperando"
    elif pendientes and ultimo is not None:
        # Poca cola pero parada: peor señal que mucha cola moviéndose.
        if _aware(ultimo) < datetime.now(timezone.utc) - timedelta(minutes=_relevo_parado_min()):
            estado, detalle = (
                "degradado",
                f"{pendientes} eventos sin publicar desde hace más de {_relevo_parado_min()} min",
            )
    return {
        "componente": "eventos_salientes",
        "estado": estado,
        "detalle": detalle,
        "pendientes": pendientes,
        "ultimo_publicado": ultimo.isoformat() if ultimo else None,
    }


def _cifrado(db: Session, tenant_id: UUID) -> dict[str, Any] | None:
    """Si el tenant revocó su clave, su CRM no está «operativo» y hay que decirlo.

    Es la única forma de que quien vea errores de descifrado entienda que no es
    una avería sino una decisión suya, sin abrir un ticket.
    """
    from crmcore.config import get_settings
    from crmcore.security import byok

    if not get_settings().byok_enabled:
        return None
    if byok.esta_revocada(db, tenant_id):
        return {
            "componente": "cifrado",
            "estado": "caido",
            "detalle": (
                "La clave propia de este tenant está revocada: los datos "
                "cifrados con ella no se pueden leer. Es irreversible"
            ),
        }
    if byok.activa(db, tenant_id) is not None:
        return {"componente": "cifrado", "estado": "operativo", "detalle": "Clave propia activa"}
    return None


def _base_de_datos(db: Session) -> dict[str, Any]:
    from sqlalchemy import text

    try:
        db.execute(text("SELECT 1"))
        return {"componente": "base_de_datos", "estado": "operativo", "detalle": "Responde"}
    except Exception as exc:  # noqa: BLE001 — informar, no lanzar: la página tiene que salir
        return {
            "componente": "base_de_datos",
            "estado": "caido",
            # Sin el detalle técnico: el mensaje de un error de conexión lleva
            # host, puerto y a veces usuario, y esta página la ve el cliente.
            "detalle": "No responde",
            "error": type(exc).__name__,
        }


# Componentes que aporta cada servicio, además de los comunes. Es un registro y
# no una lista fija porque **un servicio no puede leer las tablas de otro**: el
# estado de los webhooks lo sabe `eventing`, el de las cuotas lo sabe `tenancy`,
# y ninguno de los dos puede consultarlo por el otro. Lo cazó el gate de
# arquitectura, con razón, cuando esta página los consultaba a los dos.
#
# Cada servicio registra el suyo al importarse, y el gateway junta las páginas.
_COMPONENTES: list[Componente] = []


def registrar_componente(fn: Componente) -> Componente:
    """Añade un componente propio del servicio a su página de estado.

    Devuelve la función para poder usarse como decorador. Registrar dos veces la
    misma es inocuo: en un proceso que importe varios módulos de servicio —las
    pruebas— pasaría, y fallar ahí no protegería de nada.
    """
    if fn not in _COMPONENTES:
        _COMPONENTES.append(fn)
    return fn


def componentes_registrados() -> list[str]:
    return [fn.__name__ for fn in _COMPONENTES]


def calcular(db: Session, tenant_id: UUID) -> dict[str, Any]:
    """La página de estado de este tenant **en este servicio**, calculada ahora."""
    componentes = [_base_de_datos(db), _cola_saliente(db, tenant_id)]
    for extra in (_cifrado(db, tenant_id), *(fn(db, tenant_id) for fn in _COMPONENTES)):
        if extra is not None:
            componentes.append(extra)

    global_ = _peor([c["estado"] for c in componentes])
    if global_ != "operativo":
        logger.info(
            "estado_tenant.no_operativo",
            estado=global_,
            componentes=[c["componente"] for c in componentes if c["estado"] != "operativo"],
        )
    return {
        "estado": global_,
        "consultado_at": datetime.now(timezone.utc).isoformat(),
        "componentes": componentes,
        # Se dice explícitamente que no está cacheado. Una página de estado
        # cacheada enseña «todo bien» mientras el cliente mira una pantalla que
        # no carga, y eso destruye más confianza que no tener página.
        "cacheado": False,
    }


def _aware(momento: datetime) -> datetime:
    return momento if momento.tzinfo else momento.replace(tzinfo=timezone.utc)
