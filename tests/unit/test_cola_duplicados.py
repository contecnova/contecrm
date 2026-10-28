"""Los duplicados se encuentran solos, y los decide una persona (CRM-01.01.03.03).

Buscar duplicados ya se hacía, pero **solo al crear**: se escribía un nombre y
el sistema avisaba de a qué se parecía. Eso protege lo que entra desde hoy y no
dice nada de lo que ya está dentro — que es donde está el problema, porque los
duplicados no llegan de uno en uno: llegan de golpe con una importación.

Lo que estas pruebas defienden:

  * El barrido propone parejas **con su probabilidad y su porqué**.
  * Se puede repetir sin llenar la cola de lo mismo.
  * «No es un duplicado» se recuerda: no vuelve a proponerse.
  * Fusionar **exige decir cuál se queda**, aunque la señal sea concluyente.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from crmcore.errors import ErrorValidacion


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> Any:
    from crmcore.db.uow import UnidadDeTrabajo

    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


@pytest.fixture
def dos_iguales(uow: Any, tenant_id: UUID) -> Any:
    from services.party.modelos import Cuenta

    a = Cuenta(
        tenant_id=tenant_id,
        nombre="Talleres Arruti, S.L.",
        clave_canonica="talleres arruti",
        email="info@arruti.example",
        web="https://arruti.example",
    )
    b = Cuenta(
        tenant_id=tenant_id,
        nombre="Talleres Arruti SL",
        clave_canonica="talleres arruti",
        email="hola@arruti.example",
        web="https://arruti.example",
    )
    uow.db.add_all([a, b])
    uow.db.flush()
    return a, b


def test_el_barrido_propone_con_probabilidad_y_porque(uow: Any, dos_iguales: Any) -> None:
    from services.party import cola_duplicados as cd

    resumen = cd.barrido(uow, limite=50)

    assert resumen["propuestas"] >= 1, resumen
    cola = cd.cola(uow.db)
    assert cola, "el barrido no ha dejado nada en la cola"
    # La probabilidad va en porcentaje: «0.873» obliga a traducirlo y «87» se
    # lee de un vistazo.
    assert 0 <= cola[0]["probabilidad"] <= 100
    # Y con el porqué: sin él hay que abrir las dos fichas para decidir.
    assert cola[0]["senales"], cola[0]


def test_repetir_el_barrido_no_duplica_la_cola(uow: Any, dos_iguales: Any) -> None:
    from services.party import cola_duplicados as cd

    cd.barrido(uow, limite=50)
    cuantas = len(cd.cola(uow.db))
    cd.barrido(uow, limite=50)

    assert len(cd.cola(uow.db)) == cuantas


def test_lo_descartado_no_vuelve_a_proponerse(uow: Any, dos_iguales: Any) -> None:
    """Una cola que reaparece entera es una cola que se deja de mirar."""
    from services.party import cola_duplicados as cd

    cd.barrido(uow, limite=50)
    pareja = cd.cola(uow.db)[0]
    cd.decidir(
        uow,
        candidato_id=UUID(pareja["id"]),
        decision="no_es_duplicado",
        por=None,
        nota="Dos sociedades del mismo grupo",
    )

    cd.barrido(uow, limite=50)

    assert all(c["id"] != pareja["id"] for c in cd.cola(uow.db))


def test_fusionar_exige_decir_cual_se_queda(uow: Any, dos_iguales: Any) -> None:
    """Aunque la señal sea concluyente: la que sobrevive conserva el
    identificador que usan los sistemas de fuera, y eso no lo sabe un
    algoritmo."""
    from services.party import cola_duplicados as cd

    cd.barrido(uow, limite=50)
    pareja = cd.cola(uow.db)[0]

    with pytest.raises(ErrorValidacion) as fallo:
        cd.decidir(uow, candidato_id=UUID(pareja["id"]), decision="fusionar", por=None)

    assert fallo.value.error_code == "duplicados.falta_superviviente"


def test_una_decision_inventada_se_rechaza(uow: Any, dos_iguales: Any) -> None:
    from services.party import cola_duplicados as cd

    cd.barrido(uow, limite=50)
    pareja = cd.cola(uow.db)[0]

    with pytest.raises(ErrorValidacion) as fallo:
        cd.decidir(uow, candidato_id=UUID(pareja["id"]), decision="borrar", por=None)

    assert fallo.value.error_code == "duplicados.decision_invalida"


# ── Por la ruta, que es por donde entra la pantalla ───────────────────────
#
# Las pruebas de arriba llaman a `cola_duplicados` como módulo, y eso deja un
# hueco con forma de fallo real: la pantalla «Duplicados por resolver» declara
# la FORMA de dos respuestas —lo que devuelve el barrido y lo que devuelve una
# pareja decidida— y, si el servidor dejara de mandar uno de esos campos, la
# pantalla no daría error: se quedaría sin decir cuántas fichas ha mirado, o
# sin poder aprobar nada. Aquí se entra por la ruta.


@pytest.fixture
def cliente_party() -> Any:
    import importlib
    import os

    from crmcore.config import get_settings
    from starlette.testclient import TestClient

    previo = {k: os.environ.get(k) for k in ("OUTBOX_ENABLED", "TAREAS_FONDO_ENABLED")}
    os.environ["OUTBOX_ENABLED"] = "false"
    os.environ["TAREAS_FONDO_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        with TestClient(importlib.import_module("services.party.main").app) as cli:
            yield cli
    finally:
        for clave, valor in previo.items():
            if valor is None:
                os.environ.pop(clave, None)
            else:
                os.environ[clave] = valor
        get_settings.cache_clear()


def _cabeceras(tenant_id: UUID) -> dict[str, str]:
    from uuid import uuid4

    from crmcore.config import get_settings
    from crmcore.http.deps import H_PERMISOS, H_TENANT, H_USER, firmar_cabeceras_internas

    return firmar_cabeceras_internas(
        {H_TENANT: str(tenant_id), H_USER: str(uuid4()), H_PERMISOS: "*:*"},
        get_settings().secret_key.get_secret_value(),
    )


@pytest.mark.db
def test_la_pantalla_de_duplicados_recibe_lo_que_pinta(
    cliente_party: Any, uow: Any, tenant_id: UUID, dos_iguales: Any
) -> None:
    """Los campos que `Duplicados.tsx` lee, pedidos por la ruta."""
    cabeceras = _cabeceras(tenant_id)

    barrido = cliente_party.post(
        "/api/v1/data-quality/accounts/duplicates/barrido", headers=cabeceras, json={}
    )
    assert barrido.status_code == 200, barrido.text
    # «Hecho» a secas no dice si ha mirado tres fichas o tres mil, y la
    # pantalla lo enseña: tiene que venir.
    assert {"revisadas", "propuestas", "umbral"} <= set(barrido.json())
    assert barrido.json()["revisadas"] >= 2

    cola = cliente_party.get(
        "/api/v1/data-quality/accounts/duplicates/cola?pendientes=true&limite=100",
        headers=cabeceras,
    )
    assert cola.status_code == 200, cola.text
    parejas = cola.json()
    assert parejas, "el barrido ha propuesto y la cola no lo enseña"
    pareja = parejas[0]
    # Sin el identificador no se puede decidir nada; sin los dos lados no se
    # puede elegir cuál se queda; sin las señales hay que abrir las dos fichas
    # para saber qué se está comparando.
    assert {"id", "a_id", "b_id", "a_nombre", "b_nombre", "senales", "decision"} <= set(pareja)
    # Y la probabilidad viene en porcentaje, que es como la pinta la pantalla:
    # «0,9» obliga a traducirlo mentalmente en cada fila.
    assert 0 <= pareja["probabilidad"] <= 100

    decidida = cliente_party.post(
        f"/api/v1/data-quality/accounts/duplicates/cola/{pareja['id']}",
        headers=cabeceras,
        json={"decision": "no_es_duplicado", "superviviente_id": None, "nota": ""},
    )
    assert decidida.status_code == 200, decidida.text
    assert decidida.json()["decision"] == "no_es_duplicado"

    # Y ya no está entre las pendientes: es lo que impide que la cola reaparezca
    # entera y se deje de mirar.
    quedan = cliente_party.get(
        "/api/v1/data-quality/accounts/duplicates/cola?pendientes=true&limite=100",
        headers=cabeceras,
    )
    assert pareja["id"] not in [p["id"] for p in quedan.json()]


@pytest.mark.db
def test_fusionar_por_la_ruta_exige_el_superviviente(
    cliente_party: Any, uow: Any, tenant_id: UUID, dos_iguales: Any
) -> None:
    """La pantalla no deja pulsar «fusionar» sin elegir, y el servidor tampoco.

    Las dos mitades, porque si sólo lo exigiera la pantalla bastaría con una
    llamada a mano para fusionar lo que el servidor eligiera por su cuenta.
    """
    cabeceras = _cabeceras(tenant_id)
    cliente_party.post(
        "/api/v1/data-quality/accounts/duplicates/barrido", headers=cabeceras, json={}
    )
    pareja = cliente_party.get(
        "/api/v1/data-quality/accounts/duplicates/cola", headers=cabeceras
    ).json()[0]

    sin_elegir = cliente_party.post(
        f"/api/v1/data-quality/accounts/duplicates/cola/{pareja['id']}",
        headers=cabeceras,
        json={"decision": "fusionar", "superviviente_id": None, "nota": ""},
    )
    assert sin_elegir.status_code == 422, sin_elegir.text
    assert sin_elegir.json()["error_code"] == "duplicados.falta_superviviente"

    bien = cliente_party.post(
        f"/api/v1/data-quality/accounts/duplicates/cola/{pareja['id']}",
        headers=cabeceras,
        json={"decision": "fusionar", "superviviente_id": pareja["a_id"], "nota": ""},
    )
    assert bien.status_code == 200, bien.text
    assert bien.json()["decision"] == "fusionar"
