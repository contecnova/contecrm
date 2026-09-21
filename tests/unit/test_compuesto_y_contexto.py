"""Peticiones compuestas y acceso contextual
(CRM-00.02.01.13, CRM-00.05.01.09, CRM-00.02.02.08).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest
from crmcore.authz.contexto import Contexto, ReglaContextual, evaluar, exigir
from crmcore.errors import ErrorValidacion, Prohibido
from crmcore.http import compuesto

# ── Peticiones compuestas ─────────────────────────────────────────────────


def test_una_operacion_puede_usar_el_resultado_de_la_anterior() -> None:
    """Sin esto, agrupar no sirve para el caso que motiva agrupar: la segunda
    necesita el identificador que generó la primera."""
    resultados = [{"id": "cuenta-1"}]
    salida = compuesto.resolver({"cuenta_id": "$1.id", "nombre": "Ana"}, resultados)
    assert salida == {"cuenta_id": "cuenta-1", "nombre": "Ana"}


def test_referirse_a_una_operacion_posterior_se_rechaza_antes_de_correr() -> None:
    """Descubrirlo a mitad deja la transacción abortada y al cliente con un
    error que no dice cuál de sus operaciones estaba mal."""
    with pytest.raises(ErrorValidacion) as e:
        compuesto.validar(
            [
                {"metodo": "POST", "ruta": "/a", "cuerpo": {"x": "$2.id"}},
                {"metodo": "POST", "ruta": "/b"},
            ]
        )
    assert e.value.error_code == "compuesto.referencia_adelantada"


def test_referirse_a_si_misma_tambien() -> None:
    with pytest.raises(ErrorValidacion):
        compuesto.validar([{"metodo": "POST", "ruta": "/a", "cuerpo": {"x": "$1.id"}}])


def test_una_referencia_a_un_campo_que_no_vino_se_deja_visible() -> None:
    """Poner `None` crearía la fila con el campo vacío y nadie lo notaría hasta
    semanas después; dejarlo visible hace que falle la validación del recurso,
    que es donde tiene que fallar."""
    assert compuesto.resolver({"x": "$1.no_existe"}, [{"id": "1"}]) == {"x": "$1.no_existe"}


def test_hay_tope_de_operaciones() -> None:
    """Más que eso es una carga masiva, y para eso está el camino masivo con su
    trabajo diferido y su informe parcial."""
    muchas = [{"metodo": "POST", "ruta": "/a"}] * (compuesto.MAX_OPERACIONES + 1)
    with pytest.raises(ErrorValidacion) as e:
        compuesto.validar(muchas)
    assert e.value.error_code == "compuesto.demasiadas"


def test_una_peticion_vacia_se_rechaza() -> None:
    with pytest.raises(ErrorValidacion):
        compuesto.validar([])


def test_las_referencias_se_resuelven_tambien_dentro_de_listas() -> None:
    salida = compuesto.resolver({"ids": ["$1.id", "fijo"]}, [{"id": "x"}])
    assert salida == {"ids": ["x", "fijo"]}


# ── Acceso contextual ─────────────────────────────────────────────────────


def _ahora(hora: int) -> datetime:
    return datetime(2026, 9, 21, hora, 0, tzinfo=timezone.utc)


def test_una_ip_fuera_de_las_redes_no_pasa() -> None:
    regla = ReglaContextual(nombre="oficina", redes=("10.0.0.0/8",))
    assert evaluar(regla, Contexto(ip="10.1.2.3"))[0] is True
    assert evaluar(regla, Contexto(ip="80.1.2.3"))[0] is False


def test_una_senal_que_no_llega_no_bloquea() -> None:
    """Una IP que no llega porque hay un proxy mal configurado delante dejaría
    fuera a toda la plantilla, y eso es una caída con otro nombre."""
    regla = ReglaContextual(nombre="oficina", redes=("10.0.0.0/8",))
    assert evaluar(regla, Contexto(ip=""))[0] is True


def test_una_red_mal_escrita_no_deja_pasar_a_cualquiera() -> None:
    """Tratarla como comodín convertiría un error de tecleo en una lista de
    permitidos vacía."""
    regla = ReglaContextual(nombre="rota", redes=("no-es-una-red",))
    assert evaluar(regla, Contexto(ip="10.1.2.3"))[0] is False


def test_la_franja_horaria_que_cruza_medianoche_funciona() -> None:
    """El turno de noche existe, y escribirlo al revés es el error más común al
    configurar esto."""
    noche = ReglaContextual(nombre="noche", desde_hora=22, hasta_hora=6)
    assert evaluar(noche, Contexto(momento=_ahora(23)))[0] is True
    assert evaluar(noche, Contexto(momento=_ahora(3)))[0] is True
    assert evaluar(noche, Contexto(momento=_ahora(12)))[0] is False


def test_una_lista_vacia_no_comprueba_nada() -> None:
    """Una regla que bloquea porque la lista está vacía es la forma más rápida
    de dejar fuera a todo el mundo el día que alguien la crea sin rellenarla."""
    assert evaluar(ReglaContextual(nombre="vacia"), Contexto(ip="1.2.3.4"))[0] is True


def test_una_regla_desactivada_no_decide() -> None:
    regla = ReglaContextual(nombre="x", redes=("10.0.0.0/8",), activa=False)
    assert evaluar(regla, Contexto(ip="80.1.2.3"))[0] is True


def test_todas_las_reglas_tienen_que_cumplirse() -> None:
    """Con disyunción, añadir una regla permisiva anularía en silencio a una
    restrictiva ya existente, y nadie revisa las viejas al crear una nueva."""
    reglas = [
        ReglaContextual(nombre="red", redes=("10.0.0.0/8",)),
        ReglaContextual(nombre="pais", paises=("ES",)),
    ]
    exigir(reglas, Contexto(ip="10.1.2.3", pais="ES"))
    with pytest.raises(Prohibido) as e:
        exigir(reglas, Contexto(ip="10.1.2.3", pais="FR"))
    assert e.value.detalle["regla"] == "pais"


# ── Orden de eventos por agregado ─────────────────────────────────────────


def test_un_solo_evento_por_agregado_en_cada_vuelta() -> None:
    """Si el primer evento de una cuenta falla y se reintenta con espera, el
    segundo saldría antes: quien lo consuma vería «actualizada» antes que
    «creada» y se quedaría con el estado viejo para siempre."""
    from crmcore.bus.outbox import Relevo

    class _Fila:
        def __init__(self, tipo: str, sujeto: str) -> None:
            self.subject_tipo, self.subject_id, self.tipo = "cuenta", sujeto, tipo

    filas: list[Any] = [
        _Fila("cuenta.creada", "c1"),
        _Fila("cuenta.actualizada", "c1"),
        _Fila("cuenta.creada", "c2"),
    ]

    class _Ajustes:
        outbox_orden_por_agregado = True

    salida = Relevo.__dict__["_en_orden"](None, filas, _Ajustes())
    assert [f.tipo for f in salida] == ["cuenta.creada", "cuenta.creada"]


def test_se_puede_apagar_el_orden_para_ganar_rendimiento() -> None:
    from crmcore.bus.outbox import Relevo

    class _Fila:
        def __init__(self, sujeto: str) -> None:
            self.subject_tipo, self.subject_id = "cuenta", sujeto

    class _Ajustes:
        outbox_orden_por_agregado = False

    filas: list[Any] = [_Fila("c1"), _Fila("c1")]
    assert len(Relevo.__dict__["_en_orden"](None, filas, _Ajustes())) == 2
