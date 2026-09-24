"""La sesión de quien entra desde fuera (CRM-04.03.02.01).

El portal se diseñó headless: la API sirve datos para que cada cliente monte su
portal con su marca. Eso sigue valiendo. Lo que faltaba es que **el cliente
pueda entrar él**: todas las rutas del portal exigían un principal del CRM, así
que quien quisiera un portal tenía que montar un intermediario que guardara
credenciales de empleado para servir a sus clientes — que no es un portal, es
una credencial de empleado compartida por internet.

Lo que estas pruebas defienden, que es lo que hace que esto sea seguro:

  * El token de portal **no lleva permisos**, así que no abre ninguna ruta del
    CRM: la puerta se cierra sola en vez de depender de que nadie monte una ruta
    sin `exige_permiso`.
  * Un token de empleado **no vale** como sesión de portal. Parece inofensivo
    —tiene más permisos, no menos— pero saltaría el filtro por nivel de acceso,
    que es lo único que decide qué ve cada contacto.
  * La sesión caduca y lo dice con su propio código, para que el portal sepa
    mandar a pedir otro enlace en vez de enseñar un error.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.errors import NoAutenticado
from crmcore.http.portal_deps import contexto_portal, emitir_token_portal


class _Peticion:
    """Lo mínimo que mira la dependencia: cabecera y cookies."""

    def __init__(self, cookies: dict[str, str] | None = None) -> None:
        self.cookies = cookies or {}


def test_la_sesion_del_portal_dice_quien_es(tenant_id: UUID) -> None:
    acceso = uuid4()
    token, dura = emitir_token_portal(acceso_id=acceso, tenant_id=tenant_id, nivel="cuenta")

    sesion = contexto_portal(_Peticion(), authorization=f"Bearer {token}")

    assert sesion.acceso_id == acceso
    assert sesion.tenant_id == tenant_id
    assert sesion.nivel == "cuenta"
    assert dura > 0


def test_el_token_del_portal_no_lleva_permisos(tenant_id: UUID) -> None:
    """Es lo que impide que sirva para el CRM: todas sus rutas exigen uno."""
    import jwt
    from crmcore.config import get_settings

    token, _ = emitir_token_portal(acceso_id=uuid4(), tenant_id=tenant_id, nivel="admin")
    s = get_settings()
    carga = jwt.decode(token, s.secret_key.get_secret_value(), algorithms=[s.jwt_algorithm])

    assert "permisos" not in carga
    assert "roles" not in carga
    assert carga["tipo"] == "portal"


def test_un_token_de_empleado_no_vale_como_sesion_de_portal(tenant_id: UUID) -> None:
    """Tiene más permisos, no menos, y por eso parece inofensivo. No lo es:
    saltaría el filtro por nivel de acceso, que es lo único que decide qué ve
    cada contacto."""
    import jwt
    from crmcore.config import get_settings

    s = get_settings()
    de_empleado = jwt.encode(
        {
            "sub": str(uuid4()),
            "tenant": str(tenant_id),
            "tipo": "usuario",
            "permisos": ["case:read"],
        },
        s.secret_key.get_secret_value(),
        algorithm=s.jwt_algorithm,
    )

    with pytest.raises(NoAutenticado) as fallo:
        contexto_portal(_Peticion(), authorization=f"Bearer {de_empleado}")

    assert fallo.value.error_code == "portal.sesion_no_es_de_portal"


def test_sin_sesion_se_dice_que_hay_que_entrar() -> None:
    with pytest.raises(NoAutenticado) as fallo:
        contexto_portal(_Peticion(), authorization=None)

    assert fallo.value.error_code == "portal.sin_sesion"


def test_una_sesion_caducada_manda_a_pedir_otro_enlace(tenant_id: UUID) -> None:
    """Con su propio código: el portal tiene que saber ofrecer otro enlace en
    vez de enseñar «no autenticado», que no dice qué hacer."""
    import time

    import jwt
    from crmcore.config import get_settings

    s = get_settings()
    caducado = jwt.encode(
        {
            "sub": str(uuid4()),
            "tenant": str(tenant_id),
            "tipo": "portal",
            "exp": int(time.time()) - 60,
        },
        s.secret_key.get_secret_value(),
        algorithm=s.jwt_algorithm,
    )

    with pytest.raises(NoAutenticado) as fallo:
        contexto_portal(_Peticion(), authorization=f"Bearer {caducado}")

    assert fallo.value.error_code == "portal.sesion_caducada"


def test_la_cookie_del_portal_es_otra_que_la_del_crm(tenant_id: UUID) -> None:
    """En el mismo navegador puede haber las dos —un comercial mirando el portal
    de su cliente— y compartir nombre haría que una pisara a la otra."""
    from crmcore.config import get_settings

    token, _ = emitir_token_portal(acceso_id=uuid4(), tenant_id=tenant_id, nivel="propio")
    nombre = f"{get_settings().sesion_cookie_nombre}_portal"

    sesion = contexto_portal(_Peticion({nombre: token}), authorization=None)

    assert sesion.tenant_id == tenant_id
    # Y la del CRM no sirve para entrar en el portal.
    with pytest.raises(NoAutenticado):
        contexto_portal(_Peticion({get_settings().sesion_cookie_nombre: token}), authorization=None)


def test_un_acceso_de_nivel_cuenta_sin_cuenta_se_rechaza(uow: Any) -> None:
    """Si no, el portal entra bien y sale vacío — que se lee como «no tengo
    casos» y no como «el acceso está mal dado»."""
    from crmcore.errors import ErrorValidacion

    from services.service import portal as prt

    with pytest.raises(ErrorValidacion) as fallo:
        prt.dar_acceso(uow, contacto_id=uuid4(), email="quien@example.com", nivel="cuenta")

    assert fallo.value.error_code == "service.acceso_portal_sin_cuenta"


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> Any:
    from crmcore.db.uow import UnidadDeTrabajo

    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)
