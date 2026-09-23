"""Catálogo de servicios, malla y despliegue sin corte
(CRM-00.03.01.04, CRM-00.03.01.05, CRM-00.06.02.05, CRM-00.06.02.08).

Cuatro cosas que se documentan en una wiki, se quedan viejas y entonces hacen daño
justo cuando hacen falta: a las tres de la mañana, con un servicio caído y alguien
buscando a quién llamar.

Aquí se declaran **en el código**, junto a lo que describen, y se comprueban:

**El catálogo de servicios** dice quién es dueño de cada uno, qué promete, de qué
depende y qué runbook abrir. Un servicio sin dueño declarado es un servicio que en
una guardia nadie sabe de quién es, y el catálogo que vive en una wiki miente a los
tres meses.

**La malla** —mTLS, reintentos, tiempos de espera, corte de circuito— es lo que
impide que un servicio lento se lleve por delante a los que dependen de él. Lo que
hay que declarar no es la tecnología: es **qué se puede reintentar**, porque
reintentar una escritura no idempotente duplica pedidos.

**La alta disponibilidad** no es tener réplicas: es saber **qué pasa cuando se cae
una zona**, y haberlo probado. Una réplica que nadie ha promocionado nunca es una
suposición cara.

**Y el despliegue sin corte** solo lo es si la vuelta atrás también lo es. Un
canario que no se puede revertir en un minuto no es un canario: es un despliegue
con público.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from crmcore.errors import ErrorValidacion
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Lo que hay que declarar de cada servicio. Cerrada porque cada campo se usa en un
# momento concreto de una guardia, y el que falta es el que hace falta.
CAMPOS_DEL_CATALOGO = ("dueno", "slo", "depende_de", "runbook", "criticidad")

# Qué se puede reintentar sin duplicar nada. Es la decisión que importa de la
# malla: reintentar un POST no idempotente crea dos pedidos, y el cliente lo ve
# antes que nosotros.
REINTENTABLES = ("GET", "HEAD", "OPTIONS", "PUT", "DELETE")

# Criticidades. De aquí sale a quién se despierta y qué se degrada primero.
CRITICIDADES = ("critico", "importante", "diferible")

# Estrategias de despliegue admitidas. `recreate` está a propósito: es honesto
# para un entorno de pruebas y deshonesto llamarlo «sin corte».
ESTRATEGIAS = ("blue_green", "canary", "rolling", "recreate")

SIN_CORTE = ("blue_green", "canary", "rolling")


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def validar_catalogo(*, servicios: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Comprueba el catálogo de servicios.

    Se devuelven **todos** los huecos: quien está montando el catálogo agradece
    ver las doce cosas que faltan de una vez, no una por despliegue.

    Y se detectan las **dependencias circulares**, que son las que producen un
    arranque que nunca termina y una guardia en la que todos los servicios están
    «esperando al otro».
    """
    problemas: list[dict[str, str]] = []
    for nombre, ficha in servicios.items():
        for campo in CAMPOS_DEL_CATALOGO:
            if not ficha.get(campo):
                problemas.append(
                    {
                        "servicio": nombre,
                        "falta": campo,
                        "porque": (
                            "Un servicio sin dueño es uno que en una guardia nadie sabe "
                            "de quién es"
                            if campo == "dueno"
                            else f"Sin «{campo}» no se puede decidir en un incidente"
                        ),
                    }
                )
        criticidad = str(ficha.get("criticidad") or "")
        if criticidad and criticidad not in CRITICIDADES:
            problemas.append(
                {
                    "servicio": nombre,
                    "falta": "criticidad válida",
                    "porque": f"«{criticidad}» no es una de {list(CRITICIDADES)}",
                }
            )

    ciclos = _ciclos({n: list(f.get("depende_de") or []) for n, f in servicios.items()})
    return {
        "valido": not problemas and not ciclos,
        "problemas": problemas,
        "dependencias_circulares": ciclos,
        "servicios": len(servicios),
        "porque": (
            "Hay dependencias circulares: producen un arranque que nunca termina y una "
            "guardia en la que todos los servicios están esperando al otro."
            if ciclos
            else "El catálogo está completo."
        ),
    }


def _ciclos(grafo: dict[str, list[str]]) -> list[list[str]]:
    """Ciclos de dependencia, por búsqueda en profundidad."""
    encontrados: list[list[str]] = []
    visitando: list[str] = []

    def _bajar(nodo: str) -> None:
        if nodo in visitando:
            ciclo = visitando[visitando.index(nodo) :] + [nodo]
            if ciclo not in encontrados:
                encontrados.append(ciclo)
            return
        visitando.append(nodo)
        for hijo in grafo.get(nodo, []):
            if hijo in grafo:
                _bajar(hijo)
        visitando.pop()

    for nodo in sorted(grafo):
        _bajar(nodo)
    return encontrados


def politica_de_reintento(*, metodo: str, idempotente: bool) -> dict[str, Any]:
    """Si esta llamada se puede reintentar.

    Es la decisión que importa de la malla, y la que más se configura mal: un
    reintento automático sobre un `POST` que crea algo produce dos pedidos, y el
    cliente lo ve antes que nosotros.

    Una escritura **con clave de idempotencia sí se reintenta**, porque el
    servidor sabe que es la misma: por eso el CRM la exige en las escrituras que
    importan.
    """
    arriba = metodo.upper()
    if arriba in REINTENTABLES:
        return {
            "reintentar": True,
            "porque": f"{arriba} no cambia nada o deja el mismo resultado al repetirse.",
        }
    if idempotente:
        return {
            "reintentar": True,
            "porque": (
                "Lleva clave de idempotencia: el servidor reconoce que es la misma "
                "petición y no la ejecuta dos veces."
            ),
        }
    return {
        "reintentar": False,
        "porque": (
            f"{arriba} sin clave de idempotencia no se reintenta: crearía dos pedidos, y "
            "el cliente lo vería antes que nosotros."
        ),
    }


def plan_multi_zona(
    *,
    zonas: list[dict[str, Any]],
    ultimo_simulacro: datetime | None,
    ahora: datetime | None = None,
) -> dict[str, Any]:
    """Qué pasa de verdad si se cae una zona.

    **Tener réplicas no es alta disponibilidad.** Lo que decide si el sistema
    aguanta es si la promoción está probada y si lo que queda en pie tiene
    capacidad para todo el tráfico: dos zonas al 60 % de uso cada una no sobreviven
    a perder una, y eso se sabe sumando, no esperando.

    Y un plan **sin simulacro** es una suposición cara: nadie sabe cuánto tarda de
    verdad una promoción hasta que la ha hecho con el reloj delante.
    """
    momento = ahora or _ahora()
    activas = [z for z in zonas if z.get("activa")]
    capacidad_total = sum(float(z.get("capacidad_pct") or 0) for z in activas)
    carga = float(max((z.get("carga_pct") or 0) for z in activas)) if activas else 0.0

    # Qué queda si se cae la zona más grande.
    mayor = max((float(z.get("capacidad_pct") or 0) for z in activas), default=0.0)
    queda = capacidad_total - mayor
    aguanta = queda >= 100.0

    dias = (momento - ultimo_simulacro).days if ultimo_simulacro else None
    return {
        "zonas_activas": len(activas),
        "capacidad_total_pct": capacidad_total,
        "queda_si_cae_la_mayor_pct": queda,
        "aguanta_perder_una": aguanta,
        "ultimo_simulacro_hace_dias": dias,
        "plan_probado": dias is not None,
        "que_significa": (
            "Con una zona menos no hay capacidad para todo el tráfico: dos zonas al "
            "60 % no sobreviven a perder una, y eso se sabe sumando, no esperando."
            if not aguanta
            else (
                "Nunca se ha hecho un simulacro. Tener réplicas no es alta "
                "disponibilidad: nadie sabe cuánto tarda una promoción hasta que la ha "
                "hecho con el reloj delante."
                if dias is None
                else f"Aguanta perder una zona y el último simulacro fue hace {dias} días."
            )
        ),
        "carga_maxima_actual_pct": carga,
    }


def comprobar_despliegue(
    *,
    estrategia: str,
    puede_volver_atras_en_min: int | None,
    migracion_compatible_hacia_atras: bool,
    porcentaje_canario: int = 0,
) -> dict[str, Any]:
    """Si esto es de verdad un despliegue sin corte.

    Dos comprobaciones que separan un despliegue sin corte de uno con público:

    **La vuelta atrás tiene que ser rápida.** Un canario que no se revierte en un
    minuto no es un canario: es un despliegue progresivo con testigos, y cuando
    algo va mal lo que se hace es «esperar a ver si se arregla».

    **Y la migración tiene que ser compatible hacia atrás.** Si el esquema nuevo
    rompe al código viejo, durante el despliegue hay dos versiones hablando con la
    misma base y una de las dos falla. Eso no es un riesgo teórico: es lo que pasa
    siempre en el minuto dos.
    """
    if estrategia not in ESTRATEGIAS:
        raise ErrorValidacion(
            f"Estrategia «{estrategia}» desconocida",
            error_code="despliegue.estrategia_invalida",
            detalle={"admitidas": list(ESTRATEGIAS)},
        )
    problemas: list[str] = []
    if estrategia not in SIN_CORTE:
        problemas.append(
            f"«{estrategia}» corta el servicio. Es honesto para un entorno de pruebas y "
            "deshonesto llamarlo despliegue sin corte."
        )
    if puede_volver_atras_en_min is None or puede_volver_atras_en_min > 5:
        problemas.append(
            "La vuelta atrás no está probada o tarda demasiado. Un canario que no se "
            "revierte en un minuto es un despliegue con público: cuando algo va mal, lo "
            "que se hace es esperar a ver si se arregla."
        )
    if not migracion_compatible_hacia_atras:
        problemas.append(
            "La migración no es compatible con la versión anterior. Durante el "
            "despliegue hay dos versiones hablando con la misma base y una falla — no "
            "es un riesgo teórico, pasa en el minuto dos."
        )
    if estrategia == "canary" and not 1 <= porcentaje_canario <= 25:
        problemas.append(
            f"Un canario del {porcentaje_canario} % no sirve: por debajo del 1 % no "
            "detecta nada y por encima del 25 % ya no es un canario, es medio "
            "despliegue."
        )

    return {
        "sin_corte": not problemas,
        "problemas": problemas,
        "estrategia": estrategia,
        "que_hacer": (
            ""
            if not problemas
            else "Arreglar esto antes de desplegar: cada uno de estos puntos es una "
            "forma conocida de convertir un despliegue rutinario en un incidente."
        ),
    }


def senales_para_abortar(*, metricas: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    """Cuándo se revierte un canario, decidido **antes** de desplegar.

    Si el criterio se decide mirando los números en caliente, siempre parece que
    «todavía no es para tanto»: el error sube, alguien dice que puede ser un pico,
    y media hora después ya hay clientes afectados. Por eso los umbrales van
    escritos antes y la decisión es automática.
    """
    motivos: list[str] = []
    errores = float(metricas.get("error_pct") or 0)
    errores_base = float(base.get("error_pct") or 0)
    if errores > max(1.0, errores_base * 2):
        motivos.append(f"Los errores están en {errores} % frente a {errores_base} % de referencia.")
    p95 = float(metricas.get("p95_ms") or 0)
    p95_base = float(base.get("p95_ms") or 0)
    if p95_base and p95 > p95_base * 1.5:
        motivos.append(f"La latencia p95 es {p95} ms frente a {p95_base} ms.")
    if metricas.get("errores_de_arranque"):
        motivos.append("Hay réplicas que no llegan a arrancar.")

    return {
        "abortar": bool(motivos),
        "motivos": motivos,
        "decidido_de_antemano": True,
        "porque": (
            "Los umbrales se fijan antes de desplegar. Decidiéndolo en caliente siempre "
            "parece que «todavía no es para tanto», y media hora después ya hay clientes "
            "afectados."
        ),
    }
