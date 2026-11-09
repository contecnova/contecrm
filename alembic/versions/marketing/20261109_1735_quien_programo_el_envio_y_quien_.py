"""quien programo el envio y quien publico el recorrido

Los envios programados y los pasos de los recorridos solo corrian cuando alguien
pulsaba el boton. Para que salgan solos, cada uno tiene que actuar con la
identidad de quien lo lanzo —con sus permisos de entonces, en foto— y hasta hoy
no se guardaba. Un envio o un recorrido anterior a esta migracion queda sin
ella: no sale solo y lo dice, en vez de inventar con que permisos actuar.

Revision ID: 9c1e7a4b2d30
Revises: 2796c0098943
Servicio: marketing
Fecha: 2026-11-09 17:35:00.000000+00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "9c1e7a4b2d30"
down_revision = "2796c0098943"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("envios_programados", sa.Column("programado_por_id", sa.UUID(), nullable=True))
    op.add_column(
        "envios_programados",
        sa.Column(
            "programado_con",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column("recorridos", sa.Column("publicado_por_id", sa.UUID(), nullable=True))
    op.add_column(
        "recorridos",
        sa.Column(
            "publicado_con",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    # Se pierde quién programó y quién publicó: sin ello nada sale solo, que es
    # exactamente el estado de antes de esta migración.
    op.drop_column("recorridos", "publicado_con")
    op.drop_column("recorridos", "publicado_por_id")
    op.drop_column("envios_programados", "programado_con")
    op.drop_column("envios_programados", "programado_por_id")
