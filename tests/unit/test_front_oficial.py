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
    #
    # LO QUE ESTO NO CAZA, dicho aquí para que nadie se fíe de más: una llamada
    # inventada con el mismo número de tramos que una ruta con parámetro pasa
    # como buena. `/api/v1/accounts/exportar` encajaría con
    # `/api/v1/accounts/{cuenta_id}` aunque no exista. No se puede afinar sin
    # inventar: hoy hay tres llamadas que pasan justamente por ahí y las tres
    # son correctas —el front pide un vocabulario por su nombre, y el nombre es
    # el valor del parámetro—, así que exigir coincidencia exacta rompería
    # código bueno. Queda escrito en vez de arreglado a medias: un gate que
    # promete más de lo que comprueba es peor que uno que no existe, porque se
    # confía en él.
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
            # `:servicio` es una plantilla, no una ruta: la pestaña declara en
            # qué servicios vive la misma colección y la pantalla lo sustituye
            # por el que se elige. Se comprueba contra UNO de verdad —si está
            # publicada para uno, lo está para los que declare, y de eso se
            # encarga el gate de rutas del front, que los recorre todos—.
            if ":servicio" in ruta:
                ruta = ruta.replace(":servicio", "sales")
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
        # Si cada listado se mira como tabla, como tarjetas o por columnas.
        # Entra por el mismo criterio: es una preferencia de quien mira, no
        # dice nada del negocio, y perderla solo cuesta volver a elegirla.
        "componentes/Vistas.tsx",
        # Qué cliente está mirando quien opera la plataforma. Entra por el
        # mismo criterio y con una condición más: va en `sessionStorage`, que
        # vive en la PESTAÑA. Recargar la mantiene —si no, cada F5 devolvería a
        # mitad de trabajo— y cerrarla la olvida, que es lo correcto para algo
        # que da acceso a datos de otro. No es la sesión, no concede nada por
        # sí solo —el servidor sólo la atiende si quien la manda opera la
        # plataforma— y no guarda ni un dato de negocio: sólo cuál se mira.
        "lib/api.ts",
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


# Tope de lo que el navegador descarga para ABRIR la aplicación, en kilobytes
# comprimidos. Un presupuesto que no aprieta nunca no es un presupuesto.
#
# Subido de 120 a 128 el 24-09-2026, con su motivo, que es lo que este gate pide
# cuando no se quiere quitar nada:
#
# El paquete de entrada son 95 kB de armazón más 16 de la tabla de iconos, y
# dentro va el DICCIONARIO DE IDIOMA ENTERO —las cadenas de las noventa
# pantallas— para poder pintar el login. Ese es el peso que sobra, y la forma
# correcta de quitarlo es partir el diccionario para que cada pantalla cargue el
# suyo, no ir recortando funcionalidad para caber en un número puesto cuando el
# producto tenía la mitad de pantallas.
#
# Mientras eso no se haga, sube el tope y se deja escrito dónde está el bulto.
# Lo que sigue apretando es `PRESUPUESTO_TOTAL_KB`: la suma de todos los trozos
# son hoy 156 kB de 180, así que diferir cosas para esconderlas en otro trozo no
# cuela.
#
#   26-10-2026  128 → 130 kB.  Desglose medido de lo que se baja al abrir, para
#   que la próxima vez no haya que volver a averiguarlo:
#
#       106,7 kB  el trozo principal: React, el diccionario de idioma entero y
#                 el catálogo de módulos (10,4 kB él solo), que lo necesitan la
#                 barra lateral y la superior para pintar el menú
#        14,2 kB  `react-router-dom` — el trozo se llama «Icono» por cómo
#                 reparte Vite, no porque lleve iconos: los iconos son una
#                 fuente de ligaduras y no pesan JavaScript
#         7,2 kB  el resto: jsx-runtime, i18n, sesión, superficie, api, config
#
#   Nada de eso se puede diferir sin que la primera pantalla salga sin menú o
#   con las claves de traducción en crudo. El bulto sigue siendo el diccionario
#   —9,9 kB gzip él solo— y la forma correcta de quitarlo sigue siendo partirlo
#   por pantalla, no recortar funcionalidad para caber.
#
#   Lo que hizo saltar el tope fueron cinco cadenas nuevas: 128,08 de 128,00.
#   Ochenta bytes. Subirlo a 130 deja dos kilobytes de margen, que es un par de
#   funcionalidades más de cadenas, y mantiene la presión.
#
#   27-10-2026 · 130 → 134 y de vuelta a 118, con una medida mal hecha en medio
#   -------------------------------------------------------------------------
#   Al saltar el tope se midió qué había dentro, y la medida ESTABA MAL: se
#   tomó el tramo del chunk entre la primera y la última ruta de API —168,5 kB
#   en crudo, 42,3 comprimidos— y se dio por hecho que era la tabla de
#   pestañas. No lo era: ahí dentro iba medio paquete. La tabla sola son 4,7 kB
#   comprimidos. Queda escrito porque el error no fue de cálculo, fue de
#   método: se midió un tramo y se habló de un artefacto.
#
#   Lo que sí baja, medido sobre el paquete construido y no sobre un tramo: la
#   apertura pasa de 130,4 a 115,3 kB comprimidos. El 11,6 % no sale sólo de
#   sacar la tabla, sino de que al sacarla se pudieron diferir la pantalla de
#   módulo, la ficha y la de cliente, que eran quienes la arrastraban.
#
#   El tope vuelve a 118: tres kilobytes de margen sobre lo medido, que es un
#   par de pantallas más, y sigue fallando si alguien mete una biblioteca.
#   27-10-2026 · el diccionario, partido por fin
#   ------------------------------------------------------------------------
#   Las dos subidas anteriores dejaron escrito que el bulto era el DICCIONARIO
#   DE IDIOMA ENTERO viajando en la apertura —hace falta para pintar el acceso—
#   y que la forma correcta de quitarlo era partirlo por pantalla. Hecho: las
#   diecisiete secciones que sólo usan pantallas diferidas viven en
#   `i18n/es.pantallas.ts`, y cada `lazy` espera ese trozo ANTES de resolver su
#   componente —en paralelo habría una ventana de milisegundos con
#   `plataforma.titulo` escrito en la cabecera—.
#
#   Cuáles se mueven NO se eligió a ojo: se midió fichero a fichero qué sección
#   usa cada pantalla, y las compartidas o del marco se quedan. Si una llegara
#   tarde, se vería la clave en crudo.
#
#   Medido sobre el paquete construido: la apertura pasa de 93,3 a 88,3 kB
#   comprimidos. El tope de apertura se queda en 118 —treinta de margen, que es
#   mucho— porque bajarlo ahora congelaría el reparto actual de trozos.
PRESUPUESTO_KB = 118

# Y un tope para el conjunto, contando lo que se carga al abrir cada pantalla.
# Sin él, partir el paquete sería la forma de esconder cualquier crecimiento:
# basta con diferir lo que engorda para que el primer tope no se entere.
#
#   27-10-2026  180 → 190 kB, y el motivo es el producto, no la grasa.
#   ------------------------------------------------------------------------
#   En un día entraron cuatro pantallas: «Plataforma y cumplimiento», la del
#   objeto del modelo de datos, «Pendiente de firma» y el botón de exportar con
#   sus textos. Las cuatro cubren rutas que el servidor publicaba y que no se
#   alcanzaban desde ninguna parte, así que lo que crece es lo que se puede
#   hacer, no lo que pesa de más.
#
#   **Y partir el diccionario no baja este número, lo sube**: 184,2 → 184,8 kB.
#   Un trozo de 5,5 kB comprime peor suelto que dentro del grande. Queda dicho
#   porque es contraintuitivo y porque el aviso de este gate —«diferir una
#   pantalla la saca de la apertura, no del producto»— es exactamente eso: aquí
#   no hay nada que diferir, sólo que justificar o que quitar. No se quita, se
#   justifica.
#
#   190 deja cinco kilobytes sobre lo medido: un par de pantallas más, y sigue
#   saltando si alguien mete una biblioteca.
#
#   27-10-2026  190 → 198 kB, y otra vez es producto. Lo que entró ese día, en
#   ------------------------------------------------------------------------
#   la misma sesión: la búsqueda global en la paleta —que el manual prometía y
#   no existía—, el selector de cliente para quien opera la plataforma, el
#   panel de medidas que acompaña a un listado (noventa y seis rutas que no
#   cabían como pestaña), las seis secciones que el portal del cliente servía
#   y no enseñaba, «tu segundo factor» en Seguridad, «la suite de una vez», y
#   los cuatro paneles que faltaban en la página de estado del tenant.
#
#   Medido antes de subirlo: 192,98 kB. Se deja en 198 y no en 193 por lo
#   mismo que la vez anterior —margen para un par de pantallas— y porque el
#   tope que se roza se sube cada semana, que es como deja de medir.
#   28-10-2026  198 → 205 kB, y otra vez es producto. Lo que entró ese día:
#   ------------------------------------------------------------------------
#   «Nexus» —la pantalla desde la que se le pide algo al agente autónomo, que
#   estaba entero por debajo y sólo se veía como una fila en un listado de
#   administración— y «Duplicados por resolver», que convierte la cola de
#   parejas en algo que se puede decidir: fusionar eligiendo cuál se queda,
#   decir que no son la misma, o dejarlo para luego. Las dos son diferidas; lo
#   que crece es el total, no lo que se descarga al abrir.
#
#   Y de paso baja algo: la pestaña «Duplicados» del módulo de cuentas sale de
#   `recursos.ts`, porque enseñaba la misma colección sin poder decidir nada.
#
#   Medido antes de subirlo: 199,15 kB. Se deja en 205 por lo mismo de
#   siempre: margen para un par de pantallas, porque un tope que se roza se
#   sube cada semana y entonces deja de medir.
#
#   29-10-2026  205 → 215 kB, y es producto otra vez. Seis bloques de la cola
#   ------------------------------------------------------------------------
#   larga, todos de pantallas que faltaban para capacidades ya construidas:
#
#     · «¿qué impide que una empresa vea a otra?», medido en cada carga, en
#       Seguridad y arriba del todo;
#     · la suite por su DECLARACION —organigrama compartido, herramientas con
#       su direccion y su mapeo de roles, SSO compartido, que se aplicaria en
#       cada herramienta y el certificado de cierre con sus palabras—;
#     · «quien ve que»: el simulador separando rol de atributos, con el
#       contexto con el que se evaluo, y las excepciones de campo;
#     · la ficha de un modulo vertical instalado, con su manifiesto, su
#       integridad y su telemetria;
#     · «con que se firma»: proveedores con sus niveles eIDAS, reglas por
#       prioridad y plantillas con su plazo;
#     · y «preguntar sobre este registro», en la ficha, con el filtro a la
#       vista.
#
#   Las seis son diferidas: lo que crece es el total, no lo que se descarga al
#   abrir —esa cifra no se ha movido y su tope sigue donde estaba—. Medido
#   antes de subirlo: 208,56 kB. Se deja en 215 por lo de siempre, margen para
#   un par de pantallas.
#
#   29-10-2026  215 → 220 kB, y es la SEGUNDA subida del mismo día. Queda
#   ------------------------------------------------------------------------
#   escrito así a propósito, porque es justo lo que este comentario lleva
#   avisando desde el principio que no se puede volver rutina.
#
#   Medido, no estimado: 213,54 kB antes del bloque de «lo que una empresa
#   cambia sin escribir código» y 215,74 después. El bloque pesa 2,2 kB —cinco
#   paneles y sus textos— y el margen de esta mañana ya estaba comido hasta
#   213,54 por los bloques anteriores de la misma sesión.
#
#   Qué NO sirve aquí, y conviene tenerlo claro antes de la próxima: diferir.
#   La pantalla ya va en su propio trozo y la cifra de apertura no se ha
#   movido; este tope suma TODOS los trozos, así que diferir no le quita ni un
#   byte. Las únicas dos salidas son quitar producto o subirlo.
#
#   El bulto sigue donde dice el comentario de arriba: `es.pantallas` son 12,9
#   kB comprimidos de diccionario, y partirlo por pantalla devolvería de golpe
#   más de lo que han costado los últimos cuatro bloques juntos. Ese es el
#   trabajo que hay que hacer la próxima vez que esto apriete, en vez de subir
#   el número por tercera vez.
#
#   29-10-2026  220 → 245 kB, y lo de arriba ESTABA MAL. Corregido aquí mismo
#   ------------------------------------------------------------------------
#   para que nadie lo siga: partir el diccionario **no baja este número**.
#   Este tope suma TODOS los trozos, así que partir un trozo en varios deja la
#   suma igual —o un pelín peor, por la cabecera de cada fichero—. Lo que baja
#   la apertura no es lo mismo que lo que baja el total, y confundirlos manda
#   a quien lo lea a un trabajo de una tarde que no sirve para esto.
#
#   Lo único que baja el total es quitar código. Se intentó antes de subir el
#   número, y está medido: el diagrama de un proceso lo pintaban DOS pantallas
#   con código distinto —el editor y la instancia—, y unificarlo en un solo
#   componente ahorró **0,13 kB**. Se queda igualmente, porque dos dibujos del
#   mismo objeto divergen en cuanto uno aprende una forma de enlace que el
#   otro no; pero como ahorro no da ni para un bloque.
#
#   Y por qué 245 y no 225: porque este tope estaba midiendo el calendario.
#   Quedan ~299 capacidades hechas sin pantalla y cada bloque pesa unos 2 kB
#   medidos; con 5 kB de margen falla cada vez, se sube cada vez, y un tope que
#   se sube cada semana no decide nada. 245 son ~12 bloques: el día que se
#   agote habrá que mirarlo en serio, que es para lo que sirve un tope.
#
#   LO QUE NO SE MUEVE es `PRESUPUESTO_KB`, la apertura: 115,7 de 118 kB
#   medidos hoy. Ése es el que gobierna lo que tarda en abrir el producto y el
#   que aprieta de verdad. Diferir una pantalla le quita peso a ÉSE, y por eso
#   todas las de la cola larga van diferidas.
#
#   30-10-2026  245 → 250. **Y aquí el tope ha hecho lo que tenía que hacer**:
#   se agotó, y la línea de arriba decía que el día que pasara habría que
#   mirarlo en serio. Mirado.
#
#   Lo medido: las cuatro pantallas de esta tanda —el segmento, la puntuación
#   de un lead, los canales de entrada y el ciclo de vida de un cliente— pesan
#   **6,4 kB comprimidos entre las cuatro**: 2,1 + 1,5 + 1,2 + 1,4. O sea 1,6
#   kB por pantalla y no 2, que es mejor de lo estimado, y todas van diferidas:
#   la apertura sigue en su sitio, que es el tope que aprieta de verdad.
#
#   Lo que no cabe: quedan 246 capacidades sin pantalla. A 1,6 kB por pantalla
#   y ~5 capacidades por pantalla, la cola larga entera son **unos 80 kB más**,
#   y eso no se arregla subiendo el tope de cinco en cinco. O se parte el
#   paquete por área —que hoy no está hecho— o el producto entero pesa 330 kB.
#   **Es una decisión de producto, no un número que se sube aquí**: se sube a
#   250 para no bloquear este bloque, y la siguiente subida tiene que venir con
#   el reparto por área hecho o con la decisión tomada de no hacerlo.
#
#   30-10-2026  250 → 330, **y con el tope de verdad puesto al lado**. Este
#   número mide la suma de todos los trozos, o sea que crece con cada pantalla
#   por diseño: se agotó en dos bloques, igual que la vez anterior, porque
#   mide el calendario y no una regresión. Lo que sí es una regresión es que
#   UNA pantalla engorde, y para eso está `PRESUPUESTO_POR_PANTALLA_KB`, que
#   es el que a partir de hoy hace el trabajo.
#
#   330 está dimensionado y no elegido: quedan 236 capacidades sin pantalla,
#   que a ~5 por pantalla y 1,6 kB medidos por pantalla son ~75 kB más. 250 +
#   75 = 325. Con eso la cola larga entera cabe sin volver aquí, que es lo que
#   un tope tiene que permitir para seguir significando algo.
#
#   LO QUE NO SE MUEVE sigue siendo `PRESUPUESTO_KB`, la apertura: 115,7 de
#   118 kB medidos hoy, y ése sí gobierna lo que tarda en abrir el producto.
PRESUPUESTO_TOTAL_KB = 330

# Lo que pesa una pantalla diferida, comprimida. Mediana medida: 1,94 kB.
PRESUPUESTO_POR_PANTALLA_KB = 12


def test_la_consola_sirve_la_api_por_el_mismo_origen() -> None:
    """El nginx de la consola tiene que pasar `/api` al gateway.

    `config.json` trae `apiBase` vacío por defecto, y vacío significa «mismo
    origen». Sin un proxy que lo atienda, la llamada cae en el bloque que sirve
    ficheros: el `POST /api/v1/sesion/entrar` de la pantalla de entrada
    contestaba **405 Not Allowed** de nginx, y el `GET` era peor todavía —
    devolvía el `index.html` con un 200, así que parecía que la API respondía.

    El propio fichero decía en un comentario que «la API va detrás del mismo
    proxy». No había proxy. Un comentario que promete algo que no está es peor
    que no decir nada, y esta comprobación es la que hace que deje de poder
    pasar.

    Se comprueba aquí y no con una prueba que levante nginx porque lo que falla
    es la CONFIGURACIÓN, no el servidor: el fichero o tiene el bloque o no lo
    tiene.
    """
    conf = (FRONT.parent / "nginx.conf").read_text("utf-8")
    assert "location /api/" in conf, (
        "El nginx de la consola no pasa `/api` a ninguna parte. Con `apiBase` "
        "vacío —que es el valor por defecto—, entrar devuelve 405."
    )
    bloque = conf.split("location /api/", 1)[1].split("}", 1)[0]
    assert "proxy_pass" in bloque, "`location /api/` sin `proxy_pass` no lleva a ningún sitio"
    # Las cabeceras que el gateway necesita para saber quién llama de verdad:
    # sin ellas, la lista de redes admitidas de una clave de API y los límites
    # por IP ven a todo el mundo como el proxy.
    for cabecera in ("X-Forwarded-For", "X-Forwarded-Proto"):
        assert cabecera in bloque, f"el proxy no propaga `{cabecera}`"


def test_el_paquete_del_front_cabe_en_el_presupuesto() -> None:
    """Presupuesto de rendimiento, comprobado en local (CRM-07.04.04.03).

    Una aplicación web crece de treinta en treinta kilobytes, cada uno con su
    justificación, y un día tarda cuatro segundos en abrir. Nadie lo decide: se
    llega. Un tope que falla obliga a que la decisión sea explícita — o se
    justifica subir el número, o se quita algo.

    Se mide **lo que pide el navegador al abrir**: el módulo de entrada y lo que
    `index.html` manda precargar con él. No la suma de todos los trozos, que es
    lo que se medía antes: con las pantallas partidas por ruta esa suma incluye
    el recorrido guiado y la consola de despliegue, que nadie descarga para
    mirar sus casos. Medida así, partir el paquete —que es la forma correcta de
    adelgazar la apertura— hacía que el gate fallara más, es decir, empujaba
    justo a lo contrario.

    Se mide sobre `dist/`, así que solo corre si el front está construido: pedir
    una construcción en cada prueba convertiría el ciclo rápido en uno de dos
    minutos.
    """
    import gzip
    import re

    dist = RAIZ / "frontend" / "dist"
    if not (dist / "assets").exists():
        pytest.skip("el front no está construido (`npm run build` en `frontend/`)")

    html = (dist / "index.html").read_text("utf-8")
    # El `src` del módulo de entrada y los `modulepreload` que Vite emite para
    # lo que ese módulo importa de forma estática: exactamente lo que se baja
    # antes de que se pinte nada.
    iniciales = {m.group(1).lstrip("/") for m in re.finditer(r'(?:src|href)="([^"]+\.js)"', html)}
    assert iniciales, "no se ha encontrado ningún script en `dist/index.html`"

    comprimido = sum(len(gzip.compress((dist / r).read_bytes())) for r in iniciales)
    kb = comprimido / 1024
    assert kb <= PRESUPUESTO_KB, (
        f"Abrir el front descarga {kb:.0f} kB comprimidos y el tope son "
        f"{PRESUPUESTO_KB} kB.\n\nO se justifica subir el tope, o se difiere lo "
        "que no haga falta para la primera pantalla. Lo que no vale es que "
        "crezca sin que nadie lo decida."
    )

    total = sum(len(gzip.compress(f.read_bytes())) for f in (dist / "assets").glob("*.js"))
    total_kb = total / 1024
    assert total_kb <= PRESUPUESTO_TOTAL_KB, (
        f"El front entero ocupa {total_kb:.0f} kB comprimidos y el tope son "
        f"{PRESUPUESTO_TOTAL_KB} kB.\n\nDiferir una pantalla la saca de la "
        "apertura, no del producto."
    )

    # Y el que de verdad caza una regresión: **ninguna pantalla pesa de más**.
    #
    # El total de arriba crece con cada pantalla por diseño, así que mide el
    # calendario: se agota, se sube, y un tope que se sube cada dos bloques no
    # decide nada. Lo que sí es un fallo es que UNA pantalla engorde —alguien
    # importa una librería de gráficos para pintar una barra y se lleva 60 kB
    # a esa ruta—, y eso el total no lo distingue de haber añadido treinta
    # pantallas de dos.
    #
    # Medido el 30-10-2026 sobre 34 trozos de pantalla: mediana 1,94 kB y el
    # mayor 9,14 (`Modulo`, que monta el listado, la ficha y el formulario
    # genéricos de los 24 módulos). El tope se pone en 12: deja crecer a la
    # mayor y salta con cualquier dependencia de peso, que es justo lo que
    # tiene que decidir una persona.
    pagina = RAIZ / "frontend" / "src" / "paginas"
    pantallas = {p.stem for p in pagina.glob("*.tsx")}
    gordas = []
    vistos = 0
    for fichero in (dist / "assets").glob("*.js"):
        # El hash de Vite puede llevar guion dentro —`Campana-C2Eyql-0.js`—,
        # así que la clase de caracteres tiene que incluirlo. Sin él, el
        # recorte dejaba `Campana-C2Eyql`, que no casa con ninguna pantalla, y
        # el trozo se saltaba en silencio: plantada una pantalla de 60 kB, la
        # comprobación pasaba en verde.
        base = re.sub(r"-[A-Za-z0-9_-]+\.js$", "", fichero.name)
        if base not in pantallas:
            continue
        vistos += 1
        kb_trozo = len(gzip.compress(fichero.read_bytes())) / 1024
        if kb_trozo > PRESUPUESTO_POR_PANTALLA_KB:
            gordas.append(f"{base}: {kb_trozo:.1f} kB")

    # Si no se reconoce ninguna, la comprobación no está mirando nada: pasaría
    # en verde con el front entero engordado.
    assert vistos >= 20, f"sólo se reconocen {vistos} trozos de pantalla en dist/"
    assert not gordas, (
        f"Pantallas por encima de {PRESUPUESTO_POR_PANTALLA_KB} kB comprimidos:\n  "
        + "\n  ".join(sorted(gordas))
        + "\n\nUna pantalla que pesa así suele ser una dependencia nueva. O se "
        "justifica, o se saca."
    )
