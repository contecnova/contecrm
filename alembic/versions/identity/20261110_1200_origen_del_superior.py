"""El organigrama se fija desde Administrar (CRM-00.03.05.07): de dónde salió el
superior de cada membresía —el directorio por SCIM o a mano—, cuándo y quién.
Columnas nuevas con valor de serie; el downgrade las quita.

Revision ID: 7a1d3c9e5b20
Revises: 5154dbedd6f1
Servicio: identity
Fecha: 2026-11-10 12:00:00+00:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "7a1d3c9e5b20"
down_revision = "5154dbedd6f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "membresias",
        sa.Column(
            "superior_origen", sa.String(length=10), server_default=sa.text("''"), nullable=False
        ),
    )
    op.add_column(
        "membresias",
        sa.Column("superior_fijado_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("membresias", sa.Column("superior_fijado_por", sa.UUID(), nullable=True))


def downgrade() -> None:
    op.drop_column("membresias", "superior_fijado_por")
    op.drop_column("membresias", "superior_fijado_at")
    op.drop_column("membresias", "superior_origen")
