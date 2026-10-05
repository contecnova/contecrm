"""La reautenticación reforzada y la MFA adaptativa, EJERCITADAS
(CRM-00.05.01.18, CRM-00.05.01.19, CRM-00.05.01.21, CRM-00.05.01.22,
CRM-00.05.01.23, CRM-00.05.01.24).

Dos capacidades completas que **no aplicaban nada**.

La **lista de operaciones sensibles** existía, se publicaba en una ruta —«qué
operaciones exigen volver a verificarse»— y no la aplicaba nadie fuera de
`identity`. Y no se aplicaba por una razón concreta: la comprobación necesita
saber cuándo se superó el último factor fuerte, y esa fila vive en el esquema de
`identity`. Ningún servicio lee el esquema de otro, así que las tres operaciones
que ocurren fuera —exportar media base, borrar en bloque, restaurar encima de lo
actual— no tenían forma de comprobarlo. Lo que lo resuelve es propagar **la marca
y no la tabla**: va dentro del token y en las cabeceras firmadas, como los
permisos.

La **MFA adaptativa** estaba entera —seis señales, cada motivo explicado con
palabras— y no la llamaba nadie: el producto sabía decidir cuándo pedir el
segundo factor por el contexto y nunca se lo preguntaba.

Lo que se fija aquí es lo que distingue una comprobación de verdad de una que lo
parece: que corte, que corte **solo** lo que tiene que cortar, que no se la pueda
saltar nadie poniendo una cabecera, y que **diga lo que no ha podido mirar**.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from starlette.testclient import TestClient

pytestmark = pytest.mark.db


def _cabeceras(tenant_id: UUID, *, factor_hace_minutos: int | None = 0, **extra: str) -> Any:
    from crmcore.config import get_settings
    from crmcore.http.deps import (
        H_FACTOR_FUERTE,
        H_PERMISOS,
        H_ROLES,
        H_TENANT,
        H_TIPO,
        H_USER,
        firmar_cabeceras_internas,
    )

    valores = {
        H_TENANT: str(tenant_id),
        H_USER: str(uuid4()),
        H_PERMISOS: "*:*",
        H_ROLES: "admin",
        H_TIPO: "usuario",
        **extra,
    }
    if factor_hace_minutos is not None:
        valores[H_FACTOR_FUERTE] = (
            datetime.now(timezone.utc) - timedelta(minutes=factor_hace_minutos)
        ).isoformat()
    return firmar_cabeceras_internas(valores, get_settings().secret_key.get_secret_value())


@pytest.fixture
def cliente() -> Any:
    import importlib
    import os

    from crmcore.config import get_settings

    previo = os.environ.get("OUTBOX_ENABLED")
    os.environ["OUTBOX_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        modulo = importlib.import_module("services.sales.main")
        with TestClient(modulo.app) as cli:
            yield cli
    finally:
        if previo is None:
            os.environ.pop("OUTBOX_ENABLED", None)
        else:
            os.environ["OUTBOX_ENABLED"] = previo
        get_settings.cache_clear()


@pytest.fixture
def cliente_party() -> Any:
    import importlib
    import os

    from crmcore.config import get_settings

    previo = os.environ.get("OUTBOX_ENABLED")
    os.environ["OUTBOX_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        modulo = importlib.import_module("services.party.main")
        with TestClient(modulo.app) as cli:
            yield cli
    finally:
        if previo is None:
            os.environ.pop("OUTBOX_ENABLED", None)
        else:
            os.environ["OUTBOX_ENABLED"] = previo
        get_settings.cache_clear()


@pytest.fixture
def cliente_identidad(monkeypatch: Any) -> Any:
    import importlib
    import os

    from crmcore.config import get_settings

    # Los barridos periódicos de `identity` —desafíos de MFA caducados, estados
    # de SSO— abren su propia transacción contra la MISMA base que la prueba, y
    # al hacer rollback se llevan por delante el savepoint del caso: el síntoma
    # es un «savepoint sa_savepoint_2 does not exist» que no tiene nada que ver
    # con lo que se está probando. Se paran aquí y solo aquí: lo que se quiere
    # ejercitar son las rutas.
    async def _no_correr(self: Any) -> None:
        return None

    from crmcore.tareas import RelevoDeTareas

    monkeypatch.setattr(RelevoDeTareas, "correr", _no_correr)

    previo = os.environ.get("OUTBOX_ENABLED")
    os.environ["OUTBOX_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        modulo = importlib.import_module("services.identity.main")
        with TestClient(modulo.app) as cli:
            yield cli
    finally:
        if previo is None:
            os.environ.pop("OUTBOX_ENABLED", None)
        else:
            os.environ["OUTBOX_ENABLED"] = previo
        get_settings.cache_clear()


# ── La reverificación corta de verdad ─────────────────────────────────────


def test_exportar_sin_factor_reciente_se_corta(cliente: Any, tenant_id: UUID, db: Any) -> None:
    """La lista de operaciones sensibles existía y no aplicaba nada."""
    r = cliente.get(
        "/api/v1/opportunities/exportar", headers=_cabeceras(tenant_id, factor_hace_minutos=None)
    )
    assert r.status_code == 401, r.text
    salida = r.json()
    assert salida["error_code"] == "stepup.requerido"
    assert salida["detalle"]["operacion"] == "exportacion_masiva"
    # «Vuelve a verificarte» y «configúrate un segundo factor» son dos cosas
    # distintas para quien está delante de la pantalla.
    assert salida["detalle"]["tiene_factor"] is False


def test_un_factor_de_hace_ocho_horas_no_vale(cliente: Any, tenant_id: UUID, db: Any) -> None:
    """Que el nivel caduque antes que la sesión es todo el punto: una sesión dura
    horas, y una exportación a las seis no puede apoyarse en un factor de las
    nueve."""
    r = cliente.get(
        "/api/v1/opportunities/exportar",
        headers=_cabeceras(tenant_id, factor_hace_minutos=480),
    )
    assert r.status_code == 401, r.text
    assert r.json()["detalle"]["tiene_factor"] is True


def test_con_el_factor_recien_superado_se_exporta(cliente: Any, tenant_id: UUID, db: Any) -> None:
    r = cliente.get(
        "/api/v1/opportunities/exportar", headers=_cabeceras(tenant_id, factor_hace_minutos=1)
    )
    assert r.status_code == 200, r.text


def test_una_marca_ilegible_no_cuenta_como_verificacion(
    cliente: Any, tenant_id: UUID, db: Any
) -> None:
    """Dejarla pasar convertiría un error de formato en una puerta abierta."""
    from crmcore.http.deps import H_FACTOR_FUERTE

    r = cliente.get(
        "/api/v1/opportunities/exportar",
        headers=_cabeceras(tenant_id, factor_hace_minutos=None, **{H_FACTOR_FUERTE: "ayer"}),
    )
    assert r.status_code == 401, r.text
    assert r.json()["error_code"] == "stepup.requerido"


def test_la_marca_va_firmada_y_no_se_puede_poner_a_mano(
    cliente: Any, tenant_id: UUID, db: Any
) -> None:
    """Fuera de la firma, bastaría con decir «me acabo de verificar»."""
    from crmcore.http.deps import H_FACTOR_FUERTE

    cabeceras = dict(_cabeceras(tenant_id, factor_hace_minutos=None))
    # Se añade DESPUÉS de firmar: es lo que haría quien alcanzara la red interna.
    cabeceras[H_FACTOR_FUERTE] = datetime.now(timezone.utc).isoformat()

    r = cliente.get("/api/v1/opportunities/exportar", headers=cabeceras)
    assert r.status_code == 401, r.text
    assert r.json()["error_code"] == "auth.firma_interna_invalida"


def test_una_credencial_de_maquina_no_teclea_un_codigo(
    cliente: Any, tenant_id: UUID, db: Any
) -> None:
    """Tratarla como a una persona dejaría los procesos automáticos parados para
    siempre y sin nadie a quien pedirle el segundo factor."""
    from crmcore.http.deps import H_TIPO

    r = cliente.get(
        "/api/v1/opportunities/exportar",
        headers=_cabeceras(tenant_id, factor_hace_minutos=None, **{H_TIPO: "servicio"}),
    )
    assert r.status_code == 200, r.text


def test_solo_el_borrado_en_bloque_pide_el_factor(
    cliente_party: Any, tenant_id: UUID, db: Any
) -> None:
    """Pedirlo para todas las operaciones masivas obligaría a teclear el segundo
    factor para actualizar cien direcciones."""
    actualizar = cliente_party.post(
        "/api/v1/cuentas/masivo",
        headers=_cabeceras(tenant_id, factor_hace_minutos=None),
        json={"operacion": "actualizar", "elementos": []},
    )
    # Llega al 422 por lote vacío: lo que importa es que NO lo paró el factor.
    assert actualizar.status_code == 422, actualizar.text
    assert actualizar.json()["error_code"] == "masivo.lote_vacio"

    borrar = cliente_party.post(
        "/api/v1/cuentas/masivo",
        headers=_cabeceras(tenant_id, factor_hace_minutos=None),
        json={"operacion": "borrar", "elementos": []},
    )
    assert borrar.status_code == 401, borrar.text
    assert borrar.json()["error_code"] == "stepup.requerido"
    assert borrar.json()["detalle"]["operacion"] == "borrado_masivo"


def test_restaurar_encima_de_lo_actual_pide_el_factor(
    cliente: Any, tenant_id: UUID, db: Any
) -> None:
    r = cliente.post(
        "/api/v1/sales/restauracion",
        headers=_cabeceras(tenant_id, factor_hace_minutos=None),
        json={"objeto": "oportunidad", "ids": [str(uuid4())], "momento": "2026-01-01T00:00:00Z"},
    )
    assert r.status_code == 401, r.text
    assert r.json()["error_code"] == "stepup.requerido"


def test_una_operacion_no_declarada_no_se_puede_exigir() -> None:
    """La tabla es de datos: lo que no está en ella no se protege, y conviene que
    equivocarse de nombre dé un error y no un silencio."""
    from crmcore.errors import ErrorValidacion
    from crmcore.http.reverificacion import comprobar

    class _P:
        tipo = "usuario"
        factor_fuerte_at = ""

    with pytest.raises(ErrorValidacion) as fallo:
        comprobar(_P(), "borrar_el_universo")
    assert fallo.value.error_code == "stepup.operacion_desconocida"


# ── MFA adaptativa (CRM-00.05.01.21) ──────────────────────────────────────


def _usuario(db: Any, tenant_id: UUID, *, mfa: bool) -> Any:
    from services.identity.modelos import Membresia, Usuario
    from services.identity.servicio import hashear_contrasena

    usuario = Usuario(
        email=f"{uuid4().hex[:8]}@ejemplo.test",
        nombre="Ana Ruiz",
        hash_contrasena=hashear_contrasena("Contrasena-1"),
        mfa_activo=mfa,
    )
    db.add(usuario)
    db.flush()
    db.add(Membresia(tenant_id=tenant_id, usuario_id=usuario.id, roles=["admin"], activa=True))
    db.flush()
    return usuario


def test_el_contexto_nuevo_pide_el_segundo_factor(db: Any, tenant_id: UUID) -> None:
    """Pedir el factor cuando el contexto cambia es lo que detecta el robo de
    sesión, que es lo que la MFA de siempre no ve: una vez dentro, ya estás
    dentro."""
    from crmcore.errors import NoAutenticado

    from services.identity import factores as fa
    from services.identity.modelos import Sesion

    usuario = _usuario(db, tenant_id, mfa=True)
    # Una entrada anterior desde otra IP y otro equipo.
    db.add(
        Sesion(
            tenant_id=tenant_id,
            usuario_id=usuario.id,
            hash_refresco=uuid4().hex,
            ip="10.0.0.1",
            expira_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
    )
    db.flush()

    contexto = fa.contexto_de_entrada(db, usuario.id, tenant_id, ip="200.1.2.3", huella="")
    assert contexto["ip_conocida"] is False
    assert contexto["dispositivo_conocido"] is False

    riesgo = fa.evaluar_riesgo(**contexto)
    assert riesgo["exigir_factor"] is True
    assert "ip_nueva" in riesgo["motivos"]
    # Y con palabras, no con códigos: quien lo lee es una persona con prisa.
    assert riesgo["explicacion"].strip()
    assert "ip_nueva" not in riesgo["explicacion"]
    assert NoAutenticado  # el login lo convierte en 401; aquí se fija la decisión


def test_la_primera_entrada_no_es_sospechosa(db: Any, tenant_id: UUID) -> None:
    """Tratarla como riesgo pediría el factor a todo el mundo el día del alta,
    que es cuando menos configurado lo tiene."""
    from services.identity import factores as fa

    usuario = _usuario(db, tenant_id, mfa=True)
    contexto = fa.contexto_de_entrada(db, usuario.id, tenant_id, ip="200.1.2.3", huella="")
    assert contexto["ip_conocida"] is True
    assert contexto["dias_sin_entrar"] == 0


def test_lo_que_no_se_ha_podido_medir_se_dice(db: Any, tenant_id: UUID) -> None:
    """Sin localizador de IP, el país no se mide. Darlo por conocido haría que la
    señal más útil de las seis no saltara jamás y sin que nadie lo supiera."""
    from services.identity import factores as fa

    usuario = _usuario(db, tenant_id, mfa=True)
    contexto = fa.contexto_de_entrada(db, usuario.id, tenant_id, ip="200.1.2.3")
    assert contexto["pais_conocido"] is None

    riesgo = fa.evaluar_riesgo(**contexto)
    assert riesgo["senales_sin_medir"]
    assert "pais_nuevo" not in riesgo["motivos"]


def test_con_localizador_el_salto_imposible_salta(db: Any, tenant_id: UUID) -> None:
    """Dos países en dos horas: o hay un avión imposible o hay dos personas."""
    from services.identity import factores as fa
    from services.identity.modelos import Sesion

    usuario = _usuario(db, tenant_id, mfa=True)
    db.add(
        Sesion(
            tenant_id=tenant_id,
            usuario_id=usuario.id,
            hash_refresco=uuid4().hex,
            ip="10.0.0.1",
            expira_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
    )
    db.flush()

    try:
        fa.registrar_localizador(lambda ip: "ES" if str(ip).startswith("10.") else "BR")
        contexto = fa.contexto_de_entrada(db, usuario.id, tenant_id, ip="200.1.2.3")
        assert contexto["pais_conocido"] is False
        assert contexto["minutos_desde_otro_pais"] is not None

        riesgo = fa.evaluar_riesgo(**contexto)
        assert riesgo["sospechoso"] is True
        assert "salto_imposible" in riesgo["motivos"]
        # No se resuelve pidiendo un código: se resuelve mirando qué ha pasado.
        assert "sesiones" in riesgo["que_hacer_si_sospechoso"]
    finally:
        fa.registrar_localizador(None)


# ── Las decisiones de MFA que no se podían pedir ──────────────────────────


def test_un_solo_factor_no_es_tener_mfa(cliente_identidad: Any, tenant_id: UUID, db: Any) -> None:
    """Es tener un único punto de fallo: quien solo tiene el móvil y lo pierde se
    queda fuera, y entonces alguien de soporte lo desbloquea por teléfono."""
    r = cliente_identidad.get("/api/v1/factores/plan-de-inscripcion", headers=_cabeceras(tenant_id))
    assert r.status_code == 200, r.text
    salida = r.json()
    assert salida["completo"] is False
    # Y dice los pasos, no solo que falta algo.
    assert [p["paso"] for p in salida["pasos"]]
    assert all(p["porque"].strip() for p in salida["pasos"])


def test_sin_respaldo_el_cambio_de_movil_no_es_automatico(
    cliente_identidad: Any, tenant_id: UUID, db: Any
) -> None:
    """Y ninguno de los dos caminos es «llama a soporte»."""
    con = cliente_identidad.get(
        "/api/v1/factores/cambio-de-dispositivo" "?tiene_respaldo=true&factor_verificado=true",
        headers=_cabeceras(tenant_id),
    )
    assert con.status_code == 200, con.text
    assert con.json()["puede_solo"] is True
    assert con.json()["camino"] == "respaldo"

    sin = cliente_identidad.get(
        "/api/v1/factores/cambio-de-dispositivo" "?tiene_respaldo=false&factor_verificado=false",
        headers=_cabeceras(tenant_id),
    )
    assert sin.status_code == 200, sin.text
    assert sin.json()["puede_solo"] is False
    # Y el camino no es «llama a soporte»: es desbloqueo con dos aprobadores.
    assert sin.json()["porque"].strip()


def test_un_sms_no_vale_como_metodo_unico(cliente_identidad: Any, tenant_id: UUID, db: Any) -> None:
    """Se quita la contraseña y se deja lo más débil de los dos."""
    r = cliente_identidad.get(
        "/api/v1/factores/vale-como-unico"
        "?factor=sms&resistente_a_phishing=false&tiene_respaldo=true",
        headers=_cabeceras(tenant_id),
    )
    assert r.status_code == 200, r.text
    assert r.json()["puede"] is False

    llave = cliente_identidad.get(
        "/api/v1/factores/vale-como-unico"
        "?factor=passkey&resistente_a_phishing=true&tiene_respaldo=true",
        headers=_cabeceras(tenant_id),
    )
    assert llave.status_code == 200, llave.text
    assert llave.json()["puede"] is True


def test_el_perfil_de_un_proveedor_de_mfa_se_puede_resolver(
    cliente_identidad: Any, tenant_id: UUID, db: Any
) -> None:
    """La ruta de SSO existía y la de MFA no: equivocarse en cómo llama el
    proveedor a cada cosa no da un error, da un factor que no llega nunca."""
    from services.identity import sso

    clave = next(iter(sso.PERFILES_MFA))
    r = cliente_identidad.get(
        f"/api/v1/proveedores-identidad/perfiles-mfa/{clave}", headers=_cabeceras(tenant_id)
    )
    assert r.status_code == 200, r.text
    assert r.json()


def test_un_invitado_externo_caduca_y_lleva_motivo(
    cliente_identidad: Any, tenant_id: UUID, db: Any
) -> None:
    """Un invitado sin fecha es un usuario más, y el día que alguien revisa la
    lista aparecen quince personas que nadie recuerda haber invitado."""
    r = cliente_identidad.post(
        "/api/v1/usuarios/invitar-externo",
        headers=_cabeceras(tenant_id),
        json={
            "email": "auditor@externo.example",
            "motivo": "Auditoría de cuentas del ejercicio",
            "permisos": ["account:read"],
            "dias": 15,
        },
    )
    assert r.status_code == 201, r.text
    salida = r.json()
    assert salida["caduca_at"]
    assert salida["renovable"] is True
    assert salida["permisos"] == ["account:read"]

    sin_motivo = cliente_identidad.post(
        "/api/v1/usuarios/invitar-externo",
        headers=_cabeceras(tenant_id),
        json={"email": "otro@externo.example", "motivo": "", "permisos": ["account:read"]},
    )
    assert sin_motivo.status_code == 422, sin_motivo.text
