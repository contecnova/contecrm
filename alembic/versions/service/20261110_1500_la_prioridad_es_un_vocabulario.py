"""La prioridad del caso es un vocabulario: cabe entero en su columna.

La prioridad deja de ser una lista del código y pasa a ser el vocabulario
`prioridades_caso`, que la empresa edita en Gestor de objetos. Los valores de un
vocabulario admiten hasta 120 caracteres (`valores_vocabulario.valor`), y
`casos.prioridad` era de 20: una prioridad propia más larga se aceptaría al
validar y reventaría al guardar. Se ensancha la columna, como ya se hizo con las
de los demás vocabularios.

Ensanchar un `varchar` en Postgres no reescribe la tabla. El `downgrade` lo
estrecha de nuevo y FALLA si ya hay un valor más largo: es lo correcto, porque
recortarlo cambiaría el valor por otro que no está en el vocabulario.

Revision ID: 5c9a7e2d4f13
Revises: 7d3c1e9b5a20
Servicio: service
Fecha: 2026-11-10 15:00:00+00:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "5c9a7e2d4f13"
down_revision = "7d3c1e9b5a20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "casos",
        "prioridad",
        existing_type=sa.VARCHAR(length=20),
        type_=sa.String(length=120),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "casos",
        "prioridad",
        existing_type=sa.String(length=120),
        type_=sa.VARCHAR(length=20),
        existing_nullable=False,
    )
