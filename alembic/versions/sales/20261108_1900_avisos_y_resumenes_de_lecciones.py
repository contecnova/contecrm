"""Lecciones aprendidas: los avisos en los momentos clave y el resumen periódico.

Revision ID: 9d4f2b7e61a8
Revises: 7c2e9a41d5b3
Servicio: sales
Fecha: 2026-11-08 19:00:00+00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "9d4f2b7e61a8"
down_revision = "7c2e9a41d5b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "avisos_leccion",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("oportunidad_id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=True),
        sa.Column("momento", sa.String(length=20), nullable=False),
        sa.Column("clave", sa.String(length=200), nullable=False),
        sa.Column("titulo", sa.String(length=300), nullable=False),
        sa.Column("detalle", sa.Text(), nullable=False),
        sa.Column("lecciones", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_avisos_leccion")),
        sa.UniqueConstraint(
            "tenant_id",
            "oportunidad_id",
            "momento",
            "clave",
            name=op.f("uq_avisos_leccion_tenant_id_oportunidad_id_momento_clave"),
        ),
    )
    op.create_index(
        op.f("ix_avisos_leccion_tenant_id"), "avisos_leccion", ["tenant_id"], unique=False
    )
    op.create_index(
        op.f("ix_avisos_leccion_oportunidad_id"), "avisos_leccion", ["oportunidad_id"], unique=False
    )
    op.create_table(
        "resumenes_lecciones",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("desde", sa.Date(), nullable=False),
        sa.Column("hasta", sa.Date(), nullable=False),
        sa.Column("titulo", sa.String(length=300), nullable=False),
        sa.Column("detalle", sa.Text(), nullable=False),
        sa.Column("datos", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("destinatarios", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("enviado_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_resumenes_lecciones")),
        sa.UniqueConstraint(
            "tenant_id", "desde", name=op.f("uq_resumenes_lecciones_tenant_id_desde")
        ),
    )
    op.create_index(
        op.f("ix_resumenes_lecciones_tenant_id"), "resumenes_lecciones", ["tenant_id"], unique=False
    )


def downgrade() -> None:
    # Se pierden los avisos y los resúmenes; las lecciones, de las que salen,
    # siguen intactas y se pueden volver a calcular.
    op.drop_index(op.f("ix_resumenes_lecciones_tenant_id"), table_name="resumenes_lecciones")
    op.drop_table("resumenes_lecciones")
    op.drop_index(op.f("ix_avisos_leccion_oportunidad_id"), table_name="avisos_leccion")
    op.drop_index(op.f("ix_avisos_leccion_tenant_id"), table_name="avisos_leccion")
    op.drop_table("avisos_leccion")
