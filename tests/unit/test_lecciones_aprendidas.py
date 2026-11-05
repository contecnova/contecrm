"""Lecciones aprendidas de las oportunidades cerradas.

El expediente de una perdida tiene que decir, con su número, en qué se apartó
de las ganadas del mismo embudo; al cerrarla nace una lección obligatoria que
sólo se firma diciendo qué pasó y qué haríamos distinto; y los patrones cuentan
lo firmado.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.authz.principal import Principal
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Prohibido
from sqlalchemy import select

from tests.unit.test_forecast import pipeline, uow  # noqa: F401

pytestmark = pytest.mark.db

# Un contacto que party no deja ver a quien pide el expediente.
OCULTO = UUID("00000000-0000-0000-0000-00000000dead")


@pytest.fixture
def sin_party(monkeypatch: Any) -> list[Any]:
    """La actividad viene de party; aquí se da hecha."""
    from crmcore import ia_ficha

    pedidas: list[Any] = []

    def _leer(ruta: str, principal: Any, parametros: Any = None) -> Any:
        pedidas.append((ruta, parametros))
        if ruta.startswith("/api/v1/contacts/"):
            if ruta.endswith(str(OCULTO)):
                raise Prohibido("No lo puedes ver")
            return {"nombre_completo": "Marta Vidal", "cargo": "Directora financiera"}
        return {
            "items": [
                {
                    "tipo": "llamada",
                    "asunto": "Primera llamada",
                    "inicio_at": "2026-01-05T10:00:00+00:00",
                },
                {"tipo": "reunion", "asunto": "Demo", "inicio_at": "2026-01-20T10:00:00+00:00"},
            ]
        }

    monkeypatch.setattr(ia_ficha, "leer", _leer)
    return pedidas


def _op(db: Any, tenant_id: UUID, pipeline: Any, estado: str, dias: int, **kw: Any) -> Any:  # noqa: F811
    from services.sales.modelos import CambioEtapa, Etapa, Oportunidad

    contacto, negociacion = (
        db.execute(select(Etapa).where(Etapa.pipeline_id == pipeline.id).order_by(Etapa.orden))
        .scalars()
        .all()
    )
    creada = datetime(2026, 1, 1, tzinfo=timezone.utc)
    op = Oportunidad(
        tenant_id=tenant_id,
        nombre=kw.pop("nombre", "Op"),
        pipeline_id=pipeline.id,
        etapa_id=negociacion.id,
        importe=Decimal("10000"),
        estado=estado,
        fecha_cierre_real=(creada + timedelta(days=dias + 5)).date(),
        **kw,
    )
    db.add(op)
    db.flush()
    op.created_at = creada
    fechas = kw.get("_fechas") or [date(2026, 3, 1), date(2026, 3, 1)]
    for i, fecha in enumerate(fechas):
        db.add(
            CambioEtapa(
                tenant_id=tenant_id,
                oportunidad_id=op.id,
                etapa_desde_id=contacto.id if i else None,
                etapa_hasta_id=negociacion.id if i else contacto.id,
                dias_en_etapa=dias if i else None,
                importe_en_cambio=Decimal("10000"),
                fecha_cierre_en_cambio=fecha,
            )
        )
    db.flush()
    return op


def test_el_expediente_dice_en_que_se_aparto_de_las_ganadas(
    db: Any,
    tenant_id: UUID,
    pipeline: Any,  # noqa: F811
    sin_party: list[Any],
    monkeypatch: Any,
) -> None:
    from services.sales import lecciones as lec
    from services.sales.ajustes import ajustes
    from services.sales.modelos import CambioEtapa, CompetidorEnOportunidad

    monkeypatch.setattr(ajustes(), "lecciones_minimo_comparables", 3)
    for _ in range(4):
        _op(db, tenant_id, pipeline, "ganada", dias=10)
    perdida = _op(
        db,
        tenant_id,
        pipeline,
        "perdida",
        dias=40,
        competidor_ganador="Acme",
        motivo_perdida="competencia",
    )
    # La fecha prevista se retrasó dos veces por el camino.
    for fecha in (date(2026, 4, 1), date(2026, 5, 1)):
        db.add(
            CambioEtapa(
                tenant_id=tenant_id,
                oportunidad_id=perdida.id,
                etapa_hasta_id=perdida.etapa_id,
                fecha_cierre_en_cambio=fecha,
            )
        )
    db.add(
        CompetidorEnOportunidad(
            tenant_id=tenant_id, oportunidad_id=perdida.id, nombre="Acme", ganador=True
        )
    )
    db.flush()

    quien = Principal(id=uuid4(), tenant_id=tenant_id, permisos=frozenset({"*:*"}))
    hechos = lec.expediente(db, perdida.id, quien)
    factores = {s["factor"] for s in hechos["senales"]}
    assert "demasiado_tiempo_en_etapa" in factores  # 40 días frente a 10
    assert "fecha_movida" in factores
    assert "competidor" in factores
    assert "sin_decisor" in factores
    assert hechos["comparado_con_las_ganadas"]["ganadas"] == 4
    assert hechos["competencia"][0]["gano"] is True
    # La actividad se pide a party por la oportunidad.
    assert sin_party[0][1]["objeto"] == "oportunidad"
    assert hechos["actividad"]["total"] == 2
    # El día es el de la reunión, no el del alta: party no guarda «realizada».
    assert hechos["actividad"]["ultima"] == "2026-01-20"
    assert hechos["actividad"]["ultimas"][0]["cuando"] == "2026-01-20"


def test_con_pocas_ganadas_no_se_inventa_la_comparacion(
    db: Any,
    tenant_id: UUID,
    pipeline: Any,  # noqa: F811
    sin_party: list[Any],
) -> None:
    from services.sales import lecciones as lec

    perdida = _op(db, tenant_id, pipeline, "perdida", dias=40)
    quien = Principal(id=uuid4(), tenant_id=tenant_id, permisos=frozenset({"*:*"}))
    ref = lec.expediente(db, perdida.id, quien)["comparado_con_las_ganadas"]
    assert ref["comparable"] is False and "hacen falta" in ref["porque"]


def test_al_perder_nace_una_leccion_obligatoria_que_se_firma_entera(
    db: Any,
    tenant_id: UUID,
    pipeline: Any,  # noqa: F811
    sin_party: list[Any],
) -> None:
    from crmcore.errors import ErrorValidacion

    from services.sales import lecciones as lec

    perdida = _op(db, tenant_id, pipeline, "perdida", dias=20, motivo_perdida="precio")
    trabajo = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
    fila = lec.al_cerrar(trabajo, perdida, ganada=False)
    assert fila.obligatoria and fila.estado == "pendiente" and fila.motivo == "precio"
    quien = Principal(id=uuid4(), tenant_id=tenant_id, permisos=frozenset({"*:*"}))
    with pytest.raises(ErrorValidacion):
        lec.firmar(
            trabajo,
            fila.id,
            que_paso="Precio",
            senal_temprana="",
            que_hariamos_distinto="",
            factores=["precio"],
            principal=quien,
        )
    firmada = lec.firmar(
        trabajo,
        fila.id,
        que_paso="Llegamos con un descuento del 20 % en la última semana.",
        senal_temprana="Pidió precio en la primera reunión y no lo dimos.",
        que_hariamos_distinto="Dar una horquilla de precio en la primera reunión.",
        factores=["precio", "descuento_tardio"],
        principal=quien,
    )
    assert firmada.estado == "firmada" and firmada.firmada_por == quien.id
    assert firmada.hechos["oportunidad"]["motivo_perdida"] == "precio"
    patrones = lec.patrones(db, tenant_id)
    assert patrones["firmadas"] == 1 and patrones["factores_en_las_perdidas"]["precio"] == 1
    # La ganada también deja lección, pero no obliga.
    ganada = _op(db, tenant_id, pipeline, "ganada", dias=5)
    assert lec.al_cerrar(trabajo, ganada, ganada=True).obligatoria is False


def test_el_borrador_de_la_ia_se_lee_y_no_inventa_factores() -> None:
    from services.sales import lecciones as lec

    borrador = lec._leer_borrador(
        'Aquí va:\n{"que_paso": "Se perdió por precio", "senal_temprana": "Pidió '
        'precio pronto", "que_hariamos_distinto": "Horquilla al principio", '
        '"factores": ["precio", "astrologia"]}'
    )
    assert borrador["factores"] == ["precio"]
    assert borrador["que_hariamos_distinto"] == "Horquilla al principio"
    assert lec._leer_borrador("texto suelto")["que_paso"] == "texto suelto"


def test_las_cerradas_de_antes_reciben_su_leccion_sin_obligar(
    db: Any,
    tenant_id: UUID,
    pipeline: Any,  # noqa: F811
) -> None:
    from services.sales import lecciones as lec

    perdida = _op(db, tenant_id, pipeline, "perdida", dias=30, motivo_perdida="plazo")
    _op(db, tenant_id, pipeline, "ganada", dias=10)
    _op(db, tenant_id, pipeline, "abierta", dias=10)
    trabajo = UnidadDeTrabajo(db=db, tenant_id=tenant_id)

    assert lec.crear_de_las_cerradas(trabajo)["creadas"] == 2
    # Una segunda vez no crea nada: se puede pedir sin miedo.
    assert lec.crear_de_las_cerradas(trabajo)["creadas"] == 0
    fila = db.execute(
        select(lec.LeccionOportunidad).where(lec.LeccionOportunidad.oportunidad_id == perdida.id)
    ).scalar_one()
    # Histórica: no entra en la lista de deberes.
    assert fila.obligatoria is False and fila.estado == "pendiente"
    # Con la fecha en que se cerró la oportunidad, no la del alta de la lección.
    assert fila.cerrada_el == perdida.fecha_cierre_real and fila.importe == Decimal("10000")
    patrones = lec.patrones(db, tenant_id)
    assert patrones["pendientes_obligatorias"] == 0
    assert (patrones["perdidas"], patrones["ganadas"]) == (1, 1)
    # Lo que no pesa no sale: ninguna ganada firmada, ningún factor de ganadas.
    assert patrones["factores_en_las_ganadas"] == {}


def test_quien_decidia_lleva_su_nombre_y_no_se_inventa_el_que_no_se_ve(
    db: Any,
    tenant_id: UUID,
    pipeline: Any,  # noqa: F811
    sin_party: list[Any],
) -> None:
    from services.sales import lecciones as lec
    from services.sales.ingresos import RolCompra

    perdida = _op(db, tenant_id, pipeline, "perdida", dias=20)
    visible = uuid4()
    for contacto, rol, postura in ((visible, "decisor", -1), (OCULTO, "usuario", 1)):
        db.add(
            RolCompra(
                tenant_id=tenant_id,
                oportunidad_id=perdida.id,
                contacto_id=contacto,
                rol=rol,
                postura=postura,
                motivo="Prefiere al de siempre" if postura < 0 else "",
            )
        )
    db.flush()
    quien = Principal(id=uuid4(), tenant_id=tenant_id, permisos=frozenset({"*:*"}))
    decisores = {d["rol"]: d for d in lec.expediente(db, perdida.id, quien)["decisores"]}
    assert decisores["decisor"]["nombre"] == "Marta Vidal"
    assert decisores["decisor"]["cargo"] == "Directora financiera"
    assert decisores["decisor"]["postura"] == -1
    assert decisores["usuario"]["nombre"] is None
    senal = next(
        s
        for s in lec.expediente(db, perdida.id, quien)["senales"]
        if s["factor"] == "decisor_en_contra"
    )
    assert senal["texto"] == "En contra: Marta Vidal (decisor): Prefiere al de siempre."


def test_party_filtra_las_actividades_por_el_objeto_al_que_cuelgan(
    db: Any, tenant_id: UUID, monkeypatch: Any
) -> None:
    """El expediente pide las de la oportunidad; sin el filtro le llegaban todas."""
    from crmcore.config import limpiar_cache_settings
    from crmcore.http.deps import get_db
    from fastapi.testclient import TestClient

    from services.party.modelos import Actividad
    from tests.unit.test_los_listados_saben_contar import _app, _cabeceras

    oportunidad = uuid4()
    db.add(
        Actividad(
            tenant_id=tenant_id,
            tipo="llamada",
            asunto="de la oportunidad",
            objeto="oportunidad",
            objeto_id=oportunidad,
        )
    )
    db.add(
        Actividad(
            tenant_id=tenant_id,
            tipo="llamada",
            asunto="de otra",
            objeto="oportunidad",
            objeto_id=uuid4(),
        )
    )
    db.add(Actividad(tenant_id=tenant_id, tipo="nota", asunto="de la cuenta", cuenta_id=uuid4()))
    db.flush()
    app = _app("party")
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as cliente:
            r = cliente.get(
                f"/api/v1/activities?objeto=oportunidad&objeto_id={oportunidad}",
                headers=_cabeceras(tenant_id),
            )
    finally:
        app.dependency_overrides.clear()
        limpiar_cache_settings()
    assert r.status_code == 200, r.text
    assert [a["asunto"] for a in r.json()["items"]] == ["de la oportunidad"]
