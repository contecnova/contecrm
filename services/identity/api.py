"""API HTTP del servicio de identidad."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Literal
from uuid import UUID

from crmcore.config import get_settings
from crmcore.errors import NoAutenticado, NoEncontrado
from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from services.identity import servicio as svc
from services.identity.api_sso import router_idp, router_sso
from services.identity.esquemas import (
    ActivarMfa,
    ClaveApiCreada,
    ClaveApiOut,
    CrearClaveApi,
    CrearRol,
    CrearUsuario,
    Credenciales,
    ExplicarPermiso,
    MfaIniciada,
    Renovar,
    RolOut,
    SesionOut,
    Suplantar,
    Tokens,
    UsuarioOut,
    YoOut,
)
from services.identity.modelos import ClaveApi, Membresia, RolTenant, Sesion, Usuario
from services.identity.notificaciones import ROUTERS_NOTIFICACION

router_auth = APIRouter(prefix="/auth", tags=["autenticación"])


@router_auth.post(
    "/login",
    response_model=Tokens,
    summary="Iniciar sesión",
    description=(
        "Devuelve un token de acceso de vida corta y uno de refresco revocable. "
        "El de acceso lleva los permisos ya resueltos para que los servicios no "
        "tengan que consultarlos en cada petición."
    ),
)
def login(datos: Credenciales, request: Request) -> Any:
    # El login NO puede usar la dependencia de sesión habitual: esa sesión se
    # ata al tenant del principal autenticado, y aquí todavía no hay ninguno.
    # La primera versión de esta ruta lo hacía, y el resultado era un 500
    # («se ha abierto una sesión sin tenant») en la única ruta por la que se
    # entra al sistema. Se descubrió arrancándolo, no leyéndolo.
    #
    # El tenant sale del cuerpo de la petición, que es una PISTA sin firmar: no
    # concede acceso por sí sola. Lo que concede acceso es que exista una
    # membresía activa de ese usuario en ese tenant, y eso lo comprueba
    # `svc.autenticar`.
    from crmcore.db.session import sesion

    tenant_id = _resolver_tenant(datos.tenant)
    with sesion(tenant_id) as db:
        usuario = svc.autenticar(
            db,
            email=datos.email,
            contrasena=datos.contrasena,
            tenant_id=tenant_id,
            codigo_mfa=datos.codigo_mfa,
            huella_dispositivo=datos.huella_dispositivo,
        )
        # Qué factores se han superado de verdad en ESTA entrada. Se anota para
        # la reautenticación reforzada (CRM-00.05.01.18), que pregunta cuándo
        # fue el último factor fuerte y no si el usuario tiene MFA configurada.
        superados: tuple[str, ...] = ("contrasena",)
        if datos.codigo_mfa:
            superados = ("contrasena", "totp")
        _sesion, acceso, refresco = svc.crear_sesion(
            db,
            usuario=usuario,
            tenant_id=tenant_id,
            ip=request.client.host if request.client else "",
            user_agent=request.headers.get("user-agent", ""),
            factores_superados=superados,
        )
        if datos.recordar_dispositivo and datos.huella_dispositivo and datos.codigo_mfa:
            # Solo se recuerda el equipo si en ESTA entrada se ha demostrado el
            # segundo factor. Recordarlo sin haberlo pasado convertiría la
            # confianza en una forma de no tener MFA nunca.
            from services.identity import factores as _f

            dispositivo = _f.recordar_dispositivo(
                db,
                usuario.id,
                tenant_id,
                huella=datos.huella_dispositivo,
                nombre=request.headers.get("user-agent", "")[:120],
                ip=request.client.host if request.client else "",
            )
            _sesion.dispositivo_confianza_id = dispositivo.id
    return Tokens(
        access_token=acceso,
        refresh_token=refresco,
        expires_in=get_settings().access_token_minutos * 60,
    )


@router_auth.post(
    "/refresh",
    response_model=Tokens,
    summary="Renovar el token de acceso",
    description=(
        "El token de refresco **rota** en cada uso. Si se presenta uno ya "
        "rotado, se revocan todas las sesiones del usuario: significa que hay "
        "una copia en circulación."
    ),
)
def refrescar(datos: Renovar) -> Any:
    # Igual que el login: aquí aún no hay identidad. Además, el tenant no se
    # puede pedir —el cliente solo tiene el token de refresco—, así que la
    # sesión es de sistema y la acotación la hace el propio token: solo
    # encuentra la fila cuyo hash coincide, que es la del usuario que lo
    # obtuvo. El refresco ES la credencial.
    from crmcore.db.session import sesion

    with sesion(sistema=True) as db:
        acceso, refresco = svc.renovar(db, datos.refresh_token)
    return Tokens(
        access_token=acceso,
        refresh_token=refresco,
        expires_in=get_settings().access_token_minutos * 60,
    )


@router_auth.post(
    "/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Cerrar la sesión en curso"
)
def logout(request: Request, db: DbDep, principal: AutenticadoDep) -> None:
    sid = _sesion_del_token(request)
    if sid:
        svc.revocar(db, sid, motivo="cierre_sesion")


@router_auth.get("/me", response_model=YoOut, summary="Identidad efectiva del token")
def yo(db: DbDep, principal: AutenticadoDep) -> Any:
    usuario = db.get(Usuario, principal.id)
    if usuario is None:
        raise NoEncontrado("El usuario no existe", error_code="usuario.no_encontrado")
    membresia = db.execute(
        select(Membresia).where(
            Membresia.usuario_id == principal.id, Membresia.tenant_id == principal.tenant_id
        )
    ).scalar_one_or_none()
    return YoOut(
        usuario=UsuarioOut.model_validate(usuario),
        tenant_id=principal.tenant_id,
        roles=list(membresia.roles or []) if membresia else [],
        permisos=sorted(principal.permisos),
        suplantado_por=principal.actor_real_id,
    )


# ── MFA ───────────────────────────────────────────────────────────────────


@router_auth.post(
    "/mfa/iniciar",
    response_model=MfaIniciada,
    summary="Empezar la configuración del doble factor",
    description=(
        "Devuelve el secreto y los códigos de recuperación **una sola vez**. "
        "No queda activa hasta confirmar con un código válido: si se activara "
        "aquí, un error al escanear dejaría al usuario fuera de su cuenta."
    ),
)
def iniciar_mfa(db: DbDep, principal: AutenticadoDep) -> Any:
    usuario = db.get(Usuario, principal.id)
    if usuario is None:
        raise NoEncontrado("El usuario no existe", error_code="usuario.no_encontrado")
    secreto = svc.generar_secreto_totp()
    codigos, hashes = svc.generar_codigos_recuperacion()
    usuario.mfa_secreto = secreto
    usuario.mfa_recuperacion = hashes
    emisor = get_settings().app_name
    return MfaIniciada(
        secreto=secreto,
        uri_otpauth=f"otpauth://totp/{emisor}:{usuario.email}?secret={secreto}&issuer={emisor}",
        codigos_recuperacion=codigos,
    )


@router_auth.post("/mfa/activar", response_model=dict, summary="Confirmar y activar el MFA")
def activar_mfa(datos: ActivarMfa, db: DbDep, principal: AutenticadoDep) -> Any:
    usuario = db.get(Usuario, principal.id)
    if usuario is None or not usuario.mfa_secreto:
        raise NoEncontrado(
            "No hay una configuración de MFA iniciada", error_code="auth.mfa_no_iniciada"
        )
    if not svc.verificar_totp(usuario.mfa_secreto, datos.codigo):
        raise NoAutenticado("El código no es válido", error_code="auth.mfa_invalida")
    usuario.mfa_activo = True
    return {"mfa_activo": True}


# ── Usuarios ──────────────────────────────────────────────────────────────

router_usuarios = APIRouter(prefix="/usuarios", tags=["usuarios"])


@router_usuarios.post(
    "",
    response_model=UsuarioOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("user:write"))],
    summary="Dar de alta un usuario en el tenant",
)
def crear_usuario(datos: CrearUsuario, uow: UowDep, principal: AutenticadoDep) -> Any:
    return svc.crear_usuario(
        uow,
        email=datos.email,
        nombre=datos.nombre,
        tenant_id=principal.tenant_id,
        roles=datos.roles,
        contrasena=datos.contrasena,
    )


@router_usuarios.get(
    "",
    response_model=list[UsuarioOut],
    dependencies=[Depends(exige_permiso("user:read"))],
    summary="Usuarios del tenant",
)
def listar_usuarios(db: DbDep, principal: AutenticadoDep) -> Any:
    # Se une por membresía y no se listan los usuarios a secas: `Usuario` es una
    # de las dos tablas sin `tenant_id`, así que aquí el aislamiento lo pone
    # esta unión y no el guard. El gate de alcance lo comprueba.
    return list(
        db.execute(
            select(Usuario)
            .join(Membresia, Membresia.usuario_id == Usuario.id)
            .where(Membresia.tenant_id == principal.tenant_id)
            .order_by(Usuario.email)
        )
        .scalars()
        .all()
    )


@router_usuarios.delete(
    "/{usuario_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(exige_permiso("user:write"))],
    summary="Dar de baja a un usuario del tenant",
)
def baja_usuario(usuario_id: UUID, uow: UowDep, principal: AutenticadoDep) -> None:
    svc.desactivar_usuario(uow, usuario_id, principal.tenant_id)


# ── Roles ─────────────────────────────────────────────────────────────────

router_roles = APIRouter(prefix="/roles", tags=["roles y permisos"])


@router_roles.get("", response_model=list[RolOut], summary="Roles del tenant")
def listar_roles(db: DbDep, principal: AutenticadoDep) -> Any:
    return list(
        db.execute(select(RolTenant).where(RolTenant.tenant_id == principal.tenant_id))
        .scalars()
        .all()
    )


@router_roles.post(
    "",
    response_model=RolOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("role:write"))],
    summary="Crear un rol propio del tenant",
)
def crear_rol(datos: CrearRol, db: DbDep, principal: AutenticadoDep) -> Any:
    rol = RolTenant(tenant_id=principal.tenant_id, **datos.model_dump())
    db.add(rol)
    db.flush()
    return rol


@router_roles.post(
    "/explicar",
    response_model=dict,
    dependencies=[Depends(exige_permiso("user:read"))],
    summary="Por qué un usuario puede (o no) hacer algo",
    description=(
        "Responde con el permiso que decide y con la política ABAC que aplica. "
        "Existe porque «no puedo hacer X» sin explicación es el ticket de "
        "soporte más frecuente de cualquier CRM, y el más caro de cerrar."
    ),
)
def explicar(datos: ExplicarPermiso, db: DbDep, principal: AutenticadoDep) -> Any:
    from crmcore.authz.abac import evaluar
    from crmcore.authz.politicas import cargar

    permisos = svc.permisos_efectivos(db, datos.usuario_id, principal.tenant_id)
    permiso = f"{datos.objeto}:{datos.accion}"
    tiene_rbac = permiso in permisos or f"{datos.objeto}:*" in permisos or "*:*" in permisos

    membresia = db.execute(
        select(Membresia).where(
            Membresia.usuario_id == datos.usuario_id,
            Membresia.tenant_id == principal.tenant_id,
        )
    ).scalar_one_or_none()
    ambito = {
        "usuario": {
            "id": str(datos.usuario_id),
            "business_unit_id": str(membresia.business_unit_id)
            if membresia and membresia.business_unit_id
            else None,
            **(membresia.atributos if membresia else {}),
        },
        "registro": datos.registro,
        "contexto": {"tenant_id": str(principal.tenant_id)},
    }
    # Las políticas GUARDADAS del tenant, no una lista de ejemplo del código.
    # Mientras miraba la lista de ejemplo —con las tres desactivadas— este
    # endpoint contestaba siempre «permitido por ABAC», que es peor que no
    # contestar: daba por buena una explicación que no explicaba nada.
    decision = evaluar(
        cargar(db, principal.tenant_id),
        objeto=datos.objeto,
        accion=datos.accion,
        ambito=ambito,
    )
    return {
        "permitido": tiene_rbac and decision.permitido,
        "rbac": {
            "concede": tiene_rbac,
            "permiso": permiso,
            "roles": list(membresia.roles or []) if membresia else [],
        },
        "abac": {"permitido": decision.permitido, "explicacion": decision.explicacion()},
    }


# ── Sesiones ──────────────────────────────────────────────────────────────

router_sesiones = APIRouter(prefix="/sesiones", tags=["sesiones"])


@router_sesiones.get("", response_model=list[SesionOut], summary="Mis sesiones activas")
def mis_sesiones(db: DbDep, principal: AutenticadoDep) -> Any:
    return list(
        db.execute(
            select(Sesion)
            .where(
                Sesion.usuario_id == principal.id,
                Sesion.revocada_at.is_(None),
                Sesion.expira_at > datetime.now(timezone.utc),
            )
            .order_by(Sesion.ultima_actividad_at.desc())
        )
        .scalars()
        .all()
    )


@router_sesiones.delete(
    "/{sesion_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Cerrar una sesión"
)
def cerrar_sesion(sesion_id: UUID, db: DbDep, principal: AutenticadoDep) -> None:
    sesion = db.get(Sesion, sesion_id)
    # 404 y no 403 si la sesión es de otro: confirmar que existe ya diría de más.
    if sesion is None or (sesion.usuario_id != principal.id and not principal.tiene("user:write")):
        raise NoEncontrado("La sesión no existe", error_code="auth.sesion_no_encontrada")
    svc.revocar(db, sesion_id, motivo="revocacion_manual")


@router_sesiones.post(
    "/suplantar",
    response_model=Tokens,
    summary="Abrir sesión como otro usuario (soporte)",
    description=(
        "Solo personal de plataforma, con motivo escrito y caducidad corta. "
        "Queda en la auditoría del tenant con quién suplantó a quién y por qué."
    ),
)
def suplantar(datos: Suplantar, db: DbDep, principal: AutenticadoDep) -> Any:
    soporte = db.get(Usuario, principal.id)
    if soporte is None:
        raise NoEncontrado("El usuario no existe", error_code="usuario.no_encontrado")
    _s, acceso, refresco = svc.suplantar(
        db,
        soporte=soporte,
        usuario_id=datos.usuario_id,
        tenant_id=principal.tenant_id,
        motivo=datos.motivo,
    )
    return Tokens(
        access_token=acceso,
        refresh_token=refresco,
        expires_in=get_settings().access_token_minutos * 60,
    )


# ── Claves de API ─────────────────────────────────────────────────────────

router_claves = APIRouter(prefix="/claves-api", tags=["claves de API"])


@router_claves.post(
    "",
    response_model=ClaveApiCreada,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("apikey:write"))],
    summary="Crear una clave de API",
    description="El secreto se devuelve **una sola vez**: después solo se guarda su hash.",
)
def crear_clave(datos: CrearClaveApi, db: DbDep, principal: AutenticadoDep) -> Any:
    clave, secreto = svc.crear_clave_api(
        db,
        tenant_id=principal.tenant_id,
        nombre=datos.nombre,
        scopes=datos.scopes,
        rol=datos.rol,
        dias=datos.dias,
        ips_permitidas=datos.ips_permitidas,
        creada_por=principal.id,
    )
    db.flush()
    return ClaveApiCreada(
        id=clave.id,
        nombre=clave.nombre,
        prefijo=clave.prefijo,
        secreto=secreto,
        expira_at=clave.expira_at,
    )


@router_claves.get(
    "",
    response_model=list[ClaveApiOut],
    dependencies=[Depends(exige_permiso("apikey:read"))],
    summary="Claves de API del tenant",
)
def listar_claves(db: DbDep, principal: AutenticadoDep) -> Any:
    return list(
        db.execute(
            select(ClaveApi)
            .where(ClaveApi.tenant_id == principal.tenant_id)
            .order_by(ClaveApi.created_at.desc())
        )
        .scalars()
        .all()
    )


@router_claves.delete(
    "/{clave_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(exige_permiso("apikey:write"))],
    summary="Revocar una clave",
)
def revocar_clave(clave_id: UUID, db: DbDep, principal: AutenticadoDep) -> None:
    clave = db.get(ClaveApi, clave_id)
    if clave is None or clave.tenant_id != principal.tenant_id:
        raise NoEncontrado("La clave no existe", error_code="clave_api.no_encontrada")
    clave.revocada_at = datetime.now(timezone.utc)


# ── Utilidades internas ───────────────────────────────────────────────────


def _resolver_tenant(valor: str) -> UUID:
    """Traduce el slug o el identificador del tenant a UUID.

    Llama al servicio de tenancy por HTTP en vez de leer su tabla: la propiedad
    exclusiva de datos por servicio es justo lo que hace que esa consulta ni
    siquiera esté permitida a nivel de permisos de base de datos.
    """
    from crmcore.ids import es_id_valido, sin_prefijo

    if es_id_valido(valor):
        return sin_prefijo(valor)
    from crmcore.errors import ErrorValidacion

    # Resolver un slug exige preguntar a tenancy. Hasta que el gateway lo
    # resuelva y lo propague (que es el camino normal), se pide el identificador.
    raise ErrorValidacion(
        "Indica el identificador del tenant. El slug lo resuelve el gateway.",
        error_code="auth.tenant_no_resoluble",
    )


def _sesion_del_token(request: Request) -> UUID | None:
    """Extrae `sid` del token sin volver a validarlo.

    Ya lo validó la dependencia de autenticación; aquí solo se lee un campo. Se
    decodifica sin verificar firma A PROPÓSITO y es seguro porque el token ya
    pasó la verificación: repetirla costaría otra operación criptográfica por
    cierre de sesión sin añadir nada.
    """
    import jwt

    cabecera = request.headers.get("authorization", "")
    if not cabecera.lower().startswith("bearer "):
        return None
    try:
        datos = jwt.decode(cabecera[7:], options={"verify_signature": False})
        return UUID(datos["sid"]) if datos.get("sid") else None
    except Exception:  # noqa: BLE001 — cerrar sesión nunca debe fallar por esto
        return None


# ── Compartición (CRM-00.05.02.04) ────────────────────────────────────────

router_comparticion = APIRouter(prefix="/sharing-rules", tags=["compartición"])


class CrearReglaComparticion(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=200)
    objeto: str = Field(..., examples=["account", "opportunity"])
    condiciones: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Misma gramática que ABAC y las automatizaciones. **Vacío comparte "
            "TODO el objeto**: es legítimo, pero es la forma más fácil de abrir "
            "de más sin darse cuenta"
        ),
        examples=[[{"atributo": "provincia", "op": "=", "valor": "Bizkaia"}]],
    )
    combinacion: Literal["todas", "alguna"] = "todas"
    destino_tipo: Literal["usuario", "rol", "unidad_negocio"]
    destino_id: str
    acceso: Literal["lectura", "escritura"] = "lectura"
    activa: bool = True


class CompartirRegistro(BaseModel):
    objeto: str
    registro_id: UUID
    usuario_id: UUID
    acceso: Literal["lectura", "escritura"] = "lectura"
    hasta: date | None = Field(
        None,
        description=(
            "Caducidad. Sin ella, «compártemelo para revisar la propuesta» se "
            "convierte en un acceso permanente"
        ),
    )
    motivo: str = ""


@router_comparticion.post(
    "",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("sharing:write"))],
    summary="Crear una regla de compartición por criterio",
)
def crear_regla_comparticion(
    datos: CrearReglaComparticion, db: DbDep, principal: AutenticadoDep
) -> Any:
    from crmcore.authz.comparticion import ReglaComparticion

    regla = ReglaComparticion(tenant_id=principal.tenant_id, **datos.model_dump())
    db.add(regla)
    db.flush()
    return {"id": str(regla.id), "nombre": regla.nombre, "objeto": regla.objeto}


@router_comparticion.get(
    "",
    response_model=list[dict],
    dependencies=[Depends(exige_permiso("sharing:read"))],
    summary="Reglas de compartición del tenant",
)
def listar_reglas_comparticion(
    db: DbDep, principal: AutenticadoDep, objeto: str = Query("")
) -> Any:
    from crmcore.authz.comparticion import ReglaComparticion

    consulta = select(ReglaComparticion).where(ReglaComparticion.tenant_id == principal.tenant_id)
    if objeto:
        consulta = consulta.where(ReglaComparticion.objeto == objeto)
    return [
        {
            "id": str(r.id),
            "nombre": r.nombre,
            "objeto": r.objeto,
            "destino": f"{r.destino_tipo}:{r.destino_id}",
            "acceso": r.acceso,
            "condiciones": r.condiciones,
            "activa": r.activa,
        }
        for r in db.execute(consulta.order_by(ReglaComparticion.nombre)).scalars().all()
    ]


@router_comparticion.post(
    "/compartir",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("sharing:write"))],
    summary="Compartir un registro concreto con alguien",
)
def compartir_registro(datos: CompartirRegistro, db: DbDep, principal: AutenticadoDep) -> Any:
    from crmcore.authz import comparticion as comp

    fila = comp.compartir(
        db,
        tenant_id=principal.tenant_id,
        objeto=datos.objeto,
        registro_id=datos.registro_id,
        usuario_id=datos.usuario_id,
        acceso=datos.acceso,
        hasta=datos.hasta,
        motivo=datos.motivo,
        por=principal.id,
    )
    db.flush()
    return {"id": str(fila.id), "hasta": fila.hasta.isoformat() if fila.hasta else None}


@router_comparticion.post(
    "/explicar",
    response_model=dict,
    dependencies=[Depends(exige_permiso("sharing:read"))],
    summary="Por qué un usuario ve (o no ve) un registro",
    description=(
        "Devuelve **todos** los motivos, no el primero: quitar una compartición "
        "no cambia nada si además era el propietario, y quien administra "
        "necesita verlo antes de tocar."
    ),
)
def explicar_visibilidad(
    usuario_id: UUID,
    objeto: str,
    registro: dict[str, Any],
    db: DbDep,
    principal: AutenticadoDep,
) -> Any:
    from crmcore.authz import comparticion as comp

    return comp.visibilidad_de(
        db,
        tenant_id=principal.tenant_id,
        usuario_id=usuario_id,
        objeto=objeto,
        registro=registro,
    ).a_dict()


# ── Gestión de usuarios (CRM-07.01.01.02) ─────────────────────────────────


class DesactivarUsuario(BaseModel):
    motivo: str = Field(..., min_length=5)
    transferir_a: UUID | None = Field(
        None,
        description=(
            "A quién pasan sus registros. Sin esto, sus cuentas quedan sin "
            "dueño: invisibles para las reglas de visibilidad por propietario, "
            "sin que nadie las haya borrado"
        ),
    )


@router_usuarios.post(
    "/{usuario_id}/desactivar",
    response_model=dict,
    dependencies=[Depends(exige_permiso("user:write"))],
    summary="Dar de baja a un usuario",
    description=(
        "Desactiva la membresía, corta sus sesiones y **avisa** de lo que hay "
        "que transferir. La transferencia en sí la hace cada servicio sobre sus "
        "objetos: el maestro de cuentas no es de identidad y sus permisos de "
        "base de datos lo impiden."
    ),
)
def desactivar_usuario(
    usuario_id: UUID, datos: DesactivarUsuario, uow: UowDep, principal: AutenticadoDep
) -> Any:
    svc.desactivar_usuario(uow, usuario_id, principal.tenant_id, via="manual")
    return {
        "desactivado": True,
        "usuario_id": str(usuario_id),
        "transferir_a": str(datos.transferir_a) if datos.transferir_a else None,
        "siguiente_paso": (
            "llama a POST /party-admin/transferir-propiedad y al equivalente de "
            "cada servicio con objetos con propietario"
            if datos.transferir_a
            else "sus registros se quedan sin propietario: decide a quién pasan"
        ),
    }


@router_usuarios.get(
    "/licencias",
    response_model=dict,
    dependencies=[Depends(exige_permiso("user:read"))],
    summary="Consumo de licencias del tenant",
    description=(
        "Usuarios activos frente al tope del plan. El tope lo decide `tenancy`; "
        "aquí se cuenta quién ocupa una."
    ),
)
def licencias(db: DbDep, principal: AutenticadoDep) -> Any:
    from sqlalchemy import func as _f

    activos = db.execute(
        select(_f.count())
        .select_from(Membresia)
        .join(Usuario, Usuario.id == Membresia.usuario_id)
        .where(
            Membresia.tenant_id == principal.tenant_id,
            Membresia.activa.is_(True),
            Usuario.activo.is_(True),
        )
    ).scalar_one()
    from crmcore.runtime import settings as rt

    tope = int(rt.efectivo("licencias_maximas", db) or 0)
    return {
        "activos": int(activos),
        "tope": tope,
        "disponibles": max(0, tope - int(activos)) if tope else None,
        "sin_limite": tope == 0,
    }


from services.identity.api_factores import ROUTERS_FACTORES  # noqa: E402
from services.identity.api_politicas import ROUTERS_POLITICAS  # noqa: E402
from services.identity.api_scim import ROUTERS_SCIM  # noqa: E402
from services.identity.api_sod import ROUTERS_SOD  # noqa: E402

ROUTERS = [
    router_auth,
    router_usuarios,
    router_roles,
    router_sesiones,
    router_claves,
    router_comparticion,
    *ROUTERS_NOTIFICACION,
    router_sso,
    router_idp,
    *ROUTERS_POLITICAS,
    *ROUTERS_SOD,
    *ROUTERS_SCIM,
    *ROUTERS_FACTORES,
]
