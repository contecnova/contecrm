"""`SAML_ENABLED` y `OIDC_ENABLED` no los leía nadie (`CRM-00.05.01.01`).

Medido el 06-10-2026 con el barrido de ajustes sin lector. Los dos existían,
estaban en `.env.example`, estaban en el manual de referencia y **de ahí no
pasaban**: poner `SAML_ENABLED=false` no apagaba nada. Se seguía pudiendo
configurar un proveedor SAML y se seguía pudiendo entrar por él.

Es la peor clase de fallo de seguridad: el que deja al administrador tranquilo.
No da error, no avisa, y desde fuera el sistema contesta exactamente lo que
contestaría si el interruptor funcionara.

**Son cuatro puertas, no una**, y cerrar sólo la primera habría sido peor que
no cerrar ninguna —porque parecería hecho—:

  · configurar un proveedor de ese protocolo;
  · empezar un inicio de sesión con uno ya configurado (apagar el interruptor
    no borra los proveedores que ya estaban, que son todos los que importan);
  · la vuelta de OIDC y la de SAML, que llegan minutos después: un flujo que
    empezó antes de apagarlo entraría igual.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from services.identity import sso


@pytest.fixture
def protocolos(request: Any) -> Any:
    """Enciende o apaga los dos protocolos, y lo deja como estaba."""
    from crmcore.config import limpiar_cache_settings

    saml, oidc = request.param
    previo = {k: os.environ.get(k) for k in ("SAML_ENABLED", "OIDC_ENABLED")}
    os.environ["SAML_ENABLED"] = "true" if saml else "false"
    os.environ["OIDC_ENABLED"] = "true" if oidc else "false"
    limpiar_cache_settings()
    try:
        yield
    finally:
        for k, v in previo.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        limpiar_cache_settings()


@pytest.mark.parametrize("protocolos", [(True, True)], indirect=True)
def test_encendidos_pasan(protocolos: Any) -> None:
    sso.exigir_protocolo_activo("saml")
    sso.exigir_protocolo_activo("oidc")


@pytest.mark.parametrize("protocolos", [(False, True)], indirect=True)
def test_apagado_corta_y_dice_con_qué_se_enciende(protocolos: Any) -> None:
    """Decir «no está activo» a secas obliga a quien administra a buscar el
    nombre del ajuste, y mientras lo busca prueba otras cosas."""
    from crmcore.errors import Prohibido

    with pytest.raises(Prohibido) as fallo:
        sso.exigir_protocolo_activo("saml")
    assert fallo.value.error_code == "sso.protocolo_desactivado"
    assert "SAML_ENABLED" in str(fallo.value)
    # Y el otro sigue entrando: el interruptor es por protocolo, no un apagón.
    sso.exigir_protocolo_activo("oidc")


@pytest.mark.parametrize("protocolos", [(True, True)], indirect=True)
def test_un_protocolo_que_nadie_enchufo_no_se_da_por_bueno(protocolos: Any) -> None:
    """Caer a «activo» con los dos encendidos dejaría a un protocolo nuevo sin
    interruptor, que es justo lo que esto viene a cerrar."""
    from crmcore.errors import Prohibido

    with pytest.raises(Prohibido) as fallo:
        sso.exigir_protocolo_activo("lo_que_sea")
    assert "saml, oidc" in str(fallo.value)


# ── Las cuatro puertas ────────────────────────────────────────────────────


def _puertas() -> dict[str, str]:
    """Cada puerta, con el trozo de código que tiene que estar delante.

    Se mira el código y no se recorre cada ruta porque dos de las cuatro
    —las vueltas— necesitan un proveedor real, una firma y un estado vivo, y
    montarlo aquí probaría el montaje. Lo que importa es que la comprobación
    esté ANTES de tocar nada, y eso sí se ve.
    """
    import pathlib

    raiz = pathlib.Path(__file__).resolve().parents[2]
    fuente = (raiz / "services" / "identity" / "api_sso.py").read_text(encoding="utf-8")
    return {
        "configurar": fuente.split("def crear(")[1].split("\ndef ")[0],
        "iniciar": fuente.split("def _iniciar(")[1].split("\ndef ")[0]
        if "def _iniciar(" in fuente
        else fuente.split("def iniciar(")[1].split("\ndef ")[0],
        "vuelta_oidc": fuente.split("def _callback_oidc(")[1].split("\ndef ")[0],
        "vuelta_saml": fuente.split("def _acs_saml(")[1].split("\ndef ")[0],
    }


@pytest.mark.parametrize("puerta", ["configurar", "iniciar", "vuelta_oidc", "vuelta_saml"])
def test_las_cuatro_puertas_preguntan(puerta: str) -> None:
    cuerpo = _puertas()[puerta]
    assert "exigir_protocolo_activo" in cuerpo, (
        f"la puerta «{puerta}» no comprueba si el protocolo está activo: "
        "apagar el interruptor no la cierra"
    )


def test_la_comprobacion_va_antes_de_tocar_la_base() -> None:
    """Comprobarlo al final deja escrito el estado del flujo —o el proveedor—
    antes de decir que no, y eso ensucia la tabla con intentos de un protocolo
    que está apagado."""
    cuerpo = _puertas()["vuelta_saml"]
    assert cuerpo.index("exigir_protocolo_activo") < cuerpo.index("proveedor_para")


def test_el_barrido_que_lo_encontro_sigue_sin_contarlos() -> None:
    """Si se arreglan y nadie los quita de la lista, el número miente a la baja
    y el trabajo hecho no se ve."""
    import importlib.util
    import pathlib

    raiz = pathlib.Path(__file__).resolve().parents[2]
    ruta = raiz / "tests" / "unit" / "test_un_ajuste_sin_lector_no_enciende_nada.py"
    spec = importlib.util.spec_from_file_location("barrido_ajustes_", ruta)
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)

    sin_lector = modulo._sin_lector()
    assert "saml_enabled" not in sin_lector
    assert "oidc_enabled" not in sin_lector


# ── SCIM: la puerta por la que un IdP crea y borra cuentas ────────────────


@pytest.fixture
def identity_arrancado() -> Any:
    """El servicio tal como se despliega, con su arranque.

    Sin el `with`, `TestClient` no ejecuta el ciclo de vida y se probaría una
    aplicación a medio arrancar — que es donde el servicio instala sus
    garantías, incluida ésta.
    """
    import importlib

    from crmcore.config import get_settings
    from starlette.testclient import TestClient

    previo = os.environ.get("OUTBOX_ENABLED")
    # El relevo del outbox comparte conexión con la sesión de la prueba y sus
    # `RELEASE SAVEPOINT` se cruzan con los de esta transacción.
    os.environ["OUTBOX_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        app = importlib.import_module("services.identity.main").app
        with TestClient(app) as cliente:
            yield cliente
    finally:
        if previo is None:
            os.environ.pop("OUTBOX_ENABLED", None)
        else:
            os.environ["OUTBOX_ENABLED"] = previo
        get_settings.cache_clear()


@pytest.fixture
def scim(request: Any) -> Any:
    from crmcore.config import limpiar_cache_settings

    previo = os.environ.get("SCIM_ENABLED")
    os.environ["SCIM_ENABLED"] = "true" if request.param else "false"
    limpiar_cache_settings()
    try:
        yield
    finally:
        if previo is None:
            os.environ.pop("SCIM_ENABLED", None)
        else:
            os.environ["SCIM_ENABLED"] = previo
        limpiar_cache_settings()


@pytest.mark.db
@pytest.mark.parametrize("scim", [False], indirect=True)
def test_scim_apagado_no_atiende_por_la_ruta_real(identity_arrancado: Any, scim: Any) -> None:
    """**Por la ruta de verdad.** Ninguna prueba de SCIM entraba por HTTP —las
    treinta y una llaman a las funciones—, así que una comprobación puesta en el
    router no la habría recorrido nadie y habría parecido hecha."""
    salida = identity_arrancado.get("/api/v1/scim/v2/ServiceProviderConfig")
    assert salida.status_code == 403, salida.text[:300]
    assert salida.json().get("errorCode") == "scim.desactivado"


@pytest.mark.db
@pytest.mark.parametrize("scim", [True], indirect=True)
def test_scim_encendido_atiende(identity_arrancado: Any, scim: Any) -> None:
    """La otra mitad: si apagado y encendido contestaran lo mismo, el 403 de
    arriba podría venir de cualquier otra cosa."""
    salida = identity_arrancado.get("/api/v1/scim/v2/ServiceProviderConfig")
    assert salida.status_code != 403, salida.text[:300]


def test_la_puerta_de_scim_esta_en_el_router_y_no_en_cada_ruta() -> None:
    """Trece rutas hoy; la que se escriba mañana heredaría el descuido."""
    import pathlib

    raiz = pathlib.Path(__file__).resolve().parents[2]
    fuente = (raiz / "services" / "identity" / "api_scim.py").read_text(encoding="utf-8")
    cabecera = fuente.split("router_scim = APIRouter(")[1].split(")")[0]
    assert "exigir_scim_activo" in cabecera


# ── MFA: apagarla no puede ser una forma de cerrar la puerta ──────────────


@pytest.fixture
def mfa(request: Any) -> Any:
    from crmcore.config import limpiar_cache_settings

    previo = os.environ.get("MFA_ENABLED")
    os.environ["MFA_ENABLED"] = "true" if request.param else "false"
    limpiar_cache_settings()
    try:
        yield
    finally:
        if previo is None:
            os.environ.pop("MFA_ENABLED", None)
        else:
            os.environ["MFA_ENABLED"] = previo
        limpiar_cache_settings()


@pytest.mark.db
@pytest.mark.parametrize("mfa", [False], indirect=True)
def test_mfa_apagada_no_atiende_por_la_ruta_real(identity_arrancado: Any, mfa: Any) -> None:
    salida = identity_arrancado.get("/api/v1/factores/nivel")
    assert salida.status_code == 403, salida.text[:300]
    assert salida.json().get("error_code") == "mfa.desactivada"


@pytest.mark.db
@pytest.mark.parametrize("mfa", [True], indirect=True)
def test_mfa_encendida_atiende(identity_arrancado: Any, mfa: Any) -> None:
    """Si apagada y encendida contestaran lo mismo, el 403 de arriba podría
    venir de cualquier otra cosa — del permiso, por ejemplo."""
    salida = identity_arrancado.get("/api/v1/factores/nivel")
    assert salida.status_code != 403 or salida.json().get("error_code") != "mfa.desactivada"


def test_apagar_la_mfa_no_deja_fuera_a_quien_ya_la_tenia() -> None:
    """**Es la mitad que importa.** Con el interruptor sólo en las rutas, un
    usuario con `mfa_activo` ya puesto seguiría necesitando un código y las
    rutas para conseguirlo estarían apagadas por ese mismo interruptor: apagar
    un segundo factor se convertiría en cerrarle la puerta a quien lo tenía."""
    import pathlib

    raiz = pathlib.Path(__file__).resolve().parents[2]
    fuente = (raiz / "services" / "identity" / "servicio.py").read_text(encoding="utf-8")
    linea = next(ln for ln in fuente.splitlines() if ln.strip().startswith("exige_mfa = "))
    assert "mfa_enabled" in linea, (
        "el inicio de sesión sigue exigiendo el segundo factor sin mirar si esta "
        f"instalación lo ofrece: {linea.strip()}"
    )


def test_el_ajuste_que_solo_podia_valer_true_ya_no_existe() -> None:
    """`SUPLANTACION_EXIGE_MOTIVO` no lo leía nadie y el motivo se exige
    siempre. Enchufarlo habría sido ofrecer apagar una garantía de auditoría;
    dejarlo habría sido mentir en los dos sentidos. Se quitó."""
    import pathlib

    raiz = pathlib.Path(__file__).resolve().parents[2]
    ajustes = (raiz / "packages/crmcore/crmcore/config_parts/_auth.py").read_text(encoding="utf-8")
    assert "suplantacion_exige_motivo: bool" not in ajustes
    # Y el motivo se sigue exigiendo, que es lo que justificaba quitarlo.
    svc = (raiz / "services/identity/servicio.py").read_text(encoding="utf-8")
    assert "auth.suplantacion_sin_motivo" in svc
