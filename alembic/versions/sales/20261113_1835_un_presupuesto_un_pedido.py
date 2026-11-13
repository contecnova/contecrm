"""Un presupuesto, un pedido; y cada envío al ERP, numerado.

Auditoría del 13-11-2026:

* **FUN-B-3.** `aceptar` leía el presupuesto sin bloquearlo y nada impedía dos
  pedidos del mismo presupuesto: dos aceptaciones simultáneas creaban dos
  pedidos y dos envíos al ERP. El código bloquea ya la fila; esta restricción
  única `(tenant_id, presupuesto_id)` es el suelo. Los pedidos sin presupuesto
  (`presupuesto_id` nulo) no chocan entre sí: en Postgres dos nulos no son
  iguales para un `UNIQUE`.
* **FUN-B-4.** `pedidos.envios_erp` cuenta los envíos al ERP para que la clave
  de deduplicación de cada uno sea distinta. Los pedidos que ya existen
  empiezan en 0 y su próximo envío será el 1, que no choca con la clave antigua
  `erp:{id}` (no lleva número).

Si ya hay presupuestos con más de un pedido la restricción no se puede crear, y
la migración **se para diciendo cuántos**, en vez de borrar alguno: cuál de los
dos pedidos es el bueno —el que llegó al ERP, el que se facturó— no lo sabe una
migración, y elegir mal es perder una venta.

Revision ID: 7616ef51ee32
Revises: 732bfdc606d2
Servicio: sales
Fecha: 2026-11-13 18:35:00+00:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "7616ef51ee32"
down_revision = "732bfdc606d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pedidos",
        sa.Column("envios_erp", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    repetidos = (
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT count(*) FROM (
                    SELECT 1 FROM pedidos
                     WHERE presupuesto_id IS NOT NULL
                     GROUP BY tenant_id, presupuesto_id
                    HAVING count(*) > 1
                ) d
                """
            )
        )
        .scalar()
    )
    if repetidos:
        raise RuntimeError(
            f"Hay {repetidos} presupuesto(s) con más de un pedido. Decide a mano "
            "cuál es el bueno (el que llegó al ERP, el que se facturó) y borra o "
            "desvincula el otro antes de migrar: elegirlo aquí sería adivinar."
        )
    op.create_unique_constraint("uq_pedido_presupuesto", "pedidos", ["tenant_id", "presupuesto_id"])


def downgrade() -> None:
    op.drop_constraint("uq_pedido_presupuesto", "pedidos", type_="unique")
    op.drop_column("pedidos", "envios_erp")
