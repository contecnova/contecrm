"""Sandboxes guardados, con su copia y su caducidad (CRM-07.02.01.02). Tabla
nueva: el downgrade la quita; los tenants sandbox creados se quedan, como los demás.

Revision ID: 4c381b16a304
Revises: 7095f447d671
Servicio: tenancy
Fecha: 2026-11-05 11:22:25.538136+00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "4c381b16a304"
down_revision = "7095f447d671"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sandboxes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("tenant_sandbox_id", sa.UUID(), nullable=False),
        sa.Column("nombre", sa.String(length=120), nullable=False),
        sa.Column("proposito", sa.String(length=20), nullable=False),
        sa.Column("porcentaje", sa.Integer(), nullable=False),
        sa.Column("anonimiza", sa.Boolean(), nullable=False),
        sa.Column("motivo_sin_anonimizar", sa.Text(), nullable=False),
        sa.Column("pedido_por", sa.UUID(), nullable=True),
        sa.Column("caduca_el", sa.Date(), nullable=False),
        sa.Column("estado", sa.String(length=20), nullable=False),
        sa.Column(
            "resultado",
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
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sandboxes")),
    )
    op.create_index(op.f("ix_sandboxes_tenant_id"), "sandboxes", ["tenant_id"], unique=False)


def downgrade() -> None:
    # Un `downgrade` que no se ha probado no es un downgrade. Si esta migración
    # no se puede revertir sin pérdida de datos, dilo aquí en vez de dejar un
    # `pass` que promete algo que no cumple.
    op.drop_index(op.f("ix_sandboxes_tenant_id"), table_name="sandboxes")
    op.drop_table("sandboxes")
