"""Modelos entrenados con el histórico, el asistente que actúa y las preguntas
que se ejecutan (CRM-02.01.02.02, CRM-05.02.01.02, CRM-05.02.01.03,
CRM-02.01.01.08, CRM-04.03.02.02, CRM-05.02.02.04).

Lo que había hasta el 09-11-2026 simulaba: pesos tecleados, una sigmoide sobre
rasgos tecleados, un plan sin ejecutar y acciones que no se hacían. Estas
pruebas fijan lo que lo hace real:

  * se aprende del histórico leído por la API, y lo que se aprende se nota
    (una señal fuerte da AUC alto; ruido no se publica);
  * los rasgos de una oportunidad no miran el futuro;
  * con pocos datos no se entrena, y se dice;
  * se puntúa un registro por su id, con sus factores, y se guarda;
  * el segmento sale en marketing con los elegidos y se congela;
  * la pregunta a los datos se ejecuta contra el listado, sin texto libre, y
    devuelve la consulta;
  * la acción del asistente es de la lista cerrada, la confirma quien
    preguntó, y se ejecuta una vez.

El CRM de verdad se sustituye por un doble del lector HTTP: lo que se prueba es
qué se le pide y qué se hace con lo que devuelve.
"""

from __future__ import annotations

import math
import random
from datetime import date, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.authz.principal import Principal
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, Prohibido
from sqlalchemy import select

from services.intelligence import acciones_asistente as acc
from services.intelligence import asistencia as asis
from services.intelligence import consulta_natural as cn
from services.intelligence import gobierno as gob
from services.intelligence import predictivo as pre
from services.intelligence import rag as rag_mod
from services.intelligence.prediccion import Prediccion
from tests.unit.test_ia_generativa import (  # noqa: F401
    _proveedor,
    puerto_de_mentira,
    uow,
)

HOY = date.today()


def _historico(semilla: int = 1, *, senal: bool = True, n: int = 500) -> list[dict[str, Any]]:
    """Oportunidades cerradas de dos años y unas abiertas.

    Con `senal`, el embudo «Industria» gana el 80 % y «Retail» el 20 %, y lo
    caro tarda más: es lo que un modelo de verdad tiene que encontrar.
    """
    azar = random.Random(semilla)
    cuentas = [str(uuid4()) for _ in range(40)]
    filas = []
    for i in range(n):
        creada = HOY - timedelta(days=730 - i * 700 // n)
        embudo = "Industria" if azar.random() < 0.5 else "Retail"
        p = (0.8 if embudo == "Industria" else 0.2) if senal else 0.5
        gana = azar.random() < p
        importe = azar.choice([10_000, 30_000, 90_000])
        dias = int(importe / 1000 + azar.randint(0, 10)) if senal else azar.randint(10, 100)
        cierre = creada + timedelta(days=dias)
        abierta = cierre > HOY
        filas.append(
            {
                "id": str(uuid4()),
                "cuenta_id": azar.choice(cuentas),
                "owner_id": None,
                "pipeline": embudo,
                "importe": str(importe),
                "estado": "abierta" if abierta else ("ganada" if gana else "perdida"),
                "estado_significa": "abierto" if abierta else ("ganado" if gana else "perdido"),
                "created_at": f"{creada.isoformat()}T10:00:00+01:00",
                "fecha_cierre_real": None if abierta else cierre.isoformat(),
                "contacto_id": None,
                "lead_id": None,
            }
        )
    return filas


def _lector(oportunidades: list[dict[str, Any]], leads: list[dict[str, Any]] | None = None):
    pedidas: list[tuple[str, str, dict[str, Any]]] = []

    def leer(*, metodo: str, ruta: str, parametros: dict[str, Any] | None = None, cuerpo=None, **_):
        pedidas.append((metodo, ruta, dict(parametros or cuerpo or {})))
        if ruta == "/api/v1/opportunities":
            filas = oportunidades
            if (parametros or {}).get("cuenta_id"):
                filas = [o for o in filas if o["cuenta_id"] == parametros["cuenta_id"]]
            return {"estado": 200, "datos": {"items": filas, "hay_mas": False}}
        if ruta.startswith("/api/v1/opportunities/") and ruta.endswith("/lineas"):
            return {"estado": 200, "datos": []}
        if ruta.startswith("/api/v1/opportunities/"):
            uno = next((o for o in oportunidades if o["id"] == ruta.rsplit("/", 1)[1]), None)
            return {"estado": 200, "datos": uno} if uno else {"estado": 404, "datos": {}}
        if ruta == "/api/v1/leads":
            return {"estado": 200, "datos": {"items": leads or [], "hay_mas": False}}
        if ruta == "/api/v1/segmentos":
            return {"estado": 201, "datos": {"id": "seg-1"}}
        if ruta.endswith("/congelar"):
            return {"estado": 200, "datos": {"miembros": 3}}
        return {"estado": 404, "datos": {}}

    pre.registrar_lector(leer)
    return pedidas


@pytest.fixture(autouse=True)
def _sin_dobles():
    yield
    pre.registrar_lector(None)
    cn.registrar_lector(None)
    acc.registrar_proponedor(None)
    acc.registrar_ejecutor(None)


def _quien(*permisos: str, tenant_id: UUID | None = None) -> Principal:
    return Principal(id=uuid4(), tenant_id=tenant_id, permisos=frozenset(permisos))


# ── Matemáticas ─────────────────────────────────────────────────────────────


def test_la_logistica_encuentra_la_senal_y_el_auc_la_mide() -> None:
    azar = random.Random(3)
    x = [[azar.gauss(0, 1), azar.gauss(0, 1)] for _ in range(800)]
    y = [1 if azar.random() < pre._sigmoide(2 * a - b) else 0 for a, b in x]
    w, _ = pre.ajustar_logistica(x, y, l2=1.0, iteraciones=25)
    assert w[0] > 1.0 and w[1] < -0.5
    assert pre.auc([1, 2, 3, 4], [0, 0, 1, 1]) == 1.0
    # Empates: medio punto, no un acierto inventado.
    assert pre.auc([1, 1, 1, 1], [0, 1, 0, 1]) == 0.5
    # Una sola clase no se puede medir: None, no 0,5.
    assert pre.auc([0.2, 0.9], [1, 1]) is None


def test_la_lineal_recupera_pendiente_y_sesgo() -> None:
    azar = random.Random(4)
    x = [[azar.gauss(0, 1)] for _ in range(300)]
    w, b = pre.ajustar_lineal(x, [3 * v[0] + 2 for v in x], l2=0.0)
    assert abs(w[0] - 3) < 1e-6 and abs(b - 2) < 1e-6


def test_los_rasgos_de_una_oportunidad_no_miran_el_futuro() -> None:
    """Lo que la cuenta ganó DESPUÉS de abrir esta oportunidad no cuenta."""
    cuenta = str(uuid4())
    antes = {
        "id": "a",
        "cuenta_id": cuenta,
        "estado_significa": "ganado",
        "importe": "100",
        "created_at": "2025-01-01",
        "fecha_cierre_real": "2025-02-01",
    }
    despues = {**antes, "id": "b", "created_at": "2025-06-01", "fecha_cierre_real": "2025-08-01"}
    esta = {**antes, "id": "c", "created_at": "2025-03-01", "estado_significa": "abierto"}
    r = pre.rasgos_oportunidad(esta, pre.Historial([antes, despues, esta]))
    assert r["cuenta_ganadas_previas"] == 1


# ── Entrenar ────────────────────────────────────────────────────────────────


def test_con_senal_se_publica_y_sin_ella_no(uow: UnidadDeTrabajo) -> None:  # noqa: F811
    pedidas = _lector(_historico(senal=True))
    r = pre.entrenar(uow, tipo="cierre", usuario_id=uuid4())
    assert r["entrenado"] and r["publicado"], r
    assert r["metricas"]["auc"] > 0.7
    # Lo leído es TODO el histórico, no sólo lo abierto que el listado da por
    # defecto: sin `estado=""` se aprendería de cero cerradas.
    assert pedidas[0][2].get("estado") == ""
    activo = gob.activo(uow.db, uow.tenant_id, "cierre")
    assert activo is not None and activo.definicion["origen"] == "historico"
    assert "embudo=Industria" in activo.definicion["variables"]

    _lector(_historico(semilla=9, senal=False))
    r2 = pre.entrenar(uow, tipo="cierre", usuario_id=uuid4())
    assert r2["entrenado"] and not r2["publicado"]
    assert "por debajo del mínimo" in r2["porque"][0] or "una clase" in r2["porque"][0]
    # El descartado no desbanca al publicado.
    assert gob.activo(uow.db, uow.tenant_id, "cierre").version == r["version"]


def test_la_regresion_se_compara_con_la_mediana(uow: UnidadDeTrabajo) -> None:  # noqa: F811
    _lector(_historico(senal=True))
    r = pre.entrenar(uow, tipo="fecha_cierre", usuario_id=uuid4())
    assert r["entrenado"]
    m = r["metricas"]
    assert m["mae"] < m["mae_mediana"] and r["publicado"] == (m["mejora_pct"] >= 5.0)


def test_con_pocos_datos_no_se_entrena_y_se_dice(uow: UnidadDeTrabajo) -> None:  # noqa: F811
    _lector(_historico(n=40))
    r = pre.entrenar(uow, tipo="cierre", usuario_id=uuid4())
    assert r["entrenado"] is False and r["publicado"] is False
    assert "superstición" in " ".join(r["porque"])
    assert gob.activo(uow.db, uow.tenant_id, "cierre") is None


def test_un_tipo_que_no_se_entrena_aqui_se_rechaza(uow: UnidadDeTrabajo) -> None:  # noqa: F811
    with pytest.raises(ErrorValidacion):
        pre.entrenar(uow, tipo="anomalia", usuario_id=uuid4())


# ── Puntuar registros reales ────────────────────────────────────────────────


def test_se_puntua_por_id_con_factores_y_se_guarda(uow: UnidadDeTrabajo) -> None:  # noqa: F811
    historico = _historico(senal=True)
    _lector(historico)
    pre.entrenar(uow, tipo="cierre", usuario_id=uuid4())
    abierta = next(o for o in historico if o["estado"] == "abierta")
    quien = _quien("opportunity:read", tenant_id=uow.tenant_id)
    salida = pre.puntuar_registro(
        uow, objeto="oportunidad", objeto_id=UUID(abierta["id"]), principal=quien
    )
    cierre = next(p for p in salida["predicciones"] if p["tipo"] == "cierre")
    assert cierre["hay"] and 0 < cierre["valor"] < 1
    assert cierre["factores"] and {"etiqueta", "aporta", "valor"} <= set(cierre["factores"][0])
    # Sin modelo publicado de importe, se dice por qué y no se inventa.
    importe = next(p for p in salida["predicciones"] if p["tipo"] == "importe")
    assert importe["hay"] is False and importe["porque"]
    guardadas = (
        uow.db.execute(select(Prediccion).where(Prediccion.objeto_id == UUID(abierta["id"])))
        .scalars()
        .all()
    )
    assert len(guardadas) == 1
    # La segunda vez se devuelve la guardada, no se recalcula.
    pre.puntuar_registro(uow, objeto="oportunidad", objeto_id=UUID(abierta["id"]), principal=quien)
    assert (
        len(
            uow.db.execute(select(Prediccion).where(Prediccion.objeto_id == UUID(abierta["id"])))
            .scalars()
            .all()
        )
        == 1
    )


def test_un_modelo_de_pesos_declarados_no_puntua_registros_reales(
    uow: UnidadDeTrabajo,  # noqa: F811
) -> None:
    fila, _ = gob.registrar_version(
        uow,
        tipo="cierre",
        variables=["x"],
        pesos={"x": 1.0},
        metricas={"auc": 0.9, "precision": 1, "recall": 1, "muestras": 300},
    )
    gob.activar(uow, tipo="cierre", version=fila.version)
    historico = _historico()
    _lector(historico)
    abierta = next(o for o in historico if o["estado"] == "abierta")
    salida = pre.puntuar_registro(
        uow,
        objeto="oportunidad",
        objeto_id=UUID(abierta["id"]),
        principal=_quien(tenant_id=uow.tenant_id),
    )
    assert salida["predicciones"][0]["hay"] is False
    assert "declarados" in salida["predicciones"][0]["porque"]


# ── Siguiente mejor oferta y segmento ───────────────────────────────────────


def test_la_siguiente_oferta_sale_de_la_coocurrencia_y_se_mide() -> None:
    cestas = {f"c{i}": {"a", "b"} for i in range(12)} | {f"d{i}": {"a", "c"} for i in range(3)}
    tabla = pre.coocurrencias(cestas)
    recos = pre.recomendar({"a"}, tabla, {"b": "Bomba", "c": "Cable"}, 2)
    assert recos[0]["producto"] == "b" and "12" in recos[0]["porque"]
    medido = pre.entrenar_oferta(cestas, {}, cuantos=1)
    assert medido["metricas"]["muestras"] == 15
    assert 0 <= medido["metricas"]["acierto_top"] <= 1


def test_el_segmento_se_crea_en_marketing_con_los_elegidos_y_se_congela(
    uow: UnidadDeTrabajo,  # noqa: F811
) -> None:
    historico = _historico(senal=True)
    pedidas = _lector(historico)
    # Un modelo de propensión publicado, construido a mano: lo que se prueba
    # aquí es el segmento, no el entrenamiento (que tiene sus pruebas).
    filas = [
        r
        for c in {o["cuenta_id"] for o in historico}
        if (r := pre.rasgos_cuenta(c, historico, HOY)) is not None
    ]
    numericas, _ = pre.VARIABLES["propension"]
    definicion = pre.preparar(
        filas, numericas=numericas, categoricas=[], max_categorias=8, minimo_por_categoria=10
    )
    definicion["origen"] = "historico"
    fila, _ = gob.registrar_version(
        uow,
        tipo="propension",
        variables=definicion["variables"],
        pesos={"_sesgo": 0.0},
        metricas={"auc": 0.7, "precision": 0.5, "recall": 0.5, "muestras": 300},
    )
    fila.definicion = definicion
    gob.activar(uow, tipo="propension", version=fila.version)
    salida = pre.segmento(
        uow,
        principal=_quien("segment:write", tenant_id=uow.tenant_id),
        criterio="propension",
        minimo=0.0,
        tope=5,
        nombre="Prueba",
    )
    assert salida["creado"] and salida["previstos"] == 5
    alta = next(p for p in pedidas if p[1] == "/api/v1/segmentos")
    condicion = alta[2]["definicion"]["hijos"][0]
    assert condicion["atributo"] == "cuenta.objeto_id" and len(condicion["valor"]) == 5
    assert any(p[1] == "/api/v1/segmentos/seg-1/congelar" for p in pedidas)
    # Marketing congeló 3 de 5: se dice, no se calla.
    assert "le faltan 2" in salida["aviso"]


# ── Preguntas a los datos ───────────────────────────────────────────────────


def _crm_para_consulta(pedidas: list[tuple[str, dict[str, Any]]], monkeypatch: Any):
    def leer(*, metodo: str, ruta: str, parametros: dict[str, Any] | None = None, **_):
        pedidas.append((ruta, dict(parametros or {})))
        if ruta == "/api/v1/sales/filtros":
            return {
                "estado": 200,
                "datos": {"colecciones": {"oportunidad": "/api/v1/opportunities"}},
            }
        if ruta == "/api/v1/sales/filtros/oportunidad":
            return {
                "estado": 200,
                "datos": {"se_puede_filtrar_por": ["estado", "importe", "nombre"]},
            }
        if ruta == "/api/v1/sales/estados/oportunidad":
            return {
                "estado": 200,
                "datos": {"estados": [{"clave": "abierta"}, {"clave": "ganada"}]},
            }
        if ruta == "/api/v1/opportunities":
            filas = [
                {"estado": "ganada", "importe": "60000"},
                {"estado": "ganada", "importe": "90000"},
                {"estado": "perdida", "importe": "70000"},
            ]
            return {"estado": 200, "datos": {"items": filas, "hay_mas": False, "total_aprox": 3}}
        return {"estado": 404, "datos": {}}

    cn.registrar_lector(leer)
    monkeypatch.setattr(
        cn,
        "_contrato_de",
        lambda servicio: {
            "paths": {
                "/api/v1/opportunities": {
                    "get": {
                        "parameters": [
                            {"name": "estado", "in": "query", "schema": {"default": "abierta"}}
                        ]
                    }
                }
            }
        },
    )


def test_la_pregunta_se_ejecuta_contra_el_listado_y_devuelve_la_consulta(
    uow: UnidadDeTrabajo,  # noqa: F811
    puerto_de_mentira: dict[str, Any],  # noqa: F811
    monkeypatch: Any,
) -> None:
    _proveedor(uow)
    pedidas: list[tuple[str, dict[str, Any]]] = []
    _crm_para_consulta(pedidas, monkeypatch)
    rag_mod.registrar_traductor(
        lambda **kw: {
            "plan": {
                "objeto": "oportunidad",
                # En singular, como lo escribió el modelo de verdad: se normaliza.
                "filtro": [{"campo": "importe", "operador": ">", "valor": 50000}],
                "agrupar_por": "estado",
                "agregado": {"funcion": "suma", "campo": "importe"},
            },
            "interpretacion": "Importe por estado de lo que pasa de 50.000",
        }
    )
    salida = cn.preguntar(
        uow,
        pregunta="Importe de las oportunidades por estado",
        principal=_quien("ia:usar", tenant_id=uow.tenant_id),
    )
    assert salida["ejecutado"], salida
    assert salida["consulta"]["parametros"] == {"importe__mayor": 50000}
    # El listado filtra por su cuenta (estado=abierta) y se dice.
    assert salida["consulta"]["por_defecto_del_listado"] == {"estado": "abierta"}
    assert "estado=abierta" in salida["respuesta"]
    assert {g["grupo"]: g["valor"] for g in salida["agregados"]} == {
        "ganada": 150000,
        "perdida": 70000,
    }
    # Al modelo se le enseñaron los valores de estado del tenant.
    assert any(r == "/api/v1/sales/estados/oportunidad" for r, _ in pedidas)


def test_lo_que_no_se_puede_ejecutar_por_el_listado_no_se_ejecuta(
    uow: UnidadDeTrabajo,  # noqa: F811
    puerto_de_mentira: dict[str, Any],  # noqa: F811
    monkeypatch: Any,
) -> None:
    _proveedor(uow)
    pedidas: list[tuple[str, dict[str, Any]]] = []
    _crm_para_consulta(pedidas, monkeypatch)
    rag_mod.registrar_traductor(
        lambda **kw: {
            "plan": {
                "objeto": "oportunidad",
                # «contiene» es de la gramática de los planes, pero la API de
                # listados no lo ejecuta: sería una búsqueda de texto libre.
                "filtros": [{"campo": "nombre", "operador": "contiene", "valor": "x"}],
            },
        }
    )
    salida = cn.preguntar(uow, pregunta="oportunidades", principal=_quien(tenant_id=uow.tenant_id))
    assert salida["ejecutado"] is False
    assert "API de listados" in salida["problemas"][0]
    assert not any(r == "/api/v1/opportunities" for r, _ in pedidas)


def test_un_filtro_por_otro_operador_vacia_el_valor_por_defecto() -> None:
    plan = {"filtros": [{"campo": "estado", "operador": "en", "valor": ["ganada", "perdida"]}]}
    assert cn.parametros_de(plan) == {"estado__en": "ganada,perdida"}


def test_las_citas_agrupadas_cuentan_como_citas(
    uow: UnidadDeTrabajo,  # noqa: F811
    puerto_de_mentira: dict[str, Any],  # noqa: F811
) -> None:
    """Medido con el modelo de verdad: cita «[1, 2]» y se leía como ninguna."""
    _proveedor(uow)
    rag_mod.registrar_respondedor(lambda **kw: {"texto": "Defender el valor [1, 2]."})
    fr = [
        {"texto": "a", "permiso": "account:read", "fuente": "leccion", "id": "L1"},
        {"texto": "b", "permiso": "account:read", "fuente": "leccion", "id": "L2"},
    ]
    salida = rag_mod.responder(uow, pregunta="¿?", fragmentos=fr, principal=_quien("account:read"))
    assert salida["respondida"] and [c["id"] for c in salida["citas"]] == ["L1", "L2"]


# ── El asistente que actúa ──────────────────────────────────────────────────


def _proponer(accion: str | None, argumentos: dict[str, Any]) -> None:
    acc.registrar_proponedor(
        lambda **kw: {"accion": accion, "argumentos": argumentos, "porque": "pedido"}
    )


def test_el_asistente_propone_de_la_lista_y_no_hace_nada_hasta_confirmar(
    uow: UnidadDeTrabajo,  # noqa: F811
    puerto_de_mentira: dict[str, Any],  # noqa: F811
) -> None:
    _proveedor(uow)
    hechas: list[dict[str, Any]] = []
    acc.registrar_ejecutor(lambda **kw: hechas.append(kw) or {"estado": 201, "datos": {"id": "t1"}})
    _proponer(
        "crear_tarea",
        {"asunto": "Llamar", "inventado": "x", "objeto": "cuenta", "objeto_id": "no-es-uuid"},
    )
    quien = _quien("ia:usar", "activity:write", "account:read", tenant_id=uow.tenant_id)
    salida = asis.conversar(
        uow,
        conversacion_id=uuid4(),
        pregunta="Crea una tarea para llamar",
        fragmentos=[
            {
                "texto": "El contrato vence en marzo.",
                "permiso": "account:read",
                "fuente": "contrato",
                "id": "D1",
            }
        ],
        principal=quien,
    )
    propuesta = salida["accion_propuesta"]
    # Lo que no declara la acción se tira; un id inventado no es un id; y
    # «cuelga de una cuenta» sin decir cuál no cuelga de nada.
    assert propuesta["argumentos"] == {"asunto": "Llamar"}
    assert hechas == [] and salida["ejecutado"] is False

    hecha = acc.ejecutar(
        uow,
        accion_id=UUID(propuesta["id"]),
        principal=quien,
        confirmar=True,
        argumentos={"cuerpo": "Revisar oferta"},
    )
    assert hecha["estado"] == "ejecutada" and hecha["resultado"]["id"] == "t1"
    assert hechas == [
        {
            "metodo": "POST",
            "ruta": "/api/v1/activities",
            "cuerpo": {"asunto": "Llamar", "cuerpo": "Revisar oferta", "tipo": "tarea"},
        }
    ]
    with pytest.raises(Conflicto):
        acc.ejecutar(uow, accion_id=UUID(propuesta["id"]), principal=quien, confirmar=True)


def test_sin_permiso_no_se_ofrece_y_otra_persona_no_confirma(
    uow: UnidadDeTrabajo,  # noqa: F811
    puerto_de_mentira: dict[str, Any],  # noqa: F811
) -> None:
    _proveedor(uow)
    _proponer("abrir_caso", {"asunto": "Avería"})
    sin = _quien("ia:usar", tenant_id=uow.tenant_id)
    assert acc.proponer(uow, pregunta="abre un caso", respuesta="", principal=sin) is None

    quien = _quien("case:write", tenant_id=uow.tenant_id)
    propuesta = acc.proponer(uow, pregunta="abre un caso", respuesta="", principal=quien)
    assert propuesta and propuesta["accion"] == "abrir_caso"
    with pytest.raises(Prohibido):
        acc.ejecutar(
            uow, accion_id=UUID(propuesta["id"]), principal=_quien("case:write"), confirmar=True
        )
    descartada = acc.ejecutar(
        uow, accion_id=UUID(propuesta["id"]), principal=quien, confirmar=False
    )
    assert descartada["estado"] == "descartada"


def test_si_falta_un_dato_obligatorio_se_pide(
    uow: UnidadDeTrabajo,  # noqa: F811
    puerto_de_mentira: dict[str, Any],  # noqa: F811
) -> None:
    _proveedor(uow)
    _proponer("capturar_lead", {"nombre": "Ana"})
    quien = _quien("lead:write", tenant_id=uow.tenant_id)
    propuesta = acc.proponer(uow, pregunta="apunta un lead", respuesta="", principal=quien)
    assert propuesta["faltan"] == ["empresa"]
    with pytest.raises(ErrorValidacion):
        acc.ejecutar(uow, accion_id=UUID(propuesta["id"]), principal=quien, confirmar=True)


def test_una_accion_que_no_esta_en_la_lista_no_se_propone(
    uow: UnidadDeTrabajo,  # noqa: F811
    puerto_de_mentira: dict[str, Any],  # noqa: F811
) -> None:
    _proveedor(uow)
    _proponer("borrar_cuenta", {"id": "x"})
    quien = _quien("*:*", tenant_id=uow.tenant_id)
    assert acc.proponer(uow, pregunta="borra la cuenta", respuesta="", principal=quien) is None


def test_math_redondeo_de_intervalo_sin_validacion() -> None:
    """Un intervalo se mide en la validación: con ratios vacíos no hay intervalo."""
    assert pre._cuantil([], 0.1) == 0.0
    assert math.isclose(pre._cuantil([1, 2, 3], 0.5), 2.0)
