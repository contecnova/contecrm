"""Los alcances que pide el CRM son los que se dan de alta.

El 30-10-2026 el área de análisis entera estaba muerta en la instalación local.
Los cuadros de mando salían como dos cajas rojas y no se podía ni preguntar ni
ejecutar un informe. La causa final, después de cuatro capas:

    403 · «este token está acotado y no alcanza a esta operación
           (alcances: sources:read)»

`scripts/alta_explotacion.py` daba de alta la aplicación de contecrm en
contecintelligence con `["chat:ask", "sources:read"]` —solo lectura—, y el
mismo par estaba escrito **otra vez** como valor por defecto de `ci_scopes`.
Después, el trabajo que registra el CRM como fuente pedía un token con
`sources:write`, que ese alta no podía respaldar. Dos listas escritas a mano
que tienen que coincidir acaban no coincidiendo, y aquí ninguna de las dos
coincidía con lo que el producto pide de verdad.

Ahora hay **una sola lista** (`ALCANCES_DEL_CRM`) y esta prueba comprueba que
cubre lo que cada operación declara necesitar. No es una copia de la lista: se
recorre lo que piden las operaciones y se exige que esté.

Validada plantando el caso malo: quitando `sources:write` de `ALCANCES_DEL_CRM`
falla nombrando el alcance y la operación que lo pide.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from crmcore.config import Settings
from crmcore.config_parts._intelligence import ALCANCES_DEL_CRM

RAIZ = Path(__file__).resolve().parents[2]


def _alcances_que_pide_el_codigo() -> dict[str, list[str]]:
    """Cada constante `ALCANCES_*` de los servicios, con lo que pide.

    Se leen del árbol, no de una lista escrita aquí: una operación nueva que
    necesite un alcance nuevo entra sola en esta comprobación.
    """
    pedidos: dict[str, list[str]] = {}
    for fichero in sorted((RAIZ / "services").rglob("*.py")):
        arbol = ast.parse(fichero.read_text(), filename=str(fichero))
        for nodo in arbol.body:
            if not isinstance(nodo, ast.Assign):
                continue
            for destino in nodo.targets:
                if not isinstance(destino, ast.Name) or not destino.id.startswith("ALCANCES_"):
                    continue
                if not isinstance(nodo.value, (ast.List, ast.Tuple)):
                    continue
                valores = [
                    e.value
                    for e in nodo.value.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)
                ]
                if valores:
                    pedidos[f"{fichero.name}:{destino.id}"] = valores
    return pedidos


def test_lo_que_se_da_de_alta_cubre_lo_que_se_pide() -> None:
    pedidos = _alcances_que_pide_el_codigo()
    # Cuántas ha mirado: si no encuentra ninguna constante, no está mirando.
    assert len(pedidos) >= 2, f"sólo se han encontrado {len(pedidos)} listas de alcances"

    faltan = [
        f"«{alcance}» lo pide {quien} y no está en ALCANCES_DEL_CRM"
        for quien, alcances in sorted(pedidos.items())
        for alcance in alcances
        if alcance not in ALCANCES_DEL_CRM
    ]
    assert not faltan, (
        "El alta de la aplicación en contecintelligence se queda corta. Un "
        "alcance que se pide y no se concede sale como 403 en un worker, de "
        "noche:\n  " + "\n  ".join(faltan)
    )


def test_la_configuracion_no_escribe_la_lista_otra_vez() -> None:
    """`ci_scopes` sale de la misma lista, no de una copia."""
    assert list(Settings().ci_scopes) == list(ALCANCES_DEL_CRM)


def test_el_script_de_alta_usa_la_misma_lista() -> None:
    """Y el script que da de alta la aplicación, también.

    Se mira el código y no el valor: el script importa `ALCANCES_DEL_CRM`, y lo
    que esta prueba impide es que alguien vuelva a escribir ahí una lista.
    """
    codigo = (RAIZ / "scripts" / "alta_explotacion.py").read_text()
    assert "ALCANCES_DEL_CRM" in codigo
    literales = re.findall(r'ALCANCES_POR_DEFECTO\s*=\s*\[[^\]]*"', codigo)
    assert not literales, f"la lista vuelve a estar escrita a mano: {literales}"


def test_el_alta_reconcilia_los_alcances_de_una_aplicacion_que_ya_existe() -> None:
    """Y no sólo al crearla.

    El ramal «la aplicación ya existe» reconciliaba los orígenes del navegador
    y daba los alcances por buenos. Una aplicación dada de alta cuando la lista
    era más corta se quedaba así para siempre, y el script decía «la credencial
    de contecrm vale» mientras el análisis estaba muerto.
    """
    codigo = (RAIZ / "scripts" / "alta_explotacion.py").read_text()
    assert (
        '"scopes": [*(app.get("scopes") or []), *sin_permiso]' in codigo
    ), "el script no amplía los alcances de una aplicación ya existente"
