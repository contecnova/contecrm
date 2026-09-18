"""Aislamiento entre tenants, comprobado contra Postgres de verdad.

Cubre CRM-00.01.01.01, CRM-00.01.02.01 y CRM-00.01.02.02. Es la prueba más
importante del repositorio: si esto falla, todo lo demás da igual.

**Se ejecuta con un rol sin privilegios**, y eso no es un detalle: un SUPERUSER
—o un rol con BYPASSRLS— **ignora** las políticas aunque estén en FORCE. Una
prueba de RLS ejecutada como superusuario pasa siempre y no demuestra nada, que
es la forma más común de tener un aislamiento que solo existe sobre el papel.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
import sqlalchemy as sa

from services.tenancy.modelos import Tenant, UnidadNegocio

# Rol de aplicación de la prueba: sin SUPERUSER y sin BYPASSRLS, igual que el
# que crea `deploy/crear-bases.sh` en un despliegue real.
ROL_APP = "crm_prueba_app"


@pytest.fixture
def db_con_rls(db: Any) -> Any:
    """Prepara el esquema con RLS activada y un rol sin privilegios."""
    from crmcore.config import get_settings

    esquema = get_settings().esquema_resuelto
    db.execute(sa.text(f"CREATE ROLE {ROL_APP} NOSUPERUSER NOBYPASSRLS"))
    db.execute(sa.text(f'GRANT USAGE ON SCHEMA "{esquema}" TO {ROL_APP}'))
    db.execute(
        sa.text(
            f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "{esquema}" TO {ROL_APP}'
        )
    )

    # Se aplican las mismas políticas que en producción, con el mismo SQL: si
    # la prueba montara sus propias políticas, verificaría algo que no es lo
    # que se despliega.
    # Se aplican las MISMAS políticas que en producción, llamando al mismo
    # código (`crmcore.db.rls`). Si la prueba montara políticas «equivalentes»,
    # estaría verificando algo parecido a lo que se despliega —que es como se
    # cuela un fallo de aislamiento.
    from crmcore.db.rls import aplicar_politicas

    aplicar_politicas(db.connection(), esquema)
    db.commit()
    try:
        yield db
    finally:
        # El desmontaje tiene que ser a prueba de una prueba que falle a mitad:
        # si dejara el rol creado, la siguiente fallaría al crearlo y el motivo
        # real quedaría enterrado bajo un «role already exists».
        db.rollback()
        try:
            db.execute(sa.text("RESET ROLE"))
            db.execute(sa.text(f"DROP OWNED BY {ROL_APP}"))
            db.execute(sa.text(f"DROP ROLE IF EXISTS {ROL_APP}"))
            db.commit()
        except Exception:  # noqa: BLE001 — limpieza best-effort; el esquema se tira igual
            db.rollback()


def _como_app(db: Any, tenant_id: UUID | None) -> None:
    """Cambia al rol sin privilegios y fija el tenant de la sesión."""
    db.execute(sa.text(f"SET ROLE {ROL_APP}"))
    db.execute(
        sa.text("SELECT set_config('app.current_tenant', :t, false)"),
        {"t": str(tenant_id) if tenant_id else ""},
    )


def _como_sistema(db: Any) -> None:
    db.execute(sa.text("RESET ROLE"))
    db.execute(sa.text("SELECT set_config('app.current_tenant', '', false)"))


def test_un_tenant_no_ve_los_datos_de_otro(
    db_con_rls: Any, tenant_id: UUID, otro_tenant_id: UUID
) -> None:
    """CRM-00.01.02.01: el motor no devuelve filas de otro tenant."""
    db = db_con_rls
    _como_sistema(db)
    db.add_all(
        [
            Tenant(id=tenant_id, slug="uno", nombre="Uno"),
            Tenant(id=otro_tenant_id, slug="dos", nombre="Dos"),
            UnidadNegocio(tenant_id=tenant_id, codigo="a", nombre="Unidad de Uno"),
            UnidadNegocio(tenant_id=otro_tenant_id, codigo="b", nombre="Unidad de Dos"),
        ]
    )
    db.commit()

    _como_app(db, tenant_id)
    visibles = db.execute(sa.select(UnidadNegocio.nombre)).scalars().all()
    assert visibles == ["Unidad de Uno"], f"se ven datos ajenos: {visibles}"

    _como_app(db, otro_tenant_id)
    visibles = db.execute(sa.select(UnidadNegocio.nombre)).scalars().all()
    assert visibles == ["Unidad de Dos"], f"se ven datos ajenos: {visibles}"
    _como_sistema(db)


def test_no_se_puede_escribir_con_el_tenant_de_otro(
    db_con_rls: Any, tenant_id: UUID, otro_tenant_id: UUID
) -> None:
    """El `WITH CHECK` de la política: una fuga de ESCRITURA es peor que una de lectura.

    Sin `WITH CHECK`, un tenant no puede leer lo ajeno pero sí puede insertar
    filas marcadas con el `tenant_id` de otro — y esas filas aparecerían en el
    CRM del otro cliente como si fueran suyas.
    """
    db = db_con_rls
    _como_sistema(db)
    db.add_all(
        [
            Tenant(id=tenant_id, slug="uno", nombre="Uno"),
            Tenant(id=otro_tenant_id, slug="dos", nombre="Dos"),
        ]
    )
    db.commit()

    _como_app(db, tenant_id)
    # El identificador se genera en Python y no con `gen_random_uuid()`: el
    # Postgres embebido de las pruebas no trae pgcrypto, y lo que esta prueba
    # comprueba es la política, no de dónde sale el UUID.
    from crmcore.ids import nuevo_id

    with pytest.raises(sa.exc.ProgrammingError) as exc:
        db.execute(
            sa.text(
                "INSERT INTO unidades_negocio (id, tenant_id, codigo, nombre, activa, "
                "created_at, updated_at) "
                "VALUES (CAST(:id AS uuid), CAST(:t AS uuid), 'x', 'intrusa', true, now(), now())"
            ).bindparams(id=str(nuevo_id()), t=str(otro_tenant_id))
        )
    assert "row-level security" in str(exc.value).lower()
    db.rollback()
    _como_sistema(db)


def test_el_contexto_de_sistema_ve_todo(
    db_con_rls: Any, tenant_id: UUID, otro_tenant_id: UUID
) -> None:
    """Sin GUC fijado, la política es permisiva: es el camino de migraciones.

    Está pensado así a propósito, y lo que impide usarlo por descuido no es la
    política sino el código: abrir una sesión sin tenant exige escribir
    `sistema=True` (ver `crmcore.db.session.nueva_sesion`).
    """
    db = db_con_rls
    _como_sistema(db)
    db.add_all(
        [
            Tenant(id=tenant_id, slug="uno", nombre="Uno"),
            Tenant(id=otro_tenant_id, slug="dos", nombre="Dos"),
            UnidadNegocio(tenant_id=tenant_id, codigo="a", nombre="De Uno"),
            UnidadNegocio(tenant_id=otro_tenant_id, codigo="b", nombre="De Dos"),
        ]
    )
    db.commit()

    _como_app(db, None)  # rol sin privilegios, pero sin tenant fijado
    visibles = db.execute(sa.select(UnidadNegocio.nombre)).scalars().all()
    assert sorted(visibles) == ["De Dos", "De Uno"]
    _como_sistema(db)


def test_el_guc_no_se_hereda_entre_transacciones(
    db_con_rls: Any, tenant_id: UUID, otro_tenant_id: UUID
) -> None:
    """El tenant de una petición no puede filtrarse a la siguiente.

    Es el modo de fallo más peligroso de todos: silencioso, intermitente y entre
    clientes. Lo que lo impide es que `crmcore.db.session` fija el GUC al
    empezar CADA transacción, también cuando no hay tenant.
    """
    db = db_con_rls
    _como_sistema(db)
    db.add_all(
        [
            Tenant(id=tenant_id, slug="uno", nombre="Uno"),
            Tenant(id=otro_tenant_id, slug="dos", nombre="Dos"),
            UnidadNegocio(tenant_id=tenant_id, codigo="a", nombre="De Uno"),
        ]
    )
    db.commit()

    # Primera «petición»: con tenant, dentro de una transacción.
    db.execute(sa.text(f"SET ROLE {ROL_APP}"))
    db.execute(
        sa.text("SELECT set_config('app.current_tenant', :t, true)"),
        {"t": str(tenant_id)},
    )
    assert db.execute(sa.select(sa.func.count()).select_from(UnidadNegocio)).scalar_one() == 1
    db.commit()  # termina la transacción: el ajuste local muere con ella

    # Segunda «petición» sobre la MISMA conexión, ahora del otro tenant.
    db.execute(
        sa.text("SELECT set_config('app.current_tenant', :t, true)"),
        {"t": str(otro_tenant_id)},
    )
    visibles = db.execute(sa.select(UnidadNegocio.nombre)).scalars().all()
    assert visibles == [], f"el tenant anterior se ha filtrado: {visibles}"
    db.commit()
    _como_sistema(db)
