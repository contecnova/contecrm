"""API del servicio de inteligencia (CRM-05.02.02).

Todas las rutas que generan devuelven **propuestas**: nada de lo que sale de aquí
queda escrito en el CRM. Lo aplica el servicio dueño del objeto cuando una persona
lo acepta.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from crmcore.errors import ErrorValidacion
from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from crmcore.http.listados import montar_listado
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from services.intelligence import enrutador as rut
from services.intelligence import extraccion as ext
from services.intelligence import generacion as gen
from services.intelligence import guardias as gua
from services.intelligence import rag as rag_mod
from services.intelligence import uso as med


class Veredicto(BaseModel):
    """Si se acepta o se descarta lo que la IA propuso.

    Por cuerpo: la acción se ofrece desde la ficha con un formulario sacado del
    contrato, y un parámetro de query no está en él.
    """

    aceptar: bool = Field(..., description="true acepta el valor propuesto; false lo descarta")


class ConMotivo(BaseModel):
    """El motivo, por cuerpo y no por query.

    Por cuerpo por dos razones: el formulario de la acción se genera del
    contrato y un parámetro de query no aparece en él —la pantalla salía sin
    ningún campo y al enviar contestaba que faltaba el motivo—, y porque un
    texto libre escrito por una persona puede llevar nombres dentro, y la URL
    queda en el log de acceso y en el historial del navegador.
    """

    motivo: str = Field(..., min_length=1, max_length=1000)


router = APIRouter(prefix="/ia", tags=["ia"])
router_modelos = APIRouter(prefix="/ia/proveedores", tags=["ia"])
router_uso = APIRouter(prefix="/ia/uso", tags=["ia"])


class RegistrarProveedor(BaseModel):
    clave: str = Field(..., min_length=1, max_length=80)
    base_url: str = Field(..., min_length=1)
    region: str = Field(..., description="ue · ee_uu · reino_unido · suiza · local · otra")
    nombre: str = ""
    formato: str = Field(
        "openai_chat",
        description="Dialecto del proveedor: openai_chat · anthropic_messages · gemini_generate",
    )
    admite_opt_out: bool = False
    modelos: list[dict[str, Any]] = Field(default_factory=list)
    coste_entrada_millon: Decimal = Decimal(0)
    coste_salida_millon: Decimal = Decimal(0)
    config: dict[str, Any] = Field(default_factory=dict)
    solo_este_tenant: bool = False


class FijarPolitica(BaseModel):
    regiones_admitidas: list[str] = Field(default_factory=list)
    exigir_opt_out: bool = True
    preferencias: dict[str, str] = Field(default_factory=dict)
    presupuesto_mes: Decimal | None = None


class DeclararGuardia(BaseModel):
    clave: str = "por_defecto"
    sensibilidades_permitidas: list[str] = Field(default_factory=list)
    patrones_a_tapar: list[str] = Field(default_factory=list)
    cortar_si_aparece: bool = False
    max_caracteres: int = 100_000


class GuardarPlantilla(BaseModel):
    clave: str = Field(..., min_length=1, max_length=80)
    cuerpo: str = Field(..., min_length=1)
    tarea: str = "redaccion"
    sistema: str = ""
    nombre: str = ""
    idioma_defecto: str = ""
    motivo_version: str = ""


class Generar(BaseModel):
    plantilla: str
    datos: dict[str, Any] = Field(default_factory=dict)
    contexto: list[dict[str, Any]] = Field(
        default_factory=list, description="{texto, permiso, sensibilidad, fuente, id}"
    )
    objeto: str = ""
    objeto_id: UUID | None = None
    idioma: str = ""


class Decidir(BaseModel):
    estado: str = Field(..., description="aceptada · descartada · editada")
    texto_final: str = ""


class Preguntar(BaseModel):
    pregunta: str = Field(..., min_length=1)
    fragmentos: list[dict[str, Any]] = Field(default_factory=list)
    objeto: str = ""
    objeto_id: UUID | None = None


class PreguntarDatos(BaseModel):
    pregunta: str = Field(..., min_length=1)
    modelo_datos: dict[str, Any] = Field(default_factory=dict)


class Extraer(BaseModel):
    texto: str = Field(..., min_length=1)
    campos: list[dict[str, Any]] = Field(..., min_length=1)
    objeto: str = Field(..., min_length=1)
    objeto_id: UUID | None = None
    valores_actuales: dict[str, Any] = Field(default_factory=dict)
    origen: str = ""
    origen_id: str = ""


# ── Proveedores y política ────────────────────────────────────────────────


@router_modelos.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("ia:administrar"))],
    summary="Declarar un proveedor de IA",
    description=(
        "Con su región y si garantiza el opt-out de entrenamiento: las dos son "
        "condiciones del contrato, no preferencias."
    ),
)
def registrar_proveedor(datos: RegistrarProveedor, uow: UowDep) -> Any:
    fila, avisos = rut.registrar_proveedor(uow, **datos.model_dump())
    return {"id": str(fila.id), "clave": fila.clave, "region": fila.region, "avisos": avisos}


@router.post(
    "/politica",
    dependencies=[Depends(exige_permiso("ia:administrar"))],
    summary="Qué admite este tenant",
    description=(
        "Regiones, opt-out obligatorio, preferencia de modelo por uso y "
        "presupuesto mensual. El opt-out viene exigido por defecto: es lo que un "
        "cliente asume sin preguntarlo."
    ),
)
def fijar_politica(datos: FijarPolitica, uow: UowDep) -> Any:
    fila = rut.fijar_politica(uow, **datos.model_dump())
    return {
        "regiones_admitidas": fila.regiones_admitidas,
        "exigir_opt_out": fila.exigir_opt_out,
        "presupuesto_mes": str(fila.presupuesto_mes) if fila.presupuesto_mes else None,
    }


@router.get(
    "/eleccion",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Qué modelo atendería esta petición, y por qué",
    description=(
        "Cuando no se puede llamar, dice **cuál** de las condiciones lo impide: un "
        "«no disponible» a secas manda a revisar la conexión cuando lo que pasa es "
        "que el cliente no admite esa región."
    ),
)
def eleccion(db: DbDep, principal: AutenticadoDep, uso: str = Query("redaccion")) -> Any:
    return rut.elegir(db, principal.tenant_id, uso=uso)


@router.get(
    "/eleccion-sin-salida",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Qué modelo atendería esto sin que el dato salga de la región",
    description=(
        "Es el modo que piden los clientes que **no pueden mandar nada fuera**: "
        "sector público, sanidad, banca. Lo que ofrecen casi todos los productos "
        "es una casilla «no usar IA», que no es lo mismo: el cliente quiere la "
        "función, lo que no quiere es la salida.\n\n"
        "Tres condiciones y las tres tienen que cumplirse. **El proveedor está "
        "en la región del tenant**, no en «una región europea»: un modelo "
        "alojado en otro país de la UE sigue siendo una transferencia dentro del "
        "EEE, que es legal y no es lo que se pidió. **Garantiza que no entrena "
        "con lo que se le manda**, porque un modelo en la región que aprende de "
        "los datos los saca igual: no por la red, por el peso. **O es del propio "
        "cliente**, que es la única forma de que esto no dependa de la promesa "
        "de nadie — y por eso se prefiere cuando está.\n\n"
        "La región sale de la política del tenant cuando admite una sola. Si "
        "admite varias hay que decir cuál, porque elegir por él una de las dos "
        "es justo el supuesto que este modo existe para no hacer."
    ),
)
def eleccion_sin_salida(
    db: DbDep,
    principal: AutenticadoDep,
    uso: str = Query("redaccion"),
    region: str = Query("", description="Vacío: la única región que admita la política"),
) -> Any:
    ficha = rut.politica(db, principal.tenant_id)
    admitidas = [str(r) for r in ((ficha.regiones_admitidas if ficha else None) or [])]
    # Nada por omisión: una región por defecto en el código es la que se queda
    # el día que el cliente admite dos y nadie mira cuál se usó.
    region_elegida = region or (admitidas[0] if len(admitidas) == 1 else "")
    if not region_elegida:
        raise ErrorValidacion(
            "No se sabe en qué región tiene que quedarse el dato: la política "
            f"admite {len(admitidas)}. Hay que decirla, porque elegir una por el "
            "cliente es el supuesto que este modo existe para no hacer.",
            error_code="ia.region_del_tenant_sin_decidir",
            detalle={"regiones_admitidas": admitidas},
        )
    return rut.exigir_sin_salida(db, principal.tenant_id, uso=uso, region_del_tenant=region_elegida)


@router.post(
    "/apagar",
    dependencies=[Depends(exige_permiso("ia:administrar"))],
    summary="Interruptor de IA del tenant",
    description="Corta ahora y se decide después, sin borrar configuración.",
)
def apagar(datos: ConMotivo, uow: UowDep) -> Any:
    fila = rut.apagar(uow, motivo=datos.motivo)
    return {"ia_activa": fila.ia_activa, "datos.motivo": fila.motivo_apagado}


@router.get(
    "/presupuesto",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Lo gastado este mes y lo que queda",
    description=(
        "Sin tope declarado no se dice que quede mucho: se dice que no hay tope, "
        "que es lo que alguien tiene que decidir."
    ),
)
def presupuesto(db: DbDep, principal: AutenticadoDep) -> Any:
    return rut.presupuesto(db, principal.tenant_id)


# ── Guardarraíles ─────────────────────────────────────────────────────────


@router.post(
    "/guardias",
    dependencies=[Depends(exige_permiso("ia:administrar"))],
    summary="Qué puede salir hacia el modelo",
    description=(
        "Por defecto lo personal y lo especial **no salen**: que salgan tiene que "
        "ser una decisión escrita, no el comportamiento por omisión."
    ),
)
def declarar_guardia(datos: DeclararGuardia, uow: UowDep) -> Any:
    fila, avisos = gua.declarar_regla(uow, **datos.model_dump())
    return {"clave": fila.clave, "patrones": fila.patrones_a_tapar, "avisos": avisos}


@router.get(
    "/guardias/bloqueos",
    dependencies=[Depends(exige_permiso("ia:administrar"))],
    summary="Cuántas veces y por qué han saltado",
    description=(
        "Uno que salta mil veces al día estorba; uno que no salta nunca tampoco "
        "protege. Las dos lecturas importan y son opuestas."
    ),
)
def bloqueos(db: DbDep, principal: AutenticadoDep, dias: int = Query(7, ge=1, le=90)) -> Any:
    return gua.resumen_bloqueos(db, principal.tenant_id, dias=dias)


# ── Generación ────────────────────────────────────────────────────────────


@router.post(
    "/plantillas",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("ia:administrar"))],
    summary="Guardar una plantilla de prompt",
    description=(
        "Versionada: el día que los textos salgan raros, la primera pregunta es "
        "qué cambió, y una cadena en el código no lo dice."
    ),
)
def guardar_plantilla(datos: GuardarPlantilla, uow: UowDep) -> Any:
    fila, avisos = gen.guardar_plantilla(uow, **datos.model_dump())
    return {"clave": fila.clave, "version": fila.version, "avisos": avisos}


@router.post(
    "/generar",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Redactar, resumir o traducir",
    description=(
        "Devuelve un **borrador**: no se escribe en el CRM ni se envía a nadie. "
        "Sin contexto suficiente no se llama al modelo — redactaría algo plausible "
        "y vacío."
    ),
)
def generar(datos: Generar, uow: UowDep, principal: AutenticadoDep) -> Any:
    return gen.generar(uow, principal=principal, **datos.model_dump())


@router.post(
    "/propuestas/{propuesta_id}",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Decir qué se hizo con el borrador",
    description=(
        "Sin esto se sabe lo que cuesta la IA y no lo que vale. Lo descartado no "
        "se conserva: es un texto sobre un cliente que nadie ha validado."
    ),
)
def decidir(propuesta_id: UUID, datos: Decidir, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = gen.decidir(uow, propuesta_id, por=principal.id, **datos.model_dump())
    return {"id": str(fila.id), "estado": fila.estado}


@router.get(
    "/calidad",
    dependencies=[Depends(exige_permiso("ia:administrar"))],
    summary="Qué se acepta, qué se corrige y qué se tira",
)
def calidad(db: DbDep, principal: AutenticadoDep, dias: int = Query(30, ge=1, le=365)) -> Any:
    return gen.calidad(db, principal.tenant_id, dias=dias)


# ── Preguntas sobre datos propios ─────────────────────────────────────────


@router.post(
    "/preguntar",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Responder con el contexto dado, citando",
    description=(
        "Sin citas comprobables la respuesta **no se presenta como buena**: un "
        "párrafo perfecto sin fuente es lo que escribe un modelo cuando no "
        "encontró nada."
    ),
)
def preguntar(datos: Preguntar, uow: UowDep, principal: AutenticadoDep) -> Any:
    return rag_mod.responder(uow, principal=principal, **datos.model_dump())


@router.post(
    "/preguntar-datos",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Traducir una pregunta a un plan de consulta",
    description=(
        "El modelo **no toca la base de datos**: propone un plan que ejecuta quien "
        "tiene el dato, con los permisos de quien pregunta. Y devuelve cómo "
        "entendió la pregunta, para verlo antes de llevarse el número a una reunión."
    ),
)
def preguntar_datos(datos: PreguntarDatos, uow: UowDep, principal: AutenticadoDep) -> Any:
    return rag_mod.preguntar_a_los_datos(uow, principal=principal, **datos.model_dump())


# ── Extracción ────────────────────────────────────────────────────────────


@router.post(
    "/extraer",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Sacar campos de un texto",
    description=(
        "Cada campo viene con su **cita literal** y su confianza, y lo que ya "
        "tenía valor queda en conflicto en vez de pisarse: el dato que estaba lo "
        "puso alguien."
    ),
)
def extraer(datos: Extraer, uow: UowDep, principal: AutenticadoDep) -> Any:
    return ext.extraer(uow, principal=principal, **datos.model_dump())


@router.get(
    "/extraidos",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Lo extraído que espera decisión",
    description="Los conflictos primero: son los únicos donde equivocarse borra un dato.",
)
def extraidos(
    db: DbDep,
    principal: AutenticadoDep,
    objeto: str = Query(""),
    limite: int = Query(100, ge=1, le=500),
) -> Any:
    return ext.pendientes(db, principal.tenant_id, objeto=objeto, limite=limite)


@router.post(
    "/extraidos/{campo_id}",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Aceptar o rechazar un campo extraído",
    description=(
        "Aceptar **pide** el cambio al servicio dueño, que aplica sus reglas: "
        "escribir desde aquí saltaría el metamodelo para la IA y para nadie más."
    ),
)
def decidir_campo(campo_id: UUID, datos: Veredicto, uow: UowDep, principal: AutenticadoDep) -> Any:
    return ext.decidir(uow, campo_id, aceptar=datos.aceptar, por=principal.id)


# ── Uso y trazabilidad ────────────────────────────────────────────────────


@router_uso.get(
    "",
    dependencies=[Depends(exige_permiso("ia:administrar"))],
    summary="Consumo, coste y tasa de descarte",
    description=(
        "Las tres juntas: enseñar solo el coste hace que se discuta el precio de "
        "algo cuyo valor nadie ha medido."
    ),
)
def consumo(db: DbDep, principal: AutenticadoDep, dias: int = Query(30, ge=1, le=365)) -> Any:
    return med.consumo(db, principal.tenant_id, dias=dias)


@router_uso.get(
    "/por-dia",
    dependencies=[Depends(exige_permiso("ia:administrar"))],
    summary="Coste diario",
)
def por_dia(db: DbDep, principal: AutenticadoDep, dias: int = Query(30, ge=1, le=365)) -> Any:
    return {"dias": med.por_dia(db, principal.tenant_id, dias=dias)}


@router_uso.get(
    "/registro/{objeto}/{objeto_id}",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Qué ha hecho la IA sobre este registro",
    description="La respuesta a «¿por qué el CRM escribió esto en mi ficha?».",
)
def historial(objeto: str, objeto_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return med.historial_de(db, principal.tenant_id, objeto=objeto, objeto_id=objeto_id)


from services.intelligence.api_agentes import ROUTERS_AGENTES  # noqa: E402
from services.intelligence.api_prediccion import ROUTERS_PREDICCION  # noqa: E402
from services.intelligence.enrutador import ProveedorIA  # noqa: E402

# ── Listados ──────────────────────────────────────────────────────────────
# Estas colecciones se podían crear y no se podían leer: tenían `POST` y no
# tenían `GET`, así que lo que se daba de alta desaparecía de la vista. La API
# contestaba 405 y el front —que las declara listables— enseñaba una pantalla
# vacía sin decir por qué.

montar_listado(
    router_modelos,
    modelo=ProveedorIA,
    objeto="proveedor_ia",
    permiso="ia:administrar",
    nombre="Proveedores de IA",
)


ROUTERS = [router, router_modelos, router_uso, *ROUTERS_PREDICCION, *ROUTERS_AGENTES]
