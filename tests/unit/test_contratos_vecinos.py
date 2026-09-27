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

**Y tampoco bastaba con esto.** La comprobación de campos miraba dos funciones
escritas a mano —`_token_de_aplicacion` y `canjear_token`— de las ocho que
mandan cuerpo. Por el hueco pasó el sexto desajuste: el comentario de una
decisión de aprobación viajaba como `comment` y contecmind lo llama `note`, así
que la decisión se guardaba con su fecha y su firmante y el porqué desaparecía.
Ahora se ejercita el cliente contra un transporte simulado y se mira **lo que
sale por el cable**, no una lista; y si aparece una función que manda cuerpo y
no está ejercitada, la prueba lo dice en vez de ignorarla.

Lo tercero que faltaba: nadie comprobaba que el contrato FIJADO cubriera las
rutas que decimos consumir. El de contecmind tenía cuatro de veinte —se quedó
como estaba el día que se fijó— y el fichero parecía al día porque existía.
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


# ── Que el contrato fijado cubra lo que decimos consumir ──────────────────
#
# Rutas declaradas en el script y que el fichero fijado todavía no recoge,
# con el motivo. Igual que PENDIENTES: no es una lista de excepciones, es la de
# trabajo pendiente, y la prueba se queja también cuando sobra una entrada.
SIN_FIJAR: dict[tuple[str, str], str] = {
    ("contecmind", "/api/v1/areas"): (
        "el contrato de contecmind se fijó cuando solo se le pedían cuatro rutas y no se ha podido refrescar desde entonces: hace falta tenerlo levantado, y levantarlo es de su sesión, no de esta"
    ),
    ("contecmind", "/api/v1/folders"): (
        "el contrato de contecmind se fijó cuando solo se le pedían cuatro rutas y no se ha podido refrescar desde entonces: hace falta tenerlo levantado, y levantarlo es de su sesión, no de esta"
    ),
    ("contecmind", "/api/v1/folders/{folder_id}/documents"): (
        "el contrato de contecmind se fijó cuando solo se le pedían cuatro rutas y no se ha podido refrescar desde entonces: hace falta tenerlo levantado, y levantarlo es de su sesión, no de esta"
    ),
    ("contecmind", "/api/v1/folders/{folder_id}/effective-permissions"): (
        "el contrato de contecmind se fijó cuando solo se le pedían cuatro rutas y no se ha podido refrescar desde entonces: hace falta tenerlo levantado, y levantarlo es de su sesión, no de esta"
    ),
    ("contecmind", "/api/v1/folders/{folder_id}/summary"): (
        "el contrato de contecmind se fijó cuando solo se le pedían cuatro rutas y no se ha podido refrescar desde entonces: hace falta tenerlo levantado, y levantarlo es de su sesión, no de esta"
    ),
    ("contecmind", "/api/v1/folders/{folder_id}/concepts"): (
        "el contrato de contecmind se fijó cuando solo se le pedían cuatro rutas y no se ha podido refrescar desde entonces: hace falta tenerlo levantado, y levantarlo es de su sesión, no de esta"
    ),
    ("contecmind", "/api/v1/documents/{document_id}/move"): (
        "el contrato de contecmind se fijó cuando solo se le pedían cuatro rutas y no se ha podido refrescar desde entonces: hace falta tenerlo levantado, y levantarlo es de su sesión, no de esta"
    ),
    ("contecmind", "/api/v1/documents/{document_id}/approval"): (
        "el contrato de contecmind se fijó cuando solo se le pedían cuatro rutas y no se ha podido refrescar desde entonces: hace falta tenerlo levantado, y levantarlo es de su sesión, no de esta"
    ),
    ("contecmind", "/api/v1/approvals/pending"): (
        "el contrato de contecmind se fijó cuando solo se le pedían cuatro rutas y no se ha podido refrescar desde entonces: hace falta tenerlo levantado, y levantarlo es de su sesión, no de esta"
    ),
    ("contecmind", "/api/v1/approvals/workflows"): (
        "el contrato de contecmind se fijó cuando solo se le pedían cuatro rutas y no se ha podido refrescar desde entonces: hace falta tenerlo levantado, y levantarlo es de su sesión, no de esta"
    ),
    ("contecmind", "/api/v1/approvals/{request_id}/decide"): (
        "el contrato de contecmind se fijó cuando solo se le pedían cuatro rutas y no se ha podido refrescar desde entonces: hace falta tenerlo levantado, y levantarlo es de su sesión, no de esta"
    ),
    ("contecmind", "/api/v1/approvals/{request_id}/cancel"): (
        "el contrato de contecmind se fijó cuando solo se le pedían cuatro rutas y no se ha podido refrescar desde entonces: hace falta tenerlo levantado, y levantarlo es de su sesión, no de esta"
    ),
    ("contecmind", "/api/v1/admin/tenants/by-external/{id_externo}"): (
        "idem, y además estas tres todavía no existen allí: están acordadas y pendientes de implementar (ver el comentario del script)"
    ),
    ("contecmind", "/api/v1/admin/users/by-external/{id_externo}"): (
        "idem, y además estas tres todavía no existen allí: están acordadas y pendientes de implementar (ver el comentario del script)"
    ),
    ("contecmind", "/api/v1/admin/departments/by-external/{id_externo}"): (
        "idem, y además estas tres todavía no existen allí: están acordadas y pendientes de implementar (ver el comentario del script)"
    ),
}


def _rutas_declaradas(vecino: str) -> list[str]:
    """Las que el script dice que consumimos. Se leen de él, no se repiten."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_fijar", RAIZ / "scripts" / "fijar_contratos_vecinos.py"
    )
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return list(modulo.VECINOS[vecino]["rutas"])


@pytest.mark.parametrize("vecino", sorted(CLIENTES))
def test_el_contrato_fijado_cubre_las_rutas_que_declaramos(vecino: str) -> None:
    """Un contrato a medias parece al día: el fichero existe y no dice nada.

    El de contecmind tenía cuatro rutas de veinte. Se quedó como estaba el día
    que se fijó, la lista del script siguió creciendo y la única comprobación
    que había era que el fichero existiera.
    """
    contrato = _contrato(vecino)
    faltan = [r for r in _rutas_declaradas(vecino) if r not in contrato]
    sin_motivo = [r for r in faltan if (vecino, r) not in SIN_FIJAR]
    assert not sin_motivo, (
        f"{vecino}: se declaran rutas que el contrato fijado no recoge:\n  "
        + "\n  ".join(sin_motivo)
        + "\n\nLevanta el vecino y corre `python scripts/fijar_contratos_vecinos.py "
        f"--refrescar --solo {vecino}`. Si ahora no se puede, decláralas en "
        "SIN_FIJAR con el motivo — pero entonces esas rutas NO se están "
        "comprobando contra nada."
    )
    sobran = [r for (v, r) in SIN_FIJAR if v == vecino and r in contrato]
    assert not sobran, (
        f"{vecino}: {sorted(sobran)} ya está en el contrato fijado. Quita su "
        "entrada de SIN_FIJAR: mientras esté, se sigue dando por no comprobada."
    )


# ── Lo que sale por el cable, contra lo que el otro lado declara ──────────
#
# Cada llamada se ejercita de verdad contra un transporte simulado y se miran
# las claves que salen. Una lista de campos escrita a mano se queda vieja en
# cuanto alguien añade uno, y entonces la prueba deja de mirar justo lo que
# cambió.
LLAMADAS: dict[str, list[tuple[str, dict[str, Any]]]] = {
    "contecmind": [
        ("crear_carpeta", {"nombre": "x", "token_usuario": "t"}),
        ("mover_documento", {"documento_id": "d", "carpeta_id": "c", "token_usuario": "t"}),
        ("analizar_rama", {"carpeta_id": "c", "token_usuario": "t"}),
        ("pedir_aprobacion", {"documento_id": "d", "token_usuario": "t", "flujo_id": "f"}),
        (
            "decidir_aprobacion",
            {
                "solicitud_id": "s",
                "token_usuario": "t",
                "decision": "delegated",
                "comentario": "por qué",
                "delegar_en": "u",
            },
        ),
    ],
}

# Funciones que mandan cuerpo y NO se ejercitan aquí, con el motivo. El canje y
# el token de aplicación tienen su propia prueba más arriba, y `_llamar` es el
# transporte: no compone ningún cuerpo, lo reenvía.
NO_EJERCITADAS = {"_token_de_aplicacion", "canjear_token", "_llamar"}


def _plantilla_de(contrato: dict[str, Any], ruta: str) -> str | None:
    """La entrada del contrato que le corresponde a una ruta ya resuelta."""
    tramos = ruta.split("/")
    for plantilla in contrato:
        partes = plantilla.split("/")
        if len(partes) != len(tramos):
            continue
        if all(p.startswith("{") or p == t for p, t in zip(partes, tramos, strict=True)):
            return plantilla
    return None


@pytest.mark.parametrize("vecino", sorted(LLAMADAS))
def test_todo_cuerpo_que_sale_por_el_cable_esta_declarado(
    vecino: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El sexto desajuste: `comment` donde el otro lado dice `note`.

    No dio error —pydantic ignora lo que no conoce— y el comentario de cada
    decisión de aprobación se perdía entero.
    """
    import contextlib
    import importlib
    import os

    import httpx
    from crmcore.config import limpiar_cache_settings

    previo = dict(os.environ)
    os.environ.update(
        DMS_ENABLED="true",
        DMS_BASE_URL="https://dms.ejemplo.test",
        DMS_CLIENT_ID="crm",
        DMS_CLIENT_SECRET="x",
        DMS_AREA_NOMBRE="",
    )
    limpiar_cache_settings()
    try:
        salidas: list[tuple[str, str, dict[str, Any]]] = []

        def _transporte(peticion: httpx.Request) -> httpx.Response:
            cuerpo = json.loads(peticion.content) if peticion.content else {}
            salidas.append((peticion.method, peticion.url.path, cuerpo))
            # Lo justo para que el cliente siga: un área, una carpeta, un dict.
            if peticion.url.path == "/api/v1/areas":
                return httpx.Response(200, json={"items": [{"id": "a1", "name": "Corpus"}]})
            return httpx.Response(200, json={"id": "c1", "items": []})

        @contextlib.contextmanager
        def _fabrica(**_: Any) -> Any:
            with httpx.Client(transport=httpx.MockTransport(_transporte)) as cli:
                yield cli

        monkeypatch.setattr("crmcore.red.cliente_seguro", _fabrica)

        modulo = importlib.import_module(CLIENTES[vecino]["import"])
        for funcion, kwargs in LLAMADAS[vecino]:
            getattr(modulo, funcion)(**kwargs)

        contrato = _contrato(vecino)
        problemas: list[str] = []
        comprobadas = 0
        for metodo, ruta, cuerpo in salidas:
            if not cuerpo:
                continue
            plantilla = _plantilla_de(contrato, ruta)
            if plantilla is None or contrato[plantilla] is None:
                continue  # sin fijar: lo cubre la prueba de cobertura
            declarado = contrato[plantilla].get(metodo.lower())
            if declarado is None:
                problemas.append(f"{metodo} {ruta}: el contrato no declara ese método")
                continue
            comprobadas += 1
            sobran = sorted(set(cuerpo) - set(declarado["campos"]))
            if sobran:
                problemas.append(
                    f"{metodo} {ruta} manda {sobran} y su esquema no lo declara "
                    f"(acepta {sorted(declarado['campos'])})"
                )
        assert not problemas, f"{vecino}:\n  " + "\n  ".join(problemas)
    finally:
        os.environ.clear()
        os.environ.update(previo)
        limpiar_cache_settings()


@pytest.mark.parametrize("vecino", sorted(CLIENTES))
def test_ninguna_funcion_que_manda_cuerpo_se_queda_sin_ejercitar(vecino: str) -> None:
    """La tabla puede quedarse corta; lo que no puede es quedarse corta EN SILENCIO.

    Es como se coló `decidir_aprobacion`: se escribió una función nueva que
    manda un cuerpo y la prueba de contratos siguió mirando las mismas dos de
    siempre, tan en verde como antes.
    """
    mandan = set(_cuerpos_que_enviamos(CLIENTES[vecino]["modulo"]))
    ejercitadas = {f for f, _ in LLAMADAS.get(vecino, [])}
    huerfanas = sorted(mandan - ejercitadas - NO_EJERCITADAS)
    assert not huerfanas, (
        f"{vecino}: estas funciones mandan un cuerpo y nadie comprueba sus "
        f"campos contra el contrato: {huerfanas}.\nAñádelas a LLAMADAS con "
        "argumentos de mentira, o a NO_EJERCITADAS con el motivo."
    )
