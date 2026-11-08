"""Lo que las lecciones firmadas le dicen a las oportunidades abiertas.

Los consejos traen las del mismo cliente y las parecidas por significado, sin
repetir y sin la propia; lo que la IA no puede atribuir a una lección se
descarta; los avisos sólo salen cuando hay algo que decir y no se repiten; el
resumen sale una vez por periodo y va a quien dirige. Y dónde empieza una
señal es un ajuste en caliente, no un número en el código.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.authz.principal import Principal
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import ErrorDependencia
from sqlalchemy import select

from tests.unit.test_forecast import pipeline, uow  # noqa: F401
from tests.unit.test_lecciones_aprendidas import _op

pytestmark = pytest.mark.db


def _leccion(
    db: Any,
    tenant_id: UUID,
    op: Any,
    *,
    resultado: str = "perdida",
    estado: str = "firmada",
    perdida_en: str | None = None,
    factores: list[str] | None = None,
    responsable: UUID | None = None,
) -> Any:
    from services.sales.lecciones import LeccionOportunidad

    fila = LeccionOportunidad(
        tenant_id=tenant_id,
        oportunidad_id=op.id,
        cuenta_id=op.cuenta_id,
        titulo=op.nombre,
        resultado=resultado,
        estado=estado,
        obligatoria=resultado == "perdida",
        que_paso="Se perdió por precio",
        que_hariamos_distinto="Dar la horquilla de precio en la primera reunión",
        factores=factores or ["precio"],
        hechos={"recorrido": [{"desde": perdida_en, "hasta": "Perdida"}]} if perdida_en else {},
        cerrada_el=date(2026, 10, 1),
        firmada_at=datetime(2026, 11, 3, tzinfo=timezone.utc) if estado == "firmada" else None,
        responsable_id=responsable,
    )
    db.add(fila)
    db.flush()
    return fila


@pytest.fixture
def indice(monkeypatch: Any) -> dict[str, Any]:
    """intelligence, dado: lo que devuelva el índice lo dice cada prueba."""
    from crmcore import ia_ficha

    estado: dict[str, Any] = {"items": [], "fallo": None, "pedidas": []}

    def _pedir(ruta: str, cuerpo: Any, principal: Any) -> Any:
        estado["pedidas"].append((ruta, cuerpo))
        if estado["fallo"]:
            raise estado["fallo"]
        return {"items": estado["items"]}

    monkeypatch.setattr(ia_ficha, "pedir", _pedir)
    return estado


def test_trae_las_del_mismo_cliente_y_las_parecidas_sin_repetir(
    db: Any,
    tenant_id: UUID,
    pipeline: Any,  # noqa: F811
    indice: dict[str, Any],
) -> None:
    from services.sales import consejos

    cliente, otro = uuid4(), uuid4()
    del_cliente = [
        _leccion(db, tenant_id, _op(db, tenant_id, pipeline, "perdida", 10, cuenta_id=cliente))
        for _ in range(2)
    ]
    # Una sin firmar del mismo cliente: no se ha escrito, no aconseja nada.
    _leccion(
        db,
        tenant_id,
        _op(db, tenant_id, pipeline, "perdida", 10, cuenta_id=cliente),
        estado="pendiente",
    )
    parecida = _leccion(
        db,
        tenant_id,
        _op(db, tenant_id, pipeline, "ganada", 10, cuenta_id=otro),
        resultado="ganada",
    )
    lejana = _leccion(db, tenant_id, _op(db, tenant_id, pipeline, "perdida", 10, cuenta_id=otro))
    abierta = _op(db, tenant_id, pipeline, "abierta", 10, cuenta_id=cliente)
    indice["items"] = [
        # Ya está como «del mismo cliente»: no se repite como parecida.
        {"referencia": str(del_cliente[0].id), "parecido": 0.97},
        {"referencia": str(parecida.id), "parecido": 0.91},
        # Por debajo del umbral: el índice siempre devuelve algo, y algo que no
        # se parece no es un consejo.
        {"referencia": str(lejana.id), "parecido": 0.40},
    ]
    quien = Principal(id=uuid4(), tenant_id=tenant_id, permisos=frozenset({"*:*"}))
    salida = consejos.consejos(db, abierta.id, quien)

    assert {c["id"] for c in salida["mismo_cliente"]} == {str(f.id) for f in del_cliente}
    assert [c["id"] for c in salida["parecidas"]] == [str(parecida.id)]
    assert salida["parecidas"][0]["parecido"] == 0.91
    assert salida["busqueda_por_significado"]["usada"] is True
    # Se pregunta sólo por lecciones.
    assert indice["pedidas"][0][1]["fuentes"] == ["leccion"]


def test_sin_indice_lo_dice_y_sigue_con_las_del_cliente(
    db: Any,
    tenant_id: UUID,
    pipeline: Any,  # noqa: F811
    indice: dict[str, Any],
) -> None:
    from services.sales import consejos

    cliente = uuid4()
    _leccion(db, tenant_id, _op(db, tenant_id, pipeline, "perdida", 10, cuenta_id=cliente))
    abierta = _op(db, tenant_id, pipeline, "abierta", 10, cuenta_id=cliente)
    indice["fallo"] = ErrorDependencia("intelligence no contesta", error_code="x.caido")
    quien = Principal(id=uuid4(), tenant_id=tenant_id, permisos=frozenset({"*:*"}))
    salida = consejos.consejos(db, abierta.id, quien)
    assert len(salida["mismo_cliente"]) == 1
    assert salida["parecidas"] == []
    assert salida["busqueda_por_significado"]["usada"] is False
    assert "no contesta" in salida["busqueda_por_significado"]["porque"]


def test_un_consejo_que_no_sale_de_ninguna_leccion_se_descarta() -> None:
    from services.sales.consejos import leer_consejos

    buenos, descartados = leer_consejos(
        'Aquí están: [{"tipo": "haz", "texto": "Horquilla pronto", "leccion_id": "a"},'
        '{"tipo": "no_hagas", "texto": "Descontar al final", "leccion_id": "z"},'
        '{"tipo": "quizas", "texto": "Algo", "leccion_id": "a"}]',
        {"a"},
    )
    assert buenos == [{"tipo": "haz", "texto": "Horquilla pronto", "leccion_id": "a"}]
    assert descartados == 2


def test_sin_lecciones_no_se_llama_a_la_ia(
    db: Any,
    tenant_id: UUID,
    pipeline: Any,  # noqa: F811
    indice: dict[str, Any],
) -> None:
    from services.sales import consejos

    abierta = _op(db, tenant_id, pipeline, "abierta", 10, cuenta_id=uuid4())
    quien = Principal(id=uuid4(), tenant_id=tenant_id, permisos=frozenset({"*:*"}))
    salida = consejos.consejos_ia(db, abierta.id, quien)
    assert salida["consejos"] == [] and "Ninguna" in salida["porque"]
    assert all(ruta != "/api/v1/ia/generar" for ruta, _ in indice["pedidas"])


def test_al_entrar_en_una_etapa_avisa_de_lo_que_se_perdio_en_ella_una_vez(
    db: Any,
    tenant_id: UUID,
    pipeline: Any,  # noqa: F811
) -> None:
    from services.sales import consejos

    for factores in (["precio"], ["precio", "competidor"]):
        _leccion(
            db,
            tenant_id,
            _op(db, tenant_id, pipeline, "perdida", 10, cuenta_id=uuid4()),
            perdida_en="Negociación",
            factores=factores,
        )
    abierta = _op(db, tenant_id, pipeline, "abierta", 10, cuenta_id=uuid4())
    trabajo = UnidadDeTrabajo(db=db, tenant_id=tenant_id)

    aviso = consejos.avisar_en(trabajo, abierta, "etapa", clave="e1", etapa="Negociación")
    assert aviso is not None
    assert "se han perdido 2" in aviso.detalle and "precio" in aviso.detalle
    assert len(aviso.lecciones) == 2
    emitidos = [e for e in trabajo._pendientes if e["tipo"] == "opportunity.lesson.advice"]
    assert len(emitidos) == 1
    # Volver a entrar no duplica el aviso: lo actualiza.
    consejos.avisar_en(trabajo, abierta, "etapa", clave="e1", etapa="Negociación")
    assert len(consejos.avisos_de(db, abierta.id)) == 1
    # Y donde no hay nada que decir, no hay aviso.
    assert consejos.avisar_en(trabajo, abierta, "etapa", clave="e2", etapa="Cualificación") is None


def test_el_resumen_sale_una_vez_por_periodo_y_va_a_quien_dirige(
    db: Any,
    tenant_id: UUID,
    pipeline: Any,  # noqa: F811
) -> None:
    from crmcore.authz.jerarquia import MandoReplicado

    from services.sales import consejos

    comercial, jefa = uuid4(), uuid4()
    db.add(MandoReplicado(tenant_id=tenant_id, usuario_id=comercial, superior_id=jefa))
    _leccion(
        db,
        tenant_id,
        _op(db, tenant_id, pipeline, "perdida", 10),
        estado="pendiente",
        responsable=comercial,
    )
    trabajo = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
    hoy = date(2026, 11, 8)

    fila = consejos.resumen(trabajo, hoy=hoy)
    assert fila is not None
    assert fila.destinatarios == [str(jefa)]
    assert fila.datos["pendientes_obligatorias"] == 1
    # El mismo día no se repite, ni pidiéndolo.
    assert consejos.resumen(trabajo, hoy=hoy) is None
    assert consejos.resumen(trabajo, hoy=hoy, forzar=True) is None
    # Al día siguiente sólo si se fuerza: el periodo no ha pasado.
    assert consejos.resumen(trabajo, hoy=date(2026, 11, 9)) is None
    assert consejos.resumen(trabajo, hoy=date(2026, 11, 9), forzar=True) is not None
    total = db.execute(
        select(consejos.ResumenLecciones).where(consejos.ResumenLecciones.tenant_id == tenant_id)
    ).all()
    assert len(total) == 2


def test_donde_empieza_una_senal_es_un_ajuste_en_caliente(
    db: Any,
    tenant_id: UUID,
    pipeline: Any,  # noqa: F811
    monkeypatch: Any,
) -> None:
    """40 días frente a 10 es «tardar demasiado» con el doble; con diez veces, no."""
    from crmcore import ia_ficha
    from crmcore.runtime.settings import fijar, invalidar
    from crmcore.tenancy.context import con_contexto

    from services.sales import lecciones as lec

    # `fijar` audita, y un apunte de auditoría necesita su tenant.
    with con_contexto(tenant_id=tenant_id, origen="prueba"):
        monkeypatch.setattr(ia_ficha, "leer", lambda *a, **k: {"items": []})
        fijar(db, "lecciones_minimo_comparables", 3, ambito_id=str(tenant_id))
        for _ in range(4):
            _op(db, tenant_id, pipeline, "ganada", dias=10)
        perdida = _op(db, tenant_id, pipeline, "perdida", dias=40)
        quien = Principal(id=uuid4(), tenant_id=tenant_id, permisos=frozenset({"*:*"}))

        def _factores() -> set[str]:
            invalidar()
            return {s["factor"] for s in lec.expediente(db, perdida.id, quien)["senales"]}

        assert "demasiado_tiempo_en_etapa" in _factores()
        fijar(db, "lecciones_factor_lento", 10.0, ambito_id=str(tenant_id))
        assert "demasiado_tiempo_en_etapa" not in _factores()
        # Y el expediente dice con qué regla se calculó.
        assert lec.expediente(db, perdida.id, quien)["umbrales"]["factor_lento"] == 10.0
