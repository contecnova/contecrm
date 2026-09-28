"""Gobierno único de la suite: un solo sitio para el tenant, los usuarios, los
roles y la organización de contecrm, contecmind y contecintelligence
(CRM-00.01.07).

contecrm ya depende de contecmind (corpus documental, RT-5) y de
contecintelligence (explotación, RT-4). Hoy el tenant, los usuarios y la
organización se configuran **tres veces, a mano, en tres sitios**, y ese es el
sitio por donde se rompe: alguien entra en el CRM y no en el gestor documental;
alguien se va de la empresa y conserva el acceso a los informes; un departamento
se reorganiza en uno y no en los otros, y los permisos dejan de coincidir sin que
nadie lo vea.

La regla, y de ella sale todo lo demás: **contecrm es la fuente y las demás son
réplicas**. Un único punto de administración, empuje automático y reconciliación
que enseñe lo que ha divergido.

Cuatro decisiones que gobiernan el módulo:

**La baja pesa más que el alta, y va primero en la cola.** Un alta que tarda es
una molestia: la persona llama y alguien lo mira. Una baja que tarda es una
puerta abierta que no ve nadie. Por eso el desaprovisionamiento tiene prioridad
sobre todo lo demás y por eso su fallo sale a cuarentena visible, nunca a un log.

**El orden se garantiza por sujeto, no en general.** Dos cambios sobre personas
distintas pueden aplicarse en cualquier orden; dos sobre la misma, no. Aplicar el
alta después de la baja —que es lo que pasa con reintentos y entrega
at-least-once— deja al que se fue dentro, y el sistema diría que todo fue bien.

**Un empuje que falla en silencio deja el problema peor que no tener empuje**,
porque entonces nadie mira. De ahí que el estado de cada objeto en cada
herramienta se guarde, se compare y se enseñe.

**Lo genérico es el suelo.** Un transporte declarativo —dirección, credencial,
mapeo de campos y de roles— cubre cualquier herramienta sin escribir código; los
conectores nativos van **encima**, solo para lo que el genérico no alcanza.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from crmcore.audit import registrar
from crmcore.db.base import Base, TimestampMixin
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

logger = get_logger(__name__)

# Objetos que se gobiernan desde aquí. Cerrado a propósito: cada uno tiene su
# forma canónica y su traducción por herramienta, y una lista abierta acabaría
# empujando cualquier cosa sin que nadie hubiera pensado qué significa allí.
OBJETOS = ("tenant", "usuario", "unidad")

# Estados de una fila de sincronización. `cuarentena` es el importante: lo que no
# se puede aplicar no se reintenta para siempre ni se olvida — se aparta y se
# enseña, que es lo único que hace que alguien lo arregle.
ESTADOS = ("pendiente", "aplicado", "fallido", "cuarentena", "divergente")


class HerramientaConectada(Base, TimestampMixin):
    """Una herramienta de la suite conectada a este tenant.

    `tipo` distingue el transporte genérico del conector nativo. El genérico es
    el suelo obligatorio —cualquier herramienta funciona declarando dirección,
    credencial y mapeos, sin escribir código—; el nativo va encima y solo para lo
    que el genérico no alcanza. Al revés, cada cliente con una herramienta
    distinta sería una versión del producto.
    """

    __tablename__ = "herramientas_conectadas"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    # Nombre con el que se la conoce aquí: `contecmind`, `contecintelligence`, o
    # el que el cliente le dé a una herramienta suya.
    nombre: Mapped[str] = mapped_column(String(60), nullable=False)
    tipo: Mapped[str] = mapped_column(String(30), nullable=False, default="generico")
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    base_url: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    # Credenciales cifradas. En claro serían la llave de administración de otra
    # herramienta guardada en una tabla que consulta media aplicación.
    credenciales: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    # Identificador del tenant EN esa herramienta. Se guarda y no se deduce del
    # slug: deducirlo convertiría un control en una convención, y el día que el
    # cliente renombre algo allí, el empuje iría a la organización de otro.
    identificador_externo: Mapped[str] = mapped_column(String(200), nullable=False, default="")

    # Correspondencia entre roles de aquí y roles de allí (CRM-00.01.07.04). Es
    # dato y no código: el mismo usuario es «director comercial» aquí, «editor»
    # en el gestor documental y «analista» en el de informes, y eso lo decide
    # cada cliente.
    mapeo_roles: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # Y entre campos, para el transporte genérico: qué nombre tiene allí cada
    # cosa de aquí.
    mapeo_campos: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # VALORES CONSTANTES que la herramienta exige en toda carga y que **no son
    # un dato del objeto que se empuja, sino de la conexión**.
    #
    # El caso que lo destapó: dar de alta una organización en contecmind exige
    # `app_id` —qué aplicación la nombra—, y eso no es un campo del tenant. El
    # mapeo sabe renombrar `nombre` a `name`, pero no puede inventarse un campo
    # que no existe en el origen, así que el alta salía sin él y se comía un
    # 422. Y no se puede resolver con un conector propio para contecmind: eso es
    # justo lo que esta arquitectura evita.
    #
    # Se guardan ya con el nombre de ALLÍ, porque son suyos: no pasan por el
    # mapeo. Y no van en `credenciales` aunque se configuren a la vez: aquello
    # se cifra y no se enseña, y esto se enseña en la pantalla de la conexión
    # para que se pueda corregir.
    campos_fijos: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # Qué objetos se empujan a esta herramienta. Un gestor documental puede
    # querer usuarios y unidades pero no el plan comercial.
    objetos: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)

    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="pendiente")
    ultimo_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    verificada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("tenant_id", "nombre", name="uq_herramienta_tenant"),)


class SincronizacionSuite(Base, TimestampMixin):
    """Estado de un objeto en una herramienta: lo que se quiere y lo aplicado.

    Guardar las dos huellas —la deseada y la aplicada— es lo que convierte
    «creo que está sincronizado» en una comparación. Con solo un sello de tiempo,
    un empuje que falló y otro que nunca se intentó se parecen demasiado.
    """

    __tablename__ = "sincronizaciones_suite"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    herramienta: Mapped[str] = mapped_column(String(60), nullable=False)
    objeto: Mapped[str] = mapped_column(String(20), nullable=False)
    objeto_id: Mapped[str] = mapped_column(String(80), nullable=False)
    # alta | baja | actualizacion. La baja se distingue porque tiene prioridad y
    # porque su fallo es más grave: un alta que tarda es una molestia, una baja
    # que tarda es una puerta abierta.
    operacion: Mapped[str] = mapped_column(String(20), nullable=False, default="alta")

    hash_deseado: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    hash_aplicado: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    # Lo que se quiere que esté allí, ya traducido. Se guarda para poder
    # reintentar sin recalcular y para poder enseñar exactamente qué se mandó.
    carga: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    identificador_externo: Mapped[str | None] = mapped_column(String(200), nullable=True)

    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="pendiente")
    intentos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ultimo_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    reintentar_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    aplicado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "herramienta", "objeto", "objeto_id", name="uq_sincronizacion_suite"
        ),
        Index("ix_sincronizacion_pendientes", "tenant_id", "estado", "operacion"),
    )


class AplicacionSuite(Base):
    """Cada intento de aplicar algo en una herramienta (CRM-00.01.07.12).

    Es la auditoría transversal: un solo sitio que dice quién cambió qué y en qué
    herramienta acabó aplicándose. Sin ella, contestar «¿por qué este usuario
    sigue entrando en el gestor documental?» obliga a mirar tres registros de
    auditoría distintos y a cruzarlos de memoria.
    """

    __tablename__ = "aplicaciones_suite"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    herramienta: Mapped[str] = mapped_column(String(60), nullable=False)
    objeto: Mapped[str] = mapped_column(String(20), nullable=False)
    objeto_id: Mapped[str] = mapped_column(String(80), nullable=False)
    operacion: Mapped[str] = mapped_column(String(20), nullable=False)
    resultado: Mapped[str] = mapped_column(String(20), nullable=False)
    detalle: Mapped[str | None] = mapped_column(Text, nullable=True)
    origen: Mapped[str] = mapped_column(String(40), nullable=False, default="contecrm")
    por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_aplicaciones_suite", "tenant_id", "objeto", "objeto_id", "created_at"),
    )


# ── Identidad única del tenant (CRM-00.01.07.01) ──────────────────────────


def identidad_de_tenant(db: Session, tenant_id: UUID) -> dict[str, Any]:
    """Los datos del tenant tal como los ve toda la suite.

    Un único identificador y unos únicos datos: el `slug` es el nombre estable
    —va en subdominios y en URLs, y no se puede cambiar— y el identificador
    opaco es el que se cita entre herramientas. Dos herramientas con dos nombres
    distintos para el mismo cliente es como empieza el trabajo manual de
    conciliar, y ya no para.
    """
    from services.tenancy.modelos import Tenant

    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise NoEncontrado("El tenant no existe", error_code="suite.tenant_no_encontrado")
    return {
        "id": str(tenant.id),
        "slug": tenant.slug,
        "nombre": tenant.nombre,
        "estado": tenant.estado,
        "region": tenant.region,
        "plan": tenant.plan,
        "tier": tenant.tier,
    }


def organizacion_de_tenant(db: Session, tenant_id: UUID) -> list[dict[str, Any]]:
    """Áreas y departamentos del tenant, en forma canónica (CRM-00.01.07.05).

    Se define **una vez** aquí y cada herramienta la recibe en su propia forma.
    Definirla en tres sitios garantiza que a los tres meses son tres árboles
    distintos, y entonces los permisos que cuelgan de ellos dejan de coincidir
    sin que nadie lo haya cambiado a propósito.

    Va plana y con el padre dentro, no anidada: un árbol anidado obliga a cada
    consumidor a recorrerlo, y la mitad de las herramientas quieren la lista.
    """
    from services.tenancy.modelos import UnidadNegocio

    filas = (
        db.execute(
            select(UnidadNegocio)
            .where(UnidadNegocio.tenant_id == tenant_id)
            .order_by(UnidadNegocio.codigo)
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(f.id),
            "codigo": f.codigo,
            "nombre": f.nombre,
            "padre": str(f.padre_id) if f.padre_id else None,
            "activa": f.activa,
        }
        for f in filas
    ]


# ── Mapeo de roles por herramienta (CRM-00.01.07.04) ──────────────────────

# Rol al que cae quien no tiene ninguna correspondencia. Vacío significa «sin
# acceso», y es el valor correcto por defecto: si un rol sin mapear concediera
# el rol básico, crear un rol nuevo en el CRM daría acceso a las otras
# herramientas sin que nadie lo hubiera decidido.
SIN_MAPEO = ""


def rol_en(herramienta: HerramientaConectada, roles: list[str]) -> str:
    """El rol que le toca a este usuario en esa herramienta.

    El mapeo es **dato**: el mismo usuario es «director comercial» aquí,
    «editor» en el gestor documental y «analista» en el de informes. Programarlo
    obligaría a tocar el producto cada vez que un cliente inventa un rol, que es
    todas las semanas.

    Cuando encajan varios, gana **el de mayor precedencia declarada** y no el
    primero: un usuario con dos roles no puede recibir un permiso distinto según
    el orden en que estén guardados sus roles, que es lo que pasaría al coger el
    primero.
    """
    mapeo = herramienta.mapeo_roles or {}
    equivalencias = mapeo.get("roles") or {}
    precedencia = [str(r) for r in (mapeo.get("precedencia") or [])]

    candidatos = [str(equivalencias[r]) for r in roles if r in equivalencias]
    if not candidatos:
        return str(mapeo.get("por_defecto") or SIN_MAPEO)
    if not precedencia:
        # Sin precedencia declarada no se adivina: se ordena de forma estable
        # para que al menos el resultado sea reproducible, y se deja constancia
        # de que hace falta declararla.
        if len(set(candidatos)) > 1:
            logger.warning(
                "suite.precedencia_sin_declarar",
                herramienta=herramienta.nombre,
                candidatos=sorted(set(candidatos)),
            )
        return sorted(candidatos)[0]
    return min(candidatos, key=lambda r: precedencia.index(r) if r in precedencia else 10_000)


# ── Estado deseado ────────────────────────────────────────────────────────


def _huella(carga: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(carga, sort_keys=True, default=str).encode()).hexdigest()


def _traducir(herramienta: HerramientaConectada, carga: dict[str, Any]) -> dict[str, Any]:
    """Renombra los campos según el mapeo declarado de la herramienta.

    Es lo que permite que el transporte genérico sirva para cualquiera: la
    herramienta que llama `display_name` a lo que aquí es `nombre` se configura,
    no se programa.
    """
    mapeo = herramienta.mapeo_campos or {}
    traducida = {str(mapeo.get(k, k)): v for k, v in carga.items()} if mapeo else dict(carga)
    # LOS CAMPOS FIJOS NO SE APLICAN AQUÍ, y es deliberado. Aquí se compone lo
    # que se ENCOLA, y un valor de la conexión metido en la fila se queda
    # congelado con ella. El caso real: montas la integración, el alta falla
    # porque falta `app_id`, lo configuras… y la cola sigue fallando para
    # siempre, porque las filas pendientes llevan la carga vieja. Quien lo mire
    # concluirá que configurarlo no sirve de nada.
    #
    # Se aplican al ENVIAR, en el conector, que es donde se sabe con qué
    # conexión se está hablando en ese momento. Así corregir la configuración
    # arregla también lo que ya estaba en la cola.
    return traducida


def carga_de_usuario(
    db: Session, herramienta: HerramientaConectada, usuario: dict[str, Any]
) -> dict[str, Any]:
    """Lo que se le manda a la herramienta sobre un usuario."""
    base = {
        "id_externo": usuario["id"],
        "email": usuario["email"],
        "nombre": usuario.get("nombre") or usuario["email"],
        "activo": bool(usuario.get("activa", True)),
        "rol": rol_en(herramienta, list(usuario.get("roles") or [])),
        "unidad": usuario.get("unidad"),
    }
    return _traducir(herramienta, base)


def herramientas(
    db: Session, tenant_id: UUID, *, solo_activas: bool = True
) -> list[HerramientaConectada]:
    consulta = select(HerramientaConectada).where(HerramientaConectada.tenant_id == tenant_id)
    if solo_activas:
        consulta = consulta.where(HerramientaConectada.activa.is_(True))
    return list(db.execute(consulta.order_by(HerramientaConectada.nombre)).scalars().all())


def _herramienta(db: Session, tenant_id: UUID, nombre: str) -> HerramientaConectada:
    fila = db.execute(
        select(HerramientaConectada).where(
            HerramientaConectada.tenant_id == tenant_id,
            HerramientaConectada.nombre == nombre,
        )
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado(
            f"«{nombre}» no está conectada a este tenant",
            error_code="suite.herramienta_no_conectada",
        )
    return fila


# ── Cola de aprovisionamiento (CRM-00.01.07.10) ───────────────────────────

# Prioridad de operación. La baja va primero **siempre**: un alta que tarda es
# una molestia que alguien reporta; una baja que tarda es una puerta abierta que
# no ve nadie.
PRIORIDAD = {"baja": 0, "actualizacion": 1, "alta": 2}

# Intentos antes de apartar a cuarentena. Reintentar para siempre esconde el
# problema en un log que nadie mira; rendirse a la primera convierte un fallo de
# red en trabajo manual.
MAX_INTENTOS = 5


def encolar(
    db: Session,
    tenant_id: UUID,
    *,
    herramienta: str,
    objeto: str,
    objeto_id: str,
    operacion: str,
    carga: dict[str, Any],
) -> SincronizacionSuite:
    """Pone (o actualiza) el estado deseado de un objeto en una herramienta.

    Si ya hay una fila pendiente para el mismo objeto, **se reemplaza** en vez de
    añadir otra: la cola guarda el estado que se quiere, no el historial de
    intenciones. Encolar tres cambios seguidos de la misma persona y aplicarlos
    los tres sería aplicar dos estados intermedios que ya no interesan a nadie —
    y el último podría llegar primero.
    """
    if objeto not in OBJETOS:
        raise ErrorValidacion(
            f"«{objeto}» no es un objeto gobernado desde aquí.",
            error_code="suite.objeto_no_gobernado",
            detalle={"gobernados": list(OBJETOS)},
        )
    if operacion not in PRIORIDAD:
        raise ErrorValidacion(
            f"Operación «{operacion}» no válida.", error_code="suite.operacion_no_valida"
        )

    fila = db.execute(
        select(SincronizacionSuite).where(
            SincronizacionSuite.tenant_id == tenant_id,
            SincronizacionSuite.herramienta == herramienta,
            SincronizacionSuite.objeto == objeto,
            SincronizacionSuite.objeto_id == objeto_id,
        )
    ).scalar_one_or_none()
    if fila is None:
        fila = SincronizacionSuite(
            tenant_id=tenant_id,
            herramienta=herramienta,
            objeto=objeto,
            objeto_id=objeto_id,
        )
        db.add(fila)

    fila.operacion = operacion
    fila.carga = carga
    fila.hash_deseado = _huella(carga)
    if fila.hash_aplicado == fila.hash_deseado and operacion != "baja":
        # Ya está allí tal cual. No se reencola: empujar lo mismo otra vez gasta
        # una llamada y, con algunas herramientas, cuenta como modificación en su
        # propia auditoría — ruido que después nadie sabe interpretar.
        fila.estado = "aplicado"
        return fila

    fila.estado = "pendiente"
    fila.intentos = 0
    fila.ultimo_error = None
    fila.reintentar_at = None
    db.flush()
    return fila


def pendientes(
    db: Session, tenant_id: UUID, *, herramienta: str | None = None, limite: int = 200
) -> list[SincronizacionSuite]:
    """Lo que toca aplicar, con la baja primero y respetando la espera."""
    ahora = datetime.now(timezone.utc)
    consulta = select(SincronizacionSuite).where(
        SincronizacionSuite.tenant_id == tenant_id,
        SincronizacionSuite.estado.in_(("pendiente", "fallido")),
    )
    if herramienta:
        consulta = consulta.where(SincronizacionSuite.herramienta == herramienta)

    filas = list(db.execute(consulta).scalars().all())
    listas = [f for f in filas if f.reintentar_at is None or _con_tz(f.reintentar_at) <= ahora]
    # El orden lo pone Python y no SQL porque la prioridad es semántica —qué
    # operación importa más— y no un número que convenga guardar: guardarlo
    # obligaría a migrar la tabla cada vez que se añada una operación.
    listas.sort(key=lambda f: (PRIORIDAD.get(f.operacion, 9), f.created_at))
    return listas[:limite]


def _con_tz(valor: datetime) -> datetime:
    return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)


def anotar_resultado(
    db: Session,
    fila: SincronizacionSuite,
    *,
    ok: bool,
    detalle: str = "",
    identificador_externo: str = "",
    por: UUID | None = None,
) -> SincronizacionSuite:
    """Registra cómo fue el intento y decide si se reintenta o se aparta."""
    fila.intentos += 1
    if ok:
        fila.estado = "aplicado"
        fila.hash_aplicado = fila.hash_deseado
        fila.aplicado_at = datetime.now(timezone.utc)
        fila.ultimo_error = None
        fila.reintentar_at = None
        if identificador_externo:
            fila.identificador_externo = identificador_externo
    elif fila.intentos >= MAX_INTENTOS:
        # A cuarentena, no a un log. Reintentar para siempre esconde el problema
        # donde nadie mira; apartarlo y enseñarlo es lo único que hace que
        # alguien lo arregle.
        fila.estado = "cuarentena"
        fila.ultimo_error = detalle[:1000]
        fila.reintentar_at = None
    else:
        fila.estado = "fallido"
        fila.ultimo_error = detalle[:1000]
        # Espera creciente: una herramienta caída diez minutos no puede costar
        # diez minutos de martilleo, y una caída tres días no puede costar tres
        # días de reintentos cada segundo.
        fila.reintentar_at = datetime.now(timezone.utc) + timedelta(
            seconds=min(3600, 30 * 2 ** (fila.intentos - 1))
        )

    db.add(
        AplicacionSuite(
            tenant_id=fila.tenant_id,
            herramienta=fila.herramienta,
            objeto=fila.objeto,
            objeto_id=fila.objeto_id,
            operacion=fila.operacion,
            resultado="ok" if ok else fila.estado,
            detalle=detalle[:1000] or None,
            por=por,
        )
    )
    return fila


def cuarentena(db: Session, tenant_id: UUID) -> list[dict[str, Any]]:
    """Lo que no se ha podido aplicar y necesita una persona."""
    filas = (
        db.execute(
            select(SincronizacionSuite)
            .where(
                SincronizacionSuite.tenant_id == tenant_id,
                SincronizacionSuite.estado == "cuarentena",
            )
            .order_by(SincronizacionSuite.updated_at.desc())
        )
        .scalars()
        .all()
    )
    return [
        {
            # El identificador de la fila apartada, que es con lo que se la
            # reintenta. Sin él, la única acción que ofrece esta pantalla —«volver
            # a intentarlo»— no se puede pedir: la ruta existía y no había forma
            # de llegar a ella desde lo que se enseñaba. `objeto_id` no sirve,
            # porque es el del usuario o la unidad, no el de la sincronización.
            "id": str(f.id),
            "herramienta": f.herramienta,
            "objeto": f.objeto,
            "objeto_id": f.objeto_id,
            "operacion": f.operacion,
            "intentos": f.intentos,
            "error": f.ultimo_error,
            # Se dice qué se mandó: sin eso, quien lo mira tiene que adivinar si
            # el problema es el dato o la herramienta.
            "carga": f.carga,
            "gravedad": "alta" if f.operacion == "baja" else "normal",
        }
        for f in filas
    ]


def reintentar(db: Session, tenant_id: UUID, sincronizacion_id: UUID) -> SincronizacionSuite:
    """Saca algo de cuarentena para volver a intentarlo."""
    fila = db.get(SincronizacionSuite, sincronizacion_id)
    if fila is None or fila.tenant_id != tenant_id:
        raise NoEncontrado("No encontrado", error_code="suite.sincronizacion_no_encontrada")
    fila.estado = "pendiente"
    fila.intentos = 0
    fila.reintentar_at = None
    return fila


# ── Provisionar (CRM-00.01.07.02, .03) ────────────────────────────────────


def provisionar_tenant(db: Session, tenant_id: UUID) -> dict[str, Any]:
    """Encola el alta del tenant en cada herramienta conectada.

    Lo que **no** hace es dar por buena la cascada: cada herramienta tiene su
    fila de estado y se dice cuál ha fallado. Un alta «correcta» que dejó dos de
    tres herramientas sin el cliente es peor que una que falla, porque se
    descubre el día que alguien intenta abrir un documento.
    """
    identidad = identidad_de_tenant(db, tenant_id)
    organizacion = organizacion_de_tenant(db, tenant_id)
    encoladas = []
    for herramienta in herramientas(db, tenant_id):
        if "tenant" not in (herramienta.objetos or ["tenant", "usuario", "unidad"]):
            continue
        carga = _traducir(herramienta, {**identidad, "organizacion": organizacion})
        encolar(
            db,
            tenant_id,
            herramienta=herramienta.nombre,
            objeto="tenant",
            objeto_id=str(tenant_id),
            operacion="alta",
            carga=carga,
        )
        encoladas.append(herramienta.nombre)

    registrar(
        db,
        accion="suite.tenant_encolado",
        objeto="tenant",
        objeto_id=tenant_id,
        datos={"herramientas": encoladas},
        tenant_id=tenant_id,
    )
    return {
        "tenant": identidad["slug"],
        "herramientas": encoladas,
        # Si no hay ninguna conectada se dice: un «0 herramientas, todo bien»
        # silencioso haría creer que el cliente está en la suite cuando solo está
        # en el CRM.
        "sin_herramientas": not encoladas,
    }


def cerrar_tenant(db: Session, tenant_id: UUID) -> dict[str, Any]:
    """Encola la **baja** del tenant en cada herramienta conectada (CRM-00.01.07.13).

    El alta en cascada llevaba desde el principio y la baja no existía: cerrar un
    cliente en el CRM no le decía nada a las demás herramientas, y su gente
    seguía entrando en el gestor documental con el contrato ya terminado. Nadie
    lo descubre hasta una auditoría, que es tarde.

    Va con la prioridad de baja, que es la máxima: un alta que tarda es una
    molestia, una baja que tarda es una puerta abierta.
    """
    identidad = identidad_de_tenant(db, tenant_id)
    encoladas = []
    for herramienta in herramientas(db, tenant_id, solo_activas=False):
        if "tenant" not in (herramienta.objetos or list(OBJETOS)):
            continue
        encolar(
            db,
            tenant_id,
            herramienta=herramienta.nombre,
            objeto="tenant",
            objeto_id=str(tenant_id),
            operacion="baja",
            carga=_traducir(herramienta, identidad),
        )
        encoladas.append(herramienta.nombre)

    registrar(
        db,
        accion="suite.tenant_cerrado",
        objeto="tenant",
        objeto_id=tenant_id,
        datos={"herramientas": encoladas},
        tenant_id=tenant_id,
    )
    return {
        "tenant": identidad["slug"],
        "herramientas": encoladas,
        "sin_herramientas": not encoladas,
    }


def certificado_de_cierre(db: Session, tenant_id: UUID) -> dict[str, Any]:
    """El certificado único de baja, leyendo el estado **real** de la cola.

    La regla que lo hace valer algo vive en `ciclo_vida`: o se cierra en todas o
    se dice cuál ha quedado abierta. Lo que faltaba era quien le contara qué ha
    pasado de verdad; sin eso, la función estaba escrita, probada y era
    inalcanzable, y la capacidad constaba hecha.

    Se mira la fila de sincronización de cada herramienta, no un registro
    aparte: el estado que vale es el que decide si se volverá a intentar.
    """
    from services.tenancy.ciclo_vida import certificado_de_baja

    cierres: dict[str, dict[str, Any]] = {}
    for herramienta in herramientas(db, tenant_id, solo_activas=False):
        if "tenant" not in (herramienta.objetos or list(OBJETOS)):
            continue
        fila = db.execute(
            select(SincronizacionSuite).where(
                SincronizacionSuite.tenant_id == tenant_id,
                SincronizacionSuite.herramienta == herramienta.nombre,
                SincronizacionSuite.objeto == "tenant",
                SincronizacionSuite.objeto_id == str(tenant_id),
            )
        ).scalar_one_or_none()

        if fila is None or fila.operacion != "baja":
            # No haber pedido la baja no es haberla aplicado. Contarlo como
            # cerrado sería justo la firma en falso que este certificado existe
            # para no dar.
            cierres[herramienta.nombre] = {
                "cerrado": False,
                "porque": "no se ha pedido la baja del tenant en esta herramienta",
            }
        elif fila.estado == "aplicado":
            cierres[herramienta.nombre] = {"cerrado": True}
        else:
            cierres[herramienta.nombre] = {
                "cerrado": False,
                "porque": (
                    f"la baja está «{fila.estado}»: "
                    f"{fila.ultimo_error or 'sin aplicar todavía'}"
                ),
            }
    return certificado_de_baja(db, tenant_id, cierres=cierres)


def provisionar_usuario(
    db: Session, tenant_id: UUID, usuario: dict[str, Any], *, operacion: str = "alta"
) -> dict[str, Any]:
    """Un único alta —y una única baja— para toda la suite (CRM-00.01.07.03).

    La baja se encola **aunque el rol ya no esté mapeado**: negarse a dar de baja
    a alguien porque su rol desapareció del mapeo sería el peor fallo posible,
    exactamente el caso en que hay que echarlo.
    """
    encoladas = []
    for herramienta in herramientas(db, tenant_id):
        if "usuario" not in (herramienta.objetos or ["tenant", "usuario", "unidad"]):
            continue
        carga = carga_de_usuario(db, herramienta, usuario)
        if (
            operacion != "baja"
            and not carga.get("rol")
            and not (herramienta.mapeo_roles or {}).get("por_defecto")
        ):
            # Sin rol mapeado no se da de alta: crearlo sin rol dejaría una
            # cuenta muda que no sirve para nada y que además hay que acordarse
            # de dar de baja. Se dice, en vez de crearla y confiar.
            logger.warning(
                "suite.usuario_sin_rol",
                herramienta=herramienta.nombre,
                usuario=usuario.get("email"),
            )
            continue
        encolar(
            db,
            tenant_id,
            herramienta=herramienta.nombre,
            objeto="usuario",
            objeto_id=str(usuario["id"]),
            operacion=operacion,
            carga=carga,
        )
        encoladas.append(herramienta.nombre)

    registrar(
        db,
        accion=f"suite.usuario_{operacion}",
        objeto="usuario",
        objeto_id=usuario["id"],
        datos={"herramientas": encoladas, "email": usuario.get("email")},
        tenant_id=tenant_id,
    )
    return {"usuario": usuario.get("email"), "operacion": operacion, "herramientas": encoladas}


def provisionar_organizacion(db: Session, tenant_id: UUID) -> dict[str, Any]:
    """Encola el árbol de áreas y departamentos en cada herramienta."""
    unidades = organizacion_de_tenant(db, tenant_id)
    encoladas = []
    for herramienta in herramientas(db, tenant_id):
        if "unidad" not in (herramienta.objetos or ["tenant", "usuario", "unidad"]):
            continue
        for unidad in unidades:
            encolar(
                db,
                tenant_id,
                herramienta=herramienta.nombre,
                objeto="unidad",
                objeto_id=unidad["id"],
                operacion="alta" if unidad["activa"] else "baja",
                carga=_traducir(herramienta, unidad),
            )
        encoladas.append(herramienta.nombre)
    return {"unidades": len(unidades), "herramientas": encoladas}


# ── Simulación (CRM-00.01.07.11) ──────────────────────────────────────────


@dataclass(slots=True)
class Plan:
    herramienta: str
    altas: list[str]
    bajas: list[str]
    cambios: list[str]
    sin_cambio: int


def simular(db: Session, tenant_id: UUID, *, herramienta: str | None = None) -> dict[str, Any]:
    """Qué se crearía, cambiaría o desactivaría en cada herramienta.

    Se mira antes de aplicar porque el error caro aquí no es el técnico: es
    desactivar a media plantilla en el gestor documental por un mapeo de roles
    mal escrito, y enterarse cuando llaman.
    """
    consulta = select(SincronizacionSuite).where(
        SincronizacionSuite.tenant_id == tenant_id,
        SincronizacionSuite.estado.in_(("pendiente", "fallido")),
    )
    if herramienta:
        consulta = consulta.where(SincronizacionSuite.herramienta == herramienta)

    planes: dict[str, Plan] = {}
    aplicadas = 0
    for fila in db.execute(consulta).scalars():
        plan = planes.setdefault(fila.herramienta, Plan(fila.herramienta, [], [], [], 0))
        etiqueta = (
            f"{fila.objeto}:{fila.carga.get('email') or fila.carga.get('codigo') or fila.objeto_id}"
        )
        if fila.operacion == "baja":
            plan.bajas.append(etiqueta)
        elif fila.hash_aplicado:
            plan.cambios.append(etiqueta)
        else:
            plan.altas.append(etiqueta)

    for fila in db.execute(
        select(SincronizacionSuite).where(
            SincronizacionSuite.tenant_id == tenant_id,
            SincronizacionSuite.estado == "aplicado",
        )
    ).scalars():
        aplicadas += 1
        planes.setdefault(fila.herramienta, Plan(fila.herramienta, [], [], [], 0)).sin_cambio += 1

    return {
        "herramientas": [
            {
                "herramienta": p.herramienta,
                "altas": p.altas,
                "bajas": p.bajas,
                "cambios": p.cambios,
                "sin_cambio": p.sin_cambio,
            }
            for p in sorted(planes.values(), key=lambda p: p.herramienta)
        ],
        "total_a_aplicar": sum(
            len(p.altas) + len(p.bajas) + len(p.cambios) for p in planes.values()
        ),
        "ya_aplicadas": aplicadas,
    }


# ── Reconciliación (CRM-00.01.07.07) ──────────────────────────────────────


def reconciliar(
    db: Session,
    tenant_id: UUID,
    herramienta: str,
    estado_remoto: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Compara lo que hay allí con lo que debería haber.

    `estado_remoto` llega leído por el conector: `{objeto_id: carga}`. Se pasa
    ya leído para que esta función sea pura y se pueda probar de verdad; el
    conector se encarga de traerlo.

    Tres divergencias, y las tres importan por motivos distintos:

    * **falta allí** — el empuje no llegó. Es el caso benigno: se reencola.
    * **sobra allí** — hay alguien que aquí ya no está. Es el peligroso: suele
      ser una baja que no se aplicó, y es literalmente un acceso que sigue
      abierto.
    * **difiere** — alguien lo cambió en la otra herramienta. **No se pisa sin
      decirlo**: puede ser un ajuste deliberado del administrador de allí, y
      sobrescribirlo en silencio es cómo se pierde la confianza en el empuje
      automático.
    """
    _herramienta(db, tenant_id, herramienta)
    locales = {
        f.objeto_id: f
        for f in db.execute(
            select(SincronizacionSuite).where(
                SincronizacionSuite.tenant_id == tenant_id,
                SincronizacionSuite.herramienta == herramienta,
            )
        ).scalars()
    }

    faltan: list[str] = []
    sobran: list[str] = []
    difieren: list[dict[str, Any]] = []

    for objeto_id, fila in locales.items():
        if fila.operacion == "baja":
            if objeto_id in estado_remoto:
                sobran.append(objeto_id)
            continue
        remoto = estado_remoto.get(objeto_id)
        if remoto is None:
            faltan.append(objeto_id)
            continue
        if _huella(remoto) != fila.hash_deseado:
            difieren.append(
                {
                    "objeto_id": objeto_id,
                    "objeto": fila.objeto,
                    "aqui": fila.carga,
                    "alli": remoto,
                }
            )
            fila.estado = "divergente"

    ajenos = sorted(set(estado_remoto) - set(locales))

    return {
        "herramienta": herramienta,
        "faltan_alli": faltan,
        "sobran_alli": sobran + ajenos,
        "difieren": difieren,
        "en_linea": not (faltan or sobran or ajenos or difieren),
        # El aviso va pegado al resultado porque es lo que hay que mirar primero:
        # lo que sobra suele ser una baja no aplicada, y eso es un acceso abierto.
        "aviso": (
            f"{len(sobran) + len(ajenos)} objetos existen en «{herramienta}» y no "
            "deberían. Si son usuarios, son accesos abiertos."
            if (sobran or ajenos)
            else ""
        ),
    }


def reparar(
    db: Session, tenant_id: UUID, herramienta: str, *, objeto_ids: list[str], forzar: bool = False
) -> dict[str, Any]:
    """Reencola lo divergente para volver a empujarlo.

    Lo `divergente` —cambiado a propósito en la otra herramienta— exige `forzar`:
    repararlo es pisar el trabajo de alguien, y hacerlo sin decirlo es cómo se
    pierde la confianza en el empuje automático.
    """
    reparados, omitidos = [], []
    for objeto_id in objeto_ids:
        fila = db.execute(
            select(SincronizacionSuite).where(
                SincronizacionSuite.tenant_id == tenant_id,
                SincronizacionSuite.herramienta == herramienta,
                SincronizacionSuite.objeto_id == objeto_id,
            )
        ).scalar_one_or_none()
        if fila is None:
            omitidos.append({"objeto_id": objeto_id, "motivo": "no está gobernado desde aquí"})
            continue
        if fila.estado == "divergente" and not forzar:
            omitidos.append(
                {
                    "objeto_id": objeto_id,
                    "motivo": (
                        "cambiado en la otra herramienta; repararlo pisaría ese "
                        "cambio. Repite con forzar=true si es lo que quieres."
                    ),
                }
            )
            continue
        fila.estado = "pendiente"
        fila.intentos = 0
        fila.reintentar_at = None
        reparados.append(objeto_id)

    registrar(
        db,
        accion="suite.reparado",
        objeto="herramienta",
        objeto_id=None,
        datos={"herramienta": herramienta, "reparados": reparados, "forzado": forzar},
        tenant_id=tenant_id,
    )
    return {"reparados": reparados, "omitidos": omitidos}


# ── Panel (CRM-00.01.07.07, .12) ──────────────────────────────────────────


def panel(db: Session, tenant_id: UUID) -> dict[str, Any]:
    """Cómo está la suite para este tenant, de un vistazo."""
    conectadas = herramientas(db, tenant_id, solo_activas=False)
    resumen = []
    for herramienta in conectadas:
        cuentas = dict(
            db.execute(
                select(SincronizacionSuite.estado, func.count())
                .where(
                    SincronizacionSuite.tenant_id == tenant_id,
                    SincronizacionSuite.herramienta == herramienta.nombre,
                )
                .group_by(SincronizacionSuite.estado)
            ).all()
        )
        bajas_atascadas = int(
            db.execute(
                select(func.count())
                .select_from(SincronizacionSuite)
                .where(
                    SincronizacionSuite.tenant_id == tenant_id,
                    SincronizacionSuite.herramienta == herramienta.nombre,
                    SincronizacionSuite.operacion == "baja",
                    SincronizacionSuite.estado.in_(("pendiente", "fallido", "cuarentena")),
                )
            ).scalar_one()
            or 0
        )
        resumen.append(
            {
                "herramienta": herramienta.nombre,
                "tipo": herramienta.tipo,
                "activa": herramienta.activa,
                "estado": herramienta.estado,
                "por_estado": {k: int(v) for k, v in cuentas.items()},
                # Se saca aparte porque es lo único que hay que mirar con prisa:
                # una baja sin aplicar es un acceso que sigue abierto.
                "bajas_sin_aplicar": bajas_atascadas,
                "ultimo_error": herramienta.ultimo_error,
            }
        )

    return {
        "tenant": identidad_de_tenant(db, tenant_id),
        "herramientas": resumen,
        "cuarentena": len(cuarentena(db, tenant_id)),
        "bajas_sin_aplicar": sum(h["bajas_sin_aplicar"] for h in resumen),
        "en_verde": all(
            not h["bajas_sin_aplicar"] and h["por_estado"].get("cuarentena", 0) == 0
            for h in resumen
        )
        and bool(resumen),
        "sin_herramientas": not resumen,
    }


def historial(
    db: Session, tenant_id: UUID, *, objeto_id: str | None = None, limite: int = 200
) -> list[dict[str, Any]]:
    """Auditoría transversal: qué se aplicó, dónde y con qué resultado."""
    consulta = select(AplicacionSuite).where(AplicacionSuite.tenant_id == tenant_id)
    if objeto_id:
        consulta = consulta.where(AplicacionSuite.objeto_id == objeto_id)
    filas = (
        db.execute(consulta.order_by(AplicacionSuite.created_at.desc()).limit(limite))
        .scalars()
        .all()
    )
    return [
        {
            "at": f.created_at.isoformat(),
            "herramienta": f.herramienta,
            "objeto": f.objeto,
            "objeto_id": f.objeto_id,
            "operacion": f.operacion,
            "resultado": f.resultado,
            "detalle": f.detalle,
            "por": str(f.por) if f.por else None,
        }
        for f in filas
    ]


# ── Conexión de una herramienta (CRM-00.01.07.08) ─────────────────────────


def conectar(
    db: Session,
    tenant_id: UUID,
    *,
    nombre: str,
    base_url: str,
    credenciales: dict[str, str],
    tipo: str = "generico",
    mapeo_roles: dict[str, Any] | None = None,
    mapeo_campos: dict[str, Any] | None = None,
    campos_fijos: dict[str, Any] | None = None,
    objetos: list[str] | None = None,
    identificador_externo: str = "",
) -> HerramientaConectada:
    """Da de alta una herramienta de la suite para este tenant.

    La URL pasa por el guard de salidas, igual que un webhook o un IdP: aquí se
    mandan datos de usuarios, y una dirección apuntando a la red interna
    convertiría el empuje en una vía para hablar con lo que no se puede alcanzar
    desde fuera.
    """
    from crmcore.red import guard_url
    from crmcore.security.cifrado import cifrar_dict

    guard_url.exigir(base_url)
    if db.execute(
        select(HerramientaConectada.id).where(
            HerramientaConectada.tenant_id == tenant_id,
            HerramientaConectada.nombre == nombre,
        )
    ).first():
        raise Conflicto(
            f"«{nombre}» ya está conectada a este tenant",
            error_code="suite.herramienta_duplicada",
        )

    fila = HerramientaConectada(
        tenant_id=tenant_id,
        nombre=nombre,
        tipo=tipo,
        base_url=base_url,
        credenciales=cifrar_dict(credenciales or {}),
        mapeo_roles=mapeo_roles or {},
        mapeo_campos=mapeo_campos or {},
        campos_fijos=campos_fijos or {},
        objetos=objetos or list(OBJETOS),
        identificador_externo=identificador_externo,
    )
    db.add(fila)
    db.flush()
    registrar(
        db,
        accion="suite.herramienta_conectada",
        objeto="herramienta",
        objeto_id=fila.id,
        datos={"nombre": nombre, "tipo": tipo, "objetos": fila.objetos},
        tenant_id=tenant_id,
    )
    return fila
