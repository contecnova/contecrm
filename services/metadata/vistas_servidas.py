"""Formularios y vistas servidos como datos (CRM-00.02.03.08).

Un CRM configurable tiene un problema que no se ve hasta que hay tres clientes:
cada uno quiere su formulario, y si el formulario vive en el código del front,
cada cambio de cada cliente es un despliegue del producto. A los seis meses hay
cuatro versiones del front y ninguna está bien.

Servir la definición como datos lo arregla, y trae su propio problema: **el front
deja de saber qué va a recibir**. Por eso aquí lo importante no es el JSON, es lo
que se le promete a quien lo pinta.

Las decisiones:

**El contrato es cerrado.** Los tipos de componente son una lista y no texto
libre: un front que recibe un tipo que no conoce solo puede hacer dos cosas, y
las dos son malas — no pintar nada, o pintar una caja de texto que guarda basura
en un campo numérico.

**Lo que el front no entienda se dice en la respuesta.** Cada vista declara con
qué versión del contrato se hizo. Un front viejo recibiendo una vista nueva tiene
que poder decir «no sé pintar esto» en vez de pintarlo mal.

**La validación viaja con el campo, pero no sustituye a la del servidor.** Se
manda para que el usuario no descubra el error después de rellenar veinte campos;
el servidor la vuelve a comprobar entera, porque lo que llega por la API no pasa
por ningún formulario.

**Y los permisos se resuelven al servir, no al pintar.** Mandar el formulario
completo y que el front esconda lo que no toca deja el dato viajando hasta el
navegador: basta con abrir las herramientas para verlo.
"""

from __future__ import annotations

from typing import Any

from crmcore.errors import ErrorValidacion
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Versión del contrato de vistas. Sube cuando se añade un tipo de componente o
# cambia el significado de uno: es lo que permite a un front viejo saber que hay
# algo que no sabe pintar, en vez de pintarlo mal.
VERSION_CONTRATO = 2

# Los componentes que un front tiene que saber pintar. Lista cerrada a propósito:
# con texto libre, uno que recibe «selector_bonito» solo puede no pintar nada o
# pintar una caja de texto que guarda basura en un campo numérico.
COMPONENTES = (
    "texto",
    "texto_largo",
    "numero",
    "moneda",
    # Aparte del número: un porcentaje pintado como número corriente es donde
    # pasa lo de guardar 15 queriendo decir 0,15, y al revés.
    "porcentaje",
    "fecha",
    # Aparte de la fecha: pintar una fecha con hora como fecha pierde la hora y
    # el huso, y la reunión se queda a las 00:00 de un día que no es.
    "fecha_hora",
    "booleano",
    "seleccion",
    "seleccion_multiple",
    "referencia",
    "adjunto",
    # Solo lectura. Pintar una fórmula como campo editable deja escribir encima
    # de un valor calculado: se guarda, se recalcula, y el usuario cree que
    # cambió algo.
    "calculado",
    "mapa",
    # Un JSON en una caja de texto se guarda mal formado y revienta al leerlo,
    # no al escribirlo.
    "json",
    # Un campo cifrado pintado como texto enseña el secreto en pantalla y lo
    # mete en el autocompletado del navegador.
    "secreto",
    "correo",
    "telefono",
    "enlace",
    "seccion",
    "pestana",
    "tabla_relacionada",
)

# Qué componente pinta cada tipo del metamodelo. Las claves son EXACTAMENTE los
# tipos que admite `services/metadata/esquemas.TIPOS_CAMPO`: si aquí hubiera un
# tipo que allí no existe, sería un componente que no pinta nada, y si faltara
# uno, sería un campo que el metamodelo deja crear y ningún front sabe mostrar.
# Hay un gate que compara las dos listas.
POR_TIPO = {
    "texto": "texto",
    "texto_largo": "texto_largo",
    "numero": "numero",
    "moneda": "moneda",
    "porcentaje": "porcentaje",
    "fecha": "fecha",
    "fecha_hora": "fecha_hora",
    "booleano": "booleano",
    "lista": "seleccion",
    "lista_multiple": "seleccion_multiple",
    "formula": "calculado",
    "lookup": "referencia",
    "geolocalizacion": "mapa",
    "json": "json",
    "fichero": "adjunto",
    "cifrado": "secreto",
    "email": "correo",
    "telefono": "telefono",
    "url": "enlace",
}


def componente_de(tipo_campo: str) -> str:
    """Qué componente pinta un tipo del metamodelo.

    Un tipo desconocido **no cae a «texto»**. Caer a texto deja que alguien
    escriba «mañana» en un campo de fecha y que el CRM lo guarde: el error se
    descubre meses después, cuando alguien intenta ordenar por esa columna.
    """
    componente = POR_TIPO.get(tipo_campo)
    if componente is None:
        raise ErrorValidacion(
            f"El tipo de campo «{tipo_campo}» no tiene componente asignado. Caer a "
            "una caja de texto dejaría escribir «mañana» en un campo de fecha, y eso "
            "se descubre meses después al intentar ordenar por esa columna.",
            error_code="vistas.tipo_sin_componente",
            detalle={"tipos_conocidos": sorted(POR_TIPO)},
        )
    return componente


def servir_formulario(
    *,
    objeto: str,
    campos: list[dict[str, Any]],
    permisos_del_usuario: frozenset[str] | set[str],
    secciones: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compone la definición de un formulario para que la pinte cualquier front.

    **Los permisos se resuelven aquí.** Mandar el formulario completo y que el
    front esconda lo que no toca deja el dato viajando hasta el navegador: basta
    con abrir las herramientas de desarrollo para verlo. Lo que no se puede ver
    no se manda, y se dice cuántos campos se han quitado — sin eso, el usuario
    cree que su ficha tiene doce campos cuando tiene veinte.
    """
    from crmcore.authz.matriz import _cubre

    visibles: list[dict[str, Any]] = []
    ocultos = 0
    for campo in campos:
        exigido = str(campo.get("permiso") or "")
        if exigido and not any(_cubre(p, exigido) for p in permisos_del_usuario):
            ocultos += 1
            continue
        visibles.append(
            {
                "clave": campo.get("clave"),
                "etiqueta": campo.get("etiqueta") or campo.get("clave"),
                "componente": componente_de(str(campo.get("tipo") or "texto")),
                "obligatorio": bool(campo.get("obligatorio")),
                "solo_lectura": bool(campo.get("solo_lectura")),
                "ayuda": campo.get("ayuda") or "",
                # La validación viaja para que el usuario no descubra el error
                # después de rellenar veinte campos. NO sustituye a la del
                # servidor: lo que llega por la API no pasa por ningún formulario.
                "validacion": campo.get("validacion") or {},
                "opciones": campo.get("opciones") or [],
            }
        )

    return {
        "objeto": objeto,
        "version_contrato": VERSION_CONTRATO,
        "secciones": secciones or [{"clave": "general", "etiqueta": "General"}],
        "campos": visibles,
        # Se dice cuántos faltan: si no, el usuario cree que su ficha tiene doce
        # campos cuando tiene veinte y no entiende por qué el informe no cuadra.
        "campos_ocultos_por_permisos": ocultos,
        "la_validacion_se_repite_en_el_servidor": True,
        "porque": (
            "La validación del formulario es para no hacer perder el tiempo a quien "
            "lo rellena. La que protege el dato es la del servidor, porque lo que "
            "llega por la API no pasa por ningún formulario."
        ),
    }


def comprobar_compatibilidad(
    *, version_del_front: int, definicion: dict[str, Any]
) -> dict[str, Any]:
    """Si el front que va a pintar esto sabe hacerlo.

    Un front viejo recibiendo una vista nueva tiene que poder decir «no sé pintar
    esto» **antes** de intentarlo. Pintarlo mal es peor que no pintarlo: un
    selector que se dibuja como caja de texto guarda lo que el usuario escriba.
    """
    usados = {
        str(c.get("componente") or "")
        for c in (definicion.get("campos") or [])
        if c.get("componente")
    }
    desconocidos = sorted(usados - set(COMPONENTES))
    version_vista = int(definicion.get("version_contrato") or 1)

    return {
        "compatible": version_del_front >= version_vista and not desconocidos,
        "version_del_front": version_del_front,
        "version_de_la_vista": version_vista,
        "componentes_desconocidos": desconocidos,
        "que_hacer": (
            ""
            if version_del_front >= version_vista and not desconocidos
            else "El front no sabe pintar esta vista entera. Tiene que decirlo y no "
            "intentarlo: un componente que se dibuja como caja de texto guarda lo "
            "que el usuario escriba, y eso llega a la base."
        ),
    }


def validar_diseno(
    *, campos: list[dict[str, Any]], secciones: list[dict[str, Any]]
) -> dict[str, Any]:
    """Comprueba un formulario diseñado a mano antes de publicarlo
    (CRM-00.04.03.01).

    Las tres cosas que se rompen siempre al arrastrar campos en un diseñador, y
    ninguna da error al guardar:

    **Un campo obligatorio escondido en una pestaña** hace que el formulario no
    se pueda guardar y el usuario no vea por qué: el error sale abajo y el campo
    está en otra pantalla.

    **Un campo en una sección que no existe** desaparece sin más. Nadie lo echa
    de menos hasta que alguien pregunta dónde se mete un dato.

    **Y un formulario sin ningún campo obligatorio** produce fichas vacías que
    entran en el CRM y no sirven para nada — es la forma más silenciosa de
    llenar una base de registros basura.
    """
    claves_seccion = {str(s.get("clave")) for s in secciones}
    problemas: list[dict[str, str]] = []

    for campo in campos:
        seccion = str(campo.get("seccion") or "general")
        if seccion not in claves_seccion and seccion != "general":
            problemas.append(
                {
                    "campo": str(campo.get("clave")),
                    "problema": f"está en la sección «{seccion}», que no existe",
                    "consecuencia": "no se pintaría, y nadie lo echaría de menos",
                }
            )
        if campo.get("obligatorio") and campo.get("en_pestana_secundaria"):
            problemas.append(
                {
                    "campo": str(campo.get("clave")),
                    "problema": "es obligatorio y está en una pestaña secundaria",
                    "consecuencia": (
                        "el formulario no se puede guardar y el usuario no ve por qué: "
                        "el error sale abajo y el campo está en otra pantalla"
                    ),
                }
            )

    sin_obligatorios = not any(c.get("obligatorio") for c in campos)
    return {
        "valido": not problemas and not sin_obligatorios,
        "problemas": problemas,
        "sin_campos_obligatorios": sin_obligatorios,
        "aviso": (
            ""
            if not sin_obligatorios
            else "Ningún campo es obligatorio: se podrán crear fichas vacías, que es "
            "la forma más silenciosa de llenar el CRM de registros que no sirven."
        ),
    }
