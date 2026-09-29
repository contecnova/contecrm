"""«Hoy» es el de quien mira, no el del servidor.

**Veinticinco sitios calculaban la fecha en UTC** —`datetime.now(timezone.utc).date()`—
mientras el producto guarda la zona horaria de cada tenant y la usa para
formatear. El resultado: entre medianoche y las dos de la mañana en Madrid, y
durante **trece horas** en Auckland, «hoy» era ayer para el servidor y hoy para
el cliente.

Lo que eso rompe no es cosmético:

- los **días que quedan** de una garantía salen con uno de más;
- un plazo que vence **hoy** se sigue admitiendo como si quedara un día;
- el **presupuesto mensual de IA** cambia de mes a deshora;
- una protección de partner o una cuota trimestral empiezan y acaban el día que
  no es.

Se descubrió por accidente: una tanda de pruebas que cruzó la medianoche empezó a
fallar, y al repetirla a la una de la mañana siguió fallando. A las once de la
noche del mismo día habría pasado en verde, que es lo que llevaba pasando.

**El huso sale del ajuste por tenant que ya existía** —el mismo que usa el
formateo—, así que no hay dato nuevo que mantener ni tabla que consultar: lo
resuelve la misma cadena usuario → unidad → tenant → global que todo lo demás.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from crmcore.logging import get_logger

logger = get_logger(__name__)


def zona_del_tenant(db: Any = None) -> ZoneInfo:
    """La zona horaria efectiva, o UTC si no hay sesión con la que resolverla.

    Sin sesión se devuelve UTC y no se adivina: un valor inventado sería peor que
    el de siempre, porque escondería el problema en vez de dejarlo igual.
    """
    from crmcore.runtime import settings as rt

    nombre = str(rt.efectivo("zona_horaria", db, default="UTC") or "UTC")
    try:
        return ZoneInfo(nombre)
    except Exception:  # noqa: BLE001 — una zona mal escrita no puede tumbar una petición
        logger.warning("fechas.zona_desconocida", zona=nombre)
        return ZoneInfo("UTC")


def hoy(db: Any = None) -> date:
    """El día de hoy **donde está el cliente**.

    Se le pasa la sesión siempre que haya una. Sin ella cae a UTC, que es lo que
    hacía antes: no empeora nada y deja claro dónde falta el dato.
    """
    return datetime.now(zona_del_tenant(db)).date()


def ahora(db: Any = None) -> datetime:
    """El instante actual, con la zona del tenant puesta.

    Sigue siendo un instante absoluto —lleva su desplazamiento—, así que
    compararlo con algo guardado en UTC funciona igual. Lo que cambia es de qué
    día se considera parte, que es justo lo que estaba mal.
    """
    return datetime.now(zona_del_tenant(db))


def ahora_utc() -> datetime:
    """Para lo que de verdad es del servidor: marcas de auditoría, reintentos,
    vencimientos de token. Esos no son «el día de nadie» y tienen que ir en UTC.
    """
    return datetime.now(timezone.utc)
