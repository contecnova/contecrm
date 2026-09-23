"""Números de campo del contrato protobuf, por tenant (CRM-00.02.01.03)

Los números se guardan porque en protobuf el nombre es cosmético y el número es
el contrato: reutilizar uno mete el valor en el campo equivocado sin error y sin
log. Lo que se borra queda en `reservados` para siempre.

Revision ID: ecc0b303cb58
Revises: c4ce50c6eb6b
Servicio: metadata
Fecha: 2026-09-23 02:58:40.967884+00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "ecc0b303cb58"
down_revision = "c4ce50c6eb6b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "contratos_rpc",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("objeto", sa.String(length=100), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "numeros",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "tipos",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "reservados",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "nombres_reservados",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contratos_rpc")),
        sa.UniqueConstraint("tenant_id", "objeto", "version", name="uq_contrato_rpc"),
    )
    op.create_index(
        op.f("ix_contratos_rpc_tenant_id"), "contratos_rpc", ["tenant_id"], unique=False
    )


def downgrade() -> None:
    # Un `downgrade` que no se ha probado no es un downgrade. Si esta migración
    # no se puede revertir sin pérdida de datos, dilo aquí en vez de dejar un
    # `pass` que promete algo que no cumple.
    op.drop_index(op.f("ix_contratos_rpc_tenant_id"), table_name="contratos_rpc")
    op.drop_table("contratos_rpc")
