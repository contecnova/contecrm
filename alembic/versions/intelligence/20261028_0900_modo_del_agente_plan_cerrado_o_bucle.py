"""modo del agente: plan cerrado o bucle

Revision ID: b1c7d3a90f42
Revises: e5f99c4587f3
Servicio: intelligence
Fecha: 2026-10-28
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "b1c7d3a90f42"
down_revision = "e5f99c4587f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # `plan_cerrado` como valor del servidor y no sólo del modelo: los agentes
    # ya declarados tienen que seguir comportándose igual que ayer. Un modo por
    # defecto distinto les cambiaría la forma de decidir sin que nadie lo
    # pidiera, y es lo que más cuesta explicar después.
    op.add_column(
        "agentes_ia",
        sa.Column(
            "modo",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'plan_cerrado'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("agentes_ia", "modo")
