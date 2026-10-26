"""Un listado admite rangos o no según quién lo escribió. Eso no es un contrato.

La fábrica monta 61 listados y les da los filtros comunes —igualdad y rangos—
gratis. Hay otros **escritos a mano**, porque tienen filtros propios que la
fábrica no sabe expresar: «sólo las mías», «sólo las vencidas», «las de esta
cuenta». Tener filtros propios es legítimo; quedarse sin los comunes no.

El resultado es que `?vence_at__hasta=…` funciona en unos sitios y en otros
devuelve 422, y quien integra lo descubre probando. Peor: antes de la
comprobación de parámetros desconocidos, **se ignoraba en silencio** y devolvía
filas de más.

Esta lista es un trinquete: **sólo puede encoger**. No se baja por descuido —se
baja llamando a `aplicar_filtros_de_la_url` en el listado y borrando su línea de
aquí, en el mismo commit—.

    26-10-2026  28  medición inicial
    26-10-2026  24  actividades, cuentas, contactos, leads y oportunidades —el
                    núcleo del CRM, y lo que necesita la portada nueva
"""

from __future__ import annotations

import ast
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]

# ── Los que todavía no llaman al filtro común ─────────────────────────────
SIN_FILTROS_COMUNES_HOY = {
    "services/automation/api.py::listar",
    "services/eventing/api.py::listar",
    "services/identity/api.py::listar_usuarios",
    "services/identity/api.py::listar_roles",
    "services/identity/api.py::mis_sesiones",
    "services/identity/api.py::listar_claves",
    "services/identity/api.py::listar_reglas_comparticion",
    "services/identity/api_politicas.py::listar_politicas",
    "services/identity/api_sso.py::listar",
    "services/integration/api_encargos.py::listar_proveedores",
    "services/integration/api_encargos.py::listar",
    "services/metadata/api_entornos.py::listar_entornos",
    "services/orchestrator/api.py::bandeja",
    "services/orchestrator/api.py::listar_instancias",
    "services/orchestrator/api.py::listar_sagas",
    "services/party/api.py::listar_solicitudes",
    "services/party/api_proveedores.py::listar_proveedores",
    "services/sales/api.py::listar_pipelines",
    "services/sales/api_cotizacion.py::listar_productos",
    "services/service/api.py::listar",
    "services/tenancy/api.py::listar_planes",
    "services/tenancy/api.py::listar_tenants",
    "services/tenancy/api_catalogos.py::listar_calendarios",
    "services/tenancy/api_catalogos.py::listar_plantillas",
}


def _listados_a_mano() -> dict[str, bool]:
    """Ruta::función → si llama al filtro común.

    Se busca por el AST y no por texto: `grep` de «aplicar_filtros_de_la_url»
    en el fichero daría por bueno un listado que no lo llama porque **otro** del
    mismo fichero sí.
    """
    salida: dict[str, bool] = {}
    for fichero in sorted(RAIZ.glob("services/*/api*.py")):
        arbol = ast.parse(fichero.read_text(encoding="utf-8"))
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, ast.FunctionDef):
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
            llama = any(
                isinstance(sub, ast.Call)
                and getattr(sub.func, "id", "") == "aplicar_filtros_de_la_url"
                for sub in ast.walk(nodo)
            )
            salida[f"{fichero.relative_to(RAIZ)}::{nodo.name}"] = llama
    return salida


def test_el_recorrido_mira_de_verdad() -> None:
    """Sin esto, un recorrido que no encuentre ningún listado diría que están
    todos bien."""
    todos = _listados_a_mano()
    assert len(todos) >= 25, f"sólo se ven {len(todos)} listados escritos a mano"
    # Y uno que SÍ lo llama, para saber que la detección funciona.
    assert todos.get("services/party/api.py::listar_actividades") is True


def test_ningun_listado_nuevo_nace_sin_los_filtros_comunes() -> None:
    nuevos = sorted(k for k, llama in _listados_a_mano().items() if not llama)
    sobran = [k for k in nuevos if k not in SIN_FILTROS_COMUNES_HOY]
    assert not sobran, (
        "Listados escritos a mano que no llaman a `aplicar_filtros_de_la_url`, "
        "así que no admiten los filtros comunes ni los rangos:\n  " + "\n  ".join(sobran)
    )


def test_los_que_se_arreglan_salen_de_la_lista() -> None:
    """El trinquete sólo encoge si alguien lo encoge. Esto obliga."""
    todos = _listados_a_mano()
    ya_estan = sorted(k for k in SIN_FILTROS_COMUNES_HOY if todos.get(k) is True)
    assert not ya_estan, "Ya llaman al filtro común y siguen apuntados:\n  " + "\n  ".join(ya_estan)


def test_los_apuntados_existen() -> None:
    """Una lista con nombres que ya no existen se queda grande para siempre y
    deja de significar nada."""
    todos = _listados_a_mano()
    fantasmas = sorted(k for k in SIN_FILTROS_COMUNES_HOY if k not in todos)
    assert not fantasmas, "Apuntados y ya no existen:\n  " + "\n  ".join(fantasmas)
