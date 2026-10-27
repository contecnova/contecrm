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
    RelevoDeTareas,
    Tarea,
    _tarea_fallos_para_averia,
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
    for _ in range(_tarea_fallos_para_averia()):
        await relevo.una_vuelta()

    estado = estado_de_las_tareas()["rota"]
    assert estado["averiada"] is True
    assert estado["fallos_seguidos"] == _tarea_fallos_para_averia()
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
    assert salida["tenants"] == 2
    assert salida["fallidos"] == 1
    # CUÁL falló y por qué, no cuántos. La página de estado enseña esta salida,
    # y un «1» obliga a ir a buscar el registro del servidor — que es justo lo
    # que este módulo existe para evitar.
    assert salida["cuales"] == [
        {"tenant": "b", "error": "RuntimeError: este tenant tiene el dato mal"}
    ]


def test_sin_tenants_que_barrer_no_falla(caplog: Any) -> None:
    """Cero tenants con trabajo es un caso normal, no un error.

    La igualdad es exacta a propósito: la salida la pinta la página de estado,
    y un campo que aparece sin que nadie lo espere se queda sin sitio donde
    enseñarse. Por eso aquí está también `de_otro_pool`, que entró con el
    reparto por pool de cómputo — **cero no es lo mismo que ausente**: sin ese
    número, un proceso mal configurado barre cero tenants y su salida es
    idéntica a la de un sistema sin trabajo pendiente.
    """
    salida = por_tenant(lambda: [], lambda _t: {})()
    assert salida == {"tenants": 0, "fallidos": 0, "cuales": [], "de_otro_pool": 0}


# ── El monitor de salud lo enseña ─────────────────────────────────────────


async def test_la_averia_sale_en_la_pagina_de_estado() -> None:
    """En el monitor y no sólo en el log: un barrido que falla siempre en el
    mismo sitio y sigue en verde es otra avería silenciosa."""
    from crmcore.tareas import _componente_tareas

    def _rota() -> dict[str, Any]:
        raise RuntimeError("no hay quien la levante")

    relevo = RelevoDeTareas([Tarea("rota", 0, _rota)])
    for _ in range(_tarea_fallos_para_averia()):
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


def test_la_ficha_de_estado_cumple_el_contrato_de_los_componentes() -> None:
    """Las tres salidas, con su clave y con un estado de los válidos.

    Faltaba `componente` en las tres y el estado bueno decía «ok», que no es uno
    de los tres válidos. No se notaba porque el componente solo se registraba en
    los servicios que ya tenían tareas; apareció en cuanto los barridos del
    núcleo lo pusieron en los catorce, y entonces **reventó la página de estado
    entera** con un `KeyError`.

    Lo del estado era más silencioso y peor: el cálculo del peor estado recorre
    `("operativo", "degradado", "caido")`, así que un «ok» no casaba con nada y
    este componente no contaba para el estado global. Un componente que no suma
    es un componente que no avisa.
    """
    from crmcore.datos.estado import ESTADOS
    from crmcore.tareas import EstadoTarea, _componente_tareas, _estado

    for nombre in list(_estado):
        _estado.pop(nombre, None)

    # Sin tareas no hay ficha: un bloque vacío en un servicio que no barre nada
    # solo hace que se deje de mirar la página.
    assert _componente_tareas(None, None) is None

    casos = {
        "al día": EstadoTarea(ultimo_intento=1.0, ultimo_exito=1.0),
        # Con tiempo de sobra y sin un solo éxito: eso sí es «sin estrenar».
        "sin estrenar": EstadoTarea(ultimo_intento=1.0, primera_vez=1.0, intervalo_s=1.0),
        "averiada": EstadoTarea(ultimo_intento=1.0, fallos_seguidos=9, ultimo_error="revienta"),
    }
    for nombre, estado_tarea in casos.items():
        for otro in list(_estado):
            _estado.pop(otro, None)
        _estado["prueba.tarea"] = estado_tarea

        ficha = _componente_tareas(None, None)

        assert ficha is not None, nombre
        assert ficha["componente"] == "tareas_periodicas", f"«{nombre}» sin la clave obligatoria"
        assert ficha["estado"] in ESTADOS, (
            f"«{nombre}» devuelve el estado «{ficha['estado']}», que no es uno de "
            f"los válidos {ESTADOS}: no contaría para el estado global"
        )
        assert ficha["detalle"].strip(), f"«{nombre}» sin detalle"

    for nombre in list(_estado):
        _estado.pop(nombre, None)


def test_una_tarea_que_todavia_no_le_toca_no_sale_como_degradada() -> None:
    """Recién arrancado, NINGUNA purga ha corrido: es lo normal, no una avería.

    Las purgas esperan su primer intervalo a propósito —para no disparar catorce
    borrados masivos a la vez en un despliegue— así que contarlas como «sin
    estrenar» sacaba los catorce servicios en «degradado» durante el primer
    intervalo después de cada despliegue. Una página de estado que avisa en cada
    despliegue es una página que se deja de mirar.
    """
    import time as _t

    from crmcore.tareas import EstadoTarea, _componente_tareas, _estado

    for nombre in list(_estado):
        _estado.pop(nombre, None)

    ahora = _t.monotonic()
    # Vista hace un segundo, con un intervalo de una hora: todavía no le toca.
    _estado["prueba.purga"] = EstadoTarea(ultimo_intento=ahora, primera_vez=ahora, intervalo_s=3600)

    ficha = _componente_tareas(None, None)

    assert ficha is not None
    assert ficha["estado"] == "operativo", (
        f"una tarea que todavía no le toca sale como «{ficha['estado']}»: cada "
        "despliegue avisaría de una avería que no existe"
    )

    # Y con el intervalo vencido sí: lo que no puede es taparse para siempre.
    _estado["prueba.purga"] = EstadoTarea(
        ultimo_intento=ahora, primera_vez=ahora - 7200, intervalo_s=3600
    )
    assert _componente_tareas(None, None)["estado"] == "degradado", (
        "una tarea que lleva dos intervalos sin completarse tiene que decirse: "
        "si no, este arreglo tapa la avería que el componente existe para ver"
    )

    for nombre in list(_estado):
        _estado.pop(nombre, None)
