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
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from services.service import entitlements as ent
from services.service import operacion as ope
from services.service import servicio as svc
from services.service.entitlements import Encuesta, Entitlement
from services.service.operacion import AgenteServicio, ColaCasos, ReglaAsignacion, ReglaEscalada

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
    casos_incluidos: int | None = None
    horas_incluidas: float | None = None
    al_agotar: str = Field("avisar", description="avisar | bloquear | facturar")
    vigente_desde: date
    vigente_hasta: date | None = None


@router_entitlements.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("case:write"))],
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
    dependencies=[Depends(exige_permiso("case:read"))],
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
    dependencies=[Depends(exige_permiso("case:read"))],
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


ROUTERS_OPERACION = [
    router_colas,
    router_agentes,
    router_escalado,
    router_entitlements,
    router_encuestas,
    router_creditos,
]
