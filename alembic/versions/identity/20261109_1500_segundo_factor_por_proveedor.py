"""Segundo factor verificado por el proveedor del tenant (CRM-00.05.01.22):
perfiles declarados y quién es cada persona en el proveedor. Tablas nuevas; el
downgrade las quita y el login vuelve a verificar sólo lo local.

Revision ID: c0ea9c5680ef
Revises: 911a1fb9c3cc
Servicio: identity
Fecha: 2026-11-09 15:00:00+00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "c0ea9c5680ef"
down_revision = "911a1fb9c3cc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    jsonb_obj = sa.text("'{}'::jsonb")
    op.create_table(
        "perfiles_mfa_proveedor",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("nombre", sa.String(length=120), nullable=False),
        sa.Column("plantilla", sa.String(length=60), nullable=False),
        sa.Column("activo", sa.Boolean(), nullable=False),
        sa.Column("url", sa.String(length=1000), nullable=False),
        sa.Column("metodo", sa.String(length=10), nullable=False),
        sa.Column("formato", sa.String(length=10), nullable=False),
        sa.Column("autenticacion", postgresql.JSONB(), server_default=jsonb_obj, nullable=False),
        sa.Column("secreto", sa.Text(), server_default="", nullable=False),
        sa.Column("cabeceras", postgresql.JSONB(), server_default=jsonb_obj, nullable=False),
        sa.Column("cuerpo", postgresql.JSONB(), server_default=jsonb_obj, nullable=False),
        sa.Column("variables", postgresql.JSONB(), server_default=jsonb_obj, nullable=False),
        sa.Column(
            "campos_persona",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("respuesta", postgresql.JSONB(), server_default=jsonb_obj, nullable=False),
        sa.Column("ultima_prueba_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ultima_prueba", postgresql.JSONB(), server_default=jsonb_obj, nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_perfiles_mfa_proveedor")),
        sa.UniqueConstraint("tenant_id", "nombre", name="uq_perfil_mfa_proveedor_nombre"),
    )
    op.create_index(
        "ix_perfiles_mfa_proveedor_tenant", "perfiles_mfa_proveedor", ["tenant_id", "activo"]
    )
    op.create_table(
        "vinculos_mfa_proveedor",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("perfil_id", sa.UUID(), nullable=False),
        sa.Column("usuario_id", sa.UUID(), nullable=False),
        sa.Column("datos", postgresql.JSONB(), server_default=jsonb_obj, nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vinculos_mfa_proveedor")),
        sa.UniqueConstraint("perfil_id", "usuario_id", name="uq_vinculo_mfa_proveedor"),
    )
    op.create_index(
        "ix_vinculos_mfa_proveedor_tenant", "vinculos_mfa_proveedor", ["tenant_id", "perfil_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_vinculos_mfa_proveedor_tenant", table_name="vinculos_mfa_proveedor")
    op.drop_table("vinculos_mfa_proveedor")
    op.drop_index("ix_perfiles_mfa_proveedor_tenant", table_name="perfiles_mfa_proveedor")
    op.drop_table("perfiles_mfa_proveedor")
