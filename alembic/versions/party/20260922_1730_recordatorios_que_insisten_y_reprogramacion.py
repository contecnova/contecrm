"""Recordatorios que insisten y reprogramación automática (CRM-01.02.01.09)

Revision ID: 66a6341f4171
Revises: 9a7818379124
Servicio: party
Fecha: 2026-09-22 17:14:46.090916+00:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "66a6341f4171"
down_revision = "9a7818379124"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("actividades", sa.Column("repetir_cada_min", sa.Integer(), nullable=True))
    op.add_column("actividades", sa.Column("avisos_enviados", sa.Integer(), nullable=False))
    op.add_column("actividades", sa.Column("max_avisos", sa.Integer(), nullable=True))
    op.add_column("actividades", sa.Column("reprogramar_cada_dias", sa.Integer(), nullable=True))
    op.add_column("actividades", sa.Column("veces_reprogramada", sa.Integer(), nullable=False))
    op.add_column("actividades", sa.Column("max_reprogramaciones", sa.Integer(), nullable=True))


def downgrade() -> None:
    # Un `downgrade` que no se ha probado no es un downgrade. Si esta migración
    # no se puede revertir sin pérdida de datos, dilo aquí en vez de dejar un
    # `pass` que promete algo que no cumple.
    op.drop_column("actividades", "max_reprogramaciones")
    op.drop_column("actividades", "veces_reprogramada")
    op.drop_column("actividades", "reprogramar_cada_dias")
    op.drop_column("actividades", "max_avisos")
    op.drop_column("actividades", "avisos_enviados")
    op.drop_column("actividades", "repetir_cada_min")
