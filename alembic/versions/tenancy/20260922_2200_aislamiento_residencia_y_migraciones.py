"""Aislamiento, residencia de datos y migraciones de tenant (CRM-00.01.01, CRM-00.01.05)

Revision ID: f36eba124d92
Revises: b044cb52874f
Servicio: tenancy
Fecha: 2026-09-22 18:59:07.274490+00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "f36eba124d92"
down_revision = "b044cb52874f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "aislamiento_tenants",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("modalidad", sa.String(length=20), nullable=False),
        sa.Column("instancia", sa.String(length=200), nullable=False),
        sa.Column("base", sa.String(length=120), nullable=False),
        sa.Column("esquema", sa.String(length=120), nullable=False),
        sa.Column("pool_computo", sa.String(length=80), nullable=False),
        sa.Column("comprobado_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("comprobado_ok", sa.Boolean(), nullable=True),
        sa.Column("comprobado_detalle", sa.Text(), nullable=False),
        sa.Column("infraestructura_del_cliente", sa.Boolean(), nullable=False),
        sa.Column("notas", sa.Text(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_aislamiento_tenants")),
        sa.UniqueConstraint("tenant_id", name="uq_aislamiento_tenant"),
    )
    op.create_index("ix_aislamiento_modalidad", "aislamiento_tenants", ["modalidad"], unique=False)
    op.create_index(
        op.f("ix_aislamiento_tenants_tenant_id"), "aislamiento_tenants", ["tenant_id"], unique=False
    )
    op.create_table(
        "migraciones_aislamiento",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("desde", sa.String(length=20), nullable=False),
        sa.Column("hacia", sa.String(length=20), nullable=False),
        sa.Column("estado", sa.String(length=20), nullable=False),
        sa.Column("ventana_minutos", sa.Integer(), nullable=False),
        sa.Column("solo_lectura_desde", sa.DateTime(timezone=True), nullable=True),
        sa.Column("solo_lectura_hasta", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "recuento_origen",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "recuento_destino",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "diferencias",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("motivo_fin", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("terminada_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_migraciones_aislamiento")),
    )
    op.create_index(
        "ix_migraciones_aislamiento",
        "migraciones_aislamiento",
        ["tenant_id", "estado"],
        unique=False,
    )
    op.create_index(
        op.f("ix_migraciones_aislamiento_tenant_id"),
        "migraciones_aislamiento",
        ["tenant_id"],
        unique=False,
    )
    op.create_table(
        "residencia_datos",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("tipo_dato", sa.String(length=20), nullable=False),
        sa.Column("region", sa.String(length=20), nullable=False),
        sa.Column("proveedor", sa.String(length=120), nullable=False),
        sa.Column("notas", sa.Text(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_residencia_datos")),
        sa.UniqueConstraint("tenant_id", "tipo_dato", name="uq_residencia_tipo"),
    )
    op.create_index(
        op.f("ix_residencia_datos_tenant_id"), "residencia_datos", ["tenant_id"], unique=False
    )
    op.create_index(
        "ix_residencia_region", "residencia_datos", ["tenant_id", "region"], unique=False
    )
    op.create_table(
        "subprocesadores",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("clave", sa.String(length=80), nullable=False),
        sa.Column("nombre", sa.String(length=200), nullable=False),
        sa.Column(
            "trata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("finalidad", sa.Text(), nullable=False),
        sa.Column("region", sa.String(length=20), nullable=False),
        sa.Column("garantia", sa.String(length=40), nullable=False),
        sa.Column("referencia_garantia", sa.Text(), nullable=False),
        sa.Column("activo", sa.Boolean(), nullable=False),
        sa.Column("comunicado_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_subprocesadores")),
        sa.UniqueConstraint("tenant_id", "clave", name="uq_subprocesador"),
    )
    op.create_index("ix_subprocesadores", "subprocesadores", ["tenant_id", "activo"], unique=False)
    op.create_index(
        op.f("ix_subprocesadores_tenant_id"), "subprocesadores", ["tenant_id"], unique=False
    )
    op.create_table(
        "transferencias_internacionales",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("subprocesador", sa.String(length=80), nullable=False),
        sa.Column("tipo_dato", sa.String(length=20), nullable=False),
        sa.Column("desde_region", sa.String(length=20), nullable=False),
        sa.Column("hacia_region", sa.String(length=20), nullable=False),
        sa.Column("garantia", sa.String(length=40), nullable=False),
        sa.Column("motivo", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transferencias_internacionales")),
    )
    op.create_index(
        "ix_transferencias",
        "transferencias_internacionales",
        ["tenant_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_transferencias_garantia",
        "transferencias_internacionales",
        ["tenant_id", "garantia"],
        unique=False,
    )
    op.create_index(
        op.f("ix_transferencias_internacionales_tenant_id"),
        "transferencias_internacionales",
        ["tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    # Un `downgrade` que no se ha probado no es un downgrade. Si esta migración
    # no se puede revertir sin pérdida de datos, dilo aquí en vez de dejar un
    # `pass` que promete algo que no cumple.
    op.drop_index(
        op.f("ix_transferencias_internacionales_tenant_id"),
        table_name="transferencias_internacionales",
    )
    op.drop_index("ix_transferencias_garantia", table_name="transferencias_internacionales")
    op.drop_index("ix_transferencias", table_name="transferencias_internacionales")
    op.drop_table("transferencias_internacionales")
    op.drop_index(op.f("ix_subprocesadores_tenant_id"), table_name="subprocesadores")
    op.drop_index("ix_subprocesadores", table_name="subprocesadores")
    op.drop_table("subprocesadores")
    op.drop_index("ix_residencia_region", table_name="residencia_datos")
    op.drop_index(op.f("ix_residencia_datos_tenant_id"), table_name="residencia_datos")
    op.drop_table("residencia_datos")
    op.drop_index(
        op.f("ix_migraciones_aislamiento_tenant_id"), table_name="migraciones_aislamiento"
    )
    op.drop_index("ix_migraciones_aislamiento", table_name="migraciones_aislamiento")
    op.drop_table("migraciones_aislamiento")
    op.drop_index(op.f("ix_aislamiento_tenants_tenant_id"), table_name="aislamiento_tenants")
    op.drop_index("ix_aislamiento_modalidad", table_name="aislamiento_tenants")
    op.drop_table("aislamiento_tenants")
