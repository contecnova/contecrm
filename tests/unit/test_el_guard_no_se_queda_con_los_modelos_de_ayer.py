"""El guard de tenant descubría los modelos UNA vez. Los de después, sin filtro.

El aviso estaba escrito en el propio código desde el principio: «un modelo que
se mapeara perezosamente DESPUÉS del primer SELECT quedaría fuera del filtro
para siempre, y sería una red silenciosamente incompleta, que es peor que no
tenerla».

No era una hipótesis. Medido el 26-10-2026: en una sola ejecución de la suite,
el barrido de aislamiento denunciaba que `DELETE /api/v1/casos/{id}` devolvía
**204 sobre el registro de otro tenant** —y lo mismo en segmentos, conexiones,
objetos de metadatos, sesiones y una docena más—. Eran modelos mapeados al
importar su servicio, después de que el guard se diera por descubierto.

Esto es lo más caro que puede fallar en un sistema multi-cliente, y en pruebas
no había red debajo: el rol de la base es superusuario, así que la RLS no
aplica y el guard del ORM es la única defensa.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.db


def test_el_guard_cubre_un_modelo_mapeado_despues(db: Any, tenant_id: UUID) -> None:
    """**La prueba del fallo.** Se descubre, se mapea un modelo nuevo y se
    comprueba que entra en la lista sin que nadie reinstale nada."""
    from crmcore.db.base import Base
    from crmcore.tenancy.guard import instalar_guard, modelos_cubiertos
    from sqlalchemy import Column, String
    from sqlalchemy.dialects.postgresql import UUID as PgUUID

    instalar_guard()
    antes = set(modelos_cubiertos())
    assert len(antes) > 50, f"sólo se ven {len(antes)} modelos: el recorrido no mira"

    nombre = f"TardioDePrueba{uuid4().hex[:8]}"

    # Un modelo con `tenant_id`, mapeado AHORA: justo el caso que se escapaba.
    # Se declara con `Column` y sin anotaciones para no depender de que el
    # tipado por anotación resuelva nombres en un módulo de prueba.
    tipo = type(
        nombre,
        (Base,),
        {
            "__tablename__": f"tardio_{uuid4().hex[:8]}",
            "id": Column(PgUUID(as_uuid=True), primary_key=True),
            "tenant_id": Column(PgUUID(as_uuid=True), nullable=False, index=True),
            "nombre": Column(String(50), nullable=False, default=""),
        },
    )
    try:
        # Forzar la configuración de mapeadores, que es lo que dispara el aviso
        # al que el guard se engancha.
        Base.registry.configure()
        despues = set(modelos_cubiertos())
        assert nombre in despues, (
            "Un modelo mapeado después del descubrimiento se queda FUERA del "
            "filtro de tenant: sus filas serían visibles desde cualquier cliente."
        )
        # Y no se pierde nada de lo que ya estaba.
        assert antes <= despues
    finally:
        Base.metadata.remove(tipo.__table__)
        Base.registry._dispose_cls(tipo)  # type: ignore[attr-defined]


def test_el_descubrimiento_se_rehace_solo_al_mapear() -> None:
    """Se comprueba el mecanismo, no el resultado: si mañana alguien quita el
    enganche y deja el descubrimiento memorizado, esta prueba cae aunque los
    modelos de hoy sigan cubiertos."""
    import inspect

    from crmcore.tenancy import guard

    fuente = inspect.getsource(guard)
    assert "after_configured" in fuente, (
        "El guard ya no se entera de los modelos nuevos: vuelve a ser una red "
        "silenciosamente incompleta."
    )
    # Y que lo que hace es OLVIDAR, no recalcular dentro del escuchador:
    # recalcular ahí dispararía el descubrimiento en mitad de la configuración
    # de mapeadores, que es justo cuando la lista está a medias.
    cuerpo = fuente.split("def _olvidar_lo_descubierto")[1].split("\ndef ")[0]
    assert "_modelos_ambito = None" in cuerpo
