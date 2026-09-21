"""Las pantallas de los vocabularios de negocio (CRM-07.01.01.03).

Se monta sola en `crear_servicio`, como la papelera y por el mismo motivo: si
dependiera de que cada servicio se acuerde, faltaría justo en el que guarde el
vocabulario que alguien necesite cambiar.

Solo aparece en la superficie si el servicio declara alguno, así que en los que
no usan vocabularios no añade ni una ruta.

Cuelga de `/{servicio}/vocabularios` porque varios servicios publican la misma
ruta y sin el segmento del servicio el gateway no sabría a cuál mandarla.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from crmcore import vocabulario as voc
from crmcore.errors import Conflicto, NoEncontrado
from crmcore.http.deps import AutenticadoDep, DbDep, exige_permiso


class NuevoValor(BaseModel):
    """Un valor añadido a mano por el cliente."""

    valor: str = Field(..., min_length=1, max_length=120, pattern=r"^[a-z0-9_]+$")
    etiqueta: str = Field(..., min_length=1, max_length=200)
    orden: int = Field(100, ge=0, le=10_000)
    extra: dict[str, Any] = Field(default_factory=dict)


class CambioValor(BaseModel):
    """Lo que se puede cambiar de un valor ya existente.

    El código no: lo llevan escrito los registros históricos, y cambiarlo los
    dejaría apuntando a un valor que ya no existe. Para eso se desactiva el
    viejo y se crea el nuevo.
    """

    etiqueta: str | None = Field(None, min_length=1, max_length=200)
    orden: int | None = Field(None, ge=0, le=10_000)
    activo: bool | None = None
    extra: dict[str, Any] | None = None


def crear_router_vocabulario(servicio: str) -> APIRouter:
    router = APIRouter(prefix=f"/{servicio}/vocabularios", tags=["vocabularios"])

    @router.get(
        "",
        response_model=list[dict],
        summary=f"Vocabularios que usa «{servicio}»",
        description=(
            "Los que este servicio valida contra una lista. Cada uno dice si "
            "sigue con los valores de fábrica o si la empresa ya los ha hecho "
            "suyos."
        ),
    )
    def listar(db: DbDep, _: AutenticadoDep) -> Any:
        salida = []
        for definicion in voc.registrados().values():
            propios = voc.filas(db, definicion.nombre, incluir_inactivos=True)
            salida.append(
                {
                    "id": definicion.nombre,
                    "nombre": definicion.nombre,
                    "etiqueta": definicion.etiqueta,
                    "descripcion": definicion.descripcion,
                    "valores": len(propios) or len(definicion.defectos),
                    "de_fabrica": not propios,
                }
            )
        return salida

    @router.get(
        "/{nombre}",
        response_model=list[dict],
        summary="Valores de un vocabulario",
    )
    def valores(
        nombre: str,
        db: DbDep,
        _: AutenticadoDep,
        incluir_inactivos: bool = Query(False),
    ) -> Any:
        return _valores_de(db, nombre, incluir_inactivos=incluir_inactivos)

    def _valores_de(
        db: Any, nombre: str, *, incluir_inactivos: bool = False
    ) -> list[dict[str, Any]]:
        if voc.definicion(nombre) is None:
            raise NoEncontrado(
                f"Este servicio no usa ningún vocabulario «{nombre}»",
                error_code="vocabulario.no_declarado",
            )
        return voc.como_lista(db, nombre, incluir_inactivos=incluir_inactivos)

    @router.get(
        "/{nombre}/{valor}",
        response_model=dict,
        summary="Un valor del vocabulario",
        description=(
            "Hace falta para poder abrirlo: cambiar su rótulo o retirarlo "
            "cuelga del valor, y a un valor que no se abre no se llega desde "
            "ninguna pantalla."
        ),
    )
    def ver(nombre: str, valor: str, db: DbDep, _: AutenticadoDep) -> Any:
        fila = next((f for f in _valores_de(db, nombre) if f["valor"] == valor), None)
        if fila is None:
            raise NoEncontrado(
                f"«{valor}» no está en este vocabulario",
                error_code="vocabulario.valor_no_existe",
            )
        return fila

    @router.post(
        "/{nombre}",
        response_model=dict,
        status_code=201,
        dependencies=[Depends(exige_permiso("metadata:write"))],
        summary="Añadir un valor",
        description=(
            "La primera vez que se toca un vocabulario que aún era el de "
            "fábrica, los valores de fábrica se copian y pasan a ser del "
            "cliente. Sin eso, añadir uno dejaría la lista con ese solo."
        ),
    )
    def crear(nombre: str, datos: NuevoValor, db: DbDep, principal: AutenticadoDep) -> Any:
        if voc.definicion(nombre) is None:
            raise NoEncontrado(
                f"Este servicio no usa ningún vocabulario «{nombre}»",
                error_code="vocabulario.no_declarado",
            )
        voc.materializar(db, nombre, principal.tenant_id)
        if any(f.valor == datos.valor for f in voc.filas(db, nombre, incluir_inactivos=True)):
            raise Conflicto(
                f"«{datos.valor}» ya está en este vocabulario",
                error_code="vocabulario.duplicado",
            )
        fila = voc.ValorVocabulario(
            tenant_id=principal.tenant_id,
            vocabulario=nombre,
            valor=datos.valor,
            etiqueta=datos.etiqueta,
            orden=datos.orden,
            extra=datos.extra,
        )
        db.add(fila)
        db.flush()
        return _salida(fila)

    @router.patch(
        "/{nombre}/{valor}",
        response_model=dict,
        dependencies=[Depends(exige_permiso("metadata:write"))],
        summary="Cambiar un valor",
        description=(
            "Se puede cambiar cómo se llama, dónde sale y si sigue en uso. El "
            "código no: lo llevan escrito los registros ya guardados."
        ),
    )
    def cambiar(
        nombre: str, valor: str, datos: CambioValor, db: DbDep, principal: AutenticadoDep
    ) -> Any:
        if voc.definicion(nombre) is None:
            raise NoEncontrado(
                f"Este servicio no usa ningún vocabulario «{nombre}»",
                error_code="vocabulario.no_declarado",
            )
        # También aquí: editar una etiqueta de fábrica es tocar el vocabulario,
        # y sin materializar antes no habría nada que editar.
        voc.materializar(db, nombre, principal.tenant_id)
        fila = next(
            (f for f in voc.filas(db, nombre, incluir_inactivos=True) if f.valor == valor), None
        )
        if fila is None:
            raise NoEncontrado(
                f"«{valor}» no está en este vocabulario", error_code="vocabulario.valor_no_existe"
            )
        cambios = datos.model_dump(exclude_none=True)
        for campo, nuevo in cambios.items():
            setattr(fila, campo, nuevo)
        db.flush()
        return _salida(fila)

    @router.delete(
        "/{nombre}/{valor}",
        response_model=dict,
        dependencies=[Depends(exige_permiso("metadata:write"))],
        summary="Retirar un valor",
        description=(
            "Se desactiva, no se borra: los registros que ya lo usan tienen que "
            "seguir enseñando su etiqueta. Un valor borrado deja el histórico "
            "en códigos sin significado."
        ),
    )
    def retirar(nombre: str, valor: str, db: DbDep, principal: AutenticadoDep) -> Any:
        return cambiar(nombre, valor, CambioValor(activo=False), db, principal)

    return router


def _salida(fila: Any) -> dict[str, Any]:
    return {
        # El identificador de un valor es su CÓDIGO, no la clave de la fila.
        # Es lo que llevan escrito los registros que lo usan, lo que espera la
        # ruta de la ficha y lo único que existe mientras el vocabulario sigue
        # siendo el de fábrica — donde todavía no hay fila ninguna.
        "id": fila.valor,
        "valor": fila.valor,
        "etiqueta": fila.etiqueta,
        "orden": fila.orden,
        "activo": fila.activo,
        "extra": fila.extra,
        "de_fabrica": False,
    }
