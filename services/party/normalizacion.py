"""Normalización de datos de cuentas y contactos (CRM-01.01.04.04).

Portado del criterio de `contecweb/app/services/normalization/part_number.py`,
que resuelve el mismo problema en otro dominio y con una idea que vale igual
aquí: **normalizar en dos niveles, y no confundirlos**.

  * `normalizar_*` — limpieza segura. No quita información que distinga dos
    entidades reales: solo unifica mayúsculas, espacios y separadores.
  * `clave_canonica` — además retira formas jurídicas y palabras vacías. Esto
    **sí** puede juntar dos entidades que alguien considere distintas
    («Construcciones García S.L.» y «Construcciones García S.A.» son la misma
    clave y pueden ser dos sociedades del mismo grupo), así que se usa como
    **candidato** de deduplicación, nunca como prueba. Para fusionar hace falta
    una segunda señal: identificador fiscal, dominio de correo o un umbral de
    similitud alto.

Esa distinción es la que evita el peor error de un CRM: fusionar dos clientes
que no eran el mismo. Deshacerlo es caro y casi siempre incompleto.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

# Formas jurídicas que no distinguen dos entidades al buscar duplicados. La
# lista es de España y de los países donde opera la casa; añadir una es una
# decisión consciente, no algo que se deduzca sola.
FORMAS_JURIDICAS = frozenset(
    {
        "sl",
        "slu",
        "sll",
        "sa",
        "sau",
        "sad",
        "scp",
        "sc",
        "scoop",
        "sat",
        "sociedad limitada",
        "sociedad anonima",
        "sociedad civil",
        "cb",
        "ae",
        "aie",
        "ute",
        # Internacionales frecuentes en grupos multinacionales
        "ltd",
        "limited",
        "llc",
        "inc",
        "incorporated",
        "corp",
        "corporation",
        "gmbh",
        "ag",
        "bv",
        "nv",
        "sarl",
        "sas",
        "spa",
        "srl",
        "plc",
        "oy",
        "ab",
    }
)

# Palabras vacías que aparecen en razones sociales y no ayudan a distinguir.
VACIAS = frozenset({"de", "del", "la", "las", "el", "los", "y", "e", "and", "of", "the"})

_RE_NO_ALFANUM = re.compile(r"[^\w\s]", re.UNICODE)
_RE_ESPACIOS = re.compile(r"\s+")
_RE_SOLO_DIGITOS = re.compile(r"\D")

# Prefijos telefónicos por país, para pasar a E.164 un número escrito en local.
# Solo los de los países donde hay operación: inventar el resto daría números
# formalmente correctos y equivocados, que es peor que dejarlos sin normalizar.
PREFIJOS_PAIS = {
    "ES": "34",
    "PT": "351",
    "FR": "33",
    "IT": "39",
    "DE": "49",
    "GB": "44",
    "US": "1",
    "MX": "52",
    "AR": "54",
    "CL": "56",
    "CO": "57",
    "BR": "55",
}


def sin_acentos(texto: str) -> str:
    """Quita acentos conservando la ñ.

    La eñe se conserva a propósito: en castellano distingue palabras («año» y
    «ano»), y quitarla junta razones sociales que no son la misma.
    """
    texto = texto.replace("ñ", "\x00").replace("Ñ", "\x01")
    descompuesto = unicodedata.normalize("NFD", texto)
    limpio = "".join(c for c in descompuesto if unicodedata.category(c) != "Mn")
    return limpio.replace("\x00", "ñ").replace("\x01", "Ñ")


def normalizar_texto(texto: str | None) -> str:
    """Limpieza segura: sin acentos, minúsculas, un solo espacio."""
    if not texto:
        return ""
    return _RE_ESPACIOS.sub(" ", sin_acentos(texto).lower()).strip()


def normalizar_razon_social(nombre: str | None) -> str:
    """Nombre de empresa limpio, **conservando** la forma jurídica."""
    if not nombre:
        return ""
    limpio = _RE_NO_ALFANUM.sub(" ", sin_acentos(nombre))
    return _RE_ESPACIOS.sub(" ", limpio).strip()


def forma_juridica_de(nombre: str | None) -> str:
    """La forma jurídica que lleva el nombre, o vacío si no declara ninguna.

    Hace falta porque la clave canónica **la quita** —y tiene que quitarla, para
    que «García SL» y «García, S.L.» se reconozcan—, y eso deja indistinguibles
    dos sociedades distintas del mismo grupo: «García SL» y «García SA» salen
    con una clave idéntica y, por tanto, como duplicado concluyente.

    Fusionarlas es un error caro y difícil de deshacer: son dos entidades
    jurídicas, con dos NIF y dos contabilidades.
    """
    for palabra in normalizar_razon_social(nombre).lower().split():
        if palabra in FORMAS_JURIDICAS:
            return palabra
    # Las formas escritas con puntos —«S.L.»— quedan como letras sueltas tras
    # limpiar la puntuación: se vuelven a unir antes de buscarlas.
    for palabra in _unir_iniciales(normalizar_razon_social(nombre).lower().split()):
        if palabra in FORMAS_JURIDICAS:
            return palabra
    return ""


def _unir_iniciales(palabras: list[str]) -> list[str]:
    """Junta secuencias de letras sueltas en una sola palabra.

    Existe por un caso concreto que rompía la deduplicación: al quitar la
    puntuación, «S.L.» se convierte en dos palabras de una letra —`s` y `l`—,
    ninguna de las cuales está en la lista de formas jurídicas. Resultado:
    «Construcciones García, S.L.» daba la clave `construcciones garcia l s` y
    **no casaba** con «CONSTRUCCIONES GARCIA SL», que es exactamente el duplicado
    que había que detectar.

    El efecto secundario —una empresa llamada «A B C Consulting» pasa a
    «abc consulting»— es deseable para comparar: esas dos formas son la misma
    empresa escrita distinto.
    """
    salida: list[str] = []
    acumulado = ""
    for palabra in palabras:
        if len(palabra) == 1 and palabra.isalpha():
            acumulado += palabra
            continue
        if acumulado:
            salida.append(acumulado)
            acumulado = ""
        salida.append(palabra)
    if acumulado:
        salida.append(acumulado)
    return salida


def clave_canonica_empresa(nombre: str | None) -> str:
    """Clave de comparación: sin forma jurídica, sin palabras vacías, ordenada.

    Las palabras se **ordenan** porque «García e Hijos» y «Hijos de García» son
    la misma empresa escrita de dos formas, y es un caso real y frecuente en
    maestros de clientes cargados por distintas personas.
    """
    base = normalizar_texto(_RE_NO_ALFANUM.sub(" ", sin_acentos(nombre or "")))
    palabras = _unir_iniciales(base.split())
    palabras = [p for p in palabras if p and p not in FORMAS_JURIDICAS and p not in VACIAS]
    return " ".join(sorted(palabras))


def clave_canonica_persona(nombre: str | None, apellidos: str | None = None) -> str:
    """Clave de comparación de una persona, con las palabras ordenadas.

    Ordenadas por lo mismo: «Pérez García, Ana» y «Ana Pérez García» son la
    misma persona, y en un maestro cargado desde varias fuentes aparecen las dos.
    """
    base = normalizar_texto(f"{nombre or ''} {apellidos or ''}")
    palabras = [p for p in _RE_NO_ALFANUM.sub(" ", base).split() if p and p not in VACIAS]
    return " ".join(sorted(palabras))


def normalizar_email(email: str | None) -> str:
    """Minúsculas y sin espacios. **No** se quitan los `+etiqueta` ni los puntos.

    Es tentador normalizar `ana.perez+crm@gmail.com` a `anaperez@gmail.com`, y
    sería un error: esa equivalencia solo vale en algunos proveedores, y aplicarla
    en general junta dos buzones distintos de un dominio corporativo.
    """
    return (email or "").strip().lower()


def dominio_de(email_o_web: str | None) -> str:
    """Dominio de un correo o de una web, sin `www` ni protocolo.

    Es la segunda señal más fiable para detectar duplicados de empresa, después
    del identificador fiscal: dos fichas con correos del mismo dominio
    corporativo casi siempre son la misma organización.
    """
    if not email_o_web:
        return ""
    valor = email_o_web.strip().lower()
    if "@" in valor:
        valor = valor.rsplit("@", 1)[-1]
    valor = re.sub(r"^https?://", "", valor)
    valor = valor.split("/")[0].split("?")[0]
    valor = valor.removeprefix("www.")
    # Los dominios de correo genéricos NO identifican una empresa: dos clientes
    # distintos pueden tener los dos una dirección de gmail.
    return "" if valor in DOMINIOS_GENERICOS else valor


DOMINIOS_GENERICOS = frozenset(
    {
        "gmail.com",
        "hotmail.com",
        "outlook.com",
        "outlook.es",
        "yahoo.com",
        "yahoo.es",
        "icloud.com",
        "me.com",
        "live.com",
        "msn.com",
        "aol.com",
        "protonmail.com",
        "proton.me",
        "gmx.com",
        "terra.es",
        "telefonica.net",
    }
)


def normalizar_telefono(telefono: str | None, pais: str = "ES") -> str:
    """Pasa a E.164 (`+34600111222`) lo que se pueda, sin inventar.

    Si el número no tiene prefijo y el país no está en la tabla, se devuelve
    solo limpio de separadores: un prefijo inventado produce un teléfono
    formalmente válido que llama a otro sitio, y eso es peor que un número sin
    normalizar.
    """
    if not telefono:
        return ""
    crudo = telefono.strip()
    if crudo.startswith("+"):
        return "+" + _RE_SOLO_DIGITOS.sub("", crudo)
    if crudo.startswith("00"):
        return "+" + _RE_SOLO_DIGITOS.sub("", crudo)[2:]

    digitos = _RE_SOLO_DIGITOS.sub("", crudo)
    if not digitos:
        return ""
    prefijo = PREFIJOS_PAIS.get((pais or "").upper())
    if not prefijo:
        return digitos
    # Con prefijo nacional ya incluido (un 34 delante de nueve dígitos en
    # España), no se duplica.
    if digitos.startswith(prefijo) and len(digitos) > 9:
        return "+" + digitos
    return f"+{prefijo}{digitos}"


def normalizar_identificador_fiscal(valor: str | None) -> str:
    """Sin espacios, guiones ni puntos, en mayúsculas."""
    if not valor:
        return ""
    return re.sub(r"[\s.\-/]", "", valor).upper()


def validar_nif_es(valor: str) -> bool:
    """Valida la letra de un NIF/NIE español.

    Comprobación **de forma**, no de existencia: dice si el documento está bien
    construido, no si corresponde a alguien. Para lo segundo hace falta consultar
    el registro, y eso es otra cosa (`verificado` en el modelo).
    """
    v = normalizar_identificador_fiscal(valor)
    letras = "TRWAGMYFPDXBNJZSQVHLCKE"
    if re.fullmatch(r"\d{8}[A-Z]", v):  # NIF
        return v[8] == letras[int(v[:8]) % 23]
    if re.fullmatch(r"[XYZ]\d{7}[A-Z]", v):  # NIE
        numero = str("XYZ".index(v[0])) + v[1:8]
        return v[8] == letras[int(numero) % 23]
    if re.fullmatch(r"[A-HJNPQRSUVW]\d{7}[0-9A-J]", v):  # CIF
        pares = sum(int(v[i]) for i in (2, 4, 6))
        impares = 0
        for i in (1, 3, 5, 7):
            doble = int(v[i]) * 2
            impares += doble // 10 + doble % 10
        control = (10 - (pares + impares) % 10) % 10
        return v[8] in (str(control), "JABCDEFGHI"[control])
    return False


def similitud(a: str, b: str) -> float:
    """Parecido entre dos cadenas, de 0 a 1 (CRM-01.01.04.02: coincidencia difusa).

    Combina dos medidas porque cada una falla donde la otra acierta:

      * `SequenceMatcher` mide caracteres en orden — bien para erratas
        («Construcciones» / «Construciones»), mal para palabras cambiadas de
        sitio.
      * El solapamiento de palabras (Jaccard) mide justo lo contrario.

    Se toma la mayor de las dos: un duplicado real suele parecerse mucho según
    **alguna** de las dos, y exigir las dos a la vez pierde la mitad.
    """
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    caracteres = SequenceMatcher(None, a, b).ratio()
    pa, pb = set(a.split()), set(b.split())
    jaccard = len(pa & pb) / len(pa | pb) if (pa | pb) else 0.0
    return max(caracteres, jaccard)


# ── Calidad del dato (CRM-01.01.04.05) ────────────────────────────────────

# Campos que se puntúan y cuánto pesa cada uno. Los pesos están aquí y no
# repartidos por el código para que se puedan discutir de un vistazo: son una
# decisión de negocio («¿nos importa más el NIF o el sector?»), no técnica.
PESOS_CUENTA: dict[str, int] = {
    "nombre": 15,
    "identificador_fiscal": 20,
    "direccion": 15,
    "telefono": 10,
    "email": 10,
    "web": 5,
    "sector_codigo": 10,
    "owner_id": 10,
    "tamano": 5,
}
PESOS_CONTACTO: dict[str, int] = {
    "nombre": 15,
    "apellidos": 10,
    "email": 25,
    "telefono": 15,
    "cargo": 10,
    "cuenta": 15,
    "owner_id": 10,
}


def puntuar_calidad(presentes: dict[str, bool], pesos: dict[str, int]) -> tuple[int, list[str]]:
    """Puntuación 0-100 y lista de lo que falta.

    Devuelve las dos cosas porque un número solo no sirve para actuar: «45» no
    dice qué hacer, y «45, falta NIF y dirección» sí.
    """
    total = sum(pesos.values()) or 1
    logrado = sum(peso for campo, peso in pesos.items() if presentes.get(campo))
    faltan = sorted(campo for campo in pesos if not presentes.get(campo))
    return round(logrado * 100 / total), faltan
