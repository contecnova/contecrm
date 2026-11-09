"""El caso tiene máquina de estados configurable, y el SLA lee lo que significan.

Pedido el 09-11-2026 («todo configurable por administradores»). El código ya
lo anunciaba: qué estados paran el reloj «cambia por cliente: hay contratos
donde "esperando repuesto" lo para y otros donde no». Ahora es un estado propio
que significa «en pausa», y el reloj se para solo.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import pytest
from crmcore.datos import estados as est
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion

from services.service import servicio as svc
from services.service.estados import terminales

pytestmark = pytest.mark.db


def _con_repuesto_y_archivado() -> dict[str, Any]:
    conf = est.a_configuracion(est.MAQUINAS["caso"], de_fabrica=True)
    conf["estados"] += [
        {"clave": "esperando_repuesto", "nombre": "Esperando repuesto", "significado": "en_pausa"},
        {"clave": "archivado", "nombre": "Archivado", "significado": "cerrado"},
    ]
    conf["transiciones"]["en_curso"] = [*conf["transiciones"]["en_curso"], "esperando_repuesto"]
    conf["transiciones"]["esperando_repuesto"] = ["en_curso", "archivado"]
    conf["transiciones"]["archivado"] = ["en_curso"]
    # Y el «cerrado» de fábrica desactivado: la empresa cierra archivando.
    for e in conf["estados"]:
        if e["clave"] == "cerrado":
            e["activo"] = False
    conf["transiciones"] = {
        o: [d for d in ds if d != "cerrado"]
        for o, ds in conf["transiciones"].items()
        if o != "cerrado"
    }
    return conf


@pytest.fixture
def configurado(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> Any:
    from crmcore.runtime.settings import fijar, invalidar

    fijar(
        db,
        "maquinas_de_estado",
        {"caso": _con_repuesto_y_archivado()},
        ambito_id=str(tenant_id),
    )
    invalidar()
    yield
    invalidar()


def test_un_estado_propio_en_pausa_para_el_reloj(
    db: Any, tenant_id: UUID, configurado: Any
) -> None:
    uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
    caso = svc.abrir_caso(uow, asunto="Rotura")
    svc.cambiar_estado(uow, caso.id, estado="en_curso")
    svc.cambiar_estado(uow, caso.id, estado="esperando_repuesto")
    assert caso.pausado_desde is not None
    caso.pausado_desde = datetime.now(timezone.utc) - timedelta(hours=2)
    db.flush()
    svc.cambiar_estado(uow, caso.id, estado="en_curso")
    assert caso.pausa_acumulada_s >= 2 * 3600 - 5


def test_cerrar_lleva_al_estado_que_significa_cerrado(
    db: Any, tenant_id: UUID, configurado: Any
) -> None:
    uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
    caso = svc.abrir_caso(uow, asunto="Duda")
    svc.cerrar_caso(uow, caso.id, motivo="resuelto")
    # El «cerrado» de fábrica está desactivado: cierra en el suyo.
    assert caso.estado == "archivado"
    assert "archivado" in terminales(db)
    # Y reabrir lo reconoce como cerrado.
    svc.reabrir_caso(uow, caso.id, motivo="Vuelve a fallar", ventana_dias=0)
    assert caso.estado == "en_curso"


def test_un_paso_que_la_empresa_no_permite_se_rechaza(
    db: Any, tenant_id: UUID, configurado: Any
) -> None:
    uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
    caso = svc.abrir_caso(uow, asunto="X")
    # De «nuevo» no se va a «esperando repuesto»: sólo desde «en curso».
    with pytest.raises(Conflicto):
        svc.cambiar_estado(uow, caso.id, estado="esperando_repuesto")
    # Y un estado desactivado ya no es un estado al que ir.
    with pytest.raises(ErrorValidacion) as exc:
        svc.cambiar_estado(uow, caso.id, estado="cerrado", motivo="x")
    assert exc.value.error_code == "caso.estado_desconocido"


def test_el_estado_de_fabrica_activo_gana_al_poner() -> None:
    # Sin configuración, cerrar es «cerrado», como siempre.
    assert est.estado_de("caso", "cerrado", None) == "cerrado"
    assert est.estado_de("caso", "en_pausa", None) == "esperando_cliente"


def test_cerrar_y_reabrir_desde_el_estado_pasan_por_su_camino(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
    caso = svc.abrir_caso(uow, asunto="Y")
    svc.cambiar_estado(uow, caso.id, estado="cerrado", motivo="resuelto")
    # Cerrar por el estado deja lo mismo que «Cerrar»: fecha y motivo.
    assert caso.cerrado_at is not None and caso.motivo_cierre == "resuelto"

    # Reabrir por el estado sin motivo no pasa…
    with pytest.raises((ErrorValidacion, Conflicto)):
        svc.cambiar_estado(uow, caso.id, estado="en_curso")
    # …y con motivo cuenta como reapertura, que es lo que se mide.
    svc.cambiar_estado(uow, caso.id, estado="en_curso", motivo="Vuelve a fallar")
    assert caso.reaperturas == 1 and caso.cerrado_at is None
