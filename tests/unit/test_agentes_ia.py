"""Agentes de IA y asistencia (CRM-05.02.03.01 a .06, CRM-04.02.02.05,
CRM-04.03.02.02, CRM-01.01.05.05, CRM-03.01.02.04).

Un agente es una automatización que decide sola qué paso dar, y eso es lo que lo
hace útil y lo que lo hace peligroso. Las pruebas van detrás de las cuatro formas
en que un agente se convierte en un incidente:

  * el bucle: se llama a sí mismo cuarenta veces,
  * la factura: funciona y cuesta lo que nadie previó,
  * el paso que nadie autorizó: borra algo porque entendió mal una instrucción,
  * y lo que no se puede deshacer, que es lo que de verdad decide si se puede
    poner un agente en producción.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, Prohibido

from services.intelligence import agentes as ag
from services.intelligence import enrutador as rut
from services.intelligence import herramientas as herr


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


@pytest.fixture(autouse=True)
def puertos(request: Any) -> Any:
    """Planificador e invocador controlados: lo que se comprueba es qué se le
    pide al agente y qué se hace con lo que devuelve."""
    estado: dict[str, Any] = {
        "pasos": [
            {
                "herramienta": "get_contacts",
                "argumentos": {"q": "acme"},
                "porque": "Buscar al contacto",
            }
        ],
        "invocaciones": [],
        "falla": False,
    }

    def _planificar(**kw: Any) -> dict[str, Any]:
        estado["ultimo_plan"] = kw
        return {"pasos": estado["pasos"], "tokens_entrada": 100, "tokens_salida": 50}

    def _invocar(**kw: Any) -> dict[str, Any]:
        estado["invocaciones"].append(kw)
        if estado["falla"]:
            raise RuntimeError("la herramienta ha fallado")
        return {"ok": True}

    ag.registrar_planificador(_planificar)
    ag.registrar_invocador(_invocar)
    return estado


def _proveedor(uow: UnidadDeTrabajo) -> None:
    rut.registrar_proveedor(
        uow,
        clave="modelo-ue",
        base_url="https://ia.example.com/v1",
        region="ue",
        admite_opt_out=True,
        modelos=[{"uso": "redaccion", "nombre": "m-redaccion"}],
        coste_entrada_millon=Decimal("1.00"),
        coste_salida_millon=Decimal("3.00"),
    )


def _agente(uow: UnidadDeTrabajo, **kw: Any) -> Any:
    base: dict[str, Any] = {
        "clave": "califica",
        "tipo": "calificacion_leads",
        "permisos": ["contact:read"],
        "herramientas": [
            {"nombre": "get_contacts", "riesgo": "lectura"},
            {"nombre": "post_contacts", "riesgo": "escritura"},
            {"nombre": "delete_contacts_por_id", "riesgo": "destructivo"},
        ],
    }
    base.update(kw)
    return ag.declarar(uow, **base)


# ── Herramientas desde la API (CRM-05.02.03.02) ───────────────────────────


def test_las_herramientas_salen_del_contrato_y_no_de_una_lista() -> None:
    """Una lista escrita a mano se queda en lo que alguien recordó declarar, y a
    los seis meses el agente no sabe hacer lo que se añadió después."""
    contrato = {
        "paths": {
            "/api/v1/contacts": {
                "get": {"summary": "Listar contactos"},
                "post": {"summary": "Crear contacto"},
            }
        }
    }
    salida = herr.desde_openapi(contrato, permisos={"*:*"})
    nombres = [h["nombre"] for h in salida["herramientas"]]
    assert "get_api_v1_contacts" in nombres
    assert "post_api_v1_contacts" in nombres


def test_lo_destructivo_no_entra_por_defecto() -> None:
    """Una herramienta de borrado disponible «porque la API la tiene» es la que
    acaba usándose por una instrucción mal entendida."""
    contrato = {"paths": {"/api/v1/contacts/{id}": {"delete": {"summary": "Borrar"}}}}
    salida = herr.desde_openapi(contrato, permisos={"*:*"})
    assert salida["herramientas"] == []
    assert "DELETE /api/v1/contacts/{id}" in salida["fuera"]["riesgo_no_admitido"]


def test_sin_herramientas_se_dice_que_no_es_un_fallo_del_modelo() -> None:
    salida = herr.desde_openapi({"paths": {}}, permisos=set())
    assert salida["cuantas"] == 0
    assert "no es un fallo del modelo" in salida["aviso"]


# ── Declaración y kill switch (CRM-05.02.03.01, .04, .06) ─────────────────


@pytest.mark.db
def test_sin_decir_nada_lo_destructivo_exige_aprobacion(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Vacío no es «ninguno»: leerlo así haría que declarar un agente sin pensar
    quitara justo el control que más falta hace."""
    agente = _agente(uow)
    assert agente.aprobacion_por_riesgo == ["destructivo"]


@pytest.mark.db
def test_un_agente_sin_tope_de_acciones_no_se_declara(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Es un bucle esperando a pasar."""
    with pytest.raises(ErrorValidacion) as fallo:
        _agente(uow, max_acciones=0)
    assert fallo.value.error_code == "agente.sin_tope"


@pytest.mark.db
def test_apagar_exige_motivo(uow: UnidadDeTrabajo, contexto_tenant: UUID) -> None:
    """El siguiente que lo encienda tiene que saber qué pasó."""
    _agente(uow)
    with pytest.raises(ErrorValidacion):
        ag.apagar(uow, clave="califica", motivo="  ")


@pytest.mark.db
def test_apagar_detiene_lo_que_estaba_en_vuelo(uow: UnidadDeTrabajo, contexto_tenant: UUID) -> None:
    """Apagar un agente que sigue terminando lo que empezó no es apagarlo."""
    _proveedor(uow)
    _agente(uow)
    lanzada = ag.lanzar(uow, clave="califica", objetivo="Calificar a Acme")

    ag.apagar(uow, clave="califica", motivo="Estaba tocando lo que no debía")

    ejecucion = uow.db.get(ag.EjecucionAgente, UUID(lanzada["ejecucion_id"]))
    assert ejecucion.estado == "detenida"
    with pytest.raises(Prohibido):
        ag.avanzar(uow, ejecucion_id=ejecucion.id)


@pytest.mark.db
def test_un_agente_apagado_no_se_lanza(uow: UnidadDeTrabajo, contexto_tenant: UUID) -> None:
    _proveedor(uow)
    _agente(uow)
    ag.apagar(uow, clave="califica", motivo="por si acaso")
    with pytest.raises(Prohibido):
        ag.lanzar(uow, clave="califica", objetivo="lo que sea")


@pytest.mark.db
def test_agotar_el_presupuesto_de_tokens_para_al_agente(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Un agente que funciona y cuesta lo que nadie previó es el segundo problema,
    y no lo resuelve el tope de acciones."""
    _proveedor(uow)
    _agente(uow, presupuesto_tokens_dia=1_000)
    # El primer lanzamiento gasta 150 tokens; se fuerza el gasto acumulado.
    ejecucion = ag.lanzar(uow, clave="califica", objetivo="una")
    fila = uow.db.get(ag.EjecucionAgente, UUID(ejecucion["ejecucion_id"]))
    fila.tokens = 5_000
    uow.db.flush()

    with pytest.raises(Conflicto) as fallo:
        ag.lanzar(uow, clave="califica", objetivo="otra")
    assert fallo.value.error_code == "agente.presupuesto_agotado"


# ── Plan y control humano (CRM-05.02.03.01, .03) ──────────────────────────


@pytest.mark.db
def test_el_plan_se_guarda_antes_de_ejecutar_nada(
    uow: UnidadDeTrabajo, contexto_tenant: UUID, puertos: dict[str, Any]
) -> None:
    """Sin plan previo, la auditoría es una lista de cosas que pasaron y no hay
    forma de ver dónde se torció."""
    _proveedor(uow)
    _agente(uow)
    salida = ag.lanzar(uow, clave="califica", objetivo="Calificar a Acme")
    assert salida["pasos"], "el plan tiene que quedar guardado"
    assert puertos["invocaciones"] == [], "lanzar no puede ejecutar nada"


@pytest.mark.db
def test_un_paso_destructivo_espera_a_una_persona(
    uow: UnidadDeTrabajo, contexto_tenant: UUID, puertos: dict[str, Any]
) -> None:
    """Un control humano que depende de que el modelo pida permiso no es un
    control: se decide fuera del modelo."""
    _proveedor(uow)
    _agente(uow)
    puertos["pasos"] = [
        {"herramienta": "delete_contacts_por_id", "argumentos": {"id": "x"}, "porque": "sobra"}
    ]
    salida = ag.lanzar(uow, clave="califica", objetivo="Limpiar duplicados")

    assert salida["estado"] == "esperando_aprobacion"
    resultado = ag.avanzar(uow, ejecucion_id=UUID(salida["ejecucion_id"]))
    assert resultado["avanzado"] is False
    assert puertos["invocaciones"] == []


@pytest.mark.db
def test_por_importe_tambien_se_para(
    uow: UnidadDeTrabajo, contexto_tenant: UUID, puertos: dict[str, Any]
) -> None:
    """El riesgo de la herramienta no lo dice todo: firmar por diez euros y por
    cien mil es la misma llamada."""
    _proveedor(uow)
    _agente(uow, aprobacion_desde_importe=Decimal("1000"))
    puertos["pasos"] = [
        {
            "herramienta": "post_contacts",
            "argumentos": {},
            "porque": "cerrar",
            "importe": "5000",
        }
    ]
    salida = ag.lanzar(uow, clave="califica", objetivo="Cerrar la oferta")
    assert salida["esperando_aprobacion"] == [1]


@pytest.mark.db
def test_un_importe_ilegible_no_se_cuela(
    uow: UnidadDeTrabajo, contexto_tenant: UUID, puertos: dict[str, Any]
) -> None:
    """Dejarlo pasar haría que un dato mal formado se saltara el control."""
    _proveedor(uow)
    _agente(uow, aprobacion_desde_importe=Decimal("1000"))
    puertos["pasos"] = [
        {"herramienta": "post_contacts", "argumentos": {}, "porque": "x", "importe": "mucho"}
    ]
    salida = ag.lanzar(uow, clave="califica", objetivo="lo que sea")
    assert salida["esperando_aprobacion"] == [1]


@pytest.mark.db
def test_una_herramienta_que_no_tiene_se_descarta_y_se_dice(
    uow: UnidadDeTrabajo, contexto_tenant: UUID, puertos: dict[str, Any]
) -> None:
    """Intentarla daría un 403 del otro lado y un paso fallido que parece un
    error del sistema — y el agente «no hace lo que le pido» sin que nadie sepa
    por qué."""
    _proveedor(uow)
    _agente(uow)
    puertos["pasos"] = [
        {"herramienta": "borrar_la_base_de_datos", "argumentos": {}, "porque": "eficiencia"}
    ]
    salida = ag.lanzar(uow, clave="califica", objetivo="lo que sea")
    assert salida["herramientas_descartadas"] == ["borrar_la_base_de_datos"]
    assert salida["pasos"] == []


@pytest.mark.db
def test_el_plan_se_recorta_al_tope_y_se_avisa(
    uow: UnidadDeTrabajo, contexto_tenant: UUID, puertos: dict[str, Any]
) -> None:
    """Un plan de cuarenta pasos que se corta en el diez deja veinte a medias y
    nadie sabe cuáles."""
    _proveedor(uow)
    _agente(uow, max_acciones=2)
    puertos["pasos"] = [
        {"herramienta": "get_contacts", "argumentos": {}, "porque": str(i)} for i in range(6)
    ]
    salida = ag.lanzar(uow, clave="califica", objetivo="mucho trabajo")
    assert len(salida["pasos"]) == 2
    assert salida["plan_recortado"] is True
    assert salida["aviso"]


@pytest.mark.db
def test_avanzar_ejecuta_un_solo_paso(
    uow: UnidadDeTrabajo, contexto_tenant: UUID, puertos: dict[str, Any]
) -> None:
    """Entre paso y paso es donde caben el apagado, el tope y la aprobación: un
    bucle que los ejecuta todos convierte esos tres controles en decoración."""
    _proveedor(uow)
    _agente(uow)
    puertos["pasos"] = [
        {"herramienta": "get_contacts", "argumentos": {"n": 1}, "porque": "uno"},
        {"herramienta": "get_contacts", "argumentos": {"n": 2}, "porque": "dos"},
    ]
    salida = ag.lanzar(uow, clave="califica", objetivo="dos cosas")
    ag.avanzar(uow, ejecucion_id=UUID(salida["ejecucion_id"]))
    assert len(puertos["invocaciones"]) == 1


@pytest.mark.db
def test_un_paso_fallido_para_la_ejecucion(
    uow: UnidadDeTrabajo, contexto_tenant: UUID, puertos: dict[str, Any]
) -> None:
    """Seguir con los siguientes pasos de un plan cuyo tercer paso falló es
    ejecutar un plan que ya no tiene sentido."""
    _proveedor(uow)
    _agente(uow)
    puertos["falla"] = True
    salida = ag.lanzar(uow, clave="califica", objetivo="algo")
    resultado = ag.avanzar(uow, ejecucion_id=UUID(salida["ejecucion_id"]))
    assert resultado["estado"] == "fallido"
    ejecucion = uow.db.get(ag.EjecucionAgente, UUID(salida["ejecucion_id"]))
    assert ejecucion.estado == "fallida"


# ── Auditoría y reversión (CRM-05.02.03.05) ───────────────────────────────


@pytest.mark.db
def test_lo_que_no_declara_como_deshacerse_no_es_reversible(
    uow: UnidadDeTrabajo, contexto_tenant: UUID, puertos: dict[str, Any]
) -> None:
    """Un correo enviado no se «des-envía». Fingir que la reversión es total
    sería peor que no tenerla, porque alguien confiaría."""
    _proveedor(uow)
    _agente(uow)
    puertos["pasos"] = [{"herramienta": "post_contacts", "argumentos": {}, "porque": "mandar"}]
    salida = ag.lanzar(uow, clave="califica", objetivo="mandar algo")
    ag.avanzar(uow, ejecucion_id=UUID(salida["ejecucion_id"]))

    informe = ag.actuacion(uow.db, uow.tenant_id, UUID(salida["ejecucion_id"]))
    assert informe["reversible_del_todo"] is False
    assert informe["no_reversibles"]

    reversion = ag.revertir(uow, ejecucion_id=UUID(salida["ejecucion_id"]))
    assert reversion["completa"] is False
    assert "sin deshacer" in reversion["que_significa"]


@pytest.mark.db
def test_lo_que_declara_compensacion_se_deshace(
    uow: UnidadDeTrabajo, contexto_tenant: UUID, puertos: dict[str, Any]
) -> None:
    _proveedor(uow)
    _agente(uow)
    puertos["pasos"] = [
        {
            "herramienta": "post_contacts",
            "argumentos": {"nombre": "x"},
            "porque": "crear",
            "compensacion": {"herramienta": "delete_contacts_por_id", "argumentos": {"id": "x"}},
        }
    ]
    salida = ag.lanzar(uow, clave="califica", objetivo="crear algo")
    ag.avanzar(uow, ejecucion_id=UUID(salida["ejecucion_id"]))
    reversion = ag.revertir(uow, ejecucion_id=UUID(salida["ejecucion_id"]))

    assert reversion["revertidos"] == [1]
    assert reversion["completa"] is True


@pytest.mark.db
def test_se_revierte_en_orden_inverso(
    uow: UnidadDeTrabajo, contexto_tenant: UUID, puertos: dict[str, Any]
) -> None:
    """Los pasos se apoyan unos en otros: deshacer el primero antes que el
    tercero deja el tercero apuntando a algo que ya no está."""
    _proveedor(uow)
    _agente(uow)
    puertos["pasos"] = [
        {
            "herramienta": "post_contacts",
            "argumentos": {"n": i},
            "porque": str(i),
            "compensacion": {"herramienta": "delete_contacts_por_id", "argumentos": {"n": i}},
        }
        for i in (1, 2)
    ]
    salida = ag.lanzar(uow, clave="califica", objetivo="dos cosas")
    ag.avanzar(uow, ejecucion_id=UUID(salida["ejecucion_id"]))
    ag.avanzar(uow, ejecucion_id=UUID(salida["ejecucion_id"]))
    puertos["invocaciones"].clear()

    ag.revertir(uow, ejecucion_id=UUID(salida["ejecucion_id"]))
    orden = [i["argumentos"].get("n") for i in puertos["invocaciones"]]
    assert orden == [2, 1]


@pytest.mark.db
def test_la_actuacion_enseña_el_plan_y_lo_ejecutado_juntos(
    uow: UnidadDeTrabajo, contexto_tenant: UUID, puertos: dict[str, Any]
) -> None:
    """Ver solo lo que pasó no dice dónde se torció; ver solo el plan no dice qué
    llegó a hacerse."""
    _proveedor(uow)
    _agente(uow)
    salida = ag.lanzar(uow, clave="califica", objetivo="algo")
    informe = ag.actuacion(uow.db, uow.tenant_id, UUID(salida["ejecucion_id"]))
    assert informe["pasos"][0]["porque"]
    assert informe["pasos"][0]["estado"] == "planificado"


# ── Asistencia (CRM-04.02.02.05, CRM-03.01.02.04) ─────────────────────────


@pytest.mark.db
def test_sin_articulos_no_se_sugiere_respuesta(uow: UnidadDeTrabajo, contexto_tenant: UUID) -> None:
    """Un agente que recibe una sugerencia sin fuentes la manda igual, porque
    tiene al cliente esperando."""
    from services.intelligence import asistencia as asis

    salida = asis.sugerir_respuesta(
        uow, caso_id=uuid4(), pregunta="¿Cómo devuelvo esto?", fragmentos=[]
    )
    assert salida["hay_sugerencia"] is False
    assert salida["articulos"] == []


def test_con_pocas_senales_no_se_recomienda_nada(db: Any, tenant_id: UUID) -> None:
    """Lo que saldría es el orden por defecto del producto disfrazado de consejo,
    que es peor que callar porque parece que alguien lo pensó."""
    from services.intelligence import asistencia as asis

    salida = asis.proximos_pasos(db, tenant_id, senales={"dias_sin_contacto": 40})
    assert salida["concluyente"] is False
    assert salida["pasos"] == []


def test_cada_paso_recomendado_lleva_el_dato_que_lo_justifica(db: Any, tenant_id: UUID) -> None:
    from services.intelligence import asistencia as asis

    salida = asis.proximos_pasos(
        db,
        tenant_id,
        senales={
            "dias_sin_contacto": 40,
            "presupuesto_abierto": True,
            "reunion_de_cierre": False,
            "patrocinador_identificado": False,
        },
    )
    assert salida["concluyente"] is True
    assert all(p["porque"] for p in salida["pasos"])
    assert salida["pasos"][0]["urgencia"] == "alta"
