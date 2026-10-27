"""El eje de tiempo de una empresa sembrada se sostiene solo.

No se comprueba aquí que la siembra escriba en la base —eso lo hace
`scripts/sembrar_empresa.py --comprobar`, que recorre lo escrito y dice cuántas
filas miró—. Lo que se vigila aquí es el generador, que es donde estuvieron
**todos** los fallos de la primera carga y donde salen gratis:

  · una fecha que caía antes de aquello de lo que colgaba, porque el ajuste
    estacional de agosto restaba mes y medio sin mirar el suelo del intervalo:
    un contacto entre ciento cuarenta y cinco nacía antes que su propia
    empresa, invisible en pantalla;
  · todas las oportunidades abiertas parando a la misma altura, que dejaba el
    tablero con dos columnas vacías de cinco;
  · y un reparto de casos que daba el 76 % de SLA incumplido, porque las horas
    se sorteaban sueltas en vez de medirse contra el plazo de cada cliente.
"""

from __future__ import annotations

import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from scripts.datos_demo import (  # noqa: E402
    PRODUCTOS_DEMO,
    Reloj,
    activo_instalado,
    campanas,
    lineas_de_oferta,
    perfil_de_tecnico,
    reloj_de_caso,
    reparto_de_embudo,
)

ANCLA = datetime(2026, 10, 27, 9, 0, tzinfo=timezone.utc)


def test_nada_cae_antes_de_aquello_de_lo_que_cuelga() -> None:
    reloj = Reloj(anios=10, hoy=ANCLA)
    rnd = random.Random(1)
    # Agosto resta mes y medio, así que el caso se busca a propósito donde
    # dolía: un suelo justo después de un 1 de agosto.
    suelo = datetime(2024, 8, 2, tzinfo=timezone.utc)
    mirados = 0
    for _ in range(5_000):
        valor = reloj.momento(rnd, desde=suelo, sesgo=1.0)
        assert valor >= suelo, f"{valor} cae antes de {suelo}"
        assert valor <= reloj.hoy
        mirados += 1
    # Sin esto, un generador que devolviera siempre el suelo pasaría la prueba.
    assert mirados == 5_000
    assert len({reloj.momento(rnd, desde=suelo).date() for _ in range(200)}) > 50


def test_el_sesgo_empuja_a_lo_reciente_y_el_plano_no() -> None:
    reloj = Reloj(anios=10, hoy=ANCLA)
    rnd = random.Random(2)
    mitad = reloj.desde + (reloj.hoy - reloj.desde) / 2
    sesgadas = sum(reloj.momento(rnd) > mitad for _ in range(2_000))
    planas = sum(reloj.momento(rnd, sesgo=1.0) > mitad for _ in range(2_000))
    # Un negocio crece: con el reparto plano los gráficos salen como una barra.
    assert sesgadas > 1_200, sesgadas
    # Y el plano reparte: aplicado dos veces, un sistema de diez años no tenía
    # ni una oportunidad antes del sexto.
    assert 850 < planas < 1_150, planas


def test_el_embudo_se_recorre_entero_y_hasta_donde_haya_etapas() -> None:
    rnd = random.Random(3)
    repartos = [reparto_de_embudo(rnd, 5) for _ in range(1_000)]
    estados = [e for e, _ in repartos]
    # Ni todo se gana ni todo se pierde: una demostración con el 90 % ganado no
    # se le puede enseñar a nadie que venda.
    assert 0.2 < estados.count("ganada") / len(estados) < 0.4
    assert estados.count("abierta") and estados.count("perdida")
    # Las no ganadas reparten por TODAS las etapas del embudo que se le pase.
    # Con un tope fijo de tres, un pipeline de cinco etapas abiertas salía con
    # dos columnas vacías.
    profundidades = {p for e, p in repartos if e != "ganada"}
    assert profundidades == {1, 2, 3, 4, 5}, profundidades
    # Una ganada recorre el embudo entero: no se gana sin negociar.
    assert all(p == 0 for e, p in repartos if e == "ganada")
    assert {p for e, p in reparto_pocas(rnd)} <= {1, 2}


def reparto_pocas(rnd: random.Random) -> list[tuple[str, int]]:
    return [r for r in (reparto_de_embudo(rnd, 2) for _ in range(200)) if r[0] != "ganada"]


def test_los_casos_se_miden_contra_su_propio_plazo() -> None:
    rnd = random.Random(4)
    viejos = [reloj_de_caso(rnd, antiguo=True) for _ in range(1_000)]
    nuevos = [reloj_de_caso(rnd, antiguo=False) for _ in range(1_000)]
    # Lo que lleva meses abierto es la excepción, no el 22 %: con una
    # probabilidad fija, uno de cada cinco casos de hace seis años seguía
    # abierto y llevaba incumplido desde entonces.
    assert sum(c for c, *_ in viejos) > 940
    assert 450 < sum(c for c, *_ in nuevos) < 650
    # Y la mayoría cumple. En horas sueltas, un cliente oro con ocho horas de
    # compromiso incumplía casi siempre y el panel salía con el 76 % en rojo.
    cumplen = sum(1 for _c, _r, factor in viejos if factor <= 1)
    assert 0.78 < cumplen / len(viejos) < 0.9, cumplen / len(viejos)


def test_toda_oferta_vende_algo_del_catalogo() -> None:
    rnd = random.Random(5)
    skus = {p[0] for p in PRODUCTOS_DEMO}
    familias = {p[2] for p in PRODUCTOS_DEMO}
    # Varias familias: con una sola, el informe de margen por familia no tiene
    # nada que separar.
    assert len(familias) >= 3
    lineas = [ln for _ in range(300) for ln in lineas_de_oferta(rnd)]
    assert lineas
    assert all(ln["sku"] in skus for ln in lineas)
    assert all(ln["cantidad"] >= 1 for ln in lineas)
    assert {ln["descuento_pct"] for ln in lineas} != {0}


def test_las_campanas_ni_gastan_todas_lo_mismo_ni_lo_presupuestado() -> None:
    rnd = random.Random(6)
    reloj = Reloj(anios=10, hoy=ANCLA)
    lista = campanas(rnd, reloj, 4)
    assert len({c["anio"] for c in lista}) >= 10
    assert len({c["canal"] for c in lista}) > 1
    pasadas = [c for c in lista if c["gasto"] > c["presupuesto"]]
    cortas = [c for c in lista if 0 < c["gasto"] < c["presupuesto"]]
    # Si todas gastaran lo presupuestado, la pantalla de consumo no tendría
    # nada que decir, que es justo para lo que está.
    assert pasadas and cortas
    # Y ninguna empieza en el futuro con gasto ya hecho.
    assert all(c["gasto"] == 0 for c in lista if c["inicio"] > reloj.hoy)


def test_el_parque_y_los_tecnicos_salen_completos() -> None:
    rnd = random.Random(7)
    reloj = Reloj(anios=10, hoy=ANCLA)
    cuando = reloj.hoy - timedelta(days=400)
    activos = [activo_instalado(rnd, cuando) for _ in range(100)]
    assert all(a["instalado_el"] == cuando.date() for a in activos)
    assert len({a["numero_serie"] for a in activos}) == 100, "dos máquinas con la misma serie"
    assert len({a["zona"] for a in activos}) > 1
    tecnicos = [perfil_de_tecnico(rnd, i) for i in range(10)]
    assert all(t["competencias"] for t in tecnicos)
    assert len({t["zonas"][0] for t in tecnicos}) > 1, "todos los técnicos en la misma zona"
