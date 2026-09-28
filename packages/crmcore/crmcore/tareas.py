"""El ejecutor de tareas periódicas que no existía.

contecrm tenía workers de cola —que consumen lo que se les encola— y **nada que
hiciera «cada N minutos, barre esto»**. El 28-09-2026 se encontraron seis
funciones escritas, probadas y esperando a que alguien las llamara:

    correr_programadas       informes programados
    barrer_recordatorios     recordatorios vencidos      ← el peor
    barrer_reverificaciones  re-verificación de datos
    purgar_estados           estados SSO caducados
    purgar_aserciones        aserciones SAML caducadas
    purgar_desafios          desafíos MFA caducados

El peor era `barrer_recordatorios`: un comercial pone un recordatorio, lo ve
guardado con su fecha, **y no le llega nunca**. Sin error: no hay nada que
buscar. Y `purgar_estados` lo decía en su propia documentación —«La ejecuta una
tarea periódica»— cuando no había ninguna.

**No faltaban seis cosas: faltaba una.** Seis arreglos habrían sido seis sitios
donde volver a olvidarse; un ejecutor y las seis colgadas de él es una sola cosa
que vigilar.

**Tres reglas, y las tres nacen de averías reales:**

**Se aísla por tenant y se sigue.** Un fallo en el tenant 40 no puede parar a los
200 siguientes. Es lo que ya hace el relevo del outbox, así que no es un criterio
nuevo.

**El que falla deja su identificador y su motivo, no un contador.** «3 fallaron»
no sirve para arreglar nada.

**Y late aunque no haya nada que hacer.** Si sólo latiera al trabajar, una tarea
parada y una sin trabajo se verían igual — que es exactamente el tipo de avería
silenciosa que este módulo existe para no repetir.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from crmcore.logging import get_logger

logger = get_logger(__name__)

# Fallos seguidos de una misma tarea tras los que deja de ser «un fallo» y pasa a
# ser una avería que hay que ver en el monitor de salud. Tres porque dos pueden
# ser la base reiniciándose y cuatro ya es media hora de cosas sin barrer.
FALLOS_PARA_AVERIA = 3


@dataclass(slots=True)
class Tarea:
    """Algo que hay que hacer cada tanto.

    `funcion` no recibe nada y se apaña sola con su sesión: quien la escribe sabe
    si necesita una de sistema, una unidad de trabajo o recorrer tenants, y
    meterle eso aquí obligaría a este módulo a saber de esquemas ajenos.

    Devuelve un diccionario con lo que hizo. Se registra tal cual, porque
    «barrió 0» y «barrió 400» son la misma línea de log con distinto número y la
    diferencia es lo único que se mira.
    """

    nombre: str
    intervalo_s: float
    funcion: Callable[[], dict[str, Any]]


@dataclass(slots=True)
class EstadoTarea:
    ultimo_intento: float = 0.0
    ultimo_exito: float = 0.0
    fallos_seguidos: int = 0
    ultimo_error: str = ""
    vueltas: int = 0


# Lo que las tareas van dejando, para que el monitor de salud pueda leerlo. En
# memoria del proceso a propósito: es el estado de ESTE proceso, y guardarlo en
# la base lo convertiría en otra cosa que mantener y que se queda vieja.
_estado: dict[str, EstadoTarea] = {}


def estado_de_las_tareas() -> dict[str, dict[str, Any]]:
    """Lo que ha pasado con cada tarea, para el monitor de salud.

    **Con el motivo dentro.** Una tarea que falla siempre en el mismo sitio y
    sigue saliendo en verde es una avería silenciosa, y llevamos demasiadas hoy.
    """
    ahora = time.monotonic()
    return {
        nombre: {
            "vueltas": e.vueltas,
            "fallos_seguidos": e.fallos_seguidos,
            "ultimo_error": e.ultimo_error,
            "hace_s": round(ahora - e.ultimo_intento, 1) if e.ultimo_intento else None,
            "desde_el_ultimo_exito_s": (
                round(ahora - e.ultimo_exito, 1) if e.ultimo_exito else None
            ),
            "averiada": e.fallos_seguidos >= FALLOS_PARA_AVERIA,
        }
        for nombre, e in _estado.items()
    }


def limpiar_estado() -> None:
    """Para las pruebas: el estado es del proceso y vive entre casos."""
    _estado.clear()


@dataclass(slots=True)
class RelevoDeTareas:
    """Ejecuta las tareas de este servicio, cada una a su ritmo."""

    tareas: list[Tarea]
    _parar: asyncio.Event = field(default_factory=asyncio.Event)

    def parar(self) -> None:
        self._parar.set()

    async def correr(self) -> None:
        if not self.tareas:
            return
        # El componente de salud se engancha aquí y no al importar: un servicio
        # sin tareas no tiene por qué enseñar el apartado.
        registrar_componente_de_salud()
        logger.info(
            "tareas.relevo_arranca",
            tareas=[t.nombre for t in self.tareas],
        )
        while not self._parar.is_set():
            await self.una_vuelta()
            try:
                # Se despierta a menudo y cada tarea decide si le toca: un solo
                # bucle para todas, en vez de una tarea de asyncio por cada una.
                await asyncio.wait_for(self._parar.wait(), timeout=1.0)
            except TimeoutError:
                continue

    async def una_vuelta(self) -> None:
        ahora = time.monotonic()
        for tarea in self.tareas:
            estado = _estado.setdefault(tarea.nombre, EstadoTarea())
            if estado.ultimo_intento and ahora - estado.ultimo_intento < tarea.intervalo_s:
                continue
            await self._ejecutar(tarea, estado)

    async def _ejecutar(self, tarea: Tarea, estado: EstadoTarea) -> None:
        estado.ultimo_intento = time.monotonic()
        estado.vueltas += 1
        try:
            # En un hilo: las tareas son de base de datos y son síncronas, y
            # ejecutarlas en el bucle de eventos bloquearía todo el servicio
            # mientras barren.
            resultado = await asyncio.to_thread(tarea.funcion)
        except Exception as exc:  # noqa: BLE001 — el relevo no se muere nunca
            estado.fallos_seguidos += 1
            estado.ultimo_error = f"{type(exc).__name__}: {str(exc)[:300]}"
            registro = (
                logger.error if estado.fallos_seguidos >= FALLOS_PARA_AVERIA else logger.warning
            )
            registro(
                "tareas.fallo",
                tarea=tarea.nombre,
                seguidos=estado.fallos_seguidos,
                error=estado.ultimo_error,
            )
            return

        estado.fallos_seguidos = 0
        estado.ultimo_error = ""
        estado.ultimo_exito = time.monotonic()
        # LATE AUNQUE NO HAYA HECHO NADA. Si sólo se registrara al trabajar, una
        # tarea parada y una sin trabajo se verían igual desde fuera.
        logger.info("tareas.vuelta", tarea=tarea.nombre, **(resultado or {}))


def por_tenant(
    tenants: Callable[[], list[Any]],
    trabajo: Callable[[Any], dict[str, Any]],
) -> Callable[[], dict[str, Any]]:
    """Envuelve un trabajo por tenant aislando cada uno.

    **Un fallo en el tenant 40 no puede parar a los 200 siguientes**, y el que
    falla deja su identificador y su motivo — no un contador, que no sirve para
    arreglar nada.

    Los tenants los da quien la usa, y los saca de **su propia tabla**: los que
    tienen algo que barrer. Así no hace falta la lista de tenants, que es de
    otro servicio y no se puede leer desde aquí.
    """

    def _correr() -> dict[str, Any]:
        hechos, fallidos = 0, []
        for tenant_id in tenants():
            try:
                trabajo(tenant_id)
                hechos += 1
            except Exception as exc:  # noqa: BLE001 — aislar y seguir
                fallidos.append(
                    {"tenant": str(tenant_id), "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
                )
        if fallidos:
            logger.error("tareas.tenants_fallidos", cuantos=len(fallidos), detalle=fallidos)
        return {"tenants": hechos, "fallidos": len(fallidos)}

    return _correr


def _componente_tareas(db: Any, tenant_id: Any) -> dict[str, Any] | None:
    """Las tareas periódicas, en la página de estado.

    **Lo que se enseña es la avería, no la estadística.** Una tarea que falla
    siempre en el mismo sitio y sigue saliendo en verde es exactamente el tipo de
    cosa que este módulo existe para no repetir, así que en cuanto una acumula
    fallos seguidos se dice, **con su motivo dentro**.

    Es del proceso y no del tenant —un barrido no es de nadie—, así que sale
    igual para todos. Se devuelve `None` cuando este servicio no tiene tareas:
    un componente vacío en la página de un servicio que no barre nada solo hace
    que se deje de mirar.
    """
    estado = estado_de_las_tareas()
    if not estado:
        return None

    averiadas = {n: e for n, e in estado.items() if e["averiada"]}
    # Una tarea que nunca ha llegado a completarse no está «bien»: está sin
    # estrenar, y eso importa el día del despliegue.
    sin_estrenar = [n for n, e in estado.items() if e["desde_el_ultimo_exito_s"] is None]

    if averiadas:
        return {
            "estado": "caido",
            "detalle": "; ".join(
                f"«{n}» lleva {e['fallos_seguidos']} fallos seguidos: {e['ultimo_error']}"
                for n, e in averiadas.items()
            ),
            "tareas": estado,
        }
    if sin_estrenar:
        return {
            "estado": "degradado",
            "detalle": f"sin completar todavía: {', '.join(sorted(sin_estrenar))}",
            "tareas": estado,
        }
    return {"estado": "ok", "detalle": f"{len(estado)} tarea(s) al día", "tareas": estado}


def registrar_componente_de_salud() -> None:
    """Engancha el componente. Lo llama el relevo al arrancar, no el import:
    registrarlo al importar lo pondría en servicios que no tienen tareas."""
    from crmcore.datos.estado import registrar_componente

    _componente_tareas.__name__ = "tareas_periodicas"
    registrar_componente(_componente_tareas)
