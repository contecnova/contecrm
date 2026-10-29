"""Los dos manuales completos se comprueban solos
(CRM-07.05.01.06, CRM-07.05.02.06).

Un manual que nadie comprueba se queda viejo en tres meses y entonces **miente**,
que es peor que no tenerlo: el lector se fía. Estos dos gates no comprueban que
esté bien escrito —eso no lo puede comprobar una máquina— sino las dos formas de
quedarse viejo que sí son detectables:

**El manual de usuario deja de cubrir un área.** Se añade una sección funcional
nueva al catálogo, nadie escribe su capítulo, y el manual sigue pareciendo
completo porque nada falla.

**Y el manual técnico describe algo que ya no existe.** Un ajuste que se renombró,
un script que se borró, una ruta que cambió de sitio. Eso es peor que una omisión:
alguien lo intenta, no funciona, y deja de fiarse del resto del documento.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[2]
MANUAL_USUARIO = RAIZ / "docs" / "manual-usuario.md"
MANUAL_TECNICO = RAIZ / "docs" / "manual-tecnico.md"

# Servicios cuyas capacidades no son de cara al usuario: infraestructura,
# operación y documentación. Un capítulo de manual de usuario sobre «escalado
# horizontal por servicio» no lo lee nadie que use el CRM.
SIN_CARA_AL_USUARIO = {"infra", "ops", "docs"}


@pytest.fixture(scope="module")
def catalogo() -> dict:
    ruta = RAIZ / "docs" / "catalogo" / "catalogo.yaml"
    return yaml.safe_load(ruta.read_text(encoding="utf-8"))


def test_los_dos_manuales_existen_y_son_independientes() -> None:
    """Independientes de verdad: cada uno se puede leer entero sin el otro.

    Se comprueba lo único comprobable de eso —que ninguno dice «esto está
    explicado en el otro» para algo esencial— por la vía de exigir que los dos
    tengan sus propias partes completas. Un manual que delega su capítulo de
    configuración en el otro no es independiente, es media documentación.
    """
    assert MANUAL_USUARIO.exists(), "Falta el manual de usuario"
    assert MANUAL_TECNICO.exists(), "Falta el manual técnico"

    usuario = MANUAL_USUARIO.read_text(encoding="utf-8")
    tecnico = MANUAL_TECNICO.read_text(encoding="utf-8")

    for titulo in ("Casos de uso", "ejemplos", "perfil"):
        assert titulo.lower() in usuario.lower(), (
            f"El manual de usuario no tiene la parte de «{titulo}». Se pidió completo: "
            "funcionalidad, casos de uso y ejemplos."
        )
    for titulo in ("despliega", "Configuración", "Integración", "Operación"):
        assert titulo.lower() in tecnico.lower(), (
            f"El manual técnico no tiene la parte de «{titulo}». Se pidió completo: "
            "configuración, integración y despliegue."
        )


def test_el_manual_de_usuario_cubre_todas_las_areas(catalogo: dict) -> None:
    """Toda sección con capacidades de cara al usuario tiene su capítulo.

    El día que se añade un área funcional nueva —un módulo, una sección— esta
    prueba falla hasta que alguien escriba su capítulo, en vez de que el área
    entre sin documentar y nadie se entere hasta que un cliente pregunte.

    Se busca por el identificador de la sección escrito en el capítulo
    (`sección 3.1`), que es un ancla explícita: buscar por el nombre haría que
    renombrar una sección rompiera el gate sin que faltara nada.
    """
    texto = MANUAL_USUARIO.read_text(encoding="utf-8")
    citadas = set(re.findall(r"secci[óo]n (\d+\.\d+)", texto, re.I))

    faltan: list[str] = []
    for modulo in catalogo["modulos"]:
        for seccion in modulo["secciones"]:
            capacidades = [c for f in seccion["funciones"] for c in f["capacidades"]]
            de_usuario = [c for c in capacidades if str(c.get("svc")) not in SIN_CARA_AL_USUARIO]
            if not de_usuario:
                continue
            if seccion["id"] not in citadas:
                faltan.append(f'{seccion["id"]} — {seccion["nombre"]}')

    assert not faltan, (
        "Áreas funcionales sin capítulo en el manual de usuario:\n  "
        + "\n  ".join(sorted(faltan))
        + "\n\nAñade su capítulo con «(sección X.Y)» en el título, o explica por qué "
        "esa área no tiene nada que contarle a un usuario."
    )


def _todos_los_ajustes() -> set[str]:
    """Los ajustes de **todos** los Settings del producto, no sólo los del base.

    Cinco servicios declaran los suyos en `services/<servicio>/ajustes.py`
    heredando de `Settings`, y hasta el 29-10-2026 este gate solo miraba la
    clase base. Consecuencia: documentar en el manual un ajuste propio de un
    servicio —que es exactamente lo que hay que hacer— ponía el gate en rojo
    diciendo que no existe. Un guardián que da la alarma por lo correcto se
    acaba desactivando, y entonces deja de avisar de lo incorrecto.

    Se importan los módulos y se recorren las subclases en vez de leer una
    lista escrita aquí: una lista a mano se queda corta con el sexto servicio y
    nadie se entera, porque el síntoma es un falso rojo que alguien silencia.
    """
    import importlib

    from crmcore.config import Settings

    raiz = Path(__file__).resolve().parents[2]
    for modulo in sorted((raiz / "services").glob("*/ajustes.py")):
        importlib.import_module(f"services.{modulo.parent.name}.ajustes")

    def _con_hijas(clase: type) -> list[type]:
        return [clase] + [n for h in clase.__subclasses__() for n in _con_hijas(h)]

    clases = _con_hijas(Settings)
    # Suelo medido: si un cambio de estructura dejara de encontrar las de los
    # servicios, el gate volvería a dar falsos rojos sin decir por qué.
    assert len(clases) > 5, f"Solo se han encontrado {len(clases)} clases de ajustes"
    return {campo.upper() for clase in clases for campo in clase.model_fields}


# Verbos HTTP: se escriben en mayúsculas y entre comillas invertidas en todo el
# manual, y los de cinco letras o más pasan el filtro de forma. `PATCH` puso el
# gate en rojo el 29-10-2026 por nombrarlo en una explicación.
VERBOS_HTTP = frozenset({"PATCH", "DELETE", "OPTIONS", "TRACE", "CONNECT"})


def _constantes_del_codigo() -> set[str]:
    """Las constantes de módulo declaradas en el producto.

    Se leen del texto y no importando: importar todo el árbol para esto costaría
    segundos en cada pase y arrastraría efectos de carga que no pintan nada en
    un gate de documentación.
    """
    patron = re.compile(r"^([A-Z][A-Z0-9_]{3,})(?:\s*:[^=]+)?\s*=", re.M)
    nombres: set[str] = set()
    ficheros = 0
    for carpeta in ("packages", "services", "scripts"):
        for fichero in (RAIZ / carpeta).rglob("*.py"):
            ficheros += 1
            nombres |= set(patron.findall(fichero.read_text(encoding="utf-8")))
    # Que diga cuántos ha leído: con cero ficheros, todo lo del manual sería
    # «desconocido» y el gate daría alarma por lo correcto.
    assert ficheros > 300, f"solo se han leído {ficheros} ficheros"
    return nombres


def test_el_manual_tecnico_no_describe_ajustes_que_no_existen() -> None:
    """Un ajuste renombrado o borrado que sigue en el manual es peor que una
    omisión: alguien lo pone en su `.env`, no pasa nada, y deja de fiarse del
    resto del documento.

    Se comprueban los que el manual escribe en mayúsculas con guion bajo, que es
    como se escriben las variables de entorno, contra los `Settings` reales.
    """
    texto = MANUAL_TECNICO.read_text(encoding="utf-8")
    # Los ajustes, **y las constantes del código**. El manual técnico nombra
    # las dos cosas en mayúsculas y entre comillas invertidas, y no hay forma
    # de distinguirlas por la forma: `IA_CREDENCIALES` es un ajuste y
    # `TIPOS_DE_PRINCIPAL` es una tupla de `crmcore.vocabularios`. Lo que este
    # gate tiene que cazar es que el manual nombre algo **que ya no existe**,
    # no que no sea un ajuste.
    conocidos = _todos_los_ajustes() | _constantes_del_codigo()

    # Solo los que aparecen como `CÓDIGO` entre comillas invertidas: el texto
    # normal lleva siglas (API, CRM, SLA) que no son ajustes.
    candidatos = set(re.findall(r"`([A-Z][A-Z0-9_]{4,})`", texto))
    # Los que llevan comodín se comprueban por prefijo: `RATE_LIMIT_*`.
    concretos = {c for c in candidatos if not c.endswith("_")}

    desconocidos = sorted(
        c
        for c in concretos
        if c not in conocidos
        and not any(k.startswith(c.rstrip("*")) for k in conocidos)
        # Palabras que no son ajustes y que salen en un manual técnico.
        # Lo que se escribe en mayúsculas y entre comillas y NO es un ajuste.
        # Los verbos HTTP entran por la forma —`PATCH` tiene cinco letras— y
        # un manual técnico los nombra constantemente.
        and c not in VERBOS_HTTP
        and c not in {"POSTGRESQL", "GRAPHQL", "OPENAPI", "JSONB", "FORCE", "BYOK"}
    )

    assert not desconocidos, (
        "El manual técnico nombra ajustes que no existen en los Settings:\n  "
        + "\n  ".join(desconocidos)
        + "\n\nO se renombraron y el manual se quedó viejo, o nunca existieron. "
        "Las dos cosas hacen que alguien los ponga en su `.env` y no pase nada."
    )


def test_el_manual_tecnico_no_manda_ejecutar_scripts_que_no_estan() -> None:
    """Lo mismo con los comandos: un manual que dice «ejecuta esto» y el fichero
    no está hace perder media hora antes de que alguien sospeche del manual.
    """
    texto = MANUAL_TECNICO.read_text(encoding="utf-8")
    scripts = set(re.findall(r"scripts/([\w_]+\.py)", texto))
    faltan = sorted(s for s in scripts if not (RAIZ / "scripts" / s).exists())
    assert not faltan, "El manual técnico manda ejecutar scripts que no existen:\n  " + "\n  ".join(
        faltan
    )


def test_el_manual_tecnico_no_apunta_a_servicios_inventados() -> None:
    """La tabla de servicios es lo primero que lee alguien nuevo. Si tiene dentro
    uno que ya no está, la lectura entera empieza con una idea falsa del sistema.
    """
    texto = MANUAL_TECNICO.read_text(encoding="utf-8")
    citados = set(
        re.findall(
            r"`(gateway|tenancy|identity|metadata|party|sales|service|"
            r"marketing|intelligence|analytics|integration|orchestrator|"
            r"automation|eventing)`",
            texto,
        )
    )
    reales = {
        d.name for d in (RAIZ / "services").iterdir() if d.is_dir() and not d.name.startswith("_")
    }
    faltan = sorted(citados - reales)
    assert not faltan, "El manual técnico describe servicios que no existen:\n  " + "\n  ".join(
        faltan
    )
