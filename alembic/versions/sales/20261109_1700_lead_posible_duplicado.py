"""El lead que entra parecido a otro queda señalado (CRM-01.01.03.03).

Dos columnas en `leads`: a qué se parece (`duplicado_de_id`) y por qué
(`duplicado_detalle`). Las escribe la captura automática, donde no hay nadie a
quien preguntar: el lead se crea y una persona decide. Columnas nuevas y
vacías; el downgrade las quita sin tocar nada más.

Revision ID: 7e1d4c2a9b30
Revises: 2a7c5e9f3b10
Servicio: sales
Fecha: 2026-11-09 17:00:00+00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "7e1d4c2a9b30"
down_revision = "2a7c5e9f3b10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("leads", sa.Column("duplicado_de_id", sa.UUID(), nullable=True))
    op.add_column(
        "leads",
        sa.Column(
            "duplicado_detalle",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("leads", "duplicado_detalle")
    op.drop_column("leads", "duplicado_de_id")
