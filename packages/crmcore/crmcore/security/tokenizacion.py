"""Tokenización de datos de pago e identificadores fiscales (CRM-00.05.03.04).

Cifrar un número de tarjeta lo protege de quien lea la base. **Tokenizarlo lo
saca de la base**, que es otra cosa: lo que queda en el CRM es una referencia sin
valor, y el número vive donde sabe guardarlo quien tiene el certificado para
hacerlo.

La diferencia importa el día de la auditoría: un sistema que cifra tarjetas sigue
estando dentro del alcance de PCI; uno que no las tiene, no.

Las decisiones:

**El token no se parece al dato.** Mantener los cuatro últimos dígitos es útil y
es exactamente lo que se guarda aparte, marcado como lo que es: una pista para
que una persona reconozca su tarjeta, no un dato para operar.

**Detokenizar es una operación con nombre, permiso y rastro.** Si fuera
transparente —que el ORM lo resolviera solo al leer— el dato volvería a estar en
todas partes y la tokenización no serviría de nada. Tiene que costar pedirlo.

**Sin bóveda configurada no se tokeniza en falso.** Guardar el número «hasta que
haya bóveda» es cómo se acaba con una tabla llena de tarjetas que nadie recuerda.

**Y se busca lo que se cuela por texto libre.** El caso real no es que alguien
decida guardar tarjetas: es que un integrador manda el número en un campo de
notas, y ahí se queda.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Callable

from crmcore.errors import ErrorDependencia, ErrorValidacion
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Qué se tokeniza. Cerrada porque cada tipo tiene su regla de conservación y su
# forma de enseñarse.
TIPOS = ("tarjeta", "cuenta_bancaria", "identificador_fiscal")

# Qué pista se conserva para que una persona reconozca lo suyo. De una tarjeta,
# los cuatro últimos; de un NIF, nada — con la letra y dos dígitos se adivina el
# resto.
PISTA = {"tarjeta": 4, "cuenta_bancaria": 4, "identificador_fiscal": 0}

_boveda: Callable[..., str] | None = None
_destokenizador: Callable[..., str] | None = None


def registrar_boveda(guardar: Callable[..., str], recuperar: Callable[..., str]) -> None:
    """Conecta la bóveda que guarda los números de verdad.

    Se registra desde fuera porque **el dato no vive aquí**: quien lo guarda es
    quien tiene el certificado para hacerlo, y este módulo solo sabe pedírselo.
    """
    global _boveda, _destokenizador
    _boveda = guardar
    _destokenizador = recuperar


def hay_boveda() -> bool:
    return _boveda is not None


def tokenizar(valor: str, *, tipo: str, tenant_id: Any) -> dict[str, Any]:
    """Saca el número del CRM y devuelve una referencia sin valor.

    **Sin bóveda no se tokeniza en falso.** Guardar el número «hasta que haya
    bóveda» mete el sistema en el alcance de PCI sin que nadie lo haya decidido.
    """
    if tipo not in TIPOS:
        raise ErrorValidacion(
            f"Tipo tokenizable desconocido: «{tipo}»",
            error_code="tokenizacion.tipo_invalido",
            detalle={"admitidos": list(TIPOS)},
        )
    limpio = re.sub(r"[\s-]", "", valor or "")
    if not limpio:
        raise ErrorValidacion("No hay nada que tokenizar", error_code="tokenizacion.vacio")
    if _boveda is None:
        raise ErrorDependencia(
            "No hay bóveda configurada: este despliegue no puede tokenizar. Guardar "
            "el número mientras tanto metería el sistema en el alcance de PCI sin "
            "que nadie lo hubiera decidido.",
            error_code="tokenizacion.sin_boveda",
        )

    token = _boveda(valor=limpio, tipo=tipo, tenant_id=tenant_id)
    ultimos = PISTA[tipo]
    return {
        "token": token,
        "tipo": tipo,
        # La pista es para que una persona reconozca lo suyo, no para operar.
        "pista": limpio[-ultimos:] if ultimos else "",
        "pista_es_solo_para_reconocerlo": True,
        "tokenizado_at": datetime.now(timezone.utc).isoformat(),
        "el_numero_no_esta_aqui": (
            "El valor vive en la bóveda. Lo que guarda el CRM es esta referencia, que "
            "no sirve para cobrar ni para identificar a nadie."
        ),
    }


def destokenizar(token: str, *, tipo: str, tenant_id: Any, motivo: str, por: Any) -> str:
    """Recupera el número, **con motivo y rastro**.

    No es transparente a propósito. Si el ORM lo resolviera solo al leer, el dato
    volvería a estar en todas partes —en los registros, en las cachés, en las
    respuestas de la API— y la tokenización no habría servido de nada.
    """
    if not motivo.strip():
        raise ErrorValidacion(
            "Recuperar un dato tokenizado exige decir para qué: sin motivo, la lista "
            "de accesos es una lista de nombres sin nada que decidir.",
            error_code="tokenizacion.sin_motivo",
        )
    if _destokenizador is None:
        raise ErrorDependencia("No hay bóveda configurada", error_code="tokenizacion.sin_boveda")
    logger.warning("tokenizacion.destokenizado", tipo=tipo, motivo=motivo[:120], por=str(por))
    return _destokenizador(token=token, tipo=tipo, tenant_id=tenant_id)


def comprobar_no_hay_numeros(datos: dict[str, Any]) -> list[str]:
    """Busca números de tarjeta colados sin tokenizar.

    El caso real no es que alguien decida guardar tarjetas: es que un integrador
    manda el número en un campo de texto libre —«forma de pago: 4111…»— y ahí se
    queda. Un campo de notas con una tarjeta dentro mete al sistema en el alcance
    igual que una columna dedicada.
    """
    sospechosos: list[str] = []
    patron = re.compile(r"\b(?:\d[ -]?){13,19}\b")
    for campo, valor in (datos or {}).items():
        if not isinstance(valor, str):
            continue
        for encontrado in patron.findall(valor):
            digitos = re.sub(r"[^0-9]", "", encontrado)
            if 13 <= len(digitos) <= 19 and _luhn(digitos):
                sospechosos.append(campo)
                break
    return sorted(set(sospechosos))


def _luhn(numero: str) -> bool:
    """Comprobación de Luhn.

    Se usa para no dar la alarma con cualquier número largo: un código de pedido
    de dieciséis dígitos no es una tarjeta, y un aviso que salta con todo se
    ignora a la semana.
    """
    total = 0
    for i, caracter in enumerate(reversed(numero)):
        digito = int(caracter)
        if i % 2 == 1:
            digito *= 2
            if digito > 9:
                digito -= 9
        total += digito
    return total % 10 == 0
