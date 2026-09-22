"""Los conectores que trae un módulo se vuelven proveedores (CRM-00.04.04.06).

Un módulo vertical declara sus conectores —el transportista, el mapa de estados,
el plazo— y quien tiene que usarlos es este servicio. `integration` no puede leer
el esquema de `metadata`, así que la declaración llega **por evento**, igual que
los tipos de cambio, los calendarios y el esquema del tenant.

Lo que se replica es **declaración, no datos del tenant**: un mapa de estados y
una URL base. Por eso cabe en el evento y por eso no hay que pedirlo después.

Dos cosas que son el precio de esta decisión, dichas en voz alta:

**Lo que el cliente haya cambiado a mano no se pisa.** Si alguien corrigió el
plazo de un transportista porque en su ruta es otro, una actualización del módulo
no se lo devuelve al valor de fábrica: perder ese ajuste se nota semanas después,
cuando los informes de cumplimiento empiezan a decir que todo llega tarde.

**Desinstalar un módulo desactiva sus proveedores, no los borra.** Los encargos
en vuelo siguen apuntando a ellos, y borrar la ficha dejaría sin nombre ni mapa
de estados a envíos que todavía están en la calle.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.logging import get_logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.integration.encargos import Proveedor

logger = get_logger(__name__)


def aplicar_conectores(
    db: Session, tenant_id: UUID, *, modulo: str, conectores: list[dict[str, Any]]
) -> dict[str, Any]:
    """Crea o actualiza los proveedores que declara un módulo."""
    creados: list[str] = []
    actualizados: list[str] = []
    respetados: list[str] = []

    for definicion in conectores:
        clave = str(definicion.get("clave") or "").strip()
        if not clave:
            logger.warning("integration.conector_sin_clave", modulo=modulo)
            continue
        fila = db.execute(
            select(Proveedor).where(Proveedor.tenant_id == tenant_id, Proveedor.clave == clave)
        ).scalar_one_or_none()

        valores = {
            "nombre": str(definicion.get("nombre") or clave),
            "mapa_estados": dict(
                definicion.get("mapeo_estados") or definicion.get("mapa_estados") or {}
            ),
        }
        if definicion.get("plazo_horas") is not None:
            valores["plazo_horas"] = int(definicion["plazo_horas"])
        if definicion.get("silencio_horas") is not None:
            valores["silencio_horas"] = int(definicion["silencio_horas"])

        if fila is None:
            db.add(Proveedor(tenant_id=tenant_id, clave=clave, modulo=modulo, **valores))
            creados.append(clave)
            continue

        if fila.modulo and fila.modulo != modulo:
            # Dos módulos que declaran el mismo transportista. Gana el que ya
            # estaba: pisarlo en silencio haría que instalar un módulo cambiara
            # el comportamiento de otro sin que nadie lo pidiera.
            respetados.append(clave)
            logger.warning(
                "integration.conector_en_disputa", clave=clave, de=fila.modulo, quiere=modulo
            )
            continue
        if fila.modulo is None:
            # Lo creó una persona a mano. El módulo no se lo queda.
            respetados.append(clave)
            continue

        for campo, valor in valores.items():
            setattr(fila, campo, valor)
        fila.activo = True
        actualizados.append(clave)

    db.flush()
    return {"creados": creados, "actualizados": actualizados, "respetados": respetados}


def retirar_conectores(db: Session, tenant_id: UUID, *, modulo: str) -> list[str]:
    """Desactiva los proveedores de un módulo que se desinstala.

    **Desactivar y no borrar**: los encargos en vuelo siguen apuntando a ellos, y
    borrar la ficha dejaría sin nombre ni mapa de estados a envíos que todavía
    están en la calle.
    """
    filas = (
        db.execute(
            select(Proveedor).where(Proveedor.tenant_id == tenant_id, Proveedor.modulo == modulo)
        )
        .scalars()
        .all()
    )
    for fila in filas:
        fila.activo = False
    db.flush()
    return [f.clave for f in filas]


async def consumir(mensaje: Any) -> None:
    """Escucha la instalación, la actualización y la retirada de módulos."""
    from crmcore.db.uow import unidad_de_trabajo
    from crmcore.tenancy.context import con_contexto

    tipo = str(getattr(mensaje, "tipo", "") or "")
    if tipo not in ("module.installed", "module.updated", "module.uninstalled"):
        return
    bruto = getattr(mensaje, "tenant_id", None)
    if not bruto:
        logger.warning("integration.modulo_sin_tenant", tipo=tipo)
        return
    tenant_id = UUID(str(bruto))
    datos = getattr(mensaje, "data", None) or {}
    modulo = str(datos.get("modulo") or "")
    if not modulo:
        return

    with con_contexto(tenant_id=tenant_id, origen="bus"), unidad_de_trabajo(tenant_id) as uow:
        if tipo == "module.uninstalled":
            retirados = retirar_conectores(uow.db, tenant_id, modulo=modulo)
            if retirados:
                logger.info("integration.conectores_retirados", modulo=modulo, claves=retirados)
            return
        conectores = [c for c in (datos.get("conectores") or []) if isinstance(c, dict)]
        if not conectores:
            return
        resultado = aplicar_conectores(uow.db, tenant_id, modulo=modulo, conectores=conectores)
        logger.info("integration.conectores_aplicados", modulo=modulo, **resultado)
