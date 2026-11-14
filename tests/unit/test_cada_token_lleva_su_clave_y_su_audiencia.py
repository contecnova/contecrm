"""Auditoría 13-11-2026, SEC-11: ningún JWT llevaba `iss` ni `aud` y todos se
firmaban con la `SECRET_KEY` cruda, así que solo el campo `tipo` separaba una
sesión de empleado de un ticket de página pública. Ahora cada tipo tiene su
clave derivada y su audiencia (`crmcore.tokens`)."""

from __future__ import annotations

import time
from uuid import uuid4

import jwt
import pytest
from crmcore import tokens
from crmcore.config import get_settings


def _carga(tipo: str) -> dict[str, object]:
    return {
        "sub": str(uuid4()),
        "tenant": str(uuid4()),
        "tipo": tipo,
        "exp": int(time.time()) + 300,
    }


def test_lo_que_se_emite_se_verifica_con_emisor_y_audiencia() -> None:
    datos = tokens.verificar(tokens.emitir(_carga("usuario")), tipos={"usuario"})
    assert datos["iss"] == tokens.EMISOR
    assert datos["aud"] == tokens.audiencia("usuario")


def test_un_token_firmado_con_la_clave_cruda_ya_no_vale() -> None:
    """La forma de antes: sin `iss`/`aud` y con `SECRET_KEY` tal cual."""
    s = get_settings()
    viejo = jwt.encode(
        _carga("usuario"), s.secret_key.get_secret_value(), algorithm=s.jwt_algorithm
    )
    with pytest.raises(jwt.InvalidTokenError):
        tokens.verificar(viejo, tipos={"usuario"})


def test_cambiar_el_tipo_rompe_la_firma() -> None:
    """Un token de portal reescrito como `usuario` sigue firmado con la clave
    del portal: con la de sesión no cuadra."""
    s = get_settings()
    falso = jwt.encode(
        {**_carga("usuario"), "iss": tokens.EMISOR, "aud": tokens.audiencia("usuario")},
        tokens._clave("portal"),
        algorithm=s.jwt_algorithm,
    )
    with pytest.raises(jwt.InvalidSignatureError):
        tokens.verificar(falso, tipos={"usuario"})


def test_un_tipo_no_admitido_se_rechaza_antes_de_la_firma() -> None:
    with pytest.raises(tokens.TipoNoAdmitido):
        tokens.verificar(tokens.emitir(_carga("portal")), tipos={"usuario"})
