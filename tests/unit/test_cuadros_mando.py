"""Cuadros de mando: componentes, filtros, alertas y embebido (CRM-05.01.02).

Lo que decide si un cuadro sirve no es el dibujo: es que lo que enseña se pueda
creer y se pueda seguir hasta el registro. Las pruebas van detrás de los cuatro
sitios donde eso se pierde:

  * el componente al que le falta una pieza y sale como un hueco,
  * el filtro que se aplica a siete de ocho componentes,
  * la alerta que se dispara cuarenta veces y acaba desactivada,
  * y el cuadro embebido que enseña más de lo que ve quien lo montó.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoAutenticado

from services.analytics import cuadros as cua
from services.analytics import informes as inf


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


@pytest.fixture(autouse=True)
def sin_ejecutor() -> Any:
    inf._EJECUTOR = None
    yield
    inf._EJECUTOR = None


def _informe(uow: UnidadDeTrabajo, **kw: Any) -> inf.Informe:
    base: dict[str, Any] = {
        "clave": "pipeline",
        "nombre": "Pipeline",
        "objeto": "oportunidad",
        "columnas": ["nombre"],
    }
    base.update(kw)
    fila = inf.Informe(tenant_id=uow.tenant_id, **base)
    uow.db.add(fila)
    uow.db.flush()
    return fila


def _ejecutor(filas: list[dict[str, Any]]) -> Any:
    def fn(plan: dict[str, Any], tenant_id: UUID) -> dict[str, Any]:
        return {"filas": filas}

    return fn


# ── Componentes (CRM-05.01.02.02) ─────────────────────────────────────────


def test_el_catalogo_dice_que_necesita_cada_tipo() -> None:
    """Dos listas que tienen que coincidir acaban no coincidiendo, y la que se
    queda corta es siempre la del front."""
    por_tipo = {c["tipo"]: c for c in cua.catalogo_componentes()}
    assert set(por_tipo) == {"kpi", "tabla", "grafico", "embudo", "mapa", "gauge", "texto"}
    assert "metrica" in por_tipo["kpi"]["necesita"]


def test_un_tipo_inventado_se_rechaza() -> None:
    with pytest.raises(ErrorValidacion) as e:
        cua.validar_componente({"tipo": "holograma", "informe": "x"})
    assert e.value.error_code == "cuadro.tipo_no_valido"


def test_un_embudo_sin_orden_se_caza() -> None:
    """Sus etapas no se ordenan solas: alfabético daría «Cierre, Negociación,
    Propuesta» y el embudo saldría al revés."""
    with pytest.raises(ErrorValidacion) as e:
        cua.validar_componente(
            {"tipo": "embudo", "informe": "x", "dimension": "etapa", "metrica": "total"}
        )
    assert "orden" in e.value.detalle["faltan"]


def test_un_gauge_sin_objetivo_se_caza() -> None:
    """Un gauge sin objetivo es un KPI con una aguja: la aguja solo significa algo
    contra una meta."""
    with pytest.raises(ErrorValidacion):
        cua.validar_componente({"tipo": "gauge", "informe": "x", "metrica": "total"})


def test_un_componente_sin_informe_se_caza_salvo_el_texto() -> None:
    with pytest.raises(ErrorValidacion) as e:
        cua.validar_componente({"tipo": "tabla"})
    assert e.value.error_code == "cuadro.componente_sin_informe"
    # El texto es una nota fija: no saca datos de ningún sitio.
    assert cua.validar_componente({"tipo": "texto"}) == []


def test_un_kpi_sin_comparacion_avisa_pero_no_rompe() -> None:
    """Una cifra sola no dice si va bien o mal, pero impedir guardarla dejaría a
    alguien sin poder montar el cuadro a trozos."""
    avisos = cua.validar_componente({"tipo": "kpi", "informe": "x", "metrica": "total"})
    assert any("no compara" in a for a in avisos)


def test_el_cuadro_valida_sus_componentes_al_guardarse(uow: UnidadDeTrabajo) -> None:
    """Un componente mal configurado que solo falla al abrirse se descubre delante
    de alguien, y lo que se ve es un hueco sin explicación."""
    with pytest.raises(ErrorValidacion):
        inf.crear_cuadro(
            uow,
            clave="malo",
            nombre="Malo",
            componentes=[{"tipo": "grafico", "informe": "x"}],
        )


# ── Filtros globales y drill-down (CRM-05.01.02.03) ───────────────────────


def test_el_filtro_del_cuadro_llega_a_todos_los_componentes() -> None:
    """Si cada uno llevara el suyo, cambiar el trimestre exigiría tocar ocho
    sitios y siempre quedaría uno sin cambiar."""
    componentes = [{"tipo": "kpi"}, {"tipo": "tabla"}, {"tipo": "grafico"}]
    filtros = [{"campo": "trimestre", "operador": "=", "valor": "Q1"}]
    salida = cua.aplicar_filtros_globales(componentes, filtros)
    assert all(len(c["filtros_aplicados"]) == 1 for c in salida)


def test_un_componente_puede_declararse_inmune() -> None:
    """Hace falta para los que enseñan contexto —«total del año pasado»— que
    dejarían de decir lo que dicen si el filtro del trimestre les llegara."""
    salida = cua.aplicar_filtros_globales(
        [{"tipo": "kpi"}, {"tipo": "kpi", "ignora_filtros": True}],
        [{"campo": "trimestre", "operador": "=", "valor": "Q1"}],
    )
    assert salida[0]["filtros_aplicados"] != []
    assert salida[1]["filtros_aplicados"] == []


def test_el_detalle_lleva_el_filtro_del_punto_pulsado() -> None:
    """Sin lo segundo, pulsar en la barra de marzo llevaría a la lista del año
    entero."""
    salida = cua.enlace_al_detalle(
        {"tipo": "grafico", "informe": "pipeline"},
        {"mes": "2026-03"},
        [{"campo": "pais", "operador": "=", "valor": "ES"}],
    )
    assert salida["informe"] == "pipeline"
    assert salida["origen_filtros"] == {"del_cuadro": 1, "del_punto": 1}
    assert {"campo": "mes", "operador": "=", "valor": "2026-03"} in salida["filtros"]


def test_un_texto_no_tiene_detalle_al_que_bajar() -> None:
    with pytest.raises(ErrorValidacion) as e:
        cua.enlace_al_detalle({"tipo": "texto"}, {}, [])
    assert e.value.error_code == "cuadro.sin_detalle"


# ── Alertas (CRM-05.01.02.05) ─────────────────────────────────────────────


def test_una_alerta_sin_destinatarios_no_avisa_a_nadie(uow: UnidadDeTrabajo) -> None:
    fila = _informe(uow)
    with pytest.raises(ErrorValidacion) as e:
        cua.crear_alerta(uow, nombre="a", informe_id=fila.id, destinatarios=[])
    assert e.value.error_code == "alerta.sin_destinatarios"


def test_la_alerta_se_dispara_al_cruzar(uow: UnidadDeTrabajo) -> None:
    inf.registrar_ejecutor(_ejecutor([{"total": 120}]))
    informe = _informe(uow)
    cua.crear_alerta(
        uow,
        nombre="ventas bajas",
        informe_id=informe.id,
        metrica="total",
        comparacion="mayor",
        umbral=Decimal(100),
        destinatarios=["a@b.c"],
    )
    salida = cua.comprobar_alertas(uow, uow.tenant_id)
    assert [d["alerta"] for d in salida["disparadas"]] == ["ventas bajas"]


def test_no_se_dispara_dos_veces_seguidas(uow: UnidadDeTrabajo) -> None:
    """Un indicador que baila alrededor del umbral mandaría cuarenta avisos en una
    tarde, y al día siguiente la regla está desactivada."""
    inf.registrar_ejecutor(_ejecutor([{"total": 120}]))
    informe = _informe(uow)
    cua.crear_alerta(
        uow,
        nombre="a",
        informe_id=informe.id,
        metrica="total",
        umbral=Decimal(100),
        destinatarios=["a@b.c"],
    )
    cua.comprobar_alertas(uow, uow.tenant_id)
    assert cua.comprobar_alertas(uow, uow.tenant_id)["disparadas"] == []


def test_la_histeresis_evita_el_baile(uow: UnidadDeTrabajo, db: Any) -> None:
    """Una alerta que se apaga en el mismo punto en que se enciende manda un aviso
    por cada oscilación."""
    from sqlalchemy import select

    inf.registrar_ejecutor(_ejecutor([{"total": 120}]))
    informe = _informe(uow)
    cua.crear_alerta(
        uow,
        nombre="a",
        informe_id=informe.id,
        metrica="total",
        umbral=Decimal(100),
        histeresis=Decimal(20),
        destinatarios=["a@b.c"],
    )
    cua.comprobar_alertas(uow, uow.tenant_id)

    # Baja a 95: cruza hacia abajo el umbral pero no el margen, así que sigue roja.
    inf.registrar_ejecutor(_ejecutor([{"total": 95}]))
    cua.comprobar_alertas(uow, uow.tenant_id)
    alerta = db.execute(select(cua.AlertaUmbral)).scalars().one()
    assert alerta.estado == "disparada"

    # Baja a 70: ya supera el margen y se da por resuelta.
    inf.registrar_ejecutor(_ejecutor([{"total": 70}]))
    salida = cua.comprobar_alertas(uow, uow.tenant_id)
    assert salida["resueltas"] == ["a"]


def test_lo_que_no_se_puede_medir_no_cuenta_como_verde(uow: UnidadDeTrabajo) -> None:
    """Dar por bueno lo que no se ha medido es la forma más silenciosa de perder
    una alerta."""
    informe = _informe(uow)
    cua.crear_alerta(
        uow, nombre="a", informe_id=informe.id, umbral=Decimal(1), destinatarios=["a@b.c"]
    )
    salida = cua.comprobar_alertas(uow, uow.tenant_id)
    assert salida["disparadas"] == []
    assert len(salida["no_medibles"]) == 1


def test_una_metrica_que_el_informe_no_devuelve_se_dice(uow: UnidadDeTrabajo) -> None:
    inf.registrar_ejecutor(_ejecutor([{"otra_cosa": 5}]))
    informe = _informe(uow)
    cua.crear_alerta(
        uow,
        nombre="a",
        informe_id=informe.id,
        metrica="total",
        umbral=Decimal(1),
        destinatarios=["a@b.c"],
    )
    salida = cua.comprobar_alertas(uow, uow.tenant_id)
    assert "no devuelve la métrica" in salida["no_medibles"][0]["error"]


def test_una_anomalia_por_salto_no_se_dispara_la_primera_vez(
    uow: UnidadDeTrabajo,
) -> None:
    """Sin valor anterior no hay salto que medir, y decir que sí lo hay dispararía
    la alerta siempre al principio."""
    inf.registrar_ejecutor(_ejecutor([{"total": 1000}]))
    informe = _informe(uow)
    cua.crear_alerta(
        uow,
        nombre="salto",
        informe_id=informe.id,
        metrica="total",
        comparacion="cambia_mas_de",
        umbral=Decimal(100),
        destinatarios=["a@b.c"],
    )
    assert cua.comprobar_alertas(uow, uow.tenant_id)["disparadas"] == []
    inf.registrar_ejecutor(_ejecutor([{"total": 5000}]))
    assert cua.comprobar_alertas(uow, uow.tenant_id)["disparadas"] != []


def test_sin_alertas_no_se_dice_que_todo_va_bien(uow: UnidadDeTrabajo) -> None:
    assert cua.comprobar_alertas(uow, uow.tenant_id)["medible"] is False


# ── Embebido (CRM-05.01.02.06) ────────────────────────────────────────────


def test_sin_dominios_no_se_crea_el_embebido(uow: UnidadDeTrabajo) -> None:
    """Un cuadro embebible desde cualquier parte es un cuadro público, y lo normal
    es que traiga cifras de negocio."""
    with pytest.raises(ErrorValidacion) as e:
        cua.crear_embebido(uow, cuadro_id=uuid4(), actua_como_id=uuid4(), dominios=[])
    assert e.value.error_code == "cuadro.embebido_sin_dominios"


def test_el_secreto_no_se_guarda_en_claro(uow: UnidadDeTrabajo) -> None:
    fila, secreto = cua.crear_embebido(
        uow, cuadro_id=uuid4(), actua_como_id=uuid4(), dominios=["intranet.cliente.com"]
    )
    assert secreto not in fila.hash_secreto
    assert len(fila.hash_secreto) == 64


def test_el_embebido_solo_se_sirve_desde_su_dominio(uow: UnidadDeTrabajo) -> None:
    _, secreto = cua.crear_embebido(
        uow, cuadro_id=uuid4(), actua_como_id=uuid4(), dominios=["intranet.cliente.com"]
    )
    bueno = cua.resolver_embebido(
        uow.db, uow.tenant_id, secreto, origen="https://intranet.cliente.com"
    )
    assert bueno.usos == 1
    with pytest.raises(NoAutenticado):
        cua.resolver_embebido(uow.db, uow.tenant_id, secreto, origen="https://otro.sitio.com")


def test_un_subdominio_falso_no_cuela(uow: UnidadDeTrabajo) -> None:
    """Con «contiene», `micrm.com.ataque.net` pasaría por `micrm.com`."""
    _, secreto = cua.crear_embebido(
        uow, cuadro_id=uuid4(), actua_como_id=uuid4(), dominios=["micrm.com"]
    )
    with pytest.raises(NoAutenticado):
        cua.resolver_embebido(uow.db, uow.tenant_id, secreto, origen="https://micrm.com.ataque.net")
    # El subdominio de verdad sí vale.
    assert cua.resolver_embebido(uow.db, uow.tenant_id, secreto, origen="https://paneles.micrm.com")


def test_un_secreto_inventado_y_uno_revocado_dan_lo_mismo(uow: UnidadDeTrabajo) -> None:
    """Distinguirlos le diría a quien prueba si ese cuadro existe."""
    fila, secreto = cua.crear_embebido(
        uow, cuadro_id=uuid4(), actua_como_id=uuid4(), dominios=["x.com"]
    )
    cua.revocar_embebido(uow, fila.id)
    with pytest.raises(NoAutenticado) as revocado:
        cua.resolver_embebido(uow.db, uow.tenant_id, secreto)
    with pytest.raises(NoAutenticado) as inventado:
        cua.resolver_embebido(uow.db, uow.tenant_id, "no-existe")
    assert revocado.value.error_code == inventado.value.error_code


def test_revocar_dos_veces_se_dice(uow: UnidadDeTrabajo) -> None:
    fila, _ = cua.crear_embebido(uow, cuadro_id=uuid4(), actua_como_id=uuid4(), dominios=["x.com"])
    cua.revocar_embebido(uow, fila.id)
    with pytest.raises(Conflicto):
        cua.revocar_embebido(uow, fila.id)


def test_el_embebido_deja_dicho_a_quien_representa(uow: UnidadDeTrabajo) -> None:
    """El embebido no autentica a quien está delante de la pantalla ajena: fijar a
    quién representa impide que enseñe más de lo que ve quien lo montó."""
    yo = uuid4()
    fila, _ = cua.crear_embebido(uow, cuadro_id=uuid4(), actua_como_id=yo, dominios=["x.com"])
    assert fila.actua_como_id == yo


# ── Suscripción (CRM-05.01.02.05) ─────────────────────────────────────────


def test_suscribirse_dos_veces_no_duplica(uow: UnidadDeTrabajo) -> None:
    cuadro, usuario = uuid4(), uuid4()
    una = cua.suscribirse(uow, cuadro_id=cuadro, usuario_id=usuario)
    otra = cua.suscribirse(uow, cuadro_id=cuadro, usuario_id=usuario, periodicidad="diaria")
    assert una.id == otra.id
    assert otra.periodicidad == "diaria"
