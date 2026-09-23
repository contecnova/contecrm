"""API de calidad y gobierno del dato de cliente
(CRM-01.01.01.09, .11, .12 · CRM-01.01.02.03, .07 · CRM-01.01.04.06 a .09).

Nada de aquí cambia una ficha a espaldas de nadie: el golden record explica de
dónde sale cada valor, el enriquecimiento rellena huecos y lo que no cuadra se
convierte en una excepción con dueño.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from services.party import cuenta_360 as c360
from services.party import mdm
from services.party import stewardship as stw

router_calidad = APIRouter(prefix="/calidad-dato", tags=["calidad del dato"])
router_plan = APIRouter(prefix="/planes-cuenta", tags=["plan de cuenta"])
router_personas = APIRouter(prefix="/mapa-personas", tags=["mapa de influencia"])


class GoldenIn(BaseModel):
    campos: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    reglas: dict[str, dict[str, Any]] = Field(default_factory=dict)
    confianza_por_fuente: dict[str, int] = Field(default_factory=dict)


class CerrarIn(BaseModel):
    cierre: str
    nota: str = ""


class EnriquecerIn(BaseModel):
    candidatas: list[dict[str, Any]] = Field(default_factory=list)
    coste_por_consulta: float = 0.0
    presupuesto: float | None = None


class AplicarIn(BaseModel):
    actuales: dict[str, Any] = Field(default_factory=dict)
    del_proveedor: dict[str, Any] = Field(default_factory=dict)
    escritos_a_mano: list[str] = Field(default_factory=list)


class PlanIn(BaseModel):
    cuenta_id: UUID
    periodo: str
    objetivos: list[dict[str, Any]] = Field(default_factory=list)
    riesgos: list[dict[str, Any]] = Field(default_factory=list)
    hueco: list[dict[str, Any]] = Field(default_factory=list)
    objetivo_importe: Decimal | None = None


class FinancieroIn(BaseModel):
    cuenta_id: UUID
    estado: str
    origen: str
    vigente_at: datetime
    limite_credito: Decimal | None = None
    credito_dispuesto: Decimal | None = None
    deuda_vencida: Decimal | None = None
    bloqueado: bool = False
    motivo_bloqueo: str = ""


class RelacionIn(BaseModel):
    origen_id: UUID
    destino_id: UUID
    tipo: str
    motivo: str = ""


@router_calidad.post(
    "/golden",
    dependencies=[Depends(exige_permiso("party:read"))],
    summary="Componer la ficha buena a partir de lo que dice cada sistema",
    description=(
        "Lo que casi todos los CRM hacen es lo cómodo: **gana el último que "
        "escribió**. Eso produce fichas que cambian solas los martes por la "
        "noche, cuando pasa el proceso del ERP, sin que nadie entienda por "
        "qué.\n\n"
        "Aquí la regla es **por campo** —el NIF lo sabe mejor el ERP y el móvil "
        "quien acaba de hablar con el cliente—, y «más reciente» significa "
        "cuándo **cambió** el valor, no cuándo llegó el mensaje: un maestro que "
        "se reenvía cada noche trae mil valores idénticos con fecha nueva.\n\n"
        "Y lo que pierde **se devuelve como discrepancia**: que el ERP y el "
        "formulario digan direcciones distintas suele significar que el cliente "
        "se mudó y solo uno se enteró."
    ),
)
def golden(cuerpo: GoldenIn, principal: AutenticadoDep) -> Any:
    return mdm.componer_golden(
        campos=cuerpo.campos,
        reglas=cuerpo.reglas,
        confianza_por_fuente=cuerpo.confianza_por_fuente,
    )


@router_calidad.get(
    "/linaje/{objeto}/{objeto_id}",
    dependencies=[Depends(exige_permiso("party:read"))],
    summary="De dónde sale cada valor de esta ficha",
    description=(
        "Es la respuesta a «¿por qué pone esto aquí?». Sin ella la única "
        "contestación honesta es «no lo sé», y esa es la que hace que alguien se "
        "abra una hoja de cálculo al lado del CRM.\n\n"
        "Se distingue **cuándo cambió el valor** de **cuándo llegó el último "
        "mensaje que lo confirmaba**: no es lo mismo, y confundirlo es lo que "
        "hace que un reenvío pise una corrección de esta mañana."
    ),
)
def linaje(objeto: str, objeto_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return mdm.historia_de(db, principal.tenant_id, objeto=objeto, objeto_id=objeto_id)


@router_calidad.get(
    "/obsoletos/{objeto}/{objeto_id}",
    dependencies=[Depends(exige_permiso("party:read"))],
    summary="Qué valores llevan demasiado sin que nadie los confirme",
    description=(
        "El plazo es **por campo**: un NIF no caduca y un cargo caduca en cuanto "
        "ascienden a esa persona.\n\n"
        "Y un campo del que no hay linaje **no cuenta como fresco**: no se ha "
        "verificado nunca, que es distinto de estar al día."
    ),
)
def obsoletos(objeto: str, objeto_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return mdm.valores_obsoletos(db, principal.tenant_id, objeto=objeto, objeto_id=objeto_id)


@router_calidad.get(
    "/cola",
    dependencies=[Depends(exige_permiso("party:read"))],
    summary="La cola de excepciones de calidad",
    description=(
        "Medir la calidad del dato no arregla nada por sí solo: el informe que "
        "dice «el 38 % de las cuentas no tiene sector» lo mira todo el mundo la "
        "primera semana y nadie la segunda. Lo que arregla el dato es que "
        "**alguien concreto tenga una cola con su nombre**.\n\n"
        "Se dice aparte cuántas no tiene nadie asignadas: son las que no se van a "
        "hacer, y sin contarlas el panel enseña una cola pequeña y sana que en "
        "realidad es una vigilada y otra abandonada."
    ),
)
def cola(
    db: DbDep,
    principal: AutenticadoDep,
    mias: bool = Query(False),
    sin_asignar: bool = Query(False),
) -> Any:
    return stw.cola(
        db, principal.tenant_id, de=principal.id if mias else None, sin_asignar=sin_asignar
    )


@router_calidad.post(
    "/cola/{excepcion_id}/asignar/{usuario_id}",
    dependencies=[Depends(exige_permiso("party:write"))],
    summary="Ponerle nombre a una excepción",
)
def asignar(excepcion_id: UUID, usuario_id: UUID, uow: UowDep) -> Any:
    fila = stw.asignar(uow, excepcion_id=excepcion_id, a=usuario_id)
    return {"id": str(fila.id), "asignada_a": str(fila.asignada_a), "estado": fila.estado}


@router_calidad.post(
    "/cola/{excepcion_id}/cerrar",
    dependencies=[Depends(exige_permiso("party:write"))],
    summary="Cerrar diciendo qué se hizo",
    description=(
        "Un botón de «cerrar» a secas convierte la cola en un vertedero: se vacía "
        "y el dato sigue mal. Por eso el cierre es una de cuatro —corregido, no "
        "era un error, no se puede arreglar o ya no aplica— y las dos últimas "
        "exigen motivo.\n\n"
        "«No era un error» es una respuesta legítima **y se aprende de ella**: si "
        "la misma regla genera cien excepciones que cien personas descartan, la "
        "rota es la regla."
    ),
)
def cerrar(excepcion_id: UUID, cuerpo: CerrarIn, uow: UowDep, principal: AutenticadoDep) -> Any:
    return stw.cerrar(
        uow, excepcion_id=excepcion_id, cierre=cuerpo.cierre, nota=cuerpo.nota, por=principal.id
    )


@router_calidad.get(
    "/reglas-sospechosas",
    dependencies=[Depends(exige_permiso("party:read"))],
    summary="Qué reglas producen ruido en vez de trabajo",
    description=(
        "En cuanto la mitad de lo que hay en la cola no es un problema, se deja "
        "de abrir la cola entera. Esto enseña qué regla lo está provocando."
    ),
)
def reglas_sospechosas(db: DbDep, principal: AutenticadoDep) -> Any:
    return stw.reglas_sospechosas(db, principal.tenant_id)


@router_calidad.post(
    "/enriquecimiento/planificar",
    dependencies=[Depends(exige_permiso("party:write"))],
    summary="Qué se va a enriquecer y cuánto va a costar",
    description=(
        "Un botón de «enriquecer todo» sobre cuarenta mil cuentas es una factura "
        "que nadie aprobó. Se dice antes, no después — y se priorizan las cuentas "
        "vivas con huecos, porque enriquecer fichas inactivas de hace cinco años "
        "gasta el presupuesto en algo que nadie va a abrir."
    ),
)
def planificar(cuerpo: EnriquecerIn, principal: AutenticadoDep) -> Any:
    return stw.planificar_enriquecimiento(
        candidatas=cuerpo.candidatas,
        coste_por_consulta=cuerpo.coste_por_consulta,
        presupuesto=cuerpo.presupuesto,
    )


@router_calidad.post(
    "/enriquecimiento/aplicar",
    dependencies=[Depends(exige_permiso("party:write"))],
    summary="Aplicar lo del proveedor sin pisar lo que escribió una persona",
    description=(
        "Un proveedor de datos sabe de muchas empresas y no conoce a ninguna; "
        "quien acaba de hablar con el cliente sí. Rellena huecos y no corrige a "
        "la gente.\n\n"
        "Lo que el proveedor dice distinto de lo que hay **no se descarta**: sale "
        "como discrepancia para la cola de calidad, porque puede que el dato del "
        "CRM esté viejo y esa es justo la conversación que interesa."
    ),
)
def aplicar(cuerpo: AplicarIn, principal: AutenticadoDep) -> Any:
    return stw.aplicar_enriquecimiento(
        actuales=cuerpo.actuales,
        del_proveedor=cuerpo.del_proveedor,
        escritos_a_mano=cuerpo.escritos_a_mano,
    )


@router_plan.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("party:write"))],
    summary="Guardar el plan de una cuenta",
    description=(
        "Se exige que cada objetivo tenga **fecha y responsable**: uno sin las "
        "dos cosas es una frase, y un plan de frases se revisa una vez, en la "
        "reunión en la que se escribió.\n\n"
        "El hueco por cubrir se **calcula** contra lo que ya se le factura. "
        "Tecleado por el comercial, un plan de cuenta es una lista de deseos: "
        "sale lo que él tiene en la cabeza, no lo que nadie ha mirado."
    ),
)
def guardar_plan(cuerpo: PlanIn, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = c360.guardar_plan(
        uow,
        cuenta_id=cuerpo.cuenta_id,
        periodo=cuerpo.periodo,
        objetivos=cuerpo.objetivos,
        riesgos=cuerpo.riesgos,
        hueco=cuerpo.hueco,
        objetivo_importe=cuerpo.objetivo_importe,
        responsable_id=principal.id,
    )
    return {"id": str(fila.id), "cuenta_id": str(fila.cuenta_id), "periodo": fila.periodo}


@router_plan.post(
    "/financiero",
    dependencies=[Depends(exige_permiso("party:write"))],
    summary="Replicar el estado financiero que dice el ERP",
    description=(
        "Proyección local con **la fecha del origen**, no la de llegada. La "
        "diferencia importa el día que se bloquea una oferta: con un dato de hace "
        "tres semanas, el bloqueo es una suposición y hay que decirlo.\n\n"
        "Un bloqueo **sin motivo no se guarda**: el comercial que se encuentra la "
        "oferta parada tiene que poder decirle al cliente algo que no sea «el "
        "sistema no me deja»."
    ),
)
def financiero(cuerpo: FinancieroIn, uow: UowDep) -> Any:
    fila = c360.replicar_financiero(
        uow,
        cuenta_id=cuerpo.cuenta_id,
        estado=cuerpo.estado,
        origen=cuerpo.origen,
        vigente_at=cuerpo.vigente_at,
        limite_credito=cuerpo.limite_credito,
        credito_dispuesto=cuerpo.credito_dispuesto,
        deuda_vencida=cuerpo.deuda_vencida,
        bloqueado=cuerpo.bloqueado,
        motivo_bloqueo=cuerpo.motivo_bloqueo,
    )
    return {"cuenta_id": str(fila.cuenta_id), "estado": fila.estado, "bloqueado": fila.bloqueado}


@router_plan.get(
    "/financiero/{cuenta_id}/puede-comprometer",
    dependencies=[Depends(exige_permiso("party:read"))],
    summary="Si se le puede vender más, y con qué confianza",
    description=(
        "Tres respuestas distintas y se distinguen: **sí**, **no** y **no se "
        "sabe**. Y «no se sabe» no se redondea a «sí»: dejar pasar la oferta y "
        "descubrir el impago después es exactamente lo que este dato existe para "
        "evitar."
    ),
)
def puede_comprometer(
    cuenta_id: UUID, db: DbDep, principal: AutenticadoDep, importe: Decimal = Query(Decimal(0))
) -> Any:
    return c360.puede_comprometer(db, principal.tenant_id, cuenta_id=cuenta_id, importe=importe)


@router_personas.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("party:write"))],
    summary="Anotar cómo se relacionan dos personas de la cuenta",
    description=(
        "«Aliado» y «detractor» son valoraciones sobre una persona identificada y "
        "**exigen motivo**: sin el porqué es un rumor guardado en una base de "
        "datos, y si algún día esa persona ejerce su derecho de acceso, lo que "
        "sale es eso."
    ),
)
def anotar_relacion(cuerpo: RelacionIn, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = c360.anotar_relacion(
        uow,
        origen_id=cuerpo.origen_id,
        destino_id=cuerpo.destino_id,
        tipo=cuerpo.tipo,
        motivo=cuerpo.motivo,
        por=principal.id,
    )
    return {"id": str(fila.id), "tipo": fila.tipo}


ROUTERS_CALIDAD = [router_calidad, router_plan, router_personas]
