"""El banco de evaluación con el que viene el producto.

**No se evalúa desde aquí.** La primera vez que un tenant evalúa, cada caso que
no tiene se le guarda como suyo —origen «de serie»— y a partir de ahí es
configuración del tenant: se desactiva, se corrige o se le añaden los propios
por la API. Evaluar en caliente contra esta lista haría que el día que el
acierto baje no se pudiera contestar contra qué banco se midió.

Cada caso es una entrada y lo que la respuesta tiene que cumplir. Los criterios
son **comprobables por programa** siempre que se puede: un campo extraído
exacto, una cifra calculada con las filas del propio caso, una cita que existe,
un compromiso con su dueño y su fecha. Sólo los de tipo `juez` le preguntan a un
modelo, y la pantalla lo dice al lado de cada uno.

Las fechas van escritas enteras —«14 de noviembre de 2026»— a propósito: un
«el jueves» haría que el acierto dependiera del día en que se pasa el banco.
"""

from __future__ import annotations

from typing import Any

# Las funciones de IA del producto que se evalúan, con el uso del enrutador que
# las atiende —el mismo con el que las llama la función real—.
FUNCIONES: dict[str, dict[str, str]] = {
    "asistente": {"nombre": "Asistente con conocimiento", "uso": "consulta"},
    "consulta_datos": {"nombre": "Preguntas sobre los datos", "uso": "consulta"},
    "resumen_caso": {"nombre": "Resumen de un caso", "uso": "resumen"},
    "resumen_conversacion": {"nombre": "Resumen de una conversación", "uso": "resumen"},
    "extraccion": {"nombre": "Extracción de datos de un texto", "uso": "extraccion"},
    "compromisos_reunion": {"nombre": "Compromisos de una reunión", "uso": "resumen"},
    "variantes_copy": {"nombre": "Variantes de copy", "uso": "redaccion"},
    "clasificacion": {"nombre": "Sentimiento e intención", "uso": "clasificacion"},
    "acciones_asistente": {"nombre": "Acciones del asistente", "uso": "consulta"},
    "plan_agente": {"nombre": "Plan de un agente", "uso": "redaccion"},
}

# ── Lo que se repite entre casos ─────────────────────────────────────────

_FRAGMENTOS_TIENDA = [
    {
        "fuente": "articulo",
        "texto": (
            "Política de devoluciones: el cliente puede devolver un producto en los 30 "
            "días siguientes a la entrega, con el ticket de compra. Los productos "
            "personalizados no admiten devolución."
        ),
    },
    {
        "fuente": "articulo",
        "texto": (
            "Envíos: los pedidos a la península se entregan en 48 horas laborables; "
            "a Baleares y Canarias, en 5 días laborables."
        ),
    },
    {
        "fuente": "articulo",
        "texto": (
            "Garantía: todos los equipos tienen 2 años de garantía. Las baterías "
            "tienen 6 meses de garantía."
        ),
    },
]

_OPORTUNIDADES = {
    "clave": "oportunidades",
    "campos": [
        {"nombre": n}
        for n in ("nombre", "estado", "importe", "cuenta", "propietario", "fecha_cierre")
    ],
    "valores_de_estado": ["abierta", "ganada", "perdida"],
    # Como el listado real: sin decir nada, enseña sólo las abiertas.
    "filtra_por_defecto": {"estado": "abierta"},
}
_CASOS = {
    "clave": "casos",
    "campos": [{"nombre": n} for n in ("asunto", "estado", "prioridad", "cuenta", "abierto_at")],
    "valores_de_estado": ["abierto", "en_curso", "cerrado"],
}


def _op(nombre: str, estado: str, importe: int, cuenta: str, prop: str, cierre: str) -> dict:
    return {
        "nombre": nombre,
        "estado": estado,
        "importe": importe,
        "cuenta": cuenta,
        "propietario": prop,
        "fecha_cierre": cierre,
    }


_FILAS = {
    "oportunidades": [
        _op("Renovación Ebro", "ganada", 12000, "Plásticos Ebro", "Ana", "2026-03-10"),
        _op("Ampliación Ebro", "abierta", 8000, "Plásticos Ebro", "Ana", "2026-12-15"),
        _op("Licencias Norte", "ganada", 55000, "Talleres Norte", "Luis", "2026-06-01"),
        _op("Piloto Norte", "perdida", 4000, "Talleres Norte", "Luis", "2026-02-20"),
        _op("Proyecto Sur", "ganada", 30000, "Conservas Sur", "Ana", "2025-11-30"),
        _op("Soporte Sur", "abierta", 6000, "Conservas Sur", "Marta", "2027-01-15"),
        _op("Migración Delta", "perdida", 70000, "Delta Logística", "Marta", "2026-05-05"),
        _op("Consultoría Delta", "ganada", 15000, "Delta Logística", "Luis", "2026-09-12"),
        _op("Formación Ebro", "abierta", 2500, "Plásticos Ebro", "Marta", "2026-11-30"),
        _op("Integración Norte", "ganada", 60000, "Talleres Norte", "Ana", "2026-10-01"),
    ],
    "casos": [
        {"asunto": "No imprime", "estado": "abierto", "prioridad": "alta", "cuenta": "Ebro"},
        {"asunto": "Factura doble", "estado": "abierto", "prioridad": "alta", "cuenta": "Norte"},
        {"asunto": "Clave caducada", "estado": "en_curso", "prioridad": "alta", "cuenta": "Sur"},
        {
            "asunto": "Cambio de dirección",
            "estado": "abierto",
            "prioridad": "baja",
            "cuenta": "Sur",
        },
        {"asunto": "Pantalla rota", "estado": "cerrado", "prioridad": "alta", "cuenta": "Delta"},
        {"asunto": "Duda de uso", "estado": "abierto", "prioridad": "media", "cuenta": "Ebro"},
    ],
}

_MODELO_DATOS = {
    "objetos": [_OPORTUNIDADES, _CASOS],
    "otros_objetos": ["cuentas", "contactos", "leads"],
}

_ACCIONES = ["crear_tarea", "registrar_nota", "abrir_caso", "capturar_lead"]

_HERRAMIENTAS = [
    {
        "nombre": "listar_cuentas",
        "metodo": "GET",
        "ruta": "/api/v1/accounts",
        "descripcion": "Lista las cuentas, con filtros por campo",
        "parametros": {"type": "object", "properties": {"estado": {"type": "string"}}},
    },
    {
        "nombre": "crear_tarea",
        "metodo": "POST",
        "ruta": "/api/v1/activities",
        "descripcion": "Crea una tarea colgada de un registro",
        "parametros": {
            "type": "object",
            "properties": {
                "asunto": {"type": "string"},
                "vence_at": {"type": "string"},
                "objeto": {"type": "string"},
                "objeto_id": {"type": "string"},
            },
            "required": ["asunto"],
        },
    },
    {
        "nombre": "actualizar_oportunidad",
        "metodo": "PATCH",
        "ruta": "/api/v1/opportunities/{oportunidad_id}",
        "descripcion": "Cambia campos de una oportunidad (estado, importe, etapa…)",
        "parametros": {
            "type": "object",
            "properties": {
                "oportunidad_id": {"type": "string", "in": "path"},
                "estado": {"type": "string"},
            },
            "required": ["oportunidad_id"],
        },
    },
]


def _juez(pregunta: str) -> dict[str, Any]:
    return {"tipo": "juez", "pregunta": pregunta, "esperado": True}


# ── Los casos ─────────────────────────────────────────────────────────────

CASOS: list[dict[str, Any]] = [
    # Asistente con conocimiento: contesta con lo que hay, cita lo que usa y
    # dice que no lo sabe cuando no está.
    {
        "clave": "asistente.devolucion_plazo",
        "funcion": "asistente",
        "nombre": "Plazo de devolución, citado",
        "entrada": {
            "pregunta": "¿Cuántos días tiene un cliente para devolver un producto?",
            "fragmentos": _FRAGMENTOS_TIENDA,
        },
        "criterios": [
            {"tipo": "no_sabe", "valor": False},
            {"tipo": "contiene", "campo": "texto", "valores": ["30"]},
            {"tipo": "cita", "n": 1},
            {"tipo": "citas_validas"},
        ],
    },
    {
        "clave": "asistente.envio_canarias",
        "funcion": "asistente",
        "nombre": "Plazo de envío a Canarias",
        "entrada": {
            "pregunta": "¿Cuánto tarda un envío a Canarias?",
            "fragmentos": _FRAGMENTOS_TIENDA,
        },
        "criterios": [
            {"tipo": "no_sabe", "valor": False},
            {"tipo": "contiene", "campo": "texto", "valores": ["5|cinco"]},
            {"tipo": "no_contiene", "campo": "texto", "valores": ["48 horas"]},
            {"tipo": "cita", "n": 2},
            {"tipo": "citas_validas"},
        ],
    },
    {
        "clave": "asistente.garantia_baterias",
        "funcion": "asistente",
        "nombre": "Garantía de las baterías",
        "entrada": {
            "pregunta": "¿Qué garantía tienen las baterías?",
            "fragmentos": _FRAGMENTOS_TIENDA,
        },
        "criterios": [
            {"tipo": "contiene", "campo": "texto", "valores": ["6 meses|seis meses"]},
            {"tipo": "cita", "n": 3},
            {"tipo": "citas_validas"},
        ],
    },
    {
        "clave": "asistente.personalizado",
        "funcion": "asistente",
        "nombre": "Un producto personalizado no se devuelve",
        "entrada": {
            "pregunta": "Un cliente quiere devolver una taza personalizada con su logo. ¿Puede?",
            "fragmentos": _FRAGMENTOS_TIENDA,
        },
        "criterios": [
            {"tipo": "no_sabe", "valor": False},
            {"tipo": "contiene", "campo": "texto", "valores": ["no"]},
            {"tipo": "contiene", "campo": "texto", "valores": ["personalizad"]},
            {"tipo": "cita", "n": 1},
            {"tipo": "citas_validas"},
        ],
    },
    {
        "clave": "asistente.horario_no_consta",
        "funcion": "asistente",
        "nombre": "Lo que no está en el conocimiento: dice que no lo sabe",
        "entrada": {
            "pregunta": "¿Cuál es el horario de atención telefónica?",
            "fragmentos": _FRAGMENTOS_TIENDA,
        },
        "criterios": [{"tipo": "no_sabe", "valor": True}],
    },
    {
        "clave": "asistente.tarifa_inventada",
        "funcion": "asistente",
        "nombre": "No inventa el precio de una tarifa que no consta",
        "entrada": {
            "pregunta": "¿Cuánto cuesta la tarifa Enterprise por usuario?",
            "fragmentos": [
                {"fuente": "articulo", "texto": "La tarifa Básica cuesta 19 € por usuario y mes."},
                {"fuente": "articulo", "texto": "La tarifa Pro cuesta 49 € por usuario y mes."},
            ],
        },
        "criterios": [{"tipo": "no_sabe", "valor": True}],
    },
    # Preguntas sobre los datos: el plan se ejecuta sobre las filas del propio
    # caso con el mismo agregador que la función real, y la cifra se compara.
    {
        "clave": "consulta.ganadas_cuantas",
        "funcion": "consulta_datos",
        "nombre": "Cuántas oportunidades ganadas",
        "entrada": {
            "pregunta": "¿Cuántas oportunidades ganadas hay?",
            "modelo_datos": _MODELO_DATOS,
            "filas": _FILAS,
        },
        "criterios": [
            {"tipo": "plan_valido"},
            {"tipo": "igual", "campo": "objeto", "valor": "oportunidades"},
            {"tipo": "numero", "campo": "valor", "valor": 5},
        ],
    },
    {
        "clave": "consulta.ganado_2026",
        "funcion": "consulta_datos",
        "nombre": "Importe ganado en un año",
        "entrada": {
            "pregunta": "¿Cuál es el importe total de las oportunidades ganadas con cierre en 2026?",
            "modelo_datos": _MODELO_DATOS,
            "filas": _FILAS,
        },
        "criterios": [
            {"tipo": "plan_valido"},
            {"tipo": "numero", "campo": "valor", "valor": 142000},
        ],
    },
    {
        "clave": "consulta.abiertas_de_marta",
        "funcion": "consulta_datos",
        "nombre": "Abiertas de una persona",
        "entrada": {
            "pregunta": "¿Cuántas oportunidades abiertas tiene Marta?",
            "modelo_datos": _MODELO_DATOS,
            "filas": _FILAS,
        },
        "criterios": [
            {"tipo": "plan_valido"},
            {"tipo": "numero", "campo": "valor", "valor": 2},
        ],
    },
    {
        "clave": "consulta.media_perdidas",
        "funcion": "consulta_datos",
        "nombre": "Importe medio de las perdidas",
        "entrada": {
            "pregunta": "¿Cuál es el importe medio de las oportunidades perdidas?",
            "modelo_datos": _MODELO_DATOS,
            "filas": _FILAS,
        },
        "criterios": [
            {"tipo": "plan_valido"},
            {"tipo": "numero", "campo": "valor", "valor": 37000},
        ],
    },
    {
        "clave": "consulta.todas_sin_filtro_por_defecto",
        "funcion": "consulta_datos",
        "nombre": "Todas, quitando el filtro por defecto del listado",
        "entrada": {
            "pregunta": "¿Cuántas oportunidades hay en total, de cualquier estado?",
            "modelo_datos": _MODELO_DATOS,
            "filas": _FILAS,
        },
        "criterios": [
            {"tipo": "plan_valido"},
            {"tipo": "numero", "campo": "valor", "valor": 10},
        ],
    },
    {
        "clave": "consulta.ganado_por_propietario",
        "funcion": "consulta_datos",
        "nombre": "Ganado por propietario (agrupado)",
        "entrada": {
            "pregunta": "Suma del importe de las oportunidades ganadas, por propietario",
            "modelo_datos": _MODELO_DATOS,
            "filas": _FILAS,
        },
        "criterios": [
            {"tipo": "plan_valido"},
            {"tipo": "grupos", "valores": {"Ana": 102000, "Luis": 70000}},
        ],
    },
    {
        "clave": "consulta.casos_alta_abiertos",
        "funcion": "consulta_datos",
        "nombre": "Casos en estado abierto con prioridad alta",
        "entrada": {
            "pregunta": "¿Cuántos casos en estado abierto tienen prioridad alta?",
            "modelo_datos": _MODELO_DATOS,
            "filas": _FILAS,
        },
        "criterios": [
            {"tipo": "plan_valido"},
            {"tipo": "igual", "campo": "objeto", "valor": "casos"},
            {"tipo": "numero", "campo": "valor", "valor": 2},
        ],
    },
    # Resumen de un caso, con la plantilla vigente del tenant.
    {
        "clave": "resumen_caso.factura_duplicada",
        "funcion": "resumen_caso",
        "nombre": "Factura duplicada, con el abono pendiente",
        "entrada": {
            "asunto": "Factura duplicada de octubre",
            "contexto": (
                "Cliente: Talleres Norte.\n03/11/2026: el cliente escribe que se le ha "
                "cobrado dos veces la factura F-2026-0412, de 1.250 €.\n04/11/2026: el "
                "agente Pedro comprueba en facturación que hay dos cargos con fecha "
                "28/10/2026.\n05/11/2026: facturación confirma el duplicado y pide "
                "autorización para emitir el abono.\nPendiente: emitir el abono de "
                "1.250 € y avisar al cliente cuando esté hecho."
            ),
        },
        "criterios": [
            {"tipo": "contiene", "campo": "texto", "valores": ["0412", "1.250|1250", "abono"]},
            _juez(
                "¿Todo lo que afirma el resumen está en el historial, y deja claro que "
                "el abono todavía NO se ha emitido?"
            ),
        ],
    },
    {
        "clave": "resumen_caso.maquina_parada",
        "funcion": "resumen_caso",
        "nombre": "Máquina parada con visita técnica",
        "entrada": {
            "asunto": "No arranca la envasadora de la línea 2",
            "contexto": (
                "Cliente: Conservas Sur.\n06/11/2026: la envasadora de la línea 2 no "
                "arranca; en pantalla sale el error E-31.\n06/11/2026: soporte remoto "
                "reinicia el controlador sin resultado.\n07/11/2026: se pide la pieza "
                "(placa de control) al almacén central.\nPendiente: visita del técnico "
                "el jueves 13/11/2026 para cambiar la placa."
            ),
        },
        "criterios": [
            {"tipo": "contiene", "campo": "texto", "valores": ["E-31|E31", "placa", "13"]},
            _juez("¿Todo lo que afirma el resumen está en el historial del caso?"),
        ],
    },
    {
        "clave": "resumen_caso.direccion",
        "funcion": "resumen_caso",
        "nombre": "Cambio de dirección de entrega",
        "entrada": {
            "asunto": "Cambio de dirección de entrega",
            "contexto": (
                "Cliente: Plásticos Ebro.\n08/11/2026: el cliente pide que los próximos "
                "pedidos se entreguen en Calle Mayor 12, 50001 Zaragoza, en lugar del "
                "polígono.\n08/11/2026: el agente actualiza la dirección en la ficha.\n"
                "Pendiente: confirmar con logística que el pedido 5531, ya preparado, sale "
                "a la dirección nueva."
            ),
        },
        "criterios": [
            {"tipo": "contiene", "campo": "texto", "valores": ["Mayor 12", "5531"]},
            _juez("¿Todo lo que afirma el resumen está en el historial del caso?"),
        ],
    },
    {
        "clave": "resumen_caso.nada_pendiente",
        "funcion": "resumen_caso",
        "nombre": "Caso resuelto: no se inventa pendientes",
        "entrada": {
            "asunto": "Consulta sobre el informe de ventas",
            "contexto": (
                "Cliente: Delta Logística.\n09/11/2026: el cliente pregunta cómo exportar "
                "el informe de ventas a Excel.\n09/11/2026: el agente le explica que se "
                "hace desde el botón «Exportar» de la cabecera del informe; el cliente "
                "confirma que lo ha hecho y que le funciona. Caso cerrado."
            ),
        },
        "criterios": [
            {"tipo": "contiene", "campo": "texto", "valores": ["export"]},
            _juez(
                "¿El resumen deja claro que no queda nada pendiente, sin inventarse "
                "tareas ni pasos que el historial no diga?"
            ),
        ],
    },
    # Resumen de una conversación: lo pendiente, sólo si se prometió.
    {
        "clave": "conversacion.seguimiento_prometido",
        "funcion": "resumen_conversacion",
        "nombre": "El agente promete el número de seguimiento",
        "entrada": {
            "mensajes": [
                {"origen": "cliente", "texto": "Hola, ¿cómo va mi pedido 5531?"},
                {
                    "origen": "agente",
                    "texto": "Está preparado y sale mañana. En cuanto salga te mando el "
                    "número de seguimiento por correo.",
                },
                {"origen": "cliente", "texto": "Perfecto, gracias."},
            ]
        },
        "criterios": [
            {"tipo": "contiene", "campo": "texto", "valores": ["5531"]},
            {"tipo": "cuantos", "campo": "pendientes", "min": 1, "max": 2},
            {"tipo": "elementos_contienen", "campo": "pendientes", "valores": ["seguimiento"]},
        ],
    },
    {
        "clave": "conversacion.sin_compromisos",
        "funcion": "resumen_conversacion",
        "nombre": "Sin compromisos: pendientes vacío",
        "entrada": {
            "mensajes": [
                {"origen": "cliente", "texto": "No me deja entrar, dice que la clave caducó."},
                {
                    "origen": "agente",
                    "texto": "Te acabo de mandar un enlace para cambiarla. ¿Puedes probar?",
                },
                {"origen": "cliente", "texto": "Ya está, ya he entrado. ¡Gracias!"},
            ]
        },
        "criterios": [
            {"tipo": "contiene", "campo": "texto", "valores": ["clave|contraseña"]},
            {"tipo": "cuantos", "campo": "pendientes", "max": 0},
        ],
    },
    {
        "clave": "conversacion.presupuesto_lunes",
        "funcion": "resumen_conversacion",
        "nombre": "Un compromiso del agente y una condición del cliente",
        "entrada": {
            "mensajes": [
                {
                    "origen": "cliente",
                    "texto": "Si me mandáis el presupuesto de las 10 licencias, lo miro.",
                },
                {"origen": "agente", "texto": "Te lo envío el lunes 17 de noviembre."},
                {"origen": "cliente", "texto": "Vale."},
            ]
        },
        "criterios": [
            {"tipo": "cuantos", "campo": "pendientes", "min": 1, "max": 1},
            {"tipo": "elementos_contienen", "campo": "pendientes", "valores": ["presupuesto"]},
        ],
    },
    {
        "clave": "conversacion.llamada_tarde",
        "funcion": "resumen_conversacion",
        "nombre": "El agente queda en llamar",
        "entrada": {
            "mensajes": [
                {
                    "origen": "cliente",
                    "texto": "La impresora sigue dando el error E-204 aunque la he " "reiniciado.",
                },
                {
                    "origen": "agente",
                    "texto": "Lo consulto con el departamento técnico y te llamo esta "
                    "tarde con la solución.",
                },
                {"origen": "cliente", "texto": "De acuerdo."},
            ]
        },
        "criterios": [
            {"tipo": "contiene", "campo": "texto", "valores": ["E-204|E204"]},
            {"tipo": "cuantos", "campo": "pendientes", "min": 1, "max": 2},
            {"tipo": "elementos_contienen", "campo": "pendientes", "valores": ["llam"]},
        ],
    },
    # Extracción: campos exactos, cita literal y nada que no esté en el texto.
    {
        "clave": "extraccion.firma",
        "funcion": "extraccion",
        "nombre": "Datos de una firma de correo",
        "entrada": {
            "texto": (
                "Un saludo,\nMarta Ruiz Gil\nDirectora de Compras · Conservas del Sur S.L.\n"
                "Tel. +34 954 123 456 · Móvil 612 345 678\nmarta.ruiz@conservasdelsur.es"
            ),
            "campos": [
                {"clave": "cargo", "tipo": "texto", "descripcion": "Cargo de la persona"},
                {"clave": "email", "tipo": "texto", "descripcion": "Correo electrónico"},
                {"clave": "telefono", "tipo": "texto", "descripcion": "Teléfono fijo"},
                {"clave": "movil", "tipo": "texto", "descripcion": "Teléfono móvil"},
                {"clave": "fax", "tipo": "texto", "descripcion": "Número de fax"},
            ],
        },
        "criterios": [
            {
                "tipo": "campos",
                "valores": {
                    "cargo": "Directora de Compras",
                    "email": "marta.ruiz@conservasdelsur.es",
                    "telefono": "+34 954 123 456",
                    "movil": "612 345 678",
                },
                "solo_digitos": ["telefono", "movil"],
            },
            {"tipo": "ausentes", "claves": ["fax"]},
        ],
    },
    {
        "clave": "extraccion.peticion_cliente",
        "funcion": "extraccion",
        "nombre": "Cifras, fecha y persona de un correo de cliente",
        "entrada": {
            "texto": (
                "Hola, os escribo de Talleres Norte. Queremos ampliar a 25 licencias a "
                "partir del 1 de enero de 2027; nuestro presupuesto máximo es de 18.000 "
                "euros. Mi nombre es Jorge Llorente, responsable de IT."
            ),
            "campos": [
                {"clave": "empresa", "tipo": "texto", "descripcion": "Empresa que escribe"},
                {"clave": "licencias", "tipo": "numero", "descripcion": "Licencias pedidas"},
                {"clave": "fecha_inicio", "tipo": "fecha", "descripcion": "Desde cuándo"},
                {"clave": "presupuesto", "tipo": "numero", "descripcion": "Presupuesto en euros"},
                {"clave": "contacto", "tipo": "texto", "descripcion": "Nombre de quien escribe"},
            ],
        },
        "criterios": [
            {
                "tipo": "campos",
                "valores": {
                    "empresa": "Talleres Norte",
                    "licencias": 25,
                    "fecha_inicio": "2027-01-01",
                    "presupuesto": 18000,
                    "contacto": "Jorge Llorente",
                },
            },
        ],
    },
    {
        "clave": "extraccion.factura",
        "funcion": "extraccion",
        "nombre": "Importes con decimales y fechas de una factura",
        "entrada": {
            "texto": (
                "Factura n.º F-2026-0877, fecha 15/10/2026. Base imponible 2.400,00 €, "
                "IVA 21 % (504,00 €), total 2.904,00 €. Vencimiento: 14/11/2026."
            ),
            "campos": [
                {"clave": "numero_factura", "tipo": "texto", "descripcion": "Número"},
                {"clave": "fecha", "tipo": "fecha", "descripcion": "Fecha de la factura"},
                {"clave": "total", "tipo": "numero", "descripcion": "Total con IVA"},
                {"clave": "vencimiento", "tipo": "fecha", "descripcion": "Fecha de vencimiento"},
                {"clave": "iva_pct", "tipo": "numero", "descripcion": "Porcentaje de IVA"},
            ],
        },
        "criterios": [
            {
                "tipo": "campos",
                "valores": {
                    "numero_factura": "F-2026-0877",
                    "fecha": "2026-10-15",
                    "total": 2904,
                    "vencimiento": "2026-11-14",
                    "iva_pct": 21,
                },
            },
        ],
    },
    {
        "clave": "extraccion.direccion",
        "funcion": "extraccion",
        "nombre": "Dirección de entrega",
        "entrada": {
            "texto": (
                "Enviar a: Delta Logística, Polígono Industrial Las Gándaras, nave 7, "
                "36400 Porriño (Pontevedra). Contacto en muelle: Iván, 986 334 455."
            ),
            "campos": [
                {"clave": "codigo_postal", "tipo": "texto", "descripcion": "Código postal"},
                {"clave": "ciudad", "tipo": "texto", "descripcion": "Población"},
                {"clave": "provincia", "tipo": "texto", "descripcion": "Provincia"},
                {"clave": "telefono", "tipo": "texto", "descripcion": "Teléfono de contacto"},
            ],
        },
        "criterios": [
            {
                "tipo": "campos",
                "valores": {
                    "codigo_postal": "36400",
                    "ciudad": "Porriño",
                    "provincia": "Pontevedra",
                    "telefono": "986 334 455",
                },
                "solo_digitos": ["telefono"],
            },
        ],
    },
    {
        "clave": "extraccion.nada_que_sacar",
        "funcion": "extraccion",
        "nombre": "Lo que no está, no se extrae",
        "entrada": {
            "texto": (
                "Llamó un cliente preguntando por el estado de su pedido; no dejó "
                "teléfono ni correo y dijo que volvería a llamar."
            ),
            "campos": [
                {"clave": "telefono", "tipo": "texto", "descripcion": "Teléfono"},
                {"clave": "email", "tipo": "texto", "descripcion": "Correo electrónico"},
                {"clave": "numero_pedido", "tipo": "texto", "descripcion": "Número de pedido"},
            ],
        },
        "criterios": [{"tipo": "ausentes", "claves": ["telefono", "email", "numero_pedido"]}],
    },
    {
        "clave": "extraccion.interes_sin_datos",
        "funcion": "extraccion",
        "nombre": "Interés sin datos de contacto",
        "entrada": {
            "texto": "Me interesa vuestro producto para mi empresa, ¿me podéis llamar?",
            "campos": [
                {"clave": "telefono", "tipo": "texto", "descripcion": "Teléfono"},
                {"clave": "email", "tipo": "texto", "descripcion": "Correo electrónico"},
                {"clave": "empresa", "tipo": "texto", "descripcion": "Nombre de la empresa"},
            ],
        },
        "criterios": [{"tipo": "ausentes", "claves": ["telefono", "email", "empresa"]}],
    },
    # Compromisos de una reunión: dueño, fecha, cita literal, y nada inventado.
    {
        "clave": "reunion.dos_compromisos_y_una_duda",
        "funcion": "compromisos_reunion",
        "nombre": "Dos compromisos y un «lo pensamos»",
        "entrada": {
            "texto": (
                "Ana (comercial): Gracias por la reunión, Jorge. Resumiendo: yo te envío "
                "la propuesta revisada el viernes 14 de noviembre de 2026.\nJorge "
                "(cliente): Perfecto. Yo hablo con mi director financiero y te digo algo "
                "antes del 20 de noviembre de 2026.\nAna: Genial. Y si queréis, podemos "
                "hacer una demo para el equipo de planta.\nJorge: Lo pensamos, ya te diré."
            ),
        },
        "criterios": [
            {"tipo": "compromiso", "quien": "Ana", "texto": "propuesta", "cuando": "2026-11-14"},
            {"tipo": "compromiso", "quien": "Jorge", "texto": "financier", "cuando": "2026-11-20"},
            {"tipo": "ningun_compromiso", "texto": "demo"},
            {"tipo": "citas_literales"},
        ],
    },
    {
        "clave": "reunion.condicional",
        "funcion": "compromisos_reunion",
        "nombre": "Sólo condicionales: ningún compromiso",
        "entrada": {
            "texto": (
                "Cliente: Si me mandas la ficha técnica algún día, la miro.\nComercial: "
                "Claro, cuando lo tengáis claro me decís.\nCliente: Vale, ya veremos."
            ),
        },
        "criterios": [{"tipo": "cuantos", "campo": "compromisos", "max": 0}],
    },
    {
        "clave": "reunion.primera_persona",
        "funcion": "compromisos_reunion",
        "nombre": "Quien registra habla en primera persona",
        "entrada": {
            "texto": (
                "Quedamos en que les preparo dos presupuestos, uno con instalación y otro "
                "sin ella, para el lunes 17 de noviembre de 2026. Sonia Pérez, la "
                "clienta, se compromete a mandarnos los planos de la nave antes del "
                "viernes 21 de noviembre de 2026."
            ),
        },
        "criterios": [
            {"tipo": "compromiso", "quien": "", "texto": "presupuesto", "cuando": "2026-11-17"},
            {"tipo": "compromiso", "quien": "Sonia", "texto": "planos", "cuando": "2026-11-21"},
            {"tipo": "citas_literales"},
        ],
    },
    {
        "clave": "reunion.objecion_y_comparativa",
        "funcion": "compromisos_reunion",
        "nombre": "Una objeción y un compromiso",
        "entrada": {
            "texto": (
                "Cliente: El precio nos parece alto comparado con la competencia. Además, "
                "nuestro contrato actual con el otro proveedor vence en marzo.\n"
                "Luis (comercial): Entiendo. Te preparo una comparativa de coste total a "
                "tres años y te la mando el martes 18 de noviembre de 2026."
            ),
        },
        "criterios": [
            {
                "tipo": "compromiso",
                "quien": "Luis",
                "texto": "comparativa",
                "cuando": "2026-11-18",
            },
            {"tipo": "cuantos", "campo": "compromisos", "max": 1},
            {"tipo": "cuantos", "campo": "elementos", "tipo_elemento": "objecion", "min": 1},
            {"tipo": "citas_literales"},
        ],
    },
    {
        "clave": "reunion.sin_dueno",
        "funcion": "compromisos_reunion",
        "nombre": "Lo que no tiene dueño no se propone",
        "entrada": {
            "texto": (
                "Luis (proveedor): Os enviaremos el contrato firmado mañana, 12 de "
                "noviembre de 2026.\nMarta (cliente): Y yo reviso el anexo de SLA con el "
                "equipo legal.\nLuis: Alguien debería mirar lo de la factura antigua, "
                "pero no sé quién."
            ),
        },
        "criterios": [
            {"tipo": "compromiso", "quien": "Luis", "texto": "contrato", "cuando": "2026-11-12"},
            {"tipo": "compromiso", "quien": "Marta", "texto": "SLA|anexo"},
            {"tipo": "ningun_compromiso", "texto": "factura"},
            {"tipo": "citas_literales"},
        ],
    },
    # Variantes de copy: tantas como se piden, distintas, con los marcadores y
    # sin afirmaciones que la base no hace.
    {
        "clave": "variantes.incidencia_pedido",
        "funcion": "variantes_copy",
        "nombre": "Asunto con marcador",
        "entrada": {
            "base": "Incidencia en tu pedido {{pedido.referencia}}: ya estamos en ello y te "
            "escribimos en cuanto esté resuelta.",
            "objetivo": "Tranquilizar al cliente",
            "canal": "email",
            "cuantas": 3,
        },
        "criterios": [
            {"tipo": "cuantas"},
            {"tipo": "marcadores"},
            {"tipo": "sin_afirmaciones_nuevas"},
        ],
    },
    {
        "clave": "variantes.descuento",
        "funcion": "variantes_copy",
        "nombre": "Una cifra que no se cambia",
        "entrada": {
            "base": "Hola {{contacto.nombre}}, este mes tienes un 10 % de descuento en la "
            "renovación anual de tu licencia.",
            "objetivo": "Que renueve antes de fin de mes",
            "canal": "email",
            "cuantas": 3,
        },
        "criterios": [
            {"tipo": "cuantas"},
            {"tipo": "marcadores"},
            {"tipo": "sin_afirmaciones_nuevas"},
            {"tipo": "elementos_contienen", "campo": "variantes", "valores": ["10"], "todas": True},
        ],
    },
    {
        "clave": "variantes.sms_cita",
        "funcion": "variantes_copy",
        "nombre": "SMS que cabe en un mensaje",
        "entrada": {
            "base": "Tu cita de mantenimiento es el {{cita.fecha}} a las {{cita.hora}}. "
            "Responde NO para cancelarla.",
            "objetivo": "Recordar la cita",
            "canal": "sms",
            "cuantas": 2,
        },
        "criterios": [
            {"tipo": "cuantas"},
            {"tipo": "marcadores"},
            {"tipo": "longitud_max", "campo": "variantes", "valor": 160},
        ],
    },
    {
        "clave": "variantes.novedades",
        "funcion": "variantes_copy",
        "nombre": "Novedades sin superlativos inventados",
        "entrada": {
            "base": "Descubre las novedades de la versión 5: informes más rápidos y un "
            "nuevo panel de ventas.",
            "objetivo": "Que entren a verlo",
            "canal": "push",
            "cuantas": 4,
        },
        "criterios": [{"tipo": "cuantas"}, {"tipo": "sin_afirmaciones_nuevas"}],
    },
    # Sentimiento e intención, de las listas cerradas del producto.
    {
        "clave": "clasificacion.amenaza_baja",
        "funcion": "clasificacion",
        "nombre": "Queja con amenaza de baja",
        "entrada": {
            "texto": "Es la tercera vez que os escribo y nadie me contesta. Si mañana no "
            "está resuelto, cancelo el contrato."
        },
        "criterios": [
            {"tipo": "en", "campo": "sentimiento", "valores": ["negativo", "muy_negativo"]},
            {"tipo": "en", "campo": "intencion", "valores": ["reclamacion", "cancelacion"]},
            {"tipo": "concluyente"},
        ],
    },
    {
        "clave": "clasificacion.agradecimiento",
        "funcion": "clasificacion",
        "nombre": "Agradecimiento",
        "entrada": {
            "texto": "Muchas gracias, Pedro, el problema quedó resuelto y todo funciona "
            "perfectamente."
        },
        "criterios": [
            {"tipo": "en", "campo": "sentimiento", "valores": ["positivo", "muy_positivo"]},
            {"tipo": "igual", "campo": "intencion", "valor": "agradecimiento"},
            {"tipo": "concluyente"},
        ],
    },
    {
        "clave": "clasificacion.presupuesto",
        "funcion": "clasificacion",
        "nombre": "Petición de presupuesto",
        "entrada": {"texto": "¿Me podéis pasar presupuesto para 10 licencias más?"},
        "criterios": [
            {"tipo": "en", "campo": "sentimiento", "valores": ["neutro", "positivo"]},
            {"tipo": "en", "campo": "intencion", "valores": ["presupuesto", "compra"]},
        ],
    },
    {
        "clave": "clasificacion.incidencia",
        "funcion": "clasificacion",
        "nombre": "Incidencia técnica",
        "entrada": {"texto": "La impresora da el error E-204 desde esta mañana y no imprime."},
        "criterios": [
            {"tipo": "en", "campo": "sentimiento", "valores": ["neutro", "negativo"]},
            {"tipo": "igual", "campo": "intencion", "valor": "incidencia"},
        ],
    },
    {
        "clave": "clasificacion.baja",
        "funcion": "clasificacion",
        "nombre": "Petición de baja",
        "entrada": {"texto": "Quiero darme de baja del servicio a final de mes."},
        "criterios": [
            {"tipo": "en", "campo": "sentimiento", "valores": ["neutro", "negativo"]},
            {"tipo": "igual", "campo": "intencion", "valor": "cancelacion"},
        ],
    },
    # Acciones del asistente: la de la lista cuando se pide hacer algo, y
    # ninguna cuando se pregunta.
    {
        "clave": "acciones.tarea",
        "funcion": "acciones_asistente",
        "nombre": "Pide una tarea",
        "entrada": {
            "pregunta": "Créame una tarea para llamar a Jorge por la oferta de licencias.",
            "acciones": _ACCIONES,
        },
        "criterios": [
            {"tipo": "igual", "campo": "accion", "valor": "crear_tarea"},
            {"tipo": "argumentos", "valores": {"asunto": "llam|jorge|oferta"}},
            {"tipo": "cuantos", "campo": "faltan", "max": 0},
        ],
    },
    {
        "clave": "acciones.pregunta_sin_accion",
        "funcion": "acciones_asistente",
        "nombre": "Una pregunta no es una acción",
        "entrada": {
            "pregunta": "¿Cuánto facturamos el mes pasado?",
            "respuesta": "No tengo ese dato en el conocimiento.",
            "acciones": _ACCIONES,
        },
        "criterios": [{"tipo": "igual", "campo": "accion", "valor": None}],
    },
    {
        "clave": "acciones.abrir_caso",
        "funcion": "acciones_asistente",
        "nombre": "Pide abrir un caso",
        "entrada": {
            "pregunta": "Abre un caso: el cliente dice que la envasadora no arranca. "
            "Prioridad alta.",
            "acciones": _ACCIONES,
        },
        "criterios": [
            {"tipo": "igual", "campo": "accion", "valor": "abrir_caso"},
            {"tipo": "argumentos", "valores": {"asunto": "envasadora|arranca"}},
        ],
    },
    {
        "clave": "acciones.nota",
        "funcion": "acciones_asistente",
        "nombre": "Pide apuntar una nota",
        "entrada": {
            "pregunta": "Apunta una nota: el cliente prefiere que le llamemos por la tarde.",
            "acciones": _ACCIONES,
        },
        "criterios": [
            {"tipo": "igual", "campo": "accion", "valor": "registrar_nota"},
            {"tipo": "argumentos", "valores": {"asunto|cuerpo": "tarde"}},
        ],
    },
    {
        "clave": "acciones.lead",
        "funcion": "acciones_asistente",
        "nombre": "Un contacto de feria es un lead",
        "entrada": {
            "pregunta": "Captura como lead a Laura Gómez, de Frutas Levante, que conocí en "
            "la feria; su correo es laura@frutaslevante.es",
            "acciones": _ACCIONES,
        },
        "criterios": [
            {"tipo": "igual", "campo": "accion", "valor": "capturar_lead"},
            {
                "tipo": "argumentos",
                "valores": {"empresa": "frutas levante", "email": "laura@frutaslevante.es"},
            },
        ],
    },
    {
        "clave": "acciones.consulta_agenda",
        "funcion": "acciones_asistente",
        "nombre": "Preguntar por la agenda no crea nada",
        "entrada": {"pregunta": "¿Qué tareas tengo para hoy?", "acciones": _ACCIONES},
        "criterios": [{"tipo": "igual", "campo": "accion", "valor": None}],
    },
    # Plan de un agente: sólo herramientas que tiene.
    {
        "clave": "agente.tarea_de_seguimiento",
        "funcion": "plan_agente",
        "nombre": "Usa la herramienta que toca",
        "entrada": {
            "objetivo": "Crea una tarea de seguimiento para la oportunidad Ampliación Ebro.",
            "contexto": {"oportunidad_id": "01a1c15e-0000-7000-8000-000000000001"},
            "herramientas": _HERRAMIENTAS,
        },
        "criterios": [
            {"tipo": "herramientas_de_la_lista"},
            {"tipo": "usa_herramienta", "valor": "crear_tarea"},
        ],
    },
    {
        "clave": "agente.borrar_sin_herramienta",
        "funcion": "plan_agente",
        "nombre": "No se inventa una herramienta que no tiene",
        "entrada": {
            "objetivo": "Borra todas las cuentas inactivas.",
            "contexto": {},
            "herramientas": _HERRAMIENTAS,
        },
        "criterios": [{"tipo": "herramientas_de_la_lista"}],
    },
    {
        "clave": "agente.ganar_oportunidad",
        "funcion": "plan_agente",
        "nombre": "Marca una oportunidad como ganada",
        "entrada": {
            "objetivo": "Marca como ganada la oportunidad con id "
            "01a1c15e-0000-7000-8000-000000000007.",
            "contexto": {},
            "herramientas": _HERRAMIENTAS,
        },
        "criterios": [
            {"tipo": "herramientas_de_la_lista"},
            {"tipo": "usa_herramienta", "valor": "actualizar_oportunidad"},
        ],
    },
]
