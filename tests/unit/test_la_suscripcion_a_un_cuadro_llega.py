"""La suscripción a un cuadro de mando llega (CRM-05.01.02.05).

Medido el 10-11-2026: `SuscripcionCuadro` guardaba una hora y `proxima_at =
ahora + 1 día`, y ningún barrido la leía. Escrita y sin enchufar.

La prueba recorre la cadena entera con la zona del tenant en Madrid y la noche
del cambio de hora de por medio: suscribirse «a las 7, por correo» → el barrido
emite a las 7 de Madrid (05:00 UTC en verano) → la siguiente es a las 7 del
domingo ya en invierno (06:00 UTC) → el evento escrito en la tabla de salida lo
convierte identity en un aviso que sale por correo y sólo por correo.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from sqlalchemy import select

from services.analytics import cuadros as cua
from services.analytics import informes as inf


@pytest.mark.db
def test_a_las_7_de_madrid_llega_por_correo_tambien_la_noche_del_cambio_de_hora(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    from crmcore.bus.modelos import EventoSaliente
    from crmcore.datos.seguimiento import Notificacion
    from crmcore.runtime import settings as rt

    from services.identity.modelos import Membresia, Usuario
    from services.identity.notificaciones import consumir_evento

    rt.fijar(db, "zona_horaria", "Europe/Madrid", ambito="tenant", ambito_id=str(tenant_id))
    ana = Usuario(email="ana@ejemplo.test", nombre="Ana", activo=True)
    db.add(ana)
    db.flush()
    db.add(Membresia(tenant_id=tenant_id, usuario_id=ana.id, activa=True))
    uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
    cuadro = inf.CuadroMando(tenant_id=tenant_id, clave="direccion", nombre="Dirección")
    db.add(cuadro)
    db.flush()

    reloj = {"ahora": datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)}
    monkeypatch.setattr(cua, "_ahora", lambda: reloj["ahora"])

    s = cua.suscribirse(
        uow, cuadro_id=cuadro.id, usuario_id=ana.id, periodicidad="diaria", hora=7, canal="correo"
    )
    # Las 7 del sábado en Madrid, aún en verano (UTC+2).
    assert s.proxima_at == datetime(2026, 10, 24, 5, 0, tzinfo=timezone.utc)

    # Antes de la hora no sale nada.
    reloj["ahora"] = datetime(2026, 10, 24, 4, 59, tzinfo=timezone.utc)
    assert cua.correr_suscripciones(uow, tenant_id)["revisadas"] == 0

    reloj["ahora"] = datetime(2026, 10, 24, 5, 0, 30, tzinfo=timezone.utc)
    salida = cua.correr_suscripciones(uow, tenant_id)
    assert salida["mandadas"] == [str(s.id)]
    # El domingo ya es invierno (UTC+1): las 7 de Madrid son las 06:00 UTC.
    assert s.proxima_at == datetime(2026, 10, 25, 6, 0, tzinfo=timezone.utc)

    # Lo que llegó a la TABLA DE SALIDA, no lo que quedó en memoria.
    uow.volcar()
    db.flush()
    sobre = (
        db.execute(select(EventoSaliente).where(EventoSaliente.tipo == "dashboard.delivered"))
        .scalars()
        .one()
        .sobre
    )
    assert sobre["data"]["canales"] == ["correo"]
    db.commit()

    # Como lo entrega el bus: `tipo`, `tenant_id` y `data` del sobre.
    mensaje = {"tipo": sobre["type"], "tenant_id": sobre["tenant_id"], "data": sobre["data"]}
    asyncio.run(consumir_evento(mensaje))
    db.expunge_all()
    aviso = db.query(Notificacion).filter_by(usuario_id=ana.id).one()
    assert aviso.objeto_tipo == "cuadro_mando" and aviso.objeto_id == cuadro.id
    assert "Dirección" in aviso.titulo
    assert aviso.canales == ["correo"]


@pytest.mark.db
def test_un_cuadro_borrado_apaga_la_suscripcion_y_dice_por_que(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
    cuadro = inf.CuadroMando(tenant_id=tenant_id, clave="x", nombre="X")
    db.add(cuadro)
    db.flush()
    s = cua.suscribirse(uow, cuadro_id=cuadro.id, usuario_id=UUID(int=1), periodicidad="diaria")
    cuadro.activo = False
    reloj = s.proxima_at
    monkeypatch.setattr(cua, "_ahora", lambda: reloj)
    salida = cua.correr_suscripciones(uow, tenant_id)
    assert salida["mandadas"] == [] and len(salida["apagadas"]) == 1
    assert s.activa is False and s.ultimo_error
