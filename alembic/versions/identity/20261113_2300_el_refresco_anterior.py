"""Detectar la reutilización de un token de refresco ya rotado (FUN-A-3).

Guarda el hash del refresco anterior y cuándo se rotó: es lo que permite
distinguir un token robado (se revoca todo) de dos pestañas que renuevan a la
vez (se rechaza sin revocar). Columnas que admiten nulo; el downgrade las quita.

Revision ID: 9c4e2a7f1d38
Revises: 7a1d3c9e5b20
Servicio: identity
Fecha: 2026-11-13 23:00:00+00:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "9c4e2a7f1d38"
down_revision = "7a1d3c9e5b20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sesiones", sa.Column("hash_refresco_anterior", sa.String(64), nullable=True))
    op.add_column(
        "sesiones", sa.Column("refresco_rotado_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index("ix_sesiones_hash_refresco_anterior", "sesiones", ["hash_refresco_anterior"])


def downgrade() -> None:
    op.drop_index("ix_sesiones_hash_refresco_anterior", table_name="sesiones")
    op.drop_column("sesiones", "refresco_rotado_at")
    op.drop_column("sesiones", "hash_refresco_anterior")
