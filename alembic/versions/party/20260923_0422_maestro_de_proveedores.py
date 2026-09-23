"""Maestro y gobierno del proveedor (CRM-09.01.01)

Homologación por categoría, documentos con vigencia y contactos por función. El
proveedor no tiene tabla propia: es una cuenta con rol, y esto es lo que se le
añade encima.

Revision ID: 29379744df91
Revises: 69edc50c4259
Servicio: party
Fecha: 2026-09-23 04:22:13.167689+00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "29379744df91"
down_revision = "69edc50c4259"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "contactos_proveedor",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("cuenta_id", sa.UUID(), nullable=False),
        sa.Column("funcion", sa.String(length=20), nullable=False),
        sa.Column("nombre", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("telefono", sa.String(length=40), nullable=False),
        sa.Column("fuera_de_horario", sa.String(length=40), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contactos_proveedor")),
        sa.UniqueConstraint("tenant_id", "cuenta_id", "funcion", "email", name="uq_contacto_prov"),
    )
    op.create_index(
        op.f("ix_contactos_proveedor_tenant_id"), "contactos_proveedor", ["tenant_id"], unique=False
    )
    op.create_table(
        "documentos_proveedor",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("cuenta_id", sa.UUID(), nullable=False),
        sa.Column("clave", sa.String(length=80), nullable=False),
        sa.Column("nombre", sa.String(length=200), nullable=False),
        sa.Column("referencia", sa.String(length=300), nullable=False),
        sa.Column("valido_desde", sa.Date(), nullable=True),
        sa.Column("valido_hasta", sa.Date(), nullable=True),
        sa.Column("dias_preaviso", sa.Integer(), nullable=False),
        sa.Column("bloquea_al_vencer", sa.Boolean(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documentos_proveedor")),
        sa.UniqueConstraint("tenant_id", "cuenta_id", "clave", name="uq_documento_proveedor"),
    )
    op.create_index(
        op.f("ix_documentos_proveedor_tenant_id"),
        "documentos_proveedor",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_documentos_proveedor_vencen",
        "documentos_proveedor",
        ["tenant_id", "valido_hasta"],
        unique=False,
    )
    op.create_table(
        "homologaciones_proveedor",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("cuenta_id", sa.UUID(), nullable=False),
        sa.Column("categoria", sa.String(length=80), nullable=False),
        sa.Column("estado", sa.String(length=20), nullable=False),
        sa.Column(
            "requisitos",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("valida_hasta", sa.Date(), nullable=True),
        sa.Column("motivo", sa.Text(), nullable=False),
        sa.Column("revisada_por", sa.UUID(), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_homologaciones_proveedor")),
        sa.UniqueConstraint("tenant_id", "cuenta_id", "categoria", name="uq_homologacion"),
    )
    op.create_index(
        op.f("ix_homologaciones_proveedor_tenant_id"),
        "homologaciones_proveedor",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_homologaciones_vigencia",
        "homologaciones_proveedor",
        ["tenant_id", "valida_hasta"],
        unique=False,
    )


def downgrade() -> None:
    # Un `downgrade` que no se ha probado no es un downgrade. Si esta migración
    # no se puede revertir sin pérdida de datos, dilo aquí en vez de dejar un
    # `pass` que promete algo que no cumple.
    op.drop_index("ix_homologaciones_vigencia", table_name="homologaciones_proveedor")
    op.drop_index(
        op.f("ix_homologaciones_proveedor_tenant_id"), table_name="homologaciones_proveedor"
    )
    op.drop_table("homologaciones_proveedor")
    op.drop_index("ix_documentos_proveedor_vencen", table_name="documentos_proveedor")
    op.drop_index(op.f("ix_documentos_proveedor_tenant_id"), table_name="documentos_proveedor")
    op.drop_table("documentos_proveedor")
    op.drop_index(op.f("ix_contactos_proveedor_tenant_id"), table_name="contactos_proveedor")
    op.drop_table("contactos_proveedor")
