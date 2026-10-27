"""API de encargos seguidos (CRM-00.04.05.01 a .04, .06 a .10)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from crmcore.http.listados import aplicar_filtros_de_la_url, declarar_recurso
from crmcore.http.pagination import PaginaDeListado, paginar_consulta
from crmcore.http.parametros import admite_parametros_abiertos
from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from services.integration import encargos as enc

router = APIRouter(prefix="/encargos", tags=["encargos seguidos"])
declarar_recurso(router, "encargo", enc.Encargo)
router_proveedores = APIRouter(prefix="/proveedores-servicio", tags=["encargos seguidos"])
declarar_recurso(router_proveedores, "proveedor_servicio")


# ── Proveedores y reglas ──────────────────────────────────────────────────


class CrearProveedor(BaseModel):
    clave: str = Field(..., min_length=1, max_length=60, examples=["gls"])
    nombre: str = Field(..., min_length=1, max_length=200)
    modulo: str | None = None
    conexion_id: UUID | None = Field(
        None, description="Conexión declarativa por la que se le llama y se le sondea"
    )
    mapa_estados: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Estado del proveedor → estado del sistema. Va aquí y no en el "
            "código: traducirlo en el código significa tocar el producto por "
            "cada transportista nuevo"
        ),
        examples=[
            {"ENTREGADO": "completado", "EN_REPARTO": "en_entrega", "INCIDENCIA": "incidencia"}
        ],
    )
    plazo_horas: int | None = Field(None, ge=1, description="Plazo prometido, en horas")
    silencio_horas: int = Field(
        48, ge=1, description="Horas sin novedad a partir de las cuales el encargo se da por mudo"
    )
    coste_base: Decimal | None = None


class ProveedorOut(BaseModel):
    id: UUID
    clave: str
    nombre: str
    modulo: str | None = None
    conexion_id: UUID | None = None
    mapa_estados: dict[str, Any] = {}
    plazo_horas: int | None = None
    silencio_horas: int
    activo: bool

    model_config = {"from_attributes": True}


@router_proveedores.post(
    "",
    response_model=ProveedorOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("integracion:write"))],
    summary="Dar de alta un proveedor al que se le encargan cosas",
    description=(
        "Un transportista, un instalador, un perito. Lo que cambia entre uno y "
        "otro es la conexión, el mapa de estados y el plazo: **no hay código por "
        "proveedor**, porque con él cada cliente con un transportista distinto "
        "sería una versión del producto."
    ),
)
def crear_proveedor(datos: CrearProveedor, db: DbDep, principal: AutenticadoDep) -> Any:
    fila = enc.Proveedor(tenant_id=principal.tenant_id, **datos.model_dump())
    db.add(fila)
    db.flush()
    return fila


@router_proveedores.get(
    "",
    response_model=PaginaDeListado,
    dependencies=[Depends(exige_permiso("integracion:read"))],
    summary="Proveedores configurados",
)
def listar_proveedores(
    request: Request,
    db: DbDep,
    principal: AutenticadoDep,
    limite: int = Query(50, ge=1, le=200),
    cursor: str = Query(""),
) -> Any:
    consulta = select(enc.Proveedor).where(enc.Proveedor.tenant_id == principal.tenant_id)
    # Y los filtros comunes, con sus rangos. Estar escrito a mano no es motivo
    # para quedarse sin ellos: entonces el mismo producto admite
    # `?vence_at__hasta=…` o no según quién escribió cada listado, y eso lo
    # descubre el integrador probando.
    consulta = aplicar_filtros_de_la_url(
        request, enc.Proveedor, consulta, principal=principal, db=db, objeto="proveedor_servicio"
    )
    return paginar_consulta(
        db,
        enc.Proveedor,
        consulta,
        limite=limite,
        cursor=cursor,
        orden="clave",
        modelo_salida=ProveedorOut,
    )


class CrearRegla(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=150)
    prioridad: int = 100
    condiciones: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Misma gramática que el reparto de leads y casos",
        examples=[[{"atributo": "encargo.pais", "operador": "=", "valor": "PT"}]],
    )
    proveedor: str = Field(..., min_length=1, max_length=60)
    alternativos: list[str] = Field(
        default_factory=list,
        description=(
            "A quién ir si el primero no puede. Sin alternativa, una caída del "
            "transportista habitual para la operación entera"
        ),
    )


class ReglaOut(BaseModel):
    id: UUID
    nombre: str
    prioridad: int
    activa: bool
    condiciones: list[Any] = []
    proveedor: str
    alternativos: list[Any] = []

    model_config = {"from_attributes": True}


@router_proveedores.post(
    "/reglas",
    response_model=ReglaOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("integracion:write"))],
    summary="Regla de elección de proveedor",
)
def crear_regla(datos: CrearRegla, db: DbDep, principal: AutenticadoDep) -> Any:
    fila = enc.ReglaProveedor(tenant_id=principal.tenant_id, **datos.model_dump())
    db.add(fila)
    db.flush()
    return fila


@router_proveedores.post(
    "/simular",
    dependencies=[Depends(exige_permiso("integracion:read"))],
    summary="A qué proveedor iría este encargo",
    description=(
        "Sin crear nada. Es lo que permite cambiar una regla y comprobarlo antes "
        "de que se note en los envíos reales, y dice **qué regla** ganó: una "
        "elección que no se puede explicar no se puede corregir."
    ),
)
def simular(datos: dict[str, Any], db: DbDep, principal: AutenticadoDep) -> Any:
    proveedor, alternativos, regla = enc.elegir_proveedor(db, principal.tenant_id, datos)
    return {"proveedor": proveedor, "alternativos": alternativos, "regla": regla}


# ── Encargos ──────────────────────────────────────────────────────────────


class CrearEncargo(BaseModel):
    proveedor: str = Field(
        "", description="Vacío: lo eligen las reglas. Con valor: se fuerza ese proveedor"
    )
    referencia_externa: str | None = Field(
        None, max_length=120, description="La del proveedor, si ya se conoce al crear"
    )
    objeto_origen: str | None = Field(None, examples=["pedido", "caso"])
    objeto_origen_id: UUID | None = None
    cuenta_id: UUID | None = None
    contacto_id: UUID | None = None
    prometido_para: datetime | None = None
    datos: dict[str, Any] = Field(
        default_factory=dict,
        description="Lo propio del sector, que pone el módulo vertical",
        examples=[{"bultos": 3, "peso_kg": 14.2, "destino_cp": "08007"}],
    )


class EncargoOut(BaseModel):
    id: UUID
    proveedor: str
    referencia_propia: str
    referencia_externa: str | None = None
    estado: str
    estado_proveedor: str | None = None
    prometido_para: datetime | None = None
    completado_at: datetime | None = None
    ultima_novedad_at: datetime | None = None
    mudo: bool
    cuenta_id: UUID | None = None
    contacto_id: UUID | None = None
    # De qué registro salió el encargo: sin esto, una lista de encargos no
    # lleva a ninguna parte y hay que buscar a mano a qué oportunidad o a qué
    # caso pertenece cada uno.
    objeto_origen: str | None = None
    objeto_origen_id: UUID | None = None
    # Lo previsto contra lo facturado, que es de lo que va la conciliación.
    # Estaban en la tabla y no salían, así que la pantalla podía listar
    # encargos y no podía decir cuánto costaban.
    coste_previsto: Decimal | None = None
    coste_facturado: Decimal | None = None
    moneda: str | None = None
    # Lo que no se le enseña al cliente —coste, notas, proveedor alternativo y
    # por qué se eligió éste—: es un objeto, no un interruptor. Estaba
    # declarado `bool` y la columna es JSONB, así que **crear un encargo
    # respondía 500 al serializar**, con la fila ya escrita y su hito
    # apuntado. No lo cazó el barrido de escrituras porque esta ruta exige un
    # proveedor configurado: en un tenant vacío contesta 404 y no llega a
    # serializar nada. Hizo falta una empresa sembrada de verdad.
    interno: dict[str, Any] = {}
    datos: dict[str, Any] = {}
    created_at: datetime

    model_config = {"from_attributes": True}


@router.post(
    "",
    response_model=EncargoOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("integracion:write"))],
    summary="Encargar algo a un tercero y empezar a seguirlo",
)
def crear(datos: CrearEncargo, uow: UowDep) -> Any:
    campos = datos.model_dump()
    proveedor = campos.pop("proveedor", "") or ""
    return enc.crear(uow, proveedor=proveedor, **campos)


@router.get(
    "",
    response_model=PaginaDeListado,
    dependencies=[Depends(exige_permiso("integracion:read"))],
    summary="Encargos en seguimiento",
)
def listar(
    request: Request,
    db: DbDep,
    principal: AutenticadoDep,
    estado: str = Query(""),
    proveedor: str = Query(""),
    solo_mudos: bool = Query(False, description="Los que el proveedor lleva tiempo sin mover"),
    limite: int = Query(100, ge=1, le=500),
    cursor: str = Query(""),
) -> Any:
    consulta = select(enc.Encargo).where(enc.Encargo.tenant_id == principal.tenant_id)
    if estado:
        consulta = consulta.where(enc.Encargo.estado == estado)
    if proveedor:
        consulta = consulta.where(enc.Encargo.proveedor == proveedor)
    if solo_mudos:
        consulta = consulta.where(enc.Encargo.mudo.is_(True))
    # Y los filtros comunes, con sus rangos. Estar escrito a mano no es motivo
    # para quedarse sin ellos: entonces el mismo producto admite
    # `?vence_at__hasta=…` o no según quién escribió cada listado, y eso lo
    # descubre el integrador probando.
    consulta = aplicar_filtros_de_la_url(
        request, enc.Encargo, consulta, principal=principal, db=db, objeto="encargo"
    )
    return paginar_consulta(
        db, enc.Encargo, consulta, limite=limite, cursor=cursor, modelo_salida=EncargoOut
    )


class EventoProveedor(BaseModel):
    proveedor: str = Field(..., min_length=1)
    referencia_externa: str = ""
    referencia_propia: str = ""
    estado_proveedor: str = Field(..., description="Tal cual lo dice él, sin traducir")
    ocurrio_at: datetime | None = Field(
        None, description="Cuándo pasó según el proveedor, que no es cuándo nos enteramos"
    )
    id_externo: str = Field(
        "",
        description="Identificador del evento en su sistema. Es lo que hace la ingesta idempotente",
    )
    descripcion: str = ""
    lugar: str = ""
    crudo: dict[str, Any] = Field(default_factory=dict)


@router.post(
    "/eventos",
    dependencies=[Depends(exige_permiso("integracion:write"))],
    summary="Ingerir un evento del proveedor (webhook o sondeo)",
    description=(
        "La misma puerta para las dos vías: un transportista que empuja webhooks "
        "y otro al que hay que sondear tienen que acabar en el mismo hito, o "
        "cada informe dependería de cómo se enteró el sistema.\n\n"
        "**Idempotente** por `id_externo`: las pasarelas reintentan, y sin esto "
        "un reintento duplicaría el hito.\n\n"
        "**Ordenada**: un evento anterior al estado actual se guarda pero no se "
        "aplica. Guardarlo importa —es la prueba de lo que dijo el proveedor— y "
        "no aplicarlo también, porque un paquete que retrocede en la pantalla es "
        "una llamada al servicio de atención."
    ),
)
def ingerir(datos: EventoProveedor, uow: UowDep) -> Any:
    return enc.ingerir(uow, **datos.model_dump())


@router.get(
    "/estados-sin-mapear",
    dependencies=[Depends(exige_permiso("integracion:read"))],
    summary="Estados que llegan y no sabemos traducir",
    description=(
        "La lista que hay que mirar al integrar un proveedor nuevo: cada entrada "
        "es un evento que se guardó y no hizo nada, y el seguimiento del cliente "
        "se quedó parado sin que nadie fallara."
    ),
)
def sin_mapear(db: DbDep, principal: AutenticadoDep, dias: int = Query(30, ge=1, le=365)) -> Any:
    return enc.estados_sin_mapear(db, principal.tenant_id, dias=dias)


class AbrirIncidencia(BaseModel):
    tipo: str = Field(..., min_length=1, max_length=120, examples=["retraso/aduana"])
    descripcion: str = ""
    responsable: str = Field(
        "sin_determinar",
        description=(
            "De quién fue. Decide dos cosas distintas: si se le reclama al "
            "proveedor y si cuenta en su cumplimiento"
        ),
    )
    caso_id: UUID | None = Field(
        None, description="Caso de soporte que la atiende. Se enlaza, no se duplica"
    )


@router.post(
    "/{encargo_id}/incidencias",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("integracion:write"))],
    summary="Abrir una incidencia sobre el encargo",
)
def abrir_incidencia(encargo_id: UUID, datos: AbrirIncidencia, uow: UowDep) -> Any:
    fila = enc.abrir_incidencia(uow, encargo_id, **datos.model_dump())
    return {"id": str(fila.id), "tipo": fila.tipo, "responsable": fila.responsable}


class ResolverIncidencia(BaseModel):
    responsable: str = ""
    coste_asumido: Decimal | None = None


@router.post(
    "/incidencias/{incidencia_id}/resolver",
    dependencies=[Depends(exige_permiso("integracion:write"))],
    summary="Cerrar una incidencia",
)
def resolver_incidencia(incidencia_id: UUID, datos: ResolverIncidencia, uow: UowDep) -> Any:
    fila = enc.resolver_incidencia(uow, incidencia_id, **datos.model_dump())
    return {"id": str(fila.id), "abierta": fila.abierta, "responsable": fila.responsable}


@router.post(
    "/revisar-silencios",
    dependencies=[Depends(exige_permiso("integracion:write"))],
    summary="Marcar los encargos de los que el proveedor no dice nada",
    description=(
        "El fallo más caro de una integración de seguimiento no es el error: es "
        "el silencio. Un envío del que el transportista no dice nada durante "
        "cuatro días parece que va bien —en la pantalla pone «en tránsito»— y no "
        "va bien.\n\n"
        "Lo llama el programador del tenant. Si no hay encargos abiertos dice "
        "que **no es medible**, no que todo va bien: un verde vacío se lee igual "
        "que uno ganado."
    ),
)
def revisar_silencios(uow: UowDep, principal: AutenticadoDep) -> Any:
    return enc.revisar_silencios(uow, principal.tenant_id)


# ── Lo que ve el cliente (CRM-00.04.05.06) ────────────────────────────────


@router.get(
    "/{encargo_id}/seguimiento",
    dependencies=[Depends(exige_permiso("integracion:read"))],
    summary="El seguimiento tal como se le enseña al cliente",
    description=(
        "**El coste, el proveedor alternativo y las notas internas no salen**, y "
        "eso lo decide el servidor: si dependiera del front, bastaría una "
        "pantalla nueva que se olvidara de filtrar para enseñarle al cliente lo "
        "que nos cuesta su envío.\n\n"
        "`cuenta_id` es el ámbito del cliente, ya resuelto por el portal —el "
        "portal vive en otro servicio y ningún servicio lee el esquema de otro—. "
        "Un encargo de otra cuenta da **404 y no 403**: un 403 confirma que ese "
        "encargo existe, y con eso se puede recorrer la base preguntando por "
        "referencias."
    ),
)
def seguimiento(
    encargo_id: UUID,
    db: DbDep,
    principal: AutenticadoDep,
    cuenta_id: UUID | None = Query(None),
) -> Any:
    return enc.seguimiento_para_cliente(db, principal.tenant_id, encargo_id, cuenta_id=cuenta_id)


# ── Conciliación y cumplimiento ───────────────────────────────────────────


class Conciliar(BaseModel):
    proveedor: str = Field(..., min_length=1)
    lineas: list[dict[str, Any]] = Field(
        ...,
        description="Las líneas de su factura: referencia e importe",
        examples=[[{"referencia": "GLS-99", "importe": "12.40"}]],
    )
    tolerancia: Decimal = Decimal("0.01")


@router.post(
    "/conciliar",
    dependencies=[Depends(exige_permiso("integracion:write"))],
    summary="Comparar lo facturado con lo entregado",
    description=(
        "Las tres diferencias salen **por separado** porque llevan a tres "
        "acciones distintas: lo facturado de más se reclama, lo facturado sin "
        "entregar se investiga, y lo entregado sin facturar se provisiona."
    ),
)
def conciliar(datos: Conciliar, uow: UowDep) -> Any:
    return enc.conciliar(uow, **datos.model_dump())


@router.get(
    "/cumplimiento",
    dependencies=[Depends(exige_permiso("integracion:read"))],
    summary="Cumplimiento por proveedor",
    description=(
        "La tabla con la que se renegocia un contrato. Cuenta **solo lo que es "
        "suyo**: una incidencia cuya culpa fue del cliente o nuestra no cuenta "
        "contra el proveedor, porque un número que no se puede defender en una "
        "reunión no se usa.\n\n"
        "Un proveedor sin encargos completados sale como **no medible**, no con "
        "un 100 %: recién contratado, no ha demostrado nada."
    ),
)
def cumplimiento(
    db: DbDep,
    principal: AutenticadoDep,
    desde: date = Query(...),
    hasta: date = Query(...),
) -> Any:
    return enc.cumplimiento_proveedor(db, principal.tenant_id, desde=desde, hasta=hasta)


class ArchivarDocumento(BaseModel):
    documento_id: str = Field(..., min_length=1)
    rol: str = Field("prueba_entrega", examples=["prueba_entrega"])
    titulo: str = ""
    tipo: str = ""
    sistema: str = "contecmind"


@router.post(
    "/{encargo_id}/documentos",
    response_model=dict,
    dependencies=[Depends(exige_permiso("integracion:write"))],
    summary="Archivar la prueba de entrega del encargo",
    description=(
        "El albarán, el POD, la foto de la entrega. **Por referencia al gestor "
        "documental**, no copiados: una copia en el CRM sobrevive al borrado en el "
        "origen, y entonces conservamos un documento que el cliente cree "
        "eliminado.\n\n"
        "Hay que hacerlo pronto. Casi todos los transportistas conservan la prueba "
        "unas semanas y luego la borran: cuando el cliente llame diciendo que no "
        "le llegó, ya no se la podremos pedir a nadie."
    ),
)
def archivar_documento(
    encargo_id: UUID, datos: ArchivarDocumento, uow: UowDep, principal: AutenticadoDep
) -> Any:
    return enc.archivar_documento(
        uow,
        encargo_id,
        documento_id=datos.documento_id,
        rol=datos.rol,
        titulo=datos.titulo,
        tipo=datos.tipo,
        sistema=datos.sistema,
        por=principal.id,
    )


@router.get(
    "/entregados-sin-prueba",
    response_model=dict,
    dependencies=[Depends(exige_permiso("integracion:read"))],
    summary="Qué se dio por entregado sin dejar prueba archivada",
    description=(
        "Es la lista que hay que mirar **antes** de que el cliente llame diciendo "
        "que no le llegó. Entonces ya no se puede pedir la prueba al "
        "transportista: casi todos la conservan unas semanas y luego la borran, y "
        "lo que queda es la palabra de uno contra la del otro."
    ),
)
def entregados_sin_prueba(
    db: DbDep, principal: AutenticadoDep, dias: int = Query(30, ge=1, le=365)
) -> Any:
    return enc.entregados_sin_prueba(db, principal.tenant_id, dias=dias)


ROUTERS_ENCARGOS = [router_proveedores, router]


# Estas rutas aceptan además los filtros comunes, cuyos nombres son columnas
# del modelo y cambian con él: no se pueden declarar. Los valida
# `aplicar_filtros_de_la_url`, que rechaza lo que no es columna o lo que este
# principal no ve en claro. Las dos mitades van juntas: con el filtro y sin la
# marca, la ruta contesta 422 a sus propios filtros.
admite_parametros_abiertos(
    listar_proveedores, "llama a `aplicar_filtros_de_la_url`, que valida los filtros por columna"
)
admite_parametros_abiertos(
    listar, "llama a `aplicar_filtros_de_la_url`, que valida los filtros por columna"
)
