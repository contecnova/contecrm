"""El puerto hacia el modelo: lo único que habla con un proveedor.

Está aparte a propósito y es deliberadamente pequeño. Todo lo demás de este
servicio —enrutado, guardarraíles, plantillas, citación, medición— funciona sin
saber que existe HTTP, y eso es lo que permite probarlo de verdad: las pruebas
conectan un puerto de mentira y comprueban **qué se manda y qué se hace con lo que
vuelve**, que es donde están los fallos que importan.

Y es lo que hace que cambiar de proveedor sea configuración: aquí se traduce al
formato declarado, y no hay un módulo por casa.
"""

from __future__ import annotations

from typing import Any

from crmcore.errors import ErrorDependencia
from crmcore.logging import get_logger

logger = get_logger(__name__)


def _llamar(
    *,
    proveedor: str,
    modelo: str,
    mensajes: list[dict[str, str]],
    opt_out: bool,
    formato_json: bool = False,
) -> dict[str, Any]:
    """Manda la petición al proveedor configurado.

    El opt-out viaja **en la petición**, no solo en el contrato: la garantía que
    se le da al cliente es técnica. Si el proveedor no lo admite, el enrutador ya
    ha descartado usarlo antes de llegar aquí.
    """
    from crmcore.db.session import sesion_admin
    from crmcore.red import cliente_seguro
    from sqlalchemy import select

    from services.intelligence.enrutador import ProveedorIA

    with sesion_admin() as db:
        ficha = (
            db.execute(select(ProveedorIA).where(ProveedorIA.clave == proveedor)).scalars().first()
        )
    if ficha is None:
        raise ErrorDependencia(
            f"El proveedor «{proveedor}» ya no está configurado",
            error_code="ia.proveedor_desaparecido",
        )

    cuerpo: dict[str, Any] = {
        "model": modelo or "",
        "messages": mensajes,
    }
    if opt_out:
        # El nombre del campo lo declara el proveedor en su config: no hay dos
        # que lo llamen igual, y ponerlo aquí sería código por casa.
        clave = str((ficha.config or {}).get("campo_opt_out") or "store")
        cuerpo[clave] = False
    if formato_json:
        cuerpo["response_format"] = {"type": "json_object"}

    url = ficha.base_url.rstrip("/") + str((ficha.config or {}).get("ruta") or "/chat/completions")
    cabeceras = {"Content-Type": "application/json"}
    if (ficha.config or {}).get("cabecera_auth"):
        cabeceras[str(ficha.config["cabecera_auth"])] = str(ficha.config.get("credencial") or "")

    with cliente_seguro(timeout=float((ficha.config or {}).get("timeout_s") or 60)) as cli:
        respuesta = cli.post(url, json=cuerpo, headers=cabeceras)
    if respuesta.status_code >= 400:
        raise ErrorDependencia(
            "El proveedor de IA ha rechazado la petición",
            error_code="ia.peticion_rechazada",
            detalle={"codigo_http": respuesta.status_code},
        )
    datos = respuesta.json()
    opciones = datos.get("choices") or []
    texto = ""
    if opciones:
        texto = str((opciones[0].get("message") or {}).get("content") or "")
    uso_tokens = datos.get("usage") or {}
    return {
        "texto": texto,
        "modelo": str(datos.get("model") or modelo),
        "tokens_entrada": int(uso_tokens.get("prompt_tokens") or 0),
        "tokens_salida": int(uso_tokens.get("completion_tokens") or 0),
    }


def _generar(
    *,
    proveedor: str,
    modelo: str,
    sistema: str,
    prompt: str,
    contexto: str,
    idioma: str,
    opt_out: bool,
) -> dict[str, Any]:
    mensajes = [
        {
            "role": "system",
            "content": (
                f"{sistema}\n\nResponde en el idioma con código «{idioma}». "
                "Usa únicamente la información del contexto. Si el contexto no "
                "basta, dilo en vez de completarlo."
            ),
        },
        {"role": "user", "content": f"{prompt}\n\n--- CONTEXTO ---\n{contexto}"},
    ]
    return _llamar(proveedor=proveedor, modelo=modelo, mensajes=mensajes, opt_out=opt_out)


def _responder(
    *, proveedor: str, modelo: str, pregunta: str, fragmentos: list[dict[str, Any]], opt_out: bool
) -> dict[str, Any]:
    texto_fragmentos = "\n\n".join(f"[{f['n']}] {f.get('texto') or ''}" for f in fragmentos)
    mensajes = [
        {
            "role": "system",
            "content": (
                "Responde solo con lo que haya en los fragmentos. Cita cada "
                "afirmación con su número entre corchetes. Si los fragmentos no "
                "contienen la respuesta, di exactamente que no lo sabes."
            ),
        },
        {"role": "user", "content": f"{pregunta}\n\n{texto_fragmentos}"},
    ]
    salida = _llamar(proveedor=proveedor, modelo=modelo, mensajes=mensajes, opt_out=opt_out)
    texto = salida.get("texto") or ""
    salida["sin_respuesta"] = "no lo sé" in texto.lower() or "no lo se" in texto.lower()
    return salida


def _traducir_a_plan(
    *, proveedor: str, modelo: str, pregunta: str, modelo_datos: dict[str, Any], opt_out: bool
) -> dict[str, Any]:
    import json

    mensajes = [
        {
            "role": "system",
            "content": (
                "Devuelve SOLO un JSON con `plan` {objeto, campos, filtros, "
                "agrupar_por} y `interpretacion`, una frase en castellano que diga "
                "cómo has entendido la pregunta. No escribas SQL."
            ),
        },
        {
            "role": "user",
            "content": f"{pregunta}\n\nModelo de datos:\n{json.dumps(modelo_datos)[:6000]}",
        },
    ]
    salida = _llamar(
        proveedor=proveedor, modelo=modelo, mensajes=mensajes, opt_out=opt_out, formato_json=True
    )
    try:
        datos = json.loads(salida.get("texto") or "{}")
    except json.JSONDecodeError:
        datos = {}
    return {
        **salida,
        "plan": datos.get("plan") or {},
        "interpretacion": datos.get("interpretacion") or "",
    }


def _extraer(
    *, proveedor: str, modelo: str, texto: str, campos: list[dict[str, Any]], opt_out: bool
) -> dict[str, Any]:
    import json

    mensajes = [
        {
            "role": "system",
            "content": (
                "Extrae los campos pedidos. Devuelve SOLO un JSON con `campos`: "
                "lista de {clave, valor, confianza (0-1), cita}. La `cita` tiene "
                "que ser un fragmento LITERAL del texto. Si un campo no aparece, "
                "no lo incluyas."
            ),
        },
        {"role": "user", "content": f"Campos: {json.dumps(campos)}\n\nTexto:\n{texto}"},
    ]
    salida = _llamar(
        proveedor=proveedor, modelo=modelo, mensajes=mensajes, opt_out=opt_out, formato_json=True
    )
    try:
        datos = json.loads(salida.get("texto") or "{}")
    except json.JSONDecodeError:
        datos = {}
    return {**salida, "campos": datos.get("campos") or []}


def conectar() -> None:
    """Registra los tres puertos en sus módulos."""
    from services.intelligence import extraccion, generacion, rag

    generacion.registrar_generador(_generar)
    rag.registrar_respondedor(_responder)
    rag.registrar_traductor(_traducir_a_plan)
    extraccion.registrar_extractor(_extraer)
    logger.info("intelligence.puertos_conectados")
