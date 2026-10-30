"""Router de comentarios reutilizable (CRM-06.02.01.01).

Fábrica, como la de adjuntos y por lo mismo: la conversación cuelga de
registros que viven en servicios distintos, y cada uno declara de cuáles de los
suyos se puede hablar. El tipo de objeto va **en la ruta** para que el gateway
sepa a qué servicio reenviar; sin él, dos servicios publicarían el mismo camino.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from crmcore.datos.comentarios import (
    Comentario,
    borrar,
    crear,
    de_registro,
    donde_me_mencionan,
    editar,
    resolver,
)
from crmcore.errors import ErrorValidacion, NoEncontrado
from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso


class EscribirComentario(BaseModel):
    cuerpo: str = Field(
        ...,
        description=(
            "Texto del comentario. Las menciones se escriben "
            "`@[Nombre](identificador-de-usuario)` y se extraen del propio texto: "
            "no se mandan aparte, para que editar el texto cambie también a quién "
            "se avisa."
        ),
        examples=["Hablado con @[Ana](0196e2b4-1111-7000-8000-000000000001), confirma el plazo"],
    )
    padre_id: UUID | None = Field(None, description="Para responder dentro de un hilo")
    interno: bool = Field(
        True,
        description=(
            "Un comentario interno no sale nunca hacia el cliente: ni al portal, "
            "ni en un correo automático, ni en una exportación."
        ),
    )


class EditarComentario(BaseModel):
    cuerpo: str


def crear_router_comentarios(objetos: set[str]) -> APIRouter:
    """Construye el router de comentarios para los objetos del servicio."""
    router = APIRouter(prefix="/comentarios", tags=["comentarios"])

    def _validar(objeto_tipo: str) -> None:
        if objeto_tipo not in objetos:
            raise ErrorValidacion(
                f"Este servicio no guarda comentarios de «{objeto_tipo}»",
                error_code="comentario.objeto_no_admitido",
                detalle={"admitidos": sorted(objetos)},
            )

    def _mio(db: Any, comentario_id: UUID, objeto_tipo: str) -> Comentario:
        _validar(objeto_tipo)
        fila = db.get(Comentario, comentario_id)
        if fila is None or fila.borrado_at is not None or fila.objeto_tipo != objeto_tipo:
            raise NoEncontrado("Comentario no encontrado", error_code="comentario.no_existe")
        return fila

    # Declarada ANTES que `/{objeto_tipo}/{objeto_id}`: FastAPI resuelve por
    # orden, y si fuera después, «mis-menciones» intentaría leerse como un
    # identificador de registro y devolvería un 422 en vez de la lista.
    #
    # Va acotada por tipo de objeto y no suelta, por dos motivos: el gateway
    # enruta los comentarios por ese segmento, y las menciones de una persona
    # están repartidas entre los servicios que guardan cada conversación. La
    # respuesta a «¿dónde me han mencionado, en todo?» es la bandeja de avisos
    # de identidad, que es la única que las ve todas.
    @router.get(
        "/{objeto_tipo}/mis-menciones",
        response_model=list[dict],
        summary="Dónde me han mencionado, en este tipo de registro",
    )
    def mis_menciones(
        objeto_tipo: str,
        db: DbDep,
        principal: AutenticadoDep,
        limite: int = Query(50, ge=1, le=200),
    ) -> Any:
        _validar(objeto_tipo)
        return [
            m
            for m in donde_me_mencionan(
                db, tenant_id=principal.tenant_id, usuario_id=principal.id, limite=limite
            )
            if m["objeto_tipo"] == objeto_tipo
        ]

    @router.get(
        "/mis-menciones",
        response_model=list[dict],
        summary="Dónde me han mencionado, en cualquier registro de este servicio",
        description=(
            "La de arriba filtra por un tipo de registro, y eso obliga a quien "
            "quiera ver sus menciones a preguntar una vez por tipo y por "
            "servicio. `donde_me_mencionan` ya las busca **todas** y la ruta "
            "tiraba el resto: una mención que nadie ve es una mención que no "
            "existe, y es justo lo que pasaba."
        ),
    )
    def todas_mis_menciones(
        db: DbDep,
        principal: AutenticadoDep,
        limite: int = Query(50, ge=1, le=200),
    ) -> Any:
        return donde_me_mencionan(
            db, tenant_id=principal.tenant_id, usuario_id=principal.id, limite=limite
        )

    @router.post(
        "/{objeto_tipo}/{objeto_id}",
        response_model=dict,
        status_code=status.HTTP_201_CREATED,
        summary="Comentar un registro",
        dependencies=[Depends(exige_permiso("comentario:escribir"))],
        description=(
            "Mencionar a alguien **lo suscribe** al registro: nombrar a un "
            "compañero para que se entere y que luego no se entere de la "
            "respuesta sería absurdo. Desde ahí puede silenciarlo como "
            "cualquier otro seguimiento."
        ),
    )
    def comentar(
        objeto_tipo: str,
        objeto_id: UUID,
        datos: EscribirComentario,
        uow: UowDep,
        principal: AutenticadoDep,
    ) -> Any:
        _validar(objeto_tipo)
        comentario = crear(
            uow.db,
            tenant_id=principal.tenant_id,
            objeto_tipo=objeto_tipo,
            objeto_id=objeto_id,
            cuerpo=datos.cuerpo,
            autor_id=principal.id,
            padre_id=datos.padre_id,
            interno=datos.interno,
        )
        # El evento lleva las menciones y el autor. Quien avisa es el servicio
        # de identidad, consumiéndolo: aquí no se puede escribir en su esquema,
        # y que no se pueda es lo que garantiza la propiedad del dato.
        uow.emitir(
            "record.commented",
            subject=(objeto_tipo, objeto_id),
            data={
                "comentario_id": str(comentario.id),
                "objeto_tipo": objeto_tipo,
                "objeto_id": str(objeto_id),
                "hilo_id": str(comentario.hilo_id),
                "autor_id": str(principal.id) if principal.id else "",
                "actor_id": str(principal.id) if principal.id else "",
                "menciones": comentario.menciones,
                "extracto": comentario.cuerpo[:200],
            },
            # El hecho es «este comentario existe»; recibirlo dos veces no son
            # dos comentarios.
            dedup_key=f"record.commented:{comentario.id}",
        )
        return {
            "id": str(comentario.id),
            "hilo_id": str(comentario.hilo_id),
            "menciones": comentario.menciones,
        }

    @router.get(
        "/{objeto_tipo}/{objeto_id}",
        response_model=list[dict],
        summary="La conversación de un registro",
        description=(
            "Agrupada por hilos, no como lista plana: una conversación leída "
            "como mensajes sueltos ordenados por fecha no se entiende en cuanto "
            "hay dos temas a la vez, que es siempre."
        ),
    )
    def conversacion(
        objeto_tipo: str,
        objeto_id: UUID,
        db: DbDep,
        principal: AutenticadoDep,
        incluir_internos: bool = Query(True),
        solo_sin_resolver: bool = Query(False),
        limite: int = Query(200, ge=1, le=1000),
    ) -> Any:
        _validar(objeto_tipo)
        return de_registro(
            db,
            tenant_id=principal.tenant_id,
            objeto_tipo=objeto_tipo,
            objeto_id=objeto_id,
            incluir_internos=incluir_internos,
            solo_sin_resolver=solo_sin_resolver,
            limite=limite,
        )

    @router.patch(
        "/{objeto_tipo}/{comentario_id}",
        response_model=dict,
        summary="Editar un comentario propio",
        dependencies=[Depends(exige_permiso("comentario:escribir"))],
        description=(
            "Queda marcado como editado, y no es estética: alguien contestó a "
            "lo que ponía antes, y sin la marca esa respuesta parece no venir "
            "a cuento."
        ),
    )
    def editar_comentario(
        objeto_tipo: str,
        comentario_id: UUID,
        datos: EditarComentario,
        uow: UowDep,
        principal: AutenticadoDep,
    ) -> Any:
        _mio(uow.db, comentario_id, objeto_tipo)
        comentario = editar(uow.db, comentario_id, cuerpo=datos.cuerpo, por=principal.id)
        return {
            "id": str(comentario.id),
            "menciones": comentario.menciones,
            "ediciones": comentario.ediciones,
        }

    @router.delete(
        "/{objeto_tipo}/{comentario_id}",
        response_model=dict,
        summary="Retirar un comentario",
        dependencies=[Depends(exige_permiso("comentario:borrar"))],
        description=(
            "Se marca, no se quita: borrarlo de verdad dejaría las respuestas "
            "colgando de la nada. Quien lea el hilo ve que hubo algo y que se "
            "retiró."
        ),
    )
    def borrar_comentario(
        objeto_tipo: str, comentario_id: UUID, uow: UowDep, principal: AutenticadoDep
    ) -> Any:
        _mio(uow.db, comentario_id, objeto_tipo)
        borrar(uow.db, comentario_id, por=principal.id)
        return {"borrado": True}

    @router.post(
        "/{objeto_tipo}/hilos/{hilo_id}/resolver",
        response_model=dict,
        summary="Dar un hilo por resuelto",
        dependencies=[Depends(exige_permiso("comentario:resolver"))],
    )
    def resolver_hilo(
        objeto_tipo: str,
        hilo_id: UUID,
        uow: UowDep,
        principal: AutenticadoDep,
        resuelto: bool = Query(True),
    ) -> Any:
        _validar(objeto_tipo)
        raiz = resolver(uow.db, hilo_id, por=principal.id, resuelto=resuelto)
        return {"hilo_id": str(raiz.id), "resuelto": raiz.resuelto_at is not None}

    return router
