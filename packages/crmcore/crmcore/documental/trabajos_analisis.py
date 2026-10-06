"""Analizar una rama del corpus, en diferido (CRM-06.01.01.05).

`analizar_rama` dice en su propia documentación que **solo se llama desde un
trabajo de fondo**, y el motivo es bueno: pasa por el modelo de lenguaje, y el de
embeddings puede tardar minutos en cargar en frío. O sea que funciona en caliente
y falla en frío — en pruebas iría bien y el lunes por la mañana daría 504.

Lo que no había era el trabajo de fondo. La función estaba escrita, con su plazo
propio en minutos, y **no la llamaba nadie**: ni ruta, ni worker. El análisis de
una rama era una capacidad que no se podía pedir de ninguna forma.

Y el resultado del análisis trae **citas de fragmento**, no de documento: varias
pueden salir del mismo fichero. Pintarlas tal cual da una lista con el mismo
documento repetido cuatro veces, que parece un fallo y no lo es — por eso se
agrupan antes de guardarlas, con `documentos_citados`, que tampoco llamaba nadie.

**Una rama por tanda**, y no todas de golpe: cada análisis es una llamada que
puede tardar minutos, y una tanda que se come veinte es un commit de media hora
que, si el worker se cae, se repite entero.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from crmcore.datos.trabajos import Tanda, Trabajo, encolar, registrar_ejecutor
from crmcore.logging import get_logger

logger = get_logger(__name__)

TIPO = "documental.analizar_rama"


def _ejecutar(db: Session, trabajo: Trabajo, tope: int) -> Tanda:
    from crmcore.documental.cliente import analizar_rama, documentos_citados

    carpetas: list[str] = [str(c) for c in (trabajo.entrada.get("carpetas") or []) if c]
    if not carpetas:
        return Tanda(
            avanzados=0,
            total=0,
            resultado={"motivo": "el trabajo no trae ninguna rama que analizar"},
        )

    # Una por tanda. `tope` manda cuántas caben, pero aquí el techo real lo pone
    # el plazo del análisis: dos en el mismo commit son dos esperas de minutos
    # encadenadas.
    trozo = carpetas[trabajo.cursor : trabajo.cursor + max(1, min(tope, 1))]
    if not trozo:
        return Tanda(avanzados=0, total=len(carpetas))

    token = str(trabajo.entrada.get("token_usuario") or "")
    que = str(trabajo.entrada.get("que") or "resumen")
    pregunta = str(trabajo.entrada.get("pregunta") or "")
    con_subcarpetas = bool(trabajo.entrada.get("con_subcarpetas", True))

    hechos: list[dict[str, Any]] = []
    errores: list[dict[str, Any]] = []
    for carpeta_id in trozo:
        try:
            salida = analizar_rama(
                carpeta_id,
                token_usuario=token,
                que=que,
                pregunta=pregunta,
                con_subcarpetas=con_subcarpetas,
            )
        except Exception as exc:  # noqa: BLE001 — una rama no para las demás
            errores.append({"carpeta_id": carpeta_id, "motivo": str(exc)[:200]})
            continue
        hechos.append(
            {
                "carpeta_id": carpeta_id,
                "que": que,
                "texto": salida.get("texto") or salida.get("summary") or "",
                # Agrupadas por documento: las citas vienen por fragmento y
                # varias salen del mismo fichero.
                "documentos": documentos_citados(list(salida.get("citations") or [])),
            }
        )

    logger.info(
        "documental.rama_analizada",
        trabajo=str(trabajo.id),
        ramas=len(trozo),
        fallidas=len(errores),
    )
    return Tanda(
        avanzados=len(trozo),
        ok=len(hechos),
        fallidos=len(errores),
        errores=errores,
        total=len(carpetas),
        resultado={"analisis": hechos},
    )


def encolar_analisis(
    db: Session,
    *,
    tenant_id: UUID,
    carpetas: list[str],
    token_usuario: str,
    que: str = "resumen",
    pregunta: str = "",
    con_subcarpetas: bool = True,
    pedido_por: UUID | None = None,
) -> Trabajo:
    """Deja el análisis pedido y devuelve su ficha, para consultar el estado.

    No lo ejecuta: un análisis que tarda minutos dentro de una petición de
    usuario es un 504 con el trabajo hecho y tirado.
    """
    return encolar(
        db,
        tenant_id=tenant_id,
        tipo=TIPO,
        entrada={
            "carpetas": list(carpetas),
            "token_usuario": token_usuario,
            "que": que,
            "pregunta": pregunta,
            "con_subcarpetas": con_subcarpetas,
        },
        total=len(carpetas),
        pedido_por=pedido_por,
    )


registrar_ejecutor(TIPO, _ejecutar)
