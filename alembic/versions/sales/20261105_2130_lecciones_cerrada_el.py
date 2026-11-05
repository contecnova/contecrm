"""Lecciones aprendidas: cuándo se cerró la oportunidad y por cuánto.

La lista se ordenaba por el alta de la lección, y las históricas nacen todas el
mismo día. Las que ya existen se rellenan desde su oportunidad.

Revision ID: 7c2e9a41d5b3
Revises: 3b1444eb76f0
Servicio: sales
Fecha: 2026-11-05 21:30:00+00:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "7c2e9a41d5b3"
down_revision = "3b1444eb76f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("lecciones_oportunidad", sa.Column("cerrada_el", sa.Date(), nullable=True))
    op.add_column("lecciones_oportunidad", sa.Column("importe", sa.Numeric(18, 2), nullable=True))
    op.execute(
        """
        UPDATE lecciones_oportunidad l
           SET cerrada_el = COALESCE(o.fecha_cierre_real, l.created_at::date),
               importe = o.importe
          FROM oportunidades o
         WHERE o.id = l.oportunidad_id
        """
    )
    op.execute(
        "UPDATE lecciones_oportunidad SET cerrada_el = created_at::date WHERE cerrada_el IS NULL"
    )
    op.alter_column("lecciones_oportunidad", "cerrada_el", nullable=False)
    op.create_index(
        op.f("ix_lecciones_oportunidad_cerrada_el"),
        "lecciones_oportunidad",
        ["cerrada_el"],
        unique=False,
    )


def downgrade() -> None:
    # Se pierde sólo lo copiado: sigue en la oportunidad.
    op.drop_index(op.f("ix_lecciones_oportunidad_cerrada_el"), table_name="lecciones_oportunidad")
    op.drop_column("lecciones_oportunidad", "importe")
    op.drop_column("lecciones_oportunidad", "cerrada_el")
