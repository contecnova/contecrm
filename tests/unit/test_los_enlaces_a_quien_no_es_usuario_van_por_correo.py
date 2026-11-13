"""El enlace de entrar al portal de partner y el de confirmar un alta van SOLO por
correo, nunca en la respuesta (auditoría del 13-11-2026, SEC-5 y SEC-6).

`POST /portal-partner/entrar` devolvía el token a quien lo pidiera sin
autenticar —«solo sin correo configurado», que no se comprobaba en ninguna
parte— y además `caduca_at` solo venía relleno si el correo era de un partner.
`POST /alta` devolvía el token de confirmación al propio solicitante, que
confirmaba él mismo un alta a nombre de un correo ajeno. En los dos casos el
enlace es la prueba de que el buzón es de quien lo pide; entregarlo en la
respuesta anulaba la prueba.

Y no había camino para mandarlo: los avisos son por usuario, y ni quien pide un
alta ni la persona de un partner lo son. Ahora el servicio dueño del enlace
emite un evento interno con la dirección y el texto, y `identity` —que tiene los
transportes— lo entrega a esa dirección (`services/identity/correo_externo.py`).

Sin base de datos: las rutas se llaman con su trabajo sustituido, y la emisión
con una unidad de trabajo de verdad sobre una sesión de mentira, que es lo que
comprueba el contrato del evento.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

TOKEN = "token-de-un-solo-uso-que-no-debe-salir"


class _Resultado:
    def __init__(self, valor: Any) -> None:
        self.valor = valor

    def scalar_one_or_none(self) -> Any:
        return self.valor

    def first(self) -> Any:
        return self.valor


class _Db:
    """Sesión de mentira: devuelve en orden lo que se le siembra."""

    def __init__(self, *respuestas: Any, objetos: dict[Any, Any] | None = None) -> None:
        self.respuestas = list(respuestas)
        self.objetos = objetos or {}
        self.anadidos: list[Any] = []

    def execute(self, _consulta: Any) -> _Resultado:
        return _Resultado(self.respuestas.pop(0) if self.respuestas else None)

    def get(self, _modelo: Any, clave: Any) -> Any:
        return self.objetos.get(clave)

    def add(self, fila: Any) -> None:
        if getattr(fila, "id", None) is None:
            fila.id = uuid4()
        self.anadidos.append(fila)

    def flush(self) -> None:
        pass


def _uow(db: _Db, tenant_id: Any) -> Any:
    from crmcore.db.uow import UnidadDeTrabajo

    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


# ── SEC-5: la puerta del portal de partner ────────────────────────────────


def _ruta_entrar(monkeypatch: Any, devuelve: tuple[Any, str]) -> Any:
    from services.sales import api_partners

    @contextmanager
    def _trabajo(_tenant: str) -> Any:
        yield SimpleNamespace(tenant_id=uuid4())

    monkeypatch.setattr(api_partners, "_trabajo_sin_credencial", _trabajo)
    monkeypatch.setattr(api_partners.prt, "emitir_enlace", lambda *_a, **_k: devuelve)
    return api_partners


def test_entrar_no_devuelve_el_token_aunque_el_partner_exista(monkeypatch: Any) -> None:
    api = _ruta_entrar(
        monkeypatch,
        (SimpleNamespace(caduca_at=datetime.now(timezone.utc) + timedelta(minutes=30)), TOKEN),
    )
    salida = api.entrar(api.Entrar(tenant="acme", email="ana@acme.com"))
    assert salida == {"enviado": True}
    assert TOKEN not in repr(salida)


def test_entrar_contesta_lo_mismo_exista_o_no_el_partner(monkeypatch: Any) -> None:
    """Idénticas, no «con las mismas claves»: `caduca_at` relleno solo para un
    partner ya decía que lo era."""
    api = _ruta_entrar(
        monkeypatch,
        (SimpleNamespace(caduca_at=datetime.now(timezone.utc) + timedelta(minutes=30)), TOKEN),
    )
    conocido = api.entrar(api.Entrar(tenant="acme", email="ana@acme.com"))
    api = _ruta_entrar(monkeypatch, (None, ""))
    desconocido = api.entrar(api.Entrar(tenant="acme", email="nadie@fuera.com"))
    assert conocido == desconocido


def test_emitir_el_enlace_encola_el_correo_al_buzon_del_acceso() -> None:
    """El enlace sale por el evento interno, a la dirección del acceso y con el
    mismo token que se guarda hasheado."""
    from crmcore.events.catalogo import obtener
    from crmcore.events.dominio import PARTNER_PORTAL_ENLACE

    from services.sales import partners as prt

    tenant_id = uuid4()
    acceso = SimpleNamespace(
        id=uuid4(), partner_id=uuid4(), email="ana@acme.com", nombre="Ana", activo=True
    )
    partner = SimpleNamespace(id=acceso.partner_id, estado="activo")
    uow = _uow(_Db(acceso, objetos={acceso.partner_id: partner}), tenant_id)

    enlace, token = prt.emitir_enlace(uow, email="Ana@Acme.com", validez_minutos=30)

    assert enlace is not None and token
    assert enlace.hash_token == prt._hash(token)
    [evento] = uow._pendientes
    assert evento["tipo"] == PARTNER_PORTAL_ENLACE.tipo
    assert evento["data"]["email"] == "ana@acme.com"
    assert prt.url_del_enlace(tenant_id, token) in evento["data"]["cuerpo"]
    assert "30 minutos" in evento["data"]["cuerpo"]
    # Interno: el cuerpo lleva la entrada al portal y ningún webhook lo recibe.
    assert obtener(PARTNER_PORTAL_ENLACE.tipo).publico is False


def test_a_un_correo_sin_acceso_no_se_le_manda_nada() -> None:
    from services.sales import partners as prt

    uow = _uow(_Db(None), uuid4())
    assert prt.emitir_enlace(uow, email="nadie@fuera.com", validez_minutos=30) == (None, "")
    assert uow._pendientes == []


# ── SEC-6: el alta autoservicio ───────────────────────────────────────────


def test_pedir_el_alta_no_devuelve_el_token(monkeypatch: Any) -> None:
    import crmcore.db.uow as modulo_uow

    from services.tenancy import api_alta

    @contextmanager
    def _trabajo(*_a: Any, **_k: Any) -> Any:
        yield SimpleNamespace()

    monkeypatch.setattr(modulo_uow, "unidad_de_trabajo", _trabajo)
    monkeypatch.setattr(api_alta.alta, "solicitar", lambda *_a, **_k: TOKEN)
    monkeypatch.setattr(api_alta, "_limitar", lambda _r: None)

    salida = api_alta.pedir_alta(
        api_alta.PedirAlta(
            slug="acme-nueva", nombre_empresa="ACME", email="ana@acme.example", nombre="Ana"
        ),
        SimpleNamespace(client=SimpleNamespace(host="10.0.0.1")),
    )
    assert salida == {"enviado": True}
    assert TOKEN not in repr(salida)


def _solicitar(monkeypatch: Any, *, slug_cogido: bool) -> tuple[Any, str]:
    from services.tenancy import alta

    monkeypatch.setattr(alta, "_exigir_activo", lambda: None)
    uow = _uow(_Db((uuid4(),) if slug_cogido else None), None)
    token = alta.solicitar(
        uow,
        slug="acme-nueva",
        nombre_empresa="ACME Nueva",
        email="Ana@Acme.example",
        nombre_persona="Ana Pérez",
    )
    return uow, token


def test_pedir_el_alta_encola_el_enlace_al_buzon_indicado(monkeypatch: Any) -> None:
    from crmcore.config import get_settings
    from crmcore.events.catalogo import obtener
    from crmcore.events.dominio import ALTA_SOLICITADA

    from services.tenancy import alta

    uow, token = _solicitar(monkeypatch, slug_cogido=False)
    [evento] = uow._pendientes
    assert evento["tipo"] == ALTA_SOLICITADA.tipo
    assert evento["data"]["email"] == "ana@acme.example"
    assert alta.url_del_enlace(token) in evento["data"]["cuerpo"]
    assert f"{get_settings().onboarding_enlace_horas} horas" in evento["data"]["cuerpo"]
    assert obtener(ALTA_SOLICITADA.tipo).publico is False


def test_con_el_slug_cogido_el_correo_sale_igual(monkeypatch: Any) -> None:
    """Si no saliera, la falta del correo diría lo que la respuesta calla."""
    uow, _token = _solicitar(monkeypatch, slug_cogido=True)
    assert len(uow._pendientes) == 1


# ── La entrega, en identity ───────────────────────────────────────────────


class _Transporte:
    canal = "correo"

    def __init__(self, entregado: bool = True) -> None:
        self.entregado = entregado
        self.llamadas: list[tuple[Any, Any, Any]] = []

    def entregar(self, destino: Any, mensaje: Any, config: Any) -> Any:
        from crmcore.notificaciones import Resultado

        self.llamadas.append((destino, mensaje, config))
        return Resultado(self.entregado, "" if self.entregado else "SMTP caído", reintentar=True)


def _identity(monkeypatch: Any, transporte: _Transporte) -> Any:
    import crmcore.notificaciones as notif

    from services.identity import correo_externo

    configs: list[Any] = []
    monkeypatch.setattr(notif, "transporte_de", lambda canal: transporte)
    monkeypatch.setattr(
        correo_externo,
        "_config_correo",
        lambda tenant_id: configs.append(tenant_id) or {"remitente": "x@y"},
    )
    return correo_externo, configs


def test_identity_manda_el_enlace_a_la_direccion_del_evento(monkeypatch: Any) -> None:
    import asyncio

    from crmcore.events.dominio import PARTNER_PORTAL_ENLACE
    from crmcore.events.envelope import Evento, Subject

    transporte = _Transporte()
    correo_externo, configs = _identity(monkeypatch, transporte)
    tenant_id, acceso_id = uuid4(), uuid4()
    evento = Evento(
        type=PARTNER_PORTAL_ENLACE.tipo,
        tenant_id=tenant_id,
        subject=Subject(tipo="acceso_partner", id=str(acceso_id)),
        data={
            "acceso_id": str(acceso_id),
            "email": "ana@acme.com",
            "nombre": "Ana",
            "titulo": "Tu enlace",
            "cuerpo": "https://crm/portal-partner?t=abc",
        },
    )
    asyncio.run(correo_externo.consumir_correo_externo(evento))

    [(destino, mensaje, config)] = transporte.llamadas
    assert destino.direccion == "ana@acme.com"
    assert destino.usuario_id == acceso_id
    assert mensaje.cuerpo == "https://crm/portal-partner?t=abc"
    # Con la marca del remitente de ESA empresa.
    assert configs == [tenant_id] and config == {"remitente": "x@y"}


def test_el_alta_sale_con_la_configuracion_de_la_instalacion(monkeypatch: Any) -> None:
    """El tenant del sobre de un alta es de relleno: todavía no existe ninguno."""
    from crmcore.events.dominio import ALTA_SOLICITADA

    transporte = _Transporte()
    correo_externo, configs = _identity(monkeypatch, transporte)
    datos = {"email": "ana@acme.example", "nombre": "Ana", "titulo": "t", "cuerpo": "c"}
    assert correo_externo.entregar(ALTA_SOLICITADA.tipo, uuid4(), datos, uuid4()) is True
    assert configs == [None]


def test_un_evento_ajeno_o_incompleto_no_manda_nada(monkeypatch: Any) -> None:
    from crmcore.events.dominio import ALTA_SOLICITADA

    transporte = _Transporte()
    correo_externo, _ = _identity(monkeypatch, transporte)
    datos = {"email": "a@b.c", "titulo": "t", "cuerpo": "c"}
    assert correo_externo.entregar("user.provisioned", uuid4(), datos, uuid4()) is False
    assert correo_externo.entregar(ALTA_SOLICITADA.tipo, None, {"email": "a@b.c"}, None) is False
    assert transporte.llamadas == []


def test_si_no_sale_se_dice_y_no_revienta_el_consumidor(monkeypatch: Any) -> None:
    from crmcore.events.dominio import ALTA_SOLICITADA

    correo_externo, _ = _identity(monkeypatch, _Transporte(entregado=False))
    datos = {"email": "a@b.c", "titulo": "t", "cuerpo": "c"}
    assert correo_externo.entregar(ALTA_SOLICITADA.tipo, None, datos, uuid4()) is False


def test_identity_esta_suscrito_a_los_dos_enlaces() -> None:
    """Sin la suscripción, el evento se vuelca y no lo recoge nadie: el mismo
    callejón que dejaba sin correo el enlace de restablecer la contraseña."""
    import ast
    from pathlib import Path

    from crmcore.events.dominio import ALTA_SOLICITADA, PARTNER_PORTAL_ENLACE

    from services.identity.correo_externo import CORREOS_EXTERNOS

    assert set(CORREOS_EXTERNOS) == {ALTA_SOLICITADA.tipo, PARTNER_PORTAL_ENLACE.tipo}
    fuente = (Path(__file__).resolve().parents[2] / "services/identity/main.py").read_text(
        encoding="utf-8"
    )
    suscritos = {
        n.elts[0].id
        for n in ast.walk(ast.parse(fuente))
        if isinstance(n, ast.Tuple)
        and len(n.elts) == 3
        and isinstance(n.elts[0], ast.Name)
        and isinstance(n.elts[1], ast.Name)
        and n.elts[1].id == "consumir_correo_externo"
    }
    assert suscritos == {"ALTA_SOLICITADA", "PARTNER_PORTAL_ENLACE"}
