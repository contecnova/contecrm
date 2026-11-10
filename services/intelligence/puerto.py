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


def _proveedor_y_config(proveedor: str) -> tuple[Any, dict[str, Any]]:
    """La ficha del proveedor y su configuración, con la credencial puesta."""
    # `sesion(sistema=True)`: `sesion_admin` no existe, así que esta llamada
    # reventaba con ImportError en cuanto se usaba un proveedor de IA.
    from crmcore.db.session import sesion
    from sqlalchemy import select

    from services.intelligence.ajustes import credencial_de
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
    return ficha, config


def _enviar(
    url: str,
    cuerpo: dict[str, Any],
    cabeceras: dict[str, str],
    config: dict[str, Any],
    proveedor: str,
) -> dict[str, Any]:
    """Manda la petición y devuelve el JSON, o lanza con lo que dijo el proveedor."""
    from crmcore.red import cliente_seguro

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
    return dict(respuesta.json())


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
    from services.intelligence import dialectos
    from services.intelligence.ajustes import ajustes

    ficha, config = _proveedor_y_config(proveedor)
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
        opt_out_contrato=str(config.get("opt_out_contrato") or ""),
    )
    url = ficha.base_url.rstrip("/") + dialectos.ruta_de(
        formato, modelo=modelo, declarada=str(config.get("ruta") or "")
    )
    cabeceras = dialectos.cabeceras_de(formato, config)

    datos = _enviar(url, cuerpo, cabeceras, config, proveedor)
    salida = dialectos.respuesta(formato=formato, datos=datos, modelo_pedido=modelo)
    avisos = dialectos.avisos_de(
        formato, formato_json=formato_json, herramientas=bool(herramientas)
    )
    if avisos:
        salida["avisos"] = avisos
    return salida


def _incrustar(
    *, proveedor: str, modelo: str, textos: list[str], dimensiones: int
) -> list[list[float]]:
    """Los vectores de varios textos, en su orden (índice de conocimiento)."""
    from services.intelligence import dialectos

    ficha, config = _proveedor_y_config(proveedor)
    formato = dialectos.exigir_dialecto(ficha.formato)
    url = ficha.base_url.rstrip("/") + dialectos.ruta_de_incrustar(
        formato, modelo=modelo, declarada=str(config.get("ruta_incrustar") or "")
    )
    datos = _enviar(
        url,
        dialectos.peticion_incrustar(
            formato=formato, modelo=modelo, textos=textos, dimensiones=dimensiones
        ),
        dialectos.cabeceras_de(formato, config),
        config,
        proveedor,
    )
    vectores = dialectos.respuesta_incrustar(formato=formato, datos=datos)
    if len(vectores) != len(textos) or any(not v for v in vectores):
        raise ErrorDependencia(
            "El proveedor no ha devuelto un vector por texto",
            error_code="ia.incrustacion_incompleta",
            detalle={"pedidos": len(textos), "devueltos": len(vectores)},
        )
    return vectores


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
                "contienen la respuesta, contesta únicamente «No lo sé.», sin "
                "nada más."
            ),
        },
        {"role": "user", "content": f"{pregunta}\n\n{texto_fragmentos}"},
    ]
    salida = _llamar(proveedor=proveedor, modelo=modelo, mensajes=mensajes, opt_out=opt_out)
    salida["sin_respuesta"] = _dice_que_no_sabe(salida.get("texto") or "")
    return salida


def _dice_que_no_sabe(texto: str) -> bool:
    """Si la respuesta es «no lo sé».

    **Medido el 10-11-2026 con la evaluación de la IA.** El prompt pedía «di
    exactamente que no lo sabes» y el modelo contestaba, literal, «No lo
    sabes.»: el asistente no lo reconocía como «no sé» y lo presentaba como una
    respuesta sin fuentes. Ahora se le pide la frase exacta y se reconoce sin
    depender de la tilde.
    """
    import unicodedata

    plano = "".join(
        c for c in unicodedata.normalize("NFKD", texto.lower()) if not unicodedata.combining(c)
    )
    return "no lo se" in plano


def _traducir_a_plan(
    *, proveedor: str, modelo: str, pregunta: str, modelo_datos: dict[str, Any], opt_out: bool
) -> dict[str, Any]:
    import json

    mensajes = [
        {
            "role": "system",
            "content": (
                "Traduces una pregunta sobre los datos de un CRM a un plan de "
                "consulta. Devuelve SOLO un JSON con `plan` y `interpretacion`.\n"
                "`plan` = {objeto, campos, filtros, agrupar_por, agregado}:\n"
                "- objeto: una `clave` de `objetos` o un nombre de `otros_objetos`.\n"
                "- campos: lista de campos a enseñar (pueden ir vacíos).\n"
                "- filtros: lista de {campo, operador, valor}; operador uno de "
                "=, !=, >, >=, <, <=, en (valor lista), vacio, no_vacio. Las "
                "fechas en AAAA-MM-DD.\n"
                "- agrupar_por: un campo o null.\n"
                "- agregado: {funcion: cuenta|suma|media|minimo|maximo, campo}.\n"
                "Usa SOLO campos que aparezcan en el objeto y, para el estado, los "
                "valores de `valores_de_estado` tal cual. Si el objeto trae "
                "`filtra_por_defecto` y la pregunta es sobre todos los registros, "
                'pon ese campo con operador = y valor "" para quitarlo. '
                "`interpretacion` es una "
                "frase en castellano que diga cómo has entendido la pregunta, con "
                "el periodo y los filtros. No escribas SQL."
            ),
        },
        {
            "role": "user",
            "content": (
                f"{pregunta}\n\nHoy es {_hoy_iso()}.\n\nModelo de datos:\n"
                f"{json.dumps(modelo_datos, ensure_ascii=False)[:12000]}"
            ),
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


def _proponer_accion(
    *,
    proveedor: str,
    modelo: str,
    pregunta: str,
    respuesta: str,
    acciones: list[dict[str, Any]],
    opt_out: bool,
) -> dict[str, Any]:
    """Si la petición pide HACER algo de la lista, cuál y con qué datos.

    Se le enseña sólo la lista de quien pregunta y se le pide que no elija
    ninguna si nadie ha pedido hacer nada: un asistente que propone una tarea a
    cada pregunta acaba con todas descartadas sin leer.
    """
    import json

    peticion = [
        {
            "role": "system",
            "content": (
                "Decides si la persona está pidiendo HACER algo en el CRM. Devuelve "
                "SOLO un JSON con `accion` (una `clave` de la lista, o null si no "
                "pide hacer nada), `argumentos` (sólo campos de esa acción, con "
                "valores sacados de lo que ha escrito; no inventes ninguno) y "
                "`porque` (una frase). Fechas en ISO 8601."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Petición: {pregunta}\n\nRespuesta ya dada: {respuesta or '(ninguna)'}\n\n"
                f"Hoy es {_hoy_iso()}.\n\n"
                f"Acciones: {json.dumps(acciones, ensure_ascii=False)}"
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
    if not isinstance(datos, dict):
        datos = {}
    return {
        **salida,
        "accion": datos.get("accion") or None,
        "argumentos": datos.get("argumentos") if isinstance(datos.get("argumentos"), dict) else {},
        "porque": str(datos.get("porque") or ""),
    }


def _hoy_iso() -> str:
    """La fecha de hoy, para que «este año» o «el mes pasado» se traduzcan bien."""
    from datetime import date

    return date.today().isoformat()


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
                "no lo incluyas. El `valor` es el dato concreto que pide el campo "
                "—un nombre, un número, una fecha—: una palabra genérica («mi "
                "empresa», «el cliente», «un teléfono») no es un valor, y entonces "
                "el campo no aparece. Escribe el `valor` en el formato de su `tipo`: "
                "una fecha en AAAA-MM-DD aunque el texto la diga en palabras, y un "
                "número sin separador de miles y con punto decimal."
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

    Lo que el contrato **no** nombre se manda en el cuerpo si la ruta lo admite.

    **Y en un `GET`, a la consulta.** Antes se descartaba, con el argumento de
    que un parámetro inventado da 422 y el agente no sabría por qué. Medido el
    29-10-2026: es al revés. Los filtros de un listado son nombres de columna
    —`?telefono__vacio=true`— y el contrato no los puede declarar, así que
    todos caían aquí y **la llamada salía sin filtro**. El agente pedía los
    contactos sin teléfono, recibía todos los contactos, y concluía que el
    filtro no funcionaba. Es exactamente lo que este sistema llama en otro
    sitio «un filtro que no filtra, peor que no tener filtros, porque el
    resultado parece correcto».

    Mandarlo y recibir un 422 **sí** dice por qué: el servidor contesta «no se
    puede filtrar por X» **con la lista de los que valen**. Un error que
    enseña es mejor que un acierto que miente.
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

    if sobrantes:
        if admite_cuerpo:
            cuerpo = {**(cuerpo or {}), **sobrantes}
        elif str(declarada.get("metodo") or "").upper() == "GET":
            # Un `GET` no tiene cuerpo: o va en la consulta o no va. Y si no
            # va, la llamada sale sin acotar y devuelve todo.
            consulta.update(sobrantes)

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


def _resumir_reunion(
    *,
    proveedor: str,
    modelo: str,
    texto: str,
    idioma: str,
    tipos: list[str],
    opt_out: bool,
) -> dict[str, Any]:
    """Resumen de una llamada o reunión y lo que se dijo que se haría.

    Cada elemento lleva `quien` y una `cita` LITERAL: sin dueño no es un
    compromiso, y sin cita no se puede comprobar contra lo transcrito.
    """
    import json

    peticion = [
        {
            "role": "system",
            "content": (
                "Resumes la transcripción de una llamada o reunión comercial para "
                "quien la tuvo. Devuelve SOLO un JSON con `resumen` (5-8 frases, en "
                f"el idioma «{idioma}») y `elementos`: lista de {{tipo, texto, quien, "
                "cuando, cita}}. `tipo` es uno de " + ", ".join(tipos) + ". `quien` "
                "es la persona que se comprometió tal como se la nombra; si habla "
                "en primera persona quien tuvo la reunión y no se dice su nombre, "
                "«quien registra la reunión»; si no se sabe, vacío. `cuando` en ISO 8601 si se dijo una fecha o un plazo («antes del 20», «el "
                "viernes 14») para ESE compromiso, o vacío. Lo que una persona promete "
                "en una misma frase —«reviso el contrato y te contesto antes del "
                "lunes»— es un solo elemento, con el plazo en su `cuando`. "
                "`cita` es un fragmento LITERAL de la transcripción, dicho por "
                "`quien`. No inventes compromisos: un `compromiso` o un "
                "`proximo_paso` exige que alguien diga que lo HARÁ, en firme. Lo "
                "condicional, lo hipotético o lo que se deja en el aire —«si me la "
                "mandas, la miro», «si os parece, podríamos montar una prueba», «lo "
                "estudiaremos», «a ver si encontramos hueco», «cuando sepáis algo, "
                "avisad»— no es "
                "compromiso ni próximo paso de nadie: no lo incluyas como tal."
            ),
        },
        {"role": "user", "content": f"Hoy es {_hoy_iso()}.\n\nTranscripción:\n{texto}"},
    ]
    salida = _llamar(
        proveedor=proveedor, modelo=modelo, mensajes=peticion, opt_out=opt_out, formato_json=True
    )
    try:
        datos = json.loads(salida.get("texto") or "{}")
    except json.JSONDecodeError:
        datos = {}
    if not isinstance(datos, dict):
        datos = {}
    elementos = datos.get("elementos")
    return {
        **salida,
        "resumen": str(datos.get("resumen") or ""),
        "elementos": [e for e in elementos if isinstance(e, dict)]
        if isinstance(elementos, list)
        else [],
    }


def _redactar_variantes(
    *,
    proveedor: str,
    modelo: str,
    base: str,
    objetivo: str,
    canal: str,
    cuantas: int,
    idioma: str,
    opt_out: bool,
) -> dict[str, Any]:
    """N versiones distintas de un texto de marketing, para que alguien elija."""
    import json

    peticion = [
        {
            "role": "system",
            "content": (
                f"Escribes {cuantas} variantes DISTINTAS de un texto de marketing para "
                f"el canal «{canal}», en el idioma «{idioma}». Mantén el sentido y los "
                "datos del texto base; no añadas cifras, garantías ni superlativos que "
                "no estén en él, ni palabras que los sugieran («garantiza», «asegura», "
                "«el mejor», «líder», «gratis», «sin compromiso») si la base no las "
                "usa: cada una obliga a quien revisa a comprobarla. Conserva TAL CUAL los marcadores entre llaves "
                "dobles ({{...}}): se rellenan al enviar. Devuelve SOLO un JSON con `variantes`: lista de "
                "textos."
            ),
        },
        {
            "role": "user",
            "content": f"Objetivo: {objetivo or '(no dicho)'}\n\nTexto base:\n{base}",
        },
    ]
    salida = _llamar(
        proveedor=proveedor, modelo=modelo, mensajes=peticion, opt_out=opt_out, formato_json=True
    )
    try:
        datos = json.loads(salida.get("texto") or "{}")
    except json.JSONDecodeError:
        datos = {}
    variantes = datos.get("variantes") if isinstance(datos, dict) else None
    return {
        **salida,
        "variantes": [str(v) for v in variantes if isinstance(v, str)]
        if isinstance(variantes, list)
        else [],
    }


def conectar() -> None:
    """Registra los puertos en sus módulos."""
    from services.intelligence import (
        acciones_asistente,
        agentes,
        conversacion,
        extraccion,
        generacion,
        indice,
        rag,
        reuniones,
        variantes_copy,
    )

    generacion.registrar_generador(_generar)
    reuniones.registrar_resumidor(_resumir_reunion)
    variantes_copy.registrar_redactor(_redactar_variantes)
    rag.registrar_respondedor(_responder)
    rag.registrar_traductor(_traducir_a_plan)
    extraccion.registrar_extractor(_extraer)
    conversacion.registrar_resumidor(_resumir)
    conversacion.registrar_clasificador(_clasificar)
    agentes.registrar_planificador(_planificar)
    agentes.registrar_continuador(_siguiente_paso)
    agentes.registrar_invocador(_invocar_herramienta)
    indice.registrar_incrustador(_incrustar)
    acciones_asistente.registrar_proponedor(_proponer_accion)
    logger.info("intelligence.puertos_conectados")
