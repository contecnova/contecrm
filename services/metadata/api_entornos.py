"""API de configuración como código: paquetes, promoción, desvío y vuelta atrás
(CRM-07.02.01.03, .04, .06, .07).

Existía el motor y no existía la puerta: todo esto solo se podía usar desde
código, así que la promesa de que **todo se hace por API** tenía un agujero
justo en la parte que más falta hace automatizar — llevar un cambio de pruebas a
producción.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from crmcore.http.pagination import PaginaDeListado
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from services.metadata import entornos as ent
from services.metadata.entornos import ENTORNOS

router_entornos = APIRouter(prefix="/entornos", tags=["ALM y entornos"])


class EmpaquetarIn(BaseModel):
    nombre: str
    contenido: dict[str, Any] = Field(default_factory=dict)
    origen_entorno: str = "desarrollo"
    referencia_git: str = ""
    notas: str = ""


class PromocionIn(BaseModel):
    paquete_id: UUID
    estado_destino: dict[str, Any] = Field(default_factory=dict)


class DesplegarIn(BaseModel):
    paquete_id: UUID


class DriftIn(BaseModel):
    estado_actual: dict[str, Any] = Field(default_factory=dict)


class VolverIn(BaseModel):
    motivo: str


# ── Listado ───────────────────────────────────────────────────────────────
# Se podía desplegar, simular y volver atrás sobre un entorno, y no se podía
# saber cuáles hay. Las acciones cuelgan de `/entornos/{entorno}/...` y a un
# registro se llega por su listado.
#
# No es una tabla: los entornos son una lista cerrada del sistema. Se devuelven
# igual, porque quien integra necesita saber qué nombres admite esa ruta sin
# tener que adivinarlos ni leerse el código.


@router_entornos.get(
    "",
    response_model=PaginaDeListado,
    dependencies=[Depends(exige_permiso("metadata:read"))],
    summary="Entornos por los que pasa la configuración",
    description=(
        "Lista cerrada y en orden de promoción. No se pueden crear otros: un "
        "entorno no es un dato, es una etapa del camino de la configuración "
        "hasta producción."
    ),
)
def listar_entornos() -> Any:
    return {
        "items": [
            {"nombre": nombre, "orden": i, "es_produccion": nombre == "produccion"}
            for i, nombre in enumerate(ENTORNOS)
        ],
        "siguiente": None,
        "hay_mas": False,
    }


@router_entornos.post(
    "/paquetes",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("metadata:write"))],
    summary="Empaquetar un conjunto de cambios de configuración",
    description=(
        "El paquete lleva **de dónde sale y con qué huella**. Un artefacto sin "
        "origen es uno que nadie se atreve a promocionar, y el que no se atreve "
        "lo aplica a mano — que es volver al principio.\n\n"
        "La huella se calcula con las claves ordenadas: si no, el mismo paquete "
        "daría huellas distintas según cómo se serializara y el desvío saltaría "
        "cada día sin que nadie hubiera tocado nada."
    ),
)
def empaquetar(cuerpo: EmpaquetarIn, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = ent.empaquetar(
        uow,
        nombre=cuerpo.nombre,
        contenido=cuerpo.contenido,
        origen_entorno=cuerpo.origen_entorno,
        referencia_git=cuerpo.referencia_git,
        notas=cuerpo.notas,
        por=principal.id,
    )
    return {
        "id": str(fila.id),
        "nombre": fila.nombre,
        "version": fila.version,
        "huella": fila.huella,
    }


@router_entornos.post(
    "/{entorno}/simular",
    dependencies=[Depends(exige_permiso("metadata:read"))],
    summary="Qué pasaría al promocionar, sin aplicar nada",
    description=(
        "Lo que en pruebas era un campo nuevo puede ser en producción un campo "
        "que ya existe con otro tipo. Aplicar y descubrirlo a la mitad deja el "
        "entorno peor que antes.\n\n"
        "Un cambio de **tipo** de campo con datos dentro no se aplica solo: puede "
        "perderlos, y aquí se dice a cuántos registros afectaría."
    ),
)
def simular(entorno: str, cuerpo: PromocionIn, db: DbDep, principal: AutenticadoDep) -> Any:
    return ent.simular_promocion(
        db,
        principal.tenant_id,
        paquete_id=cuerpo.paquete_id,
        entorno=entorno,
        estado_destino=cuerpo.estado_destino,
    )


@router_entornos.post(
    "/{entorno}/desplegar",
    dependencies=[Depends(exige_permiso("metadata:write"))],
    summary="Aplicar un paquete a un entorno",
    description=(
        "Queda registrado qué paquete está aplicado y desde cuándo, que es lo que "
        "permite medir el desvío después — sin saber qué se desplegó, «qué tocó "
        "alguien a mano» no se puede contestar."
    ),
)
def desplegar(entorno: str, cuerpo: DesplegarIn, uow: UowDep, principal: AutenticadoDep) -> Any:
    return ent.desplegar(uow, paquete_id=cuerpo.paquete_id, entorno=entorno, por=principal.id)


@router_entornos.post(
    "/{entorno}/drift",
    dependencies=[Depends(exige_permiso("metadata:read"))],
    summary="Qué se ha tocado fuera del pipeline",
    description=(
        "Se compara contra **el paquete desplegado**, no contra otro entorno. "
        "Comparar dos entornos dice en qué se diferencian —que puede ser "
        "legítimo—; comparar contra lo desplegado dice qué tocó alguien a mano, "
        "que es la pregunta.\n\n"
        "Y **lo que desapareció también es desvío**: un informe que solo enseña lo "
        "que se añadió deja fuera el caso más incómodo."
    ),
)
def drift(entorno: str, cuerpo: DriftIn, db: DbDep, principal: AutenticadoDep) -> Any:
    return ent.medir_drift(
        db, principal.tenant_id, entorno=entorno, estado_actual=cuerpo.estado_actual
    )


@router_entornos.get(
    "/{entorno}/drift",
    dependencies=[Depends(exige_permiso("metadata:read"))],
    summary="El desvío del entorno con el estado que consta",
    description=(
        "La misma comprobación tomando como estado actual el que el propio CRM "
        "tiene guardado. Sirve para mirarlo de un vistazo sin montar la carga; "
        "para comparar contra un estado externo está la versión POST."
    ),
)
def drift_rapido(entorno: str, db: DbDep, principal: AutenticadoDep) -> Any:
    from services.metadata.publicacion import esquema_actual

    estado = {
        "campos": {
            f"cuenta.{c['clave']}": {"tipo": c.get("tipo")}
            for c in esquema_actual(db, principal.tenant_id, "cuenta")
        }
    }
    return ent.medir_drift(db, principal.tenant_id, entorno=entorno, estado_actual=estado)


@router_entornos.post(
    "/{entorno}/volver-atras",
    dependencies=[Depends(exige_permiso("metadata:write"))],
    summary="Reaplicar el paquete anterior",
    description=(
        "**Reaplicar y no deshacer.** Deshacer cambio a cambio falla en cuanto hay "
        "dependencias —un campo que se creó y una vista que lo usa— y deja el "
        "entorno en un estado que no ha existido nunca. Volver al paquete anterior "
        "devuelve un estado que sí existió y que además estaba probado.\n\n"
        "Exige motivo: es lo que evita que el siguiente despliegue repita el mismo "
        "fallo."
    ),
)
def volver_atras(entorno: str, cuerpo: VolverIn, uow: UowDep, principal: AutenticadoDep) -> Any:
    return ent.volver_atras(uow, entorno=entorno, motivo=cuerpo.motivo, por=principal.id)


ROUTERS_ENTORNOS = [router_entornos]
