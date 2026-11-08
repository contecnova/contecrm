"""Lecciones y avisos son parte de su oportunidad: clave ajena en cascada.

Sin ella, la protección de integridad los contaba como referencias y ninguna
oportunidad cerrada —todas tienen su lección— se podía borrar. `NOT VALID`
para no fallar por filas viejas: la cascada vale para lo que se borre de aquí
en adelante.

Revision ID: 2a7c5e9f3b10
Revises: 9d4f2b7e61a8
Servicio: sales
Fecha: 2026-11-08 20:00:00+00:00
"""

from __future__ import annotations

from alembic import op

revision = "2a7c5e9f3b10"
down_revision = "9d4f2b7e61a8"
branch_labels = None
depends_on = None

_CLAVES = (
    ("lecciones_oportunidad", "fk_lecciones_oportunidad_oportunidad_id_oportunidades"),
    ("avisos_leccion", "fk_avisos_leccion_oportunidad_id_oportunidades"),
)


def upgrade() -> None:
    for tabla, nombre in _CLAVES:
        op.create_foreign_key(
            nombre,
            tabla,
            "oportunidades",
            ["oportunidad_id"],
            ["id"],
            ondelete="CASCADE",
            postgresql_not_valid=True,
        )


def downgrade() -> None:
    for tabla, nombre in _CLAVES:
        op.drop_constraint(nombre, tabla, type_="foreignkey")
