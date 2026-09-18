"""Router de adjuntos reutilizable por cualquier servicio (CRM-06.01.01.05).

Es una **fábrica**, no un router suelto: cada servicio lo monta declarando de
qué objetos suyos se pueden colgar ficheros. Así la misma superficie HTTP
—subir, versionar, listar, descargar, enlace firmado— vale para cuentas,
oportunidades o casos sin copiarla, y a la vez un servicio no puede exponer por
accidente adjuntos de objetos que no son suyos.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select

from crmcore.datos.adjuntos import (
    Adjunto,
    borrar,
    firmar_enlace,
    leer,
    subir,
    verificar_enlace,
)
from crmcore.errors import ErrorValidacion, NoEncontrado
from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso


class AdjuntoOut(BaseModel):
    id: UUID
    objeto_tipo: str
    objeto_id: UUID
    nombre: str
    extension: str
    tipo_mime: str
    tamano: int
    sha256: str
    version: int
    documento_id: UUID
    es_actual: bool
    descripcion: str
    etiquetas: list[Any]
    analisis: str

    model_config = {"from_attributes": True}


def crear_router_adjuntos(objetos: set[str]) -> APIRouter:
    """Construye el router de adjuntos para los objetos que el servicio posee.

    `objetos` es la lista blanca de `objeto_tipo` admitidos. Sin ella, cualquier
    servicio podría escribir adjuntos con el tipo de un objeto ajeno y dejarlos
    huérfanos en su propio esquema, invisibles desde el servicio que sí es
    dueño del registro.

    **El tipo de objeto va en la ruta**, no solo en el cuerpo. Sin él, `party` y
    `sales` publicarían exactamente el mismo camino (`/adjuntos`) y el gateway
    no podría decidir a cuál reenviar: enrutaría todo a uno, y los adjuntos de
    oportunidad acabarían pidiéndose al servicio que no los tiene. Con el tipo
    delante, la ruta identifica al dueño sin ambigüedad.
    """
    router = APIRouter(prefix="/adjuntos", tags=["adjuntos"])

    def _traer(db: Any, adjunto_id: UUID, objeto_tipo: str) -> Adjunto:
        """Carga el adjunto comprobando que es del tipo que dice la ruta.

        Sin esta comprobación el segmento de la ruta sería decorativo: se podría
        pedir el adjunto de un contacto por el camino de una cuenta, y el día que
        los permisos se afinen por tipo de objeto —que es hacia donde va— ese
        camino sería la forma de saltárselos.
        """
        _validar_objeto(objeto_tipo)
        fila = db.get(Adjunto, adjunto_id)
        if fila is None or fila.deleted_at is not None or fila.objeto_tipo != objeto_tipo:
            raise NoEncontrado("Adjunto no encontrado", error_code="adjunto.no_existe")
        return fila

    def _validar_objeto(objeto_tipo: str) -> None:
        if objeto_tipo not in objetos:
            raise ErrorValidacion(
                f"Este servicio no guarda adjuntos de «{objeto_tipo}»",
                error_code="adjunto.objeto_no_admitido",
                detalle={"admitidos": sorted(objetos)},
            )

    @router.post(
        "/{objeto_tipo}",
        response_model=AdjuntoOut,
        status_code=status.HTTP_201_CREATED,
        summary="Subir un fichero",
        dependencies=[Depends(exige_permiso("adjunto:subir"))],
        description=(
            "Con `documento_id` crea una **versión nueva** del documento y deja "
            "la anterior accesible. Sin él, un documento nuevo. Dos ficheros "
            "con el mismo contenido comparten los bytes en el almacén, pero "
            "nunca entre tenants distintos."
        ),
    )
    async def subir_adjunto(
        objeto_tipo: str,
        uow: UowDep,
        principal: AutenticadoDep,
        fichero: UploadFile = File(...),
        objeto_id: UUID = Form(...),
        descripcion: str = Form(""),
        documento_id: UUID | None = Form(None),
    ) -> Any:
        _validar_objeto(objeto_tipo)
        # Se lee entero en memoria porque el tope configurado (25 MB por
        # defecto) lo hace asumible y porque el hash de deduplicación necesita
        # todos los bytes. Para ficheros grandes de verdad está `guardar_fichero`
        # del almacén, que no los carga; el día que haga falta, el cambio es
        # aquí y no en el modelo.
        datos = await fichero.read()
        return subir(
            uow.db,
            tenant_id=principal.tenant_id,
            objeto_tipo=objeto_tipo,
            objeto_id=objeto_id,
            nombre=fichero.filename or "sin-nombre",
            datos=datos,
            tipo_mime=fichero.content_type or "",
            descripcion=descripcion,
            usuario_id=principal.id,
            documento_id=documento_id,
        )

    @router.get(
        "/{objeto_tipo}", response_model=list[AdjuntoOut], summary="Adjuntos de un registro"
    )
    def listar(
        objeto_tipo: str,
        db: DbDep,
        principal: AutenticadoDep,
        objeto_id: UUID = Query(...),
        todas_las_versiones: bool = Query(False),
    ) -> Any:
        _validar_objeto(objeto_tipo)
        consulta = select(Adjunto).where(
            Adjunto.objeto_tipo == objeto_tipo,
            Adjunto.objeto_id == objeto_id,
            Adjunto.deleted_at.is_(None),
        )
        if not todas_las_versiones:
            consulta = consulta.where(Adjunto.es_actual.is_(True))
        return list(db.execute(consulta.order_by(Adjunto.created_at.desc())).scalars().all())

    @router.get(
        "/{objeto_tipo}/{adjunto_id}/versiones",
        response_model=list[AdjuntoOut],
        summary="Versiones del documento",
    )
    def versiones(objeto_tipo: str, adjunto_id: UUID, db: DbDep, _: AutenticadoDep) -> Any:
        fila = _traer(db, adjunto_id, objeto_tipo)
        return list(
            db.execute(
                select(Adjunto)
                .where(Adjunto.documento_id == fila.documento_id)
                .order_by(Adjunto.version.desc())
            )
            .scalars()
            .all()
        )

    @router.get(
        "/{objeto_tipo}/{adjunto_id}/contenido",
        summary="Descargar el fichero",
        response_class=Response,
    )
    def descargar(
        objeto_tipo: str,
        adjunto_id: UUID,
        db: DbDep,
        principal: AutenticadoDep,
        peticion: Request,
    ) -> Any:
        fila = _traer(db, adjunto_id, objeto_tipo)
        datos = leer(
            db,
            adjunto_id,
            usuario_id=principal.id,
            ip=peticion.client.host if peticion.client else "",
        )
        return _respuesta(fila, datos)

    @router.get(
        "/{objeto_tipo}/enlace/{token}",
        summary="Descargar con un enlace firmado",
        response_class=Response,
        description=(
            "No exige cabecera de autorización: la lleva el token. Es lo que "
            "permite un `<img src>` o un enlace en un correo. Caduca pronto y "
            "va firmado con el usuario dentro, así que reenviarlo no borra el "
            "rastro de quién lo pidió."
        ),
    )
    def descargar_con_enlace(objeto_tipo: str, token: str, db: DbDep, peticion: Request) -> Any:
        adjunto_id, usuario_id = verificar_enlace(token)
        fila = _traer(db, adjunto_id, objeto_tipo)
        datos = leer(
            db,
            adjunto_id,
            usuario_id=usuario_id,
            ip=peticion.client.host if peticion.client else "",
        )
        return _respuesta(fila, datos)

    @router.post(
        "/{objeto_tipo}/{adjunto_id}/enlace",
        response_model=dict,
        summary="Generar un enlace firmado",
        dependencies=[Depends(exige_permiso("adjunto:enlace"))],
    )
    def generar_enlace(
        objeto_tipo: str, adjunto_id: UUID, db: DbDep, principal: AutenticadoDep
    ) -> Any:
        _traer(db, adjunto_id, objeto_tipo)
        from crmcore.runtime import settings as rt

        return {
            "token": firmar_enlace(adjunto_id, usuario_id=principal.id, db=db),
            "caduca_en_s": int(rt.efectivo("adjunto_enlace_ttl_s", db) or 300),
        }

    @router.delete(
        "/{objeto_tipo}/{adjunto_id}",
        response_model=AdjuntoOut,
        summary="Borrar un adjunto",
        dependencies=[Depends(exige_permiso("adjunto:borrar"))],
    )
    def borrar_adjunto(
        objeto_tipo: str, adjunto_id: UUID, uow: UowDep, principal: AutenticadoDep
    ) -> Any:
        _traer(uow.db, adjunto_id, objeto_tipo)
        return borrar(uow.db, adjunto_id, usuario_id=principal.id)

    return router


def _respuesta(fila: Adjunto, datos: bytes) -> Response:
    """Devuelve el fichero como descarga.

    `Content-Disposition: attachment` y `X-Content-Type-Options: nosniff`
    **siempre**: servir en línea un fichero subido por un usuario es servir su
    HTML o su SVG desde el dominio del CRM, con la sesión de quien lo abre. La
    comodidad de previsualizar en el navegador no compensa un XSS con sesión
    válida.
    """
    nombre = fila.nombre.replace('"', "").replace("\n", " ")
    return Response(
        content=datos,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{nombre}"',
            "X-Content-Type-Options": "nosniff",
            "Content-Length": str(len(datos)),
        },
    )
