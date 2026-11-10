"""Las señales de identidad siguen a su contacto a la papelera.

Las señales se anotan solas al guardar un contacto con correo o teléfono, y
contaban como dependencia: ningún contacto así se podía borrar (409 por
`senales_identidad`). Ahora son parte del contacto: al mandarlo a la papelera
quedan inactivas (`deleted_at`), vuelven si se restaura y desaparecen al
purgarlo.

Revision ID: 7c3a9e51d2b4
Revises: 2e1f32f0fadd
Servicio: party
Fecha: 2026-11-10 18:00:00+00:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "7c3a9e51d2b4"
down_revision = "2e1f32f0fadd"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "senales_identidad",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Las de contactos que ya estaban en la papelera, inactivas como ellos.
    op.execute(
        """
        UPDATE senales_identidad s
           SET deleted_at = c.deleted_at
          FROM contactos c
         WHERE c.id = s.contacto_id
           AND c.deleted_at IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_column("senales_identidad", "deleted_at")
