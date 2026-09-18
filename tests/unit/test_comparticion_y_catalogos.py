"""Compartición de registros (CRM-00.05.02.04) y catálogos del tenant.

Cubre además las plantillas (CRM-07.01.01.04), los calendarios laborales
(CRM-07.01.01.05) y los tipos de cambio con histórico (CRM-07.01.01.06).

El hilo común: las tres son configuración del cliente, y lo que se defiende aquí
es que **ninguna decisión del sistema dependa de un valor escrito en el código**
y que todas se puedan explicar.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.errors import ErrorValidacion, NoEncontrado

from services.identity import comparticion as comp
from services.tenancy import catalogos as cat

# ── Compartición ──────────────────────────────────────────────────────────


def test_el_propietario_ve_y_escribe_su_registro(db: Any, tenant_id: UUID) -> None:
    usuario = uuid4()
    v = comp.visibilidad_de(
        db,
        tenant_id=tenant_id,
        usuario_id=usuario,
        objeto="cuenta",
        registro={"id": uuid4(), "owner_id": usuario},
    )
    assert v.puede_leer and v.puede_escribir
    assert "es su propietario" in v.motivos


def test_el_responsable_ve_lo_de_su_gente(db: Any, tenant_id: UUID) -> None:
    jefe, subordinado = uuid4(), uuid4()
    v = comp.visibilidad_de(
        db,
        tenant_id=tenant_id,
        usuario_id=jefe,
        objeto="cuenta",
        registro={"id": uuid4(), "owner_id": subordinado},
        subordinados={subordinado},
    )
    assert v.puede_leer
    assert "es responsable de quien lo posee" in v.motivos


def test_quien_no_tiene_ninguna_via_no_lo_ve(db: Any, tenant_id: UUID) -> None:
    v = comp.visibilidad_de(
        db,
        tenant_id=tenant_id,
        usuario_id=uuid4(),
        objeto="cuenta",
        registro={"id": uuid4(), "owner_id": uuid4()},
    )
    assert not v.puede_leer
    # Y se dice POR QUÉ no lo ve, que es la mitad del valor de un explicador.
    assert v.motivos == ["ninguna regla lo alcanza"]


def test_los_motivos_se_acumulan(db: Any, tenant_id: UUID) -> None:
    """Es suyo Y además se lo compartieron: quitar la compartición no cambiaría
    nada, y quien pregunta necesita ver las dos vías para saberlo."""
    usuario, registro = uuid4(), uuid4()
    comp.compartir(
        db,
        tenant_id=tenant_id,
        objeto="cuenta",
        registro_id=registro,
        usuario_id=usuario,
        acceso="lectura",
    )
    db.flush()

    v = comp.visibilidad_de(
        db,
        tenant_id=tenant_id,
        usuario_id=usuario,
        objeto="cuenta",
        registro={"id": registro, "owner_id": usuario},
    )
    assert len(v.motivos) >= 2


def test_una_comparticion_caducada_deja_de_dar_acceso(db: Any, tenant_id: UUID) -> None:
    """La caducidad es lo que impide que «compártemelo para esta tarde» se
    convierta en un acceso permanente."""
    usuario, registro = uuid4(), uuid4()
    comp.compartir(
        db,
        tenant_id=tenant_id,
        objeto="cuenta",
        registro_id=registro,
        usuario_id=usuario,
        hasta=date.today() - timedelta(days=1),
    )
    db.flush()

    v = comp.visibilidad_de(
        db,
        tenant_id=tenant_id,
        usuario_id=usuario,
        objeto="cuenta",
        registro={"id": registro, "owner_id": uuid4()},
    )
    assert not v.puede_leer


def test_compartir_dos_veces_actualiza_en_vez_de_duplicar(db: Any, tenant_id: UUID) -> None:
    usuario, registro = uuid4(), uuid4()
    a = comp.compartir(
        db,
        tenant_id=tenant_id,
        objeto="cuenta",
        registro_id=registro,
        usuario_id=usuario,
        acceso="lectura",
    )
    db.flush()
    b = comp.compartir(
        db,
        tenant_id=tenant_id,
        objeto="cuenta",
        registro_id=registro,
        usuario_id=usuario,
        acceso="escritura",
    )
    assert a.id == b.id
    assert b.acceso == "escritura"


def test_revocar_quita_el_acceso(db: Any, tenant_id: UUID) -> None:
    usuario, registro = uuid4(), uuid4()
    c = comp.compartir(
        db, tenant_id=tenant_id, objeto="cuenta", registro_id=registro, usuario_id=usuario
    )
    db.flush()
    comp.revocar(db, c.id)
    db.flush()

    v = comp.visibilidad_de(
        db,
        tenant_id=tenant_id,
        usuario_id=usuario,
        objeto="cuenta",
        registro={"id": registro, "owner_id": uuid4()},
    )
    assert not v.puede_leer


def test_una_regla_por_criterio_comparte_lo_que_cumple(db: Any, tenant_id: UUID) -> None:
    usuario = uuid4()
    db.add(
        comp.ReglaComparticion(
            tenant_id=tenant_id,
            nombre="País Vasco",
            objeto="cuenta",
            condiciones=[{"atributo": "registro.region", "operador": "=", "valor": "PV"}],
            destino_tipo="usuario",
            destino_id=str(usuario),
            acceso="lectura",
        )
    )
    db.flush()

    dentro = comp.visibilidad_de(
        db,
        tenant_id=tenant_id,
        usuario_id=usuario,
        objeto="cuenta",
        registro={"id": uuid4(), "owner_id": uuid4(), "region": "PV"},
    )
    fuera = comp.visibilidad_de(
        db,
        tenant_id=tenant_id,
        usuario_id=usuario,
        objeto="cuenta",
        registro={"id": uuid4(), "owner_id": uuid4(), "region": "CAT"},
    )

    assert dentro.puede_leer and not fuera.puede_leer


# ── Plantillas ────────────────────────────────────────────────────────────


def test_la_plantilla_sustituye_las_variables_que_tiene() -> None:
    p = cat.Plantilla(
        clave="bienvenida",
        nombre="Bienvenida",
        asunto="Hola {{contacto.nombre}}",
        cuerpo="Tu pedido {{pedido.codigo}}",
    )
    asunto, cuerpo = cat.render(p, {"contacto": {"nombre": "Ana"}, "pedido": {"codigo": "A-1"}})
    assert asunto == "Hola Ana"
    assert cuerpo == "Tu pedido A-1"


def test_lo_que_falta_se_queda_visible_y_no_se_vacia() -> None:
    """Un hueco vacío en un correo pasa desapercibido y se manda; un
    `{{nombre}}` en mitad del texto se ve y se corrige."""
    p = cat.Plantilla(clave="x", nombre="x", cuerpo="Hola {{contacto.nombre}}")
    _, cuerpo = cat.render(p, {})
    assert cuerpo == "Hola {{contacto.nombre}}"
    assert cat.variables_sin_resolver(p.cuerpo, {}) == ["contacto.nombre"]


# ── Calendarios laborales ─────────────────────────────────────────────────


def _calendario(db: Any, tenant_id: UUID, **extra: Any) -> cat.CalendarioLaboral:
    datos: dict[str, Any] = {
        "clave": "es",
        "nombre": "España",
        # Lunes a viernes, jornada partida.
        "horario": {
            str(d): [{"desde": "09:00", "hasta": "13:00"}, {"desde": "14:00", "hasta": "18:00"}]
            for d in range(5)
        },
    }
    datos.update(extra)
    c = cat.CalendarioLaboral(tenant_id=tenant_id, **datos)
    db.add(c)
    db.flush()
    return c


def test_la_hora_de_comer_no_cuenta_como_laborable(db: Any, tenant_id: UUID) -> None:
    """Con un solo intervalo por día, la jornada partida se contaría entera."""
    c = _calendario(db, tenant_id)
    lunes = datetime(2026, 9, 14, tzinfo=timezone.utc)  # lunes
    assert cat.es_laborable(db, c, lunes.replace(hour=10))
    assert not cat.es_laborable(db, c, lunes.replace(hour=13, minute=30))
    assert cat.es_laborable(db, c, lunes.replace(hour=15))


def test_el_fin_de_semana_no_es_laborable(db: Any, tenant_id: UUID) -> None:
    c = _calendario(db, tenant_id)
    sabado = datetime(2026, 9, 19, 11, tzinfo=timezone.utc)
    assert not cat.es_laborable(db, c, sabado)


def test_un_festivo_anual_se_compara_sin_el_ano(db: Any, tenant_id: UUID) -> None:
    c = _calendario(db, tenant_id)
    db.add(
        cat.Festivo(
            tenant_id=tenant_id,
            calendario_id=c.id,
            fecha=date(2020, 12, 25),
            nombre="Navidad",
            anual=True,
        )
    )
    db.flush()

    navidad_2026 = datetime(2026, 12, 25, 11, tzinfo=timezone.utc)  # viernes
    assert not cat.es_laborable(db, c, navidad_2026)


def test_el_sla_de_cuatro_horas_de_un_viernes_tarde_vence_el_lunes(
    db: Any, tenant_id: UUID
) -> None:
    """Es el caso que justifica todo esto: contando horas de reloj, un aviso
    entrado el viernes a las 18:00 se incumpliría el sábado a las 22:00, cuando
    no había nadie."""
    c = _calendario(db, tenant_id)
    viernes_tarde = datetime(2026, 9, 18, 16, 0, tzinfo=timezone.utc)

    vence = cat.sumar_horas_laborables(db, c, viernes_tarde, 4)

    assert vence.weekday() == 0  # lunes
    assert vence.date() == date(2026, 9, 21)


def test_un_calendario_sin_horario_no_cuelga_el_proceso(db: Any, tenant_id: UUID) -> None:
    """Sin el tope, el bucle no terminaría nunca y el síntoma sería una petición
    que no responde."""
    c = _calendario(db, tenant_id, clave="vacio", horario={})
    partida = datetime(2026, 9, 18, 10, tzinfo=timezone.utc)

    vence = cat.sumar_horas_laborables(db, c, partida, 4)

    assert vence >= partida + timedelta(days=364)


# ── Monedas ───────────────────────────────────────────────────────────────


def test_convierte_con_el_cambio_vigente_en_la_fecha(db: Any, tenant_id: UUID) -> None:
    """Una oportunidad cerrada en marzo tiene que seguir valiendo lo de marzo."""
    cat.fijar_tipo_cambio(
        db,
        tenant_id=tenant_id,
        desde="EUR",
        hasta="USD",
        tasa=Decimal("1.08"),
        en_fecha=date(2026, 3, 1),
    )
    cat.fijar_tipo_cambio(
        db,
        tenant_id=tenant_id,
        desde="EUR",
        hasta="USD",
        tasa=Decimal("1.15"),
        en_fecha=date(2026, 9, 1),
    )
    db.flush()

    en_marzo = cat.convertir(
        db,
        tenant_id=tenant_id,
        importe=Decimal("1000"),
        desde="EUR",
        hasta="USD",
        en_fecha=date(2026, 3, 15),
    )
    hoy = cat.convertir(
        db,
        tenant_id=tenant_id,
        importe=Decimal("1000"),
        desde="EUR",
        hasta="USD",
        en_fecha=date(2026, 9, 15),
    )

    assert en_marzo == Decimal("1080.00")
    assert hoy == Decimal("1150.00")


def test_no_usa_un_cambio_publicado_despues_de_la_operacion(db: Any, tenant_id: UUID) -> None:
    """Usarlo sería reescribir el pasado con información futura."""
    cat.fijar_tipo_cambio(
        db,
        tenant_id=tenant_id,
        desde="EUR",
        hasta="USD",
        tasa=Decimal("1.10"),
        en_fecha=date(2026, 9, 10),
    )
    db.flush()

    with pytest.raises(NoEncontrado):
        cat.convertir(
            db,
            tenant_id=tenant_id,
            importe=Decimal("100"),
            desde="EUR",
            hasta="USD",
            en_fecha=date(2026, 9, 1),
        )


def test_si_falta_el_par_directo_usa_la_inversa(db: Any, tenant_id: UUID) -> None:
    """Quien carga EUR→USD rara vez carga también USD→EUR, y calcularla es exacto."""
    cat.fijar_tipo_cambio(
        db,
        tenant_id=tenant_id,
        desde="EUR",
        hasta="USD",
        tasa=Decimal("2"),
        en_fecha=date(2026, 9, 1),
    )
    db.flush()

    assert cat.convertir(
        db,
        tenant_id=tenant_id,
        importe=Decimal("100"),
        desde="USD",
        hasta="EUR",
        en_fecha=date(2026, 9, 2),
    ) == Decimal("50.00")


def test_la_misma_moneda_no_necesita_tipo_de_cambio(db: Any, tenant_id: UUID) -> None:
    assert cat.convertir(
        db, tenant_id=tenant_id, importe=Decimal("42.50"), desde="EUR", hasta="EUR"
    ) == Decimal("42.50")


def test_fijar_el_mismo_par_y_fecha_actualiza_en_vez_de_fallar(db: Any, tenant_id: UUID) -> None:
    """Corregir un cambio mal cargado es una operación normal."""
    cat.fijar_tipo_cambio(
        db,
        tenant_id=tenant_id,
        desde="EUR",
        hasta="GBP",
        tasa=Decimal("0.90"),
        en_fecha=date(2026, 9, 1),
    )
    db.flush()
    fila = cat.fijar_tipo_cambio(
        db,
        tenant_id=tenant_id,
        desde="EUR",
        hasta="GBP",
        tasa=Decimal("0.85"),
        en_fecha=date(2026, 9, 1),
    )
    db.flush()
    assert fila.tasa == Decimal("0.85000000")


def test_un_tipo_de_cambio_no_positivo_se_rechaza(db: Any, tenant_id: UUID) -> None:
    with pytest.raises(ErrorValidacion):
        cat.fijar_tipo_cambio(db, tenant_id=tenant_id, desde="EUR", hasta="USD", tasa=Decimal("0"))
