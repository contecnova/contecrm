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
TOPE = 0

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
        for fichero in (RAIZ / carpeta).glob("*.py"):
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
