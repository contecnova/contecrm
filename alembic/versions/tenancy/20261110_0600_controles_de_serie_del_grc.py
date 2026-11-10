"""Todo lo que hay, controlado por el GRC (CRM-07.03.02.12 a CRM-07.03.02.15):
de dónde sale cada control y a qué está enlazado (`origen`, `referencia`,
`ajustado`), los hallazgos de los controles y las evidencias con caducidad.
Columnas con valor por defecto y tablas nuevas; el downgrade las quita.

Revision ID: 1a5333924500
Revises: 9b1e4f20c7d3
Servicio: tenancy
Fecha: 2026-11-10 05:59:59.941489+00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "1a5333924500"
down_revision = "9b1e4f20c7d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "grc_evidencias",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("control_codigo", sa.String(length=40), nullable=False),
        sa.Column("origen", sa.String(length=20), nullable=False),
        sa.Column("referencia", sa.String(length=80), nullable=False),
        sa.Column("descripcion", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column(
            "datos",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("caduca_at", sa.Date(), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_grc_evidencias")),
    )
    op.create_index(
        "ix_grc_evidencias_control", "grc_evidencias", ["tenant_id", "control_codigo"], unique=False
    )
    op.create_index(
        "uq_grc_evidencia", "grc_evidencias", ["tenant_id", "origen", "referencia"], unique=True
    )
    op.create_table(
        "grc_hallazgos",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("codigo", sa.String(length=120), nullable=False),
        sa.Column("control_codigo", sa.String(length=40), nullable=False),
        sa.Column("origen", sa.String(length=20), nullable=False),
        sa.Column("referencia", sa.String(length=80), server_default=sa.text("''"), nullable=False),
        sa.Column("sujeto_id", sa.UUID(), nullable=True),
        sa.Column("titulo", sa.String(length=300), nullable=False),
        sa.Column(
            "detalle",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "riesgo_codigo", sa.String(length=40), server_default=sa.text("''"), nullable=False
        ),
        sa.Column(
            "estado", sa.String(length=20), server_default=sa.text("'abierto'"), nullable=False
        ),
        sa.Column(
            "motivo_cierre", sa.String(length=40), server_default=sa.text("''"), nullable=False
        ),
        sa.Column(
            "detectado_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("cerrado_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_grc_hallazgos")),
    )
    op.create_index("uq_grc_hallazgo", "grc_hallazgos", ["tenant_id", "codigo"], unique=True)
    op.add_column(
        "grc_controles",
        sa.Column("origen", sa.String(length=20), server_default=sa.text("''"), nullable=False),
    )
    op.add_column(
        "grc_controles",
        sa.Column("referencia", sa.String(length=80), server_default=sa.text("''"), nullable=False),
    )
    op.add_column(
        "grc_controles",
        sa.Column("ajustado", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )


def downgrade() -> None:
    # Revertir pierde los hallazgos, las evidencias y el enlace de cada control
    # con su origen; los controles en sí se quedan.
    op.drop_column("grc_controles", "ajustado")
    op.drop_column("grc_controles", "referencia")
    op.drop_column("grc_controles", "origen")
    op.drop_index("uq_grc_hallazgo", table_name="grc_hallazgos")
    op.drop_table("grc_hallazgos")
    op.drop_index("uq_grc_evidencia", table_name="grc_evidencias")
    op.drop_index("ix_grc_evidencias_control", table_name="grc_evidencias")
    op.drop_table("grc_evidencias")
