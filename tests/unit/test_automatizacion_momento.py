"""Inmediata, diferida o programada, de verdad (CRM-00.03.03.05).

`momento` y `programacion` se guardaban en cada regla y **no los leía nadie**:
todo corría en el instante del disparo y una regla «los lunes a las 8» no corría
nunca. Lo que se prueba aquí es lo que se pidió al construirlo:

  · una diferida **no corre dentro del disparo**: queda en la cola y corre
    después, en su propia transacción;
  · una programada corre **a la hora de su horario**, en la zona del tenant, y
    si el proceso estuvo parado corre una vez, no tantas como se perdió;
  · **no se pierde** nada si la ejecución falla a medias —la fila sigue
    pendiente— y **no se repite** lo que llega dos veces.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest

pytestmark = pytest.mark.db

# Una acción sin efectos fuera del motor: deja una variable y sigue. Sirve
# para medir cuándo corre la regla sin montar media integración.
FIJAR = [{"tipo": "fijar", "nombre": "visto", "valor": 1}]


def _regla(db: Any, tenant_id: UUID, **extra: Any) -> Any:
    from services.automation.modelos import Automatizacion

    datos = {
        "nombre": f"Regla {uuid4().hex[:6]}",
        "disparador": "creacion",
        "objetivo": "cuenta",
        "acciones": FIJAR,
        "activa": True,
        **extra,
    }
    fila = Automatizacion(tenant_id=tenant_id, **datos)
    db.add(fila)
    db.flush()
    return fila


def _evento(tenant_id: UUID, *, tipo: str = "account.created", **data: Any) -> dict[str, Any]:
    return {
        "id": str(uuid4()),
        "tipo": tipo,
        "tenant_id": str(tenant_id),
        "data": {"cuenta_id": str(uuid4()), "nombre": "Acme", **data},
    }


def _trazas(db: Any, regla: Any) -> list[Any]:
    from sqlalchemy import select

    from services.automation.modelos import EjecucionAutomatizacion

    return list(
        db.execute(
            select(EjecucionAutomatizacion).where(
                EjecucionAutomatizacion.automatizacion_id == regla.id
            )
        )
        .scalars()
        .all()
    )


def _cola(db: Any, regla: Any) -> list[Any]:
    from sqlalchemy import select

    from services.automation.modelos import EjecucionPendiente

    db.expire_all()
    return list(
        db.execute(
            select(EjecucionPendiente).where(EjecucionPendiente.automatizacion_id == regla.id)
        )
        .scalars()
        .all()
    )


# ── El horario ────────────────────────────────────────────────────────────


def test_el_horario_cae_a_su_hora_en_la_zona_del_tenant() -> None:
    """«Los lunes a las 8» es a las 8 de quien lo escribe, no del servidor."""
    from services.automation.cron import Cron

    madrid = ZoneInfo("Europe/Madrid")
    # Domingo 8 de noviembre de 2026, mediodía en UTC.
    desde = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
    siguiente = Cron("0 8 * * 1").siguiente(desde, madrid)
    assert siguiente.astimezone(madrid) == datetime(2026, 11, 9, 8, 0, tzinfo=madrid)
    # En invierno Madrid va una hora por delante: las 8 son las 7 en UTC.
    assert siguiente == datetime(2026, 11, 9, 7, 0, tzinfo=timezone.utc)


def test_el_cambio_de_hora_no_mueve_la_regla() -> None:
    """La noche del cambio de marzo, «todos los días a las 8» sigue a las 8 de
    su reloj: en UTC pasa de las 7 a las 6. Sumar 24 horas la habría movido."""
    from services.automation.cron import Cron

    madrid = ZoneInfo("Europe/Madrid")
    diaria = Cron("0 8 * * *")
    antes = diaria.siguiente(datetime(2026, 3, 28, 9, 0, tzinfo=timezone.utc), madrid)
    assert antes == datetime(2026, 3, 29, 6, 0, tzinfo=timezone.utc)
    assert antes.astimezone(madrid).hour == 8


def test_un_horario_imposible_o_mal_escrito_se_rechaza() -> None:
    from crmcore.errors import ErrorValidacion

    from services.automation import cron

    for malo in ("", "0 8 * *", "61 * * * *", "0 0 31 2 *", "a b c d e"):
        with pytest.raises(ErrorValidacion):
            cron.leer(malo)
    assert cron.leer("*/15 9-18 * * 1-5").minutos == frozenset({0, 15, 30, 45})


# ── Diferida ──────────────────────────────────────────────────────────────


def test_una_diferida_no_corre_dentro_del_disparo_y_corre_despues(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Lo que pidió quien la escribió: que no corra en la transacción del alta."""
    from services.automation import planificador
    from services.automation.consumidores import consumir_evento

    regla = _regla(db, tenant_id, momento="diferida")
    asyncio.run(consumir_evento(_evento(tenant_id)))

    # Disparada: está en la cola y NO tiene traza todavía.
    cola = _cola(db, regla)
    assert [c.estado for c in cola] == ["pendiente"]
    assert _trazas(db, regla) == []

    salida = planificador.ejecutar_pendientes(tenant_id)
    assert salida["atendidas"] == 1, salida
    cola = _cola(db, regla)
    assert cola[0].estado == "hecha"
    trazas = _trazas(db, regla)
    assert [t.resultado for t in trazas] == ["disparada"]
    # Desde la cola se llega a su traza: el «por qué» de lo que corrió.
    assert cola[0].ejecucion_id == trazas[0].id


def test_la_inmediata_sigue_corriendo_al_momento(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    from services.automation.consumidores import consumir_evento

    regla = _regla(db, tenant_id)
    asyncio.run(consumir_evento(_evento(tenant_id)))
    assert [t.resultado for t in _trazas(db, regla)] == ["disparada"]
    assert _cola(db, regla) == []


def test_el_mismo_evento_dos_veces_encola_una(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """El bus puede entregar dos veces; la regla diferida no corre dos veces."""
    from services.automation.consumidores import consumir_evento

    regla = _regla(db, tenant_id, momento="diferida")
    evento = _evento(tenant_id)
    asyncio.run(consumir_evento(evento))
    asyncio.run(consumir_evento(evento))
    assert len(_cola(db, regla)) == 1


def test_la_espera_de_la_diferida_sale_del_ajuste(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, monkeypatch: Any
) -> None:
    """Con espera, a la hora no le ha llegado su turno y la cola no la toca."""
    from crmcore.config import get_settings

    from services.automation import planificador
    from services.automation.consumidores import consumir_evento

    monkeypatch.setattr(get_settings(), "automatizacion_diferida_espera_s", 3600)
    regla = _regla(db, tenant_id, momento="diferida")
    asyncio.run(consumir_evento(_evento(tenant_id)))
    fila = _cola(db, regla)[0]
    assert fila.ejecutar_at > datetime.now(timezone.utc) + timedelta(minutes=55)
    assert planificador.ejecutar_pendientes(tenant_id)["atendidas"] == 0
    assert _cola(db, regla)[0].estado == "pendiente"


def test_apagarla_antes_de_su_hora_la_descarta(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Apagar es como se para una regla que hace daño: lo que tenía en cola no
    corre igual."""
    from services.automation import planificador
    from services.automation.consumidores import consumir_evento

    regla = _regla(db, tenant_id, momento="diferida")
    asyncio.run(consumir_evento(_evento(tenant_id)))
    regla.activa = False
    db.flush()
    planificador.ejecutar_pendientes(tenant_id)
    assert _cola(db, regla)[0].estado == "descartada"
    assert _trazas(db, regla) == []


def test_si_falla_a_medias_no_se_pierde_y_acaba_en_fallida(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, monkeypatch: Any
) -> None:
    """Una caída a medias deshace la ejecución entera y la fila sigue
    pendiente para la vuelta siguiente; a los N intentos se da por fallida y lo
    dice."""
    from crmcore.config import get_settings

    from services.automation import motor, planificador
    from services.automation.consumidores import consumir_evento

    monkeypatch.setattr(get_settings(), "automatizacion_pendientes_max_intentos", 2)
    regla = _regla(db, tenant_id, momento="diferida")
    asyncio.run(consumir_evento(_evento(tenant_id)))

    def _revienta(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("la base se ha ido")

    monkeypatch.setattr(motor, "ejecutar", _revienta)
    planificador.ejecutar_pendientes(tenant_id)
    fila = _cola(db, regla)[0]
    assert (fila.estado, fila.intentos) == ("pendiente", 1)
    assert "la base se ha ido" in (fila.error or "")
    assert _trazas(db, regla) == []

    # Se aparta: en la misma vuelta no se reintenta contra la misma avería.
    assert fila.ejecutar_at > datetime.now(timezone.utc)
    fila.ejecutar_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.flush()
    planificador.ejecutar_pendientes(tenant_id)
    fila = _cola(db, regla)[0]
    assert (fila.estado, fila.intentos) == ("fallida", 2)


# ── Programada ────────────────────────────────────────────────────────────


def test_disparada_por_evento_espera_a_la_hora_de_su_horario(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    from services.automation.consumidores import consumir_evento
    from services.automation.cron import Cron

    regla = _regla(db, tenant_id, momento="programada", programacion="0 8 * * 1")
    asyncio.run(consumir_evento(_evento(tenant_id)))
    fila = _cola(db, regla)[0]
    esperada = Cron("0 8 * * 1").siguiente(fila.created_at, ZoneInfo("UTC"))
    assert fila.ejecutar_at == esperada
    # Sin zona configurada el tenant está en UTC: el lunes a las 8 en UTC.
    en_utc = fila.ejecutar_at.astimezone(timezone.utc)
    assert en_utc.weekday() == 0 and en_utc.hour == 8


def test_la_programada_corre_a_su_hora_y_una_sola_vez_si_se_perdieron_varias(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Tres días parado no son tres resúmenes iguales al volver: es uno."""
    from services.automation import planificador

    regla = _regla(
        db,
        tenant_id,
        disparador="programada",
        objetivo="oportunidad",
        momento="programada",
        programacion="0 8 * * *",
    )
    assert tenant_id in planificador.tenants_con_trabajo()

    # Primera vuelta: sólo calcula cuándo le toca.
    salida = planificador.una_vuelta(tenant_id)
    assert salida["recalculadas"] == 1 and salida["encoladas"] == 0, salida
    db.refresh(regla)
    assert regla.proxima_ejecucion_at > datetime.now(timezone.utc)

    # Se le hace llegar la hora... de hace tres días.
    hace_tres_dias = datetime.now(timezone.utc) - timedelta(days=3)
    regla.proxima_ejecucion_at = hace_tres_dias
    db.flush()
    salida = planificador.una_vuelta(tenant_id)
    assert salida["encoladas"] == 1 and salida["atendidas"] == 1, salida
    assert [t.resultado for t in _trazas(db, regla)] == ["disparada"]
    db.refresh(regla)
    assert regla.proxima_ejecucion_at > datetime.now(timezone.utc)

    # Y la vuelta siguiente no repite nada.
    salida = planificador.una_vuelta(tenant_id)
    assert salida["encoladas"] == 0 and salida["atendidas"] == 0, salida


def test_cambiar_el_horario_desde_la_ficha_recalcula(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """La ficha deja editar `programacion`: con la próxima hora calculada
    sobre la vieja, el cambio no surtiría efecto hasta la siguiente vuelta."""
    from services.automation import planificador

    regla = _regla(
        db, tenant_id, disparador="programada", momento="programada", programacion="0 8 * * *"
    )
    planificador.una_vuelta(tenant_id)
    regla.programacion = "30 9 * * *"
    db.flush()
    assert tenant_id in planificador.tenants_con_trabajo()
    planificador.una_vuelta(tenant_id)
    db.refresh(regla)
    assert regla.proxima_segun == "30 9 * * *"
    assert regla.proxima_ejecucion_at.astimezone(timezone.utc).minute == 30


def test_un_horario_roto_deja_traza_una_vez(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    from services.automation import planificador

    regla = _regla(
        db, tenant_id, disparador="programada", momento="programada", programacion="no vale"
    )
    planificador.una_vuelta(tenant_id)
    planificador.una_vuelta(tenant_id)
    trazas = _trazas(db, regla)
    assert [t.resultado for t in trazas] == ["fallida"]
    assert "cron" in (trazas[0].error or "")


def test_la_cola_no_viaja_al_sandbox_y_las_reglas_si(
    db: Any, tenant_id: UUID, otro_tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """La copia a un sandbox se salta lo que la tabla declara de su entorno —la
    cola— y las tablas con secretos; las automatizaciones siguen copiándose."""
    from crmcore.datos.copia_sandbox import copiar_tenant

    _regla(db, tenant_id, momento="diferida")
    salida = copiar_tenant(
        db,
        servicio="automation",
        origen=tenant_id,
        destino=otro_tenant_id,
        semilla="s",
        porcentaje=100,
        anonimizar=False,
        conservar=set(),
    )
    fuera = {n["tabla"] for n in salida["no_copiadas"]}
    assert {"ejecuciones_pendientes", "secretos_webhook_automatizacion"} <= fuera, fuera
    assert "automatizaciones" in {c["tabla"] for c in salida["copiadas"]}, salida["copiadas"]
