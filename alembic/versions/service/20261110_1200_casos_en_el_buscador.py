"""Los casos que ya existían, al índice del buscador (CRM-00.01.01.09).

Desde hoy cada caso se indexa al abrirse y al cambiar de estado, pero los que ya
estaban no habían pasado nunca por ahí: sin esto, el buscador encontraría los
casos nuevos y no los de antes, que es justo lo que un agente busca por su
código. Se copian de `casos` a `indice_busqueda` con la misma forma que pone
`services/service/indexacion.py` —asunto de título, código de subtítulo, código
y descripción en el cuerpo— y sin pisar lo que ya esté indexado. Los borrados
no entran.

El downgrade quita del índice los casos y nada más: el índice se rehace solo con
el uso, y dejar filas de un objeto que el buscador ya no pregunta no hace daño,
pero tampoco sirve.

Revision ID: 7d3c1e9b5a20
Revises: 4b8e2f6a1c90
Servicio: service
Fecha: 2026-11-10 12:00:00+00:00
"""

from __future__ import annotations

from alembic import op

revision = "7d3c1e9b5a20"
down_revision = "4b8e2f6a1c90"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO indice_busqueda
            (id, tenant_id, objeto, registro_id, titulo, subtitulo, cuerpo, owner_id, extra)
        SELECT gen_random_uuid(),
               c.tenant_id,
               'caso',
               c.id,
               LEFT(COALESCE(NULLIF(c.asunto, ''), c.codigo, '(caso sin asunto)'), 300),
               LEFT(COALESCE(c.codigo, ''), 300),
               CONCAT_WS(' ', c.codigo, c.descripcion),
               c.owner_id,
               jsonb_build_object('estado', c.estado, 'prioridad', c.prioridad)
          FROM casos c
         WHERE c.deleted_at IS NULL
        ON CONFLICT ON CONSTRAINT uq_indice_registro DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM indice_busqueda WHERE objeto = 'caso'")
