"""La ficha buena del lead (CRM-01.01.04.06).

Dos tablas nuevas: `reglas_supervivencia_lead` (qué valor sobrevive en cada
campo del lead, con la confianza de cada fuente) y `golden_leads` (la ficha
buena compuesta, con la procedencia de cada valor). Las mismas que `party`
tiene para cuentas y contactos, con el lead como único objeto. El downgrade
las quita sin tocar nada más.

Revision ID: 4b7d2e9a1c63
Revises: 9c3f1a7e5d21
Servicio: sales
Fecha: 2026-11-09 22:00:00+00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "4b7d2e9a1c63"
down_revision = "9c3f1a7e5d21"
branch_labels = None
depends_on = None


def _sellos() -> list[sa.Column]:
    return [
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
    ]


def _jsonb(nombre: str, defecto: str) -> sa.Column:
    return sa.Column(
        nombre,
        postgresql.JSONB(astext_type=sa.Text()),
        server_default=sa.text(f"'{defecto}'::jsonb"),
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "reglas_supervivencia_lead",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("campo", sa.String(length=80), nullable=False),
        sa.Column("estrategia", sa.String(length=30), nullable=False),
        _jsonb("confianza_por_fuente", "{}"),
        sa.Column("activa", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("nota", sa.Text(), server_default="", nullable=False),
        *_sellos(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reglas_supervivencia_lead")),
        sa.UniqueConstraint("tenant_id", "campo", name="uq_regla_supervivencia_lead"),
    )
    op.create_index(
        op.f("ix_reglas_supervivencia_lead_tenant_id"), "reglas_supervivencia_lead", ["tenant_id"]
    )

    op.create_table(
        "golden_leads",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("lead_id", sa.UUID(), nullable=False),
        _jsonb("valores", "{}"),
        _jsonb("procedencia", "{}"),
        _jsonb("a_revisar", "[]"),
        _jsonb("fuentes", "{}"),
        sa.Column("aplicado_at", sa.DateTime(timezone=True), nullable=True),
        _jsonb("aplicados", "[]"),
        sa.Column("compuesto_por", sa.UUID(), nullable=True),
        *_sellos(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_golden_leads")),
        sa.UniqueConstraint("tenant_id", "lead_id", name="uq_golden_lead"),
    )
    op.create_index(op.f("ix_golden_leads_tenant_id"), "golden_leads", ["tenant_id"])
    op.create_index("ix_golden_leads_lead", "golden_leads", ["tenant_id", "lead_id"])


def downgrade() -> None:
    op.drop_index("ix_golden_leads_lead", table_name="golden_leads")
    op.drop_index(op.f("ix_golden_leads_tenant_id"), table_name="golden_leads")
    op.drop_table("golden_leads")
    op.drop_index(
        op.f("ix_reglas_supervivencia_lead_tenant_id"), table_name="reglas_supervivencia_lead"
    )
    op.drop_table("reglas_supervivencia_lead")
