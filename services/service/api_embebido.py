"""Lo que un componente incrustado en una web ajena puede leer de service.

Sin identificador en la ruta: el del token (CRM-00.02.03.05). Y sólo lo que el
componente enseña — asunto, estado y cuándo se abrió—, porque lo que viaja a
una página pública está a un clic de verse.
"""

from __future__ import annotations

from typing import Any

from crmcore import embebido
from crmcore.http.deps import AutenticadoDep, DbDep
from fastapi import APIRouter
from sqlalchemy import select

from services.service.modelos import Caso

router_embebido = APIRouter(prefix="/embebido", tags=["componentes embebibles"])


@router_embebido.get(
    "/lista-casos",
    summary="Los casos de la cuenta del token",
    description=(
        "Los de ESA cuenta, que es la del token. Veinte como mucho: un "
        "componente que descarga el historial entero de un cliente grande "
        "tarda en una web ajena y enseña de más."
    ),
)
def lista_casos(db: DbDep, principal: AutenticadoDep) -> Any:
    cuenta_id = embebido.registro_del_token(principal, componente="lista-casos", objeto="cuenta")
    filas = (
        db.execute(
            select(Caso)
            .where(
                Caso.tenant_id == principal.tenant_id,
                Caso.cuenta_id == cuenta_id,
                Caso.deleted_at.is_(None),
            )
            .order_by(Caso.created_at.desc())
            .limit(20)
        )
        .scalars()
        .all()
    )
    return {
        "casos": [
            {
                "codigo": f.codigo,
                "asunto": f.asunto,
                "estado": f.estado,
                "abierto_at": f.created_at.isoformat() if f.created_at else None,
            }
            for f in filas
        ]
    }
