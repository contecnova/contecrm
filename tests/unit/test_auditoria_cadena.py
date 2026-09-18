"""La cadena de auditoría (CRM-00.05.04.01, CRM-00.05.04.03).

El registro de auditoría es la única prueba de lo que pasó, así que tiene dos
propiedades que hay que defender por separado: que **no se puede alterar** —cada
apunte encadena con el anterior por hash— y que **no se puede borrar sin que se
note** —la secuencia es consecutiva, y un hueco es por sí solo la señal—.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from crmcore.audit.chain import registrar, verificar
from crmcore.audit.modelos import ApunteAuditoria
from sqlalchemy import select


def test_dos_apuntes_en_la_misma_transaccion_no_colisionan(db: Any, tenant_id: UUID) -> None:
    """Fue un fallo real: la sesión va con `autoflush=False`, así que sin volcar
    cada apunte, la consulta del anterior no veía los añadidos en esta misma
    transacción. Dos tomaban la MISMA secuencia y el índice único reventaba al
    confirmar, con un error de clave duplicada lejísimos del sitio que lo causó.

    Pasa en cuanto una operación audita dos veces, que es lo normal: una fusión
    anota el hecho y el deshacer, un bloqueo legal se pone y se levanta, una baja
    de usuario audita la desactivación y el corte de sesiones.
    """
    for i in range(5):
        registrar(
            db,
            accion="prueba.accion",
            objeto="cosa",
            objeto_id=uuid4(),
            datos={"i": i},
            tenant_id=tenant_id,
        )

    secuencias = list(
        db.execute(
            select(ApunteAuditoria.secuencia)
            .where(ApunteAuditoria.tenant_id == tenant_id)
            .order_by(ApunteAuditoria.secuencia)
        ).scalars()
    )
    assert secuencias == [1, 2, 3, 4, 5]


def test_cada_apunte_encadena_con_el_anterior(db: Any, tenant_id: UUID) -> None:
    primero = registrar(db, accion="a", objeto="x", tenant_id=tenant_id)
    segundo = registrar(db, accion="b", objeto="x", tenant_id=tenant_id)

    assert segundo.hash_previo == primero.hash
    assert primero.hash != segundo.hash


def test_la_cadena_de_un_tenant_es_independiente_de_la_de_otro(
    db: Any, tenant_id: UUID, otro_tenant_id: UUID
) -> None:
    """Una cadena por tenant: con una global, verificar la de un cliente
    exigiría leer los apuntes de todos los demás."""
    registrar(db, accion="a", objeto="x", tenant_id=tenant_id)
    ajeno = registrar(db, accion="a", objeto="x", tenant_id=otro_tenant_id)

    assert ajeno.secuencia == 1


def test_verificar_da_por_buena_una_cadena_intacta(db: Any, tenant_id: UUID) -> None:
    for i in range(3):
        registrar(db, accion="a", objeto="x", datos={"i": i}, tenant_id=tenant_id)
    db.flush()

    resultado = verificar(db, tenant_id=tenant_id)
    assert resultado["intacta"] is True


def test_verificar_detecta_un_apunte_alterado(db: Any, tenant_id: UUID) -> None:
    """Cambiar el contenido de un apunte rompe su hash, y con él toda la cadena
    a partir de ahí. Es lo que hace que alterar la auditoría no sea silencioso."""
    for i in range(3):
        registrar(db, accion="a", objeto="x", datos={"i": i}, tenant_id=tenant_id)
    db.flush()

    apunte = db.execute(
        select(ApunteAuditoria).where(
            ApunteAuditoria.tenant_id == tenant_id, ApunteAuditoria.secuencia == 2
        )
    ).scalar_one()
    apunte.datos = {"i": 99, "manipulado": True}
    db.flush()

    resultado = verificar(db, tenant_id=tenant_id)
    assert resultado["intacta"] is False
    assert resultado["rota_en"] == 2


def test_verificar_detecta_un_apunte_borrado(db: Any, tenant_id: UUID) -> None:
    """Un hueco en la secuencia es, por sí solo, la prueba de que falta algo."""
    for i in range(4):
        registrar(db, accion="a", objeto="x", datos={"i": i}, tenant_id=tenant_id)
    db.flush()

    apunte = db.execute(
        select(ApunteAuditoria).where(
            ApunteAuditoria.tenant_id == tenant_id, ApunteAuditoria.secuencia == 2
        )
    ).scalar_one()
    db.delete(apunte)
    db.flush()

    resultado = verificar(db, tenant_id=tenant_id)
    assert resultado["intacta"] is False
