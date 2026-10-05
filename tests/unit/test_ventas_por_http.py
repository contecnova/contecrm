"""Las puertas de ventas que no existían, EJERCITADAS por HTTP
(CRM-03.01.01.11, CRM-03.01.02.05, CRM-03.04.01.05, CRM-09.01.01.07,
CRM-09.01.01.09, CRM-09.02.01).

Diez decisiones de `sales` estaban escritas, probadas y sin llamante. Dos de
ellas no eran «una ruta que falta» sino un circuito abierto:

**La calibración no podía funcionar nunca.** La columna `resultado` de una
revisión llevaba desde el primer día el comentario «para poder compararlo con lo
que pasó» y **no la escribía nadie**: todas las revisiones se quedaban con el
resultado vacío, la calibración las descartaba y contestaba «no hay suficientes
para concluir». Una respuesta razonable que habría seguido saliendo con diez años
de revisiones dentro.

**El margen por línea no se miraba.** `margen_de_oferta` sumaba el total y
`margen_de_linea` —que dice si una línea se vende por debajo de coste— no la
llamaba nadie. Un total sano tapa una línea en pérdidas, la aprobación sale por
el total, y lo que se descubre después es que el producto que más se vende pierde
dinero en cada unidad.

Y el módulo del contrato con el proveedor **no tenía ninguna puerta**: tres
funciones completas que no podía pedir nadie.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from starlette.testclient import TestClient

pytestmark = pytest.mark.db

HOY = date(2026, 10, 5)


@pytest.fixture
def cliente() -> Any:
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
            # Segundo factor recién superado. Va firmado con lo demás: las
            # operaciones sensibles —exportar en masa, borrar en bloque,
            # restaurar— lo exigen, y sin él una persona de verdad vería un
            # «vuelve a verificarte» en vez de la respuesta.
            H_FACTOR_FUERTE: datetime.now(timezone.utc).isoformat(),
        },
        get_settings().secret_key.get_secret_value(),
    )


# ── Crecimiento real (CRM-03.01.01.11) ────────────────────────────────────


def test_las_renovaciones_no_son_crecimiento(cliente: Any, cabeceras: dict[str, str]) -> None:
    """Sumarlas hace que un año plano parezca bueno hasta que alguien cruza con
    facturación."""
    r = cliente.post(
        "/api/v1/ingresos/crecimiento",
        headers=cabeceras,
        json={
            "cerradas": [
                {"importe": "100", "relacion": "nueva"},
                {"importe": "300", "relacion": "renovacion"},
            ]
        },
    )
    assert r.status_code == 200, r.text
    salida = r.json()
    assert salida["ingreso_nuevo"] == "100"
    assert salida["ingreso_mantenido"] == "300"
    assert salida["total_cerrado"] == "400"
    # Y el 25 % es el número que contesta a «¿vamos bien?», no el 400.
    assert salida["pct_que_es_crecimiento"] == 25.0


# ── Margen por línea (CRM-09.02.01) ───────────────────────────────────────


def test_una_linea_en_perdidas_no_la_tapa_el_total(cliente: Any, cabeceras: dict[str, str]) -> None:
    """El total sale sano y dentro hay un producto que pierde dinero por unidad."""
    r = cliente.post(
        "/api/v1/coste/margen",
        headers=cabeceras,
        json={
            "lineas": [
                {"referencia": "buena", "precio_venta": "1000", "coste": "400", "cantidad": "1"},
                {"referencia": "mala", "precio_venta": "10", "coste": "40", "cantidad": "5"},
            ]
        },
    )
    assert r.status_code == 200, r.text
    salida = r.json()
    # El margen global es estupendo...
    assert float(salida["margen_pct"]) > 30
    # ...y aun así se nombra la línea que pierde dinero.
    assert [x["referencia"] for x in salida["lineas_en_perdidas"]] == ["mala"]
    assert salida["lineas_en_perdidas"][0]["margen"] == "-150"
    assert "por debajo de coste" in salida["aviso_lineas_en_perdidas"]


def test_sin_lineas_en_perdidas_no_se_avisa_de_nada(
    cliente: Any, cabeceras: dict[str, str]
) -> None:
    """Un aviso que sale siempre deja de leerse."""
    r = cliente.post(
        "/api/v1/coste/margen",
        headers=cabeceras,
        json={"lineas": [{"referencia": "a", "precio_venta": "100", "coste": "40"}]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["lineas_en_perdidas"] == []
    assert r.json()["aviso_lineas_en_perdidas"] == ""


# ── Respuestas de los proveedores (CRM-09.02.01) ──────────────────────────


def test_se_dice_quien_no_ha_contestado(cliente: Any, cabeceras: dict[str, str], db: Any) -> None:
    """Si tres de cinco no contestan, no se ha comparado el mercado: se ha
    comparado lo que llegó."""
    pedidas = [str(uuid4()) for _ in range(5)]
    r = cliente.post(
        "/api/v1/coste/respuestas",
        headers=cabeceras,
        json={
            "pedidas_a": pedidas,
            "respuestas": [{"proveedor_id": pedidas[0]}, {"proveedor_id": pedidas[1]}],
            "fecha_limite": HOY.isoformat(),
        },
    )
    assert r.status_code == 200, r.text
    salida = r.json()
    assert sorted(salida["sin_contestar"]) == sorted(pedidas[2:])
    assert "es entre las que hay" in salida["que_significa"]


# ── Plan conjunto: estado y calibración (CRM-03.01.02.05) ─────────────────


def _plan(cliente: Any, cabeceras: dict[str, str], pasos: list[dict[str, Any]]) -> dict[str, Any]:
    r = cliente.post(
        "/api/v1/planes-conjuntos",
        headers=cabeceras,
        json={"oportunidad_id": str(uuid4()), "pasos": pasos},
    )
    assert r.status_code == 201, r.text
    return dict(r.json())


def test_el_estado_distingue_de_quien_es_el_retraso(
    cliente: Any, cabeceras: dict[str, str], db: Any
) -> None:
    """Si lo que se retrasa es del cliente, la fecha de cierre del CRM es una
    ilusión — y eso es lo que hay que contar antes del cierre de trimestre."""
    ayer = (HOY - timedelta(days=30)).isoformat()
    plan = _plan(
        cliente,
        cabeceras,
        [
            {
                "titulo": "Mandar la propuesta",
                "fecha": ayer,
                "de_quien": "nuestro",
                "responsable": "Ana",
            },
            {
                "titulo": "Aprobar presupuesto",
                "fecha": ayer,
                "de_quien": "del_cliente",
                "responsable": "El cliente",
            },
            {
                "titulo": "Revisar el pliego",
                "fecha": ayer,
                "de_quien": "conjunto",
                "responsable": "Los dos",
            },
            {
                "titulo": "Firmar",
                "fecha": (HOY + timedelta(days=30)).isoformat(),
                "de_quien": "del_cliente",
                "responsable": "El cliente",
            },
        ],
    )
    r = cliente.get(f"/api/v1/planes-conjuntos/{plan['id']}/estado", headers=cabeceras)
    assert r.status_code == 200, r.text
    salida = r.json()
    assert salida["retrasados_nuestros"] == ["Mandar la propuesta"]
    assert salida["retrasados_del_cliente"] == ["Aprobar presupuesto"]
    assert salida["retrasados_conjuntos"] == ["Revisar el pliego"]
    # Y con pasos ajenos retrasados, la fecha del CRM no es creíble.
    assert salida["la_fecha_es_creible"] is False
    # Y no se mezclan en un único «hay 2 pasos retrasados», que no permite
    # decidir si se aprieta dentro o se llama al cliente.
    assert salida["pasos"] == 4


def test_el_plan_de_otro_tenant_no_se_lee(cliente: Any, cabeceras: dict[str, str], db: Any) -> None:
    r = cliente.get(f"/api/v1/planes-conjuntos/{uuid4()}/estado", headers=cabeceras)
    assert r.status_code == 404, r.text


def test_la_calibracion_necesita_que_alguien_anote_como_acabo(
    cliente: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID
) -> None:
    """El circuito que estaba abierto.

    Se guardan veinte revisiones declaradas al 85 % y se cierran la mitad como
    ganadas. Si el resultado no se anotara al cerrar —que es lo que pasaba—, la
    calibración contestaría «no hay suficientes» con el archivo lleno.
    """
    from crmcore.db.uow import UnidadDeTrabajo

    from services.sales import plan_conjunto as pc

    uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
    respuestas = {
        "que_puede_salir_mal": "Que el presupuesto se caiga",
        "que_falta_por_saber": "Quién firma",
    }
    for i in range(20):
        oportunidad_id = uuid4()
        pc.revisar(
            uow,
            oportunidad_id=oportunidad_id,
            respuestas=respuestas,
            probabilidad_declarada=85,
            fecha_declarada=HOY,
            acuerdos=[],
            revisada_por=uuid4(),
        )
        # Lo que hace `_cerrar` al cerrar la oportunidad.
        assert pc.anotar_resultado(uow, oportunidad_id, ganada=bool(i % 2)) == 1
    db.flush()

    r = cliente.get("/api/v1/planes-conjuntos/calibracion", headers=cabeceras)
    assert r.status_code == 200, r.text
    salida = r.json()
    assert salida["medible"] is True
    assert salida["cerradas"] == 20
    # Un 85 % que se gana la mitad de las veces no significa 85 %.
    assert salida["tramos_desviados"]


# ── Turno de equipo en la agenda (CRM-03.01.01.07) ────────────────────────


def test_el_turno_va_por_quien_lleva_mas_tiempo_sin_recibir_una(
    cliente: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID
) -> None:
    """Por orden alfabético o por identificador sale siempre el mismo, y el
    reparto deja de repartir."""
    from services.sales import cadencias as cad

    tramos = {str(d): [["09:00", "13:00"]] for d in range(5)}
    uno, dos = uuid4(), uuid4()
    for usuario_id in (uno, dos):
        db.add(
            cad.DisponibilidadAgenda(
                tenant_id=tenant_id,
                usuario_id=usuario_id,
                tramos=tramos,
                equipo="preventa",
                activa=True,
            )
        )
    db.flush()

    primero = cliente.post("/api/v1/agenda/turno", headers=cabeceras, json={"equipo": "preventa"})
    assert primero.status_code == 200, primero.text
    segundo = cliente.post("/api/v1/agenda/turno", headers=cabeceras, json={"equipo": "preventa"})
    assert segundo.status_code == 200, segundo.text

    # Dos vueltas, dos personas distintas: eso es repartir.
    assert primero.json()["usuario_id"] != segundo.json()["usuario_id"]
    assert {primero.json()["usuario_id"], segundo.json()["usuario_id"]} == {str(uno), str(dos)}
    assert primero.json()["turno_consumido"] is True


def test_un_equipo_sin_nadie_disponible_lo_dice(
    cliente: Any, cabeceras: dict[str, str], db: Any
) -> None:
    """Repartir entre cero personas no falla: deja la reunión sin proponer."""
    r = cliente.post("/api/v1/agenda/turno", headers=cabeceras, json={"equipo": "fantasma"})
    assert r.status_code == 404, r.text
    assert r.json()["error_code"] == "agenda.equipo_sin_disponibilidad"


# ── Descuento del partner (CRM-03.04.01.05) ───────────────────────────────


def test_sin_coste_el_margen_no_se_da_por_bueno(
    cliente: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID
) -> None:
    """Un «sin problemas» que significa «no lo sé» es lo que hace que se firme un
    precio que pierde dinero."""
    from crmcore.db.uow import UnidadDeTrabajo

    from services.sales import partners as prt

    uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
    nivel = prt.crear_nivel(uow, clave="plata", nombre="Plata", descuento_extra_pct=0)
    partner = prt.crear_partner(
        uow,
        clave="revende",
        nombre="Revende SL",
        tipo="revendedor",
        nivel_id=nivel.id,
        canal="partner",
    )
    db.flush()

    r = cliente.post(
        f"/api/v1/partners/{partner.id}/descuento",
        headers=cabeceras,
        json={"precio_lista": "1000", "precio_ofertado": "900"},
    )
    assert r.status_code == 200, r.text
    salida = r.json()
    assert salida["descuento_pct"] == "10.00"
    assert salida["margen_medido"] is False
    assert salida["margen_pct"] is None


# ── Contrato y alcance del proveedor (CRM-09.01.01.07, .09) ───────────────


def test_el_contrato_avisa_por_lo_vendido_y_no_por_su_fecha(
    cliente: Any, cabeceras: dict[str, str], db: Any
) -> None:
    """Los compromisos más allá del fin del contrato son los que se quedan sin
    nadie detrás."""
    fin = date.today() + timedelta(days=60)
    r = cliente.post(
        "/api/v1/proveedores-comerciales/contrato",
        headers=cabeceras,
        json={
            "vigente_hasta": fin.isoformat(),
            "renovacion_automatica": False,
            "dias_preaviso": 30,
            "compromisos_con_clientes": [
                {"referencia": "OP-1", "fecha": (fin + timedelta(days=15)).isoformat()},
                {"referencia": "OP-2", "fecha": (fin - timedelta(days=15)).isoformat()},
            ],
        },
    )
    assert r.status_code == 200, r.text
    salida = r.json()
    assert [c["referencia"] for c in salida["compromisos_sin_cobertura"]] == ["OP-1"]
    assert salida["estado"] == "vigente"


def test_un_contrato_sin_fecha_de_fin_no_es_indefinido(
    cliente: Any, cabeceras: dict[str, str], db: Any
) -> None:
    r = cliente.post(
        "/api/v1/proveedores-comerciales/contrato",
        headers=cabeceras,
        json={"vigente_hasta": None, "renovacion_automatica": True, "dias_preaviso": 30},
    )
    assert r.status_code == 200, r.text
    salida = r.json()
    assert salida["estado"] == "sin_vigencia_declarada"
    assert salida["fiable"] is False


def test_el_alcance_se_declara_en_positivo(cliente: Any, cabeceras: dict[str, str]) -> None:
    """Lo que no está declarado no se puede comprometer."""
    r = cliente.post(
        "/api/v1/proveedores-comerciales/alcance",
        headers=cabeceras,
        json={"alcance": {"geografia": ["peninsula"], "categoria": []}},
    )
    assert r.status_code == 200, r.text
    salida = r.json()
    assert salida["alcance"] == {"geografia": ["peninsula"]}
    # Un eje vacío significa «cualquiera», y eso conviene que sea deliberado.
    assert set(salida["ejes_sin_acotar"]) == {"categoria", "cliente", "canal"}

    malo = cliente.post(
        "/api/v1/proveedores-comerciales/alcance",
        headers=cabeceras,
        json={"alcance": {"sector": ["banca"]}},
    )
    assert malo.status_code == 422, malo.text
    assert malo.json()["error_code"] == "proveedor.eje_invalido"


def test_el_porque_no_es_lo_que_hace_util_la_respuesta(
    cliente: Any, cabeceras: dict[str, str]
) -> None:
    """Por la zona se busca otro proveedor; por el tipo de trabajo se cambia lo
    que se ofrece. Son dos tardes distintas."""
    r = cliente.post(
        "/api/v1/proveedores-comerciales/puede-servir?categoria=obra&geografia=canarias",
        headers=cabeceras,
        json={"alcance": {"categoria": ["obra"], "geografia": ["peninsula"]}},
    )
    assert r.status_code == 200, r.text
    salida = r.json()
    assert salida["puede"] is False
    assert len(salida["motivos"]) == 1
    assert "canarias" in salida["motivos"][0]
