"""Que el filtro común esté escrito no quiere decir que la ruta lo admita.

El trinquete de `test_los_listados_a_mano_tambien_filtran.py` lee el código:
comprueba que cada listado escrito a mano llame a `aplicar_filtros_de_la_url` y
que esté marcado como de parámetros abiertos. Eso es la mitad.

La otra mitad es que **la ruta conteste**. Las dos cosas se separan con
facilidad: con el filtro y sin la marca, la comprobación global de parámetros
desconocidos devuelve 422 a los filtros que la propia ruta acaba de ofrecer; y
un modelo sin tabla, o un parámetro propio que se llame como una columna,
revientan sólo al pedirlo. Nada de eso se ve leyendo el fichero.

Así que esto **recorre las rutas**, una por una, con los veintidós listados que
se arreglaron el 26-10-2026 de una vez. Es un barrido, y los barridos mienten
cuando no miran: por eso dice cuántas rutas ha recorrido y falla si son menos
de las que debería.

Lo que se pide a cada una son tres cosas, que son las tres formas de estar
roto:

  · un filtro por una columna que **no existe** → 422 diciendo cuáles valen. Si
    contestara 200, el filtro se estaría ignorando en silencio y el listado
    devolvería filas de más con cara de estar filtrado;
  · un **operador inventado** → 422. Mismo motivo: aplicar igualdad sobre
    `importe__mayor` devuelve «todos los importes»;
  · y la llamada **sin filtros** → 200, que es lo que comprueba que la marca de
    parámetros abiertos no se haya llevado por delante la ruta.
"""

from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from uuid import UUID, uuid4

import pytest
from starlette.testclient import TestClient

pytestmark = pytest.mark.db

RAIZ = Path(__file__).resolve().parents[2]

# Qué servicio levanta cada fichero de API. Se escribe porque el nombre del
# servicio no siempre es el del paquete donde vive la ruta —`api_catalogos.py`
# es de tenancy, `api_proveedores.py` hay en dos sitios— y deducirlo acertaría
# casi siempre, que es la peor clase de acierto.
SERVICIOS = {
    "services/automation/api.py": "automation",
    "services/eventing/api.py": "eventing",
    "services/identity/api.py": "identity",
    "services/identity/api_politicas.py": "identity",
    "services/identity/api_sso.py": "identity",
    "services/integration/api_encargos.py": "integration",
    "services/orchestrator/api.py": "orchestrator",
    "services/party/api.py": "party",
    "services/party/api_proveedores.py": "party",
    "services/sales/api.py": "sales",
    "services/sales/api_cotizacion.py": "sales",
    "services/service/api.py": "service",
    "services/tenancy/api.py": "tenancy",
    "services/tenancy/api_catalogos.py": "tenancy",
}

# Cuántos listados a mano se esperan como mínimo. Sin esto, un recorrido que no
# encontrara ninguno pasaría en verde sin haber pedido nada.
MINIMO = 25


def _listados_con_filtro() -> dict[str, list[str]]:
    """Servicio → funciones de listado que llaman al filtro común.

    Por AST y no por texto, por lo mismo que el trinquete: un `grep` daría por
    bueno un listado que no lo llama porque **otro** del mismo fichero sí.
    """
    salida: dict[str, list[str]] = {}
    for fichero in sorted(RAIZ.glob("services/*/api*.py")):
        relativo = str(fichero.relative_to(RAIZ))
        servicio = SERVICIOS.get(relativo)
        arbol = ast.parse(fichero.read_text(encoding="utf-8"))
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, ast.FunctionDef):
                continue
            if not any(
                isinstance(sub, ast.Call)
                and getattr(sub.func, "id", "") == "aplicar_filtros_de_la_url"
                for sub in ast.walk(nodo)
            ):
                continue
            es_listado = any(
                isinstance(d, ast.Call)
                and isinstance(d.func, ast.Attribute)
                and d.func.attr == "get"
                and any(
                    kw.arg == "response_model" and getattr(kw.value, "id", "") == "PaginaDeListado"
                    for kw in d.keywords
                )
                for d in nodo.decorator_list
            )
            if not es_listado:
                continue
            assert servicio, (
                f"{relativo} publica un listado a mano y no consta de qué servicio "
                "es: sin eso, esta prueba lo dejaría sin recorrer y nadie lo sabría"
            )
            salida.setdefault(servicio, []).append(nodo.name)
    return salida


def _cliente(servicio: str) -> Iterator[Any]:
    import importlib
    import os

    from crmcore.config import get_settings

    previo = os.environ.get("OUTBOX_ENABLED")
    os.environ["OUTBOX_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        with TestClient(importlib.import_module(f"services.{servicio}.main").app) as cli:
            yield cli
    finally:
        if previo is None:
            os.environ.pop("OUTBOX_ENABLED", None)
        else:
            os.environ["OUTBOX_ENABLED"] = previo
        get_settings.cache_clear()


@pytest.fixture
def cabeceras(tenant_id: UUID) -> dict[str, str]:
    """Con todos los permisos y como administrador de plataforma: lo que se
    persigue aquí es el filtro, y un 403 escondería el 422 que se busca."""
    from crmcore.config import get_settings
    from crmcore.http.deps import (
        H_FACTOR_FUERTE,
        H_PERMISOS,
        H_PLATAFORMA,
        H_ROLES,
        H_TENANT,
        H_USER,
        firmar_cabeceras_internas,
    )

    return firmar_cabeceras_internas(
        {
            H_TENANT: str(tenant_id),
            H_USER: str(uuid4()),
            H_PERMISOS: "*:*",
            H_ROLES: "admin",
            H_PLATAFORMA: "1",
            H_FACTOR_FUERTE: datetime.now(timezone.utc).isoformat(),
        },
        get_settings().secret_key.get_secret_value(),
    )


def _caminos(rutas: Any, prefijo: str = "") -> Iterator[tuple[str, str, set[str]]]:
    """Recorre las rutas de una aplicación, entrando en los routers incluidos.

    FastAPI no deja los routers incluidos planos en `app.routes`: los envuelve
    y los resuelve al recibir la petición. Mirando sólo el primer nivel salen
    la salud y las métricas, y ningún listado — o sea, un recorrido que no
    recorre nada y pasa en verde.
    """
    for ruta in rutas:
        contexto = getattr(ruta, "include_context", None)
        if contexto is not None:
            yield from _caminos(ruta.original_router.routes, prefijo + (contexto.prefix or ""))
            continue
        nombre = getattr(getattr(ruta, "endpoint", None), "__name__", "")
        if nombre:
            yield nombre, prefijo + getattr(ruta, "path", ""), set(getattr(ruta, "methods", ()))


def _rutas(cliente: Any, funciones: list[str]) -> list[tuple[str, str]]:
    """Función → el camino por el que se la llama, sacado de la aplicación.

    De la aplicación y no escrito a mano: un camino copiado aquí se queda atrás
    el día que alguien renombre el recurso, y entonces esta prueba pediría un
    404 y lo daría por bueno.
    """
    pendientes = set(funciones)
    salida = []
    for nombre, camino, metodos in _caminos(cliente.app.routes):
        if nombre in pendientes and "GET" in metodos:
            salida.append((nombre, camino))
            pendientes.discard(nombre)
    assert not pendientes, f"no se encuentra la ruta de {sorted(pendientes)}"
    return salida


def _recorrer(cliente: Any, cabeceras: dict[str, str], funciones: list[str]) -> int:
    recorridas = 0
    for nombre, camino in _rutas(cliente, funciones):
        sin_filtro = cliente.get(camino, headers=cabeceras)
        assert sin_filtro.status_code == 200, f"{nombre} ({camino}) sin filtros: {sin_filtro.text}"

        inventada = cliente.get(f"{camino}?columna_que_no_existe=1", headers=cabeceras)
        assert inventada.status_code == 422, (
            f"{nombre} ({camino}) acepta una columna inventada con "
            f"{inventada.status_code}: el filtro se está ignorando en silencio y el "
            "listado devuelve filas de más con cara de estar filtrado"
        )

        operador = cliente.get(f"{camino}?id__contiene=x", headers=cabeceras)
        assert operador.status_code == 422, (
            f"{nombre} ({camino}) acepta un operador inventado con "
            f"{operador.status_code}: aplicar igualdad sobre «id__contiene» "
            "devolvería todos los valores"
        )
        recorridas += 1
    return recorridas


@pytest.fixture
def cuantos() -> dict[str, int]:
    return {}


def test_el_recorrido_mira_de_verdad() -> None:
    """La condición de parada va automatizada y no recordada: si el recorrido
    dejara de encontrar listados, esto falla en vez de pasar en verde."""
    todos = _listados_con_filtro()
    cuantos = sum(len(v) for v in todos.values())
    assert cuantos >= MINIMO, f"sólo se ven {cuantos} listados a mano con filtro"
    # Y uno conocido, para saber que la detección funciona.
    assert "listar_actividades" in todos["party"]


@pytest.mark.parametrize(
    "servicio",
    sorted(_listados_con_filtro()),
)
def test_los_listados_a_mano_contestan_a_sus_propios_filtros(
    servicio: str, cabeceras: dict[str, str], db: Any, contexto_tenant: UUID
) -> None:
    """Un listado por servicio no bastaría: lo que se separa es la pareja
    «filtro + marca», y se separa ruta a ruta."""
    funciones = _listados_con_filtro()[servicio]
    for cliente in _cliente(servicio):
        recorridas = _recorrer(cliente, cabeceras, funciones)
    assert recorridas == len(
        funciones
    ), f"se esperaban {len(funciones)} listados de {servicio} y se recorrieron {recorridas}"
