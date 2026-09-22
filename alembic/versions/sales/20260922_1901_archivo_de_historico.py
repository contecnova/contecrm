"""Archivo de histórico consultable (CRM-07.03.01.02)

Revision ID: 3725f65ca9a3
Revises: ba8b94193a46
Servicio: sales
Fecha: 2026-09-22 18:14:35.548390+00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "3725f65ca9a3"
down_revision = "ba8b94193a46"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "filas_archivadas",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("clase", sa.String(length=60), nullable=False),
        sa.Column("tabla", sa.String(length=80), nullable=False),
        sa.Column("registro_id", sa.UUID(), nullable=False),
        sa.Column(
            "contenido",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("fecha_original", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "archivada_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("archivada_por", sa.UUID(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_filas_archivadas")),
    )
    op.create_index(
        "ix_archivadas", "filas_archivadas", ["tenant_id", "clase", "fecha_original"], unique=False
    )
    op.create_index(
        "ix_archivadas_registro", "filas_archivadas", ["tenant_id", "registro_id"], unique=False
    )
    op.create_index(
        op.f("ix_filas_archivadas_tenant_id"), "filas_archivadas", ["tenant_id"], unique=False
    )


def downgrade() -> None:
    # Un `downgrade` que no se ha probado no es un downgrade. Si esta migración
    # no se puede revertir sin pérdida de datos, dilo aquí en vez de dejar un
    # `pass` que promete algo que no cumple.
    op.drop_index(op.f("ix_filas_archivadas_tenant_id"), table_name="filas_archivadas")
    op.drop_index("ix_archivadas_registro", table_name="filas_archivadas")
    op.drop_index("ix_archivadas", table_name="filas_archivadas")
    op.drop_table("filas_archivadas")
