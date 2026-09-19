"""Qué puede pedirle una automatización a `sales` (CRM-00.03.03.03).

La lista blanca de campos la declara este servicio, no quien manda el comando.
Sin ella, una regla podría fijar el `estado` de una oportunidad saltándose la
máquina de estados, o su `importe` sin que quede rastro de quién lo cambió.

Asignar sí se admite, y es el caso de uso principal —«los leads de industria, a
Marta»—, pero pasa por el mismo camino que una asignación manual: queda
auditada y con el origen puesto.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.bus.comandos import Manejador, registrar_manejador
from crmcore.logging import get_logger
from sqlalchemy.orm import Session

logger = get_logger(__name__)

# En un lead, una regla puede puntuar y etiquetar. No puede cambiar su estado:
# para eso está la máquina, que exige motivo en el descarte y prohíbe volver de
# «convertido».
CAMPOS_LEAD = frozenset({"puntuacion", "campos", "origen", "campana_id"})
CAMPOS_OPORTUNIDAD = frozenset({"probabilidad", "fecha_cierre", "campos", "descripcion"})


def _asignar(modelo: type, objeto: str) -> Any:
    def _ejecutar(
        db: Session,
        *,
        registro_id: Any = None,
        datos: dict[str, Any],
        origen: str,
        origen_id: str | None = None,
    ) -> None:
        from datetime import datetime, timezone

        from crmcore.audit.chain import registrar

        owner = datos.get("owner_id")
        if not registro_id or not owner:
            return
        fila = db.get(modelo, UUID(str(registro_id)))
        if fila is None or getattr(fila, "deleted_at", None) is not None:
            logger.info("sales.comando_sobre_registro_ausente", registro=str(registro_id))
            return

        anterior = fila.owner_id
        fila.owner_id = UUID(str(owner))
        if hasattr(fila, "asignado_at"):
            fila.asignado_at = datetime.now(timezone.utc)
        registrar(
            db,
            accion=f"{objeto}.asignado",
            objeto=objeto,
            objeto_id=fila.id,
            datos={
                "de": str(anterior) if anterior else None,
                "a": str(owner),
                "origen": origen,
                "origen_id": origen_id,
            },
            tenant_id=fila.tenant_id,
        )
        db.flush()

    return _ejecutar


def _actualizar(modelo: type, objeto: str) -> Any:
    def _ejecutar(
        db: Session,
        *,
        registro_id: Any = None,
        datos: dict[str, Any],
        origen: str,
        origen_id: str | None = None,
    ) -> None:
        from crmcore.audit.chain import registrar_cambios

        if not registro_id or not datos:
            return
        fila = db.get(modelo, UUID(str(registro_id)))
        if fila is None or getattr(fila, "deleted_at", None) is not None:
            return
        anterior = fila.a_dict()
        for campo, valor in datos.items():
            setattr(fila, campo, valor)
        fila.updated_origen = f"automatizacion:{origen_id}" if origen_id else "automatizacion"
        registrar_cambios(
            db, objeto=objeto, objeto_id=fila.id, anterior=anterior, nuevo=fila.a_dict()
        )
        db.flush()

    return _ejecutar


def _registrar_todo() -> None:
    from services.sales.modelos import Lead, Oportunidad

    for modelo, objeto, campos in (
        (Lead, "lead", CAMPOS_LEAD),
        (Oportunidad, "oportunidad", CAMPOS_OPORTUNIDAD),
    ):
        registrar_manejador(
            Manejador(
                objeto=objeto,
                accion="asignar",
                ejecutar=_asignar(modelo, objeto),
                campos_permitidos=frozenset({"owner_id"}),
            )
        )
        registrar_manejador(
            Manejador(
                objeto=objeto,
                accion="actualizar",
                ejecutar=_actualizar(modelo, objeto),
                campos_permitidos=campos,
            )
        )


_registrar_todo()
