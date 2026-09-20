"""Validación de identificadores fiscales por país (CRM-01.01.01.06).

Antes solo se validaba el español. Un CRM que opera en tres países y solo sabe
comprobar el NIF de uno da una falsa sensación de calidad: el maestro parece
limpio porque el 60 % de las fichas ni se comprueban.

**Dos comprobaciones distintas, y conviene no confundirlas:**

  * **De forma**, aquí: ¿está bien construido este identificador? Es un cálculo,
    no una consulta. No necesita red, es instantáneo y siempre da la misma
    respuesta. Caza el 90 % de los errores reales, que son erratas de tecleo.
  * **De existencia**, en `crmcore.datos.verificacion`: ¿existe esta empresa con
    este identificador? Eso solo lo sabe el registro oficial, hay que preguntarle
    y puede no contestar.

Confundirlas es lo que lleva a bloquear una factura porque el servicio del
ministerio estaba caído, o a dar por bueno un NIF inventado porque «el formato
es correcto».

**Por qué las fórmulas están aquí y no en un servicio externo:** son algoritmos
públicos y estables desde hace décadas, de veinte líneas cada uno. Pedirlas por
red añadiría una dependencia, una latencia y un modo de fallo a un cálculo que
no los tiene.
"""

from __future__ import annotations

import re

from crmcore.logging import get_logger

logger = get_logger(__name__)

# Países con validación de forma propia. El resto cae a la comprobación de
# formato del IVA europeo, o a «no sabemos», que es una respuesta honesta.
PAISES_CON_ALGORITMO = ("ES", "PT", "FR", "IT", "NL", "BE", "DE", "IE", "LU", "DK")

# Longitud y forma del número de IVA de cada país de la UE. Sirve para lo
# mínimo: rechazar lo que ni siquiera tiene la forma. Es la fuente oficial de la
# Comisión y cambia muy de tarde en tarde.
FORMATO_VAT_UE = {
    "AT": r"U\d{8}",
    "BE": r"[01]\d{9}",
    "BG": r"\d{9,10}",
    "CY": r"\d{8}[A-Z]",
    "CZ": r"\d{8,10}",
    "DE": r"\d{9}",
    "DK": r"\d{8}",
    "EE": r"\d{9}",
    "EL": r"\d{9}",
    "ES": r"[A-Z0-9]\d{7}[A-Z0-9]",
    "FI": r"\d{8}",
    "FR": r"[A-Z0-9]{2}\d{9}",
    "HR": r"\d{11}",
    "HU": r"\d{8}",
    "IE": r"\d[A-Z0-9+*]\d{5}[A-Z]{1,2}",
    "IT": r"\d{11}",
    "LT": r"(\d{9}|\d{12})",
    "LU": r"\d{8}",
    "LV": r"\d{11}",
    "MT": r"\d{8}",
    "NL": r"\d{9}B\d{2}",
    "PL": r"\d{10}",
    "PT": r"\d{9}",
    "RO": r"\d{2,10}",
    "SE": r"\d{12}",
    "SI": r"\d{8}",
    "SK": r"\d{10}",
}


def normalizar(valor: str) -> str:
    """Sin espacios, puntos ni guiones, y en mayúsculas."""
    return re.sub(r"[\s.\-/]", "", valor or "").upper()


def validar(valor: str, pais: str, tipo: str = "") -> tuple[bool | None, str]:
    """¿Está bien construido? Devuelve `(veredicto, motivo)`.

    El veredicto es `None` —y no `False`— cuando **no sabemos comprobarlo**. Esa
    diferencia es la que importa: decir «inválido» de un identificador de un país
    para el que no hay algoritmo bloquearía altas legítimas, y el cliente no
    tendría forma de continuar.
    """
    limpio = normalizar(valor)
    codigo = (pais or "").upper()
    if not limpio:
        return False, "vacío"

    # El número de IVA intracomunitario suele venir con el país delante
    # («ESB12345674», «BE0776091951») y también sin él. Se prueban **las dos
    # formas** y gana la que valide.
    #
    # La primera versión solo quitaba el prefijo cuando NO coincidía con el país
    # declarado, y el caso normal es justo el contrario: un identificador
    # español se escribe «ES…» y se guarda con país «ES». Resultado: los
    # identificadores bien escritos en formato intracomunitario salían
    # inválidos, que es el peor error posible en una validación — rechaza lo
    # bueno y quien lo sufre no tiene forma de continuar.
    candidatos = [(codigo, limpio)]
    if len(limpio) > 2 and limpio[:2] in FORMATO_VAT_UE and limpio[2:]:
        candidatos.append((limpio[:2], limpio[2:]))
    if tipo == "vat" or (codigo and limpio[:2] == codigo):
        candidatos.reverse()

    indecisos: list[tuple[bool | None, str]] = []
    for pais_candidato, numero in candidatos:
        veredicto = _validar_uno(pais_candidato, numero)
        if veredicto[0] is True:
            return veredicto
        indecisos.append(veredicto)

    # Ninguno validó. Se devuelve el menos categórico: un «no sabemos» vale más
    # que un «inválido» cuando una de las dos lecturas no se puede comprobar.
    for veredicto in indecisos:
        if veredicto[0] is None:
            return veredicto
    return indecisos[0]


def _validar_uno(codigo: str, limpio: str) -> tuple[bool | None, str]:
    algoritmo = _ALGORITMOS.get(codigo)
    if algoritmo is not None:
        ok = algoritmo(limpio)
        return ok, "dígito de control correcto" if ok else "dígito de control incorrecto"

    patron = FORMATO_VAT_UE.get(codigo)
    if patron is not None:
        if re.fullmatch(patron, limpio):
            # Formato correcto pero sin dígito de control comprobable: es todo lo
            # que se puede afirmar, y afirmar más sería mentir.
            return None, f"el formato encaja con el de {codigo}, sin dígito de control comprobable"
        return False, f"no tiene la forma de un identificador de {codigo}"

    return None, f"no sabemos validar identificadores de «{codigo or '?'}»"


# ── Algoritmos por país ───────────────────────────────────────────────────


def _es(v: str) -> bool:
    """NIF, NIE y CIF españoles. La implementación de referencia ya existía."""
    from services.party.normalizacion import validar_nif_es

    return validar_nif_es(v)


def _pt(v: str) -> bool:
    """NIF portugués: nueve dígitos, control módulo 11."""
    if not re.fullmatch(r"\d{9}", v):
        return False
    suma = sum(int(v[i]) * (9 - i) for i in range(8))
    control = 11 - (suma % 11)
    if control >= 10:
        control = 0
    return control == int(v[8])


def _fr(v: str) -> bool:
    """TVA francés: dos caracteres de control y el SIREN de nueve dígitos.

    Los dos primeros pueden ser letras en algunas empresas; en ese caso solo se
    comprueba el SIREN, porque la fórmula de la clave alfabética no es pública.
    """
    if not re.fullmatch(r"[A-Z0-9]{2}\d{9}", v):
        return False
    siren = v[2:]
    if not _luhn(siren):
        return False
    if v[:2].isdigit():
        return int(v[:2]) == (12 + 3 * (int(siren) % 97)) % 97
    return True


def _it(v: str) -> bool:
    """Partita IVA italiana: once dígitos con control de Luhn."""
    return bool(re.fullmatch(r"\d{11}", v)) and _luhn(v)


def _nl(v: str) -> bool:
    """BTW neerlandés: nueve dígitos, `B` y dos más. Control módulo 11."""
    if not re.fullmatch(r"\d{9}B\d{2}", v):
        return False
    suma = sum(int(v[i]) * (9 - i) for i in range(8))
    return suma % 11 == int(v[8])


def _be(v: str) -> bool:
    """BTW belga: diez dígitos, los dos últimos son el control módulo 97."""
    if not re.fullmatch(r"[01]\d{9}", v):
        return False
    return int(v[:8]) % 97 == 97 - int(v[8:])


def _de(v: str) -> bool:
    """USt-IdNr alemán: nueve dígitos con el control iterativo del ISO 7064."""
    if not re.fullmatch(r"\d{9}", v):
        return False
    producto = 10
    for digito in v[:8]:
        suma = (int(digito) + producto) % 10 or 10
        producto = (2 * suma) % 11
    control = 11 - producto
    return (control % 10) == int(v[8])


def _ie(v: str) -> bool:
    """VAT irlandés, en sus dos formas: la antigua con letra en la posición 2
    y la moderna con todo dígitos."""
    letras = "WABCDEFGHIJKLMNOPQRSTUV"
    if re.fullmatch(r"\d{7}[A-W][A-IW]?", v):
        suma = sum(int(v[i]) * (8 - i) for i in range(7))
        if len(v) == 9:
            suma += (letras.index(v[8]) if v[8] in letras else 0) * 9
        return v[7] == letras[suma % 23]
    if re.fullmatch(r"\d[A-Z+*]\d{5}[A-W]", v):
        # Forma antigua: el segundo carácter no entra en la suma.
        suma = int(v[0]) * 8 + sum(int(v[i]) * (8 - i + 1) for i in range(2, 7))
        return v[7] == letras[suma % 23]
    return False


def _lu(v: str) -> bool:
    """TVA luxemburgués: ocho dígitos, control módulo 89."""
    if not re.fullmatch(r"\d{8}", v):
        return False
    return int(v[:6]) % 89 == int(v[6:])


def _dk(v: str) -> bool:
    """CVR danés: ocho dígitos con control módulo 11."""
    if not re.fullmatch(r"\d{8}", v):
        return False
    pesos = (2, 7, 6, 5, 4, 3, 2, 1)
    return sum(int(d) * p for d, p in zip(v, pesos, strict=True)) % 11 == 0


def _luhn(numero: str) -> bool:
    """Luhn clásico. Lo usan Italia y el SIREN francés, entre otros."""
    total = 0
    for i, caracter in enumerate(reversed(numero)):
        digito = int(caracter)
        if i % 2 == 1:
            digito *= 2
            if digito > 9:
                digito -= 9
        total += digito
    return total % 10 == 0


_ALGORITMOS = {
    "ES": _es,
    "PT": _pt,
    "FR": _fr,
    "IT": _it,
    "NL": _nl,
    "BE": _be,
    "DE": _de,
    "IE": _ie,
    "LU": _lu,
    "DK": _dk,
}
