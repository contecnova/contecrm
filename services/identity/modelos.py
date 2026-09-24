"""Modelo de datos del servicio de identidad."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from crmcore.db.base import Base, SoftDeleteMixin, TimestampMixin
from crmcore.ids import nuevo_id
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column


class Usuario(Base, TimestampMixin):
    """Una persona (o una cuenta de servicio).

    **No lleva `tenant_id`**, y es la única excepción del sistema junto con
    `Tenant`. La razón es el caso que se quiere soportar: la misma persona en
    varios tenants. Si el usuario colgara de un tenant, un consultor que trabaja
    para tres clientes tendría tres identidades, tres contraseñas y tres MFA que
    configurar.

    El aislamiento no se pierde por esto: lo que acota es la membresía, y toda
    consulta de usuarios desde un tenant pasa por ella. El gate
    `test_tenant_scope_contract.py` conoce esta excepción y comprueba que
    ninguna ruta liste usuarios sin unir por membresía.
    """

    __tablename__ = "usuarios"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    email: Mapped[str] = mapped_column(
        String(320), nullable=False, unique=True, info={"sensibilidad": "personal"}
    )
    nombre: Mapped[str] = mapped_column(
        String(200), nullable=False, default="", info={"sensibilidad": "personal"}
    )
    # Nulo cuando el usuario solo entra por un proveedor de identidad externo.
    # Que sea nulable es lo que permite forzar SSO: sin contraseña local no hay
    # forma de saltarse el IdP corporativo.
    hash_contrasena: Mapped[str | None] = mapped_column(String(255), nullable=True)

    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Personal de la plataforma (soporte, operación). Ve y opera entre tenants,
    # y por eso cada acceso suyo a datos de un tenant queda auditado con motivo
    # (CRM-00.01.02.06).
    es_plataforma: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # ── MFA ───────────────────────────────────────────────────────────────
    mfa_activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Secreto TOTP, cifrado en reposo. En claro sería equivalente a guardar la
    # contraseña: quien lea la tabla puede generar códigos válidos.
    mfa_secreto: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Códigos de recuperación, hasheados. Se guardan hasheados y no en claro
    # porque son credenciales de pleno derecho: con uno se entra sin el móvil.
    mfa_recuperacion: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )

    # ── Bloqueo por intentos ──────────────────────────────────────────────
    intentos_fallidos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bloqueado_hasta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ultimo_acceso_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Preferencias que no dependen del tenant (idioma de la interfaz).
    preferencias: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    __table_args__ = (Index("ix_usuarios_activo", "activo"),)


class Membresia(Base, TimestampMixin):
    """Pertenencia de un usuario a un tenant, con sus roles ahí."""

    __tablename__ = "membresias"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    usuario_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False
    )
    roles: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    conjuntos_permisos: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    business_unit_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    # Jerarquía de mando dentro del tenant: de aquí sale la visibilidad
    # ascendente (CRM-00.05.02.02). Es del tenant y no del usuario porque la
    # misma persona puede ser responsable en uno y colaborador en otro.
    superior_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Atributos para ABAC: territorio, país, departamento.
    atributos: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "usuario_id", name="uq_membresia"),
        Index("ix_membresias_usuario", "usuario_id"),
    )


class RolTenant(Base, TimestampMixin):
    """Rol definido por el tenant, además de los de serie.

    Los roles base (`crmcore.authz.rbac.ROLES_BASE`) viven en código porque son
    los mismos para todos y tienen que existir antes de que nadie configure
    nada. Estos son los que cada organización se inventa, y por eso son datos.
    """

    __tablename__ = "roles"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    nombre: Mapped[str] = mapped_column(String(80), nullable=False)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    permisos: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    hereda_de: Mapped[str | None] = mapped_column(String(80), nullable=True)

    __table_args__ = (UniqueConstraint("tenant_id", "nombre", name="uq_rol_nombre"),)


class Sesion(Base):
    """Sesión activa: es lo que hace revocable un acceso.

    El token de acceso es un JWT y, una vez emitido, **no se puede invalidar**:
    vale hasta que caduca. Por eso dura minutos y por eso existe esta tabla — lo
    revocable es la sesión, y sin sesión válida no se puede renovar. Cerrar una
    sesión corta el acceso en cuanto caduca el token en curso, que es el
    compromiso que hace útiles los JWT sin renunciar a poder echar a alguien.
    """

    __tablename__ = "sesiones"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    usuario_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    # Hash del token de refresco, nunca el token. Si la tabla se filtra, lo que
    # se lleva el atacante no sirve para renovar nada.
    hash_refresco: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    ip: Mapped[str | None] = mapped_column(
        String(64), nullable=True, info={"sensibilidad": "personal"}
    )
    user_agent: Mapped[str | None] = mapped_column(String(400), nullable=True)
    # Huella del dispositivo, para detectar que un refresco se usa desde otro
    # sitio distinto al que lo obtuvo.
    dispositivo: Mapped[str | None] = mapped_column(String(120), nullable=True)

    creada_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    ultima_actividad_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expira_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revocada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    motivo_revocacion: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # ── Nivel de autenticación de ESTA sesión (CRM-00.05.01.18) ───────────
    # Qué factores se han superado y cuándo. Se guarda la lista y no un
    # booleano porque el step-up pregunta dos cosas distintas: «¿hubo segundo
    # factor?» y «¿hace cuánto?». Con un booleano, alguien que pasó el factor
    # por la mañana sigue autorizado a exportar la base entera por la tarde,
    # que es justo lo que la reautenticación viene a impedir.
    factores: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Cuándo se superó el último factor fuerte. Denormalizado a propósito: la
    # comprobación corre en CADA operación sensible y leerlo del JSONB obligaba
    # a recorrerlo.
    factor_fuerte_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Dispositivo de confianza con el que se entró, si lo hubo.
    dispositivo_confianza_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True
    )

    # Suplantación en curso: quién es realmente quien opera.
    actor_real_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    motivo_suplantacion: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_sesiones_activas", "usuario_id", "revocada_at"),)

    @property
    def esta_viva(self) -> bool:
        from datetime import timezone as tz

        return self.revocada_at is None and self.expira_at > datetime.now(tz.utc)


class ClaveApi(Base, TimestampMixin):
    """Credencial de máquina (CRM-00.05.01.07).

    Se guarda el **hash** del secreto, no el secreto: se enseña una sola vez, al
    crearla, y si el cliente lo pierde se genera otra. Es incómodo a propósito —
    poder recuperar una clave existente significa que está guardada en claro y
    que quien acceda a la base se lleva todas.
    """

    __tablename__ = "claves_api"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    # Prefijo visible de la clave, para poder identificarla en una lista sin
    # revelar nada: `crm_a1b2…`. Sin él, ocho claves son ocho filas iguales.
    prefijo: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    hash_secreto: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    # Ámbitos concedidos. Acotan por encima de los permisos del rol asociado:
    # una integración con scope de lectura no escribe aunque su rol pueda.
    scopes: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    rol: Mapped[str] = mapped_column(String(80), nullable=False, default="integracion")
    # Redes desde las que se admite esta clave (CRM-00.02.04.04). Vacío = sin
    # restricción, que es cómodo y es exactamente lo que conviene evitar en una
    # credencial de integración de larga vida.
    ips_permitidas: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )

    expira_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revocada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ultimo_uso_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    creada_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)


class ProveedorIdentidad(Base, TimestampMixin, SoftDeleteMixin):
    """Proveedor de identidad externo del tenant (CRM-00.05.01.03).

    Varios simultáneos por tenant a propósito: una empresa con dos direcciones
    de correo tras una fusión, o empleados por Entra ID y partners por Google.
    El `dominio_email` decide a cuál se manda a cada quien.
    """

    __tablename__ = "proveedores_identidad"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)  # oidc | saml
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    dominio_email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Configuración del proveedor. Los secretos van cifrados dentro.
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # Correspondencia entre grupos del IdP y roles de aquí. Es lo que permite
    # que dar de alta a alguien sea cosa del departamento de sistemas y no del
    # administrador del CRM.
    mapeo_roles: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    jit_provisioning: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # ── Gobierno del SSO ──────────────────────────────────────────────────
    # Dominios de correo adicionales y alias (CRM-00.05.01.14). `dominio_email`
    # se queda como el principal por compatibilidad; esta lista es la que hace
    # que una empresa con seis dominios tras tres adquisiciones no necesite seis
    # proveedores iguales.
    dominios: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Aceptar aserciones que empiezan en el IdP (CRM-00.05.01.11). Va apagado
    # por defecto: sin `InResponseTo` que atar a una petición nuestra, una
    # aserción robada se puede reenviar, y activarlo tiene que ser una decisión
    # de alguien, no el estado de fábrica.
    permite_idp_initiated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Valores de `acr`/`amr` del IdP que se aceptan como segundo factor ya
    # cumplido (CRM-00.05.01.24). Vacío = no se delega y se pide aquí.
    acr_con_mfa: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Certificados de firma con su caducidad (CRM-00.05.01.15). Son una lista y
    # no uno solo porque una rotación bien hecha tiene los dos válidos a la vez:
    # con uno solo, cambiarlo es una ventana de caída para todo el tenant.
    certificados: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )

    __table_args__ = (UniqueConstraint("tenant_id", "nombre", name="uq_idp_nombre"),)


class DesafioFactor(Base):
    """Un código de un solo uso enviado por SMS o correo (CRM-00.05.01.17).

    El código se guarda **hasheado**, igual que una contraseña: quien lea la
    tabla no puede entrar con él. Y se guarda la fila y no solo el código porque
    lo que hace seguro un OTP no es el código, es el resto: que caduque pronto,
    que solo valga una vez y que el número de intentos esté contado. Sin eso,
    seis dígitos se agotan a fuerza bruta en minutos.
    """

    __tablename__ = "desafios_factor"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    usuario_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    canal: Mapped[str] = mapped_column(String(20), nullable=False)  # sms | email
    # Dirección de destino, enmascarada. Se guarda enmascarada porque esta fila
    # se enseña al usuario («te hemos enviado un código al ***34») y guardarla
    # entera la convertiría en una filtración de teléfonos.
    destino_visible: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    hash_codigo: Mapped[str] = mapped_column(String(64), nullable=False)
    # Para qué se pidió: entrar, o autorizar una operación concreta (step-up).
    proposito: Mapped[str] = mapped_column(String(40), nullable=False, default="entrar")
    intentos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    creado_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expira_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    usado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_desafios_usuario", "usuario_id", "usado_at"),)


class DispositivoConfianza(Base, TimestampMixin):
    """Un equipo en el que este usuario ya demostró tener el segundo factor
    (CRM-00.05.01.20).

    Sirve para no pedir el factor en cada entrada desde el mismo portátil, que
    es la razón número uno por la que la gente pide que le quiten la MFA. Tres
    cosas lo hacen aceptable y no un agujero:

    * **caduca** —la confianza no es para siempre—;
    * **se revoca en remoto**, uno a uno o todos, que es lo que hace útil la
      lista cuando alguien pierde el portátil;
    * y **es por usuario y tenant**, no por equipo: un ordenador compartido no
      hereda la confianza de quien lo usó antes.
    """

    __tablename__ = "dispositivos_confianza"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    usuario_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    # Hash de la huella del dispositivo. Hasheada porque la huella en claro
    # identifica al equipo, y la tabla se consulta desde la pantalla de sesiones.
    hash_huella: Mapped[str] = mapped_column(String(64), nullable=False)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    ip_alta: Mapped[str | None] = mapped_column(
        String(64), nullable=True, info={"sensibilidad": "personal"}
    )
    expira_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ultimo_uso_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revocado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    motivo_revocacion: Mapped[str | None] = mapped_column(String(120), nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "usuario_id", "hash_huella", name="uq_dispositivo"),
    )


class SesionIdP(Base):
    """Lo que ata una sesión de aquí con la sesión del proveedor de identidad
    (CRM-00.05.01.12).

    Sin esta tabla no hay cierre de sesión único: cuando el IdP avisa de que la
    persona ha salido, lo que manda es **su** identificador de sesión
    (`SessionIndex` en SAML, `sid` en OIDC), que no se parece en nada al nuestro.
    Sin la correspondencia, el aviso llega y no hay a quién aplicárselo, y
    cerrar sesión en el IdP deja el CRM abierto — que es exactamente lo que el
    usuario cree que acaba de evitar.
    """

    __tablename__ = "sesiones_idp"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    sesion_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    proveedor_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    usuario_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    # El identificador de sesión del IdP. Es el que llega en el aviso de cierre.
    indice_idp: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    # El identificador del sujeto tal como lo da el IdP (NameID). Hay
    # proveedores que avisan del cierre por sujeto y no por sesión.
    sujeto_idp: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    creada_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    cerrada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_sesiones_idp_indice", "tenant_id", "indice_idp"),)


class AsercionConsumida(Base):
    """Aserciones SAML ya usadas, para que no se puedan reenviar
    (CRM-00.05.01.11).

    En el SSO que empieza aquí, la petición lleva un identificador propio y la
    respuesta tiene que citarlo (`InResponseTo`): eso ya impide el reenvío. En
    el que empieza en el IdP **no hay petición**, así que no hay nada que citar,
    y una aserción interceptada vale otra vez hasta que caduque.

    Lo único que lo cierra es recordar las que ya se han usado. Se guardan solo
    hasta que caduca la propia aserción: después es inútil por sí sola y la
    tabla no tiene por qué crecer para siempre.
    """

    __tablename__ = "aserciones_consumidas"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    # El `ID` de la aserción, hasheado: no aporta nada guardarlo en claro y sí
    # deja un rastro menos si la tabla se filtra.
    hash_asercion: Mapped[str] = mapped_column(String(64), nullable=False)
    proveedor_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    consumida_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expira_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (UniqueConstraint("tenant_id", "hash_asercion", name="uq_asercion_consumida"),)


# ── Tablas compartidas que viven en ESTE esquema ──────────────────────────
#
# Se importan aquí, y no solo donde se usan, porque `modelos.py` es lo que lee
# el generador de migraciones (`alembic/env.py`) y la fixture de pruebas para
# saber qué tablas tiene este servicio. Un modelo compartido que no aparezca
# aquí sencillamente **no se migra**: el código lo usa, la tabla no existe, y el
# fallo sale la primera vez que alguien lo ejerce en producción.
#
# Que la lista esté escrita a mano es deliberado: dice, en un sitio, qué tablas
# comunes guarda este servicio en su esquema. Descubrirlas automáticamente
# acabaría creando en todos los esquemas las tablas de todos.
from crmcore.authz.comparticion import ComparticionManual, ReglaComparticion  # noqa: E402
from crmcore.authz.politicas import PoliticaAbac, VersionPoliticaAbac  # noqa: E402
from crmcore.authz.proyeccion import PoliticaCampo  # noqa: E402
from crmcore.datos.papelera import EntradaPapelera  # noqa: E402
from crmcore.datos.retencion import BloqueoLegal, PoliticaRetencion  # noqa: E402
from crmcore.datos.seguimiento import (  # noqa: E402
    Notificacion,
    PreferenciaNotificacion,
    Seguimiento,
)
from crmcore.notificaciones.entrega import EntregaNotificacion  # noqa: E402
from crmcore.runtime.versiones import VersionAjuste  # noqa: E402
from crmcore.security.byok import ClaveTenant  # noqa: E402

from services.identity.sod import ExcepcionSoD, ReglaSoD  # noqa: E402
from services.identity.sso import EstadoSSO  # noqa: E402

__all__ = [
    "VersionAjuste",
    "AsercionConsumida",
    "DesafioFactor",
    "DispositivoConfianza",
    "SesionIdP",
    "ExcepcionSoD",
    "ReglaSoD",
    "PoliticaAbac",
    "VersionPoliticaAbac",
    "EntregaNotificacion",
    "ClaveTenant",
    "ClaveApi",
    "ComparticionManual",
    "EstadoSSO",
    "BloqueoLegal",
    "EntradaPapelera",
    "PoliticaCampo",
    "PoliticaRetencion",
    "Membresia",
    "Notificacion",
    "PreferenciaNotificacion",
    "ProveedorIdentidad",
    "ReglaComparticion",
    "RolTenant",
    "Seguimiento",
    "Sesion",
    "Usuario",
]


# Las actividades de tratamiento de este servicio (CRM-07.03.01.04). Se importa
# al final y solo por su efecto: declararlas al cargar los modelos es lo que
# garantiza que el RAT y los objetos no puedan separarse.
# Las plantillas de aviso, replicadas por evento desde `tenancy`: es lo que
# permite tener plantilla POR CANAL (CRM-06.02.01.07). Antes, el mismo texto iba
# al correo y al SMS recortado a 160.
from crmcore.notificaciones.plantillas_replicadas import (  # noqa: E402,F401
    PlantillaNotificacion,
)

from services.identity import tratamientos  # noqa: E402,F401

# Las tablas del chat interno (CRM-06.02.02). Se importan aquí para que las
# migraciones las vean: un modelo que solo importa su API nace sin tabla, y el
# fallo aparece la primera vez que alguien escribe un mensaje.
from services.identity.chat import (  # noqa: E402,F401
    ConversacionChat,
    MensajeChat,
    MiembroConversacion,
    Presencia,
    ReaccionMensaje,
)
