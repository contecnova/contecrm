"""altas pendientes de confirmar

Revision ID: a7c41f0b93d2
Revises: ed87644e255e
Servicio: tenancy
Fecha: 2026-10-07 06:20:00.000000+00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "a7c41f0b93d2"
down_revision = "ed87644e255e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # La solicitud de alta autoservicio, antes de que exista el tenant
    # (CRM-00.01.03.01). No lleva `tenant_id` como las demás tablas y es a
    # propósito: esto se escribe cuando todavía no hay tenant al que atribuirlo
    # — justamente es lo que se está pidiendo crear.
    op.create_table(
        "altas_pendientes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.String(length=63), nullable=False),
        sa.Column("nombre_empresa", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("nombre_persona", sa.String(length=200), nullable=False),
        # El índice es ÚNICO —se crea abajo— y no hay restricción aparte: el
        # modelo declara `unique=True, index=True`, que en SQLAlchemy es una
        # sola cosa. Poner las dos dejaría la migración distinta del modelo y el
        # gate lo caza, con razón: lo que se despliega no sería lo que se prueba.
        sa.Column("hash_token", sa.String(length=64), nullable=False),
        sa.Column("caduca_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("usado_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip_solicitud", sa.String(length=64), nullable=True),
        # Sin `server_default`: el modelo pone el valor desde Python y la tabla
        # es nueva, así que no hay filas que rellenar. Un `server_default` que el
        # modelo no tiene es una divergencia silenciosa entre lo desplegado y lo
        # probado.
        sa.Column("slug_libre", sa.Boolean(), nullable=False),
        sa.Column("tenant_creado_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_altas_pendientes_slug", "altas_pendientes", ["slug"])
    op.create_index("ix_altas_pendientes_email", "altas_pendientes", ["email"])
    op.create_index(
        "ix_altas_pendientes_hash_token", "altas_pendientes", ["hash_token"], unique=True
    )
    # Por el que pregunta la confirmación: las vivas de un slug.
    op.create_index("ix_altas_pendientes_vivas", "altas_pendientes", ["slug", "usado_at"])


def downgrade() -> None:
    op.drop_index("ix_altas_pendientes_vivas", table_name="altas_pendientes")
    op.drop_index("ix_altas_pendientes_hash_token", table_name="altas_pendientes")
    op.drop_index("ix_altas_pendientes_email", table_name="altas_pendientes")
    op.drop_index("ix_altas_pendientes_slug", table_name="altas_pendientes")
    op.drop_table("altas_pendientes")
