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

from crmcore.errors import NoEncontrado
from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from crmcore.http.listados import montar_ficha, montar_listado
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from services.party import cuenta_360 as c360
from services.party import mdm
from services.party import stewardship as stw
from services.party.cuenta_360 import (
    CambioDeEmpresa,
    EstadoFinanciero,
    PlanCuenta,
    RelacionPersona,
)
from services.party.stewardship import ExcepcionCalidad

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


class LinajeIn(BaseModel):
    objeto: str = Field(..., min_length=1, examples=["cuenta"])
    objeto_id: UUID
    campo: str = Field(..., min_length=1, examples=["telefono"])
    fuente: str = Field(
        ...,
        min_length=1,
        description="Qué sistema lo dice: el ERP, un formulario, una persona",
    )
    valor: Any = None
    cambiado_at: datetime | None = Field(
        None,
        description=(
            "Cuándo cambió el valor **de verdad**. Sin ella se asume ahora, y un "
            "maestro que se reenvía cada noche dejaría mil valores con fecha nueva"
        ),
    )
    confianza: int = Field(50, ge=0, le=100)
    gana: bool = False


class ConfirmarIn(BaseModel):
    objeto: str = Field(..., min_length=1)
    objeto_id: UUID
    campo: str = Field(..., min_length=1)
    fuente: str = Field(..., min_length=1)


class CaducidadIn(BaseModel):
    dias_por_campo: dict[str, int] = Field(default_factory=dict)


@router_calidad.post(
    "/linaje",
    dependencies=[Depends(exige_permiso("party:write"))],
    summary="Apuntar de dónde viene un valor",
    # Por qué se añadió, que no es lo que lee quien abre la pantalla:
    # Es la mitad que faltaba. El linaje se podía consultar —«¿por qué
    # pone esto aquí?»— y no se podía escribir: la tabla estaba vacía, así
    # que la consulta devolvía nada y los valores obsoletos no salían
    # nunca. Las dos respuestas eran las mismas que si todo estuviera al
    # día.
    description=(
        "Lo escribe quien integra: el conector que trae el maestro, el "
        "formulario que recoge un dato, la persona que lo corrige.\n\n"
        "Y `cambiado_at` **solo se mueve cuando el valor cambia de verdad**. Es "
        "la diferencia entre «este teléfono es de hace dos años» y «este "
        "teléfono lo reenvía el ERP cada noche»: una fuente que repite lo mismo "
        "no lo hace más fresco."
    ),
)
def apuntar_linaje(cuerpo: LinajeIn, uow: UowDep) -> Any:
    fila = mdm.anotar_linaje(
        uow,
        objeto=cuerpo.objeto,
        objeto_id=cuerpo.objeto_id,
        campo=cuerpo.campo,
        fuente=cuerpo.fuente,
        valor=cuerpo.valor,
        cambiado_at=cuerpo.cambiado_at,
        confianza=cuerpo.confianza,
        gana=cuerpo.gana,
    )
    return {
        "id": str(fila.id),
        "campo": fila.campo,
        "fuente": fila.fuente,
        "cambiado_at": fila.cambiado_at.isoformat() if fila.cambiado_at else None,
        "recibido_at": fila.recibido_at.isoformat() if fila.recibido_at else None,
    }


@router_calidad.post(
    "/linaje/confirmar",
    dependencies=[Depends(exige_permiso("party:write"))],
    summary="Alguien ha comprobado que este valor sigue siendo bueno",
    description=(
        "Mueve «cuándo se recibió» y **no** «cuándo cambió»: confirmar no es "
        "cambiar. Mover las dos haría que el dato pareciera recién actualizado "
        "cuando lo único que ha pasado es que alguien lo miró, y eso falsea "
        "todos los informes de antigüedad.\n\n"
        "Es lo que saca un valor de la cola de obsoletos sin inventarse que ha "
        "cambiado."
    ),
)
def confirmar_linaje(cuerpo: ConfirmarIn, uow: UowDep) -> Any:
    return mdm.confirmar_frescura(
        uow,
        objeto=cuerpo.objeto,
        objeto_id=cuerpo.objeto_id,
        campo=cuerpo.campo,
        fuente=cuerpo.fuente,
    )


@router_calidad.post(
    "/caducidad/comprobar",
    dependencies=[Depends(exige_permiso("party:read"))],
    summary="Si los plazos de frescura declarados tienen sentido",
    description=(
        "Un plazo de **cero días** significa «siempre obsoleto», y lo que "
        "produce es una cola de excepciones con todo dentro — que nadie mira, "
        "que es peor que no tenerla.\n\n"
        "Y al revés: un plazo de diez años es una forma de decir que ese campo "
        "no caduca sin escribirlo. Se señala para que sea una decisión y no un "
        "número puesto a ojo."
    ),
)
def comprobar_caducidad(cuerpo: CaducidadIn, principal: AutenticadoDep) -> Any:
    return mdm.caducidad_declarada(cuerpo.dias_por_campo)


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
    "/cola/barrido",
    dependencies=[Depends(exige_permiso("party:write"))],
    summary="Buscar excepciones de calidad y llenar la cola",
    description=(
        "Recorre cuentas y contactos y abre una excepción por cada cosa que "
        "esté mal. Se puede lanzar cuando se quiera y se puede repetir: la "
        "misma regla sobre el mismo campo de la misma ficha es **una** "
        "excepción, no una por pasada.\n\n"
        "Sin esto la cola no tenía por dónde llenarse —estaban la pantalla, la "
        "asignación y el cierre, y ninguna forma de que entrara nada—, así que "
        "se veía siempre vacía."
    ),
)
def barrer(uow: UowDep, limite: int = Query(500, ge=1, le=5000)) -> Any:
    return stw.barrido(uow, limite=limite)


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


@router_calidad.get(
    "/enriquecimiento/caducidad",
    dependencies=[Depends(exige_permiso("party:read"))],
    summary="Cuándo toca volver a consultar a la fuente externa",
    description=(
        "Lo que decide no es la fecha de la ficha: es cuándo se consultó al "
        "proveedor la última vez. Volver a pagar por un dato de hace una semana "
        "es tirar presupuesto; dejar uno de hace tres años es trabajar con un "
        "cargo que ya no existe.\n\n"
        "Y si **nunca** se ha consultado se dice así, no «hace mucho»: no es lo "
        "mismo un dato que se comprobó hace un año que uno que no se ha "
        "comprobado jamás, y la decisión que se toma con cada uno es distinta."
    ),
)
def caducidad_del_enriquecimiento(
    db: DbDep,
    principal: AutenticadoDep,
    ultimo_at: datetime | None = Query(None),
    dias: int = Query(180, ge=1, le=3650),
) -> Any:
    return stw.caducidad_del_enriquecimiento(ultimo_at=ultimo_at, dias=dias)


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


# ── Listados ──────────────────────────────────────────────────────────────
# Estas colecciones se podían crear y no se podían leer: tenían `POST` y no
# tenían `GET`, así que lo que se daba de alta desaparecía de la vista. La API
# contestaba 405 y el front —que las declara listables— enseñaba una pantalla
# vacía sin decir por qué.

montar_listado(
    router_plan,
    modelo=PlanCuenta,
    objeto="plan_cuenta",
    permiso="party:read",
    nombre="Planes de cuenta",
)
montar_listado(
    router_personas,
    modelo=RelacionPersona,
    objeto="relacion_persona",
    permiso="party:read",
    nombre="Mapa de personas",
)


# ── Listados de las sub-colecciones ───────────────────────────────────────
# Mismo agujero que en las colecciones raíz: se podían crear y no se podían
# leer. Un sobre de firma, una tabla del almacén o una predicción que no se
# pueden listar no existen para quien tiene que revisarlos.

montar_listado(
    router_plan,
    modelo=EstadoFinanciero,
    objeto="estado_financiero",
    permiso="party:read",
    ruta="/financiero",
    nombre="Estados financieros",
)


# ── Lo del plan de cuenta y el mapa de poder que no se podía pedir ────────
#
# Medido el 05-10-2026: siete decisiones de `cuenta_360` y tres de identidad y
# linaje estaban escritas, probadas y **sin una sola puerta**. El plan de cuenta
# tenía su tabla y su listado, y lo que lo convierte en un plan —el hueco
# calculado, el aviso de caducidad, el mapa de con quién no se ha hablado— no se
# podía pedir desde ninguna parte.


class HuecoIn(BaseModel):
    catalogo: list[dict[str, Any]] = Field(default_factory=list)
    ya_le_vendemos: list[str] = Field(default_factory=list)


@router_plan.post(
    "/hueco",
    dependencies=[Depends(exige_permiso("party:read"))],
    summary="Qué del catálogo no se le vende todavía",
    description=(
        "**Calculado, no tecleado**, y es lo único que separa un plan de cuenta "
        "de una lista de deseos. Si el hueco lo escribe el comercial, escribe lo "
        "que tiene en la cabeza; calculado contra lo que ya se factura, aparece "
        "lo que nadie había mirado."
    ),
)
def hueco_del_plan(cuerpo: HuecoIn, principal: AutenticadoDep) -> Any:
    return c360.calcular_hueco(catalogo=cuerpo.catalogo, ya_le_vendemos=cuerpo.ya_le_vendemos)


@router_plan.get(
    "/{plan_cuenta_id}/caducado",
    dependencies=[Depends(exige_permiso("party:read"))],
    summary="Si este plan lleva demasiado sin revisarse",
    description=(
        "Un plan anual que nadie toca desde enero no es un plan: es un "
        "documento. Se avisa en vez de dejarlo envejecer en silencio, porque en "
        "la reunión de seguimiento se enseña igual y nadie mira la fecha."
    ),
)
def plan_caducado(plan_cuenta_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    fila = db.get(PlanCuenta, plan_cuenta_id)
    if fila is None or fila.tenant_id != principal.tenant_id:
        raise NoEncontrado("Ese plan no existe", error_code="party.plan_no_existe")
    return c360.plan_caducado(revisado_at=fila.revisado_at)


class MapaIn(BaseModel):
    contactos: list[dict[str, Any]] = Field(default_factory=list)


@router_personas.post(
    "/mapa-de-poder",
    dependencies=[Depends(exige_permiso("party:read"))],
    summary="Quién manda, quién ayuda, quién estorba y con quién no se ha hablado",
    description=(
        "Lo último es lo que de verdad hace falta antes de una reunión. Un mapa "
        "que sólo enseña a los conocidos confirma lo que el comercial ya sabía; "
        "el valor está en el **decisor con el que nadie ha hablado**."
    ),
)
def mapa_de_poder(cuerpo: MapaIn, db: DbDep, principal: AutenticadoDep) -> Any:
    return c360.mapa_de_poder(db, principal.tenant_id, contactos=cuerpo.contactos)


@router_calidad.get(
    "/uniones-propuestas",
    dependencies=[Depends(exige_permiso("party:read"))],
    summary="Pares de contactos que parecen la misma persona",
    description=(
        "**Propone, no une.** Unir automáticamente dos personas distintas le "
        "enseña a una el historial de la otra, y eso no se deshace aunque se "
        "deshaga la unión."
    ),
)
def uniones_propuestas(
    db: DbDep,
    principal: AutenticadoDep,
    umbral: int | None = Query(None, ge=0, le=100),
    limite: int = Query(50, ge=1, le=200),
) -> Any:
    from services.party import identidad

    return identidad.proponer_uniones(db, principal.tenant_id, umbral=umbral, limite=limite)


@router_calidad.get(
    "/identidades/{objeto}/{objeto_id}",
    dependencies=[Depends(exige_permiso("party:read"))],
    summary="Con qué identificadores se conoce a esta persona en cada canal",
    description=(
        "Correo, cookie, teléfono, identificador de la aplicación, del ERP. "
        "Resolver la identidad entre canales es lo que impide que la misma "
        "persona cuente como cuatro, y para poder revisarlo hay que poder verlo."
    ),
)
def identidades_de(objeto: str, objeto_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    from services.party import identidad

    return identidad.identidades_de(db, principal.tenant_id, objeto=objeto, objeto_id=objeto_id)


# ── El contacto que cambia de empresa ─────────────────────────────────────
#
# Tres decisiones escritas y sin puerta. Lo que pasa sin ellas: la persona se va
# a otra empresa, su ficha se queda en la cuenta antigua y el comercial le
# escribe a una dirección que ya no existe — o peor, le escribe al correo nuevo
# con el histórico de la empresa anterior delante.

router_cambios = APIRouter(prefix="/cambios-de-empresa", tags=["calidad del dato"])


class IndicioIn(BaseModel):
    contacto_id: UUID
    cuenta_anterior_id: UUID | None = None
    indicio: str = Field(..., min_length=1, examples=["rebote_duro"])
    detalle: str = ""


@router_cambios.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("contact:write"))],
    summary="Abrir la sospecha de que alguien ha cambiado de empresa",
    description=(
        "**Sospecha, no hecho.** Mover el contacto en cuanto rebota un correo "
        "dejaría la cuenta antigua sin su interlocutor por un buzón lleno. Lo que "
        "se abre es una revisión con su indicio."
    ),
)
def abrir_cambio(cuerpo: IndicioIn, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = c360.detectar_cambio(
        uow,
        contacto_id=cuerpo.contacto_id,
        cuenta_anterior_id=cuerpo.cuenta_anterior_id,
        indicio=cuerpo.indicio,
        detalle=cuerpo.detalle,
    )
    return {"id": str(fila.id), "estado": fila.estado}


class ConfirmarCambio(BaseModel):
    cuenta_nueva_id: UUID
    contacto_nuevo_id: UUID


@router_cambios.post(
    "/{cambio_de_empresa_id}/confirmar",
    dependencies=[Depends(exige_permiso("contact:write"))],
    summary="Confirmar el cambio y dejar el rastro en las dos cuentas",
)
def confirmar_cambio(
    cambio_de_empresa_id: UUID, cuerpo: ConfirmarCambio, uow: UowDep, principal: AutenticadoDep
) -> Any:
    return c360.confirmar_cambio(
        uow,
        cambio_id=cambio_de_empresa_id,
        cuenta_nueva_id=cuerpo.cuenta_nueva_id,
        contacto_nuevo_id=cuerpo.contacto_nuevo_id,
    )


@router_cambios.post(
    "/{cambio_de_empresa_id}/descartar",
    dependencies=[Depends(exige_permiso("contact:write"))],
    summary="Descartar la sospecha, con motivo",
    description=(
        "Con motivo porque la misma señal volverá: sin saber por qué se descartó, "
        "la revisión siguiente vuelve a abrirla y se descarta otra vez."
    ),
)
def descartar_cambio(
    cambio_de_empresa_id: UUID,
    uow: UowDep,
    principal: AutenticadoDep,
    motivo: str = Query("", max_length=500),
) -> Any:
    return c360.descartar_cambio(uow, cambio_id=cambio_de_empresa_id, motivo=motivo)


class CuentaPersonalIn(BaseModel):
    """Lo que se mira de una cuenta de persona.

    Se declara en vez de aceptar un diccionario suelto: un cuerpo sin esquema se
    pinta como un formulario vacío, y quien lo usa tiene que adivinar los campos.
    """

    nombre: str = ""
    sector_codigo: str | None = Field(
        None,
        description=(
            "De empresa, y por eso se mira: pedirle el CNAE a un particular es lo "
            "que hace que el comercial escriba cualquier cosa para poder guardar"
        ),
    )
    empleados: int | None = None
    facturacion_anual: float | None = None


@router_plan.post(
    "/cuenta-personal/validar",
    dependencies=[Depends(exige_permiso("party:read"))],
    summary="Si esta cuenta de persona está completa para poder usarse",
    description=(
        "Una cuenta personal **no es una empresa con menos campos**: la ficha "
        "entera pasa a ser dato personal —el nombre de la cuenta es el nombre de "
        "alguien y su dirección su domicilio— y los campos de empresa dejan de "
        "tener sentido, así que no se pueden exigir."
    ),
)
def validar_cuenta_personal(cuerpo: CuentaPersonalIn, principal: AutenticadoDep) -> Any:
    return c360.validar_cuenta_personal(datos=cuerpo.model_dump(exclude_none=True))


# El listado de los cambios detectados. Sin él, abrir uno para confirmarlo o
# descartarlo exigiría saberse su identificador: la cola de revisión existiría y
# no se podría abrir.
montar_listado(
    router_cambios,
    modelo=CambioDeEmpresa,
    objeto="cambio_de_empresa",
    permiso="party:read",
    permiso_escribir="contact:write",
    nombre="Cambios de empresa",
)


ROUTERS_CALIDAD = [router_calidad, router_plan, router_personas, router_cambios]


# ── Salud de la cuenta, replicada (CRM-01.01.05.07) ───────────────────────


@router_calidad.get(
    "/salud/{cuenta_id}",
    dependencies=[Depends(exige_permiso("party:read"))],
    summary="La salud de esta cuenta, con todo lo que la matiza",
    description=(
        "Se calcula en el servicio de inteligencia y aquí vive una **copia**: un "
        "número que solo existe allí no lo ve quien tiene al cliente delante, con "
        "lo cual no cambia ninguna conversación.\n\n"
        "Las tres respuestas son distintas y ninguna se redondea a otra: **hay "
        "medida fiable**, **hay medida pero no vale para actuar** y **no hay "
        "medida** — y la tercera no es «va bien», es que nadie lo ha calculado, "
        "normalmente porque faltan las señales.\n\n"
        "Un número en rojo de hace tres meses no es una alerta: es un recuerdo, y "
        "llamar por él molesta a un cliente cuyo problema ya se resolvió."
    ),
)
def salud_de_la_cuenta(cuenta_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    from services.party import salud_replicada

    return salud_replicada.de_la_cuenta(db, principal.tenant_id, cuenta_id=cuenta_id)


@router_calidad.get(
    "/salud",
    dependencies=[Depends(exige_permiso("party:read"))],
    summary="Las cuentas que hay que mirar",
    description=(
        "**Sin las que no se pueden mirar.** Se dejan fuera las medidas poco "
        "fiables y las caducadas, y se cuentan aparte: una lista de «clientes en "
        "riesgo» donde la mitad son falsos positivos por falta de datos se abre "
        "dos veces y no se abre más — y entonces se pierden también los que sí lo "
        "estaban."
    ),
)
def cuentas_en_riesgo(db: DbDep, principal: AutenticadoDep) -> Any:
    from services.party import salud_replicada

    return salud_replicada.en_riesgo(db, principal.tenant_id)


# ── Métricas embebidas del cliente (CRM-01.01.05.06) ──────────────────────


@router_calidad.get(
    "/metricas/{cuenta_id}",
    dependencies=[Depends(exige_permiso("party:read"))],
    summary="Las métricas del cliente, con lo que falta dicho aparte",
    description=(
        "Facturación, margen, pedidos, incidencias, NPS y morosidad. Ninguna es "
        "del CRM: vienen del ERP, del sistema de soporte y de la herramienta de "
        "encuestas, y por eso cada una lleva **de cuándo es y de dónde viene** — "
        "un margen sin fecha se lee como el de hoy.\n\n"
        "«Cero incidencias» y «no tenemos el dato de incidencias» se pintan igual "
        "en un panel y significan lo contrario: aquí se distinguen.\n\n"
        "Y no se calcula nada encima: sumar o derivar produciría un número que no "
        "existe en ningún sistema y que nadie puede cuadrar."
    ),
)
def metricas_de_la_cuenta(cuenta_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    from services.party import metricas_embebidas

    return metricas_embebidas.panel_de_la_cuenta(db, principal.tenant_id, cuenta_id=cuenta_id)


@router_calidad.get(
    "/metricas",
    dependencies=[Depends(exige_permiso("party:read"))],
    summary="Si las métricas están llegando, o hace semanas que no",
    description=(
        "El fallo aquí es silencioso: la integración se cae, los paneles siguen "
        "enseñando los últimos números y nadie lo nota hasta que alguien comenta "
        "que un cliente «lleva mucho sin facturar»."
    ),
)
def salud_de_las_metricas(db: DbDep, principal: AutenticadoDep) -> Any:
    from services.party import metricas_embebidas

    return metricas_embebidas.salud_de_la_integracion(db, principal.tenant_id)


# ── La ficha del registro ─────────────────────────────────────────────────
# Sin ella, las acciones que cuelgan de un registro no se alcanzan desde
# ninguna pantalla: existen, se prueban y nadie las usa.
montar_ficha(
    router_calidad,
    modelo=ExcepcionCalidad,
    objeto="excepcion_calidad",
    permiso_leer="account:read",
    permiso_escribir="account:write",
    nombre="Calidad del dato",
    ruta="/cola",
    parametro="excepcion_id",
)
