"""Router de adjuntos reutilizable por cualquier servicio (CRM-06.01.01.05).

Es una **fábrica**, no un router suelto: cada servicio lo monta declarando de
qué objetos suyos se pueden colgar ficheros. Así la misma superficie HTTP
—subir, versionar, listar, descargar, enlace firmado— vale para cuentas,
oportunidades o casos sin copiarla, y a la vez un servicio no puede exponer por
accidente adjuntos de objetos que no son suyos.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select

from crmcore.datos.adjuntos import (
    Adjunto,
    arbol_carpetas,
    borrar,
    borrar_carpeta,
    crear_carpeta,
    firmar_enlace,
    leer,
    mover_adjunto,
    mover_carpeta,
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
    # Si se analizó y qué salió. Estaban en la tabla y no salían, así que la
    # pantalla enseñaba un adjunto sin decir si está comprobado: un fichero
    # sin analizar y uno limpio se veían igual, que es la peor de las dos
    # lecturas posibles.
    analisis_at: datetime | None = None
    analisis_detalle: str | None = None
    descripcion: str
    etiquetas: list[Any]
    analisis: str
    carpeta_id: UUID | None
    externo_sistema: str

    model_config = {"from_attributes": True}


class CarpetaEntrada(BaseModel):
    nombre: str
    padre_id: UUID | None = None


class MoverEntrada(BaseModel):
    # `None` explícito significa «a la raíz», que es una orden distinta de «no
    # lo muevas». Por eso el campo no se omite: se manda con valor nulo.
    padre_id: UUID | None = None


class MoverAdjuntoEntrada(BaseModel):
    carpeta_id: UUID | None = None


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
        carpeta_id: UUID | None = Form(None),
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
            carpeta_id=carpeta_id,
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
        carpeta_id: UUID | None = Query(None, description="Solo lo que hay en esa carpeta"),
        en_raiz: bool = Query(False, description="Solo lo que no está en ninguna carpeta"),
    ) -> Any:
        _validar_objeto(objeto_tipo)
        consulta = select(Adjunto).where(
            Adjunto.objeto_tipo == objeto_tipo,
            Adjunto.objeto_id == objeto_id,
            Adjunto.deleted_at.is_(None),
        )
        if not todas_las_versiones:
            consulta = consulta.where(Adjunto.es_actual.is_(True))
        # Sin filtro se devuelve el expediente entero, carpetas incluidas: es lo
        # que espera quien busca «todos los documentos de esta cuenta» y no
        # quiere recorrer el árbol para encontrarlos.
        if carpeta_id is not None:
            consulta = consulta.where(Adjunto.carpeta_id == carpeta_id)
        elif en_raiz:
            consulta = consulta.where(Adjunto.carpeta_id.is_(None))
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

    # ── Carpetas ──────────────────────────────────────────────────────────
    # Van bajo `/carpetas/...` y no bajo `/{objeto_tipo}/carpetas` porque
    # `{objeto_tipo}` se come cualquier primer segmento: un camino literal
    # detrás de él nunca se distinguiría del identificador de un adjunto.

    @router.get(
        "/carpetas/{objeto_tipo}",
        response_model=list[dict],
        summary="Árbol de carpetas del expediente",
        description=(
            "Plano y ordenado por ruta, con el nivel de cada una. Quien pinta "
            "el árbol lo anida en un bucle; devolverlo anidado obligaría a "
            "recorrerlo entero para encontrar una carpeta concreta."
        ),
    )
    def listar_carpetas(
        objeto_tipo: str, db: DbDep, _: AutenticadoDep, objeto_id: UUID = Query(...)
    ) -> Any:
        _validar_objeto(objeto_tipo)
        return arbol_carpetas(db, objeto_tipo=objeto_tipo, objeto_id=objeto_id)

    @router.post(
        "/carpetas/{objeto_tipo}",
        response_model=dict,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(exige_permiso("adjunto:organizar"))],
        summary="Crear una carpeta en el expediente",
    )
    def crear_carpeta_ruta(
        objeto_tipo: str,
        datos: CarpetaEntrada,
        uow: UowDep,
        principal: AutenticadoDep,
        objeto_id: UUID = Query(...),
    ) -> Any:
        _validar_objeto(objeto_tipo)
        carpeta = crear_carpeta(
            uow.db,
            tenant_id=principal.tenant_id,
            objeto_tipo=objeto_tipo,
            objeto_id=objeto_id,
            nombre=datos.nombre,
            padre_id=datos.padre_id,
        )
        return _carpeta_out(carpeta)

    @router.patch(
        "/carpetas/{objeto_tipo}/{carpeta_id}",
        response_model=dict,
        dependencies=[Depends(exige_permiso("adjunto:organizar"))],
        summary="Mover una carpeta",
        description=(
            "Recalcula la ruta de toda la rama. `padre_id: null` la lleva a la "
            "raíz del expediente."
        ),
    )
    def mover_carpeta_ruta(
        objeto_tipo: str,
        carpeta_id: UUID,
        datos: MoverEntrada,
        uow: UowDep,
        _: AutenticadoDep,
    ) -> Any:
        _validar_objeto(objeto_tipo)
        _exigir_carpeta_del_tipo(uow.db, carpeta_id, objeto_tipo)
        return _carpeta_out(mover_carpeta(uow.db, carpeta_id, nuevo_padre_id=datos.padre_id))

    @router.delete(
        "/carpetas/{objeto_tipo}/{carpeta_id}",
        response_model=dict,
        dependencies=[Depends(exige_permiso("adjunto:organizar"))],
        summary="Borrar una carpeta (su contenido se mueve, no se borra)",
        description=(
            "Lo de dentro sube a la raíz, o a `mover_a` si se indica, y se "
            "devuelve cuántos documentos se movieron. Borrar en cascada es la "
            "operación que más veces se lamenta: quien borra una carpeta está "
            "ordenando, no destruyendo."
        ),
    )
    def borrar_carpeta_ruta(
        objeto_tipo: str,
        carpeta_id: UUID,
        uow: UowDep,
        _: AutenticadoDep,
        mover_a: UUID | None = Query(None),
    ) -> Any:
        _validar_objeto(objeto_tipo)
        _exigir_carpeta_del_tipo(uow.db, carpeta_id, objeto_tipo)
        return {"movidos": borrar_carpeta(uow.db, carpeta_id, mover_a=mover_a)}

    @router.patch(
        "/{objeto_tipo}/{adjunto_id}/carpeta",
        response_model=AdjuntoOut,
        dependencies=[Depends(exige_permiso("adjunto:organizar"))],
        summary="Archivar un adjunto en una carpeta",
        description=(
            "Mueve **todas las versiones** del documento: una carpeta es dónde "
            "está el documento, no dónde está una de sus versiones."
        ),
    )
    def mover_adjunto_ruta(
        objeto_tipo: str,
        adjunto_id: UUID,
        datos: MoverAdjuntoEntrada,
        uow: UowDep,
        _: AutenticadoDep,
    ) -> Any:
        _traer(uow.db, adjunto_id, objeto_tipo)
        return mover_adjunto(uow.db, adjunto_id, carpeta_id=datos.carpeta_id)

    def _exigir_carpeta_del_tipo(db: Any, carpeta_id: UUID, objeto_tipo: str) -> None:
        """Igual que `_traer` para los adjuntos: el segmento de la ruta manda.

        Sin esto se podría tocar la carpeta de una oportunidad entrando por el
        camino de las cuentas, y el servicio dueño del registro no se enteraría.
        """
        from crmcore.datos.adjuntos import CarpetaDocumental

        fila = db.get(CarpetaDocumental, carpeta_id)
        if fila is None or fila.objeto_tipo != objeto_tipo:
            raise NoEncontrado("La carpeta no existe", error_code="carpeta.no_existe")

    return router


def _carpeta_out(carpeta: Any) -> dict[str, Any]:
    return {
        "id": str(carpeta.id),
        "nombre": carpeta.nombre,
        "padre_id": str(carpeta.padre_id) if carpeta.padre_id else None,
        "ruta": carpeta.ruta,
        "nivel": carpeta.ruta.count("/"),
    }


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
