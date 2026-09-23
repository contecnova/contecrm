"""Biblioteca de activos y aprobación de contenidos (CRM-02.04.01)

Cada activo con sus derechos de uso y su vigencia, y la versión nueva no borra la
anterior: lo que se mandó al cliente el martes tiene que poder recuperarse.

Revision ID: 4182c934641e
Revises: a5392bd19217
Servicio: marketing
Fecha: 2026-09-23 05:16:41.304980+00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "4182c934641e"
down_revision = "a5392bd19217"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "activos_marketing",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("clave", sa.String(length=120), nullable=False),
        sa.Column("nombre", sa.String(length=300), nullable=False),
        sa.Column("tipo", sa.String(length=40), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("referencia", sa.String(length=300), nullable=False),
        sa.Column("estado", sa.String(length=20), nullable=False),
        sa.Column(
            "usos_permitidos",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("licencia", sa.String(length=200), nullable=False),
        sa.Column("licencia_hasta", sa.Date(), nullable=True),
        sa.Column("vigente_hasta", sa.Date(), nullable=True),
        sa.Column("idioma", sa.String(length=10), nullable=False),
        sa.Column(
            "etiquetas",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("sustituido_por_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_activos_marketing")),
        sa.UniqueConstraint("tenant_id", "clave", "version", name="uq_activo_version"),
    )
    op.create_index(
        op.f("ix_activos_marketing_tenant_id"), "activos_marketing", ["tenant_id"], unique=False
    )
    op.create_index(
        "ix_activos_vigencia", "activos_marketing", ["tenant_id", "vigente_hasta"], unique=False
    )
    op.create_table(
        "aprobaciones_contenido",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("objeto", sa.String(length=40), nullable=False),
        sa.Column("objeto_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("paso", sa.String(length=60), nullable=False),
        sa.Column("aprobador_id", sa.UUID(), nullable=True),
        sa.Column("resultado", sa.String(length=20), nullable=False),
        sa.Column("comentario", sa.Text(), nullable=False),
        sa.Column("decidido_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("vio_los_cambios", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_aprobaciones_contenido")),
    )
    op.create_index(
        "ix_aprobaciones",
        "aprobaciones_contenido",
        ["tenant_id", "objeto", "objeto_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_aprobaciones_contenido_tenant_id"),
        "aprobaciones_contenido",
        ["tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    # Un `downgrade` que no se ha probado no es un downgrade. Si esta migración
    # no se puede revertir sin pérdida de datos, dilo aquí en vez de dejar un
    # `pass` que promete algo que no cumple.
    op.drop_index(op.f("ix_aprobaciones_contenido_tenant_id"), table_name="aprobaciones_contenido")
    op.drop_index("ix_aprobaciones", table_name="aprobaciones_contenido")
    op.drop_table("aprobaciones_contenido")
    op.drop_index("ix_activos_vigencia", table_name="activos_marketing")
    op.drop_index(op.f("ix_activos_marketing_tenant_id"), table_name="activos_marketing")
    op.drop_table("activos_marketing")
