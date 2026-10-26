"""Diseñador visual de formularios y listas (CRM-00.04.03.01).

Arrastrar campos, hacer secciones y pestañas y poner condiciones de visibilidad
**sin escribir nada**. La disposición ya vivía en `layouts`; lo que faltaba era
que alguien pudiera componerla sin saber JSON, y sobre todo que el sistema
**dijera que no** cuando el diseño está mal.

Un diseñador que guarda lo que le echen no es un diseñador: es un editor de
JSON con ratón. Los tres fallos que se cometen siempre no dan error al guardar y
se descubren semanas después, cuando un usuario dice «es que ese campo no está»:

**Un campo que no existe en el esquema.** Se guarda, no se pinta, y nadie
relaciona la pantalla vacía con el diseño que se tocó hace un mes.

**El mismo campo en dos sitios.** Se pinta dos veces, el usuario escribe en uno,
y al guardar gana el otro — el que no tocó.

**Y una condición de visibilidad usada como permiso.** Esta es la peligrosa:
esconder el margen a los comerciales con una condición NO se lo esconde. El dato
sigue viajando en la API, y basta con abrir las herramientas del navegador. Lo
que no se puede ver es un permiso; una condición solo quita ruido de la
pantalla.

Y una decisión de fondo: **las condiciones se evalúan en el servidor**, con el
registro delante, y el formulario servido ya viene sin lo que no toca pintar. Si
las evaluara el front, el dato del campo escondido habría viajado igualmente.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import ErrorValidacion, NoEncontrado
from crmcore.logging import get_logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.metadata.modelos import Layout, ObjetoDefinido
from services.metadata.vistas_servidas import componente_de, validar_diseno

logger = get_logger(__name__)

# Operadores que admite una condición de visibilidad. Lista cerrada: con texto
# libre, una condición mal escrita se queda en «no se cumple nunca», y el campo
# no aparece jamás sin que nadie sepa por qué.
OPERADORES = ("=", "!=", ">", ">=", "<", "<=", "vacio", "no_vacio", "en")


# Cuántos campos caben en una sección antes de avisar. No es un tope: es que un
# formulario de cuarenta campos seguidos no se rellena, se abandona a la mitad,
# y eso sale luego en forma de fichas incompletas.
def _disenador_aviso_campos() -> int:
    """Antes `_disenador_aviso_campos() = 15`.

    Era una constante de módulo. Sale del `.env`, que es donde una instalación
    puede afinarla sin tocar código.
    """
    from crmcore.config import get_settings

    return get_settings().disenador_aviso_campos


def _claves_del_esquema(campos: list[dict[str, Any]]) -> set[str]:
    return {str(c.get("clave")) for c in campos}


def validar_condicion(condicion: dict[str, Any], claves: set[str]) -> list[str]:
    """Qué le pasa a una condición de visibilidad. Lista vacía = está bien."""
    problemas: list[str] = []
    campo = str(condicion.get("campo") or "")
    operador = str(condicion.get("operador") or "")
    if campo not in claves:
        problemas.append(
            f"La condición mira «{campo}», que no existe en el objeto. Una condición "
            "sobre un campo inexistente no se cumple nunca: el campo no aparecerá "
            "jamás y nadie sabrá por qué."
        )
    if operador not in OPERADORES:
        problemas.append(f"Operador «{operador}» desconocido. Admitidos: {', '.join(OPERADORES)}.")
    elif operador not in ("vacio", "no_vacio") and "valor" not in condicion:
        problemas.append(
            f"La condición con «{operador}» no trae valor con el que comparar, así que "
            "no se cumple nunca."
        )
    return problemas


def validar_layout(
    *, secciones: list[dict[str, Any]], campos_del_esquema: list[dict[str, Any]]
) -> dict[str, Any]:
    """Comprueba un diseño completo antes de guardarlo.

    Se devuelven **todos** los problemas de una vez: a quien está arrastrando
    campos le sirve mucho más ver las cuatro cosas que fallan que descubrirlas
    de una en una, con un intento de guardar entre cada dos.
    """
    claves = _claves_del_esquema(campos_del_esquema)
    por_clave = {str(c.get("clave")): c for c in campos_del_esquema}
    problemas: list[dict[str, str]] = []
    avisos: list[str] = []
    vistos: dict[str, str] = {}
    planos: list[dict[str, Any]] = []

    if not secciones:
        problemas.append(
            {
                "donde": "(el diseño)",
                "problema": "no tiene ninguna sección",
                "consecuencia": "el formulario saldría en blanco",
            }
        )

    claves_seccion: set[str] = set()
    for seccion in secciones:
        clave_seccion = str(seccion.get("clave") or "")
        if not clave_seccion:
            problemas.append(
                {
                    "donde": str(seccion.get("titulo") or "(sin título)"),
                    "problema": "la sección no tiene clave",
                    "consecuencia": "no se puede referenciar ni recordar si estaba abierta",
                }
            )
        if clave_seccion in claves_seccion:
            problemas.append(
                {
                    "donde": clave_seccion,
                    "problema": "hay dos secciones con la misma clave",
                    "consecuencia": "la segunda pisa a la primera al pintar",
                }
            )
        claves_seccion.add(clave_seccion)

        campos_seccion = list(seccion.get("campos") or [])
        if len(campos_seccion) > _disenador_aviso_campos():
            avisos.append(
                f"La sección «{clave_seccion}» tiene {len(campos_seccion)} campos "
                "seguidos. Un formulario así no se rellena: se abandona a la mitad, y "
                "eso vuelve en forma de fichas incompletas."
            )

        for campo in campos_seccion:
            clave = str(campo.get("clave") or "")
            if clave not in claves:
                problemas.append(
                    {
                        "donde": f"{clave_seccion}.{clave}",
                        "problema": "el campo no existe en el objeto",
                        "consecuencia": (
                            "se guarda, no se pinta, y nadie relaciona la pantalla "
                            "vacía con el diseño que se tocó hace un mes"
                        ),
                    }
                )
            elif clave in vistos:
                problemas.append(
                    {
                        "donde": f"{clave_seccion}.{clave}",
                        "problema": f"el campo ya está en «{vistos[clave]}»",
                        "consecuencia": (
                            "se pinta dos veces; el usuario escribe en uno y al guardar "
                            "gana el otro, el que no tocó"
                        ),
                    }
                )
            else:
                vistos[clave] = clave_seccion

            condicion = campo.get("condicion") or seccion.get("condicion")
            if condicion:
                for texto in validar_condicion(dict(condicion), claves):
                    problemas.append(
                        {
                            "donde": f"{clave_seccion}.{clave}",
                            "problema": texto,
                            "consecuencia": "el campo no aparecería nunca",
                        }
                    )
                if por_clave.get(clave, {}).get("permiso"):
                    avisos.append(
                        f"«{clave}» tiene condición de visibilidad Y permiso. Está "
                        "bien, pero que quede claro: lo que protege el dato es el "
                        "permiso. La condición solo quita ruido de la pantalla."
                    )

            definicion = por_clave.get(clave)
            if definicion is not None:
                # Que el tipo tenga componente se comprueba aquí y no al pintar:
                # descubrirlo al servir el formulario deja al usuario delante de
                # una pantalla rota por un diseño que se guardó sin protestar.
                componente_de(str(definicion.get("tipo") or ""))
                planos.append(
                    {
                        **definicion,
                        "seccion": clave_seccion,
                        "en_pestana_secundaria": bool(seccion.get("pestana"))
                        and not seccion.get("pestana_principal"),
                    }
                )

    del_esquema_sin_colocar = sorted(
        c for c in claves if c not in vistos and por_clave[c].get("obligatorio")
    )
    if del_esquema_sin_colocar:
        problemas.append(
            {
                "donde": "(el diseño)",
                "problema": f"campos obligatorios que no están en ninguna sección: "
                f"{', '.join(del_esquema_sin_colocar)}",
                "consecuencia": (
                    "no se pueden rellenar y el alta fallará sin que el usuario vea "
                    "dónde está el problema"
                ),
            }
        )

    base = validar_diseno(campos=planos, secciones=[{"clave": c} for c in claves_seccion if c])
    problemas.extend(
        {
            "donde": p["campo"],
            "problema": p["problema"],
            "consecuencia": p["consecuencia"],
        }
        for p in base["problemas"]
    )

    return {
        "valido": not problemas,
        "problemas": problemas,
        "avisos": avisos,
        "campos_colocados": len(vistos),
        "campos_del_objeto": len(claves),
        "sin_colocar": sorted(claves - set(vistos)),
    }


def guardar(
    uow: UnidadDeTrabajo,
    *,
    objeto: str,
    nombre: str,
    secciones: list[dict[str, Any]],
    campos_del_esquema: list[dict[str, Any]],
    rol: str | None = None,
    es_defecto: bool = False,
) -> dict[str, Any]:
    """Guarda un diseño, **o no lo guarda y dice por qué**.

    Rechazar aquí es lo que hace que esto sea un diseñador y no un editor de
    JSON con ratón: los tres fallos típicos no dan error al pintar y se
    descubren semanas después.
    """
    veredicto = validar_layout(secciones=secciones, campos_del_esquema=campos_del_esquema)
    if not veredicto["valido"]:
        raise ErrorValidacion(
            f"El diseño tiene {len(veredicto['problemas'])} problemas que no darían "
            "error al guardar y se descubrirían semanas después.",
            error_code="disenador.diseno_invalido",
            detalle={"problemas": veredicto["problemas"]},
        )

    definido = uow.db.execute(
        select(ObjetoDefinido).where(
            ObjetoDefinido.tenant_id == uow.tenant_id, ObjetoDefinido.nombre == objeto
        )
    ).scalar_one_or_none()
    if definido is None:
        raise NoEncontrado(
            f"No hay ningún objeto «{objeto}» en este tenant",
            error_code="disenador.objeto_desconocido",
        )

    layout = uow.db.execute(
        select(Layout).where(Layout.objeto_id == definido.id, Layout.nombre == nombre)
    ).scalar_one_or_none()
    if layout is None:
        layout = Layout(tenant_id=uow.tenant_id, objeto_id=definido.id, nombre=nombre, secciones=[])
        uow.db.add(layout)

    layout.secciones = secciones
    layout.rol = rol
    layout.es_defecto = es_defecto
    uow.db.flush()

    if es_defecto:
        # Solo puede haber uno por defecto: con dos, cuál sale depende del orden
        # que devuelva la base, y eso cambia sin que nadie toque nada.
        for otro in (
            uow.db.execute(
                select(Layout).where(
                    Layout.objeto_id == definido.id,
                    Layout.es_defecto.is_(True),
                    Layout.id != layout.id,
                )
            )
            .scalars()
            .all()
        ):
            otro.es_defecto = False
        uow.db.flush()

    return {
        "objeto": objeto,
        "nombre": nombre,
        "secciones": len(secciones),
        "avisos": veredicto["avisos"],
        "sin_colocar": veredicto["sin_colocar"],
    }


def mover(
    *,
    secciones: list[dict[str, Any]],
    campo: str,
    a_seccion: str,
    posicion: int | None = None,
) -> list[dict[str, Any]]:
    """Arrastrar un campo de una sección a otra.

    Se **quita de donde estaba**. Parece obvio y es justo lo que se olvida en un
    diseñador hecho a mano: un «añadir» sin «quitar» deja el campo en los dos
    sitios, que es el fallo que hace que al guardar gane el que el usuario no
    tocó.
    """
    destino = next((s for s in secciones if str(s.get("clave")) == a_seccion), None)
    if destino is None:
        raise ErrorValidacion(
            f"No existe la sección «{a_seccion}»", error_code="disenador.seccion_desconocida"
        )

    movido: dict[str, Any] | None = None
    nuevas: list[dict[str, Any]] = []
    for seccion in secciones:
        copia = dict(seccion)
        campos = []
        for c in seccion.get("campos") or []:
            if str(c.get("clave")) == campo:
                movido = dict(c)
                continue
            campos.append(c)
        copia["campos"] = campos
        nuevas.append(copia)

    if movido is None:
        raise ErrorValidacion(
            f"El campo «{campo}» no está en ninguna sección del diseño",
            error_code="disenador.campo_no_colocado",
        )

    for seccion in nuevas:
        if str(seccion.get("clave")) == a_seccion:
            campos = list(seccion["campos"])
            indice = len(campos) if posicion is None else max(0, min(posicion, len(campos)))
            campos.insert(indice, movido)
            seccion["campos"] = campos
    return nuevas


def _cumple(condicion: dict[str, Any], registro: dict[str, Any]) -> bool:
    valor = registro.get(str(condicion.get("campo")))
    operador = str(condicion.get("operador"))
    esperado = condicion.get("valor")
    if operador == "vacio":
        return valor in (None, "", [], {})
    if operador == "no_vacio":
        return valor not in (None, "", [], {})
    if operador == "en":
        return valor in (esperado or [])
    if operador == "=":
        return valor == esperado
    if operador == "!=":
        return valor != esperado
    if valor is None or esperado is None:
        # Comparar un nulo con `>` no es falso: es que no se puede comparar. Y
        # tratarlo como falso esconde el campo sin que nadie sepa por qué.
        return False
    if operador == ">":
        return bool(valor > esperado)
    if operador == ">=":
        return bool(valor >= esperado)
    if operador == "<":
        return bool(valor < esperado)
    return bool(valor <= esperado)


def evaluar_visibilidad(
    *, secciones: list[dict[str, Any]], registro: dict[str, Any]
) -> dict[str, Any]:
    """Resuelve las condiciones **en el servidor**, con el registro delante.

    Si las evaluara el front, el dato del campo escondido habría viajado hasta el
    navegador igualmente, y ahí ya lo ve cualquiera que abra las herramientas de
    desarrollo.

    Y se dice **cuántos** se han escondido y por qué. Sin eso, el usuario cree
    que su ficha tiene ocho campos cuando tiene catorce, y llama preguntando
    dónde se mete un dato que sí existe.
    """
    visibles: list[dict[str, Any]] = []
    escondidos: list[dict[str, str]] = []

    for seccion in secciones:
        condicion_seccion = seccion.get("condicion")
        seccion_visible = not condicion_seccion or _cumple(dict(condicion_seccion), registro)
        campos_visibles: list[dict[str, Any]] = []
        for campo in seccion.get("campos") or []:
            clave = str(campo.get("clave"))
            if not seccion_visible:
                escondidos.append(
                    {
                        "campo": clave,
                        "porque": f"su sección «{seccion.get('clave')}» no cumple la condición",
                    }
                )
                continue
            condicion = campo.get("condicion")
            if condicion and not _cumple(dict(condicion), registro):
                escondidos.append(
                    {
                        "campo": clave,
                        "porque": (f"la condición sobre «{condicion.get('campo')}» no se cumple"),
                    }
                )
                continue
            campos_visibles.append(campo)
        if seccion_visible:
            visibles.append({**seccion, "campos": campos_visibles})

    return {
        "secciones": visibles,
        "escondidos": escondidos,
        "cuantos_escondidos": len(escondidos),
        "aviso": (
            ""
            if not escondidos
            else "Esconder un campo por condición NO lo protege: lo que no se puede "
            "ver es un permiso. La condición solo quita ruido de la pantalla."
        ),
    }


def columnas_de_lista(
    *, columnas: list[dict[str, Any]], campos_del_esquema: list[dict[str, Any]]
) -> dict[str, Any]:
    """El diseñador de la vista de lista (CRM-00.04.03.01, la parte de listas).

    Dos cosas que no dan error y estropean la lista:

    **Una columna sobre un campo que no existe** sale vacía en todas las filas, y
    se lee como «ningún cliente tiene ese dato».

    **Y ordenar por un campo de texto largo o por un JSON** hace un recorrido
    completo de la tabla en cada carga. Con mil filas no se nota; con un millón,
    la lista deja de abrirse y nadie relaciona una cosa con la otra.
    """
    por_clave = {str(c.get("clave")): c for c in campos_del_esquema}
    problemas: list[dict[str, str]] = []
    salida: list[dict[str, Any]] = []

    for columna in columnas:
        clave = str(columna.get("clave") or "")
        definicion = por_clave.get(clave)
        if definicion is None:
            problemas.append(
                {
                    "columna": clave,
                    "problema": "el campo no existe",
                    "consecuencia": (
                        "la columna sale vacía en todas las filas y se lee como que "
                        "ningún registro tiene ese dato"
                    ),
                }
            )
            continue
        tipo = str(definicion.get("tipo") or "")
        if columna.get("ordenable") and tipo in ("texto_largo", "json", "geolocalizacion"):
            problemas.append(
                {
                    "columna": clave,
                    "problema": f"se quiere ordenar por un campo de tipo «{tipo}»",
                    "consecuencia": (
                        "obliga a recorrer la tabla entera en cada carga; con mil filas "
                        "no se nota y con un millón la lista deja de abrirse"
                    ),
                }
            )
            continue
        salida.append(
            {
                "clave": clave,
                "etiqueta": definicion.get("etiqueta") or clave,
                "componente": componente_de(tipo),
                "ordenable": bool(columna.get("ordenable")),
                "ancho": columna.get("ancho"),
            }
        )

    return {"valido": not problemas, "columnas": salida, "problemas": problemas}


def layout_efectivo(
    db: Session, tenant_id: UUID, *, objeto: str, rol: str | None = None
) -> dict[str, Any]:
    """Qué diseño le toca a este usuario, y **por qué ese**.

    El «por qué» no es adorno: con varios layouts por rol, la pregunta que llega
    a soporte es siempre «¿por qué yo veo otra pantalla?», y sin esto hay que
    mirarlo en la base.
    """
    definido = db.execute(
        select(ObjetoDefinido).where(
            ObjetoDefinido.tenant_id == tenant_id, ObjetoDefinido.nombre == objeto
        )
    ).scalar_one_or_none()
    if definido is None:
        raise NoEncontrado(
            f"No hay ningún objeto «{objeto}» en este tenant",
            error_code="disenador.objeto_desconocido",
        )

    layouts = list(
        db.execute(select(Layout).where(Layout.objeto_id == definido.id)).scalars().all()
    )
    por_rol = next((lay for lay in layouts if rol and lay.rol == rol), None)
    defecto = next((lay for lay in layouts if lay.es_defecto), None)
    elegido = por_rol or defecto or (layouts[0] if layouts else None)

    if elegido is None:
        return {
            "objeto": objeto,
            "hay_diseno": False,
            "porque": (
                "Este objeto no tiene ningún layout diseñado. El front pintará los "
                "campos en el orden del esquema, que es un orden técnico y no el que "
                "tiene sentido para quien rellena la ficha."
            ),
        }

    return {
        "objeto": objeto,
        "hay_diseno": True,
        "nombre": elegido.nombre,
        "secciones": elegido.secciones,
        "porque": (
            f"Hay un layout para el rol «{rol}»."
            if por_rol
            else "Es el layout por defecto."
            if defecto
            else "No hay ninguno marcado por defecto, así que sale el único que hay. "
            "Conviene marcar uno: con dos sin marcar, cuál sale depende del orden que "
            "devuelva la base."
        ),
    }
