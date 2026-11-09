"""Preguntas en lenguaje natural que se ejecutan (CRM-05.02.02.04).

**Lo que había, medido el 09-11-2026.** `POST /ia/preguntar-datos` pedía a quien
llamaba el «modelo de datos» —que ninguna pantalla sabía componer— y devolvía
un plan **sin ejecutar**. Una pregunta que no se contesta.

Ahora:

1. **El esquema se lee de verdad**, del servicio que guarda cada objeto
   (`GET /{servicio}/filtros` y `/{servicio}/filtros/{objeto}`), con la
   identidad de quien pregunta: por un campo que esta persona ve enmascarado
   no se puede filtrar, y el esquema que se le enseña al modelo ya lo sabe.
2. **El modelo propone un plan**, nunca SQL, y el plan se valida contra ese
   esquema: un objeto o un campo inventado se rechaza aquí.
3. **El plan se ejecuta contra la API de listados del CRM**, con los permisos
   de quien pregunta: los mismos filtros que la URL de un listado
   (`?importe__desde=…`), la misma compartición, la misma proyección. Los
   agregados —contar, sumar, media— se calculan sobre las filas devueltas, y
   si hay más que el tope **se dice que es parcial**.
4. **Se devuelve la consulta que se hizo**, tal cual: la ruta y los
   parámetros. Es lo que permite comprobar el número antes de llevárselo a una
   reunión.

El texto de la respuesta lo compone el código con los números, no el modelo:
un modelo que redacta cifras las redondea, las mezcla o se las inventa.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from typing import Any

from crmcore.db.uow import UnidadDeTrabajo
from crmcore.logging import get_logger

from services.intelligence import predictivo, rag

logger = get_logger(__name__)

# Del plan a la URL de un listado. Es la gramática del ejecutor de la casa
# (`crmcore.http.listados.OPERADORES_DE_URL`), con su nombre de URL.
A_URL = {
    "=": "",
    "!=": "distinto",
    ">": "mayor",
    ">=": "desde",
    "<": "menor",
    "<=": "hasta",
    "en": "en",
    "vacio": "vacio",
    "no_vacio": "no_vacio",
}

AGREGADOS = ("cuenta", "suma", "media", "minimo", "maximo")

_leer: Callable[..., dict[str, Any]] | None = None


def registrar_lector(fn: Callable[..., dict[str, Any]] | None) -> None:
    global _leer
    _leer = fn


def _invocar(
    ruta: str, identidad: dict[str, Any], parametros: dict[str, Any] | None = None
) -> dict[str, Any]:
    if _leer is not None:
        return _leer(metodo="GET", ruta=ruta, parametros=parametros)
    from crmcore.http.interno import invocar

    return invocar(metodo="GET", ruta=ruta, parametros=parametros, **identidad)


def _plano(texto: str) -> str:
    sin = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in sin if not unicodedata.combining(c))


def _raices(texto: str) -> set[str]:
    """Las palabras de la pregunta reducidas a su raíz de cinco letras.

    «oportunidades» y «oportunidad» casan; «casos» y «caso» también. Es una
    preselección para no mandarle al modelo veinte objetos campo a campo, no
    una decisión: el modelo puede elegir cualquier objeto de la lista.
    """
    return {p[:5] for p in re.findall(r"[a-z]{4,}", _plano(texto))}


def esquema(
    identidad: dict[str, Any], *, pregunta: str, servicios: list[str], detallados: int
) -> dict[str, Any]:
    """Los objetos que se pueden preguntar y, de los más parecidos, sus campos."""
    colecciones: dict[str, dict[str, str]] = {}
    for servicio in servicios:
        r = _invocar(f"/api/v1/{servicio}/filtros", identidad)
        if int(r.get("estado") or 0) != 200:
            continue
        for objeto, ruta in ((r.get("datos") or {}).get("colecciones") or {}).items():
            colecciones[str(objeto)] = {"servicio": servicio, "coleccion": str(ruta)}
    raices = _raices(pregunta)

    def _parecido(objeto: str) -> int:
        nombre = {p[:5] for p in re.findall(r"[a-z]{4,}", _plano(objeto.replace("_", " ")))}
        return len(nombre & raices)

    elegidos = sorted((o for o in colecciones if _parecido(o) > 0), key=lambda o: -_parecido(o))[
        :detallados
    ]
    objetos = []
    for objeto in elegidos:
        servicio = colecciones[objeto]["servicio"]
        campos = campos_de(identidad, servicio, objeto)
        if campos is None:
            continue
        ficha: dict[str, Any] = {"clave": objeto, "campos": [{"nombre": c} for c in campos]}
        # Los valores de su estado, de la máquina de estados del tenant: sin
        # ellos el modelo escribe «Ganada» y el filtro no casa con nada.
        estados = _invocar(f"/api/v1/{servicio}/estados/{objeto}", identidad)
        if int(estados.get("estado") or 0) == 200:
            ficha["valores_de_estado"] = [
                str(e.get("clave"))
                for e in (estados.get("datos") or {}).get("estados") or []
                if e.get("activo", True)
            ]
        defecto = por_defecto(servicio, colecciones[objeto]["coleccion"])
        if defecto:
            ficha["filtra_por_defecto"] = defecto
        objetos.append(ficha)
    return {
        "objetos": objetos,
        "otros_objetos": sorted(set(colecciones) - set(elegidos)),
        "colecciones": colecciones,
    }


def campos_de(identidad: dict[str, Any], servicio: str, objeto: str) -> list[str] | None:
    r = _invocar(f"/api/v1/{servicio}/filtros/{objeto}", identidad)
    if int(r.get("estado") or 0) != 200:
        return None
    return list((r.get("datos") or {}).get("se_puede_filtrar_por") or [])


_NO_SON_FILTROS = {"limite", "cursor", "contar", "orden", "campos", "formato", "authorization"}


def _contrato(servicio: str) -> dict[str, Any]:
    from crmcore.http.interno import pedir

    return pedir(servicio, "/api/v1/openapi.json") or {}


# Las pruebas lo sustituyen por un doble (`monkeypatch.setattr`).
_contrato_de: Callable[[str], dict[str, Any]] = _contrato


def por_defecto(servicio: str, coleccion: str) -> dict[str, Any]:
    """Lo que el listado filtra SIN que se le pida, leído de su contrato.

    El de oportunidades, por ejemplo, enseña sólo las abiertas si no se dice
    otra cosa. Una respuesta a «¿cuántas oportunidades hay?» que cuenta sólo
    las abiertas sin decirlo es un número equivocado con buena cara: se dice,
    y el plan puede pedir otro valor para ese mismo parámetro.
    """
    try:
        operacion = ((_contrato_de(servicio).get("paths") or {}).get(coleccion) or {}).get(
            "get"
        ) or {}
    except Exception:  # noqa: BLE001 — sin contrato no se sabe, y se dice sin él
        return {}
    salida = {}
    for p in operacion.get("parameters") or []:
        nombre = str(p.get("name") or "")
        defecto = (p.get("schema") or {}).get("default")
        if (
            p.get("in") == "query"
            and nombre not in _NO_SON_FILTROS
            and defecto not in (None, "", False)
        ):
            salida[nombre] = defecto
    return salida


def normalizar(plan: dict[str, Any]) -> dict[str, Any]:
    """Las variantes de forma que escribe un modelo, a la forma del plan.

    Medido el 09-11-2026: a «importe total de todas las oportunidades por
    estado» el modelo devolvió `filtro` en singular, y el plan se ejecutó SIN
    el filtro que había escrito. Un filtro que se pierde por una letra es un
    número equivocado con buena cara.
    """
    if "filtros" not in plan and isinstance(plan.get("filtro"), (list, dict)):
        crudo = plan.pop("filtro")
        plan["filtros"] = crudo if isinstance(crudo, list) else [crudo]
    if isinstance(plan.get("filtros"), dict):
        plan["filtros"] = [plan["filtros"]]
    return plan


def validar_plan(plan: dict[str, Any], campos: list[str]) -> list[str]:
    """Lo que el ejecutor no puede hacer con seguridad, dicho antes de llamar."""
    problemas = []
    validos = set(campos)
    for f in plan.get("filtros") or []:
        campo, op = str(f.get("campo") or ""), str(f.get("operador") or "=")
        if campo not in validos:
            problemas.append(f"No se puede filtrar por «{campo}»: no existe o no lo ves en claro.")
        if op not in A_URL:
            problemas.append(
                f"El operador «{op}» no se puede ejecutar por la API de listados "
                "(los de texto libre no se ejecutan: serían una búsqueda, no un filtro)."
            )
    agregado = plan.get("agregado") or {}
    funcion = str(agregado.get("funcion") or "")
    if funcion and funcion not in AGREGADOS:
        problemas.append(f"El agregado «{funcion}» no existe; valen {', '.join(AGREGADOS)}.")
    if funcion and funcion != "cuenta" and str(agregado.get("campo") or "") not in validos:
        problemas.append(
            f"No se puede {funcion} «{agregado.get('campo')}»: no es un campo de este objeto."
        )
    agrupar = str(plan.get("agrupar_por") or "")
    if agrupar and agrupar not in validos:
        problemas.append(f"No se puede agrupar por «{agrupar}»: no es un campo de este objeto.")
    return problemas


def parametros_de(plan: dict[str, Any]) -> dict[str, Any]:
    salida: dict[str, Any] = {}
    for f in plan.get("filtros") or []:
        sufijo = A_URL[str(f.get("operador") or "=")]
        clave = f"{f['campo']}__{sufijo}" if sufijo else str(f["campo"])
        valor = f.get("valor")
        if sufijo in ("vacio", "no_vacio"):
            valor = "true"
        elif isinstance(valor, list):
            valor = ",".join(str(v) for v in valor)
        salida[clave] = valor
    return salida


def _numero(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def agregar(filas: list[dict[str, Any]], plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Cuenta, suma o media por grupo, sobre las filas devueltas."""
    agregado = plan.get("agregado") or {}
    funcion = str(agregado.get("funcion") or "cuenta")
    campo = str(agregado.get("campo") or "")
    grupo = str(plan.get("agrupar_por") or "")
    grupos: dict[str, list[dict[str, Any]]] = {}
    for f in filas:
        grupos.setdefault(str(f.get(grupo)) if grupo else "", []).append(f)
    salida = []
    for clave, filas_g in grupos.items():
        numeros = [n for f in filas_g if (n := _numero(f.get(campo))) is not None]
        if funcion == "cuenta":
            valor: float | None = len(filas_g)
        elif not numeros:
            valor = None
        elif funcion == "suma":
            valor = sum(numeros)
        elif funcion == "media":
            valor = sum(numeros) / len(numeros)
        elif funcion == "minimo":
            valor = min(numeros)
        else:
            valor = max(numeros)
        salida.append(
            {
                "grupo": clave if grupo else None,
                "valor": round(valor, 2) if valor is not None else None,
                "filas": len(filas_g),
            }
        )
    return sorted(salida, key=lambda g: -(g["valor"] or 0))


def _cifra(valor: Any) -> str:
    """12345678.5 → «12.345.678,5»: el texto lo lee una persona en castellano."""
    if valor is None:
        return "sin datos"
    numero = float(valor)
    texto = f"{numero:,.2f}".replace(",", "§").replace(".", ",").replace("§", ".")
    return texto[:-3] if texto.endswith(",00") else texto


def _texto(
    plan: dict[str, Any],
    agregados: list[dict[str, Any]],
    total: int | None,
    leidas: int,
    parcial: bool,
) -> str:
    agregado = plan.get("agregado") or {}
    funcion = str(agregado.get("funcion") or "cuenta")
    objeto = str(plan.get("objeto") or "")
    if funcion == "cuenta" and not plan.get("agrupar_por"):
        n = total if total is not None else leidas
        return f"Hay {n} registros de «{objeto}» que cumplen la pregunta."
    nombre = {
        "cuenta": "Cuántos",
        "suma": "Suma",
        "media": "Media",
        "minimo": "Mínimo",
        "maximo": "Máximo",
    }[funcion]
    partes = [
        f"{g['grupo'] if g['grupo'] is not None else 'Total'}: {_cifra(g['valor'])}"
        for g in agregados[:10]
    ]
    cola = (
        f" Calculado sobre {leidas} filas leídas de {total}: es PARCIAL."
        if parcial
        else f" Sobre {leidas} filas."
    )
    campo = f" de «{agregado.get('campo')}»" if funcion != "cuenta" else ""
    return f"{nombre}{campo} en «{objeto}» — " + "; ".join(partes) + "." + cola


def preguntar(uow: UnidadDeTrabajo, *, pregunta: str, principal: Any) -> dict[str, Any]:
    from services.intelligence.ajustes import ajustes

    db = uow.db
    identidad = predictivo.identidad_de(principal)
    servicios = [s.strip() for s in ajustes().ia_consulta_servicios.split(",") if s.strip()]
    datos = esquema(
        identidad,
        pregunta=pregunta,
        servicios=servicios,
        detallados=ajustes().ia_consulta_objetos_detallados,
    )
    modelo_datos = {"objetos": datos["objetos"], "otros_objetos": datos["otros_objetos"]}
    traducido = rag.preguntar_a_los_datos(
        uow, pregunta=pregunta, modelo_datos=modelo_datos, principal=principal
    )
    plan = normalizar(dict(traducido.get("plan") or {}))
    base = {
        "pregunta": pregunta,
        "interpretacion": traducido.get("interpretacion") or "",
        "llamada_id": traducido.get("llamada_id"),
        "plan": plan or None,
        "ejecutado": False,
    }
    if not traducido.get("valido") or not plan:
        return {
            **base,
            "problemas": traducido.get("problemas") or ["El modelo no ha propuesto un plan."],
        }

    objeto = str(plan.get("objeto") or "")
    destino = datos["colecciones"].get(objeto)
    if destino is None:
        return {**base, "problemas": [f"«{objeto}» no es ningún objeto que se pueda preguntar."]}
    campos = campos_de(identidad, destino["servicio"], objeto) or []
    problemas = validar_plan(plan, campos)
    if problemas:
        return {**base, "problemas": problemas}

    parametros = parametros_de(plan)
    # Lo que el listado aplica por su cuenta y el plan no ha pisado.
    aplicados: dict[str, Any] = {}
    for k, v in por_defecto(destino["servicio"], destino["coleccion"]).items():
        if k in parametros:
            continue
        if isinstance(v, str) and any(p.startswith(f"{k}__") for p in parametros):
            # El plan filtra ese campo con otro operador (`estado__en=…`): el
            # valor por defecto se vacía, o se sumarían las dos condiciones.
            parametros[k] = ""
            continue
        aplicados[k] = v
    tope = int(predictivo._ajuste("ia_consulta_tope_filas", db))
    filas: list[dict[str, Any]] = []
    total: int | None = None
    cursor = ""
    tapados: set[str] = set()
    while True:
        p = {**parametros, "limite": 200}
        if cursor:
            p["cursor"] = cursor
        else:
            p["contar"] = "true"
        r = _invocar(destino["coleccion"], identidad, p)
        if int(r.get("estado") or 0) != 200:
            return {
                **base,
                "consulta": {
                    "metodo": "GET",
                    "ruta": destino["coleccion"],
                    "parametros": parametros,
                },
                "problemas": [
                    f"El listado ha contestado {r.get('estado')}: {str(r.get('datos'))[:300]}"
                ],
            }
        tapados |= set(r.get("campos_tapados") or []) | set(r.get("campos_no_entregados") or [])
        cuerpo = r.get("datos") or {}
        if total is None and cuerpo.get("total_aprox") is not None:
            total = int(cuerpo["total_aprox"])
        filas += list(cuerpo.get("items") or [])
        cursor = str(cuerpo.get("siguiente") or "")
        if len(filas) >= tope or not cuerpo.get("hay_mas") or not cursor:
            break
    parcial = bool(total is not None and len(filas) < total)
    agregados = agregar(filas, plan)
    devueltas = int(ajustes().ia_consulta_filas_devueltas)
    columnas = [str(c) for c in (plan.get("campos") or [])] or None
    return {
        **base,
        "ejecutado": True,
        "respuesta": _texto(plan, agregados, total, len(filas), parcial)
        + (
            " El listado aplica por defecto "
            + ", ".join(f"{k}={v}" for k, v in aplicados.items())
            + "."
            if aplicados
            else ""
        ),
        "agregados": agregados,
        "total": total,
        "leidas": len(filas),
        "parcial": parcial,
        "filas": [{k: f.get(k) for k in columnas} if columnas else f for f in filas[:devueltas]],
        "consulta": {
            "metodo": "GET",
            "ruta": destino["coleccion"],
            "parametros": parametros,
            "por_defecto_del_listado": aplicados,
        },
        "campos_tapados": sorted(tapados),
        "aviso": (
            "Hay campos que no ves en claro: vienen tapados o no vienen, y no se pueden citar."
            if tapados
            else ""
        ),
    }
