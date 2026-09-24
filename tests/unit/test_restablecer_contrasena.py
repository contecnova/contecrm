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
