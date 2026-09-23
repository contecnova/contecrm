"""API del maestro y el gobierno del proveedor (CRM-09.01.01.01 a .06, .10).

El proveedor no tiene recurso propio de alta: **es una cuenta**. Aquí solo está lo
que se le añade encima —homologación, papeles, contactos y riesgo—, que es lo que
decide si se le puede encargar algo hoy.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from crmcore.http.deps import (
    AutenticadoDep,
    DbDep,
    UowDep,
    exige_permiso,
    proyectar_para,  # noqa: F401
)
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from services.party import proveedores as prv

router_proveedores = APIRouter(prefix="/proveedores", tags=["proveedores"])


class HomologarIn(BaseModel):
    categoria: str = Field(..., min_length=1, max_length=80)
    requisitos: list[dict[str, Any]] = Field(default_factory=list)
    valida_hasta: date | None = None


class DocumentoIn(BaseModel):
    clave: str
    nombre: str = ""
    referencia: str
    valido_desde: date | None = None
    valido_hasta: date | None = None
    dias_preaviso: int = prv.DIAS_PREAVISO
    bloquea_al_vencer: bool = True


class ContactoIn(BaseModel):
    funcion: str
    nombre: str = ""
    email: str
    telefono: str = ""
    fuera_de_horario: str = ""


class RiesgoIn(BaseModel):
    proveedores: list[dict[str, Any]] = Field(default_factory=list)
    umbral_concentracion: float = 40.0


class EvaluarIn(BaseModel):
    entregas: list[dict[str, Any]] = Field(default_factory=list)
    incidencias: list[dict[str, Any]] = Field(default_factory=list)
    encuesta: int | None = None


@router_proveedores.post(
    "/{cuenta_id}/rol",
    dependencies=[Depends(exige_permiso("party:write"))],
    summary="Marcar una cuenta como proveedor",
    description=(
        "Un proveedor es **una cuenta con rol**, no un maestro aparte. Uno en "
        "paralelo duplicaría la deduplicación, la jerarquía, las direcciones y "
        "los permisos, y la misma empresa que es cliente de una división y "
        "proveedor de otra estaría dos veces — con el riesgo de que se le "
        "apliquen las condiciones de la ficha equivocada.\n\n"
        "El rol **se suma**: no sustituye al de cliente."
    ),
)
def marcar_rol(cuenta_id: UUID, uow: UowDep) -> Any:
    return prv.marcar_como_proveedor(uow, cuenta_id=cuenta_id)


@router_proveedores.post(
    "/{cuenta_id}/homologacion",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("party:write"))],
    summary="Homologar para una categoría, con fecha de fin",
    description=(
        "«Proveedor homologado» a secas no significa nada: homologado ¿para qué? "
        "Uno puede valer para material de oficina y no para trabajos en altura, y "
        "tratarlo igual es como se contrata a quien no debe.\n\n"
        "**Sin todos los requisitos cubiertos no se homologa.** Homologar «con "
        "salvedades» es homologar: nadie vuelve a mirar la salvedad, y el día que "
        "pasa algo la salvedad era justo eso.\n\n"
        "**Y sin fecha de fin tampoco**: una homologación eterna es una que nadie "
        "revisa, y a los cinco años nadie sabe si esa empresa sigue teniendo los "
        "medios que tenía."
    ),
)
def homologar(cuenta_id: UUID, cuerpo: HomologarIn, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = prv.homologar(
        uow,
        cuenta_id=cuenta_id,
        categoria=cuerpo.categoria,
        requisitos=cuerpo.requisitos,
        valida_hasta=cuerpo.valida_hasta,
        revisada_por=principal.id,
    )
    return {
        "id": str(fila.id),
        "categoria": fila.categoria,
        "estado": fila.estado,
        "valida_hasta": fila.valida_hasta.isoformat() if fila.valida_hasta else None,
    }


@router_proveedores.get(
    "/{cuenta_id}/homologacion/{categoria}",
    dependencies=[Depends(exige_permiso("party:read"))],
    summary="Si se le puede encargar algo de esa categoría, hoy",
    description=(
        "La respuesta distingue **«no está homologado» de «se le caducó»**: la "
        "primera exige empezar el proceso y la segunda solo papel nuevo. "
        "Confundirlas hace que se descarte a un proveedor que valdría mañana."
    ),
)
def homologado(cuenta_id: UUID, categoria: str, db: DbDep, principal: AutenticadoDep) -> Any:
    return prv.esta_homologado(db, principal.tenant_id, cuenta_id=cuenta_id, categoria=categoria)


@router_proveedores.post(
    "/{cuenta_id}/documentos",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("party:write"))],
    summary="Registrar un papel obligatorio con su vigencia",
    description=(
        "El fichero **no se guarda aquí**: se referencia en el gestor documental, "
        "que ya existe y ya cifra. Tener dos sitios donde viven documentos deja "
        "uno de los dos sin cifrar, y será el que nadie recuerda."
    ),
)
def documento(cuenta_id: UUID, cuerpo: DocumentoIn, uow: UowDep) -> Any:
    fila = prv.registrar_documento(
        uow,
        cuenta_id=cuenta_id,
        clave=cuerpo.clave,
        nombre=cuerpo.nombre,
        referencia=cuerpo.referencia,
        valido_desde=cuerpo.valido_desde,
        valido_hasta=cuerpo.valido_hasta,
        dias_preaviso=cuerpo.dias_preaviso,
        bloquea_al_vencer=cuerpo.bloquea_al_vencer,
    )
    return {"id": str(fila.id), "clave": fila.clave}


@router_proveedores.get(
    "/{cuenta_id}/documentos",
    dependencies=[Depends(exige_permiso("party:read"))],
    summary="Qué papeles le faltan, cuáles vencen y cuáles ya vencieron",
    description=(
        "**Lo vencido que bloquea, bloquea solo.** Un certificado caducado que "
        "hay que mirar a mano no se mira: se descubre el día que el cliente "
        "pregunta quién hizo el trabajo y con qué seguro.\n\n"
        "Y si no consta ningún documento se dice: eso no es que esté todo en "
        "regla, es que no se ha pedido nada."
    ),
)
def documentos(cuenta_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return prv.estado_documental(db, principal.tenant_id, cuenta_id=cuenta_id)


@router_proveedores.get(
    "/documentos/vencen",
    dependencies=[Depends(exige_permiso("party:read"))],
    summary="La lista de trabajo: qué hay que renovar y de quién",
    description=(
        "Con lo que **ya venció** primero: eso no es un aviso, es un problema que "
        "está pasando ahora."
    ),
)
def vencen(db: DbDep, principal: AutenticadoDep, dias: int = Query(prv.DIAS_PREAVISO)) -> Any:
    return prv.documentos_que_vencen(db, principal.tenant_id, dias=dias)


@router_proveedores.post(
    "/{cuenta_id}/contactos",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("party:write"))],
    summary="A quién se llama y para qué",
)
def contacto(cuenta_id: UUID, cuerpo: ContactoIn, uow: UowDep) -> Any:
    fila = prv.registrar_contacto(
        uow,
        cuenta_id=cuenta_id,
        funcion=cuerpo.funcion,
        nombre=cuerpo.nombre,
        email=cuerpo.email,
        telefono=cuerpo.telefono,
        fuera_de_horario=cuerpo.fuera_de_horario,
    )
    return {"id": str(fila.id), "funcion": fila.funcion}


@router_proveedores.get(
    "/{cuenta_id}/a-quien-llamo",
    dependencies=[Depends(exige_permiso("party:read"))],
    summary="A quién se llama cuando esto falla",
    description=(
        "Si **no hay nadie para escalar se dice**, en vez de devolver el "
        "comercial: su teléfono a las once de la noche no es una respuesta, es "
        "media hora perdida antes de descubrir que no hay nadie."
    ),
)
def a_quien_llamo(
    cuenta_id: UUID, db: DbDep, principal: AutenticadoDep, funcion: str = Query("escalado")
) -> Any:
    return prv.a_quien_llamo(db, principal.tenant_id, cuenta_id=cuenta_id, funcion=funcion)


@router_proveedores.post(
    "/riesgo",
    dependencies=[Depends(exige_permiso("party:read"))],
    summary="Dónde duele si un proveedor falla mañana",
    description=(
        "Lo que hace daño **no es un proveedor malo**: un proveedor malo se "
        "cambia. Lo que hace daño es un proveedor bueno del que sale el 60 % de "
        "lo que se sirve y que no tiene alternativa homologada — el día que tiene "
        "un incendio no hay nada que decidir, solo que contar.\n\n"
        "Por eso se mide la **concentración** y la **alternativa**, no la opinión "
        "que se tenga de cada uno. Sin volumen registrado se dice que no es "
        "medible: se puede opinar, que no es lo mismo."
    ),
)
def riesgo(cuerpo: RiesgoIn, principal: AutenticadoDep) -> Any:
    return prv.riesgo_de_dependencia(
        proveedores=cuerpo.proveedores, umbral_concentracion=cuerpo.umbral_concentracion
    )


@router_proveedores.post(
    "/evaluacion",
    dependencies=[Depends(exige_permiso("party:read"))],
    summary="Cómo va este proveedor, con hechos",
    description=(
        "Una encuesta anual mide la relación con su comercial, que es legítimo y "
        "no es el servicio. El plazo cumplido y las incidencias sí lo miden, y "
        "son números que ya están: no hay que pedirle a nadie que rellene nada.\n\n"
        "Si no hay entregas **no se puntúa**: un proveedor al que no se le ha "
        "encargado nada no es bueno ni malo, es uno del que no se sabe."
    ),
)
def evaluacion(cuerpo: EvaluarIn, principal: AutenticadoDep) -> Any:
    return prv.evaluar(
        entregas=cuerpo.entregas, incidencias=cuerpo.incidencias, encuesta=cuerpo.encuesta
    )


# ── Listado ───────────────────────────────────────────────────────────────
# Se podían homologar proveedores y no se podía ver ninguno: las acciones
# cuelgan de `/proveedores/{cuenta_id}/...` y a un registro se llega por su
# listado.
#
# No es una tabla propia: **un proveedor es una cuenta con ese rol**. Duplicarlo
# en otra tabla habría creado dos maestros del mismo dato, que es justo lo que
# el modelo evita con `roles`.


@router_proveedores.get(
    "",
    response_model=dict,
    dependencies=[Depends(exige_permiso("party:read"))],
    summary="Listar proveedores",
    description=(
        "Las cuentas que llevan el rol `proveedor`. La misma empresa puede ser "
        "cliente de una división y proveedor de otra, y por eso los roles son "
        "una lista y no un tipo."
    ),
)
def listar_proveedores(
    db: DbDep,
    principal: AutenticadoDep,
    limite: int = Query(50, ge=1, le=200),
    cursor: str = Query(""),
) -> Any:
    from crmcore.http.pagination import ParametrosPagina, aplicar_orden_y_cursor, construir_pagina
    from sqlalchemy import select

    from services.party.modelos import Cuenta

    params = ParametrosPagina.desde_query(limite=limite, cursor=cursor, orden="-created_at")
    consulta = select(Cuenta).where(
        Cuenta.deleted_at.is_(None),
        Cuenta.roles.contains(["proveedor"]),
    )
    consulta = aplicar_orden_y_cursor(
        consulta,
        Cuenta,
        params,
        columnas_permitidas={"created_at", "nombre"},
        objeto="cuenta",
        principal=principal,
        db=db,
    )
    filas = list(db.execute(consulta.limit(params.limite + 1)).scalars().all())
    pagina = construir_pagina(filas, params, campos_orden=["-created_at"])
    proyecta = proyectar_para(principal, db, objeto="cuenta", modelo=Cuenta)
    return pagina.a_dict(proyecta)


ROUTERS_PROVEEDORES = [router_proveedores]
