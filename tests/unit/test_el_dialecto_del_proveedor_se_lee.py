"""El dialecto del proveedor de IA (CRM-05.02.02.10).

`ProveedorIA.formato` existía desde el principio: se guardaba, se enseñaba en la
consola y **no lo leía nadie**. El puerto construía siempre el cuerpo de la
familia OpenAI, así que un tenant que declarara un proveedor Anthropic o Gemini
tenía la fila bien guardada y la llamada rechazada con un 400 que no explica
nada. Las dos mitades estaban y nada las unía.

Lo que vigilan estas pruebas, por orden de lo que duele:

  * que el puerto **lea** el campo en vez de suponerlo —el circuito abierto—,
  * que cada familia reciba lo suyo, que es lo que no se puede probar con red,
  * que la respuesta de las tres se lea igual, para que el resto del servicio no
    tenga que saber de qué familia vino,
  * y que lo que una familia no sabe hacer se diga en vez de simularse.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import pytest
from crmcore.errors import ErrorDependencia, ErrorValidacion

from services.intelligence import dialectos, puerto

# ── El circuito abierto: ¿lo lee alguien? ─────────────────────────────────


class _Respuesta:
    status_code = 200

    def __init__(self, datos: dict[str, Any]) -> None:
        self._datos = datos

    def json(self) -> dict[str, Any]:
        return self._datos


class _Ficha:
    """Una fila de proveedor, con lo poco que el puerto le mira."""

    def __init__(self, formato: str) -> None:
        self.formato = formato
        self.base_url = "https://ia.example.com"
        self.config: dict[str, Any] = {}


def _puerto_de_mentira(monkeypatch: pytest.MonkeyPatch, formato: str, devuelve: dict[str, Any]):
    """Deja el puerto llamando a un proveedor que no existe, y guarda el cuerpo.

    Se parchean las dos puertas de salida —la sesión y el cliente HTTP— porque
    lo que se quiere mirar está entre las dos: qué cuerpo sale a partir de la
    fila que entra.
    """
    enviado: dict[str, Any] = {}

    @contextmanager
    def _sesion(**_kw: Any) -> Any:
        class _Db:
            def execute(self, *_a: Any, **_k: Any) -> Any:
                class _R:
                    def scalars(self_inner) -> Any:  # noqa: N805
                        class _S:
                            def first(self_s) -> Any:  # noqa: N805
                                return _Ficha(formato)

                        return _S()

                return _R()

        yield _Db()

    @contextmanager
    def _cliente(**_kw: Any) -> Any:
        class _Cli:
            def post(self, url: str, json: dict[str, Any], headers: dict[str, str]) -> Any:
                enviado["url"] = url
                enviado["cuerpo"] = json
                enviado["cabeceras"] = headers
                return _Respuesta(devuelve)

        yield _Cli()

    monkeypatch.setattr("crmcore.db.session.sesion", _sesion)
    monkeypatch.setattr("crmcore.red.cliente_seguro", _cliente)
    return enviado


def test_el_puerto_lee_el_formato_del_proveedor_y_no_lo_supone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La prueba que faltaba. Antes del 28-10-2026 esto pasaba igual con
    `formato` a cualquier cosa, porque el cuerpo siempre era el de OpenAI."""
    enviado = _puerto_de_mentira(
        monkeypatch,
        "anthropic_messages",
        {"content": [{"type": "text", "text": "hola"}], "usage": {}},
    )
    puerto._llamar(
        proveedor="p",
        modelo="m",
        mensajes=[{"role": "system", "content": "S"}, {"role": "user", "content": "U"}],
        opt_out=False,
    )
    # El cuerpo de esta familia no se parece al de OpenAI: el sistema va fuera
    # de la lista y `max_tokens` es obligatorio.
    assert "messages" in enviado["cuerpo"]
    assert enviado["cuerpo"]["system"] == "S"
    assert enviado["cuerpo"]["max_tokens"] > 0
    assert enviado["url"].endswith("/v1/messages")


def test_la_familia_de_gemini_no_habla_de_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    """Y lleva el modelo DENTRO del camino, que es la clase de detalle por la
    que una sola plantilla de ruta no vale para las tres."""
    enviado = _puerto_de_mentira(
        monkeypatch, "gemini_generate", {"candidates": [], "usageMetadata": {}}
    )
    puerto._llamar(
        proveedor="p", modelo="gemini-2", mensajes=[{"role": "user", "content": "U"}], opt_out=False
    )
    assert "contents" in enviado["cuerpo"]
    assert "messages" not in enviado["cuerpo"]
    assert enviado["url"].endswith("/v1beta/models/gemini-2:generateContent")


def test_un_formato_desconocido_se_para_antes_de_llamar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Se para en vez de caer al de OpenAI «por si acaso»: caer al de OpenAI es
    exactamente lo que hacía antes, y por eso nadie se enteró en meses."""
    _puerto_de_mentira(monkeypatch, "openai", {})
    with pytest.raises(ErrorValidacion) as exc:
        puerto._llamar(proveedor="p", modelo="m", mensajes=[], opt_out=False)
    assert exc.value.error_code == "ia.dialecto_desconocido"


# ── Qué recibe cada familia ───────────────────────────────────────────────


def test_el_sistema_sale_de_la_lista_en_las_dos_familias_que_lo_quieren_fuera() -> None:
    mensajes = [
        {"role": "system", "content": "eres X"},
        {"role": "user", "content": "hola"},
        {"role": "assistant", "content": "qué tal"},
    ]
    abierto = dialectos.peticion(
        formato="openai_chat", modelo="m", mensajes=mensajes, opt_out=False, max_tokens=100
    )
    anth = dialectos.peticion(
        formato="anthropic_messages", modelo="m", mensajes=mensajes, opt_out=False, max_tokens=100
    )
    gem = dialectos.peticion(
        formato="gemini_generate", modelo="m", mensajes=mensajes, opt_out=False, max_tokens=100
    )
    assert len(abierto["messages"]) == 3  # el sistema va dentro
    assert len(anth["messages"]) == 2 and anth["system"] == "eres X"
    assert len(gem["contents"]) == 2
    # Gemini llama «model» a lo que las otras llaman «assistant». Un historial
    # con el rol equivocado se acepta y se contesta como si lo hubiera dicho el
    # usuario, que es un fallo que no da error.
    assert [c["role"] for c in gem["contents"]] == ["user", "model"]


def test_las_herramientas_se_declaran_como_cada_familia_las_pide() -> None:
    herramientas = [{"nombre": "buscar", "descripcion": "busca", "parametros": {"type": "object"}}]
    abierto = dialectos.peticion(
        formato="openai_chat",
        modelo="m",
        mensajes=[],
        opt_out=False,
        herramientas=herramientas,
        max_tokens=10,
    )
    anth = dialectos.peticion(
        formato="anthropic_messages",
        modelo="m",
        mensajes=[],
        opt_out=False,
        herramientas=herramientas,
        max_tokens=10,
    )
    gem = dialectos.peticion(
        formato="gemini_generate",
        modelo="m",
        mensajes=[],
        opt_out=False,
        herramientas=herramientas,
        max_tokens=10,
    )
    assert abierto["tools"][0]["function"]["name"] == "buscar"
    assert anth["tools"][0]["input_schema"] == {"type": "object"}
    assert gem["tools"][0]["functionDeclarations"][0]["name"] == "buscar"


def test_el_opt_out_no_se_manda_a_ciegas_cuando_la_familia_no_tiene_campo() -> None:
    """La garantía que se le da al cliente es técnica: viaja en la petición. Un
    proveedor que dice admitirla y no declara por dónde se pide se para aquí, en
    vez de mandar un campo inventado que el proveedor rechaza —o peor, ignora."""
    with pytest.raises(ErrorDependencia) as exc:
        dialectos.peticion(
            formato="anthropic_messages", modelo="m", mensajes=[], opt_out=True, max_tokens=10
        )
    assert exc.value.error_code == "ia.opt_out_sin_campo"
    # Declarándolo, sí viaja.
    cuerpo = dialectos.peticion(
        formato="anthropic_messages",
        modelo="m",
        mensajes=[],
        opt_out=True,
        max_tokens=10,
        campo_opt_out="no_entrenar",
    )
    assert cuerpo["no_entrenar"] is False


def test_la_familia_openai_conserva_su_campo_de_siempre() -> None:
    """`store` no es un invento de este módulo: es el campo real de esa familia,
    y quitarlo habría cambiado el comportamiento de los proveedores ya
    declarados sin que nadie lo pidiera."""
    cuerpo = dialectos.peticion(
        formato="openai_chat", modelo="m", mensajes=[], opt_out=True, max_tokens=10
    )
    assert cuerpo["store"] is False


# ── Qué se lee de vuelta ──────────────────────────────────────────────────


def test_las_tres_familias_se_leen_con_las_mismas_claves() -> None:
    """Si no, el `if` por familia estaría repartido por todo el servicio en vez
    de estar en un sitio."""
    salidas = [
        dialectos.respuesta(
            formato="openai_chat",
            datos={
                "model": "m",
                "choices": [{"message": {"content": "hola"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 4},
            },
        ),
        dialectos.respuesta(
            formato="anthropic_messages",
            datos={
                "model": "m",
                "content": [{"type": "text", "text": "hola"}],
                "usage": {"input_tokens": 3, "output_tokens": 4},
            },
        ),
        dialectos.respuesta(
            formato="gemini_generate",
            datos={
                "modelVersion": "m",
                "candidates": [{"content": {"parts": [{"text": "hola"}]}}],
                "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 4},
            },
        ),
    ]
    for salida in salidas:
        assert salida["texto"] == "hola"
        assert salida["modelo"] == "m"
        assert (salida["tokens_entrada"], salida["tokens_salida"]) == (3, 4)
        assert salida["llamadas"] == []


def test_la_llamada_a_herramienta_se_lee_igual_venga_de_donde_venga() -> None:
    esperado = [{"herramienta": "buscar", "argumentos": {"q": "acme"}}]
    de_openai = dialectos.respuesta(
        formato="openai_chat",
        datos={
            "choices": [
                {
                    "message": {
                        "content": "",
                        # En esta familia los argumentos vienen como TEXTO con
                        # JSON dentro, no como objeto.
                        "tool_calls": [
                            {
                                "id": "c1",
                                "function": {"name": "buscar", "arguments": '{"q": "acme"}'},
                            }
                        ],
                    }
                }
            ]
        },
    )
    de_anthropic = dialectos.respuesta(
        formato="anthropic_messages",
        datos={
            "content": [{"type": "tool_use", "id": "c1", "name": "buscar", "input": {"q": "acme"}}]
        },
    )
    de_gemini = dialectos.respuesta(
        formato="gemini_generate",
        datos={
            "candidates": [
                {
                    "content": {
                        "parts": [{"functionCall": {"name": "buscar", "args": {"q": "acme"}}}]
                    }
                }
            ]
        },
    )
    for salida in (de_openai, de_anthropic, de_gemini):
        assert [
            {"herramienta": c["herramienta"], "argumentos": c["argumentos"]}
            for c in salida["llamadas"]
        ] == esperado


def test_unos_argumentos_ilegibles_no_tumban_la_respuesta() -> None:
    """Un JSON roto en los argumentos es cosa del modelo, no del servicio. Quien
    llama ya sabe decir que a un paso le faltan argumentos, y eso se entiende
    mucho mejor que una excepción de decodificación a tres capas."""
    salida = dialectos.respuesta(
        formato="openai_chat",
        datos={
            "choices": [
                {"message": {"tool_calls": [{"function": {"name": "x", "arguments": "{roto"}}]}}
            ]
        },
    )
    assert salida["llamadas"][0]["argumentos"] == {}


def test_lo_que_una_familia_no_sabe_hacer_se_dice_en_vez_de_simularse() -> None:
    """Sin esto, «el modelo a veces no devuelve JSON» parece un fallo del modelo
    cuando es que nadie se lo pidió por donde se pide."""
    assert dialectos.avisos_de("anthropic_messages", formato_json=True, herramientas=False)
    assert not dialectos.avisos_de("openai_chat", formato_json=True, herramientas=False)


def test_las_cabeceras_salen_de_la_configuracion_y_no_de_un_if_por_casa() -> None:
    """La versión de la API, la cabecera de autenticación y cualquier otra que
    exija un proveedor son configuración. Un `if proveedor ==` aquí sería el
    primer módulo por casa del servicio."""
    cabeceras = dialectos.cabeceras_de(
        "anthropic_messages",
        {
            "cabecera_auth": "x-api-key",
            "credencial": "secreto",
            "cabeceras": {"anthropic-version": "2023-06-01"},
        },
    )
    assert cabeceras["x-api-key"] == "secreto"
    assert cabeceras["anthropic-version"] == "2023-06-01"
    assert cabeceras["Content-Type"] == "application/json"
