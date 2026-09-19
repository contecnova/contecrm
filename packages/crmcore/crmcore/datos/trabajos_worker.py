"""Worker de trabajos asíncronos, común a todos los servicios (CRM-00.02.01.12).

    python -m services.party.trabajos_worker

No es un servicio: es el bucle, y cada servicio lo arranca sobre su propia base
con sus propios ejecutores registrados. Tiene que ser así porque el ejecutor
escribe en las tablas del servicio dentro de la misma transacción que avanza el
cursor, y un worker central no tendría permisos sobre esos esquemas — ni debería
tenerlos.

Es el mismo bucle que el del motor de procesos (`services/orchestrator/worker.py`)
y con las mismas tres propiedades, que son las que lo hacen operable:

  * **`FOR UPDATE SKIP LOCKED`**, para que N réplicas hagan el trabajo de N.
  * **Bloqueo con caducidad**, para que un worker muerto no retenga un trabajo.
  * **Un commit por tanda**, para que una caída cueste una tanda y no el trabajo.

No se factorizó el bucle con el del orquestador: se parecen, pero lo que avanzan
no tiene la misma forma —una instancia da un paso, un trabajo consume N
elementos— y el molde común habría tenido que parametrizar la toma de lote, el
avance, el cierre y el aviso. Habrían sido cuatro parámetros para ahorrar
cuarenta líneas, con el resultado habitual: nadie entiende ninguno de los dos.
"""

from __future__ import annotations

import signal
import time
from typing import Any

from crmcore.logging import get_logger, setup_logging

logger = get_logger(__name__)

_corriendo = True


def _parar(signum: int, _frame: Any) -> None:
    global _corriendo
    _corriendo = False
    logger.info("trabajos_worker.senal", senal=int(signum))


def _procesar(db: Any, trabajo: Any, tanda_max: int) -> None:
    """Lleva un trabajo hasta donde pueda en esta visita.

    Se queda con él mientras avance: soltarlo tras cada tanda para volver a
    tomarlo obligaría a una consulta con bloqueo por cada doscientos elementos,
    y con varias réplicas el trabajo iría saltando de worker en worker sin que
    eso aporte nada.
    """
    from crmcore.datos.trabajos import avanzar, avisar, soltar
    from crmcore.tenancy.context import con_contexto

    with con_contexto(tenant_id=trabajo.tenant_id, origen="trabajos"):
        while _corriendo and avanzar(db, trabajo, tanda_max=tanda_max):
            pass
        # Apagado a mitad: se suelta para que otro lo retome ya, en vez de
        # esperar a que caduque el bloqueo. Un despliegue no debería costar
        # cinco minutos de parada de algo que se sabía que iba a pasar.
        if _corriendo:
            if trabajo.callback_url:
                avisar(db, trabajo)
        else:
            soltar(db, trabajo)


def run(*, nombre: str = "trabajos") -> None:
    """Bucle principal. Lo llama el módulo `trabajos_worker` de cada servicio."""
    from uuid import uuid4

    setup_logging()
    signal.signal(signal.SIGINT, _parar)
    signal.signal(signal.SIGTERM, _parar)

    from crmcore.config import get_settings
    from crmcore.datos.trabajos import purgar_caducados, tipos_registrados, tomar_lote
    from crmcore.db.session import nueva_sesion

    cfg = get_settings()
    worker_id = f"{nombre}-{uuid4().hex[:8]}"
    tipos = tipos_registrados()
    if not tipos:
        # Arrancar un worker sin ejecutores es un despliegue mal hecho: los
        # trabajos se encolarían y nadie los tocaría, con la ficha diciendo
        # «encolado» para siempre. Se avisa fuerte y se sigue, porque el módulo
        # que los registra puede importarse después en algunos montajes.
        logger.warning("trabajos_worker.sin_ejecutores", worker=worker_id)
    logger.info("trabajos_worker.arranca", worker=worker_id, tipos=tipos)

    ultima_purga = 0.0
    while _corriendo:
        db = nueva_sesion(sistema=True)
        try:
            trabajos = tomar_lote(db, worker_id=worker_id, lote=cfg.trabajo_lote)
            for trabajo in trabajos:
                if not _corriendo:
                    break
                _procesar(db, trabajo, cfg.trabajo_tanda)

            # La purga se mira una vez por hora. Su plazo es de días, así que
            # consultarla en cada vuelta sería una consulta por segundo para
            # borrar nada.
            if time.monotonic() - ultima_purga > 3600:
                ultima_purga = time.monotonic()
                purgar_caducados(db)

            if not trabajos:
                time.sleep(cfg.trabajo_espera_vacio_s)
        except Exception as exc:  # noqa: BLE001 — el worker no puede morirse
            logger.error("trabajos_worker.vuelta_fallida", error=str(exc)[:300])
            try:
                db.rollback()
            except Exception:  # noqa: BLE001 — la sesión ya no sirve; se cierra abajo
                pass
            time.sleep(cfg.trabajo_espera_vacio_s)
        finally:
            db.close()

    logger.info("trabajos_worker.parado", worker=worker_id)
