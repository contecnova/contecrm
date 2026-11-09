"""Cada importación hecha y lo que tocó, para poder revertirla (CRM-07.01.01.08).

Tabla nueva `importaciones`: quién importó qué, de qué fichero, y de cada
registro creado o actualizado su foto de antes y de después. Es lo que permite
deshacer una carga entera el día después. El downgrade la quita sin tocar nada
más.

Revision ID: 3b8e6f1a2c47
Revises: c5bc33443c2a
Servicio: party
Fecha: 2026-11-09 17:00:00+00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "3b8e6f1a2c47"
down_revision = "c5bc33443c2a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "importaciones",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("objeto", sa.String(length=80), nullable=False),
        sa.Column("fichero", sa.String(length=300), nullable=False),
        sa.Column("por", sa.UUID(), nullable=True),
        sa.Column("creados", sa.Integer(), nullable=False),
        sa.Column("actualizados", sa.Integer(), nullable=False),
        sa.Column("fallidos", sa.Integer(), nullable=False),
        sa.Column(
            "registros",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("revertida_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revertida_por", sa.UUID(), nullable=True),
        sa.Column(
            "reversion",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_importaciones")),
    )
    op.create_index(
        "ix_importaciones_tenant",
        "importaciones",
        ["tenant_id", "objeto", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_importaciones_tenant", table_name="importaciones")
    op.drop_table("importaciones")
