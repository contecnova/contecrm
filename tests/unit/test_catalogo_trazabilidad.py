"""El catálogo funcional y el código no pueden divergir.

`docs/catalogo/catalogo.yaml` dice qué capacidades hay y en qué estado. Si ese
estado se pusiera a mano y nadie lo comprobara, al mes siguiente diría lo que
alguien creyó que había hecho, que es como acaban todas las matrices de
trazabilidad.

Las reglas que fija este gate:

  * Una capacidad **`hecho`** tiene que estar **citada por su ID** en el código o
    en una prueba, y **documentada** en el manual. Sin las dos cosas no está
    hecha: está escrita.
  * Los IDs son únicos y tienen la forma `CRM-MM.SS.FF.nn`.
  * Todo servicio citado en el catálogo existe (o es una etiqueta reconocida).
  * Todo evento del Anexo B está declarado en el catálogo de eventos del código,
    o marcado de una fase posterior.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[2]
CATALOGO = RAIZ / "docs" / "catalogo" / "catalogo.yaml"
RE_ID = re.compile(r"^CRM-\d{2}\.\d{2}\.\d{2}\.\d{2}$")

# Etiquetas de `svc` que no son un servicio desplegable.
# `front` no es un servicio del backend: es la aplicación de referencia, que
# consume la API como un cliente más. Se etiqueta aparte para que en el
# catálogo se distinga de un servicio con esquema propio.
ETIQUETAS = {"core", "infra", "docs", "ops", "front"}
# Servicios previstos en fases posteriores: se admiten en el catálogo antes de
# existir, porque el catálogo es el plan y el plan va por delante del código.
SERVICIOS_FUTUROS = {"party", "sales", "service", "marketing", "analytics", "intelligence"}


@pytest.fixture(scope="module")
def catalogo() -> dict:
    return yaml.safe_load(CATALOGO.read_text(encoding="utf-8"))


def _capacidades(catalogo: dict) -> list[dict]:
    return [
        c
        for m in catalogo["modulos"]
        for s in m["secciones"]
        for f in s["funciones"]
        for c in f["capacidades"]
    ]


def test_los_identificadores_son_validos_y_unicos(catalogo: dict) -> None:
    ids = [c["id"] for c in _capacidades(catalogo)]
    malos = [i for i in ids if not RE_ID.match(i)]
    assert not malos, f"IDs con formato incorrecto: {malos[:10]}"
    repetidos = {i for i in ids if ids.count(i) > 1}
    assert not repetidos, f"IDs repetidos (nunca se reutilizan): {sorted(repetidos)}"


def test_cada_capacidad_declara_estado_valido(catalogo: dict) -> None:
    validos = set(catalogo["estados"])
    malos = [
        f"{c['id']}: {c.get('estado')}"
        for c in _capacidades(catalogo)
        if c.get("estado") not in validos
    ]
    assert not malos, f"Estados no válidos: {malos[:10]}"


def test_los_servicios_citados_existen(catalogo: dict) -> None:
    existentes = {p.name for p in (RAIZ / "services").iterdir() if p.is_dir()}
    desconocidos = sorted(
        {
            c["svc"]
            for c in _capacidades(catalogo)
            if c.get("svc") not in existentes | ETIQUETAS | SERVICIOS_FUTUROS
        }
    )
    assert (
        not desconocidos
    ), f"El catálogo cita servicios que no existen ni están previstos: {desconocidos}"


def test_lo_declarado_hecho_esta_citado_en_el_codigo(catalogo: dict) -> None:
    """Una capacidad `hecho` se cita por su ID en el código o en una prueba.

    Es lo que convierte el catálogo en trazabilidad de verdad: desde el ID se
    llega al sitio donde está implementado o probado. Sin esto, «hecho» es una
    opinión.

    **Las capacidades de `docs` quedan fuera de esta comprobación, y solo esas.**
    Un SLA, una política de soporte o un cuadro de cumplimiento no tienen código
    que citar: el entregable *es* el documento. Exigirles una cita en el código
    llevaría a poner el identificador en un comentario cualquiera para callar al
    gate, que es peor que no comprobarlo — parecería trazado y no lo estaría.
    Siguen sujetas a la comprobación siguiente, que exige que estén escritas en
    un manual a mano.
    """
    fuentes = [
        *(RAIZ / "packages").rglob("*.py"),
        *(RAIZ / "services").rglob("*.py"),
        *(RAIZ / "tests").rglob("*.py"),
        *(RAIZ / "scripts").rglob("*.py"),
        *(RAIZ / "deploy").rglob("*.sql"),
    ]
    texto = "\n".join(
        f.read_text(encoding="utf-8", errors="ignore")
        for f in fuentes
        if "__pycache__" not in str(f)
    )
    sin_citar = [
        c["id"]
        for c in _capacidades(catalogo)
        if c.get("estado") == "hecho" and c.get("svc") != "docs" and c["id"] not in texto
    ]
    assert not sin_citar, (
        "Capacidades marcadas «hecho» que no se citan en ningún sitio del "
        "código:\n  " + "\n  ".join(sin_citar)
    )


def test_lo_declarado_hecho_esta_documentado(catalogo: dict) -> None:
    """Y además está en el manual: sin documentar, no está entregado.

    Se excluyen los documentos GENERADOS del propio catálogo (`docs/catalogo/`):
    contienen todos los identificadores por construcción, así que incluirlos
    haría que esta comprobación se cumpliera sola. Lo que se exige es que la
    capacidad esté explicada en un manual escrito a mano.
    """
    docs = "\n".join(
        f.read_text(encoding="utf-8", errors="ignore")
        for f in (RAIZ / "docs").rglob("*.md")
        if "catalogo" not in f.parts
    )
    sin_documentar = [
        c["id"]
        for c in _capacidades(catalogo)
        if c.get("estado") == "hecho" and c["id"] not in docs
    ]
    assert not sin_documentar, (
        "Capacidades «hecho» que no aparecen en el manual:\n  " + "\n  ".join(sin_documentar)
    )


def test_los_eventos_del_anexo_b_de_fase_0_estan_declarados(catalogo: dict) -> None:
    """Los eventos de la fase 0 tienen que existir en el registro del código.

    El Anexo B es el contrato con los integradores. Un evento prometido y no
    declarado es una integración que nunca recibe nada y un equipo buscando el
    fallo en su lado.
    """
    from crmcore.events.catalogo import todos

    declarados = {t.tipo for t in todos()}
    prometidos_fase_0 = {e["type"] for e in catalogo["anexo_b_eventos"] if e.get("fase") == 0}
    faltan = sorted(prometidos_fase_0 - declarados)
    assert not faltan, f"Eventos de la fase 0 prometidos y no declarados: {faltan}"


def test_el_catalogo_cubre_las_tres_restricciones(catalogo: dict) -> None:
    """Las tres restricciones transversales tienen su gate declarado y existe."""
    for restriccion in catalogo["restricciones_transversales"]:
        gate = RAIZ / restriccion["gate"]
        assert gate.exists(), (
            f"La restricción {restriccion['id']} declara el gate «{restriccion['gate']}» "
            "y ese fichero no existe"
        )


def test_el_front_oficial_cubre_todas_las_secciones(catalogo: dict) -> None:
    """El front estándar tiene que enseñar TODO lo que el sistema hace.

    No es una aspiración de producto: es lo que hace que la solución se pueda
    presentar entera. Una capacidad que solo existe por API es una capacidad que
    nadie ve, y quien mira el producto concluye que no está.

    La cobertura se declara con `cubre:` en cada capacidad del front oficial,
    apuntando a la sección del catálogo que enseña. Así el día que se añade una
    sección funcional nueva —un módulo, un área— esta prueba falla hasta que
    alguien decida qué pantalla la enseña, en vez de que la sección entre sin
    interfaz y nadie se entere hasta una demostración.

    La propia sección del front se excluye: no se enseña a sí misma.
    """
    secciones = {s["id"] for m in catalogo["modulos"] for s in m["secciones"]}
    # `7.4` es el front: no tiene que cubrirse a sí mismo.
    secciones.discard("7.4")

    cubiertas = {
        str(c["cubre"])
        for c in _capacidades(catalogo)
        if c["id"].startswith("CRM-07.04.") and c.get("cubre")
    }

    sin_pantalla = sorted(secciones - cubiertas)
    assert not sin_pantalla, (
        "Secciones del catálogo que el front oficial no declara enseñar:\n  "
        + "\n  ".join(sin_pantalla)
        + '\n\nAñade una capacidad en `CRM-07.04.03` con `cubre: "<sección>"`, o '
        "explica en el manual por qué esa sección no tiene interfaz."
    )

    # Y al revés: una declaración que apunta a una sección que ya no existe es
    # una pantalla prevista para algo que se quitó del catálogo.
    huerfanas = sorted(cubiertas - secciones - {"7.4"})
    assert not huerfanas, (
        "El front declara cubrir secciones que no existen en el catálogo:\n  "
        + "\n  ".join(huerfanas)
    )
