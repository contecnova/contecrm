"""Registrar el CRM como fuente consultable, en diferido (CRM-05.01.04.04).

**Por qué no puede ser síncrono.** El alta recorre la superficie del CRM y prueba
uno a uno los cuarenta y siete listados para medir la forma de cada respuesta —
unos paginan por cursor y otros devuelven una lista pelada, y suponerlo hace que
el alta entera falle por el primero que no encaja. Eso son doce segundos largos,
y el gateway corta a diez: el botón devolvía **504** aunque por debajo el
registro estuviera saliendo bien, que es la peor combinación posible.

No se arregla subiendo el tope. Ese plazo protege al resto: una petición que se
queda diez segundos ocupa un hueco de conexión, y treinta de esas dejan el
gateway sin atender a nadie. Lo que no cabe en una petición se acepta con 202 y
se ejecuta en un worker, que es lo que ya hace este CRM con las importaciones.

**De una vuelta, no de muchas.** Los trabajos de aquí están pensados para
recorrer cincuenta mil filas por tandas con su cursor. Este no tiene elementos
que recorrer: es una operación indivisible —o la fuente queda registrada o no—,
así que consume su único elemento en la primera vuelta. Partirlo en trozos
dejaría una fuente registrada a medias, que es peor que ninguna.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.datos.trabajos import Tanda, Trabajo, registrar_ejecutor
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.logging import get_logger
from sqlalchemy import select
from sqlalchemy.orm import Session

logger = get_logger(__name__)

TIPO = "analitica.registrar_fuente"


def _ejecutar(db: Session, trabajo: Trabajo, _tope: int) -> Tanda:
    from services.analytics.fuente import registrar_fuente
    from services.analytics.modelos import OrganizacionExterna

    if trabajo.cursor >= 1:
        return Tanda(avanzados=0, total=1)

    organizacion = db.execute(
        select(OrganizacionExterna).where(OrganizacionExterna.tenant_id == trabajo.tenant_id)
    ).scalar_one_or_none()
    if organizacion is None:
        # Un fallo con nombre y no una excepción suelta: lo que se lee en la
        # ficha del trabajo tiene que decir qué arreglar, y «sin organización»
        # se arregla mapeando el tenant, no reintentando.
        return Tanda(
            avanzados=1,
            fallidos=1,
            total=1,
            errores=[
                {
                    "motivo": "Este tenant no tiene organización asignada en "
                    "contecintelligence, así que no hay dónde registrar la fuente."
                }
            ],
        )

    uow = UnidadDeTrabajo(db=db, tenant_id=trabajo.tenant_id)
    salida: dict[str, Any] = registrar_fuente(
        uow,
        trabajo.tenant_id,
        organizacion=organizacion.organizacion,
        forzar=bool(trabajo.entrada.get("forzar")),
    )
    uow.volcar()

    if not salida.get("registrada") and not salida.get("sin_cambios"):
        return Tanda(
            avanzados=1,
            fallidos=1,
            total=1,
            errores=[{"motivo": str(salida.get("error") or "no se ha podido registrar")}],
            resultado=salida,
        )
    return Tanda(avanzados=1, ok=1, total=1, resultado=salida)


def encolar_registro(
    db: Session, *, tenant_id: UUID, forzar: bool, pedido_por: UUID | None
) -> Trabajo:
    from crmcore.datos.trabajos import encolar

    return encolar(
        db,
        tenant_id=tenant_id,
        tipo=TIPO,
        entrada={"forzar": forzar},
        total=1,
        pedido_por=pedido_por,
    )


# Importar este módulo registra el ejecutor. Lo hacen la API y el worker, que son
# procesos distintos y ninguno se puede fiar del otro: sin esto, el worker
# arrancaría sin conocer el tipo y dejaría los trabajos encolados para siempre.
registrar_ejecutor(TIPO, _ejecutar)
