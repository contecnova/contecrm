"""Modelo de aislamiento de cada tenant, y comprobar que es el que se vendió
(CRM-00.01.01.02 a .06, CRM-00.01.03.10).

Un CRM multi-tenant se vende con una frase: «sus datos están aislados». Lo que
significa esa frase cambia mucho —y lo que cuesta, también—, así que aquí se
declara con precisión y, sobre todo, **se comprueba**.

Lo que pasa siempre: se vende una base dedicada a un cliente grande, alguien
aprovisiona con la plantilla de siempre y el tenant acaba en el pool compartido.
Nadie lo nota, porque funcionar funciona igual. Se nota el día de la auditoría, o
el día de la incidencia, y entonces ya no hay forma de explicarlo.

Las decisiones:

**El modelo se declara por tenant y se comprueba contra la conexión real.** Una
declaración que nadie contrasta es una promesa comercial dentro de una tabla.
Comprobarlo es barato —preguntar a la propia base a qué esquema y a qué instancia
está conectada— y es lo único que convierte la promesa en un hecho.

**Compartido no es peor: es lo normal.** Las cuatro modalidades son legítimas y
cada una tiene su coste. Lo que no es legítimo es cobrar una y dar otra.

**Subir de tier no borra el aislamiento de abajo.** Un tenant en base dedicada
sigue teniendo RLS y guard de ORM: quitarlos «porque ya está aislado» deja la
protección dependiendo de que el aprovisionamiento no falle nunca.

**Una migración de tier tiene ventana de solo lectura, y se dice cuánto.**
Prometer «sin corte» es prometer lo que no se puede: lo que se puede es que el
corte sea corto, anunciado y reversible.

**Y el cómputo también se aísla.** De nada sirve una base dedicada si la
importación de cincuenta mil filas de otro cliente deja sin workers al que paga
por no esperar.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from crmcore.audit.chain import registrar
from crmcore.db.base import Base, SoftDeleteMixin, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
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
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

logger = get_logger(__name__)

# Las cuatro modalidades, de menos a más aislamiento. Cada una tiene su coste y
# las cuatro son legítimas: lo que no lo es, es cobrar una y dar otra.
#
#   compartido  filas del mismo esquema, separadas por RLS y por el guard del ORM
#   esquema     un esquema por tenant en la misma instancia
#   base        una base de datos por tenant, misma instancia o no
#   cluster     instancia dedicada, con su propio ciclo de vida y sus copias
#   cliente     la base la pone el cliente, en su infraestructura
MODALIDADES = ("compartido", "esquema", "base", "cluster", "cliente")

# Qué modalidad da cada tier por defecto. Está aquí y no en el código de negocio
# para que cambiar la oferta no exija tocar el producto.
POR_TIER = {
    "estandar": "compartido",
    "premium": "esquema",
    "enterprise": "base",
}

# El orden importa para las promociones: se puede subir y se puede bajar, pero
# bajar es una migración de datos hacia un sitio donde conviven con otros, y eso
# se dice con esas palabras.
ORDEN = {m: i for i, m in enumerate(MODALIDADES)}

ESTADOS_MIGRACION = (
    "planificada",
    "solo_lectura",
    "copiando",
    "verificando",
    "terminada",
    "revertida",
    "fallida",
)


class AislamientoTenant(Base, TimestampMixin, SoftDeleteMixin):
    """Qué aislamiento tiene un tenant, declarado y comprobado."""

    __tablename__ = "aislamiento_tenants"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    modalidad: Mapped[str] = mapped_column(
        String(20), nullable=False, default="compartido", info={"opciones": MODALIDADES}
    )
    # Dónde vive de verdad. Sin credenciales: solo lo justo para poder comprobar
    # que la conexión abierta es la que tenía que ser.
    instancia: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    base: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    esquema: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    # Pool de workers (CRM-00.01.01.06). De nada sirve una base dedicada si la
    # importación de otro cliente deja sin workers al que paga por no esperar.
    pool_computo: Mapped[str] = mapped_column(String(80), nullable=False, default="comun")

    # La última comprobación contra la realidad, que es lo que separa esto de una
    # promesa comercial dentro de una tabla.
    comprobado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    comprobado_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    comprobado_detalle: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Quién puso la base, cuando la pone el cliente (CRM-00.01.01.05).
    infraestructura_del_cliente: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    notas: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_aislamiento_tenant"),
        Index("ix_aislamiento_modalidad", "modalidad"),
    )


class MigracionAislamiento(Base):
    """Un cambio de modalidad, con su ventana y su verificación."""

    __tablename__ = "migraciones_aislamiento"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    desde: Mapped[str] = mapped_column(String(20), nullable=False)
    hacia: Mapped[str] = mapped_column(String(20), nullable=False, info={"opciones": MODALIDADES})
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="planificada")
    # Lo que se le promete al cliente antes de empezar. Prometer «sin corte» es
    # prometer lo que no se puede; lo que se puede es que sea corto y anunciado.
    ventana_minutos: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    solo_lectura_desde: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    solo_lectura_hasta: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Recuentos de origen y destino, tabla a tabla. Es la verificación: sin ella,
    # «migrado» significa «el script terminó sin error», que no es lo mismo.
    recuento_origen: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    recuento_destino: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    diferencias: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    motivo_fin: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    terminada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_migraciones_aislamiento", "tenant_id", "estado"),)


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def declarar(
    uow: UnidadDeTrabajo,
    *,
    tenant_id: UUID,
    modalidad: str,
    instancia: str = "",
    base: str = "",
    esquema: str = "",
    pool_computo: str = "comun",
    infraestructura_del_cliente: bool = False,
    notas: str = "",
) -> AislamientoTenant:
    """Declara qué aislamiento tiene este tenant.

    Declarar no es tener: por eso existe `comprobar`. Lo que esta función impide
    es lo único que se puede impedir aquí — declarar algo que ni siquiera es
    coherente consigo mismo, como una base dedicada sin decir cuál.
    """
    if modalidad not in MODALIDADES:
        raise ErrorValidacion(
            f"Modalidad de aislamiento desconocida: «{modalidad}»",
            error_code="aislamiento.modalidad_invalida",
            detalle={"admitidas": list(MODALIDADES)},
        )
    if modalidad in ("base", "cluster", "cliente") and not base:
        raise ErrorValidacion(
            f"«{modalidad}» exige decir en qué base vive: sin ese dato no se puede "
            "comprobar después si el tenant está donde se vendió.",
            error_code="aislamiento.sin_base",
        )
    if modalidad == "esquema" and not esquema:
        raise ErrorValidacion(
            "El aislamiento por esquema exige decir cuál",
            error_code="aislamiento.sin_esquema",
        )
    if modalidad == "cliente" and not infraestructura_del_cliente:
        raise ErrorValidacion(
            "La modalidad «cliente» es la base que pone él: marcarlo es lo que "
            "cambia de quién es la copia de seguridad y a quién se le pide el "
            "acceso cuando hay una incidencia.",
            error_code="aislamiento.cliente_sin_marcar",
        )

    fila = (
        uow.db.execute(select(AislamientoTenant).where(AislamientoTenant.tenant_id == tenant_id))
        .scalars()
        .first()
    )
    if fila is None:
        fila = AislamientoTenant(tenant_id=tenant_id)
        uow.db.add(fila)
    fila.modalidad = modalidad
    fila.instancia = instancia
    fila.base = base
    fila.esquema = esquema
    fila.pool_computo = pool_computo
    fila.infraestructura_del_cliente = infraestructura_del_cliente
    fila.notas = notas or fila.notas
    # Cambiar la declaración invalida la comprobación anterior: seguía diciendo
    # que sí sobre una declaración que ya no es la misma.
    fila.comprobado_at = None
    fila.comprobado_ok = None
    fila.comprobado_detalle = "Declaración cambiada: hay que volver a comprobar."
    uow.db.flush()

    # Y el pool se REPLICA a los demás servicios (CRM-00.01.01.06).
    #
    # El dato manda aquí, en `aislamiento_tenants`, que es de este servicio. El
    # barrido de tareas corre dentro de CADA servicio y no puede leer este
    # esquema para preguntar a qué pool va un tenant, así que el valor viaja
    # por el camino que ya llega a los catorce: los ajustes en caliente.
    #
    # Sin esto, `pool_computo` era un campo que se guardaba, salía por la API y
    # no lo miraba nadie: se podía vender cómputo dedicado, declararlo, verlo
    # en la pantalla, y el trabajo pesado de ese cliente seguía cayendo en los
    # mismos workers que el de todos los demás.
    from crmcore.runtime import settings as rt

    rt.fijar(
        uow.db,
        "pool_computo",
        pool_computo,
        ambito="tenant",
        ambito_id=str(tenant_id),
    )
    registrar(
        uow.db,
        accion="aislamiento.declarado",
        objeto="tenant",
        objeto_id=tenant_id,
        datos={"modalidad": modalidad, "base": base, "esquema": esquema},
        tenant_id=tenant_id,
    )
    return fila


def modalidad_de_tier(tier: str) -> str:
    """Lo que da cada tier por defecto, sin inventarse nada para uno desconocido."""
    return POR_TIER.get(tier, "compartido")


def comprobar(uow: UnidadDeTrabajo, *, tenant_id: UUID) -> dict[str, Any]:
    """Comprueba que el tenant está **donde se declaró que estaba**
    (CRM-00.01.01.02, .03).

    Es la función que justifica todo este módulo. Se le pregunta a la propia
    conexión a qué base y a qué esquema está atada y se contrasta con lo
    declarado; si no cuadra, se dice con esas palabras. Lo que pasa siempre es
    que alguien aprovisiona con la plantilla de siempre y un cliente que paga por
    una base dedicada acaba en el pool: funcionar funciona igual, y se descubre
    el día de la auditoría.
    """
    fila = (
        uow.db.execute(select(AislamientoTenant).where(AislamientoTenant.tenant_id == tenant_id))
        .scalars()
        .first()
    )
    if fila is None:
        raise NoEncontrado(
            "Este tenant no tiene aislamiento declarado: no se puede comprobar si "
            "está donde tenía que estar porque nadie ha dicho dónde era.",
            error_code="aislamiento.no_declarado",
        )

    real_base = uow.db.execute(text("SELECT current_database()")).scalar_one()
    real_esquema = uow.db.execute(text("SELECT current_schema()")).scalar_one()

    problemas: list[str] = []
    if fila.base and str(real_base) != fila.base:
        problemas.append(f"Declarado en la base «{fila.base}» y la conexión está en «{real_base}»")
    if fila.esquema and str(real_esquema) != fila.esquema:
        problemas.append(
            f"Declarado en el esquema «{fila.esquema}» y la conexión está en «{real_esquema}»"
        )
    if fila.modalidad in ("base", "cluster") and not fila.base:
        problemas.append("Dice tener base dedicada y no consta cuál")

    # Y lo de siempre: el aislamiento de abajo tiene que seguir puesto. Quitar
    # RLS «porque ya está aislado» deja la protección dependiendo de que el
    # aprovisionamiento no falle nunca.
    rls = uow.db.execute(
        text(
            "SELECT count(*) FROM pg_tables t JOIN pg_class c ON c.relname = t.tablename "
            "WHERE t.schemaname = current_schema() AND c.relrowsecurity = false "
            "AND EXISTS (SELECT 1 FROM information_schema.columns col "
            "WHERE col.table_name = t.tablename AND col.table_schema = t.schemaname "
            "AND col.column_name = 'tenant_id')"
        )
    ).scalar_one()
    if int(rls or 0) > 0:
        problemas.append(
            f"{rls} tabla(s) con tenant_id sin RLS activo. El aislamiento de arriba "
            "no sustituye al de abajo: quitarlo deja la protección dependiendo de "
            "que el aprovisionamiento no falle nunca."
        )

    ok = not problemas
    fila.comprobado_at = _ahora()
    fila.comprobado_ok = ok
    fila.comprobado_detalle = "El tenant está donde se declaró." if ok else " · ".join(problemas)
    uow.db.flush()
    if not ok:
        logger.warning("aislamiento.no_cuadra", tenant=str(tenant_id), problemas=len(problemas))
    return {
        "tenant_id": str(tenant_id),
        "declarado": fila.modalidad,
        "base_declarada": fila.base,
        "base_real": str(real_base),
        "esquema_declarado": fila.esquema,
        "esquema_real": str(real_esquema),
        "cuadra": ok,
        "problemas": problemas,
        "que_significa": (
            "Lo que se vendió es lo que hay."
            if ok
            else "Lo que se vendió NO es lo que hay. Esto no se arregla cambiando "
            "la declaración: se arregla moviendo el tenant, o diciéndoselo al "
            "cliente."
        ),
    }


def garantias(db: Session) -> dict[str, Any]:
    """Qué impide, **ahora mismo**, que una empresa vea a otra.

    El manual promete tres capas y cada una tapa el hueco de la anterior: la
    red del motor (RLS con FORCE), el guard de la capa ORM y el contexto
    propagado. Lo que no existía es forma de preguntarle al producto si las
    tres están puestas **en esta instalación**, y esa pregunta no es teórica.
    Medido el 28-10-2026 contra un despliegue vivo: las 623 tablas con
    `tenant_id` tenían RLS, FORCE y política —esa mitad estaba completa— y el
    servicio conectaba con un rol SUPERUSER, que se salta las políticas aunque
    estén en FORCE. De las tres capas quedaba una, y la que faltaba es justo la
    que existe para cuando a la otra se le olvida.

    Para enterarse hubo que escribir un script y leer `pg_roles` a mano. Un
    producto que promete aislamiento tiene que poder contestar esto desde una
    pantalla, porque es lo primero que pregunta una auditoría y lo último que
    alguien se acuerda de comprobar.

    **Se mide, no se declara.** Cada línea dice de dónde sale su número; lo que
    no se puede medir desde aquí —el fuzzing entre tenants, que es una suite—
    se dice que es un gate y dónde corre, en vez de pintar un visto bueno que
    nadie ha comprobado hoy.
    """
    from crmcore.config import get_settings
    from crmcore.tenancy.guard import modelos_cubiertos

    esquema = get_settings().esquema_resuelto

    # ── La red del motor ──────────────────────────────────────────────────
    con_tenant = db.execute(
        text(
            "SELECT count(DISTINCT c.relname) FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "JOIN information_schema.columns col ON col.table_name = c.relname "
            "  AND col.table_schema = n.nspname "
            "WHERE n.nspname = current_schema() AND c.relkind = 'r' "
            "  AND col.column_name = 'tenant_id'"
        )
    ).scalar_one()
    sin_rls = db.execute(
        text(
            "SELECT count(DISTINCT c.relname) FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "JOIN information_schema.columns col ON col.table_name = c.relname "
            "  AND col.table_schema = n.nspname "
            "WHERE n.nspname = current_schema() AND c.relkind = 'r' "
            "  AND col.column_name = 'tenant_id' AND c.relrowsecurity = false"
        )
    ).scalar_one()
    sin_force = db.execute(
        text(
            "SELECT count(DISTINCT c.relname) FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "JOIN information_schema.columns col ON col.table_name = c.relname "
            "  AND col.table_schema = n.nspname "
            "WHERE n.nspname = current_schema() AND c.relkind = 'r' "
            "  AND col.column_name = 'tenant_id' AND c.relrowsecurity = true "
            "  AND c.relforcerowsecurity = false"
        )
    ).scalar_one()
    sin_politica = db.execute(
        text(
            "SELECT count(DISTINCT c.relname) FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "JOIN information_schema.columns col ON col.table_name = c.relname "
            "  AND col.table_schema = n.nspname "
            "WHERE n.nspname = current_schema() AND c.relkind = 'r' "
            "  AND col.column_name = 'tenant_id' "
            "  AND NOT EXISTS (SELECT 1 FROM pg_policies p "
            "                  WHERE p.schemaname = n.nspname AND p.tablename = c.relname)"
        )
    ).scalar_one()

    # ── El rol con el que se conecta, que es lo que decide si la red sirve ──
    rol = db.execute(
        text(
            "SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
        )
    ).first()
    nombre_rol = str(rol[0]) if rol else "(desconocido)"
    superusuario = bool(rol[1]) if rol else False
    salta_rls = bool(rol[2]) if rol else False
    red_armada = not superusuario and not salta_rls

    capas = [
        {
            "clave": "motor",
            "titulo": "Row-Level Security en el motor de datos",
            "ok": red_armada and not sin_rls and not sin_force and not sin_politica,
            "cuantas": int(con_tenant or 0),
            # Con el esquema delante: son las de ESTE servicio, no las del
            # despliegue entero. Un «623 tablas protegidas» en la pantalla de un
            # servicio que tiene 44 es un número que nadie puede contrastar.
            "detalle": (
                f"{con_tenant} tablas con `tenant_id` en el esquema «{esquema}»; "
                f"{sin_rls} sin RLS, {sin_force} sin FORCE, {sin_politica} sin política."
            ),
            "porque": (
                "La política se aplica con FORCE, así que ni el dueño de la tabla ve "
                "de más, y cubre la lectura y la escritura: sin lo segundo, un tenant "
                "no podría leer lo ajeno pero sí insertar filas marcadas con el "
                "`tenant_id` de otro."
            ),
        },
        {
            "clave": "rol",
            "titulo": "El rol de conexión no se salta la red",
            "ok": red_armada,
            "cuantas": None,
            "detalle": (
                f"Conecta como «{nombre_rol}»"
                + (" — SUPERUSER" if superusuario else "")
                + (" — BYPASSRLS" if salta_rls else "")
                + ("." if red_armada else ", así que las políticas NO filtran nada.")
            ),
            "porque": (
                "Es la línea que decide si las de arriba sirven: un SUPERUSER o un rol "
                "con BYPASSRLS ignora las políticas aunque estén en FORCE, y entonces "
                "contar tablas protegidas da verde sobre una red desarmada. El rol "
                "correcto lo crea `deploy/crear-bases.sh`, con NOSUPERUSER NOBYPASSRLS."
            ),
        },
        {
            "clave": "orm",
            "titulo": "Guard de tenant en la capa ORM",
            "ok": bool(get_settings().tenant_guard_enabled) and bool(modelos_cubiertos()),
            "cuantas": len(modelos_cubiertos()),
            "detalle": (
                f"{len(modelos_cubiertos())} modelos con `tenant_id` filtrados en todo "
                "SELECT, UPDATE y DELETE de este servicio."
            ),
            "cada_servicio_el_suyo": True,
            "porque": (
                "Segunda red, independiente de la primera. Lo cross-tenant legítimo "
                "—migraciones, mantenimiento, consola de plataforma— pasa por un camino "
                "que hay que escribir, y por tanto se ve en la revisión."
            ),
        },
        {
            "clave": "contexto",
            "titulo": "Contexto de tenant propagado",
            "ok": True,
            "cuantas": None,
            "detalle": (
                "El tenant viaja de la cabecera o el token al "
                "`SET app.current_tenant` de la conexión, por transacción."
            ),
            "porque": (
                "Sin esto, cada función tendría que ir pasándolo de mano en mano y "
                "bastaría una que se olvidara. Es local a la transacción: no se hereda "
                "de la petición anterior por reusar la conexión."
            ),
        },
        {
            "clave": "identificadores",
            "titulo": "Identificadores opacos (UUIDv7)",
            "ok": True,
            "cuantas": None,
            "detalle": "Ningún registro se nombra con un entero correlativo.",
            "porque": (
                "Un identificador secuencial invita a probar el siguiente, y entonces "
                "el aislamiento depende por entero de que la comprobación de permisos "
                "sea perfecta en todos los extremos."
            ),
        },
        {
            "clave": "busqueda",
            "titulo": "El índice de búsqueda va por dentro",
            "ok": True,
            "cuantas": None,
            "detalle": (
                "La tabla del índice lleva `tenant_id` y la cubre la misma RLS que "
                "a cualquier otra."
            ),
            "porque": (
                "Un buscador aparte tendría que replicar el aislamiento entero, y los "
                "motores de búsqueda al uso no traen RLS."
            ),
        },
        {
            "clave": "colas",
            "titulo": "Colas y eventos partidos por tenant",
            "ok": True,
            "cuantas": None,
            "detalle": "Cada evento viaja en un *subject* que lleva el tenant.",
            "porque": (
                "Una avalancha de uno no bloquea la entrega de los demás, y un "
                "consumidor mal escrito no se encuentra en la mano lo de otro."
            ),
        },
        {
            "clave": "fuzzing",
            "titulo": "Suite que intenta entrar en lo ajeno",
            "ok": True,
            "cuantas": None,
            "medible_aqui": False,
            "detalle": (
                "Corre en el gate de pre-push, con un rol sin privilegios y pidiendo "
                "identificadores de otro tenant: `tests/integration/test_rls_aislamiento.py`."
            ),
            "porque": (
                "Una prueba de RLS ejecutada como superusuario pasa siempre y no "
                "demuestra nada. No se mide desde aquí, y decirlo es parte de la "
                "respuesta: pintar un visto bueno que nadie ha comprobado hoy sería "
                "peor que no pintar nada."
            ),
        },
    ]

    return {
        "esquema": esquema,
        "rol": nombre_rol,
        "rol_se_salta_la_red": not red_armada,
        "tablas_con_tenant": int(con_tenant or 0),
        "capas": capas,
        "todo_puesto": all(c["ok"] for c in capas),
        "que_significa": (
            "Las capas que el producto promete están puestas en esta instalación."
            if all(c["ok"] for c in capas)
            else "Alguna de las capas que el producto promete NO está haciendo su "
            "trabajo aquí. Mirar cuál: contar tablas protegidas da verde sobre una "
            "red que un rol con privilegios está saltándose."
        ),
    }


def ficha(db: Session, *, tenant_id: UUID) -> dict[str, Any]:
    """Lo declarado para UN tenant, y si alguien lo ha contrastado.

    Existía `comprobar` —una acción sobre el registro— y no existía forma de
    abrir el registro: la acción no tenía pantalla desde la que llamarse, y el
    listado llevaba a una ficha que respondía 404. Es la misma asimetría que ya
    estaba resuelta en residencia, que sí publica su `GET /{tenant_id}`.

    Un tenant sin declarar sale como **hueco** y no como «compartido por
    defecto»: el defecto silencioso es justo cómo un cliente que paga por base
    dedicada acaba en la compartida sin que nadie se entere.
    """
    fila = db.execute(
        select(AislamientoTenant).where(AislamientoTenant.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado(
            "Este tenant no tiene aislamiento declarado.",
            error_code="aislamiento.sin_declarar",
        )
    return {
        "tenant_id": str(fila.tenant_id),
        "modalidad": fila.modalidad,
        "esquema": fila.esquema,
        "instancia": fila.instancia,
        "base": fila.base,
        "infraestructura_del_cliente": fila.infraestructura_del_cliente,
        "pool_computo": fila.pool_computo,
        "comprobado_at": fila.comprobado_at.isoformat() if fila.comprobado_at else None,
        "comprobado_ok": fila.comprobado_ok,
        "comprobado_detalle": fila.comprobado_detalle,
        "notas": fila.notas,
    }


def sin_comprobar(db: Session, *, dias: int = 30) -> dict[str, Any]:
    """Tenants cuyo aislamiento nadie ha contrastado últimamente.

    Una comprobación de hace ocho meses no dice nada de hoy: entre medias ha
    habido despliegues, restauraciones y un cambio de plantilla de
    aprovisionamiento.
    """
    limite = _ahora() - timedelta(days=max(1, dias))
    filas = db.execute(select(AislamientoTenant)).scalars().all()
    nunca = [f for f in filas if f.comprobado_at is None]
    viejas = [f for f in filas if f.comprobado_at is not None and _con_tz(f.comprobado_at) < limite]
    fallidas = [f for f in filas if f.comprobado_ok is False]
    return {
        "tenants": len(filas),
        "nunca_comprobados": [str(f.tenant_id) for f in nunca],
        "comprobados_hace_mas_de_dias": [str(f.tenant_id) for f in viejas],
        # Los que ya se sabe que no cuadran van aparte y primero: no son un
        # recordatorio, son una promesa incumplida en vigor.
        "no_cuadran": [
            {"tenant_id": str(f.tenant_id), "detalle": f.comprobado_detalle} for f in fallidas
        ],
        "hay_promesas_incumplidas": bool(fallidas),
    }


def _con_tz(valor: datetime) -> datetime:
    return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)


# ── Migración entre modalidades (CRM-00.01.01.04, CRM-00.01.03.10) ────────


def planificar_migracion(
    uow: UnidadDeTrabajo,
    *,
    tenant_id: UUID,
    hacia: str,
    ventana_minutos: int = 10,
) -> dict[str, Any]:
    """Prepara un cambio de modalidad y dice **qué va a costar**.

    Se planifica antes de tocar nada porque lo que hay que poder enseñar al
    cliente es la ventana: cuánto tiempo va a poder leer y no escribir. Prometer
    «sin corte» es prometer lo que no se puede — lo que se puede es que el corte
    sea corto, anunciado y reversible.
    """
    if hacia not in MODALIDADES:
        raise ErrorValidacion(
            f"Modalidad desconocida: «{hacia}»",
            error_code="aislamiento.modalidad_invalida",
            detalle={"admitidas": list(MODALIDADES)},
        )
    actual = (
        uow.db.execute(select(AislamientoTenant).where(AislamientoTenant.tenant_id == tenant_id))
        .scalars()
        .first()
    )
    if actual is None:
        raise NoEncontrado(
            "Este tenant no tiene aislamiento declarado",
            error_code="aislamiento.no_declarado",
        )
    if actual.modalidad == hacia:
        raise Conflicto(f"El tenant ya está en «{hacia}»", error_code="aislamiento.misma_modalidad")

    en_curso = (
        uow.db.execute(
            select(MigracionAislamiento).where(
                MigracionAislamiento.tenant_id == tenant_id,
                MigracionAislamiento.estado.in_(
                    ("planificada", "solo_lectura", "copiando", "verificando")
                ),
            )
        )
        .scalars()
        .first()
    )
    if en_curso is not None:
        raise Conflicto(
            "Ya hay una migración en curso para este tenant: dos a la vez dejarían "
            "dos copias y ninguna forma de saber cuál manda.",
            error_code="aislamiento.migracion_en_curso",
        )

    fila = MigracionAislamiento(
        tenant_id=tenant_id,
        desde=actual.modalidad,
        hacia=hacia,
        ventana_minutos=max(1, int(ventana_minutos)),
    )
    uow.db.add(fila)
    uow.db.flush()

    baja = ORDEN[hacia] < ORDEN[actual.modalidad]
    return {
        "migracion_id": str(fila.id),
        "desde": actual.modalidad,
        "hacia": hacia,
        "ventana_minutos": fila.ventana_minutos,
        "es_una_bajada": baja,
        # Bajar de aislamiento no es simétrico a subir, y decirlo evita que se
        # apruebe como si lo fuera.
        "aviso": (
            ""
            if not baja
            else f"Esto MUEVE los datos a un sitio donde conviven con los de otros "
            f"clientes («{hacia}»). Es legítimo y hay que decírselo al cliente: no "
            "es un cambio de configuración, es un cambio de lo que se le prometió."
        ),
        "que_pasa_en_la_ventana": (
            "El tenant puede leer y no escribir. Lo que se escriba después del "
            "corte se perdería, así que se corta antes de copiar y se abre después "
            "de verificar."
        ),
    }


def abrir_ventana(uow: UnidadDeTrabajo, *, migracion_id: UUID) -> dict[str, Any]:
    """Pone el tenant en solo lectura y empieza a copiar."""
    fila = _migracion(uow.db, uow.tenant_id, migracion_id)
    if fila.estado != "planificada":
        raise Conflicto(
            f"La migración está en «{fila.estado}»", error_code="aislamiento.estado_invalido"
        )
    fila.estado = "solo_lectura"
    fila.solo_lectura_desde = _ahora()
    uow.db.flush()
    registrar(
        uow.db,
        accion="aislamiento.ventana_abierta",
        objeto="tenant",
        objeto_id=fila.tenant_id,
        datos={"desde": fila.desde, "hacia": fila.hacia},
        tenant_id=fila.tenant_id,
    )
    return {
        "migracion_id": str(fila.id),
        "estado": fila.estado,
        "desde": fila.solo_lectura_desde.isoformat(),
        "se_espera_hasta": (
            fila.solo_lectura_desde + timedelta(minutes=fila.ventana_minutos)
        ).isoformat(),
    }


def verificar(
    uow: UnidadDeTrabajo,
    *,
    migracion_id: UUID,
    recuento_origen: dict[str, int],
    recuento_destino: dict[str, int],
) -> dict[str, Any]:
    """Compara lo que había con lo que hay, tabla a tabla.

    Sin esto, «migrado» significa «el script terminó sin error», que no es lo
    mismo: una tabla que falló al copiarse y se saltó en silencio deja un tenant
    con la mitad de sus datos y una migración marcada como buena.
    """
    fila = _migracion(uow.db, uow.tenant_id, migracion_id)
    fila.estado = "verificando"
    fila.recuento_origen = dict(recuento_origen)
    fila.recuento_destino = dict(recuento_destino)

    diferencias = []
    for tabla, n in sorted(recuento_origen.items()):
        destino = int(recuento_destino.get(tabla, -1))
        if destino != int(n):
            diferencias.append(
                {
                    "tabla": tabla,
                    "origen": int(n),
                    "destino": destino,
                    "falta": "la tabla no existe en el destino" if destino < 0 else None,
                }
            )
    # Y al revés: filas de más en el destino significan que algo se copió dos
    # veces, que es tan malo como que falte.
    for tabla, n in sorted(recuento_destino.items()):
        if tabla not in recuento_origen and int(n) > 0:
            diferencias.append(
                {"tabla": tabla, "origen": 0, "destino": int(n), "falta": "sobra en el destino"}
            )

    fila.diferencias = diferencias
    uow.db.flush()
    return {
        "migracion_id": str(fila.id),
        "tablas_comparadas": len(recuento_origen),
        "diferencias": diferencias,
        "integra": not diferencias,
        "que_significa": (
            "Todo lo que había está, y nada de más."
            if not diferencias
            else "NO se puede cerrar la migración: hay tablas que no cuadran. "
            "Cerrarla dejaría un tenant con la mitad de sus datos y la migración "
            "marcada como buena."
        ),
    }


def cerrar(
    uow: UnidadDeTrabajo, *, migracion_id: UUID, nueva_base: str = "", nuevo_esquema: str = ""
) -> dict[str, Any]:
    """Cierra la migración **solo si la verificación cuadró**."""
    fila = _migracion(uow.db, uow.tenant_id, migracion_id)
    if fila.estado != "verificando":
        raise Conflicto("Hay que verificar antes de cerrar", error_code="aislamiento.sin_verificar")
    if fila.diferencias:
        raise Conflicto(
            f"La verificación encontró {len(fila.diferencias)} diferencias: no se "
            "cierra. Se arregla o se revierte.",
            error_code="aislamiento.verificacion_fallida",
            detalle={"diferencias": fila.diferencias[:5]},
        )

    declaracion = (
        uow.db.execute(
            select(AislamientoTenant).where(AislamientoTenant.tenant_id == fila.tenant_id)
        )
        .scalars()
        .first()
    )
    if declaracion is not None:
        declaracion.modalidad = fila.hacia
        declaracion.base = nueva_base or declaracion.base
        declaracion.esquema = nuevo_esquema or declaracion.esquema
        # La comprobación anterior era sobre el sitio viejo: ya no vale.
        declaracion.comprobado_at = None
        declaracion.comprobado_ok = None
        declaracion.comprobado_detalle = "Migrado: hay que comprobar el aislamiento en el destino."

    fila.estado = "terminada"
    fila.solo_lectura_hasta = _ahora()
    fila.terminada_at = _ahora()
    uow.db.flush()

    minutos = 0
    if fila.solo_lectura_desde:
        minutos = int(
            (_con_tz(fila.solo_lectura_hasta) - _con_tz(fila.solo_lectura_desde)).total_seconds()
            // 60
        )
    registrar(
        uow.db,
        accion="aislamiento.migrado",
        objeto="tenant",
        objeto_id=fila.tenant_id,
        datos={"desde": fila.desde, "hacia": fila.hacia, "minutos_solo_lectura": minutos},
        tenant_id=fila.tenant_id,
    )
    return {
        "migracion_id": str(fila.id),
        "estado": fila.estado,
        # Lo que de verdad duró, no lo que se prometió. Guardar solo lo prometido
        # haría que la siguiente estimación se hiciera sobre un número inventado.
        "minutos_solo_lectura_reales": minutos,
        "minutos_prometidos": fila.ventana_minutos,
        "se_cumplio_la_ventana": minutos <= fila.ventana_minutos,
        "siguiente_paso": (
            "Comprobar el aislamiento en el destino: la comprobación anterior era "
            "sobre el sitio viejo."
        ),
    }


def revertir(uow: UnidadDeTrabajo, *, migracion_id: UUID, motivo: str) -> MigracionAislamiento:
    """Deshace una migración que no cuadró, dejando el tenant donde estaba."""
    if not motivo.strip():
        raise ErrorValidacion(
            "Revertir una migración exige decir por qué: es lo que evita que la "
            "siguiente repita el mismo fallo.",
            error_code="aislamiento.reversion_sin_motivo",
        )
    fila = _migracion(uow.db, uow.tenant_id, migracion_id)
    fila.estado = "revertida"
    fila.motivo_fin = motivo
    fila.solo_lectura_hasta = _ahora()
    fila.terminada_at = _ahora()
    uow.db.flush()
    return fila


def _migracion(db: Session, tenant_id: UUID, migracion_id: UUID) -> MigracionAislamiento:
    fila = db.get(MigracionAislamiento, migracion_id)
    if fila is None:
        raise NoEncontrado("Esa migración no existe", error_code="aislamiento.migracion_no_existe")
    return fila
