"""Superficie del corpus documental (RT-5).

Fábrica, como adjuntos y comentarios: cada servicio la monta declarando de qué
objetos suyos se pueden enlazar documentos. Así la misma superficie vale para
cuentas, oportunidades y casos sin copiarla, y un servicio no puede enlazar
documentos a objetos que no son suyos.

**Lo que sale del CRM y lo que sale del gestor**, que conviene no confundir:

  * La **lista** de documentos de un registro sale del CRM, sin llamar a nadie:
    una ficha que depende de un servicio externo para pintar una lista tarda lo
    que tarde ese servicio.
  * El **estado real** —versión publicada, si está obsoleto— y la **búsqueda**
    salen del gestor, con la identidad del usuario. Cachear un «aprobado» sería
    enseñar una versión vigente que ya no lo es, y alguien firmaría por ella.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query, status
from pydantic import BaseModel, Field

from crmcore.errors import ErrorValidacion
from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso


class EnlaceEntrada(BaseModel):
    documento_id: str = Field(max_length=120, description="Identificador en el gestor documental")
    titulo: str = Field("", max_length=300)
    tipo: str = Field("", max_length=60)
    rol: str = Field(
        "",
        max_length=80,
        description=(
            "Para qué está enlazado: «contrato marco», «certificado ISO». Es del "
            "CRM y no del gestor: el mismo documento puede ser el contrato de "
            "una cuenta y el anexo de otra."
        ),
    )
    sistema: str = Field("contecmind", max_length=60)


class OrganizacionEntrada(BaseModel):
    organizacion: str = Field(
        min_length=1,
        max_length=120,
        description="Identificador de la organización de este tenant en el gestor",
    )


def crear_router_documental(objetos: set[str]) -> APIRouter:
    """Monta el corpus documental para los objetos que el servicio posee."""
    router = APIRouter(prefix="/documentos", tags=["corpus documental"])

    def _validar(objeto_tipo: str) -> None:
        if objeto_tipo not in objetos:
            raise ErrorValidacion(
                f"Este servicio no enlaza documentos de «{objeto_tipo}»",
                error_code="documental.objeto_no_admitido",
                detalle={"admitidos": sorted(objetos)},
            )

    @router.get(
        "/estado",
        summary="Si hay corpus documental en este despliegue",
        description=(
            "Dice también **qué sigue funcionando sin él**: los adjuntos de los "
            "registros son otra cosa y no dependen del gestor. Sin esa línea, un "
            "estado que dice «no alcanzable» hace pensar que no se puede "
            "adjuntar nada, y sí se puede."
        ),
    )
    def estado_documental(_: AutenticadoDep) -> Any:
        from crmcore.documental import cliente

        return cliente.estado()

    @router.get(
        "/{objeto_tipo}/{objeto_id}",
        summary="Documentos enlazados a un registro",
        description=(
            "Sale del CRM, **sin llamar al gestor**: una ficha que depende de un "
            "servicio externo para pintar una lista tarda lo que tarde ese "
            "servicio. El estado real se pide al abrir el documento."
        ),
    )
    def listar(objeto_tipo: str, objeto_id: UUID, db: DbDep, _: AutenticadoDep) -> Any:
        from crmcore.documental import documentos_de

        _validar(objeto_tipo)
        return documentos_de(db, objeto_tipo=objeto_tipo, objeto_id=objeto_id)

    @router.post(
        "/{objeto_tipo}/{objeto_id}",
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(exige_permiso("documento:enlazar"))],
        summary="Enlazar un documento del corpus con un registro",
        description=(
            "Guarda **el enlace y el contexto**, nunca una copia del documento: "
            "duplicarlo crearía dos verdades que divergen en cuanto alguien "
            "publique una versión nueva allí, y la del CRM sería la vieja sin "
            "decirlo."
        ),
    )
    def crear_enlace(
        objeto_tipo: str,
        objeto_id: UUID,
        uow: UowDep,
        principal: AutenticadoDep,
        datos: EnlaceEntrada = Body(...),
    ) -> Any:
        from crmcore.documental import enlazar

        _validar(objeto_tipo)
        enlace = enlazar(
            uow.db,
            tenant_id=principal.tenant_id,
            objeto_tipo=objeto_tipo,
            objeto_id=objeto_id,
            por=principal.id,
            **datos.model_dump(),
        )
        return {"id": str(enlace.id), "documento_id": enlace.documento_id}

    @router.delete(
        "/{objeto_tipo}/{objeto_id}/{enlace_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[Depends(exige_permiso("documento:desenlazar"))],
        summary="Quitar el enlace (no borra el documento)",
        description=(
            "El CRM no es dueño del documento. Borrarlo allí desde aquí sería que "
            "un usuario del CRM destruyera el contrato que otro departamento "
            "guardó, sin pasar por las reglas de ese gestor.\n\n"
            "Un **bloqueo legal** sobre el registro impide quitar el enlace: un "
            "bloqueo que permite desenlazar la prueba y luego decir «aquí no "
            "consta» no es un bloqueo."
        ),
    )
    def borrar_enlace(objeto_tipo: str, objeto_id: UUID, enlace_id: UUID, uow: UowDep) -> None:
        from crmcore.documental import quitar_enlace

        _validar(objeto_tipo)
        quitar_enlace(uow.db, enlace_id, objeto_id=objeto_id)

    @router.get(
        "/buscar",
        summary="Buscar en el corpus, con la identidad de quien pregunta",
        description=(
            "La búsqueda la resuelve el gestor **con un token del usuario**, no "
            "con la credencial de la aplicación: así aplica sus propios permisos "
            "y cada uno ve lo que vería entrando al gestor. Buscar con la "
            "credencial le enseñaría el corpus entero del tenant."
        ),
    )
    def buscar_corpus(
        db: DbDep,
        principal: AutenticadoDep,
        q: str = Query(..., min_length=1, max_length=300),
        limite: int = Query(20, ge=1, le=100),
    ) -> Any:
        from crmcore.documental import cliente, organizacion_de

        organizacion = organizacion_de(db, principal.tenant_id)
        token = cliente.canjear_token(
            organizacion=organizacion,
            sujeto=str(principal.id),
            rol=cliente.rol_para(principal.permisos, principal.es_admin_plataforma),
        )
        return {"resultados": cliente.buscar(q, token_usuario=token.token, limite=limite)}

    @router.get(
        "/organizacion",
        summary="A qué organización del gestor se mapea este tenant",
        description=(
            "Sin mapeo no se llama al gestor, así que esto es lo primero que hay "
            "que mirar cuando el corpus «no aparece» en un tenant concreto."
        ),
    )
    def ver_organizacion(db: DbDep, principal: AutenticadoDep) -> Any:
        from sqlalchemy import select

        from crmcore.documental.enlaces import OrganizacionDocumental

        fila = db.execute(
            select(OrganizacionDocumental).where(
                OrganizacionDocumental.tenant_id == principal.tenant_id
            )
        ).scalar_one_or_none()
        if fila is None:
            return {"mapeada": False, "organizacion": "", "estado": "sin_mapear"}
        return {
            "mapeada": True,
            "organizacion": fila.organizacion,
            "estado": fila.estado,
            "ultimo_error": fila.ultimo_error,
        }

    @router.put(
        "/organizacion",
        dependencies=[Depends(exige_permiso("documento:admin"))],
        summary="Mapear este tenant a una organización del gestor",
        description=(
            "Se declara, no se deriva del identificador del tenant: derivarlo "
            "convertiría el aislamiento entre clientes en una convención, y una "
            "convención no para a nadie."
        ),
    )
    def fijar_organizacion(
        datos: OrganizacionEntrada, uow: UowDep, principal: AutenticadoDep
    ) -> Any:
        from crmcore.documental import mapear_organizacion

        fila = mapear_organizacion(
            uow.db, tenant_id=principal.tenant_id, organizacion=datos.organizacion
        )
        return {"mapeada": True, "organizacion": fila.organizacion, "estado": fila.estado}

    return router
