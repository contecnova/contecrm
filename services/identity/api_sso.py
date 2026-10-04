"""API de inicio de sesión contra proveedores externos.

OIDC (CRM-00.05.01.01) y SAML (CRM-00.05.01.02), más la configuración de los
proveedores del tenant (CRM-00.05.01.03) y el alta automática (CRM-00.05.01.04).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

from crmcore.errors import Conflicto, ErrorValidacion, NoAutenticado, NoEncontrado
from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from crmcore.http.listados import montar_ficha  # noqa: E402
from crmcore.http.pagination import PaginaDeListado, paginar_consulta
from crmcore.logging import get_logger
from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from services.identity import oidc as oidc_cli
from services.identity import organigrama, sso, sso_gobierno
from services.identity import saml as saml_sp
from services.identity.modelos import ProveedorIdentidad

logger = get_logger(__name__)

router_sso = APIRouter(prefix="/sso", tags=["sso"])
router_idp = APIRouter(prefix="/proveedores-identidad", tags=["proveedores de identidad"])


# ── Configuración de proveedores ──────────────────────────────────────────


class CrearProveedor(BaseModel):
    nombre: str = Field(..., max_length=120)
    tipo: str = Field(..., pattern="^(oidc|saml)$")
    dominio_email: str | None = Field(
        None,
        max_length=200,
        description=(
            "Dominio de correo que manda a este proveedor. Es lo que permite "
            "tener varios a la vez —empleados por uno y partners por otro— sin "
            "preguntarle al usuario a cuál quiere ir, que es una pregunta que "
            "nadie sabe contestar."
        ),
    )
    config: dict[str, Any] = Field(
        default_factory=dict,
        examples=[
            {
                "issuer_url": "https://login.microsoftonline.com/<tenant>/v2.0",
                "client_id": "…",
                "client_secret": "…",
                "redirect_uri": "https://crm.cliente.com/api/v1/sso/oidc/callback",
            }
        ],
    )
    mapeo_roles: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Grupo del proveedor → rol de aquí. Un grupo sin correspondencia no "
            "da rol: lo contrario convierte crear un grupo en el IdP en conceder "
            "acceso al CRM."
        ),
        examples=[{"CRM-Comerciales": "comercial", "CRM-Admins": ["admin"]}],
    )
    jit_provisioning: bool = True
    activo: bool = True


class ProveedorOut(BaseModel):
    id: UUID
    nombre: str
    tipo: str
    activo: bool
    dominio_email: str | None
    jit_provisioning: bool
    mapeo_roles: dict[str, Any]
    # `config` NO se devuelve entera: lleva el secreto de cliente y la clave
    # privada del SP. Se devuelve solo qué claves tiene, que es lo que hace
    # falta para saber si está completa.
    claves_config: list[str]


def _salida(fila: ProveedorIdentidad) -> ProveedorOut:
    return ProveedorOut(
        id=fila.id,
        nombre=fila.nombre,
        tipo=fila.tipo,
        activo=fila.activo,
        dominio_email=fila.dominio_email,
        jit_provisioning=fila.jit_provisioning,
        mapeo_roles=dict(fila.mapeo_roles or {}),
        claves_config=sorted(fila.config or {}),
    )


# Claves de configuración cuyo valor es un secreto. Se cifran al guardar y no
# salen nunca por la API.
SECRETAS = {"client_secret", "sp_private_key"}


class AjustesPerfil(BaseModel):
    """Lo que un cliente cambia de un perfil, y nada más.

    Se declara en vez de aceptar un diccionario suelto: un cuerpo sin esquema
    se pinta como un formulario vacío, y entonces quien configura el proveedor
    desde la consola no ve qué puede tocar. Son tres campos, y son justo los
    que cambian entre proveedores — el protocolo no se ajusta, porque es lo que
    el perfil **es**.
    """

    campo_email: str | None = Field(
        None, description="Qué campo del token trae el correo. Sin él no hay identidad usable."
    )
    campo_nombre: str | None = Field(None, description="Qué campo trae el nombre para mostrar.")
    campo_grupos: str | None = Field(
        None,
        description=(
            "Cómo llama este proveedor a los grupos. Equivocarse aquí no da un "
            "error: da un usuario que entra sin permisos."
        ),
    )


@router_idp.get(
    "/perfiles",
    summary="Perfiles de proveedor declarados",
    description=(
        "Lo que cambia entre proveedores de identidad son las direcciones y los "
        "nombres de los campos, y eso es **configuración**: un módulo por casa "
        "—uno para cada proveedor de SSO, otro para cada uno de MFA— convierte "
        "cada implantación nueva en una versión del producto que hay que "
        "mantener diez años.\n\n"
        "Esta ruta faltaba: los perfiles estaban declarados y probados, y **no "
        "los alcanzaba ninguna ruta**, así que quien configuraba un proveedor "
        "tenía que saberse de memoria qué campo trae el correo en el suyo. "
        "Equivocarse ahí no da un error: da un usuario que entra sin grupos y "
        "sin permisos, y nadie lo relaciona con el campo mal escrito."
    ),
)
def listar_perfiles(_: AutenticadoDep) -> Any:
    return {
        "sso": {clave: dict(valor) for clave, valor in sso.PERFILES_SSO.items()},
        "mfa": {clave: dict(valor) for clave, valor in sso.PERFILES_MFA.items()},
        "como_se_anade": (
            "Añadir un perfil es configuración, no código: se declara qué campo "
            "trae el correo, cuál el nombre y cómo llama a los grupos."
        ),
    }


@router_idp.post(
    "/perfiles/{clave}/resolver",
    summary="Resolver un perfil con los ajustes del cliente encima",
    description=(
        "Devuelve la configuración que resultaría, y **dice si está completa**. "
        "Un perfil sin campo de correo deja un usuario sin identidad utilizable: "
        "no es un error visible, es un usuario que no encaja con ninguna cuenta.\n\n"
        "Un perfil desconocido **no cae al genérico en silencio**: se dice."
    ),
)
def resolver_perfil(clave: str, ajustes: AjustesPerfil, _: AutenticadoDep) -> Any:
    # El cuerpo va OBLIGATORIO aunque sus tres campos sean opcionales: con
    # `AjustesPerfil | None` el esquema sale como `anyOf` y la consola, que se
    # construye del contrato, no encuentra los campos — pinta un formulario
    # vacío. Mandar `{}` es perfectamente válido y devuelve el perfil base.
    return sso.perfil_sso(clave, ajustes.model_dump(exclude_none=True))


@router_idp.get("", response_model=PaginaDeListado, summary="Proveedores del tenant")
def listar(
    db: DbDep,
    principal: AutenticadoDep,
    limite: int = Query(50, ge=1, le=200),
    cursor: str = Query(""),
) -> Any:
    return paginar_consulta(
        db,
        ProveedorIdentidad,
        select(ProveedorIdentidad),
        limite=limite,
        cursor=cursor,
        orden="nombre",
        fila_a_dict=_salida,
    )


@router_idp.post(
    "",
    response_model=ProveedorOut,
    status_code=status.HTTP_201_CREATED,
    summary="Configurar un proveedor de identidad",
    dependencies=[Depends(exige_permiso("idp:configurar"))],
)
def crear(datos: CrearProveedor, uow: UowDep, principal: AutenticadoDep) -> Any:
    from crmcore.security.cifrado import cifrar

    ya = uow.db.execute(
        select(ProveedorIdentidad).where(ProveedorIdentidad.nombre == datos.nombre)
    ).scalar_one_or_none()
    if ya is not None:
        raise Conflicto(
            f"Ya hay un proveedor llamado «{datos.nombre}»",
            error_code="idp.nombre_duplicado",
        )

    config = dict(datos.config)
    if datos.tipo == "saml":
        problemas = saml_sp.problemas_de_configuracion(config)
        if problemas:
            # Todos de una vez: quien configura un IdP agradece ver las cuatro
            # cosas que faltan antes que descubrirlas de una en una con un
            # intento de inicio de sesión entre cada dos.
            raise ErrorValidacion(
                "La configuración SAML está incompleta",
                error_code="saml.configuracion_incompleta",
                detalle={"problemas": problemas},
            )
    else:
        faltan = [c for c in ("issuer_url", "client_id", "redirect_uri") if not config.get(c)]
        if faltan:
            raise ErrorValidacion(
                "La configuración OIDC está incompleta",
                error_code="oidc.configuracion_incompleta",
                detalle={"faltan": faltan},
            )

    for clave in SECRETAS:
        if config.get(clave):
            config[clave] = cifrar(str(config[clave]), proposito="idp")

    fila = ProveedorIdentidad(
        tenant_id=uow.tenant_id,
        nombre=datos.nombre,
        tipo=datos.tipo,
        activo=datos.activo,
        dominio_email=datos.dominio_email,
        config=config,
        mapeo_roles=datos.mapeo_roles,
        jit_provisioning=datos.jit_provisioning,
    )
    uow.db.add(fila)
    uow.db.flush()
    return _salida(fila)


@router_idp.post(
    "/{proveedor_id}/comprobar",
    response_model=dict,
    summary="Comprobar que el proveedor responde",
    description=(
        "Lee el documento de descubrimiento y las claves, y dice qué falta. Es "
        "la comprobación que hay que poder hacer **antes** de mandar a nadie a "
        "iniciar sesión: un IdP mal configurado descubierto por el primer "
        "usuario es una mañana perdida."
    ),
    dependencies=[Depends(exige_permiso("idp:configurar"))],
)
def comprobar(proveedor_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    fila = db.get(ProveedorIdentidad, proveedor_id)
    if fila is None:
        raise NoEncontrado("El proveedor no existe", error_code="idp.no_existe")

    if fila.tipo == "saml":
        problemas = saml_sp.problemas_de_configuracion(fila.config or {})
        return {
            "tipo": "saml",
            "libreria_instalada": saml_sp.disponible(),
            "problemas": problemas,
            "listo": saml_sp.disponible() and not problemas,
        }

    proveedor = oidc_cli.desde_modelo(fila)
    oidc_cli.invalidar_cache(proveedor.id)
    documento = oidc_cli._descubrir(proveedor)
    claves = oidc_cli._jwks(proveedor).get("keys") or []
    return {
        "tipo": "oidc",
        "emisor": documento.get("issuer"),
        "claves": len(claves),
        "algoritmos": sorted(
            oidc_cli.ALGORITMOS
            & set(documento.get("id_token_signing_alg_values_supported") or oidc_cli.ALGORITMOS)
        ),
        "soporta_pkce": "S256" in (documento.get("code_challenge_methods_supported") or []),
        "listo": bool(claves),
    }


@router_idp.get(
    "/{proveedor_id}/metadatos-saml",
    summary="Metadatos SAML de nuestro lado",
    description="El XML que hay que darle al administrador del IdP.",
    response_class=Response,
    dependencies=[Depends(exige_permiso("idp:configurar"))],
)
def metadatos_saml(proveedor_id: UUID, db: DbDep) -> Any:
    fila = db.get(ProveedorIdentidad, proveedor_id)
    if fila is None or fila.tipo != "saml":
        raise NoEncontrado(
            "No hay un proveedor SAML con ese identificador", error_code="idp.no_existe"
        )
    return Response(content=saml_sp.metadatos(fila.config or {}), media_type="application/xml")


# ── Flujo de inicio de sesión ─────────────────────────────────────────────


# ── Sesión para las rutas por las que se entra ────────────────────────────


@contextmanager
def _trabajo(tenant_id: UUID) -> Iterator[Any]:
    """Unidad de trabajo para una ruta a la que se llega **sin autenticar**.

    Estas tres rutas no pueden usar `UowDep`: esa dependencia abre la sesión con
    el tenant del principal, y aquí todavía no hay principal —el proveedor de
    identidad llega anónimo, que es como llega siempre—. Con `UowDep`
    contestaban 500, «se ha abierto una sesión sin tenant», **las tres**: el
    SSO no funcionaba de punta a punta y nadie lo había ejercitado nunca.

    Es exactamente lo que ya le pasó a `/auth/login`, que lo dejó escrito en su
    propio comentario. Esto es el mismo patrón.

    El tenant es una **pista sin firmar** y no concede acceso por sí sola: lo
    que concede acceso es la firma de la aserción contra el certificado de ESE
    proveedor de ESE tenant, o el estado de un solo uso que solo emitimos
    nosotros.
    """
    from crmcore.bus.outbox import despertar_relevo
    from crmcore.db.session import sesion
    from crmcore.db.uow import UnidadDeTrabajo

    with sesion(tenant_id) as db:
        uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
        yield uow
        uow._volcar_eventos()
    despertar_relevo()


class Iniciar(BaseModel):
    tenant_id: UUID
    email: str | None = Field(
        None, description="Para elegir proveedor por dominio cuando hay varios"
    )
    proveedor: str | None = Field(None, description="Nombre del proveedor, si se sabe cuál")
    volver_a: str | None = None


@router_sso.post(
    "/iniciar",
    response_model=dict,
    summary="Empezar un inicio de sesión externo",
    description=(
        "Devuelve la URL a la que hay que mandar al usuario. Con OIDC lleva "
        "**PKCE siempre**, incluso habiendo secreto de cliente: OAuth 2.1 lo "
        "exige para todos los clientes, y sin él quien intercepte el código —en "
        "un log de proxy, en un `Referer`— puede canjearlo."
    ),
)
def iniciar(datos: Iniciar) -> Any:
    with _trabajo(datos.tenant_id) as uow:
        return _iniciar(datos, uow)


def _iniciar(datos: Iniciar, uow: Any) -> Any:
    fila = sso.proveedor_para(uow.db, datos.tenant_id, email=datos.email, nombre=datos.proveedor)

    if fila.tipo == "saml":
        inicio = saml_sp.url_de_inicio(fila.config or {}, volver_a=datos.volver_a)
        # SE GUARDA, igual que el `state` de OIDC y por lo mismo: es lo que ata
        # la respuesta a esta petición y lo que la hace de un solo uso. Antes se
        # tiraba, y entonces la vuelta no se comparaba con nada.
        sso.guardar_estado(
            uow.db,
            tenant_id=datos.tenant_id,
            proveedor_id=fila.id,
            estado=inicio.id_peticion,
            nonce="",
            verificador="",
            volver_a=datos.volver_a,
        )
        return {"tipo": "saml", "url": inicio.url, "proveedor": fila.nombre}

    proveedor = oidc_cli.desde_modelo(fila)
    autorizacion = oidc_cli.construir_autorizacion(proveedor)
    sso.guardar_estado(
        uow.db,
        tenant_id=datos.tenant_id,
        proveedor_id=fila.id,
        estado=autorizacion.estado,
        nonce=autorizacion.nonce,
        verificador=autorizacion.verificador,
        volver_a=datos.volver_a,
    )
    return {"tipo": "oidc", "url": autorizacion.url, "proveedor": fila.nombre}


class VueltaOIDC(BaseModel):
    code: str
    state: str


@router_sso.post(
    "/oidc/callback",
    response_model=dict,
    summary="Vuelta del proveedor OIDC",
    description=(
        "Canjea el código, verifica el token de identidad —firma, emisor, "
        "audiencia, vigencia y nonce— y deja al usuario dentro. El estado es de "
        "**un solo uso**: sin eso, quien capture la respuesta la reenvía y entra."
    ),
)
def callback_oidc(datos: VueltaOIDC) -> Any:
    # El tenant vive DENTRO del estado, así que hay que mirarlo antes de
    # poder abrir la sesión. Se mira sin gastarlo: el vale se quema dentro de
    # la transacción que completa la entrada, y si esa falla no se pierde.
    with _trabajo(sso.tenant_del_estado(datos.state)) as uow:
        return _callback_oidc(datos, uow)


def _callback_oidc(datos: VueltaOIDC, uow: Any) -> Any:
    estado = sso.consumir_estado(uow.db, datos.state)
    fila = uow.db.get(ProveedorIdentidad, estado.proveedor_id)
    if fila is None or not fila.activo:
        raise NoEncontrado(
            "El proveedor de este inicio de sesión ya no está activo",
            error_code="sso.proveedor_inactivo",
        )

    proveedor = oidc_cli.desde_modelo(fila)
    tokens = oidc_cli.canjear(proveedor, codigo=datos.code, verificador=estado.verificador)
    claims = oidc_cli.verificar_id_token(proveedor, tokens.id_token, nonce=estado.nonce)

    usuario = sso.entrar_o_provisionar(
        uow.db,
        tenant_id=estado.tenant_id,
        proveedor=proveedor,
        email=str(claims.get("email") or ""),
        nombre=str(claims.get("name") or claims.get("preferred_username") or ""),
        sujeto_externo=str(claims["sub"]),
        grupos=oidc_cli.grupos_de(claims),
    )
    # El IdP recalcula los roles en CADA entrada, así que el organigrama se
    # vuelve a publicar aquí: si solo se publicara al crear el usuario, quien
    # cambia de departamento seguiría apareciendo como aprobador del anterior.
    organigrama.publicar(uow, estado.tenant_id, usuario.id)
    return _entrada(
        uow,
        usuario,
        estado.tenant_id,
        fila.nombre,
        estado.volver_a,
        fila=fila,
        claims=claims,
        # `sid` es el identificador de sesión del IdP en OIDC; sin él, el aviso
        # de cierre solo puede resolverse por sujeto.
        indice_idp=str(claims.get("sid") or ""),
        sujeto_idp=str(claims.get("sub") or ""),
    )


@router_sso.post(
    "/saml/acs",
    response_model=dict,
    summary="Vuelta del proveedor SAML",
    description=(
        "La firma de la aserción la valida `python3-saml`, no este código: "
        "comprobar una firma XML a mano es un campo de minas conocido, y una "
        "implementación propia que funciona con las aserciones de prueba es "
        "exactamente por donde se cuela una falsificada."
    ),
)
async def acs_saml(
    peticion: Request,
    tenant_id: UUID = Query(...),
    proveedor: str | None = Query(None),
) -> Any:
    formulario = dict(await peticion.form())
    with _trabajo(tenant_id) as uow:
        return _acs_saml(formulario, uow, tenant_id, proveedor)


def _acs_saml(formulario: dict[str, Any], uow: Any, tenant_id: UUID, proveedor: str | None) -> Any:
    fila = sso.proveedor_para(uow.db, tenant_id, nombre=proveedor)
    if fila.tipo != "saml":
        raise ErrorValidacion("Ese proveedor no es SAML", error_code="saml.proveedor_no_es_saml")

    # Hay dos vías y cada una se cierra de una forma. Si la aserción cita una
    # petición, esa petición tiene que constar como nuestra y se gasta al usarla.
    # Si no cita ninguna, empieza en el IdP: eso va apagado por defecto y se
    # apunta la aserción para que no valga dos veces.
    citada = saml_sp.en_respuesta_a(formulario)
    if citada:
        estado = sso.consumir_estado(uow.db, citada)
        if estado.proveedor_id != fila.id or estado.tenant_id != tenant_id:
            # Un inicio abierto con un proveedor no puede cerrarse con otro: si
            # no, un tenant con un IdP propio podría cerrar el inicio de otro.
            raise NoAutenticado(
                "Ese inicio de sesión no es de este proveedor",
                error_code="sso.estado_de_otro_proveedor",
            )

    correo, nombre, grupos, contexto = saml_sp.procesar_respuesta(
        fila.config or {}, formulario, id_peticion=citada or None
    )

    if not citada:
        sso_gobierno.admitir_asercion_idp(
            uow.db,
            fila,
            id_asercion=contexto.get("id_asercion", ""),
            no_despues_de=_momento(contexto.get("no_despues_de", "")),
            en_respuesta_a=contexto.get("en_respuesta_a") or None,
        )
    usuario = sso.entrar_o_provisionar(
        uow.db,
        tenant_id=tenant_id,
        proveedor=_como_proveedor(fila),
        email=correo,
        nombre=nombre,
        sujeto_externo=correo,
        grupos=grupos,
    )
    organigrama.publicar(uow, tenant_id, usuario.id)
    return _entrada(
        uow,
        usuario,
        tenant_id,
        fila.nombre,
        None,
        fila=fila,
        claims={"authn_context": contexto.get("authn_context", "")},
        indice_idp=str(contexto.get("session_index") or ""),
        sujeto_idp=str(contexto.get("name_id") or correo),
    )


def _momento(texto: str) -> Any:
    """El `NotOnOrAfter` de la aserción, tal como lo da la librería.

    `python3-saml` lo devuelve como **marca de tiempo unix**, no como texto ISO:
    lo pasa por `parse_SAML_to_time`, que documenta `rtype: int`. Leerlo como
    ISO fallaría siempre, en silencio, y la aserción se quedaría con la ventana
    por defecto sin que nadie se enterara — que es peor que no leerlo, porque
    parece que se lee.

    Si no viene o no se entiende se devuelve `None` y el registro de aserciones
    pone su propia ventana: quedarse sin ventana por no saber leer una fecha
    sería aceptar la aserción para siempre.
    """
    from datetime import datetime, timezone

    if not texto:
        return None
    try:
        return datetime.fromtimestamp(float(texto), tz=timezone.utc)
    except (ValueError, OverflowError, OSError):
        logger.warning("saml.no_despues_de_ilegible", valor=texto[:60])
        return None


def _como_proveedor(fila: ProveedorIdentidad) -> Any:
    """Vista mínima de un proveedor SAML con lo que `sso` necesita.

    SAML no tiene `client_id` ni descubrimiento, así que no encaja en el
    `Proveedor` de OIDC. Se pasa un objeto con los tres campos que el tramo
    común mira, en vez de forzar una estructura que sobra en la mitad de sus
    campos.
    """
    from types import SimpleNamespace

    return SimpleNamespace(
        nombre=fila.nombre,
        jit=fila.jit_provisioning,
        mapeo_roles=dict(fila.mapeo_roles or {}),
    )


def _entrada(
    uow: Any,
    usuario: Any,
    tenant_id: UUID,
    proveedor: str,
    volver_a: str | None,
    *,
    fila: Any = None,
    claims: dict[str, Any] | None = None,
    indice_idp: str = "",
    sujeto_idp: str = "",
) -> Any:
    """Abre sesión y devuelve los tokens, igual que el inicio de sesión local.

    Pasa por `crear_sesion` y no por un camino propio: ahí viven el tope de
    sesiones concurrentes, la caducidad y la revocación. Un inicio de sesión por
    SSO que se saltara eso tendría sesiones que no se pueden cortar.
    """
    from crmcore.audit.chain import registrar
    from crmcore.config import get_settings

    # ¿El IdP ya exigió segundo factor? (CRM-00.05.01.24). Solo se cree si el
    # proveedor declara qué valores de `acr`/`amr` cuentan: cualquier IdP puede
    # mandar un `amr` que diga lo que sea, y aceptarlo sin acuerdo previo
    # convierte la MFA en una casilla que rellena el otro lado.
    from services.identity import factores as _factores
    from services.identity import servicio as svc

    mfa_del_idp = bool(
        fila is not None and claims and _factores.el_idp_ya_hizo_mfa(uow.db, fila, claims)
    )
    superados = ("sso", "idp") if mfa_del_idp else ("sso",)

    _sesion, acceso, refresco = svc.crear_sesion(
        uow.db, usuario=usuario, tenant_id=tenant_id, factores_superados=superados
    )

    # Atar la sesión a la del IdP para el cierre único (CRM-00.05.01.12). Sin
    # esto, el aviso de cierre llega con el identificador del proveedor y no hay
    # a quién aplicárselo: salir del IdP dejaría el CRM abierto.
    enlazada = False
    if fila is not None and (indice_idp or sujeto_idp):
        from services.identity import sso_gobierno

        enlazada = (
            sso_gobierno.atar_sesion_al_idp(
                uow.db,
                sesion=_sesion,
                proveedor_id=fila.id,
                usuario_id=usuario.id,
                tenant_id=tenant_id,
                indice_idp=indice_idp,
                sujeto_idp=sujeto_idp,
            )
            is not None
        )

    registrar(
        uow.db,
        accion="sesion.iniciada",
        objeto="usuario",
        objeto_id=usuario.id,
        datos={
            "via": "sso",
            "proveedor": proveedor,
            "mfa_del_idp": mfa_del_idp,
            # Se anota cuando NO se puede propagar el cierre: es una carencia
            # del proveedor, no un fallo de aquí, y sin dejarla escrita se
            # descubre el día que alguien se queja de que salir no sirve.
            "cierre_unico": enlazada,
        },
        tenant_id=tenant_id,
    )
    return {
        "access_token": acceso,
        "refresh_token": refresco,
        "expires_in": get_settings().access_token_minutos * 60,
        "volver_a": volver_a,
    }


# ── La ficha del registro ─────────────────────────────────────────────────
# Sin ella, las acciones que cuelgan de un registro no se alcanzan desde
# ninguna pantalla: existen, se prueban y nadie las usa.


# ── SSO compartido por la suite (CRM-00.01.07.09) ─────────────────────────


@router_idp.get(
    "/suite",
    dependencies=[Depends(exige_permiso("idp:configurar"))],
    summary="Qué herramientas de la suite comparten de verdad este proveedor",
    description=(
        "El proveedor se configura **una vez** y lo usan todas las herramientas "
        "cableadas contra él. Repetirlo en cada una es cómo se acaba con tres "
        "certificados distintos, dos caducados y nadie sabiendo cuál es el "
        "bueno.\n\n"
        "Lo que se publica es el **estado real y no la intención**: una "
        "herramienta que dice estar conectada y tiene otro certificado no "
        "comparte el SSO, tiene el suyo, y el día que el cliente rote el "
        "certificado se cae sólo esa sin que nadie entienda por qué.\n\n"
        "Las herramientas se declaran en la configuración del proveedor, en "
        "`herramientas: {nombre: {conectada, huella_certificado}}`."
    ),
)
def sso_de_la_suite(db: DbDep, principal: AutenticadoDep) -> Any:
    from services.identity import sso_gobierno

    return sso_gobierno.plan_de_sso_compartido(db, principal.tenant_id)


montar_ficha(
    router_idp,
    modelo=ProveedorIdentidad,
    objeto="proveedor_identidad",
    permiso_leer="idp:configurar",
    permiso_escribir="idp:configurar",
    nombre="Proveedores de identidad",
    parametro="proveedor_id",
)
