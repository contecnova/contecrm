"""Las rutas que el front declara existen en la API, con su método.

El front no escribe un formulario por recurso: declara en `recursos.ts` de dónde
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

MODULOS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "recursos.ts"

# Una entrada de `recursos.ts` es un objeto sin objetos dentro: `{ nombre: "…",
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
        # Una colección que vive en varios servicios declara cuáles y su ruta
        # lleva `:servicio`. Se comprueban TODOS: si sólo se mirara el primero,
        # añadir un servicio a la lista que no publique esa ruta dejaría una
        # opción del selector que siempre da 404, y nadie lo cazaría.
        servicios = re.search(r"por_servicio:\s*\[([^\]]*)\]", bloque)
        cuales = re.findall(r'"([^"]+)"', servicios.group(1)) if servicios else [servicio]
        for suyo in cuales:
            if listar := campo(bloque, "listar"):
                salida.append((nombre, suyo, listar.replace(":servicio", suyo), "get"))
            if crear := campo(bloque, "crear"):
                salida.append((nombre, suyo, crear.replace(":servicio", suyo), "post"))
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

    `recursos.ts` tenía 110 listados y 22 altas al escribir esto. El suelo va por
    debajo para que quitar pantallas a propósito no lo rompa, y lo bastante
    cerca para que un cambio de formato que deje de leer el fichero sí lo haga.
    """
    total = len(_declaraciones())
    assert (
        total > 100
    ), f"solo se leen {total} declaraciones de recursos.ts; el gate no está mirando"


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
# Lo de arriba comprueba lo que se declara en `recursos.ts`. Pero hay veinte
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
    # La búsqueda global: la compone el gateway preguntando a los índices de
    # cada servicio, así que no está en el contrato de ninguno.
    "/api/v1/buscar",
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


# ── Nadie teclea un identificador a mano ──────────────────────────────────

_PERSONAS = re.compile(r"const SON_PERSONAS = new Set\(\[(.*?)\]\)", re.S)
_MISMO_TIPO = re.compile(r"const SON_DEL_MISMO_TIPO = new Set\(\[(.*?)\]\)", re.S)


def _campos_resolubles() -> tuple[set[str], set[str], set[str]]:
    """Qué sabe resolver el front: objetos declarados, personas y autorreferencias."""
    referencias = (FRONT_SRC / "lib" / "referencias.ts").read_text(encoding="utf-8")
    objetos = set(re.findall(r'objeto:\s*"([^"]+)"', MODULOS.read_text(encoding="utf-8")))
    personas = set(re.findall(r'"([^"]+)"', (_PERSONAS.search(referencias) or [""])[1] or ""))
    mismo = set(re.findall(r'"([^"]+)"', (_MISMO_TIPO.search(referencias) or [""])[1] or ""))
    return objetos, personas, mismo


def test_ningun_formulario_pide_un_identificador_a_mano() -> None:
    """Un campo que apunta a otro registro se **elige**, no se teclea.

    `01a0cfbd-62b6-7a9b-8c98-f2bb8230cfd5` en una caja de texto no es un
    formulario: es un volcado de la base de datos con una etiqueta encima. Nadie
    se sabe un UUID, así que el campo o se deja vacío o se rellena copiando de
    otra pantalla —y una copia mal hecha apunta a otro registro sin avisar.

    El front resuelve tres casos: el objeto declarado en `recursos.ts`
    (`cuenta_id` → cuentas), los campos que son personas (`owner_id`) y los que
    apuntan al mismo tipo (`padre_id`). Lo que no encaje en ninguno **tiene que
    declararlo la columna** con `info={"referencia": "..."}`; si no, sale como
    un identificador a la vista.
    """
    objetos, personas, mismo_tipo = _campos_resolubles()
    sueltos: list[str] = []
    for servicio in SERVICIOS:
        import importlib

        from crmcore.config import limpiar_cache_settings

        os.environ["SERVICE_NAME"] = servicio
        limpiar_cache_settings()
        documento = importlib.import_module(f"services.{servicio}.main").app.openapi()
        esquemas = documento.get("components", {}).get("schemas") or {}
        for nombre, esquema in esquemas.items():
            if not nombre.startswith("Editar"):
                continue
            for campo, propiedad in (esquema.get("properties") or {}).items():
                if not campo.endswith("_id"):
                    continue
                if propiedad.get("referencia") or campo in personas or campo in mismo_tipo:
                    continue
                if campo[: -len("_id")] in objetos:
                    continue
                sueltos.append(f"{servicio}.{nombre[len('Editar') :]}.{campo}")

    assert not sueltos, (
        "Formularios que piden un identificador a mano:\n  "
        + "\n  ".join(sorted(sueltos))
        + '\n\nDeclara a qué apunta la columna —`info={"referencia": "contacto"}`— '
        "o el `objeto` del recurso en `recursos.ts`. Si lo pone el sistema y no una "
        "persona, sácalo del formulario con `NO_EDITABLES`."
    )
