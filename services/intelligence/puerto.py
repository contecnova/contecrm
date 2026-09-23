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
    # `sesion(sistema=True)`: `sesion_admin` no existe, así que esta llamada
    # reventaba con ImportError en cuanto se usaba un proveedor de IA.
    from crmcore.db.session import sesion
    from crmcore.red import cliente_seguro
    from sqlalchemy import select

    from services.intelligence.enrutador import ProveedorIA

    with sesion(sistema=True) as db:
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


def _resumir(
    *, proveedor: str, modelo: str, mensajes: list[dict[str, Any]], opt_out: bool
) -> dict[str, Any]:
    """Resume una conversación y separa lo que quedó pendiente.

    Los pendientes van en su propio campo a propósito: es lo que el siguiente
    agente lee primero y lo que más se inventa un modelo, así que se revisa
    aparte en vez de tener que releer el resumen entero buscando compromisos.
    """
    import json

    transcripcion = "\n".join(
        f"[{m.get('origen') or 'desconocido'}] {m.get('texto') or ''}" for m in mensajes
    )
    peticion = [
        {
            "role": "system",
            "content": (
                "Resume esta conversación de atención al cliente para el agente que "
                "la recoge. Devuelve SOLO un JSON con `resumen` (texto breve) y "
                "`pendientes` (lista de compromisos EXPLÍCITOS que aparezcan en la "
                "conversación). Si no se prometió nada, `pendientes` va vacío: no "
                "inventes compromisos, porque el siguiente agente los dará por buenos."
            ),
        },
        {"role": "user", "content": transcripcion},
    ]
    salida = _llamar(
        proveedor=proveedor, modelo=modelo, mensajes=peticion, opt_out=opt_out, formato_json=True
    )
    try:
        datos = json.loads(salida.get("texto") or "{}")
    except json.JSONDecodeError:
        datos = {}
    return {
        **salida,
        "texto": str(datos.get("resumen") or ""),
        "pendientes": list(datos.get("pendientes") or []),
    }


def _clasificar(
    *,
    proveedor: str,
    modelo: str,
    texto: str,
    sentimientos: list[str],
    intenciones: list[str],
    opt_out: bool,
) -> dict[str, Any]:
    """Sentimiento e intención, con confianza y con las palabras en que se apoya.

    Se le piden las etiquetas de una lista cerrada y se le exige la confianza: sin
    ella no hay forma de separar «está enfadado» de «puede que esté enfadado», y
    esa diferencia es la que decide si se avisa a un supervisor.
    """
    import json

    peticion = [
        {
            "role": "system",
            "content": (
                "Clasifica el mensaje del cliente. Devuelve SOLO un JSON con "
                f"`sentimiento` (uno de {sentimientos}), `intencion` (una de "
                f"{intenciones}), `confianza` (0-1) y `indicios` (fragmentos "
                "LITERALES del mensaje en los que te apoyas). Si el mensaje no da "
                "para decidir, baja la confianza en vez de elegir al azar."
            ),
        },
        {"role": "user", "content": texto},
    ]
    salida = _llamar(
        proveedor=proveedor, modelo=modelo, mensajes=peticion, opt_out=opt_out, formato_json=True
    )
    try:
        datos = json.loads(salida.get("texto") or "{}")
    except json.JSONDecodeError:
        datos = {}
    return {
        **salida,
        "sentimiento": datos.get("sentimiento"),
        "intencion": datos.get("intencion"),
        "confianza": datos.get("confianza") or 0,
        "indicios": list(datos.get("indicios") or []),
    }


def _planificar(
    *,
    proveedor: str,
    modelo: str,
    objetivo: str,
    contexto: dict[str, Any],
    herramientas: list[dict[str, Any]],
    opt_out: bool,
) -> dict[str, Any]:
    """Pide un plan de pasos, no una respuesta.

    Se le da el catálogo de herramientas **que el agente tiene**, no todas las del
    CRM: un modelo al que se le enseña una herramienta que no puede usar la pide,
    y entonces el plan se llena de pasos que van a fallar.
    """
    import json

    peticion = [
        {
            "role": "system",
            "content": (
                "Eres un planificador. Devuelve SOLO un JSON con `pasos`: lista de "
                "{herramienta, argumentos, porque, importe (si lo hay), "
                "compensacion {herramienta, argumentos} si el paso se puede "
                "deshacer}. Usa ÚNICAMENTE las herramientas de la lista. Si un "
                "paso no se puede deshacer, no inventes una compensación: deja el "
                "campo fuera."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Objetivo: {objetivo}\n\n"
                f"Contexto: {json.dumps(contexto, ensure_ascii=False)}\n\n"
                f"Herramientas: {json.dumps(herramientas, ensure_ascii=False)}"
            ),
        },
    ]
    salida = _llamar(
        proveedor=proveedor, modelo=modelo, mensajes=peticion, opt_out=opt_out, formato_json=True
    )
    try:
        datos = json.loads(salida.get("texto") or "{}")
    except json.JSONDecodeError:
        datos = {}
    return {**salida, "pasos": list(datos.get("pasos") or [])}


def _invocar_herramienta(
    *,
    herramienta: str,
    argumentos: dict[str, Any],
    principal_id: Any = None,
    permisos: list[str] | None = None,
) -> dict[str, Any]:
    """Llama a la herramienta por la API del CRM, con la identidad del agente.

    Por la API y no por la base de datos: un agente que escribiera directamente
    se saltaría el metamodelo, los permisos y las reglas de negocio, que es lo
    que hace que un CRM tenga una sola verdad sobre qué se puede hacer.

    Va sin implementar contra un despliegue concreto a propósito: la dirección
    del gateway y la credencial del agente son configuración, y el módulo que las
    resuelve es el mismo que resuelve las de cualquier otra llamada saliente.
    """
    raise ErrorDependencia(
        "Este despliegue no tiene conectado el invocador de herramientas del "
        "agente. Sin él, un agente puede planificar pero no actuar — y eso es "
        "mejor que actuar a medias.",
        error_code="agente.invocador_no_configurado",
        detalle={"herramienta": herramienta},
    )


def conectar() -> None:
    """Registra los puertos en sus módulos."""
    from services.intelligence import agentes, conversacion, extraccion, generacion, rag

    generacion.registrar_generador(_generar)
    rag.registrar_respondedor(_responder)
    rag.registrar_traductor(_traducir_a_plan)
    extraccion.registrar_extractor(_extraer)
    conversacion.registrar_resumidor(_resumir)
    conversacion.registrar_clasificador(_clasificar)
    agentes.registrar_planificador(_planificar)
    agentes.registrar_invocador(_invocar_herramienta)
    logger.info("intelligence.puertos_conectados")
