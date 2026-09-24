#!/usr/bin/env python3
"""Dibuja los procesos del CRM de extremo a extremo, con sus entradas y salidas.

    python scripts/gen_procesos.py            # escribe docs/procesos.md
    python scripts/gen_procesos.py --check    # falla si está desfasado

**Generado, no escrito a mano.** Un documento de procesos escrito a mano dice lo
que alguien creyó que pasaba el día que lo escribió, y a partir de ahí va
mintiendo: cada operación nueva, cada evento y cada transición lo dejan un poco
más lejos de la verdad, y nadie se entera porque un documento no falla.

Aquí cada pieza sale de donde de verdad vive:

* **Qué se puede pedir y qué se devuelve**, del contrato OpenAPI de cada
  servicio.
* **Qué eventos dispara cada operación**, leyendo el código: se sigue quién
  llama a quién desde la función que atiende la ruta hasta el `emitir(...)`.
* **Quién reacciona a cada evento**, de las suscripciones que declara cada
  servicio al arrancar.
* **Por qué estados pasa cada cosa**, de las máquinas de estado registradas.

Lo que no se puede derivar no se inventa: si una operación no emite nada, aquí
sale sin eventos, y eso también es información.
"""

from __future__ import annotations

import argparse
import ast
import importlib
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
SALIDA = RAIZ / "docs" / "procesos.md"

SERVICIOS = [
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
]

# Hasta dónde se sigue la cadena de llamadas buscando el `emitir`. Tres saltos
# cubren «ruta → servicio → ayudante»; más produce ruido, porque a esa distancia
# la relación deja de ser «esta operación dispara esto».
SALTOS = 3


def _app(servicio: str) -> Any:
    from crmcore.config import limpiar_cache_settings

    os.environ["SERVICE_NAME"] = servicio
    os.environ.setdefault("ENV", "dev")
    limpiar_cache_settings()
    return importlib.import_module(f"services.{servicio}.main").app


class _Analisis(ast.NodeVisitor):
    """Qué emite cada función y a quién llama, en un fichero."""

    def __init__(self) -> None:
        self.emite: dict[str, set[str]] = defaultdict(set)
        # `{funcion: {(alias o "", nombre)}}`. El alias es el del import
        # —`svc.abrir_caso` guarda `("svc", "abrir_caso")`— y es lo que permite
        # saber a QUÉ módulo va la llamada cuando dos módulos tienen una función
        # con el mismo nombre, que pasa a menudo.
        self.llama: dict[str, set[tuple[str, str]]] = defaultdict(set)
        self.alias: dict[str, str] = {}
        self._funcion: list[str] = []

    def visit_ImportFrom(self, nodo: ast.ImportFrom) -> None:  # noqa: N802
        modulo = (nodo.module or "").rsplit(".", 1)[-1]
        for alias in nodo.names:
            # `from services.x import servicio as svc` → svc apunta a `servicio`
            self.alias[alias.asname or alias.name] = alias.name
            if modulo and not alias.asname:
                self.alias.setdefault(alias.name, alias.name)
        self.generic_visit(nodo)

    def _entrar(self, nodo: Any) -> None:
        self._funcion.append(nodo.name)
        self.generic_visit(nodo)
        self._funcion.pop()

    visit_FunctionDef = _entrar  # noqa: N815
    visit_AsyncFunctionDef = _entrar  # noqa: N815

    def visit_Call(self, nodo: ast.Call) -> None:  # noqa: N802
        if self._funcion:
            actual = self._funcion[-1]
            alias, nombre = _llamado(nodo.func)
            if nombre:
                self.llama[actual].add((alias, nombre))
            if nombre == "emitir" and nodo.args:
                self.emite[actual] |= _literales(nodo.args[0])
        self.generic_visit(nodo)


def _literales(nodo: ast.expr) -> set[str]:
    """Los tipos de evento que puede ser esta expresión.

    No siempre es un literal: `emitir("opportunity.won" if ganada else
    "opportunity.lost")` es una sola llamada que emite dos hechos distintos.
    Mirando solo constantes, ese emisor —y el cierre de una oportunidad con
    él— no aparecía en ninguna parte del documento.
    """
    if isinstance(nodo, ast.Constant):
        return {nodo.value} if isinstance(nodo.value, str) else set()
    if isinstance(nodo, ast.IfExp):
        return _literales(nodo.body) | _literales(nodo.orelse)
    return set()


def _llamado(nodo: ast.expr) -> tuple[str, str]:
    """`(alias, nombre)` de una llamada. El alias va vacío si no lo lleva."""
    if isinstance(nodo, ast.Name):
        return "", nodo.id
    if isinstance(nodo, ast.Attribute):
        if isinstance(nodo.value, ast.Name):
            return nodo.value.id, nodo.attr
        return "", nodo.attr
    return "", ""


def _mapa_del_servicio(servicio: str) -> tuple[dict, dict, dict]:
    """Qué emite y a quién llama cada función, **con su módulo**.

    Con el módulo y no solo el nombre: media docena de módulos tienen una
    función `crear`, y juntándolas el documento decía que dar de alta una
    cadencia emite `quote.created`. Una atribución falsa hace este documento
    peor que no tenerlo, porque se lee como si fuera cierta.
    """
    emite: dict[tuple[str, str], set[str]] = defaultdict(set)
    llama: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
    donde: dict[str, set[str]] = defaultdict(set)
    alias: dict[str, dict[str, str]] = {}
    # También `crmcore`: los routers compartidos —comentarios, papelera,
    # adjuntos— emiten hechos que ninguna operación parecía disparar, porque el
    # código está fuera del servicio aunque las rutas las monte él.
    ficheros = sorted((RAIZ / "services" / servicio).glob("*.py")) + sorted(
        (RAIZ / "packages" / "crmcore" / "crmcore").rglob("*.py")
    )
    modulos = {f.stem for f in ficheros}
    for fichero in ficheros:
        modulo = fichero.stem
        analisis = _Analisis()
        analisis.visit(ast.parse(fichero.read_text(encoding="utf-8")))
        for f, tipos in analisis.emite.items():
            emite[(modulo, f)] |= tipos
        for f, destinos in analisis.llama.items():
            llama[(modulo, f)] |= destinos
        for f in set(analisis.emite) | set(analisis.llama):
            donde[f].add(modulo)
        alias[modulo] = {a: m for a, m in analisis.alias.items() if m in modulos}
    return emite, llama, donde, alias


def _eventos_de(
    inicio: tuple[str, str], emite: dict, llama: dict, donde: dict, alias: dict
) -> set[str]:
    """Los eventos que dispara una operación, siguiendo a quién llama.

    Al seguir una llamada se busca primero en el **mismo módulo**; si no está,
    solo se salta cuando ese nombre existe en un único sitio del servicio. Con
    el nombre en dos módulos no se adivina: se corta ahí. Una cadena de más se
    lee como un hecho y no lo es.
    """
    vistos: set[tuple[str, str]] = set()
    tipos: set[str] = set()
    frontera = {inicio}
    for _ in range(SALTOS):
        siguiente: set[tuple[str, str]] = set()
        for clave in frontera:
            if clave in vistos:
                continue
            vistos.add(clave)
            tipos |= emite.get(clave, set())
            modulo, actual = clave
            for como, nombre in llama.get(clave, set()):
                # Si la llamada lleva alias —`svc.abrir_caso`— el módulo lo dice
                # el import, y no hay nada que adivinar. Es lo que resuelve los
                # casos en que dos módulos tienen una función con el mismo
                # nombre, que es donde antes se cortaba la cadena.
                destino = alias.get(modulo, {}).get(como) if como else None
                if destino:
                    siguiente.add((destino, nombre))
                    continue
                # El mismo módulo primero, **salvo que sea ella misma**: la
                # función que atiende la ruta se llama igual que la del
                # servicio a la que llama —`cambiar_etapa` llama a
                # `svc.cambiar_etapa`—, y resolviéndolo en el propio módulo se
                # seguía a sí misma y la cadena no salía de ahí. Ahí se perdía
                # el cierre de una oportunidad entero.
                if nombre != actual and ((modulo, nombre) in emite or (modulo, nombre) in llama):
                    siguiente.add((modulo, nombre))
                    continue
                candidatos = donde.get(nombre, set()) - {modulo}
                if len(candidatos) == 1:
                    siguiente.add((next(iter(candidatos)), nombre))
        frontera = siguiente - vistos
        if not frontera:
            break
    return tipos


SUSCRIPCION = re.compile(r'\(\s*"([^"]+)"\s*,\s*(\w+)\s*,', re.S)


def _suscripciones(servicio: str) -> list[tuple[str, str]]:
    """`(patrón de evento, función)` de lo que este servicio escucha."""
    principal = RAIZ / "services" / servicio / "main.py"
    if not principal.exists():
        return []
    texto = principal.read_text(encoding="utf-8")
    bloque = re.search(r"suscripciones\s*=\s*\[(.*?)\n\s*\]", texto, re.S)
    if not bloque:
        return []
    return [(m.group(1), m.group(2)) for m in SUSCRIPCION.finditer(bloque.group(1))]


def _campos_de(documento: dict, esquema: dict | None) -> list[str]:
    """Los campos de un cuerpo, resueltos si vienen por referencia."""
    if not esquema:
        return []
    if "$ref" in esquema:
        nombre = esquema["$ref"].split("/")[-1]
        esquema = (documento.get("components", {}).get("schemas") or {}).get(nombre, {})
    obligatorios = set(esquema.get("required") or [])
    return [
        f"{campo}*" if campo in obligatorios else campo
        for campo in (esquema.get("properties") or {})
    ]


def _entrada_salida(documento: dict, operacion: dict) -> tuple[str, str]:
    cuerpo = (
        (operacion.get("requestBody") or {}).get("content", {}).get("application/json", {})
    ).get("schema")
    campos = _campos_de(documento, cuerpo)
    parametros = [
        f"{p['name']}*" if p.get("required") else p["name"]
        for p in operacion.get("parameters") or []
        if p.get("in") in ("path", "query")
    ]
    entrada = ", ".join(parametros + campos) or "—"
    respuestas = sorted(operacion.get("responses") or {})
    salida = ", ".join(respuestas) or "—"
    return entrada, salida


def _maquinas() -> dict[str, Any]:
    """Las máquinas de estado registradas, importando los servicios que las declaran."""
    for servicio in SERVICIOS:
        for modulo in ("estados", "modelos"):
            try:
                os.environ["SERVICE_NAME"] = servicio
                importlib.import_module(f"services.{servicio}.{modulo}")
            except Exception:  # noqa: BLE001 — un servicio sin ese módulo no es un fallo
                continue
    from crmcore.datos.estados import MAQUINAS

    return dict(MAQUINAS)


def _catalogo_de_eventos() -> dict[str, Any]:
    importlib.import_module("crmcore.events.dominio")
    from crmcore.events.catalogo import todos

    return {t.tipo: t for t in todos()}


def generar() -> str:
    tipos = _catalogo_de_eventos()
    maquinas = _maquinas()

    # Quién escucha qué, para poder decir en cada operación a quién despierta.
    oyentes: dict[str, list[str]] = defaultdict(list)
    for servicio in SERVICIOS:
        for patron, funcion in _suscripciones(servicio):
            oyentes[patron].append(f"{servicio}.{funcion}")

    def quien_escucha(tipo: str) -> list[str]:
        salida: list[str] = []
        for patron, quienes in oyentes.items():
            expresion = "^" + re.escape(patron).replace(r"\*", "[^.]*") + "$"
            if re.match(expresion, tipo):
                salida.extend(quienes)
        return sorted(set(salida))

    lineas: list[str] = [
        "# Procesos, de extremo a extremo",
        "",
        "> Generado por `scripts/gen_procesos.py`. **No se edita a mano**: cada",
        "> pieza sale del contrato de cada servicio, del código que emite los",
        "> eventos, de las suscripciones declaradas al arrancar y de las máquinas",
        "> de estado registradas. Un documento de procesos escrito a mano dice lo",
        "> que alguien creyó que pasaba el día que lo escribió.",
        "",
        "Cada proceso se lee así: **qué se pide** (entrada), **qué contesta**",
        "(salida), **qué dispara** (eventos) y **a quién despierta** (quién",
        "reacciona). Una operación sin eventos no encadena nada: también es un",
        "dato.",
        "",
    ]

    # ── Máquinas de estado ────────────────────────────────────────────────
    lineas += ["## Por qué estados pasa cada cosa", ""]
    for objeto in sorted(maquinas):
        maquina = maquinas[objeto]
        lineas += [
            f"### {objeto}",
            "",
            f"Empieza en **{maquina.inicial}**."
            + (f" No se sale de: {', '.join(sorted(maquina.finales))}." if maquina.finales else ""),
            "",
            "```mermaid",
            "stateDiagram-v2",
            f"    [*] --> {maquina.inicial}",
        ]
        for desde in sorted(maquina.transiciones):
            for hacia in sorted(maquina.transiciones[desde]):
                lineas.append(f"    {desde} --> {hacia}")
        for final in sorted(maquina.finales):
            lineas.append(f"    {final} --> [*]")
        lineas += ["```", ""]

    # ── Operaciones, servicio a servicio ──────────────────────────────────
    lineas += ["## Qué se puede hacer, y qué desencadena", ""]
    # Qué operación dispara cada evento, para poder decirlo también al revés.
    desde_donde: dict[str, set[str]] = defaultdict(set)
    for servicio in SERVICIOS:
        app = _app(servicio)
        documento = app.openapi()
        emite, llama, donde, alias = _mapa_del_servicio(servicio)
        # De qué función sale cada ruta, preguntándoselo a la propia aplicación:
        # el identificador del OpenAPI trae el nombre pero no el módulo, y el
        # módulo es justo lo que evita confundir dos funciones que se llaman
        # igual.
        # Con el recorrido plano de `crmcore`: esta versión de FastAPI envuelve
        # los routers incluidos, así que `app.routes` devuelve envoltorios sin
        # función detrás y no se podía saber de dónde sale ninguna ruta.
        from crmcore.http.superficie import _rutas_planas

        de_la_ruta: dict[tuple[str, str], tuple[str, str]] = {}
        for prefijo, r in _rutas_planas(app):
            destino = getattr(r, "endpoint", None)
            if destino is None or not getattr(r, "methods", None):
                continue
            modulo = getattr(destino, "__module__", "").rsplit(".", 1)[-1]
            camino = prefijo + getattr(r, "path", "")
            for m in r.methods:
                de_la_ruta[(m.upper(), camino)] = (modulo, destino.__name__)

        filas: list[tuple[str, str, str, str, str]] = []
        for ruta, operaciones in sorted((documento.get("paths") or {}).items()):
            if not ruta.startswith("/api/"):
                continue
            for metodo, operacion in operaciones.items():
                if metodo.upper() not in ("GET", "POST", "PATCH", "PUT", "DELETE"):
                    continue
                origen = de_la_ruta.get((metodo.upper(), ruta))
                eventos = sorted(_eventos_de(origen, emite, llama, donde, alias)) if origen else []
                # Solo lo que cambia algo o dispara algo: un listado no es un
                # proceso, y con los 1.700 dentro el documento no se lee.
                if metodo.upper() == "GET" and not eventos:
                    continue
                entrada, salida = _entrada_salida(documento, operacion)
                despierta = sorted({o for e in eventos for o in quien_escucha(e)})
                for e in eventos:
                    desde_donde[e].add(f"{metodo.upper()} {ruta}")
                filas.append(
                    (
                        f"`{metodo.upper()} {ruta}`",
                        operacion.get("summary") or "",
                        entrada,
                        salida,
                        ", ".join(f"`{e}`" for e in eventos) or "—",
                    )
                )
                if despierta:
                    filas[-1] = (*filas[-1][:4], filas[-1][4] + " → " + ", ".join(despierta))

        if not filas:
            continue
        lineas += [
            f"### {servicio}",
            "",
            "| Operación | Qué hace | Entrada | Respuestas | Dispara → despierta a |",
            "| --- | --- | --- | --- | --- |",
        ]
        for fila in filas:
            lineas.append("| " + " | ".join(c.replace("|", "\\|") for c in fila) + " |")
        lineas.append("")

    # ── Mapa de eventos ───────────────────────────────────────────────────
    lineas += [
        "## El mapa de eventos",
        "",
        "Quién produce cada hecho, qué lo dispara y quién reacciona. Lo que no",
        "tiene a nadie escuchando no está roto: está disponible para quien quiera",
        "integrarse. Y lo que no tiene ninguna operación detrás **lo dispara un",
        "proceso de fondo** —un trabajo programado, un consumidor—, no una",
        "llamada de nadie.",
        "",
        "| Evento | Lo produce | Campos | Lo dispara | Reacciona |",
        "| --- | --- | --- | --- | --- |",
    ]
    for tipo in sorted(tipos):
        definicion = tipos[tipo]
        escuchan = quien_escucha(tipo)
        origenes = sorted(desde_donde.get(tipo, set()))
        lineas.append(
            f"| `{tipo}` | {definicion.productor} | "
            f"{', '.join(definicion.campos) or '—'} | "
            + (", ".join(f"`{o}`" for o in origenes[:3]) if origenes else "un proceso de fondo")
            + (f" (+{len(origenes) - 3})" if len(origenes) > 3 else "")
            + f" | {', '.join(escuchan) or '—'} |"
        )
    lineas.append("")
    return "\n".join(lineas)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="solo comprobar que está al día")
    args = parser.parse_args()

    texto = generar()
    if args.check:
        if not SALIDA.exists() or SALIDA.read_text(encoding="utf-8") != texto:
            print(
                "docs/procesos.md está desfasado respecto del código.\n"
                "Regenéralo:  python scripts/gen_procesos.py",
                file=sys.stderr,
            )
            return 1
        print("docs/procesos.md al día")
        return 0

    SALIDA.write_text(texto, encoding="utf-8")
    print(f"Escrito {SALIDA.relative_to(RAIZ)} ({len(texto.splitlines())} líneas)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
