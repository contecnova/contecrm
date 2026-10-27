"""Pipeline de ventas: etapas, criterios de salida, cierre y reapertura.

Cubre CRM-03.01.01.01 (oportunidad), .02 (pipelines múltiples), .03 (criterios
de salida), .05 (líneas), .09 (competidores), .12 (estancamiento) y .14 (bloqueo
tras el cierre), además de CRM-01.01.03.01 (conversión del lead) y .05 (motivos
de descarte normalizados).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion
from crmcore.fechas import hoy

from services.sales import servicio as svc
from services.sales.modelos import CambioEtapa, Etapa, LineaOportunidad, Pipeline


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    """Unidad de trabajo sobre la sesión de la prueba.

    No usa `unidad_de_trabajo()` porque esa abre su propia sesión y haría
    commit: aquí interesa compartir la transacción de la prueba para poder
    afirmar sobre el estado sin depender de lo que quede en la base.
    """
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


def _pipeline(db: Any, tenant_id: UUID, *, criterios: list[str] | None = None) -> Pipeline:
    """Un pipeline de tres etapas: la del medio exige importe y fecha."""
    pipeline = Pipeline(tenant_id=tenant_id, clave="ventas", nombre="Ventas", por_defecto=True)
    db.add(pipeline)
    db.flush()
    db.add_all(
        [
            Etapa(
                tenant_id=tenant_id,
                pipeline_id=pipeline.id,
                clave="contacto",
                nombre="Primer contacto",
                orden=1,
                probabilidad=10,
                criterios_salida=criterios
                if criterios is not None
                else ["importe", "fecha_cierre"],
                dias_estancamiento=7,
            ),
            Etapa(
                tenant_id=tenant_id,
                pipeline_id=pipeline.id,
                clave="negociacion",
                nombre="Negociación",
                orden=2,
                probabilidad=60,
            ),
            Etapa(
                tenant_id=tenant_id,
                pipeline_id=pipeline.id,
                clave="ganada",
                nombre="Ganada",
                orden=3,
                probabilidad=100,
                terminal=True,
                ganada=True,
            ),
            Etapa(
                tenant_id=tenant_id,
                pipeline_id=pipeline.id,
                clave="perdida",
                nombre="Perdida",
                orden=4,
                probabilidad=0,
                terminal=True,
                ganada=False,
            ),
        ]
    )
    db.flush()
    return pipeline


def _etapa(db: Any, pipeline: Pipeline, clave: str) -> Etapa:
    from sqlalchemy import select

    return db.execute(
        select(Etapa).where(Etapa.pipeline_id == pipeline.id, Etapa.clave == clave)
    ).scalar_one()


# ── Creación ──────────────────────────────────────────────────────────────


def test_la_oportunidad_nace_en_la_primera_etapa(db: Any, tenant_id: UUID, uow: Any) -> None:
    pipeline = _pipeline(db, tenant_id)
    oportunidad = svc.crear_oportunidad_nueva(uow, nombre="Obra nueva", importe=Decimal("15000"))

    assert oportunidad.etapa_id == _etapa(db, pipeline, "contacto").id
    # La probabilidad la hereda de la etapa, no se inventa.
    assert oportunidad.probabilidad == 10
    assert oportunidad.estado == "abierta"
    # Y queda el primer apunte del historial de etapas.
    assert db.query(CambioEtapa).filter_by(oportunidad_id=oportunidad.id).count() == 1


def test_el_codigo_es_correlativo_por_tenant_y_ano(db: Any, tenant_id: UUID, uow: Any) -> None:
    _pipeline(db, tenant_id)
    a = svc.crear_oportunidad_nueva(uow, nombre="Una")
    b = svc.crear_oportunidad_nueva(uow, nombre="Otra")
    anio = hoy(db).year
    assert a.codigo == f"OPP-{anio}-00001"
    assert b.codigo == f"OPP-{anio}-00002"


def test_el_importe_ponderado_sale_de_la_probabilidad(db: Any, tenant_id: UUID, uow: Any) -> None:
    _pipeline(db, tenant_id)
    oportunidad = svc.crear_oportunidad_nueva(uow, nombre="X", importe=Decimal("10000"))
    oportunidad.probabilidad = 30
    assert oportunidad.importe_ponderado == Decimal("3000")


# ── Criterios de salida ───────────────────────────────────────────────────


def test_no_se_avanza_sin_cumplir_los_criterios(db: Any, tenant_id: UUID, uow: Any) -> None:
    """CRM-03.01.01.03: es lo que hace que la previsión signifique algo.

    Sin criterios, una oportunidad llega a «negociación» sin importe ni fecha y
    el pipeline suma números que nadie se cree.
    """
    pipeline = _pipeline(db, tenant_id)
    oportunidad = svc.crear_oportunidad_nueva(uow, nombre="Sin datos")

    with pytest.raises(ErrorValidacion) as exc:
        svc.cambiar_etapa(uow, oportunidad.id, etapa_id=_etapa(db, pipeline, "negociacion").id)

    assert exc.value.error_code == "sales.criterios_salida_incumplidos"
    campos = {e["campo"] for e in exc.value.errores}
    assert campos == {"importe", "fecha_cierre"}


def test_con_los_criterios_cumplidos_se_avanza(db: Any, tenant_id: UUID, uow: Any) -> None:
    pipeline = _pipeline(db, tenant_id)
    oportunidad = svc.crear_oportunidad_nueva(
        uow, nombre="Completa", importe=Decimal("5000"), fecha_cierre=hoy(db)
    )
    svc.cambiar_etapa(uow, oportunidad.id, etapa_id=_etapa(db, pipeline, "negociacion").id)

    assert oportunidad.etapa_id == _etapa(db, pipeline, "negociacion").id
    # La probabilidad sigue a la etapa porque no había ajuste manual.
    assert oportunidad.probabilidad == 60


def test_forzar_salta_los_criterios_y_deja_constancia(db: Any, tenant_id: UUID, uow: Any) -> None:
    """`forzar` existe para la carga de históricos, que nunca los cumplen."""
    pipeline = _pipeline(db, tenant_id)
    oportunidad = svc.crear_oportunidad_nueva(uow, nombre="Histórica")
    svc.cambiar_etapa(
        uow, oportunidad.id, etapa_id=_etapa(db, pipeline, "negociacion").id, forzar=True
    )
    db.flush()

    cambio = (
        db.query(CambioEtapa)
        .filter_by(oportunidad_id=oportunidad.id)
        .order_by(CambioEtapa.created_at.desc(), CambioEtapa.id.desc())
        .first()
    )
    assert cambio.motivo == "carga forzada"


def test_la_probabilidad_ajustada_a_mano_no_se_pisa(db: Any, tenant_id: UUID, uow: Any) -> None:
    """Si el comercial la ajustó, la etapa no se la lleva por delante.

    Es su valoración del caso concreto, y sustituirla por el valor de tabla
    borra información que el sistema no tiene.

    El ajuste se hace por el camino real y no tocando el atributo: lo que marca
    la probabilidad como manual es pasar por el servicio (CRM-03.01.01.04).
    Antes se deducía comparando con la probabilidad de la etapa de origen, y esa
    heurística fallaba por los dos lados —un ajuste que coincidiera con la etapa
    se perdía, y uno que no coincidiera se arrastraba para siempre—.
    """
    pipeline = _pipeline(db, tenant_id, criterios=[])
    oportunidad = svc.crear_oportunidad_nueva(uow, nombre="Ajustada")
    svc.actualizar_oportunidad(uow, oportunidad.id, {"probabilidad": 25})
    svc.cambiar_etapa(uow, oportunidad.id, etapa_id=_etapa(db, pipeline, "negociacion").id)

    assert oportunidad.probabilidad == 25
    assert oportunidad.probabilidad_manual is True


def test_sin_ajuste_manual_la_probabilidad_sigue_a_la_etapa(
    db: Any, tenant_id: UUID, uow: Any
) -> None:
    """El caso normal, que la heurística anterior también podía romper."""
    pipeline = _pipeline(db, tenant_id, criterios=[])
    oportunidad = svc.crear_oportunidad_nueva(uow, nombre="Sin ajustar")
    destino = _etapa(db, pipeline, "negociacion")
    svc.cambiar_etapa(uow, oportunidad.id, etapa_id=destino.id)

    assert oportunidad.probabilidad == destino.probabilidad


# ── Cierre y reapertura ───────────────────────────────────────────────────


def test_llegar_a_una_etapa_ganadora_cierra_la_oportunidad(
    db: Any, tenant_id: UUID, uow: Any
) -> None:
    pipeline = _pipeline(db, tenant_id, criterios=[])
    oportunidad = svc.crear_oportunidad_nueva(uow, nombre="Se gana", importe=Decimal("9000"))
    svc.cambiar_etapa(uow, oportunidad.id, etapa_id=_etapa(db, pipeline, "ganada").id)

    assert oportunidad.estado == "ganada"
    assert oportunidad.probabilidad == 100
    assert oportunidad.fecha_cierre_real == hoy(db)
    assert oportunidad.bloqueada is True
    # Y se emite el evento que dispara el order-to-cash.
    assert any(e["tipo"] == "opportunity.won" for e in uow._pendientes)


def test_una_oportunidad_cerrada_no_se_edita(db: Any, tenant_id: UUID, uow: Any) -> None:
    """CRM-03.01.01.14: sus números ya están en un informe que alguien miró."""
    pipeline = _pipeline(db, tenant_id, criterios=[])
    oportunidad = svc.crear_oportunidad_nueva(uow, nombre="Cerrada", importe=Decimal("100"))
    svc.cambiar_etapa(uow, oportunidad.id, etapa_id=_etapa(db, pipeline, "ganada").id)

    with pytest.raises(Conflicto) as exc:
        svc.actualizar_oportunidad(uow, oportunidad.id, {"importe": Decimal("999999")})
    assert exc.value.error_code == "sales.oportunidad_bloqueada"


def test_reabrir_exige_motivo_y_emite_evento(db: Any, tenant_id: UUID, uow: Any) -> None:
    """Quien consumió el cierre tiene que poder deshacerlo."""
    pipeline = _pipeline(db, tenant_id, criterios=[])
    oportunidad = svc.crear_oportunidad_nueva(uow, nombre="Vuelve", importe=Decimal("100"))
    svc.cambiar_etapa(uow, oportunidad.id, etapa_id=_etapa(db, pipeline, "ganada").id)

    with pytest.raises(ErrorValidacion):
        svc.reabrir(
            uow, oportunidad.id, etapa_id=_etapa(db, pipeline, "negociacion").id, motivo="  "
        )

    svc.reabrir(
        uow,
        oportunidad.id,
        etapa_id=_etapa(db, pipeline, "negociacion").id,
        motivo="el cliente retoma el proyecto en septiembre",
    )
    assert oportunidad.estado == "abierta"
    assert oportunidad.bloqueada is False
    assert oportunidad.reaperturas == 1
    assert any(e["tipo"] == "opportunity.reopened" for e in uow._pendientes)


def test_no_se_reabre_en_una_etapa_terminal(db: Any, tenant_id: UUID, uow: Any) -> None:
    pipeline = _pipeline(db, tenant_id, criterios=[])
    oportunidad = svc.crear_oportunidad_nueva(uow, nombre="X", importe=Decimal("1"))
    svc.cambiar_etapa(uow, oportunidad.id, etapa_id=_etapa(db, pipeline, "ganada").id)

    with pytest.raises(ErrorValidacion) as exc:
        svc.reabrir(
            uow, oportunidad.id, etapa_id=_etapa(db, pipeline, "perdida").id, motivo="error"
        )
    assert exc.value.error_code == "sales.etapa_reapertura_invalida"


# ── Líneas ────────────────────────────────────────────────────────────────


def test_el_total_de_la_cabecera_sigue_a_las_lineas(db: Any, tenant_id: UUID, uow: Any) -> None:
    """Un importe que no cuadra con sus líneas deja el pipeline sin credibilidad."""
    _pipeline(db, tenant_id, criterios=[])
    oportunidad = svc.crear_oportunidad_nueva(uow, nombre="Con líneas")

    for cantidad, precio, descuento in [(2, "100.00", 0), (3, "50.00", 10)]:
        db.add(
            LineaOportunidad(
                tenant_id=tenant_id,
                oportunidad_id=oportunidad.id,
                descripcion="línea",
                cantidad=Decimal(cantidad),
                precio_unitario=Decimal(precio),
                descuento_pct=Decimal(descuento),
                total=svc.calcular_linea(Decimal(cantidad), Decimal(precio), Decimal(descuento)),
            )
        )
    db.flush()
    total = svc.recalcular_total(db, oportunidad)
    # 2×100 = 200, más 3×50 con 10 % = 135
    assert total == Decimal("335.00")
    assert oportunidad.importe == Decimal("335.00")


def test_el_redondeo_se_hace_una_sola_vez() -> None:
    """Redondear en cada paso acumula diferencias que no cuadran con la factura."""
    assert svc.calcular_linea(Decimal(3), Decimal("33.333"), Decimal(0)) == Decimal("100.00")
    assert svc.calcular_linea(Decimal(1), Decimal("10.00"), Decimal("33.333")) == Decimal("6.67")


# ── Estancamiento ─────────────────────────────────────────────────────────


def test_el_estancamiento_usa_el_umbral_de_cada_etapa(db: Any, tenant_id: UUID, uow: Any) -> None:
    """CRM-03.01.01.12: tres semanas en «negociación» puede ser normal."""
    _pipeline(db, tenant_id, criterios=[])
    oportunidad = svc.crear_oportunidad_nueva(uow, nombre="Parada")
    # La etapa «contacto» declara 7 días; se retrasa la entrada 10 días.
    oportunidad.etapa_desde = datetime.now(timezone.utc) - timedelta(days=10)
    db.flush()

    estancadas = svc.oportunidades_estancadas(db, tenant_id)
    assert [e["nombre"] for e in estancadas] == ["Parada"]
    assert estancadas[0]["limite"] == 7 and estancadas[0]["dias_en_etapa"] >= 10


# ── Leads ─────────────────────────────────────────────────────────────────


def test_el_sla_corre_desde_la_entrada_no_desde_la_asignacion(
    db: Any, tenant_id: UUID, uow: Any
) -> None:
    """Contarlo desde la asignación permitiría cumplirlo siempre asignando tarde."""
    lead = svc.crear_lead(uow, nombre="Ana", empresa="ACME", email="ana@acme.es")
    assert lead.sla_primera_respuesta_at is not None
    margen = lead.sla_primera_respuesta_at - lead.created_at if lead.created_at else None
    # `created_at` lo pone el servidor en el flush; si aún no está, se compara
    # con ahora, que es equivalente para lo que se quiere comprobar.
    referencia = margen or (lead.sla_primera_respuesta_at - datetime.now(timezone.utc))
    assert timedelta(hours=3) < referencia < timedelta(hours=5)


def test_la_primera_respuesta_es_idempotente(db: Any, tenant_id: UUID, uow: Any) -> None:
    lead = svc.crear_lead(uow, nombre="Ana")
    svc.registrar_primera_respuesta(db, lead.id)
    primera = lead.primera_respuesta_at
    svc.registrar_primera_respuesta(db, lead.id)
    assert lead.primera_respuesta_at == primera


def test_el_sla_incumplido_queda_marcado(db: Any, tenant_id: UUID, uow: Any) -> None:
    lead = svc.crear_lead(uow, nombre="Tarde")
    lead.sla_primera_respuesta_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db.flush()
    svc.registrar_primera_respuesta(db, lead.id)
    assert lead.sla_incumplido is True


def test_el_motivo_de_descarte_es_de_lista_cerrada(db: Any, tenant_id: UUID, uow: Any) -> None:
    """Lo que se quiere es contar, y el texto libre no se puede agrupar."""
    lead = svc.crear_lead(uow, nombre="Descartable")
    with pytest.raises(ErrorValidacion) as exc:
        svc.descartar_lead(uow, lead.id, motivo="no me gusta")
    assert exc.value.error_code == "sales.motivo_descarte_invalido"

    svc.descartar_lead(uow, lead.id, motivo="sin_presupuesto", nota="vuelven en enero")
    assert lead.estado == "descartado"
    # Y se programa su vuelta a la cola: un «ahora no» no es un no para siempre.
    assert lead.reciclar_at is not None


def test_la_conversion_conserva_la_traza(db: Any, tenant_id: UUID, uow: Any) -> None:
    """CRM-01.01.03.01: sin la traza, la atribución es una estimación."""
    from crmcore.ids import nuevo_id

    _pipeline(db, tenant_id, criterios=[])
    lead = svc.crear_lead(uow, nombre="Ana", empresa="ACME", origen="feria")
    cuenta_id, contacto_id = nuevo_id(), nuevo_id()

    lead, oportunidad = svc.convertir_lead(
        uow,
        lead.id,
        cuenta_id=cuenta_id,
        contacto_id=contacto_id,
        nombre_oportunidad="ACME — primer proyecto",
        importe=Decimal("20000"),
    )

    assert lead.estado == "convertido"
    assert lead.cuenta_id == cuenta_id
    assert oportunidad is not None and oportunidad.lead_id == lead.id
    assert any(e["tipo"] == "lead.converted" for e in uow._pendientes)


def test_no_se_convierte_dos_veces(db: Any, tenant_id: UUID, uow: Any) -> None:
    from crmcore.ids import nuevo_id

    _pipeline(db, tenant_id, criterios=[])
    lead = svc.crear_lead(uow, nombre="Ana")
    svc.convertir_lead(uow, lead.id, cuenta_id=nuevo_id(), crear_oportunidad=False)

    with pytest.raises(Conflicto) as exc:
        svc.convertir_lead(uow, lead.id, cuenta_id=nuevo_id())
    assert exc.value.error_code == "sales.lead_ya_convertido"


def test_no_hay_pipeline_configurado_da_un_error_util(db: Any, tenant_id: UUID, uow: Any) -> None:
    """El mensaje dice qué hacer, no solo que falta algo."""
    from crmcore.errors import NoEncontrado

    with pytest.raises(NoEncontrado) as exc:
        svc.crear_oportunidad_nueva(uow, nombre="Sin pipeline")
    assert exc.value.error_code == "sales.sin_pipeline"
    assert "Crea uno" in exc.value.mensaje


# ── CRM-00.04.01.11 · Numeración de negocio por objeto ───────────────────
#
# El código que la gente dice por teléfono. Lo que había contaba filas, y
# contar falla de tres maneras que pasan todas: al borrar se repite número, dos
# altas simultáneas piden el mismo, y una carga histórica con códigos propios
# deja el recuento sin relación con el último emitido.


def test_borrar_una_oportunidad_no_repite_su_codigo_crm_00_04_01_11(
    db: Any, tenant_id: UUID, uow: Any
) -> None:
    """**El caso que el recuento no sabe resolver.**

    Con un contador que cuenta filas: se crean dos, se borra una, quedan una y
    la siguiente vuelve a pedir el 2 — el mismo código que ya tiene impreso el
    cliente en una oferta. Con un contador de verdad, el 2 no vuelve.
    """
    from services.sales.modelos import Oportunidad

    _pipeline(db, tenant_id)
    una = svc.crear_oportunidad_nueva(uow, nombre="Una")
    dos = svc.crear_oportunidad_nueva(uow, nombre="Dos")
    db.flush()
    assert una.codigo != dos.codigo, (una.codigo, dos.codigo)

    # Se borra la segunda, que es lo que hacía repetir el número.
    db.delete(db.get(Oportunidad, dos.id))
    db.flush()

    tres = svc.crear_oportunidad_nueva(uow, nombre="Tres")
    db.flush()
    assert (
        tres.codigo != dos.codigo
    ), f"«{tres.codigo}» repite un código ya emitido: el contador está contando filas"


def test_el_patron_del_codigo_lo_decide_el_cliente_crm_00_04_01_11(
    db: Any, tenant_id: UUID, uow: Any
) -> None:
    """`OPP-2026-00123` es una convención, no una ley: hay clientes que numeran
    por delegación y otros que arrastran el formato del sistema del que vienen
    —y tiene que seguir siendo el mismo para que sus referencias de veinte años
    no se queden huérfanas."""
    from crmcore import numeracion

    _pipeline(db, tenant_id)
    numeracion.declarar(
        db,
        tenant_id,
        objeto="oportunidad",
        patron="NEG/{anio_corto}/{secuencia}",
        relleno=3,
        reinicio="anual",
        empezar_en=41,
    )
    nueva = svc.crear_oportunidad_nueva(uow, nombre="Con su formato")
    db.flush()
    assert nueva.codigo.startswith("NEG/"), nueva.codigo
    assert nueva.codigo.endswith("/042"), nueva.codigo


def test_el_contador_no_se_puede_bajar_por_la_api_crm_00_04_01_11(db: Any, tenant_id: UUID) -> None:
    """Es la única forma de hacer daño desde esa pantalla: bajarlo repetiría
    códigos que ya están impresos en ofertas y albaranes."""
    from crmcore import numeracion

    numeracion.declarar(
        db,
        tenant_id,
        objeto="pedido",
        patron="PED-{anio}-{secuencia}",
        reinicio="anual",
        empezar_en=100,
    )
    fila = numeracion.declarar(
        db, tenant_id, objeto="pedido", patron="PED-{anio}-{secuencia}", reinicio="anual"
    )
    # Sin `empezar_en`, cambiar el patrón NO toca el contador.
    assert fila.ultimo == 100, fila.ultimo
