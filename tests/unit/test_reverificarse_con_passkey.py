"""Volver a verificarse con una passkey, sin salir (auditoría 13-11-2026, UX-28).

Sólo se podía con el código de la app de autenticación: quien tenía únicamente
passkeys —el factor más fuerte de los que hay— tenía que salir y volver a
entrar con la llave para cada operación sensible.

Lo que fija esta prueba, en el orden en que duele si se rompe:

- el reto es SÓLO de las llaves de quien está dentro y exige la verificación
  del usuario (huella o PIN), no sólo tener el dispositivo;
- un reto de ENTRAR no vale para reverificarse;
- una llave de otra cuenta del mismo tenant no eleva esta sesión;
- la buena eleva la sesión, devuelve el token que hay que usar y no se puede
  reproducir.

La firma de verdad la hace un autenticador y aquí no lo hay: se sustituye la
comprobación criptográfica de la librería (`verify_authentication_response`)
y se prueba todo lo que hay alrededor, que es lo que escribimos nosotros.
"""

from __future__ import annotations

import base64
import json
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from tests.unit.test_las_pantallas_de_gobierno_y_lecciones_piden_lo_que_hay import (
    _cabeceras,
    _cliente,
)

pytestmark = pytest.mark.db

CONTRASENA = "una-contrasena-larga-1"


def _b64url(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).rstrip(b"=").decode()


# En base64url de verdad: las opciones decodifican el identificador y lo
# vuelven a codificar, y uno que no lo es («mia») sale cambiado («miY»).
MIA = _b64url(b"llave-mia")
AJENA = _b64url(b"llave-ajena")


def _firma(credencial: str, reto: str) -> dict[str, Any]:
    """Lo mínimo de la respuesta del navegador que miramos antes de la cripto."""
    cliente = json.dumps({"challenge": reto, "type": "webauthn.get"}).encode()
    return {
        "id": credencial,
        "rawId": credencial,
        "type": "public-key",
        "response": {
            "clientDataJSON": _b64url(cliente),
            "authenticatorData": "",
            "signature": "",
        },
    }


def test_reverificarse_con_la_passkey_sin_salir(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    import webauthn

    from services.identity.passkeys import Passkey

    comprobadas: list[dict[str, Any]] = []

    def _verificar(**kwargs: Any) -> Any:
        comprobadas.append(kwargs)
        return SimpleNamespace(new_sign_count=len(comprobadas))

    monkeypatch.setattr(webauthn, "verify_authentication_response", _verificar)

    with _cliente("identity", monkeypatch) as cli:
        r = cli.post(
            "/api/v1/usuarios",
            headers=_cabeceras(tenant_id),
            json={"email": "llave@ejemplo.com", "nombre": "Llave", "contrasena": CONTRASENA},
        )
        assert r.status_code == 201, r.text[:300]
        r = cli.post(
            "/api/v1/auth/login",
            json={"email": "llave@ejemplo.com", "contrasena": CONTRASENA, "tenant": str(tenant_id)},
        )
        assert r.status_code == 200, r.text[:300]
        auth = {"Authorization": f"Bearer {r.json()['access_token']}"}
        yo = UUID(cli.get("/api/v1/auth/me", headers=auth).json()["usuario"]["id"])

        # Sin ninguna llave se dice qué hacer, en vez de abrir el navegador
        # para nada.
        r = cli.post("/api/v1/auth/passkeys/reverificar", headers=auth)
        assert r.status_code == 409, r.text[:300]
        assert r.json()["error_code"] == "auth.sin_passkey"

        db.add(Passkey(tenant_id=tenant_id, usuario_id=yo, credencial_id=MIA, clave_publica=b"k"))
        db.add(
            Passkey(
                tenant_id=tenant_id, usuario_id=uuid4(), credencial_id=AJENA, clave_publica=b"k"
            )
        )
        db.flush()

        nivel = cli.get("/api/v1/factores/nivel", headers=auth).json()
        assert nivel["tiene_passkey"] is True and nivel["tiene_app"] is False

        def _reto() -> dict[str, Any]:
            r = cli.post("/api/v1/auth/passkeys/reverificar", headers=auth)
            assert r.status_code == 200, r.text[:300]
            return r.json()

        opciones = _reto()
        # Sólo las suyas, y con huella o PIN exigidos.
        assert [c["id"] for c in opciones["allowCredentials"]] == [MIA]
        assert opciones["userVerification"] == "required"

        # Un reto de entrar no vale aquí.
        de_entrar = cli.post(
            "/api/v1/auth/passkeys/entrar", json={"tenant": str(tenant_id)}
        ).json()["challenge"]
        r = cli.post(
            "/api/v1/auth/passkeys/reverificar/confirmar",
            headers=auth,
            json={"respuesta": _firma(MIA, de_entrar)},
        )
        assert r.status_code == 401, r.text[:300]
        assert r.json()["error_code"] == "passkey.reto_no_valido"

        # La llave de otra cuenta no eleva ESTA sesión.
        r = cli.post(
            "/api/v1/auth/passkeys/reverificar/confirmar",
            headers=auth,
            json={"respuesta": _firma(AJENA, _reto()["challenge"])},
        )
        assert r.status_code == 401, r.text[:300]
        assert r.json()["error_code"] == "passkey.de_otra_cuenta"
        assert comprobadas == []

        # La buena eleva la sesión y devuelve el token que hay que usar.
        reto = _reto()["challenge"]
        r = cli.post(
            "/api/v1/auth/passkeys/reverificar/confirmar",
            headers=auth,
            json={"respuesta": _firma(MIA, reto)},
        )
        assert r.status_code == 200, r.text[:300]
        cuerpo = r.json()
        assert cuerpo["usar_este_token"] is True
        assert cuerpo["access_token"] and cuerpo["factor_fuerte_at"]
        assert comprobadas[-1]["require_user_verification"] is True

        # Y la misma firma no vale dos veces.
        r = cli.post(
            "/api/v1/auth/passkeys/reverificar/confirmar",
            headers=auth,
            json={"respuesta": _firma(MIA, reto)},
        )
        assert r.status_code == 401, r.text[:300]
        assert r.json()["error_code"] == "passkey.reto_no_valido"
