"""la cabecera del instante, para que la firma del chat caduque

Revision ID: a1c0f6e2b713
Revises: 8c961a68a491
Servicio: integration
Fecha: 2026-10-06 05:50:00.000000+00:00

La firma entrante del chat se comprobaba con un HMAC propio **sin mirar el
instante**, así que un mensaje capturado una vez valía para siempre — y lo que
hay al otro lado son cambios en el CRM. La verificación del núcleo, que sí tiene
ventana, estaba escrita y no la llamaba nadie.

Cada plataforma llama de una forma a la cabecera con la marca de tiempo, así que
se declara por canal. Vacía significa **canal reproducible**, y eso se dice al
declararlo en vez de callarlo.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "a1c0f6e2b713"
down_revision = "8c961a68a491"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Con `server_default` y retirándolo después: `nullable=False` sin él falla
    # en cuanto la tabla tiene filas, y los canales ya declarados las tienen.
    op.add_column(
        "canales_chat",
        sa.Column("cabecera_momento", sa.String(length=80), nullable=False, server_default=""),
    )
    op.alter_column("canales_chat", "cabecera_momento", server_default=None)


def downgrade() -> None:
    op.drop_column("canales_chat", "cabecera_momento")
