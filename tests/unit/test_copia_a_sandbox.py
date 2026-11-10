"""La copia de un tenant a su sandbox (CRM-07.02.01.02).

El plan de copia y la anonimización existían como cálculos sueltos y no había
copia. Aquí se comprueba el motor que cada servicio ejecuta sobre sus tablas:

- los identificadores nuevos son los mismos en todos los servicios, así que una
  referencia de una tabla a otra sigue cuadrando en la copia;
- lo que el modelo declara personal sale anonimizado, y el origen no se toca;
- la copia parcial es por cuenta: la relación de un contacto con una cuenta que
  la muestra deja fuera no se copia, y los contactos van con sus cuentas;
- una tabla con secretos no se copia nunca.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

pytestmark = pytest.mark.db


def _cuenta_y_contacto(db: Any, tenant_id: UUID, nombre: str, correo: str) -> tuple[Any, Any]:
    from services.party.modelos import Contacto, Cuenta, RelacionContactoCuenta

    cuenta = Cuenta(tenant_id=tenant_id, nombre=nombre, clave_canonica=nombre.lower())
    contacto = Contacto(
        tenant_id=tenant_id,
        nombre="Marta",
        apellidos="Ruiz",
        nombre_completo="Marta Ruiz",
        email=correo,
        clave_canonica=correo,
    )
    db.add_all([cuenta, contacto])
    db.flush()
    db.add(
        RelacionContactoCuenta(tenant_id=tenant_id, contacto_id=contacto.id, cuenta_id=cuenta.id)
    )
    db.flush()
    return cuenta, contacto


def test_la_copia_traduce_los_identificadores_y_anonimiza(db: Any, tenant_id: UUID) -> None:
    from crmcore.datos.copia_sandbox import copiar_tenant, nuevo_identificador

    from services.party.modelos import Contacto, Cuenta, RelacionContactoCuenta

    cuenta, contacto = _cuenta_y_contacto(db, tenant_id, "Metales Norte", "marta@norte.example")
    # Sensible y numérico: el seudónimo es texto y revienta la columna.
    cuenta.empleados = 40
    db.flush()
    destino = uuid4()
    semilla = "semilla-de-prueba"
    resultado = copiar_tenant(
        db,
        servicio="party",
        origen=tenant_id,
        destino=destino,
        semilla=semilla,
        porcentaje=100,
        anonimizar=True,
        conservar=set(),
    )
    assert not resultado["fallidas"], resultado["fallidas"]
    # Las filas se cuentan de verdad: con un lote el controlador decía -1.
    por_tabla = {t["tabla"]: t["filas"] for t in resultado["copiadas"]}
    assert por_tabla["cuentas"] == 1 and por_tabla["contacto_cuenta"] == 1
    assert resultado["filas"] == sum(por_tabla.values()) > 0

    copia = db.get(Cuenta, nuevo_identificador(semilla, cuenta.id))
    assert copia is not None and copia.tenant_id == destino
    # Lo numérico sensible no se inventa: se suprime.
    assert copia.empleados is None
    copia_contacto = db.get(Contacto, nuevo_identificador(semilla, contacto.id))
    assert copia_contacto is not None
    # Lo que el modelo declara personal sale anonimizado…
    assert copia_contacto.email and copia_contacto.email != "marta@norte.example"
    # …y lo marcado sólo para copias también: el nombre y su clave canónica, que
    # es el nombre normalizado. Pasaban en claro: 193 de 193 en la primera copia.
    assert copia_contacto.nombre_completo != "Marta Ruiz"
    assert copia_contacto.clave_canonica != "marta@norte.example"
    assert copia.nombre != "Metales Norte"
    # Sin tocar lo que cada rol ve en la aplicación: la sensibilidad no cambia.
    from crmcore.authz.proyeccion import sensibilidad_de

    assert sensibilidad_de(Contacto, "nombre_completo") == "interno"
    # …y la relación apunta a las copias, no a los originales.
    relacion = db.execute(
        select(RelacionContactoCuenta).where(RelacionContactoCuenta.tenant_id == destino)
    ).scalar_one()
    assert relacion.cuenta_id == copia.id
    assert relacion.contacto_id == copia_contacto.id
    # El origen, intacto.
    db.refresh(contacto)
    assert contacto.email == "marta@norte.example"


def test_la_copia_parcial_es_por_cuenta(db: Any, tenant_id: UUID) -> None:
    from crmcore.datos.copia_sandbox import copiar_tenant, en_la_muestra, nuevo_identificador

    from services.party.modelos import Cuenta, RelacionContactoCuenta

    semilla = "semilla-parcial"
    cuentas = [
        _cuenta_y_contacto(db, tenant_id, f"Cuenta {i}", f"c{i}@x.example")[0] for i in range(12)
    ]
    destino = uuid4()
    copiar_tenant(
        db,
        servicio="party",
        origen=tenant_id,
        destino=destino,
        semilla=semilla,
        porcentaje=30,
        anonimizar=True,
        conservar=set(),
    )
    for cuenta in cuentas:
        dentro = en_la_muestra(semilla, cuenta.id, 30)
        copia = db.get(Cuenta, nuevo_identificador(semilla, cuenta.id))
        assert (copia is not None) == dentro
        relaciones = db.execute(
            select(RelacionContactoCuenta).where(
                RelacionContactoCuenta.tenant_id == destino,
                RelacionContactoCuenta.cuenta_id == nuevo_identificador(semilla, cuenta.id),
            )
        ).all()
        assert bool(relaciones) == dentro
    # Que la muestra no sea ni todo ni nada, o la prueba no prueba nada.
    dentro = sum(en_la_muestra(semilla, c.id, 30) for c in cuentas)
    assert 0 < dentro < len(cuentas)


def test_el_porcentaje_limita_tambien_los_contactos(db: Any, tenant_id: UUID) -> None:
    """Los contactos no llevan `cuenta_id` y se copiaban TODOS con cualquier
    porcentaje: justo los datos personales que la copia parcial quiere reducir.
    Ahora van con su cuenta, y los sueltos por su propio identificador."""
    from crmcore.datos.copia_sandbox import copiar_tenant, en_la_muestra, nuevo_identificador

    from services.party.modelos import Contacto

    semilla = "semilla-contactos"
    pares = [_cuenta_y_contacto(db, tenant_id, f"Con {i}", f"k{i}@x.example") for i in range(12)]
    sueltos = []
    for i in range(12):
        suelto = Contacto(
            tenant_id=tenant_id,
            nombre="Suelto",
            nombre_completo=f"Suelto {i}",
            email=f"s{i}@x.example",
            clave_canonica=f"s{i}@x.example",
        )
        db.add(suelto)
        sueltos.append(suelto)
    db.flush()
    destino = uuid4()
    resultado = copiar_tenant(
        db,
        servicio="party",
        origen=tenant_id,
        destino=destino,
        semilla=semilla,
        porcentaje=30,
        anonimizar=True,
        conservar=set(),
    )
    assert not resultado["fallidas"], resultado["fallidas"]
    # El contacto de una cuenta copiada llega con ella; el de una que se quedó
    # fuera, no (salvo que su propio identificador caiga en la muestra).
    for cuenta, contacto in pares:
        esperado = en_la_muestra(semilla, cuenta.id, 30) or en_la_muestra(semilla, contacto.id, 30)
        copia = db.get(Contacto, nuevo_identificador(semilla, contacto.id))
        assert (copia is not None) == esperado
    for suelto in sueltos:
        copia = db.get(Contacto, nuevo_identificador(semilla, suelto.id))
        assert (copia is not None) == en_la_muestra(semilla, suelto.id, 30)
    copiados = db.execute(select(Contacto).where(Contacto.tenant_id == destino)).scalars().all()
    # Y la cuenta de lo copiado: ni todos ni ninguno, o la prueba no prueba nada.
    assert 0 < len(copiados) < len(pares) + len(sueltos), len(copiados)


def test_una_tabla_con_secretos_no_se_copia(db: Any, tenant_id: UUID) -> None:
    from crmcore.datos.copia_sandbox import copiar_tenant

    resultado = copiar_tenant(
        db,
        servicio="identity",
        origen=tenant_id,
        destino=uuid4(),
        semilla="semilla-secretos",
        porcentaje=100,
        anonimizar=True,
        conservar=set(),
    )
    assert "claves_api" in {t["tabla"] for t in resultado["no_copiadas"]}


def test_lo_que_apunta_a_algo_global_no_se_traduce(db: Any, tenant_id: UUID) -> None:
    """Un usuario existe una vez para todos: la copia sigue apuntando al mismo.

    Traducirlo dejaba la fila apuntando a algo que no existe —medido con un
    conector: `instalaciones_conector` caía por su clave a su manifiesto—.
    """
    from crmcore.datos.copia_sandbox import copiar_tenant

    from services.identity.modelos import Membresia, Usuario

    usuario = Usuario(email=f"u{uuid4().hex[:8]}@x.example")
    db.add(usuario)
    db.flush()
    db.add(Membresia(tenant_id=tenant_id, usuario_id=usuario.id))
    db.flush()
    destino = uuid4()
    resultado = copiar_tenant(
        db,
        servicio="identity",
        origen=tenant_id,
        destino=destino,
        semilla="semilla-global",
        porcentaje=100,
        anonimizar=True,
        conservar=set(),
    )
    assert not resultado["fallidas"], resultado["fallidas"]
    copia = db.execute(select(Membresia).where(Membresia.tenant_id == destino)).scalar_one()
    assert copia.usuario_id == usuario.id


def test_un_sandbox_se_crea_como_tenant_hijo_y_caduca(
    monkeypatch: Any, tenant_id: UUID, db: Any
) -> None:
    import importlib

    from crmcore.config import get_settings
    from crmcore.tareas import RelevoDeTareas
    from starlette.testclient import TestClient

    from tests.unit.test_reverificacion_y_mfa_adaptativa import _cabeceras

    async def _no_correr(self: Any) -> None:
        return None

    from services.tenancy.modelos import Tenant

    db.add(Tenant(id=tenant_id, slug=f"cliente-{tenant_id.hex[:8]}", nombre="Cliente S.A."))
    db.commit()
    monkeypatch.setattr(RelevoDeTareas, "correr", _no_correr)
    monkeypatch.setenv("OUTBOX_ENABLED", "false")
    get_settings.cache_clear()
    try:
        with TestClient(importlib.import_module("services.tenancy.main").app) as cli:
            cab = _cabeceras(tenant_id)
            sin_motivo = cli.post(
                "/api/v1/sandboxes",
                headers=cab,
                json={"nombre": "Pruebas", "proposito": "pruebas", "anonimizar": False},
            )
            assert sin_motivo.status_code == 403, sin_motivo.text
            alta = cli.post(
                "/api/v1/sandboxes",
                headers=cab,
                json={"nombre": "Pruebas", "proposito": "pruebas", "porcentaje": 10},
            )
            assert alta.status_code == 201, alta.text
            # Un segundo seguido: el slug no puede salir de la hora.
            otro = cli.post(
                "/api/v1/sandboxes",
                headers=cab,
                json={"nombre": "Formación", "proposito": "formacion"},
            )
            assert otro.status_code == 201, otro.text
            ficha = cli.get(f"/api/v1/sandboxes/{alta.json()['id']}", headers=cab).json()
            assert ficha["estado"] == "preparado"
            assert ficha["caduca_el"]
            # Apagarlo suspende el tenant hijo desde la sesión del origen: daba
            # 409 en la secuencia de la auditoría, como el alta.
            apagado = cli.post(
                f"/api/v1/sandboxes/{alta.json()['id']}/apagar",
                headers=cab,
                json={"motivo": "Ya no hace falta"},
            )
            assert apagado.status_code == 200, apagado.text
            assert apagado.json()["estado"] == "apagado"
    finally:
        get_settings.cache_clear()
