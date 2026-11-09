"""Jerarquía de empresas completa (CRM-00.01.03.07) y cortes de consumo para
facturación (CRM-00.01.06.07). Columnas nuevas en `tenants` —la relación con el
padre y lo que la hija le deja ver— y la tabla de cortes. El downgrade las
quita.

Revision ID: 9b1e4f20c7d3
Revises: 4c381b16a304
Servicio: tenancy
Fecha: 2026-11-09 16:00:00+00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "9b1e4f20c7d3"
down_revision = "4c381b16a304"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("relacion_padre", sa.String(length=30), nullable=True))
    op.add_column(
        "tenants",
        sa.Column(
            "comparte_con_padre",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "tenants",
        sa.Column("comparte_actualizado_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("tenants", sa.Column("comparte_actualizado_por", sa.UUID(), nullable=True))

    op.create_table(
        "cortes_consumo",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("periodo", sa.String(length=20), nullable=False),
        sa.Column("origen", sa.String(length=20), nullable=False),
        sa.Column(
            "filas",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("completo", sa.Boolean(), nullable=False),
        sa.Column(
            "no_leidos",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("estado_envio", sa.String(length=20), nullable=False),
        sa.Column("intentos", sa.Integer(), nullable=False),
        sa.Column("ultimo_error", sa.Text(), nullable=False),
        sa.Column("respuesta_codigo", sa.Integer(), nullable=True),
        sa.Column("enviado_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pedido_por", sa.UUID(), nullable=True),
        sa.Column(
            "tomado_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_cortes_consumo_tenant_id"), "cortes_consumo", ["tenant_id"], unique=False
    )
    op.create_index(
        "ix_cortes_consumo_periodo",
        "cortes_consumo",
        ["tenant_id", "periodo", "origen"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_cortes_consumo_periodo", table_name="cortes_consumo")
    op.drop_index(op.f("ix_cortes_consumo_tenant_id"), table_name="cortes_consumo")
    op.drop_table("cortes_consumo")
    op.drop_column("tenants", "comparte_actualizado_por")
    op.drop_column("tenants", "comparte_actualizado_at")
    op.drop_column("tenants", "comparte_con_padre")
    op.drop_column("tenants", "relacion_padre")
