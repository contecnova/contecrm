"""La sesión del navegador va en cookie, no en el cliente (CRM-07.04.02.03).

`identity` devuelve los tokens en el cuerpo, que es lo correcto para una
integración: un servicio guarda su token donde quiera. Para un navegador no lo
es. Si el token llega al cliente, la aplicación tiene que guardarlo, y todos los
sitios que sobreviven a una recarga los puede leer un script inyectado — con lo
que un XSS deja de ser un susto y pasa a ser una sesión robada.

Lo que estas pruebas defienden:

  * La respuesta de entrar **no lleva el token**. Devolverlo «por comodidad»
    anularía todo, porque alguien lo guardaría.
  * La cookie lleva las cuatro propiedades, y ninguna es decorativa.
  * La cookie **autentica de verdad**, y una cabecera explícita manda sobre ella.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import jwt
import pytest
from crmcore.config import get_settings
from crmcore.http.deps import AutenticadoDep


def _token(tenant_id: UUID, usuario_id: UUID) -> str:
    """Un token de acceso como el que emite identidad."""
    from datetime import datetime, timedelta, timezone

    s = get_settings()
    return jwt.encode(
        {
            "sub": str(usuario_id),
            "tenant_id": str(tenant_id),
            "permisos": ["tenant:read"],
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        s.secret_key.get_secret_value(),
        algorithm=s.jwt_algorithm,
    )


@pytest.fixture
def api_con_cookie(tenant_id: UUID) -> Any:
    """Un servicio real, para comprobar que la cookie autentica de verdad."""
    from crmcore.service import crear_servicio
    from fastapi import APIRouter
    from starlette.testclient import TestClient

    router = APIRouter()

    @router.get("/quien", summary="Quién soy")
    def quien(principal: AutenticadoDep) -> dict[str, str]:
        return {"usuario": str(principal.id), "tenant": str(principal.tenant_id)}

    app = crear_servicio(
        nombre="pruebas",
        descripcion="pruebas de sesión",
        routers=[router],
        necesita_db=False,
        necesita_bus=False,
    )
    return TestClient(app)


def test_la_cookie_autentica_igual_que_la_cabecera(api_con_cookie: Any, tenant_id: UUID) -> None:
    usuario = uuid4()
    token = _token(tenant_id, usuario)
    s = get_settings()

    respuesta = api_con_cookie.get("/api/v1/quien", cookies={s.sesion_cookie_nombre: token})

    assert respuesta.status_code == 200
    assert respuesta.json()["usuario"] == str(usuario)


def test_una_cabecera_explicita_manda_sobre_la_cookie(api_con_cookie: Any, tenant_id: UUID) -> None:
    """Si no, una pestaña con sesión abierta cambiaría en silencio la identidad
    de una llamada de API hecha desde la misma máquina."""
    de_la_cookie = uuid4()
    de_la_cabecera = uuid4()
    s = get_settings()

    respuesta = api_con_cookie.get(
        "/api/v1/quien",
        cookies={s.sesion_cookie_nombre: _token(tenant_id, de_la_cookie)},
        headers={"Authorization": f"Bearer {_token(tenant_id, de_la_cabecera)}"},
    )

    assert respuesta.json()["usuario"] == str(de_la_cabecera)


def test_sin_cookie_ni_cabecera_no_hay_identidad(api_con_cookie: Any) -> None:
    respuesta = api_con_cookie.get("/api/v1/quien")
    assert respuesta.status_code in (401, 403), respuesta.text


def test_la_cookie_lleva_las_cuatro_propiedades() -> None:
    """`HttpOnly` la esconde de los scripts, `Secure` impide que viaje en claro,
    `SameSite` corta el envío cruzado y `Path` la acota a la API. Quitar
    cualquiera deshace una parte distinta de la protección."""
    from fastapi import Response

    from services.gateway.sesion import poner_cookie

    respuesta = Response()
    poner_cookie(respuesta, "un-token", segundos=900)
    cabecera = respuesta.headers["set-cookie"].lower()

    assert "httponly" in cabecera
    assert "samesite=lax" in cabecera
    assert "path=/api" in cabecera
    # `secure` sale de la configuración para poder trabajar en local sobre http.
    assert ("secure" in cabecera) == get_settings().sesion_cookie_secure


def test_entrar_no_devuelve_el_token_en_el_cuerpo() -> None:
    """Es la promesa entera: si el token vuelve en el cuerpo, alguien lo guarda
    donde un script lo lee y la cookie no ha servido de nada."""
    import inspect

    from services.gateway import sesion

    fuente = inspect.getsource(sesion)
    # La ruta devuelve solo cuándo caduca. Comprobarlo sobre el código y no
    # sobre una llamada es lo que permite que este gate siga valiendo cuando
    # alguien añada un campo a esa respuesta «que no hace daño».
    assert 'return {"caduca_en_s"' in fuente
    # Lo que no puede aparecer es el token en la respuesta. Se mira la línea del
    # `return`, no el fichero entero: `access_token_minutos` es configuración y
    # sí tiene que estar.
    linea = next(linea for linea in fuente.splitlines() if 'return {"caduca_en_s"' in linea)
    assert "access_token" not in linea.replace("access_token_minutos", "")
