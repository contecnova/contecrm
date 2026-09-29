"""Canal indirecto: partners, portal, registro y precios (CRM-03.04.01).

Un programa de canal falla siempre por los mismos cinco sitios, y las pruebas van
detrás de esos y no de los caminos felices:

  * el partner que entra activo sin haber terminado el alta,
  * la certificación que se marcó una vez y sigue marcada tres años después,
  * el registro de oportunidad que no protege porque el cliente se escribió de
    otra manera,
  * el segundo partner al que se le dice **quién** tiene el cliente,
  * y el partner que ve la cartera del de al lado cambiando un número.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.authz.principal import Principal
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoAutenticado, NoEncontrado

from services.sales import partners as prt


# El «hoy» del producto, no el de la máquina. Igual que en activos y fondos:
# estas comprobaciones se construían con el reloj local y el producto calcula el
# día en la zona del tenant —UTC cuando no hay ninguna—, así que estaban verdes
# veintidós horas al día y rojas dos.
def _hoy() -> date:
    from crmcore.fechas import hoy

    return hoy()


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


def _partner(uow: UnidadDeTrabajo, clave: str = "acme", **kw: Any) -> prt.Partner:
    base: dict[str, Any] = {"clave": clave, "nombre": clave.title(), "canal": clave}
    base.update(kw)
    return prt.crear_partner(uow, **base)


def _activo(uow: UnidadDeTrabajo, clave: str = "acme", **kw: Any) -> prt.Partner:
    fila = _partner(uow, clave, **kw)
    prt.activar(uow, fila.id)
    return fila


# ── Alta, niveles y certificaciones (CRM-03.04.01.01) ─────────────────────


def test_el_partner_nace_en_alta_no_activo(uow: UnidadDeTrabajo) -> None:
    """Un partner que entra activo registra antes de haber firmado nada."""
    fila = _partner(uow)
    assert fila.estado == "alta"


def test_no_se_activa_con_pasos_de_alta_pendientes(uow: UnidadDeTrabajo) -> None:
    fila = _partner(uow, pasos_onboarding=["contrato", "alta_fiscal"])
    with pytest.raises(Conflicto) as error:
        prt.activar(uow, fila.id)
    assert "contrato" in str(error.value.detalle)


def test_se_puede_forzar_la_activacion_pero_exige_motivo(uow: UnidadDeTrabajo) -> None:
    """Sin esta puerta, lo que se hace es marcar como hecho lo que no se hizo."""
    fila = _partner(uow, pasos_onboarding=["contrato"])
    with pytest.raises(ErrorValidacion):
        prt.activar(uow, fila.id, forzar=True)
    activado = prt.activar(uow, fila.id, forzar=True, motivo="Acuerdo verbal del director")
    assert activado.estado == "activo"
    # El paso sigue pendiente: forzar no lo da por hecho.
    assert [p for p in activado.onboarding if not p["hecho"]]


def test_completar_un_paso_que_no_existe_avisa(uow: UnidadDeTrabajo) -> None:
    fila = _partner(uow, pasos_onboarding=["contrato"])
    with pytest.raises(ErrorValidacion):
        prt.completar_paso(uow, fila.id, "seguro")
    prt.completar_paso(uow, fila.id, "contrato")
    prt.activar(uow, fila.id)


def test_una_certificacion_caducada_deja_de_contar(uow: UnidadDeTrabajo) -> None:
    """Una certificación sin caducidad es un logotipo, no un requisito."""
    fila = _partner(uow)
    prt.certificar(uow, fila.id, clave="tecnico", caduca_el=_hoy() - timedelta(days=1))
    prt.certificar(uow, fila.id, clave="comercial", caduca_el=_hoy() + timedelta(days=30))
    vigentes = prt.certificaciones_vigentes(uow.db, uow.tenant_id, fila.id)
    assert vigentes == {"comercial"}


def test_no_cumple_el_nivel_si_le_falta_una_certificacion(uow: UnidadDeTrabajo) -> None:
    nivel = prt.crear_nivel(
        uow, clave="oro", nombre="Oro", certificaciones_exigidas=["tecnico", "comercial"]
    )
    fila = _partner(uow, nivel_id=nivel.id)
    prt.certificar(uow, fila.id, clave="tecnico")
    estado = prt.cumple_nivel(uow.db, uow.tenant_id, fila.id)
    assert estado["cumple"] is False
    assert estado["certificaciones_faltantes"] == ["comercial"]


def test_sin_facturacion_medida_el_nivel_no_concluye(uow: UnidadDeTrabajo) -> None:
    """Cero y «no lo sé» llevan a decisiones opuestas: una baja de nivel a quien
    factura."""
    nivel = prt.crear_nivel(uow, clave="oro", nombre="Oro", facturacion_minima=Decimal(100000))
    fila = _partner(uow, nivel_id=nivel.id)
    estado = prt.cumple_nivel(uow.db, uow.tenant_id, fila.id)
    assert estado["cumple"] is False
    assert estado["concluyente"] is False
    assert estado["facturacion_medida"] is False
    # Con el dato encima de la mesa sí concluye.
    con_dato = prt.cumple_nivel(uow.db, uow.tenant_id, fila.id, facturacion=Decimal(150000))
    assert con_dato["cumple"] is True and con_dato["concluyente"] is True


def test_no_se_activa_si_no_cumple_su_nivel_y_se_sabe(uow: UnidadDeTrabajo) -> None:
    nivel = prt.crear_nivel(uow, clave="oro", nombre="Oro", certificaciones_exigidas=["tecnico"])
    fila = _partner(uow, nivel_id=nivel.id)
    with pytest.raises(Conflicto):
        prt.activar(uow, fila.id, facturacion=Decimal(1))


def test_las_certificaciones_avisan_antes_de_caducar(uow: UnidadDeTrabajo) -> None:
    """Certificar a alguien lleva semanas: avisar el mismo día no sirve."""
    fila = _partner(uow)
    prt.certificar(uow, fila.id, clave="tecnico", caduca_el=_hoy() + timedelta(days=10))
    prt.certificar(uow, fila.id, clave="lejana", caduca_el=_hoy() + timedelta(days=400))
    aviso = prt.certificaciones_por_caducar(uow.db, uow.tenant_id, dias=30)
    claves = [c["clave"] for c in aviso["certificaciones"]]
    assert claves == ["tecnico"]
    assert aviso["certificaciones"][0]["caducada"] is False


def test_suspender_exige_motivo(uow: UnidadDeTrabajo) -> None:
    fila = _activo(uow)
    with pytest.raises(ErrorValidacion):
        prt.cambiar_estado(uow, fila.id, estado="suspendido")
    prt.cambiar_estado(uow, fila.id, estado="suspendido", motivo="Impago")


# ── Portal y compartimento (CRM-03.04.01.02, .03) ─────────────────────────


def test_el_enlace_a_un_correo_desconocido_no_dice_nada(uow: UnidadDeTrabajo) -> None:
    """Distinguirlo convertiría el portal en la lista de nuestros partners."""
    enlace, token = prt.emitir_enlace(uow, email="nadie@ejemplo.com")
    assert enlace is None and token == ""


def test_el_enlace_es_de_un_solo_uso(uow: UnidadDeTrabajo) -> None:
    fila = _activo(uow)
    prt.dar_acceso(uow, fila.id, email="ana@acme.com")
    _, token = prt.emitir_enlace(uow, email="ana@acme.com")
    acceso = prt.canjear_enlace(uow, token)
    assert acceso.partner_id == fila.id
    with pytest.raises(NoAutenticado):
        prt.canjear_enlace(uow, token)


def test_revocar_corta_los_enlaces_vivos(uow: UnidadDeTrabajo) -> None:
    """Si no, quien acaba de perder el acceso entra con el correo de esta mañana."""
    fila = _activo(uow)
    acceso = prt.dar_acceso(uow, fila.id, email="ana@acme.com")
    _, token = prt.emitir_enlace(uow, email="ana@acme.com")
    prt.revocar_acceso(uow, acceso.id, motivo="Se ha ido de la empresa")
    with pytest.raises(NoAutenticado):
        prt.canjear_enlace(uow, token)


def test_un_partner_de_baja_no_entra(uow: UnidadDeTrabajo) -> None:
    fila = _activo(uow)
    prt.dar_acceso(uow, fila.id, email="ana@acme.com")
    prt.cambiar_estado(uow, fila.id, estado="baja", motivo="Fin de contrato")
    enlace, token = prt.emitir_enlace(uow, email="ana@acme.com")
    assert enlace is None and token == ""


def test_el_compartimento_viaja_en_el_principal(uow: UnidadDeTrabajo) -> None:
    """Si saliera de la URL, entrar en la cartera del vecino sería cambiar un número."""
    from crmcore.authz.estanco import compartimento_de

    fila = _activo(uow)
    acceso = prt.dar_acceso(uow, fila.id, email="ana@acme.com")
    principal = Principal(id=uuid4(), atributos=prt.atributos_principal(acceso))
    comp = compartimento_de(principal)
    assert comp is not None and comp.tipo == "partner" and comp.id == fila.id


def test_el_partner_no_ve_lo_de_otro_partner(uow: UnidadDeTrabajo) -> None:
    from crmcore.authz.estanco import aplicar_estanco, exigir_propio
    from sqlalchemy import select

    uno = _activo(uow, "uno")
    otro = _activo(uow, "otro")
    mio, _ = prt.registrar_oportunidad(
        uow, partner_id=uno.id, cliente_nombre="Cliente A", nif="A11111111"
    )
    ajeno, _ = prt.registrar_oportunidad(
        uow, partner_id=otro.id, cliente_nombre="Cliente B", nif="B22222222"
    )
    acceso = prt.dar_acceso(uow, uno.id, email="ana@uno.com")
    principal = Principal(id=uuid4(), atributos=prt.atributos_principal(acceso))

    consulta = aplicar_estanco(
        select(prt.RegistroOportunidad).where(prt.RegistroOportunidad.tenant_id == uow.tenant_id),
        prt.RegistroOportunidad.partner_id,
        principal=principal,
        tipo="partner",
    )
    vistos = {r.id for r in uow.db.execute(consulta).scalars()}
    assert vistos == {mio.id}

    # Y por identificador directo: **404, no 403**. Un 403 confirmaría que existe.
    with pytest.raises(NoEncontrado):
        exigir_propio(ajeno, atributo="partner_id", principal=principal, tipo="partner")
    exigir_propio(mio, atributo="partner_id", principal=principal, tipo="partner")


def test_un_empleado_sin_compartimento_lo_ve_todo(uow: UnidadDeTrabajo) -> None:
    """«Sin acotar» no es «acotado a nada»: escrito al revés, los empleados
    dejarían de ver nada."""
    from crmcore.authz.estanco import aplicar_estanco
    from sqlalchemy import select

    uno = _activo(uow, "uno")
    otro = _activo(uow, "otro")
    prt.registrar_oportunidad(uow, partner_id=uno.id, cliente_nombre="A", nif="A11111111")
    prt.registrar_oportunidad(uow, partner_id=otro.id, cliente_nombre="B", nif="B22222222")
    principal = Principal(id=uuid4())
    consulta = aplicar_estanco(
        select(prt.RegistroOportunidad).where(prt.RegistroOportunidad.tenant_id == uow.tenant_id),
        prt.RegistroOportunidad.partner_id,
        principal=principal,
        tipo="partner",
    )
    assert len(list(uow.db.execute(consulta).scalars())) == 2


def test_el_partner_no_puede_registrar_a_nombre_de_otro(uow: UnidadDeTrabajo) -> None:
    """Aceptar el identificador del cuerpo permitiría robar un registro."""
    from crmcore.authz.estanco import dueno_forzado

    uno = _activo(uow, "uno")
    otro = _activo(uow, "otro")
    acceso = prt.dar_acceso(uow, uno.id, email="ana@uno.com")
    principal = Principal(id=uuid4(), atributos=prt.atributos_principal(acceso))
    assert dueno_forzado(principal, tipo="partner", pedido=otro.id) == uno.id


# ── Registro de oportunidad y protección (CRM-03.04.01.02) ────────────────


def test_un_registro_sin_identificar_al_cliente_no_protege(uow: UnidadDeTrabajo) -> None:
    """Con el nombre suelto, la misma empresa son tres registros distintos."""
    fila = _activo(uow)
    with pytest.raises(ErrorValidacion):
        prt.registrar_oportunidad(uow, partner_id=fila.id, cliente_nombre="Talleres García SL")


def test_el_nif_se_normaliza_para_detectar_el_conflicto(uow: UnidadDeTrabajo) -> None:
    uno = _activo(uow, "uno")
    otro = _activo(uow, "otro")
    primero, _ = prt.registrar_oportunidad(
        uow, partner_id=uno.id, cliente_nombre="Talleres", nif="b-12 345 678"
    )
    prt.decidir_registro(uow, primero.id, aprobar=True)
    _, aviso = prt.registrar_oportunidad(
        uow, partner_id=otro.id, cliente_nombre="TALLERES SL", nif="B12345678"
    )
    assert aviso["hay_conflicto"] is True


def test_al_segundo_no_se_le_dice_de_quien_es(uow: UnidadDeTrabajo) -> None:
    """Para un competidor que también es partner, el nombre es la información."""
    uno = _activo(uow, "uno")
    otro = _activo(uow, "otro")
    primero, _ = prt.registrar_oportunidad(
        uow, partner_id=uno.id, cliente_nombre="Cliente", nif="A11111111"
    )
    prt.decidir_registro(uow, primero.id, aprobar=True)
    _, aviso = prt.registrar_oportunidad(
        uow, partner_id=otro.id, cliente_nombre="Cliente", nif="A11111111"
    )
    texto = " ".join(str(v) for v in aviso.values())
    assert "uno" not in texto.lower()
    assert str(uno.id) not in texto
    assert aviso["es_propio"] is False


def test_al_propio_partner_si_se_le_dice_que_ya_lo_tenia(uow: UnidadDeTrabajo) -> None:
    """Es su dato; no decírselo le hace registrar lo mismo cada semana."""
    uno = _activo(uow, "uno")
    primero, _ = prt.registrar_oportunidad(
        uow, partner_id=uno.id, cliente_nombre="Cliente", nif="A11111111"
    )
    prt.decidir_registro(uow, primero.id, aprobar=True)
    _, aviso = prt.registrar_oportunidad(
        uow, partner_id=uno.id, cliente_nombre="Cliente", nif="A11111111"
    )
    assert aviso["es_propio"] is True


def test_el_segundo_registro_se_guarda_igual(uow: UnidadDeTrabajo) -> None:
    """Tirarlo dejaría al fabricante sin saber que dos partners van al mismo sitio."""
    uno = _activo(uow, "uno")
    otro = _activo(uow, "otro")
    primero, _ = prt.registrar_oportunidad(
        uow, partner_id=uno.id, cliente_nombre="Cliente", nif="A11111111"
    )
    prt.decidir_registro(uow, primero.id, aprobar=True)
    segundo, _ = prt.registrar_oportunidad(
        uow, partner_id=otro.id, cliente_nombre="Cliente", nif="A11111111"
    )
    assert segundo.estado == "pendiente"
    assert segundo.conflicto_con == primero.id


def test_un_registro_caducado_deja_de_proteger(uow: UnidadDeTrabajo) -> None:
    uno = _activo(uow, "uno")
    otro = _activo(uow, "otro")
    primero, _ = prt.registrar_oportunidad(
        uow, partner_id=uno.id, cliente_nombre="Cliente", nif="A11111111"
    )
    prt.decidir_registro(uow, primero.id, aprobar=True, dias_proteccion=1)
    prt.caducar_protecciones(uow, en_fecha=_hoy() + timedelta(days=5))
    _, aviso = prt.registrar_oportunidad(
        uow, partner_id=otro.id, cliente_nombre="Cliente", nif="A11111111"
    )
    assert aviso["hay_conflicto"] is False


def test_aprobar_fija_una_fecha_y_rechazar_exige_motivo(uow: UnidadDeTrabajo) -> None:
    """Una protección «mientras trabaje el cliente» acaba discutiéndose por correo."""
    fila = _activo(uow)
    uno, _ = prt.registrar_oportunidad(
        uow, partner_id=fila.id, cliente_nombre="Cliente", nif="A11111111"
    )
    aprobado = prt.decidir_registro(uow, uno.id, aprobar=True, dias_proteccion=45)
    assert aprobado.protegido_hasta == _hoy() + timedelta(days=45)

    dos, _ = prt.registrar_oportunidad(
        uow, partner_id=fila.id, cliente_nombre="Otro", nif="B22222222"
    )
    with pytest.raises(ErrorValidacion):
        prt.decidir_registro(uow, dos.id, aprobar=False)
    rechazado = prt.decidir_registro(uow, dos.id, aprobar=False, motivo="Cliente ya nuestro")
    assert rechazado.estado == "rechazado" and rechazado.motivo


def test_el_evento_de_rechazo_no_promete_una_fecha_que_no_existe(
    uow: UnidadDeTrabajo,
) -> None:
    """Un rechazo no tiene fecha de protección. Prometerla en el contrato para
    mandarla vacía haría que el consumidor se fiara de un campo que a veces no
    significa nada — y este fallo solo sale con el catálogo de eventos cargado,
    es decir, con la suite entera."""
    fila = _activo(uow)
    registro, _ = prt.registrar_oportunidad(
        uow, partner_id=fila.id, cliente_nombre="Cliente", nif="A11111111"
    )
    rechazado = prt.decidir_registro(uow, registro.id, aprobar=False, motivo="Cliente ya nuestro")
    assert rechazado.protegido_hasta is None


def test_la_proteccion_la_manda_el_nivel_del_partner(uow: UnidadDeTrabajo) -> None:
    """Un partner de nivel alto protege más tiempo: eso *es* el programa."""
    nivel = prt.crear_nivel(uow, clave="oro", nombre="Oro", dias_proteccion=180)
    fila = _partner(uow, nivel_id=nivel.id)
    prt.activar(uow, fila.id)
    registro, _ = prt.registrar_oportunidad(
        uow, partner_id=fila.id, cliente_nombre="Cliente", nif="A11111111"
    )
    aprobado = prt.decidir_registro(uow, registro.id, aprobar=True)
    assert aprobado.protegido_hasta == _hoy() + timedelta(days=180)


def test_un_partner_suspendido_no_registra(uow: UnidadDeTrabajo) -> None:
    fila = _activo(uow)
    prt.cambiar_estado(uow, fila.id, estado="suspendido", motivo="Revisión")
    with pytest.raises(Conflicto):
        prt.registrar_oportunidad(
            uow, partner_id=fila.id, cliente_nombre="Cliente", nif="A11111111"
        )


def test_un_registro_decidido_no_se_decide_dos_veces(uow: UnidadDeTrabajo) -> None:
    fila = _activo(uow)
    registro, _ = prt.registrar_oportunidad(
        uow, partner_id=fila.id, cliente_nombre="Cliente", nif="A11111111"
    )
    prt.decidir_registro(uow, registro.id, aprobar=True)
    with pytest.raises(Conflicto):
        prt.decidir_registro(uow, registro.id, aprobar=False, motivo="Me arrepiento")


# ── Precios de canal (CRM-03.04.01.05) ────────────────────────────────────


def _producto(uow: UnidadDeTrabajo, precio: Decimal = Decimal(1000)):
    from services.sales import catalogo

    fila = catalogo.Producto(
        tenant_id=uow.tenant_id, sku="SKU-1", nombre="Producto", precio_base=precio
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila


def test_el_precio_de_canal_sale_del_motor_de_siempre(uow: UnidadDeTrabajo) -> None:
    """Duplicar el motor habría dado dos precios del mismo producto."""
    fila = _activo(uow, "acme")
    producto = _producto(uow)
    calculo = prt.precio_para_partner(
        uow.db, uow.tenant_id, partner_id=fila.id, producto_id=producto.id
    )
    assert calculo["canal"] == "acme"
    assert Decimal(calculo["precio"]) == Decimal(1000)


def test_el_nivel_aplica_su_descuento_y_queda_explicado(uow: UnidadDeTrabajo) -> None:
    nivel = prt.crear_nivel(uow, clave="oro", nombre="Oro", descuento_extra_pct=Decimal(10))
    fila = _partner(uow, nivel_id=nivel.id)
    prt.activar(uow, fila.id)
    producto = _producto(uow)
    calculo = prt.precio_para_partner(
        uow.db, uow.tenant_id, partner_id=fila.id, producto_id=producto.id
    )
    assert Decimal(calculo["precio"]) == Decimal(900)
    assert any("nivel oro" in paso["regla"] for paso in calculo["pasos"])


def test_sin_acuerdo_se_dice_que_no_hay_acuerdo(uow: UnidadDeTrabajo) -> None:
    """Cero y «sin acuerdo» llevan a conversaciones distintas con el partner."""
    fila = _activo(uow)
    producto = _producto(uow)
    calculo = prt.precio_para_partner(
        uow.db, uow.tenant_id, partner_id=fila.id, producto_id=producto.id
    )
    assert calculo["hay_acuerdo"] is False


def test_el_suelo_dice_hasta_donde_puede_bajar_el_partner(uow: UnidadDeTrabajo) -> None:
    fila = _activo(uow)
    uow.db.add(
        prt.AcuerdoCanal(
            tenant_id=uow.tenant_id, partner_id=fila.id, descuento_maximo_pct=Decimal(15)
        )
    )
    uow.db.flush()
    producto = _producto(uow)
    calculo = prt.precio_para_partner(
        uow.db, uow.tenant_id, partner_id=fila.id, producto_id=producto.id
    )
    assert Decimal(calculo["precio_suelo"]) == Decimal(850)


def test_el_acuerdo_del_nivel_vale_cuando_el_partner_no_tiene_el_suyo(
    uow: UnidadDeTrabajo,
) -> None:
    nivel = prt.crear_nivel(uow, clave="oro", nombre="Oro")
    fila = _partner(uow, nivel_id=nivel.id)
    prt.activar(uow, fila.id)
    uow.db.add(
        prt.AcuerdoCanal(
            tenant_id=uow.tenant_id, nivel_id=nivel.id, descuento_maximo_pct=Decimal(20)
        )
    )
    uow.db.flush()
    acuerdo = prt.acuerdo_de(uow.db, uow.tenant_id, fila.id)
    assert acuerdo is not None and Decimal(acuerdo.descuento_maximo_pct) == Decimal(20)


def test_pasarse_del_tope_necesita_aprobacion(uow: UnidadDeTrabajo) -> None:
    fila = _activo(uow)
    uow.db.add(
        prt.AcuerdoCanal(
            tenant_id=uow.tenant_id,
            partner_id=fila.id,
            descuento_maximo_pct=Decimal(10),
            margen_minimo_pct=Decimal(20),
        )
    )
    uow.db.flush()
    dentro = prt.comprobar_descuento(
        uow.db,
        uow.tenant_id,
        partner_id=fila.id,
        precio_lista=Decimal(1000),
        precio_ofertado=Decimal(950),
    )
    assert dentro["necesita_aprobacion"] is False
    fuera = prt.comprobar_descuento(
        uow.db,
        uow.tenant_id,
        partner_id=fila.id,
        precio_lista=Decimal(1000),
        precio_ofertado=Decimal(800),
    )
    assert fuera["necesita_aprobacion"] is True


def test_sin_coste_el_margen_no_se_afirma(uow: UnidadDeTrabajo) -> None:
    fila = _activo(uow)
    salida = prt.comprobar_descuento(
        uow.db,
        uow.tenant_id,
        partner_id=fila.id,
        precio_lista=Decimal(1000),
        precio_ofertado=Decimal(1000),
    )
    assert salida["margen_medido"] is False and salida["margen_pct"] is None


# ── Rendimiento y planes conjuntos (CRM-03.04.01.06) ──────────────────────


def test_el_rendimiento_mide_la_conversion_no_solo_el_importe(uow: UnidadDeTrabajo) -> None:
    """Quien registra treinta y cierra uno bloquea clientes a los demás."""
    fila = _activo(uow)
    for i in range(4):
        registro, _ = prt.registrar_oportunidad(
            uow, partner_id=fila.id, cliente_nombre=f"C{i}", nif=f"A1111111{i}"
        )
        prt.decidir_registro(uow, registro.id, aprobar=True)
        if i == 0:
            prt.vincular_oportunidad(uow, registro.id, oportunidad_id=uuid4())
    salida = prt.rendimiento(
        uow.db,
        uow.tenant_id,
        desde=_hoy() - timedelta(days=1),
        hasta=_hoy() + timedelta(days=1),
        cerrado_por_partner={str(fila.id): Decimal(10000)},
    )
    linea = salida["partners"][0]
    assert linea["registros"] == 4 and linea["convertidos"] == 1
    assert linea["conversion_pct"] == 25.0


def test_sin_lo_cerrado_el_rendimiento_lo_dice(uow: UnidadDeTrabajo) -> None:
    """Los importes a cero no significan que no se haya vendido."""
    _activo(uow)
    salida = prt.rendimiento(uow.db, uow.tenant_id, desde=_hoy(), hasta=_hoy())
    assert salida["medible"] is False and salida["aviso"]


def test_sin_cuota_de_canal_no_se_dice_que_va_bien(uow: UnidadDeTrabajo) -> None:
    fila = _activo(uow)
    salida = prt.rendimiento(
        uow.db,
        uow.tenant_id,
        desde=_hoy() - timedelta(days=1),
        hasta=_hoy() + timedelta(days=1),
        cerrado_por_partner={str(fila.id): Decimal(5000)},
    )
    assert salida["partners"][0]["con_cuota"] is False
    assert salida["partners"][0]["pct_cuota"] is None


def test_la_cuota_de_canal_es_la_misma_cuota(uow: UnidadDeTrabajo) -> None:
    """Con una tabla aparte habría dos formas de calcular lo mismo."""
    from services.sales import territorios as ter

    fila = _activo(uow)
    ter.crear_cuota(
        uow,
        partner_id=fila.id,
        desde=_hoy() - timedelta(days=1),
        hasta=_hoy() + timedelta(days=1),
        objetivo=Decimal(10000),
    )
    salida = prt.rendimiento(
        uow.db,
        uow.tenant_id,
        desde=_hoy() - timedelta(days=1),
        hasta=_hoy() + timedelta(days=1),
        cerrado_por_partner={str(fila.id): Decimal(5000)},
    )
    linea = salida["partners"][0]
    assert linea["con_cuota"] is True and linea["pct_cuota"] == 50.0


def test_un_objetivo_sin_numero_avisa_al_crear_el_plan(uow: UnidadDeTrabajo) -> None:
    """Un plan conjunto en prosa no se revisa en el trimestre siguiente."""
    fila = _activo(uow)
    _, avisos = prt.crear_plan(
        uow,
        fila.id,
        nombre="2026",
        desde=date(2026, 1, 1),
        hasta=date(2026, 12, 31),
        objetivos=[{"metrica": "importe", "objetivo": 100000}, {"metrica": "crecer"}],
    )
    assert len(avisos) == 1


def test_un_objetivo_sin_dato_no_es_un_objetivo_incumplido(uow: UnidadDeTrabajo) -> None:
    fila = _activo(uow)
    plan, _ = prt.crear_plan(
        uow,
        fila.id,
        nombre="2026",
        desde=date(2026, 1, 1),
        hasta=date(2026, 12, 31),
        objetivos=[
            {"metrica": "importe", "objetivo": 100000},
            {"metrica": "leads", "objetivo": 50},
        ],
    )
    revision = prt.revisar_plan(uow, plan.id, logrado={"importe": 60000})
    por_metrica = {d["metrica"]: d for d in revision["detalle"]}
    assert por_metrica["importe"]["pct"] == 60.0
    assert por_metrica["leads"]["medible"] is False
    assert por_metrica["leads"]["pct"] is None
