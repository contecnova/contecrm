"""API del canal indirecto (CRM-03.04.01).

Dos familias de rutas que parecen la misma y no lo son:

  * `/partners/**` las usa el fabricante: dar de alta, certificar, decidir
    registros, fijar acuerdos.
  * `/portal-partner/**` las usa el partner. Todo lo que se sirve ahí sale
    **acotado por el compartimento del token** (CRM-03.04.01.03) y nunca por un
    identificador que venga en la petición.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from crmcore.authz.estanco import aplicar_estanco, exigir_propio
from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from crmcore.http.listados import montar_ficha
from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from services.sales import partners as prt

router = APIRouter(prefix="/partners", tags=["partners"])
router_niveles = APIRouter(prefix="/niveles-partner", tags=["partners"])
router_registros = APIRouter(prefix="/registros-oportunidad", tags=["partners"])
router_portal = APIRouter(prefix="/portal-partner", tags=["partners"])


class CrearNivel(BaseModel):
    clave: str = Field(..., min_length=1, max_length=60)
    nombre: str = Field(..., min_length=1, max_length=200)
    orden: int = 0
    facturacion_minima: Decimal = Decimal(0)
    certificaciones_exigidas: list[str] = Field(default_factory=list)
    descuento_extra_pct: Decimal = Decimal(0)
    dias_proteccion: int | None = Field(
        None, description="Protección del registro para este nivel. Nulo = la del programa"
    )


class CrearPartner(BaseModel):
    clave: str = Field(..., min_length=1, max_length=80)
    nombre: str = Field(..., min_length=1, max_length=200)
    tipo: str = ""
    canal: str = Field("", description="Canal con el que entra en el motor de precios")
    pais: str | None = None
    cuenta_id: UUID | None = None
    nivel_id: UUID | None = None
    responsable_id: UUID | None = None
    pasos_onboarding: list[str] = Field(default_factory=list)


class Certificar(BaseModel):
    clave: str = Field(..., min_length=1, max_length=80)
    nombre: str = ""
    persona: str = ""
    obtenida_el: date | None = None
    caduca_el: date | None = None
    evidencia_url: str = ""


class Activar(BaseModel):
    facturacion: Decimal = Decimal(0)
    forzar: bool = False
    motivo: str = ""


class CambiarEstado(BaseModel):
    estado: str
    motivo: str = ""


class DarAcceso(BaseModel):
    email: str
    nombre: str = ""
    nivel: str = "comercial"


class Registrar(BaseModel):
    partner_id: UUID | None = Field(
        None,
        description=(
            "Solo lo usa el fabricante. Desde el portal se ignora: el partner sale "
            "del token, no de la petición"
        ),
    )
    cliente_nombre: str = Field(..., min_length=1, max_length=200)
    nif: str | None = None
    dominio: str | None = None
    cuenta_id: UUID | None = None
    contacto: dict[str, Any] = Field(default_factory=dict)
    importe_estimado: Decimal = Decimal(0)
    moneda: str = "EUR"
    cierre_estimado: date | None = None
    descripcion: str = ""


class Decidir(BaseModel):
    aprobar: bool
    motivo: str = ""
    dias_proteccion: int | None = None


class Acuerdo(BaseModel):
    partner_id: UUID | None = None
    nivel_id: UUID | None = None
    lista_precio_id: UUID | None = None
    descuento_maximo_pct: Decimal = Decimal(0)
    margen_minimo_pct: Decimal | None = None
    desde: date | None = None
    hasta: date | None = None


class Plan(BaseModel):
    nombre: str
    desde: date
    hasta: date
    objetivos: list[dict[str, Any]] = Field(default_factory=list)
    acciones: list[dict[str, Any]] = Field(default_factory=list)


class Revision(BaseModel):
    fecha: date | None = None
    logrado: dict[str, Any] = Field(default_factory=dict)
    notas: str = ""


class Rendimiento(BaseModel):
    desde: date
    hasta: date
    cerrado_por_partner: dict[str, Decimal] = Field(default_factory=dict)


# ── Niveles y alta ────────────────────────────────────────────────────────


@router_niveles.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("partner:write"))],
    summary="Definir un nivel del programa de canal",
    description=(
        "Los niveles son **filas**, no una lista en el código: cada fabricante "
        "tiene los suyos y con tres fijos el primer cliente pide el cuarto."
    ),
)
def crear_nivel(datos: CrearNivel, uow: UowDep) -> Any:
    fila = prt.crear_nivel(uow, **datos.model_dump())
    return {"id": str(fila.id), "clave": fila.clave, "orden": fila.orden}


@router_niveles.get(
    "",
    dependencies=[Depends(exige_permiso("partner:read"))],
    summary="Niveles del programa",
)
def listar_niveles(db: DbDep, principal: AutenticadoDep) -> Any:
    filas = (
        db.execute(
            select(prt.NivelPartner)
            .where(prt.NivelPartner.tenant_id == principal.tenant_id)
            .order_by(prt.NivelPartner.orden)
        )
        .scalars()
        .all()
    )
    return {
        "niveles": [
            {
                "id": str(f.id),
                "clave": f.clave,
                "nombre": f.nombre,
                "orden": f.orden,
                "facturacion_minima": str(f.facturacion_minima),
                "certificaciones_exigidas": f.certificaciones_exigidas,
                "descuento_extra_pct": str(f.descuento_extra_pct),
                "dias_proteccion": f.dias_proteccion,
            }
            for f in filas
        ]
    }


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("partner:write"))],
    summary="Dar de alta un partner",
    description=(
        "Nace en `alta`, **no activo**: un partner que entra activo registra "
        "oportunidades antes de haber firmado nada."
    ),
)
def crear_partner(datos: CrearPartner, uow: UowDep) -> Any:
    fila = prt.crear_partner(uow, **datos.model_dump())
    return {"id": str(fila.id), "clave": fila.clave, "estado": fila.estado}


@router.get(
    "",
    dependencies=[Depends(exige_permiso("partner:read"))],
    summary="Partners del tenant",
)
def listar_partners(
    db: DbDep,
    principal: AutenticadoDep,
    estado: str | None = Query(None),
    limite: int = Query(50, ge=1, le=200),
) -> Any:
    consulta = select(prt.Partner).where(prt.Partner.tenant_id == principal.tenant_id)
    if estado:
        consulta = consulta.where(prt.Partner.estado == estado)
    # Un partner que entrara aquí solo se vería a sí mismo, aunque la ruta sea la
    # del fabricante: el compartimento manda sobre el permiso.
    consulta = aplicar_estanco(consulta, prt.Partner.id, principal=principal, tipo="partner")
    filas = db.execute(consulta.order_by(prt.Partner.nombre).limit(limite)).scalars().all()
    return {
        "partners": [
            {
                "id": str(f.id),
                "clave": f.clave,
                "nombre": f.nombre,
                "tipo": f.tipo,
                "canal": f.canal,
                "estado": f.estado,
                "nivel_id": str(f.nivel_id) if f.nivel_id else None,
                "pendientes_alta": [
                    p.get("paso") for p in (f.onboarding or []) if not p.get("hecho")
                ],
            }
            for f in filas
        ]
    }


@router.post(
    "/{partner_id}/pasos/{paso}",
    dependencies=[Depends(exige_permiso("partner:write"))],
    summary="Marcar hecho un paso del alta",
)
def completar_paso(partner_id: UUID, paso: str, uow: UowDep) -> Any:
    fila = prt.completar_paso(uow, partner_id, paso)
    return {"id": str(fila.id), "onboarding": fila.onboarding}


@router.post(
    "/{partner_id}/certificaciones",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("partner:write"))],
    summary="Registrar una certificación",
    description=(
        "Con caducidad: una certificación sin vencimiento es una casilla marcada "
        "hace tres años por alguien que ya no trabaja allí."
    ),
)
def certificar(partner_id: UUID, datos: Certificar, uow: UowDep) -> Any:
    fila = prt.certificar(uow, partner_id, **datos.model_dump())
    return {"id": str(fila.id), "clave": fila.clave, "caduca_el": str(fila.caduca_el or "")}


@router.get(
    "/certificaciones/por-caducar",
    dependencies=[Depends(exige_permiso("partner:read"))],
    summary="Certificaciones que se caen pronto",
)
def por_caducar(db: DbDep, principal: AutenticadoDep, dias: int | None = Query(None)) -> Any:
    return prt.certificaciones_por_caducar(db, principal.tenant_id, dias=dias)


@router.post(
    "/{partner_id}/activar",
    dependencies=[Depends(exige_permiso("partner:write"))],
    summary="Activar un partner",
    description=(
        "Comprueba pasos y nivel. Se puede **forzar con motivo**: sin esa puerta, "
        "lo que se hace es marcar como hecho un trámite que no se hizo."
    ),
)
def activar(partner_id: UUID, datos: Activar, uow: UowDep) -> Any:
    fila = prt.activar(uow, partner_id, **datos.model_dump())
    return {"id": str(fila.id), "estado": fila.estado, "motivo": fila.motivo_estado}


@router.post(
    "/{partner_id}/estado",
    dependencies=[Depends(exige_permiso("partner:write"))],
    summary="Suspender, reactivar o dar de baja",
)
def cambiar_estado(partner_id: UUID, datos: CambiarEstado, uow: UowDep) -> Any:
    fila = prt.cambiar_estado(uow, partner_id, **datos.model_dump())
    return {"id": str(fila.id), "estado": fila.estado}


@router.post(
    "/{partner_id}/accesos",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("partner:write"))],
    summary="Dar acceso al portal a una persona del partner",
)
def dar_acceso(partner_id: UUID, datos: DarAcceso, uow: UowDep) -> Any:
    fila = prt.dar_acceso(uow, partner_id, **datos.model_dump())
    return {"id": str(fila.id), "email": fila.email, "nivel": fila.nivel}


@router.delete(
    "/accesos/{acceso_id}",
    dependencies=[Depends(exige_permiso("partner:write"))],
    summary="Revocar el acceso al portal",
)
def revocar_acceso(acceso_id: UUID, uow: UowDep, motivo: str = Query("")) -> Any:
    fila = prt.revocar_acceso(uow, acceso_id, motivo=motivo)
    return {"id": str(fila.id), "activo": fila.activo}


# ── Registro de oportunidad ───────────────────────────────────────────────


@router_registros.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("partner:write"))],
    summary="Registrar una oportunidad de canal",
    description=(
        "Exige NIF, dominio o cuenta: el nombre no identifica a nadie. Si ya hay un "
        "registro vivo, este se guarda igual marcado en conflicto, y **no se dice de "
        "quién es el otro**."
    ),
)
def registrar(datos: Registrar, uow: UowDep, principal: AutenticadoDep) -> Any:
    from crmcore.authz.estanco import dueno_forzado

    partner_id = dueno_forzado(principal, tipo="partner", pedido=datos.partner_id)
    if partner_id is None:
        from crmcore.errors import ErrorValidacion

        raise ErrorValidacion("Falta el partner del registro.", error_code="partners.sin_partner")
    cuerpo = datos.model_dump()
    cuerpo.pop("partner_id")
    fila, aviso = prt.registrar_oportunidad(uow, partner_id=partner_id, **cuerpo)
    return {"id": str(fila.id), "estado": fila.estado, **aviso}


@router_registros.get(
    "",
    dependencies=[Depends(exige_permiso("partner:read"))],
    summary="Registros de oportunidad",
)
def listar_registros(
    db: DbDep,
    principal: AutenticadoDep,
    estado: str | None = Query(None),
    limite: int = Query(50, ge=1, le=200),
) -> Any:
    consulta = select(prt.RegistroOportunidad).where(
        prt.RegistroOportunidad.tenant_id == principal.tenant_id
    )
    if estado:
        consulta = consulta.where(prt.RegistroOportunidad.estado == estado)
    consulta = aplicar_estanco(
        consulta, prt.RegistroOportunidad.partner_id, principal=principal, tipo="partner"
    )
    filas = (
        db.execute(consulta.order_by(prt.RegistroOportunidad.created_at.desc()).limit(limite))
        .scalars()
        .all()
    )
    return {
        "registros": [
            {
                "id": str(f.id),
                "cliente": f.cliente_nombre,
                "estado": f.estado,
                "importe_estimado": str(f.importe_estimado),
                "protegido_hasta": str(f.protegido_hasta) if f.protegido_hasta else None,
                "motivo": f.motivo,
                # El conflicto se dice; con quién, no.
                "en_conflicto": f.conflicto_con is not None,
            }
            for f in filas
        ]
    }


@router_registros.post(
    "/{registro_id}/decidir",
    dependencies=[Depends(exige_permiso("partner:write"))],
    summary="Aprobar o rechazar un registro",
    description=(
        "Aprobar es **fijar una fecha**; rechazar exige motivo. Una protección "
        "«mientras trabaje el cliente» no se puede comprobar."
    ),
)
def decidir(registro_id: UUID, datos: Decidir, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = prt.decidir_registro(uow, registro_id, decidido_por=principal.id, **datos.model_dump())
    return {
        "id": str(fila.id),
        "estado": fila.estado,
        "protegido_hasta": str(fila.protegido_hasta) if fila.protegido_hasta else None,
    }


@router_registros.post(
    "/caducar",
    dependencies=[Depends(exige_permiso("partner:write"))],
    summary="Cerrar las protecciones vencidas",
)
def caducar(uow: UowDep) -> Any:
    return prt.caducar_protecciones(uow)


@router_registros.post(
    "/{registro_id}/oportunidad/{oportunidad_id}",
    dependencies=[Depends(exige_permiso("partner:write"))],
    summary="Enlazar el registro con la oportunidad que salió de él",
)
def vincular(registro_id: UUID, oportunidad_id: UUID, uow: UowDep) -> Any:
    fila = prt.vincular_oportunidad(uow, registro_id, oportunidad_id=oportunidad_id)
    return {"id": str(fila.id), "estado": fila.estado}


# ── Acuerdos, precios y rendimiento ───────────────────────────────────────


@router.post(
    "/acuerdos",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("partner:write"))],
    summary="Fijar un acuerdo de canal",
)
def crear_acuerdo(datos: Acuerdo, uow: UowDep) -> Any:
    fila = prt.AcuerdoCanal(tenant_id=uow.tenant_id, **datos.model_dump())
    uow.db.add(fila)
    uow.db.flush()
    return {"id": str(fila.id)}


@router.get(
    "/{partner_id}/precio/{producto_id}",
    dependencies=[Depends(exige_permiso("partner:read"))],
    summary="Precio de un producto para un partner",
    description=(
        "Delega en el motor de precios con el canal del partner y añade el "
        "descuento de nivel y el **suelo** por debajo del cual hace falta aprobar."
    ),
)
def precio(
    partner_id: UUID,
    producto_id: UUID,
    db: DbDep,
    principal: AutenticadoDep,
    cantidad: Decimal = Query(Decimal(1)),
    cuenta_id: UUID | None = Query(None),
    moneda: str = Query(""),
) -> Any:
    return prt.precio_para_partner(
        db,
        principal.tenant_id,
        partner_id=partner_id,
        producto_id=producto_id,
        cantidad=cantidad,
        cuenta_id=cuenta_id,
        moneda=moneda,
    )


@router.post(
    "/{partner_id}/planes",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("partner:write"))],
    summary="Plan de negocio conjunto",
)
def crear_plan(partner_id: UUID, datos: Plan, uow: UowDep) -> Any:
    fila, avisos = prt.crear_plan(uow, partner_id, **datos.model_dump())
    return {"id": str(fila.id), "avisos": avisos}


@router.post(
    "/planes/{plan_conjunto_id}/revisiones",
    dependencies=[Depends(exige_permiso("partner:write"))],
    summary="Anotar una revisión del plan conjunto",
)
def revisar_plan(plan_conjunto_id: UUID, datos: Revision, uow: UowDep) -> Any:
    return prt.revisar_plan(uow, plan_conjunto_id, **datos.model_dump())


@router.post(
    "/rendimiento",
    dependencies=[Depends(exige_permiso("partner:read"))],
    summary="Rendimiento del canal",
    description=(
        "Lo cerrado lo trae quien llama, como en las cuotas: calcularlo aquí daría "
        "un segundo número del mismo negocio. La **conversión** es el dato que "
        "importa: quien registra treinta y cierra uno está bloqueando clientes."
    ),
)
def rendimiento(datos: Rendimiento, db: DbDep, principal: AutenticadoDep) -> Any:
    return prt.rendimiento(
        db,
        principal.tenant_id,
        desde=datos.desde,
        hasta=datos.hasta,
        cerrado_por_partner=datos.cerrado_por_partner,
    )


# ── Portal del partner ────────────────────────────────────────────────────


# ── La puerta del portal del partner ──────────────────────────────────────
#
# A estas dos rutas se llega **sin credencial ninguna**: son donde el partner
# consigue la primera. Por eso no pueden pedir la sesión con `UowDep`, que la
# abre con el tenant del principal — y aquí no hay principal.
#
# Medido el 29-09-2026: las dos contestaban `401 auth.requerida`. La puerta
# pedía la llave que reparte, así que **ningún partner podía entrar nunca**. Es
# lo mismo que le pasó a `/auth/login` y a las tres rutas de SSO.
#
# El tenant llega en el cuerpo y es una **pista sin firmar**: no concede acceso
# por sí sola. Lo que concede acceso es tener un acceso activo con ese correo en
# ese tenant, o un enlace de un solo uso que emitimos nosotros.


@contextmanager
def _trabajo_sin_credencial(tenant: str) -> Iterator[Any]:
    """Unidad de trabajo para una puerta de entrada, con el tenant del cuerpo."""
    from crmcore.bus.outbox import despertar_relevo
    from crmcore.db.session import sesion
    from crmcore.db.uow import UnidadDeTrabajo
    from crmcore.http.interno import resolver_tenant
    from crmcore.tenancy.context import con_contexto

    tenant_id = resolver_tenant(tenant)
    with con_contexto(tenant_id=tenant_id, origen="api"), sesion(tenant_id) as db:
        uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
        yield uow
        uow._volcar_eventos()
    despertar_relevo()


class Entrar(BaseModel):
    # El tenant, igual que en el inicio de sesión del CRM: la pantalla del
    # portal pide el nombre de la organización, que es lo único que un partner
    # tiene. Sin esto la ruta no puede abrir ninguna sesión.
    tenant: str = Field(min_length=1, max_length=200)
    email: str


class Canjear(BaseModel):
    tenant: str = Field(min_length=1, max_length=200)
    token: str


@router_portal.post(
    "/entrar",
    summary="Pedir un enlace de entrada al portal",
    description=(
        "Responde **igual exista o no** el correo: distinguirlos convertiría el "
        "portal en un comprobador de qué empresas son partners nuestros.\n\n"
        "El tenant va en el cuerpo porque a esta ruta se llega sin haber "
        "entrado: es una pista sin firmar, y lo que concede acceso es tener un "
        "acceso activo con ese correo."
    ),
)
def entrar(datos: Entrar) -> Any:
    with _trabajo_sin_credencial(datos.tenant) as uow:
        enlace, token = prt.emitir_enlace(uow, email=datos.email)
        return {
            "enviado": True,
            # El token solo sale en la respuesta cuando no hay canal de correo
            # configurado; en producción va por correo y aquí no se devuelve.
            "token": token or None,
            "caduca_at": enlace.caduca_at.isoformat() if enlace is not None else None,
        }


@router_portal.post(
    "/canjear",
    summary="Canjear el enlace y abrir sesión de partner",
)
def canjear(datos: Canjear, request: Request) -> Any:
    with _trabajo_sin_credencial(datos.tenant) as uow:
        return _canjear(datos, uow, request)


def _canjear(datos: Canjear, uow: Any, request: Request) -> Any:
    acceso = prt.canjear_enlace(uow, datos.token, ip=request.client.host if request.client else "")
    return {
        "acceso_id": str(acceso.id),
        "partner_id": str(acceso.partner_id),
        "nivel": acceso.nivel,
        "atributos_principal": prt.atributos_principal(acceso),
    }


@router_portal.get(
    "/mis-registros",
    dependencies=[Depends(exige_permiso("partner:read"))],
    summary="Los registros del partner que pregunta",
    description=(
        "Acotado por el **compartimento del token**. Si saliera de un parámetro, "
        "entrar en la cartera del partner de al lado sería cambiar un número."
    ),
)
def mis_registros(db: DbDep, principal: AutenticadoDep) -> Any:
    consulta = aplicar_estanco(
        select(prt.RegistroOportunidad).where(
            prt.RegistroOportunidad.tenant_id == principal.tenant_id
        ),
        prt.RegistroOportunidad.partner_id,
        principal=principal,
        tipo="partner",
    )
    filas = (
        db.execute(consulta.order_by(prt.RegistroOportunidad.created_at.desc()).limit(100))
        .scalars()
        .all()
    )
    return {
        "registros": [
            {
                "id": str(f.id),
                "cliente": f.cliente_nombre,
                "estado": f.estado,
                "protegido_hasta": str(f.protegido_hasta) if f.protegido_hasta else None,
                "motivo": f.motivo,
            }
            for f in filas
        ]
    }


@router_portal.get(
    "/registros/{registro_id}",
    dependencies=[Depends(exige_permiso("partner:read"))],
    summary="Un registro del partner",
    description=(
        "Un registro de otro partner devuelve **404, no 403**: entre competidores "
        "que comparten fabricante, la existencia ya es la información."
    ),
)
def un_registro(registro_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    from crmcore.errors import NoEncontrado

    fila = db.get(prt.RegistroOportunidad, registro_id)
    if fila is None or fila.tenant_id != principal.tenant_id:
        raise NoEncontrado("No encontrado", error_code="partners.registro_no_encontrado")
    exigir_propio(fila, atributo="partner_id", principal=principal, tipo="partner")
    return {
        "id": str(fila.id),
        "cliente": fila.cliente_nombre,
        "estado": fila.estado,
        "importe_estimado": str(fila.importe_estimado),
        "protegido_hasta": str(fila.protegido_hasta) if fila.protegido_hasta else None,
        "motivo": fila.motivo,
    }


ROUTERS_PARTNERS = [router, router_niveles, router_registros, router_portal]


# ── Fichas: ver, editar y borrar ──────────────────────────────────────────
# De los veintidós recursos que el front deja crear, uno solo se podía abrir,
# editar y borrar. Estos no tenían ni ficha: se creaban y no había forma de
# volver a verlos —ni de corregir una errata— desde ninguna pantalla.
montar_ficha(
    router,
    modelo=prt.Partner,
    objeto="partner",
    permiso_leer="partner:read",
    permiso_escribir="partner:write",
    nombre="Partners",
    parametro="partner_id",
)


# ── La ficha del registro ─────────────────────────────────────────────────
# Sin ella, las acciones que cuelgan de un registro no se alcanzan desde
# ninguna pantalla: existen, se prueban y nadie las usa.
montar_ficha(
    router_registros,
    modelo=prt.RegistroOportunidad,
    objeto="registro_oportunidad",
    permiso_leer="partner:read",
    permiso_escribir="partner:write",
    nombre="Registros de oportunidad",
)
