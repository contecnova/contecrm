#!/usr/bin/env python3
"""El eje de tiempo de una empresa sembrada, y las capas que no tenía ninguna
(CRM-07.04.05.06).

Esto **no** es un segundo sembrador. `scripts/sembrar_empresa.py` ya compone
una empresa con volumen y variedad —nombres, sectores, poblaciones, CIF,
plantilla, facturación derivada de la plantilla—, y repetir ese vocabulario
aquí habría dejado dos catálogos de empresas que se separan a la primera
corrección. Lo que aquí se añade es lo que allí no había:

  · **Diez años.** Todo se creaba hoy: las actividades entre −90 y +45 días,
    los casos en los últimos 120 y las oportunidades en ±210. Con eso no se
    puede enseñar ni una evolución anual, ni un ciclo medio de venta, ni una
    comparación con el año pasado — y son tres de las pantallas que más se
    miran. `Reloj` reparte cualquier fecha sobre el periodo entero, con más
    peso en lo reciente, menos en agosto y **nunca antes de aquello de lo que
    cuelga**.
  · **El recorrido, no solo el destino.** Una oportunidad ganada sin historial
    de etapas no dice cuánto tardó en cada una, que es de lo que vive el
    informe de embudo.
  · **Lo que se vendió.** Un catálogo de productos, para que un importe de
    180.000 € tenga líneas debajo y el margen por familia salga de algo.
  · **El gasto de marketing** y **el parque instalado**, que son las dos
    familias que quedaban sin un solo registro.

Todo sale de un `random.Random` que recibe quien llama, para que la empresa
siga siendo la misma con la misma semilla: dos demostraciones de la misma
versión tienen que enseñar lo mismo, o el comercial que preparó la suya ayer no
encuentra hoy la cuenta que iba a abrir.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

# ── El eje de tiempo ─────────────────────────────────────────────────────


class Reloj:
    """De cuándo a cuándo pasan las cosas, y con qué reparto."""

    def __init__(self, anios: int = 10, hoy: datetime | None = None) -> None:
        # El mundo se ancla a HOY a propósito: una demostración cuyos datos
        # envejecen deja de enseñar «el mes pasado» al mes siguiente. `hoy`
        # permite fijar el ancla, que es lo que necesitan las pruebas para
        # comparar fecha a fecha.
        self.anios = max(1, anios)
        self.hoy = hoy or datetime.now(timezone.utc)
        self.desde = self.hoy - timedelta(days=365 * self.anios)

    def momento(
        self, rnd: random.Random, *, desde: datetime | None = None, sesgo: float = 0.6
    ) -> datetime:
        """Un instante del periodo, por defecto con más peso en lo reciente.

        Si todos los años pesaran igual, los gráficos saldrían planos y el
        primero que los mire sabría que son inventados: un negocio crece.

        `sesgo=1.0` reparte plano, y es lo que se usa para lo que cuelga de una
        cuenta. Aplicar el sesgo dos veces —una a la cuenta y otra a su
        oportunidad— empujaba todo tan al final que un sistema de **diez** años
        no tenía ni una sola oportunidad antes del sexto. El crecimiento sigue
        estando, porque las cuentas sí nacen sesgadas y cada una arrastra las
        suyas.
        """
        inicio = desde or self.desde
        margen = max(1, int((self.hoy - inicio).total_seconds()))
        momento = inicio + timedelta(seconds=int(margen * (rnd.random() ** sesgo)))
        # Agosto baja: la estacionalidad es lo primero que se nota cuando no
        # está, porque un negocio no factura igual en agosto que en octubre.
        if momento.month == 8 and rnd.random() < 0.6:
            momento -= timedelta(days=45)
        # Y nunca antes de aquello de lo que cuelga. El ajuste de agosto se come
        # mes y medio, y eso bastaba para que un contacto naciera antes que su
        # propia cuenta: un caso entre ciento cuarenta y cinco, que es justo la
        # clase de cosa que no se ve mirando la pantalla.
        return max(momento, inicio)

    def dentro_del_periodo(self, valor: datetime) -> bool:
        return self.desde <= valor <= self.hoy


# ── Cómo se reparte un embudo de verdad ──────────────────────────────────


def reparto_de_embudo(rnd: random.Random, etapas_abiertas: int = 3) -> tuple[str, int]:
    """En qué acabó una oportunidad y hasta qué etapa llegó.

    Se pierde más de lo que se gana y una parte sigue abierta: una
    demostración donde la mayoría se gana no se le puede enseñar a nadie que
    venda, porque el informe de conversión sale en el 90 % y lo primero que
    hace quien lo ve es dejar de creerse el resto.

    Y la profundidad varía **con las etapas que tenga ese embudo**. Con un
    número fijo, todas las abiertas se quedaban en las tres primeras y un
    pipeline de cinco etapas abiertas salía con dos columnas vacías: ni una
    sola oportunidad en «Negociación» ni en «Pendiente de adjudicación», que
    son justo las dos que se miran al final del trimestre. Una ganada sí
    recorre el embudo entero: no se gana sin negociar.
    """
    estado = rnd.choices(("ganada", "perdida", "abierta"), weights=(28, 47, 25))[0]
    if estado == "ganada":
        return estado, 0  # 0 = hasta el final; lo resuelve quien conoce el pipeline
    tope = max(1, etapas_abiertas)
    # Pesos decrecientes: cuanto más avanzada la etapa, menos llegan. Un embudo
    # donde queda tanta gente al final como al principio no es un embudo.
    pesos = [max(1, tope - i) for i in range(tope)]
    return estado, rnd.choices(range(1, tope + 1), weights=pesos)[0]


def reloj_de_caso(rnd: random.Random, *, antiguo: bool) -> tuple[bool, float, float]:
    """Si el caso se cerró, y cuánto tardó **medido en su propio SLA**.

    En horas sueltas, un cliente oro con ocho horas de compromiso incumplía
    casi siempre y el panel de SLA salía con el 76 % en rojo: un servicio así
    no existe, y una pantalla que lo enseña no sirve para nada. Los factores se
    aplican sobre el margen que le haya tocado, que lo sabe el servicio de
    atención y no este generador.

    Y lo que lleva meses abierto es la excepción, no el 22 %: con una
    probabilidad fija, uno de cada cinco casos de hace seis años seguía abierto
    y su plazo llevaba incumplido desde entonces.
    """
    cerrado = rnd.random() < (0.97 if antiguo else 0.55)
    cumple = rnd.random() < 0.84
    factor_resolucion = rnd.uniform(0.15, 0.9) if cumple else rnd.uniform(1.2, 3.5)
    factor_respuesta = rnd.uniform(0.1, 0.85) if rnd.random() < 0.91 else rnd.uniform(1.1, 2.5)
    return cerrado, factor_respuesta, factor_resolucion


# ── El catálogo que se vende ─────────────────────────────────────────────

# Con familias de verdad: el informe de margen por familia y las reglas de
# precio no se pueden enseñar con un solo producto.
PRODUCTOS_DEMO: tuple[tuple[str, str, str, int, int, str, str | None], ...] = (
    ("SRV-INST", "Instalación llave en mano", "Servicios", 18_500, 12_000, "puntual", None),
    ("SRV-PM", "Mantenimiento preventivo anual", "Servicios", 9_800, 5_400, "recurrente", "anual"),
    ("SRV-SOP", "Soporte 24×7", "Servicios", 1_250, 700, "recurrente", "mensual"),
    ("SRV-AUD", "Auditoría técnica", "Servicios", 4_200, 2_100, "puntual", None),
    ("EQ-CT100", "Centralita CT-100", "Equipos", 7_400, 5_100, "puntual", None),
    ("EQ-CT250", "Centralita CT-250", "Equipos", 15_900, 10_800, "puntual", None),
    ("EQ-SEN", "Sensor industrial", "Equipos", 380, 190, "puntual", None),
    ("EQ-ARM", "Armario de control", "Equipos", 2_900, 1_750, "puntual", None),
    ("LIC-BASE", "Licencia plataforma", "Licencias", 6_000, 900, "recurrente", "anual"),
    ("LIC-PLUS", "Licencia plataforma Plus", "Licencias", 11_500, 1_600, "recurrente", "anual"),
    ("FOR-OP", "Formación de operadores", "Formación", 2_400, 1_100, "puntual", None),
    ("FOR-ADM", "Formación de administradores", "Formación", 3_600, 1_500, "puntual", None),
)

EQUIPOS = tuple(p for p in PRODUCTOS_DEMO if p[2] == "Equipos")


def lineas_de_oferta(rnd: random.Random) -> list[dict[str, Any]]:
    """Qué se le ofreció. Sin líneas, una venta de 180.000 € no dice qué se vendió."""
    return [
        {
            "sku": sku,
            "cantidad": rnd.randrange(1, 9 if familia != "Servicios" else 3),
            "descuento_pct": rnd.choice((0, 0, 0, 5, 10, 15)),
        }
        for sku, _nombre, familia, *_resto in rnd.sample(PRODUCTOS_DEMO, rnd.randrange(1, 5))
    ]


# ── Marketing: el gasto, que no es el presupuesto ────────────────────────

CANALES_CAMPANA = ("email", "eventos", "buscadores", "social", "telemarketing")
TEMAS_CAMPANA = (
    "Captación industria",
    "Renovación de contratos",
    "Jornadas técnicas",
    "Lanzamiento de servicio",
    "Reactivación de inactivos",
)


def campanas(rnd: random.Random, reloj: Reloj, por_anio: int = 4) -> list[dict[str, Any]]:
    """Una campaña por canal y año, con su presupuesto y su consumo.

    El gasto no es el presupuesto: unas se pasan y otras no llegan, que es
    justo lo que se mira en el informe de consumo. Si todas gastaran lo
    presupuestado, la pantalla no tendría nada que enseñar.
    """
    salida: list[dict[str, Any]] = []
    for anio in range(reloj.desde.year, reloj.hoy.year + 1):
        for _ in range(por_anio):
            canal = rnd.choice(CANALES_CAMPANA)
            tema = rnd.choice(TEMAS_CAMPANA)
            inicio = datetime(anio, rnd.randrange(1, 13), rnd.randrange(1, 28), tzinfo=timezone.utc)
            presupuesto = Decimal(rnd.randrange(3_000, 90_000))
            gasto = (presupuesto * Decimal(rnd.randrange(60, 131)) / Decimal(100)).quantize(
                Decimal("0.01")
            )
            if inicio > reloj.hoy:
                # Una campaña que aún no ha empezado no ha gastado nada.
                gasto = Decimal(0)
            salida.append(
                {
                    "clave": f"{canal}-{tema.split()[0].lower()}-{anio}-{len(salida)}",
                    "nombre": f"{tema} {anio} ({canal})",
                    "canal": canal,
                    "anio": anio,
                    "inicio": inicio,
                    "fin": inicio + timedelta(days=rnd.randrange(30, 180)),
                    "presupuesto": presupuesto,
                    "gasto": gasto,
                }
            )
    return salida


# ── Servicio de campo ────────────────────────────────────────────────────

ZONAS = ("norte", "sur", "centro", "levante", "noroeste")
COMPETENCIAS = ("electricidad", "mecanica", "automatizacion", "redes", "climatizacion")


def activo_instalado(rnd: random.Random, cuando: datetime) -> dict[str, Any]:
    """Una máquina en casa del cliente.

    Es lo que da sentido a un caso de avería y a una orden de trabajo: sin
    parque instalado, el servicio de campo enseña órdenes que no mantienen
    nada.
    """
    sku, nombre, *_ = rnd.choice(EQUIPOS)
    return {
        "nombre": nombre,
        "modelo": sku,
        "numero_serie": f"{sku}-{rnd.randrange(100000, 999999)}",
        "instalado_el": cuando.date(),
        "ubicacion": f"Planta {rnd.choice('ABC')}, nave {rnd.randrange(1, 6)}",
        "zona": rnd.choice(ZONAS),
    }


def perfil_de_tecnico(rnd: random.Random, indice: int) -> dict[str, Any]:
    return {
        "zonas": [ZONAS[indice % len(ZONAS)]],
        "competencias": sorted(rnd.sample(COMPETENCIAS, rnd.randrange(1, 4))),
        "minutos_jornada": rnd.choice((420, 480, 480, 540)),
    }
