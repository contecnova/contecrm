"""El secreto TOTP y los códigos de recuperación que se están configurando (SEC-20).

Hasta confirmarlos con un código no sustituyen a los activos: cambiar de
autenticador y escanear mal dejaba la cuenta con un secreto sin confirmar y sin
sus códigos de recuperación. Columnas con valor de serie; el downgrade las quita.

Revision ID: 5e7a1c3d9b42
Revises: 9c4e2a7f1d38
Servicio: identity
Fecha: 2026-11-14 01:00:00+00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "5e7a1c3d9b42"
down_revision = "9c4e2a7f1d38"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("usuarios", sa.Column("mfa_secreto_pendiente", sa.Text(), nullable=True))
    op.add_column(
        "usuarios",
        sa.Column(
            "mfa_recuperacion_pendiente",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("usuarios", "mfa_recuperacion_pendiente")
    op.drop_column("usuarios", "mfa_secreto_pendiente")
