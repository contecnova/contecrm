"""Paquetes de configuración, promoción y drift (CRM-07.02.01)

Revision ID: c4ce50c6eb6b
Revises: c1afcd538d6d
Servicio: metadata
Fecha: 2026-09-23 02:33:48.583397+00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "c4ce50c6eb6b"
down_revision = "c1afcd538d6d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "despliegues_configuracion",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("entorno", sa.String(length=20), nullable=False),
        sa.Column("paquete_id", sa.UUID(), nullable=False),
        sa.Column("huella", sa.String(length=64), nullable=False),
        sa.Column("vigente", sa.Boolean(), nullable=False),
        sa.Column("anterior_id", sa.UUID(), nullable=True),
        sa.Column("desplegado_por", sa.UUID(), nullable=True),
        sa.Column(
            "desplegado_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("motivo", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_despliegues_configuracion")),
    )
    op.create_index(
        "ix_despliegues",
        "despliegues_configuracion",
        ["tenant_id", "entorno", "vigente"],
        unique=False,
    )
    op.create_index(
        op.f("ix_despliegues_configuracion_tenant_id"),
        "despliegues_configuracion",
        ["tenant_id"],
        unique=False,
    )
    op.create_table(
        "paquetes_configuracion",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("nombre", sa.String(length=200), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("origen_entorno", sa.String(length=20), nullable=False),
        sa.Column("referencia_git", sa.String(length=200), nullable=False),
        sa.Column(
            "contenido",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("huella", sa.String(length=64), nullable=False),
        sa.Column("notas", sa.Text(), nullable=False),
        sa.Column("creado_por", sa.UUID(), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_paquetes_configuracion")),
        sa.UniqueConstraint("tenant_id", "nombre", "version", name="uq_paquete_version"),
    )
    op.create_index("ix_paquetes", "paquetes_configuracion", ["tenant_id", "nombre"], unique=False)
    op.create_index(
        op.f("ix_paquetes_configuracion_tenant_id"),
        "paquetes_configuracion",
        ["tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    # Un `downgrade` que no se ha probado no es un downgrade. Si esta migración
    # no se puede revertir sin pérdida de datos, dilo aquí en vez de dejar un
    # `pass` que promete algo que no cumple.
    op.drop_index(op.f("ix_paquetes_configuracion_tenant_id"), table_name="paquetes_configuracion")
    op.drop_index("ix_paquetes", table_name="paquetes_configuracion")
    op.drop_table("paquetes_configuracion")
    op.drop_index(
        op.f("ix_despliegues_configuracion_tenant_id"), table_name="despliegues_configuracion"
    )
    op.drop_index("ix_despliegues", table_name="despliegues_configuracion")
    op.drop_table("despliegues_configuracion")
