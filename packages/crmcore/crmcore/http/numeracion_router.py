"""La pantalla de la numeración de negocio (CRM-00.04.01.11).

Se monta sola en `crear_servicio`, como los vocabularios y la papelera, y por
el mismo motivo: si dependiera de que cada servicio se acuerde, faltaría justo
en el que guarda el objeto cuyo código alguien necesita cambiar.

Cuelga de `/{servicio}/numeracion` porque varios servicios publican la misma
ruta y sin el segmento del servicio el gateway no sabría a cuál mandarla.

**Lo que no deja hacer, y es lo importante.** No deja bajar el contador por
debajo de lo ya emitido —repetiría códigos impresos en ofertas— ni guardar un
patrón incoherente con su reinicio: eso se comprueba al guardar, no al emitir,
porque descubrirlo al emitir es descubrirlo con un registro a medio crear.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from crmcore import numeracion as num
from crmcore.errors import ErrorValidacion
from crmcore.fechas import hoy
from crmcore.http.deps import AutenticadoDep, DbDep, exige_permiso


class DeclararNumeracion(BaseModel):
    objeto: str = Field(..., min_length=1, max_length=80, examples=["oportunidad"])
    patron: str = Field(
        ...,
        min_length=1,
        max_length=120,
        description="Piezas: " + ", ".join(f"{{{p}}}" for p in num.PIEZAS),
        examples=["OPP-{anio}-{secuencia}"],
    )
    relleno: int = Field(5, ge=1, le=12, description="Dígitos de la secuencia: 5 da 00123")
    reinicio: str = Field("anual", description=" | ".join(num.REINICIOS))
    empezar_en: int | None = Field(
        None,
        ge=0,
        description=(
            "El último código ya emitido, para llegar de otro sistema sin "
            "repetir números que el cliente tiene impresos"
        ),
    )


def crear_router_numeracion(servicio: str) -> APIRouter:
    router = APIRouter(prefix=f"/{servicio}/numeracion", tags=["numeración"])

    @router.get(
        "",
        response_model=list[dict],
        dependencies=[Depends(exige_permiso("metadata:read"))],
        summary=f"Cómo se numera cada objeto de «{servicio}»",
        description=(
            "Con el **siguiente código que saldría**, que es lo que nadie puede "
            "saber mirando un contador: entre el número y el código hay un "
            "patrón, un relleno y un periodo."
        ),
    )
    def listar(db: DbDep, principal: AutenticadoDep) -> Any:
        filas = (
            db.execute(
                select(num.NumeracionObjeto).where(
                    num.NumeracionObjeto.tenant_id == principal.tenant_id
                )
            )
            .scalars()
            .all()
        )
        dia = hoy(db)
        salida = []
        for fila in filas:
            # Se enseña el SIGUIENTE, no el último: quien mira esta pantalla
            # quiere saber qué va a salir, no qué salió.
            asomado = num.NumeracionObjeto(
                objeto=fila.objeto,
                patron=fila.patron,
                relleno=fila.relleno,
                reinicio=fila.reinicio,
                periodo=fila.periodo,
                ultimo=fila.ultimo + 1,
            )
            salida.append(
                {
                    "id": str(fila.id),
                    "objeto": fila.objeto,
                    "patron": fila.patron,
                    "relleno": fila.relleno,
                    "reinicio": fila.reinicio,
                    "periodo": fila.periodo,
                    "ultimo": fila.ultimo,
                    "activa": fila.activa,
                    "siguiente_codigo": num.formatear(asomado, dia),
                }
            )
        return salida

    @router.post(
        "",
        response_model=dict,
        dependencies=[Depends(exige_permiso("metadata:write"))],
        summary="Declarar o cambiar cómo se numera un objeto",
        description=(
            "El patrón se comprueba **al guardar**. Un patrón sin `{secuencia}` "
            "daría el mismo código a todos los registros, y lo que se vería es "
            "«no se puede crear», no «falta el número»."
        ),
    )
    def declarar(datos: DeclararNumeracion, db: DbDep, principal: AutenticadoDep) -> Any:
        actual = db.execute(
            select(num.NumeracionObjeto).where(
                num.NumeracionObjeto.tenant_id == principal.tenant_id,
                num.NumeracionObjeto.objeto == datos.objeto,
            )
        ).scalar_one_or_none()
        # Bajar el contador repite códigos que ya están en ofertas y albaranes.
        # Es la única forma de hacer daño desde aquí, y por eso se cierra.
        if actual is not None and datos.empezar_en is not None and datos.empezar_en < actual.ultimo:
            raise ErrorValidacion(
                f"El contador de «{datos.objeto}» va por {actual.ultimo}: bajarlo "
                f"a {datos.empezar_en} repetiría códigos que ya se han emitido.",
                error_code="numeracion.contador_hacia_atras",
            )
        fila = num.declarar(
            db,
            principal.tenant_id,
            objeto=datos.objeto,
            patron=datos.patron,
            relleno=datos.relleno,
            reinicio=datos.reinicio,
            empezar_en=datos.empezar_en,
        )
        asomado = num.NumeracionObjeto(
            objeto=fila.objeto,
            patron=fila.patron,
            relleno=fila.relleno,
            reinicio=fila.reinicio,
            periodo=fila.periodo,
            ultimo=fila.ultimo + 1,
        )
        return {
            "objeto": fila.objeto,
            "patron": fila.patron,
            "ultimo": fila.ultimo,
            "siguiente_codigo": num.formatear(asomado, hoy(db)),
        }

    return router
