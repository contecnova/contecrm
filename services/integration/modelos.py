"""Modelo de datos de las integraciones."""

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


class Conexion(Base, TimestampMixin, SoftDeleteMixin):
    """Una conexión a un sistema externo, declarada, no programada."""

    __tablename__ = "conexiones"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    # Qué sistema es, en texto libre y para información: `sap`, `holded`, `odoo`.
    # NO cambia el comportamiento — el comportamiento sale de `config`. Si el
    # tipo decidiera algo, volveríamos a tener código por proveedor.
    sistema: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    descripcion: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # rest | soap | sftp | fichero | amqp. De momento solo `rest` está
    # implementado; los demás llegan en la fase 2 y el campo existe ya para que
    # el modelo no tenga que cambiar entonces.
    protocolo: Mapped[str] = mapped_column(String(20), nullable=False, default="rest")
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Última prueba de conectividad (CRM-00.03.04.05): cuándo y con qué
    # resultado. Sin esto, una credencial caducada se descubre cuando falla un
    # proceso de negocio, no antes.
    probada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    prueba_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    prueba_detalle: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (UniqueConstraint("tenant_id", "nombre", name="uq_conexion_nombre"),)


class Credencial(Base, TimestampMixin):
    """Secretos de una conexión, cifrados y rotables.

    Separados de la conexión para poder rotarlos sin tocar la configuración, y
    para que quien puede editar un mapeo no tenga por qué poder leer una clave.
    """

    __tablename__ = "credenciales"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    conexion_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("conexiones.id", ondelete="CASCADE"), nullable=False
    )
    # Valores cifrados con la clave del tenant. Nunca se devuelven por la API:
    # se escriben y se usan, pero no se leen.
    valores: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Rotación: cuándo caduca y cuándo se avisó. Una credencial sin fecha de
    # caducidad es una que nadie rota nunca.
    caduca_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rotada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (Index("ix_credenciales_conexion", "conexion_id", "activa"),)


class Operacion(Base, TimestampMixin):
    """Una llamada declarada sobre una conexión.

    «Leer clientes», «crear pedido», «consultar stock». Lleva la ruta, el
    método, los parámetros, dónde están los resultados en la respuesta, cómo se
    pagina y el mapeo a los campos de contecrm.
    """

    __tablename__ = "operaciones"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    conexion_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("conexiones.id", ondelete="CASCADE"), nullable=False
    )
    clave: Mapped[str] = mapped_column(String(120), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    definicion: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # ── Cuándo se ejecuta sola ────────────────────────────────────────────
    #
    # Hasta el 05-10-2026 **nunca**: el conector estaba completo y sólo lo
    # disparaba una ruta a mano. Una integración que hay que ejecutar pulsando
    # un botón no es una integración, es una pantalla — y por eso las
    # decisiones que la gobiernan (cuándo avanzar la marca, cómo reintentar, a
    # qué ritmo traer la primera carga) estaban escritas, probadas y sin que
    # las llamara nadie.
    #
    # La cadencia es **de la operación**, no un valor global: leer el maestro de
    # clientes una vez al día y consultar el stock cada cinco minutos son la
    # misma pieza con ritmos distintos. Cero significa «sólo a mano», que es el
    # comportamiento que tenían todas antes y por tanto el de serie.
    cada_minutos: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    proxima_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    ultima_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # La marca del incremento, **tal cual la dio el proveedor**. Traducirla a un
    # formato común sería inventar un estándar que se rompe con el primer
    # proveedor que cambie de forma.
    marca: Mapped[str] = mapped_column(
        String(300), nullable=False, default="", server_default=text("''")
    )
    # Fallos seguidos y hasta cuándo está en reposo. Lo segundo sale de lo que
    # diga el proveedor (`Retry-After`): reintentar antes gasta cuota para que
    # vuelva a decir que no, y de paso parece un ataque.
    intentos: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    pausada_hasta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ultimo_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Estado que el transporte necesita entre pasadas. Hoy sólo lo usa el SFTP,
    # para contar cuántas veces ha visto un fichero a medio escribir: ese
    # contador vivía en memoria del proceso, y **en memoria se pierde al
    # reiniciar**, así que un fichero atascado desde hace tres días volvía a
    # empezar de cero y el aviso no saltaba nunca. La propia función lo dejó
    # dicho; aquí está el sitio donde guardarlo.
    estado_transporte: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    __table_args__ = (
        UniqueConstraint("conexion_id", "clave", name="uq_operacion_clave"),
        Index("ix_operaciones_programadas", "tenant_id", "activa", "proxima_at"),
    )


class RegistroRecibido(Base):
    """Un registro que entró por una integración, antes de que nadie decida nada.

    **Es la respuesta a «dónde van los resultados».** Sin un sitio donde
    aterrizar, una ejecución programada sólo podía dejar un contador en la traza
    y tirar lo leído, que es la forma más cara de no integrar nada.

    Lo que aterriza ya viene con los nombres de campo de contecrm —el mapeo es
    parte de la configuración— así que quien lo consuma no sabe nada de la API
    de origen.

    **La clave es el identificador externo**, y es lo que hace que la
    sincronización sea idempotente. Es la misma lección que `elementos_buzon`
    lleva escrita: sin él, una reunión aparece cuatro veces en la ficha porque
    el calendario reenvía el evento cada vez que alguien lo toca.

    No se queda para siempre: es una copia de datos de un sistema ajeno, y
    guardarla sin plazo es acumular datos personales de los que no somos
    responsables (`INTEGRACION_REGISTROS_RETENCION_DIAS`).
    """

    __tablename__ = "registros_recibidos"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    conexion_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    operacion: Mapped[str] = mapped_column(String(120), nullable=False)
    # Lo pone el sistema copiándolo del origen, nunca una persona: por eso va
    # marcado como no editable. Un formulario que lo pidiera a mano invitaría a
    # inventarse una clave, y la clave es justo lo que hace que el mismo pedido
    # no entre cuatro veces.
    externo_id: Mapped[str] = mapped_column(String(300), nullable=False)
    datos: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # recibido | procesado | descartado. Lo tercero con su motivo: un registro
    # que no entra y no dice por qué manda a mirar al sistema de origen, donde
    # el dato está bien.
    estado: Mapped[str] = mapped_column(
        String(20), nullable=False, default="recibido", server_default=text("'recibido'")
    )
    porque: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "conexion_id", "operacion", "externo_id", name="uq_registro_recibido"
        ),
        Index("ix_registros_recibidos", "tenant_id", "estado", "created_at"),
    )


class Ejecucion(Base):
    """Traza de cada llamada a un sistema externo (CRM-00.03.04.06).

    Es el monitor de integraciones. Guardar la petición y la respuesta
    recortadas es lo que permite depurar con el proveedor sin pedirle sus logs,
    que es la conversación que de otro modo dura una semana.
    """

    __tablename__ = "ejecuciones_integracion"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    conexion_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    operacion: Mapped[str] = mapped_column(String(120), nullable=False)
    # ok | error | parcial
    resultado: Mapped[str] = mapped_column(String(20), nullable=False)
    registros: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    paginas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duracion_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Parámetros de la llamada, ya sin secretos.
    parametros: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_ejecuciones_conexion", "tenant_id", "conexion_id", "created_at"),
        Index("ix_ejecuciones_resultado", "tenant_id", "resultado", "created_at"),
    )


# Tabla común: la clave propia del tenant (BYOK, CRM-00.01.04.09) se replica
# al esquema de cada servicio, porque cada uno cifra y descifra los campos de sus
# propias tablas dentro de sus transacciones.
# La papelera de este servicio. Su router se monta —`/<servicio>/papelera`— y sin
# la tabla la pantalla devolvía 500: `relation "papelera" does not exist`. El
# borrado es lógico y cada servicio guarda la suya en su esquema, que es lo que
# impide que uno lea las tablas de otro.
from crmcore.documental.firma_presencial import FirmaPresencial  # noqa: E402,F401
from crmcore.documental.plantillas import (  # noqa: E402,F401
    DocumentoGenerado,
    PlantillaDocumento,
)
from crmcore.security.byok import ClaveTenant  # noqa: E402,F401

# Las actividades de tratamiento de este servicio (CRM-07.03.01.04). Se importa
# al final y solo por su efecto: declararlas al cargar los modelos es lo que
# garantiza que el RAT y los objetos no puedan separarse.
from services.integration import tratamientos  # noqa: E402,F401
from services.integration.buzon import Buzon, ElementoSincronizado  # noqa: E402,F401
from services.integration.canales_entrada import (  # noqa: E402,F401
    CanalEntrada,
    Interaccion,
)
from services.integration.canonico import (  # noqa: E402,F401
    Adaptador,
    ConflictoSincronizacion,
    ObjetoCanonico,
    Vinculo,
)
from services.integration.colaboracion import CanalChat  # noqa: E402,F401
from services.integration.convivencia import (  # noqa: E402,F401
    ProgresoMigracion,
    ReglaConvivencia,
)

# Los encargos seguidos viven en su propio módulo porque tienen lógica propia
# —traducción de estados, ingesta ordenada, conciliación—, pero sus tablas son de
# este esquema y tienen que estar aquí: `alembic` solo importa `modelos.py`, y una
# tabla que no se importe no se migra y falla en la primera consulta, lejos.
from services.integration.encargos import (  # noqa: E402,F401
    Encargo,
    HitoEncargo,
    IncidenciaEncargo,
    Proveedor,
    ReglaProveedor,
)
from services.integration.federacion import Embebido, VistaFederada  # noqa: E402,F401

# La firma electrónica vive en su propio módulo —tiene su propia lógica de
# evidencia y de niveles—, pero sus tablas son de este esquema y tienen que
# importarse aquí: `alembic` solo mira `modelos.py`.
from services.integration.firma import (  # noqa: E402,F401
    EvidenciaFirma,
    Firmante,
    LlamadaProveedorFirma,
    PlantillaFirma,
    ProveedorFirma,
    ReglaProveedorFirma,
    Sobre,
)
from services.integration.manifiestos import Instalacion, Manifiesto  # noqa: E402,F401
from services.integration.mcp import (  # noqa: E402,F401
    Exposicion,
    Herramienta,
    LlamadaAgente,
)

# Suites de productividad: consentimiento por persona y suscripción a cambios
# (CRM-06.01.03.02, .05).
from services.integration.suites import (  # noqa: E402,F401
    ConsentimientoSuite,
    SuscripcionSuite,
)
from services.integration.telemetria import (  # noqa: E402,F401
    Dispositivo,
    EstadoRegla,
    Lectura,
    ReglaTelemetria,
)
