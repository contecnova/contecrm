"""Las puertas de entrar tienen tope por IP y no delatan qué correos existen.

SEC-13 (auditoría 13-11-2026): login, restablecer y entrar con passkey solo
tenían el límite general (1200/min por IP) y el bloqueo por cuenta, que deja
probar una contraseña contra mil cuentas y bloquear a propósito las de otros. Y
el login no calculaba ningún hash si el correo no existía, así que el tiempo de
respuesta decía qué correos tienen cuenta.

FUN-A-14: el tope del alta se contaba en `tenancy` por la IP del gateway, un
solo contador para todo el mundo.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from crmcore.config import get_settings
from crmcore.errors import LimiteExcedido, NoAutenticado
from crmcore.rutas_de_api import TOPES_POR_IP

PUERTAS = (
    "/api/v1/auth/login",
    "/api/v1/sesion/entrar",
    "/api/v1/auth/restablecer",
    "/api/v1/auth/passkeys/entrar",
    "/api/v1/portal/enlace",
    "/api/v1/portal/sesion",
    "/api/v1/portal-partner/",
    "/api/v1/alta",
)


def test_cada_puerta_de_entrar_tiene_su_tope_declarado() -> None:
    s = get_settings()
    for puerta in PUERTAS:
        assert puerta in TOPES_POR_IP, puerta
        limite, ventana = TOPES_POR_IP[puerta]
        assert int(getattr(s, limite)) > 0 and int(getattr(s, ventana)) > 0, puerta


async def test_el_gateway_corta_al_pasar_el_tope(monkeypatch: pytest.MonkeyPatch) -> None:
    from crmcore.http import rate_limit

    from services.gateway.api import _tope_por_ip

    monkeypatch.setattr(get_settings(), "entrar_intentos_por_ip", 2)
    rate_limit.limpiar_memoria()

    class _Peticion:
        client = type("c", (), {"host": "203.0.113.50"})()
        headers: dict[str, str] = {}

    for _ in range(2):
        await _tope_por_ip("/api/v1/auth/login", _Peticion())  # type: ignore[arg-type]
    with pytest.raises(LimiteExcedido):
        await _tope_por_ip("/api/v1/auth/login", _Peticion())  # type: ignore[arg-type]
    rate_limit.limpiar_memoria()


def test_el_login_del_navegador_pasa_por_el_tope() -> None:
    import inspect

    from services.gateway import sesion

    assert '_tope_por_ip("/api/v1/sesion/entrar"' in inspect.getsource(sesion)


def test_un_correo_desconocido_tambien_calcula_el_hash(
    db: Any, tenant_id: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Si no lo calcula, la respuesta llega antes y el tiempo delata la cuenta."""
    from services.identity import servicio as svc

    llamadas: list[Any] = []
    original = svc.verificar_contrasena

    def _espia(hash_guardado: Any, contrasena: str) -> bool:
        llamadas.append(hash_guardado)
        return original(hash_guardado, contrasena)

    monkeypatch.setattr(svc, "verificar_contrasena", _espia)
    with pytest.raises(NoAutenticado):
        svc.autenticar(db, email="nadie@ninguna.example", contrasena="x" * 16, tenant_id=tenant_id)
    assert llamadas == [None]
