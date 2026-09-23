#!/usr/bin/env python3
"""Siembra una empresa con datos de verdad: volumen, variedad y coherencia.

    python scripts/sembrar_empresa.py --slug ficosa --nombre "Ficosa, S.A." \
        --email direccion@ficosa.example --contrasena "…"

**Qué lo diferencia de `sembrar_demo.py`.** Aquel crea cuatro cuentas para
enseñar que el sistema funciona. Este crea una empresa con la que se puede
trabajar: decenas de cuentas, cientos de contactos y actividades, un pipeline
con oportunidades repartidas por etapa y por fecha, casos en todos los estados
—incluidos los que incumplen el plazo— y usuarios con roles distintos. Sin
volumen no se ve nada de lo que hace un CRM: ni un embudo, ni una previsión, ni
una cola de casos, ni un aviso de vencimiento.

**Nada de esto está escrito fila a fila.** Los datos se componen de piezas
—nombres, apellidos, sectores, poblaciones, tipos de proyecto— y se combinan con
un generador **sembrado a partir del slug**, así que dos ejecuciones sobre la
misma empresa dan exactamente los mismos datos y dos empresas distintas dan
datos distintos. Una lista de trescientas filas escritas a mano sería imposible
de mantener y, peor, tendría la variedad de quien la escribió: cinco sectores y
tres provincias.

**Corre por partes, una por servicio.** No es una molestia del guion: el
contenedor de `sales` conecta con un rol que no tiene permisos sobre el esquema
de `party`, y eso es el aislamiento funcionando. Cada parte se ejecuta donde
tiene permisos:

    --parte tenant    desde tenancy
    --parte usuarios  desde identity
    --parte party     desde party
    --parte sales     desde sales
    --parte service   desde service

**Y las partes se pasan los identificadores por un fichero.** Las oportunidades
y los casos cuelgan de cuentas que viven en otro esquema. En ejecución, un
servicio que necesita eso lo resuelve por evento o por API; aquí, sembrando, se
escribe un fichero de enlace con `--enlaces`. Se dice claramente porque es la
única costura del guion: sin ella, las oportunidades saldrían sueltas y la mitad
de las pantallas —el 360 de la cuenta, los casos por cliente— no enseñarían
nada.

**Se niega a ejecutarse en producción.** Sembrar datos de ejemplo en la base de
un cliente no es un fallo recuperable con un `DELETE`: los eventos ya se han
publicado, la auditoría ya lo ha registrado y los webhooks ya han salido.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import unicodedata
from pathlib import Path
from uuid import UUID

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "packages" / "crmcore"))


# ══════════════════════════════════════════════════════════════════════════
#  Las piezas con las que se compone todo
# ══════════════════════════════════════════════════════════════════════════

NOMBRES = [
    "Ana",
    "Luis",
    "Marta",
    "Jordi",
    "Elena",
    "Paco",
    "Carmen",
    "Iván",
    "Nuria",
    "Sergio",
    "Lucía",
    "Andrés",
    "Pilar",
    "Óscar",
    "Rocío",
    "Javier",
    "Beatriz",
    "Rubén",
    "Silvia",
    "Gonzalo",
    "Mireia",
    "Alberto",
    "Teresa",
    "Unai",
    "Cristina",
    "Manuel",
    "Aitana",
    "Diego",
    "Raquel",
    "Pablo",
]

APELLIDOS = [
    "Bermúdez",
    "Onaindía",
    "Ferrer",
    "Puig",
    "Casal",
    "Ramos",
    "Iglesias",
    "Salvador",
    "Miralles",
    "Arrieta",
    "Castaño",
    "Vilaseca",
    "Lorenzo",
    "Ibáñez",
    "Quintana",
    "Sáenz",
    "Domínguez",
    "Herrero",
    "Prieto",
    "Bonet",
    "Escudero",
    "Cabrera",
    "Valverde",
    "Nogueira",
    "Zabala",
    "Peralta",
]

# Sector con su código CNAE. El código va porque el CRM lo usa para segmentar, y
# una cuenta sin sector no entra en ninguna audiencia: sembrar sin él dejaría
# medio marketing sin datos que enseñar.
SECTORES = [
    ("Componentes de automoción", "2932"),
    ("Metalurgia y transformados", "2511"),
    ("Electrónica industrial", "2611"),
    ("Plásticos técnicos", "2229"),
    ("Logística y transporte", "4941"),
    ("Distribución mayorista", "4690"),
    ("Maquinaria de producción", "2899"),
    ("Energía y renovables", "3511"),
    ("Sanidad privada", "8610"),
    ("Construcción industrial", "4299"),
    ("Química y recubrimientos", "2030"),
    ("Textil técnico", "1396"),
]

FORMAS = ["S.A.", "S.L.", "S.L.U.", "S.A.U.", "Group", "Ibérica, S.L."]

RAICES_EMPRESA = [
    "Metalúrgica del Norte",
    "Distribuciones Levante",
    "Talleres Arruti",
    "Electrónica Vallés",
    "Plásticos Ebro",
    "Transportes Duero",
    "Componentes Miño",
    "Industrias Guadiana",
    "Tecnologías Cantábrico",
    "Maquinaria Pirineos",
    "Química Mediterránea",
    "Sistemas Atlántico",
    "Automoción Segura",
    "Precisión Bética",
    "Montajes Aragón",
    "Forjas Alcarria",
    "Cableados Tajo",
    "Inyección Turia",
    "Estampaciones Nervión",
    "Recubrimientos Júcar",
    "Ensamblajes Sella",
    "Mecanizados Besós",
    "Bobinados Genil",
    "Troqueles Ter",
]

POBLACIONES = [
    ("Barcelona", "08001"),
    ("Viladecavalls", "08232"),
    ("Rubí", "08191"),
    ("Zaragoza", "50001"),
    ("Valencia", "46001"),
    ("Bilbao", "48001"),
    ("Vigo", "36201"),
    ("Valladolid", "47001"),
    ("Sevilla", "41001"),
    ("Pamplona", "31001"),
    ("Burgos", "09001"),
    ("Martorell", "08760"),
]

CARGOS = [
    "Directora de compras",
    "Director de compras",
    "Jefe de planta",
    "Responsable de calidad",
    "Gerente",
    "Director de operaciones",
    "Responsable de mantenimiento",
    "Ingeniera de producto",
    "Directora financiera",
    "Responsable de IT",
    "Jefa de proyecto",
    "Director general",
]

# Qué se vende. Cada tipo trae su horquilla de importe, porque un pipeline en el
# que todo vale lo mismo no enseña nada: el valor de la previsión está justo en
# que las oportunidades son desiguales.
PROYECTOS = [
    ("Renovación de línea de montaje", 120_000, 480_000),
    ("Utillaje para nueva referencia", 35_000, 140_000),
    ("Contrato de mantenimiento anual", 18_000, 90_000),
    ("Automatización de control de calidad", 60_000, 260_000),
    ("Suministro de componentes plegables", 45_000, 300_000),
    ("Migración de sistema de planta", 80_000, 220_000),
    ("Ampliación de capacidad de inyección", 150_000, 600_000),
    ("Serie corta de preproducción", 12_000, 55_000),
    ("Banco de pruebas a medida", 40_000, 180_000),
    ("Reposición de sensórica", 9_000, 42_000),
]

ASUNTOS_CASO = [
    "Pieza fuera de tolerancia en el lote",
    "Retraso en la entrega comprometida",
    "Avería en la célula de soldadura",
    "Discrepancia en el albarán",
    "Error de referencia en el pedido",
    "Sensor de posición sin señal",
    "Vibración anómala en la prensa",
    "Documentación de homologación incompleta",
    "Consumo eléctrico por encima de lo previsto",
    "Software de la estación no arranca",
    "Petición de repuesto urgente",
    "Duda sobre el plan de mantenimiento",
]

MOTIVOS_PERDIDA = ["precio", "plazo", "competencia", "sin_presupuesto", "sin_decision"]
CANALES_LEAD = ["web", "feria", "referencia", "llamada_fria", "campaña", "partner"]


def _sin_acentos(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )


def _dominio(empresa: str) -> str:
    base = _sin_acentos(empresa).lower()
    base = "".join(c for c in base if c.isalnum() or c == " ").split()
    # `.example` está reservado para esto (RFC 2606): un dominio inventado que
    # existiera de verdad convertiría los datos de muestra en correo a terceros.
    return f"{''.join(base[:2])[:22]}.example"


def _correo(nombre: str, apellidos: str, empresa: str) -> str:
    n = _sin_acentos(nombre).lower()
    a = _sin_acentos(apellidos).lower().replace(" ", "")
    return f"{n}.{a}@{_dominio(empresa)}"


def _cif(rnd: random.Random) -> str:
    """Un CIF español con su dígito de control bien calculado.

    Tiene que estar bien porque el CRM lo valida al dar de alta la cuenta, y hace
    bien: un identificador fiscal mal formado es lo que luego impide cruzar la
    cuenta con el ERP. Sembrar con identificadores inválidos habría obligado a
    saltarse la validación, y entonces los datos de muestra no servirían para
    probar justo lo que hay que probar.

    Que el control sea correcto no significa que el CIF exista: es una
    comprobación de forma, y siete dígitos al azar difícilmente caen en una
    sociedad real.
    """
    letra = rnd.choice("ABEH")  # estas llevan control numérico
    digitos = [rnd.randrange(0, 10) for _ in range(7)]
    pares = sum(digitos[i] for i in (1, 3, 5))
    impares = 0
    for i in (0, 2, 4, 6):
        doble = digitos[i] * 2
        impares += doble // 10 + doble % 10
    control = (10 - (pares + impares) % 10) % 10
    return f"{letra}{''.join(map(str, digitos))}{control}"


def _telefono(rnd: random.Random) -> str:
    return f"+34 9{rnd.randrange(10, 99)} {rnd.randrange(100, 999)} {rnd.randrange(100, 999)}"


# ══════════════════════════════════════════════════════════════════════════
#  Cuánto se siembra
# ══════════════════════════════════════════════════════════════════════════


class Volumen:
    """Cuántas filas de cada cosa. Se pasa por CLI para poder sembrar pequeño.

    El reparto no es arbitrario: hay más contactos que cuentas porque una cuenta
    industrial tiene varios interlocutores, más actividades que todo lo demás
    porque el día a día de un CRM son actividades, y más casos que oportunidades
    porque el postventa genera mucho más volumen que la venta.
    """

    def __init__(self, escala: int) -> None:
        self.cuentas = escala
        self.contactos = escala * 3
        self.actividades = escala * 4
        self.leads = int(escala * 1.4)
        self.oportunidades = escala * 2
        self.casos = int(escala * 2.5)


# ══════════════════════════════════════════════════════════════════════════
#  Partes
# ══════════════════════════════════════════════════════════════════════════


def _cambiar_a(servicio: str) -> None:
    """Apunta el proceso al esquema y al rol de ese servicio.

    La configuración y el engine se cachean por proceso: sin limpiarlos, la
    siguiente parte seguiría conectada al esquema de la anterior y fallaría con
    un «relation does not exist» que no dice nada de lo que pasa.
    """
    from crmcore.config import limpiar_cache_settings
    from crmcore.db.session import reset_engine

    os.environ["SERVICE_NAME"] = servicio
    limpiar_cache_settings()
    reset_engine()


def sembrar_tenant(cfg: argparse.Namespace) -> UUID:
    """Plan, tenant y unidades de negocio. Corre donde `tenancy` tiene permisos."""
    _cambiar_a("tenancy")
    from crmcore.db.uow import unidad_de_trabajo
    from crmcore.tenancy.context import contexto_sistema
    from sqlalchemy import select

    from services.tenancy import servicio as svc
    from services.tenancy.modelos import Plan, Tenant, UnidadNegocio

    with contexto_sistema(origen="cli"), unidad_de_trabajo(sistema=True) as uow:
        existente = uow.db.execute(
            select(Tenant).where(Tenant.slug == cfg.slug)
        ).scalar_one_or_none()
        if existente:
            print(f"El tenant «{cfg.slug}» ya existe ({existente.id}).")
            tenant_id = existente.id
        else:
            if not uow.db.execute(select(Plan).where(Plan.codigo == cfg.plan)).scalar_one_or_none():
                uow.db.add(
                    Plan(
                        codigo=cfg.plan,
                        nombre="Corporativo",
                        descripcion="Todo activo, con cuotas dimensionadas para varias plantas",
                        capacidades={
                            "procesos": True,
                            "automatizaciones": True,
                            "integraciones": True,
                            "webhooks": True,
                            "ia_generativa": False,
                        },
                        cuotas={
                            "quota_registros": 1_000_000,
                            "quota_api_calls_por_minuto": 6_000,
                        },
                    )
                )
                uow.db.flush()
            tenant = svc.crear_tenant(uow, slug=cfg.slug, nombre=cfg.nombre, plan=cfg.plan)
            tenant_id = tenant.id
            print(f"Tenant «{cfg.slug}» creado: {tenant_id}")

        # Unidades de negocio: sin ellas, la visibilidad por unidad y los
        # informes por planta no tienen sobre qué apoyarse, y son la mitad de
        # lo que distingue a una empresa industrial de una lista de contactos.
        existentes = {
            u.codigo
            for u in uow.db.execute(
                select(UnidadNegocio).where(UnidadNegocio.tenant_id == tenant_id)
            ).scalars()
        }
        nuevas = 0
        for codigo, nombre in (
            ("corp", "Corporación"),
            ("oem", "Equipo original (OEM)"),
            ("recambio", "Recambio y postventa"),
            ("iberia", "Iberia"),
            ("centroeuropa", "Centroeuropa"),
        ):
            if codigo in existentes:
                continue
            uow.db.add(UnidadNegocio(tenant_id=tenant_id, codigo=codigo, nombre=nombre))
            nuevas += 1
        if nuevas:
            print(f"{nuevas} unidades de negocio creadas")
        return tenant_id


# Quién trabaja aquí. Con roles distintos a propósito: con todo el mundo de
# administrador no se ve nada de lo que hace el CRM —ni una regla de visibilidad,
# ni una aprobación, ni un permiso denegado— y eso es justo lo que hay que poder
# enseñar.
PLANTILLA = [
    ("direccion", "Dirección general", ["admin"]),
    ("ventas.oem", "Responsable de ventas OEM", ["responsable_ventas"]),
    ("comercial.norte", "Comercial zona norte", ["comercial"]),
    ("comercial.levante", "Comercial zona levante", ["comercial"]),
    ("comercial.centro", "Comercial zona centro", ["comercial"]),
    ("soporte.jefe", "Responsable de soporte", ["responsable_soporte"]),
    ("soporte.n1", "Agente de soporte N1", ["agente_soporte"]),
    ("soporte.n2", "Agente de soporte N2", ["agente_soporte"]),
    ("marketing", "Responsable de marketing", ["usuario"]),
    ("auditoria", "Auditoría interna", ["solo_lectura"]),
]


def sembrar_usuarios(cfg: argparse.Namespace, tenant_id: UUID) -> list[str]:
    """La plantilla. Corre donde `identity` tiene permisos."""
    _cambiar_a("identity")
    from crmcore.db.uow import unidad_de_trabajo
    from crmcore.errors import Conflicto
    from crmcore.tenancy.context import con_contexto

    from services.identity import servicio as svc

    dominio = cfg.email.split("@", 1)[1]
    creados: list[str] = []
    with con_contexto(tenant_id=tenant_id, origen="cli"), unidad_de_trabajo(tenant_id) as uow:
        # La cuenta que pidió quien siembra va primero y con su correo tal cual:
        # es la que se va a usar para entrar, y hacerla derivar del patrón
        # obligaría a adivinarla.
        try:
            svc.crear_usuario(
                uow,
                email=cfg.email,
                nombre=cfg.responsable,
                tenant_id=tenant_id,
                roles=["admin"],
                contrasena=cfg.contrasena,
                via="semilla",
            )
            creados.append(cfg.email)
        except Conflicto:
            print(f"El usuario «{cfg.email}» ya existe en este tenant.")

        for buzon, nombre, roles in PLANTILLA:
            email = f"{buzon}@{dominio}"
            if email == cfg.email:
                continue
            try:
                svc.crear_usuario(
                    uow,
                    email=email,
                    nombre=nombre,
                    tenant_id=tenant_id,
                    roles=roles,
                    # La misma contraseña para toda la plantilla de muestra, y
                    # se dice: son cuentas de un entorno de demostración, y
                    # fingir que cada una tiene la suya obligaría a apuntarlas
                    # en algún sitio, que es peor.
                    contrasena=cfg.contrasena,
                    via="semilla",
                )
                creados.append(email)
            except Conflicto:
                continue
    print(f"{len(creados)} usuarios creados")
    return creados


def sembrar_party(cfg: argparse.Namespace, tenant_id: UUID, vol: Volumen) -> dict[str, object]:
    """Cuentas, contactos y actividades. Corre donde `party` tiene permisos."""
    _cambiar_a("party")
    from datetime import datetime, timedelta, timezone

    from crmcore.db.uow import unidad_de_trabajo
    from crmcore.errors import Conflicto
    from crmcore.tenancy.context import con_contexto
    from sqlalchemy import select

    from services.party import servicio as svc
    from services.party.modelos import Cuenta

    rnd = random.Random(f"{cfg.slug}:party")
    enlaces: dict[str, object] = {"cuentas": [], "contactos": []}

    with con_contexto(tenant_id=tenant_id, origen="cli"), unidad_de_trabajo(tenant_id) as uow:
        ya = list(uow.db.execute(select(Cuenta).limit(1)).scalars())
        if ya:
            print("Ya hay cuentas en este tenant. Se reutilizan para enlazar.")
            for cuenta in uow.db.execute(select(Cuenta)).scalars():
                enlaces["cuentas"].append(  # type: ignore[union-attr]
                    {"id": str(cuenta.id), "nombre": cuenta.nombre, "tier": cuenta.tier}
                )
            return enlaces

        cuentas: list[tuple[UUID, str, str]] = []
        for i in range(vol.cuentas):
            raiz = RAICES_EMPRESA[i % len(RAICES_EMPRESA)]
            # A partir de la segunda vuelta se añade la población para que el
            # nombre siga siendo distinto sin repetir la raíz: es lo que hace un
            # grupo industrial de verdad —una sociedad por planta—.
            vuelta = i // len(RAICES_EMPRESA)
            poblacion, cp = POBLACIONES[i % len(POBLACIONES)]
            nombre = (
                f"{raiz}, {rnd.choice(FORMAS)}"
                if vuelta == 0
                else f"{raiz} {poblacion}, {rnd.choice(FORMAS)}"
            )
            sector, cnae = SECTORES[i % len(SECTORES)]
            # El tier no se reparte al azar: pocas cuentas A, muchas C. Una
            # cartera equilibrada no existe, y con ella las reglas de SLA por
            # tier y la priorización comercial no se distinguen.
            tier = "A" if i % 9 == 0 else ("B" if i % 3 == 0 else "C")
            try:
                cuenta = svc.crear_cuenta(
                    uow,
                    nombre=nombre,
                    sector_codigo=cnae,
                    sector_esquema="CNAE",
                    tier=tier,
                    telefono=_telefono(rnd),
                    web=f"https://www.{_dominio(nombre)}",
                    email=f"info@{_dominio(nombre)}",
                    empleados=(plantilla := rnd.choice([25, 60, 120, 250, 400, 900, 1800])),
                    # El tamaño se deriva de la plantilla en vez de sortearse
                    # aparte: una cuenta de 25 personas etiquetada como «grande»
                    # ensucia cualquier segmento que use uno de los dos campos.
                    tamano=(
                        "pequena" if plantilla < 50 else "mediana" if plantilla < 250 else "grande"
                    ),
                    # La facturación sale de la plantilla, no de un sorteo
                    # aparte. Sorteada daba cuentas de 25 personas facturando
                    # 254 M€, y un dato así no es «de muestra»: es falso, y
                    # cualquier segmento o informe que lo use sale absurdo.
                    # 90–260 k€ por empleado es la horquilla industrial.
                    facturacion_anual=plantilla * rnd.randrange(90, 260) * 1_000,
                    identificadores=[{"tipo": "nif", "valor": _cif(rnd)}],
                    forzar=True,
                )
            except Conflicto:
                continue
            cuentas.append((cuenta.id, nombre, tier))
            enlaces["cuentas"].append(  # type: ignore[union-attr]
                {"id": str(cuenta.id), "nombre": nombre, "tier": tier, "sector": sector}
            )
        print(f"{len(cuentas)} cuentas creadas")

        contactos: list[tuple[UUID, UUID]] = []
        for i in range(vol.contactos):
            cuenta_id, empresa, _tier = cuentas[i % len(cuentas)]
            nombre = NOMBRES[(i * 7) % len(NOMBRES)]
            apellidos = (
                f"{APELLIDOS[(i * 5) % len(APELLIDOS)]} {APELLIDOS[(i * 11) % len(APELLIDOS)]}"
            )
            try:
                contacto = svc.crear_contacto(
                    uow,
                    nombre=nombre,
                    apellidos=apellidos,
                    email=_correo(nombre, apellidos.split()[0] + str(i), empresa),
                    telefono=_telefono(rnd),
                    cargo=CARGOS[i % len(CARGOS)],
                    cuenta_id=cuenta_id,
                    forzar=True,
                )
            except Conflicto:
                continue
            contactos.append((contacto.id, cuenta_id))
            enlaces["contactos"].append(  # type: ignore[union-attr]
                {"id": str(contacto.id), "cuenta_id": str(cuenta_id)}
            )
        print(f"{len(contactos)} contactos creados")

        # Las actividades se reparten en el tiempo hacia atrás y hacia delante.
        # Todas al día escondería los avisos y los vencimientos, que es la mitad
        # de lo que se nota al usar un CRM.
        ahora = datetime.now(timezone.utc)
        tipos = ["llamada", "correo", "reunion", "tarea", "visita"]
        acciones = [
            "Seguimiento de la oferta",
            "Enviar propuesta revisada",
            "Visita a planta",
            "Revisión de plan de calidad",
            "Cierre de condiciones anuales",
            "Presentación de nueva referencia",
            "Reclamación de pedido pendiente",
            "Repaso de incidencias abiertas",
        ]
        for i in range(vol.actividades):
            cuenta_id, empresa, _t = cuentas[i % len(cuentas)]
            dias = rnd.randrange(-90, 45)
            svc.crear_actividad(
                uow,
                tipo=tipos[i % len(tipos)],
                asunto=f"{acciones[i % len(acciones)]} — {empresa.split(',')[0]}",
                objeto="cuenta",
                objeto_id=cuenta_id,
                vence_at=ahora + timedelta(days=dias, hours=rnd.randrange(0, 9)),
            )
        print(f"{vol.actividades} actividades creadas, repartidas entre −90 y +45 días")

    return enlaces


def sembrar_sales(cfg: argparse.Namespace, tenant_id: UUID, vol: Volumen, enlaces: dict) -> None:
    """Pipeline, leads y oportunidades. Corre donde `sales` tiene permisos."""
    _cambiar_a("sales")
    from datetime import date, timedelta
    from decimal import Decimal

    from crmcore.db.uow import unidad_de_trabajo
    from crmcore.tenancy.context import con_contexto
    from sqlalchemy import select

    from services.sales import servicio as svc
    from services.sales.modelos import Etapa, Lead, Oportunidad, Pipeline

    rnd = random.Random(f"{cfg.slug}:sales")
    cuentas = list(enlaces.get("cuentas") or [])

    # Clave, nombre, probabilidad, terminal, ganada. «Terminal» y «ganada» van
    # por separado: perdida también es terminal, y confundirlas falsea cualquier
    # ratio de conversión.
    etapas_def = [
        ("cualificacion", "Cualificación", 10, False, False),
        ("analisis", "Análisis técnico", 25, False, False),
        ("oferta", "Oferta presentada", 45, False, False),
        ("negociacion", "Negociación", 70, False, False),
        ("adjudicacion", "Pendiente de adjudicación", 85, False, False),
        ("ganada", "Ganada", 100, True, True),
        ("perdida", "Perdida", 0, True, False),
    ]

    with con_contexto(tenant_id=tenant_id, origen="cli"), unidad_de_trabajo(tenant_id) as uow:
        pipeline = uow.db.execute(
            select(Pipeline).where(Pipeline.tenant_id == tenant_id).limit(1)
        ).scalar_one_or_none()
        if pipeline is None:
            pipeline = Pipeline(
                tenant_id=tenant_id,
                clave="oem",
                nombre="Venta a fabricante (OEM)",
                descripcion="De la cualificación técnica a la adjudicación del programa.",
                activo=True,
                por_defecto=True,
            )
            uow.db.add(pipeline)
            uow.db.flush()
            for orden, (clave, nombre, prob, terminal, ganada) in enumerate(etapas_def):
                uow.db.add(
                    Etapa(
                        tenant_id=tenant_id,
                        pipeline_id=pipeline.id,
                        clave=clave,
                        nombre=nombre,
                        orden=orden,
                        probabilidad=prob,
                        terminal=terminal,
                        ganada=ganada,
                    )
                )
            uow.db.flush()
            print(f"Pipeline «{pipeline.nombre}» con {len(etapas_def)} etapas creado")

        etapas = list(
            uow.db.execute(
                select(Etapa).where(Etapa.pipeline_id == pipeline.id).order_by(Etapa.orden)
            ).scalars()
        )
        abiertas = [e for e in etapas if not e.terminal]
        ganada = next((e for e in etapas if e.ganada), None)
        perdida = next((e for e in etapas if e.terminal and not e.ganada), None)

        if uow.db.execute(select(Lead).limit(1)).scalar_one_or_none():
            print("Ya hay leads en este tenant. No se tocan.")
        else:
            for i in range(vol.leads):
                nombre = NOMBRES[(i * 3) % len(NOMBRES)]
                apellidos = APELLIDOS[(i * 13) % len(APELLIDOS)]
                empresa = f"{RAICES_EMPRESA[(i * 5) % len(RAICES_EMPRESA)]} {rnd.choice(FORMAS)}"
                svc.crear_lead(
                    uow,
                    nombre=nombre,
                    apellidos=apellidos,
                    empresa=empresa,
                    email=_correo(nombre, f"{apellidos}{i}", empresa),
                    telefono=_telefono(rnd),
                    origen=rnd.choice(CANALES_LEAD),
                )
            print(f"{vol.leads} leads creados")

        if uow.db.execute(select(Oportunidad).limit(1)).scalar_one_or_none():
            print("Ya hay oportunidades en este tenant. No se tocan.")
        elif not cuentas:
            print("Sin fichero de enlace no se pueden atar oportunidades a cuentas: se omiten.")
        else:
            hoy = date.today()
            for i in range(vol.oportunidades):
                cuenta = cuentas[i % len(cuentas)]
                titulo, minimo, maximo = PROYECTOS[i % len(PROYECTOS)]
                # Una de cada cuatro está cerrada, y de esas, dos de cada tres
                # ganadas. Un pipeline sin histórico no permite calcular ni una
                # tasa de conversión ni un ciclo medio de venta, que es para lo
                # que sirve tener el histórico.
                cerrada = i % 4 == 0
                etapa = (
                    (ganada if i % 12 != 0 else perdida)
                    if cerrada and ganada and perdida
                    else abiertas[i % len(abiertas)]
                )
                assert etapa is not None
                dias = rnd.randrange(-180, -5) if cerrada else rnd.randrange(5, 210)
                extras: dict[str, object] = {
                    "descripcion": f"{titulo} para {cuenta['nombre']}.",
                    "fecha_cierre": hoy + timedelta(days=dias),
                    "etapa_id": etapa.id,
                }
                if cerrada:
                    extras["estado"] = "ganada" if etapa.ganada else "perdida"
                    extras["fecha_cierre_real"] = hoy + timedelta(days=dias)
                    if not etapa.ganada:
                        extras["motivo_perdida"] = rnd.choice(MOTIVOS_PERDIDA)
                svc.crear_oportunidad_nueva(
                    uow,
                    nombre=f"{titulo} — {cuenta['nombre'].split(',')[0]}",
                    cuenta_id=UUID(str(cuenta["id"])),
                    pipeline_id=pipeline.id,
                    importe=Decimal(rnd.randrange(minimo, maximo)),
                    **extras,
                )
            print(f"{vol.oportunidades} oportunidades creadas, una de cada cuatro ya cerrada")


def sembrar_service(cfg: argparse.Namespace, tenant_id: UUID, vol: Volumen, enlaces: dict) -> None:
    """Taxonomía, SLA, colas y casos. Corre donde `service` tiene permisos."""
    _cambiar_a("service")
    from datetime import datetime, timedelta, timezone

    from crmcore.db.uow import unidad_de_trabajo
    from crmcore.tenancy.context import con_contexto
    from sqlalchemy import select

    from services.service.modelos import Caso, CategoriaCaso, DefinicionSLA
    from services.service.operacion import ColaCasos

    rnd = random.Random(f"{cfg.slug}:service")
    cuentas = list(enlaces.get("cuentas") or [])

    with con_contexto(tenant_id=tenant_id, origen="cli"), unidad_de_trabajo(tenant_id) as uow:
        if uow.db.execute(select(CategoriaCaso).limit(1)).scalar_one_or_none() is None:
            # Un árbol de dos niveles: solo las hojas se pueden elegir. Dejar
            # elegir el nodo intermedio convierte «calidad» en un cajón donde
            # acaba la mitad de los casos, y entonces la taxonomía no agrupa.
            arbol = {
                ("calidad", "Calidad de producto"): [
                    ("dimensional", "Fuera de tolerancia", "alta"),
                    ("material", "Defecto de material", "alta"),
                    ("acabado", "Acabado y aspecto", "baja"),
                ],
                ("logistica", "Logística y entregas"): [
                    ("retraso", "Retraso de entrega", "alta"),
                    ("albaran", "Discrepancia documental", "baja"),
                    ("embalaje", "Embalaje dañado", "media"),
                ],
                ("tecnico", "Soporte técnico"): [
                    ("averia", "Avería en máquina", "critica"),
                    ("software", "Software de estación", "media"),
                    ("sensorica", "Sensórica y señales", "media"),
                ],
                ("comercial", "Administración y comercial"): [
                    ("facturacion", "Facturación", "baja"),
                    ("pedido", "Error en pedido", "media"),
                ],
            }
            for orden, ((clave, nombre), hojas) in enumerate(arbol.items()):
                padre = CategoriaCaso(
                    tenant_id=tenant_id,
                    clave=clave,
                    nombre=nombre,
                    orden=orden * 10,
                    seleccionable=False,
                )
                uow.db.add(padre)
                uow.db.flush()
                for j, (hclave, hnombre, prioridad) in enumerate(hojas):
                    uow.db.add(
                        CategoriaCaso(
                            tenant_id=tenant_id,
                            padre_id=padre.id,
                            clave=f"{clave}.{hclave}",
                            nombre=hnombre,
                            orden=j,
                            prioridad_sugerida=prioridad,
                        )
                    )
            uow.db.flush()
            print(f"Taxonomía de casos creada: {len(arbol)} familias y sus hojas")

        if uow.db.execute(select(DefinicionSLA).limit(1)).scalar_one_or_none() is None:
            # Por tier de cliente. Un SLA único para todos no es un compromiso:
            # o se le promete de más al cliente pequeño o de menos al grande.
            for clave, nombre, tier, primera, resolucion in (
                ("oro", "Clientes A — programa OEM", "A", 1, 8),
                ("plata", "Clientes B", "B", 4, 24),
                ("bronce", "Clientes C", "C", 8, 72),
            ):
                uow.db.add(
                    DefinicionSLA(
                        tenant_id=tenant_id,
                        clave=clave,
                        nombre=nombre,
                        tier_cliente=tier,
                        horas_primera_respuesta=primera,
                        horas_resolucion=resolucion,
                        calendario="laborable",
                        aviso_pct=80,
                    )
                )
            uow.db.flush()
            print("3 definiciones de SLA creadas, una por tier")

        if uow.db.execute(select(ColaCasos).limit(1)).scalar_one_or_none() is None:
            for clave, nombre, descripcion in (
                ("entrada", "Entrada", "Todo lo que llega sin clasificar."),
                ("calidad", "Calidad", "Reclamaciones de producto y no conformidades."),
                ("campo", "Servicio de campo", "Lo que exige desplazamiento a planta."),
                ("admin", "Administración", "Facturación, pedidos y documentación."),
            ):
                uow.db.add(
                    ColaCasos(
                        tenant_id=tenant_id, clave=clave, nombre=nombre, descripcion=descripcion
                    )
                )
            uow.db.flush()
            print("4 colas de casos creadas")

        if uow.db.execute(select(Caso).limit(1)).scalar_one_or_none():
            print("Ya hay casos en este tenant. No se tocan.")
            return
        if not cuentas:
            print("Sin fichero de enlace no se pueden atar casos a cuentas: se omiten.")
            return

        hojas = list(
            uow.db.execute(
                select(CategoriaCaso).where(
                    CategoriaCaso.tenant_id == tenant_id,
                    CategoriaCaso.seleccionable.is_(True),
                    CategoriaCaso.padre_id.isnot(None),
                )
            ).scalars()
        )
        ahora = datetime.now(timezone.utc)
        # El reparto de estados imita una cola real: la mayoría cerrada, una
        # minoría viva. Con todos abiertos no se puede medir nada —ni tiempo de
        # resolución ni reincidencia— y con todos cerrados la cola sale vacía.
        estados = (
            ["cerrado"] * 10
            + ["resuelto"] * 3
            + ["en_curso"] * 4
            + ["esperando_cliente"] * 2
            + ["asignado"] * 2
            + ["nuevo"] * 2
        )
        horas_por_tier = {"A": 8, "B": 24, "C": 72}
        incumplidos = 0
        for i in range(vol.casos):
            cuenta = cuentas[i % len(cuentas)]
            hoja = hojas[i % len(hojas)] if hojas else None
            estado = estados[i % len(estados)]
            tier = str(cuenta.get("tier") or "C")
            abierto = ahora - timedelta(days=rnd.randrange(0, 120), hours=rnd.randrange(0, 23))
            vence = abierto + timedelta(hours=horas_por_tier.get(tier, 72))
            terminado = estado in ("cerrado", "resuelto")
            # Uno de cada siete se pasa de plazo. Una cola sin incumplimientos
            # no enseña para qué sirve el SLA, y ponerlos todos al día sería
            # sembrar el sistema con la respuesta que a uno le gustaría ver.
            tarde = i % 7 == 0
            resuelto_at = (
                (
                    vence + timedelta(hours=rnd.randrange(2, 40))
                    if tarde
                    else abierto
                    + timedelta(hours=rnd.randrange(1, max(2, horas_por_tier.get(tier, 72))))
                )
                if terminado
                else None
            )
            if tarde and terminado:
                incumplidos += 1
            uow.db.add(
                Caso(
                    tenant_id=tenant_id,
                    codigo=f"CS-{i + 1:05d}",
                    asunto=f"{ASUNTOS_CASO[i % len(ASUNTOS_CASO)]} — {cuenta['nombre'].split(',')[0]}",
                    descripcion="Caso de muestra generado al sembrar la empresa.",
                    tipo=rnd.choice(["incidencia", "peticion", "reclamacion"]),
                    categoria_id=hoja.id if hoja else None,
                    linea="general",
                    severidad=rnd.choice(["baja", "media", "alta", "critica"]),
                    prioridad=(hoja.prioridad_sugerida if hoja else None) or "media",
                    origen=rnd.choice(["correo", "telefono", "portal", "manual"]),
                    estado=estado,
                    cuenta_id=UUID(str(cuenta["id"])),
                    equipo=rnd.choice(["entrada", "calidad", "campo", "admin"]),
                    sla_clave={"A": "oro", "B": "plata"}.get(tier, "bronce"),
                    sla_version=1,
                    vence_resolucion_at=vence,
                    resuelto_at=resuelto_at,
                    cerrado_at=resuelto_at if estado == "cerrado" else None,
                    incumplio_resolucion=bool(terminado and tarde),
                    created_at=abierto,
                )
            )
        print(f"{vol.casos} casos creados; {incumplidos} cerrados fuera de plazo")


# ══════════════════════════════════════════════════════════════════════════


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug", required=True, help="identificador corto de la empresa")
    parser.add_argument("--nombre", default="", help="razón social")
    parser.add_argument("--email", default="", help="correo de la cuenta de administración")
    parser.add_argument("--contrasena", default="", help="contraseña de las cuentas sembradas")
    parser.add_argument("--responsable", default="Dirección", help="nombre de esa persona")
    parser.add_argument("--plan", default="corporativo")
    parser.add_argument(
        "--escala",
        type=int,
        default=60,
        help="cuántas cuentas; el resto de volúmenes se derivan de esta",
    )
    parser.add_argument("--parte", default="todo")
    parser.add_argument("--tenant", default="", help="identificador del tenant, para las partes")
    parser.add_argument("--enlaces", default="", help="fichero de enlace entre partes")
    cfg = parser.parse_args()
    cfg.nombre = cfg.nombre or cfg.slug
    cfg.email = cfg.email or f"direccion@{cfg.slug}.example"

    from crmcore.config import get_settings

    if get_settings().env.lower().startswith("prod"):
        print(
            "Esto no se ejecuta en producción. Sembrar datos de ejemplo en la base "
            "de un cliente no se deshace con un DELETE: los eventos ya se han "
            "publicado y la auditoría ya lo ha registrado.",
            file=sys.stderr,
        )
        return 2

    vol = Volumen(cfg.escala)
    ruta_enlaces = Path(cfg.enlaces) if cfg.enlaces else None
    enlaces: dict[str, object] = {}
    if ruta_enlaces and ruta_enlaces.exists():
        enlaces = json.loads(ruta_enlaces.read_text(encoding="utf-8"))

    if cfg.parte in ("tenant", "todo"):
        tenant_id = sembrar_tenant(cfg)
        print(f"\nTENANT={tenant_id}\n")
        if cfg.parte == "tenant":
            return 0
    else:
        if not cfg.tenant:
            print(
                "Falta --tenant con el identificador. Lo imprime `--parte tenant`.", file=sys.stderr
            )
            return 1
        tenant_id = UUID(cfg.tenant)

    if cfg.parte in ("usuarios", "todo"):
        sembrar_usuarios(cfg, tenant_id)
        if cfg.parte == "usuarios":
            return 0

    if cfg.parte in ("party", "todo"):
        enlaces = sembrar_party(cfg, tenant_id, vol)
        if ruta_enlaces:
            ruta_enlaces.write_text(json.dumps(enlaces, ensure_ascii=False), encoding="utf-8")
            print(f"Enlaces escritos en {ruta_enlaces}")
        if cfg.parte == "party":
            return 0

    if cfg.parte in ("sales", "todo"):
        sembrar_sales(cfg, tenant_id, vol, enlaces)
        if cfg.parte == "sales":
            return 0

    if cfg.parte in ("service", "todo"):
        sembrar_service(cfg, tenant_id, vol, enlaces)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
