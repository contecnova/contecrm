"""Punto de entrada del servicio de inteligencia."""

from __future__ import annotations

from crmcore.service import crear_servicio

# Importarlo registra el ejecutor de la medición de salud. Lo necesita la API
# para poder encolarla; el worker lo importa por su cuenta, que es otro proceso.
import services.intelligence.trabajos_salud  # noqa: F401,E402
from services.intelligence.api import ROUTERS
from services.intelligence.api_modelos import ROUTERS_MODELOS

_relevo: object | None = None
_tarea_relevo: object | None = None


def _tareas() -> list[object]:
    """El recálculo periódico de la salud de las cuentas (`CRM-01.01.05`).

    **No existía.** `SALUD_RECALCULO_HORAS` estaba en los ajustes, documentado
    —«por la noche, no en cada apertura de ficha: la salud no cambia en una
    tarde, y recalcularla al abrir pondría una consulta pesada en el camino de
    una pantalla que se abre cien veces al día»— y no lo leía nadie, porque la
    medición solo se disparaba si alguien pulsaba un botón.

    O sea que la lista de cuentas en riesgo enseñaba lo que se midió la última
    vez que alguien se acordó. Una lista así se abre dos veces y se deja de
    mirar, que es exactamente lo que este número venía a evitar.

    Se encola un trabajo por tenant y no se calcula aquí: la medición recorre
    todas sus cuentas y eso es trabajo de fondo con su progreso y su informe
    parcial, no algo que deba correr dentro de una tarea de reloj.
    """
    from crmcore.config import get_settings
    from crmcore.db.session import sesion
    from crmcore.tareas import Tarea, por_tenant

    from services.intelligence.salud import SaludCuenta
    from services.intelligence.trabajos_salud import encolar_medicion

    cada = int(get_settings().salud_recalculo_horas) * 3600

    def _tenants_con_salud() -> list[object]:
        """De SU propia tabla: los tenants que ya tienen salud medida.

        No se pide la lista a `tenancy` —es de otro servicio y no se lee desde
        aquí— y además la lista buena es más corta: un tenant que nunca ha
        medido la salud no la quiere recalculada por su cuenta, la quiere
        cuando la pida.
        """
        from sqlalchemy import select

        with sesion(sistema=True) as db:
            return [t for (t,) in db.execute(select(SaludCuenta.tenant_id).distinct()).all()]

    def _encolar(tenant_id: object) -> dict[str, object]:
        with sesion(sistema=True) as db:
            trabajo = encolar_medicion(db, tenant_id=tenant_id, pedido_por=None)
            return {"trabajo": str(trabajo.id)}

    return [Tarea("intelligence.salud", cada, por_tenant(_tenants_con_salud, _encolar))]


async def _al_arrancar() -> None:
    """Conecta los puertos hacia el modelo, si este despliegue tiene alguno.

    Los tres —generar, responder y extraer— se **registran**, no se importan: así
    el núcleo no sabe de ningún proveedor, y un despliegue sin modelo configurado
    arranca igual y dice que no puede generar, en vez de fallar al abrir la
    primera pantalla.
    """
    import asyncio

    from crmcore.tareas import RelevoDeTareas

    from services.intelligence.puerto import conectar

    conectar()

    global _relevo, _tarea_relevo
    _relevo = RelevoDeTareas(_tareas())
    _tarea_relevo = asyncio.create_task(_relevo.correr(), name="intelligence-tareas")


async def _al_parar() -> None:
    if _relevo is not None:
        _relevo.parar()
    if _tarea_relevo is not None:
        _tarea_relevo.cancel()


app = crear_servicio(
    nombre="intelligence",
    descripcion=(
        "IA generativa sobre los datos del CRM, con las garantías delante: el "
        "modelo se elige por tenant con su región y su opt-out, los permisos se "
        "comprueban antes de recuperar el contexto, lo generado se propone y no "
        "se escribe, lo que responde cita sus fuentes, y cada llamada queda "
        "registrada con su coste y su resultado."
    ),
    routers=[*ROUTERS, *ROUTERS_MODELOS],
    al_arrancar=_al_arrancar,
    al_parar=_al_parar,
)
