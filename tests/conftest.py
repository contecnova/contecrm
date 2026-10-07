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
import shutil
import sys
import tempfile
import time
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
# LOS RELEVOS DE TAREAS, APAGADOS EN TODA LA SUITE.
#
# Aquí y no en cada prueba porque el motivo es de la suite entera: el arnés ata
# todas las sesiones a UNA conexión (ver `db`, más abajo), y un relevo abre la
# suya cada segundo. Sus `RELEASE SAVEPOINT` se cruzan con los de la transacción
# de la prueba en curso y revientan la consulta siguiente con «savepoint
# sa_savepoint_N does not exist» — normalmente en OTRA prueba, varios ficheros
# más allá, que es lo que lo hacía parecer aleatorio.
#
# Medido el 06-10-2026: `pytest` a secas daba 5 fallos, los cinco en
# `test_fuzzing_tenant`, y sólo al correr la suite entera en un proceso. El
# preflight no los veía porque la parte en dos mitades.
#
# Esto no deja sin probar los relevos: sus pruebas llaman a `una_vuelta()`, que
# es el trabajo, y no a `correr()`, que es el bucle. Lo que se apaga es el
# bucle.
os.environ.setdefault("TAREAS_RELEVO_ENABLED", "false")


# Cuánto puede llevar vivo un Postgres de pruebas antes de darlo por abandonado.
# La suite entera tarda dos minutos, así que una hora es de sobra: nada que esté
# sirviendo a una tanda de verdad llega ahí. Se mide en horas y no en minutos
# para no matarle el servidor a otra sesión que esté corriendo en paralelo.
HORAS_PARA_DARLO_POR_ABANDONADO = 1


def esta_abandonado(ppid: str, etime: str) -> bool:
    """¿Este servidor es de una tanda muerta, o de una que está corriendo?

    Se decide con dos datos y nada más, para que se pueda comprobar sin
    fabricar un proceso huérfano de verdad —que no hay forma de fabricar: en
    cuanto acaba quien lo creó, `pgserver` lo para—.

    **Padre 1** quiere decir que quien lo lanzó ya no está. **Y más de una hora
    de vida** quiere decir que no es de una tanda en curso: la suite entera
    tarda dos minutos. Las dos condiciones juntas, porque solo la primera
    mataría el servidor de una sesión que esté corriendo ahora mismo en
    paralelo, y eso sería cambiar un problema por otro peor.
    """
    if ppid != "1":
        return False
    # `etime` viene como [[dd-]hh:]mm:ss.
    if "-" in etime:
        return True  # días
    if etime.count(":") < 2:
        return False  # solo mm:ss
    return int(etime.split(":")[0]) >= HORAS_PARA_DARLO_POR_ABANDONADO


def _recoger_servidores_abandonados() -> None:
    """Para los Postgres embebidos que dejaron tandas anteriores.

    POR QUÉ HACE FALTA. El `cleanup()` del fixture se ejecuta al terminar, y por
    eso no se ejecuta nunca cuando la tanda muere de mala manera: un `SIGKILL`,
    un `pkill` del proceso padre, una terminal cerrada. El servidor queda
    adoptado por init y sigue vivo. Medido el 28-09-2026: **once servidores
    sueltos, el más viejo de casi catorce horas, 849 MB de directorios de datos**.

    Y no es solo basura. Durante toda esa noche dimos por hecho que «dos tandas
    a la vez se cuelgan por el Postgres embebido» era una propiedad del sistema
    —así estaba escrito— y lo que había era una docena de instancias
    abandonadas peleándose. La norma describía el síntoma como si fuera la
    causa.

    No se puede arreglar en el teardown, porque a `SIGKILL` no se le pone un
    manejador. Así que se limpia al ARRANCAR, que es el único momento en que se
    puede estar seguro: si un servidor de este repositorio lleva horas vivo y
    huérfano, no está sirviendo a nadie.
    """
    import re
    import subprocess

    # PRIMERO los directorios huérfanos SIN proceso. Son la mayoría: una tanda
    # que termina bien para su servidor y deja los datos, y el recolector de
    # abajo —que mira `ps`— no los ve porque ya no hay proceso que ver. Es el
    # agujero que dejó 908 directorios y 24 GB en diez días.
    #
    # Se borran los de más de una hora: los recientes pueden ser de una tanda
    # que esté corriendo ahora mismo en otra ventana, y borrarle la base a una
    # tanda viva es peor que el disco lleno.
    hace_una_hora = time.time() - 3600
    for carpeta in Path(tempfile.gettempdir()).glob("contecrm-test-*"):
        try:
            if carpeta.stat().st_mtime < hace_una_hora:
                shutil.rmtree(carpeta, ignore_errors=True)
        except OSError:
            continue

    raiz = str(Path(__file__).resolve().parent.parent)
    try:
        salida = subprocess.run(
            ["ps", "-eo", "pid,ppid,etime,command"],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
    except Exception:  # noqa: BLE001 — no poder mirarlo no puede romper la suite
        return

    for linea in salida.splitlines():
        if raiz not in linea or "pgserver" not in linea:
            continue
        # SOLO LOS DE PRUEBAS, reconocidos por el prefijo de su directorio.
        #
        # No todo `pgserver` de este repositorio es basura: `scripts/postgres_local.py`
        # levanta uno PERSISTENTE a propósito en `var/pgdata` —es el Postgres de
        # desarrollo que usa `setup.sh`, y vive fuera de cualquier tanda—. Este
        # recolector lo daba por abandonado en cuanto pasaba una hora, que es
        # siempre, y lo habría parado en mitad del trabajo de alguien.
        #
        # Es el mismo error que vengo arreglando toda la noche, cometido por mí
        # al escribir la limpieza: una condición que parece precisa —«de este
        # repositorio y huérfano y viejo»— y que incluye un caso legítimo que
        # nadie miró.
        if "contecrm-test-" not in linea:
            continue
        partes = linea.split(None, 3)
        if len(partes) < 4 or not esta_abandonado(partes[1], partes[2]):
            continue
        datos = re.search(r"-D (\S+)", partes[3])
        if not datos:
            continue
        carpeta = datos.group(1)
        pg_ctl = (
            Path(sys.prefix)
            / "lib"
            / "python3.12"
            / "site-packages"
            / ("pgserver/pginstall/bin/pg_ctl")
        )
        try:
            # Se para con `pg_ctl`, no a machetazos: un `kill -9` deja el
            # directorio de datos a medias y el siguiente arranque no abre.
            subprocess.run(
                [str(pg_ctl), "-D", carpeta, "-w", "-m", "fast", "stop"],
                capture_output=True,
                timeout=30,
            )
            shutil.rmtree(Path(carpeta).parent, ignore_errors=True)
        except Exception:  # noqa: BLE001
            continue


@pytest.fixture(scope="session")
def postgres_uri() -> Iterator[str]:
    """Postgres embebido para toda la sesión de pruebas.

    Uno solo para toda la sesión: arrancarlo cuesta unos segundos y hacerlo por
    prueba multiplicaría eso por cientos. El aislamiento entre pruebas lo da un
    esquema nuevo por prueba, que es barato.
    """
    import pgserver

    _recoger_servidores_abandonados()
    directorio = Path(tempfile.mkdtemp(prefix="contecrm-test-"))
    servidor = pgserver.get_server(directorio / "pgdata")
    uri = servidor.get_uri()
    # SQLAlchemy con psycopg 3 necesita el prefijo explícito; pgserver devuelve
    # el de libpq.
    yield uri.replace("postgresql://", "postgresql+psycopg://", 1)
    servidor.cleanup()
    # Y SE BORRA EL DIRECTORIO. `cleanup()` para el servidor y deja los datos:
    # medido el 05-10-2026, **908 directorios de 24 GB acumulados desde el 25 de
    # septiembre**, uno por cada tanda de pruebas de diez días.
    #
    # No es solo disco. Spotlight los indexa, y con 24 GB de ficheros de una
    # base de datos indexándose el disco va al 90 % de ocupación de forma
    # permanente: la misma tanda que tardaba 59 segundos pasó a tardar 152 con
    # el mismo trabajo de CPU, esperando al disco. Un recolector que solo mira
    # los servidores VIVOS no ve esto, porque el servidor ya murió bien.
    shutil.rmtree(directorio, ignore_errors=True)


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
    from crmcore.datos.guard_borrados import instalar_guard_borrados
    from crmcore.db import session as db_session
    from crmcore.db.session import get_engine
    from crmcore.tenancy.guard import instalar_guard
    from sqlalchemy.orm import sessionmaker

    # Los dos guards, como en un servicio de verdad: si la suite corriera sin
    # el de borrados, las pruebas verían registros que en producción están
    # escondidos, que es la peor forma de tener una suite en verde.
    instalar_guard()
    instalar_guard_borrados()
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
        # Los vocabularios de negocio: tabla común, como `ajustes_runtime`, y en
        # el esquema de CADA servicio. Faltaba aquí desde que se creó, así que su
        # tabla no existía en pruebas y **ninguna prueba con base de datos podía
        # tocarla**: las tres rutas que la leen —motivos de descarte, motivos de
        # pérdida y el listado de vocabularios— reventaban con «relation
        # valores_vocabulario does not exist» en cuanto alguien las abría.
        "crmcore.vocabulario",
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
        "services.sales.partners",
        "services.sales.comisiones",
        "services.marketing.fondos",
        "services.service.activos",
        "services.service.campo",
        # El servicio de casos entero. Faltaba, y con él VEINTICUATRO tablas:
        # casos, colas, SLA, escalada, encuestas, conocimiento, comunidad,
        # portal, entitlements, omnicanal y macros. Ninguna se creaba en el
        # esquema de pruebas, así que ninguna prueba con base de datos podía
        # tocarlas — no es que estuvieran mal probadas: es que no se podían
        # probar. Se vio con el barrido de humo de los listados.
        "services.service.modelos",
        "services.service.operacion",
        "services.service.omnicanal",
        "services.service.conocimiento",
        "services.service.portal",
        "services.service.entitlements",
        "services.service.postventa",
        "services.service.problemas",
        "services.integration.telemetria",
        "services.integration.canonico",
        "services.integration.manifiestos",
        "services.integration.mcp",
        "services.integration.canales_entrada",
        "services.integration.federacion",
        "services.integration.convivencia",
        "services.analytics.almacen",
        "services.analytics.semantico",
        "services.party.identidad",
        "services.intelligence.modelos",
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
    from crmcore.config import get_settings
    from crmcore.http.rate_limit import limpiar_memoria
    from crmcore.obs.metrics import reset_metricas
    from crmcore.runtime.settings import invalidar

    limpiar()
    limpiar_memoria()
    invalidar()
    reset_metricas()
    # Y la caché de `Settings`, que NO estaba. `invalidar()` limpia los ajustes
    # de runtime —los que viven en la base— pero `get_settings` es un `lru_cache`
    # sobre el `.env` y las variables de entorno: una prueba que hace
    # `monkeypatch.setenv` y limpia la caché deja el valor nuevo cacheado, y
    # `monkeypatch` deshace la variable DESPUÉS, sin volver a limpiar. El
    # resultado es que la siguiente prueba hereda un ajuste que ya no existe en
    # el entorno, y falla —o pasa— por algo que no tiene que ver con ella.
    get_settings.cache_clear()


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


async def esperar_a(condicion: Any, timeout_s: float = 2.0) -> bool:
    """Espera a que una condición se cumpla, sondeando.

    Existe para que ninguna prueba use `asyncio.sleep(0.5)` a ojo: una espera
    fija o es lenta de más o falla en una máquina cargada — y esta máquina se
    carga, porque conviven varias suites.

    Vivía en `crmcore.bus.memoria`, que es código de producción, y no la usaba
    nadie. Un ayudante de pruebas en producción es código que nadie ejecuta en
    producción y que ningún recorrido de pruebas cubre: aquí sí tiene llamantes
    y aquí es donde se mira si deja de hacer falta.
    """
    import asyncio

    limite = asyncio.get_event_loop().time() + timeout_s
    while asyncio.get_event_loop().time() < limite:
        if condicion():
            return True
        await asyncio.sleep(0.01)
    return False
