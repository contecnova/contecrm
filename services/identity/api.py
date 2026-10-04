"""API HTTP del servicio de identidad."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Literal
from uuid import UUID

from crmcore.config import get_settings
from crmcore.errors import NoAutenticado, NoEncontrado
from crmcore.http.deps import (
    AutenticadoDep,
    DbDep,
    UowDep,
    exige_firma_interna,
    exige_permiso,
)
from crmcore.http.pagination import PaginaDeListado, paginar_consulta
from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select

from services.identity import servicio as svc
from services.identity.api_chat import ROUTERS_CHAT
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


# ── Olvidé la contraseña (CRM-00.05.01.26) ────────────────────────────────


class PedirRestablecer(BaseModel):
    email: EmailStr
    tenant: str = Field(..., min_length=1, max_length=120)


@router_auth.post(
    "/restablecer",
    summary="Pedir un enlace para cambiar la contraseña",
    description=(
        "La respuesta es **la misma exista o no** ese correo. Distinguirlas "
        "convertiría esta pantalla en un comprobador de qué correos tienen "
        "cuenta aquí, que es exactamente la lista que quiere quien va a "
        "intentar entrar.\n\n"
        "El token se devuelve para que lo mande quien integre el correo; nunca "
        "se le enseña a quien lo pide."
    ),
)
def pedir_restablecer(datos: PedirRestablecer, request: Request) -> Any:
    from crmcore.db.session import sesion
    from crmcore.db.uow import UnidadDeTrabajo

    from services.identity import restablecer as rst

    tenant_id = _resolver_tenant(datos.tenant)
    with sesion(tenant_id) as db:
        uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
        token = rst.solicitar(
            uow, email=datos.email, ip=request.client.host if request.client else ""
        )
    return {"enviado": True, "token": token}


class ConfirmarRestablecer(BaseModel):
    token: str = Field(..., min_length=1, max_length=200)
    contrasena: str = Field(..., min_length=1, max_length=200)


@router_auth.post(
    "/restablecer/confirmar",
    summary="Cambiar la contraseña con el enlace recibido",
    description=(
        "De un solo uso. Un token inexistente, usado o caducado dan **el mismo "
        "error**.\n\n"
        "Al cambiarla se **cierran todas las sesiones**: quien pide restablecer "
        "no puede entrar, o sospecha, y dejar abiertas las que había es dejar "
        "dentro justo a quien lo motivó."
    ),
)
def confirmar_restablecer(datos: ConfirmarRestablecer, request: Request) -> Any:
    # Sesión de sistema: quien llega aquí no ha entrado, así que no hay tenant
    # en el contexto. Lo que acota es el token, como en el refresco.
    from crmcore.db.session import sesion

    from services.identity import restablecer as rst

    with sesion(sistema=True) as db:
        usuario_id = rst.confirmar(
            db,
            datos.token,
            contrasena=datos.contrasena,
            ip=request.client.host if request.client else "",
        )
    return {"cambiada": True, "usuario_id": str(usuario_id)}


# ── Passkeys (CRM-00.05.01.23) ────────────────────────────────────────────


class PedirPasskey(BaseModel):
    """Para empezar a entrar con una llave.

    El correo es **opcional**: con llaves residentes el dispositivo ya sabe
    cuál es la suya, y no pedirlo evita además que esta pantalla diga si un
    correo tiene cuenta.
    """

    tenant: str = Field(..., min_length=1, max_length=120)
    email: str = Field("", max_length=320)


@router_auth.post(
    "/passkeys/entrar",
    summary="Empezar a entrar con una passkey",
    description=(
        "Devuelve el reto que firma el dispositivo. Vale **una sola vez** y "
        "caduca en minutos: si no, una firma capturada se podría reproducir, "
        "que es justo el ataque del que protege esto."
    ),
)
def empezar_passkey(datos: PedirPasskey) -> Any:
    from crmcore.db.session import sesion

    from services.identity import passkeys as pk
    from services.identity.modelos import Usuario

    tenant_id = _resolver_tenant(datos.tenant)
    with sesion(tenant_id) as db:
        usuario = None
        if datos.email.strip():
            from sqlalchemy import select as _select

            usuario = db.execute(
                _select(Usuario).where(
                    Usuario.email == datos.email.strip().lower(), Usuario.activo.is_(True)
                )
            ).scalar_one_or_none()
        # Si el correo no existe se devuelve un reto igualmente, sin llaves
        # permitidas: el navegador dirá que no hay ninguna y quien prueba no se
        # entera de si esa cuenta existe.
        return pk.opciones_entrada(db, tenant_id=tenant_id, usuario=usuario)


class FirmaPasskey(BaseModel):
    tenant: str = Field(..., min_length=1, max_length=120)
    respuesta: dict[str, Any]


@router_auth.post(
    "/passkeys/entrar/confirmar",
    response_model=Tokens,
    summary="Entrar con la firma de la passkey",
)
def entrar_con_passkey(datos: FirmaPasskey, request: Request) -> Any:
    from crmcore.db.session import sesion

    from services.identity import passkeys as pk

    tenant_id = _resolver_tenant(datos.tenant)
    with sesion(tenant_id) as db:
        llave = pk.verificar_entrada(
            db, respuesta=datos.respuesta, ip=request.client.host if request.client else ""
        )
        from services.identity.modelos import Usuario

        usuario = db.get(Usuario, llave.usuario_id)
        if usuario is None or not usuario.activo:
            from crmcore.errors import NoAutenticado

            raise NoAutenticado("Esa llave no vale aquí", error_code="passkey.usuario_inactivo")

        # EL SSO FORZADO TAMBIÉN AQUÍ (CRM-00.05.01.13). No se comprobaba: de
        # las tres puertas que abren sesión, solo la contraseña lo miraba.
        #
        # Y es la vía de escape que más importa, porque la passkey es una
        # credencial **local**: vive en el dispositivo y en nuestra base, no en
        # el directorio del cliente. Quien causa baja en el directorio pierde el
        # SSO y conserva su passkey, así que seguía entrando — que es
        # exactamente lo único que forzar el SSO viene a impedir.
        #
        # Que sea más fuerte que una contraseña no cambia nada: lo que se exige
        # no es fortaleza, es que dar de baja a alguien corte el acceso.
        from services.identity.sso_gobierno import exigir_sso_si_toca

        exigir_sso_si_toca(db, usuario, tenant_id)
        # Una passkey con verificación del usuario es más fuerte que una
        # contraseña: se anota como tal para la reautenticación reforzada, que
        # pregunta cuándo fue el último factor fuerte.
        _sesion, acceso, refresco = svc.crear_sesion(
            db,
            usuario=usuario,
            tenant_id=tenant_id,
            ip=request.client.host if request.client else "",
            user_agent=request.headers.get("user-agent", ""),
            factores_superados=("webauthn",),
        )
    return Tokens(
        access_token=acceso,
        refresh_token=refresco,
        expires_in=get_settings().access_token_minutos * 60,
    )


class NombrePasskey(BaseModel):
    nombre: str = Field("", max_length=120)


@router_auth.post(
    "/passkeys",
    summary="Empezar a registrar una passkey",
    description=(
        "Se le pasan al navegador las llaves que ya tiene esta cuenta para que "
        "**no registre dos veces el mismo dispositivo**: quien pulsa el botón "
        "dos veces acabaría con dos llaves idénticas y una lista que no dice "
        "nada."
    ),
)
def empezar_registro_passkey(db: DbDep, principal: AutenticadoDep) -> Any:
    from services.identity import passkeys as pk
    from services.identity.modelos import Usuario

    usuario = db.get(Usuario, principal.id)
    if usuario is None:
        raise NoEncontrado("Ese usuario no existe", error_code="identity.usuario_no_encontrado")
    return pk.opciones_registro(db, tenant_id=principal.tenant_id, usuario=usuario)


class RegistroPasskey(BaseModel):
    respuesta: dict[str, Any]
    nombre: str = Field("", max_length=120)


@router_auth.post(
    "/passkeys/confirmar",
    status_code=status.HTTP_201_CREATED,
    summary="Guardar la passkey recién creada",
)
def confirmar_registro_passkey(
    datos: RegistroPasskey, uow: UowDep, principal: AutenticadoDep
) -> Any:
    from services.identity import passkeys as pk

    fila = pk.guardar_registro(
        uow, usuario_id=principal.id, respuesta=datos.respuesta, nombre=datos.nombre
    )
    return {"id": str(fila.id), "nombre": fila.nombre}


@router_auth.get(
    "/passkeys",
    response_model=list[dict],
    summary="Mis passkeys",
    description=(
        "Con su nombre y cuándo se usó por última vez: sin eso, revocar una de "
        "tres es elegir a ciegas."
    ),
)
def mis_passkeys(db: DbDep, principal: AutenticadoDep) -> Any:
    from services.identity import passkeys as pk

    return pk.listar(db, principal.id)


@router_auth.delete(
    "/passkeys/{passkey_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Quitar una passkey",
    description=(
        "Se borra de verdad, no va a la papelera: una credencial revocada que "
        "sigue guardada invita a restaurarla, y restaurar una credencial es "
        "justo lo que no puede pasar."
    ),
)
def quitar_passkey(passkey_id: UUID, uow: UowDep, principal: AutenticadoDep) -> None:
    from services.identity import passkeys as pk

    pk.revocar(uow, usuario_id=principal.id, passkey_id=passkey_id)


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
    response_model=PaginaDeListado,
    dependencies=[Depends(exige_permiso("user:read"))],
    summary="Usuarios del tenant",
    description=(
        "Por páginas con cursor. Antes devolvía la lista entera sin tope: en un "
        "tenant de diez mil personas eso es diez mil filas en una respuesta, y el "
        "navegador que la pide se queda parado sin que nadie sepa por qué."
    ),
)
def listar_usuarios(
    db: DbDep,
    principal: AutenticadoDep,
    limite: int = Query(50, ge=1, le=200),
    cursor: str = Query(""),
) -> Any:
    # Se une por membresía y no se listan los usuarios a secas: `Usuario` es una
    # de las dos tablas sin `tenant_id`, así que aquí el aislamiento lo pone
    # esta unión y no el guard. El gate de alcance lo comprueba.
    consulta = (
        select(Usuario)
        .join(Membresia, Membresia.usuario_id == Usuario.id)
        .where(Membresia.tenant_id == principal.tenant_id)
    )
    # Por correo y no por fecha: es el orden con el que se busca a una persona en
    # una lista, y el cursor tiene que ir por la misma columna que el orden.
    return paginar_consulta(
        db, Usuario, consulta, limite=limite, cursor=cursor, orden="email", modelo_salida=UsuarioOut
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


@router_roles.get("", response_model=PaginaDeListado, summary="Roles del tenant")
def listar_roles(
    db: DbDep,
    principal: AutenticadoDep,
    limite: int = Query(50, ge=1, le=200),
    cursor: str = Query(""),
) -> Any:
    consulta = select(RolTenant).where(RolTenant.tenant_id == principal.tenant_id)
    return paginar_consulta(
        db, RolTenant, consulta, limite=limite, cursor=cursor, orden="nombre", modelo_salida=RolOut
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


@router_sesiones.get("", response_model=PaginaDeListado, summary="Mis sesiones activas")
def mis_sesiones(
    db: DbDep,
    principal: AutenticadoDep,
    limite: int = Query(50, ge=1, le=200),
    cursor: str = Query(""),
) -> Any:
    consulta = select(Sesion).where(
        Sesion.usuario_id == principal.id,
        Sesion.revocada_at.is_(None),
        Sesion.expira_at > datetime.now(timezone.utc),
    )
    return paginar_consulta(
        db,
        Sesion,
        consulta,
        limite=limite,
        cursor=cursor,
        orden="-ultima_actividad_at",
        modelo_salida=SesionOut,
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
    response_model=PaginaDeListado,
    dependencies=[Depends(exige_permiso("apikey:read"))],
    summary="Claves de API del tenant",
)
def listar_claves(
    db: DbDep,
    principal: AutenticadoDep,
    limite: int = Query(50, ge=1, le=200),
    cursor: str = Query(""),
) -> Any:
    consulta = select(ClaveApi).where(ClaveApi.tenant_id == principal.tenant_id)
    return paginar_consulta(
        db, ClaveApi, consulta, limite=limite, cursor=cursor, modelo_salida=ClaveApiOut
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


class ClaveInterna(BaseModel):
    """Lo que otro servicio de la casa pide para poder leer el CRM por su API."""

    tenant_id: UUID
    nombre: str = "contecintelligence"
    # Días de vida. Una credencial de integración de larga vida es una decisión,
    # así que se escribe y no se hereda de un valor por defecto escondido.
    dias: int = 365


@router_claves.post(
    "/interna",
    response_model=ClaveApiCreada,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_firma_interna)],
    include_in_schema=False,
    summary="Clave de solo lectura para otro servicio de la casa (interno)",
)
def crear_clave_interna(datos: ClaveInterna) -> Any:
    """Emite una clave `solo_lectura` para un tenant, sin pasar por una persona.

    Existe para que registrar el CRM como fuente consultable pueda ser un BOTÓN.
    contecintelligence necesita una credencial con la que leer, y las únicas
    formas de dársela eran pegarla a mano en su formulario —que es justo lo que
    no puede pedírsele a nadie— o que un operador ejecutara un script.

    `solo_lectura` es `*:read`: lo que ve esa clave es exactamente lo que ve un
    lector del CRM. No hay forma de pedir una con más.

    Si ya hay una con ese nombre y sin revocar, se **rota**: el secreto anterior
    deja de valer y se devuelve el nuevo. Acumular una credencial por cada vez
    que alguien pulsa el botón es una forma silenciosa de repartir llaves.
    """
    from crmcore.db.session import sesion

    with sesion(sistema=True) as db:
        previas = (
            db.execute(
                select(ClaveApi).where(
                    ClaveApi.tenant_id == datos.tenant_id,
                    ClaveApi.nombre == datos.nombre,
                    ClaveApi.revocada_at.is_(None),
                )
            )
            .scalars()
            .all()
        )
        for vieja in previas:
            vieja.revocada_at = datetime.now(timezone.utc)
        clave, secreto = svc.crear_clave_api(
            db,
            tenant_id=datos.tenant_id,
            nombre=datos.nombre,
            scopes=[],
            rol="solo_lectura",
            dias=datos.dias,
            ips_permitidas=[],
            creada_por=None,
        )
        db.flush()
        return ClaveApiCreada(
            id=clave.id,
            nombre=clave.nombre,
            prefijo=clave.prefijo,
            secreto=secreto,
            expira_at=clave.expira_at,
        )


class ValidarClaveApi(BaseModel):
    """Lo que el gateway pregunta para poder dejar pasar una clave de API."""

    secreto: str
    # La dirección de quien llama, para la lista de redes admitidas de la clave.
    # La resuelve el gateway, que es quien ve la conexión de verdad.
    ip: str = ""


class ClaveApiValidada(BaseModel):
    """La identidad que representa esa clave, ya resuelta.

    Se devuelven los PERMISOS y no solo el rol: quien pregunta es el gateway, y
    el gateway no conoce el catálogo de roles de cada tenant —ni debe—. Resolver
    ahí obligaría a leer el esquema de identity desde otro servicio, que es
    justo lo que el contrato de arquitectura prohíbe.
    """

    clave_id: UUID
    tenant_id: UUID
    nombre: str
    rol: str
    scopes: list[str]
    permisos: list[str]


@router_claves.post(
    "/validar",
    response_model=ClaveApiValidada,
    dependencies=[Depends(exige_firma_interna)],
    include_in_schema=False,
    summary="Validar una clave de API (interno, solo el gateway)",
)
def validar_clave(datos: ValidarClaveApi) -> Any:
    """Convierte el secreto de una clave en la identidad que representa.

    **Esto es lo que faltaba para que las claves de API sirvieran de algo.**
    `svc.validar_clave_api` estaba escrita, probada y completa —incluida la
    comprobación de redes admitidas— y no la llamaba NADIE: se podían crear
    credenciales de máquina y ninguna autenticaba nada. Una clave recién creada
    contestaba 401 en cualquier ruta.

    Va detrás de la firma interna y fuera del contrato público: es una ruta entre
    el gateway e identity, no algo que nadie de fuera deba poder llamar. Sin el
    secreto compartido no se entra, y con él ya se podría entrar como cualquiera.

    Y la sesión es de SISTEMA: la clave se busca por su hash sin saber todavía de
    qué tenant es —averiguarlo es precisamente lo que se está pidiendo—, así que
    con una sesión de tenant la RLS no la encontraría nunca.
    """
    from crmcore.db.session import sesion

    with sesion(sistema=True) as db:
        clave = svc.validar_clave_api(db, datos.secreto, ip=datos.ip)
        permisos = svc.permisos_de_rol(db, clave.rol, clave.tenant_id)
        return ClaveApiValidada(
            clave_id=clave.id,
            tenant_id=clave.tenant_id,
            nombre=clave.nombre,
            rol=clave.rol,
            scopes=list(clave.scopes or []),
            permisos=sorted(permisos),
        )


# ── Utilidades internas ───────────────────────────────────────────────────


def _resolver_tenant(valor: str) -> UUID:
    """Traduce el slug o el identificador del tenant a UUID.

    La implementación vive en `crmcore.http.interno` porque lo necesitan todas
    las puertas de entrada y hay más de una —el portal del partner tropezó con
    lo mismo—. Dos implementaciones de «¿de qué tenant es este nombre?» divergen
    siempre, y la que se queda atrás es la puerta por la que se entra.
    """
    from crmcore.http.interno import resolver_tenant

    return resolver_tenant(valor)


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
    response_model=PaginaDeListado,
    dependencies=[Depends(exige_permiso("sharing:read"))],
    summary="Reglas de compartición del tenant",
)
def listar_reglas_comparticion(
    db: DbDep,
    principal: AutenticadoDep,
    objeto: str = Query(""),
    limite: int = Query(50, ge=1, le=200),
    cursor: str = Query(""),
) -> Any:
    from crmcore.authz.comparticion import ReglaComparticion

    consulta = select(ReglaComparticion).where(ReglaComparticion.tenant_id == principal.tenant_id)
    if objeto:
        consulta = consulta.where(ReglaComparticion.objeto == objeto)
    return paginar_consulta(
        db,
        ReglaComparticion,
        consulta,
        limite=limite,
        cursor=cursor,
        orden="nombre",
        fila_a_dict=lambda r: {
            "id": str(r.id),
            "nombre": r.nombre,
            "objeto": r.objeto,
            "destino": f"{r.destino_tipo}:{r.destino_id}",
            "acceso": r.acceso,
            "condiciones": r.condiciones,
            "activa": r.activa,
        },
    )


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
    *ROUTERS_CHAT,
]
