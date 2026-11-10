"""Un valor de vocabulario cabe entero en la columna que lo guarda.

Los vocabularios del cliente admiten valores de hasta 120 caracteres
(`valores_vocabulario.valor`), y las columnas que guardan el valor elegido
eran más estrechas: un rol o una función de más de 20 se aceptaba al validar y
reventaba al guardar. Se ensanchan las columnas en vez de recortar el
vocabulario, porque el vocabulario es común a todos y cada columna tenía su
propio tope. `contactos_proveedor.funcion` (20), `equipo_cuenta.rol` (40) y `relaciones_persona.tipo` (20) pasan a 120.

Ensanchar un `varchar` en Postgres no reescribe la tabla. El `downgrade` lo
estrecha de nuevo y FALLA si ya hay un valor más largo: es lo correcto, porque
recortarlo cambiaría el valor por otro que no está en el vocabulario.

Revision ID: 2e1f32f0fadd
Revises: 9d2e4c7b1a60
Servicio: party
Fecha: 2026-11-10 10:10:36.650758+00:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "2e1f32f0fadd"
down_revision = "9d2e4c7b1a60"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "contactos_proveedor",
        "funcion",
        existing_type=sa.VARCHAR(length=20),
        type_=sa.String(length=120),
        existing_nullable=False,
    )
    op.alter_column(
        "equipo_cuenta",
        "rol",
        existing_type=sa.VARCHAR(length=40),
        type_=sa.String(length=120),
        existing_nullable=False,
    )
    op.alter_column(
        "relaciones_persona",
        "tipo",
        existing_type=sa.VARCHAR(length=20),
        type_=sa.String(length=120),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "relaciones_persona",
        "tipo",
        existing_type=sa.String(length=120),
        type_=sa.VARCHAR(length=20),
        existing_nullable=False,
    )
    op.alter_column(
        "equipo_cuenta",
        "rol",
        existing_type=sa.String(length=120),
        type_=sa.VARCHAR(length=40),
        existing_nullable=False,
    )
    op.alter_column(
        "contactos_proveedor",
        "funcion",
        existing_type=sa.String(length=120),
        type_=sa.VARCHAR(length=20),
        existing_nullable=False,
    )
