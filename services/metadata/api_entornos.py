"""API de configuración como código: paquetes, promoción, desvío y vuelta atrás
(CRM-07.02.01.03, .04, .06, .07).

Existía el motor y no existía la puerta: todo esto solo se podía usar desde
código, así que la promesa de que **todo se hace por API** tenía un agujero
justo en la parte que más falta hace automatizar — llevar un cambio de pruebas a
producción.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.errors import NoEncontrado
from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from crmcore.http.listados import declarar_recurso
from crmcore.http.pagination import PaginaDeListado
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from services.metadata import entornos as ent
from services.metadata.entornos import ENTORNOS

router_entornos = APIRouter(prefix="/entornos", tags=["ALM y entornos"])
declarar_recurso(router_entornos, "entorno")


class EmpaquetarIn(BaseModel):
    nombre: str
    contenido: dict[str, Any] = Field(default_factory=dict)
    origen_entorno: str = "desarrollo"
    referencia_git: str = ""
    notas: str = ""


class PromocionIn(BaseModel):
    paquete_id: UUID
    estado_destino: dict[str, Any] = Field(default_factory=dict)


class DesplegarIn(BaseModel):
    paquete_id: UUID


class DriftIn(BaseModel):
    estado_actual: dict[str, Any] = Field(default_factory=dict)


class VolverIn(BaseModel):
    motivo: str


# ── Listado ───────────────────────────────────────────────────────────────
# Se podía desplegar, simular y volver atrás sobre un entorno, y no se podía
# saber cuáles hay. Las acciones cuelgan de `/entornos/{entorno}/...` y a un
# registro se llega por su listado.
#
# No es una tabla: los entornos son una lista cerrada del sistema. Se devuelven
# igual, porque quien integra necesita saber qué nombres admite esa ruta sin
# tener que adivinarlos ni leerse el código.


@router_entornos.get(
    "",
    response_model=PaginaDeListado,
    dependencies=[Depends(exige_permiso("metadata:read"))],
    summary="Entornos por los que pasa la configuración",
    description=(
        "Lista cerrada y en orden de promoción. No se pueden crear otros: un "
        "entorno no es un dato, es una etapa del camino de la configuración "
        "hasta producción."
    ),
)
def listar_entornos() -> Any:
    # `total_aprox` sin pedirlo, y es el único listado que lo hace: en los
    # demás contarlo cuesta un recorrido de la tabla y por eso va detrás de
    # `?contar=true`. Aquí la lista está entera en memoria, así que el número
    # ya se sabe — y esconderlo detrás de un parámetro sería pedir permiso
    # para algo que no cuesta nada.
    entornos = [
        {"nombre": nombre, "orden": i, "es_produccion": nombre == "produccion"}
        for i, nombre in enumerate(ENTORNOS)
    ]
    return {
        "items": entornos,
        "siguiente": None,
        "hay_mas": False,
        "total_aprox": len(entornos),
    }


@router_entornos.get(
    "/{entorno}",
    dependencies=[Depends(exige_permiso("metadata:read"))],
    summary="Un entorno, con lo que se puede preguntar de él",
    description=(
        "Existe porque de un entorno cuelgan cinco acciones —desplegar, "
        "simular, mirar el desvío, volver atrás— y **a un registro que no se "
        "abre no se llega desde ninguna pantalla**. Sin esta ruta, esas cinco "
        "sólo se alcanzaban desde un desplegable escrito a mano.\n\n"
        "Un nombre que no está en la lista responde 404 en vez de un entorno "
        "vacío: «no existe» y «existe y no tiene nada» llevan a sitios "
        "distintos."
    ),
)
def ver_entorno(entorno: str) -> Any:
    if entorno not in ENTORNOS:
        raise NoEncontrado(
            f"«{entorno}» no es un entorno de este sistema",
            error_code="entorno.no_encontrado",
            detalle={"entornos": list(ENTORNOS)},
        )
    i = ENTORNOS.index(entorno)
    return {
        "nombre": entorno,
        "orden": i,
        "es_produccion": entorno == "produccion",
        # El siguiente del camino: es lo que se pregunta al promocionar, y
        # calcularlo en el front obliga a conocer el orden en dos sitios.
        "promociona_a": ENTORNOS[i + 1] if i + 1 < len(ENTORNOS) else None,
        "viene_de": ENTORNOS[i - 1] if i > 0 else None,
    }


@router_entornos.post(
    "/paquetes",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("metadata:write"))],
    summary="Empaquetar un conjunto de cambios de configuración",
    description=(
        "El paquete lleva **de dónde sale y con qué huella**. Un artefacto sin "
        "origen es uno que nadie se atreve a promocionar, y el que no se atreve "
        "lo aplica a mano — que es volver al principio.\n\n"
        "La huella se calcula con las claves ordenadas: si no, el mismo paquete "
        "daría huellas distintas según cómo se serializara y el desvío saltaría "
        "cada día sin que nadie hubiera tocado nada."
    ),
)
def empaquetar(cuerpo: EmpaquetarIn, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = ent.empaquetar(
        uow,
        nombre=cuerpo.nombre,
        contenido=cuerpo.contenido,
        origen_entorno=cuerpo.origen_entorno,
        referencia_git=cuerpo.referencia_git,
        notas=cuerpo.notas,
        por=principal.id,
    )
    return {
        "id": str(fila.id),
        "nombre": fila.nombre,
        "version": fila.version,
        "huella": fila.huella,
    }


@router_entornos.get(
    "/{entorno}/desplegado",
    dependencies=[Depends(exige_permiso("metadata:read"))],
    summary="Qué hay puesto aquí, de qué commit sale y quién lo puso",
    # Por qué se añadió, que no es lo que lee quien abre la pantalla:
    # El paquete guarda la referencia de Git desde el principio y no había
    # forma de leerla: se escribía al empaquetar y ninguna ruta la
    # devolvía, así que «¿de qué versión del repositorio sale lo que hay
    # en producción?» no se podía contestar desde el producto.
    description=(
        "Si el paquete no declara referencia se dice, en vez de dejar el hueco: "
        "hay tenants que configuran desde la consola, y eso no es un fallo — es "
        "que no hay commit al que volver, sólo el paquete anterior."
    ),
)
def desplegado(entorno: str, db: DbDep, principal: AutenticadoDep) -> Any:
    return ent.desplegado(db, principal.tenant_id, entorno=entorno)


@router_entornos.post(
    "/{entorno}/simular",
    dependencies=[Depends(exige_permiso("metadata:read"))],
    summary="Qué pasaría al promocionar, sin aplicar nada",
    description=(
        "Lo que en pruebas era un campo nuevo puede ser en producción un campo "
        "que ya existe con otro tipo. Aplicar y descubrirlo a la mitad deja el "
        "entorno peor que antes.\n\n"
        "Un cambio de **tipo** de campo con datos dentro no se aplica solo: puede "
        "perderlos, y aquí se dice a cuántos registros afectaría."
    ),
)
def simular(entorno: str, cuerpo: PromocionIn, db: DbDep, principal: AutenticadoDep) -> Any:
    return ent.simular_promocion(
        db,
        principal.tenant_id,
        paquete_id=cuerpo.paquete_id,
        entorno=entorno,
        estado_destino=cuerpo.estado_destino,
    )


@router_entornos.post(
    "/{entorno}/desplegar",
    dependencies=[Depends(exige_permiso("metadata:write"))],
    summary="Aplicar un paquete a un entorno",
    description=(
        "Queda registrado qué paquete está aplicado y desde cuándo, que es lo que "
        "permite medir el desvío después — sin saber qué se desplegó, «qué tocó "
        "alguien a mano» no se puede contestar."
    ),
)
def desplegar(entorno: str, cuerpo: DesplegarIn, uow: UowDep, principal: AutenticadoDep) -> Any:
    return ent.desplegar(uow, paquete_id=cuerpo.paquete_id, entorno=entorno, por=principal.id)


@router_entornos.post(
    "/{entorno}/drift",
    dependencies=[Depends(exige_permiso("metadata:read"))],
    summary="Qué se ha tocado fuera del pipeline",
    description=(
        "Se compara contra **el paquete desplegado**, no contra otro entorno. "
        "Comparar dos entornos dice en qué se diferencian —que puede ser "
        "legítimo—; comparar contra lo desplegado dice qué tocó alguien a mano, "
        "que es la pregunta.\n\n"
        "Y **lo que desapareció también es desvío**: un informe que solo enseña lo "
        "que se añadió deja fuera el caso más incómodo."
    ),
)
def drift(entorno: str, cuerpo: DriftIn, db: DbDep, principal: AutenticadoDep) -> Any:
    return ent.medir_drift(
        db, principal.tenant_id, entorno=entorno, estado_actual=cuerpo.estado_actual
    )


@router_entornos.get(
    "/{entorno}/drift",
    dependencies=[Depends(exige_permiso("metadata:read"))],
    summary="El desvío del entorno con el estado que consta",
    description=(
        "La misma comprobación tomando como estado actual el que el propio CRM "
        "tiene guardado. Sirve para mirarlo de un vistazo sin montar la carga; "
        "para comparar contra un estado externo está la versión POST."
    ),
)
def drift_rapido(
    entorno: str,
    db: DbDep,
    principal: AutenticadoDep,
    objeto: str = Query("cuenta", description="De qué objeto se leen los campos para comparar"),
) -> Any:
    """La vista rápida: compara **solo los campos** de un objeto.

    Tres cosas estaban mal:

      · leía `clave` de la definición publicada de cada campo, que trae
        `nombre`. Un `KeyError` — o sea, **un 500** en cuanto el objeto tenía un
        campo. La ruta solo respondía cuando no había nada que comparar, que es
        justo cuando no sirve;
      · el estado se montaba como un diccionario `{clave: {...}}` y la
        comparación espera una **lista** de entradas con su `clave`. Al
        recorrer un diccionario salen cadenas, ninguna es un `dict` y el estado
        actual quedaba vacío: todo lo que traía el paquete aparecía como
        desaparecido. Un entorno recién desplegado y sin tocar salía como
        desviado entero;
      · y se comparaban los ocho tipos de contenido contra un estado que solo
        sabía de campos, así que vistas, pipelines, plantillas y ajustes se
        daban por borrados también.

    Ahora se compara lo que se puede leer y se dice qué queda fuera. Para
    comparar contra un estado externo completo está la versión POST.
    """
    from crmcore.errors import NoEncontrado

    from services.metadata.publicacion import esquema_actual

    try:
        campos = esquema_actual(db, principal.tenant_id, objeto)
    except NoEncontrado:
        # No es un 404 de la ruta: la ruta existe y ha respondido. Lo que no hay
        # es contra qué comparar, y eso es un «no se sabe», no un «no existe».
        return {
            "entorno": entorno,
            "medible": False,
            "porque": (
                f"No hay ningún objeto «{objeto}» en esta implantación, así que no "
                "se puede leer su estado para compararlo. Eso no significa que no "
                "se haya tocado nada — significa que no se sabe."
            ),
        }

    # `clave` y no `nombre`: así es como se llama en un paquete. La versión
    # anterior leía `c["clave"]` de la definición publicada, que trae `nombre`,
    # así que esta ruta era un KeyError —un 500— en cuanto el objeto tenía un
    # solo campo. Solo respondía en el caso en que no había nada que comparar.
    estado = {"campos": [{"clave": c["nombre"], "tipo": c.get("tipo")} for c in campos]}
    return ent.medir_drift(
        db,
        principal.tenant_id,
        entorno=entorno,
        estado_actual=estado,
        tipos=("campos",),
    )


@router_entornos.post(
    "/{entorno}/volver-atras",
    dependencies=[Depends(exige_permiso("metadata:write"))],
    summary="Reaplicar el paquete anterior",
    description=(
        "**Reaplicar y no deshacer.** Deshacer cambio a cambio falla en cuanto hay "
        "dependencias —un campo que se creó y una vista que lo usa— y deja el "
        "entorno en un estado que no ha existido nunca. Volver al paquete anterior "
        "devuelve un estado que sí existió y que además estaba probado.\n\n"
        "Exige motivo: es lo que evita que el siguiente despliegue repita el mismo "
        "fallo."
    ),
)
def volver_atras(entorno: str, cuerpo: VolverIn, uow: UowDep, principal: AutenticadoDep) -> Any:
    return ent.volver_atras(uow, entorno=entorno, motivo=cuerpo.motivo, por=principal.id)


ROUTERS_ENTORNOS = [router_entornos]
