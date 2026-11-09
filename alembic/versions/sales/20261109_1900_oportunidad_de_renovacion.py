"""El contrato sabe su oportunidad de renovación (CRM-03.03.02.10).

Una columna vacía en `contratos`, `oportunidad_renovacion_id`: la oportunidad
que se abrió al llegar el preaviso. Es lo que impide que la revisión periódica
abra otra en cada pasada. Nada se rellena; el downgrade la quita.

Revision ID: 9c3f1a7e5d21
Revises: 7e1d4c2a9b30
Servicio: sales
Fecha: 2026-11-09 19:00:00+00:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "9c3f1a7e5d21"
down_revision = "7e1d4c2a9b30"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("contratos", sa.Column("oportunidad_renovacion_id", sa.UUID(), nullable=True))


def downgrade() -> None:
    op.drop_column("contratos", "oportunidad_renovacion_id")
