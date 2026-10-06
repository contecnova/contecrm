"""El ETag se emitía y no lo miraba nadie (CRM-00.02.01.09).

El middleware pone el `ETag` en toda respuesta versionada. Está bien hecho, tiene
sus pruebas y lleva tiempo funcionando. Lo que **no** había es ninguna ruta que
mirase lo que el cliente devuelve con él:

**`If-Match`, el que evita el cambio perdido.** Dos personas abren la misma
ficha, las dos editan, y la segunda en guardar pisa el cambio de la primera **sin
que ninguna se entere**. No da error, no deja rastro y se descubre semanas
después, cuando alguien pregunta por qué el dato que escribió no está. La
comprobación estaba escrita, probada por su propia prueba y sin aplicar.

Y el `ETagMiddleware` afirmaba en su documentación que había un gate que exigía
usarla «si una ruta de actualización sobre un recurso versionado no la usa».
**Ese gate no existía.** Una referencia a un guardián que no está es peor que no
mencionarlo: hace que el siguiente que lo lea dé por cubierto lo que no lo está.
Este fichero es ese gate, ahora de verdad.

**`If-None-Match`, el que ahorra el cuerpo.** El cliente devolvía el ETag
obedientemente y recibía la ficha entera otra vez: cincuenta campos y sus
relaciones, cada vez que alguien vuelve a la pestaña.
"""

from __future__ import annotations

import ast
import pathlib
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from starlette.testclient import TestClient

pytestmark = pytest.mark.db

RAIZ = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture
def cliente(db: Any) -> Any:
    import importlib
    import os

    from crmcore.config import get_settings

    previo = os.environ.get("OUTBOX_ENABLED")
    os.environ["OUTBOX_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        modulo = importlib.import_module("services.sales.main")
        with TestClient(modulo.app) as cli:
            yield cli
    finally:
        if previo is None:
            os.environ.pop("OUTBOX_ENABLED", None)
        else:
            os.environ["OUTBOX_ENABLED"] = previo
        get_settings.cache_clear()


@pytest.fixture
def cabeceras(tenant_id: UUID) -> dict[str, str]:
    from crmcore.config import get_settings
    from crmcore.http.deps import (
        H_FACTOR_FUERTE,
        H_PERMISOS,
        H_ROLES,
        H_TENANT,
        H_USER,
        firmar_cabeceras_internas,
    )

    return firmar_cabeceras_internas(
        {
            H_TENANT: str(tenant_id),
            H_USER: str(uuid4()),
            H_PERMISOS: "*:*",
            H_ROLES: "admin",
            H_FACTOR_FUERTE: datetime.now(timezone.utc).isoformat(),
        },
        get_settings().secret_key.get_secret_value(),
    )


@pytest.fixture
def contrato(db: Any, tenant_id: UUID) -> Any:
    """Un producto: un recurso versionado de verdad y con ficha genérica.

    Versionado **de verdad** importa: hay modelos cuyo `version` es un dato del
    negocio —la versión del presupuesto que se le manda al cliente, la del
    fichero que se vuelve a subir— y a ésos no se les puede usar para
    concurrencia, porque no cambian al editar.
    """
    from datetime import date

    from services.sales.presupuestos import Contrato

    fila = Contrato(
        tenant_id=tenant_id,
        numero="C-ETAG",
        cuenta_id=uuid4(),
        titulo="Mantenimiento 2026",
        inicio=date(2026, 1, 1),
    )
    db.add(fila)
    db.commit()
    return fila


# ── If-Match: el cambio perdido ───────────────────────────────────────────


def test_editar_con_la_version_que_se_leyo_pasa(
    cliente: Any, cabeceras: dict[str, str], contrato: Any
) -> None:
    r = cliente.get(f"/api/v1/contratos/{contrato.id}", headers=cabeceras)
    assert r.status_code == 200, r.text[:300]
    etag = r.headers.get("etag")
    assert etag, "la lectura no trae ETag: no hay nada que devolver"

    editado = cliente.patch(
        f"/api/v1/contratos/{contrato.id}",
        json={"titulo": "Tarifa 2026 revisada"},
        headers={**cabeceras, "If-Match": etag},
    )
    assert editado.status_code == 200, editado.text[:300]
    assert editado.json()["titulo"] == "Tarifa 2026 revisada"


def test_editar_con_una_version_vieja_se_rechaza(
    cliente: Any, cabeceras: dict[str, str], contrato: Any
) -> None:
    """**Es el caso que esto existe para cazar.** Sin él, la segunda persona en
    guardar borra lo de la primera y ninguna de las dos se entera."""
    viejo = cliente.get(f"/api/v1/contratos/{contrato.id}", headers=cabeceras).headers["etag"]

    # Otra persona guarda primero.
    cliente.patch(
        f"/api/v1/contratos/{contrato.id}",
        json={"titulo": "La que llegó antes"},
        headers={**cabeceras, "If-Match": viejo},
    ).raise_for_status()

    # Y ahora la primera, con la ficha que abrió hace diez minutos.
    r = cliente.patch(
        f"/api/v1/contratos/{contrato.id}",
        json={"titulo": "La que llegó tarde"},
        headers={**cabeceras, "If-Match": viejo},
    )
    assert r.status_code == 409, r.text[:300]

    # Y lo de la primera sigue ahí: no se ha pisado.
    actual = cliente.get(f"/api/v1/contratos/{contrato.id}", headers=cabeceras).json()
    assert actual["titulo"] == "La que llegó antes"


def test_sin_if_match_se_edita_como_siempre(
    cliente: Any, cabeceras: dict[str, str], contrato: Any
) -> None:
    """Exigirlo rompería a todo el que ya integra sin mandarlo. Quien lo manda
    queda protegido; quien no, se comporta como hasta ahora."""
    r = cliente.patch(
        f"/api/v1/contratos/{contrato.id}",
        json={"titulo": "Sin cabecera"},
        headers=cabeceras,
    )
    assert r.status_code == 200, r.text[:300]


def test_el_asterisco_vale_si_el_registro_existe(
    cliente: Any, cabeceras: dict[str, str], contrato: Any
) -> None:
    """Es lo que quiere quien actualiza algo que acaba de leer sin haberse
    quedado la versión."""
    r = cliente.patch(
        f"/api/v1/contratos/{contrato.id}",
        json={"titulo": "Con asterisco"},
        headers={**cabeceras, "If-Match": "*"},
    )
    assert r.status_code == 200, r.text[:300]


# ── If-None-Match: el cuerpo que no hace falta ────────────────────────────


def test_si_el_cliente_ya_tiene_la_version_buena_no_se_le_manda_el_cuerpo(
    cliente: Any, cabeceras: dict[str, str], contrato: Any
) -> None:
    """El cliente devolvía el ETag obedientemente y recibía la ficha entera otra
    vez: cincuenta campos y sus relaciones, cada vez que vuelve a la pestaña."""
    primera = cliente.get(f"/api/v1/contratos/{contrato.id}", headers=cabeceras)
    etag = primera.headers["etag"]

    segunda = cliente.get(
        f"/api/v1/contratos/{contrato.id}", headers={**cabeceras, "If-None-Match": etag}
    )
    assert segunda.status_code == 304, segunda.text[:300]
    assert not segunda.content, "un 304 con cuerpo no ahorra nada"


def test_si_ha_cambiado_vuelve_el_cuerpo_entero(
    cliente: Any, cabeceras: dict[str, str], contrato: Any
) -> None:
    """La otra mitad: servir un 304 sobre un registro que cambió deja al cliente
    con el dato viejo creyendo que está al día, que es peor que no ahorrar."""
    etag = cliente.get(f"/api/v1/contratos/{contrato.id}", headers=cabeceras).headers["etag"]
    cliente.patch(
        f"/api/v1/contratos/{contrato.id}", json={"titulo": "Cambiada"}, headers=cabeceras
    ).raise_for_status()

    r = cliente.get(
        f"/api/v1/contratos/{contrato.id}", headers={**cabeceras, "If-None-Match": etag}
    )
    assert r.status_code == 200, r.text[:300]
    assert r.json()["titulo"] == "Cambiada"


def test_sin_if_none_match_vuelve_el_cuerpo(
    cliente: Any, cabeceras: dict[str, str], contrato: Any
) -> None:
    r = cliente.get(f"/api/v1/contratos/{contrato.id}", headers=cabeceras)
    assert r.status_code == 200
    assert r.json()["numero"] == "C-ETAG"


# ── Lo que NO se toca ─────────────────────────────────────────────────────


def test_el_version_de_negocio_no_lo_toca_el_bloqueo(db: Any, tenant_id: UUID) -> None:
    """La versión del presupuesto la lee el cliente: es la 1, la 2, la 3 de la
    oferta. Incrementarla en cada edición cambiaría un dato del negocio — y el
    cliente recibiría la «versión 7» de algo que solo se ha mandado dos veces."""
    from services.sales.presupuestos import Presupuesto

    assert (
        Presupuesto.__mapper__.version_id_col is None
    ), "el bloqueo optimista ha entrado en un modelo cuyo `version` es de negocio"

    fila = Presupuesto(tenant_id=tenant_id, numero="P-1", titulo="Oferta")
    db.add(fila)
    db.commit()
    antes = fila.version

    fila.titulo = "Oferta revisada"
    db.commit()
    db.refresh(fila)
    assert fila.version == antes, "editar el presupuesto le ha cambiado su versión de negocio"


def test_el_version_de_la_fila_si_lo_lleva_la_base(db: Any, tenant_id: UUID) -> None:
    """La otra mitad, medida: en una entidad normal sube sola en cada escritura.
    **Se quedaba en 1 toda la vida del registro**, y con eso el ETag era
    constante y el `If-Match` del cliente cuadraba siempre."""
    from datetime import date

    from services.sales.presupuestos import Contrato

    assert Contrato.__mapper__.version_id_col is not None

    fila = Contrato(
        tenant_id=tenant_id,
        numero="C-VER",
        cuenta_id=uuid4(),
        titulo="Uno",
        inicio=date(2026, 1, 1),
    )
    db.add(fila)
    db.commit()
    assert fila.version == 1

    fila.titulo = "Dos"
    db.commit()
    db.refresh(fila)
    assert fila.version == 2, "el contador no sube: la protección sería decorativa"


def test_el_cambio_perdido_de_verdad_contesta_409_y_no_500() -> None:
    """Cuando lo caza la base y no la cabecera. Sin manejador sale como «error
    interno», y entonces la pantalla ofrece **reintentar** — que es exactamente
    pisar el cambio ajeno, lo contrario de lo que toca."""
    from crmcore.service import crear_servicio
    from fastapi import APIRouter
    from sqlalchemy.orm.exc import StaleDataError

    router = APIRouter()

    @router.get("/choque", summary="Simula el choque que caza la base")
    async def choque() -> dict[str, bool]:
        raise StaleDataError("UPDATE statement on table matched 0 rows")

    app = crear_servicio(
        nombre="pruebas-choque",
        descripcion="cambio perdido",
        routers=[router],
        necesita_db=False,
        necesita_bus=False,
    )
    with TestClient(app, raise_server_exceptions=False) as cliente:
        r = cliente.get("/api/v1/choque")

    assert r.status_code == 409, r.text[:300]
    assert r.json()["error_code"] == "conflicto.version_caducada"
    # Y dice qué hacer: releer y decidir, no reintentar.
    assert "vuelve a cargarlo" in r.json()["detail"].lower()


# ── El gate que el middleware decía tener ─────────────────────────────────


def _funcion(fuente: str, nombre: str) -> ast.FunctionDef:
    arbol = ast.parse(fuente)
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.FunctionDef) and nodo.name == nombre:
            return nodo
    raise AssertionError(f"no se ha encontrado «{nombre}»: el recorrido no mira")


def test_la_ficha_generica_aplica_las_dos_mitades() -> None:
    """Las dos, y en la ficha genérica: montarlo recurso a recurso significaría
    tenerlo en los que alguien recordó, y un cliente no puede usar `If-Match` en
    un recurso que unas veces lo comprueba y otras no."""
    fuente = (RAIZ / "packages" / "crmcore" / "crmcore" / "http" / "listados.py").read_text(
        encoding="utf-8"
    )

    def _llamadas(nombre: str) -> set[str]:
        nodo = _funcion(fuente, nombre)
        return {
            getattr(n.func, "id", None) or getattr(n.func, "attr", None)
            for n in ast.walk(nodo)
            if isinstance(n, ast.Call)
        }

    assert "comprobar_if_match" in _llamadas("editar"), (
        "la edición genérica no mira el If-Match: dos personas editando la misma "
        "ficha vuelven a pisarse"
    )
    assert "comprobar_if_none_match" in _llamadas("ver"), (
        "la lectura genérica no mira el If-None-Match: el ETag que emitimos no "
        "sirve para ahorrar nada"
    )


def test_el_middleware_no_apunta_a_un_guardian_que_no_existe() -> None:
    """Decía que el gate estaba en `test_contratos_arquitectura.py`, y allí no
    había nada. Una referencia a un guardián que no está hace que el siguiente
    que la lea dé por cubierto lo que no lo está."""
    etag = (RAIZ / "packages" / "crmcore" / "crmcore" / "http" / "etag.py").read_text(
        encoding="utf-8"
    )
    nombrados = {
        linea.strip() for linea in etag.splitlines() if "test_" in linea and ".py" in linea
    }
    for linea in nombrados:
        import re

        for fichero in re.findall(r"test_[a-z0-9_]+\.py", linea):
            assert (
                RAIZ / "tests" / "unit" / fichero
            ).exists(), f"`etag.py` dice apoyarse en «{fichero}», que no existe"
    assert nombrados, "el recorrido no ha encontrado ninguna referencia que comprobar"
