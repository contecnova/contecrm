"""API de entornos de pruebas con datos del cliente (CRM-07.02.01.02).

Copiar producción a pruebas es sacar los datos personales de tus clientes de donde
están protegidos y ponerlos donde entra todo el mundo. Por eso aquí casi todo es
una comprobación previa.
"""

from __future__ import annotations

from typing import Any

from crmcore.http.deps import AutenticadoDep, exige_permiso
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from services.tenancy import sandboxes as sbx

router_sandboxes = APIRouter(prefix="/sandboxes", tags=["entornos de pruebas"])


class PlanIn(BaseModel):
    proposito: str
    porcentaje: int = 5
    anonimizar: bool = True
    motivo_sin_anonimizar: str = ""


class ReglasIn(BaseModel):
    campos_personales: list[str] = Field(default_factory=list)
    reglas: dict[str, str] = Field(default_factory=dict)


class CaducadosIn(BaseModel):
    sandboxes: list[dict[str, Any]] = Field(default_factory=list)


@router_sandboxes.post(
    "/plan",
    dependencies=[Depends(exige_permiso("tenancy:write"))],
    summary="Preparar una copia a un entorno que no es producción",
    description=(
        "**Copiar sin anonimizar exige pedirlo y explicarlo**, con nombre. Que sea "
        "una casilla marcada por defecto es lo que hace que nadie la mire: a "
        "pruebas entran el consultor externo, el becario y el proveedor que está "
        "integrando algo, y no hay ni el mismo cifrado ni el mismo control de "
        "acceso.\n\n"
        "Se recomienda copia **parcial**, y no por espacio: con el 5 % de los "
        "clientes se prueba igual de bien y hay veinte veces menos que proteger.\n\n"
        "Hay cosas que no se copian nunca —tokens, claves de API, secretos de "
        "webhook—: un token válido en pruebas es una puerta abierta a producción."
    ),
)
def plan(cuerpo: PlanIn, principal: AutenticadoDep) -> Any:
    return sbx.plan_de_copia(
        proposito=cuerpo.proposito,
        porcentaje=cuerpo.porcentaje,
        anonimizar=cuerpo.anonimizar,
        motivo_sin_anonimizar=cuerpo.motivo_sin_anonimizar,
        pedido_por=principal.id,
    )


class AnonimizarIn(BaseModel):
    entorno: str = Field(
        ...,
        min_length=1,
        description=(
            "El nombre del entorno destino. De él sale la sal, **distinta por "
            "entorno**: con la misma en todos, juntar dos copias con campos "
            "distintos anonimizados reconstruiría el registro entero"
        ),
    )
    filas: list[dict[str, Any]] = Field(default_factory=list)
    reglas: dict[str, str] = Field(default_factory=dict)


@router_sandboxes.post(
    "/anonimizar",
    dependencies=[Depends(exige_permiso("tenancy:write"))],
    summary="Aplicar la anonimización a estas filas",
    description=(
        "**Consistente dentro del entorno**: el mismo valor original da siempre "
        "el mismo valor falso, así que una búsqueda por cliente sigue "
        "devolviendo sus oportunidades y sus casos. Sin eso el entorno no sirve "
        "para probar nada que cruce datos, que es casi todo lo que se "
        "prueba.\n\n"
        "**Y distinto entre entornos.** La sal sale del nombre del entorno: con "
        "la misma en todos, juntar dos copias con campos distintos anonimizados "
        "devolvería el registro entero.\n\n"
        "El valor falso **conserva la forma** —un correo sigue siendo un correo, "
        "un teléfono un teléfono—, que es lo que hace que las pantallas con "
        "validación funcionen en pruebas. Y un campo con regla desconocida **se "
        "vacía**: por defecto se protege, no se copia."
    ),
)
def anonimizar(cuerpo: AnonimizarIn, principal: AutenticadoDep) -> Any:
    from crmcore.config import get_settings
    from crmcore.seguridad.anonimizar import sal_de_entorno

    sal = sal_de_entorno(cuerpo.entorno, get_settings().secret_key.get_secret_value())
    salidas = [
        sbx.anonimizar_fila(fila=fila, reglas=cuerpo.reglas, semilla=sal) for fila in cuerpo.filas
    ]
    return {
        "entorno": cuerpo.entorno,
        "filas": [s["fila"] for s in salidas],
        # Los avisos, juntos y sin repetir: una regla desconocida sale en todas
        # las filas y repetirla mil veces esconde las demás.
        "avisos": sorted({a for s in salidas for a in s["avisos"]}),
        "porque": (
            "Mismo valor y mismo entorno, mismo sustituto. Distinto entorno, "
            "sustituto distinto: cruzar dos copias no reconstruye nada."
        ),
    }


@router_sandboxes.post(
    "/reglas",
    dependencies=[Depends(exige_permiso("tenancy:read"))],
    summary="Comprobar que toda columna personal tiene decidido su tratamiento",
    description=(
        "Es la comprobación que evita el fallo típico: se anonimiza lo que se ve "
        "—nombres y correos— y se olvidan el teléfono de una tabla secundaria, el "
        "campo personalizado que alguien creó y el nombre completo escrito a mano "
        "en una nota."
    ),
)
def reglas(cuerpo: ReglasIn, principal: AutenticadoDep) -> Any:
    return sbx.comprobar_reglas(campos_personales=cuerpo.campos_personales, reglas=cuerpo.reglas)


@router_sandboxes.post(
    "/caducados",
    dependencies=[Depends(exige_permiso("tenancy:read"))],
    summary="Qué entornos hay que refrescar o apagar",
    description=(
        "El sandbox creado para una migración hace año y medio sigue ahí con los "
        "datos de entonces, sin actualizaciones y sin que nadie recuerde quién "
        "tiene acceso. No es desorden: es una copia de datos de clientes viviendo "
        "en un sitio del que ya nadie se acuerda."
    ),
)
def caducados(cuerpo: CaducadosIn, principal: AutenticadoDep) -> Any:
    return sbx.caducados(sandboxes=cuerpo.sandboxes)


ROUTERS_SANDBOXES = [router_sandboxes]
