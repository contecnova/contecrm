"""Worker del repartidor de notificaciones (CRM-06.02.01.02).

    python -m services.identity.reparto_worker

Un proceso aparte del que atiende la API, y no una tarea en segundo plano de
ella, por lo mismo que los trabajos asíncronos: una tarea en segundo plano muere
con el proceso, y un despliegue a mitad de un lote perdería esos avisos sin que
nadie lo supiera.
"""

from __future__ import annotations

import signal
import time
from typing import Any

from crmcore.logging import get_logger, setup_logging

import services.identity.transportes  # noqa: F401 — registra los transportes

logger = get_logger(__name__)

_corriendo = True


def _parar(signum: int, _frame: Any) -> None:
    global _corriendo
    _corriendo = False
    logger.info("reparto.senal", senal=int(signum))


def run() -> None:
    from uuid import uuid4

    setup_logging()
    signal.signal(signal.SIGINT, _parar)
    signal.signal(signal.SIGTERM, _parar)

    from crmcore.config import get_settings
    from crmcore.db.session import nueva_sesion
    from crmcore.notificaciones import transportes_registrados

    from services.identity.reparto import repartir_lote

    cfg = get_settings()
    worker = f"reparto-{uuid4().hex[:8]}"
    canales = transportes_registrados()
    if not cfg.smtp_host:
        # Se avisa fuerte y se arranca igual: los avisos se quedan en la cola
        # con su motivo y salen en cuanto alguien configure el servidor, que es
        # mejor que descartarlos o que negarse a arrancar.
        logger.warning("reparto.sin_smtp", worker=worker)
    logger.info("reparto.arranca", worker=worker, canales=canales)

    while _corriendo:
        db = nueva_sesion(sistema=True)
        try:
            cuenta = repartir_lote(db, limite=cfg.notificacion_lote)
            if cuenta["nuevas"] or cuenta["reintentos"]:
                logger.info("reparto.vuelta", **cuenta)
            else:
                time.sleep(cfg.notificacion_espera_vacio_s)
        except Exception as exc:  # noqa: BLE001 — el worker no puede morirse
            logger.error("reparto.vuelta_fallida", error=str(exc)[:300])
            try:
                db.rollback()
            except Exception:  # noqa: BLE001 — la sesión ya no sirve
                pass
            time.sleep(cfg.notificacion_espera_vacio_s)
        finally:
            db.close()

    logger.info("reparto.parado", worker=worker)


if __name__ == "__main__":
    run()
