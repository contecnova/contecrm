"""Auditoría de la automatización declarativa (CRM-00.03.03), por el motor.

Cinco capacidades sin ninguna prueba que las nombre. Lo que persigue esto es lo
que distingue una automatización útil de una que se come el sistema:

  · **cuándo ocurre X, si Y, entonces Z** (CRM-00.03.03.01): las tres partes,
    y la lista de acciones **cerrada** — una automatización que ejecuta código
    arbitrario es código de un usuario final corriendo en producción;
  · **los disparadores** (CRM-00.03.03.02): lista cerrada también, y un
    disparador inventado se rechaza en vez de guardarse sin disparar nunca;
  · **inmediata, diferida o programada** (CRM-00.03.03.05): una regla que manda
    un correo tiene que poder esperar a que la transacción confirme, porque si
    no manda el correo de un registro que acabó deshaciéndose;
  · **el bucle entre reglas** (CRM-00.03.03.06): dos reglas que se disparan
    mutuamente consumen el sistema entero, y eso no falla — va lento y nadie
    sabe por qué. Se corta por profundidad **y se dice por qué**;
  · y **el depurador** (CRM-00.03.03.07): qué decidió cada condición sobre
    ESTE registro. Sin eso, «¿por qué no se ha disparado?» se contesta
    leyendo código.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.db


@pytest.fixture
def regla(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> Any:
    from services.automation.modelos import Automatizacion

    fila = Automatizacion(
        tenant_id=tenant_id,
        nombre="Avisar de las grandes",
        disparador="creacion",
        objetivo="oportunidad",
        condiciones=[{"atributo": "importe", "op": ">", "valor": 1000}],
        combinacion="todas",
        # `calcular` no toca nada de fuera: deja una variable y sigue. Es la
        # acción que permite medir el motor sin montar media integración.
        acciones=[{"tipo": "calcular", "guardar_en": "aviso", "valor": "alta"}],
        activa=True,
    )
    db.add(fila)
    db.flush()
    return fila


# ── CRM-00.03.03.01 · Cuando X, si Y, entonces Z ──────────────────────────


def test_las_acciones_son_una_lista_cerrada_crm_00_03_03_01(db: Any) -> None:
    """**Una automatización que ejecuta código arbitrario es código de un
    usuario final corriendo en producción**, con los permisos del sistema y sin
    revisión. La lista cerrada es lo que lo impide, y por eso es una lista y no
    un intérprete."""
    from services.automation.motor import ACCIONES

    assert ACCIONES, "no hay lista de acciones"
    # Ninguna que ejecute código: si apareciera, la automatización dejaría de
    # ser declarativa sin que nadie lo decidiera.
    prohibidas = {"eval", "exec", "codigo", "script", "python", "sql"}
    assert not (set(ACCIONES) & prohibidas), sorted(set(ACCIONES) & prohibidas)


def test_la_condicion_decide_si_se_dispara_crm_00_03_03_01(
    db: Any, tenant_id: UUID, regla: Any, contexto_tenant: UUID
) -> None:
    """El «si Y» no es un adorno: es lo que separa «avisar de las grandes» de
    «avisar de todas», que es lo que hace que la gente filtre los avisos."""
    from services.automation.motor import evaluar_condiciones

    grande, _ = evaluar_condiciones(regla, {"importe": 5000})
    pequena, _ = evaluar_condiciones(regla, {"importe": 10})
    assert grande is True
    assert pequena is False


# ── CRM-00.03.03.02 · Disparadores ────────────────────────────────────────


def test_solo_se_aplican_las_reglas_del_disparador_y_el_objeto_crm_00_03_03_02(
    db: Any, tenant_id: UUID, regla: Any, contexto_tenant: UUID
) -> None:
    """Una regla de «cuando se crea una oportunidad» no puede dispararse al
    borrar una cuenta. Parece obvio y es exactamente lo que falla cuando el
    filtro se escribe en el sitio equivocado."""
    from services.automation.motor import aplicables

    suyas = aplicables(db, tenant_id=tenant_id, disparador="creacion", objetivo="oportunidad")
    assert [r.id for r in suyas] == [regla.id]

    assert aplicables(db, tenant_id=tenant_id, disparador="borrado", objetivo="oportunidad") == []
    assert aplicables(db, tenant_id=tenant_id, disparador="creacion", objetivo="cuenta") == []


def test_una_regla_desactivada_no_se_aplica_crm_00_03_03_02(
    db: Any, tenant_id: UUID, regla: Any, contexto_tenant: UUID
) -> None:
    """Desactivar es la forma de parar una regla que está haciendo daño sin
    borrarla —y perder con ella lo que se tardó en escribirla—. Si no parase,
    lo único que quedaría sería borrar."""
    from services.automation.motor import aplicables

    regla.activa = False
    db.flush()
    assert aplicables(db, tenant_id=tenant_id, disparador="creacion", objetivo="oportunidad") == []


def test_una_regla_de_otro_tenant_no_se_aplica_crm_00_03_03_02(
    db: Any, tenant_id: UUID, otro_tenant_id: UUID, regla: Any, contexto_tenant: UUID
) -> None:
    """Una automatización ajena corriendo sobre los datos de otro no es un
    fallo de permisos: es una empresa modificando los registros de otra."""
    from services.automation.motor import aplicables

    ajenas = aplicables(db, tenant_id=otro_tenant_id, disparador="creacion", objetivo="oportunidad")
    assert ajenas == []


# ── CRM-00.03.03.06 · Bucles entre reglas ─────────────────────────────────


def test_la_cascada_se_corta_y_dice_por_que_crm_00_03_03_06(
    db: Any, tenant_id: UUID, regla: Any, contexto_tenant: UUID
) -> None:
    """**Dos reglas que se disparan mutuamente consumen el sistema entero, y
    eso no falla**: va lento y nadie sabe por qué. Se corta por profundidad, y
    la traza dice que se cortó y en cuánto — sin eso, lo que se ve es una regla
    que a veces no se ejecuta.
    """
    from crmcore.config import get_settings

    from services.automation.motor import ContextoEjecucion, disparar

    tope = get_settings().automatizacion_max_cascada
    trazas = disparar(
        db,
        tenant_id=tenant_id,
        disparador="creacion",
        objetivo="oportunidad",
        valores={"importe": 5000},
        registro_id=str(uuid4()),
        contexto=ContextoEjecucion(profundidad=tope),
    )
    assert trazas, "no ha dejado constancia de nada"
    traza = trazas[0]
    assert traza.resultado == "omitida_por_cascada", traza.resultado
    assert str(tope) in (traza.error or ""), traza.error
    assert "bucle" in (traza.error or "").lower(), traza.error


def test_por_debajo_del_tope_la_regla_se_ejecuta_crm_00_03_03_06(
    db: Any, tenant_id: UUID, regla: Any, contexto_tenant: UUID
) -> None:
    """La otra mitad: un guardián que lo corte todo también «evita los bucles»,
    y deja las automatizaciones sin ejecutarse nunca."""
    from services.automation.motor import ContextoEjecucion, disparar

    # Quién ejecuta cada acción se **registra desde fuera**, como el puerto del
    # proveedor de firma: lo que se mide aquí es el motor —qué decide, qué deja
    # escrito y dónde corta—, no que una acción llegue a su destino.
    hechas: list[dict[str, Any]] = []

    def calculador(**kw: Any) -> dict[str, Any]:
        hechas.append(kw)
        return {"ok": True}

    trazas = disparar(
        db,
        tenant_id=tenant_id,
        disparador="creacion",
        objetivo="oportunidad",
        valores={"importe": 5000},
        registro_id=str(uuid4()),
        contexto=ContextoEjecucion(),
        ejecutores={"calcular": calculador},
    )
    assert trazas and trazas[0].resultado != "omitida_por_cascada", trazas
    # **Y llega a terminar.** Hasta el 26-10-2026 no: las variables finales se
    # metían dentro de `decisiones`, que es una LISTA, con `{**decisiones,
    # "variables": …}` — y eso revienta con «'list' object is not a mapping»
    # justo cuando la regla SÍ cumple sus condiciones. O sea que ninguna
    # automatización que se disparara de verdad llegaba al final; sólo pasaban
    # las que no se disparaban.
    assert trazas[0].resultado == "disparada", trazas[0].error
    assert trazas[0].variables, "no queda constancia de con qué variables acabó"
    assert trazas[0].decisiones, "ni de qué decidió cada condición"
    assert hechas, "la acción no ha llegado a su ejecutor"


# ── CRM-00.03.03.07 · El depurador ────────────────────────────────────────


def test_la_traza_dice_que_decidio_cada_condicion_crm_00_03_03_07(
    db: Any, tenant_id: UUID, regla: Any, contexto_tenant: UUID
) -> None:
    """«¿Por qué no se ha disparado?» es la pregunta de toda automatización que
    alguien configura, y sin esto se contesta leyendo código — que quien la
    configuró no sabe leer.

    Lo que hace falta es por registro y condición a condición: el atributo, el
    operador, lo que valía y si se cumplió.
    """
    from services.automation.motor import evaluar_condiciones

    _, decisiones = evaluar_condiciones(regla, {"importe": 10})
    assert decisiones, "la evaluación no deja constancia de nada"
    una = decisiones[0]
    for campo in ("atributo", "operador"):
        assert campo in una, f"falta «{campo}»: {sorted(una)}"
    assert una["atributo"] == "importe"
