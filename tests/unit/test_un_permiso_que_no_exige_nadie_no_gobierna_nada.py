"""Un rol que concede un permiso que nadie exige engaña a quien lo lee.

Tercer barrido de la misma familia: la sonda de funciones sin llamante encontró
92, la de ajustes sin lector encontró 20, y ésta recorre los permisos.

El daño no es el permiso de más. Es que **el catálogo de roles es la promesa que
lee quien administra**: si `responsable_soporte` dice «gestiona derechos de
servicio», el administrador que asigne ese rol cree que ha separado esa
responsabilidad. Si ninguna ruta exige `entitlement:write`, no ha separado nada.

Medido el 11-10-2026: 6 de 53 permisos concedidos no los exigía nadie, y uno era
un agujero de verdad —las rutas de derechos de servicio exigían `case:write`,
que tiene **cualquier agente**, en vez del `entitlement:write` que el catálogo
promete—. Dos eran restos de un nombre anterior (`note:*`, cuando las notas son
los comentarios) y uno de un control que nunca se enchufó
(`opportunity:approve`, cuando las aprobaciones son genéricas).

Qué cuenta como «lo exige alguien»: que la cadena aparezca en el código del
producto, del front o de los scripts. No sólo dentro de `exige_permiso(...)`,
porque hay rutas que lo resuelven de otra forma —el router masivo lo construye
con `recurso.permiso_de(operacion)` a partir de un diccionario declarado— y
buscar sólo la llamada dejaría fuera esa familia entera. Es el error que ya costó
doce falsos positivos en el barrido de ajustes.
"""

from __future__ import annotations

import ast
import functools
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
RBAC = RAIZ / "packages" / "crmcore" / "crmcore" / "authz" / "rbac.py"

DONDE_BUSCAR: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("services", (".py",)),
    ("packages", (".py",)),
    ("scripts", (".py",)),
    ("frontend/src", (".ts", ".tsx")),
)

# ── Los que hoy concede alguien y no exige nadie ──────────────────────────
#
# Lista CERRADA y nominal: sólo puede encoger. Un tope numérico dejaría sitio
# para que entre uno nuevo cada vez que se arregla otro.
#
#   11-10-2026  6  medición inicial
#   11-10-2026  0  entitlement:* pasa a exigirse donde el catálogo lo promete,
#                  y note:* y opportunity:approve se quitan de los roles
SIN_EXIGIR_HOY: set[str] = set()


@functools.cache
def _corpus() -> str:
    """Todo el producto menos el fichero que declara los roles.

    Menos ése porque es el que los concede: contarlo haría que todo permiso
    estuviera «exigido» por el hecho de existir, que es un guardián mirando su
    propio reflejo.
    """
    trozos = []
    for carpeta, extensiones in DONDE_BUSCAR:
        base = RAIZ / carpeta
        if not base.exists():
            continue
        for fichero in base.rglob("*"):
            if (
                fichero.suffix in extensiones
                and "__pycache__" not in str(fichero)
                and fichero != RBAC
            ):
                trozos.append(fichero.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(trozos)


@functools.cache
def _concedidos() -> dict[str, frozenset[str]]:
    """Permisos por rol, leídos del AST.

    Del AST y no del texto: el fichero nombra permisos en los comentarios que
    explican por qué un rol NO los tiene, y contarlos como concedidos sería
    justo lo contrario de lo que dicen.
    """
    arbol = ast.parse(RBAC.read_text(encoding="utf-8"))
    salida: dict[str, frozenset[str]] = {}
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
                salida[nombre] = frozenset(permisos)
    return salida


@functools.cache
def _sin_exigir() -> frozenset[str]:
    corpus = _corpus()
    # Los comodines quedan fuera: `*:read` no es un permiso que nadie exija, es
    # una forma de concederlos todos. Su cobertura la vigila el guardián del
    # vocabulario de verbos, que es otro recorrido y otra pregunta.
    todos = {p for ps in _concedidos().values() for p in ps if "*" not in p}
    return frozenset(p for p in todos if p not in corpus)


def test_el_recorrido_mira_de_verdad() -> None:
    """Un recorrido que no lee nada da cero sin exigir, que es el mismo verde
    que tenerlo todo bien."""
    roles = _concedidos()
    assert len(roles) >= 8, f"solo se ven {len(roles)} roles"
    todos = {p for ps in roles.values() for p in ps if "*" not in p}
    assert len(todos) >= 40, f"solo se ven {len(todos)} permisos concedidos"
    # Y uno que evidentemente se exige, para saber que el corpus se está leyendo.
    assert "account:read" not in _sin_exigir()


def test_ningun_permiso_nuevo_se_concede_sin_que_nadie_lo_exija() -> None:
    """Lo que no puede pasar es que la lista CREZCA: un permiso nuevo que no
    gobierna nada es una promesa nueva que no se cumple."""
    nuevos = sorted(_sin_exigir() - SIN_EXIGIR_HOY)
    assert not nuevos, (
        "Permisos que algún rol concede y que no exige ninguna ruta. O los "
        "exige quien debería, o sobran del rol:\n  " + "\n  ".join(nuevos)
    )


def test_los_que_se_arreglan_salen_de_la_lista() -> None:
    sobran = sorted(SIN_EXIGIR_HOY - _sin_exigir())
    assert not sobran, "Ya se exigen y siguen apuntados. Quítalos:\n  " + "\n  ".join(sobran)


def test_el_fichero_que_los_concede_no_cuenta_como_que_los_exige() -> None:
    """Contarlo haría que todo permiso estuviera exigido por existir."""
    corpus = _corpus()
    assert "ROLES_BASE: dict[str, Rol]" not in corpus


def test_los_derechos_de_servicio_los_gobierna_su_propio_permiso() -> None:
    """**El agujero que encontró este barrido**, fijado para que no vuelva.

    Dar de alta un derecho fija a qué tiene derecho el cliente y durante cuánto.
    Con `case:write` lo podía hacer cualquier agente, mientras el catálogo de
    roles decía por escrito que de eso se encarga `responsable_soporte`.
    """
    fuente = (RAIZ / "services/service/api_operacion.py").read_text(encoding="utf-8")
    alta = fuente.split('summary="Dar de alta un derecho de servicio"')[0][-600:]
    assert 'exige_permiso("entitlement:write")' in alta, (
        "dar de alta un derecho de servicio ha dejado de exigir el permiso que "
        "el catálogo de roles promete"
    )
