"""La sesión de quien entra desde fuera: cliente o proveedor (CRM-04.03.02.01).

    @router.get("/portal/mis-casos")
    def mis_casos(acceso: PortalDep, db: DbDep): ...

El portal se diseñó **headless**: la API sirve datos para que cada cliente monte
su portal con su marca. Eso sigue valiendo, y por eso las rutas de
administración del portal —dar acceso, revocarlo, emitir el enlace— las llama un
empleado con su sesión del CRM.

Lo que faltaba es lo otro: que **el cliente pueda entrar él**. Todas las rutas
del portal exigían un principal del CRM y recibían el `acceso_id` por la URL,
así que un cliente final no podía usarlas —no tiene sesión de empleado— y quien
quisiera un portal tenía que escribir un intermediario que guardase credenciales
de empleado para servir a sus clientes. Eso no es un portal: es una credencial
de empleado compartida por internet.

**El token de portal no es el de un empleado**, y la diferencia es lo que lo
hace seguro:

* No lleva permisos. Un token sin permisos no puede llamar a ninguna ruta del
  CRM, porque todas exigen uno; la puerta se cierra sola en vez de depender de
  que nadie monte una ruta sin `exige_permiso`.
* Lleva el **acceso** y no el contacto: qué se puede ver lo decide el nivel del
  acceso, que ya está resuelto en el servidor.
* Dura poco y se renueva entrando otra vez con el enlace, porque un portal se
  usa a ratos y un token largo en el navegador de un cliente es un token que
  acaba en un correo reenviado.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, Header, Request

from crmcore.errors import NoAutenticado

# Cuánto dura la sesión del portal. Corta: se entra con el enlace, se hace lo
# que se iba a hacer y se sale. Alargarla no ahorra un paso —el enlace se pide
# igual— y sí alarga la ventana si el navegador es compartido.
MINUTOS = 60

TIPO = "portal"


def emitir_token_portal(
    *,
    acceso_id: UUID,
    tenant_id: UUID,
    nivel: str,
    cuenta_id: UUID | None = None,
    secciones: list[str] | None = None,
) -> tuple[str, int]:
    """El token con el que el cliente llama al portal. Devuelve también cuánto dura."""
    import jwt

    from crmcore.config import get_settings

    s = get_settings()
    ahora = datetime.now(timezone.utc)
    carga = {
        "sub": str(acceso_id),
        "tenant": str(tenant_id),
        "tipo": TIPO,
        "nivel": nivel,
        # La empresa del contacto va en el token, y no es un capricho: lo que un
        # proveedor ve de sí mismo lo sirve `party`, que no puede preguntarle a
        # `service` de qué cuenta es este acceso —los servicios no se llaman
        # entre sí—. Yendo firmada aquí, cada servicio sirve lo suyo sin
        # consultar a nadie y sin fiarse de lo que diga el cliente.
        "cuenta": str(cuenta_id) if cuenta_id else "",
        # Qué puede abrir, FIRMADO. Va en el token por lo mismo que la cuenta: el
        # portal lo sirven varios servicios —los contratos y los pedidos son de
        # `sales`, los contactos de `party`— y ninguno puede leer la tabla de
        # accesos, que es de `service`. Sin esto, la comprobación de sección sólo
        # podía hacerse en el servicio dueño del acceso, y en los demás no se
        # hacía: el portal quedaba filtrado en el cliente, que es un filtro de
        # pantalla, no un control.
        "secciones": sorted(set(secciones or [])),
        # Sin `permisos` y sin `roles` **a propósito**: es lo que impide que este
        # token sirva para nada del CRM.
        "iat": int(ahora.timestamp()),
        "exp": int((ahora + timedelta(minutes=MINUTOS)).timestamp()),
    }
    token = jwt.encode(carga, s.secret_key.get_secret_value(), algorithm=s.jwt_algorithm)
    return token, MINUTOS * 60


def _carga(token: str) -> dict[str, Any]:
    import jwt

    from crmcore.config import get_settings

    s = get_settings()
    try:
        return dict(
            jwt.decode(token, s.secret_key.get_secret_value(), algorithms=[s.jwt_algorithm])
        )
    except jwt.ExpiredSignatureError:
        raise NoAutenticado(
            "La sesión del portal ha caducado. Pide otro enlace de acceso.",
            error_code="portal.sesion_caducada",
        )
    except jwt.InvalidTokenError:
        raise NoAutenticado("Esta sesión no es válida", error_code="portal.sesion_invalida")


def contexto_portal(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> Any:
    """Quién es quien llama al portal, y deja el tenant en el contexto.

    El tenant lo fija esta dependencia, como hace la del CRM: sin él, las
    consultas del portal no pasarían por el aislamiento y verían las de otra
    empresa. Es el mismo mecanismo, no uno paralelo.
    """
    from dataclasses import replace

    from crmcore.config import get_settings
    from crmcore.tenancy.context import contexto_actual, fijar_contexto

    s = get_settings()
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:]
    else:
        # La cookie del portal es otra que la del CRM: en el mismo navegador
        # puede haber las dos —un comercial mirando el portal de su cliente— y
        # compartir nombre haría que una pisara a la otra.
        token = request.cookies.get(f"{s.sesion_cookie_nombre}_portal", "")
    if not token:
        raise NoAutenticado("Hace falta entrar en el portal", error_code="portal.sin_sesion")

    carga = _carga(token)
    if carga.get("tipo") != TIPO:
        # Un token de empleado no vale aquí. Podría parecer inofensivo —tiene
        # más permisos, no menos— pero saltaría el filtro por nivel de acceso,
        # que es lo único que decide qué ve cada contacto.
        raise NoAutenticado(
            "Esta sesión no es del portal", error_code="portal.sesion_no_es_de_portal"
        )

    try:
        acceso_id = UUID(str(carga["sub"]))
        tenant_id = UUID(str(carga["tenant"]))
    except (KeyError, ValueError):
        raise NoAutenticado(
            "Esta sesión no tiene la forma esperada", error_code="portal.sesion_malformada"
        )

    ctx = contexto_actual()
    fijar_contexto(replace(ctx, tenant_id=tenant_id, user_id=None))
    cuenta = str(carga.get("cuenta") or "")
    return SesionPortal(
        acceso_id=acceso_id,
        tenant_id=tenant_id,
        nivel=str(carga.get("nivel", "")),
        cuenta_id=UUID(cuenta) if cuenta else None,
        secciones=[str(s) for s in (carga.get("secciones") or [])],
    )


class SesionPortal:
    """Quién llama al portal: su acceso, su empresa y su nivel."""

    __slots__ = ("acceso_id", "tenant_id", "nivel", "cuenta_id", "secciones")

    def __init__(
        self,
        *,
        acceso_id: UUID,
        tenant_id: UUID,
        nivel: str,
        cuenta_id: UUID | None = None,
        secciones: list[str] | None = None,
    ) -> None:
        self.acceso_id = acceso_id
        self.tenant_id = tenant_id
        self.nivel = nivel
        self.cuenta_id = cuenta_id
        self.secciones = list(secciones or [])

    def exigir_seccion(self, seccion: str) -> None:
        """Corta si este acceso no tiene esa sección. **En el servidor.**

        `secciones_de` se le cuenta al cliente «para que no pinte botones», y
        filtrar en el cliente funciona hasta que alguien mira la respuesta de la
        API — y entonces el portal deja de ser un portal para ser una copia del
        CRM con un filtro de pantalla.

        Vive aquí y no en el servicio dueño del acceso porque el portal lo
        sirven varios: los contratos y los pedidos son de `sales`, los contactos
        de `party`, y ninguno puede leer la tabla de accesos. Dos
        implementaciones de «¿puede ver esto?» divergen, y la que se queda corta
        es siempre la del servicio que no es el dueño.
        """
        if seccion not in self.secciones:
            raise NoAutenticado(
                "Este acceso no incluye esa sección del portal",
                error_code="portal.seccion_no_incluida",
            )

    def exigir_cuenta(self) -> UUID:
        """La empresa de quien llama, o un error claro.

        Lo que se sirve por cuenta —sus documentos, sus homologaciones— no tiene
        sentido sin ella, y devolver una lista vacía haría creer que no hay nada
        cuando lo que pasa es que el acceso está mal dado.
        """
        if self.cuenta_id is None:
            raise NoAutenticado(
                "Este acceso no está asociado a ninguna empresa",
                error_code="portal.sin_empresa",
            )
        return self.cuenta_id


PortalDep = Annotated[SesionPortal, Depends(contexto_portal)]


def exige_seccion_portal(seccion: str) -> Any:
    """Guarda **declarada en la ruta** para una sección del portal.

        @router.get("/mi/activos", dependencies=[Depends(exige_seccion_portal("activos"))])

    Declarada y no escrita dentro, por lo mismo que `exige_permiso`: una
    comprobación en el cuerpo de la función no se ve al leer la ruta, no la
    encuentra ningún gate, y la que se olvida no avisa de nada — simplemente
    sirve datos a quien no tenía esa sección.
    """

    def _guarda(sesion: PortalDep) -> None:
        sesion.exigir_seccion(seccion)

    return _guarda
