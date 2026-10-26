"""Worker del motor: despierta instancias vencidas y las hace avanzar.

    python -m services.orchestrator.worker

Es el único sitio donde el tiempo hace avanzar un proceso. Su bucle es
deliberadamente simple: toma un lote de instancias cuyo `despertar_at` ya ha
vencido, las bloquea, las avanza y las suelta.

Tres detalles que hacen que esto funcione con varias réplicas:

  * **`FOR UPDATE SKIP LOCKED`**: cada worker se lleva instancias distintas sin
    esperar a los demás. Sin él, N réplicas dan el rendimiento de una.
  * **Bloqueo con caducidad** (`tomada_hasta`): si un worker muere con
    instancias tomadas, otro las recupera cuando caduca el bloqueo. Sin
    caducidad, esas instancias quedarían bloqueadas para siempre — vivas,
    invisibles y sin avanzar, que es el peor modo de fallo posible.
  * **Un commit por instancia**: un fallo al avanzar una no arrastra a las demás
    del lote.

Escala horizontal: arranca varios procesos. Apagado limpio: SIGTERM termina la
instancia en curso y sale, sin dejar un proceso a medio paso.
"""

from __future__ import annotations

import signal
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from crmcore.logging import get_logger, setup_logging
from sqlalchemy import or_, select

from services.orchestrator.modelos import InstanciaProceso, TareaHumana
from services.orchestrator.motor import Motor

logger = get_logger(__name__)


# Cuánto se queda un worker una instancia antes de que otro pueda recuperarla.
# Debe superar con holgura lo que tarda el paso más lento; si se queda corto,
# dos workers avanzan la misma instancia a la vez.
def _worker_bloqueo_min() -> int:
    """Antes `_worker_bloqueo_min() = 5`.

    Era una constante de módulo. Sale del `.env`, que es donde una instalación
    puede afinarla sin tocar código.
    """
    from crmcore.config import get_settings

    return get_settings().worker_bloqueo_min


# Instancias por vuelta. Lotes grandes amortizan el viaje a la base; lotes
# pequeños reparten mejor entre réplicas.
def _worker_lote() -> int:
    """Antes `_worker_lote() = 20`.

    Era una constante de módulo. Sale del `.env`, que es donde una instalación
    puede afinarla sin tocar código.
    """
    from crmcore.config import get_settings

    return get_settings().worker_lote


# Espera cuando no hay nada vencido. Es la latencia máxima de un temporizador,
# así que no conviene subirla mucho.
ESPERA_VACIO_S = 2.0

_corriendo = True


def _parar(signum: int, _frame: Any) -> None:
    global _corriendo
    _corriendo = False
    logger.info("worker.senal", senal=int(signum))


def _tomar_lote(db: Any, worker_id: str) -> list[InstanciaProceso]:
    """Toma instancias vencidas y las bloquea para este worker."""
    ahora = datetime.now(timezone.utc)
    instancias = (
        db.execute(
            select(InstanciaProceso)
            .where(
                InstanciaProceso.estado.in_(("ejecutando", "esperando")),
                InstanciaProceso.despertar_at.is_not(None),
                InstanciaProceso.despertar_at <= ahora,
                # O no la tiene nadie, o quien la tenía dejó caducar el bloqueo.
                or_(
                    InstanciaProceso.tomada_hasta.is_(None),
                    InstanciaProceso.tomada_hasta < ahora,
                ),
            )
            .order_by(InstanciaProceso.despertar_at)
            .limit(_worker_lote())
            .with_for_update(skip_locked=True)
        )
        .scalars()
        .all()
    )
    for instancia in instancias:
        instancia.tomada_por = worker_id
        instancia.tomada_hasta = ahora + timedelta(minutes=_worker_bloqueo_min())
    db.commit()
    return list(instancias)


def _avanzar_una(
    instancia_id: Any, tenant_id: Any, tomada_por: str, invocadores: dict[str, Any]
) -> None:
    """Avanza una instancia en una sesión **de su tenant**. Nunca propaga.

    El lote se toma con una sesión de sistema, porque hay que mirar las
    instancias de todos los tenants para saber cuáles han vencido. Avanzarlas en
    esa misma sesión dejaría al motor sin la red del guard del ORM, que se
    aparta ante una sesión de sistema. Hoy ningún paso lee un identificador que
    venga de fuera, así que no hay fuga demostrable — pero el día que un
    invocador la lea, la red tiene que estar puesta, no pendiente de que alguien
    se acuerde. Es la misma corrección que en el worker de trabajos, donde sí
    había fuga.
    """
    from crmcore.db.session import nueva_sesion

    db = nueva_sesion(tenant_id)
    try:
        _avanzar_en(db, instancia_id, tomada_por, invocadores)
    finally:
        db.close()


def _avanzar_en(db: Any, instancia_id: Any, tomada_por: str, invocadores: dict[str, Any]) -> None:
    instancia = db.get(InstanciaProceso, instancia_id)
    if instancia is None:
        # La instancia se ha ido entre la toma y ahora (una baja de tenant, una
        # purga). No es un error del worker.
        logger.info("worker.instancia_ausente", instancia=str(instancia_id))
        return

    from crmcore.tenancy.context import con_contexto

    try:
        with con_contexto(tenant_id=instancia.tenant_id, origen="orquestador"):
            motor = Motor(db, invocadores=invocadores, worker_id=tomada_por)
            motor.avanzar(instancia)
        instancia.tomada_por = None
        instancia.tomada_hasta = None
        # Si sigue ejecutando y no ha programado un despertar, que la recoja la
        # vuelta siguiente: dejar `despertar_at` en el pasado es lo que hace que
        # un proceso largo avance en turnos en vez de monopolizar el worker.
        if instancia.estado == "ejecutando" and instancia.despertar_at is None:
            instancia.despertar_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as exc:  # noqa: BLE001 — una instancia rota no tumba el worker
        db.rollback()
        logger.error(
            "worker.instancia_fallida",
            instancia=str(instancia.id),
            error=str(exc)[:300],
        )
        # Se libera el bloqueo igualmente: si no, la instancia queda retenida
        # hasta que caduque, y con ella el proceso de un cliente.
        try:
            instancia.tomada_por = None
            instancia.tomada_hasta = None
            instancia.estado = "fallida"
            instancia.error = str(exc)[:1000]
            db.commit()
        except Exception:  # noqa: BLE001 — la base no responde; lo hará otro worker
            db.rollback()


def _vencer_tareas(db: Any) -> int:
    """Escala o caduca las tareas humanas que han pasado su plazo.

    Sin esto, una tarea que nadie mira detiene el proceso indefinidamente y en
    silencio — que es la forma habitual en que un flujo con aprobaciones acaba
    con cien expedientes parados sin que nadie lo sepa.
    """
    ahora = datetime.now(timezone.utc)
    vencidas = (
        db.execute(
            select(TareaHumana)
            .where(
                TareaHumana.estado == "pendiente",
                TareaHumana.vence_at.is_not(None),
                TareaHumana.vence_at < ahora,
            )
            .limit(_worker_lote())
        )
        .scalars()
        .all()
    )
    for tarea in vencidas:
        tarea.estado = "escalada" if tarea.asignada_rol else "caducada"
        logger.warning(
            "tarea.vencida",
            tarea=str(tarea.id),
            paso=tarea.paso,
            estado=tarea.estado,
        )
    if vencidas:
        db.commit()
    return len(vencidas)


def construir_invocadores() -> dict[str, Any]:
    """Operaciones que los procesos pueden invocar.

    De momento vacío: los servicios de negocio llegan en la fase 1, y un
    invocador que no existe se detecta al **publicar** la definición, no al
    ejecutarla. Registrar aquí operaciones falsas para «que no falle» sería
    peor: los procesos parecerían funcionar y no harían nada.
    """
    return {}


def run() -> None:
    setup_logging()
    signal.signal(signal.SIGINT, _parar)
    signal.signal(signal.SIGTERM, _parar)

    from crmcore.db.session import nueva_sesion

    worker_id = f"orq-{uuid4().hex[:8]}"
    invocadores = construir_invocadores()
    logger.info("worker.arranca", worker=worker_id, invocadores=len(invocadores))

    ultima_revision_tareas = 0.0
    while _corriendo:
        db = nueva_sesion(sistema=True)
        try:
            instancias = _tomar_lote(db, worker_id)
            # id, tenant y quién la tomó, ANTES de dejar la sesión de sistema:
            # la instancia se vuelve a leer dentro de la suya.
            pendientes = [(i.id, i.tenant_id, str(i.tomada_por)) for i in instancias]
            for instancia_id, tenant_id, tomada_por in pendientes:
                if not _corriendo:
                    break
                _avanzar_una(instancia_id, tenant_id, tomada_por, invocadores)

            # Las tareas vencidas se revisan una vez por minuto, no en cada
            # vuelta: su plazo es de horas, y consultarlas cada dos segundos
            # sería una consulta por segundo para nada.
            if time.monotonic() - ultima_revision_tareas > 60:
                ultima_revision_tareas = time.monotonic()
                _vencer_tareas(db)

            if not instancias:
                time.sleep(ESPERA_VACIO_S)
        except Exception as exc:  # noqa: BLE001 — el worker no puede morirse
            logger.error("worker.vuelta_fallida", error=str(exc)[:300])
            time.sleep(ESPERA_VACIO_S)
        finally:
            db.close()

    logger.info("worker.parado", worker=worker_id)


if __name__ == "__main__":
    run()
