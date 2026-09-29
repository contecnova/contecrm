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
from uuid import UUID

from crmcore.errors import ErrorValidacion, NoEncontrado
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
    nombre: str,
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
                f"La descripción de «{nombre}» es demasiado corta para servir de algo. "
                "Hace falta qué significa, en qué se basa y quién lo rellena: con menos, "
                "el catálogo parece completo y sigue sin poder usarse.",
                error_code="semantica.descripcion_pobre",
            )
        if texto.lower().strip(" .") == etiqueta.lower().strip(" ."):
            raise ErrorValidacion(
                f"La descripción de «{nombre}» es la etiqueta otra vez. Eso ya lo "
                "teníamos: lo que falta es qué significa.",
                error_code="semantica.descripcion_es_la_etiqueta",
            )

    sin_explicar = [
        str(v.get("valor")) for v in (valores or []) if not str(v.get("significa") or "").strip()
    ]

    return {
        "nombre": nombre,
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
    fuera_sensibles = [c["nombre"] for c in campos if c.get("sensible")]
    fuera_internos = [c["nombre"] for c in campos if c.get("rol") == "interno"]
    sin_describir = [c["nombre"] for c in campos if not str(c.get("descripcion") or "").strip()]

    return {
        "objeto": objeto,
        "campos": [
            {
                "nombre": c["nombre"],
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
            c["nombre"] for c in campos if not str(c.get("descripcion") or "").strip()
        ][:20],
    }


# ── Dónde vive todo esto ──────────────────────────────────────────────────
#
# Hasta aquí es una función pura: valida y devuelve. Lo que sigue es lo que la
# conecta con el producto, y es lo que faltaba: la ruta que declaraba semántica
# validaba el cuerpo, devolvía el resultado y **no lo guardaba en ningún sitio**.
# Una semántica que se pierde al contestar deja el catálogo exactamente igual de
# vacío que estaba, con la diferencia de que el que la declaró se fue creyendo
# que estaba hecho.

# Sensibilidades que dejan un campo fuera de cualquier contexto de inferencia.
# Se derivan de `sensibilidad`, que ya es la clasificación oficial del campo
# (CRM-07.03.01.05) y de la que salen el enmascaramiento por rol y el mapa de
# datos personales. Una segunda columna «sensible» acabaría contradiciéndola, y
# entonces no se sabría cuál manda.
SENSIBILIDADES_RESERVADAS = frozenset({"confidencial", "personal", "especial"})


def es_sensible(sensibilidad: str) -> bool:
    """Si el contenido de este campo puede salir hacia un proveedor de inferencia."""
    return str(sensibilidad or "").strip().lower() in SENSIBILIDADES_RESERVADAS


def _como_semantica(campo: Any) -> dict[str, Any]:
    """Un campo del modelo, en la forma que entiende esta capa."""
    sensible = es_sensible(campo.sensibilidad)
    return {
        "nombre": campo.nombre,
        "etiqueta": campo.etiqueta,
        "tipo": campo.tipo,
        "rol": campo.rol_semantico,
        "descripcion": campo.descripcion_semantica,
        "valores": list(campo.valores_semanticos or []),
        "sensible": sensible,
        # Que esté marcado explotable no basta: lo sensible no sale aunque
        # alguien lo marque, y el que lo marcó rara vez lo piensa.
        "explotable": bool(campo.explotable) and not sensible,
    }


def campos_descritos(db: Any, tenant_id: UUID, objeto: str) -> list[dict[str, Any]]:
    """Los campos personalizados de un objeto, con lo que significan.

    Se leen de **la tabla de campos de este servicio**, no de la réplica que
    viaja por el bus: la réplica lleva lo justo para validar, filtrar e indexar
    —y eso está decidido a propósito, mandar de más engorda cada evento— así que
    no lleva descripciones. Esta ruta vive en `metadata`, que es donde están los
    campos: ir a buscarlos a una copia recortada era el fallo.
    """
    from sqlalchemy import select

    from services.metadata.modelos import CampoDefinido, ObjetoDefinido

    fila = db.execute(
        select(ObjetoDefinido).where(
            ObjetoDefinido.tenant_id == tenant_id, ObjetoDefinido.nombre == objeto
        )
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado(
            f"El objeto «{objeto}» no existe", error_code="metadata.objeto_no_encontrado"
        )
    campos = (
        db.execute(
            select(CampoDefinido)
            .where(CampoDefinido.objeto_id == fila.id, CampoDefinido.activo.is_(True))
            .order_by(CampoDefinido.orden, CampoDefinido.nombre)
        )
        .scalars()
        .all()
    )
    return [_como_semantica(c) for c in campos]


def declarar(
    db: Any,
    tenant_id: UUID,
    objeto: str,
    *,
    nombre: str,
    descripcion: str,
    rol: str,
    valores: list[dict[str, Any]] | None = None,
    explotable: bool = True,
) -> dict[str, Any]:
    """Guarda qué significa un campo. Esto es lo que antes se perdía.

    Se exige que el campo **exista**: declarar la semántica de un campo que no
    está deja una descripción huérfana que nadie volverá a mirar y que hace que
    la cobertura mienta hacia arriba.

    La etiqueta, el tipo y la sensibilidad **no se reciben**: ya están en el
    campo. Recibirlos permitiría declarar «este campo no es sensible» sobre uno
    clasificado como personal, que es justo la puerta por la que se escapa un
    dato de salud a un proveedor de inferencia.
    """
    from sqlalchemy import select

    from services.metadata.modelos import CampoDefinido, ObjetoDefinido

    objeto_fila = db.execute(
        select(ObjetoDefinido).where(
            ObjetoDefinido.tenant_id == tenant_id, ObjetoDefinido.nombre == objeto
        )
    ).scalar_one_or_none()
    if objeto_fila is None:
        raise NoEncontrado(
            f"El objeto «{objeto}» no existe", error_code="metadata.objeto_no_encontrado"
        )
    campo = db.execute(
        select(CampoDefinido).where(
            CampoDefinido.objeto_id == objeto_fila.id, CampoDefinido.nombre == nombre
        )
    ).scalar_one_or_none()
    if campo is None:
        raise NoEncontrado(
            f"El campo «{nombre}» no existe en «{objeto}»: no se puede describir lo que "
            "no está. Crea el campo primero.",
            error_code="metadata.campo_no_encontrado",
        )

    # Se valida ANTES de escribir, y con los datos del campo de verdad.
    descrito = describir_campo(
        nombre=nombre,
        etiqueta=campo.etiqueta,
        tipo=campo.tipo,
        descripcion=descripcion,
        rol=rol,
        valores=valores,
        sensible=es_sensible(campo.sensibilidad),
        explotable=explotable,
    )

    campo.descripcion_semantica = descrito["descripcion"]
    campo.rol_semantico = descrito["rol"]
    campo.valores_semanticos = descrito["valores"]
    campo.explotable = bool(explotable)
    db.flush()

    logger.info(
        "metadata.semantica_declarada",
        objeto=objeto,
        campo=nombre,
        rol=rol,
        explotable=descrito["explotable"],
    )
    return descrito
