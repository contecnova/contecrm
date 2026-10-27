#!/usr/bin/env python3
"""Siembra una empresa con datos de verdad: volumen, variedad, coherencia y diez
años de historia (CRM-07.04.05.06).

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
    --parte marketing desde marketing

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

from scripts.datos_demo import (  # noqa: E402
    PRODUCTOS_DEMO,
    Reloj,
    activo_instalado,
    campanas,
    lineas_de_oferta,
    perfil_de_tecnico,
    reloj_de_caso,
    reparto_de_embudo,
)

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

    def __init__(self, escala: int, anios: int = 10) -> None:
        self.cuentas = escala
        self.contactos = escala * 3
        # Más actividades y más casos cuanto más periodo se siembre: con los
        # volúmenes atados solo a la escala, diez años de historia tenían la
        # misma cantidad de apuntes que seis meses, y la gráfica de evolución
        # salía como una línea plana con un pico al final.
        self.actividades = escala * 4 * anios
        self.leads = int(escala * 1.4) * max(1, anios // 2)
        self.oportunidades = escala * 2 * max(1, anios // 2)
        # Por año y no por periodo: con los casos atados sólo a la escala, diez
        # años de postventa daban 186 casos —uno y medio al mes— y la cola del
        # día salía con once. Un cliente industrial abre varios al año, y es
        # ese ritmo el que llena la bandeja de quien atiende.
        self.casos = int(escala * 2.5) * anios
        self.activos = escala * 2
        self.campanas_por_anio = 4


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
    """Cuentas, contactos y actividades, repartidas en los años que se pidan.

    Las fechas de alta no son decorativas. Sin ellas, diez años de cartera
    aparecen creados hoy: la gráfica de altas por año sale como una barra, la
    comparación con el año pasado no tiene con qué comparar y la antigüedad de
    un cliente —que es lo que decide si se le llama o no— es cero para todos.
    """
    _cambiar_a("party")
    from datetime import datetime, timedelta

    from crmcore.db.uow import unidad_de_trabajo
    from crmcore.errors import Conflicto
    from crmcore.tenancy.context import con_contexto
    from sqlalchemy import select

    from services.party import servicio as svc
    from services.party.modelos import Cuenta

    rnd = random.Random(f"{cfg.slug}:party")
    reloj = Reloj(anios=cfg.anios)
    enlaces: dict[str, object] = {"cuentas": [], "contactos": [], "anios": cfg.anios}

    with con_contexto(tenant_id=tenant_id, origen="cli"), unidad_de_trabajo(tenant_id) as uow:
        # No se sale si ya hay cuentas: se **completa** lo que falte. Salir era
        # lo que dejaba a un tenant con cuatro cuentas de la demo mínima sin
        # poder crecer nunca —el sembrado se daba por hecho y no creaba nada—,
        # y con cuatro cuentas no se ve ni un embudo ni una cola de casos. El
        # alta ya rechaza los duplicados por nombre, así que repetirlo es
        # seguro.

        # Con su fecha de alta: lo que cuelga de una cuenta no puede nacer
        # antes que ella, y para comprobarlo hay que tenerla a mano.
        cuentas: list[tuple[UUID, str, str, datetime]] = []
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
                    # La cartera no nace de golpe: se reparte sobre el periodo
                    # con más altas en los años recientes, que es como crece
                    # una empresa.
                    created_at=(alta := reloj.momento(rnd)),
                )
            except Conflicto:
                continue
            cuentas.append((cuenta.id, nombre, tier, alta))
            enlaces["cuentas"].append(  # type: ignore[union-attr]
                {
                    "id": str(cuenta.id),
                    "nombre": nombre,
                    "tier": tier,
                    "sector": sector,
                    "alta": alta.isoformat(),
                }
            )
        print(f"{len(cuentas)} cuentas creadas")

        # A lo que viene después se le cuelgan TODAS las cuentas del tenant, no
        # solo las de esta pasada: si no, al completar un tenant que ya tenía
        # cuentas, los contactos y las oportunidades se amontonarían en las
        # nuevas y las viejas se quedarían sin nada.
        for fila in uow.db.execute(select(Cuenta).where(Cuenta.tenant_id == tenant_id)).scalars():
            if all(str(fila.id) != c["id"] for c in enlaces["cuentas"]):  # type: ignore[index,union-attr]
                enlaces["cuentas"].append(  # type: ignore[union-attr]
                    {
                        "id": str(fila.id),
                        "nombre": fila.nombre,
                        "tier": fila.tier,
                        "sector": "",
                        "alta": fila.created_at.isoformat(),
                    }
                )
                cuentas.append((fila.id, fila.nombre, fila.tier or "C", fila.created_at))

        contactos: list[tuple[UUID, UUID]] = []
        for i in range(vol.contactos):
            cuenta_id, empresa, _tier, alta_cuenta = cuentas[i % len(cuentas)]
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
                    # Plano dentro de la vida de SU cuenta, no sesgado otra vez
                    # hacia hoy: el sesgo aplicado dos veces amontonaba todo en
                    # los últimos años.
                    created_at=reloj.momento(rnd, desde=alta_cuenta, sesgo=1.0),
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
        ahora = reloj.hoy
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
        pendientes = 0
        for i in range(vol.actividades):
            cuenta_id, empresa, _t, alta_cuenta = cuentas[i % len(cuentas)]
            # Una parte pequeña vence en los próximos días: sin nada por
            # delante, la bandeja de «lo que me toca hoy» sale vacía el día de
            # la demostración, que es la primera pantalla que se enseña. Pero
            # sólo una parte pequeña: lo que hace falta ahí son unas decenas de
            # tareas, no una proporción de diez años de historia.
            if rnd.random() < 0.08:
                vence = ahora + timedelta(days=rnd.randrange(-4, 21), hours=rnd.randrange(24))
                # Hacia atrás desde HOY y no desde el vencimiento: restando del
                # vencimiento, las que vencen dentro de tres semanas se
                # apuntaban en el futuro.
                creada = ahora - timedelta(days=rnd.randrange(0, 26), hours=rnd.randrange(24))
            else:
                creada = reloj.momento(rnd, desde=alta_cuenta, sesgo=1.0)
                vence = creada + timedelta(days=rnd.randrange(1, 45))
            # Una tarea se apunta ANTES de vencer y nunca en el futuro.
            creada = min(creada, vence, ahora)
            # Lo pasado está hecho salvo un resto: un histórico sin ninguna
            # tarea olvidada no se parece a ninguna bandeja real.
            hecha = vence < ahora and rnd.random() < 0.88
            pendientes += 0 if hecha else 1
            svc.crear_actividad(
                uow,
                tipo=tipos[i % len(tipos)],
                asunto=f"{acciones[i % len(acciones)]} — {empresa.split(',')[0]}",
                objeto="cuenta",
                objeto_id=cuenta_id,
                vence_at=vence,
                estado="completada" if hecha else "pendiente",
                created_at=creada,
            )
        print(
            f"{vol.actividades} actividades creadas en {cfg.anios} años "
            f"({pendientes} siguen pendientes)"
        )

    return enlaces


def sembrar_sales(cfg: argparse.Namespace, tenant_id: UUID, vol: Volumen, enlaces: dict) -> None:
    """Catálogo, pipeline, leads, oportunidades con su historial, y lo que se vendió.

    Tres cosas que no estaban y que son la mitad de lo que se mira:

      · **El recorrido.** Una oportunidad ganada sin historial de etapas no
        dice cuánto tardó en cada una, y el informe de embudo —dónde se atasca
        la venta— no tiene de dónde salir.
      · **Lo que se ofreció.** Un importe de 180.000 € sin líneas no dice qué
        se vendió, y el margen por familia no se puede calcular.
      · **El pedido.** Una venta ganada que no acaba en pedido deja la pantalla
        de pedidos vacía en un sistema donde se han ganado trescientas.
    """
    _cambiar_a("sales")
    from datetime import timedelta
    from decimal import Decimal

    from crmcore.db.uow import unidad_de_trabajo
    from crmcore.errors import Conflicto as ConflictoCrm
    from crmcore.errors import ErrorValidacion
    from crmcore.tenancy.context import con_contexto
    from sqlalchemy import func, select

    from services.sales import presupuestos as svc_presupuestos
    from services.sales import servicio as svc
    from services.sales.catalogo import Producto
    from services.sales.modelos import CambioEtapa, Etapa, Lead, Oportunidad, Pipeline

    rnd = random.Random(f"{cfg.slug}:sales")
    reloj = Reloj(anios=cfg.anios)
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

        # Se cuenta lo que ya hay y se crea **lo que falta** hasta el volumen
        # pedido. Antes, con un solo registro el sembrado se daba por hecho y no
        # creaba nada: un tenant con las cuatro filas de la demo mínima no podía
        # crecer nunca, y con cuatro filas no se ve ni un embudo ni una cola.
        # Filtrado por tenant **a mano**. Sin el `where`, el corte miraba las
        # filas de TODOS los tenants de la base: al sembrar la segunda empresa
        # encontraba las de la primera, decía «ya hay» y se iba sin crear nada.
        # Y no fallaba: dejaba la empresa nueva con la pantalla vacía y un
        # mensaje tranquilizador.
        # El catálogo va primero: una oferta sin productos no se puede crear,
        # y el motor de precios es quien pone el precio —no quien llama—, así
        # que sin catálogo no hay con qué calcularlo.
        if (
            uow.db.execute(
                select(Producto).where(Producto.tenant_id == tenant_id).limit(1)
            ).scalar_one_or_none()
            is None
        ):
            for sku, nombre_p, familia, precio, coste, tipo_ing, periodicidad in PRODUCTOS_DEMO:
                uow.db.add(
                    Producto(
                        tenant_id=tenant_id,
                        sku=sku,
                        nombre=nombre_p,
                        familia=familia,
                        precio_base=Decimal(precio),
                        coste=Decimal(coste),
                        tipo_ingreso=tipo_ing,
                        periodicidad=periodicidad,
                        activo=True,
                    )
                )
            uow.db.flush()
            print(f"{len(PRODUCTOS_DEMO)} productos de catálogo creados")
        productos = {
            f.sku: f.id
            for f in uow.db.execute(select(Producto).where(Producto.tenant_id == tenant_id))
            .scalars()
            .all()
        }

        ya_leads = int(
            uow.db.execute(
                select(func.count()).select_from(Lead).where(Lead.tenant_id == tenant_id)
            ).scalar_one_or_none()
            or 0
        )
        if ya_leads >= vol.leads:
            print(f"Ya hay {ya_leads} leads: no hacen falta más.")
        else:
            for i in range(ya_leads, vol.leads):
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
                    # Repartidos en el periodo: todos de hoy dejaba el informe
                    # de captación por mes con una sola barra.
                    created_at=reloj.momento(rnd),
                )
            print(f"{vol.leads - ya_leads} leads creados")

        ya_oport = int(
            uow.db.execute(
                select(func.count())
                .select_from(Oportunidad)
                .where(Oportunidad.tenant_id == tenant_id)
            ).scalar_one_or_none()
            or 0
        )
        if ya_oport >= vol.oportunidades:
            print(f"Ya hay {ya_oport} oportunidades: no hacen falta más.")
        elif not cuentas:
            print("Sin fichero de enlace no se pueden atar oportunidades a cuentas: se omiten.")
        else:
            caminos = [e for e in abiertas]
            hechos = {"ofertas": 0, "aprobaciones": 0, "pedidos": 0, "descartadas": 0}
            for i in range(ya_oport, vol.oportunidades):
                cuenta = cuentas[i % len(cuentas)]
                titulo, minimo, maximo = PROYECTOS[i % len(PROYECTOS)]
                alta_cuenta = _fecha(cuenta.get("alta")) or reloj.desde
                # La oportunidad nace DESPUÉS que su cuenta y dentro del
                # periodo. Antes se sorteaba un desplazamiento sobre hoy, así
                # que una cartera de diez años tenía todo el embudo en los
                # últimos seis meses.
                abierta = reloj.momento(rnd, desde=alta_cuenta, sesgo=1.0)
                estado, pasos = reparto_de_embudo(rnd, len(caminos))
                importe = Decimal(rnd.randrange(minimo, maximo))
                duracion = rnd.randrange(15, 240)
                cierre = abierta + timedelta(days=duracion)
                oportunidad = svc.crear_oportunidad_nueva(
                    uow,
                    nombre=f"{titulo} — {cuenta['nombre'].split(',')[0]}",
                    cuenta_id=UUID(str(cuenta["id"])),
                    pipeline_id=pipeline.id,
                    importe=importe,
                    descripcion=f"{titulo} para {cuenta['nombre']}.",
                    fecha_cierre=cierre.date(),
                    created_at=abierta,
                    etapa_desde=abierta,
                )
                _recorrer_embudo(
                    uow,
                    CambioEtapa,
                    oportunidad=oportunidad,
                    camino=caminos,
                    ganada=ganada,
                    perdida=perdida,
                    estado=estado,
                    pasos=pasos,
                    abierta=abierta,
                    cierre=min(cierre, reloj.hoy),
                    motivo=rnd.choice(MOTIVOS_PERDIDA),
                )
                try:
                    _ofertar(
                        uow,
                        svc_presupuestos,
                        productos=productos,
                        oportunidad=oportunidad,
                        estado=estado,
                        abierta=abierta,
                        cierre=min(cierre, reloj.hoy),
                        lineas=lineas_de_oferta(rnd),
                        hechos=hechos,
                    )
                except (ConflictoCrm, ErrorValidacion) as error:
                    # Se dice, no se esconde: una oferta que el propio producto
                    # rechaza es información, y callarla dejaría la empresa con
                    # menos ofertas de las que el recuento dice.
                    hechos["descartadas"] += 1
                    print(f"  oferta descartada: {error}")
            print(
                f"{vol.oportunidades - ya_oport} oportunidades creadas con su historial; "
                f"{hechos['ofertas']} ofertas ({hechos['aprobaciones']} pasaron por aprobación) "
                f"y {hechos['pedidos']} pedidos"
                + (f"; {hechos['descartadas']} descartadas" if hechos["descartadas"] else "")
            )


def _fecha(valor: object):
    """Una fecha del fichero de enlace, o `None` si no venía."""
    from datetime import datetime

    if not isinstance(valor, str) or not valor:
        return None
    try:
        return datetime.fromisoformat(valor)
    except ValueError:
        return None


def _recorrer_embudo(
    uow,
    CambioEtapa,
    *,
    oportunidad,
    camino: list,
    ganada,
    perdida,
    estado: str,
    pasos: int,
    abierta,
    cierre,
    motivo: str,
) -> None:
    """Escribe por dónde pasó la oportunidad hasta donde está hoy.

    El historial se escribe aquí y no llamando a `cambiar_etapa` porque ese
    camino sella la fecha con `now()` y exige los criterios de salida: los dos
    están bien para el uso en vivo y los dos hacen imposible cargar histórico,
    que por definición nunca cumplió unos criterios que aún no existían. Lo que
    sí se respeta es la forma del apunte, para que las pantallas de duración por
    etapa y de deslizamiento lean lo mismo que leen de una venta real.
    """
    from datetime import timedelta

    # El apunte de nacimiento lo pone el servicio con `now()`; aquí se corrige a
    # la fecha real, porque la duración de la primera etapa se calcula restando
    # desde él y si no, sale de diez años.
    from sqlalchemy import select as _select

    primero = (
        uow.db.execute(_select(CambioEtapa).where(CambioEtapa.oportunidad_id == oportunidad.id))
        .scalars()
        .first()
    )
    if primero is not None:
        primero.created_at = abierta

    recorrido = camino if estado == "ganada" else camino[: max(1, pasos)]
    momento, anterior = abierta, camino[0].id
    for etapa in recorrido[1:]:
        dias = max(1, int((cierre - momento).days / max(1, len(recorrido))))
        siguiente = momento + timedelta(days=dias)
        uow.db.add(
            CambioEtapa(
                tenant_id=uow.tenant_id,
                oportunidad_id=oportunidad.id,
                etapa_desde_id=anterior,
                etapa_hasta_id=etapa.id,
                dias_en_etapa=dias,
                importe_en_cambio=oportunidad.importe,
                fecha_cierre_en_cambio=oportunidad.fecha_cierre,
                created_at=siguiente,
            )
        )
        oportunidad.etapa_id = etapa.id
        oportunidad.probabilidad = etapa.probabilidad
        oportunidad.etapa_desde = siguiente
        anterior, momento = etapa.id, siguiente

    if estado != "abierta":
        final = ganada if estado == "ganada" else perdida
        if final is None:
            return
        uow.db.add(
            CambioEtapa(
                tenant_id=uow.tenant_id,
                oportunidad_id=oportunidad.id,
                etapa_desde_id=anterior,
                etapa_hasta_id=final.id,
                dias_en_etapa=max(0, (cierre - momento).days),
                importe_en_cambio=oportunidad.importe,
                fecha_cierre_en_cambio=oportunidad.fecha_cierre,
                motivo=motivo if estado == "perdida" else "",
                created_at=cierre,
            )
        )
        oportunidad.etapa_id = final.id
        oportunidad.probabilidad = final.probabilidad
        oportunidad.etapa_desde = cierre
        oportunidad.estado = estado
        oportunidad.fecha_cierre_real = cierre.date()
        # Cerrada y bloqueada: una oportunidad cerrada no se edita, y una
        # demostración donde sí se puede enseña una regla que el producto no
        # tiene.
        oportunidad.bloqueada = True
        if estado == "perdida":
            oportunidad.motivo_perdida = motivo
    oportunidad.ultima_actividad_at = momento


def _ofertar(
    uow,
    svc_presupuestos,
    *,
    productos: dict,
    oportunidad,
    estado: str,
    abierta,
    cierre,
    lineas: list,
    hechos: dict,
) -> None:
    """La oferta de esta oportunidad y, si se ganó, su pedido.

    Se recorre el camino de verdad —`crear`, `enviar`, `aceptar`— y no se
    insertan filas a mano: es ese camino el que calcula los precios con el
    motor, decide si el descuento necesita aprobación y numera el pedido.
    Insertando a mano saldrían ofertas con precios que la aplicación nunca
    daría, y la demostración enseñaría números que el producto no produce.
    """
    from datetime import timedelta

    detalle = [
        {
            "producto_id": productos[linea["sku"]],
            "cantidad": linea["cantidad"],
            "descuento_pct": linea["descuento_pct"],
        }
        for linea in lineas
        if linea["sku"] in productos
    ]
    if not detalle:
        return

    presupuesto = svc_presupuestos.crear(
        uow,
        lineas=detalle,
        cuenta_id=oportunidad.cuenta_id,
        oportunidad_id=oportunidad.id,
        titulo=f"Oferta — {oportunidad.nombre}",
    )
    hechos["ofertas"] += 1
    svc_presupuestos.enviar(uow, presupuesto.id)
    if presupuesto.estado == "en_aprobacion":
        # El descuento pedía aprobación y la aplicación lo paró. Se aprueba y se
        # vuelve a mandar: así hay ofertas que pasaron por la matriz de
        # aprobación y queda constancia de por qué.
        hechos["aprobaciones"] += 1
        presupuesto.estado = "aprobado"
        uow.db.flush()
        svc_presupuestos.enviar(uow, presupuesto.id)

    presupuesto.created_at = abierta
    presupuesto.enviado_at = abierta + timedelta(days=2)
    # Y sus líneas con ella. Quedaban todas creadas hoy, así que un informe de
    # qué se vendió por año salía con el catálogo entero en el año en curso.
    # No hay relación declarada entre el presupuesto y sus líneas, así que se
    # piden: inventarse el atributo habría fallado en silencio.
    from sqlalchemy import select as _sel

    from services.sales.presupuestos import LineaPresupuesto as _Linea

    for linea in (
        uow.db.execute(_sel(_Linea).where(_Linea.presupuesto_id == presupuesto.id)).scalars().all()
    ):
        linea.created_at = abierta

    if estado == "ganada":
        # `aceptar` se niega si la oferta ha caducado, y la de una venta de 2019
        # caducó en 2019. Se le da vigencia para recorrer el camino de verdad y
        # luego se devuelve a su fecha: el pedido queda numerado y auditado por
        # la aplicación, no inventado aquí.
        from crmcore.fechas import hoy as _hoy

        valido = presupuesto.valido_hasta
        presupuesto.valido_hasta = _hoy(uow.db) + timedelta(days=1)
        uow.db.flush()
        pedido = svc_presupuestos.aceptar(uow, presupuesto.id)
        presupuesto.valido_hasta = valido
        presupuesto.aceptado_at = cierre
        pedido.created_at = cierre
        pedido.confirmado_at = cierre
        pedido.estado = "confirmado"
        hechos["pedidos"] += 1
    elif estado == "perdida":
        presupuesto.estado = "rechazado"


def sembrar_service(cfg: argparse.Namespace, tenant_id: UUID, vol: Volumen, enlaces: dict) -> None:
    """Taxonomía, SLA, colas y casos. Corre donde `service` tiene permisos."""
    _cambiar_a("service")
    from datetime import timedelta

    from crmcore.db.uow import unidad_de_trabajo
    from crmcore.tenancy.context import con_contexto
    from sqlalchemy import func, select

    from services.service.modelos import Caso, CategoriaCaso, DefinicionSLA
    from services.service.operacion import ColaCasos

    rnd = random.Random(f"{cfg.slug}:service")
    reloj = Reloj(anios=cfg.anios)
    cuentas = list(enlaces.get("cuentas") or [])

    with con_contexto(tenant_id=tenant_id, origen="cli"), unidad_de_trabajo(tenant_id) as uow:
        if (
            uow.db.execute(
                select(CategoriaCaso).where(CategoriaCaso.tenant_id == tenant_id).limit(1)
            ).scalar_one_or_none()
            is None
        ):
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

        if (
            uow.db.execute(
                select(DefinicionSLA).where(DefinicionSLA.tenant_id == tenant_id).limit(1)
            ).scalar_one_or_none()
            is None
        ):
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

        if (
            uow.db.execute(
                select(ColaCasos).where(ColaCasos.tenant_id == tenant_id).limit(1)
            ).scalar_one_or_none()
            is None
        ):
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

        ya_casos = int(
            uow.db.execute(
                select(func.count()).select_from(Caso).where(Caso.tenant_id == tenant_id)
            ).scalar_one_or_none()
            or 0
        )
        if ya_casos >= vol.casos:
            print(f"Ya hay {ya_casos} casos: no hacen falta más.")
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
        # El reparto de estados imita una cola real: la mayoría cerrada, una
        # minoría viva. Con todos abiertos no se puede medir nada —ni tiempo de
        # resolución ni reincidencia— y con todos cerrados la cola sale vacía.
        #
        # El reparto de los que siguen vivos. Cuáles están cerrados ya no se
        # sortea: lo decide la fecha, porque un caso de hace seis años cerrado
        # o no es lo que separa una cola creíble de una inventada.
        estados_vivos = (
            ["en_curso"] * 4 + ["esperando_cliente"] * 2 + ["asignado"] * 2 + ["nuevo"] * 2
        )
        horas_por_tier = {"A": 8, "B": 24, "C": 72}
        incumplidos = abiertos_vivos = 0
        casos_puestos: list[tuple[UUID, UUID, str, object, object]] = []
        for i in range(ya_casos, vol.casos):
            cuenta = cuentas[i % len(cuentas)]
            hoja = hojas[i % len(hojas)] if hojas else None
            tier = str(cuenta.get("tier") or "C")
            alta_cuenta = _fecha(cuenta.get("alta")) or reloj.desde
            # El caso nace DESPUÉS que su cliente y dentro del periodo. Antes se
            # repartían en los últimos 120 días, así que un sistema de diez años
            # tenía toda la postventa en el último trimestre y la comparación
            # con el año pasado no tenía con qué comparar.
            # Con reparto plano salían nueve casos vivos de ciento ochenta y
            # seis: la cola del día quedaba vacía, que es la primera pantalla
            # que abre quien atiende. No es un retoque estético — el volumen de
            # postventa sigue al parque instalado, y el parque crece, así que
            # los últimos años pesan más. El periodo entero sigue cubierto
            # porque el suelo es el alta de su cliente.
            abierto = reloj.momento(rnd, desde=alta_cuenta, sesgo=0.75)
            margen = timedelta(hours=horas_por_tier.get(tier, 72))
            vence = abierto + margen
            # Cuánto tardó, **medido en su propio SLA** y no en horas sueltas:
            # un cliente A con ocho horas de compromiso y un cierre a cuarenta
            # incumple siempre, y el panel salía en rojo por construcción.
            cerrado, factor_respuesta, factor_resolucion = reloj_de_caso(
                rnd, antiguo=(reloj.hoy - abierto) > timedelta(days=45)
            )
            resuelto_at = abierto + margen * factor_resolucion
            if not cerrado or resuelto_at > reloj.hoy:
                # Un caso no se cierra en el futuro: si el margen lo llevaría
                # más allá de hoy, sigue abierto, que es lo que de verdad pasa
                # con un caso reciente.
                estado, resuelto_at = estados_vivos[i % len(estados_vivos)], None
                tarde = reloj.hoy > vence
                abiertos_vivos += 1
            else:
                estado = "cerrado" if i % 4 else "resuelto"
                tarde = resuelto_at > vence
            if tarde and resuelto_at is not None:
                incumplidos += 1
            primera = min(abierto + margen * factor_respuesta, reloj.hoy)
            caso = Caso(
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
                vence_primera_respuesta_at=abierto + margen / 4,
                vence_resolucion_at=vence,
                primera_respuesta_at=primera,
                incumplio_primera_respuesta=primera > abierto + margen / 4,
                resuelto_at=resuelto_at,
                cerrado_at=resuelto_at if estado == "cerrado" else None,
                incumplio_resolucion=bool(tarde),
                created_at=abierto,
            )
            uow.db.add(caso)
            uow.db.flush()
            casos_puestos.append(
                (
                    caso.id,
                    UUID(str(cuenta["id"])),
                    caso.prioridad,
                    abierto,
                    caso.cerrado_at,
                )
            )
        print(
            f"{vol.casos - ya_casos} casos creados en {cfg.anios} años; "
            f"{incumplidos} fuera de plazo y {abiertos_vivos} todavía vivos"
        )

    _sembrar_campo(cfg, tenant_id, vol, cuentas, casos_puestos, reloj)


# ══════════════════════════════════════════════════════════════════════════


def _sembrar_campo(
    cfg: argparse.Namespace,
    tenant_id: UUID,
    vol: Volumen,
    cuentas: list,
    casos: list,
    reloj: Reloj,
) -> None:
    """Técnicos, parque instalado y órdenes de trabajo.

    Era la familia que no tenía **ni una sola fila**: el planificador, la
    agenda del técnico, el mapa de rutas y la ficha de un activo se abrían
    vacíos en un sistema con ochocientos casos. Y las órdenes cuelgan de un
    caso y de un activo del mismo cliente: sueltas no enseñan nada, porque lo
    que se mira en el servicio de campo es por qué hay que ir, a qué máquina y
    de quién es.
    """
    from datetime import timedelta
    from decimal import Decimal

    from crmcore.db.uow import unidad_de_trabajo
    from sqlalchemy import select

    from services.service import activos as svc_activos
    from services.service import campo as svc_campo
    from services.service.campo import Tecnico

    rnd = random.Random(f"{cfg.slug}:campo")

    with unidad_de_trabajo(tenant_id) as uow:
        if (
            uow.db.execute(
                select(Tecnico).where(Tecnico.tenant_id == tenant_id).limit(1)
            ).scalar_one_or_none()
            is not None
        ):
            print("Ya hay técnicos de campo: no se tocan.")
            return

        from services.identity.modelos import Membresia  # noqa: F401  (solo el id)

        # Los técnicos son usuarios del tenant, no una lista aparte: un técnico
        # que no es usuario no puede firmar un parte, y el servicio de campo
        # acabaría enseñando nombres que no existen en ningún otro sitio. Los
        # identificadores de usuario no se pueden leer desde aquí —otro
        # esquema—, así que se usa el del propio técnico como referencia: lo
        # que importa en esta pantalla es a quién se le asigna, y eso es la
        # fila de técnico.
        tecnicos = []
        for i in range(max(3, vol.cuentas // 8)):
            perfil = perfil_de_tecnico(rnd, i)
            fila = Tecnico(
                tenant_id=tenant_id,
                usuario_id=UUID(int=i + 1),
                nombre=f"{NOMBRES[(i * 3) % len(NOMBRES)]} {APELLIDOS[(i * 7) % len(APELLIDOS)]}",
                zonas=perfil["zonas"],
                competencias=perfil["competencias"],
                minutos_jornada=perfil["minutos_jornada"],
                activo=True,
            )
            uow.db.add(fila)
            tecnicos.append(fila)
        uow.db.flush()
        print(f"{len(tecnicos)} técnicos de campo dados de alta")

        por_cuenta: dict[UUID, list] = {}
        puestos = 0
        for i in range(vol.activos):
            cuenta = cuentas[i % len(cuentas)]
            cuenta_id = UUID(str(cuenta["id"]))
            alta = _fecha(cuenta.get("alta")) or reloj.desde
            datos = activo_instalado(rnd, reloj.momento(rnd, desde=alta, sesgo=1.0))
            activo, _avisos = svc_activos.crear(
                uow,
                nombre=datos["nombre"],
                modelo=datos["modelo"],
                numero_serie=datos["numero_serie"],
                cuenta_id=cuenta_id,
                ubicacion=datos["ubicacion"],
                instalado_el=datos["instalado_el"],
            )
            por_cuenta.setdefault(cuenta_id, []).append((activo.id, datos))
            puestos += 1

        ordenes = 0
        for i, (caso_id, cuenta_id, prioridad, abierto, cerrado) in enumerate(casos):
            # No todos los casos acaban en visita: un servicio donde cada
            # incidencia manda un técnico no existe, y la pantalla de «cuántas
            # se resuelven en remoto» saldría a cero.
            if i % 3 or cuenta_id not in por_cuenta:
                continue
            activo_id, datos_activo = por_cuenta[cuenta_id][i % len(por_cuenta[cuenta_id])]
            tecnico = tecnicos[i % len(tecnicos)]
            orden, _avisos = svc_campo.crear_orden(
                uow,
                titulo=f"Visita por caso {i + 1}",
                tipo="correctivo" if prioridad in ("alta", "critica") else "inspeccion",
                caso_id=caso_id,
                activo_id=activo_id,
                cuenta_id=cuenta_id,
                zona=datos_activo["zona"],
                prioridad=prioridad,
                competencias=list(tecnico.competencias)[:1],
                duracion_estimada_min=60 * (2 if prioridad == "critica" else 1),
                ventana_desde=abierto + timedelta(days=1),
                ventana_hasta=abierto + timedelta(days=4),
                # Sin coordenadas la orden no entra en la optimización de ruta,
                # y el planificador es justo lo que se enseña.
                latitud=Decimal("41.%06d" % ((i * 7919) % 1_000_000)),
                longitud=Decimal("2.%06d" % ((i * 104729) % 1_000_000)),
            )
            # `crear_orden` deja la orden en borrador y sin cita, que es lo
            # correcto cuando alguien la abre de verdad. Cargando histórico eso
            # deja diez años de órdenes esperando planificación, y el
            # planificador sale con mil trabajos sin asignar que nadie va a
            # hacer.
            cita = abierto + timedelta(days=2)
            orden.created_at = abierto
            orden.tecnico_id = tecnico.id
            orden.cita_desde = cita
            orden.cita_hasta = cita + timedelta(minutes=orden.duracion_estimada_min)
            orden.motivo_asignacion = "Zona y competencia, carga del día dentro de jornada"
            if cerrado:
                orden.estado = "cerrada"
                orden.iniciada_at = cita
                orden.completada_at = min(cerrado, cita + timedelta(hours=6))
                orden.cerrada_at = cerrado
                orden.firmado_por = "Responsable de planta"
                orden.firmado_at = cerrado
                orden.conforme = True
            elif cita < reloj.hoy:
                orden.estado = "en_curso"
                orden.iniciada_at = cita
            else:
                orden.estado = "planificada"
            ordenes += 1
        print(f"{puestos} activos instalados y {ordenes} órdenes de trabajo")


def sembrar_marketing(cfg: argparse.Namespace, tenant_id: UUID, vol: Volumen) -> None:
    """Programas y campañas con su presupuesto y su consumo.

    Otra familia que estaba a cero: la pantalla de campañas, la de consumo de
    presupuesto y la de atribución se abrían vacías. Las campañas cuelgan de un
    programa por año porque el presupuesto sube por la jerarquía: con todas
    sueltas, el consumo por programa sale vacío aunque haya cuarenta campañas.
    """
    _cambiar_a("marketing")
    from crmcore.db.uow import unidad_de_trabajo
    from crmcore.tenancy.context import con_contexto
    from sqlalchemy import select

    from services.marketing import campanas as svc_campanas
    from services.marketing.campanas import Campana

    rnd = random.Random(f"{cfg.slug}:marketing")
    reloj = Reloj(anios=cfg.anios)

    with con_contexto(tenant_id=tenant_id, origen="cli"):
        with unidad_de_trabajo(tenant_id) as uow:
            if (
                uow.db.execute(
                    select(Campana).where(Campana.tenant_id == tenant_id).limit(1)
                ).scalar_one_or_none()
                is not None
            ):
                print("Ya hay campañas: no se tocan.")
                return

        lista = campanas(rnd, reloj, vol.campanas_por_anio)
        programas: dict[int, UUID] = {}
        with unidad_de_trabajo(tenant_id) as uow:
            for anio in sorted({c["anio"] for c in lista}):
                from datetime import date as _date
                from datetime import datetime as _dt
                from datetime import timezone as _tz

                programa = svc_campanas.crear(
                    uow,
                    clave=f"plan-{anio}",
                    nombre=f"Plan de marketing {anio}",
                    nivel="programa",
                    desde=_date(anio, 1, 1),
                    hasta=_date(anio, 12, 31),
                    estado="finalizada" if anio < reloj.hoy.year else "activa",
                    created_at=min(_dt(anio, 1, 1, tzinfo=_tz.utc), reloj.hoy),
                )
                programas[anio] = programa.id

        with unidad_de_trabajo(tenant_id) as uow:
            for datos in lista:
                svc_campanas.crear(
                    uow,
                    clave=datos["clave"],
                    nombre=datos["nombre"],
                    nivel="campana",
                    padre_id=programas[datos["anio"]],
                    canal=datos["canal"],
                    tipo=datos["canal"],
                    desde=datos["inicio"].date(),
                    hasta=datos["fin"].date(),
                    presupuesto=datos["presupuesto"],
                    gasto=datos["gasto"],
                    estado="finalizada" if datos["fin"] < reloj.hoy else "activa",
                    created_at=min(datos["inicio"], reloj.hoy),
                )
        print(f"{len(programas)} programas y {len(lista)} campañas creadas")


# ══════════════════════════════════════════════════════════════════════════
#  Comprobar lo sembrado
# ══════════════════════════════════════════════════════════════════════════

# Lo que tiene que ser cierto, por servicio. Es **por servicio** y no una lista
# suelta porque cada parte corre donde tiene permisos: `sales` no puede mirar
# si un contacto nació antes que su cuenta, porque no ve el esquema de `party`.
# Pretender comprobarlo todo desde un sitio sólo funcionaría en local, que es
# justo donde no hace falta.
#
# Cada comprobación dice CUÁNTAS filas recorrió, no sólo cuántas fallaron: una
# consulta que no encuentra nada porque la tabla está vacía da cero fallos y
# parece verde. Las tres primeras veces que se ejecutó esto, el recorrido fue
# el dato que delató que faltaban datos.
COMPROBACIONES: dict[str, tuple[tuple[str, str, str], ...]] = {
    "party": (
        (
            "ningún contacto nace antes que su cuenta",
            "select count(*) from contacto_cuenta r join contactos k on k.id = r.contacto_id "
            "join cuentas c on c.id = r.cuenta_id "
            "where r.tenant_id = :t and k.created_at < c.created_at",
            "select count(*) from contacto_cuenta where tenant_id = :t",
        ),
        (
            "ninguna actividad se apunta en el futuro ni después de vencer",
            "select count(*) from actividades where tenant_id = :t "
            "and (created_at > now() or created_at > vence_at)",
            "select count(*) from actividades where tenant_id = :t",
        ),
        (
            # Sólo se exige cuando hay cartera con la que repartir: con seis
            # cuentas no se puede cubrir una década, y una comprobación que
            # falla por el tamaño que se pidió es una que se aprende a ignorar.
            "la cartera cubre el periodo y no un solo año",
            "select case when count(*) >= 12 "
            "and count(distinct extract(year from created_at)) < 3 then 1 else 0 end "
            "from cuentas where tenant_id = :t",
            "select count(*) from cuentas where tenant_id = :t",
        ),
        (
            "queda trabajo por delante en la agenda",
            "select case when count(*) = 0 then 1 else 0 end from actividades "
            "where tenant_id = :t and estado <> 'completada' and vence_at > now()",
            "select count(*) from actividades where tenant_id = :t",
        ),
    ),
    "sales": (
        (
            "ninguna oportunidad se crea ni se cierra en el futuro",
            "select count(*) from oportunidades where tenant_id = :t "
            "and (created_at > now() or fecha_cierre_real > current_date)",
            "select count(*) from oportunidades where tenant_id = :t",
        ),
        (
            "ningún cambio de etapa es anterior al alta de su oportunidad",
            "select count(*) from cambios_etapa h join oportunidades o on o.id = h.oportunidad_id "
            "where h.tenant_id = :t and h.created_at < o.created_at - interval '1 second'",
            "select count(*) from cambios_etapa where tenant_id = :t",
        ),
        (
            "el estado concuerda con la etapa",
            "select count(*) from oportunidades o join etapas e on e.id = o.etapa_id "
            "where o.tenant_id = :t and ((o.estado = 'abierta' and e.terminal) "
            "or (o.estado = 'ganada' and not e.ganada) "
            "or (o.estado = 'perdida' and not (e.terminal and not e.ganada)))",
            "select count(*) from oportunidades where tenant_id = :t",
        ),
        (
            "toda perdida dice por qué",
            "select count(*) from oportunidades where tenant_id = :t and estado = 'perdida' "
            "and coalesce(motivo_perdida, '') = ''",
            "select count(*) from oportunidades where tenant_id = :t and estado = 'perdida'",
        ),
        (
            # Con menos oportunidades vivas que el triple de etapas, que alguna
            # columna salga vacía es aritmética, no un defecto de los datos.
            "el embudo tiene gente en todas sus etapas no terminales",
            "select count(*) from etapas e where e.tenant_id = :t and not e.terminal "
            "and not exists (select 1 from oportunidades o where o.etapa_id = e.id) "
            "and (select count(*) from oportunidades o2 where o2.tenant_id = :t "
            "and o2.estado = 'abierta') >= 3 * (select count(*) from etapas e2 "
            "where e2.tenant_id = :t and not e2.terminal)",
            "select count(*) from etapas where tenant_id = :t and not terminal",
        ),
        (
            "toda oportunidad ganada acabó en pedido",
            "select count(*) from oportunidades o where o.tenant_id = :t and o.estado = 'ganada' "
            "and not exists (select 1 from presupuestos p join pedidos d "
            "on d.presupuesto_id = p.id where p.oportunidad_id = o.id)",
            "select count(*) from oportunidades where tenant_id = :t and estado = 'ganada'",
        ),
        (
            "ninguna oportunidad lleva dos ofertas",
            "select count(*) from (select oportunidad_id from presupuestos where tenant_id = :t "
            "group by 1 having count(*) > 1) x",
            "select count(*) from presupuestos where tenant_id = :t",
        ),
        (
            "ningún presupuesto se queda sin líneas",
            "select count(*) from presupuestos p where p.tenant_id = :t and not exists "
            "(select 1 from lineas_presupuesto l where l.presupuesto_id = p.id)",
            "select count(*) from presupuestos where tenant_id = :t",
        ),
    ),
    "service": (
        (
            "ningún caso se cierra antes de abrirse ni en el futuro",
            "select count(*) from casos where tenant_id = :t "
            "and (cerrado_at < created_at or cerrado_at > now())",
            "select count(*) from casos where tenant_id = :t",
        ),
        (
            "todo caso lleva su reloj de SLA",
            "select count(*) from casos where tenant_id = :t and vence_resolucion_at is null",
            "select count(*) from casos where tenant_id = :t",
        ),
        (
            "el incumplimiento coincide con las fechas",
            "select count(*) from casos where tenant_id = :t and cerrado_at is not null "
            "and incumplio_resolucion <> (cerrado_at > vence_resolucion_at)",
            "select count(*) from casos where tenant_id = :t and cerrado_at is not null",
        ),
        (
            "queda cola viva que atender",
            "select case when count(*) = 0 then 1 else 0 end from casos "
            "where tenant_id = :t and cerrado_at is null and resuelto_at is null",
            "select count(*) from casos where tenant_id = :t",
        ),
        (
            "toda orden es del mismo cliente que su caso y que su activo",
            "select count(*) from ordenes_trabajo o "
            "left join casos c on c.id = o.caso_id "
            "left join activos_instalados a on a.id = o.activo_id "
            "where o.tenant_id = :t and (o.cuenta_id is distinct from c.cuenta_id "
            "or o.cuenta_id is distinct from a.cuenta_id)",
            "select count(*) from ordenes_trabajo where tenant_id = :t",
        ),
        (
            "toda orden tiene técnico y cita, y no antes de su caso",
            "select count(*) from ordenes_trabajo o join casos c on c.id = o.caso_id "
            "where o.tenant_id = :t and (o.tecnico_id is null or o.cita_desde is null "
            "or o.cita_desde < c.created_at)",
            "select count(*) from ordenes_trabajo where tenant_id = :t",
        ),
    ),
    "marketing": (
        (
            "ninguna campaña cuelga del aire",
            "select count(*) from campanas where tenant_id = :t and nivel = 'campana' "
            "and padre_id is null",
            "select count(*) from campanas where tenant_id = :t and nivel = 'campana'",
        ),
        (
            "ninguna campaña se crea en el futuro",
            "select count(*) from campanas where tenant_id = :t and created_at > now()",
            "select count(*) from campanas where tenant_id = :t",
        ),
        (
            "ni todas gastan lo presupuestado ni todas se pasan",
            "select case when count(*) filter (where gasto > presupuesto) = 0 "
            "or count(*) filter (where gasto > 0 and gasto < presupuesto) = 0 then 1 else 0 end "
            "from campanas where tenant_id = :t and nivel = 'campana' and presupuesto is not null",
            "select count(*) from campanas where tenant_id = :t and nivel = 'campana'",
        ),
    ),
}


def comprobar(tenant_id: UUID, partes: tuple[str, ...]) -> int:
    """Recorre lo sembrado y dice si se sostiene. Devuelve cuántas cosas fallan."""
    from crmcore.db.uow import unidad_de_trabajo
    from crmcore.tenancy.context import con_contexto
    from sqlalchemy import text

    fallos = 0
    for parte in partes:
        comprobaciones = COMPROBACIONES.get(parte)
        if not comprobaciones:
            continue
        _cambiar_a(parte)
        print(f"\n{parte}:")
        with con_contexto(tenant_id=tenant_id, origen="cli"), unidad_de_trabajo(tenant_id) as uow:
            for titulo, sql_mal, sql_total in comprobaciones:
                mal = uow.db.execute(text(sql_mal), {"t": tenant_id}).scalar() or 0
                total = uow.db.execute(text(sql_total), {"t": tenant_id}).scalar() or 0
                if total == 0:
                    # Cero filas no es «todo bien»: es que no hay nada que
                    # mirar, y una pantalla vacía no enseña nada.
                    print(f"  SIN DATOS  {titulo} (0 filas recorridas)")
                    fallos += 1
                elif mal:
                    print(f"  MAL        {titulo}: {mal} de {total}")
                    fallos += 1
                else:
                    print(f"  bien       {titulo} ({total} filas recorridas)")
    return fallos


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
    parser.add_argument(
        "--anios",
        type=int,
        default=10,
        help="cuántos años de historia se siembran hacia atrás (por defecto, diez)",
    )
    parser.add_argument("--parte", default="todo")
    parser.add_argument(
        "--comprobar",
        action="store_true",
        help="no siembra: recorre lo sembrado y comprueba que se sostiene",
    )
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

    if cfg.anios < 1:
        print("«--anios» tiene que ser al menos 1.", file=sys.stderr)
        return 2
    vol = Volumen(cfg.escala, cfg.anios)

    if cfg.comprobar:
        if not cfg.tenant:
            print("Falta --tenant con el identificador de la empresa.", file=sys.stderr)
            return 2
        partes = tuple(COMPROBACIONES) if cfg.parte == "todo" else (cfg.parte,)
        fallos = comprobar(UUID(cfg.tenant), partes)
        if fallos:
            print(f"\n{fallos} {'comprobaciones' if fallos > 1 else 'comprobación'} mal.")
        else:
            print("\nTodo se sostiene.")
        return 1 if fallos else 0
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
        if cfg.parte == "service":
            return 0

    if cfg.parte in ("marketing", "todo"):
        sembrar_marketing(cfg, tenant_id, vol)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
