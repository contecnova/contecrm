"""Inicio de sesión contra un proveedor externo: estado, provisión y roles.

Es el tramo común de OIDC y de SAML. Los dos protocolos se diferencian en cómo
se habla con el proveedor; lo que pasa **después** —quién es esta persona, si
existe aquí, con qué roles entra— es lo mismo, y tenerlo dos veces garantizaría
que la política de provisión acabe siendo distinta según por dónde entre cada
uno.

**El estado del flujo va a la base de datos, no a la caché.** Entre que se manda
al usuario al proveedor y vuelve pueden pasar minutos, y la vuelta puede
atender la réplica que no inició el flujo. Con la caché en memoria eso sería un
inicio de sesión que falla siempre y solo en producción, donde hay más de una
réplica.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from crmcore.db.base import Base
from crmcore.errors import Conflicto, ErrorValidacion, NoAutenticado, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import (
    DateTime,
    Index,
    String,
    Text,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

logger = get_logger(__name__)


class EstadoSSO(Base):
    """Un inicio de sesión a medias.

    Guarda el `state`, el `nonce` y el verificador PKCE entre la ida y la
    vuelta. Se borra al usarse: un estado reutilizable convierte la respuesta
    del proveedor en algo que se puede repetir.
    """

    __tablename__ = "estados_sso"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    proveedor_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)

    # El `state` se guarda **hasheado**. Va en la URL, así que acaba en el log
    # del proxy y en el historial del navegador; guardarlo en claro haría que
    # quien lea un log pueda cerrar un inicio de sesión ajeno.
    estado_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, info={"secreto": True}
    )
    nonce: Mapped[str] = mapped_column(String(64), nullable=False)
    verificador: Mapped[str] = mapped_column(String(128), nullable=False)
    volver_a: Mapped[str | None] = mapped_column(Text, nullable=True)

    caduca_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_estados_sso_caducidad", "tenant_id", "caduca_at"),)


def _hash(valor: str) -> str:
    return hashlib.sha256(valor.encode("utf-8")).hexdigest()


def guardar_estado(
    db: Session,
    *,
    tenant_id: UUID,
    proveedor_id: UUID,
    estado: str,
    nonce: str,
    verificador: str,
    volver_a: str | None = None,
) -> EstadoSSO:
    from crmcore.runtime import settings as rt

    ttl = int(rt.efectivo("sso_estado_ttl_s", db) or 300)
    fila = EstadoSSO(
        tenant_id=tenant_id,
        proveedor_id=proveedor_id,
        estado_hash=_hash(estado),
        nonce=nonce,
        verificador=verificador,
        volver_a=volver_a,
        caduca_at=datetime.now(timezone.utc) + timedelta(seconds=ttl),
    )
    db.add(fila)
    db.flush()
    return fila


def tenant_del_estado(estado: str) -> UUID:
    """De qué tenant es un inicio a medias, **sin gastarlo**.

    Hace falta antes de poder abrir la sesión: la vuelta del proveedor llega sin
    autenticar y el tenant vive dentro del estado, así que hay un huevo y una
    gallina. Se resuelve con una sesión de sistema que mira **una fila
    encontrada por un secreto** —el estado va hasheado y no se puede adivinar— y
    que no lee nada más.

    No se consume aquí: gastarlo es cosa de la transacción que completa la
    entrada, para que un fallo a mitad no deje al usuario con el vale quemado y
    sin sesión.
    """
    from crmcore.db.session import sesion

    with sesion(None, sistema=True) as db:
        fila = db.execute(
            select(EstadoSSO.tenant_id).where(EstadoSSO.estado_hash == _hash(estado))
        ).scalar_one_or_none()
    if fila is None:
        raise NoAutenticado(
            "Este inicio de sesión no consta o ya se ha usado",
            error_code="sso.estado_desconocido",
        )
    return fila


def consumir_estado(db: Session, estado: str) -> EstadoSSO:
    """Recupera el estado y **lo borra**. Un solo uso.

    Sin el borrado, la respuesta del proveedor se podría repetir: quien la
    capture —en un log, en el historial— la reenvía y entra. El borrado es lo
    que convierte el `state` en un vale de un solo uso.
    """
    fila = db.execute(
        select(EstadoSSO).where(EstadoSSO.estado_hash == _hash(estado))
    ).scalar_one_or_none()
    if fila is None:
        raise NoAutenticado(
            "Este inicio de sesión no consta o ya se ha usado",
            error_code="sso.estado_desconocido",
        )
    caducado = fila.caduca_at < datetime.now(timezone.utc)
    db.delete(fila)
    db.flush()
    if caducado:
        raise NoAutenticado(
            "El inicio de sesión ha tardado demasiado; vuelve a intentarlo",
            error_code="sso.estado_caducado",
        )
    return fila


def purgar_estados(db: Session) -> int:
    """Borra los estados caducados. La ejecuta una tarea periódica.

    Sin esto, la tabla crece con cada inicio de sesión abandonado — que son
    muchos: cualquiera que abra el formulario del IdP y cierre la pestaña.
    """
    caducados = (
        db.execute(select(EstadoSSO).where(EstadoSSO.caduca_at < datetime.now(timezone.utc)))
        .scalars()
        .all()
    )
    for fila in caducados:
        db.delete(fila)
    return len(caducados)


# ── Identidad → usuario ───────────────────────────────────────────────────


def roles_desde_grupos(mapeo: dict[str, Any], grupos: list[str]) -> list[str]:
    """Traduce los grupos del proveedor a roles de aquí.

    La comparación **ignora mayúsculas**: Entra ID devuelve los grupos tal como
    los escribió quien los creó, y el administrador del CRM los teclea otra vez
    en el mapeo. Exigir coincidencia exacta hace que el mapeo «no funcione» sin
    que nadie vea por qué.

    Un grupo sin correspondencia **no da rol**, y eso es deliberado: lo contrario
    —un rol por defecto para cualquier grupo desconocido— convierte crear un
    grupo en el IdP en conceder acceso al CRM.
    """
    if not mapeo:
        return []
    normalizado = {str(k).strip().lower(): v for k, v in mapeo.items()}
    roles: list[str] = []
    for grupo in grupos:
        destino = normalizado.get(str(grupo).strip().lower())
        if isinstance(destino, str):
            roles.append(destino)
        elif isinstance(destino, (list, tuple)):
            roles.extend(str(r) for r in destino)
    return list(dict.fromkeys(roles))


def entrar_o_provisionar(
    db: Session,
    *,
    tenant_id: UUID,
    proveedor: Any,
    email: str,
    nombre: str,
    sujeto_externo: str,
    grupos: list[str],
) -> Any:
    """Encuentra al usuario o lo crea, y ajusta sus roles según el proveedor.

    **El correo es la llave, no el `sub`.** El identificador del proveedor es
    estable dentro de ese proveedor, pero un tenant puede tener dos, y la misma
    persona llegaría como dos usuarios distintos. Se guarda el `sub` para poder
    detectar un cambio de correo, pero la identidad se resuelve por correo.

    **Los roles se recalculan en cada entrada.** Quitar a alguien de un grupo en
    el IdP tiene que quitarle el acceso aquí; si los roles solo se asignaran al
    crear el usuario, el día que alguien cambia de departamento conservaría los
    permisos antiguos para siempre. Los roles puestos a mano en el CRM **no** se
    tocan: el mapeo solo gobierna los que él mismo concede.
    """
    from services.identity.modelos import Membresia, Usuario

    correo = (email or "").strip().lower()
    if not correo:
        raise ErrorValidacion(
            "El proveedor de identidad no ha devuelto correo, y sin él no se puede "
            "saber quién es esta persona",
            error_code="sso.sin_email",
        )

    usuario = db.execute(select(Usuario).where(Usuario.email == correo)).scalar_one_or_none()
    nuevo = usuario is None

    if nuevo:
        if not proveedor.jit:
            raise Conflicto(
                "Este usuario no existe y el proveedor no tiene el alta automática "
                "activada. Hay que darlo de alta antes.",
                error_code="sso.sin_jit",
                detalle={"email": correo},
            )
        usuario = Usuario(
            email=correo,
            nombre=nombre or correo.split("@")[0],
            activo=True,
            # Sin contraseña local: es lo que hace que forzar SSO sea de verdad
            # —sin credencial propia no hay forma de saltarse el IdP— y crear
            # una vacía sería una puerta trasera.
            hash_contrasena=None,
        )
        db.add(usuario)
        db.flush()

    membresia = db.execute(
        select(Membresia).where(
            Membresia.usuario_id == usuario.id, Membresia.tenant_id == tenant_id
        )
    ).scalar_one_or_none()
    if membresia is None:
        if not proveedor.jit:
            raise Conflicto(
                "Este usuario no pertenece a este tenant y el alta automática está " "desactivada",
                error_code="sso.sin_jit",
            )
        membresia = Membresia(tenant_id=tenant_id, usuario_id=usuario.id, activa=True)
        db.add(membresia)
        db.flush()
    elif not membresia.activa:
        raise NoAutenticado(
            "Esta cuenta está dada de baja en este tenant",
            error_code="sso.membresia_inactiva",
        )

    concedidos = roles_desde_grupos(proveedor.mapeo_roles or {}, grupos)
    if concedidos:
        gobernados = {str(v) for v in _roles_del_mapeo(proveedor.mapeo_roles or {})}
        manuales = [r for r in (membresia.roles or []) if r not in gobernados]
        membresia.roles = list(dict.fromkeys(manuales + concedidos))
    elif proveedor.mapeo_roles:
        # Tiene mapeo pero ninguno de sus grupos encaja: se le quitan los roles
        # que ese mapeo concede y se le dejan los manuales. Dejarle los de la
        # última vez sería no retirar el acceso al cambiar de departamento.
        gobernados = {str(v) for v in _roles_del_mapeo(proveedor.mapeo_roles)}
        membresia.roles = [r for r in (membresia.roles or []) if r not in gobernados]

    logger.info(
        "sso.entrada",
        tenant=str(tenant_id),
        proveedor=proveedor.nombre,
        usuario=str(usuario.id),
        nuevo=nuevo,
        roles=len(membresia.roles or []),
    )
    return usuario


def _roles_del_mapeo(mapeo: dict[str, Any]) -> list[str]:
    """Todos los roles que ese mapeo puede conceder. Son los que gobierna."""
    salida: list[str] = []
    for destino in mapeo.values():
        if isinstance(destino, str):
            salida.append(destino)
        elif isinstance(destino, (list, tuple)):
            salida.extend(str(r) for r in destino)
    return salida


def proveedor_para(
    db: Session, tenant_id: UUID, *, email: str | None = None, nombre: str | None = None
) -> Any:
    """Elige el proveedor: por nombre si se pide, o por dominio del correo.

    El dominio es lo que permite tener varios a la vez —empleados por Entra ID y
    partners por Google, o dos correos tras una fusión— sin preguntarle al
    usuario a cuál quiere ir, que es una pregunta que nadie sabe contestar.
    """
    from services.identity.modelos import ProveedorIdentidad

    consulta = select(ProveedorIdentidad).where(
        ProveedorIdentidad.tenant_id == tenant_id,
        ProveedorIdentidad.activo.is_(True),
    )
    if nombre:
        consulta = consulta.where(ProveedorIdentidad.nombre == nombre)

    candidatos = list(db.execute(consulta).scalars().all())
    if not candidatos:
        raise NoEncontrado(
            "Este tenant no tiene configurado ningún proveedor de identidad activo",
            error_code="sso.sin_proveedor",
        )
    if nombre:
        return candidatos[0]

    if email and "@" in email:
        # SE DELEGA en la resolución de `sso_gobierno`, que es la buena.
        #
        # Aquí había una segunda: comparaba solo con `dominio_email` y no
        # miraba ni la lista de dominios añadidos ni la herencia de
        # subdominios. O sea que un usuario de un dominio extra —los que
        # acumula una empresa tras una adquisición— o de `ventas.ejemplo.com`
        # **no podía entrar por ninguna puerta**: el SSO forzado SÍ encontraba
        # su proveedor y le bloqueaba la contraseña, y esta no lo encontraba y
        # le negaba el SSO. Fuera del CRM, sin nada que lo explicara.
        #
        # Dos implementaciones de «¿qué proveedor le toca a este correo?»
        # divergen siempre, y la que se queda atrás es la puerta por la que no
        # se entra. El import es local porque `sso_gobierno` ya importa de
        # aquí.
        from services.identity.sso_gobierno import proveedor_por_correo

        suyo = proveedor_por_correo(db, tenant_id, email)
        if suyo is not None:
            return suyo

    sin_dominio = [p for p in candidatos if not (p.dominio_email or "").strip()]
    if sin_dominio:
        return sin_dominio[0]

    raise NoEncontrado(
        "Ningún proveedor de identidad cubre ese dominio de correo",
        error_code="sso.dominio_sin_proveedor",
        detalle={"dominios": sorted({p.dominio_email for p in candidatos if p.dominio_email})},
    )


# ── Perfiles de proveedor, sin un módulo por casa (CRM-00.05.01.16, .22) ──

# Lo que cambia entre proveedores de identidad: las direcciones, los nombres de
# los campos y poco más. Eso es configuración. Un conector por casa —uno para
# cada proveedor de SSO, otro para cada uno de MFA— convierte cada implantación
# nueva en una versión del producto que hay que mantener diez años.
#
# Lo que SÍ cambia de verdad entre ellos, y por eso se declara, es qué campo trae
# el correo y cómo llaman a los grupos: equivocarse ahí no da un error, da un
# usuario sin permisos que nadie entiende.
PERFILES_SSO = {
    "saml_generico": {
        "protocolo": "saml2",
        "campo_email": "email",
        "campo_nombre": "displayName",
        "campo_grupos": "groups",
    },
    "oidc_generico": {
        "protocolo": "oidc",
        "campo_email": "email",
        "campo_nombre": "name",
        "campo_grupos": "groups",
    },
}

# Igual con el segundo factor: lo que cambia es el endpoint, la credencial y cómo
# se llama a «empujar una notificación» o «validar un código».
PERFILES_MFA = {
    "otp_generico": {"tipo": "otp", "operaciones": ("enviar", "validar")},
    "push_generico": {"tipo": "push", "operaciones": ("empujar", "consultar")},
    "webauthn": {"tipo": "webauthn", "operaciones": ("reto", "verificar")},
}


def perfil_sso(clave: str, ajustes: dict[str, Any] | None = None) -> dict[str, Any]:
    """Resuelve un perfil de proveedor de identidad y lo que lo ajusta.

    Devuelve el perfil base con los ajustes del cliente encima. Lo importante es
    que **los campos son configuración**: quien conecta un proveedor nuevo escribe
    qué campo trae el correo y cómo llaman a los grupos, no un módulo.

    Un perfil desconocido **no cae al genérico en silencio**: se dice. Caer al
    genérico produce un usuario que entra sin grupos y sin permisos, y nadie
    relaciona eso con que el perfil estaba mal escrito.
    """
    base = PERFILES_SSO.get(clave)
    if base is None:
        raise ErrorValidacion(
            f"Perfil de SSO desconocido: «{clave}». Los declarados son "
            f"{sorted(PERFILES_SSO)}; añadir uno es configuración, no código.",
            error_code="sso.perfil_desconocido",
            detalle={"declarados": sorted(PERFILES_SSO)},
        )
    resuelto = {**base, **(ajustes or {})}
    faltan = [c for c in ("campo_email",) if not resuelto.get(c)]
    return {
        "perfil": clave,
        "config": resuelto,
        "completo": not faltan,
        "faltan": faltan,
        "porque": (
            "El perfil sabe de dónde sacar el correo y los grupos."
            if not faltan
            else "Sin saber qué campo trae el correo, el usuario entra sin identidad "
            "utilizable: no es un error visible, es un usuario que no encaja con "
            "ninguna cuenta."
        ),
    }


def perfil_mfa(clave: str) -> dict[str, Any]:
    """Resuelve un perfil de proveedor de segundo factor (CRM-00.05.01.22).

    Igual que el de SSO: lo que cambia entre proveedores de MFA es el endpoint,
    la credencial y cómo llaman a «empujar una notificación» o «validar un
    código». Un módulo por casa —uno por cada proveedor— sería el mismo error
    repetido en otra capa.
    """
    base = PERFILES_MFA.get(clave)
    if base is None:
        raise ErrorValidacion(
            f"Perfil de MFA desconocido: «{clave}». Los declarados son " f"{sorted(PERFILES_MFA)}.",
            error_code="mfa.perfil_desconocido",
            detalle={"declarados": sorted(PERFILES_MFA)},
        )
    return {"perfil": clave, **base, "operaciones": list(base["operaciones"])}
