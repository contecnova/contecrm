"""Métricas del cliente traídas de otros sistemas (CRM-01.01.05.06)

Cada una con de cuándo es y de dónde viene: un margen sin fecha se lee como el de
hoy, y lo que no ha llegado no vale cero.

Revision ID: e0241621eebc
Revises: 9e11435f55ec
Servicio: party
Fecha: 2026-09-23 05:02:36.385377+00:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "e0241621eebc"
down_revision = "9e11435f55ec"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "metricas_cuenta",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("cuenta_id", sa.UUID(), nullable=False),
        sa.Column("clave", sa.String(length=40), nullable=False),
        sa.Column("valor", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("moneda", sa.String(length=3), nullable=False),
        sa.Column("vigente_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("origen", sa.String(length=80), nullable=False),
        sa.Column("nota", sa.Text(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_metricas_cuenta")),
        sa.UniqueConstraint("tenant_id", "cuenta_id", "clave", name="uq_metrica_cuenta"),
    )
    op.create_index(
        "ix_metricas_cuenta", "metricas_cuenta", ["tenant_id", "cuenta_id"], unique=False
    )
    op.create_index(
        op.f("ix_metricas_cuenta_tenant_id"), "metricas_cuenta", ["tenant_id"], unique=False
    )


def downgrade() -> None:
    # Un `downgrade` que no se ha probado no es un downgrade. Si esta migración
    # no se puede revertir sin pérdida de datos, dilo aquí en vez de dejar un
    # `pass` que promete algo que no cumple.
    op.drop_index(op.f("ix_metricas_cuenta_tenant_id"), table_name="metricas_cuenta")
    op.drop_index("ix_metricas_cuenta", table_name="metricas_cuenta")
    op.drop_table("metricas_cuenta")
