"""Los comodines de los roles dependen de cómo se escriba el verbo.

Medido el 11-10-2026. El vocabulario de permisos está **mezclado**: 461 rutas
exigen `:read` y diez exigen `:leer` o `:consultar`; 478 exigen `:write` y una
docena dicen `:escribir`, `:editar`, `:crear`, `:borrar` o `:subir`.

Eso no sería más que una fealdad si no fuera porque dos roles de serie se apoyan
en un **comodín**:

    solo_lectura   `*:read`            «Consulta todo, no modifica nada»
    integracion    `*:read`, `*:write` cuenta de servicio

Con sólo `*:read`, «consulta todo» era falso: el rol de auditoría no alcanzaba
`cumplimiento:leer` —que es exactamente lo que un auditor viene a mirar— ni las
seis rutas de analítica. Y la cuenta de integración no podía subir un adjunto ni
escribir un comentario, que son dos de las cosas que más hace una integración.

**No se renombran los permisos.** Un tenant puede tener roles propios que citen
`analitica:consultar`, y cambiarlo les quitaría el acceso sin avisar. Lo que se
hace es que los comodines cubran el vocabulario entero, y que el vocabulario
**sea cerrado**: un verbo nuevo entra por aquí o no entra.

Este recorrido es lo que convierte la convención en una regla. Sin él, la
siguiente ruta que exija `:ver` o `:modificar` volvería a escaparse de los
comodines, y nadie lo notaría hasta que un auditor dijera que no ve algo.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
RE_EXIGE = re.compile(r'exige_permiso\(\s*["\']([a-z_]+):([a-z_*]+)["\']')

# El vocabulario, por lo que cada verbo SIGNIFICA. Lo que decide a qué comodín
# pertenece un verbo es si lee o si escribe, no en qué idioma está escrito.
VERBOS_DE_LECTURA = frozenset({"read", "leer", "consultar"})
VERBOS_DE_ESCRITURA = frozenset({"write", "escribir", "editar", "crear", "borrar", "subir"})
# Y los que no son ni una cosa ni la otra: administrar, decidir, aprobar, purgar.
# NO los cubre ningún comodín a propósito —ver la descripción de `integracion`:
# una credencial de máquina filtrada no debe poder cambiar quién tiene acceso—,
# así que se enumeran aquí para que añadir uno sea una decisión y no un
# descuido.
VERBOS_PRIVILEGIADOS = frozenset(
    {
        "admin",
        "administrar",
        "approve",
        "auditar",
        "bloquear",
        "configurar",
        "convert",
        "credenciales",
        "decidir",
        "delete",
        "desenlazar",
        "enlace",
        "enlazar",
        "exportar",
        "import",
        "invocar",
        "merge",
        "organizar",
        "purgar",
        "purge",
        "registrar",
        "reopen",
        "resolver",
        "restaurar",
        "usar",
    }
)


def _verbos_usados() -> dict[str, list[str]]:
    usos: dict[str, list[str]] = {}
    for carpeta in ("services", "packages"):
        for fichero in (RAIZ / carpeta).rglob("*.py"):
            if "__pycache__" in str(fichero):
                continue
            texto = fichero.read_text(encoding="utf-8", errors="ignore")
            for m in RE_EXIGE.finditer(texto):
                usos.setdefault(m.group(2), []).append(f"{fichero.name}: {m.group(0)[16:]}")
    return usos


def _roles() -> dict[str, set[str]]:
    arbol = ast.parse((RAIZ / "packages/crmcore/crmcore/authz/rbac.py").read_text(encoding="utf-8"))
    salida: dict[str, set[str]] = {}
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Call) and getattr(nodo.func, "id", "") == "Rol":
            nombre, permisos = "", set()
            for clave in nodo.keywords:
                if clave.arg == "nombre" and isinstance(clave.value, ast.Constant):
                    nombre = clave.value.value
                if clave.arg == "permisos":
                    permisos = {
                        n.value
                        for n in ast.walk(clave.value)
                        if isinstance(n, ast.Constant) and isinstance(n.value, str)
                    }
            if nombre:
                salida[nombre] = permisos
    return salida


def test_el_recorrido_mira_de_verdad() -> None:
    """Un recorrido que no encuentra rutas pasa siempre."""
    usos = _verbos_usados()
    assert sum(len(v) for v in usos.values()) >= 900, "el recorrido no está viendo las rutas"
    assert "read" in usos and "write" in usos
    assert len(_roles()) >= 8


def test_ningun_verbo_nuevo_entra_sin_decidir_de_que_lado_cae() -> None:
    """Un verbo que no esté en ninguna de las tres listas se escapa de los
    comodines, y eso no se nota hasta que alguien dice que no ve algo."""
    conocidos = VERBOS_DE_LECTURA | VERBOS_DE_ESCRITURA | VERBOS_PRIVILEGIADOS | {"*"}
    nuevos = sorted(set(_verbos_usados()) - conocidos)
    assert not nuevos, (
        "Verbos de permiso que no están clasificados. Decide de qué lado caen y "
        "añádelos a la lista que toque —si leen o escriben, los comodines de "
        "`solo_lectura` e `integracion` tienen que cubrirlos—:\n  " + "\n  ".join(nuevos)
    )


def test_solo_lectura_consulta_de_verdad_todo() -> None:
    """Es lo que dice su descripción. Con sólo `*:read` no alcanzaba
    `cumplimiento:leer`, que es justo lo que un auditor viene a mirar."""
    permisos = _roles()["solo_lectura"]
    faltan = sorted(f"*:{v}" for v in VERBOS_DE_LECTURA if f"*:{v}" not in permisos)
    assert not faltan, f"«Consulta todo» y no alcanza: {faltan}"


def test_solo_lectura_no_escribe_nada() -> None:
    """La otra mitad de su promesa, y la que importa: ampliar los comodines de
    lectura no puede colarle una escritura."""
    permisos = _roles()["solo_lectura"]
    escriben = sorted(
        p for p in permisos if p.split(":", 1)[-1] in (VERBOS_DE_ESCRITURA | VERBOS_PRIVILEGIADOS)
    )
    assert not escriben, f"«No modifica nada» y tiene: {escriben}"


def test_la_cuenta_de_integracion_escribe_lo_que_escribe_una_integracion() -> None:
    """Con sólo `*:write` no podía subir un adjunto ni escribir un comentario."""
    permisos = _roles()["integracion"]
    faltan = sorted(f"*:{v}" for v in VERBOS_DE_ESCRITURA if f"*:{v}" not in permisos)
    assert not faltan, f"una integración no puede: {faltan}"


def test_la_cuenta_de_integracion_no_administra() -> None:
    """Su propia descripción: «una credencial de máquina filtrada no debe poder
    cambiar quién tiene acceso». Si un comodín cubriera `administrar`, podría."""
    permisos = _roles()["integracion"]
    privilegiados = sorted(p for p in permisos if p.split(":", 1)[-1] in VERBOS_PRIVILEGIADOS)
    assert not privilegiados, f"la cuenta de servicio administra: {privilegiados}"


def test_las_tres_listas_no_se_solapan() -> None:
    """Un verbo en dos listas haría que el resultado dependiera del orden en que
    se consulten, que es como una regla deja de ser una regla."""
    assert not (VERBOS_DE_LECTURA & VERBOS_DE_ESCRITURA)
    assert not (VERBOS_DE_LECTURA & VERBOS_PRIVILEGIADOS)
    assert not (VERBOS_DE_ESCRITURA & VERBOS_PRIVILEGIADOS)
