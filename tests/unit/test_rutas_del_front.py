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


def test_cada_pantalla_apunta_a_una_operacion_que_existe() -> None:
    declaradas = _declaraciones()
    contratos: dict[str, dict] = {}
    rotas: list[str] = []
    for nombre, servicio, ruta, metodo in declaradas:
        if servicio not in contratos:
            contratos[servicio] = _contrato(servicio)
        ops = contratos[servicio].get(ruta) or {}
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
