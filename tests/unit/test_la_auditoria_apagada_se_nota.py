"""`AUDIT_ENABLED` y `AUDIT_HASH_CHAIN` no los leía nadie (`CRM-00.05.04`).

Medido el 06-10-2026 con el barrido de ajustes sin lector. Los dos estaban en
`.env.example`, estaban en el manual de referencia y de ahí no pasaban: ponerlos
a `false` no apagaba nada.

Aquí el daño va en los dos sentidos. Quien los pone a `false` para probar algo
cree que ha apagado la auditoría y la sigue teniendo —menos malo—; y quien
hereda una instalación con `AUDIT_ENABLED=false` en el fichero de entorno cree
que no tiene auditoría cuando sí, o al revés el día que alguien los enchufe.

Tres decisiones que no son obvias:

  · **Apagar la auditoría no puede ser invisible.** No marca el servicio como
    «no listo» —no es una avería— pero el readiness lo dice. Una instalación sin
    auditoría tiene que ser una decisión que alguien ve en el panel, no algo que
    se descubre el día que hay que demostrar quién tocó qué.
  · **Apagar la cadena no es romperla.** `verificar` tiene que distinguir «aquí
    no se encadenó a propósito» de «aquí alguien alteró un apunte»: lo segundo
    es una acusación, y desde fuera no hay forma de separarlas si el informe no
    lo dice.
  · **La secuencia no se afloja nunca.** Un borrado dentro de un tramo sin
    cadena lo sigue cazando el hueco en la secuencia, que es la segunda red.
"""

from __future__ import annotations

import os
from typing import Any
from uuid import UUID

import pytest

pytestmark = pytest.mark.db


@pytest.fixture
def auditoria(request: Any) -> Any:
    """`(encendida, con_cadena)`, y lo deja como estaba."""
    from crmcore.config import limpiar_cache_settings

    encendida, cadena = request.param
    previo = {k: os.environ.get(k) for k in ("AUDIT_ENABLED", "AUDIT_HASH_CHAIN")}
    os.environ["AUDIT_ENABLED"] = "true" if encendida else "false"
    os.environ["AUDIT_HASH_CHAIN"] = "true" if cadena else "false"
    limpiar_cache_settings()
    try:
        yield
    finally:
        for k, v in previo.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        limpiar_cache_settings()


def _apuntar(db: Any, n: int = 1) -> None:
    from crmcore.audit import chain

    for i in range(n):
        chain.registrar(db, accion="probar", objeto="cosa", objeto_id=f"c{i}")


def _cuantos(db: Any, tenant_id: UUID) -> int:
    from crmcore.audit.modelos import ApunteAuditoria
    from sqlalchemy import func, select

    return int(
        db.execute(
            select(func.count())
            .select_from(ApunteAuditoria)
            .where(ApunteAuditoria.tenant_id == tenant_id)
        ).scalar_one()
    )


@pytest.mark.parametrize("auditoria", [(True, True)], indirect=True)
def test_encendida_anota(db: Any, tenant_id: UUID, contexto_tenant: UUID, auditoria: Any) -> None:
    antes = _cuantos(db, tenant_id)
    _apuntar(db, 2)
    assert _cuantos(db, tenant_id) == antes + 2


@pytest.mark.parametrize("auditoria", [(False, True)], indirect=True)
def test_apagada_no_anota_nada(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, auditoria: Any
) -> None:
    """El caso entero: hasta hoy esto escribía igual."""
    from crmcore.audit import chain

    antes = _cuantos(db, tenant_id)
    salida = chain.registrar(db, accion="probar", objeto="cosa", objeto_id="x")
    assert salida is None
    assert _cuantos(db, tenant_id) == antes


@pytest.mark.parametrize("auditoria", [(True, False)], indirect=True)
def test_sin_cadena_anota_pero_no_encadena(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, auditoria: Any
) -> None:
    from crmcore.audit import chain

    antes = _cuantos(db, tenant_id)
    _apuntar(db, 2)
    assert _cuantos(db, tenant_id) == antes + 2

    informe = chain.verificar(db, tenant_id)
    # No acusa de manipulación a quien sólo apagó la cadena…
    assert informe["intacta"] is True, informe
    # …pero tampoco deja creer que está encadenada entera.
    assert informe["sin_cadena"] >= 2, informe


@pytest.mark.parametrize("auditoria", [(True, False)], indirect=True)
def test_un_borrado_dentro_del_tramo_sin_cadena_se_sigue_cazando(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, auditoria: Any
) -> None:
    """Es la condición que hace aceptable apagar la cadena. Sin esto, apagarla
    sería abrir una ventana por la que se borra sin dejar rastro."""
    from crmcore.audit import chain
    from crmcore.audit.modelos import ApunteAuditoria
    from sqlalchemy import delete, select

    _apuntar(db, 4)
    db.flush()
    secuencias = sorted(
        db.execute(select(ApunteAuditoria.secuencia).where(ApunteAuditoria.tenant_id == tenant_id))
        .scalars()
        .all()
    )
    assert len(secuencias) >= 4
    db.execute(delete(ApunteAuditoria).where(ApunteAuditoria.secuencia == secuencias[-2]))
    db.flush()

    informe = chain.verificar(db, tenant_id)
    assert informe["intacta"] is False, informe
    assert "borrado" in informe.get("motivo", "")


@pytest.mark.parametrize("auditoria", [(True, True)], indirect=True)
def test_la_cadena_encendida_sigue_cazando_una_alteracion(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, auditoria: Any
) -> None:
    """La comprobación cara sigue estando. Si apagar la cadena hubiera dejado de
    recalcular siempre, encenderla no serviría de nada."""
    from crmcore.audit import chain
    from crmcore.audit.modelos import ApunteAuditoria
    from sqlalchemy import select, update

    _apuntar(db, 2)
    db.flush()
    ultima = db.execute(
        select(ApunteAuditoria.secuencia)
        .where(ApunteAuditoria.tenant_id == tenant_id)
        .order_by(ApunteAuditoria.secuencia.desc())
        .limit(1)
    ).scalar_one()
    db.execute(
        update(ApunteAuditoria)
        .where(ApunteAuditoria.secuencia == ultima)
        .values(motivo="lo he cambiado yo")
    )
    db.flush()

    informe = chain.verificar(db, tenant_id)
    assert informe["intacta"] is False, informe
    assert "alterado" in informe.get("motivo", "")


def test_el_readiness_dice_que_la_auditoria_esta_apagada() -> None:
    """No marca «no listo» —no es una avería— pero no puede ser invisible."""
    import pathlib

    raiz = pathlib.Path(__file__).resolve().parents[2]
    fuente = (raiz / "packages/crmcore/crmcore/service.py").read_text(encoding="utf-8")
    cuerpo = fuente.split("async def ready(")[1].split("\n    @app.")[0]
    assert "audit_enabled" in cuerpo
    assert "AUDIT_HASH_CHAIN" in cuerpo
