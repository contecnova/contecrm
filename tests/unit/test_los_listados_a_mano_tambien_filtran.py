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
    26-10-2026  23  casos, que es lo que necesita la bandeja para repartir por
                    plazo sin contar sobre una página
    26-10-2026   0  los veintidós restantes, de una vez. El veintitrés
                    —`listar_entornos`— no es deuda: devuelve una lista cerrada
                    escrita en el código, así que no hay columnas que filtrar.
                    Pasa a `NO_TIENEN_COLUMNAS`, con su motivo.
"""

from __future__ import annotations

import ast
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]

# ── Los que todavía no llaman al filtro común ─────────────────────────────
#
# Vacío desde el 26-10-2026. No significa que no queden listados a mano:
# significa que todos los que hay admiten los filtros comunes además de los
# suyos.
SIN_FILTROS_COMUNES_HOY: set[str] = set()

# ── Y los que no tienen columnas que filtrar ──────────────────────────────
#
# Esto no es deuda, es una excepción con su motivo. Un listado que no lee una
# tabla no tiene columnas por las que filtrar, así que `aplicar_filtros_de_la_url`
# no tendría contra qué validar: le pasaríamos un modelo inventado para que
# rechazara todo, que es una comprobación que finge.
#
# Cada entrada dice por qué. Sin el motivo, la lista se convierte en el sitio
# donde se mete lo que da guerra.
NO_TIENEN_COLUMNAS = {
    "services/metadata/api_entornos.py::listar_entornos": (
        "devuelve una lista CERRADA escrita en el código —las cuatro etapas por "
        "las que pasa la configuración— y no una tabla: no hay columnas por las "
        "que filtrar, y crear entornos no se puede"
    ),
}


def _marcados_abiertos() -> set[str]:
    """Funciones marcadas con `admite_parametros_abiertos`, por fichero."""
    salida: set[str] = set()
    for fichero in sorted(RAIZ.glob("services/*/api*.py")):
        arbol = ast.parse(fichero.read_text(encoding="utf-8"))
        for nodo in ast.walk(arbol):
            if (
                isinstance(nodo, ast.Call)
                and getattr(nodo.func, "id", "") == "admite_parametros_abiertos"
                and nodo.args
            ):
                nombre = getattr(nodo.args[0], "id", "")
                if nombre:
                    salida.add(f"{fichero.relative_to(RAIZ)}::{nombre}")
    return salida


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
    sobran = [k for k in nuevos if k not in SIN_FILTROS_COMUNES_HOY and k not in NO_TIENEN_COLUMNAS]
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


def test_quien_llama_al_filtro_comun_se_declara_abierto() -> None:
    """**Las dos mitades van juntas o no funciona ninguna.**

    La comprobación global de parámetros rechaza lo que una ruta no declara, y
    los filtros comunes son nombres de columna: no se pueden declarar. Un
    listado que llama a `aplicar_filtros_de_la_url` y no se marca abierto
    contesta 422 a sus propios filtros — «esta operación no mira
    «importe__mayor»» sobre un filtro que la pantalla acaba de ofrecer.

    Medido el 26-10-2026: pasó en los seis listados del día a día en cuanto se
    les dio el filtro, y lo cazó una prueba de rango, no una de parámetros.
    """
    abiertos = _marcados_abiertos()
    sin_marcar = sorted(
        nombre for nombre, llama in _listados_a_mano().items() if llama and nombre not in abiertos
    )
    assert not sin_marcar, (
        "Listados que aplican los filtros comunes y NO están marcados como "
        "abiertos: responderán 422 a sus propios filtros.\n  " + "\n  ".join(sin_marcar)
    )


def test_nadie_se_declara_abierto_sin_necesitarlo() -> None:
    """La marca apaga una comprobación de seguridad —que ningún parámetro se
    ignore en silencio—, así que no puede ponerse «por si acaso». Si una ruta
    la lleva sin llamar al filtro común, o bien le falta el filtro o bien le
    sobra la marca; las dos cosas hay que mirarlas."""
    listados = _listados_a_mano()
    de_mas = sorted(
        nombre for nombre in _marcados_abiertos() if nombre in listados and not listados[nombre]
    )
    assert not de_mas, "Marcados como abiertos sin aplicar los filtros comunes:\n  " + "\n  ".join(
        de_mas
    )


def test_las_excepciones_siguen_existiendo_y_dicen_por_qué() -> None:
    """Una excepción sin motivo se copia a la siguiente ruta que dé guerra, y
    entonces la comprobación deja de comprobar. Y una que ya no existe deja la
    lista grande para siempre."""
    todos = _listados_a_mano()
    fantasmas = sorted(k for k in NO_TIENEN_COLUMNAS if k not in todos)
    assert not fantasmas, "Exceptuados y ya no existen:\n  " + "\n  ".join(fantasmas)
    sin_motivo = sorted(k for k, motivo in NO_TIENEN_COLUMNAS.items() if len(motivo) < 40)
    assert not sin_motivo, "Exceptuados sin un motivo que se pueda leer:\n  " + "\n  ".join(
        sin_motivo
    )
    # Y si alguno acabara llamando al filtro común, sobra de aquí.
    ya_filtran = sorted(k for k in NO_TIENEN_COLUMNAS if todos.get(k) is True)
    assert not ya_filtran, "Exceptuados que ya filtran:\n  " + "\n  ".join(ya_filtran)
