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
TOPE_SIN_PUERTA = 157

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
    assert len(_sin_puerta(frozenset())) == len(
        colecciones
    ), "sin una sola llamada del front, el recuento tiene que ser el total"

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
