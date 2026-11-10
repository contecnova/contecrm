"""Lo que integración ve en los canales, contado a quien lo tiene que saber
(CRM-01.01.05.02, CRM-03.03.01.04 y el «número erróneo» del marcador).

Hasta el 09-11-2026 tres cosas estaban escritas a un lado y sin llamar desde el
otro: party tenía su ruta para anotar señales de identidad y nadie se las
mandaba; sales tenía la puerta única para «ha contestado» y el buzón no
avisaba; y el marcador decía «marca el teléfono como erróneo» en vez de
marcarlo. Estas pruebas miran la llamada que sale, una sola vez, y que un
fallo del otro lado no tumba la entrada.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import NoDisponible
from starlette.testclient import TestClient

from services.integration import buzon as buz
from services.integration import canales_entrada as canales
from services.integration import senales_identidad as sen
from services.integration import telefonia as tel

pytestmark = pytest.mark.db

OBSERVAR = "/api/v1/calidad-dato/identidades/observar"


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


class _Otro:
    """Party y sales de mentira: apuntan lo que se les pide y contestan."""

    def __init__(self, *, caido: bool = False, sacadas: int = 1) -> None:
        self.caido = caido
        self.sacadas = sacadas
        self.pedido: list[dict[str, Any]] = []

    def __call__(self, **kw: Any) -> dict[str, Any]:
        self.pedido.append(kw)
        if self.caido:
            raise NoDisponible("party no responde", error_code="interno.servicio_no_responde")
        if kw["ruta"] == "/api/v1/cadencias/respuesta":
            return {"ok": True, "estado": 200, "datos": {"sacadas": self.sacadas}}
        if kw["ruta"] == "/api/v1/contacts" and kw["metodo"] == "GET":
            return {"ok": True, "datos": {"items": []}}
        return {"ok": True, "estado": 201, "datos": {"id": str(uuid4())}}

    def a(self, ruta: str) -> list[dict[str, Any]]:
        return [p for p in self.pedido if p["ruta"] == ruta]


def _identidad(tenant_id: UUID) -> dict[str, Any]:
    return {"tenant_id": tenant_id, "principal_id": uuid4(), "permisos": [], "roles": []}


# ── Señales de identidad (CRM-01.01.05.02) ────────────────────────────────


def test_la_senal_se_manda_una_vez_y_con_su_contacto(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    party = _Otro()
    contacto = uuid4()
    for _ in range(2):
        fila = sen.anotar_y_enviar(
            uow.db,
            uow.tenant_id,
            identidad=_identidad(uow.tenant_id),
            invocar=party,
            tipo="email",
            valor="Ana@Cliente.com",
            origen="canal:correo",
            referencia="m-1",
            contacto_id=contacto,
        )
    assert fila is not None and fila.estado == "enviada"
    assert len(party.a(OBSERVAR)) == 1
    cuerpo = party.a(OBSERVAR)[0]["cuerpo"]
    assert cuerpo == {
        "tipo": "email",
        "valor": "Ana@Cliente.com",
        "contacto_id": str(contacto),
        "origen": "canal:correo",
    }


def test_si_party_no_contesta_queda_en_error_y_el_relevo_la_manda_como_sistema(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    fila = sen.anotar_y_enviar(
        uow.db,
        uow.tenant_id,
        identidad=_identidad(uow.tenant_id),
        invocar=_Otro(caido=True),
        tipo="telefono",
        valor="+34600111222",
        origen="telefonia",
        referencia="ll-1",
    )
    assert fila is not None and fila.estado == "error"
    assert "no responde" in fila.error

    party = _Otro()
    assert sen.reenviar_pendientes(uow.db, uow.tenant_id, invocar=party)["enviadas"] == 1
    assert fila.estado == "enviada"
    # Sin persona detrás: la identidad del sistema, con el permiso justo.
    llamada = party.a(OBSERVAR)[0]
    assert llamada["principal_id"] == uow.tenant_id
    assert llamada["permisos"] == ["contact:write"]
    # Y no se vuelve a mandar.
    assert sen.reenviar_pendientes(uow.db, uow.tenant_id, invocar=party)["enviadas"] == 0


def test_lo_que_party_rechaza_no_se_reintenta(uow: UnidadDeTrabajo, contexto_tenant: UUID) -> None:
    def rechaza(**kw: Any) -> dict[str, Any]:
        return {"ok": False, "estado": 422, "datos": {"mensaje": "Tipo de señal no reconocido"}}

    fila = sen.anotar_y_enviar(
        uow.db,
        uow.tenant_id,
        identidad=_identidad(uow.tenant_id),
        invocar=rechaza,
        tipo="raro",
        valor="x",
        origen="integracion:clientes",
        referencia="r-1",
    )
    assert fila is not None and fila.estado == "rechazada"
    party = _Otro()
    sen.reenviar_pendientes(uow.db, uow.tenant_id, invocar=party)
    assert party.pedido == []


def test_el_correo_que_entra_por_un_canal_manda_su_senal_y_party_caido_no_lo_tumba(
    uow: UnidadDeTrabajo, contexto_tenant: UUID, monkeypatch: Any
) -> None:
    party = _Otro(caido=True)
    monkeypatch.setattr(sen, "_invocar", party)
    salida = canales.registrar(
        uow,
        canal="correo",
        id_externo="<m-1@cliente.com>",
        interlocutor="ana@cliente.com",
        identidad=_identidad(uow.tenant_id),
    )
    assert salida["registrada"] is True
    assert salida["senal_identidad"] == "error"

    # Atribuirla después ata la señal al contacto, y vuelve a party.
    party.caido = False
    contacto = uuid4()
    canales.atribuir(
        uow,
        UUID(salida["interaccion_id"]),
        contacto_id=contacto,
        identidad=_identidad(uow.tenant_id),
    )
    assert party.a(OBSERVAR)[-1]["cuerpo"]["contacto_id"] == str(contacto)

    # El usuario de la CLI es de la casa: no es señal de nadie.
    otra = canales.registrar(
        uow, canal="cli", id_externo="cli-1", interlocutor="yo", identidad=_identidad(uow.tenant_id)
    )
    assert otra["senal_identidad"] == ""


def test_el_numero_que_llama_es_una_senal_con_su_contacto(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    contacto = str(uuid4())
    pedido: list[dict[str, Any]] = []

    def party(**kw: Any) -> dict[str, Any]:
        pedido.append(kw)
        if kw["ruta"] == "/api/v1/contacts" and "telefono__en" in (kw.get("parametros") or {}):
            return {"ok": True, "datos": {"items": [{"id": contacto, "nombre_completo": "Ana"}]}}
        if kw["metodo"] == "GET":
            return {"ok": True, "datos": {"items": []}}
        return {"ok": True, "estado": 201, "datos": {"id": str(uuid4())}}

    for evento in ("entrante", "contestada"):
        tel.ingerir(
            db,
            tenant_id,
            conexion=None,
            aviso={
                "id_externo": "c-77",
                "evento": evento,
                "numero": "+34600111222",
                "sentido": "entrante",
            },
            identidad=_identidad(tenant_id),
            invocar=party,
        )
    senales = [p for p in pedido if p["ruta"] == OBSERVAR]
    assert len(senales) == 1
    assert senales[0]["cuerpo"]["tipo"] == "telefono"
    assert senales[0]["cuerpo"]["contacto_id"] == contacto


def test_lo_que_entra_del_erp_manda_las_senales_que_declara_la_operacion(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    from services.integration import programador
    from services.integration.modelos import Operacion

    operacion = Operacion(
        tenant_id=uow.tenant_id,
        conexion_id=uuid4(),
        clave="clientes_erp",
        nombre="Clientes del ERP",
        definicion={"senales_identidad": {"codigo": "id_erp", "cif": "nif"}},
    )
    programador._aterrizar(
        uow,
        operacion,
        [
            {"id_externo": "C-1", "codigo": "C-1", "cif": "B12345678"},
            {"id_externo": "C-2", "codigo": "C-2"},
        ],
    )
    party = _Otro()
    assert sen.reenviar_pendientes(uow.db, uow.tenant_id, invocar=party)["enviadas"] == 3
    tipos = sorted(p["cuerpo"]["tipo"] for p in party.a(OBSERVAR))
    assert tipos == ["id_erp", "id_erp", "nif"]
    assert {p["cuerpo"]["origen"] for p in party.a(OBSERVAR)} == {"integracion:clientes_erp"}


# ── La respuesta del buzón saca de las cadencias (CRM-03.03.01.04) ────────


def _buzon_de_correo(uow: UnidadDeTrabajo, **kw: Any) -> Any:
    fila = buz.conectar(
        uow,
        usuario_id=uuid4(),
        perfil="correo-generico",
        direccion="comercial@empresa.com",
        **kw,
    )
    buz.marcar_autorizado(uow, buzon_id=fila.id)
    return fila


def test_el_correo_que_contesta_saca_de_la_cadencia_una_sola_vez(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    buzon = _buzon_de_correo(uow)
    elementos = [
        {"id": "m-1", "remitente": "Ana@Cliente.com", "participantes": ["ana@cliente.com"]},
        # Lo que manda el propio comercial no es una respuesta.
        {
            "id": "m-2",
            "remitente": "comercial@empresa.com",
            "participantes": ["ana@cliente.com"],
        },
        {"id": "m-3", "direccion": "saliente", "participantes": ["ana@cliente.com"]},
    ]
    buz.sincronizar(
        uow, buzon_id=buzon.id, elementos=elementos, direcciones_conocidas=["ana@cliente.com"]
    )
    otros = _Otro()
    ident = _identidad(uow.tenant_id)
    salida = buz.avisar_respuestas(uow, buzon_id=buzon.id, identidad=ident, invocar=otros)
    assert salida == {"avisadas": 1, "sacadas_de_cadencias": 1, "errores": 0}
    aviso = otros.a("/api/v1/cadencias/respuesta")
    assert [a["cuerpo"] for a in aviso] == [{"email": "ana@cliente.com", "tipo": "respondio"}]
    assert aviso[0]["principal_id"] == ident["principal_id"]
    # Quien contesta es también una señal de identidad.
    assert otros.a(OBSERVAR)[0]["cuerpo"]["valor"] == "ana@cliente.com"

    # El proveedor reenvía el mismo correo y se sincroniza otra vez: nada sale.
    buz.sincronizar(uow, buzon_id=buzon.id, elementos=elementos[:1])
    assert (
        buz.avisar_respuestas(uow, buzon_id=buzon.id, identidad=ident, invocar=otros)["avisadas"]
        == 0
    )
    assert len(otros.a("/api/v1/cadencias/respuesta")) == 1


def test_si_las_cadencias_no_contestan_se_reintenta_en_la_siguiente_vuelta(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    buzon = _buzon_de_correo(uow, criterio="todo")
    buz.sincronizar(uow, buzon_id=buzon.id, elementos=[{"id": "m-9", "de": "lead@fuera.com"}])
    ident = _identidad(uow.tenant_id)
    salida = buz.avisar_respuestas(
        uow, buzon_id=buzon.id, identidad=ident, invocar=_Otro(caido=True)
    )
    assert salida["errores"] == 1
    otros = _Otro()
    assert (
        buz.avisar_respuestas(uow, buzon_id=buzon.id, identidad=ident, invocar=otros)["avisadas"]
        == 1
    )


def test_del_que_no_es_nadie_aqui_no_se_guarda_la_direccion(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    buzon = _buzon_de_correo(uow)
    buz.sincronizar(
        uow,
        buzon_id=buzon.id,
        elementos=[{"id": "m-5", "remitente": "spam@fuera.com", "participantes": ["x@y.com"]}],
        direcciones_conocidas=["ana@cliente.com"],
    )
    otros = _Otro(sacadas=0)
    buz.avisar_respuestas(
        uow, buzon_id=buzon.id, identidad=_identidad(uow.tenant_id), invocar=otros
    )
    fila = uow.db.query(buz.ElementoSincronizado).filter_by(externo_id="m-5").one()
    assert fila.respuesta_cadencia == "avisada"
    assert fila.remitente == ""
    assert otros.a(OBSERVAR) == []


def test_el_correo_registrado_se_hace_actividad_email(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    buzon = _buzon_de_correo(uow, criterio="todo")
    buz.sincronizar(
        uow, buzon_id=buzon.id, elementos=[{"id": "m-7", "asunto": "Re: oferta", "de": "a@b.com"}]
    )
    otros = _Otro()
    salida = buz.registrar_reuniones(
        uow, buzon_id=buzon.id, identidad=_identidad(uow.tenant_id), invocar=otros
    )
    assert salida["creadas"] == 1
    alta = otros.a("/api/v1/activities")[0]["cuerpo"]
    assert alta["tipo"] == "email"
    assert alta["detalles"]["remitente"] == "a@b.com"


# ── «Número erróneo» marca el teléfono de la ficha ────────────────────────


def _llamada(db: Any, tenant_id: UUID, contacto_id: UUID | None) -> tel.LlamadaTelefonica:
    fila = tel.LlamadaTelefonica(
        tenant_id=tenant_id,
        sentido="saliente",
        numero="600111222",
        estado="colgada",
        contacto_id=contacto_id,
        identificacion={},
        contexto={},
        ivr={},
        transferencias=[],
        eventos=[],
    )
    db.add(fila)
    db.flush()
    return fila


def test_numero_erroneo_marca_el_telefono_del_contacto_en_party(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    contacto = uuid4()
    llamada = _llamada(db, tenant_id, contacto)
    party = _Otro()
    tel.anotar_resultado(
        db,
        tenant_id,
        llamada_id=llamada.id,
        resultado_comercial="numero_erroneo",
        nota="",
        invocar=party,
        identidad=_identidad(tenant_id),
    )
    parche = [p for p in party.pedido if p["metodo"] == "PATCH"]
    assert parche[0]["ruta"] == f"/api/v1/contacts/{contacto}"
    assert parche[0]["cuerpo"] == {"estado_telefono": "erroneo"}
    assert tel.a_dict(llamada)["telefono_marcado"]["marcado"] is True

    # Otro resultado no toca la ficha.
    otra = _llamada(db, tenant_id, contacto)
    party = _Otro()
    tel.anotar_resultado(
        db,
        tenant_id,
        llamada_id=otra.id,
        resultado_comercial="hablado",
        nota="",
        invocar=party,
        identidad=_identidad(tenant_id),
    )
    assert party.pedido == []
    assert tel.a_dict(otra)["telefono_marcado"] is None


def test_sin_contacto_o_si_party_no_deja_se_dice_que_falta(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    sin = _llamada(db, tenant_id, None)
    tel.anotar_resultado(
        db,
        tenant_id,
        llamada_id=sin.id,
        resultado_comercial="numero_erroneo",
        nota="",
        invocar=_Otro(),
        identidad=_identidad(tenant_id),
    )
    assert "márcalo a mano" in tel.a_dict(sin)["telefono_marcado"]["porque"]

    def prohibe(**kw: Any) -> dict[str, Any]:
        return {"ok": False, "estado": 403, "datos": {"mensaje": "sin permiso"}}

    con = _llamada(db, tenant_id, uuid4())
    tel.anotar_resultado(
        db,
        tenant_id,
        llamada_id=con.id,
        resultado_comercial="numero_erroneo",
        nota="",
        invocar=prohibe,
        identidad=_identidad(tenant_id),
    )
    marcado = tel.a_dict(con)["telefono_marcado"]
    assert marcado["marcado"] is False and "sin permiso" in marcado["porque"]


def test_el_marcador_dice_si_la_telefonia_marco_el_telefono() -> None:
    from services.service import marcador

    contacto = str(uuid4())

    def servicios(marcado: dict[str, Any]) -> Any:
        def _llamar(**kw: Any) -> dict[str, Any]:
            if kw["metodo"] == "GET":
                return {"ok": True, "datos": {"id": "l1", "contacto_id": contacto}}
            return {"ok": True, "estado": 200, "datos": {"telefono_marcado": marcado}}

        return _llamar

    base = {
        "identidad": {"tenant_id": uuid4(), "principal_id": uuid4()},
        "llamada_id": uuid4(),
        "resultado": "numero_erroneo",
        "nota": "",
        "proxima_fecha": None,
    }
    bien = marcador.colgar(**base, invocar=servicios({"marcado": True}))
    assert bien["aplicadas"] == ["Teléfono marcado como erróneo en la ficha"]
    mal = marcador.colgar(**base, invocar=servicios({"marcado": False, "porque": "sin permiso"}))
    assert mal["pendientes"] == ["sin permiso"]


# ── Por HTTP: las rutas que piden las pantallas ───────────────────────────


@pytest.fixture
def cliente(monkeypatch: Any, db: Any) -> Iterator[TestClient]:
    from crmcore.config import get_settings
    from crmcore.service import crear_servicio

    from services.integration.api_buzon import ROUTERS_BUZON
    from services.integration.api_conectividad import ROUTERS_CONECTIVIDAD
    from services.integration.api_telefonia import ROUTERS_TELEFONIA

    get_settings.cache_clear()
    app = crear_servicio(
        nombre="integration",
        descripcion="integration: señales y respuestas",
        routers=[*ROUTERS_BUZON, *ROUTERS_CONECTIVIDAD, *ROUTERS_TELEFONIA],
        necesita_bus=False,
    )
    with TestClient(app) as cli:
        yield cli
    get_settings.cache_clear()


@pytest.fixture
def cabeceras(tenant_id: UUID) -> dict[str, str]:
    from crmcore.config import get_settings
    from crmcore.http.deps import H_PERMISOS, H_TENANT, H_USER, firmar_cabeceras_internas

    return firmar_cabeceras_internas(
        {H_TENANT: str(tenant_id), H_USER: str(uuid4()), H_PERMISOS: "*:*"},
        get_settings().secret_key.get_secret_value(),
    )


def test_por_http_sincronizar_avisa_a_las_cadencias_y_el_canal_manda_su_senal(
    cliente: TestClient, cabeceras: dict[str, str], monkeypatch: Any
) -> None:
    otros = _Otro()
    monkeypatch.setattr(buz, "_invocar", otros)
    monkeypatch.setattr(sen, "_invocar", otros)
    alta = cliente.post(
        "/api/v1/buzones",
        headers=cabeceras,
        json={
            "usuario_id": str(uuid4()),
            "perfil": "correo-generico",
            "direccion": "http-senales@empresa.com",
            "criterio": "todo",
        },
    )
    assert alta.status_code == 201, alta.text
    bid = alta.json()["id"]
    cliente.post(f"/api/v1/buzones/{bid}/autorizado", headers=cabeceras)
    r = cliente.post(
        f"/api/v1/buzones/{bid}/sincronizar",
        headers=cabeceras,
        json={"elementos": [{"id": "h-1", "remitente": "lead@fuera.com"}]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["respuestas"]["avisadas"] == 1
    assert r.json()["reuniones"]["creadas"] == 1
    assert otros.a("/api/v1/cadencias/respuesta")[0]["cuerpo"]["email"] == "lead@fuera.com"

    canal = cliente.post(
        "/api/v1/canales-entrada/interacciones",
        headers=cabeceras,
        json={
            "canal": "sms",
            "id_externo": f"sms-{uuid4().hex[:6]}",
            "interlocutor": "+34600999888",
        },
    )
    assert canal.status_code == 200, canal.text
    assert canal.json()["senal_identidad"] == "enviada"
    assert otros.a(OBSERVAR)[-1]["cuerpo"]["tipo"] == "telefono"


def test_por_http_el_resultado_numero_erroneo_devuelve_si_se_marco(
    cliente: TestClient, cabeceras: dict[str, str], db: Any, tenant_id: UUID, monkeypatch: Any
) -> None:
    party = _Otro()
    monkeypatch.setattr(tel, "_invocar", party)
    llamada = _llamada(db, tenant_id, uuid4())
    db.flush()
    r = cliente.post(
        f"/api/v1/telefonia/llamadas/{llamada.id}/resultado",
        headers=cabeceras,
        json={"resultado_comercial": "numero_erroneo"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["telefono_marcado"]["marcado"] is True
    assert [p["cuerpo"] for p in party.pedido if p["metodo"] == "PATCH"] == [
        {"estado_telefono": "erroneo"}
    ]
