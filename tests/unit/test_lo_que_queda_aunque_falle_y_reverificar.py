"""Lo que tiene que quedar aunque la petición falle, y volver a verificarse sin
salir (CRM-00.05.01.18).

Medido el 10-11-2026:

- tres contraseñas malas dejaban `intentos_fallidos` en 0: el error que se
  contesta deshacía la transacción y con ella el contador, así que el bloqueo
  por fuerza bruta no actuaba nunca;
- no había forma de superar un factor fuerte con la sesión abierta: toda
  operación sensible —crear una clave de API, exportar, borrar en bloque—
  obligaba a salir y volver a entrar.
"""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID

import pytest

from tests.unit.test_las_pantallas_de_gobierno_y_lecciones_piden_lo_que_hay import (
    _cabeceras,
    _cliente,
)

pytestmark = pytest.mark.db

CONTRASENA = "una-contrasena-larga-1"


def _alta(cli: Any, tenant_id: UUID, email: str) -> None:
    r = cli.post(
        "/api/v1/usuarios",
        headers=_cabeceras(tenant_id),
        json={"email": email, "nombre": "Prueba", "contrasena": CONTRASENA},
    )
    assert r.status_code == 201, r.text[:300]


def _entrar(cli: Any, tenant_id: UUID, email: str, contrasena: str = CONTRASENA) -> Any:
    return cli.post(
        "/api/v1/auth/login",
        json={"email": email, "contrasena": contrasena, "tenant": str(tenant_id)},
    )


def _intentos(cli: Any, tenant_id: UUID, email: str) -> int:
    r = cli.get(f"/api/v1/usuarios?email={email}", headers=_cabeceras(tenant_id))
    cuerpo = r.json()
    filas = cuerpo if isinstance(cuerpo, list) else cuerpo.get("datos") or cuerpo.get("items") or []
    return int(next(u for u in filas if u["email"] == email)["intentos_fallidos"])


def test_el_acceso_con_contrasena_mala_contesta_y_apunta(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _cliente("identity", monkeypatch) as cli:
        _alta(cli, tenant_id, "fallos@ejemplo.com")
        for _ in range(3):
            r = _entrar(cli, tenant_id, "fallos@ejemplo.com", "mala")
            assert r.status_code == 401
            assert r.json()["error_code"] == "auth.credenciales_invalidas"
        # Que el contador QUEDE no se puede ver con el fixture `db` (comparte
        # una conexión y el deshacer de la petición se lo lleva): lo comprueba
        # `test_lo_escrito_aparte_queda_aunque_la_peticion_se_deshaga`, con
        # conexiones de verdad, y la pila local (10-11-2026).


def test_reverificarse_con_la_app_sin_salir(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    from services.identity import servicio as svc

    with _cliente("identity", monkeypatch) as cli:
        _alta(cli, tenant_id, "reverifica@ejemplo.com")
        r = _entrar(cli, tenant_id, "reverifica@ejemplo.com")
        assert r.status_code == 200, r.text[:300]
        auth = {"Authorization": f"Bearer {r.json()['access_token']}"}

        # Sin la app activada, se dice qué hacer.
        r = cli.post("/api/v1/auth/mfa/reverificar", headers=auth, json={"codigo": "123456"})
        assert r.status_code == 409, r.text[:300]
        assert r.json()["error_code"] == "auth.mfa_no_activa"

        secreto = cli.post("/api/v1/auth/mfa/iniciar", headers=auth).json()["secreto"]
        r = cli.post(
            "/api/v1/auth/mfa/activar",
            headers=auth,
            json={"codigo": svc.codigo_totp(secreto, time.time())},
        )
        assert r.status_code == 200, r.text[:300]

        # Un código malo no eleva nada (cuenta como intento fallido: ver la
        # prueba de lo escrito aparte).
        r = cli.post("/api/v1/auth/mfa/reverificar", headers=auth, json={"codigo": "000000"})
        assert r.status_code == 401, r.text[:300]
        assert r.json()["error_code"] == "auth.mfa_invalida"

        # El bueno eleva la sesión y devuelve el token que hay que usar.
        r = cli.post(
            "/api/v1/auth/mfa/reverificar",
            headers=auth,
            json={"codigo": svc.codigo_totp(secreto, time.time())},
        )
        assert r.status_code == 200, r.text[:300]
        cuerpo = r.json()
        assert cuerpo["usar_este_token"] is True
        assert cuerpo["access_token"] and cuerpo["factor_fuerte_at"]


def test_lo_escrito_aparte_queda_aunque_la_peticion_se_deshaga(_esquema: str) -> None:
    """Con conexiones de verdad, como en producción.

    Sin el fixture `db`: ése comparte UNA conexión con puntos de guardado
    anidados para poder deshacerlo todo al final, y ahí el deshacer de la
    petición se lleva también lo escrito «aparte» —que en producción va por otra
    conexión—. Medido al escribir esta prueba: con el fixture, 0; así, 1.
    """
    from uuid import uuid4

    from crmcore.db.session import guardar_aunque_falle, sesion
    from sqlalchemy import delete, select

    from services.identity.modelos import Usuario

    usuario_id = uuid4()
    with sesion(sistema=True) as s:
        s.add(Usuario(id=usuario_id, email=f"{usuario_id}@ejemplo.com", nombre="Aparte"))
    try:
        # La petición: lee la fila, apunta el fallo aparte y termina en error.
        with pytest.raises(RuntimeError):
            with sesion(sistema=True) as peticion:
                peticion.get(Usuario, usuario_id)
                guardar_aunque_falle(Usuario, usuario_id, {"intentos_fallidos": 1})
                raise RuntimeError("la petición contesta con error")
        with sesion(sistema=True) as s:
            intentos = s.execute(
                select(Usuario.intentos_fallidos).where(Usuario.id == usuario_id)
            ).scalar_one()
        assert intentos == 1
    finally:
        with sesion(sistema=True) as s:
            s.execute(delete(Usuario).where(Usuario.id == usuario_id))
