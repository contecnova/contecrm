"""Invocar una operación declarada de una conexión DESDE dentro de integración.

La telefonía, la compensación externa y las referencias de la suite llaman a
un proveedor por su conexión. Lo hacían tres copias de lo mismo —buscar la
operación, sacar los secretos, ejecutar el conector, apuntar la traza— o, peor,
no lo hacía nadie. Aquí está una vez, con la traza en el monitor de
integraciones también cuando falla: una llamada que no deja rastro al fallar es
la que se investiga en el proveedor, donde todo está bien.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from uuid import UUID

from crmcore.errors import CrmError, ErrorDependencia
from sqlalchemy import select
from sqlalchemy.orm import Session


def operacion_declarada(db: Session, conexion_id: UUID, clave: str) -> bool:
    """Si la conexión tiene declarada y activa esa operación."""
    from services.integration.modelos import Operacion

    return (
        db.execute(
            select(Operacion.id).where(
                Operacion.conexion_id == conexion_id,
                Operacion.clave == clave,
                Operacion.activa.is_(True),
            )
        ).first()
        is not None
    )


def ejecutar(
    db: Session,
    *,
    conexion: Any,
    clave: str,
    parametros: dict[str, Any],
    timeout_s: float = 30.0,
    codigo_error: str = "integracion.operacion_no_declarada",
) -> dict[str, Any]:
    """Ejecuta la operación `clave` de la conexión y devuelve lo que contesta.

    Se ejecuta en la misma petición: quien pulsa «Llamar» espera a que la
    centralita diga que ha marcado. La traza se apunta pase lo que pase.
    """
    from services.integration import conector
    from services.integration.api import _secretos
    from services.integration.modelos import Ejecucion, Operacion

    fila = db.execute(
        select(Operacion).where(
            Operacion.conexion_id == conexion.id,
            Operacion.clave == clave,
            Operacion.activa.is_(True),
        )
    ).scalar_one_or_none()
    if fila is None:
        raise ErrorDependencia(
            f"La conexión «{conexion.nombre}» no declara la operación «{clave}». "
            "Declararla es configuración, no código: Integraciones › la conexión › "
            "Declarar una operación.",
            error_code=codigo_error,
            detalle={"conexion": conexion.nombre, "operacion": clave},
        )

    inicio = time.perf_counter()
    traza = Ejecucion(
        tenant_id=conexion.tenant_id,
        conexion_id=conexion.id,
        operacion=clave,
        resultado="ok",
        parametros=parametros,
    )
    try:
        resultado = asyncio.run(
            conector.ejecutar(
                dict(conexion.config or {}),
                dict(fila.definicion or {}),
                parametros,
                secretos=_secretos(db, conexion.id),
                tenant_id=str(conexion.tenant_id),
                timeout_s=timeout_s,
            )
        )
    except CrmError as exc:
        traza.resultado = "error"
        traza.error = f"{exc.error_code}: {exc.mensaje}"[:2000]
        traza.duracion_ms = int((time.perf_counter() - inicio) * 1000)
        db.add(traza)
        db.flush()
        raise
    traza.registros = len(resultado["registros"])
    traza.paginas = resultado["paginas"]
    traza.duracion_ms = int((time.perf_counter() - inicio) * 1000)
    db.add(traza)
    db.flush()
    return resultado


def primer_registro(resultado: dict[str, Any]) -> dict[str, Any]:
    """El primer registro mapeado, o vacío."""
    registros = resultado.get("registros") or []
    return dict(registros[0]) if registros and isinstance(registros[0], dict) else {}
