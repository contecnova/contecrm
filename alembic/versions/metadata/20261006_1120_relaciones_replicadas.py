"""las relaciones del objeto, replicadas con su esquema

Revision ID: 59e271b175e7
Revises: 53406b10e92a
Servicio: metadata
Fecha: 2026-10-06 11:20:00.000000+00:00

Una relación polimórfica dice a qué puede apuntar una referencia, y esa
comprobación estaba escrita en `metadata` —donde se declaran— sin que la llamara
nadie: quien escribe los valores son los otros servicios, y ninguno lee ese
esquema. Ahora las relaciones del objeto viajan replicadas con sus campos, por el
mismo camino, y la comprobación se hace donde se escribe.

Vacío es **sin acotar**, no «no admite ninguno»: una relación que no declara
destino acepta cualquiera a propósito.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "59e271b175e7"
down_revision = "53406b10e92a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "esquemas_tenant",
        sa.Column(
            "relaciones",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("esquemas_tenant", "relaciones")
