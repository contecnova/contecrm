"""Limitación de tratamiento y archivo de histórico (CRM-02.04.02.05, CRM-07.03.01.02)

Revision ID: 13c7597f9c8f
Revises: 66a6341f4171
Servicio: party
Fecha: 2026-09-22 18:14:33.475387+00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "13c7597f9c8f"
down_revision = "66a6341f4171"
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
    op.create_table(
        "limitaciones_tratamiento",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("contacto_id", sa.UUID(), nullable=False),
        sa.Column(
            "tratamientos",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("motivo", sa.String(length=40), nullable=False),
        sa.Column("detalle", sa.Text(), nullable=False),
        sa.Column("solicitud_id", sa.UUID(), nullable=True),
        sa.Column("activa", sa.Boolean(), nullable=False),
        sa.Column(
            "desde", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("hasta", sa.DateTime(timezone=True), nullable=True),
        sa.Column("motivo_levantamiento", sa.Text(), nullable=False),
        sa.Column("puesta_por", sa.UUID(), nullable=True),
        sa.Column("levantada_por", sa.UUID(), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_limitaciones_tratamiento")),
    )
    op.create_index(
        "ix_limitaciones_activas",
        "limitaciones_tratamiento",
        ["tenant_id", "contacto_id", "activa"],
        unique=False,
    )
    op.create_index(
        op.f("ix_limitaciones_tratamiento_tenant_id"),
        "limitaciones_tratamiento",
        ["tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    # Un `downgrade` que no se ha probado no es un downgrade. Si esta migración
    # no se puede revertir sin pérdida de datos, dilo aquí en vez de dejar un
    # `pass` que promete algo que no cumple.
    op.drop_index(
        op.f("ix_limitaciones_tratamiento_tenant_id"), table_name="limitaciones_tratamiento"
    )
    op.drop_index("ix_limitaciones_activas", table_name="limitaciones_tratamiento")
    op.drop_table("limitaciones_tratamiento")
    op.drop_index(op.f("ix_filas_archivadas_tenant_id"), table_name="filas_archivadas")
    op.drop_index("ix_archivadas_registro", table_name="filas_archivadas")
    op.drop_index("ix_archivadas", table_name="filas_archivadas")
    op.drop_table("filas_archivadas")
