"""Roles del agente autónomo: con cuáles ve los campos

Un agente sin rol cae al comodín de la política de sensibilidad del tenant y
recibe los valores **tapados** —«··············tora» donde iba un nombre—, que
tienen la forma de un dato y se citan como si lo fueran. Se le declaran, igual
que los permisos, y no se heredan de quien lo puso en marcha.

Por defecto, lista vacía: un agente que ya existía sigue sin rol hasta que
alguien se lo dé. Lo contrario —darle uno al migrar— sería ampliarle lo que ve
sin que nadie lo decidiera.

Revision ID: 6ac215658a59
Revises: b1c7d3a90f42
Servicio: intelligence
Fecha: 2026-10-29 09:08:32.746478+00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "6ac215658a59"
down_revision = "b1c7d3a90f42"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agentes_ia",
        sa.Column(
            "roles",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    # Reversible sin pérdida de nada que no se pueda volver a declarar: los
    # roles de un agente son configuración, y declararlos otra vez es una
    # llamada. Probado hacia abajo y hacia arriba el 29-10-2026.
    op.drop_column("agentes_ia", "roles")
