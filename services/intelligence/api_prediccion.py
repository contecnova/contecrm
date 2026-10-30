"""API de modelos predictivos y señales de conversación (CRM-05.02.01,
CRM-03.02.01.06, CRM-04.02.02.06 y CRM-04.02.02.07).

Ninguna de estas rutas escribe en el CRM. Puntúan, predicen, avisan y resumen; lo
que hay que hacer con eso lo decide una persona, y por eso todas devuelven el
porqué al lado del número. Una API que devolviera solo `{"score": 78}` obligaría
a cada frontend a inventarse una explicación, y se la inventaría distinta.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from crmcore.http.listados import montar_listado
from crmcore.http.trabajos_router import crear_router_trabajos
from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, Field

from services.intelligence import anomalias as ano
from services.intelligence import conversacion as conv
from services.intelligence import gobierno as gob
from services.intelligence import prediccion as pred
from services.intelligence import salud as sal
from services.intelligence.prediccion import Prediccion
from services.intelligence.salud import SaludCuenta

router_modelos_ml = APIRouter(prefix="/ia/modelos", tags=["ia"])
router_prediccion = APIRouter(prefix="/ia/prediccion", tags=["ia"])
router_salud = APIRouter(prefix="/ia/salud", tags=["ia"])
router_anomalias = APIRouter(prefix="/ia/anomalias", tags=["ia"])
router_conversacion = APIRouter(prefix="/ia/conversacion", tags=["ia"])


# ── Gobierno de modelos ───────────────────────────────────────────────────


class RegistrarVersion(BaseModel):
    tipo: str = Field(..., description="scoring_lead · cierre · churn · anomalia …")
    variables: list[str] = Field(default_factory=list)
    pesos: dict[str, float] = Field(default_factory=dict)
    metricas: dict[str, float] = Field(default_factory=dict)
    datos_desde: date | None = None
    datos_hasta: date | None = None
    ejemplos: int = 0
    vigencia_dias: int = 180
    notas: str = ""


class MedirDeriva(BaseModel):
    tipo: str
    metrica: str
    valor: float
    muestras: int
    desde: date
    hasta: date


@router_modelos_ml.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("ia:administrar"))],
    summary="Registrar una versión de modelo entrenada con datos del tenant",
    description=(
        "Cada tenant entrena con lo suyo (CRM-05.02.01.06). La respuesta incluye "
        "los avisos: un modelo con pocos ejemplos se registra, pero se dice."
    ),
)
def registrar_version(cuerpo: RegistrarVersion, uow: UowDep) -> Any:
    modelo, avisos = gob.registrar_version(uow, **cuerpo.model_dump())
    return {
        "id": str(modelo.id),
        "tipo": modelo.tipo,
        "version": modelo.version,
        "estado": modelo.estado,
        "avisos": avisos,
    }


@router_modelos_ml.post(
    "/{tipo}/versiones/{version}/activar",
    dependencies=[Depends(exige_permiso("ia:administrar"))],
    summary="Activar una versión",
    description=(
        "Exige métricas y devuelve la comparación con la anterior: activar a ciegas "
        "es cómo un modelo peor se queda meses en producción (CRM-05.02.01.07)."
    ),
)
def activar(tipo: str, version: int, uow: UowDep) -> Any:
    return gob.activar(uow, tipo=tipo, version=version)


@router_modelos_ml.get(
    "",
    dependencies=[Depends(exige_permiso("ia:administrar"))],
    summary="Qué modelos hay, con qué métricas y desde cuándo",
)
def estado_modelos(db: DbDep, principal: AutenticadoDep) -> Any:
    return gob.estado_modelos(db, principal.tenant_id)


@router_modelos_ml.get(
    "/deriva",
    dependencies=[Depends(exige_permiso("ia:administrar"))],
    summary="Cómo ha ido acertando el modelo con el tiempo",
    # Por qué se añadió, que no es lo que lee quien abre la pantalla:
    # Las mediciones se anotaban y no las leía nadie: había ruta para
    # escribir una y ninguna para verlas. Una deriva que no se mira no
    # avisa de nada, que es lo contrario de para lo que se mide.
    description=(
        "Cada medición va con **su referencia y la caída** respecto a ella: un "
        "AUC de 0,71 no dice nada solo y dice mucho al lado del 0,86 con el que "
        "se entrenó. Y con **cuántos casos** se midió, porque una caída medida "
        "sobre catorce casos no es la misma noticia que una medida sobre "
        "catorce mil."
    ),
)
def historial_de_deriva(
    db: DbDep,
    principal: AutenticadoDep,
    modelo_id: UUID | None = Query(None),
    limite: int = Query(200, ge=1, le=1000),
) -> Any:
    return gob.historial_de_deriva(db, principal.tenant_id, modelo_id=modelo_id, limite=limite)


@router_modelos_ml.post(
    "/deriva",
    dependencies=[Depends(exige_permiso("ia:administrar"))],
    summary="Anotar una medición de deriva",
    description=(
        "Se mide contra lo que pasó de verdad, no contra el entrenamiento: lo "
        "segundo solo dice que el modelo se acuerda de lo que vio."
    ),
)
def medir_deriva(cuerpo: MedirDeriva, uow: UowDep) -> Any:
    return gob.medir_deriva(uow, **cuerpo.model_dump())


# ── Scoring y predicción ──────────────────────────────────────────────────


class Puntuar(BaseModel):
    tipo: str
    objeto: str = Field(..., max_length=60)
    objeto_id: UUID
    rasgos: dict[str, Any] = Field(default_factory=dict)
    vigencia_dias: int = 14


class AnotarReal(BaseModel):
    tipo: str
    objeto_id: UUID
    real: Decimal


class ForecastPredictivo(BaseModel):
    oportunidades: list[dict[str, Any]] = Field(default_factory=list)
    forecast_humano: Decimal | None = None


@router_prediccion.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Puntuar un registro con explicación",
    description=(
        "Devuelve el número, lo que empuja a favor y **lo que empuja en contra** "
        "(CRM-05.02.01.01, .03). Un scoring que solo enseña lo bueno convierte a "
        "todos los leads en buenos leads."
    ),
)
def puntuar(cuerpo: Puntuar, uow: UowDep) -> Any:
    return pred.puntuar(uow, **cuerpo.model_dump())


# Va ANTES de `/{tipo}/{objeto_id}`: tiene los mismos tramos y «acierto» se leía
# como un tipo de predicción, así que la respuesta era un 422 diciendo que
# «oportunidad» no es un identificador válido.
@router_prediccion.get(
    "/acierto/{tipo}",
    dependencies=[Depends(exige_permiso("ia:administrar"))],
    summary="Cómo está acertando el modelo sobre lo ya cerrado",
)
def acierto(
    tipo: str, db: DbDep, principal: AutenticadoDep, dias: int = Query(90, ge=7, le=730)
) -> Any:
    return pred.acierto(db, principal.tenant_id, tipo=tipo, dias=dias)


@router_prediccion.get(
    "/{tipo}/{objeto_id}",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="La última predicción, si no ha caducado",
    description=(
        "Una caducada no se devuelve: nadie mira la fecha de un número que aparece " "en una ficha."
    ),
)
def vigente(tipo: str, objeto_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return pred.vigente(db, principal.tenant_id, tipo=tipo, objeto_id=objeto_id)


@router_prediccion.post(
    "/real",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Anotar lo que pasó de verdad",
    description="Sin esto la deriva no se puede medir contra la realidad.",
)
def anotar_real(cuerpo: AnotarReal, uow: UowDep) -> Any:
    fila = pred.anotar_real(uow, **cuerpo.model_dump())
    if fila is None:
        return {"anotada": False, "porque": "No había predicción para ese registro."}
    return {"anotada": True, "prediccion_id": str(fila.id)}


@router_prediccion.post(
    "/forecast",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Forecast predictivo al lado del humano",
    description=(
        "No lo sustituye (CRM-03.02.01.06): devuelve los dos, la diferencia y qué "
        "parte del pipeline no se ha podido puntuar."
    ),
)
def forecast(cuerpo: ForecastPredictivo, db: DbDep, principal: AutenticadoDep) -> Any:
    return pred.forecast_predictivo(
        db,
        principal.tenant_id,
        oportunidades=cuerpo.oportunidades,
        forecast_humano=cuerpo.forecast_humano,
    )


# ── Salud de cuenta ───────────────────────────────────────────────────────


class MedirSalud(BaseModel):
    cuenta_id: UUID
    senales: dict[str, Any] = Field(default_factory=dict)
    pesos: dict[str, int] | None = None
    umbrales: dict[str, int] | None = None


@router_salud.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Medir la salud de una cuenta (CRM-05.02.01.04)",
    description=(
        "Las señales que no llegan no puntúan cero: se reparte su peso y se avisa "
        "de cuánto del total quedó sin medir."
    ),
)
def medir_salud(cuerpo: MedirSalud, uow: UowDep) -> Any:
    fila = sal.medir(uow, **cuerpo.model_dump())
    return {
        "cuenta_id": str(fila.cuenta_id),
        "puntuacion": float(fila.puntuacion),
        "nivel": fila.nivel,
        "fiable": fila.fiable,
        "porque": fila.motivo,
        "detalle": fila.detalle,
        "senales_ausentes": fila.senales_ausentes,
    }


@router_salud.post(
    "/medir-todas",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Medir la salud de todas las cuentas",
    description=(
        "Calcula las señales que el CRM ya conoce —relación, soporte, "
        "patrocinador y valor— leyéndolas por su propia API con una credencial de "
        "solo lectura, y las pondera con los pesos configurados.\n\n"
        "Las que no se pueden medir aquí (`uso` necesita telemetría del producto y "
        "`pago` el ERP) **se dejan ausentes**: su peso se reparte entre las que sí "
        "llegan y la respuesta dice cuánto quedó sin medir. Un 50 por defecto se "
        "leería como «regular» y significa «no lo sabemos».\n\n"
        "Va en diferido: son cuatro llamadas por cuenta, y una cartera de mil son "
        "cuatro mil."
    ),
)
def medir_todas(respuesta: Response, uow: UowDep, principal: AutenticadoDep) -> Any:
    from services.intelligence.trabajos_salud import encolar_medicion

    trabajo = encolar_medicion(uow.db, tenant_id=principal.tenant_id, pedido_por=principal.id)
    respuesta.status_code = status.HTTP_202_ACCEPTED
    return {
        "trabajo_id": str(trabajo.id),
        "estado": trabajo.estado,
        "consultar_en": f"/api/v1/intelligence/trabajos/{trabajo.id}",
    }


@router_salud.get(
    "/riesgo",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Cuentas que conviene mirar",
    description="Riesgo no es churn confirmado, y la respuesta lo dice con esas palabras.",
)
def en_riesgo(
    db: DbDep,
    principal: AutenticadoDep,
    dias: int = Query(60, ge=1, le=365),
    incluir_no_fiables: bool = Query(False),
) -> Any:
    return sal.en_riesgo(db, principal.tenant_id, dias=dias, incluir_no_fiables=incluir_no_fiables)


@router_salud.get(
    "/{cuenta_id}",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Evolución de una cuenta",
)
def historia_salud(cuenta_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return {"historia": sal.historia(db, principal.tenant_id, cuenta_id)}


# ── Anomalías ─────────────────────────────────────────────────────────────


class Vigilar(BaseModel):
    ambito: str = Field(..., description="pipeline · actividad · servicio · ingresos · datos")
    clave: str = Field(..., max_length=120)
    descripcion: str = ""
    minimo_observaciones: int | None = None
    sigmas: Decimal | None = None


class Observar(BaseModel):
    ambito: str
    clave: str
    fecha: date
    valor: Decimal


class Revisar(BaseModel):
    era_real: bool
    comentario: str = ""


@router_anomalias.post(
    "/series",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("ia:administrar"))],
    summary="Declarar una serie vigilada",
)
def vigilar(cuerpo: Vigilar, uow: UowDep) -> Any:
    serie = ano.vigilar(uow, **cuerpo.model_dump())
    return {
        "id": str(serie.id),
        "ambito": serie.ambito,
        "clave": serie.clave,
        "minimo_observaciones": serie.minimo_observaciones,
        "sigmas": float(serie.sigmas),
    }


@router_anomalias.post(
    "/observaciones",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Registrar un valor y comprobar si es anómalo (CRM-05.02.01.05)",
    description=(
        "Por debajo del mínimo de observaciones devuelve `medible: false` con "
        "cuántas faltan: avisar con cuatro datos es avisar de que la serie es nueva."
    ),
)
def observar(cuerpo: Observar, uow: UowDep) -> Any:
    return ano.observar(uow, **cuerpo.model_dump())


@router_anomalias.get(
    "",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Anomalías por revisar, las más desviadas primero",
)
def pendientes(db: DbDep, principal: AutenticadoDep, limite: int = Query(50, ge=1, le=200)) -> Any:
    return {"anomalias": ano.pendientes(db, principal.tenant_id, limite=limite)}


@router_anomalias.post(
    "/{anomalia_id}/revisar",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Decir si el aviso valía",
    description="Es lo único que permite saber después si el detector sirve o hace ruido.",
)
def revisar(anomalia_id: UUID, cuerpo: Revisar, uow: UowDep) -> Any:
    fila = ano.revisar(uow, anomalia_id=anomalia_id, **cuerpo.model_dump())
    return {"id": str(fila.id), "revisada": fila.revisada, "era_real": fila.era_real}


@router_anomalias.get(
    "/utilidad",
    dependencies=[Depends(exige_permiso("ia:administrar"))],
    summary="Cuánto acierta el detector según quien lo mira",
)
def utilidad(db: DbDep, principal: AutenticadoDep, dias: int = Query(90, ge=7, le=365)) -> Any:
    return ano.utilidad(db, principal.tenant_id, dias=dias)


# ── Señales de conversación ───────────────────────────────────────────────


class Resumir(BaseModel):
    conversacion_id: UUID
    mensajes: list[dict[str, Any]] = Field(default_factory=list)
    momento: str = "cierre"
    caso_id: UUID | None = None
    mensajes_totales: int | None = None


class Clasificar(BaseModel):
    conversacion_id: UUID
    texto: str = Field(..., min_length=1)
    umbral_confianza: float = 0.6
    umbral_escalado: float = 0.8


@router_anomalias.get(
    "/{anomalia_id}",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Una anomalía, con lo que la explica",
    # Por qué se añadió, que no es lo que lee quien abre la pantalla:
    # Existía «decir si el aviso valía» y no existía forma de abrir el
    # aviso: la acción no tenía pantalla desde la que llamarse.
    description=(
        "Lleva el valor, lo que se esperaba, cuánto se desvía y por qué, que es "
        "lo que hace falta para contestar si era real. Sin eso se contesta a ojo, "
        "y entonces la respuesta no mide el detector: mide quién la dio."
    ),
)
def ficha_de_anomalia(anomalia_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return ano.ficha(db, tenant_id=principal.tenant_id, anomalia_id=anomalia_id)


@router_conversacion.get(
    "/resumenes",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Los resúmenes propuestos, con lo que quedó pendiente",
    # Por qué se añadió, que no es lo que lee quien abre la pantalla:
    # Se escribían y no los leía nadie. El resumen existe para que el
    # agente que recoge una conversación no empiece de cero, y ninguna
    # ruta lo devolvía: se generaba, se pagaba al proveedor de IA y se
    # quedaba en una tabla que nadie podía abrir.
    description=(
        "Los **pendientes** van aparte del texto porque son lo que el siguiente "
        "agente lee primero y lo que más se inventa un modelo. Y van **de "
        "cuántos mensajes salió y cuántos se usaron**: un resumen hecho con "
        "veinte de doscientos mensajes no es el mismo documento, y sin esos dos "
        "números los dos se leen igual."
    ),
)
def resumenes_de_conversacion(
    db: DbDep,
    principal: AutenticadoDep,
    conversacion_id: UUID | None = Query(None),
    caso_id: UUID | None = Query(None),
    limite: int = Query(100, ge=1, le=500),
) -> Any:
    return conv.resumenes_de(
        db,
        principal.tenant_id,
        conversacion_id=conversacion_id,
        caso_id=caso_id,
        limite=limite,
    )


@router_conversacion.post(
    "/resumen",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Resumir al cerrar o al transferir (CRM-04.02.02.06)",
    description=(
        "Con `caso_id` el resumen se **pide** al servicio de soporte: el estado es "
        "«pedido», no «hecho», porque el otro lado todavía puede rechazarlo."
    ),
)
def resumir(cuerpo: Resumir, uow: UowDep, principal: AutenticadoDep) -> Any:
    return conv.resumir(uow, principal=principal, **cuerpo.model_dump())


@router_conversacion.post(
    "/senal",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Sentimiento e intención (CRM-04.02.02.07)",
    description=(
        "Por debajo del umbral devuelve `concluyente: false` en vez de «neutro», y "
        "nunca escala sola: `escalado_automatico` es siempre false."
    ),
)
def clasificar(cuerpo: Clasificar, uow: UowDep) -> Any:
    return conv.clasificar(uow, **cuerpo.model_dump())


@router_conversacion.get(
    "/{conversacion_id}",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Cómo ha ido el ánimo a lo largo de la conversación",
)
def evolucion(conversacion_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return conv.evolucion(db, principal.tenant_id, conversacion_id)


# ── Listados de las sub-colecciones ───────────────────────────────────────
# Mismo agujero que en las colecciones raíz: se podían crear y no se podían
# leer. Un sobre de firma, una tabla del almacén o una predicción que no se
# pueden listar no existen para quien tiene que revisarlos.

montar_listado(
    router_prediccion,
    modelo=Prediccion,
    objeto="prediccion",
    permiso="ia:usar",
    nombre="Predicciones",
)
montar_listado(
    router_salud,
    modelo=SaludCuenta,
    objeto="salud_cuenta",
    permiso="ia:usar",
    nombre="Salud de cuentas",
)


# Los trabajos de este servicio. Sin este router, la medición devolvería un
# identificador que no se puede consultar en ninguna parte.
router_trabajos_ia = crear_router_trabajos(
    permiso_ver="ia:usar", permiso_cancelar="ia:administrar", prefijo="/intelligence/trabajos"
)

ROUTERS_PREDICCION = [
    router_trabajos_ia,
    router_modelos_ml,
    router_prediccion,
    router_salud,
    router_anomalias,
    router_conversacion,
]
