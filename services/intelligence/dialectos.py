"""Traducción entre lo que este servicio quiere decir y cómo lo dice cada
familia de proveedores (CRM-05.02.02.10).

`ProveedorIA.formato` existía desde el principio, se guardaba, se enseñaba en la
consola… **y no lo leía nadie**. `puerto._llamar` construía siempre el cuerpo de
la familia OpenAI, así que un tenant que declarara un proveedor Anthropic o
Gemini tenía la pantalla correcta, la fila correcta en la base de datos y una
llamada que el proveedor rechazaba con un 400 ilegible. Es el circuito abierto de
siempre: las dos mitades estaban, nada las unía.

Aquí está la unión, y está en su propio módulo por una razón concreta: es lo
único de la casa que sabe cómo se llama cada campo en cada familia, y quiero
poder probarlo **sin red**. Las pruebas le dan un cuerpo de respuesta de cada
familia y comprueban que sale lo mismo; si mañana una familia cambia un nombre,
se cambia en un sitio.

Las decisiones:

**Tres familias, no veinte proveedores.** Azure, groq, mistral, deepseek,
together y cualquier otro clon hablan `openai_chat`; declararlos uno a uno sería
justo la lista escrita a mano que esta casa no quiere. Lo que se declara es el
dialecto y la dirección.

**Lista cerrada y comprobada al declarar.** `formato` era texto libre: se podía
guardar «openai» o «Anthropic» y la fila quedaba bien guardada y mal llamada.
Ahora se valida igual que la región.

**El dialecto traduce, no decide.** Qué se le pide al modelo, con qué
herramientas y con qué guardarraíles lo decide quien llama. Aquí sólo se cambia
de idioma, en los dos sentidos.

**Lo que una familia no sabe hacer se dice, no se simula.** La familia Anthropic
no tiene un interruptor de «devuélveme JSON»; se devuelve en `avisos` y quien
llama ya se lo pide por el texto del sistema. Fingir que están los tres botones
haría que el fallo apareciera en la respuesta y no en la llamada.
"""

from __future__ import annotations

import json
from typing import Any

from crmcore.errors import ErrorDependencia, ErrorValidacion
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Las familias que se saben hablar. Una familia, no un proveedor: groq, mistral,
# deepseek, together y Azure OpenAI son todos `openai_chat`, y meterlos como
# entradas distintas sería volver a la lista escrita a mano que se queda corta
# en cuanto aparece el séptimo clon.
DIALECTOS = ("openai_chat", "anthropic_messages", "gemini_generate")

# Dónde cuelga la conversación en cada familia, cuando el proveedor no declara
# otra ruta en su `config`. La de Gemini lleva el modelo DENTRO del camino, que
# es justo la clase de detalle por el que hace falta este módulo.
_RUTA = {
    "openai_chat": "/chat/completions",
    "anthropic_messages": "/v1/messages",
    "gemini_generate": "/v1beta/models/{modelo}:generateContent",
}

# El campo con el que se pide no entrenar con lo enviado, cuando la familia
# tiene uno de verdad. Las otras dos no lo tienen en el cuerpo: lo que se pide
# por contrato, y por eso el proveedor que diga admitir opt-out **tiene que
# declarar en su config en qué campo se pide**. Inventarlo aquí mandaría un
# campo desconocido y lo que volvería es un 400, no una garantía.
_CAMPO_OPT_OUT = {"openai_chat": "store"}


# Lo que el catálogo de herramientas anota para USO INTERNO y no puede salir.
#
# `in` dice si cada parámetro va en el camino, en la consulta o en el cuerpo, y
# lo necesita `puerto._repartir_argumentos` para colocar lo que devuelve el
# modelo. Pero vive dentro del esquema del parámetro, y ese esquema se manda al
# proveedor tal cual: es JSON Schema, y `in` no es de JSON Schema.
#
# Medido el 29-10-2026: dos familias se lo tragan sin decir nada y **Gemini
# rechaza la llamada entera** con «Unknown name "in" … Cannot find field», una
# línea por cada parámetro de cada herramienta. Se quita aquí, en la frontera,
# y no en el catálogo: el dato hace falta dentro.
_SOLO_NUESTRO = ("in",)


def _esquema_hacia_fuera(esquema: Any) -> Any:
    """El mismo esquema sin lo que es anotación nuestra, a cualquier profundidad.

    Recursivo porque un parámetro puede ser un objeto con propiedades o una
    lista de objetos, y limpiar solo el primer nivel deja la llamada rechazada
    igual — con el mismo error y un sitio menos donde buscarlo.
    """
    if isinstance(esquema, dict):
        return {
            clave: _esquema_hacia_fuera(valor)
            for clave, valor in esquema.items()
            if clave not in _SOLO_NUESTRO
        }
    if isinstance(esquema, list):
        return [_esquema_hacia_fuera(x) for x in esquema]
    return esquema


def exigir_dialecto(formato: str) -> str:
    """Comprueba que el dialecto declarado es uno de los que se saben hablar."""
    if formato not in DIALECTOS:
        raise ErrorValidacion(
            f"El formato «{formato}» no es ninguno de los dialectos que se saben "
            "hablar. Un proveedor con un formato desconocido se guarda bien y se "
            "llama mal.",
            error_code="ia.dialecto_desconocido",
            detalle={"validos": list(DIALECTOS)},
        )
    return formato


def ruta_de(formato: str, *, modelo: str, declarada: str = "") -> str:
    """El camino al que se manda la petición."""
    plantilla = declarada or _RUTA[exigir_dialecto(formato)]
    return plantilla.replace("{modelo}", modelo or "")


def peticion(
    *,
    formato: str,
    modelo: str,
    mensajes: list[dict[str, str]],
    opt_out: bool,
    formato_json: bool = False,
    herramientas: list[dict[str, Any]] | None = None,
    max_tokens: int,
    campo_opt_out: str = "",
) -> dict[str, Any]:
    """El cuerpo de la petición, en el idioma de la familia.

    `mensajes` llega siempre en el dialecto neutro —el de la familia OpenAI, por
    ser el que más se parece a los demás—: una lista de `{role, content}` donde
    `role` puede ser `system`, `user` o `assistant`. Las otras dos familias sacan
    el sistema fuera de la lista, y eso se hace aquí y no en quien llama.
    """
    exigir_dialecto(formato)
    sistema = "\n\n".join(
        str(m.get("content") or "") for m in mensajes if m.get("role") == "system"
    )
    turnos = [m for m in mensajes if m.get("role") != "system"]

    if formato == "openai_chat":
        cuerpo: dict[str, Any] = {"model": modelo or "", "messages": list(mensajes)}
        if formato_json:
            cuerpo["response_format"] = {"type": "json_object"}
        if herramientas:
            cuerpo["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": h["nombre"],
                        "description": h.get("descripcion") or "",
                        "parameters": _esquema_hacia_fuera(
                            h.get("parametros") or {"type": "object", "properties": {}}
                        ),
                    },
                }
                for h in herramientas
            ]
    elif formato == "anthropic_messages":
        # `max_tokens` es obligatorio en esta familia, no opcional como en las
        # otras dos. Sin él la llamada se rechaza, así que quien llama lo pasa
        # siempre y sale de configuración, no de una constante.
        cuerpo = {
            "model": modelo or "",
            "max_tokens": max_tokens,
            "messages": [
                {"role": m.get("role") or "user", "content": str(m.get("content") or "")}
                for m in turnos
            ],
        }
        if sistema:
            cuerpo["system"] = sistema
        if herramientas:
            cuerpo["tools"] = [
                {
                    "name": h["nombre"],
                    "description": h.get("descripcion") or "",
                    "input_schema": _esquema_hacia_fuera(
                        h.get("parametros") or {"type": "object", "properties": {}}
                    ),
                }
                for h in herramientas
            ]
    else:  # gemini_generate
        cuerpo = {
            "contents": [
                {
                    # Gemini llama «model» a lo que las otras dos llaman
                    # «assistant». Un historial con el rol equivocado se acepta
                    # y se contesta como si lo hubiera dicho el usuario.
                    "role": "model" if m.get("role") == "assistant" else "user",
                    "parts": [{"text": str(m.get("content") or "")}],
                }
                for m in turnos
            ]
        }
        if sistema:
            cuerpo["systemInstruction"] = {"parts": [{"text": sistema}]}
        config: dict[str, Any] = {"maxOutputTokens": max_tokens}
        if formato_json:
            config["responseMimeType"] = "application/json"
        cuerpo["generationConfig"] = config
        if herramientas:
            cuerpo["tools"] = [
                {
                    "functionDeclarations": [
                        {
                            "name": h["nombre"],
                            "description": h.get("descripcion") or "",
                            "parameters": _esquema_hacia_fuera(
                                h.get("parametros") or {"type": "object", "properties": {}}
                            ),
                        }
                        for h in herramientas
                    ]
                }
            ]

    if opt_out:
        campo = campo_opt_out or _CAMPO_OPT_OUT.get(formato) or ""
        if not campo:
            raise ErrorDependencia(
                "Este proveedor dice admitir opt-out de entrenamiento pero no "
                "declara en qué campo se pide, y su familia no tiene uno "
                "estándar. Se para aquí: mandar la petición sin el campo sería "
                "dar por buena una garantía que no viaja.",
                error_code="ia.opt_out_sin_campo",
                detalle={"formato": formato},
            )
        cuerpo[campo] = False

    return cuerpo


def avisos_de(formato: str, *, formato_json: bool, herramientas: bool) -> list[str]:
    """Lo que se ha pedido y esta familia no sabe hacer de verdad.

    Se devuelve en vez de callarse porque la diferencia se nota en la respuesta
    y no en la llamada: sin esto, «el modelo a veces no devuelve JSON» parece un
    fallo del modelo cuando es que nadie se lo pidió por donde se pide.
    """
    avisos: list[str] = []
    if formato_json and formato == "anthropic_messages":
        avisos.append(
            "Esta familia no tiene modo JSON en la petición: el JSON se pide por "
            "el texto del sistema y puede venir envuelto en texto."
        )
    if herramientas and formato not in DIALECTOS:  # pragma: no cover — lo ataja exigir_dialecto
        avisos.append("Familia desconocida: no se sabe cómo se le declaran herramientas.")
    return avisos


def cabeceras_de(formato: str, config: dict[str, Any]) -> dict[str, str]:
    """Las cabeceras de la llamada, según lo que declare el proveedor.

    Genérico a propósito: la cabecera de autenticación y las que haga falta
    añadir —la versión de la API, por ejemplo— salen de `config`, no de un `if`
    por casa. Lo único que pone la familia es el `Content-Type`.
    """
    exigir_dialecto(formato)
    cabeceras = {"Content-Type": "application/json"}
    for nombre, valor in (config.get("cabeceras") or {}).items():
        cabeceras[str(nombre)] = str(valor)
    if config.get("cabecera_auth"):
        cabeceras[str(config["cabecera_auth"])] = str(config.get("credencial") or "")
    return cabeceras


def respuesta(*, formato: str, datos: dict[str, Any], modelo_pedido: str = "") -> dict[str, Any]:
    """Lee la respuesta de la familia y la devuelve en el dialecto neutro.

    Siempre con las mismas claves —`texto`, `modelo`, los dos contadores de
    tokens y `llamadas`—, porque quien llama no tiene por qué saber de qué
    familia vino: si lo supiera, el `if` por familia estaría repartido por todo
    el servicio en vez de estar aquí.
    """
    exigir_dialecto(formato)
    if formato == "openai_chat":
        opciones = datos.get("choices") or []
        mensaje = (opciones[0].get("message") or {}) if opciones else {}
        uso = datos.get("usage") or {}
        return {
            "texto": str(mensaje.get("content") or ""),
            "modelo": str(datos.get("model") or modelo_pedido),
            "tokens_entrada": int(uso.get("prompt_tokens") or 0),
            "tokens_salida": int(uso.get("completion_tokens") or 0),
            "llamadas": [
                {
                    "id": str(llamada.get("id") or ""),
                    "herramienta": str((llamada.get("function") or {}).get("name") or ""),
                    "argumentos": _json_o_vacio((llamada.get("function") or {}).get("arguments")),
                }
                for llamada in (mensaje.get("tool_calls") or [])
            ],
        }

    if formato == "anthropic_messages":
        bloques = datos.get("content") or []
        uso = datos.get("usage") or {}
        return {
            "texto": "".join(str(b.get("text") or "") for b in bloques if b.get("type") == "text"),
            "modelo": str(datos.get("model") or modelo_pedido),
            "tokens_entrada": int(uso.get("input_tokens") or 0),
            "tokens_salida": int(uso.get("output_tokens") or 0),
            "llamadas": [
                {
                    "id": str(b.get("id") or ""),
                    "herramienta": str(b.get("name") or ""),
                    "argumentos": dict(b.get("input") or {}),
                }
                for b in bloques
                if b.get("type") == "tool_use"
            ],
        }

    candidatos = datos.get("candidates") or []
    partes = ((candidatos[0].get("content") or {}).get("parts") or []) if candidatos else []
    uso = datos.get("usageMetadata") or {}
    return {
        "texto": "".join(str(p.get("text") or "") for p in partes if "text" in p),
        "modelo": str(datos.get("modelVersion") or modelo_pedido),
        "tokens_entrada": int(uso.get("promptTokenCount") or 0),
        # **Los de razonamiento cuentan como salida, porque se facturan.** Los
        # modelos que razonan de esta familia declaran aparte lo que han
        # gastado pensando, y no sale en `candidatesTokenCount`. Medido el
        # 29-10-2026 en una llamada real: 14 de entrada, 40 de respuesta y
        # **979 de razonamiento** — contar sólo la respuesta dejaba el coste en
        # la veinticincoava parte, y con él el presupuesto del tenant, que
        # entonces no corta nunca.
        #
        # La suma cuadra con lo que declara el propio proveedor:
        # 14 + 40 + 979 = 1033 = `totalTokenCount`.
        "tokens_salida": (
            int(uso.get("candidatesTokenCount") or 0) + int(uso.get("thoughtsTokenCount") or 0)
        ),
        "llamadas": [
            {
                "id": "",
                "herramienta": str((p.get("functionCall") or {}).get("name") or ""),
                "argumentos": dict((p.get("functionCall") or {}).get("args") or {}),
            }
            for p in partes
            if p.get("functionCall")
        ],
    }


def _json_o_vacio(texto: Any) -> dict[str, Any]:
    """Los argumentos de la familia OpenAI vienen como TEXTO con JSON dentro.

    Y a veces con JSON roto. Se devuelve vacío en vez de reventar: quien llama
    ya sabe decir que a un paso le faltan argumentos, y eso se entiende mucho
    mejor que una excepción de decodificación a tres capas de distancia.
    """
    if isinstance(texto, dict):
        return dict(texto)
    try:
        datos = json.loads(str(texto or "{}"))
    except json.JSONDecodeError:
        logger.warning("ia.argumentos_ilegibles")
        return {}
    return dict(datos) if isinstance(datos, dict) else {}
