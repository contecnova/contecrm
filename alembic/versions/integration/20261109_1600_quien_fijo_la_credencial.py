"""quién fijó o rotó la credencial de una conexión

Revision ID: 9c3e5a71d2b4
Revises: 2e1ae29a557e
Servicio: integration
Fecha: 2026-11-09 16:00:00+00:00

La pantalla de credenciales no enseña nunca el secreto, y por eso lo único que
puede contestar es **cuándo y quién**. El cuándo estaba (`created_at`,
`rotada_at`); el quién no se guardaba.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "9c3e5a71d2b4"
down_revision = "2e1ae29a557e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("credenciales", sa.Column("fijada_por", sa.UUID(), nullable=True))


def downgrade() -> None:
    op.drop_column("credenciales", "fijada_por")
