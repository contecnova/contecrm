"""De dónde sale la presión del sistema (CRM-08.01.01.06).

`crmcore.resiliencia` sabe **qué hacer** cuando el sistema está saturado —dejar
pasar lo crítico, aplazar lo diferible— y no sabe **cuándo lo está**: eso lo tiene
que declarar quien mide. Sin nadie que lo declare, la presión vale cero para
siempre, todo pasa siempre, y la degradación controlada es un mecanismo que existe
en el código y no se activa jamás. Es el peor tipo de función: la que da confianza
sin hacer nada.

Este módulo es el que mide. Tres señales, y la decisión de cómo se combinan:

**La latencia contra el objetivo.** Es la que nota el usuario. Si el p95 va al
doble de lo prometido, el sistema ya está mal aunque nada haya fallado.

**El pool de conexiones.** Es la que avisa **antes**: cuando se agota, las
peticiones no van lentas, fallan de golpe.

**Y la cola de trabajos.** Dice que el trabajo de fondo se está acumulando, que es
el aviso más temprano de los tres y el que menos se mira.

**Manda la peor.** Promediarlas suaviza justo la que está dando el problema: con
el pool al 95 % y todo lo demás bien, la media sale tranquila y el sistema está a
punto de caer.

Y una decisión sobre cómo baja: **la presión sube rápido y baja despacio**. Si
bajara igual de rápido, el sistema oscilaría —admite, se satura, rechaza, se
alivia, admite— y esa oscilación es peor para el usuario que una degradación
estable, porque hace que la mitad de las peticiones fallen sin patrón.
"""

from __future__ import annotations

from typing import Any

from crmcore.logging import get_logger

logger = get_logger(__name__)

# Cuánto puede empeorar la latencia respecto del objetivo antes de contar como
# presión máxima. El doble: a partir de ahí, lo que note el usuario ya no depende
# de cuánto peor vaya.
FACTOR_LATENCIA = 2.0

# A partir de qué ocupación del pool empieza a contar. Por debajo del 70 % un pool
# ocupado es un pool que se está usando, que es para lo que está.
POOL_DESDE = 0.70

# Cuántos trabajos pendientes por worker cuentan como saturación total. Es alto a
# propósito: una cola con cien trabajos no es un problema si hay diez workers.
COLA_POR_WORKER = 200

# Cuánto baja la presión en cada medida cuando la señal mejora. Sube de golpe y
# baja un 15 % cada vez: sin esto el sistema oscila, y media petición fallando sin
# patrón es peor que una degradación estable.
BAJADA_MAXIMA = 0.15


def _normalizar(valor: float) -> float:
    return max(0.0, min(1.0, valor))


def por_latencia(*, p95_ms: float, objetivo_ms: float) -> float:
    """Presión que aporta la latencia frente a lo prometido.

    Se mide contra el **objetivo**, no contra un número absoluto: 800 ms son un
    desastre en una lectura de lista y están bien en un informe pesado, y un
    umbral fijo trata igual dos cosas que no lo son.
    """
    if objetivo_ms <= 0:
        return 0.0
    exceso = (p95_ms - objetivo_ms) / (objetivo_ms * (FACTOR_LATENCIA - 1))
    return _normalizar(exceso)


def por_pool(*, en_uso: int, tamano: int) -> float:
    """Presión que aporta el pool de conexiones.

    Es la señal que avisa **antes**: cuando el pool se agota, las peticiones no se
    ponen lentas, fallan de golpe. Por eso empieza a contar en el 70 % y no en el
    100 %.
    """
    if tamano <= 0:
        return 0.0
    ocupacion = en_uso / tamano
    if ocupacion <= POOL_DESDE:
        return 0.0
    return _normalizar((ocupacion - POOL_DESDE) / (1 - POOL_DESDE))


def por_cola(*, pendientes: int, workers: int) -> float:
    """Presión que aporta la cola de trabajos de fondo.

    Se mide **por worker**: cien trabajos con diez workers no es lo mismo que cien
    con uno, y contar solo el total hace que un despliegue con menos réplicas
    parezca un pico de carga.
    """
    if workers <= 0:
        return 1.0 if pendientes else 0.0
    return _normalizar(pendientes / (workers * COLA_POR_WORKER))


def calcular(
    *,
    p95_ms: float | None = None,
    objetivo_ms: float | None = None,
    pool_en_uso: int | None = None,
    pool_tamano: int | None = None,
    cola_pendientes: int | None = None,
    workers: int | None = None,
    presion_anterior: float = 0.0,
) -> dict[str, Any]:
    """La presión del proceso ahora mismo, con **de dónde sale**.

    Manda la peor señal. Promediarlas suaviza justo la que está dando el
    problema: con el pool al 95 % y lo demás bien, la media sale tranquila y el
    sistema está a punto de caer.

    Y la señal que no se puede medir **no cuenta como cero**: se dice cuál falta.
    Un proceso que solo mide latencia y da presión baja mientras su cola crece
    está dando una respuesta tranquilizadora sobre algo que no ha mirado.
    """
    señales: dict[str, float] = {}
    sin_medir: list[str] = []

    if p95_ms is not None and objetivo_ms:
        señales["latencia"] = por_latencia(p95_ms=p95_ms, objetivo_ms=objetivo_ms)
    else:
        sin_medir.append("latencia")

    if pool_en_uso is not None and pool_tamano:
        señales["pool"] = por_pool(en_uso=pool_en_uso, tamano=pool_tamano)
    else:
        sin_medir.append("pool")

    if cola_pendientes is not None and workers is not None:
        señales["cola"] = por_cola(pendientes=cola_pendientes, workers=workers)
    else:
        sin_medir.append("cola")

    if not señales:
        return {
            "presion": presion_anterior,
            "medible": False,
            "sin_medir": sin_medir,
            "porque": (
                "No se ha podido medir ninguna señal. La presión se queda como estaba: "
                "ponerla a cero sería decir que todo va bien sin haber mirado."
            ),
        }

    cruda = max(señales.values())
    peor = max(señales, key=lambda k: señales[k])

    # Sube de golpe y baja despacio. Sin esto el sistema oscila entre admitir y
    # rechazar, y media petición fallando sin patrón es peor para el usuario que
    # una degradación estable.
    if cruda >= presion_anterior:
        final = cruda
    else:
        final = max(cruda, presion_anterior - BAJADA_MAXIMA)

    return {
        "presion": round(final, 3),
        "medible": True,
        "manda": peor,
        "senales": {k: round(v, 3) for k, v in señales.items()},
        "sin_medir": sin_medir,
        "subiendo": cruda >= presion_anterior,
        "porque": (
            f"Manda «{peor}» con {round(señales[peor], 2)}. Se coge la peor y no la "
            "media: promediar suaviza justo la señal que está dando el problema."
            + (
                f" No se ha podido medir: {', '.join(sin_medir)} — y lo que no se mide "
                "no cuenta como cero."
                if sin_medir
                else ""
            )
        ),
    }


def aplicar(resultado: dict[str, Any]) -> float:
    """Le dice a `resiliencia` cuánta presión hay.

    Existe para que el sitio donde se mide y el sitio donde se decide sean dos, y
    para que quede una sola línea que los une — que es la que faltaba: el
    mecanismo de degradación llevaba desde el principio sin que nadie le dijera
    nunca que el sistema estaba saturado, así que no se activó jamás.
    """
    from crmcore import resiliencia

    valor = float(resultado.get("presion") or 0.0)
    anterior = resiliencia.presion()
    resiliencia.fijar_presion(valor)

    if valor >= 0.6 > anterior:
        logger.warning(
            "presion.degradando",
            extra={
                "presion": valor,
                "manda": resultado.get("manda"),
                "senales": resultado.get("senales"),
            },
        )
    elif anterior >= 0.6 > valor:
        logger.info("presion.recuperada", extra={"presion": valor})
    return valor


def que_se_esta_aplazando(presion_actual: float) -> dict[str, Any]:
    """Qué se está dejando pasar y qué no, con la presión de ahora.

    Sirve para contestar la pregunta de un incidente —«¿por qué mi informe no
    sale?»— sin tener que leer el código: lo diferible cae primero, lo crítico no
    cae nunca.
    """
    from crmcore import resiliencia

    return {
        "presion": round(presion_actual, 2),
        "critica": True,
        "normal": presion_actual < 0.9,
        "diferible": presion_actual < 0.6,
        "que_significa": (
            "Todo pasa: el sistema no está bajo presión."
            if presion_actual < 0.6
            else (
                "Se están aplazando los recálculos, los informes pesados y las tareas "
                "de fondo. Las escrituras de usuario siguen pasando."
                if presion_actual < 0.9
                else "Solo pasa lo crítico: autenticación y escrituras de usuario. Todo "
                "lo demás espera."
            )
        ),
        "prioridades": {
            "critica": resiliencia.CRITICA,
            "normal": resiliencia.NORMAL,
            "diferible": resiliencia.DIFERIBLE,
        },
    }
