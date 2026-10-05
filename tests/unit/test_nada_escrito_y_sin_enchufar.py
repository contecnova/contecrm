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
TOPE = 81

# Las que no cuentan, con su motivo. Ninguna es una decisión de producto: son
# ayudantes del andamio —de pruebas, de registro o de SDK— que **sí** tienen
# llamante, pero en `tests/` o fuera del repositorio, y esta sonda mira sólo
# producción a propósito: si mirara las pruebas, una función usada únicamente
# por su propia prueba pasaría por enchufada, que es el caso que más engaña.
NO_CUENTAN: dict[str, str] = {
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
