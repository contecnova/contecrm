"""Modelo de datos de cuentas, contactos y actividades."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from crmcore.db.base import (
    Base,
    EntidadBase,
    MetadatosMixin,
    SoftDeleteMixin,
    TimestampMixin,
)
from crmcore.ids import nuevo_id
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column


class Cuenta(EntidadBase, SoftDeleteMixin, MetadatosMixin):
    """Una organización: cliente, prospecto, partner, proveedor o competidor.

    Cubre CRM-01.01.01.01 (ficha con datos fiscales, comerciales y operativos) y
    CRM-01.01.01.02 (jerarquías multinivel, en `JerarquiaCuenta`).

    Los papeles no son excluyentes y por eso van en `roles`, no en un campo
    `tipo`: la misma empresa puede ser cliente de una división y proveedor de
    otra, y con un solo tipo habría que duplicarla.
    """

    __tablename__ = "cuentas"

    nombre: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    # Nombre comercial cuando difiere del legal. No es un capricho: la factura
    # lleva uno y el comercial conoce el otro, y buscar por el que no es acaba
    # en «este cliente no está» y en una ficha duplicada.
    nombre_comercial: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Clave canónica para detectar duplicados: nombre normalizado sin forma
    # jurídica. Se indexa porque es la primera criba de la deduplicación.
    clave_canonica: Mapped[str] = mapped_column(String(300), nullable=False, index=True)

    # cliente | prospecto | partner | proveedor | competidor | otro
    roles: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # activa | inactiva | bloqueada. Distinto de la papelera: una cuenta inactiva
    # existe y se consulta; una borrada está en la papelera.
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="activa")
    # Etapa del ciclo de vida, configurable por el tenant (lista maestra).
    ciclo_vida: Mapped[str | None] = mapped_column(String(60), nullable=True)

    # ── Segmentación (CRM-01.01.01.07) ────────────────────────────────────
    # Código de sector con su esquema declarado: CNAE en España, NAICS en
    # EE. UU., SIC en informes anglosajones. Guardar solo el número sin decir de
    # qué tabla es lo hace inservible al cruzarlo con datos externos.
    sector_esquema: Mapped[str | None] = mapped_column(String(10), nullable=True)
    sector_codigo: Mapped[str | None] = mapped_column(String(20), nullable=True)
    tamano: Mapped[str | None] = mapped_column(String(30), nullable=True)
    empleados: Mapped[int | None] = mapped_column(
        Integer, nullable=True, info={"sensibilidad": "confidencial"}
    )
    facturacion_anual: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2), nullable=True, info={"sensibilidad": "confidencial"}
    )
    moneda: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    # Clasificación comercial: tier (oro/plata/bronce) y ABC por valor.
    tier: Mapped[str | None] = mapped_column(String(30), nullable=True)
    clasificacion_abc: Mapped[str | None] = mapped_column(String(1), nullable=True)

    # ── Contacto y web ────────────────────────────────────────────────────
    web: Mapped[str | None] = mapped_column(String(500), nullable=True)
    telefono: Mapped[str | None] = mapped_column(
        String(40), nullable=True, info={"sensibilidad": "personal"}
    )
    email: Mapped[str | None] = mapped_column(
        String(320), nullable=True, info={"sensibilidad": "personal"}
    )
    # Dominio de correo, derivado de la web o del correo. Es la segunda señal
    # más fiable para detectar duplicados después del identificador fiscal.
    dominio: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)

    # ── Propiedad ─────────────────────────────────────────────────────────
    # Propietario comercial. De aquí salen las reglas de visibilidad por
    # propietario y la jerarquía de mando.
    owner_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True, index=True)
    business_unit_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    # ── Calidad del dato ──────────────────────────────────────────────────
    # Puntuación de completitud, recalculada al escribir (CRM-01.01.04.05).
    calidad: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Qué falta, para poder enseñarlo sin recalcular: ["nif", "sector"].
    calidad_faltan: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Cuando esta cuenta se fusionó en otra, a cuál. La fila se conserva en vez
    # de borrarse: hay documentos, correos y sistemas externos que apuntan a
    # este identificador, y borrarlo los deja apuntando al vacío.
    fusionada_en_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    __table_args__ = (
        Index("ix_cuentas_tenant_nombre", "tenant_id", "nombre"),
        Index("ix_cuentas_canonica", "tenant_id", "clave_canonica"),
        Index("ix_cuentas_owner", "tenant_id", "owner_id"),
        # Índice parcial sobre lo vivo: las consultas normales excluyen la
        # papelera y las fusionadas, y así no recorren lo que ya no se usa.
        Index(
            "ix_cuentas_vivas",
            "tenant_id",
            "estado",
            postgresql_where=text("deleted_at IS NULL AND fusionada_en_id IS NULL"),
        ),
    )


class IdentificadorFiscal(Base, TimestampMixin):
    """NIF, CIF, VAT o EIN de una cuenta (CRM-01.01.01.06).

    En plural porque un grupo con filiales en varios países tiene uno por país,
    y una sola columna obliga a elegir cuál se guarda — normalmente el del país
    de quien dio de alta la ficha.
    """

    __tablename__ = "identificadores_fiscales"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    cuenta_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("cuentas.id", ondelete="CASCADE"), nullable=False
    )
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)  # nif | cif | vat | ein
    pais: Mapped[str] = mapped_column(String(2), nullable=False, default="ES")
    valor: Mapped[str] = mapped_column(String(40), nullable=False)
    # Normalizado sin espacios ni guiones: es lo que se compara al deduplicar.
    valor_normalizado: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    principal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Estado de verificación contra el registro oficial (VIES para el VAT
    # intracomunitario). `None` = nunca comprobado, que es distinto de «no
    # válido»: uno es falta de información y el otro es un dato malo.
    verificado: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    verificado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verificacion_detalle: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "pais", "valor_normalizado", name="uq_fiscal_valor"),
    )


class Direccion(Base, TimestampMixin):
    """Dirección tipificada de una cuenta o de un contacto (CRM-01.01.01.05)."""

    __tablename__ = "direcciones"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    # Polimórfica: cuenta o contacto. Se guarda el tipo además del id porque el
    # mismo identificador no puede colisionar (son UUID) pero saber a qué apunta
    # sin consultarlo hace las listas mucho más baratas.
    objeto: Mapped[str] = mapped_column(String(20), nullable=False)
    objeto_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)

    # fiscal | envio | facturacion | visita | postal
    tipo: Mapped[str] = mapped_column(String(20), nullable=False, default="fiscal")
    principal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    linea1: Mapped[str] = mapped_column(String(300), nullable=False)
    linea2: Mapped[str | None] = mapped_column(String(300), nullable=True)
    codigo_postal: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ciudad: Mapped[str | None] = mapped_column(String(150), nullable=True)
    provincia: Mapped[str | None] = mapped_column(String(150), nullable=True)
    pais: Mapped[str] = mapped_column(String(2), nullable=False, default="ES")

    # Geocodificación. Se guarda como dos columnas y no como un tipo geográfico
    # para no exigir PostGIS: lo que hace falta hoy —distancias aproximadas y
    # pintar un mapa— se resuelve con esto.
    latitud: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    longitud: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    geocodificada_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Estado de validación postal: None = sin comprobar, True = existe.
    validada: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    __table_args__ = (Index("ix_direcciones_objeto", "tenant_id", "objeto", "objeto_id"),)


class JerarquiaCuenta(Base, TimestampMixin):
    """Relación padre–hijo entre cuentas, en una jerarquía concreta.

    **Varias jerarquías simultáneas** (CRM-01.01.01.03), y esa es la razón de que
    esto sea una tabla y no una columna `padre_id` en la cuenta: la estructura
    legal de un grupo no coincide con la comercial, ni con la de facturación, ni
    con la de entrega. Con una sola columna hay que elegir cuál se representa, y
    la que se pierde acaba viviendo en una hoja de cálculo.
    """

    __tablename__ = "jerarquias_cuenta"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    # legal | comercial | facturacion | entrega — o la que defina el tenant.
    jerarquia: Mapped[str] = mapped_column(String(40), nullable=False, default="legal")
    cuenta_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("cuentas.id", ondelete="CASCADE"), nullable=False
    )
    padre_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("cuentas.id", ondelete="CASCADE"), nullable=False
    )
    # Papel del hijo dentro de esa jerarquía: filial, delegación, centro…
    rol: Mapped[str | None] = mapped_column(String(60), nullable=True)
    porcentaje_participacion: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "jerarquia", "cuenta_id", name="uq_jerarquia_cuenta"),
        Index("ix_jerarquias_padre", "tenant_id", "jerarquia", "padre_id"),
    )


class RelacionCuenta(Base, TimestampMixin):
    """Relación NO jerárquica entre dos cuentas (CRM-01.01.01.04).

    Partner, competidor, proveedor, prescriptor. Separada de la jerarquía porque
    no implica pertenencia ni consolidación: que A sea partner de B no hace que
    los números de A sumen en B.
    """

    __tablename__ = "relaciones_cuenta"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    cuenta_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("cuentas.id", ondelete="CASCADE"), nullable=False
    )
    relacionada_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("cuentas.id", ondelete="CASCADE"), nullable=False
    )
    tipo: Mapped[str] = mapped_column(String(40), nullable=False)
    # La inversa se guarda explícita («es proveedor de» ↔ «es cliente de») en vez
    # de deducirse: no toda relación es simétrica y adivinar la inversa produce
    # etiquetas absurdas en la ficha del otro lado.
    tipo_inverso: Mapped[str | None] = mapped_column(String(40), nullable=True)
    notas: Mapped[str | None] = mapped_column(Text, nullable=True)
    desde: Mapped[date | None] = mapped_column(Date, nullable=True)
    hasta: Mapped[date | None] = mapped_column(Date, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "cuenta_id", "relacionada_id", "tipo", name="uq_relacion_cuenta"
        ),
    )


class MiembroEquipoCuenta(Base, TimestampMixin):
    """Equipo de cuenta con roles (CRM-01.01.01.10).

    El propietario es uno; el equipo es quien más trabaja la cuenta. Sin esta
    tabla, el técnico que lleva tres años atendiendo a un cliente no aparece en
    ningún sitio y su conocimiento se pierde cuando cambia el comercial.
    """

    __tablename__ = "equipo_cuenta"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    cuenta_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("cuentas.id", ondelete="CASCADE"), nullable=False
    )
    usuario_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    # owner | kam | tecnico | soporte | financiero | otro
    rol: Mapped[str] = mapped_column(String(40), nullable=False)
    # Acceso que concede pertenecer al equipo: lectura o escritura. Es una regla
    # de compartición, no un permiso global.
    acceso: Mapped[str] = mapped_column(String(20), nullable=False, default="lectura")
    desde: Mapped[date | None] = mapped_column(Date, nullable=True)
    hasta: Mapped[date | None] = mapped_column(Date, nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "cuenta_id", "usuario_id", "rol", name="uq_equipo_cuenta"),
    )


class Contacto(EntidadBase, SoftDeleteMixin, MetadatosMixin):
    """Una persona.

    **No cuelga de una cuenta.** La relación es N:M (`RelacionContactoCuenta`)
    porque una misma persona puede ser contacto de varias empresas —consultores,
    administradores de fincas, grupos— y porque cuando cambia de trabajo interesa
    seguirla, no duplicarla.
    """

    __tablename__ = "contactos"

    nombre: Mapped[str] = mapped_column(String(150), nullable=False)
    apellidos: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Nombre completo calculado, para buscar y para mostrar sin recomponerlo en
    # cada consulta. Se mantiene al escribir.
    nombre_completo: Mapped[str] = mapped_column(String(350), nullable=False, index=True)
    clave_canonica: Mapped[str] = mapped_column(String(350), nullable=False, index=True)

    tratamiento: Mapped[str | None] = mapped_column(String(20), nullable=True)
    cargo: Mapped[str | None] = mapped_column(String(150), nullable=True)
    # Cuándo se anonimizó por una solicitud de supresión (CRM-07.03.01.03). Es
    # distinto de borrar: la fila sigue, sin lo que identifica a la persona,
    # porque las referencias desde oportunidades y facturas tienen que seguir
    # apuntando a algo. Se guarda la fecha para que nadie intente «arreglar» el
    # nombre después creyendo que se perdió por un fallo.
    anonimizado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    departamento: Mapped[str | None] = mapped_column(String(150), nullable=True)

    # ── Canales (CRM-01.01.02.01) ─────────────────────────────────────────
    email: Mapped[str | None] = mapped_column(
        String(320), nullable=True, index=True, info={"sensibilidad": "personal"}
    )
    email_secundario: Mapped[str | None] = mapped_column(
        String(320), nullable=True, info={"sensibilidad": "personal"}
    )
    telefono: Mapped[str | None] = mapped_column(
        String(40), nullable=True, info={"sensibilidad": "personal"}
    )
    movil: Mapped[str | None] = mapped_column(
        String(40), nullable=True, info={"sensibilidad": "personal"}
    )
    # Canales que no son teléfono ni correo: LinkedIn, WhatsApp, Teams…
    # En JSONB porque la lista cambia con la moda y una columna por red obliga a
    # migrar el esquema cada vez que aparece una.
    canales: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    # ── Preferencias de contacto (CRM-01.01.02.05) ────────────────────────
    idioma: Mapped[str | None] = mapped_column(String(10), nullable=True)
    canal_preferido: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Franja horaria preferida y frecuencia máxima. No es cortesía: en muchos
    # países forma parte del cumplimiento, y en todos evita quemar al contacto.
    horario_preferido: Mapped[str | None] = mapped_column(String(60), nullable=True)
    frecuencia_maxima: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # `no_contactar` corta TODO, por encima de cualquier consentimiento. Es el
    # interruptor que un contacto enfadado espera que funcione de inmediato.
    no_contactar: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    owner_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True, index=True)
    estado_email: Mapped[str | None] = mapped_column(String(20), nullable=True)
    estado_telefono: Mapped[str | None] = mapped_column(String(20), nullable=True)
    calidad: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    calidad_faltan: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    fusionado_en_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    __table_args__ = (
        # El nombre lleva `tenant` para no colisionar con el índice que
        # `index=True` crea en la propia columna (`ix_contactos_email`).
        # La colisión hacía fallar la creación del esquema entero.
        Index("ix_contactos_tenant_email", "tenant_id", "email"),
        Index("ix_contactos_canonica", "tenant_id", "clave_canonica"),
        Index(
            "ix_contactos_vivos",
            "tenant_id",
            postgresql_where=text("deleted_at IS NULL AND fusionado_en_id IS NULL"),
        ),
    )


class RelacionContactoCuenta(Base, TimestampMixin):
    """Vínculo N:M entre un contacto y una cuenta (CRM-01.01.02.02).

    Con **vigencia**: cuando alguien cambia de empresa no se borra el vínculo
    anterior, se cierra. Así el histórico de una cuenta sigue teniendo sentido
    —quién firmó aquel contrato— y el contacto conserva su recorrido.
    """

    __tablename__ = "contacto_cuenta"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    contacto_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("contactos.id", ondelete="CASCADE"), nullable=False
    )
    cuenta_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("cuentas.id", ondelete="CASCADE"), nullable=False
    )
    rol: Mapped[str | None] = mapped_column(String(80), nullable=True)
    cargo: Mapped[str | None] = mapped_column(String(150), nullable=True)
    # Contacto principal de esa cuenta. Solo puede haber uno vivo, y lo garantiza
    # un índice único parcial en vez de la disciplina de quien escribe.
    principal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    desde: Mapped[date | None] = mapped_column(Date, nullable=True)
    hasta: Mapped[date | None] = mapped_column(Date, nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "contacto_id", "cuenta_id", name="uq_contacto_cuenta"),
        Index(
            "ix_contacto_cuenta_principal",
            "tenant_id",
            "cuenta_id",
            unique=True,
            postgresql_where=text("principal AND hasta IS NULL"),
        ),
    )


class Consentimiento(Base, TimestampMixin):
    """Consentimiento por finalidad y canal, con su base legal (CRM-01.01.02.06).

    Se guarda la **prueba**, no solo el «sí»: de dónde vino, cuándo y con qué
    texto. Un consentimiento sin prueba no vale nada ante una reclamación, que es
    exactamente cuando hace falta.

    Y se guarda **cada cambio como una fila nueva**, no se actualiza: la historia
    de consentimientos de una persona es lo que demuestra que en el momento del
    envío había permiso.
    """

    __tablename__ = "consentimientos"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    contacto_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("contactos.id", ondelete="CASCADE"), nullable=False
    )
    # comercial | newsletter | encuestas | perfilado | cesion_terceros
    finalidad: Mapped[str] = mapped_column(String(60), nullable=False)
    canal: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # email | sms | telefono | postal
    concedido: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # consentimiento | interes_legitimo | contrato | obligacion_legal
    base_legal: Mapped[str] = mapped_column(String(40), nullable=False, default="consentimiento")

    # La prueba: origen, texto aceptado y evidencia técnica.
    origen: Mapped[str | None] = mapped_column(String(80), nullable=True)
    texto_aceptado: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidencia: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    fecha: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Caducidad, para las jurisdicciones o políticas que exigen renovarlo.
    caduca_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index(
            "ix_consentimientos_vigente", "tenant_id", "contacto_id", "finalidad", "canal", "fecha"
        ),
    )


class Actividad(EntidadBase, SoftDeleteMixin):
    """Tarea, llamada, reunión, nota o visita (CRM-01.02.01.01).

    **Un solo modelo para los cinco tipos**, y no cinco tablas. La razón es el
    timeline: la vista 360 de una cuenta tiene que ordenar cronológicamente todo
    lo que ha pasado, y con cinco tablas eso es una unión de cinco consultas que
    hay que ampliar cada vez que aparece un tipo nuevo.

    La relación con el objeto es **polimórfica** (CRM-01.02.01.03): una actividad
    puede colgar de una cuenta, un contacto, una oportunidad, un caso o un objeto
    propio del tenant.
    """

    __tablename__ = "actividades"

    # tarea | llamada | reunion | nota | visita | email
    tipo: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    asunto: Mapped[str] = mapped_column(String(300), nullable=False)
    cuerpo: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Relación polimórfica ──────────────────────────────────────────────
    objeto: Mapped[str | None] = mapped_column(String(60), nullable=True)
    objeto_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    # Cuenta y contacto se desnormalizan además del objeto polimórfico: el
    # timeline de una cuenta tiene que traer también las actividades colgadas de
    # sus oportunidades y sus casos, y sin estas columnas eso exige recorrer el
    # grafo en cada consulta.
    cuenta_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True, index=True)
    contacto_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True, index=True
    )

    # ── Estado y asignación ───────────────────────────────────────────────
    # pendiente | en_curso | completada | cancelada
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="pendiente")
    prioridad: Mapped[str] = mapped_column(String(20), nullable=False, default="normal")
    asignada_a: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True, index=True)
    delegada_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    vence_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    inicio_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fin_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Recordatorio: cuándo avisar. Nulo = sin recordatorio.
    recordar_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    recordatorio_enviado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # ── Datos propios del tipo ────────────────────────────────────────────
    # Duración de una llamada, asistentes de una reunión, coordenadas de una
    # visita. En JSONB porque son distintos por tipo y una columna por cada uno
    # deja la tabla llena de nulos.
    detalles: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    resultado: Mapped[str | None] = mapped_column(String(80), nullable=True)

    __table_args__ = (
        Index("ix_actividades_timeline", "tenant_id", "cuenta_id", "created_at"),
        Index("ix_actividades_objeto", "tenant_id", "objeto", "objeto_id"),
        Index(
            "ix_actividades_pendientes",
            "tenant_id",
            "asignada_a",
            "vence_at",
            postgresql_where=text("estado IN ('pendiente','en_curso') AND deleted_at IS NULL"),
        ),
    )

    @property
    def esta_vencida(self) -> bool:
        from datetime import timezone as tz

        return (
            self.vence_at is not None
            and self.estado in ("pendiente", "en_curso")
            and self.vence_at < datetime.now(tz.utc)
        )


class Fusion(Base, TimestampMixin):
    """Registro de una fusión de duplicados (CRM-01.01.04.03).

    Se guarda qué se fusionó en qué, qué valores sobrevivieron y qué relaciones
    se reparentaron. Es lo que permite responder a «¿dónde ha ido esta ficha?» y,
    si la fusión estuvo mal hecha, reconstruir qué había antes.
    """

    __tablename__ = "fusiones"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    objeto: Mapped[str] = mapped_column(String(30), nullable=False)  # cuenta | contacto
    superviviente_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    absorbido_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    # Estado completo del absorbido antes de fusionar. Es la única forma de
    # deshacer una fusión equivocada, y las fusiones equivocadas existen.
    estado_previo: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # Qué campo se quedó de cuál.
    supervivencia: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    relaciones_movidas: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    fusionado_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    motivo: Mapped[str | None] = mapped_column(Text, nullable=True)
    deshecha_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SolicitudDerechos(Base, TimestampMixin):
    """Solicitud de derechos del interesado (CRM-07.03.01.03).

    Acceso, rectificación, supresión, portabilidad, oposición y limitación. Lleva
    **plazo legal** calculado al recibirla: un mes desde la recepción, que es lo
    que exige el RGPD, y el aviso salta antes de que venza — no el día después.
    """

    __tablename__ = "solicitudes_derechos"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    contacto_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    # Se guarda también el correo: una solicitud puede llegar de alguien que no
    # está identificado todavía en el sistema, y tiene el mismo plazo legal.
    email_solicitante: Mapped[str] = mapped_column(String(320), nullable=False)
    tipo: Mapped[str] = mapped_column(String(30), nullable=False)
    # recibida | verificando_identidad | en_curso | resuelta | rechazada
    estado: Mapped[str] = mapped_column(String(30), nullable=False, default="recibida")
    canal_entrada: Mapped[str | None] = mapped_column(String(40), nullable=True)

    recibida_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    vence_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    resuelta_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolucion: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Evidencia de la respuesta: qué se entregó o qué se borró, y cuándo.
    evidencia: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    responsable_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    __table_args__ = (Index("ix_solicitudes_pendientes", "tenant_id", "estado", "vence_at"),)


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
from crmcore.busqueda import DocumentoIndexado  # noqa: E402
from crmcore.datos.adjuntos import Adjunto, DescargaAdjunto  # noqa: E402
from crmcore.datos.comentarios import Comentario  # noqa: E402
from crmcore.datos.papelera import EntradaPapelera  # noqa: E402
from crmcore.datos.retencion import BloqueoLegal, PoliticaRetencion  # noqa: E402
from crmcore.datos.trabajos import Trabajo  # noqa: E402
from crmcore.documental.enlaces import DocumentoEnlazado, OrganizacionDocumental  # noqa: E402
from crmcore.security.byok import ClaveTenant  # noqa: E402

__all__ = [
    "PoliticaAbac",
    "VersionPoliticaAbac",
    "DocumentoEnlazado",
    "OrganizacionDocumental",
    "ComparticionManual",
    "ReglaComparticion",
    "ClaveTenant",
    "Actividad",
    "Adjunto",
    "Comentario",
    "Consentimiento",
    "Contacto",
    "Cuenta",
    "DescargaAdjunto",
    "Direccion",
    "BloqueoLegal",
    "DocumentoIndexado",
    "EntradaPapelera",
    "PoliticaCampo",
    "PoliticaRetencion",
    "Trabajo",
    "Fusion",
    "IdentificadorFiscal",
    "JerarquiaCuenta",
    "MiembroEquipoCuenta",
    "RelacionContactoCuenta",
    "RelacionCuenta",
    "SolicitudDerechos",
]
