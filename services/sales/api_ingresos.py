"""API de ingresos, equipo de venta, grupo de compra y plan conjunto
(CRM-03.01.01.06, .07, .08, .10, .11 · CRM-03.01.02.05, .06 · CRM-01.01.02.04).

Casi todo lo de aquí existe para que una previsión signifique algo: separar lo
recurrente, repartir el ingreso en el tiempo y saber con quién no se ha hablado.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from crmcore import fechas
from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from crmcore.http.listados import montar_listado
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from services.sales import ingresos as ing
from services.sales import plan_conjunto as pc
from services.sales.plan_conjunto import PlanConjuntoCliente


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


router_ingresos = APIRouter(prefix="/ingresos", tags=["ingresos y recurrencia"])
router_planes = APIRouter(prefix="/planes-conjuntos", tags=["plan conjunto y revisión"])


class MetricasIn(BaseModel):
    lineas: list[dict[str, Any]] = Field(default_factory=list)


class CerradasIn(BaseModel):
    cerradas: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Las oportunidades cerradas con su `importe` y su `relacion` "
            "(`nueva`, `renovacion`, `sustitucion`…): la relación es la que "
            "decide si eso es crecimiento o es mantenerse"
        ),
    )


class CalendarioIn(BaseModel):
    oportunidad_id: UUID
    importe_total: Decimal
    desde: date
    meses: int
    tipo: str = "recurrente"
    moneda: str = "EUR"


class RepartoIn(BaseModel):
    oportunidad_id: UUID
    participaciones: list[dict[str, Any]] = Field(default_factory=list)


class RolIn(BaseModel):
    oportunidad_id: UUID
    contacto_id: UUID
    rol: str
    postura: int = 0
    motivo: str = ""


class RelacionIn(BaseModel):
    origen_id: UUID
    destino_id: UUID
    tipo: str


class PlanIn(BaseModel):
    oportunidad_id: UUID
    pasos: list[dict[str, Any]] = Field(default_factory=list)
    fecha_objetivo: date | None = None


class RevisionIn(BaseModel):
    oportunidad_id: UUID
    respuestas: dict[str, str] = Field(default_factory=dict)
    probabilidad_declarada: int = 0
    fecha_declarada: date | None = None
    acuerdos: list[dict[str, Any]] = Field(default_factory=list)


@router_ingresos.post(
    "/metricas",
    dependencies=[Depends(exige_permiso("sales:read"))],
    summary="ARR, MRR, TCV y ACV separando lo recurrente de lo puntual",
    description=(
        "El error clásico es dividir el valor total por los años: un contrato de "
        "dos años con la implantación cobrada aparte tiene un ARR que no se "
        "parece a eso, y la métrica con la que se valora la empresa sale "
        "inflada.\n\n"
        "Aquí cada línea dice de qué tipo es, y lo que no es recurrente **no "
        "entra en el ARR** por mucho que se repita todos los años."
    ),
)
def metricas(cuerpo: MetricasIn, principal: AutenticadoDep) -> Any:
    return ing.metricas_de_ingreso(lineas=cuerpo.lineas)


@router_ingresos.post(
    "/crecimiento",
    dependencies=[Depends(exige_permiso("sales:read"))],
    summary="Cuánto se ha crecido de verdad, descontando lo que solo se mantiene",
    description=(
        "Es la cifra que se enseña en el comité y la que más se infla sin "
        "querer: **sumar las renovaciones al crecimiento hace que un año plano "
        "parezca bueno**, y la corrección llega el día que alguien cruza con "
        "facturación — delante de todo el mundo.\n\n"
        "Una renovación y una sustitución mantienen ingreso; no lo añaden. Se "
        "devuelven los dos números por separado y el porcentaje del cierre que "
        "es crecimiento de verdad, que es el que contesta a «¿vamos bien?»."
    ),
)
def crecimiento(cuerpo: CerradasIn, principal: AutenticadoDep) -> Any:
    return ing.crecimiento_real(cerradas=cuerpo.cerradas)


@router_ingresos.post(
    "/calendario",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("sales:write"))],
    summary="Repartir el importe por periodos",
    description=(
        "Una oportunidad grande que se cobra en doce meses no es un mes bueno: "
        "son doce meses decentes, y la diferencia decide si alguien contrata a un "
        "comercial más.\n\n"
        "El redondeo se ajusta en el último periodo: si sobrara un céntimo, la "
        "suma del calendario no cuadraría con el importe y el descuadre saldría "
        "en un informe seis meses después sin que nadie supiera de dónde viene."
    ),
)
def calendario(cuerpo: CalendarioIn, uow: UowDep) -> Any:
    return ing.planificar_ingresos(
        uow,
        oportunidad_id=cuerpo.oportunidad_id,
        importe_total=cuerpo.importe_total,
        desde=cuerpo.desde,
        meses=cuerpo.meses,
        tipo=cuerpo.tipo,
        moneda=cuerpo.moneda,
    )


@router_ingresos.get(
    "/previsto",
    dependencies=[Depends(exige_permiso("sales:read"))],
    summary="Lo que se espera ingresar por periodo",
    description=(
        "Distinto del forecast por fecha de cierre, y las dos cosas hacen falta: "
        "una dice cuándo se firma y otra cuándo entra el dinero. Confundirlas es "
        "lo que hace que un trimestre «excelente» no se note en caja hasta el "
        "siguiente."
    ),
)
def previsto(
    db: DbDep,
    principal: AutenticadoDep,
    desde: date | None = Query(None, description="Por defecto, el trimestre en curso"),
    hasta: date | None = Query(None, description="Por defecto, el trimestre en curso"),
) -> Any:
    # Con la sesión: el trimestre «en curso» es el de donde está el cliente. El
    # 1 de enero a la una de la mañana en Madrid, sin ella, el por defecto es el
    # último trimestre del año anterior.
    por_defecto = _trimestre_en_curso(db)
    desde, hasta = desde or por_defecto[0], hasta or por_defecto[1]
    return ing.previsto_por_periodo(db, principal.tenant_id, desde=desde, hasta=hasta)


@router_ingresos.post(
    "/reparto",
    dependencies=[Depends(exige_permiso("sales:write"))],
    summary="Repartir el crédito entre comerciales",
    description=(
        "**El crédito suma 100 o no se guarda.** Es la regla más tonta y la que "
        "más se salta: con repartos al 60/60 las comisiones cuadran hacia arriba "
        "y el descuadre lo encuentra finanzas tres meses después, cuando ya se ha "
        "pagado.\n\n"
        "El **overlay no resta**: es apoyo que se reconoce sin quitarle nada al "
        "titular, y mezclarlo con el crédito es lo que hace que la gente invente "
        "porcentajes para que cuadre."
    ),
)
def reparto(cuerpo: RepartoIn, uow: UowDep) -> Any:
    return ing.repartir_credito(
        uow, oportunidad_id=cuerpo.oportunidad_id, participaciones=cuerpo.participaciones
    )


@router_ingresos.post(
    "/rol-compra",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("sales:write"))],
    summary="Qué papel tiene cada contacto en la decisión",
    description=(
        "Decir que alguien está en contra **exige motivo**: es una etiqueta que "
        "otro comercial leerá dentro de seis meses y aplicará sin poder "
        "contrastarla, y encima es una valoración sobre una persona identificada."
    ),
)
def rol_compra(cuerpo: RolIn, uow: UowDep) -> Any:
    fila = ing.anotar_rol(
        uow,
        oportunidad_id=cuerpo.oportunidad_id,
        contacto_id=cuerpo.contacto_id,
        rol=cuerpo.rol,
        postura=cuerpo.postura,
        motivo=cuerpo.motivo,
    )
    return {"id": str(fila.id), "rol": fila.rol}


@router_ingresos.get(
    "/grupo-compra/{oportunidad_id}",
    dependencies=[Depends(exige_permiso("sales:read"))],
    summary="El mapa de la decisión y a quién no se ha visto",
    description=(
        "Lo que hace útil esto no es la lista: es lo que falta. Una oportunidad "
        "sin decisor identificado no está avanzada por mucho que el presupuesto "
        "esté mandado, y un económico con el que nadie ha hablado es la razón más "
        "habitual de que un cierre «seguro» se caiga en la última semana."
    ),
)
def grupo_compra(oportunidad_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return ing.grupo_de_compra(db, principal.tenant_id, oportunidad_id=oportunidad_id)


@router_ingresos.get(
    "/de/{oportunidad_id}",
    dependencies=[Depends(exige_permiso("sales:read"))],
    summary="El reparto y las relacionadas de una oportunidad",
    # Por qué se añadió, que no es lo que lee quien abre la pantalla:
    # Se escribían y no las leía nadie (CRM-03.01.01.08, CRM-03.01.01.11).
    # El reparto entre comerciales y el enlace con la renovación o el
    # upsell se guardaban en su tabla, y esas tablas sólo las consultaba
    # su propio escritor para reemplazar filas: ninguna ruta las devolvía.
    # Se podía declarar quién se lleva qué parte de una comisión y no
    # había forma de comprobarlo hasta que llegaba la liquidación.
    description=(
        "Van juntas porque se miran juntas: delante de una oportunidad las dos "
        "preguntas son «¿quién se lleva esto?» y «¿de qué viene y qué sale de "
        "aquí?».\n\n"
        "El total del crédito viene calculado y con un **sí o no de si cuadra**: "
        "un reparto que no suma 100 es lo que hay que ver de un vistazo, y "
        "dejar que lo sume cada pantalla garantiza que una de ellas no lo sume. "
        "El overlay no entra en esa suma a propósito: es apoyo que no resta al "
        "titular."
    ),
)
def lo_de_esta_oportunidad(oportunidad_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return ing.lo_de_esta_oportunidad(db, principal.tenant_id, oportunidad_id=oportunidad_id)


@router_ingresos.post(
    "/relacionar",
    dependencies=[Depends(exige_permiso("sales:write"))],
    summary="Enlazar dos oportunidades diciendo qué tipo de relación es",
    description=(
        "Importa para el informe: una renovación que sustituye a un contrato **no "
        "es ingreso nuevo**, y contarla como tal duplica el crecimiento del "
        "trimestre. Es de los errores que más tarda en descubrirse, porque el "
        "número sale bien."
    ),
)
def relacionar(cuerpo: RelacionIn, uow: UowDep) -> Any:
    return ing.relacionar(
        uow, origen_id=cuerpo.origen_id, destino_id=cuerpo.destino_id, tipo=cuerpo.tipo
    )


@router_planes.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("sales:write"))],
    summary="Guardar el plan conjunto con el cliente",
    description=(
        "**Tiene que haber pasos del cliente.** Un plan donde todos los pasos son "
        "nuestros es una lista de seguimiento interna con otro nombre: el cliente "
        "ni la mira y no compromete a nadie. Lo valioso es justo lo incómodo — "
        "que el cliente ponga fecha a su parte, porque si no quiere, eso ya es "
        "una respuesta.\n\n"
        "Y cada paso necesita fecha y responsable: sin ellas es una lista de "
        "buenas intenciones que se enseña en la reunión y no se mira entre "
        "reuniones."
    ),
)
def guardar_plan(cuerpo: PlanIn, uow: UowDep) -> Any:
    fila = pc.guardar_plan(
        uow,
        oportunidad_id=cuerpo.oportunidad_id,
        pasos=cuerpo.pasos,
        fecha_objetivo=cuerpo.fecha_objetivo,
    )
    return {"id": str(fila.id), "pasos": len(fila.pasos)}


@router_planes.post(
    "/revision",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("sales:write"))],
    summary="Registrar una revisión estructurada de la oportunidad",
    description=(
        "Se exigen **las preguntas incómodas** —qué puede salir mal y qué falta "
        "por saber—, que son las que la gente se salta. Una revisión sin ellas es "
        "«¿cómo lo ves?» con acta, y el número sube porque el comercial está "
        "metido dentro.\n\n"
        "Y los acuerdos llevan dueño y fecha: «hay que hablar con el director "
        "financiero» sin quién ni cuándo es la misma reunión repetida dentro de "
        "dos semanas."
    ),
)
def revision(cuerpo: RevisionIn, uow: UowDep, principal: AutenticadoDep) -> Any:
    return pc.revisar(
        uow,
        oportunidad_id=cuerpo.oportunidad_id,
        respuestas=cuerpo.respuestas,
        probabilidad_declarada=cuerpo.probabilidad_declarada,
        fecha_declarada=cuerpo.fecha_declarada,
        acuerdos=cuerpo.acuerdos,
        revisada_por=principal.id,
    )


@router_planes.get(
    "/sin-revisar",
    dependencies=[Depends(exige_permiso("sales:read"))],
    summary="Qué oportunidades llevan demasiado sin revisarse",
    description=(
        "Se filtran las grandes y las avanzadas: revisar cien oportunidades "
        "pequeñas al mes es lo que convierte las revisiones en un trámite que "
        "nadie prepara."
    ),
)
def sin_revisar(db: DbDep, principal: AutenticadoDep, dias: int = Query(30)) -> Any:
    from sqlalchemy import select

    from services.sales.modelos import Oportunidad

    filas = list(
        db.execute(
            select(Oportunidad).where(
                Oportunidad.tenant_id == principal.tenant_id,
                Oportunidad.estado == "abierta",
            )
        )
        .scalars()
        .all()
    )
    return pc.sin_revisar(
        oportunidades=[{"id": f.id, "importe": f.importe} for f in filas],
        dias=dias,
        # El día lo pone quien tiene la sesión. `sin_revisar` es pura a
        # propósito; alimentarla con UTC desde aquí sería dejar el fallo intacto
        # un nivel más arriba.
        hoy=fechas.hoy(db),
    )


@router_planes.get(
    "/calibracion",
    dependencies=[Depends(exige_permiso("sales:read"))],
    summary="Cuánto se parece lo que se dice en las revisiones a lo que pasa",
    description=(
        "Es el único uso que justifica guardar las revisiones. Si todo lo que se "
        "revisa al 80 % se gana la mitad de las veces, **el 80 % no significa "
        "80 %**: significa «me gusta este caso», y el forecast construido con eso "
        "no cuadra nunca.\n\n"
        "Con pocas revisiones cerradas **no se concluye**. Llamar optimista a un "
        "equipo con seis casos es injusto y le quita credibilidad al ejercicio "
        "entero, que es como se deja de revisar.\n\n"
        "El resultado de cada revisión se anota **al cerrar la oportunidad**, "
        "que es el único momento en que se sabe."
    ),
)
def calibracion(db: DbDep, principal: AutenticadoDep) -> Any:
    return pc.calibracion(db, principal.tenant_id)


@router_planes.get(
    "/{plan_conjunto_id}/estado",
    dependencies=[Depends(exige_permiso("sales:read"))],
    summary="Cómo va el plan, y de quién es lo que va retrasado",
    description=(
        "Distinguirlo es todo el valor. Si lo que se retrasa es **nuestro**, se "
        "aprieta dentro; si lo que se retrasa es **del cliente**, la fecha de "
        "cierre que hay en el CRM es una ilusión — y eso es lo que hay que "
        "contar antes de que llegue el final del trimestre, no después.\n\n"
        "Se dice además si el cliente lo ha **visto**: un plan «conjunto» que el "
        "cliente no ha abierto es nuestro plan, y conviene que el CRM no diga lo "
        "contrario."
    ),
)
def estado_del_plan(plan_conjunto_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    from crmcore.errors import NoEncontrado

    fila = db.get(PlanConjuntoCliente, plan_conjunto_id)
    if fila is None or fila.tenant_id != principal.tenant_id:
        raise NoEncontrado("Ese plan conjunto no existe", error_code="plan_conjunto.no_encontrado")
    return {
        "plan_conjunto_id": str(fila.id),
        "oportunidad_id": str(fila.oportunidad_id),
        **pc.estado_del_plan(
            plan={
                "pasos": list(fila.pasos or []),
                "compartido_con_el_cliente": fila.compartido_con_el_cliente,
                "visto_por_el_cliente_at": fila.visto_por_el_cliente_at,
            },
            # El día lo pone quien tiene la sesión: «retrasado» calculado en UTC
            # adelanta un día para media Europa de madrugada, y un paso que no lo
            # está sale en rojo delante del cliente.
            hoy=fechas.hoy(db),
        ),
    }


# ── Listados ──────────────────────────────────────────────────────────────
# Estas colecciones se podían crear y no se podían leer: tenían `POST` y no
# tenían `GET`, así que lo que se daba de alta desaparecía de la vista. La API
# contestaba 405 y el front —que las declara listables— enseñaba una pantalla
# vacía sin decir por qué.

montar_listado(
    router_planes,
    modelo=PlanConjuntoCliente,
    objeto="plan_conjunto",
    permiso="sales:read",
    nombre="Planes conjuntos",
)


ROUTERS_INGRESOS = [router_ingresos, router_planes]
