"""API de telemetría de dispositivos y de modelo canónico
(CRM-04.04.02.05, CRM-00.03.04.08, CRM-00.03.04.09)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from crmcore.http.listados import montar_ficha
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from services.integration import canonico as can
from services.integration import telemetria as tel


class LadoQueGana(BaseModel):
    """Qué versión se queda cuando las dos han cambiado."""

    gana: Literal["nuestro", "externo"] = Field(..., description="Qué lado prevalece")


router = APIRouter(prefix="/dispositivos", tags=["telemetria"])
router_canonico = APIRouter(prefix="/modelo-canonico", tags=["canonico"])
router_sync = APIRouter(prefix="/sincronizacion", tags=["canonico"])


class CrearDispositivo(BaseModel):
    identificador: str = Field(..., min_length=1, max_length=120)
    nombre: str = ""
    activo_id: UUID | None = None
    cuenta_id: UUID | None = None
    modelo: str | None = None
    cadencia_min: int | None = Field(
        None, description="Cada cuánto debería dar señal; sin esto no se detecta el silencio"
    )


class CrearReglaTelemetria(BaseModel):
    clave: str = Field(..., min_length=1, max_length=80)
    condiciones: list[dict[str, Any]] = Field(..., min_length=1)
    accion: str = Field("aviso", description="caso · preventivo · aviso")
    nombre: str = ""
    severidad: str = "media"
    asunto: str = ""
    modelo: str | None = None
    silencio_min: int | None = None
    repeticiones: int = 1


class Ingesta(BaseModel):
    identificador: str = Field(..., min_length=1)
    metrica: str = ""
    valor: Decimal | None = None
    datos: dict[str, Any] = Field(default_factory=dict)
    medido_at: datetime | None = None


class DefinirObjeto(BaseModel):
    clave: str = Field(..., min_length=1, max_length=80)
    campos: list[dict[str, Any]] = Field(..., min_length=1)
    nombre: str = ""
    descripcion: str = ""
    claves_negocio: list[str] = Field(default_factory=list)


class RegistrarAdaptador(BaseModel):
    objeto: str
    sistema: str
    mapeo: dict[str, str]
    politica: str = Field("manual", description="nuestro · externo · reciente · manual")
    politica_por_campo: dict[str, str] = Field(default_factory=dict)
    direccion: str = "ambas"
    direccion_por_campo: dict[str, str] = Field(default_factory=dict)
    campo_modificado: str | None = None


class Emparejar(BaseModel):
    objeto: str
    sistema: str
    registro_id: UUID
    id_externo: str


class Conciliar(BaseModel):
    objeto: str
    sistema: str
    id_externo: str
    nuestro: dict[str, Any] = Field(default_factory=dict)
    suyo: dict[str, Any] = Field(default_factory=dict)
    modificado_nuestro: datetime | None = None
    modificado_suyo: datetime | None = None


# ── Telemetría ────────────────────────────────────────────────────────────


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("integracion:write"))],
    summary="Dar de alta un dispositivo",
)
def crear_dispositivo(datos: CrearDispositivo, uow: UowDep) -> Any:
    fila, avisos = tel.registrar_dispositivo(uow, **datos.model_dump())
    return {"id": str(fila.id), "identificador": fila.identificador, "avisos": avisos}


@router.get(
    "",
    dependencies=[Depends(exige_permiso("integracion:read"))],
    summary="Dispositivos",
)
def listar(db: DbDep, principal: AutenticadoDep, limite: int = Query(50, ge=1, le=200)) -> Any:
    filas = (
        db.execute(
            select(tel.Dispositivo)
            .where(tel.Dispositivo.tenant_id == principal.tenant_id)
            .limit(limite)
        )
        .scalars()
        .all()
    )
    return {
        "dispositivos": [
            {
                "id": str(f.id),
                "identificador": f.identificador,
                "nombre": f.nombre,
                "activo_id": str(f.activo_id) if f.activo_id else None,
                "cadencia_min": f.cadencia_min,
                "ultima_lectura_at": (
                    f.ultima_lectura_at.isoformat() if f.ultima_lectura_at else None
                ),
                "activo": f.activo,
            }
            for f in filas
        ]
    }


@router.post(
    "/reglas",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("integracion:write"))],
    summary="Declarar cuándo una lectura merece abrir algo",
    description=(
        "Con ventana de silencio y repeticiones: sin ellas, un aparato que se "
        "vuelve loco abre mil casos y tumba la cola de soporte."
    ),
)
def crear_regla(datos: CrearReglaTelemetria, uow: UowDep) -> Any:
    fila = tel.crear_regla(uow, **datos.model_dump())
    return {"id": str(fila.id), "clave": fila.clave, "accion": fila.accion}


@router.post(
    "/lecturas",
    dependencies=[Depends(exige_permiso("integracion:write"))],
    summary="Ingerir una lectura",
    description=(
        "Devuelve **qué se hizo y por qué**, no «ok»: si se descartó por no cruzar "
        "umbral, si se agrupó bajo un caso ya abierto o si abrió uno. El caso lo "
        "abre `service` por comando; aquí consta *pedido*, no creado."
    ),
)
def ingerir(datos: Ingesta, uow: UowDep) -> Any:
    return tel.ingerir(uow, **datos.model_dump())


@router.get(
    "/silenciosos",
    dependencies=[Depends(exige_permiso("integracion:read"))],
    summary="Aparatos que han dejado de dar señal",
    description=(
        "Dejar de recibir es una señal. Los que **nunca** dieron señal van aparte: "
        "un aparato roto y uno sin instalar no son lo mismo."
    ),
)
def silenciosos(
    db: DbDep, principal: AutenticadoDep, factor: float = Query(3.0, ge=1.0, le=100.0)
) -> Any:
    return tel.silenciosos(db, principal.tenant_id, factor=factor)


# ── Modelo canónico ───────────────────────────────────────────────────────


@router_canonico.post(
    "/objetos",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("integracion:write"))],
    summary="Definir un objeto del idioma común",
)
def definir_objeto(datos: DefinirObjeto, uow: UowDep) -> Any:
    fila, avisos = can.definir_objeto(uow, **datos.model_dump())
    return {"id": str(fila.id), "clave": fila.clave, "avisos": avisos}


@router_canonico.get(
    "/objetos",
    dependencies=[Depends(exige_permiso("integracion:read"))],
    summary="Objetos canónicos",
)
def listar_objetos(db: DbDep, principal: AutenticadoDep) -> Any:
    filas = (
        db.execute(
            select(can.ObjetoCanonico).where(can.ObjetoCanonico.tenant_id == principal.tenant_id)
        )
        .scalars()
        .all()
    )
    return {
        "objetos": [
            {
                "id": str(f.id),
                "clave": f.clave,
                "nombre": f.nombre,
                "campos": f.campos,
                "claves_negocio": f.claves_negocio,
            }
            for f in filas
        ]
    }


@router_canonico.post(
    "/adaptadores",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("integracion:write"))],
    summary="Declarar cómo traduce un sistema externo",
    description=(
        "Comprueba que lo mapeado existe: un campo mal escrito no falla, deja de "
        "sincronizarse en silencio y se descubre con los datos ya divergidos."
    ),
)
def registrar_adaptador(datos: RegistrarAdaptador, uow: UowDep) -> Any:
    fila, avisos = can.registrar_adaptador(uow, **datos.model_dump())
    return {"id": str(fila.id), "sistema": fila.sistema, "avisos": avisos}


@router_canonico.post(
    "/traducir",
    dependencies=[Depends(exige_permiso("integracion:read"))],
    summary="Traducir un registro externo al idioma común",
    description="Lo que llega sin mapear **se devuelve aparte**, no se tira.",
)
def traducir(
    db: DbDep,
    principal: AutenticadoDep,
    objeto: str = Query(...),
    sistema: str = Query(...),
    externo: dict[str, Any] | None = None,
) -> Any:
    return can.a_canonico(
        db, principal.tenant_id, objeto=objeto, sistema=sistema, externo=externo or {}
    )


# ── Sincronización bidireccional ──────────────────────────────────────────


@router_sync.post(
    "/vinculos",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("integracion:write"))],
    summary="Emparejar un registro nuestro con uno suyo",
)
def emparejar(datos: Emparejar, uow: UowDep) -> Any:
    fila = can.emparejar(uow, **datos.model_dump())
    return {"id": str(fila.id), "en_conflicto": fila.en_conflicto}


@router_sync.post(
    "/conciliar",
    dependencies=[Depends(exige_permiso("integracion:write"))],
    summary="Decidir campo a campo qué valor gana",
    description=(
        "Devuelve lo que hay que escribir en cada lado y los conflictos que no se "
        "han podido decidir. **No escribe**: quien llama es el dueño de cada "
        "sistema. Un eco —lo que acabamos de escribir allí— se detecta y se dice."
    ),
)
def conciliar(datos: Conciliar, uow: UowDep) -> Any:
    return can.conciliar(uow, **datos.model_dump())


@router_sync.get(
    "/conflictos",
    dependencies=[Depends(exige_permiso("integracion:read"))],
    summary="Conflictos sin resolver",
    description=(
        "Con el número de veces que ha vuelto cada uno: un conflicto que se repite "
        "cada hora se arregla cambiando la política, no resolviéndolo cien veces."
    ),
)
def conflictos(db: DbDep, principal: AutenticadoDep, sistema: str = Query("")) -> Any:
    return can.pendientes(db, principal.tenant_id, sistema=sistema)


@router_sync.post(
    "/conflictos/{conflicto_id}/resolver",
    dependencies=[Depends(exige_permiso("integracion:write"))],
    summary="Elegir un lado",
)
def resolver(
    conflicto_id: UUID,
    uow: UowDep,
    datos: LadoQueGana,
    principal: AutenticadoDep,
) -> Any:
    return can.resolver_conflicto(uow, conflicto_id, gana=datos.gana, por=principal.id)


ROUTERS_TELEMETRIA = [router, router_canonico, router_sync]


# ── La ficha del registro ─────────────────────────────────────────────────
# Sin ella, las acciones que cuelgan de un registro no se alcanzan desde
# ninguna pantalla: existen, se prueban y nadie las usa.
montar_ficha(
    router_sync,
    modelo=can.ConflictoSincronizacion,
    objeto="conflicto_sincronizacion",
    permiso_leer="integracion:read",
    permiso_escribir="integracion:write",
    nombre="Conflictos de sincronización",
    ruta="/conflictos",
    parametro="conflicto_id",
)
