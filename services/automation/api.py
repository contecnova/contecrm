"""API de las automatizaciones."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from crmcore.audit.chain import registrar
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado
from crmcore.http.deps import AutenticadoDep, DbDep, exige_permiso
from crmcore.http.listados import aplicar_filtros_de_la_url, montar_ficha  # noqa: E402
from crmcore.http.pagination import PaginaDeListado, paginar_consulta
from crmcore.http.parametros import admite_parametros_abiertos
from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from services.automation import entornos_auto as entornos
from services.automation import extensiones, motor
from services.automation.modelos import Automatizacion, EjecucionAutomatizacion


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
    for accion in datos.acciones:
        if str(accion.get("tipo", "")) not in motor.ACCIONES:
            raise ErrorValidacion(
                f"Acción no admitida: «{accion.get('tipo')}»",
                error_code="automatizacion.accion_no_admitida",
                detalle={"admitidas": sorted(motor.ACCIONES)},
            )
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


class PromocionarIn(BaseModel):
    definicion: dict[str, Any] = Field(default_factory=dict)
    desde: str = Field("pruebas", min_length=1)
    hacia: str = Field("produccion", min_length=1)
    probada_en_seco: bool = False
    afectados_en_pruebas: int = Field(0, ge=0)


class PlantillaIn(BaseModel):
    plantilla: dict[str, Any] = Field(default_factory=dict)
    existentes: list[str] = Field(default_factory=list)


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
    dependencies=[Depends(exige_permiso("automatizacion:write"))],
    summary="Llevar una automatización de pruebas a producción",
    description=(
        "**Sin pasar antes por la prueba en seco, no se promociona.** No es "
        "burocracia: lo que se promociona toca datos de clientes de verdad, y la "
        "única diferencia entre una regla buena y una que manda cuatro mil "
        "correos es haber mirado a cuántos toca."
    ),
)
def promocionar(cuerpo: PromocionarIn, principal: AutenticadoDep) -> Any:
    return entornos.promocionar(
        definicion=cuerpo.definicion,
        desde=cuerpo.desde,
        hacia=cuerpo.hacia,
        probada_en_seco=cuerpo.probada_en_seco,
        afectados_en_pruebas=cuerpo.afectados_en_pruebas,
    )


@router.post(
    "/plantillas/instalar",
    dependencies=[Depends(exige_permiso("automatizacion:write"))],
    summary="Instalar una plantilla de automatizaciones por industria",
    description=(
        "Lo que se instala **no se activa solo**: una plantilla que se enciende "
        "al instalarse manda correos a clientes reales con textos que nadie ha "
        "leído.\n\n"
        "Y lo que ya existe **no se pisa**: si el tenant ya tiene una regla con "
        "ese nombre, se dice y se deja la suya. Sobrescribirla es perder trabajo "
        "de alguien sin preguntar."
    ),
)
def instalar_plantilla(cuerpo: PlantillaIn, principal: AutenticadoDep) -> Any:
    return entornos.instalar_plantilla(plantilla=cuerpo.plantilla, existentes=cuerpo.existentes)


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

    from crmcore.errors import ErrorValidacion

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
