"""Una pantalla no puede leer un campo que su ruta no devuelve.

El trinquete de al lado —`test_la_pantalla_no_lee_campos_que_nadie_envia`—
exige que cada contrato que una pantalla da por bueno esté **recorrido por una
prueba de servidor**, y dice en su cabecera que resolver «ruta → claves que
devuelve» era un proyecto aparte. Esto es ese proyecto, y hacía falta: las
cuatro roturas de abajo tenían las dos cosas, prueba de servidor y ruta
correcta, y seguían rotas porque el nombre del campo no coincidía.

Medido el 29-10-2026, cuatro pantallas en producción:

  · **marketing** pintaba `tipo`, `miembros` y `calculado_at` de cada segmento;
    la API devuelve `dinamico`, `tamano` y `tamano_at`. Y de cada campaña,
    `miembros`, `enviados` y `respuestas`: ninguno de los tres es una columna de
    la campaña. Seis campos inventados en una pantalla;
  · **conocimiento** listaba artículos por `titulo`, y el título no es una
    columna del artículo —vive en `versiones_articulo`—. La lista salía sin
    nombres, y al escribir en el buscador `a.titulo.toLowerCase()` tumbaba la
    pantalla entera;
  · **territorios** contaba `criterios` de cada territorio y el listado no los
    devolvía: decía «0 criterios» en todos, incluido el que reparte media
    cartera. El `?? 0` que lo protegía de caerse es lo que lo escondía;
  · **la ficha de una oportunidad** declaraba `tipo` en sus líneas, y la API
    manda `tipo_ingreso`.

**Por qué el trinquete anterior no las vio.** Ninguna de las cuatro usaba
`llamar<Tipo>(…)`. Usaban `llamar<unknown>(…)` y le ponían la forma después,
con `filas<Tipo>(r.datos)` — veintiuna rutas de diez pantallas por ahí. Eso se
ha cerrado por construcción con `listar<T>()`, que lleva la ruta y la forma en
la misma llamada.

**Lo que esta prueba NO hace.** No adivina. Resuelve las claves de una ruta sólo por
caminos exactos —el modelo de un listado genérico con sus agregados y sus
extras declarados, el esquema de salida, la proyección, el diccionario literal
del manejador, o un salto de delegación a una función con nombre— y lo que no
cae en ninguno lo cuenta y lo deja fuera en vez de inventarse un veredicto.

Medido: **523 rutas resueltas y 125 contratos de pantalla, con 26 puntos
ciegos**. Las tres cifras se comprueban, porque un resolutor que
dejara de ver el servidor pasaría en verde sin mirar nada. Se ha plantado: con
`_ficheros()` devolviendo la lista vacía, dos de las tres pruebas se ponen
rojas.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[2]
PANTALLAS = RAIZ / "frontend" / "src" / "paginas"
SERVICIOS = RAIZ / "services"
COMPARTIDO = RAIZ / "packages" / "crmcore" / "crmcore"
PREFIJO = "/api/v1"


def _ficheros() -> list[Path]:
    """Dónde vive el servidor: los servicios y el paquete común.

    El común hace falta: la papelera, el rastro, el cumplimiento, el volumen y
    la restauración los publica un router compartido que monta cada servicio,
    así que sin mirar ahí esas rutas quedaban ciegas en los trece.
    """
    return sorted(SERVICIOS.rglob("*.py")) + sorted(COMPARTIDO.rglob("*.py"))


# Las llamadas que declaran la forma de lo que leen.
RE_TIPADA = re.compile(
    r'\b(?:listar|listarPagina|llamar)<([^<>(]+?)>\(\s*[`"\']([^`"\']+)',
)
RE_INTERFAZ = re.compile(r"^(?:export )?interface (\w+) \{\n(.*?)^\}", re.S | re.M)
# Un campo obligatorio: sin `?`. Los opcionales dicen ya que pueden no venir.
RE_CAMPO_OBLIGATORIO = re.compile(r"^  (\w+)(\??):", re.M)


def _normalizar(ruta: str) -> str:
    """`/api/v1/casos/${id}/x?a=1` → `/api/v1/casos/{}/x`."""
    return re.sub(r"\$\{[^}]*\}|\{[^}]*\}", "{}", ruta.split("?")[0]).rstrip("/")


def _interfaces(texto: str) -> dict[str, set[str]]:
    salida: dict[str, set[str]] = {}
    for m in RE_INTERFAZ.finditer(texto):
        salida[m.group(1)] = {
            nombre for nombre, opcional in RE_CAMPO_OBLIGATORIO.findall(m.group(2)) if not opcional
        }
    return salida


RE_CONSTANTE = re.compile(r'^const (\w+) = "([^"]+)";', re.M)


def _texto_de_la_llamada(texto: str, desde: int) -> str:
    """El texto de una llamada, de su `(` a su `)`, contando paréntesis.

    Hace falta para saber si lleva `metodo:`. Mirar los N caracteres
    siguientes no vale: una llamada con un cuerpo largo deja el `metodo` fuera
    de la ventana y la llamada pasa por GET.
    """
    abre = texto.find("(", desde)
    if abre < 0:
        return ""
    profundidad = 0
    for i in range(abre, len(texto)):
        if texto[i] == "(":
            profundidad += 1
        elif texto[i] == ")":
            profundidad -= 1
            if profundidad == 0:
                return texto[abre : i + 1]
    return texto[abre:]


def contratos_de_las_pantallas() -> list[tuple[str, str, str, set[str]]]:
    """(pantalla, ruta, tipo, campos obligatorios que la pantalla espera)."""
    salida: list[tuple[str, str, str, set[str]]] = []
    for fichero in sorted(PANTALLAS.glob("*.tsx")):
        texto = fichero.read_text(encoding="utf-8")
        declaradas = _interfaces(texto)
        # Una pantalla puede guardar la ruta en una constante —`${COLA}`—, y
        # sin resolverla la ruta se normaliza a `{}` y no casa con nada.
        constantes = dict(RE_CONSTANTE.findall(texto))
        for encaje in RE_TIPADA.finditer(texto):
            # Sólo las lecturas: el servidor se resuelve por GET, y comparar un
            # POST contra la forma del GET de la misma ruta es comparar dos
            # respuestas distintas.
            if "metodo:" in _texto_de_la_llamada(texto, encaje.start()):
                continue
            tipo, ruta = encaje.group(1), encaje.group(2)
            for nombre_const, valor in constantes.items():
                ruta = ruta.replace("${" + nombre_const + "}", valor)
            nombre = tipo.strip().removesuffix("[]").strip()
            campos = declaradas.get(nombre)
            if campos:
                salida.append((fichero.name, _normalizar(ruta), nombre, campos))
    return salida


# ── El servidor: qué claves devuelve cada ruta ────────────────────────────


def _texto(nodo: Any) -> str | None:
    return nodo.value if isinstance(nodo, ast.Constant) and isinstance(nodo.value, str) else None


def _nombre(nodo: Any) -> str | None:
    if isinstance(nodo, ast.Name):
        return nodo.id
    if isinstance(nodo, ast.Attribute):
        return nodo.attr
    return None


def _columnas_de_los_modelos() -> dict[str, set[str]]:
    """Clase → columnas. `x: Mapped[…] = mapped_column(…)` y nada más.

    Las columnas son lo que un listado genérico devuelve de cada fila, así que
    se leen del mismo sitio del que salen: la declaración del modelo.

    **Con las de sus bases.** `id` no lo declara ninguna entidad: lo pone
    `EntidadBase`, igual que `created_at` lo pone `TimestampMixin`. Sin
    heredarlas, el resolutor decía que `/accounts` no devuelve `id`.
    """
    propias: dict[str, set[str]] = {}
    bases: dict[str, list[str]] = {}
    for fichero in _ficheros():
        try:
            arbol = ast.parse(fichero.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - un fichero roto lo caza otro gate
            continue
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, ast.ClassDef):
                continue
            campos = {
                hijo.target.id
                for hijo in nodo.body
                if isinstance(hijo, ast.AnnAssign)
                and isinstance(hijo.target, ast.Name)
                and "Mapped" in ast.dump(hijo.annotation)
            }
            propias.setdefault(nodo.name, set()).update(campos)
            bases.setdefault(nodo.name, []).extend(b for b in (_nombre(x) for x in nodo.bases) if b)

    def _con_bases(nombre: str, vistos: frozenset[str]) -> set[str]:
        if nombre in vistos:  # herencia circular: no se cuelga, se corta
            return set()
        campos = set(propias.get(nombre, set()))
        for base in bases.get(nombre, []):
            campos |= _con_bases(base, vistos | {nombre})
        return campos

    resueltas = {nombre: _con_bases(nombre, frozenset()) for nombre in propias}
    return {nombre: campos for nombre, campos in resueltas.items() if campos}


def _campos_de_los_esquemas() -> dict[str, set[str]]:
    """Clase Pydantic → sus campos. Es lo que publica un `response_model`."""
    salida: dict[str, set[str]] = {}
    for fichero in _ficheros():
        try:
            arbol = ast.parse(fichero.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, ast.ClassDef):
                continue
            bases = {_nombre(b) for b in nodo.bases}
            if "BaseModel" not in bases and not (bases & set(salida)):
                continue
            campos = {
                hijo.target.id
                for hijo in nodo.body
                if isinstance(hijo, ast.AnnAssign) and isinstance(hijo.target, ast.Name)
            }
            # Hereda de otro esquema ya visto: los campos del padre también salen.
            for base in bases:
                campos |= salida.get(base or "", set())
            if campos:
                salida.setdefault(nodo.name, set()).update(campos)
    return salida


def _rollups_declarados() -> dict[str, set[str]]:
    """Objeto → nombres de sus agregados, que el listado pega a cada fila."""
    salida: dict[str, set[str]] = {}
    for fichero in _ficheros():
        try:
            arbol = ast.parse(fichero.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        for nodo in ast.walk(arbol):
            if not (isinstance(nodo, ast.Call) and _nombre(nodo.func) == "declarar"):
                continue
            if not nodo.args or _texto(nodo.args[0]) is None:
                continue
            objeto = _texto(nodo.args[0]) or ""
            for argumento in nodo.args[1:]:
                if isinstance(argumento, ast.Call) and _nombre(argumento.func) == "Rollup":
                    for clave in argumento.keywords:
                        if clave.arg == "nombre" and _texto(clave.value):
                            salida.setdefault(objeto, set()).add(_texto(clave.value) or "")
    return salida


def _returns_propios(funcion: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.Return]:
    """Los `return` de ESTA función, sin bajar a las que lleva dentro.

    Un manejador con una función auxiliar dentro —«pregunta a cada servicio y
    devuelve su trozo»— tiene los `return` de la auxiliar en su árbol, y
    contarlos hacía que el resolutor dijera que `/estado/consultas-degradadas`
    devuelve lo que devuelve el trozo, no la respuesta. Un contrato sano
    denunciado, que es la peor forma de fallar: manda a cambiar lo que estaba
    bien.
    """
    salida: list[ast.Return] = []

    def _bajar(nodo: ast.AST) -> None:
        for hijo in ast.iter_child_nodes(nodo):
            if isinstance(hijo, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            if isinstance(hijo, ast.Return):
                salida.append(hijo)
            _bajar(hijo)

    _bajar(funcion)
    return salida


def _claves_del_literal(
    funcion: ast.FunctionDef | ast.AsyncFunctionDef,
    contexto: dict[str, Any] | None = None,
) -> set[str] | None:
    """Las claves del diccionario que devuelve el manejador, si es literal.

    Sólo si **todos** sus `return` con valor son un diccionario literal —o una
    lista de uno—. Con uno solo que no lo sea no se sabe qué devuelve por el
    otro camino, y contestar a medias sería peor que no contestar.
    """
    claves: set[str] = set()
    visto = False
    for nodo in _returns_propios(funcion):
        if nodo.value is None:
            continue
        valor = nodo.value
        if isinstance(valor, (ast.ListComp, ast.GeneratorExp)):
            valor = valor.elt
        elif isinstance(valor, ast.List) and len(valor.elts) == 1:
            valor = valor.elts[0]
        elif isinstance(valor, ast.Call) and _nombre(valor.func) == "list" and valor.args:
            interior = valor.args[0]
            if isinstance(interior, (ast.ListComp, ast.GeneratorExp)):
                valor = interior.elt
        if not isinstance(valor, ast.Dict):
            return None
        for clave, hijo in zip(valor.keys, valor.values, strict=True):
            if clave is None:
                # `**algo()`: se sigue si es una llamada a una función con
                # nombre que devuelve un literal. `explicar()` mete así los
                # umbrales, y pararse aquí dejaba ciega la ruta que más forma
                # tiene de todo el scoring.
                suyas = (
                    _claves_del_literal(contexto[_nombre(hijo.func) or ""])
                    if contexto is not None
                    and isinstance(hijo, ast.Call)
                    and _nombre(hijo.func) in contexto
                    else None
                )
                if suyas is None:
                    return None
                claves |= suyas
                continue
            if _texto(clave) is None:
                return None
            claves.add(_texto(clave) or "")
        visto = True
    return claves if visto else None


def _claves_delegadas(
    funcion: ast.FunctionDef | ast.AsyncFunctionDef,
    locales: dict[str, Any],
    por_modulo: dict[str, dict[str, Any]],
    alias: dict[str, str],
) -> set[str] | None:
    """Las claves de aquello a lo que el manejador delega.

    Casi ningún manejador calcula: devuelve lo que le da el módulo de su
    servicio —`return seg.tamano(db, …)`—, y pararse en el manejador dejaba
    ciego al resolutor justo en las rutas que más forma tienen.

    **Sólo se sigue lo que de verdad es una delegación**: una función del mismo
    fichero, o una de un módulo importado con nombre. Un `x.metodo(…)` sobre
    una variable local NO se sigue, y eso no es prudencia de más: buscando por
    el nombre del atributo, `pagina.a_dict(…)` del listado de cuentas casaba
    con `a_dict()` de previsión —otro servicio, otra cosa— y el resolutor
    contestaba que `/accounts` devuelve «compromiso» y «ponderado». Una
    respuesta equivocada aquí es peor que ninguna: aprueba un contrato roto, y
    denuncia uno sano.

    Y sólo si **todos** sus `return` con valor delegan y todos resuelven: uno
    que no resuelva deja el conjunto incompleto, y un conjunto incompleto
    convierte un campo que sí viene en un falso positivo.
    """
    claves: set[str] = set()
    visto = False
    for nodo in _returns_propios(funcion):
        if nodo.value is None:
            continue
        valor = nodo.value
        if isinstance(valor, ast.Await):
            valor = valor.value
        if isinstance(valor, (ast.ListComp, ast.GeneratorExp)):
            valor = valor.elt
        if not isinstance(valor, ast.Call):
            return None

        destino = None
        vecinas: dict[str, Any] = locales
        if isinstance(valor.func, ast.Name):
            destino = locales.get(valor.func.id)
        elif isinstance(valor.func, ast.Attribute) and isinstance(valor.func.value, ast.Name):
            modulo = alias.get(valor.func.value.id)
            if modulo is not None:
                destino = por_modulo.get(modulo, {}).get(valor.func.attr)
                # Las vecinas de la función de destino son las de SU módulo:
                # un `**_lo_que_decide(…)` dentro se resuelve ahí, no aquí.
                vecinas = por_modulo.get(modulo, {})
        if destino is None:
            return None

        suyas = _claves_del_literal(destino, vecinas)
        if suyas is None:
            return None
        claves |= suyas
        visto = True
    return claves if visto else None


def _funciones_por_modulo() -> dict[str, dict[str, Any]]:
    """`services.x.y` → {nombre de función: su nodo}.

    Por módulo y no por nombre suelto: el mismo nombre existe en varios
    servicios y resolver por nombre es cómo el resolutor acabó diciendo que el
    listado de cuentas devuelve una previsión.
    """
    salida: dict[str, dict[str, Any]] = {}
    for fichero in _ficheros():
        try:
            arbol = ast.parse(fichero.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        modulo = ".".join(fichero.relative_to(RAIZ).with_suffix("").parts)
        salida[modulo] = {
            nodo.name: nodo
            for nodo in arbol.body
            if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
    return salida


def _alias_de_modulos(arbol: ast.Module) -> dict[str, str]:
    """`from services.marketing import segmentos as seg` → {"seg": "services.marketing.segmentos"}."""
    alias: dict[str, str] = {}
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.ImportFrom) and (nodo.module or "").startswith("services"):
            for nombre in nodo.names:
                alias[nombre.asname or nombre.name] = f"{nodo.module}.{nombre.name}"
        elif isinstance(nodo, ast.Import):
            for nombre in nodo.names:
                if nombre.name.startswith("services"):
                    alias[nombre.asname or nombre.name] = nombre.name
    return alias


def claves_por_ruta() -> tuple[dict[str, set[str]], set[str]]:
    """Ruta → claves que puede devolver, y las rutas que no se han podido resolver."""
    columnas = _columnas_de_los_modelos()
    esquemas = _campos_de_los_esquemas()
    rollups = _rollups_declarados()
    por_modulo = _funciones_por_modulo()

    resueltas: dict[str, set[str]] = {}
    sin_resolver: set[str] = set()

    for fichero in _ficheros():
        try:
            arbol = ast.parse(fichero.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue

        alias = _alias_de_modulos(arbol)
        locales = {
            nodo.name: nodo
            for nodo in arbol.body
            if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

        # Los prefijos de los routers de este fichero.
        prefijos: dict[str, str] = {}
        for nodo in ast.walk(arbol):
            if (
                isinstance(nodo, ast.Assign)
                and isinstance(nodo.value, ast.Call)
                and _nombre(nodo.value.func) == "APIRouter"
                and len(nodo.targets) == 1
                and isinstance(nodo.targets[0], ast.Name)
            ):
                # Un router sin `prefix` cuelga directamente de `/api/v1`, y
                # es donde vive media pantalla de estado. Saltárselo dejaba sin
                # resolver sus rutas y, peor, le dejaba la forma de la ruta del
                # mismo nombre que publica cada servicio: la del gateway junta
                # los trece y la de un servicio devuelve sólo lo suyo.
                prefijos[nodo.targets[0].id] = ""
                for clave in nodo.value.keywords:
                    if clave.arg != "prefix":
                        continue
                    # Los routers compartidos componen su prefijo con el nombre
                    # del servicio: `f"/{nombre}/rastro"`. Esa parte es
                    # exactamente el `{}` que el front escribe con `${servicio}`.
                    if isinstance(clave.value, ast.JoinedStr):
                        prefijos[nodo.targets[0].id] = "".join(
                            _texto(t) or "{}" for t in clave.value.values
                        )
                    elif _texto(clave.value) is not None:
                        prefijos[nodo.targets[0].id] = _texto(clave.value) or ""

        # Listados genéricos: las claves son las columnas del modelo.
        for nodo in ast.walk(arbol):
            if not (isinstance(nodo, ast.Call) and _nombre(nodo.func) == "montar_listado"):
                continue
            router = _nombre(nodo.args[0]) if nodo.args else None
            datos = {c.arg: c for c in nodo.keywords}
            modelo = _nombre(datos["modelo"].value) if "modelo" in datos else None
            if router not in prefijos or modelo not in columnas:
                continue
            objeto = _texto(datos["objeto"].value) if "objeto" in datos else ""
            ruta = (_texto(datos["ruta"].value) if "ruta" in datos else "") or ""
            extras = set()
            if "extras_declara" in datos and isinstance(
                datos["extras_declara"].value, (ast.Tuple, ast.List)
            ):
                extras = {_texto(e) or "" for e in datos["extras_declara"].value.elts if _texto(e)}
            completa = _normalizar(f"{PREFIJO}{prefijos[router]}{ruta}")
            resueltas.setdefault(completa, set()).update(
                columnas[modelo] | rollups.get(objeto or "", set()) | extras
            )

        # Fichas genéricas: la misma fila que el listado, por su id.
        for nodo in ast.walk(arbol):
            if not (isinstance(nodo, ast.Call) and _nombre(nodo.func) == "montar_ficha"):
                continue
            router = _nombre(nodo.args[0]) if nodo.args else None
            datos = {c.arg: c for c in nodo.keywords}
            modelo = _nombre(datos["modelo"].value) if "modelo" in datos else None
            if router not in prefijos or modelo not in columnas:
                continue
            objeto = _texto(datos["objeto"].value) if "objeto" in datos else ""
            completa = _normalizar(f"{PREFIJO}{prefijos[router]}/{{}}")
            resueltas.setdefault(completa, set()).update(
                columnas[modelo] | rollups.get(objeto or "", set())
            )

        # Rutas escritas a mano.
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorador in nodo.decorator_list:
                if not (
                    isinstance(decorador, ast.Call) and isinstance(decorador.func, ast.Attribute)
                ):
                    continue
                # Sólo GET. Mezclar el POST de crear con el GET de listar
                # —misma ruta, respuestas distintas— hacía que el contrato de
                # `/casos` se resolviera con la forma de «caso creado», que no
                # tiene ni asunto ni estado: cuatro contratos sanos denunciados
                # y, peor, una ruta sin resolver que parecía resuelta.
                if decorador.func.attr != "get":
                    continue
                router = _nombre(decorador.func.value)
                if router not in prefijos:
                    continue
                camino = _texto(decorador.args[0]) if decorador.args else ""
                if camino is None:
                    continue
                completa = _normalizar(f"{PREFIJO}{prefijos[router]}{camino}")

                # El sobre y la fila **se suman**, no se eligen: una pantalla
                # puede tipar la página entera —para mirar `siguiente`— o la
                # fila, porque `filas()` desenvuelve. Resolver sólo el sobre
                # denunciaba diez contratos sanos: `PaginaDeListado` no tiene
                # ni `nombre` ni `email`, y por ahí pasan todos los listados.
                claves: set[str] | None = None
                for clave in decorador.keywords:
                    if clave.arg == "response_model":
                        nombre = _nombre(clave.value)
                        if nombre is None and isinstance(clave.value, ast.Subscript):
                            nombre = _nombre(clave.value.slice)
                        if nombre in esquemas:
                            claves = set(esquemas[nombre])
                de_la_fila: set[str] | None = None
                if True:
                    for llamada in ast.walk(nodo):
                        if not isinstance(llamada, ast.Call):
                            continue
                        for clave in llamada.keywords:
                            if clave.arg == "modelo_salida" and _nombre(clave.value) in esquemas:
                                de_la_fila = set(esquemas[_nombre(clave.value) or ""])
                            # La fila la arma una lambda con el diccionario
                            # delante: es tan exacto como un literal.
                            if clave.arg == "fila_a_dict" and isinstance(clave.value, ast.Lambda):
                                if isinstance(clave.value.body, ast.Dict) and all(
                                    _texto(k) for k in clave.value.body.keys
                                ):
                                    de_la_fila = {_texto(k) or "" for k in clave.value.body.keys}
                        # Y el listado que serializa con un esquema de salida lo
                        # dice en la proyección: `proyectar_con_esquema(…, XOut)`.
                        if _nombre(llamada.func) == "proyectar_con_esquema":
                            for argumento in llamada.args:
                                if _nombre(argumento) in esquemas:
                                    de_la_fila = set(esquemas[_nombre(argumento) or ""])
                        # `XOut(…).model_dump()`: la fila la arma el esquema.
                        if (
                            isinstance(llamada.func, ast.Attribute)
                            and llamada.func.attr == "model_dump"
                            and isinstance(llamada.func.value, ast.Call)
                            and _nombre(llamada.func.value.func) in esquemas
                        ):
                            de_la_fila = set(esquemas[_nombre(llamada.func.value.func) or ""])
                        # `proyectar_para(…, modelo=M)`: la fila son las
                        # columnas de M, recortadas por la política de acceso.
                        if _nombre(llamada.func) == "proyectar_para":
                            for clave in llamada.keywords:
                                if clave.arg == "modelo" and _nombre(clave.value) in columnas:
                                    de_la_fila = set(columnas[_nombre(clave.value) or ""])
                if claves is None:
                    claves = _claves_del_literal(nodo)
                if claves is None:
                    claves = _claves_delegadas(nodo, locales, por_modulo, alias)
                if claves is None and de_la_fila is None:
                    sin_resolver.add(completa)
                else:
                    resueltas.setdefault(completa, set()).update(
                        (claves or set()) | (de_la_fila or set())
                    )

    return resueltas, sin_resolver - set(resueltas)


# ── Las pruebas ───────────────────────────────────────────────────────────
#
# El tope sólo baja, y cada bajada va en el mismo commit que la arregla.
#
#   29-10-2026  4 pantallas  medido por primera vez. Marketing (segmentos y
#                            campañas), conocimiento, territorios y la ficha de
#                            una oportunidad. Las cuatro arregladas en el mismo
#                            commit, así que el tope nace en cero.
TOPE_CONTRATOS_ROTOS = 0

# Rutas que una pantalla tipa y cuya forma no se resuelve por ninguno de los
# caminos exactos. Son el punto ciego, y se cuentan para que no crezca.
#
# No se resuelven porque su manejador compone la respuesta con dos saltos de
# delegación o montando el diccionario por partes. Perseguirlas de una en una
# no vale la pena: cada camino nuevo que se añadió aquí acertó de lleno hasta
# que uno falló, y un resolutor que contesta mal es peor que uno que calla —el
# de `pagina.a_dict` dijo que `/accounts` devuelve una previsión, y el que
# contaba los `return` de dentro de una función auxiliar denunció un contrato
# sano—.
#
#   29-10-2026  26 de 120  medido al escribirlo, con 484 rutas resueltas.
#   29-10-2026  26 de 125  la ficha de un segmento y la de la puntuacion de un
#                          lead anadieron dos ciegas, y las dos se resolvieron
#                          en el mismo commit: `montar_ficha` devuelve las
#                          columnas del modelo igual que el listado, y un
#                          `**otra_cosa()` dentro del literal se sigue como una
#                          delegacion mas. 523 rutas resueltas.
TOPE_SIN_RESOLVER = 26


def test_la_resolucion_mira_de_verdad() -> None:
    """Sin esto, una resolución que no encontrara nada pasaría en verde.

    Las tres cifras son las medidas el 29-10-2026, con holgura hacia abajo. Lo
    que vigilan no es que crezcan: es que no se desplomen porque una refactor
    le haya quitado la vista al resolutor.
    """
    resueltas, _ = claves_por_ruta()
    contratos = contratos_de_las_pantallas()
    assert len(resueltas) >= 400, f"sólo se resuelven {len(resueltas)} rutas"
    assert len(contratos) >= 100, f"sólo se ven {len(contratos)} contratos de pantalla"

    # Y tres que SÍ se resuelven, una por camino, para saber que funcionan: si
    # uno se rompiera, su familia entera dejaría de mirarse sin que bajara el
    # recuento total lo bastante para notarlo.
    assert "titulo" in resueltas["/api/v1/conocimiento/articulos"]  # extras declarados
    assert "miembros" in resueltas["/api/v1/campanas"]  # rollup declarado
    assert "tamano_at" in resueltas["/api/v1/segmentos"]  # literal del manejador
    assert "definicion" in resueltas["/api/v1/segmentos/{}"]  # ficha genérica
    # Y los umbrales, que `explicar()` mete con `**_lo_que_decide(…)`.
    assert "umbrales" in resueltas["/api/v1/puntuacion/leads/{}"]


def test_ninguna_pantalla_lee_un_campo_que_su_ruta_no_devuelve() -> None:
    resueltas, _ = claves_por_ruta()
    rotos: list[str] = []
    for pantalla, ruta, tipo, campos in contratos_de_las_pantallas():
        claves = resueltas.get(ruta)
        if claves is None:
            continue
        faltan = campos - claves
        if faltan:
            rotos.append(f"{pantalla} · {ruta} · {tipo} lee {sorted(faltan)} y no vienen")

    assert len(rotos) <= TOPE_CONTRATOS_ROTOS, (
        f"{len(rotos)} contratos rotos (tope {TOPE_CONTRATOS_ROTOS}):\n  " + "\n  ".join(rotos)
    )


def test_el_punto_ciego_no_crece() -> None:
    """Lo que el resolutor no alcanza se cuenta, no se esconde.

    Una ruta que una pantalla tipa y que aquí no se sabe resolver no está
    vigilada por nada, y un punto ciego que no se cuenta se convierte en
    permiso: la siguiente pantalla que lea un campo inventado por una de estas
    rutas pasaría en verde igual que pasaron las cuatro de arriba.
    """
    resueltas, _ = claves_por_ruta()
    ciegas = sorted(
        {ruta for _, ruta, _, _ in contratos_de_las_pantallas() if ruta not in resueltas}
    )
    assert len(ciegas) <= TOPE_SIN_RESOLVER, (
        f"{len(ciegas)} rutas sin resolver (tope {TOPE_SIN_RESOLVER}). O se "
        f"resuelven, o baja el tope con la que se haya resuelto:\n  " + "\n  ".join(ciegas)
    )
