"""API de las automatizaciones."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from crmcore.audit.chain import registrar
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado
from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from crmcore.http.listados import aplicar_filtros_de_la_url, montar_ficha  # noqa: E402
from crmcore.http.pagination import CONTAR_TOTAL_DESCRIPCION, PaginaDeListado, paginar_consulta
from crmcore.http.parametros import admite_parametros_abiertos
from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from services.automation import entornos_auto as entornos
from services.automation import extensiones, motor, planificador, plantillas, validacion
from services.automation.modelos import (
    Automatizacion,
    EjecucionAutomatizacion,
    EjecucionPendiente,
)


class CrearAutomatizacion(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=200)
    descripcion: str = ""
    disparador: Literal[
        "creacion", "modificacion", "eliminacion", "evento", "webhook", "programada", "manual"
    ]
    objetivo: str = Field(
        ..., description="Objeto o tipo de evento", examples=["lead", "opportunity.won"]
    )
    campos_vigilados: list[str] = Field(
        default_factory=list,
        description=(
            "Para `modificacion`. Vacío = cualquier cambio la dispara, que "
            "suele ser más de lo que se quiere"
        ),
        examples=[["etapa", "importe"]],
    )
    programacion: str | None = Field(None, description="Expresión cron, para `programada`")
    condiciones: list[dict[str, Any]] = Field(default_factory=list)
    combinacion: Literal["todas", "alguna"] = "todas"
    acciones: list[dict[str, Any]] = Field(
        ...,
        examples=[[{"tipo": "asignar", "parametros": {"usuario_id": "@territorio.owner_id"}}]],
    )
    prioridad: int = Field(100, ge=0, le=10000)
    momento: Literal["inmediata", "diferida", "programada"] = "inmediata"
    # Nace apagada a propósito: una regla recién creada se prueba antes de
    # dejarla actuar sobre datos reales.
    activa: bool = False


class AutomatizacionOut(BaseModel):
    id: UUID
    nombre: str
    descripcion: str
    disparador: str
    objetivo: str
    campos_vigilados: list[str] = []
    condiciones: list[dict[str, Any]] = []
    combinacion: str
    acciones: list[dict[str, Any]] = []
    activa: bool
    prioridad: int
    momento: str
    ejecuciones: int
    fallos: int
    # Cuándo corrió por última vez y, si es programada, con qué horario.
    # Estaban en la tabla y no salían: una automatización con doce fallos y
    # sin fecha no deja saber si pasó ayer o hace medio año.
    ultima_ejecucion_at: datetime | None = None
    # La expresión cron, tal como se guarda: **una cadena**, no un objeto.
    # Estaba declarada aquí como `dict` y la columna es `String(120)` que
    # admite nulo, así que crear una automatización sin programación —que es
    # el caso normal, porque la mayoría se disparan por evento— reventaba al
    # serializar la respuesta: 500 limpio, con la fila ya escrita. No lo cazó
    # ninguna prueba porque todas las que crean una le ponían horario.
    programacion: str | None = None
    # Cuándo le toca a una programada encendida. Es lo primero que se mira
    # para saber si el horario está bien escrito.
    proxima_ejecucion_at: datetime | None = None
    # Quién la encendió: con sus permisos actúan los procesos que lance. Se
    # busca por nombre en la pantalla.
    activada_por_id: UUID | None = Field(None, json_schema_extra={"referencia": "usuario"})
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class ProbarAutomatizacion(BaseModel):
    """Prueba en seco: evalúa condiciones y dice qué haría, sin hacer nada."""

    valores: dict[str, Any]


class EjecucionOut(BaseModel):
    id: UUID
    objeto: str
    registro_id: str | None = None
    resultado: str
    decisiones: list[dict[str, Any]] = []
    acciones_ejecutadas: list[dict[str, Any]] = []
    error: str | None = None
    duracion_ms: int

    model_config = {"from_attributes": True}


class Interruptor(BaseModel):
    """Si la regla queda encendida o apagada. Por cuerpo, para que la acción
    tenga formulario: por query no aparece en el contrato y salía vacía."""

    activa: bool = Field(..., description="true la enciende, false la apaga")


router = APIRouter(prefix="/automatizaciones", tags=["automatizaciones"])


@router.post(
    "",
    response_model=AutomatizacionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("automation:write"))],
    summary="Crear una automatización",
    description="Nace **desactivada**: pruébala con `/probar` antes de activarla.",
)
def crear(datos: CrearAutomatizacion, db: DbDep, principal: AutenticadoDep) -> Any:
    # El horario de una programada y el evento de una «evento», comprobados al
    # guardar: guardados mal, la regla no corría nunca y nadie lo veía.
    validacion.exigir(datos.model_dump())
    # Las acciones, también las de control —si, para_cada, fijar—: el motor
    # las ejecuta y el alta las rechazaba, así que ramas y bucles no se podían
    # guardar. Lo comprueba `validacion`, la misma que usan las plantillas y la
    # promoción, para que ninguna puerta deje pasar lo que otra rechaza.
    if db.execute(
        select(Automatizacion.id).where(
            Automatizacion.tenant_id == principal.tenant_id,
            Automatizacion.nombre == datos.nombre,
        )
    ).first():
        raise Conflicto(
            "Ya existe una automatización con ese nombre",
            error_code="automatizacion.nombre_duplicado",
        )

    regla = Automatizacion(tenant_id=principal.tenant_id, **datos.model_dump())
    planificador.recalcular_proxima(regla, db)
    # Si nace encendida, quien la crea es quien la activa.
    planificador.anotar_activacion(regla, principal)
    db.add(regla)
    db.flush()
    registrar(
        db,
        accion="automatizacion.creada",
        objeto="automatizacion",
        objeto_id=regla.id,
        datos={"nombre": datos.nombre, "disparador": datos.disparador},
    )
    return regla


@router.get(
    "",
    response_model=PaginaDeListado,
    dependencies=[Depends(exige_permiso("automation:read"))],
    summary="Automatizaciones del tenant",
)
def listar(
    request: Request,
    db: DbDep,
    principal: AutenticadoDep,
    objetivo: str = Query(""),
    solo_activas: bool = Query(False),
    limite: int = Query(50, ge=1, le=200),
    cursor: str = Query(""),
    contar: bool = Query(False, description=CONTAR_TOTAL_DESCRIPCION),
) -> Any:
    consulta = select(Automatizacion).where(Automatizacion.tenant_id == principal.tenant_id)
    if objetivo:
        consulta = consulta.where(Automatizacion.objetivo == objetivo)
    if solo_activas:
        consulta = consulta.where(Automatizacion.activa.is_(True))
    # Por prioridad, que es el orden en que se EJECUTAN: verlas en otro orden hace
    # difícil entender cuál actúa primero sobre el mismo registro.
    # Y los filtros comunes, con sus rangos. Estar escrito a mano no es motivo
    # para quedarse sin ellos: entonces el mismo producto admite
    # `?vence_at__hasta=…` o no según quién escribió cada listado, y eso lo
    # descubre el integrador probando.
    consulta = aplicar_filtros_de_la_url(
        request, Automatizacion, consulta, principal=principal, db=db, objeto="automatizacion"
    )
    return paginar_consulta(
        db,
        Automatizacion,
        consulta,
        limite=limite,
        cursor=cursor,
        orden="prioridad",
        modelo_salida=AutomatizacionOut,
        contar=contar,
    )


@router.post(
    "/{regla_id}/probar",
    response_model=dict,
    dependencies=[Depends(exige_permiso("automation:read"))],
    summary="Probar una regla sin ejecutarla",
    description=(
        "Evalúa las condiciones con los valores que se le pasen y devuelve la "
        "decisión de cada una y qué acciones se ejecutarían. Nada se ejecuta."
    ),
)
def probar(
    regla_id: UUID, datos: ProbarAutomatizacion, db: DbDep, principal: AutenticadoDep
) -> Any:
    regla = db.get(Automatizacion, regla_id)
    if regla is None or regla.tenant_id != principal.tenant_id:
        raise NoEncontrado("La automatización no existe", error_code="automatizacion.no_encontrada")
    cumple, decisiones = motor.evaluar_condiciones(regla, datos.valores)
    return {
        "se_dispararia": cumple,
        "decisiones": decisiones,
        "acciones": regla.acciones if cumple else [],
    }


@router.post(
    "/{regla_id}/activar",
    response_model=AutomatizacionOut,
    dependencies=[Depends(exige_permiso("automation:write"))],
    summary="Activar o desactivar una regla",
)
def activar(regla_id: UUID, datos: Interruptor, db: DbDep, principal: AutenticadoDep) -> Any:
    regla = db.get(Automatizacion, regla_id)
    if regla is None or regla.tenant_id != principal.tenant_id:
        raise NoEncontrado("La automatización no existe", error_code="automatizacion.no_encontrada")
    regla.activa = datos.activa
    # Encender una programada calcula su próxima hora —y rechaza un horario
    # roto antes de encenderla, no la primera vez que debería haber corrido—.
    planificador.recalcular_proxima(regla, db)
    planificador.anotar_activacion(regla, principal)
    registrar(
        db,
        accion="automatizacion.activada" if datos.activa else "automatizacion.desactivada",
        objeto="automatizacion",
        objeto_id=regla.id,
        datos={"nombre": regla.nombre},
    )
    return regla


@router.get(
    "/{regla_id}/ejecuciones",
    response_model=list[EjecucionOut],
    dependencies=[Depends(exige_permiso("automation:read"))],
    summary="Historial de ejecuciones, con las decisiones tomadas",
    description=(
        "Incluye las veces que **no** se disparó y por qué condición. Es lo que "
        "responde a «¿por qué no se ha asignado este registro?»."
    ),
)
def ejecuciones(
    regla_id: UUID,
    db: DbDep,
    principal: AutenticadoDep,
    limite: int = Query(50, ge=1, le=200),
) -> Any:
    return list(
        db.execute(
            select(EjecucionAutomatizacion)
            .where(
                EjecucionAutomatizacion.automatizacion_id == regla_id,
                EjecucionAutomatizacion.tenant_id == principal.tenant_id,
            )
            .order_by(EjecucionAutomatizacion.created_at.desc())
            .limit(limite)
        )
        .scalars()
        .all()
    )


@router.get(
    "/registro/{objeto}/{registro_id}",
    response_model=list[EjecucionOut],
    dependencies=[Depends(exige_permiso("automation:read"))],
    summary="Qué automatizaciones han tocado este registro",
    description=(
        "Vista desde el registro y no desde la regla. Es la que se necesita "
        "cuando un dato tiene un valor raro y hay que averiguar quién lo puso."
    ),
)
def por_registro(objeto: str, registro_id: str, db: DbDep, principal: AutenticadoDep) -> Any:
    return list(
        db.execute(
            select(EjecucionAutomatizacion)
            .where(
                EjecucionAutomatizacion.tenant_id == principal.tenant_id,
                EjecucionAutomatizacion.objeto == objeto,
                EjecucionAutomatizacion.registro_id == registro_id,
            )
            .order_by(EjecucionAutomatizacion.created_at.desc())
            .limit(100)
        )
        .scalars()
        .all()
    )


# ── Probar y promocionar, y plantillas por industria ──────────────────────
# (CRM-00.03.03.08, CRM-00.03.03.09)
#
# Una automatización se escribe en producción porque es donde están los datos de
# verdad, y se prueba **activándola**. Eso funciona hasta el día en que la regla
# toca cuatro mil registros. El módulo que permite probarla sin tocar nada
# estaba escrito, probado y no lo importaba nadie.


class ProbarEnSecoIn(BaseModel):
    nombre: str = Field(..., min_length=1)
    afectados: list[dict[str, Any]] = Field(default_factory=list)
    acciones: list[dict[str, Any]] = Field(default_factory=list)
    limite_muestra: int = Field(20, ge=1, le=200)


class PromoverIn(BaseModel):
    """Traer automatizaciones de un sandbox a esta empresa, primero en seco."""

    sandbox_id: UUID = Field(
        ...,
        description="El sandbox de donde vienen",
        json_schema_extra={"referencia": "sandbox"},
    )
    nombres: list[str] = Field(
        default_factory=list,
        description="Cuáles, por su nombre. Vacío = todas las del sandbox",
    )
    huella: str = Field(
        "",
        description=(
            "Vacía, es la prueba en seco: dice qué pasaría y devuelve una huella. "
            "Con esa huella, se aplica — si nada ha cambiado entre medias"
        ),
    )


ClavePlantilla = Literal[plantillas.CLAVES]  # type: ignore[valid-type]


class InstalarPlantillaIn(BaseModel):
    clave: ClavePlantilla = Field(..., description="Qué plantilla de la biblioteca")  # type: ignore[valid-type]
    responsable_id: UUID | None = Field(
        None,
        description=(
            "A quién avisa o asigna. Lo piden las plantillas que reparten trabajo; "
            "en las demás, sin elegir se avisa a quien sigue el registro"
        ),
        json_schema_extra={"referencia": "usuario"},
    )
    nombre: str = Field(
        "",
        max_length=200,
        description="Otro nombre, si ya tienes una automatización con el de la plantilla",
    )


class EjecutarAhoraIn(BaseModel):
    registro_id: str = Field(
        "",
        max_length=80,
        description=(
            "El registro sobre el que se ejecuta. Vacío en las que no actúan sobre "
            "uno, como un recordatorio"
        ),
    )
    valores: dict[str, Any] = Field(
        default_factory=dict,
        description="Los datos del registro que miran sus condiciones y acciones",
    )


class PendienteOut(BaseModel):
    id: UUID
    automatizacion_id: UUID
    origen: str
    objeto: str
    registro_id: str | None = None
    ejecutar_at: datetime
    estado: str
    intentos: int
    error: str | None = None
    ejecucion_id: UUID | None = None
    created_at: datetime | None = None
    terminada_at: datetime | None = None

    model_config = {"from_attributes": True}


@router.post(
    "/probar-en-seco",
    dependencies=[Depends(exige_permiso("automatizacion:read"))],
    summary="Qué haría esta automatización, sin hacer nada",
    description=(
        "**A cuántos toca y qué les haría**, con una muestra de los registros "
        "concretos. Probarla activándola funciona hasta el día en que la regla "
        "toca cuatro mil, y entonces lo que hay que deshacer son cuatro mil "
        "correos ya enviados.\n\n"
        "La muestra va **acotada**: una lista de cuatro mil no se mira, y lo que "
        "se quiere ver es si los que caen son los que uno tenía en la cabeza."
    ),
)
def probar_en_seco(cuerpo: ProbarEnSecoIn, principal: AutenticadoDep) -> Any:
    return entornos.probar_en_seco(
        nombre=cuerpo.nombre,
        afectados=cuerpo.afectados,
        acciones=cuerpo.acciones,
        limite_muestra=cuerpo.limite_muestra,
    )


@router.post(
    "/promocionar",
    dependencies=[Depends(exige_permiso("automation:write"))],
    summary="Promover automatizaciones desde un sandbox",
    description=(
        "Trae a esta empresa las automatizaciones de uno de sus sandboxes, "
        "**creándolas o actualizándolas de verdad**. Antes devolvía un JSON y no "
        "guardaba nada.\n\n"
        "**Primero en seco**: sin `huella`, dice qué pasaría con cada una "
        "—crear, actualizar, sin cambios, cuáles se apagarían— y devuelve una "
        "huella. Con esa huella se aplica, y si algo ha cambiado entre medias no "
        "se aplica nada: lo que se confirma es lo que se vio.\n\n"
        "Se copia la definición y no el estado, todo **llega apagado** y cada una "
        "queda en la auditoría con el sandbox del que vino."
    ),
)
def promocionar(cuerpo: PromoverIn, uow: UowDep, principal: AutenticadoDep) -> Any:
    return entornos.promover(
        uow,
        principal,
        sandbox_id=cuerpo.sandbox_id,
        nombres=[n.strip() for n in cuerpo.nombres if n.strip()],
        huella=cuerpo.huella,
    )


@router.get(
    "/plantillas",
    response_model=PaginaDeListado,
    dependencies=[Depends(exige_permiso("automation:read"))],
    summary="La biblioteca de plantillas de automatización",
    description=(
        "Reglas completas por industria, listas para instalar con un clic. Dice "
        "cuáles ya tienes instaladas —por nombre— y qué da por supuesta cada una."
    ),
)
def listar_plantillas(db: DbDep, principal: AutenticadoDep) -> Any:
    instaladas = set(
        db.execute(
            select(Automatizacion.nombre).where(
                Automatizacion.tenant_id == principal.tenant_id,
                Automatizacion.nombre.in_([p.nombre for p in plantillas.PLANTILLAS]),
            )
        )
        .scalars()
        .all()
    )
    items = [
        {
            "clave": p.clave,
            "nombre": p.nombre,
            "descripcion": p.descripcion,
            "industrias": list(p.industrias),
            "disparador": p.regla["disparador"],
            "objetivo": p.regla["objetivo"],
            "momento": p.regla.get("momento", "inmediata"),
            "necesita_responsable": p.necesita_responsable,
            "requiere": list(p.requiere),
            "instalada": p.nombre in instaladas,
        }
        for p in plantillas.PLANTILLAS
    ]
    return {"items": items, "siguiente": None, "total_aprox": len(items)}


@router.post(
    "/plantillas/instalar",
    dependencies=[Depends(exige_permiso("automation:write"))],
    summary="Instalar una plantilla de la biblioteca",
    description=(
        "Se elige por su clave y **crea la automatización de verdad, apagada**: "
        "una plantilla que se enciende al instalarse manda avisos con textos que "
        "nadie ha leído. Antes había que teclear la plantilla en JSON y "
        "contestaba «instaladas» sin crear nada.\n\n"
        "Lo que ya existe con ese nombre **no se pisa**: se dice, y se puede "
        "instalar con otro."
    ),
)
def instalar_plantilla(cuerpo: InstalarPlantillaIn, uow: UowDep, principal: AutenticadoDep) -> Any:
    return entornos.instalar(
        uow, clave=cuerpo.clave, responsable_id=cuerpo.responsable_id, nombre=cuerpo.nombre
    )


@router.get(
    "/pendientes",
    response_model=PaginaDeListado,
    dependencies=[Depends(exige_permiso("automation:read"))],
    summary="Ejecuciones diferidas y programadas, en cola y ya atendidas",
    description=(
        "Lo que espera su momento y lo que ya corrió, con su estado. Sin esto, "
        "una diferida que no ha corrido no se distingue de una que no se disparó."
    ),
)
def listar_pendientes(
    db: DbDep,
    principal: AutenticadoDep,
    estado: str = Query("", description="pendiente, hecha, fallida o descartada"),
    automatizacion_id: UUID | None = Query(None),
    limite: int = Query(50, ge=1, le=200),
    cursor: str = Query(""),
    contar: bool = Query(False, description=CONTAR_TOTAL_DESCRIPCION),
) -> Any:
    consulta = select(EjecucionPendiente).where(EjecucionPendiente.tenant_id == principal.tenant_id)
    if estado:
        consulta = consulta.where(EjecucionPendiente.estado == estado)
    if automatizacion_id:
        consulta = consulta.where(EjecucionPendiente.automatizacion_id == automatizacion_id)
    return paginar_consulta(
        db,
        EjecucionPendiente,
        consulta,
        limite=limite,
        cursor=cursor,
        orden="-created_at",
        modelo_salida=PendienteOut,
        contar=contar,
    )


@router.post(
    "/{regla_id}/ejecutar",
    dependencies=[Depends(exige_permiso("automation:write"))],
    summary="Ejecutar ahora sobre un registro",
    description=(
        "El disparador **manual**: corre la regla ya, sobre el registro que se "
        "diga, y deja su traza como cualquier otra ejecución. Corre ahora aunque "
        "sea diferida o programada —es lo que se pide—, pero no si está apagada: "
        "apagarla es como se para una regla, y para mirar qué haría sin hacer "
        "nada está «Probar»."
    ),
)
def ejecutar_ahora(
    regla_id: UUID, datos: EjecutarAhoraIn, uow: UowDep, principal: AutenticadoDep
) -> Any:
    from services.automation import ejecutores as ejecutores_mod

    regla = uow.db.get(Automatizacion, regla_id)
    if regla is None or regla.tenant_id != principal.tenant_id or regla.deleted_at is not None:
        raise NoEncontrado("La automatización no existe", error_code="automatizacion.no_encontrada")
    if not regla.activa:
        raise Conflicto(
            "Está apagada. Enciéndela para ejecutarla, o usa «Probar» para ver qué "
            "haría sin hacer nada.",
            error_code="automatizacion.apagada",
        )
    registro_id = datos.registro_id.strip() or None
    valores = {**datos.valores, "_manual": True}
    if registro_id:
        valores.setdefault(f"{regla.objetivo}_id", registro_id)
    traza = motor.ejecutar(
        uow.db,
        regla,
        valores=valores,
        objeto=regla.objetivo,
        registro_id=registro_id,
        ejecutores=ejecutores_mod.construir(uow),
    )
    uow.db.flush()
    registrar(
        uow.db,
        accion="automatizacion.ejecutada_a_mano",
        objeto="automatizacion",
        objeto_id=regla.id,
        datos={"nombre": regla.nombre, "registro_id": registro_id, "resultado": traza.resultado},
    )
    return {
        "resultado": traza.resultado,
        "ejecucion_id": str(traza.id),
        "acciones_ejecutadas": len(traza.acciones_ejecutadas or []),
        "decisiones": traza.decisiones,
        "error": traza.error,
    }


@router.post(
    "/{regla_id}/secreto-webhook",
    dependencies=[Depends(exige_permiso("automation:write"))],
    summary="Generar el secreto del webhook que la dispara",
    description=(
        "Para las de disparador **webhook**. Devuelve la dirección a la que hay "
        "que llamar y el secreto con el que se firma, **una sola vez**: no se "
        "vuelve a enseñar. Generarlo otra vez lo cambia y el anterior deja de "
        "valer al momento.\n\n"
        "La firma es la misma que la de los webhooks que manda el CRM: HMAC-SHA256 "
        "de `<momento>.<cuerpo>` en `X-Contecrm-Firma`, con el momento en "
        "segundos en `X-Contecrm-Momento`."
    ),
)
def secreto_webhook(regla_id: UUID, uow: UowDep, principal: AutenticadoDep) -> Any:
    from services.automation import webhook_entrante

    return webhook_entrante.generar_secreto(uow, regla_id=regla_id, por=principal.id)


@router.post(
    "/webhook/{tenant_id}/{regla_id}",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Disparar una automatización desde fuera (webhook entrante)",
    description=(
        "Endpoint **público**: lo llama otro sistema, que no tiene usuario en el "
        "CRM. No es anónimo: lo autoriza la **firma** del cuerpo con el secreto "
        "de esa automatización, con ventana contra reenvíos. El cuerpo JSON son "
        "los valores con los que corre la regla; `registro_id`, si viene, es el "
        "registro sobre el que actúa.\n\n"
        "Firma mala, regla inexistente o sin secreto contestan **lo mismo**: "
        "decir cuál de las tres es le enseña a quien prueba qué tiene que cambiar."
    ),
)
async def recibir_webhook(tenant_id: UUID, regla_id: UUID, peticion: Request) -> Any:
    from crmcore.db.uow import unidad_de_trabajo
    from crmcore.security.firma import H_FIRMA, H_MOMENTO
    from crmcore.tenancy.context import con_contexto

    from services.automation import webhook_entrante

    # Los BYTES recibidos, no el JSON releído: la firma es de lo que llegó, y
    # reserializarlo cambia espacios y orden y la deja sin casar.
    crudo = await peticion.body()
    with (
        con_contexto(tenant_id=tenant_id, origen="webhook"),
        unidad_de_trabajo(tenant_id) as uow,
    ):
        return webhook_entrante.recibir(
            uow,
            regla_id=regla_id,
            cuerpo=crudo,
            firma=peticion.headers.get(H_FIRMA, ""),
            momento=peticion.headers.get(H_MOMENTO, ""),
        )


# ── Código del tenant: sandbox, versiones, firma y observabilidad ─────────
# (CRM-00.04.02.01, .05, .06, .07)
#
# Dejar que un cliente ejecute su código dentro del CRM es la diferencia entre
# un producto configurable y uno programable, y también la forma más rápida de
# que una instalación se caiga por algo que no escribimos nosotros. Todo lo que
# lo hace aceptable estaba escrito, probado y sin que lo importara nadie.

router_extensiones = APIRouter(prefix="/extensiones", tags=["código del tenant"])


class LimitesIn(BaseModel):
    consumo: dict[str, Any] = Field(default_factory=dict)


class CapacidadesIn(BaseModel):
    capacidades: list[str] = Field(default_factory=list)


class PublicarVersionIn(BaseModel):
    clave: str = Field(..., min_length=1)
    codigo_base64: str = Field(..., min_length=1)
    version: int = Field(..., ge=1)
    dependencias: dict[str, str] = Field(default_factory=dict)
    capacidades: list[str] = Field(default_factory=list)
    versiones_vivas: list[int] = Field(default_factory=list)


class FirmaIn(BaseModel):
    codigo_base64: str = Field(..., min_length=1)
    huella_firmada: str = ""
    firmante: str = ""
    firmantes_de_confianza: list[str] = Field(default_factory=list)


class ObservabilidadIn(BaseModel):
    clave: str = Field(..., min_length=1)
    ejecuciones: list[dict[str, Any]] = Field(default_factory=list)
    coste_por_segundo: float = Field(0.0, ge=0)


def _codigo(base64_: str) -> bytes:
    import base64 as _b64

    try:
        return _b64.b64decode(base64_, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise ErrorValidacion(
            "El código no viene en base64 válido. Mandarlo como texto plano "
            "rompería con cualquier byte que no sea ASCII, que es el primer "
            "fichero con un acento dentro.",
            error_code="extension.codigo_ilegible",
        ) from exc


@router_extensiones.post(
    "/limites",
    dependencies=[Depends(exige_permiso("automatizacion:read"))],
    summary="Si este consumo se pasa de lo que puede gastar una extensión",
    description=(
        "Tiempo, memoria y llamadas salientes. Los tres, porque con solo el "
        "tiempo un bucle que no hace nada pasa, y con solo la memoria uno que "
        "llama mil veces a un tercero también.\n\n"
        "Y se dice **cuál** se pasó: «la extensión ha fallado» no deja arreglar "
        "nada."
    ),
)
def limites_de_extension(cuerpo: LimitesIn, principal: AutenticadoDep) -> Any:
    return extensiones.comprobar_limites(consumo=cuerpo.consumo)


@router_extensiones.post(
    "/capacidades",
    dependencies=[Depends(exige_permiso("automatizacion:read"))],
    summary="Si lo que pide esta extensión se le puede dar",
    description=(
        "La lista es **de lo que se permite**, no de lo que se prohíbe: una "
        "lista de prohibiciones nunca está completa, porque nadie piensa en lo "
        "que todavía no ha pasado."
    ),
)
def capacidades_de_extension(cuerpo: CapacidadesIn, principal: AutenticadoDep) -> Any:
    extensiones.exigir_permitido(capacidades=cuerpo.capacidades)
    return {"permitido": True, "capacidades": sorted(set(cuerpo.capacidades))}


@router_extensiones.post(
    "/versiones",
    dependencies=[Depends(exige_permiso("automatizacion:write"))],
    summary="Publicar una versión de una extensión",
    description=(
        "Con su huella, sus dependencias declaradas y las versiones que siguen "
        "vivas: una extensión que se actualiza en caliente deja a medias las "
        "ejecuciones en curso, y lo que estaba a medias es lo que nadie "
        "reclama."
    ),
)
def publicar_version(cuerpo: PublicarVersionIn, principal: AutenticadoDep) -> Any:
    return extensiones.publicar_version(
        clave=cuerpo.clave,
        codigo=_codigo(cuerpo.codigo_base64),
        version=cuerpo.version,
        dependencias=cuerpo.dependencias,
        capacidades=cuerpo.capacidades,
        versiones_vivas=cuerpo.versiones_vivas,
    )


@router_extensiones.post(
    "/firma",
    dependencies=[Depends(exige_permiso("automatizacion:write"))],
    summary="Revisar la firma del código antes de ejecutarlo",
    description=(
        "Se comprueba la **huella del código**, no quién dice ser el firmante: "
        "un código firmado por alguien de confianza que no coincide con su "
        "huella es un código cambiado después de firmarlo."
    ),
)
def revisar_firma(cuerpo: FirmaIn, principal: AutenticadoDep) -> Any:
    return extensiones.revisar_firma(
        codigo=_codigo(cuerpo.codigo_base64),
        huella_firmada=cuerpo.huella_firmada,
        firmante=cuerpo.firmante,
        firmantes_de_confianza=cuerpo.firmantes_de_confianza,
        revisada_por=principal.id,
    )


class EjecucionIn(BaseModel):
    clave: str = Field(..., min_length=1)
    version: int = Field(1, ge=1)
    entrada: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Con qué se ejecutó. **Va dentro a propósito**: una extensión que "
            "falla con un registro concreto y no guarda cuál obliga a "
            "reproducirlo a ciegas, y eso son horas"
        ),
    )
    consumo: dict[str, Any] = Field(
        default_factory=dict,
        description="`milisegundos`, `memoria_mb`, `llamadas_salientes`",
    )


@router_extensiones.post(
    "/ejecucion",
    dependencies=[Depends(exige_permiso("automatizacion:read"))],
    summary="El apunte de una ejecución, con sus límites ya mirados",
    description=(
        "Lo que queda anotado de cada vuelta del código del cliente: con qué se "
        "ejecutó, cuánto consumió y **si se pasó de algún límite, de cuál**. "
        "«La extensión ha fallado» no deja arreglar nada.\n\n"
        "**La salida no se guarda.** Puede llevar el registro entero, y "
        "duplicarlo en una tabla de apuntes es multiplicar lo que hay que "
        "proteger.\n\n"
        "Es el apunte que después alimenta `/extensiones/observabilidad`, que es "
        "donde se decide si una extensión se deja puesta."
    ),
)
def apuntar_ejecucion(cuerpo: EjecucionIn, principal: AutenticadoDep) -> Any:
    return extensiones.resumen_de_ejecucion(
        clave=cuerpo.clave,
        version=cuerpo.version,
        entrada=cuerpo.entrada,
        consumo=cuerpo.consumo,
    )


@router_extensiones.post(
    "/observabilidad",
    dependencies=[Depends(exige_permiso("automatizacion:read"))],
    summary="Cómo se está portando una extensión",
    description=(
        "Lo que hace falta para decidir si se deja puesta: cuánto tarda, cuánto "
        "falla y cuánto cuesta. Sin esto, el código del cliente es una caja "
        "negra dentro del producto y lo que se mira cuando algo va lento es "
        "todo menos la extensión."
    ),
)
def observabilidad_de_extension(cuerpo: ObservabilidadIn, principal: AutenticadoDep) -> Any:
    return extensiones.observabilidad(
        clave=cuerpo.clave,
        ejecuciones=cuerpo.ejecuciones,
        coste_por_segundo=cuerpo.coste_por_segundo,
    )


ROUTERS = [router, router_extensiones]


# ── La ficha del registro ─────────────────────────────────────────────────
# Sin ella, las acciones que cuelgan de un registro no se alcanzan desde
# ninguna pantalla: existen, se prueban y nadie las usa.
montar_ficha(
    router,
    modelo=Automatizacion,
    objeto="automatizacion",
    permiso_leer="automation:read",
    permiso_escribir="automation:write",
    nombre="Automatizaciones",
    parametro="regla_id",
)


# Estas rutas aceptan además los filtros comunes, cuyos nombres son columnas
# del modelo y cambian con él: no se pueden declarar. Los valida
# `aplicar_filtros_de_la_url`, que rechaza lo que no es columna o lo que este
# principal no ve en claro. Las dos mitades van juntas: con el filtro y sin la
# marca, la ruta contesta 422 a sus propios filtros.
admite_parametros_abiertos(
    listar, "llama a `aplicar_filtros_de_la_url`, que valida los filtros por columna"
)
