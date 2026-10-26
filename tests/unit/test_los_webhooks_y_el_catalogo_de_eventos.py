"""Auditoría de webhooks y catálogo de eventos (CRM-00.02.02).

Seis capacidades sin ninguna prueba que las nombre. Lo que un webhook tiene que
resistir es el día que el integrador no está mirando, así que lo que se
persigue aquí es cada forma de fallar en silencio:

  · suscribirse a un evento **que no existe** —no falla nunca, simplemente no
    llega nada, y el integrador pierde días buscando el fallo en su lado—;
  · una **firma sin su instante**, que es inverificable y llega al otro lado
    como «firma incorrecta»;
  · un **reenvío** de algo capturado hace un año, con su firma intacta;
  · un endpoint que lleva días cayéndose y **sigue recibiendo**;
  · un **catálogo** que no publica lo que un consumidor necesita para
    escribirse un cliente;
  · y un **replay** sin tope, que es una denegación de servicio autoinfligida
    y además al integrador.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator
from uuid import UUID, uuid4

import pytest
from starlette.testclient import TestClient

pytestmark = pytest.mark.db


@pytest.fixture
def cliente(db: Any) -> Iterator[Any]:
    import importlib
    import os

    from crmcore.config import get_settings

    previo = os.environ.get("OUTBOX_ENABLED")
    os.environ["OUTBOX_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        with TestClient(importlib.import_module("services.eventing.main").app) as cli:
            yield cli
    finally:
        if previo is None:
            os.environ.pop("OUTBOX_ENABLED", None)
        else:
            os.environ["OUTBOX_ENABLED"] = previo
        get_settings.cache_clear()


@pytest.fixture
def cabeceras(tenant_id: UUID) -> dict[str, str]:
    from crmcore.config import get_settings
    from crmcore.http.deps import (
        H_FACTOR_FUERTE,
        H_PERMISOS,
        H_ROLES,
        H_TENANT,
        H_USER,
        firmar_cabeceras_internas,
    )

    return firmar_cabeceras_internas(
        {
            H_TENANT: str(tenant_id),
            H_USER: str(uuid4()),
            H_PERMISOS: "*:*",
            H_ROLES: "admin",
            H_FACTOR_FUERTE: datetime.now(timezone.utc).isoformat(),
        },
        get_settings().secret_key.get_secret_value(),
    )


@pytest.fixture
def sin_resolver_dns(monkeypatch: Any) -> Iterator[list[str]]:
    """Desactiva **sólo** la comprobación de red del alta, y la deja a la vista.

    Al dar de alta un webhook se comprueba que la URL se pueda consultar desde
    el servidor y que no apunte a la red interna ni a los metadatos del
    proveedor de nube. Eso exige DNS, y una prueba que dependa del DNS falla en
    un portátil sin red por un motivo que no tiene nada que ver con lo que mide.

    Así que aquí se anota la llamada en vez de hacerla, y **se comprueba que se
    sigue haciendo** en `test_una_url_que_no_se_puede_consultar_se_rechaza`: sin
    eso, doblarla aquí escondería que alguien la quitara del alta.
    """
    from services.eventing import api as api_eventing

    vistas: list[str] = []
    monkeypatch.setattr(api_eventing, "exigir", lambda url: vistas.append(url))
    yield vistas


def _un_tipo_real() -> str:
    """Un tipo del catálogo de verdad. Escrito a mano se queda obsoleto."""
    from crmcore.events.catalogo import todos

    return sorted(t.tipo for t in todos())[0]


# ── CRM-00.02.02.01 · Suscripciones por tenant, con filtros ───────────────


def test_suscribirse_a_un_evento_que_no_existe_se_rechaza_crm_00_02_02_01(
    cliente: Any, cabeceras: dict[str, str], contexto_tenant: UUID
) -> None:
    """**No falla nunca**: simplemente no llega nada. El integrador pierde días
    buscando el fallo en su lado, y lo que hay es una errata en el tipo. Por eso
    se rechaza al dar de alta y se dice cuáles existen."""
    r = cliente.post(
        "/api/v1/webhooks",
        headers=cabeceras,
        json={
            "nombre": "el mío",
            "url": "https://ejemplo.invalid/webhook",
            "eventos": ["oportunidad.ganada"],  # el tipo real no se llama así
        },
    )
    assert r.status_code == 422, r.text
    assert "disponibles" in str(
        r.json()
    ), "rechaza y no dice cuáles valen: el integrador se queda igual"


def test_un_webhook_por_http_plano_no_se_admite_crm_00_02_02_01(
    cliente: Any, cabeceras: dict[str, str], contexto_tenant: UUID
) -> None:
    """Lleva datos de negocio firmados; por HTTP plano cualquiera en el camino
    los lee. Y se rechaza al configurarlo, no en un registro a las tres de la
    mañana."""
    r = cliente.post(
        "/api/v1/webhooks",
        headers=cabeceras,
        json={
            "nombre": "inseguro",
            "url": "http://ejemplo.invalid/webhook",
            "eventos": [_un_tipo_real()],
        },
    )
    assert r.status_code == 422, r.text


def test_el_secreto_se_devuelve_una_vez_y_solo_una_crm_00_02_02_01(
    cliente: Any, cabeceras: dict[str, str], sin_resolver_dns: Any, contexto_tenant: UUID
) -> None:
    """Es con lo que el integrador verifica la firma, así que tiene que verlo al
    crearla. Y no puede volver a salir en el listado: un secreto que se puede
    releer no es un secreto, es una contraseña guardada en claro."""
    creada = cliente.post(
        "/api/v1/webhooks",
        headers=cabeceras,
        json={
            "nombre": "el mío",
            "url": "https://ejemplo.invalid/webhook",
            "eventos": [_un_tipo_real()],
        },
    )
    assert creada.status_code == 201, creada.text
    secreto = creada.json()["secreto"]
    assert secreto

    listadas = cliente.get("/api/v1/webhooks", headers=cabeceras).json()["items"]
    assert listadas, listadas
    assert secreto not in str(listadas), "el secreto vuelve a salir en el listado"


def test_una_url_que_no_se_puede_consultar_se_rechaza_crm_00_02_02_01(
    cliente: Any, cabeceras: dict[str, str], contexto_tenant: UUID
) -> None:
    """La otra mitad del doble de arriba: **sin doblar nada**, el alta mira la
    URL de verdad. Un webhook a un host que no existe no falla al crearse y
    luego llena el registro de entregas fallidas; y uno a la red interna o a los
    metadatos del proveedor de nube es la vía clásica para que alguien se lleve
    las credenciales de la máquina."""
    r = cliente.post(
        "/api/v1/webhooks",
        headers=cabeceras,
        json={
            "nombre": "a ninguna parte",
            "url": "https://ejemplo.invalid/webhook",
            "eventos": [_un_tipo_real()],
        },
    )
    assert r.status_code == 422, r.text
    assert r.json()["error_code"] == "red.url_bloqueada", r.json()


def test_el_alta_sigue_comprobando_la_url_crm_00_02_02_01(
    cliente: Any, cabeceras: dict[str, str], sin_resolver_dns: list[str], contexto_tenant: UUID
) -> None:
    """Y que la comprobación se llama de verdad, para que doblarla en las demás
    pruebas no esconda que alguien la quite del alta."""
    cliente.post(
        "/api/v1/webhooks",
        headers=cabeceras,
        json={
            "nombre": "el mío",
            "url": "https://ejemplo.invalid/webhook",
            "eventos": [_un_tipo_real()],
        },
    )
    assert sin_resolver_dns == ["https://ejemplo.invalid/webhook"], sin_resolver_dns


# ── CRM-00.02.02.02 · Firma, instante y anti-replay ───────────────────────


def test_la_firma_lleva_el_instante_dentro_crm_00_02_02_02() -> None:
    """Sin el instante **dentro de la firma**, un mensaje capturado se reenvía
    tal cual dentro de un año con su firma intacta. Que viaje en una cabecera
    aparte no basta: tiene que entrar en el material firmado."""
    from crmcore.security.firma import firmar

    cuerpo = b'{"id":"1"}'
    ahora = int(time.time())
    assert firmar(cuerpo, "secreto", ahora) != firmar(cuerpo, "secreto", ahora + 1), (
        "el instante no entra en la firma: el mismo cuerpo firma igual siempre, "
        "así que un mensaje capturado vale para siempre"
    )


def test_un_mensaje_viejo_no_se_acepta_aunque_la_firma_sea_buena_crm_00_02_02_02() -> None:
    """Es el anti-replay. La ventana absorbe el desfase de reloj razonable entre
    dos máquinas y no más."""
    from crmcore.security.firma import firmar, verificar_firma

    cuerpo = b'{"id":"1"}'
    viejo = int(time.time()) - 3600
    firma = firmar(cuerpo, "secreto", viejo)
    assert verificar_firma(cuerpo, "secreto", firma, viejo) is False
    # Y dentro de la ventana, la misma firma vale.
    ahora = int(time.time())
    assert verificar_firma(cuerpo, "secreto", firmar(cuerpo, "secreto", ahora), ahora) is True


def test_la_ventana_la_pone_la_configuracion_crm_00_02_02_02() -> None:
    """Era una constante mientras el ajuste existía y estaba documentado como
    configurable: quien lo bajara para apretar el anti-replay cambiaba un número
    que no hacía nada. Un límite que nadie consulta no limita."""
    from crmcore.config import get_settings
    from crmcore.security.firma import ventana_por_defecto

    assert ventana_por_defecto() == int(get_settings().webhook_firma_ventana_s)


def test_las_cabeceras_firmadas_llevan_firma_y_momento_crm_00_02_02_02() -> None:
    """Una firma sin su instante es **inverificable**, y el fallo aparece en el
    lado del integrador como «firma incorrecta» — que manda a buscar al sitio
    equivocado."""
    from crmcore.security.firma import H_FIRMA, H_MOMENTO, cabeceras_firmadas, verificar_firma

    cuerpo = b'{"id":"1"}'
    cab = cabeceras_firmadas(cuerpo, "secreto")
    assert H_FIRMA in cab and H_MOMENTO in cab, sorted(cab)
    assert verificar_firma(cuerpo, "secreto", cab[H_FIRMA], int(cab[H_MOMENTO])) is True


# ── CRM-00.02.02.03 · Reintentos, DLQ y reenvío ───────────────────────────


def test_el_reintento_se_separa_cada_vez_mas_crm_00_02_02_03() -> None:
    """Reintentar cada segundo contra un endpoint caído es insistir en el peor
    momento: cuando el otro lado está intentando levantarse."""
    from crmcore.config import get_settings

    from services.eventing.entrega import _programar_reintento
    from services.eventing.modelos import Entrega, Suscripcion

    s = get_settings()
    suscripcion = Suscripcion(tenant_id=uuid4(), nombre="x", url="https://x.invalid", eventos=["a"])
    esperas = []
    for intento in (1, 2, 3, 4):
        registro = Entrega(tenant_id=suscripcion.tenant_id, suscripcion_id=suscripcion.id)
        _programar_reintento(registro, suscripcion, intento, s)
        esperas.append(registro.proximo_intento_at)

    diferencias = [(esperas[i + 1] - esperas[i]).total_seconds() for i in range(len(esperas) - 1)]
    assert all(
        b > a for a, b in zip(diferencias, diferencias[1:], strict=False)
    ), f"los reintentos no se separan: {diferencias}"


def test_un_endpoint_que_no_responde_se_desactiva_y_se_puede_reactivar_crm_00_02_02_03(
    cliente: Any, cabeceras: dict[str, str], db: Any, sin_resolver_dns: Any, contexto_tenant: UUID
) -> None:
    """Seguir mandando a un endpoint que lleva días caído gasta a los dos lados
    y esconde los que sí fallan hoy. Se desactiva, **se dice**, y se reactiva
    desde la consola cuando el integrador avisa de que ya está."""
    from sqlalchemy import select

    from services.eventing.modelos import Suscripcion

    creada = cliente.post(
        "/api/v1/webhooks",
        headers=cabeceras,
        json={
            "nombre": "el mío",
            "url": "https://ejemplo.invalid/webhook",
            "eventos": [_un_tipo_real()],
        },
    ).json()

    fila = db.execute(select(Suscripcion).where(Suscripcion.id == UUID(creada["id"]))).scalar_one()
    fila.activa = False
    fila.fallos_consecutivos = 20
    fila.desactivada_at = datetime.now(timezone.utc)
    db.flush()

    r = cliente.post(f"/api/v1/webhooks/{creada['id']}/reactivar", headers=cabeceras)
    assert r.status_code == 200, r.text
    assert r.json()["activa"] is True
    db.expire_all()
    vuelta = db.execute(
        select(Suscripcion).where(Suscripcion.id == UUID(creada["id"]))
    ).scalar_one()
    assert vuelta.fallos_consecutivos == 0, (
        "se reactiva con el contador de fallos puesto: se desactivaría otra vez "
        "al primer fallo, y parecería que la reactivación no funciona"
    )


# ── CRM-00.02.02.05 · Topic por tenant ────────────────────────────────────


def test_el_tenant_va_en_el_subject_y_el_patron_lo_respeta_crm_00_02_02_05() -> None:
    """El tenant va **en el subject**, no sólo en la carga: así un consumidor se
    puede suscribir a uno concreto y el transporte reparte por tenant, para que
    una avalancha de uno no bloquee la entrega de los demás.

    Y el patrón tiene que ser la hermana exacta: se publicaba en
    `prefijo.<tenant>.<tipo>` y se suscribía a `prefijo.<tipo>`, sin el segmento
    del tenant, así que **ningún subject casó nunca con ningún patrón** y el bus
    no entregó un solo evento entre servicios. No fallaba nada visible: publicar
    funcionaba y la tabla de salida se marcaba como publicada.
    """
    import re

    from crmcore.events.envelope import crear_evento, subject_patron

    tenant = uuid4()
    evento = crear_evento("account.created", tenant_id=tenant, subject=("cuenta", uuid4()), data={})
    publicado = evento.subject_bus("contecrm")
    assert publicado == f"contecrm.{tenant}.account.created"

    patron = subject_patron("contecrm", "account.created")
    # El comodín es de UN segmento: con `>` se tragaría también lo que viniera
    # detrás del tipo, y un `account.created.v2` acabaría en el consumidor de
    # `account.created`.
    assert ">" not in patron, patron
    casa = re.fullmatch(patron.replace(".", r"\.").replace("*", "[^.]+"), publicado)
    assert casa, f"«{publicado}» no casa con «{patron}»: el bus no entregaría nada"

    otro = crear_evento(
        "account.created.v2", tenant_id=tenant, subject=("cuenta", uuid4()), data={}
    ).subject_bus("contecrm")
    assert not re.fullmatch(
        patron.replace(".", r"\.").replace("*", "[^.]+"), otro
    ), "el patrón se traga lo que viene detrás del tipo"


# ── CRM-00.02.02.07 · Catálogo de eventos ─────────────────────────────────


def test_el_catalogo_dice_lo_que_hace_falta_para_consumirlo_crm_00_02_02_07(
    cliente: Any, cabeceras: dict[str, str], contexto_tenant: UUID
) -> None:
    """Un catálogo que solo lista nombres no sirve para escribir un cliente:
    hace falta saber **qué campos trae** cada evento y **de qué versión**, o el
    integrador acaba deduciéndolo de un ejemplo que le pasaron por correo."""
    r = cliente.get("/api/v1/eventos/catalogo", headers=cabeceras)
    assert r.status_code == 200, r.text
    tipos = r.json()
    assert len(tipos) >= 20, f"sólo se publican {len(tipos)} tipos"
    uno = tipos[0]
    for campo in ("tipo", "version", "descripcion", "campos"):
        assert campo in uno, f"falta «{campo}»: {sorted(uno)}"


def test_el_asyncapi_se_publica_y_es_navegable_crm_00_02_02_07(
    cliente: Any, cabeceras: dict[str, str], contexto_tenant: UUID
) -> None:
    """En el formato que las herramientas del integrador saben leer. Un
    catálogo propio obliga a cada uno a escribirse su propio lector."""
    r = cliente.get("/api/v1/eventos/asyncapi.json", headers=cabeceras)
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc.get("asyncapi"), sorted(doc)
    assert doc.get("channels"), "sin canales, el documento no describe nada"


# ── CRM-00.02.02.09 · Replay ──────────────────────────────────────────────


def test_el_replay_tiene_tope_y_rechaza_la_ventana_al_reves_crm_00_02_02_09(
    cliente: Any, cabeceras: dict[str, str], sin_resolver_dns: Any, contexto_tenant: UUID
) -> None:
    """Un replay de un año entero a un endpoint lento es una denegación de
    servicio autoinfligida, y además al integrador. Y una ventana al revés es
    una errata que devolvería cero sin decir por qué."""
    creada = cliente.post(
        "/api/v1/webhooks",
        headers=cabeceras,
        json={
            "nombre": "el mío",
            "url": "https://ejemplo.invalid/webhook",
            "eventos": [_un_tipo_real()],
        },
    ).json()

    ahora = datetime.now(timezone.utc)
    al_reves = cliente.post(
        f"/api/v1/webhooks/{creada['id']}/replay",
        headers=cabeceras,
        json={"desde": ahora.isoformat(), "hasta": (ahora - timedelta(days=1)).isoformat()},
    )
    assert al_reves.status_code == 422, al_reves.text

    bien = cliente.post(
        f"/api/v1/webhooks/{creada['id']}/replay",
        headers=cabeceras,
        json={"desde": (ahora - timedelta(days=1)).isoformat()},
    )
    assert bien.status_code == 200, bien.text
    assert bien.json()["tope"] == 5000, bien.json()


def test_el_replay_reencola_lo_archivado_y_no_lo_inventa_crm_00_02_02_09(
    cliente: Any,
    cabeceras: dict[str, str],
    db: Any,
    tenant_id: UUID,
    sin_resolver_dns: Any,
    contexto_tenant: UUID,
) -> None:
    """Reencola lo que está archivado, con su `dedup_key`: la deduplicación del
    otro lado evita que procese dos veces lo que sí recibió."""
    from crmcore.events.envelope import crear_evento

    from services.eventing.modelos import EventoArchivado

    creada = cliente.post(
        "/api/v1/webhooks",
        headers=cabeceras,
        json={
            "nombre": "el mío",
            "url": "https://ejemplo.invalid/webhook",
            "eventos": [_un_tipo_real()],
        },
    ).json()

    tipo = _un_tipo_real()
    evento = crear_evento(tipo, tenant_id=tenant_id, subject=("cosa", uuid4()), data={})
    db.add(
        EventoArchivado(
            tenant_id=tenant_id,
            tipo=tipo,
            dedup_key=evento.dedup_key,
            occurred_at=datetime.now(timezone.utc) - timedelta(hours=2),
            sobre=evento.a_dict(),
        )
    )
    db.flush()

    r = cliente.post(
        f"/api/v1/webhooks/{creada['id']}/replay",
        headers=cabeceras,
        json={"desde": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()},
    )
    assert r.status_code == 200, r.text
    assert r.json()["reencolados"] == 1, r.json()

    entregas = cliente.get(f"/api/v1/webhooks/{creada['id']}/entregas", headers=cabeceras).json()
    assert str(entregas), entregas
