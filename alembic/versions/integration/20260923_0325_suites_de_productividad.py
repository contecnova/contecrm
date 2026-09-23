"""Consentimiento por persona y suscripción a cambios de la suite (CRM-06.01.03)

Una fila por persona y recurso a propósito: «conectó su Microsoft 365» no es una
respuesta cuando alguien pregunta si el CRM lee sus correos. Esto sí lo es.

Revision ID: 198ecb8a8a1e
Revises: f3b40e0d2b16
Servicio: integration
Fecha: 2026-09-23 03:25:52.043713+00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "198ecb8a8a1e"
down_revision = "f3b40e0d2b16"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "consentimientos_suite",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("usuario_id", sa.UUID(), nullable=False),
        sa.Column("perfil", sa.String(length=80), nullable=False),
        sa.Column("recurso", sa.String(length=30), nullable=False),
        sa.Column("sentido", sa.String(length=10), nullable=False),
        sa.Column(
            "alcances",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("concedido_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocado_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("concedido_por", sa.UUID(), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consentimientos_suite")),
        sa.UniqueConstraint(
            "tenant_id", "usuario_id", "perfil", "recurso", "sentido", name="uq_consentimiento"
        ),
    )
    op.create_index(
        op.f("ix_consentimientos_suite_tenant_id"),
        "consentimientos_suite",
        ["tenant_id"],
        unique=False,
    )
    op.create_table(
        "suscripciones_suite",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("usuario_id", sa.UUID(), nullable=False),
        sa.Column("perfil", sa.String(length=80), nullable=False),
        sa.Column("recurso", sa.String(length=30), nullable=False),
        sa.Column("externo_id", sa.String(length=300), nullable=False),
        sa.Column("caduca_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("renovada_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("estado", sa.String(length=20), nullable=False),
        sa.Column("motivo", sa.Text(), nullable=False),
        sa.Column("en_sondeo", sa.Boolean(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_suscripciones_suite")),
        sa.UniqueConstraint("tenant_id", "usuario_id", "perfil", "recurso", name="uq_suscripcion"),
    )
    op.create_index(
        "ix_suscripciones_caducidad",
        "suscripciones_suite",
        ["tenant_id", "caduca_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_suscripciones_suite_tenant_id"), "suscripciones_suite", ["tenant_id"], unique=False
    )


def downgrade() -> None:
    # Un `downgrade` que no se ha probado no es un downgrade. Si esta migración
    # no se puede revertir sin pérdida de datos, dilo aquí en vez de dejar un
    # `pass` que promete algo que no cumple.
    op.drop_index(op.f("ix_suscripciones_suite_tenant_id"), table_name="suscripciones_suite")
    op.drop_index("ix_suscripciones_caducidad", table_name="suscripciones_suite")
    op.drop_table("suscripciones_suite")
    op.drop_index(op.f("ix_consentimientos_suite_tenant_id"), table_name="consentimientos_suite")
    op.drop_table("consentimientos_suite")
