"""Territorios, cuotas y capacidad (CRM-03.02.02).

Un territorio decide de quién es un cliente, y por eso es la pieza que más
discusiones provoca de un CRM: cuando dos comerciales creen que una cuenta es
suya, el problema no es técnico. Las pruebas van detrás de los cinco sitios donde
eso se decide mal:

  * la cuenta que no encaja en ningún sitio y nadie ve,
  * el solape que hace que gane el orden alfabético,
  * la excepción que el recálculo se lleva por delante,
  * la cuota completa a quien entró el día 20,
  * y la cobertura medida contra la cuota entera a mitad de trimestre.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import ErrorValidacion, NoEncontrado
from crmcore.fechas import hoy

from services.sales import territorios as ter


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


def _territorio(uow: UnidadDeTrabajo, clave: str, provincias: list[str] | None = None, **kw: Any):
    criterios = (
        [
            {
                "tipo": "geografia",
                "condiciones": [
                    {"atributo": "cuenta.provincia", "operador": "en", "valor": provincias}
                ],
            }
        ]
        if provincias
        else []
    )
    base: dict[str, Any] = {"clave": clave, "nombre": clave.title(), "criterios": criterios}
    base.update(kw)
    fila, _ = ter.crear(uow, **base)
    return fila


def _publicado(uow: UnidadDeTrabajo, clave: str, provincias: list[str] | None = None, **kw: Any):
    fila = _territorio(uow, clave, provincias, **kw)
    ter.publicar(uow, fila.id)
    return fila


# ── Definición (CRM-03.02.02.01) ──────────────────────────────────────────


def test_un_criterio_inventado_se_rechaza() -> None:
    with pytest.raises(ErrorValidacion) as e:
        ter.validar_criterios([{"tipo": "por_simpatia", "condiciones": [{}]}])
    assert e.value.error_code == "territorio.criterio_no_valido"


def test_un_criterio_sin_condiciones_se_rechaza() -> None:
    """Sin condiciones no recorta nada, y quien lo escribió cree que sí."""
    with pytest.raises(ErrorValidacion) as e:
        ter.validar_criterios([{"tipo": "geografia"}])
    assert e.value.error_code == "territorio.criterio_vacio"


def test_un_territorio_sin_criterios_avisa() -> None:
    """Es lo que se quiere del territorio «resto» y un error en cualquier otro."""
    avisos = ter.validar_criterios([])
    assert any("le entrará todo" in a for a in avisos)


def test_nace_en_borrador(uow: UnidadDeTrabajo) -> None:
    """Es lo que permite montar el mapa entero antes de que mueva una cuenta."""
    fila = _territorio(uow, "norte", ["B", "GI"])
    assert fila.estado == "borrador"


def test_un_borrador_no_asigna_nada(uow: UnidadDeTrabajo) -> None:
    _territorio(uow, "norte", ["B"])
    salida = ter.resolver(uow.db, uow.tenant_id, {"provincia": "B"})
    assert salida["territorio_id"] is None


# ── Asignación (CRM-03.02.02.02) ──────────────────────────────────────────


def test_la_cuenta_cae_donde_le_toca_y_se_dice_por_que(uow: UnidadDeTrabajo) -> None:
    """«¿Por qué esta cuenta es de Norte?» no se cierra con un número, se cierra
    con una regla."""
    _publicado(uow, "norte", ["B", "GI"])
    salida = ter.resolver(uow.db, uow.tenant_id, {"provincia": "B"})
    assert salida["territorio"] == "norte"
    assert "geografia" in salida["por_que"]


def test_gana_la_prioridad_mas_baja(uow: UnidadDeTrabajo) -> None:
    _publicado(uow, "resto", prioridad=900)
    _publicado(uow, "norte", ["B"], prioridad=10)
    assert ter.resolver(uow.db, uow.tenant_id, {"provincia": "B"})["territorio"] == "norte"


def test_una_cuenta_sin_territorio_se_dice(uow: UnidadDeTrabajo) -> None:
    """Asignarla al primero disponible esconde un problema que hay que ver."""
    _publicado(uow, "norte", ["B"])
    salida = ter.resolver(uow.db, uow.tenant_id, {"provincia": "SE"})
    assert salida["territorio_id"] is None
    assert "No encaja" in salida["por_que"]


def test_la_excepcion_manda_sobre_la_regla(uow: UnidadDeTrabajo) -> None:
    """Si una regla pudiera ganarle, la excepción no serviría para nada."""
    _publicado(uow, "norte", ["B"])
    sur = _publicado(uow, "sur", ["SE"])
    cuenta = uuid4()
    ter.declarar_excepcion(
        uow,
        cuenta_id=cuenta,
        territorio_id=sur.id,
        motivo="La lleva el director desde antes de la reorganización",
    )
    salida = ter.resolver(uow.db, uow.tenant_id, {"provincia": "B"}, cuenta_id=cuenta)
    assert salida["territorio"] == "sur"
    assert salida["por_excepcion"] is True
    assert "director" in salida["por_que"]


def test_una_excepcion_sin_motivo_se_rechaza(uow: UnidadDeTrabajo) -> None:
    """Es indistinguible de un error, y nadie se atreve a quitarla dos años
    después."""
    norte = _publicado(uow, "norte", ["B"])
    with pytest.raises(ErrorValidacion) as e:
        ter.declarar_excepcion(uow, cuenta_id=uuid4(), territorio_id=norte.id, motivo="   ")
    assert e.value.error_code == "territorio.excepcion_sin_motivo"


def test_una_excepcion_caducada_deja_de_mandar(uow: UnidadDeTrabajo) -> None:
    _publicado(uow, "norte", ["B"])
    sur = _publicado(uow, "sur", ["SE"])
    cuenta = uuid4()
    ter.declarar_excepcion(
        uow,
        cuenta_id=cuenta,
        territorio_id=sur.id,
        motivo="temporal",
        hasta=hoy(uow.db) - timedelta(days=1),
    )
    salida = ter.resolver(uow.db, uow.tenant_id, {"provincia": "B"}, cuenta_id=cuenta)
    assert salida["territorio"] == "norte"


# ── Simulación (CRM-03.02.02.03) ──────────────────────────────────────────


def test_la_simulacion_dice_que_cuentas_cambian_de_dueno(uow: UnidadDeTrabajo) -> None:
    """Publicar y ver qué pasa significa doscientas cuentas cambiando de dueño el
    lunes por la mañana."""
    _publicado(uow, "norte", ["B"])
    salida = ter.simular(uow.db, uow.tenant_id, [{"id": str(uuid4()), "provincia": "B"}])
    assert len(salida["cambian"]) == 1
    assert salida["cambian"][0]["a"] == "norte"


def test_la_simulacion_caza_el_solape(uow: UnidadDeTrabajo) -> None:
    """Es el error que produce una asignación dependiente del orden alfabético, y
    nadie lo busca hasta que dos comerciales discuten."""
    _publicado(uow, "aaa", ["B"], prioridad=50)
    _publicado(uow, "bbb", ["B"], prioridad=50)
    salida = ter.simular(uow.db, uow.tenant_id, [{"id": str(uuid4()), "provincia": "B"}])
    assert len(salida["solapes"]) == 1
    assert salida["seguro_publicar"] is False


def test_la_simulacion_caza_las_cuentas_sin_dueno(uow: UnidadDeTrabajo) -> None:
    _publicado(uow, "norte", ["B"])
    salida = ter.simular(uow.db, uow.tenant_id, [{"id": str(uuid4()), "provincia": "SE"}])
    assert len(salida["sin_territorio"]) == 1
    assert salida["seguro_publicar"] is False


def test_un_mapa_limpio_es_seguro_de_publicar(uow: UnidadDeTrabajo) -> None:
    _publicado(uow, "norte", ["B"], prioridad=10)
    _publicado(uow, "resto", prioridad=900)
    salida = ter.simular(
        uow.db,
        uow.tenant_id,
        [{"id": str(uuid4()), "provincia": "B"}, {"id": str(uuid4()), "provincia": "SE"}],
    )
    assert salida["seguro_publicar"] is True


def test_aplicar_escribe_las_asignaciones(uow: UnidadDeTrabajo) -> None:
    _publicado(uow, "norte", ["B"])
    salida = ter.aplicar(uow, uow.tenant_id, [{"id": str(uuid4()), "provincia": "B"}])
    assert salida["asignadas"] == 1


# ── Cuotas y prorrateo (CRM-03.02.02.04, .05) ─────────────────────────────


def test_una_cuota_sin_sujeto_no_la_cumple_nadie(uow: UnidadDeTrabajo) -> None:
    with pytest.raises(ErrorValidacion) as e:
        ter.crear_cuota(
            uow, desde=date(2026, 1, 1), hasta=date(2026, 3, 31), objetivo=Decimal(100000)
        )
    assert e.value.error_code == "cuota.sin_sujeto"


def test_una_metrica_inventada_se_rechaza(uow: UnidadDeTrabajo) -> None:
    with pytest.raises(ErrorValidacion):
        ter.crear_cuota(
            uow,
            desde=date(2026, 1, 1),
            hasta=date(2026, 3, 31),
            objetivo=Decimal(1),
            usuario_id=uuid4(),
            metrica="karma",
        )


def test_quien_entra_a_mitad_no_tiene_la_cuota_entera(uow: UnidadDeTrabajo) -> None:
    """Darle la cuota completa hace que su primer periodo sea imposible y el del
    equipo, injusto: alguien tendrá que cubrir lo que él no podía hacer."""
    cuota = ter.crear_cuota(
        uow,
        desde=date(2026, 1, 1),
        hasta=date(2026, 3, 31),
        objetivo=Decimal(90000),
        usuario_id=uuid4(),
        activa_desde=date(2026, 3, 1),
    )
    salida = ter.prorratear(cuota)
    assert salida["prorrateado"] is True
    assert Decimal(salida["objetivo_efectivo"]) < Decimal(90000)
    # El objetivo del plan sigue siendo el mismo y se enseña al lado.
    assert salida["objetivo_periodo"] == "90000"


def test_el_hueco_del_prorrateo_se_dice(uow: UnidadDeTrabajo) -> None:
    """Es el número que se olvida: el equipo sigue teniendo el objetivo entero."""
    cuota = ter.crear_cuota(
        uow,
        desde=date(2026, 1, 1),
        hasta=date(2026, 12, 31),
        objetivo=Decimal(120000),
        usuario_id=uuid4(),
        activa_desde=date(2026, 7, 1),
    )
    salida = ter.prorratear(cuota)
    assert Decimal(salida["hueco"]) > 0


def test_el_periodo_entero_no_se_prorratea(uow: UnidadDeTrabajo) -> None:
    cuota = ter.crear_cuota(
        uow,
        desde=date(2026, 1, 1),
        hasta=date(2026, 3, 31),
        objetivo=Decimal(90000),
        usuario_id=uuid4(),
    )
    assert ter.prorratear(cuota)["prorrateado"] is False


# ── Consecución y ranking (CRM-03.02.02.06) ───────────────────────────────


def test_el_ranking_va_por_porcentaje_y_no_por_importe(uow: UnidadDeTrabajo) -> None:
    """Por importe, quien lleva la cuenta grande gana siempre y el ranking deja de
    decir nada sobre quién trabaja bien."""
    grande, pequeno = uuid4(), uuid4()
    ter.crear_cuota(
        uow,
        desde=date(2026, 1, 1),
        hasta=date(2026, 3, 31),
        objetivo=Decimal(1000000),
        usuario_id=grande,
    )
    ter.crear_cuota(
        uow,
        desde=date(2026, 1, 1),
        hasta=date(2026, 3, 31),
        objetivo=Decimal(50000),
        usuario_id=pequeno,
    )
    salida = ter.consecucion(
        uow.db,
        uow.tenant_id,
        desde=date(2026, 1, 1),
        hasta=date(2026, 3, 31),
        logrado_por_sujeto={str(grande): Decimal(300000), str(pequeno): Decimal(45000)},
    )
    # El grande vende seis veces más y va al 30 %; el pequeño, al 90 %.
    assert salida["ranking"][0]["sujeto"] == str(pequeno)


def test_sin_cuotas_no_se_dice_que_se_va_bien(uow: UnidadDeTrabajo) -> None:
    salida = ter.consecucion(uow.db, uow.tenant_id, desde=date(2026, 1, 1), hasta=date(2026, 3, 31))
    assert salida["medible"] is False
    assert "no hay contra qué medir" in salida["aviso"]


# ── Cobertura (CRM-03.02.02.07) ───────────────────────────────────────────


def test_la_cobertura_se_mide_contra_lo_que_queda(uow: UnidadDeTrabajo) -> None:
    """A mitad de trimestre, comparar el pipeline con la cuota entera dice que todo
    el mundo va mal incluso cuando van bien."""
    quien = uuid4()
    ter.crear_cuota(
        uow,
        desde=date(2026, 1, 1),
        hasta=date(2026, 3, 31),
        objetivo=Decimal(100000),
        usuario_id=quien,
    )
    # Lleva 80.000 y le faltan 20.000; con 70.000 de pipeline va sobrado.
    salida = ter.cobertura(
        uow.db,
        uow.tenant_id,
        desde=date(2026, 1, 1),
        hasta=date(2026, 3, 31),
        logrado_por_sujeto={str(quien): Decimal(80000)},
        pipeline_por_sujeto={str(quien): Decimal(70000)},
    )
    assert salida["sujetos"][0]["suficiente"] is True
    assert salida["en_riesgo"] == []


def test_quien_ya_cumplio_no_sale_como_cobertura_infinita(uow: UnidadDeTrabajo) -> None:
    """Quien lo lea tiene que ver que ese no necesita más pipeline, no que tiene
    muchísimo."""
    quien = uuid4()
    ter.crear_cuota(
        uow,
        desde=date(2026, 1, 1),
        hasta=date(2026, 3, 31),
        objetivo=Decimal(100000),
        usuario_id=quien,
    )
    salida = ter.cobertura(
        uow.db,
        uow.tenant_id,
        desde=date(2026, 1, 1),
        hasta=date(2026, 3, 31),
        logrado_por_sujeto={str(quien): Decimal(120000)},
    )
    assert salida["sujetos"][0]["ya_cumplida"] is True
    assert salida["en_riesgo"] == []


def test_el_que_va_corto_sale_en_riesgo(uow: UnidadDeTrabajo) -> None:
    quien = uuid4()
    ter.crear_cuota(
        uow,
        desde=date(2026, 1, 1),
        hasta=date(2026, 3, 31),
        objetivo=Decimal(100000),
        usuario_id=quien,
    )
    salida = ter.cobertura(
        uow.db,
        uow.tenant_id,
        desde=date(2026, 1, 1),
        hasta=date(2026, 3, 31),
        pipeline_por_sujeto={str(quien): Decimal(50000)},
    )
    assert len(salida["en_riesgo"]) == 1
    # Y se dice contra qué se comparó, porque el mínimo no es una ley.
    assert salida["cobertura_minima"] == "3"


def test_un_territorio_que_no_existe_da_404(uow: UnidadDeTrabajo) -> None:
    with pytest.raises(NoEncontrado):
        ter.publicar(uow, uuid4())


# ── Congelación del objetivo de un periodo (CRM-03.02.02.08) ─────────────
#
# El problema es de confianza, no de permisos: a partir del cierre, los
# informes de consecución, las comisiones y las revisiones se calculan contra
# ese número. Si el número puede cambiar después —y cambia siempre, porque
# alguien reimporta la hoja o corrige una celda— nadie puede decir contra qué
# se midió a nadie.


def test_con_el_objetivo_cerrado_no_entra_otra_cuota_crm_03_02_02_08(
    uow: UnidadDeTrabajo,
) -> None:
    """Y el mensaje dice **cuándo se cerró y por qué**: «no se puede modificar»
    a secas manda a preguntar a quien no sabe, y lo que hace falta es saber a
    quién pedir la reapertura."""
    from crmcore.errors import Conflicto

    quien = uuid4()
    ter.crear_cuota(
        uow,
        desde=date(2026, 7, 1),
        hasta=date(2026, 9, 30),
        objetivo=Decimal(100000),
        usuario_id=quien,
    )
    ter.congelar_objetivo(uow, periodo="2026-T3", por=quien, motivo="plan aprobado en comité")

    with pytest.raises(Conflicto) as e:
        ter.crear_cuota(
            uow,
            desde=date(2026, 7, 1),
            hasta=date(2026, 9, 30),
            objetivo=Decimal(250000),
            usuario_id=quien,
        )
    assert e.value.error_code == "cuota.objetivo_congelado"
    assert "2026-T3" in str(e.value)
    assert "plan aprobado en comité" in str(e.value)


def test_cerrar_un_trimestre_no_cierra_los_demas_crm_03_02_02_08(uow: UnidadDeTrabajo) -> None:
    """Si cerrara el año entero, cerrar el tercer trimestre impediría planificar
    el cuarto, que es cuando se hace."""
    ter.congelar_objetivo(uow, periodo="2026-T3", motivo="cerrado")
    cuarto = ter.crear_cuota(
        uow,
        desde=date(2026, 10, 1),
        hasta=date(2026, 12, 31),
        objetivo=Decimal(90000),
        usuario_id=uuid4(),
    )
    assert cuarto.objetivo == Decimal(90000)


def test_descongelar_sin_motivo_no_se_puede_crm_03_02_02_08(uow: UnidadDeTrabajo) -> None:
    """Permitirlo convierte el cierre en un trámite de dos clics, que es no
    tener cierre."""
    ter.congelar_objetivo(uow, periodo="2026-T1", motivo="plan cerrado")
    with pytest.raises(ErrorValidacion) as e:
        ter.descongelar_objetivo(uow, periodo="2026-T1", motivo="   ")
    assert e.value.error_code == "cuota.descongelar_sin_motivo"


def test_descongelar_deja_rastro_y_vuelve_a_dejar_cargar_crm_03_02_02_08(
    uow: UnidadDeTrabajo,
) -> None:
    """Y el rastro es una fila, no un interruptor: descongelar y volver a
    congelar es legítimo —se revisa el plan a mitad de año— y con un booleano
    el segundo cierre pisaría al primero, de modo que «¿cuándo se cerró y por
    qué se reabrió?» no tendría respuesta."""
    quien = uuid4()
    ter.congelar_objetivo(uow, periodo="2026-T2", por=quien, motivo="plan de abril")
    abierto = ter.descongelar_objetivo(
        uow, periodo="2026-T2", por=quien, motivo="revisión por la pérdida del contrato grande"
    )
    assert abierto.descongelado_at is not None
    assert abierto.motivo == "plan de abril"
    assert "contrato grande" in abierto.motivo_descongelacion

    # Y ahora sí entra la cuota revisada.
    nueva = ter.crear_cuota(
        uow,
        desde=date(2026, 4, 1),
        hasta=date(2026, 6, 30),
        objetivo=Decimal(50000),
        usuario_id=quien,
    )
    assert nueva.objetivo == Decimal(50000)

    # Volver a cerrarlo crea una congelación NUEVA: el historial queda entero.
    otra = ter.congelar_objetivo(uow, periodo="2026-T2", por=quien, motivo="plan revisado")
    assert otra.id != abierto.id


def test_congelar_dos_veces_no_duplica_crm_03_02_02_08(uow: UnidadDeTrabajo) -> None:
    """Dos congelaciones vivas del mismo periodo darían dos respuestas a «desde
    cuándo está cerrado»."""
    una = ter.congelar_objetivo(uow, periodo="2026", motivo="plan anual")
    otra = ter.congelar_objetivo(uow, periodo="2026", motivo="otra vez")
    assert una.id == otra.id
    assert una.motivo == "plan anual"


def test_el_periodo_de_una_cuota_se_nombra_igual_que_se_cierra_crm_03_02_02_08() -> None:
    """Si la etiqueta no coincidiera con la que usa quien cierra, la
    congelación no alcanzaría a ninguna cuota y el cierre sería decorativo."""
    assert ter.etiqueta_de_periodo(date(2026, 8, 15), "trimestral") == "2026-T3"
    assert ter.etiqueta_de_periodo(date(2026, 8, 15), "mensual") == "2026-08"
    assert ter.etiqueta_de_periodo(date(2026, 8, 15), "anual") == "2026"
