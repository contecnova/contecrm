"""quién lanzó cada instancia y con qué permisos actúa

Los pasos «servicio» llaman a la API del CRM en nombre de quien lanzó el
proceso. Esa identidad tiene que guardarse al arrancar: el proceso sigue días
después, cuando la petición que lo pidió ya no existe.

Revision ID: da41584730f7
Revises: 969e3de452c9
Servicio: orchestrator
Fecha: 2026-11-09 12:00:00+00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "da41584730f7"
down_revision = "969e3de452c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("instancias_proceso", sa.Column("lanzada_por", sa.UUID(), nullable=True))
    # NULL a propósito en las que ya existen: no se sabe quién las lanzó, y
    # rellenarlo con alguien sería inventarse con qué permisos actúan.
    op.add_column(
        "instancias_proceso",
        sa.Column(
            "permisos_de_lanzamiento",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("instancias_proceso", "permisos_de_lanzamiento")
    op.drop_column("instancias_proceso", "lanzada_por")
