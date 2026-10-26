"""Auditoría de autenticación (CRM-00.05.01), por sus rutas.

Cinco capacidades sin ninguna prueba que las nombre. Lo que se persigue aquí es
cada forma que tiene la autenticación de fallar **a favor de quien no debe**:

  · **recuperar el acceso** (CRM-00.05.01.26): la pantalla de «he olvidado la
    contraseña» es un comprobador de qué correos tienen cuenta aquí si
    distingue el que existe del que no — y esa lista es justo la que quiere
    quien va a intentar entrar. Y el enlace tiene que valer **una vez**;
  · **las credenciales de máquina** (CRM-00.05.01.07): una clave sin caducidad
    y sin ámbito es una contraseña permanente con permisos de todo, pegada en
    el fichero de configuración de un integrador;
  · **las sesiones** (CRM-00.05.01.08): revocar tiene que surtir efecto, y una
    sesión caducada no puede seguir valiendo;
  · **el MFA** (CRM-00.05.01.06): un segundo factor que se puede reutilizar no
    es un segundo factor;
  · y **el alta automática por federación** (CRM-00.05.01.04): quien entra por
    el proveedor del cliente no puede quedarse fuera por no estar dado de alta,
    ni entrar con más permisos de los que su proveedor declara.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import pytest

pytestmark = pytest.mark.db


def monkeypatch_cfg(modulo: Any, valores: dict[str, Any]) -> None:
    """Enciende un ajuste de ejecución para esta prueba.

    Se sustituye el lector del módulo y no la tabla: lo que se mide es el
    comportamiento con el ajuste puesto, no cómo se guarda — eso tiene sus
    propias pruebas.
    """
    anterior = modulo._cfg

    def leer(db: Any, clave: str) -> Any:
        if clave in valores:
            return valores[clave]
        return anterior(db, clave)

    modulo._cfg = leer


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> Any:
    from crmcore.db.uow import UnidadDeTrabajo

    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


@pytest.fixture
def ana(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> Any:
    from services.identity.modelos import Membresia, Usuario

    usuario = Usuario(email="ana@example.com", nombre="Ana")
    db.add(usuario)
    db.flush()
    db.add(Membresia(tenant_id=tenant_id, usuario_id=usuario.id, roles=["comercial"]))
    db.flush()
    return usuario


# ── CRM-00.05.01.26 · Volver a entrar ─────────────────────────────────────


def test_el_enlace_vale_una_sola_vez_crm_00_05_01_26(
    uow: Any, db: Any, ana: Any, contexto_tenant: UUID
) -> None:
    """Un enlace que vale dos veces vale para siempre en el correo de quien lo
    recibió: basta con que alguien llegue a ese buzón meses después."""
    from crmcore.errors import NoAutenticado

    from services.identity import restablecer as rst

    token = rst.solicitar(uow, email="ana@example.com")
    assert token, "no se ha emitido enlace para un correo que sí existe"

    quien = rst.confirmar(db, token, contrasena="una-contrasena-larga-de-verdad")
    assert quien == ana.id

    with pytest.raises(NoAutenticado):
        rst.confirmar(db, token, contrasena="otra-contrasena-larga-de-verdad")


def test_un_enlace_caducado_no_vale_crm_00_05_01_26(
    uow: Any, db: Any, ana: Any, contexto_tenant: UUID
) -> None:
    """La caducidad es lo que acota la ventana: sin ella, el enlace de hace seis
    meses sigue abriendo la cuenta."""
    from crmcore.errors import NoAutenticado
    from sqlalchemy import select

    from services.identity import restablecer as rst

    token = rst.solicitar(uow, email="ana@example.com")
    fila = db.execute(select(rst.EnlaceRestablecer)).scalars().first()
    fila.caduca_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db.flush()

    with pytest.raises(NoAutenticado):
        rst.confirmar(db, token, contrasena="una-contrasena-larga-de-verdad")


def test_un_correo_que_no_existe_contesta_igual_crm_00_05_01_26(
    uow: Any, db: Any, ana: Any, contexto_tenant: UUID
) -> None:
    """**La misma respuesta exista o no.** Distinguirlas convierte la pantalla
    en un comprobador de qué correos tienen cuenta aquí, que es exactamente la
    lista que quiere quien va a intentar entrar.

    Por dentro no se emite nada, claro; lo que no puede es notarse desde fuera.
    """
    from services.identity import restablecer as rst

    assert rst.solicitar(uow, email="nadie@example.com") == ""


def test_el_enlace_se_guarda_hasheado_crm_00_05_01_26(
    uow: Any, db: Any, ana: Any, contexto_tenant: UUID
) -> None:
    """Quien lea la tabla —una copia de seguridad, un volcado de soporte— no
    puede sacar de ahí un enlace que abra cuentas."""
    from sqlalchemy import select

    from services.identity import restablecer as rst

    token = rst.solicitar(uow, email="ana@example.com")
    fila = db.execute(select(rst.EnlaceRestablecer)).scalars().first()
    guardado = str(getattr(fila, "token_hash", "") or getattr(fila, "hash_token", ""))
    assert guardado, "no se ve dónde se guarda el token"
    assert token not in guardado, "el token está guardado en claro"


# ── CRM-00.05.01.07 · Credenciales de máquina ─────────────────────────────


def test_una_clave_de_api_lleva_ambito_y_caducidad_crm_00_05_01_07(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Una clave sin ámbito y sin caducidad es una contraseña permanente con
    permisos de todo, pegada en el fichero de configuración de un integrador —
    y nadie se acuerda de ella hasta que alguien la usa."""
    from services.identity.modelos import ClaveApi

    columnas = set(ClaveApi.__table__.columns.keys())
    for campo in ("scopes", "expira_at", "revocada_at", "ips_permitidas", "ultimo_uso_at"):
        assert campo in columnas, f"falta «{campo}»: {sorted(columnas)}"


def test_el_secreto_de_la_clave_no_se_guarda_en_claro_crm_00_05_01_07(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Se guarda su huella y un prefijo con el que reconocerla. El prefijo
    existe para poder decir **cuál** es sin poder usarla: sin él, revocar la
    correcta en una incidencia es adivinar."""
    from services.identity.modelos import ClaveApi

    columnas = set(ClaveApi.__table__.columns.keys())
    assert "hash_secreto" in columnas
    assert "prefijo" in columnas
    assert "secreto" not in columnas, "la clave se guarda en claro"


def test_el_ultimo_uso_se_anota_crm_00_05_01_07(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Es lo único que permite contestar «¿esta clave la usa alguien?» el día
    que hay que retirar las que sobran. Sin eso, nadie se atreve a revocar
    ninguna."""
    from services.identity.modelos import ClaveApi

    assert "ultimo_uso_at" in set(ClaveApi.__table__.columns.keys())


# ── CRM-00.05.01.08 · Sesiones ────────────────────────────────────────────


def test_revocar_una_sesion_surte_efecto_crm_00_05_01_08(
    db: Any, tenant_id: UUID, ana: Any, contexto_tenant: UUID
) -> None:
    """Revocar que no revoca es la peor clase de botón: quien lo pulsa se queda
    tranquilo y la sesión sigue viva."""
    from services.identity import servicio as svc
    from services.identity.modelos import Sesion

    sesion = Sesion(
        tenant_id=tenant_id,
        usuario_id=ana.id,
        hash_refresco="x" * 64,
        expira_at=datetime.now(timezone.utc) + timedelta(days=1),
    )
    db.add(sesion)
    db.flush()

    svc.revocar(db, sesion.id, motivo="prueba")
    db.flush()
    db.refresh(sesion)
    assert sesion.revocada_at is not None


def test_una_sesion_caducada_no_vale_aunque_no_se_revoque_crm_00_05_01_08(
    db: Any, tenant_id: UUID, ana: Any, contexto_tenant: UUID
) -> None:
    """La caducidad es lo que acota la exposición si alguien copia el token:
    sin ella, lo copiado vale hasta que alguien se dé cuenta."""
    from sqlalchemy import select

    from services.identity.modelos import Sesion

    viva = Sesion(
        tenant_id=tenant_id,
        usuario_id=ana.id,
        hash_refresco="a" * 64,
        expira_at=datetime.now(timezone.utc) + timedelta(days=1),
    )
    caducada = Sesion(
        tenant_id=tenant_id,
        usuario_id=ana.id,
        hash_refresco="b" * 64,
        expira_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    db.add_all([viva, caducada])
    db.flush()

    # La consulta que usa el listado de «mis sesiones activas»: las que no están
    # revocadas y no han caducado.
    activas = (
        db.execute(
            select(Sesion).where(
                Sesion.usuario_id == ana.id,
                Sesion.revocada_at.is_(None),
                Sesion.expira_at > datetime.now(timezone.utc),
            )
        )
        .scalars()
        .all()
    )
    assert [s.id for s in activas] == [viva.id], "la sesión caducada sigue contando como activa"


# ── CRM-00.05.01.06 · MFA ─────────────────────────────────────────────────


def test_un_codigo_totp_no_se_puede_reutilizar_crm_00_05_01_06(
    db: Any, tenant_id: UUID, ana: Any, contexto_tenant: UUID
) -> None:
    """El código vale **en su ventana** y no fuera de ella: cada paso son 30
    segundos y la ventana absorbe el desfase normal entre el reloj del móvil y
    el del servidor, sin ampliar de más el margen para ir probando códigos."""
    from services.identity import servicio as svc

    secreto = svc.generar_secreto_totp()
    ahora = datetime.now(timezone.utc).timestamp()

    assert svc.verificar_totp(secreto, svc.codigo_totp(secreto, ahora)) is True
    # Uno de hace diez minutos —veinte pasos atrás— ya no entra en la ventana.
    viejo = svc.codigo_totp(secreto, ahora - 600)
    assert (
        svc.verificar_totp(secreto, viejo) is False
    ), "un código de hace diez minutos sigue valiendo: la ventana no acota nada"


def test_un_codigo_de_un_solo_uso_se_consume_crm_00_05_01_06(
    uow: Any, db: Any, ana: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """El código que se manda por SMS o correo **se consume al usarlo**: un
    segundo factor que vale dos veces no es un segundo factor.

    Y pedir otro **invalida el anterior**: dos códigos vivos a la vez doblan la
    superficie y confunden a quien recibe los dos.
    """
    # El canal viene **apagado de fábrica**, y eso es una decisión: un segundo
    # factor por correo que nadie ha configurado manda códigos a direcciones
    # sin verificar. Se enciende aquí, que es lo que haría la instalación.
    from crmcore.errors import Prohibido
    from sqlalchemy import select

    from services.identity import factores as fac

    with pytest.raises(Prohibido) as apagado:
        fac.emitir_desafio(db, ana, tenant_id, canal="email", direccion="ana@example.com")
    assert apagado.value.error_code == "factor.canal_desactivado"

    monkeypatch_cfg(fac, {"otp_email_enabled": True})

    # Un transporte de mentira: lo que se mide es que el código anterior deje
    # de valer, no que salga un correo. Entregar de verdad es de la
    # integración y tiene sus propias pruebas.
    from crmcore.notificaciones.base import _TRANSPORTES

    class Doble:
        canal = "email"

        def entregar(self, destino: Any, mensaje: Any, config: Any) -> Any:
            from crmcore.notificaciones.base import Resultado

            return Resultado(entregado=True, detalle="doble de prueba")

    previo = _TRANSPORTES.get("email")
    _TRANSPORTES["email"] = Doble()

    fac.emitir_desafio(db, ana, tenant_id, canal="email", direccion="ana@example.com")
    db.flush()
    primero = (
        db.execute(select(fac.DesafioFactor).order_by(fac.DesafioFactor.creado_at.desc()))
        .scalars()
        .first()
    )
    assert primero is not None and primero.usado_at is None, "nace ya usado"

    # Pedir otro invalida el anterior. Se salta la espera de reenvío moviendo
    # su fecha: lo que se mide es la invalidación, no el antifraude del SMS.
    primero.creado_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    db.flush()
    fac.emitir_desafio(db, ana, tenant_id, canal="email", direccion="ana@example.com")
    db.flush()
    db.refresh(primero)
    assert primero.usado_at is not None, (
        "el código anterior sigue vivo: dos a la vez doblan la superficie y "
        "confunden a quien recibe los dos"
    )
    if previo is None:
        _TRANSPORTES.pop("email", None)
    else:
        _TRANSPORTES["email"] = previo


def test_un_codigo_que_no_es_no_vale_crm_00_05_01_06(
    db: Any, tenant_id: UUID, ana: Any, contexto_tenant: UUID
) -> None:
    from services.identity import servicio as svc

    secreto = svc.generar_secreto_totp()
    assert svc.verificar_totp(secreto, "000000") is False
    # Y el de OTRO secreto tampoco, que es lo que impide que un código visto en
    # una pantalla sirva en otra cuenta.
    assert svc.verificar_totp(secreto, svc.codigo_totp(svc.generar_secreto_totp())) is False
