"""API de catálogo, precios, presupuestos, contratos y suscripciones
(CRM-03.03.02)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from crmcore.datos.estados import con_significado
from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from crmcore.http.listados import (
    aplicar_filtros_de_la_url,
    declarar_recurso,
    montar_ficha,
    montar_listado,
)
from crmcore.http.pagination import CONTAR_TOTAL_DESCRIPCION, PaginaDeListado, paginar_consulta
from crmcore.http.parametros import admite_parametros_abiertos
from crmcore.http.portal_deps import PortalDep, exige_seccion_portal
from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from services.sales import catalogo as cat
from services.sales import presupuestos as pre
from services.sales.catalogo import ListaPrecio
from services.sales.presupuestos import Contrato, Pedido, Presupuesto, SuscripcionCliente

router_prod = APIRouter(prefix="/productos", tags=["catálogo"])
declarar_recurso(router_prod, "producto", cat.Producto)
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
    # El coste y el margen mínimo: un precio sin coste al lado no deja ver si
    # un descuento se come el margen, que es la única pregunta que se hace
    # quien aprueba una oferta. Estaban en la tabla y no salían.
    coste: Decimal | None = None
    margen_minimo_pct: Decimal | None = None
    # Y cómo se vende: la unidad y, si es recurrente, cada cuánto.
    unidad: str | None = None
    periodicidad: str | None = None
    descripcion: str | None = None
    atributos: dict[str, Any] = {}
    activo: bool
    # Un producto retirado no desaparece —sigue en ofertas y contratos
    # firmados—, así que la fecha de retirada tiene que verse.
    retirado_el: date | None = None
    created_at: datetime

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
    response_model=PaginaDeListado,
    dependencies=[Depends(exige_permiso("producto:read"))],
    summary="Catálogo del tenant",
)
def listar_productos(
    request: Request,
    db: DbDep,
    principal: AutenticadoDep,
    familia: str = Query(""),
    solo_activos: bool = Query(True),
    limite: int = Query(200, ge=1, le=1000),
    cursor: str = Query(""),
    contar: bool = Query(False, description=CONTAR_TOTAL_DESCRIPCION),
) -> Any:
    consulta = select(cat.Producto).where(cat.Producto.tenant_id == principal.tenant_id)
    if familia:
        consulta = consulta.where(cat.Producto.familia == familia)
    if solo_activos:
        consulta = consulta.where(cat.Producto.activo.is_(True))
    # Y los filtros comunes, con sus rangos. Estar escrito a mano no es motivo
    # para quedarse sin ellos: entonces el mismo producto admite
    # `?vence_at__hasta=…` o no según quién escribió cada listado, y eso lo
    # descubre el integrador probando.
    consulta = aplicar_filtros_de_la_url(
        request, cat.Producto, consulta, principal=principal, db=db, objeto="producto"
    )
    return paginar_consulta(
        db,
        cat.Producto,
        consulta,
        limite=limite,
        cursor=cursor,
        orden="sku",
        modelo_salida=ProductoOut,
        contar=contar,
    )


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
    # Una tarifa de coste es una lista con el sentido cambiado y su proveedor
    # (CRM-09.02.01.01). El modelo y el motor lo sabían; el alta no lo admitía,
    # así que el motor calculaba costes de tarifas que no se podían crear.
    # Lista cerrada y no un patrón: con el patrón el formulario daba una caja de
    # texto donde había que escribir «coste» sin tilde ni mayúscula.
    sentido: Literal["venta", "coste"] = Field(
        "venta",
        description="Venta, lo que cobramos; coste, lo que nos cobra un proveedor",
    )
    proveedor_id: UUID | None = Field(
        None, description="Obligatorio en una tarifa de coste, y prohibido en una de venta"
    )


@router_precios.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("producto:write"))],
    summary="Crear una lista de precios",
)
def crear_lista(datos: CrearLista, db: DbDep, principal: AutenticadoDep) -> Any:
    # Una tarifa de coste sin proveedor se aplicaría a todos, y una de venta con
    # proveedor no la encontraría nunca el motor: las dos se rechazan diciendo
    # por qué, en vez de guardarse y no hacer lo que se pensaba.
    if (datos.sentido == "coste") != (datos.proveedor_id is not None):
        from crmcore.errors import ErrorValidacion

        raise ErrorValidacion(
            "Una tarifa de coste lleva su proveedor, y una lista de venta no lleva ninguno.",
            error_code="lista_precio.proveedor_y_sentido",
            detalle={"sentido": datos.sentido},
        )
    fila = cat.ListaPrecio(tenant_id=principal.tenant_id, **datos.model_dump())
    db.add(fila)
    db.flush()
    return {"id": str(fila.id), "clave": fila.clave}


class CrearReglaPrecio(BaseModel):
    # La lista se ELIGE y la acción es una lista cerrada: el formulario pedía
    # el identificador de la lista tecleado y la acción escrita a mano, con las
    # cinco válidas en la ayuda (visto el 10-11-2026).
    lista_id: UUID = Field(..., json_schema_extra={"referencia": "lista_precio"})
    nombre: str = ""
    prioridad: int = 100
    producto_id: UUID | None = None
    familia: str | None = None
    desde_cantidad: Decimal = Field(Decimal(0), description="Escalado por volumen")
    condiciones: list[dict[str, Any]] = Field(
        default_factory=list, description="Misma gramática que el reparto de leads y casos"
    )
    accion: Literal[cat.ACCIONES] = Field(  # type: ignore[valid-type]
        ...,
        description="Fijar el precio, o descontar o recargar un porcentaje o un importe",
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
    # La lista tiene que existir y ser de este tenant: sin esto, una lista
    # inventada reventaba con 500 al escribir la clave ajena (lo cazó el humo
    # de escrituras el 10-11-2026).
    lista = db.get(cat.ListaPrecio, datos.lista_id)
    if lista is None or lista.tenant_id != principal.tenant_id or lista.deleted_at is not None:
        from crmcore.errors import NoEncontrado

        raise NoEncontrado("Esa lista de precios no existe", error_code="catalogo.lista_no_existe")
    fila = cat.ReglaPrecio(tenant_id=principal.tenant_id, **datos.model_dump())
    db.add(fila)
    db.flush()
    return {"id": str(fila.id)}


# Las reglas de una lista, para VERLAS y quitarlas (CRM-03.03.02.03,
# CRM-09.02.01.01). Se podían añadir y no había forma de saber qué reglas tenía
# una lista ni en qué orden se aplican: la ficha de la lista salía sin ellas, y
# una regla equivocada no se podía retirar (visto el 10-11-2026).
def _lista_del_tenant(db: Any, tenant_id: UUID, lista_id: UUID) -> Any:
    from crmcore.errors import NoEncontrado

    lista = db.get(cat.ListaPrecio, lista_id)
    if lista is None or lista.tenant_id != tenant_id:
        raise NoEncontrado("La lista no existe", error_code="catalogo.lista_no_encontrada")
    return lista


@router_precios.get(
    "/{lista_id}/reglas",
    response_model=list[dict[str, Any]],
    dependencies=[Depends(exige_permiso("producto:read"))],
    summary="Reglas de la lista, en el orden en que se aplican",
)
def reglas_de_la_lista(lista_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    from sqlalchemy import select

    _lista_del_tenant(db, principal.tenant_id, lista_id)
    filas = (
        db.execute(
            select(cat.ReglaPrecio)
            .where(
                cat.ReglaPrecio.tenant_id == principal.tenant_id,
                cat.ReglaPrecio.lista_id == lista_id,
            )
            .order_by(cat.ReglaPrecio.prioridad, cat.ReglaPrecio.nombre)
        )
        .scalars()
        .all()
    )
    return [
        {
            # En el orden en que se leen: el panel de la ficha enseña los
            # primeros, y sin la acción y el valor no se sabe qué hace la regla.
            "id": str(f.id),
            "nombre": f.nombre,
            "accion": f.accion,
            "valor": str(f.valor),
            "desde_cantidad": str(f.desde_cantidad),
            "prioridad": f.prioridad,
            "producto_id": str(f.producto_id) if f.producto_id else None,
            "familia": f.familia,
            "exclusiva": f.exclusiva,
        }
        for f in filas
    ]


@router_precios.delete(
    "/{lista_id}/reglas/{regla_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(exige_permiso("producto:write"))],
    summary="Quitar una regla de la lista",
)
def quitar_regla(lista_id: UUID, regla_id: UUID, db: DbDep, principal: AutenticadoDep) -> None:
    from crmcore.errors import NoEncontrado

    _lista_del_tenant(db, principal.tenant_id, lista_id)
    regla = db.get(cat.ReglaPrecio, regla_id)
    if regla is None or regla.lista_id != lista_id or regla.tenant_id != principal.tenant_id:
        raise NoEncontrado(
            "La regla no es de esta lista", error_code="catalogo.regla_no_encontrada"
        )
    db.delete(regla)
    db.flush()


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
    # Con límites, como `CrearLinea` (esquemas.py). Sin ellos un descuento del
    # 150 % daba un total negativo y uno de 1000 % desbordaba la columna
    # Numeric(5,2) y contestaba 500 (auditoría 13-11-2026, FUN-B-14).
    cantidad: Decimal = Field(Decimal(1), gt=0)
    descuento_pct: Decimal = Field(Decimal(0), ge=0, le=100)
    precio_unitario: Decimal | None = Field(
        None, ge=0, description="Solo para líneas libres, sin producto de catálogo"
    )
    coste_unitario: Decimal | None = Field(None, ge=0)


class CrearPresupuesto(BaseModel):
    # Vacías se toman las de la oportunidad: la oferta se hace desde ella y
    # pedir que se vuelvan a teclear las líneas que ya tiene era el primer
    # paso de una oferta que no cuadra con su oportunidad (10-11-2026).
    lineas: list[LineaEntrada] = Field(
        default_factory=list,
        description="Si se deja vacío y hay oportunidad, se copian sus líneas",
    )
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


@router_pre.get(
    "/{presupuesto_id}/costes-al-dia",
    dependencies=[Depends(exige_permiso("quote:read"))],
    summary="Si el coste ha cambiado desde que se ofertó",
    description=(
        "El coste se congela en cada línea al ofertar (CRM-09.02.01.03). Esto lo "
        "compara con el de hoy y **avisa sin reescribir**: reescribir mandaría al "
        "cliente unos números que nadie aprobó. Las líneas que no se pueden "
        "comparar —sin coste congelado o sin producto— se cuentan aparte, porque "
        "callarlas haría pasar «no se sabe» por «no ha cambiado»."
    ),
)
def costes_al_dia(presupuesto_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    from crmcore import costes as cst

    fila = db.get(pre.Presupuesto, presupuesto_id)
    if fila is None or fila.tenant_id != principal.tenant_id:
        from crmcore.errors import NoEncontrado

        raise NoEncontrado("El presupuesto no existe", error_code="presupuesto.no_encontrado")
    lineas = (
        db.execute(
            select(pre.LineaPresupuesto)
            .where(pre.LineaPresupuesto.presupuesto_id == fila.id)
            .order_by(pre.LineaPresupuesto.orden)
        )
        .scalars()
        .all()
    )
    congeladas: list[dict[str, Any]] = []
    hoy: dict[str, Decimal] = {}
    no_comparables: list[str] = []
    for linea in lineas:
        referencia = linea.sku or linea.descripcion or str(linea.id)
        if linea.coste_unitario is None or linea.producto_id is None:
            no_comparables.append(referencia)
            continue
        actual = cat.calcular_precio(
            db,
            principal.tenant_id,
            producto_id=linea.producto_id,
            cantidad=Decimal(linea.cantidad),
            moneda=fila.moneda,
        )["coste"]
        if actual is None:
            no_comparables.append(referencia)
            continue
        congeladas.append({"referencia": referencia, "coste_congelado": linea.coste_unitario})
        hoy[referencia] = Decimal(actual)
    # Un literal con la delegación dentro, y no «asignar, añadir y devolver»: así
    # lo sigue el resolutor de contratos y la pantalla que lo lee queda vigilada.
    return {
        **cst.revisar_costes_congelados(lineas_congeladas=congeladas, costes_hoy=hoy),
        "comparadas": len(congeladas),
        "no_comparables": no_comparables,
    }


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


class Clausula(BaseModel):
    model_config = {"extra": "allow"}

    titulo: str = Field(..., min_length=1, max_length=300)
    texto: str = Field("", max_length=5000)


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
    # Con columnas: el alta pedía las cláusulas en un editor de JSON
    # (visto el 10-11-2026). Lo que traiga de más una integración se conserva.
    clausulas: list[Clausula] = Field(default_factory=list)


class CambiarEstado(BaseModel):
    estado: str = Field(max_length=40)
    motivo: str = ""


def _cambiar(uow: Any, objeto: str, modelo: Any, fila_id: UUID, datos: CambiarEstado) -> Any:
    """El cambio de estado de la ficha, con los estados de la empresa.

    Lo que tiene su acción —enviar, aceptar, la versión nueva, renovar— no se
    hace aquí: lo dice y dice cuál. Lo demás —los estados propios, suspender o
    terminar un contrato, que el cliente rechace— se mueve desde aquí.
    """
    from crmcore.errors import NoEncontrado

    from services.sales import servicio as svc

    fila = uow.db.get(modelo, fila_id)
    if fila is None or fila.tenant_id != uow.tenant_id or getattr(fila, "deleted_at", None):
        raise NoEncontrado(f"El {objeto} no existe", error_code=f"{objeto}.no_encontrado")
    svc.cambiar_estado(uow, objeto, fila, estado=datos.estado, motivo=datos.motivo)
    return {"id": str(fila.id), "estado": fila.estado}


@router_pre.post(
    "/{presupuesto_id}/estado",
    dependencies=[Depends(exige_permiso("quote:write"))],
    summary="Mover el presupuesto de estado",
)
def cambiar_estado_presupuesto(presupuesto_id: UUID, datos: CambiarEstado, uow: UowDep) -> Any:
    return _cambiar(uow, "presupuesto", Presupuesto, presupuesto_id, datos)


@router_ctr.post(
    "/{contrato_id}/estado",
    dependencies=[Depends(exige_permiso("contract:write"))],
    summary="Mover el contrato de estado: suspender, terminar o reactivar",
)
def cambiar_estado_contrato(contrato_id: UUID, datos: CambiarEstado, uow: UowDep) -> Any:
    return _cambiar(uow, "contrato", Contrato, contrato_id, datos)


@router_ctr.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("contract:write"))],
    summary="Dar de alta un contrato",
)
def crear_contrato(datos: CrearContrato, uow: UowDep) -> Any:
    fila = pre.crear_contrato(uow, **datos.model_dump())
    return {"id": str(fila.id), "numero": fila.numero, "fin": str(fila.fin) if fila.fin else None}


class RevisarRenovaciones(BaseModel):
    contrato_id: UUID | None = Field(None, description="Revisar sólo este contrato")
    contrato_ids: list[UUID] | None = Field(
        None, max_length=500, description="Revisar sólo estos contratos"
    )


@router_ctr.post(
    "/revisar-renovaciones",
    dependencies=[Depends(exige_permiso("contract:write"))],
    summary="Avisar de los preavisos y renovar lo que toca",
    description=(
        "Los contratos **sin** renovación automática también avisan. Son los que "
        "se olvidan: nadie los renueva y el cliente se va sin que nadie lo haya "
        "decidido. Sin cuerpo revisa todos los vigentes, como la tarea "
        "periódica; con `contrato_id` o `contrato_ids`, sólo esos —«revisar este "
        "contrato» desde su ficha—, y los que no se pudieron revisar salen en "
        "`no_revisados` con el porqué."
    ),
)
def revisar_renovaciones(
    uow: UowDep, principal: AutenticadoDep, cuerpo: RevisarRenovaciones = RevisarRenovaciones()
) -> Any:
    ids: list[UUID] | None = None
    if cuerpo.contrato_id or cuerpo.contrato_ids:
        ids = [*(cuerpo.contrato_ids or []), *([cuerpo.contrato_id] if cuerpo.contrato_id else [])]
    return pre.revisar_renovaciones(uow, principal.tenant_id, contrato_ids=ids)


# ── Suscripciones ─────────────────────────────────────────────────────────


class AltaSuscripcion(BaseModel):
    cuenta_id: UUID
    plan: str = Field(..., min_length=1, max_length=120)
    importe_periodo: Decimal = Field(..., ge=0)
    inicio: date
    periodicidad: Literal["mensual", "trimestral", "anual"] = "mensual"
    contrato_id: UUID | None = None
    producto_id: UUID | None = None
    cantidad: Decimal = Field(Decimal(1), gt=0)
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
    # Lista cerrada: el formulario pedía escribir «cambio_plan» con las cinco
    # opciones en la ayuda (visto el 10-11-2026).
    tipo: Literal[  # type: ignore[valid-type]
        tuple(t for t in pre.TIPOS_CAMBIO_SUSCRIPCION if t != "alta")
    ] = Field(
        ..., description="Qué cambia: el plan, la cantidad, una pausa, la reanudación o la baja"
    )
    efectivo_el: date | None = None
    plan: str | None = None
    cantidad: Decimal | None = Field(None, gt=0)
    importe_periodo: Decimal | None = Field(None, ge=0)
    motivo: str = ""


@router_sus.post(
    # `{suscripcion_id}`, el mismo nombre que la función. Era
    # `{suscripcion_cliente_id}`: FastAPI tomaba `suscripcion_id` por un
    # parámetro de consulta obligatorio que nadie manda y contestaba 422 a
    # cualquier cambio — no se podía cambiar de plan ni dar de baja una
    # suscripción desde ningún sitio (visto el 10-11-2026).
    "/{suscripcion_id}/cambios",
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


# ── Lo que el cliente ve de lo suyo, desde su portal ──────────────────────
#
# El portal anunciaba «contratos» y «pedidos» y no había ruta para ninguno: el
# cliente pintaba botones que no llevaban a ninguna parte. Se sirven **desde
# aquí** y no desde `service`, que es quien tiene la tabla de accesos, porque
# traer contratos y pedidos allí obligaría a copiarlos — y la copia es siempre
# la que se queda vieja.
#
# Lo que hace posible servirlos sin leer la tabla de accesos es que la sesión
# del portal lleva su empresa y sus secciones **firmadas** en el token.

router_portal_cliente = APIRouter(prefix="/portal", tags=["portal del cliente"])


@router_portal_cliente.get(
    "/mi/contratos",
    response_model=list[dict],
    dependencies=[Depends(exige_seccion_portal("contratos"))],
    summary="Mis contratos",
    description=(
        "**Por empresa, y sólo los firmados.** Un borrador de contrato es una "
        "negociación en curso: enseñárselo al cliente antes de tiempo es "
        "enseñarle condiciones que todavía se están discutiendo internamente.\n\n"
        "Van con su fecha de fin y su preaviso: el día del vencimiento ya es "
        "tarde para no renovar, y esa es justo la fecha que el cliente necesita "
        "saber."
    ),
)
def mis_contratos(db: DbDep, sesion: PortalDep, limite: int = Query(100, ge=1, le=500)) -> Any:
    filas = (
        db.execute(
            select(Contrato)
            .where(
                Contrato.tenant_id == sesion.tenant_id,
                Contrato.cuenta_id == sesion.exigir_cuenta(),
                Contrato.estado.not_in(con_significado("contrato", "borrador", db)),
            )
            .order_by(Contrato.inicio.desc())
            .limit(limite)
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(f.id),
            "numero": f.numero,
            "titulo": f.titulo,
            "estado": f.estado,
            "inicio": f.inicio.isoformat() if f.inicio else None,
            "fin": f.fin.isoformat() if f.fin else None,
            "renovacion_automatica": f.renovacion_automatica,
            "preaviso_dias": f.preaviso_dias,
            "importe": str(f.importe),
            "moneda": f.moneda,
        }
        for f in filas
    ]


@router_portal_cliente.get(
    "/mi/pedidos",
    response_model=list[dict],
    dependencies=[Depends(exige_seccion_portal("pedidos"))],
    summary="Mis pedidos",
    description=(
        "Con la **referencia del ERP** y si el traspaso terminó. Es lo primero "
        "que pregunta quien llama: no «en qué estado está en vuestro CRM», sino "
        "«qué número tengo para reclamar».\n\n"
        "El error del ERP **no se le enseña al cliente**: es un detalle interno "
        "de nuestro traspaso y lo único que consigue es que nos llame para "
        "contárnoslo. Lo que ve es que todavía no está confirmado."
    ),
)
def mis_pedidos(db: DbDep, sesion: PortalDep, limite: int = Query(100, ge=1, le=500)) -> Any:
    filas = (
        db.execute(
            select(Pedido)
            .where(
                Pedido.tenant_id == sesion.tenant_id,
                Pedido.cuenta_id == sesion.exigir_cuenta(),
            )
            .order_by(Pedido.created_at.desc())
            .limit(limite)
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(f.id),
            "numero": f.numero,
            "estado": f.estado,
            "total": str(f.total),
            "moneda": f.moneda,
            "referencia_erp": f.referencia_erp,
            "confirmado": f.confirmado_at is not None,
        }
        for f in filas
    ]


ROUTERS_COTIZACION = [
    router_portal_cliente,
    router_prod,
    router_precios,
    router_pre,
    router_ctr,
    router_sus,
    router_ped,
]


# Estas rutas aceptan además los filtros comunes, cuyos nombres son columnas
# del modelo y cambian con él: no se pueden declarar. Los valida
# `aplicar_filtros_de_la_url`, que rechaza lo que no es columna o lo que este
# principal no ve en claro. Las dos mitades van juntas: con el filtro y sin la
# marca, la ruta contesta 422 a sus propios filtros.
admite_parametros_abiertos(
    listar_productos, "llama a `aplicar_filtros_de_la_url`, que valida los filtros por columna"
)

# ── Corregir lo dado de alta ──────────────────────────────────────────────
# Se podía crear y no había forma de cambiarlo: una errata, un plazo mal
# puesto o retirarlo obligaban a crear otro al lado. Medido el 05-11-2026: de
# las pestañas que admiten alta, treinta no admitían ningún cambio, y de ellas
# éstas eran un hueco y no una decisión. Se monta al final del módulo para que
# `/{id}` quede detrás de las rutas con nombre propio de la misma colección.
# Retirar un producto es desmarcar `activo`: los presupuestos de hace dos años
# lo siguen nombrando, y por eso aquí no hay borrado.
montar_ficha(
    router_prod,
    modelo=cat.Producto,
    objeto="producto",
    permiso_leer="producto:read",
    permiso_escribir="producto:write",
    nombre="Productos",
)
