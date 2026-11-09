"""La clasificación TCSEC dice lo que mide, y no sube de nivel con lo que no.

Pedido el 09-11-2026: clasificar la instalación por nivel, los controles que
exige cada nivel y el informe para auditoría.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.errors import ErrorValidacion

from services.tenancy import tcsec

pytestmark = pytest.mark.db


def _todo(estado: str) -> Any:
    return lambda ctx: (estado, "medido", {})


def _con(monkeypatch: pytest.MonkeyPatch, **por_clave: str) -> None:
    """Sustituye las comprobaciones: las nombradas dan ese estado, el resto cumple."""
    nuevos = tuple(
        replace(r, comprobar=_todo(por_clave.get(r.clave, tcsec.CUMPLE)))
        if r.comprobar is not None
        else r
        for r in tcsec.REQUISITOS
    )
    monkeypatch.setattr(tcsec, "REQUISITOS", nuevos)
    monkeypatch.setattr(tcsec, "_POR_CLAVE", {r.clave: r for r in nuevos})


def test_el_nivel_es_el_ultimo_con_todo_cumplido(
    db: Any, tenant_id: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    _con(monkeypatch, **{"C2-RESP": tcsec.NO_CUMPLE})
    ev = tcsec.evaluar(db, tenant_id, uuid4())
    assert ev["nivel"] == "C1"
    assert ev["siguiente"] == "C2" and ev["falta_para_el_siguiente"] == ["C2-RESP"]


def test_lo_que_no_se_pudo_medir_no_cuenta_como_cumplido(
    db: Any, tenant_id: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    def revienta(ctx: Any) -> Any:
        raise RuntimeError("identidad caída")

    _con(monkeypatch)
    nuevos = tuple(
        replace(r, comprobar=revienta) if r.clave == "C1-DAC" else r for r in tcsec.REQUISITOS
    )
    monkeypatch.setattr(tcsec, "REQUISITOS", nuevos)
    ev = tcsec.evaluar(db, tenant_id, uuid4())
    dac = next(r for r in ev["requisitos"] if r["clave"] == "C1-DAC")
    assert dac["estado"] == tcsec.SIN_MEDIR and "identidad caída" in dac["detalle"]
    assert ev["nivel"] == "D"


def test_b1_no_se_alcanza_mientras_falte_la_escritura_por_etiqueta(
    db: Any, tenant_id: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    _con(monkeypatch)
    nuevos = tuple(
        replace(r, comprobar=tcsec._escritura_por_etiqueta) if r.clave == "B1-MAC-ESCRIBIR" else r
        for r in tcsec.REQUISITOS
    )
    monkeypatch.setattr(tcsec, "REQUISITOS", nuevos)
    ev = tcsec.evaluar(db, tenant_id, uuid4())
    assert ev["nivel"] == "C2"
    assert "B1-MAC-ESCRIBIR" in ev["falta_para_el_siguiente"]
    # Y no se puede tapar con una atestación.
    with pytest.raises(ErrorValidacion) as exc:
        tcsec.atestiguar(
            db,
            tenant_id=tenant_id,
            requisito="B1-MAC-ESCRIBIR",
            resultado="efectivo",
            evidencia="dicho",
            por=None,
        )
    assert exc.value.error_code == "tcsec.se_mide_solo"


def test_un_requisito_atestiguado_cumple_hasta_que_caduca(db: Any, tenant_id: UUID) -> None:
    from services.tenancy.grc import EvaluacionControl

    ctx = tcsec.Contexto(db=db, tenant_id=tenant_id, principal_id=uuid4(), _cache={})
    req = tcsec._POR_CLAVE["B2-CANALES"]
    assert tcsec._atestacion(ctx, req)[0] == tcsec.NO_CUMPLE

    with pytest.raises(ErrorValidacion) as exc:
        tcsec.atestiguar(
            db,
            tenant_id=tenant_id,
            requisito="B2-CANALES",
            resultado="efectivo",
            evidencia=" ",
            por=None,
        )
    assert exc.value.error_code == "tcsec.sin_evidencia"

    tcsec.atestiguar(
        db,
        tenant_id=tenant_id,
        requisito="B2-CANALES",
        resultado="efectivo",
        evidencia="Análisis de canales, acta 2026-11",
        por=None,
    )
    estado, _, datos = tcsec._atestacion(ctx, req)
    assert estado == tcsec.CUMPLE and datos["evidencia"].startswith("Análisis")

    # Vencida, deja de valer.
    fila = db.query(EvaluacionControl).filter_by(control_codigo="TCSEC-B2-CANALES").one()
    fila.proxima_at = fila.fecha - timedelta(days=1)
    db.flush()
    assert tcsec._atestacion(ctx, req)[0] == tcsec.NO_CUMPLE


def test_el_informe_lleva_el_nivel_y_cada_requisito(
    db: Any, tenant_id: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    _con(monkeypatch, **{"C1-AISLA": tcsec.NO_CUMPLE})
    texto = tcsec.informe_markdown(tcsec.evaluar(db, tenant_id, uuid4()))
    assert "**Nivel alcanzado**: D" in texto
    for r in tcsec.REQUISITOS:
        assert r.clave in texto
    assert "| No cumple |" in texto


def test_un_ajuste_no_editable_se_lee_de_la_configuracion(db: Any, tenant_id: UUID) -> None:
    # `login_bloqueo_minutos` no es editable en caliente: leído sólo como
    # ajuste daba vacío, y C1 salía «bloqueo apagado» con el bloqueo a 15.
    ctx = tcsec.Contexto(db=db, tenant_id=tenant_id, principal_id=uuid4(), _cache={})
    estado, detalle, datos = tcsec._identificacion(ctx)
    assert datos["login_bloqueo_minutos"] > 0
    assert estado == tcsec.CUMPLE, detalle
