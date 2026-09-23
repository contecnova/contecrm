"""Golden record, linaje, cola de excepciones, enriquecimiento, B2C, plan de
cuenta, financiero, mapa de influencia y cambio de empresa
(CRM-01.01.01.09, .11, .12 · CRM-01.01.02.03, .07 · CRM-01.01.04.06 a .09).

Lo que persiguen estas pruebas son fichas que cambian solas —el maestro del ERP
que pisa una corrección de esta mañana—, colas de calidad que se vacían sin
arreglar nada, bloqueos basados en datos de hace tres semanas y contactos movidos
de cuenta que dejan a la anterior sin historia.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import ErrorValidacion, NoEncontrado

from services.party import cuenta_360 as c360
from services.party import mdm
from services.party import stewardship as stw

AHORA = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


# ── Golden record (CRM-01.01.04.06) ───────────────────────────────────────


def test_lo_que_escribio_una_persona_no_lo_pisa_un_proceso() -> None:
    """Quien corrige un teléfono a mano está diciendo que el otro estaba mal."""
    salida = mdm.resolver_valor(
        campo="telefono",
        candidatos=[
            {"fuente": "erp", "valor": "900", "cambiado_at": AHORA},
            {"fuente": "manual", "valor": "600", "cambiado_at": AHORA - timedelta(days=5)},
        ],
    )
    assert salida["valor"] == "600"
    assert salida["fuente"] == "manual"


def test_mas_reciente_es_cuando_cambio_el_valor_y_no_cuando_llego_el_mensaje() -> None:
    """Un ERP que reenvía el maestro cada noche trae valores idénticos con fecha
    nueva: con la fecha de llegada, pisan lo que se corrigió esta mañana."""
    salida = mdm.resolver_valor(
        campo="direccion",
        candidatos=[
            {
                "fuente": "erp",
                "valor": "Calle Vieja 1",
                "recibido_at": AHORA,
                "cambiado_at": AHORA - timedelta(days=400),
            },
            {
                "fuente": "web",
                "valor": "Calle Nueva 2",
                "recibido_at": AHORA - timedelta(days=1),
                "cambiado_at": AHORA - timedelta(days=1),
            },
        ],
        estrategia="mas_reciente",
    )
    assert salida["valor"] == "Calle Nueva 2"


def test_si_una_fuente_no_dice_cuando_cambio_se_avisa() -> None:
    salida = mdm.resolver_valor(
        campo="web",
        candidatos=[
            {"fuente": "erp", "valor": "a.com", "recibido_at": AHORA},
            {"fuente": "web", "valor": "b.com", "cambiado_at": AHORA - timedelta(days=1)},
        ],
        estrategia="mas_reciente",
    )
    assert "solo cuándo llegó el mensaje" in salida["porque"]


def test_lo_que_pierde_se_devuelve_como_discrepancia() -> None:
    """Que dos sistemas digan direcciones distintas suele significar que el
    cliente se mudó y solo uno se enteró."""
    salida = mdm.resolver_valor(
        campo="direccion",
        candidatos=[
            {"fuente": "erp", "valor": "A", "cambiado_at": AHORA},
            {"fuente": "web", "valor": "B", "cambiado_at": AHORA},
        ],
        confianza_por_fuente={"erp": 90, "web": 10},
    )
    assert salida["valor"] == "A"
    assert salida["discrepancias"][0]["fuente"] == "web"


def test_hay_campos_que_decide_una_persona() -> None:
    """Elegir automáticamente es lo que produce fichas que cambian solas."""
    salida = mdm.resolver_valor(
        campo="razon_social",
        candidatos=[
            {"fuente": "erp", "valor": "Acme SL"},
            {"fuente": "registro", "valor": "Acme Sociedad Limitada"},
        ],
        estrategia="decide_una_persona",
    )
    assert salida["hay_que_decidir"] is True
    assert salida["valor"] is None


def test_el_golden_dice_de_donde_sale_cada_valor() -> None:
    salida = mdm.componer_golden(
        campos={
            "nif": [{"fuente": "erp", "valor": "B123"}],
            "telefono": [
                {"fuente": "erp", "valor": "900"},
                {"fuente": "manual", "valor": "600"},
            ],
        },
        reglas={},
    )
    assert salida["valores"]["telefono"] == "600"
    assert salida["de_donde_sale_cada_uno"]["nif"]["fuente"] == "erp"
    assert salida["limpio"] is False


def test_una_estrategia_inventada_se_rechaza() -> None:
    with pytest.raises(ErrorValidacion) as fallo:
        mdm.resolver_valor(
            campo="x", candidatos=[{"fuente": "a", "valor": "1"}], estrategia="lo_que_sea"
        )
    assert fallo.value.error_code == "mdm.estrategia_invalida"


# ── Linaje (CRM-01.01.04.07) ──────────────────────────────────────────────


@pytest.mark.db
def test_reenviar_el_mismo_valor_no_lo_marca_como_cambiado(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Es la diferencia entre «esta fuente sigue diciendo lo mismo» y «esta
    fuente lo ha cambiado»."""
    cuenta = uuid4()
    primera = mdm.anotar_linaje(
        uow, objeto="cuenta", objeto_id=cuenta, campo="web", fuente="erp", valor="a.com"
    )
    cambiado = primera.cambiado_at
    segunda = mdm.anotar_linaje(
        uow, objeto="cuenta", objeto_id=cuenta, campo="web", fuente="erp", valor="a.com"
    )
    assert segunda.cambiado_at == cambiado
    tercera = mdm.anotar_linaje(
        uow, objeto="cuenta", objeto_id=cuenta, campo="web", fuente="erp", valor="b.com"
    )
    assert tercera.cambiado_at != cambiado


@pytest.mark.db
def test_sin_linaje_no_se_dice_que_la_ficha_este_al_dia(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """No se ha verificado nunca, que es distinto de estar al día."""
    salida = mdm.valores_obsoletos(uow.db, uow.tenant_id, objeto="cuenta", objeto_id=uuid4())
    assert "nunca se ha verificado" in salida["aviso"]


@pytest.mark.db
def test_confirmar_no_es_cambiar(uow: UnidadDeTrabajo, contexto_tenant: UUID) -> None:
    """Mover también la fecha de cambio haría que el dato pareciera recién
    actualizado y todos los informes de antigüedad dirían algo falso."""
    cuenta = uuid4()
    fila = mdm.anotar_linaje(
        uow, objeto="cuenta", objeto_id=cuenta, campo="nif", fuente="erp", valor="B1"
    )
    antes = fila.cambiado_at
    salida = mdm.confirmar_frescura(
        uow, objeto="cuenta", objeto_id=cuenta, campo="nif", fuente="erp"
    )
    assert salida["el_valor_no_ha_cambiado"] is True
    assert fila.cambiado_at == antes


@pytest.mark.db
def test_no_se_puede_confirmar_lo_que_no_consta_de_donde_vino(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    with pytest.raises(ErrorValidacion) as fallo:
        mdm.confirmar_frescura(uow, objeto="cuenta", objeto_id=uuid4(), campo="x", fuente="y")
    assert fallo.value.error_code == "mdm.sin_linaje"


def test_un_plazo_de_cero_dias_lo_marca_todo_obsoleto() -> None:
    """Produce una cola con todo dentro, que nadie mira: peor que no tenerla."""
    salida = mdm.caducidad_declarada({"telefono": 0})
    assert salida["valido"] is False


# ── Cola de excepciones (CRM-01.01.04.08) ─────────────────────────────────


@pytest.mark.db
def test_la_misma_regla_sobre_la_misma_ficha_no_abre_diez_excepciones(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Sin esto, el proceso nocturno abre otra cada noche y a la semana hay tres
    mil que son siete."""
    cuenta = uuid4()
    a = stw.abrir(
        uow,
        objeto="cuenta",
        objeto_id=cuenta,
        tipo="falta_obligatorio",
        regla="sector_obligatorio",
        detalle="falta el sector",
        campo="sector_codigo",
    )
    b = stw.abrir(
        uow,
        objeto="cuenta",
        objeto_id=cuenta,
        tipo="falta_obligatorio",
        regla="sector_obligatorio",
        detalle="falta el sector",
        campo="sector_codigo",
    )
    assert a.id == b.id


@pytest.mark.db
def test_una_excepcion_sin_regla_no_se_abre(uow: UnidadDeTrabajo, contexto_tenant: UUID) -> None:
    """Es lo que permite descubrir después que una regla genera ruido."""
    with pytest.raises(ErrorValidacion) as fallo:
        stw.abrir(
            uow,
            objeto="cuenta",
            objeto_id=uuid4(),
            tipo="falta_obligatorio",
            regla="  ",
            detalle="x",
        )
    assert fallo.value.error_code == "calidad.sin_regla"


@pytest.mark.db
def test_cerrar_como_no_era_un_error_exige_motivo(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Dentro de seis meses nadie sabrá si la regla estaba mal."""
    fila = stw.abrir(
        uow,
        objeto="cuenta",
        objeto_id=uuid4(),
        tipo="formato_invalido",
        regla="nif_formato",
        detalle="x",
    )
    with pytest.raises(ErrorValidacion) as fallo:
        stw.cerrar(uow, excepcion_id=fila.id, cierre="no_era_un_error", nota="", por=uuid4())
    assert fallo.value.error_code == "calidad.cierre_sin_motivo"


@pytest.mark.db
def test_la_cola_cuenta_aparte_las_que_no_tiene_nadie(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Son las que no se van a hacer: una cola sin dueño crece hasta que nadie la
    abre."""
    stw.abrir(
        uow,
        objeto="cuenta",
        objeto_id=uuid4(),
        tipo="falta_obligatorio",
        regla="r1",
        detalle="x",
    )
    salida = stw.cola(uow.db, uow.tenant_id)
    assert salida["sin_asignar"] == 1
    assert "nadie la abre" in salida["aviso"]


@pytest.mark.db
def test_una_regla_que_todo_el_mundo_descarta_sale_como_sospechosa(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Si cinco personas dicen que no es un error, la rota es la regla."""
    for _ in range(6):
        fila = stw.abrir(
            uow,
            objeto="cuenta",
            objeto_id=uuid4(),
            tipo="formato_invalido",
            regla="telefono_raro",
            detalle="x",
        )
        stw.cerrar(
            uow,
            excepcion_id=fila.id,
            cierre="no_era_un_error",
            nota="es una extensión interna",
            por=uuid4(),
        )
    salida = stw.reglas_sospechosas(uow.db, uow.tenant_id)
    assert salida["reglas"][0]["regla"] == "telefono_raro"


@pytest.mark.db
def test_una_excepcion_cerrada_no_se_reasigna(uow: UnidadDeTrabajo, contexto_tenant: UUID) -> None:
    fila = stw.abrir(
        uow, objeto="cuenta", objeto_id=uuid4(), tipo="sin_propietario", regla="r", detalle="x"
    )
    stw.cerrar(uow, excepcion_id=fila.id, cierre="corregido", nota="", por=uuid4())
    with pytest.raises(ErrorValidacion) as fallo:
        stw.asignar(uow, excepcion_id=fila.id, a=uuid4())
    assert fallo.value.error_code == "calidad.ya_cerrada"


# ── Enriquecimiento (CRM-01.01.04.09, CRM-01.01.01.08) ────────────────────


def test_se_dice_cuanto_va_a_costar_antes_de_gastarlo() -> None:
    """Un botón de «enriquecer todo» sobre cuarenta mil cuentas es una factura
    que nadie aprobó."""
    salida = stw.planificar_enriquecimiento(
        candidatas=[{"id": str(i), "faltan": ["sector"], "valor": i} for i in range(10)],
        coste_por_consulta=0.5,
        presupuesto=2.0,
    )
    assert salida["se_consultan"] == 4
    assert salida["coste_estimado"] == 2.0
    assert salida["se_ejecuta_ya"] is False


def test_no_se_enriquecen_las_inactivas() -> None:
    """Gasta el presupuesto en fichas que nadie va a abrir."""
    salida = stw.planificar_enriquecimiento(
        candidatas=[
            {"id": "1", "faltan": ["sector"], "activa": False},
            {"id": "2", "faltan": ["sector"]},
        ],
        coste_por_consulta=1.0,
    )
    assert salida["se_consultan"] == 1
    assert salida["descartadas_por_inactivas_o_completas"] == 1


def test_el_enriquecimiento_rellena_huecos_y_no_corrige_a_las_personas() -> None:
    """El proveedor sabe de muchas empresas y no conoce a ninguna."""
    salida = stw.aplicar_enriquecimiento(
        actuales={"telefono": "600", "sector_codigo": None},
        del_proveedor={"telefono": "900", "sector_codigo": "6201"},
        escritos_a_mano=["telefono"],
    )
    assert salida["aplicados"] == {"sector_codigo": "6201"}
    assert salida["campos_manuales_respetados"] == ["telefono"]
    assert salida["discrepancias"][0]["campo"] == "telefono"


def test_nunca_enriquecido_no_es_lo_mismo_que_hace_mucho() -> None:
    salida = stw.caducidad_del_enriquecimiento(ultimo_at=None, ahora=AHORA)
    assert salida["nunca_consultado"] is True


# ── Cuentas personales (CRM-01.01.01.09) ──────────────────────────────────


def test_una_cuenta_personal_es_dato_personal_entera() -> None:
    """El nombre de la cuenta es el nombre de alguien y su dirección es su
    domicilio."""
    salida = c360.validar_cuenta_personal(datos={"nombre": "Ana Pérez"})
    assert salida["es_dato_personal_toda_la_ficha"] is True
    assert "la cuenta entera" in salida["que_implica"]


def test_los_campos_de_empresa_en_una_cuenta_personal_se_avisan() -> None:
    """Exigirlos es lo que hace que alguien escriba cualquier cosa para poder
    guardar."""
    salida = c360.validar_cuenta_personal(datos={"nombre": "Ana", "empleados": 1})
    assert "empleados" in salida["campos_de_empresa_presentes"]


# ── Plan de cuenta (CRM-01.01.01.11) ──────────────────────────────────────


def test_el_hueco_se_calcula_y_no_se_teclea() -> None:
    """Tecleado sale lo que el comercial tiene en la cabeza, no lo que nadie ha
    mirado."""
    salida = c360.calcular_hueco(
        catalogo=[
            {"clave": "a", "familia": "F", "potencial": 10},
            {"clave": "b", "familia": "F", "potencial": 90},
        ],
        ya_le_vendemos=["a"],
    )
    assert [h["producto"] for h in salida["hueco"]] == ["b"]
    assert salida["pct_cubierto"] == 50.0


@pytest.mark.db
def test_un_objetivo_sin_fecha_ni_dueno_no_es_un_objetivo(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Un plan de frases se revisa una vez: en la reunión en la que se escribió."""
    with pytest.raises(ErrorValidacion) as fallo:
        c360.guardar_plan(
            uow,
            cuenta_id=uuid4(),
            periodo="2026",
            objetivos=[{"titulo": "crecer"}],
            riesgos=[],
            hueco=[],
        )
    assert fallo.value.error_code == "plan.objetivo_incompleto"


def test_un_plan_que_nadie_revisa_se_avisa() -> None:
    salida = c360.plan_caducado(revisado_at=AHORA - timedelta(days=200), ahora=AHORA)
    assert salida["caducado"] is True
    assert "es un documento" in salida["porque"]


# ── Estado financiero (CRM-01.01.01.12) ───────────────────────────────────


@pytest.mark.db
def test_un_bloqueo_sin_motivo_no_se_guarda(uow: UnidadDeTrabajo, contexto_tenant: UUID) -> None:
    """El comercial tiene que poder decirle al cliente algo que no sea «el
    sistema no me deja»."""
    with pytest.raises(ErrorValidacion) as fallo:
        c360.replicar_financiero(
            uow,
            cuenta_id=uuid4(),
            estado="bloqueado",
            origen="erp",
            vigente_at=AHORA,
            bloqueado=True,
        )
    assert fallo.value.error_code == "financiero.bloqueo_sin_motivo"


@pytest.mark.db
def test_sin_dato_financiero_no_se_dice_que_esta_al_corriente(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """No es que esté al corriente: es que no se sabe, y no es lo mismo."""
    salida = c360.puede_comprometer(
        uow.db, uow.tenant_id, cuenta_id=uuid4(), importe=Decimal(100), ahora=AHORA
    )
    assert salida["puede"] is None
    assert salida["fiable"] is False


@pytest.mark.db
def test_un_dato_financiero_viejo_avisa_de_que_el_bloqueo_es_una_suposicion(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """El comercial deja de creerse un bloqueo basado en algo de hace tres
    semanas."""
    cuenta = uuid4()
    c360.replicar_financiero(
        uow,
        cuenta_id=cuenta,
        estado="al_corriente",
        origen="erp",
        vigente_at=AHORA - timedelta(days=21),
        limite_credito=Decimal(1000),
        credito_dispuesto=Decimal(0),
    )
    salida = c360.puede_comprometer(
        uow.db, uow.tenant_id, cuenta_id=cuenta, importe=Decimal(100), ahora=AHORA
    )
    assert salida["puede"] is True
    assert salida["fiable"] is False
    assert "21 días" in salida["aviso"]


@pytest.mark.db
def test_sin_limite_de_credito_no_se_trata_como_ilimitado(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Es una decisión que nadie ha tomado."""
    cuenta = uuid4()
    c360.replicar_financiero(
        uow, cuenta_id=cuenta, estado="al_corriente", origen="erp", vigente_at=AHORA
    )
    salida = c360.puede_comprometer(
        uow.db, uow.tenant_id, cuenta_id=cuenta, importe=Decimal(1), ahora=AHORA
    )
    assert salida["puede"] is None


@pytest.mark.db
def test_una_cuenta_bloqueada_dice_que_decirle_al_cliente(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    cuenta = uuid4()
    c360.replicar_financiero(
        uow,
        cuenta_id=cuenta,
        estado="bloqueado",
        origen="erp",
        vigente_at=AHORA,
        bloqueado=True,
        motivo_bloqueo="tres facturas vencidas de más de 90 días",
    )
    salida = c360.puede_comprometer(
        uow.db, uow.tenant_id, cuenta_id=cuenta, importe=Decimal(1), ahora=AHORA
    )
    assert salida["puede"] is False
    assert "90 días" in salida["que_decirle_al_cliente"]


# ── Mapa de influencia (CRM-01.01.02.03) ──────────────────────────────────


@pytest.mark.db
def test_llamar_detractor_a_alguien_exige_motivo(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Sin el porqué es un rumor guardado en una base de datos, y si esa persona
    ejerce su derecho de acceso, lo que sale es eso."""
    with pytest.raises(ErrorValidacion) as fallo:
        c360.anotar_relacion(
            uow, origen_id=uuid4(), destino_id=uuid4(), tipo="detractor", motivo=""
        )
    assert fallo.value.error_code == "relacion.opinion_sin_motivo"


@pytest.mark.db
def test_una_jerarquia_no_necesita_motivo(uow: UnidadDeTrabajo, contexto_tenant: UUID) -> None:
    """«Reporta a» es un hecho, no una opinión."""
    fila = c360.anotar_relacion(
        uow, origen_id=uuid4(), destino_id=uuid4(), tipo="reporta_a", motivo=""
    )
    assert fila.tipo == "reporta_a"


@pytest.mark.db
def test_el_mapa_enseña_con_quien_no_se_ha_hablado_nunca(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Es lo único que este mapa aporta que el comercial no supiera ya."""
    salida = c360.mapa_de_poder(
        uow.db,
        uow.tenant_id,
        contactos=[
            {"id": str(uuid4()), "nombre": "A", "rol_compra": "decisor"},
            {"id": str(uuid4()), "nombre": "B", "ultima_interaccion": AHORA},
        ],
    )
    assert len(salida["decisores_sin_hablar"]) == 1


# ── Cambio de empresa (CRM-01.01.02.07) ───────────────────────────────────


@pytest.mark.db
def test_un_rebote_abre_sospecha_y_no_cambia_la_ficha(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Un correo que rebota puede ser un buzón lleno: cambiar la ficha deja a un
    cliente activo marcado como que se fue."""
    fila = c360.detectar_cambio(
        uow,
        contacto_id=uuid4(),
        cuenta_anterior_id=uuid4(),
        indicio="correo_rebotado",
        detalle="rebote permanente",
    )
    assert fila.estado == "detectado"


@pytest.mark.db
def test_confirmar_no_mueve_el_contacto_de_cuenta(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Mover la ficha reescribe la historia: la cuenta antigua pasaría a no haber
    hablado nunca con nadie."""
    contacto = uuid4()
    fila = c360.detectar_cambio(
        uow,
        contacto_id=contacto,
        cuenta_anterior_id=uuid4(),
        indicio="aparece_en_otra_cuenta",
        detalle="firma nueva",
    )
    with pytest.raises(ErrorValidacion) as fallo:
        c360.confirmar_cambio(
            uow, cambio_id=fila.id, cuenta_nueva_id=uuid4(), contacto_nuevo_id=contacto
        )
    assert fallo.value.error_code == "cambio.no_se_mueve"

    salida = c360.confirmar_cambio(
        uow, cambio_id=fila.id, cuenta_nueva_id=uuid4(), contacto_nuevo_id=uuid4()
    )
    assert salida["la_historia_se_queda_donde_estaba"] is True
    assert "Llamarle" in salida["que_hacer_ahora"]


@pytest.mark.db
def test_descartar_un_indicio_exige_motivo(uow: UnidadDeTrabajo, contexto_tenant: UUID) -> None:
    """Sin motivo, el mismo rebote vuelve a abrir la sospecha la semana que
    viene, y a la quinta se deja de mirar la cola."""
    fila = c360.detectar_cambio(
        uow, contacto_id=uuid4(), cuenta_anterior_id=None, indicio="correo_rebotado", detalle="x"
    )
    with pytest.raises(ErrorValidacion) as fallo:
        c360.descartar_cambio(uow, cambio_id=fila.id, motivo="  ")
    assert fallo.value.error_code == "cambio.descarte_sin_motivo"


@pytest.mark.db
def test_un_cambio_que_no_existe_se_dice(uow: UnidadDeTrabajo, contexto_tenant: UUID) -> None:
    with pytest.raises(NoEncontrado):
        c360.descartar_cambio(uow, cambio_id=uuid4(), motivo="x")
