"""La prioridad del caso es de la empresa, y responder un caso manda el correo.

Dos fricciones medidas el 10-11-2026 con las tareas del día (T08 y T09):

* **La prioridad era texto libre en el alta** —se tecleaba «alta»— y una lista
  cerrada del código en la edición. Ahora es el vocabulario `prioridades_caso`:
  el formulario la ofrece como lista, la empresa añade las suyas, el alta y la
  edición las validan contra lo que tenga la empresa, y el escalado sube por
  su orden.
* **Responder apuntaba y no mandaba.** Ahora `responder_caso` manda por el
  canal de la casa (marketing) y deja constancia salga o no; aquí el canal se
  sustituye en su puerta (`crmcore.http.interno.invocar`), que es por donde
  sale de verdad.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore import vocabulario as voc
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import ErrorValidacion

from services.service import operacion as ope
from services.service import servicio as svc
from services.service.modelos import VOCABULARIO_PRIORIDAD, EventoCaso
from services.service.operacion import ReglaEscalada

pytestmark = pytest.mark.db


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


def _urgente_encima(db: Any, tenant_id: UUID) -> None:
    """La empresa añade «Urgente» por encima de «Crítica»."""
    voc.materializar(db, VOCABULARIO_PRIORIDAD, tenant_id)
    db.add(
        voc.ValorVocabulario(
            tenant_id=tenant_id,
            vocabulario=VOCABULARIO_PRIORIDAD,
            valor="urgente",
            etiqueta="Urgente",
            orden=1000,
        )
    )
    db.flush()


# ── La prioridad ──────────────────────────────────────────────────────────


def test_de_fabrica_va_en_su_orden_y_con_su_rotulo(db: Any, contexto_tenant: UUID) -> None:
    """Es una escala: alfabéticamente sería alta, baja, crítica, media."""
    lista = voc.como_lista(db, VOCABULARIO_PRIORIDAD)
    assert [f["valor"] for f in lista] == ["baja", "media", "alta", "critica"]
    assert lista[3]["etiqueta"] == "Crítica"


def test_una_prioridad_de_la_empresa_vale_al_abrir_y_el_escalado_llega_a_ella(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    with pytest.raises(ErrorValidacion):
        svc.abrir_caso(uow, asunto="Antes de tenerla", prioridad="urgente")

    _urgente_encima(db, tenant_id)
    assert svc.abrir_caso(uow, asunto="Ya la tiene", prioridad="urgente").prioridad == "urgente"

    # «Subir prioridad» sube por la escala de la empresa: de crítica, a urgente.
    db.add(
        ReglaEscalada(tenant_id=tenant_id, nombre="sube", consumido_pct=50, subir_prioridad=True)
    )
    caso = svc.abrir_caso(uow, asunto="Va justo", prioridad="critica")
    ahora = datetime.now(timezone.utc)
    caso.created_at = ahora - timedelta(hours=9)
    caso.vence_resolucion_at = ahora + timedelta(hours=1)
    db.flush()
    ope.evaluar_escaladas(uow, tenant_id)
    assert caso.prioridad == "urgente"


def test_el_contrato_dice_de_que_vocabulario_sale() -> None:
    """Sin esto el formulario pinta una caja de texto: no sabe que es una lista."""
    from services.service.main import app

    esquemas = app.openapi()["components"]["schemas"]
    for nombre in ("AbrirCaso", "EditarCaso"):
        assert esquemas[nombre]["properties"]["prioridad"]["x-vocabulario"] == (
            "service/prioridades_caso"
        ), nombre


def test_editar_valida_contra_la_lista_de_la_empresa(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """La edición genérica validaba contra la tupla del código: una prioridad
    propia se podía poner al abrir y no al corregir."""
    import importlib
    import os

    from crmcore.config import get_settings
    from crmcore.http.deps import H_PERMISOS, H_TENANT, H_USER, firmar_cabeceras_internas
    from starlette.testclient import TestClient

    caso = svc.abrir_caso(uow, asunto="Para editar")
    db.flush()
    os.environ["OUTBOX_ENABLED"] = "false"
    get_settings.cache_clear()
    cabeceras = firmar_cabeceras_internas(
        {H_TENANT: str(tenant_id), H_USER: str(uuid4()), H_PERMISOS: "*:*"},
        get_settings().secret_key.get_secret_value(),
    )
    try:
        with TestClient(importlib.import_module("services.service.main").app) as cli:
            ruta = f"/api/v1/casos/{caso.id}"
            r = cli.patch(ruta, json={"prioridad": "urgente"}, headers=cabeceras)
            assert r.status_code == 422, r.text
            assert r.json()["error_code"] == "vocabulario.valor_no_valido"

            _urgente_encima(db, tenant_id)
            r = cli.patch(ruta, json={"prioridad": "urgente"}, headers=cabeceras)
            assert r.status_code == 200, r.text
    finally:
        os.environ.pop("OUTBOX_ENABLED", None)
        get_settings.cache_clear()


# ── Responder ─────────────────────────────────────────────────────────────


@pytest.fixture
def canal(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Clientes y marketing, sustituidos en la puerta por la que se les llama.

    `salida` es lo que contesta marketing al mandar; cada llamada queda en
    `llamadas` para ver qué se pidió.
    """
    import crmcore.http.interno as interno

    estado: dict[str, Any] = {
        "llamadas": [],
        "email_contacto": "cliente@example.com",
        "salida": {"enviado": True, "envio_id": "e-1", "motivo": "", "plantilla": "respuesta_caso"},
    }

    def falso(*, metodo: str, ruta: str, cuerpo: Any = None, **_: Any) -> dict[str, Any]:
        estado["llamadas"].append((metodo, ruta, cuerpo))
        if ruta.startswith("/api/v1/contacts/"):
            return {"ok": True, "estado": 200, "datos": {"email": estado["email_contacto"]}}
        if ruta == "/api/v1/correo/enviar":
            return {"ok": True, "estado": 200, "datos": dict(estado["salida"])}
        if ruta == "/api/v1/activities":
            return {"ok": True, "estado": 201, "datos": {"id": "a-1"}}
        raise AssertionError(f"llamada inesperada: {metodo} {ruta}")

    monkeypatch.setattr(interno, "invocar", falso)
    return estado


def _cuerpo(canal: dict[str, Any], ruta: str) -> dict[str, Any]:
    return next(c for _, r, c in canal["llamadas"] if r == ruta)


def test_responder_manda_al_contacto_y_cuenta_como_primera_respuesta(
    db: Any, contexto_tenant: UUID, uow: Any, canal: dict[str, Any]
) -> None:
    caso = svc.abrir_caso(uow, asunto="Ruido en el motor", contacto_id=uuid4())
    salida = svc.responder_caso(uow, caso.id, mensaje="Cambiamos el rodamiento.")

    assert salida["enviado"] is True and salida["para"] == "cliente@example.com"
    assert salida["asunto"] == f"Re: Ruido en el motor [{caso.codigo}]"
    correo = _cuerpo(canal, "/api/v1/correo/enviar")
    assert correo["plantilla"] == "respuesta_caso" and correo["objeto_id"] == str(caso.id)
    actividad = _cuerpo(canal, "/api/v1/activities")
    assert actividad["tipo"] == "email" and actividad["objeto"] == "caso"
    assert actividad["detalles"]["enviado"] is True
    assert caso.primera_respuesta_at is not None
    evento = db.query(EventoCaso).filter_by(caso_id=caso.id, tipo="respuesta").one()
    assert evento.detalle["enviado"] is True and evento.detalle["actividad_id"] == "a-1"


def test_lo_que_no_sale_consta_como_no_salido(
    db: Any, contexto_tenant: UUID, uow: Any, canal: dict[str, Any]
) -> None:
    """Sin remitente o sin servidor no sale: se apunta igual, se dice por qué y
    no cuenta como respuesta al cliente, porque no le ha llegado."""
    canal["salida"] = {"enviado": False, "envio_id": "e-2", "motivo": "No hay remitente."}
    caso = svc.abrir_caso(uow, asunto="Etiqueta mal impresa")
    salida = svc.responder_caso(uow, caso.id, mensaje="Lo miramos.", para="otra@example.com")

    assert salida["enviado"] is False and "remitente" in salida["motivo"]
    assert _cuerpo(canal, "/api/v1/activities")["asunto"].startswith("No ha salido:")
    assert caso.primera_respuesta_at is None
    evento = db.query(EventoCaso).filter_by(caso_id=caso.id, tipo="respuesta").one()
    assert evento.detalle["enviado"] is False


def test_sin_a_quien_mandarla_lo_dice_antes_de_mandar_nada(
    db: Any, contexto_tenant: UUID, uow: Any, canal: dict[str, Any]
) -> None:
    caso = svc.abrir_caso(uow, asunto="Sin contacto")
    with pytest.raises(ErrorValidacion) as exc:
        svc.responder_caso(uow, caso.id, mensaje="Hola")
    assert exc.value.error_code == "service.respuesta_sin_destinatario"
    assert canal["llamadas"] == []
