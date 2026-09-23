"""Tarifas de coste sobre el mismo motor de precios (CRM-09.02.01.01)

Dos columnas en `listas_precio` en vez de un motor paralelo: uno para costes
acabaría con dos formas de escalar por volumen y dos maneras de resolver la
vigencia, y una de las dos se quedaría atrás.

Revision ID: bd50c599fe59
Revises: 90db623d5499
Servicio: sales
Fecha: 2026-09-23 04:31:00.731190+00:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "bd50c599fe59"
down_revision = "90db623d5499"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "listas_precio",
        sa.Column(
            "sentido", sa.String(length=10), server_default=sa.text("'venta'"), nullable=False
        ),
    )
    op.add_column("listas_precio", sa.Column("proveedor_id", sa.UUID(), nullable=True))
    op.create_index(
        op.f("ix_listas_precio_proveedor_id"), "listas_precio", ["proveedor_id"], unique=False
    )


def downgrade() -> None:
    # Un `downgrade` que no se ha probado no es un downgrade. Si esta migración
    # no se puede revertir sin pérdida de datos, dilo aquí en vez de dejar un
    # `pass` que promete algo que no cumple.
    op.drop_index(op.f("ix_listas_precio_proveedor_id"), table_name="listas_precio")
    op.drop_column("listas_precio", "proveedor_id")
    op.drop_column("listas_precio", "sentido")
