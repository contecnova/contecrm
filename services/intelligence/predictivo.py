"""Modelos entrenados con el histórico del CRM, de verdad
(CRM-02.01.02.02, CRM-05.02.01.02, CRM-05.02.01.03, CRM-02.01.01.08).

**Lo que había antes, medido el 09-11-2026.** `POST /ia/modelos` registraba
pesos que alguien tecleaba, `POST /ia/prediccion` aplicaba una sigmoide a unos
rasgos que también se tecleaban, y el importe y la fecha de cierre salían como
un porcentaje. Constaba «entrenado con el histórico» y no había ningún
histórico: había una calculadora.

Lo de aquí lee el histórico del CRM **por su API** —leads convertidos y
descartados, oportunidades ganadas y perdidas con sus importes y fechas, las
líneas de lo ganado por cuenta—, entrena, mide contra un periodo que el modelo
no ha visto y **no publica lo que no supera el mínimo configurado**. Y puntúa
registros reales por su identificador, explicando los factores.

Las decisiones:

**Sin dependencias nuevas.** No hay numpy ni scikit-learn en el entorno, y
meterlos por esto sería una dependencia pesada para cuatro modelos lineales. La
regresión logística se ajusta por Newton (IRLS) y la lineal por mínimos
cuadrados con regularización, resolviendo el sistema a mano: con diez o veinte
variables son milisegundos. Son modelos sencillos **a propósito**: cada peso se
puede enseñar como un porqué.

**Las mismas funciones para entrenar y para puntuar.** Los rasgos de un registro
se calculan con el mismo código en los dos momentos. Que el entrenamiento y la
puntuación calculen distinto es la manera más común de que un modelo que
validó bien puntúe mal en producción.

**Sin mirar el futuro.** Los rasgos de una oportunidad son los que se sabían
cuando se abrió: cuántas ganó y perdió esa cuenta ANTES, no después. La etapa,
la probabilidad tecleada o el motivo de pérdida no entran: dicen cómo acabó.

**Separado por fecha.** Se entrena con lo viejo y se mide con lo nuevo, que es
lo que le pasará en producción. El modelo publicado es exactamente el medido.

**Con pocos datos, se dice.** No se publica un modelo con cuarenta casos ni uno
que no le gana a «decir siempre lo mismo».
"""

from __future__ import annotations

import math
from bisect import bisect_left
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from crmcore.db.base import Base, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import ErrorDependencia, ErrorValidacion, NoEncontrado
from crmcore.fechas import hoy as hoy_del_cliente
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import Boolean, DateTime, String, Text, UniqueConstraint, select
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from services.intelligence import gobierno as gob

logger = get_logger(__name__)

# Qué modelos se entrenan aquí y sobre qué objeto puntúan.
ENTRENABLES: dict[str, str] = {
    "scoring_lead": "lead",
    "cierre": "oportunidad",
    "importe": "oportunidad",
    "fecha_cierre": "oportunidad",
    "propension": "cuenta",
    "siguiente_oferta": "cuenta",
}

# Lo que se lee del CRM para entrenar con permisos de sólo lectura. El
# entrenamiento es del tenant entero —un modelo que aprendiera sólo de lo que
# ve quien pulsa el botón cambiaría según quién lo pulse— y por eso no lleva la
# compartición de una persona; sí lleva su identificador para el rastro.
PERMISOS_DE_LECTURA = ("lead:read", "opportunity:read")

# El listado de oportunidades enseña por defecto sólo las abiertas
# (`estado=abierta`): para aprender de lo ganado y lo perdido hay que pedirlas
# todas, y se pide así —estado vacío— porque es como lo admite el propio listado.
TODAS: dict[str, Any] = {"estado": ""}

# Cómo se llama cada rasgo en pantalla. Son los rasgos de ESTE módulo, no
# campos del CRM: el nombre técnico no le dice nada a quien lee el porqué.
ETIQUETAS = {
    "log_importe": "Importe de la oportunidad",
    "cuenta_ganadas_previas": "Ventas ganadas antes a esta cuenta",
    "cuenta_perdidas_previas": "Ventas perdidas antes con esta cuenta",
    "cuenta_tasa_previa": "Tasa de éxito previa con esta cuenta",
    "propietario_tasa_previa": "Tasa de éxito previa del comercial",
    "log_importe_medio_cuenta": "Importe medio ganado antes a esta cuenta",
    "tiene_contacto": "Tiene contacto asignado",
    "viene_de_lead": "Viene de un lead convertido",
    "embudo": "Embudo",
    "origen": "Origen",
    "pais": "País",
    "tiene_email": "Tiene email",
    "tiene_telefono": "Tiene teléfono",
    "tiene_web": "Tiene web",
    "tiene_cargo": "Tiene cargo",
    "tiene_empresa": "Tiene empresa",
    "de_campana": "Viene de una campaña",
    "con_utm": "Llegó con parámetros de campaña",
    "con_propietario": "Tiene comercial asignado",
    "ganadas_previas": "Ventas ganadas hasta hoy",
    "perdidas_previas": "Ventas perdidas hasta hoy",
    "abiertas": "Oportunidades abiertas ahora",
    "log_importe_ganado": "Importe ganado hasta hoy",
    "dias_desde_ultima_ganada": "Días desde la última venta ganada",
    "antiguedad_dias": "Antigüedad como cliente (días)",
}


# ── Ajustes: una lectura por llamada, nunca dentro de un bucle ───────────


def _ajuste(clave: str, db: Any = None) -> Any:
    """Un ajuste del servicio; con sesión, el del tenant si lo ha cambiado."""
    from services.intelligence.ajustes import ajustes

    defecto = getattr(ajustes(), clave)
    if db is None:
        return defecto
    from crmcore.runtime import settings as rt

    try:
        valor = rt.efectivo(clave, db)
    except Exception:  # noqa: BLE001 — una clave sin registrar cae al .env
        valor = None
    return defecto if valor is None else type(defecto)(valor)


# ── Matemáticas, sin dependencias ────────────────────────────────────────


def resolver(matriz: list[list[float]], vector: list[float]) -> list[float]:
    """Resuelve A·x = b por eliminación gaussiana con pivote parcial.

    Con la regularización la matriz es definida positiva, así que el pivote
    nulo sólo aparece en casos degenerados: se trata como cero en vez de
    reventar, que es lo mismo que haría un ridge con una columna constante.
    """
    n = len(vector)
    a = [list(fila) + [vector[i]] for i, fila in enumerate(matriz)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[piv][col]) < 1e-12:
            continue
        a[col], a[piv] = a[piv], a[col]
        for r in range(n):
            if r == col:
                continue
            f = a[r][col] / a[col][col]
            if f:
                fila_r, fila_c = a[r], a[col]
                for k in range(col, n + 1):
                    fila_r[k] -= f * fila_c[k]
    return [a[i][n] / a[i][i] if abs(a[i][i]) >= 1e-12 else 0.0 for i in range(n)]


def _sigmoide(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-35.0, min(35.0, x))))


def ajustar_logistica(
    x: list[list[float]], y: list[int], *, l2: float, iteraciones: int
) -> tuple[list[float], float]:
    """Regresión logística por Newton (IRLS) con regularización L2.

    El sesgo no se regulariza: castigarlo empuja todas las probabilidades
    hacia el 50 % y el modelo parece más prudente de lo que es.
    """
    d = len(x[0]) if x else 0
    beta = [0.0] * (d + 1)  # último = sesgo
    for _ in range(max(1, iteraciones)):
        grad = [0.0] * (d + 1)
        hess = [[0.0] * (d + 1) for _ in range(d + 1)]
        for fila, yi in zip(x, y, strict=True):
            z = beta[d] + sum(b * v for b, v in zip(beta, fila, strict=False))
            p = _sigmoide(z)
            w = max(p * (1 - p), 1e-9)
            ext = [*fila, 1.0]
            r = yi - p
            for i in range(d + 1):
                grad[i] += r * ext[i]
                wi = w * ext[i]
                hi = hess[i]
                for j in range(i, d + 1):
                    hi[j] += wi * ext[j]
        for i in range(d + 1):
            for j in range(i):
                hess[i][j] = hess[j][i]
        for i in range(d):
            grad[i] -= l2 * beta[i]
            hess[i][i] += l2
        paso = resolver(hess, grad)
        beta = [b + s for b, s in zip(beta, paso, strict=True)]
        if max(abs(s) for s in paso) < 1e-6:
            break
    return beta[:d], beta[d]


def ajustar_lineal(x: list[list[float]], y: list[float], *, l2: float) -> tuple[list[float], float]:
    """Mínimos cuadrados con regularización L2 (ridge), sesgo sin castigar."""
    d = len(x[0]) if x else 0
    ata = [[0.0] * (d + 1) for _ in range(d + 1)]
    aty = [0.0] * (d + 1)
    for fila, yi in zip(x, y, strict=True):
        ext = [*fila, 1.0]
        for i in range(d + 1):
            aty[i] += ext[i] * yi
            for j in range(d + 1):
                ata[i][j] += ext[i] * ext[j]
    for i in range(d):
        ata[i][i] += l2
    beta = resolver(ata, aty)
    return beta[:d], beta[d]


def auc(puntuaciones: list[float], etiquetas: list[int]) -> float | None:
    """Área bajo la curva ROC por rangos (Mann-Whitney), con empates a medias.

    `None` si falta una de las dos clases: no hay nada que ordenar, y un 0,5
    ahí parecería una medida.
    """
    pares = sorted(zip(puntuaciones, etiquetas, strict=True), key=lambda t: t[0])
    pos = sum(1 for _, e in pares if e == 1)
    neg = len(pares) - pos
    if not pos or not neg:
        return None
    suma_rangos = 0.0
    i = 0
    while i < len(pares):
        j = i
        while j + 1 < len(pares) and pares[j + 1][0] == pares[i][0]:
            j += 1
        rango = (i + j) / 2 + 1
        suma_rangos += rango * sum(1 for k in range(i, j + 1) if pares[k][1] == 1)
        i = j + 1
    return (suma_rangos - pos * (pos + 1) / 2) / (pos * neg)


def metricas_clasificacion(
    prob: list[float], y: list[int], *, umbral: float = 0.5
) -> dict[str, Any]:
    """AUC, precisión, exhaustividad y la regla tonta al lado."""
    tp = sum(1 for p, e in zip(prob, y, strict=True) if p >= umbral and e == 1)
    fp = sum(1 for p, e in zip(prob, y, strict=True) if p >= umbral and e == 0)
    fn = sum(1 for p, e in zip(prob, y, strict=True) if p < umbral and e == 1)
    aciertos = sum(1 for p, e in zip(prob, y, strict=True) if (p >= umbral) == (e == 1))
    base = sum(y) / len(y) if y else 0.0
    valor_auc = auc(prob, y)
    return {
        "auc": round(valor_auc, 4) if valor_auc is not None else None,
        "precision": round(tp / (tp + fp), 4) if tp + fp else 0.0,
        "recall": round(tp / (tp + fn), 4) if tp + fn else 0.0,
        "acierto": round(aciertos / len(y), 4) if y else 0.0,
        "acierto_regla_tonta": round(max(base, 1 - base), 4),
        "tasa_base": round(base, 4),
        "brier": round(sum((p - e) ** 2 for p, e in zip(prob, y, strict=True)) / len(y), 4)
        if y
        else 0.0,
        "muestras": len(y),
    }


def _mediana(valores: list[float]) -> float:
    o = sorted(valores)
    if not o:
        return 0.0
    m = len(o) // 2
    return o[m] if len(o) % 2 else (o[m - 1] + o[m]) / 2


def _cuantil(valores: list[float], q: float) -> float:
    o = sorted(valores)
    if not o:
        return 0.0
    pos = (len(o) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return o[lo] + (o[hi] - o[lo]) * (pos - lo)


def metricas_regresion(
    predichos: list[float], reales: list[float], *, referencia: float
) -> dict[str, Any]:
    """Error medio contra la regla tonta: decir siempre la mediana del entreno."""
    n = len(reales)
    mae = sum(abs(p - r) for p, r in zip(predichos, reales, strict=True)) / n if n else 0.0
    mae_base = sum(abs(referencia - r) for r in reales) / n if n else 0.0
    return {
        "mae": round(mae, 2),
        "mae_mediana": round(mae_base, 2),
        "mejora_pct": round((1 - mae / mae_base) * 100, 1) if mae_base else 0.0,
        "error_mediano": round(
            _mediana([abs(p - r) for p, r in zip(predichos, reales, strict=True)]), 2
        ),
        "muestras": n,
    }


# ── Escalado y categorías: la «definición» que viaja con el modelo ───────


def preparar(
    filas: list[dict[str, Any]],
    *,
    numericas: list[str],
    categoricas: list[str],
    max_categorias: int,
    minimo_por_categoria: int,
) -> dict[str, Any]:
    """Cómo se convierte un caso en números, aprendido SÓLO del entrenamiento.

    Las medias y las categorías salen de lo que el modelo ve al entrenar: si
    salieran de todo, el periodo de validación se colaría por el escalado.
    """
    escalas: dict[str, list[float]] = {}
    for v in numericas:
        vals = [float(f.get(v) or 0.0) for f in filas]
        media = sum(vals) / len(vals) if vals else 0.0
        var = sum((x - media) ** 2 for x in vals) / len(vals) if vals else 0.0
        escalas[v] = [media, math.sqrt(var) or 1.0]
    categorias: dict[str, list[str]] = {}
    for c in categoricas:
        cuenta: dict[str, int] = {}
        for f in filas:
            k = str(f.get(c) or "")
            if k:
                cuenta[k] = cuenta.get(k, 0) + 1
        frecuentes = sorted(
            (k for k, n in cuenta.items() if n >= minimo_por_categoria),
            key=lambda k: -cuenta[k],
        )[:max_categorias]
        # Con una sola categoría frecuente no hay nada que distinguir.
        categorias[c] = frecuentes if len(cuenta) > 1 else []
    nombres = list(numericas)
    for c in categoricas:
        nombres += [f"{c}={k}" for k in categorias[c]]
    # Las variables indicadoras también se escalan, con sus medias del entreno:
    # así todos los pesos se leen en la misma unidad y se pueden comparar.
    for c in categoricas:
        for k in categorias[c]:
            vals = [1.0 if str(f.get(c) or "") == k else 0.0 for f in filas]
            media = sum(vals) / len(vals) if vals else 0.0
            var = sum((x - media) ** 2 for x in vals) / len(vals) if vals else 0.0
            escalas[f"{c}={k}"] = [media, math.sqrt(var) or 1.0]
    return {"variables": nombres, "escalas": escalas, "categorias": categorias}


def _crudo(fila: dict[str, Any], nombre: str) -> float:
    if "=" in nombre:
        c, _, k = nombre.partition("=")
        return 1.0 if str(fila.get(c) or "") == k else 0.0
    return float(fila.get(nombre) or 0.0)


def vectorizar(fila: dict[str, Any], definicion: dict[str, Any]) -> list[float]:
    salida = []
    for nombre in definicion["variables"]:
        media, desv = definicion["escalas"][nombre]
        salida.append((_crudo(fila, nombre) - media) / desv)
    return salida


def explicar(
    fila: dict[str, Any], definicion: dict[str, Any], pesos: dict[str, float], cuantos: int
) -> list[dict[str, Any]]:
    """Lo que empuja cada variable respecto a un caso medio, ordenado.

    Peso por valor escalado: «cuánto sube o baja la puntuación porque esto es
    distinto de lo habitual». Se enseñan también los que restan.
    """
    contribuciones = []
    for nombre, z in zip(definicion["variables"], vectorizar(fila, definicion), strict=True):
        aporta = float(pesos.get(nombre, 0.0)) * z
        if abs(aporta) < 1e-6:
            continue
        base, _, categoria = nombre.partition("=")
        etiqueta = ETIQUETAS.get(base, base)
        contribuciones.append(
            {
                "variable": nombre,
                "etiqueta": f"{etiqueta}: {categoria}" if categoria else etiqueta,
                "valor": (
                    ("sí" if _crudo(fila, nombre) else "no")
                    if categoria
                    else round(_valor_legible(base, fila.get(base)), 2)
                ),
                "aporta": round(aporta, 4),
            }
        )
    contribuciones.sort(key=lambda c: -abs(c["aporta"]))
    return contribuciones[:cuantos]


def _valor_legible(nombre: str, valor: Any) -> float:
    """Lo que está en logaritmo se enseña en su unidad."""
    numero = float(valor or 0.0)
    return math.expm1(numero) if nombre.startswith("log_") else numero


def _lineal(fila: dict[str, Any], definicion: dict[str, Any], pesos: dict[str, float]) -> float:
    z = float(pesos.get("_sesgo", 0.0))
    for nombre, v in zip(definicion["variables"], vectorizar(fila, definicion), strict=True):
        z += float(pesos.get(nombre, 0.0)) * v
    return z


# ── Fechas ────────────────────────────────────────────────────────────────


def _fecha(valor: Any) -> date | None:
    if not valor:
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    try:
        return datetime.fromisoformat(str(valor).replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(str(valor)[:10])
        except ValueError:
            return None


def _resultado(op: dict[str, Any]) -> str:
    """ganado · perdido · abierto, por lo que SIGNIFICA el estado.

    La empresa puede llamar «Adjudicada» a la ganada: el listado manda lo que
    significa, y es eso lo que se mira. Sin ello, el estado de serie.
    """
    significa = str(op.get("estado_significa") or "")
    if significa in ("ganado", "perdido", "abierto"):
        return significa
    estado = str(op.get("estado") or "")
    return {"ganada": "ganado", "perdida": "perdido"}.get(estado, "abierto")


# ── Rasgos de cada objeto (los mismos al entrenar y al puntuar) ──────────


class Historial:
    """Lo cerrado por cuenta y por comercial, ordenado por fecha de cierre.

    Es lo que permite preguntar «¿cuántas había ganado esta cuenta ANTES de
    esta fecha?» sin mirar el futuro.
    """

    def __init__(self, oportunidades: list[dict[str, Any]]) -> None:
        self.por: dict[tuple[str, str], list[tuple[date, int, float]]] = {}
        for op in oportunidades:
            res = _resultado(op)
            cierre = _fecha(op.get("fecha_cierre_real"))
            if res == "abierto" or cierre is None:
                continue
            importe = float(op.get("importe") or 0)
            for clave in ("cuenta_id", "owner_id"):
                if op.get(clave):
                    self.por.setdefault((clave, str(op[clave])), []).append(
                        (cierre, 1 if res == "ganado" else 0, importe)
                    )
        for lista in self.por.values():
            lista.sort(key=lambda t: t[0])
        self._fechas = {k: [t[0] for t in v] for k, v in self.por.items()}

    def antes(self, clave: str, valor: Any, momento: date) -> tuple[int, int, float]:
        """(ganadas, perdidas, importe ganado) cerradas antes de `momento`."""
        if not valor:
            return 0, 0, 0.0
        k = (clave, str(valor))
        lista = self.por.get(k) or []
        hasta = bisect_left(self._fechas.get(k) or [], momento)
        g = sum(1 for t in lista[:hasta] if t[1] == 1)
        importe = sum(t[2] for t in lista[:hasta] if t[1] == 1)
        return g, hasta - g, importe


def rasgos_oportunidad(op: dict[str, Any], historial: Historial, *, hoy: date) -> dict[str, Any]:
    """Lo que se sabía de una oportunidad cuando se abrió.

    `hoy` —el día del cliente— sólo cuenta si la oportunidad no trae su alta.
    """
    momento = _fecha(op.get("created_at")) or hoy
    g, p, imp = historial.antes("cuenta_id", op.get("cuenta_id"), momento)
    go, po, _ = historial.antes("owner_id", op.get("owner_id"), momento)
    return {
        "log_importe": math.log1p(max(float(op.get("importe") or 0), 0.0)),
        "cuenta_ganadas_previas": g,
        "cuenta_perdidas_previas": p,
        "cuenta_tasa_previa": (g + 1) / (g + p + 2),
        "propietario_tasa_previa": (go + 1) / (go + po + 2),
        "log_importe_medio_cuenta": math.log1p(imp / g) if g else 0.0,
        "tiene_contacto": 1 if op.get("contacto_id") else 0,
        "viene_de_lead": 1 if op.get("lead_id") else 0,
        "embudo": str(op.get("pipeline") or op.get("pipeline_id") or ""),
    }


def rasgos_lead(lead: dict[str, Any]) -> dict[str, Any]:
    """Lo que se sabe de un lead al capturarlo. Nada de lo que pasó después."""
    return {
        "origen": str(lead.get("origen") or ""),
        "pais": str(lead.get("pais") or ""),
        "tiene_email": 1 if lead.get("email") else 0,
        "tiene_telefono": 1 if lead.get("telefono") else 0,
        "tiene_web": 1 if lead.get("web") else 0,
        "tiene_cargo": 1 if lead.get("cargo") else 0,
        "tiene_empresa": 1 if lead.get("empresa") else 0,
        "de_campana": 1 if lead.get("campana_id") else 0,
        "con_utm": 1 if lead.get("utm") else 0,
        "con_propietario": 1 if lead.get("owner_id") else 0,
    }


def resultado_lead(lead: dict[str, Any]) -> int | None:
    """1 convertido, 0 descartado, None si sigue vivo."""
    estado = str(lead.get("estado") or "")
    if lead.get("convertido_at") or estado == "convertido":
        return 1
    if estado == "descartado":
        return 0
    return None


def rasgos_cuenta(
    cuenta_id: str, oportunidades: list[dict[str, Any]], corte: date
) -> dict[str, Any] | None:
    """La relación de una cuenta con nosotros vista en `corte`.

    `None` si en esa fecha todavía no había ninguna oportunidad suya: no se
    puede predecir la compra de alguien que aún no conocíamos.
    """
    propias = [o for o in oportunidades if str(o.get("cuenta_id") or "") == cuenta_id]
    creadas = [o for o in propias if (_fecha(o.get("created_at")) or corte) <= corte]
    if not creadas:
        return None
    g = p = abiertas = 0
    importe = 0.0
    ultima: date | None = None
    for o in creadas:
        cierre = _fecha(o.get("fecha_cierre_real"))
        res = _resultado(o)
        if res != "abierto" and cierre is not None and cierre <= corte:
            if res == "ganado":
                g += 1
                importe += float(o.get("importe") or 0)
                ultima = max(ultima, cierre) if ultima else cierre
            else:
                p += 1
        else:
            abiertas += 1
    primera = min(_fecha(o.get("created_at")) or corte for o in creadas)
    return {
        "ganadas_previas": g,
        "perdidas_previas": p,
        "abiertas": abiertas,
        "log_importe_ganado": math.log1p(importe),
        "dias_desde_ultima_ganada": min((corte - ultima).days, 3650) if ultima else 3650,
        "antiguedad_dias": (corte - primera).days,
        "_importe_medio": importe / g if g else 0.0,
    }


def agrupar_por_cuenta(oportunidades: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Una pasada: sin esto, cada foto de cada cuenta recorre todo el histórico."""
    salida: dict[str, list[dict[str, Any]]] = {}
    for o in oportunidades:
        if o.get("cuenta_id"):
            salida.setdefault(str(o["cuenta_id"]), []).append(o)
    return salida


def compra_en(cuenta_id: str, oportunidades: list[dict[str, Any]], desde: date, hasta: date) -> int:
    """1 si la cuenta ganó alguna venta en (desde, hasta]."""
    for o in oportunidades:
        if str(o.get("cuenta_id") or "") != cuenta_id or _resultado(o) != "ganado":
            continue
        cierre = _fecha(o.get("fecha_cierre_real"))
        if cierre and desde < cierre <= hasta:
            return 1
    return 0


VARIABLES = {
    "cierre": (
        [
            "log_importe",
            "cuenta_ganadas_previas",
            "cuenta_perdidas_previas",
            "cuenta_tasa_previa",
            "propietario_tasa_previa",
            "tiene_contacto",
            "viene_de_lead",
        ],
        ["embudo"],
    ),
    # El importe no se usa para predecir el importe: sería predecirlo con él.
    "importe": (
        [
            "cuenta_ganadas_previas",
            "cuenta_tasa_previa",
            "log_importe_medio_cuenta",
            "propietario_tasa_previa",
            "tiene_contacto",
            "viene_de_lead",
        ],
        ["embudo"],
    ),
    "fecha_cierre": (
        [
            "log_importe",
            "cuenta_ganadas_previas",
            "cuenta_perdidas_previas",
            "propietario_tasa_previa",
            "tiene_contacto",
            "viene_de_lead",
        ],
        ["embudo"],
    ),
    "scoring_lead": (
        [
            "tiene_email",
            "tiene_telefono",
            "tiene_web",
            "tiene_cargo",
            "tiene_empresa",
            "de_campana",
            "con_utm",
            "con_propietario",
        ],
        ["origen", "pais"],
    ),
    "propension": (
        [
            "ganadas_previas",
            "perdidas_previas",
            "abiertas",
            "log_importe_ganado",
            "dias_desde_ultima_ganada",
            "antiguedad_dias",
        ],
        [],
    ),
}


# ── Casos de entrenamiento, por tipo ─────────────────────────────────────


def casos_de(
    tipo: str,
    *,
    leads: list[dict[str, Any]],
    oportunidades: list[dict[str, Any]],
    hoy: date,
    horizonte_dias: int,
) -> list[dict[str, Any]]:
    """Cada caso: sus rasgos, su objetivo (`_y`) y la fecha que lo ordena (`_t`)."""
    casos: list[dict[str, Any]] = []
    if tipo == "scoring_lead":
        for lead in leads:
            y = resultado_lead(lead)
            t = _fecha(lead.get("created_at"))
            if y is None or t is None:
                continue
            casos.append({**rasgos_lead(lead), "_y": y, "_t": t})
        return casos
    if tipo in ("cierre", "importe", "fecha_cierre"):
        hist = Historial(oportunidades)
        for op in oportunidades:
            res = _resultado(op)
            cierre = _fecha(op.get("fecha_cierre_real"))
            creada = _fecha(op.get("created_at"))
            if res == "abierto" or cierre is None or creada is None:
                continue
            r = rasgos_oportunidad(op, hist, hoy=hoy)
            if tipo == "cierre":
                y: float = 1 if res == "ganado" else 0
            elif tipo == "importe":
                if res != "ganado" or float(op.get("importe") or 0) <= 0:
                    continue
                y = math.log1p(float(op["importe"]))
            else:
                y = math.log1p(max((cierre - creada).days, 0))
            casos.append({**r, "_y": y, "_t": cierre})
        return casos
    if tipo == "propension":
        # Una foto de cada cuenta cada `horizonte` días: «¿comprará en los
        # próximos N días?», contestado con lo que se sabía en esa fecha. La
        # última foto es la de hace un horizonte, que ya tiene su respuesta.
        fechas = [d for o in oportunidades if (d := _fecha(o.get("created_at")))]
        if not fechas:
            return []
        por_cuenta = agrupar_por_cuenta(oportunidades)
        cuentas = sorted(por_cuenta)
        paso = timedelta(days=horizonte_dias)
        corte = hoy - paso
        primero = min(fechas)
        while corte > primero:
            for cuenta in cuentas:
                r = rasgos_cuenta(cuenta, por_cuenta[cuenta], corte)
                if r is None:
                    continue
                y = compra_en(cuenta, por_cuenta[cuenta], corte, corte + paso)
                casos.append({**r, "_y": y, "_t": corte, "_cuenta": cuenta})
            corte -= paso
        return casos
    raise ErrorValidacion(f"«{tipo}» no se entrena aquí.", error_code="predictivo.tipo")


def particion(casos: list[dict[str, Any]], pct_validacion: int) -> tuple[list, list, date | None]:
    """Lo viejo para entrenar y lo nuevo para medir, por fecha."""
    ordenados = sorted(casos, key=lambda c: c["_t"])
    corte = len(ordenados) - max(1, len(ordenados) * pct_validacion // 100)
    # Que una misma fecha no quede partida entre los dos lados: en la
    # propensión una foto entera es un instante, y partirla mezclaría futuro.
    while 0 < corte < len(ordenados) and ordenados[corte]["_t"] == ordenados[corte - 1]["_t"]:
        corte -= 1
    if corte <= 0:
        corte = len(ordenados) - max(1, len(ordenados) * pct_validacion // 100)
    return (
        ordenados[:corte],
        ordenados[corte:],
        (ordenados[corte]["_t"] if corte < len(ordenados) else None),
    )


def familia_de(tipo: str) -> str:
    return gob.FAMILIA.get(tipo, "clasificacion")


def entrenar_lineal(
    tipo: str,
    casos: list[dict[str, Any]],
    *,
    pct_validacion: int,
    l2: float,
    iteraciones: int,
    max_categorias: int,
    minimo_por_categoria: int,
) -> dict[str, Any]:
    """Entrena y mide un modelo lineal. Puro: sin base ni red, para probarlo."""
    numericas, categoricas = VARIABLES[tipo]
    entreno, validacion, corte = particion(casos, pct_validacion)
    definicion = preparar(
        entreno,
        numericas=numericas,
        categoricas=categoricas,
        max_categorias=max_categorias,
        minimo_por_categoria=minimo_por_categoria,
    )
    xe = [vectorizar(c, definicion) for c in entreno]
    xv = [vectorizar(c, definicion) for c in validacion]
    clasificador = familia_de(tipo) == "clasificacion"
    if clasificador:
        w, b = ajustar_logistica(
            xe, [int(c["_y"]) for c in entreno], l2=l2, iteraciones=iteraciones
        )
    else:
        w, b = ajustar_lineal(xe, [float(c["_y"]) for c in entreno], l2=l2)
    pesos = {n: round(v, 6) for n, v in zip(definicion["variables"], w, strict=True)}
    pesos["_sesgo"] = round(b, 6)

    def _z(x: list[float]) -> float:
        return b + sum(a * v for a, v in zip(w, x, strict=True))

    if clasificador:
        metricas = metricas_clasificacion(
            [_sigmoide(_z(x)) for x in xv], [int(c["_y"]) for c in validacion]
        )
    else:
        # El error se mide en la unidad del negocio (euros, días), no en
        # logaritmos: un «0,3 de error» no le dice nada a nadie.
        reales = [math.expm1(float(c["_y"])) for c in validacion]
        predichos = [math.expm1(_z(x)) for x in xv]
        referencia = math.expm1(_mediana([float(c["_y"]) for c in entreno]))
        metricas = metricas_regresion(predichos, reales, referencia=referencia)
        # El intervalo: cuánto se equivoca hacia cada lado, en proporción.
        # Medido en la validación, no en el entreno, que siempre acierta más.
        ratios = [r / p for p, r in zip(predichos, reales, strict=True) if p > 0]
        definicion["intervalo"] = [round(_cuantil(ratios, 0.1), 4), round(_cuantil(ratios, 0.9), 4)]
        definicion["referencia"] = round(referencia, 2)
    definicion.update({"origen": "historico", "objetivo_log": not clasificador})
    return {
        "pesos": pesos,
        "definicion": definicion,
        "metricas": metricas,
        "entreno": len(entreno),
        "validacion": len(validacion),
        "corte": corte.isoformat() if corte else None,
        "desde": min(c["_t"] for c in casos),
        "hasta": max(c["_t"] for c in casos),
    }


def suficiente(tipo: str, casos: list[dict[str, Any]], *, minimos: dict[str, int]) -> list[str]:
    """Por qué NO se puede entrenar, o lista vacía."""
    problemas = []
    if familia_de(tipo) == "clasificacion":
        si = sum(1 for c in casos if c["_y"] == 1)
        no = len(casos) - si
        if len(casos) < minimos["casos"]:
            problemas.append(
                f"Hay {len(casos)} casos con resultado conocido y hacen falta al menos "
                f"{minimos['casos']}. Con menos, lo que sale no es un modelo: es una "
                "superstición con decimales."
            )
        if si < minimos["por_clase"] or no < minimos["por_clase"]:
            problemas.append(
                f"Hay {si} positivos y {no} negativos; hacen falta {minimos['por_clase']} "
                "de cada. Un modelo que casi no ha visto una de las dos aprende a decir "
                "siempre la otra."
            )
    elif len(casos) < minimos["regresion"]:
        problemas.append(
            f"Hay {len(casos)} casos y hacen falta al menos {minimos['regresion']} para "
            "medir el error de una regresión sin que dependa de cuatro casos."
        )
    return problemas


def veredicto(
    tipo: str, metricas: dict[str, Any], *, auc_minimo: float, mejora_minima: float
) -> tuple[bool, str]:
    """Si se publica, y por qué sí o por qué no, en una frase."""
    familia = familia_de(tipo)
    if familia == "clasificacion":
        valor = metricas.get("auc")
        if valor is None:
            return False, (
                "El periodo apartado sólo tiene casos de una clase: el acierto no se "
                "puede medir, y un modelo sin medir no se publica."
            )
        if valor < auc_minimo:
            return False, (
                f"AUC {valor:.2f} en el periodo apartado, por debajo del mínimo "
                f"{auc_minimo:.2f}. Se guarda con sus métricas y no puntúa."
            )
        return True, f"AUC {valor:.2f} en el periodo apartado (mínimo {auc_minimo:.2f})."
    if familia == "regresion":
        mejora = float(metricas.get("mejora_pct") or 0)
        if mejora < mejora_minima:
            return False, (
                f"Se equivoca de media {metricas.get('mae')} y decir siempre la mediana "
                f"se equivoca {metricas.get('mae_mediana')}: mejora un {mejora} %, por "
                f"debajo del {mejora_minima} % exigido. No se publica."
            )
        return True, (
            f"Error medio {metricas.get('mae')} frente a {metricas.get('mae_mediana')} de "
            f"decir siempre la mediana: un {mejora} % mejor."
        )
    acierto = float(metricas.get("acierto_top") or 0)
    base = float(metricas.get("acierto_popularidad") or 0)
    if acierto <= 0 or acierto < base:
        return False, (
            f"Acierta el producto apartado el {acierto * 100:.0f} % de las veces y "
            f"recomendar lo más vendido acierta el {base * 100:.0f} %: no se publica."
        )
    return True, (
        f"Acierta el producto apartado el {acierto * 100:.0f} % de las veces, frente al "
        f"{base * 100:.0f} % de recomendar lo más vendido."
    )


# ── Siguiente mejor oferta: coocurrencia entre cuentas ───────────────────


def producto_de(linea: dict[str, Any]) -> tuple[str, str]:
    """(clave, nombre) de un producto de una línea."""
    if linea.get("producto_id"):
        return str(linea["producto_id"]), str(linea.get("descripcion") or linea["producto_id"])
    nombre = str(linea.get("descripcion") or "").strip()
    return nombre.lower(), nombre


def coocurrencias(cestas: dict[str, set[str]]) -> dict[str, Any]:
    cuentas_por: dict[str, int] = {}
    co: dict[str, dict[str, int]] = {}
    for productos in cestas.values():
        for p in productos:
            cuentas_por[p] = cuentas_por.get(p, 0) + 1
            for q in productos:
                if q != p:
                    co.setdefault(p, {})[q] = co.setdefault(p, {}).get(q, 0) + 1
    return {"cuentas_por": cuentas_por, "co": co}


def recomendar(
    tiene: set[str], tabla: dict[str, Any], nombres: dict[str, str], cuantos: int
) -> list[dict[str, Any]]:
    """Lo que compraron las cuentas que compraron lo mismo, con su porqué."""
    puntos: dict[str, float] = {}
    motivo: dict[str, tuple[str, int, int]] = {}
    for p in tiene:
        base = tabla["cuentas_por"].get(p, 0)
        for q, n in (tabla["co"].get(p) or {}).items():
            if q in tiene or n < 2 or not base:
                continue
            confianza = n / base
            puntos[q] = puntos.get(q, 0.0) + confianza
            if q not in motivo or n > motivo[q][1]:
                motivo[q] = (p, n, base)
    orden = sorted(puntos, key=lambda q: -puntos[q])[:cuantos]
    return [
        {
            "producto": q,
            "nombre": nombres.get(q, q),
            "puntuacion": round(puntos[q], 4),
            "porque": (
                f"De las {motivo[q][2]} cuentas que tienen «{nombres.get(motivo[q][0], motivo[q][0])}», "
                f"{motivo[q][1]} tienen también «{nombres.get(q, q)}»."
            ),
        }
        for q in orden
    ]


def entrenar_oferta(
    cestas: dict[str, set[str]], nombres: dict[str, str], *, cuantos: int
) -> dict[str, Any]:
    """Valida dejando fuera un producto de cada cuenta y mirando si se recomienda."""
    import random

    azar = random.Random(7)  # fijo: la misma medida con los mismos datos
    aciertos = aciertos_pop = 0
    probadas = 0
    for cuenta, productos in cestas.items():
        if len(productos) < 2:
            continue
        apartado = azar.choice(sorted(productos))
        resto = {c: (p - {apartado} if c == cuenta else p) for c, p in cestas.items()}
        tabla = coocurrencias(resto)
        propuestas = [
            r["producto"] for r in recomendar(productos - {apartado}, tabla, nombres, cuantos)
        ]
        populares = [
            p
            for p in sorted(tabla["cuentas_por"], key=lambda k: -tabla["cuentas_por"][k])
            if p not in productos - {apartado}
        ][:cuantos]
        probadas += 1
        aciertos += apartado in propuestas
        aciertos_pop += apartado in populares
    return {
        "metricas": {
            "acierto_top": round(aciertos / probadas, 4) if probadas else 0.0,
            "acierto_popularidad": round(aciertos_pop / probadas, 4) if probadas else 0.0,
            "top": cuantos,
            "muestras": probadas,
            "productos": len({p for ps in cestas.values() for p in ps}),
        },
        "tabla": coocurrencias(cestas),
    }


# ── Leer el histórico del CRM, por su API ────────────────────────────────


def identidad_de(principal: Any) -> dict[str, Any]:
    """La de quien pide: sus permisos y su compartición."""
    return {
        "tenant_id": principal.tenant_id,
        "principal_id": principal.id,
        "permisos": sorted(getattr(principal, "permisos", None) or []),
        "roles": sorted(getattr(principal, "roles", None) or []),
        "tipo": "usuario",
    }


def identidad_de_entreno(tenant_id: Any, usuario_id: Any) -> dict[str, Any]:
    """Sólo lectura, sobre el tenant entero, a nombre de quien lo pidió."""
    return {
        "tenant_id": tenant_id,
        "principal_id": usuario_id or tenant_id,
        "permisos": list(PERMISOS_DE_LECTURA),
        "roles": [],
        "tipo": "agente",
    }


_lector: Callable[..., dict[str, Any]] | None = None


def registrar_lector(fn: Callable[..., dict[str, Any]] | None) -> None:
    """Las pruebas sustituyen la llamada HTTP por un doble."""
    global _lector
    _lector = fn


def _invocar(metodo: str, ruta: str, *, identidad: dict[str, Any], **kw: Any) -> dict[str, Any]:
    if _lector is not None:
        return _lector(metodo=metodo, ruta=ruta, **kw)
    from crmcore.http.interno import invocar

    return invocar(metodo=metodo, ruta=ruta, **identidad, **kw)


def leer_todo(
    ruta: str, *, identidad: dict[str, Any], parametros: dict[str, Any] | None = None, tope: int
) -> tuple[list[dict[str, Any]], bool]:
    """Recorre un listado paginado. Devuelve las filas y si se llegó al tope."""
    filas: list[dict[str, Any]] = []
    cursor = ""
    while True:
        p = {**(parametros or {}), "limite": 200}
        if cursor:
            p["cursor"] = cursor
        r = _invocar("GET", ruta, identidad=identidad, parametros=p)
        if int(r.get("estado") or 0) != 200:
            raise ErrorDependencia(
                f"No se ha podido leer {ruta} ({r.get('estado')})",
                error_code="predictivo.lectura",
                detalle={"ruta": ruta, "estado": r.get("estado")},
            )
        datos = r.get("datos") or {}
        filas += list(datos.get("items") or [])
        if len(filas) >= tope:
            return filas[:tope], True
        cursor = str(datos.get("siguiente") or "")
        if not datos.get("hay_mas") or not cursor:
            return filas, False


def leer_uno(ruta: str, *, identidad: dict[str, Any]) -> dict[str, Any]:
    r = _invocar("GET", ruta, identidad=identidad)
    if int(r.get("estado") or 0) == 404:
        raise NoEncontrado(
            "Ese registro no existe o no lo puedes ver", error_code="predictivo.no_encontrado"
        )
    if int(r.get("estado") or 0) != 200:
        raise ErrorDependencia(
            f"No se ha podido leer {ruta} ({r.get('estado')})",
            error_code="predictivo.lectura",
            detalle={"ruta": ruta, "estado": r.get("estado")},
        )
    return dict(r.get("datos") or {})


# ── Entrenar ─────────────────────────────────────────────────────────────


def _hoy(db: Any) -> date:
    from crmcore.fechas import hoy

    return hoy(db)


def entrenar(uow: UnidadDeTrabajo, *, tipo: str, usuario_id: Any) -> dict[str, Any]:
    """Lee el histórico, entrena, mide y publica si supera el mínimo."""
    if tipo not in ENTRENABLES:
        raise ErrorValidacion(
            f"«{tipo}» no se entrena con el histórico.",
            error_code="predictivo.tipo",
            detalle={"validos": list(ENTRENABLES)},
        )
    db = uow.db
    identidad = identidad_de_entreno(uow.tenant_id, usuario_id)
    tope = int(_ajuste("ia_entreno_tope_registros"))
    hoy = _hoy(db)
    leidos: dict[str, Any] = {}
    leads: list[dict[str, Any]] = []
    oportunidades: list[dict[str, Any]] = []
    if tipo == "scoring_lead":
        leads, recortado = leer_todo("/api/v1/leads", identidad=identidad, tope=tope)
        leidos = {"leads": len(leads), "recortado": recortado}
    else:
        oportunidades, recortado = leer_todo(
            "/api/v1/opportunities", identidad=identidad, parametros=TODAS, tope=tope
        )
        leidos = {"oportunidades": len(oportunidades), "recortado": recortado}

    if tipo == "siguiente_oferta":
        return _entrenar_oferta(
            uow, oportunidades, identidad=identidad, usuario_id=usuario_id, leidos=leidos
        )

    horizonte = int(_ajuste("ia_propension_horizonte_dias", db))
    casos = casos_de(
        tipo, leads=leads, oportunidades=oportunidades, hoy=hoy, horizonte_dias=horizonte
    )
    problemas = suficiente(
        tipo,
        casos,
        minimos={
            "casos": int(_ajuste("ia_minimo_casos_entreno")),
            "por_clase": int(_ajuste("ia_minimo_por_clase")),
            "regresion": int(_ajuste("ia_minimo_casos_regresion")),
        },
    )
    if problemas:
        return {
            "tipo": tipo,
            "entrenado": False,
            "publicado": False,
            "casos": len(casos),
            "leidos": leidos,
            "porque": problemas,
            "que_hacer": (
                "Seguir sin este modelo hasta tener histórico. Un modelo malo es peor que "
                "ninguno: se le hace caso igual."
            ),
        }
    resultado = entrenar_lineal(
        tipo,
        casos,
        pct_validacion=int(_ajuste("ia_pct_validacion")),
        l2=float(_ajuste("ia_regularizacion_l2")),
        iteraciones=int(_ajuste("ia_entreno_iteraciones")),
        max_categorias=int(_ajuste("ia_categorias_maximas")),
        minimo_por_categoria=int(_ajuste("ia_minimo_por_categoria")),
    )
    if tipo == "propension":
        resultado["definicion"]["horizonte_dias"] = horizonte
    return _registrar(
        uow,
        tipo=tipo,
        resultado=resultado,
        casos=len(casos),
        usuario_id=usuario_id,
        leidos=leidos,
    )


def _registrar(
    uow: UnidadDeTrabajo,
    *,
    tipo: str,
    resultado: dict[str, Any],
    casos: int,
    usuario_id: Any,
    leidos: dict[str, Any],
) -> dict[str, Any]:
    db = uow.db
    metricas = {k: v for k, v in resultado["metricas"].items() if v is not None}
    publicar, porque = veredicto(
        tipo,
        resultado["metricas"],
        auc_minimo=float(_ajuste("ia_auc_minimo_publicar", db)),
        mejora_minima=float(_ajuste("ia_mejora_minima_regresion_pct", db)),
    )
    variables = list(resultado["definicion"].get("variables") or ["coocurrencia"])
    fila, avisos = gob.registrar_version(
        uow,
        tipo=tipo,
        variables=variables,
        pesos=resultado.get("pesos") or {},
        metricas=metricas,
        datos_desde=resultado.get("desde"),
        datos_hasta=resultado.get("hasta"),
        ejemplos=casos,
        notas=f"Entrenado con el histórico del CRM. {porque}",
    )
    fila.definicion = resultado["definicion"]
    fila.entrenado_por = UUID(str(usuario_id)) if usuario_id else None
    comparacion: dict[str, Any] = {}
    if publicar:
        comparacion = gob.activar(uow, tipo=tipo, version=fila.version)["comparacion"]
    else:
        fila.estado = "descartada"
    db.flush()
    logger.info("predictivo.entrenado", tipo=tipo, version=fila.version, publicado=publicar)
    return {
        "tipo": tipo,
        "entrenado": True,
        "publicado": publicar,
        "version": fila.version,
        "estado": fila.estado,
        "porque": [porque],
        "metricas": resultado["metricas"],
        "casos": casos,
        "entreno": resultado.get("entreno"),
        "validacion": resultado.get("validacion"),
        "corte": resultado.get("corte"),
        "leidos": leidos,
        "avisos": avisos,
        "comparacion": comparacion,
    }


def _cestas(
    oportunidades: list[dict[str, Any]], *, identidad: dict[str, Any], tope: int
) -> tuple[dict[str, set[str]], dict[str, str], int]:
    """Los productos de lo ganado, por cuenta. Una llamada por oportunidad."""
    ganadas = [o for o in oportunidades if _resultado(o) == "ganado" and o.get("cuenta_id")]
    cestas: dict[str, set[str]] = {}
    nombres: dict[str, str] = {}
    for op in ganadas[:tope]:
        r = _invocar("GET", f"/api/v1/opportunities/{op['id']}/lineas", identidad=identidad)
        if int(r.get("estado") or 0) != 200:
            continue
        lineas = r.get("datos")
        lineas = lineas.get("items") if isinstance(lineas, dict) else lineas
        for linea in lineas or []:
            clave, nombre = producto_de(linea)
            if clave:
                cestas.setdefault(str(op["cuenta_id"]), set()).add(clave)
                nombres[clave] = nombre
    return cestas, nombres, min(len(ganadas), tope)


def _entrenar_oferta(
    uow: UnidadDeTrabajo,
    oportunidades: list[dict[str, Any]],
    *,
    identidad: dict[str, Any],
    usuario_id: Any,
    leidos: dict[str, Any],
) -> dict[str, Any]:
    db = uow.db
    cestas, nombres, leidas = _cestas(
        oportunidades, identidad=identidad, tope=int(_ajuste("ia_nbo_tope_oportunidades"))
    )
    leidos = {**leidos, "ganadas_leidas_linea_a_linea": leidas}
    con_dos = sum(1 for p in cestas.values() if len(p) >= 2)
    minimo = int(_ajuste("ia_nbo_minimo_cuentas", db))
    if con_dos < minimo:
        return {
            "tipo": "siguiente_oferta",
            "entrenado": False,
            "publicado": False,
            "casos": con_dos,
            "leidos": leidos,
            "porque": [
                f"Hay {con_dos} cuentas con dos o más productos en sus ventas ganadas y hacen "
                f"falta {minimo}. Con menos, «quien compró X también compró Y» es una "
                "anécdota, no una recomendación."
            ],
            "que_hacer": "Registrar las líneas de producto en las oportunidades ganadas.",
        }
    cuantos = int(_ajuste("ia_nbo_recomendaciones"))
    medido = entrenar_oferta(cestas, nombres, cuantos=cuantos)
    resultado = {
        "pesos": {},
        "definicion": {
            "origen": "historico",
            "variables": ["coocurrencia"],
            "tabla": medido["tabla"],
            "nombres": nombres,
            "cestas": {c: sorted(p) for c, p in cestas.items()},
        },
        "metricas": medido["metricas"],
        "desde": None,
        "hasta": None,
    }
    return _registrar(
        uow,
        tipo="siguiente_oferta",
        resultado=resultado,
        casos=con_dos,
        usuario_id=usuario_id,
        leidos=leidos,
    )


# ── Puntuar registros reales ─────────────────────────────────────────────


def _vigente_guardada(db: Any, tenant_id: UUID, tipo: str, objeto_id: UUID, modelo_id: UUID) -> Any:
    from services.intelligence.prediccion import Prediccion

    return (
        db.execute(
            select(Prediccion)
            .where(
                Prediccion.tenant_id == tenant_id,
                Prediccion.tipo == tipo,
                Prediccion.objeto_id == objeto_id,
                Prediccion.modelo_id == modelo_id,
                Prediccion.caduca_at > datetime.now(timezone.utc),
            )
            .order_by(Prediccion.created_at.desc())
        )
        .scalars()
        .first()
    )


def _guardar(
    uow: UnidadDeTrabajo,
    *,
    tipo: str,
    objeto: str,
    objeto_id: UUID,
    modelo: Any,
    valor: float,
    minimo: float | None,
    maximo: float | None,
    factores: list[dict[str, Any]],
    vigencia: int,
) -> Any:
    from services.intelligence.prediccion import Prediccion

    def _d(v: float | None) -> Decimal | None:
        return None if v is None else Decimal(str(round(min(max(v, -9.9e7), 9.9e7), 4)))

    fila = Prediccion(
        tenant_id=uow.tenant_id,
        tipo=tipo,
        objeto=objeto,
        objeto_id=objeto_id,
        modelo_id=modelo.id,
        version_modelo=modelo.version,
        valor=_d(valor),
        minimo=_d(minimo),
        maximo=_d(maximo),
        factores=factores,
        caduca_at=datetime.now(timezone.utc) + timedelta(days=vigencia),
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila


def _salida(
    tipo: str, fila: Any, modelo: Any, extra: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "tipo": tipo,
        "hay": True,
        "valor": float(fila.valor),
        "minimo": float(fila.minimo) if fila.minimo is not None else None,
        "maximo": float(fila.maximo) if fila.maximo is not None else None,
        "factores": list(fila.factores or []),
        "modelo": {
            "version": modelo.version,
            "metricas": modelo.metricas,
            "entrenado_at": (modelo.entrenado_at.isoformat() if modelo.entrenado_at else None),
        },
        "calculada_at": fila.created_at.isoformat() if fila.created_at else None,
        **(extra or {}),
    }


def _sin(tipo: str, porque: str) -> dict[str, Any]:
    return {"tipo": tipo, "hay": False, "porque": porque}


def _modelo_activo(db: Any, tenant_id: UUID, tipo: str) -> tuple[Any, str]:
    modelo = gob.activo(db, tenant_id, tipo)
    if modelo is None:
        return None, (
            "No hay un modelo publicado de este tipo. Se entrena desde «Modelos "
            "predictivos»; si no supera el mínimo, no se publica y aquí no sale nada."
        )
    if (modelo.definicion or {}).get("origen") != "historico":
        return None, (
            "El modelo publicado es de pesos declarados a mano, no entrenado con el "
            "histórico: no se puntúa con él un registro real."
        )
    return modelo, ""


def puntuar_registro(
    uow: UnidadDeTrabajo, *, objeto: str, objeto_id: UUID, principal: Any, recalcular: bool = False
) -> dict[str, Any]:
    """Todas las predicciones de un registro, leído por su id con tus permisos."""
    identidad = identidad_de(principal)
    db = uow.db
    cuantos = int(_ajuste("ia_factores_visibles", db))
    vigencia = int(_ajuste("ia_prediccion_vigencia_dias", db))
    salida: list[dict[str, Any]] = []
    if objeto == "oportunidad":
        op = leer_uno(f"/api/v1/opportunities/{objeto_id}", identidad=identidad)
        res = _resultado(op)
        if res != "abierto":
            return {
                "objeto": objeto,
                "objeto_id": str(objeto_id),
                "predicciones": [],
                "porque": f"La oportunidad ya está cerrada ({res}): no hay nada que predecir.",
            }
        historia, _ = leer_todo(
            "/api/v1/opportunities",
            identidad=identidad,
            parametros={**TODAS, "cuenta_id": op["cuenta_id"]}
            if op.get("cuenta_id")
            else {**TODAS, "id": str(objeto_id)},
            tope=int(_ajuste("ia_entreno_tope_registros")),
        )
        if op.get("owner_id"):
            del_comercial, _ = leer_todo(
                "/api/v1/opportunities",
                identidad=identidad,
                parametros={**TODAS, "owner_id": op["owner_id"]},
                tope=int(_ajuste("ia_entreno_tope_registros")),
            )
            vistos = {o["id"] for o in historia}
            historia += [o for o in del_comercial if o["id"] not in vistos]
        rasgos = rasgos_oportunidad(op, Historial(historia), hoy=hoy_del_cliente(db))
        for tipo in ("cierre", "importe", "fecha_cierre"):
            salida.append(
                _puntuar_lineal(
                    uow, tipo, objeto, objeto_id, rasgos, recalcular, cuantos, vigencia, contexto=op
                )
            )
    elif objeto == "lead":
        lead = leer_uno(f"/api/v1/leads/{objeto_id}", identidad=identidad)
        if resultado_lead(lead) is not None:
            return {
                "objeto": objeto,
                "objeto_id": str(objeto_id),
                "predicciones": [],
                "porque": "El lead ya está convertido o descartado: no hay nada que predecir.",
            }
        salida.append(
            _puntuar_lineal(
                uow,
                "scoring_lead",
                objeto,
                objeto_id,
                rasgos_lead(lead),
                recalcular,
                cuantos,
                vigencia,
            )
        )
    elif objeto == "cuenta":
        historia, _ = leer_todo(
            "/api/v1/opportunities",
            identidad=identidad,
            parametros={**TODAS, "cuenta_id": str(objeto_id)},
            tope=int(_ajuste("ia_entreno_tope_registros")),
        )
        rasgos = rasgos_cuenta(str(objeto_id), historia, _hoy(db))
        if rasgos is None:
            salida.append(
                _sin(
                    "propension",
                    "Esta cuenta no tiene ninguna oportunidad: no hay historia de la que partir.",
                )
            )
        else:
            salida.append(
                _puntuar_lineal(
                    uow, "propension", objeto, objeto_id, rasgos, recalcular, cuantos, vigencia
                )
            )
        salida.append(siguiente_oferta(db, uow.tenant_id, str(objeto_id)))
    else:
        raise ErrorValidacion(
            f"No se predice nada sobre «{objeto}».",
            error_code="predictivo.objeto",
            detalle={"validos": ["lead", "oportunidad", "cuenta"]},
        )
    return {"objeto": objeto, "objeto_id": str(objeto_id), "predicciones": salida}


def _puntuar_lineal(
    uow: UnidadDeTrabajo,
    tipo: str,
    objeto: str,
    objeto_id: UUID,
    rasgos: dict[str, Any],
    recalcular: bool,
    cuantos: int,
    vigencia: int,
    *,
    contexto: dict[str, Any] | None = None,
) -> dict[str, Any]:
    modelo, porque = _modelo_activo(uow.db, uow.tenant_id, tipo)
    if modelo is None:
        return _sin(tipo, porque)
    hoy = hoy_del_cliente(uow.db)
    extra = _extra(tipo, contexto, rasgos, hoy=hoy)
    if not recalcular:
        guardada = _vigente_guardada(uow.db, uow.tenant_id, tipo, objeto_id, modelo.id)
        if guardada is not None:
            return _salida(
                tipo,
                guardada,
                modelo,
                _extra(tipo, contexto, rasgos, float(guardada.valor), hoy=hoy),
            )
    definicion = dict(modelo.definicion or {})
    pesos = {str(k): float(v) for k, v in (modelo.pesos or {}).items()}
    z = _lineal(rasgos, definicion, pesos)
    minimo = maximo = None
    if familia_de(tipo) == "clasificacion":
        valor = _sigmoide(z)
    else:
        valor = math.expm1(z)
        lo, hi = (definicion.get("intervalo") or [None, None])[:2]
        if lo is not None and hi is not None:
            minimo, maximo = valor * float(lo), valor * float(hi)
    factores = explicar(rasgos, definicion, pesos, cuantos)
    fila = _guardar(
        uow,
        tipo=tipo,
        objeto=objeto,
        objeto_id=objeto_id,
        modelo=modelo,
        valor=valor,
        minimo=minimo,
        maximo=maximo,
        factores=factores,
        vigencia=vigencia,
    )
    extra = _extra(tipo, contexto, rasgos, valor, hoy=hoy)
    return _salida(tipo, fila, modelo, extra)


def _extra(
    tipo: str,
    op: dict[str, Any] | None,
    rasgos: dict[str, Any],
    valor: float | None = None,
    *,
    hoy: date,
) -> dict[str, Any]:
    """Lo que hace legible el número: la fecha que sale, lo declarado al lado."""
    if op is None or valor is None:
        return {}
    if tipo == "importe":
        return {"declarado": float(op.get("importe") or 0), "moneda": op.get("moneda") or ""}
    if tipo == "fecha_cierre":
        # El día del cliente, que pone quien llama con su sesión: con el de
        # UTC, de madrugada «pasada de lo habitual» se decidía con el de ayer.
        creada = _fecha(op.get("created_at")) or hoy
        prevista = creada + timedelta(days=round(valor))
        return {
            "fecha_prevista": max(prevista, hoy).isoformat(),
            "pasada_de_lo_habitual": prevista < hoy,
            "declarada": op.get("fecha_cierre"),
        }
    return {}


def siguiente_oferta(db: Any, tenant_id: UUID, cuenta_id: str) -> dict[str, Any]:
    modelo, porque = _modelo_activo(db, tenant_id, "siguiente_oferta")
    if modelo is None:
        return _sin("siguiente_oferta", porque)
    definicion = modelo.definicion or {}
    tiene = set((definicion.get("cestas") or {}).get(cuenta_id) or [])
    if not tiene:
        return _sin(
            "siguiente_oferta",
            "Esta cuenta no tiene productos en sus ventas ganadas: no hay de qué partir, y "
            "recomendarle lo más vendido no sería una recomendación para ella.",
        )
    tabla = definicion.get("tabla") or {"cuentas_por": {}, "co": {}}
    recomendadas = recomendar(
        tiene, tabla, definicion.get("nombres") or {}, int(_ajuste("ia_nbo_recomendaciones", db))
    )
    return {
        "tipo": "siguiente_oferta",
        "hay": bool(recomendadas),
        "recomendaciones": recomendadas,
        "porque": "" if recomendadas else "Ninguna cuenta parecida tiene algo que esta no tenga.",
        "modelo": {"version": modelo.version, "metricas": modelo.metricas},
    }


# ── Segmento predictivo ──────────────────────────────────────────────────

CRITERIOS = ("propension", "valor_esperado", "scoring_lead")


def segmento(
    uow: UnidadDeTrabajo,
    *,
    principal: Any,
    criterio: str,
    minimo: float,
    tope: int | None,
    nombre: str,
) -> dict[str, Any]:
    """Crea en marketing un segmento con los mejor puntuados y lo congela."""
    if criterio not in CRITERIOS:
        raise ErrorValidacion(
            f"Criterio «{criterio}» no válido.",
            error_code="predictivo.criterio",
            detalle={"validos": list(CRITERIOS)},
        )
    db = uow.db
    tipo = "scoring_lead" if criterio == "scoring_lead" else "propension"
    modelo, porque = _modelo_activo(db, uow.tenant_id, tipo)
    if modelo is None:
        raise ErrorValidacion(porque, error_code="predictivo.sin_modelo")
    identidad = identidad_de(principal)
    tope_lectura = int(_ajuste("ia_entreno_tope_registros"))
    definicion = dict(modelo.definicion or {})
    pesos = {str(k): float(v) for k, v in (modelo.pesos or {}).items()}
    candidatos: list[dict[str, Any]] = []
    if tipo == "scoring_lead":
        leads, recortado = leer_todo("/api/v1/leads", identidad=identidad, tope=tope_lectura)
        for lead in leads:
            if resultado_lead(lead) is None:
                p = _sigmoide(_lineal(rasgos_lead(lead), definicion, pesos))
                candidatos.append({"id": str(lead["id"]), "puntuacion": p})
        objeto = "lead"
    else:
        ops, recortado = leer_todo(
            "/api/v1/opportunities", identidad=identidad, parametros=TODAS, tope=tope_lectura
        )
        hoy = _hoy(db)
        media_tenant = [float(o.get("importe") or 0) for o in ops if _resultado(o) == "ganado"]
        media = sum(media_tenant) / len(media_tenant) if media_tenant else 0.0
        por_cuenta = agrupar_por_cuenta(ops)
        for cuenta in sorted(por_cuenta):
            r = rasgos_cuenta(cuenta, por_cuenta[cuenta], hoy)
            if r is None:
                continue
            p = _sigmoide(_lineal(r, definicion, pesos))
            valor = p * (r["_importe_medio"] or media)
            candidatos.append(
                {"id": cuenta, "puntuacion": valor if criterio == "valor_esperado" else p}
            )
        objeto = "cuenta"
    dentro = sorted(
        (c for c in candidatos if c["puntuacion"] >= minimo), key=lambda c: -c["puntuacion"]
    )
    if tope:
        dentro = dentro[:tope]
    if not dentro:
        return {
            "creado": False,
            "candidatos": len(candidatos),
            "porque": f"Ninguno de los {len(candidatos)} candidatos llega a {minimo}.",
        }
    import secrets

    clave = f"ia-{criterio}-{_hoy(db).isoformat()}-{secrets.token_hex(3)}"
    r = _invocar(
        "POST",
        "/api/v1/segmentos",
        identidad=identidad,
        cuerpo={
            "clave": clave,
            "nombre": nombre or f"Predictivo: {criterio}",
            "objeto": objeto,
            "definicion": {
                "op": "y",
                "hijos": [
                    {
                        "atributo": f"{objeto}.objeto_id",
                        "operador": "en",
                        "valor": [c["id"] for c in dentro],
                    }
                ],
            },
            "dinamico": True,
            "descripcion": (
                f"Creado por el modelo «{tipo}» v{modelo.version} el {_hoy(db).isoformat()}: "
                f"{len(dentro)} con {criterio} ≥ {minimo}. Congelado al crearlo: la lista "
                "es la de ese día."
            ),
        },
    )
    if int(r.get("estado") or 0) not in (200, 201):
        raise ErrorDependencia(
            "Marketing no ha creado el segmento",
            error_code="predictivo.segmento",
            detalle={"estado": r.get("estado"), "dijo": r.get("datos")},
        )
    segmento_id = str((r.get("datos") or {}).get("id") or "")
    congelado = _invocar("POST", f"/api/v1/segmentos/{segmento_id}/congelar", identidad=identidad)
    datos = congelado.get("datos") or {}
    miembros = (
        int(datos.get("miembros") or datos.get("tamano") or 0) if isinstance(datos, dict) else 0
    )
    return {
        "creado": True,
        "segmento_id": segmento_id,
        "clave": clave,
        "objeto": objeto,
        "previstos": len(dentro),
        "congelados": miembros,
        "candidatos": len(candidatos),
        "recortado": recortado,
        "aviso": (
            ""
            if miembros >= len(dentro)
            else f"El modelo eligió {len(dentro)} y marketing congeló {miembros}: marketing "
            "sólo segmenta los registros que tiene en su proyección, y le faltan "
            f"{len(dentro) - miembros}."
        ),
        "primeros": dentro[:10],
    }


# ── Reentreno programado ─────────────────────────────────────────────────


def versiones(db: Any, tenant_id: UUID, tipo: str | None = None) -> list[dict[str, Any]]:
    consulta = select(gob.ModeloML).where(gob.ModeloML.tenant_id == tenant_id)
    if tipo:
        consulta = consulta.where(gob.ModeloML.tipo == tipo)
    filas = (
        db.execute(consulta.order_by(gob.ModeloML.tipo, gob.ModeloML.version.desc()))
        .scalars()
        .all()
    )
    return [
        {
            "id": str(f.id),
            "tipo": f.tipo,
            "version": f.version,
            "estado": f.estado,
            "origen": str((f.definicion or {}).get("origen") or "declarado"),
            "metricas": f.metricas,
            "ejemplos": f.ejemplos,
            "ventana": f"{f.datos_desde} → {f.datos_hasta}"
            if f.datos_desde and f.datos_hasta
            else "",
            "entrenado_at": f.entrenado_at.isoformat() if f.entrenado_at else None,
            "notas": f.notas,
        }
        for f in filas
    ]


class ProgramacionEntreno(Base, TimestampMixin):
    """Un modelo que se reentrena solo cada N días.

    Guarda quién lo programó: el reentreno lee con permisos de sólo lectura,
    pero a nombre de alguien, y es ese nombre el que aparece en el rastro.
    """

    __tablename__ = "programaciones_entreno"
    __table_args__ = (UniqueConstraint("tenant_id", "tipo", name="uq_programacion_entreno"),)

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    tipo: Mapped[str] = mapped_column(String(30), nullable=False)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    programada_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    ultima_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    proxima_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Lo que salió la última vez, en una frase: «publicada v12» o «no hay
    # bastantes datos». Un reentreno que falla en silencio deja puntuando un
    # modelo cada vez más viejo sin que nadie lo sepa.
    ultimo_resultado: Mapped[str] = mapped_column(Text, nullable=False, default="")


def programar(uow: UnidadDeTrabajo, *, tipo: str, activa: bool, usuario_id: Any) -> dict[str, Any]:
    if tipo not in ENTRENABLES:
        raise ErrorValidacion(
            f"«{tipo}» no se entrena con el histórico.", error_code="predictivo.tipo"
        )
    dias = int(_ajuste("ia_reentreno_dias", uow.db))
    fila = uow.db.execute(
        select(ProgramacionEntreno).where(
            ProgramacionEntreno.tenant_id == uow.tenant_id, ProgramacionEntreno.tipo == tipo
        )
    ).scalar_one_or_none()
    ahora = datetime.now(timezone.utc)
    if fila is None:
        fila = ProgramacionEntreno(
            tenant_id=uow.tenant_id, tipo=tipo, proxima_at=ahora + timedelta(days=dias)
        )
        uow.db.add(fila)
    fila.activa = activa
    fila.programada_por = UUID(str(usuario_id)) if usuario_id else None
    if activa:
        fila.proxima_at = (fila.ultima_at or ahora) + timedelta(days=dias)
    uow.db.flush()
    return _programacion(fila, dias)


def _programacion(fila: Any, dias: int) -> dict[str, Any]:
    return {
        "tipo": fila.tipo,
        "activa": fila.activa,
        "cada_dias": dias,
        "ultima_at": fila.ultima_at.isoformat() if fila.ultima_at else None,
        "proxima_at": fila.proxima_at.isoformat() if fila.proxima_at else None,
        "ultimo_resultado": fila.ultimo_resultado,
    }


def programaciones(db: Any, tenant_id: UUID) -> list[dict[str, Any]]:
    dias = int(_ajuste("ia_reentreno_dias", db))
    filas = (
        db.execute(select(ProgramacionEntreno).where(ProgramacionEntreno.tenant_id == tenant_id))
        .scalars()
        .all()
    )
    return [_programacion(f, dias) for f in filas]


def tenants_con_programacion() -> list[Any]:
    from crmcore.db.session import sesion

    with sesion(sistema=True) as db:
        return [
            t
            for (t,) in db.execute(
                select(ProgramacionEntreno.tenant_id)
                .where(ProgramacionEntreno.activa.is_(True))
                .distinct()
            ).all()
        ]


def reentrenar_lo_que_toca(tenant_id: Any) -> dict[str, Any]:
    """Lo que vence de este tenant. Cada tipo en su propia unidad de trabajo:
    que falle uno no deja sin reentrenar a los demás."""
    from crmcore.db.session import sesion
    from crmcore.db.uow import unidad_de_trabajo

    ahora = datetime.now(timezone.utc)
    with sesion(tenant_id) as db:
        pendientes = [
            (f.tipo, f.programada_por)
            for f in db.execute(
                select(ProgramacionEntreno).where(
                    ProgramacionEntreno.tenant_id == tenant_id,
                    ProgramacionEntreno.activa.is_(True),
                    ProgramacionEntreno.proxima_at <= ahora,
                )
            ).scalars()
        ]
    hechos: dict[str, str] = {}
    for tipo, por in pendientes:
        try:
            with unidad_de_trabajo(tenant_id) as uow:
                r = entrenar(uow, tipo=tipo, usuario_id=por)
                resumen = (
                    f"v{r.get('version')} {'publicada' if r.get('publicado') else 'no publicada'}: "
                    + " ".join(r.get("porque") or [])
                    if r.get("entrenado")
                    else "No entrenado: " + " ".join(r.get("porque") or [])
                )
        except Exception as exc:  # noqa: BLE001 — se anota y se sigue
            resumen = f"Falló: {type(exc).__name__}: {str(exc)[:200]}"
        with unidad_de_trabajo(tenant_id) as uow:
            fila = uow.db.execute(
                select(ProgramacionEntreno).where(
                    ProgramacionEntreno.tenant_id == tenant_id, ProgramacionEntreno.tipo == tipo
                )
            ).scalar_one()
            fila.ultima_at = ahora
            fila.proxima_at = ahora + timedelta(days=int(_ajuste("ia_reentreno_dias", uow.db)))
            fila.ultimo_resultado = resumen[:1000]
        hechos[tipo] = resumen
    return {"reentrenados": hechos}
