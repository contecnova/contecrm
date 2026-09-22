"""API HTTP del servicio de atención (CRM-04.01.01, CRM-04.01.02)."""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from services.service import servicio as svc
from services.service.modelos import Caso, CategoriaCaso, DefinicionSLA, EventoCaso

router_casos = APIRouter(prefix="/casos", tags=["casos"])
router_taxonomia = APIRouter(prefix="/categorias-caso", tags=["casos"])
router_sla = APIRouter(prefix="/sla", tags=["SLA"])


# ── Taxonomía (CRM-04.01.01.02) ───────────────────────────────────────────


class CrearCategoria(BaseModel):
    clave: str = Field(max_length=80)
    nombre: str = Field(max_length=200)
    padre_id: UUID | None = None
    linea: str = Field("general", max_length=60)
    orden: int = 100
    seleccionable: bool = True
    prioridad_sugerida: str | None = None


@router_taxonomia.get(
    "",
    dependencies=[Depends(exige_permiso("case:read"))],
    summary="Árbol de clasificación de casos",
    description=(
        "Es un árbol y no dos campos fijos porque cada línea de servicio "
        "clasifica a su profundidad: soporte de software llega a tres niveles y "
        "mantenimiento de instalaciones a cinco. Con dos campos, el tercer nivel "
        "acaba concatenado dentro del segundo y los informes dejan de agrupar."
    ),
)
def arbol(db: DbDep, principal: AutenticadoDep, linea: str = Query("", max_length=60)) -> Any:
    return svc.arbol_de_categorias(db, principal.tenant_id, linea)


@router_taxonomia.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Añadir un nodo al árbol",
)
def crear_categoria(datos: CrearCategoria, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = CategoriaCaso(tenant_id=principal.tenant_id, **datos.model_dump())
    uow.db.add(fila)
    uow.db.flush()
    return {"id": str(fila.id), "clave": fila.clave, "nombre": fila.nombre}


# ── SLA (CRM-04.01.02.02) ─────────────────────────────────────────────────


class CrearSLA(BaseModel):
    clave: str = Field(max_length=60)
    nombre: str = Field(max_length=200)
    prioridad: str | None = None
    tier_cliente: str | None = None
    cuenta_id: UUID | None = None
    horas_primera_respuesta: float | None = None
    horas_resolucion: float | None = None
    horas_actualizacion: float | None = None
    calendario: str = Field("", max_length=60)
    aviso_pct: int = Field(80, ge=10, le=100)


@router_sla.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Publicar una definición de SLA",
    description=(
        "Cada publicación es una **versión nueva**: cambiar el SLA no reescribe "
        "el pasado. Un contrato renegociado no puede convertir en incumplidos "
        "casos que se atendieron a tiempo con las reglas de entonces, ni al "
        "revés — y esa es la trampa del SLA guardado como una fila que se edita."
    ),
)
def crear_sla(datos: CrearSLA, uow: UowDep, principal: AutenticadoDep) -> Any:
    from sqlalchemy import func as _func

    ultima = uow.db.execute(
        select(_func.max(DefinicionSLA.version)).where(
            DefinicionSLA.tenant_id == principal.tenant_id,
            DefinicionSLA.clave == datos.clave,
        )
    ).scalar_one()
    fila = DefinicionSLA(
        tenant_id=principal.tenant_id, version=int(ultima or 0) + 1, **datos.model_dump()
    )
    uow.db.add(fila)
    uow.db.flush()
    return {"id": str(fila.id), "clave": fila.clave, "version": fila.version}


@router_sla.get(
    "",
    dependencies=[Depends(exige_permiso("case:read"))],
    summary="Definiciones de SLA vigentes",
)
def listar_sla(db: DbDep, principal: AutenticadoDep) -> Any:
    filas = (
        db.execute(
            select(DefinicionSLA)
            .where(DefinicionSLA.tenant_id == principal.tenant_id)
            .order_by(DefinicionSLA.clave, DefinicionSLA.version.desc())
        )
        .scalars()
        .all()
    )
    return [
        {
            "clave": f.clave,
            "version": f.version,
            "nombre": f.nombre,
            "prioridad": f.prioridad,
            "tier_cliente": f.tier_cliente,
            "horas_primera_respuesta": float(f.horas_primera_respuesta or 0) or None,
            "horas_resolucion": float(f.horas_resolucion or 0) or None,
            "calendario": f.calendario,
            "activa": f.activa,
        }
        for f in filas
    ]


@router_sla.get(
    "/en-riesgo",
    dependencies=[Depends(exige_permiso("case:read"))],
    summary="Casos que van a incumplir si nadie hace nada",
    description=(
        "Avisar **cuando ya se ha incumplido** no sirve de nada: el "
        "incumplimiento ya está. Lo único que cambia algo es avisar antes.\n\n"
        "Se ordena por lo que **queda**, no por prioridad: un caso crítico con "
        "seis horas por delante puede esperar a uno medio que vence en diez "
        "minutos. Y lo ya incumplido se marca aparte, para que la lista no se "
        "llene de cosas sin remedio y deje de mirarse."
    ),
)
def en_riesgo(
    db: DbDep, principal: AutenticadoDep, umbral_pct: int = Query(80, ge=1, le=100)
) -> Any:
    return svc.en_riesgo(db, principal.tenant_id, umbral_pct=umbral_pct)


@router_sla.get(
    "/cumplimiento",
    dependencies=[Depends(exige_permiso("case:read"))],
    summary="Cumplimiento de SLA del periodo",
    description=(
        "La primera respuesta y la resolución se cuentan **aparte**: un "
        "porcentaje único esconde que se contesta rápido y se resuelve tarde, "
        "que es el patrón más común y el que más queja genera.\n\n"
        "Sin casos con compromiso no se dice 100 %: sería un verde que nadie se "
        "ha ganado."
    ),
)
def cumplimiento(
    db: DbDep,
    principal: AutenticadoDep,
    desde: date = Query(...),
    hasta: date = Query(...),
) -> Any:
    return svc.cumplimiento(db, principal.tenant_id, desde=desde, hasta=hasta)


# ── Casos ─────────────────────────────────────────────────────────────────


class AbrirCaso(BaseModel):
    asunto: str = Field(max_length=300)
    descripcion: str | None = None
    tipo: str = Field("incidencia", max_length=40)
    categoria_id: UUID | None = None
    prioridad: str | None = None
    severidad: str | None = None
    origen: str = Field("manual", max_length=30)
    cuenta_id: UUID | None = None
    contacto_id: UUID | None = None
    producto_id: UUID | None = None
    activo_id: UUID | None = None
    contrato_id: UUID | None = None
    pedido_id: UUID | None = None
    padre_id: UUID | None = None
    owner_id: UUID | None = None
    equipo: str | None = None
    tier_cliente: str = ""
    campos: dict[str, Any] = Field(default_factory=dict)


@router_casos.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Abrir un caso",
    description=(
        "**Severidad y prioridad son dos campos.** La severidad es del problema "
        "—qué está roto y cuánto— y la prioridad es de la respuesta —en qué "
        "orden se atiende—. Fundirlas hace imposible decir «esto es grave pero "
        "puede esperar» y «esto es menor pero es para el cliente que renueva el "
        "viernes», y en cuanto se funden alguien marca todo como crítico.\n\n"
        "Solo las **hojas** del árbol clasifican: dejar elegir un nodo intermedio "
        "convierte «software» en un cajón donde acaba la mitad de los casos."
    ),
)
def abrir(datos: AbrirCaso, uow: UowDep, principal: AutenticadoDep) -> Any:
    cuerpo = datos.model_dump(exclude_none=True)
    tier = cuerpo.pop("tier_cliente", "")
    asunto = cuerpo.pop("asunto")
    caso = svc.abrir_caso(uow, asunto=asunto, tier_cliente=tier, **cuerpo)
    return {
        "id": str(caso.id),
        "codigo": caso.codigo,
        "prioridad": caso.prioridad,
        "sla": caso.sla_clave,
        "vence_primera_respuesta_at": (
            caso.vence_primera_respuesta_at.isoformat() if caso.vence_primera_respuesta_at else None
        ),
        "vence_resolucion_at": (
            caso.vence_resolucion_at.isoformat() if caso.vence_resolucion_at else None
        ),
        # Se dice cuando no hay SLA: un caso sin compromiso no es un caso
        # cumplido, y si no se dice aquí nadie lo mira hasta el informe de fin de
        # mes, donde sale como «sin datos».
        "aviso": ""
        if caso.sla_clave
        else "No hay ninguna definición de SLA que aplique a este caso",
    }


@router_casos.get(
    "",
    dependencies=[Depends(exige_permiso("case:read"))],
    summary="Buscar casos",
)
def listar(
    db: DbDep,
    principal: AutenticadoDep,
    estado: str = Query("", max_length=30),
    prioridad: str = Query("", max_length=20),
    cuenta_id: UUID | None = Query(None),
    limite: int = Query(50, ge=1, le=200),
) -> Any:
    consulta = select(Caso).where(Caso.tenant_id == principal.tenant_id, Caso.deleted_at.is_(None))
    if estado:
        consulta = consulta.where(Caso.estado == estado)
    if prioridad:
        consulta = consulta.where(Caso.prioridad == prioridad)
    if cuenta_id:
        consulta = consulta.where(Caso.cuenta_id == cuenta_id)
    filas = db.execute(consulta.order_by(Caso.created_at.desc()).limit(limite)).scalars().all()
    return [
        {
            "id": str(f.id),
            "codigo": f.codigo,
            "asunto": f.asunto,
            "estado": f.estado,
            "prioridad": f.prioridad,
            "severidad": f.severidad,
            "vence_resolucion_at": (
                f.vence_resolucion_at.isoformat() if f.vence_resolucion_at else None
            ),
            "incumplio_resolucion": f.incumplio_resolucion,
        }
        for f in filas
    ]


@router_casos.get(
    "/{caso_id}",
    dependencies=[Depends(exige_permiso("case:read"))],
    summary="Ficha del caso",
)
def leer(caso_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    caso = svc.exigir_caso(db, caso_id)
    eventos = (
        db.execute(
            select(EventoCaso)
            .where(EventoCaso.caso_id == caso.id, EventoCaso.tenant_id == principal.tenant_id)
            .order_by(EventoCaso.created_at)
        )
        .scalars()
        .all()
    )
    return {
        "id": str(caso.id),
        "codigo": caso.codigo,
        "asunto": caso.asunto,
        "descripcion": caso.descripcion,
        "estado": caso.estado,
        "prioridad": caso.prioridad,
        "severidad": caso.severidad,
        "clasificacion": svc.ruta_de_categoria(db, principal.tenant_id, caso.categoria_id)
        if caso.categoria_id
        else [],
        "campos": dict(caso.campos or {}),
        "sla": {
            "clave": caso.sla_clave,
            "version": caso.sla_version,
            "vence_primera_respuesta_at": (
                caso.vence_primera_respuesta_at.isoformat()
                if caso.vence_primera_respuesta_at
                else None
            ),
            "vence_resolucion_at": (
                caso.vence_resolucion_at.isoformat() if caso.vence_resolucion_at else None
            ),
            "primera_respuesta_at": (
                caso.primera_respuesta_at.isoformat() if caso.primera_respuesta_at else None
            ),
            "pausa_acumulada_s": caso.pausa_acumulada_s,
            "incumplio_primera_respuesta": caso.incumplio_primera_respuesta,
            "incumplio_resolucion": caso.incumplio_resolucion,
        },
        "relaciones": svc.arbol_de_caso(db, principal.tenant_id, caso.id),
        "historial": [
            {"tipo": e.tipo, "detalle": e.detalle, "at": e.created_at.isoformat()} for e in eventos
        ],
    }


class CambiarEstado(BaseModel):
    estado: str = Field(max_length=30)
    motivo: str = ""


@router_casos.put(
    "/{caso_id}/estado",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Mover el caso de estado",
    description=(
        "Entrar en «esperando cliente» **para el reloj** y salir lo reanuda "
        "desplazando el vencimiento por el tiempo parado. Si no se desplazara, "
        "parar el reloj sería decorativo: el caso se marcaría incumplido por una "
        "espera que era del cliente.\n\n"
        "La pausa se **acumula**: un caso que entra y sale cuatro veces perdería "
        "tres de las cuatro esperas si solo se guardara la última."
    ),
)
def cambiar_estado(
    caso_id: UUID, datos: CambiarEstado, uow: UowDep, principal: AutenticadoDep
) -> Any:
    caso = svc.cambiar_estado(uow, caso_id, estado=datos.estado, motivo=datos.motivo)
    return {"id": str(caso.id), "estado": caso.estado, "pausa_s": caso.pausa_acumulada_s}


@router_casos.post(
    "/{caso_id}/primera-respuesta",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Marcar la primera respuesta",
    description=(
        "Solo la primera cuenta: registrar cada respuesta como «primera» haría "
        "que el indicador midiera la última, que es el número que siempre sale "
        "bien."
    ),
)
def primera_respuesta(caso_id: UUID, uow: UowDep, principal: AutenticadoDep) -> Any:
    caso = svc.registrar_primera_respuesta(uow, caso_id, por=principal.usuario_id)
    return {
        "id": str(caso.id),
        "primera_respuesta_at": (
            caso.primera_respuesta_at.isoformat() if caso.primera_respuesta_at else None
        ),
        "a_tiempo": not caso.incumplio_primera_respuesta,
    }


class CerrarCaso(BaseModel):
    motivo: str = Field(min_length=1, max_length=80)
    resolucion: str = ""
    exige_validacion: bool = False


@router_casos.post(
    "/{caso_id}/cerrar",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Cerrar el caso con un motivo tipificado",
    description=(
        "El motivo es **obligatorio**. Sin él, el informe de cierres dice "
        "cuántos se cerraron y no por qué, que es la única parte útil: "
        "«resuelto», «no era un problema» y «el cliente no contestó» llevan a "
        "tres decisiones distintas."
    ),
)
def cerrar(caso_id: UUID, datos: CerrarCaso, uow: UowDep, principal: AutenticadoDep) -> Any:
    caso = svc.cerrar_caso(
        uow,
        caso_id,
        motivo=datos.motivo,
        resolucion=datos.resolucion,
        exige_validacion=datos.exige_validacion,
    )
    return {
        "id": str(caso.id),
        "estado": caso.estado,
        "incumplio_resolucion": caso.incumplio_resolucion,
        "validacion_cliente": caso.validacion_cliente,
    }


class ReabrirCaso(BaseModel):
    motivo: str = Field(min_length=1, max_length=1000)


@router_casos.post(
    "/{caso_id}/reabrir",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Reabrir un caso cerrado",
    description=(
        "Dentro de la ventana configurada. Pasada, **no se reabre**: se abre uno "
        "nuevo enlazado. Reabrir un caso de hace ocho meses falsea todos los "
        "indicadores del periodo en que se cerró —tiempo de resolución, "
        "cumplimiento, casos cerrados— y esos números ya están en un informe que "
        "alguien miró."
    ),
)
def reabrir(caso_id: UUID, datos: ReabrirCaso, uow: UowDep, principal: AutenticadoDep) -> Any:
    caso = svc.reabrir_caso(uow, caso_id, motivo=datos.motivo)
    return {"id": str(caso.id), "estado": caso.estado, "reaperturas": caso.reaperturas}


class Enlace(BaseModel):
    maestro_id: UUID


@router_casos.post(
    "/{caso_id}/maestro",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Colgar el caso de una incidencia masiva",
    description=(
        "Cien casos que son la misma caída se cuelgan de uno: se investiga una "
        "vez y se cierran juntos. Cerrarlos uno a uno no solo es trabajo, es que "
        "la respuesta que recibe cada cliente acaba siendo distinta."
    ),
)
def enlazar(caso_id: UUID, datos: Enlace, uow: UowDep, principal: AutenticadoDep) -> Any:
    caso = svc.enlazar_a_maestro(uow, caso_id, datos.maestro_id)
    return {"id": str(caso.id), "maestro_id": str(caso.maestro_id)}


@router_casos.post(
    "/{caso_id}/cerrar-masiva",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Cerrar el maestro y todos los casos colgados",
)
def cerrar_masiva(caso_id: UUID, datos: CerrarCaso, uow: UowDep, principal: AutenticadoDep) -> Any:
    return svc.cerrar_masiva(uow, caso_id, motivo=datos.motivo, resolucion=datos.resolucion)


class Duplicado(BaseModel):
    original_id: UUID


@router_casos.post(
    "/{caso_id}/duplicado",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Marcar como duplicado de otro",
    description=(
        "No se borra: el cliente que lo abrió tiene derecho a ver su caso y su "
        "respuesta. Borrarlo hace que su referencia deje de existir, y quien "
        "pregunta por ella recibe un «no existe» que suena a que nadie le "
        "atendió."
    ),
)
def duplicado(caso_id: UUID, datos: Duplicado, uow: UowDep, principal: AutenticadoDep) -> Any:
    caso = svc.marcar_duplicado(uow, caso_id, datos.original_id)
    return {"id": str(caso.id), "duplicado_de": str(caso.duplicado_de_id)}


ROUTERS = [router_casos, router_taxonomia, router_sla]
