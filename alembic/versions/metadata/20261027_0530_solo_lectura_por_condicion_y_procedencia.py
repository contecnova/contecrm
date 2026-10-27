"""solo lectura por condicion y por procedencia

`solo_lectura` era una marca fija: o el campo se podía tocar siempre, o no se
podía tocar nunca. Y lo que pide el negocio es lo de en medio, que es lo que
pasa de verdad:

  * **por condición**: el importe de una oportunidad se edita mientras está
    abierta y deja de editarse cuando se cierra. Con una marca fija hay que
    elegir entre dejar que alguien cambie lo ya firmado o impedir que nadie
    corrija una errata antes de firmar;

  * **por procedencia**: un campo que llega de un sistema externo no lo puede
    cambiar una persona, porque la siguiente sincronización le pisa el cambio
    y nadie entiende por qué «no se guarda». Pero sí lo escribe la integración
    que lo trae. El dueño del valor es el sistema del que viene.

Las dos como DATO del campo y no en el código: el diseñador ya tiene
condiciones para la visibilidad, y que la de solo-lectura viviera en otro sitio
—o en una regla de validación escrita a mano— haría que la misma pregunta se
contestara en dos lenguajes distintos.

Entran vacías: ningún campo existente cambia de comportamiento. Una lista de
procedencias vacía significa «cualquiera», no «ninguna»: al revés, esta
migración dejaría todo el modelo de solo lectura para todo el mundo.

Revision ID: a7c41d2e8b90
Revises: 59e271b175e7
Servicio: metadata
Fecha: 2026-10-27 05:30:00.000000+00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a7c41d2e8b90"
down_revision: str | None = "59e271b175e7"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "campos",
        sa.Column(
            "solo_lectura_si",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "campos",
        sa.Column(
            "solo_lectura_salvo_origen",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("campos", "solo_lectura_salvo_origen")
    op.drop_column("campos", "solo_lectura_si")
