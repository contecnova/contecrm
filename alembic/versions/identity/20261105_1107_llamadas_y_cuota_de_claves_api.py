"""Llamadas de cada clave de API y su cuota mensual (CRM-00.02.04.06). Tabla y
columna nuevas: el downgrade las quita y la cuota vuelve a no existir.

Revision ID: 911a1fb9c3cc
Revises: 28a7e83be67b
Servicio: identity
Fecha: 2026-11-05 11:07:19.635459+00:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "911a1fb9c3cc"
down_revision = "28a7e83be67b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llamadas_clave_api",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("clave_id", sa.UUID(), nullable=False),
        sa.Column("cuando", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metodo", sa.String(length=10), nullable=False),
        sa.Column("ruta", sa.String(length=500), nullable=False),
        sa.Column("status", sa.Integer(), nullable=False),
        sa.Column("duracion_ms", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llamadas_clave_api")),
    )
    op.create_index(
        op.f("ix_llamadas_clave_api_tenant_id"), "llamadas_clave_api", ["tenant_id"], unique=False
    )
    op.create_index(
        "ix_llamadas_clave_cuando", "llamadas_clave_api", ["clave_id", "cuando"], unique=False
    )
    op.add_column("claves_api", sa.Column("cuota_mes", sa.Integer(), nullable=True))


def downgrade() -> None:
    # Un `downgrade` que no se ha probado no es un downgrade. Si esta migración
    # no se puede revertir sin pérdida de datos, dilo aquí en vez de dejar un
    # `pass` que promete algo que no cumple.
    op.drop_column("claves_api", "cuota_mes")
    op.drop_index("ix_llamadas_clave_cuando", table_name="llamadas_clave_api")
    op.drop_index(op.f("ix_llamadas_clave_api_tenant_id"), table_name="llamadas_clave_api")
    op.drop_table("llamadas_clave_api")
