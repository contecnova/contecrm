"""Rutas de compras al proveedor (ver `services.party.compras`).

Las colecciones salen por `montar_listado` y `montar_ficha`, como el resto: así
tienen pestaña, ficha y acciones en el front oficial sin pantallas escritas a
mano. Las altas y las acciones van escritas aquí porque cada una comprueba algo
—que al proveedor se le pidiera oferta, que esté homologado, que la capacidad
alcance— y el alta genérica no sabría.

Las acciones que sólo leen —comparar, quién ha contestado, la fecha que se
puede prometer— van como `POST` sobre el registro, igual que las demás
preguntas del producto («Qué pasaría si…»): es la forma en que la ficha las
ofrece y enseña su respuesta.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from crmcore.http.listados import montar_ficha, montar_listado
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from services.party import compras as cmp

router_compras = APIRouter(prefix="/compras", tags=["compras al proveedor"])
router_proveedor_medido = APIRouter(prefix="/proveedores", tags=["proveedores"])


# ── Peticiones de oferta y respuestas (CRM-09.02.01.04, .05, .07, .08) ───


class CrearPeticion(BaseModel):
    categoria: str = Field(..., min_length=1, max_length=80)
    proveedores: list[UUID] = Field(..., min_length=1)
    fecha_limite: date
    descripcion: str = ""
    cantidad: Decimal = Field(Decimal(1), gt=0)
    unidad: str = "ud"
    fecha_necesaria: date | None = Field(
        None, description="Para cuándo hace falta: sin ella, el que llega tarde no se descarta"
    )
    oportunidad_id: UUID | None = Field(
        None,
        description=(
            "La oportunidad que la motiva. Una petición suelta no se cierra nunca: "
            "nadie sabe si aquello se ganó o se perdió"
        ),
    )


@router_compras.post(
    "/peticiones",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("party:write"))],
    summary="Pedir oferta a varios proveedores",
)
def crear_peticion(datos: CrearPeticion, uow: UowDep) -> Any:
    fila, aviso = cmp.crear_peticion(uow, **datos.model_dump())
    return {"id": str(fila.id), "estado": fila.estado, "aviso": aviso}


class RegistrarRespuesta(BaseModel):
    proveedor_id: UUID
    coste_unitario: Decimal = Field(..., ge=0)
    plazo_dias: int | None = Field(
        None,
        ge=0,
        description="Sin plazo no se inventa una fecha: se dice que no se puede prometer",
    )
    moneda: str = "EUR"
    recibida_el: date | None = None
    notas: str = ""


@router_compras.post(
    "/peticiones/{peticion_oferta_id}/respuestas",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("party:write"))],
    summary="Anotar lo que ha contestado un proveedor",
)
def registrar_respuesta(peticion_oferta_id: UUID, datos: RegistrarRespuesta, uow: UowDep) -> Any:
    fila = cmp.registrar_respuesta(uow, peticion_oferta_id, **datos.model_dump())
    return {"id": str(fila.id), "estado": fila.estado}


@router_compras.get(
    "/peticiones/{peticion_oferta_id}/respuestas",
    dependencies=[Depends(exige_permiso("party:read"))],
    summary="Las respuestas de esta petición",
)
def respuestas_de(peticion_oferta_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    cmp._uno(db, cmp.PeticionOferta, peticion_oferta_id, principal.tenant_id, "peticion")
    return {
        "items": [
            {
                "id": str(r.id),
                "proveedor_id": str(r.proveedor_id),
                "proveedor": cmp._nombre(db, principal.tenant_id, r.proveedor_id),
                "coste_unitario": str(r.coste_unitario),
                "moneda": r.moneda,
                "plazo_dias": r.plazo_dias,
                "recibida_el": r.recibida_el.isoformat(),
                "estado": r.estado,
            }
            for r in cmp._respuestas(db, principal.tenant_id, peticion_id=peticion_oferta_id)
        ]
    }


@router_compras.post(
    "/peticiones/{peticion_oferta_id}/quien-ha-contestado",
    dependencies=[Depends(exige_permiso("party:read"))],
    summary="Quién ha contestado, y sobre todo quién no",
)
def quien_ha_contestado(peticion_oferta_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return cmp.quien_ha_contestado(db, principal.tenant_id, peticion_oferta_id)


@router_compras.post(
    "/peticiones/{peticion_oferta_id}/comparar",
    dependencies=[Depends(exige_permiso("party:read"))],
    summary="Comparar las respuestas por coste, plazo y riesgo",
    description=(
        "Con lo que ya consta de cada proveedor: su homologación para la "
        "categoría de la petición, si tiene papeles vencidos que bloquean y la "
        "fecha que se puede prometer con su plazo. Se devuelven todas con su "
        "motivo de descarte, no sólo la ganadora."
    ),
)
def comparar(peticion_oferta_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return cmp.comparar(db, principal.tenant_id, peticion_oferta_id)


class Repartir(BaseModel):
    regla: str = Field(
        "menor_coste",
        description="menor_coste · mas_capacidad_libre · menor_plazo · por_acuerdo",
    )


@router_compras.post(
    "/peticiones/{peticion_oferta_id}/repartir",
    dependencies=[Depends(exige_permiso("party:read"))],
    summary="Repartir la cantidad entre quienes pueden servirla",
)
def repartir(
    peticion_oferta_id: UUID, datos: Repartir, db: DbDep, principal: AutenticadoDep
) -> Any:
    return cmp.repartir(db, principal.tenant_id, peticion_oferta_id, regla=datos.regla)


class Adjudicar(BaseModel):
    cantidad: Decimal | None = Field(None, gt=0, description="Vacío: la de la petición")
    forzar: bool = Field(False, description="Comprometer por encima de la capacidad libre")
    motivo: str = Field("", description="Obligatorio si se fuerza")


@router_compras.post(
    "/respuestas/{respuesta_oferta_id}/adjudicar",
    dependencies=[Depends(exige_permiso("party:write"))],
    summary="Adjudicar a este proveedor",
)
def adjudicar(respuesta_oferta_id: UUID, datos: Adjudicar, uow: UowDep) -> Any:
    return cmp.adjudicar(uow, respuesta_oferta_id, **datos.model_dump())


class Entrega(BaseModel):
    entregada_el: date | None = Field(None, description="Vacío: hoy")
    coste_final: Decimal | None = Field(
        None, ge=0, description="Lo que acabó costando, para medir el desvío"
    )


@router_compras.post(
    "/respuestas/{respuesta_oferta_id}/entrega",
    dependencies=[Depends(exige_permiso("party:write"))],
    summary="Anotar que se entregó, y lo que costó",
)
def anotar_entrega(respuesta_oferta_id: UUID, datos: Entrega, uow: UowDep) -> Any:
    fila = cmp.anotar_entrega(uow, respuesta_oferta_id, **datos.model_dump())
    return {"id": str(fila.id), "entregada_el": fila.entregada_el.isoformat()}


class Incidencia(BaseModel):
    gravedad: str = Field(..., description="baja · media · alta · critica")
    descripcion: str = Field(..., min_length=1)


@router_compras.post(
    "/respuestas/{respuesta_oferta_id}/incidencia",
    dependencies=[Depends(exige_permiso("party:write"))],
    summary="Anotar una incidencia del proveedor",
)
def anotar_incidencia(respuesta_oferta_id: UUID, datos: Incidencia, uow: UowDep) -> Any:
    fila = cmp.anotar_incidencia(uow, respuesta_oferta_id, **datos.model_dump())
    return {"id": str(fila.id), "incidencias": len(fila.incidencias)}


@router_compras.post(
    "/respuestas/{respuesta_oferta_id}/fecha-prometible",
    dependencies=[Depends(exige_permiso("party:read"))],
    summary="Qué fecha se le puede prometer al cliente con este proveedor",
)
def fecha_prometible(respuesta_oferta_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return cmp.fecha_prometible(db, principal.tenant_id, respuesta_oferta_id)


# ── Capacidad (CRM-09.02.01.06) ───────────────────────────────────────────


class CrearCapacidad(BaseModel):
    proveedor_id: UUID
    categoria: str = Field(..., min_length=1, max_length=80)
    desde: date
    hasta: date
    contratada: Decimal = Field(..., gt=0)
    unidad: str = "ud"


@router_compras.post(
    "/capacidades",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("party:write"))],
    summary="Declarar la capacidad contratada con un proveedor en un periodo",
)
def crear_capacidad(datos: CrearCapacidad, uow: UowDep) -> Any:
    from crmcore.errors import ErrorValidacion

    from services.party import proveedores as prv

    if datos.hasta < datos.desde:
        raise ErrorValidacion(
            "El periodo acaba antes de empezar.", error_code="capacidad.periodo_al_reves"
        )
    prv.exigir_proveedor(uow.db, uow.tenant_id, datos.proveedor_id)
    fila = cmp.CapacidadProveedor(tenant_id=uow.tenant_id, **datos.model_dump())
    uow.db.add(fila)
    uow.db.flush()
    return {"id": str(fila.id)}


@router_compras.post(
    "/capacidades/{capacidad_proveedor_id}/disponible",
    dependencies=[Depends(exige_permiso("party:read"))],
    summary="Cuánto queda de verdad con este proveedor",
)
def disponible(capacidad_proveedor_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return cmp.disponible(db, principal.tenant_id, capacidad_proveedor_id)


class Reservar(BaseModel):
    cantidad: Decimal = Field(..., gt=0)
    firme: bool = Field(
        True, description="Falso: está en una oferta abierta, todavía no comprometida"
    )
    forzar: bool = False
    motivo: str = ""
    oportunidad_id: UUID | None = None


@router_compras.post(
    "/capacidades/{capacidad_proveedor_id}/reservar",
    dependencies=[Depends(exige_permiso("party:write"))],
    summary="Comprometer capacidad, o negarse a hacerlo",
)
def reservar(capacidad_proveedor_id: UUID, datos: Reservar, uow: UowDep) -> Any:
    return cmp.reservar(uow, capacidad_proveedor_id, **datos.model_dump())


# ── Rappel (CRM-09.02.01.09) ──────────────────────────────────────────────


class CrearRappel(BaseModel):
    proveedor_id: UUID
    desde: date
    hasta: date
    tramos: list[dict[str, Any]] = Field(
        ..., min_length=1, description='[{"desde": 10000, "pct": 2}, …]'
    )


@router_compras.post(
    "/rappels",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("party:write"))],
    summary="Declarar los tramos de rappel de un proveedor",
)
def crear_rappel(datos: CrearRappel, uow: UowDep) -> Any:
    from services.party import proveedores as prv

    prv.exigir_proveedor(uow.db, uow.tenant_id, datos.proveedor_id)
    fila = cmp.AcuerdoRappel(tenant_id=uow.tenant_id, **datos.model_dump())
    uow.db.add(fila)
    uow.db.flush()
    return {"id": str(fila.id)}


@router_compras.post(
    "/rappels/{acuerdo_rappel_id}/estimado",
    dependencies=[Depends(exige_permiso("party:read"))],
    summary="Qué se recuperará, con lo comprado de verdad",
)
def rappel_estimado(acuerdo_rappel_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return cmp.rappel(db, principal.tenant_id, acuerdo_rappel_id)


# ── Contrato (CRM-09.01.01.07) y alcance (CRM-09.01.01.09) ───────────────


class CrearContrato(BaseModel):
    proveedor_id: UUID
    numero: str = ""
    vigente_desde: date | None = None
    vigente_hasta: date | None = Field(
        None, description="Sin fecha no es indefinido: es que nadie la ha escrito, y se dirá"
    )
    renovacion_automatica: bool = False
    dias_preaviso: int = Field(0, ge=0, le=365)
    notas: str = ""


@router_compras.post(
    "/contratos",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("party:write"))],
    summary="Registrar el contrato con un proveedor",
)
def crear_contrato(datos: CrearContrato, uow: UowDep) -> Any:
    from services.party import proveedores as prv

    prv.exigir_proveedor(uow.db, uow.tenant_id, datos.proveedor_id)
    fila = cmp.ContratoProveedor(tenant_id=uow.tenant_id, **datos.model_dump())
    uow.db.add(fila)
    uow.db.flush()
    return {"id": str(fila.id)}


@router_compras.post(
    "/contratos/{contrato_proveedor_id}/estado",
    dependencies=[Depends(exige_permiso("party:read"))],
    summary="Qué hay que hacer con este contrato, mirando lo comprometido",
)
def estado_del_contrato(contrato_proveedor_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return cmp.estado_del_contrato(db, principal.tenant_id, contrato_proveedor_id)


class CrearAlcance(BaseModel):
    proveedor_id: UUID
    alcance: dict[str, list[str]] = Field(
        ..., description="Por eje: categoria, geografia, cliente y canal"
    )


@router_compras.post(
    "/alcances",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("party:write"))],
    summary="Declarar qué puede servir un proveedor, en positivo",
)
def crear_alcance(datos: CrearAlcance, uow: UowDep) -> Any:
    from crmcore import proveedores_comercial as pcom
    from crmcore.errors import Conflicto

    from services.party import proveedores as prv

    prv.exigir_proveedor(uow.db, uow.tenant_id, datos.proveedor_id)
    from sqlalchemy import select

    if uow.db.execute(
        select(cmp.AlcanceProveedor).where(
            cmp.AlcanceProveedor.tenant_id == uow.tenant_id,
            cmp.AlcanceProveedor.proveedor_id == datos.proveedor_id,
        )
    ).scalar_one_or_none():
        raise Conflicto(
            "Ese proveedor ya tiene su alcance declarado: edítalo.",
            error_code="alcance.ya_existe",
        )
    revision = pcom.declarar_alcance(alcance=datos.alcance)
    fila = cmp.AlcanceProveedor(
        tenant_id=uow.tenant_id, proveedor_id=datos.proveedor_id, alcance=datos.alcance
    )
    uow.db.add(fila)
    uow.db.flush()
    return {"id": str(fila.id), **revision}


class PuedeServir(BaseModel):
    categoria: str = ""
    geografia: str = ""
    cliente_id: str | None = None


@router_compras.post(
    "/alcances/{alcance_proveedor_id}/puede-servir",
    dependencies=[Depends(exige_permiso("party:read"))],
    summary="Si este proveedor puede atender este caso, y por qué no",
)
def puede_servir(
    alcance_proveedor_id: UUID, datos: PuedeServir, db: DbDep, principal: AutenticadoDep
) -> Any:
    fila = cmp._uno(db, cmp.AlcanceProveedor, alcance_proveedor_id, principal.tenant_id, "alcance")
    return cmp.puede_servir(db, principal.tenant_id, fila.proveedor_id, **datos.model_dump())


# ── El proveedor, medido (CRM-09.01.01.04, .05, .10) ─────────────────────


@router_proveedor_medido.post(
    "/riesgo-medido",
    dependencies=[Depends(exige_permiso("party:read"))],
    summary="Dónde duele si un proveedor falla mañana, con lo comprado de verdad",
    description=(
        "La concentración sale de lo adjudicado a cada proveedor, y las "
        "alternativas de quienes están homologados hoy para sus mismas "
        "categorías. La ruta `/proveedores/riesgo` sigue publicada para quien "
        "integre con sus propios datos."
    ),
)
def riesgo_medido(db: DbDep, principal: AutenticadoDep) -> Any:
    return cmp.riesgo_de_dependencia(db, principal.tenant_id)


@router_proveedor_medido.post(
    "/{cuenta_id}/evaluacion-medida",
    dependencies=[Depends(exige_permiso("party:read"))],
    summary="Cómo va este proveedor, con las entregas y las incidencias anotadas",
)
def evaluacion_medida(cuenta_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return cmp.evaluacion(db, principal.tenant_id, cuenta_id)


@router_proveedor_medido.post(
    "/{cuenta_id}/baja-con-lo-comprometido",
    dependencies=[Depends(exige_permiso("party:read"))],
    summary="Si se puede dar de baja, con lo que tiene adjudicado y sin entregar",
)
def baja_con_lo_comprometido(cuenta_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return cmp.puede_darse_de_baja(db, principal.tenant_id, cuenta_id)


# ── Listados y fichas ─────────────────────────────────────────────────────

for _modelo, _objeto, _ruta, _nombre, _editable in (
    (
        cmp.PeticionOferta,
        "peticion_oferta",
        "/peticiones",
        "Peticiones de oferta",
        frozenset({"descripcion", "fecha_limite", "fecha_necesaria", "estado"}),
    ),
    (
        cmp.RespuestaOferta,
        "respuesta_oferta",
        "/respuestas",
        "Respuestas de proveedor",
        frozenset({"coste_unitario", "plazo_dias", "notas"}),
    ),
    (
        cmp.CapacidadProveedor,
        "capacidad_proveedor",
        "/capacidades",
        "Capacidad de proveedor",
        frozenset({"hasta", "contratada"}),
    ),
    (
        cmp.ReservaCapacidad,
        "reserva_capacidad",
        "/reservas",
        "Reservas de capacidad",
        # Sólo el motivo: la cantidad y si es firme se cambian liberando y
        # reservando otra vez, que es lo que deja rastro.
        frozenset({"motivo"}),
    ),
    (
        cmp.AcuerdoRappel,
        "acuerdo_rappel",
        "/rappels",
        "Rappels",
        frozenset({"hasta", "tramos", "cerrado"}),
    ),
    (
        cmp.ContratoProveedor,
        "contrato_proveedor",
        "/contratos",
        "Contratos de proveedor",
        frozenset(
            {
                "numero",
                "vigente_desde",
                "vigente_hasta",
                "renovacion_automatica",
                "dias_preaviso",
                "notas",
            }
        ),
    ),
    (
        cmp.AlcanceProveedor,
        "alcance_proveedor",
        "/alcances",
        "Alcance de proveedor",
        frozenset({"alcance"}),
    ),
):
    montar_listado(
        router_compras,
        modelo=_modelo,
        objeto=_objeto,
        permiso="party:read",
        permiso_escribir="party:write",
        nombre=_nombre,
        ruta=_ruta,
        ficha=False,
    )
    montar_ficha(
        router_compras,
        modelo=_modelo,
        objeto=_objeto,
        permiso_leer="party:read",
        permiso_escribir="party:write",
        nombre=_nombre,
        ruta=_ruta,
        editable=_editable,
    )

ROUTERS_COMPRAS = [router_compras, router_proveedor_medido]
