"""El acuerdo de servicio del proveedor, frente al que prometemos (CRM-09.01.01.08).

Una tabla nueva, `acuerdos_proveedor`, con lo que sostiene cada proveedor de
servicio por contrato (respuesta, resolución, disponibilidad, cobertura), y una
columna vacía en `entitlements`, `proveedor_clave`, que dice qué proveedor da
cada derecho. Nada se rellena: sin acuerdo, la revisión lo dice. El downgrade
quita las dos cosas sin tocar nada más.

Revision ID: 4b8e2f6a1c90
Revises: caca569f16b9
Servicio: service
Fecha: 2026-11-09 19:00:00+00:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "4b8e2f6a1c90"
down_revision = "caca569f16b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "acuerdos_proveedor",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("proveedor_clave", sa.String(length=60), nullable=False),
        sa.Column("respuesta_h", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("resolucion_h", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("disponibilidad_pct", sa.Numeric(precision=6, scale=3), nullable=True),
        sa.Column("cobertura_horaria", sa.String(length=40), nullable=True),
        sa.Column("vigente_hasta", sa.Date(), nullable=True),
        sa.Column("notas", sa.Text(), nullable=False, server_default=""),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "proveedor_clave", name="uq_acuerdo_proveedor"),
    )
    op.create_index(
        op.f("ix_acuerdos_proveedor_tenant_id"), "acuerdos_proveedor", ["tenant_id"], unique=False
    )
    op.add_column("entitlements", sa.Column("proveedor_clave", sa.String(length=60), nullable=True))


def downgrade() -> None:
    op.drop_column("entitlements", "proveedor_clave")
    op.drop_index(op.f("ix_acuerdos_proveedor_tenant_id"), table_name="acuerdos_proveedor")
    op.drop_table("acuerdos_proveedor")
