"""Agentes de IA: plan, control humano, límites y reversión (CRM-05.02.03)

Revision ID: e76ef576e996
Revises: 54b1c05e6e66
Servicio: intelligence
Fecha: 2026-09-22 18:30:51.826770+00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "e76ef576e996"
down_revision = "54b1c05e6e66"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agentes_ia",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("clave", sa.String(length=80), nullable=False),
        sa.Column("tipo", sa.String(length=40), nullable=False),
        sa.Column("descripcion", sa.Text(), nullable=False),
        sa.Column("principal_id", sa.UUID(), nullable=True),
        sa.Column(
            "permisos",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "herramientas",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("max_acciones", sa.Integer(), nullable=False),
        sa.Column("presupuesto_tokens_dia", sa.Integer(), nullable=False),
        sa.Column("activo", sa.Boolean(), nullable=False),
        sa.Column("motivo_apagado", sa.Text(), nullable=False),
        sa.Column(
            "aprobacion_por_riesgo",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("aprobacion_desde_importe", sa.Numeric(precision=18, scale=2), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agentes_ia")),
        sa.UniqueConstraint("tenant_id", "clave", name="uq_agente_clave"),
    )
    op.create_index("ix_agentes_activos", "agentes_ia", ["tenant_id", "activo"], unique=False)
    op.create_index(op.f("ix_agentes_ia_tenant_id"), "agentes_ia", ["tenant_id"], unique=False)
    op.create_table(
        "ejecuciones_agente",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("agente_id", sa.UUID(), nullable=False),
        sa.Column("objetivo", sa.Text(), nullable=False),
        sa.Column(
            "contexto",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("estado", sa.String(length=30), nullable=False),
        sa.Column("lanzada_por", sa.UUID(), nullable=True),
        sa.Column("motivo_fin", sa.Text(), nullable=False),
        sa.Column("tokens", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("terminada_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ejecuciones_agente")),
    )
    op.create_index(
        "ix_ejecuciones_agente",
        "ejecuciones_agente",
        ["tenant_id", "agente_id", "estado"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ejecuciones_agente_tenant_id"), "ejecuciones_agente", ["tenant_id"], unique=False
    )
    op.create_table(
        "pasos_agente",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("ejecucion_id", sa.UUID(), nullable=False),
        sa.Column("orden", sa.Integer(), nullable=False),
        sa.Column("herramienta", sa.String(length=80), nullable=False),
        sa.Column("riesgo", sa.String(length=20), nullable=False),
        sa.Column("porque", sa.Text(), nullable=False),
        sa.Column(
            "argumentos",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("importe", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("estado", sa.String(length=30), nullable=False),
        sa.Column(
            "resultado",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column(
            "compensacion",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("reversible", sa.Boolean(), nullable=False),
        sa.Column("aprobado_por", sa.UUID(), nullable=True),
        sa.Column("aprobado_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ejecutado_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revertido_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pasos_agente")),
    )
    op.create_index(
        "ix_pasos_agente", "pasos_agente", ["tenant_id", "ejecucion_id", "orden"], unique=False
    )
    op.create_index(op.f("ix_pasos_agente_tenant_id"), "pasos_agente", ["tenant_id"], unique=False)
    op.create_index("ix_pasos_pendientes", "pasos_agente", ["tenant_id", "estado"], unique=False)


def downgrade() -> None:
    # Un `downgrade` que no se ha probado no es un downgrade. Si esta migración
    # no se puede revertir sin pérdida de datos, dilo aquí en vez de dejar un
    # `pass` que promete algo que no cumple.
    op.drop_index("ix_pasos_pendientes", table_name="pasos_agente")
    op.drop_index(op.f("ix_pasos_agente_tenant_id"), table_name="pasos_agente")
    op.drop_index("ix_pasos_agente", table_name="pasos_agente")
    op.drop_table("pasos_agente")
    op.drop_index(op.f("ix_ejecuciones_agente_tenant_id"), table_name="ejecuciones_agente")
    op.drop_index("ix_ejecuciones_agente", table_name="ejecuciones_agente")
    op.drop_table("ejecuciones_agente")
    op.drop_index(op.f("ix_agentes_ia_tenant_id"), table_name="agentes_ia")
    op.drop_index("ix_agentes_activos", table_name="agentes_ia")
    op.drop_table("agentes_ia")
