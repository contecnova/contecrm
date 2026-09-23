"""API del servicio de metadatos."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.audit.chain import registrar
from crmcore.errors import Conflicto, NoEncontrado
from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from crmcore.rpc.esquema import CAMPOS_QUE_NO_SALEN
from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from services.metadata import relaciones as rel
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
    db.flush()
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
    layouts = list(db.execute(select(Layout).where(Layout.objeto_id == objeto.id)).scalars().all())
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
def crear_campo(nombre: str, datos: CrearCampo, db: DbDep, principal: AutenticadoDep) -> Any:
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
    campo = CampoDefinido(tenant_id=principal.tenant_id, objeto_id=objeto.id, **datos.model_dump())
    db.add(campo)
    db.flush()
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
def deprecar_campo(nombre: str, campo: str, db: DbDep, principal: AutenticadoDep) -> Any:
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
    # Es un POST que no escribe, pero sí exige permiso de LECTURA sobre los
    # metadatos: la respuesta revela qué campos existen, cuáles son obligatorios
    # y qué reglas hay, que es el esquema del tenant.
    dependencies=[Depends(exige_permiso("metadata:read"))],
    summary="Validar un registro sin guardarlo",
    description=(
        "Ejecuta **las mismas** reglas que al guardar. Un frontend puede "
        "enseñar los errores antes de enviar sin reimplementarlas —que es como "
        "acaban divergiendo del servidor."
    ),
)
def validar(nombre: str, datos: ValidarRegistro, db: DbDep, principal: AutenticadoDep) -> Any:
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
    valores, errores = validar_registro(campos, datos.datos, reglas=reglas, parcial=datos.parcial)
    return ResultadoValidacion(valido=not errores, errores=errores, valores=valores)


@router.post(
    "/objetos/{nombre}/reglas",
    response_model=ReglaOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("metadata:write"))],
    summary="Crear una regla de validación",
)
def crear_regla(nombre: str, datos: CrearRegla, db: DbDep, principal: AutenticadoDep) -> Any:
    objeto = _objeto(db, principal.tenant_id, nombre)
    regla = ReglaValidacion(
        tenant_id=principal.tenant_id, objeto_id=objeto.id, **datos.model_dump()
    )
    db.add(regla)
    db.flush()
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
def crear_valor(lista: str, datos: CrearValorLista, db: DbDep, principal: AutenticadoDep) -> Any:
    fila = ValorLista(tenant_id=principal.tenant_id, lista=lista, **datos.model_dump())
    db.add(fila)
    db.flush()
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
def desactivar_valor(lista: str, valor: str, db: DbDep, principal: AutenticadoDep) -> Any:
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


# ── Relaciones entre objetos (CRM-00.04.01.03) ────────────────────────────


class CrearRelacion(BaseModel):
    nombre: str = Field(..., max_length=80)
    etiqueta: str = Field(..., max_length=200)
    nombre_inverso: str = Field(
        "",
        max_length=80,
        description=(
            "Cómo se llama vista desde el otro lado. Sin esto, la ficha del "
            "destino enseña «relaciones» sin nombre: desde la cuenta se llama "
            "«contactos» y desde el contacto, «cuentas»."
        ),
    )
    descripcion: str = ""
    origen: str = Field(..., max_length=80)
    destino: str | None = Field(None, max_length=80)
    destinos: list[str] = Field(
        default_factory=list, description="Tipos admitidos, solo en las polimórficas"
    )
    tipo: str = Field(
        "referencia", description="referencia | maestro_detalle | jerarquica | polimorfica"
    )
    cardinalidad: str = Field("1:N", description="1:1 | 1:N | N:M")
    al_borrar: str = Field("restringir", description="restringir | cascada | desvincular")
    obligatoria: bool = False
    via: str | None = Field(None, description="Objeto intermedio de una N:M")
    activa: bool = True


class RelacionOut(BaseModel):
    id: UUID
    nombre: str
    etiqueta: str
    nombre_inverso: str
    origen: str
    destino: str | None
    destinos: list[Any]
    tipo: str
    cardinalidad: str
    al_borrar: str
    obligatoria: bool
    via: str | None
    activa: bool

    model_config = {"from_attributes": True}


@router.get(
    "/relaciones/tipos",
    response_model=dict,
    summary="Tipos de relación y qué implica cada uno",
    description=(
        "No son etiquetas: cada tipo impone reglas distintas. Una "
        "maestro-detalle es siempre 1:N, obligatoria y en cascada, porque eso "
        "es lo que significa; dejar elegirlo la convertiría en una referencia "
        "con otro nombre."
    ),
)
def tipos_relacion() -> Any:
    return {
        "tipos": rel.TIPOS,
        "cardinalidades": list(rel.CARDINALIDADES),
        "al_borrar": rel.AL_BORRAR,
    }


@router.get("/relaciones", response_model=list[RelacionOut], summary="Relaciones declaradas")
def listar_relaciones(db: DbDep, principal: AutenticadoDep) -> Any:
    return list(
        db.execute(
            select(rel.RelacionDefinida)
            .where(rel.RelacionDefinida.tenant_id == principal.tenant_id)
            .order_by(rel.RelacionDefinida.origen, rel.RelacionDefinida.nombre)
        )
        .scalars()
        .all()
    )


@router.post(
    "/relaciones",
    response_model=RelacionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("metadata:write"))],
    summary="Declarar una relación entre objetos",
    description=(
        "Devuelve **todos** los problemas de coherencia a la vez, no el "
        "primero: quien modela un objeto agradece ver de una vez las tres cosas "
        "que no encajan en vez de corregir una, reenviar y descubrir la "
        "siguiente."
    ),
)
def crear_relacion(datos: CrearRelacion, db: DbDep, principal: AutenticadoDep) -> Any:
    return rel.crear(db, tenant_id=principal.tenant_id, datos=datos.model_dump())


@router.post(
    "/relaciones/validar",
    response_model=dict,
    summary="Comprobar una relación sin declararla",
    dependencies=[Depends(exige_permiso("metadata:write"))],
    description=(
        "Para el editor de modelo: enseña si encaja antes de guardarla. Cada "
        "regla que se comprueba aquí es una que, si no se comprueba, se "
        "descubre con datos dentro — y entonces arreglarla es una migración."
    ),
)
def validar_relacion(datos: CrearRelacion, _: AutenticadoDep) -> Any:
    problemas = rel.validar(datos.model_dump())
    return {"valida": not problemas, "problemas": problemas}


@router.get(
    "/relaciones/grafo",
    response_model=dict,
    summary="El mapa de relaciones del tenant",
    description=(
        "Lo necesita cualquier interfaz dirigida por metadatos: sin el grafo, "
        "una pantalla no puede ofrecer «ver los contactos de esta cuenta» sin "
        "que alguien lo haya programado a mano, que es justo lo que un modelo "
        "extensible viene a evitar."
    ),
)
def grafo_relaciones(db: DbDep, principal: AutenticadoDep) -> Any:
    return rel.grafo(db, principal.tenant_id)


@router.get(
    "/objetos/{objeto}/plan-de-borrado",
    response_model=list[dict],
    summary="Qué se rompe si borro este objeto",
    description=(
        "Hay que poder contestarlo **antes** de borrar. Lo que impide va "
        "primero: enterrarlo entre veinte cascadas hace que se lea el listado y "
        "se pase por alto justo lo que bloquea.\n\n"
        "Solo mira las relaciones **declaradas**: lo que un servicio arrastre "
        "por su cuenta —la cascada de la papelera, una clave ajena— no sale "
        "aquí, y se dice en vez de fingir que esta es la lista completa."
    ),
)
def plan_de_borrado(objeto: str, db: DbDep, principal: AutenticadoDep) -> Any:
    return [
        p.a_dict() for p in rel.plan_de_borrado(db, tenant_id=principal.tenant_id, objeto=objeto)
    ]


# ── Tipos de registro y gobierno del esquema ──────────────────────────────

router_gobierno = APIRouter(prefix="/metadata", tags=["metadatos"])


@router_gobierno.get(
    "/objetos/{nombre}/limites",
    response_model=dict,
    dependencies=[Depends(exige_permiso("metadata:read"))],
    summary="Cuánto esquema lleva este objeto y cuánto le queda",
    description=(
        "Campos activos, tope y porcentaje (CRM-00.04.01.09). El porcentaje no "
        "es cosmética: nadie sabe si 140 campos son muchos, y todo el mundo "
        "entiende «vas por el 70 %»."
    ),
)
def limites_objeto(nombre: str, db: DbDep, principal: AutenticadoDep) -> Any:
    from services.metadata.gobierno import limites

    objeto = _objeto(db, principal.tenant_id, nombre)
    return limites(db, principal.tenant_id, objeto.id)


@router_gobierno.get(
    "/objetos/{nombre}/tipos",
    response_model=list[dict],
    dependencies=[Depends(exige_permiso("metadata:read"))],
    summary="Tipos de registro del objeto",
    description=(
        "El mismo objeto con caras distintas (CRM-00.04.01.05): una cuenta de "
        "empresa y una pública no comparten campos ni listas, y modelarlas como "
        "dos objetos rompe los informes — «cuántos clientes tengo» deja de "
        "tener una respuesta."
    ),
)
def tipos_registro(nombre: str, db: DbDep, principal: AutenticadoDep) -> Any:
    from services.metadata.gobierno import TipoRegistro

    objeto = _objeto(db, principal.tenant_id, nombre)
    filas = (
        db.execute(
            select(TipoRegistro)
            .where(TipoRegistro.objeto_id == objeto.id, TipoRegistro.activo.is_(True))
            .order_by(TipoRegistro.clave)
        )
        .scalars()
        .all()
    )
    return [
        {
            "clave": f.clave,
            "nombre": f.nombre,
            "por_defecto": f.por_defecto,
            "campos_ocultos": list(f.campos_ocultos or []),
            "valores_lista": f.valores_lista,
            "layout": f.layout,
        }
        for f in filas
    ]


@router_gobierno.put(
    "/objetos/{nombre}/tipos/{clave}",
    response_model=dict,
    dependencies=[Depends(exige_permiso("metadata:write"))],
    summary="Crear o cambiar un tipo de registro",
)
def guardar_tipo_registro(
    nombre: str, clave: str, cuerpo: dict[str, Any], db: DbDep, principal: AutenticadoDep
) -> Any:
    from services.metadata.gobierno import guardar_tipo

    objeto = _objeto(db, principal.tenant_id, nombre)
    fila = guardar_tipo(
        db,
        tenant_id=principal.tenant_id,
        objeto_id=objeto.id,
        clave=clave,
        nombre=str(cuerpo.get("nombre") or clave),
        layout=cuerpo.get("layout"),
        valores_lista=cuerpo.get("valores_lista"),
        campos_ocultos=cuerpo.get("campos_ocultos"),
        por_defecto=bool(cuerpo.get("por_defecto")),
    )
    return {"clave": fila.clave, "nombre": fila.nombre, "por_defecto": fila.por_defecto}


@router_gobierno.post(
    "/objetos/{nombre}/renombrar-campo",
    response_model=dict,
    dependencies=[Depends(exige_permiso("metadata:write"))],
    summary="Empezar un renombrado compatible (CRM-00.04.01.10)",
    description=(
        "Los dos nombres funcionan a la vez y se cuenta cada uso del viejo. "
        "Renombrar de golpe rompe a quien manda el nombre viejo, y en un CRM "
        "con integraciones eso es siempre alguien."
    ),
)
def renombrar_campo(
    nombre: str, cuerpo: dict[str, Any], db: DbDep, principal: AutenticadoDep
) -> Any:
    from services.metadata.gobierno import anunciar_renombrado

    cambio = anunciar_renombrado(
        db,
        tenant_id=principal.tenant_id,
        objeto=nombre,
        desde=str(cuerpo.get("desde", "")),
        hasta=str(cuerpo.get("hasta", "")),
    )
    return {"desde": cambio.campo_origen, "hasta": cambio.campo_destino, "estado": cambio.estado}


@router_gobierno.post(
    "/objetos/{nombre}/retirar-campo-viejo",
    response_model=dict,
    dependencies=[Depends(exige_permiso("metadata:write"))],
    summary="Retirar el nombre viejo, si de verdad ha dejado de usarse",
    description=(
        "Se comprueba con el contador de usos y no con una fecha: el día que "
        "toca siempre hay alguien usándolo, y cortar entonces convierte una "
        "mejora planificada en una incidencia."
    ),
)
def retirar_campo_viejo(
    nombre: str, cuerpo: dict[str, Any], db: DbDep, principal: AutenticadoDep
) -> Any:
    from services.metadata.gobierno import completar_renombrado

    cambio = completar_renombrado(
        db,
        tenant_id=principal.tenant_id,
        objeto=nombre,
        desde=str(cuerpo.get("desde", "")),
        dias_sin_uso=int(cuerpo.get("dias_sin_uso", 30)),
    )
    return {"desde": cambio.campo_origen, "estado": cambio.estado, "usos": cambio.usos_del_viejo}


ROUTERS = [router, router_gobierno]


# ── Publicar, previsualizar, empaquetar y rastrear (CRM-00.04.03) ─────────


@router.get(
    "/objetos/{nombre}/previsualizar",
    dependencies=[Depends(exige_permiso("metadata:write"))],
    summary="Qué pasaría al publicar este esquema",
    description=(
        "Quien añade un campo obligatorio a un objeto con ochenta mil registros "
        "no sabe que los ochenta mil se quedan sin rellenar — y no lo sabe hasta "
        "que alguien intenta guardar uno viejo y no puede. Esto lo dice antes, "
        "que es la diferencia entre una decisión y una sorpresa.\n\n"
        "Cuando no se puede contar los registros afectados **se dice**: «no se ha "
        "podido contar» y «no afecta a nadie» son cosas distintas."
    ),
)
def previsualizar_esquema(nombre: str, db: DbDep, principal: AutenticadoDep) -> Any:
    from services.metadata import publicacion

    return publicacion.previsualizar(db, principal.tenant_id, nombre)


class Publicar(BaseModel):
    nota: str = Field("", max_length=1000)


@router.post(
    "/objetos/{nombre}/publicar",
    dependencies=[Depends(exige_permiso("metadata:write"))],
    summary="Publicar el esquema a todos los servicios",
    description=(
        "Publicar es un acto explícito porque configurar no lo es: mientras "
        "alguien define campos, el esquema a medias no puede viajar. Si viajara, "
        "el cliente vería su formulario cambiar mientras el consultor todavía "
        "está pensando, y una validación a medio escribir rechazaría altas "
        "buenas.\n\n"
        "A partir de aquí, cada servicio valida, filtra e indexa por esos campos "
        "sin que nadie escriba código."
    ),
)
def publicar_esquema(nombre: str, datos: Publicar, uow: UowDep, principal: AutenticadoDep) -> Any:
    from services.metadata import publicacion

    return publicacion.publicar(
        uow.db, principal.tenant_id, nombre, por=principal.id, nota=datos.nota
    )


@router.get(
    "/objetos/{nombre}/trazabilidad",
    dependencies=[Depends(exige_permiso("metadata:read"))],
    summary="Quién puso cada campo, cuándo y si se usa",
    description=(
        "Sin esto, la respuesta a «¿puedo quitar este campo?» es siempre «no lo "
        "sé», y por si acaso no se quita nada: es como un modelo de datos acaba "
        "con trescientos campos de los que nadie recuerda la mitad.\n\n"
        "El uso se cuenta al **escribir** y no al leer: leer mide quién mira, "
        "escribir mide si el campo se rellena."
    ),
)
def trazabilidad_esquema(nombre: str, db: DbDep, principal: AutenticadoDep) -> Any:
    from services.metadata import publicacion

    return publicacion.trazabilidad(db, principal.tenant_id, nombre)


@router.get(
    "/objetos/{nombre}/candidatos-columna",
    dependencies=[Depends(exige_permiso("metadata:write"))],
    summary="Campos que ya justifican una columna real",
    description=(
        "Materializar **no** es la norma: un `ALTER TABLE` en una tabla "
        "compartida por mil tenants los bloquea a todos, así que el JSONB con "
        "índice de expresión es el camino normal y esto es la excepción.\n\n"
        "La excepción se decide con una medida y no con una intuición: sin "
        "número, cada cliente que note su lista lenta pediría columna."
    ),
)
def candidatos_columna(nombre: str, db: DbDep, principal: AutenticadoDep) -> Any:
    from services.metadata import publicacion

    return publicacion.candidatos_a_materializar(db, principal.tenant_id, nombre)


@router.get(
    "/paquete",
    dependencies=[Depends(exige_permiso("metadata:read"))],
    summary="Exportar el esquema para llevarlo a otro entorno",
    description=(
        "Lo que se lleva es **la configuración, nunca los datos**. Un paquete "
        "que arrastrara registros convertiría una promoción a producción en una "
        "fuga: los datos de pruebas suelen ser copias anonimizadas a medias de "
        "clientes reales."
    ),
)
def exportar_paquete(
    db: DbDep,
    principal: AutenticadoDep,
    objeto: list[str] = Query(default=[], description="Vacío = todos"),
) -> Any:
    from services.metadata import publicacion

    return publicacion.exportar_paquete(db, principal.tenant_id, list(objeto) or None)


class InstalarPaquete(BaseModel):
    paquete: dict[str, Any]
    aplicar: bool = Field(
        False,
        description=(
            "Falso simula y no toca nada. Es el valor por defecto a propósito: "
            "un paquete es un cambio de modelo de datos en producción, y el "
            "error más caro es pulsar el botón creyendo que aún se estaba mirando"
        ),
    )


@router.post(
    "/paquete/instalar",
    dependencies=[Depends(exige_permiso("metadata:write"))],
    summary="Instalar un paquete de esquema",
    description=(
        "Lo que ya existe y difiere **no se pisa en silencio**: se informa y se "
        "deja fuera. Sobrescribir la configuración que alguien ajustó en "
        "producción con la de un entorno de pruebas es la forma habitual de "
        "perder dos semanas de trabajo de un consultor.\n\n"
        "Instalar deja la configuración puesta pero **no la publica**: eso es un "
        "paso aparte y deliberado."
    ),
)
def instalar_paquete(datos: InstalarPaquete, uow: UowDep, principal: AutenticadoDep) -> Any:
    from services.metadata import publicacion

    return publicacion.instalar_paquete(
        uow.db,
        principal.tenant_id,
        datos.paquete,
        simular=not datos.aplicar,
        por=principal.id,
    )


# ── Módulos verticales (CRM-00.04.04) ─────────────────────────────────────


class InstalarModulo(BaseModel):
    manifiesto: dict[str, Any]
    aplicar: bool = Field(
        False,
        description=(
            "Falso simula y no toca nada. Es el valor por defecto a propósito: "
            "instalar un módulo es un cambio de modelo de datos en producción, y "
            "el error más caro es pulsar el botón creyendo que aún se estaba "
            "mirando"
        ),
    )


@router.post(
    "/modulos/instalar",
    dependencies=[Depends(exige_permiso("metadata:write"))],
    summary="Instalar un módulo vertical",
    description=(
        "Un módulo es un paquete declarativo: objetos, campos, taxonomías, "
        "estados, flujos, permisos, plantillas, pantallas y conectores. Que el "
        "producto sea headless es lo que permite que sus pantallas salgan de la "
        "superficie declarada, sin escribir front.\n\n"
        "Todo lo que trae va **prefijado con su clave**: sin prefijo, dos módulos "
        "que llamen «envío» a cosas distintas se pisan, y el segundo que se "
        "instale rompe al primero.\n\n"
        "Las dependencias se comprueban **antes y todas juntas**: instalar, "
        "fallar, corregir y repetir cinco veces es la experiencia que hace que "
        "nadie quiera instalar módulos."
    ),
)
def instalar_modulo(datos: InstalarModulo, uow: UowDep, principal: AutenticadoDep) -> Any:
    from services.metadata import modulos

    return modulos.instalar(uow, datos.manifiesto, aplicar=datos.aplicar, por=principal.id)


class ActualizarModulo(BaseModel):
    manifiesto: dict[str, Any]
    aplicar: bool = False
    forzar_fijos: bool = Field(
        False,
        description=(
            "Pisa los elementos que el módulo gobierna y el cliente modificó. "
            "Hacerlo en silencio es cómo se pierde la confianza en las "
            "actualizaciones, así que hay que pedirlo"
        ),
    )


@router.post(
    "/modulos/actualizar",
    dependencies=[Depends(exige_permiso("metadata:write"))],
    summary="Actualizar un módulo respetando lo que el cliente ajustó",
    description=(
        "**Lo que decide si los módulos funcionan a los dos años es esto.** El "
        "cliente habrá tocado lo que el módulo trajo, y una actualización que "
        "pise sus cambios se deja de instalar — y entonces cada cliente se queda "
        "congelado en su versión.\n\n"
        "Tres reglas: lo **fijo** lo gobierna el módulo y se actualiza, avisando "
        "si el cliente lo tocó; lo **editable** que el cliente tocó no se toca "
        "nunca más, porque es suyo desde que lo tocó; lo **semilla** se crea una "
        "vez y ya está.\n\n"
        "Lo que la versión nueva ya no trae **no se borra**: se marca como "
        "huérfano y se dice. Borrarlo se llevaría por delante los registros que "
        "cuelgan de él sin que nadie lo hubiera decidido."
    ),
)
def actualizar_modulo(datos: ActualizarModulo, uow: UowDep, principal: AutenticadoDep) -> Any:
    from services.metadata import modulos

    return modulos.actualizar(
        uow,
        datos.manifiesto,
        aplicar=datos.aplicar,
        forzar_fijos=datos.forzar_fijos,
        por=principal.id,
    )


class DesinstalarModulo(BaseModel):
    aplicar: bool = False
    borrar_datos: bool = Field(
        False,
        description=(
            "Por defecto los registros se conservan. Un «desinstalado "
            "correctamente» que deja doscientos mil registros huérfanos es peor "
            "que no poder desinstalar"
        ),
    )


@router.post(
    "/modulos/{clave}/desinstalar",
    dependencies=[Depends(exige_permiso("metadata:write"))],
    summary="Quitar un módulo diciendo qué pasa con los datos",
    description=(
        "Se niega si otro módulo depende de este. Y se dice **cuántos registros "
        "hay por objeto**; cuando no se pueden contar, se dice que no se han "
        "podido contar en vez de suponer que son cero."
    ),
)
def desinstalar_modulo(
    clave: str, datos: DesinstalarModulo, uow: UowDep, principal: AutenticadoDep
) -> Any:
    from services.metadata import modulos

    return modulos.desinstalar(
        uow,
        clave,
        aplicar=datos.aplicar,
        borrar_datos=datos.borrar_datos,
        por=principal.id,
    )


@router.get(
    "/modulos",
    dependencies=[Depends(exige_permiso("metadata:read"))],
    summary="Módulos instalados en este tenant",
)
def listar_modulos(db: DbDep, principal: AutenticadoDep) -> Any:
    from services.metadata import modulos

    return modulos.instalados(db, principal.tenant_id)


@router.get(
    "/modulos/catalogo",
    dependencies=[Depends(exige_permiso("metadata:read"))],
    summary="Módulos disponibles para instalar",
    description=(
        "Se dice si está **firmado y revisado**, porque de eso depende si se "
        "instala a ciegas: un módulo sin firma puede haber sido modificado por "
        "cualquiera entre quien lo escribió y quien lo instala."
    ),
)
def catalogo_modulos(
    db: DbDep, principal: AutenticadoDep, sector: str = Query("", max_length=80)
) -> Any:
    from services.metadata import modulos

    return modulos.catalogo(db, sector=sector)


@router.get(
    "/modulos/{clave}/integridad",
    dependencies=[Depends(exige_permiso("metadata:read"))],
    summary="¿Lo instalado es lo que se publicó?",
    description=(
        "Compara la huella de lo instalado con la del catálogo. Cuando la versión "
        "ya no está publicada **se dice que no se puede comparar**, en vez de "
        "darlo por bueno."
    ),
)
def integridad_modulo(clave: str, db: DbDep, principal: AutenticadoDep) -> Any:
    from services.metadata import modulos

    return modulos.comprobar_integridad(db, principal.tenant_id, clave)


@router.get(
    "/modulos/{clave}/telemetria",
    dependencies=[Depends(exige_permiso("metadata:read"))],
    summary="Qué del módulo se usa de verdad",
    description=(
        "Dice si el módulo está bien recortado: uno con quince objetos de los que "
        "se usan dos no está completo, está inflado — y cada objeto que sobra es "
        "una entrada de menú que el usuario tiene que aprender a ignorar.\n\n"
        "Se dice cuándo el dato **todavía no es concluyente**: un módulo instalado "
        "ayer con todo sin usar no está inflado, está recién puesto."
    ),
)
def telemetria_modulo(clave: str, db: DbDep, principal: AutenticadoDep) -> Any:
    from services.metadata import modulos

    return modulos.telemetria(db, principal.tenant_id, clave)


@router.get(
    "/modulos/superficie",
    dependencies=[Depends(exige_permiso("metadata:read"))],
    summary="Pantallas que aportan los módulos instalados",
    description=(
        "El front oficial pinta lo que la superficie declara, así que un módulo "
        "añade pantallas **declarándolas**, sin escribir front.\n\n"
        "Solo las de los módulos instalados y activos: servir las de uno "
        "desinstalado dejaría un menú con entradas que llevan a un 404, que es "
        "peor que no tener la entrada."
    ),
)
def superficie_modulos(db: DbDep, principal: AutenticadoDep) -> Any:
    from services.metadata import modulos

    return modulos.superficie_de_modulos(db, principal.tenant_id)


# ── Contrato gRPC del objeto (CRM-00.02.01.03) ────────────────────────────


@router.get(
    "/objetos/{objeto}/contrato.proto",
    dependencies=[Depends(exige_permiso("metadata:read"))],
    summary="El `.proto` de este objeto, generado desde el esquema publicado",
    response_class=PlainTextResponse,
    description=(
        "Se **genera**, no se mantiene a mano: un `.proto` escrito al lado de la "
        "API dice algo distinto en cuanto alguien añade un campo, y el que se "
        "queda viejo es siempre el que menos gente mira.\n\n"
        "Los números de campo salen de los guardados al publicar el esquema, no "
        "de recalcularlos aquí: recalcular daría un fichero distinto según el "
        "orden en que vinieran los campos, y el integrador vería un contrato que "
        "«cambia solo».\n\n"
        "Lo que existió y se borró aparece como `reserved`. Es feo de leer y es "
        "la única forma de que su número no se reutilice — reutilizarlo mete el "
        "valor en el campo equivocado sin error, sin log y sin que nadie se "
        "entere."
    ),
)
def contrato_proto(objeto: str, db: DbDep, principal: AutenticadoDep) -> Any:
    from crmcore.metamodelo import campos_de

    from services.metadata import contrato_rpc

    salida = contrato_rpc.proto(
        db, principal.tenant_id, objeto=objeto, campos=campos_de(db, principal.tenant_id, objeto)
    )
    cabecera = ""
    if salida.get("aviso"):
        cabecera = f"// AVISO: {salida['aviso']}\n"
    return PlainTextResponse(cabecera + salida["contenido"], media_type="text/plain")


@router.get(
    "/objetos/{objeto}/contrato-rpc",
    dependencies=[Depends(exige_permiso("metadata:read"))],
    summary="Qué números tiene cada campo y qué se ha reservado",
    description=(
        "Para poder responder a «¿por qué este campo no llega?» sin abrir el "
        "`.proto`: dice qué número tiene cada uno, cuáles están reservados "
        "porque existieron, y qué campos **no salen** por el contrato y por qué."
    ),
)
def contrato_rpc_estado(objeto: str, db: DbDep, principal: AutenticadoDep) -> Any:
    from crmcore.metamodelo import campos_de

    from services.metadata import contrato_rpc

    campos = campos_de(db, principal.tenant_id, objeto)
    salida = contrato_rpc.proto(db, principal.tenant_id, objeto=objeto, campos=campos)
    return {
        "objeto": objeto,
        "numeros": salida["numeros"],
        "reservados": salida["reservados"],
        "guardado": salida["numeros_guardados"],
        "campos_que_no_salen": [
            {"clave": c.get("clave"), "porque": porque}
            for c in campos
            for tipo, porque in CAMPOS_QUE_NO_SALEN.items()
            if str(c.get("tipo") or "") == tipo
        ],
    }


# ── Diseñador visual de formularios y listas (CRM-00.04.03.01) ────────────


class DisenoIn(BaseModel):
    """Un diseño completo: secciones, con sus campos y sus condiciones."""

    nombre: str = Field(..., min_length=1, max_length=120)
    secciones: list[dict[str, Any]] = Field(default_factory=list)
    rol: str | None = None
    es_defecto: bool = False


class ColumnasIn(BaseModel):
    columnas: list[dict[str, Any]] = Field(default_factory=list)


@router.post(
    "/objetos/{objeto}/diseno",
    dependencies=[Depends(exige_permiso("metadata:write"))],
    summary="Guardar un diseño de formulario",
    description=(
        "Arrastrar campos, secciones, pestañas y condiciones de visibilidad, sin "
        "escribir nada.\n\n"
        "**Se rechaza el diseño que está mal**, que es lo que separa esto de un "
        "editor de JSON con ratón: un campo que no existe, el mismo campo en dos "
        "secciones o un obligatorio sin sitio no dan error al guardar y se "
        "descubren semanas después, cuando un usuario dice «es que ese campo no "
        "está».\n\n"
        "Se devuelven **todos** los problemas de una vez: descubrirlos de uno en "
        "uno, con un intento de guardar entre cada dos, es lo que hace que la "
        "gente deje de usar el diseñador."
    ),
)
def guardar_diseno(objeto: str, cuerpo: DisenoIn, uow: UowDep) -> Any:
    from services.metadata import disenador
    from services.metadata.publicacion import esquema_actual

    return disenador.guardar(
        uow,
        objeto=objeto,
        nombre=cuerpo.nombre,
        secciones=cuerpo.secciones,
        campos_del_esquema=esquema_actual(uow.db, uow.tenant_id, objeto),
        rol=cuerpo.rol,
        es_defecto=cuerpo.es_defecto,
    )


@router.post(
    "/objetos/{objeto}/diseno/comprobar",
    dependencies=[Depends(exige_permiso("metadata:read"))],
    summary="Qué le pasa a este diseño, sin guardarlo",
    description=(
        "Para que el diseñador pueda avisar **mientras** se arrastra, en vez de "
        "al pulsar guardar. Devuelve los problemas y los avisos por separado: un "
        "problema impide guardar y un aviso solo dice que eso se rellena mal."
    ),
)
def comprobar_diseno(objeto: str, cuerpo: DisenoIn, db: DbDep, principal: AutenticadoDep) -> Any:
    from services.metadata import disenador
    from services.metadata.publicacion import esquema_actual

    return disenador.validar_layout(
        secciones=cuerpo.secciones,
        campos_del_esquema=esquema_actual(db, principal.tenant_id, objeto),
    )


@router.get(
    "/objetos/{objeto}/diseno",
    dependencies=[Depends(exige_permiso("metadata:read"))],
    summary="Qué diseño le toca a este usuario, y por qué ese",
    description=(
        "El «por qué» no es adorno: con varios diseños por rol, la pregunta que "
        "llega a soporte es siempre «¿por qué yo veo otra pantalla?», y sin esto "
        "hay que mirarlo en la base de datos."
    ),
)
def diseno_efectivo(
    objeto: str, db: DbDep, principal: AutenticadoDep, rol: str | None = Query(None)
) -> Any:
    from services.metadata import disenador

    return disenador.layout_efectivo(db, principal.tenant_id, objeto=objeto, rol=rol)


@router.post(
    "/objetos/{objeto}/lista/comprobar",
    dependencies=[Depends(exige_permiso("metadata:read"))],
    summary="Comprobar las columnas de una vista de lista",
    description=(
        "Dos cosas que no dan error y estropean la lista: una columna sobre un "
        "campo que no existe sale vacía en todas las filas —y se lee como «ningún "
        "cliente tiene ese dato»—, y ordenar por un texto largo o un JSON obliga "
        "a recorrer la tabla entera en cada carga. Con mil filas no se nota; con "
        "un millón, la lista deja de abrirse y nadie relaciona una cosa con la "
        "otra."
    ),
)
def comprobar_lista(objeto: str, cuerpo: ColumnasIn, db: DbDep, principal: AutenticadoDep) -> Any:
    from services.metadata import disenador
    from services.metadata.publicacion import esquema_actual

    return disenador.columnas_de_lista(
        columnas=cuerpo.columnas,
        campos_del_esquema=esquema_actual(db, principal.tenant_id, objeto),
    )


# ── Contexto semántico de los campos personalizados (CRM-00.04.03.07) ─────


class CampoSemanticoIn(BaseModel):
    clave: str
    etiqueta: str
    tipo: str
    descripcion: str
    rol: str
    valores: list[dict[str, Any]] = Field(default_factory=list)
    sensible: bool = False
    explotable: bool = True


@router.post(
    "/objetos/{objeto}/semantica",
    dependencies=[Depends(exige_permiso("metadata:write"))],
    summary="Declarar qué significa un campo personalizado",
    description=(
        "Un tenant crea `cmp_2`, de tipo lista, con valores `A`, `B` y `C`. Para "
        "el CRM es perfecto; para cualquier cosa que tenga que **razonar** sobre "
        "esos datos es basura: no sabe qué es `cmp_2` ni qué significa `B`.\n\n"
        "Se exige que la descripción diga algo más que la etiqueta. «Segmento: "
        "segmento» es la forma más común de rellenar esto y deja el catálogo "
        "igual de inútil, con la diferencia de que ahora parece completo.\n\n"
        "Y lo sensible se marca para que quede fuera: un campo con el diagnóstico "
        "de un paciente no entra en un contexto que se manda a un proveedor de "
        "inferencia, y quien lo creó rara vez lo piensa."
    ),
)
def declarar_semantica(objeto: str, cuerpo: CampoSemanticoIn, principal: AutenticadoDep) -> Any:
    from services.metadata import semantica

    return semantica.describir_campo(
        clave=cuerpo.clave,
        etiqueta=cuerpo.etiqueta,
        tipo=cuerpo.tipo,
        descripcion=cuerpo.descripcion,
        rol=cuerpo.rol,
        valores=cuerpo.valores,
        sensible=cuerpo.sensible,
        explotable=cuerpo.explotable,
    )


@router.get(
    "/objetos/{objeto}/semantica",
    dependencies=[Depends(exige_permiso("metadata:read"))],
    summary="El diccionario que se le pasa a lo que razona sobre este objeto",
    description=(
        "Va **sin los campos sensibles y sin los internos**, y dice cuántos ha "
        "dejado fuera: un contexto recortado en silencio hace que el asistente "
        "conteste «no hay ningún campo de eso» cuando lo que pasa es que no se lo "
        "hemos enseñado.\n\n"
        "Y devuelve la **cobertura**: con el 30 % de los campos descritos, la IA "
        "entiende el 30 %, y la diferencia entre eso y lo que la gente cree que "
        "compró es la razón de la mayoría de los proyectos de IA decepcionantes."
    ),
)
def contexto_semantico(objeto: str, db: DbDep, principal: AutenticadoDep) -> Any:
    from crmcore.metamodelo import campos_de

    from services.metadata import semantica

    campos = campos_de(db, principal.tenant_id, objeto)
    return {
        **semantica.contexto_semantico(objeto=objeto, campos=campos),
        "cobertura": semantica.cobertura(campos=campos),
    }
