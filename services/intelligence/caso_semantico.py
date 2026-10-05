"""Búsqueda semántica y sugerencia en el caso (CRM-04.03.01.04).

Un agente con un caso abierto no quiere buscar: quiere que le pongan delante los
tres casos parecidos que ya se resolvieron y el artículo que los explica. Eso es lo
que ahorra la llamada al compañero veterano, que es el cuello de botella real de
cualquier servicio.

La búsqueda por palabras no sirve aquí porque el cliente escribe «no me va el
correo» y el artículo dice «configuración IMAP». La semántica sí, y trae sus
propios problemas:

**Un resultado sin cita no vale.** Si no se puede abrir la fuente, el agente tiene
que creerse un párrafo generado y responder con él — y cuando esté mal, y alguno
estará mal, no habrá forma de saber si falló el dato o el modelo.

**Lo parecido no es lo aplicable.** Dos casos pueden hablar de lo mismo y ser de
productos distintos, de versiones distintas o de contratos distintos. Se enseña qué
tienen en común y qué no, y eso lo decide el agente.

**Los permisos se aplican antes de buscar, no después.** Filtrar los resultados
después ya ha metido en el índice el contenido de casos que ese agente no puede
ver, y basta con que un fragmento aparezca en el resumen.

**Y no se sugiere lo que no se ha resuelto.** Un caso parecido que sigue abierto no
es una solución: es otro que tiene el mismo problema.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.errors import ErrorValidacion
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Qué se puede sugerir en un caso. Cerrada: cada cosa se presenta distinto y se
# mide distinto, y «lo que sea parecido» acaba enseñando el caso de otro cliente.
FUENTES = ("caso_resuelto", "articulo", "documento", "conversacion")

# Parecido mínimo para enseñar algo. Por debajo, lo que se sugiere es ruido con
# aspecto de ayuda — y el agente deja de mirar el panel después de dos veces.
PARECIDO_MINIMO = 0.7

# Cuántas sugerencias como mucho. Cinco caben en la pantalla al lado del caso;
# veinte son otra búsqueda que hacer.
TOPE = 5


def buscar(
    *,
    resultados: list[dict[str, Any]],
    contexto_del_caso: dict[str, Any],
    permisos_del_agente: set[str] | frozenset[str],
    tope: int = TOPE,
) -> dict[str, Any]:
    """Filtra y ordena lo que se le pone delante al agente.

    Los resultados llegan ya buscados —quien habla con el índice es el puerto de
    inteligencia—, y aquí se decide **qué se enseña y con qué advertencia**, que
    es donde están los errores que importan.
    """
    admitidos: list[dict[str, Any]] = []
    descartados: list[dict[str, str]] = []

    for resultado in resultados:
        fuente = str(resultado.get("fuente") or "")
        if fuente not in FUENTES:
            descartados.append(
                {"ref": str(resultado.get("referencia")), "porque": "fuente desconocida"}
            )
            continue
        permiso = resultado.get("permiso")
        if permiso and permiso not in permisos_del_agente:
            # Se descarta sin decir de qué iba: decir «hay un caso parecido que no
            # puedes ver» ya filtra información sobre otro cliente.
            descartados.append({"ref": "(oculto)", "porque": "sin permiso"})
            continue
        if float(resultado.get("parecido") or 0) < PARECIDO_MINIMO:
            descartados.append({"ref": str(resultado.get("referencia")), "porque": "poco parecido"})
            continue
        if fuente == "caso_resuelto" and not resultado.get("resuelto"):
            descartados.append(
                {
                    "ref": str(resultado.get("referencia")),
                    "porque": (
                        "el caso parecido sigue abierto: no es una solución, es otro que "
                        "tiene el mismo problema"
                    ),
                }
            )
            continue
        if not resultado.get("cita"):
            descartados.append(
                {
                    "ref": str(resultado.get("referencia")),
                    "porque": (
                        "sin cita comprobable; el agente tendría que creerse un párrafo "
                        "generado y responder con él"
                    ),
                }
            )
            continue

        admitidos.append(
            {
                "fuente": fuente,
                "referencia": resultado.get("referencia"),
                "titulo": resultado.get("titulo"),
                "parecido": round(float(resultado.get("parecido")), 2),
                "cita": resultado.get("cita"),
                **_en_que_se_parece(resultado, contexto_del_caso),
            }
        )

    admitidos.sort(key=lambda r: -r["parecido"])
    return {
        "sugerencias": admitidos[:tope],
        # Contra qué se comparó, literal. Es lo único que deja comprobar desde
        # fuera que salió el recorte y no la ficha entera: las dos respuestas se
        # parecen mucho y sólo una manda el nombre del cliente a un tercero.
        "contexto_usado": dict(contexto_del_caso),
        "descartadas": len(descartados),
        "motivos_de_descarte": descartados[:10],
        "hay": bool(admitidos),
        "porque": (
            "No hay nada lo bastante parecido. Enseñar resultados flojos es peor que no "
            "enseñar nada: después de dos veces, el agente deja de mirar el panel."
            if not admitidos
            else "Ordenadas por parecido, todas con su cita para poder abrirlas."
        ),
    }


def _en_que_se_parece(resultado: dict[str, Any], contexto: dict[str, Any]) -> dict[str, Any]:
    """Qué comparten y qué no. Lo parecido no siempre es lo aplicable.

    Dos casos pueden hablar de lo mismo y ser de productos distintos, de versiones
    distintas o de contratos distintos. La decisión es del agente, y para tomarla
    necesita ver la diferencia, no solo el porcentaje.
    """
    iguales: list[str] = []
    distintos: list[dict[str, Any]] = []
    for clave in ("producto", "version", "tipo_contrato", "canal"):
        aqui = contexto.get(clave)
        alli = resultado.get(clave)
        if aqui is None or alli is None:
            continue
        if str(aqui) == str(alli):
            iguales.append(clave)
        else:
            distintos.append({"campo": clave, "en_este_caso": aqui, "en_el_sugerido": alli})
    return {
        "coincide_en": iguales,
        "difiere_en": distintos,
        "ojo": (
            ""
            if not distintos
            else "Se parece, pero no es lo mismo: "
            + ", ".join(f"{d['campo']} distinto" for d in distintos)
            + ". Lo parecido no siempre es lo aplicable."
        ),
    }


def aprender_de_lo_usado(*, sugerencias: list[dict[str, Any]]) -> dict[str, Any]:
    """Si esto le sirve al agente o solo ocupa sitio en la pantalla.

    Se mide por **lo que usa**, no por lo que abre. Y si no usa casi nada, el
    problema no es del agente: o el índice está vacío de lo que hace falta, o el
    umbral de parecido está dejando pasar ruido.
    """
    if not sugerencias:
        return {
            "medible": False,
            "porque": (
                "No se ha sugerido nada todavía. Eso no es que funcione mal: es que no "
                "hay datos para decir nada."
            ),
        }
    usadas = [s for s in sugerencias if s.get("usada")]
    abiertas = [s for s in sugerencias if s.get("abierta")]
    pct = round(len(usadas) / len(sugerencias) * 100, 1)
    return {
        "medible": True,
        "sugerencias": len(sugerencias),
        "abiertas": len(abiertas),
        "usadas": len(usadas),
        "pct_usadas": pct,
        "sirve": pct >= 15,
        "que_significa": (
            f"Solo se usa el {pct} % de lo que se sugiere. El problema no es del agente: "
            "o el índice no tiene lo que hace falta, o el umbral de parecido está "
            "dejando pasar ruido."
            if pct < 15
            else f"Se usa el {pct} % de lo sugerido."
        ),
    }


def exigir_permiso_de_indexacion(*, objeto: str, permiso: str | None) -> None:
    """Nada entra en el índice sin saber quién puede verlo.

    Indexar primero y filtrar después ya ha metido el contenido en un sitio del
    que sale por otros caminos: basta con que un fragmento aparezca en un resumen
    para que un agente lea el caso de un cliente que no le toca.
    """
    if not permiso:
        raise ErrorValidacion(
            f"«{objeto}» no declara qué permiso hace falta para verlo, así que no se "
            "indexa. Filtrar después de buscar ya es tarde: el fragmento aparece en el "
            "resumen aunque el resultado se descarte.",
            error_code="semantica.sin_permiso_declarado",
        )


def contexto_para_el_modelo(
    *, caso: dict[str, Any], incluir_datos_personales: bool = False
) -> dict[str, Any]:
    """Qué del caso se le manda al modelo.

    Por defecto, **sin datos personales**: para encontrar casos parecidos hace
    falta el problema, no el nombre de quien lo tiene. Mandar la ficha entera
    manda datos personales a un proveedor de inferencia sin ninguna ganancia.
    """
    salida = {
        "asunto": caso.get("asunto"),
        "descripcion": caso.get("descripcion"),
        "producto": caso.get("producto"),
        "version": caso.get("version"),
        "categoria": caso.get("categoria"),
        # Los dos que faltaban. `_en_que_se_parece` compara producto, versión,
        # tipo de contrato y canal: recortarlos dejaba dos de los cuatro avisos
        # de «se parece, pero no es lo mismo» sin poder salir, y ninguno de los
        # dos es un dato personal.
        "tipo_contrato": caso.get("tipo_contrato"),
        "canal": caso.get("canal"),
    }
    if incluir_datos_personales:
        salida["contacto"] = caso.get("contacto")
    return {
        "contexto": {k: v for k, v in salida.items() if v is not None},
        "lleva_datos_personales": incluir_datos_personales,
        "porque": (
            "Para encontrar casos parecidos hace falta el problema, no el nombre de "
            "quien lo tiene. Mandar la ficha entera manda datos personales a un "
            "proveedor de inferencia sin ninguna ganancia."
        ),
    }


def sugerir_para(*, caso_id: UUID, sugerencias: list[dict[str, Any]]) -> dict[str, Any]:
    """Empaqueta lo que se enseña al lado del caso."""
    return {
        "caso_id": str(caso_id),
        "sugerencias": sugerencias[:TOPE],
        "como_leerlo": (
            "Cada una con su cita: si no se puede abrir la fuente, no se responde con " "ella."
        ),
    }
