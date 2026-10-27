"""API del gateway: proxy autenticado y superficie propia mínima."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
from crmcore.config import get_settings
from crmcore.errors import ErrorValidacion, LimiteExcedido, NoDisponible, NoEncontrado
from crmcore.http.deps import (
    AutenticadoDep,
    PlataformaDep,
    PrincipalDep,
    cookie_rechazada,
    exige_firma_interna,
    exige_permiso,
    ip_de,
)
from crmcore.http.parametros import admite_parametros_abiertos
from crmcore.logging import get_logger
from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from services.gateway import anomalias, empuje, operatividad, proxy, rutas
from services.gateway import superficie_api as superficie
from services.gateway.sesion import crear_router_sesion

logger = get_logger(__name__)

# Router propio del gateway, bajo `/api/v1`.
router = APIRouter(tags=["gateway"])

# Router del proxy: se monta SIN prefijo porque reenvía la ruta completa.
router_proxy = APIRouter(tags=["gateway"])

# Cliente HTTP reutilizado: crear uno por petición desperdicia el pool de
# conexiones y añade un handshake TLS a cada llamada interna.
_cliente: httpx.AsyncClient | None = None
_destinos: dict[str, rutas.Destino] = {}


async def arrancar() -> None:
    """Prepara el cliente HTTP y la tabla de destinos."""
    global _cliente, _destinos

    _destinos = rutas.cargar_destinos(get_settings().rutas_servicios)
    # Sin límite de conexiones el gateway puede abrir miles contra un servicio
    # lento y quedarse sin descriptores; con un límite, las peticiones esperan
    # en cola, que es un fallo mucho más benigno.
    _cliente = httpx.AsyncClient(
        limits=httpx.Limits(max_connections=200, max_keepalive_connections=50),
        follow_redirects=False,
    )
    logger.info("gateway.destinos", servicios=sorted(_destinos))


def cliente_y_destino(servicio: str) -> tuple[Any, str]:
    """El cliente HTTP del gateway y la URL de un servicio. Para el middleware.

    Se expone en vez de importar `_cliente` desde fuera porque el middleware
    corre por petición y el cliente se crea al arrancar: leer la variable
    directamente daría `None` en la primera petición si algo cambiara el orden.
    """
    destino = _destinos.get(servicio)
    return _cliente, (destino.url_base if destino else "")


async def parar() -> None:
    if _cliente is not None:
        await _cliente.aclose()


@router.get("/servicios", summary="Servicios enrutados y su salud")
async def servicios(_: PrincipalDep) -> Any:
    """Estado de los servicios de detrás.

    Es el registro de servicios en su forma mínima (CRM-00.03.01.04): qué hay,
    dónde está y si responde. Se consulta en vivo en vez de cachearse: el valor
    de este endpoint es decir la verdad en el momento en que se pregunta.
    """
    if _cliente is None:
        raise NoDisponible("El gateway aún no ha arrancado", error_code="gateway.arrancando")

    salida = []
    for nombre, destino in sorted(_destinos.items()):
        try:
            respuesta = await _cliente.get(f"{destino.url_base}/health/ready", timeout=3.0)
            salida.append(
                {
                    "servicio": nombre,
                    "url": destino.url_base,
                    "estado": "listo" if respuesta.status_code == 200 else "no listo",
                    "detalle": respuesta.json().get("comprobaciones", {}),
                }
            )
        except Exception as exc:  # noqa: BLE001 — un servicio caído es información, no un error
            salida.append(
                {
                    "servicio": nombre,
                    "url": destino.url_base,
                    "estado": "inalcanzable",
                    "detalle": str(exc)[:200],
                }
            )
    return salida


@router.get(
    "/contrato/{servicio}",
    summary="El contrato OpenAPI de un servicio",
    description=(
        "Devuelve el OpenAPI del servicio indicado, tal cual lo publica él.\n\n"
        "Existe porque el front **genera los formularios leyendo el contrato**: "
        "los campos de un alta salen del esquema de la operación, no de una "
        "lista escrita en el front. Sin esta ruta, la llamada fallaba con 404, "
        "el front se lo tragaba —está dentro de un `catch`— y **todos** los "
        "formularios de alta salían vacíos, sin que nada lo dijera.\n\n"
        "No se enruta `/api/v1/<servicio>/...` de forma general a propósito: "
        "eso expondría cada ruta interna de cada servicio por un camino "
        "paralelo al de la tabla de enrutado, que es la única lista de "
        "acoplamiento del sistema."
    ),
)
async def contrato_de_servicio(servicio: str, _: PrincipalDep) -> Any:
    if _cliente is None:
        raise NoDisponible("El gateway aún no ha arrancado", error_code="gateway.arrancando")
    destino = _destinos.get(servicio)
    if destino is None:
        # 404 con la lista de los que sí hay: un 404 a secas deja a quien
        # integra sin saber si se equivocó de nombre o si el servicio no está
        # desplegado en esta instalación, que son dos problemas distintos.
        raise NoEncontrado(
            f"No hay ningún servicio enrutado con el nombre «{servicio}»",
            error_code="gateway.servicio_desconocido",
            detalle={"servicios": sorted(_destinos)},
        )
    # Por el prefijo configurado y no por `/openapi.json` a secas: el contrato
    # se publica bajo el prefijo de versión de la API (`/api/v1/openapi.json`),
    # que es el mismo ajuste con el que se sirve todo lo demás.
    prefijo = get_settings().api_prefix.rstrip("/")
    try:
        respuesta = await _cliente.get(f"{destino.url_base}{prefijo}/openapi.json", timeout=10.0)
    except httpx.HTTPError as exc:
        raise NoDisponible(
            f"El servicio «{servicio}» no ha contestado con su contrato",
            error_code="gateway.contrato_no_disponible",
        ) from exc
    if respuesta.status_code != 200:
        raise NoDisponible(
            f"El servicio «{servicio}» ha contestado {respuesta.status_code} a su contrato",
            error_code="gateway.contrato_no_disponible",
        )
    return respuesta.json()


@router.get(
    "/estado",
    summary="Cómo va MI CRM ahora mismo",
    description=(
        "La página de estado privada de este tenant: junta lo que publica cada "
        "servicio sobre **sus** componentes y devuelve una sola vista.\n\n"
        "Se compone en vez de calcularse en un sitio porque ningún servicio "
        "lee las tablas de otro: el estado de los webhooks lo sabe `eventing` y "
        "el de las cuotas lo sabe `tenancy`. Cada uno publica lo suyo.\n\n"
        "Solo dice lo de este tenant. Ni cuántos hay, ni cómo van los demás, ni "
        "qué versión corre cada réplica: una página de estado que filtra la "
        "forma de la plataforma es un mapa para quien quiera atacarla."
    ),
)
async def estado_del_tenant(request: Request, principal: AutenticadoDep) -> Any:
    import asyncio
    from datetime import datetime, timezone

    from crmcore.config import get_settings
    from crmcore.datos.estado import _peor

    if _cliente is None:
        raise NoDisponible("El gateway aún no ha arrancado", error_code="gateway.arrancando")

    cabeceras = proxy.cabeceras_de_identidad(
        principal, get_settings().secret_key.get_secret_value()
    )

    async def _preguntar(nombre: str) -> list[dict[str, Any]]:
        try:
            respuesta = await _cliente.get(
                f"{_destinos[nombre].url_base}/api/v1/estado",
                headers=cabeceras,
                timeout=5.0,
            )
            if respuesta.status_code != 200:
                raise RuntimeError(f"respondió {respuesta.status_code}")
            return [
                {**componente, "servicio": nombre}
                for componente in respuesta.json().get("componentes", [])
            ]
        except Exception:  # noqa: BLE001 — un servicio caído es información, no un error
            # No se filtra el mensaje: el de un error de conexión lleva host y
            # puerto, y esta página la ve el cliente.
            return [
                {
                    "servicio": nombre,
                    "componente": nombre,
                    "estado": "caido",
                    "detalle": "El servicio no responde",
                }
            ]

    # En paralelo: en serie, diez servicios con cinco segundos de plazo son
    # cincuenta segundos de espera en el peor caso — justo cuando algo va mal y
    # el cliente más necesita la página.
    respuestas = await asyncio.gather(*(_preguntar(n) for n in sorted(_destinos)))
    componentes: list[dict[str, Any]] = [c for lote in respuestas for c in lote]

    return {
        "estado": _peor([c["estado"] for c in componentes]) if componentes else "caido",
        "consultado_at": datetime.now(timezone.utc).isoformat(),
        "componentes": componentes,
        "cacheado": False,
    }


@router.get(
    "/estado/consumo",
    summary="Cuánta cuota lleva gastada este tenant, sumando todos los módulos",
    description=(
        "Las cuotas van **por módulo** —cada servicio guarda lo suyo y cuenta lo "
        "suyo—, así que la suma se compone preguntando a cada uno.\n\n"
        "**Un servicio que no contesta sale como «no se ha podido leer», nunca "
        "como cero.** Un cero es una afirmación falsa —«no has gastado nada»— y "
        "un cliente que ve ceros llega al tope sin haber visto subir el número "
        "nunca. «No se ha podido leer» es verdad y se puede mirar."
    ),
)
async def consumo_del_tenant(request: Request, principal: AutenticadoDep) -> Any:
    import asyncio
    from datetime import datetime, timezone

    from crmcore.config import get_settings

    if _cliente is None:
        raise NoDisponible("El gateway aún no ha arrancado", error_code="gateway.arrancando")

    cabeceras = proxy.cabeceras_de_identidad(
        principal, get_settings().secret_key.get_secret_value()
    )

    async def _preguntar(nombre: str) -> dict[str, Any]:
        try:
            respuesta = await _cliente.get(
                f"{_destinos[nombre].url_base}/api/v1/estado/consumo",
                headers=cabeceras,
                timeout=5.0,
            )
            if respuesta.status_code != 200:
                raise RuntimeError(f"respondió {respuesta.status_code}")
            return {"servicio": nombre, "legible": True, "metricas": respuesta.json()["metricas"]}
        except Exception:  # noqa: BLE001 — un servicio caído es información, no un error
            # NO SE DEVUELVE CERO. El mensaje del error tampoco se filtra: lleva
            # host y puerto, y esto lo ve el cliente.
            return {
                "servicio": nombre,
                "legible": False,
                "porque": "El servicio no responde: su consumo no se ha podido leer",
            }

    # En paralelo, por lo mismo que la página de estado: en serie, diez servicios
    # con cinco segundos de plazo son cincuenta segundos de espera justo cuando
    # algo va mal.
    respuestas = await asyncio.gather(*(_preguntar(n) for n in sorted(_destinos)))

    # La suma por métrica, arrastrando lo que no se ha podido leer. Sumar sólo lo
    # legible y callar lo demás daría un total que parece completo y no lo es.
    total: dict[str, dict[str, Any]] = {}
    sin_leer: list[str] = []
    for r in respuestas:
        if not r["legible"]:
            sin_leer.append(r["servicio"])
            continue
        for m in r["metricas"]:
            if not m.get("legible", True):
                sin_leer.append(f"{r['servicio']}/{m['metrica']}")
                continue
            acumulado = total.setdefault(
                m["metrica"], {"metrica": m["metrica"], "consumido": 0, "por_modulo": {}}
            )
            acumulado["consumido"] += m["consumido"]
            acumulado["por_modulo"][r["servicio"]] = m["consumido"]
            # El tope es por módulo, así que el máximo declarado se enseña al
            # lado en vez de sumarse: sumar topes daría un límite que no existe
            # en ninguna parte.
            if not m["sin_limite"]:
                acumulado.setdefault("topes_por_modulo", {})[r["servicio"]] = m["limite"]

    return {
        "consultado_at": datetime.now(timezone.utc).isoformat(),
        "metricas": sorted(total.values(), key=lambda m: m["metrica"]),
        # Se dice arriba y no enterrado en una fila: un total al que le falta un
        # módulo no es un total, y quien lo mire tiene que saberlo antes de
        # tomar una decisión con él.
        "completo": not sin_leer,
        "no_leidos": sorted(set(sin_leer)),
    }


@router.get(
    "/estado/slo",
    summary="Cuánto margen queda antes de incumplir lo prometido",
    description=(
        "El presupuesto de error de cada servicio para este tenant "
        "(CRM-00.06.01.04), con el objetivo del **tier contratado**.\n\n"
        "Se compone aquí porque el tier lo sabe `tenancy` y el tráfico lo sabe "
        "cada servicio, y ninguno lee las tablas del otro. El gateway pregunta "
        "el tier una vez y se lo pasa a todos: así el objetivo que se aplica es "
        "el que se firmó, y no el que cada servicio se hubiera supuesto.\n\n"
        "Lo que no se ha podido consultar **se dice**. Un servicio que no "
        "responde y desaparece de la lista deja una página que enseña margen de "
        "sobra precisamente cuando algo va mal."
    ),
)
async def slo_del_tenant(request: Request, principal: AutenticadoDep) -> Any:
    import asyncio
    from datetime import datetime, timezone

    from crmcore.config import get_settings

    if _cliente is None:
        raise NoDisponible("El gateway aún no ha arrancado", error_code="gateway.arrancando")

    cabeceras = proxy.cabeceras_de_identidad(
        principal, get_settings().secret_key.get_secret_value()
    )

    tier = "estandar"
    tier_conocido = False
    if "tenancy" in _destinos:
        try:
            respuesta = await _cliente.get(
                f"{_destinos['tenancy'].url_base}/api/v1/compromisos",
                headers=cabeceras,
                timeout=5.0,
            )
            if respuesta.status_code == 200:
                tier = str(respuesta.json().get("tier") or "estandar")
                tier_conocido = True
        except Exception:  # noqa: BLE001 — sin tier se aplica el estándar y se dice
            tier_conocido = False

    async def _preguntar(nombre: str) -> dict[str, Any]:
        try:
            respuesta = await _cliente.get(
                f"{_destinos[nombre].url_base}/api/v1/estado/slo",
                headers=cabeceras,
                params={"tier": tier},
                timeout=5.0,
            )
            if respuesta.status_code != 200:
                raise RuntimeError(f"respondió {respuesta.status_code}")
            return {"servicio": nombre, **respuesta.json()}
        except Exception:  # noqa: BLE001 — un servicio que no contesta es información
            return {
                "servicio": nombre,
                "medible": False,
                "motivo": "El servicio no ha respondido a la consulta de SLO",
            }

    presupuestos = await asyncio.gather(*(_preguntar(n) for n in sorted(_destinos)))
    medibles = [p for p in presupuestos if p.get("medible")]
    agotados = [p["servicio"] for p in medibles if p.get("agotado")]
    sin_respuesta = [p["servicio"] for p in presupuestos if not p.get("medible")]

    return {
        "tier": tier,
        # Que el tier salga por defecto no es lo mismo que que sea el contratado,
        # y la diferencia cambia el objetivo que se está aplicando.
        "tier_confirmado": tier_conocido,
        "consultado_at": datetime.now(timezone.utc).isoformat(),
        "servicios": presupuestos,
        "servicios_medibles": len(medibles),
        "sin_medicion": sin_respuesta,
        "presupuesto_agotado_en": agotados,
        "se_puede_desplegar": not agotados,
        "que_significa": (
            f"Presupuesto agotado en {', '.join(agotados)}: toca parar de añadir y "
            "arreglar lo que falla"
            if agotados
            else "Queda margen en todos los servicios medibles: se puede seguir desplegando"
        ),
    }


@router.get(
    "/estado/contratos",
    summary="Contratos de evento de toda la instalación",
    description=(
        "Contract testing interno dirigido por el consumidor "
        "(CRM-00.03.01.03): junta lo que publica cada servicio sobre los "
        "contratos de evento que consume.\n\n"
        "Se junta aquí porque un contrato tiene dos lados en dos servicios "
        "distintos: mirarlo servicio a servicio enseña la mitad de cada uno y "
        "no deja ver lo único que importa, que es si lo que uno promete lo "
        "cumple para quien depende de ello."
    ),
)
async def contratos_de_la_instalacion(principal: AutenticadoDep) -> Any:
    import asyncio

    from crmcore.config import get_settings

    if _cliente is None:
        raise NoDisponible("El gateway aún no ha arrancado", error_code="gateway.arrancando")

    cabeceras = proxy.cabeceras_de_identidad(
        principal, get_settings().secret_key.get_secret_value()
    )

    async def _preguntar(nombre: str) -> dict[str, Any]:
        try:
            respuesta = await _cliente.get(
                f"{_destinos[nombre].url_base}/api/v1/estado/contratos",
                headers=cabeceras,
                timeout=5.0,
            )
            if respuesta.status_code != 200:
                raise RuntimeError(f"respondió {respuesta.status_code}")
            return dict(respuesta.json())
        except Exception:  # noqa: BLE001 — un servicio mudo es información
            # Un servicio que no contesta NO cuenta como «en verde»: contarlo
            # así daría por verificado un contrato que nadie ha comprobado, que
            # es exactamente lo que este gate existe para impedir.
            return {"servicio": nombre, "medible": False, "en_verde": False}

    partes = await asyncio.gather(*(_preguntar(n) for n in sorted(_destinos)))
    incumplimientos = [i for p in partes for i in p.get("incumplimientos", [])]
    return {
        "en_verde": not incumplimientos and all(p.get("medible", True) for p in partes),
        "incumplimientos": incumplimientos,
        "servicios": partes,
        "sin_respuesta": [p["servicio"] for p in partes if not p.get("medible", True)],
    }


@router.get(
    "/estado/ui-referencia",
    summary="Si la instalación necesita la interfaz de referencia",
    description=(
        "«Somos headless y la interfaz es opcional» (CRM-00.02.03.02) no se "
        "erosiona de golpe: se erosiona con una redirección cada vez. Esto lo "
        "mide en **todos** los servicios y junta los hallazgos.\n\n"
        "Un servicio que no contesta NO cuenta como independiente: contarlo así "
        "daría por comprobado lo que nadie ha mirado, que es justo lo que esto "
        "existe para impedir."
    ),
)
async def ui_de_referencia_de_la_instalacion(principal: AutenticadoDep) -> Any:
    import asyncio

    from crmcore.config import get_settings
    from crmcore.http.ui_opcional import estado_de_la_ui

    if _cliente is None:
        raise NoDisponible("El gateway aún no ha arrancado", error_code="gateway.arrancando")

    s = get_settings()
    cabeceras = proxy.cabeceras_de_identidad(principal, s.secret_key.get_secret_value())

    async def _preguntar(nombre: str) -> dict[str, Any]:
        try:
            respuesta = await _cliente.get(
                f"{_destinos[nombre].url_base}/api/v1/estado/ui-referencia",
                headers=cabeceras,
                timeout=5.0,
            )
            if respuesta.status_code != 200:
                raise RuntimeError(f"respondió {respuesta.status_code}")
            return dict(respuesta.json())
        except Exception:  # noqa: BLE001 — un servicio mudo es información
            return {
                "servicio": nombre,
                "independiente": False,
                "hallazgos": [
                    {
                        "donde": nombre,
                        "que": "el servicio no contesta",
                        "consecuencia": (
                            "no se puede afirmar que sea independiente de la interfaz, "
                            "y darlo por bueno sería declarar comprobado lo que nadie "
                            "ha mirado"
                        ),
                    }
                ],
            }

    partes = await asyncio.gather(*(_preguntar(n) for n in sorted(_destinos)))
    hallazgos = [h for p in partes for h in p.get("hallazgos", [])]
    return {
        "independiente": not hallazgos,
        "hallazgos": hallazgos,
        "servicios": partes,
        "la_interfaz": estado_de_la_ui(settings=s),
    }


@router.get(
    "/estado/presion",
    summary="Qué se está aplazando en la instalación y por qué",
    description=(
        "La presión de un solo servicio no dice nada: lo que se aplaza depende "
        "del que esté peor. Aquí se juntan las de todos (CRM-08.01.01.06).\n\n"
        "Un servicio que no contesta **no cuenta como tranquilo**: se dice que no "
        "se sabe, que es distinto."
    ),
)
async def presion_de_la_instalacion(principal: AutenticadoDep) -> Any:
    import asyncio

    from crmcore.config import get_settings

    if _cliente is None:
        raise NoDisponible("El gateway aún no ha arrancado", error_code="gateway.arrancando")

    cabeceras = proxy.cabeceras_de_identidad(
        principal, get_settings().secret_key.get_secret_value()
    )

    async def _preguntar(nombre: str) -> dict[str, Any]:
        try:
            respuesta = await _cliente.get(
                f"{_destinos[nombre].url_base}/api/v1/estado/presion",
                headers=cabeceras,
                timeout=5.0,
            )
            if respuesta.status_code != 200:
                raise RuntimeError(f"respondió {respuesta.status_code}")
            return dict(respuesta.json())
        except Exception:  # noqa: BLE001 — un servicio mudo es información
            return {"servicio": nombre, "medible": False, "presion": None}

    partes = await asyncio.gather(*(_preguntar(n) for n in sorted(_destinos)))
    medibles = [p for p in partes if p.get("presion") is not None]
    peor = max(medibles, key=lambda p: p["presion"], default=None)
    mudos = [p["servicio"] for p in partes if p.get("presion") is None]

    return {
        "peor": peor,
        "servicios": partes,
        "sin_respuesta": mudos,
        "que_significa": (
            "No ha contestado ningún servicio: no se puede decir que todo esté "
            "tranquilo, se puede decir que no se sabe."
            if not medibles
            else (peor or {}).get("que_significa", "")
        ),
        "aviso": (
            ""
            if not mudos
            else f"{len(mudos)} servicios no contestan. Un servicio mudo no cuenta como "
            "tranquilo: es justo el que suele estar peor."
        ),
    }


class SoloLecturaIn(BaseModel):
    activo: bool
    motivo: str = Field(
        "",
        description=(
            "Qué está pasando, en una frase que se le pueda enseñar a quien no "
            "puede guardar. Obligatorio al entrar"
        ),
    )


@router.post(
    "/estado/solo-lectura",
    summary="Poner la instalación entera en solo lectura, o sacarla",
    description=(
        "**Va por aquí y no a un servicio suelto**, y es el punto: el modo vive "
        "en memoria de cada proceso, así que ponerlo en uno dejaría los otros "
        "trece escribiendo. Un modo degradado a medias es peor que ninguno — la "
        "mitad de las operaciones guardan y la otra mitad no, y lo que queda "
        "después es un estado que nadie sabe reconstruir.\n\n"
        "Se dice **a cuáles ha llegado y a cuáles no**: un servicio que no "
        "contesta sigue escribiendo, y eso hay que saberlo ahora, no después.\n\n"
        "La lectura sigue funcionando en todos. Es lo que separa «no se puede "
        "guardar, tus datos están ahí» de «el CRM no funciona»."
    ),
)
async def solo_lectura_de_la_instalacion(datos: SoloLecturaIn, principal: PlataformaDep) -> Any:
    import asyncio

    from crmcore.config import get_settings

    if _cliente is None:
        raise NoDisponible("El gateway aún no ha arrancado", error_code="gateway.arrancando")
    if datos.activo and not datos.motivo.strip():
        raise ErrorValidacion(
            "Entrar en modo solo lectura exige decir por qué: es lo que se le "
            "enseña a quien no puede guardar.",
            error_code="resiliencia.solo_lectura_sin_motivo",
        )

    cabeceras = proxy.cabeceras_de_identidad(
        principal, get_settings().secret_key.get_secret_value()
    )

    async def _avisar(nombre: str) -> dict[str, Any]:
        try:
            respuesta = await _cliente.post(
                f"{_destinos[nombre].url_base}/api/v1/estado/solo-lectura",
                json=datos.model_dump(),
                headers=cabeceras,
                timeout=5.0,
            )
            if respuesta.status_code != 200:
                raise RuntimeError(f"respondió {respuesta.status_code}")
            return {"servicio": nombre, "aplicado": True}
        except Exception as exc:  # noqa: BLE001 — un servicio mudo es información
            return {"servicio": nombre, "aplicado": False, "error": str(exc)[:200]}

    partes = await asyncio.gather(*(_avisar(n) for n in sorted(_destinos)))
    sin_aplicar = [p["servicio"] for p in partes if not p["aplicado"]]
    return {
        "activo": datos.activo,
        "motivo": datos.motivo,
        "servicios": partes,
        "sin_aplicar": sin_aplicar,
        "completo": not sin_aplicar,
        "aviso": (
            ""
            if not sin_aplicar
            else f"{len(sin_aplicar)} servicios no lo han aplicado y siguen "
            "escribiendo. Un modo degradado a medias deja un estado que nadie "
            "sabe reconstruir después."
        ),
    }


# ── Lo que necesita quien integra, antes de escribir una línea ────────────
#
# `sdk.plan_de_generacion` y `sdk.contrato_de_componente` estaban escritas,
# probadas y **sin que las alcanzara ninguna ruta**: el producto sabía decir qué
# se genera del contrato y qué hay que escribir a mano en cada lenguaje, y qué
# promete un componente embebible, y no lo decía en ninguna parte. Quien
# integraba tenía que preguntarlo por correo.
#
# Van en el gateway porque son del CRM entero, no de un servicio: el SDK se
# genera del contrato que publica el gateway, y un componente embebible habla
# con la API pública, no con `party` ni con `sales`.


@router.get(
    "/estado/consultas-degradadas",
    summary="Qué consultas se han vuelto lentas, en toda la instalación",
    description=(
        "Comparadas **consigo mismas**, no con un umbral: una consulta que "
        "siempre tardó 800 ms no es un problema nuevo, y una que pasó de 20 a 90 "
        "sí lo es aunque siga por debajo de cualquier umbral. Un umbral fijo caza "
        "las lentas de siempre y se pierde las que se acaban de torcer, que son "
        "las que tienen arreglo.\n\n"
        "Se juntan las de **todos** los servicios: cada uno mide las suyas en su "
        "propio proceso, y mirar sólo las de uno es mirar por la ventana que se "
        "tiene a mano.\n\n"
        "Un servicio que no contesta **no cuenta como sano**: se dice que no se "
        "sabe, que es distinto."
    ),
)
async def consultas_degradadas_de_la_instalacion(principal: AutenticadoDep) -> Any:
    import asyncio

    from crmcore.config import get_settings

    if _cliente is None:
        raise NoDisponible("El gateway aún no ha arrancado", error_code="gateway.arrancando")

    cabeceras = proxy.cabeceras_de_identidad(
        principal, get_settings().secret_key.get_secret_value()
    )

    async def _preguntar(nombre: str) -> dict[str, Any]:
        try:
            respuesta = await _cliente.get(
                f"{_destinos[nombre].url_base}/api/v1/estado/consultas-degradadas",
                headers=cabeceras,
                timeout=5.0,
            )
            if respuesta.status_code != 200:
                raise RuntimeError(f"respondió {respuesta.status_code}")
            return {"servicio": nombre, **dict(respuesta.json())}
        except Exception:  # noqa: BLE001 — un servicio mudo es información
            return {"servicio": nombre, "legible": False}

    partes = await asyncio.gather(*(_preguntar(n) for n in sorted(_destinos)))
    mudos = [p["servicio"] for p in partes if p.get("legible") is False]
    return {
        "servicios": partes,
        "sin_respuesta": mudos,
        "aviso": (
            ""
            if not mudos
            else f"{len(mudos)} servicios no contestan. Un servicio mudo no cuenta "
            "como sano: suele ser justo el que peor va."
        ),
    }


# ── Lo que hace falta antes de desplegar o de escalar ─────────────────────
#
# Ocho decisiones de observabilidad estaban escritas, probadas y sin que las
# alcanzara ninguna ruta. Son las que se consultan cuando algo va mal o cuando
# hay que crecer, y entonces nadie se pone a leer código.
#
# Van en el gateway y no en cada servicio porque son del **despliegue entero**:
# dónde conviene escalar, si una migración se puede deshacer, si el reparto por
# zonas aguanta perder una. Repartidas por los catorce darían catorce respuestas
# a la misma pregunta, y la que se mire será la del servicio que se tenga a mano.


class EscaladoIn(BaseModel):
    servicios: list[dict[str, Any]] = Field(default_factory=list)


class ReplicasIn(BaseModel):
    servicio: str
    limite: str = Field(..., examples=["conexiones_bd"])
    capacidad_del_limite: int = Field(..., ge=1)
    consumo_por_replica: int = Field(..., ge=1)
    replicas_actuales: int = Field(..., ge=0)


class ReplicableIn(BaseModel):
    servicio: str
    declaracion: dict[str, Any] = Field(default_factory=dict)


class DespliegueIn(BaseModel):
    estrategia: str = Field(..., examples=["canario"])
    puede_volver_atras_en_min: int | None = None
    migracion_compatible_hacia_atras: bool = True
    porcentaje_canario: int = Field(0, ge=0, le=100)


class AbortarIn(BaseModel):
    metricas: dict[str, Any] = Field(default_factory=dict)
    base: dict[str, Any] = Field(default_factory=dict)


class ZonasIn(BaseModel):
    zonas: list[dict[str, Any]] = Field(default_factory=list)
    ultimo_simulacro: datetime | None = None


class CatalogoIn(BaseModel):
    servicios: dict[str, dict[str, Any]] = Field(default_factory=dict)


@router.post(
    "/escalado/donde",
    summary="Qué servicio conviene escalar, y por qué",
)
def donde_escalar(cuerpo: EscaladoIn, principal: PlataformaDep) -> Any:
    from crmcore.obs.escalado import donde_escalar as calcular

    return calcular(servicios=cuerpo.servicios)


@router.post(
    "/escalado/replicas",
    summary="Cuántas réplicas sirven de algo antes de topar con el límite",
    description=(
        "Añadir réplicas por encima del límite que las estrangula **no "
        "acelera nada**: lo que hace es consumir más del recurso que ya está "
        "al tope —conexiones de base, cuota del proveedor— y empeorarlo para "
        "las que ya había."
    ),
)
def replicas_utiles(cuerpo: ReplicasIn, principal: PlataformaDep) -> Any:
    from crmcore.obs.escalado import replicas_utiles as calcular

    return calcular(**cuerpo.model_dump())


@router.post(
    "/escalado/replicable",
    summary="Si este servicio se puede replicar de verdad",
)
def comprobar_replicable(cuerpo: ReplicableIn, principal: PlataformaDep) -> Any:
    from crmcore.obs.escalado import comprobar_replicable as comprobar

    return comprobar(servicio=cuerpo.servicio, declaracion=cuerpo.declaracion)


@router.post(
    "/despliegue/comprobar",
    summary="Si este despliegue se puede deshacer, y en cuánto",
    description=(
        "**La vuelta atrás es la pregunta, no el despliegue.** Un despliegue "
        "que no se puede deshacer en minutos obliga a arreglar hacia delante "
        "con el sistema caído, que es cuando peor se decide. Y una migración "
        "que no es compatible hacia atrás convierte el «volvemos a la "
        "anterior» en «no se puede»."
    ),
)
def comprobar_despliegue(cuerpo: DespliegueIn, principal: PlataformaDep) -> Any:
    from crmcore.obs.topologia import comprobar_despliegue as comprobar

    return comprobar(**cuerpo.model_dump())


@router.post(
    "/despliegue/abortar",
    summary="Si lo que se está midiendo pide abortar el despliegue",
    description=(
        "Declararlo **antes** de empezar es lo que lo hace servir: a mitad de "
        "un despliegue que va mal, la discusión sobre si abortar la gana "
        "siempre quien tiene más ganas de que funcione."
    ),
)
def senales_para_abortar(cuerpo: AbortarIn, principal: PlataformaDep) -> Any:
    from crmcore.obs.topologia import senales_para_abortar as comprobar

    return comprobar(metricas=cuerpo.metricas, base=cuerpo.base)


@router.get(
    "/despliegue/reintento",
    summary="Si esta operación se puede reintentar sin duplicar nada",
    description=(
        "Reintentar un `POST` no idempotente crea el registro dos veces. Es "
        "la decisión que toma una pasarela o un cliente, y tenerla escrita en "
        "un solo sitio evita que cada uno la resuelva a su manera."
    ),
)
def politica_de_reintento(
    principal: AutenticadoDep, metodo: str = "POST", idempotente: bool = False
) -> Any:
    from crmcore.obs.topologia import politica_de_reintento as politica

    return politica(metodo=metodo, idempotente=idempotente)


@router.post(
    "/multi-zona",
    summary="Si el reparto por zonas aguanta perder una",
    description=(
        "Con el **último simulacro** dentro: un plan multi-zona que no se ha "
        "probado nunca es un diagrama. El día que se cae una zona se descubre "
        "lo que faltaba, y ese día no hay tiempo."
    ),
)
def plan_multi_zona(cuerpo: ZonasIn, principal: PlataformaDep) -> Any:
    from crmcore.obs.topologia import plan_multi_zona as plan

    return plan(zonas=cuerpo.zonas, ultimo_simulacro=cuerpo.ultimo_simulacro)


@router.post(
    "/topologia/validar",
    summary="Si el catálogo de servicios se sostiene",
)
def validar_catalogo(cuerpo: CatalogoIn, principal: PlataformaDep) -> Any:
    from crmcore.obs.topologia import validar_catalogo as validar

    return validar(servicios=cuerpo.servicios)


@router.get(
    "/sdk/plan",
    summary="Qué se genera del contrato y qué hay que escribir a mano",
    description=(
        "**Un SDK escrito a mano se queda viejo. Siempre.** Alguien lo escribe "
        "con cariño para tres lenguajes y a los cuatro meses la API tiene dos "
        "endpoints que el SDK no conoce — y el integrador no se entera de que "
        "existen. Por eso se genera del contrato.\n\n"
        "Y por eso esta ruta dice también **lo que no se genera**, que es lo que "
        "cuesta de verdad: el reintento con espera creciente, la paginación "
        "resuelta en un iterador y los errores del producto como excepciones con "
        "nombre. Devolver sólo la lista de lenguajes haría creer que el SDK está "
        "hecho cuando lo que hay es un cliente HTTP con los nombres de los "
        "endpoints."
    ),
)
def plan_del_sdk(
    principal: AutenticadoDep,
    lenguajes: str = Query(
        "",
        description="Separados por comas. Vacío: todos los que se mantienen",
    ),
) -> Any:
    from crmcore import sdk
    from crmcore.config import get_settings

    pedidos = [x.strip() for x in lenguajes.split(",") if x.strip()] or list(sdk.LENGUAJES)
    return sdk.plan_de_generacion(
        lenguajes=pedidos, version_api=str(get_settings().api_prefix).strip("/") or "v1"
    )


@router.get(
    "/sdk/componentes",
    summary="Los componentes embebibles y qué promete cada uno",
    description=(
        "Un componente que se incrusta en la web de un cliente **no se puede "
        "cambiar a la ligera**: su contrato es tan público como el de la API, y "
        "romperlo rompe una página que no es nuestra — y se entera él antes que "
        "nosotros.\n\n"
        "Lleva dentro la parte que casi siempre se olvida: **con qué identidad "
        "habla**. Un componente que usa la sesión del CRM en una web pública deja "
        "entrar a quien pase por ahí; basta con abrir las herramientas del "
        "navegador."
    ),
)
def componentes_embebibles(principal: AutenticadoDep, nombre: str = Query("")) -> Any:
    from crmcore import sdk

    if nombre:
        return sdk.contrato_de_componente(nombre)
    return {
        "componentes": [sdk.contrato_de_componente(c) for c in sdk.COMPONENTES],
    }


@router.get(
    "/superficie",
    summary="Todo lo que sabe hacer el CRM, en una lista",
    description=(
        "Junta la superficie de **todos** los servicios: cada operación con su "
        "método, su ruta pública, el permiso que exige y si es de "
        "administración.\n\n"
        "Es lo que hace comprobable la promesa de que la consola de "
        "administración está replicada al 100 % por API (CRM-07.01.01.01): la "
        "consola se construye leyendo esto, así que no puede existir una acción "
        "de consola que no sea una llamada de esta lista.\n\n"
        "Se agrega aquí y no se pide servicio a servicio porque quien la "
        "consume es un cliente de fuera, que no conoce —ni debe conocer— cómo "
        "está repartido el sistema por dentro."
    ),
)
async def superficie_completa(_: AutenticadoDep) -> Any:
    import asyncio
    from datetime import datetime, timezone

    if _cliente is None:
        raise NoDisponible("El gateway aún no ha arrancado", error_code="gateway.arrancando")

    async def _preguntar(nombre: str) -> dict[str, Any]:
        try:
            respuesta = await _cliente.get(
                f"{_destinos[nombre].url_base}/api/v1/superficie", timeout=5.0
            )
            if respuesta.status_code != 200:
                raise RuntimeError(f"respondió {respuesta.status_code}")
            return respuesta.json()
        except Exception:  # noqa: BLE001 — un servicio caído es información
            # Se devuelve el hueco en vez de omitirlo: una superficie a la que
            # le falta un servicio sin decirlo haría que la consola escondiera
            # media administración como si no existiera.
            return {"servicio": nombre, "alcanzable": False, "operaciones": []}

    partes = await asyncio.gather(*(_preguntar(n) for n in sorted(_destinos)))

    operaciones: list[dict[str, Any]] = []
    incompletos: list[str] = []
    for parte in partes:
        if parte.get("alcanzable") is False:
            incompletos.append(str(parte.get("servicio")))
            continue
        for operacion in parte.get("operaciones", []):
            operaciones.append({**operacion, "servicio": parte.get("servicio")})
    operaciones.sort(key=lambda o: (o["ruta"], o["metodo"]))

    return {
        "consultado_at": datetime.now(timezone.utc).isoformat(),
        "servicios": sorted(_destinos),
        # Nombrar a quien no contesta es la diferencia entre una lista corta y
        # una lista corta que se sabe corta.
        "servicios_sin_contestar": incompletos,
        "completa": not incompletos,
        "total": len(operaciones),
        "administracion": sum(1 for o in operaciones if o.get("administracion")),
        "operaciones": operaciones,
        # Qué objetos admiten adjuntos, comentarios y documentos.
        #
        # Estas tres rutas son `/adjuntos/{objeto}`, así que en la lista de
        # operaciones aparecen una sola vez y con el objeto sin resolver: quien
        # la lee no puede saber a cuáles se aplican. El front pedía las tres
        # para **cualquier** ficha y recibía 404 en 81 de 85 — tres peticiones
        # fallidas por ficha abierta, y tres pestañas que no podían funcionar.
        #
        # Es el gateway quien lo sabe, porque es quien enruta por objeto.
        "objetos": {
            "adjuntos": sorted(rutas.OBJETOS_ADJUNTO),
            "comentarios": sorted(rutas.OBJETOS_COMENTARIO),
            "documentos": sorted(rutas.OBJETOS_DOCUMENTO),
        },
    }


@router_proxy.api_route(
    "/api/{ruta:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
    summary="Proxy a los servicios",
    description=(
        "Toda la API pública pasa por aquí. El gateway resuelve el tenant, "
        "autentica, aplica los límites y reenvía con la identidad firmada."
    ),
    include_in_schema=False,
)
async def proxy_api(ruta: str, request: Request, principal: PrincipalDep) -> Response:
    if _cliente is None:
        raise NoDisponible("El gateway aún no ha arrancado", error_code="gateway.arrancando")

    # Una cookie de sesión que ya no vale se responde AQUÍ, y con su motivo.
    #
    # `contexto_autenticado` no la tumba a propósito —si lo hiciera, la cookie
    # caducada impediría volver a entrar, porque la idempotencia pide el
    # principal en toda escritura, también en la de entrar—. Pero lo que se
    # proxia no es entrar: es la API, y llamarla con una sesión expirada tiene
    # que decir que expiró. Sin esto llegaba al servicio de destino como una
    # llamada anónima y volvía un «hace falta autenticarse» genérico, con el que
    # el navegador no sabe si le toca renovar o mandar a la pantalla de entrada.
    rechazada = cookie_rechazada()
    if rechazada is not None and f"/api/{ruta}" not in rutas.RUTAS_DE_SESION:
        raise rechazada

    ruta_completa = f"/api/{ruta}"
    nombre = rutas.servicio_de(ruta_completa)
    if nombre is None:
        raise NoEncontrado(
            "No hay ninguna ruta de la API que corresponda",
            error_code="gateway.ruta_desconocida",
        )
    destino = _destinos.get(nombre)
    if destino is None:
        # 503 y no 404: la ruta existe, lo que falta es el servicio. Un 404 haría
        # pensar que la llamada está mal escrita.
        raise NoDisponible(
            f"El servicio «{nombre}» no está desplegado en esta instalación",
            error_code="gateway.servicio_no_desplegado",
            detalle={"servicio": nombre},
        )

    # ¿PUEDE ESTE TENANT OPERAR? Aquí y no en cada servicio: es el único paso
    # obligado de toda la API pública, y repetir la comprobación trece veces
    # garantiza que a la catorceava se olvide.
    #
    # Esto no existía. La comprobación estaba escrita en `tenancy` desde el
    # principio —con una documentación que decía «lo llama el gateway en cada
    # petición»— y no la llamaba nadie: un tenant suspendido creaba cuentas.
    destino_tenancy = _destinos.get("tenancy")
    if destino_tenancy is not None:
        await operatividad.exigir(
            _cliente,
            destino_tenancy.url_base,
            getattr(principal, "tenant_id", None),
            request.method,
        )
        # Y si el plan incluye este módulo. Va DESPUÉS de la operatividad y con
        # el mismo dato cacheado: un tenant suspendido tiene que enterarse de que
        # está suspendido, no de que no ha contratado marketing.
        await operatividad.exigir_capacidad(
            _cliente,
            destino_tenancy.url_base,
            getattr(principal, "tenant_id", None),
            nombre,
        )

    # ACCESO CONTEXTUAL (CRM-00.05.01.09): desde dónde entra, con qué y a qué
    # hora. El ABAC ya decide por atributos del usuario y del registro; esto
    # añade los del **momento**, que son los que cambian entre una sesión
    # legítima y la misma credencial usada por otro.
    #
    # Se comprueba **en cada petición y no al entrar**: comprobarlo solo en el
    # login deja la sesión abierta cuando las condiciones dejan de cumplirse, y
    # el caso que se quiere cubrir es exactamente ese. El módulo que lo evalúa
    # llevaba desde que se escribió sin que lo importara nadie.
    reglas = operatividad.reglas_contextuales(getattr(principal, "tenant_id", None))
    if reglas:
        from datetime import datetime, timezone

        from crmcore.authz import contexto as ctx_mod

        ctx_mod.exigir(
            [ctx_mod.ReglaContextual(**r) for r in reglas],
            ctx_mod.Contexto(
                ip=ip_de(request),
                dispositivo=request.headers.get("x-crm-dispositivo", ""),
                # El país no se adivina: si no llega, la regla que dependa de él
                # no aplica. Una señal ausente no es una señal incumplida —
                # bloquear por una IP que no llega porque hay un proxy delante
                # deja fuera a toda la plantilla, y eso es una caída.
                pais=request.headers.get("x-crm-pais", ""),
                momento=datetime.now(timezone.utc),
            ),
        )

    # TRÁFICO ANÓMALO (CRM-00.01.06.05). El límite de tasa fijo protege del
    # abuso y no protege de lo que de verdad tumba un multi-tenant: **un cliente
    # que hace lo de siempre, pero diez veces más**. Su importación nocturna se
    # vuelve diurna, o alguien monta un bucle en su integración, y el resto
    # empieza a esperar sin que nadie haya pasado ningún límite.
    #
    # El módulo que lo mide y lo frena estaba escrito, probado y **no lo
    # importaba nadie**, así que nada de esto ocurría. Va aquí porque este es el
    # único paso obligado de toda la API pública.
    tenant = getattr(principal, "tenant_id", None)
    if tenant is not None:
        anomalias.anotar(tenant, 1)
        freno = anomalias.estado(tenant)
        if freno["frenado"]:
            raise LimiteExcedido(
                freno.get("motivo") or "Estás haciendo muchas más peticiones de lo habitual.",
                error_code="gateway.tenant_frenado",
                detalle=freno,
            )
        veredicto = anomalias.evaluar(tenant)
        if veredicto["anomalo"]:
            # Se frena y **se deja pasar esta**: cortar la petición que destapa
            # la anomalía castiga a quien la hizo por llegar primero. La
            # siguiente ya encuentra el freno puesto.
            anomalias.frenar(tenant, motivo=veredicto["porque"])

    s = get_settings()
    respuesta = await proxy.reenviar(
        _cliente,
        url_base=destino.url_base,
        metodo=request.method,
        ruta=ruta_completa,
        query=str(request.url.query or ""),
        cabeceras=dict(request.headers),
        cuerpo=await request.body(),
        identidad=proxy.cabeceras_de_identidad(principal, s.secret_key.get_secret_value()),
        timeout_s=s.http_interno_timeout_s,
    )
    # Un flujo se devuelve COMO FLUJO. Leer `respuesta.content` de una respuesta
    # abierta en streaming la esperaría entera —que en un `text/event-stream` es
    # para siempre— y además rompería lo único que hace útil un flujo: que lo
    # que pasa ahora se vea ahora.
    if respuesta.headers.get("content-type", "").startswith("text/event-stream"):
        return StreamingResponse(
            respuesta.aiter_raw(),
            status_code=respuesta.status_code,
            media_type="text/event-stream",
            # Sin buffering intermedio: nginx acumula por defecto y un evento se
            # quedaría esperando a que se llene el buffer.
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            background=BackgroundTask(respuesta.aclose),
        )

    # La respuesta del servicio se devuelve tal cual, incluidos su código y sus
    # cabeceras de contrato: el gateway no reinterpreta lo que dice el servicio.
    return Response(
        content=respuesta.content,
        status_code=respuesta.status_code,
        headers={
            k: v
            for k, v in respuesta.headers.items()
            if k.lower() not in ("content-length", "transfer-encoding", "connection")
        },
        media_type=respuesta.headers.get("content-type"),
    )


# **El proxy no puede declarar lo que no conoce** (CRM-00.02.04.01).
#
# La comprobación de parámetros desconocidos es una dependencia GLOBAL de cada
# aplicación, y eso incluye a este catch-all. Como aquí no hay más parámetro
# declarado que el camino, el guardián rechazaba CUALQUIER parámetro de
# consulta que pasara por el gateway —que es por donde pasa todo— con un «esta
# operación no mira «limite»» y una lista de admitidos de tres elementos.
#
# Lo veía cualquiera que abriera el tablero de ventas: pide doscientas
# oportunidades, y la pantalla salía entera en rojo. Lo contó quien lo usaba.
#
# La comprobación no desaparece: la hace **el servicio de destino**, que sí
# sabe qué mira cada una de sus rutas. Aquí sería imposible por construcción —
# tendría que conocer las dos mil quinientas operaciones de los trece
# servicios— y fingir que la hace es peor que no hacerla.
admite_parametros_abiertos(
    proxy_api,
    "es el proxy de toda la API: los parámetros los declara y los comprueba la "
    "ruta de destino, que es la única que sabe cuáles mira",
)


@router.get(
    "/buscar",
    summary="Buscar en todo el CRM",
    description=(
        "Pregunta a cada servicio por su índice y junta los resultados por "
        "relevancia. La búsqueda global se compone aquí y no en un índice "
        "compartido: así ningún servicio necesita leer el esquema de otro, y el "
        "aislamiento de cada índice sigue siendo el mismo que el de sus datos.\n\n"
        "Un servicio que no responda **no hace fallar la búsqueda**: se devuelve "
        "lo que haya y se dice cuáles faltan. Media respuesta útil vale más que "
        "un error, y ocultar que falta la mitad sería peor que las dos cosas."
    ),
)
async def buscar_global(
    peticion: Request,
    principal: AutenticadoDep,
    q: str = Query(..., min_length=1, max_length=300),
    limite: int = Query(20, ge=1, le=100),
) -> Any:
    """Reparte la consulta entre los servicios que tienen índice."""
    import asyncio

    if _cliente is None:
        raise NoDisponible("El gateway aún no ha arrancado", error_code="gateway.arrancando")

    # Los servicios con índice. Se declara la lista en vez de preguntar a todos:
    # el gateway ya sabe quién tiene búsqueda, y llamar a los diez para que
    # siete devuelvan 404 multiplica por tres el tiempo de cada consulta.
    con_indice = [s for s in ("party", "sales") if s in _destinos]

    cabeceras = {
        k: v
        for k, v in peticion.headers.items()
        if k.lower().startswith("x-") or k.lower() == "authorization"
    }

    async def _preguntar(servicio: str) -> tuple[str, list[dict[str, Any]] | None]:
        destino = _destinos[servicio]
        try:
            respuesta = await _cliente.get(
                f"{destino.url_base}/api/v1/buscar",
                params={"q": q, "limite": limite},
                headers=cabeceras,
                timeout=5.0,
            )
            if respuesta.status_code != 200:
                return servicio, None
            return servicio, list(respuesta.json().get("resultados") or [])
        except Exception:  # noqa: BLE001 — un servicio caído no puede tumbar la búsqueda
            return servicio, None

    respuestas = await asyncio.gather(*(_preguntar(s) for s in con_indice))

    resultados: list[dict[str, Any]] = []
    fallidos: list[str] = []
    for servicio, filas in respuestas:
        if filas is None:
            fallidos.append(servicio)
            continue
        for fila in filas:
            resultados.append({**fila, "servicio": servicio})

    resultados.sort(key=lambda r: float(r.get("relevancia") or 0), reverse=True)
    if fallidos:
        logger.warning("gateway.busqueda_parcial", servicios_caidos=fallidos)
    return {
        "consulta": q,
        "total": len(resultados[:limite]),
        "resultados": resultados[:limite],
        # Se dice siempre, aunque esté vacío: quien lo consume tiene que poder
        # distinguir «no hay resultados» de «no hemos podido preguntar».
        "servicios_sin_responder": fallidos,
    }


def _piezas() -> tuple[Any, dict[str, rutas.Destino], float]:
    """El cliente, los destinos y el plazo, resueltos al llamar y no al montar."""
    if _cliente is None:
        raise NoDisponible("El gateway aún no ha arrancado", error_code="gateway.arrancando")
    return _cliente, _destinos, get_settings().http_interno_timeout_s


# ── Superficie para integradores (CRM-00.02.01.02, .15, CRM-00.02.03.03,
# CRM-00.02.04.03, .06, CRM-00.04.02.04) ──────────────────────────────────
#
# Todo lo de aquí estaba escrito, probado y sin que lo importara nadie: la
# lectura compuesta, el sandbox con datos sintéticos, el mTLS por integración,
# el panel del integrador y el endpoint con nombre del tenant. Seis funciones,
# cero puertas.


class ComposicionIn(BaseModel):
    nombre: str = Field(..., min_length=1)
    partes: list[dict[str, Any]] = Field(default_factory=list)
    perfil: str = Field("web", description="web · movil")


class SandboxIn(BaseModel):
    objetos: list[str] = Field(default_factory=list)
    filas_por_objeto: int = Field(25, ge=1, le=500)


class MtlsIn(BaseModel):
    huella_declarada: str = ""
    huella_presentada: str = ""
    obligatorio: bool = False


class PanelIn(BaseModel):
    clave: str = Field(..., min_length=1)
    llamadas: list[dict[str, Any]] = Field(default_factory=list)
    cuota_mes: int = Field(0, ge=0)
    scopes: list[str] = Field(default_factory=list)


class EndpointPropioIn(BaseModel):
    ruta: str = Field(..., min_length=1)
    composicion: str = Field(..., min_length=1)
    permiso: str = Field(..., min_length=1)


@router.post(
    "/integracion/composicion/validar",
    dependencies=[Depends(exige_permiso("integracion:read"))],
    summary="Comprobar una lectura compuesta antes de ejecutarla",
    description=(
        "**Los permisos se comprueban parte a parte.** Una composición no puede "
        "enseñar lo que sus partes no enseñarían: si alguien puede leer cuentas "
        "y no oportunidades, la composición no le trae las oportunidades — y eso "
        "se decide aquí, no al pintarlo.\n\n"
        "Y tiene **coste**: una composición es tantas consultas como partes, "
        "así que se mide antes. Una pantalla que pide quince cosas en una "
        "llamada no es una llamada barata, es quince con menos viajes de red."
    ),
)
async def validar_composicion(cuerpo: ComposicionIn, principal: AutenticadoDep) -> Any:
    return superficie.validar_composicion(
        nombre=cuerpo.nombre,
        partes=cuerpo.partes,
        permisos_del_llamante=frozenset(principal.permisos),
        perfil=cuerpo.perfil,
    )


@router.post(
    "/integracion/sandbox",
    dependencies=[Depends(exige_permiso("integracion:write"))],
    summary="Un entorno de pruebas con datos sintéticos",
    description=(
        "**Generados y no copiados.** Copiar datos de producción a un entorno de "
        "pruebas es cómo se filtra una base de clientes entera por un sitio que "
        "no tiene las mismas protecciones, y es lo que hace todo el mundo porque "
        "es lo cómodo."
    ),
)
async def sandbox(cuerpo: SandboxIn, principal: AutenticadoDep) -> Any:
    return superficie.crear_sandbox(
        tenant_id=principal.tenant_id,
        objetos=cuerpo.objetos,
        filas_por_objeto=cuerpo.filas_por_objeto,
    )


@router.post(
    "/integracion/mtls",
    dependencies=[Depends(exige_permiso("integracion:read"))],
    summary="Comprobar el certificado de cliente de una integración",
    description=(
        "**Por integración y no globalmente.** Obligarlo a todos deja fuera a "
        "quien se integra con un script de cuatro líneas; no ofrecerlo deja sin "
        "nada a quien mueve dinero por esa API. Son dos clientes distintos y "
        "necesitan dos respuestas distintas."
    ),
)
async def mtls(cuerpo: MtlsIn, principal: AutenticadoDep) -> Any:
    superficie.exigir_mtls(
        huella_declarada=cuerpo.huella_declarada,
        huella_presentada=cuerpo.huella_presentada,
        obligatorio=cuerpo.obligatorio,
    )
    return {"valido": True}


@router.post(
    "/integracion/panel",
    dependencies=[Depends(exige_permiso("integracion:read"))],
    summary="Lo que ve un integrador de su propia clave",
    description=(
        "**Lo que de verdad pasó, no lo que el contrato promete.** Un portal que "
        "solo documenta es una web bonita que no resuelve la llamada de las tres "
        "de la mañana; lo que la resuelve es ver el último error, con su cuerpo "
        "y su hora."
    ),
)
async def panel_de_integrador(cuerpo: PanelIn, principal: AutenticadoDep) -> Any:
    return superficie.panel_de_integrador(
        clave=cuerpo.clave,
        llamadas=cuerpo.llamadas,
        cuota_mes=cuerpo.cuota_mes,
        scopes=cuerpo.scopes,
    )


@router.post(
    "/integracion/endpoint-propio",
    dependencies=[Depends(exige_permiso("integracion:write"))],
    summary="Un endpoint con nombre del tenant, sobre el mismo gateway",
    description=(
        "Es una **composición con nombre suyo**, no una puerta aparte: los "
        "permisos, los límites de tasa y la auditoría son los mismos. Si fuera "
        "una puerta aparte, sería la puerta por la que se salta todo lo "
        "anterior."
    ),
)
async def endpoint_propio(cuerpo: EndpointPropioIn, principal: AutenticadoDep) -> Any:
    return superficie.declarar_endpoint_propio(
        ruta=cuerpo.ruta,
        composicion=cuerpo.composicion,
        permiso=cuerpo.permiso,
        tenant_id=principal.tenant_id,
    )


# ── Empuje de eventos al cliente (CRM-00.02.02.10) ────────────────────────
#
# Los webhooks exigen que quien escucha tenga una dirección pública y estable, y
# eso deja fuera a media integración real: un navegador, una aplicación móvil,
# un servicio dentro de una red cerrada. Todos pueden **llamar** al CRM y
# ninguno puede recibir una llamada.
#
# El módulo que lo resuelve estaba escrito, probado y sin que lo importara
# nadie: la cola, el flujo reanudable, el aviso de hueco y el latido. Nada de
# eso ocurría.


@router.get(
    "/eventos/flujo",
    summary="Recibir eventos sin exponer un endpoint",
    description=(
        "Un flujo `text/event-stream` con lo que pasa en este tenant.\n\n"
        "**Reanudable**: con `desde` se retoma donde se cortó. Y si lo que se "
        "pide ya se ha caído de la cola, el primer mensaje lo **dice** en vez de "
        "ir directamente a lo nuevo: un cliente que cree haberlo recibido todo y "
        "no lo ha recibido toma decisiones sobre datos incompletos, y sabiendo "
        "que hay hueco puede recargar el estado entero.\n\n"
        "Lleva **latido** cada veinte segundos: sin él, un intermediario cierra "
        "el flujo por inactividad y el cliente cree que el servidor se ha caído."
    ),
)
async def flujo_de_eventos(principal: AutenticadoDep, desde: int = Query(0, ge=0)) -> Any:
    from fastapi.responses import StreamingResponse

    return StreamingResponse(
        empuje.flujo(principal.tenant_id, desde=desde),
        media_type="text/event-stream",
        # Sin esto, un proxy intermedio acumula la respuesta y el «tiempo real»
        # llega en bloques de treinta segundos.
        headers={"cache-control": "no-cache", "x-accel-buffering": "no"},
    )


@router.post(
    "/interno/empuje",
    # Firma interna y no permiso: la llama otro servicio, no una persona. Es más
    # cerrada que cualquier permiso — no la pasa un token de usuario.
    dependencies=[Depends(exige_firma_interna)],
    summary="Dejar un evento disponible para quien esté escuchando",
    description=(
        "La llama **otro servicio**, con la identidad firmada de siempre: el "
        "que ya recibe todos los eventos para repartirlos por webhook es el que "
        "sabe cuándo pasa algo, y el flujo vive aquí porque el gateway es la "
        "única puerta pública — que es justo el punto de esta capacidad.\n\n"
        "No está en el portal público: cuelga de `/interno`, que solo alcanza "
        "quien lleva la firma interna."
    ),
)
async def empujar_evento(request: Request, principal: AutenticadoDep) -> Any:
    from crmcore.http.cuerpo import cuerpo_json

    # Igual que la captura pública: leer el cuerpo crudo sin red convierte un
    # error de quien llama en un error del servidor.
    cuerpo = await cuerpo_json(request)
    tenant = principal.tenant_id or cuerpo.get("tenant_id")
    if tenant is None:
        raise ErrorValidacion(
            "El evento no dice de qué tenant es, así que no hay a quién " "empujárselo.",
            error_code="empuje.sin_tenant",
        )
    from uuid import UUID as _UUID

    identificador = empuje.publicar(
        tenant if isinstance(tenant, _UUID) else _UUID(str(tenant)), dict(cuerpo)
    )
    return {"id": identificador, "colas": empuje.estado()}


@router.get(
    "/eventos/estado",
    summary="Cuántos escuchan y qué hay en cola",
    description=(
        "Para saber si el empuje está sirviendo a alguien. Una cola que crece "
        "sin oyentes es memoria gastada, y un oyente que no recibe nada suele "
        "ser una integración que se quedó conectada y nadie mira."
    ),
)
async def estado_del_empuje(principal: AutenticadoDep) -> Any:
    return empuje.estado()


ROUTERS = [router, crear_router_sesion(_piezas)]
ROUTERS_SIN_PREFIJO = [router_proxy]
