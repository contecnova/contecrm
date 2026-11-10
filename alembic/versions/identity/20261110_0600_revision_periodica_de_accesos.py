"""Revisión periódica de accesos (CRM-07.03.02.15): campañas con plazo y una
revisión por cada rol o conjunto de permisos de cada persona, asignada a su
responsable. Tablas nuevas; el downgrade las quita.

Revision ID: 5154dbedd6f1
Revises: c0ea9c5680ef
Servicio: identity
Fecha: 2026-11-10 06:00:14.084582+00:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "5154dbedd6f1"
down_revision = "c0ea9c5680ef"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recert_campanas",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("nombre", sa.String(length=200), nullable=False),
        sa.Column("plazo_at", sa.Date(), nullable=False),
        sa.Column(
            "estado", sa.String(length=20), server_default=sa.text("'abierta'"), nullable=False
        ),
        sa.Column("revisor_por_defecto", sa.UUID(), nullable=True),
        sa.Column("creada_por", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("cerrada_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recert_campanas")),
    )
    op.create_index("ix_recert_campanas", "recert_campanas", ["tenant_id", "estado"], unique=False)
    op.create_table(
        "recert_revisiones",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("campana_id", sa.UUID(), nullable=False),
        sa.Column("responsable_id", sa.UUID(), nullable=False),
        sa.Column("usuario_id", sa.UUID(), nullable=False),
        sa.Column("tipo", sa.String(length=20), nullable=False),
        sa.Column("valor", sa.String(length=120), nullable=False),
        sa.Column(
            "decision", sa.String(length=20), server_default=sa.text("'pendiente'"), nullable=False
        ),
        sa.Column("comentario", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("decidido_por", sa.UUID(), nullable=True),
        sa.Column("decidido_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("vencida_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recert_revisiones")),
    )
    op.create_index(
        "ix_recert_revisiones_campana",
        "recert_revisiones",
        ["tenant_id", "campana_id"],
        unique=False,
    )
    op.create_index(
        "ix_recert_revisiones_responsable",
        "recert_revisiones",
        ["tenant_id", "responsable_id", "decision"],
        unique=False,
    )


def downgrade() -> None:
    # Revertir pierde el historial de las campañas; los accesos retirados no
    # vuelven, porque la retirada ya se aplicó en las membresías.
    op.drop_index("ix_recert_revisiones_responsable", table_name="recert_revisiones")
    op.drop_index("ix_recert_revisiones_campana", table_name="recert_revisiones")
    op.drop_table("recert_revisiones")
    op.drop_index("ix_recert_campanas", table_name="recert_campanas")
    op.drop_table("recert_campanas")
