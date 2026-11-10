"""El token que lleva dentro a qué registro puede mirar (CRM-00.02.03.05).

Un componente embebible se incrusta en una página que **no es nuestra**: el
portal de un cliente, una intranet, una web pública. Y ahí la pregunta que
decide si la capacidad sirve o es un agujero no es cómo se pinta, es **con qué
identidad habla**.

**Con la sesión del CRM, no.** Un componente que usa la sesión deja entrar a
quien pase por la página: basta con abrir las herramientas del navegador, coger
el token y llamar a la API con él. A partir de ahí tiene todo lo que tiene la
persona que lo emitió.

Por eso el token es **acotado al registro que enseña**, y el acotamiento no es
un permiso: es que **el identificador va dentro del token**. El extremo del
componente no recibe ningún identificador por la URL —no hay nada que cambiar
en las herramientas del navegador— y lee el suyo del token. Un token de la
cuenta A no puede pedir la cuenta B porque no hay forma de pedir la cuenta B.

Y dura poco. Un token embebido vive en el HTML de una página que puede quedarse
abierta toda la noche en el mostrador de una tienda; con una hora de vida, lo
que se filtra caduca solo.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from crmcore.errors import NoAutenticado, Prohibido

# El tipo de principal que llevan estos tokens. Se mira por nombre y no por
# ausencia de permisos: un token sin permisos podría ser otra cosa mañana, y
# entonces esta comprobación dejaría de significar lo que dice.
TIPO = "componente"

# Qué tipo de registro enseña cada componente y qué alcance lleva su token. Una
# sola tabla para quien emite el token (el gateway) y quien lo atiende (cada
# servicio, con `crmcore.http.deps.exige_componente`): con dos, el día que no
# coincidan el token sale bien y la ruta lo rechaza —o al revés—.
#
# El alcance es lo mínimo para pintar eso y nada más. No hereda los permisos de
# quien lo pide: si los heredara, el token de un escaparate llevaría dentro los
# de un administrador.
OBJETO_DE_COMPONENTE: dict[str, str] = {
    "ficha-cuenta": "cuenta",
    "lista-casos": "cuenta",
    "formulario-alta": "formulario",
    "estado-pedido": "pedido",
}
# Dónde se pregunta si quien PIDE el token puede ver ese registro: la ficha del
# servicio dueño, con su identidad. Ahí está toda la visibilidad —permiso,
# compartición, unidad de negocio— y repetirla en el gateway sería escribir
# otra respuesta a «¿puede ver esto?», que es la que se queda corta.
RUTA_DEL_OBJETO: dict[str, str] = {
    "cuenta": "/accounts/{id}",
    "formulario": "/captura/canales/{id}",
    "pedido": "/pedidos/{id}",
}
PERMISOS_DE_COMPONENTE: dict[str, list[str]] = {
    "ficha-cuenta": ["party:read"],
    "lista-casos": ["case:read"],
    "formulario-alta": ["lead:write"],
    "estado-pedido": ["sales:read"],
}


def validar(componente: str, objeto: str) -> None:
    """Que el componente exista y enseñe ese tipo de objeto.

    Aparte de `emitir` porque quien emite pregunta antes al servicio dueño si
    quien lo pide puede ver el registro, y esa pregunta no tiene sentido —ni
    se sabe a quién hacerla— con un componente o un objeto que no casan.
    """
    from crmcore.errors import ErrorValidacion
    from crmcore.sdk import COMPONENTES

    if componente not in COMPONENTES:
        raise ErrorValidacion(
            f"Componente desconocido: «{componente}»",
            error_code="embebido.componente_desconocido",
            detalle={"admitidos": list(COMPONENTES)},
        )

    esperado = OBJETO_DE_COMPONENTE.get(componente)
    if esperado and objeto != esperado:
        # Un token de «ficha-cuenta» sobre un pedido sale bien y la ruta lo
        # rechaza después: quien integra ve un 403 en la web de su cliente sin
        # saber por qué. Se dice al emitirlo, que es cuando se puede corregir.
        raise ErrorValidacion(
            f"El componente «{componente}» enseña un «{esperado}», no un «{objeto}»",
            error_code="embebido.objeto_no_corresponde",
            detalle={"objeto": esperado},
        )


def emitir(
    *,
    componente: str,
    objeto: str,
    objeto_id: UUID,
    tenant_id: UUID,
    permisos: list[str],
    minutos: int,
) -> dict[str, Any]:
    """Un token para UN componente sobre UN registro.

    `permisos` lo pone quien lo emite y se queda corto a propósito: lo mínimo
    para pintar eso y nada más. No hereda los de quien lo pide — si los
    heredara, el token de un escaparate llevaría dentro los de un administrador.
    """
    import jwt

    from crmcore.config import get_settings

    validar(componente, objeto)
    s = get_settings()
    ahora = datetime.now(timezone.utc)
    caduca = ahora + timedelta(minutes=max(1, minutos))
    carga = {
        "tipo": TIPO,
        "tenant": str(tenant_id),
        "componente": componente,
        # **Aquí está el acotamiento.** El extremo no recibe identificador por
        # la URL: lee éste.
        "objeto": objeto,
        "objeto_id": str(objeto_id),
        "permisos": sorted(set(permisos)),
        "iat": int(ahora.timestamp()),
        "exp": int(caduca.timestamp()),
    }
    return {
        "token": jwt.encode(carga, s.secret_key.get_secret_value(), algorithm=s.jwt_algorithm),
        "caduca_at": caduca.isoformat(),
        "componente": componente,
        "objeto": objeto,
        "objeto_id": str(objeto_id),
        # Se devuelve también lo que NO puede hacer, porque quien integra esto
        # necesita saberlo antes de ponerlo en una página pública.
        "alcance": (
            "Sólo este registro y sólo para leerlo. El identificador va dentro "
            "del token: no hay forma de apuntarlo a otro."
        ),
    }


def registro_del_token(principal: Any, *, componente: str, objeto: str) -> UUID:
    """El identificador que lleva el token, comprobando que es el que toca.

    Tres comprobaciones y cada una tapa un agujero distinto:

      * que sea un token de componente —uno de sesión aquí daría a cualquiera
        con sesión acceso por una puerta que no revisa permisos de fila—;
      * que sea de ESTE componente —si no, el token de una lista de casos
        serviría para abrir la ficha de la cuenta—;
      * y que sea de este tipo de objeto, por lo mismo.
    """
    if getattr(principal, "tipo", "") != TIPO:
        raise NoAutenticado(
            "Esta ruta sólo la atiende un token de componente embebido",
            error_code="embebido.token_no_es_de_componente",
        )
    extra = getattr(principal, "atributos", None) or {}
    suyo_componente = str(extra.get("componente") or "")
    suyo_objeto = str(extra.get("objeto") or "")
    bruto = str(extra.get("objeto_id") or "")
    if suyo_componente != componente or suyo_objeto != objeto or not bruto:
        raise Prohibido(
            "Este token no es de este componente",
            error_code="embebido.token_de_otro_componente",
        )
    try:
        return UUID(bruto)
    except ValueError:
        raise NoAutenticado(
            "El token no lleva un registro válido", error_code="embebido.token_malformado"
        )
