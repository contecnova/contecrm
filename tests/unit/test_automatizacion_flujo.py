"""Ramas, bucles y variables de flujo (CRM-00.03.03.04).

Una automatización deja de ser una lista de acciones en cuanto alguien necesita
«si el importe pasa de X, avisa; si no, asigna» o «por cada línea, comprueba
stock». Lo que estas pruebas defienden son los tres límites sin los cuales eso
se convierte en un motor de procesos mal hecho:

  * **El bucle tiene tope y lo dice.** Una iteración cortada en silencio es peor
    que no tenerla, porque el resultado parcial parece completo.
  * **El anidamiento tiene tope.** Más de tres niveles es un proceso, y para eso
    está el motor que sabe reanudar y compensar.
  * **Las variables no se escapan.** Una regla no puede contaminar a la
    siguiente, o «funciona sola pero no cuando corre después de aquella».
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from services.automation import motor as mtr
from services.automation.modelos import Automatizacion


def _regla(acciones: list[Any], **extra: Any) -> Automatizacion:
    return Automatizacion(
        tenant_id=uuid4(),
        nombre="prueba",
        disparador="registro_creado",
        objetivo="cuenta",
        condiciones=[],
        acciones=acciones,
        # Los contadores tienen `default` de Python, que solo se aplica al
        # volcar: construir el objeto en memoria los deja a `None` y el motor
        # los incrementa.
        ejecuciones=0,
        fallos=0,
        **extra,
    )


@pytest.fixture
def ejecutores() -> dict[str, Any]:
    """Ejecutores que solo apuntan lo que se les pide."""
    llamadas: list[dict[str, Any]] = []

    def notificar(**kwargs: Any) -> dict[str, Any]:
        kwargs.pop("_contexto", None)
        kwargs.pop("_tenant_id", None)
        llamadas.append(kwargs)
        return {"ok": True, "eco": kwargs}

    return {"notificar": notificar, "_llamadas": llamadas}


def _ejecutar(db: Any, regla: Automatizacion, valores: dict[str, Any], ejecutores: dict[str, Any]):
    return mtr.ejecutar(
        db,
        regla,
        valores=valores,
        objeto="cuenta",
        registro_id=str(uuid4()),
        ejecutores={k: v for k, v in ejecutores.items() if not k.startswith("_")},
    )


# ── Ramas ─────────────────────────────────────────────────────────────────


@pytest.mark.db
def test_una_rama_elige_camino_y_lo_deja_escrito(
    db: Any, ejecutores: dict[str, Any], contexto_tenant: Any
) -> None:
    """Sin dejarlo escrito, «¿por qué entró por esta rama?» no se contesta, y
    contestarlo es la única razón de que este motor deje traza de todo."""
    regla = _regla(
        [
            {
                "tipo": "si",
                "condiciones": [{"atributo": "importe", "op": ">", "valor": 100}],
                "entonces": [{"tipo": "notificar", "parametros": {"texto": "grande"}}],
                "si_no": [{"tipo": "notificar", "parametros": {"texto": "pequeño"}}],
            }
        ]
    )

    traza = _ejecutar(db, regla, {"importe": 500}, ejecutores)

    assert [c["texto"] for c in ejecutores["_llamadas"]] == ["grande"]
    rama = next(a for a in traza.acciones_ejecutadas if a["tipo"] == "si")
    assert rama["cumple"] is True


@pytest.mark.db
def test_la_rama_usa_la_misma_gramatica_que_el_disparo(
    db: Any, ejecutores: dict[str, Any], contexto_tenant: Any
) -> None:
    """Dos gramáticas en el mismo motor se comportarían distinto ante el mismo
    dato, y nadie sabría cuál mira qué."""
    regla = _regla(
        [
            {
                "tipo": "si",
                "condiciones": [{"atributo": "estado", "op": "=", "valor": "activa"}],
                "entonces": [{"tipo": "notificar", "parametros": {"texto": "sí"}}],
            }
        ]
    )
    _ejecutar(db, regla, {"estado": "cerrada"}, ejecutores)
    assert ejecutores["_llamadas"] == []


# ── Bucles ────────────────────────────────────────────────────────────────


@pytest.mark.db
def test_un_bucle_recorre_la_coleccion(
    db: Any, ejecutores: dict[str, Any], contexto_tenant: Any
) -> None:
    regla = _regla(
        [
            {
                "tipo": "para_cada",
                "sobre": "@lineas",
                "como": "linea",
                "hacer": [{"tipo": "notificar", "parametros": {"texto": "@linea"}}],
            }
        ]
    )

    _ejecutar(db, regla, {"lineas": ["a", "b", "c"]}, ejecutores)

    assert [c["texto"] for c in ejecutores["_llamadas"]] == ["a", "b", "c"]


@pytest.mark.db
def test_un_bucle_demasiado_largo_se_corta_y_lo_dice(
    db: Any, ejecutores: dict[str, Any], contexto_tenant: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cortar en silencio haría que alguien viera «disparada» y diera por hecho
    que recorrió las seiscientas líneas."""
    from crmcore.config import limpiar_cache_settings

    monkeypatch.setenv("AUTOMATIZACION_MAX_VUELTAS", "2")
    limpiar_cache_settings()
    regla = _regla(
        [
            {
                "tipo": "para_cada",
                "sobre": "@lineas",
                "hacer": [{"tipo": "notificar", "parametros": {"texto": "x"}}],
            }
        ]
    )

    traza = _ejecutar(db, regla, {"lineas": [1, 2, 3, 4, 5]}, ejecutores)
    limpiar_cache_settings()

    bucle = next(a for a in traza.acciones_ejecutadas if a["tipo"] == "para_cada")
    assert bucle["vueltas"] == 2
    assert bucle["cortado"] is True
    assert bucle["de"] == 5


@pytest.mark.db
def test_un_para_cada_sobre_algo_que_no_es_lista_falla_claro(
    db: Any, ejecutores: dict[str, Any], contexto_tenant: Any
) -> None:
    regla = _regla([{"tipo": "para_cada", "sobre": "@nombre", "hacer": []}])
    traza = _ejecutar(db, regla, {"nombre": "ACME"}, ejecutores)
    assert traza.resultado == "fallida"
    assert "esperaba una lista" in traza.error


# ── Variables de flujo ────────────────────────────────────────────────────


@pytest.mark.db
def test_una_variable_se_declara_y_la_ven_las_acciones_siguientes(
    db: Any, ejecutores: dict[str, Any], contexto_tenant: Any
) -> None:
    regla = _regla(
        [
            {"tipo": "fijar", "nombre": "saludo", "valor": "hola"},
            {"tipo": "notificar", "parametros": {"texto": "@saludo"}},
        ]
    )
    _ejecutar(db, regla, {}, ejecutores)
    assert ejecutores["_llamadas"][0]["texto"] == "hola"


@pytest.mark.db
def test_las_variables_no_se_escapan_a_la_regla_siguiente(
    db: Any, ejecutores: dict[str, Any], contexto_tenant: Any
) -> None:
    """«Esta regla funciona sola pero no cuando corre después de aquella» es de
    los fallos más caros de encontrar."""
    valores = {"importe": 10}
    regla = _regla([{"tipo": "fijar", "nombre": "cosa", "valor": 1}])
    _ejecutar(db, regla, valores, ejecutores)
    assert "cosa" not in valores


@pytest.mark.db
def test_el_anidamiento_tiene_tope(
    db: Any, ejecutores: dict[str, Any], contexto_tenant: Any
) -> None:
    """Más de tres niveles es un proceso, y para eso está el motor que sabe
    reanudar y compensar."""
    hoja: list[Any] = [{"tipo": "notificar", "parametros": {}}]
    for _ in range(6):
        hoja = [{"tipo": "si", "condiciones": [], "entonces": hoja}]

    traza = _ejecutar(db, _regla(hoja), {}, ejecutores)
    assert traza.resultado == "fallida"
    assert "anidados" in traza.error
