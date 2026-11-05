"""Una clave técnica que se enseña, se enseña en castellano.

El front pinta claves de la API —``forma_juridica_distinta``,
``fecha_revision``, ``importe_linea``— delante de las personas: como rótulo de
un campo, como etiqueta de un valor y como nombre de columna. Lo hace
``humanizar`` (``frontend/src/lib/formato.ts``), que parte por los guiones
bajos, capitaliza y consulta un diccionario de palabras con tilde.

**Medido el 03-11-2026.** Se vio «Forma juridica distinta» en la cola de
duplicados. En vez de añadir esa palabra y seguir, se midió la familia entera:
las **1.586 claves que el producto puede enseñar** —propiedades y valores de
enum de los catorce contratos— cruzadas con **cómo escribe el producto cada
palabra en sus propios textos**, que es la única autoridad que no hay que
inventar: si ``es.ts`` dice «dirección», un rótulo que ponga «Direccion» está
mal. Salieron 62, de las que 56 eran inequívocas.

La prueba vive en Python y no en el front porque aquí se pueden construir los
catorce contratos —el front sólo ve las claves que él mismo nombra, que son
177 de 1.586—. Lo que comprueba es estático: que toda palabra que deba llevar
tilde esté en el diccionario de ``formato.ts``.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from tests.unit._contratos import SERVICIOS, contrato

RAIZ = Path(__file__).resolve().parents[2]
FRONT = RAIZ / "frontend" / "src"

# Las que se quedan fuera, con su motivo. Es una lista de EXCEPCIONES y no de
# aceptadas: así, una palabra nueva entra vigilada y no al revés.
AMBIGUAS = {
    "cambio": "`fecha_cierre_en_cambio` es el sustantivo, no «cambió»",
    "como": "`actua_como_id` es «actúa como»",
    "este": "`solo_este_tenant` es el demostrativo",
    "paso": "un paso de un proceso, no «pasó»",
    "intento": "el sustantivo",
    "solo": "la RAE le quitó la tilde en 2010",
    "cual": "como etiqueta sería interrogativo, como valor no",
    "cuando": "lo mismo",
    "cuantos": "lo mismo",
    "quien": "lo mismo",
    "publico": "«publico» es también el verbo",
    "critico": "«critico» es también el verbo",
    "calculo": "«calculo» es también el verbo",
    "numero": "«numero» es también el verbo",
    "termino": "«termino» es también el verbo",
    "continua": "«continua» y «continúa» son las dos palabras",
    "valido": "«valido» es también el verbo",
    "valida": "«valida» es también el verbo",
    # `su_media` es el promedio de ese tenant, no el imperfecto de «medir».
    # Son dos palabras distintas, no la misma mal escrita.
    "media": "«media» es el promedio; «medía» es del verbo medir",
    "ingles": "el idioma lleva tilde, el gentilicio en minúscula también",
    # Salieron al ampliar la autoridad a los manuales: ahí aparecen como verbo
    # y en una clave técnica son sustantivo o preposición.
    "caso": "`cuenta_como_caso` es el sustantivo, no «casó»",
    "hacia": "`migracion_compatible_hacia_atras` es la preposición",
    "marco": "el sustantivo, no «marcó»",
    "mudo": "el adjetivo, no «mudó»",
    "proceso": "`version_proceso` es el sustantivo, no «procesó»",
    "confirmo": "`confirmo_que_es_irreversible` es primera persona",
    "perdida": "`oportunidad_perdida` es participio y `nota_perdida` es «pérdida»: sin saber cuál, se deja",
    # Salieron al mirar también las cadenas que escriben los servicios.
    "corto": "el adjetivo, no «cortó»",
    "cobro": "el sustantivo, no «cobró»",
    "dejo": "primera persona, no «dejó»",
    "esta": "el demostrativo",
    "estas": "el demostrativo",
    "estos": "el demostrativo; la RAE les quitó la tilde",
    "donde": "sólo lleva tilde cuando es interrogativo",
    "entero": "el adjetivo, no «enteró»",
    "fallo": "el sustantivo, no «falló»",
    "mando": "el sustantivo, no «mandó»",
    "publica": "también es el verbo",
    "salto": "el sustantivo, no «saltó»",
}


def _desnuda(palabra: str) -> str:
    """La misma palabra sin sus tildes, para poder compararlas."""
    return "".join(
        c for c in unicodedata.normalize("NFD", palabra) if unicodedata.category(c) != "Mn"
    )


# Lo que el producto escribe en castellano, y que por tanto manda sobre cómo se
# escribe cada palabra. Los **manuales entran a propósito**: con sólo los
# ficheros de la interfaz, el gate no cazaba «jurídica» —la palabra que
# destapó todo esto—, porque la interfaz no la usa en ninguna frase. Medido:
# los textos de pantalla dan 312 palabras con tilde y los dos manuales 1.108.
AUTORIDADES = (
    FRONT / "i18n" / "es.ts",
    FRONT / "i18n" / "es.pantallas.ts",
    RAIZ / "docs" / "manual-usuario.md",
    RAIZ / "docs" / "manual-tecnico.md",
)


def _como_las_escribe_el_producto() -> dict[str, str]:
    """Cómo escribe el producto cada palabra, según sus propios textos.

    Es la autoridad, y no hace falta inventar un diccionario de castellano: si
    el producto escribe «dirección», entonces «Direccion» en un rótulo está
    mal.
    """
    texto = ""
    for ruta in AUTORIDADES:
        texto += ruta.read_text(encoding="utf-8")
    mapa: dict[str, str] = {}
    for trozo in re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{4,}", texto):
        palabra = trozo.lower()
        sin = _desnuda(palabra)
        if sin != palabra:
            mapa[sin] = palabra
    return mapa


def _diccionario_del_front() -> dict[str, str]:
    """El `CON_TILDE` de `formato.ts`, leído tal cual."""
    fuente = (FRONT / "lib" / "formato.ts").read_text(encoding="utf-8")
    bloque = re.search(r"const CON_TILDE[^{]*\{(.*?)\n\};", fuente, re.S)
    assert bloque, "no se encuentra `CON_TILDE` en formato.ts"
    return dict(re.findall(r'^\s+([a-z]+): "([^"]+)",', bloque.group(1), re.M))


def _claves_que_se_ensenan() -> set[str]:
    """Propiedades y valores de enum de los catorce contratos."""
    claves: set[str] = set()

    def recorre(nodo: object) -> None:
        if isinstance(nodo, dict):
            for clave, valor in nodo.items():
                if clave == "properties" and isinstance(valor, dict):
                    claves.update(valor)
                if clave == "enum" and isinstance(valor, list):
                    claves.update(v for v in valor if isinstance(v, str))
                recorre(valor)
        elif isinstance(nodo, list):
            for x in nodo:
                recorre(x)

    for servicio in SERVICIOS:
        recorre(contrato(servicio).get("components", {}))

    # Y las cadenas con guion bajo que los servicios escriben a mano, que
    # también acaban humanizadas en una pantalla. `forma_juridica_distinta`
    # —la que destapó todo esto— es una de ésas: no es una propiedad ni un
    # enum, la añade `services/party/duplicados.py` a una lista de señales.
    # Sin esta fuente, el gate no cazaba la palabra que lo originó: comprobado
    # plantándola.
    for fichero in (RAIZ / "services").rglob("*.py"):
        if "test" in fichero.name:
            continue
        for literal in re.findall(
            r"""["']([a-z]+(?:_[a-z]+)+)["']""", fichero.read_text(encoding="utf-8")
        ):
            # Los nombres de índice, restricción y clave ajena NO se enseñan:
            # son del esquema de la base y por convención llevan su prefijo.
            # Meterlos obligaría a tener en el diccionario palabras que nadie
            # va a leer nunca.
            if literal.split("_")[0] in {"ix", "uq", "fk", "pk", "ck", "idx"}:
                continue
            claves.add(literal)
    return claves


def test_ninguna_clave_que_se_ensena_sale_mal_escrita() -> None:
    como_se_escriben = _como_las_escribe_el_producto()
    # Sin esto, «ninguna mal escrita» sería el resultado de no haber mirado.
    assert len(como_se_escriben) > 700, (
        f"solo se han leído {len(como_se_escriben)} palabras con tilde de los "
        "textos del producto: la comprobación no está mirando nada"
    )

    diccionario = _diccionario_del_front()
    claves = _claves_que_se_ensenan()
    assert len(claves) > 1000, (
        f"solo se han recogido {len(claves)} claves de los contratos: "
        "la comprobación no está mirando nada"
    )

    mal: dict[str, str] = {}
    for clave in claves:
        for palabra in re.split(r"[_\s]+", clave.lower()):
            if len(palabra) < 4 or palabra in AMBIGUAS or palabra in diccionario:
                continue
            buena = como_se_escriben.get(palabra)
            if buena and buena != palabra:
                mal[palabra] = f"{buena}  (p. ej. en «{clave}»)"

    assert not mal, (
        "claves que el producto enseña con una palabra que él mismo escribe de "
        "otra forma. O se añaden a `CON_TILDE` en `formato.ts`, o se declaran "
        "ambiguas aquí con su motivo:\n  "
        + "\n  ".join(f"{p} → {d}" for p, d in sorted(mal.items()))
    )
