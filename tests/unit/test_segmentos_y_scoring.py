"""Segmentos y puntuación de leads (CRM-02.01.01, CRM-02.01.02).

Dos cosas se prueban con insistencia porque son las que cuestan dinero: que un
segmento nunca alcance a quien pidió no ser alcanzado, y que el scoring no meta
en el mismo saco a un estudiante muy activo y a un director de compras.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado

from services.marketing import proyeccion as proy
from services.marketing import puntuacion as pun
from services.marketing import segmentos as seg
from services.marketing.modelos import PerfilMarketing


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


def _perfil(db: Any, tenant_id: UUID, *, objeto: str = "contacto", **datos: Any) -> PerfilMarketing:
    objeto_id = datos.pop("objeto_id", None) or uuid4()
    fila = proy.aplicar(db, tenant_id=tenant_id, objeto=objeto, objeto_id=objeto_id, datos=datos)
    db.flush()
    return fila


# ── Definición y validación (CRM-02.01.01.02) ─────────────────────────────


def test_un_arbol_vacio_no_pasa() -> None:
    """Una definición rota que se descubre al lanzar la campaña ya ha costado el
    envío."""
    with pytest.raises(ErrorValidacion) as e:
        seg.validar({})
    assert e.value.error_code == "marketing.segmento_sin_definicion"


def test_no_niega_varias_condiciones_a_la_vez() -> None:
    """«no» de varias cosas es ambiguo: ¿ninguna, o no todas? Obligar a
    envolverlas primero deja escrito cuál de las dos se quería."""
    with pytest.raises(ErrorValidacion) as e:
        seg.validar({"op": "no", "hijos": [{"atributo": "a"}, {"atributo": "b"}]})
    assert e.value.error_code == "marketing.no_con_varios_hijos"


def test_un_arbol_demasiado_anidado_se_corta() -> None:
    """Una definición con anidamiento sin fin haría que la evaluación no
    terminara, y el síntoma sería una petición que no responde."""
    arbol: dict[str, Any] = {"atributo": "contacto.pais", "operador": "=", "valor": "ES"}
    for _ in range(12):
        arbol = {"op": "y", "hijos": [arbol]}
    with pytest.raises(ErrorValidacion) as e:
        seg.validar(arbol)
    assert e.value.error_code == "marketing.segmento_demasiado_anidado"


def test_la_logica_booleana_anidada_se_evalua() -> None:
    """«(A o B) y no C» es la consulta normal en marketing."""
    definicion = {
        "op": "y",
        "hijos": [
            {
                "op": "o",
                "hijos": [
                    {"atributo": "c.sector", "operador": "=", "valor": "construccion"},
                    {"atributo": "c.sector", "operador": "=", "valor": "obra"},
                ],
            },
            {"op": "no", "hijos": [{"atributo": "c.pais", "operador": "=", "valor": "FR"}]},
        ],
    }
    assert seg.evalua(definicion, {"c": {"sector": "obra", "pais": "ES"}}) is True
    assert seg.evalua(definicion, {"c": {"sector": "obra", "pais": "FR"}}) is False
    assert seg.evalua(definicion, {"c": {"sector": "banca", "pais": "ES"}}) is False


def test_los_operadores_temporales_son_relativos() -> None:
    """Guardada la fecha calculada, «leads recientes» seguiría devolviendo los
    mismos de hace medio año."""
    hoy = datetime.now(timezone.utc).date()
    definicion = {"atributo": "c.alta", "operador": "hace_menos_de_dias", "valor": 30}
    assert seg.evalua(definicion, {"c": {"alta": hoy - timedelta(days=5)}}) is True
    assert seg.evalua(definicion, {"c": {"alta": hoy - timedelta(days=90)}}) is False


# ── Segmentos sobre la proyección (CRM-02.01.01.01, .03, .04) ─────────────


@pytest.mark.db
def test_un_segmento_dinamico_se_recalcula(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """«Clientes activos» tiene que significar lo que significa hoy."""
    _perfil(db, tenant_id, email="a@x.com", pais="ES")
    segmento = seg.crear(
        uow,
        clave="espanoles",
        nombre="Españoles",
        objeto="contacto",
        definicion={"atributo": "contacto.pais", "operador": "=", "valor": "ES"},
    )
    db.flush()
    assert len(seg.miembros(db, tenant_id, segmento.id)) == 1

    _perfil(db, tenant_id, email="b@x.com", pais="ES")
    assert len(seg.miembros(db, tenant_id, segmento.id)) == 2


@pytest.mark.db
def test_un_segmento_congelado_no_cambia(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """«¿A quién se le mandó?» tiene que poder contestarse en junio con la lista
    de marzo."""
    _perfil(db, tenant_id, email="a@x.com", pais="ES")
    segmento = seg.crear(
        uow,
        clave="espanoles",
        nombre="Españoles",
        objeto="contacto",
        definicion={"atributo": "contacto.pais", "operador": "=", "valor": "ES"},
    )
    db.flush()
    seg.congelar(uow, segmento.id)
    db.flush()

    _perfil(db, tenant_id, email="b@x.com", pais="ES")
    assert len(seg.miembros(db, tenant_id, segmento.id)) == 1


@pytest.mark.db
def test_un_atributo_no_segmentable_se_rechaza_al_crear(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Descubrir que un segmento no se puede calcular el día del envío es
    descubrirlo tarde."""
    with pytest.raises(ErrorValidacion) as e:
        seg.crear(
            uow,
            clave="raro",
            nombre="Raro",
            objeto="contacto",
            definicion={"atributo": "contacto.inventado", "operador": "=", "valor": 1},
        )
    assert e.value.error_code == "marketing.atributo_no_segmentable"


@pytest.mark.db
def test_un_operador_sin_traduccion_se_rechaza(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Omitir la condición que no sabe traducirse daría un segmento más grande
    que el pedido, y el error se descubriría al recibir la queja de alguien a
    quien no había que escribir."""
    with pytest.raises(ErrorValidacion) as e:
        seg.crear(
            uow,
            clave="raro",
            nombre="Raro",
            objeto="contacto",
            definicion={"atributo": "contacto.pais", "operador": "contiene", "valor": "ES"},
        )
    assert e.value.error_code == "marketing.operador_sin_traduccion"


@pytest.mark.db
def test_los_dados_de_baja_no_entran_en_un_dinamico(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Siguen en la tabla para que un segmento congelado explique a quién
    incluía, pero uno dinámico no puede seguir seleccionando a quien ya no
    existe."""
    fila = _perfil(db, tenant_id, email="a@x.com", pais="ES")
    segmento = seg.crear(
        uow,
        clave="espanoles",
        nombre="Españoles",
        objeto="contacto",
        definicion={"atributo": "contacto.pais", "operador": "=", "valor": "ES"},
    )
    db.flush()
    proy.marcar_baja(db, tenant_id=tenant_id, objeto_id=fila.objeto_id)
    db.flush()
    assert seg.miembros(db, tenant_id, segmento.id) == []


@pytest.mark.db
def test_una_exclusion_rota_no_se_ignora(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Si se ignorara, el segmento pasaría a incluir a quien se excluía y nadie
    lo notaría hasta el envío."""
    _perfil(db, tenant_id, email="a@x.com", pais="ES")
    segmento = seg.crear(
        uow,
        clave="espanoles",
        nombre="Españoles",
        objeto="contacto",
        definicion={"atributo": "contacto.pais", "operador": "=", "valor": "ES"},
        excluye=[uuid4()],
    )
    db.flush()
    with pytest.raises(ErrorValidacion) as e:
        seg.miembros(db, tenant_id, segmento.id)
    assert e.value.error_code == "marketing.exclusion_rota"


@pytest.mark.db
def test_el_tamano_lleva_la_hora_del_calculo(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Un número sin fecha al lado se lee como actual aunque sea de hace tres
    semanas, y sobre eso se decide un envío."""
    _perfil(db, tenant_id, email="a@x.com", pais="ES")
    segmento = seg.crear(
        uow,
        clave="espanoles",
        nombre="Españoles",
        objeto="contacto",
        definicion={"atributo": "contacto.pais", "operador": "=", "valor": "ES"},
    )
    db.flush()
    salida = seg.tamano(db, tenant_id, segmento.id)
    assert salida["alcanzables"] == 1
    assert salida["calculado_at"]


# ── Supresiones (CRM-02.01.01.06) ─────────────────────────────────────────


@pytest.mark.db
def test_el_suprimido_no_cuenta_como_alcanzable(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Enseñar solo el total haría que alguien planificara un envío a diez mil y
    saliera a siete mil sin saber por qué faltan tres mil."""
    _perfil(db, tenant_id, email="si@x.com", pais="ES")
    _perfil(db, tenant_id, email="no@x.com", pais="ES")
    seg.suprimir(uow, direccion="no@x.com", motivo="baja")
    segmento = seg.crear(
        uow,
        clave="espanoles",
        nombre="Españoles",
        objeto="contacto",
        definicion={"atributo": "contacto.pais", "operador": "=", "valor": "ES"},
    )
    db.flush()

    salida = seg.tamano(db, tenant_id, segmento.id)
    assert salida["bruto"] == 2
    assert salida["alcanzables"] == 1
    assert salida["suprimidos"] == 1


@pytest.mark.db
def test_la_supresion_alcanza_a_las_fichas_duplicadas(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """La misma persona puede estar en tres fichas duplicadas; suprimir una sola
    dejaría que las otras dos le siguieran escribiendo."""
    for _ in range(3):
        _perfil(db, tenant_id, email="mismo@x.com", pais="ES")
    seg.suprimir(uow, direccion="mismo@x.com", motivo="queja")
    db.flush()

    ids = [p.objeto_id for p in db.query(PerfilMarketing).all()]
    alcanzables, fuera = seg.filtrar_suprimidos(db, tenant_id, "contacto", ids)
    assert alcanzables == [] and len(fuera) == 3


@pytest.mark.db
def test_sin_direccion_no_se_cuenta_como_alcanzable(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Contarlo como alcanzable infla la audiencia y después el envío sale más
    pequeño de lo prometido sin explicación."""
    fila = _perfil(db, tenant_id, pais="ES")
    alcanzables, fuera = seg.filtrar_suprimidos(db, tenant_id, "contacto", [fila.objeto_id])
    assert alcanzables == [] and fuera == [fila.objeto_id]


@pytest.mark.db
def test_una_queja_es_permanente(db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any) -> None:
    """Deshacerla con un clic convierte la protección en una casilla."""
    fila = seg.suprimir(uow, direccion="enfadado@x.com", motivo="queja")
    db.flush()
    with pytest.raises(Conflicto) as e:
        seg.levantar_supresion(uow, fila.id, motivo="dice que fue sin querer")
    assert e.value.error_code == "marketing.supresion_permanente"


@pytest.mark.db
def test_levantar_una_supresion_exige_motivo(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Es volver a escribir a alguien que había dicho que no."""
    fila = seg.suprimir(uow, direccion="baja@x.com", motivo="baja")
    db.flush()
    with pytest.raises(ErrorValidacion):
        seg.levantar_supresion(uow, fila.id, motivo="")


@pytest.mark.db
def test_la_baja_selectiva_no_corta_los_avisos_de_servicio(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Es lo que evita que alguien se dé de baja de todo por no poder darse de
    baja de una cosa."""
    fila = _perfil(db, tenant_id, email="selectivo@x.com")
    seg.suprimir(uow, direccion="selectivo@x.com", motivo="baja", ambito="newsletter")
    db.flush()

    alcanzables, _ = seg.filtrar_suprimidos(
        db, tenant_id, "contacto", [fila.objeto_id], ambito="avisos"
    )
    assert alcanzables == [fila.objeto_id]
    _, fuera = seg.filtrar_suprimidos(
        db, tenant_id, "contacto", [fila.objeto_id], ambito="newsletter"
    )
    assert fuera == [fila.objeto_id]


@pytest.mark.db
def test_un_segmento_congelado_tambien_respeta_las_supresiones(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """La baja pudo llegar después de congelarlo: es exactamente el caso que la
    supresión existe para impedir."""
    _perfil(db, tenant_id, email="tarde@x.com", pais="ES")
    segmento = seg.crear(
        uow,
        clave="espanoles",
        nombre="Españoles",
        objeto="contacto",
        definicion={"atributo": "contacto.pais", "operador": "=", "valor": "ES"},
    )
    db.flush()
    seg.congelar(uow, segmento.id)
    seg.suprimir(uow, direccion="tarde@x.com", motivo="baja")
    db.flush()

    assert seg.tamano(db, tenant_id, segmento.id)["alcanzables"] == 0


# ── Solapamiento (CRM-02.01.01.07) ────────────────────────────────────────


@pytest.mark.db
def test_el_solapamiento_da_el_porcentaje_sobre_cada_uno(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Mil personas comunes es mucho si uno de los segmentos tiene mil doscientos
    y poco si tiene cien mil."""
    _perfil(db, tenant_id, email="a@x.com", pais="ES", sector="obra")
    _perfil(db, tenant_id, email="b@x.com", pais="ES", sector="banca")
    espana = seg.crear(
        uow,
        clave="es",
        nombre="España",
        objeto="contacto",
        definicion={"atributo": "contacto.pais", "operador": "=", "valor": "ES"},
    )
    obra = seg.crear(
        uow,
        clave="obra",
        nombre="Obra",
        objeto="contacto",
        definicion={"atributo": "contacto.sector", "operador": "=", "valor": "obra"},
    )
    db.flush()

    salida = seg.solapamiento(db, tenant_id, espana.id, obra.id)
    assert salida["comunes"] == 1
    assert salida["pct_de_a"] == 50.0
    assert salida["pct_de_b"] == 100.0


# ── Puntuación (CRM-02.01.02.01, .03, .04, .05) ───────────────────────────


def _modelo(uow: Any, **kw: Any) -> Any:
    base = {
        "clave": "estandar",
        "nombre": "Estándar",
        "reglas_interes": [
            {
                "nombre": "descargó el comparativo",
                "condicion": {"atributo": "lead.origen", "operador": "=", "valor": "descarga"},
                "puntos": 30,
            }
        ],
        "reglas_encaje": [
            {
                "nombre": "sector objetivo",
                "condicion": {"atributo": "lead.sector", "operador": "=", "valor": "obra"},
                "puntos": 60,
            }
        ],
        "umbral_mql_interes": 20,
        "umbral_mql_encaje": 50,
        "grados": [
            {"desde": 80, "grado": "A"},
            {"desde": 50, "grado": "B"},
            {"desde": 0, "grado": "C"},
        ],
    }
    base.update(kw)
    return pun.crear_modelo(uow, **base)


@pytest.mark.db
def test_hacen_falta_los_dos_ejes_para_ser_mql(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Con uno solo, o pasan estudiantes muy activos o directores que no han
    mostrado ningún interés."""
    _modelo(uow)
    activo = _perfil(db, tenant_id, objeto="lead", origen="descarga", sector="banca")
    encajado = _perfil(db, tenant_id, objeto="lead", origen="feria", sector="obra")
    ambos = _perfil(db, tenant_id, objeto="lead", origen="descarga", sector="obra")
    db.flush()

    assert pun.puntuar(uow, activo.objeto_id).calificacion == "ninguno"
    assert pun.puntuar(uow, encajado.objeto_id).calificacion == "ninguno"
    assert pun.puntuar(uow, ambos.objeto_id).calificacion == "mql"


@pytest.mark.db
def test_el_encaje_no_decae_y_el_interes_si(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Que alguien sea director de compras no deja de ser cierto porque lleve dos
    meses sin abrir un correo."""
    _modelo(uow, decaimiento_puntos=10, decaimiento_dias=30, interes_minimo=5)
    lead = _perfil(db, tenant_id, objeto="lead", origen="descarga", sector="obra")
    lead.ultima_actividad_at = datetime.now(timezone.utc) - timedelta(days=90)
    db.flush()

    fila = pun.puntuar(uow, lead.objeto_id)
    assert fila.encaje == 60
    assert fila.interes == 5  # 30 - 3 periodos × 10, con mínimo 5
    assert fila.decaido == 25


@pytest.mark.db
def test_el_interes_nunca_baja_del_minimo(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Un lead que fue muy activo hace un año no puede quedar indistinguible de
    uno que no ha hecho nada nunca."""
    _modelo(uow, decaimiento_puntos=100, decaimiento_dias=1, interes_minimo=3)
    lead = _perfil(db, tenant_id, objeto="lead", origen="descarga", sector="obra")
    lead.ultima_actividad_at = datetime.now(timezone.utc) - timedelta(days=400)
    db.flush()
    assert pun.puntuar(uow, lead.objeto_id).interes == 3


@pytest.mark.db
def test_el_grado_coge_el_tramo_mas_alto(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Con el orden al revés, un encaje de 95 caería en el tramo de 0 y todo el
    mundo sería «C»."""
    _modelo(uow)
    lead = _perfil(db, tenant_id, objeto="lead", origen="descarga", sector="obra")
    db.flush()
    assert pun.puntuar(uow, lead.objeto_id).grado == "B"


@pytest.mark.db
def test_la_puntuacion_dice_por_que(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """«Este lead tiene 87» no le sirve a nadie: lo que hace que un comercial
    llame es saber que descargó el comparativo."""
    _modelo(uow)
    lead = _perfil(db, tenant_id, objeto="lead", origen="descarga", sector="obra")
    db.flush()
    pun.puntuar(uow, lead.objeto_id)
    db.flush()

    salida = pun.explicar(db, tenant_id, lead.objeto_id)
    assert salida["por_interes"][0]["regla"] == "descargó el comparativo"
    assert salida["por_encaje"][0]["regla"] == "sector objetivo"


@pytest.mark.db
def test_el_evento_de_calificacion_solo_sale_al_cambiar(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Emitirlo en cada recálculo haría que «avisa a ventas cuando pase a MQL»
    disparara cada hora sobre el mismo lead."""
    _modelo(uow)
    lead = _perfil(db, tenant_id, objeto="lead", origen="descarga", sector="obra")
    db.flush()

    pun.puntuar(uow, lead.objeto_id)
    primera = len([e for e in uow._pendientes if e["tipo"] == "lead.qualified"])
    pun.puntuar(uow, lead.objeto_id)
    segunda = len([e for e in uow._pendientes if e["tipo"] == "lead.qualified"])
    assert primera == 1 and segunda == 1


@pytest.mark.db
def test_una_version_nueva_no_repuntua_sola_y_se_dice(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Dejar la mitad de la base con el modelo viejo hace que dos leads iguales
    salgan con puntuaciones distintas, y la lista deja de servir para ordenar por
    prioridad."""
    _modelo(uow)
    lead = _perfil(db, tenant_id, objeto="lead", origen="descarga", sector="obra")
    db.flush()
    pun.puntuar(uow, lead.objeto_id)
    db.flush()

    _modelo(uow, umbral_mql_interes=99)
    db.flush()

    assert pun.pendientes_de_recalcular(db, tenant_id) == [lead.objeto_id]
    assert "versión anterior" in pun.explicar(db, tenant_id, lead.objeto_id)["aviso"]


@pytest.mark.db
def test_una_regla_sin_puntos_no_se_publica(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    with pytest.raises(ErrorValidacion) as e:
        pun.crear_modelo(
            uow,
            clave="malo",
            nombre="Malo",
            reglas_interes=[
                {"condicion": {"atributo": "lead.origen", "operador": "=", "valor": "x"}}
            ],
        )
    assert e.value.error_code == "marketing.regla_sin_puntos"


@pytest.mark.db
def test_un_lead_sin_proyectar_lo_dice(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Puntuarlo a cero lo dejaría al final de la lista sin que nadie entendiera
    por qué."""
    _modelo(uow)
    with pytest.raises(NoEncontrado) as e:
        pun.puntuar(uow, uuid4())
    assert e.value.error_code == "marketing.lead_no_proyectado"


# ── La proyección (CRM-02.01.01.01) ───────────────────────────────────────


@pytest.mark.db
def test_el_perfil_se_fusiona_y_no_se_reemplaza(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Cada evento trae lo suyo; reemplazar dejaría el perfil con solo lo del
    último, borrando lo que ya se sabía."""
    objeto_id = uuid4()
    _perfil(db, tenant_id, objeto="lead", objeto_id=objeto_id, email="a@x.com", sector="obra")
    fila = _perfil(db, tenant_id, objeto="lead", objeto_id=objeto_id, origen="feria")
    assert fila.email == "a@x.com" and fila.sector == "obra" and fila.origen == "feria"


@pytest.mark.db
def test_los_campos_propios_tambien_se_fusionan(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    objeto_id = uuid4()
    _perfil(db, tenant_id, objeto_id=objeto_id, campos={"obra": "Torre"})
    fila = _perfil(db, tenant_id, objeto_id=objeto_id, campos={"fase": "final"})
    assert fila.campos == {"obra": "Torre", "fase": "final"}


@pytest.mark.db
def test_una_baja_marca_y_no_borra(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """Si la fila desapareciera, un segmento congelado quedaría con
    identificadores que no resuelven a nada."""
    fila = _perfil(db, tenant_id, email="a@x.com")
    assert proy.marcar_baja(db, tenant_id=tenant_id, objeto_id=fila.objeto_id) == 1
    db.flush()
    assert fila.baja is True
