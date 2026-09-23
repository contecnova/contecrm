"""API de catálogo, precios, presupuestos, contratos y suscripciones
(CRM-03.03.02)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from crmcore.http.listados import montar_listado
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from services.sales import catalogo as cat
from services.sales import presupuestos as pre
from services.sales.catalogo import ListaPrecio
from services.sales.presupuestos import Contrato, Pedido, Presupuesto, SuscripcionCliente

router_prod = APIRouter(prefix="/productos", tags=["catálogo"])
router_precios = APIRouter(prefix="/listas-precio", tags=["catálogo"])
router_pre = APIRouter(prefix="/presupuestos", tags=["cotización"])
router_ctr = APIRouter(prefix="/contratos", tags=["contratación"])
router_sus = APIRouter(prefix="/suscripciones", tags=["contratación"])
router_ped = APIRouter(prefix="/pedidos", tags=["contratación"])


# ── Catálogo ──────────────────────────────────────────────────────────────


class CrearProducto(BaseModel):
    sku: str = Field(..., min_length=1, max_length=80)
    nombre: str = Field(..., min_length=1, max_length=300)
    descripcion: str = ""
    familia: str | None = None
    tipo_ingreso: str = Field("puntual", description="puntual · recurrente")
    periodicidad: str | None = None
    unidad: str = "ud"
    precio_base: Decimal = Field(
        Decimal(0), description="El punto de partida, no el precio final: encima van las listas"
    )
    moneda: str = "EUR"
    coste: Decimal | None = Field(
        None,
        description=(
            "Nulo cuando no se conoce. Un cero fingido daría un margen del 100 % "
            "que nadie cuestionaría"
        ),
    )
    margen_minimo_pct: Decimal | None = None
    atributos: dict[str, Any] = Field(default_factory=dict)


class ProductoOut(BaseModel):
    id: UUID
    sku: str
    nombre: str
    familia: str | None = None
    tipo_ingreso: str
    precio_base: Decimal
    moneda: str
    activo: bool

    model_config = {"from_attributes": True}


@router_prod.post(
    "",
    response_model=ProductoOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("producto:write"))],
    summary="Dar de alta un producto",
)
def crear_producto(datos: CrearProducto, db: DbDep, principal: AutenticadoDep) -> Any:
    fila = cat.Producto(tenant_id=principal.tenant_id, **datos.model_dump())
    db.add(fila)
    db.flush()
    return fila


@router_prod.get(
    "",
    response_model=list[ProductoOut],
    dependencies=[Depends(exige_permiso("producto:read"))],
    summary="Catálogo del tenant",
)
def listar_productos(
    db: DbDep,
    principal: AutenticadoDep,
    familia: str = Query(""),
    solo_activos: bool = Query(True),
    limite: int = Query(200, ge=1, le=1000),
) -> Any:
    consulta = select(cat.Producto).where(cat.Producto.tenant_id == principal.tenant_id)
    if familia:
        consulta = consulta.where(cat.Producto.familia == familia)
    if solo_activos:
        consulta = consulta.where(cat.Producto.activo.is_(True))
    return list(db.execute(consulta.order_by(cat.Producto.sku).limit(limite)).scalars().all())


class CrearRelacion(BaseModel):
    producto_id: UUID
    relacion: str = Field(..., description="requiere · excluye · incluye · sugiere")
    otro_id: UUID
    cantidad: Decimal = Decimal(1)
    motivo: str = Field(
        "",
        description=(
            "Se enseña cuando la configuración falla. Un «no se puede» sin motivo "
            "hace que quien está con el cliente delante lo salte por otro camino"
        ),
    )


@router_prod.post(
    "/relaciones",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("producto:write"))],
    summary="Declarar qué va con qué",
)
def crear_relacion(datos: CrearRelacion, db: DbDep, principal: AutenticadoDep) -> Any:
    if datos.relacion not in cat.RELACIONES:
        from crmcore.errors import ErrorValidacion

        raise ErrorValidacion(
            f"Relación «{datos.relacion}» no válida.",
            error_code="catalogo.relacion_no_valida",
            detalle={"validas": list(cat.RELACIONES)},
        )
    fila = cat.RelacionProducto(tenant_id=principal.tenant_id, **datos.model_dump())
    db.add(fila)
    db.flush()
    return {"id": str(fila.id)}


class ComprobarConfiguracion(BaseModel):
    lineas: list[dict[str, Any]]


@router_prod.post(
    "/comprobar-configuracion",
    dependencies=[Depends(exige_permiso("producto:read"))],
    summary="¿Se pueden vender juntos?",
    description=(
        "Devuelve problemas y sugerencias **por separado**, y no bloquea por las "
        "segundas: una regla `sugiere` que impidiera guardar convertiría una "
        "recomendación comercial en un obstáculo, y lo que se hace entonces es "
        "borrarla del catálogo."
    ),
)
def comprobar_configuracion(
    datos: ComprobarConfiguracion, db: DbDep, principal: AutenticadoDep
) -> Any:
    return cat.comprobar_configuracion(db, principal.tenant_id, datos.lineas)


class CrearLista(BaseModel):
    clave: str = Field(..., min_length=1, max_length=80)
    nombre: str = Field(..., min_length=1, max_length=200)
    moneda: str = "EUR"
    cuenta_id: UUID | None = Field(None, description="Vacío: vale para cualquiera")
    canal: str | None = None
    desde: date | None = None
    hasta: date | None = None
    prioridad: int = Field(
        100,
        description=(
            "Cuando dos listas encajan gana la de prioridad más baja. Declararlo "
            "evita que el precio dependa del orden de inserción en la base"
        ),
    )


@router_precios.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("producto:write"))],
    summary="Crear una lista de precios",
)
def crear_lista(datos: CrearLista, db: DbDep, principal: AutenticadoDep) -> Any:
    fila = cat.ListaPrecio(tenant_id=principal.tenant_id, **datos.model_dump())
    db.add(fila)
    db.flush()
    return {"id": str(fila.id), "clave": fila.clave}


class CrearReglaPrecio(BaseModel):
    lista_id: UUID
    nombre: str = ""
    prioridad: int = 100
    producto_id: UUID | None = None
    familia: str | None = None
    desde_cantidad: Decimal = Field(Decimal(0), description="Escalado por volumen")
    condiciones: list[dict[str, Any]] = Field(
        default_factory=list, description="Misma gramática que el reparto de leads y casos"
    )
    accion: str = Field(
        ...,
        description="fijar · descuento_pct · descuento_importe · recargo_pct · recargo_importe",
    )
    valor: Decimal = Decimal(0)
    exclusiva: bool = Field(
        False,
        description=(
            "Corta el paso a las siguientes. Hace falta para los precios cerrados "
            "por contrato: sin ella, una promoción posterior podría bajar un "
            "precio pactado y nadie lo vería hasta la factura"
        ),
    )


@router_precios.post(
    "/reglas",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("producto:write"))],
    summary="Añadir una regla de precio",
)
def crear_regla(datos: CrearReglaPrecio, db: DbDep, principal: AutenticadoDep) -> Any:
    if datos.accion not in cat.ACCIONES:
        from crmcore.errors import ErrorValidacion

        raise ErrorValidacion(
            f"Acción «{datos.accion}» no válida.",
            error_code="catalogo.accion_no_valida",
            detalle={"validas": list(cat.ACCIONES)},
        )
    fila = cat.ReglaPrecio(tenant_id=principal.tenant_id, **datos.model_dump())
    db.add(fila)
    db.flush()
    return {"id": str(fila.id)}


@router_precios.get(
    "/calcular",
    dependencies=[Depends(exige_permiso("producto:read"))],
    summary="Qué le cobramos a este cliente por esto",
    description=(
        "Devuelve el precio **y qué reglas lo produjeron, en orden**. Un precio "
        "que no se puede explicar se discute con el cliente delante, y entonces "
        "se acaba dando el descuento igual.\n\n"
        "Cuando no se aplicó ninguna regla lo dice (`de_catalogo`): es la "
        "diferencia entre «le cobramos su tarifa» y «le cobramos la de catálogo "
        "porque no tiene tarifa»."
    ),
)
def calcular(
    db: DbDep,
    principal: AutenticadoDep,
    producto_id: UUID = Query(...),
    cantidad: Decimal = Query(Decimal(1)),
    cuenta_id: UUID | None = Query(None),
    canal: str = Query(""),
    moneda: str = Query(""),
) -> Any:
    return cat.calcular_precio(
        db,
        principal.tenant_id,
        producto_id=producto_id,
        cantidad=cantidad,
        cuenta_id=cuenta_id,
        canal=canal,
        moneda=moneda,
    )


# ── Presupuestos ──────────────────────────────────────────────────────────


class LineaEntrada(BaseModel):
    producto_id: UUID | None = None
    descripcion: str = ""
    cantidad: Decimal = Decimal(1)
    descuento_pct: Decimal = Decimal(0)
    precio_unitario: Decimal | None = Field(
        None, description="Solo para líneas libres, sin producto de catálogo"
    )
    coste_unitario: Decimal | None = None


class CrearPresupuesto(BaseModel):
    lineas: list[LineaEntrada] = Field(..., min_length=1)
    cuenta_id: UUID | None = None
    oportunidad_id: UUID | None = None
    contacto_id: UUID | None = None
    titulo: str = ""
    moneda: str = "EUR"
    canal: str = ""
    idioma: str = "es"
    marca: str = ""
    dias_validez: int = Field(30, ge=1, le=365)
    notas: str = ""
    condiciones: str = ""


@router_pre.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("quote:write"))],
    summary="Crear un presupuesto",
    description=(
        "El precio **no lo pone quien llama**: lo calcula el motor y el "
        "presupuesto guarda la explicación. Si lo trajera el llamante, el precio "
        "dependería de la pantalla que se usara, y dos canales darían dos números "
        "para el mismo cliente."
    ),
)
def crear_presupuesto(datos: CrearPresupuesto, uow: UowDep) -> Any:
    campos = datos.model_dump()
    lineas = campos.pop("lineas")
    fila = pre.crear(uow, lineas=lineas, **campos)
    return {
        "id": str(fila.id),
        "numero": fila.numero,
        "version": fila.version,
        "total": str(fila.total),
        "margen_pct": str(fila.margen_pct) if fila.margen_pct is not None else None,
    }


class NuevaVersion(BaseModel):
    lineas: list[LineaEntrada] | None = Field(
        None, description="Sin líneas se copian las de la versión anterior, sin recalcular precios"
    )
    titulo: str | None = None
    notas: str | None = None
    condiciones: str | None = None
    valido_hasta: date | None = None


@router_pre.post(
    "/{presupuesto_id}/versiones",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("quote:write"))],
    summary="Sacar la versión siguiente",
    description=(
        "**La anterior no se toca.** Editar en sitio hace imposible responder a "
        "«esto no es lo que me mandaste», que es la conversación que de verdad "
        "ocurre. La anterior queda `sustituido`, no borrada: sigue siendo lo que "
        "el cliente tiene en su correo."
    ),
)
def nueva_version(presupuesto_id: UUID, datos: NuevaVersion, uow: UowDep) -> Any:
    campos = {k: v for k, v in datos.model_dump().items() if v is not None}
    lineas = campos.pop("lineas", None)
    fila = pre.nueva_version(uow, presupuesto_id, lineas=lineas, **campos)
    return {"id": str(fila.id), "numero": fila.numero, "version": fila.version}


@router_pre.get(
    "/{presupuesto_id}/cambios",
    dependencies=[Depends(exige_permiso("quote:read"))],
    summary="Qué cambió respecto de la versión anterior",
    description=(
        "Se calcula al pedirlo y no se guarda: una diferencia guardada se queda "
        "desfasada en cuanto alguien corrige una línea, y entonces miente con "
        "toda la apariencia de ser un dato."
    ),
)
def cambios(presupuesto_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return pre.comparar_versiones(db, principal.tenant_id, presupuesto_id)


@router_pre.get(
    "/{presupuesto_id}/politica-descuento",
    dependencies=[Depends(exige_permiso("quote:read"))],
    summary="¿Puede salir solo o necesita aprobación?",
    description=(
        "Mira **las dos cosas**: el descuento sobre tarifa y el margen que queda. "
        "Un 20 % sobre un producto con 60 puntos de margen y un 20 % sobre uno "
        "con 12 son cosas distintas, y una matriz que solo mire el porcentaje "
        "aprueba la segunda sin que nadie se entere.\n\n"
        "Cuando el margen **no se sabe** se exige aprobación y se dice que es por "
        "eso: tratar «no lo sé» como «está bien» es cómo se firma un presupuesto "
        "que pierde dinero."
    ),
)
def politica_descuento(presupuesto_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    fila = db.get(pre.Presupuesto, presupuesto_id)
    if fila is None or fila.tenant_id != principal.tenant_id:
        from crmcore.errors import NoEncontrado

        raise NoEncontrado("El presupuesto no existe", error_code="presupuesto.no_encontrado")
    return pre.politica_de_descuento(db, principal.tenant_id, fila)


@router_pre.post(
    "/{presupuesto_id}/enviar",
    dependencies=[Depends(exige_permiso("quote:write"))],
    summary="Mandar el presupuesto al cliente",
    description=(
        "El control de la matriz de descuentos está **aquí y no en la pantalla**: "
        "si dependiera del front, bastaría una integración que llamara a la API "
        "para saltársela entera."
    ),
)
def enviar(presupuesto_id: UUID, uow: UowDep) -> Any:
    return pre.enviar(uow, presupuesto_id)


@router_pre.post(
    "/{presupuesto_id}/aceptar",
    dependencies=[Depends(exige_permiso("quote:write"))],
    summary="El cliente acepta: nace el pedido",
    description=(
        "Se comprueba la vigencia. Aceptar un presupuesto caducado sin decir nada "
        "es cómo se sirve a precio de hace un año, y el descubrimiento llega con "
        "la factura."
    ),
)
def aceptar(presupuesto_id: UUID, uow: UowDep) -> Any:
    pedido = pre.aceptar(uow, presupuesto_id)
    return {"pedido_id": str(pedido.id), "numero": pedido.numero, "total": str(pedido.total)}


@router_pre.get(
    "/{presupuesto_id}/documento",
    dependencies=[Depends(exige_permiso("quote:read"))],
    summary="Los datos para componer el PDF",
    description=(
        "Devuelve **datos y no un PDF**: la maquetación, la marca y el idioma son "
        "del generador documental, común a toda la suite. Generar el binario aquí "
        "metería tipografías y plantillas dentro del servicio de ventas y "
        "obligaría a desplegarlo para cambiar un logotipo.\n\n"
        "**El coste y el margen no salen.** Es el error más caro que se puede "
        "cometer al componer una oferta, y por eso se decide en el servidor y no "
        "en la plantilla."
    ),
)
def documento(presupuesto_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return pre.documento(db, principal.tenant_id, presupuesto_id)


@router_pre.post(
    "/caducar-vencidos",
    dependencies=[Depends(exige_permiso("quote:write"))],
    summary="Marcar caducados los que pasaron su vigencia",
    description=(
        "Un presupuesto que sigue diciendo «enviado» seis meses después aparece "
        "en el pipeline como negocio vivo, y la previsión lo cuenta."
    ),
)
def caducar(uow: UowDep, principal: AutenticadoDep) -> Any:
    return pre.caducar_vencidos(uow, principal.tenant_id)


# ── Contratos (CRM-03.03.02.08, CRM-03.03.02.10) ──────────────────────────
# ── Contratos ─────────────────────────────────────────────────────────────


class CrearContrato(BaseModel):
    cuenta_id: UUID
    inicio: date
    fin: date | None = None
    presupuesto_id: UUID | None = None
    titulo: str = ""
    importe: Decimal = Decimal(0)
    moneda: str = "EUR"
    renovacion_automatica: bool = False
    preaviso_dias: int = Field(
        30,
        ge=0,
        description="El día del vencimiento ya es tarde para no renovar: esta es la fecha que importa",
    )
    meses_renovacion: int = Field(12, ge=1)
    clausulas: list[dict[str, Any]] = Field(default_factory=list)


@router_ctr.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("contract:write"))],
    summary="Dar de alta un contrato",
)
def crear_contrato(datos: CrearContrato, uow: UowDep) -> Any:
    fila = pre.crear_contrato(uow, **datos.model_dump())
    return {"id": str(fila.id), "numero": fila.numero, "fin": str(fila.fin) if fila.fin else None}


@router_ctr.post(
    "/revisar-renovaciones",
    dependencies=[Depends(exige_permiso("contract:write"))],
    summary="Avisar de los preavisos y renovar lo que toca",
    description=(
        "Los contratos **sin** renovación automática también avisan. Son los que "
        "se olvidan: nadie los renueva y el cliente se va sin que nadie lo haya "
        "decidido."
    ),
)
def revisar_renovaciones(uow: UowDep, principal: AutenticadoDep) -> Any:
    return pre.revisar_renovaciones(uow, principal.tenant_id)


# ── Suscripciones ─────────────────────────────────────────────────────────


class AltaSuscripcion(BaseModel):
    cuenta_id: UUID
    plan: str = Field(..., min_length=1, max_length=120)
    importe_periodo: Decimal
    inicio: date
    periodicidad: str = Field("mensual", description="mensual · trimestral · anual")
    contrato_id: UUID | None = None
    producto_id: UUID | None = None
    cantidad: Decimal = Decimal(1)
    moneda: str = "EUR"


@router_sus.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("contract:write"))],
    summary="Alta de suscripción",
)
def alta_suscripcion(datos: AltaSuscripcion, uow: UowDep) -> Any:
    fila = pre.alta_suscripcion(uow, **datos.model_dump())
    return {"id": str(fila.id), "plan": fila.plan, "estado": fila.estado}


class CambioSuscripcionEntrada(BaseModel):
    tipo: str = Field(..., description="cambio_plan · cambio_cantidad · pausa · reanudacion · baja")
    efectivo_el: date | None = None
    plan: str | None = None
    cantidad: Decimal | None = None
    importe_periodo: Decimal | None = None
    motivo: str = ""


@router_sus.post(
    "/{suscripcion_cliente_id}/cambios",
    dependencies=[Depends(exige_permiso("contract:write"))],
    summary="Cambiar una suscripción, con su prorrateo",
    description=(
        "El prorrateo se calcula **por días reales del periodo**, no por "
        "treintavos: un cambio a mitad de febrero con treintavos cobra de menos, "
        "y es la diferencia que el cliente encuentra cuando revisa la factura.\n\n"
        "El histórico es append-only: sin él, responder «¿desde cuándo paga "
        "esto?» exige mirar facturas."
    ),
)
def cambiar_suscripcion(suscripcion_id: UUID, datos: CambioSuscripcionEntrada, uow: UowDep) -> Any:
    return pre.cambiar_suscripcion(uow, suscripcion_id, **datos.model_dump())


@router_sus.get(
    "/recurrente",
    dependencies=[Depends(exige_permiso("contract:read"))],
    summary="MRR y ARR",
    description=(
        "Las **pausadas no cuentan**: una suscripción pausada no factura, y "
        "contarla infla el recurrente con dinero que no entra. Se dicen aparte, "
        "porque es la cifra que avisa de una fuga antes de que sea una baja."
    ),
)
def recurrente(db: DbDep, principal: AutenticadoDep) -> Any:
    return pre.ingreso_recurrente(db, principal.tenant_id)


# ── Pedidos y ERP ─────────────────────────────────────────────────────────


@router_ped.post(
    "/{pedido_id}/enviar-erp",
    dependencies=[Depends(exige_permiso("order:write"))],
    summary="Mandar el pedido al ERP",
    description=(
        "Lo deja **esperando confirmación**. No se da por bueno porque la llamada "
        "no diera error: el ERP puede aceptar el mensaje y rechazar el pedido "
        "después, y un traspaso que se cierra al enviar es cómo se descubre en el "
        "cierre de mes que faltan pedidos."
    ),
)
def enviar_erp(pedido_id: UUID, uow: UowDep) -> Any:
    return pre.enviar_a_erp(uow, pedido_id)


class RespuestaErp(BaseModel):
    aceptado: bool
    referencia_erp: str = ""
    error: str = ""
    respuesta: dict[str, Any] = Field(default_factory=dict)


@router_ped.post(
    "/{pedido_id}/respuesta-erp",
    dependencies=[Depends(exige_permiso("order:write"))],
    summary="Anotar lo que el ERP respondió",
)
def respuesta_erp(pedido_id: UUID, datos: RespuestaErp, uow: UowDep) -> Any:
    return pre.confirmar_desde_erp(uow, pedido_id, **datos.model_dump())


@router_ped.get(
    "/conciliacion-erp",
    dependencies=[Depends(exige_permiso("order:read"))],
    summary="Pedidos de los que el ERP no ha dicho nada",
    description=(
        "Mismo problema que el encargo mudo del seguimiento externo, y por eso se "
        "resuelve igual: **el silencio no es una confirmación**. Un pedido "
        "enviado del que nadie contesta parece en curso, y lo que hay detrás casi "
        "siempre es un mensaje perdido.\n\n"
        "Los rechazados salen también: un pedido rechazado por el ERP que nadie "
        "mira es una venta cerrada que no se sirve."
    ),
)
def conciliacion(
    uow: UowDep, principal: AutenticadoDep, horas: int = Query(24, ge=1, le=720)
) -> Any:
    return pre.conciliar_erp(uow, principal.tenant_id, horas_espera=horas)


# ── Listados ──────────────────────────────────────────────────────────────
# Estas colecciones se podían crear y no se podían leer: tenían `POST` y no
# tenían `GET`, así que lo que se daba de alta desaparecía de la vista. La API
# contestaba 405 y el front —que las declara listables— enseñaba una pantalla
# vacía sin decir por qué.

montar_listado(
    router_precios,
    modelo=ListaPrecio,
    objeto="lista_precio",
    permiso="producto:read",
    nombre="Listas de precios",
)
montar_listado(
    router_pre,
    modelo=Presupuesto,
    objeto="presupuesto",
    permiso="quote:read",
    nombre="Presupuestos",
)
montar_listado(
    router_ctr,
    modelo=Contrato,
    objeto="contrato",
    permiso="contract:read",
    nombre="Contratos",
)
montar_listado(
    router_sus,
    modelo=SuscripcionCliente,
    objeto="suscripcion",
    permiso="contract:read",
    nombre="Suscripciones",
)


# ── Listados ──────────────────────────────────────────────────────────────
# Colecciones con acciones sobre sus registros y sin forma de listarlos: se
# podía desplegar un entorno, invocar un agente o cerrar una visita, y no ver
# ninguno. A una acción sobre un registro se llega por su ficha, y a la ficha
# por el listado: sin listado, la acción no la alcanza nadie.

montar_listado(
    router_ped,
    modelo=Pedido,
    objeto="pedido",
    permiso="quote:read",
    nombre="Pedidos",
)


ROUTERS_COTIZACION = [
    router_prod,
    router_precios,
    router_pre,
    router_ctr,
    router_sus,
    router_ped,
]
