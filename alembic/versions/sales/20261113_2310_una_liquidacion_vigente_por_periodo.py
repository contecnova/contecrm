"""Una liquidación vigente por plan, beneficiario y periodo (FUN-B-6).

La restricción `uq_liquidacion` no impedía nada: siempre lleva un NULL (usuario
o partner) y en Postgres dos NULL no chocan. Se sustituye por un índice único
parcial con `NULLS NOT DISTINCT` (Postgres 15+; el despliegue usa 16) que no
cuenta las anuladas, para poder volver a liquidar un periodo anulado.

Si ya hay duplicados vigentes, se para y dice cuántos: decidir cuál de dos
liquidaciones es la buena es una decisión de quien paga, no de una migración.

Revision ID: 3b8d5f0c6e21
Revises: 7616ef51ee32
Servicio: sales
Fecha: 2026-11-13 23:10:00+00:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "3b8d5f0c6e21"
down_revision = "7616ef51ee32"
branch_labels = None
depends_on = None


def upgrade() -> None:
    repetidas = (
        op.get_bind()
        .execute(
            sa.text(
                """
            SELECT count(*) FROM (
                SELECT 1 FROM liquidaciones_comision
                WHERE estado <> 'anulada'
                GROUP BY tenant_id, plan_id, usuario_id, partner_id, desde
                HAVING count(*) > 1
            ) d
            """
            )
        )
        .scalar()
    )
    if repetidas:
        raise RuntimeError(
            f"Hay {repetidas} periodos con más de una liquidación vigente. Anula las que "
            "sobren (estado «anulada») y vuelve a migrar: esta migración no elige cuál vale."
        )
    op.drop_constraint("uq_liquidacion", "liquidaciones_comision", type_="unique")
    op.create_index(
        "uq_liquidacion_vigente",
        "liquidaciones_comision",
        ["tenant_id", "plan_id", "usuario_id", "partner_id", "desde"],
        unique=True,
        postgresql_nulls_not_distinct=True,
        postgresql_where=sa.text("estado <> 'anulada'"),
    )


def downgrade() -> None:
    op.drop_index("uq_liquidacion_vigente", table_name="liquidaciones_comision")
    op.create_unique_constraint(
        "uq_liquidacion",
        "liquidaciones_comision",
        ["tenant_id", "plan_id", "usuario_id", "partner_id", "desde"],
    )
