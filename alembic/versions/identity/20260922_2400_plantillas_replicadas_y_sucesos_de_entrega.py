"""Plantillas de aviso replicadas y sucesos de entrega (CRM-06.02.01.07, .08)

Revision ID: 0a2f39bd5f50
Revises: 685c01fe91fa
Servicio: identity
Fecha: 2026-09-22 19:25:16.304822+00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0a2f39bd5f50"
down_revision = "685c01fe91fa"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plantillas_notificacion_replicadas",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("clave", sa.String(length=120), nullable=False),
        sa.Column("idioma", sa.String(length=10), nullable=False),
        sa.Column("canal", sa.String(length=20), nullable=False),
        sa.Column("asunto", sa.String(length=300), nullable=False),
        sa.Column("cuerpo", sa.Text(), nullable=False),
        sa.Column(
            "variables",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("activa", sa.Boolean(), nullable=False),
        sa.Column(
            "actualizado_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plantillas_notificacion_replicadas")),
        sa.UniqueConstraint(
            "tenant_id", "clave", "idioma", "canal", name="uq_plantilla_notificacion_replicada"
        ),
    )
    op.create_index(
        op.f("ix_plantillas_notificacion_replicadas_tenant_id"),
        "plantillas_notificacion_replicadas",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_plantillas_replicadas",
        "plantillas_notificacion_replicadas",
        ["tenant_id", "clave", "canal"],
        unique=False,
    )
    op.add_column(
        "entregas_notificacion",
        sa.Column(
            "sucesos",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    # Un `downgrade` que no se ha probado no es un downgrade. Si esta migración
    # no se puede revertir sin pérdida de datos, dilo aquí en vez de dejar un
    # `pass` que promete algo que no cumple.
    op.drop_column("entregas_notificacion", "sucesos")
    op.drop_index("ix_plantillas_replicadas", table_name="plantillas_notificacion_replicadas")
    op.drop_index(
        op.f("ix_plantillas_notificacion_replicadas_tenant_id"),
        table_name="plantillas_notificacion_replicadas",
    )
    op.drop_table("plantillas_notificacion_replicadas")
