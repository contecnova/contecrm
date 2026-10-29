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
        # `falla` es la herramienta que revienta; `rechaza` es el destino que
        # contesta 4xx. Son dos caminos distintos en `avanzar` y con uno solo
        # se probaba la mitad.
        "rechaza": False,
    }

    def _planificar(**kw: Any) -> dict[str, Any]:
        estado["ultimo_plan"] = kw
        return {"pasos": estado["pasos"], "tokens_entrada": 100, "tokens_salida": 50}

    def _invocar(**kw: Any) -> dict[str, Any]:
        estado["invocaciones"].append(kw)
        if estado["falla"]:
            raise RuntimeError("la herramienta ha fallado")
        # El invocador de verdad **no lanza** cuando el destino contesta 4xx:
        # devuelve `ok: False` con el cuerpo, porque un rechazo es información
        # para el agente. El doble tiene que poder hacer lo mismo, o se prueba
        # sólo la mitad.
        if estado["rechaza"]:
            return {"estado": 401, "ok": False, "datos": {"detail": "Falta autenticación"}}
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


@pytest.mark.db
def test_una_clave_borrada_se_puede_volver_a_declarar(
    uow: UnidadDeTrabajo, contexto_tenant: UUID, puertos: dict[str, Any]
) -> None:
    """La clave es única por tenant y el índice cuenta las filas borradas.

    Sin mirar la papelera, declarar otra vez no encontraba nada, intentaba
    insertar y chocaba con un 409 que habla de «un registro que ya existe» y
    que quien lo lee no puede ver. Al sembrado le pasa igual: lo cuenta como
    duplicado y deja el tenant sin agente sin que nada lo diga.

    Y vuelve con **lo que se declara ahora**: resucitar con la configuración
    vieja sería devolver permisos que alguien quitó.
    """
    from crmcore.datos.papelera import borrar

    fila = _agente(uow, clave="revivible", permisos=["contact:read", "contact:write"])
    borrar(uow.db, fila, objeto="agente_ia")
    uow.db.flush()

    vuelta = _agente(uow, clave="revivible", permisos=["contact:read"])
    assert vuelta.id == fila.id, "no se ha revivido la misma fila: se ha creado otra"
    assert vuelta.esta_borrado is False
    assert vuelta.permisos == ["contact:read"]


@pytest.mark.db
def test_un_agente_sin_herramientas_lo_dice_en_vez_de_planificar_nada(
    uow: UnidadDeTrabajo, contexto_tenant: UUID, puertos: dict[str, Any]
) -> None:
    """Medido el 29-10-2026: ningún agente declarado tenía herramientas.

    Se llamaba al modelo igual, con la lista vacía; no podía proponer ningún
    paso; y esto devolvía un plan de cero pasos con el aviso en blanco. La
    pantalla decía que había ido bien y no se había hecho nada — y la llamada
    se pagaba.
    """
    _proveedor(uow)
    _agente(uow, clave="pelado", herramientas=[])
    with pytest.raises(Conflicto) as caso:
        ag.lanzar(uow, clave="pelado", objetivo="lo que sea")
    assert caso.value.error_code == "agente.sin_herramientas"
    # Y ni se ha llegado a invocar nada: no se paga por saber que no puede
    # haber plan.
    assert puertos["invocaciones"] == []


@pytest.mark.db
def test_una_herramienta_que_contesta_401_no_es_un_paso_hecho(
    uow: UnidadDeTrabajo, contexto_tenant: UUID, puertos: dict[str, Any]
) -> None:
    """La promesa entera de esta pantalla es poder ver qué ha hecho el agente.

    El destino contestaba 401 —el agente llamaba sin identidad— y el paso se
    guardaba como «hecho» con el error dentro del resultado: verde en pantalla
    y verde en la auditoría. Lo único que delataba el problema era la
    conclusión del modelo, «necesito credenciales válidas», que se lee como un
    límite del modelo y es un fallo de configuración.
    """
    _proveedor(uow)
    _agente(uow)
    puertos["rechaza"] = True
    salida = ag.lanzar(uow, clave="califica", objetivo="algo")
    resultado = ag.avanzar(uow, ejecucion_id=UUID(salida["ejecucion_id"]))
    assert resultado["estado"] == "fallido"
    # Y se dice QUÉ contestó, no sólo que no pudo: «401» a secas no se arregla.
    assert "401" in resultado["error"]
    assert "autenticación" in resultado["error"]
    ejecucion = uow.db.get(ag.EjecucionAgente, UUID(salida["ejecucion_id"]))
    assert ejecucion.estado == "fallida"


# ── El bucle iterativo (CRM-05.02.03.01) ──────────────────────────────────
#
# Un plan cerrado no puede expresar un objetivo cuya segunda mitad depende de la
# primera: «qué cuentas están en riesgo y, de cada una, mira su facturación» se
# escribiría sobre cuentas que todavía no se sabe cuáles son. Lo que estas
# pruebas vigilan no es que el bucle funcione, sino que **no se lleve por delante
# los tres controles** al iterar: el tope, el presupuesto y la aprobación.


@pytest.fixture
def bucle() -> Any:
    """Un continuador controlado: devuelve los pasos que se le pongan, en orden,
    y guarda lo que se le mandó en cada vuelta."""
    estado: dict[str, Any] = {"proximos": [], "recibido": [], "porque_para": "ya está"}

    def _siguiente(**kw: Any) -> dict[str, Any]:
        estado["recibido"].append(kw)
        if estado["proximos"]:
            return {"paso": estado["proximos"].pop(0), "tokens_entrada": 10, "tokens_salida": 5}
        return {
            "paso": None,
            "porque": estado["porque_para"],
            "conclusion": "Tres cuentas en riesgo",
            "tokens_entrada": 10,
            "tokens_salida": 5,
        }

    ag.registrar_continuador(_siguiente)
    yield estado
    ag.registrar_continuador(None)  # type: ignore[arg-type]


def _paso(n: int) -> dict[str, Any]:
    return {"herramienta": "get_contacts", "argumentos": {"n": n}, "porque": f"vuelta {n}"}


@pytest.mark.db
def test_el_iterativo_decide_con_el_resultado_del_anterior_delante(
    uow: UnidadDeTrabajo, contexto_tenant: UUID, puertos: dict[str, Any], bucle: dict[str, Any]
) -> None:
    """Esto es TODO lo que distingue al bucle de un plan cerrado: lo que se le
    manda para decidir el segundo paso incluye lo que devolvió el primero. Sin
    esta propiedad el modo iterativo es un plan cerrado con más llamadas."""
    _proveedor(uow)
    _agente(uow, modo="iterativo")
    bucle["proximos"] = [_paso(1), _paso(2)]
    salida = ag.lanzar(uow, clave="califica", objetivo="mira y luego decide")
    ejecucion_id = UUID(salida["ejecucion_id"])

    # Vuelta 1: ejecuta el paso que se decidió al lanzar.
    ag.avanzar(uow, ejecucion_id=ejecucion_id)
    # Vuelta 2: no queda paso, así que decide uno nuevo.
    segunda = ag.avanzar(uow, ejecucion_id=ejecucion_id)

    assert segunda["paso_decidido"]["orden"] == 2
    # Al decidir el segundo, el primero ya está hecho Y con su resultado.
    hechos = bucle["recibido"][-1]["hechos"]
    assert [h["estado"] for h in hechos] == ["hecho"]
    assert hechos[0]["resultado"] == {"ok": True}
    # Y al lanzar no había nada hecho: el primer paso se decidió a ciegas, que
    # es lo correcto, y no con los resultados de una ejecución anterior.
    assert bucle["recibido"][0]["hechos"] == []


@pytest.mark.db
def test_el_paso_del_bucle_se_guarda_antes_de_ejecutarse(
    uow: UnidadDeTrabajo, contexto_tenant: UUID, puertos: dict[str, Any], bucle: dict[str, Any]
) -> None:
    """La vuelta que decide no ejecuta. Si decidiera y ejecutara de una, entre
    las dos cosas no cabría ni el apagado ni la aprobación, que es justo donde
    tienen que caber."""
    _proveedor(uow)
    _agente(uow, modo="iterativo")
    bucle["proximos"] = [_paso(1), _paso(2)]
    salida = ag.lanzar(uow, clave="califica", objetivo="algo")
    ejecucion_id = UUID(salida["ejecucion_id"])
    ag.avanzar(uow, ejecucion_id=ejecucion_id)
    antes = len(puertos["invocaciones"])

    decidida = ag.avanzar(uow, ejecucion_id=ejecucion_id)

    assert decidida["avanzado"] is False
    assert len(puertos["invocaciones"]) == antes, "la vuelta que piensa no puede ejecutar"
    assert decidida["paso_decidido"]["estado"] == "planificado"


@pytest.mark.db
def test_un_paso_del_bucle_que_necesita_aprobacion_espera_igual(
    uow: UnidadDeTrabajo, contexto_tenant: UUID, puertos: dict[str, Any], bucle: dict[str, Any]
) -> None:
    """El control humano no se salta por iterar. Era el riesgo real de meter un
    bucle: que el paso decidido sobre la marcha se ejecutara sin pasar por donde
    pasa el de un plan."""
    _proveedor(uow)
    _agente(uow, modo="iterativo", aprobacion_por_riesgo=["escritura", "destructivo"])
    bucle["proximos"] = [{"herramienta": "post_contacts", "argumentos": {}, "porque": "escribir"}]
    salida = ag.lanzar(uow, clave="califica", objetivo="escribe algo")
    assert salida["esperando_aprobacion"] == [1]
    resultado = ag.avanzar(uow, ejecucion_id=UUID(salida["ejecucion_id"]))
    assert resultado["avanzado"] is False
    assert puertos["invocaciones"] == []


@pytest.mark.db
def test_el_bucle_para_cuando_el_modelo_dice_que_ya_esta_y_con_SU_motivo(
    uow: UnidadDeTrabajo, contexto_tenant: UUID, puertos: dict[str, Any], bucle: dict[str, Any]
) -> None:
    """«No queda ningún paso» no distingue entre cumplido y rendido. El motivo
    que queda guardado es el único rastro de por qué el bucle paró donde paró."""
    _proveedor(uow)
    _agente(uow, modo="iterativo")
    bucle["porque_para"] = "Ninguna cuenta cumple el criterio"
    salida = ag.lanzar(uow, clave="califica", objetivo="busca")
    # No se ha decidido ni un paso: el modelo ha dicho que no hace falta.
    assert salida["pasos"] == []
    ejecucion_id = UUID(salida["ejecucion_id"])
    final = ag.avanzar(uow, ejecucion_id=ejecucion_id)
    assert final["terminada"] is True
    assert final["porque"] == "Ninguna cuenta cumple el criterio"
    assert final["conclusion"] == "Tres cuentas en riesgo"
    assert ag.actuacion(uow.db, uow.tenant_id, ejecucion_id)["motivo_fin"] == (
        "Ninguna cuenta cumple el criterio"
    )


@pytest.mark.db
def test_un_bucle_que_no_para_solo_lo_para_el_tope(
    uow: UnidadDeTrabajo, contexto_tenant: UUID, puertos: dict[str, Any], bucle: dict[str, Any]
) -> None:
    """El caso malo plantado: un modelo que pide un paso más indefinidamente.
    Es el incidente número uno de un agente iterativo, y el tope es lo único que
    lo separa de una factura."""
    _proveedor(uow)
    _agente(uow, modo="iterativo", max_acciones=3)

    def _sin_fin(**kw: Any) -> dict[str, Any]:
        return {"paso": _paso(len(kw["hechos"]) + 1), "tokens_entrada": 1, "tokens_salida": 1}

    ag.registrar_continuador(_sin_fin)
    salida = ag.lanzar(uow, clave="califica", objetivo="no pares")
    ejecucion_id = UUID(salida["ejecucion_id"])
    vueltas = 0
    while vueltas < 50:
        vueltas += 1
        resultado = ag.avanzar(uow, ejecucion_id=ejecucion_id)
        if resultado.get("terminada") or resultado.get("detenida"):
            break
    assert vueltas < 50, "el bucle no ha parado solo"
    assert len(puertos["invocaciones"]) <= 3
    ejecucion = uow.db.get(ag.EjecucionAgente, ejecucion_id)
    assert ejecucion.motivo_fin == "Tope de acciones alcanzado"


@pytest.mark.db
def test_el_presupuesto_se_mira_en_cada_vuelta_y_no_solo_al_lanzar(
    uow: UnidadDeTrabajo, contexto_tenant: UUID, puertos: dict[str, Any], bucle: dict[str, Any]
) -> None:
    """Un bucle con el presupuesto mirado una sola vez al principio es un bucle
    sin presupuesto: donde se gasta es en cada vuelta."""
    _proveedor(uow)
    _agente(uow, modo="iterativo", max_acciones=20, presupuesto_tokens_dia=1_000)
    bucle["proximos"] = [_paso(1), _paso(2), _paso(3)]
    salida = ag.lanzar(uow, clave="califica", objetivo="gasta")
    ejecucion_id = UUID(salida["ejecucion_id"])
    # Se gasta el presupuesto por fuera, como lo gastaría otra ejecución del
    # mismo agente mientras ésta sigue en marcha.
    ejecucion = uow.db.get(ag.EjecucionAgente, ejecucion_id)
    ejecucion.tokens = 5_000
    uow.db.flush()

    ag.avanzar(uow, ejecucion_id=ejecucion_id)  # ejecuta el paso 1
    parada = ag.avanzar(uow, ejecucion_id=ejecucion_id)  # tocaría pensar

    assert parada["detenida"] is True
    assert "presupuesto" in parada["porque"]
    assert uow.db.get(ag.EjecucionAgente, ejecucion_id).estado == "detenida"


@pytest.mark.db
def test_un_resultado_enorme_se_recorta_y_se_dice(
    uow: UnidadDeTrabajo, contexto_tenant: UUID, puertos: dict[str, Any], bucle: dict[str, Any]
) -> None:
    """Sin recortar, en la quinta vuelta la petición es el listado cinco veces.
    Y se dice que viene cortado: un modelo que ve una lista cortada sin saberlo
    concluye que no había más."""
    _proveedor(uow)
    _agente(uow, modo="iterativo")
    puertos["grande"] = True

    def _invocar_mucho(**kw: Any) -> dict[str, Any]:
        puertos["invocaciones"].append(kw)
        return {"filas": [{"nombre": f"cuenta {i}" * 10} for i in range(500)]}

    ag.registrar_invocador(_invocar_mucho)
    bucle["proximos"] = [_paso(1), _paso(2)]
    salida = ag.lanzar(uow, clave="califica", objetivo="lista larga")
    ejecucion_id = UUID(salida["ejecucion_id"])
    ag.avanzar(uow, ejecucion_id=ejecucion_id)
    ag.avanzar(uow, ejecucion_id=ejecucion_id)

    enviado = bucle["recibido"][-1]["hechos"][0]["resultado"]
    assert enviado["recortado"] is True
    assert enviado["aviso"]
    # Contra el AJUSTE, no contra un número escrito aquí. El tope subió de
    # 2.000 a 20.000 el 29-10-2026 —con 2.000 el agente veía dos cuentas de
    # sesenta y cinco— y esta prueba se puso roja por duplicar el valor en vez
    # de leerlo. Una prueba que copia una constante se rompe cada vez que la
    # constante hace su trabajo.
    from services.intelligence.ajustes import ajustes

    assert len(enviado["muestra"]) <= ajustes().ia_caracteres_resultado_paso


@pytest.mark.db
def test_una_herramienta_que_el_bucle_pide_y_no_tiene_no_se_reintenta(
    uow: UnidadDeTrabajo, contexto_tenant: UUID, puertos: dict[str, Any], bucle: dict[str, Any]
) -> None:
    """Volver a preguntar es el bucle que se come el presupuesto pidiendo lo
    mismo una y otra vez."""
    _proveedor(uow)
    _agente(uow, modo="iterativo")
    bucle["proximos"] = [
        _paso(1),
        {"herramienta": "borrar_la_base", "argumentos": {}, "porque": "no"},
    ]
    salida = ag.lanzar(uow, clave="califica", objetivo="algo")
    ejecucion_id = UUID(salida["ejecucion_id"])
    ag.avanzar(uow, ejecucion_id=ejecucion_id)
    fallo = ag.avanzar(uow, ejecucion_id=ejecucion_id)
    assert fallo["herramientas_descartadas"] == ["borrar_la_base"]
    assert uow.db.get(ag.EjecucionAgente, ejecucion_id).estado == "fallida"


@pytest.mark.db
def test_un_modo_que_no_existe_no_se_declara(uow: UnidadDeTrabajo, contexto_tenant: UUID) -> None:
    """Texto libre en el modo acabaría en un agente guardado como «bucle» que
    planifica cerrado, y nadie miraría ahí."""
    with pytest.raises(ErrorValidacion):
        _agente(uow, modo="a_ver_que_pasa")


@pytest.mark.db
def test_el_plan_cerrado_sigue_siendo_el_de_antes(
    uow: UnidadDeTrabajo, contexto_tenant: UUID, puertos: dict[str, Any]
) -> None:
    """Los agentes ya declarados no cambian de forma de decidir porque se haya
    añadido un modo nuevo. Sin esto, la migración les cambiaría el
    comportamiento sin que nadie lo pidiera."""
    _proveedor(uow)
    agente = _agente(uow)
    assert agente.modo == "plan_cerrado"
    salida = ag.lanzar(uow, clave="califica", objetivo="algo")
    assert len(salida["pasos"]) == 1
    # Y no toca el continuador ni aunque esté registrado.
    assert "ultimo_plan" in puertos


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


# ── El invocador de verdad (CRM-05.02.03.01) ──────────────────────────────
#
# Hasta el 27-10-2026 `puerto._invocar_herramienta` lanzaba siempre: el agente
# planificaba y **no podía actuar en ningún despliegue**, con la capacidad
# constando `hecho`. Lo que sigue prueba las tres decisiones del invocador real,
# que son donde esto se rompe: de dónde salen método y ruta, dónde va cada
# argumento, y qué pasa cuando falta un hueco de la ruta.


def test_una_herramienta_sin_declarar_no_se_intenta_a_ciegas() -> None:
    """El paso guarda el NOMBRE, no la ruta. Si el agente ya no tiene esa
    herramienta no hay a qué llamar, y adivinar una ruta por el nombre es cómo
    un agente acaba llamando a algo que nadie le dio."""
    from crmcore.errors import ErrorDependencia

    from services.intelligence import puerto

    with pytest.raises(ErrorDependencia) as fallo:
        puerto._invocar_herramienta(herramienta="get_api_v1_contacts", argumentos={}, definicion={})
    assert fallo.value.error_code == "agente.herramienta_sin_declarar"


def test_cada_argumento_va_donde_la_ruta_lo_espera() -> None:
    """Camino, consulta y cuerpo salen del contrato, no del nombre del campo.

    Adivinar por el nombre es el principio de la lista escrita a mano: un
    `cuenta_id` que en una ruta va en el camino y en otra en la consulta.
    """
    from services.intelligence.puerto import _repartir_argumentos

    declarada = {
        "ruta": "/api/v1/cuentas/{cuenta_id}/contactos",
        "parametros": {
            "properties": {
                "cuenta_id": {"in": "path"},
                "limite": {"in": "query"},
                "cuerpo": {"type": "object"},
            }
        },
    }
    ruta, consulta, cuerpo = _repartir_argumentos(
        declarada, {"cuenta_id": "01a1", "limite": 10, "nota": "hola"}
    )
    assert ruta == "/api/v1/cuentas/01a1/contactos", "el valor sustituye al hueco"
    assert consulta == {"limite": 10}
    # Lo que el contrato no nombra viaja en el cuerpo si la ruta lo admite.
    assert cuerpo == {"nota": "hola"}


def test_lo_que_no_cabe_en_ningun_sitio_no_se_cuela_en_la_consulta() -> None:
    """Una ruta sin cuerpo y un argumento que no está en el contrato: se
    descarta. Mandarlo en la consulta es un 422 que el agente no sabe leer."""
    from services.intelligence.puerto import _repartir_argumentos

    declarada = {"ruta": "/api/v1/cuentas", "parametros": {"properties": {}}}
    ruta, consulta, cuerpo = _repartir_argumentos(declarada, {"inventado": 1})
    assert (ruta, consulta, cuerpo) == ("/api/v1/cuentas", {}, None)


def test_un_hueco_sin_rellenar_se_dice_y_no_se_manda() -> None:
    """Sin esto, `/cuentas/{cuenta_id}` llega al servicio con el hueco literal y
    vuelve un 404 que no explica nada — ni al agente ni a quien lo audita."""
    from crmcore.errors import ErrorDependencia

    from services.intelligence.puerto import _repartir_argumentos

    declarada = {
        "ruta": "/api/v1/cuentas/{cuenta_id}",
        "parametros": {"properties": {"cuenta_id": {"in": "path"}}},
    }
    with pytest.raises(ErrorDependencia) as fallo:
        _repartir_argumentos(declarada, {})
    assert fallo.value.error_code == "agente.ruta_incompleta"
    assert "cuenta_id" in str(fallo.value)


def test_el_agente_llama_con_SU_identidad_y_no_con_la_de_la_casa(
    monkeypatch: Any,
) -> None:
    """La identidad del agente viaja en las cabeceras firmadas.

    Un agente que llamara con las cabeceras vacías tendría el poder de «la
    casa», que no es acotable y no aparece en el rastro como nadie. Esto
    comprueba lo que se manda, que es donde se rompería sin ruido.
    """
    from crmcore.http import interno

    visto: dict[str, Any] = {}

    class _Respuesta:
        status_code = 200
        # La respuesta de verdad trae cabeceras, y de ellas sale lo que el
        # destino ha tapado o retenido. Un doble sin ellas revienta donde el
        # código sí mira, y eso dice «la pantalla está rota» cuando lo que
        # faltaba era el doble.
        headers: dict[str, str] = {}

        def json(self) -> dict[str, Any]:
            return {"items": []}

    def _request(metodo: str, url: str, **kw: Any) -> Any:
        visto.update({"metodo": metodo, "url": url, **kw})
        return _Respuesta()

    import httpx

    monkeypatch.setattr(httpx, "request", _request)
    monkeypatch.setattr(interno, "direccion_de", lambda _s: "http://party:8000")

    tenant = uuid4()
    agente_id = uuid4()
    salida = interno.invocar(
        metodo="GET",
        ruta="/api/v1/cuentas",
        parametros={"limite": 5},
        cuerpo=None,
        tenant_id=tenant,
        principal_id=agente_id,
        permisos=["account:read"],
    )
    assert salida == {"estado": 200, "ok": True, "datos": {"items": []}}
    assert visto["url"] == "http://party:8000/api/v1/cuentas"
    cabeceras = visto["headers"]
    assert cabeceras["x-crm-tenant"] == str(tenant)
    assert cabeceras["x-crm-user"] == str(agente_id)
    assert cabeceras["x-crm-permisos"] == "account:read"
    # Del vocabulario común, no de una cadena suelta: «maquina» se escribía
    # aquí y no la miraba ninguno de los dos consumidores, así que el agente
    # pasaba por persona y la compartición le devolvía cero filas.
    from crmcore.vocabularios import NO_SON_PERSONAS

    assert cabeceras["x-crm-tipo"] in NO_SON_PERSONAS
    # Nunca admin de plataforma: un error de un agente no puede tener alcance
    # de todos los clientes.
    assert cabeceras["x-crm-plataforma"] == ""


def test_un_error_del_destino_es_informacion_para_el_agente_no_una_caida(
    monkeypatch: Any,
) -> None:
    """Un 409 tiene que llegarle al modelo para que corrija en el paso
    siguiente. Convertirlo en excepción marca el paso como caído y pierde el
    porqué, que es justo lo que el agente necesitaba leer."""
    from crmcore.http import interno

    class _Respuesta:
        status_code = 409
        headers: dict[str, str] = {}

        def json(self) -> dict[str, Any]:
            return {"detail": "Ya existe un contacto con ese correo"}

    import httpx

    monkeypatch.setattr(httpx, "request", lambda *a, **k: _Respuesta())
    monkeypatch.setattr(interno, "direccion_de", lambda _s: "http://party:8000")

    salida = interno.invocar(
        metodo="POST",
        ruta="/api/v1/contactos",
        cuerpo={"email": "a@b.c"},
        tenant_id=uuid4(),
        principal_id=uuid4(),
    )
    assert salida["ok"] is False
    assert salida["estado"] == 409
    assert "Ya existe" in salida["datos"]["detail"]


def test_un_campo_tapado_se_le_dice_al_agente_en_vez_de_colarselo(
    monkeypatch: Any,
) -> None:
    """Un valor enmascarado tiene la FORMA de un dato, y se cita como si lo fuera.

    Medido el 29-10-2026: el agente preguntó por tres cuentas y contestó que se
    llamaban «··············tora», «··cosa» y «·············elta». Con
    seguridad, porque nada en el cuerpo decía lo contrario — el aviso viajaba
    en una cabecera y `invocar` sólo leía el cuerpo.

    Retenido y tapado se dicen **aparte**: lo retenido no viene y se ve el
    hueco; lo tapado viene y parece bueno.
    """
    from crmcore.http import interno

    class _Respuesta:
        status_code = 200
        headers = {
            "x-campos-enmascarados": "nombre,telefono",
            "x-campos-retenidos": "nif",
        }

        def json(self) -> dict[str, Any]:
            return {"items": [{"nombre": "··············tora"}]}

    import httpx

    monkeypatch.setattr(httpx, "request", lambda *a, **k: _Respuesta())
    monkeypatch.setattr(interno, "direccion_de", lambda _s: "http://party:8000")

    salida = interno.invocar(
        metodo="GET", ruta="/api/v1/cuentas", tenant_id=uuid4(), principal_id=uuid4()
    )
    assert salida["campos_tapados"] == ["nombre", "telefono"]
    assert salida["campos_no_entregados"] == ["nif"]
    # Y en palabras, porque lo que lee el modelo es texto.
    assert "nombre" in salida["aviso"] and "no se puede citar" in salida["aviso"]


def test_sin_nada_tapado_no_se_avisa_de_nada(monkeypatch: Any) -> None:
    """Un aviso que sale siempre deja de leerse."""
    from crmcore.http import interno

    class _Respuesta:
        status_code = 200
        headers: dict[str, str] = {}

        def json(self) -> dict[str, Any]:
            return {"items": []}

    import httpx

    monkeypatch.setattr(httpx, "request", lambda *a, **k: _Respuesta())
    monkeypatch.setattr(interno, "direccion_de", lambda _s: "http://party:8000")

    salida = interno.invocar(
        metodo="GET", ruta="/api/v1/cuentas", tenant_id=uuid4(), principal_id=uuid4()
    )
    assert "aviso" not in salida and "campos_tapados" not in salida


def test_los_roles_del_agente_viajan_porque_deciden_que_campos_ve(
    monkeypatch: Any,
) -> None:
    """El permiso decide si puede pedir la ruta; el rol, qué ve de la respuesta.

    Sin roles, la política de sensibilidad manda al comodín y devuelve los
    valores tapados.
    """
    from crmcore.http import interno

    visto: dict[str, Any] = {}

    class _Respuesta:
        status_code = 200
        headers: dict[str, str] = {}

        def json(self) -> dict[str, Any]:
            return {}

    import httpx

    monkeypatch.setattr(httpx, "request", lambda m, u, **kw: (visto.update(kw), _Respuesta())[1])
    monkeypatch.setattr(interno, "direccion_de", lambda _s: "http://party:8000")

    interno.invocar(
        metodo="GET",
        ruta="/api/v1/cuentas",
        tenant_id=uuid4(),
        principal_id=uuid4(),
        permisos=["account:read"],
        roles=["comercial", "admin"],
    )
    assert visto["headers"]["x-crm-roles"] == "admin,comercial"


def test_un_filtro_que_el_contrato_no_nombra_va_a_la_CONSULTA_en_un_get(
    monkeypatch: Any,
) -> None:
    """**Un filtro que no filtra es peor que no tener filtros.**

    Los filtros de un listado son nombres de columna —`?telefono__vacio=true`—
    y el contrato no los puede declarar: el conjunto cambia con el rol. Antes,
    todo lo que el contrato no nombraba se descartaba en un `GET`, así que la
    llamada salía **sin acotar** y devolvía la tabla entera. Medido el
    29-10-2026: el agente pidió los contactos sin teléfono, recibió todos los
    contactos y concluyó que el filtro estaba roto.

    Mandarlo y recibir un 422 sí dice por qué — el servidor contesta con la
    lista de los que valen. Un error que enseña es mejor que un acierto que
    miente.
    """
    from services.intelligence import puerto

    ruta, consulta, cuerpo = puerto._repartir_argumentos(
        {"metodo": "GET", "ruta": "/api/v1/contacts", "parametros": {"properties": {}}},
        {"telefono__vacio": "true"},
    )
    assert consulta == {"telefono__vacio": "true"}
    assert cuerpo is None
    assert ruta == "/api/v1/contacts"


def test_en_lo_que_escribe_lo_no_declarado_sigue_yendo_al_cuerpo(
    monkeypatch: Any,
) -> None:
    """La regla nueva es sólo para el `GET`, que no tiene cuerpo donde ponerlo.

    Sin esta prueba, el cambio se extiende al `POST` el día que alguien lo
    simplifique, y entonces un campo de un alta viajaría en la URL — donde se
    queda escrito en los registros del servidor.
    """
    from services.intelligence import puerto

    _, consulta, cuerpo = puerto._repartir_argumentos(
        {
            "metodo": "POST",
            "ruta": "/api/v1/contacts",
            "parametros": {"properties": {"cuerpo": {"type": "object"}}},
        },
        {"nombre": "Alguien"},
    )
    assert consulta == {}
    assert cuerpo == {"nombre": "Alguien"}


def test_una_ruta_que_no_atiende_nadie_no_se_manda_a_ningun_sitio() -> None:
    """Y se distingue de «el servicio no responde»: la respuesta al agente —y a
    quien lo audita— no es la misma."""
    from crmcore.errors import NoDisponible
    from crmcore.http import interno

    with pytest.raises(NoDisponible) as fallo:
        interno.invocar(
            metodo="GET",
            ruta="/api/v1/esto-no-existe-en-ninguna-tabla",
            tenant_id=uuid4(),
            principal_id=uuid4(),
        )
    assert fallo.value.error_code == "interno.ruta_sin_dueno"
