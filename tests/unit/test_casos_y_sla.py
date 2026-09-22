"""Casos y SLA (CRM-04.01.01, CRM-04.01.02).

Un SLA que no se puede explicar no se puede exigir. Estas pruebas van detrás de
eso: que el reloj cuente horas laborables, que la pausa desplace el vencimiento,
que cambiar la definición no reescriba el pasado y que avisar llegue antes del
incumplimiento y no después.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.datos.calendario import CalendarioLaboral, Festivo
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado

from services.service import servicio as svc
from services.service.modelos import CategoriaCaso, DefinicionSLA, EventoCaso

HOY = date.today()


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


@pytest.fixture
def calendario(db: Any, tenant_id: UUID) -> CalendarioLaboral:
    """Lunes a viernes de 9 a 18, jornada partida."""
    fila = CalendarioLaboral(
        tenant_id=tenant_id,
        clave="oficina",
        nombre="Oficina",
        por_defecto=True,
        horario={
            str(d): [{"desde": "09:00", "hasta": "14:00"}, {"desde": "15:00", "hasta": "18:00"}]
            for d in range(5)
        },
    )
    db.add(fila)
    db.flush()
    return fila


def _sla(db: Any, tenant_id: UUID, **kw: Any) -> DefinicionSLA:
    base = {
        "clave": "estandar",
        "nombre": "Estándar",
        "version": 1,
        "horas_primera_respuesta": 4,
        "horas_resolucion": 24,
        "calendario": "oficina",
        "vigente_desde": HOY - timedelta(days=30),
    }
    base.update(kw)
    fila = DefinicionSLA(tenant_id=tenant_id, **base)
    db.add(fila)
    db.flush()
    return fila


# ── Taxonomía (CRM-04.01.01.02) ───────────────────────────────────────────


def _categoria(db: Any, tenant_id: UUID, clave: str, **kw: Any) -> CategoriaCaso:
    fila = CategoriaCaso(tenant_id=tenant_id, clave=clave, nombre=clave.title(), **kw)
    db.add(fila)
    db.flush()
    return fila


@pytest.mark.db
def test_un_nodo_intermedio_no_clasifica(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Dejar elegir un nodo intermedio convierte «software» en un cajón donde
    acaba la mitad de los casos, y entonces la taxonomía no sirve para agrupar."""
    padre = _categoria(db, tenant_id, "software")
    _categoria(db, tenant_id, "instalacion", padre_id=padre.id)

    with pytest.raises(ErrorValidacion) as e:
        svc.abrir_caso(uow, asunto="No arranca", categoria_id=padre.id)
    assert e.value.error_code == "service.categoria_no_es_hoja"


@pytest.mark.db
def test_la_hoja_si_clasifica_y_sugiere_prioridad(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Propone, no impone: quien atiende sabe cosas que la taxonomía no."""
    padre = _categoria(db, tenant_id, "software")
    hoja = _categoria(db, tenant_id, "caida_total", padre_id=padre.id, prioridad_sugerida="critica")
    caso = svc.abrir_caso(uow, asunto="Todo caído", categoria_id=hoja.id)
    assert caso.prioridad == "critica"

    otro = svc.abrir_caso(uow, asunto="Todo caído", categoria_id=hoja.id, prioridad="baja")
    assert otro.prioridad == "baja"


@pytest.mark.db
def test_la_ruta_de_clasificacion_llega_a_la_raiz(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """«Cuántos casos de software» no se puede contestar si solo se guarda la
    hoja sin saber de qué cuelga."""
    padre = _categoria(db, tenant_id, "software")
    medio = _categoria(db, tenant_id, "instalacion", padre_id=padre.id)
    hoja = _categoria(db, tenant_id, "licencia", padre_id=medio.id)
    assert svc.ruta_de_categoria(db, tenant_id, hoja.id) == [
        "Software",
        "Instalacion",
        "Licencia",
    ]


# ── Severidad y prioridad (CRM-04.01.01.01) ───────────────────────────────


@pytest.mark.db
def test_severidad_y_prioridad_son_dos_campos(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """«Grave pero puede esperar» y «menor pero urgente por el cliente» son
    casos reales que un solo campo no puede representar."""
    caso = svc.abrir_caso(uow, asunto="Fuga lenta", severidad="critica", prioridad="baja")
    assert caso.severidad == "critica" and caso.prioridad == "baja"


@pytest.mark.db
def test_una_prioridad_inventada_se_rechaza(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    with pytest.raises(ErrorValidacion) as e:
        svc.abrir_caso(uow, asunto="X", prioridad="urgentisima")
    assert e.value.error_code == "service.prioridad_no_valida"


@pytest.mark.db
def test_el_caso_tiene_codigo_legible(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Es lo que el cliente escribe en el asunto de un correo; sin él la
    referencia acaba siendo un UUID que nadie transcribe bien."""
    caso = svc.abrir_caso(uow, asunto="Primero")
    assert caso.codigo == f"CAS-{HOY.year}-00001"


# ── SLA: cuál aplica (CRM-04.01.02.02) ────────────────────────────────────


@pytest.mark.db
def test_gana_el_sla_mas_especifico(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, calendario: Any, uow: Any
) -> None:
    """Un cliente con contrato especial no puede recibir el trato estándar, que
    es justo el que se paga por no tener."""
    cuenta = uuid4()
    _sla(db, tenant_id, clave="general")
    _sla(db, tenant_id, clave="vip", cuenta_id=cuenta, horas_resolucion=4)

    caso = svc.abrir_caso(uow, asunto="Urgente", cuenta_id=cuenta)
    assert caso.sla_clave == "vip"


@pytest.mark.db
def test_ante_dos_igual_de_especificas_gana_la_version_mas_alta(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, calendario: Any, uow: Any
) -> None:
    """Publicar una versión nueva es la forma de decir «a partir de ahora,
    esta»."""
    _sla(db, tenant_id, clave="estandar", version=1, horas_resolucion=24)
    _sla(db, tenant_id, clave="estandar", version=2, horas_resolucion=8)
    caso = svc.abrir_caso(uow, asunto="X")
    assert caso.sla_version == 2


@pytest.mark.db
def test_cambiar_el_sla_no_reescribe_el_pasado(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, calendario: Any, uow: Any
) -> None:
    """Un contrato renegociado no puede convertir en incumplidos casos que se
    atendieron a tiempo con las reglas de entonces."""
    _sla(db, tenant_id, clave="estandar", horas_resolucion=24)
    caso = svc.abrir_caso(uow, asunto="Antiguo")
    vence_antes = caso.vence_resolucion_at

    _sla(db, tenant_id, clave="estandar", version=2, horas_resolucion=1)
    db.flush()
    db.refresh(caso)
    assert caso.vence_resolucion_at == vence_antes


@pytest.mark.db
def test_sin_sla_aplicable_se_dice(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Un caso sin compromiso no es un caso cumplido."""
    caso = svc.abrir_caso(uow, asunto="Sin contrato")
    assert caso.sla_clave is None
    assert caso.vence_resolucion_at is None


# ── El reloj (CRM-04.01.02.03, .04) ───────────────────────────────────────


@pytest.mark.db
def test_el_plazo_cuenta_horas_laborables(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, calendario: Any, uow: Any
) -> None:
    """Es lo que hace que un aviso entrado el viernes a las 18:00 no se incumpla
    el sábado a las 22:00, cuando no había nadie."""
    _sla(db, tenant_id, horas_resolucion=4)
    caso = svc.abrir_caso(uow, asunto="X")
    # El vencimiento cae dentro del horario o después, nunca 4 horas de reloj
    # exactas si se abre fuera de jornada.
    assert caso.vence_resolucion_at is not None
    assert caso.vence_resolucion_at > caso.created_at


@pytest.mark.db
def test_un_festivo_no_cuenta(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, calendario: Any
) -> None:
    """Sin festivos, un plazo vencería en Navidad."""
    from crmcore.datos.calendario import es_laborable

    dia = HOY + timedelta(days=(0 - HOY.weekday()) % 7 + 7)  # un lunes futuro
    db.add(Festivo(tenant_id=tenant_id, calendario_id=calendario.id, fecha=dia, nombre="Fiesta"))
    db.flush()
    momento = datetime.combine(dia, time(10, 0), tzinfo=timezone.utc)
    assert es_laborable(db, calendario, momento) is False


@pytest.mark.db
def test_la_pausa_desplaza_el_vencimiento(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, calendario: Any, uow: Any
) -> None:
    """Si no se desplazara, parar el reloj sería decorativo: el caso se marcaría
    incumplido por una espera que era del cliente."""
    _sla(db, tenant_id, horas_resolucion=8)
    caso = svc.abrir_caso(uow, asunto="X")
    vence_antes = caso.vence_resolucion_at

    svc.cambiar_estado(uow, caso.id, estado="esperando_cliente")
    caso.pausado_desde = datetime.now(timezone.utc) - timedelta(hours=3)
    db.flush()
    svc.cambiar_estado(uow, caso.id, estado="en_curso")

    assert caso.pausa_acumulada_s >= 3 * 3600 - 5
    assert caso.vence_resolucion_at > vence_antes


@pytest.mark.db
def test_la_pausa_se_acumula(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, calendario: Any, uow: Any
) -> None:
    """Un caso que entra y sale cuatro veces perdería tres de las cuatro esperas
    si solo se guardara la última, y el tiempo de resolución saldría peor de lo
    que fue."""
    _sla(db, tenant_id, horas_resolucion=8)
    caso = svc.abrir_caso(uow, asunto="X")

    for _ in range(3):
        svc.cambiar_estado(uow, caso.id, estado="esperando_cliente")
        caso.pausado_desde = datetime.now(timezone.utc) - timedelta(hours=1)
        db.flush()
        svc.cambiar_estado(uow, caso.id, estado="en_curso")

    assert caso.pausa_acumulada_s >= 3 * 3600 - 15


@pytest.mark.db
def test_solo_la_primera_respuesta_cuenta(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, calendario: Any, uow: Any
) -> None:
    """Registrar cada respuesta como «primera» haría que el indicador midiera la
    última, que es el número que siempre sale bien."""
    _sla(db, tenant_id)
    caso = svc.abrir_caso(uow, asunto="X")
    svc.registrar_primera_respuesta(uow, caso.id)
    primera = caso.primera_respuesta_at
    svc.registrar_primera_respuesta(uow, caso.id)
    assert caso.primera_respuesta_at == primera


@pytest.mark.db
def test_responder_tarde_marca_el_incumplimiento(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, calendario: Any, uow: Any
) -> None:
    _sla(db, tenant_id, horas_primera_respuesta=4)
    caso = svc.abrir_caso(uow, asunto="X")
    caso.vence_primera_respuesta_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.flush()
    svc.registrar_primera_respuesta(uow, caso.id)
    assert caso.incumplio_primera_respuesta is True


@pytest.mark.db
def test_los_dos_incumplimientos_se_marcan_por_separado(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, calendario: Any, uow: Any
) -> None:
    """Incumplir la primera respuesta y incumplir la resolución son dos
    conversaciones distintas con el cliente."""
    _sla(db, tenant_id)
    caso = svc.abrir_caso(uow, asunto="X")
    svc.registrar_primera_respuesta(uow, caso.id)
    caso.vence_resolucion_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.flush()
    svc.cerrar_caso(uow, caso.id, motivo="resuelto")

    assert caso.incumplio_primera_respuesta is False
    assert caso.incumplio_resolucion is True


# ── Riesgo (CRM-04.01.02.05) ──────────────────────────────────────────────


@pytest.mark.db
def test_se_avisa_antes_de_incumplir(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, calendario: Any, uow: Any
) -> None:
    """Avisar cuando ya se ha incumplido no sirve de nada: el incumplimiento ya
    está."""
    _sla(db, tenant_id, horas_resolucion=8)
    caso = svc.abrir_caso(uow, asunto="Va justo")
    caso.vence_resolucion_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    caso.created_at = datetime.now(timezone.utc) - timedelta(hours=8)
    db.flush()

    riesgo = svc.en_riesgo(db, tenant_id)
    assert riesgo and riesgo[0]["caso_id"] == str(caso.id)
    assert riesgo[0]["ya_incumplido"] is False


@pytest.mark.db
def test_el_riesgo_se_ordena_por_lo_que_queda_no_por_prioridad(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, calendario: Any, uow: Any
) -> None:
    """Un caso crítico con seis horas por delante puede esperar a uno medio que
    vence en diez minutos."""
    _sla(db, tenant_id, horas_resolucion=8)
    critico = svc.abrir_caso(uow, asunto="Crítico", prioridad="critica")
    medio = svc.abrir_caso(uow, asunto="Medio", prioridad="media")
    ahora = datetime.now(timezone.utc)
    for caso, minutos in ((critico, 300), (medio, 10)):
        caso.created_at = ahora - timedelta(hours=8)
        caso.vence_resolucion_at = ahora + timedelta(minutes=minutos)
    db.flush()

    riesgo = svc.en_riesgo(db, tenant_id)
    assert riesgo[0]["caso_id"] == str(medio.id)


@pytest.mark.db
def test_un_caso_ya_resuelto_no_sale_en_riesgo(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, calendario: Any, uow: Any
) -> None:
    _sla(db, tenant_id, horas_resolucion=8)
    caso = svc.abrir_caso(uow, asunto="X")
    svc.cerrar_caso(uow, caso.id, motivo="resuelto")
    db.flush()
    assert svc.en_riesgo(db, tenant_id, umbral_pct=1) == []


# ── Cierre y reapertura (CRM-04.01.01.09, .10) ────────────────────────────


@pytest.mark.db
def test_cerrar_exige_motivo(db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any) -> None:
    """Sin motivo, el informe de cierres dice cuántos se cerraron y no por qué,
    que es la única parte útil."""
    caso = svc.abrir_caso(uow, asunto="X")
    with pytest.raises(ErrorValidacion) as e:
        svc.cerrar_caso(uow, caso.id, motivo="  ")
    assert e.value.error_code == "service.cierre_sin_motivo"


@pytest.mark.db
def test_no_se_cierra_dos_veces(db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any) -> None:
    caso = svc.abrir_caso(uow, asunto="X")
    svc.cerrar_caso(uow, caso.id, motivo="resuelto")
    with pytest.raises(Conflicto):
        svc.cerrar_caso(uow, caso.id, motivo="resuelto")


@pytest.mark.db
def test_reabrir_dentro_de_la_ventana(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    caso = svc.abrir_caso(uow, asunto="X")
    svc.cerrar_caso(uow, caso.id, motivo="resuelto")
    svc.reabrir_caso(uow, caso.id, motivo="el problema sigue", ventana_dias=30)
    assert caso.estado == "en_curso" and caso.reaperturas == 1


@pytest.mark.db
def test_fuera_de_la_ventana_no_se_reabre(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Reabrir un caso de hace ocho meses falsea todos los indicadores del
    periodo en que se cerró, y esos números ya están en un informe."""
    caso = svc.abrir_caso(uow, asunto="X")
    svc.cerrar_caso(uow, caso.id, motivo="resuelto")
    caso.cerrado_at = datetime.now(timezone.utc) - timedelta(days=240)
    db.flush()

    with pytest.raises(Conflicto) as e:
        svc.reabrir_caso(uow, caso.id, motivo="vuelve", ventana_dias=30)
    assert e.value.error_code == "service.fuera_de_ventana_de_reapertura"


@pytest.mark.db
def test_reabrir_exige_motivo(db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any) -> None:
    caso = svc.abrir_caso(uow, asunto="X")
    svc.cerrar_caso(uow, caso.id, motivo="resuelto")
    with pytest.raises(ErrorValidacion):
        svc.reabrir_caso(uow, caso.id, motivo="")


# ── Jerarquía e incidencias masivas (CRM-04.01.01.04, .11) ────────────────


@pytest.mark.db
def test_cerrar_la_masiva_cierra_todos_los_colgados(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Cerrarlos uno a uno no solo es trabajo: es que la respuesta que recibe
    cada cliente acaba siendo distinta."""
    maestro = svc.abrir_caso(uow, asunto="Caída del servicio")
    hijos = [svc.abrir_caso(uow, asunto=f"No entro {i}") for i in range(3)]
    for hijo in hijos:
        svc.enlazar_a_maestro(uow, hijo.id, maestro.id)
    db.flush()

    salida = svc.cerrar_masiva(uow, maestro.id, motivo="incidencia resuelta")
    assert salida["cuantos"] == 3
    assert all(h.estado == "cerrado" for h in hijos)
    assert maestro.estado == "cerrado"


@pytest.mark.db
def test_un_maestro_no_cuelga_de_otro_maestro(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Una cadena de maestros deja algo que nadie sabe cerrar."""
    raiz = svc.abrir_caso(uow, asunto="Raíz")
    medio = svc.abrir_caso(uow, asunto="Medio")
    hoja = svc.abrir_caso(uow, asunto="Hoja")
    svc.enlazar_a_maestro(uow, medio.id, raiz.id)
    db.flush()

    with pytest.raises(ErrorValidacion) as e:
        svc.enlazar_a_maestro(uow, hoja.id, medio.id)
    assert e.value.error_code == "service.maestro_encadenado"


@pytest.mark.db
def test_un_duplicado_no_se_borra(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """El cliente que lo abrió tiene derecho a ver su caso y su respuesta;
    borrarlo hace que su referencia deje de existir."""
    original = svc.abrir_caso(uow, asunto="El bueno")
    copia = svc.abrir_caso(uow, asunto="El mismo otra vez")
    svc.marcar_duplicado(uow, copia.id, original.id)
    db.flush()

    assert svc.exigir_caso(db, copia.id) is not None
    assert copia.duplicado_de_id == original.id
    assert copia.motivo_cierre == "duplicado"


@pytest.mark.db
def test_un_caso_no_es_duplicado_de_si_mismo(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    caso = svc.abrir_caso(uow, asunto="X")
    with pytest.raises(ErrorValidacion):
        svc.marcar_duplicado(uow, caso.id, caso.id)


# ── Cumplimiento (CRM-04.01.02.03) ────────────────────────────────────────


@pytest.mark.db
def test_el_cumplimiento_separa_respuesta_de_resolucion(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, calendario: Any, uow: Any
) -> None:
    """Un porcentaje único esconde que se contesta rápido y se resuelve tarde,
    que es el patrón más común y el que más queja genera."""
    _sla(db, tenant_id)
    caso = svc.abrir_caso(uow, asunto="X")
    svc.registrar_primera_respuesta(uow, caso.id)
    caso.vence_resolucion_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.flush()
    svc.cerrar_caso(uow, caso.id, motivo="resuelto")
    db.flush()

    salida = svc.cumplimiento(
        db, tenant_id, desde=HOY - timedelta(days=1), hasta=HOY + timedelta(days=1)
    )
    assert salida["primera_respuesta"]["cumplimiento_pct"] == 100.0
    assert salida["resolucion"]["cumplimiento_pct"] == 0.0


@pytest.mark.db
def test_sin_casos_no_se_dice_cien_por_cien(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Sería un verde que nadie se ha ganado."""
    salida = svc.cumplimiento(db, tenant_id, desde=HOY, hasta=HOY)
    assert salida["medible"] is False
    assert salida["primera_respuesta"]["cumplimiento_pct"] is None


@pytest.mark.db
def test_el_historial_del_caso_se_puede_ordenar(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Con `now()` los eventos de la misma transacción compartirían instante y el
    historial dejaría de poder ordenarse."""
    caso = svc.abrir_caso(uow, asunto="X")
    svc.cambiar_estado(uow, caso.id, estado="en_curso")
    svc.cambiar_estado(uow, caso.id, estado="esperando_cliente")
    db.flush()

    from sqlalchemy import select

    eventos = (
        db.execute(
            select(EventoCaso).where(EventoCaso.caso_id == caso.id).order_by(EventoCaso.created_at)
        )
        .scalars()
        .all()
    )
    assert [e.tipo for e in eventos] == ["abierto", "estado", "estado"]
    assert len({e.created_at for e in eventos}) == 3


@pytest.mark.db
def test_no_se_ve_un_caso_de_otro_tenant(
    db: Any, tenant_id: UUID, otro_tenant_id: UUID, contexto_tenant: UUID
) -> None:
    with pytest.raises(NoEncontrado):
        svc.exigir_caso(db, uuid4())
