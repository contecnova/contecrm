"""API de servicio de campo y activos instalados (CRM-04.04.01 y CRM-04.04.02).

`/sincronizacion` está aparte del resto a propósito: es la única ruta pensada para
que la llame un móvil que ha estado sin red, y lo que devuelve no es «ok», es el
resultado **de cada cambio** — aplicado, duplicado, en conflicto o rechazado.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from services.service import activos as act
from services.service import campo

router = APIRouter(prefix="/ordenes-trabajo", tags=["campo"])
router_tecnicos = APIRouter(prefix="/tecnicos-campo", tags=["campo"])
router_repuestos = APIRouter(prefix="/repuestos", tags=["campo"])
router_planes = APIRouter(prefix="/planes-preventivos", tags=["campo"])
router_sync = APIRouter(prefix="/sincronizacion-campo", tags=["campo"])
router_activos = APIRouter(prefix="/activos", tags=["activos"])


# ── Cuerpos ───────────────────────────────────────────────────────────────


class CrearTecnico(BaseModel):
    usuario_id: UUID
    nombre: str = ""
    zonas: list[str] = Field(
        default_factory=list,
        description="Vacío = cubre todas: un dato que falta no deja sin trabajo",
    )
    competencias: list[dict[str, Any]] = Field(
        default_factory=list,
        description="{clave, nivel}: «sabe de» y «está certificado en» no son lo mismo",
    )
    base_latitud: Decimal | None = None
    base_longitud: Decimal | None = None
    minutos_jornada: int = 480


class CrearOrden(BaseModel):
    titulo: str = Field(..., min_length=1, max_length=300)
    tipo: str = "correctivo"
    descripcion: str = ""
    caso_id: UUID | None = None
    activo_id: UUID | None = None
    cuenta_id: UUID | None = None
    direccion: str = ""
    latitud: Decimal | None = None
    longitud: Decimal | None = None
    zona: str | None = None
    prioridad: str = "media"
    competencias: list[str] = Field(default_factory=list)
    duracion_estimada_min: int = 60
    ventana_desde: datetime | None = None
    ventana_hasta: datetime | None = None


class Asignar(BaseModel):
    tecnico_id: UUID
    cita_desde: datetime | None = None
    cita_hasta: datetime | None = None
    forzar: bool = False
    motivo: str = ""


class Linea(BaseModel):
    tipo: str = Field(..., description="material · tiempo · desplazamiento · otro")
    concepto: str = ""
    cantidad: Decimal = Decimal(1)
    unidad: str = "ud"
    repuesto_id: UUID | None = None
    precio: Decimal | None = None
    desde: datetime | None = None
    hasta: datetime | None = None
    facturable: bool = True


class Completar(BaseModel):
    resumen: str = ""
    diagnostico: str = ""
    checklist: list[dict[str, Any]] = Field(default_factory=list)
    evidencias: list[dict[str, Any]] = Field(
        default_factory=list, description="Referencias al gestor documental, no binarios"
    )
    forzar: bool = False


class Firmar(BaseModel):
    firmado_por: str = Field(..., min_length=1)
    conforme: bool = True
    motivo_no_conforme: str = ""
    documento_id: UUID | None = None


class Movimiento(BaseModel):
    tecnico_id: UUID
    repuesto_id: UUID
    tipo: str = Field(..., description="carga · consumo · devolucion · ajuste · merma")
    cantidad: Decimal
    orden_id: UUID | None = None
    motivo: str = ""


class CrearPlan(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=200)
    activo_id: UUID
    cada_dias: int | None = None
    cada_contador: Decimal | None = None
    duracion_min: int = 60
    competencias: list[str] = Field(default_factory=list)
    checklist: list[dict[str, Any]] = Field(default_factory=list)
    antelacion_dias: int = 15


class Sincronizar(BaseModel):
    dispositivo: str = Field(..., min_length=1, max_length=120)
    cambios: list[dict[str, Any]] = Field(
        ...,
        description=(
            "Cada uno con su `id_cliente` generado en el móvil: reenviar el lote no " "duplica nada"
        ),
    )


class CrearActivo(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=200)
    numero_serie: str | None = None
    codigo: str | None = None
    modelo: str | None = None
    fabricante: str | None = None
    producto_id: UUID | None = None
    cuenta_id: UUID | None = None
    ubicacion: str = ""
    latitud: Decimal | None = None
    longitud: Decimal | None = None
    instalado_el: date | None = None
    padre_id: UUID | None = None
    contador: Decimal | None = None
    unidad_contador: str | None = None


class CrearGarantia(BaseModel):
    desde: date
    hasta: date
    tipo: str = "fabricante"
    cobertura: list[str] = Field(
        default_factory=list, description="piezas · mano_obra · desplazamiento"
    )
    referencia: str = ""
    proveedor: str = ""
    limite_contador: Decimal | None = None
    exclusiones: str = ""


class Sustituir(BaseModel):
    nuevo_nombre: str = Field(..., min_length=1)
    numero_serie: str | None = None
    motivo: str = Field(..., min_length=1)
    modelo: str | None = None
    heredar_garantias: bool = False


class Lectura(BaseModel):
    valor: Decimal
    unidad: str | None = None


# ── Técnicos ──────────────────────────────────────────────────────────────


@router_tecnicos.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Dar de alta un técnico de campo",
)
def crear_tecnico(datos: CrearTecnico, uow: UowDep) -> Any:
    fila = campo.Tecnico(tenant_id=uow.tenant_id, **datos.model_dump())
    uow.db.add(fila)
    uow.db.flush()
    return {"id": str(fila.id), "usuario_id": str(fila.usuario_id)}


@router_tecnicos.get(
    "",
    dependencies=[Depends(exige_permiso("case:read"))],
    summary="Técnicos de campo",
)
def listar_tecnicos(db: DbDep, principal: AutenticadoDep) -> Any:
    filas = (
        db.execute(select(campo.Tecnico).where(campo.Tecnico.tenant_id == principal.tenant_id))
        .scalars()
        .all()
    )
    return {
        "tecnicos": [
            {
                "id": str(f.id),
                "usuario_id": str(f.usuario_id),
                "nombre": f.nombre,
                "zonas": f.zonas,
                "competencias": f.competencias,
                "activo": f.activo,
                "base_conocida": f.base_latitud is not None,
            }
            for f in filas
        ]
    }


@router_tecnicos.get(
    "/{tecnico_id}/ruta",
    dependencies=[Depends(exige_permiso("case:read"))],
    summary="Ruta del día",
    description=(
        "Heurística del más cercano desde la base del técnico, con el tiempo de "
        "viaje estimado **en línea recta** (`estimacion: linea_recta`). Lo que no "
        "tiene coordenadas va al final y se dice: presentarlo como óptimo sería "
        "presentar el orden de la lista como una ruta."
    ),
)
def ruta(
    tecnico_id: UUID,
    dia: date,
    db: DbDep,
    principal: AutenticadoDep,
    velocidad_kmh: Decimal | None = Query(None),
) -> Any:
    return campo.planificar_ruta(
        db, principal.tenant_id, tecnico_id=tecnico_id, dia=dia, velocidad_kmh=velocidad_kmh
    )


# ── Órdenes de trabajo ────────────────────────────────────────────────────


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Crear una orden de trabajo",
    description="Nace en borrador y devuelve qué no se podrá hacer con lo que falta.",
)
def crear_orden(datos: CrearOrden, uow: UowDep) -> Any:
    fila, avisos = campo.crear_orden(uow, **datos.model_dump())
    return {"id": str(fila.id), "estado": fila.estado, "avisos": avisos}


@router.get(
    "",
    dependencies=[Depends(exige_permiso("case:read"))],
    summary="Órdenes de trabajo",
)
def listar_ordenes(
    db: DbDep,
    principal: AutenticadoDep,
    estado: str | None = Query(None),
    tecnico_id: UUID | None = Query(None),
    limite: int = Query(50, ge=1, le=200),
) -> Any:
    consulta = select(campo.OrdenTrabajo).where(campo.OrdenTrabajo.tenant_id == principal.tenant_id)
    if estado:
        consulta = consulta.where(campo.OrdenTrabajo.estado == estado)
    if tecnico_id:
        consulta = consulta.where(campo.OrdenTrabajo.tecnico_id == tecnico_id)
    filas = (
        db.execute(consulta.order_by(campo.OrdenTrabajo.cita_desde.desc()).limit(limite))
        .scalars()
        .all()
    )
    return {
        "ordenes": [
            {
                "id": str(f.id),
                "codigo": f.codigo,
                "titulo": f.titulo,
                "tipo": f.tipo,
                "estado": f.estado,
                "prioridad": f.prioridad,
                "tecnico_id": str(f.tecnico_id) if f.tecnico_id else None,
                "cita_desde": f.cita_desde.isoformat() if f.cita_desde else None,
                "firmado": bool(f.firmado_at),
                "conforme": f.conforme,
            }
            for f in filas
        ]
    }


@router.get(
    "/{orden_id}",
    dependencies=[Depends(exige_permiso("case:read"))],
    summary="Una orden con su parte y su reparto de cobertura",
    description=(
        "Las tres cestas van separadas: lo que paga el cliente, lo que se reclama "
        "al fabricante y lo que **no se sabe**. Fundir la tercera es facturar mal "
        "o perder una reclamación."
    ),
)
def detalle_orden(orden_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return campo.resumen_orden(db, principal.tenant_id, orden_id)


@router.get(
    "/{orden_id}/candidatos",
    dependencies=[Depends(exige_permiso("case:read"))],
    summary="Quién puede hacerla, y por qué no puede el resto",
    description=(
        "La lista de descartados es la mitad del valor: «nadie disponible» por "
        "competencia, por zona o por bajas son tres decisiones distintas."
    ),
)
def ver_candidatos(orden_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return campo.candidatos(db, principal.tenant_id, orden_id)


@router.post(
    "/{orden_id}/asignar",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Asignar técnico y cita",
    description=(
        "Sin las competencias exigidas no asigna, salvo `forzar` **con motivo**: "
        "mandar al que casi puede es a veces lo correcto, pero tiene que quedar "
        "escrito que se hizo a sabiendas."
    ),
)
def asignar(orden_id: UUID, datos: Asignar, uow: UowDep) -> Any:
    fila, avisos = campo.asignar(uow, orden_id, **datos.model_dump())
    return {"id": str(fila.id), "estado": fila.estado, "avisos": avisos}


@router.post(
    "/{orden_id}/lineas",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Apuntar material, tiempo o desplazamiento",
    description=(
        "El material descuenta de la furgoneta, y la cobertura de garantía se "
        "calcula al apuntar: el técnico tiene que poder decir ahí mismo si eso lo "
        "paga el cliente."
    ),
)
def anotar_linea(orden_id: UUID, datos: Linea, uow: UowDep) -> Any:
    fila, avisos = campo.anotar_linea(uow, orden_id, **datos.model_dump())
    return {
        "id": str(fila.id),
        "cubierto_garantia": fila.cubierto_garantia,
        "nota_cobertura": fila.nota_cobertura,
        "avisos": avisos,
    }


@router.post(
    "/{orden_id}/iniciar",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Empezar el trabajo",
)
def iniciar(orden_id: UUID, uow: UowDep) -> Any:
    fila = campo.iniciar(uow, orden_id)
    return {"id": str(fila.id), "estado": fila.estado}


@router.post(
    "/{orden_id}/pausar",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Pausar con motivo",
)
def pausar(orden_id: UUID, uow: UowDep, motivo: str = Query(..., min_length=1)) -> Any:
    fila = campo.pausar(uow, orden_id, motivo=motivo)
    return {"id": str(fila.id), "estado": fila.estado, "motivo": fila.motivo_estado}


@router.post(
    "/{orden_id}/completar",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Completar el trabajo y dejar el parte",
    description=(
        "Un checklist con obligatorios sin responder no cierra salvo `forzar`: uno "
        "que se puede dejar a medias se deja a medias, y entonces no vale ni como "
        "control ni como prueba."
    ),
)
def completar(orden_id: UUID, datos: Completar, uow: UowDep) -> Any:
    fila, informe = campo.completar(uow, orden_id, **datos.model_dump())
    return {"id": str(fila.id), "estado": fila.estado, **informe}


@router.post(
    "/{orden_id}/firmar",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Firma del cliente sobre el parte",
    description=(
        "Guarda la **huella de lo firmado**: una conformidad que no dice sobre qué "
        "se dio no sirve el día que se discute lo que se hizo. Se admite firmar no "
        "conforme con motivo — exigir conformidad hace que firme el técnico."
    ),
)
def firmar(orden_id: UUID, datos: Firmar, uow: UowDep) -> Any:
    return campo.firmar(uow, orden_id, **datos.model_dump())


@router.post(
    "/{orden_id}/cerrar",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Cerrar la orden tras revisarla",
)
def cerrar(orden_id: UUID, uow: UowDep, forzar: bool = Query(False)) -> Any:
    fila = campo.cerrar(uow, orden_id, forzar=forzar)
    plan = campo.registrar_preventivo_hecho(uow, orden_id)
    return {
        "id": str(fila.id),
        "estado": fila.estado,
        "plan_reprogramado": str(plan.proxima_fecha) if plan and plan.proxima_fecha else None,
    }


# ── Repuestos y almacén móvil ─────────────────────────────────────────────


@router_repuestos.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Dar de alta un repuesto",
)
def crear_repuesto(
    uow: UowDep,
    sku: str = Query(..., min_length=1),
    nombre: str = Query(..., min_length=1),
    unidad: str = Query("ud"),
) -> Any:
    fila = campo.Repuesto(tenant_id=uow.tenant_id, sku=sku, nombre=nombre, unidad=unidad)
    uow.db.add(fila)
    uow.db.flush()
    return {"id": str(fila.id), "sku": fila.sku}


@router_repuestos.get(
    "",
    dependencies=[Depends(exige_permiso("case:read"))],
    summary="Repuestos",
)
def listar_repuestos(db: DbDep, principal: AutenticadoDep) -> Any:
    filas = (
        db.execute(select(campo.Repuesto).where(campo.Repuesto.tenant_id == principal.tenant_id))
        .scalars()
        .all()
    )
    return {
        "repuestos": [
            {
                "id": str(f.id),
                "sku": f.sku,
                "nombre": f.nombre,
                "unidad": f.unidad,
                "activo": f.activo,
            }
            for f in filas
        ]
    }


@router_repuestos.post(
    "/movimientos",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Mover stock de la furgoneta",
    description=(
        "**No se bloquea por falta de stock.** Si el técnico dice que ha montado la "
        "pieza, está montada: lo que está mal es el stock. El saldo queda en "
        "negativo y se marca, que es la lista que hay que revisar."
    ),
)
def mover(datos: Movimiento, uow: UowDep) -> Any:
    return campo.mover_repuesto(uow, **datos.model_dump())


@router_repuestos.get(
    "/reposicion",
    dependencies=[Depends(exige_permiso("case:read"))],
    summary="Qué hay que cargar",
)
def reposicion(db: DbDep, principal: AutenticadoDep, tecnico_id: UUID | None = Query(None)) -> Any:
    return campo.reposicion(db, principal.tenant_id, tecnico_id=tecnico_id)


# ── Preventivo ────────────────────────────────────────────────────────────


@router_planes.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Crear un plan preventivo",
    description="Por días, por uso o por los dos: lo que antes llegue.",
)
def crear_plan(datos: CrearPlan, uow: UowDep) -> Any:
    fila = campo.crear_plan(uow, **datos.model_dump())
    return {"id": str(fila.id), "proxima_fecha": str(fila.proxima_fecha or "")}


@router_planes.get(
    "",
    dependencies=[Depends(exige_permiso("case:read"))],
    summary="Planes preventivos",
)
def listar_planes(db: DbDep, principal: AutenticadoDep) -> Any:
    filas = (
        db.execute(
            select(campo.PlanPreventivo).where(
                campo.PlanPreventivo.tenant_id == principal.tenant_id
            )
        )
        .scalars()
        .all()
    )
    return {
        "planes": [
            {
                "id": str(f.id),
                "nombre": f.nombre,
                "activo_id": str(f.activo_id),
                "cada_dias": f.cada_dias,
                "cada_contador": str(f.cada_contador) if f.cada_contador else None,
                "proxima_fecha": str(f.proxima_fecha) if f.proxima_fecha else None,
                "activo": f.activo,
            }
            for f in filas
        ]
    }


@router_planes.get(
    "/vencimientos",
    dependencies=[Depends(exige_permiso("case:read"))],
    summary="Qué toca revisar y por qué",
    description=(
        "Dice si vence **por calendario o por uso**: una es «toca la revisión "
        "anual» y la otra es «esta máquina ha trabajado el doble de lo previsto»."
    ),
)
def vencimientos(db: DbDep, principal: AutenticadoDep) -> Any:
    return campo.vencimientos(db, principal.tenant_id)


@router_planes.post(
    "/generar",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Generar las órdenes preventivas que tocan",
    description=(
        "Una por plan a la vez: un plan mensual desatendido seis meses generaría "
        "seis órdenes idénticas, y lo que se hace entonces es cerrarlas sin mirar."
    ),
)
def generar(uow: UowDep) -> Any:
    return campo.generar_preventivas(uow)


# ── Sincronización del móvil ──────────────────────────────────────────────


@router_sync.post(
    "",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Volcar el trabajo hecho sin red",
    description=(
        "Idempotente por `id_cliente`, guarda el reloj del móvil aparte del del "
        "servidor y **devuelve los conflictos en vez de resolverlos**: elegir "
        "automáticamente significa perder media jornada de alguien en silencio."
    ),
)
def sincronizar(datos: Sincronizar, uow: UowDep) -> Any:
    return campo.sincronizar(uow, dispositivo=datos.dispositivo, cambios=datos.cambios)


# ── Activos instalados ────────────────────────────────────────────────────


@router_activos.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Dar de alta un activo instalado",
    description=(
        "Dos activos vivos con la misma serie se rechazan: significan una "
        "sustitución que nadie registró, y mezclan dos historiales."
    ),
)
def crear_activo(datos: CrearActivo, uow: UowDep) -> Any:
    fila, avisos = act.crear(uow, **datos.model_dump())
    return {"id": str(fila.id), "codigo": fila.codigo, "avisos": avisos}


@router_activos.get(
    "",
    dependencies=[Depends(exige_permiso("case:read"))],
    summary="Activos instalados",
)
def listar_activos(
    db: DbDep,
    principal: AutenticadoDep,
    cuenta_id: UUID | None = Query(None),
    limite: int = Query(50, ge=1, le=200),
) -> Any:
    if cuenta_id:
        return {"activos": act.parque_de(db, principal.tenant_id, cuenta_id)}
    filas = (
        db.execute(
            select(act.ActivoInstalado)
            .where(act.ActivoInstalado.tenant_id == principal.tenant_id)
            .order_by(act.ActivoInstalado.nombre)
            .limit(limite)
        )
        .scalars()
        .all()
    )
    return {
        "activos": [
            {
                "id": str(f.id),
                "codigo": f.codigo,
                "nombre": f.nombre,
                "modelo": f.modelo,
                "numero_serie": f.numero_serie,
                "estado": f.estado,
                "ubicacion": f.ubicacion,
                "contador": str(f.contador) if f.contador is not None else None,
            }
            for f in filas
        ]
    }


@router_activos.get(
    "/{activo_id}/arbol",
    dependencies=[Depends(exige_permiso("case:read"))],
    summary="El activo y sus componentes",
)
def arbol(activo_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return act.arbol(db, principal.tenant_id, activo_id)


@router_activos.get(
    "/{activo_id}/historial",
    dependencies=[Depends(exige_permiso("case:read"))],
    summary="Historial del activo y de a lo que sustituyó",
    description=(
        "La pregunta real no es «¿qué le pasó a esta máquina?», es «¿esto ya había "
        "fallado antes?», y la respuesta suele estar en el equipo anterior — que "
        "sale marcado para no inflar la tasa de avería de este."
    ),
)
def historial(activo_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return act.historial(db, principal.tenant_id, activo_id)


@router_activos.get(
    "/{activo_id}/cobertura",
    dependencies=[Depends(exige_permiso("case:read"))],
    summary="Si algo está cubierto por garantía",
    description=(
        "Sin garantías registradas devuelve `concluyente: false`, no «no cubierto»: "
        "un `false` por falta de datos factura al cliente que sí tenía cobertura."
    ),
)
def cobertura(
    activo_id: UUID,
    db: DbDep,
    principal: AutenticadoDep,
    concepto: str = Query("piezas", description="piezas · mano_obra · desplazamiento"),
) -> Any:
    return act.cobertura_de(db, principal.tenant_id, activo_id, concepto=concepto)


@router_activos.post(
    "/{activo_id}/garantias",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Registrar una garantía",
)
def crear_garantia(activo_id: UUID, datos: CrearGarantia, uow: UowDep) -> Any:
    fila = act.registrar_garantia(uow, activo_id, **datos.model_dump())
    return {"id": str(fila.id), "hasta": str(fila.hasta), "cobertura": fila.cobertura}


@router_activos.get(
    "/garantias/por-vencer",
    dependencies=[Depends(exige_permiso("case:read"))],
    summary="Garantías que vencen pronto",
)
def por_vencer(db: DbDep, principal: AutenticadoDep, dias: int | None = Query(None)) -> Any:
    return act.garantias_por_vencer(db, principal.tenant_id, dias=dias)


@router_activos.post(
    "/{activo_id}/sustituir",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Sustituir el equipo, dejando los dos enlazados",
    description=(
        "Las garantías **no se heredan por defecto**: heredarlas en silencio daría "
        "cobertura a una máquina que nadie aseguró."
    ),
)
def sustituir(activo_id: UUID, datos: Sustituir, uow: UowDep) -> Any:
    fila = act.sustituir(uow, activo_id, **datos.model_dump())
    return {"id": str(fila.id), "sustituye_a": str(fila.sustituye_a_id)}


@router_activos.post(
    "/{activo_id}/contador",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Anotar una lectura del contador de uso",
    description=(
        "Una lectura que baja se acepta y se marca: rechazarla haría que el técnico "
        "no anotara nada, que es peor."
    ),
)
def contador(activo_id: UUID, datos: Lectura, uow: UowDep) -> Any:
    return act.leer_contador(uow, activo_id, **datos.model_dump())


@router_activos.post(
    "/{activo_id}/padre",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Mover un componente de equipo",
)
def mover_componente(
    activo_id: UUID,
    uow: UowDep,
    nuevo_padre_id: UUID | None = Query(None),
    motivo: str = Query(""),
) -> Any:
    fila = act.mover_componente(uow, activo_id, nuevo_padre_id=nuevo_padre_id, motivo=motivo)
    return {"id": str(fila.id), "padre_id": str(fila.padre_id) if fila.padre_id else None}


ROUTERS_CAMPO = [
    router,
    router_tecnicos,
    router_repuestos,
    router_planes,
    router_sync,
    router_activos,
]
