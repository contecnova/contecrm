"""Forzar SSO cierra **todas** las puertas, no la principal (`CRM-00.05.01.13`).

Forzar el SSO existe para una cosa: que dar de baja a alguien en el directorio
del cliente le corte el acceso de verdad. Con cualquier credencial local viva,
el SSO es una comodidad y no un control — quien se va del directorio sigue
entrando por la otra puerta, y esa puerta no la mira nadie.

Medido el 04-10-2026: de las **tres** puertas que abren sesión, solo una lo
comprobaba.

    /auth/login              contraseña   ✓ lo comprobaba
    /auth/passkeys/.../confirmar  passkey  ✗ NO lo comprobaba
    /auth/restablecer/confirmar   nueva contraseña  ✗ NO lo comprobaba

La passkey es la grave: es una credencial **local**, vive en el dispositivo y
en nuestra base, no en el directorio. Quien causa baja pierde el SSO y conserva
su passkey. Que sea más fuerte que una contraseña no cambia nada — lo que se
exige aquí no es fortaleza, es que la baja corte.

El restablecimiento es menos grave y más tonto: dejaba poner una contraseña
nueva que el login iba a rechazar siempre, así que el usuario acababa
convencido de que la escribe mal.

Y se comprueba **la otra mitad**: sin SSO forzado las tres puertas abren, y la
cuenta de rescate entra aunque esté forzado. Sin eso, un cambio que cerrara
todo pasaría igual — y dejar fuera al administrador de rescate un sábado con el
certificado del IdP caducado es cómo se acaba tocando la base a mano.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from crmcore.errors import Prohibido

pytestmark = pytest.mark.db


def _usuario(db: Any, tenant_id: UUID, email: str = "ana@cliente.com") -> Any:
    """Por la vía normal: `crear_usuario` crea también su membresía, y sin ella
    el login falla por otro motivo y la prueba diría lo que no es."""
    from crmcore.db.uow import UnidadDeTrabajo

    from services.identity import servicio as svc

    uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
    usuario = svc.crear_usuario(
        uow,
        tenant_id=tenant_id,
        email=email,
        nombre="Ana",
        contrasena="una-contrasena-larga",
        roles=[],
    )
    db.flush()
    return usuario


def _proveedor_que_fuerza(db: Any, tenant_id: UUID, *, rescate: list[str] | None = None) -> Any:
    from services.identity.modelos import ProveedorIdentidad

    fila = ProveedorIdentidad(
        tenant_id=tenant_id,
        nombre="Entra",
        tipo="oidc",
        config={"forzar_sso": True, "cuentas_de_rescate": rescate or []},
        dominios=["cliente.com"],
        activo=True,
    )
    db.add(fila)
    db.flush()
    return fila


# ── La puerta que ya lo comprobaba ────────────────────────────────────────


def test_la_contrasena_no_entra_con_el_sso_forzado(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    from services.identity.sso_gobierno import exigir_sso_si_toca

    usuario = _usuario(db, tenant_id)
    _proveedor_que_fuerza(db, tenant_id)

    with pytest.raises(Prohibido) as fallo:
        exigir_sso_si_toca(db, usuario, tenant_id)
    assert fallo.value.error_code == "sso.obligatorio"


# ── Las dos que no ────────────────────────────────────────────────────────


def test_la_passkey_tampoco_entra_con_el_sso_forzado(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """La vía de escape de verdad: una credencial local que sobrevive a la baja.

    Se mira el código de la ruta además del comportamiento: lo que faltaba no
    era la comprobación —existía— sino que esta puerta la llamara.
    """
    import inspect

    from services.identity import api

    # SE BUSCA LA LLAMADA, no el nombre. La primera versión miraba
    # «exigir_sso_si_toca» a secas y la línea del `import` ya la contiene: al
    # quitar la llamada de verdad, la prueba seguía en verde. Una sonda que
    # confunde importar con llamar da por puesto un control que no se ejecuta.
    fuente = inspect.getsource(api.entrar_con_passkey)
    assert "exigir_sso_si_toca(db, usuario, tenant_id)" in fuente, (
        "la entrada con passkey no comprueba el SSO forzado: quien causa baja "
        "en el directorio conserva su passkey y sigue entrando, que es lo único "
        "que forzar el SSO viene a impedir"
    )


def test_restablecer_no_deja_poner_contrasena_con_el_sso_forzado(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Dejaba ponerla y el login la rechazaba siempre: «sin contraseña local»
    tiene que valer también para la puerta que las crea."""
    from crmcore.db.uow import UnidadDeTrabajo

    from services.identity import restablecer as rst

    usuario = _usuario(db, tenant_id)
    _proveedor_que_fuerza(db, tenant_id)
    uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
    token = rst.solicitar(uow, email=usuario.email)
    db.flush()

    with pytest.raises(Prohibido) as fallo:
        rst.confirmar(db, token, contrasena="otra-contrasena-larga")
    assert fallo.value.error_code == "restablecer.sso_obligatorio"


# ── Y la otra mitad: sin forzar, y con cuenta de rescate ──────────────────


def test_sin_sso_forzado_la_contrasena_entra(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Sin esto, un cambio que cerrara todas las puertas pasaría igual."""
    from services.identity.sso_gobierno import exigir_sso_si_toca

    usuario = _usuario(db, tenant_id)
    exigir_sso_si_toca(db, usuario, tenant_id)  # no lanza


def test_sin_sso_forzado_se_puede_restablecer(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    from crmcore.db.uow import UnidadDeTrabajo

    from services.identity import restablecer as rst

    usuario = _usuario(db, tenant_id)
    uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
    token = rst.solicitar(uow, email=usuario.email)
    db.flush()

    assert rst.confirmar(db, token, contrasena="otra-contrasena-larga") == usuario.id


def test_la_cuenta_de_rescate_entra_y_queda_escrito(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Sin ninguna excepción, un certificado caducado un sábado deja al cliente
    fuera de su propio CRM y la salida acaba siendo tocar la base a mano.

    Pero la excepción **se audita**: una que no se ve deja de ser una excepción
    y pasa a ser la puerta de siempre.
    """
    from crmcore.audit.modelos import ApunteAuditoria
    from sqlalchemy import select

    from services.identity.sso_gobierno import exigir_sso_si_toca

    usuario = _usuario(db, tenant_id, email="rescate@cliente.com")
    _proveedor_que_fuerza(db, tenant_id, rescate=["rescate@cliente.com"])

    exigir_sso_si_toca(db, usuario, tenant_id)  # no lanza
    db.flush()

    acciones = [
        a.accion
        for a in db.execute(select(ApunteAuditoria).where(ApunteAuditoria.tenant_id == tenant_id))
        .scalars()
        .all()
    ]
    assert "sso.rescate_usado" in acciones, f"la entrada de rescate no ha dejado apunte: {acciones}"


def test_una_cuenta_que_no_es_de_rescate_no_se_cuela(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """La lista es nominal: estar en el mismo tenant no basta."""
    from services.identity.sso_gobierno import exigir_sso_si_toca

    otro = _usuario(db, tenant_id, email="otro@cliente.com")
    _proveedor_que_fuerza(db, tenant_id, rescate=["rescate@cliente.com"])

    with pytest.raises(Prohibido):
        exigir_sso_si_toca(db, otro, tenant_id)


def _sin_imports(fuente: str) -> str:
    """El cuerpo sin sus líneas de `import`.

    Hace falta porque `from ... import exigir_sso_si_toca` contiene el nombre
    de la función, así que buscarlo a secas da por comprobada una puerta que
    solo lo importa. Se descubrió mutando: quitada la llamada, la prueba
    seguía verde.
    """
    return "\n".join(
        linea for linea in fuente.splitlines() if not linea.strip().startswith(("import ", "from "))
    )


def test_no_queda_ninguna_puerta_sin_comprobar() -> None:
    """Las tres que abren sesión, contadas.

    Una puerta nueva que no lo compruebe es exactamente cómo se vuelve a abrir
    la vía de escape, y no falla nada: simplemente entra quien no debería.
    """
    import inspect

    from services.identity import api, restablecer
    from services.identity import servicio as svc

    puertas = {
        "contraseña": inspect.getsource(svc.autenticar),
        "passkey": inspect.getsource(api.entrar_con_passkey),
        "restablecer": inspect.getsource(restablecer.confirmar),
    }
    # Las LLAMADAS, con su paréntesis: el nombre suelto lo trae el `import`.
    sin_comprobar = [
        nombre
        for nombre, fuente in puertas.items()
        if "exigir_sso_si_toca(" not in _sin_imports(fuente)
        and "puede_tener_contrasena_local(" not in _sin_imports(fuente)
    ]
    assert not sin_comprobar, (
        f"estas puertas abren sesión sin mirar el SSO forzado: {sin_comprobar}. "
        "Forzar el SSO vale lo que valga la puerta más floja."
    )
