"""Lo que sale solo en marketing: envíos programados y pasos de recorrido
(CRM-02.02.02.05, CRM-02.02.02.01).

Hasta el 09-11-2026 un envío «a su mejor hora» no salía a ninguna hora: sólo
cuando alguien pulsaba «despachar». Ahora lo mueve una tarea periódica, y actúa
con la identidad de quien lo programó o publicó —foto de sus permisos al
hacerlo—. Lo que no la tiene no sale y lo dice.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.authz.principal import Principal
from crmcore.db.uow import UnidadDeTrabajo
from sqlalchemy import event, select

from services.marketing import campanas as cmp
from services.marketing import envios as env
from services.marketing import recorridos as rec
from services.marketing import vista_correo as vis


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


@pytest.fixture
def mandados(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """El servidor de correo: apunta a quién se manda, no manda nada."""
    from crmcore.notificaciones.smtp import TransporteSMTP

    valores = {
        "dominio_promocional": "info.marca.com",
        "remitente_promocional": "noticias@info.marca.com",
        "correo_flujo_promocional": {"host": "smtp-promo.local"},
    }
    original = vis._ajuste
    monkeypatch.setattr(
        vis,
        "_ajuste",
        lambda clave, db: valores[clave] if clave in valores else original(clave, db),
    )
    salida: list[str] = []
    monkeypatch.setattr(
        TransporteSMTP, "_enviar", lambda self, correo, host, config, s: salida.append(correo["To"])
    )
    return salida


def _quien() -> Principal:
    return Principal(
        id=uuid4(),
        permisos=frozenset({"campana:write", "opportunity:read"}),
        roles=frozenset({"marketing"}),
    )


def _plantilla(uow: UnidadDeTrabajo, clave: str = "promo") -> None:
    from services.marketing.correo import PlantillaMarketing

    uow.db.add(
        PlantillaMarketing(
            tenant_id=uow.tenant_id,
            clave=clave,
            nombre=clave,
            asunto="Hola {{nombre|cliente}}",
            clase="promocional",
            bloques=[],
        )
    )
    uow.db.flush()


def _perfil(uow: UnidadDeTrabajo) -> UUID:
    from services.marketing.modelos import PerfilMarketing

    quien = uuid4()
    uow.db.add(
        PerfilMarketing(
            tenant_id=uow.tenant_id,
            objeto="contacto",
            objeto_id=quien,
            email=f"{quien.hex[:8]}@cliente.com",
        )
    )
    uow.db.flush()
    return quien


def _programar(uow: UnidadDeTrabajo, *, por: Any) -> UUID:
    _plantilla(uow)
    campana = cmp.crear(uow, clave=f"c{uuid4().hex[:6]}", nombre="c")
    uow.db.flush()
    env.programar(
        uow,
        origen="campana",
        origen_id=campana.id,
        destinatarios=[_perfil(uow)],
        plantilla="promo",
        inmediato=True,
        por=env.foto(por),
    )
    return campana.id


def _envios(db: Any, origen_id: UUID) -> list[env.EnvioProgramado]:
    db.expire_all()
    return list(
        db.execute(
            select(env.EnvioProgramado).where(env.EnvioProgramado.origen_id == origen_id)
        ).scalars()
    )


def _vuelta_de_envios() -> dict[str, Any]:
    from crmcore.tareas import por_tenant

    return por_tenant(env.tenants_con_envios_vencidos, env.despachar_vencidos)()


# ── Envíos ────────────────────────────────────────────────────────────────


def test_el_envio_vencido_sale_solo_con_quien_lo_programo(
    db: Any, uow: UnidadDeTrabajo, contexto_tenant: UUID, mandados: list[str]
) -> None:
    quien = _quien()
    campana = _programar(uow, por=quien)
    [envio] = _envios(db, campana)
    assert envio.programado_por_id == quien.id
    assert envio.programado_con["permisos"] == ["campana:write", "opportunity:read"]

    vuelta = _vuelta_de_envios()

    assert vuelta["tenants"] == 1 and vuelta["fallidos"] == 0
    [envio] = _envios(db, campana)
    assert envio.estado == "enviado" and mandados == [envio.direccion]


def test_no_sale_dos_veces_y_coge_las_filas_sin_esperar_a_las_de_otro(
    db: Any, uow: UnidadDeTrabajo, contexto_tenant: UUID, mandados: list[str]
) -> None:
    _programar(uow, por=_quien())
    sentencias: list[str] = []
    conexion = db.connection()

    def _apuntar(conn: Any, cursor: Any, sql: str, *a: Any) -> None:
        if "FROM envios_programados" in sql and sql.lstrip().upper().startswith("SELECT"):
            sentencias.append(sql)

    event.listen(conexion, "before_cursor_execute", _apuntar)
    try:
        assert env.despachar_vencidos(uow.tenant_id)["enviados"] == 1
        assert env.despachar_vencidos(uow.tenant_id)["enviados"] == 0
    finally:
        event.remove(conexion, "before_cursor_execute", _apuntar)

    assert len(mandados) == 1
    # Dos procesos a la vez se reparten la cola: el que llega segundo salta las
    # filas que el primero tiene cogidas en vez de mandarlas otra vez.
    assert sentencias and all("FOR UPDATE SKIP LOCKED" in s for s in sentencias)


def test_sin_identidad_no_sale_y_dice_por_que(
    db: Any, uow: UnidadDeTrabajo, contexto_tenant: UUID, mandados: list[str]
) -> None:
    campana = _programar(uow, por=None)

    r = env.despachar_vencidos(uow.tenant_id)

    assert r["enviados"] == 0 and r["sin_identidad"] == 1
    [envio] = _envios(db, campana)
    assert envio.estado == "programado" and envio.motivo == env.SIN_IDENTIDAD
    assert "No consta quién lo programó" in envio.motivo
    assert mandados == []
    # Dicho una vez: la vuelta siguiente no lo vuelve a contar.
    assert env.despachar_vencidos(uow.tenant_id)["sin_identidad"] == 0


def test_lo_que_sale_solo_pide_con_los_permisos_que_tenia_y_no_con_mas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from crmcore.http import interno

    pedido: dict[str, Any] = {}
    monkeypatch.setattr(interno, "invocar", lambda **kw: pedido.update(kw) or {"ok": True})
    quien = _quien()

    env.invocar_como(env.foto(quien))(
        metodo="GET", ruta="/api/v1/productos", permisos=["opportunity:read", "producto:read"]
    )

    assert pedido["principal_id"] == quien.id
    assert pedido["permisos"] == ["opportunity:read"] and pedido["roles"] == ["marketing"]


# ── Recorridos ────────────────────────────────────────────────────────────


def _recorrido(uow: UnidadDeTrabajo, *, publicado_por: Any) -> tuple[Any, UUID]:
    _plantilla(uow, "bienvenida")
    nodos = {
        "hola": {
            "tipo": "accion",
            "accion": "email",
            "plantilla": "bienvenida",
            "siguiente": "fin",
        },
        "fin": {"tipo": "fin"},
    }
    fila, _ = rec.crear(uow, clave=f"r{uuid4().hex[:6]}", nombre="R", nodos=nodos, inicio="hola")
    rec.publicar(uow, fila.id, principal=publicado_por)
    persona = _perfil(uow)
    assert rec.entrar(uow, fila.id, objeto_id=persona)["entro"]
    return fila, persona


def test_el_recorrido_avanza_solo_y_su_envio_lleva_a_quien_lo_publico(
    db: Any, uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    from crmcore.tareas import por_tenant

    quien = _quien()
    fila, _ = _recorrido(uow, publicado_por=quien)

    vuelta = por_tenant(rec.tenants_con_recorridos_pendientes, rec.avanzar_solos)()

    assert vuelta["tenants"] == 1 and vuelta["fallidos"] == 0
    [envio] = _envios(db, fila.id)
    assert envio.nodo == "hola" and envio.programado_por_id == quien.id


def test_el_recorrido_sin_quien_lo_publico_no_avanza_solo_y_lo_dice(
    db: Any, uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    fila, _ = _recorrido(uow, publicado_por=None)

    r = rec.avanzar_solos(uow.tenant_id)

    assert r["pendientes"] == 0 and r["sin_identidad"] == [fila.clave]
    assert _envios(db, fila.id) == []
