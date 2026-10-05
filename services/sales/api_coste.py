"""API de coste, tarifas y capacidad (CRM-09.02.01.01 a .09).

Todo lo de aquí sirve para una sola conversación: **si esta oferta gana dinero**.
Aprobar por porcentaje de descuento es aprobar a ciegas — un 5 % sobre algo que se
compra caro pierde dinero y un 30 % sobre algo que se compra bien no.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from crmcore import fechas
from crmcore.http.deps import AutenticadoDep, DbDep, exige_permiso
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from services.sales import coste as cst

router_coste = APIRouter(prefix="/coste", tags=["coste y capacidad"])


class MargenIn(BaseModel):
    lineas: list[dict[str, Any]] = Field(default_factory=list)
    margen_minimo_pct: Decimal = cst.MARGEN_MINIMO_PCT


class CongelarIn(BaseModel):
    lineas: list[dict[str, Any]] = Field(default_factory=list)


class RevisarIn(BaseModel):
    lineas_congeladas: list[dict[str, Any]] = Field(default_factory=list)
    costes_hoy: dict[str, Decimal] = Field(default_factory=dict)


class CompararIn(BaseModel):
    ofertas: list[dict[str, Any]] = Field(default_factory=list)
    fecha_necesaria: date | None = None


class PeticionIn(BaseModel):
    proveedores: list[UUID] = Field(default_factory=list)
    lineas: list[dict[str, Any]] = Field(default_factory=list)
    fecha_limite: date
    oportunidad_id: UUID | None = None


class RespuestasIn(BaseModel):
    pedidas_a: list[UUID] = Field(default_factory=list, description="A quién se le pidió oferta")
    respuestas: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Cada una con `proveedor_id` y, si la hay, `recibida_el`",
    )
    fecha_limite: date


class RepartoIn(BaseModel):
    candidatos: list[dict[str, Any]] = Field(default_factory=list)
    cantidad: Decimal
    regla: str = "menor_coste"


class RappelIn(BaseModel):
    compra_acumulada: Decimal
    tramos: list[dict[str, Any]] = Field(default_factory=list)
    cerrado: bool = False


@router_coste.get(
    "/tarifa/{producto_id}",
    dependencies=[Depends(exige_permiso("sales:read"))],
    summary="Lo que nos cuesta un producto con un proveedor",
    description=(
        "Sale del **mismo motor de precios** que la venta, con el sentido "
        "cambiado. Un motor paralelo para costes acabaría con dos formas de "
        "escalar por volumen y dos maneras de resolver la vigencia, y una de las "
        "dos se quedaría atrás.\n\n"
        "Las listas de coste y las de venta no se mezclan nunca: si se mezclaran, "
        "una tarifa de proveedor podría entrar en el precio y el cliente vería lo "
        "que nos cuesta."
    ),
)
def tarifa(
    producto_id: UUID,
    db: DbDep,
    principal: AutenticadoDep,
    proveedor_id: UUID | None = Query(None),
    cantidad: Decimal = Query(Decimal(1)),
) -> Any:
    from services.sales.catalogo import calcular_precio

    return calcular_precio(
        db,
        principal.tenant_id,
        producto_id=producto_id,
        cantidad=cantidad,
        sentido="coste",
        proveedor_id=proveedor_id,
    )


@router_coste.post(
    "/margen",
    dependencies=[Depends(exige_permiso("sales:read"))],
    summary="El margen de la oferta, y qué líneas no se pueden medir",
    description=(
        "Sin coste **no se devuelve margen cero**: se dice que no se sabe. Un "
        "margen en blanco se lee como «no hay margen» o como «no importa» según "
        "quien mire, y las dos lecturas son peores que la verdad.\n\n"
        "Y una oferta con costes incompletos no tiene «un margen aproximado»: "
        "tiene un margen desconocido. Enseñar la media de lo que sí se sabe es la "
        "forma elegante de mentir en una hoja de aprobación."
    ),
)
def margen(cuerpo: MargenIn, principal: AutenticadoDep) -> Any:
    return cst.margen_de_oferta(lineas=cuerpo.lineas, margen_minimo_pct=cuerpo.margen_minimo_pct)


@router_coste.post(
    "/congelar",
    dependencies=[Depends(exige_permiso("sales:write"))],
    summary="Fijar el coste en el momento de ofertar",
    description=(
        "Si la oferta recalculara el coste cada vez que se abre, el margen que "
        "alguien aprobó en septiembre habría desaparecido en octubre sin que "
        "nadie tocara nada — y la aprobación pasaría a referirse a unos números "
        "que ya no existen."
    ),
)
def congelar(cuerpo: CongelarIn, principal: AutenticadoDep) -> Any:
    return cst.congelar_coste(lineas=cuerpo.lineas)


@router_coste.post(
    "/congelar/revisar",
    dependencies=[Depends(exige_permiso("sales:read"))],
    summary="Qué ha cambiado desde que se congeló, sin tocar la oferta",
    description=(
        "Reescribir la oferta sería lo cómodo y es lo peor: el comercial la manda "
        "creyendo que lleva los números que aprobó su jefe. Se avisa, con cuánto "
        "ha cambiado, y decide una persona."
    ),
)
def revisar(cuerpo: RevisarIn, principal: AutenticadoDep) -> Any:
    return cst.revisar_costes_congelados(
        lineas_congeladas=cuerpo.lineas_congeladas, costes_hoy=cuerpo.costes_hoy
    )


@router_coste.post(
    "/comparar",
    dependencies=[Depends(exige_permiso("sales:read"))],
    summary="Comparar proveedores por coste, plazo y riesgo",
    description=(
        "El más barato que llega dos semanas tarde no es la opción barata: es un "
        "incumplimiento con descuento. Y el que no está homologado no es una "
        "opción, por mucho que su número sea el mejor.\n\n"
        "Se devuelven **todas** con su motivo de descarte: quien decide necesita "
        "poder explicar por qué no eligió la más barata, normalmente a alguien "
        "que solo ha visto esa columna."
    ),
)
def comparar(cuerpo: CompararIn, principal: AutenticadoDep) -> Any:
    return cst.comparar_proveedores(ofertas=cuerpo.ofertas, fecha_necesaria=cuerpo.fecha_necesaria)


@router_coste.post(
    "/peticion",
    dependencies=[Depends(exige_permiso("sales:write"))],
    summary="Preparar una petición de oferta al proveedor",
    description=(
        "**Ligada a la oportunidad** que la motiva: una petición suelta no se "
        "cierra nunca, porque nadie sabe si aquello se ganó o se perdió, y acaba "
        "en una lista de cosas abiertas que nadie limpia.\n\n"
        "Y con fecha límite real: sin ella la respuesta llega cuando el cliente "
        "ya ha decidido, y el precio que se le dio se puso a ojo."
    ),
)
def peticion(cuerpo: PeticionIn, db: DbDep, principal: AutenticadoDep) -> Any:
    return cst.preparar_peticion(
        proveedores=cuerpo.proveedores,
        lineas=cuerpo.lineas,
        fecha_limite=cuerpo.fecha_limite,
        oportunidad_id=cuerpo.oportunidad_id,
        # Una fecha límite «de hoy» calculada en UTC adelanta el plazo un día
        # para media Europa de madrugada, y el plazo de una petición de oferta
        # es lo que decide si la respuesta llega a tiempo.
        hoy=fechas.hoy(db),
    )


@router_coste.post(
    "/respuestas",
    dependencies=[Depends(exige_permiso("sales:read"))],
    summary="Qué ha contestado cada proveedor, y quién no ha contestado",
    description=(
        "**Lo segundo es lo que casi nunca se enseña y lo que más se necesita.** "
        "Si tres de cinco no han contestado, la comparación no es entre cinco "
        "opciones: es entre dos, y decidir sin saberlo es creer que se ha "
        "comparado el mercado cuando se ha comparado lo que llegó.\n\n"
        "Se dice también **quién llegó fuera de plazo**, porque una oferta buena "
        "recibida tarde no es una opción: es la conversación de por qué se "
        "eligió otra."
    ),
)
def respuestas(cuerpo: RespuestasIn, db: DbDep, principal: AutenticadoDep) -> Any:
    return cst.recoger_respuestas(
        pedidas_a=cuerpo.pedidas_a,
        respuestas=cuerpo.respuestas,
        fecha_limite=cuerpo.fecha_limite,
        # Igual que al preparar la petición: un «hoy» en UTC cierra el plazo un
        # día antes para media Europa de madrugada, y el plazo es lo que decide
        # si una respuesta cuenta.
        hoy=fechas.hoy(db),
    )


@router_coste.get(
    "/capacidad",
    dependencies=[Depends(exige_permiso("sales:read"))],
    summary="Cuánto queda de verdad con este proveedor",
    description=(
        "Una cuota que solo mira lo contratado y no lo **ya comprometido** deja "
        "vender tres veces lo mismo, y eso se descubre en la semana de la "
        "entrega.\n\n"
        "Se enseña aparte lo que hay **en ofertas abiertas**: todavía no es un "
        "compromiso, pero si se ganan todas tampoco cabe — y esa conversación es "
        "mejor tenerla antes de mandar la cuarta oferta."
    ),
)
def capacidad(
    principal: AutenticadoDep,
    contratada: Decimal = Query(Decimal(0)),
    comprometida: Decimal = Query(Decimal(0)),
    en_ofertas: Decimal = Query(Decimal(0)),
) -> Any:
    return cst.capacidad_disponible(
        contratada=contratada, ya_comprometida=comprometida, en_ofertas_abiertas=en_ofertas
    )


@router_coste.get(
    "/fecha-prometible",
    dependencies=[Depends(exige_permiso("sales:read"))],
    summary="Qué fecha se le puede dar al cliente con este proveedor detrás",
    description=(
        "Este es el orden correcto: **primero se mira el plazo y después se "
        "promete**. Al revés —prometer y luego buscar quién lo cumpla— es lo que "
        "produce los retrasos, y deja al comercial en una posición imposible.\n\n"
        "Si el proveedor no declara plazo **no se inventa uno**: se dice que no "
        "se puede prometer fecha todavía, que es incómodo y es verdad."
    ),
)
def fecha_prometible(
    db: DbDep,
    principal: AutenticadoDep,
    plazo_proveedor_dias: int | None = Query(None),
    dias_propios: int = Query(2),
) -> Any:
    return cst.fecha_que_se_puede_prometer(
        plazo_proveedor_dias=plazo_proveedor_dias,
        dias_propios=dias_propios,
        desde=fechas.hoy(db),
    )


@router_coste.post(
    "/reparto",
    dependencies=[Depends(exige_permiso("sales:write"))],
    summary="Repartir entre los proveedores que pueden servir",
    description=(
        "La regla **se declara**. Sin regla reparte quien monta la oferta, y cada "
        "uno lo hace de una manera — normalmente con el de siempre, que es como "
        "se llega a depender de uno sin que nadie lo haya decidido.\n\n"
        "Y si no cabe entero se dice cuánto falta, en vez de repartir lo que hay "
        "y dejar el resto sin asignar sin avisar."
    ),
)
def reparto(cuerpo: RepartoIn, principal: AutenticadoDep) -> Any:
    return cst.repartir(candidatos=cuerpo.candidatos, cantidad=cuerpo.cantidad, regla=cuerpo.regla)


@router_coste.post(
    "/rappel",
    dependencies=[Depends(exige_permiso("sales:read"))],
    summary="Qué se recuperará del proveedor y a qué periodo pertenece",
    description=(
        "Un rappel estimado **no es dinero**: depende de llegar al tramo, y si el "
        "año se tuerce no se llega.\n\n"
        "Y se imputa **al periodo, no a las ofertas que lo generaron**: "
        "repartirlo hacia atrás haría que una oferta pareciera rentable por algo "
        "que todavía no ha pasado."
    ),
)
def rappel(cuerpo: RappelIn, principal: AutenticadoDep) -> Any:
    return cst.rappel_estimado(
        compra_acumulada=cuerpo.compra_acumulada, tramos=cuerpo.tramos, cerrado=cuerpo.cerrado
    )


ROUTERS_COSTE = [router_coste]
