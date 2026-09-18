"""RT-4: la explotación del dato no se reimplementa aquí.

Informes, cuadros de mando, consultas analíticas y preguntas en lenguaje natural
los resuelve **contecintelligence**, consumido de forma frontless: contecrm pone
las pantallas y el contexto, y las consultas las responde su API delegada con el
tenant, el usuario y sus permisos propagados. El usuario no sale del CRM.

Este gate existe porque una decisión así se incumple sola. No hace falta mala fe:
basta que alguien necesite «un informe rápido» y escriba un generador de SQL en
un rincón. Al año hay dos motores de explotación, ninguno de los dos completo, y
el modelo semántico dice cosas distintas según por dónde se pregunte.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[2]
CATALOGO = RAIZ / "docs" / "catalogo" / "catalogo.yaml"

# Las funciones cuya explotación está delegada. Se nombran por su identificador
# y no por su texto: el texto se puede reescribir sin darse cuenta, el
# identificador no.
FUNCIONES_DELEGADAS = ("CRM-05.01.01", "CRM-05.01.02")

# Nombres de módulo que delatan un motor propio de explotación. La lista es de
# nombres y no de contenidos a propósito: lo que se quiere impedir es que
# **empiece**, y empieza siempre por crear el fichero.
NOMBRES_PROHIBIDOS = {
    "motor_informes.py",
    "generador_sql.py",
    "constructor_informes.py",
    "report_engine.py",
    "query_builder.py",
}


@pytest.fixture(scope="module")
def catalogo() -> dict:
    return yaml.safe_load(CATALOGO.read_text(encoding="utf-8"))


def test_la_restriccion_esta_declarada(catalogo: dict) -> None:
    ids = {r["id"] for r in catalogo["restricciones_transversales"]}
    assert "RT-4" in ids, (
        "RT-4 ha desaparecido del catálogo. La delegación de la explotación en "
        "contecintelligence es un requisito, no una preferencia."
    )


def test_las_capacidades_de_explotacion_se_declaran_delegadas(catalogo: dict) -> None:
    """Cada capacidad de informes y cuadros de mando dice de dónde sale.

    Sin esta marca, quien coja la capacidad para implementarla no tiene forma de
    saber que no hay que escribirla: el enunciado, leído solo, pide construir un
    motor de informes.
    """
    sin_marcar: list[str] = []
    for modulo in catalogo["modulos"]:
        for seccion in modulo["secciones"]:
            for funcion in seccion["funciones"]:
                if funcion["id"] not in FUNCIONES_DELEGADAS:
                    continue
                for cap in funcion["capacidades"]:
                    if "contecintelligence" not in str(cap.get("reutiliza", "")):
                        sin_marcar.append(cap["id"])

    assert not sin_marcar, (
        "Capacidades de explotación sin declarar que se delegan en "
        "contecintelligence:\n  " + "\n  ".join(sin_marcar)
    )


def test_la_integracion_esta_en_el_catalogo(catalogo: dict) -> None:
    """Delegar no es no hacer nada: la integración es trabajo, y está declarada."""
    ids = {
        c["id"]
        for m in catalogo["modulos"]
        for s in m["secciones"]
        for f in s["funciones"]
        for c in f["capacidades"]
        if f["id"] == "CRM-05.01.04"
    }
    assert len(ids) >= 5, "Falta el grupo de capacidades de la integración (CRM-05.01.04)"


def test_no_hay_un_motor_de_informes_propio() -> None:
    """Lo que se quiere impedir es que empiece, y empieza por crear el fichero."""
    encontrados = [
        str(f.relative_to(RAIZ))
        for f in (RAIZ / "services").rglob("*.py")
        if f.name in NOMBRES_PROHIBIDOS
    ]
    assert not encontrados, (
        "Hay módulos que parecen un motor de explotación propio:\n  "
        + "\n  ".join(encontrados)
        + "\n\nLa explotación la resuelve contecintelligence (RT-4). Si de verdad "
        "hace falta algo que su API no cubre, lo que toca es ampliarla ahí, no "
        "empezar un segundo motor aquí."
    )


def test_nadie_escribe_sql_a_partir_de_texto_del_usuario() -> None:
    """La consulta en lenguaje natural la traduce contecintelligence.

    Aquí se busca el patrón que la delataría: componer SQL concatenando algo que
    viene de una petición. Además de duplicar el motor, es la vía directa a una
    inyección, porque quien lo escribe deprisa no parametriza.
    """
    sospechosas: list[str] = []
    patron = re.compile(r'(f"|f\')\s*SELECT\s', re.IGNORECASE)
    for fichero in (RAIZ / "services").rglob("*.py"):
        if "__pycache__" in str(fichero):
            continue
        for numero, linea in enumerate(fichero.read_text(encoding="utf-8").splitlines(), 1):
            if patron.search(linea):
                sospechosas.append(f"{fichero.relative_to(RAIZ)}:{numero}")

    assert not sospechosas, "SQL compuesto por interpolación de texto:\n  " + "\n  ".join(
        sospechosas
    )
