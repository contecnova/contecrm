"""API HTTP del servicio `party`."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.errors import ErrorValidacion, NoEncontrado
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
from crmcore.http.pagination import ParametrosPagina, aplicar_orden_y_cursor, construir_pagina
from crmcore.http.retencion_router import crear_router_retencion
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select

from services.party import administracion as admin
from services.party import duplicados
from services.party import servicio as svc
from services.party.esquemas import (
    ActividadOut,
    ActualizarCuenta,
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
    RegistrarConsentimiento,
    SolicitudDerechosEntrada,
    SolicitudDerechosOut,
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
    consulta = select(Cuenta).where(Cuenta.deleted_at.is_(None), Cuenta.fusionada_en_id.is_(None))
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
def deshacer_fusion(fusion_id: UUID, motivo: str, db: DbDep) -> Any:
    duplicados.deshacer_fusion(db, fusion_id, motivo=motivo)
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
    consulta = select(Contacto).where(
        Contacto.deleted_at.is_(None), Contacto.fusionado_en_id.is_(None)
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
    contacto = db.get(Contacto, contacto_id)
    if contacto is None or contacto.deleted_at is not None:
        raise NoEncontrado("El contacto no existe", error_code="party.contacto_no_encontrado")
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
def purgar_papelera(motivo: str, db: DbDep, principal: AutenticadoDep) -> Any:
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
    de_usuario: UUID,
    a_usuario: UUID,
    motivo: str,
    db: DbDep,
    principal: AutenticadoDep,
    simular: bool = Query(True),
) -> Any:
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


# Adjuntos de los objetos que este servicio posee. La lista blanca impide que
# `party` guarde en su esquema ficheros de una oportunidad, que es de `sales`:
# quedarían invisibles desde donde vive el registro.
router_adjuntos = crear_router_adjuntos({"cuenta", "contacto", "actividad"})


router_comentarios = crear_router_comentarios({"cuenta", "contacto", "actividad"})


# Las clases de dato de este servicio se declaran al importar su módulo.
from services.party import retencion as _retencion  # noqa: E402,F401

router_retencion = crear_router_retencion()


from services.party.indexacion import OBJETOS as _OBJETOS_BUSCABLES  # noqa: E402

router_busqueda = crear_router_busqueda(_OBJETOS_BUSCABLES)


# Operaciones masivas y sus trabajos diferidos. Importar el módulo es lo que
# registra los ejecutores, así que tiene que pasar también en el worker: por eso
# `trabajos_worker.py` importa esto mismo y no se fía de que la API lo haya
# hecho, que en el worker no ha pasado.
from crmcore.http.masivo_router import crear_router_masivo  # noqa: E402
from crmcore.http.trabajos_router import crear_router_trabajos  # noqa: E402

from services.party.masivo import RECURSOS as _RECURSOS_MASIVOS  # noqa: E402

routers_masivos = [crear_router_masivo(r) for r in _RECURSOS_MASIVOS]

# Ver los trabajos exige el permiso de administrar el maestro y no uno genérico:
# la ficha de un trabajo guarda la entrada completa, que en una importación son
# los datos personales del fichero que subió el cliente.
router_trabajos = crear_router_trabajos(
    permiso_ver="account:import", permiso_cancelar="account:import"
)


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
    router_trabajos,
    *routers_masivos,
]
