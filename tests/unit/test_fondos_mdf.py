"""Fondos de marketing del canal — MDF (CRM-03.04.01.04).

Dinero del fabricante que gasta el partner. Las pruebas van detrás de los cuatro
sitios donde ese dinero se pierde:

  * el saldo que solo descuenta lo pagado y deja sobrecomprometer el fondo,
  * el plazo de justificación que no existe y deja facturas contra un
    presupuesto cerrado,
  * la justificación de 6.000 que se paga como 10.000,
  * y el retorno estupendo calculado sobre el 10 % del gasto.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion

from services.marketing import fondos as mdf


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


@pytest.fixture
def partner_id(uow: UnidadDeTrabajo) -> UUID:
    pid = uuid4()
    mdf.registrar_partner(
        uow.db, tenant_id=uow.tenant_id, partner_id=pid, clave="acme", nombre="Acme"
    )
    return pid


def _fondo(uow: UnidadDeTrabajo, partner_id: UUID, asignado: Decimal = Decimal(10000)):
    fila, _ = mdf.crear_fondo(
        uow,
        partner_id=partner_id,
        desde=date.today() - timedelta(days=30),
        hasta=date.today() + timedelta(days=300),
        asignado=asignado,
    )
    return fila


# ── Apertura y proyección ─────────────────────────────────────────────────


def test_el_partner_llega_por_evento_y_se_avisa_si_no_ha_llegado(
    uow: UnidadDeTrabajo,
) -> None:
    """Bloquear haría que un retraso del bus pareciera un error del usuario."""
    _, avisos = mdf.crear_fondo(
        uow,
        partner_id=uuid4(),
        desde=date.today(),
        hasta=date.today() + timedelta(days=90),
        asignado=Decimal(1000),
    )
    assert avisos and "bus de eventos" in avisos[0]


def test_un_fondo_de_cero_no_es_un_fondo(uow: UnidadDeTrabajo, partner_id: UUID) -> None:
    with pytest.raises(ErrorValidacion):
        mdf.crear_fondo(
            uow,
            partner_id=partner_id,
            desde=date.today(),
            hasta=date.today() + timedelta(days=90),
            asignado=Decimal(0),
        )


# ── Saldo (CRM-03.04.01.04) ───────────────────────────────────────────────


def test_lo_comprometido_resta_del_saldo(uow: UnidadDeTrabajo, partner_id: UUID) -> None:
    """Un saldo que solo descuenta lo pagado enseña dinero que ya tiene dueño."""
    fondo = _fondo(uow, partner_id)
    solicitud = mdf.solicitar(uow, fondo.id, titulo="Feria", importe=Decimal(4000))
    mdf.decidir(uow, solicitud.id, aprobar=True)
    estado = mdf.saldo(uow.db, uow.tenant_id, fondo.id)
    assert Decimal(estado["comprometido"]) == Decimal(4000)
    assert Decimal(estado["disponible"]) == Decimal(6000)
    assert Decimal(estado["pagado"]) == Decimal(0)


def test_no_se_aprueba_por_encima_del_saldo(uow: UnidadDeTrabajo, partner_id: UUID) -> None:
    """Es el momento exacto en que se sobrecompromete un fondo."""
    fondo = _fondo(uow, partner_id, Decimal(5000))
    una = mdf.solicitar(uow, fondo.id, titulo="Feria", importe=Decimal(4000))
    otra = mdf.solicitar(uow, fondo.id, titulo="Webinar", importe=Decimal(2000))
    mdf.decidir(uow, una.id, aprobar=True)
    with pytest.raises(Conflicto) as error:
        mdf.decidir(uow, otra.id, aprobar=True)
    assert error.value.detalle["disponible"] == "1000.00"


def test_se_puede_pedir_aunque_no_haya_saldo(uow: UnidadDeTrabajo, partner_id: UUID) -> None:
    """Impedirlo escondería cuánto se está pidiendo de más, que es lo que hace
    falta para decidir si se amplía el fondo."""
    fondo = _fondo(uow, partner_id, Decimal(1000))
    mdf.solicitar(uow, fondo.id, titulo="Feria", importe=Decimal(9000))
    estado = mdf.saldo(uow.db, uow.tenant_id, fondo.id)
    assert Decimal(estado["pendiente_de_decidir"]) == Decimal(9000)
    assert estado["cabria_todo"] is False


def test_se_puede_aprobar_menos_de_lo_pedido(uow: UnidadDeTrabajo, partner_id: UUID) -> None:
    """«Aprobado» a secas obliga a aprobar todo o nada."""
    fondo = _fondo(uow, partner_id)
    solicitud = mdf.solicitar(uow, fondo.id, titulo="Feria", importe=Decimal(8000))
    decidida = mdf.decidir(uow, solicitud.id, aprobar=True, importe_aprobado=Decimal(3000))
    assert Decimal(decidida.importe_aprobado or 0) == Decimal(3000)


def test_rechazar_exige_motivo(uow: UnidadDeTrabajo, partner_id: UUID) -> None:
    fondo = _fondo(uow, partner_id)
    solicitud = mdf.solicitar(uow, fondo.id, titulo="Feria", importe=Decimal(1000))
    with pytest.raises(ErrorValidacion):
        mdf.decidir(uow, solicitud.id, aprobar=False)
    mdf.decidir(uow, solicitud.id, aprobar=False, motivo="Fuera del plan conjunto")


def test_un_fondo_cerrado_no_admite_solicitudes(uow: UnidadDeTrabajo, partner_id: UUID) -> None:
    fondo = _fondo(uow, partner_id)
    fondo.cerrado = True
    uow.db.flush()
    with pytest.raises(Conflicto):
        mdf.solicitar(uow, fondo.id, titulo="Tarde", importe=Decimal(100))


# ── Justificación y plazo ─────────────────────────────────────────────────


def test_el_plazo_no_se_pasa_del_cierre_del_fondo(uow: UnidadDeTrabajo, partner_id: UUID) -> None:
    """Justificar en marzo contra un presupuesto que cerró en diciembre no lo
    cobra nadie."""
    fila, _ = mdf.crear_fondo(
        uow,
        partner_id=partner_id,
        desde=date.today() - timedelta(days=10),
        hasta=date.today() + timedelta(days=10),
        asignado=Decimal(5000),
    )
    solicitud = mdf.solicitar(uow, fila.id, titulo="Feria", importe=Decimal(1000))
    decidida = mdf.decidir(uow, solicitud.id, aprobar=True, dias_para_justificar=180)
    assert decidida.justificar_antes_de == fila.hasta


def test_sin_evidencia_no_hay_justificacion(uow: UnidadDeTrabajo, partner_id: UUID) -> None:
    """Lo que se paga sin factura no se puede defender en una auditoría."""
    fondo = _fondo(uow, partner_id)
    solicitud = mdf.solicitar(uow, fondo.id, titulo="Feria", importe=Decimal(1000))
    mdf.decidir(uow, solicitud.id, aprobar=True)
    with pytest.raises(ErrorValidacion):
        mdf.justificar(uow, solicitud.id, importe=Decimal(1000))


def test_justificar_fuera_de_plazo_se_admite_marcado(
    uow: UnidadDeTrabajo, partner_id: UUID
) -> None:
    """No dejar hace que la factura llegue por correo y se meta a mano sin plazo."""
    fondo = _fondo(uow, partner_id)
    solicitud = mdf.solicitar(uow, fondo.id, titulo="Feria", importe=Decimal(1000))
    mdf.decidir(uow, solicitud.id, aprobar=True)
    solicitud.justificar_antes_de = date.today() - timedelta(days=1)
    uow.db.flush()
    _, avisos = mdf.justificar(
        uow,
        solicitud.id,
        importe=Decimal(1000),
        evidencias=[{"documento_id": str(uuid4())}],
        resultados={"leads": 20},
    )
    assert any("Fuera de plazo" in a for a in avisos)


def test_justificar_sin_resultados_avisa_de_que_no_se_medira(
    uow: UnidadDeTrabajo, partner_id: UUID
) -> None:
    fondo = _fondo(uow, partner_id)
    solicitud = mdf.solicitar(uow, fondo.id, titulo="Feria", importe=Decimal(1000))
    mdf.decidir(uow, solicitud.id, aprobar=True)
    _, avisos = mdf.justificar(
        uow, solicitud.id, importe=Decimal(1000), evidencias=[{"documento_id": str(uuid4())}]
    )
    assert any("no se sabe" in a for a in avisos)


def test_se_acepta_lo_menor_de_aprobado_y_justificado(
    uow: UnidadDeTrabajo, partner_id: UUID
) -> None:
    """Pagar lo aprobado sin mirar la justificación es regalar dinero."""
    fondo = _fondo(uow, partner_id)
    solicitud = mdf.solicitar(uow, fondo.id, titulo="Feria", importe=Decimal(10000))
    mdf.decidir(uow, solicitud.id, aprobar=True)
    justificacion, _ = mdf.justificar(
        uow,
        solicitud.id,
        importe=Decimal(6000),
        evidencias=[{"documento_id": str(uuid4())}],
        resultados={"leads": 30},
    )
    actualizada = mdf.revisar_justificacion(uow, justificacion.id, aceptar=True)
    assert Decimal(actualizada.importe_justificado or 0) == Decimal(6000)


def test_justificar_de_mas_no_paga_de_mas(uow: UnidadDeTrabajo, partner_id: UUID) -> None:
    fondo = _fondo(uow, partner_id)
    solicitud = mdf.solicitar(uow, fondo.id, titulo="Feria", importe=Decimal(1000))
    mdf.decidir(uow, solicitud.id, aprobar=True, importe_aprobado=Decimal(1000))
    justificacion, avisos = mdf.justificar(
        uow,
        solicitud.id,
        importe=Decimal(1500),
        evidencias=[{"documento_id": str(uuid4())}],
        resultados={"leads": 5},
    )
    assert any("más de lo aprobado" in a for a in avisos)
    actualizada = mdf.revisar_justificacion(uow, justificacion.id, aceptar=True)
    assert Decimal(actualizada.importe_justificado or 0) == Decimal(1000)


def test_solo_se_paga_lo_justificado_y_con_referencia(
    uow: UnidadDeTrabajo, partner_id: UUID
) -> None:
    fondo = _fondo(uow, partner_id)
    solicitud = mdf.solicitar(uow, fondo.id, titulo="Feria", importe=Decimal(1000))
    mdf.decidir(uow, solicitud.id, aprobar=True)
    with pytest.raises(Conflicto):
        mdf.pagar(uow, solicitud.id, referencia="FAC-1")
    justificacion, _ = mdf.justificar(
        uow,
        solicitud.id,
        importe=Decimal(1000),
        evidencias=[{"documento_id": str(uuid4())}],
        resultados={"leads": 10},
    )
    mdf.revisar_justificacion(uow, justificacion.id, aceptar=True)
    with pytest.raises(ErrorValidacion):
        mdf.pagar(uow, solicitud.id, referencia=" ")
    pagada = mdf.pagar(uow, solicitud.id, referencia="FAC-1")
    assert pagada.estado == "pagada"


def test_caducar_libera_el_dinero_y_deja_constancia(uow: UnidadDeTrabajo, partner_id: UUID) -> None:
    """Una caducidad calculada al vuelo acaba en «a mí nadie me avisó»."""
    fondo = _fondo(uow, partner_id)
    solicitud = mdf.solicitar(uow, fondo.id, titulo="Feria", importe=Decimal(4000))
    mdf.decidir(uow, solicitud.id, aprobar=True)
    solicitud.justificar_antes_de = date.today() - timedelta(days=1)
    uow.db.flush()

    salida = mdf.caducar_pendientes(uow)
    assert Decimal(salida["liberado"]) == Decimal(4000)
    assert str(solicitud.id) in salida["caducadas"]
    assert solicitud.motivo
    estado = mdf.saldo(uow.db, uow.tenant_id, fondo.id)
    assert Decimal(estado["disponible"]) == Decimal(10000)


# ── Retorno ───────────────────────────────────────────────────────────────


def test_el_retorno_dice_la_cobertura_de_la_medicion(
    uow: UnidadDeTrabajo, partner_id: UUID
) -> None:
    """Un retorno calculado sobre el 10 % del gasto no es el retorno del fondo."""
    fondo = _fondo(uow, partner_id)
    for titulo, resultados in (("Con datos", {"leads": 100}), ("Sin datos", {})):
        solicitud = mdf.solicitar(uow, fondo.id, titulo=titulo, importe=Decimal(1000))
        mdf.decidir(uow, solicitud.id, aprobar=True)
        justificacion, _ = mdf.justificar(
            uow,
            solicitud.id,
            importe=Decimal(1000),
            evidencias=[{"documento_id": str(uuid4())}],
            resultados=resultados,
        )
        mdf.revisar_justificacion(uow, justificacion.id, aceptar=True)

    salida = mdf.retorno(uow.db, uow.tenant_id, fondo.id)
    assert salida["campanas"] == 2 and salida["campanas_con_resultados"] == 1
    assert salida["cobertura_pct"] == 50.0
    assert salida["resultados"]["leads"] == "100"
    assert salida["coste_por"]["leads"] == "10.00"
    assert salida["aviso"]


def test_sin_ninguna_campana_medida_el_retorno_no_es_concluyente(
    uow: UnidadDeTrabajo, partner_id: UUID
) -> None:
    fondo = _fondo(uow, partner_id)
    salida = mdf.retorno(uow.db, uow.tenant_id, fondo.id)
    assert salida["medible"] is False
