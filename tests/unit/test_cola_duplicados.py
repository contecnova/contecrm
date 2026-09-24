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
