"""El guard del ORM no se puede envenenar con la caché de sentencias.

Regresión de la fuga más grave encontrada en este proyecto, y la que mejor
explica por qué una suite de aislamiento tiene que usar **más de un tenant en el
mismo proceso**.

El guard inyecta `with_loader_criteria(modelo, lambda cls: ...)`. SQLAlchemy
compila esos lambdas una vez y los cachea por su objeto de código; analiza sus
**variables de cierre** y las convierte en parámetros ligados, de modo que el
valor viaja en cada ejecución. Un **argumento por defecto** no es una variable
de cierre: no se analiza, y su valor queda horneado en la expresión cacheada.

El guard usaba `lambda cls, tid=tenant_id: cls.tenant_id == tid`. Consecuencia:
el primer tenant que consultaba en el proceso fijaba el filtro para todos los
demás, y **el segundo tenant veía las filas del primero**.

No se había visto porque cada prueba monta un motor nuevo —y con él una caché de
sentencias nueva— y casi todas usan un solo tenant. En un proceso de API, que
vive días y atiende a muchos tenants, habría filtrado desde el primer minuto.

Por eso estas pruebas hacen siempre lo mismo: consultar con un tenant, y después
con otro, **en la misma sesión de motor**.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from crmcore.db.session import nueva_sesion

from services.party.modelos import Contacto, Cuenta

# Su fallo llega a producción y no se arregla después: una fuga entre tenants o
# una ruta publicada que no responde. Por eso esta prueba NO sale del push.
pytestmark = pytest.mark.despliegue


def _cuenta(db: Any, tenant_id: UUID, nombre: str) -> Cuenta:
    fila = Cuenta(tenant_id=tenant_id, nombre=nombre, clave_canonica=nombre.lower())
    db.add(fila)
    return fila


@pytest.mark.db
def test_consultar_con_un_tenant_no_fija_el_filtro_para_el_siguiente(
    db: Any, tenant_id: UUID, otro_tenant_id: UUID
) -> None:
    """La fuga, tal cual era."""
    _cuenta(db, tenant_id, "De A")
    _cuenta(db, otro_tenant_id, "De B")
    db.commit()

    vistos: dict[str, list[str]] = {}
    for etiqueta, quien in (("B", otro_tenant_id), ("A", tenant_id)):
        sesion = nueva_sesion(quien)
        try:
            vistos[etiqueta] = [c.nombre for c in sesion.execute(sa.select(Cuenta)).scalars()]
        finally:
            sesion.close()

    assert vistos == {"B": ["De B"], "A": ["De A"]}


@pytest.mark.db
def test_con_tres_tenants_seguidos_cada_uno_ve_lo_suyo(db: Any) -> None:
    """Dos no bastan: con el fallo original, el tercero también veía lo del
    primero, y una prueba de dos podría pasar por casualidad si el orden fuera
    el afortunado."""
    tenants = [uuid4() for _ in range(3)]
    for i, t in enumerate(tenants):
        _cuenta(db, t, f"Cuenta {i}")
    db.commit()

    for i, t in enumerate(tenants):
        sesion = nueva_sesion(t)
        try:
            nombres = [c.nombre for c in sesion.execute(sa.select(Cuenta)).scalars()]
        finally:
            sesion.close()
        assert nombres == [f"Cuenta {i}"], f"el tenant {i} vio {nombres}"


@pytest.mark.db
def test_tambien_se_filtra_al_recuperar_por_identificador(
    db: Any, tenant_id: UUID, otro_tenant_id: UUID
) -> None:
    """`Session.get()` va por el mismo camino y tiene la misma caché. Era por
    donde se coló: `GET /cuentas/{id}` del tenant B devolvía la del A."""
    ajena = _cuenta(db, tenant_id, "Ajena")
    db.commit()

    # Primero consulta B, para poblar la caché con su valor.
    sesion_b = nueva_sesion(otro_tenant_id)
    try:
        sesion_b.execute(sa.select(Cuenta)).scalars().all()
        assert sesion_b.get(Cuenta, ajena.id) is None
    finally:
        sesion_b.close()

    sesion_a = nueva_sesion(tenant_id)
    try:
        assert sesion_a.get(Cuenta, ajena.id) is not None
    finally:
        sesion_a.close()


@pytest.mark.db
def test_el_filtro_no_se_mezcla_entre_modelos_distintos(
    db: Any, tenant_id: UUID, otro_tenant_id: UUID
) -> None:
    """El mismo lambda se aplica a los ochenta modelos. Si el valor se horneara
    por objeto de código, consultar cuentas fijaría también el filtro de
    contactos."""
    _cuenta(db, otro_tenant_id, "Cuenta de B")
    db.add(
        Contacto(
            tenant_id=tenant_id,
            nombre="Contacto",
            apellidos="De A",
            nombre_completo="Contacto De A",
            clave_canonica="contacto de a",
        )
    )
    db.commit()

    sesion_b = nueva_sesion(otro_tenant_id)
    try:
        assert [c.nombre for c in sesion_b.execute(sa.select(Cuenta)).scalars()] == ["Cuenta de B"]
        assert sesion_b.execute(sa.select(Contacto)).scalars().all() == []
    finally:
        sesion_b.close()

    sesion_a = nueva_sesion(tenant_id)
    try:
        assert sesion_a.execute(sa.select(Cuenta)).scalars().all() == []
        assert [c.nombre for c in sesion_a.execute(sa.select(Contacto)).scalars()] == ["Contacto"]
    finally:
        sesion_a.close()


@pytest.mark.db
def test_una_actualizacion_tampoco_alcanza_al_tenant_ajeno(
    db: Any, tenant_id: UUID, otro_tenant_id: UUID
) -> None:
    """El guard filtra también UPDATE y DELETE. Con el filtro envenenado, un
    `UPDATE ... WHERE` del tenant A habría escrito sobre las filas del B."""
    _cuenta(db, tenant_id, "De A")
    _cuenta(db, otro_tenant_id, "De B")
    db.commit()

    sesion_b = nueva_sesion(otro_tenant_id)
    try:
        sesion_b.execute(sa.select(Cuenta)).scalars().all()
    finally:
        sesion_b.close()

    sesion_a = nueva_sesion(tenant_id)
    try:
        sesion_a.execute(sa.update(Cuenta).values(estado="prospecto"))
        sesion_a.commit()
    finally:
        sesion_a.close()

    filas = dict(db.execute(sa.text("SELECT nombre, estado FROM cuentas")).all())
    assert filas["De A"] == "prospecto"
    assert filas["De B"] != "prospecto", "el UPDATE del tenant A alcanzó a las filas del B"
