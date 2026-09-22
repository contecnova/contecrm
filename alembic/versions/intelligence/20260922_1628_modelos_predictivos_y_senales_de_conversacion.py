"""Modelos predictivos y señales de conversación (CRM-05.02.01, CRM-04.02.02.06-07)

Revision ID: 54b1c05e6e66
Revises: 2d56ba1ccd9e
Servicio: intelligence
Fecha: 2026-09-22 16:28:44.062978+00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "54b1c05e6e66"
down_revision = "2d56ba1ccd9e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "anomalias",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("serie_id", sa.UUID(), nullable=False),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("valor", sa.Numeric(precision=16, scale=4), nullable=False),
        sa.Column("esperado", sa.Numeric(precision=16, scale=4), nullable=False),
        sa.Column("desviacion", sa.Numeric(precision=16, scale=4), nullable=False),
        sa.Column("z", sa.Numeric(precision=8, scale=2), nullable=False),
        sa.Column("sentido", sa.String(length=10), nullable=False),
        sa.Column("severidad", sa.String(length=10), nullable=False),
        sa.Column("explicacion", sa.Text(), nullable=False),
        sa.Column("revisada", sa.Boolean(), nullable=False),
        sa.Column("era_real", sa.Boolean(), nullable=True),
        sa.Column("comentario", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_anomalias")),
    )
    op.create_index("ix_anomalias", "anomalias", ["tenant_id", "serie_id", "fecha"], unique=False)
    op.create_index("ix_anomalias_revision", "anomalias", ["tenant_id", "revisada"], unique=False)
    op.create_index(op.f("ix_anomalias_tenant_id"), "anomalias", ["tenant_id"], unique=False)
    op.create_table(
        "derivas_modelo",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("modelo_id", sa.UUID(), nullable=False),
        sa.Column("ventana_desde", sa.Date(), nullable=False),
        sa.Column("ventana_hasta", sa.Date(), nullable=False),
        sa.Column("metrica", sa.String(length=30), nullable=False),
        sa.Column("valor", sa.Numeric(precision=8, scale=4), nullable=False),
        sa.Column("referencia", sa.Numeric(precision=8, scale=4), nullable=False),
        sa.Column("muestras", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_derivas_modelo")),
    )
    op.create_index(
        "ix_derivas_modelo",
        "derivas_modelo",
        ["tenant_id", "modelo_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_derivas_modelo_tenant_id"), "derivas_modelo", ["tenant_id"], unique=False
    )
    op.create_table(
        "modelos_ml",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("tipo", sa.String(length=30), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("estado", sa.String(length=20), nullable=False),
        sa.Column("datos_desde", sa.Date(), nullable=True),
        sa.Column("datos_hasta", sa.Date(), nullable=True),
        sa.Column("ejemplos", sa.Integer(), nullable=False),
        sa.Column(
            "variables",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "pesos",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "metricas",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("entrenado_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activado_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("vigencia_dias", sa.Integer(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_modelos_ml")),
        sa.UniqueConstraint("tenant_id", "tipo", "version", name="uq_modelo_ml_version"),
    )
    op.create_index("ix_modelos_ml", "modelos_ml", ["tenant_id", "tipo", "estado"], unique=False)
    op.create_index(op.f("ix_modelos_ml_tenant_id"), "modelos_ml", ["tenant_id"], unique=False)
    op.create_table(
        "observaciones_serie",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("serie_id", sa.UUID(), nullable=False),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("valor", sa.Numeric(precision=16, scale=4), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_observaciones_serie")),
    )
    op.create_index(
        "ix_observaciones_serie",
        "observaciones_serie",
        ["tenant_id", "serie_id", "fecha"],
        unique=False,
    )
    op.create_index(
        op.f("ix_observaciones_serie_tenant_id"), "observaciones_serie", ["tenant_id"], unique=False
    )
    op.create_table(
        "predicciones",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("tipo", sa.String(length=30), nullable=False),
        sa.Column("objeto", sa.String(length=60), nullable=False),
        sa.Column("objeto_id", sa.UUID(), nullable=False),
        sa.Column("modelo_id", sa.UUID(), nullable=False),
        sa.Column("version_modelo", sa.Integer(), nullable=False),
        sa.Column("valor", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("minimo", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("maximo", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column(
            "factores",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("caduca_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("real", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("real_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_predicciones")),
    )
    op.create_index(
        "ix_predicciones",
        "predicciones",
        ["tenant_id", "objeto", "objeto_id", "tipo"],
        unique=False,
    )
    op.create_index(op.f("ix_predicciones_tenant_id"), "predicciones", ["tenant_id"], unique=False)
    op.create_index(
        "ix_predicciones_vigencia", "predicciones", ["tenant_id", "tipo", "caduca_at"], unique=False
    )
    op.create_table(
        "resumenes_conversacion",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("conversacion_id", sa.UUID(), nullable=False),
        sa.Column("caso_id", sa.UUID(), nullable=True),
        sa.Column("momento", sa.String(length=20), nullable=False),
        sa.Column("texto", sa.Text(), nullable=False),
        sa.Column(
            "pendientes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("mensajes_totales", sa.Integer(), nullable=False),
        sa.Column("mensajes_usados", sa.Integer(), nullable=False),
        sa.Column("parcial", sa.Boolean(), nullable=False),
        sa.Column("estado", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_resumenes_conversacion")),
    )
    op.create_index(
        "ix_resumenes_conversacion",
        "resumenes_conversacion",
        ["tenant_id", "conversacion_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_resumenes_conversacion_tenant_id"),
        "resumenes_conversacion",
        ["tenant_id"],
        unique=False,
    )
    op.create_table(
        "salud_cuentas",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("cuenta_id", sa.UUID(), nullable=False),
        sa.Column("puntuacion", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("anterior", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column("nivel", sa.String(length=20), nullable=False),
        sa.Column(
            "detalle",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "senales_ausentes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("fiable", sa.Boolean(), nullable=False),
        sa.Column("motivo", sa.Text(), nullable=False),
        sa.Column(
            "medida_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_salud_cuentas")),
        sa.UniqueConstraint("tenant_id", "cuenta_id", "medida_at", name="uq_salud_cuenta_momento"),
    )
    op.create_index("ix_salud_cuentas", "salud_cuentas", ["tenant_id", "cuenta_id"], unique=False)
    op.create_index("ix_salud_cuentas_nivel", "salud_cuentas", ["tenant_id", "nivel"], unique=False)
    op.create_index(
        op.f("ix_salud_cuentas_tenant_id"), "salud_cuentas", ["tenant_id"], unique=False
    )
    op.create_table(
        "senales_conversacion",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("conversacion_id", sa.UUID(), nullable=False),
        sa.Column("sentimiento", sa.String(length=20), nullable=False),
        sa.Column("intencion", sa.String(length=20), nullable=False),
        sa.Column("confianza", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column("concluyente", sa.Boolean(), nullable=False),
        sa.Column(
            "indicios",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("sugiere_escalar", sa.Boolean(), nullable=False),
        sa.Column("porque", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_senales_conversacion")),
    )
    op.create_index(
        "ix_senales_conversacion",
        "senales_conversacion",
        ["tenant_id", "conversacion_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_senales_conversacion_tenant_id"),
        "senales_conversacion",
        ["tenant_id"],
        unique=False,
    )
    op.create_table(
        "series_vigiladas",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("ambito", sa.String(length=20), nullable=False),
        sa.Column("clave", sa.String(length=120), nullable=False),
        sa.Column("descripcion", sa.Text(), nullable=False),
        sa.Column("minimo_observaciones", sa.Integer(), nullable=False),
        sa.Column("sigmas", sa.Numeric(precision=4, scale=2), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_series_vigiladas")),
    )
    op.create_index(
        "ix_series_vigiladas", "series_vigiladas", ["tenant_id", "ambito", "clave"], unique=True
    )
    op.create_index(
        op.f("ix_series_vigiladas_tenant_id"), "series_vigiladas", ["tenant_id"], unique=False
    )


def downgrade() -> None:
    # Un `downgrade` que no se ha probado no es un downgrade. Si esta migración
    # no se puede revertir sin pérdida de datos, dilo aquí en vez de dejar un
    # `pass` que promete algo que no cumple.
    op.drop_index(op.f("ix_series_vigiladas_tenant_id"), table_name="series_vigiladas")
    op.drop_index("ix_series_vigiladas", table_name="series_vigiladas")
    op.drop_table("series_vigiladas")
    op.drop_index(op.f("ix_senales_conversacion_tenant_id"), table_name="senales_conversacion")
    op.drop_index("ix_senales_conversacion", table_name="senales_conversacion")
    op.drop_table("senales_conversacion")
    op.drop_index(op.f("ix_salud_cuentas_tenant_id"), table_name="salud_cuentas")
    op.drop_index("ix_salud_cuentas_nivel", table_name="salud_cuentas")
    op.drop_index("ix_salud_cuentas", table_name="salud_cuentas")
    op.drop_table("salud_cuentas")
    op.drop_index(op.f("ix_resumenes_conversacion_tenant_id"), table_name="resumenes_conversacion")
    op.drop_index("ix_resumenes_conversacion", table_name="resumenes_conversacion")
    op.drop_table("resumenes_conversacion")
    op.drop_index("ix_predicciones_vigencia", table_name="predicciones")
    op.drop_index(op.f("ix_predicciones_tenant_id"), table_name="predicciones")
    op.drop_index("ix_predicciones", table_name="predicciones")
    op.drop_table("predicciones")
    op.drop_index(op.f("ix_observaciones_serie_tenant_id"), table_name="observaciones_serie")
    op.drop_index("ix_observaciones_serie", table_name="observaciones_serie")
    op.drop_table("observaciones_serie")
    op.drop_index(op.f("ix_modelos_ml_tenant_id"), table_name="modelos_ml")
    op.drop_index("ix_modelos_ml", table_name="modelos_ml")
    op.drop_table("modelos_ml")
    op.drop_index(op.f("ix_derivas_modelo_tenant_id"), table_name="derivas_modelo")
    op.drop_index("ix_derivas_modelo", table_name="derivas_modelo")
    op.drop_table("derivas_modelo")
    op.drop_index(op.f("ix_anomalias_tenant_id"), table_name="anomalias")
    op.drop_index("ix_anomalias_revision", table_name="anomalias")
    op.drop_index("ix_anomalias", table_name="anomalias")
    op.drop_table("anomalias")
