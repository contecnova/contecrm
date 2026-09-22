"""Cohortes, embudo y correlación entre actividad y resultados
(CRM-05.01.03.04, .05, .06).

Tres análisis que en casi todos los CRM se hacen exportando a una hoja de cálculo,
y por eso se hacen mal: se pierde la definición, se pierde el periodo y nadie
puede repetirlos.

Los tres comparten una decisión: **los hechos los trae quien llama**. Las fechas
de alta, los cambios de etapa y las actividades viven en `party`, `sales` y el
almacén analítico; leerlos desde aquí exigiría entrar en el esquema de otro
servicio. Lo que aporta este módulo es el cálculo y —sobre todo— **decir cuándo un
número no significa nada**.

Y una regla que se repite en los tres: **un periodo incompleto no se compara con
uno completo**. La cohorte de este mes lleva cinco días, su retención a 30 días no
existe todavía, y ponerla en la misma tabla que la de hace un año hace que parezca
que todo empeora. Aquí sale marcada como inmadura, o no sale.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from crmcore.errors import ErrorValidacion
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Cómo se agrupa una cohorte. Cerrada: cada una tiene su forma de calcular el
# periodo siguiente, y «quincenal» o «cada 45 días» exigirían decidir qué pasa
# con los meses de 31 días.
PERIODOS = ("dia", "semana", "mes", "trimestre")

# Mínimo de sujetos para que un porcentaje signifique algo. Por debajo, una
# cohorte de tres clientes pasa del 100 % al 66 % porque uno se fue, y eso se lee
# como un desplome.
MINIMO_COHORTE = 5


def _redondear(valor: Decimal) -> Decimal:
    return Decimal(valor).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def _inicio_periodo(momento: date, periodo: str) -> date:
    if periodo == "dia":
        return momento
    if periodo == "semana":
        return momento - timedelta(days=momento.weekday())
    if periodo == "mes":
        return momento.replace(day=1)
    trimestre = (momento.month - 1) // 3
    return date(momento.year, trimestre * 3 + 1, 1)


def _siguiente(inicio: date, periodo: str, n: int = 1) -> date:
    if periodo == "dia":
        return inicio + timedelta(days=n)
    if periodo == "semana":
        return inicio + timedelta(weeks=n)
    meses = n if periodo == "mes" else n * 3
    mes = inicio.month - 1 + meses
    return date(inicio.year + mes // 12, mes % 12 + 1, 1)


def _a_fecha(valor: Any) -> date | None:
    if valor is None:
        return None
    if isinstance(valor, date) and not isinstance(valor, datetime):
        return valor
    if isinstance(valor, datetime):
        return valor.date()
    try:
        return datetime.fromisoformat(str(valor)).date()
    except ValueError:
        return None


# ── Cohortes y retención (CRM-05.01.03.04) ────────────────────────────────


def cohortes(
    *,
    sujetos: list[dict[str, Any]],
    periodo: str = "mes",
    periodos: int = 6,
    hoy: date | None = None,
    minimo: int = MINIMO_COHORTE,
) -> dict[str, Any]:
    """Retención por cohorte de alta (CRM-05.01.03.04).

    `sujetos` los trae quien llama: `{id, alta, actividad: [fechas]}` — o `baja`,
    si lo que se mide es permanencia. No se leen de ningún esquema ajeno.

    Tres decisiones que cambian lo que se lee:

    **Un periodo que aún no ha terminado no cuenta como caído.** La cohorte de
    este mes no ha tenido tiempo de volver; marcarla al 0 % la pinta como un
    desastre. Sale como `inmaduro`, y quien lea la tabla lo ve.

    **Una cohorte pequeña no da porcentaje.** Con tres clientes, uno que se va es
    un −33 % que se lee como un desplome. Se devuelve el recuento y se dice que no
    es significativa.

    **La retención se mide contra la propia cohorte**, no contra el total: si se
    midiera contra el total, una cohorte grande parecería mejor que una pequeña
    aunque se comportaran igual.
    """
    if periodo not in PERIODOS:
        raise ErrorValidacion(
            f"Periodo «{periodo}» no válido.",
            error_code="cohortes.periodo_no_valido",
            detalle={"validos": list(PERIODOS)},
        )
    ahora = hoy or datetime.now(timezone.utc).date()
    grupos: dict[date, list[dict[str, Any]]] = {}
    sin_alta = 0
    for sujeto in sujetos:
        alta = _a_fecha(sujeto.get("alta"))
        if alta is None:
            # Sin fecha de alta no hay cohorte posible. Meterlo en la primera
            # sería inventarse su origen.
            sin_alta += 1
            continue
        grupos.setdefault(_inicio_periodo(alta, periodo), []).append(sujeto)

    filas = []
    for inicio in sorted(grupos):
        miembros = grupos[inicio]
        celdas = []
        for n in range(periodos):
            desde = _siguiente(inicio, periodo, n)
            hasta = _siguiente(inicio, periodo, n + 1)
            inmaduro = hasta > ahora
            activos = 0
            for sujeto in miembros:
                fechas = [_a_fecha(f) for f in (sujeto.get("actividad") or [])]
                if any(f and desde <= f < hasta for f in fechas):
                    activos += 1
            celdas.append(
                {
                    "periodo": n,
                    "desde": str(desde),
                    "activos": activos,
                    "pct": (
                        float(_redondear(Decimal(100 * activos) / Decimal(len(miembros))))
                        if len(miembros) >= minimo and not inmaduro
                        else None
                    ),
                    # Dos motivos distintos para no dar porcentaje, y se
                    # distinguen: uno se arregla esperando y el otro no se
                    # arregla.
                    "inmaduro": inmaduro,
                    "poco_significativo": len(miembros) < minimo,
                }
            )
        filas.append(
            {
                "cohorte": str(inicio),
                "sujetos": len(miembros),
                "significativa": len(miembros) >= minimo,
                "celdas": celdas,
            }
        )

    return {
        "periodo": periodo,
        "periodos": periodos,
        "en_fecha": str(ahora),
        "cohortes": filas,
        "minimo_significativo": minimo,
        "sin_fecha_de_alta": sin_alta,
        # Con sujetos sin alta, la tabla no cuenta a todo el mundo: decirlo evita
        # que alguien sume las cohortes y le salga otro total.
        "concluyente": sin_alta == 0 and bool(filas),
        "aviso": (
            f"{sin_alta} sujetos sin fecha de alta quedan fuera de todas las cohortes."
            if sin_alta
            else ""
        ),
    }


# ── Embudo multi-etapa (CRM-05.01.03.05) ──────────────────────────────────


def embudo(
    *,
    etapas: list[str],
    recorridos: list[dict[str, Any]],
    hoy: date | None = None,
) -> dict[str, Any]:
    """Conversión y tiempos entre etapas (CRM-05.01.03.05).

    `recorridos` es una lista de `{id, pasos: [{etapa, fecha}], abierto}` — lo que
    cada oportunidad, lead o caso fue haciendo. Lo trae quien llama.

    Dos decisiones:

    **Lo abierto no cuenta como perdido.** Una oportunidad que está en la etapa 3
    no ha fallado en la 4: todavía no ha llegado. Contarla como caída hunde la
    tasa de las etapas finales y hace que parezca que el equipo cierra peor de lo
    que cierra. Se cuentan aparte.

    **El tiempo es la mediana, no la media.** Un solo negocio de dos años mueve la
    media de todo el trimestre y hace irreconocible el dato; la mediana dice lo que
    tarda un caso normal, que es la pregunta real.

    Y se devuelve el **mayor salto de caída**, porque la pregunta que sigue a
    «¿cómo va el embudo?» es siempre «¿dónde se atasca?».
    """
    if len(etapas) < 2:
        raise ErrorValidacion(
            "Un embudo necesita al menos dos etapas.", error_code="embudo.pocas_etapas"
        )
    ahora = hoy or datetime.now(timezone.utc).date()
    indice = {etapa: i for i, etapa in enumerate(etapas)}

    llegadas: list[int] = [0] * len(etapas)
    abiertos_en: list[int] = [0] * len(etapas)
    tiempos: list[list[int]] = [[] for _ in etapas]

    for recorrido in recorridos:
        pasos = [
            (str(p.get("etapa")), _a_fecha(p.get("fecha")))
            for p in (recorrido.get("pasos") or [])
            if str(p.get("etapa")) in indice
        ]
        pasos = [(e, f) for e, f in pasos if f is not None]
        pasos.sort(key=lambda p: p[1])  # type: ignore[arg-type,return-value]
        if not pasos:
            continue
        alcanzadas = {e for e, _ in pasos}
        for etapa in alcanzadas:
            llegadas[indice[etapa]] += 1
        ultima = max(alcanzadas, key=lambda e: indice[e])
        if recorrido.get("abierto"):
            abiertos_en[indice[ultima]] += 1
        for (etapa, fecha), (siguiente, fecha_siguiente) in zip(pasos, pasos[1:], strict=False):
            salto = indice[siguiente] - indice[etapa]
            if salto == 1 and fecha and fecha_siguiente:
                tiempos[indice[etapa]].append((fecha_siguiente - fecha).days)

    filas = []
    for i, etapa in enumerate(etapas):
        anterior = llegadas[i - 1] if i else llegadas[0]
        # Lo que se quedó por el camino, sin contar lo que sigue vivo en la etapa
        # anterior: eso no ha caído, está en curso.
        caidos = max(0, anterior - llegadas[i] - (abiertos_en[i - 1] if i else 0))
        dias = sorted(tiempos[i])
        filas.append(
            {
                "etapa": etapa,
                "llegaron": llegadas[i],
                "abiertos_aqui": abiertos_en[i],
                "conversion_desde_anterior": (
                    float(_redondear(Decimal(100 * llegadas[i]) / Decimal(anterior)))
                    if i and anterior
                    else None
                ),
                "caidos": caidos if i else 0,
                "dias_mediana": dias[len(dias) // 2] if dias else None,
                "medible": bool(dias),
            }
        )

    con_conversion = [f for f in filas if f["conversion_desde_anterior"] is not None]
    peor = min(con_conversion, key=lambda f: f["conversion_desde_anterior"], default=None)
    return {
        "en_fecha": str(ahora),
        "etapas": filas,
        "recorridos": len(recorridos),
        "abiertos": sum(abiertos_en),
        # La pregunta que sigue siempre a «¿cómo va el embudo?».
        "mayor_caida": (
            {
                "etapa": peor["etapa"],
                "conversion": peor["conversion_desde_anterior"],
                "caidos": peor["caidos"],
            }
            if peor
            else None
        ),
        "medible": bool(recorridos),
        "aviso": (
            ""
            if recorridos
            else "Sin recorridos en el periodo: no hay embudo, que es distinto de "
            "un embudo con conversión cero."
        ),
    }


# ── Actividad y resultados (CRM-05.01.03.06) ──────────────────────────────


def correlacion_actividad(
    *,
    sujetos: list[dict[str, Any]],
    metrica: str = "cerrado",
    minimo: int = 8,
) -> dict[str, Any]:
    """Relación entre lo que se hace y lo que se cierra (CRM-05.01.03.06).

    `sujetos` es `{id, actividades: n, <metrica>: valor}`. Devuelve la correlación
    de Pearson, **y todo lo que hace falta para no malinterpretarla**:

    **Correlación no es causa, y aquí se dice con todas las letras.** El comercial
    que cierra más hace más llamadas porque tiene más clientes interesados; obligar
    al resto a hacer el mismo número de llamadas no produce los mismos cierres. Un
    CRM que presenta esta cifra como una instrucción hace daño real: se acaba
    midiendo actividad en vez de resultados, y entonces la actividad se infla.

    **Con pocos sujetos no se calcula.** Con cinco comerciales, un valor atípico
    da 0,9 o −0,3 según quién esté de vacaciones.

    **Si no hay variación, no hay correlación.** Si todos hacen las mismas
    llamadas, el coeficiente no existe; devolver cero se leería como «no influye»,
    que es otra cosa.
    """
    validos = [
        s for s in sujetos if s.get("actividades") is not None and s.get(metrica) is not None
    ]
    if len(validos) < minimo:
        return {
            "medible": False,
            "sujetos": len(validos),
            "minimo": minimo,
            "porque": (
                f"Hacen falta al menos {minimo} sujetos: con menos, un valor atípico "
                "decide el resultado."
            ),
        }

    xs = [float(s["actividades"]) for s in validos]
    ys = [float(s[metrica]) for s in validos]
    n = len(xs)
    media_x, media_y = sum(xs) / n, sum(ys) / n
    sxx = sum((x - media_x) ** 2 for x in xs)
    syy = sum((y - media_y) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return {
            "medible": False,
            "sujetos": n,
            "porque": (
                "No hay variación en una de las dos series: si todos hacen lo mismo, "
                "la correlación no existe. Devolver cero se leería como «no influye», "
                "que es otra cosa."
            ),
        }
    sxy = sum((x - media_x) * (y - media_y) for x, y in zip(xs, ys, strict=True))
    r = sxy / (sxx**0.5 * syy**0.5)

    # Quién se sale de la recta. Es la parte accionable de verdad: el que hace
    # mucho y cierra poco necesita ayuda con la cualificación, no con el teléfono.
    pendiente = sxy / sxx
    corte = media_y - pendiente * media_x
    atipicos = []
    for sujeto, x, y in zip(validos, xs, ys, strict=True):
        esperado = pendiente * x + corte
        desvio = y - esperado
        if syy and abs(desvio) > (syy / n) ** 0.5:
            atipicos.append(
                {
                    "id": str(sujeto.get("id") or ""),
                    "actividades": x,
                    metrica: y,
                    "esperado": round(esperado, 2),
                    "por_encima": desvio > 0,
                }
            )

    return {
        "medible": True,
        "sujetos": n,
        "coeficiente": round(r, 3),
        "fuerza": ("fuerte" if abs(r) >= 0.7 else "moderada" if abs(r) >= 0.4 else "débil"),
        "actividades_media": round(media_x, 1),
        f"{metrica}_media": round(media_y, 2),
        "atipicos": atipicos,
        # Se devuelve con el número, no en la documentación: quien lea el panel no
        # va a leer la documentación.
        "aviso": (
            "Correlación no es causa. Quien más cierra suele hacer más actividad "
            "porque tiene más clientes interesados, no al revés: exigir el mismo "
            "número de llamadas al resto infla la actividad sin mover los cierres."
        ),
    }
