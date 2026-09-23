"""Modelos entrenados con el histórico: scoring, segmentación y por qué
(CRM-02.01.02.02, CRM-02.01.02.06, CRM-02.01.01.08).

Un modelo entrenado con el histórico de conversión es lo más útil y lo más
peligroso que hay en un CRM, por una razón que casi nunca se dice en voz alta:
**aprende lo que hizo el equipo comercial, no lo que funciona**. Si durante tres
años solo se llamó a las empresas grandes de Madrid, el modelo concluirá que las
empresas grandes de Madrid convierten — y tendrá razón en los datos y estará
equivocado en el mundo.

Las decisiones:

**Se exige tamaño y equilibrio antes de entrenar.** Con cuarenta casos y tres
ganados no sale un modelo: sale una superstición con decimales. Y decirlo antes es
lo único que evita que alguien tome decisiones con ella durante un año.

**El modelo se prueba contra un periodo que no ha visto.** Medir el acierto sobre
los mismos datos con los que se entrenó da siempre un número magnífico y
completamente inútil.

**Se compara con la regla tonta.** Si acertar «todos pierden» da un 85 % porque
solo se gana el 15 %, un modelo con un 86 % no aporta nada. Es la comparación que
nadie hace y la que decide si el modelo sirve.

**Los factores que empujan se enseñan siempre**, ordenados por cuánto empujaron.
Una puntuación sin explicación se mira una vez, no coincide con lo que el comercial
sabe de su cliente, y a partir de ahí no se mira más — y hace bien, porque él
estuvo en la reunión y el modelo no.

**Y lo que no puede entrar en el modelo no entra.** Sexo, edad, nacionalidad y
código postal como sustituto de todo lo anterior: un modelo que decide a quién se
llama con esas variables es discriminación con un informe bonito delante.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from crmcore.errors import ErrorValidacion
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Mínimos para que entrenar tenga sentido. No son cifras mágicas: son el punto por
# debajo del cual el resultado depende más del azar que del histórico, y por
# tanto el punto por debajo del cual hay que decir que no.
MINIMO_CASOS = 200
MINIMO_POR_CLASE = 30

# Variables que NO entran en un modelo que decide a quién se llama o a quién se le
# da prioridad. No es una opción de configuración: es la diferencia entre un
# modelo y una discriminación con un informe delante.
PROHIBIDAS = {
    "sexo": "Decidir a quién se atiende por el sexo es discriminación, tenga el modelo la precisión que tenga",
    "edad": "Lo mismo, y además suele ser un sustituto de otra cosa que sí se puede medir",
    "nacionalidad": "Igual, y con agravante",
    "origen_etnico": "Categoría especial del artículo 9: ni se guarda ni se modela",
    "religion": "Categoría especial del artículo 9",
    "salud": "Categoría especial del artículo 9",
    "codigo_postal": (
        "Parece inocuo y es el sustituto clásico de la renta y del origen: un modelo "
        "que prioriza por código postal acaba haciendo lo mismo que uno que pregunta "
        "por el barrio"
    ),
}

# Cuánto del histórico se reserva para comprobar. Se separa por FECHA y no al azar:
# repartir aleatoriamente mete casos del futuro en el entrenamiento y el acierto
# sale inflado — el modelo ha visto cómo acabó lo que tiene que predecir.
PCT_VALIDACION = 25


def comprobar_variables(*, variables: list[str]) -> dict[str, Any]:
    """Rechaza las variables que no pueden entrar en el modelo.

    Se comprueba **al declarar el modelo**, no al usarlo. Entrenarlo y bloquearlo
    después significaría que el modelo prohibido ya existe y que alguien puede
    ejecutarlo por otro camino.
    """
    usadas = [v for v in variables if v.lower() in PROHIBIDAS]
    if usadas:
        raise ErrorValidacion(
            "Hay variables que no pueden entrar en un modelo que decide a quién se "
            "atiende: " + ", ".join(f"{v} ({PROHIBIDAS[v.lower()]})" for v in usadas),
            error_code="modelo.variable_prohibida",
            detalle={"variables": usadas},
        )
    return {"admitidas": sorted(set(variables)), "comprobadas_contra": sorted(PROHIBIDAS)}


def se_puede_entrenar(*, casos: list[dict[str, Any]], variables: list[str]) -> dict[str, Any]:
    """Si hay histórico suficiente, **y qué sesgo trae el que hay**.

    Lo primero evita la superstición con decimales. Lo segundo es lo que casi
    nadie mira: un histórico donde el 90 % de lo ganado es de un solo sector no
    enseña qué convierte, enseña a qué sector se dedicó el equipo — y el modelo
    recomendará justo eso, para siempre.
    """
    comprobar_variables(variables=variables)

    ganados = [c for c in casos if c.get("resultado") == "ganado"]
    perdidos = [c for c in casos if c.get("resultado") == "perdido"]
    problemas: list[str] = []

    if len(casos) < MINIMO_CASOS:
        problemas.append(
            f"Solo hay {len(casos)} casos cerrados y hacen falta al menos {MINIMO_CASOS}. "
            "Con menos, lo que sale no es un modelo: es una superstición con decimales."
        )
    if len(ganados) < MINIMO_POR_CLASE or len(perdidos) < MINIMO_POR_CLASE:
        problemas.append(
            f"Hay {len(ganados)} ganados y {len(perdidos)} perdidos; hacen falta "
            f"{MINIMO_POR_CLASE} de cada. Un modelo que casi no ha visto perder aprende "
            "a decir que sí."
        )

    # Concentración del histórico: de dónde sale lo ganado.
    avisos: list[str] = []
    for dimension in ("sector", "origen", "propietario"):
        valores: dict[str, int] = {}
        for caso in ganados:
            clave = str(caso.get(dimension) or "")
            if clave:
                valores[clave] = valores.get(clave, 0) + 1
        if not valores:
            continue
        mayor, cuantos = max(valores.items(), key=lambda kv: kv[1])
        if ganados and cuantos / len(ganados) > 0.6:
            avisos.append(
                f"El {round(cuantos / len(ganados) * 100)} % de lo ganado es de "
                f"«{mayor}» ({dimension}). El modelo aprenderá que eso convierte, y en "
                "realidad está aprendiendo a qué se dedicó el equipo."
            )

    return {
        "se_puede": not problemas,
        "casos": len(casos),
        "ganados": len(ganados),
        "perdidos": len(perdidos),
        "problemas": problemas,
        "sesgos_del_historico": avisos,
        "que_hacer": (
            ""
            if not problemas
            else "Seguir usando las reglas declaradas hasta tener histórico. Un modelo "
            "malo es peor que ninguno: se le hace caso igual."
        ),
    }


def particion_temporal(
    *, casos: list[dict[str, Any]], pct_validacion: int = PCT_VALIDACION
) -> dict[str, Any]:
    """Separa entrenamiento y validación **por fecha, no al azar**.

    Repartir aleatoriamente mete casos posteriores en el entrenamiento, y entonces
    el modelo ha visto cómo acabó lo que tiene que predecir. El acierto sale
    magnífico y no significa nada: en producción no existe el futuro.
    """
    con_fecha = [c for c in casos if isinstance(c.get("cerrado_el"), date)]
    if len(con_fecha) != len(casos):
        raise ErrorValidacion(
            f"{len(casos) - len(con_fecha)} casos no tienen fecha de cierre. Sin ella no "
            "se puede separar por tiempo, y separar al azar infla el acierto.",
            error_code="modelo.caso_sin_fecha",
        )
    ordenados = sorted(con_fecha, key=lambda c: c["cerrado_el"])
    corte = len(ordenados) - max(1, len(ordenados) * pct_validacion // 100)
    return {
        "entrenamiento": ordenados[:corte],
        "validacion": ordenados[corte:],
        "corte": ordenados[corte]["cerrado_el"].isoformat() if corte < len(ordenados) else None,
        "porque": (
            "Separado por fecha: el modelo se entrena con lo viejo y se comprueba con lo "
            "nuevo, que es lo que le va a pasar en producción."
        ),
    }


def evaluar_modelo(*, predicciones: list[dict[str, Any]], umbral: float = 0.5) -> dict[str, Any]:
    """Qué tal acierta, **comparado con no tener modelo**.

    Esta es la comparación que nadie hace: si solo se gana el 15 %, decir «todos
    pierden» acierta el 85 % de las veces. Un modelo con un 86 % de acierto suena
    bien y no aporta nada — y con ese número se justifica un proyecto entero.

    Se enseñan además los **falsos negativos**, que son los que duelen: las
    oportunidades que el modelo dijo que no y se ganaron son las que nadie llamó.
    """
    if not predicciones:
        return {
            "medible": False,
            "porque": "No hay predicciones con resultado conocido todavía.",
        }

    reales = [p for p in predicciones if p.get("resultado") in ("ganado", "perdido")]
    if not reales:
        return {"medible": False, "porque": "Ninguna predicción tiene resultado conocido."}

    positivos = [p for p in reales if p["resultado"] == "ganado"]
    aciertos = 0
    falsos_negativos: list[Any] = []
    falsos_positivos = 0
    for p in reales:
        dijo_si = float(p.get("puntuacion") or 0) >= umbral
        gano = p["resultado"] == "ganado"
        if dijo_si == gano:
            aciertos += 1
        elif gano:
            falsos_negativos.append(p.get("referencia"))
        else:
            falsos_positivos += 1

    tasa_base = len(positivos) / len(reales)
    regla_tonta = max(tasa_base, 1 - tasa_base)
    acierto = aciertos / len(reales)

    return {
        "medible": True,
        "casos": len(reales),
        "acierto": round(acierto * 100, 1),
        "acierto_de_la_regla_tonta": round(regla_tonta * 100, 1),
        "aporta": acierto > regla_tonta + 0.03,
        "falsos_negativos": falsos_negativos[:20],
        "falsos_positivos": falsos_positivos,
        "veredicto": (
            f"El modelo acierta el {round(acierto * 100, 1)} % y decir siempre lo mismo "
            f"acertaría el {round(regla_tonta * 100, 1)} %: no aporta lo suficiente para "
            "tomar decisiones con él."
            if acierto <= regla_tonta + 0.03
            else f"El modelo acierta el {round(acierto * 100, 1)} % frente al "
            f"{round(regla_tonta * 100, 1)} % de la regla tonta."
        ),
        "que_duele": (
            f"{len(falsos_negativos)} oportunidades que el modelo descartó y se ganaron. "
            "Son las que nadie habría llamado."
            if falsos_negativos
            else ""
        ),
    }


def factores(*, contribuciones: dict[str, float], cuantos: int = 5) -> dict[str, Any]:
    """Los porqués de una puntuación, ordenados por cuánto empujaron.

    «Esto puntúa 78 porque han abierto tres presupuestos y porque llevan dos
    semanas sin contestar» es accionable. «Esto puntúa 78» no lo es, y además no
    se cree — el comercial estuvo en la reunión y el modelo no.

    Se enseñan también **los que restan**. Un panel que solo cuenta lo que suma
    hace pensar que la puntuación es baja por falta de datos, cuando puede ser por
    algo concreto que se puede arreglar.
    """
    ordenadas = sorted(contribuciones.items(), key=lambda kv: -abs(kv[1]))
    suman = [{"factor": k, "empuja": round(v, 3)} for k, v in ordenadas if v > 0][:cuantos]
    restan = [{"factor": k, "empuja": round(v, 3)} for k, v in ordenadas if v < 0][:cuantos]
    return {
        "suman": suman,
        "restan": restan,
        "medible": bool(ordenadas),
        "porque": (
            "Ordenados por cuánto empujaron. Sin esto la puntuación se mira una vez, no "
            "coincide con lo que el comercial sabe de su cliente, y ya no se mira más."
            if ordenadas
            else "El modelo no ha devuelto contribuciones: la puntuación no se puede "
            "explicar, y una puntuación que no se explica no se usa."
        ),
    }


def segmento_predictivo(
    *, candidatos: list[dict[str, Any]], minimo_puntuacion: float, tope: int | None = None
) -> dict[str, Any]:
    """Un segmento definido por propensión en vez de por filtros.

    Y con la advertencia que lo hace honesto: un segmento predictivo **cambia
    solo**. Quien lo usa para una campaña tiene que saber que la lista de hoy no
    es la de la semana que viene, porque si no comparará resultados de dos
    audiencias distintas creyendo que son la misma.
    """
    dentro = [c for c in candidatos if float(c.get("puntuacion") or 0) >= minimo_puntuacion]
    dentro.sort(key=lambda c: -float(c.get("puntuacion") or 0))
    recortado = dentro[:tope] if tope else dentro
    sin_puntuacion = [c for c in candidatos if c.get("puntuacion") is None]

    return {
        "miembros": [str(c.get("id")) for c in recortado],
        "cuantos": len(recortado),
        "sin_puntuacion": len(sin_puntuacion),
        "es_dinamico": True,
        "aviso": (
            "Este segmento cambia solo: la lista de hoy no es la de la semana que viene. "
            "Comparar resultados de dos ejecuciones es comparar dos audiencias distintas."
        ),
        "los_sin_puntuar": (
            ""
            if not sin_puntuacion
            else f"{len(sin_puntuacion)} candidatos no tienen puntuación y se quedan "
            "fuera. No es que no encajen: es que no se han podido puntuar, normalmente "
            "por falta de datos."
        ),
    }


def deriva(
    *, distribucion_entrenamiento: dict[str, float], distribucion_hoy: dict[str, float]
) -> dict[str, Any]:
    """Si el mundo ha cambiado desde que se entrenó el modelo.

    Un modelo no avisa cuando deja de valer: sigue dando números con la misma
    seguridad. Si el mix de clientes ha cambiado —otro sector, otro tamaño, otro
    canal—, el modelo sigue puntuando como si nada y nadie lo nota hasta que
    alguien compara el acierto de este trimestre con el del anterior.
    """
    claves = set(distribucion_entrenamiento) | set(distribucion_hoy)
    cambios = []
    for clave in sorted(claves):
        antes = float(distribucion_entrenamiento.get(clave, 0))
        ahora = float(distribucion_hoy.get(clave, 0))
        if abs(ahora - antes) >= 10:
            cambios.append(
                {
                    "segmento": clave,
                    "antes_pct": antes,
                    "ahora_pct": ahora,
                    "diferencia": round(ahora - antes, 1),
                }
            )
    return {
        "hay_deriva": bool(cambios),
        "cambios": cambios,
        "que_significa": (
            "El mix de casos se parece al del entrenamiento."
            if not cambios
            else "El mundo ha cambiado desde que se entrenó. El modelo seguirá dando "
            "números con la misma seguridad, y nadie lo notará hasta comparar el acierto "
            "de dos trimestres."
        ),
    }
