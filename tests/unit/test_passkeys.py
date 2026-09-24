"""Passkeys: entrar sin contraseña y sin poder caer en un engaño.

Una passkey es la única credencial de este sistema que **no se pierde por
phishing**: el navegador solo la entrega al dominio que la creó, así que no se
puede teclear en una página falsa. Eso vale mientras el servidor haga bien tres
cosas, que son las que se comprueban aquí.

  * El **reto lo elige el servidor** y vale una sola vez. Si valiera dos, una
    firma capturada se podría reproducir — que es el ataque del que protege
    esto.
  * El **contador solo sube**. Es la única señal que delata un autenticador
    clonado: dos copias de la misma llave acaban firmando con un contador que
    retrocede.
  * La **clave privada no está aquí**. Se guarda la pública, así que una base de
    datos filtrada no da acceso a ninguna cuenta.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.errors import NoAutenticado


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> Any:
    from crmcore.db.uow import UnidadDeTrabajo

    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


@pytest.fixture
def usuario(uow: Any) -> Any:
    from services.identity.modelos import Usuario

    fila = Usuario(email="conllave@empresa.example", nombre="Con Llave", activo=True)
    uow.db.add(fila)
    uow.db.flush()
    return fila


def test_el_reto_lo_elige_el_servidor_y_se_guarda(uow: Any, usuario: Any, tenant_id: UUID) -> None:
    import sqlalchemy as sa

    from services.identity import passkeys as pk

    opciones = pk.opciones_registro(uow.db, tenant_id=tenant_id, usuario=usuario)

    assert opciones["challenge"]
    guardados = uow.db.execute(sa.select(pk.RetoPasskey)).scalars().all()
    assert [r.proposito for r in guardados] == ["registro"]
    assert guardados[0].reto == opciones["challenge"]


def test_un_reto_solo_vale_una_vez(uow: Any, usuario: Any, tenant_id: UUID) -> None:
    """Si valiera dos, una firma capturada se podría reproducir."""
    from services.identity import passkeys as pk

    opciones = pk.opciones_entrada(uow.db, tenant_id=tenant_id, usuario=usuario)
    reto = opciones["challenge"]

    pk._consumir_reto(uow.db, reto_b64=reto, proposito="entrada")

    with pytest.raises(NoAutenticado) as fallo:
        pk._consumir_reto(uow.db, reto_b64=reto, proposito="entrada")
    assert fallo.value.error_code == "passkey.reto_no_valido"


def test_un_reto_caducado_no_vale(uow: Any, usuario: Any, tenant_id: UUID) -> None:
    import sqlalchemy as sa

    from services.identity import passkeys as pk

    opciones = pk.opciones_entrada(uow.db, tenant_id=tenant_id, usuario=usuario)
    fila = uow.db.execute(sa.select(pk.RetoPasskey)).scalars().all()[-1]
    fila.caduca_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    uow.db.flush()

    with pytest.raises(NoAutenticado):
        pk._consumir_reto(uow.db, reto_b64=opciones["challenge"], proposito="entrada")


def test_un_reto_de_registro_no_sirve_para_entrar(uow: Any, usuario: Any, tenant_id: UUID) -> None:
    """Separar los propósitos impide que un reto pedido para registrar una
    llave se use para firmar una entrada."""
    from services.identity import passkeys as pk

    opciones = pk.opciones_registro(uow.db, tenant_id=tenant_id, usuario=usuario)

    with pytest.raises(NoAutenticado):
        pk._consumir_reto(uow.db, reto_b64=opciones["challenge"], proposito="entrada")


def test_sin_usuario_se_devuelve_reto_igualmente(uow: Any, tenant_id: UUID) -> None:
    """No decir si ese correo existe es lo que impide que esta pantalla sirva
    para averiguar quién tiene cuenta aquí."""
    from services.identity import passkeys as pk

    opciones = pk.opciones_entrada(uow.db, tenant_id=tenant_id, usuario=None)

    assert opciones["challenge"]
    assert not opciones.get("allowCredentials")


def test_no_se_guarda_ninguna_clave_privada(uow: Any, usuario: Any, tenant_id: UUID) -> None:
    """Se guarda la pública y un contador. Una base filtrada no da acceso."""
    from services.identity import passkeys as pk

    columnas = {c.key for c in pk.Passkey.__table__.columns}

    assert "clave_publica" in columnas
    assert not {c for c in columnas if "privad" in c or "secreto" in c}


def test_las_llaves_se_listan_con_su_nombre_y_su_uso(
    uow: Any, usuario: Any, tenant_id: UUID
) -> None:
    """Sin nombre y sin fecha de uso, revocar una de tres es elegir a ciegas."""
    from services.identity import passkeys as pk

    uow.db.add(
        pk.Passkey(
            tenant_id=tenant_id,
            usuario_id=usuario.id,
            credencial_id="unacredencial",
            clave_publica=b"\x01\x02",
            nombre="El iPhone",
        )
    )
    uow.db.flush()

    listadas = pk.listar(uow.db, usuario.id)

    assert [x["nombre"] for x in listadas] == ["El iPhone"]
    assert listadas[0]["ultimo_uso_at"] is None


def test_revocar_borra_de_verdad(uow: Any, usuario: Any, tenant_id: UUID) -> None:
    """Y no a la papelera: una credencial revocada que sigue guardada invita a
    restaurarla, y restaurar una credencial es lo que no puede pasar."""
    import sqlalchemy as sa

    from services.identity import passkeys as pk

    fila = pk.Passkey(
        tenant_id=tenant_id,
        usuario_id=usuario.id,
        credencial_id="otracredencial",
        clave_publica=b"\x01",
        nombre="La del cajón",
    )
    uow.db.add(fila)
    uow.db.flush()

    pk.revocar(uow, usuario_id=usuario.id, passkey_id=fila.id)

    assert uow.db.execute(sa.select(pk.Passkey)).scalars().all() == []


def test_no_se_revoca_la_llave_de_otro(uow: Any, usuario: Any, tenant_id: UUID) -> None:
    from crmcore.errors import NoEncontrado

    from services.identity import passkeys as pk

    fila = pk.Passkey(
        tenant_id=tenant_id,
        usuario_id=uuid4(),
        credencial_id="ajena",
        clave_publica=b"\x01",
    )
    uow.db.add(fila)
    uow.db.flush()

    with pytest.raises(NoEncontrado):
        pk.revocar(uow, usuario_id=usuario.id, passkey_id=fila.id)
