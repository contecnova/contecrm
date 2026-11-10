"""API del código del tenant, con datos (CRM-00.04.02.01, .04, .05, .06, .07).

Las rutas de cálculo de `api.py` (`/extensiones/limites`, `/versiones`,
`/firma`, `/observabilidad`…) siguen para quien integre con sus propios datos;
éstas trabajan con las extensiones guardadas.

El orden en que se montan importa: los listados con nombre —`/firmantes`,
`/endpoints`— van antes que la ficha `/{extension_id}`, o la ficha se los
tragaría.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from crmcore.errors import ErrorDependencia
from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from crmcore.http.listados import montar_ficha, montar_listado
from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from services.automation import codigo_tenant as ct
from services.automation import motor_js

router_codigo = APIRouter(prefix="/extensiones", tags=["código del tenant"])
router_propios = APIRouter(prefix="/propios", tags=["endpoints propios"])


# ── Firmantes de confianza ────────────────────────────────────────────────


class FirmanteIn(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=200)
    clave_publica: str = Field(
        ..., min_length=1, description="Clave pública Ed25519: 32 bytes en base64"
    )


montar_listado(
    router_codigo,
    modelo=ct.FirmanteExtension,
    objeto="firmante_extension",
    ruta="/firmantes",
    permiso="automatizacion:read",
    permiso_escribir="automatizacion:write",
    nombre="Firmantes de confianza",
    ficha=False,
)


@router_codigo.post(
    "/firmantes",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("automatizacion:write"))],
    summary="Dar por bueno a un firmante de extensiones",
    description=(
        "Con su clave pública Ed25519. Una extensión de terceros sólo se puede "
        "publicar firmada por alguien de esta lista, y aun así la revisa una persona."
    ),
)
def alta_firmante(datos: FirmanteIn, uow: UowDep) -> Any:
    fila = ct.alta_firmante(uow, nombre=datos.nombre, clave_publica=datos.clave_publica)
    return {"id": str(fila.id), "nombre": fila.nombre, "huella_clave": fila.huella_clave}


montar_ficha(
    router_codigo,
    modelo=ct.FirmanteExtension,
    objeto="firmante_extension",
    ruta="/firmantes",
    parametro="firmante_id",
    permiso_leer="automatizacion:read",
    permiso_escribir="automatizacion:write",
    nombre="Firmantes de confianza",
    editable=frozenset({"nombre", "activo"}),
)


# ── Endpoints propios ─────────────────────────────────────────────────────


class EndpointIn(BaseModel):
    metodo: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    ruta: str = Field(
        ..., min_length=1, description="Tramos en minúsculas: se sirve en /api/v1/propios/<ruta>"
    )
    extension_id: UUID
    permiso: str = Field(
        "", description="El permiso que tiene que tener quien llama; vacío: basta con entrar"
    )
    descripcion: str = ""


montar_listado(
    router_codigo,
    modelo=ct.EndpointPropio,
    objeto="endpoint_propio",
    ruta="/endpoints",
    permiso="automatizacion:read",
    permiso_escribir="automatizacion:write",
    nombre="Endpoints propios",
    ficha=False,
)


@router_codigo.post(
    "/endpoints",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("automatizacion:write"))],
    summary="Publicar un endpoint propio",
    description=(
        "Un método y una ruta del tenant, servidos en `/api/v1/propios/<ruta>` por el "
        "mismo gateway, con la misma autenticación y el permiso que se pida aquí. "
        "Ejecutan la versión activa de la extensión con lo que llega."
    ),
)
def crear_endpoint(datos: EndpointIn, uow: UowDep) -> Any:
    fila = ct.crear_endpoint(
        uow,
        metodo=datos.metodo,
        ruta=datos.ruta,
        extension_id=datos.extension_id,
        permiso=datos.permiso,
        descripcion=datos.descripcion,
    )
    return {"id": str(fila.id), "metodo": fila.metodo, "ruta": fila.ruta}


montar_ficha(
    router_codigo,
    modelo=ct.EndpointPropio,
    objeto="endpoint_propio",
    ruta="/endpoints",
    parametro="endpoint_id",
    permiso_leer="automatizacion:read",
    permiso_escribir="automatizacion:write",
    nombre="Endpoints propios",
    editable=frozenset({"permiso", "descripcion", "activo"}),
)


# ── Extensiones ───────────────────────────────────────────────────────────


class ExtensionIn(BaseModel):
    clave: str = Field(..., min_length=2, max_length=80)
    nombre: str = Field(..., min_length=1, max_length=200)
    descripcion: str = ""
    origen: Literal["propia", "tercero"] = Field(
        "propia", description="«tercero» exige firma y revisión antes de activarse"
    )
    permisos: list[str] = Field(
        default_factory=list,
        description="Con qué permisos se hacen las acciones que devuelva; nunca más que los tuyos",
    )


class VersionIn(BaseModel):
    codigo: str = Field(..., min_length=1, description="JavaScript con `function main(entrada)`")
    notas: str = ""
    firmante_id: UUID | None = Field(None, description="Sólo las de terceros")
    firma: str = Field("", description="Firma Ed25519 de la huella SHA-256 del código, en base64")


class RevisionIn(BaseModel):
    aprobar: bool
    nota: str = Field(..., min_length=1, description="Qué se ha mirado")


class ActivarIn(BaseModel):
    version: int = Field(..., ge=1)
    motivo: str = ""


class VolverAtrasIn(BaseModel):
    motivo: str = Field(..., min_length=1, description="Qué falló en la versión que se quita")


class VersionOut(BaseModel):
    # Lo que la lista enseña como nombre de la fila: sin él salía la huella.
    titulo: str
    version: int
    estado: str
    activa: bool
    huella: str
    motor_version: str
    notas: str | None = None
    publicada_por: str | None = None
    publicada_el: str | None = None
    revisada_por: str | None = None
    nota_revision: str | None = None


class ListaVersiones(BaseModel):
    items: list[VersionOut]


class EjecucionOut(BaseModel):
    # Qué pasó, en una línea: sin él la fila se llamaba por su identificador.
    titulo: str
    id: str
    cuando: str | None = None
    version: int
    origen: str
    ok: bool
    cortada_por: str | None = None
    ms: int
    combustible: int
    error: str | None = None
    logs: list[Any] = Field(default_factory=list)
    acciones: int
    acciones_fallidas: int
    coste: float


class ListaEjecuciones(BaseModel):
    items: list[EjecucionOut]


class ProbarIn(BaseModel):
    entrada: dict[str, Any] = Field(default_factory=dict)
    version: int | None = Field(None, ge=1, description="Vacío: la activa")


@router_codigo.get(
    "/motor",
    dependencies=[Depends(exige_permiso("automatizacion:read"))],
    summary="El motor que ejecuta las extensiones, y sus topes",
)
def motor(principal: AutenticadoDep) -> Any:
    limites = motor_js.Limites.de_ajustes()
    estado = motor_js.estado_del_motor()
    # La frase que lo lee, para la pestaña de Extensiones: sin ella la medida
    # es un `listo: true` y seis números sin decir qué son.
    que_significa = (
        f"Motor JavaScript {estado['version']}, listo y con la huella que se fijó. "
        "Cada ejecución se corta en cuanto pasa uno de estos topes."
        if estado.get("listo")
        else str(estado.get("porque") or "")
    )
    return {**estado, "limites": limites.__dict__, "que_significa": que_significa}


@router_codigo.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("automatizacion:write"))],
    summary="Dar de alta una extensión",
    description=(
        "Una función del tenant. Se publica después su código, versión a versión, y "
        "se activa la que tiene que ejecutarse."
    ),
)
def crear_extension(datos: ExtensionIn, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = ct.crear_extension(
        uow,
        clave=datos.clave,
        nombre=datos.nombre,
        descripcion=datos.descripcion,
        origen=datos.origen,
        permisos=datos.permisos,
        por=principal.id,
        puede=principal.tiene,
    )
    return {"id": str(fila.id), "clave": fila.clave}


montar_listado(
    router_codigo,
    modelo=ct.Extension,
    objeto="extension",
    permiso="automatizacion:read",
    permiso_escribir="automatizacion:write",
    nombre="Extensiones",
    ficha=False,
)
montar_ficha(
    router_codigo,
    modelo=ct.Extension,
    objeto="extension",
    permiso_leer="automatizacion:read",
    permiso_escribir="automatizacion:write",
    nombre="Extensiones",
    editable=frozenset({"nombre", "descripcion"}),
)


@router_codigo.get(
    "/{extension_id}/versiones",
    response_model=ListaVersiones,
    dependencies=[Depends(exige_permiso("automatizacion:read"))],
    summary="Las versiones publicadas de esta extensión",
)
def versiones(extension_id: UUID, db: DbDep) -> Any:
    from sqlalchemy import select

    ext = ct.extension(db, extension_id)
    filas = db.execute(
        select(ct.VersionExtension)
        .where(ct.VersionExtension.extension_id == ext.id)
        .order_by(ct.VersionExtension.version.desc())
    ).scalars()
    return {
        "items": [
            {
                "titulo": f"Versión {v.version}"
                + (" · activa" if v.version == ext.version_activa else "")
                + {
                    "pendiente_revision": " · pendiente de revisión",
                    "rechazada": " · rechazada",
                }.get(v.estado, ""),
                "version": v.version,
                "estado": v.estado,
                "activa": v.version == ext.version_activa,
                "huella": v.huella,
                "motor_version": v.motor_version,
                "notas": v.notas,
                "publicada_por": str(v.publicada_por) if v.publicada_por else None,
                "publicada_el": v.created_at.isoformat() if v.created_at else None,
                "revisada_por": str(v.revisada_por) if v.revisada_por else None,
                "nota_revision": v.nota_revision,
            }
            for v in filas
        ]
    }


@router_codigo.post(
    "/{extension_id}/versiones",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("automatizacion:write"))],
    summary="Publicar una versión nueva del código",
    description=(
        "Crea la versión siguiente sin pisar ninguna y sin activarla. Si la extensión "
        "es de terceros, va con su firma, se comprueba contra la clave del firmante y "
        "queda pendiente de que la revise otra persona."
    ),
)
def publicar(extension_id: UUID, datos: VersionIn, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = ct.publicar_version(
        uow,
        extension_id,
        codigo=datos.codigo,
        notas=datos.notas,
        firmante_id=datos.firmante_id,
        firma=datos.firma,
        por=principal.id,
    )
    return {"version": fila.version, "estado": fila.estado, "huella": fila.huella}


@router_codigo.post(
    "/{extension_id}/versiones/{version}/revisar",
    dependencies=[Depends(exige_permiso("automatizacion:write"))],
    summary="Revisar una versión de terceros",
    description=("Aprobarla o rechazarla, con nota. No la puede revisar quien la publicó."),
)
def revisar(
    extension_id: UUID, version: int, datos: RevisionIn, uow: UowDep, principal: AutenticadoDep
) -> Any:
    fila = ct.revisar_version(
        uow, extension_id, version, aprobar=datos.aprobar, nota=datos.nota, por=principal.id
    )
    return {"version": fila.version, "estado": fila.estado}


@router_codigo.post(
    "/{extension_id}/activar",
    dependencies=[Depends(exige_permiso("automatizacion:write"))],
    summary="Activar una versión",
    description="La que se ejecuta desde ahora. Las demás siguen guardadas, enteras.",
)
def activar(extension_id: UUID, datos: ActivarIn, uow: UowDep) -> Any:
    ext = ct.activar(uow, extension_id, datos.version, motivo=datos.motivo)
    return {"id": str(ext.id), "version_activa": ext.version_activa}


@router_codigo.post(
    "/{extension_id}/volver-atras",
    dependencies=[Depends(exige_permiso("automatizacion:write"))],
    summary="Volver a la versión anterior",
    description=(
        "Activa la versión anterior que se puede activar, entera: volver atrás no es "
        "deshacer cambios, que falla en cuanto hay dependencias. Lleva motivo."
    ),
)
def volver_atras(extension_id: UUID, datos: VolverAtrasIn, uow: UowDep) -> Any:
    ext = ct.volver_atras(uow, extension_id, motivo=datos.motivo)
    return {"id": str(ext.id), "version_activa": ext.version_activa}


@router_codigo.post(
    "/{extension_id}/probar",
    dependencies=[Depends(exige_permiso("automatizacion:write"))],
    summary="Probar la extensión con una entrada",
    description=(
        "La ejecuta en el sandbox con la entrada que se le dé y enseña lo que "
        "devuelve, sus `console.log` y lo que gastó. **Las acciones que pida no se "
        "hacen**: se enseñan. La prueba cuenta para la cuota y queda apuntada."
    ),
)
def probar(extension_id: UUID, datos: ProbarIn, db: DbDep, principal: AutenticadoDep) -> Any:
    ext = ct.extension(db, extension_id)
    return ct.ejecutar(
        db,
        ext,
        entrada=datos.entrada,
        origen="prueba",
        quien=principal.id,
        version=datos.version,
        hacer_acciones=False,
    )


@router_codigo.post(
    "/{extension_id}/observabilidad",
    dependencies=[Depends(exige_permiso("automatizacion:read"))],
    summary="Cómo va esta extensión: ejecuciones, fallos, cortes y coste",
    description=(
        "Con las ejecuciones guardadas: cuántas, cuántas fallaron y cuántas se "
        "cortaron por límite —aparte, porque una que falla tiene un error que "
        "arreglar y una que se corta tiene un diseño que revisar—, las más lentas "
        "con su entrada, el coste atribuido y el desglose por versión. Es POST y "
        "no GET para que se pueda pedir desde la ficha, como el panel de una clave "
        "de API: no cambia nada."
    ),
)
def observabilidad(extension_id: UUID, db: DbDep) -> Any:
    return ct.observabilidad(db, ct.extension(db, extension_id))


@router_codigo.get(
    "/{extension_id}/ejecuciones",
    response_model=ListaEjecuciones,
    dependencies=[Depends(exige_permiso("automatizacion:read"))],
    summary="Las últimas ejecuciones, con su error y sus logs",
)
def ejecuciones(extension_id: UUID, db: DbDep, limite: int = 50) -> Any:
    from sqlalchemy import select

    ext = ct.extension(db, extension_id)
    filas = db.execute(
        select(ct.EjecucionExtension)
        .where(ct.EjecucionExtension.extension_id == ext.id)
        .order_by(ct.EjecucionExtension.cuando.desc())
        .limit(max(1, min(limite, 500)))
    ).scalars()
    return {
        "items": [
            {
                "titulo": f"v{e.version} · {e.origen} · {e.ms} ms · "
                + (
                    "bien"
                    if e.ok
                    else f"cortada por {e.cortada_por}"
                    if e.cortada_por
                    else (e.error or "falló").splitlines()[0][:120]
                ),
                "id": str(e.id),
                "cuando": e.cuando.isoformat() if e.cuando else None,
                "version": e.version,
                "origen": e.origen,
                "ok": e.ok,
                "cortada_por": e.cortada_por,
                "ms": e.ms,
                "combustible": e.combustible,
                "error": e.error,
                "logs": e.logs,
                "acciones": e.acciones,
                "acciones_fallidas": e.acciones_fallidas,
                "coste": float(e.coste),
            }
            for e in filas
        ]
    }


# ── Los endpoints propios, servidos ───────────────────────────────────────


async def invocar_endpoint_propio(
    ruta: str, request: Request, db: DbDep, principal: AutenticadoDep
) -> Any:
    from starlette.concurrency import run_in_threadpool

    fila = ct.resolver_endpoint(db, principal.tenant_id, request.method, ruta)
    if fila.permiso:
        principal.exigir(fila.permiso)
    cuerpo: Any = None
    if request.method in ("POST", "PUT", "PATCH"):
        try:
            cuerpo = await request.json()
        except ValueError:
            cuerpo = None
    ext = ct.extension(db, fila.extension_id)
    entrada = {
        "metodo": request.method,
        "ruta": fila.ruta,
        "consulta": dict(request.query_params),
        "cuerpo": cuerpo,
        "quien": {"id": str(principal.id) if principal.id else None},
    }
    # En un hilo: la ejecución bloquea hasta su tope de reloj, y en el bucle de
    # eventos pararía todas las demás peticiones del servicio mientras tanto.
    salida = await run_in_threadpool(
        ct.ejecutar, db, ext, entrada=entrada, origen="endpoint", quien=principal.id
    )
    if not salida["ok"]:
        # Se CONTESTA el error, no se lanza: lanzarlo deshace la transacción de
        # la petición y con ella el apunte de esta ejecución, que es justo la que
        # más interesa ver. Medido: la ejecución fallida no aparecía.
        from crmcore.http.problems import manejar_error_dominio

        return await manejar_error_dominio(
            request,
            ErrorDependencia(
                f"La extensión «{ext.clave}» no ha contestado bien: {salida['error']}",
                error_code="extension.fallo",
                detalle={"cortada_por": salida["cortada_por"], "version": salida["version"]},
            ),
        )
    resultado = salida["resultado"]
    if isinstance(resultado, dict) and isinstance(resultado.get("estado"), int):
        estado = int(resultado["estado"])
        if not 200 <= estado <= 499:
            estado = 200
        return JSONResponse(status_code=estado, content=resultado.get("cuerpo"))
    return resultado


# Una ruta por método, y no una con todos: con una sola, FastAPI publica el
# mismo `operationId` para los cinco métodos y un cliente generado del
# contrato choca consigo mismo. Lo avisaba en cada arranque y no lo leía nadie.
for _metodo in ct.METODOS_ENDPOINT:
    router_propios.add_api_route(
        "/{ruta:path}",
        invocar_endpoint_propio,
        methods=[_metodo],
        operation_id=f"invocar_endpoint_propio_{_metodo.lower()}",
        summary="Un endpoint propio del tenant",
        description=(
            "Ejecuta la extensión del endpoint con `{metodo, ruta, consulta, cuerpo}`. "
            "Si devuelve `{estado, cuerpo}`, se contesta eso; si no, 200 con lo que "
            "devuelva. El permiso lo declara cada endpoint y se comprueba al resolverlo."
        ),
    )


ROUTERS_CODIGO = [router_codigo, router_propios]
