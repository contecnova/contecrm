"""Descubrimiento de la superficie de administración (CRM-07.01.01.01).

«La consola de administración está replicada al 100 % por API» es una promesa
que se incumple sola: basta que alguien añada una pantalla con una acción que
solo la consola sabe hacer. Al mes siguiente la integración de un cliente no
puede automatizar un alta y nadie sabe decir desde cuándo.

Aquí esa promesa se convierte en algo comprobable. Cada servicio publica su
**superficie**: las operaciones que expone, con su método, su ruta, qué permiso
piden y si son de administración. La consola se construye leyendo esto, así que
no puede existir una acción de consola que no sea una llamada de esta lista —
por construcción, no por disciplina.

Se monta sola en `crear_servicio`, como la salud. Si dependiera de que cada
servicio se acuerde de montarla, faltaría en alguno, y precisamente en el que
menos se mira.
"""

from __future__ import annotations

from typing import Any, get_origin

from fastapi import APIRouter, FastAPI

# Marcadores que identifican una etiqueta de administración. Se comparan como
# **fragmento** y sin acentos porque los servicios rotulan a su manera
# —«claves de API», «roles y permisos», «administración de party»— y una lista
# de etiquetas exactas se queda desfasada en cuanto alguien rotula distinto.
# Cuando eso pasa no falla nada: simplemente esa operación deja de contarse
# como de administración, y el fallo pasa desapercibido.
MARCADORES_ADMIN = (
    "tenant",
    "plan",
    "flag",
    "ajuste",
    "plantilla",
    "calendario",
    "moneda",
    "rol",
    "usuario",
    "sesion",
    "clave",
    "compartici",
    "administraci",
    "papelera",
    "metadato",
    "integraci",
    "webhook",
    "evento",
    "enrutamiento",
    "cola de fallidos",
    "automatizaci",
    "proceso",
)


def _sin_acentos(texto: str) -> str:
    import unicodedata

    return "".join(
        c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn"
    )


def es_administracion(etiquetas: list[str]) -> bool:
    """Si alguna etiqueta de la ruta la señala como de administración."""
    normalizadas = [_sin_acentos(e) for e in etiquetas]
    return any(m in e for e in normalizadas for m in MARCADORES_ADMIN)


def _permiso_de(ruta: Any) -> str | None:
    """Saca el permiso que exige una ruta de sus dependencias.

    Lee el nombre del argumento por defecto de la dependencia generada por
    `exige_permiso`, que es donde queda el permiso. Es introspección, sí, pero
    la alternativa —declarar el permiso otra vez en una tabla— tendría dos
    fuentes de verdad y la tabla se quedaría atrás.
    """
    for dependencia in (
        getattr(ruta, "dependant", None).dependencies if getattr(ruta, "dependant", None) else []
    ):
        cierre = getattr(dependencia.call, "__closure__", None) or ()
        for celda in cierre:
            valor = celda.cell_contents
            if isinstance(valor, str) and ":" in valor and " " not in valor:
                return valor
    return None


def _objeto_de(camino: str) -> str:
    """El objeto de negocio del recurso que lleva esta ruta, si se sabe."""
    from crmcore.http.listados import objeto_del_recurso

    partes = [p for p in camino.split("/") if p]
    # `/api/v1/<recurso>/...`: el recurso es el tercer segmento.
    return objeto_del_recurso(partes[2]) if len(partes) >= 3 else ""


def _devuelve_lista(ruta: Any) -> bool:
    """¿Esta operación devuelve **muchos** registros o uno solo?

    Lo necesita el front para distinguir una sub-colección de una vista. Sin
    esto, cualquier `GET /cosa/{id}/loquesea` se pintaba como un panel plegable
    con su lista dentro, y los que devuelven un objeto —la vista 360 de la
    cuenta, a quién llamar de un proveedor— salían como un panel que dice
    «Nada todavía» para siempre. Un panel que nunca puede tener contenido es
    peor que no tenerlo: parece que falta el dato.
    """
    modelo = getattr(ruta, "response_model", None)
    if modelo is None:
        return False
    origen = get_origin(modelo)
    if origen in (list, tuple, set, frozenset):
        return True
    # Una página con cursor también es una colección, y es la otra forma en que
    # este sistema devuelve muchos.
    campos = getattr(modelo, "model_fields", None)
    return bool(campos and "items" in campos)


def _exige_datos(ruta: Any) -> bool:
    """¿Hace falta darle algo por la URL además de los tramos de la ruta?

    Lo necesita el front para no pintar como panel lo que no puede funcionar sin
    más información: «a quién puedo contactar» exige la finalidad y el canal, y
    «la ruta del técnico» exige el día. Pedidos sin eso responden 422, y en la
    ficha eso salía como un panel que **siempre** da error — no como una
    pregunta a la que falta contestar.
    """
    from pydantic_core import PydanticUndefined

    dependant = getattr(ruta, "dependant", None)
    for parametro in getattr(dependant, "query_params", []) or []:
        campo = getattr(parametro, "field_info", None)
        # Obligatorio es «sin valor por defecto». Pydantic lo marca con su
        # propio centinela, no con `...`: comprobando `...` no salía ninguno, y
        # el gate pasaba diciendo que no hay ninguna operación que exija datos.
        if getattr(campo, "default", None) in (PydanticUndefined, Ellipsis):
            return True
    return False


def _es_de_plataforma(ruta: Any) -> bool:
    """Si esta operación solo la puede hacer quien opera la plataforma.

    Se lee de sus dependencias, como el permiso, y por el mismo motivo: la
    alternativa es una lista en el front que hay que acordarse de actualizar, y
    lo que pasa cuando no se actualiza es que a un administrador de empresa se
    le enseña un menú entero —«Tenants y unidades»— cuyo contenido no puede ver
    y que al abrirlo solo dice que no es para él.

    `es_admin_plataforma` no es un permiso: un administrador de empresa tiene
    `tenant:read` y aun así recibe 403. Por eso no basta con mirar permisos.
    """
    dependant = getattr(ruta, "dependant", None)
    for dependencia in getattr(dependant, "dependencies", []) or []:
        if getattr(dependencia.call, "__name__", "") == "exige_plataforma":
            return True
        # `PlataformaDep` llega como sub-dependencia del propio parámetro.
        for hija in getattr(dependencia, "dependencies", []) or []:
            if getattr(hija.call, "__name__", "") == "exige_plataforma":
                return True
    return False


def _rutas_planas(app: FastAPI) -> list[tuple[str, Any]]:
    """Todas las rutas del servicio, incluidas las de routers incluidos.

    Las versiones recientes de FastAPI no aplanan `include_router`: dejan un
    envoltorio perezoso en `app.routes` que resuelve sus rutas al atender la
    petición. Recorrer `app.routes` a secas, que es lo que uno escribe primero,
    devuelve **cuatro** operaciones en un servicio con veintiuna, y el resultado
    parece correcto porque no falla nada.
    """
    planas: list[tuple[str, Any]] = []
    pendientes: list[tuple[str, Any]] = [("", r) for r in app.routes]
    while pendientes:
        prefijo, ruta = pendientes.pop()
        interno = getattr(ruta, "original_router", None)
        if interno is not None:
            # El prefijo con el que se incluyó vive en el envoltorio, no en las
            # rutas: sin arrastrarlo, la superficie anunciaría `/calendarios` y
            # quien lo llamara recibiría un 404, porque la ruta real es
            # `/api/v1/calendarios`.
            contexto = getattr(ruta, "include_context", None)
            suyo = getattr(contexto, "prefix", "") or ""
            pendientes.extend((prefijo + suyo, r) for r in getattr(interno, "routes", []))
            continue
        anidadas = getattr(ruta, "routes", None)
        if anidadas and not getattr(ruta, "methods", None):
            pendientes.extend((prefijo, r) for r in anidadas)
            continue
        planas.append((prefijo, ruta))
    return planas


def montar_superficie(app: FastAPI, nombre: str, prefijo: str) -> None:
    """Añade `/superficie` al servicio."""

    router = APIRouter(tags=["superficie"])

    @router.get(
        f"{prefijo}/superficie",
        summary="Qué sabe hacer este servicio",
        description=(
            "Lista todas las operaciones del servicio con su método, ruta, "
            "permiso exigido y si son de administración. La consola se "
            "construye a partir de esto: es lo que garantiza que no haya "
            "ninguna acción que solo se pueda hacer desde la interfaz."
        ),
    )
    def superficie() -> dict[str, Any]:  # noqa: C901 — un solo recorrido, sin ramas ocultas
        operaciones: list[dict[str, Any]] = []
        for prefijo, ruta in _rutas_planas(app):
            metodos = getattr(ruta, "methods", None)
            camino = prefijo + getattr(ruta, "path", "")
            if not metodos or camino.startswith("/health") or camino.endswith("/superficie"):
                continue
            etiquetas = [str(t) for t in (getattr(ruta, "tags", None) or [])]
            for metodo in sorted(metodos - {"HEAD", "OPTIONS"}):
                operaciones.append(
                    {
                        "metodo": metodo,
                        "ruta": camino,
                        "resumen": getattr(ruta, "summary", "") or "",
                        "etiquetas": etiquetas,
                        "permiso": _permiso_de(ruta),
                        "administracion": es_administracion(etiquetas),
                        "solo_plataforma": _es_de_plataforma(ruta),
                        "devuelve_lista": _devuelve_lista(ruta),
                        "exige_datos": _exige_datos(ruta),
                        # De qué objeto de negocio es este recurso.
                        #
                        # Va aquí porque el registro que lo sabe se llena al
                        # montar los routers, y eso pasa DENTRO de cada servicio:
                        # otro proceso que lo pregunte se encuentra el registro
                        # vacío. La superficie es justo lo que cada servicio
                        # publica de sí mismo, así que es donde tiene que salir.
                        #
                        # Sin esto, quien monta informes no sabe que los de
                        # «oportunidad» se leen de `opportunities`, y no se puede
                        # adivinar: la ruta está en inglés porque es contrato con
                        # quien integra, y el objeto en castellano porque es el
                        # idioma del negocio.
                        "objeto": _objeto_de(camino),
                    }
                )
        operaciones.sort(key=lambda o: (o["ruta"], o["metodo"]))
        return {
            "servicio": nombre,
            "total": len(operaciones),
            "administracion": sum(1 for o in operaciones if o["administracion"]),
            "solo_plataforma": sum(1 for o in operaciones if o["solo_plataforma"]),
            "operaciones": operaciones,
        }

    app.include_router(router)
