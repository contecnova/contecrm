"""Auditoría del chat interno (CRM-06.02.02), recorriendo sus rutas.

Nueve capacidades declaradas hechas, ninguna con nota de auditoría y ninguna
citada por una prueba. Se recorrieron una a una el 26-10-2026 por HTTP, que es
donde se rompen estas cosas —en la serialización— y es lo que lee el navegador.

Ocho estaban. La novena, la papelera, **no existía**: el modelo del mensaje
llevaba las columnas de borrado desde el principio y su propio comentario
apuntaba a la capacidad, pero

  · no había ninguna ruta que borrara un mensaje,
  · ninguna que lo recuperara,
  · `identity` no declaraba **ninguna** clase de retención ni publicaba el
    router de retención, así que nada de lo suyo caducaba nunca,
  · y las tablas de política y de bloqueo legal ya estaban creadas en su
    esquema, esperando desde siempre a que alguien las usara.

Escrito y sin enchufar, y contado como hecho. Lo que se construyó para cerrarlo
está aquí recorrido: borrar deja **lápida** —el cuerpo y los adjuntos se van, el
hueco en el hilo se queda—, el histórico de ediciones de un borrado no se
enseña, la búsqueda no lo encuentra, y la retención lo purga con el plazo que
fije la empresa y consultando los bloqueos legales.
"""

from __future__ import annotations

from datetime import datetime, timezone
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
        with TestClient(importlib.import_module("services.identity.main").app) as cli:
            yield cli
    finally:
        if previo is None:
            os.environ.pop("OUTBOX_ENABLED", None)
        else:
            os.environ["OUTBOX_ENABLED"] = previo
        get_settings.cache_clear()


def _cabeceras(tenant_id: UUID, usuario: UUID) -> dict[str, str]:
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
            H_USER: str(usuario),
            H_PERMISOS: "*:*",
            H_ROLES: "admin",
            H_FACTOR_FUERTE: datetime.now(timezone.utc).isoformat(),
        },
        get_settings().secret_key.get_secret_value(),
    )


@pytest.fixture
def ana() -> UUID:
    return uuid4()


@pytest.fixture
def luis() -> UUID:
    return uuid4()


@pytest.fixture
def de_ana(tenant_id: UUID, ana: UUID) -> dict[str, str]:
    return _cabeceras(tenant_id, ana)


@pytest.fixture
def de_luis(tenant_id: UUID, luis: UUID) -> dict[str, str]:
    return _cabeceras(tenant_id, luis)


@pytest.fixture
def canal(cliente: Any, de_ana: dict[str, str], luis: UUID, contexto_tenant: UUID) -> str:
    """Un canal con Ana y Luis dentro."""
    r = cliente.post(
        "/api/v1/chat/conversaciones",
        headers=de_ana,
        json={"tipo": "canal", "clave": "ventas", "nombre": "Ventas", "miembros": [str(luis)]},
    )
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


def _escribir(
    cliente: Any, cabeceras: dict[str, str], canal: str, cuerpo: str, **extra: Any
) -> dict:
    r = cliente.post(
        f"/api/v1/chat/conversaciones/{canal}/mensajes",
        headers=cabeceras,
        json={"cuerpo": cuerpo, **extra},
    )
    assert r.status_code == 201, r.text
    return dict(r.json())


# ── CRM-06.02.02.01 · Canales, grupos y directos ──────────────────────────


def test_los_tres_tipos_de_conversacion_crm_06_02_02_01(
    cliente: Any, de_ana: dict[str, str], luis: UUID, contexto_tenant: UUID
) -> None:
    """Y el directo **no se crea dos veces**: quien escribe a alguien con quien
    ya habló espera seguir la misma conversación, no abrir una vacía al lado de
    la que tiene el histórico."""
    canal = cliente.post(
        "/api/v1/chat/conversaciones",
        headers=de_ana,
        json={"tipo": "canal", "clave": "general", "nombre": "General"},
    )
    grupo = cliente.post(
        "/api/v1/chat/conversaciones",
        headers=de_ana,
        json={"tipo": "grupo", "nombre": "Oferta Acme", "miembros": [str(luis)]},
    )
    uno = cliente.post(
        "/api/v1/chat/conversaciones",
        headers=de_ana,
        json={"tipo": "directo", "miembros": [str(luis)]},
    )
    otro = cliente.post(
        "/api/v1/chat/conversaciones",
        headers=de_ana,
        json={"tipo": "directo", "miembros": [str(luis)]},
    )
    for r in (canal, grupo, uno, otro):
        assert r.status_code == 201, r.text
    assert uno.json()["id"] == otro.json()["id"], (
        "se ha abierto un segundo directo con la misma persona: así es como se "
        "acaban teniendo tres conversaciones con alguien y el histórico repartido"
    )

    inventado = cliente.post(
        "/api/v1/chat/conversaciones", headers=de_ana, json={"tipo": "megafono"}
    )
    assert inventado.status_code == 422, inventado.text


def test_un_canal_privado_no_sale_en_la_lista_de_quien_no_esta_crm_06_02_02_01(
    cliente: Any, de_ana: dict[str, str], de_luis: dict[str, str], contexto_tenant: UUID
) -> None:
    """**El nombre de un canal ya es información.** Un listado de todas las
    conversaciones del tenant enseñaría «due-diligence» o «salida-de-javier» a
    quien no está dentro."""
    cliente.post(
        "/api/v1/chat/conversaciones",
        headers=de_ana,
        json={
            "tipo": "canal",
            "clave": "due-diligence",
            "nombre": "Due diligence",
            "privada": True,
        },
    )
    mias = cliente.get("/api/v1/chat/conversaciones", headers=de_ana).json()
    suyas = cliente.get("/api/v1/chat/conversaciones", headers=de_luis).json()
    assert [c["clave"] for c in mias] == ["due-diligence"]
    assert suyas == [], "el canal de otro sale en la lista de quien no está dentro"


# ── CRM-06.02.02.02 · Colgada de un registro ──────────────────────────────


def test_la_conversacion_de_un_registro_se_abre_desde_su_ficha_crm_06_02_02_02(
    cliente: Any, de_ana: dict[str, str], contexto_tenant: UUID
) -> None:
    """Hablar de ESTA oportunidad sin pegar enlaces y sin cambiar de
    aplicación, que es justo donde se pierde el contexto. Y pedirla dos veces
    devuelve la misma: si no, cada visita a la ficha abriría una nueva."""
    oportunidad = uuid4()
    uno = cliente.get(f"/api/v1/chat/conversaciones/de/oportunidad/{oportunidad}", headers=de_ana)
    assert uno.status_code == 200, uno.text
    assert uno.json()["objeto_tipo"] == "oportunidad"
    assert uno.json()["objeto_id"] == str(oportunidad)

    otra = cliente.get(f"/api/v1/chat/conversaciones/de/oportunidad/{oportunidad}", headers=de_ana)
    assert otra.json()["id"] == uno.json()["id"]

    # Y quien la abre entra: abrirla y no poder leerla sería el fallo más tonto.
    assert (
        cliente.get(f"/api/v1/chat/conversaciones/{uno.json()['id']}", headers=de_ana).status_code
        == 200
    )


# ── CRM-06.02.02.03 · Hilos, reacciones y edición con historial ───────────


def test_un_hilo_cuelga_de_su_mensaje_crm_06_02_02_03(
    cliente: Any, de_ana: dict[str, str], canal: str
) -> None:
    """Hilos de verdad y no «citas»: con dos temas a la vez, una conversación
    plana es ilegible."""
    padre = _escribir(cliente, de_ana, canal, "¿Bajamos el precio de Acme?")
    hija = _escribir(cliente, de_ana, canal, "Yo lo veo", responde_a_id=padre["id"])
    assert hija["responde_a_id"] == padre["id"]


def test_la_reaccion_es_un_interruptor_crm_06_02_02_03(
    cliente: Any, de_ana: dict[str, str], canal: str
) -> None:
    """Pulsar dos veces el mismo emoji lo quita, que es lo que espera
    cualquiera que haya usado un chat. Y la lista de emojis es cerrada."""
    mensaje = _escribir(cliente, de_ana, canal, "Cerrado")
    ruta = f"/api/v1/chat/mensajes/{mensaje['id']}/reacciones"
    assert cliente.post(ruta, headers=de_ana, json={"emoji": "🎉"}).json()["puesta"] is True
    assert cliente.post(ruta, headers=de_ana, json={"emoji": "🎉"}).json()["puesta"] is False
    assert cliente.post(ruta, headers=de_ana, json={"emoji": "💩"}).status_code == 422


def test_lo_corregido_se_ve_corregido_y_no_reescrito_crm_06_02_02_03(
    cliente: Any, de_ana: dict[str, str], de_luis: dict[str, str], canal: str
) -> None:
    """En una conversación donde se decide algo, saber qué decía antes es justo
    lo que hace falta cuando alguien lo discute. Y **no lo edita un tercero**:
    que un administrador pueda reescribir lo que dijo otro convierte el
    histórico en algo que no se puede citar, y la única razón de tenerlo es
    poder citarlo."""
    mensaje = _escribir(cliente, de_ana, canal, "Le damos un 30 %")
    editado = cliente.patch(
        f"/api/v1/chat/mensajes/{mensaje['id']}",
        headers=de_ana,
        json={"cuerpo": "Le damos un 13 %"},
    )
    assert editado.status_code == 200, editado.text
    assert editado.json()["ediciones"] == 1 and editado.json()["editado_at"]

    versiones = cliente.get(
        f"/api/v1/chat/mensajes/{mensaje['id']}/versiones", headers=de_luis
    ).json()
    assert versiones and versiones[0]["cuerpo"] == "Le damos un 30 %"

    ajena = cliente.patch(
        f"/api/v1/chat/mensajes/{mensaje['id']}", headers=de_luis, json={"cuerpo": "Un 50 %"}
    )
    assert ajena.status_code == 403, ajena.text


# ── CRM-06.02.02.04 · Menciones ───────────────────────────────────────────


def test_una_mencion_viaja_con_el_mensaje_crm_06_02_02_04(
    cliente: Any, de_ana: dict[str, str], canal: str, luis: UUID
) -> None:
    """Avisan por el mismo camino que el resto, así que lo que esta ruta tiene
    que garantizar es que a quién se menciona **llega y se guarda**: sin eso no
    hay a quién avisar."""
    mensaje = _escribir(cliente, de_ana, canal, "@luis mira esto", menciones=[str(luis)])
    assert mensaje["menciones"] == [str(luis)]


# ── CRM-06.02.02.05 · Leídos y no leídos ──────────────────────────────────


def test_los_no_leidos_son_por_persona_crm_06_02_02_05(
    cliente: Any, de_ana: dict[str, str], de_luis: dict[str, str], canal: str
) -> None:
    """Por persona y no por conversación: un contador compartido diría que está
    todo leído porque lo leyó otro."""
    _escribir(cliente, de_ana, canal, "uno")
    _escribir(cliente, de_ana, canal, "dos")

    de_el = cliente.get("/api/v1/chat/sin-leer", headers=de_luis).json()
    assert de_el["mensajes"] >= 2, de_el
    assert de_el["conversaciones"] == 1, de_el

    cliente.post(f"/api/v1/chat/conversaciones/{canal}/leido", headers=de_luis)
    assert cliente.get("/api/v1/chat/sin-leer", headers=de_luis).json()["mensajes"] == 0

    # Y la marca de Luis no ha movido la de Ana.
    lista = cliente.get("/api/v1/chat/conversaciones", headers=de_luis).json()
    assert lista[0]["sin_leer"] == 0


# ── CRM-06.02.02.06 · Presencia ───────────────────────────────────────────


def test_la_presencia_dice_si_esperar_o_llamar_crm_06_02_02_06(
    cliente: Any, de_ana: dict[str, str], contexto_tenant: UUID
) -> None:
    """«En un cliente hasta las 5» responde a la pregunta real, que no es si
    está conectado sino si merece la pena esperar. Y `visto_at` es lo que
    distingue «ausente» de «lleva tres días sin aparecer»."""
    puesto = cliente.put(
        "/api/v1/chat/presencia",
        headers=de_ana,
        json={"estado": "ocupado", "mensaje": "En un cliente hasta las 5"},
    )
    assert puesto.status_code == 200, puesto.text

    filas = cliente.get("/api/v1/chat/presencia", headers=de_ana).json()
    assert filas and filas[0]["estado"] == "ocupado"
    assert filas[0]["mensaje"] == "En un cliente hasta las 5"
    assert filas[0]["visto_at"]

    inventado = cliente.put("/api/v1/chat/presencia", headers=de_ana, json={"estado": "de_fiesta"})
    assert inventado.status_code == 422


# ── CRM-06.02.02.07 · Entrega en vivo ─────────────────────────────────────


def test_el_flujo_en_vivo_se_anuncia_como_flujo_crm_06_02_02_07(cliente: Any) -> None:
    """El contrato tiene que decir que esto es un flujo y no una respuesta JSON
    corriente. Cuando no lo decía, cualquiera que lea el contrato —un cliente
    generado, un catálogo de API, un barrido de rutas— la pedía como una más y
    se quedaba esperando para siempre a algo que no termina por diseño. Ha
    colgado dos barridos aquí."""
    contrato = cliente.get("/api/v1/openapi.json").json()
    operacion = contrato["paths"]["/api/v1/chat/eventos"]["get"]
    tipos = set(operacion["responses"]["200"]["content"])
    assert "text/event-stream" in tipos, (
        f"el contrato anuncia {sorted(tipos)}: quien lo lea pedirá un JSON y se "
        "quedará esperando a que termine un flujo que no termina"
    )


def test_lo_escrito_mientras_no_habia_conexion_llega_al_volver_crm_06_02_02_07(
    db: Any,
    de_luis: dict[str, str],
    cliente: Any,
    canal: str,
    tenant_id: UUID,
    ana: UUID,
    contexto_tenant: UUID,
) -> None:
    """La mitad que faltaba de «reconexión Y recuperación por cursor».

    La reconexión la hace el navegador solo, y eso ya funcionaba. Lo que no
    había era la recuperación: el flujo arrancaba en `now()`, así que todo lo
    escrito mientras el portátil tenía la tapa cerrada **no llegaba nunca**. No
    falla y no avisa: a la conversación le faltan mensajes y quien mira cree
    que nadie ha escrito.

    **La prueba es el contraste, y lleva el caso malo dentro**: con el cursor
    que devuelve el navegador llega lo que se perdió; sin él —que es lo que
    pasaba siempre— no llega nada. Afirmar sólo lo primero no distinguiría
    entre honrar el cursor y mandarlo todo siempre.

    **Por qué se tira del generador y no se abre el flujo con el cliente.** Este
    endpoint hace `db.rollback()` entre vueltas —a propósito: mantener la
    sesión abierta reservaría una conexión de Postgres por persona conectada—,
    y dentro de la transacción de una prueba ese rollback se lleva por delante
    el escenario. Abrirlo con `TestClient` deja la prueba esperando para
    siempre a unos mensajes que acaba de borrar ella misma. Se pide la primera
    tanda, que es anterior al primer rollback, y con plazo duro: este flujo ya
    ha colgado dos barridos de este repositorio.
    """
    import asyncio
    from datetime import timedelta

    from services.identity.api_chat import eventos

    primero = _escribir(cliente, de_luis, canal, "antes del corte")
    _escribir(cliente, de_luis, canal, "esto se escribió con la tapa cerrada")

    # Un instante ANTES de los dos. No se usa el `created_at` del primero
    # porque dentro de una transacción `now()` de Postgres es el mismo para
    # todas las filas: los dos mensajes comparten marca y `> corte` los
    # dejaría a ambos fuera por un detalle del entorno de pruebas, no del
    # código.
    corte = (datetime.fromisoformat(primero["created_at"]) - timedelta(seconds=5)).isoformat()

    de_quien = tenant_id

    class _Ana:
        id = ana
        tenant_id = de_quien

    async def primeros_trozos(last_event_id: str | None, cuantos: int) -> str:
        respuesta = await eventos(
            db=db,
            principal=_Ana(),
            desde=None,
            last_event_id=last_event_id,
            espera_s=0.5,
        )
        texto = ""
        it = respuesta.body_iterator.__aiter__()
        for _ in range(cuantos):
            texto += await asyncio.wait_for(it.__anext__(), timeout=4)
        return texto

    # CON el cursor que manda el navegador: llega lo del corte.
    # Cuatro trozos: el `retry`, el saludo y **un trozo por mensaje**. Con tres
    # sólo llegaba el primero de los dos y la prueba fallaba por contar mal, no
    # por el código.
    con_cursor = asyncio.run(asyncio.wait_for(primeros_trozos(corte, 4), timeout=20))
    assert "esto se escribió con la tapa cerrada" in con_cursor, (
        "lo escrito durante el corte no ha llegado al reconectar: el cursor de "
        "`Last-Event-ID` no se honra y la conversación pierde mensajes sin "
        "decirlo.\nRecibido:\n" + con_cursor[:600]
    )
    # Y el id viaja, que es lo que hace posible la vuelta siguiente.
    assert "id: " in con_cursor, (
        "los eventos no llevan `id`, así que el navegador no tiene qué devolver "
        "en `Last-Event-ID` y la próxima reconexión vuelve a perder lo del corte"
    )

    # SIN cursor: el comportamiento de antes. Los dos primeros trozos son el
    # `retry` y el saludo; el tercero no llega porque no hay nada nuevo desde
    # «ahora», y eso es exactamente lo que se perdía.
    async def sin_cursor() -> bool:
        respuesta = await eventos(
            db=db, principal=_Ana(), desde=None, last_event_id=None, espera_s=0.5
        )
        it = respuesta.body_iterator.__aiter__()
        texto = ""
        for _ in range(2):
            texto += await it.__anext__()
        assert "event: mensaje" not in texto, texto
        try:
            await asyncio.wait_for(it.__anext__(), timeout=2)
        except TimeoutError:
            return True
        return False

    assert asyncio.run(asyncio.wait_for(sin_cursor(), timeout=20)), (
        "sin cursor ha llegado algo: entonces el flujo manda lo viejo siempre y "
        "la prueba de arriba no distinguiría entre honrar el cursor y no acotar"
    )


def test_un_last_event_id_ilegible_no_tumba_el_flujo_crm_06_02_02_07() -> None:
    """Un cursor corrupto se ignora, no revienta.

    Es lo que llega de un cliente viejo, de una caché rara o de un intermediario
    que toca cabeceras. Tumbar el flujo ahí sería dejar sin chat justo a quien
    está volviendo, que es cuando más se nota.
    """
    from services.identity.api_chat import _desde_cabecera

    assert _desde_cabecera(None) is None
    assert _desde_cabecera("") is None
    assert _desde_cabecera("no-es-una-fecha") is None
    # Y uno bueno se lee, con su zona. Sin zona se asume UTC: compararlo con un
    # instante con zona reventaría la consulta justo en la reconexión.
    leido = _desde_cabecera("2026-10-29T10:00:00+00:00")
    assert leido is not None and leido.tzinfo is not None
    ingenuo = _desde_cabecera("2026-10-29T10:00:00")
    assert ingenuo is not None and ingenuo.tzinfo is not None


# ── CRM-06.02.02.08 · Búsqueda solo en lo mío ─────────────────────────────


def test_la_busqueda_no_entra_donde_no_estoy_crm_06_02_02_08(
    cliente: Any, de_ana: dict[str, str], de_luis: dict[str, str], contexto_tenant: UUID
) -> None:
    """Buscar en todas encontraría texto de canales en los que no se está: una
    fuga por la puerta de atrás, y de las que no dejan rastro."""
    suyo = cliente.post(
        "/api/v1/chat/conversaciones",
        headers=de_ana,
        json={"tipo": "canal", "clave": "direccion", "nombre": "Dirección"},
    ).json()["id"]
    _escribir(cliente, de_ana, suyo, "El EBITDA del trimestre es 1,2 M")

    mio = cliente.get("/api/v1/chat/buscar?texto=EBITDA", headers=de_ana).json()
    ajeno = cliente.get("/api/v1/chat/buscar?texto=EBITDA", headers=de_luis).json()
    assert len(mio) == 1 and "EBITDA" in mio[0]["cuerpo"]
    assert ajeno == [], "la búsqueda ha entrado en un canal en el que no se está"


# ── CRM-06.02.02.09 · Papelera y retención ────────────────────────────────


def test_un_mensaje_borrado_deja_lapida_crm_06_02_02_09(
    cliente: Any, de_ana: dict[str, str], canal: str
) -> None:
    """**La capacidad que no existía.** Y la decisión al construirla: no
    desaparece del hilo. Un mensaje que se esfuma deja las respuestas colgando
    de nada y quien lee la conversación una semana después no entiende el hilo
    ni sabe que falta algo. Lo que se va es el cuerpo, que es lo que se quería
    quitar."""
    uno = _escribir(cliente, de_ana, canal, "AKIA...clave que no debía estar aquí")
    _escribir(cliente, de_ana, canal, "Ya la he rotado", responde_a_id=uno["id"])

    borrado = cliente.delete(f"/api/v1/chat/mensajes/{uno['id']}", headers=de_ana)
    assert borrado.status_code == 200, borrado.text
    assert borrado.json()["borrado"] is True
    assert borrado.json()["cuerpo"] == ""

    hilo = cliente.get(f"/api/v1/chat/conversaciones/{canal}/mensajes", headers=de_ana).json()
    assert len(hilo) == 2, "el mensaje ha desaparecido del hilo y la respuesta cuelga de nada"
    primero = next(m for m in hilo if m["id"] == uno["id"])
    assert primero["borrado"] is True and primero["cuerpo"] == ""
    assert primero["borrado_at"]


def test_lo_borrado_no_se_busca_ni_se_lee_en_el_historico_crm_06_02_02_09(
    cliente: Any, de_ana: dict[str, str], de_luis: dict[str, str], canal: str
) -> None:
    """Las dos puertas de atrás. Si la búsqueda lo encuentra por su texto, o si
    el histórico de ediciones lo enseña, la papelera no sirve de nada justo en
    el caso que la justifica."""
    mensaje = _escribir(cliente, de_ana, canal, "El móvil de Ana es 600112233")
    cliente.patch(
        f"/api/v1/chat/mensajes/{mensaje['id']}",
        headers=de_ana,
        json={"cuerpo": "El móvil de Ana es 600112233 (corrijo: 600112244)"},
    )
    cliente.delete(f"/api/v1/chat/mensajes/{mensaje['id']}", headers=de_ana)

    assert cliente.get("/api/v1/chat/buscar?texto=600112233", headers=de_ana).json() == []
    versiones = cliente.get(
        f"/api/v1/chat/mensajes/{mensaje['id']}/versiones", headers=de_luis
    ).json()
    assert versiones == [], "el texto anterior de un mensaje borrado sigue a un clic"


def test_un_borrado_por_error_se_deshace_crm_06_02_02_09(
    cliente: Any, de_ana: dict[str, str], canal: str
) -> None:
    """Es la diferencia entre una papelera y un borrado."""
    mensaje = _escribir(cliente, de_ana, canal, "Confirmado con el cliente")
    cliente.delete(f"/api/v1/chat/mensajes/{mensaje['id']}", headers=de_ana)
    vuelto = cliente.post(f"/api/v1/chat/mensajes/{mensaje['id']}/recuperar", headers=de_ana)
    assert vuelto.status_code == 200, vuelto.text
    assert vuelto.json()["borrado"] is False
    assert vuelto.json()["cuerpo"] == "Confirmado con el cliente"
    assert cliente.get("/api/v1/chat/buscar?texto=Confirmado", headers=de_ana).json()


def test_nadie_borra_el_mensaje_de_otro_crm_06_02_02_09(
    cliente: Any, de_ana: dict[str, str], de_luis: dict[str, str], canal: str
) -> None:
    """Lo borra quien lo escribió o quien administra la conversación. Luis está
    dentro del canal y no lo creó, así que no es ni una cosa ni la otra."""
    mensaje = _escribir(cliente, de_ana, canal, "Lo mío")
    ajeno = cliente.delete(f"/api/v1/chat/mensajes/{mensaje['id']}", headers=de_luis)
    assert ajeno.status_code == 403, ajeno.text


def test_borrar_dos_veces_no_pisa_quien_lo_borro_crm_06_02_02_09(
    cliente: Any, de_ana: dict[str, str], canal: str
) -> None:
    """Pedir dos veces lo mismo da lo mismo. Lo que no puede es mover la fecha,
    que es desde donde cuenta el plazo de la papelera: cada repetición alejaría
    la purga y el mensaje se quedaría ahí para siempre."""
    mensaje = _escribir(cliente, de_ana, canal, "uno")
    primera = cliente.delete(f"/api/v1/chat/mensajes/{mensaje['id']}", headers=de_ana).json()
    segunda = cliente.delete(f"/api/v1/chat/mensajes/{mensaje['id']}", headers=de_ana).json()
    # El INSTANTE, no la cadena: la primera respuesta sale del objeto en sesión
    # y la segunda de la fila releída, así que el mismo momento puede venir con
    # el desfase local en una y en UTC en la otra. Las dos son correctas y
    # comparar texto daría un falso rojo.
    assert datetime.fromisoformat(primera["borrado_at"]) == datetime.fromisoformat(
        segunda["borrado_at"]
    )


def test_la_papelera_del_chat_tiene_quien_la_vacie_crm_06_02_02_09(
    cliente: Any, de_ana: dict[str, str], contexto_tenant: UUID
) -> None:
    """**La otra mitad del agujero.** `identity` no declaraba ninguna clase de
    retención ni publicaba el router, así que nada de lo suyo caducaba nunca:
    una papelera que guarda para siempre no es una papelera.

    Las tablas de política y de bloqueo legal ya estaban creadas en su esquema
    desde siempre, esperando a que alguien las usara.
    """
    r = cliente.get("/api/v1/identity/retencion/clases", headers=de_ana)
    assert r.status_code == 200, r.text
    clases = {c["clave"]: c for c in r.json()}
    assert "chat_mensajes_borrados" in clases, sorted(clases)

    clase = clases["chat_mensajes_borrados"]
    # Desde que se BORRÓ, no desde que se escribió: contando desde la creación,
    # borrar hoy un mensaje del año pasado lo purgaría en la siguiente pasada y
    # la papelera no serviría para deshacer nada.
    assert clase["desde"] == "deleted_at"
    # Cero: el plazo lo decide el tenant, que es quien conoce su obligación.
    # Acertar por él sería destruir datos de alguien con una suposición.
    assert clase["dias_defecto"] == 0


def test_el_plazo_lo_fija_la_empresa_y_se_purga_de_verdad_crm_06_02_02_09(
    cliente: Any, de_ana: dict[str, str], canal: str, db: Any
) -> None:
    """Con el plazo puesto, lo que lleva en la papelera más de la cuenta se va.
    Y se va de la tabla: dejarlo con una marca no lo quita de ningún sitio, que
    es justo lo que no sirve cuando lo que se pegó fue una credencial."""
    from datetime import timedelta

    from crmcore.datos.guard_borrados import con_borrados

    from services.identity.chat import MensajeChat

    mensaje = _escribir(cliente, de_ana, canal, "credencial que no debía estar aquí")
    cliente.delete(f"/api/v1/chat/mensajes/{mensaje['id']}", headers=de_ana)

    # Hay que mirar dentro de la papelera para envejecerlo: el guard de borrados
    # esconde la fila, y `db.get` a secas devuelve None.
    with con_borrados(db) as sesion:
        fila = sesion.get(MensajeChat, UUID(mensaje["id"]))
    assert fila is not None
    fila.deleted_at = datetime.now(timezone.utc) - timedelta(days=40)
    db.flush()

    puesta = cliente.put(
        "/api/v1/identity/retencion/politicas",
        headers=de_ana,
        json={"clase": "chat_mensajes_borrados", "dias": 30},
    )
    assert puesta.status_code in (200, 201), puesta.text

    # **Simula por defecto**, como la importación masiva y por el mismo motivo:
    # lo que se va a llevar por delante hay que poder verlo antes, no después.
    ensayo = cliente.post("/api/v1/identity/retencion/purgar", headers=de_ana)
    assert ensayo.status_code == 200, ensayo.text
    mia = next(i for i in ensayo.json() if i["clase"] == "chat_mensajes_borrados")
    assert mia["candidatos"] == 1 and mia["simulado"] is True, mia
    assert mia["purgados"] == 0, "un ensayo que purga no es un ensayo"
    assert mia["dias_retencion"] == 30
    with con_borrados(db) as sesion:
        assert (
            sesion.get(MensajeChat, UUID(mensaje["id"])) is not None
        ), "el ensayo ha borrado de verdad: entonces no es un ensayo"

    purga = cliente.post("/api/v1/identity/retencion/purgar?simular=false", headers=de_ana)
    assert purga.status_code == 200, purga.text
    db.expire_all()
    # Y se comprueba MIRANDO DENTRO de la papelera. Con `db.get` a secas, el
    # guard lo escondería igual aunque la fila siguiera ahí: la comprobación
    # saldría verde sin haber purgado nada.
    with con_borrados(db) as sesion:
        assert sesion.get(MensajeChat, UUID(mensaje["id"])) is None, (
            "sigue en la tabla pasado el plazo: una papelera que guarda para "
            "siempre no es una papelera"
        )
