"""Las rutas que el front declara existen en la API, con su método.

El front no escribe un formulario por recurso: declara en `modulos.ts` de dónde
se lista y a dónde se crea cada cosa, y saca los campos del OpenAPI del servicio
dueño. Eso funciona mientras las dos partes digan la misma ruta.

Cuando no coinciden no se rompe nada de forma visible: la base de conocimiento
listaba en `/conocimiento/articulos` y creaba en `/conocimiento`, así que el
listado salía —vacío, porque nunca se pudo crear un artículo— y el botón
«Nuevo» abría un formulario vacío que al enviarse contestaba 405. Una pantalla
que no falla y no funciona es peor que una que falla.

Este gate lee las declaraciones del front y las comprueba contra el contrato
real de cada servicio.
"""

from __future__ import annotations

import importlib
import os
import re
from pathlib import Path

import pytest

MODULOS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "modulos.ts"

# Una entrada de `modulos.ts` es un objeto sin objetos dentro: `{ nombre: "…",
# listar: "…", servicio: "…" }`. Se leen con expresión regular y no importando
# el módulo porque es TypeScript; a cambio, el gate de abajo exige un recuento
# mínimo, para que un cambio de formato que deje de encontrar entradas se note.
ENTRADA = re.compile(r"\{[^{}]*?\}", re.S)


def _declaraciones() -> list[tuple[str, str, str, str]]:
    """`(nombre, servicio, ruta, método)` por cada listado y cada alta del front."""
    salida: list[tuple[str, str, str, str]] = []

    def campo(bloque: str, nombre: str) -> str | None:
        hallado = re.search(rf'{nombre}:\s*"([^"]+)"', bloque)
        return hallado.group(1) if hallado else None

    for bloque in ENTRADA.findall(MODULOS.read_text(encoding="utf-8")):
        servicio = campo(bloque, "servicio")
        if not servicio:
            continue
        nombre = campo(bloque, "nombre") or "(sin nombre)"
        if listar := campo(bloque, "listar"):
            salida.append((nombre, servicio, listar, "get"))
        if crear := campo(bloque, "crear"):
            salida.append((nombre, servicio, crear, "post"))
    return salida


def _contrato(servicio: str) -> dict:
    from crmcore.config import limpiar_cache_settings

    os.environ["SERVICE_NAME"] = servicio
    limpiar_cache_settings()
    return importlib.import_module(f"services.{servicio}.main").app.openapi().get("paths") or {}


@pytest.fixture(autouse=True)
def _devolver_el_servicio():
    """Deja `SERVICE_NAME` como estaba, para no contaminar el resto de la suite."""
    from crmcore.config import limpiar_cache_settings

    previo = os.environ.get("SERVICE_NAME")
    try:
        yield
    finally:
        if previo is None:
            os.environ.pop("SERVICE_NAME", None)
        else:
            os.environ["SERVICE_NAME"] = previo
        limpiar_cache_settings()


def _plantilla(paths: dict, ruta: str) -> str | None:
    """Con qué plantilla del contrato se corresponde una ruta concreta.

    La misma regla que usa el front (`lib/contrato.ts`), y tiene que ser la
    misma: si aquí se comparara literalmente, el gate daría por rota una
    pantalla que funciona —`/sales/vocabularios/motivos_perdida` se declara como
    `/sales/vocabularios/{nombre}`— y la forma de callarlo sería declarar mal la
    pantalla.
    """
    if ruta in paths:
        return ruta
    tramos = ruta.split("?")[0].split("/")
    mejor, menos = None, len(tramos) + 1
    for candidata in paths:
        suyos = candidata.split("/")
        if len(suyos) != len(tramos):
            continue
        parametros = sum(1 for t in suyos if t.startswith("{") and t.endswith("}"))
        encaja = all(
            (suyo.startswith("{") and suyo.endswith("}")) or suyo == mio
            for suyo, mio in zip(suyos, tramos, strict=True)
        )
        if encaja and parametros < menos:
            mejor, menos = candidata, parametros
    return mejor


def test_cada_pantalla_apunta_a_una_operacion_que_existe() -> None:
    declaradas = _declaraciones()
    contratos: dict[str, dict] = {}
    rotas: list[str] = []
    for nombre, servicio, ruta, metodo in declaradas:
        if servicio not in contratos:
            contratos[servicio] = _contrato(servicio)
        plantilla = _plantilla(contratos[servicio], ruta)
        ops = (contratos[servicio].get(plantilla) if plantilla else None) or {}
        if metodo not in ops:
            tiene = ",".join(sorted(ops)) or "la ruta no existe"
            rotas.append(f"{nombre} [{servicio}] {metodo.upper()} {ruta} → {tiene}")

    assert not rotas, "El front pide operaciones que la API no tiene:\n  " + "\n  ".join(rotas)


def test_el_gate_ve_las_pantallas() -> None:
    """Un gate que no encuentra declaraciones pasa siempre.

    `modulos.ts` tenía 110 listados y 22 altas al escribir esto. El suelo va por
    debajo para que quitar pantallas a propósito no lo rompa, y lo bastante
    cerca para que un cambio de formato que deje de leer el fichero sí lo haga.
    """
    total = len(_declaraciones())
    assert total > 100, f"solo se leen {total} declaraciones de modulos.ts; el gate no está mirando"


def test_lo_que_se_lista_se_puede_abrir() -> None:
    """Una colección con acciones sobre un registro tiene ficha.

    Las acciones de un registro —enviar una oferta, aceptarla, inscribir en una
    cadencia, levantar un bloqueo— se ofrecen desde su ficha, y la ficha se
    abre con `GET /coleccion/{id}`. Sin esa ruta no hay por dónde llegar:
    treinta y cuatro recursos publicaban ochenta acciones que no aparecían en
    ninguna pantalla, y la que sí enlazaba contestaba 404.

    Se mira solo lo que el front declara: una colección interna sin pantalla no
    necesita ficha, y exigírsela sería trabajo por el trabajo.
    """
    import re as _re

    declaradas = {(s, r) for _, s, r, metodo in _declaraciones() if metodo == "get"}
    contratos: dict[str, dict] = {}
    huerfanas: list[str] = []
    for servicio, listar in sorted(declaradas):
        if servicio not in contratos:
            contratos[servicio] = _contrato(servicio)
        paths = contratos[servicio]
        if listar not in paths:
            continue
        ficha = any(_re.fullmatch(_re.escape(listar) + r"/\{[a-z_]+\}", p) for p in paths)
        acciones = [
            p
            for p in paths
            if p.startswith(listar + "/{") and p.count("/") == listar.count("/") + 2
        ]
        if not ficha and acciones:
            huerfanas.append(f"{listar} [{servicio}]: {len(acciones)} acciones y ninguna ficha")

    assert not huerfanas, (
        "Colecciones con acciones sobre un registro y sin ficha desde la que "
        "llegar a ellas:\n  " + "\n  ".join(huerfanas)
    )


# ── Las pantallas escritas a mano ─────────────────────────────────────────
#
# Lo de arriba comprueba lo que se declara en `modulos.ts`. Pero hay veinte
# pantallas escritas a mano —el tablero, la consola de agente, el puesto, la
# suite— que llaman a la API directamente, y esas no las miraba nadie: una ruta
# mal escrita ahí solo se descubre abriendo la pantalla, y algunas se abren poco.

LLAMADA = re.compile(r'llamar[^(]*\(\s*[`"](/api/v1/[^`"]*)[`"](?P<resto>[^)]*)', re.S)
FRONT_SRC = MODULOS.parents[1]

# Los trece servicios que publican contrato. Se listan aquí porque el gate de
# abajo tiene que mirarlos todos: una pantalla no sabe —ni debe— de qué servicio
# sale cada ruta, y el gateway la enruta por ella.
SERVICIOS = (
    "tenancy",
    "identity",
    "metadata",
    "orchestrator",
    "automation",
    "integration",
    "eventing",
    "party",
    "sales",
    "analytics",
    "intelligence",
    "service",
    "marketing",
)

# Rutas que el front pide **a propósito** sabiendo que pueden no existir, o que
# sirve el propio gateway y no un servicio.
_DEL_GATEWAY = {
    "/api/v1/sesion/entrar",
    "/api/v1/sesion/renovar",
    "/api/v1/sesion/salir",
    "/api/v1/superficie",
    "/api/v1/servicios",
    "/api/v1/estado",
    "/api/v1/salud",
}

# Y las que el gateway sirve con un tramo variable dentro.
_DEL_GATEWAY_CON_PARAMETRO = ("/api/v1/contrato/",)


def _llamadas_escritas_a_mano() -> list[tuple[str, str, str]]:
    """`(fichero, ruta, método)` de cada `llamar()` del front."""
    salida: list[tuple[str, str, str]] = []
    for fichero in sorted(FRONT_SRC.rglob("*.tsx")) + sorted(FRONT_SRC.rglob("*.ts")):
        if fichero.name.endswith(".test.ts"):
            continue
        for encontrada in LLAMADA.finditer(fichero.read_text(encoding="utf-8")):
            ruta = encontrada.group(1)
            if ruta.split("?")[0] in _DEL_GATEWAY:
                continue
            if ruta.startswith(_DEL_GATEWAY_CON_PARAMETRO):
                continue
            metodo = re.search(r'metodo:\s*"(\w+)"', encontrada.group("resto"))
            salida.append((fichero.name, ruta, (metodo.group(1) if metodo else "GET").lower()))
    return salida


def _encaja(plantilla: str, concreta: str) -> bool:
    """¿La ruta que pide el front es esta plantilla del contrato?

    Los tramos `${...}` del front y los `{...}` del contrato valen por
    cualquiera; el resto tiene que coincidir. Sin esto no se podría comprobar
    ninguna ruta que lleve un identificador dentro, que son la mitad.
    """
    a, b = plantilla.split("/"), concreta.split("?")[0].split("/")
    if len(a) != len(b):
        return False
    for tp, tf in zip(a, b, strict=True):
        if tp.startswith("{") or tf.startswith("${") or "${" in tf:
            continue
        if tp != tf:
            return False
    return True


def test_toda_llamada_del_front_existe_en_algun_contrato() -> None:
    """Ninguna pantalla pide algo que la API no tenga.

    Se comprueba **con el método que usa**: una ruta que existe para `GET` y se
    pide con `POST` responde 405, y en pantalla eso sale como «algo ha ido mal»
    sin decir qué.
    """
    contratos = {servicio: _contrato(servicio) for servicio in SERVICIOS}
    rotas: list[str] = []
    for fichero, ruta, metodo in _llamadas_escritas_a_mano():
        alcanzada = False
        for paths in contratos.values():
            for plantilla, operaciones in paths.items():
                if _encaja(plantilla, ruta) and metodo in operaciones:
                    alcanzada = True
                    break
            if alcanzada:
                break
        if not alcanzada:
            rotas.append(f"{fichero}: {metodo.upper()} {ruta}")

    assert not rotas, (
        "Pantallas que piden algo que la API no tiene:\n  "
        + "\n  ".join(dict.fromkeys(rotas))
        + "\n\nEn pantalla esto sale como «algo ha ido mal», sin decir qué falta."
    )
