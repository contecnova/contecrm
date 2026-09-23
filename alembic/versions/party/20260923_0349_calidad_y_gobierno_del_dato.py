"""Calidad y gobierno del dato de cliente (CRM-01.01.01, CRM-01.01.02, CRM-01.01.04)

Linaje por valor, cola de excepciones, plan de cuenta, estado financiero
replicado, mapa de influencia y cambio de empresa. Y la marca de cuenta
personal, que no es un modelo aparte a propósito.

Revision ID: 69edc50c4259
Revises: fa0e825d7cb3
Servicio: party
Fecha: 2026-09-23 03:49:32.495433+00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "69edc50c4259"
down_revision = "fa0e825d7cb3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cambios_de_empresa",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("contacto_id", sa.UUID(), nullable=False),
        sa.Column("cuenta_anterior_id", sa.UUID(), nullable=True),
        sa.Column("indicio", sa.String(length=40), nullable=False),
        sa.Column("detalle", sa.Text(), nullable=False),
        sa.Column("estado", sa.String(length=20), nullable=False),
        sa.Column("contacto_nuevo_id", sa.UUID(), nullable=True),
        sa.Column("cuenta_nueva_id", sa.UUID(), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cambios_de_empresa")),
    )
    op.create_index(
        op.f("ix_cambios_de_empresa_tenant_id"), "cambios_de_empresa", ["tenant_id"], unique=False
    )
    op.create_index(
        "ix_cambios_empresa", "cambios_de_empresa", ["tenant_id", "estado"], unique=False
    )
    op.create_table(
        "estados_financieros",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("cuenta_id", sa.UUID(), nullable=False),
        sa.Column("estado", sa.String(length=20), nullable=False),
        sa.Column("limite_credito", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("credito_dispuesto", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("deuda_vencida", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("dias_vencido_maximo", sa.Numeric(precision=6, scale=0), nullable=True),
        sa.Column("moneda", sa.String(length=3), nullable=False),
        sa.Column("bloqueado", sa.Boolean(), nullable=False),
        sa.Column("motivo_bloqueo", sa.Text(), nullable=False),
        sa.Column("vigente_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("origen", sa.String(length=80), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_estados_financieros")),
        sa.UniqueConstraint("tenant_id", "cuenta_id", name="uq_financiero_cuenta"),
    )
    op.create_index(
        op.f("ix_estados_financieros_tenant_id"), "estados_financieros", ["tenant_id"], unique=False
    )
    op.create_table(
        "excepciones_calidad",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("objeto", sa.String(length=40), nullable=False),
        sa.Column("objeto_id", sa.UUID(), nullable=False),
        sa.Column("tipo", sa.String(length=30), nullable=False),
        sa.Column("campo", sa.String(length=80), nullable=False),
        sa.Column("regla", sa.String(length=120), nullable=False),
        sa.Column("detalle", sa.Text(), nullable=False),
        sa.Column("prioridad", sa.Integer(), nullable=False),
        sa.Column("asignada_a", sa.UUID(), nullable=True),
        sa.Column("estado", sa.String(length=20), nullable=False),
        sa.Column("cierre", sa.String(length=30), nullable=False),
        sa.Column("nota_de_cierre", sa.Text(), nullable=False),
        sa.Column("cerrada_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cerrada_por", sa.UUID(), nullable=True),
        sa.Column("datos", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_excepciones_calidad")),
    )
    op.create_index(
        op.f("ix_excepciones_calidad_asignada_a"),
        "excepciones_calidad",
        ["asignada_a"],
        unique=False,
    )
    op.create_index(
        op.f("ix_excepciones_calidad_tenant_id"), "excepciones_calidad", ["tenant_id"], unique=False
    )
    op.create_index(
        "ix_excepciones_cola",
        "excepciones_calidad",
        ["tenant_id", "estado", "prioridad"],
        unique=False,
    )
    op.create_index(
        "ix_excepciones_registro",
        "excepciones_calidad",
        ["tenant_id", "objeto", "objeto_id"],
        unique=False,
    )
    op.create_index(
        "ix_excepciones_regla", "excepciones_calidad", ["tenant_id", "regla"], unique=False
    )
    op.create_table(
        "linaje_valores",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("objeto", sa.String(length=40), nullable=False),
        sa.Column("objeto_id", sa.UUID(), nullable=False),
        sa.Column("campo", sa.String(length=80), nullable=False),
        sa.Column("fuente", sa.String(length=80), nullable=False),
        sa.Column("valor", sa.Text(), nullable=False),
        sa.Column(
            "recibido_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("cambiado_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("gana", sa.Integer().with_variant(sa.Integer(), "postgresql"), nullable=False),
        sa.Column("confianza", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_linaje_valores")),
    )
    op.create_index(
        "ix_linaje_campo",
        "linaje_valores",
        ["tenant_id", "objeto", "objeto_id", "campo"],
        unique=False,
    )
    op.create_index(
        "ix_linaje_registro", "linaje_valores", ["tenant_id", "objeto", "objeto_id"], unique=False
    )
    op.create_index(
        op.f("ix_linaje_valores_tenant_id"), "linaje_valores", ["tenant_id"], unique=False
    )
    op.create_table(
        "planes_cuenta",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("cuenta_id", sa.UUID(), nullable=False),
        sa.Column("periodo", sa.String(length=20), nullable=False),
        sa.Column("objetivo_importe", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("moneda", sa.String(length=3), nullable=False),
        sa.Column(
            "objetivos",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "riesgos",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "hueco",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("calculado_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revisado_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("responsable_id", sa.UUID(), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_planes_cuenta")),
        sa.UniqueConstraint("tenant_id", "cuenta_id", "periodo", name="uq_plan_cuenta"),
    )
    op.create_index(
        op.f("ix_planes_cuenta_tenant_id"), "planes_cuenta", ["tenant_id"], unique=False
    )
    op.create_table(
        "relaciones_persona",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("origen_id", sa.UUID(), nullable=False),
        sa.Column("destino_id", sa.UUID(), nullable=False),
        sa.Column("tipo", sa.String(length=20), nullable=False),
        sa.Column("motivo", sa.Text(), nullable=False),
        sa.Column("anotada_por", sa.UUID(), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_relaciones_persona")),
        sa.UniqueConstraint(
            "tenant_id", "origen_id", "destino_id", "tipo", name="uq_relacion_persona"
        ),
    )
    op.create_index(
        "ix_relaciones_persona", "relaciones_persona", ["tenant_id", "origen_id"], unique=False
    )
    op.create_index(
        op.f("ix_relaciones_persona_tenant_id"), "relaciones_persona", ["tenant_id"], unique=False
    )
    op.add_column(
        "cuentas",
        sa.Column("es_personal", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )


def downgrade() -> None:
    # Un `downgrade` que no se ha probado no es un downgrade. Si esta migración
    # no se puede revertir sin pérdida de datos, dilo aquí en vez de dejar un
    # `pass` que promete algo que no cumple.
    op.drop_column("cuentas", "es_personal")
    op.drop_index(op.f("ix_relaciones_persona_tenant_id"), table_name="relaciones_persona")
    op.drop_index("ix_relaciones_persona", table_name="relaciones_persona")
    op.drop_table("relaciones_persona")
    op.drop_index(op.f("ix_planes_cuenta_tenant_id"), table_name="planes_cuenta")
    op.drop_table("planes_cuenta")
    op.drop_index(op.f("ix_linaje_valores_tenant_id"), table_name="linaje_valores")
    op.drop_index("ix_linaje_registro", table_name="linaje_valores")
    op.drop_index("ix_linaje_campo", table_name="linaje_valores")
    op.drop_table("linaje_valores")
    op.drop_index("ix_excepciones_regla", table_name="excepciones_calidad")
    op.drop_index("ix_excepciones_registro", table_name="excepciones_calidad")
    op.drop_index("ix_excepciones_cola", table_name="excepciones_calidad")
    op.drop_index(op.f("ix_excepciones_calidad_tenant_id"), table_name="excepciones_calidad")
    op.drop_index(op.f("ix_excepciones_calidad_asignada_a"), table_name="excepciones_calidad")
    op.drop_table("excepciones_calidad")
    op.drop_index(op.f("ix_estados_financieros_tenant_id"), table_name="estados_financieros")
    op.drop_table("estados_financieros")
    op.drop_index("ix_cambios_empresa", table_name="cambios_de_empresa")
    op.drop_index(op.f("ix_cambios_de_empresa_tenant_id"), table_name="cambios_de_empresa")
    op.drop_table("cambios_de_empresa")
