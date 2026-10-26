"""`setup.sh` dejaba el producto sin interfaz y sin decirlo.

Medido el 26-10-2026 sobre un arranque real: en local se levantaban los catorce
servicios, se imprimía

    Gateway:    http://localhost:18080/api/v1/docs

y se acababa. Quien lo ejecutaba se quedaba con **una API en pie y ninguna
pantalla**, sin que nada se lo dijera — y esa línea, que lleva `/api/v1/docs`,
se lee como «aquí está el producto» cuando lo que enseña es el contrato.

La llamada que levanta la interfaz estaba escrita desde hacía tiempo, y sólo la
hacía el camino de Docker.

Esto se comprueba leyendo el guion y no ejecutándolo: arrancar la plataforma
entera dentro de una prueba tarda minutos y necesita puertos libres. Lo que se
vigila es que las dos piezas sigan unidas, que es lo que se separó.
"""

from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
SETUP = RAIZ / "setup.sh"


def _cuerpo(funcion: str) -> str:
    """El cuerpo de una función de shell, de su apertura a la llave de cierre
    en la primera columna."""
    texto = SETUP.read_text(encoding="utf-8")
    inicio = texto.index(f"{funcion}() {{")
    fin = texto.index("\n}\n", inicio)
    return texto[inicio:fin]


def test_el_guion_existe_y_tiene_los_dos_caminos() -> None:
    """El control del recorrido: si cambiaran de nombre, lo de abajo pasaría
    sin mirar nada."""
    texto = SETUP.read_text(encoding="utf-8")
    for funcion in ("arrancar_local", "arrancar_docker", "arrancar_front"):
        assert f"{funcion}() {{" in texto, f"ya no existe «{funcion}»"


def test_los_dos_caminos_levantan_la_interfaz() -> None:
    """**El fallo.** Sólo el de Docker la levantaba."""
    for camino in ("arrancar_local", "arrancar_docker"):
        assert "arrancar_front" in _cuerpo(camino), (
            f"«{camino}» no levanta la interfaz: deja el producto con la API en "
            "pie y ninguna pantalla, que es lo que ya pasó."
        )


def test_los_dos_caminos_dicen_dónde_está_la_interfaz() -> None:
    """Levantarla y no decir dónde está es la mitad del problema: quien arranca
    se queda mirando la URL de la documentación, que es lo único que se
    imprimía."""
    for camino in ("arrancar_local", "arrancar_docker"):
        cuerpo = _cuerpo(camino)
        assert re.search(
            r"(Interfaz|Front|Consola):", cuerpo
        ), f"«{camino}» no dice dónde está la interfaz"


def test_la_interfaz_no_se_da_por_arrancada_sin_comprobarlo() -> None:
    """Se imprimía «Front en :15173» en cuanto se lanzaba el proceso. Con un
    fallo de compilación o el puerto ocupado, el mensaje decía que estaba y no
    estaba — peor que no decir nada, porque manda a buscar el problema al sitio
    equivocado."""
    cuerpo = _cuerpo("arrancar_front")
    assert "lsof" in cuerpo and "while" in cuerpo, (
        "«arrancar_front» no espera a que la interfaz escuche antes de " "anunciarla"
    )


def test_el_puerto_que_se_anuncia_es_el_que_se_usa() -> None:
    """Vite, por defecto, **se cambia de puerto en silencio** si el suyo está
    ocupado: lo dice en una línea de su registro y sigue. El arranque imprime
    el del `.env`, así que lo anunciado y lo que escucha dejan de coincidir.

    Medido con dos instancias a la vez: la segunda se fue al 15174 y el
    arranque seguía diciendo 15173.
    """
    vite = (RAIZ / "frontend/vite.config.ts").read_text(encoding="utf-8")
    assert "strictPort: true" in vite, (
        "Vite puede cambiarse de puerto sin avisar, y entonces la URL que "
        "imprime el arranque no es la que funciona."
    )
