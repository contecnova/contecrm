"""API del maestro y el gobierno del proveedor (CRM-09.01.01.01 a .06, .10).

El proveedor no tiene recurso propio de alta: **es una cuenta**. Aquí solo está lo
que se le añade encima —homologación, papeles, contactos y riesgo—, que es lo que
decide si se le puede encargar algo hoy.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from crmcore.errors import NoEncontrado
from crmcore.http.deps import (
    AutenticadoDep,
    DbDep,
    UowDep,
    exige_permiso,
    proyectar_para,
)
from crmcore.http.listados import declarar_recurso
from crmcore.http.pagination import PaginaDeListado
from crmcore.http.portal_deps import PortalDep
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from services.party import proveedores as prv
from services.party.esquemas import ActualizarCuenta, CrearCuenta, CuentaOut

router_proveedores = APIRouter(prefix="/proveedores", tags=["proveedores"])
declarar_recurso(router_proveedores, "proveedor")


class HomologarIn(BaseModel):
    categoria: str = Field(..., min_length=1, max_length=80)
    requisitos: list[dict[str, Any]] = Field(default_factory=list)
    valida_hasta: date | None = None


class EstadoDocumental(BaseModel):
    """Los papeles de un proveedor: la lista y lo que hay que mirar.

    Se declara como modelo y no como `dict` sueltos porque la superficie mira el
    tipo de salida para saber si una operación devuelve **muchos**: la ficha
    solo pinta como panel lo que es una lista, y con un `dict` anónimo este
    panel se quedaba fuera — un proveedor sin sus papeles a la vista es
    precisamente lo que había que arreglar.
    """

    items: list[dict[str, Any]] = Field(default_factory=list)
    documentos: int = 0
    vencidos: list[dict[str, Any]] = Field(default_factory=list)
    por_vencer: list[dict[str, Any]] = Field(default_factory=list)
    sin_fecha_de_caducidad: list[str] = Field(default_factory=list)
    bloqueado: bool = False
    porque: str = ""
    medible: bool = False
    aviso: str = ""


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


# ── Lo que un proveedor ve de sí mismo, desde el portal ───────────────────
#
# Quien llama aquí no es un empleado: es el proveedor, con la sesión del portal.
# Por eso no hay `exige_permiso` —su token no lleva permisos, a propósito— y la
# cuenta no viene en la ruta sino **firmada en el token**: aceptarla de quien
# llama dejaría a un proveedor mirar los papeles de otro, que es la fuga más
# fácil de un portal.
#
# Existe porque perseguir los certificados caducados de los proveedores es
# trabajo de alguien todos los meses, y el único que puede resolverlo es el
# proveedor. Enseñárselo a él convierte una lista de reclamaciones en algo que
# se arregla solo.


@router_proveedores.get(
    "/mi/resumen",
    response_model=dict,
    summary="Mi ficha de proveedor",
    description=(
        "Dice también si esta empresa **es** proveedora: el portal lo pregunta "
        "para saber si enseñar esta parte, y así no tiene que adivinarlo ni se "
        "le enseña una sección vacía a quien solo es cliente."
    ),
)
def mi_resumen_proveedor(db: DbDep, sesion: PortalDep) -> Any:
    from services.party.modelos import Cuenta

    cuenta = db.get(Cuenta, sesion.exigir_cuenta())
    es_proveedor = cuenta is not None and "proveedor" in (cuenta.roles or [])
    return {
        "es_proveedor": es_proveedor,
        "nombre": cuenta.nombre if cuenta else "",
    }


@router_proveedores.get(
    "/mi/documentos",
    response_model=EstadoDocumental,
    summary="Mis papeles y cuándo caducan",
)
def mis_documentos(db: DbDep, sesion: PortalDep) -> Any:
    return prv.estado_documental(db, sesion.tenant_id, cuenta_id=sesion.exigir_cuenta())


@router_proveedores.post(
    "/mi/documentos",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
    summary="Subir el papel renovado",
    description=(
        "El proveedor renueva lo suyo sin que nadie se lo pida dos veces. Es lo "
        "que convierte la lista de certificados caducados en algo que se "
        "resuelve solo: hoy la única forma de actualizarlo es que alguien de "
        "dentro llame, reciba el papel por correo y lo registre a mano."
    ),
)
def subir_mi_documento(cuerpo: DocumentoIn, uow: UowDep, sesion: PortalDep) -> Any:
    fila = prv.registrar_documento(
        uow,
        cuenta_id=sesion.exigir_cuenta(),
        clave=cuerpo.clave,
        nombre=cuerpo.nombre,
        referencia=cuerpo.referencia,
        valido_hasta=cuerpo.valido_hasta,
        valido_desde=cuerpo.valido_desde,
    )
    return {
        "id": str(fila.id),
        "clave": fila.clave,
        "valido_hasta": fila.valido_hasta.isoformat() if fila.valido_hasta else None,
    }


@router_proveedores.get(
    "/mi/homologaciones",
    response_model=list[dict],
    summary="Para qué estoy homologado y hasta cuándo",
)
def mis_homologaciones(db: DbDep, sesion: PortalDep) -> Any:
    from sqlalchemy import select

    filas = (
        db.execute(
            select(prv.Homologacion).where(prv.Homologacion.cuenta_id == sesion.exigir_cuenta())
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(f.id),
            "categoria": f.categoria,
            "estado": f.estado,
            "valida_hasta": f.valida_hasta.isoformat() if f.valida_hasta else None,
        }
        for f in filas
    ]


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
    response_model=EstadoDocumental,
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


@router_proveedores.get(
    "/{cuenta_id}/contactos",
    response_model=list[dict],
    dependencies=[Depends(exige_permiso("party:read"))],
    summary="Los contactos declarados de este proveedor",
    description=(
        "Se podían dar de alta y no se podían leer: la pantalla enseñaba «a "
        "quién llamo» —que devuelve solo el de escalado— y no había forma de "
        "ver quién más consta ni de comprobar qué falta."
    ),
)
def listar_contactos(cuenta_id: UUID, db: DbDep, _: AutenticadoDep) -> Any:
    from sqlalchemy import select

    filas = (
        db.execute(
            select(prv.ContactoProveedor)
            .where(prv.ContactoProveedor.cuenta_id == cuenta_id)
            .order_by(prv.ContactoProveedor.funcion)
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(f.id),
            "funcion": f.funcion,
            "nombre": f.nombre,
            "email": f.email,
            "telefono": f.telefono,
            "fuera_de_horario": f.fuera_de_horario,
        }
        for f in filas
    ]


@router_proveedores.get(
    "/{cuenta_id}/homologaciones",
    response_model=list[dict],
    dependencies=[Depends(exige_permiso("party:read"))],
    summary="En qué categorías está homologado, y hasta cuándo",
    description=(
        "Se podía homologar por categoría y consultarla de una en una, sabiendo "
        "ya el nombre de la categoría. Quien abre la ficha no lo sabe: lo que "
        "necesita es la lista."
    ),
)
def listar_homologaciones(cuenta_id: UUID, db: DbDep, _: AutenticadoDep) -> Any:
    from sqlalchemy import select

    filas = (
        db.execute(
            select(prv.Homologacion)
            .where(prv.Homologacion.cuenta_id == cuenta_id)
            .order_by(prv.Homologacion.categoria)
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(f.id),
            "categoria": f.categoria,
            "estado": f.estado,
            "valida_hasta": f.valida_hasta.isoformat() if f.valida_hasta else None,
            "requisitos": f.requisitos,
        }
        for f in filas
    ]


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
    response_model=PaginaDeListado,
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
    from crmcore.http.pagination import (
        ParametrosPagina,
        aplicar_orden_y_cursor,
        construir_pagina,
    )
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


@router_proveedores.post(
    "",
    response_model=CuentaOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("party:write"))],
    summary="Dar de alta un proveedor",
    description=(
        "Crea la cuenta **ya con el rol de proveedor**, con la misma "
        "comprobación de duplicados que un cliente: es el mismo maestro.\n\n"
        "Existía la forma larga —crear la cuenta por un lado y marcarle el rol "
        "por otro— y no la corta, así que desde la pantalla de proveedores no se "
        "podía dar de alta ninguno: había que saber que un proveedor es una "
        "cuenta, irse a cuentas, crearla y volver. Quien no lo sabía veía una "
        "lista que no dejaba hacer nada."
    ),
)
def crear_proveedor(datos: CrearCuenta, uow: UowDep) -> Any:
    from services.party import servicio as svc

    payload = datos.model_dump(exclude={"identificadores", "forzar", "roles"})
    # El rol se **suma** a los que pida quien crea: la misma empresa puede ser
    # cliente de una división y proveedor de otra. Si no pide ninguno no se le
    # cuela `cliente` —que es el valor por defecto del esquema de cuentas—,
    # porque dar de alta un proveedor no es dar de alta un cliente.
    pedidos = set(datos.roles) if "roles" in datos.model_fields_set else set()
    roles = sorted(pedidos | {"proveedor"})
    return svc.crear_cuenta(
        uow,
        identificadores=[i.model_dump() for i in datos.identificadores],
        forzar=datos.forzar,
        roles=roles,
        **payload,
    )


def _proveedor(db: Any, cuenta_id: UUID, *, accion: str) -> Any:
    """La cuenta con rol de proveedor, o 404 — **pasando por las políticas**.

    Por el punto de decisión y no con un `db.get` a secas: es el único sitio en
    el que se resuelve quién puede ver qué, y un cargador que se lo salta abre
    una puerta lateral a un registro que la ficha de cuentas sí protege. Hay un
    gate que lo comprueba, y tenía razón.
    """
    from crmcore.authz.decision import exigir

    from services.party.modelos import Cuenta

    cuenta = db.get(Cuenta, cuenta_id)
    if cuenta is None or cuenta.deleted_at is not None or "proveedor" not in (cuenta.roles or []):
        raise NoEncontrado(
            "No hay ningún proveedor con ese identificador",
            error_code="party.proveedor_no_encontrado",
        )
    exigir(db, objeto="cuenta", accion=accion, registro=cuenta)
    return cuenta


@router_proveedores.get(
    "/{cuenta_id}",
    response_model=CuentaOut,
    dependencies=[Depends(exige_permiso("party:read"))],
    summary="Ficha de un proveedor",
    description=(
        "La misma cuenta, vista desde su rol de proveedor. Hace falta para "
        "poder **abrir** una fila del listado: sin ella, homologar, subir un "
        "certificado o ver a quién llamar no se alcanzaban desde ninguna "
        "pantalla, porque todo eso cuelga del proveedor y al proveedor no se "
        "entraba."
    ),
)
def ver_proveedor(cuenta_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    from services.party.modelos import Cuenta

    cuenta = _proveedor(db, cuenta_id, accion="leer")
    return proyectar_para(principal, db, objeto="cuenta", modelo=Cuenta)(cuenta)


@router_proveedores.patch(
    "/{cuenta_id}",
    response_model=CuentaOut,
    dependencies=[Depends(exige_permiso("party:write"))],
    summary="Actualizar un proveedor",
    description=(
        "Es la cuenta, así que cambia lo mismo y deja el mismo historial campo "
        "a campo. Está aquí para que la ficha del proveedor se edite donde se "
        "abre, y no obligue a irse a cuentas sabiendo que un proveedor es una."
    ),
)
def actualizar_proveedor(cuenta_id: UUID, datos: ActualizarCuenta, uow: UowDep) -> Any:
    from services.party import servicio as svc

    _proveedor(uow.db, cuenta_id, accion="escribir")
    return svc.actualizar_cuenta(
        uow, cuenta_id, datos.model_dump(exclude_unset=True, exclude_none=True)
    )


@router_proveedores.delete(
    "/{cuenta_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(exige_permiso("party:write"))],
    summary="Enviar un proveedor a la papelera",
    description=(
        "Es la cuenta, así que es el mismo borrado lógico y la misma papelera. "
        "Está aquí porque donde se abre una ficha tiene que poder borrarse: si "
        "no, hay que saber que un proveedor es una cuenta e irse a cuentas."
    ),
)
def borrar_proveedor(cuenta_id: UUID, uow: UowDep, principal: AutenticadoDep) -> None:
    from crmcore.datos import integridad, papelera

    cuenta = _proveedor(uow.db, cuenta_id, accion="escribir")
    integridad.exigir_sin_dependencias(uow.db, cuenta, objeto="cuenta")
    papelera.borrar(uow.db, cuenta, objeto="cuenta", etiqueta=cuenta.nombre, por=principal.id)


ROUTERS_PROVEEDORES = [router_proveedores]
