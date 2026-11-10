"""Un valor de vocabulario cabe entero en la columna que lo guarda.

Los vocabularios del cliente admiten valores de hasta 120 caracteres
(`valores_vocabulario.valor`), y las columnas que guardan el valor elegido
eran más estrechas: un rol o una función de más de 20 se aceptaba al validar y
reventaba al guardar. Se ensanchan las columnas en vez de recortar el
vocabulario, porque el vocabulario es común a todos y cada columna tenía su
propio tope. `roles_compra.rol` (20), `leads.motivo_descarte`, `oportunidades.motivo_perdida` y `lecciones_oportunidad.motivo` (80) pasan a 120.

Ensanchar un `varchar` en Postgres no reescribe la tabla. El `downgrade` lo
estrecha de nuevo y FALLA si ya hay un valor más largo: es lo correcto, porque
recortarlo cambiaría el valor por otro que no está en el vocabulario.

Revision ID: 732bfdc606d2
Revises: 4b7d2e9a1c63
Servicio: sales
Fecha: 2026-11-10 10:10:39.220359+00:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "732bfdc606d2"
down_revision = "4b7d2e9a1c63"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "leads",
        "motivo_descarte",
        existing_type=sa.VARCHAR(length=80),
        type_=sa.String(length=120),
        existing_nullable=True,
    )
    op.alter_column(
        "lecciones_oportunidad",
        "motivo",
        existing_type=sa.VARCHAR(length=80),
        type_=sa.String(length=120),
        existing_nullable=True,
    )
    op.alter_column(
        "oportunidades",
        "motivo_perdida",
        existing_type=sa.VARCHAR(length=80),
        type_=sa.String(length=120),
        existing_nullable=True,
    )
    op.alter_column(
        "roles_compra",
        "rol",
        existing_type=sa.VARCHAR(length=20),
        type_=sa.String(length=120),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "roles_compra",
        "rol",
        existing_type=sa.String(length=120),
        type_=sa.VARCHAR(length=20),
        existing_nullable=False,
    )
    op.alter_column(
        "oportunidades",
        "motivo_perdida",
        existing_type=sa.String(length=120),
        type_=sa.VARCHAR(length=80),
        existing_nullable=True,
    )
    op.alter_column(
        "lecciones_oportunidad",
        "motivo",
        existing_type=sa.String(length=120),
        type_=sa.VARCHAR(length=80),
        existing_nullable=True,
    )
    op.alter_column(
        "leads",
        "motivo_descarte",
        existing_type=sa.String(length=120),
        type_=sa.VARCHAR(length=80),
        existing_nullable=True,
    )
