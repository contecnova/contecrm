"""API HTTP del servicio `party`."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.authz.visibilidad import aplicar_visibilidad
from crmcore.errors import ErrorValidacion
from crmcore.http.adjuntos_router import crear_router_adjuntos
from crmcore.http.busqueda_router import crear_router_busqueda
from crmcore.http.comentarios_router import crear_router_comentarios
from crmcore.http.deps import (
    AutenticadoDep,
    DbDep,
    UowDep,
    exige_permiso,
    proyectar_para,
)
from crmcore.http.documental_router import crear_router_documental
from crmcore.http.pagination import ParametrosPagina, aplicar_orden_y_cursor, construir_pagina
from crmcore.http.retencion_router import crear_router_retencion
from fastapi import APIRouter, Body, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from services.party import administracion as admin
from services.party import duplicados
from services.party import servicio as svc
from services.party.esquemas import (
    ActividadOut,
    ActualizarCuenta,
    AsignarActividad,
    CandidatoOut,
    CompletarActividad,
    ConsentimientoOut,
    ContactoOut,
    CrearActividad,
    CrearContacto,
    CrearCuenta,
    CuentaOut,
    DireccionEntrada,
    DireccionOut,
    EnlazarJerarquia,
    Fusionar,
    MiembroEquipoEntrada,
    MiembroEquipoOut,
    RecordatorioEntrada,
    RegistrarConsentimiento,
    RelacionCuentaEntrada,
    SolicitudDerechosEntrada,
    SolicitudDerechosOut,
    SupresionEntrada,
    VincularContacto,
    Vista360,
)
from services.party.modelos import (
    Actividad,
    Consentimiento,
    Contacto,
    Cuenta,
    Direccion,
    SolicitudDerechos,
)

# ── Cuentas ───────────────────────────────────────────────────────────────


class ConMotivo(BaseModel):
    """El motivo, por cuerpo y no por query.

    Por cuerpo por dos razones: el formulario de la acción se genera del
    contrato y un parámetro de query no aparece en él —la pantalla salía sin
    ningún campo y al enviar contestaba que faltaba el motivo—, y porque un
    texto libre escrito por una persona puede llevar nombres dentro, y la URL
    queda en el log de acceso y en el historial del navegador.
    """

    motivo: str = Field(..., min_length=1, max_length=1000)


class TransferirPropiedad(BaseModel):
    """El traspaso de todo lo de una persona a otra, cuando alguien se va."""

    de_usuario: UUID
    a_usuario: UUID
    motivo: str = Field("", max_length=1000)
    simular: bool = Field(True, description="Cuenta sin mover nada")


router_cuentas = APIRouter(prefix="/accounts", tags=["cuentas"])


@router_cuentas.post(
    "",
    response_model=CuentaOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("account:write"))],
    summary="Dar de alta una cuenta",
    description=(
        "Comprueba duplicados **antes** de crear. Si encuentra uno concluyente "
        "—mismo identificador fiscal o similitud altísima— responde 409 con los "
        "candidatos y cómo continuar. Con `forzar=true` se crea igualmente y la "
        "decisión queda en la auditoría."
    ),
)
def crear_cuenta(datos: CrearCuenta, uow: UowDep) -> Any:
    payload = datos.model_dump(exclude={"identificadores", "forzar"})
    return svc.crear_cuenta(
        uow,
        identificadores=[i.model_dump() for i in datos.identificadores],
        forzar=datos.forzar,
        **payload,
    )


@router_cuentas.get(
    "",
    response_model=dict,
    dependencies=[Depends(exige_permiso("account:read"))],
    summary="Listar cuentas",
    description="Paginación por cursor: estable aunque se creen o borren filas entre páginas.",
)
def listar_cuentas(
    db: DbDep,
    principal: AutenticadoDep,
    limite: int = Query(50, ge=1, le=200),
    cursor: str = Query(""),
    orden: str = Query("-created_at"),
    buscar: str = Query("", description="Busca en nombre y nombre comercial"),
    estado: str = Query(""),
    owner_id: UUID | None = Query(None),
) -> Any:
    params = ParametrosPagina.desde_query(limite=limite, cursor=cursor, orden=orden)
    # La compartición se aplica ANTES que los filtros del usuario, y da igual el
    # orden para el resultado: se pone primero para que se vea al leer que toda
    # consulta de este listado sale ya acotada, y no dependa de que quien añada
    # un filtro nuevo lo ponga en el sitio correcto (CRM-00.05.02.04).
    consulta = aplicar_visibilidad(
        select(Cuenta).where(Cuenta.deleted_at.is_(None), Cuenta.fusionada_en_id.is_(None)),
        Cuenta,
        db=db,
        principal=principal,
        objeto="cuenta",
        permiso_ver_todo="account:admin",
    )
    if buscar:
        from sqlalchemy import or_

        patron = f"%{buscar.lower()}%"
        consulta = consulta.where(
            or_(
                Cuenta.nombre.ilike(patron),
                Cuenta.nombre_comercial.ilike(patron),
                Cuenta.clave_canonica.ilike(patron),
            )
        )
    if estado:
        consulta = consulta.where(Cuenta.estado == estado)
    if owner_id:
        consulta = consulta.where(Cuenta.owner_id == owner_id)

    consulta = aplicar_orden_y_cursor(
        consulta,
        Cuenta,
        params,
        columnas_permitidas={"created_at", "nombre", "calidad", "updated_at"},
        objeto="cuenta",
        principal=principal,
        db=db,
    )
    filas = list(db.execute(consulta.limit(params.limite + 1)).scalars().all())
    pagina = construir_pagina(filas, params, campos_orden=[orden])
    return pagina.a_dict(lambda c: CuentaOut.model_validate(c).model_dump(mode="json"))


@router_cuentas.get(
    "/{cuenta_id}",
    response_model=CuentaOut,
    dependencies=[Depends(exige_permiso("account:read"))],
    summary="Ficha de una cuenta",
)
def obtener_cuenta(cuenta_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    # La proyección va aquí y no en el modelo de salida: el objeto se sigue
    # necesitando entero para las reglas de negocio, y vaciarle campos para
    # serializar sabotearía la lógica que viene después.
    proyecta = proyectar_para(principal, db, objeto="cuenta", modelo=Cuenta)
    return proyecta(svc._cuenta(db, cuenta_id))


@router_cuentas.patch(
    "/{cuenta_id}",
    response_model=CuentaOut,
    dependencies=[Depends(exige_permiso("account:write"))],
    summary="Actualizar una cuenta",
    description="Deja historial campo a campo: valor anterior, nuevo, autor y origen.",
)
def actualizar_cuenta(cuenta_id: UUID, datos: ActualizarCuenta, uow: UowDep) -> Any:
    return svc.actualizar_cuenta(
        uow, cuenta_id, datos.model_dump(exclude_unset=True, exclude_none=True)
    )


@router_cuentas.delete(
    "/{cuenta_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(exige_permiso("account:delete"))],
    summary="Enviar una cuenta a la papelera",
    description=(
        "No borra: marca. Borrar de verdad una cuenta con años de historia es "
        "irreversible y casi siempre un error humano."
    ),
)
def borrar_cuenta(cuenta_id: UUID, db: DbDep, principal: AutenticadoDep) -> None:
    admin.borrar_cuenta(db, cuenta_id, por=principal.id)


@router_cuentas.get(
    "/{cuenta_id}/360",
    response_model=Vista360,
    dependencies=[Depends(exige_permiso("account:read"))],
    summary="Vista 360 de la cuenta",
    description=(
        "Perfil unificado para cualquier frontend: ficha, identificadores, "
        "direcciones, contactos vivos y timeline. Declara explícitamente qué "
        "métricas **todavía no** están disponibles, para que un consumidor "
        "distinga «no hay datos» de «este CRM no lo tiene aún»."
    ),
)
def vista_360(cuenta_id: UUID, db: DbDep) -> Any:
    return svc.vista_360(db, cuenta_id)


@router_cuentas.get(
    "/{cuenta_id}/timeline",
    response_model=list[dict],
    dependencies=[Depends(exige_permiso("account:read"))],
    summary="Timeline de la cuenta",
)
def timeline_cuenta(cuenta_id: UUID, db: DbDep, limite: int = Query(50, ge=1, le=200)) -> Any:
    # Se comprueba primero que la cuenta existe y es de este tenant. No filtraba
    # datos —el guard del ORM ya vacía la lista—, pero devolvía 200 donde
    # `GET /cuentas/{id}` devuelve 404 para el MISMO identificador. Esa
    # incoherencia es una fuga en potencia: el día que alguien añada al timeline
    # un dato que no cuelgue de una tabla con `tenant_id`, empezaría a salir.
    # Lo encontró el fuzzing sistemático de rutas.
    svc.exigir_cuenta(db, cuenta_id)
    return svc.timeline(db, cuenta_id=cuenta_id, limite=limite)


@router_cuentas.post(
    "/{cuenta_id}/direcciones",
    response_model=DireccionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("account:write"))],
    summary="Añadir una dirección",
)
def crear_direccion(
    cuenta_id: UUID, datos: DireccionEntrada, db: DbDep, principal: AutenticadoDep
) -> Any:
    cuenta = svc._cuenta(db, cuenta_id)
    direccion = Direccion(
        tenant_id=principal.tenant_id, objeto="cuenta", objeto_id=cuenta.id, **datos.model_dump()
    )
    db.add(direccion)
    db.flush()
    svc._recalcular_calidad_cuenta(db, cuenta)
    return direccion


@router_cuentas.post(
    "/{cuenta_id}/jerarquia",
    response_model=dict,
    dependencies=[Depends(exige_permiso("account:write"))],
    summary="Colgar la cuenta de otra en una jerarquía",
    description=(
        "Pueden coexistir varias jerarquías (legal, comercial, facturación, "
        "entrega). Rechaza el enlace si formaría un ciclo."
    ),
)
def enlazar_jerarquia(cuenta_id: UUID, datos: EnlazarJerarquia, db: DbDep) -> Any:
    enlace = svc.enlazar_jerarquia(
        db,
        cuenta_id=cuenta_id,
        padre_id=datos.padre_id,
        jerarquia=datos.jerarquia,
        rol=datos.rol,
    )
    return {"jerarquia": enlace.jerarquia, "padre_id": str(enlace.padre_id), "rol": enlace.rol}


@router_cuentas.get(
    "/{cuenta_id}/jerarquia",
    response_model=dict,
    dependencies=[Depends(exige_permiso("account:read"))],
    summary="Árbol de la jerarquía desde esta cuenta",
)
def arbol_jerarquia(cuenta_id: UUID, db: DbDep, jerarquia: str = Query("legal")) -> Any:
    return svc.arbol_jerarquia(db, cuenta_id, jerarquia=jerarquia)


# ── Calidad del dato ──────────────────────────────────────────────────────

router_calidad = APIRouter(prefix="/data-quality", tags=["calidad del dato"])


@router_calidad.get(
    "/accounts/duplicates",
    response_model=list[CandidatoOut],
    dependencies=[Depends(exige_permiso("account:read"))],
    summary="Buscar duplicados de una cuenta antes de crearla",
    description=(
        "Lo mismo que hace el alta, pero sin crear nada: sirve para que un "
        "formulario avise mientras se escribe. Devuelve **por qué** se propone "
        "cada candidato, porque «mismo NIF» y «nombre parecido» llevan a "
        "decisiones distintas."
    ),
)
def duplicados_cuenta(
    db: DbDep,
    principal: AutenticadoDep,
    nombre: str = Query(..., min_length=2),
    nif: str = Query(""),
    email: str = Query(""),
    web: str = Query(""),
) -> Any:
    candidatos = duplicados.buscar_cuentas_duplicadas(
        db,
        tenant_id=principal.tenant_id,
        nombre=nombre,
        identificadores=[nif] if nif else None,
        email=email or None,
        web=web or None,
    )
    return [c.a_dict() for c in candidatos]


@router_calidad.post(
    "/accounts/{cuenta_id}/merge",
    response_model=dict,
    dependencies=[Depends(exige_permiso("account:merge"))],
    summary="Fusionar dos cuentas",
    description=(
        "La absorbida **no se borra**: se marca y conserva su identificador, "
        "porque hay documentos y sistemas externos que apuntan a él. Todo lo que "
        "colgaba de ella se reparenta, y la fusión se puede deshacer."
    ),
)
def fusionar_cuentas(
    cuenta_id: UUID, datos: Fusionar, uow: UowDep, principal: AutenticadoDep
) -> Any:
    fusion = duplicados.fusionar_cuentas(
        uow.db,
        superviviente_id=cuenta_id,
        absorbida_id=datos.absorbido_id,
        campos_ganadores=datos.campos_ganadores,
        motivo=datos.motivo,
        por=principal.id,
    )
    uow.db.flush()
    uow.emitir(
        "account.merged",
        subject=("cuenta", cuenta_id),
        data={"superviviente_id": str(cuenta_id), "absorbido_id": str(datos.absorbido_id)},
    )
    uow.emitir(
        "record.merged",
        subject=("cuenta", cuenta_id),
        data={
            "objeto": "cuenta",
            "superviviente_id": str(cuenta_id),
            "absorbido_id": str(datos.absorbido_id),
        },
    )
    return {
        "fusion_id": str(fusion.id),
        "relaciones_movidas": fusion.relaciones_movidas,
        "campos_de_la_absorbida": [
            c for c, quien in fusion.supervivencia.items() if quien == "absorbida"
        ],
    }


@router_calidad.post(
    "/merges/{fusion_id}/undo",
    status_code=status.HTTP_200_OK,
    response_model=dict,
    dependencies=[Depends(exige_permiso("account:merge"))],
    summary="Deshacer una fusión",
    description=(
        "Restaura los **campos** de la ficha absorbida y la reactiva. **No** "
        "devuelve las relaciones a su sitio: al reparentar se pierde de cuál "
        "venía cada una, y repartirlas a ojo sería peor que dejarlas juntas."
    ),
)
def deshacer_fusion(fusion_id: UUID, datos: ConMotivo, db: DbDep) -> Any:
    duplicados.deshacer_fusion(db, fusion_id, motivo=datos.motivo)
    return {"deshecha": True, "aviso": "las relaciones reparentadas no se han devuelto"}


# ── Contactos ─────────────────────────────────────────────────────────────

router_contactos = APIRouter(prefix="/contacts", tags=["contactos"])


@router_contactos.post(
    "",
    response_model=ContactoOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("contact:write"))],
    summary="Dar de alta un contacto",
)
def crear_contacto(datos: CrearContacto, uow: UowDep) -> Any:
    payload = datos.model_dump(exclude={"cuenta_id", "rol", "forzar"})
    return svc.crear_contacto(
        uow, cuenta_id=datos.cuenta_id, rol=datos.rol, forzar=datos.forzar, **payload
    )


@router_contactos.get(
    "",
    response_model=dict,
    dependencies=[Depends(exige_permiso("contact:read"))],
    summary="Listar contactos",
)
def listar_contactos(
    db: DbDep,
    principal: AutenticadoDep,
    limite: int = Query(50, ge=1, le=200),
    cursor: str = Query(""),
    buscar: str = Query(""),
    cuenta_id: UUID | None = Query(None),
) -> Any:
    from services.party.modelos import RelacionContactoCuenta

    params = ParametrosPagina.desde_query(limite=limite, cursor=cursor, orden="-created_at")
    consulta = aplicar_visibilidad(
        select(Contacto).where(Contacto.deleted_at.is_(None), Contacto.fusionado_en_id.is_(None)),
        Contacto,
        db=db,
        principal=principal,
        objeto="contacto",
        permiso_ver_todo="contact:admin",
    )
    if buscar:
        patron = f"%{buscar.lower()}%"
        consulta = consulta.where(Contacto.clave_canonica.ilike(patron))
    if cuenta_id:
        consulta = consulta.join(
            RelacionContactoCuenta, RelacionContactoCuenta.contacto_id == Contacto.id
        ).where(
            RelacionContactoCuenta.cuenta_id == cuenta_id,
            RelacionContactoCuenta.hasta.is_(None),
        )
    consulta = aplicar_orden_y_cursor(
        consulta,
        Contacto,
        params,
        columnas_permitidas={"created_at", "nombre_completo", "calidad"},
        objeto="contacto",
        principal=principal,
        db=db,
    )
    filas = list(db.execute(consulta.limit(params.limite + 1)).scalars().all())
    pagina = construir_pagina(filas, params, campos_orden=["-created_at"])
    return pagina.a_dict(lambda c: ContactoOut.model_validate(c).model_dump(mode="json"))


@router_contactos.get(
    "/{contacto_id}",
    response_model=ContactoOut,
    dependencies=[Depends(exige_permiso("contact:read"))],
    summary="Ficha de un contacto",
)
def obtener_contacto(contacto_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    # Por el cargador compartido: es el que evalúa las políticas de acceso, y
    # cargarlo aquí a mano era saltárselas sin que se notara.
    contacto = svc.exigir_contacto(db, contacto_id)
    proyecta = proyectar_para(principal, db, objeto="contacto", modelo=Contacto)
    return proyecta(contacto)


@router_contactos.post(
    "/{contacto_id}/cuentas",
    response_model=dict,
    dependencies=[Depends(exige_permiso("contact:write"))],
    summary="Vincular el contacto con una cuenta",
    description=(
        "La relación es N:M: una persona puede serlo de varias empresas, con "
        "papel distinto en cada una."
    ),
)
def vincular(contacto_id: UUID, datos: VincularContacto, db: DbDep) -> Any:
    vinculo = svc.vincular_contacto(
        db,
        contacto_id=contacto_id,
        cuenta_id=datos.cuenta_id,
        rol=datos.rol,
        cargo=datos.cargo,
        principal=datos.principal,
    )
    return {"cuenta_id": str(vinculo.cuenta_id), "rol": vinculo.rol, "principal": vinculo.principal}


@router_contactos.delete(
    "/{contacto_id}/cuentas/{cuenta_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(exige_permiso("contact:write"))],
    summary="Cerrar el vínculo con una cuenta",
    description=(
        "La persona dejó esa empresa. Se cierra con fecha, no se borra: el "
        "histórico de la cuenta tiene que seguir teniendo sentido."
    ),
)
def desvincular(contacto_id: UUID, cuenta_id: UUID, motivo: str, db: DbDep) -> None:
    svc.cerrar_vinculo(db, contacto_id=contacto_id, cuenta_id=cuenta_id, motivo=motivo)


@router_contactos.post(
    "/{contacto_id}/consentimientos",
    response_model=ConsentimientoOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("contact:write"))],
    summary="Registrar un consentimiento",
    description=(
        "Se guarda como fila **nueva**, nunca sobrescribiendo: la historia "
        "completa es lo que demuestra que en el momento del envío había permiso."
    ),
)
def registrar_consentimiento(contacto_id: UUID, datos: RegistrarConsentimiento, uow: UowDep) -> Any:
    return svc.registrar_consentimiento(uow, contacto_id=contacto_id, **datos.model_dump())


@router_contactos.get(
    "/{contacto_id}/consentimientos",
    response_model=list[ConsentimientoOut],
    dependencies=[Depends(exige_permiso("contact:read"))],
    summary="Historial de consentimientos",
)
def listar_consentimientos(contacto_id: UUID, db: DbDep) -> Any:
    svc.exigir_contacto(db, contacto_id)
    return list(
        db.execute(
            select(Consentimiento)
            .where(Consentimiento.contacto_id == contacto_id)
            .order_by(Consentimiento.fecha.desc())
        )
        .scalars()
        .all()
    )


@router_contactos.get(
    "/{contacto_id}/puede-contactar",
    response_model=dict,
    dependencies=[Depends(exige_permiso("contact:read"))],
    summary="¿Se puede contactar hoy por este canal y finalidad?",
    description=(
        "La pregunta que tiene que hacer marketing **antes** de cada envío. "
        "Tiene en cuenta el interruptor global de la ficha, la caducidad y el "
        "último apunte, en ese orden."
    ),
)
def puede_contactar(
    contacto_id: UUID,
    db: DbDep,
    finalidad: str = Query(...),
    canal: str = Query(...),
) -> Any:
    return {
        "puede": svc.consentimiento_vigente(db, contacto_id, finalidad=finalidad, canal=canal),
        "finalidad": finalidad,
        "canal": canal,
    }


# ── Actividades ───────────────────────────────────────────────────────────

router_actividades = APIRouter(prefix="/activities", tags=["actividades"])


@router_actividades.post(
    "",
    response_model=ActividadOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("activity:write"))],
    summary="Registrar una actividad",
    description=(
        "Tarea, llamada, reunión, nota o visita. Se cuelga de cualquier objeto "
        "del CRM, incluidos los propios del tenant."
    ),
)
def crear_actividad(datos: CrearActividad, uow: UowDep) -> Any:
    return svc.crear_actividad(uow, **datos.model_dump())


@router_actividades.get(
    "",
    response_model=list[ActividadOut],
    dependencies=[Depends(exige_permiso("activity:read"))],
    summary="Listar actividades",
)
def listar_actividades(
    db: DbDep,
    principal: AutenticadoDep,
    estado: str = Query(""),
    tipo: str = Query(""),
    mias: bool = Query(False, description="Solo las asignadas a quien pregunta"),
    vencidas: bool = Query(False),
    limite: int = Query(50, ge=1, le=200),
) -> Any:
    consulta = select(Actividad).where(Actividad.deleted_at.is_(None))
    if estado:
        consulta = consulta.where(Actividad.estado == estado)
    if tipo:
        consulta = consulta.where(Actividad.tipo == tipo)
    if mias:
        consulta = consulta.where(Actividad.asignada_a == principal.id)
    if vencidas:
        consulta = consulta.where(
            Actividad.vence_at < datetime.now(timezone.utc),
            Actividad.estado.in_(("pendiente", "en_curso")),
        )
    return list(
        db.execute(
            consulta.order_by(Actividad.vence_at.nulls_last(), Actividad.created_at.desc()).limit(
                limite
            )
        )
        .scalars()
        .all()
    )


@router_actividades.post(
    "/{actividad_id}/completar",
    response_model=ActividadOut,
    dependencies=[Depends(exige_permiso("activity:write"))],
    summary="Completar una actividad",
)
def completar(
    actividad_id: UUID, datos: CompletarActividad, uow: UowDep, principal: AutenticadoDep
) -> Any:
    actividad = svc.completar_actividad(
        uow.db, actividad_id, resultado=datos.resultado, por=principal.id
    )
    uow.emitir(
        "activity.completed",
        subject=("actividad", actividad_id),
        data={
            "actividad_id": str(actividad_id),
            "tipo": actividad.tipo,
            "resultado": actividad.resultado,
        },
    )
    return actividad


# ── Derechos del interesado ───────────────────────────────────────────────

router_derechos = APIRouter(prefix="/data-subject-requests", tags=["derechos del interesado"])


@router_derechos.post(
    "",
    response_model=SolicitudDerechosOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("contact:write"))],
    summary="Registrar una solicitud de derechos",
    description=(
        "Acceso, rectificación, supresión, portabilidad, oposición o limitación. "
        "El plazo legal se calcula **al recibirla**, no al empezar a tramitarla: "
        "el reloj corre desde que llega."
    ),
)
def crear_solicitud(datos: SolicitudDerechosEntrada, db: DbDep, principal: AutenticadoDep) -> Any:
    solicitud = svc.crear_solicitud_derechos(
        db, tenant_id=principal.tenant_id, **datos.model_dump()
    )
    db.flush()
    return _solicitud_out(solicitud)


@router_derechos.get(
    "",
    response_model=list[SolicitudDerechosOut],
    dependencies=[Depends(exige_permiso("contact:read"))],
    summary="Solicitudes y su plazo",
    description="Ordenadas por vencimiento: lo que antes vence, primero.",
)
def listar_solicitudes(
    db: DbDep, _: AutenticadoDep, estado: str = Query(""), limite: int = Query(50, ge=1, le=200)
) -> Any:
    consulta = select(SolicitudDerechos)
    if estado:
        consulta = consulta.where(SolicitudDerechos.estado == estado)
    filas = db.execute(consulta.order_by(SolicitudDerechos.vence_at).limit(limite)).scalars().all()
    return [_solicitud_out(s) for s in filas]


@router_derechos.post(
    "/{solicitud_id}/ejecutar-acceso",
    response_model=dict,
    dependencies=[Depends(exige_permiso("contact:read"))],
    summary="Reunir todo lo que este servicio guarda de la persona",
    description=(
        "Vale para acceso y para portabilidad: el contenido es el mismo y lo que "
        "cambia es a quién se entrega y en qué formato.\n\n"
        "**Solo los datos de este servicio.** `party` no puede leer el esquema de "
        "`sales` ni el de `service`, así que la respuesta completa al interesado "
        "exige preguntar también a los demás. Devolver esto como si fuera todo "
        "sería la forma más silenciosa de incumplir: el interesado recibiría un "
        "expediente incompleto creyendo que es completo. La respuesta lo dice en "
        "`alcance`.\n\n"
        "El contenido **no se guarda**: guardarlo sería conservar exactamente los "
        "datos que el interesado quiere que dejemos de tener. Lo que queda es la "
        "huella, que basta para demostrar después qué se entregó."
    ),
)
def ejecutar_acceso(solicitud_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    from services.party import derechos

    return derechos.ejecutar_acceso(db, solicitud_id, por=principal.id)


@router_derechos.post(
    "/{solicitud_id}/ejecutar-supresion",
    response_model=dict,
    dependencies=[Depends(exige_permiso("contact:delete"))],
    summary="Suprimir los datos de la persona, respetando los bloqueos legales",
    description=(
        "**Anonimiza, no borra.** Hay datos que la empresa tiene obligación de "
        "conservar —una factura, un contrato— aunque el interesado pida la "
        "supresión. Se rompe el vínculo con la persona y se conserva el hecho "
        "económico; borrar la fila rompería la contabilidad y sería otro "
        "incumplimiento distinto.\n\n"
        "**Un bloqueo legal gana sobre el derecho de supresión.** Si un juzgado "
        "ha pedido conservar esos datos, no se tocan, la solicitud queda EN CURSO "
        "y la evidencia dice por qué, para que alguien conteste al interesado "
        "explicando el conflicto. No es un fallo del sistema: es la ley "
        "resolviendo dos obligaciones que chocan.\n\n"
        "Es irreversible y exige confirmación explícita."
    ),
)
def ejecutar_supresion(
    solicitud_id: UUID,
    db: DbDep,
    principal: AutenticadoDep,
    cuerpo: SupresionEntrada = Body(default_factory=SupresionEntrada),
) -> Any:
    from services.party import derechos

    return derechos.ejecutar_supresion(
        db, solicitud_id, por=principal.id, confirmado=cuerpo.confirmo_que_es_irreversible
    )


class RectificacionEntrada(BaseModel):
    cambios: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Qué campo y con qué valor. Lo decide una persona: de una solicitud "
            "en prosa no se deduce qué hay que corregir."
        ),
    )


class LimitacionEntrada(BaseModel):
    tratamientos: list[str] | None = Field(
        None,
        description=(
            "Qué se limita. Vacío = TODO lo limitable, que es lo que pide quien "
            "invoca el artículo 18 sin entrar en detalle."
        ),
    )
    motivo: str = "exactitud_discutida"


class LevantarLimitacionEntrada(BaseModel):
    motivo: str = Field(
        ...,
        min_length=3,
        description=(
            "Por qué se levanta. Obligatorio: una limitación que desaparece sin "
            "rastro deja a nadie pudiendo decir desde cuándo se volvió a tratar."
        ),
    )


@router_derechos.post(
    "/{solicitud_id}/ejecutar-portabilidad",
    response_model=dict,
    dependencies=[Depends(exige_permiso("contact:read"))],
    summary="Entregar los datos en formato de lectura mecánica",
    description=(
        "Mismo contenido que el acceso, porque son los mismos datos, pero **se "
        "dice qué queda fuera**: la portabilidad cubre lo que el interesado "
        "aportó, no lo que la empresa dedujo sobre él. Entregar un scoring "
        "interno como «sus datos» regala el trabajo propio y da por bueno ante "
        "el interesado un juicio que nunca pidió."
    ),
)
def ejecutar_portabilidad(solicitud_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    from services.party import derechos

    return derechos.ejecutar_portabilidad(db, solicitud_id, por=principal.id)


@router_derechos.post(
    "/{solicitud_id}/ejecutar-rectificacion",
    response_model=dict,
    dependencies=[Depends(exige_permiso("contact:write"))],
    summary="Corregir los datos que el interesado dice que están mal",
    description=(
        "Se guarda **lo que había antes**: sin el valor anterior, una "
        "rectificación es indistinguible de una edición cualquiera, y lo que hay "
        "que poder demostrar es justo que se corrigió lo que el interesado "
        "señaló.\n\n"
        "Solo campos de la persona. Cambiar importes o estados desde aquí sería "
        "usar un derecho para saltarse las reglas de negocio."
    ),
)
def ejecutar_rectificacion(
    solicitud_id: UUID, cuerpo: RectificacionEntrada, db: DbDep, principal: AutenticadoDep
) -> Any:
    from services.party import derechos

    return derechos.ejecutar_rectificacion(
        db, solicitud_id, cambios=cuerpo.cambios, por=principal.id
    )


@router_derechos.post(
    "/{solicitud_id}/ejecutar-oposicion",
    response_model=dict,
    dependencies=[Depends(exige_permiso("contact:write"))],
    summary="Atender la oposición al tratamiento",
    description=(
        "Se traduce en una limitación de verdad —con su fila, su fecha y su "
        "motivo—, no en un «no contactar» escrito en un campo de texto que la "
        "siguiente importación pisa. Y **se avisa a quien envía**: la limitación "
        "que se queda en este servicio no limita nada."
    ),
)
def ejecutar_oposicion(
    solicitud_id: UUID, cuerpo: LimitacionEntrada, db: DbDep, principal: AutenticadoDep
) -> Any:
    from services.party import derechos

    return derechos.ejecutar_oposicion(
        db, solicitud_id, tratamientos=cuerpo.tratamientos, por=principal.id
    )


@router_derechos.post(
    "/{solicitud_id}/ejecutar-limitacion",
    response_model=dict,
    dependencies=[Depends(exige_permiso("contact:write"))],
    summary="Bloquear el tratamiento sin borrar nada (CRM-02.04.02.05)",
    description=(
        "El derecho que casi nadie implementa y el que más problemas evita: los "
        "datos se conservan y dejan de usarse. No se borran, porque si la "
        "exactitud estaba en discusión y el interesado tenía razón hay que poder "
        "rectificarlos.\n\n"
        "La respuesta dice **qué no se para**: la ley permite seguir tratando "
        "para defender reclamaciones y para cumplir obligaciones legales, y "
        "prometer un bloqueo total sería prometer lo que el sistema no puede dar."
    ),
)
def ejecutar_limitacion(
    solicitud_id: UUID, cuerpo: LimitacionEntrada, db: DbDep, principal: AutenticadoDep
) -> Any:
    from services.party import derechos

    return derechos.ejecutar_limitacion(
        db,
        solicitud_id,
        tratamientos=cuerpo.tratamientos,
        motivo=cuerpo.motivo,
        por=principal.id,
    )


@router_derechos.get(
    "/limitaciones/{contacto_id}",
    response_model=dict,
    dependencies=[Depends(exige_permiso("contact:read"))],
    summary="Qué tratamientos tiene limitados esta persona",
)
def limitaciones_de(contacto_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    from services.party import limitacion as lim

    # Se carga el contacto por el cargador de siempre, que comprueba el tenant y
    # las políticas y devuelve 404 si no es de aquí. Sin esto, preguntar por un
    # identificador ajeno respondía 200 con «no está limitado», que confirma que
    # ese identificador existe en alguna parte — lo cazó el fuzzer de tenants.
    svc.exigir_contacto(db, contacto_id)

    estado = {
        t: lim.esta_limitado(db, principal.tenant_id, contacto_id, tratamiento=t)
        for t in lim.TRATAMIENTOS
    }
    return {
        "contacto_id": str(contacto_id),
        "por_tratamiento": estado,
        "alguno_limitado": any(v["limitado"] for v in estado.values()),
        "no_se_paran": lim.NO_SE_PUEDE_LIMITAR,
    }


@router_derechos.post(
    "/limitaciones/{contacto_id}/levantar",
    response_model=dict,
    dependencies=[Depends(exige_permiso("contact:write"))],
    summary="Levantar la limitación, dejando dicho por qué",
)
def levantar_limitacion(
    contacto_id: UUID, cuerpo: LevantarLimitacionEntrada, uow: UowDep, principal: AutenticadoDep
) -> Any:
    from services.party import limitacion as lim

    fila = lim.levantar(uow, contacto_id=contacto_id, motivo=cuerpo.motivo, por=principal.id)
    return {
        "contacto_id": str(contacto_id),
        "levantada": True,
        "hasta": fila.hasta.isoformat() if fila.hasta else None,
        "motivo": fila.motivo_levantamiento,
    }


def _solicitud_out(solicitud: SolicitudDerechos) -> dict[str, Any]:
    restantes = (solicitud.vence_at - datetime.now(timezone.utc)).days
    return {
        "id": solicitud.id,
        "email_solicitante": solicitud.email_solicitante,
        "tipo": solicitud.tipo,
        "estado": solicitud.estado,
        "recibida_at": solicitud.recibida_at,
        "vence_at": solicitud.vence_at,
        "resuelta_at": solicitud.resuelta_at,
        "dias_restantes": restantes,
    }


# ── Administración: papelera, importación y transferencia ─────────────────

router_admin = APIRouter(prefix="/party-admin", tags=["administración de party"])


@router_admin.get(
    "/papelera",
    response_model=list[dict],
    dependencies=[Depends(exige_permiso("account:delete"))],
    summary="Qué hay en la papelera y cuánto queda para que sea irrecuperable",
    description=(
        "Incluye los días que faltan para la purga, que es el dato que importa "
        "a quien está buscando algo que borró sin querer."
    ),
)
def listar_papelera(
    db: DbDep,
    principal: AutenticadoDep,
    objeto: str = Query("", description="cuenta, contacto…"),
    limite: int = Query(50, ge=1, le=200),
) -> Any:
    return admin.listar_papelera(db, principal.tenant_id, objeto=objeto, limite=limite)


@router_admin.post(
    "/papelera/{entrada_id}/restaurar",
    response_model=dict,
    dependencies=[Depends(exige_permiso("account:delete"))],
    summary="Restaurar un registro y lo que se borró con él",
    description=(
        "En cascada: si no se devolviera todo, quedaría una ficha viva con la "
        "mitad de su historia perdida — peor que no restaurar, porque parece "
        "completa."
    ),
)
def restaurar_papelera(entrada_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    entrada = admin.restaurar_entrada(db, entrada_id, por=principal.id)
    return {
        "restaurado": True,
        "objeto": entrada.objeto,
        "registro_id": str(entrada.registro_id),
        "en_cascada": sum(len(v) for v in (entrada.cascada or {}).values()),
    }


@router_admin.post(
    "/papelera/purgar",
    response_model=dict,
    dependencies=[Depends(exige_permiso("account:purge"))],
    summary="Destruir definitivamente lo que ya pasó su plazo",
    description=(
        "**Irreversible.** Exige motivo y queda auditado: destruye datos de un "
        "cliente y tiene que poder demostrarse cuándo y por qué se hizo."
    ),
)
def purgar_papelera(datos: ConMotivo, db: DbDep, principal: AutenticadoDep) -> Any:
    motivo = datos.motivo
    if len(motivo.strip()) < 10:
        raise ErrorValidacion(
            "La purga exige un motivo escrito de al menos 10 caracteres",
            error_code="papelera.motivo_requerido",
        )
    return {"purgados": admin.purgar_vencidos(db, principal.tenant_id, motivo=motivo)}


@router_admin.post(
    "/transferir-propiedad",
    response_model=dict,
    dependencies=[Depends(exige_permiso("account:admin"))],
    summary="Traspasar todo lo de una persona a otra",
    description=(
        "La operación que hace falta cuando alguien deja la empresa. Con "
        "`simular=true` cuenta sin tocar nada: quien la ejecuta necesita ver "
        "cuánto va a mover antes de moverlo."
    ),
)
def transferir_propiedad(
    datos: TransferirPropiedad,
    db: DbDep,
    principal: AutenticadoDep,
) -> Any:
    de_usuario, a_usuario = datos.de_usuario, datos.a_usuario
    motivo, simular = datos.motivo, datos.simular
    if not simular and len(motivo.strip()) < 5:
        raise ErrorValidacion(
            "La transferencia exige un motivo escrito",
            error_code="party.transferencia_sin_motivo",
        )
    movidos = admin.transferir(
        db,
        tenant_id=principal.tenant_id,
        de_usuario=de_usuario,
        a_usuario=a_usuario,
        motivo=motivo,
        simular=simular,
    )
    return {"simulado": simular, "movidos": movidos, "total": sum(movidos.values())}


@router_admin.post(
    "/importar/cuentas",
    response_model=dict,
    dependencies=[Depends(exige_permiso("account:import"))],
    summary="Importar cuentas desde filas",
    description=(
        "**Simula por defecto.** La operación destructiva se pide a propósito: "
        "quien llame por error con un fichero de prueba recibe un informe, no un "
        "maestro de clientes contaminado. Al actualizar, rellena huecos y no "
        "pisa lo que ya hay."
    ),
)
def importar_cuentas(
    filas: list[dict[str, Any]],
    db: DbDep,
    _: AutenticadoDep,
    simular: bool = Query(True),
    actualizar: bool = Query(False),
) -> Any:
    informe = admin.importar_cuentas(db, filas, simular=simular, actualizar=actualizar)
    return informe.a_dict()


# ── Asignación, delegación y vencidas (CRM-01.02.01.02) ───────────────────


@router_actividades.post(
    "/{actividad_id}/asignar",
    response_model=ActividadOut,
    dependencies=[Depends(exige_permiso("activity:write"))],
    summary="Poner la actividad en la lista de alguien",
    description=(
        "Emite un aviso, porque eso importa más que el dato: una tarea que "
        "aparece en la lista de alguien sin que se entere es una tarea que se "
        "hace tarde.\n\n"
        "Asignar **borra** la marca de delegación. Pasar una tarea a otra "
        "persona no es lo mismo que delegarla, y dejar el rastro haría que la "
        "ficha dijera que alguien la delegó a quien ya no la tiene."
    ),
)
def asignar_actividad(cuerpo: AsignarActividad, actividad_id: UUID, uow: UowDep) -> Any:
    return svc.asignar_actividad(uow, actividad_id, usuario_id=cuerpo.usuario_id)


@router_actividades.post(
    "/{actividad_id}/delegar",
    response_model=ActividadOut,
    dependencies=[Depends(exige_permiso("activity:write"))],
    summary="Delegar la actividad sin dejar de ser responsable",
    description=(
        "La diferencia con asignar no es cosmética: quien delega **sigue siendo "
        "responsable** de que se haga, y la tarea le sigue apareciendo en sus "
        "vencidas. Sin eso, una tarea delegada desaparece de la vista del que la "
        "delegó y nadie vuelve a mirarla — que es lo que pasa con las tareas "
        "delegadas por correo."
    ),
)
def delegar_actividad(
    cuerpo: AsignarActividad, actividad_id: UUID, uow: UowDep, principal: AutenticadoDep
) -> Any:
    return svc.delegar_actividad(uow, actividad_id, usuario_id=cuerpo.usuario_id, por=principal.id)


@router_actividades.post(
    "/{actividad_id}/recordatorio",
    response_model=ActividadOut,
    dependencies=[Depends(exige_permiso("activity:write"))],
    summary="Programar o quitar el recordatorio",
    description=(
        "Cambiar la fecha **rearma** el recordatorio aunque ya se hubiera "
        "enviado: quien la mueve espera que le avisen otra vez, y mantener la "
        "marca haría que una tarea aplazada nunca volviera a avisar.\n\n"
        "Con `cuando` a nulo se quita.\n\n"
        "Con `repetir_cada_min` el aviso **insiste** hasta que la tarea se "
        "cierra o se agota el tope (CRM-01.02.01.09), y con "
        "`reprogramar_cada_dias` la tarea no atendida se empuja sola — siempre "
        "después de avisar de que venció, y dejándolo dicho: una tarea que "
        "cambia de fecha en silencio hace que nadie se fíe de ninguna fecha.\n\n"
        "Las dos exigen tope. Sin él, un aviso suena cuando ya no le importa a "
        "nadie y una tarea no consta vencida nunca."
    ),
)
def programar_recordatorio(cuerpo: RecordatorioEntrada, actividad_id: UUID, uow: UowDep) -> Any:
    return svc.programar_recordatorio(
        uow,
        actividad_id,
        cuando=cuerpo.cuando,
        repetir_cada_min=cuerpo.repetir_cada_min,
        max_avisos=cuerpo.max_avisos,
        reprogramar_cada_dias=cuerpo.reprogramar_cada_dias,
        max_reprogramaciones=cuerpo.max_reprogramaciones,
    )


@router_actividades.get(
    "/vencidas",
    response_model=list[ActividadOut],
    dependencies=[Depends(exige_permiso("activity:read"))],
    summary="Lo que ya debería estar hecho y no lo está",
    description=(
        "Por defecto, las de quien pregunta **y las que delegó**. Eso segundo es "
        "la mitad del valor de delegar: quien delega sigue siendo responsable, y "
        "sin esta vista la tarea desaparece de su vista en cuanto la pasa.\n\n"
        "Con `de_todos` —y el permiso de administrar actividades— se ven las del "
        "equipo entero."
    ),
)
def listar_vencidas(
    db: DbDep,
    principal: AutenticadoDep,
    incluir_delegadas: bool = Query(True),
    de_todos: bool = Query(False),
    limite: int = Query(100, ge=1, le=500),
) -> Any:
    de_quien = None if (de_todos and principal.tiene("activity:admin")) else principal.id
    return svc.actividades_vencidas(
        db, usuario_id=de_quien, incluir_delegadas=incluir_delegadas, limite=limite
    )


# ── Relaciones no jerárquicas entre cuentas (CRM-01.01.01.04) ─────────────


@router_cuentas.get(
    "/{cuenta_id}/relaciones",
    response_model=list[dict],
    dependencies=[Depends(exige_permiso("account:read"))],
    summary="Con qué otras cuentas se relaciona esta",
    description=(
        "Partner, competidor, proveedor, prescriptor. **No implica pertenencia "
        "ni consolidación**: que A sea partner de B no hace que los números de A "
        "sumen en B. Esa es la diferencia con la jerarquía.\n\n"
        "Devuelve las relaciones **en las dos direcciones**: donde una ficha "
        "dice «es proveedor de», la otra dice «es cliente de». Se guarda una "
        "sola fila y se lee al revés, en vez de duplicarla — dos filas obligan a "
        "sincronizarlas y el día que una se quede huérfana las dos fichas se "
        "contradicen."
    ),
)
def listar_relaciones_cuenta(cuenta_id: UUID, db: DbDep) -> Any:
    svc.exigir_cuenta(db, cuenta_id)
    return svc.relaciones_de_cuenta(db, cuenta_id)


@router_cuentas.post(
    "/{cuenta_id}/relaciones",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("account:write"))],
    summary="Relacionar esta cuenta con otra",
)
def crear_relacion_cuenta(cuenta_id: UUID, datos: RelacionCuentaEntrada, uow: UowDep) -> Any:
    relacion = svc.relacionar_cuentas(uow, cuenta_id=cuenta_id, **datos.model_dump())
    return {
        "id": str(relacion.id),
        "cuenta_id": str(relacion.cuenta_id),
        "relacionada_id": str(relacion.relacionada_id),
        "tipo": relacion.tipo,
        "tipo_inverso": relacion.tipo_inverso,
    }


@router_cuentas.delete(
    "/{cuenta_id}/relaciones/{relacion_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(exige_permiso("account:write"))],
    summary="Quitar una relación",
    description="Vale desde cualquiera de las dos fichas: la relación es una sola.",
)
def borrar_relacion_cuenta(cuenta_id: UUID, relacion_id: UUID, uow: UowDep) -> None:
    svc.desrelacionar_cuentas(uow, cuenta_id=cuenta_id, relacion_id=relacion_id)


# ── Verificación contra registros externos ────────────────────────────────


@router_cuentas.post(
    "/{cuenta_id}/identificadores/{identificador_id}/verificar",
    response_model=dict,
    dependencies=[Depends(exige_permiso("account:write"))],
    summary="Comprobar un identificador fiscal contra el registro oficial",
    description=(
        "Son dos comprobaciones distintas y conviene no confundirlas: la **de "
        "forma** (¿está bien construido?) se hace al guardar, es un cálculo y "
        "siempre da la misma respuesta; la **de existencia** (¿existe esta "
        "empresa?) solo la sabe el registro oficial, hay que preguntarle y puede "
        "no contestar.\n\n"
        "Si el registro no contesta **no se degrada el dato**: se conserva el "
        "veredicto anterior y se devuelve `no_concluyente`. Poner «desconocido» "
        "encima de un «válido» porque hoy hubo un timeout convertiría cada "
        "incidencia de red en una pérdida de información.\n\n"
        "Un veredicto de los últimos 90 días **no se vuelve a preguntar** salvo "
        "con `forzar`: muchos registros oficiales tienen cuota, y gastarla "
        "repitiendo lo que ya se sabe deja sin comprobar lo que no. La respuesta "
        "dice si viene de antes con `desde_cache`."
    ),
)
def verificar_identificador(cuenta_id: UUID, identificador_id: UUID, uow: UowDep) -> Any:
    return svc.verificar_identificador_fiscal(
        uow, cuenta_id=cuenta_id, identificador_id=identificador_id
    )


@router_cuentas.post(
    "/{cuenta_id}/direcciones/{direccion_id}/geocodificar",
    response_model=dict,
    dependencies=[Depends(exige_permiso("account:write"))],
    summary="Geocodificar una dirección",
    description=(
        "Pregunta al geocodificador configurado por este tenant. **No hay "
        "código de ningún proveedor**: se declara a dónde llamar y de qué parte "
        "de la respuesta salen las coordenadas."
    ),
)
def geocodificar_direccion(cuenta_id: UUID, direccion_id: UUID, uow: UowDep) -> Any:
    return svc.geocodificar(uow, objeto="cuenta", objeto_id=cuenta_id, direccion_id=direccion_id)


# ── Equipo de cuenta (CRM-01.01.01.10) ────────────────────────────────────


@router_cuentas.get(
    "/{cuenta_id}/equipo",
    response_model=list[MiembroEquipoOut],
    dependencies=[Depends(exige_permiso("account:read"))],
    summary="Quién trabaja esta cuenta",
    description=(
        "El propietario es uno; el equipo es quien más trabaja la cuenta. Sin "
        "esto, el técnico que lleva tres años atendiendo a un cliente no "
        "aparece en ningún sitio y su conocimiento se pierde cuando cambia el "
        "comercial.\n\n"
        "Devuelve **todos**, vigentes o no: quien administra el equipo necesita "
        "ver al que entra el mes que viene y al que salió ayer, o no puede "
        "corregir una fecha mal puesta. Con `solo_vigentes` se pregunta quién "
        "lleva la cuenta hoy."
    ),
)
def listar_equipo(cuenta_id: UUID, db: DbDep, solo_vigentes: bool = Query(False)) -> Any:
    from datetime import date

    svc.exigir_cuenta(db, cuenta_id)
    hoy = date.today()
    return [
        MiembroEquipoOut(
            id=m.id,
            cuenta_id=m.cuenta_id,
            usuario_id=m.usuario_id,
            rol=m.rol,
            acceso=m.acceso,
            desde=m.desde,
            hasta=m.hasta,
            vigente=(m.desde is None or m.desde <= hoy) and (m.hasta is None or m.hasta >= hoy),
        )
        for m in svc.equipo_de_cuenta(db, cuenta_id, solo_vigentes=solo_vigentes)
    ]


@router_cuentas.post(
    "/{cuenta_id}/equipo",
    response_model=MiembroEquipoOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("account:write"))],
    summary="Sumar a alguien al equipo de la cuenta",
    description=(
        "Pertenecer al equipo **da visibilidad** sobre la cuenta, así que el "
        "alta se audita y emite un evento: quien audite quién puede ver qué lo "
        "necesita.\n\n"
        "Repetir el alta del mismo usuario y rol **actualiza** la vigencia y el "
        "acceso en vez de fallar: es lo que hace quien renueva a alguien, y "
        "obligarle a borrar y volver a crear pierde la fecha de alta original."
    ),
)
def añadir_miembro_equipo(cuenta_id: UUID, datos: MiembroEquipoEntrada, uow: UowDep) -> Any:
    from datetime import date

    miembro = svc.añadir_al_equipo(uow, cuenta_id=cuenta_id, **datos.model_dump())
    hoy = date.today()
    return MiembroEquipoOut(
        id=miembro.id,
        cuenta_id=miembro.cuenta_id,
        usuario_id=miembro.usuario_id,
        rol=miembro.rol,
        acceso=miembro.acceso,
        desde=miembro.desde,
        hasta=miembro.hasta,
        vigente=(miembro.desde is None or miembro.desde <= hoy)
        and (miembro.hasta is None or miembro.hasta >= hoy),
    )


@router_cuentas.delete(
    "/{cuenta_id}/equipo/{miembro_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(exige_permiso("account:write"))],
    summary="Sacar a alguien del equipo",
    description=(
        "Borra la fila: el equipo de hace dos años no lo consulta nadie. Lo que "
        "sí queda es el apunte de auditoría, que es donde se busca «¿desde "
        "cuándo dejó de ver esto?»."
    ),
)
def quitar_miembro_equipo(cuenta_id: UUID, miembro_id: UUID, uow: UowDep) -> None:
    svc.quitar_del_equipo(uow, cuenta_id=cuenta_id, miembro_id=miembro_id)


# Adjuntos de los objetos que este servicio posee. La lista blanca impide que
# `party` guarde en su esquema ficheros de una oportunidad, que es de `sales`:
# quedarían invisibles desde donde vive el registro.
router_adjuntos = crear_router_adjuntos({"cuenta", "contacto", "actividad"})


router_comentarios = crear_router_comentarios({"cuenta", "contacto", "actividad"})


# Las clases de dato de este servicio se declaran al importar su módulo.
from services.party import retencion as _retencion  # noqa: E402,F401

# ── Recursos transversales, bajo el nombre del servicio ───────────────────
# Retención, búsqueda y trabajos los monta la misma fábrica en varios servicios.
# Con el camino corto —`/api/v1/trabajos/{id}`— el gateway no puede saber a cuál
# va: el identificador no delata al dueño. El resultado era que estas tres
# familias, escritas y probadas, devolvían 404 desde fuera. Con el nombre del
# servicio delante la ruta es inequívoca y además se lee.
router_retencion = crear_router_retencion("/party/retencion")


from services.party.indexacion import OBJETOS as _OBJETOS_BUSCABLES  # noqa: E402

router_busqueda = crear_router_busqueda(_OBJETOS_BUSCABLES, "/party/buscar")


# Operaciones masivas y sus trabajos diferidos. Importar el módulo es lo que
# registra los ejecutores, así que tiene que pasar también en el worker: por eso
# `trabajos_worker.py` importa esto mismo y no se fía de que la API lo haya
# hecho, que en el worker no ha pasado.
from crmcore.http.listados import montar_ficha  # noqa: E402
from crmcore.http.masivo_router import crear_router_masivo  # noqa: E402
from crmcore.http.trabajos_router import crear_router_trabajos  # noqa: E402

from services.party.masivo import RECURSOS as _RECURSOS_MASIVOS  # noqa: E402

routers_masivos = [crear_router_masivo(r) for r in _RECURSOS_MASIVOS]

# Ver los trabajos exige el permiso de administrar el maestro y no uno genérico:
# la ficha de un trabajo guarda la entrada completa, que en una importación son
# los datos personales del fichero que subió el cliente.
router_trabajos = crear_router_trabajos(
    permiso_ver="account:import", permiso_cancelar="account:import", prefijo="/party/trabajos"
)


# Corpus documental delegado en contecmind (RT-5). La lista blanca impide que
# este servicio enlace documentos a objetos que no son suyos.
router_documental = crear_router_documental({"cuenta", "contacto"})


ROUTERS = [
    router_admin,
    router_cuentas,
    router_contactos,
    router_actividades,
    router_calidad,
    router_derechos,
    router_adjuntos,
    router_comentarios,
    router_retencion,
    router_busqueda,
    router_documental,
    router_trabajos,
    *routers_masivos,
]


# ── Fichas: ver, editar y borrar ──────────────────────────────────────────
# De los veintidós recursos que el front deja crear, uno solo se podía abrir,
# editar y borrar. Estos no tenían ni ficha: se creaban y no había forma de
# volver a verlos —ni de corregir una errata— desde ninguna pantalla.
montar_ficha(
    router_actividades,
    modelo=Actividad,
    objeto="actividad",
    permiso_leer="activity:read",
    permiso_escribir="activity:write",
    nombre="Actividades",
    parametro="actividad_id",
)


# ── Lo que a la ficha le faltaba: corregir y borrar ───────────────────────
# Estos tres ya se podían abrir —tienen su lectura escrita a mano, con sus
# reglas de visibilidad— y no se podían ni corregir ni borrar desde ninguna
# pantalla. Un contacto con el correo mal escrito se quedaba así para siempre.
montar_ficha(
    router_contactos,
    modelo=Contacto,
    objeto="contacto",
    permiso_leer="contact:read",
    permiso_escribir="contact:write",
    permiso_borrar="contact:delete",
    nombre="Contactos",
    parametro="contacto_id",
    # La lectura ya la tiene escrita, con su propia proyección y su control de
    # visibilidad. Aquí solo se añade lo que faltaba: corregir y borrar.
    con_lectura=False,
)
