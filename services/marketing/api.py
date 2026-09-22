"""API de segmentos y puntuación (CRM-02.01.01, CRM-02.01.02)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from services.marketing import puntuacion as pun
from services.marketing import segmentos as seg
from services.marketing.modelos import ModeloPuntuacion, Segmento, Supresion

router_segmentos = APIRouter(prefix="/segmentos", tags=["segmentación"])
router_supresiones = APIRouter(prefix="/supresiones", tags=["segmentación"])
router_puntuacion = APIRouter(prefix="/puntuacion", tags=["calificación de leads"])


# ── Segmentos (CRM-02.01.01.01 a .05) ─────────────────────────────────────


class CrearSegmento(BaseModel):
    clave: str = Field(max_length=80)
    nombre: str = Field(max_length=200)
    objeto: str = Field("contacto", description="contacto | lead | cuenta")
    definicion: dict[str, Any] = Field(
        description=(
            'Árbol anidado: {"op":"y","hijos":[{"atributo":"lead.pais",'
            '"operador":"en","valor":["ES"]}]}. Anidado porque «(A o B) y no C» '
            "es la consulta normal en marketing, y con una lista plana solo se "
            "puede expresar «todo y» o «todo o»"
        )
    )
    dinamico: bool = True
    excluye: list[UUID] = Field(default_factory=list)
    descripcion: str = ""


@router_segmentos.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("segment:write"))],
    summary="Crear un segmento",
    description=(
        "Un segmento es **una definición, no una lista**. Guardar la lista parece "
        "más rápido y es lo que hace que a la semana esté desfasada sin que nadie "
        "lo sepa.\n\n"
        "La definición se valida **y se traduce a SQL al crear**: descubrir que un "
        "segmento no se puede calcular el día del envío es descubrirlo tarde.\n\n"
        "Los operadores temporales son relativos (`hace_menos_de_dias`) y se "
        "evalúan contra el momento de la consulta: guardada la fecha, «leads "
        "recientes» seguiría devolviendo los mismos de hace medio año."
    ),
)
def crear(datos: CrearSegmento, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = seg.crear(
        uow,
        clave=datos.clave,
        nombre=datos.nombre,
        objeto=datos.objeto,
        definicion=datos.definicion,
        dinamico=datos.dinamico,
        excluye=datos.excluye,
        descripcion=datos.descripcion,
    )
    return {"id": str(fila.id), "clave": fila.clave, "dinamico": fila.dinamico}


@router_segmentos.get(
    "",
    dependencies=[Depends(exige_permiso("segment:read"))],
    summary="Segmentos del tenant",
)
def listar(db: DbDep, principal: AutenticadoDep) -> Any:
    filas = (
        db.execute(
            select(Segmento)
            .where(Segmento.tenant_id == principal.tenant_id, Segmento.activo.is_(True))
            .order_by(Segmento.nombre)
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(s.id),
            "clave": s.clave,
            "nombre": s.nombre,
            "objeto": s.objeto,
            "dinamico": s.dinamico,
            "tamano": s.tamano,
            # La fecha va pegada al número: uno sin fecha al lado se lee como
            # actual aunque sea de hace tres semanas, y sobre eso se decide un
            # envío.
            "tamano_at": s.tamano_at.isoformat() if s.tamano_at else None,
        }
        for s in filas
    ]


@router_segmentos.get(
    "/{segmento_id}/tamano",
    dependencies=[Depends(exige_permiso("segment:read"))],
    summary="Cuánta gente hay, ahora mismo",
    description=(
        "Se devuelve el bruto, los alcanzables y **cuántos caen por supresión**. "
        "Enseñar solo el total haría que alguien planificara un envío a diez mil "
        "y saliera a siete mil sin saber por qué faltan tres mil."
    ),
)
def tamano(segmento_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return seg.tamano(db, principal.tenant_id, segmento_id)


@router_segmentos.get(
    "/{segmento_id}/miembros",
    dependencies=[Depends(exige_permiso("segment:read"))],
    summary="Quién está en el segmento",
    description=(
        "Es la API que activa audiencias en canales externos (CRM-02.01.01.05). "
        "Resta las exclusiones **y las supresiones** también en los segmentos "
        "congelados: que uno congelado se librara de las supresiones sería "
        "exactamente el caso que la supresión existe para impedir, porque la baja "
        "pudo llegar después de congelarlo."
    ),
)
def miembros(
    segmento_id: UUID,
    db: DbDep,
    principal: AutenticadoDep,
    limite: int = Query(1000, ge=1, le=50_000),
) -> Any:
    ids = seg.miembros(db, principal.tenant_id, segmento_id, limite=limite)
    return {"miembros": [str(i) for i in ids], "cuantos": len(ids)}


@router_segmentos.post(
    "/{segmento_id}/congelar",
    dependencies=[Depends(exige_permiso("segment:write"))],
    summary="Congelar el segmento en una lista fija",
    description=(
        "Se congela **antes de un envío**, no después: la pregunta «¿a quién se "
        "le mandó?» tiene que poder contestarse en junio con la lista de marzo, y "
        "un segmento dinámico en junio devuelve otra gente."
    ),
)
def congelar(segmento_id: UUID, uow: UowDep, principal: AutenticadoDep) -> Any:
    return seg.congelar(uow, segmento_id)


@router_segmentos.get(
    "/solapamiento",
    dependencies=[Depends(exige_permiso("segment:read"))],
    summary="Cuánta gente comparten dos segmentos",
    description=(
        "La pregunta real no es de estadística: es «si lanzo las dos campañas esta "
        "semana, ¿a cuánta gente le van a llegar las dos?». Por eso se devuelve el "
        "número **y el porcentaje sobre cada uno**: mil personas comunes es mucho "
        "si uno tiene mil doscientos y poco si tiene cien mil."
    ),
)
def solapamiento(
    db: DbDep, principal: AutenticadoDep, a: UUID = Query(...), b: UUID = Query(...)
) -> Any:
    return seg.solapamiento(db, principal.tenant_id, a, b)


# ── Supresiones (CRM-02.01.01.06) ─────────────────────────────────────────


class Suprimir(BaseModel):
    direccion: str = Field(max_length=320)
    canal: str = Field("email", max_length=20)
    motivo: str = Field("baja", description="baja | rebote_duro | queja | manual | lista_negra")
    ambito: str = Field("global", max_length=40)
    detalle: str = ""
    contacto_id: UUID | None = None


@router_supresiones.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("segment:write"))],
    summary="No escribir más a esta dirección",
    description=(
        "Se suprime **por dirección y no por identificador**: la misma persona "
        "puede estar en tres fichas duplicadas, y suprimir una sola dejaría que "
        "las otras dos le siguieran escribiendo — que es exactamente la queja que "
        "acaba en una denuncia.\n\n"
        "El ámbito permite la baja selectiva: «no quiero la newsletter pero sí "
        "los avisos de servicio» es lo que evita que alguien se dé de baja de "
        "todo por no poder darse de baja de una cosa.\n\n"
        "Una queja por spam se marca **permanente**: deshacerla con un clic "
        "convierte la protección en una casilla."
    ),
)
def suprimir(datos: Suprimir, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = seg.suprimir(
        uow,
        direccion=datos.direccion,
        canal=datos.canal,
        motivo=datos.motivo,
        ambito=datos.ambito,
        detalle=datos.detalle,
        contacto_id=datos.contacto_id,
    )
    return {"id": str(fila.id), "permanente": fila.permanente}


class Levantar(BaseModel):
    motivo: str = Field(min_length=1, max_length=1000)


@router_supresiones.delete(
    "/{supresion_id}",
    dependencies=[Depends(exige_permiso("segment:write"))],
    summary="Levantar una supresión",
    description=(
        "Exige motivo escrito: es volver a escribir a alguien que había dicho que "
        "no. Y una supresión permanente **no se levanta desde aquí**."
    ),
)
def levantar(supresion_id: UUID, datos: Levantar, uow: UowDep, principal: AutenticadoDep) -> Any:
    seg.levantar_supresion(uow, supresion_id, motivo=datos.motivo)
    return {"levantada": True}


@router_supresiones.get(
    "",
    dependencies=[Depends(exige_permiso("segment:read"))],
    summary="Lista de supresiones",
)
def listar_supresiones(
    db: DbDep, principal: AutenticadoDep, limite: int = Query(200, ge=1, le=5000)
) -> Any:
    filas = (
        db.execute(
            select(Supresion)
            .where(Supresion.tenant_id == principal.tenant_id)
            .order_by(Supresion.created_at.desc())
            .limit(limite)
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(s.id),
            "canal": s.canal,
            "direccion": s.direccion,
            "motivo": s.motivo,
            "ambito": s.ambito,
            "permanente": s.permanente,
        }
        for s in filas
    ]


# ── Puntuación (CRM-02.01.02.01, .03, .04, .05) ───────────────────────────


class CrearModelo(BaseModel):
    clave: str = Field(max_length=80)
    nombre: str = Field(max_length=200)
    reglas_interes: list[dict[str, Any]] = Field(default_factory=list)
    reglas_encaje: list[dict[str, Any]] = Field(default_factory=list)
    decaimiento_puntos: int = Field(0, ge=0, le=1000)
    decaimiento_dias: int = Field(30, ge=1, le=3650)
    interes_minimo: int = Field(0, ge=0, le=1000)
    umbral_mql_interes: int | None = None
    umbral_mql_encaje: int | None = None
    umbral_sql_interes: int | None = None
    umbral_sql_encaje: int | None = None
    grados: list[dict[str, Any]] = Field(default_factory=list)


@router_puntuacion.post(
    "/modelos",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("segment:write"))],
    summary="Publicar una versión del modelo de puntuación",
    description=(
        "**Dos ejes y no uno.** El error clásico del lead scoring es un solo "
        "número: un estudiante que abre diez correos suma lo mismo que un "
        "director de compras que abrió uno, y a la tercera vez que le pasan un "
        "lead que no compra, ventas deja de fiarse de la lista.\n\n"
        "El **encaje** no decae —que alguien sea director de compras no deja de "
        "ser cierto porque lleve dos meses sin abrir un correo— y el **interés** "
        "sí, porque el interés de hace seis meses no es interés.\n\n"
        "Cada publicación es una **versión**: editar en caliente hace que las "
        "puntuaciones de ayer y las de hoy no sean comparables sin que nadie lo "
        "sepa."
    ),
)
def crear_modelo(datos: CrearModelo, uow: UowDep, principal: AutenticadoDep) -> Any:
    cuerpo = datos.model_dump()
    fila = pun.crear_modelo(
        uow,
        clave=cuerpo.pop("clave"),
        nombre=cuerpo.pop("nombre"),
        reglas_interes=cuerpo.pop("reglas_interes"),
        reglas_encaje=cuerpo.pop("reglas_encaje"),
        **cuerpo,
    )
    return {"id": str(fila.id), "clave": fila.clave, "version": fila.version}


@router_puntuacion.post(
    "/leads/{lead_id}",
    dependencies=[Depends(exige_permiso("lead:write"))],
    summary="Puntuar un lead",
    description=(
        "Para pasar a MQL se exigen **los dos ejes**: con uno solo, o pasan "
        "estudiantes muy activos o directores que no han mostrado ningún "
        "interés.\n\n"
        "El cambio de calificación se emite **solo cuando cambia**: emitirlo en "
        "cada recálculo haría que la regla «avisa a ventas cuando pase a MQL» "
        "disparara cada hora sobre el mismo lead."
    ),
)
def puntuar(
    lead_id: UUID,
    uow: UowDep,
    principal: AutenticadoDep,
    modelo: str = Query("", max_length=80),
) -> Any:
    fila = pun.puntuar(uow, lead_id, modelo_clave=modelo)
    return {
        "lead_id": str(lead_id),
        "interes": fila.interes,
        "encaje": fila.encaje,
        "grado": fila.grado,
        "calificacion": fila.calificacion,
    }


@router_puntuacion.get(
    "/leads/{lead_id}",
    dependencies=[Depends(exige_permiso("lead:read"))],
    summary="Por qué este lead tiene esta puntuación",
    description=(
        "«Este lead tiene 87» no le sirve a nadie: lo que hace que un comercial "
        "llame es saber que descargó el comparativo de precios y visitó la página "
        "de contratación dos veces.\n\n"
        "El decaimiento se enseña aparte: sin él, quien mira no entiende por qué "
        "un lead que hizo muchas cosas tiene poco interés y concluye que el "
        "scoring está roto."
    ),
)
def explicar(lead_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return pun.explicar(db, principal.tenant_id, lead_id)


@router_puntuacion.get(
    "/pendientes",
    dependencies=[Depends(exige_permiso("lead:read"))],
    summary="Leads puntuados con una versión vieja del modelo",
    description=(
        "Publicar una versión nueva no repuntúa a nadie por sí solo, y dejar la "
        "mitad de la base con el modelo viejo hace que dos leads iguales salgan "
        "con puntuaciones distintas — y entonces la lista deja de servir para "
        "ordenar por prioridad, que es lo único para lo que se usa."
    ),
)
def pendientes(
    db: DbDep, principal: AutenticadoDep, limite: int = Query(500, ge=1, le=5000)
) -> Any:
    ids = pun.pendientes_de_recalcular(db, principal.tenant_id, limite=limite)
    return {"leads": [str(i) for i in ids], "cuantos": len(ids)}


@router_puntuacion.get(
    "/modelos",
    dependencies=[Depends(exige_permiso("segment:read"))],
    summary="Modelos de puntuación publicados",
)
def listar_modelos(db: DbDep, principal: AutenticadoDep) -> Any:
    filas = (
        db.execute(
            select(ModeloPuntuacion)
            .where(ModeloPuntuacion.tenant_id == principal.tenant_id)
            .order_by(ModeloPuntuacion.clave, ModeloPuntuacion.version.desc())
        )
        .scalars()
        .all()
    )
    return [
        {
            "clave": m.clave,
            "nombre": m.nombre,
            "version": m.version,
            "activo": m.activo,
            "reglas_interes": len(m.reglas_interes or []),
            "reglas_encaje": len(m.reglas_encaje or []),
            "decaimiento": f"{m.decaimiento_puntos} cada {m.decaimiento_dias} días",
        }
        for m in filas
    ]


from services.marketing.api_campanas import ROUTERS_CAMPANAS  # noqa: E402

ROUTERS = [router_segmentos, router_supresiones, router_puntuacion, *ROUTERS_CAMPANAS]
