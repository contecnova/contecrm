"""Jerarquía de mando y territorios replicados (CRM-00.05.02.12, CRM-00.05.02.07)

Revision ID: 77f641a100cc
Revises: 3725f65ca9a3
Servicio: sales
Fecha: 2026-09-22 19:15:18.356446+00:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "77f641a100cc"
down_revision = "3725f65ca9a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mando_replicado",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("usuario_id", sa.UUID(), nullable=False),
        sa.Column("superior_id", sa.UUID(), nullable=True),
        sa.Column(
            "actualizado_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mando_replicado")),
        sa.UniqueConstraint("tenant_id", "usuario_id", name="uq_mando_replicado"),
    )
    op.create_index(
        op.f("ix_mando_replicado_tenant_id"), "mando_replicado", ["tenant_id"], unique=False
    )
    op.create_index(
        "ix_mando_superior", "mando_replicado", ["tenant_id", "superior_id"], unique=False
    )
    op.create_table(
        "territorio_replicado",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("territorio_id", sa.UUID(), nullable=False),
        sa.Column("padre_id", sa.UUID(), nullable=True),
        sa.Column("usuario_id", sa.UUID(), nullable=True),
        sa.Column("clave", sa.String(length=80), nullable=False),
        sa.Column(
            "actualizado_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_territorio_replicado")),
        sa.UniqueConstraint(
            "tenant_id", "territorio_id", "usuario_id", name="uq_territorio_replicado"
        ),
    )
    op.create_index(
        "ix_territorio_padre", "territorio_replicado", ["tenant_id", "padre_id"], unique=False
    )
    op.create_index(
        op.f("ix_territorio_replicado_tenant_id"),
        "territorio_replicado",
        ["tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    # Un `downgrade` que no se ha probado no es un downgrade. Si esta migración
    # no se puede revertir sin pérdida de datos, dilo aquí en vez de dejar un
    # `pass` que promete algo que no cumple.
    op.drop_index(op.f("ix_territorio_replicado_tenant_id"), table_name="territorio_replicado")
    op.drop_index("ix_territorio_padre", table_name="territorio_replicado")
    op.drop_table("territorio_replicado")
    op.drop_index("ix_mando_superior", table_name="mando_replicado")
    op.drop_index(op.f("ix_mando_replicado_tenant_id"), table_name="mando_replicado")
    op.drop_table("mando_replicado")
