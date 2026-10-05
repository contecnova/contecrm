"""API del servicio de explotación (RT-4).

Lo que expone es lo justo para que una pantalla de contecrm pueda preguntar a
contecintelligence: el token corto, a qué organización corresponde el tenant, y
si la integración está viva. Los informes no pasan por aquí — los pide el
navegador directamente con ese token, que es lo que hace que la explotación sea
frontless de verdad y no un proxy que reimplementa media API ajena.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.db.session import sesion
from crmcore.errors import NoEncontrado
from crmcore.http.deps import AutenticadoDep, DbDep, PlataformaDep, UowDep, exige_permiso
from crmcore.logging import get_logger
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from services.analytics import cliente
from services.analytics.modelos import ConsultaAnalitica, OrganizacionExterna

logger = get_logger(__name__)

from services.analytics import coste_real  # noqa: E402

router = APIRouter(prefix="/analitica", tags=["explotación"])


class OrganizacionOut(BaseModel):
    tenant_id: UUID
    organizacion: str
    estado: str
    ultimo_error: str | None

    model_config = {"from_attributes": True}


class AsignarOrganizacion(BaseModel):
    tenant_id: UUID
    organizacion: str = Field(
        ...,
        max_length=120,
        description=(
            "Identificador de la organización en contecintelligence. Tiene que "
            "estar mapeada allí: solo acepta nombrar las que conoce, y ese es el "
            "control que impide que un token diga pertenecer a un cliente "
            "cualquiera."
        ),
    )


@router.get(
    "/estado",
    response_model=dict,
    summary="Si la explotación está disponible",
    description=(
        "Dice lo último que se sabe de contecintelligence: si responde, cuánto "
        "tardó y qué versión tiene. Con `comprobar=true` vuelve a preguntar.\n\n"
        "Es lo que una pantalla mira antes de ofrecer informes: enseñar el botón "
        "y que falle al pulsarlo es peor que decir de entrada que la explotación "
        "no está disponible."
    ),
)
def estado_integracion(
    _: AutenticadoDep, comprobar: bool = Query(False, description="Volver a preguntar ahora")
) -> Any:
    if comprobar:
        cliente.comprobar()
    return cliente.estado()


@router.post(
    "/token",
    response_model=dict,
    summary="Token de usuario final para consultar",
    description=(
        "Canja **en el servidor** la credencial de aplicación por un token corto "
        "que nombra esta organización, esta persona y unos alcances. La "
        "credencial nunca baja al navegador: puede representar a todos los "
        "tenants, así que ahí sería la llave de todos.\n\n"
        "El rol que se manda sale de los permisos que la persona tiene **aquí**, "
        "y se traduce a la baja: una explotación que ve más que la aplicación es "
        "una fuga con otro nombre."
    ),
    dependencies=[Depends(exige_permiso("analitica:consultar"))],
)
def token(db: DbDep, principal: AutenticadoDep) -> Any:
    organizacion = _organizacion_de(db, principal.tenant_id)
    emitido = cliente.canjear_token(
        organizacion=organizacion.organizacion,
        sujeto=str(principal.id),
        rol=cliente.rol_para(principal.permisos, principal.es_admin_plataforma),
    )
    logger.info(
        "analytics.token_emitido",
        tenant=str(principal.tenant_id),
        organizacion=organizacion.organizacion,
        rol=emitido.alcances,
    )
    return emitido.a_dict()


def _organizacion_de(db: Any, tenant_id: UUID) -> OrganizacionExterna:
    fila = db.execute(
        select(OrganizacionExterna).where(OrganizacionExterna.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado(
            "Este tenant no tiene organización asignada en contecintelligence. Se "
            "asigna al provisionarlo; si es un tenant antiguo, hay que asignarla a mano.",
            error_code="analytics.sin_organizacion",
        )
    return fila


@router.get(
    "/organizaciones",
    response_model=list[OrganizacionOut],
    summary="Correspondencia entre tenants y organizaciones",
)
def listar_organizaciones(_: PlataformaDep) -> Any:
    # Sesión de SISTEMA, no la del tenant que pregunta. La correspondencia es
    # una tabla de plataforma: cada fila es de OTRO tenant, y con la sesión
    # normal la RLS solo dejaba ver la del propio —una tabla de tres tenants
    # devolvía una fila, sin error y sin decir que faltaban dos.
    with sesion(sistema=True) as db:
        return [
            OrganizacionOut.model_validate(fila)
            for fila in db.execute(
                select(OrganizacionExterna).order_by(OrganizacionExterna.created_at)
            )
            .scalars()
            .all()
        ]


@router.put(
    "/organizaciones",
    response_model=OrganizacionOut,
    status_code=status.HTTP_200_OK,
    summary="Asignar la organización de un tenant",
    description=(
        "Operación de plataforma: un tenant no decide con qué organización de "
        "contecintelligence se corresponde, porque entonces podría nombrar la de "
        "otro."
    ),
)
def asignar_organizacion(datos: AsignarOrganizacion, _: PlataformaDep) -> Any:
    # Por lo mismo que el listado, y aquí no era «incompleto» sino IMPOSIBLE:
    # escribir la fila de otro tenant desde la sesión del propio viola la
    # política de RLS, y Postgres contesta `new row violates row-level security
    # policy`. Salía como 500 genérico, así que desde fuera parecía una avería
    # del servicio en vez de lo que era: esta ruta nunca había funcionado para
    # ningún tenant que no fuera el de quien llamaba.
    with sesion(sistema=True) as db:
        return _asignar(db, datos)


def _asignar(db: Any, datos: AsignarOrganizacion) -> Any:
    fila = db.execute(
        select(OrganizacionExterna).where(OrganizacionExterna.tenant_id == datos.tenant_id)
    ).scalar_one_or_none()
    if fila is None:
        fila = OrganizacionExterna(
            tenant_id=datos.tenant_id, organizacion=datos.organizacion, estado="pendiente"
        )
        db.add(fila)
    elif fila.organizacion != datos.organizacion:
        # Cambiar la organización de un tenant que ya consultaba deja sus
        # preguntas guardadas apuntando a datos de otra parte. Se permite —hace
        # falta al migrar— pero no en silencio.
        logger.warning(
            "analytics.organizacion_cambiada",
            tenant=str(datos.tenant_id),
            antes=fila.organizacion,
            ahora=datos.organizacion,
        )
        fila.organizacion = datos.organizacion
        fila.estado = "pendiente"
    db.flush()
    # Se serializa DENTRO de la sesión: fuera, el `commit` ya ha expirado los
    # atributos y leerlos dispararía un refresco sobre una sesión cerrada.
    return OrganizacionOut.model_validate(fila)


class RegistrarConsulta(BaseModel):
    pregunta: str = Field(..., max_length=2_000)
    fuente: str | None = None
    filas_devueltas: int = Field(0, ge=0)
    duracion_ms: int = Field(0, ge=0)
    error: str | None = None
    contexto: dict[str, Any] = Field(default_factory=dict)


@router.post(
    "/consultas",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
    summary="Anotar una consulta analítica",
    description=(
        "La explotación es la vía por la que más dato sale de un CRM de una sola "
        "vez. Sin este registro, «¿quién sacó la lista de clientes antes de "
        "irse?» no tiene respuesta — y esa es la pregunta que se hace después.\n\n"
        "Se guarda la pregunta y el **recuento** de lo devuelto, no las filas: "
        "copiarlas aquí duplicaría el dato personal y multiplicaría la superficie "
        "que hay que proteger."
    ),
    dependencies=[Depends(exige_permiso("analitica:consultar"))],
)
def anotar_consulta(datos: RegistrarConsulta, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = ConsultaAnalitica(
        tenant_id=principal.tenant_id,
        usuario_id=principal.id,
        **datos.model_dump(),
    )
    uow.db.add(fila)
    uow.db.flush()
    return {"id": str(fila.id)}


@router.get(
    "/consultas",
    response_model=list[dict],
    summary="Qué se ha preguntado",
    dependencies=[Depends(exige_permiso("analitica:auditar"))],
)
def listar_consultas(
    db: DbDep, principal: AutenticadoDep, limite: int = Query(100, ge=1, le=1000)
) -> Any:
    filas = (
        db.execute(
            select(ConsultaAnalitica)
            .where(ConsultaAnalitica.tenant_id == principal.tenant_id)
            .order_by(ConsultaAnalitica.created_at.desc())
            .limit(limite)
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(f.id),
            "usuario_id": str(f.usuario_id) if f.usuario_id else None,
            "pregunta": f.pregunta,
            "fuente": f.fuente,
            "filas_devueltas": f.filas_devueltas,
            "duracion_ms": f.duracion_ms,
            "error": f.error,
            "cuando": f.created_at.isoformat() if f.created_at else None,
        }
        for f in filas
    ]


ROUTERS = [router]


@router.get(
    "/modelo-semantico",
    summary="Qué puede explotar contecintelligence de este tenant",
    description=(
        "Los campos que un cliente añade en su implantación no están en ningún "
        "esquema que contecintelligence pueda leer. Esto los publica —con su "
        "tipo, su papel analítico y la vista SQL donde ya están proyectados como "
        "columnas tipadas— para que aparezcan como dimensión o métrica **sin que "
        "nadie modele nada aparte** (CRM-00.04.03.06).\n\n"
        "Va el modelo, **nunca el dato**: mandar valores aquí convertiría una "
        "descripción de esquema en una copia del CRM fuera de su sitio.\n\n"
        "Los campos personales y de categoría especial se dejan fuera **y se "
        "dice cuáles**: acabarían en un cuadro de mando que alguien comparte, y "
        "el enmascaramiento por rol de la API no llega hasta ahí."
    ),
)
def modelo_semantico(
    db: DbDep,
    principal: AutenticadoDep,
    objeto: list[str] = Query(default=[], description="Vacío = todos"),
) -> Any:
    from services.analytics import modelo_semantico as sem

    return sem.modelo_de(db, principal.tenant_id, list(objeto) or None)


# ── Coste real frente a ofertado (CRM-09.02.01.10) ────────────────────────
#
# El margen de una oferta es una previsión; el de verdad se sabe cuando llega la
# factura del proveedor, y casi nadie vuelve a mirarlo. Por eso las empresas
# descubren que un tipo de trabajo pierde dinero **después de haberlo vendido
# veinte veces**.
#
# El módulo que lo compara estaba escrito, probado y no lo importaba nadie.


class PedidosIn(BaseModel):
    pedidos: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Cada uno con lo ofertado y lo facturado. Lo que decide es el par, "
            "no el importe: un pedido sin factura todavía no se puede comparar"
        ),
    )


@router.post(
    "/coste-real/desviacion",
    dependencies=[Depends(exige_permiso("analitica:read"))],
    summary="Qué se ofertó y qué costó de verdad",
    description=(
        "El margen de una oferta es una previsión. El de verdad se sabe cuando "
        "llega la factura, y es el que dice si ese tipo de trabajo gana dinero. "
        "Sin esta comparación se descubre después de haberlo vendido veinte "
        "veces.\n\n"
        "Lo que **todavía no se puede comparar** se dice aparte: un pedido sin "
        "factura no es un pedido con desviación cero, y meterlo en la media la "
        "aplana justo donde hace falta que se note."
    ),
)
def desviacion_de_coste(cuerpo: PedidosIn, principal: AutenticadoDep) -> Any:
    return coste_real.desviacion(pedidos=cuerpo.pedidos)


@router.post(
    "/coste-real/por-proveedor",
    dependencies=[Depends(exige_permiso("analitica:read"))],
    summary="Quién se desvía y cuánto, por proveedor",
    description=(
        "Es la lectura que cambia a quién se le pide la próxima oferta. Un "
        "proveedor que siempre factura un 20 % por encima de lo que ofertó no es "
        "más caro: es que su oferta no vale, y eso solo se ve acumulando."
    ),
)
def coste_por_proveedor(cuerpo: PedidosIn, principal: AutenticadoDep) -> Any:
    return coste_real.por_proveedor(pedidos=cuerpo.pedidos)
