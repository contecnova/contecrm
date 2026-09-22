"""Onboarding por industria, clonado, fusión y marca blanca (CRM-00.01.03, CRM-00.01.04.06)

Revision ID: 48c5d4996477
Revises: f36eba124d92
Servicio: tenancy
Fecha: 2026-09-22 19:15:14.242987+00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "48c5d4996477"
down_revision = "f36eba124d92"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "aplicaciones_perfil",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("perfil", sa.String(length=60), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "aplicado",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "saltado",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_aplicaciones_perfil")),
    )
    op.create_index(
        "ix_aplicaciones_perfil", "aplicaciones_perfil", ["tenant_id", "perfil"], unique=False
    )
    op.create_index(
        op.f("ix_aplicaciones_perfil_tenant_id"), "aplicaciones_perfil", ["tenant_id"], unique=False
    )
    op.create_table(
        "marca_tenants",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("nombre_producto", sa.String(length=120), nullable=False),
        sa.Column("logo_url", sa.Text(), nullable=False),
        sa.Column("favicon_url", sa.Text(), nullable=False),
        sa.Column("color_principal", sa.String(length=7), nullable=False),
        sa.Column("color_texto", sa.String(length=7), nullable=False),
        sa.Column("color_fondo", sa.String(length=7), nullable=False),
        sa.Column("dominio_propio", sa.String(length=200), nullable=False),
        sa.Column("dominio_verificado", sa.Boolean(), nullable=False),
        sa.Column("dominio_envio", sa.String(length=200), nullable=False),
        sa.Column("dominio_envio_verificado", sa.Boolean(), nullable=False),
        sa.Column("remitente", sa.String(length=320), nullable=False),
        sa.Column("pie_correo", sa.Text(), nullable=False),
        sa.Column("activa", sa.Boolean(), nullable=False),
        sa.Column("activada_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "extra",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_marca_tenants")),
        sa.UniqueConstraint("tenant_id", name="uq_marca_tenant"),
    )
    op.create_index("ix_marca_activa", "marca_tenants", ["activa"], unique=False)
    op.create_index(
        op.f("ix_marca_tenants_tenant_id"), "marca_tenants", ["tenant_id"], unique=False
    )
    op.create_table(
        "operaciones_tenant",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("tipo", sa.String(length=20), nullable=False),
        sa.Column("origen_id", sa.UUID(), nullable=True),
        sa.Column("destino_id", sa.UUID(), nullable=True),
        sa.Column("uso", sa.String(length=20), nullable=False),
        sa.Column(
            "bloques",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("estado", sa.String(length=20), nullable=False),
        sa.Column(
            "plan",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "conflictos",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "resultado",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("motivo_fin", sa.Text(), nullable=False),
        sa.Column("terminada_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_operaciones_tenant")),
    )
    op.create_index(
        "ix_operaciones_tenant", "operaciones_tenant", ["tenant_id", "tipo", "estado"], unique=False
    )
    op.create_index(
        op.f("ix_operaciones_tenant_tenant_id"), "operaciones_tenant", ["tenant_id"], unique=False
    )
    op.create_table(
        "perfiles_industria",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("clave", sa.String(length=60), nullable=False),
        sa.Column("nombre", sa.String(length=200), nullable=False),
        sa.Column("descripcion", sa.Text(), nullable=False),
        sa.Column(
            "contenido",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "no_incluye",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("activo", sa.Boolean(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_perfiles_industria")),
        sa.UniqueConstraint("clave", "version", name="uq_perfil_industria"),
    )
    op.create_index(
        "ix_perfiles_industria", "perfiles_industria", ["clave", "activo"], unique=False
    )


def downgrade() -> None:
    # Un `downgrade` que no se ha probado no es un downgrade. Si esta migración
    # no se puede revertir sin pérdida de datos, dilo aquí en vez de dejar un
    # `pass` que promete algo que no cumple.
    op.drop_index("ix_perfiles_industria", table_name="perfiles_industria")
    op.drop_table("perfiles_industria")
    op.drop_index(op.f("ix_operaciones_tenant_tenant_id"), table_name="operaciones_tenant")
    op.drop_index("ix_operaciones_tenant", table_name="operaciones_tenant")
    op.drop_table("operaciones_tenant")
    op.drop_index(op.f("ix_marca_tenants_tenant_id"), table_name="marca_tenants")
    op.drop_index("ix_marca_activa", table_name="marca_tenants")
    op.drop_table("marca_tenants")
    op.drop_index(op.f("ix_aplicaciones_perfil_tenant_id"), table_name="aplicaciones_perfil")
    op.drop_index("ix_aplicaciones_perfil", table_name="aplicaciones_perfil")
    op.drop_table("aplicaciones_perfil")
