"""Compras al proveedor: peticiones de oferta, respuestas, capacidad y sus
reservas, rappel, contrato y alcance (CRM-09.02.01.04 a .09, CRM-09.01.01.04,
.05, .07, .09 y .10). Tablas nuevas: el downgrade las quita sin tocar nada más.

Revision ID: c5bc33443c2a
Revises: 2fd2e4de37e6
Servicio: party
Fecha: 2026-11-05 10:23:58.817854+00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "c5bc33443c2a"
down_revision = "2fd2e4de37e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "acuerdos_rappel",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("proveedor_id", sa.UUID(), nullable=False),
        sa.Column("desde", sa.Date(), nullable=False),
        sa.Column("hasta", sa.Date(), nullable=False),
        sa.Column(
            "tramos",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("cerrado", sa.Boolean(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_acuerdos_rappel")),
    )
    op.create_index(
        op.f("ix_acuerdos_rappel_proveedor_id"), "acuerdos_rappel", ["proveedor_id"], unique=False
    )
    op.create_index(
        op.f("ix_acuerdos_rappel_tenant_id"), "acuerdos_rappel", ["tenant_id"], unique=False
    )
    op.create_table(
        "alcances_proveedor",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("proveedor_id", sa.UUID(), nullable=False),
        sa.Column(
            "alcance",
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alcances_proveedor")),
        sa.UniqueConstraint("tenant_id", "proveedor_id", name="uq_alcance_proveedor"),
    )
    op.create_index(
        op.f("ix_alcances_proveedor_tenant_id"), "alcances_proveedor", ["tenant_id"], unique=False
    )
    op.create_table(
        "capacidades_proveedor",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("proveedor_id", sa.UUID(), nullable=False),
        sa.Column("categoria", sa.String(length=80), nullable=False),
        sa.Column("desde", sa.Date(), nullable=False),
        sa.Column("hasta", sa.Date(), nullable=False),
        sa.Column("unidad", sa.String(length=20), nullable=False),
        sa.Column("contratada", sa.Numeric(precision=14, scale=4), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_capacidades_proveedor")),
    )
    op.create_index(
        "ix_capacidades_periodo",
        "capacidades_proveedor",
        ["tenant_id", "proveedor_id", "desde"],
        unique=False,
    )
    op.create_index(
        op.f("ix_capacidades_proveedor_proveedor_id"),
        "capacidades_proveedor",
        ["proveedor_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_capacidades_proveedor_tenant_id"),
        "capacidades_proveedor",
        ["tenant_id"],
        unique=False,
    )
    op.create_table(
        "contratos_proveedor",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("proveedor_id", sa.UUID(), nullable=False),
        sa.Column("numero", sa.String(length=80), nullable=False),
        sa.Column("vigente_desde", sa.Date(), nullable=True),
        sa.Column("vigente_hasta", sa.Date(), nullable=True),
        sa.Column("renovacion_automatica", sa.Boolean(), nullable=False),
        sa.Column("dias_preaviso", sa.Integer(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contratos_proveedor")),
    )
    op.create_index(
        op.f("ix_contratos_proveedor_proveedor_id"),
        "contratos_proveedor",
        ["proveedor_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_contratos_proveedor_tenant_id"), "contratos_proveedor", ["tenant_id"], unique=False
    )
    op.create_table(
        "peticiones_oferta",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("oportunidad_id", sa.UUID(), nullable=True),
        sa.Column("categoria", sa.String(length=80), nullable=False),
        sa.Column("descripcion", sa.Text(), nullable=False),
        sa.Column("cantidad", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("unidad", sa.String(length=20), nullable=False),
        sa.Column("fecha_limite", sa.Date(), nullable=False),
        sa.Column("fecha_necesaria", sa.Date(), nullable=True),
        sa.Column(
            "proveedores",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("estado", sa.String(length=20), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_peticiones_oferta")),
    )
    op.create_index(
        op.f("ix_peticiones_oferta_tenant_id"), "peticiones_oferta", ["tenant_id"], unique=False
    )
    op.create_table(
        "reservas_capacidad",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("capacidad_id", sa.UUID(), nullable=False),
        sa.Column("respuesta_id", sa.UUID(), nullable=True),
        sa.Column("oportunidad_id", sa.UUID(), nullable=True),
        sa.Column("cantidad", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("firme", sa.Boolean(), nullable=False),
        sa.Column("forzada", sa.Boolean(), nullable=False),
        sa.Column("motivo", sa.Text(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reservas_capacidad")),
    )
    op.create_index(
        op.f("ix_reservas_capacidad_capacidad_id"),
        "reservas_capacidad",
        ["capacidad_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_reservas_capacidad_tenant_id"), "reservas_capacidad", ["tenant_id"], unique=False
    )
    op.create_table(
        "respuestas_oferta",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("peticion_id", sa.UUID(), nullable=False),
        sa.Column("proveedor_id", sa.UUID(), nullable=False),
        sa.Column("coste_unitario", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("moneda", sa.String(length=3), nullable=False),
        sa.Column("plazo_dias", sa.Integer(), nullable=True),
        sa.Column("recibida_el", sa.Date(), nullable=False),
        sa.Column("notas", sa.Text(), nullable=False),
        sa.Column("estado", sa.String(length=20), nullable=False),
        sa.Column("cantidad_adjudicada", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("fecha_comprometida", sa.Date(), nullable=True),
        sa.Column("entregada_el", sa.Date(), nullable=True),
        sa.Column("coste_final", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column(
            "incidencias",
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
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_respuestas_oferta")),
        sa.UniqueConstraint("tenant_id", "peticion_id", "proveedor_id", name="uq_respuesta_oferta"),
    )
    op.create_index(
        op.f("ix_respuestas_oferta_peticion_id"), "respuestas_oferta", ["peticion_id"], unique=False
    )
    op.create_index(
        op.f("ix_respuestas_oferta_proveedor_id"),
        "respuestas_oferta",
        ["proveedor_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_respuestas_oferta_tenant_id"), "respuestas_oferta", ["tenant_id"], unique=False
    )


def downgrade() -> None:
    # Un `downgrade` que no se ha probado no es un downgrade. Si esta migración
    # no se puede revertir sin pérdida de datos, dilo aquí en vez de dejar un
    # `pass` que promete algo que no cumple.
    op.drop_index(op.f("ix_respuestas_oferta_tenant_id"), table_name="respuestas_oferta")
    op.drop_index(op.f("ix_respuestas_oferta_proveedor_id"), table_name="respuestas_oferta")
    op.drop_index(op.f("ix_respuestas_oferta_peticion_id"), table_name="respuestas_oferta")
    op.drop_table("respuestas_oferta")
    op.drop_index(op.f("ix_reservas_capacidad_tenant_id"), table_name="reservas_capacidad")
    op.drop_index(op.f("ix_reservas_capacidad_capacidad_id"), table_name="reservas_capacidad")
    op.drop_table("reservas_capacidad")
    op.drop_index(op.f("ix_peticiones_oferta_tenant_id"), table_name="peticiones_oferta")
    op.drop_table("peticiones_oferta")
    op.drop_index(op.f("ix_contratos_proveedor_tenant_id"), table_name="contratos_proveedor")
    op.drop_index(op.f("ix_contratos_proveedor_proveedor_id"), table_name="contratos_proveedor")
    op.drop_table("contratos_proveedor")
    op.drop_index(op.f("ix_capacidades_proveedor_tenant_id"), table_name="capacidades_proveedor")
    op.drop_index(op.f("ix_capacidades_proveedor_proveedor_id"), table_name="capacidades_proveedor")
    op.drop_index("ix_capacidades_periodo", table_name="capacidades_proveedor")
    op.drop_table("capacidades_proveedor")
    op.drop_index(op.f("ix_alcances_proveedor_tenant_id"), table_name="alcances_proveedor")
    op.drop_table("alcances_proveedor")
    op.drop_index(op.f("ix_acuerdos_rappel_tenant_id"), table_name="acuerdos_rappel")
    op.drop_index(op.f("ix_acuerdos_rappel_proveedor_id"), table_name="acuerdos_rappel")
    op.drop_table("acuerdos_rappel")
