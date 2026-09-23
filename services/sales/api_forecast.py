"""API de previsión de ventas (CRM-03.02.01, CRM-03.01.01.13)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from crmcore.http.listados import montar_listado
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from services.sales import forecast
from services.sales.modelos import PeriodoForecast

router_forecast = APIRouter(prefix="/forecast", tags=["previsión"])


# ── Categorías ────────────────────────────────────────────────────────────


@router_forecast.get(
    "/categorias",
    dependencies=[Depends(exige_permiso("opportunity:read"))],
    summary="Categorías de previsión del tenant",
    description=(
        "Son datos y no una lista en el código. «Pipeline, best case, commit, "
        "cerrado» es lo habitual, pero hay quien mete «upside» en medio y quien "
        "lo llama de otra manera; con la lista a fuego, cada organización sería "
        "una versión del producto.\n\n"
        "Lo que sí es del sistema es el significado: si cuenta como compromiso "
        "y si es terminal. Va en dos banderas explícitas y no deducido del "
        "nombre, que se rompería en cuanto alguien lo traduzca."
    ),
)
def listar_categorias(db: DbDep, principal: AutenticadoDep) -> Any:
    filas = forecast.categorias(db, principal.tenant_id) or forecast.sembrar_categorias(
        db, principal.tenant_id
    )
    return [
        {
            "clave": c.clave,
            "nombre": c.nombre,
            "orden": c.orden,
            "cuenta_como_compromiso": c.cuenta_como_compromiso,
            "terminal": c.terminal,
            "por_defecto": c.por_defecto,
            "color": c.color,
        }
        for c in filas
    ]


class Clasificacion(BaseModel):
    categoria: str = Field(max_length=40)


@router_forecast.put(
    "/oportunidades/{oportunidad_id}/categoria",
    dependencies=[Depends(exige_permiso("opportunity:write"))],
    summary="Poner una oportunidad en una categoría de previsión",
    description=(
        "Se comprueba que la categoría exista. Aceptar cualquier texto haría que "
        "una errata creara una categoría fantasma cuyo importe desaparece del "
        "total sin que nadie lo eche en falta: el peor error de datos, el que "
        "resta en silencio."
    ),
)
def clasificar(
    oportunidad_id: UUID, datos: Clasificacion, uow: UowDep, principal: AutenticadoDep
) -> Any:
    from services.sales.servicio import exigir_oportunidad

    oportunidad = exigir_oportunidad(uow.db, oportunidad_id)
    forecast.clasificar(uow.db, oportunidad, datos.categoria)
    return {"oportunidad_id": str(oportunidad_id), "categoria": datos.categoria}


# ── Periodos ──────────────────────────────────────────────────────────────


class PeriodoNuevo(BaseModel):
    clave: str = Field(max_length=40, description="2026-Q1, 2026-03…")
    desde: date
    hasta: date
    nombre: str = ""


@router_forecast.post(
    "/periodos",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("opportunity:write"))],
    summary="Abrir un periodo de previsión",
)
def abrir_periodo(datos: PeriodoNuevo, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = forecast.abrir_periodo(
        uow.db,
        principal.tenant_id,
        clave=datos.clave,
        desde=datos.desde,
        hasta=datos.hasta,
        nombre=datos.nombre,
    )
    return {"clave": fila.clave, "desde": fila.desde, "hasta": fila.hasta}


@router_forecast.post(
    "/periodos/{clave}/cerrar",
    dependencies=[Depends(exige_permiso("opportunity:write"))],
    summary="Cerrar el periodo y dejar su foto final",
    description=(
        "Cerrar es lo que hace que el número signifique algo: mientras está "
        "abierto, el commit del trimestre cambia cada vez que alguien toca una "
        "oportunidad, y comparar dos informes de fechas distintas es comparar "
        "dos cosas que no son la misma.\n\n"
        "La foto se toma **dentro** del cierre: un cierre sin foto es un número "
        "que ya no se puede reconstruir."
    ),
)
def cerrar_periodo(clave: str, uow: UowDep, principal: AutenticadoDep) -> Any:
    return forecast.cerrar_periodo(uow.db, principal.tenant_id, clave, por=principal.id)


class Reapertura(BaseModel):
    motivo: str = Field(min_length=1, max_length=1000)


@router_forecast.post(
    "/periodos/{clave}/reabrir",
    dependencies=[Depends(exige_permiso("opportunity:write"))],
    summary="Reabrir un periodo cerrado",
    description=(
        "Acto explícito, motivado y contado. Si fuera gratis, «cerrado» dejaría "
        "de significar nada. El contador de reaperturas está para que se vea "
        "cuántas veces ha pasado, que es la señal de que el cierre no se está "
        "respetando."
    ),
)
def reabrir_periodo(clave: str, datos: Reapertura, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = forecast.reabrir_periodo(
        uow.db, principal.tenant_id, clave, motivo=datos.motivo, por=principal.id
    )
    return {"clave": fila.clave, "reaperturas": fila.reaperturas}


# ── El número ─────────────────────────────────────────────────────────────


@router_forecast.get(
    "/periodos/{clave}",
    dependencies=[Depends(exige_permiso("opportunity:read"))],
    summary="Previsión del periodo por categoría",
    description=(
        "La conversión usa el cambio del **día de cierre** de cada oportunidad, "
        "no el de hoy: con el de hoy, el histórico de ventas se mueve solo y el "
        "mismo trimestre da números distintos según cuándo se consulte.\n\n"
        "Lo que no se ha podido convertir sale aparte y **no** se cuenta como "
        "cero: un total al que le faltan importes en silencio es peor que uno "
        "que avisa, porque nadie lo cuestiona."
    ),
)
def previsión(
    clave: str,
    db: DbDep,
    principal: AutenticadoDep,
    moneda: str = Query("", max_length=3),
    owner_id: list[UUID] = Query(default=[]),
) -> Any:
    return forecast.a_dict(
        forecast.calcular(
            db,
            principal.tenant_id,
            periodo_clave=clave,
            owners=list(owner_id) or None,
            moneda=moneda or None,
        )
    )


class Jerarquia(BaseModel):
    nodos: dict[str, list[UUID]] = Field(
        description=(
            "Nodo → comerciales. Llega resuelto porque el organigrama vive en "
            "`identity` y ningún servicio lee el esquema de otro; además, así la "
            "misma llamada sirve para agrupar por territorio o por canal"
        )
    )
    moneda: str = ""


@router_forecast.post(
    "/periodos/{clave}/jerarquia",
    dependencies=[Depends(exige_permiso("opportunity:read"))],
    summary="Previsión por comercial, equipo, región y compañía",
    description=(
        "El total de la compañía se calcula aparte y **no** sumando los nodos: "
        "una oportunidad cuyo dueño no esté en ninguna rama desaparecería de la "
        "suma sin que nadie lo notara, y el agujero se descubre al final del "
        "trimestre. Si la resta no es cero, se dice."
    ),
)
def por_jerarquia(clave: str, datos: Jerarquia, db: DbDep, principal: AutenticadoDep) -> Any:
    return forecast.previsión_por_jerarquía(
        db,
        principal.tenant_id,
        periodo_clave=clave,
        jerarquía={k: list(v) for k, v in datos.nodos.items()},
        moneda=datos.moneda or None,
    )


@router_forecast.get(
    "/periodos/{clave}/desglose",
    dependencies=[Depends(exige_permiso("opportunity:read"))],
    summary="Previsión por producto, familia o tipo de ingreso",
    description=(
        "Se calcula sobre las **líneas** y no sobre la cabecera, que es lo único "
        "que permite que una oportunidad con software y servicios cuente en las "
        "dos familias por su parte. Repartir la cabecera a ojo daría un desglose "
        "que suma bien y reparte mal, que es peor que no tenerlo."
    ),
)
def desglose(
    clave: str,
    db: DbDep,
    principal: AutenticadoDep,
    por: str = Query("familia", description="familia | tipo_ingreso | producto"),
    moneda: str = Query("", max_length=3),
) -> Any:
    return forecast.desglose(
        db, principal.tenant_id, periodo_clave=clave, por=por, moneda=moneda or None
    )


# ── Ajustes ───────────────────────────────────────────────────────────────


class Ajuste(BaseModel):
    categoria: str = Field(max_length=40, default="commit")
    importe_ajustado: Decimal
    importe_bruto: Decimal
    motivo: str = Field(min_length=1, max_length=2000)
    ambito: str = Field("usuario", max_length=20)
    ambito_id: UUID | None = None
    moneda: str = Field("EUR", max_length=3)


@router_forecast.post(
    "/periodos/{clave}/ajustes",
    dependencies=[Depends(exige_permiso("opportunity:write"))],
    summary="Ajustar el número calculado",
    description=(
        "Los responsables ajustan siempre, porque saben cosas que no están en el "
        "CRM. El problema nunca fue que ajusten: es que el ajuste se hacía en una "
        "hoja aparte y después nadie sabía quién quitó doscientos mil euros ni "
        "por qué. **El motivo es obligatorio.**\n\n"
        "Se guarda el bruto junto al ajustado porque sin él no se puede medir si "
        "los ajustes acertaron, que es la única forma de saber si conviene hacer "
        "caso la próxima vez."
    ),
)
def ajustar(clave: str, datos: Ajuste, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = forecast.ajustar(
        uow.db,
        principal.tenant_id,
        periodo_clave=clave,
        categoria=datos.categoria,
        importe_ajustado=datos.importe_ajustado,
        importe_bruto=datos.importe_bruto,
        motivo=datos.motivo,
        ambito=datos.ambito,
        ambito_id=datos.ambito_id,
        por=principal.id,
        moneda=datos.moneda,
    )
    return {"id": str(fila.id), "delta": str(fila.importe_ajustado - fila.importe_bruto)}


@router_forecast.get(
    "/periodos/{clave}/ajustes",
    dependencies=[Depends(exige_permiso("opportunity:read"))],
    summary="Ajustes del periodo, con autor y motivo",
)
def listar_ajustes(clave: str, db: DbDep, principal: AutenticadoDep) -> Any:
    return forecast.ajustes_de(db, principal.tenant_id, clave)


@router_forecast.get(
    "/periodos/{clave}/acierto-ajustes",
    dependencies=[Depends(exige_permiso("opportunity:read"))],
    summary="¿Los ajustes acercaron al número real?",
    description=(
        "Es la pregunta que nadie se hace y que decide si los ajustes sirven. Si "
        "no hay nada cerrado todavía se dice que no es medible, en vez de "
        "devolver un cero que parecería un acierto perfecto."
    ),
)
def acierto(clave: str, db: DbDep, principal: AutenticadoDep) -> Any:
    return forecast.acierto_de_los_ajustes(db, principal.tenant_id, clave)


# ── Instantáneas y waterfall ──────────────────────────────────────────────


class Instantanea(BaseModel):
    etiqueta: str = Field("", max_length=120)
    moneda: str = Field("", max_length=3)


@router_forecast.post(
    "/periodos/{clave}/instantaneas",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("opportunity:write"))],
    summary="Congelar la previsión de hoy",
    description=(
        "Sin fotos no hay waterfall: «qué ha cambiado desde el lunes» no se "
        "puede contestar mirando solo el estado de hoy, y reconstruirlo desde el "
        "historial es caro y frágil. Se guarda el estado de cada oportunidad, no "
        "una referencia: si apuntara a la oportunidad, la foto cambiaría con ella "
        "y dejaría de ser una foto."
    ),
)
def tomar_instantanea(
    clave: str, datos: Instantanea, uow: UowDep, principal: AutenticadoDep
) -> Any:
    foto = forecast.tomar_instantanea(
        uow.db,
        principal.tenant_id,
        clave,
        etiqueta=datos.etiqueta,
        por=principal.id,
        moneda=datos.moneda or None,
    )
    return {
        "id": str(foto.id),
        "etiqueta": foto.etiqueta,
        "totales": foto.totales,
        "oportunidades": foto.oportunidades,
    }


@router_forecast.get(
    "/periodos/{clave}/instantaneas",
    dependencies=[Depends(exige_permiso("opportunity:read"))],
    summary="Fotos del periodo",
)
def listar_instantaneas(clave: str, db: DbDep, principal: AutenticadoDep) -> Any:
    return [
        {
            "id": str(f.id),
            "etiqueta": f.etiqueta,
            "tomada_at": f.tomada_at.isoformat(),
            "moneda": f.moneda,
            "totales": f.totales,
            "oportunidades": f.oportunidades,
        }
        for f in forecast.instantaneas(db, principal.tenant_id, clave)
    ]


@router_forecast.get(
    "/waterfall",
    dependencies=[Depends(exige_permiso("opportunity:read"))],
    summary="Qué ha cambiado entre dos fotos, descompuesto",
    description=(
        "La diferencia entre dos totales no explica nada: «hemos bajado 300.000» "
        "no dice si es porque se ha perdido una operación grande, porque tres se "
        "han ido al trimestre siguiente o porque han bajado los importes. Las "
        "causas se separan porque cada una lleva a una conversación distinta.\n\n"
        "Salir de la foto no es lo mismo que perderse: mezclarlo inflaría la tasa "
        "de pérdida y llevaría a revisar un problema que no existe."
    ),
)
def waterfall(
    db: DbDep,
    principal: AutenticadoDep,
    desde: UUID = Query(description="Instantánea de partida"),
    hasta: UUID = Query(description="Instantánea de llegada"),
) -> Any:
    return forecast.waterfall(db, principal.tenant_id, desde, hasta)


# ── Deslizamiento ─────────────────────────────────────────────────────────


@router_forecast.get(
    "/periodos/{clave}/deslizamiento",
    dependencies=[Depends(exige_permiso("opportunity:read"))],
    summary="Cuánto se ha movido el periodo y cuántas veces",
    description=(
        "Se saca el número de veces, no solo los días: una oportunidad empujada "
        "cuatro veces dos semanas cada una no es lo mismo que otra movida dos "
        "meses de golpe, aunque el total coincida. La primera es un problema de "
        "calificación; la segunda, un cliente que cambió de plan."
    ),
)
def deslizamiento(clave: str, db: DbDep, principal: AutenticadoDep) -> Any:
    return forecast.deslizamiento(db, principal.tenant_id, clave)


@router_forecast.get(
    "/oportunidades/{oportunidad_id}/historial-prevision",
    dependencies=[Depends(exige_permiso("opportunity:read"))],
    summary="Cambios de importe y de fecha de esta oportunidad",
)
def historial(oportunidad_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return forecast.historial_de(db, principal.tenant_id, oportunidad_id)


# ── Listados de las sub-colecciones ───────────────────────────────────────
# Mismo agujero que en las colecciones raíz: se podían crear y no se podían
# leer. Un sobre de firma, una tabla del almacén o una predicción que no se
# pueden listar no existen para quien tiene que revisarlos.

montar_listado(
    router_forecast,
    modelo=PeriodoForecast,
    objeto="periodo_forecast",
    permiso="opportunity:read",
    ruta="/periodos",
    nombre="Periodos de previsión",
)


ROUTERS_FORECAST = [router_forecast]
