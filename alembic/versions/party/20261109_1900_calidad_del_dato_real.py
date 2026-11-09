"""Calidad del dato sobre los registros reales (CRM-01.01.04.06, CRM-01.01.01.08).

Cuatro tablas nuevas: `reglas_supervivencia` (qué valor sobrevive por objeto y
campo, con la confianza de cada fuente), `golden_records` (la ficha buena
compuesta, con la procedencia de cada valor), `perfiles_enriquecimiento` (cada
proveedor declarado sobre el conector de integration) y
`propuestas_enriquecimiento` (lo que contestó, esperando revisión). El
downgrade las quita sin tocar nada más.

Revision ID: 9d2e4c7b1a60
Revises: 3b8e6f1a2c47
Servicio: party
Fecha: 2026-11-09 19:00:00+00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "9d2e4c7b1a60"
down_revision = "3b8e6f1a2c47"
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
        "reglas_supervivencia",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("objeto", sa.String(length=40), nullable=False),
        sa.Column("campo", sa.String(length=80), nullable=False),
        sa.Column("estrategia", sa.String(length=30), nullable=False),
        _jsonb("confianza_por_fuente", "{}"),
        sa.Column("activa", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("nota", sa.Text(), server_default="", nullable=False),
        *_sellos(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reglas_supervivencia")),
        sa.UniqueConstraint("tenant_id", "objeto", "campo", name="uq_regla_supervivencia"),
    )
    op.create_index(
        op.f("ix_reglas_supervivencia_tenant_id"), "reglas_supervivencia", ["tenant_id"]
    )

    op.create_table(
        "golden_records",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("objeto", sa.String(length=40), nullable=False),
        sa.Column("objeto_id", sa.UUID(), nullable=False),
        _jsonb("valores", "{}"),
        _jsonb("procedencia", "{}"),
        _jsonb("a_revisar", "[]"),
        _jsonb("fuentes", "{}"),
        sa.Column("aplicado_at", sa.DateTime(timezone=True), nullable=True),
        _jsonb("aplicados", "[]"),
        sa.Column("compuesto_por", sa.UUID(), nullable=True),
        *_sellos(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_golden_records")),
        sa.UniqueConstraint("tenant_id", "objeto", "objeto_id", name="uq_golden_record"),
    )
    op.create_index(op.f("ix_golden_records_tenant_id"), "golden_records", ["tenant_id"])
    op.create_index("ix_golden_records_objeto", "golden_records", ["tenant_id", "objeto"])

    op.create_table(
        "perfiles_enriquecimiento",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("clave", sa.String(length=60), nullable=False),
        sa.Column("nombre", sa.String(length=150), nullable=False),
        sa.Column("objeto", sa.String(length=40), nullable=False),
        sa.Column("conexion_id", sa.UUID(), nullable=False),
        sa.Column("operacion", sa.String(length=80), nullable=False),
        _jsonb("parametros", "{}"),
        _jsonb("mapeo", "{}"),
        sa.Column("confianza", sa.Integer(), server_default="40", nullable=False),
        sa.Column(
            "coste_por_consulta",
            sa.Numeric(precision=10, scale=4),
            server_default="0",
            nullable=False,
        ),
        sa.Column("activo", sa.Boolean(), server_default=sa.true(), nullable=False),
        *_sellos(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_perfiles_enriquecimiento")),
        sa.UniqueConstraint("tenant_id", "clave", name="uq_perfil_enriquecimiento"),
    )
    op.create_index(
        op.f("ix_perfiles_enriquecimiento_tenant_id"), "perfiles_enriquecimiento", ["tenant_id"]
    )

    op.create_table(
        "propuestas_enriquecimiento",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("perfil_id", sa.UUID(), nullable=False),
        sa.Column("perfil_clave", sa.String(length=60), nullable=False),
        sa.Column("objeto", sa.String(length=40), nullable=False),
        sa.Column("objeto_id", sa.UUID(), nullable=False),
        _jsonb("campos", "[]"),
        sa.Column("estado", sa.String(length=20), server_default="pendiente", nullable=False),
        sa.Column("consultado_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pedido_por", sa.UUID(), nullable=True),
        sa.Column("decidido_por", sa.UUID(), nullable=True),
        sa.Column("decidido_at", sa.DateTime(timezone=True), nullable=True),
        _jsonb("aplicados", "[]"),
        *_sellos(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_propuestas_enriquecimiento")),
    )
    op.create_index(
        op.f("ix_propuestas_enriquecimiento_tenant_id"), "propuestas_enriquecimiento", ["tenant_id"]
    )
    op.create_index(
        "ix_propuestas_enriquecimiento",
        "propuestas_enriquecimiento",
        ["tenant_id", "estado", "objeto", "objeto_id"],
    )


def downgrade() -> None:
    op.drop_table("propuestas_enriquecimiento")
    op.drop_table("perfiles_enriquecimiento")
    op.drop_table("golden_records")
    op.drop_table("reglas_supervivencia")
