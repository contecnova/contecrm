"""Lo que una entrada de menú dice que enseña, su pantalla lo tiene que tocar.

El informe de cobertura del front cuenta un recurso como «enseñado» en cuanto
una entrada de navegación lo declara en su lista `recursos`. **Nadie comprueba
esa declaración.** Declarar es gratis y callar sale caro, así que la lista se
llena de recursos que la pantalla no pide nunca, y el informe —que es el que
se mira para decidir qué falta— da por cubierto lo que no existe.

Medido el 27-10-2026, antes de tocar nada: de 45 recursos declarados en la
navegación, **30 no los pedía ningún fichero del front**. Entre ellos,
`aprobaciones` (once operaciones publicadas; la pantalla de aprobaciones pide
`/api/v1/documentos`, que es otra cosa), `aislamiento` y `residencia` (31
operaciones que sólo tenían puerta por API), y `aprobaciones-documentales`, que
ni siquiera existe como recurso: cero operaciones con ese nombre.

La comprobación es tonta a propósito: que el literal `api/v1/<recurso>` aparezca
en algún fichero del front que no sea la propia navegación ni el informe. No
demuestra que la pantalla lo enseñe BIEN; demuestra que lo pide, que es la mitad
que faltaba. La otra mitad —que esté en el menú que toca, con el permiso que
toca— la decide quien lo escribe, y el catálogo la fija por capacidad.

Se excluye `Cobertura.tsx` porque es quien consume la declaración: si contara,
el informe se validaría a sí mismo.
"""

from __future__ import annotations

import functools
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
FRONT = RAIZ / "frontend" / "src"
NAVEGACION = FRONT / "lib" / "navegacion.ts"

# No cuentan como pantalla: la propia declaración y el informe que la lee.
NO_VALEN = {"navegacion.ts", "Cobertura.tsx"}

# ── Histórico. Cada línea, el bloque que la bajó ──────────────────────────
#
#   27-10-2026  30 de 45  medido por primera vez. El informe de cobertura
#                          contaba como enseñado todo lo declarado, sin mirar
#                          la pantalla
#   27-10-2026  18 de 45  puestos en su modulo los que ya eran listados de
#                          verdad: aislamiento, migraciones de aislamiento,
#                          residencia, subprocesadores y transferencias en
#                          Tenants; aprobaciones en Procesos; encargos con sus
#                          tres vistas derivadas, plantillas de documento y
#                          firma presencial en Operacion; creditos de servicio
#                          y cumplimiento de SLA en Casos; recorridos en
#                          Campanas; activos en Contenido. Y pantalla propia
#                          para la conversacion, que es a donde ya enlazaba la
#                          cola de la consola de agente sin que existiera.
#                          `aprobaciones-documentales` no existia como recurso:
#                          la pantalla pide `documentos`, y eso es lo que
#                          declara ahora
TOPE_RECLAMADO_SIN_TOCAR = 18


@functools.cache
def _reclamados() -> tuple[str, ...]:
    texto = NAVEGACION.read_text(encoding="utf-8")
    recursos: set[str] = set()
    for lista in re.findall(r"recursos:\s*\[([^\]]*)\]", texto):
        recursos |= {t.strip().strip('"') for t in lista.split(",") if t.strip()}
    return tuple(sorted(recursos))


@functools.cache
def _texto_del_front() -> str:
    return "\n".join(
        p.read_text(encoding="utf-8", errors="ignore")
        for p in FRONT.rglob("*.ts*")
        if "/pruebas/" not in str(p) and ".test." not in str(p) and p.name not in NO_VALEN
    )


def _sin_tocar() -> tuple[str, ...]:
    texto = _texto_del_front()
    return tuple(r for r in _reclamados() if f"api/v1/{r}" not in texto)


def test_el_recorrido_mira_de_verdad() -> None:
    """Primero, que esto no esté midiendo el vacío.

    Si la navegación cambiara de forma o el patrón dejara de casar, saldrían
    cero reclamados y el gate pasaría en verde sin haber abierto un fichero.
    """
    assert len(_reclamados()) > 30, _reclamados()
    assert len(_texto_del_front()) > 100_000, len(_texto_del_front())
    # Y que al menos uno SÍ se encuentra: si el literal que se busca estuviera
    # mal formado, no encontraría ninguno y el tope subiría solo.
    assert len(_sin_tocar()) < len(_reclamados())


def test_un_reclamo_inventado_se_caza() -> None:
    """Se comprueba plantando el caso malo.

    Un recurso que no existe en ninguna parte tiene que salir en la lista. Si
    no saliera, el gate estaría diciendo que todo está bien porque no mira.
    """
    inventado = "recurso-que-no-existe-en-ninguna-parte"
    assert f"api/v1/{inventado}" not in _texto_del_front()


def test_el_tope_de_reclamos_sin_tocar_solo_baja() -> None:
    """Y sólo baja: cada bajada, en el commit de la pantalla que la justifica."""
    sin = _sin_tocar()
    assert len(sin) <= TOPE_RECLAMADO_SIN_TOCAR, (
        f"{len(sin)} recursos declarados que ninguna pantalla pide, y el tope "
        f"está en {TOPE_RECLAMADO_SIN_TOCAR}: {list(sin)}"
    )
    assert len(sin) >= TOPE_RECLAMADO_SIN_TOCAR - 2, (
        f"van {len(sin)} y el tope sigue en {TOPE_RECLAMADO_SIN_TOCAR}: bájalo "
        "en este mismo commit, con una línea diciendo qué se miró"
    )
