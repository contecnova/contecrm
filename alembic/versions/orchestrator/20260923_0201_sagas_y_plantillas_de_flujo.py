"""Sagas con compensación y plantillas de flujo (CRM-03.03.02.12, CRM-00.03.05.15)

Revision ID: 0f495cfea288
Revises: 497a14e51e9f
Servicio: orchestrator
Fecha: 2026-09-23 02:33:50.254362+00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0f495cfea288"
down_revision = "497a14e51e9f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pasos_saga",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("saga_id", sa.UUID(), nullable=False),
        sa.Column("orden", sa.Integer(), nullable=False),
        sa.Column("nombre", sa.String(length=80), nullable=False),
        sa.Column("servicio", sa.String(length=40), nullable=False),
        sa.Column("estado", sa.String(length=20), nullable=False),
        sa.Column(
            "datos",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "compensacion",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("compensable", sa.Boolean(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("ejecutado_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("compensado_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pasos_saga")),
        sa.UniqueConstraint("tenant_id", "saga_id", "orden", name="uq_paso_saga"),
    )
    op.create_index("ix_pasos_saga", "pasos_saga", ["tenant_id", "saga_id", "orden"], unique=False)
    op.create_index(op.f("ix_pasos_saga_tenant_id"), "pasos_saga", ["tenant_id"], unique=False)
    op.create_table(
        "plantillas_flujo",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("clave", sa.String(length=80), nullable=False),
        sa.Column("sector", sa.String(length=60), nullable=False),
        sa.Column("caso_de_uso", sa.String(length=120), nullable=False),
        sa.Column("nombre", sa.String(length=200), nullable=False),
        sa.Column(
            "definicion",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "no_resuelve",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("activa", sa.Boolean(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plantillas_flujo")),
        sa.UniqueConstraint("clave", "version", name="uq_plantilla_flujo"),
    )
    op.create_index("ix_plantillas_flujo", "plantillas_flujo", ["sector", "activa"], unique=False)
    op.create_table(
        "sagas",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("clave", sa.String(length=80), nullable=False),
        sa.Column("objeto", sa.String(length=60), nullable=False),
        sa.Column("objeto_id", sa.UUID(), nullable=True),
        sa.Column("estado", sa.String(length=20), nullable=False),
        sa.Column("version_proceso", sa.Integer(), nullable=False),
        sa.Column(
            "contexto",
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sagas")),
    )
    op.create_index("ix_sagas", "sagas", ["tenant_id", "clave", "estado"], unique=False)
    op.create_index(op.f("ix_sagas_tenant_id"), "sagas", ["tenant_id"], unique=False)


def downgrade() -> None:
    # Un `downgrade` que no se ha probado no es un downgrade. Si esta migración
    # no se puede revertir sin pérdida de datos, dilo aquí en vez de dejar un
    # `pass` que promete algo que no cumple.
    op.drop_index(op.f("ix_sagas_tenant_id"), table_name="sagas")
    op.drop_index("ix_sagas", table_name="sagas")
    op.drop_table("sagas")
    op.drop_index("ix_plantillas_flujo", table_name="plantillas_flujo")
    op.drop_table("plantillas_flujo")
    op.drop_index(op.f("ix_pasos_saga_tenant_id"), table_name="pasos_saga")
    op.drop_index("ix_pasos_saga", table_name="pasos_saga")
    op.drop_table("pasos_saga")
