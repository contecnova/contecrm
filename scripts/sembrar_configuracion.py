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
        # El identificador del tenant, que algún alta pide en el cuerpo. Se
        # saca de la sesión al entrar y no se pasa por parámetro: el que
        # manda es el de la sesión, y pedirlo aparte abre la puerta a sembrar
        # en un tenant distinto del que se ha entrado.
        self.tenant_id: str = ""

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
        estado, yo = self._llamar("GET", "/api/v1/auth/me")
        self.tenant_id = str((yo or {}).get("tenant_id") or "") if estado == 200 else ""

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
        if estado == 422 and "limite" in str(_motivo(cuerpo)):
            # **No todo lo que devuelve una lista es una colección paginada.**
            # Hay extremos que devuelven un catálogo acotado —las clases de
            # retención de un servicio, los planes de comisión de un tenant—:
            # no declaran `limite` porque no crece, y la API rechaza por
            # principio el parámetro que no mira, que es lo correcto —un
            # filtro que se ignora en silencio devuelve de más y nadie se
            # entera—. El que se equivocaba era este cliente, mandándolo a
            # todo. Se reintenta sin él en vez de apuntarlo como fallo: tres
            # listados salían en el informe de altas rechazadas sin que nada
            # estuviera roto.
            estado, cuerpo = self._llamar("GET", ruta)
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
        if isinstance(cuerpo, dict):
            if isinstance(cuerpo.get("items"), list):
                return list(cuerpo["items"])
            # Y la tercera forma: cuarenta extremos devuelven su lista bajo su
            # propio nombre —`{partners: […]}`, `{ordenes: […]}`—. Se coge
            # cuando hay una sola propiedad que sea un array; con dos no se
            # adivina y elegir mal es peor que no elegir.
            arrays = [v for v in cuerpo.values() if isinstance(v, list)]
            if len(arrays) == 1:
                return list(arrays[0])
        return []

    def subir(
        self, ruta: str, nombre: str, contenido: bytes, campos: dict[str, str]
    ) -> dict | None:
        """Sube un fichero por `multipart/form-data`, a mano.

        Sin dependencias, como el resto de este cliente: corre antes que nada y
        añadir `requests` para esto sería pagar una dependencia por veinte
        líneas. Los adjuntos son el panel que más se abre en una ficha, y
        salían vacíos en todas: una pantalla de adjuntos vacía se lee como que
        la función no está hecha.
        """
        import uuid as _uuid

        frontera = f"----contecrm{_uuid.uuid4().hex}"
        trozos: list[bytes] = []
        for clave, valor in campos.items():
            trozos.append(
                f'--{frontera}\r\nContent-Disposition: form-data; name="{clave}"\r\n\r\n'
                f"{valor}\r\n".encode()
            )
        trozos.append(
            f'--{frontera}\r\nContent-Disposition: form-data; name="fichero"; '
            f'filename="{nombre}"\r\nContent-Type: text/plain\r\n\r\n'.encode()
        )
        trozos.append(contenido + b"\r\n")
        trozos.append(f"--{frontera}--\r\n".encode())
        cuerpo = b"".join(trozos)

        pet = urllib.request.Request(f"{self.base}{ruta}", data=cuerpo, method="POST")
        pet.add_header("Content-Type", f"multipart/form-data; boundary={frontera}")
        if self.token:
            pet.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(pet, timeout=TIEMPO_ESPERA) as r:
                self.cuenta["creados"] += 1
                crudo = r.read().decode()
                return json.loads(crudo) if crudo else {}
        except urllib.error.HTTPError as e:
            crudo = e.read().decode()
            try:
                respuesta = json.loads(crudo)
            except json.JSONDecodeError:
                respuesta = {"detail": crudo[:300]}
            if e.code == 409:
                self.cuenta["saltados"] += 1
                return None
            self.fallos.append(f"POST {ruta} «{nombre}» → {e.code} {_motivo(respuesta)}")
            return None

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
    """Por qué se ha rechazado, con el campo concreto cuando lo hay.

    «Los datos enviados no son válidos» es el texto del validador de entrada y
    **no dice nada**: el campo que falla viaja aparte, en `errores`. Sin él,
    tres altas rechazadas obligan a reproducirlas a mano una por una para
    enterarse de que lo que fallaba era una lista donde se esperaba un objeto.
    Un diagnóstico que calla lo que sabe cuesta más que no tenerlo, porque
    parece completo.
    """
    if not isinstance(respuesta, dict):
        return str(respuesta)[:200]
    detalles = respuesta.get("errores") or respuesta.get("detalle") or {}
    pistas = ""
    if isinstance(detalles, list) and detalles:
        pistas = " · " + "; ".join(
            f"{'.'.join(str(x) for x in (d.get('loc') or [])[1:])}: {d.get('msg') or d.get('mensaje')}"
            for d in detalles[:4]
            if isinstance(d, dict)
        )
    elif isinstance(detalles, dict) and detalles:
        pistas = " · " + json.dumps(detalles, ensure_ascii=False)[:200]
    for clave in ("mensaje", "detail", "message", "error"):
        if respuesta.get(clave):
            return (str(respuesta[clave])[:300] + pistas)[:500]
    return json.dumps(respuesta, ensure_ascii=False)[:300]


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
    # Antes de crearlas, las que ya hay. Esta ruta **no rechaza el nombre
    # repetido** —una regla de reparto puede llamarse como otra, y está bien
    # que pueda— así que el 409 que hace idempotente al resto del sembrado aquí
    # no llega y una segunda pasada dejaría las tres duplicadas.
    #
    # Comprobado el 27-10-2026 que todavía no había pasado: las seis tarjetas
    # que se veían en pantalla eran tres de este cliente y tres de otro, por el
    # cruce de tenants de la cuenta de plataforma. Esto es para que no pase.
    ya = {str(r.get("nombre") or "") for r in api.listar("/api/v1/lead-routing/reglas", 100)}
    for regla in reglas:
        if regla["candidatos"] and regla["nombre"] not in ya:
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
            # Con fecha de revisión, como todos: un artículo publicado hacia
            # fuera sin ella es el que sigue ahí tres años después describiendo
            # una versión que ya no existe.
            "revisar_el": _f(120),
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
        # La cuenta del contacto va **explícita**: el acceso de nivel «cuenta»
        # filtra por ella, y sin ella el portal entra bien y sale vacío — que se
        # lee como «no tengo casos» y no como «el acceso está mal dado». Quien
        # no la tenga se queda en nivel «propio», que sí funciona sin cuenta.
        # La cuenta sale de la RELACIÓN, no del contacto: un contacto no cuelga
        # de una empresa —la relación es N:M a propósito, porque la misma
        # persona puede serlo de dos—. Sin mirarla aquí, todos los accesos
        # nacían sin cuenta y el portal entraba y salía vacío.
        vinculos = api.listar(f"/api/v1/contacts/{contacto['id']}/cuentas", 5)
        cuenta_id = _uno(vinculos, "cuenta_id", "id")
        creado = api.crear(
            "/api/v1/portal/accesos",
            {
                "contacto_id": str(contacto["id"]),
                "email": str(contacto["email"]),
                "cuenta_id": str(cuenta_id) if cuenta_id else None,
                "nivel": "cuenta" if cuenta_id else "propio",
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
    for i, partner in enumerate(partners):
        if i < len(cuentas) and cuentas[i].get("id"):
            partner["cuenta_id"] = str(cuentas[i]["id"])
        api.crear("/api/v1/partners", partner)

    # Se releen en vez de quedarse con lo que devolvió el alta: al pasar el
    # sembrado por segunda vez, las altas contestan «ya existe» y no devuelven
    # identificador, y entonces todo lo que cuelga de un partner —registros de
    # oportunidad, fondos— se quedaba sin él y fallaba. Un sembrado tiene que
    # poder correrse dos veces.
    por_clave = {
        p.get("clave"): str(p["id"]) for p in api.listar("/api/v1/partners", 50) if p.get("id")
    }
    creados = [por_clave[p["clave"]] for p in partners if p["clave"] in por_clave]

    # Un partner nace en alta y no puede registrar oportunidades hasta que se
    # activa: es la puerta que impide que alguien a medias de onboarding empiece
    # a proteger clientes. Aquí se pasa por ella, no se rodea.
    for partner_id in creados:
        for paso in ("acuerdo_firmado", "formacion", "datos_fiscales"):
            api._llamar("POST", f"/api/v1/partners/{partner_id}/pasos/{paso}", {})
        api.crear(f"/api/v1/partners/{partner_id}/activar", {})

    # Con dominio, no solo con nombre: el registro de oportunidad existe para
    # decidir cuál de dos partners protegió antes al mismo cliente, y el nombre
    # no identifica a nadie —la misma empresa se escribe de cinco maneras—.
    registros = [
        (
            "Grupo Talleres Unidos",
            "talleresunidos.example",
            120000,
            "Renovación de la gama de retrovisores",
        ),
        (
            "Carrocerías del Sur",
            "carroceriasdelsur.example",
            48000,
            "Primer pedido de sensores de aparcamiento",
        ),
        ("Autobuses Levante", "autobuseslevante.example", 310000, "Equipamiento de flota completa"),
    ]
    for i, (cliente, dominio, importe, descripcion) in enumerate(registros):
        cuerpo: dict[str, Any] = {
            "cliente_nombre": cliente,
            "dominio": dominio,
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
        api.crear("/api/v1/activos", cuerpo)

    # Se releen en vez de quedarse con lo que devolvió el alta: en el segundo
    # paso el alta contesta «ya existe» y no devuelve identificador, y entonces
    # todo lo que cuelga de un activo —planes preventivos, telemetría— se
    # quedaba sin crear sin que nada fallara.
    ids_activo = [str(a["id"]) for a in api.listar("/api/v1/activos", 50) if a.get("id")]

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
                "nombre": f"Mantenimiento programado · {activos[i % len(activos)][0]}",
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


# ── Proveedores: quién nos suministra y con qué papeles ───────────────────


def sembrar_proveedores(api: Api) -> None:
    """Cuentas con papel de proveedor, sus homologaciones y sus documentos.

    Un proveedor **es una cuenta con rol**, no un maestro aparte: la misma
    empresa puede ser cliente de una división y proveedor de otra, y tenerla
    dos veces acabaría aplicándole las condiciones de la ficha equivocada.

    Los documentos llevan fecha de caducidad a propósito, y uno a posta **sin
    fecha**: lo que nunca aparece en una lista de vencidos es lo que se queda
    caducado para siempre, y esa pantalla existe para enseñarlo.
    """
    cuentas = api.listar("/api/v1/accounts", 30)
    if not cuentas:
        return

    perfiles = [
        (
            "quimica",
            [
                ("iso9001", "ISO 9001", 400, True),
                ("seguro_rc", "Seguro de responsabilidad civil", 120, True),
                ("ficha_seguridad", "Ficha de seguridad del material", 0, False),
            ],
        ),
        (
            "mecanizado",
            [
                ("iatf16949", "IATF 16949", 250, True),
                ("seguro_rc", "Seguro de responsabilidad civil", -20, True),
            ],
        ),
        (
            "logistica",
            [
                ("iso14001", "ISO 14001", 45, False),
                ("seguro_rc", "Seguro de responsabilidad civil", 500, True),
            ],
        ),
    ]

    for i, (categoria, documentos) in enumerate(perfiles):
        if i >= len(cuentas) or not cuentas[i].get("id"):
            continue
        cuenta_id = str(cuentas[i]["id"])
        api.crear(f"/api/v1/proveedores/{cuenta_id}/rol", {})
        api.crear(
            f"/api/v1/proveedores/{cuenta_id}/homologacion",
            {
                "categoria": categoria,
                "requisitos": [
                    {"clave": "auditoria_inicial", "cubierto": True},
                    {"clave": "muestra_aprobada", "cubierto": True},
                ],
                "valida_hasta": _f(300 + i * 60),
            },
        )
        for clave, nombre, dias, bloquea in documentos:
            api.crear(
                f"/api/v1/proveedores/{cuenta_id}/documentos",
                {
                    "clave": clave,
                    "nombre": nombre,
                    "referencia": f"{clave.upper()}-{2024 + i}",
                    "valido_desde": _f(-500),
                    # `dias = 0` deja el documento sin caducidad, que es el caso
                    # que esta pantalla tiene que saber enseñar.
                    **({"valido_hasta": _f(dias)} if dias else {}),
                    "dias_preaviso": 60,
                    "bloquea_al_vencer": bloquea,
                },
            )
        api.crear(
            f"/api/v1/proveedores/{cuenta_id}/contactos",
            {
                "funcion": "escalado",
                "nombre": "Guardia de incidencias",
                "email": f"guardia{i}@example.com",
                "telefono": "+34 900 000 00{i}".format(i=i),
                # El teléfono de guardia, que es otro: media razón de ser de
                # esta pantalla es «a quién llamo a las once de la noche», y el
                # número de oficina parece servir y no sirve.
                "fuera_de_horario": "+34 600 000 00{i}".format(i=i),
            },
        )


# ── Catálogo de producto y circuito de venta ──────────────────────────────


def sembrar_catalogo(api: Api) -> None:
    """Lo que se vende y a qué precio.

    Sin catálogo no hay oferta, y sin oferta no hay pedido ni contrato: la
    mitad del módulo de ventas enseñaba listas vacías porque faltaba la pieza
    de la que cuelga todo lo demás.
    """
    productos = [
        ("RS-220", "Sensor de aparcamiento RS-220", "sensores", 48.50, 22.10),
        ("RV-940", "Retrovisor exterior con cámara", "vision", 186.00, 94.30),
        ("CAM-ADAS-3", "Cámara frontal ADAS", "vision", 312.00, 158.00),
        ("ARN-12", "Arnés de conexión 12 vías", "conectividad", 14.20, 6.40),
        ("ECU-77", "Unidad de control ECU-77", "electronica", 420.00, 231.00),
        ("SOP-24X7", "Soporte técnico 24x7 (anual)", "servicios", 12000.00, 4800.00),
    ]
    for sku, nombre, familia, precio, coste in productos:
        api.crear(
            "/api/v1/productos",
            {
                "sku": sku,
                "nombre": nombre,
                "familia": familia,
                "descripcion": f"{nombre}. Homologado para el mercado europeo.",
                # El de servicio es recurrente y el resto de una vez: mezclarlos
                # en la misma periodicidad haría que el ingreso recurrente
                # contara como venta puntual, y la previsión saldría al revés.
                "tipo_ingreso": "recurrente" if sku.startswith("SOP") else "unico",
                "periodicidad": "anual" if sku.startswith("SOP") else "",
                "unidad": "ud",
                "precio_base": precio,
                "coste": coste,
                "moneda": "EUR",
                "margen_minimo_pct": 25,
            },
        )

    listas = [
        ("tarifa_oem", "Tarifa OEM", "oem", 10),
        ("tarifa_recambio", "Tarifa de recambio", "recambio", 20),
        ("tarifa_partner", "Tarifa de canal", "partner", 30),
    ]
    for clave, nombre, canal, prioridad in listas:
        api.crear(
            "/api/v1/listas-precio",
            {
                "clave": clave,
                "nombre": nombre,
                "canal": canal,
                "moneda": "EUR",
                "prioridad": prioridad,
                "desde": _f(-180),
                "hasta": _f(185),
            },
        )


def sembrar_cotizacion(api: Api) -> None:
    """Ofertas, pedidos, contratos y suscripciones: lo que sigue a ganar.

    Se encadenan de verdad —la oferta genera el pedido, el pedido el contrato—
    en vez de crearse sueltos: tres listas con registros que no se conocen
    entre sí enseñan que las pantallas existen, no que el circuito funcione.
    """
    cuentas = api.listar("/api/v1/accounts", 20)
    productos = {p.get("sku"): p for p in api.listar("/api/v1/productos", 50)}
    oportunidades = api.listar("/api/v1/opportunities", 20)
    if not cuentas or not productos:
        return

    def linea(sku: str, cantidad: int, descuento: float = 0.0) -> dict[str, Any]:
        producto = productos.get(sku) or {}
        return {
            "producto_id": str(producto.get("id")) if producto.get("id") else None,
            "descripcion": producto.get("nombre") or sku,
            "cantidad": cantidad,
            "descuento_pct": descuento,
            "precio_unitario": float(producto.get("precio_base") or 0) or 100.0,
            "coste_unitario": float(producto.get("coste") or 0) or 50.0,
        }

    ofertas = [
        ("Equipamiento de sensores para la serie 2027", [linea("RS-220", 12000, 8)]),
        (
            "Retrovisores con cámara · programa OEM",
            [linea("RV-940", 3500, 12), linea("ARN-12", 3500)],
        ),
        ("Renovación del soporte 24x7", [linea("SOP-24X7", 1)]),
        ("Cámaras ADAS para preserie", [linea("CAM-ADAS-3", 400, 5), linea("ECU-77", 400)]),
    ]
    creadas: list[str] = []
    for i, (titulo, lineas) in enumerate(ofertas):
        cuerpo: dict[str, Any] = {
            "titulo": titulo,
            "lineas": [{k: v for k, v in fila.items() if v is not None} for fila in lineas],
            "moneda": "EUR",
            "dias_validez": 30,
            "condiciones": "Precios EXW. Plazo de entrega a confirmar en el pedido en firme.",
        }
        if i < len(cuentas) and cuentas[i].get("id"):
            cuerpo["cuenta_id"] = str(cuentas[i]["id"])
        if i < len(oportunidades) and oportunidades[i].get("id"):
            cuerpo["oportunidad_id"] = str(oportunidades[i]["id"])
        hecha = api.crear("/api/v1/presupuestos", cuerpo)
        if hecha and hecha.get("id"):
            creadas.append(str(hecha["id"]))

    # Contratos y suscripciones, colgando de sus cuentas.
    for i, cuenta in enumerate(cuentas[:3]):
        if not cuenta.get("id"):
            continue
        api.crear(
            "/api/v1/contratos",
            {
                "cuenta_id": str(cuenta["id"]),
                "titulo": f"Acuerdo marco de suministro {2026 + i}",
                "inicio": _f(-120 + i * 30),
                "fin": _f(600 + i * 30),
                "importe": 450000 + i * 120000,
                "moneda": "EUR",
                # Renovación automática con preaviso: lo caro de un contrato no
                # es firmarlo, es que se renueve solo sin que nadie lo mire.
                "renovacion_automatica": True,
                "preaviso_dias": 90,
                "meses_renovacion": 12,
            },
        )
        api.crear(
            "/api/v1/suscripciones",
            {
                "cuenta_id": str(cuenta["id"]),
                "plan": ["soporte_24x7", "soporte_estandar", "soporte_basico"][i],
                "importe_periodo": [12000, 4800, 1200][i],
                "inicio": _f(-90 + i * 20),
                "periodicidad": "anual",
                "moneda": "EUR",
                "cantidad": 1,
            },
        )


# ── Previsión: periodos, cuotas y territorio ──────────────────────────────


def sembrar_prevision(api: Api) -> None:
    """Con qué se hace una previsión.

    El módulo enseñaba el resumen del pipeline y se llamaba «Previsión». Sin
    periodos no hay con qué comparar, sin cuota no hay contra qué medir y sin
    territorio no se sabe de quién es cada cosa: las tres pantallas existían y
    las tres estaban vacías.
    """
    hoy = HOY
    trimestre = 3 * ((hoy.month - 1) // 3) + 1
    for i in range(-1, 3):
        mes = trimestre + i * 3
        anyo = hoy.year + (mes - 1) // 12
        mes = (mes - 1) % 12 + 1
        fin_mes = mes + 3
        anyo_fin = anyo + (fin_mes - 1) // 12
        fin_mes = (fin_mes - 1) % 12 + 1
        api.crear(
            "/api/v1/forecast/periodos",
            {
                "clave": f"{anyo}-T{(mes - 1) // 3 + 1}",
                "nombre": f"{anyo} · trimestre {(mes - 1) // 3 + 1}",
                "desde": f"{anyo}-{mes:02d}-01",
                "hasta": (date(anyo_fin, fin_mes, 1) - timedelta(days=1)).isoformat(),
            },
        )

    usuarios = [u for u in api.listar("/api/v1/usuarios", 20) if u.get("id")]
    for i, usuario in enumerate(usuarios[:4]):
        api.crear(
            "/api/v1/cuotas",
            {
                "usuario_id": str(usuario["id"]),
                "desde": _f(-90),
                "hasta": _f(90),
                "objetivo": 750000 + i * 250000,
                "periodo": "trimestral",
                "metrica": "importe",
                "moneda": "EUR",
            },
        )

    # Cada criterio declara de qué TIPO es —geografía, sector, tamaño…— y no
    # solo su condición: es lo que permite explicar por qué una cuenta cayó en
    # un territorio y no en otro, que es la pregunta que llega siempre.
    def geo(paises: list[str]) -> list[dict[str, Any]]:
        return [
            {
                "tipo": "geografia",
                "condiciones": [{"atributo": "pais", "operador": "en", "valor": paises}],
            }
        ]

    territorios = [
        ("iberia", "Iberia", None, geo(["ES", "PT"])),
        ("dach", "DACH", None, geo(["DE", "AT", "CH"])),
        ("francia", "Francia y Benelux", None, geo(["FR", "BE", "NL", "LU"])),
        (
            "oem_global",
            "Cuentas OEM globales",
            None,
            [
                {
                    "tipo": "tamano",
                    "condiciones": [{"atributo": "empleados", "operador": ">=", "valor": 5000}],
                }
            ],
        ),
    ]
    for i, (clave, nombre, _padre, criterios) in enumerate(territorios):
        cuerpo: dict[str, Any] = {
            "clave": clave,
            "nombre": nombre,
            "criterios": criterios,
            # La prioridad decide quién se queda una cuenta que encaja en dos:
            # sin ella, el reparto depende del orden de la tabla y cambia solo.
            "prioridad": 10 * (i + 1),
            "descripcion": f"Cuentas de {nombre}.",
        }
        if i < len(usuarios) and usuarios[i].get("id"):
            cuerpo["responsable_id"] = str(usuarios[i]["id"])
        api.crear("/api/v1/territorios", cuerpo)


def sembrar_prospeccion(api: Api) -> None:
    """Con qué se persigue un lead: cadencias, plantillas y metodología."""
    api.crear(
        "/api/v1/cadencias",
        {
            "clave": "rfq_entrante",
            "nombre": "Petición de oferta entrante",
            "descripcion": "Lo que se hace las dos semanas siguientes a una RFQ",
            "solo_laborable": True,
            "salida_por_cuenta": True,
            "pasos": [
                {
                    "dia": 0,
                    "canal": "correo",
                    "plantilla": "acuse_rfq",
                    "asunto": "Hemos recibido tu petición",
                },
                {"dia": 1, "canal": "llamada", "guion": "Confirmar alcance y plazo"},
                {"dia": 4, "canal": "correo", "plantilla": "propuesta_tecnica"},
                {"dia": 9, "canal": "llamada", "guion": "Seguimiento de la propuesta"},
                {"dia": 14, "canal": "correo", "plantilla": "ultimo_aviso"},
            ],
        },
    )
    api.crear(
        "/api/v1/cadencias",
        {
            "clave": "feria",
            "nombre": "Seguimiento de feria",
            "descripcion": "Los contactos de una feria se enfrían en una semana",
            "solo_laborable": True,
            "pasos": [
                {"dia": 0, "canal": "correo", "plantilla": "gracias_visita"},
                {"dia": 2, "canal": "social", "guion": "Conectar con nota personal"},
                {"dia": 6, "canal": "llamada", "guion": "Proponer reunión técnica"},
            ],
        },
    )

    plantillas = [
        (
            "acuse_rfq",
            "Acuse de petición de oferta",
            "Hemos recibido tu petición, {{contacto.nombre}}",
        ),
        (
            "propuesta_tecnica",
            "Envío de propuesta técnica",
            "Propuesta técnica · {{cuenta.nombre}}",
        ),
        ("ultimo_aviso", "Último contacto antes de cerrar", "¿Seguimos adelante con la propuesta?"),
        ("gracias_visita", "Gracias por la visita", "Un placer verte en {{evento.nombre}}"),
    ]
    for clave, nombre, asunto in plantillas:
        api.crear(
            "/api/v1/plantillas-correo",
            {
                "clave": clave,
                "nombre": nombre,
                "asunto": asunto,
                "cuerpo": (
                    "Hola {{contacto.nombre}}:\n\n"
                    "…\n\n"
                    "Un saludo,\n{{usuario.nombre}} · Ficosa"
                ),
            },
        )

    api.crear(
        "/api/v1/metodologias",
        {
            "clave": "meddic",
            "nombre": "MEDDIC",
            "familia": "meddic",
            # Con criterios y no solo con el nombre: una metodología que no
            # dice qué comprobar es un cartel, no un método.
            "criterios": [
                {"clave": "metricas", "nombre": "Métricas", "pregunta": "¿Qué mejora y cuánto?"},
                {
                    "clave": "comprador_economico",
                    "nombre": "Comprador económico",
                    "pregunta": "¿Quién firma el gasto?",
                },
                {
                    "clave": "criterios_decision",
                    "nombre": "Criterios de decisión",
                    "pregunta": "¿Con qué van a comparar?",
                },
                {
                    "clave": "proceso_decision",
                    "nombre": "Proceso de decisión",
                    "pregunta": "¿Qué pasos faltan hasta la firma?",
                },
                {
                    "clave": "dolor",
                    "nombre": "Dolor identificado",
                    "pregunta": "¿Qué les cuesta hoy no resolverlo?",
                },
                {
                    "clave": "campeon",
                    "nombre": "Campeón",
                    "pregunta": "¿Quién nos vende por dentro?",
                },
            ],
        },
    )


# ── Integración: con qué habla el CRM y cómo traduce ──────────────────────


def sembrar_integracion(api: Api) -> None:
    """Conectores, canales de chat, modelo canónico y vistas federadas.

    Es la parte que decide si el CRM es una isla. Vacía, sus seis pantallas
    enseñan listas de nada y quien mira concluye que no se integra con nada.
    """
    api.crear(
        "/api/v1/modelo-canonico/objetos",
        {
            "clave": "cliente",
            "nombre": "Cliente",
            "descripcion": "La forma común de un cliente entre el CRM y el ERP",
            # Las claves de negocio y no el identificador interno: el ERP no
            # conoce nuestros UUID, y casar por nombre casa mal.
            "claves_negocio": ["nif", "codigo_erp"],
            "campos": [
                {"clave": "nif", "tipo": "texto", "obligatorio": True},
                {"clave": "codigo_erp", "tipo": "texto"},
                {"clave": "razon_social", "tipo": "texto", "obligatorio": True},
                {"clave": "pais", "tipo": "texto"},
                {"clave": "condiciones_pago", "tipo": "texto"},
            ],
        },
    )
    api.crear(
        "/api/v1/modelo-canonico/objetos",
        {
            "clave": "pedido",
            "nombre": "Pedido",
            "claves_negocio": ["referencia"],
            "campos": [
                {"clave": "referencia", "tipo": "texto", "obligatorio": True},
                {"clave": "cliente_nif", "tipo": "texto", "obligatorio": True},
                {"clave": "importe", "tipo": "numero"},
                {"clave": "fecha_entrega", "tipo": "fecha"},
            ],
        },
    )

    api.crear(
        "/api/v1/conectores",
        {
            "clave": "erp_sap",
            "nombre": "SAP S/4HANA",
            "version": "1.2.0",
            "categoria": "erp",
            "protocolo": "rest",
            "descripcion": "Maestro de clientes y pedidos",
            "dominios": ["erp.ficosa.com"],
            "operaciones": [
                {"clave": "leer_cliente", "metodo": "GET", "ruta": "/clientes/{nif}"},
                {"clave": "crear_pedido", "metodo": "POST", "ruta": "/pedidos"},
            ],
            "credenciales": [{"clave": "oauth2", "tipo": "oauth2", "obligatoria": True}],
            # Qué cambia en esta versión. El servicio lo exige y tiene razón:
            # quien actualiza una integración de producción no puede hacerlo
            # a ciegas.
            "notas_version": (
                "Añadida la creación de pedidos y el filtro por NIF al leer clientes."
            ),
        },
    )
    api.crear(
        "/api/v1/conectores",
        {
            "clave": "mdm",
            "nombre": "Maestro de datos corporativo",
            "version": "0.9.0",
            "categoria": "otros",
            "protocolo": "rest",
            "dominios": ["mdm.ficosa.com"],
            "operaciones": [
                {"clave": "publicar_cuenta", "metodo": "POST", "ruta": "/clientes"},
            ],
            "notas_version": "Primera versión: publicación de cuentas al maestro.",
        },
    )

    api.crear(
        "/api/v1/canales-chat",
        {
            "clave": "whatsapp_soporte",
            "url_entrante": "https://www.example.com/hooks/whatsapp",
            "secreto": "CAMBIAR-EN-PRODUCCION",
            "perfil": "whatsapp",
            # Las órdenes son las que el canal sabe ejecutar, no las que a uno
            # le gustaría: una orden inventada se acepta y luego no hace nada.
            "ordenes": ["consultar", "registrar_nota", "cambiar_estado"],
        },
    )
    api.crear(
        "/api/v1/canales-chat",
        {
            "clave": "web_chat",
            "url_entrante": "https://www.example.com/hooks/webchat",
            "secreto": "CAMBIAR-EN-PRODUCCION",
            "perfil": "web",
            "ordenes": ["consultar", "registrar_nota"],
        },
    )

    proveedores = [
        ("transporte_seur", "SEUR", "logistica", 48),
        ("laboratorio_ensayos", "Laboratorio de ensayos externo", "calidad", 120),
        ("taller_reparacion", "Taller de reparación autorizado", "postventa", 72),
    ]
    for clave, nombre, modulo, plazo in proveedores:
        api.crear(
            "/api/v1/proveedores-servicio",
            {
                "clave": clave,
                "nombre": nombre,
                "modulo": modulo,
                "plazo_horas": plazo,
                # El silencio se vigila aparte del plazo: un proveedor que no
                # contesta es un problema antes de incumplir, no después.
                "silencio_horas": max(8, plazo // 4),
                "coste_base": 0,
            },
        )

    conexiones = {c.get("nombre"): c for c in api.listar("/api/v1/integraciones/conexiones", 30)}
    erp = conexiones.get("ERP (SAP S/4HANA)") or {}
    api.crear(
        "/api/v1/federacion/vistas",
        {
            "clave": "facturas_erp",
            **({"conexion_id": str(erp["id"])} if erp.get("id") else {}),
            "nombre": "Facturas del ERP",
            "objeto": "cuenta",
            "operacion": "leer_facturas",
            "clave_registro": "nif",
            # Los datos no se copian: se leen en el ERP cuando alguien abre la
            # ficha. Copiarlos obligaría a mantenerlos sincronizados y a
            # explicar por qué el saldo del CRM no es el del ERP.
            "cache_s": 300,
            "timeout_ms": 4000,
            "campos": [
                {"clave": "numero", "etiqueta": "Factura"},
                {"clave": "fecha", "etiqueta": "Fecha", "tipo": "fecha"},
                {"clave": "importe", "etiqueta": "Importe", "tipo": "numero"},
                {"clave": "estado", "etiqueta": "Estado"},
            ],
        },
    )

    activos = api.listar("/api/v1/activos", 10)
    for i, activo in enumerate(activos[:4]):
        cuerpo: dict[str, Any] = {
            "identificador": f"IOT-{1000 + i}",
            "nombre": f"Telemetría de {activo.get('nombre') or 'activo'}",
            "modelo": "TLM-2",
            "cadencia_min": 15,
        }
        if activo.get("id"):
            cuerpo["activo_id"] = str(activo["id"])
        api.crear("/api/v1/dispositivos", cuerpo)

    # Las tablas del almacén primero: un destino apunta a tablas, y sin ellas
    # se rechaza. Es el orden correcto y además el que explica para qué sirve
    # cada cosa.
    tablas = [
        (
            "oportunidades",
            "sales",
            "oportunidad",
            ["id", "nombre", "importe", "etapa_id", "estado", "fecha_cierre", "owner_id"],
        ),
        ("cuentas", "party", "cuenta", ["id", "nombre", "estado", "sector_codigo", "owner_id"]),
        ("casos", "service", "caso", ["id", "codigo", "prioridad", "estado", "cuenta_id"]),
    ]
    for clave, servicio, objeto, columnas in tablas:
        api.crear(
            "/api/v1/almacen/tablas",
            {
                "clave": clave,
                "nombre": clave.capitalize(),
                "servicio": servicio,
                "objeto": objeto,
                "columnas": [{"clave": c, "tipo": "texto"} for c in columnas],
                "estrategia": "incremental",
                "frecuencia_min": 60,
            },
        )

    api.crear(
        "/api/v1/almacen/destinos",
        {
            "clave": "bi_corporativo",
            "nombre": "BI corporativo",
            "tipo": "s3",
            "tablas": ["oportunidades", "cuentas", "casos"],
            "config": {"bucket": "ficosa-bi", "prefijo": "crm/", "formato": "parquet"},
        },
    )


# ── Lo que faltaba en cada área ───────────────────────────────────────────


def sembrar_resto(api: Api) -> None:
    """Las pantallas que quedaban vacías, cada una con lo suyo.

    Van juntas porque son pocas de cada área y no dan para una parte propia;
    lo que no hacen es quedarse sin sembrar, que es lo que pasaba.
    """
    # ── Servicio: encuestas y repuestos ──────────────────────────────────
    casos = api.listar("/api/v1/casos", 20)
    for i, caso in enumerate(casos[:6]):
        if caso.get("id"):
            api.crear(
                "/api/v1/encuestas",
                {
                    "caso_id": str(caso["id"]),
                    "tipo": "csat" if i % 2 else "nps",
                    "validez_dias": 14,
                },
            )

    repuestos = [
        ("RP-CONECTOR-12", "Conector de 12 vías", "ud", 3.40),
        ("RP-LENTE-ADAS", "Lente para cámara ADAS", "ud", 28.90),
        ("RP-JUNTA-RS", "Junta de estanqueidad RS", "ud", 1.20),
        ("RP-CABLE-2M", "Latiguillo de 2 m", "ud", 6.75),
    ]
    for sku, nombre, unidad, coste in repuestos:
        api.crear(
            "/api/v1/repuestos",
            {"sku": sku, "nombre": nombre, "unidad": unidad, "coste": coste, "activo": True},
        )

    # ── Clientes: lo que se repite y quién decide ────────────────────────
    api.crear(
        "/api/v1/plantillas-actividad",
        {
            "clave": "alta_cliente",
            "nombre": "Alta de cliente nuevo",
            "proceso": "alta_cliente",
            "descripcion": "Lo que hay que hacer las dos primeras semanas",
            "actividades": [
                {"dia": 0, "tipo": "llamada", "asunto": "Llamada de bienvenida"},
                {"dia": 2, "tipo": "tarea", "asunto": "Recoger datos fiscales y de cobro"},
                {"dia": 5, "tipo": "reunion", "asunto": "Presentar al equipo técnico"},
                {"dia": 12, "tipo": "tarea", "asunto": "Confirmar primera entrega"},
            ],
        },
    )
    api.crear(
        "/api/v1/plantillas-actividad",
        {
            "clave": "revision_trimestral",
            "nombre": "Revisión trimestral de cuenta",
            "actividades": [
                {"dia": 0, "tipo": "tarea", "asunto": "Preparar el informe de consumo"},
                {"dia": 3, "tipo": "reunion", "asunto": "Revisión con el cliente"},
                {"dia": 5, "tipo": "tarea", "asunto": "Registrar acuerdos y próximos pasos"},
            ],
        },
    )

    cuentas = api.listar("/api/v1/accounts", 20)
    for i, cuenta in enumerate(cuentas[:3]):
        cuerpo: dict[str, Any] = {
            "asunto": [
                "Revisión mensual de servicio",
                "Comité de calidad",
                "Seguimiento de programa",
            ][i],
            "desde": _f(7 + i),
            "patron": ["mensual", "mensual", "semanal"][i],
            "cada": 1,
            "tipo": "reunion",
            "repeticiones": 12,
        }
        if cuenta.get("id"):
            cuerpo["cuenta_id"] = str(cuenta["id"])
        api.crear("/api/v1/recurrencias", cuerpo)

    # El mapa de personas: quién influye en quién dentro de una cuenta. Es lo
    # que distingue una lista de contactos de saber a quién hay que convencer.
    contactos = [c for c in api.listar("/api/v1/contacts", 30) if c.get("id")]
    relaciones = [
        ("reporta_a", "Jerarquía directa"),
        ("influye_en", "Influye en la decisión"),
        ("aliado", "Nos ha apoyado en compras anteriores"),
        ("detractor", "Ha frenado la compra antes"),
    ]
    for i in range(min(6, len(contactos) - 1)):
        tipo, motivo = relaciones[i % len(relaciones)]
        api.crear(
            "/api/v1/mapa-personas",
            {
                "origen_id": str(contactos[i]["id"]),
                "destino_id": str(contactos[i + 1]["id"]),
                "tipo": tipo,
                "motivo": motivo,
            },
        )

    # ── Marketing: consentimiento y reglas de contenido ──────────────────
    api.crear(
        "/api/v1/reglas-contenido",
        {
            "marca": "Ficosa",
            "pais": "ES",
            "idioma": "es",
            "exige_textos": ["Ficosa International S.A.", "Darse de baja"],
            "prohibe_textos": ["garantizado", "el mejor del mercado"],
            "notas": "Legal revisa cualquier afirmación comparativa antes de enviar.",
        },
    )
    api.crear(
        "/api/v1/reglas-contenido",
        {
            "marca": "Ficosa",
            "pais": "DE",
            "idioma": "de",
            "exige_textos": ["Impressum"],
            "notas": "En Alemania el pie exige Impressum; sin él, el envío no cumple.",
        },
    )
    for i in range(6):
        api.crear(
            "/api/v1/cookies",
            {
                "visitante": f"visitante-{1000 + i}",
                "version_aviso": "2026-01",
                "categorias": {
                    "necesarias": True,
                    "analitica": i % 2 == 0,
                    "publicidad": i % 3 == 0,
                },
                "meses_validez": 12,
            },
        )

    # ── Identidad: qué sigue cada quien ──────────────────────────────────
    for cuenta in cuentas[:5]:
        if cuenta.get("id"):
            api.crear(
                "/api/v1/seguimientos",
                {
                    "objeto_tipo": "cuenta",
                    "objeto_id": str(cuenta["id"]),
                    # El motivo es de una lista corta: es lo que decide cómo se
                    # avisa y si se puede dejar de seguir.
                    "motivo": "propietario",
                },
            )


# ── Lo que existe porque alguien ha trabajado ─────────────────────────────


def sembrar_trabajo(api: Api) -> None:
    """Las pantallas que se llenan usando el sistema, no dándolo de alta.

    Una visita existe porque alguien hizo check-in; una solicitud de fondos,
    porque un partner la pidió; una liquidación, porque se cerró un periodo.
    Escribir esas filas a mano las dejaría sin su historia —sin quién, sin
    cuándo, sin el estado por el que pasaron— y la pantalla enseñaría algo que
    no podría haber pasado.
    """
    # ── Visitas comerciales: check-in y check-out ────────────────────────
    cuentas = [c for c in api.listar("/api/v1/accounts", 20) if c.get("id")]
    for i, cuenta in enumerate(cuentas[:4]):
        visita = api.crear(
            "/api/v1/visitas/check-in",
            {
                "cuenta_id": str(cuenta["id"]),
                "lat": 41.39 + i * 0.01,
                "lon": 2.16 + i * 0.01,
                "notas": [
                    "Revisión de programa",
                    "Presentación de gama",
                    "Auditoría de calidad",
                    "Cierre de oferta",
                ][i],
            },
        )
        # Dos se cierran y dos se quedan abiertas: una lista donde todas están
        # cerradas no enseña el estado que de verdad se mira, que es «¿quién
        # está ahora mismo en un cliente?».
        if visita and visita.get("id") and i % 2 == 0:
            api.crear(
                f"/api/v1/visitas/{visita['id']}/check-out",
                {"resumen": "Acuerdos recogidos y próximos pasos por correo."},
            )

    # ── Fondos de marketing: solicitudes y su decisión ───────────────────
    fondos = [f for f in api.listar("/api/v1/fondos-mdf", 20) if f.get("id")]
    peticiones = [
        ("Stand en la feria IAA", 18000, "Presencia conjunta en el pabellón 4"),
        ("Campaña de recambio en buscadores", 6500, "Tres meses, mercado ibérico"),
        ("Jornada técnica para talleres", 4200, "Cincuenta asistentes previstos"),
    ]
    for i, fondo in enumerate(fondos[:3]):
        titulo, importe, detalle = peticiones[i % len(peticiones)]
        solicitud = api.crear(
            f"/api/v1/fondos-mdf/{fondo['id']}/solicitudes",
            {
                "titulo": titulo,
                "importe": importe,
                "descripcion": detalle,
                "actividad": "feria" if i == 0 else "campana",
                "fecha_actividad": _f(45 + i * 20),
            },
        )
        # Una aprobada, una denegada y una pendiente: las tres columnas que esa
        # pantalla existe para separar.
        if solicitud and solicitud.get("id"):
            if i == 0:
                api.crear(
                    f"/api/v1/solicitudes-mdf/{solicitud['id']}/decidir",
                    {"aprobar": True, "importe_aprobado": importe, "motivo": "Encaja con el plan"},
                )
            elif i == 1:
                api.crear(
                    f"/api/v1/solicitudes-mdf/{solicitud['id']}/decidir",
                    {"aprobar": False, "motivo": "Fuera del trimestre presupuestado"},
                )

    # ── Liquidaciones de comisión del periodo cerrado ────────────────────
    planes = [p for p in api.listar("/api/v1/planes-comision", 20) if p.get("id")]
    usuarios = [u for u in api.listar("/api/v1/usuarios", 20) if u.get("id")]
    for i, plan in enumerate(planes[:2]):
        cuerpo: dict[str, Any] = {
            "plan_id": str(plan["id"]),
            "desde": _f(-120),
            "hasta": _f(-30),
        }
        if i < len(usuarios):
            cuerpo["usuario_id"] = str(usuarios[i]["id"])
        api.crear("/api/v1/liquidaciones", cuerpo)


# ── Chat interno ──────────────────────────────────────────────────────────


def sembrar_chat(api: Api) -> None:
    """Canales de equipo, una conversación de oportunidad y algo dicho.

    Un chat vacío no se entiende: parece que no funciona. Con tres canales y
    una conversación colgada de una oportunidad se ve de un vistazo para qué
    sirve —y sobre todo qué lo diferencia de poner un enlace a otra
    herramienta—.
    """
    canales = [
        ("ventas", "Ventas", "Lo que pasa en el embudo cada día"),
        ("soporte", "Soporte", "Lo que se está cociendo en la cola de casos"),
        ("anuncios", "Anuncios", "Lo que hay que leer aunque no se conteste"),
    ]
    creados: dict[str, str] = {}
    for clave, nombre, proposito in canales:
        hecho = api.crear(
            "/api/v1/chat/conversaciones",
            {"tipo": "canal", "clave": clave, "nombre": nombre, "proposito": proposito},
        )
        if hecho and hecho.get("id"):
            creados[clave] = str(hecho["id"])

    # Todo el mundo en los canales: un canal con una sola persona dentro no
    # enseña nada de lo que hace un chat.
    usuarios = [str(u["id"]) for u in api.listar("/api/v1/usuarios", 30) if u.get("id")]
    for conversacion_id in creados.values():
        for usuario_id in usuarios[:6]:
            api._llamar(
                "POST",
                f"/api/v1/chat/conversaciones/{conversacion_id}/miembros",
                {"usuario_id": usuario_id},
            )

    conversacion = [
        ("ventas", "Metalúrgica del Norte pide un 8 % sobre la tarifa OEM en el programa 2027."),
        ("ventas", "Con ese volumen entra. Lo paso por aprobación de descuento."),
        ("soporte", "Dos casos de la misma planta con el sensor RS-220 bajo lluvia intensa."),
        ("soporte", "Los agrupo en un problema: si es la misma causa se arregla una vez."),
        ("anuncios", "El martes cambia la tarifa de recambio. Está ya en Listas de precio."),
    ]
    for clave, texto in conversacion:
        if clave in creados:
            api.crear(f"/api/v1/chat/conversaciones/{creados[clave]}/mensajes", {"cuerpo": texto})

    # Y la que cuelga de una oportunidad, que es lo que distingue este chat.
    oportunidades = api.listar("/api/v1/opportunities", 5)
    if oportunidades and oportunidades[0].get("id"):
        estado, cuerpo = api._llamar(
            "GET", f"/api/v1/chat/conversaciones/de/oportunidad/{oportunidades[0]['id']}"
        )
        if estado == 200 and isinstance(cuerpo, dict) and cuerpo.get("id"):
            api.crear(
                f"/api/v1/chat/conversaciones/{cuerpo['id']}/mensajes",
                {
                    "cuerpo": (
                        "El cliente pide entrega en dos fases. Lo hablo con planta y "
                        "lo dejo aquí para que quede con la oportunidad."
                    )
                },
            )


# ── Quién lleva cada cosa ─────────────────────────────────────────────────


def sembrar_duenos(api: Api) -> None:
    """Reparte cuentas, oportunidades, leads y casos entre el equipo.

    Sin dueño no funciona **media aplicación**, y no de forma visible: «mis
    oportunidades» sale vacía, la visibilidad por responsable no recorta nada,
    la cuota no tiene contra qué medirse, la comisión no sabe de quién es la
    venta y el tablero enseña tarjetas sin cara. Nada de eso falla: sale vacío,
    que es peor, porque parece que la función no está hecha.

    El reparto es **estable**: la misma cuenta cae siempre en el mismo
    comercial, porque se reparte por la posición en una lista ordenada y no al
    azar. Volver a sembrar y que cambien todos los dueños haría imposible
    comprobar nada dos veces.
    """
    usuarios = sorted(
        (u for u in api.listar("/api/v1/usuarios", 50) if u.get("id")),
        key=lambda u: str(u.get("email", "")),
    )
    if not usuarios:
        return

    # A cada cosa le toca quien la lleva de verdad: las cuentas y el embudo a
    # quien vende, los casos a quien atiende. Repartirlo todo entre todos daría
    # colas de soporte a un comercial, y eso no lo mira nadie.
    def de(prefijos: tuple[str, ...]) -> list[str]:
        elegidos = [str(u["id"]) for u in usuarios if str(u.get("email", "")).startswith(prefijos)]
        return elegidos or [str(u["id"]) for u in usuarios]

    comerciales = de(("comercial", "ventas", "direccion"))
    soporte = de(("soporte",))

    # `estado=` vacío a propósito: el listado de oportunidades filtra por
    # «abierta» si no se dice nada, y repartir solo lo abierto deja sin dueño lo
    # ganado y lo perdido —que es justo el histórico con el que se calcula la
    # consecución de cada comercial—.
    repartos = [
        ("/api/v1/accounts", "?estado=", "owner_id", comerciales),
        ("/api/v1/opportunities", "?estado=", "owner_id", comerciales),
        ("/api/v1/leads", "?estado=", "owner_id", comerciales),
        ("/api/v1/casos", "?estado=", "owner_id", soporte),
    ]
    for ruta, filtro, campo, entre in repartos:
        filas = api.listar(f"{ruta}{filtro}", 200)
        for i, fila in enumerate(filas):
            if not fila.get("id") or fila.get(campo):
                continue
            # Una oportunidad cerrada está **bloqueada a propósito**: sus
            # números ya están en un informe que alguien ha mirado, y cambiarle
            # el dueño cambiaría la consecución de dos comerciales a la vez.
            # Reabrirla para repartirla sería saltarse justo la regla que el
            # producto defiende, así que se deja como está.
            if fila.get("bloqueada"):
                continue
            estado, cuerpo = api._llamar(
                "PATCH", f"{ruta}/{fila['id']}", {campo: entre[i % len(entre)]}
            )
            if estado not in (200, 204):
                api.fallos.append(f"PATCH {ruta}/{fila['id']} → {estado} {_motivo(cuerpo)}")
                break


def sembrar_pantallas_vacias(api: Api) -> None:
    """Las cuatro que quedaban sin una sola fila.

    Una pantalla vacía no se lee como «aún no hay nada»: se lee como que la
    función no está hecha. Estas cuatro son catálogos que se dan de alta —no
    vistas derivadas, que sí pueden estar vacías con razón— y no las llenaba
    nadie.
    """
    # Mapa de influencia: quién manda sobre quién dentro del cliente. Se hace
    # entre contactos REALES y en pares, porque una relación necesita dos.
    contactos = [c["id"] for c in api.listar("/api/v1/contacts", 12) if c.get("id")]
    for i in range(0, min(len(contactos) - 1, 6), 2):
        api.crear(
            "/api/v1/mapa-personas",
            {
                "origen_id": contactos[i],
                "destino_id": contactos[i + 1],
                "tipo": "influye_en",
                "motivo": "Lo dijo en la última visita: firma él pero decide el otro.",
            },
        )

    # Diccionario de métricas: lo que significa cada número antes de enseñarlo
    # en un cuadro de mando.
    for clave, nombre, objeto, agregacion, campo, unidad in (
        ("ingresos_ganados", "Ingresos ganados", "oportunidad", "suma", "importe", "EUR"),
        ("oportunidades_abiertas", "Oportunidades abiertas", "oportunidad", "cuenta", "id", ""),
        ("casos_abiertos", "Casos abiertos", "caso", "cuenta", "id", ""),
        ("ticket_medio", "Ticket medio", "oportunidad", "media", "importe", "EUR"),
    ):
        api.crear(
            "/api/v1/metricas",
            {
                "clave": clave,
                "nombre": nombre,
                "objeto": objeto,
                "agregacion": agregacion,
                "campo": campo,
                "unidad": unidad,
                "definicion": f"{nombre}, calculado sobre {objeto}.",
            },
        )

    # Liquidaciones de comisión. El plan hay que **activarlo** antes: uno en
    # borrador no liquida —se simula—, y esa negativa llega como un 409 que el
    # sembrado contaba como «ya existía», así que la pantalla se quedaba vacía
    # sin que nada lo dijera.
    planes = [p for p in api.listar("/api/v1/planes-comision", 5) if p.get("id")]
    activo = next((p for p in planes if p.get("estado") == "activo"), None)
    if activo is None and planes:
        # Y antes de activarlo, una regla: el servicio se niega a activar un
        # plan sin ninguna —«liquidaría cero a todo el mundo»— y tiene razón,
        # pero el sembrado creaba los planes vacíos, así que ninguno llegaba a
        # activo y la pantalla de liquidaciones no podía tener nada nunca.
        api.crear(
            f"/api/v1/planes-comision/{planes[0]['id']}/reglas",
            {
                "tipo": "porcentaje",
                "nombre": "Comisión base sobre margen",
                "porcentaje": 3,
                "orden": 10,
            },
        )
        api.crear(f"/api/v1/planes-comision/{planes[0]['id']}/activar", {})
        activo = planes[0]
    if activo:
        api.crear(
            "/api/v1/liquidaciones",
            {"plan_id": activo["id"], "desde": _f(-60), "hasta": _f(-30)},
        )

    # Comunidad: cuelga de un acceso al portal, así que se busca uno.
    accesos = [a for a in api.listar("/api/v1/portal/accesos", 5) if a.get("id")]
    if accesos:
        for titulo, cuerpo in (
            (
                "¿Cada cuánto hay que calibrar el equipo?",
                "En el manual pone una vez al año, pero el técnico nos dijo que "
                "con este uso conviene cada seis meses. ¿Cuál vale?",
            ),
            (
                "Recambios equivalentes al filtro F-220",
                "El F-220 tarda tres semanas. ¿Hay alguno homologado que sirva " "mientras llega?",
            ),
        ):
            hilo = api.crear(
                "/api/v1/comunidad/hilos",
                {
                    "acceso_id": accesos[0]["id"],
                    "titulo": titulo,
                    "cuerpo": cuerpo,
                    "categoria": "producto",
                },
            )
            # Y se aprueba: un hilo nace **en moderación** y el listado sirve
            # solo lo publicado —con razón: un hilo en moderación que se cuela
            # en la vista pública es justo lo que la moderación viene a
            # impedir—, así que sin este paso la comunidad se ve vacía.
            if hilo and hilo.get("id"):
                api.crear(
                    f"/api/v1/comunidad/hilos/{hilo['id']}/moderar",
                    {"aprobar": True, "motivo": "Pregunta legítima de producto"},
                )


def sembrar_calidad(api: Api) -> None:
    """Llena la cola de excepciones de calidad pasando el barrido.

    Va **después** de los dueños a propósito: media cola son «sin propietario»,
    y pasándolo antes se abrirían cientos de excepciones que el propio sembrado
    resuelve un paso después. Quedarían abiertas —nadie las cierra— y la
    primera impresión de la pantalla sería una cola de ruido, que es
    exactamente como se consigue que nadie vuelva a mirarla.
    """
    api.crear("/api/v1/calidad-dato/cola/barrido?limite=2000", {})
    # Y las parejas que podrían ser la misma ficha. Se deja **sin decidir** a
    # propósito: la cola llena es la pantalla, y decidirla desde el sembrado
    # dejaría la pantalla vacía enseñando algo que ya está resuelto.
    api.crear("/api/v1/data-quality/accounts/duplicates/barrido?limite=2000", {})


def sembrar_rastro(api: Api) -> None:
    """Las pantallas que no se llenan creando, sino usando.

    La papelera, los reenvíos, el archivo de eventos: son consecuencia de
    trabajar, no cosas que se den de alta. Vacías no se entienden —«papelera»
    sin nada dentro no dice si guarda borrados o si no funciona— así que aquí
    se provoca la consecuencia de verdad, borrando algo que se acaba de crear
    para eso, en vez de escribir una fila a mano en su tabla.
    """
    correos = {f"papelera{i}@example.com" for i in range(2)}
    for i, nombre in enumerate(("Contacto duplicado", "Contacto dado de baja")):
        api.crear(
            "/api/v1/contacts",
            {
                "nombre": nombre,
                "apellidos": "(de prueba)",
                "email": f"papelera{i}@example.com",
            },
        )
    # Se buscan por correo en vez de quedarse con lo que devolvió el alta: al
    # segundo paso ya existen, el alta contesta «ya existe» sin identificador, y
    # entonces no se borraba nada y la papelera seguía vacía.
    for contacto in api.listar("/api/v1/contacts", 200):
        if contacto.get("email") in correos and contacto.get("id"):
            estado, cuerpo = api._llamar("DELETE", f"/api/v1/contacts/{contacto['id']}")
            if estado not in (200, 202, 204, 409):
                api.fallos.append(
                    f"DELETE /api/v1/contacts/{contacto['id']} → {estado} {_motivo(cuerpo)}"
                )

    # Duplicados de verdad, que es lo que esa pantalla tiene que enseñar. Con
    # una sola cuenta por nombre, la búsqueda se encuentra a sí misma y el
    # resultado —«similitud 1.0»— no explica para qué sirve la pantalla. Aquí
    # se crean parejas como las que aparecen solas en cualquier CRM: la misma
    # empresa dada de alta dos veces con el nombre escrito de otra manera.
    parejas = [
        ("Metalúrgica del Norte S.L.U.", "Metalurgica del Norte SLU"),
        ("Talleres Ibéricos, S.A.", "TALLERES IBERICOS SA"),
        ("Componentes Delta", "Componentes Delta S.L."),
    ]
    for original, variante in parejas:
        for nombre in (original, variante):
            api.crear(
                "/api/v1/accounts",
                {"nombre": nombre, "roles": ["cliente"], "estado": "activa"},
            )


def sembrar_analitica(api: Api) -> None:
    """Preguntas ya hechas, para que el historial de consultas no salga vacío.

    **Se mira antes de escribir**, que es la excepción en este script. El resto
    de partes se apoyan en que la API conteste 409 al duplicado, y por eso pasar
    el sembrador dos veces es inofensivo. Aquí no puede haber 409: el registro de
    consultas es un DIARIO, y la misma pregunta hecha dos veces son dos filas de
    verdad. Negarle el duplicado sería romper lo que la tabla significa.

    Así que la idempotencia la pone el sembrador. Sin esto, cada pase añadía seis
    filas: en esta instalación había 84 para 7 preguntas distintas —un tenant con
    cada una doce veces— y la pantalla de consultas parecía rota.
    """
    if api.listar("/api/v1/analitica/consultas", limite=1):
        api.cuenta["saltados"] += 1
        return

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


def sembrar_lo_que_sale_vacio(api: Api) -> None:
    """Las últimas pantallas que se abrían sin una sola fila.

    Medido el 27-10-2026 sobre una empresa sembrada entera: de 452 tablas, 335
    seguían vacías. La mayoría **con razón** —excepciones de calidad, bloqueos
    legales, fusiones, migraciones de aislamiento: cosas que sólo existen
    cuando pasa algo—, y una tabla vacía porque no ha pasado nada no es un
    hueco. Las que sí lo eran salían a 25: las que **alguna pantalla lista**, y
    por tanto alguien abre y ve en blanco.

    Aquí se llenan las que tienen un alta de verdad. Las que no la tienen se
    dicen abajo, con el motivo, en vez de inventarlas: un informe que da por
    cubierto lo que no lo está es peor que no tenerlo.
    """
    # ── Comentarios sobre registros reales ────────────────────────────────
    #
    # Es la conversación interna sobre un cliente, una venta o un caso, y es de
    # lo primero que se mira al abrir una ficha: vacía siempre, parece que el
    # panel no funciona.
    comentarios = (
        "Hablado con ellos por teléfono: confirman presupuesto para el primer trimestre.",
        "Ojo con los plazos de este cliente: la última vez se retrasó la entrega dos semanas.",
        "Lo lleva ahora otra persona por su parte. Pedir contacto actualizado.",
    )
    for ruta, tipo in (
        ("/api/v1/accounts", "cuenta"),
        ("/api/v1/opportunities", "oportunidad"),
        ("/api/v1/casos", "caso"),
    ):
        filas = api.listar(f"{ruta}?estado=", 3)
        for i, fila in enumerate(filas):
            if not fila.get("id"):
                continue
            api.crear(
                f"/api/v1/comentarios/{tipo}/{fila['id']}",
                {"cuerpo": comentarios[i % len(comentarios)], "interno": i % 2 == 0},
            )

    # ── Adjuntos sobre registros reales ──────────────────────────────────
    #
    # El panel de adjuntos es de los primeros que se abren en una ficha, y
    # salía vacío en todas. Se suben ficheros de texto pequeños y con nombre
    # que diga qué son: un «documento.pdf» de relleno no enseña nada.
    adjuntos = (
        ("acta-reunion.txt", "Acta de la reunión de arranque", b"Asistentes, acuerdos y plazos."),
        ("pliego-tecnico.txt", "Pliego técnico recibido", b"Requisitos y condiciones del cliente."),
        ("foto-instalacion.txt", "Nota de la visita a planta", b"Medidas tomadas en la visita."),
    )
    for ruta, tipo in (
        ("/api/v1/accounts", "cuenta"),
        ("/api/v1/opportunities", "oportunidad"),
        ("/api/v1/casos", "caso"),
    ):
        for i, fila in enumerate(api.listar(f"{ruta}?estado=", 2)):
            if not fila.get("id"):
                continue
            nombre, descripcion, contenido = adjuntos[i % len(adjuntos)]
            api.subir(
                f"/api/v1/adjuntos/{tipo}",
                nombre,
                contenido,
                {"objeto_id": str(fila["id"]), "descripcion": descripcion},
            )

    # ── Informes y cuadros de mando ───────────────────────────────────────
    # Las agrupaciones son **objetos** con su campo —y su periodo si es una
    # fecha—, no nombres de columna: lo dice el propio contrato en su ejemplo.
    # Con cadenas, el alta responde 422 «los datos enviados no son válidos» y
    # no dice cuál, que es por lo que costó encontrarlo.
    for clave, nombre, objeto, columnas, agrupaciones in (
        (
            "cartera-por-sector",
            "Cartera por sector",
            "cuenta",
            ["nombre", "tier"],
            [{"campo": "sector_codigo"}],
        ),
        (
            "ventas-por-etapa",
            "Ventas por etapa",
            "oportunidad",
            ["nombre", "importe"],
            [{"campo": "estado"}],
        ),
        (
            "casos-por-prioridad",
            "Casos por prioridad",
            "caso",
            ["asunto", "estado"],
            [{"campo": "prioridad"}],
        ),
    ):
        api.crear(
            "/api/v1/informes",
            {
                "clave": clave,
                "nombre": nombre,
                "objeto": objeto,
                "descripcion": f"{nombre}, con el recorte que tengas puesto.",
                "columnas": columnas,
                "agrupaciones": agrupaciones,
            },
        )

    api.crear(
        "/api/v1/cuadros-mando",
        {
            "clave": "direccion",
            "nombre": "Cuadro de dirección",
            "descripcion": "Lo que se mira en el comité: cartera, embudo y postventa.",
            # Cada componente apunta al informe del que saca los datos —sin
            # él no hay de dónde— y un «kpi» necesita además su métrica. Lo
            # valida al guardarlo, no al pintarlo: un cuadro mal montado que
            # sólo falla al abrirse se descubre delante de alguien.
            "componentes": [
                {
                    "tipo": "kpi",
                    "titulo": "Ingresos ganados",
                    "informe": "ventas-por-etapa",
                    "metrica": "ingresos_ganados",
                },
                {
                    "tipo": "grafico",
                    "titulo": "Casos por prioridad",
                    "informe": "casos-por-prioridad",
                    "dimension": "prioridad",
                    "metrica": "casos_abiertos",
                    "forma": "barras",
                },
            ],
        },
    )

    # ── Plantillas de documento y canales de entrada ──────────────────────
    api.crear(
        "/api/v1/plantillas-documento",
        {
            "clave": "oferta-estandar",
            "nombre": "Oferta estándar",
            "tipo": "propuesta",
            "cuerpo": (
                "Estimado/a {{contacto}}:\n\nAdjuntamos nuestra oferta para "
                "{{oportunidad}}, por importe de {{importe}}.\n\nVigencia: 30 días."
            ),
        },
    )
    api.crear(
        "/api/v1/canales-entrada",
        {
            "clave": "buzon-comercial",
            "canal": "correo",
            "nombre": "Buzón comercial",
            "destino": "lead",
        },
    )

    # ── Activos de marketing y un recorrido ───────────────────────────────
    api.crear(
        "/api/v1/activos-marketing",
        {
            "clave": "foto-planta-2026",
            "nombre": "Fotografía de planta 2026",
            "referencia": "https://activos.example.com/planta-2026.jpg",
            "tipo": "imagen",
            "usos_permitidos": ["web", "correo"],
            "licencia": "propia",
        },
    )
    api.crear(
        "/api/v1/recorridos",
        {
            "clave": "bienvenida-cliente",
            "nombre": "Bienvenida al cliente nuevo",
            "descripcion": "Tres toques en tres semanas tras la primera compra.",
            "inicio": "saludo",
            # El lienzo ES la definición: un diccionario de nodos con su tipo
            # y a dónde van, no una lista.
            "nodos": {
                "saludo": {
                    "tipo": "accion",
                    "accion": "email",
                    "plantilla": "bienvenida",
                    "siguiente": "esperar",
                },
                "esperar": {"tipo": "espera", "dias": 7, "siguiente": "encuesta"},
                "encuesta": {"tipo": "accion", "accion": "email", "siguiente": "fin"},
                "fin": {"tipo": "fin"},
            },
        },
    )

    # ── Un agente de IA y los subprocesadores ─────────────────────────────
    api.crear(
        "/api/v1/ia/agentes-autonomos",
        {
            "clave": "primera-respuesta",
            "tipo": "respuesta_soporte",
            "descripcion": "Propone la primera respuesta de un caso, para que la revise alguien.",
            "permisos": ["account:read", "activity:read"],
            "max_acciones": 20,
        },
    )
    # `trata` no es opcional, y el propio servidor lo explica: «un
    # subprocesador sin eso es un nombre en una lista, y no contesta a lo que
    # pregunta un cliente».
    for clave, nombre, finalidad, trata in (
        (
            "correo-transaccional",
            "Proveedor de correo",
            "Envío de avisos y notificaciones",
            ["transaccional"],
        ),
        (
            "almacen-objetos",
            "Almacenamiento de adjuntos",
            "Guardar los ficheros adjuntos",
            ["adjuntos", "copias"],
        ),
    ):
        api.crear(
            "/api/v1/residencia/subprocesadores",
            {
                "tenant_id": api.tenant_id,
                "clave": clave,
                "nombre": nombre,
                "finalidad": finalidad,
                "trata": trata,
                "region": "ue",
                "garantia": "clausulas_tipo",
            },
        )

    # ── Encargos a proveedor, con su rastro ───────────────────────────────
    #
    # La pantalla de encargos se abría vacía en un sistema con mil casos. Se
    # atan a una cuenta real: un encargo sin cliente no contesta «¿de quién es
    # este envío?», que es la pregunta por la que se mira.
    cuentas = api.listar("/api/v1/accounts?estado=", 3)
    # Los proveedores que de verdad tiene este tenant, no dos nombres
    # inventados: el alta los comprueba —«no hay ningún proveedor
    # «mensajeria» configurado»— y hace bien, porque un encargo a un
    # proveedor que no existe no lo recoge nadie.
    proveedores = [
        p["clave"] for p in api.listar("/api/v1/proveedores-servicio", 10) if p.get("clave")
    ]
    for i, cuenta in enumerate(cuentas):
        if not cuenta.get("id") or not proveedores:
            continue
        api.crear(
            "/api/v1/encargos",
            {
                "proveedor": proveedores[i % len(proveedores)],
                "referencia_externa": f"EXT-{1000 + i}",
                "objeto_origen": "cuenta",
                "objeto_origen_id": str(cuenta["id"]),
                "cuenta_id": str(cuenta["id"]),
                "datos": {"concepto": "Recogida de material para revisión"},
            },
        )

    # ── Plantillas de comunicación del tenant ─────────────────────────────
    for clave, nombre, asunto, cuerpo in (
        (
            "aviso-vencimiento",
            "Aviso de vencimiento",
            "Tu contrato vence el {{fecha}}",
            "Hola {{nombre}}:\n\nTe recordamos que tu contrato vence el {{fecha}}.",
        ),
        (
            "gracias-por-el-pedido",
            "Gracias por el pedido",
            "Hemos recibido tu pedido {{numero}}",
            "Hola {{nombre}}:\n\nTu pedido {{numero}} está confirmado.",
        ),
    ):
        api.crear(
            "/api/v1/plantillas",
            {
                "clave": clave,
                "nombre": nombre,
                "tipo": "correo",
                "idioma": "es",
                "asunto": asunto,
                "cuerpo": cuerpo,
            },
        )

    # ── Créditos de servicio del trimestre ────────────────────────────────
    #
    # No se dan de alta: se **calculan** a partir de los incumplimientos de
    # SLA que ya hay. Pedirlo es lo que los crea, y sin pedirlo la pantalla
    # sale vacía aunque haya casos fuera de plazo — que es justo lo contrario
    # de lo que pasa.
    hoy = date.today()
    api.crear(
        "/api/v1/creditos-servicio/calcular",
        {
            "periodo": f"{hoy.year}-T{(hoy.month - 1) // 3 + 1}",
            "desde": str(hoy.replace(day=1) - timedelta(days=90)),
            "hasta": str(hoy),
        },
    )

    # ── Lo que NO se siembra, y por qué ───────────────────────────────────
    #
    # Se dice en vez de callarlo: un listado de pantallas pendientes que
    # esconde las que no se pueden llenar deja a quien lo lee creyendo que ya
    # está todo, y la que falta la descubre el cliente.
    #
    #   · **notificaciones, conversaciones, mensajes y anomalías** — no se dan
    #     de alta: los produce el sistema cuando pasa algo. Sembrarlos a mano sería escribir en la tabla lo que el producto
    #     tendría que haber escrito, y entonces la demostración enseña un
    #     resultado sin el camino que lo produce.
    #   · **passkeys y dispositivos de confianza** — son de una persona y de su
    #     navegador: no hay forma de crearlos desde fuera, y es la protección
    #     funcionando.
    #   · **créditos de servicio** — se calculan, y se calculan aquí: salen
    #     cero porque ningún contrato de esta empresa los pacta. Cero es la
    #     respuesta correcta, no un hueco.
    #   · **claves de API y proveedores de identidad** — el alta exige volver a
    #     verificar la identidad, y SAML está apagado en esta instalación. Las
    #     dos salen ya en el informe de «rechazadas por diseño».


def sembrar_las_que_siguen_vacias(api: Api) -> None:
    """Las pestañas que seguían abriéndose sin una sola fila (27-10-2026).

    Medido cruzando lo que cada pestaña lista con lo que hay en la base para
    este tenant: **de 130 pestañas con tabla identificada, 36 salían vacías**.
    No es lo mismo que una tabla vacía: una excepción de calidad o una fusión
    vacías están bien —son cosas que sólo existen cuando pasa algo—. Éstas no:
    son configuración o trabajo corriente que cualquier instalación tiene.

    Cada alta va con **datos que se sostienen**: el consentimiento de un buzón
    apunta a un usuario de verdad, el plan de cuenta a una cuenta de verdad, la
    encuesta a un caso resuelto. Inventar identificadores daría filas que la
    ficha no puede abrir, que es peor que la pestaña vacía.
    """
    sin_sembrar: list[str] = []
    usuarios = api.listar("/api/v1/usuarios", 5)
    cuentas = api.listar("/api/v1/accounts", 5)
    contactos = api.listar("/api/v1/contacts", 5)
    oportunidades = api.listar("/api/v1/opportunities", 5)
    casos = api.listar("/api/v1/casos", 5)

    # ── Correo y calendario de cada uno ───────────────────────────────────
    for i, usuario in enumerate(usuarios[:3]):
        api.crear(
            "/api/v1/buzones",
            {
                "usuario_id": usuario["id"],
                "perfil": "generico",
                "direccion": usuario.get("email") or f"persona{i}@ejemplo.com",
                "ambito": "correo" if i % 2 == 0 else "calendario",
                "entrante": True,
                "saliente": i % 2 == 0,
            },
        )
    api.crear(
        "/api/v1/suites/perfiles",
        {
            "nombre": "Microsoft 365 del cliente",
            "sistema": "m365",
            # Como configuración, no como código: endpoints, campos y límites.
            "config": {
                "base_url": "https://graph.microsoft.com/v1.0",
                "token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
                "incremento": "delta",
                "alcances": {
                    "base": "offline_access",
                    "correo.leer": "Mail.Read",
                    "calendario.leer": "Calendars.Read",
                    "calendario.escribir": "Calendars.ReadWrite",
                    "contactos.leer": "Contacts.Read",
                },
                "recursos": {
                    "correo": {
                        "endpoint": "/me/messages",
                        "incremento": "token_delta",
                        "sentidos": ["leer"],
                        "campos": {
                            "asunto": "subject",
                            "cuerpo": "body.content",
                            "de": "from.emailAddress.address",
                            "fecha": "receivedDateTime",
                        },
                    },
                    "calendario": {
                        "endpoint": "/me/events",
                        "incremento": "token_delta",
                        "sentidos": ["leer", "escribir"],
                        "campos": {
                            "asunto": "subject",
                            "inicio": "start.dateTime",
                            "fin": "end.dateTime",
                        },
                    },
                    "contactos": {
                        "endpoint": "/me/contacts",
                        "incremento": "token_delta",
                        "sentidos": ["leer"],
                        "campos": {
                            "nombre": "displayName",
                            "email": "emailAddresses[0].address",
                            "telefono": "mobilePhone",
                        },
                    },
                },
            },
        },
    )

    # ── Convivencia con el CRM heredado ───────────────────────────────────
    #
    # Quién manda sobre cada objeto mientras los dos sistemas conviven. Sin
    # reglas, la migración es «a ver quién escribe último».
    for objeto, dueno in (("cuenta", "nuevo"), ("contacto", "heredado"), ("lead", "ambos")):
        api.crear(
            "/api/v1/convivencia",
            {
                "objeto": objeto,
                "dueno": dueno,
                "nombre": f"Quién manda en {objeto}",
                "prioridad": 10,
                "manda_en_empate": "nuevo" if dueno == "ambos" else None,
                "replicar_al_heredado": dueno == "nuevo",
            },
        )

    # ── Un agente de IA expuesto por MCP ──────────────────────────────────
    api.crear(
        "/api/v1/agentes-ia/exposiciones",
        {
            "clave": "soporte-lectura",
            "nombre": "Soporte, sólo lectura",
            "descripcion": "Consultar casos y artículos. No escribe nada.",
            "cuota_hora": 120,
        },
    )

    # ── Repuestos y su reposición ─────────────────────────────────────────
    for sku, nombre, unidad, coste in (
        ("REP-FILT", "Filtro de repuesto", "unidad", 18.5),
        ("REP-JUNTA", "Junta de estanqueidad", "unidad", 4.2),
        ("REP-ACEITE", "Aceite hidráulico", "litro", 9.9),
    ):
        api.crear(
            "/api/v1/repuestos",
            {"sku": sku, "nombre": nombre, "unidad": unidad, "coste": coste, "activo": True},
        )

    # ── La encuesta de un caso cerrado ────────────────────────────────────
    #
    # A casos de verdad: una encuesta sin caso no se puede abrir desde ninguna
    # parte, y el resumen de satisfacción saldría calculado sobre nada.
    for caso in casos[:3]:
        api.crear("/api/v1/encuestas", {"caso_id": caso["id"], "tipo": "csat", "validez_dias": 14})

    # ── Plan de cuenta y plan conjunto ────────────────────────────────────
    for cuenta in cuentas[:2]:
        api.crear(
            "/api/v1/planes-cuenta",
            {
                "cuenta_id": cuenta["id"],
                "periodo": "2026",
                # Con fecha y con responsable los dos: el producto rechaza lo
                # demás, y tiene razón — «un plan de frases se revisa una vez:
                # en la reunión en la que se escribió».
                "objetivos": [
                    {
                        "titulo": "Entrar en la planta de Zaragoza",
                        "fecha_objetivo": "2026-06-30",
                        "responsable_id": (usuarios[0]["id"] if usuarios else None),
                    },
                    {
                        "titulo": "Renovar el contrato de mantenimiento",
                        "fecha_objetivo": "2026-09-30",
                        "responsable_id": (usuarios[0]["id"] if usuarios else None),
                    },
                ],
                "riesgos": [{"titulo": "El responsable de compras cambia de puesto"}],
                "objetivo_importe": 250000,
            },
        )
    for oportunidad in oportunidades[:2]:
        api.crear(
            "/api/v1/planes-conjuntos",
            {
                "oportunidad_id": oportunidad["id"],
                "pasos": [
                    {
                        "titulo": "Visita técnica a la planta",
                        "de_quien": "nuestro",
                        "fecha": "2026-03-15",
                        "responsable": (usuarios[0]["id"] if usuarios else "Comercial"),
                    },
                    {
                        "titulo": "Validación del pliego",
                        "de_quien": "del_cliente",
                        "fecha": "2026-04-10",
                        "responsable": "Compras del cliente",
                    },
                    {
                        "titulo": "Prueba de concepto en su línea",
                        "de_quien": "conjunto",
                        "fecha": "2026-05-20",
                        "responsable": "Ingeniería de ambas partes",
                    },
                ],
            },
        )

    # ── Alguien que ha cambiado de empresa ────────────────────────────────
    for contacto in contactos[:2]:
        api.crear(
            "/api/v1/cambios-de-empresa",
            {
                "contacto_id": contacto["id"],
                "indicio": "correo_rebotado",
                "detalle": "Su dirección rebota y aparece en otra empresa en LinkedIn.",
            },
        )

    # ── Un proveedor de identidad declarado ───────────────────────────────
    api.crear(
        "/api/v1/proveedores-identidad",
        {
            "nombre": "Directorio corporativo (OIDC)",
            "tipo": "oidc",
            "dominio_email": "contecrm.dev",
            "config": {"issuer": "https://login.example.com/", "client_id": "contecrm"},
            "jit_provisioning": True,
            "activo": False,
        },
    )

    # ── Cómo está aislado este cliente, y dónde se tratan sus datos ───────
    #
    # El panel de aislamiento vacío se lee como «no está aislado». Lo que pasa
    # es que nadie lo ha declarado, que es otra cosa — y es justo lo que la
    # pantalla existe para que deje de pasar.
    yo = api.tenant_id
    if yo:
        api.crear(
            "/api/v1/aislamiento",
            {
                "tenant_id": yo,
                "modalidad": "esquema",
                "tier": "estandar",
                "instancia": "crm-eu-1",
                "base": "contecrm",
                "esquema": "por_servicio",
                "notas": "Un esquema por servicio, con RLS por tenant dentro de cada uno.",
            },
        )
        # Lo que trata cada uno, con los tipos que admite el producto: no es
        # una etiqueta libre, y por eso el proveedor de modelos declara «ia» y
        # el de ficheros «adjuntos» — es lo que luego permite contestar «¿quién
        # ve los adjuntos de mis clientes?» sin leerse contratos.
        for clave, nombre, region, finalidad, trata in (
            (
                "correo",
                "Proveedor de correo transaccional",
                "ue",
                "Envío de avisos y notificaciones",
                ["transaccional"],
            ),
            (
                "almacenamiento",
                "Almacenamiento de adjuntos",
                "ue",
                "Guardar ficheros de los registros",
                ["adjuntos", "copias"],
            ),
            (
                "ia",
                "Proveedor de modelos de lenguaje",
                "ue",
                "Resúmenes y borradores asistidos",
                ["ia"],
            ),
        ):
            api.crear(
                "/api/v1/residencia/subprocesadores",
                {
                    "tenant_id": yo,
                    "clave": clave,
                    "nombre": nombre,
                    "region": region,
                    "finalidad": finalidad,
                    "trata": trata,
                    # Las que reconoce el RGPD, no las siglas del contrato:
                    # dentro de la UE no hace falta transferencia, así que lo
                    # que aplica es la decisión de adecuación.
                    "garantia": "decision_adecuacion",
                },
            )

    # ── Un cuadro incrustado ──────────────────────────────────────────────
    cuadros = api.listar("/api/v1/cuadros-mando", 1)
    if cuadros:
        api.crear(
            "/api/v1/cuadros-mando/embebidos",
            {
                "cuadro_id": cuadros[0]["id"],
                "dominios": ["intranet.ejemplo.com"],
                "nombre": "Cuadro para la intranet",
                "minutos_validez": 60,
            },
        )

    # ── Una saga en marcha ────────────────────────────────────────────────
    #
    # Lo que cruza servicios y hay que poder deshacer. Sin ninguna, la pantalla
    # no enseña qué pasa cuando un paso falla a mitad, que es para lo que está.
    api.crear(
        "/api/v1/sagas",
        {
            "clave": "alta-de-cliente",
            "objeto": "cuenta",
            "pasos": [
                {"nombre": "crear_cuenta", "servicio": "party"},
                {"nombre": "abrir_oportunidad", "servicio": "sales"},
                {"nombre": "dar_de_alta_en_soporte", "servicio": "service"},
            ],
        },
    )

    # ── Dónde vive cada clase de dato, y qué sale de la región ────────────
    if yo:
        for tipo_dato, region, proveedor in (
            ("transaccional", "ue", "Infraestructura propia (Fráncfort)"),
            ("copias", "ue", "Almacenamiento cifrado (Irlanda)"),
            ("ia", "ue", "Proveedor de modelos con opt-out de entrenamiento"),
        ):
            api.crear(
                "/api/v1/residencia",
                {
                    "tenant_id": yo,
                    "tipo_dato": tipo_dato,
                    "region": region,
                    "proveedor": proveedor,
                },
            )
        # Una transferencia declarada: lo que sale y por qué. Sin ninguna, la
        # pantalla no distingue «no sale nada» de «nadie lo ha mirado».
        api.crear(
            "/api/v1/residencia/transferencias",
            {
                "tenant_id": yo,
                "tipo_dato": "registros",
                "desde_region": "ue",
                "hacia_region": "us",
                "subprocesador": "Soporte del fabricante del motor de búsqueda",
                "motivo": "Diagnóstico de incidencias con el índice, bajo petición",
            },
        )

    # ── Mis preferencias de aviso ─────────────────────────────────────────
    #
    # Por PUT: no es una colección a la que se añade, es lo que esta persona
    # ha elegido. Sin una sola fila, la pantalla de avisos parece rota.
    for tipo, canales in (
        ("mencion", ["app", "correo"]),
        ("asignacion", ["app"]),
        ("vencimiento", ["app", "correo"]),
    ):
        api.crear(
            "/api/v1/notificaciones/preferencias",
            {"tipo": tipo, "canales": canales, "agrupar_minutos": 15},
            metodo="PUT",
        )

    # ── Lo que cada uno ha autorizado de su suite ─────────────────────────
    api.crear(
        "/api/v1/suites/consentimiento",
        {
            "perfil": "Microsoft 365 del cliente",
            "recursos": ["correo"],
            "sentido": "leer",
            "tiene_refresco": True,
        },
    )

    # ── Una aprobación en marcha ──────────────────────────────────────────
    #
    # La bandeja vacía se lee como «no hay nada que aprobar», y lo que pasa es
    # que nunca se ha pedido ninguna.
    if oportunidades:
        api.crear(
            "/api/v1/aprobaciones",
            {
                "politica": "descuento",
                "objeto": "oportunidad",
                "objeto_id": oportunidades[0]["id"],
                "titulo": "Descuento del 18 % en la oferta de renovación",
                "etapas": [
                    {
                        "nombre": "Responsable comercial",
                        "origen": "usuario",
                        "usuarios": [u["id"] for u in usuarios[:1]],
                        "quorum": "cualquiera",
                        "vence_en_horas": 48,
                    },
                    {
                        "nombre": "Dirección",
                        "origen": "usuario",
                        "usuarios": [u["id"] for u in usuarios[:1]],
                        "quorum": "todos",
                        "vence_en_horas": 72,
                    },
                ],
                "campos_vigilados": ["importe", "descuento_pct"],
            },
        )

    # ── Un documento generado y su sobre de firma ─────────────────────────
    #
    # El panel «pendiente de firma» vacío se lee como «nadie debe nada». Para
    # que haya algo que firmar hace falta un documento de verdad: se genera
    # desde una plantilla, que es el camino que usa una persona.
    plantillas = api.listar("/api/v1/plantillas-documento", 3)
    if plantillas and cuentas and contactos:
        generado = api.crear(
            "/api/v1/plantillas-documento/generar",
            {
                "clave": plantillas[0].get("clave") or plantillas[0].get("nombre"),
                "objeto": "cuenta",
                "objeto_id": cuentas[0]["id"],
                "datos": {
                    "cliente": cuentas[0].get("nombre") or "Cliente",
                    "fecha": "2026-10-27",
                },
                # Una plantilla puede pedir campos que esta instalación no
                # tiene todavía: se permite para poder enseñar el circuito, y
                # el propio documento dice qué le faltó.
                "permitir_incompleto": True,
            },
        )
        # `generar` devuelve el TEXTO, no un documento archivado: lo dice su
        # propia respuesta —«aquí no se guarda el documento: dos copias del
        # mismo contrato divergen»— y el `documento_id` lo pone quien lo sube
        # al corpus. En esta instalación el corpus no tiene organización
        # asignada, así que no hay a qué atar un sobre de firma.
        documento_id = (generado or {}).get("documento_id") or (generado or {}).get("id")
        if not documento_id:
            sin_sembrar.append(
                "firma/sobres: hace falta un documento archivado en el corpus, y este "
                "despliegue no tiene gestor documental conectado"
            )
        if documento_id:
            api.crear(
                "/api/v1/firma/sobres",
                {
                    "documento_id": documento_id,
                    "firmantes": [
                        {
                            "nombre": contactos[0].get("nombre_completo") or "Cliente",
                            "email": contactos[0].get("email") or "cliente@ejemplo.com",
                            "orden": 1,
                        }
                    ],
                    "objeto_origen": "cuenta",
                    "objeto_origen_id": cuentas[0]["id"],
                    "cuenta_id": cuentas[0]["id"],
                    "asunto": "Contrato de mantenimiento 2026",
                    "mensaje": "Adjuntamos el contrato para su firma.",
                    "dias_validez": 15,
                },
            )

    # ── Y lo que NO se puede sembrar, con el motivo ───────────────────────
    #
    # Es la otra mitad del informe. Una tabla vacía porque no ha pasado nada no
    # es un hueco, y callarlo deja a quien mira la pantalla sin saber si falta
    # un dato o falta un suceso.
    sin_sembrar.extend(
        [
            "créditos de servicio: los genera el incumplimiento de un SLA, no un alta",
            "registros recibidos y conflictos de sincronización: llegan de fuera, "
            "cuando un sistema externo empuja datos",
            "proveedores de identidad: SAML y OIDC están apagados en esta instalación "
            "(SAML_ENABLED, OIDC_ENABLED)",
        ]
    )
    print(f"  {api.cuenta['creados']} creados hasta aquí")
    print("  Lo que no se siembra, y por qué:")
    for motivo in sin_sembrar:
        print(f"    · {motivo}")


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
    "proveedores": sembrar_proveedores,
    "catalogo": sembrar_catalogo,
    "cotizacion": sembrar_cotizacion,
    "prevision": sembrar_prevision,
    "prospeccion": sembrar_prospeccion,
    "integracion": sembrar_integracion,
    "resto": sembrar_resto,
    "trabajo": sembrar_trabajo,
    "chat": sembrar_chat,
    "duenos": sembrar_duenos,
    "pantallas_vacias": sembrar_pantallas_vacias,
    "calidad": sembrar_calidad,
    "analitica": sembrar_analitica,
    "rastro": sembrar_rastro,
    "lo_que_sale_vacio": sembrar_lo_que_sale_vacio,
    "las_que_siguen_vacias": sembrar_las_que_siguen_vacias,
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

    # **Lo que la API rechaza por diseño no es un fallo.** Mezclarlo con lo que
    # sí lo es tiene un coste medido: la primera pasada completa dio «30 altas
    # rechazadas», y ocho eran el producto defendiéndose —reverificación por
    # operación sensible, publicar exige otro aprobador, SAML apagado en esta
    # instalación—. Quien lee treinta persigue treinta, encuentra ocho que no
    # llevan a ninguna parte, y a la tercera deja de leer la lista.
    por_diseno, rotos = [], []
    for fallo in api.fallos:
        esperado = any(
            marca in fallo
            for marca in (
                "exige volver a verificar",
                "exige aprobación de alguien distinto",
                "no está activo en esta instalación",
                "está cerrada y bloqueada",
            )
        )
        (por_diseno if esperado else rotos).append(fallo)

    if por_diseno:
        print(f"\n{len(por_diseno)} rechazadas POR DISEÑO (el producto defendiéndose):")
        for fallo in por_diseno:
            print(f"  · {fallo}")

    if rotos:
        print(f"\n{len(rotos)} altas rechazadas sin motivo previsto:")
        for fallo in rotos:
            print(f"  · {fallo}")
        # Se devuelve error: un sembrado a medias que dice que todo fue bien es
        # cómo se acaba mirando una pantalla vacía sin saber que falló su alta.
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
