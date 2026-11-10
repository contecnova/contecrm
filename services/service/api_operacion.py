"""API de colas, agentes, escalado, entitlements y satisfacción
(CRM-04.01.01.05 a .12, CRM-04.01.02.01 a .08, CRM-04.02.02.03).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from crmcore.http.listados import montar_listado
from crmcore.logging import get_logger
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from services.service import entitlements as ent
from services.service import operacion as ope
from services.service import servicio as svc
from services.service.entitlements import CreditoServicio, Encuesta, Entitlement
from services.service.operacion import AgenteServicio, ColaCasos, ReglaAsignacion, ReglaEscalada

logger = get_logger(__name__)

router_colas = APIRouter(prefix="/colas", tags=["casos"])
router_agentes = APIRouter(prefix="/agentes", tags=["casos"])
router_escalado = APIRouter(prefix="/escalado", tags=["casos"])
router_entitlements = APIRouter(prefix="/entitlements", tags=["SLA"])
router_encuestas = APIRouter(prefix="/encuestas", tags=["satisfacción"])
router_creditos = APIRouter(prefix="/creditos-servicio", tags=["SLA"])


# ── Colas (CRM-04.01.01.05) ───────────────────────────────────────────────


class CrearCola(BaseModel):
    clave: str = Field(max_length=80)
    nombre: str = Field(max_length=200)
    descripcion: str = ""
    miembros: list[UUID] = Field(default_factory=list)
    canales: list[str] = Field(default_factory=list)
    competencias: list[str] = Field(default_factory=list)
    nivel: int = Field(1, ge=1, le=9)


@router_colas.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Crear una cola de trabajo",
    description=(
        "La cola no es redundante con la asignación automática: es **el sitio "
        "donde cae lo que no se ha podido asignar**. Sin ella, un caso que "
        "ninguna regla sabe repartir se queda sin dueño y sin lista, que es el "
        "único estado del que nadie se entera."
    ),
)
def crear_cola(datos: CrearCola, uow: UowDep, principal: AutenticadoDep) -> Any:
    cuerpo = datos.model_dump()
    cuerpo["miembros"] = [str(m) for m in cuerpo["miembros"]]
    fila = ColaCasos(tenant_id=principal.tenant_id, **cuerpo)
    uow.db.add(fila)
    uow.db.flush()
    return {"id": str(fila.id), "clave": fila.clave}


# ── Reglas de reparto: verlas y quitarlas (CRM-04.01.01.05) ──────────────
#
# Se podían crear y no se podían ver: la regla entraba, repartía, y nadie podía
# saber cuáles había ni quitar la que sobraba. Van ANTES de `/{clave}`, que si
# no se queda con «reglas» como si fuera la clave de una cola.


@router_colas.get(
    "/reglas",
    dependencies=[Depends(exige_permiso("case:read"))],
    response_model=list[dict[str, Any]],
    summary="Reglas de reparto de casos",
    description="En el orden en que se evalúan: gana la primera que encaja.",
)
def listar_reglas(db: DbDep, principal: AutenticadoDep) -> Any:
    filas = (
        db.execute(
            select(ReglaAsignacion)
            .where(ReglaAsignacion.tenant_id == principal.tenant_id)
            .order_by(ReglaAsignacion.prioridad, ReglaAsignacion.nombre)
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(r.id),
            "nombre": r.nombre,
            "prioridad": r.prioridad,
            "activa": r.activa,
            "canal": r.canal,
            "estrategia": r.estrategia,
            "cola": r.cola,
            "competencias": list(r.competencias or []),
            "condiciones": list(r.condiciones or []),
        }
        for r in filas
    ]


@router_colas.delete(
    "/reglas/{regla_id}",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Quitar una regla de reparto",
    description="Lo ya repartido no se mueve: la traza de cada asignación guarda el nombre de la regla.",
)
def quitar_regla(regla_id: UUID, uow: UowDep, principal: AutenticadoDep) -> Any:
    from crmcore.errors import NoEncontrado

    fila = uow.db.get(ReglaAsignacion, regla_id)
    if fila is None or fila.tenant_id != principal.tenant_id:
        raise NoEncontrado("Esa regla no existe", error_code="service.regla_no_encontrada")
    uow.db.delete(fila)
    return {"id": str(regla_id), "quitada": True}


class CambiarCola(BaseModel):
    nombre: str | None = Field(None, max_length=200)
    descripcion: str | None = None
    miembros: list[UUID] | None = None
    canales: list[str] | None = None
    competencias: list[str] | None = None
    nivel: int | None = Field(None, ge=1, le=9)


@router_colas.patch(
    "/{clave}",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Cambiar una cola de trabajo",
    description=(
        "Quién coge de ella, por qué canales entra y con qué competencias. Se "
        "cambia **solo lo que se envía**.\n\n"
        "Por su clave y no por su identificador, igual que se abre: la cola se "
        "lee por `/colas/{clave}`, y editarla por otra llave obligaría a la "
        "pantalla a saber dos nombres de lo mismo. La clave no se cambia: los "
        "casos y las reglas de asignación apuntan a ella."
    ),
)
def cambiar_cola(clave: str, datos: CambiarCola, db: DbDep, principal: AutenticadoDep) -> Any:
    from crmcore.errors import NoEncontrado
    from sqlalchemy import select

    fila = db.execute(
        select(ColaCasos).where(
            ColaCasos.tenant_id == principal.tenant_id,
            ColaCasos.clave == clave,
            ColaCasos.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado("Esa cola no existe", error_code="cola.no_encontrada")
    for campo, valor in datos.model_dump(exclude_unset=True).items():
        # Un nulo explícito no vacía la cola: los campos de una cola no tienen
        # «sin valor», y vaciar los miembros se pide mandando la lista vacía.
        if valor is None:
            continue
        setattr(fila, campo, [str(m) for m in valor] if campo == "miembros" else valor)
    db.flush()
    return {
        "id": str(fila.id),
        "clave": fila.clave,
        "nombre": fila.nombre,
        "descripcion": fila.descripcion,
        "miembros": fila.miembros,
        "canales": fila.canales,
        "competencias": fila.competencias,
        "nivel": fila.nivel,
    }


@router_colas.get(
    "/{clave}",
    dependencies=[Depends(exige_permiso("case:read"))],
    summary="Lo que espera en una cola",
    description=(
        "Ordenado por **lo que vence antes**, no por prioridad ni por "
        "antigüedad: la pregunta de quien coge de una cola es «qué se me va a "
        "incumplir primero», y ordenar por prioridad deja un caso medio a punto "
        "de vencer debajo de uno crítico con dos días por delante.\n\n"
        "Los casos sin SLA se marcan: si no, quedan al final y parecen los menos "
        "urgentes cuando en realidad son los que nadie ha medido."
    ),
)
def ver_cola(
    clave: str, db: DbDep, principal: AutenticadoDep, limite: int = Query(100, ge=1, le=500)
) -> Any:
    return ope.cola(db, principal.tenant_id, clave, limite=limite)


@router_colas.post(
    "/{clave}/coger/{caso_id}",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Adjudicarse un caso de la cola",
    description=(
        "Se comprueba que siga libre: dos agentes mirando la misma cola pulsan a "
        "la vez, y sin esta comprobación el segundo se queda con el caso del "
        "primero sin que ninguno lo sepa."
    ),
)
def coger(clave: str, caso_id: UUID, uow: UowDep, principal: AutenticadoDep) -> Any:
    caso = ope.coger_de_cola(uow, caso_id, principal.id)
    return {"id": str(caso.id), "owner_id": str(caso.owner_id), "estado": caso.estado}


# ── Reglas de asignación (CRM-04.01.01.05, .06) ───────────────────────────


class CrearReglaAsignacion(BaseModel):
    nombre: str = Field(max_length=150)
    descripcion: str = ""
    prioridad: int = 100
    condiciones: list[dict[str, Any]] = Field(default_factory=list)
    combinacion: str = "todas"
    estrategia: str = "menos_carga"
    cola: str | None = None
    candidatos: list[UUID] = Field(default_factory=list)
    competencias: list[str] = Field(default_factory=list)
    canal: str = "caso"


@router_colas.post(
    "/reglas",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Regla de reparto de casos",
    description=(
        "Misma forma que las de leads a propósito: condiciones en el formato de "
        "ABAC, prioridad ascendente y gana **la primera** que encaja. Con varias "
        "que puntúan, explicar el resultado deja de ser posible y el supervisor "
        "pierde el control sobre su propio reparto.\n\n"
        "La estrategia `menos_carga_ponderada` reparte por **hueco libre** y no "
        "por carga absoluta: con carga absoluta, quien tiene capacidad 20 y lleva "
        "5 parece más ocupado que quien tiene capacidad 5 y lleva 4, y el reparto "
        "acaba saturando justo al que menos cabe."
    ),
)
def crear_regla(datos: CrearReglaAsignacion, uow: UowDep, principal: AutenticadoDep) -> Any:
    cuerpo = datos.model_dump()
    cuerpo["candidatos"] = [str(c) for c in cuerpo["candidatos"]]
    fila = ReglaAsignacion(tenant_id=principal.tenant_id, **cuerpo)
    uow.db.add(fila)
    uow.db.flush()
    return {"id": str(fila.id), "nombre": fila.nombre}


@router_colas.post(
    "/asignar/{caso_id}",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Asignar un caso por reglas",
)
def asignar(
    caso_id: UUID, uow: UowDep, principal: AutenticadoDep, canal: str = Query("caso")
) -> Any:
    caso = svc.exigir_caso(uow.db, caso_id)
    registro = ope.asignar(uow, caso, canal=canal)
    return {
        "caso_id": str(caso.id),
        "asignado_a": str(registro.asignado_a) if registro.asignado_a else None,
        "cola": registro.cola,
        "regla": registro.regla_nombre,
        "motivo": registro.motivo,
    }


@router_colas.get(
    "/explicar/{caso_id}",
    dependencies=[Depends(exige_permiso("case:read"))],
    summary="Por qué este caso acabó donde acabó",
    description=(
        "Con las reglas descartadas y el motivo de cada descarte. Sin esto, «¿por "
        "qué me ha caído a mí?» no tiene respuesta y el reparto automático deja "
        "de respetarse a la primera discusión.\n\n"
        "Se distingue «la regla no encaja» de «encajaba pero no había nadie con "
        "hueco»: son dos problemas distintos y confundirlos lleva a reescribir "
        "una regla que estaba bien."
    ),
)
def explicar(caso_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return ope.explicar_asignacion(db, principal.tenant_id, caso_id)


# ── Agentes (CRM-04.02.02.03) ─────────────────────────────────────────────


class Presencia(BaseModel):
    presencia: str = Field(description="disponible | ocupado | ausente | no_molestar | fuera")
    motivo: str = ""


@router_agentes.put(
    "/presencia",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Cambiar mi presencia",
    description=(
        "`ausente` y `no_molestar` se distinguen a propósito: el primero es «no "
        "está» y el segundo «está pero no puede». Fundirlos hace que un "
        "supervisor no pueda saber si le falta gente o le falta capacidad, que "
        "son dos problemas con soluciones opuestas.\n\n"
        "Se guarda **desde cuándo**: «lleva cuarenta minutos en no molestar» es "
        "una conversación distinta de «acaba de ponerse»."
    ),
)
def fijar_presencia(datos: Presencia, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = ope.fijar_presencia(
        uow.db,
        principal.tenant_id,
        principal.id,
        presencia=datos.presencia,
        motivo=datos.motivo,
    )
    return {"presencia": fila.presencia, "desde": fila.presencia_desde.isoformat()}


class ConfigurarAgente(BaseModel):
    usuario_id: UUID
    capacidad: dict[str, int] = Field(default_factory=dict)
    competencias: list[str] = Field(default_factory=list)
    nivel: int = Field(1, ge=1, le=9)
    activo: bool = True


@router_agentes.put(
    "",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Capacidad y competencias de un agente",
    description=(
        "La capacidad es **por canal** y no un número único: alguien puede llevar "
        "tres chats a la vez y una sola llamada. Con un número único, o se "
        "infradotan los chats o se satura el teléfono.\n\n"
        "Un canal sin tope declarado se considera **sin límite** y no cero: un "
        "agente al que nadie configuró la capacidad tiene que poder trabajar, y "
        "tratarlo como saturado dejaría la cola llena sin que nadie entendiera "
        "por qué."
    ),
)
def configurar_agente(datos: ConfigurarAgente, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = uow.db.execute(
        select(AgenteServicio).where(
            AgenteServicio.tenant_id == principal.tenant_id,
            AgenteServicio.usuario_id == datos.usuario_id,
        )
    ).scalar_one_or_none()
    if fila is None:
        fila = AgenteServicio(tenant_id=principal.tenant_id, usuario_id=datos.usuario_id)
        uow.db.add(fila)
    fila.capacidad = datos.capacidad
    fila.competencias = datos.competencias
    fila.nivel = datos.nivel
    fila.activo = datos.activo
    uow.db.flush()
    return {"usuario_id": str(fila.usuario_id), "capacidad": fila.capacidad}


@router_agentes.get(
    "",
    dependencies=[Depends(exige_permiso("case:read"))],
    response_model=list[dict[str, Any]],
    summary="Agentes de servicio",
    description=(
        "Todos los configurados, estén o no disponibles, con su presencia, su "
        "capacidad por canal y sus competencias. La capacidad y las "
        "competencias se podían fijar y no ver: el reparto por carga y "
        "competencia decidía con datos que nadie podía revisar."
    ),
)
def listar_agentes(db: DbDep, principal: AutenticadoDep) -> Any:
    filas = (
        db.execute(
            select(AgenteServicio)
            .where(AgenteServicio.tenant_id == principal.tenant_id)
            .order_by(AgenteServicio.presencia, AgenteServicio.usuario_id)
        )
        .scalars()
        .all()
    )
    carga = ope.carga_de(db, principal.tenant_id, [a.usuario_id for a in filas])
    return [
        {
            "id": str(a.usuario_id),
            "usuario_id": str(a.usuario_id),
            "presencia": a.presencia,
            "presencia_desde": a.presencia_desde.isoformat() if a.presencia_desde else None,
            "carga": carga.get(a.usuario_id, 0),
            **{f"capacidad_{c}": (a.capacidad or {}).get(c) for c in ope.CANALES},
            "competencias": list(a.competencias or []),
            "nivel": a.nivel,
            "activo": a.activo,
        }
        for a in filas
    ]


class AltaAgente(BaseModel):
    """Lo mismo que `PUT /agentes`, con la capacidad canal a canal.

    Un diccionario `{"chat": 3}` en un formulario es una caja de JSON; un
    número por canal es lo que un supervisor sabe rellenar. Vacío es «sin
    límite», no cero.
    """

    usuario_id: UUID
    capacidad_caso: int | None = Field(None, ge=0, le=500)
    capacidad_chat: int | None = Field(None, ge=0, le=50)
    capacidad_telefono: int | None = Field(None, ge=0, le=10)
    capacidad_correo: int | None = Field(None, ge=0, le=500)
    competencias: list[str] = Field(default_factory=list)
    nivel: int = Field(1, ge=1, le=9)
    activo: bool = True


@router_agentes.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Configurar un agente",
    description="Si ya estaba configurado, se sustituye su capacidad y sus competencias.",
)
def alta_agente(datos: AltaAgente, uow: UowDep, principal: AutenticadoDep) -> Any:
    capacidad = {c: v for c in ope.CANALES if (v := getattr(datos, f"capacidad_{c}")) is not None}
    return configurar_agente(
        ConfigurarAgente(
            usuario_id=datos.usuario_id,
            capacidad=capacidad,
            competencias=datos.competencias,
            nivel=datos.nivel,
            activo=datos.activo,
        ),
        uow,
        principal,
    )


@router_agentes.delete(
    "/{usuario_id}",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Dejar de tratarlo como agente",
    description="No toca sus casos: los que llevaba siguen siendo suyos.",
)
def quitar_agente(usuario_id: UUID, uow: UowDep, principal: AutenticadoDep) -> Any:
    from crmcore.errors import NoEncontrado

    fila = uow.db.execute(
        select(AgenteServicio).where(
            AgenteServicio.tenant_id == principal.tenant_id,
            AgenteServicio.usuario_id == usuario_id,
        )
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado(
            "No está configurado como agente", error_code="service.agente_no_encontrado"
        )
    uow.db.delete(fila)
    return {"usuario_id": str(usuario_id), "quitado": True}


@router_agentes.get(
    "/disponibles",
    dependencies=[Depends(exige_permiso("case:read"))],
    summary="Quién puede coger un caso ahora mismo",
    description=(
        "Filtra por presencia, competencias y **capacidad libre en ese canal**. "
        "Saltarse la capacidad convierte el reparto en un reparto formal: el caso "
        "figura asignado, nadie lo mira y el SLA corre igual — que es peor que "
        "dejarlo en cola, porque en cola al menos se ve."
    ),
)
def disponibles(
    db: DbDep,
    principal: AutenticadoDep,
    canal: str = Query("caso"),
    competencia: list[str] = Query(default=[]),
) -> Any:
    agentes = ope.agentes_disponibles(
        db, principal.tenant_id, canal=canal, competencias=list(competencia) or None
    )
    carga = ope.carga_de(db, principal.tenant_id, [a.usuario_id for a in agentes])
    return [
        {
            "usuario_id": str(a.usuario_id),
            "presencia": a.presencia,
            "capacidad": (a.capacidad or {}).get(canal),
            "carga": carga.get(a.usuario_id, 0),
            "competencias": a.competencias,
        }
        for a in agentes
    ]


# ── Escalado (CRM-04.01.01.07) y derivación (.08) ─────────────────────────


class CrearEscalada(BaseModel):
    nombre: str = Field(max_length=150)
    prioridad: int = 100
    consumido_pct: int | None = Field(None, ge=1, le=200)
    severidad_minima: str | None = None
    solo_vip: bool = False
    al_incumplir: bool = False
    subir_nivel: bool = True
    subir_prioridad: bool = False
    asignar_a: UUID | None = None
    cola_destino: str | None = None
    avisar_a: list[UUID] = Field(default_factory=list)


@router_escalado.post(
    "/reglas",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Regla de escalado",
    description=(
        "Los disparadores van declarados por separado —porcentaje consumido, "
        "severidad, cliente VIP, incumplimiento— y no como una condición "
        "genérica, porque son los cuatro que se usan de verdad y tenerlos "
        "explícitos es lo que permite explicarle al cliente **por qué** se escaló "
        "su caso."
    ),
)
def crear_escalada(datos: CrearEscalada, uow: UowDep, principal: AutenticadoDep) -> Any:
    cuerpo = datos.model_dump()
    cuerpo["avisar_a"] = [str(u) for u in cuerpo["avisar_a"]]
    fila = ReglaEscalada(tenant_id=principal.tenant_id, **cuerpo)
    uow.db.add(fila)
    uow.db.flush()
    return {"id": str(fila.id), "nombre": fila.nombre}


@router_escalado.post(
    "/evaluar",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Aplicar las reglas de escalado ahora",
    description=(
        "Se decide por **lo que queda**, no por lo que ha pasado: escalar cuando "
        "el SLA ya se ha incumplido llega tarde por definición.\n\n"
        "Un caso **no se escala dos veces por la misma regla**: si se escalara en "
        "cada pasada, el responsable recibiría el mismo aviso cada cinco minutos "
        "y dejaría de leerlos."
    ),
)
def evaluar(
    uow: UowDep,
    principal: AutenticadoDep,
    cuenta_vip: list[UUID] = Query(default=[]),
) -> Any:
    return ope.evaluar_escaladas(uow, principal.tenant_id, cuentas_vip=set(cuenta_vip) or None)


class Derivar(BaseModel):
    cola_destino: str = Field(max_length=80)
    motivo: str = Field(min_length=1, max_length=2000)
    interno: bool = False


@router_escalado.post(
    "/derivar/{caso_id}",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Pasar el caso a otro nivel o a una cola interna",
    description=(
        "El motivo es obligatorio: una derivación sin motivo obliga a quien la "
        "recibe a leerse el caso entero para averiguar qué se espera de él, y eso "
        "es lo que hace que las derivaciones reboten.\n\n"
        "**El caso sigue siendo del cliente.** Derivar no crea uno nuevo ni "
        "reinicia el reloj: el cliente no tiene por qué esperar otra vez desde "
        "cero porque hayamos movido su problema de mesa."
    ),
)
def derivar(caso_id: UUID, datos: Derivar, uow: UowDep, principal: AutenticadoDep) -> Any:
    caso = ope.derivar(
        uow,
        caso_id,
        cola_destino=datos.cola_destino,
        motivo=datos.motivo,
        interno=datos.interno,
    )
    return {"id": str(caso.id), "equipo": caso.equipo, "campos": caso.campos}


# ── Entitlements (CRM-04.01.02.01, .06) ───────────────────────────────────


class CrearEntitlement(BaseModel):
    clave: str = Field(max_length=60)
    nombre: str = Field(max_length=200)
    cuenta_id: UUID | None = None
    contrato_id: UUID | None = None
    producto_id: UUID | None = None
    plan: str | None = None
    sla_clave: str | None = None
    proveedor_clave: str | None = Field(
        None, max_length=60, description="Proveedor de servicio que lo da, si no lo damos nosotros"
    )
    casos_incluidos: int | None = None
    horas_incluidas: float | None = None
    al_agotar: str = Field("avisar", description="avisar | bloquear | facturar")
    vigente_desde: date
    vigente_hasta: date | None = None


@router_entitlements.post(
    "",
    status_code=status.HTTP_201_CREATED,
    # `entitlement:write` y no `case:write`. Dar de alta un derecho de servicio
    # es gestión del contrato, no trabajo de caso: fija a qué tiene derecho el
    # cliente y durante cuánto. Con `case:write` lo podía hacer **cualquier
    # agente**, y el catálogo de roles dice por escrito que de los derechos se
    # encarga `responsable_soporte` — la separación estaba prometida y no
    # existía (medido el 11-10-2026).
    dependencies=[Depends(exige_permiso("entitlement:write"))],
    summary="Dar de alta un derecho de servicio",
    description=(
        "Gana el **más específico**: contrato sobre producto, producto sobre "
        "cuenta y cuenta sobre plan. Al revés, un cliente con un contrato de "
        "soporte negociado aparte recibiría lo que le da su plan comercial — que "
        "es justo lo que pagó por mejorar.\n\n"
        "Qué pasa al agotar se **declara**: avisar, bloquear o facturar el exceso "
        "son las tres legítimas según contrato, y elegir por el cliente "
        "significaría cortarle el soporte a quien pagaba por el exceso."
    ),
)
def crear_entitlement(datos: CrearEntitlement, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = ent.Entitlement(tenant_id=principal.tenant_id, **datos.model_dump())
    uow.db.add(fila)
    uow.db.flush()
    return {"id": str(fila.id), "clave": fila.clave}


@router_entitlements.get(
    "/aplicable",
    dependencies=[Depends(exige_permiso("entitlement:read"))],
    summary="Qué derecho aplica a este cliente",
)
def aplicable(
    db: DbDep,
    principal: AutenticadoDep,
    cuenta_id: UUID | None = Query(None),
    contrato_id: UUID | None = Query(None),
    producto_id: UUID | None = Query(None),
    plan: str = Query(""),
) -> Any:
    fila = ent.entitlement_aplicable(
        db,
        principal.tenant_id,
        cuenta_id=cuenta_id,
        contrato_id=contrato_id,
        producto_id=producto_id,
        plan=plan,
    )
    if fila is None:
        return {"tiene_derecho": False}
    return {
        "tiene_derecho": True,
        "clave": fila.clave,
        "sla_clave": fila.sla_clave,
        "saldo": ent.saldo(db, principal.tenant_id, fila.id),
    }


class Imputar(BaseModel):
    caso_id: UUID | None = None
    horas: float = Field(0, ge=0)
    concepto: str = ""
    cuenta_como_caso: bool = True


@router_entitlements.post(
    "/{entitlement_id}/consumo",
    status_code=status.HTTP_201_CREATED,
    # Éste SÍ se queda en `case:write`, y es una decisión: imputar consumo es lo
    # que hace quien atiende el caso —apunta las horas que ha gastado— y
    # exigirle el permiso de gestionar derechos obligaría a que un responsable
    # cerrara cada caso. Lo que no puede hacer un agente es CREAR el derecho ni
    # cambiar a qué tiene derecho el cliente; gastar lo que ya tiene concedido
    # es su trabajo.
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Imputar consumo contra el derecho",
    description=(
        "**No bloquea aquí.** Comprobar el saldo y negarse a imputar haría que el "
        "trabajo ya hecho no se registrara, que es la peor combinación: se ha "
        "gastado y no consta. Se anota siempre y el saldo se consulta aparte.\n\n"
        "Una fila por apunte y no un contador: con un contador, un cliente que "
        "discute la factura no puede ver **qué** consumió, y la única respuesta "
        "posible es «el sistema dice que 40 horas»."
    ),
)
def imputar(entitlement_id: UUID, datos: Imputar, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = ent.imputar(
        uow,
        entitlement_id=entitlement_id,
        caso_id=datos.caso_id,
        horas=datos.horas,
        concepto=datos.concepto,
        cuenta_como_caso=datos.cuenta_como_caso,
        por=principal.id,
    )
    return {"id": str(fila.id), "saldo": ent.saldo(uow.db, principal.tenant_id, entitlement_id)}


@router_entitlements.get(
    "/{entitlement_id}/saldo",
    dependencies=[Depends(exige_permiso("entitlement:read"))],
    summary="Cuánto queda del derecho",
    description=(
        "Se devuelven las **dos bolsas** —casos y horas— aunque solo una esté "
        "limitada: enseñar solo la limitada hace que quien mira no sepa si la "
        "otra no se cuenta o es que nadie ha gastado.\n\n"
        "Y se avisa de la caducidad además del saldo: un derecho con 200 horas "
        "libres que vence el viernes es tan inservible como uno agotado."
    ),
)
def saldo(entitlement_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return ent.saldo(db, principal.tenant_id, entitlement_id)


# ── Satisfacción (CRM-04.01.01.12) ────────────────────────────────────────


class ProgramarEncuesta(BaseModel):
    caso_id: UUID
    tipo: str = Field("csat", description="csat | ces | nps")
    validez_dias: int = Field(14, ge=1, le=180)


@router_encuestas.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Enviar la encuesta tras cerrar",
    description=(
        "El token se devuelve **una sola vez** y se guarda hasheado: quien lea la "
        "tabla no puede contestar por el cliente.\n\n"
        "No se manda dos veces: recibir la misma encuesta cada vez que alguien "
        "toca el caso es la forma más rápida de que el cliente la marque como "
        "correo no deseado, y entonces se pierden todas las siguientes."
    ),
)
def programar(datos: ProgramarEncuesta, uow: UowDep, principal: AutenticadoDep) -> Any:
    caso = svc.exigir_caso(uow.db, datos.caso_id)
    fila, token = ent.programar_encuesta(
        uow, caso, tipo=datos.tipo, validez_dias=datos.validez_dias
    )
    return {"id": str(fila.id), "tipo": fila.tipo, "token": token}


class Responder(BaseModel):
    token: str = Field(min_length=1, max_length=200)
    puntuacion: int
    comentario: str = ""


@router_encuestas.post(
    "/{encuesta_id}/responder",
    summary="Responder la encuesta",
    description=(
        "No exige iniciar sesión: el cliente contesta con el enlace que recibió. "
        "Un token equivocado devuelve 404 y no 403, para no confirmar que esa "
        "encuesta existe."
    ),
)
def responder(encuesta_id: UUID, datos: Responder, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = ent.responder_encuesta(
        uow,
        encuesta_id=encuesta_id,
        token=datos.token,
        puntuacion=datos.puntuacion,
        comentario=datos.comentario,
    )
    return {"id": str(fila.id), "puntuacion": fila.puntuacion}


@router_encuestas.get(
    "/resumen",
    dependencies=[Depends(exige_permiso("case:read"))],
    summary="CSAT, CES y NPS del periodo",
    description=(
        "La **tasa de respuesta va junto al número**, no aparte: un CSAT de 4,8 "
        "sobre el 3 % de los clientes no es un CSAT de 4,8, y enseñarlos "
        "separados hace que el primero se cite y el segundo no.\n\n"
        "Se guarda la invitación aunque nadie conteste: sin saber a cuántos se "
        "preguntó, el número lo calculan los que contestan —los muy contentos y "
        "los muy enfadados— y no significa nada."
    ),
)
def resumen_satisfaccion(
    db: DbDep, principal: AutenticadoDep, desde: date = Query(...), hasta: date = Query(...)
) -> Any:
    return ent.satisfaccion(db, principal.tenant_id, desde=desde, hasta=hasta)


# ── Cumplimiento desglosado y créditos (CRM-04.01.02.07, .08) ─────────────


@router_creditos.get(
    "/cumplimiento",
    dependencies=[Depends(exige_permiso("case:read"))],
    summary="Cumplimiento por cliente o por equipo",
    description=(
        "El total global esconde lo único accionable: un 94 % puede ser «todo va "
        "bien» o «va bien con todos menos con el cliente grande». Solo el "
        "desglose distingue esas dos situaciones, y son opuestas.\n\n"
        "Ordenado por el peor primero: la lista existe para actuar, y ordenarla "
        "alfabéticamente obliga a buscar el problema en vez de enseñarlo."
    ),
)
def cumplimiento(
    db: DbDep,
    principal: AutenticadoDep,
    desde: date = Query(...),
    hasta: date = Query(...),
    por: str = Query("cuenta", description="cuenta | equipo"),
) -> Any:
    return ent.cumplimiento_desglosado(db, principal.tenant_id, desde=desde, hasta=hasta, por=por)


class CalcularCreditos(BaseModel):
    periodo: str = Field(max_length=20)
    desde: date
    hasta: date
    escala: list[dict[str, Any]] = Field(
        default_factory=list,
        description='Tramos: [{"hasta_pct": 95, "credito_pct": 5}, …]. Cada contrato tiene la suya',
    )


@router_creditos.post(
    "/calcular",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Proponer los créditos del periodo",
    description=(
        "Se **propone, no se aplica**. Descontar dinero de una factura "
        "automáticamente por un incumplimiento que puede tener explicación —una "
        "parada acordada, un dato que faltaba del cliente— convertiría cada "
        "incidencia en una reclamación. Lo que sí hace el sistema es no dejar que "
        "se olvide.\n\n"
        "Un crédito ya decidido **no se recalcula**: cambiaría un importe que el "
        "cliente ya ha visto en su factura."
    ),
)
def calcular(datos: CalcularCreditos, uow: UowDep, principal: AutenticadoDep) -> Any:
    propuestos = ent.calcular_creditos(
        uow,
        periodo=datos.periodo,
        desde=datos.desde,
        hasta=datos.hasta,
        escala=datos.escala,
    )
    return {"periodo": datos.periodo, "propuestos": propuestos}


class DecidirCredito(BaseModel):
    aprobar: bool
    motivo: str = Field(min_length=1, max_length=2000)
    importe: Decimal | None = None


@router_creditos.post(
    "/{credito_id}/decidir",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Aprobar o rechazar un crédito propuesto",
    description=(
        "El motivo es obligatorio en los dos sentidos. Rechazar sin explicación "
        "deja al comercial que atiende a ese cliente sin nada que decirle, y "
        "aprobar sin explicación hace imposible saber después si fue una decisión "
        "o un descuido."
    ),
)
def decidir(credito_id: UUID, datos: DecidirCredito, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = ent.decidir_credito(
        uow,
        credito_id,
        aprobar=datos.aprobar,
        motivo=datos.motivo,
        importe=datos.importe,
        por=principal.id,
    )
    return {"id": str(fila.id), "estado": fila.estado}


# ── Listados ──────────────────────────────────────────────────────────────
# Estas cuatro colecciones se podían crear y no se podían leer: el `POST` estaba
# y el `GET` no, así que una cola, una regla de escalado o un entitlement se
# daban de alta y desaparecían de la vista. La API contestaba 405 y el front
# —que los declara listables— enseñaba una pantalla vacía.

montar_listado(
    router_colas,
    modelo=ColaCasos,
    objeto="cola",
    permiso="case:read",
    nombre="Colas de casos",
)
montar_listado(
    router_escalado,
    modelo=ReglaEscalada,
    objeto="regla_escalado",
    permiso="case:read",
    ruta="/reglas",
    nombre="Reglas de escalado",
)
montar_listado(
    router_entitlements,
    modelo=Entitlement,
    objeto="entitlement",
    permiso="case:read",
    nombre="Entitlements",
)
montar_listado(
    router_encuestas,
    modelo=Encuesta,
    objeto="encuesta",
    permiso="case:read",
    nombre="Encuestas de satisfacción",
)


# ── Listados ──────────────────────────────────────────────────────────────
# Colecciones con acciones sobre sus registros y sin forma de listarlos: se
# podía desplegar un entorno, invocar un agente o cerrar una visita, y no ver
# ninguno. A una acción sobre un registro se llega por su ficha, y a la ficha
# por el listado: sin listado, la acción no la alcanza nadie.

montar_listado(
    router_creditos,
    modelo=CreditoServicio,
    objeto="credito_servicio",
    permiso="case:read",
    nombre="Créditos de servicio",
)


# ── Antes de abrir el caso, y antes de firmar el pliego ───────────────────


@router_entitlements.get(
    "/{entitlement_id}/puede-abrirse",
    dependencies=[Depends(exige_permiso("entitlement:read"))],
    summary="Si se puede abrir un caso contra este derecho, y qué decir si no",
    description=(
        "Devuelve la **decisión**, no un corte: quien abre el caso decide qué "
        "hacer según el contrato —bloquear, avisar o facturar el exceso—, y las "
        "tres son legítimas. Elegir por él significaría cortarle el soporte a "
        "alguien que pagaba por el exceso.\n\n"
        "Se mira **antes** de abrirlo. Descubrir que el derecho estaba agotado "
        "cuando el caso lleva dos días abiertos deja la conversación en el peor "
        "sitio posible."
    ),
)
def puede_abrirse(entitlement_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return ent.comprobar_antes_de_abrir(db, principal.tenant_id, entitlement_id)


router_sla_proveedores = APIRouter(prefix="/sla-proveedores", tags=["SLA"])


class MaximoIn(BaseModel):
    del_proveedor: dict[str, Any] = Field(default_factory=dict)
    proveedor_clave: str | None = Field(
        None,
        max_length=60,
        description="Con él se usa el acuerdo GUARDADO del proveedor y no el tecleado",
    )
    horas_propias: float | None = Field(
        None,
        ge=0,
        description=(
            "Lo que tardamos NOSOTROS en lo nuestro: recibir el aviso, "
            "diagnosticar, escalar al proveedor. Si no se cuenta, el compromiso "
            "que se firma es el del proveedor y el cliente nos reclama la "
            "diferencia"
        ),
    )


@router_sla_proveedores.post(
    "/maximo-que-se-puede-prometer",
    dependencies=[Depends(exige_permiso("case:read"))],
    summary="Lo mejor que se puede firmar con este proveedor detrás",
    description=(
        "La conversación **al revés**: en vez de comprobar un pliego ya escrito, "
        "decirle al comercial qué puede ofrecer antes de escribirlo. Es más barato "
        "que descubrirlo en la revisión legal, y mucho más que descubrirlo en la "
        "primera incidencia.\n\n"
        "Sin el acuerdo del proveedor **no se contesta**: se podría adivinar, que "
        "es lo que se hace ahora y lo que este módulo existe para evitar."
    ),
)
def maximo_que_se_puede_prometer(cuerpo: MaximoIn, db: DbDep, principal: AutenticadoDep) -> Any:
    from services.service import proveedores_sla as psla

    del_proveedor = dict(cuerpo.del_proveedor)
    if cuerpo.proveedor_clave:
        # El acuerdo GUARDADO, no el que teclea quien pregunta: lo tecleado es
        # lo que el comercial cree que sostiene el proveedor, y esa creencia es
        # justo lo que este módulo existe para comprobar.
        proveedores = _proveedores_de_integracion(db, principal)
        acuerdo = next(
            (
                a
                for a in psla.acuerdos(db, principal.tenant_id)
                if a.proveedor_clave == cuerpo.proveedor_clave
            ),
            None,
        )
        del_proveedor = psla.del_proveedor(acuerdo, (proveedores or {}).get(cuerpo.proveedor_clave))
    return psla.maximo_que_se_puede_prometer(
        del_proveedor=del_proveedor,
        horas_propias=psla._horas_propias(cuerpo.horas_propias, db),
    )


def _proveedores_de_integracion(db: Any, principal: Any) -> dict[str, dict[str, Any]] | None:
    """Los proveedores de servicio que constan en `integration`, por clave.

    Por HTTP: el proveedor vive allí y este servicio no lee su esquema. `None`
    si no contesta, que no es lo mismo que «no hay ninguno»."""
    from crmcore.errors import NoDisponible
    from crmcore.http.interno import invocar
    from crmcore.runtime import settings as rt

    from services.service.ajustes import ajustes

    espera = rt.efectivo("sla_proveedor_espera_s", db)
    try:
        respuesta = invocar(
            metodo="GET",
            ruta="/api/v1/proveedores-servicio",
            parametros={"limite": 200},
            tenant_id=principal.tenant_id,
            principal_id=principal.id,
            permisos=["integracion:read"],
            timeout_s=float(espera if espera is not None else ajustes().sla_proveedor_espera_s),
        )
    except NoDisponible as exc:
        logger.warning("service.sla_proveedor_integracion_sin_respuesta", error=str(exc)[:200])
        return None
    datos = respuesta.get("datos") if respuesta.get("ok") else None
    items = datos.get("items") if isinstance(datos, dict) else None
    if not isinstance(items, list):
        logger.warning("service.sla_proveedor_integracion_rechazo", estado=respuesta.get("estado"))
        return None
    return {str(p.get("clave")): p for p in items if p.get("clave")}


class AcuerdoIn(BaseModel):
    respuesta_h: float | None = Field(None, ge=0)
    resolucion_h: float | None = Field(
        None, ge=0, description="Vacío: vale el plazo del proveedor en integración"
    )
    disponibilidad_pct: float | None = Field(None, ge=0, le=100)
    cobertura_horaria: str | None = Field(None, max_length=40, examples=["24x7", "L-V 9-18"])
    vigente_hasta: date | None = None
    notas: str | None = Field(None, max_length=4000)


@router_sla_proveedores.get(
    "/acuerdos",
    dependencies=[Depends(exige_permiso("entitlement:read"))],
    summary="Los acuerdos de servicio guardados de cada proveedor",
)
def listar_acuerdos(db: DbDep, principal: AutenticadoDep) -> Any:
    from services.service import proveedores_sla as psla

    return [psla.acuerdo_como_dict(a) for a in psla.acuerdos(db, principal.tenant_id)]


@router_sla_proveedores.put(
    "/acuerdos/{proveedor_clave}",
    dependencies=[Depends(exige_permiso("entitlement:write"))],
    summary="Guardar lo que sostiene un proveedor",
    description=(
        "Respuesta, resolución, disponibilidad y cobertura **firmadas con el "
        "proveedor**. Si la resolución se deja vacía vale el plazo que consta "
        "del proveedor en integración."
    ),
)
def guardar_acuerdo(
    proveedor_clave: str, cuerpo: AcuerdoIn, db: DbDep, principal: AutenticadoDep
) -> Any:
    from services.service import proveedores_sla as psla

    fila = psla.guardar_acuerdo(
        db, principal.tenant_id, proveedor_clave, cuerpo.model_dump(exclude_unset=True)
    )
    return psla.acuerdo_como_dict(fila)


@router_sla_proveedores.delete(
    "/acuerdos/{proveedor_clave}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(exige_permiso("entitlement:write"))],
    summary="Quitar el acuerdo guardado de un proveedor",
)
def borrar_acuerdo(proveedor_clave: str, db: DbDep, principal: AutenticadoDep) -> None:
    from services.service import proveedores_sla as psla

    psla.borrar_acuerdo(db, principal.tenant_id, proveedor_clave)


class ProveedorDelDerecho(BaseModel):
    proveedor_clave: str | None = Field(None, max_length=60)


@router_sla_proveedores.put(
    "/entitlements/{entitlement_id}/proveedor",
    dependencies=[Depends(exige_permiso("entitlement:write"))],
    summary="Quién da este derecho al cliente",
    description="Vacío: lo damos nosotros y no hay acuerdo de proveedor que comparar.",
)
def proveedor_del_derecho(
    entitlement_id: UUID, cuerpo: ProveedorDelDerecho, db: DbDep, principal: AutenticadoDep
) -> Any:
    from crmcore.errors import NoEncontrado

    fila = db.get(ent.Entitlement, entitlement_id)
    if fila is None or fila.tenant_id != principal.tenant_id or fila.deleted_at is not None:
        raise NoEncontrado("Ese derecho no existe", error_code="entitlement.no_encontrado")
    fila.proveedor_clave = (cuerpo.proveedor_clave or "").strip() or None
    db.flush()
    return {"id": str(fila.id), "proveedor_clave": fila.proveedor_clave}


@router_sla_proveedores.get(
    "/revision",
    dependencies=[Depends(exige_permiso("entitlement:read"))],
    summary="Lo que prometemos al cliente frente a lo que sostiene su proveedor",
    description=(
        "Cada derecho activo con un proveedor detrás, comparado con el acuerdo "
        "guardado de ese proveedor. Avisa de **todo** lo que no se puede "
        "cumplir —y de los derechos cuyo proveedor no tiene acuerdo: no tenerlo "
        "no es tenerlo bien—. Si integración no contesta, se compara con lo "
        "guardado y se dice."
    ),
)
def revision(db: DbDep, principal: AutenticadoDep) -> Any:
    from services.service import proveedores_sla as psla

    proveedores = _proveedores_de_integracion(db, principal)
    salida = psla.revisar(db, principal.tenant_id, proveedores=proveedores)
    return salida


class CompararIn(BaseModel):
    prometido_al_cliente: dict[str, Any] = Field(default_factory=dict)
    del_proveedor: dict[str, Any] = Field(default_factory=dict)
    horas_propias: float | None = Field(None, ge=0)


@router_sla_proveedores.post(
    "/comparar",
    dependencies=[Depends(exige_permiso("case:read"))],
    summary="Comparar un pliego con lo que sostiene el proveedor",
    description="Devuelve **todos** los incumplimientos, no el primero.",
)
def comparar(cuerpo: CompararIn, db: DbDep, principal: AutenticadoDep) -> Any:
    from services.service import proveedores_sla as psla

    return psla.comparar(
        prometido_al_cliente=cuerpo.prometido_al_cliente,
        del_proveedor=cuerpo.del_proveedor,
        horas_propias=psla._horas_propias(cuerpo.horas_propias, db),
    )


ROUTERS_OPERACION = [
    router_sla_proveedores,
    router_colas,
    router_agentes,
    router_escalado,
    router_entitlements,
    router_encuestas,
    router_creditos,
]
