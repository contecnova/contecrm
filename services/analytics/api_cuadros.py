"""API de componentes, filtros, alertas y embebido (CRM-05.01.02)."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from crmcore.http.listados import montar_listado
from fastapi import APIRouter, Depends, Header, status
from pydantic import BaseModel, Field

from services.analytics import cuadros as cua
from services.analytics.cuadros import EnlaceEmbebido

router = APIRouter(prefix="/cuadros-mando", tags=["informes"])


@router.get(
    "/componentes",
    dependencies=[Depends(exige_permiso("informe:read"))],
    summary="Los tipos de componente que existen, con lo que necesita cada uno",
    description=(
        "Se publica para que la pantalla de montaje ofrezca lo que existe en vez "
        "de una lista escrita a mano en el front: dos listas que tienen que "
        "coincidir acaban no coincidiendo, y la que se queda corta es siempre la "
        "del front."
    ),
)
def componentes() -> Any:
    return cua.catalogo_componentes()


class FiltrosGlobales(BaseModel):
    componentes: list[dict[str, Any]]
    filtros: list[dict[str, Any]] = Field(default_factory=list)


@router.post(
    "/aplicar-filtros",
    dependencies=[Depends(exige_permiso("informe:read"))],
    summary="Pasar los filtros del cuadro a sus componentes",
    description=(
        "El filtro es **del cuadro**, no de cada componente: si cada uno llevara "
        "el suyo, cambiar el trimestre exigiría tocar ocho sitios y siempre "
        "quedaría uno sin cambiar — y nadie se daría cuenta, porque un número "
        "plausible no se cuestiona.\n\n"
        "Un componente puede declararse inmune (`ignora_filtros`) para los que "
        "enseñan contexto, como «total del año pasado». Se declara, no se adivina."
    ),
)
def aplicar_filtros(datos: FiltrosGlobales) -> Any:
    return {"componentes": cua.aplicar_filtros_globales(datos.componentes, datos.filtros)}


class Detalle(BaseModel):
    componente: dict[str, Any]
    punto: dict[str, Any] = Field(
        default_factory=dict, description="Los valores del punto pulsado: la barra, el sector"
    )
    filtros: list[dict[str, Any]] = Field(default_factory=list)


@router.post(
    "/detalle",
    dependencies=[Depends(exige_permiso("informe:read"))],
    summary="A qué lista lleva pulsar un punto",
    description=(
        "Baja **hasta el registro**, no hasta otra agregación. Un cuadro del que "
        "no se puede bajar al detalle obliga a rehacer la consulta a mano en otra "
        "pantalla, y ahí ya no coinciden los números — y entonces se deja de creer "
        "al cuadro.\n\n"
        "Lleva los filtros del cuadro **y el del punto**: sin lo segundo, pulsar "
        "en la barra de marzo llevaría a la lista del año entero."
    ),
)
def detalle(datos: Detalle) -> Any:
    return cua.enlace_al_detalle(datos.componente, datos.punto, datos.filtros)


class CrearAlerta(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=200)
    informe_id: UUID
    metrica: str = Field("filas", description="Una métrica del informe, o «filas»")
    comparacion: str = Field(
        "mayor", description="mayor · mayor_igual · menor · menor_igual · igual · cambia_mas_de"
    )
    umbral: Decimal = Decimal(0)
    histeresis: Decimal = Field(
        Decimal(0),
        description=(
            "Margen para volver al verde. Sin él, un indicador que baila alrededor "
            "del umbral manda cuarenta avisos en una tarde y al día siguiente la "
            "regla está desactivada"
        ),
    )
    silencio_horas: int = Field(12, ge=1, le=720)
    destinatarios: list[str] = Field(..., min_length=1)


@router.post(
    "/alertas",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("informe:write"))],
    summary="Avisar cuando una métrica cruza una línea",
)
def crear_alerta(datos: CrearAlerta, uow: UowDep) -> Any:
    fila = cua.crear_alerta(uow, **datos.model_dump())
    return {"id": str(fila.id), "nombre": fila.nombre, "estado": fila.estado}


@router.post(
    "/alertas/comprobar",
    dependencies=[Depends(exige_permiso("informe:write"))],
    summary="Ejecutar las alertas activas",
    description=(
        "Lo que no se ha podido medir sale aparte (`no_medibles`) y **no cuenta "
        "como verde**: dar por bueno lo que no se ha medido es la forma más "
        "silenciosa de perder una alerta."
    ),
)
def comprobar_alertas(uow: UowDep, principal: AutenticadoDep) -> Any:
    return cua.comprobar_alertas(uow, principal.tenant_id)


class CrearEmbebido(BaseModel):
    cuadro_id: UUID
    dominios: list[str] = Field(
        ...,
        min_length=1,
        description=(
            "Desde dónde se puede incrustar. Vacío NO significa «desde cualquier "
            "sitio»: significa que no se sirve, porque un cuadro embebible desde "
            "cualquier parte es un cuadro público"
        ),
        examples=[["intranet.cliente.com"]],
    )
    nombre: str = ""
    minutos_validez: int = Field(10, ge=1, le=1440)
    modo_alcance: str = Field(
        "enlace",
        description=(
            "Con qué alcance se calcula lo que el cuadro enseña. «enlace»: con el "
            "de quien lo crea, igual para todo el que lo abra y nunca más de lo "
            "que ve quien lo montó. «quien_mira»: con el de la persona que la "
            "aplicación anfitriona diga que está delante, y entonces hace falta "
            "que lo diga"
        ),
        examples=["enlace"],
    )


@router.post(
    "/embebidos",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("informe:write"))],
    summary="Habilitar un cuadro para incrustarlo fuera",
    description=(
        "El secreto se devuelve **una sola vez**; en la base queda su hash.\n\n"
        "El enlace **actúa como una persona concreta** —quien lo crea— y lo que "
        "el cuadro enseña **se calcula con el alcance de esa persona**, no con el "
        "de quien tiene el navegador abierto. Eso es lo que impide que un cuadro "
        "incrustado enseñe más de lo que ve quien lo montó.\n\n"
        'Con `modo_alcance="quien_mira"` se calcula en cambio con el de la '
        "persona que la aplicación anfitriona diga que está delante, y entonces "
        "nadie ve nada que no vería entrando él. Hace falta que lo diga: sin "
        "sujeto, ese enlace no se sirve."
    ),
)
def crear_embebido(datos: CrearEmbebido, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila, secreto = cua.crear_embebido(
        uow,
        cuadro_id=datos.cuadro_id,
        actua_como_id=principal.id,
        dominios=datos.dominios,
        nombre=datos.nombre,
        minutos_validez=datos.minutos_validez,
        modo_alcance=datos.modo_alcance,
    )
    return {
        "id": str(fila.id),
        "secreto": secreto,
        "actua_como": str(fila.actua_como_id),
        "dominios": list(fila.dominios),
        "modo_alcance": fila.modo_alcance,
    }


@router.post(
    "/embebidos/{enlace_id}/revocar",
    dependencies=[Depends(exige_permiso("informe:write"))],
    summary="Revocar un enlace embebido",
    description="No se borra: su uso queda en el histórico, que es lo que permite auditarlo.",
)
def revocar(enlace_id: UUID, uow: UowDep) -> Any:
    return cua.revocar_embebido(uow, enlace_id)


class Suscribirse(BaseModel):
    cuadro_id: UUID
    periodicidad: str = Field("semanal", description="diaria · semanal · mensual")
    hora: int = Field(8, ge=0, le=23)


@router.post(
    "/suscripciones",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("informe:read"))],
    summary="Que el cuadro llegue solo",
    description=(
        "Uno se suscribe **a sí mismo**. Suscribir a otro convierte un cuadro en "
        "correo no deseado que el receptor no sabe cómo parar, y lo que hace es "
        "marcarlo como basura — y con él, todo lo que mande el CRM."
    ),
)
def suscribirse(datos: Suscribirse, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = cua.suscribirse(
        uow,
        cuadro_id=datos.cuadro_id,
        usuario_id=principal.id,
        periodicidad=datos.periodicidad,
        hora=datos.hora,
    )
    return {
        "id": str(fila.id),
        "proxima_at": fila.proxima_at.isoformat() if fila.proxima_at else None,
    }


# ── Incrustar fuera: dos puertas, y ninguna pide sesión del CRM ───────────
#
# Antes había una sola ruta y exigía sesión **del CRM**, así que un cuadro no se
# podía incrustar en la aplicación de un cliente sin repartirles credenciales de
# empleado. Y lo que devolvía era el identificador del cuadro: los datos los
# pedía después quien miraba, con sus propios permisos, de modo que el
# `actua_como` del enlace no acotaba nada.
#
# Ahora el secreto se queda en el servidor del anfitrión y lo que llega al
# navegador es un ticket corto que solo vale para este cuadro.


class AbrirEmbebido(BaseModel):
    secreto: str = Field(..., min_length=1)
    sujeto: str = Field(
        "",
        description=(
            "El correo de quien está mirando, según el SSO de la aplicación "
            "anfitriona. Se comprueba contra las membresías de verdad: lo que el "
            "anfitrión afirma es QUIÉN mira, no qué puede ver"
        ),
        examples=["ana@cliente.com"],
    )


@router.post(
    "/embebidos/abrir",
    summary="Cambiar el secreto del enlace por un ticket corto",
    description=(
        "**La llama el servidor de la aplicación anfitriona, no el navegador.** "
        "Si el secreto llegara al navegador, cualquiera que abriese las "
        "herramientas del desarrollador se llevaría una credencial de larga vida "
        "a ese cuadro.\n\n"
        "No hace falta sesión del CRM: lo que autentica es el secreto del enlace, "
        "y exigir además un permiso sería circular — es la credencial que se "
        "entregó justo para esto. El ticket que devuelve **no lleva permisos**, "
        "así que no sirve para ninguna otra ruta del CRM.\n\n"
        "Un secreto inexistente, desactivado o de otro dominio dan **el mismo "
        "error**: distinguirlos le diría a quien prueba si ese cuadro existe y "
        "desde dónde se sirve. La comprobación del dominio es por coincidencia "
        "exacta o de subdominio, nunca «contiene»: con «contiene», "
        "`micrm.com.ataque.net` pasaría por `micrm.com`."
    ),
)
def abrir_embebido(datos: AbrirEmbebido, origin: str = Header("", alias="Origin")) -> Any:
    # Sesión de SISTEMA, y hay que escribirlo: el enlace se busca por el hash de
    # su secreto sin saber todavía de qué organización es —averiguarlo es lo que
    # se está pidiendo—, así que con una sesión de tenant la RLS no lo
    # encontraría nunca. Es la misma forma que tienen el inicio de sesión y la
    # validación de una clave de API, por la misma razón.
    from crmcore.db.session import sesion

    with sesion(sistema=True) as db:
        return cua.abrir_embebido(db, secreto=datos.secreto, origen=origin, sujeto=datos.sujeto)


def _ticket(authorization: str = Header("", alias="Authorization")) -> dict[str, Any]:
    """El ticket del embebido, validado.

    Viaja en `Authorization: Bearer`, como cualquier otra credencial del
    producto: así el tenant lo fija el mecanismo de siempre y estas rutas no
    montan uno paralelo. Lo que lo distingue de un token de empleado es el campo
    `tipo`, y `leer_ticket` lo exige.
    """
    from crmcore.errors import NoAutenticado

    if not authorization.lower().startswith("bearer "):
        raise NoAutenticado(
            "Hace falta el ticket del cuadro incrustado",
            error_code="cuadro.embebido_sin_ticket",
        )
    return cua.leer_ticket(authorization[7:])


TicketDep = Annotated[dict, Depends(_ticket)]


@router.get(
    "/embebido",
    summary="Qué pinta el cuadro incrustado",
    description=(
        "Devuelve los componentes, **sin sus datos**. Los datos van aparte, uno a "
        "uno: un cuadro de ocho componentes servido entero tardaría lo que el más "
        "lento, y lo que se vería mientras tanto es una página en blanco."
    ),
)
def embebido(db: DbDep, ticket: TicketDep) -> Any:
    return cua.cuadro_del_embebido(db, ticket)


class DatosEmbebido(BaseModel):
    indice: int = Field(0, ge=0, description="Qué componente del cuadro se pide")
    filtros: list[dict[str, Any]] = Field(default_factory=list)


@router.post(
    "/embebido/datos",
    summary="Los datos de un componente del cuadro incrustado",
    description=(
        "**Se ejecuta con el alcance del ticket**, que es el del enlace o el de "
        "quien mira según se declarase el enlace — nunca el de quien tiene el "
        "navegador abierto, que aquí ni siquiera necesita cuenta.\n\n"
        "Es un POST porque lleva filtros en el cuerpo, y no exige permiso porque "
        "el ticket ya es la autorización: lo emitió esta misma API a cambio del "
        "secreto del enlace, y no lleva permisos para no servir en ningún otro "
        "sitio.\n\n"
        "Queda marcado como `embebido` en el histórico de ejecuciones: sin eso, "
        "el consumo de un panel colgado en una intranet se mezcla con el de la "
        "gente trabajando, y es el primer sitio donde mirar cuando el motor "
        "analítico se queda corto."
    ),
)
def datos_embebido(datos: DatosEmbebido, uow: UowDep, ticket: TicketDep) -> Any:
    return cua.datos_del_embebido(uow, ticket, indice=datos.indice, filtros=datos.filtros)


# ── Listados de las sub-colecciones ───────────────────────────────────────
# Mismo agujero que en las colecciones raíz: se podían crear y no se podían
# leer. Un sobre de firma, una tabla del almacén o una predicción que no se
# pueden listar no existen para quien tiene que revisarlos.

montar_listado(
    router,
    modelo=EnlaceEmbebido,
    objeto="enlace_embebido",
    permiso="informe:read",
    ruta="/embebidos",
    nombre="Enlaces embebidos",
)


ROUTERS_CUADROS = [router]
