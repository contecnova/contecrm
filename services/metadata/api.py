"""API del servicio de metadatos."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select

from crmcore.audit.chain import registrar
from crmcore.errors import Conflicto, NoEncontrado
from crmcore.http.deps import AutenticadoDep, DbDep, exige_permiso
from services.metadata.esquemas import (
    CampoOut,
    CrearCampo,
    CrearObjeto,
    CrearRegla,
    CrearValorLista,
    DescribeOut,
    ObjetoOut,
    ReglaOut,
    ResultadoValidacion,
    ValidarRegistro,
    ValorListaOut,
)
from services.metadata.modelos import (
    CampoDefinido,
    Layout,
    ObjetoDefinido,
    ReglaValidacion,
    ValorLista,
)
from services.metadata.validacion import validar_registro

router = APIRouter(prefix="/metadata", tags=["metadatos"])


def _objeto(db: Any, tenant_id: UUID, nombre: str) -> ObjetoDefinido:
    objeto = db.execute(
        select(ObjetoDefinido).where(
            ObjetoDefinido.tenant_id == tenant_id, ObjetoDefinido.nombre == nombre
        )
    ).scalar_one_or_none()
    if objeto is None:
        raise NoEncontrado(
            f"El objeto «{nombre}» no existe", error_code="metadata.objeto_no_encontrado"
        )
    return objeto


# ── Objetos ───────────────────────────────────────────────────────────────


@router.post(
    "/objetos",
    response_model=ObjetoOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("metadata:write"))],
    summary="Crear un objeto propio del tenant",
    description=(
        "No ejecuta DDL: el objeto queda declarado y sus registros viven en el "
        "modelo común. Por eso crear un objeto en un tenant no afecta a los demás."
    ),
)
def crear_objeto(datos: CrearObjeto, db: DbDep, principal: AutenticadoDep) -> Any:
    if db.execute(
        select(ObjetoDefinido.id).where(
            ObjetoDefinido.tenant_id == principal.tenant_id,
            ObjetoDefinido.nombre == datos.nombre,
        )
    ).first():
        raise Conflicto(
            "Ya existe un objeto con ese nombre", error_code="metadata.objeto_duplicado"
        )
    objeto = ObjetoDefinido(
        tenant_id=principal.tenant_id,
        origen="propio",
        etiqueta_plural=datos.etiqueta_plural or datos.etiqueta,
        **datos.model_dump(exclude={"etiqueta_plural"}),
    )
    db.add(objeto)
    registrar(
        db,
        accion="metadata.objeto_creado",
        objeto="objeto",
        objeto_id=objeto.id,
        datos={"nombre": datos.nombre},
    )
    return objeto


@router.get(
    "/objetos",
    response_model=list[ObjetoOut],
    summary="Objetos del tenant",
)
def listar_objetos(db: DbDep, principal: AutenticadoDep) -> Any:
    return list(
        db.execute(
            select(ObjetoDefinido)
            .where(
                ObjetoDefinido.tenant_id == principal.tenant_id,
                ObjetoDefinido.activo.is_(True),
            )
            .order_by(ObjetoDefinido.nombre)
        )
        .scalars()
        .all()
    )


@router.get(
    "/objetos/{nombre}/describe",
    response_model=DescribeOut,
    summary="Descripción completa del objeto",
    description=(
        "Campos, validaciones, layouts y los permisos de quien pregunta. Es la "
        "llamada que permite a cualquier frontend renderizar formularios y "
        "listas sin saber nada del CRM ni duplicar reglas."
    ),
)
def describe(nombre: str, db: DbDep, principal: AutenticadoDep) -> Any:
    objeto = _objeto(db, principal.tenant_id, nombre)
    campos = list(
        db.execute(
            select(CampoDefinido)
            .where(CampoDefinido.objeto_id == objeto.id, CampoDefinido.activo.is_(True))
            .order_by(CampoDefinido.orden, CampoDefinido.nombre)
        )
        .scalars()
        .all()
    )
    reglas = list(
        db.execute(
            select(ReglaValidacion).where(
                ReglaValidacion.objeto_id == objeto.id, ReglaValidacion.activa.is_(True)
            )
        )
        .scalars()
        .all()
    )
    layouts = list(
        db.execute(select(Layout).where(Layout.objeto_id == objeto.id)).scalars().all()
    )
    return DescribeOut(
        objeto=ObjetoOut.model_validate(objeto),
        campos=[CampoOut.model_validate(c) for c in campos],
        reglas=[ReglaOut.model_validate(r) for r in reglas],
        layouts=[
            {"nombre": layout.nombre, "rol": layout.rol, "secciones": layout.secciones}
            for layout in layouts
        ],
        permisos={
            accion: principal.tiene(f"{nombre}:{accion}")
            for accion in ("read", "write", "delete", "export")
        },
    )


# ── Campos ────────────────────────────────────────────────────────────────


@router.post(
    "/objetos/{nombre}/campos",
    response_model=CampoOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("metadata:write"))],
    summary="Añadir un campo a un objeto",
)
def crear_campo(
    nombre: str, datos: CrearCampo, db: DbDep, principal: AutenticadoDep
) -> Any:
    objeto = _objeto(db, principal.tenant_id, nombre)
    if db.execute(
        select(CampoDefinido.id).where(
            CampoDefinido.objeto_id == objeto.id, CampoDefinido.nombre == datos.nombre
        )
    ).first():
        raise Conflicto(
            "Ya existe un campo con ese nombre en el objeto",
            error_code="metadata.campo_duplicado",
        )
    campo = CampoDefinido(
        tenant_id=principal.tenant_id, objeto_id=objeto.id, **datos.model_dump()
    )
    db.add(campo)
    registrar(
        db,
        accion="metadata.campo_creado",
        objeto="campo",
        objeto_id=campo.id,
        datos={"objeto": nombre, "campo": datos.nombre, "tipo": datos.tipo},
    )
    return campo


@router.delete(
    "/objetos/{nombre}/campos/{campo}",
    response_model=CampoOut,
    dependencies=[Depends(exige_permiso("metadata:write"))],
    summary="Deprecar un campo",
    description=(
        "No lo borra: lo marca como deprecado. Sigue leyéndose y deja de "
        "ofrecerse para escribir, que es lo que permite retirarlo sin romper "
        "integraciones que aún lo mandan."
    ),
)
def deprecar_campo(
    nombre: str, campo: str, db: DbDep, principal: AutenticadoDep
) -> Any:
    objeto = _objeto(db, principal.tenant_id, nombre)
    fila = db.execute(
        select(CampoDefinido).where(
            CampoDefinido.objeto_id == objeto.id, CampoDefinido.nombre == campo
        )
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado("El campo no existe", error_code="metadata.campo_no_encontrado")
    fila.deprecado = True
    fila.solo_lectura = True
    registrar(
        db,
        accion="metadata.campo_deprecado",
        objeto="campo",
        objeto_id=fila.id,
        datos={"objeto": nombre, "campo": campo},
    )
    return fila


# ── Validación ────────────────────────────────────────────────────────────


@router.post(
    "/objetos/{nombre}/validar",
    response_model=ResultadoValidacion,
    summary="Validar un registro sin guardarlo",
    description=(
        "Ejecuta **las mismas** reglas que al guardar. Un frontend puede "
        "enseñar los errores antes de enviar sin reimplementarlas —que es como "
        "acaban divergiendo del servidor."
    ),
)
def validar(
    nombre: str, datos: ValidarRegistro, db: DbDep, principal: AutenticadoDep
) -> Any:
    objeto = _objeto(db, principal.tenant_id, nombre)
    campos = list(
        db.execute(select(CampoDefinido).where(CampoDefinido.objeto_id == objeto.id))
        .scalars()
        .all()
    )
    reglas = list(
        db.execute(select(ReglaValidacion).where(ReglaValidacion.objeto_id == objeto.id))
        .scalars()
        .all()
    )
    valores, errores = validar_registro(
        campos, datos.datos, reglas=reglas, parcial=datos.parcial
    )
    return ResultadoValidacion(valido=not errores, errores=errores, valores=valores)


@router.post(
    "/objetos/{nombre}/reglas",
    response_model=ReglaOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("metadata:write"))],
    summary="Crear una regla de validación",
)
def crear_regla(
    nombre: str, datos: CrearRegla, db: DbDep, principal: AutenticadoDep
) -> Any:
    objeto = _objeto(db, principal.tenant_id, nombre)
    regla = ReglaValidacion(
        tenant_id=principal.tenant_id, objeto_id=objeto.id, **datos.model_dump()
    )
    db.add(regla)
    return regla


# ── Listas maestras ───────────────────────────────────────────────────────


@router.get(
    "/listas/{lista}",
    response_model=list[ValorListaOut],
    summary="Valores de una lista maestra",
)
def valores_lista(
    lista: str,
    db: DbDep,
    principal: AutenticadoDep,
    incluir_inactivos: bool = Query(False),
) -> Any:
    consulta = select(ValorLista).where(
        ValorLista.tenant_id == principal.tenant_id, ValorLista.lista == lista
    )
    if not incluir_inactivos:
        consulta = consulta.where(ValorLista.activo.is_(True))
    return list(
        db.execute(consulta.order_by(ValorLista.orden, ValorLista.etiqueta)).scalars().all()
    )


@router.post(
    "/listas/{lista}",
    response_model=ValorListaOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("metadata:write"))],
    summary="Añadir un valor a una lista maestra",
)
def crear_valor(
    lista: str, datos: CrearValorLista, db: DbDep, principal: AutenticadoDep
) -> Any:
    fila = ValorLista(tenant_id=principal.tenant_id, lista=lista, **datos.model_dump())
    db.add(fila)
    return fila


@router.delete(
    "/listas/{lista}/{valor}",
    response_model=ValorListaOut,
    dependencies=[Depends(exige_permiso("metadata:write"))],
    summary="Desactivar un valor de lista",
    description=(
        "Se desactiva, no se borra: los registros históricos que lo usan tienen "
        "que seguir enseñando su etiqueta. Un valor borrado convierte el "
        "histórico en códigos sin significado."
    ),
)
def desactivar_valor(
    lista: str, valor: str, db: DbDep, principal: AutenticadoDep
) -> Any:
    fila = db.execute(
        select(ValorLista).where(
            ValorLista.tenant_id == principal.tenant_id,
            ValorLista.lista == lista,
            ValorLista.valor == valor,
        )
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado("El valor no existe", error_code="metadata.valor_no_encontrado")
    fila.activo = False
    return fila


ROUTERS = [router]
