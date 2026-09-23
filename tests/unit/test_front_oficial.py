"""El front oficial no es un cliente privilegiado (CRM-07.04.02.07, .08).

contecrm es frontless: toda capacidad existe primero como servicio con contrato
y la interfaz es un consumidor más. Eso deja de ser cierto en el momento en que
la interfaz oficial hace algo que la API no publica, o decide algo que debería
decidir el servidor — y ese momento no llega de golpe: llega una pantalla a la
vez, cada una con su prisa.

Estos dos gates son lo que lo impide. No comprueban el aspecto del front:
comprueban que **no pueda** convertirse en el privilegiado.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
FRONT = RAIZ / "frontend" / "src"

pytestmark = pytest.mark.skipif(not FRONT.exists(), reason="el front oficial no está en este árbol")


def _sin_comentarios(texto: str) -> str:
    """El código, sin los comentarios.

    Hace falta porque los comentarios de este front explican precisamente lo que
    NO se hace —«la sesión va en cookie, nunca en `localStorage`»— y un gate que
    mirara el fichero entero daría por infracción la frase que documenta la
    regla. Castigar la explicación de una decisión correcta es la forma más
    rápida de que nadie vuelva a escribirla.
    """
    sin_bloque = re.sub(r"/\*.*?\*/", "", texto, flags=re.S)
    return re.sub(r"^\s*//.*$", "", sin_bloque, flags=re.M)


def _fuentes() -> list[Path]:
    return sorted(
        p
        for p in FRONT.rglob("*.ts*")
        if not p.name.endswith(".test.ts") and not p.name.endswith(".test.tsx")
    )


# Rutas literales que el front puede llamar aunque no salgan de la superficie,
# con el motivo escrito. Cada entrada es una excepción y por eso se nombran.
RUTAS_EXENTAS = {
    "/api/v1/superficie": "es la propia superficie: pedirla no puede exigir estar en ella",
    "/api/v1/estado": "la agrega el gateway juntando la de todos los servicios",
    "/api/v1/sso/iniciar": "el arranque del SSO, que es una navegación del navegador, no una llamada",
}


def test_toda_llamada_del_front_existe_como_ruta_publicada() -> None:
    """Una pantalla que llama a algo que la API no publica es una funcionalidad
    que solo existe en la interfaz — exactamente lo que RT-1 prohíbe.

    Se comprueba sobre las rutas **literales** que aparecen en el código. Las
    que el front construye leyendo la superficie no hace falta comprobarlas: por
    construcción salen de ahí, que es de lo que trata toda la consola.
    """
    import importlib
    import os

    os.environ["BUS_BACKEND"] = "memoria"
    publicadas: set[str] = set()
    servicios = sorted(
        p.name
        for p in (RAIZ / "services").iterdir()
        if p.is_dir() and not p.name.startswith("_") and (p / "main.py").exists()
    )
    for servicio in servicios:
        os.environ["SERVICE_NAME"] = servicio
        app = importlib.import_module(f"services.{servicio}.main").app
        publicadas |= set(app.openapi()["paths"])

    # `/api/v1/algo/{id}` en el servidor ↔ `/api/v1/algo/` + lo que sea aquí.
    patrones = [re.compile("^" + re.sub(r"\{[^}]+\}", "[^/]+", r) + "$") for r in publicadas]

    literal = re.compile(r'"(/api/v1/[^"$`]*)"')
    desconocidas: list[str] = []
    for fichero in _fuentes():
        for encontrada in literal.findall(_sin_comentarios(fichero.read_text(encoding="utf-8"))):
            # La cadena de consulta no es parte de la ruta: `/coste/capacidad` y
            # `/coste/capacidad?contratada=10` son el mismo endpoint, y tratarlas
            # como distintas haría que este gate acusara de inventarse una ruta a
            # una llamada correcta.
            ruta = encontrada.split("?", 1)[0]
            if ruta in RUTAS_EXENTAS:
                continue
            if not any(p.match(ruta) for p in patrones):
                desconocidas.append(f"{fichero.relative_to(FRONT)}: {ruta}")

    assert not desconocidas, (
        "El front llama a rutas que ningún servicio publica:\n  "
        + "\n  ".join(sorted(desconocidas))
        + "\n\nSi la ruta es legítima y no sale de la superficie, añádela a "
        "`RUTAS_EXENTAS` con su motivo."
    )


# Señales de que una decisión de negocio se ha colado en la interfaz. Son
# fragmentos y no nombres exactos porque lo que se busca es la intención, y
# quien escribe `calcularDescuento` no lo llama igual dos veces.
LOGICA_DE_NEGOCIO = (
    "calcularPrecio",
    "calcularDescuento",
    "calcularImpuesto",
    "aplicarDescuento",
    "puntuarLead",
    "calcularSla",
    "calcularComision",
    "siguienteEtapa",
)


def test_cero_logica_de_negocio_en_el_front() -> None:
    """Ni cálculo de precios, ni de permisos, ni de reglas de estado (CRM-07.04.02.08).

    La regla real es más ancha de lo que un gate puede comprobar, así que esto
    caza lo que sí se puede cazar: los cálculos que tienen nombre. Lo que no
    puede comprobar —una regla de negocio escondida en un `if`— lo sostiene la
    revisión, y por eso conviene que la lista de arriba crezca cada vez que
    aparezca uno nuevo.

    Lo que sí se comprueba entero es lo de los permisos: el front **lee** los
    permisos efectivos que le da el servidor y con eso decide qué ofrecer, pero
    no puede derivar permisos de ningún otro sitio.
    """
    encontrados: list[str] = []
    for fichero in _fuentes():
        texto = _sin_comentarios(fichero.read_text(encoding="utf-8"))
        for marca in LOGICA_DE_NEGOCIO:
            if marca in texto:
                encontrados.append(f"{fichero.relative_to(FRONT)}: {marca}")

    assert not encontrados, (
        "Cálculo de negocio en la interfaz:\n  "
        + "\n  ".join(sorted(encontrados))
        + "\n\nEso lo decide el servicio y se pide por API."
    )


def test_el_front_no_guarda_datos_de_negocio_en_el_navegador() -> None:
    """Solo preferencias de quien mira (CRM-07.04.02.09).

    Y el token de sesión **nunca**: un XSS con el token en `localStorage` es una
    sesión robada; con cookie `HttpOnly`, no. Por eso el cliente de API no lee ni
    escribe ningún almacén y la sesión viaja en cookie.
    """
    # La lista es explícita a propósito: añadir un fichero aquí es una decisión
    # que se ve en la revisión. El criterio para entrar es el mismo para los
    # tres — se guarda una preferencia de quien mira, que si se pierde no pasa
    # nada y que no le dice a nadie nada sobre el negocio ni sobre la sesión.
    permitidos = {
        "lib/tema.ts",  # claro u oscuro
        "lib/panel.tsx",  # el menú lateral, abierto o cerrado
        "componentes/BarraLateral.tsx",  # qué secciones del menú se dejaron plegadas
        "componentes/Tabla.tsx",  # qué columnas quiere ver cada quien en cada listado
    }
    usos: list[str] = []
    for fichero in _fuentes():
        relativo = str(fichero.relative_to(FRONT))
        if relativo in permitidos:
            continue
        texto = _sin_comentarios(fichero.read_text(encoding="utf-8"))
        for almacen in ("localStorage", "sessionStorage", "indexedDB"):
            if almacen in texto:
                usos.append(f"{relativo}: {almacen}")

    assert not usos, (
        "El front guarda cosas en el navegador fuera de `lib/tema.ts`:\n  "
        + "\n  ".join(sorted(usos))
        + "\n\nAhí solo van preferencias de quien mira, nunca dato de negocio ni "
        "la sesión."
    )


def test_cada_seccion_declarada_hecha_tiene_pantalla_en_el_codigo() -> None:
    """La declaración del catálogo y las pantallas reales no pueden separarse
    (CRM-07.04.05.01).

    El catálogo dice qué secciones enseña el front oficial; `modulos.ts` dice
    qué pantallas hay. Son dos listas, y dos listas que tienen que coincidir
    acaban no coincidiendo — la que se queda corta es siempre la del código,
    porque marcar una capacidad como hecha cuesta una línea y construir la
    pantalla cuesta una tarde.

    Así que una sección declarada **hecha** tiene que tener su módulo aquí, o
    ser una de las dos pantallas a medida que existen por su cuenta.
    """
    import yaml

    catalogo = yaml.safe_load((RAIZ / "docs" / "catalogo" / "catalogo.yaml").read_text("utf-8"))
    declaradas = {
        str(c["cubre"])
        for m in catalogo["modulos"]
        for s in m["secciones"]
        for f in s["funciones"]
        for c in f["capacidades"]
        if c["id"].startswith("CRM-07.04.03.") and c.get("cubre") and c["estado"] == "hecho"
    }

    # Pantallas a medida: las que no salen de `modulos.ts` porque no son un
    # listado de un recurso. Se declaran **con su fichero** y se comprueba que
    # existe — una exención sin comprobar es la forma más fácil de que este gate
    # deje de servir: se añade una línea y la sección se da por cubierta sin que
    # nadie haya escrito nada.
    A_MEDIDA = {
        # La consola se construye leyendo la superficie, no una lista.
        "7.1": "Consola.tsx",
        # El estado lo agrega el gateway juntando el de cada servicio.
        "0.6": "Estado.tsx",
        # Los compromisos se enseñan dentro del estado, al lado de lo medido.
        "8.2": "Estado.tsx",
        # La colaboración vive en la ficha de cualquier registro, a la que se
        # llega desde todos los listados en vez de tener entrada propia.
        "6.2": "Ficha.tsx",
        "5.2": "Inteligencia.tsx",
        "6.1": "Puesto.tsx",
        "7.2": "Alm.tsx",
        "7.5": "Ayuda.tsx",
        "8.1": "Rendimiento.tsx",
        "9.1": "Proveedores.tsx",
        "9.2": "Coste.tsx",
    }
    faltan_ficheros = sorted(
        seccion
        for seccion, fichero in A_MEDIDA.items()
        if not (FRONT / "paginas" / fichero).exists()
    )
    assert not faltan_ficheros, (
        "Secciones declaradas «a medida» cuya pantalla no existe:\n  "
        + "\n  ".join(faltan_ficheros)
    )

    modulos = (FRONT / "lib" / "modulos.ts").read_text("utf-8")
    con_pantalla = set(re.findall(r'seccion:\s*"([^"]+)"', modulos)) | set(A_MEDIDA)

    sin_pantalla = sorted(declaradas - con_pantalla)
    assert not sin_pantalla, (
        "Secciones declaradas hechas en el catálogo sin módulo en el front:\n  "
        + "\n  ".join(sin_pantalla)
        + "\n\nAñade el módulo en `frontend/src/lib/modulos.ts` o devuelve la "
        "capacidad a «pendiente»."
    )

    # Y al revés: un módulo que dice cubrir una sección que el catálogo no da
    # por hecha está enseñando algo que nadie ha declarado terminado.
    sobrantes = sorted(set(re.findall(r'seccion:\s*"([^"]+)"', modulos)) - declaradas)
    assert not sobrantes, (
        "Módulos del front que cubren secciones no declaradas hechas:\n  " + "\n  ".join(sobrantes)
    )


def test_el_front_es_accesible_por_teclado_y_para_lectores(  # noqa: D103
) -> None:
    """Accesibilidad WCAG 2.2 AA (CRM-07.04.01.06, CRM-07.04.04.02).

    Lo que un gate estático puede comprobar de la accesibilidad no es todo, y
    conviene decirlo: el contraste real y el orden de foco los mide el navegador.
    Lo que sí se puede comprobar aquí son los fallos que más veces aparecen y
    que ninguna herramienta perdona:

      * un salto al contenido, sin el cual cada página empieza recorriendo el
        menú entero;
      * `lang` en el documento, sin el cual el lector de pantalla lee castellano
        con fonética inglesa;
      * que toda `<nav>` esté rotulada, porque «navegación» a secas no
        distingue entre el menú principal y el de un módulo;
      * que ningún control interactivo se quede sin nombre accesible.

    `eslint-plugin-jsx-a11y` cubre el resto en cada cambio, y está en la
    configuración del front con sus reglas recomendadas.
    """
    marco = (FRONT / "componentes" / "Marco.tsx").read_text("utf-8")
    assert "saltarAlContenido" in marco, "falta el salto al contenido"
    assert 'id="contenido"' in marco, "el salto no tiene destino"

    indice = (FRONT.parent / "index.html").read_text("utf-8")
    assert 'lang="es"' in indice, "el documento no declara idioma"

    sin_rotular: list[str] = []
    for fichero in _fuentes():
        texto = _sin_comentarios(fichero.read_text("utf-8"))
        for nav in re.findall(r"<nav\b[^>]*>", texto):
            if "aria-label" not in nav:
                sin_rotular.append(f"{fichero.relative_to(FRONT)}: {nav[:60]}")
    assert not sin_rotular, (
        "Navegaciones sin rótulo:\n  "
        + "\n  ".join(sin_rotular)
        + "\n\n«navegación» a secas no distingue el menú principal del de un módulo."
    )

    # La configuración de accesibilidad tiene que estar activa: sin el plugin,
    # los fallos que sí se detectan solos dejarían de detectarse y este gate
    # daría una falsa sensación de cobertura.
    eslint = (FRONT.parent / "eslint.config.js").read_text("utf-8")
    assert "jsx-a11y" in eslint, "el front no comprueba accesibilidad en cada cambio"


# Tope del paquete servido al navegador, en kilobytes comprimidos. No es una
# cifra redonda: es lo que hoy ocupa el front con margen para crecer un tercio.
# Un presupuesto que no aprieta nunca no es un presupuesto.
PRESUPUESTO_KB = 120


def test_el_paquete_del_front_cabe_en_el_presupuesto() -> None:
    """Presupuesto de rendimiento, comprobado en local (CRM-07.04.04.03).

    Una aplicación web crece de treinta en treinta kilobytes, cada uno con su
    justificación, y un día tarda cuatro segundos en abrir. Nadie lo decide: se
    llega. Un tope que falla obliga a que la decisión sea explícita — o se
    justifica subir el número, o se quita algo.

    Se mide sobre `dist/`, así que solo corre si el front está construido: pedir
    una construcción en cada prueba convertiría el ciclo rápido en uno de dos
    minutos.
    """
    import gzip

    dist = RAIZ / "frontend" / "dist" / "assets"
    if not dist.exists():
        pytest.skip("el front no está construido (`npm run build` en `frontend/`)")

    comprimido = sum(len(gzip.compress(f.read_bytes())) for f in dist.glob("*.js"))
    kb = comprimido / 1024
    assert kb <= PRESUPUESTO_KB, (
        f"El paquete del front ocupa {kb:.0f} kB comprimidos y el tope son "
        f"{PRESUPUESTO_KB} kB.\n\nO se justifica subir el tope, o se quita algo. "
        "Lo que no vale es que crezca sin que nadie lo decida."
    )
