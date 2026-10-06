"""Maestro y gobierno del proveedor (CRM-09.01.01.01 a .10).

Un CRM que solo mira al cliente cuenta media historia: en muchos negocios quien
da el servicio es un proveedor, y lo que se le promete al cliente depende de lo
que sostenga él. Estas pruebas van detrás de lo que se descubre tarde — el seguro
vencido, la homologación eterna, el proveedor único sin alternativa y el SLA que
se firma sin comparar con el de quien va a ir.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion
from crmcore.fechas import hoy

from services.party import proveedores as prv
from services.party.modelos import Cuenta
from services.sales import proveedores_comercial as pcom
from services.service import proveedores_sla as psla

# ANCLADO AL DÍA DE HOY, no a una fecha escrita.
#
# Era `date(2026, 9, 23)`, y el 4 de octubre la suite empezó a fallar sola: las
# pruebas que piden una homologación «válida hasta dentro de diez días» pasaron
# a pedirla con una fecha ya pasada, y el producto —con razón— las rechaza. Una
# fecha fija en una prueba es una bomba de relojería: funciona hasta que no, y
# el día que revienta no hay ningún cambio que lo explique.
HOY = hoy()


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


def _cuenta(uow: UnidadDeTrabajo, *, roles: list[str] | None = None) -> Cuenta:
    fila = Cuenta(
        tenant_id=uow.tenant_id,
        nombre="Suministros Acme",
        clave_canonica="suministros acme",
        roles=roles if roles is not None else ["cliente"],
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila


# ── El proveedor es una cuenta (CRM-09.01.01.01) ──────────────────────────


@pytest.mark.db
def test_el_rol_de_proveedor_se_suma_y_no_sustituye(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """La misma empresa puede ser cliente de una división y proveedor de otra:
    sustituir el rol le aplicaría las condiciones de la ficha equivocada."""
    cuenta = _cuenta(uow)
    salida = prv.marcar_como_proveedor(uow, cuenta_id=cuenta.id)
    assert set(salida["roles"]) == {"cliente", "proveedor"}


@pytest.mark.db
def test_tratar_como_proveedor_a_quien_no_lo_es_se_rechaza(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """No aparecería en ninguna lista de proveedores y nadie revisaría sus
    papeles."""
    cuenta = _cuenta(uow)
    with pytest.raises(ErrorValidacion) as fallo:
        prv.exigir_proveedor(uow.db, uow.tenant_id, cuenta.id)
    assert fallo.value.error_code == "proveedor.sin_rol"


# ── Homologación (CRM-09.01.01.02) ────────────────────────────────────────


@pytest.mark.db
def test_no_se_homologa_con_salvedades(uow: UnidadDeTrabajo, contexto_tenant: UUID) -> None:
    """Nadie vuelve a mirar la salvedad, y el día que pasa algo la salvedad era
    justo eso."""
    cuenta = _cuenta(uow, roles=["proveedor"])
    with pytest.raises(ErrorValidacion) as fallo:
        prv.homologar(
            uow,
            cuenta_id=cuenta.id,
            categoria="trabajos_en_altura",
            requisitos=[
                {"clave": "seguro_rc", "cubierto": True},
                {"clave": "formacion", "cubierto": False},
            ],
            valida_hasta=HOY + timedelta(days=365),
            revisada_por=uuid4(),
        )
    assert fallo.value.error_code == "proveedor.requisitos_incompletos"


@pytest.mark.db
def test_una_homologacion_sin_fecha_de_fin_no_se_guarda(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """A los cinco años nadie sabe si esa empresa sigue teniendo los medios que
    tenía cuando se la aprobó."""
    cuenta = _cuenta(uow, roles=["proveedor"])
    with pytest.raises(ErrorValidacion) as fallo:
        prv.homologar(
            uow,
            cuenta_id=cuenta.id,
            categoria="oficina",
            requisitos=[{"clave": "alta_censal", "cubierto": True}],
            valida_hasta=None,
            revisada_por=uuid4(),
        )
    assert fallo.value.error_code == "proveedor.homologacion_sin_fin"


@pytest.mark.db
def test_homologado_para_una_cosa_no_vale_para_otra(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Uno puede servir material de oficina y no hacer trabajos en altura."""
    cuenta = _cuenta(uow, roles=["proveedor"])
    prv.homologar(
        uow,
        cuenta_id=cuenta.id,
        categoria="oficina",
        requisitos=[{"clave": "alta_censal", "cubierto": True}],
        valida_hasta=HOY + timedelta(days=200),
        revisada_por=uuid4(),
    )
    assert prv.esta_homologado(
        uow.db, uow.tenant_id, cuenta_id=cuenta.id, categoria="oficina", hoy=HOY
    )["puede"]
    otra = prv.esta_homologado(
        uow.db, uow.tenant_id, cuenta_id=cuenta.id, categoria="altura", hoy=HOY
    )
    assert otra["puede"] is False
    assert otra["motivo"] == "sin_homologar"


@pytest.mark.db
def test_se_distingue_caducada_de_sin_homologar(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Una exige empezar el proceso y la otra solo papel nuevo: confundirlas hace
    que se descarte a un proveedor que valdría mañana."""
    cuenta = _cuenta(uow, roles=["proveedor"])
    prv.homologar(
        uow,
        cuenta_id=cuenta.id,
        categoria="oficina",
        requisitos=[{"clave": "x", "cubierto": True}],
        valida_hasta=HOY + timedelta(days=10),
        revisada_por=uuid4(),
    )
    salida = prv.esta_homologado(
        uow.db,
        uow.tenant_id,
        cuenta_id=cuenta.id,
        categoria="oficina",
        hoy=HOY + timedelta(days=30),
    )
    assert salida["motivo"] == "caducada"
    assert "no hay que empezar de cero" in salida["que_hacer"].lower()


@pytest.mark.db
def test_una_categoria_rechazada_no_se_rehomologa_sin_mirar_el_motivo(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Rechazada no es caducada: repetirlo sin revisar es repetir una decisión que
    alguien tomó por algo."""
    cuenta = _cuenta(uow, roles=["proveedor"])
    fila = prv.Homologacion(
        tenant_id=uow.tenant_id,
        cuenta_id=cuenta.id,
        categoria="altura",
        estado="rechazada",
        motivo="sin medios propios",
    )
    uow.db.add(fila)
    uow.db.flush()
    with pytest.raises(Conflicto) as fallo:
        prv.homologar(
            uow,
            cuenta_id=cuenta.id,
            categoria="altura",
            requisitos=[{"clave": "x", "cubierto": True}],
            valida_hasta=HOY + timedelta(days=100),
            revisada_por=uuid4(),
        )
    assert fallo.value.error_code == "proveedor.estaba_rechazada"


# ── Documentos con vigencia (CRM-09.01.01.03) ─────────────────────────────


@pytest.mark.db
def test_un_documento_sin_referencia_es_una_fila_que_miente(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Dice que el papel existe sin que nadie pueda verlo."""
    cuenta = _cuenta(uow, roles=["proveedor"])
    with pytest.raises(ErrorValidacion) as fallo:
        prv.registrar_documento(
            uow,
            cuenta_id=cuenta.id,
            clave="seguro_rc",
            nombre="Seguro",
            referencia="  ",
            valido_hasta=HOY,
        )
    assert fallo.value.error_code == "proveedor.documento_sin_referencia"


@pytest.mark.db
def test_un_documento_vencido_que_bloquea_bloquea_solo(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Uno que hay que mirar a mano no se mira: se descubre cuando el cliente
    pregunta con qué seguro se hizo el trabajo."""
    cuenta = _cuenta(uow, roles=["proveedor"])
    prv.registrar_documento(
        uow,
        cuenta_id=cuenta.id,
        clave="seguro_rc",
        nombre="Seguro RC",
        referencia="doc-1",
        valido_hasta=HOY - timedelta(days=1),
    )
    salida = prv.estado_documental(uow.db, uow.tenant_id, cuenta_id=cuenta.id, hoy=HOY)
    assert salida["bloqueado"] is True


@pytest.mark.db
def test_sin_documentos_no_se_dice_que_este_todo_en_regla(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    cuenta = _cuenta(uow, roles=["proveedor"])
    salida = prv.estado_documental(uow.db, uow.tenant_id, cuenta_id=cuenta.id, hoy=HOY)
    assert salida["medible"] is False
    assert "no se ha pedido nada" in salida["aviso"]


@pytest.mark.db
def test_se_avisa_antes_de_que_venza_y_no_el_mismo_dia(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Renovar un seguro lleva semanas: avisar el día que vence es no avisar."""
    cuenta = _cuenta(uow, roles=["proveedor"])
    prv.registrar_documento(
        uow,
        cuenta_id=cuenta.id,
        clave="seguro_rc",
        nombre="Seguro",
        referencia="doc-1",
        valido_hasta=HOY + timedelta(days=10),
    )
    salida = prv.estado_documental(uow.db, uow.tenant_id, cuenta_id=cuenta.id, hoy=HOY)
    assert salida["por_vencer"][0]["dias"] == 10
    assert salida["bloqueado"] is False


# ── Riesgo (CRM-09.01.01.04) ──────────────────────────────────────────────


def test_sin_volumen_no_se_habla_de_concentracion() -> None:
    """Se puede opinar, que no es lo mismo."""
    salida = prv.riesgo_de_dependencia(proveedores=[{"id": "1", "nombre": "A"}])
    assert salida["medible"] is False


def test_el_riesgo_es_depender_sin_alternativa() -> None:
    """Lo que hace daño no es un proveedor malo: es un proveedor bueno del que se
    depende y que no tiene alternativa."""
    salida = prv.riesgo_de_dependencia(
        proveedores=[
            {"id": "1", "nombre": "Único", "volumen": 70},
            {"id": "2", "nombre": "Otro", "volumen": 30, "alternativas_homologadas": ["1"]},
        ]
    )
    assert [c["nombre"] for c in salida["criticos"]] == ["Único"]
    assert "solo que contar" in salida["que_significa"]


def test_un_proveedor_grande_con_alternativa_no_es_critico() -> None:
    salida = prv.riesgo_de_dependencia(
        proveedores=[{"id": "1", "volumen": 90, "alternativas_homologadas": ["2"]}]
    )
    assert salida["criticos"] == []


# ── Evaluación (CRM-09.01.01.05) ──────────────────────────────────────────


def test_sin_entregas_no_se_puntua_a_un_proveedor() -> None:
    """Uno al que no se le ha encargado nada no es bueno ni malo: no se sabe."""
    salida = prv.evaluar(entregas=[], incidencias=[])
    assert salida["medible"] is False


def test_la_evaluacion_va_con_hechos_y_la_encuesta_se_marca_como_otra_cosa() -> None:
    """Una encuesta anual mide la relación con el comercial del proveedor."""
    salida = prv.evaluar(
        entregas=[{"en_plazo": True}, {"en_plazo": False}],
        incidencias=[{"gravedad": "critica"}],
        encuesta=9,
    )
    assert salida["pct_en_plazo"] == 50.0
    assert salida["incidencias_graves"] == 1
    assert "relación con su comercial" in salida["aviso"]


# ── Contactos por función (CRM-09.01.01.06) ───────────────────────────────


@pytest.mark.db
def test_si_no_hay_a_quien_escalar_se_dice(uow: UnidadDeTrabajo, contexto_tenant: UUID) -> None:
    """Dar el teléfono del comercial a las once de la noche no es una respuesta."""
    cuenta = _cuenta(uow, roles=["proveedor"])
    prv.registrar_contacto(uow, cuenta_id=cuenta.id, funcion="comercial", nombre="A", email="a@b.c")
    salida = prv.a_quien_llamo(uow.db, uow.tenant_id, cuenta_id=cuenta.id, funcion="escalado")
    assert salida["hay"] is False
    assert salida["funciones_que_si_hay"] == ["comercial"]


@pytest.mark.db
def test_un_escalado_sin_telefono_fuera_de_horario_se_marca(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Es el dato que nadie tiene cuando hace falta."""
    cuenta = _cuenta(uow, roles=["proveedor"])
    prv.registrar_contacto(uow, cuenta_id=cuenta.id, funcion="escalado", nombre="B", email="b@b.c")
    salida = prv.a_quien_llamo(uow.db, uow.tenant_id, cuenta_id=cuenta.id, funcion="escalado")
    assert salida["sin_telefono_fuera_de_horario"] == ["B"]


# ── Contrato y alcance (CRM-09.01.01.07, .09) ─────────────────────────────


def test_el_contrato_avisa_por_lo_vendido_y_no_solo_por_su_fecha() -> None:
    """Los compromisos posteriores al fin del contrato son los que se quedan sin
    nadie detrás."""
    salida = pcom.estado_del_contrato(
        vigente_hasta=HOY + timedelta(days=60),
        renovacion_automatica=False,
        dias_preaviso=30,
        compromisos_con_clientes=[
            {"referencia": "OP-1", "fecha": HOY + timedelta(days=90)},
            {"referencia": "OP-2", "fecha": HOY + timedelta(days=10)},
        ],
        hoy=HOY,
    )
    assert [c["referencia"] for c in salida["compromisos_sin_cobertura"]] == ["OP-1"]


def test_un_preaviso_pasado_con_renovacion_automatica_se_dice() -> None:
    """Se renueva solo aunque nadie lo quiera, y eso se descubre con la factura."""
    salida = pcom.estado_del_contrato(
        vigente_hasta=HOY + timedelta(days=10),
        renovacion_automatica=True,
        dias_preaviso=30,
        hoy=HOY,
    )
    assert salida["preaviso_pasado"] is True
    assert "se renueva solo" in salida["aviso"]


def test_un_contrato_sin_vigencia_no_es_indefinido() -> None:
    """Es que nadie lo ha escrito, y el día que el proveedor diga que terminó no
    habrá con qué discutirlo."""
    salida = pcom.estado_del_contrato(
        vigente_hasta=None, renovacion_automatica=False, dias_preaviso=30, hoy=HOY
    )
    assert salida["fiable"] is False


def test_el_alcance_se_declara_en_positivo() -> None:
    """La lista de exclusiones nunca está completa, porque nadie piensa en lo que
    todavía no ha pasado."""
    salida = pcom.declarar_alcance(alcance={"geografia": ["ES-MD", "ES-B"], "categoria": []})
    assert salida["alcance"] == {"geografia": ["ES-B", "ES-MD"]}
    assert "categoria" in salida["ejes_sin_acotar"]


def test_se_dice_por_que_un_proveedor_no_puede_servir_un_caso() -> None:
    """En un caso se busca otro proveedor y en el otro se cambia lo que se
    ofrece."""
    salida = pcom.puede_servir(
        alcance={"geografia": ["ES-MD"], "categoria": ["oficina"]},
        categoria="oficina",
        geografia="ES-GC",
    )
    assert salida["puede"] is False
    assert "promesa sin nadie detrás" in salida["motivos"][0]


def test_un_eje_inventado_se_rechaza() -> None:
    with pytest.raises(ErrorValidacion) as fallo:
        pcom.declarar_alcance(alcance={"color": ["azul"]})
    assert fallo.value.error_code == "proveedor.eje_invalido"


# ── SLA del proveedor frente al del cliente (CRM-09.01.01.08) ─────────────


def test_no_se_puede_prometer_mejor_de_lo_que_sostiene_el_proveedor() -> None:
    """Comercial promete cuatro horas porque es lo que pide el pliego, y el
    proveedor que va a ir tiene contratadas ocho."""
    salida = psla.comparar(
        prometido_al_cliente={"respuesta_h": 4},
        del_proveedor={"respuesta_h": 8},
    )
    assert salida["se_sostiene"] is False
    assert salida["problemas"][0]["hace_falta_al_menos"] == 9.0


def test_los_tiempos_se_suman() -> None:
    """Prometer el mismo tiempo del proveedor es prometer uno que solo existiría
    si nosotros no hiciéramos nada."""
    salida = psla.maximo_que_se_puede_prometer(del_proveedor={"respuesta_h": 4}, horas_propias=2)
    assert salida["maximo"]["respuesta_h"] == 6.0


def test_lo_que_el_proveedor_no_declara_no_se_da_por_bueno() -> None:
    """No es que lo tenga bien: es que no lo ha dicho, y firmarlo así es firmar
    sin saber."""
    salida = psla.comparar(
        prometido_al_cliente={"respuesta_h": 24, "resolucion_h": 48},
        del_proveedor={"respuesta_h": 8},
    )
    assert salida["sin_declarar_por_el_proveedor"] == ["resolucion_h"]
    assert salida["se_sostiene"] is False


def test_sin_acuerdo_del_proveedor_no_se_adivina() -> None:
    with pytest.raises(ErrorValidacion) as fallo:
        psla.maximo_que_se_puede_prometer(del_proveedor={})
    assert fallo.value.error_code == "sla.proveedor_sin_acuerdo"


def test_una_cobertura_menor_que_la_prometida_se_caza() -> None:
    """Lo que pase fuera de su horario lo cubre quien lo firmó."""
    salida = psla.comparar(
        prometido_al_cliente={"cobertura_horaria": "24x7"},
        del_proveedor={"cobertura_horaria": "L-V 9-18"},
    )
    assert salida["se_sostiene"] is False


# ── Baja (CRM-09.01.01.10) ────────────────────────────────────────────────


def test_no_se_da_de_baja_a_quien_tiene_trabajo_comprometido() -> None:
    """Quitarlo del maestro no cancela lo vendido: hace que el día de la entrega
    nadie sepa quién tenía que ir."""
    salida = prv.puede_darse_de_baja(
        compromisos_abiertos=[{"referencia": "OT-1"}], alternativas_homologadas=2
    )
    assert salida["puede"] is False


def test_dar_de_baja_al_unico_homologado_deja_un_hueco_y_se_dice() -> None:
    """Homologar a otro lleva semanas: conviene tenerlo antes."""
    salida = prv.puede_darse_de_baja(compromisos_abiertos=[], alternativas_homologadas=0)
    assert salida["puede"] is True
    assert salida["deja_hueco"] is True
