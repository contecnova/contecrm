"""Una preferencia que sólo puede cambiarte un administrador no la cambia nadie.

El idioma, el formato de fecha, la zona horaria y la densidad de la interfaz
están declarados **hasta el ámbito de usuario** desde el principio: la jerarquía
de ajustes termina en «usuario» precisamente para esto. Pero la única ruta que
fijaba un ajuste exigía `tenant:write`, así que en la práctica la cadena se
cortaba un escalón antes: un comercial no va a abrir un ticket para que le
cambien el formato de fecha, y la preferencia personal no existía.

Aquí se comprueba la ruta que lo arregla, y sobre todo **lo que no puede hacer**:
el ámbito lo pone el servidor y no el cuerpo de la petición.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from starlette.testclient import TestClient

pytestmark = pytest.mark.db


@pytest.fixture
def cliente(db: Any) -> Any:
    """El cliente HTTP, **atado al esquema de pruebas**.

    `db` no se usa dentro, y aun así tiene que estar: sin él esta fixture se
    construye antes de que se levante el Postgres embebido, la aplicación crea
    su motor contra el 5432 de la máquina y todas las pruebas fallan con
    «Connection refused» — un fallo que parece de entorno y es de orden.
    """
    import importlib
    import os

    from crmcore.config import get_settings

    previo = os.environ.get("OUTBOX_ENABLED")
    os.environ["OUTBOX_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        modulo = importlib.import_module("services.tenancy.main")
        with TestClient(modulo.app) as cli:
            yield cli
    finally:
        if previo is None:
            os.environ.pop("OUTBOX_ENABLED", None)
        else:
            os.environ["OUTBOX_ENABLED"] = previo
        get_settings.cache_clear()


def _cabeceras(tenant_id: UUID, usuario: UUID, permisos: str) -> dict[str, str]:
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
            H_PERMISOS: permisos,
            H_ROLES: "comercial",
            H_FACTOR_FUERTE: datetime.now(timezone.utc).isoformat(),
        },
        get_settings().secret_key.get_secret_value(),
    )


# ── Qué cuenta como preferencia personal ──────────────────────────────────


def test_el_criterio_sale_de_la_declaracion_no_de_una_lista() -> None:
    """Si fuera una lista escrita a mano, la siguiente clave que alguien declare
    por usuario se quedaría fuera **sin avisar**: la preferencia simplemente no
    se podría guardar y nadie sabría por qué."""
    from crmcore.runtime.keys import CLAVES, es_preferencia_personal

    personales = {c for c in CLAVES if es_preferencia_personal(c)}
    # Exactamente las que la declaración marca con ámbito de usuario y sin
    # sensibilidad. Se recalcula aquí en vez de copiarse para que el día que
    # alguien añada una, esta prueba no sea la que haya que acordarse de tocar.
    esperadas = {
        c.clave for c in CLAVES.values() if c.minimo_ambito == "usuario" and not c.sensible
    }
    assert personales == esperadas
    assert len(personales) >= 4, f"sólo se ven {len(personales)}: el recorrido no está mirando"
    assert "ui_densidad" in personales


def test_lo_sensible_queda_fuera_aunque_sea_de_usuario() -> None:
    """Es la salida de emergencia, y tiene que funcionar: lo que un día tenga
    sentido por usuario pero deba ponerlo un administrador —una exención, un
    permiso ampliado— se marca sensible y se queda en la consola."""
    from dataclasses import replace

    from crmcore.runtime.keys import CLAVES, es_preferencia_personal

    idioma = CLAVES["idioma"]
    assert es_preferencia_personal("idioma")
    # El mismo ajuste, marcado sensible, deja de serlo.
    assert replace(idioma, sensible=True).minimo_ambito == "usuario"
    CLAVES["idioma"] = replace(idioma, sensible=True)
    try:
        assert not es_preferencia_personal("idioma")
    finally:
        CLAVES["idioma"] = idioma


def test_un_tope_de_instalacion_no_es_personal() -> None:
    from crmcore.runtime.keys import es_preferencia_personal

    assert not es_preferencia_personal("sso_estado_ttl_s")
    assert not es_preferencia_personal("una_clave_que_no_existe")


# ── Por la ruta de verdad ─────────────────────────────────────────────────


def test_quien_no_administra_puede_cambiar_la_suya(
    cliente: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """**Es el fallo entero.** Con `tenant:write` exigido, esto era un 403 y la
    preferencia no existía para quien la quería."""
    usuario = uuid4()
    cab = _cabeceras(tenant_id, usuario, "account:read")

    puesta = cliente.put(
        "/api/v1/mis-preferencias/ui_densidad", json={"valor": "comoda"}, headers=cab
    )
    assert puesta.status_code == 200, puesta.text
    assert puesta.json() == {"clave": "ui_densidad", "valor": "comoda", "ambito": "usuario"}

    vistas = cliente.get("/api/v1/mis-preferencias", headers=cab)
    assert vistas.status_code == 200, vistas.text
    assert vistas.json()["ui_densidad"]["valor"] == "comoda"
    # Y dice de dónde sale: sin eso, quien ve un valor que no ha puesto no sabe
    # si es el defecto del despliegue o algo que le han fijado.
    assert vistas.json()["ui_densidad"]["origen"] == "usuario"


def test_sin_haber_elegido_nada_sale_el_defecto_del_despliegue(
    cliente: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Y sale marcado como del entorno, no como suyo: ver «comoda» puesto por ti
    cuando no lo has tocado es lo que hace que nadie entienda la pantalla."""
    cab = _cabeceras(tenant_id, uuid4(), "account:read")
    ficha = cliente.get("/api/v1/mis-preferencias", headers=cab).json()["ui_densidad"]
    assert ficha["valor"] == "compacta"
    assert ficha["origen"] == "entorno"
    # Y viaja con qué se puede elegir, para que la pantalla no tenga que
    # repetir la lista: dos listas de opciones acaban no coincidiendo.
    assert ficha["opciones"] == ["compacta", "comoda"]


def test_la_mia_no_le_cambia_la_suya_a_nadie(
    cliente: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Una preferencia que se le aplica a otro no es una preferencia."""
    ana, luis = uuid4(), uuid4()
    cliente.put(
        "/api/v1/mis-preferencias/ui_densidad",
        json={"valor": "comoda"},
        headers=_cabeceras(tenant_id, ana, "account:read"),
    )
    suya = cliente.get(
        "/api/v1/mis-preferencias", headers=_cabeceras(tenant_id, luis, "account:read")
    ).json()
    assert suya["ui_densidad"]["valor"] == "compacta"
    assert suya["ui_densidad"]["origen"] == "entorno"


def test_el_cuerpo_no_puede_elegir_el_ambito(
    cliente: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """**La pieza que hace que esto sea seguro.**

    Si el ámbito viajara en el cuerpo, cualquiera con una cuenta normal
    cambiaría la densidad —o el idioma— de todo el tenant mandando
    `ambito: "tenant"`. Se manda a propósito y se comprueba que no pasa nada:
    el campo sobra, y lo que se guarda es lo del usuario.
    """
    ana, luis = uuid4(), uuid4()
    puesta = cliente.put(
        "/api/v1/mis-preferencias/ui_densidad",
        json={"valor": "comoda", "ambito": "tenant", "ambito_id": str(tenant_id)},
        headers=_cabeceras(tenant_id, ana, "account:read"),
    )
    assert puesta.status_code == 200, puesta.text
    assert puesta.json()["ambito"] == "usuario"
    # Y lo que importa: a Luis no le ha llegado nada.
    otro = cliente.get(
        "/api/v1/mis-preferencias", headers=_cabeceras(tenant_id, luis, "account:read")
    ).json()
    assert otro["ui_densidad"]["valor"] == "compacta", "se ha fijado en el tenant"


def test_una_palanca_de_la_instalacion_se_rechaza_y_se_dice_donde_va(
    cliente: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """«No se puede» a secas manda a mirar los permisos cuando el problema es
    que esa clave no es de nadie en particular."""
    respuesta = cliente.put(
        "/api/v1/mis-preferencias/sso_estado_ttl_s",
        json={"valor": 120},
        headers=_cabeceras(tenant_id, uuid4(), "account:read"),
    )
    assert respuesta.status_code == 422, respuesta.text
    assert "consola de ajustes" in respuesta.text


def test_un_valor_fuera_de_las_opciones_no_entra(
    cliente: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """La validación es la del catálogo, no una nueva: dos validaciones del
    mismo campo acaban admitiendo cosas distintas."""
    respuesta = cliente.put(
        "/api/v1/mis-preferencias/ui_densidad",
        json={"valor": "gigante"},
        headers=_cabeceras(tenant_id, uuid4(), "account:read"),
    )
    assert respuesta.status_code == 422, respuesta.text


def test_solo_salen_las_personales(cliente: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """La consola entera tiene cientos de ajustes. Enseñárselos a quien sólo
    puede cambiar cinco es la forma más rápida de que no cambie ninguno."""
    from crmcore.runtime.keys import CLAVES

    vistas = cliente.get(
        "/api/v1/mis-preferencias", headers=_cabeceras(tenant_id, uuid4(), "account:read")
    ).json()
    assert 4 <= len(vistas) < len(CLAVES) / 10, f"{len(vistas)} de {len(CLAVES)}"
    assert "sso_estado_ttl_s" not in vistas
