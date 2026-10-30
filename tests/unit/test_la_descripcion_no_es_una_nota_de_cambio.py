"""La descripción de un endpoint la lee quien abre la pantalla, no quien revisa el commit.

El front pinta el `description` de OpenAPI como el texto de la lista. En
`/m/casos` eso salía así, debajo del título «Buscar casos»:

    Por páginas con cursor. Devolvía una lista pelada con un tope de 50, y sin
    declarar su modelo de respuesta: así la superficie no la reconocía como
    colección y la explotación la registraba como una entidad que se lee
    entera. La métrica «casos abiertos» contestaba 50 habiendo 153, con su
    cara de cifra buena.

Cuatro líneas sobre un fallo ya arreglado, en la pantalla de un agente de
soporte que lo único que quiere es ver sus casos. Medido sobre los 1273
`description=` del repositorio: **33 abrían así**, todas escritas al cerrar la
capacidad que las creó.

El porqué no se tira —es lo que explica la decisión— pero baja al comentario
del código, que es donde lo busca quien lo necesita.

La prueba mira **el primer párrafo**: dentro, un «antes esto fallaba» que
contextualiza una regla concreta es legítimo. Lo que no puede es ser la
entrada.

Validada plantando el caso malo: devolviendo su primer párrafo a cualquiera
de las 33, falla nombrando el fichero y el `summary`.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]

# Las formas en que se cuenta un fallo ya arreglado. No es una lista de frases
# prohibidas: son los tiempos verbales con los que se narra lo que ya no pasa.
NOTA_DE_CAMBIO = re.compile(
    r"\b("
    r"[Dd]evolvía|Estaba|Pasaba|Salía|contestaba|se hacía|Existía"
    r"|No se (podía|sabía|veía)|[Ss]e (escribía|escribían|declaraban|podía|podían)"
    r"|[Nn]o había forma|no l[ao]s? leía|Faltaba|Faltaban"
    r")\b"
)


def _descripciones() -> list[tuple[Path, str, str]]:
    """Cada `description=` de un decorador de ruta, con su `summary`."""
    salida: list[tuple[Path, str, str]] = []
    for fichero in sorted((RAIZ / "services").rglob("*.py")):
        arbol = ast.parse(fichero.read_text(), filename=str(fichero))
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, ast.Call):
                continue
            kw = {k.arg: k.value for k in nodo.keywords if k.arg}
            descripcion = kw.get("description")
            if not isinstance(descripcion, ast.Constant) or not isinstance(descripcion.value, str):
                continue
            resumen = kw.get("summary")
            titulo = (
                resumen.value
                if isinstance(resumen, ast.Constant) and isinstance(resumen.value, str)
                else f"línea {nodo.lineno}"
            )
            salida.append((fichero, titulo, descripcion.value))
    return salida


def test_ninguna_descripcion_abre_contando_lo_que_fallaba() -> None:
    todas = _descripciones()
    # Cuántas ha mirado: una comprobación que no recorre nada parece verde.
    assert len(todas) > 900, f"sólo se han leído {len(todas)} descripciones"

    malas = []
    for fichero, titulo, texto in todas:
        primero = texto.split("\n\n")[0]
        if NOTA_DE_CAMBIO.search(primero):
            malas.append(f"{fichero.relative_to(RAIZ)} · «{titulo}»: {primero[:90]}…")

    assert not malas, (
        "Estas descripciones abren contando el fallo que las motivó. Eso lo lee "
        "quien abre la pantalla. Baja el párrafo a un comentario del código y "
        "deja delante qué devuelve la ruta:\n  " + "\n  ".join(malas)
    )


def test_la_sonda_reconoce_el_caso_malo() -> None:
    """Que el detector detecte: si no, lo de arriba pasa en verde por nada."""
    assert NOTA_DE_CAMBIO.search(
        "Devolvía una lista pelada con un tope de 50, y sin declarar su modelo."
    )
    assert NOTA_DE_CAMBIO.search("**Se escribían y no las leía nadie** (CRM-03.01.01.08).")
    assert NOTA_DE_CAMBIO.search("**No había forma de crear uno.** La tabla existía.")
    assert NOTA_DE_CAMBIO.search("Faltaba, y sin esto la excepción no es un control.")
    # Y que no se cebe con lo legítimo.
    assert not NOTA_DE_CAMBIO.search("Los casos de soporte, por páginas.")
    assert not NOTA_DE_CAMBIO.search(
        "Antes de cada sincronización, no al conectar: el consentimiento cambia."
    )
