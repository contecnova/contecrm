"""Decidir una aprobación desde el correo, sin entrar al CRM (CRM-00.03.05.12).

Constaba hecho y no lo estaba: el enlace de un solo uso existía, pero canjearlo
pedía una sesión con permiso de decidir —para decidir «sin entrar» había que
entrar— y no se mandaba ningún correo. Estas pruebas van detrás de lo que lo
hace usable y de lo que lo haría peligroso:

  * que al abrirse una etapa salga un correo por aprobador, con la página
    pública y no la API;
  * que la puerta pública funcione SIN sesión, enseñe lo justo y no gaste el
    enlace al mirarlo;
  * que inexistente, usado, caducado o de una etapa que ya no se vota den lo
    mismo;
  * que el aviso no caiga en otro buzón si el titular no está;
  * y que el tope por IP lo cuente el gateway, que es quien ve la IP.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import LimiteExcedido, NoAutenticado
from sqlalchemy import select
from starlette.testclient import TestClient

from services.orchestrator import aprobaciones as apr
from services.orchestrator import enlaces_publicos as enl
from services.orchestrator import organizacion as org

pytestmark = pytest.mark.db


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


@pytest.fixture
def gente(db: Any, tenant_id: UUID) -> dict[str, UUID]:
    """Comercial → jefe → director."""
    p = {n: uuid4() for n in ("comercial", "jefe", "director")}
    org.aplicar(
        db, tenant_id, {"user_id": str(p["director"]), "roles": ["direccion"], "activa": True}
    )
    org.aplicar(
        db,
        tenant_id,
        {
            "user_id": str(p["jefe"]),
            "roles": ["jefe"],
            "superior_id": str(p["director"]),
            "activa": True,
        },
    )
    org.aplicar(
        db,
        tenant_id,
        {
            "user_id": str(p["comercial"]),
            "roles": ["comercial"],
            "superior_id": str(p["jefe"]),
            "activa": True,
        },
    )
    return p


def _crear(uow: UnidadDeTrabajo, gente: dict[str, UUID], **kw: Any) -> apr.SolicitudAprobacion:
    base: dict[str, Any] = {
        "politica": "descuento",
        "objeto": "oportunidad",
        "objeto_id": uuid4(),
        "titulo": "Descuento del 22 % a Acme",
        "etapas": [{"origen": "jerarquia", "escalones": 1, "nombre": "Jefe"}],
        "contexto": {"descuento_pct": 22, "cuenta": "Acme"},
        "solicitante_id": gente["comercial"],
    }
    base.update(kw)
    return apr.crear(uow, **base)


def _enlaces_emitidos(uow: UnidadDeTrabajo) -> list[dict[str, Any]]:
    """Lo que llegó a la TABLA DE SALIDA, no lo que quedó en memoria."""
    from crmcore.bus.modelos import EventoSaliente

    uow.volcar()
    uow.db.flush()
    filas = (
        uow.db.execute(select(EventoSaliente).where(EventoSaliente.tipo == "approval.link.issued"))
        .scalars()
        .all()
    )
    return [f.sobre["data"] for f in filas]


def _token_de(cuerpo: str) -> str:
    linea = next(x for x in cuerpo.splitlines() if "/decidir?t=" in x)
    return linea.split("t=", 1)[1].strip()


@pytest.fixture
def publica(db: Any) -> Any:
    """El orquestador por HTTP y SIN cabeceras de identidad: como llega quien
    abre el correo."""
    import importlib
    import os

    from crmcore.config import get_settings

    previo = os.environ.get("OUTBOX_ENABLED")
    os.environ["OUTBOX_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        modulo = importlib.import_module("services.orchestrator.main")
        with TestClient(modulo.app) as cli:
            yield cli
    finally:
        if previo is None:
            os.environ.pop("OUTBOX_ENABLED", None)
        else:
            os.environ["OUTBOX_ENABLED"] = previo
        get_settings.cache_clear()


# ── El envío ──────────────────────────────────────────────────────────────


def test_al_abrirse_la_etapa_sale_un_correo_con_la_pagina_publica(
    uow: UnidadDeTrabajo, gente: dict[str, UUID]
) -> None:
    from crmcore.config import get_settings

    solicitud = _crear(uow, gente)
    emitidos = _enlaces_emitidos(uow)
    assert len(emitidos) == 1
    aviso = emitidos[0]
    assert aviso["titular_id"] == str(gente["jefe"])
    assert aviso["canales"] == ["correo"]
    assert aviso["objeto_id"] == str(solicitud.id)
    # La página del FRONT, no la API: un enlace a la API enseña un JSON.
    base = get_settings().front_base_url.rstrip("/")
    assert f"{base}/decidir?t=" in aviso["cuerpo"]
    assert "Acme" in aviso["cuerpo"]
    # En la base, sólo el hash.
    token = _token_de(aviso["cuerpo"])
    fila = uow.db.execute(select(apr.EnlaceDecision)).scalars().one()
    assert fila.hash_token != token and len(fila.hash_token) == 64


def test_la_siguiente_etapa_tambien_avisa(uow: UnidadDeTrabajo, gente: dict[str, UUID]) -> None:
    solicitud = _crear(
        uow,
        gente,
        etapas=[
            {"origen": "jerarquia", "escalones": 1, "nombre": "Jefe"},
            {"origen": "rol", "rol": "direccion", "nombre": "Dirección"},
        ],
    )
    apr.decidir(uow, solicitud.id, usuario_id=gente["jefe"], decision="aprobar")
    titulares = [e["titular_id"] for e in _enlaces_emitidos(uow)]
    assert titulares == [str(gente["jefe"]), str(gente["director"])]


def test_con_el_ajuste_apagado_no_sale_ninguno(
    uow: UnidadDeTrabajo, gente: dict[str, UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    from crmcore.config import get_settings

    monkeypatch.setattr(get_settings(), "aprobacion_enlace_por_correo", False)
    _crear(uow, gente)
    assert _enlaces_emitidos(uow) == []


def test_el_aviso_no_cae_en_otro_buzon_si_el_titular_no_esta(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Los demás avisos, sin destinatario, van a quien sigue el registro. Éste
    no: el enlace firma en nombre del titular."""
    from crmcore.datos.seguimiento import Notificacion, seguir

    from services.identity.modelos import Membresia, Usuario
    from services.identity.notificaciones import consumir_evento

    seguidor = Usuario(email="sigue@ejemplo.test", nombre="Sigue", activo=True)
    db.add(seguidor)
    db.flush()
    db.add(Membresia(tenant_id=tenant_id, usuario_id=seguidor.id, activa=True))
    solicitud_id = uuid4()
    seguir(
        db,
        tenant_id=tenant_id,
        usuario_id=seguidor.id,
        objeto_tipo="aprobacion",
        objeto_id=solicitud_id,
        motivo="manual",
    )
    db.commit()

    asyncio.run(
        consumir_evento(
            {
                "tipo": "approval.link.issued",
                "tenant_id": str(tenant_id),
                "data": {
                    "objeto_tipo": "aprobacion",
                    "objeto_id": str(solicitud_id),
                    # Un titular que no es de este tenant (o ya no está).
                    "titular_id": str(uuid4()),
                    "titulo": "Te toca decidir",
                    "cuerpo": "http://front/decidir?t=secreto",
                    "canales": ["correo"],
                },
            }
        )
    )
    db.expunge_all()
    assert db.query(Notificacion).filter_by(usuario_id=seguidor.id).count() == 0


def test_al_titular_le_llega_por_correo_aunque_lo_pida_el_mismo(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    from crmcore.datos.seguimiento import Notificacion

    from services.identity.modelos import Membresia, Usuario
    from services.identity.notificaciones import consumir_evento

    titular = Usuario(email="jefe@ejemplo.test", nombre="Jefe", activo=True)
    db.add(titular)
    db.flush()
    db.add(Membresia(tenant_id=tenant_id, usuario_id=titular.id, activa=True))
    db.commit()

    asyncio.run(
        consumir_evento(
            {
                "tipo": "approval.link.issued",
                "tenant_id": str(tenant_id),
                "data": {
                    "objeto_tipo": "aprobacion",
                    "objeto_id": str(uuid4()),
                    "titular_id": str(titular.id),
                    # Lo pidió él mismo desde la ficha: no se le excluye.
                    "actor_id": str(titular.id),
                    "titulo": "Te toca decidir",
                    "cuerpo": "http://front/decidir?t=secreto",
                    "canales": ["correo"],
                },
            }
        )
    )
    db.expunge_all()
    aviso = db.query(Notificacion).filter_by(usuario_id=titular.id).one()
    assert "correo" in aviso.canales


# ── La puerta pública ─────────────────────────────────────────────────────


def test_ver_sin_sesion_enseña_lo_justo_y_no_gasta_el_enlace(
    uow: UnidadDeTrabajo, gente: dict[str, UUID], publica: Any
) -> None:
    _crear(uow, gente)
    token = _token_de(_enlaces_emitidos(uow)[0]["cuerpo"])

    for _ in range(2):
        r = publica.post("/api/v1/enlace-de-aprobacion/ver", json={"token": token})
        assert r.status_code == 200, r.text
    datos = r.json()
    assert datos["titulo"] == "Descuento del 22 % a Acme"
    assert datos["etapa"] == "Jefe"
    assert datos["datos"] == {"descuento_pct": 22, "cuenta": "Acme"}
    # Ni lo interno, ni identificadores, ni quién más vota.
    texto = r.text
    assert "_solicitante_id" not in texto
    assert str(gente["jefe"]) not in texto and str(gente["comercial"]) not in texto
    assert set(datos) == {"titulo", "objeto", "etapa", "datos", "caduca_at", "decisiones"}


def test_decidir_sin_sesion_vota_como_el_titular_y_por_correo(
    uow: UnidadDeTrabajo, gente: dict[str, UUID], publica: Any
) -> None:
    solicitud = _crear(uow, gente)
    token = _token_de(_enlaces_emitidos(uow)[0]["cuerpo"])

    r = publica.post(
        "/api/v1/enlace-de-aprobacion/decidir",
        json={"token": token, "decision": "pedir_cambios", "comentario": "Baja al 15 %"},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"decision": "pedir_cambios", "estado": "cambios_pedidos"}

    voto = uow.db.execute(select(apr.DecisionAprobacion)).scalars().one()
    assert voto.via == "correo"
    assert voto.decidio_id == gente["jefe"] and voto.titular_id == gente["jefe"]
    assert voto.comentario == "Baja al 15 %"
    uow.db.refresh(solicitud)
    assert solicitud.estado == "cambios_pedidos"

    # Un solo uso: la segunda vez, el error de siempre.
    otra = publica.post(
        "/api/v1/enlace-de-aprobacion/decidir", json={"token": token, "decision": "aprobar"}
    )
    assert otra.status_code == 401


def test_inexistente_usado_y_caducado_responden_igual(
    uow: UnidadDeTrabajo, gente: dict[str, UUID], publica: Any
) -> None:
    _crear(uow, gente)
    token = _token_de(_enlaces_emitidos(uow)[0]["cuerpo"])
    fila = uow.db.execute(select(apr.EnlaceDecision)).scalars().one()
    fila.caduca_at = apr._ahora() - timedelta(minutes=1)
    uow.db.flush()

    caducado = publica.post("/api/v1/enlace-de-aprobacion/ver", json={"token": token})
    inventado = publica.post("/api/v1/enlace-de-aprobacion/ver", json={"token": "x" * 43})
    assert caducado.status_code == inventado.status_code == 401
    assert caducado.json()["error_code"] == inventado.json()["error_code"]
    assert caducado.json()["detail"] == inventado.json()["detail"]


def test_un_enlace_de_una_etapa_que_ya_no_se_vota_no_sirve(
    uow: UnidadDeTrabajo, gente: dict[str, UUID]
) -> None:
    """El jefe recibe el enlace de la primera etapa, decide desde el CRM, y el
    enlace sigue en su buzón. No puede servir para votar en la segunda."""
    solicitud = _crear(
        uow,
        gente,
        etapas=[
            {"origen": "jerarquia", "escalones": 1, "nombre": "Jefe"},
            {"origen": "usuario", "usuarios": [str(gente["jefe"])], "nombre": "Otra vez"},
        ],
    )
    token = _token_de(_enlaces_emitidos(uow)[0]["cuerpo"])
    apr.decidir(uow, solicitud.id, usuario_id=gente["jefe"], decision="aprobar")
    with pytest.raises(NoAutenticado):
        enl.ver(token)


def test_un_enlace_de_antes_de_reaprobar_no_firma_lo_nuevo(
    uow: UnidadDeTrabajo, gente: dict[str, UUID]
) -> None:
    solicitud = _crear(uow, gente, campos_vigilados=["descuento_pct"])
    viejo = _token_de(_enlaces_emitidos(uow)[0]["cuerpo"])
    apr.comprobar_vigencia(uow, solicitud.id, {"descuento_pct": 30, "cuenta": "Acme"})
    with pytest.raises(NoAutenticado):
        enl.ver(viejo)
    # El nuevo, el de la vuelta reabierta, sí.
    nuevo = _token_de(_enlaces_emitidos(uow)[-1]["cuerpo"])
    assert enl.ver(nuevo)["datos"]["descuento_pct"] == 30


def test_pedirlo_desde_la_ficha_devuelve_la_pagina_y_lo_manda(
    uow: UnidadDeTrabajo, gente: dict[str, UUID]
) -> None:
    from services.orchestrator.api_aprobaciones import PedirEnlace, pedir_enlace

    solicitud = _crear(uow, gente)
    _enlaces_emitidos(uow)

    class _Principal:
        tenant_id = uow.tenant_id

    salida = pedir_enlace(
        PedirEnlace(solicitud_id=solicitud.id, titular_id=gente["jefe"]),
        uow,
        _Principal(),  # type: ignore[arg-type]
    )
    assert salida["url"].endswith(salida["token"]) and "/decidir?t=" in salida["url"]
    assert salida["enviado_por_correo"] is True
    assert len(_enlaces_emitidos(uow)) == 2


# ── El tope por IP ────────────────────────────────────────────────────────


def test_la_ruta_publica_tiene_tope_y_lo_cuenta_el_gateway() -> None:
    from crmcore import rutas_de_api as rutas
    from crmcore.config import get_settings

    assert rutas.servicio_de("/api/v1/enlace-de-aprobacion/ver") == "orchestrator"
    prefijo, (limite, ventana) = next(
        (p, v)
        for p, v in rutas.TOPES_POR_IP.items()
        if "/api/v1/enlace-de-aprobacion/ver".startswith(p)
    )
    s = get_settings()
    assert int(getattr(s, limite)) > 0 and int(getattr(s, ventana)) > 0
    assert prefijo.endswith("/")


def test_pasado_el_tope_la_misma_ip_se_corta(monkeypatch: pytest.MonkeyPatch) -> None:
    from crmcore.config import get_settings
    from crmcore.http import rate_limit

    from services.gateway import api as gw

    rate_limit.limpiar_memoria()
    s = get_settings()
    monkeypatch.setattr(s, "aprobacion_enlace_intentos_por_ip", 3)

    async def _sin_redis() -> bool:
        return False

    monkeypatch.setattr(rate_limit, "_conectar_redis", _sin_redis)

    class _Peticion:
        headers: dict[str, str] = {}

        class client:  # noqa: N801 — imita a `request.client`
            host = "203.0.113.9"

    ruta = "/api/v1/enlace-de-aprobacion/ver"
    for _ in range(3):
        asyncio.run(gw._tope_por_ip(ruta, _Peticion()))  # type: ignore[arg-type]
    with pytest.raises(LimiteExcedido):
        asyncio.run(gw._tope_por_ip(ruta, _Peticion()))  # type: ignore[arg-type]
    # Otra ruta no cuenta contra éste.
    asyncio.run(gw._tope_por_ip("/api/v1/aprobaciones", _Peticion()))  # type: ignore[arg-type]
    rate_limit.limpiar_memoria()
