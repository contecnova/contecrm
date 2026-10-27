"""Dependencias de FastAPI compartidas por todos los servicios.

Aquí está la autenticación de las peticiones que llegan a un servicio. Hay dos
casos y conviene no mezclarlos:

  * **Petición del gateway.** El gateway ya autenticó al usuario y pasa la
    identidad en cabeceras internas firmadas. El servicio no vuelve a validar el
    token del usuario final: no lo tiene y no debería tenerlo.
  * **Petición directa.** Contra un servicio, en desarrollo o desde otro
    servicio. Lleva token propio y se valida aquí.

Que el gateway pase la identidad por cabecera **solo funciona si esas cabeceras
no pueden falsificarse desde fuera**. Dos condiciones, las dos necesarias:
la red interna no es alcanzable desde fuera, y las cabeceras van firmadas con un
secreto compartido. La segunda está implementada; la primera es del despliegue y
está dicha en el manual de operación, porque un servicio publicado por error en
Internet con esta confianza activada es un salto de autenticación directo.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from collections.abc import Iterator
from contextvars import ContextVar
from typing import Annotated, Any, Callable
from uuid import UUID

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from crmcore.authz.principal import ANONIMO, Principal
from crmcore.db.al_margen import al_margen
from crmcore.errors import NoAutenticado, Prohibido
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Cabeceras con las que el gateway propaga la identidad ya verificada.
H_TENANT = "x-crm-tenant"
H_USER = "x-crm-user"
H_PERMISOS = "x-crm-permisos"
# Los roles viajan ADEMÁS de los permisos, y no son redundantes: hay decisiones
# que se toman por rol y no por permiso —una tarea humana asignada a
# «responsable_ventas» la coge quien tenga ese rol—. Sin propagarlos, esa
# bandeja sale vacía aunque el usuario tenga el rol: se descubrió probando el
# ciclo completo de una aprobación.
H_ROLES = "x-crm-roles"
H_SCOPES = "x-crm-scopes"
H_ACTOR_REAL = "x-crm-actor-real"
H_SESION = "x-crm-sesion"
# Cuándo se superó el último factor fuerte. Va firmada con las demás: si fuera
# una cabecera suelta, cualquiera que llegara a la red interna podría decir que
# acaba de verificarse y saltarse la reautenticación entera.
H_FACTOR_FUERTE = "x-crm-factor-fuerte"
H_PLATAFORMA = "x-crm-plataforma"
# Qué CLASE de principal es: persona, servicio, automatización, agente. Faltaba,
# y su ausencia no se notaba mientras todo lo que entraba eran personas. En
# cuanto entró una credencial de máquina, los servicios de detrás la trataron
# como a una persona sin registros a su nombre y le enseñaron CERO filas — sin
# error, que es la forma más cara de equivocarse.
# El alcance de un componente embebido (CRM-00.02.03.05): a qué componente y a
# qué registro está atado el token. Viaja firmado como el resto de la
# identidad, porque a los servicios de detrás no les llega el token —y sin
# esto, el extremo del componente no sabría de qué registro hablar y habría que
# pasarle el identificador por la URL, que es justo lo que el acotamiento
# existe para impedir.
H_EMBEBIDO = "x-crm-embebido"
H_TIPO = "x-crm-tipo"
H_FIRMA = "x-crm-firma"
H_MOMENTO = "x-crm-momento"


# Ventana en la que se acepta la firma interna. Corta: estas peticiones viajan
# por la red interna y tardan milisegundos, así que una ventana amplia solo
# amplía el margen para reutilizar una petición capturada.
def _firma_interna_ventana_s() -> int:
    """Tope del núcleo, antes `_firma_interna_ventana_s() = 30`.

    Era una constante de módulo. Sale del `.env`, no de los ajustes en
    caliente: es un tope operativo del despliegue y «por cliente» no
    significaría nada.
    """
    from crmcore.config import get_settings

    return get_settings().firma_interna_ventana_s


def firmar_cabeceras_internas(valores: dict[str, str], secreto: str) -> dict[str, str]:
    """Firma las cabeceras de identidad. Lo usa el gateway al reenviar."""
    momento = str(int(time.time()))
    material = _material(valores, momento)
    firma = hmac.new(secreto.encode(), material.encode(), hashlib.sha256).hexdigest()
    return {**valores, H_MOMENTO: momento, H_FIRMA: firma}


def _material(valores: dict[str, str], momento: str) -> str:
    """Cadena que se firma: las cabeceras ordenadas más el instante.

    Ordenadas para que emisor y verificador construyan la misma cadena
    independientemente del orden en que se hayan compuesto los valores.
    """
    partes = [f"{k.lower()}={v}" for k, v in sorted(valores.items()) if v]
    return "|".join([*partes, momento])


def _verificar_firma(request: Request, secreto: str) -> bool:
    firma = request.headers.get(H_FIRMA, "")
    momento = request.headers.get(H_MOMENTO, "")
    if not firma or not momento.isdigit():
        return False
    if abs(time.time() - int(momento)) > _firma_interna_ventana_s():
        logger.warning("deps.firma_caducada")
        return False
    valores = {
        h: request.headers.get(h, "")
        for h in (
            H_TENANT,
            H_USER,
            H_TIPO,
            H_PERMISOS,
            H_ROLES,
            H_SCOPES,
            H_ACTOR_REAL,
            H_PLATAFORMA,
            H_SESION,
            # La marca del factor fuerte va DENTRO de lo firmado. Fuera, sería
            # una cabecera que pone cualquiera que alcance la red interna, y la
            # reautenticación reforzada entera dejaría de valer: bastaría con
            # decir «me acabo de verificar».
            H_FACTOR_FUERTE,
        )
    }
    esperada = hmac.new(
        secreto.encode(), _material(valores, momento).encode(), hashlib.sha256
    ).hexdigest()
    # Comparación en tiempo constante: comparar con `==` filtra por el tiempo de
    # ejecución cuántos caracteres iniciales ha acertado quien lo intenta.
    return hmac.compare_digest(firma, esperada)


async def exige_firma_interna(request: Request) -> None:
    """Deja pasar solo a otro servicio de la casa, sin exigir un usuario.

    Hay llamadas entre servicios que ocurren **antes** de que haya nadie
    autenticado: la más clara es traducir el slug de la organización a su
    identificador cuando alguien está escribiendo su contraseña. Ahí no hay
    principal que propagar, y exigir uno obligaría a inventar un usuario de
    sistema con permisos de plataforma para una consulta que solo devuelve un
    identificador.

    Lo que se comprueba es la firma HMAC, con la misma clave y la misma ventana
    de treinta segundos que el resto del tráfico interno. Sin el secreto no se
    entra, y con él ya se podría entrar como cualquiera: esto no abre nada que
    no estuviera abierto.
    """
    from crmcore.config import get_settings

    if not _verificar_firma(request, get_settings().secret_key.get_secret_value()):
        raise NoAutenticado(
            "Esta ruta es interna entre servicios",
            error_code="auth.firma_interna_invalida",
        )


async def contexto_autenticado(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> Principal:
    """Resuelve el principal de la petición y lo deja en el contexto.

    Es la dependencia que usan casi todos los endpoints. No decide permisos: eso
    es de `exige_permiso`. Solo establece quién es.
    """
    from crmcore.config import get_settings
    from crmcore.http.middleware import fijar_identidad_en_contexto

    s = get_settings()
    secreto = s.secret_key.get_secret_value()

    principal: Principal
    # El motivo por el que la cookie no valía, si traía una que no valía. Viaja
    # en el contexto y no en la firma de las dependencias: cambiarla obligaría a
    # que todo lo que llama a `exige_autenticacion` pasara la petición.
    cookie_rechazada: NoAutenticado | None = None
    # Identidad ya resuelta por quien atiende la petición ANTES de llegar aquí.
    # Hoy solo la pone el gateway, para las claves de API: validarlas exige
    # preguntar a `identity`, que es una llamada de red, y esta dependencia es
    # síncrona y la usan los trece servicios. Dejar el hueco aquí mantiene toda
    # la lógica de la clave en el gateway —que es quien tiene esa conversación—
    # sin que ningún servicio de detrás sepa que existen las claves.
    precalculado = getattr(request.state, "principal_precalculado", None)
    if precalculado is not None:
        principal = precalculado
    elif request.headers.get(H_FIRMA):
        if not _verificar_firma(request, secreto):
            raise NoAutenticado(
                "La identidad propagada no es válida",
                error_code="auth.firma_interna_invalida",
            )
        principal = _principal_de_cabeceras(request)
    elif authorization and authorization.lower().startswith("bearer "):
        principal = _principal_de_token(authorization[7:], secreto)
    elif request.cookies.get(s.sesion_cookie_nombre):
        # Sesión de navegador (CRM-07.04.02.03). El mismo token, en una cookie
        # `HttpOnly` que ningún script puede leer: es la única forma de que un
        # XSS no se lleve la sesión. La pone y la quita el gateway, que es lo
        # único con lo que habla un navegador.
        #
        # Va DESPUÉS de la cabecera a propósito: una integración que manda su
        # token explícitamente tiene que mandar sobre la cookie que el navegador
        # arrastre, o una pestaña con sesión abierta cambiaría en silencio la
        # identidad de una llamada de API.
        #
        # Y una cookie que ya no vale deja la petición ANÓNIMA en vez de
        # tumbarla. La diferencia con la cabecera es quién la manda: la cabecera
        # la pone quien llama, para esta llamada; la cookie la arrastra el
        # navegador solo, también cuando lo que se está pidiendo es justamente
        # volver a entrar. Tumbándola, la cookie caducada hacía fallar con «el
        # token ha caducado» al propio `POST /sesion/entrar` —la idempotencia es
        # global y pide el principal en toda escritura—, así que la sesión
        # expirada dejaba a la persona **encerrada fuera**: la pantalla de
        # entrada rechazaba la contraseña correcta hasta borrar las cookies a
        # mano. Quien exija identidad sigue respondiendo 401, y con este mismo
        # motivo, porque va anotado en la petición.
        try:
            principal = _principal_de_token(request.cookies[s.sesion_cookie_nombre], secreto)
        except NoAutenticado as sin_sesion:
            cookie_rechazada = sin_sesion
            principal = ANONIMO
    else:
        principal = ANONIMO

    # Una sola forma de construir el contexto de identidad. Esto estaba escrito
    # aquí en línea y además existía `fijar_identidad_en_contexto`, que decía en
    # su documentación que la llamaba esta dependencia y no la llamaba nadie: dos
    # maneras de montar lo mismo, y la que menos se mira es la que se queda
    # corta —a aquélla le faltaban dos campos—.
    fijar_identidad_en_contexto(
        tenant_id=principal.tenant_id,
        user_id=principal.id,
        business_unit_id=principal.business_unit_id,
        scopes=principal.scopes,
        es_admin_plataforma=principal.es_admin_plataforma,
        actor_real_id=principal.actor_real_id,
        extra={
            "principal": principal,
            "ip": _ip(request),
            "cookie_rechazada": cookie_rechazada,
        },
    )
    return principal


def ip_de(request: Request) -> str:
    """La IP de quien llama, mirando la cabecera del proxy si la hay.

    Pública porque la necesita el gateway para el acceso contextual: tener dos
    formas de averiguar la IP acabaría con dos respuestas distintas para la
    misma petición, y la que decide quién entra sería la peor de las dos.
    """
    return _ip(request)


def _ip(request: Request) -> str:
    from crmcore.config import get_settings

    if get_settings().trust_proxy_headers:
        reenviada = request.headers.get("x-forwarded-for", "")
        if reenviada:
            return reenviada.split(",")[0].strip()
    return request.client.host if request.client else ""


def _principal_de_cabeceras(request: Request) -> Principal:
    def _uuid(nombre: str) -> UUID | None:
        valor = request.headers.get(nombre, "")
        try:
            return UUID(valor) if valor else None
        except ValueError:
            return None

    return Principal(
        id=_uuid(H_USER),
        tipo=request.headers.get(H_TIPO) or "usuario",
        tenant_id=_uuid(H_TENANT),
        actor_real_id=_uuid(H_ACTOR_REAL),
        sesion_id=_uuid(H_SESION),
        factor_fuerte_at=request.headers.get(H_FACTOR_FUERTE, ""),
        permisos=frozenset(p for p in request.headers.get(H_PERMISOS, "").split(",") if p),
        roles=frozenset(r for r in request.headers.get(H_ROLES, "").split(",") if r),
        scopes=frozenset(p for p in request.headers.get(H_SCOPES, "").split(",") if p),
        es_admin_plataforma=request.headers.get(H_PLATAFORMA, "") == "1",
        atributos=_embebido_de_cabecera(request.headers.get(H_EMBEBIDO, "")),
    )


def _embebido_de_cabecera(valor: str) -> dict[str, object]:
    """`componente|objeto|id` → los tres atributos, o nada.

    Formato plano y no JSON porque viaja en una cabecera HTTP firmada: un JSON
    con comillas dentro de una cabecera es una fuente de escapados mal hechos,
    y lo que se transporta son tres cadenas sin espacios.
    """
    partes = valor.split("|")
    if len(partes) != 3 or not all(partes):
        return {}
    return {"componente": partes[0], "objeto": partes[1], "objeto_id": partes[2]}


def _principal_de_token(token: str, secreto: str) -> Principal:
    import jwt

    from crmcore.config import get_settings

    try:
        datos: dict[str, Any] = jwt.decode(
            token, secreto, algorithms=[get_settings().jwt_algorithm]
        )
    except jwt.ExpiredSignatureError:
        # Código propio y distinto del genérico: un cliente que sabe que el
        # token caducó renueva y reintenta solo; uno que recibe «no autenticado»
        # manda al usuario a la pantalla de inicio de sesión sin necesidad.
        raise NoAutenticado("El token ha caducado", error_code="auth.token_caducado")
    except jwt.InvalidTokenError:
        raise NoAutenticado("El token no es válido", error_code="auth.token_invalido")

    try:
        return Principal(
            id=UUID(datos["sub"]) if datos.get("sub") else None,
            tenant_id=UUID(datos["tenant"]) if datos.get("tenant") else None,
            tipo=datos.get("tipo", "usuario"),
            permisos=frozenset(datos.get("permisos", [])),
            roles=frozenset(datos.get("roles", [])),
            scopes=frozenset(datos.get("scopes", [])),
            es_admin_plataforma=bool(datos.get("plataforma")),
            actor_real_id=UUID(datos["actor_real"]) if datos.get("actor_real") else None,
            sesion_id=UUID(datos["sid"]) if datos.get("sid") else None,
            factor_fuerte_at=str(datos.get("af") or ""),
            # El acotamiento de un componente embebido, si lo lleva.
            atributos=(
                {
                    "componente": str(datos.get("componente") or ""),
                    "objeto": str(datos.get("objeto") or ""),
                    "objeto_id": str(datos.get("objeto_id") or ""),
                }
                if datos.get("componente")
                else {}
            ),
        )
    except (ValueError, KeyError):
        raise NoAutenticado(
            "El token no tiene la forma esperada", error_code="auth.token_malformado"
        )


def principal_de_token(token: str, secreto: str) -> Principal:
    """Valida un token y devuelve quién es, **con el mismo código que HTTP**.

    Existe para que otras superficies —gRPC, una cola, lo que venga— no monten su
    propia validación. Dos implementaciones de «¿este token vale?» divergen
    siempre, y la que se queda atrás es la puerta por la que se entra.
    """
    return _principal_de_token(token, secreto)


PrincipalDep = Annotated[Principal, Depends(contexto_autenticado)]


def cookie_rechazada() -> NoAutenticado | None:
    """Por qué no valía la cookie de sesión de esta petición, si traía una.

    Una cookie caducada deja la petición anónima en vez de tumbarla —si no, no
    se podría volver a entrar—, pero el motivo no se pierde: quien exija
    identidad lo responde, y con él el navegador distingue una sesión que expiró
    —renovar y reintentar— de una llamada que nunca trajo credencial.
    """
    from crmcore.tenancy.context import contexto_actual

    valor = contexto_actual().extra.get("cookie_rechazada")
    return valor if isinstance(valor, NoAutenticado) else None


def exige_autenticacion(principal: PrincipalDep) -> Principal:
    """Endpoint que exige identidad, sea del tipo que sea."""
    if principal.es_anonimo:
        rechazada = cookie_rechazada()
        if rechazada is not None:
            raise rechazada
        raise NoAutenticado("Esta operación exige autenticación", error_code="auth.requerida")
    return principal


AutenticadoDep = Annotated[Principal, Depends(exige_autenticacion)]


def exige_permiso(permiso: str) -> Any:
    """Fábrica de dependencia que exige un permiso concreto.

        @router.post("/accounts", dependencies=[Depends(exige_permiso("account:write"))])

    Se declara en la ruta y no dentro del cuerpo a propósito: así el gate
    `test_auth_gate_contract.py` puede recorrer las rutas y comprobar que
    ninguna escribe sin exigir permiso. Una comprobación escondida dentro de la
    función no se puede auditar sin ejecutarla.
    """

    def _dep(principal: AutenticadoDep) -> Principal:
        principal.exigir(permiso)
        return principal

    # El permiso queda colgado de la dependencia para que la matriz de permisos
    # (CRM-07.03.02.09) pueda leerlo de las rutas montadas. Deducirlo del código
    # fuente obligaría a mantener un inventario aparte, y un inventario y la
    # realidad dejan de coincidir el día que alguien cambia una y no el otro —
    # que es el día en que la auditoría deja de valer.
    _dep.permiso_exigido = permiso  # type: ignore[attr-defined]
    return _dep


def exige_plataforma(principal: AutenticadoDep) -> Principal:
    """Solo personal de la plataforma (alta de tenants, operación)."""
    if not principal.es_admin_plataforma:
        raise Prohibido(
            "Esta operación es de administración de la plataforma",
            error_code="authz.solo_plataforma",
        )
    return principal


PlataformaDep = Annotated[Principal, Depends(exige_plataforma)]


# La sesión que comparte una petición compuesta, si la hay. Es un `ContextVar` y
# no un atributo de la aplicación porque dos peticiones compuestas simultáneas
# tienen que ver cada una la suya: un atributo global las mezclaría, y mezclarlas
# significa escribir en la transacción de otro cliente.
_sesion_compartida: ContextVar[Session | None] = ContextVar("sesion_compartida", default=None)


def compartir_sesion(db: Session | None) -> Any:
    """Marca esta sesión como la de la petición compuesta en curso.

    Devuelve el testigo para restaurarla: sin restaurar, la siguiente petición
    de la misma tarea seguiría escribiendo en una sesión ya cerrada.
    """
    return _sesion_compartida.set(db)


def soltar_sesion(testigo: Any) -> None:
    _sesion_compartida.reset(testigo)


def get_db(principal: PrincipalDep) -> Iterator[Session]:
    """Sesión de base de datos atada al tenant de la petición.

    Atarla aquí, y no en cada endpoint, es lo que hace que el aislamiento no
    dependa de que nadie se despiste: la sesión nace con el tenant, y de ahí
    salen el GUC de RLS y el guard ORM.
    """
    from crmcore.db.session import nueva_sesion

    if principal.es_anonimo and principal.tenant_id is None:
        # 401 y no 500. Sin esto, `nueva_sesion(None)` levantaba
        # «db.sesion_sin_tenant», que es un error interno: la aplicación web
        # pregunta quién eres al arrancar, antes de que haya sesión, y recibía
        # un 500 en cada carga. Un 500 dice «esto está roto»; lo que pasa es
        # que todavía no has entrado, y eso es un 401.
        #
        # El orden de los parámetros del endpoint decidía cuál de los dos
        # salía: con `db` antes que `principal`, reventaba la sesión; con
        # `principal` antes, contestaba 401. Que la respuesta dependa del orden
        # en que alguien escribió la firma no es aceptable, así que se resuelve
        # aquí, que es por donde pasan las dos.
        raise NoAutenticado("Esta operación exige autenticación", error_code="auth.requerida")

    # Si hay una sesión COMPARTIDA, se usa esa y no se abre otra. Es lo que hace
    # que una petición compuesta —varias operaciones en una llamada— sea **una
    # sola transacción**: cada sub-petición pasa por aquí, y si cada una abriera
    # la suya, «todo o nada» serían cinco escrituras independientes y quedarse a
    # medias dejaría una cuenta sin contacto que alguien tendría que limpiar a
    # mano.
    #
    # No se cierra ni se confirma aquí: la abre y la cierra quien la compartió,
    # que es el único que sabe si el conjunto salió bien.
    compartida = _sesion_compartida.get()
    if compartida is not None:
        yield compartida
        return

    db = nueva_sesion(principal.tenant_id, sistema=principal.es_admin_plataforma)
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


DbDep = Annotated[Session, Depends(get_db)]


def get_uow(principal: PrincipalDep) -> Iterator[Any]:
    """Unidad de trabajo: transacción más los eventos que produce.

    Se usa en las escrituras que emiten eventos de dominio, que son casi todas.
    """
    from crmcore.bus.outbox import despertar_relevo
    from crmcore.db.session import nueva_sesion
    from crmcore.db.uow import UnidadDeTrabajo

    if principal.es_anonimo and principal.tenant_id is None:
        # La MISMA guarda que `get_db`, y por lo mismo. Estaba solo allí, así
        # que toda ruta de escritura sin autenticar contestaba 500 —«se ha
        # abierto una sesión sin tenant»— en vez de 401. Un 500 dice «esto está
        # roto»; lo que pasa es que no has entrado.
        #
        # Que una de las dos dependencias tuviera la guarda y la otra no hacía
        # que la respuesta dependiera de cuál usara el endpoint, que es lo mismo
        # que ya pasó con el orden de los parámetros.
        raise NoAutenticado("Esta operación exige autenticación", error_code="auth.requerida")

    # EL MODO SOLO LECTURA SE APLICA AQUÍ. `exigir_escritura` estaba escrita,
    # probada y **sin que la llamara nadie**: se podía entrar en modo degradado
    # y las escrituras seguían pasando. O sea, el modo existía en la página de
    # estado y no existía en el sistema.
    #
    # Va en la unidad de trabajo y no en cada ruta porque es por donde pasan
    # todas las escrituras: ponerlo ruta a ruta es «funciona donde alguien se
    # acordó», y durante una incidencia el que falta es el que escribe.
    from crmcore.resiliencia import exigir_escritura

    exigir_escritura()

    # Si hay una sesión COMPARTIDA, se usa esa y no se abre otra — exactamente
    # igual que en `get_db`, y por el mismo motivo.
    #
    # **Esta mitad faltaba.** `get_db` lo miraba desde el principio y `get_uow`
    # no, así que una petición compuesta cumplía «todo o nada» sólo si la ruta
    # usaba `DbDep`. Las que usan `UowDep` —las escrituras que emiten eventos,
    # o sea casi todas— abrían su propia sesión y la **confirmaban** al acabar
    # su sub-petición: lo escrito por las operaciones anteriores quedaba
    # confirmado de verdad antes de que fallara la siguiente, y el `rollback()`
    # del conjunto ya no lo tocaba.
    #
    # Quien mandaba «crea la cuenta y luego el contacto» y fallaba en el
    # contacto se quedaba con la cuenta creada **y** un error diciendo que se
    # había deshecho todo. Medido por HTTP en
    # `test_la_peticion_compuesta_es_todo_o_nada.py`.
    #
    # Los eventos sí se vuelcan aquí: son de esta operación y tienen que
    # escribirse dentro de la misma transacción que el cambio. Quien confirma
    # —o deshace— es el dueño de la sesión compartida, que es el único que sabe
    # si el conjunto entero salió bien.
    compartida = _sesion_compartida.get()
    if compartida is not None:
        uow = UnidadDeTrabajo(db=compartida, tenant_id=compartida.info.get("tenant_id"))
        yield uow
        uow._volcar_eventos()
        return

    db = nueva_sesion(principal.tenant_id, sistema=principal.es_admin_plataforma)
    uow = UnidadDeTrabajo(db=db, tenant_id=db.info.get("tenant_id"))
    try:
        yield uow
        uow._volcar_eventos()
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    despertar_relevo()


UowDep = Annotated[Any, Depends(get_uow)]


def proyectar_para(
    principal: Principal, db: Any, *, objeto: str, modelo: type
) -> Callable[[Any], dict[str, Any]]:
    """Devuelve la función que serializa un registro **ya filtrado**.

    Se usa así en un endpoint:

        proyecta = proyectar_para(principal, db, objeto="cuenta", modelo=Cuenta)
        return [proyecta(c) for c in cuentas]

    Es una llamada explícita y no magia en la serialización, y es deliberado:
    enmascarar el campo equivocado en silencio es peor que una llamada que
    falta, porque una llamada que falta la caza el gate
    (`test_contratos_arquitectura.py`) y un enmascarado equivocado no lo caza
    nadie hasta que un cliente enseña una pantalla con puntos donde debería
    haber un teléfono.

    La política se resuelve **una vez** y se cierra sobre el resultado: hacerlo
    por fila consultaría las excepciones una vez por registro, y un listado de
    doscientas cuentas haría doscientas consultas para aplicar la misma regla.
    """
    from crmcore.authz.proyeccion import (
        _excepciones,
        _nivel_del_campo,
        _politica_por_rol,
        anotar_retenidos,
        enmascarable,
    )
    from crmcore.config import get_settings
    from crmcore.security.cifrado import enmascarar

    activo = bool(get_settings().masking_enabled)
    politica = _politica_por_rol(db) if activo else {}
    excepciones = _excepciones(db, principal.tenant_id, objeto) if activo else {}

    # Los campos CALCULADOS del tenant (CRM-00.04.01.04), resueltos una vez
    # igual que la política: leer el esquema por fila haría una consulta por
    # registro de un listado de doscientos.
    #
    # Se evalúan aquí porque aquí pasan **todas** las lecturas —listado, ficha y
    # exportación—: el tipo de campo «fórmula» se podía declarar desde el primer
    # día y no lo evaluaba nadie, así que el campo existía, la persona escribía
    # su fórmula y el registro no enseñaba ningún valor. Sin error.
    # El `try` lleva SAVEPOINT y no va suelto, y la diferencia no es cosmética:
    # el 27-10-2026 faltaba `esquemas_tenant` en siete de los trece esquemas, la
    # consulta de aquí reventaba, el `except` lo daba por «sin fórmulas» —que es
    # la respuesta correcta— y la petición se moría DOS líneas más abajo, al
    # leer las políticas ABAC, con un `InFailedSqlTransaction` que no nombraba
    # ni el metamodelo ni la tabla que faltaba. `GET /ia/agentes-autonomos` daba
    # 500 y el mensaje mandaba a buscar el fallo donde no estaba.
    formulas: list[tuple[str, str]] = []
    with al_margen(db, "proyeccion.formulas_no_resueltas", objeto=objeto):
        from crmcore.metamodelo import campos_de

        formulas = [
            (str(c.get("nombre")), str((c.get("restricciones") or {}).get("formula") or ""))
            for c in campos_de(db, principal.tenant_id, objeto)
            if c.get("tipo") == "formula" and c.get("activo", True)
        ]
    roles = frozenset(principal.roles) | (
        {"admin"} if principal.es_admin_plataforma else frozenset()
    )

    def _proyecta(fila: Any) -> dict[str, Any]:
        datos = fila.a_dict() if hasattr(fila, "a_dict") else dict(fila)
        if formulas:
            from crmcore.datos.formulas import evaluar

            # Dentro de `campos`, que es donde viven los del tenant. Y el
            # calculado **pisa** lo que hubiera guardado con ese nombre: un
            # campo calculado no se escribe, se calcula, y un valor viejo
            # guardado ahí sería el que se enseñara.
            propios = dict(datos.get("campos") or {})
            contexto = {**datos, **propios}
            for nombre_formula, texto in formulas:
                if texto:
                    propios[nombre_formula] = evaluar(texto, contexto)
            datos = {**datos, "campos": propios}
        # Las políticas ABAC de alcance «campos» (CRM-00.05.02.20) se evalúan
        # POR REGISTRO, no una vez: dependen de la fila —«el margen de las
        # oportunidades de otra unidad de negocio»—, así que no se pueden
        # resolver fuera del bucle como la política por sensibilidad.
        #
        # Se hace aunque el enmascarado global esté apagado: `MASKING_ENABLED`
        # gobierna la proyección por sensibilidad, que es una decisión de
        # despliegue; una política la ha escrito el cliente y apagarla desde el
        # `.env` sería saltarse su configuración desde la nuestra.
        por_politica = _ocultos_de_politica(db, objeto, datos)
        if not activo:
            return (
                {k: v for k, v in datos.items() if k not in por_politica} if por_politica else datos
            )
        salida: dict[str, Any] = {}
        retenidos: set[str] = set(por_politica)
        for campo, valor in datos.items():
            if campo in por_politica:
                continue
            nivel = _nivel_del_campo(campo, modelo, roles, politica, excepciones)
            if nivel == "claro" or valor is None:
                salida[campo] = valor
            elif nivel == "enmascarado":
                # Solo se enmascara lo que se puede enmascarar sin cambiar de
                # tipo. Ver `crmcore.authz.proyeccion.enmascarable`: hacerlo
                # sobre un número o una lista producía una cadena que rompía el
                # contrato y devolvía un 500.
                salida[campo] = enmascarar(valor) if enmascarable(modelo, campo, valor) else valor
            else:
                # Se anota para anunciarlo en la cabecera `X-Campos-Retenidos`.
                # Sin ese anuncio, el cliente no puede distinguir «este campo
                # está vacío» de «este campo no te lo doy», y esa diferencia
                # cambia lo que hace con él: rellenarlo o pedir permiso.
                retenidos.add(campo)
        anotar_retenidos(retenidos)
        return salida

    return _proyecta


def _ocultos_de_politica(db: Any, objeto: str, datos: dict[str, Any]) -> set[str]:
    """Campos que una política ABAC esconde en este registro concreto.

    Si evaluar falla **se esconde**, no se enseña: un error resolviendo una
    política que restringe no se puede resolver enseñando el campo. Como no se
    sabe cuáles tocaba esconder, se esconden todos los que alguna política
    controla para ese objeto — acotado, y sin enseñar nada que se estuviera
    negando. Es la regla contraria a la de compartición, y está razonada en
    `crmcore.authz.decision`.
    """
    from crmcore.authz.decision import campos_ocultos
    from crmcore.logging import get_logger

    try:
        return campos_ocultos(db, objeto=objeto, registro=datos)
    except Exception as exc:  # noqa: BLE001 — ante la duda, no se enseña
        # Con la traza y el tipo, no sólo el mensaje. Sin esto, un fallo aquí
        # sale como «current transaction is aborted» —que es la CONSECUENCIA de
        # otro error anterior, no la causa— y no hay forma de saber de dónde
        # vino: costó una tarde perseguir uno así, con el mensaje bueno
        # escondido detrás del de la transacción rota.
        import traceback

        get_logger(__name__).error(
            "abac.fallo_al_ocultar",
            objeto=objeto,
            tipo=type(exc).__name__,
            error=str(exc)[:300],
            traza=traceback.format_exc()[-1200:],
        )
        try:
            from crmcore.authz.politicas import campos_gobernados
            from crmcore.tenancy.context import contexto_actual

            tid = contexto_actual().tenant_id
            return campos_gobernados(db, tid, objeto) if tid else set()
        except Exception:  # noqa: BLE001 — si ni eso se puede, no se sirve la ficha
            raise exc from None
