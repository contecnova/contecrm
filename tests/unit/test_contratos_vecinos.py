"""Lo que pedimos a los vecinos existe EN SU CONTRATO PUBLICADO (RT-4, RT-5).

Esta prueba existe porque las otras no bastaban, y conviene entender por qué
antes de tocarla.

La integración con contecintelligence llevaba meses rota con CINCO desajustes:
número de pasos, mecanismo de autenticación, prefijo de la ruta y dos nombres de
campo. Todos de contrato. Y **ninguna prueba con dobles los habría cazado**: un
doble contesta lo que se le dice, así que fija la suposición de quien lo escribe,
no lo que el otro lado publica. `test_cliente_intelligence.py` es útil —fija la
forma de la conversación— pero habría pasado en verde con las cinco.

Lo que sí los caza es comparar contra su OpenAPI, fijado en
`tests/fixtures/contratos/` y regenerable con:

    python scripts/fijar_contratos_vecinos.py --refrescar

Corre en milisegundos y no necesita a nadie levantado, así que cabe en el
preflight — que es la condición para que sirva de algo.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest

RAIZ = Path(__file__).resolve().parent.parent.parent
CONTRATOS = RAIZ / "tests" / "fixtures" / "contratos"

# Rutas que el otro lado TODAVÍA no publica, con el motivo. No es una lista de
# excepciones: es la lista de trabajo pendiente, y la prueba se queja tanto si
# aparece una que no está aquí como si una de aquí ya existe —entonces hay que
# quitarla, y eso es justo lo que se quiere que alguien note el día que ocurra.
PENDIENTES: dict[tuple[str, str], str] = {
    (
        "contecmind",
        "/api/v1/oauth/token",
    ): "contecmind no tiene credenciales de aplicación; especificado en su docs/DESIGN_aplicaciones_anfitrionas.md",
    (
        "contecmind",
        "/api/v1/tokens/exchange",
    ): "idem: sin canje no hay con qué autenticarse, y por eso DMS_ENABLED=false",
}

CLIENTES: dict[str, dict[str, Any]] = {
    "contecintelligence": {
        "modulo": RAIZ / "services" / "analytics" / "cliente.py",
        "import": "services.analytics.cliente",
    },
    "contecmind": {
        "modulo": RAIZ / "packages" / "crmcore" / "crmcore" / "documental" / "cliente.py",
        "import": "crmcore.documental.cliente",
    },
}


def _cuerpos_que_enviamos(fichero: Path) -> dict[str, list[str]]:
    """Las claves de cada cuerpo JSON que el cliente manda, por función.

    Se leen del AST y no de una lista escrita a mano: una lista a mano se queda
    vieja en cuanto alguien añade un campo, y entonces la prueba deja de mirar
    justo lo que cambió.
    """
    arbol = ast.parse(fichero.read_text("utf-8"))
    salida: dict[str, list[str]] = {}
    for funcion in ast.walk(arbol):
        if not isinstance(funcion, ast.FunctionDef):
            continue
        for nodo in ast.walk(funcion):
            dic: ast.Dict | None = None
            if isinstance(nodo, ast.Assign) and isinstance(nodo.value, ast.Dict):
                if any(isinstance(t, ast.Name) and t.id == "cuerpo" for t in nodo.targets):
                    dic = nodo.value
            elif isinstance(nodo, ast.Call):
                for kw in nodo.keywords:
                    if kw.arg == "json" and isinstance(kw.value, ast.Dict):
                        dic = kw.value
            if dic is None:
                continue
            claves = [c.value for c in dic.keys if isinstance(c, ast.Constant)]
            if claves:
                salida.setdefault(funcion.name, []).extend(claves)
    return salida


def _contrato(vecino: str) -> dict[str, Any]:
    fichero = CONTRATOS / f"{vecino}.json"
    assert fichero.exists(), (
        f"Falta el contrato fijado de {vecino}. Levántalo y corre "
        "`python scripts/fijar_contratos_vecinos.py --refrescar`."
    )
    return json.loads(fichero.read_text("utf-8"))


@pytest.mark.parametrize("vecino", sorted(CLIENTES))
def test_las_rutas_que_llamamos_existen_en_su_contrato(vecino: str) -> None:
    """Una ruta inventada no falla hasta que alguien abre la pantalla."""
    import importlib

    modulo = importlib.import_module(CLIENTES[vecino]["import"])
    contrato = _contrato(vecino)

    for nombre in ("RUTA_APLICACION", "RUTA_CANJE"):
        ruta = getattr(modulo, nombre)
        assert ruta in contrato, (
            f"{vecino}: el cliente llama a {ruta} y esa ruta no está fijada. "
            "Si es nueva, refresca el contrato; si no, está mal escrita."
        )
        pendiente = PENDIENTES.get((vecino, ruta))
        if contrato[ruta] is None:
            assert pendiente, (
                f"{vecino}: el cliente llama a {ruta} y el servicio NO la publica. "
                "O se implementa allí, o se declara en PENDIENTES con su motivo."
            )
        else:
            assert not pendiente, (
                f"{vecino}: {ruta} YA existe en su contrato. Quita su entrada de "
                "PENDIENTES y comprueba que el camino completo funciona."
            )


@pytest.mark.parametrize("vecino", sorted(CLIENTES))
def test_los_campos_que_enviamos_estan_declarados_en_su_esquema(vecino: str) -> None:
    """Un campo que el otro lado no declara se ignora EN SILENCIO.

    Es el desajuste más caro de los cinco, precisamente porque no rompe nada:
    `ttl` en vez de `ttl_s` hacía que el token saliera con la duración por
    defecto del otro lado, sin error y sin aviso.
    """
    contrato = _contrato(vecino)
    enviados = _cuerpos_que_enviamos(CLIENTES[vecino]["modulo"])

    esperado = {
        "_token_de_aplicacion": "RUTA_APLICACION",
        "canjear_token": "RUTA_CANJE",
    }
    import importlib

    modulo = importlib.import_module(CLIENTES[vecino]["import"])

    for funcion, constante in esperado.items():
        assert funcion in enviados, f"{vecino}: {funcion} ya no manda ningún cuerpo JSON"
        ruta = getattr(modulo, constante)
        declarado = contrato.get(ruta)
        if declarado is None:
            continue  # ruta pendiente; lo cubre la otra prueba
        campos = set(declarado["post"]["campos"])
        sobran = set(enviados[funcion]) - campos
        assert not sobran, (
            f"{vecino}: {funcion} manda {sorted(sobran)} y {ruta} no lo declara. "
            f"Lo que acepta es {sorted(campos)}. Un campo que no declara se "
            "ignora sin decir nada."
        )


def test_los_dos_clientes_de_la_casa_hacen_lo_mismo() -> None:
    """Mismo problema, misma solución. Aquí es donde se separaron.

    El de contecintelligence se arregló y el de contecmind se quedó atrás: uno
    hacía dos pasos y el otro iba directo al canje con autenticación básica. Dos
    formas de resolver lo mismo en la misma casa es lo que garantiza que la
    siguiente que se escriba elija la que no toca.
    """
    formas = {}
    for vecino, cfg in CLIENTES.items():
        enviados = _cuerpos_que_enviamos(cfg["modulo"])
        formas[vecino] = (
            tuple(sorted(enviados["_token_de_aplicacion"])),
            tuple(sorted(enviados["canjear_token"])),
        )

    distintos = set(formas.values())
    assert len(distintos) == 1, (
        "Los dos clientes mandan cosas distintas para lo mismo:\n"
        + "\n".join(f"  {v}: {f}" for v, f in sorted(formas.items()))
    )
