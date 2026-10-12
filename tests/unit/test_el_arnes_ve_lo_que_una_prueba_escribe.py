"""La premisa del arnés: lo que una prueba escribe lo ve la aplicación.

El arnés ata **todas** las sesiones a una conexión y aísla cada prueba con un
savepoint. De ahí sale la propiedad de la que depende media suite: una fila que
la prueba escribe y **vuelca sin confirmar** la ve la sesión que abre la
aplicación al atender la petición.

Esto no estaba comprobado en ninguna parte, y es la premisa. El 12-10-2026 se
cambió un `commit` por un `flush` en el recorrido de aislamiento —confirmar en
cada vuelta soltaba un savepoint, y con doscientas rutas bastaba con que uno se
soltara fuera de orden para reventar la siguiente— y entonces la pregunta pasó a
ser obligatoria: si el `flush` no bastara, ese recorrido contestaría 404 a todo,
que es **la respuesta correcta para un ajeno**, y pasaría sin mirar nada.

Se comprueba aquí y no allí porque allí **no se puede**: el producto devuelve
2xx a un desconocido en algunas rutas a propósito —lo que delata una fuga es
responder DISTINTO, no responder—, así que desde el código de estado no se
distingue «la ve» de «no la ve». Aquí sí, porque se mira la fila.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

pytestmark = pytest.mark.db


def test_otra_sesion_ve_lo_volcado_sin_confirmar(db: Any, tenant_id: UUID) -> None:
    """Es la propiedad entera, en cuatro líneas."""
    from crmcore.db.session import sesion
    from sqlalchemy import select

    from services.party.modelos import Contacto

    fila = Contacto(
        tenant_id=tenant_id,
        nombre="Visible",
        nombre_completo="Visible Sin Confirmar",
        clave_canonica="visible sin confirmar",
    )
    db.add(fila)
    db.flush()  # SIN confirmar

    with sesion(tenant_id) as otra:
        encontrada = otra.execute(
            select(Contacto).where(Contacto.id == fila.id)
        ).scalar_one_or_none()

    assert encontrada is not None, (
        "Una sesión nueva no ve lo que la prueba acaba de volcar. Si eso pasa, "
        "toda prueba que escriba con `db` y luego llame a la aplicación está "
        "probando contra una base vacía — y las que esperan un 404 pasan sin "
        "mirar nada."
    )
    assert encontrada.nombre == "Visible"


def test_lo_que_una_prueba_escribe_no_sobrevive_a_la_prueba(db: Any, tenant_id: UUID) -> None:
    """La otra mitad del trato. Si sobreviviera, la prueba siguiente heredaría
    filas que no creó — y las de aislamiento, que cuentan lo que encuentran,
    empezarían a contestar distinto según el orden."""
    from sqlalchemy import func, select

    from services.party.modelos import Contacto

    cuantos = db.execute(
        select(func.count()).select_from(Contacto).where(Contacto.nombre == "Visible")
    ).scalar_one()
    assert cuantos == 0, (
        f"han quedado {cuantos} filas de la prueba anterior: el savepoint no se "
        "está deshaciendo entre pruebas"
    )
