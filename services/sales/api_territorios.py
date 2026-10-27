"""API de territorios, cuotas y capacidad (CRM-03.02.02)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from crmcore import fechas
from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from crmcore.http.listados import montar_ficha, montar_listado
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from services.sales import territorios as ter
from services.sales.territorios import Cuota


def _trimestre_en_curso(db: Any = None) -> tuple[date, date]:
    """El trimestre natural de hoy.

    Un informe de periodo que exige fechas contesta 422 a quien solo abre la
    pantalla, y «faltan desde y hasta» no es una respuesta útil a «enséñame la
    consecución». Sin fechas se entiende lo que entendería cualquiera: este
    trimestre.

    Con sesión, el trimestre en curso es el de **donde está el cliente**: el 1 de
    enero a la una de la mañana en Madrid, en UTC todavía es diciembre, y el
    informe que se abre solo sale con el trimestre anterior.
    """
    hoy = fechas.hoy(db)
    primer_mes = 3 * ((hoy.month - 1) // 3) + 1
    desde = date(hoy.year, primer_mes, 1)
    siguiente = date(hoy.year + (primer_mes + 3 > 12), (primer_mes + 3 - 1) % 12 + 1, 1)
    return desde, siguiente - timedelta(days=1)


router = APIRouter(prefix="/territorios", tags=["territorios"])
router_cuotas = APIRouter(prefix="/cuotas", tags=["territorios"])


class CrearTerritorio(BaseModel):
    clave: str = Field(..., min_length=1, max_length=80)
    nombre: str = Field(..., min_length=1, max_length=200)
    descripcion: str = ""
    criterios: list[dict[str, Any]] = Field(
        default_factory=list,
        description="geografia · sector · tamano · producto · canal · nominal",
        examples=[
            [
                {
                    "tipo": "geografia",
                    "condiciones": [
                        {"atributo": "cuenta.provincia", "operador": "en", "valor": ["B", "GI"]}
                    ],
                }
            ]
        ],
    )
    padre_id: UUID | None = None
    prioridad: int = Field(
        100,
        description=(
            "Cuando dos encajan gana el más bajo. Declarado, no implícito: con "
            "desempate por orden de inserción, el dueño de una cuenta cambiaría al "
            "restaurar una copia"
        ),
    )
    responsable_id: UUID | None = None


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("opportunity:write"))],
    summary="Crear un territorio",
    description=(
        "Nace **en borrador** a propósito: es lo que permite montar el mapa entero "
        "—con sus solapes y sus huecos— antes de que mueva una sola cuenta."
    ),
)
def crear(datos: CrearTerritorio, uow: UowDep) -> Any:
    fila, avisos = ter.crear(uow, **datos.model_dump())
    return {"id": str(fila.id), "clave": fila.clave, "estado": fila.estado, "avisos": avisos}


@router.get(
    "",
    dependencies=[Depends(exige_permiso("opportunity:read"))],
    summary="Territorios del tenant",
)
def listar(db: DbDep, principal: AutenticadoDep) -> Any:
    filas = (
        db.execute(
            select(ter.Territorio)
            .where(ter.Territorio.tenant_id == principal.tenant_id)
            .order_by(ter.Territorio.prioridad, ter.Territorio.clave)
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(f.id),
            "clave": f.clave,
            "nombre": f.nombre,
            "estado": f.estado,
            "prioridad": f.prioridad,
            "responsable_id": str(f.responsable_id) if f.responsable_id else None,
        }
        for f in filas
    ]


class Cuentas(BaseModel):
    cuentas: list[dict[str, Any]] = Field(
        ...,
        description="Las cuentas a repartir, con los atributos que miran los criterios",
        examples=[[{"id": "…", "nombre": "Acme", "provincia": "B", "sector": "industria"}]],
    )


@router.post(
    "/simular",
    dependencies=[Depends(exige_permiso("opportunity:read"))],
    summary="Qué pasaría si se publicara el mapa",
    description=(
        "**Publicar y ver qué pasa** significa que doscientas cuentas cambian de "
        "dueño el lunes por la mañana, y deshacerlo no devuelve las conversaciones "
        "que ya se tuvieron.\n\n"
        "Dice lo que cambia, lo que se queda **sin territorio** y lo que queda en "
        "**solape** —dos territorios con la misma prioridad—, que es el error que "
        "produce una asignación dependiente del orden alfabético y que nadie busca "
        "hasta que dos comerciales discuten."
    ),
)
def simular(datos: Cuentas, db: DbDep, principal: AutenticadoDep) -> Any:
    return ter.simular(db, principal.tenant_id, datos.cuentas)


@router.post(
    "/{territorio_id}/publicar",
    dependencies=[Depends(exige_permiso("opportunity:write"))],
    summary="Publicar un territorio",
)
def publicar(territorio_id: UUID, uow: UowDep) -> Any:
    return ter.publicar(uow, territorio_id)


class MiembroIn(BaseModel):
    usuario_id: UUID
    solo_lectura: bool = Field(
        False,
        description=("Si solo mira o además es dueño de las cuentas del territorio"),
    )


@router.get(
    "/{territorio_id}/miembros",
    dependencies=[Depends(exige_permiso("opportunity:read"))],
    summary="Quién trabaja este territorio",
    description=(
        "El responsable **y** los miembros. El responsable va dentro a propósito: "
        "es quien lo trabaja por definición, y dejarlo fuera obligaría a cada "
        "pantalla a acordarse de sumarlo.\n\n"
        "Se podía añadir gente y quitarla, y no se podía mirar quién había: para "
        "saber a quién afectaba un cambio de territorio había que quitarlo y ver "
        "quién se quejaba."
    ),
)
def miembros(territorio_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    gente = ter.miembros_de(db, principal.tenant_id, territorio_id)
    return {
        "territorio_id": str(territorio_id),
        "usuarios": [str(u) for u in gente],
        "cuantos": len(gente),
    }


@router.post(
    "/{territorio_id}/miembros",
    dependencies=[Depends(exige_permiso("opportunity:write"))],
    summary="Sumar a alguien al territorio",
    description=(
        "Y **vuelve a publicar el mapa**, que es lo que hace que sirva de algo: "
        "la visibilidad por territorio la resuelve cada servicio contra su copia "
        "replicada, y esa copia solo cambia cuando llega el evento. Añadir un "
        "miembro sin republicar lo deja apuntado en el maestro y sin efecto en "
        "ninguna pantalla — que es peor que no poder añadirlo, porque parece "
        "hecho.\n\n"
        "Si el territorio todavía no está publicado **no se emite nada**: "
        "publicarlo es una decisión que se toma una vez, y adelantarla aquí haría "
        "que un mapa a medio montar empezara a asignar cuentas."
    ),
)
def anadir_miembro(territorio_id: UUID, cuerpo: MiembroIn, uow: UowDep) -> Any:
    return ter.anadir_miembro(
        uow,
        territorio_id=territorio_id,
        usuario_id=cuerpo.usuario_id,
        solo_lectura=cuerpo.solo_lectura,
    )


@router.delete(
    "/{territorio_id}/miembros/{usuario_id}",
    dependencies=[Depends(exige_permiso("opportunity:write"))],
    summary="Sacar a alguien del territorio",
    description=(
        "Se republica también al quitar, y es la mitad que más importa: quien "
        "deja un territorio tiene que dejar de ver sus cuentas **ese día**. Un "
        "alta que se propaga y una baja que no es la forma más silenciosa de que "
        "alguien siga viendo la cartera de la que ya no se ocupa."
    ),
)
def quitar_miembro(territorio_id: UUID, usuario_id: UUID, uow: UowDep) -> Any:
    return ter.quitar_miembro(uow, territorio_id=territorio_id, usuario_id=usuario_id)


@router.post(
    "/aplicar",
    dependencies=[Depends(exige_permiso("opportunity:write"))],
    summary="Escribir las asignaciones calculadas",
)
def aplicar(datos: Cuentas, uow: UowDep, principal: AutenticadoDep) -> Any:
    return ter.aplicar(uow, principal.tenant_id, datos.cuentas)


@router.post(
    "/resolver",
    dependencies=[Depends(exige_permiso("opportunity:read"))],
    summary="A qué territorio va esta cuenta, y por qué",
    description=(
        "El **porqué** se devuelve siempre. Sin él, «¿por qué esta cuenta es de "
        "Norte?» no tiene respuesta, y esa es justo la pregunta que abre la "
        "discusión entre dos comerciales — que no se cierra con un número, se "
        "cierra con una regla."
    ),
)
def resolver(
    cuenta: dict[str, Any], db: DbDep, principal: AutenticadoDep, cuenta_id: UUID | None = None
) -> Any:
    return ter.resolver(db, principal.tenant_id, cuenta, cuenta_id=cuenta_id)


class Excepcion(BaseModel):
    cuenta_id: UUID
    territorio_id: UUID
    motivo: str = Field(
        ...,
        min_length=1,
        description=(
            "Obligatorio. Una excepción sin motivo es indistinguible de un error, y "
            "nadie se atreve a quitarla dos años después"
        ),
    )
    hasta: date | None = None


@router.post(
    "/excepciones",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("opportunity:write"))],
    summary="Sacar una cuenta de su territorio por decisión",
    description=(
        "La excepción **manda sobre cualquier regla**: es el punto entero de que "
        "exista. Siempre hay una cuenta nominal que lleva el director aunque esté "
        "en la zona de otro, y si no se puede declarar, alguien la reasigna a mano "
        "y el siguiente recálculo se la quita — y entonces nadie vuelve a fiarse "
        "del recálculo."
    ),
)
def excepcion(datos: Excepcion, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = ter.declarar_excepcion(uow, por=principal.id, **datos.model_dump())
    return {"id": str(fila.id), "cuenta_id": str(fila.cuenta_id)}


class CrearCuota(BaseModel):
    desde: date
    hasta: date
    objetivo: Decimal
    usuario_id: UUID | None = None
    equipo: str | None = None
    territorio_id: UUID | None = None
    periodo: str = Field("trimestral", description="mensual · trimestral · anual")
    metrica: str = Field(
        "importe", description="importe · unidades · oportunidades · nuevos_clientes · margen"
    )
    moneda: str = "EUR"
    familia: str | None = None
    activa_desde: date | None = Field(
        None, description="Para quien entra a mitad de periodo: de aquí sale el prorrateo"
    )
    activa_hasta: date | None = None


@router_cuotas.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("forecast:write"))],
    summary="Fijar una cuota",
)
def crear_cuota(datos: CrearCuota, uow: UowDep) -> Any:
    fila = ter.crear_cuota(uow, **datos.model_dump())
    return {"id": str(fila.id), "prorrateo": ter.prorratear(fila)}


class CongelarObjetivo(BaseModel):
    periodo: str = Field(
        ...,
        min_length=1,
        max_length=20,
        description="Como lo nombra quien lo cierra: 2026, 2026-T3, 2026-07",
        examples=["2026-T3"],
    )
    motivo: str = Field("", max_length=500)


class DescongelarObjetivo(BaseModel):
    periodo: str = Field(..., min_length=1, max_length=20, examples=["2026-T3"])
    motivo: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description=(
            "Obligatorio. Una reapertura sin motivo es justo lo que congelar " "viene a impedir"
        ),
    )


@router_cuotas.post(
    "/congelar",
    dependencies=[Depends(exige_permiso("forecast:congelar"))],
    summary="Cerrar el objetivo de un periodo (CRM-03.02.02.08)",
    description=(
        "A partir de aquí, el objetivo de ese periodo deja de tocarse: ni a "
        "mano ni recargando la hoja.\n\n"
        "**Lo que se congela es el objetivo, no la consecución.** Lo vendido "
        "sigue entrando; congelar la consecución sería congelar la realidad.\n\n"
        "Permiso aparte de `forecast:write` a propósito: fijar una cuota es "
        "trabajo de todos los días y cerrar el periodo no."
    ),
)
def congelar_objetivo(datos: CongelarObjetivo, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = ter.congelar_objetivo(uow, periodo=datos.periodo, por=principal.id, motivo=datos.motivo)
    return {
        "periodo": fila.periodo,
        "congelado_at": fila.congelado_at.isoformat(),
        "motivo": fila.motivo,
    }


@router_cuotas.post(
    "/descongelar",
    dependencies=[Depends(exige_permiso("forecast:congelar"))],
    summary="Abrirlo otra vez, dejando constancia",
    description=(
        "El motivo es obligatorio. Permitir una reapertura sin motivo convierte "
        "el cierre en un trámite de dos clics, que es no tener cierre."
    ),
)
def descongelar_objetivo(datos: DescongelarObjetivo, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = ter.descongelar_objetivo(
        uow, periodo=datos.periodo, por=principal.id, motivo=datos.motivo
    )
    return {
        "periodo": fila.periodo,
        "descongelado_at": fila.descongelado_at.isoformat() if fila.descongelado_at else None,
        "motivo": fila.motivo_descongelacion,
    }


@router_cuotas.get(
    "/congelaciones",
    dependencies=[Depends(exige_permiso("forecast:read"))],
    summary="Qué periodos están cerrados, y los que se reabrieron",
    description=(
        "Con su historial: una reapertura legítima —se revisa el plan a mitad "
        "de año— tiene que dejar rastro, y con un simple interruptor el segundo "
        "cierre pisaría al primero."
    ),
)
def listar_congelaciones(db: DbDep, principal: AutenticadoDep) -> Any:
    from sqlalchemy import select as _select

    filas = (
        db.execute(
            _select(ter.CongelacionObjetivo)
            .where(ter.CongelacionObjetivo.tenant_id == principal.tenant_id)
            .order_by(ter.CongelacionObjetivo.congelado_at.desc())
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(f.id),
            "periodo": f.periodo,
            "congelado_at": f.congelado_at.isoformat(),
            "congelado_por": str(f.congelado_por) if f.congelado_por else None,
            "motivo": f.motivo,
            "vigente": f.descongelado_at is None,
            "descongelado_at": f.descongelado_at.isoformat() if f.descongelado_at else None,
            "descongelado_por": str(f.descongelado_por) if f.descongelado_por else None,
            "motivo_descongelacion": f.motivo_descongelacion,
        }
        for f in filas
    ]


@router_cuotas.get(
    "/consecucion",
    dependencies=[Depends(exige_permiso("forecast:read"))],
    summary="Cuánto lleva cada uno, y el ranking",
    description=(
        "El ranking sale **por porcentaje y no por importe**: por importe, quien "
        "lleva la cuenta grande gana siempre y el ranking deja de decir nada sobre "
        "quién trabaja bien.\n\n"
        "Lo logrado lo trae quien llama: vive en las oportunidades, y calcularlo "
        "aquí sería recalcular el forecast con otro criterio — y dos números "
        "distintos de lo mismo es peor que uno solo."
    ),
)
def consecucion(
    db: DbDep,
    principal: AutenticadoDep,
    desde: date | None = Query(None, description="Por defecto, el trimestre en curso"),
    hasta: date | None = Query(None, description="Por defecto, el trimestre en curso"),
) -> Any:
    por_defecto = _trimestre_en_curso(db)
    return ter.consecucion(
        db, principal.tenant_id, desde=desde or por_defecto[0], hasta=hasta or por_defecto[1]
    )


class Cobertura(BaseModel):
    desde: date
    hasta: date
    pipeline_por_sujeto: dict[str, Decimal] = Field(default_factory=dict)
    logrado_por_sujeto: dict[str, Decimal] = Field(default_factory=dict)
    minimo: Decimal = Field(
        Decimal(3),
        description=(
            "Cobertura mínima. No es una ley: un equipo que cierra el 50 % necesita "
            "dos y uno que cierra el 15 % necesita casi siete"
        ),
    )


@router_cuotas.post(
    "/cobertura",
    dependencies=[Depends(exige_permiso("forecast:read"))],
    summary="Si hay pipeline suficiente para llegar",
    description=(
        "Se mide contra la cuota que **queda**, no contra la del periodo. A mitad "
        "de trimestre, comparar el pipeline con la cuota entera dice que todo el "
        "mundo va mal incluso cuando van bien, y a fuerza de decirlo deja de "
        "mirarse."
    ),
)
def cobertura(datos: Cobertura, db: DbDep, principal: AutenticadoDep) -> Any:
    return ter.cobertura(
        db,
        principal.tenant_id,
        desde=datos.desde,
        hasta=datos.hasta,
        pipeline_por_sujeto=datos.pipeline_por_sujeto,
        logrado_por_sujeto=datos.logrado_por_sujeto,
        minimo=datos.minimo,
    )


# ── Listados ──────────────────────────────────────────────────────────────
# Estas colecciones se podían crear y no se podían leer: tenían `POST` y no
# tenían `GET`, así que lo que se daba de alta desaparecía de la vista. La API
# contestaba 405 y el front —que las declara listables— enseñaba una pantalla
# vacía sin decir por qué.

montar_listado(
    router_cuotas,
    modelo=Cuota,
    objeto="cuota",
    permiso="forecast:read",
    nombre="Cuotas",
)


ROUTERS_TERRITORIOS = [router, router_cuotas]


# ── La ficha del registro ─────────────────────────────────────────────────
# Sin ella, las acciones que cuelgan de un registro no se alcanzan desde
# ninguna pantalla: existen, se prueban y nadie las usa.
montar_ficha(
    router,
    modelo=ter.Territorio,
    objeto="territorio",
    permiso_leer="forecast:read",
    permiso_escribir="forecast:write",
    nombre="Territorios",
    parametro="territorio_id",
)
