"""Retención del audit trail y volcado a un SIEM (CRM-00.05.04.04).

Dos cosas que van juntas y suelen contarse por separado.

**La retención**: un audit trail que crece para siempre acaba siendo la tabla
más grande del sistema y la más lenta de consultar, y entonces se deja de
consultar. Pero borrarlo sin más rompe la cadena de hashes, que es lo que lo
hace verificable. Así que se **purga por tramos completos y se deja constancia
del corte**: quien verifique la cadena a partir de ahí encuentra el punto y el
motivo, en vez de un hueco que parece manipulación.

**El volcado**: quien tiene un SIEM quiere los eventos de seguridad en él, no en
otra pantalla más. Se exporta en un formato neutro —JSON Lines con los campos
habituales— y no en el de un producto concreto: escribir el formato de uno ata
la instalación a ese uno, y el adaptador de cualquier SIEM a JSON Lines son
veinte líneas.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from crmcore.audit.modelos import ApunteAuditoria
from crmcore.errors import Conflicto
from crmcore.logging import get_logger

logger = get_logger(__name__)


def a_jsonl(db: Session, tenant_id: UUID, *, desde: datetime, hasta: datetime) -> Iterator[str]:
    """Los apuntes de un periodo, una línea por apunte.

    Se devuelve como generador y no como lista: un año de audit trail de un
    tenant activo no cabe cómodamente en memoria, y cargarlo entero para
    volcarlo a un fichero es justo el patrón que hace que la exportación tumbe
    el proceso.
    """
    filas = db.execute(
        select(ApunteAuditoria)
        .where(
            ApunteAuditoria.tenant_id == tenant_id,
            ApunteAuditoria.created_at >= desde,
            ApunteAuditoria.created_at < hasta,
        )
        .order_by(ApunteAuditoria.secuencia)
    ).scalars()

    for fila in filas:
        yield (
            json.dumps(
                {
                    # Nombres neutros y no los de un producto concreto: el adaptador
                    # de cualquier SIEM a esto son veinte líneas, y escribir el
                    # formato de uno ata la instalación a ese uno.
                    "timestamp": fila.created_at.isoformat(),
                    "tenant": str(fila.tenant_id),
                    "action": fila.accion,
                    "object": fila.objeto,
                    "object_id": fila.objeto_id,
                    "actor": str(fila.actor_id) if fila.actor_id else None,
                    "actor_type": fila.actor_tipo,
                    "on_behalf_of": str(fila.actor_real_id) if fila.actor_real_id else None,
                    "source": fila.origen,
                    "ip": fila.ip,
                    "request_id": fila.request_id,
                    "reason": fila.motivo,
                    "data": fila.datos,
                    # La secuencia y el hash viajan también: es lo que permite a
                    # quien lo reciba comprobar que no falta nada por el camino.
                    "sequence": fila.secuencia,
                    "hash": fila.hash,
                    "previous_hash": fila.hash_previo,
                },
                ensure_ascii=False,
            )
            + "\n"
        )


def purgar(
    db: Session, tenant_id: UUID, *, dias_retencion: int, por: UUID | None = None
) -> dict[str, Any]:
    """Borra lo más viejo que la retención, dejando constancia del corte.

    **Se purga por tramos completos desde el principio**, nunca por el medio: la
    cadena de hashes encadena cada apunte con el anterior, así que quitar uno de
    en medio la rompe y quien la verifique después no puede distinguir eso de
    una manipulación.

    Y antes de borrar se apunta **qué se borra y hasta dónde**, en un apunte que
    queda dentro de la cadena. Así quien verifique encuentra el corte explicado
    en vez de un hueco.
    """
    from crmcore.audit import registrar

    if dias_retencion < 1:
        raise Conflicto(
            "Una retención de menos de un día borraría el rastro del propio día",
            error_code="siem.retencion_invalida",
        )

    corte = datetime.now(timezone.utc) - timedelta(days=dias_retencion)
    ultimo = db.execute(
        select(func.max(ApunteAuditoria.secuencia)).where(
            ApunteAuditoria.tenant_id == tenant_id, ApunteAuditoria.created_at < corte
        )
    ).scalar_one_or_none()
    if ultimo is None:
        return {"borrados": 0, "hasta_secuencia": None}

    cuantos = int(
        db.execute(
            select(func.count())
            .select_from(ApunteAuditoria)
            .where(ApunteAuditoria.tenant_id == tenant_id, ApunteAuditoria.secuencia <= ultimo)
        ).scalar_one()
        or 0
    )

    # El apunte del corte va ANTES del borrado y por tanto queda en la cadena
    # nueva: si fuera después, el primer apunte tras la purga no tendría con qué
    # encadenarse y la verificación fallaría en el sitio equivocado.
    registrar(
        db,
        accion="auditoria.purgada",
        objeto="auditoria",
        objeto_id=str(ultimo),
        datos={
            "apuntes_borrados": cuantos,
            "hasta_secuencia": ultimo,
            "retencion_dias": dias_retencion,
            "corte": corte.isoformat(),
        },
        motivo=f"Retención de {dias_retencion} días",
        tenant_id=tenant_id,
    )
    db.flush()

    db.query(ApunteAuditoria).filter(
        ApunteAuditoria.tenant_id == tenant_id, ApunteAuditoria.secuencia <= ultimo
    ).delete(synchronize_session=False)
    logger.warning(
        "auditoria.purgada", tenant=str(tenant_id), borrados=cuantos, hasta=ultimo, por=str(por)
    )
    return {"borrados": cuantos, "hasta_secuencia": ultimo}


def consultar(
    db: Session,
    tenant_id: UUID,
    *,
    accion: str = "",
    objeto: str = "",
    actor_id: UUID | None = None,
    desde: datetime | None = None,
    hasta: datetime | None = None,
    limite: int = 100,
) -> list[dict[str, Any]]:
    """Consulta filtrable del audit trail (CRM-00.05.04.05).

    Desde la propia plataforma y no exportando a otro sitio: la pregunta «¿quién
    tocó esta cuenta?» se hace mientras se mira la cuenta, y obligar a salir a
    otra herramienta para responderla significa que casi nunca se responde.
    """
    consulta = select(ApunteAuditoria).where(ApunteAuditoria.tenant_id == tenant_id)
    if accion:
        consulta = consulta.where(ApunteAuditoria.accion == accion)
    if objeto:
        consulta = consulta.where(ApunteAuditoria.objeto == objeto)
    if actor_id:
        consulta = consulta.where(ApunteAuditoria.actor_id == actor_id)
    if desde:
        consulta = consulta.where(ApunteAuditoria.created_at >= desde)
    if hasta:
        consulta = consulta.where(ApunteAuditoria.created_at < hasta)

    filas = (
        db.execute(consulta.order_by(ApunteAuditoria.secuencia.desc()).limit(limite))
        .scalars()
        .all()
    )
    return [
        {
            "secuencia": f.secuencia,
            "cuando": f.created_at.isoformat(),
            "accion": f.accion,
            "objeto": f.objeto,
            "objeto_id": f.objeto_id,
            "actor_id": str(f.actor_id) if f.actor_id else None,
            "en_nombre_de": str(f.actor_real_id) if f.actor_real_id else None,
            "origen": f.origen,
            "ip": f.ip,
            "motivo": f.motivo,
            "datos": f.datos,
        }
        for f in filas
    ]
