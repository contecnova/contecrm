"""Políticas ABAC: escribirlas, versionarlas y probarlas antes de activarlas.

Se escriben aquí —en `identity`, que es donde vive el control de acceso— y se
replican por evento a todos los servicios, porque la decisión se toma donde
está el dato (`crmcore.authz.politicas`).

La pieza que más importa de este fichero no es el CRUD: es el **simulador**
(CRM-00.05.02.21). Una política de acceso mal escrita no da un error, da un
corte de acceso silencioso a gente que estaba trabajando, y se descubre por los
tickets. Poder preguntar «¿qué vería esta persona con esta política?» **antes**
de activarla es lo que hace que alguien se atreva a escribir una.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.authz.politicas import politica_por_dimension
from crmcore.authz.proyeccion import fijar_politica_campo
from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from crmcore.http.pagination import PaginaDeListado, paginar_consulta
from crmcore.http.reverificacion import dependencia as exige_reverificacion
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

router_politicas = APIRouter(prefix="/politicas-acceso", tags=["roles y permisos"])


class CondicionEntrada(BaseModel):
    atributo: str = Field(
        max_length=120,
        description="Ruta del atributo: `registro.owner_id`, `usuario.territorio`, `contexto.hora`",
    )
    operador: str = Field(max_length=10)
    valor: Any = Field(
        None,
        description="Literal, o `@otro.atributo` para comparar con otro atributo del ámbito",
    )


class PoliticaEntrada(BaseModel):
    nombre: str = Field(max_length=120)
    objeto: str = Field(max_length=60, description="`cuenta`, `oportunidad`… o `*` para todos")
    acciones: list[str] = Field(min_length=1)
    condiciones: list[CondicionEntrada] = Field(default_factory=list)
    combinacion: str = "todas"
    prioridad: int = 100
    alcance: str = Field(
        "registro",
        description=(
            "`registro` esconde el registro entero a quien no cumple; `campos` "
            "esconde solo los campos que nombra y deja ver el registro"
        ),
    )
    campos: list[str] = Field(default_factory=list)
    activa: bool = False
    descripcion: str = Field("", max_length=500)


class SimulacionEntrada(BaseModel):
    usuario_id: UUID
    objeto: str = Field(max_length=60)
    accion: str = Field(max_length=30)
    registro: dict[str, Any] = Field(
        default_factory=dict, description="El registro sobre el que se pregunta"
    )
    politica: PoliticaEntrada | None = Field(
        None,
        description=(
            "Política que todavía NO está guardada, para probarla antes de "
            "crearla. Sin ella se simula con las activas del tenant"
        ),
    )


@router_politicas.get(
    "",
    response_model=PaginaDeListado,
    dependencies=[Depends(exige_permiso("user:read"))],
    summary="Políticas de acceso del tenant",
    description=(
        "Todas, activas y desactivadas. Las desactivadas existen para poder "
        "escribirlas y probarlas con el simulador sin que decidan nada."
    ),
)
def listar_politicas(
    db: DbDep,
    principal: AutenticadoDep,
    limite: int = Query(50, ge=1, le=200),
    cursor: str = Query(""),
) -> Any:
    from crmcore.authz.politicas import PoliticaAbac, a_dict

    consulta = select(PoliticaAbac).where(PoliticaAbac.tenant_id == principal.tenant_id)
    # Por prioridad, que es el orden en que se APLICAN: verlas en otro orden hace
    # difícil entender cuál gana.
    return paginar_consulta(
        db,
        PoliticaAbac,
        consulta,
        limite=limite,
        cursor=cursor,
        orden="prioridad",
        fila_a_dict=a_dict,
    )


class DimensionIn(BaseModel):
    objeto: str = Field(..., min_length=1, examples=["cuenta"])
    acciones: list[str] = Field(default_factory=lambda: ["read", "write"])
    alcance: str = Field(
        "registro", description="registro: esconde la fila · campos: la deja y tapa campos"
    )
    campos: list[str] = Field(default_factory=list)


@router_politicas.post(
    "/dimension/{dimension}",
    dependencies=[Depends(exige_permiso("role:read"))],
    summary="Montar la política de una dimensión, lista para guardar",
    description=(
        "Las cuatro restricciones que piden todos los clientes grandes —unidad "
        "de negocio, marca, país y canal— escritas siempre igual. Montarlas a "
        "mano cada vez es lo que hace que una diga `=` y otra `en`, y que dos "
        "clientes con la misma regla tengan comportamientos distintos.\n\n"
        "**Devuelve la política y no la guarda.** Quién la activa y con qué "
        "alcance —esconder el registro o dejarlo y tapar campos— es una decisión "
        "de negocio, y darla por hecha es cómo se deja a media plantilla sin ver "
        "su propia cartera un lunes por la mañana."
    ),
)
def politica_de_dimension(dimension: str, cuerpo: DimensionIn, principal: AutenticadoDep) -> Any:
    return politica_por_dimension(
        dimension,
        objeto=cuerpo.objeto,
        acciones=cuerpo.acciones,
        alcance=cuerpo.alcance,
        campos=cuerpo.campos,
    )


class PoliticaCampoIn(BaseModel):
    objeto: str = Field(..., min_length=1)
    campo: str = Field(..., min_length=1)
    nivel: str = Field(..., description="claro · enmascarado · oculto")
    rol: str = Field("*", description="`*` para todos los roles")


@router_politicas.post(
    "/campos",
    dependencies=[Depends(exige_permiso("role:write"))],
    summary="Declarar una excepción para un campo concreto",
    description=(
        "La sensibilidad de un campo sale de su clasificación, y eso cubre el "
        "caso normal. Esto es para el que no: «el móvil del contacto lo ve "
        "soporte en claro aunque sea un dato personal», «el margen lo tapamos "
        "también para dirección».\n\n"
        "Se declara **por campo y por rol**, y queda escrito: una excepción que "
        "vive en la cabeza de quien la pidió es la que nadie revisa al año "
        "siguiente."
    ),
)
def politica_de_campo(cuerpo: PoliticaCampoIn, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = fijar_politica_campo(
        uow.db,
        tenant_id=principal.tenant_id,
        objeto=cuerpo.objeto,
        campo=cuerpo.campo,
        nivel=cuerpo.nivel,
        rol=cuerpo.rol,
    )
    return {
        "objeto": fila.objeto,
        "campo": fila.campo,
        "nivel": fila.nivel,
        "rol": fila.rol,
    }


@router_politicas.put(
    "/{nombre}",
    response_model=dict,
    dependencies=[
        Depends(exige_permiso("role:write")),
        # Cambiar quién puede ver qué es la operación con la que se abre
        # cualquier otra puerta: quien llega a una sesión ajena se da permisos y
        # a partir de ahí todo lo que haga es legítimo para el sistema.
        exige_reverificacion("cambio_permisos"),
    ],
    summary="Crear o cambiar una política",
    description=(
        "Sube la versión y guarda una copia de la anterior. La gramática se "
        "valida antes de guardar: una política con un operador que no existe se "
        "evaluaría como denegar, y eso convertiría un error de escritura en un "
        "corte de acceso silencioso el día que alguien la activara."
    ),
)
def guardar_politica(
    nombre: str, datos: PoliticaEntrada, uow: UowDep, principal: AutenticadoDep
) -> Any:
    from crmcore.authz.politicas import a_dict, guardar

    fila = guardar(
        uow.db,
        tenant_id=principal.tenant_id,
        nombre=nombre,
        objeto=datos.objeto,
        acciones=datos.acciones,
        condiciones=[c.model_dump() for c in datos.condiciones],
        combinacion=datos.combinacion,
        prioridad=datos.prioridad,
        alcance=datos.alcance,
        campos=datos.campos,
        activa=datos.activa,
        descripcion=datos.descripcion,
        por=principal.id,
    )
    return a_dict(fila)


@router_politicas.delete(
    "/{nombre}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(exige_permiso("role:write"))],
    summary="Quitar una política",
    description="Su histórico de versiones se queda: es lo que contesta a quién preguntará después.",
)
def borrar_politica(nombre: str, uow: UowDep, principal: AutenticadoDep) -> None:
    from crmcore.authz.politicas import borrar

    borrar(uow.db, tenant_id=principal.tenant_id, nombre=nombre, por=principal.id)


@router_politicas.get(
    "/{nombre}/versiones",
    response_model=list[dict],
    dependencies=[Depends(exige_permiso("user:read"))],
    summary="Historial de una política",
    description=(
        "Qué decía esta política en cada versión y quién la cambió. Sin esto, "
        "«¿por qué no veía yo esto el mes pasado?» no tiene respuesta: la tabla "
        "viva solo enseña el estado de hoy."
    ),
)
def versiones_politica(nombre: str, db: DbDep, principal: AutenticadoDep) -> Any:
    from crmcore.authz.politicas import PoliticaAbac, VersionPoliticaAbac

    politica = db.execute(
        select(PoliticaAbac).where(
            PoliticaAbac.tenant_id == principal.tenant_id, PoliticaAbac.nombre == nombre
        )
    ).scalar_one_or_none()
    consulta = select(VersionPoliticaAbac).where(
        VersionPoliticaAbac.tenant_id == principal.tenant_id
    )
    # Si la política se borró, su histórico sigue ahí pero ya no hay fila viva
    # a la que atarlo: se busca por contenido, que guarda el nombre.
    if politica is not None:
        consulta = consulta.where(VersionPoliticaAbac.politica_id == politica.id)
    else:
        consulta = consulta.where(VersionPoliticaAbac.contenido["nombre"].astext == nombre)
    filas = db.execute(consulta.order_by(VersionPoliticaAbac.version.desc())).scalars().all()
    return [
        {
            "version": f.version,
            "contenido": f.contenido,
            "cambiada_por": str(f.cambiada_por) if f.cambiada_por else None,
            "created_at": f.created_at.isoformat(),
        }
        for f in filas
    ]


@router_politicas.post(
    "/simular",
    response_model=dict,
    dependencies=[Depends(exige_permiso("user:read"))],
    summary="Qué vería esta persona, antes de activar nada",
    description=(
        "Evalúa con los atributos REALES del usuario que se indique, sobre el "
        "registro que se pase, y devuelve la decisión con su porqué.\n\n"
        "Se puede pasar una política que todavía no existe: es la forma de "
        "comprobar qué haría antes de crearla. Una política mal escrita no da "
        "un error, da un corte de acceso silencioso a gente que estaba "
        "trabajando, y se descubre por los tickets."
    ),
)
def simular(datos: SimulacionEntrada, db: DbDep, principal: AutenticadoDep) -> Any:
    from crmcore.authz.abac import Condicion, Politica, evaluar
    from crmcore.authz.politicas import cargar

    from services.identity import servicio as svc
    from services.identity.modelos import Membresia

    membresia = db.execute(
        select(Membresia).where(
            Membresia.usuario_id == datos.usuario_id,
            Membresia.tenant_id == principal.tenant_id,
        )
    ).scalar_one_or_none()
    permisos = svc.permisos_efectivos(db, datos.usuario_id, principal.tenant_id)

    from datetime import datetime, timezone

    ahora = datetime.now(timezone.utc)
    ambito = {
        "usuario": {
            "id": str(datos.usuario_id),
            "roles": list(membresia.roles or []) if membresia else [],
            "business_unit_id": (
                str(membresia.business_unit_id)
                if membresia and membresia.business_unit_id
                else None
            ),
            **(membresia.atributos if membresia else {}),
        },
        "contexto": {
            "tenant_id": str(principal.tenant_id),
            "hora": ahora.hour,
            "dia_semana": ahora.weekday(),
        },
        "registro": datos.registro,
    }

    if datos.politica is not None:
        politicas = [
            Politica(
                nombre=datos.politica.nombre,
                objeto=datos.politica.objeto,
                acciones=frozenset(datos.politica.acciones),
                condiciones=tuple(
                    Condicion(c.atributo, c.operador, c.valor) for c in datos.politica.condiciones
                ),
                combinacion=datos.politica.combinacion,
                prioridad=datos.politica.prioridad,
                # En el simulador se evalúa aunque esté desactivada: probarla es
                # justo lo que se está haciendo.
                activa=True,
                descripcion=datos.politica.descripcion,
            )
        ]
        origen = "política propuesta, sin guardar"
    else:
        politicas = cargar(db, principal.tenant_id)
        origen = f"{len(politicas)} políticas activas del tenant"

    decision = evaluar(politicas, objeto=datos.objeto, accion=datos.accion, ambito=ambito)
    permiso = f"{datos.objeto}:{datos.accion}"
    tiene_rbac = permiso in permisos or f"{datos.objeto}:*" in permisos or "*:*" in permisos
    return {
        # El resultado de verdad es la conjunción: el ABAC restringe, no
        # concede. Devolver solo la parte ABAC haría creer que una política
        # permisiva abre un acceso que el rol no da.
        "permitido": tiene_rbac and decision.permitido,
        "origen": origen,
        "rbac": {"concede": tiene_rbac, "permiso": permiso},
        "abac": {"permitido": decision.permitido, "explicacion": decision.explicacion()},
        "ambito": ambito,
    }


ROUTERS_POLITICAS = [router_politicas]


@router_politicas.get(
    "/publicar",
    response_model=dict,
    dependencies=[Depends(exige_permiso("user:read"))],
    summary="La política del tenant en formato neutro",
    description=(
        "Para cargarla en otro motor de decisión (OPA, Cedar, el del cliente) "
        "sin leer nuestra base (CRM-00.05.02.06). No es Rego ni Cedar a "
        "propósito: traducirla aquí ataría el producto a ese dialecto. La "
        "semántica va dentro del documento, porque quien escriba el traductor "
        "la necesita delante."
    ),
)
def publicar_politica(db: DbDep, principal: AutenticadoDep) -> Any:
    from crmcore.authz.motor_externo import publicar
    from crmcore.authz.politicas import cargar

    return publicar(cargar(db, principal.tenant_id), tenant=str(principal.tenant_id))
