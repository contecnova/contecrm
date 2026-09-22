"""Fixtures comunes de la suite.

Dos decisiones que condicionan cómo se escriben las pruebas aquí:

**Postgres de verdad, no un sustituto.** Media plataforma depende de cosas que
solo tiene Postgres: RLS, JSONB, `FOR UPDATE SKIP LOCKED`, `ON CONFLICT`. Una
prueba contra SQLite pasaría y no probaría nada de eso. Se usa `pgserver`, que
trae los binarios de PostgreSQL 16 dentro del wheel, así que no hace falta
Docker ni permisos de administrador — y por tanto el gate de `pre-push` puede
correr estas pruebas en cualquier máquina, que es justo lo que evita que alguien
acabe empujando con `--no-verify`.

**La marca `db` se pone sola.** `pytest_collection_modifyitems` marca lo que use
la fixture de base de datos. Así `pytest -m "not db"` sigue siendo un ciclo de
segundos y nadie tiene que acordarse de etiquetar nada.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

# Se fija ANTES de importar nada de `crmcore`: la configuración se lee una vez
# y se cachea, así que ponerlo después no tendría efecto.
os.environ.setdefault("ENV", "dev")
os.environ.setdefault("SERVICE_NAME", "pruebas")
os.environ.setdefault("BUS_BACKEND", "memoria")
os.environ.setdefault("SECRET_KEY", "clave-de-pruebas-no-vale-para-nada-mas")
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
os.environ.setdefault("METRICS_POR_TENANT", "false")


@pytest.fixture(scope="session")
def postgres_uri() -> Iterator[str]:
    """Postgres embebido para toda la sesión de pruebas.

    Uno solo para toda la sesión: arrancarlo cuesta unos segundos y hacerlo por
    prueba multiplicaría eso por cientos. El aislamiento entre pruebas lo da un
    esquema nuevo por prueba, que es barato.
    """
    import pgserver

    directorio = Path(tempfile.mkdtemp(prefix="contecrm-test-"))
    servidor = pgserver.get_server(directorio / "pgdata")
    uri = servidor.get_uri()
    # SQLAlchemy con psycopg 3 necesita el prefijo explícito; pgserver devuelve
    # el de libpq.
    yield uri.replace("postgresql://", "postgresql+psycopg://", 1)
    servidor.cleanup()


@pytest.fixture(scope="session")
def _esquema(postgres_uri: str) -> Iterator[str]:
    """Monta el esquema UNA vez para toda la sesión de pruebas.

    Antes se creaba y se tiraba uno por prueba. Medido: 0,28 s en crear las 98
    tablas y 0,08 s en tirarlas, o sea **0,36 s de coste fijo por prueba**. Con
    537 pruebas con base de datos eso eran 195 de los 200 segundos que tardaba
    la suite: el tiempo no se iba en probar, se iba en montar y desmontar.

    Y lo peor no era el número, era la pendiente: cada tabla nueva del producto
    encarecía TODAS las pruebas a la vez. Con el esquema por sesión, una tabla
    nueva cuesta unos milisegundos una vez.
    """
    import sqlalchemy as sa
    from crmcore.config import limpiar_cache_settings
    from crmcore.db.base import Base
    from crmcore.db.session import get_engine, reset_engine

    esquema = "pruebas"
    os.environ["DATABASE_URL"] = postgres_uri
    os.environ["DB_SCHEMA"] = esquema
    limpiar_cache_settings()
    reset_engine()

    # Se importan todos los modelos ANTES de crear las tablas: si un modelo se
    # importara después, su tabla no existiría y el fallo aparecería lejos, en
    # la primera consulta, como un «relation does not exist» sin contexto.
    _importar_todos_los_modelos()

    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(sa.text(f'CREATE SCHEMA IF NOT EXISTS "{esquema}"'))
        conn.commit()
    # `pgcrypto` NO se crea aquí a propósito: el Postgres embebido de `pgserver`
    # no lo trae, y el código no lo necesita — los identificadores los genera
    # Python (`crmcore.ids.nuevo_id`), no `gen_random_uuid()`. Donde sí hace
    # falta es en el despliegue real, y ahí lo crea `deploy/crear-bases.sh`.
    # Que la suite no dependa de él es lo que permite correrla sin Docker.
    Base.metadata.create_all(engine)

    yield esquema

    reset_engine()


@pytest.fixture
def db(_esquema: str) -> Iterator[Any]:
    """Sesión de base de datos aislada por TRANSACCIÓN, no por esquema.

    Cada prueba corre dentro de una transacción que se deshace al terminar. El
    aislamiento es el mismo que antes —ninguna prueba ve lo que escribió otra—
    y el coste pasa de 0,36 s a unos milisegundos.

    **Todas las sesiones de la prueba comparten la misma conexión**, incluidas
    las que abre el propio código de la aplicación (`unidad_de_trabajo`,
    `nueva_sesion`, los consumidores del bus). Sin eso, una sesión abierta
    dentro del código escribiría fuera de la transacción de la prueba y
    ensuciaría la siguiente — que es el modo de fallo por el que este patrón se
    hace mal.

    `join_transaction_mode="create_savepoint"` es lo que permite que el código
    bajo prueba haga `commit()` de verdad: cada commit libera un savepoint en
    vez de cerrar la transacción de fuera, así que el código se comporta igual
    que en producción y la prueba sigue pudiendo deshacerlo todo.
    """
    from crmcore.db import session as db_session
    from crmcore.db.session import get_engine
    from crmcore.tenancy.guard import instalar_guard
    from sqlalchemy.orm import sessionmaker

    instalar_guard()
    conexion = get_engine().connect()
    transaccion = conexion.begin()

    fabrica = sessionmaker(
        bind=conexion,
        autoflush=False,
        expire_on_commit=False,
        future=True,
        join_transaction_mode="create_savepoint",
    )
    anterior = db_session._sessionmaker
    db_session._sessionmaker = fabrica

    sesion = fabrica()
    sesion.info["sistema"] = True
    sesion.info["tenant_id"] = None
    try:
        yield sesion
    finally:
        sesion.close()
        db_session._sessionmaker = anterior
        # Se deshace TODO, incluido lo que el código hubiera confirmado: los
        # commits de dentro eran savepoints.
        transaccion.rollback()
        conexion.close()


def _importar_todos_los_modelos() -> None:
    """Importa cada módulo de modelos para que `Base.metadata` esté completo."""
    import importlib

    modulos = [
        "crmcore.audit.modelos",
        "crmcore.bus.modelos",
        "crmcore.http.idempotency",
        "crmcore.runtime.settings",
        "crmcore.datos.adjuntos",
        "crmcore.datos.comentarios",
        "crmcore.datos.retencion",
        "crmcore.datos.jerarquia",
        "crmcore.busqueda",
        "crmcore.authz.proyeccion",
        "crmcore.datos.papelera",
        "crmcore.datos.seguimiento",
        "crmcore.datos.trabajos",
        "crmcore.security.byok",
        "crmcore.notificaciones.entrega",
        "crmcore.documental.enlaces",
        "crmcore.authz.politicas",
        "services.tenancy.grc",
        "services.identity.sod",
        "services.metadata.gobierno",
        "crmcore.runtime.versiones",
        "services.tenancy.modelos",
        "services.identity.modelos",
        "services.orchestrator.modelos",
        "services.metadata.modelos",
        "services.metadata.relaciones",
        "services.automation.modelos",
        "services.integration.modelos",
        "services.eventing.modelos",
        "services.party.modelos",
        "services.sales.modelos",
        "services.sales.enrutamiento",
        "services.sales.origen",
        "services.sales.captura",
        "services.party.retencion",
        "services.sales.retencion",
        "services.analytics.modelos",
        "services.tenancy.catalogos",
        "services.tenancy.baja",
        "crmcore.authz.comparticion",
        "services.identity.sso",
        "services.orchestrator.aprobaciones",
        "services.orchestrator.organizacion",
        "services.sales.catalogo",
        "services.sales.presupuestos",
        "services.integration.firma",
        "services.analytics.informes",
        "services.analytics.fuente",
        "services.analytics.cuadros",
        "services.sales.cadencias",
        "services.marketing.modelos",
        "services.marketing.recorridos",
        "services.marketing.correo",
        "services.marketing.canales",
        "services.sales.territorios",
        "services.party.actividades_extra",
    ]
    for modulo in modulos:
        try:
            importlib.import_module(modulo)
        except ModuleNotFoundError:
            # Un servicio que aún no existe no debe romper la suite de los que
            # sí. La lista se mantiene a mano a propósito: un `walk_packages`
            # importaría también lo que no toca y ocultaría errores de import.
            pass


@pytest.fixture
def tenant_id() -> UUID:
    """Identificador de tenant estable dentro de una prueba."""
    from crmcore.ids import nuevo_id

    return nuevo_id()


@pytest.fixture
def otro_tenant_id() -> UUID:
    """Segundo tenant, para las pruebas de aislamiento."""
    from crmcore.ids import nuevo_id

    return nuevo_id()


@pytest.fixture
def contexto_tenant(tenant_id: UUID) -> Iterator[UUID]:
    """Ejecuta la prueba con un tenant en el contexto."""
    from crmcore.tenancy.context import con_contexto

    with con_contexto(tenant_id=tenant_id):
        yield tenant_id


@pytest.fixture(autouse=True)
def _limpiar_estado_global() -> Iterator[None]:
    """Deja el estado de módulo limpio entre pruebas.

    Autouse a propósito: el bus en memoria, los contadores de límites y la caché
    de ajustes son estado de módulo, y una prueba que hereda el de la anterior
    falla —o peor, pasa— por motivos que no tienen que ver con lo que prueba.
    """
    yield
    from crmcore.bus.memoria import limpiar
    from crmcore.http.rate_limit import limpiar_memoria
    from crmcore.obs.metrics import reset_metricas
    from crmcore.runtime.settings import invalidar

    limpiar()
    limpiar_memoria()
    invalidar()
    reset_metricas()


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Marca automáticamente lo que necesita infraestructura.

    Se hace aquí y no a mano en cada prueba porque una marca manual se olvida, y
    una prueba con base de datos sin marcar rompe el ciclo rápido de quien no
    tiene Postgres — que es exactamente el problema que la marca venía a evitar.
    """
    for item in items:
        fixtures = getattr(item, "fixturenames", ())
        if "db" in fixtures or "postgres_uri" in fixtures:
            item.add_marker(pytest.mark.db)
        if "integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)
