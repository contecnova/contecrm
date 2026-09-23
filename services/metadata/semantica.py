"""Los campos personalizados, explicados para que la IA los pueda usar
(CRM-00.04.03.07).

Un tenant crea un campo `cmp_2`, de tipo lista, con valores `A`, `B` y `C`. Para
el CRM es perfecto: se guarda, se valida, se filtra. Para cualquier cosa que tenga
que **razonar** sobre esos datos —un asistente, un modelo, una consulta en
lenguaje natural— es basura: no sabe qué es `cmp_2` ni qué significa `B`.

Esto es lo que resuelve. No es documentación bonita: es la diferencia entre que la
pregunta «¿cuántos clientes están en riesgo?» encuentre el campo que el cliente
usa para eso o conteste que no hay ninguno.

Las decisiones:

**La descripción es obligatoria para lo que se quiere explotar, y no es la
etiqueta.** «Segmento» como etiqueta y como descripción no aporta nada: hace falta
qué significa, en qué se basa y quién lo rellena.

**Los valores de una lista se explican uno a uno.** Saber que el campo admite `A`,
`B` y `C` no sirve de nada; saber que `C` significa «cliente en revisión de
crédito» cambia lo que se puede preguntar.

**Lo sensible se marca para que quede fuera.** Un campo personalizado con el
diagnóstico de un paciente no entra en un contexto que se manda a un proveedor de
inferencia, y quien lo creó rara vez lo piensa.

**Y se dice qué NO se puede explotar todavía.** Un catálogo semántico incompleto
que no dice que lo está hace que quien pregunte concluya que el dato no existe,
cuando lo que pasa es que nadie lo ha descrito.
"""

from __future__ import annotations

from typing import Any

from crmcore.errors import ErrorValidacion
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Para qué sirve un campo, desde el punto de vista de quien razona con él. Cerrada
# porque cada categoría se usa distinto: por una se agrupa, por otra se ordena y
# otra no se toca nunca.
ROLES_SEMANTICOS = (
    "identificador",
    "clasificacion",  # agrupa: sector, segmento, tipo
    "medida",  # se suma o se promedia
    "fecha",
    "estado",  # posición en un ciclo
    "texto_libre",  # se lee, no se agrega
    "referencia",
    "interno",  # no se explota: notas, campos técnicos
)

# Longitud mínima de una descripción útil. No es una cifra mágica: por debajo de
# eso lo que se escribe es la etiqueta otra vez, y eso ya lo teníamos.
MINIMO_DESCRIPCION = 25


def describir_campo(
    *,
    clave: str,
    etiqueta: str,
    tipo: str,
    descripcion: str,
    rol: str,
    valores: list[dict[str, Any]] | None = None,
    sensible: bool = False,
    explotable: bool = True,
) -> dict[str, Any]:
    """Declara qué significa un campo personalizado.

    Se exige que la descripción **diga algo más que la etiqueta**. «Segmento:
    segmento» es la forma más común de rellenar este campo y deja el catálogo
    exactamente igual de inútil que estaba, con la diferencia de que ahora parece
    completo.
    """
    if rol not in ROLES_SEMANTICOS:
        raise ErrorValidacion(
            f"Rol semántico «{rol}» desconocido",
            error_code="semantica.rol_invalido",
            detalle={"admitidos": list(ROLES_SEMANTICOS)},
        )
    texto = descripcion.strip()
    if explotable and rol != "interno":
        if len(texto) < MINIMO_DESCRIPCION:
            raise ErrorValidacion(
                f"La descripción de «{clave}» es demasiado corta para servir de algo. "
                "Hace falta qué significa, en qué se basa y quién lo rellena: con menos, "
                "el catálogo parece completo y sigue sin poder usarse.",
                error_code="semantica.descripcion_pobre",
            )
        if texto.lower().strip(" .") == etiqueta.lower().strip(" ."):
            raise ErrorValidacion(
                f"La descripción de «{clave}» es la etiqueta otra vez. Eso ya lo "
                "teníamos: lo que falta es qué significa.",
                error_code="semantica.descripcion_es_la_etiqueta",
            )

    sin_explicar = [
        str(v.get("valor")) for v in (valores or []) if not str(v.get("significa") or "").strip()
    ]

    return {
        "clave": clave,
        "etiqueta": etiqueta,
        "tipo": tipo,
        "rol": rol,
        "descripcion": texto,
        "valores": valores or [],
        "valores_sin_explicar": sin_explicar,
        "sensible": sensible,
        "explotable": explotable and not sensible,
        "porque_no_se_explota": (
            ""
            if not sensible
            else "Está marcado como sensible: no entra en ningún contexto que se mande a "
            "un proveedor de inferencia. Quien crea el campo rara vez lo piensa, y por "
            "eso se pregunta al declararlo."
        ),
        "aviso": (
            ""
            if not sin_explicar
            else f"{len(sin_explicar)} valores de la lista no dicen qué significan. Saber "
            "que el campo admite «A», «B» y «C» no sirve de nada; saber que «C» es "
            "«cliente en revisión de crédito» cambia lo que se puede preguntar."
        ),
    }


def contexto_semantico(*, objeto: str, campos: list[dict[str, Any]]) -> dict[str, Any]:
    """El diccionario que se le pasa a lo que tenga que razonar sobre este objeto.

    Va **sin los campos sensibles y sin los internos**, y dice cuántos ha dejado
    fuera. Un contexto recortado en silencio hace que el asistente conteste «no
    hay ningún campo de eso» cuando lo que pasa es que no se lo hemos enseñado.
    """
    utiles = [
        c
        for c in campos
        if c.get("explotable") and c.get("rol") != "interno" and not c.get("sensible")
    ]
    fuera_sensibles = [c["clave"] for c in campos if c.get("sensible")]
    fuera_internos = [c["clave"] for c in campos if c.get("rol") == "interno"]
    sin_describir = [c["clave"] for c in campos if not str(c.get("descripcion") or "").strip()]

    return {
        "objeto": objeto,
        "campos": [
            {
                "clave": c["clave"],
                "significa": c.get("descripcion"),
                "rol": c.get("rol"),
                "tipo": c.get("tipo"),
                "valores": [
                    {"valor": v.get("valor"), "significa": v.get("significa")}
                    for v in (c.get("valores") or [])
                ],
            }
            for c in utiles
        ],
        "fuera_por_sensibles": fuera_sensibles,
        "fuera_por_internos": fuera_internos,
        "sin_describir": sin_describir,
        "completo": not sin_describir,
        "aviso": (
            ""
            if not sin_describir
            else f"{len(sin_describir)} campos de este objeto no están descritos y no "
            "entran en el contexto. Quien pregunte por ellos concluirá que el dato no "
            "existe, cuando lo que pasa es que nadie lo ha explicado."
        ),
    }


def cobertura(*, campos: list[dict[str, Any]]) -> dict[str, Any]:
    """Cuánto del modelo del tenant se puede explotar de verdad.

    Es el número que hay que enseñar antes de prometer que «la IA entiende tus
    datos». Con el 30 % de los campos descritos, entiende el 30 % — y la diferencia
    entre eso y lo que la gente cree que compró es la razón de la mayoría de los
    proyectos de IA decepcionantes.
    """
    if not campos:
        return {
            "medible": False,
            "porque": (
                "Este objeto no tiene campos personalizados. No hay nada que describir "
                "ni nada que prometer."
            ),
        }
    descritos = [c for c in campos if str(c.get("descripcion") or "").strip()]
    explotables = [c for c in descritos if c.get("explotable") and not c.get("sensible")]
    pct = round(len(explotables) / len(campos) * 100, 1)
    return {
        "medible": True,
        "campos": len(campos),
        "descritos": len(descritos),
        "explotables": len(explotables),
        "pct": pct,
        "que_significa": (
            f"Se puede explotar el {pct} % de los campos personalizados. Prometer que "
            "«la IA entiende tus datos» con este porcentaje es la razón de la mayoría de "
            "los proyectos de IA decepcionantes."
            if pct < 70
            else f"El {pct} % de los campos personalizados está descrito y es explotable."
        ),
        "los_que_faltan": [
            c["clave"] for c in campos if not str(c.get("descripcion") or "").strip()
        ][:20],
    }
