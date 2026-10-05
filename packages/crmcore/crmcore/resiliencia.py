"""Que un tenant saturado no arrastre a los demás
(CRM-00.01.06.03, CRM-00.01.06.04, CRM-00.06.02.07).

Las cuotas dicen **cuánto** puede consumir cada cliente al mes. Esto es otra
cosa: qué pasa **ahora mismo**, cuando uno satura un recurso compartido y los
demás empiezan a esperar detrás. Las cuotas no lo ven, porque nadie ha superado
la suya: simplemente están todos pidiendo a la vez.

Tres mecanismos, y los tres responden a la misma idea — **fallar rápido y
parcialmente es mejor que esperar y caer entero**:

**Mamparos** (`bulkheads`): cada tenant tiene un número máximo de operaciones
simultáneas sobre un recurso. Sin ellos, un tenant que lanza doscientas
importaciones se lleva todas las conexiones del pool y los demás ven errores de
conexión — que no dicen nada de lo que está pasando y mandan a buscar el fallo a
la base de datos.

**Cortacircuitos** (`circuit breakers`): un recurso que falla repetidamente deja
de intentarse durante un rato. Reintentar contra algo caído no lo arregla y sí
consume el hilo que lo intenta: es como una caída se convierte en una caída
total.

**Degradación**: bajo saturación se difiere lo que puede esperar en vez de
rechazarlo todo por igual. Rechazar una escritura de cliente y un recálculo de
previsión con el mismo criterio es tratar como iguales dos cosas que no lo son.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator
from uuid import UUID

from crmcore.errors import ErrorValidacion, NoDisponible
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Prioridad de una operación. Lo que se difiere primero bajo presión es lo de
# abajo, y el orden no es negociable: entre perder la escritura de un comercial
# y retrasar un recálculo de previsión, no hay duda.
CRITICA = "critica"  # escrituras de usuario, autenticación
NORMAL = "normal"  # lecturas, listados
DIFERIBLE = "diferible"  # recálculos, reindexados, informes de fondo

ORDEN = {CRITICA: 0, NORMAL: 1, DIFERIBLE: 2}


@dataclass
class _Mampara:
    tope: int
    en_curso: int = 0
    rechazadas: int = 0


_mamparas: dict[tuple[str, UUID | None], _Mampara] = {}
_cerrojo = threading.Lock()


@contextmanager
def mampara(recurso: str, tenant_id: UUID | None, *, tope: int) -> Iterator[None]:
    """Limita cuántas operaciones simultáneas hace un tenant sobre un recurso.

    Por tenant y no global a propósito: un tope global protege el sistema y
    **no** protege a los clientes entre sí, que es el problema de verdad en
    multi-tenant. Con tope global, el tenant que lanza doscientas importaciones
    ocupa el cupo y los demás esperan detrás sin haber hecho nada.
    """
    clave = (recurso, tenant_id)
    with _cerrojo:
        estado = _mamparas.setdefault(clave, _Mampara(tope=tope))
        estado.tope = tope
        if estado.en_curso >= estado.tope:
            estado.rechazadas += 1
            logger.warning(
                "resiliencia.mampara_llena",
                recurso=recurso,
                tenant=str(tenant_id),
                tope=tope,
            )
            raise NoDisponible(
                f"Hay {tope} operaciones de «{recurso}» en curso para este cliente. "
                "Espera a que terminen antes de lanzar más.",
                error_code="resiliencia.mampara_llena",
                detalle={"recurso": recurso, "tope": tope},
            )
        estado.en_curso += 1
    try:
        yield
    finally:
        with _cerrojo:
            estado.en_curso = max(0, estado.en_curso - 1)


def _umbral_configurado() -> int:
    """Fallos seguidos que abren el circuito, **de la configuración**.

    Era un `5` escrito aquí mientras existía `CB_UMBRAL_FALLOS` en los ajustes,
    editable y documentado, **sin que lo leyera nadie**. Una instalación que
    quisiera abrir antes —porque su proveedor de correo se cae a menudo y no
    quiere gastar hilos reintentando— cambiaba un número que no hacía nada.
    """
    from crmcore.config import get_settings

    return int(get_settings().cb_umbral_fallos)


def _descanso_configurado() -> float:
    """Cuánto se queda abierto el circuito, **de la configuración**.

    Lo mismo que el umbral: `CB_REPOSO_S` existía y no lo leía nadie.
    """
    from crmcore.config import get_settings

    return float(get_settings().cb_reposo_s)


@dataclass
class _Circuito:
    fallos: int = 0
    abierto_hasta: float = 0.0
    # Cuántos fallos seguidos abren el circuito, y cuánto se queda abierto. Los
    # valores efectivos salen de la configuración; aquí solo hay un arranque
    # razonable para un circuito que todavía no ha fallado nunca.
    umbral: int = 5
    descanso_s: float = 30.0
    aperturas: int = 0


_circuitos: dict[str, _Circuito] = defaultdict(_Circuito)


def circuito_abierto(recurso: str) -> bool:
    """Si este recurso está descansando por haber fallado demasiado."""
    circuito = _circuitos[recurso]
    if circuito.abierto_hasta and time.monotonic() < circuito.abierto_hasta:
        return True
    if circuito.abierto_hasta:
        # Se cierra al vencer el descanso, pero NO se reinicia el contador de
        # fallos a cero: se deja a un fallo del umbral. Así, si sigue roto, el
        # primer intento vuelve a abrirlo en vez de tener que fallar cinco veces
        # más — que sería cinco veces el mismo timeout para todos los que pasen.
        circuito.abierto_hasta = 0.0
        circuito.fallos = max(0, circuito.umbral - 1)
    return False


def anotar_fallo(
    recurso: str, *, umbral: int | None = None, descanso_s: float | None = None
) -> None:
    """Apunta un fallo y abre el circuito si ya van demasiados seguidos.

    Sin `umbral` ni `descanso_s` se usan los de la configuración. Quien llame
    con valores propios los impone para ese recurso: hay recursos que merecen
    otro trato —un proveedor de inferencia caro no se reintenta como una caché—
    y eso se decide en la llamada, no en un ajuste global.
    """
    circuito = _circuitos[recurso]
    circuito.umbral = _umbral_configurado() if umbral is None else umbral
    circuito.descanso_s = _descanso_configurado() if descanso_s is None else descanso_s
    circuito.fallos += 1
    if circuito.fallos >= circuito.umbral:
        circuito.abierto_hasta = time.monotonic() + circuito.descanso_s
        circuito.aperturas += 1
        logger.error(
            "resiliencia.circuito_abierto",
            recurso=recurso,
            fallos=circuito.fallos,
            descanso_s=circuito.descanso_s,
        )


def anotar_exito(recurso: str) -> None:
    """Un éxito borra el historial: lo que importa son los fallos SEGUIDOS.

    Contar fallos acumulados abriría el circuito de un recurso que va bien
    simplemente porque lleva meses funcionando y ha fallado cinco veces en todo
    ese tiempo.
    """
    _circuitos[recurso].fallos = 0


@contextmanager
def circuito(
    recurso: str, *, umbral: int | None = None, descanso_s: float | None = None
) -> Iterator[None]:
    """Protege una llamada a un recurso que puede caerse.

    Reintentar contra algo caído no lo arregla y sí consume el hilo que lo
    intenta: es como una caída de un servicio se convierte en una caída total.
    """
    if circuito_abierto(recurso):
        raise NoDisponible(
            f"«{recurso}» no responde y se ha dejado de intentar durante un rato",
            error_code="resiliencia.circuito_abierto",
            detalle={"recurso": recurso},
        )
    try:
        yield
    except Exception:
        anotar_fallo(recurso, umbral=umbral, descanso_s=descanso_s)
        raise
    else:
        anotar_exito(recurso)


# ── Degradación y modo lectura ────────────────────────────────────────────


@dataclass
class _Presion:
    """Cuánta presión tiene el sistema ahora mismo, de 0 a 1."""

    valor: float = 0.0
    desde: float = field(default_factory=time.monotonic)


_presion = _Presion()


def fijar_presion(valor: float) -> None:
    """Lo fija quien mide: el gateway con su latencia, el worker con su cola.

    Se declara desde fuera y no se calcula aquí porque cada proceso sabe una
    cosa distinta de su propia saturación, y un cálculo central tendría que
    adivinar la de todos.
    """
    _presion.valor = max(0.0, min(1.0, valor))
    _presion.desde = time.monotonic()


def presion() -> float:
    return _presion.valor


def admite(prioridad: str) -> bool:
    """Si una operación de esta prioridad pasa con la presión actual.

    Lo diferible cae primero y lo crítico no cae nunca. Rechazar una escritura
    de cliente y un recálculo de previsión con el mismo criterio es tratar como
    iguales dos cosas que no lo son: una la está haciendo alguien delante de la
    pantalla y la otra puede esperar diez minutos sin que nadie lo note.
    """
    from crmcore.config import get_settings

    if prioridad == CRITICA:
        return True
    s = get_settings()
    if prioridad == NORMAL:
        return _presion.valor < float(s.degradacion_umbral_normal)
    # Los dos umbrales estaban escritos aquí —0.9 y 0.6— mientras
    # `DEGRADACION_UMBRAL_POOL` existía en los ajustes, documentado como «a
    # partir del cual se difiere lo no crítico», y no lo leía nadie. Quien lo
    # bajara para proteger antes su instalación cambiaba un número que no hacía
    # nada.
    return _presion.valor < float(s.degradacion_umbral_pool)


def exigir(prioridad: str) -> None:
    """Corta con 503 si la presión no admite esta prioridad.

    Con `Retry-After` implícito en el mensaje: un 503 sin decir cuándo volver
    hace que el cliente reintente inmediatamente, y mil clientes reintentando
    inmediatamente es cómo una degradación se convierte en una caída.
    """
    if admite(prioridad):
        return
    raise NoDisponible(
        "El sistema está saturado y esta operación puede esperar. "
        "Se ha diferido para que no afecte a lo urgente.",
        error_code="resiliencia.diferida",
        detalle={"prioridad": prioridad, "presion": round(_presion.valor, 2)},
    )


# ── Modo degradado: solo lectura (CRM-00.06.02.07) ────────────────────────

_solo_lectura = {"activo": False, "motivo": ""}


def entrar_en_solo_lectura(motivo: str) -> None:
    """Deja el sistema leyendo pero sin escribir.

    Es lo que convierte una avería de la base primaria en «no se puede guardar»
    en vez de en «el CRM no funciona». La diferencia importa: con lectura, el
    comercial que está delante de un cliente sigue viendo su ficha.

    **El motivo es obligatorio.** Sin él, quien no puede guardar cree que su
    cambio tenía algo malo y lo reintenta cambiándolo, que es cómo se pierde
    trabajo durante una incidencia — y además el mensaje que ve dice «el sistema
    está en modo solo lectura: », que es peor que no decir nada.
    """
    if not str(motivo).strip():
        raise ErrorValidacion(
            "Entrar en modo solo lectura exige decir por qué: es lo que se le "
            "enseña a quien no puede guardar.",
            error_code="resiliencia.solo_lectura_sin_motivo",
        )
    _solo_lectura["activo"] = True
    _solo_lectura["motivo"] = motivo
    logger.error("resiliencia.solo_lectura", motivo=motivo)


def salir_de_solo_lectura() -> None:
    _solo_lectura["activo"] = False
    _solo_lectura["motivo"] = ""
    logger.warning("resiliencia.escritura_restablecida")


def en_solo_lectura() -> bool:
    return bool(_solo_lectura["activo"])


def exigir_escritura() -> None:
    """Corta las escrituras mientras dure el modo degradado.

    El mensaje dice el motivo, y eso no es cortesía: sin él, el usuario cree que
    su cambio tenía algo malo y lo reintenta cambiándolo, que es cómo se pierde
    trabajo durante una incidencia.
    """
    if not _solo_lectura["activo"]:
        return
    raise NoDisponible(
        f"El sistema está en modo solo lectura: {_solo_lectura['motivo']}. "
        "Tus datos siguen ahí y se puede consultar todo; guardar no, de momento.",
        error_code="resiliencia.solo_lectura",
        detalle={"motivo": _solo_lectura["motivo"]},
    )


def estado() -> dict[str, Any]:
    """Qué está pasando ahora mismo, para la página de estado y las métricas."""
    return {
        "presion": round(_presion.valor, 2),
        "solo_lectura": bool(_solo_lectura["activo"]),
        "motivo": _solo_lectura["motivo"],
        "circuitos_abiertos": sorted(r for r in _circuitos if circuito_abierto(r)),
        "mamparas_llenas": sorted(
            f"{recurso}:{tenant}"
            for (recurso, tenant), m in _mamparas.items()
            if m.en_curso >= m.tope
        ),
    }


def reiniciar() -> None:
    """Vacía el estado de módulo. Para las pruebas, que si no se contaminan."""
    _mamparas.clear()
    _circuitos.clear()
    _presion.valor = 0.0
    _solo_lectura["activo"] = False
    _solo_lectura["motivo"] = ""
