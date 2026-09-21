"""SCIM 2.0: aprovisionamiento y **desaprovisionamiento** automático
(CRM-00.05.01.05, RFC 7643 y RFC 7644).

Reutiliza `contecweb:app/services/scim.py` y `contecflow-PSA:app/services/
scim_service.py`: de ahí salen el sobre `ListResponse`, el formato de error y
—sobre todo— el catálogo de rarezas de los proveedores, que es lo que de verdad
cuesta descubrir.

**Lo que importa aquí es la baja, no el alta.** Un alta que falla se ve el
primer día: la persona nueva no puede entrar y llama. Una baja que falla no la
ve nadie: alguien que se fue de la empresa hace ocho meses conserva su acceso, y
eso solo sale en una auditoría o en un incidente. Por eso el módulo trata la
desactivación como el camino principal y no como un caso más del `PATCH`, y por
eso `DELETE` **no borra**: desactiva la membresía y corta las sesiones, igual
que `active: false`.

Las dos rarezas que hay que soportar sí o sí, porque las mandan los dos
proveedores mayoritarios y ninguna es opcional:

1. **`active` como cadena.** Entra ID manda `"value": "False"` —texto, con
   mayúscula— en lugar del booleano que dice el RFC. Leído con `bool()` eso es
   `True`, que es exactamente lo contrario de lo que pide: la baja se
   convertiría en «sigue activo». Es el fallo más caro posible en este módulo.
2. **`PATCH` sin `path`.** Okta manda `{"op": "replace", "value": {"active":
   false}}`, con el atributo dentro del valor. Si solo se mira `path`, la
   operación se ignora en silencio y se responde 200, que es peor que fallar.

Ninguna de las dos se corrige «detectando el proveedor»: se aceptan las dos
formas siempre, porque son ambas interpretaciones defendibles del texto del RFC
y porque detectar por proveedor obliga a tocar el producto cada vez que aparece
uno nuevo.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from services.identity import servicio as svc
from services.identity.modelos import Membresia, RolTenant, Usuario

ESQUEMA_USUARIO = "urn:ietf:params:scim:schemas:core:2.0:User"
ESQUEMA_GRUPO = "urn:ietf:params:scim:schemas:core:2.0:Group"
ESQUEMA_LISTA = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
ESQUEMA_PATCH = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
ESQUEMA_ERROR = "urn:ietf:params:scim:api:messages:2.0:Error"

# Tope duro de página. El RFC deja que el servidor imponga el suyo y avise en
# `itemsPerPage`; sin tope, un `count=100000` de un IdP mal configurado se lleva
# por delante el servicio de identidad, que es justamente el que no puede caer.
MAXIMO_POR_PAGINA = 200


# ── Verdad booleana tolerante ─────────────────────────────────────────────


def como_booleano(valor: Any) -> bool:
    """Lee `active` venga como venga, y **falla** si no se entiende.

    Devolver `True` por defecto ante un valor raro sería convertir una baja
    ilegible en un alta silenciosa. Cuando no se entiende, se rechaza la
    petición: el IdP reintenta y alguien lo ve.
    """
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, str):
        texto = valor.strip().lower()
        if texto in {"true", "1", "yes"}:
            return True
        if texto in {"false", "0", "no"}:
            return False
    if isinstance(valor, (int, float)) and valor in (0, 1):
        return bool(valor)
    raise ErrorValidacion(
        f"No se entiende el valor de 'active': {valor!r}",
        error_code="scim.active_ilegible",
        detalle={"recibido": repr(valor)},
    )


# ── Filtros ───────────────────────────────────────────────────────────────

# Los IdP mandan, en la práctica, un único filtro de igualdad para comprobar si
# el recurso ya existe antes de crearlo. Soportar la gramática entera del RFC
# sería escribir un intérprete para un caso que nadie usa; soportar solo esto y
# **decirlo** es más honrado que aparentar que se soporta todo y devolver
# resultados incorrectos ante un `and`.
_FILTRO = re.compile(
    r'^\s*(?P<atributo>[A-Za-z][\w.:]*)\s+(?P<op>eq|ne|co|sw)\s+"(?P<valor>[^"]*)"\s*$',
    re.IGNORECASE,
)

_ATRIBUTOS_USUARIO = {"username": Usuario.email, "externalid": Usuario.email}
_ATRIBUTOS_GRUPO = {"displayname": RolTenant.nombre}


def traducir_filtro(filtro: str, atributos: dict[str, Any]) -> Any:
    """Traduce un filtro SCIM a una condición SQL, o dice que no puede."""
    casa = _FILTRO.match(filtro or "")
    if casa is None:
        raise ErrorValidacion(
            "Solo se admiten filtros simples de la forma 'atributo op \"valor\"' "
            "con los operadores eq, ne, co y sw.",
            error_code="scim.filtro_no_soportado",
            detalle={"filtro": filtro},
        )
    nombre = casa.group("atributo").lower()
    columna = atributos.get(nombre)
    if columna is None:
        raise ErrorValidacion(
            f"No se puede filtrar por '{casa.group('atributo')}'.",
            error_code="scim.atributo_no_filtrable",
            detalle={"filtrables": sorted(atributos)},
        )
    valor = casa.group("valor")
    op = casa.group("op").lower()
    if op == "eq":
        return func.lower(columna) == valor.lower()
    if op == "ne":
        return func.lower(columna) != valor.lower()
    if op == "co":
        return columna.ilike(f"%{valor}%")
    return columna.ilike(f"{valor}%")


# ── Representación ────────────────────────────────────────────────────────


def _momento(valor: datetime | None) -> str:
    momento = valor or datetime.now(timezone.utc)
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=timezone.utc)
    return momento.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def usuario_a_scim(usuario: Usuario, membresia: Membresia, base: str) -> dict[str, Any]:
    """Representación SCIM de un usuario **dentro de un tenant**.

    `active` sale de la membresía y no del usuario: la misma persona puede estar
    de baja en un tenant y en activo en otro, y es lo que hace que un consultor
    no tenga tres identidades. Mirar `Usuario.activo` aquí haría que dar de baja
    a alguien en un cliente lo echara de todos.
    """
    nombre = (usuario.nombre or "").strip()
    partes = nombre.split(" ", 1)
    return {
        "schemas": [ESQUEMA_USUARIO],
        "id": str(usuario.id),
        "externalId": str(usuario.id),
        "userName": usuario.email,
        "name": {
            "formatted": nombre,
            "givenName": partes[0] if partes else "",
            "familyName": partes[1] if len(partes) > 1 else "",
        },
        "displayName": nombre or usuario.email,
        "emails": [{"value": usuario.email, "primary": True, "type": "work"}],
        "active": bool(membresia.activa),
        "groups": [{"value": r, "display": r} for r in (membresia.roles or [])],
        "meta": {
            "resourceType": "User",
            "created": _momento(getattr(usuario, "created_at", None)),
            "lastModified": _momento(getattr(membresia, "updated_at", None)),
            "location": f"{base}/Users/{usuario.id}",
        },
    }


def grupo_a_scim(rol: RolTenant, miembros: list[Usuario], base: str) -> dict[str, Any]:
    return {
        "schemas": [ESQUEMA_GRUPO],
        "id": str(rol.id),
        "displayName": rol.nombre,
        "members": [
            {"value": str(u.id), "display": u.email, "$ref": f"{base}/Users/{u.id}"}
            for u in miembros
        ],
        "meta": {
            "resourceType": "Group",
            "created": _momento(getattr(rol, "created_at", None)),
            "lastModified": _momento(getattr(rol, "updated_at", None)),
            "location": f"{base}/Groups/{rol.id}",
        },
    }


def lista(
    recursos: list[dict[str, Any]], total: int, inicio: int, por_pagina: int
) -> dict[str, Any]:
    return {
        "schemas": [ESQUEMA_LISTA],
        "totalResults": total,
        "startIndex": inicio,
        "itemsPerPage": min(por_pagina, len(recursos)) if recursos else 0,
        "Resources": recursos,
    }


# ── Lectura ───────────────────────────────────────────────────────────────


def _membresia(db: Session, usuario_id: UUID, tenant_id: UUID) -> Membresia:
    fila = db.execute(
        select(Membresia).where(
            Membresia.usuario_id == usuario_id, Membresia.tenant_id == tenant_id
        )
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado(
            "Ese usuario no pertenece a este tenant", error_code="scim.usuario_no_encontrado"
        )
    return fila


def buscar_usuarios(
    db: Session,
    tenant_id: UUID,
    *,
    filtro: str = "",
    inicio: int = 1,
    por_pagina: int = 100,
) -> tuple[list[tuple[Usuario, Membresia]], int]:
    consulta = (
        select(Usuario, Membresia)
        .join(Membresia, Membresia.usuario_id == Usuario.id)
        .where(Membresia.tenant_id == tenant_id)
    )
    if filtro:
        consulta = consulta.where(traducir_filtro(filtro, _ATRIBUTOS_USUARIO))

    total = db.execute(
        select(func.count()).select_from(consulta.order_by(None).subquery())
    ).scalar_one()

    por_pagina = max(1, min(por_pagina, MAXIMO_POR_PAGINA))
    desplazamiento = max(0, inicio - 1)
    filas = db.execute(
        consulta.order_by(Usuario.email).offset(desplazamiento).limit(por_pagina)
    ).all()
    return [(f[0], f[1]) for f in filas], int(total)


def leer_usuario(db: Session, usuario_id: UUID, tenant_id: UUID) -> tuple[Usuario, Membresia]:
    membresia = _membresia(db, usuario_id, tenant_id)
    usuario = db.get(Usuario, usuario_id)
    if usuario is None:  # pragma: no cover - la FK lo impide
        raise NoEncontrado("Usuario no encontrado", error_code="scim.usuario_no_encontrado")
    return usuario, membresia


# ── Escritura ─────────────────────────────────────────────────────────────


def _correo(cuerpo: dict[str, Any]) -> str:
    """El correo de un recurso SCIM, mirando donde de verdad lo ponen.

    El RFC dice que `userName` es el identificador y `emails` el contacto, pero
    hay IdP que mandan el nombre de cuenta en `userName` y el correo solo en
    `emails`. Como aquí la identidad **es** el correo, se cogen los dos y gana
    el que parezca un correo.
    """
    nombre_cuenta = str(cuerpo.get("userName") or "").strip()
    correos = cuerpo.get("emails") or []
    primario = ""
    for entrada in correos:
        if isinstance(entrada, dict) and entrada.get("value"):
            if entrada.get("primary") or not primario:
                primario = str(entrada["value"]).strip()
    elegido = nombre_cuenta if "@" in nombre_cuenta else (primario or nombre_cuenta)
    if not elegido:
        raise ErrorValidacion(
            "Hace falta 'userName' o un correo en 'emails'.",
            error_code="scim.sin_identificador",
        )
    return elegido.lower()


def _nombre(cuerpo: dict[str, Any]) -> str:
    nombre = cuerpo.get("name") or {}
    if isinstance(nombre, dict):
        formateado = str(nombre.get("formatted") or "").strip()
        if formateado:
            return formateado
        partes = [nombre.get("givenName") or "", nombre.get("familyName") or ""]
        junto = " ".join(p.strip() for p in partes if str(p).strip())
        if junto:
            return junto
    return str(cuerpo.get("displayName") or "").strip()


def _roles(cuerpo: dict[str, Any], db: Session, tenant_id: UUID) -> list[str]:
    """Los roles que trae el recurso, quedándose solo con los que existen.

    Un IdP manda los grupos que tiene él, que no son los roles de aquí. Aceptar
    a ciegas un grupo llamado «Administradores» y darle permisos por el nombre
    sería dejar la matriz de permisos en manos de quien administre el directorio
    corporativo. Se cruzan con los roles reales del tenant y lo que no case se
    ignora, que es lo que hace que el IdP no pueda escalar privilegios.
    """
    crudos = []
    for grupo in cuerpo.get("groups") or []:
        if isinstance(grupo, dict):
            crudos.append(str(grupo.get("display") or grupo.get("value") or "").strip())
        elif isinstance(grupo, str):
            crudos.append(grupo.strip())
    for rol in cuerpo.get("roles") or []:
        if isinstance(rol, dict):
            crudos.append(str(rol.get("value") or "").strip())
        elif isinstance(rol, str):
            crudos.append(rol.strip())
    if not crudos:
        return []

    from crmcore.authz.rbac import ROLES_BASE

    propios = {
        n.lower()
        for n in db.execute(
            select(RolTenant.nombre).where(RolTenant.tenant_id == tenant_id)
        ).scalars()
    }
    conocidos = {r.lower() for r in ROLES_BASE} | propios
    return [c for c in crudos if c.lower() in conocidos]


def crear_usuario(
    uow: UnidadDeTrabajo, tenant_id: UUID, cuerpo: dict[str, Any]
) -> tuple[Usuario, Membresia]:
    email = _correo(cuerpo)
    existente = uow.db.execute(select(Usuario).where(Usuario.email == email)).scalar_one_or_none()
    if existente is not None:
        membresia = uow.db.execute(
            select(Membresia).where(
                Membresia.usuario_id == existente.id, Membresia.tenant_id == tenant_id
            )
        ).scalar_one_or_none()
        if membresia is not None:
            # Es el caso más común en producción: el IdP reintenta un alta que
            # ya salió bien pero cuya respuesta se perdió. El RFC pide 409, y
            # darlo con el identificador dentro deja al IdP reconciliar solo.
            raise Conflicto(
                "Ya existe un usuario con ese userName en este tenant",
                error_code="scim.usuario_duplicado",
                detalle={"id": str(existente.id)},
            )

    usuario = svc.crear_usuario(
        uow,
        email=email,
        nombre=_nombre(cuerpo) or email,
        tenant_id=tenant_id,
        roles=_roles(cuerpo, uow.db, tenant_id),
        contrasena=None,  # entra por el IdP: sin contraseña local no hay atajo
        via="scim",
    )
    membresia = _membresia(uow.db, usuario.id, tenant_id)
    if "active" in cuerpo and not como_booleano(cuerpo["active"]):
        # Sí pasa: un alta de alguien que ya estaba suspendido en el directorio.
        desactivar(uow, usuario.id, tenant_id)
    return usuario, membresia


def actualizar_usuario(
    uow: UnidadDeTrabajo, usuario_id: UUID, tenant_id: UUID, cuerpo: dict[str, Any]
) -> tuple[Usuario, Membresia]:
    """`PUT`: el recurso entero se reemplaza por lo que llega."""
    usuario, membresia = leer_usuario(uow.db, usuario_id, tenant_id)
    nombre = _nombre(cuerpo)
    if nombre:
        usuario.nombre = nombre
    roles = _roles(cuerpo, uow.db, tenant_id)
    if roles:
        membresia.roles = roles
    if "active" in cuerpo:
        _fijar_actividad(uow, usuario_id, tenant_id, membresia, como_booleano(cuerpo["active"]))
    return usuario, membresia


def aplicar_patch(
    uow: UnidadDeTrabajo, usuario_id: UUID, tenant_id: UUID, cuerpo: dict[str, Any]
) -> tuple[Usuario, Membresia]:
    """`PATCH`: el camino por el que llega de verdad la baja.

    Se aceptan las dos formas —con `path` y con el atributo dentro de `value`—
    porque las mandan los dos proveedores mayoritarios. Ver la cabecera.
    """
    usuario, membresia = leer_usuario(uow.db, usuario_id, tenant_id)
    operaciones = cuerpo.get("Operations") or cuerpo.get("operations") or []
    if not operaciones:
        raise ErrorValidacion(
            "Un PatchOp sin operaciones no cambia nada; probablemente el cuerpo "
            "no es el que se pretendía enviar.",
            error_code="scim.patch_vacio",
        )

    aplicadas = 0
    for op in operaciones:
        if not isinstance(op, dict):
            continue
        accion = str(op.get("op") or "").lower()
        if accion not in {"replace", "add", "remove"}:
            raise ErrorValidacion(
                f"Operación '{op.get('op')}' no admitida.", error_code="scim.op_no_soportada"
            )
        camino = str(op.get("path") or "").strip()
        valor = op.get("value")

        # Forma 1: `path` explícito. El atributo puede venir cualificado con el
        # URN del esquema, que se recorta porque no cambia el significado.
        if camino:
            atributo = camino.split(":")[-1].lower()
            pares: list[tuple[str, Any]] = [(atributo, valor)]
        # Forma 2: sin `path`, con el atributo dentro del valor (Okta).
        elif isinstance(valor, dict):
            pares = [(str(k).split(":")[-1].lower(), v) for k, v in valor.items()]
        else:
            raise ErrorValidacion(
                "Operación sin 'path' y con un valor que no es un objeto: no hay "
                "forma de saber qué atributo se pretende cambiar.",
                error_code="scim.patch_sin_destino",
            )

        for atributo, contenido in pares:
            if atributo == "active":
                # `remove active` es, en la práctica, una baja.
                activo = False if accion == "remove" else como_booleano(contenido)
                _fijar_actividad(uow, usuario_id, tenant_id, membresia, activo)
                aplicadas += 1
            elif atributo in {"displayname", "name.formatted"}:
                usuario.nombre = str(contenido or "").strip() or usuario.nombre
                aplicadas += 1
            elif atributo in {"username", "emails.value", 'emails[type eq "work"].value'}:
                nuevo = str(contenido or "").strip().lower()
                if nuevo and nuevo != usuario.email:
                    choque = uow.db.execute(
                        select(Usuario).where(Usuario.email == nuevo, Usuario.id != usuario.id)
                    ).scalar_one_or_none()
                    if choque is not None:
                        raise Conflicto(
                            "Ese userName ya lo tiene otro usuario",
                            error_code="scim.usuario_duplicado",
                            detalle={"id": str(choque.id)},
                        )
                    usuario.email = nuevo
                aplicadas += 1
            elif atributo in {"groups", "roles"}:
                roles = _roles({atributo: contenido}, uow.db, tenant_id)
                membresia.roles = [] if accion == "remove" else roles
                aplicadas += 1
            # Lo demás se ignora a propósito: los IdP mandan decenas de
            # atributos de directorio (departamento, oficina, manager) que aquí
            # no tienen sitio, y fallar por ellos rompería el ciclo entero.

    if aplicadas == 0:
        raise ErrorValidacion(
            "Ninguna operación del PatchOp afectaba a un atributo gestionable.",
            error_code="scim.patch_sin_efecto",
            detalle={"gestionables": ["active", "userName", "displayName", "groups"]},
        )
    return usuario, membresia


def _fijar_actividad(
    uow: UnidadDeTrabajo,
    usuario_id: UUID,
    tenant_id: UUID,
    membresia: Membresia,
    activo: bool,
) -> None:
    if activo and not membresia.activa:
        reactivar(uow, usuario_id, tenant_id, membresia)
    elif not activo and membresia.activa:
        desactivar(uow, usuario_id, tenant_id)


def desactivar(uow: UnidadDeTrabajo, usuario_id: UUID, tenant_id: UUID) -> None:
    """La baja: membresía inactiva **y sesiones cortadas**.

    Marcar la membresía sin revocar las sesiones dejaría al que se va operando
    hasta que le caducara el token, que es precisamente el rato que importa.
    `svc.desactivar_usuario` hace las dos cosas, audita y emite el evento que
    los demás servicios necesitan para quitarle asignaciones.
    """
    svc.desactivar_usuario(uow, usuario_id, tenant_id, via="scim")


def reactivar(
    uow: UnidadDeTrabajo, usuario_id: UUID, tenant_id: UUID, membresia: Membresia | None = None
) -> None:
    from crmcore.audit import registrar

    membresia = membresia or _membresia(uow.db, usuario_id, tenant_id)
    membresia.activa = True
    usuario = uow.db.get(Usuario, usuario_id)
    registrar(
        uow.db,
        accion="usuario.alta",
        objeto="usuario",
        objeto_id=usuario_id,
        datos={"via": "scim", "reactivacion": True},
        tenant_id=tenant_id,
    )
    uow.emitir(
        "user.provisioned",
        subject=("usuario", usuario_id),
        data={
            "user_id": str(usuario_id),
            # El contrato de `user.provisioned` promete `email`, y hay
            # consumidores que lo usan para avisar. Omitirlo aquí dejaba la
            # reactivación emitiendo un evento incompleto; lo cazó el contract
            # testing en ejecución (CRM-00.03.01.03), no una revisión.
            "email": usuario.email if usuario else "",
            "via": "scim",
            "reactivacion": True,
        },
    )


# ── Grupos ────────────────────────────────────────────────────────────────


def buscar_grupos(
    db: Session, tenant_id: UUID, *, filtro: str = "", inicio: int = 1, por_pagina: int = 100
) -> tuple[list[tuple[RolTenant, list[Usuario]]], int]:
    consulta = select(RolTenant).where(RolTenant.tenant_id == tenant_id)
    if filtro:
        consulta = consulta.where(traducir_filtro(filtro, _ATRIBUTOS_GRUPO))
    total = db.execute(
        select(func.count()).select_from(consulta.order_by(None).subquery())
    ).scalar_one()
    por_pagina = max(1, min(por_pagina, MAXIMO_POR_PAGINA))
    roles = (
        db.execute(consulta.order_by(RolTenant.nombre).offset(max(0, inicio - 1)).limit(por_pagina))
        .scalars()
        .all()
    )
    return [(rol, miembros_de(db, rol, tenant_id)) for rol in roles], int(total)


def miembros_de(db: Session, rol: RolTenant, tenant_id: UUID) -> list[Usuario]:
    filas = (
        db.execute(
            select(Usuario)
            .join(Membresia, Membresia.usuario_id == Usuario.id)
            .where(
                Membresia.tenant_id == tenant_id,
                Membresia.activa.is_(True),
                Membresia.roles.contains([rol.nombre]),
            )
            .order_by(Usuario.email)
        )
        .scalars()
        .all()
    )
    return list(filas)


def leer_grupo(db: Session, grupo_id: UUID, tenant_id: UUID) -> tuple[RolTenant, list[Usuario]]:
    rol = db.execute(
        select(RolTenant).where(RolTenant.id == grupo_id, RolTenant.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if rol is None:
        raise NoEncontrado("Grupo no encontrado", error_code="scim.grupo_no_encontrado")
    return rol, miembros_de(db, rol, tenant_id)


def patch_grupo(
    uow: UnidadDeTrabajo, grupo_id: UUID, tenant_id: UUID, cuerpo: dict[str, Any]
) -> tuple[RolTenant, list[Usuario]]:
    """Altas y bajas de miembros de un grupo, que es el 99 % de lo que llega."""
    rol, _ = leer_grupo(uow.db, grupo_id, tenant_id)
    for op in cuerpo.get("Operations") or cuerpo.get("operations") or []:
        if not isinstance(op, dict):
            continue
        accion = str(op.get("op") or "").lower()
        camino = str(op.get("path") or "").lower()
        if not camino.startswith("members"):
            continue
        valores = op.get("value")
        entradas = valores if isinstance(valores, list) else [valores]
        ids: list[UUID] = []
        for entrada in entradas:
            crudo = entrada.get("value") if isinstance(entrada, dict) else entrada
            if not crudo:
                continue
            try:
                ids.append(UUID(str(crudo)))
            except ValueError:
                continue
        for usuario_id in ids:
            membresia = _membresia(uow.db, usuario_id, tenant_id)
            roles = list(membresia.roles or [])
            if accion == "remove":
                roles = [r for r in roles if r != rol.nombre]
            elif rol.nombre not in roles:
                roles.append(rol.nombre)
            membresia.roles = roles
    # Los miembros se releen por SQL (`roles @> [...]`), así que sin vaciar
    # antes la sesión se devolvería la lista de antes del cambio y el IdP daría
    # la operación por no aplicada.
    uow.db.flush()
    return rol, miembros_de(uow.db, rol, tenant_id)


# ── Descubrimiento ────────────────────────────────────────────────────────


def configuracion_del_proveedor(base: str) -> dict[str, Any]:
    """Lo que el servidor dice de sí mismo, sin adornar.

    Aquí se declara `filter.supported` con el tope real y `patch` soportado.
    Declarar `bulk` o `sort` sin tenerlos haría que el IdP los intentara y se
    llevara un 501 a mitad de un ciclo de sincronización.
    """
    return {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
        "documentationUri": f"{base}/Schemas",
        "patch": {"supported": True},
        "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
        "filter": {"supported": True, "maxResults": MAXIMO_POR_PAGINA},
        "changePassword": {"supported": False},
        "sort": {"supported": False},
        "etag": {"supported": False},
        "authenticationSchemes": [
            {
                "type": "oauthbearertoken",
                "name": "Clave de API",
                "description": (
                    "Clave de API del tenant con permiso 'user:write', enviada "
                    "como 'Authorization: Bearer'. La clave acota el tenant: un "
                    "cliente SCIM nunca ve ni toca usuarios de otro."
                ),
                "primary": True,
            }
        ],
        "meta": {
            "resourceType": "ServiceProviderConfig",
            "location": f"{base}/ServiceProviderConfig",
        },
    }


def tipos_de_recurso(base: str) -> list[dict[str, Any]]:
    return [
        {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ResourceType"],
            "id": "User",
            "name": "User",
            "endpoint": "/Users",
            "schema": ESQUEMA_USUARIO,
            "meta": {"resourceType": "ResourceType", "location": f"{base}/ResourceTypes/User"},
        },
        {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ResourceType"],
            "id": "Group",
            "name": "Group",
            "endpoint": "/Groups",
            "schema": ESQUEMA_GRUPO,
            "meta": {"resourceType": "ResourceType", "location": f"{base}/ResourceTypes/Group"},
        },
    ]


def _atributo(nombre: str, tipo: str = "string", **extra: Any) -> dict[str, Any]:
    base = {
        "name": nombre,
        "type": tipo,
        "multiValued": False,
        "required": False,
        "caseExact": False,
        "mutability": "readWrite",
        "returned": "default",
        "uniqueness": "none",
    }
    base.update(extra)
    return base


def esquemas(base: str) -> list[dict[str, Any]]:
    """Solo los atributos que de verdad se guardan.

    Publicar atributos que se ignoran hace que el IdP los mapee y que alguien dé
    por hecho que el departamento viaja. No viaja, y decirlo aquí evita la
    sorpresa seis meses después.
    """
    return [
        {
            "id": ESQUEMA_USUARIO,
            "name": "User",
            "description": "Usuario con membresía en el tenant.",
            "attributes": [
                _atributo("userName", required=True, uniqueness="server"),
                _atributo("displayName"),
                _atributo("active", "boolean"),
                _atributo("emails", "complex", multiValued=True),
                _atributo("groups", "complex", multiValued=True, mutability="readWrite"),
            ],
            "meta": {"resourceType": "Schema", "location": f"{base}/Schemas/{ESQUEMA_USUARIO}"},
        },
        {
            "id": ESQUEMA_GRUPO,
            "name": "Group",
            "description": "Rol del tenant visto como grupo.",
            "attributes": [
                _atributo("displayName", required=True),
                _atributo("members", "complex", multiValued=True),
            ],
            "meta": {"resourceType": "Schema", "location": f"{base}/Schemas/{ESQUEMA_GRUPO}"},
        },
    ]
