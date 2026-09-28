"""Una función periódica que no cuelga de nadie no puede pasar en verde.

El 28-09-2026 había **seis** funciones escritas, probadas y sin llamador:

    correr_programadas       los informes programados no salían nunca
    barrer_recordatorios     los recordatorios vencidos no se emitían
    barrer_reverificaciones  la re-verificación no ocurría
    purgar_estados           la tabla crecía sin techo
    purgar_aserciones        ídem
    purgar_desafios          ídem

Todas con su prueba unitaria **en verde**, porque la prueba llamaba a la función
y la función siempre estuvo bien. Lo que faltaba era que alguien la llamara.

Esto es lo que impide la séptima. Sin esta prueba, mañana alguien escribe otro
barrido, le sale verde, y estamos donde estábamos: una avería que no se descubre
hasta que un cliente pregunta por qué no le llega algo que ve guardado.

**El criterio no es el nombre, es la alcanzabilidad.** `caducar_vencidos` también
suena a barrido y está bien: la llama una ruta. Lo que no puede existir es una
función con pinta de tarea periódica a la que **no llegue nadie**: ni una ruta,
ni un consumidor, ni un `Tarea(...)` de algún `main.py`.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]

# Nombres que delatan una tarea de reloj: algo que hay que pasar cada tanto.
PISTAS = (
    "barrer_",
    "purgar_",
    "correr_programadas",
    "caducar_",
    "reintentar_pendientes",
    "pendientes_de_",
)

# Lo que suena a barrido y NO lo es, **con el motivo al lado**. Una exención sin
# motivo es un olvido con permiso.
NO_SON_TAREAS: dict[str, str] = {
    "purgar_tenant": "la llama la baja del tenant, no un reloj",
    "purgar_papelera": "es una acción del usuario sobre su papelera, con su ruta",
}


def _candidatas() -> dict[str, Path]:
    encontradas: dict[str, Path] = {}
    for fichero in (RAIZ / "services").rglob("*.py"):
        if "__pycache__" in str(fichero):
            continue
        try:
            arbol = ast.parse(fichero.read_text(encoding="utf-8"), str(fichero))
        except SyntaxError:  # pragma: no cover
            continue
        for nodo in arbol.body:
            if not isinstance(nodo, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if nodo.name.startswith("_") or nodo.decorator_list:
                continue
            if any(p in nodo.name for p in PISTAS) and nodo.name not in NO_SON_TAREAS:
                encontradas[nodo.name] = fichero
    return encontradas


def _codigo_de_produccion() -> list[tuple[str, str]]:
    """Todo el código que puede llamarlas. **Las pruebas no cuentan**: que una
    prueba la llame es exactamente lo que pasaba con las seis."""
    ficheros = []
    for carpeta in ("services", "packages", "scripts"):
        for fichero in (RAIZ / carpeta).rglob("*.py"):
            if "__pycache__" not in str(fichero):
                ficheros.append((str(fichero), fichero.read_text(encoding="utf-8")))
    return ficheros


def test_toda_funcion_con_pinta_de_barrido_la_llama_alguien() -> None:
    produccion = _codigo_de_produccion()
    sueltas: list[str] = []

    for nombre, definida_en in sorted(_candidatas().items()):
        usos = 0
        for ruta, texto in produccion:
            encontrados = len(re.findall(rf"\b{re.escape(nombre)}\b", texto))
            if ruta == str(definida_en):
                encontrados -= 1  # su propia definición no cuenta
            usos += encontrados
        if usos <= 0:
            sueltas.append(f"{nombre}  ({definida_en.relative_to(RAIZ)})")

    assert not sueltas, (
        "Estas funciones tienen pinta de tarea periódica y **no las llama nadie** "
        "en producción:\n  "
        + "\n  ".join(sueltas)
        + "\n\nUna prueba que las llame no cuenta: eso es exactamente lo que "
        "pasaba con las seis que se encontraron el 28-09-2026, todas en verde y "
        "ninguna ejecutándose. Cuélgala de un `Tarea(...)` en el `main.py` de su "
        "servicio, dale una ruta, o —si de verdad no es un barrido— añádela a "
        "NO_SON_TAREAS con su motivo."
    )


def test_las_exenciones_dicen_por_que() -> None:
    for nombre, motivo in NO_SON_TAREAS.items():
        assert motivo.strip(), f"«{nombre}» está exenta y no dice por qué"


def _tareas_declaradas() -> set[str]:
    """Los nombres que aparecen dentro de un `Tarea(...)` en algún `main.py`."""
    nombres: set[str] = set()
    for fichero in (RAIZ / "services").rglob("main.py"):
        texto = fichero.read_text(encoding="utf-8")
        nombres |= set(re.findall(r"Tarea\(\s*\"([^\"]+)\"", texto))
    return nombres


def test_las_seis_de_aquel_dia_siguen_colgadas() -> None:
    """El caso concreto, por si el barrido de arriba se afinara de más.

    Si alguien quita una de estas seis del `main.py` de su servicio, la función
    sigue existiendo, su prueba unitaria sigue verde, y vuelve a no ejecutarse
    nunca. Esto lo impide por nombre.
    """
    esperadas = {
        "party.recordatorios",
        "party.reverificaciones",
        "analytics.informes_programados",
        "identity.estados_sso",
        "identity.aserciones_saml",
        "identity.desafios_mfa",
    }
    faltan = esperadas - _tareas_declaradas()
    assert not faltan, (
        "Estas tareas han dejado de estar declaradas en su `main.py`:\n  "
        + "\n  ".join(sorted(faltan))
        + "\n\nSu función sigue existiendo y su prueba seguirá en verde, pero no "
        "la ejecutará nadie. Es el fallo que se arregló el 28-09-2026."
    )


def test_cada_servicio_con_tareas_las_arranca_y_las_para() -> None:
    """Declarar la lista no basta: hay que arrancar el relevo, y pararlo.

    Un relevo que no se para deja el bucle vivo entre recargas en desarrollo, y
    uno que no se arranca es exactamente el agujero de partida.
    """
    for fichero in (RAIZ / "services").rglob("main.py"):
        texto = fichero.read_text(encoding="utf-8")
        if "Tarea(" not in texto:
            continue
        servicio = fichero.parent.name
        assert (
            "RelevoDeTareas" in texto
        ), f"«{servicio}» declara tareas y no arranca el relevo: no se ejecutarán."
        assert "al_arrancar=" in texto, f"«{servicio}» no engancha su arranque"
        assert (
            "al_parar=" in texto
        ), f"«{servicio}» arranca el relevo y no lo para: el bucle queda vivo."
