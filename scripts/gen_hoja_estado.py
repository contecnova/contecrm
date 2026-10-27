#!/usr/bin/env python3
"""Genera la hoja web de estado del proyecto desde el catálogo.

    python scripts/gen_hoja_estado.py            # escribe docs/hoja-estado.html
    python scripts/gen_hoja_estado.py --check    # falla si está desfasada

**Generada, no mantenida a mano.** El catálogo (`docs/catalogo/catalogo.yaml`)
es la fuente de verdad del alcance y del estado, y un gate impide declarar
«hecho» lo que no está citado en el código y documentado en el manual. Si esta
hoja se editara a mano, al segundo día diría lo que alguien creyó que había
hecho — que es exactamente lo que el catálogo existe para evitar.

Lo que falta de cada capacidad «en curso» se lee de la tabla «Lo que está a
medias» del manual funcional, para no tener ese texto escrito en dos sitios.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
CATALOGO = RAIZ / "docs" / "catalogo" / "catalogo.yaml"
MANUAL = RAIZ / "docs" / "manual-3-funcionalidades.md"
SALIDA = RAIZ / "docs" / "hoja-estado.html"

# Las notas salen de las tablas del manual, y **se leen por su cabecera**, no por
# la posición de las columnas. La versión anterior daba por hecho que toda tabla
# de capacidades tenía tres columnas —capacidad, qué hay, qué falta—; la del
# capítulo de huecos tiene dos, así que su «qué falta» acababa publicado en la
# web bajo la etiqueta «qué hay». Es decir: la hoja presentaba como construido
# exactamente lo que no lo estaba, que es la peor forma posible de equivocarse
# en este documento.
RE_FILA = re.compile(r"^\|\s*`?(CRM-[\d.]+)`?\s*([^|]*)\|(.+)$", re.M)


def _tablas(texto: str) -> list[tuple[list[str], list[str]]]:
    """Cada tabla Markdown del manual como (cabeceras, filas)."""
    salida: list[tuple[list[str], list[str]]] = []
    cabeceras: list[str] = []
    filas: list[str] = []
    for linea in texto.split("\n"):
        if linea.startswith("|"):
            celdas = [c.strip() for c in linea.strip().strip("|").split("|")]
            if not cabeceras:
                cabeceras = celdas
            elif set("".join(celdas)) <= set("-: "):
                continue  # la línea separadora
            else:
                filas.append(linea)
        else:
            if cabeceras and filas:
                salida.append((cabeceras, filas))
            cabeceras, filas = [], []
    if cabeceras and filas:
        salida.append((cabeceras, filas))
    return salida


def _notas_a_medias() -> dict[str, dict[str, str]]:
    """Qué hay y qué falta de cada capacidad, según el manual.

    Se busca la columna por su título. Si una tabla no declara «qué hay», su
    texto es lo que FALTA y así se publica: adivinarlo por la posición fue
    exactamente el fallo que hizo que la web enseñara un hueco como si fuera
    algo construido.
    """
    if not MANUAL.exists():
        return {}

    notas: dict[str, dict[str, str]] = {}
    for cabeceras, filas in _tablas(MANUAL.read_text(encoding="utf-8")):
        titulos = [c.lower() for c in cabeceras]
        col_hay = next((i for i, t in enumerate(titulos) if "qué hay" in t or "que hay" in t), None)
        col_falta = next(
            (i for i, t in enumerate(titulos) if "falta" in t or "no está" in t or "no esta" in t),
            None,
        )
        if col_falta is None and col_hay is None:
            continue
        for linea in filas:
            celdas = [c.strip() for c in linea.strip().strip("|").split("|")]
            encontrado = re.search(r"CRM-[\d.]+", celdas[0] if celdas else "")
            if not encontrado:
                continue
            nota = {
                "hay": _limpiar(celdas[col_hay])
                if col_hay is not None and col_hay < len(celdas)
                else "",
                "falta": (
                    _limpiar(celdas[col_falta])
                    if col_falta is not None and col_falta < len(celdas)
                    else ""
                ),
            }
            if nota["hay"] or nota["falta"]:
                notas[encontrado.group(0)] = nota
    return notas


def _limpiar(texto: str) -> str:
    """Quita el énfasis de Markdown: aquí el resaltado lo pone el CSS."""
    return re.sub(r"\*\*(.+?)\*\*", r"\1", texto).strip()


def _datos() -> dict:
    import yaml

    catalogo = yaml.safe_load(CATALOGO.read_text(encoding="utf-8"))
    notas = _notas_a_medias()

    capacidades = []
    for modulo in catalogo["modulos"]:
        for seccion in modulo["secciones"]:
            for funcion in seccion["funciones"]:
                for cap in funcion["capacidades"]:
                    nota = notas.get(cap["id"], {})
                    capacidades.append(
                        {
                            "id": cap["id"],
                            "t": cap["t"],
                            "c": cap.get("c", "A"),
                            "fase": cap.get("fase", 0),
                            "svc": cap.get("svc", "core"),
                            "estado": cap.get("estado", "pendiente"),
                            "reutiliza": cap.get("reutiliza", ""),
                            "modulo": f"{modulo['id']} · {modulo['nombre']}",
                            "seccion": f"{seccion['id']} · {seccion['nombre']}",
                            "funcion": funcion["nombre"],
                            "hay": nota.get("hay", ""),
                            "falta": nota.get("falta", ""),
                            # VISTO FUNCIONAR, que no es lo mismo que «hecho».
                            #
                            # «Hecho» quiere decir declarado, con código, con
                            # prueba y con manual. El 28-09-2026 aparecieron
                            # seis cosas que constaban hechas y no funcionaban
                            # —una exportación que daba error del servidor, un
                            # token que caducaba a los quince minutos, cuatro
                            # migraciones que rompen al actualizar a un cliente
                            # con datos— y **ninguna habría movido ese número**.
                            #
                            # Se marca SOLO lo recorrido contra el sistema en
                            # marcha, y dice cómo se recorrió. Nunca por
                            # deducción: una marca puesta porque «obviamente
                            # funciona» devuelve el problema al sitio donde
                            # estaba. Y se marca cuando se ve, no auditando las
                            # 772 de golpe: una columna vacía al 99 % diría de
                            # menos igual que el total dice de más.
                            #
                            # El hueco entre «hecho» y «visto» es el mapa de lo
                            # que nadie ha comprobado nunca.
                            "visto": cap.get("visto", ""),
                            # Y por qué una capacidad no tiene pantalla, cuando
                            # su entregable no es una. Se publica a propósito:
                            # sacar algo del recuento es la salida barata, y lo
                            # que la encarece es que el motivo se lea.
                            "sin_pantalla_porque": cap.get("sin_pantalla_porque", ""),
                        }
                    )

    return {
        "generado": date.today().isoformat(),
        "version": str(catalogo.get("version", "")),
        "criticidades": catalogo.get("criticidades", {}),
        "estados": catalogo.get("estados", {}),
        "fases": {str(k): v for k, v in (catalogo.get("fases") or {}).items()},
        "capacidades": capacidades,
        "eventos": catalogo.get("anexo_b_eventos", []),
        "restricciones": catalogo.get("restricciones_transversales", []),
    }


def _sin_fecha(html: str) -> str:
    """El HTML menos la fecha de generación.

    La fecha cambia todos los días, así que compararla haría que el gate fallara
    cada mañana sin que nada del proyecto hubiera cambiado — y un gate que falla
    por sistema se acaba ignorando, que es peor que no tenerlo.
    """
    return re.sub(r'"generado":"\d{4}-\d{2}-\d{2}"', '"generado":""', html)


def main() -> int:
    datos = _datos()
    plantilla = (Path(__file__).parent / "plantilla_hoja_estado.html").read_text(encoding="utf-8")
    html = plantilla.replace(
        "/*__DATOS__*/null", json.dumps(datos, ensure_ascii=False, separators=(",", ":"))
    )

    if "--check" in sys.argv:
        actual = SALIDA.read_text(encoding="utf-8") if SALIDA.exists() else ""
        if _sin_fecha(actual) != _sin_fecha(html):
            print(
                f"«{SALIDA.relative_to(RAIZ)}» está desfasada respecto del catálogo "
                "o del manual.\nRegenérala:  python scripts/gen_hoja_estado.py",
                file=sys.stderr,
            )
            return 1
        print("hoja de estado al día")
        return 0

    SALIDA.write_text(html, encoding="utf-8")
    total = len(datos["capacidades"])
    hechas = sum(1 for c in datos["capacidades"] if c["estado"] == "hecho")
    print(f"Escrito {SALIDA.relative_to(RAIZ)} ({total} capacidades, {hechas} hechas)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
