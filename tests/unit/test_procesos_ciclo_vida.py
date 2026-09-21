"""Borrador, publicada y archivada (CRM-00.03.05.05, CRM-00.03.05.03).

Un motor de procesos se rompe siempre por el mismo sitio: alguien cambia el
diagrama un martes y doscientas instancias a medias pasan a ejecutar pasos que
no existían cuando empezaron. Lo que lo evita es que las versiones no se
sobrescriban y que retirar una **no pare** lo que ya está en vuelo.

Y la validación, que es la otra mitad: un paso inalcanzable es código muerto, y
uno sin salida es una instancia que entra y no sale — se queda en curso para
siempre, consumiendo su temporizador y sin que nadie sepa por qué.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from services.orchestrator import motor as mtr


def _definicion(**cambios: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "inicio": "empezar",
        "pasos": {
            "empezar": {"tipo": "servicio", "operacion": "x.y", "siguiente": "terminar"},
            "terminar": {"tipo": "fin"},
        },
    }
    base.update(cambios)
    return base


# ── Validación ────────────────────────────────────────────────────────────


def test_una_definicion_correcta_no_tiene_problemas() -> None:
    assert mtr.validar_definicion(_definicion()) == []


def test_un_bucle_sin_salida_se_detecta() -> None:
    """Una instancia que entra ahí no sale: se queda en curso para siempre,
    consumiendo su temporizador y sin que nadie sepa por qué."""
    problemas = mtr.validar_definicion(
        _definicion(
            pasos={
                "empezar": {"tipo": "servicio", "operacion": "x.y", "siguiente": "dar_vueltas"},
                "dar_vueltas": {"tipo": "servicio", "operacion": "x.y", "siguiente": "empezar"},
            }
        )
    )
    assert any("no se llega a ningún paso final" in p for p in problemas)


def test_una_rama_que_no_enlaza_a_ningun_fin_se_detecta() -> None:
    """Es el otro caso que se escribe solo al reorganizar un flujo."""
    problemas = mtr.validar_definicion(
        _definicion(
            pasos={
                "empezar": {
                    "tipo": "decision",
                    "condiciones": [{"si": {"op": "="}, "entonces": "bien"}],
                    "si_no": "mal",
                },
                "bien": {"tipo": "fin"},
                # `mal` hace algo y se queda ahí: nunca llega a un final.
                "mal": {"tipo": "servicio", "operacion": "x.y"},
            }
        )
    )
    assert any("«mal»" in p and "final" in p for p in problemas)


def test_un_paso_inalcanzable_se_sigue_detectando() -> None:
    problemas = mtr.validar_definicion(
        _definicion(
            pasos={
                "empezar": {"tipo": "servicio", "operacion": "x.y", "siguiente": "terminar"},
                "terminar": {"tipo": "fin"},
                "olvidado": {"tipo": "fin"},
            }
        )
    )
    assert any("«olvidado» no es alcanzable" in p for p in problemas)


# ── Ciclo de vida ─────────────────────────────────────────────────────────


@pytest.mark.db
def test_un_borrador_no_se_puede_instanciar(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Es para lo que sirve: dejar un proceso a medias entre sesiones de trabajo
    sin arriesgarse a que un disparador lo arranque a mitad de escribirlo."""
    from services.orchestrator.modelos import DefinicionProceso

    db.add(
        DefinicionProceso(
            tenant_id=tenant_id,
            clave="a_medias",
            version=1,
            nombre="A medias",
            definicion=_definicion(),
            estado="borrador",
        )
    )
    db.flush()

    # El motor solo mira las publicadas.
    from sqlalchemy import select

    publicadas = db.execute(
        select(DefinicionProceso).where(
            DefinicionProceso.clave == "a_medias", DefinicionProceso.estado == "publicada"
        )
    ).scalar_one_or_none()
    assert publicadas is None


@pytest.mark.db
def test_archivar_no_para_las_instancias_en_vuelo(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Archivar impide arrancar NUEVAS, no matar las que ya van. Una instancia
    que se corta a mitad deja su compensación sin ejecutar, que es peor que
    dejarla terminar."""
    from sqlalchemy import select

    from services.orchestrator.modelos import DefinicionProceso, InstanciaProceso

    definicion = DefinicionProceso(
        tenant_id=tenant_id,
        clave="retirado",
        version=1,
        nombre="Retirado",
        definicion=_definicion(),
        estado="publicada",
    )
    db.add(definicion)
    db.flush()
    instancia = InstanciaProceso(
        tenant_id=tenant_id,
        definicion_id=definicion.id,
        clave="retirado",
        version=1,
        estado="ejecutando",
        paso_actual="empezar",
    )
    db.add(instancia)
    db.flush()

    definicion.estado = "archivada"
    db.flush()

    viva = db.execute(
        select(InstanciaProceso).where(InstanciaProceso.id == instancia.id)
    ).scalar_one()
    assert viva.estado == "ejecutando"
    assert viva.version == 1
