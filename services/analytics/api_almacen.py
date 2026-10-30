"""API de analítica avanzada: almacén, exportación, modelo semántico y análisis.

CRM-05.01.03.01 a .07 y CRM-05.01.04.09, .10.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from crmcore.http.listados import montar_ficha, montar_listado
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from services.analytics import almacen as alm
from services.analytics import cliente as ci
from services.analytics import cohortes as coh
from services.analytics import fuente as fue
from services.analytics import semantico as sem
from services.analytics.almacen import FuenteFederada, TablaAnalitica

router = APIRouter(prefix="/almacen", tags=["analitica"])
router_metricas = APIRouter(prefix="/metricas", tags=["analitica"])
router_analisis = APIRouter(prefix="/analisis", tags=["analitica"])


class DeclararTabla(BaseModel):
    clave: str = Field(..., min_length=1, max_length=80)
    columnas: list[dict[str, Any]] = Field(..., min_length=1)
    servicio: str = ""
    objeto: str = ""
    nombre: str = ""
    ruta: str = Field(
        "",
        max_length=200,
        description=(
            "Ruta de la API de la que se traen las filas, p. ej. `/api/v1/accounts`. "
            "Sin ella la tabla no se carga sola, y la pantalla de frescura lo dice."
        ),
    )
    estrategia: str = Field("incremental", description="completa · incremental")
    frecuencia_min: int = 60


class Cargar(BaseModel):
    tabla: str
    filas: list[dict[str, Any]] = Field(default_factory=list)
    hasta: datetime | None = None
    completa: bool = False


class DeclararDestino(BaseModel):
    clave: str = Field(..., min_length=1, max_length=80)
    tipo: str = Field(..., description="Informativo: no cambia el comportamiento")
    tablas: list[str] = Field(..., min_length=1)
    config: dict[str, Any] = Field(default_factory=dict)
    nombre: str = ""


class ConfirmarEnvio(BaseModel):
    destino: str
    marcas: dict[str, str] = Field(default_factory=dict)
    error: str = ""


class DeclararFederada(BaseModel):
    clave: str = Field(..., min_length=1, max_length=80)
    tipo: str = ""
    objetos: list[str] = Field(..., min_length=1)
    config: dict[str, Any] = Field(default_factory=dict)
    nombre: str = ""
    tope_filas: int = 100_000
    timeout_s: int = 60


class DefinirMetrica(BaseModel):
    clave: str = Field(..., min_length=1, max_length=80)
    nombre: str = Field(..., min_length=1)
    objeto: str = Field(..., min_length=1)
    definicion: str = ""
    agregacion: str = "suma"
    campo: str | None = None
    numerador: str | None = None
    denominador: str | None = None
    filtros: list[dict[str, Any]] = Field(default_factory=list)
    dimensiones: list[str] = Field(default_factory=list)
    unidad: str = ""
    dueno_id: UUID | None = None


class NuevaVersion(BaseModel):
    motivo: str = Field(..., min_length=1)
    cambios: dict[str, Any] = Field(default_factory=dict)


class Cohortes(BaseModel):
    sujetos: list[dict[str, Any]] = Field(
        ..., description="{id, alta, actividad: [fechas]} — los trae quien llama"
    )
    periodo: str = "mes"
    periodos: int = 6
    hoy: date | None = None


class Embudo(BaseModel):
    etapas: list[str] = Field(..., min_length=2)
    recorridos: list[dict[str, Any]] = Field(default_factory=list)


class Correlacion(BaseModel):
    sujetos: list[dict[str, Any]] = Field(default_factory=list)
    metrica: str = "cerrado"


class PreguntaEnContexto(BaseModel):
    pregunta: str = Field(..., min_length=1)
    objeto: str = Field(..., min_length=1)
    registro_id: UUID
    etiqueta: str = ""


# ── Almacén analítico ─────────────────────────────────────────────────────


@router.post(
    "/tablas",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("informe:write"))],
    summary="Declarar una tabla del almacén analítico",
    description=(
        "El almacén es **otro sitio**: se alimenta por cargas declaradas y no "
        "consultando el operacional en vivo, que es lo que hace que el CRM vaya "
        "lento justo cuando se sacan los informes."
    ),
)
def declarar_tabla(datos: DeclararTabla, uow: UowDep) -> Any:
    fila = alm.declarar_tabla(uow, **datos.model_dump())
    return {"id": str(fila.id), "clave": fila.clave, "estrategia": fila.estrategia}


@router.post(
    "/cargas",
    dependencies=[Depends(exige_permiso("informe:write"))],
    summary="Cargar filas en el almacén",
    description=(
        "Las entrega el servicio dueño, con su `clave_origen`: sin ella repetir "
        "una carga duplica las filas y todos los recuentos salen al doble. La "
        "marca de agua **solo avanza si la carga termina bien**."
    ),
)
def cargar(datos: Cargar, uow: UowDep) -> Any:
    return alm.cargar(uow, **datos.model_dump())


@router.post(
    "/cargar",
    dependencies=[Depends(exige_permiso("informe:write"))],
    summary="Cargar el almacén ahora",
    description=(
        "Trae las filas de cada tabla declarada por la API pública del propio CRM, "
        "con una credencial de solo lectura. Es lo que hace que «Frescura» deje de "
        "decir «nunca cargada»: el diseño original esperaba que cada servicio "
        "empujara lo suyo y ninguno lo hizo nunca.\n\n"
        "Un fallo en una tabla no para las demás, y cada una lleva su resultado."
    ),
)
def cargar_ahora(uow: UowDep, principal: AutenticadoDep, tabla: str = Query("")) -> Any:
    from services.analytics import cargador

    clave_api, base = cargador.clave_y_base(principal.tenant_id)
    if not base:
        from crmcore.errors import NoDisponible

        raise NoDisponible(
            "Falta CI_URL_DEL_CRM: sin saber con qué dirección se ve a sí mismo, "
            "el CRM no puede leerse para llenar el almacén.",
            error_code="almacen.sin_direccion",
        )
    if tabla:
        return cargador.cargar_tabla(uow, tabla, clave_api=clave_api, base_url=base)
    return cargador.cargar_todas(uow, clave_api=clave_api, base_url=base)


@router.get(
    "/frescura",
    dependencies=[Depends(exige_permiso("informe:read"))],
    summary="De cuándo son los datos de cada tabla",
    description=(
        "Un panel que enseña datos de anoche como si fueran de ahora hace que "
        "alguien llame a un cliente con una cifra que ya no existe."
    ),
)
def frescura(db: DbDep, principal: AutenticadoDep) -> Any:
    return alm.frescura(db, principal.tenant_id)


@router.get(
    "/tablas/{tabla}",
    dependencies=[Depends(exige_permiso("informe:read"))],
    summary="Leer del almacén, con la edad del dato",
)
def leer(
    tabla: str, db: DbDep, principal: AutenticadoDep, limite: int = Query(1000, ge=1, le=10000)
) -> Any:
    return alm.leer(db, principal.tenant_id, tabla=tabla, limite=limite)


@router.post(
    "/destinos",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("informe:write"))],
    summary="Declarar un destino de exportación continua",
    description=(
        "La lista de tablas es obligatoria: exportar «todo» por defecto saca datos "
        "personales a un sitio que quizá no está preparado para tenerlos."
    ),
)
def declarar_destino(datos: DeclararDestino, uow: UowDep) -> Any:
    fila, avisos = alm.declarar_destino(uow, **datos.model_dump())
    return {"id": str(fila.id), "clave": fila.clave, "avisos": avisos}


@router.get(
    "/destinos/{destino}/envio",
    dependencies=[Depends(exige_permiso("informe:read"))],
    summary="Qué hay que mandar desde la última marca",
    description="**Prepara, no envía**: el envío lo hace quien sabe hablar con ese almacén.",
)
def preparar_envio(
    destino: str, db: DbDep, principal: AutenticadoDep, tope: int = Query(10000, ge=1, le=100000)
) -> Any:
    return alm.preparar_envio(db, principal.tenant_id, destino=destino, tope=tope)


@router.post(
    "/destinos/confirmar",
    dependencies=[Depends(exige_permiso("informe:write"))],
    summary="Avanzar las marcas tras un envío confirmado",
    description=(
        "Con error no se avanza nada: un destino que avanza la marca tras un fallo "
        "se salta ese tramo para siempre."
    ),
)
def confirmar_envio(datos: ConfirmarEnvio, uow: UowDep) -> Any:
    fila = alm.confirmar_envio(uow, **datos.model_dump())
    return {"clave": fila.clave, "marcas": fila.marcas, "error": fila.ultimo_error}


@router.get(
    "/destinos",
    dependencies=[Depends(exige_permiso("informe:read"))],
    summary="Retraso y errores de las exportaciones",
)
def retraso(db: DbDep, principal: AutenticadoDep) -> Any:
    return alm.retraso_exportacion(db, principal.tenant_id)


@router.post(
    "/federadas",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("informe:write"))],
    summary="Declarar un lake del cliente consultable sin copiar",
    description=(
        "Los objetos consultables son obligatorios: sin lista, una consulta "
        "federada puede leer el lake entero con nuestra credencial."
    ),
)
def declarar_federada(datos: DeclararFederada, uow: UowDep) -> Any:
    fila = alm.declarar_fuente_federada(uow, **datos.model_dump())
    return {"id": str(fila.id), "clave": fila.clave, "objetos": fila.objetos}


@router.get(
    "/federadas/{fuente}/plan",
    dependencies=[Depends(exige_permiso("informe:read"))],
    summary="Plan de consulta federada",
    description=(
        "Plan y no SQL (RT-4). Y dice lo que **no** se puede hacer: cruzarlo con "
        "tablas del CRM exigiría traer una de las dos, que es copiar con otro nombre."
    ),
)
def plan_federado(
    fuente: str,
    db: DbDep,
    principal: AutenticadoDep,
    objeto: str = Query(..., min_length=1),
    limite: int | None = Query(None),
) -> Any:
    return alm.plan_federado(db, principal.tenant_id, fuente=fuente, objeto=objeto, limite=limite)


# ── Modelo semántico ──────────────────────────────────────────────────────


@router_metricas.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("informe:write"))],
    summary="Definir una métrica",
    description="Nace **en borrador**: una métrica que nace certificada no la ha revisado nadie.",
)
def definir(datos: DefinirMetrica, uow: UowDep) -> Any:
    fila, avisos = sem.definir(uow, **datos.model_dump())
    return {"id": str(fila.id), "clave": fila.clave, "version": fila.version, "avisos": avisos}


@router_metricas.get(
    "",
    dependencies=[Depends(exige_permiso("informe:read"))],
    summary="Diccionario de métricas",
    description=(
        "Las no certificadas **también salen**, marcadas: esconderlas hace que se "
        "calculen en una hoja aparte, que es peor."
    ),
)
def catalogo(db: DbDep, principal: AutenticadoDep, solo_certificadas: bool = Query(False)) -> Any:
    return sem.catalogo(db, principal.tenant_id, solo_certificadas=solo_certificadas)


@router_metricas.get(
    "/{clave}",
    dependencies=[Depends(exige_permiso("informe:read"))],
    summary="Una métrica",
    # Por qué se añadió, que no es lo que lee quien abre la pantalla:
    # Existe para que la métrica tenga FICHA. El front deriva la ficha de
    # que haya un `GET` por identificador, y de la ficha cuelgan las
    # acciones: sin esta ruta, certificar o versionar estaban en la API y
    # no se podían hacer desde ninguna pantalla.
)
def una_metrica(clave: str, db: DbDep, principal: AutenticadoDep) -> Any:
    return sem.una(db, principal.tenant_id, clave)


@router_metricas.post(
    "/{clave}/certificar",
    dependencies=[Depends(exige_permiso("informe:write"))],
    summary="Certificar una métrica",
    description="Exige dueño y definición escrita: sin dueño no se puede corregir cuando falle.",
)
def certificar(
    clave: str, uow: UowDep, principal: AutenticadoDep, dueno_id: UUID | None = Query(None)
) -> Any:
    fila = sem.certificar(uow, clave=clave, por=principal.id, dueno_id=dueno_id)
    return {"clave": fila.clave, "version": fila.version, "estado": fila.estado}


@router_metricas.post(
    "/{clave}/versiones",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("informe:write"))],
    summary="Crear una versión nueva",
    description=(
        "Con motivo obligatorio: un número publicado que cambia sin explicación "
        "hace que se desconfíe de todos los demás."
    ),
)
def nueva_version(clave: str, datos: NuevaVersion, uow: UowDep) -> Any:
    fila = sem.nueva_version(uow, clave=clave, motivo=datos.motivo, **datos.cambios)
    return {"clave": fila.clave, "version": fila.version, "estado": fila.estado}


@router_metricas.get(
    "/{clave}/plan",
    dependencies=[Depends(exige_permiso("informe:read"))],
    summary="Plan de cálculo de una métrica",
    description=(
        "Se puede pedir una **versión concreta**: es lo que permite reproducir un "
        "informe de hace tres meses con la definición de entonces."
    ),
)
def plan_metrica(
    clave: str,
    db: DbDep,
    principal: AutenticadoDep,
    version: int | None = Query(None),
    dimensiones: list[str] | None = Query(None),
) -> Any:
    return sem.plan_de(
        db, principal.tenant_id, clave=clave, version=version, dimensiones=dimensiones
    )


@router_metricas.post(
    "/{clave}/ejecutar",
    dependencies=[Depends(exige_permiso("informe:read"))],
    summary="Cuánto vale ahora mismo",
    # Por qué se añadió, que no es lo que lee quien abre la pantalla:
    # Existía el PLAN de cálculo y no existía el cálculo. O sea que una
    # métrica se podía definir, versionar y certificar, y no se podía ver
    # cuánto vale: la pantalla enseñaba su definición y nada más. Una
    # métrica que no se puede mirar no es una métrica, es una ficha.
    description=(
        "El número **nunca va solo**: lleva su unidad, si está certificada y el "
        "aviso cuando no lo está. Un número sin eso se copia a una presentación "
        "y allí ya parece oficial.\n\n"
        "Lo calcula el mismo motor que los informes. Dos motores dando la misma "
        "cifra es cómo se acaba con dos números distintos para «cuántas "
        "oportunidades hay», y entonces la discusión deja de ser sobre el "
        "negocio."
    ),
)
def ejecutar_metrica(
    clave: str,
    db: DbDep,
    principal: AutenticadoDep,
    version: int | None = Query(None),
    dimensiones: list[str] | None = Query(None),
) -> Any:
    return sem.ejecutar(
        db,
        principal.tenant_id,
        clave=clave,
        version=version,
        dimensiones=dimensiones,
        usuario_id=principal.id,
        roles=frozenset(principal.roles or []),
        es_admin=principal.es_admin_plataforma,
    )


# ── Análisis ──────────────────────────────────────────────────────────────


@router_analisis.post(
    "/cohortes",
    dependencies=[Depends(exige_permiso("informe:read"))],
    summary="Retención por cohorte",
    description=(
        "Un periodo sin terminar sale como `inmaduro` y una cohorte pequeña no da "
        "porcentaje: marcarlas al 0 % las pinta como un desastre que no ha pasado."
    ),
)
def cohortes(datos: Cohortes) -> Any:
    return coh.cohortes(**datos.model_dump())


@router_analisis.post(
    "/embudo",
    dependencies=[Depends(exige_permiso("informe:read"))],
    summary="Conversión y tiempos entre etapas",
    description=(
        "Lo abierto no cuenta como perdido, y el tiempo es la **mediana**: un solo "
        "negocio de dos años mueve la media de todo el trimestre."
    ),
)
def embudo(datos: Embudo) -> Any:
    return coh.embudo(**datos.model_dump())


@router_analisis.post(
    "/actividad",
    dependencies=[Depends(exige_permiso("informe:read"))],
    summary="Relación entre actividad y resultados",
    description=(
        "Devuelve el coeficiente **con el aviso de que correlación no es causa**: "
        "exigir el mismo número de llamadas al resto infla la actividad sin mover "
        "los cierres."
    ),
)
def actividad(datos: Correlacion) -> Any:
    return coh.correlacion_actividad(**datos.model_dump())


@router_analisis.post(
    "/contexto",
    dependencies=[Depends(exige_permiso("informe:read"))],
    summary="Preguntar sobre el registro que se está mirando",
    description=(
        "El filtro se **añade**, no se sugiere, y se devuelve visible: un número "
        "que parece de toda la empresa y es de una cuenta no cuadra con nada en la "
        "reunión siguiente."
    ),
)
def contexto(datos: PreguntaEnContexto, db: DbDep, principal: AutenticadoDep) -> Any:
    return fue.contexto_del_registro(db, principal.tenant_id, **datos.model_dump())


@router_analisis.get(
    "/despliegue",
    dependencies=[Depends(exige_permiso("informe:read"))],
    summary="Cómo está resuelta la dependencia de contecintelligence",
    description=(
        "La pila lo levanta con el perfil `bi`, o se apunta a uno ya en marcha. "
        "Las dos valen; lo que no vale es no saber cuál está en uso."
    ),
)
def despliegue() -> Any:
    return ci.modo_despliegue()


# ── Listados de las sub-colecciones ───────────────────────────────────────
# Mismo agujero que en las colecciones raíz: se podían crear y no se podían
# leer. Un sobre de firma, una tabla del almacén o una predicción que no se
# pueden listar no existen para quien tiene que revisarlos.

montar_listado(
    router,
    modelo=TablaAnalitica,
    objeto="tabla_analitica",
    permiso="informe:read",
    ruta="/tablas",
    nombre="Tablas del almacén",
)
montar_listado(
    router,
    modelo=FuenteFederada,
    objeto="fuente_federada",
    permiso="informe:read",
    ruta="/federadas",
    nombre="Fuentes federadas",
)


ROUTERS_ALMACEN = [router, router_metricas, router_analisis]


# ── La ficha del registro ─────────────────────────────────────────────────
# Sin ella, las acciones que cuelgan de un registro no se alcanzan desde
# ninguna pantalla: existen, se prueban y nadie las usa.
# Sin lectura: una métrica se lee por su CLAVE —`GET /metricas/{clave}`, más
# arriba— porque es así como se la nombra en un informe y en una pregunta. La
# lectura genérica por id tiene los mismos tramos, se declaraba después y era
# inalcanzable: quien la pidiera con un UUID acabaría en la de clave, que
# buscaría una métrica llamada como ese UUID y contestaría 404. Editar y borrar
# sí van por id, y esos no chocan con nada.
montar_ficha(
    router_metricas,
    modelo=sem.Metrica,
    objeto="metrica",
    permiso_leer="analitica:consultar",
    permiso_escribir="analitica:administrar",
    nombre="Métricas",
    parametro="metrica_id",
    con_lectura=False,
)
montar_ficha(
    router,
    modelo=alm.DestinoExportacion,
    objeto="destino_exportacion",
    permiso_leer="analitica:consultar",
    permiso_escribir="analitica:administrar",
    nombre="Destinos de exportación",
    ruta="/destinos",
    parametro="destino_id",
)
