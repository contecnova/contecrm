"""API HTTP del servicio de identidad."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.config import get_settings
from crmcore.errors import NoAutenticado, NoEncontrado
from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select

from services.identity import servicio as svc
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
        )
        _sesion, acceso, refresco = svc.crear_sesion(
            db,
            usuario=usuario,
            tenant_id=tenant_id,
            ip=request.client.host if request.client else "",
            user_agent=request.headers.get("user-agent", ""),
        )
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
    from crmcore.authz.abac import POLITICAS_EJEMPLO, evaluar

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
    decision = evaluar(
        [p for p in POLITICAS_EJEMPLO if p.activa],
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


ROUTERS = [router_auth, router_usuarios, router_roles, router_sesiones, router_claves]
