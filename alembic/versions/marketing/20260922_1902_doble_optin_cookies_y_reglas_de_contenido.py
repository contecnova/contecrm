"""Doble opt-in, cookies y reglas de contenido (CRM-02.04.02.02, CRM-07.03.01.08, CRM-02.04.01.03)

Revision ID: a5392bd19217
Revises: 87b9cb8936ac
Servicio: marketing
Fecha: 2026-09-22 18:14:37.269565+00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "a5392bd19217"
down_revision = "87b9cb8936ac"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "confirmaciones_optin",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("canal", sa.String(length=20), nullable=False),
        sa.Column("destino", sa.String(length=320), nullable=False),
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("estado", sa.String(length=20), nullable=False),
        sa.Column("texto_aceptado", sa.Text(), nullable=False),
        sa.Column("finalidad", sa.String(length=60), nullable=False),
        sa.Column("ip_solicitud", sa.String(length=64), nullable=True),
        sa.Column("ip_confirmacion", sa.String(length=64), nullable=True),
        sa.Column("caduca_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmado_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_confirmaciones_optin")),
    )
    op.create_index(
        op.f("ix_confirmaciones_optin_tenant_id"),
        "confirmaciones_optin",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_optin_pendientes",
        "confirmaciones_optin",
        ["tenant_id", "canal", "destino", "estado"],
        unique=False,
    )
    op.create_index("ix_optin_token", "confirmaciones_optin", ["tenant_id", "token"], unique=False)
    op.create_table(
        "consentimientos_cookies",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("visitante", sa.String(length=80), nullable=False),
        sa.Column("contacto_id", sa.UUID(), nullable=True),
        sa.Column(
            "categorias",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("version_aviso", sa.String(length=40), nullable=False),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("agente", sa.String(length=300), nullable=True),
        sa.Column(
            "decidido_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("caduca_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consentimientos_cookies")),
    )
    op.create_index(
        op.f("ix_consentimientos_cookies_tenant_id"),
        "consentimientos_cookies",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_cookies_visitante",
        "consentimientos_cookies",
        ["tenant_id", "visitante", "decidido_at"],
        unique=False,
    )
    op.create_table(
        "reglas_contenido",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("marca", sa.String(length=80), nullable=False),
        sa.Column("pais", sa.String(length=2), nullable=False),
        sa.Column("idioma", sa.String(length=10), nullable=False),
        sa.Column(
            "plantillas_bloqueadas",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "exige_textos",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "prohibe_textos",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("activa", sa.Boolean(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reglas_contenido")),
        sa.UniqueConstraint("tenant_id", "marca", "pais", "idioma", name="uq_regla_contenido"),
    )
    op.create_index(
        "ix_reglas_contenido", "reglas_contenido", ["tenant_id", "activa"], unique=False
    )
    op.create_index(
        op.f("ix_reglas_contenido_tenant_id"), "reglas_contenido", ["tenant_id"], unique=False
    )


def downgrade() -> None:
    # Un `downgrade` que no se ha probado no es un downgrade. Si esta migración
    # no se puede revertir sin pérdida de datos, dilo aquí en vez de dejar un
    # `pass` que promete algo que no cumple.
    op.drop_index(op.f("ix_reglas_contenido_tenant_id"), table_name="reglas_contenido")
    op.drop_index("ix_reglas_contenido", table_name="reglas_contenido")
    op.drop_table("reglas_contenido")
    op.drop_index("ix_cookies_visitante", table_name="consentimientos_cookies")
    op.drop_index(
        op.f("ix_consentimientos_cookies_tenant_id"), table_name="consentimientos_cookies"
    )
    op.drop_table("consentimientos_cookies")
    op.drop_index("ix_optin_token", table_name="confirmaciones_optin")
    op.drop_index("ix_optin_pendientes", table_name="confirmaciones_optin")
    op.drop_index(op.f("ix_confirmaciones_optin_tenant_id"), table_name="confirmaciones_optin")
    op.drop_table("confirmaciones_optin")
