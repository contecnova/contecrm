"""Recuperar el acceso sin que sirva para averiguar quién tiene cuenta.

Sin esto, olvidar la contraseña era un billete de ida: la única salida era que
alguien de dentro la cambiara a mano, y eso produce contraseñas dictadas por
teléfono y administradores que acaban poniendo la misma para todos.

Lo que estas pruebas defienden:

  * Un correo que no existe **no se distingue** de uno que sí: si se
    distinguiera, esta pantalla sería un comprobador de qué correos tienen
    cuenta aquí.
  * El enlace vale **una vez** y caduca.
  * Al usarlo se **cierran todas las sesiones**: quien pide restablecer no
    puede entrar, o sospecha, y dejar abiertas las que había es dejar dentro a
    quien lo motivó.
  * El token se guarda hasheado, así que leer la base no da acceso.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.errors import ErrorValidacion, NoAutenticado


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> Any:
    from crmcore.db.uow import UnidadDeTrabajo

    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


@pytest.fixture
def usuario(uow: Any, tenant_id: UUID) -> Any:
    from services.identity import servicio as svc
    from services.identity.modelos import Usuario

    # Un usuario no lleva tenant: es global y su pertenencia la dice la
    # membresía. Es lo que permite que la misma persona esté en dos empresas.
    fila = Usuario(
        email="quien@empresa.example",
        nombre="Quien Olvida",
        hash_contrasena=svc.hashear_contrasena("LaDeSiempre.2026"),
        activo=True,
    )
    uow.db.add(fila)
    uow.db.flush()
    from services.identity.modelos import Membresia

    uow.db.add(Membresia(tenant_id=tenant_id, usuario_id=fila.id, activa=True))
    uow.db.flush()
    return fila


def test_un_correo_desconocido_no_se_distingue(uow: Any) -> None:
    """Devuelve vacío en vez de fallar, y quien llama contesta lo mismo en los
    dos casos. Distinguirlo es filtrar quién tiene cuenta."""
    from services.identity import restablecer as rst

    assert rst.solicitar(uow, email="nadie@ninguna.example") == ""


def test_el_enlace_cambia_la_contrasena(uow: Any, usuario: Any) -> None:
    from services.identity import restablecer as rst
    from services.identity import servicio as svc

    token = rst.solicitar(uow, email=usuario.email)
    assert token

    rst.confirmar(uow.db, token, contrasena="UnaNuevaDeVerdad.2026")

    assert svc.verificar_contrasena(usuario.hash_contrasena, "UnaNuevaDeVerdad.2026")
    assert not svc.verificar_contrasena(usuario.hash_contrasena, "LaDeSiempre.2026")


def test_el_enlace_vale_una_sola_vez(uow: Any, usuario: Any) -> None:
    from services.identity import restablecer as rst

    token = rst.solicitar(uow, email=usuario.email)
    rst.confirmar(uow.db, token, contrasena="UnaNuevaDeVerdad.2026")

    with pytest.raises(NoAutenticado) as fallo:
        rst.confirmar(uow.db, token, contrasena="OtraMas.2026")

    assert fallo.value.error_code == "restablecer.enlace_no_valido"


def test_un_enlace_caducado_no_vale(uow: Any, usuario: Any) -> None:
    from services.identity import restablecer as rst

    token = rst.solicitar(uow, email=usuario.email)
    enlace = (
        uow.db.execute(__import__("sqlalchemy").select(rst.EnlaceRestablecer)).scalars().all()[-1]
    )
    enlace.caduca_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    uow.db.flush()

    with pytest.raises(NoAutenticado):
        rst.confirmar(uow.db, token, contrasena="UnaNuevaDeVerdad.2026")


def test_el_token_no_se_guarda_en_claro(uow: Any, usuario: Any) -> None:
    """Quien lea la base no puede usar los enlaces pendientes. Es la misma
    razón por la que no se guarda la contraseña."""
    import sqlalchemy as sa

    from services.identity import restablecer as rst

    token = rst.solicitar(uow, email=usuario.email)
    guardados = [
        f.hash_token for f in uow.db.execute(sa.select(rst.EnlaceRestablecer)).scalars().all()
    ]

    assert token not in guardados


def test_una_contrasena_corta_se_rechaza_en_el_servidor(uow: Any, usuario: Any) -> None:
    """Una comprobación que solo vive en el navegador no comprueba nada."""
    from services.identity import restablecer as rst

    token = rst.solicitar(uow, email=usuario.email)

    with pytest.raises(ErrorValidacion) as fallo:
        rst.confirmar(uow.db, token, contrasena="corta")

    assert fallo.value.error_code == "restablecer.contrasena_corta"


def test_al_cambiarla_se_cierran_las_sesiones(uow: Any, usuario: Any, tenant_id: UUID) -> None:
    from services.identity import restablecer as rst
    from services.identity import servicio as svc

    svc.crear_sesion(uow.db, usuario=usuario, tenant_id=tenant_id, ip="", user_agent="")
    vivas = svc.sesiones_activas(uow.db, usuario.id) if hasattr(svc, "sesiones_activas") else None

    token = rst.solicitar(uow, email=usuario.email)
    rst.confirmar(uow.db, token, contrasena="UnaNuevaDeVerdad.2026")

    import sqlalchemy as sa

    from services.identity.modelos import Sesion

    abiertas = (
        uow.db.execute(
            sa.select(Sesion).where(Sesion.usuario_id == usuario.id, Sesion.revocada_at.is_(None))
        )
        .scalars()
        .all()
    )
    assert abiertas == [], f"quedan {len(abiertas)} sesiones abiertas (antes: {vivas})"


def test_un_usuario_inactivo_no_puede_restablecer(uow: Any, usuario: Any) -> None:
    from services.identity import restablecer as rst

    token = rst.solicitar(uow, email=usuario.email)
    usuario.activo = False
    uow.db.flush()

    with pytest.raises(NoAutenticado):
        rst.confirmar(uow.db, token, contrasena="UnaNuevaDeVerdad.2026")


def test_los_enlaces_pendientes_se_pueden_mirar(uow: Any, usuario: Any) -> None:
    """Para que quien vigila la instalación vea si alguien está pidiendo
    enlaces de una cuenta que no es suya."""
    from services.identity import restablecer as rst

    rst.solicitar(uow, email=usuario.email, ip="10.0.0.9")

    pendientes = rst.pendientes(uow.db, usuario.id)

    assert len(pendientes) == 1
    assert pendientes[0]["ip_solicitud"] == "10.0.0.9"
    assert pendientes[0]["caducado"] is False
    assert uuid4() is not None


# ── El enlace va al buzón, nunca a quien lo pide (SEC-1, auditoría 13-11-2026) ──
#
# La respuesta de `POST /auth/restablecer` llevaba el token. Quien supiera el
# correo de alguien y el slug de su empresa se quedaba con su cuenta en dos
# llamadas. Estas pruebas fijan las tres piezas del arreglo.


def test_la_respuesta_http_no_lleva_el_token() -> None:
    """La ruta no devuelve nada que abra la cuenta: ni el token ni el enlace."""
    import inspect

    from services.identity import api

    fuente = inspect.getsource(api.pedir_restablecer)
    retorno = fuente[fuente.rindex("return") :]
    assert "token" not in retorno, retorno
    assert "enlace" not in retorno, retorno


def test_el_evento_lleva_el_enlace_y_no_sale_a_los_webhooks(uow: Any, usuario: Any) -> None:
    """El enlace viaja en el evento interno hacia el aviso por correo, y el
    catálogo lo marca como no público: un webhook del tenant no lo recibe."""
    from crmcore.events.catalogo import obtener

    from services.identity import restablecer as rst

    token = rst.solicitar(uow, email=usuario.email)

    eventos = [e for e in uow._pendientes if e["tipo"] == "user.password.reset_requested"]
    assert len(eventos) == 1
    datos = eventos[0]["data"]
    assert datos["canales"] == ["correo"]
    assert rst.url_del_enlace(token) in datos["cuerpo"]
    declarado = obtener("user.password.reset_requested")
    assert declarado is not None and declarado.publico is False


def test_el_enlace_apunta_a_la_interfaz_configurada(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sale de `FRONT_BASE_URL`, no de una dirección escrita en el código."""
    from crmcore.config import get_settings

    from services.identity import restablecer as rst

    monkeypatch.setattr(get_settings(), "front_base_url", "https://crm.empresa.example/")
    assert rst.url_del_enlace("a+b/c") == "https://crm.empresa.example/?restablecer=a%2Bb%2Fc"


def test_el_aviso_sale_solo_por_correo_y_sin_esperar(
    uow: Any, usuario: Any, tenant_id: UUID
) -> None:
    """La regla de avisos lo manda al titular y a nadie más, sólo por correo y
    con prioridad que atraviesa silencio y agrupación."""
    import asyncio

    import sqlalchemy as sa
    from crmcore.datos.seguimiento import Notificacion, PreferenciaNotificacion
    from crmcore.db import uow as modulo_uow

    from services.identity import restablecer as rst
    from services.identity.notificaciones import consumir_evento

    # Alguien que agrupa sus avisos y tiene la noche entera en silencio: aun así
    # el enlace tiene que salir ya.
    uow.db.add(
        PreferenciaNotificacion(
            tenant_id=tenant_id,
            usuario_id=usuario.id,
            tipo="*",
            canales=["app"],
            agrupar_minutos=30,
            silencio_desde=0,
            silencio_hasta=23,
        )
    )
    uow.db.flush()

    rst.solicitar(uow, email=usuario.email)
    evento = next(e for e in uow._pendientes if e["tipo"] == "user.password.reset_requested")

    testigo = modulo_uow.compartir(uow)
    try:
        asyncio.run(
            consumir_evento(
                {"tipo": evento["tipo"], "tenant_id": str(tenant_id), "data": evento["data"]}
            )
        )
    finally:
        modulo_uow.soltar(testigo)

    avisos = (
        uow.db.execute(
            sa.select(Notificacion).where(Notificacion.tipo == "user.password.reset_requested")
        )
        .scalars()
        .all()
    )
    assert len(avisos) == 1
    aviso = avisos[0]
    assert aviso.usuario_id == usuario.id
    assert "correo" in aviso.canales
    assert aviso.prioridad == "urgente"
    assert aviso.entregar_at <= datetime.now(timezone.utc)


def test_sin_cuenta_en_este_tenant_no_hay_enlace(uow: Any, tenant_id: UUID) -> None:
    """El usuario es global: un enlace pedido por la puerta de otra empresa
    cambiaría la contraseña con la que entra en la suya."""
    from services.identity import restablecer as rst
    from services.identity import servicio as svc
    from services.identity.modelos import Usuario

    uow.db.add(
        Usuario(
            email="de-otra@empresa.example",
            nombre="De Otra",
            hash_contrasena=svc.hashear_contrasena("LaDeSiempre.2026"),
            activo=True,
        )
    )
    uow.db.flush()

    assert rst.solicitar(uow, email="de-otra@empresa.example") == ""
    assert not [e for e in uow._pendientes if e["tipo"] == "user.password.reset_requested"]


def test_el_alta_y_el_cambio_exigen_el_minimo_del_ajuste(monkeypatch: pytest.MonkeyPatch) -> None:
    """`hashear_contrasena` tenía un 12 escrito: subir `contrasena_minimo`
    endurecía el restablecer y dejaba igual el alta y el cambio."""
    from crmcore.config import get_settings

    from services.identity.servicio import hashear_contrasena

    monkeypatch.setattr(get_settings(), "contrasena_minimo", 16)
    with pytest.raises(ErrorValidacion) as fallo:
        hashear_contrasena("catorce-letras")
    assert "16" in str(fallo.value)
    assert hashear_contrasena("dieciseis-letras")
