"""Previsión de ventas (CRM-03.02.01.01 a .09, CRM-03.01.01.04 y .13).

Un número de previsión solo vale si se puede explicar. Estas pruebas van
detrás de eso: que el total no esconda lo que no ha podido sumar, que el
*waterfall* separe las causas, que un ajuste sin motivo no pase, y que el cambio
de moneda sea el del día y no el de hoy.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.datos.cambio import fijar_tipo_cambio
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado
from crmcore.fechas import hoy

from services.sales import forecast
from services.sales import servicio as svc
from services.sales.modelos import Etapa, Oportunidad, Pipeline

HOY = hoy()
DESDE = HOY - timedelta(days=30)
HASTA = HOY + timedelta(days=30)


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


@pytest.fixture
def pipeline(db: Any, tenant_id: UUID) -> Pipeline:
    fila = Pipeline(tenant_id=tenant_id, clave="ventas", nombre="Ventas", por_defecto=True)
    db.add(fila)
    db.flush()
    db.add_all(
        [
            Etapa(
                tenant_id=tenant_id,
                pipeline_id=fila.id,
                clave="contacto",
                nombre="Contacto",
                orden=1,
                probabilidad=10,
                criterios_salida=[],
            ),
            Etapa(
                tenant_id=tenant_id,
                pipeline_id=fila.id,
                clave="negociacion",
                nombre="Negociación",
                orden=2,
                probabilidad=60,
            ),
        ]
    )
    db.flush()
    return fila


@pytest.fixture
def periodo(db: Any, tenant_id: UUID) -> Any:
    return forecast.abrir_periodo(db, tenant_id, clave="2026-Q1", desde=DESDE, hasta=HASTA)


def _oportunidad(
    db: Any,
    tenant_id: UUID,
    pipeline: Pipeline,
    *,
    importe: str = "1000",
    moneda: str = "EUR",
    categoria: str | None = None,
    probabilidad: int = 50,
    owner: UUID | None = None,
    estado: str = "abierta",
    fecha: date | None = None,
) -> Oportunidad:
    from sqlalchemy import select

    etapa = db.execute(
        select(Etapa).where(Etapa.pipeline_id == pipeline.id, Etapa.clave == "contacto")
    ).scalar_one()
    fila = Oportunidad(
        tenant_id=tenant_id,
        nombre="Op",
        pipeline_id=pipeline.id,
        etapa_id=etapa.id,
        importe=Decimal(importe),
        moneda=moneda,
        probabilidad=probabilidad,
        fecha_cierre=fecha or HOY,
        categoria_forecast=categoria,
        owner_id=owner,
        estado=estado,
    )
    db.add(fila)
    db.flush()
    return fila


# ── Categorías (CRM-03.02.01.01) ──────────────────────────────────────────


@pytest.mark.db
def test_las_categorias_son_datos_del_tenant(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Con la lista escrita en el código, cada organización con un «upside» en
    medio sería una versión del producto."""
    creadas = forecast.sembrar_categorias(db, tenant_id)
    assert {c.clave for c in creadas} == {"pipeline", "best_case", "commit", "cerrado"}
    # Sembrar dos veces no duplica: la segunda instalación del mismo tenant no
    # puede acabar con ocho categorías.
    assert len(forecast.sembrar_categorias(db, tenant_id)) == 4


@pytest.mark.db
def test_el_significado_no_se_deduce_del_nombre(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Deducir «commit» de la palabra rompería en cuanto alguien la traduzca."""
    forecast.sembrar_categorias(db, tenant_id)
    por_clave = {c.clave: c for c in forecast.categorias(db, tenant_id)}
    assert por_clave["commit"].cuenta_como_compromiso is True
    assert por_clave["pipeline"].cuenta_como_compromiso is False
    assert por_clave["cerrado"].terminal is True


@pytest.mark.db
def test_una_categoria_inventada_no_se_acepta(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, pipeline: Pipeline
) -> None:
    """Una errata crearía una categoría fantasma cuyo importe desaparece del
    total sin que nadie lo eche en falta: el peor error, el que resta en
    silencio."""
    forecast.sembrar_categorias(db, tenant_id)
    oportunidad = _oportunidad(db, tenant_id, pipeline)
    with pytest.raises(ErrorValidacion) as e:
        forecast.clasificar(db, oportunidad, "commmit")
    assert e.value.error_code == "forecast.categoria_desconocida"


# ── El número (CRM-03.02.01.01, .07) ──────────────────────────────────────


@pytest.mark.db
def test_el_compromiso_suma_solo_lo_que_cuenta_como_tal(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, pipeline: Pipeline, periodo: Any
) -> None:
    forecast.sembrar_categorias(db, tenant_id)
    _oportunidad(db, tenant_id, pipeline, importe="1000", categoria="commit")
    _oportunidad(db, tenant_id, pipeline, importe="5000", categoria="pipeline")

    salida = forecast.calcular(db, tenant_id, periodo_clave="2026-Q1")
    assert salida.total == Decimal("6000")
    assert salida.compromiso == Decimal("1000")


@pytest.mark.db
def test_lo_que_no_se_puede_convertir_no_se_cuenta_como_cero(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, pipeline: Pipeline, periodo: Any
) -> None:
    """Un total al que le faltan importes en silencio es peor que uno que avisa,
    porque nadie lo cuestiona."""
    forecast.sembrar_categorias(db, tenant_id)
    _oportunidad(db, tenant_id, pipeline, importe="1000", moneda="EUR")
    _oportunidad(db, tenant_id, pipeline, importe="9999", moneda="JPY")

    salida = forecast.calcular(db, tenant_id, periodo_clave="2026-Q1", moneda="EUR")
    assert salida.total == Decimal("1000")
    assert len(salida.sin_tipo_de_cambio) == 1
    assert "NO están sumadas" in forecast.a_dict(salida)["aviso"]


@pytest.mark.db
def test_la_conversion_usa_el_cambio_del_dia_de_cierre(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, pipeline: Pipeline, periodo: Any
) -> None:
    """Con el cambio de hoy, el histórico de ventas se mueve solo y el mismo
    trimestre da números distintos según cuándo se consulte."""
    forecast.sembrar_categorias(db, tenant_id)
    antiguo = HOY - timedelta(days=20)
    fijar_tipo_cambio(
        db, tenant_id=tenant_id, desde="USD", hasta="EUR", tasa=Decimal("2"), en_fecha=antiguo
    )
    fijar_tipo_cambio(
        db, tenant_id=tenant_id, desde="USD", hasta="EUR", tasa=Decimal("1"), en_fecha=HOY
    )
    _oportunidad(db, tenant_id, pipeline, importe="100", moneda="USD", fecha=antiguo)

    salida = forecast.calcular(db, tenant_id, periodo_clave="2026-Q1", moneda="EUR")
    # Con el cambio de hoy daría 100; con el del día de cierre, 200.
    assert salida.total == Decimal("200.00")


# ── Jerarquía (CRM-03.02.01.02) ───────────────────────────────────────────


@pytest.mark.db
def test_la_compania_no_es_la_suma_de_los_equipos(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, pipeline: Pipeline, periodo: Any
) -> None:
    """Una oportunidad cuyo dueño no esté en ninguna rama desaparecería de la
    suma sin que nadie lo notara, y el agujero se descubre al final del
    trimestre."""
    forecast.sembrar_categorias(db, tenant_id)
    ana, huerfano = uuid4(), uuid4()
    _oportunidad(db, tenant_id, pipeline, importe="1000", owner=ana)
    _oportunidad(db, tenant_id, pipeline, importe="500", owner=huerfano)

    salida = forecast.previsión_por_jerarquía(
        db, tenant_id, periodo_clave="2026-Q1", jerarquía={"Equipo Norte": [ana]}
    )
    assert salida["nodos"]["Equipo Norte"]["total"] == "1000.00"
    assert salida["compañía"]["total"] == "1500.00"
    assert salida["sin_asignar"] == "500.00"
    assert salida["cuadra"] is False


# ── Desglose (CRM-03.02.01.08) ────────────────────────────────────────────


@pytest.mark.db
def test_el_desglose_reparte_por_lineas_y_no_por_cabecera(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, pipeline: Pipeline, periodo: Any
) -> None:
    """Es lo único que permite que una oportunidad con software y servicios
    cuente en las dos familias por su parte."""
    from services.sales.modelos import LineaOportunidad

    forecast.sembrar_categorias(db, tenant_id)
    oportunidad = _oportunidad(db, tenant_id, pipeline, importe="1000")
    db.add_all(
        [
            LineaOportunidad(
                tenant_id=tenant_id,
                oportunidad_id=oportunidad.id,
                descripcion="Licencias",
                familia="Software",
                total=Decimal("700"),
            ),
            LineaOportunidad(
                tenant_id=tenant_id,
                oportunidad_id=oportunidad.id,
                descripcion="Implantación",
                familia="Servicios",
                total=Decimal("300"),
            ),
        ]
    )
    db.flush()

    salida = forecast.desglose(db, tenant_id, periodo_clave="2026-Q1", por="familia")
    assert salida["grupos"]["Software"]["importe"] == "700.00"
    assert salida["grupos"]["Servicios"]["importe"] == "300.00"


@pytest.mark.db
def test_no_se_desglosa_por_lo_que_no_existe(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, periodo: Any
) -> None:
    with pytest.raises(ErrorValidacion) as e:
        forecast.desglose(db, tenant_id, periodo_clave="2026-Q1", por="color")
    assert e.value.error_code == "forecast.desglose_no_soportado"


# ── Ajustes (CRM-03.02.01.03) ─────────────────────────────────────────────


@pytest.mark.db
def test_un_ajuste_sin_motivo_no_pasa(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, periodo: Any
) -> None:
    """Un ajuste sin motivo es exactamente el problema que esto viene a
    resolver: el número cambia, nadie sabe por qué, y al trimestre siguiente la
    discusión empieza de cero."""
    with pytest.raises(ErrorValidacion) as e:
        forecast.ajustar(
            db,
            tenant_id,
            periodo_clave="2026-Q1",
            categoria="commit",
            importe_ajustado=Decimal("800"),
            importe_bruto=Decimal("1000"),
            motivo="   ",
        )
    assert e.value.error_code == "forecast.ajuste_sin_motivo"


@pytest.mark.db
def test_el_ajuste_guarda_el_bruto_al_lado(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, periodo: Any
) -> None:
    """Sin el bruto no se puede medir si los ajustes acertaron, que es la única
    forma de saber si conviene hacer caso la próxima vez."""
    forecast.ajustar(
        db,
        tenant_id,
        periodo_clave="2026-Q1",
        categoria="commit",
        importe_ajustado=Decimal("800"),
        importe_bruto=Decimal("1000"),
        motivo="El cliente ha cambiado de director de compras",
    )
    filas = forecast.ajustes_de(db, tenant_id, "2026-Q1")
    assert filas[0]["bruto"] == "1000.00" and filas[0]["delta"] == "-200.00"
    assert "director de compras" in filas[0]["motivo"]


@pytest.mark.db
def test_se_puede_saber_si_el_ajuste_acerto(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, pipeline: Pipeline, periodo: Any
) -> None:
    """Es la pregunta que nadie se hace y la que decide si los ajustes sirven."""
    forecast.sembrar_categorias(db, tenant_id)
    _oportunidad(db, tenant_id, pipeline, importe="800", estado="ganada")
    forecast.ajustar(
        db,
        tenant_id,
        periodo_clave="2026-Q1",
        categoria="commit",
        importe_ajustado=Decimal("800"),
        importe_bruto=Decimal("1000"),
        motivo="ajuste a la baja",
    )
    salida = forecast.acierto_de_los_ajustes(db, tenant_id, "2026-Q1")
    assert salida["medible"] is True
    assert salida["el_ajuste_acerto"] is True


@pytest.mark.db
def test_sin_nada_cerrado_no_se_dice_que_el_ajuste_acerto(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, periodo: Any
) -> None:
    """Un cero parecería un acierto perfecto."""
    assert forecast.acierto_de_los_ajustes(db, tenant_id, "2026-Q1")["medible"] is False


# ── Cierre de periodo (CRM-03.02.01.09) ───────────────────────────────────


@pytest.mark.db
def test_cerrar_deja_foto_y_no_se_cierra_dos_veces(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, pipeline: Pipeline, periodo: Any
) -> None:
    """Un cierre sin foto es un número que ya no se puede reconstruir."""
    forecast.sembrar_categorias(db, tenant_id)
    _oportunidad(db, tenant_id, pipeline, importe="1000", categoria="commit")

    salida = forecast.cerrar_periodo(db, tenant_id, "2026-Q1")
    assert salida["totales"]["commit"] == "1000.00"
    with pytest.raises(Conflicto):
        forecast.cerrar_periodo(db, tenant_id, "2026-Q1")


@pytest.mark.db
def test_un_ajuste_sobre_un_periodo_cerrado_se_rechaza(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, periodo: Any
) -> None:
    """Cerrado significa que su número ya está en un informe que alguien ha
    mirado."""
    forecast.cerrar_periodo(db, tenant_id, "2026-Q1")
    with pytest.raises(Conflicto) as e:
        forecast.ajustar(
            db,
            tenant_id,
            periodo_clave="2026-Q1",
            categoria="commit",
            importe_ajustado=Decimal("1"),
            importe_bruto=Decimal("1"),
            motivo="da igual",
        )
    assert e.value.error_code == "forecast.periodo_cerrado"


@pytest.mark.db
def test_reabrir_exige_motivo_y_queda_contado(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, periodo: Any
) -> None:
    """Si reabrir fuera gratis, «cerrado» dejaría de significar nada."""
    forecast.cerrar_periodo(db, tenant_id, "2026-Q1")
    with pytest.raises(ErrorValidacion):
        forecast.reabrir_periodo(db, tenant_id, "2026-Q1", motivo="")

    fila = forecast.reabrir_periodo(db, tenant_id, "2026-Q1", motivo="entró una venta tarde")
    assert fila.reaperturas == 1
    assert fila.cerrado_at is None


@pytest.mark.db
def test_no_se_toca_una_fecha_dentro_de_un_periodo_cerrado(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, periodo: Any
) -> None:
    """Sin esto, cerrar sería decorativo: la foto queda pero las oportunidades
    siguen moviéndose y al trimestre siguiente nadie entiende por qué la foto no
    cuadra con el detalle."""
    forecast.cerrar_periodo(db, tenant_id, "2026-Q1")
    with pytest.raises(Conflicto):
        forecast.exigir_periodo_abierto(db, tenant_id, HOY)
    # Fuera del periodo cerrado no estorba.
    forecast.exigir_periodo_abierto(db, tenant_id, HASTA + timedelta(days=60))


# ── Instantáneas y waterfall (CRM-03.02.01.04, .05) ───────────────────────


@pytest.mark.db
def test_la_foto_guarda_el_estado_y_no_una_referencia(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, pipeline: Pipeline, periodo: Any
) -> None:
    """Si apuntara a la oportunidad, la foto cambiaría con ella y dejaría de ser
    una foto. Es el fallo clásico de los «históricos» hechos con joins."""
    forecast.sembrar_categorias(db, tenant_id)
    oportunidad = _oportunidad(db, tenant_id, pipeline, importe="1000", categoria="commit")
    foto = forecast.tomar_instantanea(db, tenant_id, "2026-Q1", etiqueta="lunes")

    oportunidad.importe = Decimal("50")
    db.flush()

    from sqlalchemy import select

    from services.sales.modelos import LineaInstantanea

    linea = db.execute(
        select(LineaInstantanea).where(LineaInstantanea.instantanea_id == foto.id)
    ).scalar_one()
    assert linea.importe == Decimal("1000")


@pytest.mark.db
def test_el_waterfall_separa_las_causas(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, pipeline: Pipeline, periodo: Any
) -> None:
    """«Hemos bajado 300.000» no dice si se ha perdido una operación grande, si
    tres se han ido al trimestre siguiente o si han bajado los importes. Cada
    causa lleva a una conversación distinta."""
    forecast.sembrar_categorias(db, tenant_id)
    estable = _oportunidad(db, tenant_id, pipeline, importe="1000", categoria="commit")
    a_perder = _oportunidad(db, tenant_id, pipeline, importe="500", categoria="commit")
    a_deslizar = _oportunidad(db, tenant_id, pipeline, importe="300", categoria="commit")

    foto_a = forecast.tomar_instantanea(db, tenant_id, "2026-Q1", etiqueta="lunes")

    estable.importe = Decimal("1200")
    a_perder.estado = "perdida"
    a_deslizar.fecha_cierre = HOY + timedelta(days=14)
    _oportunidad(db, tenant_id, pipeline, importe="900", categoria="commit")
    db.flush()

    foto_b = forecast.tomar_instantanea(db, tenant_id, "2026-Q1", etiqueta="viernes")
    salida = forecast.waterfall(db, tenant_id, foto_a.id, foto_b.id)

    assert salida["entradas"]["cuantas"] == 1
    assert salida["perdidas"]["cuantas"] == 1
    assert salida["deslizadas"]["cuantas"] == 1
    assert salida["deslizadas"]["detalle"][0]["dias"] == 14
    assert salida["variacion_de_importe"]["delta"] == "200.00"


@pytest.mark.db
def test_salir_de_la_foto_no_es_perderse(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, pipeline: Pipeline, periodo: Any
) -> None:
    """Mezclarlo inflaría la tasa de pérdida y llevaría a revisar un problema
    que no existe."""
    forecast.sembrar_categorias(db, tenant_id)
    se_va = _oportunidad(db, tenant_id, pipeline, importe="400", categoria="commit")
    foto_a = forecast.tomar_instantanea(db, tenant_id, "2026-Q1")

    se_va.fecha_cierre = HASTA + timedelta(days=90)  # al trimestre siguiente
    db.flush()
    foto_b = forecast.tomar_instantanea(db, tenant_id, "2026-Q1")

    salida = forecast.waterfall(db, tenant_id, foto_a.id, foto_b.id)
    assert salida["salidas"]["cuantas"] == 1
    assert salida["perdidas"]["cuantas"] == 0


@pytest.mark.db
def test_no_se_comparan_fotos_en_monedas_distintas(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, periodo: Any
) -> None:
    """Restar euros de dólares daría un waterfall precioso y falso."""
    a = forecast.tomar_instantanea(db, tenant_id, "2026-Q1", moneda="EUR")
    b = forecast.tomar_instantanea(db, tenant_id, "2026-Q1", moneda="USD")
    with pytest.raises(ErrorValidacion) as e:
        forecast.waterfall(db, tenant_id, a.id, b.id)
    assert e.value.error_code == "forecast.monedas_distintas"


# ── Deslizamiento (CRM-03.01.01.13) ───────────────────────────────────────


@pytest.mark.db
def test_un_cambio_de_fecha_sin_cambio_de_etapa_queda_anotado(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, pipeline: Pipeline, uow: Any
) -> None:
    """Es el hueco típico: `CambioEtapa` solo anota cuando la oportunidad se
    mueve, y el deslizamiento casi nunca va con un cambio de etapa."""
    oportunidad = _oportunidad(db, tenant_id, pipeline, importe="1000")
    svc.actualizar_oportunidad(uow, oportunidad.id, {"fecha_cierre": HOY + timedelta(days=21)})
    db.flush()

    historial = forecast.historial_de(db, tenant_id, oportunidad.id)
    assert historial[0]["campo"] == "fecha_cierre"
    assert historial[0]["dias_deslizados"] == 21


@pytest.mark.db
def test_el_deslizamiento_cuenta_las_veces_y_no_solo_los_dias(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, pipeline: Pipeline, periodo: Any, uow: Any
) -> None:
    """Empujada cuatro veces dos semanas no es lo mismo que movida dos meses de
    golpe: la primera es un problema de calificación."""
    oportunidad = _oportunidad(db, tenant_id, pipeline, importe="1000")
    # Dentro del periodo: la consulta filtra por la fecha de cierre FINAL, así
    # que una oportunidad empujada fuera del trimestre ya no es deslizamiento
    # de este trimestre — es una salida, y la cuenta el waterfall.
    for semanas in (1, 2, 3):
        svc.actualizar_oportunidad(
            uow, oportunidad.id, {"fecha_cierre": HOY + timedelta(weeks=semanas)}
        )
    db.flush()

    salida = forecast.deslizamiento(db, tenant_id, "2026-Q1")
    assert salida["empujadas"] == 1
    assert salida["empujadas_mas_de_una_vez"] == 1
    assert salida["detalle"][0]["veces"] == 3


@pytest.mark.db
def test_no_se_ve_el_historial_de_una_oportunidad_ajena(
    db: Any, tenant_id: UUID, otro_tenant_id: UUID, contexto_tenant: UUID, pipeline: Pipeline
) -> None:
    """Devolver una lista vacía parece inofensivo y no lo es: un 200 confirma
    que ese identificador existe en algún sitio."""
    with pytest.raises(NoEncontrado):
        forecast.historial_de(db, tenant_id, uuid4())


# ── Probabilidad manual (CRM-03.01.01.04) ─────────────────────────────────


@pytest.mark.db
def test_fijar_la_probabilidad_la_marca_como_manual(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, pipeline: Pipeline, uow: Any
) -> None:
    """Si no, el siguiente cambio de etapa la pisa y el comercial deja de
    ajustarla a la tercera vez: el dato se vuelve decorativo."""
    oportunidad = _oportunidad(db, tenant_id, pipeline, probabilidad=50)
    svc.actualizar_oportunidad(uow, oportunidad.id, {"probabilidad": 85})
    assert oportunidad.probabilidad_manual is True


# ── Tipos de cambio replicados (CRM-03.02.01.07) ──────────────────────────


@pytest.mark.db
def test_sales_tiene_su_propia_tabla_de_cambio(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """`sales` no puede leer el esquema de `tenancy`, así que la tabla vive en
    el suyo y se replica por evento. Sin esto, sumar un pipeline de diez mil
    oportunidades en cuatro monedas serían diez mil llamadas de red."""
    from crmcore.datos.cambio import TipoCambio, convertir

    fijar_tipo_cambio(
        db, tenant_id=tenant_id, desde="USD", hasta="EUR", tasa=Decimal("0.9"), en_fecha=HOY
    )
    assert convertir(
        db, tenant_id=tenant_id, importe=Decimal("100"), desde="USD", hasta="EUR", en_fecha=HOY
    ) == Decimal("90.00")
    assert TipoCambio.__tablename__ == "tipos_cambio"


@pytest.mark.db
def test_la_inversa_se_calcula_sola(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """Quien carga EUR→USD rara vez carga también USD→EUR."""
    from crmcore.datos.cambio import convertir

    fijar_tipo_cambio(
        db, tenant_id=tenant_id, desde="EUR", hasta="USD", tasa=Decimal("2"), en_fecha=HOY
    )
    assert convertir(
        db, tenant_id=tenant_id, importe=Decimal("100"), desde="USD", hasta="EUR", en_fecha=HOY
    ) == Decimal("50.00")
