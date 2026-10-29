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
    herramientas: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Manda la petición al proveedor configurado, **en su dialecto**.

    El opt-out viaja **en la petición**, no solo en el contrato: la garantía que
    se le da al cliente es técnica. Si el proveedor no lo admite, el enrutador ya
    ha descartado usarlo antes de llegar aquí.

    Hasta el 28-10-2026 aquí se construía siempre el cuerpo de la familia
    OpenAI, aunque la fila del proveedor dijera otra cosa: `formato` se
    guardaba, se enseñaba y **no lo leía nadie**. Ahora la traducción vive en
    `dialectos` y esto sólo decide a quién se llama y qué se hace con lo que
    vuelve.
    """
    # `sesion(sistema=True)`: `sesion_admin` no existe, así que esta llamada
    # reventaba con ImportError en cuanto se usaba un proveedor de IA.
    from crmcore.db.session import sesion
    from crmcore.red import cliente_seguro
    from sqlalchemy import select

    from services.intelligence import dialectos
    from services.intelligence.ajustes import ajustes, credencial_de
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

    config = dict(ficha.config or {})
    # La credencial, del `.env` y no de la ficha. Un secreto guardado en la
    # base de datos viaja con cada copia, cada volcado, cada clonado a una demo
    # y cada exportación de salida del tenant. Lo que la ficha declara es QUÉ
    # cabecera lleva; el valor lo pone el despliegue.
    if not config.get("credencial"):
        config["credencial"] = credencial_de(ficha.clave)
    formato = dialectos.exigir_dialecto(ficha.formato)
    cuerpo = dialectos.peticion(
        formato=formato,
        modelo=modelo,
        mensajes=mensajes,
        opt_out=opt_out,
        formato_json=formato_json,
        herramientas=herramientas,
        max_tokens=int(config.get("max_tokens") or ajustes().ia_max_tokens_respuesta),
        campo_opt_out=str(config.get("campo_opt_out") or ""),
    )
    url = ficha.base_url.rstrip("/") + dialectos.ruta_de(
        formato, modelo=modelo, declarada=str(config.get("ruta") or "")
    )
    cabeceras = dialectos.cabeceras_de(formato, config)

    with cliente_seguro(timeout=float(config.get("timeout_s") or 60)) as cli:
        respuesta = cli.post(url, json=cuerpo, headers=cabeceras)
    if respuesta.status_code >= 400:
        # **Lo que dijo el proveedor, no sólo que dijo que no.** Con el código
        # HTTP a secas, «400» manda a revisar la credencial cuando lo que falla
        # es un modelo que no existe, un parámetro que esa familia no admite o
        # una cuota agotada — y cada una se arregla en un sitio distinto. Se
        # recorta porque es un mensaje de error, no una respuesta: lo que
        # interesa es la primera frase.
        raise ErrorDependencia(
            "El proveedor de IA ha rechazado la petición",
            error_code="ia.peticion_rechazada",
            detalle={
                "codigo_http": respuesta.status_code,
                "proveedor": proveedor,
                "dijo": respuesta.text[:500],
            },
        )
    salida = dialectos.respuesta(formato=formato, datos=respuesta.json(), modelo_pedido=modelo)
    avisos = dialectos.avisos_de(
        formato, formato_json=formato_json, herramientas=bool(herramientas)
    )
    if avisos:
        salida["avisos"] = avisos
    return salida


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


def _siguiente_paso(
    *,
    proveedor: str,
    modelo: str,
    objetivo: str,
    contexto: dict[str, Any],
    herramientas: list[dict[str, Any]],
    hechos: list[dict[str, Any]],
    opt_out: bool,
) -> dict[str, Any]:
    """Pide UN paso con lo ya hecho delante, o que diga que ya está.

    Es el modo iterativo, y lo que lo hace distinto de `_planificar` no es el
    número de pasos: es que **lo que se le manda incluye los resultados**. Un
    plan cerrado se escribe sin saber qué va a devolver el primer paso, y hay
    objetivos cuya segunda mitad es exactamente eso.

    Se le pide por *tool use* nativo cuando el proveedor lo habla: así los
    argumentos los valida el propio proveedor contra el esquema de la
    herramienta, que es la validación que se pierde pidiendo un JSON de texto.
    Y se lee también el texto: si no llama a ninguna herramienta, lo que escriba
    es su conclusión, no un fallo.
    """
    import json

    peticion = [
        {
            "role": "system",
            "content": (
                "Vas paso a paso. Mira lo ya hecho y llama a UNA sola "
                "herramienta, la que haga falta ahora. Si el objetivo ya está "
                "cumplido —o no se puede cumplir con lo que tienes—, NO llames a "
                "ninguna y escribe la conclusión en texto, diciendo en qué te "
                "apoyas. Un resultado marcado como recortado no significa que no "
                "haya más."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Objetivo: {objetivo}\n\n"
                f"Contexto: {json.dumps(contexto, ensure_ascii=False)}\n\n"
                f"Hecho hasta ahora: {json.dumps(hechos, ensure_ascii=False, default=str)}"
            ),
        },
    ]
    salida = _llamar(
        proveedor=proveedor,
        modelo=modelo,
        mensajes=peticion,
        opt_out=opt_out,
        herramientas=herramientas,
    )
    llamadas = list(salida.get("llamadas") or [])
    if not llamadas:
        return {**salida, "paso": None, "conclusion": salida.get("texto") or ""}
    # Una sola, aunque pida varias: el control humano, el tope y el apagado
    # viven entre paso y paso, y ejecutar tres de golpe porque el modelo las
    # pidió juntas los convierte en decoración.
    primera = llamadas[0]
    return {
        **salida,
        "paso": {
            "herramienta": primera.get("herramienta") or "",
            "argumentos": primera.get("argumentos") or {},
            "porque": salida.get("texto") or "",
        },
        "pedidas_a_la_vez": len(llamadas),
    }


def _invocar_herramienta(
    *,
    herramienta: str,
    argumentos: dict[str, Any],
    definicion: dict[str, Any] | None = None,
    tenant_id: Any = None,
    principal_id: Any = None,
    permisos: list[str] | None = None,
    roles: list[str] | None = None,
) -> dict[str, Any]:
    """Llama a la herramienta por la API del CRM, con la identidad del agente.

    Por la API y no por la base de datos: un agente que escribiera directamente
    se saltaría el metamodelo, los permisos y las reglas de negocio, que es lo
    que hace que un CRM tenga una sola verdad sobre qué se puede hacer.

    **Esto no existía hasta el 27-10-2026.** Lanzaba siempre
    `agente.invocador_no_configurado`, así que un agente planificaba y no
    actuaba **en ningún despliegue** — y `CRM-05.02.03.01` decía «agentes que
    ejecutan procesos» y constaba hecho. La excusa escrita aquí era que la
    dirección y la credencial son configuración; lo eran, y configuración es
    justo lo que esta casa sabe resolver: la dirección sale de
    `RUTAS_SERVICIOS` —la misma que usa el gateway— y la identidad se firma con
    el secreto interno, como cualquier llamada entre servicios.

    El método y la ruta salen de la DECLARACIÓN de la herramienta, no de su
    nombre: el nombre es legible y estable, pero no es una dirección. Una
    herramienta que el agente ya no tiene no se intenta a ciegas.
    """
    from crmcore.http.interno import invocar

    declarada = dict(definicion or {})
    metodo = str(declarada.get("metodo") or "")
    ruta = str(declarada.get("ruta") or "")
    if not metodo or not ruta:
        raise ErrorDependencia(
            f"La herramienta «{herramienta}» no está declarada en este agente, "
            "así que no se sabe a qué ruta llama. No se intenta adivinar.",
            error_code="agente.herramienta_sin_declarar",
            detalle={"herramienta": herramienta},
        )

    ruta_final, consulta, cuerpo = _repartir_argumentos(declarada, argumentos)
    return invocar(
        metodo=metodo,
        ruta=ruta_final,
        parametros=consulta,
        cuerpo=cuerpo,
        tenant_id=tenant_id,
        principal_id=principal_id,
        permisos=list(permisos or []),
        # Los roles deciden QUÉ CAMPOS ve de lo que le devuelvan. Sin ellos,
        # la política de sensibilidad lo manda al comodín y recibe los valores
        # tapados — con la forma de un dato.
        roles=list(roles or []),
    )


def _repartir_argumentos(
    declarada: dict[str, Any], argumentos: dict[str, Any]
) -> tuple[str, dict[str, Any], dict[str, Any] | None]:
    """Coloca cada argumento donde la ruta lo espera: camino, consulta o cuerpo.

    El contrato ya dice de cada parámetro si va `in: path` o `in: query` —lo
    guarda `herramientas.desde_openapi`—, así que aquí no hay que adivinarlo.
    Adivinarlo por el nombre sería el principio de la lista escrita a mano: un
    `cliente_id` que a veces va en el camino y a veces en la consulta.

    Lo que el contrato **no** nombre se manda en el cuerpo si la ruta lo admite,
    y si no, se descarta — un parámetro inventado en la consulta es un 422 y el
    agente no sabría por qué.
    """
    import re

    ruta = str(declarada.get("ruta") or "")
    propiedades = dict((declarada.get("parametros") or {}).get("properties") or {})
    admite_cuerpo = "cuerpo" in propiedades

    consulta: dict[str, Any] = {}
    cuerpo: dict[str, Any] | None = None
    sobrantes: dict[str, Any] = {}

    for nombre, valor in (argumentos or {}).items():
        if nombre == "cuerpo":
            cuerpo = dict(valor) if isinstance(valor, dict) else {"valor": valor}
            continue
        donde = str((propiedades.get(nombre) or {}).get("in") or "")
        if donde == "path":
            ruta = ruta.replace(f"{{{nombre}}}", str(valor))
        elif donde == "query":
            consulta[nombre] = valor
        else:
            sobrantes[nombre] = valor

    if sobrantes and admite_cuerpo:
        cuerpo = {**(cuerpo or {}), **sobrantes}

    # Un hueco sin rellenar se dice aquí y no se manda: `/cuentas/{cuenta_id}`
    # tal cual llega al servicio como un identificador literal «{cuenta_id}» y
    # vuelve un 404 que no explica nada.
    huecos = re.findall(r"\{([^}]+)\}", ruta)
    if huecos:
        raise ErrorDependencia(
            f"Faltan valores para {', '.join(huecos)} en la ruta de la herramienta",
            error_code="agente.ruta_incompleta",
            detalle={"ruta": ruta, "faltan": huecos},
        )
    return ruta, consulta, cuerpo


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
    agentes.registrar_continuador(_siguiente_paso)
    agentes.registrar_invocador(_invocar_herramienta)
    logger.info("intelligence.puertos_conectados")
