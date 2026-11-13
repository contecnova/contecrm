"""Poner o cambiar un factor fuerte exige haberse verificado hace poco
(auditoría del 13-11-2026, SEC-4; CRM-00.05.01.18 y CRM-00.05.01.23).

`/mfa/iniciar` reescribía el secreto de un MFA **ya activo** sin pedir nada más
que la sesión, y `mfa_activo` seguía a cierto: con una sesión robada se cambiaba
el autenticador de la víctima por el del atacante en una llamada. El alta de
passkeys, igual: se colgaba una llave propia en la cuenta de otro, y esa llave
sobrevive a que la víctima cambie la contraseña. Quitar el factor sí exigía
reverificación (`cambio_mfa`); ponerlo o cambiarlo, que da lo mismo o más, no.

Sin base de datos: lo que se fija es la decisión de las rutas —corta o no corta,
y si corta, antes de escribir—, y eso se ve llamándolas con su usuario delante.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest


class _Db:
    """Lo mínimo de una sesión: `get` devuelve el usuario sembrado."""

    def __init__(self, usuario: Any) -> None:
        self.usuario = usuario

    def get(self, _modelo: Any, _id: Any) -> Any:
        return self.usuario


def _usuario(*, mfa_activo: bool) -> Any:
    return SimpleNamespace(
        id=uuid4(),
        email="ana@ejemplo.com",
        mfa_activo=mfa_activo,
        mfa_secreto="SECRETOVIEJO" if mfa_activo else None,
        mfa_recuperacion=["hash-viejo"] if mfa_activo else [],
    )


def _principal(usuario: Any, *, factor_hace_minutos: int | None) -> Any:
    marca = (
        (datetime.now(timezone.utc) - timedelta(minutes=factor_hace_minutos)).isoformat()
        if factor_hace_minutos is not None
        else ""
    )
    return SimpleNamespace(
        id=usuario.id,
        tenant_id=uuid4(),
        tipo="usuario",
        factor_fuerte_at=marca,
        actor_real_id=None,
        sesion_id=None,
    )


def _corta_por_reverificacion(fallo: Any) -> None:
    assert fallo.value.error_code == "stepup.requerido"
    assert fallo.value.detalle["operacion"] == "cambio_mfa"


# ── /mfa/iniciar ──────────────────────────────────────────────────────────


def test_con_el_mfa_activo_iniciar_sin_reverificar_se_corta_y_no_toca_el_secreto() -> None:
    """El caso de la auditoría: el secreto de un MFA activo no se reescribe con
    la sesión a secas."""
    from crmcore.errors import NoAutenticado

    from services.identity.api import iniciar_mfa

    usuario = _usuario(mfa_activo=True)
    with pytest.raises(NoAutenticado) as fallo:
        iniciar_mfa(_Db(usuario), _principal(usuario, factor_hace_minutos=None))
    _corta_por_reverificacion(fallo)
    assert usuario.mfa_secreto == "SECRETOVIEJO"
    assert usuario.mfa_recuperacion == ["hash-viejo"]


def test_un_factor_de_hace_horas_tampoco_vale_para_cambiar_el_autenticador() -> None:
    from crmcore.errors import NoAutenticado
    from crmcore.http.reverificacion import minutos_de_validez

    from services.identity.api import iniciar_mfa

    usuario = _usuario(mfa_activo=True)
    viejo = minutos_de_validez() + 1
    with pytest.raises(NoAutenticado) as fallo:
        iniciar_mfa(_Db(usuario), _principal(usuario, factor_hace_minutos=viejo))
    _corta_por_reverificacion(fallo)
    assert usuario.mfa_secreto == "SECRETOVIEJO"


def test_con_el_mfa_activo_y_reverificado_se_puede_cambiar_de_autenticador() -> None:
    """La otra mitad: sin ella, un arreglo que lo cerrara todo pasaría igual."""
    from services.identity.api import iniciar_mfa

    usuario = _usuario(mfa_activo=True)
    salida = iniciar_mfa(_Db(usuario), _principal(usuario, factor_hace_minutos=0))
    assert salida.secreto and salida.secreto != "SECRETOVIEJO"
    assert usuario.mfa_secreto == salida.secreto


def test_la_primera_configuracion_no_pide_un_factor_que_no_existe(monkeypatch: Any) -> None:
    """Sin ningún factor fuerte no hay con qué verificarse: exigirlo haría
    imposible configurar el primero."""
    from services.identity import servicio as svc
    from services.identity.api import iniciar_mfa

    monkeypatch.setattr(svc, "tiene_factor_fuerte", lambda _db, _u: False)
    usuario = _usuario(mfa_activo=False)
    salida = iniciar_mfa(_Db(usuario), _principal(usuario, factor_hace_minutos=None))
    assert usuario.mfa_secreto == salida.secreto


def test_quien_solo_tiene_passkey_tambien_tiene_que_reverificarse(monkeypatch: Any) -> None:
    """Una passkey es un factor fuerte: con ella, configurar la app de códigos
    también es cambiar el segundo factor de la cuenta."""
    from crmcore.errors import NoAutenticado

    from services.identity import servicio as svc
    from services.identity.api import iniciar_mfa

    monkeypatch.setattr(svc, "tiene_factor_fuerte", lambda _db, _u: True)
    usuario = _usuario(mfa_activo=False)
    with pytest.raises(NoAutenticado) as fallo:
        iniciar_mfa(_Db(usuario), _principal(usuario, factor_hace_minutos=None))
    _corta_por_reverificacion(fallo)
    assert usuario.mfa_secreto is None


# ── Alta de passkeys ──────────────────────────────────────────────────────


def _sin_tocar_passkeys(monkeypatch: Any) -> list[str]:
    """Sustituye lo que escribe para ver si se llega a llamar."""
    from services.identity import passkeys as pk

    llamadas: list[str] = []
    monkeypatch.setattr(
        pk, "opciones_registro", lambda *a, **k: llamadas.append("opciones") or {"ok": 1}
    )
    monkeypatch.setattr(
        pk,
        "guardar_registro",
        lambda *a, **k: llamadas.append("guardar") or SimpleNamespace(id=uuid4(), nombre="x"),
    )
    return llamadas


def test_empezar_una_passkey_con_factor_y_sin_reverificar_se_corta(monkeypatch: Any) -> None:
    from crmcore.errors import NoAutenticado

    from services.identity.api import empezar_registro_passkey

    llamadas = _sin_tocar_passkeys(monkeypatch)
    usuario = _usuario(mfa_activo=True)
    with pytest.raises(NoAutenticado) as fallo:
        empezar_registro_passkey(_Db(usuario), _principal(usuario, factor_hace_minutos=None))
    _corta_por_reverificacion(fallo)
    assert llamadas == [], "ha emitido el reto de registro sin reverificar"


def test_guardar_una_passkey_con_factor_y_sin_reverificar_se_corta(monkeypatch: Any) -> None:
    """La que escribe. Se puede llamar sin haber pasado por `/passkeys`, así que
    la comprobación de allí no la protege."""
    from crmcore.errors import NoAutenticado

    from services.identity.api import RegistroPasskey, confirmar_registro_passkey

    llamadas = _sin_tocar_passkeys(monkeypatch)
    usuario = _usuario(mfa_activo=True)
    uow = SimpleNamespace(db=_Db(usuario), tenant_id=uuid4())
    with pytest.raises(NoAutenticado) as fallo:
        confirmar_registro_passkey(
            RegistroPasskey(respuesta={}),
            uow,
            _principal(usuario, factor_hace_minutos=None),
        )
    _corta_por_reverificacion(fallo)
    assert llamadas == [], "ha guardado la llave sin reverificar"


def test_con_factor_reverificado_la_passkey_se_registra(monkeypatch: Any) -> None:
    from services.identity.api import (
        RegistroPasskey,
        confirmar_registro_passkey,
        empezar_registro_passkey,
    )

    llamadas = _sin_tocar_passkeys(monkeypatch)
    usuario = _usuario(mfa_activo=True)
    principal = _principal(usuario, factor_hace_minutos=0)
    empezar_registro_passkey(_Db(usuario), principal)
    confirmar_registro_passkey(
        RegistroPasskey(respuesta={}), SimpleNamespace(db=_Db(usuario)), principal
    )
    assert llamadas == ["opciones", "guardar"]


def test_la_primera_passkey_de_una_cuenta_sin_factor_se_registra(monkeypatch: Any) -> None:
    """Sin factor fuerte no hay con qué verificarse: la primera llave entra con
    la sesión, como antes, y deja su evento para quien vigila las cuentas."""
    from services.identity import servicio as svc
    from services.identity.api import empezar_registro_passkey

    llamadas = _sin_tocar_passkeys(monkeypatch)
    monkeypatch.setattr(svc, "tiene_factor_fuerte", lambda _db, _u: False)
    usuario = _usuario(mfa_activo=False)
    empezar_registro_passkey(_Db(usuario), _principal(usuario, factor_hace_minutos=None))
    assert llamadas == ["opciones"]


# ── Qué cuenta como «tiene factor fuerte» ─────────────────────────────────


def test_tener_factor_fuerte_es_mfa_activo_o_alguna_passkey() -> None:
    from services.identity.servicio import tiene_factor_fuerte

    class _DbPasskeys:
        def __init__(self, fila: Any) -> None:
            self.fila = fila
            self.consultas = 0

        def execute(self, _consulta: Any) -> Any:
            self.consultas += 1
            return SimpleNamespace(first=lambda: self.fila)

    # Con el MFA activo ni se pregunta por las passkeys.
    db = _DbPasskeys(None)
    assert tiene_factor_fuerte(db, _usuario(mfa_activo=True)) is True
    assert db.consultas == 0

    assert tiene_factor_fuerte(_DbPasskeys((uuid4(),)), _usuario(mfa_activo=False)) is True
    assert tiene_factor_fuerte(_DbPasskeys(None), _usuario(mfa_activo=False)) is False
