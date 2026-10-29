"""API del ciclo de vida de un tenant: clonar, escindir, fusionar y perfilar
(CRM-07.02.01.03, CRM-07.02.01.07).

Medido el 05-10-2026: siete decisiones de `ciclo_vida` estaban escritas,
probadas y **sin que las alcanzara ninguna ruta**. Son las operaciones más caras
de deshacer que tiene el producto —una fusión mal hecha mezcla los datos de dos
clientes— y la parte que las hace seguras, la **simulación**, no se podía pedir.

La decisión de fondo: **primero se simula y después se ejecuta**, y las dos son
llamadas distintas. Una operación que simula y ejecuta en el mismo paso no es
una simulación: es una ejecución con un informe.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.errors import NoEncontrado
from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from crmcore.http.listados import montar_listado
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from services.tenancy import ciclo_vida as cv
from services.tenancy.ciclo_vida import OperacionTenant, PerfilIndustria

router_ciclo = APIRouter(prefix="/ciclo-vida", tags=["ciclo de vida del tenant"])


class ClonadoIn(BaseModel):
    origen_id: UUID
    uso: str = Field(..., examples=["formacion"])
    bloques: list[str] = Field(default_factory=list)
    recuentos: dict[str, int] | None = None
    # **Por defecto se anonimiza.** Lo contrario sería una casilla marcada que
    # nadie mira, y a un entorno que no es producción entran el consultor
    # externo, el becario y el proveedor que está integrando algo: allí no hay
    # ni el mismo cifrado ni el mismo control de acceso.
    anonimizar: bool = True
    motivo_sin_anonimizar: str = ""
    # Se recomienda copia parcial, y no por espacio: con el 5 % de los clientes
    # se prueba igual de bien y hay veinte veces menos que proteger.
    porcentaje: int = Field(100, ge=1, le=100)


@router_ciclo.post(
    "/clonado/simular",
    dependencies=[Depends(exige_permiso("tenant:write"))],
    summary="Qué se copiaría y qué no, antes de copiar nada",
    description=(
        "Clonar un tenant es sacar los datos de un cliente de donde están "
        "protegidos. La simulación dice **qué bloques saldrían y cuántas filas**, "
        "que es lo que permite decidir antes y no después."
    ),
)
def simular_clonado(cuerpo: ClonadoIn, uow: UowDep, principal: AutenticadoDep) -> Any:
    return cv.simular_clonado(
        uow,
        origen_id=cuerpo.origen_id,
        uso=cuerpo.uso,
        bloques=cuerpo.bloques,
        anonimizar=cuerpo.anonimizar,
        motivo_sin_anonimizar=cuerpo.motivo_sin_anonimizar,
        porcentaje=cuerpo.porcentaje,
        pedido_por=principal.id,
        recuentos=cuerpo.recuentos,
    )


class EjecutarClonadoIn(BaseModel):
    operacion_id: UUID = Field(
        ...,
        description=(
            "La simulación que se ejecuta. Se exige para que ejecutar sea siempre "
            "el segundo paso: una operación que simula y ejecuta a la vez no es "
            "una simulación, es una ejecución con informe"
        ),
    )
    destino_id: UUID
    copiado: dict[str, int] = Field(default_factory=dict)


@router_ciclo.post(
    "/clonado/ejecutar",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("tenant:write"))],
    summary="Ejecutar el clonado que se simuló",
)
def ejecutar_clonado(cuerpo: EjecutarClonadoIn, uow: UowDep, principal: AutenticadoDep) -> Any:
    return cv.ejecutar_clonado(
        uow,
        operacion_id=cuerpo.operacion_id,
        destino_id=cuerpo.destino_id,
        copiado=cuerpo.copiado,
    )


class EscisionIn(BaseModel):
    origen_id: UUID
    reparto: dict[str, str] = Field(
        default_factory=dict,
        description="Qué se va a cada lado. Lo que no se reparta se queda, y se dice",
    )
    inventario: list[str] = Field(default_factory=list)


@router_ciclo.post(
    "/escision/simular",
    dependencies=[Depends(exige_permiso("tenant:write"))],
    summary="Qué pasa si esta empresa se parte en dos",
    description=(
        "Lo que no se reparte **no desaparece**: se queda donde está y se dice "
        "cuál es. Una escisión que no lista lo no repartido deja datos en el lado "
        "equivocado y nadie lo descubre hasta que alguien los busca."
    ),
)
def simular_escision(cuerpo: EscisionIn, uow: UowDep, principal: AutenticadoDep) -> Any:
    return cv.simular_escision(
        uow,
        origen_id=cuerpo.origen_id,
        reparto=cuerpo.reparto,
        inventario=cuerpo.inventario,
    )


class FusionIn(BaseModel):
    absorbido_id: UUID
    superviviente_id: UUID
    choques: dict[str, list[str]] | None = None


@router_ciclo.post(
    "/fusion/simular",
    dependencies=[Depends(exige_permiso("tenant:write"))],
    summary="Qué choca si estas dos empresas se juntan",
    description=(
        "**Los choques se enseñan, no se resuelven solos.** Dos tenants con la "
        "misma clave de producto o el mismo código de territorio no son un "
        "detalle: resolverlo automáticamente por antigüedad o por orden alfabético "
        "deja al cliente con la configuración del otro sin saberlo."
    ),
)
def simular_fusion(cuerpo: FusionIn, uow: UowDep, principal: AutenticadoDep) -> Any:
    return cv.simular_fusion(
        uow,
        absorbido_id=cuerpo.absorbido_id,
        superviviente_id=cuerpo.superviviente_id,
        choques=cuerpo.choques,
    )


class PerfilIn(BaseModel):
    clave: str = Field(..., min_length=1, examples=["industrial"])
    nombre: str = ""
    descripcion: str = ""
    contenido: dict[str, Any] = Field(default_factory=dict)
    no_incluye: list[str] = Field(
        default_factory=list,
        description=(
            "Lo que este perfil NO trae. Se declara porque un perfil que no dice "
            "lo que le falta se vende como completo, y el hueco se descubre en la "
            "primera semana de uso"
        ),
    )


@router_ciclo.post(
    "/perfiles",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("tenant:write"))],
    summary="Declarar un perfil de industria",
)
def guardar_perfil(cuerpo: PerfilIn, db: DbDep, principal: AutenticadoDep) -> Any:
    fila = cv.guardar_perfil(
        db,
        clave=cuerpo.clave,
        nombre=cuerpo.nombre or cuerpo.clave,
        contenido=cuerpo.contenido,
        descripcion=cuerpo.descripcion,
        no_incluye=cuerpo.no_incluye,
    )
    return {"clave": fila.clave, "nombre": fila.nombre}


@router_ciclo.get(
    "/perfiles/{clave}/simular",
    dependencies=[Depends(exige_permiso("tenant:read"))],
    summary="Qué dejaría este perfil en el tenant, sin aplicarlo",
)
def simular_perfil(clave: str, db: DbDep, principal: AutenticadoDep) -> Any:
    return cv.simular_perfil(db, principal.tenant_id, clave=clave)


class AplicarPerfilIn(BaseModel):
    clave: str
    existentes: dict[str, list[str]] | None = Field(
        None,
        description=(
            "Lo que el tenant ya tiene, para no pisarlo. Aplicar un perfil encima "
            "de una configuración hecha a mano es cómo se pierde el trabajo de una "
            "implantación"
        ),
    )


@router_ciclo.post(
    "/perfiles/aplicar",
    dependencies=[Depends(exige_permiso("tenant:write"))],
    summary="Aplicar el perfil, respetando lo que ya hay",
)
def aplicar_perfil(cuerpo: AplicarPerfilIn, uow: UowDep, principal: AutenticadoDep) -> Any:
    return cv.aplicar_perfil(
        uow,
        tenant_id=uow.tenant_id,
        clave=cuerpo.clave,
        existentes=cuerpo.existentes,
    )


@router_ciclo.get(
    "/perfiles",
    response_model=list[dict],
    dependencies=[Depends(exige_permiso("tenant:read"))],
    summary="Los perfiles de industria declarados",
    description=(
        "Listado **de la instalación, no del tenant**: un perfil de industria es "
        "una preconfiguración de quien opera la plataforma y la misma sirve para "
        "todos los clientes. Por eso no lleva `tenant_id` y no se monta con el "
        "listado genérico, que acota por tenant — hacerlo devolvería siempre "
        "vacío.\n\n"
        "Sin este listado se podían declarar y no ver: hay que saberse las claves "
        "de memoria, y entonces se declara el mismo perfil dos veces con nombres "
        "distintos."
    ),
)
def listar_perfiles(db: DbDep, principal: AutenticadoDep) -> Any:
    from sqlalchemy import select

    filas = db.execute(select(PerfilIndustria).order_by(PerfilIndustria.clave)).scalars().all()
    return [
        {
            "clave": f.clave,
            "nombre": f.nombre,
            "descripcion": f.descripcion,
            # Lo que NO trae, al lado de lo que trae: un perfil que no dice lo
            # que le falta se vende como completo.
            "no_incluye": list(f.no_incluye or []),
        }
        for f in filas
    ]


@router_ciclo.get(
    "/perfiles/{clave}",
    dependencies=[Depends(exige_permiso("tenant:read"))],
    summary="Un perfil de industria",
    description=(
        "Existe porque de un perfil cuelga **simular qué dejaría puesto**, y a "
        "un registro que no se abre no se llega desde ninguna pantalla. Sin "
        "esto, esa simulación sólo se alcanzaba sabiéndose la clave de memoria."
        "\n\n"
        "Lleva lo que el perfil **no** incluye, igual que el listado: un perfil "
        "que no dice lo que le falta se vende como completo."
    ),
)
def ver_perfil(clave: str, db: DbDep, principal: AutenticadoDep) -> Any:
    from sqlalchemy import select

    fila = (
        db.execute(select(PerfilIndustria).where(PerfilIndustria.clave == clave)).scalars().first()
    )
    if fila is None:
        raise NoEncontrado(
            f"No hay ningún perfil de industria «{clave}»",
            error_code="ciclo_vida.perfil_no_encontrado",
        )
    return {
        "clave": fila.clave,
        "nombre": fila.nombre,
        "descripcion": fila.descripcion,
        "no_incluye": list(fila.no_incluye or []),
        "contenido": dict(fila.contenido or {}),
    }


# ── Listados ──────────────────────────────────────────────────────────────
#
# Un clonado, una fusión y una escisión guardan su PLAN y sus CONFLICTOS —y el
# modelo dice por qué: «es lo que alguien tiene que leer ANTES de aprobar»—, y
# no había ninguna ruta que los listara. Se leían por identificador y nada más,
# así que sólo podía volver a ellos quien se hubiera guardado el id de la
# respuesta.
#
# Son las operaciones más peligrosas del producto: mover los datos de un cliente
# a otro tenant, juntar dos, partir uno. Que no se puedan recorrer significa que
# nadie puede contestar «¿qué se ha hecho sobre este cliente?».
montar_listado(
    router_ciclo,
    modelo=OperacionTenant,
    objeto="operacion_tenant",
    permiso="tenant:read",
    permiso_escribir="tenant:write",
    ruta="/operaciones",
    nombre="Clonados, fusiones y escisiones",
)

ROUTERS_CICLO_VIDA = [router_ciclo]
