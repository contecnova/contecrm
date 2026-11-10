"""La evaluación de la IA: banco, comprobaciones, ejecución, aviso y rutas.

Sin llamar al modelo real: los puertos se sustituyen por dobles y lo que se
prueba es lo que la evaluación hace con lo que vuelve —que es donde un acierto
falso se cuela—. Las rutas se recorren por HTTP como las pide la pantalla
«Evaluación de la IA», y se fija la forma que ésta lee.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from starlette.testclient import TestClient

from services.intelligence import (
    acciones_asistente,
    agentes,
    conversacion,
    extraccion,
    generacion,
    rag,
    reuniones,
    variantes_copy,
)
from services.intelligence import evaluacion as ev
from services.intelligence.evaluacion_de_serie import CASOS, FUNCIONES
from tests.unit.test_ia_generativa import _proveedor

# ── Sin base de datos ─────────────────────────────────────────────────────


def test_el_banco_de_serie_cubre_cada_funcion_con_criterios_que_se_saben_comprobar() -> None:
    claves = [c["clave"] for c in CASOS]
    assert len(claves) == len(set(claves)), "claves repetidas en el banco"
    por_funcion: dict[str, int] = {}
    for caso in CASOS:
        assert caso["funcion"] in FUNCIONES, caso["clave"]
        assert caso["criterios"], f"{caso['clave']} no comprueba nada"
        for criterio in caso["criterios"]:
            assert criterio["tipo"] in ev.COMPROBACIONES, (caso["clave"], criterio)
        por_funcion[caso["funcion"]] = por_funcion.get(caso["funcion"], 0) + 1
    # Cada función con al menos tres casos: con uno, un 100 % no dice nada.
    assert set(por_funcion) == set(FUNCIONES)
    assert min(por_funcion.values()) >= 3, por_funcion
    # El juez sólo donde no hay otra forma: en los resúmenes de caso.
    con_juez = {c["funcion"] for c in CASOS for x in c["criterios"] if x["tipo"] == "juez"}
    assert con_juez == {"resumen_caso"}


# El plan BUENO de cada pregunta del banco. Si la cifra esperada de un caso
# estuviera mal calculada, el modelo que acierta saldría fallado: esto lo caza.
_PLANES_BUENOS = {
    "consulta.ganadas_cuantas": {
        "objeto": "oportunidades",
        "filtros": [{"campo": "estado", "operador": "=", "valor": "ganada"}],
        "agregado": {"funcion": "cuenta"},
    },
    "consulta.ganado_2026": {
        "objeto": "oportunidades",
        "filtros": [
            {"campo": "estado", "operador": "=", "valor": "ganada"},
            {"campo": "fecha_cierre", "operador": ">=", "valor": "2026-01-01"},
            {"campo": "fecha_cierre", "operador": "<=", "valor": "2026-12-31"},
        ],
        "agregado": {"funcion": "suma", "campo": "importe"},
    },
    "consulta.abiertas_de_marta": {
        "objeto": "oportunidades",
        "filtros": [{"campo": "propietario", "operador": "=", "valor": "Marta"}],
        "agregado": {"funcion": "cuenta"},
    },
    "consulta.media_perdidas": {
        "objeto": "oportunidades",
        "filtros": [{"campo": "estado", "operador": "=", "valor": "perdida"}],
        "agregado": {"funcion": "media", "campo": "importe"},
    },
    "consulta.todas_sin_filtro_por_defecto": {
        "objeto": "oportunidades",
        "filtros": [{"campo": "estado", "operador": "=", "valor": ""}],
        "agregado": {"funcion": "cuenta"},
    },
    "consulta.ganado_por_propietario": {
        "objeto": "oportunidades",
        "filtros": [{"campo": "estado", "operador": "=", "valor": "ganada"}],
        "agrupar_por": "propietario",
        "agregado": {"funcion": "suma", "campo": "importe"},
    },
    "consulta.casos_alta_abiertos": {
        "objeto": "casos",
        "filtros": [
            {"campo": "estado", "operador": "=", "valor": "abierto"},
            {"campo": "prioridad", "operador": "=", "valor": "alta"},
        ],
        "agregado": {"funcion": "cuenta"},
    },
}


@pytest.mark.parametrize("clave", sorted(_PLANES_BUENOS))
def test_las_cifras_del_banco_salen_de_sus_filas_con_el_plan_bueno(clave: str) -> None:
    caso = next(c for c in CASOS if c["clave"] == clave)
    plan = _PLANES_BUENOS[clave]
    salida = ev._ex_consulta(
        lambda **kw: {"plan": plan, "interpretacion": ""}, caso["entrada"], None
    )
    resultado = ev.comprobar(caso["criterios"], salida)
    assert all(r["ok"] for r in resultado), resultado


def test_el_filtro_por_defecto_del_listado_se_aplica_si_el_plan_no_lo_quita() -> None:
    caso = next(c for c in CASOS if c["clave"] == "consulta.todas_sin_filtro_por_defecto")
    sin_quitar = {"objeto": "oportunidades", "filtros": [], "agregado": {"funcion": "cuenta"}}
    salida = ev._ex_consulta(lambda **kw: {"plan": sin_quitar}, caso["entrada"], None)
    # Como el listado real: sin decir nada, sólo las abiertas (3), no las 10.
    assert salida["valor"] == 3
    assert not all(r["ok"] for r in ev.comprobar(caso["criterios"], salida))


def test_lo_que_no_se_puede_evaluar_no_se_cumple() -> None:
    assert ev.comprobar([{"tipo": "inventado"}], {})[0]["ok"] is False
    # Un juez sin conectar no aprueba.
    r = ev.comprobar([{"tipo": "juez", "pregunta": "¿?"}], {"texto": "x"})[0]
    assert r["ok"] is False and r["juez"] is True


def test_contiene_admite_alternativas_y_no_distingue_acentos() -> None:
    criterio = [{"tipo": "contiene", "campo": "texto", "valores": ["5|cinco", "canarias"]}]
    assert ev.comprobar(criterio, {"texto": "Tarda cinco días a CANÁRIAS"})[0]["ok"]
    fallo = ev.comprobar(criterio, {"texto": "Tarda 48 horas"})[0]
    assert not fallo["ok"] and "5|cinco" in fallo["porque"]


def test_el_numero_con_decimales_se_convierte_bien() -> None:
    """Medido el 10-11-2026 con el banco: «2904.00» salía 290400.

    `convertir` quitaba todos los puntos como si fueran de millar, y el modelo
    devuelve el importe con punto decimal. Un total de factura cien veces mayor
    con buena cara.
    """
    from decimal import Decimal

    assert extraccion.convertir("2904.00", "numero") == (Decimal("2904.00"), True)
    assert extraccion.convertir(2904.0, "numero") == (Decimal("2904.0"), True)
    assert extraccion.convertir("2.904,00", "numero") == (Decimal("2904.00"), True)
    assert extraccion.convertir("18.000", "numero") == (Decimal("18000"), True)
    assert extraccion.convertir("1.250.000", "numero") == (Decimal("1250000"), True)
    assert extraccion.convertir("21", "numero") == (Decimal("21"), True)


# ── Con base de datos ─────────────────────────────────────────────────────


_PUERTOS = {
    "rag._respondedor": (rag, "_respondedor"),
    "rag._traductor": (rag, "_traductor"),
    "generacion._generador": (generacion, "_generador"),
    "conversacion._resumidor": (conversacion, "_resumidor"),
    "conversacion._clasificador": (conversacion, "_clasificador"),
    "extraccion._extractor": (extraccion, "_extractor"),
    "reuniones._resumidor": (reuniones, "_resumidor"),
    "variantes_copy._redactor": (variantes_copy, "_redactor"),
    "acciones_asistente._proponedor": (acciones_asistente, "_proponedor"),
    "agentes._planificador": (agentes, "_planificador"),
}


@pytest.fixture
def puertos() -> Any:
    """Deja los puertos como estaban: son globales del proceso."""
    previos = {k: getattr(m, a) for k, (m, a) in _PUERTOS.items()}
    try:
        yield
    finally:
        for k, (m, a) in _PUERTOS.items():
            setattr(m, a, previos[k])


def _todo_mal() -> None:
    """Un modelo que contesta a todo con lo mismo y sin sustancia."""
    vacio = {"texto": "Respuesta genérica.", "tokens_entrada": 10, "tokens_salida": 5}
    for modulo, atributo in _PUERTOS.values():
        setattr(modulo, atributo, lambda **kw: dict(vacio))


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


@pytest.mark.db
def test_un_caso_de_extraccion_bien_y_mal_con_el_mismo_filtro_que_la_funcion(
    uow: UnidadDeTrabajo, puertos: Any
) -> None:
    _proveedor(uow)
    caso = next(c for c in CASOS if c["clave"] == "extraccion.factura")
    texto = caso["entrada"]["texto"]

    def _bien(**kw: Any) -> dict[str, Any]:
        return {
            "campos": [
                {
                    "clave": "numero_factura",
                    "valor": "F-2026-0877",
                    "confianza": 0.9,
                    "cita": "F-2026-0877",
                },
                {"clave": "fecha", "valor": "2026-10-15", "confianza": 0.9, "cita": "15/10/2026"},
                {
                    "clave": "total",
                    "valor": "2904.00",
                    "confianza": 0.9,
                    "cita": "total 2.904,00 €",
                },
                {
                    "clave": "vencimiento",
                    "valor": "14/11/2026",
                    "confianza": 0.9,
                    "cita": "Vencimiento: 14/11/2026",
                },
                {"clave": "iva_pct", "valor": 21, "confianza": 0.9, "cita": "IVA 21 %"},
            ],
            "tokens_entrada": 100,
            "tokens_salida": 50,
        }

    extraccion.registrar_extractor(_bien)
    r = ev.evaluar_caso(uow, caso)
    assert r["acierto"], r["porque"]
    assert r["version_prompt"] and r["latencia_ms"] >= 0 and r["coste"] > 0

    def _cita_inventada(**kw: Any) -> dict[str, Any]:
        salida = _bien()
        salida["campos"][2]["cita"] = "importe total de 2.904 euros"  # no está en el texto
        return salida

    assert "importe total de 2.904 euros" not in texto
    extraccion.registrar_extractor(_cita_inventada)
    r = ev.evaluar_caso(uow, caso)
    assert not r["acierto"]
    assert "total: no extraído (la cita no aparece en el texto)" in r["porque"]


@pytest.mark.db
def test_el_asistente_que_no_dice_no_lo_se_con_esas_palabras_falla(
    uow: UnidadDeTrabajo, puertos: Any
) -> None:
    _proveedor(uow)
    caso = next(c for c in CASOS if c["clave"] == "asistente.horario_no_consta")
    rag.registrar_respondedor(
        lambda **kw: {"texto": "El horario es de 9 a 18 h [1].", "sin_respuesta": False}
    )
    r = ev.evaluar_caso(uow, caso)
    assert not r["acierto"] and "no lo sabe" in r["porque"]
    rag.registrar_respondedor(lambda **kw: {"texto": "No lo sé.", "sin_respuesta": True})
    assert ev.evaluar_caso(uow, caso)["acierto"]


@pytest.mark.db
def test_un_proveedor_que_falla_es_un_caso_fallado_con_su_motivo(
    uow: UnidadDeTrabajo, puertos: Any
) -> None:
    from crmcore.errors import ErrorDependencia

    _proveedor(uow)

    def _cae(**kw: Any) -> dict[str, Any]:
        raise ErrorDependencia(
            "El proveedor de IA ha rechazado la petición",
            error_code="ia.peticion_rechazada",
            detalle={"dijo": "quota exceeded"},
        )

    extraccion.registrar_extractor(_cae)
    caso = next(c for c in CASOS if c["funcion"] == "extraccion")
    r = ev.evaluar_caso(uow, caso)
    assert not r["acierto"] and "quota exceeded" in r["porque"]


@pytest.mark.db
def test_una_ejecucion_entera_guarda_el_acierto_por_funcion_y_avisa_si_baja(
    uow: UnidadDeTrabajo, puertos: Any
) -> None:
    _proveedor(
        uow,
        modelos=[
            {"uso": u, "clave": f"m-{u}", "nombre": u}
            for u in sorted({f["uso"] for f in FUNCIONES.values()})
        ],
    )
    _todo_mal()
    pide = uuid4()
    resumen = ev.evaluar(uow, pedida_por=pide)

    assert resumen["estado"] == "terminada"
    assert resumen["casos"] == len(CASOS)
    assert set(resumen["por_funcion"]) == set(FUNCIONES)
    for funcion, datos in resumen["por_funcion"].items():
        assert datos["casos"] >= 3 and datos["acierto"] is not None, funcion
    # Con un modelo que no contesta nada útil, todo baja del umbral —salvo lo
    # que acierta por no hacer nada, que también se ve—.
    bajas = {b["funcion"] for b in resumen["bajo_umbral"]}
    assert {"asistente", "consulta_datos", "extraccion", "compromisos_reunion"} <= bajas
    assert resumen["aviso"].startswith("La evaluación de la IA ha bajado")
    assert set(resumen["versiones_prompt"]) == set(FUNCIONES)

    avisos = [p for p in uow._pendientes if p["tipo"] == "automatizacion.aviso"]
    assert len(avisos) == 1
    assert avisos[0]["data"]["menciones"] == [str(pide)]
    assert avisos[0]["data"]["objeto_tipo"] == "evaluacion_ia"

    # Lo escrito, no sólo lo devuelto: cada caso con su porqué.
    detalle = ev.detalle(uow.db, uow.tenant_id, UUID(resumen["id"]))
    assert len(detalle["resultados"]) == len(CASOS)
    assert all(r["porque"] for r in detalle["resultados"] if not r["acierto"])

    # Y el banco se instaló como configuración del tenant: una segunda vez no
    # duplica nada.
    assert ev.asegurar_banco(uow) == 0


@pytest.mark.db
def test_un_caso_desactivado_no_se_evalua_ni_vuelve_al_reinstalar(
    uow: UnidadDeTrabajo, puertos: Any
) -> None:
    _proveedor(uow)
    ev.asegurar_banco(uow)
    clave = CASOS[0]["clave"]
    ev.cambiar_caso(uow, clave=clave, activo=False)
    ev.asegurar_banco(uow)
    fila = ev.preparar(uow)
    assert clave not in fila.casos_previstos
    assert len(fila.casos_previstos) == len(CASOS) - 1


# ── Por HTTP, como la pantalla ────────────────────────────────────────────


@pytest.fixture
def cliente(db: Any) -> Any:
    import importlib
    import os

    from crmcore.config import get_settings

    previo = os.environ.get("OUTBOX_ENABLED")
    os.environ["OUTBOX_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        modulo = importlib.import_module("services.intelligence.main")
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
            H_FACTOR_FUERTE: datetime.now(timezone.utc).isoformat(),
        },
        get_settings().secret_key.get_secret_value(),
    )


@pytest.mark.db
def test_la_pantalla_por_http_evaluar_ver_y_cambiar_el_banco(
    cliente: TestClient, cabeceras: dict[str, str], uow: UnidadDeTrabajo, puertos: Any
) -> None:
    _proveedor(uow)
    uow.db.flush()

    vacio = cliente.get("/api/v1/ia/evaluacion", headers=cabeceras)
    assert vacio.status_code == 200, vacio.text
    cuerpo = vacio.json()
    assert {
        "umbral",
        "cada_horas",
        "ultima",
        "en_curso",
        "funciones",
        "tendencia",
        "fallos",
    } <= set(cuerpo)
    assert cuerpo["ultima"] is None and cuerpo["banco"] == len(CASOS)
    assert {f["funcion"] for f in cuerpo["funciones"]} == set(FUNCIONES)

    lanzada = cliente.post(
        "/api/v1/ia/evaluacion/ejecutar", headers=cabeceras, json={"funciones": ["extraccion"]}
    )
    assert lanzada.status_code == 202, lanzada.text
    ids = lanzada.json()
    assert {"ejecucion_id", "casos"} <= set(ids)
    otra = cliente.post("/api/v1/ia/evaluacion/ejecutar", headers=cabeceras, json={})
    assert otra.status_code == 409 and otra.json()["error_code"] == "evaluacion.en_curso"
    assert (
        cliente.get("/api/v1/ia/evaluacion", headers=cabeceras).json()["en_curso"]["id"]
        == ids["ejecucion_id"]
    )

    # La tarea de fondo, vuelta a vuelta, como la corre el relevo del servicio:
    # una tanda cada vez, y la última la cierra.
    _todo_mal()
    assert uow.tenant_id in ev.tenants_con_evaluacion_en_curso()
    vueltas = []
    for _ in range(50):
        r = ev.avanzar_en_curso(uow.tenant_id)
        vueltas.append(r)
        if r.get("cerrada"):
            break
    assert vueltas[-1]["cerrada"] == ids["ejecucion_id"]
    assert sum(v["avanzados"] for v in vueltas) == ids["casos"]
    assert uow.tenant_id not in ev.tenants_con_evaluacion_en_curso()

    panel = cliente.get("/api/v1/ia/evaluacion", headers=cabeceras).json()
    assert panel["ultima"]["id"] == ids["ejecucion_id"]
    extr = next(f for f in panel["funciones"] if f["funcion"] == "extraccion")
    assert extr["casos"] == ids["casos"] and extr["acierto"] is not None
    assert {
        "nombre",
        "aciertos",
        "acierto_anterior",
        "coste",
        "latencia_media_ms",
        "version_prompt",
    } <= set(extr)
    assert panel["tendencia"] and "extraccion" in panel["tendencia"][-1]
    assert panel["fallos"] and {"caso_nombre", "funcion", "porque", "criterios"} <= set(
        panel["fallos"][0]
    )

    lista = cliente.get("/api/v1/ia/evaluacion/ejecuciones", headers=cabeceras).json()
    assert lista["ejecuciones"][0]["id"] == ids["ejecucion_id"]
    una = cliente.get(f"/api/v1/ia/evaluacion/ejecuciones/{ids['ejecucion_id']}", headers=cabeceras)
    assert una.status_code == 200 and una.json()["resultados"]

    casos = cliente.get("/api/v1/ia/evaluacion/casos", headers=cabeceras).json()
    assert casos["instalado"] and len(casos["casos"]) == len(CASOS)
    clave = casos["casos"][0]["clave"]
    apagado = cliente.patch(
        f"/api/v1/ia/evaluacion/casos/{clave}", headers=cabeceras, json={"activo": False}
    )
    assert apagado.status_code == 200 and apagado.json()["activo"] is False

    nuevo = cliente.post(
        "/api/v1/ia/evaluacion/casos",
        headers=cabeceras,
        json={
            "clave": "propio.saludo",
            "funcion": "clasificacion",
            "entrada": {"texto": "Gracias por todo"},
            "criterios": [{"tipo": "igual", "campo": "intencion", "valor": "agradecimiento"}],
        },
    )
    assert nuevo.status_code == 201, nuevo.text
    assert nuevo.json()["origen"] == "propio"
    malo = cliente.post(
        "/api/v1/ia/evaluacion/casos",
        headers=cabeceras,
        json={
            "clave": "propio.x",
            "funcion": "clasificacion",
            "entrada": {"t": 1},
            "criterios": [{"tipo": "magia"}],
        },
    )
    assert malo.status_code == 422 and malo.json()["error_code"] == "evaluacion.criterio"


def test_no_lo_se_se_reconoce_y_no_lo_sabes_ya_no_se_pide() -> None:
    """Medido el 10-11-2026: el modelo contestaba «No lo sabes.» al pie de la
    letra del prompt, y el asistente lo presentaba como una respuesta."""
    import inspect

    from services.intelligence import puerto

    assert puerto._dice_que_no_sabe("No lo sé.")
    assert puerto._dice_que_no_sabe("no lo se")
    assert not puerto._dice_que_no_sabe("El plazo es de 30 días [1].")
    assert "que no lo sabes" not in inspect.getsource(puerto._responder)


@pytest.mark.db
def test_un_caso_de_serie_sin_tocar_se_pone_al_dia_y_uno_cambiado_no(
    uow: UnidadDeTrabajo,
) -> None:
    ev.asegurar_banco(uow)
    intacto, cambiado = CASOS[0]["clave"], CASOS[1]["clave"]
    filas = {
        f.clave: f for f in uow.db.query(ev.CasoEvaluacionIA).filter_by(tenant_id=uow.tenant_id)
    }
    # Como si el producto hubiera corregido el criterio después de instalarlo.
    filas[intacto].criterios = [{"tipo": "contiene", "campo": "texto", "valores": ["viejo"]}]
    propio = [{"tipo": "contiene", "campo": "texto", "valores": ["mío"]}]
    ev.cambiar_caso(uow, clave=cambiado, criterios=propio)
    ev.cambiar_caso(uow, clave=intacto, activo=False)
    ev.asegurar_banco(uow)
    assert filas[intacto].criterios == CASOS[0]["criterios"]
    assert filas[intacto].activo is False
    assert filas[cambiado].criterios == propio and filas[cambiado].version == 2
