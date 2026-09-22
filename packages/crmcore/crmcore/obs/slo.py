"""Objetivos de servicio y presupuesto de error (CRM-00.06.01.04).

Un SLA le dice al cliente qué se le promete. Un **SLO** le dice al equipo cuándo
parar de añadir cosas y arreglar las que hay. Sin él, la conversación «¿podemos
desplegar el viernes?» se decide por intuición y por quién habla más alto.

La pieza que lo hace útil es el **presupuesto de error**: si el objetivo es
99,9 % mensual, el presupuesto es el 0,1 % restante — unos 43 minutos. Mientras
quede presupuesto, se despliega; cuando se agota, se para y se arregla. Convierte
una discusión de opiniones en una cuenta.

Las decisiones:

**Por servicio y por tier**, porque prometer lo mismo a todos obliga a prometer
lo del más exigente o a incumplir al que paga por ello. El tier sale del plan
contratado, igual que RPO y RTO.

**Se mide sobre lo que el cliente nota**, no sobre lo que es fácil de medir. La
disponibilidad de un proceso que nadie usa no es disponibilidad; lo que cuenta
son las peticiones servidas correctamente frente al total.

**Se cuenta por tenant, no por tier.** Cada servicio sabe de qué tenant es cada
petición, pero **no** qué tier ha contratado —eso vive en `tenancy` y ningún
servicio lee el esquema de otro—. Contando por tenant, el tier se aplica al
leer, donde sí se sabe: lo fino se puede agregar y lo agregado no se puede
desglosar.

**Los contadores viven fuera del proceso.** En memoria sobrevivirían hasta el
siguiente despliegue, y con tres réplicas cada una tendría su propia verdad. Un
presupuesto mensual que se reinicia al desplegar dice siempre que queda margen —
que es exactamente lo que uno quiere oír y exactamente por lo que no serviría.
Se usa Redis, que ya está ahí para los límites de tasa; si no hay, se cae a
memoria y **se dice en la respuesta**, porque un número calculado sobre una
ventana de dos horas no es el presupuesto del mes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from crmcore.logging import get_logger

logger = get_logger(__name__)

# Tiers con compromiso declarado. Lista cerrada: el tier decide qué se promete,
# y un valor libre haría que un plan mal escrito se quedara sin objetivo.
TIERS = ("estandar", "premium", "enterprise")


@dataclass(frozen=True, slots=True)
class Objetivo:
    """Lo que se compromete de un servicio en un tier."""

    servicio: str
    tier: str
    # Porcentaje de peticiones que deben salir bien, mensual.
    disponibilidad_pct: float
    # Percentil 95 de latencia, en milisegundos. El p95 y no la media: la media
    # la arregla un montón de respuestas rápidas mientras el 5 % de los usuarios
    # espera cuatro segundos, y son esos los que llaman.
    latencia_p95_ms: int


@dataclass
class Consumo:
    """Lo gastado del presupuesto en el periodo."""

    peticiones: int = 0
    fallidas: int = 0
    lentas: int = 0
    # De dónde salen estas cuentas y desde cuándo. Va dentro a propósito: es lo
    # que distingue «el mes» de «desde que arrancó este proceso».
    origen: str = "memoria"
    desde: str = ""


def objetivo_de(servicio: str, tier: str) -> Objetivo:
    """El objetivo configurado para un servicio en un tier.

    Sale de `Settings`, no de constantes: el compromiso es una decisión de
    negocio con coste, y cambiarla no puede exigir un despliegue de código.
    """
    from crmcore.config import get_settings

    s = get_settings()
    if tier not in TIERS:
        # No se inventa un objetivo para un tier desconocido ni se coge el más
        # exigente: se aplica el estándar y se deja dicho, que es lo que se
        # promete por defecto.
        logger.warning("slo.tier_desconocido", tier=tier)
        tier = "estandar"
    return Objetivo(
        servicio=servicio,
        tier=tier,
        disponibilidad_pct=float(getattr(s, f"disponibilidad_{tier}")),
        latencia_p95_ms=int(getattr(s, f"latencia_p95_ms_{tier}")),
    )


def periodo(hoy: date | None = None) -> str:
    """Clave del periodo en curso. Mensual, como los compromisos."""
    dia = hoy or datetime.now(timezone.utc).date()
    return f"{dia.year:04d}-{dia.month:02d}"


def _clave(servicio: str, tenant_id: UUID | str | None, mes: str) -> str:
    return f"slo:{servicio}:{tenant_id or 'sin_tenant'}:{mes}"


# Respaldo en memoria: solo cuando no hay Redis. Se marca como tal en la
# respuesta, porque un presupuesto calculado desde el último arranque no es el
# presupuesto del mes y quien lo lea tiene que saberlo.
_memoria: dict[str, dict[str, int]] = {}
_arranque = datetime.now(timezone.utc)


async def _conectar() -> Any:
    """El cliente compartido, que se ata al bucle en curso.

    Va por `crmcore.redis_cliente` y no por una variable de aquí: un cliente
    guardado en un global sobrevive al bucle que lo creó, y a partir de ahí falla
    en cada operación sin que nadie lo note — los contadores seguirían dando
    números, los de un solo proceso.
    """
    from crmcore.redis_cliente import cliente

    return await cliente()


async def anotar(
    servicio: str,
    tenant_id: UUID | str | None,
    *,
    ok: bool,
    ms: float,
    mes: str | None = None,
) -> None:
    """Apunta una petición contra el presupuesto.

    Se cuenta **lenta** aparte de **fallida**: una respuesta que llega en cuatro
    segundos es un error para quien la espera aunque devuelva 200, y mezclarlas
    escondería el problema más común detrás del más raro.

    Y se cuenta la lentitud **contra los tres umbrales a la vez**. Guardar solo
    «lenta según el estándar» obligaría a decidir el tier al escribir, que es
    justo donde no se sabe; y recalcularlo después sería imposible, porque los
    milisegundos de cada petición ya no están. Son dos contadores más por tenant
    y mes: sale barato comparado con no poder responder la pregunta.

    Nunca levanta: si el contador falla, se pierde una petición de la cuenta,
    pero la respuesta al cliente sale igual. Al revés —tirar una petición buena
    porque no se pudo apuntar— sería que la medición del SLO gastara SLO.
    """
    clave = _clave(servicio, tenant_id, mes or periodo())
    incrementos: list[str] = ["peticiones"]
    if not ok:
        incrementos.append("fallidas")
    else:
        for tier in TIERS:
            if ms > objetivo_de(servicio, tier).latencia_p95_ms:
                incrementos.append(f"lentas_{tier}")

    try:
        r = await _conectar()
        if r:
            pipe = r.pipeline()
            for campo in incrementos:
                pipe.hincrby(clave, campo, 1)
            # Dos periodos de vida: el actual se necesita entero y el anterior
            # sigue sirviendo para comparar mientras dura el actual.
            pipe.expire(clave, 62 * 24 * 3600)
            await pipe.execute()
            return
    except Exception as exc:  # noqa: BLE001
        logger.warning("slo.no_anotado", motivo=str(exc)[:120])

    fila = _memoria.setdefault(clave, {})
    for campo in incrementos:
        fila[campo] = fila.get(campo, 0) + 1


async def consumo_de(
    servicio: str,
    tenant_id: UUID | str | None,
    *,
    tier: str = "estandar",
    mes: str | None = None,
) -> Consumo:
    """Lo consumido en el periodo, de donde esté guardado.

    El `tier` decide qué contador de lentitud se lee: la misma petición de 1,5 s
    es normal en estándar y es una falta en enterprise, y esa es exactamente la
    diferencia que el cliente está pagando.
    """
    if tier not in TIERS:
        tier = "estandar"
    clave = _clave(servicio, tenant_id, mes or periodo())
    try:
        r = await _conectar()
        if r:
            datos = await r.hgetall(clave) or {}
            return Consumo(
                peticiones=int(datos.get("peticiones") or 0),
                fallidas=int(datos.get("fallidas") or 0),
                lentas=int(datos.get(f"lentas_{tier}") or 0),
                origen="compartido",
                desde=f"periodo {mes or periodo()}",
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("slo.no_leido", motivo=str(exc)[:120])

    fila = _memoria.get(clave, {})
    return Consumo(
        peticiones=int(fila.get("peticiones") or 0),
        fallidas=int(fila.get("fallidas") or 0),
        lentas=int(fila.get(f"lentas_{tier}") or 0),
        origen="memoria_del_proceso",
        desde=_arranque.isoformat(),
    )


def presupuesto(
    objetivo: Objetivo, consumo: Consumo, *, dias_del_periodo: int = 30
) -> dict[str, Any]:
    """Cuánto presupuesto de error queda, y qué significa.

    Se devuelve en **minutos equivalentes** además de en porcentaje: «te queda el
    37 % del presupuesto» no le dice nada a nadie, y «te quedan 16 minutos de
    caída este mes» se entiende a la primera.
    """
    permitido_pct = 100.0 - objetivo.disponibilidad_pct
    minutos_del_periodo = dias_del_periodo * 24 * 60
    presupuesto_minutos = minutos_del_periodo * permitido_pct / 100

    base = {
        "servicio": objetivo.servicio,
        "tier": objetivo.tier,
        "objetivo_pct": objetivo.disponibilidad_pct,
        "latencia_objetivo_ms": objetivo.latencia_p95_ms,
        "presupuesto_minutos": round(presupuesto_minutos),
        "contado_en": consumo.origen,
        # Sin esto, un número calculado desde el último despliegue se lee como el
        # del mes, y el del mes es el único que vale para decidir si se para.
        "aviso": (
            ""
            if consumo.origen != "memoria_del_proceso"
            else "Contado solo en la memoria de este proceso desde "
            f"{consumo.desde}: no es la ventana del periodo, y cada réplica "
            "tiene la suya. Con Redis disponible, esta cuenta es del periodo."
        ),
    }

    if consumo.peticiones == 0:
        # Sin tráfico no hay medición, y decir «100 % disponible» sería mentir
        # con la verdad: un servicio que nadie usa no ha demostrado nada.
        return {
            **base,
            "medible": False,
            "motivo": "No ha habido peticiones en el periodo",
        }

    malas = consumo.fallidas + consumo.lentas
    consumido_pct = malas / consumo.peticiones * 100
    gastado = min(1.0, consumido_pct / permitido_pct) if permitido_pct else 1.0

    return {
        **base,
        "medible": True,
        "real_pct": round(100 - consumido_pct, 3),
        "peticiones": consumo.peticiones,
        "fallidas": consumo.fallidas,
        # Las lentas se enseñan aparte: quien lee esto necesita saber si el
        # problema es que se cae o que va lento, porque se arreglan distinto.
        "lentas": consumo.lentas,
        "presupuesto_gastado_pct": round(gastado * 100, 1),
        "minutos_restantes": round(presupuesto_minutos * (1 - gastado)),
        "agotado": gastado >= 1.0,
        "que_significa": (
            "Presupuesto agotado: toca parar de añadir y arreglar lo que falla"
            if gastado >= 1.0
            else "Queda margen: se puede seguir desplegando"
        ),
    }


def ventana(dias: int = 30) -> tuple[datetime, datetime]:
    hasta = datetime.now(timezone.utc)
    return hasta - timedelta(days=dias), hasta


def reiniciar() -> None:
    """Vacía los contadores en memoria. Para las pruebas."""
    _memoria.clear()
