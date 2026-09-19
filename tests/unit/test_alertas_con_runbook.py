"""Toda alerta tiene instrucciones (CRM-00.06.01.05).

Una alerta sin runbook despierta a alguien a las tres de la mañana para que
averigüe desde cero qué significa. Lo que pasa después —siempre— es que se
silencia, y una alerta silenciada no avisa de nada: el sistema queda peor que si
no la tuviera, porque ahora además hay quien cree que está cubierto.

Este gate comprueba las dos direcciones. Que ninguna alerta enlace un runbook que
no existe, y que ningún runbook se quede huérfano — un runbook que ninguna alerta
usa suele ser el rastro de una alerta que se quitó, y leerlo en un incidente
manda a quien lo lee a buscar algo que ya no está.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[2]
ALERTAS = RAIZ / "ops" / "prometheus" / "alertas.yml"
RUNBOOKS = RAIZ / "docs" / "runbooks"


@pytest.fixture(scope="module")
def reglas() -> list[dict]:
    documento = yaml.safe_load(ALERTAS.read_text(encoding="utf-8"))
    return [r for grupo in documento["groups"] for r in grupo["rules"]]


def _nombre_runbook(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1]


def test_hay_alertas_definidas(reglas: list[dict]) -> None:
    assert len(reglas) >= 5, "El fichero de alertas está casi vacío"


def test_toda_alerta_tiene_runbook_y_existe(reglas: list[dict]) -> None:
    problemas: list[str] = []
    for regla in reglas:
        nombre = regla.get("alert", "(sin nombre)")
        url = (regla.get("annotations") or {}).get("runbook_url", "")
        if not url:
            problemas.append(f"{nombre}: no enlaza ningún runbook")
            continue
        fichero = RUNBOOKS / f"{_nombre_runbook(url)}.md"
        if not fichero.exists():
            problemas.append(f"{nombre}: enlaza «{fichero.name}», que no existe")
    assert not problemas, "Alertas sin instrucciones:\n  " + "\n  ".join(problemas)


def test_ningun_runbook_huerfano(reglas: list[dict]) -> None:
    """Un runbook que ninguna alerta usa suele ser el rastro de una alerta que se
    quitó, y leerlo en un incidente manda a buscar algo que ya no está."""
    enlazados = {
        _nombre_runbook((r.get("annotations") or {}).get("runbook_url", "")) for r in reglas
    }
    existentes = {f.stem for f in RUNBOOKS.glob("*.md")} - {"index"}
    huerfanos = sorted(existentes - enlazados)
    assert not huerfanos, f"Runbooks que ninguna alerta enlaza: {huerfanos}"


def test_toda_alerta_dice_que_hacer(reglas: list[dict]) -> None:
    """Una alerta dice qué hacer, no solo qué pasa.

    «La tabla de salida se está atascando» es un hecho; «los eventos dejarán de
    entregarse y hay que mirar el bus» es accionable. Se comprueba que hay
    resumen y descripción, que son los dos campos que se leen en el aviso antes
    de abrir nada.
    """
    incompletas = [
        r.get("alert", "(sin nombre)")
        for r in reglas
        if not (r.get("annotations") or {}).get("resumen")
        or not (r.get("annotations") or {}).get("descripcion")
    ]
    assert not incompletas, f"Alertas sin resumen o sin descripción: {incompletas}"


def test_toda_alerta_declara_gravedad(reglas: list[dict]) -> None:
    """Sin gravedad, el encaminamiento no sabe a quién despertar y todo acaba en
    el mismo sitio: o se despierta a alguien por un aviso, o no se le despierta
    por una caída."""
    validas = {"critica", "aviso"}
    malas = [
        f"{r.get('alert')}: {(r.get('labels') or {}).get('severidad')}"
        for r in reglas
        if (r.get("labels") or {}).get("severidad") not in validas
    ]
    assert not malas, f"Alertas con gravedad ausente o desconocida: {malas}"


def test_toda_alerta_espera_antes_de_disparar(reglas: list[dict]) -> None:
    """`for` es lo que separa una alerta de un pico.

    Sin él, un reinicio de dos segundos manda un aviso de servicio caído, y a la
    tercera vez nadie los mira.
    """
    sin_espera = [r.get("alert") for r in reglas if not r.get("for")]
    assert not sin_espera, f"Alertas que disparan al instante: {sin_espera}"


def test_los_runbooks_siguen_la_misma_estructura() -> None:
    """Quien abre uno a las tres de la mañana no puede estar adivinando dónde
    mirar. El orden también importa: diagnóstico antes que acción, porque la
    mitad de los incidentes se empeoran actuando sobre el síntoma equivocado.
    """
    exigidas = ["## Qué significa", "## Cuánto corre", "## Qué mirar", "## Qué hacer"]
    problemas: list[str] = []
    for fichero in sorted(RUNBOOKS.glob("*.md")):
        if fichero.stem == "index":
            continue
        texto = fichero.read_text(encoding="utf-8")
        faltan = [s for s in exigidas if s not in texto]
        if faltan:
            problemas.append(f"{fichero.name}: le faltan {faltan}")
            continue
        posiciones = [texto.index(s) for s in exigidas]
        if posiciones != sorted(posiciones):
            problemas.append(f"{fichero.name}: las secciones están desordenadas")
    assert not problemas, "Runbooks mal formados:\n  " + "\n  ".join(problemas)


def test_las_expresiones_de_las_alertas_usan_metricas_que_existen(reglas: list[dict]) -> None:
    """Una alerta sobre una métrica que no se publica no salta nunca.

    Es el fallo más silencioso posible: parece que hay cobertura y no la hay. Se
    comprueba contra los nombres declarados en el código, no contra una lista
    aparte que se desincronizaría.
    """
    fuente = (RAIZ / "packages" / "crmcore" / "crmcore" / "obs" / "metrics.py").read_text(
        encoding="utf-8"
    )
    declaradas = set(re.findall(r'"(crm_[a-z_]+)"', fuente))
    # `up` la publica Prometheus, no el código.
    conocidas = declaradas | {"up"}

    desconocidas: list[str] = []
    for regla in reglas:
        for usada in re.findall(r"\b(crm_[a-z_]+)\b", regla.get("expr", "")):
            # Los histogramas se consultan con el sufijo `_bucket`, que Prometheus
            # genera y el código no nombra.
            base = usada[: -len("_bucket")] if usada.endswith("_bucket") else usada
            if base not in conocidas:
                desconocidas.append(f"{regla.get('alert')}: {usada}")
    assert not desconocidas, f"Alertas sobre métricas que no se publican: {desconocidas}"
