"""Arranca el proceso que pide una automatización (`comando.proceso.lanzar`).

La acción «lanzar_proceso» de `automation` emite un comando con la clave del
proceso y sus variables de entrada. Hasta el 09-11-2026 no lo escuchaba nadie:
la regla decía «proceso lanzado» en su historial y el proceso no existía. Lo
atiende este servicio porque es el dueño de las instancias —`automation` no
puede escribir en este esquema, y eso es lo que mantiene la propiedad del dato—.

**Con qué permisos actúa.** Los de quien activó la automatización, si el comando
los trae en `datos.lanzado_por` = `{"principal_id", "tipo", "permisos",
"roles"}`. Si no los trae, la instancia arranca SIN identidad: sus decisiones y
sus tareas humanas funcionan, y el primer paso que tenga que llamar al CRM falla
diciendo que no se sabe con qué permisos actuar. Inventarlos —los de un
administrador, los de «la casa»— daría a una regla cualquiera poderes que nadie
le dio.

**Un comando que no se puede cumplir no se reintenta.** Un proceso que no está
publicado, o la cuota del mes agotada, no se arreglan solos en el siguiente
reintento: se registra y se descarta. Dejar que el error suba repetiría el
mensaje sin fin.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.errors import CrmError
from crmcore.logging import get_logger

logger = get_logger(__name__)

TIPO = "comando.proceso.lanzar"


def identidad_del_comando(datos: dict[str, Any]) -> tuple[UUID | None, dict[str, Any] | None]:
    """(quién, con qué) a partir de `datos.lanzado_por`. (None, None) si no viene.

    Se exige el identificador Y la lista de permisos: con sólo uno de los dos
    no se puede llamar en nombre de nadie, y aceptarlo a medias sería volver a
    inventar la otra mitad.
    """
    bruto = datos.get("lanzado_por")
    if not isinstance(bruto, dict):
        return None, None
    try:
        quien = UUID(str(bruto.get("principal_id") or ""))
    except ValueError:
        return None, None
    permisos = bruto.get("permisos")
    if not isinstance(permisos, list):
        return None, None
    return quien, {
        "tipo": str(bruto.get("tipo") or "usuario"),
        "permisos": sorted({str(p) for p in permisos}),
        "roles": sorted({str(r) for r in bruto.get("roles") or []}),
    }


async def consumir(mensaje: Any) -> None:
    from crmcore.db.uow import unidad_de_trabajo
    from crmcore.tenancy.context import con_contexto

    from services.orchestrator.motor import Motor

    if str(getattr(mensaje, "tipo", "") or "") != TIPO:
        return
    bruto = getattr(mensaje, "tenant_id", None)
    sobre = getattr(mensaje, "data", None) or {}
    datos = sobre.get("datos") or {}
    clave = str(datos.get("definicion") or "").strip()
    if not bruto or not clave:
        logger.warning("lanzar_proceso.comando_incompleto", tenant=str(bruto or ""))
        return
    tenant_id = UUID(str(bruto))
    entrada = datos.get("entrada") if isinstance(datos.get("entrada"), dict) else {}
    lanzada_por, permisos = identidad_del_comando(datos)

    with (
        con_contexto(tenant_id=tenant_id, origen="automatizacion"),
        unidad_de_trabajo(tenant_id) as uow,
    ):
        try:
            instancia = Motor(uow.db).arrancar(
                tenant_id=tenant_id,
                clave=clave,
                variables=dict(entrada),
                origen=(
                    str(sobre.get("origen") or "automatizacion")[:60],
                    str(sobre.get("origen_id") or "")[:80],
                ),
                lanzada_por=lanzada_por,
                permisos_de_lanzamiento=permisos,
            )
        except CrmError as exc:
            logger.warning(
                "lanzar_proceso.no_se_puede",
                clave=clave,
                error_code=getattr(exc, "error_code", ""),
                motivo=str(exc)[:200],
            )
            return
        logger.info(
            "lanzar_proceso.arrancado",
            clave=clave,
            instancia=str(instancia.id),
            con_identidad=permisos is not None,
        )
