"""Entorno de Alembic, con un esquema y una cadena de versiones por servicio.

Se ejecuta con `-x servicio=<nombre>`, y de ahí salen tres cosas:

  * el **esquema** sobre el que se migra (`search_path`),
  * la **carpeta de versiones** de ese servicio,
  * la **conexión**, que usa el rol de migración (`DATABASE_ADMIN_URL`) y no el
    de la aplicación — que no tiene DDL a propósito.

`version_table_schema` va al esquema del servicio: si la tabla de versiones
fuera común, dos servicios se pisarían el histórico y una migración de ventas
parecería aplicada en soporte.
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool, text

from alembic import context

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "packages" / "crmcore"))

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

SERVICIO = context.get_x_argument(as_dictionary=True).get("servicio") or os.environ.get(
    "SERVICE_NAME", ""
)
if not SERVICIO:
    raise SystemExit(
        "Falta el servicio. Usa:  alembic -x servicio=tenancy upgrade head\n"
        "Sin él no se sabe qué esquema migrar, y migrar el equivocado es peor "
        "que no migrar."
    )

os.environ["SERVICE_NAME"] = SERVICIO

# Cada servicio tiene su carpeta de versiones. Es lo que hace que sus cadenas de
# migración sean independientes: el servicio de ventas puede ir por la revisión
# 40 y el de soporte por la 3 sin que ninguno espere al otro.
_VERSIONES = RAIZ / "alembic" / "versions" / SERVICIO
_VERSIONES.mkdir(parents=True, exist_ok=True)
config.set_main_option("version_locations", str(_VERSIONES))
config.set_main_option("servicio", SERVICIO)

# Los modelos se importan DESPUÉS de fijar el servicio: algunos leen la
# configuración al importarse.
from crmcore.config import get_settings, limpiar_cache_settings  # noqa: E402
from crmcore.db.base import Base  # noqa: E402

# La configuración se cachea por proceso, y `scripts/migrar.py --todos` migra
# los siete servicios en UNO. Sin limpiar la caché, los seis siguientes leerían
# el `service_name` del primero y escribirían su tabla de versiones en el
# esquema equivocado —«relation "tenancy.alembic_version" does not exist»— o,
# peor, migrarían el esquema de otro servicio sin avisar.
limpiar_cache_settings()


def _importar_modelos(servicio: str) -> None:
    """Importa los modelos comunes y los del servicio que se migra.

    Solo los suyos: si se importaran los de todos, `--autogenerate` intentaría
    crear en este esquema las tablas de los demás servicios, que es exactamente
    lo contrario de la propiedad exclusiva de datos.
    """
    import importlib

    comunes = [
        "crmcore.audit.modelos",
        # Las políticas de campo son de TODOS los servicios, no de unos pocos.
        # No estaban aquí, así que la tabla solo existía en los cinco esquemas
        # cuyos modelos la importaban de rebote. Consecuencia: en los otros
        # ocho, `proyectar_para` —lo que decide qué columnas ve cada rol—
        # consultaba una tabla inexistente y **cualquier listado reventaba con
        # un 500**. Y si no hubiera reventado sería peor: una política escrita
        # por el cliente no se aplicaría ahí, en silencio.
        "crmcore.authz.proyeccion",
        # Y las políticas ABAC, por lo mismo y con el mismo síntoma: la tabla
        # existía en nueve esquemas de trece, y en los otros cuatro cualquier
        # listado que pasara por el filtro de acceso reventaba con un 500
        # —«relation "politicas_abac" does not exist»— sobre una pantalla que
        # no tiene nada que ver con la seguridad.
        "crmcore.authz.politicas",
        # La papelera, por lo mismo y con el mismo síntoma: TODO servicio con
        # base publica `/{servicio}/papelera` —lo monta `crear_servicio`, no el
        # servicio— así que la tabla tiene que estar en los trece esquemas. Solo
        # estaba en seis, los que además la usaban para borrar; en los otros
        # siete la pantalla de papelera daba 500 al abrirla, «relation
        # "papelera" does not exist», sobre una ruta que el contrato anunciaba
        # y la superficie enseñaba.
        #
        # Estaba en el módulo de modelos de cada servicio, que es pedir que el
        # siguiente se acuerde. Aquí no hay nada que recordar.
        "crmcore.datos.papelera",
        # El enlace a un documento del corpus, por lo mismo: el enlace es del
        # REGISTRO y los registros están en los trece servicios, así que la
        # tabla va en los trece esquemas. Estaba solo en cinco, y no por una
        # decisión: en cuatro porque su `modelos.py` la importaba y en el quinto
        # —`integration`— de rebote, por importar otra cosa del mismo paquete.
        # O sea que dónde existía la tabla dependía de qué módulo importara cada
        # servicio por casualidad.
        "crmcore.documental.enlaces",
        "crmcore.bus.modelos",
        "crmcore.http.idempotency",
        "crmcore.runtime.settings",
        # Los vocabularios de negocio: cada servicio guarda el suyo en su
        # esquema, porque los valida en mitad de una operación y no puede
        # preguntárselos a otro servicio.
        "crmcore.vocabulario",
        # La numeración de negocio: misma forma y mismo motivo. Y va en los
        # TRECE a propósito, no en los tres que hoy la usan: decidir a mano en
        # cuáles existe la tabla es exactamente la fragilidad que ya se
        # arregló con los vocabularios, donde dónde existía dependía de qué
        # importara cada servicio por casualidad.
        "crmcore.numeracion",
    ]
    for modulo in [*comunes, f"services.{servicio}.modelos"]:
        try:
            importlib.import_module(modulo)
        except ModuleNotFoundError as exc:
            # El gateway no tiene modelos propios y es correcto que no los
            # tenga: su estado es la tabla de rutas, que viene de configuración.
            if f"services.{servicio}.modelos" not in str(exc):
                raise


_importar_modelos(SERVICIO)
target_metadata = Base.metadata

_settings = get_settings()
ESQUEMA = _settings.esquema_resuelto
# El rol de migración, no el de la aplicación. Si no está configurado se cae al
# de la aplicación y fallará con «permission denied», que es un error claro y
# mejor que migrar con un rol que no debería poder.
URL = _settings.database_admin_url or _settings.database_url


def run_migrations_offline() -> None:
    context.configure(
        url=URL,
        target_metadata=target_metadata,
        literal_binds=True,
        version_table_schema=ESQUEMA,
        include_schemas=False,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    seccion = config.get_section(config.config_ini_section) or {}
    seccion["sqlalchemy.url"] = URL
    conectable = engine_from_config(seccion, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with conectable.connect() as conexion:
        # Se comprueba ANTES de crear, en vez de confiar en `IF NOT EXISTS`.
        # Postgres verifica el privilegio CREATE sobre la base **aunque el
        # esquema ya exista**, así que `CREATE SCHEMA IF NOT EXISTS` falla con
        # «permission denied for database» contra el rol de migración de un
        # despliegue real — donde los esquemas los crea `deploy/crear-bases.sh`
        # y el rol de servicio, a propósito, no puede crear esquemas nuevos.
        #
        # Se descubrió levantando la pila con Docker: en local el rol es
        # superusuario y el problema no aparece. Es justo la diferencia por la
        # que el manual insiste en probar con Docker antes de dar algo por bueno.
        existe = conexion.execute(
            text("SELECT 1 FROM pg_namespace WHERE nspname = :esquema"),
            {"esquema": ESQUEMA},
        ).first()
        if not existe:
            conexion.execute(text(f'CREATE SCHEMA "{ESQUEMA}"'))
        conexion.execute(text(f'SET search_path TO "{ESQUEMA}", public'))
        conexion.commit()

        context.configure(
            connection=conexion,
            target_metadata=target_metadata,
            version_table_schema=ESQUEMA,
            # **False, y es la diferencia entre una migración correcta y una que
            # borra la base.** Los modelos no declaran esquema —lo pone el
            # `search_path`, que es lo que permite que el mismo modelo viva en
            # `identity` en producción y en un esquema efímero en las pruebas—.
            # Con `include_schemas=True`, Alembic refleja las tablas
            # cualificadas (`identity.sesiones`) y las compara con unas de
            # metadatos sin esquema (`sesiones`): no casa ninguna, así que
            # propone BORRAR todas las existentes y crearlas de nuevo. La
            # primera migración salió bien porque la base estaba vacía y no
            # había nada que borrar; la segunda llevaba trece `drop_table`.
            include_schemas=False,
            # Compara tipos y defaults de servidor: sin esto, `--autogenerate`
            # no detecta que una columna cambió de VARCHAR(80) a VARCHAR(200) y
            # la migración pasa por buena mientras la base sigue como estaba.
            compare_type=True,
            compare_server_default=True,
            include_object=_solo_mi_esquema,
        )
        with context.begin_transaction():
            context.run_migrations()
        # Commit explícito. Con SQLAlchemy 2.0 y una conexión propia, salir del
        # bloque de Alembic no basta: la transacción de la conexión queda sin
        # confirmar y al cerrar se revierte TODO —esquema incluido—, con el
        # agravante de que Alembic informa de un upgrade correcto que en
        # realidad no ha persistido nada.
        conexion.commit()


# Índices que `--autogenerate` NO puede comparar, con su motivo.
#
# Postgres **normaliza** la expresión de un índice al guardarla: lo que se
# escribe como `to_tsvector('spanish', a || ' ' || b)` vuelve como
# `to_tsvector('spanish'::regconfig, (((a)::text || ' '::text) || ...))`. La
# comparación con lo que dice el modelo no coincide **nunca**, así que Alembic
# propone borrarlo y recrearlo en cada generación: el ruido acabaría haciendo
# que nadie mire lo que propone, que es peor que no generar nada.
#
# La lista es de nombres y está aquí a la vista, no es una regla que excluya
# «los índices raros»: lo que no se compara hay que saber cuál es. Añadir o
# cambiar uno de estos exige escribir la migración a mano.
INDICES_NO_COMPARABLES = {
    "ix_indice_texto",  # GIN sobre to_tsvector(...) del índice de búsqueda
}


def _solo_mi_esquema(objeto, nombre, tipo, reflejado, comparar_con) -> bool:  # noqa: ANN001
    """Qué entra en `--autogenerate`.

    Dos exclusiones, y las dos vienen de haberlo roto antes:

    **La tabla de versiones de Alembic.** Con `include_schemas=True`, la ve
    reflejada y, como no está en los metadatos, propone borrarla. La primera
    tanda de migraciones generadas aquí llevaba un `op.drop_table('alembic_version')`
    al final: la migración se aplicaba, se borraba a sí misma el registro y
    fallaba al anotarse con «relation "…alembic_version" does not exist». Se
    aplicaba «bien» y no persistía nada.

    **Las tablas de otros esquemas.** Todos los servicios comparten base, así
    que sin filtro `--autogenerate` propone borrar las tablas de los demás. El
    resultado sería una migración de un servicio que destruye el trabajo de otro.
    Con `include_schemas=False` la reflexión ya se queda en el esquema del
    `search_path`, pero el filtro se mantiene: es la red que protege del día que
    alguien vuelva a poner `include_schemas=True` sin entender por qué estaba a
    `False`.
    """
    if nombre == "alembic_version":
        return False
    if tipo == "index" and nombre in INDICES_NO_COMPARABLES:
        return False
    if tipo == "table":
        esquema = getattr(objeto, "schema", None)
        return esquema in (None, ESQUEMA)
    return True


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
