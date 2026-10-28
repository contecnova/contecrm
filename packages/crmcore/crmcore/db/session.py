"""Engine y sesiones, con el aislamiento por tenant cosido a la sesión.

Tres garantías, todas automáticas:

1. **El GUC de tenant se fija al empezar CADA transacción**, no una vez al
   autenticar. Una `Session` vive varias transacciones (un commit abre otra), y
   un GUC fijado con `SET` normal sobrevive a la transacción pero NO a la
   devolución de la conexión al pool. Fijarlo al inicio de cada transacción con
   `set_config(..., is_local => true)` lo ata al ámbito correcto: vale para
   toda la transacción y desaparece al terminarla.

2. **El GUC se limpia al devolver la conexión al pool.** Si no, la siguiente
   petición que reutilice esa conexión empieza con el tenant de la anterior,
   y ese es el peor fallo posible: silencioso, intermitente y entre clientes.

3. **El tenant autoritativo vive en `session.info["tenant_id"]`**, no en el
   contextvar. Lo pone quien abre la sesión. El guard ORM mira ahí. Se explica
   el porqué en `crmcore.tenancy.context`.

Y una comprobación de arranque: con `rls_enabled=true`, el rol de conexión NO
puede ser SUPERUSER ni tener BYPASSRLS, porque esos roles se saltan las
políticas aunque estén en FORCE. Sin esta comprobación, RLS puede estar
«activado» y no aislar nada — que es mucho peor que no tenerlo, porque da
confianza sin darla.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import Session, sessionmaker

from crmcore.config import get_settings
from crmcore.logging import get_logger

logger = get_logger(__name__)

# GUC que leen las políticas de RLS. El nombre va con punto porque Postgres
# exige que un ajuste personalizado lleve prefijo de espacio de nombres.
GUC_TENANT = "app.current_tenant"

_engine: Engine | None = None
_sessionmaker: sessionmaker[Session] | None = None


def _construir_engine() -> Engine:
    s = get_settings()
    url = make_url(s.database_url)
    if url.get_backend_name() != "postgresql":
        # No es purismo: RLS, JSONB, los índices GIN y el outbox con
        # `FOR UPDATE SKIP LOCKED` son de Postgres. Un SQLite «para ir tirando»
        # daría un sistema que pasa las pruebas y no aísla nada en producción.
        raise RuntimeError(
            f"Solo se admite PostgreSQL como DATABASE_URL (recibido: {url.get_backend_name()})"
        )

    engine = create_engine(
        s.database_url,
        pool_size=s.db_pool_size,
        max_overflow=s.db_max_overflow,
        pool_timeout=s.db_pool_timeout_s,
        pool_recycle=s.db_pool_recycle_s,
        pool_pre_ping=True,
        connect_args={
            "connect_timeout": s.db_connect_timeout_s,
            # Keepalives: una sesión puede quedarse tomada durante una llamada
            # larga a un sistema externo. Mientras espera, la conexión está
            # ociosa y un NAT o un cortafuegos puede matarla en silencio; el
            # fallo aparece mucho después, al cerrar, como «server closed the
            # connection unexpectedly».
            "keepalives": 1,
            "keepalives_idle": 30,
            "keepalives_interval": 10,
            "keepalives_count": 5,
            # Esquema del servicio primero, `public` después para las
            # extensiones. Es lo que impide que un servicio lea por descuido una
            # tabla homónima de otro.
            "options": f"-csearch_path={s.esquema_resuelto},public",
            # Cifrado en tránsito con la base (CRM-00.05.03.01). Va aquí y no
            # en la URL para que sea **un ajuste**, revisable en un sitio, en
            # vez de un parámetro escondido en una cadena de conexión que cada
            # entorno escribe a su manera — que es como acaba habiendo uno en
            # producción sin `sslmode` y nadie lo ve.
            #
            # Si la URL ya trae `sslmode`, manda ella: hay despliegues donde la
            # cadena la genera el proveedor de la base y no se puede tocar.
            **({} if "sslmode" in s.database_url else {"sslmode": s.db_sslmode}),
        },
    )
    _instalar_hooks_rls(engine)
    return engine


def _instalar_hooks_rls(engine: Engine) -> None:
    # NO hay limpieza del GUC al devolver la conexión al pool, y es una decisión
    # medida, no un olvido:
    #
    #   * No hace falta. El GUC se fija con `set_config(..., is_local => true)`,
    #     que lo ata a la TRANSACCIÓN: desaparece al hacer commit o rollback, así
    #     que no puede sobrevivir a la devolución de la conexión. Y aunque
    #     sobreviviera, `_aplicar_guc` lo reescribe al empezar CADA transacción
    #     —también cuando no hay tenant, donde escribe cadena vacía—, de modo que
    #     un valor heredado nunca llega a poder leerse.
    #   * Y rompe. Ejecutar un `SET` en el evento `checkin` deja la conexión en
    #     estado INTRANS *después* del reset del pool, y el siguiente checkout
    #     falla con «can't change autocommit now: connection in transaction
    #     status INTRANS». Se comprobó con psycopg 3 al escribir la suite del
    #     motor de procesos: nueve pruebas en rojo por una limpieza que no
    #     limpiaba nada.
    #
    # Lo que de verdad garantiza que no se filtre el tenant entre peticiones es
    # `_aplicar_guc`, y hay una prueba de aislamiento que lo comprueba contra un
    # Postgres real reutilizando conexiones del pool.

    @event.listens_for(Session, "after_begin")
    def _aplicar_guc(session: Session, _transaction: Any, connection: Any) -> None:
        """Fija el GUC al empezar cada transacción de la sesión.

        `is_local => true` lo ata a la transacción: sobrevive a los savepoints,
        desaparece al commit y no puede filtrarse a la siguiente transacción que
        use la misma conexión.
        """
        if not get_settings().rls_enabled:
            return
        tenant = session.info.get("tenant_id")
        # Sin tenant se fija cadena vacía, no se omite el SET: omitirlo dejaría
        # el valor que hubiera puesto la transacción anterior. La política trata
        # la cadena vacía como «contexto de sistema».
        valor = str(tenant) if tenant else ""
        connection.execute(
            text("SELECT set_config(:clave, :valor, true)"),
            {"clave": GUC_TENANT, "valor": valor},
        )


def verificar_rol_sin_bypass(engine: Engine) -> list[str]:
    """Comprueba que el rol de conexión no se salta RLS.

    Devuelve la lista de problemas (vacía si todo correcto) en vez de lanzar,
    para que el arranque pueda enseñarlos todos juntos con su explicación.
    """
    s = get_settings()
    if not s.rls_enabled:
        return []
    try:
        with engine.connect() as conn:
            fila = conn.execute(
                text("SELECT rolsuper, rolbypassrls FROM pg_roles " "WHERE rolname = current_user")
            ).first()
    except Exception as exc:  # noqa: BLE001 — sin base no se puede verificar; lo dirá el readiness
        logger.warning("rls.verificacion_imposible", error=str(exc)[:200])
        return []
    if fila is None:
        return []
    problemas = []
    if fila[0]:
        problemas.append(
            "El rol de conexión es SUPERUSER: se salta Row-Level Security aunque "
            "esté en FORCE, así que el aislamiento por tenant NO está garantizado. "
            "Usa el rol de aplicación que crea deploy/crear-bases.sh."
        )
    if fila[1]:
        problemas.append(
            "El rol de conexión tiene BYPASSRLS: se salta las políticas de "
            "aislamiento. Quítaselo con ALTER ROLE ... NOBYPASSRLS."
        )
    return problemas


def exigir_rol_sin_bypass(engine: Engine) -> list[str]:
    """Lo mismo, pero **decidiendo**: fuera de `dev` no se arranca.

    `verificar_rol_sin_bypass` mide y no decide, y durante un tiempo el arranque
    sólo escribía el aviso en el registro «porque en producción lo convierte en
    fallo el gate de despliegue». Ese gate no existía. Medido el 28-10-2026: la
    pila local servía con el rol `postgres` —SUPERUSER— y, con él, las 623
    tablas con RLS, FORCE y política **no filtran nada**. No es que estuvieran
    mal escritas: están probadas y aíslan con un rol correcto
    (`tests/integration/test_rls_aislamiento.py`). Es que nadie obligaba a usar
    uno.

    Un aviso en el registro de arranque no es una red: nadie lee el arranque de
    un servicio que arrancó. En `dev` sigue siendo un aviso, porque trabajar con
    el rol de administrador en el portátil es lo normal y negarse ahí haría
    imposible el ciclo local. En cualquier otro entorno **se niega a arrancar**,
    que es el único momento en que alguien se entera.

    Devuelve los avisos para que el que llama los escriba; si no se puede
    arrancar, lanza.
    """
    avisos = verificar_rol_sin_bypass(engine)
    if avisos and get_settings().env != "dev":
        raise RuntimeError(
            "El rol de conexión se salta Row-Level Security, así que el "
            "aislamiento por tenant NO está garantizado en este despliegue. "
            + " ".join(avisos)
            + " Si esto es un entorno de desarrollo, ponle ENV=dev."
        )
    return avisos


def get_engine() -> Engine:
    """Engine del proceso. Se construye una sola vez."""
    global _engine
    if _engine is None:
        _engine = _construir_engine()
    return _engine


def get_sessionmaker() -> sessionmaker[Session]:
    """El fabricante de sesiones, y con él el guard de tenant.

    **El guard se instala aquí y no solo en `crear_servicio`.** Lo estaba solo
    ahí, y un worker es un proceso que nunca llama a esa factoría: abría
    sesiones sin la red del ORM puesta. En producción quedaba RLS, pero RLS
    tampoco cubre una sesión de sistema, así que la red era exactamente
    ninguna. Instalarlo al fabricar el primer `Session` cubre todo proceso que
    toque la base —API, worker, script de mantenimiento, prueba— sin que nadie
    tenga que acordarse.
    """
    global _sessionmaker
    if _sessionmaker is None:
        from crmcore.tenancy.guard import instalar_guard

        instalar_guard()
        _sessionmaker = sessionmaker(
            bind=get_engine(),
            autoflush=False,
            expire_on_commit=False,  # poder leer el objeto tras el commit
            future=True,
        )
    return _sessionmaker


def nueva_sesion(tenant_id: UUID | None = None, *, sistema: bool = False) -> Session:
    """Abre una sesión atada a un tenant.

    `tenant_id=None` con `sistema=False` es un error de programación, no un
    caso de uso: significa que alguien abrió una sesión sin saber de quién son
    los datos que va a tocar. Para las operaciones que de verdad cruzan tenants
    (migraciones, mantenimiento, consola de plataforma) está `sistema=True`, que
    hay que escribir y por tanto se ve en la revisión y en el `grep`.
    """
    from crmcore.errors import ErrorInterno
    from crmcore.tenancy.context import contexto_actual

    if tenant_id is None and not sistema:
        tenant_id = contexto_actual().tenant_id
        if tenant_id is None:
            raise ErrorInterno(
                "Se ha abierto una sesión sin tenant y sin declarar sistema=True",
                error_code="db.sesion_sin_tenant",
            )
    sesion = get_sessionmaker()()
    sesion.info["tenant_id"] = tenant_id
    sesion.info["sistema"] = sistema
    return sesion


@contextmanager
def sesion(tenant_id: UUID | None = None, *, sistema: bool = False) -> Iterator[Session]:
    """Sesión con commit al salir bien y rollback al salir mal.

        with sesion(tenant_id) as db:
            db.add(cuenta)

    Cierra siempre. Una sesión sin cerrar retiene una conexión del pool, y
    cuarenta de esas dejan el servicio sin conexiones con la base perfectamente
    sana.
    """
    db = nueva_sesion(tenant_id, sistema=sistema)
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def reset_engine() -> None:
    """Tira el engine y el sessionmaker. Solo para pruebas que cambian la URL."""
    global _engine, _sessionmaker
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _sessionmaker = None
