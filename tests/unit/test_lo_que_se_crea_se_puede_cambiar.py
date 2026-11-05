"""Lo que una pantalla deja dar de alta, se puede cambiar después.

Un CRM en el que sólo se puede añadir es un formulario con memoria. Medido el
05-11-2026 cruzando las pestañas de `recursos.ts` con los trece contratos:
**treinta** admitían alta y ninguna forma de cambio —ni `PATCH`, ni `PUT`, ni
`DELETE`, ni una acción sobre el registro—. Un producto no se podía renombrar
ni retirar; una cola no podía cambiar de miembros; un rol, de permisos. La
errata se quedaba, o se creaba otro al lado.

Diecisiete eran un hueco y se cerraron. Las demás lo son **a propósito**, y
cada una dice aquí por qué: un histórico no se edita, una versión publicada no
se reescribe, y lo que se declara por clave se cambia declarándolo otra vez.
Una lista de las que sí pueden cambiarse se quedaría corta con la siguiente;
una de las que no, con su motivo, obliga a justificarse.

Validada plantando el caso malo: sin la ficha de productos, falla y la nombra.
"""

from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
RECURSOS = RAIZ / "frontend/src/lib/recursos.ts"
ENTRADA = re.compile(r"\{[^{}]*?\}", re.S)

SERVICIOS = [
    "tenancy",
    "identity",
    "metadata",
    "orchestrator",
    "automation",
    "integration",
    "eventing",
    "party",
    "sales",
    "analytics",
    "intelligence",
    "service",
    "marketing",
]

SIN_CAMBIOS_PORQUE: dict[str, str] = {
    "/api/v1/ciclo-vida/perfiles": (
        "Guardar un perfil de industria crea una versión nueva y desactiva la "
        "anterior: cambiarlo es volver a declararlo con la misma clave."
    ),
    "/api/v1/residencia": (
        "Fijar la residencia reescribe la del mismo tipo de dato: se cambia "
        "volviendo a declararla, y así queda una sola por tipo."
    ),
    "/api/v1/residencia/transferencias": (
        "Es el registro de salidas de datos fuera de su región: un registro que "
        "se puede corregir a posteriori no sirve de prueba ante nadie."
    ),
    "/api/v1/procesos/definiciones": (
        "Una definición publicada no se reescribe: las instancias en vuelo "
        "terminan con su versión. Se cambia publicando otra desde el editor."
    ),
    "/api/v1/aprobaciones/enlaces": (
        "Son enlaces firmados de un solo uso para decidir desde el correo: "
        "editarlos rompería la firma, y caducan solos."
    ),
    "/api/v1/repuestos/movimientos": (
        "Es el libro de movimientos de almacén: un error se corrige con un "
        "movimiento contrario, no reescribiendo el que ya cuadró el stock."
    ),
    "/api/v1/ia/modelos": (
        "Cada alta registra una versión entrenada con sus métricas: se cambia "
        "registrando otra, y la anterior queda para comparar."
    ),
    "/api/v1/ia/modelos/deriva": (
        "Son mediciones de deriva contra lo que pasó de verdad: corregir una "
        "medición a mano la convertiría en una opinión."
    ),
    "/api/v1/ia/guardias": (
        "Declarar un guardarraíl reescribe el de la misma clave: se cambia "
        "volviéndolo a declarar, con su validación de sensibilidades."
    ),
    "/api/v1/ia/plantillas": (
        "Las plantillas de prompt van por versiones: lo que se respondió con una "
        "tiene que poder rastrearse a esa versión, no a la de hoy."
    ),
    "/api/v1/ia/salud": (
        "Cada alta es una medición de la salud de una cuenta en un momento: se "
        "vuelve a medir, no se corrige la anterior."
    ),
    "/api/v1/analitica/consultas": (
        "Es el registro de preguntas hechas a la analítica, con su duración y "
        "su error: un histórico que se puede editar deja de servir."
    ),
    "/api/v1/puntuacion/modelos": (
        "Los modelos de puntuación se publican por versiones: cambiar uno en "
        "sitio haría incomparables los leads puntuados antes y después."
    ),
    "/api/v1/sla": (
        "Las definiciones de SLA van por versiones: cada caso se mide con la "
        "versión con la que nació, y reescribirla cambiaría plazos ya vencidos."
    ),
}


def _pestanas_con_alta() -> list[tuple[str, str]]:
    salida = []
    for bloque in ENTRADA.findall(RECURSOS.read_text(encoding="utf-8")):
        listar = re.search(r'listar:\s*"([^"]+)"', bloque)
        nombre = re.search(r'nombre:\s*"([^"]+)"', bloque)
        if listar and nombre and ":servicio" not in listar.group(1):
            salida.append((nombre.group(1), listar.group(1).split("?")[0]))
    return salida


def test_lo_que_se_da_de_alta_se_puede_cambiar() -> None:
    from tests.unit._contratos import caminos

    operaciones: set[str] = set()
    for servicio in SERVICIOS:
        for ruta, metodos in caminos(servicio).items():
            operaciones |= {f"{m.upper()} {ruta}" for m in metodos}

    sin_cambios: list[str] = []
    miradas = 0
    vistas: set[str] = set()
    for nombre, base in _pestanas_con_alta():
        if base in vistas or f"POST {base}" not in operaciones:
            continue
        vistas.add(base)
        miradas += 1
        cambio = re.compile(
            rf"^(PATCH|PUT|DELETE) {re.escape(base)}/\{{[a-z_]+\}}$"
            rf"|^POST {re.escape(base)}/\{{[a-z_]+\}}(/[a-z-]+)?$"
        )
        if any(cambio.match(o) for o in operaciones):
            continue
        if base not in SIN_CAMBIOS_PORQUE:
            sin_cambios.append(f"«{nombre}» ({base})")

    assert miradas > 100, f"sólo se han mirado {miradas} pestañas con alta"
    assert not sin_cambios, (
        "Pestañas que dejan dar de alta y no admiten ningún cambio después. "
        "Monta su ficha (`montar_ficha`) o di en SIN_CAMBIOS_PORQUE por qué no "
        "debe cambiarse:\n  " + "\n  ".join(sin_cambios)
    )


def test_los_motivos_son_motivos_y_siguen_haciendo_falta() -> None:
    """Un motivo vacío no justifica nada, y uno de una pestaña que ya admite
    cambios es una excepción que nadie volverá a mirar."""
    for base, motivo in SIN_CAMBIOS_PORQUE.items():
        assert len(motivo) >= 60, f"{base}: el motivo no explica nada"
    declaradas = {base for _, base in _pestanas_con_alta()}
    sobran = sorted(set(SIN_CAMBIOS_PORQUE) - declaradas)
    assert not sobran, f"Excepciones de pestañas que ya no existen: {sobran}"
