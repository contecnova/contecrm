"""Nada escrito, probado y sin que lo llame nadie.

El patrón que más averías ha dado en este repositorio, y con diferencia: una
función correcta, con su prueba unitaria en verde, **a la que no llega nadie**.
No falla nunca. Simplemente, lo que promete no ocurre.

Lo que ya ha costado:

    admitir_asercion_idp     una aserción SAML valía tantas veces como se mandara
    inbox.purgar             la bandeja de entrada crecía sin techo en 14 servicios
    outbox.purgar_publicados ídem
    adjuntos.purgar_huerfanos ídem
    desde_canonico           el mapeo de salida no se alcanzaba desde ninguna ruta
    perfil_sso               los perfiles de IdP no los veía nadie
    consumir_tenant_provisionado  los tenants nacían sin organización
    seis barridos periódicos sin relevo que los ejecutara

Medido el 04-10-2026 en los módulos de integración con terceros: **47
funciones públicas sin un solo llamante de producción**. Eso no se arregla en
un commit —cada una necesita su puerta, y varias necesitan decidir quién las
llama— pero sí se puede impedir que crezca, y eso es lo que hace esto.

**Cómo cuenta, y por qué así.** Las llamadas se cuentan con AST, no buscando el
nombre en el texto: una mención en un comentario no es un llamante, y
confundirlo ya dio un falso rojo hoy. Y se mira además si el nombre se pasa
como valor, porque un manejador registrado —`registrar_transporte("sftp",
listar_sftp)`— sí tiene quien lo llame aunque no haya un paréntesis detrás.

**Y una segunda medida, porque la primera no lo ve todo.** Contar llamadas por
nombre deja pasar un módulo entero sin enchufar: basta con que otra parte del
producto llame a algo que se llame igual —`archivar`, `conectar`, `registrar`—
para que sus funciones parezcan alcanzadas. Medido el 05-10-2026:
`crmcore.datos.particionado` tiene nueve funciones públicas, **no lo importa
nadie**, y la primera medida solo delataba seis. Así que se mira también qué
módulos de producción no importa ningún otro: **ninguno**. Llegó a ser
dieciocho.
"""

from __future__ import annotations

import ast
import collections
import re
from functools import lru_cache
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]

# Dónde se mira. Son los módulos que hablan con sistemas de fuera, que es donde
# está el grueso: 42 de las 51 capacidades que nombran un tercero siguen sin
# auditar, y esto explica por qué.
CARPETAS = (
    "services",
    "packages/crmcore/crmcore",
)

# Tope medido. **Baja o se queda, nunca sube**: cada número de más es una
# función que promete algo que no ocurre.
#
#   04-10-2026  47  medición inicial (sólo integration, marketing, service y
#                   las notificaciones del núcleo)
#   05-10-2026  46  `portal.exigir_nivel` quitada — no la llamaba nadie, no
#                   tenía prueba, y solapaba con `exigir_seccion`, que sí se
#                   usa. Dos comprobaciones de permiso con una sin usar es cómo
#                   acaba usándose la floja.
#   05-10-2026  44  telefonía enchufada: `pantalla_al_sonar` y
#                   `registrar_llamada` no tenían ruta, así que la centralita
#                   no tenía dónde pedir el screen pop ni dónde dar el parte
#                   de una llamada perdida.
#   05-10-2026  35  las nueve decisiones de `suites_recursos` estaban escritas
#                   y probadas sin una sola puerta: nadie de fuera podía pedir
#                   ninguna.
#   05-10-2026   0  CERO en las cuatro carpetas de entonces. Lo que faltaba no
#                   eran puertas sueltas: era que **nada de integración corría
#                   en bucle**, así que las decisiones de una sincronización no
#                   tenían dónde ocurrir.
#   05-10-2026   0  Y **el alcance se amplía a todo**: `services` entero y
#                   `crmcore` entero. Antes se miraban cuatro carpetas de
#                   veintitantas, así que el cero de arriba era el cero de la
#                   cuarta parte. Al ampliarlo salieron 26 en el núcleo, de las
#                   que nueve eran decisiones de verdad sin puerta —entre ellas,
#                   que un campo a medida no recibía ni índice ni vista, que el
#                   móvil sin conexión no tenía por dónde sincronizar, y que una
#                   extensión suscrita a un evento no recibía ninguno—. Cerradas
#                   las nueve, el resto son ayudantes de pruebas y están abajo
#                   con su motivo.
#   05-10-2026 143  **El cero de arriba era falso, y lo era por culpa de esta
#                   misma sonda.** El recorrido usaba `glob("*.py")`, que mira
#                   los ficheros SUELTOS de una carpeta y no los de dentro.
#                   Mientras `CARPETAS` nombraba cuatro carpetas hoja funcionaba;
#                   al ampliarlo a `services` entero pasó a mirar los ficheros
#                   que hay directamente en `services/` —ninguno— y devolvió
#                   cero. Un cero que significaba «no se ha mirado», leído como
#                   «no queda nada», y así se reportó.
#
#                   Es exactamente el fallo que este fichero persigue, cometido
#                   por él: una comprobación que no mira parece verde. Con
#                   `rglob` el número de verdad es 143, y de ahí se baja.
#   05-10-2026 126  Cerradas las de `party` —el plan de cuenta que no era un
#                   plan, el contacto que cambia de empresa, la fusión de
#                   contactos, la comprobación de la evidencia— y las seis de
#                   recuperación, que son justo las que se consultan el día del
#                   incidente, y ese día nadie se pone a escribir código.
#   05-10-2026 115  Observabilidad: ocho decisiones que se consultan cuando
#                   algo va mal o cuando hay que crecer —dónde escalar, si el
#                   despliegue se puede deshacer, si el multi-zona aguanta—
#                   pasan al gateway, que es de quien son: repartidas por los
#                   catorce darían catorce respuestas a la misma pregunta. Y los
#                   contadores de eventos publicados y consumidos, que estaban
#                   escritos y no los llamaba el bus: el panel enseñaba cero con
#                   el bus trabajando, y un cero se lee como «no pasa nada».
#                   Y nueve ayudantes de prueba más pasan a `NO_CUENTAN` con su
#                   motivo: vaciar un registro de proceso entre casos no es una
#                   decisión de producto sin puerta.
#   05-10-2026  97  El ciclo de vida del tenant —clonar, escindir, fusionar,
#                   perfilar— era lo más caro de deshacer que tiene el producto
#                   y la parte que lo hace seguro, la SIMULACIÓN, no se podía
#                   pedir. Y la modalidad de aislamiento ahora sale del tier
#                   contratado: aprovisionar con la plantilla de siempre es cómo
#                   un cliente que paga por base dedicada acaba en la compartida.
#   05-10-2026  92  Metadatos: el tope de campos a medida se ENSEÑABA en una
#                   ruta y no se aplicaba —el sistema sabía decir que un objeto
#                   estaba lleno y dejaba añadir igual—, y la visibilidad por
#                   condición, el formulario servido y la traducción del nombre
#                   viejo de un campo no se podían pedir. Lo primero no da un
#                   error: da una tabla con cuatrocientas columnas y consultas
#                   que se arrastran, y cuando se nota ya no se pueden quitar
#                   porque alguien las usa.
#   05-10-2026  81  La IA aplicada: once decisiones escritas y sin puerta. La
#                   partición del histórico por FECHA —repartir al azar mete
#                   casos posteriores en el entrenamiento y el modelo ha visto
#                   cómo acabó lo que tiene que predecir: el acierto sale
#                   magnífico y no significa nada—, el recorte de lo que sale
#                   hacia el proveedor de inferencia —la ruta recibía el
#                   contexto ya compuesto, así que qué datos personales salían
#                   lo decidía cada pantalla—, el permiso que hay que declarar
#                   antes de indexar, el traspaso de la llamada con lo ya
#                   hablado, la diferencia entre avisar de que se graba y
#                   consentir el entrenamiento, y el modo sin salida de datos.
#                   Ninguna daba error: el producto se comportaba como si esas
#                   decisiones no existieran, y todo en verde.
#   05-10-2026  71  Ventas: diez, y dos de ellas no eran «una ruta que falta»
#                   sino un circuito abierto. La CALIBRACIÓN no podía funcionar
#                   nunca: la columna `resultado` de una revisión llevaba desde
#                   el primer día el comentario «para poder compararlo con lo
#                   que pasó» y no la escribía nadie, así que con el archivo
#                   lleno contestaba «no hay suficientes para concluir». Y el
#                   MARGEN POR LÍNEA no se miraba: el total tapa una línea
#                   vendida por debajo de coste, la aprobación sale por el
#                   total, y lo que se descubre después es que el producto que
#                   más se vende pierde dinero en cada unidad. El contrato con
#                   el proveedor y su alcance no tenían ninguna puerta.
#   05-10-2026  62  La capa de datos: `crmcore.datos.particionado` resolvía
#                   entero el volumen —qué tablas crecen, por qué se corta por
#                   tiempo y no por tenant, qué se puede mover a frío y qué lo
#                   impide— y NO LO IMPORTABA NADIE. El rastro de agregados
#                   estaba encendido sin encender: la tabla de hechos se creaba
#                   en dos servicios, nadie declaraba ningún agregado y por eso
#                   estaba siempre vacía. Y la exportación de un listado no
#                   existía, así que `columnas_exportables` —que es lo que hace
#                   que una exportación traiga los campos del cliente— no tenía
#                   a quién servir.
#   05-10-2026  55  Identidad: la lista de operaciones sensibles se publicaba y
#                   no la aplicaba NADIE fuera de `identity`, porque la marca
#                   del último factor fuerte vive en su esquema y ningún
#                   servicio lee el de otro. Exportar media base, borrar en
#                   bloque y restaurar encima de lo actual no la comprobaban.
#                   Y la MFA adaptativa estaba entera —seis señales, cada
#                   motivo explicado con palabras— sin que el login se la
#                   preguntara nunca.
#   05-10-2026  48  `party`: otro circuito abierto. El LINAJE del dato se podía
#                   consultar y no se podía escribir —`anotar_linaje` no la
#                   llamaba nadie—, así que la tabla estaba siempre vacía:
#                   «¿por qué pone esto aquí?» contestaba nada y «qué valores
#                   llevan sin confirmarse» contestaba que ninguno. Las dos
#                   respuestas son las que saldrían si todo estuviera al día.
#   05-10-2026  44  Seguridad del dato: la MARCA DE ORIGEN no la ponía nadie,
#                   así que la salida de datos más grande del producto —la
#                   exportación de un tenant— salía sin marcar. La búsqueda de
#                   tarjetas coladas por texto libre tampoco corría, y un campo
#                   de notas con una dentro mete al sistema en el alcance de PCI
#                   igual que una columna dedicada. Y del anonimizado había DOS
#                   implementaciones: la que se usaba devolvía hexadecimal para
#                   todo, así que un correo anonimizado no era un correo y
#                   ninguna pantalla con validación funcionaba en pruebas.
#   05-10-2026  39  El gateway: tres módulos completos sin importar. El
#                   TRÁFICO ANÓMALO —el límite fijo no protege del cliente que
#                   hace lo de siempre diez veces más— estaba medido, escalonado
#                   y explicado, y no corría. El EMPUJE SIN ENDPOINT dejaba
#                   fuera a media integración real —un navegador, un móvil, una
#                   red cerrada— y tenía cola, flujo reanudable, aviso de hueco
#                   y latido sin que los alcanzara nada. Y la superficie del
#                   integrador: composición, sandbox, mTLS, panel y endpoint
#                   propio. Seis funciones, cero puertas.
#   05-10-2026  32  Cuatro capacidades de servicio sin puerta: probar una
#                   automatización sin activarla —se prueban activándolas, y
#                   funciona hasta el día en que la regla toca cuatro mil—, el
#                   código del tenant con su sandbox y su firma, los cambios
#                   hacia el lago del cliente, y el coste real frente al
#                   ofertado, que es como se descubre que un tipo de trabajo
#                   pierde dinero después de haberlo vendido veinte veces.
#   05-10-2026  30  Y los últimos módulos del núcleo que no importaba nadie, con
#                   lo que la segunda medida llega a CERO: las peticiones
#                   compuestas —tres viajes de red desde un móvil son tres
#                   ocasiones de quedarse a medias—, el acceso contextual, la
#                   invalidación de la caché por evento —la que evita que
#                   alguien vea desaparecer su propio cambio— y el transporte
#                   gRPC, cuyo ajuste existía, estaba documentado y no lo leía
#                   nadie: encenderlo no encendía nada.
#   05-10-2026  25  El mapa de territorios estaba abierto por los dos extremos:
#                   `visibilidad.py` resolvía el acceso contra una tabla
#                   replicada que NO ESCRIBÍA NADIE —el evento lo emitía ventas
#                   y no lo consumía ningún servicio—, así que esa vía devolvía
#                   siempre vacío; y aunque alguien lo hubiera consumido, el
#                   evento llevaba la clave y la versión, con lo que no se puede
#                   replicar nada. Faltaba además la puerta para añadir o quitar
#                   miembros. Con ellos, la lista de IP de una clave de API —que
#                   se comprobaba al usarla y no al guardarla—, la política por
#                   dimensión y la excepción por campo.
#   05-10-2026  22  Las sagas con compensación: el servicio anuncia en su propia
#                   descripción «sagas con compensación» y el módulo que las
#                   resuelve NO LO ALCANZABA NINGUNA RUTA. Cinco funciones
#                   públicas, enteras y probadas por dentro, y ni un camino desde
#                   fuera: ni arrancar una, ni marcar un paso, ni fallarlo, ni
#                   mirar qué pasaría al publicar una versión nueva sobre lo que
#                   está en vuelo. La sonda solo delataba tres de las cinco,
#                   porque `iniciar` y `fallar` se llaman igual que funciones de
#                   otros módulos y contar por nombre no distingue una de otra.
#   06-10-2026  19  El gobierno de los módulos y el tipo de registro, tres
#                   circuitos abiertos en el mismo servicio: el `describe` no
#                   aplicaba el tipo de registro —el formulario de «cuenta
#                   pública» se pintaba con los campos de la privada y la lista
#                   entera—; NADIE ponía la marca «modificado por el cliente»,
#                   con lo que toda la lógica de no pisar su trabajo al
#                   actualizar un módulo era inalcanzable y el informe de la
#                   actualización salía limpio; y la telemetría contaba cero
#                   usos siempre, así que «¿sobra la mitad de este módulo?»
#                   tenía siempre la misma respuesta equivocada.
TOPE = 19

# Las que no cuentan, con su motivo. Ninguna es una decisión de producto: son
# ayudantes del andamio —de pruebas, de registro o de SDK— que **sí** tienen
# llamante, pero en `tests/` o fuera del repositorio, y esta sonda mira sólo
# producción a propósito: si mirara las pruebas, una función usada únicamente
# por su propia prueba pasaría por enchufada, que es el caso que más engaña.
NO_CUENTAN: dict[str, str] = {
    "registrar_localizador": (
        "Puerto de despliegue, como `registrar_transporte`: quien instale un "
        "localizador de IP registra el suyo. Aquí no se enchufa ninguno a "
        "propósito —atar el producto a un proveedor de geolocalización es lo que "
        "no se hace—, y la ausencia NO se disimula: `evaluar_riesgo` devuelve "
        "«el país no se ha podido medir» en vez de darlo por conocido."
    ),
    "es_entorno_de_pruebas": "lo usan las pruebas para no hablar con el mundo",
    "limpiar_medidores": "el registro es del proceso y vive entre casos de prueba",
    "medidores_registrados": "para que una prueba diga qué se está midiendo",
    "limpiar_tratamientos": "igual: registro de proceso que hay que vaciar entre casos",
    "contables_declarados": "para comprobar qué cuenta como registro del cliente",
    "limpiar_declarados": "registro de proceso, se vacía entre casos",
    "limpiar_hooks": "registro de proceso, se vacía entre casos",
    "limpiar_estado": "registro de proceso, se vacía entre casos",
    "reset_logging": "reconfigurar el registro entre casos de prueba",
    "tablas_declaradas": "para comprobar que cada servicio declara las suyas",
    "reset_metricas": "registro de proceso: las métricas se vacían entre casos",
    "reset_guard": "registro de proceso, se vacía entre casos",
    "componentes_registrados": "para comprobar qué componentes publica la página de estado",
    "agregados_declarados": "para comprobar qué agregados se han declarado",
    "resolutores_registrados": "para comprobar qué resolutores de visibilidad hay",
    "politicas_sin_invalidacion": "para cazar en pruebas una caché que nadie invalida",
    "recursos_por_objeto": "para comprobar el mapa recurso → objeto",
    "limpiar_memoria": "registro de proceso del limitador, se vacía entre casos",
    "generador_registrado": "para comprobar qué generador se ha enchufado",
    "bus_actual": "para que una prueba mire a qué bus se ha conectado el servicio",
    "hay_cliente": "para saltarse una prueba cuando no hay Redis",
    "en_solo_lectura": "accesor de una línea; el estado se lee por `estado()`",
    # Superficie para QUIEN INTEGRA. No la llama el producto por definición: la
    # llama el código de fuera, y quitarla porque «no la usa nadie» sería
    # romperle la extensión a un cliente.
    "registrar_hook": "API de extensiones: la llama la extensión, no el producto",
    "desde_problema": "API del SDK: reconstruye un error del producto en el cliente",
    "con_prefijo": "API del SDK: compone un identificador legible",
    "ahora_utc": "API del SDK y de las pruebas; el producto usa `hoy(db)`",
}


@lru_cache(maxsize=1)
def _arboles() -> dict[str, ast.Module]:
    """Cada fichero de producción, parseado UNA vez.

    Las dos comprobaciones recorren los mismos ficheros: parsearlos dos veces
    duplicaba el coste del gate sin mirar nada nuevo.
    """
    salida: dict[str, ast.Module] = {}
    for fichero in [
        *(RAIZ / "services").rglob("*.py"),
        *(RAIZ / "packages").rglob("*.py"),
        *(RAIZ / "scripts").rglob("*.py"),
    ]:
        if "__pycache__" in str(fichero):
            continue
        try:
            salida[str(fichero)] = ast.parse(fichero.read_text(encoding="utf-8"), str(fichero))
        except SyntaxError:  # pragma: no cover
            continue
    return salida


@lru_cache(maxsize=1)
def _llamadas_de_produccion() -> collections.Counter[str]:
    """Cuántas veces se LLAMA a cada nombre, contado con AST."""
    cuenta: collections.Counter[str] = collections.Counter()
    for arbol in _arboles().values():
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Call):
                nombre = getattr(nodo.func, "id", None) or getattr(nodo.func, "attr", None)
                if nombre:
                    cuenta[nombre] += 1
    return cuenta


@lru_cache(maxsize=1)
def _corpus() -> str:
    """Todo el código de producción, leído UNA vez.

    La primera versión releía los ficheros por cada nombre: 17 segundos para
    una comprobación que mira texto. Un guardián no puede ser el coste.
    """
    return "\n".join(
        f.read_text(encoding="utf-8")
        for f in [*(RAIZ / "services").rglob("*.py"), *(RAIZ / "packages").rglob("*.py")]
        if "__pycache__" not in str(f)
    )


def _se_pasa_como_valor(nombre: str) -> bool:
    """Si el nombre aparece en producción fuera de su propia definición.

    Un manejador registrado no se llama con paréntesis: se pasa. Sin esto, todo
    lo que vive en un registro saldría como suelto.
    """
    return len(re.findall(rf"\b{re.escape(nombre)}\b", _corpus())) > 1


def _sin_llamante() -> list[str]:
    llamadas = _llamadas_de_produccion()
    sueltas: list[str] = []
    arboles = _arboles()
    for carpeta in CARPETAS:
        # `rglob` y no `glob`. Con `glob` sólo se miraban los ficheros SUELTOS de
        # la carpeta, no los de dentro. Mientras `CARPETAS` nombraba cuatro
        # carpetas hoja funcionaba; al ampliarlo a `services` entero, el
        # recorrido pasó a mirar los ficheros que hay directamente en
        # `services/` —ninguno— y el resultado fue cero. Un cero que significaba
        # «no se ha mirado», leído como «no queda nada».
        for fichero in (RAIZ / carpeta).rglob("*.py"):
            if "__pycache__" in str(fichero):
                continue
            arbol = arboles.get(str(fichero))
            if arbol is None:
                continue
            for nodo in arbol.body:
                if not isinstance(nodo, ast.FunctionDef | ast.AsyncFunctionDef):
                    continue
                # Las privadas y las que llevan decorador —una ruta, un
                # consumidor— tienen quien las llame por definición.
                if nodo.name.startswith("_") or nodo.decorator_list:
                    continue
                if nodo.name in NO_CUENTAN or llamadas[nodo.name]:
                    continue
                if _se_pasa_como_valor(nodo.name):
                    continue
                sueltas.append(f"{fichero.relative_to(RAIZ)}::{nodo.name}")
    return sorted(sueltas)


# ── Segunda medida: módulos que no carga nadie ────────────────────────────
#
# La de arriba cuenta llamadas **por nombre**, y por eso no ve un módulo entero
# sin enchufar: basta con que otra parte del producto llame a algo que se llame
# igual —`archivar`, `conectar`, `registrar`— para que sus funciones parezcan
# alcanzadas. Medido el 05-10-2026: `crmcore.datos.particionado` tiene nueve
# funciones públicas, **nadie lo importa**, y la primera medida solo delataba
# seis.
#
# Un módulo que no importa nadie no es «código que todavía no se usa»: es una
# decisión del producto que el producto no toma. Y como no falla, no se nota.

# Lo que se carga sin que ningún `import` lo diga, con el porqué de cada uno.
# Es una lista de excepciones y no una lista de los que sí: una lista de los que
# sí se queda corta el día que alguien añade otra forma de arrancar algo.
SE_CARGAN_DE_OTRA_FORMA: dict[str, str] = {
    "main": (
        "Es el punto de entrada del proceso: lo levanta uvicorn por nombre, no "
        "lo importa otro módulo. Si no se cargara, el servicio no arrancaría — "
        "se nota el primer día."
    ),
    "modelos": (
        "El registro de tablas del servicio. Lo importa `alembic/env.py` por "
        "nombre construido al migrar, que es cuando hace falta que "
        "`Base.metadata` esté completa."
    ),
    "trabajos_worker": (
        "Proceso aparte, arrancado por su propio comando. No lo importa nadie "
        "por lo mismo que no se importa un `main`."
    ),
    "reparto_worker": "Ídem: proceso aparte con su propio comando.",
    "worker": "Ídem: proceso aparte con su propio comando.",
}

# Medido el 05-10-2026. Baja o se queda, nunca sube.
TOPE_MODULOS = 0


def _modulo_de(fichero: Path) -> str:
    partes = fichero.relative_to(RAIZ).with_suffix("").parts
    if partes[0] == "packages":
        partes = partes[2:]
    return ".".join(partes)


@lru_cache(maxsize=1)
def _importados() -> set[str]:
    """Todo lo que algún fichero de producción importa, contado con AST.

    Se recorren también `scripts/` y `alembic/`: desde ahí se cargan cosas que
    nadie más importa —las políticas de RLS, los registros de tablas— y no
    mirarlos las habría contado como huérfanas.
    """
    salida: set[str] = set()
    arboles = dict(_arboles())
    for extra in (RAIZ / "alembic").rglob("*.py"):
        if "__pycache__" in str(extra):
            continue
        try:
            arboles[str(extra)] = ast.parse(extra.read_text(encoding="utf-8"), str(extra))
        except SyntaxError:  # pragma: no cover
            continue
    for arbol in arboles.values():
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Import):
                for alias in nodo.names:
                    salida.add(alias.name)
            elif isinstance(nodo, ast.ImportFrom) and nodo.module:
                salida.add(nodo.module)
                for alias in nodo.names:
                    salida.add(f"{nodo.module}.{alias.name}")
    return salida


def _modulos_sin_cargar() -> list[str]:
    importados = _importados()
    sueltos: list[str] = []
    for carpeta in CARPETAS:
        for fichero in (RAIZ / carpeta).rglob("*.py"):
            if "__pycache__" in str(fichero) or fichero.name == "__init__.py":
                continue
            if fichero.stem in SE_CARGAN_DE_OTRA_FORMA:
                continue
            modulo = _modulo_de(fichero)
            if modulo not in importados:
                sueltos.append(modulo)
    return sorted(sueltos)


def test_el_recorrido_de_modulos_mira_de_verdad() -> None:
    """Si el recorrido se rompe, «ninguno suelto» significa «no se ha mirado».

    Es el fallo que ya costó una medida falsa en este mismo fichero: un cero que
    se leyó como «no queda nada».

    Se exige el número **y las dos formas de importar**. Solo con el número, una
    versión que dejara de mirar los `import x` seguía pasando: los `from x
    import y` bastan para llegar a quinientos, y lo que se cuela por el hueco es
    justo lo que se importa de la otra forma.
    """
    importados = _importados()
    assert len(importados) > 500, (
        f"solo se han contado {len(importados)} importaciones en todo el "
        "producto: el recorrido se ha roto y su resultado no significa nada"
    )
    # Un `import x.y` suelto y un `from x import y`, los dos presentes en el
    # producto. Si falta uno de los dos, el recorrido ha dejado de mirar esa
    # forma y los módulos que entran por ella salen como huérfanos.
    assert "asyncio" in importados, "no se están contando los `import x`"
    assert "crmcore.errors" in importados, "no se están contando los `from x import y`"


def test_ningun_modulo_nuevo_se_queda_sin_cargar() -> None:
    """Un módulo que no importa nadie no se ejecuta nunca, entero.

    No da error: hace que el producto se comporte como si esa decisión no
    existiera. Y la medida de arriba no lo ve, porque cuenta nombres y basta una
    coincidencia para que parezca alcanzado.
    """
    sueltos = _modulos_sin_cargar()
    assert len(sueltos) <= TOPE_MODULOS, (
        f"han subido a {len(sueltos)} los módulos que no carga nadie en "
        f"producción, y el tope medido eran {TOPE_MODULOS}:\n  "
        + "\n  ".join(sueltos)
        + "\n\nO se enchufa, o se quita, o se añade a SE_CARGAN_DE_OTRA_FORMA "
        "diciendo quién lo carga y cuándo."
    )


def test_las_exenciones_de_carga_dicen_quien_las_carga() -> None:
    for nombre, motivo in SE_CARGAN_DE_OTRA_FORMA.items():
        assert motivo.strip(), f"«{nombre}» está exento y no dice quién lo carga"


def test_el_recorrido_mira_de_verdad() -> None:
    """Sin esto, un cambio que dejara la lista vacía pasaría en verde.

    Y «ninguna suelta» sería lo contrario de lo que significa: que no se ha
    mirado.
    """
    llamadas = _llamadas_de_produccion()
    assert len(llamadas) > 1_000, (
        f"solo se han contado {len(llamadas)} nombres llamados en todo el "
        "producto: el recorrido se ha roto y su resultado no significa nada"
    )


def test_lo_escrito_y_sin_enchufar_no_crece() -> None:
    """El tope baja o se queda, nunca sube.

    Subirlo es añadir una función que promete algo que no ocurre, y eso no se
    descubre con una prueba en verde: se descubre cuando un cliente pregunta
    por qué no le llega algo que ve guardado.
    """
    sueltas = _sin_llamante()
    assert len(sueltas) <= TOPE, (
        f"han subido a {len(sueltas)} las funciones públicas sin un solo "
        f"llamante de producción, y el tope medido eran {TOPE}. Cada una de más "
        "es código correcto, probado, y que no se ejecuta nunca:\n  "
        + "\n  ".join(sueltas[: TOPE + 10])
        + "\n\nO se le pone su puerta, o se quita, o entra en NO_CUENTAN con su "
        "motivo escrito."
    )


def test_las_exenciones_dicen_por_que() -> None:
    for nombre, motivo in NO_CUENTAN.items():
        assert motivo.strip(), f"«{nombre}» está exenta y no dice por qué"
