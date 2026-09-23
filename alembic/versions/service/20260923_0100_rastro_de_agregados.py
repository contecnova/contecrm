"""Rastro completo de agregados críticos (CRM-00.05.04.06)

Revision ID: 7496c546c672
Revises: 596974f419ec
Servicio: service
Fecha: 2026-09-22 22:59:04.257381+00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "7496c546c672"
down_revision = "596974f419ec"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hechos_agregado",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("objeto", sa.String(length=60), nullable=False),
        sa.Column("objeto_id", sa.UUID(), nullable=False),
        sa.Column("secuencia", sa.Integer(), nullable=False),
        sa.Column("tipo", sa.String(length=60), nullable=False),
        sa.Column(
            "datos",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("por", sa.UUID(), nullable=True),
        sa.Column("compensa_id", sa.UUID(), nullable=True),
        sa.Column(
            "ocurrido_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_hechos_agregado")),
        sa.UniqueConstraint(
            "tenant_id", "objeto", "objeto_id", "secuencia", name="uq_hecho_secuencia"
        ),
    )
    op.create_index(
        "ix_hechos_agregado",
        "hechos_agregado",
        ["tenant_id", "objeto", "objeto_id", "secuencia"],
        unique=False,
    )
    op.create_index(
        op.f("ix_hechos_agregado_tenant_id"), "hechos_agregado", ["tenant_id"], unique=False
    )


def downgrade() -> None:
    # Un `downgrade` que no se ha probado no es un downgrade. Si esta migración
    # no se puede revertir sin pérdida de datos, dilo aquí en vez de dejar un
    # `pass` que promete algo que no cumple.
    op.drop_index(op.f("ix_hechos_agregado_tenant_id"), table_name="hechos_agregado")
    op.drop_index("ix_hechos_agregado", table_name="hechos_agregado")
    op.drop_table("hechos_agregado")
