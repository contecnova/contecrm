"""Campañas, atribución, presión de contacto y rebotes
(CRM-02.02.01, CRM-02.02.02.06, CRM-02.03.01.04).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion
from crmcore.fechas import hoy

from services.marketing import campanas as cmp
from services.marketing import segmentos as seg

HOY = hoy()


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


def _campana(uow: Any, **kw: Any) -> Any:
    base = {"clave": "otono", "nombre": "Campaña de otoño"}
    base.update(kw)
    return cmp.crear(uow, **base)


# ── Jerarquía y presupuesto (CRM-02.02.01.01) ─────────────────────────────


@pytest.mark.db
def test_una_tactica_no_puede_tener_debajo_un_programa(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Sin la comprobación, el árbol se desordena en dos semanas y el consumo de
    presupuesto deja de poder subir."""
    tactica = _campana(uow, clave="t", nivel="tactica")
    db.flush()
    with pytest.raises(ErrorValidacion) as e:
        _campana(uow, clave="p", nivel="programa", padre_id=tactica.id)
    assert e.value.error_code == "marketing.jerarquia_invalida"


@pytest.mark.db
def test_el_gasto_sube_por_la_jerarquia(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Se imputa donde ocurre y sube al consultarlo: sumarlo al escribir obligaría
    a recalcular todo cada vez que alguien mueve una táctica."""
    programa = _campana(uow, clave="prog", nivel="programa", presupuesto=Decimal("10000"))
    campana = _campana(uow, clave="camp", nivel="campana", padre_id=programa.id)
    tactica = _campana(uow, clave="tact", nivel="tactica", padre_id=campana.id)
    db.flush()

    cmp.imputar_gasto(uow, tactica.id, importe=Decimal("1500"), concepto="anuncios")
    cmp.imputar_gasto(uow, campana.id, importe=Decimal("500"), concepto="diseño")
    db.flush()

    salida = cmp.consumo(db, tenant_id, programa.id)
    assert Decimal(salida["gasto"]) == Decimal("2000")
    assert Decimal(salida["restante"]) == Decimal("8000")
    assert salida["consumido_pct"] == 20.0


@pytest.mark.db
def test_se_dice_si_lo_de_abajo_supera_lo_de_arriba(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """No es un fallo, es un aviso de planificación, pero enseñarlo evita la
    sorpresa de octubre."""
    programa = _campana(uow, clave="prog", nivel="programa", presupuesto=Decimal("1000"))
    _campana(uow, clave="c1", nivel="campana", padre_id=programa.id, presupuesto=Decimal("800"))
    _campana(uow, clave="c2", nivel="campana", padre_id=programa.id, presupuesto=Decimal("800"))
    db.flush()
    assert cmp.consumo(db, tenant_id, programa.id)["hijos_presupuestados_de_mas"] is True


@pytest.mark.db
def test_no_se_imputa_gasto_negativo(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    campana = _campana(uow)
    db.flush()
    with pytest.raises(ErrorValidacion) as e:
        cmp.imputar_gasto(uow, campana.id, importe=Decimal("-100"))
    assert e.value.error_code == "marketing.gasto_negativo"


# ── Calendario (CRM-02.02.01.03) ──────────────────────────────────────────


@pytest.mark.db
def test_el_solapamiento_es_de_audiencia_y_canal_no_de_fechas(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Dos campañas la misma semana a públicos distintos no molestan a nadie; dos
    al mismo público por el mismo canal sí."""
    segmento = uuid4()
    for clave, seg_id, canal in (
        ("a", segmento, "email"),
        ("b", segmento, "email"),
        ("c", segmento, "sms"),
        ("d", uuid4(), "email"),
    ):
        _campana(
            uow,
            clave=clave,
            nivel="campana",
            estado="en_curso",
            canal=canal,
            segmento_id=seg_id,
            desde=HOY,
            hasta=HOY + timedelta(days=7),
        )
    db.flush()

    salida = cmp.calendario(db, tenant_id, desde=HOY, hasta=HOY + timedelta(days=7))
    choques = {tuple(sorted((c["a"], c["b"]))) for c in salida["solapamientos"]}
    assert choques == {("a", "b")}


@pytest.mark.db
def test_las_campanas_sin_fechas_se_cuentan_aparte(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Quedan fuera del calendario, y quien lo mira creería que no hay nada más en
    marcha."""
    _campana(uow, clave="sin_fechas", estado="en_curso")
    db.flush()
    assert cmp.calendario(db, tenant_id, desde=HOY, hasta=HOY)["sin_fechas"] == 1


# ── Miembros y embudo (CRM-02.02.01.04) ───────────────────────────────────


@pytest.mark.db
def test_recargar_el_segmento_no_reinicia_el_embudo(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """El embudo se quedaría a cero cada vez que se refresca la audiencia."""
    campana = _campana(uow)
    db.flush()
    objetivo = uuid4()
    cmp.anadir_miembros(uow, campana.id, objeto_ids=[objetivo])
    cmp.avanzar(uow, campana.id, objetivo, estado="clicado")
    db.flush()

    salida = cmp.anadir_miembros(uow, campana.id, objeto_ids=[objetivo, uuid4()])
    assert salida["anadidos"] == 1 and salida["ya_estaban"] == 1
    assert cmp.embudo(db, tenant_id, campana.id)["embudo"]["clicado"] == 1


@pytest.mark.db
def test_el_embudo_no_retrocede(db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any) -> None:
    """Permitir el retroceso haría que las tasas de conversión bajaran solas con
    el tiempo sin que nadie hubiera hecho nada peor."""
    campana = _campana(uow)
    db.flush()
    objetivo = uuid4()
    cmp.anadir_miembros(uow, campana.id, objeto_ids=[objetivo])
    cmp.avanzar(uow, campana.id, objetivo, estado="respondido")
    fila = cmp.avanzar(uow, campana.id, objetivo, estado="abierto")
    assert fila.estado == "respondido"


@pytest.mark.db
def test_el_embudo_es_acumulado(db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any) -> None:
    """Contar solo el estado actual daría «5 abiertos y 40 respondidos», que no se
    sostiene y hace que nadie se crea el resto del informe."""
    campana = _campana(uow)
    db.flush()
    for estado in ("enviado", "abierto", "respondido"):
        objetivo = uuid4()
        cmp.anadir_miembros(uow, campana.id, objeto_ids=[objetivo])
        cmp.avanzar(uow, campana.id, objetivo, estado=estado)
    db.flush()

    embudo = cmp.embudo(db, tenant_id, campana.id)["embudo"]
    assert embudo["enviado"] == 3 and embudo["abierto"] == 2 and embudo["respondido"] == 1


# ── Eventos (CRM-02.02.01.07) ─────────────────────────────────────────────


@pytest.mark.db
def test_el_aforo_se_respeta(db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any) -> None:
    campana = _campana(uow, clave="feria", tipo="evento", aforo=2)
    db.flush()
    for _ in range(2):
        cmp.inscribir(uow, campana.id, uuid4())
    db.flush()
    with pytest.raises(Conflicto) as e:
        cmp.inscribir(uow, campana.id, uuid4())
    assert e.value.error_code == "marketing.aforo_completo"


@pytest.mark.db
def test_inscribirse_y_aparecer_no_es_lo_mismo(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Sin ese dato, un evento con trescientas inscripciones y ochenta asistentes
    se informa como un éxito."""
    campana = _campana(uow, clave="feria", tipo="evento")
    db.flush()
    vino, no_vino, sin_marcar = uuid4(), uuid4(), uuid4()
    for objetivo in (vino, no_vino, sin_marcar):
        cmp.inscribir(uow, campana.id, objetivo)
    db.flush()
    cmp.marcar_asistencia(uow, campana.id, vino, asistio=True)
    cmp.marcar_asistencia(uow, campana.id, no_vino, asistio=False)
    db.flush()

    salida = cmp.resultado_evento(db, tenant_id, campana.id)
    assert salida["inscritos"] == 3
    assert salida["asistieron"] == 1
    assert salida["no_aparecieron"] == 1
    # Se dice cuántos no se marcaron: sin eso, una asistencia baja podría ser que
    # no vino nadie o que nadie pasó lista.
    assert salida["sin_marcar"] == 1
    assert salida["tasa_asistencia_pct"] == 50.0


# ── Atribución (CRM-02.02.01.06) ──────────────────────────────────────────


def _toques(*claves: str) -> list[Any]:
    base = datetime.now(timezone.utc) - timedelta(days=len(claves))
    return [
        cmp.ToqueCampana(
            tenant_id=uuid4(),
            toque_id=uuid4(),
            campana=clave,
            ocurrio_at=base + timedelta(days=i),
        )
        for i, clave in enumerate(claves)
    ]


def test_primer_y_ultimo_toque_dan_respuestas_opuestas() -> None:
    """Las dos son defendibles, y elegir una y presentarla como «el ROI» es lo que
    hace que nadie se crea los informes de marketing."""
    toques = _toques("feria", "webinar", "anuncio")
    primero = cmp.repartir(toques, Decimal("1000"), modelo="primer_toque")
    ultimo = cmp.repartir(toques, Decimal("1000"), modelo="ultimo_toque")
    assert primero[0].campana == "feria" and primero[0].importe == Decimal("1000.00")
    assert ultimo[0].campana == "anuncio" and ultimo[0].importe == Decimal("1000.00")


def test_el_modelo_en_u_premia_los_extremos() -> None:
    toques = _toques("a", "b", "c")
    reparto = {r.campana: r.peso for r in cmp.repartir(toques, Decimal("100"), modelo="en_u")}
    assert reparto["a"] == 0.4 and reparto["c"] == 0.4
    assert round(reparto["b"], 3) == 0.2


def test_el_decaimiento_pesa_mas_lo_reciente() -> None:
    """Sin semivida no hay «decaimiento»: hay una constante disfrazada."""
    toques = _toques("viejo", "medio", "nuevo")
    reparto = {
        r.campana: r.peso for r in cmp.repartir(toques, Decimal("100"), modelo="decaimiento")
    }
    assert reparto["nuevo"] > reparto["medio"] > reparto["viejo"]


def test_los_toques_sin_campana_no_se_descartan() -> None:
    """Descartarlos haría que el tráfico directo y el boca a boca parecieran no
    existir."""
    toques = _toques("feria")
    toques.append(
        cmp.ToqueCampana(
            tenant_id=uuid4(), toque_id=uuid4(), campana=None, ocurrio_at=datetime.now(timezone.utc)
        )
    )
    claves = {r.campana for r in cmp.repartir(toques, Decimal("100"), modelo="lineal")}
    assert "(sin campaña)" in claves


def test_un_modelo_inventado_se_rechaza() -> None:
    with pytest.raises(ErrorValidacion) as e:
        cmp.repartir(_toques("a"), Decimal("1"), modelo="a_ojo")
    assert e.value.error_code == "marketing.modelo_atribucion_no_valido"


@pytest.mark.db
def test_la_ventana_deja_fuera_los_toques_viejos(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Sin ella, la primera campaña que hizo la empresa se lleva el crédito de
    todo lo que pase después."""
    lead = uuid4()
    for dias, clave in ((500, "antigua"), (5, "reciente")):
        db.add(
            cmp.ToqueCampana(
                tenant_id=tenant_id,
                toque_id=uuid4(),
                lead_id=lead,
                campana=clave,
                ocurrio_at=datetime.now(timezone.utc) - timedelta(days=dias),
            )
        )
    db.flush()

    salida = cmp.atribuir(db, tenant_id, lead_id=lead, importe=Decimal("1000"), ventana_dias=90)
    claves = {r["campana"] for r in salida["modelos"]["lineal"]}
    assert claves == {"reciente"}


@pytest.mark.db
def test_sin_toques_no_se_atribuye_a_nadie(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """Repartirlo «a la campaña más reciente» inventaría un origen que no consta,
    que es cómo se fabrica un ROI que no se sostiene."""
    salida = cmp.atribuir(db, tenant_id, lead_id=uuid4(), importe=Decimal("1000"))
    assert salida["sin_toques"] is True
    assert salida["modelos"]["lineal"] == []


# ── Rendimiento (CRM-02.02.01.05, .02) ────────────────────────────────────


@pytest.mark.db
def test_sin_ingresos_el_roi_no_es_cero_sino_no_medible(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Cero se leería como «no trajo nada»."""
    campana = _campana(uow, objetivos={"convertido": 50})
    db.flush()
    cmp.imputar_gasto(uow, campana.id, importe=Decimal("1000"))
    db.flush()

    salida = cmp.rendimiento(db, tenant_id, campana.id)
    assert salida["roi_medible"] is False
    assert salida["roi_pct"] is None
    assert "no se ha medido" in salida["aviso"]


@pytest.mark.db
def test_el_plan_se_compara_con_lo_real(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    campana = _campana(uow, objetivos={"convertido": 10})
    db.flush()
    objetivo = uuid4()
    cmp.anadir_miembros(uow, campana.id, objeto_ids=[objetivo])
    cmp.avanzar(uow, campana.id, objetivo, estado="convertido")
    db.flush()

    salida = cmp.rendimiento(db, tenant_id, campana.id, ingresos_atribuidos=Decimal("5000"))
    assert salida["plan_vs_real"]["convertido"] == {"objetivo": 10, "real": 1}
    assert salida["roi_medible"] is False or salida["roi_pct"] is not None


# ── Presión de contacto (CRM-02.02.02.06) ─────────────────────────────────


@pytest.mark.db
def test_sin_regla_no_se_frena_pero_se_cuenta(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Cuando alguien pregunta «¿a cuánta gente le hemos escrito cuatro veces?»,
    ya es tarde para empezar a contar."""
    objetivo = uuid4()
    for _ in range(5):
        cmp.anotar_envio(db, tenant_id, objeto_id=objetivo)
    db.flush()

    assert cmp.comprobar_fatiga(db, tenant_id, objetivo)["permitido"] is True
    assert cmp.presion(db, tenant_id)["envios"] == 5


@pytest.mark.db
def test_pasado_el_tope_no_se_permite(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    db.add(cmp.ReglaFatiga(tenant_id=tenant_id, canal="email", maximo=2, ventana_dias=7))
    objetivo = uuid4()
    for _ in range(2):
        cmp.anotar_envio(db, tenant_id, objeto_id=objetivo)
    db.flush()

    salida = cmp.comprobar_fatiga(db, tenant_id, objetivo)
    assert salida["permitido"] is False
    assert "máximo 2" in salida["motivos"][0]


@pytest.mark.db
def test_lo_transaccional_no_cuenta_para_la_fatiga(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Contarlo haría que un cliente con muchas incidencias dejara de recibir la
    información que ha pedido."""
    db.add(cmp.ReglaFatiga(tenant_id=tenant_id, canal="email", maximo=1, ventana_dias=7))
    objetivo = uuid4()
    for _ in range(5):
        cmp.anotar_envio(db, tenant_id, objeto_id=objetivo, transaccional=True)
    db.flush()
    assert cmp.comprobar_fatiga(db, tenant_id, objetivo)["permitido"] is True


@pytest.mark.db
def test_hay_dos_limites_y_no_uno(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """Un tope semanal no impide mandar los tres el mismo martes por la mañana,
    que es exactamente lo que el destinatario percibe como acoso."""
    db.add(
        cmp.ReglaFatiga(
            tenant_id=tenant_id, canal="email", maximo=10, ventana_dias=7, horas_minimas=48
        )
    )
    objetivo = uuid4()
    cmp.anotar_envio(db, tenant_id, objeto_id=objetivo)
    db.flush()

    salida = cmp.comprobar_fatiga(db, tenant_id, objetivo)
    assert salida["permitido"] is False
    assert "mínimo son 48 h" in salida["motivos"][0]


# ── Rebotes y quejas (CRM-02.03.01.04) ────────────────────────────────────


@pytest.mark.db
def test_un_rebote_duro_suprime_al_instante(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Seguir escribiéndole hunde la reputación de envío del dominio, y con ella
    la entrega de todos los correos."""
    salida = cmp.anotar_rebote(uow, direccion="no@existe.com", tipo="duro", codigo="550")
    db.flush()
    assert salida["suprimido"] is True
    _, fuera = seg.filtrar_suprimidos(db, tenant_id, "contacto", [])
    assert fuera == []
    from services.marketing.modelos import Supresion

    assert db.query(Supresion).filter_by(direccion="no@existe.com").one().motivo == "rebote_duro"


@pytest.mark.db
def test_una_queja_suprime_de_forma_permanente(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    cmp.anotar_rebote(uow, direccion="enfadado@x.com", tipo="queja")
    db.flush()
    from services.marketing.modelos import Supresion

    assert db.query(Supresion).filter_by(direccion="enfadado@x.com").one().permanente is True


@pytest.mark.db
def test_un_blando_aislado_no_suprime(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Uno aislado es normal: el buzón estaba lleno."""
    salida = cmp.anotar_rebote(uow, direccion="lleno@x.com", tipo="blando")
    assert salida["suprimido"] is False and salida["blandos_seguidos"] == 1


@pytest.mark.db
def test_varios_blandos_seguidos_si_suprimen(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Sin el histórico hay que elegir entre suprimir al primer fallo —perdiendo
    contactos buenos— o no suprimir nunca."""
    salida = {}
    for _ in range(cmp.BLANDOS_PARA_SUPRIMIR):
        salida = cmp.anotar_rebote(uow, direccion="muerta@x.com", tipo="blando")
        db.flush()
    assert salida["suprimido"] is True
    assert salida["motivo"] == "blandos_acumulados"


@pytest.mark.db
def test_un_tipo_de_rebote_inventado_se_rechaza(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    with pytest.raises(ErrorValidacion) as e:
        cmp.anotar_rebote(uow, direccion="x@x.com", tipo="raro")
    assert e.value.error_code == "marketing.rebote_no_valido"


@pytest.mark.db
def test_la_salud_de_envio_lleva_el_umbral_al_lado(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Una tasa de queja del 0,3 % suena a poco y es el triple de lo que los
    proveedores toleran: un número sin referencia no dice si hay que actuar."""
    for _ in range(100):
        cmp.anotar_envio(db, tenant_id, objeto_id=uuid4())
    for _ in range(3):
        cmp.anotar_rebote(uow, direccion=f"q{uuid4().hex[:6]}@x.com", tipo="queja")
    db.flush()

    salida = cmp.salud_de_envio(db, tenant_id)
    assert salida["tasa_queja_pct"] == 3.0
    assert salida["umbral_queja_pct"] == 0.1
    assert salida["en_riesgo"] is True


@pytest.mark.db
def test_sin_envios_la_salud_no_es_medible(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    salida = cmp.salud_de_envio(db, tenant_id)
    assert salida["medible"] is False
    assert salida["tasa_queja_pct"] is None
