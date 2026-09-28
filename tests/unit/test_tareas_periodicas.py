"""El ejecutor de tareas periódicas (CRM-00.06.01.06 y las seis que colgaban).

contecrm tenía workers de cola y **nada que hiciera «cada N minutos, barre
esto»**. Seis funciones estaban escritas, probadas y sin llamador: los
recordatorios vencidos no se emitían nunca, los informes programados no salían,
y tres tablas de estados caducados crecían sin techo.

**No faltaban seis cosas: faltaba una.** Seis arreglos habrían sido seis sitios
donde volver a olvidarse.

Lo que se prueba aquí son las tres reglas, y las tres nacen de averías reales:
que un tenant que falla no pare a los demás, que el que falla deje **su
identificador y su motivo** —no un contador—, y que la tarea **late aunque no
tenga nada que hacer**, porque si sólo latiera al trabajar, una tarea parada y
una sin trabajo se verían igual.
"""

from __future__ import annotations

from typing import Any

import pytest
from crmcore.tareas import (
    FALLOS_PARA_AVERIA,
    RelevoDeTareas,
    Tarea,
    estado_de_las_tareas,
    limpiar_estado,
    por_tenant,
)


@pytest.fixture(autouse=True)
def _limpio() -> Any:
    limpiar_estado()
    yield
    limpiar_estado()


# ── Late aunque no haya nada que barrer ───────────────────────────────────


async def test_una_tarea_sin_trabajo_deja_constancia_igual() -> None:
    """Si sólo se registrara al trabajar, una tarea parada y una sin trabajo se
    verían igual desde fuera — y ésa es justo la avería que no se ve."""
    await RelevoDeTareas([Tarea("vacia", 0, lambda: {"barridos": 0})]).una_vuelta()

    estado = estado_de_las_tareas()["vacia"]
    assert estado["vueltas"] == 1
    assert estado["desde_el_ultimo_exito_s"] is not None
    assert estado["averiada"] is False


async def test_cada_tarea_va_a_su_ritmo() -> None:
    """Una tarea que acaba de correr no vuelve a correr en la misma vuelta: el
    relevo se despierta a menudo y cada una decide si le toca."""
    corridas = []
    relevo = RelevoDeTareas([Tarea("lenta", 3_600, lambda: corridas.append(1) or {})])

    await relevo.una_vuelta()
    await relevo.una_vuelta()
    await relevo.una_vuelta()

    assert len(corridas) == 1, "ha corrido más veces de las que tocaba"


# ── El que falla deja su motivo, y a los tres es avería ───────────────────


async def test_tras_varios_fallos_seguidos_sale_como_averia_con_su_motivo() -> None:
    """Un contador no sirve para arreglar nada: hace falta el error."""

    def _rota() -> dict[str, Any]:
        raise RuntimeError("la base no contesta")

    relevo = RelevoDeTareas([Tarea("rota", 0, _rota)])
    for _ in range(FALLOS_PARA_AVERIA):
        await relevo.una_vuelta()

    estado = estado_de_las_tareas()["rota"]
    assert estado["averiada"] is True
    assert estado["fallos_seguidos"] == FALLOS_PARA_AVERIA
    assert "la base no contesta" in estado["ultimo_error"]


async def test_un_fallo_suelto_no_es_una_averia() -> None:
    """Dos fallos pueden ser la base reiniciándose. Dar la alarma a la primera
    gasta el crédito del monitor."""
    fallar = [True]

    def _intermitente() -> dict[str, Any]:
        if fallar[0]:
            fallar[0] = False
            raise RuntimeError("se cayó una vez")
        return {"ok": 1}

    relevo = RelevoDeTareas([Tarea("intermitente", 0, _intermitente)])
    await relevo.una_vuelta()
    assert estado_de_las_tareas()["intermitente"]["fallos_seguidos"] == 1

    await relevo.una_vuelta()
    estado = estado_de_las_tareas()["intermitente"]
    assert estado["fallos_seguidos"] == 0, "un éxito tiene que limpiar la cuenta"
    assert estado["ultimo_error"] == ""
    assert estado["averiada"] is False


async def test_una_tarea_que_revienta_no_tumba_el_relevo() -> None:
    """El relevo no se muere nunca: si lo hiciera, el primer fallo se llevaría
    por delante todas las demás tareas del servicio."""
    hechas = []

    def _rota() -> dict[str, Any]:
        raise RuntimeError("boom")

    relevo = RelevoDeTareas(
        [
            Tarea("rota", 0, _rota),
            Tarea("sana", 0, lambda: hechas.append(1) or {"ok": 1}),
        ]
    )
    await relevo.una_vuelta()

    assert hechas == [1], "la tarea sana no ha corrido después de la que revienta"


# ── Un tenant que falla no para a los demás ───────────────────────────────


def test_un_tenant_que_falla_no_para_a_los_siguientes() -> None:
    """Un fallo en el tenant 40 no puede parar a los 200 siguientes."""
    vistos = []

    def _trabajo(tenant: str) -> dict[str, Any]:
        if tenant == "b":
            raise RuntimeError("este tenant tiene el dato mal")
        vistos.append(tenant)
        return {}

    salida = por_tenant(lambda: ["a", "b", "c"], _trabajo)()

    assert vistos == ["a", "c"], "el fallo de «b» ha parado a «c»"
    assert salida == {"tenants": 2, "fallidos": 1}


def test_sin_tenants_que_barrer_no_falla(caplog: Any) -> None:
    """Cero tenants con trabajo es un caso normal, no un error."""
    salida = por_tenant(lambda: [], lambda _t: {})()
    assert salida == {"tenants": 0, "fallidos": 0}


# ── El monitor de salud lo enseña ─────────────────────────────────────────


async def test_la_averia_sale_en_la_pagina_de_estado() -> None:
    """En el monitor y no sólo en el log: un barrido que falla siempre en el
    mismo sitio y sigue en verde es otra avería silenciosa."""
    from crmcore.tareas import _componente_tareas

    def _rota() -> dict[str, Any]:
        raise RuntimeError("no hay quien la levante")

    relevo = RelevoDeTareas([Tarea("rota", 0, _rota)])
    for _ in range(FALLOS_PARA_AVERIA):
        await relevo.una_vuelta()

    salida = _componente_tareas(None, None)
    assert salida is not None
    assert salida["estado"] == "caido"
    assert "no hay quien la levante" in salida["detalle"]
    assert "rota" in salida["detalle"]


def test_un_servicio_sin_tareas_no_enseña_el_apartado() -> None:
    """Un componente vacío en la página de un servicio que no barre nada solo
    hace que se deje de mirar la página."""
    from crmcore.tareas import _componente_tareas

    assert _componente_tareas(None, None) is None


async def test_una_tarea_sin_estrenar_se_dice() -> None:
    """Sin completar todavía no es «bien»: importa el día del despliegue."""
    from crmcore.tareas import _componente_tareas

    def _rota() -> dict[str, Any]:
        raise RuntimeError("primera vuelta y ya falla")

    await RelevoDeTareas([Tarea("nueva", 0, _rota)]).una_vuelta()

    salida = _componente_tareas(None, None)
    assert salida is not None
    assert salida["estado"] == "degradado"
    assert "nueva" in salida["detalle"]
