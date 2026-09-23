"""Ingresos recurrentes, reparto, grupo de compra y plan conjunto (CRM-03.01)

Lo recurrente y lo puntual separados, el calendario de ingreso que usa la
previsión, el crédito que suma 100 y la revisión que se puede comparar con lo que
pasó.

Revision ID: e475fba37933
Revises: bd50c599fe59
Servicio: sales
Fecha: 2026-09-23 05:02:34.572920+00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "e475fba37933"
down_revision = "bd50c599fe59"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lineas_ingreso",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("oportunidad_id", sa.UUID(), nullable=False),
        sa.Column("periodo", sa.Date(), nullable=False),
        sa.Column("importe", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("tipo", sa.String(length=20), nullable=False),
        sa.Column("moneda", sa.String(length=3), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lineas_ingreso")),
    )
    op.create_index(
        "ix_lineas_ingreso_op", "lineas_ingreso", ["tenant_id", "oportunidad_id"], unique=False
    )
    op.create_index(
        "ix_lineas_ingreso_periodo", "lineas_ingreso", ["tenant_id", "periodo"], unique=False
    )
    op.create_index(
        op.f("ix_lineas_ingreso_tenant_id"), "lineas_ingreso", ["tenant_id"], unique=False
    )
    op.create_table(
        "participaciones_comerciales",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("oportunidad_id", sa.UUID(), nullable=False),
        sa.Column("usuario_id", sa.UUID(), nullable=False),
        sa.Column("papel", sa.String(length=20), nullable=False),
        sa.Column("porcentaje", sa.Numeric(precision=6, scale=2), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_participaciones_comerciales")),
        sa.UniqueConstraint(
            "tenant_id", "oportunidad_id", "usuario_id", "papel", name="uq_participacion"
        ),
    )
    op.create_index(
        op.f("ix_participaciones_comerciales_tenant_id"),
        "participaciones_comerciales",
        ["tenant_id"],
        unique=False,
    )
    op.create_table(
        "planes_conjuntos_cliente",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("oportunidad_id", sa.UUID(), nullable=False),
        sa.Column("fecha_objetivo", sa.Date(), nullable=True),
        sa.Column(
            "pasos",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("compartido_con_el_cliente", sa.Boolean(), nullable=False),
        sa.Column("visto_por_el_cliente_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_planes_conjuntos_cliente")),
    )
    op.create_index(
        op.f("ix_planes_conjuntos_cliente_tenant_id"),
        "planes_conjuntos_cliente",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_planes_conjuntos_op",
        "planes_conjuntos_cliente",
        ["tenant_id", "oportunidad_id"],
        unique=False,
    )
    op.create_table(
        "relaciones_oportunidad",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("origen_id", sa.UUID(), nullable=False),
        sa.Column("destino_id", sa.UUID(), nullable=False),
        sa.Column("tipo", sa.String(length=20), nullable=False),
        sa.Column(
            "datos",
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_relaciones_oportunidad")),
        sa.UniqueConstraint("tenant_id", "origen_id", "destino_id", "tipo", name="uq_relacion_op"),
    )
    op.create_index(
        op.f("ix_relaciones_oportunidad_tenant_id"),
        "relaciones_oportunidad",
        ["tenant_id"],
        unique=False,
    )
    op.create_table(
        "revisiones_oportunidad",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("oportunidad_id", sa.UUID(), nullable=False),
        sa.Column("revisada_por", sa.UUID(), nullable=True),
        sa.Column(
            "respuestas",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("probabilidad_declarada", sa.Integer(), nullable=False),
        sa.Column("fecha_declarada", sa.Date(), nullable=True),
        sa.Column(
            "acuerdos",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("resultado", sa.String(length=20), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_revisiones_oportunidad")),
    )
    op.create_index(
        "ix_revisiones_op", "revisiones_oportunidad", ["tenant_id", "oportunidad_id"], unique=False
    )
    op.create_index(
        op.f("ix_revisiones_oportunidad_tenant_id"),
        "revisiones_oportunidad",
        ["tenant_id"],
        unique=False,
    )
    op.create_table(
        "roles_compra",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("oportunidad_id", sa.UUID(), nullable=False),
        sa.Column("contacto_id", sa.UUID(), nullable=False),
        sa.Column("rol", sa.String(length=20), nullable=False),
        sa.Column("postura", sa.Numeric(precision=2, scale=0), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_roles_compra")),
        sa.UniqueConstraint(
            "tenant_id", "oportunidad_id", "contacto_id", "rol", name="uq_rol_compra"
        ),
    )
    op.create_index(op.f("ix_roles_compra_tenant_id"), "roles_compra", ["tenant_id"], unique=False)


def downgrade() -> None:
    # Un `downgrade` que no se ha probado no es un downgrade. Si esta migración
    # no se puede revertir sin pérdida de datos, dilo aquí en vez de dejar un
    # `pass` que promete algo que no cumple.
    op.drop_index(op.f("ix_roles_compra_tenant_id"), table_name="roles_compra")
    op.drop_table("roles_compra")
    op.drop_index(op.f("ix_revisiones_oportunidad_tenant_id"), table_name="revisiones_oportunidad")
    op.drop_index("ix_revisiones_op", table_name="revisiones_oportunidad")
    op.drop_table("revisiones_oportunidad")
    op.drop_index(op.f("ix_relaciones_oportunidad_tenant_id"), table_name="relaciones_oportunidad")
    op.drop_table("relaciones_oportunidad")
    op.drop_index("ix_planes_conjuntos_op", table_name="planes_conjuntos_cliente")
    op.drop_index(
        op.f("ix_planes_conjuntos_cliente_tenant_id"), table_name="planes_conjuntos_cliente"
    )
    op.drop_table("planes_conjuntos_cliente")
    op.drop_index(
        op.f("ix_participaciones_comerciales_tenant_id"), table_name="participaciones_comerciales"
    )
    op.drop_table("participaciones_comerciales")
    op.drop_index(op.f("ix_lineas_ingreso_tenant_id"), table_name="lineas_ingreso")
    op.drop_index("ix_lineas_ingreso_periodo", table_name="lineas_ingreso")
    op.drop_index("ix_lineas_ingreso_op", table_name="lineas_ingreso")
    op.drop_table("lineas_ingreso")
