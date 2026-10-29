"""Una pantalla que lee un campo inexistente no falla: se queda vacía.

Es el fallo más caro de los que he encontrado, porque **no se nota**. No hay
error, no hay traza, no hay 500: el campo llega `undefined`, la lista sale
vacía, el reloj dice «sin plazo» y la pantalla parece que funciona. Y como el
escenario de su prueba está escrito con la forma que la pantalla se imagina —no
con la que manda el servidor—, la prueba confirma la ficción.

Medido el 26-10-2026, dos casos reales en producción:

  · la **bandeja de casos** leía `numero`, `vence_at`, `cola` y `escalado`;
    la API devuelve `codigo` y `vence_resolucion_at`. Resultado: todos los
    casos caían en «con margen», el reloj decía siempre «sin plazo» y el
    número salía en blanco;
  · la pantalla de **inteligencia** pintaba «lo que suma» y «lo que resta»
    desde `salud.detalle`, que el servidor nunca envía —es una copia y el
    detalle vive en quien lo calcula—: los dos paneles salían vacíos, con sus
    rótulos puestos, en la pantalla que existe para explicar la puntuación.

**Lo que NO sirve, medido antes de construirlo.** Un barrido que compruebe si
el nombre existe «en algún sitio» del backend no caza nada: `vence_at`,
`numero`, `cola` y `escalado` aparecen los cuatro en el producto, y los cuatro
dentro del mismo servicio. Tiene que ser por ENDPOINT.

Y por eso esto es un trinquete y no un gate completo: resolver «ruta → función
→ claves que devuelve» atravesando las delegaciones es un proyecto aparte. Lo
que se vigila aquí es lo que se puede comprobar barato y tiene dientes: que
cada contrato que una pantalla da por bueno esté **fijado por una prueba de
servidor**, que es lo que de verdad impidió que los dos volvieran.
"""

from __future__ import annotations

import pathlib
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
PANTALLAS = RAIZ / "frontend/src/paginas"
PRUEBAS = RAIZ / "tests/unit"

SERVICIOS = frozenset(
    {
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
    }
)

# `listar` y `listarPagina` cuentan igual que `llamar`: las tres llevan la ruta
# y la forma en la misma llamada. Sin las dos primeras, veintiuna rutas de diez
# pantallas quedaban fuera — que es por donde entraron las cuatro pantallas que
# leían campos que nadie manda (29-10-2026).
RE_LLAMAR = re.compile(
    r'\b(?:llamar|listar|listarPagina)<([A-Za-z0-9_\[\]{}<> ,|]+)>\(\s*[`"\']([^`"\']+)'
)

# ── Contratos que una pantalla da por bueno y ninguna prueba recorre ──────
#
# **Lo que esto comprueba, y lo que NO.** Comprueba que la ruta de la que una
# pantalla declara una forma esté recorrida por alguna prueba de servidor.
# Recorrerla no es fijar sus campos: un barrido que sólo mira el código de
# respuesta la recorre y no comprueba nada de lo que la pantalla lee.
#
# Lo que de verdad impidió que los dos fallos volvieran son las pruebas por
# contrato —`test_la_bandeja_de_casos_reparte_de_verdad.py`,
# `test_los_contratos_que_leen_las_pantallas.py`,
# `test_la_cola_del_agente_se_ordena_de_verdad.py`—, que afirman campo a campo
# lo que sale por HTTP. Esto es el suelo: que no haya una pantalla pidiéndole
# una forma a una ruta que **nadie** toca.
#
# Lista CERRADA y nominal: sólo puede encoger. Se baja escribiendo una prueba
# de servidor que recorra el endpoint de verdad y compruebe los campos que la
# pantalla lee —como `test_la_bandeja_de_casos_reparte_de_verdad.py`— y
# borrando la línea en el mismo commit.
#
#   26-10-2026  23 rutas con contrato, 22 ya fijadas por una prueba de
#               servidor y UNA sin fijar: la consola de agente, que se
#               probaba llamando a la función y no recorriendo la ruta —y
#               es justo en la serialización donde se rompen estas cosas—.
#   26-10-2026  11 de 23 sin recorrer. Y cinco FIJADAS campo a campo —la
#               bandeja de casos, la cola del agente, la vista 360, lo
#               vencido de la portada y la salud de una cuenta—, que son las
#               que se verificaron a mano y las dos que estaban rotas.
#
#               La primera medición dijo «0 de 23» y era mentira: el
#               recorrido se leía a SÍ MISMO, y esta lista, al nombrar las
#               rutas, las daba por recorridas. El trinquete se justificaba
#               solo. Por eso el fichero se excluye del barrido.
#   26-10-2026  0 de 23. Las once se recorren en
#               `test_los_once_contratos_que_nadie_recorria.py`, cada una
#               pidiendo la ruta de verdad y comprobando los campos que su
#               pantalla lee. Diez estaban bien; la undécima —el desvío de un
#               entorno— era un 500, y además la pantalla leía dos campos que
#               el servidor no manda: uno dejaba el aviso siempre en verde y el
#               otro la tumbaba entera.
#
#               La lista vacía NO significa que los contratos estén fijados:
#               significa que ninguna pantalla le pide una forma a una ruta que
#               nadie toca. Fijar los campos es lo que hacen las pruebas por
#               contrato, y es lo que de verdad impide que esto vuelva.
SIN_RECORRER_HOY: set[str] = set()


def _rutas_que_piden_un_tipo() -> dict[str, set[str]]:
    """Ruta → pantallas que le piden una forma concreta.

    Sólo las llamadas con tipo —`llamar<Algo>(...)`— porque son las que
    declaran un contrato. Una llamada sin tipo no promete nada, así que
    tampoco puede mentir.
    """
    salida: dict[str, set[str]] = {}
    for fichero in sorted(PANTALLAS.glob("*.tsx")):
        texto = fichero.read_text(encoding="utf-8")
        for tipo, ruta in RE_LLAMAR.findall(texto):
            if "unknown" in tipo:
                continue
            # Una pantalla puede guardar la ruta en una constante —`${COLA}`—:
            # sin resolverla, la ruta se normaliza a `{}` y no casa con nada,
            # así que el gate pedía una prueba para una ruta sin nombre.
            for nombre_const, valor in re.findall(r'^const (\w+) = "([^"]+)";', texto, re.M):
                ruta = ruta.replace("${" + nombre_const + "}", valor)
            # Las partes variables se normalizan: `${id}` no distingue rutas.
            limpia = re.sub(r"\$\{[^}]*\}", "{}", ruta.split("?")[0])
            salida.setdefault(limpia, set()).add(fichero.name)
    return salida


def _rutas_con_prueba_de_servidor() -> set[str]:
    """Rutas que alguna prueba de servidor recorre de verdad."""
    vistas: set[str] = set()
    for fichero in PRUEBAS.glob("*.py"):
        # **Este fichero no cuenta.** Su propia lista nombra las rutas, así que
        # al leerse a sí mismo las daba por recorridas: el trinquete se
        # justificaba solo y no avisaba de nada. Medido al escribirlo.
        if fichero.name == pathlib.Path(__file__).name:
            continue
        texto = fichero.read_text(encoding="utf-8")
        # **Una llave de f-string puede llevar comillas dentro**, y eso cortaba
        # la ruta justo ahí: de `f"/api/v1/chat/mensajes/{mensaje[\'id\']}/versiones"`
        # salía `/api/v1/chat/mensajes/{mensaje[`, que no casa con nada. El
        # gate pedía entonces una prueba para una ruta que llevaba meses
        # probada — y un punto ciego así es peor que una regla que falta,
        # porque manda a escribir una prueba duplicada y sigue en rojo cuando
        # se escribe. Medido el 29-10-2026 con `/chat/mensajes/{}/versiones`.
        #
        # Se arregla en el propio patrón y no vaciando las llaves de todo el
        # fichero: eso se probó primero y dejó fuera siete rutas que sí
        # estaban recorridas.
        for ruta in re.findall(r'["\'](/api/v1/(?:[^"\'\s{]|\{[^}]*\})+)', texto):
            forma = re.sub(r"\{[^}]*\}|\$\{[^}]*\}", "{}", ruta.split("?")[0])
            vistas.add(forma)
            # Las rutas que cada servicio publica en su prefijo —la papelera,
            # el cumplimiento, el volumen— las escribe el front con
            # `${servicio}` y una prueba las recorre con un servicio concreto.
            # Son la misma ruta: la monta el mismo router compartido para los
            # trece. Sin esto, el gate pedía una prueba por servicio para algo
            # que sólo existe una vez.
            partes = forma.split("/")
            if len(partes) > 3 and partes[3] in SERVICIOS:
                vistas.add("/".join(partes[:3] + ["{}"] + partes[4:]))
    return vistas


def test_el_recorrido_mira_de_verdad() -> None:
    """Sin esto, un recorrido que no encontrara ninguna llamada diría que no
    queda ningún contrato sin fijar."""
    rutas = _rutas_que_piden_un_tipo()
    assert len(rutas) >= 15, f"sólo se ven {len(rutas)} rutas con contrato"
    # Y una que SÍ está fijada, para saber que la detección funciona.
    assert "/api/v1/casos/bandeja" in rutas
    assert "/api/v1/casos/bandeja" in _rutas_con_prueba_de_servidor()


def _la_recorre_alguna(ruta_pantalla: str, probadas: set[str]) -> bool:
    """Si alguna prueba recorre esa ruta, admitiendo que fije lo que la pantalla
    deja variable.

    La pantalla escribe `/api/v1/${servicio}/rastro/campos/${objeto}/${id}` y la
    prueba lo pide con un objeto concreto —`oportunidad`—, que es lo correcto:
    una prueba que no fija el objeto no recorre nada. Comparando los textos tal
    cual no coinciden, y el gate daba rojo por una ruta que **sí** está
    recorrida. Un guardián que da la alarma por lo correcto se acaba
    desactivando, y entonces deja de avisar de lo incorrecto.

    Lo que se sigue exigiendo: el mismo número de tramos y que **todos los
    literales de la pantalla** coincidan. Un `{}` de la pantalla casa con
    cualquier tramo; uno de la prueba, sólo con otro `{}` — al revés sería
    admitir que una prueba genérica cubre una ruta concreta que nadie pide.
    """
    if ruta_pantalla in probadas:
        return True
    suyos = ruta_pantalla.split("/")
    for probada in probadas:
        otros = probada.split("/")
        if len(otros) != len(suyos):
            continue
        if all(mio == "{}" or mio == suyo for mio, suyo in zip(suyos, otros, strict=False)):
            return True
    return False


def test_ninguna_pantalla_pide_una_forma_a_una_ruta_que_nadie_toca() -> None:
    """Es el suelo, no el techo: que ninguna pantalla declare la forma de una
    respuesta que **ninguna** prueba de servidor llega a pedir. Fijar los
    campos es otra cosa, y se hace en las pruebas por contrato."""
    rutas = _rutas_que_piden_un_tipo()
    con_prueba = _rutas_con_prueba_de_servidor()
    nuevos = sorted(
        r for r in rutas if not _la_recorre_alguna(r, con_prueba) and r not in SIN_RECORRER_HOY
    )
    assert not nuevos, (
        "Pantallas que declaran la forma de una respuesta que ninguna prueba "
        "de servidor llega a pedir. Si el servidor deja de mandar un campo "
        "—o nunca lo mandó— la pantalla se queda vacía y nadie se entera:\n  "
        + "\n  ".join(f"{r}  ({', '.join(sorted(rutas[r]))})" for r in nuevos)
    )


def test_los_que_se_fijan_salen_de_la_lista() -> None:
    """El trinquete sólo encoge si alguien lo encoge."""
    con_prueba = _rutas_con_prueba_de_servidor()
    sobran = sorted(r for r in SIN_RECORRER_HOY if r in con_prueba)
    assert not sobran, "Ya tienen prueba y siguen apuntados:\n  " + "\n  ".join(sobran)


def test_los_apuntados_siguen_existiendo() -> None:
    """Una lista con rutas que ya no se piden se queda grande para siempre y
    deja de significar nada."""
    rutas = _rutas_que_piden_un_tipo()
    fantasmas = sorted(r for r in SIN_RECORRER_HOY if r not in rutas)
    assert not fantasmas, "Apuntados y ya no se piden:\n  " + "\n  ".join(fantasmas)
