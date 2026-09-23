#!/usr/bin/env python3
"""Deja la instalación con la configuración puesta y los catálogos llenos.

`sembrar_empresa.py` llena lo que se **mueve** —cuentas, contactos, ofertas,
casos—. Este llena lo que las sostiene: canales, plantillas, segmentos,
entitlements, procesos, reglas, riesgos, roles. Sin eso la aplicación se abre y
la mitad de sus pantallas están vacías, que es distinto de que no existan pero
no lo parece: quien la ve por primera vez concluye que esa parte no está hecha.

Va **por la API y no por el ORM**, y es deliberado. Lo sembrado así es
exactamente lo que una persona podría haber creado desde el front: pasa por las
mismas validaciones, los mismos permisos y los mismos eventos. Y tiene un
efecto de vuelta —si un alta está rota, el sembrado se para y lo dice— que
escribiendo directamente en las tablas se pierde: ahí la pantalla acaba
enseñando registros que nadie habría podido crear.

Uso:

    python scripts/sembrar_configuracion.py --tenant ficosa \\
        --email admin@ficosa.com --contrasena '…'
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import date, timedelta
from typing import Any

TIEMPO_ESPERA = 30


class Api:
    """Cliente mínimo. Sin dependencias: este script corre antes que nada."""

    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.token = ""
        # Los contadores viven en un diccionario y no en atributos porque las
        # sesiones secundarias los comparten: si cada una llevara los suyos, el
        # recuento final diría menos de lo que se ha creado.
        self.cuenta: dict[str, int] = {"creados": 0, "saltados": 0}
        self.fallos: list[str] = []

    def _llamar(self, metodo: str, ruta: str, cuerpo: Any = None) -> tuple[int, Any]:
        datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
        pet = urllib.request.Request(f"{self.base}{ruta}", data=datos, method=metodo)
        pet.add_header("Content-Type", "application/json")
        if self.token:
            pet.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(pet, timeout=TIEMPO_ESPERA) as r:
                crudo = r.read().decode()
                return r.status, (json.loads(crudo) if crudo else None)
        except urllib.error.HTTPError as e:
            crudo = e.read().decode()
            try:
                return e.code, json.loads(crudo)
            except json.JSONDecodeError:
                return e.code, {"detail": crudo[:300]}
        except urllib.error.URLError as e:  # pragma: no cover - red
            return 0, {"detail": str(e.reason)}

    def entrar(self, email: str, contrasena: str, tenant: str) -> None:
        estado, cuerpo = self._llamar(
            "POST",
            "/api/v1/auth/login",
            {"email": email, "contrasena": contrasena, "tenant": tenant},
        )
        if estado != 200:
            raise SystemExit(f"No se ha podido entrar ({estado}): {cuerpo}")
        self.token = cuerpo.get("access_token") or cuerpo.get("token") or ""
        if not self.token:
            raise SystemExit(f"La respuesta de entrada no trae token: {sorted(cuerpo)}")

    def como(self, email: str, contrasena: str, tenant: str) -> "Api":
        """Otra sesión, con los contadores compartidos.

        Hay cosas que **no puede hacer quien las crea**, y con razón: publicar
        un artículo hacia el cliente exige que lo mire alguien distinto del
        autor, porque el fallo caro de una base de conocimiento —sacar fuera un
        procedimiento con nombres de clientes dentro— no lo ve quien lo
        escribió. El sembrado pasa por la misma puerta en vez de saltársela.
        """
        otra = Api(self.base)
        otra.entrar(email, contrasena, tenant)
        otra.fallos = self.fallos
        otra.cuenta = self.cuenta
        return otra

    def listar(self, ruta: str, limite: int = 50) -> list[dict]:
        sep = "&" if "?" in ruta else "?"
        estado, cuerpo = self._llamar("GET", f"{ruta}{sep}limite={limite}")
        if estado != 200:
            # Una ruta que no existe no puede pasar por «no hay nada». Pasó:
            # el sembrado pedía `/api/v1/contactos` —que es `/contacts`—, leía
            # una lista vacía y creaba los accesos al portal sin contacto, es
            # decir, no creaba ninguno. Y no se quejó nadie, porque un listado
            # vacío es una respuesta legítima.
            self.fallos.append(f"GET {ruta} → {estado} {_motivo(cuerpo)}")
            return []
        if isinstance(cuerpo, list):
            return cuerpo
        for clave in ("items", "datos", "resultados", "filas"):
            if isinstance(cuerpo, dict) and isinstance(cuerpo.get(clave), list):
                return cuerpo[clave]
        return []

    def crear(self, ruta: str, cuerpo: dict, *, metodo: str = "POST") -> dict | None:
        estado, respuesta = self._llamar(metodo, ruta, cuerpo)
        if estado in (200, 201, 204):
            self.cuenta["creados"] += 1
            return respuesta if isinstance(respuesta, dict) else {}
        # Un duplicado no es un fallo: el script se vuelve a pasar sobre una
        # instalación ya sembrada y tiene que poder terminar.
        if estado == 409:
            self.cuenta["saltados"] += 1
            return None
        etiqueta = cuerpo.get("clave") or cuerpo.get("nombre") or cuerpo.get("codigo") or ""
        self.fallos.append(f"{metodo} {ruta} «{etiqueta}» → {estado} {_motivo(respuesta)}")
        return None


def _motivo(respuesta: Any) -> str:
    if not isinstance(respuesta, dict):
        return str(respuesta)[:200]
    for clave in ("mensaje", "detail", "message", "error"):
        if respuesta.get(clave):
            return str(respuesta[clave])[:300]
    return json.dumps(respuesta)[:300]


def _uno(filas: list[dict], *claves: str) -> str:
    """El primer identificador utilizable de un listado, o cadena vacía."""
    for fila in filas:
        for clave in claves:
            if fila.get(clave):
                return str(fila[clave])
    return ""


HOY = date.today()


def _f(dias: int) -> str:
    return (HOY + timedelta(days=dias)).isoformat()


# ── Identidad y plataforma ────────────────────────────────────────────────

# Perfiles de trabajo reales, con los permisos escritos uno a uno. Se
# comprueban contra el catálogo que publica el servidor antes de enviarlos: un
# permiso inventado haría un rol que existe y no deja hacer nada, que es peor
# que no tener el rol.
ROLES = [
    (
        "Dirección comercial",
        "Ve todo el embudo y la previsión, y configura el proceso de venta",
        [
            "account:read",
            "account:write",
            "account:admin",
            "contact:read",
            "contact:write",
            "lead:read",
            "lead:write",
            "lead:convert",
            "lead:configurar",
            "opportunity:read",
            "opportunity:write",
            "opportunity:reopen",
            "pipeline:read",
            "pipeline:write",
            "forecast:read",
            "forecast:write",
            "quote:read",
            "quote:write",
            "order:read",
            "commission:read",
            "commission:approve",
            "producto:read",
            "informe:read",
        ],
    ),
    (
        "Comercial de cuenta",
        "Trabaja su cartera: cuentas, contactos, ofertas y actividades",
        [
            "account:read",
            "account:write",
            "contact:read",
            "contact:write",
            "lead:read",
            "lead:write",
            "lead:convert",
            "opportunity:read",
            "opportunity:write",
            "quote:read",
            "quote:write",
            "activity:read",
            "activity:write",
            "pipeline:read",
            "producto:read",
            "documento:enlazar",
            "adjunto:subir",
            "comentario:escribir",
        ],
    ),
    (
        "Soporte técnico",
        "Atiende casos y mantiene la base de conocimiento",
        [
            "case:read",
            "case:write",
            "knowledge:read",
            "knowledge:write",
            "conocimiento:read",
            "account:read",
            "contact:read",
            "activity:read",
            "activity:write",
            "contract:read",
            "comentario:escribir",
            "adjunto:subir",
        ],
    ),
    (
        "Marketing",
        "Campañas, segmentos y consentimiento",
        [
            "campaign:read",
            "campaign:write",
            "campana:read",
            "campana:write",
            "marketing:read",
            "marketing:write",
            "segment:read",
            "segment:write",
            "lead:read",
            "lead:write",
            "contact:read",
            "plantilla:crear",
            "plantilla:editar",
            "informe:read",
        ],
    ),
    (
        "Auditoría interna",
        "Solo lectura, incluida la traza. No cambia nada: es su razón de ser",
        [
            "account:read",
            "contact:read",
            "lead:read",
            "opportunity:read",
            "case:read",
            "party:read",
            "sales:read",
            "tenant:read",
            "user:read",
            "apikey:read",
            "cumplimiento:leer",
            "analitica:auditar",
            "aprobacion:read",
            "informe:read",
        ],
    ),
    (
        "Operaciones de sistema",
        "Integraciones, webhooks y procesos. No ve datos de negocio",
        [
            "integracion:read",
            "integracion:write",
            "integracion:credenciales",
            "integration:read",
            "integration:write",
            "webhook:read",
            "webhook:write",
            "proceso:read",
            "proceso:write",
            "automation:read",
            "automation:write",
            "event:read",
            "metadata:read",
        ],
    ),
]


def sembrar_identidad(api: Api) -> None:
    """Roles, credenciales de máquina y federación."""
    catalogo = {
        o["permiso"]
        for o in (api._llamar("GET", "/api/v1/superficie")[1] or {}).get("operaciones", [])
        if o.get("permiso")
    }
    for nombre, descripcion, permisos in ROLES:
        # Solo los que el servidor reconoce. Si el catálogo no llegó, van todos:
        # mejor un rol con un permiso de más que ninguno.
        validos = [p for p in permisos if p in catalogo] if catalogo else permisos
        api.crear(
            "/api/v1/roles",
            {"nombre": nombre, "descripcion": descripcion, "permisos": validos},
        )

    api.crear(
        "/api/v1/claves-api",
        {
            "nombre": "Integración con el ERP",
            "scopes": ["account:read", "account:write", "contact:read", "order:read"],
            "dias": 365,
        },
    )
    api.crear(
        "/api/v1/claves-api",
        {"nombre": "Formularios de la web corporativa", "scopes": ["lead:write"], "dias": 180},
    )
    api.crear(
        "/api/v1/proveedores-identidad",
        {
            "nombre": "Directorio corporativo",
            "tipo": "saml",
            "dominio_email": "ficosa.com",
            "jit_provisioning": True,
            # Inactivo a propósito: dejarlo activo en una instalación recién
            # sembrada dejaría fuera a todo el mundo, porque el SSO al que
            # apunta no existe.
            "activo": False,
            "config": {
                "idp_entity_id": "https://sso.ficosa.com/saml/metadata",
                "idp_sso_url": "https://sso.ficosa.com/saml/sso",
                "idp_x509_cert": (
                    "-----BEGIN CERTIFICATE-----\n"
                    "SUSTITUIR POR EL CERTIFICADO DE FIRMA DEL IDP CORPORATIVO\n"
                    "-----END CERTIFICATE-----"
                ),
                "sp_entity_id": "https://crm.ficosa.com/saml/metadata",
                "sp_acs_url": "https://crm.ficosa.com/api/v1/auth/saml/acs",
            },
            "mapeo_roles": {"CRM-Ventas": "Comercial de cuenta", "CRM-Soporte": "Soporte técnico"},
        },
    )
    # Políticas de acceso por atributo: quién ve qué dentro de lo que su rol le
    # deja ver. El rol dice «puede leer cuentas»; esto dice «las de su zona».
    # Nacen **inactivas**: una política de visibilidad encendida sobre datos ya
    # cargados esconde registros a gente que los estaba viendo, y eso se decide
    # mirándolo, no al sembrar.
    politicas = [
        {
            "nombre": "cartera_propia",
            "objeto": "cuenta",
            "acciones": ["leer", "escribir"],
            "condiciones": [
                {"atributo": "registro.owner_id", "operador": "=", "valor": "@usuario.id"}
            ],
            "prioridad": 50,
            "alcance": "registro",
            "descripcion": "Cada comercial ve y edita las cuentas que lleva",
        },
        {
            "nombre": "oportunidades_de_mi_unidad",
            "objeto": "oportunidad",
            "acciones": ["leer"],
            "condiciones": [
                {
                    "atributo": "registro.unidad_negocio_id",
                    "operador": "=",
                    "valor": "@usuario.unidad_id",
                }
            ],
            "prioridad": 60,
            "alcance": "registro",
            "descripcion": "El embudo se ve por unidad de negocio",
        },
        {
            "nombre": "datos_bancarios_solo_finanzas",
            "objeto": "cuenta",
            "acciones": ["leer"],
            "condiciones": [{"atributo": "usuario.rol", "operador": "en", "valor": ["admin"]}],
            "prioridad": 10,
            # Por campos y no por registro: esconder la cuenta entera a quien
            # no es de finanzas dejaría sin trabajar a medio equipo comercial;
            # lo que no tiene que ver es el IBAN.
            "alcance": "campos",
            "campos": ["iban", "condiciones_pago"],
            "descripcion": "Los datos de cobro solo los ve quien los necesita",
        },
    ]
    for politica in politicas:
        api.crear(f"/api/v1/politicas-acceso/{politica['nombre']}", politica, metodo="PUT")

    api.crear(
        "/api/v1/segregacion/reglas/SOD-DESCUENTOS",
        {
            "nombre": "Quien pide un descuento no lo aprueba",
            "descripcion": "Separación de funciones sobre el circuito de ofertas",
            "permisos_a": ["quote:write"],
            "permisos_b": ["aprobacion:decidir"],
            "nivel": "alto",
        },
        metodo="PUT",
    )
    api.crear(
        "/api/v1/segregacion/reglas/SOD-PURGA",
        {
            "nombre": "Quien administra cuentas no purga datos",
            "descripcion": "Borrar definitivamente y administrar no van en la misma persona",
            "permisos_a": ["account:admin"],
            "permisos_b": ["retencion:purgar", "account:purge"],
            "nivel": "alto",
        },
        metodo="PUT",
    )


# ── Modelo de datos propio del cliente ────────────────────────────────────


def sembrar_metadatos(api: Api) -> None:
    """Objetos y relaciones que este cliente añade al modelo estándar.

    Un fabricante de componentes no vende «oportunidades» sueltas: vende
    programas de un vehículo que duran años y cuelgan de una planta concreta.
    Eso no está en el CRM de serie y es justamente para lo que existe el
    módulo de metadatos.
    """
    objetos = [
        {
            "nombre": "programa_vehiculo",
            "etiqueta": "Programa de vehículo",
            "etiqueta_plural": "Programas de vehículo",
            "descripcion": "Modelo y generación de un fabricante para el que se produce",
            "icono": "directions_car",
            "papelera": True,
            "estados": {
                "inicial": "estudio",
                "valores": ["estudio", "nominado", "serie", "fin_de_vida"],
            },
        },
        {
            "nombre": "planta",
            "etiqueta": "Planta",
            "etiqueta_plural": "Plantas",
            "descripcion": "Centro de producción del cliente al que se entrega",
            "icono": "factory",
            "papelera": True,
        },
        {
            "nombre": "homologacion",
            "etiqueta": "Homologación",
            "etiqueta_plural": "Homologaciones",
            "descripcion": "Certificación de una pieza para un mercado",
            "icono": "verified",
            "estados": {
                "inicial": "solicitada",
                "valores": ["solicitada", "en_curso", "concedida", "denegada"],
            },
        },
    ]
    for objeto in objetos:
        api.crear("/api/v1/metadata/objetos", objeto)

    relaciones = [
        {
            "nombre": "programa_de_la_cuenta",
            "etiqueta": "Programas",
            "nombre_inverso": "Cliente",
            "descripcion": "Programas de vehículo de un fabricante",
            "origen": "cuenta",
            "destino": "programa_vehiculo",
            "cardinalidad": "1:N",
            "al_borrar": "restringir",
        },
        {
            "nombre": "planta_de_la_cuenta",
            "etiqueta": "Plantas",
            "nombre_inverso": "Empresa",
            "origen": "cuenta",
            "destino": "planta",
            "cardinalidad": "1:N",
            "al_borrar": "restringir",
        },
        {
            "nombre": "programa_de_la_oportunidad",
            "etiqueta": "Programa",
            "nombre_inverso": "Oportunidades",
            "descripcion": "Programa al que responde esta oportunidad",
            # Del programa a sus oportunidades: la cardinalidad se declara
            # desde el lado que manda, y el destino es el que se repite.
            "origen": "programa_vehiculo",
            "destino": "oportunidad",
            "cardinalidad": "1:N",
            "al_borrar": "desvincular",
        },
    ]
    for relacion in relaciones:
        api.crear("/api/v1/metadata/relaciones", relacion)


# ── Procesos, decisiones y automatización ─────────────────────────────────

# Un proceso de verdad, con sus tres formas de bifurcar: una tabla que edita
# negocio, una tarea humana y un paso de servicio. Un proceso de ejemplo con un
# solo paso enseña que el motor arranca, no que sirva para algo.
PROCESO_APROBACION = {
    "inicio": "clasificar",
    "pasos": {
        "clasificar": {
            "tipo": "tabla",
            "tabla": "aprobacion_descuento",
            "guardar_en": "aprobacion",
            "siguiente": "decidir_ruta",
        },
        "decidir_ruta": {
            "tipo": "decision",
            "condiciones": [
                {
                    "si": {"atributo": "aprobacion.nivel", "op": "=", "valor": "automatica"},
                    "entonces": "aprobada",
                },
                {
                    "si": {"atributo": "aprobacion.nivel", "op": "=", "valor": "direccion"},
                    "entonces": "visto_bueno_direccion",
                },
            ],
            "siguiente": "visto_bueno_responsable",
        },
        "visto_bueno_responsable": {
            "tipo": "humano",
            "titulo": "Aprobar el descuento de la oferta",
            "asignada_rol": "responsable_ventas",
            "respuestas": ["aprobar", "rechazar"],
            "rutas": {"aprobar": "aprobada", "rechazar": "rechazada"},
        },
        "visto_bueno_direccion": {
            "tipo": "humano",
            "titulo": "Descuento por encima del umbral: lo aprueba dirección",
            "asignada_rol": "admin",
            "respuestas": ["aprobar", "rechazar"],
            "rutas": {"aprobar": "aprobada", "rechazar": "rechazada"},
        },
        "aprobada": {"tipo": "fin", "resultado": "aprobada"},
        "rechazada": {"tipo": "fin", "resultado": "rechazada"},
    },
}

PROCESO_ALTA_CLIENTE = {
    "inicio": "comprobar_datos",
    "pasos": {
        "comprobar_datos": {
            "tipo": "decision",
            "condiciones": [
                {"si": {"atributo": "cif", "op": "vacio"}, "entonces": "pedir_datos"},
            ],
            "siguiente": "validar_riesgo",
        },
        "pedir_datos": {
            "tipo": "humano",
            "titulo": "Faltan datos fiscales del cliente",
            "asignada_rol": "comercial",
            "respuestas": ["completado"],
            "rutas": {"completado": "validar_riesgo"},
        },
        "validar_riesgo": {
            "tipo": "espera",
            "segundos": 3600,
            "siguiente": "revisar_credito",
        },
        "revisar_credito": {
            "tipo": "humano",
            "titulo": "Revisar el límite de crédito propuesto",
            "asignada_rol": "admin",
            "respuestas": ["aprobar", "rechazar"],
            "rutas": {"aprobar": "alta_hecha", "rechazar": "denegada"},
        },
        "alta_hecha": {"tipo": "fin", "resultado": "alta_hecha"},
        "denegada": {"tipo": "fin", "resultado": "denegada"},
    },
}

TABLA_DESCUENTOS = {
    "nombre": "Quién aprueba cada descuento",
    "politica": "primera",
    "entradas": [
        {
            "clave": "descuento",
            "etiqueta": "Descuento (%)",
            "expresion": "@descuento",
            "tipo": "numero",
        },
        {
            "clave": "importe",
            "etiqueta": "Importe de la oferta",
            "expresion": "@importe",
            "tipo": "numero",
        },
    ],
    "salidas": [
        {"clave": "nivel", "etiqueta": "Quién aprueba", "tipo": "texto"},
        {"clave": "dias_maximos", "etiqueta": "Plazo de respuesta (días)", "tipo": "numero"},
    ],
    "reglas": [
        {
            "nombre": "Descuento pequeño: no necesita visto bueno",
            "condiciones": [{"entrada": "descuento", "op": "<=", "valor": 5}],
            "salidas": {"nivel": "automatica", "dias_maximos": 0},
        },
        {
            "nombre": "Hasta el 15 %, lo aprueba el responsable",
            "condiciones": [{"entrada": "descuento", "op": "<=", "valor": 15}],
            "salidas": {"nivel": "responsable", "dias_maximos": 2},
        },
        {
            "nombre": "Oferta grande con descuento alto: dirección",
            "condiciones": [
                {"entrada": "descuento", "op": ">", "valor": 15},
                {"entrada": "importe", "op": ">=", "valor": 100000},
            ],
            "salidas": {"nivel": "direccion", "dias_maximos": 5},
        },
        {
            "nombre": "Resto de descuentos altos",
            "condiciones": [{"entrada": "descuento", "op": ">", "valor": 15}],
            "salidas": {"nivel": "direccion", "dias_maximos": 3},
        },
    ],
}

TABLA_PRIORIDAD_CASO = {
    "nombre": "Prioridad de un caso según contrato e impacto",
    "politica": "prioridad",
    "entradas": [
        {
            "clave": "plan",
            "etiqueta": "Plan de soporte",
            "expresion": "@entitlement.plan",
            "tipo": "texto",
        },
        {
            "clave": "linea_parada",
            "etiqueta": "¿Línea parada?",
            "expresion": "@caso.linea_parada",
            "tipo": "booleano",
        },
    ],
    "salidas": [
        {"clave": "prioridad", "etiqueta": "Prioridad", "tipo": "texto"},
        {"clave": "horas_respuesta", "etiqueta": "Respuesta comprometida (h)", "tipo": "numero"},
    ],
    "reglas": [
        {
            "nombre": "Línea de producción parada: siempre lo primero",
            "prioridad": 100,
            "condiciones": [{"entrada": "linea_parada", "op": "=", "valor": True}],
            "salidas": {"prioridad": "critica", "horas_respuesta": 1},
        },
        {
            "nombre": "Plan 24x7",
            "prioridad": 50,
            "condiciones": [{"entrada": "plan", "op": "=", "valor": "24x7"}],
            "salidas": {"prioridad": "alta", "horas_respuesta": 4},
        },
        {
            "nombre": "Plan estándar",
            "prioridad": 10,
            "condiciones": [{"entrada": "plan", "op": "=", "valor": "estandar"}],
            "salidas": {"prioridad": "normal", "horas_respuesta": 24},
        },
    ],
}


def sembrar_procesos(api: Api) -> None:
    """Definiciones, tablas de decisión e instancias en marcha.

    Las tablas antes que los procesos, porque el proceso las referencia y al
    publicarlo se revalida: publicar primero el proceso lo dejaría en borrador
    con un error que no explica nada.
    """
    api.crear("/api/v1/tablas-decision/aprobacion_descuento", TABLA_DESCUENTOS, metodo="PUT")
    api.crear("/api/v1/tablas-decision/prioridad_caso", TABLA_PRIORIDAD_CASO, metodo="PUT")

    api.crear(
        "/api/v1/procesos/definiciones",
        {
            "clave": "aprobacion_descuento",
            "nombre": "Aprobación de descuento en oferta",
            "descripcion": "Quién tiene que dar el visto bueno a un descuento, y en cuánto tiempo",
            "definicion": PROCESO_APROBACION,
            "estado": "publicada",
            "disparadores": ["quote.descuento_solicitado"],
        },
    )
    api.crear(
        "/api/v1/procesos/definiciones",
        {
            "clave": "alta_cliente",
            "nombre": "Alta de cliente nuevo",
            "descripcion": "Comprobación fiscal y de crédito antes de operar con un cliente",
            "definicion": PROCESO_ALTA_CLIENTE,
            "estado": "publicada",
            "disparadores": ["account.creada"],
        },
    )

    # Instancias en marcha, para que la pantalla de procesos enseñe trabajo y
    # no una tabla vacía —y para que las tareas humanas existan, que cuelgan
    # de ellas y no se pueden crear de otra forma—.
    for descuento, importe in ((22, 480_000), (12, 75_000), (18, 250_000)):
        api.crear(
            "/api/v1/instancias",
            {
                "clave": "aprobacion_descuento",
                "variables": {"descuento": descuento, "importe": importe},
                "origen_tipo": "oportunidad",
            },
        )
    api.crear("/api/v1/instancias", {"clave": "alta_cliente", "variables": {"cif": ""}})


# ── Automatización, integraciones y eventos ───────────────────────────────


def sembrar_automatizacion(api: Api) -> None:
    """Reglas que hacen algo solas.

    Son las que convierten el CRM en una herramienta que trabaja y no en una
    base de datos con formularios: avisar cuando una oportunidad grande cambia
    de etapa, abrir el circuito de aprobación cuando el descuento se pasa,
    reclamar la oferta que lleva una semana sin respuesta.
    """
    reglas = [
        {
            "nombre": "Aviso cuando una oportunidad grande cambia de etapa",
            "descripcion": "Dirección comercial se entera el mismo día, no en el comité",
            "disparador": "modificacion",
            "objetivo": "oportunidad",
            "campos_vigilados": ["etapa"],
            "condiciones": [{"atributo": "importe", "op": ">=", "valor": 250000}],
            "combinacion": "todas",
            "acciones": [
                {
                    "tipo": "notificar",
                    "parametros": {
                        "titulo": "Oportunidad grande en movimiento",
                        "cuerpo": "«@nombre» ha pasado a la etapa @etapa (@importe €)",
                        "objeto": "oportunidad",
                        "registro_id": "@id",
                    },
                }
            ],
            "prioridad": 10,
            "momento": "inmediata",
            "activa": True,
        },
        {
            "nombre": "Descuento alto: abrir la aprobación",
            "descripcion": "Lanza el proceso de aprobación en lugar de confiar en que alguien avise",
            "disparador": "modificacion",
            "objetivo": "oferta",
            "campos_vigilados": ["descuento_pct"],
            "condiciones": [{"atributo": "descuento_pct", "op": ">", "valor": 15}],
            "acciones": [
                {
                    "tipo": "lanzar_proceso",
                    "parametros": {
                        "clave": "aprobacion_descuento",
                        "variables": {"descuento": "@descuento_pct", "importe": "@total"},
                    },
                }
            ],
            "prioridad": 5,
            "momento": "inmediata",
            "activa": True,
        },
        {
            "nombre": "Lead sin atender en 48 horas",
            "descripcion": "Reasigna el lead que nadie ha tocado, antes de que se enfríe",
            "disparador": "programada",
            "objetivo": "lead",
            "programacion": "0 8 * * *",
            "condiciones": [
                {"atributo": "estado", "op": "=", "valor": "nuevo"},
                {"atributo": "owner_id", "op": "vacio"},
            ],
            "combinacion": "alguna",
            "acciones": [
                {
                    "tipo": "notificar",
                    "parametros": {
                        "titulo": "Lead sin atender",
                        "cuerpo": "«@nombre» lleva más de 48 horas sin asignar",
                        "objeto": "lead",
                        "registro_id": "@id",
                    },
                }
            ],
            "prioridad": 20,
            "momento": "programada",
            "activa": True,
        },
        {
            "nombre": "Caso crítico: avisar al responsable de la cuenta",
            "disparador": "creacion",
            "objetivo": "caso",
            "condiciones": [{"atributo": "prioridad", "op": "=", "valor": "critica"}],
            "acciones": [
                {
                    "tipo": "notificar",
                    "parametros": {
                        "titulo": "Caso crítico abierto",
                        "cuerpo": "@titulo",
                        "objeto": "caso",
                        "registro_id": "@id",
                    },
                }
            ],
            "prioridad": 1,
            "momento": "inmediata",
            "activa": True,
        },
        {
            "nombre": "Cliente nuevo: arrancar el alta",
            "disparador": "creacion",
            "objetivo": "cuenta",
            "acciones": [
                {
                    "tipo": "lanzar_proceso",
                    "parametros": {"clave": "alta_cliente", "variables": {"cif": "@cif"}},
                }
            ],
            "prioridad": 30,
            "momento": "diferida",
            # Inactiva: se deja escrita y apagada porque encenderla en una
            # instalación recién sembrada abriría un expediente por cada cuenta
            # que se cargue, y eso lo decide quien la explota.
            "activa": False,
        },
    ]
    for regla in reglas:
        api.crear("/api/v1/automatizaciones", regla)


def sembrar_integraciones(api: Api) -> None:
    """Conexiones con los sistemas de alrededor y salidas por webhook."""
    conexiones = [
        {
            "nombre": "ERP (SAP S/4HANA)",
            "sistema": "sap",
            "descripcion": "Maestro de clientes, pedidos y facturación",
            "protocolo": "rest",
            "config": {
                "base_url": "https://erp.ficosa.com/api",
                "autenticacion": "oauth2",
                "entorno": "produccion",
            },
        },
        {
            "nombre": "Correo corporativo (Microsoft 365)",
            "sistema": "microsoft365",
            "descripcion": "Sincronización de correo y calendario del equipo comercial",
            "protocolo": "graph",
            "config": {
                "tenant": "ficosa.onmicrosoft.com",
                "ambito": "Mail.Read Calendars.ReadWrite",
            },
        },
        {
            "nombre": "Portal de compras del cliente",
            "sistema": "generico",
            "descripcion": "Recepción de peticiones de oferta (RFQ) de los fabricantes",
            "protocolo": "sftp",
            "config": {"host": "sftp.proveedores.example.com", "ruta": "/rfq/entrada"},
        },
        {
            "nombre": "Telefonía (centralita)",
            "sistema": "generico",
            "descripcion": "Registro automático de llamadas como actividad",
            "protocolo": "webhook",
            "config": {"direccion": "entrante"},
        },
    ]
    for conexion in conexiones:
        api.crear("/api/v1/integraciones/conexiones", conexion)

    webhooks = [
        {
            "nombre": "Avisar al ERP de cada pedido",
            "url": "https://www.example.com/hooks/crm/pedidos",
            "eventos": ["opportunity.stage.changed", "order.submitted"],
            "cabeceras": {"X-Origen": "contecrm"},
        },
        {
            "nombre": "Alta de cliente al maestro de datos",
            "url": "https://www.example.com/hooks/clientes",
            "eventos": ["account.created", "account.merged"],
        },
        {
            "nombre": "Casos críticos al canal de guardia",
            "url": "https://www.example.com/hooks/guardia",
            "eventos": ["case.escalated", "case.created"],
            "condiciones": [{"atributo": "prioridad", "op": "=", "valor": "critica"}],
        },
    ]
    for webhook in webhooks:
        api.crear("/api/v1/webhooks", webhook)


# ── Ventas: captura, enrutado y atribución ────────────────────────────────


def sembrar_ventas(api: Api) -> None:
    """Por dónde entran los leads, quién los coge y de dónde vienen."""
    canales = [
        {
            "clave": "web_contacto",
            "nombre": "Formulario de contacto de la web",
            "tipo": "formulario",
            "mapeo": {
                "nombre": "first_name",
                "apellidos": "last_name",
                "email": "email",
                "empresa": "company",
                "telefono": "phone",
            },
            "fijos": {"origen": "web"},
            "obligatorios": ["email", "empresa"],
            # Campo señuelo: lo rellenan los robots y nadie más. Es lo que
            # separa el formulario abierto a internet del buzón de spam.
            "campo_trampa": "apellido2",
            "max_por_hora": 120,
        },
        {
            "clave": "rfq_portal",
            "nombre": "Peticiones de oferta del portal de compras",
            "tipo": "api",
            "mapeo": {"empresa": "buyer_name", "email": "buyer_email", "web": "buyer_site"},
            "fijos": {"origen": "rfq"},
            "obligatorios": ["email"],
            "max_por_hora": 600,
        },
        {
            "clave": "feria",
            "nombre": "Captación en ferias y congresos",
            "tipo": "importacion",
            "mapeo": {"nombre": "Nombre", "email": "Email", "empresa": "Empresa"},
            "fijos": {"origen": "evento"},
            "obligatorios": ["email"],
        },
    ]
    for canal in canales:
        api.crear("/api/v1/captura/canales", canal)

    usuarios = api.listar("/api/v1/usuarios", 20)
    candidatos = [str(u["id"]) for u in usuarios if u.get("id")][:4]

    reglas = [
        {
            "nombre": "Cuentas grandes al equipo de key accounts",
            "descripcion": "Por encima de 500 empleados no entra en el reparto normal",
            "prioridad": 10,
            "condiciones": [{"atributo": "empleados", "operador": ">=", "valor": 500}],
            "combinacion": "todas",
            "estrategia": "round_robin",
            "candidatos": candidatos[:2],
            "activa": True,
        },
        {
            "nombre": "Peticiones de oferta: al que menos carga tenga",
            "descripcion": "Una RFQ tiene fecha de cierre; va a quien pueda atenderla",
            "prioridad": 20,
            "condiciones": [{"atributo": "origen", "operador": "=", "valor": "rfq"}],
            "estrategia": "menos_carga",
            "candidatos": candidatos,
            "activa": True,
        },
        {
            "nombre": "Resto de leads, reparto equitativo",
            "prioridad": 100,
            "condiciones": [{"atributo": "email", "operador": "no_vacio", "valor": None}],
            "estrategia": "round_robin",
            "candidatos": candidatos,
            "activa": True,
        },
    ]
    for regla in reglas:
        if regla["candidatos"]:
            api.crear("/api/v1/lead-routing/reglas", regla)

    # Toques de origen: la cadena por la que llegó cada lead. Sin ellos la
    # atribución de campañas no puede decir nada, y la pantalla que la enseña
    # sale vacía sin explicar que es por falta de dato.
    leads = api.listar("/api/v1/leads", 20)
    rastro = [
        ("organico", {"utm_source": "google", "utm_medium": "organic"}),
        ("campana", {"utm_source": "linkedin", "utm_medium": "cpc", "utm_campaign": "adas-2026"}),
        ("directo", {}),
        ("evento", {"utm_source": "iaa", "utm_medium": "feria"}),
        ("referido", {"utm_source": "partner", "utm_medium": "referral"}),
    ]
    for i, lead in enumerate(leads[:12]):
        canal, parametros = rastro[i % len(rastro)]
        api.crear(
            "/api/v1/origen/toques",
            {
                "lead_id": str(lead.get("id")),
                "canal": canal,
                "ocurrio_at": f"{_f(-30 + i)}T09:00:00Z",
                "parametros": parametros,
            },
        )


# ── Marketing: canales, consentimiento, contenido y campañas ──────────────


def sembrar_marketing(api: Api) -> None:
    """Lo que hace falta para poder enviar algo sin infringir nada.

    El orden importa: las categorías de preferencia y los dominios antes que
    los canales, los canales antes que las campañas, y las supresiones desde el
    principio. Sembrar campañas sobre una instalación sin lista de supresión es
    enseñar una pantalla que en producción sería ilegal.
    """
    categorias = [
        {
            "clave": "operativa",
            "nombre": "Avisos de servicio",
            "descripcion": "Incidencias, mantenimientos y cambios en pedidos en curso",
            "obligatoria": True,
            "por_defecto": True,
            "orden": "10",
        },
        {
            "clave": "producto",
            "nombre": "Novedades de producto",
            "descripcion": "Nuevas gamas, homologaciones y fichas técnicas",
            "por_defecto": True,
            "orden": "20",
        },
        {
            "clave": "eventos",
            "nombre": "Ferias y jornadas técnicas",
            "descripcion": "Invitaciones a eventos del sector",
            "orden": "30",
        },
        {
            "clave": "comercial",
            "nombre": "Ofertas y promociones",
            "descripcion": "Comunicaciones comerciales",
            "orden": "40",
        },
    ]
    for categoria in categorias:
        api.crear("/api/v1/preferencias/categorias", categoria)

    dominios = [
        {
            "dominio": "info.ficosa.com",
            "uso": "marketing",
            "spf": True,
            "dkim": True,
            "dmarc": "quarantine",
            "bimi": False,
        },
        {
            "dominio": "ficosa.com",
            "uso": "transaccional",
            "spf": True,
            "dkim": True,
            "dmarc": "reject",
            "bimi": True,
        },
    ]
    for dominio in dominios:
        api.crear("/api/v1/dominios-envio", dominio)

    canales = [
        {
            "clave": "email_marketing",
            "nombre": "Correo de marketing",
            "tipo": "email",
            "remitente": "comunicaciones@info.ficosa.com",
            "silencio_desde": 21,
            "silencio_hasta": 8,
            "coste_mensaje": "0.0008",
        },
        {
            "clave": "email_operativo",
            "nombre": "Correo operativo",
            "tipo": "email",
            "remitente": "avisos@ficosa.com",
            "coste_mensaje": "0.0008",
        },
        {
            "clave": "sms",
            "nombre": "SMS",
            "tipo": "sms",
            "silencio_desde": 21,
            "silencio_hasta": 9,
            "coste_mensaje": "0.045",
        },
        {"clave": "whatsapp", "nombre": "WhatsApp Business", "tipo": "whatsapp"},
    ]
    for canal in canales:
        api.crear("/api/v1/canales-marketing", canal)

    api.crear(
        "/api/v1/presion/reglas",
        {"canal": "email", "maximo": 4, "ventana_dias": 30, "horas_minimas": 48},
        metodo="PUT",
    )

    bloques = [
        {
            "clave": "cabecera",
            "nombre": "Cabecera con logotipo",
            "tipo": "cabecera",
            "contenido": {"logo": "https://info.ficosa.com/img/logo.png", "alto": 48},
        },
        {
            "clave": "pie_legal",
            "nombre": "Pie legal con baja",
            "tipo": "pie",
            "contenido": {
                "texto": "Ficosa International S.A. · Recibes esto porque tienes relación comercial con nosotros.",
                "enlace_baja": "{{url_baja}}",
            },
            # Obligatorio en promocional: sin pie de baja, el envío comercial no
            # cumple, y dejarlo a criterio de quien monta la plantilla es confiar
            # en que nadie tenga prisa.
            "obligatorio_en_promocional": True,
        },
        {
            "clave": "ficha_producto",
            "nombre": "Ficha de producto",
            "tipo": "contenido",
            "contenido": {"columnas": 2, "muestra": ["imagen", "referencia", "descripcion"]},
        },
    ]
    for bloque in bloques:
        api.crear("/api/v1/correo/bloques", bloque)

    plantillas = [
        {
            "clave": "bienvenida",
            "nombre": "Bienvenida a cliente nuevo",
            "asunto": "Bienvenido a Ficosa, {{contacto.nombre}}",
            "preencabezado": "Tu equipo de contacto y cómo llegar a nosotros",
            "clase": "operativa",
            "categoria": "operativa",
            "idioma": "es",
            "bloques": [{"clave": "cabecera"}, {"clave": "pie_legal"}],
        },
        {
            "clave": "novedades_trimestre",
            "nombre": "Novedades del trimestre",
            "asunto": "Novedades de producto · {{trimestre}}",
            "clase": "promocional",
            "categoria": "producto",
            "idioma": "es",
            "bloques": [{"clave": "cabecera"}, {"clave": "ficha_producto"}, {"clave": "pie_legal"}],
        },
        {
            "clave": "invitacion_feria",
            "nombre": "Invitación a feria",
            "asunto": "Te esperamos en {{evento.nombre}}",
            "clase": "promocional",
            "categoria": "eventos",
            "idioma": "es",
            "bloques": [{"clave": "cabecera"}, {"clave": "pie_legal"}],
        },
        {
            "clave": "aviso_incidencia",
            "nombre": "Aviso de incidencia",
            "asunto": "Incidencia en tu pedido {{pedido.referencia}}",
            "clase": "operativa",
            "categoria": "operativa",
            "idioma": "es",
            "bloques": [{"clave": "cabecera"}],
        },
    ]
    for plantilla in plantillas:
        api.crear("/api/v1/correo/plantillas", plantilla)

    landings = [
        {
            "clave": "descarga_catalogo",
            "titulo": "Catálogo técnico 2026",
            "campos": [
                {"nombre": "email", "etiqueta": "Correo corporativo", "obligatorio": True},
                {"nombre": "empresa", "etiqueta": "Empresa", "obligatorio": True},
                {"nombre": "cargo", "etiqueta": "Cargo"},
            ],
            "pide_consentimiento": ["producto", "comercial"],
            "canal_captura": "web_contacto",
        },
        {
            "clave": "webinar_adas",
            "titulo": "Webinar: sensores ADAS de nueva generación",
            "campos": [
                {"nombre": "email", "etiqueta": "Correo", "obligatorio": True},
                {"nombre": "nombre", "etiqueta": "Nombre", "obligatorio": True},
            ],
            "pide_consentimiento": ["eventos"],
            "canal_captura": "web_contacto",
        },
    ]
    for landing in landings:
        api.crear("/api/v1/landings", landing)

    segmentos = [
        {
            "clave": "clientes_activos",
            "nombre": "Clientes activos",
            "objeto": "cuenta",
            "dinamico": True,
            "descripcion": "Cuentas en estado cliente, que son las que pueden recibir novedades",
            "definicion": {"atributo": "cuenta.estado", "operador": "=", "valor": "cliente"},
        },
        {
            "clave": "grandes_cuentas",
            "nombre": "Grandes cuentas",
            "objeto": "cuenta",
            "dinamico": True,
            "descripcion": "Más de 500 empleados: las lleva el equipo de key accounts",
            "definicion": {"atributo": "cuenta.empleados", "operador": ">=", "valor": 500},
        },
        {
            "clave": "contactos_tecnicos",
            "nombre": "Perfiles técnicos",
            "objeto": "contacto",
            "dinamico": True,
            "descripcion": "Ingeniería, calidad y planta: reciben ficha técnica, no oferta",
            # Con «en» y no con «contiene»: un segmento dinámico se calcula
            # sobre la base, y «contiene» no tiene traducción honesta a SQL —
            # depende del tipo de la columna—. El servicio lo dice al guardarlo
            # en vez de aceptarlo y devolver luego una lista que no cuadra.
            "definicion": {
                "atributo": "contacto.cargo",
                "operador": "en",
                "valor": [
                    "Ingeniera de producto",
                    "Ingeniero de producto",
                    "Responsable de calidad",
                    "Responsable de mantenimiento",
                    "Jefe de planta",
                    "Jefa de proyecto",
                    "Responsable de IT",
                ],
            },
        },
        {
            "clave": "clientes_grandes_activos",
            "nombre": "Grandes cuentas activas",
            "objeto": "cuenta",
            "dinamico": True,
            "descripcion": "El cruce de las dos anteriores: a quien de verdad se invita a la feria",
            "definicion": {
                "op": "y",
                "hijos": [
                    {"atributo": "cuenta.estado", "operador": "=", "valor": "cliente"},
                    {"atributo": "cuenta.empleados", "operador": ">=", "valor": 500},
                ],
            },
        },
    ]
    for segmento in segmentos:
        api.crear("/api/v1/segmentos", segmento)

    api.crear(
        "/api/v1/puntuacion/modelos",
        {
            "clave": "b2b_automocion",
            "nombre": "Puntuación B2B de automoción",
            # Interés: lo que la persona hace. Encaje: lo que la persona es. Se
            # puntúan por separado a propósito —un becario muy interesado y un
            # director de compras que aún no ha abierto nada no son el mismo
            # caso, y un único número los confundiría—.
            "reglas_interes": [
                {
                    "nombre": "Ha pedido el catálogo técnico",
                    "condicion": {
                        "atributo": "evento",
                        "operador": "=",
                        "valor": "landing.enviada",
                    },
                    "puntos": 15,
                },
                {
                    "nombre": "Abre los correos",
                    "condicion": {"atributo": "aperturas_30d", "operador": ">=", "valor": 3},
                    "puntos": 10,
                },
                {
                    "nombre": "Ha visitado la página de precios",
                    "condicion": {
                        "atributo": "paginas",
                        "operador": "contiene",
                        "valor": "precios",
                    },
                    "puntos": 10,
                },
            ],
            "reglas_encaje": [
                {
                    "nombre": "Fabricante de vehículo",
                    "condicion": {"atributo": "sector", "operador": "=", "valor": "automocion"},
                    "puntos": 30,
                },
                {
                    "nombre": "Más de 500 empleados",
                    "condicion": {"atributo": "cuenta.empleados", "operador": ">=", "valor": 500},
                    "puntos": 20,
                },
                {
                    "nombre": "Mercado objetivo",
                    "condicion": {
                        "atributo": "pais",
                        "operador": "en",
                        "valor": ["ES", "FR", "DE", "PT"],
                    },
                    "puntos": 10,
                },
            ],
            # El interés caduca: un lead que se interesó hace ocho meses y no ha
            # vuelto no vale lo mismo que uno de esta semana, y sin decaimiento
            # la lista de «calientes» se llena de fósiles.
            "decaimiento_puntos": 5,
            "decaimiento_dias": 30,
            "interes_minimo": 0,
            "umbral_mql_interes": 40,
            "umbral_mql_encaje": 30,
            "umbral_sql_interes": 70,
            "umbral_sql_encaje": 50,
            "grados": [
                {"clave": "A", "desde": 80},
                {"clave": "B", "desde": 60},
                {"clave": "C", "desde": 40},
                {"clave": "D", "desde": 0},
            ],
        },
    )

    campanas = [
        {
            "clave": "adas-2026",
            "nombre": "Lanzamiento ADAS 2026",
            "nivel": "campana",
            "tipo": "producto",
            "canal": "email",
            "desde": _f(-45),
            "hasta": _f(45),
            "presupuesto": 85000,
            "moneda": "EUR",
            "objetivos": {"leads": 400, "oportunidades": 40, "ingreso": 2500000},
        },
        {
            "clave": "iaa-2026",
            "nombre": "Feria IAA Mobility 2026",
            "nivel": "campana",
            "tipo": "evento",
            "canal": "presencial",
            "desde": _f(20),
            "hasta": _f(24),
            "presupuesto": 140000,
            "moneda": "EUR",
            "lugar": "Múnich",
            "aforo": 300,
            "objetivos": {"leads": 250, "reuniones": 60},
        },
        {
            "clave": "fidelizacion-q4",
            "nombre": "Fidelización de clientes activos",
            "nivel": "campana",
            "tipo": "fidelizacion",
            "canal": "email",
            "desde": _f(-10),
            "hasta": _f(80),
            "presupuesto": 20000,
            "moneda": "EUR",
            "objetivos": {"aperturas": 3000, "reuniones": 30},
        },
        {
            "clave": "catalogo-tecnico",
            "nombre": "Descarga del catálogo técnico",
            "nivel": "campana",
            "tipo": "captacion",
            "canal": "web",
            "desde": _f(-120),
            "hasta": _f(60),
            "presupuesto": 15000,
            "moneda": "EUR",
            "objetivos": {"descargas": 1200, "leads": 300},
        },
    ]
    for campana in campanas:
        api.crear("/api/v1/campanas", campana)

    # Supresiones y rebotes: la higiene de la lista. Se siembran con direcciones
    # de dominios reservados a documentación (RFC 2606), para que no exista la
    # posibilidad de que un envío de prueba alcance a alguien real.
    supresiones = [
        {
            "direccion": "baja.voluntaria@example.com",
            "canal": "email",
            "motivo": "baja",
            "ambito": "global",
            "detalle": "Se dio de baja desde el pie del correo",
        },
        {
            "direccion": "queja@example.com",
            "canal": "email",
            "motivo": "queja",
            "ambito": "global",
            "detalle": "Marcó el envío como spam",
        },
        {
            "direccion": "no-comercial@example.org",
            "canal": "email",
            "motivo": "peticion",
            "ambito": "categoria",
            "detalle": "Solo quiere avisos operativos",
        },
    ]
    for supresion in supresiones:
        api.crear("/api/v1/supresiones", supresion)

    rebotes = [
        {
            "direccion": "buzon-inexistente@example.com",
            "tipo": "duro",
            "codigo": "550",
            "detalle": "Mailbox does not exist",
            "proveedor": "ses",
        },
        {
            "direccion": "buzon-lleno@example.org",
            "tipo": "blando",
            "codigo": "452",
            "detalle": "Mailbox full",
            "proveedor": "ses",
        },
        {
            "direccion": "dominio-caido@example.net",
            "tipo": "blando",
            "codigo": "421",
            "detalle": "Service not available",
            "proveedor": "ses",
        },
    ]
    for rebote in rebotes:
        api.crear("/api/v1/rebotes", rebote)


# ── Servicio: canales, SLA, macros, conocimiento y portal ─────────────────


def sembrar_servicio(api: Api, aprobador: Api | None = None) -> None:
    """Todo lo que hace falta para atender un caso de principio a fin."""
    canales = [
        {
            "clave": "soporte_email",
            "nombre": "soporte@ficosa.com",
            "tipo": "correo",
            "direccion_propia": "soporte@ficosa.com",
            "mapeo": {"titulo": "subject", "descripcion": "body", "email": "from"},
            "obligatorios": ["email"],
            "max_por_hora": 500,
        },
        {
            "clave": "portal_cliente",
            "nombre": "Portal de cliente",
            "tipo": "portal",
            "mapeo": {"titulo": "asunto", "descripcion": "detalle"},
            "obligatorios": ["titulo"],
            "campo_trampa": "referencia_interna",
        },
        {
            "clave": "telefono",
            "nombre": "Teléfono de soporte",
            "tipo": "telefono",
            "fijos": {"origen": "llamada"},
        },
        {
            "clave": "rma",
            "nombre": "Devoluciones y garantías (RMA)",
            "tipo": "formulario",
            "mapeo": {"titulo": "motivo", "descripcion": "descripcion"},
            "fijos": {"categoria": "garantia"},
            "obligatorios": ["titulo"],
        },
    ]
    for canal in canales:
        api.crear("/api/v1/canales-servicio", canal)

    cuentas = api.listar("/api/v1/accounts", 30)
    planes = [
        ("soporte_24x7", "Soporte 24x7 (línea de producción)", "24x7", 1000, 400.0),
        ("soporte_estandar", "Soporte estándar 8x5", "estandar", 200, 80.0),
        ("soporte_basico", "Soporte básico", "basico", 50, 20.0),
    ]
    for i, (clave, nombre, plan, casos, horas) in enumerate(planes):
        cuenta = cuentas[i] if i < len(cuentas) else None
        cuerpo = {
            "clave": clave,
            "nombre": nombre,
            "plan": plan,
            "casos_incluidos": casos,
            "horas_incluidas": horas,
            # Al agotar se avisa, no se corta: cortar el soporte de una línea
            # parada porque se acabó la bolsa de horas es exactamente lo que
            # nadie quiere que pase de forma automática.
            "al_agotar": "avisar",
            "vigente_desde": _f(-180),
            "vigente_hasta": _f(185),
        }
        if cuenta and cuenta.get("id"):
            cuerpo["cuenta_id"] = str(cuenta["id"])
        api.crear("/api/v1/entitlements", cuerpo)

    # A quién se avisa son usuarios concretos, no un rol escrito a mano: la
    # regla tiene que poder mandar el aviso sin resolver nada en el momento del
    # incumplimiento, que es cuando menos conviene depender de una tabla más.
    responsables = [str(u["id"]) for u in api.listar("/api/v1/usuarios", 20) if u.get("id")][:3]
    reglas = [
        {
            "nombre": "Aviso al consumir el 75 % del plazo",
            "prioridad": 10,
            "consumido_pct": 75,
            "severidad_minima": "normal",
            "avisar_a": responsables[:1],
        },
        {
            "nombre": "Al 90 %, sube de nivel",
            "prioridad": 20,
            "consumido_pct": 90,
            "subir_nivel": True,
            "subir_prioridad": True,
            "avisar_a": responsables[:2],
        },
        {
            "nombre": "Incumplido: a la cola de dirección",
            "prioridad": 30,
            "al_incumplir": True,
            "cola_destino": "direccion_servicio",
            "avisar_a": responsables,
        },
        {
            "nombre": "Clientes VIP: se escala antes",
            "prioridad": 5,
            "consumido_pct": 50,
            "solo_vip": True,
            "subir_prioridad": True,
            "avisar_a": responsables[:1],
        },
    ]
    for regla in reglas:
        api.crear("/api/v1/escalado/reglas", regla)

    macros = [
        {
            "clave": "acuse",
            "nombre": "Acuse de recibo",
            "cuerpo": "Hemos recibido tu consulta y la estamos revisando. "
            "Te respondemos con el diagnóstico en cuanto lo tengamos.",
            "acciones": {"estado": "en_curso"},
            "canales": ["email", "portal"],
        },
        {
            "clave": "pedir_datos",
            "nombre": "Pedir número de serie y lote",
            "cuerpo": "Para poder seguir necesitamos el número de serie de la pieza "
            "y el lote de fabricación, que están en la etiqueta lateral.",
            "acciones": {"estado": "esperando_cliente"},
            "canales": ["email", "portal"],
        },
        {
            "clave": "abrir_rma",
            "nombre": "Abrir devolución",
            "cuerpo": "Abrimos una devolución (RMA). Recibirás la etiqueta de envío "
            "y las instrucciones de embalaje en un correo aparte.",
            "acciones": {"categoria": "garantia", "prioridad": "alta"},
            "canales": ["email"],
        },
        {
            "clave": "cerrar_resuelto",
            "nombre": "Cerrar como resuelto",
            "cuerpo": "Damos el caso por resuelto. Si vuelve a ocurrir, respóndenos "
            "a este mismo mensaje y lo reabrimos con todo el histórico.",
            "acciones": {"estado": "resuelto"},
            "canales": ["email", "portal"],
        },
    ]
    for macro in macros:
        api.crear("/api/v1/macros", macro)

    articulos = [
        {
            "clave": "kb-rma",
            "titulo": "Cómo abrir una devolución (RMA)",
            "resumen": "Pasos, plazos y qué datos hacen falta para tramitar una garantía.",
            "cuerpo": "## Antes de empezar\n\nTen a mano el número de serie y el lote.\n\n"
            "## Pasos\n\n1. Abre un caso desde el portal indicando «garantía».\n"
            "2. Adjunta una foto de la etiqueta y del defecto.\n"
            "3. Recibirás la etiqueta de envío en 24 h laborables.\n\n"
            "## Plazos\n\nLa garantía cubre 24 meses desde la entrega.",
            "audiencia": "cliente",
            "etiquetas": ["garantia", "rma", "logistica"],
            "canales": ["portal", "email"],
            "revisar_el": _f(180),
        },
        {
            "clave": "kb-serie",
            "titulo": "Dónde encontrar el número de serie",
            "resumen": "Ubicación de la etiqueta según familia de producto.",
            "cuerpo": "La etiqueta va en el lateral derecho de la carcasa. En los "
            "espejos retrovisores está bajo la tapa del anclaje.",
            "audiencia": "cliente",
            "etiquetas": ["identificacion"],
            "canales": ["portal"],
        },
        {
            "clave": "kb-linea-parada",
            "titulo": "Protocolo de línea parada",
            "resumen": "Qué hacer cuando un cliente notifica que su línea está detenida.",
            "cuerpo": "## Es prioridad crítica, siempre\n\n1. Abrir el caso con "
            "prioridad crítica aunque el plan no lo cubra.\n"
            "2. Avisar al responsable de la cuenta y al jefe de planta.\n"
            "3. Convocar puente técnico en menos de una hora.\n\n"
            "No esperes a la confirmación del entitlement: se revisa después.",
            "audiencia": "interno",
            "etiquetas": ["critico", "protocolo"],
            "revisar_el": _f(90),
        },
        {
            "clave": "kb-homologacion",
            "titulo": "Documentación de homologación por mercado",
            "resumen": "Qué certificados pide cada mercado y quién los emite.",
            "cuerpo": "Europa: ECE R46. Estados Unidos: FMVSS 111. China: CCC.\n"
            "Los certificados los emite calidad y se adjuntan a la ficha del programa.",
            "audiencia": "interno",
            "etiquetas": ["calidad", "homologacion"],
        },
    ]
    claves_publicables = []
    for articulo in articulos:
        creado = api.crear("/api/v1/conocimiento/articulos", articulo)
        if creado and creado.get("id"):
            claves_publicables.append(creado["id"])
    # Publicar algunos: una base de conocimiento entera en borrador no la ve
    # nadie, y la pantalla del portal saldría vacía sin explicar por qué. Lo
    # hace el aprobador, no el autor, porque el servicio lo exige y tiene razón.
    publica = aprobador or api
    for articulo_id in claves_publicables[:3]:
        publica.crear(f"/api/v1/conocimiento/{articulo_id}/publicar", {})

    # Portal y comunidad: cuelgan de contactos reales, así que se buscan.
    contactos = api.listar("/api/v1/contacts", 30)
    accesos: list[str] = []
    for contacto in contactos[:6]:
        if not contacto.get("id") or not contacto.get("email"):
            continue
        creado = api.crear(
            "/api/v1/portal/accesos",
            {
                "contacto_id": str(contacto["id"]),
                "email": str(contacto["email"]),
                "nivel": "cuenta",
                "secciones": ["casos", "conocimiento", "pedidos", "documentos"],
            },
        )
        if creado and creado.get("id"):
            accesos.append(str(creado["id"]))

    hilos = [
        (
            "¿Compatibilidad del sensor RS-220 con la serie anterior?",
            "Estamos montando la serie 2024 y queremos saber si el RS-220 es "
            "retrocompatible con el arnés antiguo o hace falta adaptador.",
            "producto",
        ),
        (
            "Plazo habitual de una RMA en agosto",
            "¿Los plazos de devolución se alargan en agosto? Lo preguntamos para "
            "planificar el paro de la línea.",
            "logistica",
        ),
        (
            "Certificado ECE R46 actualizado",
            "Necesitamos la última revisión del certificado para el expediente de "
            "homologación de nuestro cliente final.",
            "calidad",
        ),
    ]
    for i, (titulo, cuerpo, categoria) in enumerate(hilos):
        if i < len(accesos):
            api.crear(
                "/api/v1/comunidad/hilos",
                {
                    "acceso_id": accesos[i],
                    "titulo": titulo,
                    "cuerpo": cuerpo,
                    "categoria": categoria,
                },
            )


# ── Gobierno: retención, derechos, riesgos y controles ────────────────────


def sembrar_gobierno(api: Api) -> None:
    """Lo que hay que tener puesto para que esto sea legal de explotar.

    Se siembra con datos de verdad —plazos, riesgos y controles que un
    responsable reconocería— y no con ejemplos vacíos, porque estas pantallas
    existen precisamente para que alguien las revise.
    """
    # Las clases de dato las declara el propio servicio: se leen de la API en
    # vez de escribirlas aquí, porque una lista a mano se queda desfasada y
    # entonces la política que más importa es justo la que no se fija.
    plazos = {
        "actividades": (1095, "Tres años: es el histórico que sostiene el análisis de cartera"),
        "adjuntos_borrados": (30, "Un mes de margen para recuperar un borrado por error"),
        "comentarios_borrados": (30, "Mismo margen que los adjuntos, por coherencia"),
        "contactos_borrados": (30, "Un mes en la papelera antes de la destrucción definitiva"),
        "cuentas_borradas": (90, "Tres meses: una cuenta borrada por error se nota más tarde"),
        "descargas_adjunto": (365, "Un año de traza de descargas, por si hay que auditar una fuga"),
        "papelera": (60, "Dos meses de papelera general"),
        "solicitudes_derechos": (
            1095,
            "Tres años: hay que poder demostrar que se atendió y cuándo",
        ),
    }
    declaradas = {c.get("clave") for c in api.listar("/api/v1/party/retencion/clases", 100)}
    politicas = [
        {"clase": clase, "dias": dias, "motivo": motivo, "activa": True}
        for clase, (dias, motivo) in plazos.items()
        if not declaradas or clase in declaradas
    ]
    for politica in politicas:
        api.crear("/api/v1/party/retencion/politicas", politica, metodo="PUT")

    api.crear(
        "/api/v1/party/retencion/bloqueos",
        {
            "motivo": "Litigio abierto con un proveedor: no se puede purgar nada de esta cuenta",
            "objeto": "cuenta",
            "referencia": "LEG-2026-014",
        },
    )
    api.crear(
        "/api/v1/party/retencion/bloqueos",
        {
            "motivo": "Auditoría de calidad en curso (IATF 16949)",
            "objeto": "caso",
            "referencia": "AUD-2026-03",
        },
    )

    contactos = api.listar("/api/v1/contacts", 10)
    peticiones = [
        ("acceso", "Quiere saber qué datos suyos tenemos"),
        ("supresion", "Pide que borremos sus datos tras dejar la empresa"),
        ("rectificacion", "El cargo que consta no es el suyo"),
        ("portabilidad", "Pide sus datos en formato reutilizable"),
        ("oposicion", "No quiere recibir más comunicaciones comerciales"),
    ]
    for i, (tipo, _motivo_humano) in enumerate(peticiones):
        contacto = contactos[i] if i < len(contactos) else None
        cuerpo: dict[str, Any] = {
            "tipo": tipo,
            "email_solicitante": str(
                (contacto or {}).get("email") or f"solicitante{i}@example.com"
            ),
            "canal_entrada": "email" if i % 2 == 0 else "portal",
        }
        if contacto and contacto.get("id"):
            cuerpo["contacto_id"] = str(contacto["id"])
        api.crear("/api/v1/data-subject-requests", cuerpo)

    riesgos = [
        (
            "RSK-001",
            {
                "titulo": "Fuga de datos de contacto por exportación masiva",
                "descripcion": "Un comercial puede exportar toda la cartera antes de irse",
                "categoria": "privacidad",
                "probabilidad": 3,
                "impacto": 4,
                "tratamiento": "mitigar",
                "estado": "abierto",
                "residual_probabilidad": 2,
                "residual_impacto": 3,
                "revision_at": _f(90),
            },
        ),
        (
            "RSK-002",
            {
                "titulo": "Envío comercial sin consentimiento válido",
                "descripcion": "Sanción por comunicación a contactos sin base legal",
                "categoria": "cumplimiento",
                "probabilidad": 2,
                "impacto": 5,
                "tratamiento": "mitigar",
                "estado": "abierto",
                "residual_probabilidad": 1,
                "residual_impacto": 4,
                "revision_at": _f(60),
            },
        ),
        (
            "RSK-003",
            {
                "titulo": "Previsión de ventas poco fiable",
                "descripcion": "Decisiones de capacidad sobre un embudo desactualizado",
                "categoria": "operacional",
                "probabilidad": 4,
                "impacto": 3,
                "tratamiento": "mitigar",
                "estado": "abierto",
                "residual_probabilidad": 2,
                "residual_impacto": 3,
                "revision_at": _f(30),
            },
        ),
        (
            "RSK-004",
            {
                "titulo": "Dependencia de una integración con el ERP",
                "descripcion": "Si el ERP cae, no se pueden confirmar pedidos",
                "categoria": "tecnologico",
                "probabilidad": 2,
                "impacto": 4,
                "tratamiento": "transferir",
                "estado": "abierto",
                "revision_at": _f(120),
            },
        ),
    ]
    for codigo, riesgo in riesgos:
        api.crear(f"/api/v1/grc/riesgos/{codigo}", riesgo, metodo="PUT")

    controles = [
        (
            "CTL-001",
            {
                "nombre": "Límite y traza de las exportaciones",
                "descripcion": "Toda exportación queda registrada y por encima de 500 filas pide motivo",
                "tipo": "preventivo",
                "automatico": True,
                "frecuencia": "continuo",
                "activo": True,
                "riesgos": ["RSK-001"],
                "marcos": [
                    {"marco": "ISO 27001", "referencia": "A.8.12"},
                    {"marco": "RGPD", "referencia": "art. 32"},
                ],
                "fuente_evidencia": "auditoria",
            },
        ),
        (
            "CTL-002",
            {
                "nombre": "Comprobación de consentimiento antes de cada envío",
                "descripcion": "El canal rechaza el envío si no hay consentimiento vigente",
                "tipo": "preventivo",
                "automatico": True,
                "frecuencia": "continuo",
                "activo": True,
                "riesgos": ["RSK-002"],
                "marcos": [
                    {"marco": "RGPD", "referencia": "art. 6"},
                    {"marco": "LSSI", "referencia": "art. 21"},
                ],
                "fuente_evidencia": "marketing",
            },
        ),
        (
            "CTL-003",
            {
                "nombre": "Revisión mensual del embudo",
                "descripcion": "Las oportunidades sin movimiento en 30 días se revisan en comité",
                "tipo": "detectivo",
                "automatico": False,
                "frecuencia": "mensual",
                "activo": True,
                "riesgos": ["RSK-003"],
                "fuente_evidencia": "pipeline",
            },
        ),
        (
            "CTL-004",
            {
                "nombre": "Separación de funciones en aprobaciones",
                "descripcion": "Quien pide un descuento no puede aprobarlo",
                "tipo": "preventivo",
                "automatico": True,
                "frecuencia": "continuo",
                "activo": True,
                "marcos": [{"marco": "SOX", "referencia": "302"}],
                "fuente_evidencia": "identidad",
            },
        ),
    ]
    for codigo, control in controles:
        api.crear(f"/api/v1/grc/controles/{codigo}", control, metodo="PUT")


# ── Canal indirecto: quién revende y con qué reglas ───────────────────────


def sembrar_canal(api: Api) -> None:
    """Partners, sus niveles, sus registros de oportunidad y su comisión.

    Un fabricante de componentes no vende solo en directo: tiene distribuidores
    e integradores, y el conflicto de siempre —dos que registran el mismo
    cliente— se resuelve con la protección por niveles. Sin datos, esa pantalla
    no se entiende: el registro de oportunidad parece burocracia hasta que ves
    dos apuntando al mismo sitio.
    """
    niveles = [
        {
            "clave": "plata",
            "nombre": "Plata",
            "orden": 1,
            "facturacion_minima": 50000,
            "descuento_extra_pct": 3,
            "dias_proteccion": 30,
        },
        {
            "clave": "oro",
            "nombre": "Oro",
            "orden": 2,
            "facturacion_minima": 250000,
            "certificaciones_exigidas": ["tecnica_nivel_1"],
            "descuento_extra_pct": 7,
            "dias_proteccion": 60,
        },
        {
            "clave": "platino",
            "nombre": "Platino",
            "orden": 3,
            "facturacion_minima": 1000000,
            "certificaciones_exigidas": ["tecnica_nivel_1", "tecnica_nivel_2"],
            "descuento_extra_pct": 12,
            "dias_proteccion": 90,
        },
    ]
    for nivel in niveles:
        api.crear("/api/v1/niveles-partner", nivel)

    cuentas = api.listar("/api/v1/accounts", 30)
    partners = [
        {
            "clave": "iberdist",
            "nombre": "Iberdist Componentes S.L.",
            "tipo": "distribuidor",
            "canal": "recambio",
            "pais": "ES",
        },
        {
            "clave": "eurotech",
            "nombre": "EuroTech Integration GmbH",
            "tipo": "integrador",
            "canal": "oem",
            "pais": "DE",
        },
        {
            "clave": "lusoparts",
            "nombre": "LusoParts Lda.",
            "tipo": "distribuidor",
            "canal": "recambio",
            "pais": "PT",
        },
    ]
    creados: list[str] = []
    for i, partner in enumerate(partners):
        if i < len(cuentas) and cuentas[i].get("id"):
            partner["cuenta_id"] = str(cuentas[i]["id"])
        hecho = api.crear("/api/v1/partners", partner)
        if hecho and hecho.get("id"):
            creados.append(str(hecho["id"]))

    registros = [
        ("Grupo Talleres Unidos", 120000, "Renovación de la gama de retrovisores"),
        ("Carrocerías del Sur", 48000, "Primer pedido de sensores de aparcamiento"),
        ("Autobuses Levante", 310000, "Equipamiento de flota completa"),
    ]
    for i, (cliente, importe, descripcion) in enumerate(registros):
        cuerpo: dict[str, Any] = {
            "cliente_nombre": cliente,
            "importe_estimado": importe,
            "moneda": "EUR",
            "cierre_estimado": _f(45 + i * 30),
            "descripcion": descripcion,
        }
        if i < len(creados):
            cuerpo["partner_id"] = creados[i]
        api.crear("/api/v1/registros-oportunidad", cuerpo)

    api.crear(
        "/api/v1/planes-comision",
        {
            "clave": "canal_2026",
            "nombre": "Comisión de canal 2026",
            "desde": _f(-60),
            "hasta": _f(300),
            "base": "margen",
            "moneda": "EUR",
            "periodicidad": "trimestral",
            # Se devenga al cobrar y no al firmar: comisionar sobre una factura
            # que luego no se cobra obliga a reclamar dinero ya pagado, y eso
            # no se recupera nunca del todo.
            "devengo": "cobro",
        },
    )
    api.crear(
        "/api/v1/planes-comision",
        {
            "clave": "directa_2026",
            "nombre": "Comisión de venta directa 2026",
            "desde": _f(-60),
            "hasta": _f(300),
            "base": "importe",
            "moneda": "EUR",
            "periodicidad": "mensual",
            "devengo": "cobro",
        },
    )

    for i, partner_id in enumerate(creados):
        api.crear(
            "/api/v1/fondos-mdf",
            {
                "partner_id": partner_id,
                "nombre": f"Fondo de marketing {2026} · {partners[i]['nombre']}",
                "desde": _f(-30),
                "hasta": _f(335),
                "asignado": 15000 + i * 10000,
                "moneda": "EUR",
            },
        )


# ── Servicio de campo: quién va, con qué y a qué ──────────────────────────


def sembrar_campo(api: Api) -> None:
    """Técnicos, activos instalados, órdenes de trabajo y mantenimiento.

    Es el módulo que convierte «tenemos un caso» en «va Andrés el martes con la
    pieza». Vacío, todas sus pantallas parecen listas de nada: la de repuestos,
    la de planes preventivos y la de órdenes sin asignar son las tres que un
    responsable mira cada mañana.
    """
    usuarios = api.listar("/api/v1/usuarios", 20)
    cuentas = api.listar("/api/v1/accounts", 20)

    tecnicos = [
        # La competencia lleva nivel: «sabe de» y «está certificado en» no son
        # lo mismo, y el planificador distingue las dos cosas al asignar.
        (
            "Zona norte",
            ["ES-PV", "ES-NA", "ES-CB"],
            [
                {"clave": "electronica", "nivel": "certificado"},
                {"clave": "mecanica", "nivel": "basico"},
            ],
        ),
        (
            "Zona levante",
            ["ES-VC", "ES-MU"],
            [
                {"clave": "electronica", "nivel": "basico"},
                {"clave": "software", "nivel": "certificado"},
            ],
        ),
        ("Zona centro", ["ES-MD", "ES-CM"], [{"clave": "mecanica", "nivel": "certificado"}]),
    ]
    for i, (nombre, zonas, competencias) in enumerate(tecnicos):
        if i >= len(usuarios) or not usuarios[i].get("id"):
            continue
        api.crear(
            "/api/v1/tecnicos-campo",
            {
                "usuario_id": str(usuarios[i]["id"]),
                "nombre": f"Técnico de {nombre.lower()}",
                "zonas": zonas,
                "competencias": competencias,
                "minutos_jornada": 480,
            },
        )

    activos = [
        ("Línea de montaje L1", "RS-220", "Ficosa", "Nave 1 · Planta baja"),
        ("Banco de pruebas ADAS", "BP-ADAS-3", "Ficosa", "Laboratorio"),
        ("Célula de visión artificial", "CV-900", "Ficosa", "Nave 2"),
        ("Estación de calibración", "EC-120", "Ficosa", "Nave 2 · Zona limpia"),
    ]
    ids_activo: list[str] = []
    for i, (nombre, modelo, fabricante, ubicacion) in enumerate(activos):
        cuerpo: dict[str, Any] = {
            "nombre": nombre,
            "modelo": modelo,
            "fabricante": fabricante,
            "ubicacion": ubicacion,
            "numero_serie": f"SN-2024-{1000 + i}",
            "instalado_el": _f(-400 + i * 30),
            "contador": 4200 + i * 900,
            "unidad_contador": "horas",
        }
        if i < len(cuentas) and cuentas[i].get("id"):
            cuerpo["cuenta_id"] = str(cuentas[i]["id"])
        hecho = api.crear("/api/v1/activos", cuerpo)
        if hecho and hecho.get("id"):
            ids_activo.append(str(hecho["id"]))

    ordenes = [
        ("Sustituir el sensor de la estación 3", "correctiva", "alta", 120),
        ("Calibración semestral", "preventiva", "normal", 180),
        ("Revisión tras aviso de vibración", "correctiva", "critica", 240),
        ("Actualizar firmware de la célula de visión", "preventiva", "baja", 90),
        ("Puesta en marcha del banco nuevo", "instalacion", "normal", 300),
    ]
    for i, (titulo, tipo, prioridad, minutos) in enumerate(ordenes):
        cuerpo = {
            "titulo": titulo,
            "tipo": tipo,
            "prioridad": prioridad,
            "duracion_estimada_min": minutos,
            "zona": ["ES-PV", "ES-VC", "ES-MD"][i % 3],
            "ventana_desde": f"{_f(2 + i)}T08:00:00Z",
            "ventana_hasta": f"{_f(2 + i)}T18:00:00Z",
        }
        if ids_activo:
            cuerpo["activo_id"] = ids_activo[i % len(ids_activo)]
        if i < len(cuentas) and cuentas[i].get("id"):
            cuerpo["cuenta_id"] = str(cuentas[i]["id"])
        api.crear("/api/v1/ordenes-trabajo", cuerpo)

    for i, activo_id in enumerate(ids_activo[:3]):
        api.crear(
            "/api/v1/planes-preventivos",
            {
                "nombre": f"Mantenimiento programado · {activos[i][0]}",
                "activo_id": activo_id,
                "cada_dias": [90, 180, 365][i],
                "duracion_min": 120,
                "competencias": ["mecanica"],
                "antelacion_dias": 15,
                "checklist": [
                    {"paso": "Revisar holguras", "obligatorio": True},
                    {"paso": "Cambiar filtro", "obligatorio": True},
                    {"paso": "Registrar el contador", "obligatorio": False},
                ],
            },
        )

    devoluciones = [
        ("Pieza recibida con el conector dañado", "Llegó rota de fábrica"),
        ("No corresponde a la referencia pedida", "Error de preparación"),
    ]
    for i, (motivo, descripcion) in enumerate(devoluciones):
        cuerpo = {"motivo": motivo, "descripcion": descripcion, "comprado_el": _f(-45 - i * 10)}
        if i < len(cuentas) and cuentas[i].get("id"):
            cuerpo["cuenta_id"] = str(cuentas[i]["id"])
        api.crear("/api/v1/devoluciones", cuerpo)

    problemas = [
        ("Falsos positivos del sensor RS-220 con lluvia intensa", "alta"),
        ("Consumo elevado en la célula de visión tras el último firmware", "normal"),
    ]
    for titulo, severidad in problemas:
        api.crear(
            "/api/v1/problemas",
            {
                "titulo": titulo,
                "severidad": severidad,
                "descripcion": (
                    "Se agrupan aquí los casos con la misma causa: se arregla una vez "
                    "y se cierran todos, en vez de contestar veinte veces lo mismo."
                ),
            },
        )

    api.crear(
        "/api/v1/expedientes",
        {
            "asunto": "Reclamación ante la junta arbitral de consumo",
            "entrada_at": f"{_f(-12)}T10:00:00Z",
            "plazo_dias": 30,
            "plazo_habiles": True,
            "tipo": "reclamacion",
            "via": "organismo",
            "organismo": "Junta Arbitral de Consumo de Cataluña",
            "referencia_externa": "JAC-2026-00412",
        },
    )


def sembrar_rastro(api: Api) -> None:
    """Las pantallas que no se llenan creando, sino usando.

    La papelera, los reenvíos, el archivo de eventos: son consecuencia de
    trabajar, no cosas que se den de alta. Vacías no se entienden —«papelera»
    sin nada dentro no dice si guarda borrados o si no funciona— así que aquí
    se provoca la consecuencia de verdad, borrando algo que se acaba de crear
    para eso, en vez de escribir una fila a mano en su tabla.
    """
    for i, nombre in enumerate(("Contacto duplicado", "Contacto dado de baja")):
        creado = api.crear(
            "/api/v1/contacts",
            {
                "nombre": nombre,
                "apellidos": "(de prueba)",
                "email": f"papelera{i}@example.com",
            },
        )
        if creado and creado.get("id"):
            estado, _ = api._llamar("DELETE", f"/api/v1/contacts/{creado['id']}")
            if estado not in (200, 202, 204):
                api.fallos.append(f"DELETE /api/v1/contacts/{creado['id']} → {estado}")


def sembrar_analitica(api: Api) -> None:
    """Preguntas ya hechas, para que el historial de consultas no salga vacío."""
    preguntas = [
        "¿Cuántas oportunidades hay abiertas por etapa?",
        "Ingreso previsto para el próximo trimestre por comercial",
        "Casos abiertos por cliente y prioridad",
        "Tasa de conversión de lead a oportunidad, por canal de origen",
        "Cuentas sin actividad en los últimos 90 días",
        "Descuento medio concedido por familia de producto",
    ]
    for i, pregunta in enumerate(preguntas):
        api.crear(
            "/api/v1/analitica/consultas",
            {
                "pregunta": pregunta,
                "fuente": "almacen",
                "filas_devueltas": 12 + i * 7,
                "duracion_ms": 180 + i * 45,
                "contexto": {"origen": "sembrado inicial"},
            },
        )


# ── Arranque ──────────────────────────────────────────────────────────────

PARTES: dict[str, Any] = {
    "identidad": sembrar_identidad,
    "metadatos": sembrar_metadatos,
    "procesos": sembrar_procesos,
    "automatizacion": sembrar_automatizacion,
    "integraciones": sembrar_integraciones,
    "ventas": sembrar_ventas,
    "marketing": sembrar_marketing,
    "servicio": sembrar_servicio,
    "gobierno": sembrar_gobierno,
    "canal": sembrar_canal,
    "campo": sembrar_campo,
    "analitica": sembrar_analitica,
    "rastro": sembrar_rastro,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://localhost:18080")
    parser.add_argument("--tenant", required=True, help="identificador corto de la empresa")
    parser.add_argument("--email", required=True)
    parser.add_argument("--contrasena", required=True)
    parser.add_argument(
        "--aprobador",
        default="",
        help=(
            "correo de una SEGUNDA persona, para lo que el sistema no deja "
            "aprobar a quien lo crea (publicar conocimiento hacia el cliente)"
        ),
    )
    parser.add_argument(
        "--parte",
        default="todo",
        help="una de: " + ", ".join(PARTES) + ", o «todo»",
    )
    cfg = parser.parse_args()

    api = Api(cfg.base)
    api.entrar(cfg.email, cfg.contrasena, cfg.tenant)

    aprobador = api.como(cfg.aprobador, cfg.contrasena, cfg.tenant) if cfg.aprobador else None

    partes = list(PARTES) if cfg.parte == "todo" else [cfg.parte]
    for nombre in partes:
        if nombre not in PARTES:
            raise SystemExit(f"Parte desconocida: «{nombre}». Hay: {', '.join(PARTES)}")
        antes = api.cuenta["creados"]
        if nombre == "servicio":
            sembrar_servicio(api, aprobador)
        else:
            PARTES[nombre](api)
        print(f"  {nombre:16} {api.cuenta['creados'] - antes:4} registros")

    print(f"\nCreados {api.cuenta['creados']}, ya existían {api.cuenta['saltados']}.")
    if api.fallos:
        print(f"\n{len(api.fallos)} altas rechazadas por la API:")
        for fallo in api.fallos:
            print(f"  · {fallo}")
        # Se devuelve error: un sembrado a medias que dice que todo fue bien es
        # cómo se acaba mirando una pantalla vacía sin saber que falló su alta.
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
