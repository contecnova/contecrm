"""Plantillas de actividad, visitas y recurrencias
(CRM-01.02.01.07, CRM-01.02.01.08, CRM-01.02.01.09).

Tres cosas pequeñas que cambian el día a día, y tres formas de estropearlas:

  * la plantilla que deja todas las tareas en quien la lanzó,
  * el check-in que se puede falsificar desde el móvil,
  * y la recurrente que se acumula hasta que nadie mira la bandeja.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado
from crmcore.fechas import hoy

from services.party import actividades_extra as ax


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


def _plantilla(uow: UnidadDeTrabajo, actividades: list[dict[str, Any]], **kw: Any):
    base: dict[str, Any] = {
        "clave": "implantacion",
        "nombre": "Implantación",
        "proceso": "implantacion",
        "actividades": actividades,
    }
    base.update(kw)
    fila = ax.PlantillaActividades(tenant_id=uow.tenant_id, **base)
    uow.db.add(fila)
    uow.db.flush()
    return fila


# ── Plantillas (CRM-01.02.01.07) ──────────────────────────────────────────


def test_una_plantilla_vacia_no_crea_nada() -> None:
    with pytest.raises(ErrorValidacion) as e:
        ax.validar_plantilla([])
    assert e.value.error_code == "plantilla_actividades.vacia"


def test_una_actividad_sin_asunto_se_rechaza() -> None:
    """Nadie sabría qué hacer."""
    with pytest.raises(ErrorValidacion) as e:
        ax.validar_plantilla([{"dias": 0}])
    assert e.value.error_code == "plantilla_actividades.sin_asunto"


def test_las_actividades_sin_dueno_avisan() -> None:
    """Convierte una implantación en la lista de tareas de una sola persona."""
    avisos = ax.validar_plantilla([{"asunto": "Arranque", "dias": 0}])
    assert any("de quién son" in a for a in avisos)


def test_los_desfases_cuentan_desde_el_arranque(uow: UnidadDeTrabajo) -> None:
    """Calcularlos desde hoy pone todas las tareas vencidas antes de empezar."""
    _plantilla(
        uow,
        [
            {"asunto": "Arranque", "dias": 0, "asignada_a": str(uuid4())},
            {"asunto": "Plan", "dias": 5, "asignada_a": str(uuid4())},
        ],
    )
    arranque = hoy(uow.db) + timedelta(days=30)
    salida = ax.aplicar_plantilla(
        uow, "implantacion", objeto="cuenta", objeto_id=uuid4(), desde=arranque
    )
    assert salida["creadas"] == 2

    from sqlalchemy import select

    from services.party.modelos import Actividad

    fechas = sorted(a.vence_at.date() for a in uow.db.execute(select(Actividad)).scalars())
    assert fechas[0] == arranque
    assert fechas[1] == arranque + timedelta(days=5)


def test_se_cuenta_cuantas_cayeron_en_quien_la_lanzo(uow: UnidadDeTrabajo) -> None:
    """Sin ese número, una plantilla mal repartida parece bien repartida."""
    _plantilla(
        uow,
        [
            {"asunto": "Con dueño", "dias": 0, "asignada_a": str(uuid4())},
            {"asunto": "Sin dueño", "dias": 1},
            {"asunto": "Por rol", "dias": 2, "rol": "consultor"},
        ],
    )
    salida = ax.aplicar_plantilla(
        uow,
        "implantacion",
        objeto="cuenta",
        objeto_id=uuid4(),
        por=uuid4(),
        asignaciones={"consultor": uuid4()},
    )
    assert salida["sin_dueno_declarado"] == 1


def test_una_plantilla_que_no_existe_da_404(uow: UnidadDeTrabajo) -> None:
    with pytest.raises(NoEncontrado):
        ax.aplicar_plantilla(uow, "no-existe", objeto="cuenta", objeto_id=uuid4())


def test_una_plantilla_desactivada_no_se_aplica(uow: UnidadDeTrabajo) -> None:
    _plantilla(uow, [{"asunto": "x", "dias": 0}], activa=False)
    with pytest.raises(Conflicto):
        ax.aplicar_plantilla(uow, "implantacion", objeto="cuenta", objeto_id=uuid4())


# ── Visitas y check-in (CRM-01.02.01.08) ──────────────────────────────────


def test_la_distancia_se_calcula_de_verdad() -> None:
    """Un check-in cuya distancia la manda el móvil se falsifica cambiando un
    número."""
    # Sagrada Familia y Camp Nou: unos 4,3 km en línea recta.
    metros = ax.distancia_m(41.4036, 2.1744, 41.3809, 2.1228)
    assert 4000 < metros < 5000
    assert ax.distancia_m(41.4036, 2.1744, 41.4036, 2.1744) == 0


def test_estar_lejos_no_bloquea_el_check_in(uow: UnidadDeTrabajo) -> None:
    """Hay polígonos donde el GPS falla cien metros y direcciones mal
    geocodificadas: rechazarlo deja sin registrar una visita que sí ocurrió."""
    salida = ax.check_in(
        uow,
        usuario_id=uuid4(),
        lat=41.4036,
        lon=2.1744,
        lat_esperada=41.3809,
        lon_esperada=2.1228,
        tope_m=500,
    )
    assert salida["fuera_de_sitio"] is True
    assert salida["visita_id"]


def test_sin_punto_esperado_no_se_da_por_comprobada(uow: UnidadDeTrabajo) -> None:
    """Se registra igual y se dice, en vez de dar por buena una visita sin
    comprobar."""
    salida = ax.check_in(uow, usuario_id=uuid4(), lat=41.4, lon=2.1)
    assert salida["comprobada"] is False
    assert salida["distancia_m"] is None


def test_una_precision_mala_invalida_la_distancia(uow: UnidadDeTrabajo) -> None:
    """Una distancia de 300 m con una precisión de ±800 m no significa nada."""
    salida = ax.check_in(
        uow,
        usuario_id=uuid4(),
        lat=41.4036,
        lon=2.1744,
        lat_esperada=41.4040,
        lon_esperada=2.1750,
        precision_m=800,
        tope_m=500,
    )
    assert "precisión" in salida["aviso"]


def test_una_visita_de_dos_minutos_se_señala(uow: UnidadDeTrabajo) -> None:
    """Puede ser un error al pulsar y puede ser que no le recibieran, y son cosas
    distintas."""
    entrada = ax.check_in(uow, usuario_id=uuid4(), lat=41.4, lon=2.1)
    salida = ax.check_out(uow, UUID(entrada["visita_id"]))
    assert salida["sospechosamente_corta"] is True


def test_no_se_cierra_dos_veces(uow: UnidadDeTrabajo) -> None:
    entrada = ax.check_in(uow, usuario_id=uuid4(), lat=41.4, lon=2.1)
    ax.check_out(uow, UUID(entrada["visita_id"]))
    with pytest.raises(Conflicto):
        ax.check_out(uow, UUID(entrada["visita_id"]))


# ── Recurrencia (CRM-01.02.01.09) ─────────────────────────────────────────


def _recurrencia(uow: UnidadDeTrabajo, **kw: Any):
    base: dict[str, Any] = {
        "asunto": "Revisión mensual",
        "desde": datetime.now(timezone.utc) - timedelta(minutes=1),
        "patron": "mensual",
        "repeticiones": 6,
    }
    base.update(kw)
    return ax.crear_recurrencia(uow, **base)


def test_una_recurrencia_sin_fin_se_rechaza(uow: UnidadDeTrabajo) -> None:
    """Sigue creando tareas cuando el proyecto lleva dos años cerrado, y quien las
    recibe no sabe ni por qué."""
    with pytest.raises(ErrorValidacion) as e:
        ax.crear_recurrencia(
            uow, asunto="x", desde=datetime.now(timezone.utc), repeticiones=None, hasta=None
        )
    assert e.value.error_code == "recurrencia.sin_fin"


def test_un_patron_inventado_se_rechaza(uow: UnidadDeTrabajo) -> None:
    with pytest.raises(ErrorValidacion):
        _recurrencia(uow, patron="cuando_apetezca")


def test_los_meses_se_suman_como_meses() -> None:
    """Una revisión mensual el día 31 tiene que caer el último día del mes
    siguiente, no el 3 del otro."""
    enero31 = datetime(2026, 1, 31, 9, 0, tzinfo=timezone.utc)
    assert ax._siguiente("mensual", enero31, 1).date() == date(2026, 2, 28)


def test_los_dias_laborables_saltan_el_fin_de_semana() -> None:
    viernes = datetime(2026, 3, 6, 9, 0, tzinfo=timezone.utc)
    assert viernes.weekday() == 4
    assert ax._siguiente("dias_laborables", viernes, 1).weekday() == 0


def test_generar_crea_la_primera(uow: UnidadDeTrabajo) -> None:
    _recurrencia(uow)
    salida = ax.generar_pendientes(uow, uow.tenant_id)
    assert salida["creadas"] == ["Revisión mensual"]


def test_la_siguiente_espera_a_que_se_cierre_la_anterior(uow: UnidadDeTrabajo) -> None:
    """Crear las 52 de golpe llena la bandeja de tareas de dentro de un año, y lo
    que hace la gente es dejar de mirar la bandeja."""
    fila = _recurrencia(uow, patron="diaria")
    ax.generar_pendientes(uow, uow.tenant_id)
    fila.proxima_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    uow.db.flush()
    salida = ax.generar_pendientes(uow, uow.tenant_id)
    assert salida["creadas"] == []
    assert salida["esperando_a_la_anterior"] == ["Revisión mensual"]


def test_al_cerrar_la_anterior_se_crea_la_siguiente(uow: UnidadDeTrabajo) -> None:
    from services.party.modelos import Actividad

    fila = _recurrencia(uow, patron="diaria")
    ax.generar_pendientes(uow, uow.tenant_id)
    anterior = uow.db.get(Actividad, fila.ultima_creada_id)
    anterior.estado = "completada"
    fila.proxima_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    uow.db.flush()
    assert ax.generar_pendientes(uow, uow.tenant_id)["creadas"] == ["Revisión mensual"]


def test_al_agotar_las_repeticiones_se_apaga(uow: UnidadDeTrabajo) -> None:
    fila = _recurrencia(uow, patron="diaria", repeticiones=1, una_a_una=False)
    ax.generar_pendientes(uow, uow.tenant_id)
    fila.proxima_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    uow.db.flush()
    salida = ax.generar_pendientes(uow, uow.tenant_id)
    assert salida["terminadas"] == ["Revisión mensual"]
    assert fila.activa is False


def test_sin_pendientes_no_se_dice_que_todo_va_bien(uow: UnidadDeTrabajo) -> None:
    assert ax.generar_pendientes(uow, uow.tenant_id)["medible"] is False
