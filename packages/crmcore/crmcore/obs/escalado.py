"""Escalado horizontal, servicio por servicio (CRM-08.01.01.02).

Que cada servicio se escale por separado es la razón principal de que esto no sea
un monolito. Pero «poner más réplicas» no es una respuesta: casi siempre **no
arregla nada y a veces empeora**, y conviene saber por qué antes de un incidente.

Dos cosas que hay que tener claras:

**Cada servicio tiene un límite que no es la CPU.** El gateway lo tiene en las
conexiones salientes, los servicios de datos en el pool de Postgres, el de
inteligencia en la cuota del proveedor de inferencia. Añadir réplicas por encima
de ese límite **empeora**: más réplicas es más conexiones peleando por el mismo
pool, más contención y más latencia, no menos.

**Y un servicio solo se puede replicar si no guarda nada en su proceso.** Un
contador en memoria, una caché que se cree única, un planificador sin elección de
líder: con una réplica funcionan, con tres cuentan la tercera parte, caducan
distinto y ejecutan la misma tarea tres veces. Esto ya ha pasado aquí —los
contadores del presupuesto de error estaban en memoria y con dos réplicas medían
la mitad—, así que está declarado y comprobado.
"""

from __future__ import annotations

from typing import Any

from crmcore.errors import ErrorValidacion
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Qué limita de verdad a cada servicio. No es la CPU casi nunca, y confundirlo es
# lo que hace que alguien duplique réplicas y empeore la latencia.
LIMITES = (
    "pool_postgres",
    "conexiones_salientes",
    "cuota_externa",
    "cpu",
    "memoria",
    "bus",
)

# Lo que impide replicar un proceso. Cada uno con lo que pasa de verdad cuando se
# ignora, porque en abstracto todos suenan a detalle.
RIESGOS = {
    "contador_en_memoria": (
        "Con tres réplicas, cada una cuenta un tercio. Ya pasó aquí con el presupuesto "
        "de error: medía la mitad y el panel decía que todo iba bien"
    ),
    "cache_en_memoria": (
        "Cada réplica caduca cuando le toca, así que el mismo usuario ve el valor "
        "nuevo o el viejo según a quién le caiga la petición"
    ),
    "planificador_sin_lider": (
        "Las tres réplicas ejecutan la tarea programada: tres correos, tres cobros, "
        "tres importaciones"
    ),
    "fichero_local": (
        "Cada réplica ve solo lo que ella escribió, y el usuario ve el adjunto o no "
        "según dónde caiga"
    ),
    "sesion_pegajosa": (
        "Obliga a que el usuario vuelva siempre a la misma réplica, así que un "
        "despliegue le corta la sesión"
    ),
    "bloqueo_en_proceso": (
        "Un lock de Python no impide nada entre procesos: dos réplicas hacen a la vez "
        "lo que el lock existía para serializar"
    ),
}


def comprobar_replicable(*, servicio: str, declaracion: dict[str, Any]) -> dict[str, Any]:
    """Si este servicio se puede poner a tres réplicas sin romper nada.

    Se comprueban los riesgos **declarados**, con lo que pasa de verdad cuando se
    ignoran. Y se devuelven todos: quien está preparando un servicio para escalar
    agradece la lista entera, no descubrirlos de uno en uno con un incidente entre
    cada dos.
    """
    presentes = [
        {"riesgo": clave, "pasa": RIESGOS[clave]} for clave in RIESGOS if declaracion.get(clave)
    ]
    return {
        "servicio": servicio,
        "replicable": not presentes,
        "riesgos": presentes,
        "que_hacer": (
            ""
            if not presentes
            else "Mover lo compartido fuera del proceso —Redis para contadores y cachés, "
            "elección de líder para lo programado, almacenamiento común para los "
            "ficheros— antes de subir de una réplica."
        ),
    }


def replicas_utiles(
    *,
    servicio: str,
    limite: str,
    capacidad_del_limite: int,
    consumo_por_replica: int,
    replicas_actuales: int,
) -> dict[str, Any]:
    """Cuántas réplicas **sirven de algo**, y a partir de cuál empeora.

    Es la cuenta que nadie hace antes de escalar. Si el límite es el pool de
    Postgres y cada réplica abre veinte conexiones sobre un pool de cien, la quinta
    réplica no reparte trabajo: **quita conexiones a las otras cuatro**. La latencia
    sube y la conclusión habitual es «hay que poner más réplicas».
    """
    if limite not in LIMITES:
        raise ErrorValidacion(
            f"Límite «{limite}» desconocido",
            error_code="escalado.limite_invalido",
            detalle={"admitidos": list(LIMITES)},
        )
    if consumo_por_replica <= 0:
        raise ErrorValidacion(
            "Una réplica que no consume nada del límite no existe: si no consume, el "
            "límite no es ese.",
            error_code="escalado.consumo_invalido",
        )

    maximo = capacidad_del_limite // consumo_por_replica
    sobran = max(0, replicas_actuales - maximo)
    return {
        "servicio": servicio,
        "limite": limite,
        "replicas_utiles_maximo": maximo,
        "replicas_actuales": replicas_actuales,
        "sobran": sobran,
        "puede_crecer": max(0, maximo - replicas_actuales),
        "que_significa": (
            f"Con {replicas_actuales} réplicas ya se está por encima de lo que permite "
            f"«{limite}»: {sobran} de más. Cada una quita capacidad a las otras, la "
            "latencia sube, y la conclusión habitual es poner todavía más."
            if sobran
            else (
                f"Caben {maximo - replicas_actuales} réplicas más antes de tocar el "
                f"límite de «{limite}»."
                if maximo > replicas_actuales
                else f"Ya se está en el máximo que permite «{limite}»: para crecer más "
                "hay que subir ese límite, no las réplicas."
            )
        ),
    }


def donde_escalar(*, servicios: list[dict[str, Any]]) -> dict[str, Any]:
    """Qué servicio hay que escalar de verdad.

    Escalar el que va lento no siempre sirve: si el gateway tarda porque `party`
    tarda, poner más gateways hace que esperen más peticiones a la vez. Lo que hay
    que mirar es **dónde se pasa el tiempo**, no dónde se nota.

    Y cuando todos están por debajo de su límite, la respuesta honesta es que el
    problema no es de capacidad — que es más incómoda y ahorra una factura.
    """
    saturados = [s for s in servicios if float(s.get("uso_del_limite_pct") or 0) >= 80]
    if not saturados:
        return {
            "escalar": [],
            "porque": (
                "Ningún servicio está cerca de su límite. Si algo va lento, no es de "
                "capacidad: escalar aquí cuesta dinero y no arregla nada."
            ),
        }
    culpables = [
        s
        for s in saturados
        if not any(
            otro.get("nombre") in (s.get("depende_de") or [])
            and float(otro.get("uso_del_limite_pct") or 0) >= 80
            for otro in servicios
        )
    ]
    return {
        "escalar": [s.get("nombre") for s in (culpables or saturados)],
        "saturados": [s.get("nombre") for s in saturados],
        "porque": (
            "Se escala el que está saturado y no depende de otro que también lo esté. "
            "Si el gateway tarda porque `party` tarda, poner más gateways solo hace que "
            "esperen más peticiones a la vez."
        ),
    }
