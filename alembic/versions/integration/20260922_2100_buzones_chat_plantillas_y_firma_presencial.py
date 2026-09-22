"""Buzones, chat, plantillas documentales y firma presencial (CRM-06.01.01, CRM-06.01.02.09)

Revision ID: f3b40e0d2b16
Revises: 3e4e7cd3fa63
Servicio: integration
Fecha: 2026-09-22 18:44:19.264046+00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "f3b40e0d2b16"
down_revision = "3e4e7cd3fa63"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "buzones",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("usuario_id", sa.UUID(), nullable=False),
        sa.Column("perfil", sa.String(length=60), nullable=False),
        sa.Column("ambito", sa.String(length=20), nullable=False),
        sa.Column("direccion", sa.String(length=320), nullable=False),
        sa.Column("criterio", sa.String(length=40), nullable=False),
        sa.Column("entrante", sa.Boolean(), nullable=False),
        sa.Column("saliente", sa.Boolean(), nullable=False),
        sa.Column("estado", sa.String(length=20), nullable=False),
        sa.Column("motivo", sa.Text(), nullable=False),
        sa.Column("marca_incremento", sa.Text(), nullable=False),
        sa.Column("sincronizado_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_buzones")),
        sa.UniqueConstraint("tenant_id", "usuario_id", "ambito", "direccion", name="uq_buzon"),
    )
    op.create_index("ix_buzones_estado", "buzones", ["tenant_id", "estado"], unique=False)
    op.create_index(op.f("ix_buzones_tenant_id"), "buzones", ["tenant_id"], unique=False)
    op.create_table(
        "canales_chat",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("clave", sa.String(length=80), nullable=False),
        sa.Column("perfil", sa.String(length=60), nullable=False),
        sa.Column("url_entrante", sa.Text(), nullable=False),
        sa.Column("secreto", sa.Text(), nullable=False),
        sa.Column("cabecera_firma", sa.String(length=80), nullable=False),
        sa.Column(
            "ordenes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("activo", sa.Boolean(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_canales_chat")),
        sa.UniqueConstraint("tenant_id", "clave", name="uq_canal_chat"),
    )
    op.create_index("ix_canales_chat", "canales_chat", ["tenant_id", "activo"], unique=False)
    op.create_index(op.f("ix_canales_chat_tenant_id"), "canales_chat", ["tenant_id"], unique=False)
    op.create_table(
        "documentos_enlazados",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("objeto_tipo", sa.String(length=60), nullable=False),
        sa.Column("objeto_id", sa.UUID(), nullable=False),
        sa.Column("documento_id", sa.String(length=120), nullable=False),
        sa.Column("sistema", sa.String(length=60), nullable=False),
        sa.Column("titulo", sa.String(length=300), nullable=False),
        sa.Column("tipo", sa.String(length=60), nullable=False),
        sa.Column("rol", sa.String(length=80), nullable=False),
        sa.Column("enlazado_por", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documentos_enlazados")),
        sa.UniqueConstraint(
            "tenant_id",
            "objeto_tipo",
            "objeto_id",
            "sistema",
            "documento_id",
            "rol",
            name="uq_documento_enlazado",
        ),
    )
    op.create_index(
        "ix_docenlazados_objeto",
        "documentos_enlazados",
        ["tenant_id", "objeto_tipo", "objeto_id"],
        unique=False,
    )
    op.create_table(
        "documentos_generados",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("plantilla_clave", sa.String(length=80), nullable=False),
        sa.Column("plantilla_version", sa.Integer(), nullable=False),
        sa.Column("objeto", sa.String(length=60), nullable=False),
        sa.Column("objeto_id", sa.UUID(), nullable=True),
        sa.Column("documento_id", sa.String(length=200), nullable=False),
        sa.Column("generado_por", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documentos_generados")),
    )
    op.create_index(
        "ix_documentos_generados",
        "documentos_generados",
        ["tenant_id", "plantilla_clave", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_documentos_generados_tenant_id"),
        "documentos_generados",
        ["tenant_id"],
        unique=False,
    )
    op.create_table(
        "elementos_buzon",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("buzon_id", sa.UUID(), nullable=False),
        sa.Column("externo_id", sa.String(length=300), nullable=False),
        sa.Column("tipo", sa.String(length=20), nullable=False),
        sa.Column("asunto", sa.Text(), nullable=False),
        sa.Column("ocurrido_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resultado", sa.String(length=30), nullable=False),
        sa.Column("porque", sa.Text(), nullable=False),
        sa.Column("actividad_id", sa.UUID(), nullable=True),
        sa.Column("version_externa", sa.String(length=120), nullable=False),
        sa.Column(
            "asistentes",
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_elementos_buzon")),
        sa.UniqueConstraint("tenant_id", "buzon_id", "externo_id", name="uq_elemento_buzon"),
    )
    op.create_index(
        "ix_elementos_buzon",
        "elementos_buzon",
        ["tenant_id", "buzon_id", "ocurrido_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_elementos_buzon_tenant_id"), "elementos_buzon", ["tenant_id"], unique=False
    )
    op.create_table(
        "firmas_presenciales",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("objeto", sa.String(length=60), nullable=False),
        sa.Column("objeto_id", sa.UUID(), nullable=True),
        sa.Column("firmante_nombre", sa.String(length=200), nullable=False),
        sa.Column("documento_identidad", sa.String(length=60), nullable=True),
        sa.Column("testigo_id", sa.UUID(), nullable=True),
        sa.Column(
            "trazo",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("puntos", sa.Integer(), nullable=False),
        sa.Column("duracion_ms", sa.Integer(), nullable=False),
        sa.Column("huella_documento", sa.String(length=64), nullable=False),
        sa.Column("documento_id", sa.String(length=200), nullable=False),
        sa.Column("consentimiento_biometrico", sa.Boolean(), nullable=False),
        sa.Column("texto_consentimiento", sa.Text(), nullable=False),
        sa.Column(
            "firmado_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("dispositivo", sa.String(length=200), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_firmas_presenciales")),
    )
    op.create_index(
        "ix_firmas_presenciales",
        "firmas_presenciales",
        ["tenant_id", "objeto", "objeto_id"],
        unique=False,
    )
    op.create_index(
        "ix_firmas_presenciales_huella",
        "firmas_presenciales",
        ["tenant_id", "huella_documento"],
        unique=False,
    )
    op.create_index(
        op.f("ix_firmas_presenciales_tenant_id"), "firmas_presenciales", ["tenant_id"], unique=False
    )
    op.create_table(
        "organizaciones_documentales",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("organizacion", sa.String(length=120), nullable=False),
        sa.Column("estado", sa.String(length=20), nullable=False),
        sa.Column("ultimo_error", sa.String(length=500), nullable=False),
        sa.Column("verificada_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organizaciones_documentales")),
    )
    op.create_index("ix_orgdoc_tenant", "organizaciones_documentales", ["tenant_id"], unique=True)
    op.create_table(
        "plantillas_documento",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("clave", sa.String(length=80), nullable=False),
        sa.Column("tipo", sa.String(length=20), nullable=False),
        sa.Column("nombre", sa.String(length=200), nullable=False),
        sa.Column("idioma", sa.String(length=10), nullable=False),
        sa.Column("cuerpo", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "clausulas_bloqueadas",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("vigente", sa.Boolean(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plantillas_documento")),
        sa.UniqueConstraint("tenant_id", "clave", "version", name="uq_plantilla_doc"),
    )
    op.create_index(
        "ix_plantillas_doc", "plantillas_documento", ["tenant_id", "clave", "vigente"], unique=False
    )
    op.create_index(
        op.f("ix_plantillas_documento_tenant_id"),
        "plantillas_documento",
        ["tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    # Un `downgrade` que no se ha probado no es un downgrade. Si esta migración
    # no se puede revertir sin pérdida de datos, dilo aquí en vez de dejar un
    # `pass` que promete algo que no cumple.
    op.drop_index(op.f("ix_plantillas_documento_tenant_id"), table_name="plantillas_documento")
    op.drop_index("ix_plantillas_doc", table_name="plantillas_documento")
    op.drop_table("plantillas_documento")
    op.drop_index("ix_orgdoc_tenant", table_name="organizaciones_documentales")
    op.drop_table("organizaciones_documentales")
    op.drop_index(op.f("ix_firmas_presenciales_tenant_id"), table_name="firmas_presenciales")
    op.drop_index("ix_firmas_presenciales_huella", table_name="firmas_presenciales")
    op.drop_index("ix_firmas_presenciales", table_name="firmas_presenciales")
    op.drop_table("firmas_presenciales")
    op.drop_index(op.f("ix_elementos_buzon_tenant_id"), table_name="elementos_buzon")
    op.drop_index("ix_elementos_buzon", table_name="elementos_buzon")
    op.drop_table("elementos_buzon")
    op.drop_index(op.f("ix_documentos_generados_tenant_id"), table_name="documentos_generados")
    op.drop_index("ix_documentos_generados", table_name="documentos_generados")
    op.drop_table("documentos_generados")
    op.drop_index("ix_docenlazados_objeto", table_name="documentos_enlazados")
    op.drop_table("documentos_enlazados")
    op.drop_index(op.f("ix_canales_chat_tenant_id"), table_name="canales_chat")
    op.drop_index("ix_canales_chat", table_name="canales_chat")
    op.drop_table("canales_chat")
    op.drop_index(op.f("ix_buzones_tenant_id"), table_name="buzones")
    op.drop_index("ix_buzones_estado", table_name="buzones")
    op.drop_table("buzones")
