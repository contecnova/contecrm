"""Un valor de vocabulario cabe entero en la columna que lo guarda.

Los vocabularios del cliente admiten valores de hasta 120 caracteres
(`valores_vocabulario.valor`), y las columnas que guardan el valor elegido
eran más estrechas: un rol o una función de más de 20 se aceptaba al validar y
reventaba al guardar. Se ensanchan las columnas en vez de recortar el
vocabulario, porque el vocabulario es común a todos y cada columna tenía su
propio tope. `llamadas_telefonicas.resultado_comercial` pasa de 40 a 120.

Ensanchar un `varchar` en Postgres no reescribe la tabla. El `downgrade` lo
estrecha de nuevo y FALLA si ya hay un valor más largo: es lo correcto, porque
recortarlo cambiaría el valor por otro que no está en el vocabulario.

Revision ID: 5bf60621ec37
Revises: ec8575af15f3
Servicio: integration
Fecha: 2026-11-10 10:10:34.391919+00:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "5bf60621ec37"
down_revision = "ec8575af15f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "llamadas_telefonicas",
        "resultado_comercial",
        existing_type=sa.VARCHAR(length=40),
        type_=sa.String(length=120),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "llamadas_telefonicas",
        "resultado_comercial",
        existing_type=sa.String(length=120),
        type_=sa.VARCHAR(length=40),
        existing_nullable=True,
    )
