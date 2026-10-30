"""API de campañas, atribución, presión de contacto y rebotes
(CRM-02.02.01, CRM-02.02.02.06, CRM-02.03.01.04).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from crmcore.http.listados import montar_ficha, montar_listado
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from services.marketing import campanas as cmp
from services.marketing.campanas import Campana, Rebote, ReglaFatiga

router_campanas = APIRouter(prefix="/campanas", tags=["campañas"])
router_atribucion = APIRouter(prefix="/atribucion", tags=["campañas"])
router_presion = APIRouter(prefix="/presion", tags=["campañas"])
router_rebotes = APIRouter(prefix="/rebotes", tags=["campañas"])


class CrearCampana(BaseModel):
    clave: str = Field(max_length=80)
    nombre: str = Field(max_length=300)
    nivel: str = Field("campana", description=" | ".join(cmp.NIVELES))
    padre_id: UUID | None = None
    tipo: str = Field("email", max_length=60)
    canal: str = Field("email", max_length=40)
    desde: date | None = None
    hasta: date | None = None
    presupuesto: Decimal | None = None
    moneda: str = Field("EUR", max_length=3)
    objetivos: dict[str, Any] = Field(default_factory=dict)
    segmento_id: UUID | None = None
    lugar: str | None = None
    aforo: int | None = None


@router_campanas.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("campaign:write"))],
    summary="Crear un programa, una campaña o una táctica",
    description=(
        "La jerarquía es real, no una etiqueta: una táctica cuelga de una campaña "
        "y una campaña de un programa, nunca al revés. Sin la comprobación el "
        "árbol se desordena en dos semanas y el consumo de presupuesto deja de "
        "poder subir.\n\n"
        "Un **evento o feria es una campaña**, no una tabla aparte: tiene "
        "presupuesto, miembros y resultados, y separarlo obligaría a duplicar la "
        "atribución y el ROI para él solo."
    ),
)
def crear(datos: CrearCampana, uow: UowDep, principal: AutenticadoDep) -> Any:
    cuerpo = datos.model_dump()
    fila = cmp.crear(
        uow,
        clave=cuerpo.pop("clave"),
        nombre=cuerpo.pop("nombre"),
        nivel=cuerpo.pop("nivel"),
        padre_id=cuerpo.pop("padre_id"),
        **cuerpo,
    )
    return {"id": str(fila.id), "clave": fila.clave, "nivel": fila.nivel}


class Gasto(BaseModel):
    importe: Decimal
    concepto: str = ""


@router_campanas.post(
    "/{campana_id}/gasto",
    dependencies=[Depends(exige_permiso("campaign:write"))],
    summary="Imputar gasto",
    description=(
        "El gasto se imputa **donde ocurre** —la táctica— y sube por la jerarquía "
        "al consultarlo, no al escribirlo. Sumarlo hacia arriba al escribir "
        "obligaría a recalcularlo todo cada vez que alguien mueve una táctica, y "
        "el primer fallo dejaría dos totales distintos sin saber cuál es bueno."
    ),
)
def gasto(campana_id: UUID, datos: Gasto, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = cmp.imputar_gasto(uow, campana_id, importe=datos.importe, concepto=datos.concepto)
    return {"id": str(fila.id), "gasto": str(fila.gasto)}


@router_campanas.get(
    "/{campana_id}/consumo",
    dependencies=[Depends(exige_permiso("campaign:read"))],
    summary="Presupuesto contra gasto, con lo de abajo incluido",
    description=(
        "Se dice si **lo repartido abajo supera lo asignado arriba**: no es un "
        "fallo, es un aviso de planificación, pero enseñarlo evita la sorpresa de "
        "octubre."
    ),
)
def consumo(campana_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return cmp.consumo(db, principal.tenant_id, campana_id)


@router_campanas.get(
    "/calendario",
    dependencies=[Depends(exige_permiso("campaign:read"))],
    summary="Qué hay en marcha y qué se solapa",
    description=(
        "El solapamiento que importa no es el de fechas: es el de **audiencia y "
        "canal**. Dos campañas la misma semana a públicos distintos no molestan a "
        "nadie; dos al mismo público por el mismo canal sí.\n\n"
        "Se dice cuántas campañas en curso **no tienen fechas**: quedan fuera del "
        "calendario, y quien lo mira creería que no hay nada más en marcha."
    ),
)
def calendario(
    db: DbDep, principal: AutenticadoDep, desde: date = Query(...), hasta: date = Query(...)
) -> Any:
    return cmp.calendario(db, principal.tenant_id, desde=desde, hasta=hasta)


class Miembros(BaseModel):
    objeto_ids: list[UUID]
    objeto: str = "contacto"
    fuente: str = Field(
        "segmento", description="segmento | importacion | inscripcion | manual | api"
    )


@router_campanas.post(
    "/{campana_id}/miembros",
    dependencies=[Depends(exige_permiso("campaign:write"))],
    summary="Meter gente en la campaña",
    description=(
        "Repetir una alta **no reinicia su estado**: quien ya está en «clicado» no "
        "puede volver a «objetivo» porque alguien recargó el segmento. El embudo "
        "se quedaría a cero cada vez que se refresca la audiencia."
    ),
)
def miembros(campana_id: UUID, datos: Miembros, uow: UowDep, principal: AutenticadoDep) -> Any:
    return cmp.anadir_miembros(
        uow,
        campana_id,
        objeto_ids=datos.objeto_ids,
        objeto=datos.objeto,
        fuente=datos.fuente,
    )


class Avanzar(BaseModel):
    objeto_id: UUID
    estado: str = Field(description=" | ".join(cmp.ESTADOS_MIEMBRO))


@router_campanas.put(
    "/{campana_id}/miembros",
    dependencies=[Depends(exige_permiso("campaign:write"))],
    summary="Mover a un miembro por el embudo",
    description=(
        "**No retrocede.** Que alguien abra un correo después de haber respondido "
        "no lo devuelve a «abierto»: el embudo mide hasta dónde llegó cada uno, y "
        "permitir el retroceso haría que las tasas bajaran solas con el tiempo sin "
        "que nadie hubiera hecho nada peor."
    ),
)
def avanzar(campana_id: UUID, datos: Avanzar, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = cmp.avanzar(uow, campana_id, datos.objeto_id, estado=datos.estado)
    return {"objeto_id": str(fila.objeto_id), "estado": fila.estado}


@router_campanas.get(
    "/{campana_id}/miembros",
    dependencies=[Depends(exige_permiso("campaign:read"))],
    summary="Quiénes están en la campaña, con su estado",
    # Por qué se añadió, que no es lo que lee quien abre la pantalla:
    # Faltaba: se podían añadir miembros y cambiarles el estado, y no
    # había forma de listarlos. El embudo dice cuántos hay en cada estado
    # y no quiénes, y para quien lleva la campaña la diferencia entre «40
    # han hecho clic» y poder llamarlos es toda.
    description=(
        "Se puede filtrar por estado, que es lo que se hace con esto: la lista "
        "entera de una campaña de veinte mil no la mira nadie; los que abrieron "
        "y no respondieron, sí."
    ),
)
def listar_miembros(
    campana_id: UUID,
    db: DbDep,
    principal: AutenticadoDep,
    estado: str = Query("", max_length=20),
    limite: int = Query(200, ge=1, le=1000),
) -> Any:
    return cmp.miembros_de(db, principal.tenant_id, campana_id, estado=estado, limite=limite)


@router_campanas.get(
    "/{campana_id}/embudo",
    dependencies=[Depends(exige_permiso("campaign:read"))],
    summary="El embudo de la campaña",
    description=(
        "**Acumulado** y no por estado actual: quien respondió también abrió, y "
        "contar solo el estado actual daría «5 abiertos y 40 respondidos», que no "
        "se sostiene y hace que nadie se crea el resto del informe."
    ),
)
def embudo(campana_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return cmp.embudo(db, principal.tenant_id, campana_id)


@router_campanas.get(
    "/{campana_id}/rendimiento",
    dependencies=[Depends(exige_permiso("campaign:read"))],
    summary="Coste por lead, coste por conversión y ROI",
    description=(
        "Los ingresos atribuidos llegan **de fuera**: los calcula quien conoce las "
        "oportunidades, que es `sales`. Si no llegan, se dice que el ROI **no es "
        "medible** en vez de devolver cero — que se leería como «no trajo nada»."
    ),
)
def rendimiento(
    campana_id: UUID,
    db: DbDep,
    principal: AutenticadoDep,
    ingresos_atribuidos: Decimal | None = Query(None),
) -> Any:
    return cmp.rendimiento(
        db, principal.tenant_id, campana_id, ingresos_atribuidos=ingresos_atribuidos
    )


# ── Eventos y ferias (CRM-02.02.01.07) ────────────────────────────────────


class Inscripcion(BaseModel):
    objeto_id: UUID
    objeto: str = "contacto"


@router_campanas.post(
    "/{campana_id}/inscripciones",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("campaign:write"))],
    summary="Inscribir a alguien en un evento",
    description="Respeta el aforo declarado.",
)
def inscribir(campana_id: UUID, datos: Inscripcion, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = cmp.inscribir(uow, campana_id, datos.objeto_id, objeto=datos.objeto)
    return {"objeto_id": str(fila.objeto_id), "estado": fila.estado}


class Asistencia(BaseModel):
    objeto_id: UUID
    asistio: bool


@router_campanas.put(
    "/{campana_id}/asistencia",
    dependencies=[Depends(exige_permiso("campaign:write"))],
    summary="Marcar quién apareció de verdad",
    description=(
        "Inscribirse y aparecer no es lo mismo, y la diferencia entre las dos es "
        "el dato que decide si el evento salió bien. Sin él, uno con trescientas "
        "inscripciones y ochenta asistentes se informa como un éxito."
    ),
)
def asistencia(campana_id: UUID, datos: Asistencia, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = cmp.marcar_asistencia(uow, campana_id, datos.objeto_id, asistio=datos.asistio)
    return {"objeto_id": str(fila.objeto_id), "asistio": fila.asistio}


@router_campanas.get(
    "/{campana_id}/evento",
    dependencies=[Depends(exige_permiso("campaign:read"))],
    summary="Resultado del evento",
    description=(
        "Se dice **cuántos no se marcaron**: sin eso, una asistencia baja podría "
        "ser que no vino nadie o que nadie pasó lista, y son dos problemas "
        "opuestos."
    ),
)
def evento(campana_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return cmp.resultado_evento(db, principal.tenant_id, campana_id)


# ── Atribución (CRM-02.02.01.06) ──────────────────────────────────────────


@router_atribucion.get(
    "/leads/{lead_id}",
    dependencies=[Depends(exige_permiso("campaign:read"))],
    summary="A qué campañas se atribuye esta venta",
    description=(
        "Se calculan **varios modelos sobre los mismos toques y se enseñan "
        "juntos**. El primer toque premia a quien trajo al desconocido; el "
        "último, a quien cerró: las dos respuestas son defendibles, y elegir una "
        "y presentarla como «el ROI» es lo que hace que nadie se crea los "
        "informes de marketing.\n\n"
        "La **ventana** existe porque un toque de hace tres años no trajo esta "
        "venta: sin ella, la primera campaña que hizo la empresa se lleva el "
        "crédito de todo lo que pase después.\n\n"
        "Los toques **sin campaña no se descartan**: se agrupan aparte. "
        "Descartarlos haría que el tráfico directo y el boca a boca parecieran no "
        "existir."
    ),
)
def atribuir(
    lead_id: UUID,
    db: DbDep,
    principal: AutenticadoDep,
    importe: Decimal = Query(...),
    ventana_dias: int = Query(90, ge=1, le=1095),
    modelo: list[str] = Query(default=[]),
) -> Any:
    return cmp.atribuir(
        db,
        principal.tenant_id,
        lead_id=lead_id,
        importe=importe,
        modelos=list(modelo) or None,
        ventana_dias=ventana_dias,
    )


# ── Presión de contacto (CRM-02.02.02.06) ─────────────────────────────────


class CrearFatiga(BaseModel):
    canal: str = Field("email", max_length=20)
    maximo: int = Field(3, ge=1, le=100)
    ventana_dias: int = Field(7, ge=1, le=365)
    horas_minimas: int = Field(0, ge=0, le=720)


@router_presion.put(
    "/reglas",
    dependencies=[Depends(exige_permiso("campaign:write"))],
    summary="Regla de fatiga por canal",
    description=(
        "Hay **dos límites y no uno**: un tope semanal no impide mandar los tres "
        "el mismo martes por la mañana, que es exactamente lo que el destinatario "
        "percibe como acoso."
    ),
)
def regla_fatiga(datos: CrearFatiga, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = uow.db.execute(
        select(cmp.ReglaFatiga).where(
            cmp.ReglaFatiga.tenant_id == principal.tenant_id,
            cmp.ReglaFatiga.canal == datos.canal,
        )
    ).scalar_one_or_none()
    if fila is None:
        fila = cmp.ReglaFatiga(tenant_id=principal.tenant_id, canal=datos.canal)
        uow.db.add(fila)
    fila.maximo = datos.maximo
    fila.ventana_dias = datos.ventana_dias
    fila.horas_minimas = datos.horas_minimas
    uow.db.flush()
    return {"canal": fila.canal, "maximo": fila.maximo, "ventana_dias": fila.ventana_dias}


@router_presion.get(
    "/comprobar/{objeto_id}",
    dependencies=[Depends(exige_permiso("campaign:read"))],
    summary="¿Se le puede escribir hoy a esta persona?",
    description=(
        "Las comunicaciones **transaccionales no cuentan**: un aviso de servicio, "
        "una factura o la respuesta a un caso no son marketing, y contarlas haría "
        "que un cliente con muchas incidencias dejara de recibir lo que ha "
        "pedido.\n\n"
        "Devuelve la decisión en vez de lanzar: hay envíos legítimos que "
        "justifican saltarse el tope —el aviso de fin de contrato— y esa decisión "
        "tiene que quedar en quien envía."
    ),
)
def comprobar(
    objeto_id: UUID, db: DbDep, principal: AutenticadoDep, canal: str = Query("email")
) -> Any:
    return cmp.comprobar_fatiga(db, principal.tenant_id, objeto_id, canal=canal)


@router_presion.get(
    "",
    dependencies=[Depends(exige_permiso("campaign:read"))],
    summary="A cuánta gente le hemos escrito y cuántas veces",
    description=(
        "Es la diferencia entre una campaña y una denuncia, y el dato solo existe "
        "si se cuenta desde el principio: cuando alguien pregunta, ya es tarde "
        "para empezar a contar. Por eso se cuenta **aunque no haya regla de "
        "fatiga**."
    ),
)
def presion(
    db: DbDep,
    principal: AutenticadoDep,
    dias: int = Query(7, ge=1, le=365),
    canal: str = Query("email"),
) -> Any:
    return cmp.presion(db, principal.tenant_id, dias=dias, canal=canal)


# ── Rebotes y quejas (CRM-02.03.01.04) ────────────────────────────────────


class AnotarRebote(BaseModel):
    direccion: str = Field(max_length=320)
    tipo: str = Field(description="duro | blando | queja")
    codigo: str = ""
    detalle: str = ""
    campana_id: UUID | None = None
    proveedor: str = ""


@router_rebotes.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("campaign:write"))],
    summary="Registrar un rebote o una queja",
    description=(
        "**Un duro suprime al instante**: la dirección no existe, y seguir "
        "escribiéndole hunde la reputación de envío del dominio — y con ella la "
        "entrega de todos los correos, incluidos los que sí importan.\n\n"
        "**Una queja suprime y es permanente**: alguien ha pulsado «esto es "
        "spam».\n\n"
        "**Los blandos se acumulan.** Uno aislado es normal —el buzón estaba "
        "lleno—; varios seguidos son una dirección muerta. Sin el histórico hay "
        "que elegir entre suprimir al primer fallo, perdiendo contactos buenos, o "
        "no suprimir nunca."
    ),
)
def rebote(datos: AnotarRebote, uow: UowDep, principal: AutenticadoDep) -> Any:
    return cmp.anotar_rebote(
        uow,
        direccion=datos.direccion,
        tipo=datos.tipo,
        codigo=datos.codigo,
        detalle=datos.detalle,
        campana_id=datos.campana_id,
        proveedor=datos.proveedor,
    )


@router_rebotes.get(
    "/salud",
    dependencies=[Depends(exige_permiso("campaign:read"))],
    summary="Tasas de rebote y de queja, con el umbral al lado",
    description=(
        "Se enseñan **por separado y con el umbral del sector**: una tasa de queja "
        "del 0,3 % suena a poco y es el triple de lo que los proveedores toleran "
        "antes de empezar a mandar a la carpeta de spam. Un número sin referencia "
        "no dice si hay que hacer algo."
    ),
)
def salud(db: DbDep, principal: AutenticadoDep, dias: int = Query(30, ge=1, le=365)) -> Any:
    return cmp.salud_de_envio(db, principal.tenant_id, dias=dias)


# ── Listados ──────────────────────────────────────────────────────────────
# Estas colecciones se podían crear y no se podían leer: tenían `POST` y no
# tenían `GET`, así que lo que se daba de alta desaparecía de la vista. La API
# contestaba 405 y el front —que las declara listables— enseñaba una pantalla
# vacía sin decir por qué.

montar_listado(
    router_presion,
    modelo=ReglaFatiga,
    objeto="regla_fatiga",
    permiso="campaign:read",
    ruta="/reglas",
    nombre="Reglas de presión de contacto",
)
montar_listado(
    router_campanas,
    modelo=Campana,
    objeto="campana",
    permiso="campaign:read",
    nombre="Campañas",
)
montar_listado(
    router_rebotes,
    modelo=Rebote,
    objeto="rebote",
    permiso="campaign:read",
    nombre="Rebotes y quejas",
)


ROUTERS_CAMPANAS = [router_campanas, router_atribucion, router_presion, router_rebotes]


# ── Fichas: ver, editar y borrar ──────────────────────────────────────────
# De los veintidós recursos que el front deja crear, uno solo se podía abrir,
# editar y borrar. Estos no tenían ni ficha: se creaban y no había forma de
# volver a verlos —ni de corregir una errata— desde ninguna pantalla.
montar_ficha(
    router_campanas,
    modelo=Campana,
    objeto="campana",
    permiso_leer="campaign:read",
    permiso_escribir="campaign:write",
    nombre="Campañas",
    parametro="campana_id",
)
