"""Qué consulta se está degradando, y con qué volumen (CRM-00.06.01.07).

Una consulta que tarda 20 ms con mil filas y 4 segundos con un millón no falla
nunca: va empeorando. Nadie abre una incidencia por eso — se abre por «el CRM va
lento», meses después, cuando ya hay veinte consultas candidatas y ninguna
evidencia de cuál empezó.

Lo que hace falta no es medir el tiempo medio, que sube despacio y no dice nada.
Es **medir el tiempo contra el volumen**: una consulta sana tarda parecido con
mil filas y con cien mil porque usa un índice; una que no lo usa tarda
proporcionalmente más. Esa proporción es la señal, y se ve mucho antes de que el
tiempo absoluto moleste.

Se agrega por **forma de la consulta** y no por texto: dos consultas iguales con
parámetros distintos son la misma, y contarlas por separado esconde justo la que
se repite.
"""

from __future__ import annotations

import re
import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

from crmcore.logging import get_logger

logger = get_logger(__name__)


@dataclass
class Medida:
    """Lo acumulado de una forma de consulta."""

    veces: int = 0
    ms_total: float = 0.0
    filas_total: int = 0
    ms_maximo: float = 0.0
    # Muestras (filas, ms) para estimar la pendiente. Acotadas: guardar todas
    # convierte la observabilidad en el problema que venía a medir.
    muestras: list[tuple[int, float]] = field(default_factory=list)

    @property
    def ms_media(self) -> float:
        return self.ms_total / self.veces if self.veces else 0.0

    @property
    def us_por_fila(self) -> float:
        """Microsegundos por fila devuelta. Es la señal.

        Una consulta con índice tiene un coste por fila casi constante; una que
        recorre la tabla entera lo tiene creciente. Comparar esto entre dos
        momentos dice si está empeorando, y el tiempo absoluto no.
        """
        return (self.ms_total * 1000 / self.filas_total) if self.filas_total else 0.0


_medidas: dict[str, Medida] = defaultdict(Medida)


# Muestras por forma. Treinta bastan para ver una tendencia y no pesan.
def _obs_max_muestras() -> int:
    """Tope del núcleo, antes `_obs_max_muestras() = 30`.

    Era una constante de módulo. Sale del `.env`, no de los ajustes en
    caliente: es un tope operativo del despliegue y «por cliente» no
    significaría nada.
    """
    from crmcore.config import get_settings

    return get_settings().obs_max_muestras


_NUMEROS = re.compile(r"\b\d+\b")
_CADENAS = re.compile(r"'[^']*'")
_EN_LISTA = re.compile(r"\bIN\s*\([^)]*\)", re.IGNORECASE)


def forma(sql: str) -> str:
    """La consulta sin sus valores, para poder agruparla.

    Las listas de `IN` se colapsan a una sola marca: sin eso, la misma consulta
    con 3 y con 300 identificadores serían dos formas distintas, y la que se
    repite quedaría repartida entre cientos de filas del informe.
    """
    limpia = _EN_LISTA.sub("IN (?)", " ".join(sql.split()))
    limpia = _CADENAS.sub("?", limpia)
    limpia = _NUMEROS.sub("?", limpia)
    return limpia[:500]


@contextmanager
def medir(sql: str) -> Iterator[dict[str, int]]:
    """Mide una consulta. Quien la usa declara cuántas filas salieron.

    Las filas las pone quien llama y no se adivinan: el número de filas
    devueltas es lo que convierte el tiempo en una señal, y una estimación mala
    ahí produce un informe que señala la consulta equivocada.
    """
    resultado = {"filas": 0}
    inicio = time.perf_counter()
    try:
        yield resultado
    finally:
        anotar(sql, (time.perf_counter() - inicio) * 1000, resultado.get("filas", 0))


def anotar(sql: str, ms: float, filas: int) -> None:
    clave = forma(sql)
    medida = _medidas[clave]
    medida.veces += 1
    medida.ms_total += ms
    medida.filas_total += max(0, filas)
    medida.ms_maximo = max(medida.ms_maximo, ms)
    if len(medida.muestras) < _obs_max_muestras():
        medida.muestras.append((max(0, filas), ms))


def degradadas(*, minimo_veces: int = 20, factor: float = 2.0) -> list[dict[str, Any]]:
    """Las consultas cuyo coste por fila crece con el volumen.

    Se compara el coste por fila de las ejecuciones **grandes** contra las
    **pequeñas** de la misma forma. Si tarda proporcionalmente más cuanto más
    devuelve, no está usando índice para el filtro que importa — y eso es lo que
    explota cuando el cliente crece, no antes.

    Se exige un mínimo de ejecuciones porque con tres muestras cualquier ruido
    del disco parece una tendencia, y un informe que señala consultas sanas se
    deja de mirar a la semana.
    """
    salida: list[dict[str, Any]] = []
    for clave, medida in _medidas.items():
        if medida.veces < minimo_veces or len(medida.muestras) < 6:
            continue
        ordenadas = sorted(medida.muestras, key=lambda m: m[0])
        mitad = len(ordenadas) // 2
        pequenas, grandes = ordenadas[:mitad], ordenadas[mitad:]
        coste_pequenas = _coste_por_fila(pequenas)
        coste_grandes = _coste_por_fila(grandes)
        if coste_pequenas <= 0 or coste_grandes <= 0:
            continue
        if coste_grandes >= coste_pequenas * factor:
            salida.append(
                {
                    "consulta": clave,
                    "veces": medida.veces,
                    "ms_media": round(medida.ms_media, 1),
                    "ms_maximo": round(medida.ms_maximo, 1),
                    "us_por_fila_pocas": round(coste_pequenas, 2),
                    "us_por_fila_muchas": round(coste_grandes, 2),
                    "empeora": round(coste_grandes / coste_pequenas, 1),
                    # Se dice qué mirar, no solo que va mal: un informe que
                    # señala sin decir qué hacer se consulta una vez.
                    "que_mirar": (
                        "El coste por fila crece con el volumen: suele ser un filtro "
                        "u orden sin índice, o un índice que no empieza por la columna "
                        "que filtra"
                    ),
                }
            )
    return sorted(salida, key=lambda d: d["empeora"], reverse=True)


def _coste_por_fila(muestras: list[tuple[int, float]]) -> float:
    filas = sum(f for f, _ in muestras)
    ms = sum(m for _, m in muestras)
    return (ms * 1000 / filas) if filas else 0.0


def informe(*, top: int = 20) -> list[dict[str, Any]]:
    """Las consultas que más tiempo total consumen.

    Por tiempo **total** y no por tiempo medio: una consulta de 2 ms que corre
    cien mil veces cuesta más que una de 900 ms que corre dos, y es la que hay
    que arreglar primero. El informe por media señala siempre la segunda.
    """
    filas = [
        {
            "consulta": clave,
            "veces": m.veces,
            "ms_total": round(m.ms_total, 1),
            "ms_media": round(m.ms_media, 2),
            "ms_maximo": round(m.ms_maximo, 1),
            "us_por_fila": round(m.us_por_fila, 2),
        }
        for clave, m in _medidas.items()
    ]
    return sorted(filas, key=lambda d: d["ms_total"], reverse=True)[:top]


def reiniciar() -> None:
    _medidas.clear()
