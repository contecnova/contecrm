"""Lo que ve un integrador de su propia clave de API (CRM-00.02.04.06).

Es un cálculo puro: recibe las llamadas y devuelve el panel. Las llamadas las
guarda `identity` —dueña de las claves— a partir de lo que apunta el gateway en
cada petición hecha con clave, y el panel de la clave se calcula con ellas.
"""

from __future__ import annotations

from typing import Any


def panel_de_integrador(
    *,
    clave: str,
    llamadas: list[dict[str, Any]],
    cuota_mes: int,
    scopes: list[str],
) -> dict[str, Any]:
    """Lo que ve un integrador de su propia clave.

    **Lo que de verdad pasó, no lo que el contrato promete.** Un portal que solo
    documenta es una web bonita que no resuelve la llamada de las tres de la
    mañana; lo que la resuelve es ver el último error con su código y su hora.

    Los errores van **separados por culpa**: los suyos —4xx— y los nuestros
    —5xx—. Mezclarlos hace que un integrador pase una tarde revisando su código
    por una caída nuestra, o al revés.
    """
    total = len(llamadas)
    suyos = [ll for ll in llamadas if 400 <= int(ll.get("status") or 0) < 500]
    nuestros = [ll for ll in llamadas if int(ll.get("status") or 0) >= 500]
    ultimos_errores = sorted(
        (ll for ll in llamadas if int(ll.get("status") or 0) >= 400),
        key=lambda ll: str(ll.get("cuando") or ""),
        reverse=True,
    )[:10]

    return {
        "clave": clave,
        "scopes": sorted(set(scopes)),
        "llamadas": total,
        "consumido_pct": round(100 * total / cuota_mes, 1) if cuota_mes else None,
        "quedan": max(0, cuota_mes - total) if cuota_mes else None,
        # Separados por culpa: mezclarlos hace que un integrador pase una tarde
        # revisando su código por una caída nuestra.
        "errores_suyos": len(suyos),
        "errores_nuestros": len(nuestros),
        "ultimos_errores": [
            {
                "cuando": ll.get("cuando"),
                "ruta": ll.get("ruta"),
                "status": ll.get("status"),
                "detalle": str(ll.get("detalle") or "")[:200],
            }
            for ll in ultimos_errores
        ],
        "que_mirar_primero": (
            "Nada: no hay errores en la ventana."
            if not suyos and not nuestros
            else "Los errores 5xx son nuestros: si los hay, abre incidencia en vez de "
            "revisar tu código."
            if nuestros
            else "Todos los errores son 4xx: la petición no cuadra con el contrato. El "
            "detalle de cada uno dice qué campo."
        ),
    }
