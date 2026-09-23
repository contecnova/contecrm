"""Salud de la cuenta replicada desde intelligence (CRM-01.01.05.07)

Una copia, no la verdad: lo justo para que quien tiene al cliente delante sepa que
tiene que mirarlo, con su fecha y su fiabilidad dentro.

Revision ID: 9e11435f55ec
Revises: 29379744df91
Servicio: party
Fecha: 2026-09-23 04:47:34.501750+00:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "9e11435f55ec"
down_revision = "29379744df91"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "salud_cuenta_replicada",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("cuenta_id", sa.UUID(), nullable=False),
        sa.Column("puntuacion", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("nivel", sa.String(length=20), nullable=False),
        sa.Column("fiable", sa.Boolean(), nullable=False),
        sa.Column("motivo", sa.Text(), nullable=False),
        sa.Column("medida_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_salud_cuenta_replicada")),
        sa.UniqueConstraint("tenant_id", "cuenta_id", name="uq_salud_replicada"),
    )
    op.create_index(
        op.f("ix_salud_cuenta_replicada_tenant_id"),
        "salud_cuenta_replicada",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_salud_replicada_nivel", "salud_cuenta_replicada", ["tenant_id", "nivel"], unique=False
    )


def downgrade() -> None:
    # Un `downgrade` que no se ha probado no es un downgrade. Si esta migración
    # no se puede revertir sin pérdida de datos, dilo aquí en vez de dejar un
    # `pass` que promete algo que no cumple.
    op.drop_index("ix_salud_replicada_nivel", table_name="salud_cuenta_replicada")
    op.drop_index(op.f("ix_salud_cuenta_replicada_tenant_id"), table_name="salud_cuenta_replicada")
    op.drop_table("salud_cuenta_replicada")
