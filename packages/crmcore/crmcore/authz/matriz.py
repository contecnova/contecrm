"""Matriz de permisos inspeccionable (CRM-07.03.02.09).

«¿Quién puede borrar una cuenta?» es una pregunta que en casi todos los sistemas
se contesta leyendo código. Y se contesta mal: alguien mira la pantalla de roles,
ve que «comercial» no tiene `account:delete` y contesta que nadie — sin saber que
hay un rol con `*:*` y tres personas dentro.

Esto la contesta desde lo que hay de verdad: **las rutas que se publican** y
**los permisos que conceden los roles**, cruzados. No desde un documento.

Cuatro decisiones:

**Se deriva de las rutas montadas, no de una lista.** Una lista de permisos
escrita a mano se queda desfasada en el primer endpoint nuevo, y ese endpoint
sería justo el que nadie audita.

**Los comodines se expanden.** Un rol con `*:*` no aparece con un asterisco: se
enseña qué puede hacer exactamente, porque el asterisco es donde se esconden los
privilegios que nadie contó.

**Se enseñan los dos huecos, y son opuestos.** Un permiso que exige una ruta y no
tiene ningún rol es funcionalidad muerta —nadie puede usarla—; un permiso
concedido que ninguna ruta exige es un privilegio fantasma que alguien concedió
por si acaso. El primero es un fallo de configuración; el segundo, un riesgo.

**El ABAC se dice al lado, no se mezcla.** Tener el permiso no significa poder
sobre todos los registros: las políticas acotan después. Presentar solo el RBAC
haría creer que un comercial ve todas las cuentas; presentar solo lo efectivo
escondería lo que pasaría si mañana se quita una política.
"""

from __future__ import annotations

from typing import Any

from crmcore.logging import get_logger

logger = get_logger(__name__)


def _rutas(objeto: Any, prefijo: str = "") -> list[tuple[str, Any]]:
    """Todas las rutas, incluidas las que cuelgan de routers incluidos.

    No basta con `app.routes`: esta versión de FastAPI no aplana los routers al
    incluirlos, los envuelve. Quedarse en el primer nivel devolvía siete rutas de
    infraestructura y ninguna de negocio — es decir, una matriz de permisos vacía
    que habría dicho que no hay nada que auditar.
    """
    salida: list[tuple[str, Any]] = []
    for ruta in getattr(objeto, "routes", []) or []:
        interno = getattr(ruta, "original_router", None)
        if interno is not None:
            salida.extend(_rutas(interno, prefijo + (getattr(ruta, "prefix", "") or "")))
            continue
        camino = getattr(ruta, "path", "")
        if camino:
            salida.append((prefijo + camino, ruta))
    return salida


def permisos_de_las_rutas(app: Any) -> dict[str, list[str]]:
    """Qué permiso exige cada ruta publicada, leído de la propia aplicación.

    Se lee de las dependencias montadas y no de un inventario: lo que un
    inventario dice que exige una ruta y lo que la ruta exige de verdad dejan de
    coincidir el día que alguien cambia una y no el otro — y el día que dejan de
    coincidir es el día en que la auditoría deja de valer.
    """
    salida: dict[str, list[str]] = {}
    for camino, ruta in _rutas(app):
        exigidos: list[str] = []
        for dependencia in getattr(getattr(ruta, "dependant", None), "dependencies", []) or []:
            llamada = getattr(dependencia, "call", None)
            # `exige_permiso` devuelve un cierre que lleva el permiso dentro.
            requerido = getattr(llamada, "permiso_exigido", None)
            if requerido:
                exigidos.append(str(requerido))
        for metodo in sorted(getattr(ruta, "methods", []) or []):
            if metodo in ("HEAD", "OPTIONS"):
                continue
            if exigidos:
                salida[f"{metodo} {camino}"] = sorted(set(exigidos))
    return salida


def _cubre(permiso_concedido: str, permiso_exigido: str) -> bool:
    """Si un permiso concedido cubre al exigido, expandiendo comodines.

    El comodín solo vale a la derecha de los dos puntos y por segmento completo,
    igual que en la comprobación real: si aquí se expandiera de otra forma, la
    matriz enseñaría algo distinto de lo que el sistema hace, que es peor que no
    tener matriz.
    """
    if permiso_concedido == permiso_exigido:
        return True
    objeto_c, _, accion_c = permiso_concedido.partition(":")
    objeto_e, _, accion_e = permiso_exigido.partition(":")
    return (objeto_c in ("*", objeto_e)) and (accion_c in ("*", accion_e))


def matriz(
    app: Any,
    roles: dict[str, Any],
    *,
    politicas: list[Any] | None = None,
) -> dict[str, Any]:
    """Quién puede hacer qué, y qué no puede hacer nadie.

    `roles` son los del tenant —los de base más los suyos—, porque un rol propio
    con `*:*` es exactamente lo que hay que poder ver y lo que no sale en ninguna
    documentación del producto.
    """
    por_ruta = permisos_de_las_rutas(app)
    exigidos = sorted({p for permisos in por_ruta.values() for p in permisos})

    por_permiso: dict[str, list[str]] = {p: [] for p in exigidos}
    concedidos: set[str] = set()
    for nombre, rol in roles.items():
        suyos = set(getattr(rol, "permisos", None) or [])
        concedidos |= suyos
        for exigido in exigidos:
            if any(_cubre(c, exigido) for c in suyos):
                por_permiso[exigido].append(nombre)

    sin_rol = sorted(p for p, quien in por_permiso.items() if not quien)
    fantasma = sorted(
        c for c in concedidos if "*" not in c and not any(_cubre(c, e) for e in exigidos)
    )

    # Las políticas ABAC se enseñan al lado: acotan DESPUÉS del permiso, y
    # mezclarlas haría creer que un permiso concedido ya está limitado —o al
    # revés, que no lo está—.
    acotados: dict[str, list[str]] = {}
    for politica in politicas or []:
        objeto = str(getattr(politica, "objeto", "") or "")
        if objeto:
            acotados.setdefault(objeto, []).append(str(getattr(politica, "nombre", "")))

    return {
        "rutas_con_permiso": len(por_ruta),
        "permisos_exigidos": exigidos,
        "quien_puede": {p: sorted(quien) for p, quien in por_permiso.items()},
        # Los dos huecos, y son opuestos: uno es funcionalidad muerta y el otro
        # un privilegio que alguien concedió por si acaso.
        "exigidos_sin_ningun_rol": sin_rol,
        "concedidos_que_ninguna_ruta_exige": fantasma,
        "acotados_por_politica": acotados,
        "que_significa": (
            "Tener el permiso no significa poder sobre todos los registros: las "
            "políticas ABAC acotan después, y por eso se enseñan al lado en vez "
            "de mezclarse con el permiso."
        ),
        "aviso": (
            ""
            if not sin_rol
            else f"{len(sin_rol)} permiso(s) que alguna ruta exige no los tiene "
            "ningún rol: esa funcionalidad no la puede usar nadie."
        ),
    }
