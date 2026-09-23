"""La papelera de cada servicio, con su restauración (CRM-00.06.02.04).

Existe porque el borrado lógico se extendió a los catálogos de configuración
—plantillas de correo, canales, segmentos, activos, partners— y la papelera es
**de cada servicio**: cada uno guarda la suya en su propio esquema, que es lo
que hace que un servicio no tenga que leer las tablas de otro.

Sin esto, borrar una plantilla la mandaba a una papelera de marketing que no
tenía ninguna pantalla: el registro desaparecía del listado y no aparecía en
ningún otro sitio. Recuperable en la base y perdido para quien lo necesitaba,
que es la peor forma de tener una papelera.

Se monta sola en `crear_servicio`, como la restauración selectiva, y por el
mismo motivo: si dependiera de que cada servicio se acuerde, faltaría
precisamente en el que guarde lo que alguien acabe borrando.

Cuelga de `/{servicio}/papelera` porque los doce publican la misma ruta y sin
el segmento del servicio el gateway no sabría a cuál mandar la petición.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso


class Purga(BaseModel):
    """El motivo de una purga, que es irreversible.

    Con motivo obligatorio y por cuerpo: destruir definitivamente los datos de
    un cliente tiene que poder demostrarse cuándo y por qué se hizo, y un
    motivo en la URL acaba en el log de acceso.
    """

    motivo: str = Field(..., min_length=10, max_length=1000)


def _modelos_del_servicio() -> dict[str, type]:
    """Nombre de objeto → modelo, para poder restaurar.

    Van los dos juegos de claves: los nombres de objeto declarados al montar el
    borrado —que es como los guarda la entrada de papelera— y los nombres de
    tabla, por si alguien borró declarando la tabla. Sobran claves y no falta
    ninguna, que es el lado correcto por el que equivocarse: una clave de más
    no hace nada, una de menos deja un registro sin poder restaurar.
    """
    from crmcore.datos.papelera import objetos_registrados
    from crmcore.db.base import Base

    salida: dict[str, type] = {}
    for mapeador in Base.registry.mappers:
        modelo = mapeador.class_
        tabla = getattr(modelo, "__table__", None)
        if tabla is not None and "deleted_at" in tabla.columns:
            salida[tabla.name] = modelo
    salida.update(objetos_registrados())
    return salida


def crear_router_papelera(servicio: str) -> APIRouter:
    from crmcore.datos.papelera import EntradaPapelera, purgar, restaurar

    router = APIRouter(prefix=f"/{servicio}/papelera", tags=["papelera"])

    @router.get(
        "",
        response_model=list[dict],
        dependencies=[Depends(exige_permiso("datos:restaurar"))],
        summary=f"Qué hay en la papelera de «{servicio}»",
        description=(
            "Con los días que faltan para la purga, que es el dato que importa "
            "a quien está buscando algo que borró sin querer."
        ),
    )
    def listar(
        db: DbDep,
        principal: AutenticadoDep,
        objeto: str = Query("", description="Filtra por tipo de objeto"),
        limite: int = Query(50, ge=1, le=200),
    ) -> Any:
        consulta = select(EntradaPapelera).where(
            EntradaPapelera.tenant_id == principal.tenant_id,
            EntradaPapelera.restaurado_at.is_(None),
            EntradaPapelera.purgado_at.is_(None),
        )
        if objeto:
            consulta = consulta.where(EntradaPapelera.objeto == objeto)
        filas = (
            db.execute(consulta.order_by(EntradaPapelera.borrado_at.desc()).limit(limite))
            .scalars()
            .all()
        )
        ahora = datetime.now(timezone.utc)
        return [
            {
                "id": str(f.id),
                "servicio": servicio,
                "objeto": f.objeto,
                "registro_id": str(f.registro_id),
                "etiqueta": f.etiqueta,
                "borrado_at": f.borrado_at.isoformat(),
                "purgable_at": f.purgable_at.isoformat(),
                "dias_para_purga": (f.purgable_at - ahora).days,
                "en_cascada": sum(len(v) for v in (f.cascada or {}).values()),
            }
            for f in filas
        ]

    @router.post(
        "/{entrada_id}/restaurar",
        response_model=dict,
        dependencies=[Depends(exige_permiso("datos:restaurar"))],
        summary="Devolver un registro a la vida",
        description=(
            "En cascada: se restaura también lo que se borró con él. Devolver "
            "solo la cabecera dejaría una ficha viva con la mitad de su "
            "historia perdida, que parece completa y no lo está."
        ),
    )
    def restaurar_entrada(entrada_id: UUID, uow: UowDep, principal: AutenticadoDep) -> Any:
        entrada = restaurar(uow.db, entrada_id, modelos=_modelos_del_servicio(), por=principal.id)
        return {
            "id": str(entrada.id),
            "objeto": entrada.objeto,
            "registro_id": str(entrada.registro_id),
            "restaurado": True,
        }

    @router.post(
        "/purgar",
        response_model=dict,
        dependencies=[Depends(exige_permiso("retencion:purgar"))],
        summary="Destruir definitivamente lo que ya cumplió su plazo",
        description=(
            "Irreversible, y solo alcanza a lo que pasó el plazo de retención. "
            "Lo que tiene un bloqueo legal no se purga aunque le toque."
        ),
    )
    def purgar_vencidos(datos: Purga, uow: UowDep, principal: AutenticadoDep) -> Any:
        return {
            "purgados": purgar(
                uow.db,
                tenant_id=principal.tenant_id,
                modelos=_modelos_del_servicio(),
                motivo=datos.motivo,
            )
        }

    return router
