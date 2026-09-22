"""Catálogo, precios, presupuestos y contratación (CRM-03.03.02).

Las pruebas van detrás de los cinco sitios donde una cotización pierde dinero sin
que nadie lo vea:

  * el precio que sale de la pantalla en vez de del motor,
  * el descuento que se aprueba mirando el porcentaje y no el margen,
  * el margen que se calcula con un coste que falta,
  * el presupuesto caducado que se acepta igual,
  * y el pedido que se da por traspasado porque la llamada no dio error.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion

from services.sales import catalogo as cat
from services.sales import presupuestos as pre


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


@pytest.fixture
def caja(db: Any, tenant_id: UUID) -> cat.Producto:
    fila = cat.Producto(
        tenant_id=tenant_id,
        sku="CAJA-10",
        nombre="Caja de diez",
        familia="embalaje",
        precio_base=Decimal("100.00"),
        coste=Decimal("60.00"),
    )
    db.add(fila)
    db.flush()
    return fila


def _lista(db: Any, tenant_id: UUID, **kw: Any) -> cat.ListaPrecio:
    base = {"clave": "general", "nombre": "General", "prioridad": 100}
    base.update(kw)
    fila = cat.ListaPrecio(tenant_id=tenant_id, **base)
    db.add(fila)
    db.flush()
    return fila


def _regla(db: Any, tenant_id: UUID, lista: cat.ListaPrecio, **kw: Any) -> cat.ReglaPrecio:
    base = {"accion": "descuento_pct", "valor": Decimal(10)}
    base.update(kw)
    fila = cat.ReglaPrecio(tenant_id=tenant_id, lista_id=lista.id, **base)
    db.add(fila)
    db.flush()
    return fila


# ── Motor de precios (CRM-03.03.02.03) ────────────────────────────────────


def test_sin_listas_se_cobra_el_catalogo_y_se_dice(db: Any, tenant_id: UUID, caja: Any) -> None:
    """Es la diferencia entre «le cobramos su tarifa» y «le cobramos la de
    catálogo porque no tiene tarifa»."""
    salida = cat.calcular_precio(db, tenant_id, producto_id=caja.id)
    assert salida["precio"] == "100.00"
    assert salida["de_catalogo"] is True


def test_el_precio_explica_de_donde_sale(db: Any, tenant_id: UUID, caja: Any) -> None:
    """Un precio que no se puede explicar se discute con el cliente delante, y
    entonces se acaba dando el descuento igual."""
    lista = _lista(db, tenant_id)
    _regla(db, tenant_id, lista, nombre="rebaja general", valor=Decimal(10))
    salida = cat.calcular_precio(db, tenant_id, producto_id=caja.id)
    assert salida["precio"] == "90.00"
    assert salida["reglas_aplicadas"][0]["regla"] == "rebaja general"
    assert salida["reglas_aplicadas"][0]["antes"] == "100.00"


def test_la_lista_de_una_cuenta_manda_sobre_la_general(db: Any, tenant_id: UUID, caja: Any) -> None:
    cuenta = uuid4()
    suya = _lista(db, tenant_id, clave="acme", nombre="Acme", cuenta_id=cuenta, prioridad=10)
    _regla(db, tenant_id, suya, nombre="acuerdo acme", accion="fijar", valor=Decimal("70.00"))
    general = _lista(db, tenant_id, prioridad=100)
    _regla(db, tenant_id, general, nombre="general", valor=Decimal(5))

    mia = cat.calcular_precio(db, tenant_id, producto_id=caja.id, cuenta_id=cuenta)
    otra = cat.calcular_precio(db, tenant_id, producto_id=caja.id, cuenta_id=uuid4())
    # La suya se aplica primero; la general después rebaja un 5 % sobre eso.
    assert mia["reglas_aplicadas"][0]["regla"] == "acuerdo acme"
    assert otra["precio"] == "95.00"


def test_una_regla_exclusiva_corta_el_paso(db: Any, tenant_id: UUID, caja: Any) -> None:
    """Sin ella, una promoción posterior podría bajar un precio ya pactado y
    nadie lo vería hasta la factura."""
    cuenta = uuid4()
    suya = _lista(db, tenant_id, clave="acme", nombre="Acme", cuenta_id=cuenta, prioridad=10)
    _regla(
        db,
        tenant_id,
        suya,
        nombre="precio cerrado",
        accion="fijar",
        valor=Decimal("70.00"),
        exclusiva=True,
    )
    general = _lista(db, tenant_id, prioridad=100)
    _regla(db, tenant_id, general, nombre="promo", valor=Decimal(20))

    salida = cat.calcular_precio(db, tenant_id, producto_id=caja.id, cuenta_id=cuenta)
    assert salida["precio"] == "70.00"
    assert len(salida["reglas_aplicadas"]) == 1


def test_el_escalado_por_volumen_solo_vale_desde_su_cantidad(
    db: Any, tenant_id: UUID, caja: Any
) -> None:
    lista = _lista(db, tenant_id)
    _regla(
        db,
        tenant_id,
        lista,
        nombre="a partir de 100",
        desde_cantidad=Decimal(100),
        valor=Decimal(30),
    )
    poco = cat.calcular_precio(db, tenant_id, producto_id=caja.id, cantidad=Decimal(10))
    mucho = cat.calcular_precio(db, tenant_id, producto_id=caja.id, cantidad=Decimal(150))
    assert poco["precio"] == "100.00"
    assert mucho["precio"] == "70.00"


def test_una_lista_caducada_no_se_aplica(db: Any, tenant_id: UUID, caja: Any) -> None:
    lista = _lista(db, tenant_id, hasta=date.today() - timedelta(days=1))
    _regla(db, tenant_id, lista, valor=Decimal(50))
    assert cat.calcular_precio(db, tenant_id, producto_id=caja.id)["precio"] == "100.00"


def test_el_precio_nunca_baja_de_cero(db: Any, tenant_id: UUID, caja: Any) -> None:
    """Una regla mal escrita que lo dejara en negativo produciría un abono en vez
    de una venta, y eso llega hasta la contabilidad antes de que nadie lo mire."""
    lista = _lista(db, tenant_id)
    _regla(db, tenant_id, lista, accion="descuento_importe", valor=Decimal(500))
    assert cat.calcular_precio(db, tenant_id, producto_id=caja.id)["precio"] == "0"


def test_sin_coste_no_se_inventa_un_margen(db: Any, tenant_id: UUID) -> None:
    """Un margen inventado es peor que ninguno, porque se usa para decidir
    descuentos."""
    from services.sales.catalogo import Producto

    fila = Producto(tenant_id=tenant_id, sku="X", nombre="X", precio_base=Decimal(10))
    db.add(fila)
    db.flush()
    assert cat.calcular_precio(db, tenant_id, producto_id=fila.id)["margen_pct"] is None


# ── Configuración de producto (CRM-03.03.02.02) ───────────────────────────


def test_lo_que_requiere_algo_y_no_lo_lleva_se_caza(db: Any, tenant_id: UUID, caja: Any) -> None:
    tapa = cat.Producto(tenant_id=tenant_id, sku="TAPA", nombre="Tapa", precio_base=Decimal(5))
    db.add(tapa)
    db.flush()
    db.add(
        cat.RelacionProducto(
            tenant_id=tenant_id,
            producto_id=caja.id,
            relacion="requiere",
            otro_id=tapa.id,
            motivo="La caja no cierra sin su tapa.",
        )
    )
    db.flush()
    salida = cat.comprobar_configuracion(db, tenant_id, [{"producto_id": str(caja.id)}])
    assert salida["valida"] is False
    assert salida["problemas"][0]["motivo"] == "La caja no cierra sin su tapa."


def test_una_sugerencia_no_bloquea(db: Any, tenant_id: UUID, caja: Any) -> None:
    """Una regla `sugiere` que impidiera guardar convertiría una recomendación
    comercial en un obstáculo, y lo que se hace entonces es borrarla."""
    extra = cat.Producto(tenant_id=tenant_id, sku="EXTRA", nombre="Extra", precio_base=Decimal(1))
    db.add(extra)
    db.flush()
    db.add(
        cat.RelacionProducto(
            tenant_id=tenant_id, producto_id=caja.id, relacion="sugiere", otro_id=extra.id
        )
    )
    db.flush()
    salida = cat.comprobar_configuracion(db, tenant_id, [{"producto_id": str(caja.id)}])
    assert salida["valida"] is True
    assert len(salida["sugerencias"]) == 1


def test_dos_incompatibles_juntos_se_cazan(db: Any, tenant_id: UUID, caja: Any) -> None:
    otro = cat.Producto(tenant_id=tenant_id, sku="OTRA", nombre="Otra", precio_base=Decimal(1))
    db.add(otro)
    db.flush()
    db.add(
        cat.RelacionProducto(
            tenant_id=tenant_id, producto_id=caja.id, relacion="excluye", otro_id=otro.id
        )
    )
    db.flush()
    salida = cat.comprobar_configuracion(
        db, tenant_id, [{"producto_id": str(caja.id)}, {"producto_id": str(otro.id)}]
    )
    assert salida["problemas"][0]["tipo"] == "incompatible"


def test_un_producto_retirado_no_se_puede_vender(db: Any, tenant_id: UUID, caja: Any) -> None:
    caja.activo = False
    db.flush()
    salida = cat.comprobar_configuracion(db, tenant_id, [{"producto_id": str(caja.id)}])
    assert salida["problemas"][0]["tipo"] == "retirado"


# ── Presupuestos (CRM-03.03.02.01, .05) ───────────────────────────────────


def test_el_presupuesto_calcula_el_precio_con_el_motor(
    uow: UnidadDeTrabajo, caja: Any, db: Any
) -> None:
    """Si lo trajera el llamante, el precio dependería de la pantalla que se
    usara, y dos canales darían dos números para el mismo cliente."""
    lista = _lista(db, uow.tenant_id)
    _regla(db, uow.tenant_id, lista, nombre="general", valor=Decimal(10))
    fila = pre.crear(uow, lineas=[{"producto_id": str(caja.id), "cantidad": 2}])
    assert fila.total == Decimal("180.00")
    assert fila.subtotal == Decimal("200.00")


def test_el_margen_sale_del_coste_real(uow: UnidadDeTrabajo, caja: Any) -> None:
    fila = pre.crear(uow, lineas=[{"producto_id": str(caja.id), "cantidad": 1}])
    # 100 de precio, 60 de coste → 40 %.
    assert fila.margen_pct == Decimal("40.00")


def test_con_una_linea_sin_coste_no_hay_margen_de_presupuesto(
    uow: UnidadDeTrabajo, caja: Any
) -> None:
    """Con una sola línea sin coste, el margen saldría inflado y se usaría para
    aprobar un descuento que no se puede dar."""
    fila = pre.crear(
        uow,
        lineas=[
            {"producto_id": str(caja.id)},
            {"descripcion": "portes", "precio_unitario": 20},
        ],
    )
    assert fila.margen_pct is None


def test_un_presupuesto_sin_lineas_no_ofrece_nada(uow: UnidadDeTrabajo) -> None:
    with pytest.raises(ErrorValidacion):
        pre.crear(uow, lineas=[])


def test_una_combinacion_invalida_no_llega_a_presupuesto(
    uow: UnidadDeTrabajo, caja: Any, db: Any
) -> None:
    otro = cat.Producto(tenant_id=uow.tenant_id, sku="OTRA", nombre="Otra", precio_base=Decimal(1))
    db.add(otro)
    db.flush()
    db.add(
        cat.RelacionProducto(
            tenant_id=uow.tenant_id, producto_id=caja.id, relacion="excluye", otro_id=otro.id
        )
    )
    db.flush()
    with pytest.raises(ErrorValidacion) as e:
        pre.crear(uow, lineas=[{"producto_id": str(caja.id)}, {"producto_id": str(otro.id)}])
    assert e.value.error_code == "presupuesto.configuracion_invalida"


# ── Versiones (CRM-03.03.02.01) ───────────────────────────────────────────


def test_la_version_anterior_no_se_toca(uow: UnidadDeTrabajo, caja: Any) -> None:
    """Editar en sitio hace imposible responder a «esto no es lo que me
    mandaste», que es la conversación que de verdad ocurre."""
    v1 = pre.crear(uow, lineas=[{"producto_id": str(caja.id)}])
    total_v1 = v1.total
    v2 = pre.nueva_version(uow, v1.id, lineas=[{"producto_id": str(caja.id), "cantidad": 5}])
    assert v2.version == 2
    assert v1.estado == "sustituido"
    assert v1.total == total_v1


def test_copiar_una_version_no_recalcula_precios(uow: UnidadDeTrabajo, caja: Any, db: Any) -> None:
    """Si se recalcularan, cambiar una coma del título movería el precio porque
    las tarifas habrían cambiado entre medias, y nadie entendería por qué."""
    v1 = pre.crear(uow, lineas=[{"producto_id": str(caja.id)}])
    lista = _lista(db, uow.tenant_id)
    _regla(db, uow.tenant_id, lista, valor=Decimal(50))
    v2 = pre.nueva_version(uow, v1.id, titulo="otro título")
    assert v2.total == v1.total


def test_los_cambios_entre_versiones_se_calculan_al_pedirlos(
    uow: UnidadDeTrabajo, caja: Any
) -> None:
    v1 = pre.crear(uow, lineas=[{"producto_id": str(caja.id), "cantidad": 1}])
    v2 = pre.nueva_version(uow, v1.id, lineas=[{"producto_id": str(caja.id), "cantidad": 3}])
    cambios = pre.comparar_versiones(uow.db, uow.tenant_id, v2.id)
    assert cambios["cambios"][0]["cambio"] == "modificada"
    assert cambios["cambios"][0]["cantidad_ahora"] == "3.0000"


def test_un_presupuesto_aceptado_no_admite_otra_version(uow: UnidadDeTrabajo, caja: Any) -> None:
    fila = pre.crear(uow, lineas=[{"producto_id": str(caja.id)}], cuenta_id=uuid4())
    pre.enviar(uow, fila.id)
    pre.aceptar(uow, fila.id)
    with pytest.raises(Conflicto):
        pre.nueva_version(uow, fila.id)


# ── Matriz de descuentos (CRM-03.03.02.04) ────────────────────────────────


def test_un_descuento_pequeno_sale_solo(uow: UnidadDeTrabajo, caja: Any) -> None:
    fila = pre.crear(uow, lineas=[{"producto_id": str(caja.id), "descuento_pct": 5}])
    salida = pre.enviar(uow, fila.id)
    assert salida["enviado"] is True


def test_un_descuento_grande_se_para(uow: UnidadDeTrabajo, caja: Any) -> None:
    fila = pre.crear(uow, lineas=[{"producto_id": str(caja.id), "descuento_pct": 40}])
    salida = pre.enviar(uow, fila.id)
    assert salida["enviado"] is False
    assert salida["estado"] == "en_aprobacion"


def test_un_descuento_pequeno_que_hunde_el_margen_tambien_se_para(
    uow: UnidadDeTrabajo, db: Any
) -> None:
    """Es la prueba que justifica mirar el margen: un 5 % sobre un producto de 8
    puntos deja la venta en pérdidas, y una matriz que solo mire el porcentaje lo
    aprueba sin que nadie se entere."""
    justo = cat.Producto(
        tenant_id=uow.tenant_id,
        sku="JUSTO",
        nombre="Margen justo",
        precio_base=Decimal(100),
        coste=Decimal(92),
    )
    db.add(justo)
    db.flush()
    fila = pre.crear(uow, lineas=[{"producto_id": str(justo.id), "descuento_pct": 5}])
    salida = pre.enviar(uow, fila.id)
    assert salida["enviado"] is False
    assert any("margen" in m for m in salida["motivos"])


def test_sin_margen_conocido_se_exige_aprobacion(uow: UnidadDeTrabajo, caja: Any) -> None:
    """Tratar «no lo sé» como «está bien» es cómo se firma un presupuesto que
    pierde dinero."""
    fila = pre.crear(
        uow,
        lineas=[{"producto_id": str(caja.id)}, {"descripcion": "portes", "precio_unitario": 20}],
    )
    salida = pre.enviar(uow, fila.id)
    assert salida["enviado"] is False
    assert any("no se puede saber el margen" in m for m in salida["motivos"])


def test_el_suelo_del_producto_manda_sobre_el_general(uow: UnidadDeTrabajo, caja: Any) -> None:
    """Un producto con margen mínimo propio lo tiene porque el general no le
    vale."""
    caja.margen_minimo_pct = Decimal(38)
    uow.db.flush()
    fila = pre.crear(uow, lineas=[{"producto_id": str(caja.id), "descuento_pct": 5}])
    politica = pre.politica_de_descuento(uow.db, uow.tenant_id, fila)
    assert politica["necesita_aprobacion"] is True
    assert any("mínimo propio" in m for m in politica["motivos"])


def test_aprobado_se_manda_aunque_la_matriz_lo_pidiera(uow: UnidadDeTrabajo, caja: Any) -> None:
    fila = pre.crear(uow, lineas=[{"producto_id": str(caja.id), "descuento_pct": 40}])
    pre.enviar(uow, fila.id)
    fila.estado = "aprobado"
    uow.db.flush()
    assert pre.enviar(uow, fila.id)["enviado"] is True


# ── Aceptación y vigencia ─────────────────────────────────────────────────


def test_aceptar_crea_el_pedido(uow: UnidadDeTrabajo, caja: Any) -> None:
    fila = pre.crear(uow, lineas=[{"producto_id": str(caja.id)}], cuenta_id=uuid4())
    pre.enviar(uow, fila.id)
    pedido = pre.aceptar(uow, fila.id)
    assert pedido.numero.startswith("PED-")
    assert pedido.total == fila.total


def test_un_presupuesto_caducado_no_se_acepta(uow: UnidadDeTrabajo, caja: Any) -> None:
    """Aceptarlo sin decir nada es cómo se sirve a precio de hace un año, y el
    descubrimiento llega con la factura."""
    fila = pre.crear(uow, lineas=[{"producto_id": str(caja.id)}], cuenta_id=uuid4())
    pre.enviar(uow, fila.id)
    fila.valido_hasta = date.today() - timedelta(days=1)
    uow.db.flush()
    with pytest.raises(Conflicto) as e:
        pre.aceptar(uow, fila.id)
    assert e.value.error_code == "presupuesto.caducado"


def test_los_vencidos_se_marcan_para_que_no_cuenten_como_pipeline(
    uow: UnidadDeTrabajo, caja: Any
) -> None:
    fila = pre.crear(uow, lineas=[{"producto_id": str(caja.id)}])
    pre.enviar(uow, fila.id)
    fila.valido_hasta = date.today() - timedelta(days=1)
    uow.db.flush()
    salida = pre.caducar_vencidos(uow, uow.tenant_id)
    assert salida["caducados"] == [fila.numero]


# ── Documento (CRM-03.03.02.06) ───────────────────────────────────────────


def test_el_documento_no_lleva_coste_ni_margen(uow: UnidadDeTrabajo, caja: Any) -> None:
    """Es el error más caro que se puede cometer al componer una oferta."""
    fila = pre.crear(uow, lineas=[{"producto_id": str(caja.id)}])
    doc = pre.documento(uow.db, uow.tenant_id, fila.id)
    plano = str(doc)
    assert "coste" not in plano
    assert "margen" not in plano


def test_el_documento_lleva_su_marca_y_su_idioma(uow: UnidadDeTrabajo, caja: Any) -> None:
    """Un grupo con tres marcas manda ofertas con la que corresponda, y quien la
    compone no tiene que adivinarlo."""
    fila = pre.crear(uow, lineas=[{"producto_id": str(caja.id)}], marca="norte", idioma="ca")
    assert pre.documento(uow.db, uow.tenant_id, fila.id)["plantilla"] == "presupuesto/norte/ca"


def test_el_documento_no_enseña_descuentos_a_cero(uow: UnidadDeTrabajo, caja: Any) -> None:
    """Una columna con ceros invita a pedir descuento a quien no lo había
    pedido."""
    fila = pre.crear(uow, lineas=[{"producto_id": str(caja.id)}])
    assert pre.documento(uow.db, uow.tenant_id, fila.id)["lineas"][0]["descuento_pct"] is None


# ── Contratos y renovaciones (CRM-03.03.02.08, .10) ───────────────────────


def test_un_contrato_que_se_renueva_solo_necesita_fin(uow: UnidadDeTrabajo) -> None:
    """Sin fecha de fin no hay nada que renovar ni cuándo avisar."""
    with pytest.raises(ErrorValidacion):
        pre.crear_contrato(uow, cuenta_id=uuid4(), inicio=date.today(), renovacion_automatica=True)


def test_el_preaviso_avisa_antes_de_vencer(uow: UnidadDeTrabajo) -> None:
    """El día que vence ya es tarde para no renovar, y quien quería negociar se
    encuentra con otro año firmado."""
    pre.crear_contrato(
        uow,
        cuenta_id=uuid4(),
        inicio=date.today() - timedelta(days=300),
        fin=date.today() + timedelta(days=20),
        preaviso_dias=30,
    )
    salida = pre.revisar_renovaciones(uow, uow.tenant_id)
    assert len(salida["avisados"]) == 1
    assert salida["avisados"][0]["dias"] == 20


def test_no_se_avisa_dos_veces(uow: UnidadDeTrabajo) -> None:
    """Sin la marca, el aviso se manda cada noche hasta que alguien lo silencia
    apagando la alerta entera."""
    pre.crear_contrato(
        uow,
        cuenta_id=uuid4(),
        inicio=date.today() - timedelta(days=300),
        fin=date.today() + timedelta(days=20),
    )
    pre.revisar_renovaciones(uow, uow.tenant_id)
    assert pre.revisar_renovaciones(uow, uow.tenant_id)["avisados"] == []


def test_lo_renovado_no_cuenta_como_baja(uow: UnidadDeTrabajo) -> None:
    """Mezclarlas hace que la tasa de bajas cuente como pérdidas las
    renovaciones."""
    viejo = pre.crear_contrato(
        uow,
        cuenta_id=uuid4(),
        inicio=date.today() - timedelta(days=400),
        fin=date.today() - timedelta(days=1),
        renovacion_automatica=True,
        meses_renovacion=12,
    )
    salida = pre.revisar_renovaciones(uow, uow.tenant_id)
    assert len(salida["renovados"]) == 1
    assert viejo.estado == "renovado"


def test_la_renovacion_respeta_el_final_de_mes(uow: UnidadDeTrabajo) -> None:
    """Un contrato que vence el 31 de enero y se renueva doce meses no puede
    convertirse en el 3 de marzo, que es lo que pasa sumando días."""
    assert pre._sumar_meses(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert pre._sumar_meses(date(2026, 1, 31), 12) == date(2027, 1, 31)


# ── Suscripciones (CRM-03.03.02.09) ───────────────────────────────────────


def test_el_cambio_de_plan_prorratea(uow: UnidadDeTrabajo) -> None:
    fila = pre.alta_suscripcion(
        uow,
        cuenta_id=uuid4(),
        plan="basico",
        importe_periodo=Decimal(100),
        inicio=date.today(),
    )
    salida = pre.cambiar_suscripcion(
        uow,
        fila.id,
        tipo="cambio_plan",
        plan="pro",
        importe_periodo=Decimal(160),
    )
    assert salida["plan"] == "pro"
    assert Decimal(salida["prorrateo"]) > 0


def test_el_historico_de_la_suscripcion_no_se_pisa(uow: UnidadDeTrabajo, db: Any) -> None:
    """Sin él, responder «¿desde cuándo paga esto?» exige mirar facturas, y el
    ARR de hace seis meses no se puede reconstruir."""
    fila = pre.alta_suscripcion(
        uow, cuenta_id=uuid4(), plan="basico", importe_periodo=Decimal(100), inicio=date.today()
    )
    pre.cambiar_suscripcion(
        uow, fila.id, tipo="cambio_plan", plan="pro", importe_periodo=Decimal(160)
    )
    from sqlalchemy import select

    cambios = (
        db.execute(
            select(pre.CambioSuscripcion).where(pre.CambioSuscripcion.suscripcion_id == fila.id)
        )
        .scalars()
        .all()
    )
    assert {c.tipo for c in cambios} == {"alta", "cambio_plan"}
    cambio = next(c for c in cambios if c.tipo == "cambio_plan")
    assert cambio.plan_antes == "basico"
    assert cambio.plan_despues == "pro"


def test_una_suscripcion_cancelada_no_se_cambia(uow: UnidadDeTrabajo) -> None:
    fila = pre.alta_suscripcion(
        uow, cuenta_id=uuid4(), plan="basico", importe_periodo=Decimal(100), inicio=date.today()
    )
    pre.cambiar_suscripcion(uow, fila.id, tipo="baja")
    with pytest.raises(Conflicto):
        pre.cambiar_suscripcion(uow, fila.id, tipo="cambio_plan", plan="pro")


def test_lo_pausado_no_cuenta_como_recurrente(uow: UnidadDeTrabajo) -> None:
    """Contarlo infla el recurrente con dinero que no entra."""
    activa = pre.alta_suscripcion(
        uow,
        cuenta_id=uuid4(),
        plan="a",
        importe_periodo=Decimal(100),
        inicio=date.today() - timedelta(days=1),
    )
    pausada = pre.alta_suscripcion(
        uow,
        cuenta_id=uuid4(),
        plan="b",
        importe_periodo=Decimal(50),
        inicio=date.today() - timedelta(days=1),
    )
    pre.cambiar_suscripcion(uow, pausada.id, tipo="pausa")
    salida = pre.ingreso_recurrente(uow.db, uow.tenant_id)
    assert salida["mrr"] == "100.00"
    assert salida["mrr_pausado"] == "50.00"
    assert activa.estado == "activa"


def test_el_arr_anual_se_normaliza_a_mensual(uow: UnidadDeTrabajo) -> None:
    pre.alta_suscripcion(
        uow,
        cuenta_id=uuid4(),
        plan="anual",
        importe_periodo=Decimal(1200),
        inicio=date.today() - timedelta(days=1),
        periodicidad="anual",
    )
    salida = pre.ingreso_recurrente(uow.db, uow.tenant_id)
    assert salida["mrr"] == "100.00"
    assert salida["arr"] == "1200.00"


# ── Traspaso al ERP (CRM-03.03.02.11) ─────────────────────────────────────


def test_el_pedido_queda_esperando_confirmacion(uow: UnidadDeTrabajo, caja: Any) -> None:
    """El ERP puede aceptar el mensaje y rechazar el pedido después."""
    fila = pre.crear(uow, lineas=[{"producto_id": str(caja.id)}], cuenta_id=uuid4())
    pre.enviar(uow, fila.id)
    pedido = pre.aceptar(uow, fila.id)
    salida = pre.enviar_a_erp(uow, pedido.id)
    assert salida["estado"] == "enviado_erp"
    assert pedido.confirmado_at is None


def test_el_rechazo_del_erp_se_guarda_con_su_motivo(uow: UnidadDeTrabajo, caja: Any) -> None:
    fila = pre.crear(uow, lineas=[{"producto_id": str(caja.id)}], cuenta_id=uuid4())
    pre.enviar(uow, fila.id)
    pedido = pre.aceptar(uow, fila.id)
    pre.enviar_a_erp(uow, pedido.id)
    pre.confirmar_desde_erp(uow, pedido.id, aceptado=False, error="cliente bloqueado")
    assert pedido.estado == "rechazado_erp"
    assert pedido.error_erp == "cliente bloqueado"


def test_un_pedido_sin_respuesta_sale_en_la_conciliacion(uow: UnidadDeTrabajo, caja: Any) -> None:
    """El silencio no es una confirmación: un pedido enviado del que nadie
    contesta parece en curso, y detrás casi siempre hay un mensaje perdido."""
    fila = pre.crear(uow, lineas=[{"producto_id": str(caja.id)}], cuenta_id=uuid4())
    pre.enviar(uow, fila.id)
    pedido = pre.aceptar(uow, fila.id)
    pre.enviar_a_erp(uow, pedido.id)
    pedido.enviado_at = datetime.now(timezone.utc) - timedelta(hours=48)
    uow.db.flush()
    salida = pre.conciliar_erp(uow, uow.tenant_id, horas_espera=24)
    assert [p["numero"] for p in salida["sin_respuesta"]] == [pedido.numero]
    assert salida["en_verde"] is False


def test_un_pedido_rechazado_que_nadie_mira_tambien_sale(uow: UnidadDeTrabajo, caja: Any) -> None:
    """Es una venta cerrada que no se sirve."""
    fila = pre.crear(uow, lineas=[{"producto_id": str(caja.id)}], cuenta_id=uuid4())
    pre.enviar(uow, fila.id)
    pedido = pre.aceptar(uow, fila.id)
    pre.enviar_a_erp(uow, pedido.id)
    pre.confirmar_desde_erp(uow, pedido.id, aceptado=False, error="sin stock")
    salida = pre.conciliar_erp(uow, uow.tenant_id)
    assert salida["rechazados"][0]["error"] == "sin stock"


def test_sin_pedidos_no_se_dice_que_todo_esta_bien(uow: UnidadDeTrabajo) -> None:
    assert pre.conciliar_erp(uow, uow.tenant_id)["medible"] is False


def test_un_pedido_ya_confirmado_no_se_reenvia(uow: UnidadDeTrabajo, caja: Any) -> None:
    """Reenviarlo duplicaría el pedido en el ERP del cliente."""
    fila = pre.crear(uow, lineas=[{"producto_id": str(caja.id)}], cuenta_id=uuid4())
    pre.enviar(uow, fila.id)
    pedido = pre.aceptar(uow, fila.id)
    pre.enviar_a_erp(uow, pedido.id)
    pre.confirmar_desde_erp(uow, pedido.id, aceptado=True, referencia_erp="SO-1")
    with pytest.raises(Conflicto):
        pre.enviar_a_erp(uow, pedido.id)


def test_un_presupuesto_sin_cuenta_no_llega_a_pedido(uow: UnidadDeTrabajo, caja: Any) -> None:
    """Un presupuesto se puede preparar para un posible cliente que todavía no es
    cuenta; un pedido no. Dejarlo pasar convierte el problema en un rechazo del
    ERP dos días después, con el pedido ya prometido al cliente."""
    fila = pre.crear(uow, lineas=[{"producto_id": str(caja.id)}])
    pre.enviar(uow, fila.id)
    with pytest.raises(Conflicto) as e:
        pre.aceptar(uow, fila.id)
    assert e.value.error_code == "presupuesto.sin_cuenta"
