"""Colecciones publicadas a las que no se llega desde ninguna pantalla.

Una ruta que la API publica y el front no pide es trabajo hecho que no usa
nadie. No falla —no hay error, no hay traza— y por eso crece sin que se note:
cada capacidad nueva añade sus rutas, y las que no se enganchan a una pantalla
se quedan ahí, contadas como hechas.

Medido sobre el contrato sellado el 27-10-2026: **702 colecciones `GET` y 252
sin puerta**. No es un número para arreglar de un commit —cada una necesita
decidir dónde se enseña, y varias no se enseñan a propósito— pero sí para que
no suba. Esto es un trinquete, como el de capacidades sin pantalla.

**Las cuatro formas de llegar, y por qué cuentan las cuatro.** Una colección
tiene puerta si:

  1. alguna pantalla la pide **literalmente**;
  2. una pantalla pide `/api/v1/:servicio/…` o `/api/v1/${servicio}/…` y esta
     ruta es la de uno de los servicios: la misma pantalla las abre todas —la
     de Plataforma con su selector, y las pestañas con `por_servicio`—;
  3. es el `…/exportar` de una colección que sí tiene puerta: el botón de
     exportar lo pone la pantalla sola, no hace falta declararlo;
  4. cuelga de un identificador de una colección con puerta
     —`/cuentas/{id}/direcciones`—: la ficha genérica descubre sus
     subcolecciones de la superficie, en marcha.

Sin las cuatro, este gate contaría como huérfanas rutas que se abren todos los
días. La primera versión no tenía la 2 y decía 352 en vez de 252: cien rutas
que la pantalla de Plataforma sí abre.

**Lo que NO comprueba**: que la pantalla la pida bien, ni que conteste. Eso lo
miran `test_la_pantalla_manda_lo_que_el_servidor_exige` y el barrido de
pestañas. Aquí sólo si hay por dónde entrar.
"""

from __future__ import annotations

import functools
import json
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
SELLO = RAIZ / "docs/contrato-publicado.json"
FRONT = RAIZ / "frontend/src"

#   27-10-2026  252 de 702  primera medida, con la sonda ya corregida.
#   27-10-2026  200 de 702  el informe de cumplimiento, el plan de particionado
#                            y el rastro completo, en la pantalla de Plataforma:
#                            una familia repetida en los trece servicios son
#                            tres paneles, no treinta y nueve pestañas.
#   27-10-2026  177 de 702  doce colecciones que no salían en ninguna pestaña
#                            —sagas, reglas de compartición, planes de cuenta,
#                            buzones, calendarios…— y las fichas de entorno y
#                            calendario, que no existían.
#   27-10-2026  167 de 708  `por_servicio`: una pestaña abre la misma colección
#                            en todos los servicios que la publican. El
#                            denominador sube porque el contrato se reselló.
#   27-10-2026  161 de 708  el portal del cliente enseñaba dos secciones de
#                            ocho. Las otras seis estaban publicadas y servidas
#                            —lo instalado, los contratos, los pedidos, los
#                            artículos, la comunidad y quién más entra— sin que
#                            el cliente pudiera verlas.
#   27-10-2026  157 de 708  la página de estado del tenant decía en su propia
#                            cabecera que enseña el objetivo de servicio y el
#                            presupuesto de error (CRM-00.06.01.04) y leía una
#                            sola ruta. Las otras cuatro —objetivo, consumo
#                            sobre lo contratado, promesas entre servicios y
#                            consultas degradadas— estaban servidas y nadie las
#                            pedía.
#   27-10-2026  148 de 708  `resumen`: una pestaña puede llevar encima las
#                            MEDIDAS que la acompañan —un objeto con cifras y
#                            la frase que dice qué significan—. De las que
#                            quedaban sin puerta, 96 de 157 eran eso: no caben
#                            como pestaña y hacerle una pantalla a cada una
#                            serían noventa y seis pantallas de un párrafo.
#                            Estrenado en el módulo de IA, con tres listados
#                            que tampoco tenían pestaña.
#   27-10-2026  127 de 708  veintiuna medidas enganchadas a la pestaña donde
#                            se preguntan: la salud del dato encima de su cola,
#                            las licencias encima de los usuarios, el MRR
#                            encima de las suscripciones, los casos a punto de
#                            incumplir encima de los acuerdos de servicio.
#   27-10-2026  108 de 708  nueve listados que no tenían pestaña —las tablas
#                            del almacén, las fuentes federadas, los cuadros
#                            incrustados, las interacciones por canal, lo
#                            programado y lo recibido de cada integración, el
#                            estado financiero de un plan de cuenta y el
#                            histórico de tipos de cambio— y la numeración, que
#                            enseñaba la de ventas y no la de `party` ni la de
#                            `service`.
#   27-10-2026  107 de 708  la búsqueda global. No es una puerta menos: es que
#                            `GET /api/v1/buscar` no la llamaba nadie Y además
#                            devolvía cero siempre, porque el gateway
#                            preguntaba a `/api/v1/buscar` de cada servicio y
#                            cada uno la publica en `/api/v1/{servicio}/buscar`.
#   27-10-2026   87 de 708  veinte declaradas SIN PANTALLA A PROPÓSITO, cada
#                            una con su motivo y dos gates que impiden que la
#                            lista envejezca: las sondas de salud, el SCIM que
#                            llama el directorio del cliente, los componentes
#                            que se pintan en SU web, los documentos de
#                            contrato, dos caminos a una colección que ya tiene
#                            pestaña, y las conversaciones, que se trabajan en
#                            la consola de agente en una sola cola.
#   27-10-2026   76 de 708  doce medidas más: el panel de GRC encima de los
#                            riesgos, los pares que parecen la misma persona y
#                            la caducidad del enriquecimiento encima de la cola
#                            de calidad, la eficacia del conocimiento, el
#                            remitente de cada clase de correo, qué se puede
#                            explotar del tenant, la clave de cifrado propia y
#                            la revisión de activos.
#   27-10-2026   60 de 708  el panel «tu segundo factor» en Seguridad —con qué
#                            has entrado, qué te falta, qué te van a pedir
#                            reverificar y qué pasa si cambias de móvil, que es
#                            la llamada que acaba en desbloqueo manual—, y
#                            cuatro pestañas: módulos instalados, avisos y
#                            preferencias, perfiles de industria y aprobaciones
#                            de activos.
#   27-10-2026   48 de 708  «la suite de una vez» —qué cambiaría lo que está a
#                            punto de aplicarse, cómo ve el cliente la suite
#                            entera y si las bajas se cerraron en TODAS las
#                            herramientas—, tres medidas más y cinco rutas que
#                            no llevan pantalla a propósito.
#   27-10-2026   44 de 708  tres informes de periodo que no tenían pestaña
#                            —cumplimiento de SLA, satisfacción y el calendario
#                            de campañas, donde se ve qué se solapa— y el flujo
#                            de eventos, que es un `text/event-stream` abierto
#                            y no una colección: una pantalla que lo listara se
#                            quedaría colgada.
#
# **De qué son las 44 que quedan**, clasificadas el 27-10-2026 para que el
# siguiente no tenga que medirlo otra vez. No son más de lo mismo:
#
#   · **~20 son calculadoras**: piden datos que sólo tiene quien está en mitad
#     de otra cosa —«¿qué le cobramos a este cliente por esto?», «¿se puede
#     mandar esto, ahora, a esta persona?», «¿a qué proveedor le toca este
#     correo?»—. Su sitio es dentro del flujo donde se preguntan, no una
#     pestaña: una pantalla que pide un JSON a mano no es una pantalla, es una
#     calculadora en la que el usuario tiene que ser el modelo. Abrirlas es
#     trabajo de cada flujo, no de la navegación.
#   · **~8 cuelgan de un registro pero por OTRO prefijo**: el historial de
#     previsión de una oportunidad vive en `/forecast/oportunidades/{id}/…` y
#     su ficha en `/opportunities/{id}`. La ficha descubre sus paneles por
#     prefijo común, así que no los ve. Lo que los identifica es el nombre del
#     parámetro —`{oportunidad_id}`—, que es la convención que ya usa
#     `montar_ficha`; engancharlos por ahí es un trabajo propio y además varias
#     devuelven un objeto, no una lista, y la ficha hoy sólo pinta listas.
#   · **6 son el corpus documental** —carpetas, sus documentos, sus permisos—,
#     que es una pantalla entera y pide decidir cómo se navega un árbol.
#   · **3 son del chat** —buscar, presencia, versiones de un mensaje—, que son
#     mejoras de esa pantalla.
TOPE_SIN_PUERTA = 44

# ── Las que no llevan pantalla A PROPÓSITO ───────────────────────────────
#
# Con su motivo, y el motivo tiene que ser una propiedad de la ruta, no una
# excusa. Una lista de excepciones sin razones es una forma de poner el
# contador en verde; con razones es lo contrario de una lista de los que SÍ:
# cada línea se puede discutir, y la que no se sostenga se quita y se abre la
# puerta.
#
# Hay un gate más abajo que exige que cada una siga existiendo en el contrato:
# una excepción a una ruta que ya no está es una línea que nadie va a releer.
SIN_PUERTA_A_PROPOSITO: dict[str, str] = {
    # Sondas del balanceador y del orquestador. No son API de negocio: las
    # llama la infraestructura cada pocos segundos y una persona nunca.
    "/health": "sonda de infraestructura",
    "/health/live": "sonda de infraestructura",
    "/health/ready": "sonda de infraestructura",
    # SCIM es el estándar con el que el directorio del CLIENTE da de alta y de
    # baja a su gente. Lo llama su proveedor de identidad, no una pantalla
    # nuestra; lo que sí tiene pantalla es qué proveedores hay configurados.
    "/api/v1/scim/v2/Users": "la llama el proveedor de identidad del cliente",
    "/api/v1/scim/v2/Groups": "la llama el proveedor de identidad del cliente",
    "/api/v1/scim/v2/Schemas": "la llama el proveedor de identidad del cliente",
    "/api/v1/scim/v2/ResourceTypes": "la llama el proveedor de identidad del cliente",
    "/api/v1/scim/v2/ServiceProviderConfig": "la llama el proveedor de identidad del cliente",
    # Los componentes embebibles se pintan DENTRO de la web del cliente, con su
    # token acotado a un registro. Una pantalla nuestra que los abriera sería
    # la ficha que ya existe.
    "/api/v1/embebido/ficha-cuenta": "se pinta en la web del cliente, no aquí",
    "/api/v1/embebido/estado-pedido": "se pinta en la web del cliente, no aquí",
    "/api/v1/embebido/lista-casos": "se pinta en la web del cliente, no aquí",
    "/api/v1/sdk/componentes": "catálogo para quien integra, como el OpenAPI",
    "/api/v1/sdk/plan": "catálogo para quien integra, como el OpenAPI",
    "/api/v1/eventos/asyncapi.json": "documento de contrato, como el OpenAPI",
    # Dos caminos a la misma colección. El que tiene pestaña es el otro, y
    # enseñar los dos obligaría a saber cuál mira cada pantalla.
    "/api/v1/agentes-ia": "misma colección que /agentes-ia/exposiciones, que sí tiene pestaña",
    "/api/v1/agentes-ia/exportar": "misma colección que /agentes-ia/exposiciones",
    "/api/v1/party-admin/papelera": "misma papelera que /party/papelera, que sí tiene pestaña",
    # Decisión escrita en `recursos.ts`: las conversaciones se trabajan desde
    # la consola de agente, que las da junto a los casos en UNA sola cola. Una
    # lista aparte reintroduce la bandeja por canal que la omnicanalidad viene
    # a quitar.
    "/api/v1/conversaciones": "se trabajan en la consola de agente, en una sola cola",
    "/api/v1/conversaciones/exportar": "se trabajan en la consola de agente",
    # La portada del portal se compone de sus secciones, y el portal las pinta
    # una a una: pedirla además sería pedir dos veces lo mismo.
    "/api/v1/portal/mi/resumen": "el portal pinta sus secciones, que es lo que resume",
    # La búsqueda por servicio: su puerta es la paleta, que llama a
    # `/api/v1/buscar` y el gateway reparte. Una pantalla por servicio sería
    # pedirle al usuario que sepa en cuál vive lo que busca.
    "/api/v1/party/buscar": "la llama la búsqueda global, que sí tiene puerta",
    "/api/v1/sales/buscar": "la llama la búsqueda global, que sí tiene puerta",
    # Los valores admitidos de un vocabulario de negocio. La pantalla que los
    # gobierna es la del vocabulario —donde además se cambian—: enseñar los dos
    # caminos obligaría a saber cuál manda.
    "/api/v1/leads/motivos-descarte": "los gobierna la pantalla de vocabularios de negocio",
    "/api/v1/pipeline/motivos-perdida": "los gobierna la pantalla de vocabularios de negocio",
    # El contrato de un módulo, para quien lo escribe. Es documentación, como
    # el OpenAPI, y por eso no tiene pantalla: lo que sí la tiene es qué
    # módulos hay instalados y si lo instalado es lo que se publicó.
    "/api/v1/metadata/modulos/superficie": "documento de contrato del módulo, como el OpenAPI",
    # Un `text/event-stream` que se queda abierto, con latido cada veinte
    # segundos. Lo consume quien integra para recibir eventos sin montar un
    # endpoint propio; una pantalla que lo «listara» se quedaría colgada.
    "/api/v1/eventos/flujo": "es un flujo que se queda abierto, no una colección",
}


SERVICIOS = (
    "party",
    "sales",
    "service",
    "marketing",
    "metadata",
    "analytics",
    "identity",
    "orchestrator",
    "automation",
    "integration",
    "intelligence",
    "tenancy",
    "eventing",
    "gateway",
)


def _forma(ruta: str) -> str:
    """La ruta sin valores: `{cuenta_id}` y `${id}` son lo mismo aquí."""
    return re.sub(r"\{[^}]*\}", "{}", ruta.split("?")[0]).rstrip("/")


@functools.cache
def _colecciones() -> dict[str, str]:
    """Colección `GET` → servicio que la publica, del contrato sellado.

    Colección y no ficha: el último tramo no es un parámetro. Una ficha se abre
    desde su listado, así que exigirle puerta propia sería contar dos veces.
    """
    sello = json.loads(SELLO.read_text(encoding="utf-8"))
    salida: dict[str, str] = {}
    for servicio, operaciones in sello.items():
        for operacion in operaciones:
            metodo, _, camino = operacion.partition(" ")
            if metodo != "GET" or camino.rstrip("/").split("/")[-1].startswith("{"):
                continue
            salida[camino] = servicio
    return salida


@functools.cache
def _pedidas() -> frozenset[str]:
    """Todo lo que el front pide, con las plantillas de servicio expandidas."""
    texto = "\n".join(
        p.read_text(encoding="utf-8", errors="ignore")
        for p in FRONT.rglob("*.ts*")
        if "/pruebas/" not in p.as_posix()
    )
    salida: set[str] = set()
    for cruda in re.findall(r'["\'`](/api/v1/[^"\'`\s]*)', texto):
        forma = re.sub(r"\$\{[^}]*\}", "{}", cruda.split("?")[0]).rstrip("/")
        salida.add(forma)
        # `:servicio` —`recursos.ts`— y `${servicio}` en el tramo del servicio
        # —las pantallas con selector— valen para los catorce nombres.
        if ":servicio" in forma:
            salida |= {forma.replace(":servicio", s) for s in SERVICIOS}
        partes = forma.split("/")
        if len(partes) > 3 and partes[3] == "{}":
            salida |= {"/".join(partes[:3] + [s] + partes[4:]) for s in SERVICIOS}
    return frozenset(salida)


def _sin_puerta(pedidas: frozenset[str] | None = None) -> tuple[str, ...]:
    pedidas = _pedidas() if pedidas is None else pedidas
    exportables = {f"{r}/exportar" for r in pedidas}

    def cuelga_de_una_con_puerta(camino: str) -> bool:
        partes = _forma(camino).split("/")
        if "{}" not in partes:
            return False
        return "/".join(partes[: partes.index("{}")]) in pedidas

    return tuple(
        sorted(
            c
            for c in _colecciones()
            if _forma(c) not in pedidas
            and _forma(c) not in exportables
            and c not in SIN_PUERTA_A_PROPOSITO
            and not cuelga_de_una_con_puerta(c)
        )
    )


def test_el_recorrido_mira_de_verdad() -> None:
    """Si el sello no se leyera, o el patrón dejara de encontrar llamadas, esto
    saldría en verde sin haber comparado nada — el verde de no mirar."""
    colecciones = _colecciones()
    assert len(colecciones) >= 600, f"sólo se ven {len(colecciones)} colecciones en el sello"
    pedidas = _pedidas()
    assert len(pedidas) >= 300, f"sólo se ven {len(pedidas)} rutas pedidas por el front"
    # Y que al menos una colección conocida esté reconocida como abierta: si
    # ninguna lo estuviera, el recuento sería el total y el tope lo cazaría,
    # pero al revés —si TODAS lo estuvieran— saldría cero sin mirar.
    assert "/api/v1/accounts" in pedidas
    assert "/api/v1/accounts" in colecciones


def test_el_gate_caza_una_puerta_que_se_cierra() -> None:
    """Validación por mutación, plantando el caso malo.

    Con el front sin pedir nada, TODAS tienen que salir huérfanas. Y quitando
    una sola puerta —la de cuentas— tiene que salir esa y las suyas: la ficha y
    el exportar cuelgan de ella, así que cerrarla cierra tres.
    """
    colecciones = _colecciones()
    # Todo menos las declaradas a propósito, que no dependen del front.
    a_proposito = len([r for r in SIN_PUERTA_A_PROPOSITO if r in colecciones])
    assert (
        len(_sin_puerta(frozenset())) == len(colecciones) - a_proposito
    ), "sin una sola llamada del front, el recuento tiene que ser todo lo demás"

    cerrada = frozenset(r for r in _pedidas() if r != "/api/v1/accounts")
    nuevas = set(_sin_puerta(cerrada)) - set(_sin_puerta())
    assert "/api/v1/accounts" in nuevas, nuevas
    assert (
        "/api/v1/accounts/exportar" in nuevas
    ), "el exportar de una colección sin puerta tampoco la tiene"


def test_las_colecciones_sin_puerta_no_crecen() -> None:
    """Publicar una colección y no enseñarla en ninguna parte es trabajo hecho
    que no usa nadie, y no da ningún error que lo delate."""
    cuantas = len(_sin_puerta())
    assert cuantas <= TOPE_SIN_PUERTA, (
        f"Han subido a {cuantas} las colecciones publicadas sin forma de llegar "
        f"a ellas; el tope medido eran {TOPE_SIN_PUERTA}. Si has publicado una "
        f"ruta nueva, dile desde qué pantalla se abre:\n  " + "\n  ".join(_sin_puerta()[:20])
    )


def test_el_tope_baja_cuando_se_abren_puertas() -> None:
    """Un tope que se queda alto deja de medir: al mes siguiente admite otra vez
    las que se acaban de quitar."""
    cuantas = len(_sin_puerta())
    assert cuantas >= TOPE_SIN_PUERTA - 3, (
        f"Van {cuantas} y el tope dice {TOPE_SIN_PUERTA}: bájalo en este mismo "
        "commit, que es lo que convierte el arreglo en un suelo."
    )


def test_ninguna_excepcion_sobra() -> None:
    """Una excepción a una ruta que ya no existe es una línea que nadie relee.

    Y es peor que inútil: el día que vuelva a publicarse esa ruta, se daría por
    excusada sin que nadie lo haya decidido.
    """
    colecciones = _colecciones()
    # Las sondas de salud no están en el contrato publicado —no son API de
    # negocio— así que se comprueban por su forma.
    sobran = [
        ruta
        for ruta in SIN_PUERTA_A_PROPOSITO
        if ruta not in colecciones and not ruta.startswith("/health")
    ]
    assert not sobran, "Excepciones a rutas que ya no publica nadie. Se quitan:\n  " + "\n  ".join(
        sobran
    )


def test_toda_excepcion_lleva_su_motivo() -> None:
    """Sin motivo, esta lista es una forma de poner el contador en verde.

    Con motivo es lo contrario de una lista de los que SÍ: cada línea se puede
    discutir, y la que no se sostenga se quita y se abre la puerta.
    """
    mudas = [r for r, porque in SIN_PUERTA_A_PROPOSITO.items() if len(porque.strip()) < 15]
    assert not mudas, mudas
