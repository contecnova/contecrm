"""suscripciones a cuadros con canal, dia y rastro de la ultima

Las suscripciones a cuadros de mando (CRM-05.01.02.05) guardaban una hora y una
proxima ejecucion y ningun barrido las ejecutaba. Ahora las corre la tarea
`analytics.suscripciones_cuadro` y necesitan:

- `canal`: por donde llega (app, correo, push, sms, webhook). `app` por
  defecto: las que ya existen siguen sin mandar correo que nadie pidio.
- `dia_semana` y `dia_mes`: como una programacion de informe, porque la
  proxima se calcula con el mismo `_siguiente_ejecucion`.
- `ultima_at` y `ultimo_error`: cuando corrio y, si se apago, por que.

Revision ID: 8d2a1b3c4e56
Revises: 7c1f0a9b2d34
Servicio: analytics
Fecha: 2026-11-10 18:00:00+00:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "8d2a1b3c4e56"
down_revision = "7c1f0a9b2d34"
branch_labels = None
depends_on = None

TABLA = "suscripciones_cuadro"


def upgrade() -> None:
    op.add_column(
        TABLA, sa.Column("canal", sa.String(length=20), nullable=False, server_default="app")
    )
    op.add_column(TABLA, sa.Column("dia_semana", sa.Integer(), nullable=True))
    op.add_column(TABLA, sa.Column("dia_mes", sa.Integer(), nullable=True))
    op.add_column(TABLA, sa.Column("ultima_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(TABLA, sa.Column("ultimo_error", sa.String(length=1000), nullable=True))


def downgrade() -> None:
    for columna in ("ultimo_error", "ultima_at", "dia_mes", "dia_semana", "canal"):
        op.drop_column(TABLA, columna)
