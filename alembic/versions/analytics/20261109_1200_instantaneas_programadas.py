"""instantaneas programadas por informe

Una programacion de informe hacia una sola cosa: mandarlo. Las instantaneas
(CRM-05.01.01.05) solo se tomaban a mano —`POST /informes/{id}/instantanea`—, y
una serie historica que depende de que alguien se acuerde cada lunes tiene
huecos justo las semanas que mas importan. Ahora una programacion dice QUE hace:
`enviar` (lo de siempre) o `instantanea` (guardar lo que dice el informe ese
dia), y el barrido de programadas que ya existia la ejecuta.

`enviar` por defecto: las programaciones que ya existen siguen haciendo
exactamente lo que hacian.

Revision ID: 7c1f0a9b2d34
Revises: 4a6033543e57
Servicio: analytics
Fecha: 2026-11-09 12:00:00+00:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "7c1f0a9b2d34"
down_revision = "4a6033543e57"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "programaciones_informe",
        sa.Column("accion", sa.String(length=20), nullable=False, server_default="enviar"),
    )


def downgrade() -> None:
    # Se pierde qué programaciones eran de instantánea: vuelven a ser envíos sin
    # destino, que el barrido rechazaría. Por eso se borran antes de quitar la
    # columna, y se dice aquí.
    op.execute("DELETE FROM programaciones_informe WHERE accion = 'instantanea'")
    op.drop_column("programaciones_informe", "accion")
