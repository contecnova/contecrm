"""API de conectividad: catálogo de conectores, MCP, canales de entrada,
federación y convivencia con el sistema heredado.

CRM-00.03.04.01, .03, .10, .11 · CRM-07.02.01.09 · CRM-00.02.03.09, .10 ·
CRM-01.01.05.04 · CRM-00.03.01.07 · CRM-01.02.01.04.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from crmcore.http.listados import montar_listado
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from services.integration import canales_entrada as canales
from services.integration import convivencia as conv
from services.integration import federacion as fed
from services.integration import manifiestos as man
from services.integration import mcp as mcp_mod
from services.integration import transportes_legado as transportes
from services.integration.mcp import Exposicion

router = APIRouter(prefix="/conectores", tags=["conectores"])
# `/agentes` ya es del servicio de atención —los agentes de soporte y su
# presencia—, así que aquí va `/agentes-ia`. Dos servicios compartiendo prefijo
# hacen que el gateway mande a uno las rutas del otro.
router_mcp = APIRouter(prefix="/agentes-ia", tags=["mcp"])
router_canales = APIRouter(prefix="/canales-entrada", tags=["canales"])
router_fed = APIRouter(prefix="/federacion", tags=["federacion"])
router_conv = APIRouter(prefix="/convivencia", tags=["convivencia"])


# ── Cuerpos ───────────────────────────────────────────────────────────────


class PublicarManifiesto(BaseModel):
    clave: str = Field(..., min_length=1, max_length=80)
    nombre: str = Field(..., min_length=1, max_length=200)
    version: str = Field(..., min_length=1, max_length=20)
    operaciones: list[dict[str, Any]] = Field(..., min_length=1)
    categoria: str = "otros"
    descripcion: str = ""
    protocolo: str = Field("rest", description="rest · soap · sftp · fichero · edi · amqp")
    credenciales: list[dict[str, Any]] = Field(default_factory=list)
    dominios: list[str] = Field(default_factory=list)
    config_defecto: dict[str, Any] = Field(default_factory=dict)
    notas_version: str = ""


class Instalar(BaseModel):
    clave: str
    version: str = ""
    config: dict[str, Any] = Field(default_factory=dict)
    credenciales_puestas: list[str] = Field(default_factory=list)


class LeerFichero(BaseModel):
    contenido: str
    config: dict[str, Any] = Field(
        default_factory=dict, description="formato, separador, columnas, dialecto…"
    )


class CrearExposicion(BaseModel):
    clave: str = Field(..., min_length=1, max_length=80)
    nombre: str = ""
    descripcion: str = ""
    cuota_hora: int = 1000


class PublicarHerramienta(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=80)
    permiso: str = Field(..., min_length=1)
    descripcion: str = ""
    tipo: str = "lectura"
    parametros: dict[str, Any] = Field(default_factory=dict)
    destino: dict[str, Any] = Field(default_factory=dict)
    exige_confirmacion: bool = False


class Invocar(BaseModel):
    herramienta: str
    argumentos: dict[str, Any] = Field(default_factory=dict)
    agente_id: UUID | None = None


class DeclararCanal(BaseModel):
    clave: str = Field(..., min_length=1, max_length=80)
    canal: str = Field(..., description="correo · sms · voz · chat · cli · agente · calendario")
    destino: str = ""
    nombre: str = ""
    produce: str = "actividad"
    guardar_contenido: bool = False


class RegistrarInteraccion(BaseModel):
    canal: str
    id_externo: str = Field(..., min_length=1)
    interlocutor: str = ""
    asunto: str = ""
    contenido: str = ""
    ocurrido_at: datetime | None = None
    duracion_s: int | None = None
    direccion: str = "entrante"
    clave_canal: str = ""
    contacto_id: UUID | None = None
    cuenta_id: UUID | None = None
    usuario_id: UUID | None = None
    datos: dict[str, Any] = Field(default_factory=dict)


class DeclararVista(BaseModel):
    clave: str = Field(..., min_length=1, max_length=80)
    objeto: str = Field(..., min_length=1)
    campos: list[dict[str, Any]] = Field(..., min_length=1)
    nombre: str = ""
    instalacion_clave: str = ""
    operacion: str = ""
    clave_registro: str = "id"
    conexion_id: UUID | None = None
    timeout_ms: int = 2000
    cache_s: int = 60


class DeclararEmbebido(BaseModel):
    clave: str = Field(..., min_length=1, max_length=80)
    anfitrion: str = ""
    origenes: list[str] = Field(..., min_length=1)
    bloques: list[str] = Field(..., min_length=1)
    contexto: dict[str, str] = Field(default_factory=dict)
    nombre: str = ""


class ResolverContexto(BaseModel):
    clave: str
    origen: str
    parametros: dict[str, Any] = Field(default_factory=dict)


class DeclararConvivencia(BaseModel):
    objeto: str = Field(..., min_length=1)
    dueno: str = Field(..., description="heredado · nuevo · ambos")
    nombre: str = ""
    condiciones: list[dict[str, Any]] = Field(default_factory=list)
    prioridad: int = 100
    manda_en_empate: str | None = None
    replicar_al_heredado: bool = False


class Medir(BaseModel):
    objeto: str
    en_heredado: int = Field(..., ge=0)
    en_nuevo: int = Field(..., ge=0)
    nota: str = ""


# ── Catálogo de conectores ────────────────────────────────────────────────


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("integracion:write"))],
    summary="Publicar una versión de conector en el catálogo",
    description=(
        "Un conector es un **manifiesto**, no un módulo: añadir un ERP es publicar "
        "un documento, no desplegar código. Se valida al publicarlo, porque un "
        "mapeo mal escrito descubierto en un proceso nocturno produce un error que "
        "no se parece a la causa."
    ),
)
def publicar(datos: PublicarManifiesto, uow: UowDep) -> Any:
    fila = man.publicar(uow, **datos.model_dump())
    return {"id": str(fila.id), "clave": fila.clave, "version": fila.version}


@router.get(
    "",
    dependencies=[Depends(exige_permiso("integracion:read"))],
    summary="Catálogo de conectores disponibles",
    description=(
        "La última versión de cada uno, con lo que va a pedir y a qué dominios va "
        "a llamar **antes** de instalarlo."
    ),
)
def catalogo(db: DbDep, categoria: str = Query("")) -> Any:
    return man.catalogo(db, categoria=categoria)


@router.post(
    "/instalar",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("integracion:write"))],
    summary="Instalar un conector en este tenant",
    description=(
        "Devuelve qué credenciales faltan en vez de fallar: instalar y configurar "
        "son dos momentos, y la credencial la tiene a veces otra persona. Lo que no "
        "se hace es darlo por operativo."
    ),
)
def instalar(datos: Instalar, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila, informe = man.instalar(uow, por=principal.id, **datos.model_dump())
    return {"id": str(fila.id), "clave": fila.clave, "version": fila.version, **informe}


@router.get(
    "/instalados",
    dependencies=[Depends(exige_permiso("integracion:read"))],
    summary="Lo instalado aquí y qué actualizaciones hay",
    description="**No se actualiza solo**: se dice qué cambia y decide una persona.",
)
def instalados(db: DbDep, principal: AutenticadoDep) -> Any:
    return man.actualizaciones(db, principal.tenant_id)


@router.post(
    "/{clave}/actualizar",
    dependencies=[Depends(exige_permiso("integracion:write"))],
    summary="Subir una instalación de versión",
)
def actualizar(
    clave: str, uow: UowDep, principal: AutenticadoDep, a_version: str = Query("")
) -> Any:
    return man.actualizar(uow, clave=clave, a_version=a_version, por=principal.id)


@router.delete(
    "/{clave}",
    dependencies=[Depends(exige_permiso("integracion:write"))],
    summary="Desinstalar un conector",
    description="Los datos ya traídos **se quedan**: son de la empresa, no del conector.",
)
def desinstalar(clave: str, uow: UowDep, motivo: str = Query("")) -> Any:
    fila = man.desinstalar(uow, clave=clave, motivo=motivo)
    return {"id": str(fila.id), "estado": fila.estado}


@router.post(
    "/transportes/leer",
    dependencies=[Depends(exige_permiso("integracion:write"))],
    summary="Interpretar un fichero plano o un mensaje EDI",
    description=(
        "Sin adivinar el formato: separador, columnas y dialecto se declaran. "
        "Detectarlo automáticamente funciona el 95 % de las veces, y el 5 % son "
        "cargas que entran mal sin fallar."
    ),
)
def leer(
    datos: LeerFichero, tipo: str = Query("fichero", description="fichero · edi · soap")
) -> Any:
    if tipo == "edi":
        resultado = transportes.leer_edi(datos.contenido, datos.config)
    elif tipo == "soap":
        resultado = transportes.leer_soap(datos.contenido, datos.config)
    else:
        resultado = transportes.leer_fichero(datos.contenido, datos.config)
    return {"filas": resultado.filas, "avisos": resultado.avisos, "cuantas": len(resultado.filas)}


@router.get(
    "/transportes",
    dependencies=[Depends(exige_permiso("integracion:read"))],
    summary="Qué protocolos sabe hablar esta instalación",
)
def listar_transportes() -> Any:
    return {
        "protocolos": list(transportes.PROTOCOLOS),
        "registrados": transportes.transportes_registrados(),
        "formatos_fichero": list(transportes.FORMATOS),
        "dialectos_edi": list(transportes.DIALECTOS_EDI),
    }


# ── Agentes (MCP) ─────────────────────────────────────────────────────────


@router_mcp.post(
    "/exposiciones",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("integracion:write"))],
    summary="Crear un conjunto de herramientas para agentes",
)
def crear_exposicion(datos: CrearExposicion, uow: UowDep) -> Any:
    fila = mcp_mod.crear_exposicion(uow, **datos.model_dump())
    return {"id": str(fila.id), "clave": fila.clave, "cuota_hora": fila.cuota_hora}


@router_mcp.post(
    "/exposiciones/{exposicion_id}/herramientas",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("integracion:write"))],
    summary="Publicar una herramienta",
    description=(
        "Las de escritura se traducen a un **comando** al servicio dueño: no hay "
        "puerta trasera que se salte las reglas de negocio."
    ),
)
def publicar_herramienta(exposicion_id: UUID, datos: PublicarHerramienta, uow: UowDep) -> Any:
    fila, avisos = mcp_mod.publicar_herramienta(uow, exposicion_id, **datos.model_dump())
    return {"id": str(fila.id), "nombre": fila.nombre, "avisos": avisos}


@router_mcp.get(
    "/{exposicion}/herramientas",
    dependencies=[Depends(exige_permiso("integracion:read"))],
    summary="Catálogo de herramientas para este agente",
    description=(
        "Filtrado por **sus** permisos antes de enseñarlo: publicar todo y fallar "
        "al invocar le hace gastar llamadas en lo que no puede hacer."
    ),
)
def catalogo_mcp(exposicion: str, db: DbDep, principal: AutenticadoDep) -> Any:
    return mcp_mod.catalogo_para(
        db, principal.tenant_id, exposicion=exposicion, principal=principal
    )


@router_mcp.post(
    "/{exposicion}/invocar",
    dependencies=[Depends(exige_permiso("integracion:read"))],
    summary="Invocar una herramienta",
    description=(
        "Comprueba interruptor, permiso, cuota y parámetros, en ese orden. La "
        "escritura queda **pedida** al servicio dueño, no hecha."
    ),
)
def invocar(exposicion: str, datos: Invocar, uow: UowDep, principal: AutenticadoDep) -> Any:
    return mcp_mod.invocar(
        uow,
        exposicion=exposicion,
        herramienta=datos.herramienta,
        argumentos=datos.argumentos,
        principal=principal,
        agente_id=datos.agente_id,
    )


@router_mcp.post(
    "/{exposicion}/detener",
    dependencies=[Depends(exige_permiso("integracion:write"))],
    summary="Interruptor de emergencia",
    description="Corta ahora y se decide después, sin tocar permisos ni borrar nada.",
)
def detener(exposicion: str, uow: UowDep, motivo: str = Query(..., min_length=1)) -> Any:
    fila = mcp_mod.detener(uow, exposicion=exposicion, motivo=motivo)
    return {"clave": fila.clave, "detenida": fila.detenida, "motivo": fila.motivo_detencion}


@router_mcp.get(
    "/uso",
    dependencies=[Depends(exige_permiso("integracion:read"))],
    summary="Qué han hecho los agentes",
    description=(
        "Los rechazos importan tanto como las ejecuciones: muchos por permisos "
        "significan que el catálogo y lo que el agente puede no coinciden."
    ),
)
def uso(db: DbDep, principal: AutenticadoDep, horas: int = Query(24, ge=1, le=720)) -> Any:
    return mcp_mod.uso(db, principal.tenant_id, horas=horas)


# ── Canales de entrada ────────────────────────────────────────────────────


@router_canales.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("integracion:write"))],
    summary="Declarar una vía de entrada sin interfaz",
)
def declarar_canal(datos: DeclararCanal, uow: UowDep) -> Any:
    fila = canales.declarar_canal(uow, **datos.model_dump())
    return {"id": str(fila.id), "clave": fila.clave, "produce": fila.produce}


@router_canales.post(
    "/interacciones",
    dependencies=[Depends(exige_permiso("integracion:write"))],
    summary="Registrar una interacción llegada por un canal",
    description=(
        "Idempotente por el identificador del canal. Lo que no se puede atribuir "
        "**se guarda y se cuenta**: un correo de una dirección desconocida es un "
        "contacto que falta, no basura."
    ),
)
def registrar_interaccion(datos: RegistrarInteraccion, uow: UowDep) -> Any:
    return canales.registrar(uow, **datos.model_dump())


@router_canales.get(
    "/sin-atribuir",
    dependencies=[Depends(exige_permiso("integracion:read"))],
    summary="Interacciones que no se pudieron colgar de nadie",
)
def sin_atribuir(
    db: DbDep, principal: AutenticadoDep, limite: int = Query(100, ge=1, le=500)
) -> Any:
    return canales.sin_atribuir(db, principal.tenant_id, limite=limite)


@router_canales.post(
    "/interacciones/{interaccion_id}/atribuir",
    dependencies=[Depends(exige_permiso("integracion:write"))],
    summary="Atribuir a posteriori",
)
def atribuir(
    interaccion_id: UUID,
    uow: UowDep,
    contacto_id: UUID | None = Query(None),
    cuenta_id: UUID | None = Query(None),
) -> Any:
    fila = canales.atribuir(uow, interaccion_id, contacto_id=contacto_id, cuenta_id=cuenta_id)
    return {"id": str(fila.id), "atribuida": fila.atribuida}


@router_canales.get(
    "/contacto/{contacto_id}",
    dependencies=[Depends(exige_permiso("integracion:read"))],
    summary="Lo hablado con un contacto, de todos los canales",
)
def actividad_de(contacto_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return canales.actividad_de(db, principal.tenant_id, contacto_id=contacto_id)


# ── Federación y embebido ─────────────────────────────────────────────────


@router_fed.post(
    "/vistas",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("integracion:write"))],
    summary="Declarar un bloque de datos externos sin replicar",
)
def declarar_vista(datos: DeclararVista, uow: UowDep) -> Any:
    fila, avisos = fed.declarar_vista(uow, **datos.model_dump())
    return {"id": str(fila.id), "clave": fila.clave, "avisos": avisos}


@router_fed.get(
    "/vistas",
    dependencies=[Depends(exige_permiso("integracion:read"))],
    summary="Vistas federadas declaradas",
)
def listar_vistas(db: DbDep, principal: AutenticadoDep, objeto: str = Query("")) -> Any:
    consulta = select(fed.VistaFederada).where(fed.VistaFederada.tenant_id == principal.tenant_id)
    if objeto:
        consulta = consulta.where(fed.VistaFederada.objeto == objeto)
    filas = db.execute(consulta).scalars().all()
    return {
        "vistas": [
            {
                "id": str(f.id),
                "clave": f.clave,
                "objeto": f.objeto,
                "campos": f.campos,
                "timeout_ms": f.timeout_ms,
                "cache_s": f.cache_s,
                "activa": f.activa,
            }
            for f in filas
        ],
        # Se repite aquí porque es la pregunta de quien lo integra.
        "filtrable": False,
    }


@router_fed.post(
    "/embebidos",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("integracion:write"))],
    summary="Declarar dónde puede vivir el CRM embebido",
    description=(
        "La lista de orígenes es obligatoria y en https: sin ella, cualquier página "
        "podría incrustarlo y pedir datos con la sesión de quien la abra."
    ),
)
def declarar_embebido(datos: DeclararEmbebido, uow: UowDep) -> Any:
    fila = fed.declarar_embebido(uow, **datos.model_dump())
    return {"id": str(fila.id), "clave": fila.clave, "origenes": fila.origenes}


@router_fed.post(
    "/embebidos/contexto",
    dependencies=[Depends(exige_permiso("integracion:read"))],
    summary="Traducir el contexto que manda el anfitrión",
)
def resolver_contexto(datos: ResolverContexto, db: DbDep, principal: AutenticadoDep) -> Any:
    return fed.resolver_contexto(
        db,
        principal.tenant_id,
        clave=datos.clave,
        origen=datos.origen,
        parametros=datos.parametros,
    )


# ── Convivencia con el heredado ───────────────────────────────────────────


@router_conv.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("integracion:write"))],
    summary="Declarar quién manda sobre un objeto",
    description=(
        "Por objeto y por criterio, no por sistema entero: «los clientes nuevos "
        "aquí, los antiguos allí» es como se migra de verdad."
    ),
)
def declarar_convivencia(datos: DeclararConvivencia, uow: UowDep) -> Any:
    fila, avisos = conv.declarar(uow, **datos.model_dump())
    return {"id": str(fila.id), "objeto": fila.objeto, "dueno": fila.dueno, "avisos": avisos}


@router_conv.get(
    "/quien-manda",
    dependencies=[Depends(exige_permiso("integracion:read"))],
    summary="Quién manda sobre este registro, y por qué",
    description=(
        "Sin ninguna regla declarada manda el heredado: equivocarse hacia el viejo "
        "produce un dato que hay que traer; hacia el nuevo, dos verdades."
    ),
)
def quien_manda(
    db: DbDep, principal: AutenticadoDep, objeto: str = Query(..., min_length=1)
) -> Any:
    return conv.quien_manda(db, principal.tenant_id, objeto=objeto)


@router_conv.post(
    "/medidas",
    dependencies=[Depends(exige_permiso("integracion:write"))],
    summary="Anotar cuántos registros quedan en cada lado",
)
def medir(datos: Medir, uow: UowDep) -> Any:
    fila = conv.medir(uow, **datos.model_dump())
    return {"objeto": fila.objeto, "en_heredado": fila.en_heredado, "en_nuevo": fila.en_nuevo}


@router_conv.get(
    "/progreso",
    dependencies=[Depends(exige_permiso("integracion:read"))],
    summary="Cuánto queda por migrar, y de cuándo es la medida",
    description=(
        "Un strangler sin medida no termina. Una medida de hace tres meses "
        "presentada como actual hace creer que va bien, así que la edad va delante."
    ),
)
def progreso(db: DbDep, principal: AutenticadoDep) -> Any:
    return conv.progreso(db, principal.tenant_id)


@router_conv.post(
    "/{objeto}/migrado",
    dependencies=[Depends(exige_permiso("integracion:write"))],
    summary="Cerrar la convivencia de un objeto",
)
def dar_por_migrado(
    objeto: str, uow: UowDep, forzar: bool = Query(False), motivo: str = Query("")
) -> Any:
    return conv.dar_por_migrado(uow, objeto=objeto, forzar=forzar, motivo=motivo)


# ── Listados ──────────────────────────────────────────────────────────────
# Estas colecciones se podían crear y no se podían leer: tenían `POST` y no
# tenían `GET`, así que lo que se daba de alta desaparecía de la vista. La API
# contestaba 405 y el front —que las declara listables— enseñaba una pantalla
# vacía sin decir por qué.

montar_listado(
    router_canales,
    modelo=canales.CanalEntrada,
    objeto="canal_entrada",
    permiso="integracion:read",
    nombre="Canales de entrada",
)
montar_listado(
    router_conv,
    modelo=conv.ReglaConvivencia,
    objeto="regla_convivencia",
    permiso="integracion:read",
    nombre="Reglas de convivencia",
)


# ── Listados de las sub-colecciones ───────────────────────────────────────
# Mismo agujero que en las colecciones raíz: se podían crear y no se podían
# leer. Un sobre de firma, un subprocesador o una transferencia internacional
# que no se pueden listar no existen para quien tiene que auditarlos.

montar_listado(
    router_mcp,
    modelo=Exposicion,
    objeto="exposicion_mcp",
    permiso="integracion:read",
    ruta="/exposiciones",
    nombre="Exposiciones de agentes",
)
montar_listado(
    router_canales,
    modelo=canales.Interaccion,
    objeto="interaccion",
    permiso="integracion:read",
    ruta="/interacciones",
    nombre="Interacciones de canal",
)


# ── Listados ──────────────────────────────────────────────────────────────
# Colecciones con acciones sobre sus registros y sin forma de listarlos: se
# podía desplegar un entorno, invocar un agente o cerrar una visita, y no ver
# ninguno. A una acción sobre un registro se llega por su ficha, y a la ficha
# por el listado: sin listado, la acción no la alcanza nadie.

montar_listado(
    router_mcp,
    modelo=Exposicion,
    objeto="exposicion_mcp_raiz",
    permiso="integracion:read",
    nombre="Agentes de IA expuestos",
)


ROUTERS_CONECTIVIDAD = [router, router_mcp, router_canales, router_fed, router_conv]
