"""Lo que decide si una integración de suite sigue viva a los seis meses
(`CRM-06.01.03.11` a `.17`, `.19`, `.20`).

Casi nada de esto falla: **se degrada en silencio**. Una suscripción que caduca,
un proveedor que corta la cuota, un buzón que lleva una semana sin credencial.
Nada de eso da un error rojo: el CRM se queda quieto y la gente deja de fiarse
sin saber muy bien por qué.

Medido el 05-10-2026: ocho decisiones de este módulo estaban escritas, probadas
y **sin que las llamara nadie**. Las dos peores:

  * `por_renovar` tenía ruta y `caer_a_sondeo` no tenía llamante. O sea: el
    sistema sabía decir qué suscripciones se iban a morir, lo enseñaba en una
    pantalla y **no hacía nada**.
  * `estado_credencial` distinguía «hay que renovar», «hay que avisar» y «esto
    se va a romper solo», y no lo miraba nunca — y además no tenía de dónde:
    la caducidad de la credencial no se guardaba en ninguna parte.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Prohibido

from services.integration import suites as su
from services.integration import suites_operacion as sop

AHORA = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


def _suscripcion(uow: UnidadDeTrabajo, *, caduca_at: datetime | None) -> su.SuscripcionSuite:
    fila = su.SuscripcionSuite(
        tenant_id=uow.tenant_id,
        usuario_id=uuid4(),
        perfil="m365",
        recurso="correo",
        externo_id=uuid4().hex,
        caduca_at=caduca_at,
        estado="activa",
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila


def test_la_que_ya_caduco_cae_al_sondeo_en_vez_de_quedarse_muda(uow: UnidadDeTrabajo) -> None:
    """**Esta es la del agujero.**

    Quedarse esperando avisos que ya no llegan no da ningún error: simplemente
    no entra nada, y el usuario lo descubre cuando echa de menos una cita.
    """
    muerta = _suscripcion(uow, caduca_at=AHORA - timedelta(hours=2))
    salida = su.mantener_suscripciones(uow, ahora=AHORA)
    assert len(salida["caidas_a_sondeo"]) == 1
    uow.db.refresh(muerta)
    assert muerta.en_sondeo is True
    assert muerta.estado != "activa"
    assert muerta.motivo, "cae al sondeo sin decir por qué"


def test_la_que_caduca_pronto_se_avisa_pero_no_se_tira(uow: UnidadDeTrabajo) -> None:
    """Todavía funciona. Tirarla antes de tiempo convierte un aviso en una
    degradación, y sondear no es lo mismo que enterarse al instante."""
    viva = _suscripcion(uow, caduca_at=AHORA + timedelta(minutes=30))
    salida = su.mantener_suscripciones(uow, ahora=AHORA)
    assert salida["caidas_a_sondeo"] == []
    assert [s["id"] for s in salida["por_renovar"]] == [str(viva.id)]
    uow.db.refresh(viva)
    assert viva.en_sondeo is False


def test_la_que_no_dice_cuando_caduca_sale_avisada(uow: UnidadDeTrabajo) -> None:
    """Todas caducan: la que no lo declara es la que se muere sin avisar."""
    _suscripcion(uow, caduca_at=None)
    salida = su.mantener_suscripciones(uow, ahora=AHORA)
    assert salida["sin_caducidad_declarada"]
    assert salida["aviso"]


# ── La credencial que se rompe sola ───────────────────────────────────────


def _consentimiento(
    uow: UnidadDeTrabajo, *, caduca: datetime | None, refresco: bool
) -> su.ConsentimientoSuite:
    fila = su.ConsentimientoSuite(
        tenant_id=uow.tenant_id,
        usuario_id=uuid4(),
        perfil="m365",
        recurso="correo",
        sentido="leer",
        concedido_at=AHORA - timedelta(days=30),
        credencial_caduca_at=caduca,
        tiene_refresco=refresco,
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila


def test_una_credencial_sin_refresco_y_con_caducidad_se_dice_ahora_no_el_martes(
    uow: UnidadDeTrabajo,
) -> None:
    """Funciona meses y un martes deja de entrar el correo de veinte personas a
    la vez."""
    bomba = _consentimiento(uow, caduca=AHORA + timedelta(days=20), refresco=False)
    salida = su.salud_de_las_credenciales(uow.db, uow.tenant_id, ahora=AHORA)
    cuales = [c["consentimiento_id"] for c in salida["que_piden_algo"]]
    assert str(bomba.id) in cuales
    assert salida["revisados"] == 1


def test_la_que_no_tiene_caducidad_medida_no_cuenta_como_buena(uow: UnidadDeTrabajo) -> None:
    """De una credencial de la que no consta caducidad no se sabe que esté bien:
    se sabe que no está medida. Tratarla como buena es cómo se llega al martes."""
    sin_medir = _consentimiento(uow, caduca=None, refresco=True)
    salida = su.salud_de_las_credenciales(uow.db, uow.tenant_id, ahora=AHORA)
    cuales = [c["consentimiento_id"] for c in salida["que_piden_algo"]]
    assert str(sin_medir.id) in cuales
    assert any(c["fiable"] is False for c in salida["que_piden_algo"])


def test_una_credencial_con_refresco_y_lejos_no_molesta(uow: UnidadDeTrabajo) -> None:
    """Si saliera también ésta, la lista sería todo y nadie la miraría."""
    _consentimiento(uow, caduca=AHORA + timedelta(days=300), refresco=True)
    salida = su.salud_de_las_credenciales(uow.db, uow.tenant_id, ahora=AHORA)
    assert salida["que_piden_algo"] == []


def test_la_caducidad_concedida_se_guarda_de_verdad(uow: UnidadDeTrabajo) -> None:
    """Sin guardarla, `estado_credencial` sólo podía contestar «no consta
    caducidad»: verdad, e inútil."""
    quien = uuid4()
    cuando = AHORA + timedelta(days=60)
    su.conceder(
        uow,
        usuario_id=quien,
        quien_concede=quien,
        perfil_nombre="m365",
        recursos=["correo"],
        alcances=["Mail.Read"],
        credencial_caduca_at=cuando,
        tiene_refresco=True,
    )
    from sqlalchemy import select

    fila = uow.db.execute(
        select(su.ConsentimientoSuite).where(su.ConsentimientoSuite.usuario_id == quien)
    ).scalar_one()
    assert fila.credencial_caduca_at is not None
    assert fila.tiene_refresco is True


# ── Las dos comprobaciones que van antes de cada vuelta ───────────────────


def test_los_alcances_se_miran_antes_de_llamar_y_no_despues_de_fallar() -> None:
    """Llamar sin el permiso y esperar el 403 gasta una petición de la cuota del
    tenant para averiguar algo que ya se sabía."""
    with pytest.raises(Prohibido) as fallo:
        sop.exigir_alcances(concedidos=["Mail.Read"], necesarios=["Mail.Read", "Calendars.Read"])
    assert fallo.value.error_code == "suite.alcance_insuficiente"
    assert "Calendars.Read" in fallo.value.detalle["faltan"]


def test_la_regla_del_usuario_no_puede_ensanchar_la_del_tenant() -> None:
    """Si pudiera, la política de la empresa sería una sugerencia: bastaría con
    que una persona marcara «traerlo todo»."""
    salida = sop.combinar_reglas(
        del_tenant={"carpetas": ["Bandeja"], "incluir_adjuntos": False},
        del_usuario={"carpetas": ["Bandeja", "Privado"], "incluir_adjuntos": True},
    )
    assert "Privado" not in (salida.get("carpetas") or [])
    assert salida.get("incluir_adjuntos") is not True
