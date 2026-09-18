"""Aplicación de Row-Level Security, en un solo sitio.

Esto era un fichero `.sql` con un bloque `DO $$` que generaba las políticas con
`format()` y comillas anidadas. Tenía dos problemas, y el segundo es el grave:

  * Las comillas escapadas dentro de `format()` son casi imposibles de leer y se
    rompen con cambiar una coma — pasó al escribir la prueba de aislamiento.
  * **No lo probaba nadie.** El fichero se aplicaba en el despliegue y la prueba
    montaba sus propias políticas «equivalentes»: se estaba verificando algo
    parecido a lo que se despliega, que es exactamente como se cuela un fallo de
    aislamiento.

Ahora hay una sola implementación, en Python, que usan el despliegue
(`scripts/aplicar_rls.py`) y la prueba (`tests/integration/test_rls_aislamiento.py`).
Lo que se prueba es lo que se despliega.

Ver `deploy/sql/rls.sql` para la explicación de por qué RLS y de su limitación
con roles SUPERUSER.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from crmcore.logging import get_logger

logger = get_logger(__name__)

NOMBRE_POLITICA = "aislamiento_tenant"

# La condición de la política, tal cual va a la base. Está escrita una vez y se
# usa en `USING` y en `WITH CHECK`, que tienen que decir lo mismo: `USING` filtra
# lo que se lee y `WITH CHECK` lo que se escribe. Con solo `USING`, un tenant no
# puede LEER lo ajeno pero sí puede INSERTAR filas con el `tenant_id` de otro, y
# esas filas aparecerían en el CRM del otro cliente como suyas.
CONDICION = (
    "tenant_id::text = current_setting('app.current_tenant', true) "
    "OR coalesce(current_setting('app.current_tenant', true), '') = ''"
)


def tablas_con_tenant(conexion: Any, esquema: str) -> list[str]:
    """Tablas del esquema que tienen columna `tenant_id`."""
    filas = conexion.execute(
        text(
            """
            SELECT c.relname
              FROM pg_class c
              JOIN pg_namespace n ON n.oid = c.relnamespace
              JOIN pg_attribute a ON a.attrelid = c.oid
             WHERE n.nspname = :esquema
               AND c.relkind = 'r'
               AND a.attname = 'tenant_id'
               AND NOT a.attisdropped
             ORDER BY c.relname
            """
        ),
        {"esquema": esquema},
    ).all()
    return [f[0] for f in filas]


def aplicar_politicas(conexion: Any, esquema: str) -> list[str]:
    """Activa RLS FORCE y la política de aislamiento en todo el esquema.

    Idempotente: se puede ejecutar después de cada migración. Devuelve las
    tablas tocadas.
    """
    tablas = tablas_con_tenant(conexion, esquema)
    for tabla in tablas:
        ref = f'"{esquema}"."{tabla}"'
        conexion.execute(text(f"ALTER TABLE {ref} ENABLE ROW LEVEL SECURITY"))
        # FORCE: sin él, el DUEÑO de la tabla se salta su propia política, y el
        # dueño es el rol de migración. Con FORCE, ni el dueño ve de más.
        conexion.execute(text(f"ALTER TABLE {ref} FORCE ROW LEVEL SECURITY"))
        conexion.execute(text(f"DROP POLICY IF EXISTS {NOMBRE_POLITICA} ON {ref}"))
        conexion.execute(
            text(
                f"CREATE POLICY {NOMBRE_POLITICA} ON {ref} "
                f"USING ({CONDICION}) WITH CHECK ({CONDICION})"
            )
        )
    logger.info("rls.aplicada", esquema=esquema, tablas=len(tablas))
    return tablas


def tablas_sin_politica(conexion: Any, esquema: str) -> list[str]:
    """Tablas con `tenant_id` a las que les falta la política.

    Lo usa el gate: una tabla nueva sin política es un agujero de aislamiento
    que no da ningún síntoma hasta que dos clientes se ven los datos.
    """
    filas = conexion.execute(
        text(
            """
            SELECT c.relname
              FROM pg_class c
              JOIN pg_namespace n ON n.oid = c.relnamespace
              JOIN pg_attribute a ON a.attrelid = c.oid
             WHERE n.nspname = :esquema
               AND c.relkind = 'r'
               AND a.attname = 'tenant_id'
               AND NOT a.attisdropped
               AND (
                 NOT c.relrowsecurity
                 OR NOT c.relforcerowsecurity
                 OR NOT EXISTS (
                   SELECT 1 FROM pg_policy p
                    WHERE p.polrelid = c.oid AND p.polname = :politica
                 )
               )
             ORDER BY c.relname
            """
        ),
        {"esquema": esquema, "politica": NOMBRE_POLITICA},
    ).all()
    return [f[0] for f in filas]
