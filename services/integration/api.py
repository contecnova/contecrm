"""API del servicio de integración."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.audit.chain import registrar
from crmcore.errors import Conflicto, CrmError, ErrorValidacion, NoEncontrado
from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from crmcore.http.listados import montar_ficha, montar_listado
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from services.integration import conector
from services.integration.modelos import (
    Conexion,
    Credencial,
    Ejecucion,
    Operacion,
    RegistroRecibido,
)


class CrearConexion(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=200)
    sistema: str = Field(
        "",
        description=(
            "Informativo. NO cambia el comportamiento: si lo cambiara, "
            "volveríamos a tener código por proveedor"
        ),
        examples=["sap", "odoo"],
    )
    descripcion: str = ""
    protocolo: str = "rest"
    config: dict[str, Any] = Field(
        ...,
        description="URL base, tipo de autenticación, cabeceras fijas, marcadores de vacío",
        examples=[
            {
                "url_base": "https://erp.cliente.com/api/v2",
                "auth_tipo": "oauth2_client_credentials",
                "oauth_token_url": "https://erp.cliente.com/oauth/token",
            }
        ],
    )


class ConexionOut(BaseModel):
    id: UUID
    nombre: str
    sistema: str
    descripcion: str
    protocolo: str
    config: dict[str, Any] = {}
    activa: bool
    probada_at: datetime | None = None
    prueba_ok: bool | None = None
    prueba_detalle: str | None = None

    model_config = {"from_attributes": True}


class FijarCredencial(BaseModel):
    valores: dict[str, str] = Field(
        ...,
        description="Se guardan cifrados y no se devuelven nunca",
        examples=[{"client_id": "…", "client_secret": "…"}],
    )
    caduca_at: datetime | None = None


class CrearOperacion(BaseModel):
    clave: str = Field(..., min_length=1, max_length=120, examples=["leer_clientes"])
    nombre: str = Field(..., min_length=1, max_length=200)
    definicion: dict[str, Any] = Field(
        ...,
        description=(
            "Método, ruta, query, cuerpo, dónde están los resultados, paginación "
            "y mapeo a campos de contecrm"
        ),
        examples=[
            {
                "metodo": "GET",
                "ruta": "/customers",
                "ruta_resultados": "data.items",
                "paginacion": {
                    "estilo": "cursor",
                    "ruta_cursor": "meta.next",
                    "param_cursor": "cursor",
                },
                "mapeo": {
                    "nombre": ["legal_name", "name"],
                    "nif": "tax_id",
                    "email": "contact.email",
                },
                "valores_vacios": ["N/A", "-"],
            }
        ],
    )


class OperacionOut(BaseModel):
    id: UUID
    clave: str
    nombre: str
    definicion: dict[str, Any] = {}
    activa: bool

    model_config = {"from_attributes": True}


class Invocar(BaseModel):
    parametros: dict[str, Any] = Field(default_factory=dict)
    # Prueba en seco: ejecuta la llamada pero no propaga el resultado a nadie.
    # Sirve para validar un mapeo contra datos reales sin efectos.
    solo_probar: bool = False


class EjecucionOut(BaseModel):
    id: UUID
    operacion: str
    resultado: str
    registros: int
    paginas: int
    duracion_ms: int
    error: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


router = APIRouter(prefix="/integraciones", tags=["integraciones"])


def _conexion(db: Any, tenant_id: UUID, conexion_id: UUID) -> Conexion:
    conexion = db.get(Conexion, conexion_id)
    if conexion is None or conexion.tenant_id != tenant_id:
        raise NoEncontrado("La conexión no existe", error_code="integracion.no_encontrada")
    return conexion


def _secretos(db: Any, conexion_id: UUID) -> dict[str, str]:
    """Descifra las credenciales activas de la conexión."""
    credencial = db.execute(
        select(Credencial)
        .where(Credencial.conexion_id == conexion_id, Credencial.activa.is_(True))
        .order_by(Credencial.version.desc())
        .limit(1)
    ).scalar_one_or_none()
    if credencial is None:
        return {}
    from crmcore.security.cifrado import descifrar_dict

    return descifrar_dict(credencial.valores)


@router.post(
    "/conexiones",
    response_model=ConexionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("integracion:write"))],
    summary="Declarar una conexión a un sistema externo",
)
def crear_conexion(datos: CrearConexion, db: DbDep, principal: AutenticadoDep) -> Any:
    if db.execute(
        select(Conexion.id).where(
            Conexion.tenant_id == principal.tenant_id, Conexion.nombre == datos.nombre
        )
    ).first():
        raise Conflicto(
            "Ya existe una conexión con ese nombre", error_code="integracion.nombre_duplicado"
        )
    conexion = Conexion(tenant_id=principal.tenant_id, **datos.model_dump())
    db.add(conexion)
    db.flush()
    registrar(
        db,
        accion="integracion.conexion_creada",
        objeto="conexion",
        objeto_id=conexion.id,
        datos={"nombre": datos.nombre, "sistema": datos.sistema},
    )
    return conexion


@router.get(
    "/conexiones",
    response_model=list[ConexionOut],
    dependencies=[Depends(exige_permiso("integracion:read"))],
    summary="Conexiones del tenant",
)
def listar_conexiones(db: DbDep, principal: AutenticadoDep) -> Any:
    return list(
        db.execute(
            select(Conexion)
            .where(Conexion.tenant_id == principal.tenant_id)
            .order_by(Conexion.nombre)
        )
        .scalars()
        .all()
    )


@router.put(
    "/conexiones/{conexion_id}/credenciales",
    response_model=dict,
    dependencies=[Depends(exige_permiso("integracion:credenciales"))],
    summary="Fijar o rotar las credenciales de una conexión",
    description=(
        "Se guardan cifradas y no se devuelven nunca. Rotar crea una versión "
        "nueva y desactiva la anterior, así que se puede revertir si la nueva "
        "credencial resulta estar mal."
    ),
)
def fijar_credencial(
    conexion_id: UUID, datos: FijarCredencial, db: DbDep, principal: AutenticadoDep
) -> Any:
    conexion = _conexion(db, principal.tenant_id, conexion_id)
    from crmcore.security.cifrado import cifrar_dict

    anteriores = list(
        db.execute(
            select(Credencial).where(
                Credencial.conexion_id == conexion.id, Credencial.activa.is_(True)
            )
        )
        .scalars()
        .all()
    )
    for previa in anteriores:
        previa.activa = False
        previa.rotada_at = datetime.now(timezone.utc)

    credencial = Credencial(
        tenant_id=principal.tenant_id,
        conexion_id=conexion.id,
        valores=cifrar_dict(datos.valores),
        version=(max((c.version for c in anteriores), default=0) + 1),
        caduca_at=datos.caduca_at,
    )
    db.add(credencial)
    # El token cacheado de la credencial vieja deja de valer al rotar.
    conector.limpiar_tokens()
    registrar(
        db,
        accion="integracion.credencial_rotada",
        objeto="conexion",
        objeto_id=conexion.id,
        datos={"version": credencial.version, "claves": sorted(datos.valores)},
    )
    return {"version": credencial.version, "rotada": bool(anteriores)}


@router.post(
    "/conexiones/{conexion_id}/probar",
    response_model=dict,
    dependencies=[Depends(exige_permiso("integracion:write"))],
    summary="Probar la conectividad de una conexión",
    description=(
        "Ejecuta la operación marcada como prueba, o la primera declarada. "
        "Sirve para descubrir una credencial caducada **antes** de que falle un "
        "proceso de negocio."
    ),
)
async def probar(conexion_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    conexion = _conexion(db, principal.tenant_id, conexion_id)
    operacion = db.execute(
        select(Operacion)
        .where(Operacion.conexion_id == conexion.id, Operacion.activa.is_(True))
        .order_by(Operacion.created_at)
        .limit(1)
    ).scalar_one_or_none()
    if operacion is None:
        raise NoEncontrado(
            "La conexión no tiene ninguna operación declarada con la que probar",
            error_code="integracion.sin_operaciones",
        )
    try:
        resultado = await conector.ejecutar(
            conexion.config,
            operacion.definicion,
            {},
            secretos=_secretos(db, conexion.id),
            tenant_id=str(principal.tenant_id),
        )
        conexion.prueba_ok = True
        conexion.prueba_detalle = (
            f"{resultado['registros'] and len(resultado['registros'])} registros"
        )
    except CrmError as exc:
        conexion.prueba_ok = False
        conexion.prueba_detalle = f"{exc.error_code}: {exc.mensaje}"[:500]
    conexion.probada_at = datetime.now(timezone.utc)
    return {"ok": conexion.prueba_ok, "detalle": conexion.prueba_detalle}


@router.post(
    "/conexiones/{conexion_id}/operaciones",
    response_model=OperacionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("integracion:write"))],
    summary="Declarar una operación",
)
def crear_operacion(
    conexion_id: UUID, datos: CrearOperacion, db: DbDep, principal: AutenticadoDep
) -> Any:
    conexion = _conexion(db, principal.tenant_id, conexion_id)
    operacion = Operacion(
        tenant_id=principal.tenant_id, conexion_id=conexion.id, **datos.model_dump()
    )
    db.add(operacion)
    db.flush()
    return operacion


@router.post(
    "/conexiones/{conexion_id}/operaciones/{clave}/invocar",
    response_model=dict,
    dependencies=[Depends(exige_permiso("integracion:invocar"))],
    summary="Invocar una operación",
    description=(
        "Devuelve los registros **ya mapeados** a campos de contecrm: quien "
        "consume esto no sabe nada de la API de origen, que es lo que permite "
        "cambiar de sistema externo sin tocar el resto."
    ),
)
async def invocar(
    conexion_id: UUID, clave: str, datos: Invocar, db: DbDep, principal: AutenticadoDep
) -> Any:
    conexion = _conexion(db, principal.tenant_id, conexion_id)
    operacion = db.execute(
        select(Operacion).where(Operacion.conexion_id == conexion.id, Operacion.clave == clave)
    ).scalar_one_or_none()
    if operacion is None:
        raise NoEncontrado(
            "La operación no existe", error_code="integracion.operacion_no_encontrada"
        )

    inicio = time.perf_counter()
    traza = Ejecucion(
        tenant_id=principal.tenant_id,
        conexion_id=conexion.id,
        operacion=clave,
        resultado="ok",
        parametros=datos.parametros,
    )
    try:
        resultado = await conector.ejecutar(
            conexion.config,
            operacion.definicion,
            datos.parametros,
            secretos=_secretos(db, conexion.id),
            tenant_id=str(principal.tenant_id),
        )
        traza.registros = len(resultado["registros"])
        traza.paginas = resultado["paginas"]
    except CrmError as exc:
        traza.resultado = "error"
        traza.error = f"{exc.error_code}: {exc.mensaje}"[:2000]
        traza.duracion_ms = int((time.perf_counter() - inicio) * 1000)
        db.add(traza)
        # Se relanza tras registrar la traza: el monitor tiene que ver el fallo
        # aunque el llamante reciba el error.
        raise
    traza.duracion_ms = int((time.perf_counter() - inicio) * 1000)
    db.add(traza)
    return {
        "registros": resultado["registros"],
        "total": len(resultado["registros"]),
        "paginas": resultado["paginas"],
        "crudos": resultado["crudos"],
    }


@router.get(
    "/ejecuciones",
    response_model=list[EjecucionOut],
    dependencies=[Depends(exige_permiso("integracion:read"))],
    summary="Monitor de integraciones",
    description="Ejecuciones recientes con su resultado, volumen y duración.",
)
def ejecuciones(
    db: DbDep,
    principal: AutenticadoDep,
    resultado: str = Query(""),
    limite: int = Query(50, ge=1, le=200),
) -> Any:
    consulta = select(Ejecucion).where(Ejecucion.tenant_id == principal.tenant_id)
    if resultado:
        consulta = consulta.where(Ejecucion.resultado == resultado)
    return list(
        db.execute(consulta.order_by(Ejecucion.created_at.desc()).limit(limite)).scalars().all()
    )


# ── El programador: lo que se ejecuta solo ────────────────────────────────
#
# Hasta el 05-10-2026 **nada**. El conector estaba completo y lo disparaba una
# ruta a mano, así que una integración exigía que alguien pulsara un botón cada
# día — y las decisiones que la gobiernan (cuándo avanza la marca, cómo se
# reintenta, a qué ritmo se trae la primera carga) estaban escritas, probadas y
# sin que las llamara nadie.


class Programacion(BaseModel):
    cada_minutos: int = Field(
        0,
        ge=0,
        le=43_200,
        description=(
            "Cada cuánto se ejecuta sola. Cero: sólo a mano. Hay un suelo "
            "configurable, porque por debajo el proveedor acaba cortando la cuota "
            "— y cuando corta lo hace para todos los clientes, no sólo para el "
            "que se pasó"
        ),
    )
    activa: bool = True


@router.put(
    "/conexiones/{conexion_id}/operaciones/{clave}/programacion",
    response_model=dict,
    dependencies=[Depends(exige_permiso("integracion:write"))],
    summary="Cada cuánto se ejecuta sola esta operación",
    description=(
        "La cadencia es **de la operación** y no un valor global: leer el maestro "
        "de clientes una vez al día y consultar el stock cada cinco minutos son la "
        "misma pieza con ritmos distintos, y un intervalo único obliga al lento a "
        "correr como el rápido o al revés — y lo que se hace entonces es apagar el "
        "que molesta.\n\n"
        "La primera vuelta sale **ya**, no dentro de un ciclo: quien acaba de "
        "configurarla quiere ver si funciona, no enterarse mañana de que la ruta "
        "estaba mal escrita."
    ),
)
def programar_operacion(
    conexion_id: UUID, clave: str, datos: Programacion, uow: UowDep, principal: AutenticadoDep
) -> Any:
    from services.integration import programador

    conexion = _conexion(uow.db, principal.tenant_id, conexion_id)
    operacion = uow.db.execute(
        select(Operacion).where(Operacion.conexion_id == conexion.id, Operacion.clave == clave)
    ).scalar_one_or_none()
    if operacion is None:
        raise NoEncontrado(
            "La operación no existe", error_code="integracion.operacion_no_encontrada"
        )
    return programador.programar(
        uow, operacion.id, cada_minutos=datos.cada_minutos, activa=datos.activa
    )


@router.get(
    "/programacion",
    response_model=list[dict],
    dependencies=[Depends(exige_permiso("integracion:read"))],
    summary="Qué se ejecuta solo, cuándo le toca y qué le pasó la última vez",
    description=(
        "Con el último error **a la vista**. Una operación que lleva tres semanas "
        "fallando y no se ve en ninguna pantalla es una integración que «a veces "
        "no trae datos», y eso se investiga mirando el sistema de enfrente, donde "
        "está todo bien."
    ),
)
def programacion(db: DbDep, principal: AutenticadoDep) -> Any:
    filas = (
        db.execute(
            select(Operacion)
            .where(Operacion.tenant_id == principal.tenant_id, Operacion.cada_minutos > 0)
            .order_by(Operacion.proxima_at)
        )
        .scalars()
        .all()
    )
    return [
        {
            "operacion": f.clave,
            "conexion_id": str(f.conexion_id),
            "cada_minutos": f.cada_minutos,
            "activa": f.activa,
            "proxima_at": f.proxima_at.isoformat() if f.proxima_at else None,
            "ultima_at": f.ultima_at.isoformat() if f.ultima_at else None,
            "marca": f.marca,
            "intentos": f.intentos,
            "pausada_hasta": f.pausada_hasta.isoformat() if f.pausada_hasta else None,
            "ultimo_error": f.ultimo_error,
        }
        for f in filas
    ]


class EstadoRegistro(BaseModel):
    estado: str = Field(
        "procesado",
        description="procesado · descartado. Descartar sin motivo no se admite",
    )
    porque: str = ""


@router.post(
    "/registros-recibidos/{registro_id}/estado",
    response_model=dict,
    dependencies=[Depends(exige_permiso("integracion:write"))],
    summary="Marcar un registro recibido como procesado o descartado",
    description=(
        "**Descartar exige motivo.** Un registro que no entra y no dice por qué "
        "manda a mirar al sistema de origen, donde el dato está bien, y ahí se "
        "pierde la tarde.\n\n"
        "El estado es además lo que hace que la purga tenga algo que purgar: lo "
        "que entra es una copia de datos de un sistema ajeno, y guardarla sin "
        "plazo es acumular datos personales de los que no somos responsables."
    ),
)
def estado_registro(
    registro_id: UUID, datos: EstadoRegistro, uow: UowDep, principal: AutenticadoDep
) -> Any:
    fila = uow.db.get(RegistroRecibido, registro_id)
    if fila is None or fila.tenant_id != principal.tenant_id:
        raise NoEncontrado("Ese registro no existe", error_code="integracion.registro_no_existe")
    if datos.estado not in ("procesado", "descartado"):
        raise ErrorValidacion(
            "Un registro recibido se marca «procesado» o «descartado».",
            error_code="integracion.estado_desconocido",
        )
    if datos.estado == "descartado" and not datos.porque.strip():
        raise ErrorValidacion(
            "Descartar un registro exige decir por qué: sin motivo, quien lo "
            "eche de menos irá a mirar al sistema de origen, donde el dato está "
            "bien.",
            error_code="integracion.descarte_sin_motivo",
        )
    fila.estado = datos.estado
    fila.porque = datos.porque.strip()
    uow.db.flush()
    return {"id": str(fila.id), "estado": fila.estado, "porque": fila.porque}


class EnvioLegado(BaseModel):
    cuerpo: str = Field(..., min_length=1, description="Lo que se manda, tal cual")
    accion: str = Field(
        "",
        description=(
            "La `SOAPAction`, cuando el servicio la exige. Vacía NO es lo mismo que "
            "ausente: hay servidores que rechazan la petición sin ella y el error "
            "que dan no lo dice"
        ),
    )


@router.post(
    "/conexiones/{conexion_id}/enviar",
    response_model=dict,
    dependencies=[Depends(exige_permiso("integracion:invocar"))],
    summary="Mandar algo por un transporte heredado (SOAP o AMQP)",
    description=(
        "La otra mitad de los transportes heredados. `publicar_amqp` y "
        "`envolver_soap` estaban escritas, probadas y **sin que las llamara "
        "nadie**: se podía declarar una conexión AMQP y no había forma de "
        "publicar en ella. Una integración que sólo sabe leer deja al cliente "
        "escribiendo en el ERP a mano, que es la mitad del trabajo que venía a "
        "quitar.\n\n"
        "Por un transporte de sólo lectura —sftp, fichero, edi— **se dice que no** "
        "en vez de aceptar la petición y no mandar nada."
    ),
)
def enviar_por_transporte(
    conexion_id: UUID, datos: EnvioLegado, db: DbDep, principal: AutenticadoDep
) -> Any:
    from services.integration import transportes_legado as legado

    conexion = _conexion(db, principal.tenant_id, conexion_id)
    return legado.enviar_programado(
        str(conexion.protocolo or ""),
        dict(conexion.config or {}),
        {"accion": datos.accion} if datos.accion else {},
        datos.cuerpo,
    )


montar_listado(
    router,
    modelo=RegistroRecibido,
    objeto="registro_recibido",
    permiso="integracion:read",
    ruta="/registros-recibidos",
    nombre="Registros recibidos",
)


ROUTERS = [router]


# ── La ficha del registro ─────────────────────────────────────────────────
# Sin ella, las acciones que cuelgan de un registro no se alcanzan desde
# ninguna pantalla: existen, se prueban y nadie las usa.
montar_ficha(
    router,
    modelo=Conexion,
    objeto="conexion",
    permiso_leer="integracion:read",
    permiso_escribir="integracion:write",
    nombre="Conexiones",
    ruta="/conexiones",
    parametro="conexion_id",
)
