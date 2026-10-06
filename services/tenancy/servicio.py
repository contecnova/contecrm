"""Lógica del servicio de tenancy.

Aquí vive lo que responde a «¿existe, está operativo, qué puede usar y cuánto
lleva gastado?». Los routers de `api.py` solo traducen HTTP; toda la decisión
está en este módulo, que es lo que permite que la misma lógica la use un
consumidor del bus o un trabajo de fondo sin duplicarla.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from crmcore.audit.chain import registrar
from crmcore.datos.estados import Maquina, registrar_maquina
from crmcore.datos.estados import comprobar as comprobar_estado
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado, Prohibido
from crmcore.logging import get_logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.tenancy.modelos import FeatureFlag, Plan, Tenant, UnidadNegocio

logger = get_logger(__name__)

# Un slug va en subdominios y en URLs: se limita a lo que es válido en un nombre
# de host, y se prohíben los que colisionarían con subdominios de servicio.
RE_SLUG = re.compile(r"^[a-z0-9]([a-z0-9-]{1,61}[a-z0-9])?$")
SLUGS_RESERVADOS = frozenset(
    {"www", "api", "app", "admin", "gateway", "status", "docs", "mail", "smtp", "ns"}
)

# Estados y las transiciones permitidas. Se declara la máquina entera en vez de
# comprobar caso por caso: así se puede enseñar, y añadir un estado obliga a
# decir desde dónde se llega a él.
# La máquina de estados del tenant, declarada en el motor compartido
# (CRM-00.04.01.07). Estaba aquí como una tabla suelta con su comprobación a
# mano; pasarla al motor le da lo que le faltaba —restricción por tenant,
# auditoría automática de cada transición y el mismo mensaje de error que el
# resto del sistema— y evita que la siguiente máquina se escriba otra vez.
MAQUINA_TENANT = registrar_maquina(
    Maquina(
        objeto="tenant",
        inicial="activo",
        transiciones={
            "activo": frozenset({"suspendido", "solo_lectura", "en_baja"}),
            "suspendido": frozenset({"activo", "solo_lectura", "en_baja"}),
            "solo_lectura": frozenset({"activo", "suspendido", "en_baja"}),
            # De `en_baja` se puede volver: una baja por error tiene que ser
            # recuperable mientras los datos sigan ahí.
            "en_baja": frozenset({"activo", "archivado"}),
        },
        # `archivado` es terminal: los datos ya se han destruido.
        finales=frozenset({"archivado"}),
        # Todo lo que degrada el servicio exige motivo. Seis meses después,
        # «¿por qué está suspendido este cliente?» es una pregunta real, y sin
        # motivo escrito la respuesta se pierde con quien lo hizo.
        exigen_motivo=frozenset({"suspendido", "solo_lectura", "en_baja"}),
    )
)

# Se conserva para quien la importaba. Sale de la máquina, así que no puede
# desincronizarse de ella.
TRANSICIONES: dict[str, frozenset[str]] = dict(MAQUINA_TENANT.transiciones)


# ── Alta y ciclo de vida ──────────────────────────────────────────────────


def crear_tenant(
    uow: UnidadDeTrabajo,
    *,
    slug: str,
    nombre: str,
    plan: str = "base",
    region: str | None = None,
    aislamiento: str | None = None,
    tenant_padre_id: UUID | None = None,
    idioma: str = "es",
    zona_horaria: str = "Europe/Madrid",
    moneda: str = "EUR",
) -> Tenant:
    """Da de alta un tenant (CRM-00.01.03.01).

    **La región y el aislamiento no se escriben aquí: salen de la
    configuración.** Estaban a fuego en TRES sitios —el esquema de la API, esta
    firma y la columna del modelo— mientras `TENANT_DEFAULT_REGION` y
    `TENANT_DEFAULT_ISOLATION` existían, estaban documentados y no los leía
    nadie (medido el 06-10-2026).

    En el aislamiento eso era un ajuste decorativo; en la región es peor: el
    valor se guarda en el tenant **para poder auditar dónde vive cada dato**, y
    una instalación en otra región daba de alta a todos sus clientes diciendo
    que sus datos están en Europa. El dato de residencia no es un valor por
    defecto cualquiera: es el que se enseña cuando alguien pregunta.
    """
    from crmcore.config import get_settings

    s = get_settings()
    region = region or s.tenant_default_region
    aislamiento = aislamiento or s.tenant_default_isolation

    slug = slug.strip().lower()
    if not RE_SLUG.match(slug):
        raise ErrorValidacion(
            "El identificador debe tener entre 2 y 63 caracteres, en minúsculas, "
            "y solo letras, números o guiones (no al principio ni al final)",
            error_code="tenant.slug_invalido",
        )
    if slug in SLUGS_RESERVADOS:
        raise ErrorValidacion(
            f"«{slug}» está reservado para uso del sistema",
            error_code="tenant.slug_reservado",
        )
    if uow.db.execute(select(Tenant.id).where(Tenant.slug == slug)).first():
        raise Conflicto(
            "Ya existe un tenant con ese identificador",
            error_code="tenant.slug_duplicado",
        )

    if tenant_padre_id and not uow.db.get(Tenant, tenant_padre_id):
        raise NoEncontrado(
            "El tenant padre indicado no existe", error_code="tenant.padre_no_encontrado"
        )

    tenant = Tenant(
        slug=slug,
        nombre=nombre.strip(),
        plan=plan,
        region=region,
        aislamiento=aislamiento,
        tenant_padre_id=tenant_padre_id,
        idioma=idioma,
        zona_horaria=zona_horaria,
        moneda=moneda,
        estado="activo",
        provisionado_at=datetime.now(timezone.utc),
    )
    uow.db.add(tenant)
    # `flush` para tener el id antes de emitir el evento: el sobre lo lleva como
    # sujeto, y sin id el consumidor no sabría de qué tenant habla.
    uow.db.flush()

    # Las cuotas que vende el plan, puestas como ajustes del tenant. **Sin esto
    # el plan no acota nada**: lo que corta de verdad (`crmcore.cuotas.tope`) lee
    # los ajustes, y los ajustes no sabían del plan — así que un plan con 5.000
    # correos al mes dejaba pasar cincuenta mil. Medido: la única función que
    # miraba el plan sólo la usaban dos pantallas, y ninguna cortaba nada.
    #
    # Se materializan en vez de que cada lector consulte el plan: el plan vive en
    # el esquema de tenancy y los trece servicios no lo leen —ni deben—, mientras
    # que los ajustes ya se replican a todos.
    aplicar_cuotas_del_plan(uow.db, tenant.id, plan_codigo=plan)

    registrar(
        uow.db,
        accion="tenant.provisionado",
        objeto="tenant",
        objeto_id=tenant.id,
        datos={"slug": slug, "plan": plan, "region": region},
        tenant_id=tenant.id,
    )
    uow.emitir(
        "tenant.provisioned",
        subject=("tenant", tenant.id),
        data={
            "tenant_id": str(tenant.id),
            "slug": slug,
            "plan": plan,
            "region": region,
        },
    )
    logger.info("tenant.creado", slug=slug, plan=plan, region=region)
    return tenant


def cambiar_estado(
    uow: UnidadDeTrabajo, tenant_id: UUID, *, nuevo: str, motivo: str = ""
) -> Tenant:
    """Cambia el estado del tenant respetando la máquina de estados.

    Exige motivo para todo lo que degrada el servicio. No es burocracia: seis
    meses después, «¿por qué está suspendido este cliente?» es una pregunta
    real, y sin motivo escrito la respuesta se pierde con quien lo hizo.
    """
    tenant = uow.db.get(Tenant, tenant_id)
    if tenant is None:
        raise NoEncontrado("El tenant no existe", error_code="tenant.no_encontrado")

    if nuevo == tenant.estado:
        return tenant

    # El motor comprueba la transición, exige el motivo donde toca y aplica las
    # restricciones que haya puesto el tenant.
    comprobar_estado("tenant", desde=tenant.estado, hasta=nuevo, motivo=motivo, db=uow.db)

    anterior = tenant.estado
    tenant.estado = nuevo
    tenant.motivo_estado = motivo.strip() or None
    ahora = datetime.now(timezone.utc)
    if nuevo == "suspendido":
        tenant.suspendido_at = ahora
    elif nuevo == "en_baja":
        tenant.baja_solicitada_at = ahora
        # Se pide ya el inventario del corpus documental a todos los servicios
        # (RT-5): la ventana de recuperación da treinta días para que contesten,
        # y el certificado de destrucción se compone con sus respuestas. Pedirlo
        # en el momento de destruir no daría tiempo a nadie.
        from crmcore.documental.inventario import solicitar_inventario

        solicitar_inventario(uow.db, tenant_id=tenant.id, motivo="baja")
        # Ventana de recuperación antes de que los datos sean destruibles. Una
        # baja instantánea convierte un error administrativo en una pérdida
        # irreversible.
        tenant.datos_borrables_at = ahora + timedelta(days=30)
    elif nuevo == "activo":
        tenant.suspendido_at = None
        tenant.baja_solicitada_at = None
        tenant.datos_borrables_at = None

    registrar(
        uow.db,
        accion="tenant.estado_cambiado",
        objeto="tenant",
        objeto_id=tenant.id,
        datos={"desde": anterior, "hasta": nuevo},
        motivo=motivo or None,
        tenant_id=tenant.id,
    )
    if nuevo == "suspendido":
        uow.emitir(
            "tenant.suspended",
            subject=("tenant", tenant.id),
            data={"tenant_id": str(tenant.id), "motivo": motivo},
        )
    elif nuevo == "activo" and anterior in ("suspendido", "solo_lectura"):
        uow.emitir(
            "tenant.reactivated",
            subject=("tenant", tenant.id),
            data={"tenant_id": str(tenant.id)},
        )
    logger.info("tenant.estado", slug=tenant.slug, desde=anterior, hasta=nuevo)
    return tenant


def propagar_localizacion(db: Session, tenant: Tenant, cambios: dict[str, Any]) -> None:
    """Lleva idioma, huso y moneda del perfil a los ajustes, que es lo que se lee.

    **Estaban desconectados.** `Tenant.zona_horaria` lo ponía el administrador en
    el perfil y **no lo leía nadie**: el formateo y los cálculos de fecha van por
    `rt.efectivo("zona_horaria")`, que nadie rellenaba, así que caía a UTC. Un
    cliente configuraba su huso y el producto seguía en el del servidor.

    Se propaga al cambiar y no se lee del tenant en cada consulta porque el
    ajuste tiene su propia cadena —usuario → unidad → tenant → global—, y un
    usuario puede tener el suyo: leer el del tenant directamente se saltaría la
    preferencia de la persona, que es justo lo que el ajuste existe para
    respetar.
    """
    from crmcore.runtime import settings as rt

    for campo, clave in (
        ("zona_horaria", "zona_horaria"),
        ("idioma", "idioma"),
        ("moneda", "moneda_funcional"),
    ):
        if campo not in cambios or not cambios[campo]:
            continue
        rt.fijar(db, clave, cambios[campo], ambito="tenant", ambito_id=str(tenant.id))


def operatividad(db: Session, tenant_id: UUID) -> dict[str, Any]:
    """Si este tenant puede leer y escribir, y por qué no.

    Devuelve el estado en vez de lanzar porque **el gateway lo cachea**: una
    llamada a tenancy por cada petición de la API sería doblar la latencia de
    todo el sistema. Quien decide sigue siendo esta capa —la regla de qué estado
    permite qué vive aquí y en un solo sitio—; el gateway sólo la aplica.
    """
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise NoEncontrado("El tenant no existe", error_code="tenant.no_encontrado")
    return {
        "estado": tenant.estado,
        "puede_leer": tenant.puede_leer,
        "puede_escribir": tenant.puede_escribir,
        "motivo": tenant.motivo_estado or "",
    }


def exigir_operativo(db: Session, tenant_id: UUID, *, escritura: bool) -> Tenant:
    """Comprueba que el tenant puede operar.

    **Esta función existía desde el principio y no la llamaba nadie**, mientras
    su propia documentación decía que «lo llama el gateway en cada petición». No
    era verdad: el 28-09-2026 se montó el caso y un tenant SUSPENDIDO creó una
    cuenta —201—, y uno en solo lectura también. La suspensión y la ventana de
    mantenimiento existían en la tabla y en ningún sitio más.

    Ahora la aplica el gateway sobre `operatividad`, con caché corta. Esta sigue
    aquí para quien tenga la sesión delante y quiera el objeto.

    El estado `solo_lectura` es lo que hace posible una ventana de mantenimiento
    sin corte (CRM-08.02.01.03): quien consulta sigue trabajando y quien escribe
    recibe un 409 que dice qué pasa, en vez de un error genérico o una pantalla
    que no responde.

    Se separan lectura y escritura porque el estado `solo_lectura` es la razón
    de ser de esta función: permite cortar las escrituras sin cortar el acceso.
    """
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise NoEncontrado("El tenant no existe", error_code="tenant.no_encontrado")
    if not tenant.puede_leer:
        from crmcore.errors import TenantSuspendido

        raise TenantSuspendido(
            f"El servicio está suspendido: {tenant.motivo_estado or 'contacta con soporte'}",
            error_code="tenant.suspendido",
        )
    if escritura and not tenant.puede_escribir:
        from crmcore.errors import SoloLectura

        raise SoloLectura(
            f"El servicio está en solo lectura: {tenant.motivo_estado or 'contacta con soporte'}",
            error_code="tenant.solo_lectura",
        )
    return tenant


# ── Planes, capacidades y flags ───────────────────────────────────────────


def capacidades_de(db: Session, tenant_id: UUID) -> dict[str, bool]:
    """Capacidades activas del tenant según su plan."""
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise NoEncontrado("El tenant no existe", error_code="tenant.no_encontrado")
    plan = db.execute(select(Plan).where(Plan.codigo == tenant.plan)).scalar_one_or_none()
    return dict(plan.capacidades) if plan else {}


def exigir_capacidad(db: Session, tenant_id: UUID, capacidad: str) -> None:
    """Lanza si el plan del tenant no incluye la capacidad."""
    if not capacidades_de(db, tenant_id).get(capacidad, False):
        raise Prohibido(
            f"Tu plan no incluye «{capacidad}»",
            error_code="plan.capacidad_no_incluida",
            # Se dice qué falta: el usuario ya sabe qué intentó, y sin el nombre
            # de la capacidad no puede ni preguntar por ella a comercial.
            detalle={"capacidad": capacidad},
        )


def flag_activo(
    db: Session, clave: str, *, tenant_id: UUID | None = None, user_id: UUID | None = None
) -> bool:
    """Resuelve un feature flag: usuario > tenant > global.

    El despliegue por porcentaje reparte por **hash** del identificador y no al
    azar: si fuera aleatorio, a un mismo usuario le aparecería y desaparecería la
    funcionalidad entre dos peticiones, que es la peor forma de probar algo.
    """
    candidatos = [
        (FeatureFlag.user_id == user_id) if user_id else None,
        (FeatureFlag.tenant_id == tenant_id) if tenant_id else None,
    ]
    for condicion in [c for c in candidatos if c is not None]:
        flag = db.execute(
            select(FeatureFlag).where(FeatureFlag.clave == clave, condicion)
        ).scalar_one_or_none()
        if flag is not None:
            return _resuelve_flag(flag, tenant_id, user_id)

    global_ = db.execute(
        select(FeatureFlag).where(
            FeatureFlag.clave == clave,
            FeatureFlag.tenant_id.is_(None),
            FeatureFlag.user_id.is_(None),
        )
    ).scalar_one_or_none()
    return _resuelve_flag(global_, tenant_id, user_id) if global_ else False


def _resuelve_flag(flag: FeatureFlag, tenant_id: UUID | None, user_id: UUID | None) -> bool:
    if flag.activo:
        return True
    if flag.porcentaje <= 0:
        return False
    if flag.porcentaje >= 100:
        return True
    semilla = f"{flag.clave}:{user_id or tenant_id or ''}"
    cubeta = int(hashlib.sha256(semilla.encode()).hexdigest()[:8], 16) % 100
    return cubeta < flag.porcentaje


# ── Cuotas y medición ─────────────────────────────────────────────────────


# ── Lo que se quitó aquí, y por qué ───────────────────────────────────────
#
# Vivían aquí `medir`, `consumo_actual` y `comprobar_cuota`: una segunda forma de
# llevar las cuotas, por contadores en la tabla `consumos`. **No la llamaba
# nadie**, así que la tabla estaba siempre vacía — y sus dos únicos lectores, el
# panel de consumo del cliente y el componente de estado de la plataforma,
# enseñaban cero de todo con los topes bien puestos al lado. «Has usado 0 de
# 5.000 correos» el mes que mandaste cuatro mil, y una página de estado que no
# podía avisar de una cuota agotada ni queriendo.
#
# La forma que SÍ funciona —y la que corta de verdad— cuenta las filas
# (`crmcore.cuotas.exigir` con su `contar`, y los medidores de
# `crmcore.consumo`). Es mejor por un motivo concreto: un contador aparte se
# desincroniza el primer día que algo se borra por otra vía —una purga, una
# fusión, una baja— y entonces el cliente ve una cuota agotada que no se
# corresponde con lo que tiene.
#
# Dos implementaciones de la misma regla es lo que este repositorio se dedica a
# quitar, así que se queda una. La tabla `consumos` no se borra aquí: eso es una
# migración y va aparte; vacía no molesta a nadie.


def aplicar_cuotas_del_plan(
    db: Session, tenant_id: UUID, *, plan_codigo: str, por: UUID | None = None
) -> dict[str, Any]:
    """Escribe las cuotas del plan como ajustes de este tenant.

    **Lo que ya tenga puesto a mano NO se pisa.** Un cliente al que se le subió
    el tope por una negociación no puede perderlo porque alguien le reasigne el
    mismo plan: el ajuste del tenant manda sobre el plan, y aquí se respeta ese
    orden en vez de confiar en que nadie vuelva a pulsar el botón.
    """
    from crmcore.tenancy.context import con_contexto, contexto_actual

    plan = db.execute(select(Plan).where(Plan.codigo == plan_codigo)).scalar_one_or_none()
    if plan is None:
        return {"plan": plan_codigo, "aplicadas": [], "porque": "ese plan no existe"}

    # **En el contexto del tenant al que se le aplican.** Provisionar ocurre
    # fuera de cualquier tenant —todavía no existe cuando empieza—, y fijar un
    # ajuste deja un apunte de auditoría que exige saber de quién es. Sin esto,
    # `fijar` escribía la fila y REVENTABA después, dejando el ajuste puesto, la
    # caché sin invalidar y a quien llamaba creyendo que no se había aplicado
    # nada: medido, salían cero cuotas aplicadas con las filas ya en la base.
    #
    # Y el apunte queda donde tiene que quedar: en el tenant cuyo tope cambia.
    if contexto_actual().tenant_id == tenant_id:
        return _aplicar_cuotas(db, plan, tenant_id, por)
    with con_contexto(tenant_id=tenant_id, origen="provisionado"):
        return _aplicar_cuotas(db, plan, tenant_id, por)


def _aplicar_cuotas(db: Session, plan: Plan, tenant_id: UUID, por: UUID | None) -> dict[str, Any]:
    from crmcore.runtime import settings as rt

    plan_codigo = plan.codigo

    # Lo que este tenant ya tenga puesto **en su propio ámbito**. No vale
    # preguntar por el valor efectivo: ése cae al valor de serie del despliegue y
    # siempre devuelve algo, así que la guarda no habría respetado nada — habría
    # saltado todas las cuotas y el plan no se habría aplicado nunca. Medido: con
    # `efectivo` no se aplicaba ni una.
    propios = rt._valores_de_ambito(db, "tenant", str(tenant_id))

    puestas: list[str] = []
    respetadas: list[str] = []
    for clave, valor in (plan.cuotas or {}).items():
        if clave in propios:
            respetadas.append(clave)
            continue
        try:
            rt.fijar(db, clave, int(valor), ambito="tenant", ambito_id=str(tenant_id), por=por)
        except Exception as exc:  # noqa: BLE001 — una cuota mal declarada no impide el alta
            logger.warning(
                "tenant.cuota_del_plan_no_aplicada",
                plan=plan_codigo,
                clave=clave,
                error=str(exc)[:200],
            )
            continue
        puestas.append(clave)

    logger.info("tenant.cuotas_del_plan", plan=plan_codigo, puestas=len(puestas))
    return {
        "plan": plan_codigo,
        "aplicadas": sorted(puestas),
        # Las que ya tenían valor propio y no se tocan, dichas: si no, quien
        # reasigna el plan cree que ha dejado al cliente con los topes del plan.
        "respetadas": sorted(respetadas),
    }


# `limite_de` vivía aquí: resolvía el tope mirando el ajuste del tenant y, si no
# había, el plan contratado. Se ha quedado redundante por el arreglo de arriba —
# las cuotas del plan se materializan como ajustes al provisionar, así que
# `rt.efectivo` ya las incluye y no hace falta un segundo resolutor que consulte
# el plan. Tener dos era, además, lo que escondía el agujero: el que miraba el
# plan sólo lo usaban dos pantallas, y el que corta de verdad no lo miraba.


def crear_unidad(
    db: Session, tenant_id: UUID, *, codigo: str, nombre: str, padre_id: UUID | None = None
) -> UnidadNegocio:
    if db.execute(
        select(UnidadNegocio.id).where(
            UnidadNegocio.tenant_id == tenant_id, UnidadNegocio.codigo == codigo
        )
    ).first():
        raise Conflicto(
            "Ya existe una unidad de negocio con ese código",
            error_code="unidad.codigo_duplicado",
        )
    unidad = UnidadNegocio(
        tenant_id=tenant_id, codigo=codigo.strip(), nombre=nombre.strip(), padre_id=padre_id
    )
    db.add(unidad)
    # Volcado antes de devolverla: los valores por defecto (id, fechas) los pone
    # SQLAlchemy en el flush, y quien la serializa corre ANTES del commit. Sin
    # esto, la respuesta sale con `id: null` y un 500 al validarla.
    db.flush()
    return unidad
