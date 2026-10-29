"""Un campo publicado que no rellenaba nadie: `total_aprox`.

**El contrato de toda página del CRM declara `total_aprox`** —está en `Pagina` y
en `PaginaDeListado`, así que un cliente generado del OpenAPI lo espera— y
ninguna ruta lo ponía nunca. Un campo que se declara y no llega.

Medido el 29-10-2026 por la vía peor: preguntándole al asistente «cuántas
cuentas no tienen web». Supo listarlas y contestó que contarlas no podía,
porque la API no lo ofrece. Y el que paga la pregunta no distingue «no se
puede» de «no se ha implementado»: concluye que el producto no sabe contar.

Se cuenta **sólo si se pide** (`?contar=true`): contar exacto cuesta un
recorrido completo de la tabla y casi nadie necesita el número —necesita saber
si hay más, que ya lo dice `hay_mas` sin coste—. Pero cuando hace falta, tiene
que estar en los tres caminos por los que se sirve una página:

1. `montar_listado`, la fábrica
2. `paginar_consulta`, los listados a mano que la usan
3. `construir_pagina` a pelo, los siete que arman su propia consulta

Esta prueba vigila las tres cosas que pueden salir mal, y cada una **se validó
plantando el caso malo** (29-10-2026):

- Que el número no llegue. Plantado quitando `total_aprox=total` de
  `construir_pagina`: rojo.
- **Que encoja al avanzar.** Es el fallo sutil: contar DESPUÉS del cursor da
  «cuántas quedan desde aquí», que tiene toda la pinta de un total y baja
  página a página. Plantado contando después de `aplicar_orden_y_cursor`:
  rojo en la página 2 y verde en la primera, que es justo cómo se cuela.
- Que cuente la tabla y no lo que ve quien pregunta. Plantado contando
  `select(Cuenta)` en vez de la consulta filtrada: rojo.

Y un gate sobre la aplicación construida —no sobre el código— para que el
listado número treinta y cuatro no nazca sin saber contar.
"""

from __future__ import annotations

import importlib
import os
from typing import Any
from uuid import UUID, uuid4

import pytest

SERVICIOS = [
    "tenancy",
    "identity",
    "metadata",
    "orchestrator",
    "automation",
    "integration",
    "eventing",
    "party",
    "sales",
    "analytics",
    "intelligence",
    "service",
    "marketing",
]

# ── Los que NO ofrecen contar, con su motivo ──────────────────────────────
#
# Por excepciones y no por una lista de los que sí: una lista de los que sí se
# queda corta en silencio el día que alguien añade el treinta y cuatro, y nadie
# se entera porque la prueba sigue verde contando los treinta y tres de antes.
#
# Y cada excepción se **comprueba**, no se cree: la de abajo tiene su prueba
# justo después. Un motivo escrito y nada más es una lista de permisos.
NO_SABEN_CONTAR: dict[str, str] = {
    "metadata: GET /api/v1/entornos": (
        "no lee una tabla: devuelve la lista cerrada de etapas por las que pasa "
        "la configuración, entera y en memoria. No tiene `?contar=true` porque "
        "devuelve `total_aprox` SIEMPRE — el número ya se sabe y cobrarlo "
        "aparte sería pedir permiso para algo que no cuesta nada. Lo comprueba "
        "`test_el_unico_que_cuenta_sin_pedirselo`"
    ),
}


@pytest.fixture(autouse=True)
def _devolver_el_servicio() -> Any:
    from crmcore.config import limpiar_cache_settings

    previo = os.environ.get("SERVICE_NAME")
    try:
        yield
    finally:
        if previo is None:
            os.environ.pop("SERVICE_NAME", None)
        else:
            os.environ["SERVICE_NAME"] = previo
        limpiar_cache_settings()


def _app(servicio: str) -> Any:
    from crmcore.config import limpiar_cache_settings

    os.environ["SERVICE_NAME"] = servicio
    os.environ["BUS_BACKEND"] = "memoria"
    limpiar_cache_settings()
    return importlib.import_module(f"services.{servicio}.main").app


def _es_una_pagina(esquema: dict[str, Any], contrato: dict[str, Any]) -> bool:
    ref = esquema.get("$ref")
    if ref and ref.startswith("#/components/schemas/"):
        nombre = ref.rsplit("/", 1)[-1]
        esquema = (contrato.get("components", {}).get("schemas", {}) or {}).get(nombre, {})
    propiedades = esquema.get("properties") or {}
    return "items" in propiedades and "total_aprox" in propiedades


def test_todo_listado_que_publica_total_aprox_sabe_rellenarlo() -> None:
    """Se le pregunta a la aplicación construida, no al fichero.

    Un listado se registra de cuatro formas distintas —a mano, por la fábrica,
    por un router transversal, por un `include_router` de otro módulo— y leer
    el código no las ve todas. El OpenAPI de la app sí: es lo que de verdad se
    publica.
    """
    sin_contar: list[str] = []

    for servicio in SERVICIOS:
        contrato = _app(servicio).openapi()
        for ruta, metodos in (contrato.get("paths") or {}).items():
            operacion = metodos.get("get")
            if not operacion or not ruta.startswith("/api/v1/"):
                continue
            contenido = (
                ((operacion.get("responses") or {}).get("200") or {}).get("content") or {}
            ).get("application/json") or {}
            if not _es_una_pagina(contenido.get("schema") or {}, contrato):
                continue
            nombres = {p.get("name") for p in operacion.get("parameters") or []}
            if "contar" in nombres:
                continue
            clave = f"{servicio}: GET {ruta}"
            if clave not in NO_SABEN_CONTAR:
                sin_contar.append(clave)

    assert not sin_contar, (
        f"{len(sin_contar)} listados publican `total_aprox` en su contrato y no "
        "tienen forma de rellenarlo: el campo se declara y no llega nunca.\n  "
        + "\n  ".join(sorted(sin_contar))
    )


def _cabeceras(tenant_id: UUID) -> dict[str, str]:
    from crmcore.config import get_settings
    from crmcore.http.deps import H_PERMISOS, H_TENANT, H_USER, firmar_cabeceras_internas

    return firmar_cabeceras_internas(
        {H_TENANT: str(tenant_id), H_USER: str(uuid4()), H_PERMISOS: "*:*"},
        get_settings().secret_key.get_secret_value(),
    )


@pytest.fixture
def cliente_party(db: Any) -> Any:
    from crmcore.http.deps import get_db
    from fastapi.testclient import TestClient

    app = _app("party")
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as cliente:
            yield cliente
    finally:
        app.dependency_overrides.clear()


def _cuentas(db: Any, tenant_id: UUID, cuantas: int, estado: str = "activa") -> None:
    from services.party.modelos import Cuenta

    for i in range(cuantas):
        db.add(
            Cuenta(
                tenant_id=tenant_id,
                nombre=f"{estado} {i:02d}",
                clave_canonica=f"{estado}{i:02d}",
                estado=estado,
            )
        )
    db.flush()


def test_sin_pedirlo_no_se_cuenta(cliente_party: Any, db: Any, tenant_id: UUID) -> None:
    """Contar cuesta un recorrido de la tabla: no se hace de oficio."""
    _cuentas(db, tenant_id, 3)
    r = cliente_party.get("/api/v1/accounts", headers=_cabeceras(tenant_id))
    assert r.status_code == 200, r.text
    # La clave viene igual —está en el `response_model`, así que FastAPI la
    # serializa— y lo que se comprueba es que llegue **vacía**: así era como
    # llegaba siempre antes de esto, en los treinta y tres listados.
    assert r.json().get("total_aprox") is None, (
        "El total ha llegado sin pedirlo: entonces cada listado de cada pantalla "
        "paga un recorrido completo de la tabla para un número que casi nadie mira."
    )


def test_el_total_no_encoge_al_pasar_de_pagina(
    cliente_party: Any, db: Any, tenant_id: UUID
) -> None:
    """El fallo que se cuela: contar con el cursor puesto.

    Con el cursor aplicado, el `count` dice **cuántas quedan de aquí en
    adelante**. En la primera página coincide con el total y parece correcto;
    en la segunda ya miente, y nadie vuelve a mirar la primera.
    """
    _cuentas(db, tenant_id, 5)
    cab = _cabeceras(tenant_id)

    primera = cliente_party.get("/api/v1/accounts?limite=2&contar=true", headers=cab).json()
    assert primera["total_aprox"] == 5, primera
    assert len(primera["items"]) == 2
    assert primera["hay_mas"] is True

    segunda = cliente_party.get(
        f"/api/v1/accounts?limite=2&contar=true&cursor={primera['siguiente']}", headers=cab
    ).json()
    assert segunda["total_aprox"] == 5, (
        "El total ha cambiado al pasar de página: se está contando DESPUÉS del "
        f"cursor, así que lo que devuelve es cuántas quedan ({segunda['total_aprox']}) "
        "con cara de ser el total (5)."
    )


def test_el_total_es_el_de_los_filtros_no_el_de_la_tabla(
    cliente_party: Any, db: Any, tenant_id: UUID
) -> None:
    """Un total que no pasa por los filtros no contesta a la pregunta.

    Y además es una filtración: diría cuántas hay en la tabla, no cuántas ve
    quien pregunta.
    """
    _cuentas(db, tenant_id, 4, estado="activa")
    _cuentas(db, tenant_id, 3, estado="inactiva")
    cab = _cabeceras(tenant_id)

    todas = cliente_party.get("/api/v1/accounts?contar=true", headers=cab).json()
    assert todas["total_aprox"] == 7, todas

    activas = cliente_party.get("/api/v1/accounts?contar=true&estado=activa", headers=cab).json()
    assert activas["total_aprox"] == 4, (
        f"Con el filtro puesto el total dice {activas['total_aprox']} de 7: se está "
        "contando la tabla entera y no la consulta filtrada."
    )


def test_tambien_cuenta_por_los_otros_dos_caminos(
    cliente_party: Any, db: Any, tenant_id: UUID
) -> None:
    """Los otros dos: `paginar_consulta` y la fábrica.

    Van juntos a propósito. Lo que se comprueba no es cada listado —son
    treinta y tres— sino que **el número llega por los tres caminos por los que
    se sirve una página**. `paginar_consulta` era el peor de los tres: contaba
    la consulta y luego construía el diccionario de respuesta a mano,
    olvidándose de `total_aprox`. Pagaba el recorrido completo de la tabla y
    tiraba el número en la puerta.
    """
    from services.party.cuenta_360 import PlanCuenta
    from services.party.modelos import Actividad

    cuenta_id = uuid4()
    for i in range(3):
        db.add(Actividad(tenant_id=tenant_id, tipo="llamada", asunto=f"a{i}", cuenta_id=cuenta_id))
    for i in range(2):
        db.add(PlanCuenta(tenant_id=tenant_id, cuenta_id=cuenta_id, periodo=f"2026-Q{i + 1}"))
    db.flush()
    cab = _cabeceras(tenant_id)

    # Por `paginar_consulta`.
    act = cliente_party.get("/api/v1/activities?contar=true", headers=cab)
    assert act.status_code == 200, act.text
    assert act.json()["total_aprox"] == 3, act.json()

    # Por la fábrica (`montar_listado`).
    planes = cliente_party.get("/api/v1/planes-cuenta?contar=true", headers=cab)
    assert planes.status_code == 200, planes.text
    assert planes.json()["total_aprox"] == 2, planes.json()


def test_el_unico_que_cuenta_sin_pedirselo(db: Any, tenant_id: UUID) -> None:
    """La excepción de `NO_SABEN_CONTAR`, medida.

    Está exenta de `?contar=true` porque da el total siempre. Si deja de darlo,
    la exención se queda en el diccionario diciendo que todo está bien — que es
    la forma en que una lista de excepciones se convierte en una lista de
    permisos.
    """
    from crmcore.http.deps import get_db
    from fastapi.testclient import TestClient

    app = _app("metadata")
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as cliente:
            r = cliente.get("/api/v1/entornos", headers=_cabeceras(tenant_id))
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["total_aprox"] == len(cuerpo["items"]), (
        "El listado exento de `?contar=true` ha dejado de dar el total: la "
        "exención ya no se sostiene y hay que quitarla de NO_SABEN_CONTAR."
    )
