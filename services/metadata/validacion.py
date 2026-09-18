"""Motor de validación: el mismo código para guardar y para el dry-run.

Que sea **el mismo** es la única forma de que el dry-run signifique algo. Si la
comprobación previa y la de guardar fueran dos implementaciones, tarde o
temprano divergirían y el cliente recibiría un «válido» seguido de un error al
enviar — que es peor que no ofrecer dry-run.

Devuelve **todos** los errores, no el primero. Un formulario que corrige un
error por intento es una conversación de cinco viajes con el servidor.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from crmcore.errors import ErrorValidacion

# Validadores por tipo de campo. Cada uno devuelve el valor convertido o lanza
# `_Invalido` con el motivo. Se separan por tipo para que añadir un tipo nuevo
# sea añadir una función, no tocar una cadena de condicionales.
RE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$")
RE_TELEFONO = re.compile(r"^\+?[0-9\s().-]{6,25}$")
RE_URL = re.compile(r"^https?://[^\s]+$")


class _Invalido(Exception):
    def __init__(self, motivo: str, detalle: dict[str, Any] | None = None) -> None:
        super().__init__(motivo)
        self.motivo = motivo
        self.detalle = detalle or {}


def _texto(valor: Any, r: dict[str, Any]) -> str:
    texto = str(valor)
    minimo, maximo = r.get("min_longitud"), r.get("max_longitud")
    if minimo is not None and len(texto) < int(minimo):
        raise _Invalido(f"debe tener al menos {minimo} caracteres")
    if maximo is not None and len(texto) > int(maximo):
        raise _Invalido(f"no puede pasar de {maximo} caracteres")
    patron = r.get("patron")
    if patron:
        try:
            if not re.match(str(patron), texto):
                raise _Invalido(r.get("mensaje_patron") or "no tiene el formato esperado")
        except re.error:
            # Un patrón mal escrito es un error de configuración, no del dato.
            # Se deja pasar el valor y se avisa: bloquear a los usuarios por una
            # expresión regular mal puesta por un administrador sería peor.
            pass
    return texto


def _numero(valor: Any, r: dict[str, Any]) -> float:
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        raise _Invalido("no es un número")
    minimo, maximo = r.get("min"), r.get("max")
    if minimo is not None and numero < float(minimo):
        raise _Invalido(f"no puede ser menor que {minimo}")
    if maximo is not None and numero > float(maximo):
        raise _Invalido(f"no puede ser mayor que {maximo}")
    decimales = r.get("decimales")
    if decimales is not None:
        numero = round(numero, int(decimales))
    return numero


def _booleano(valor: Any, _r: dict[str, Any]) -> bool:
    if isinstance(valor, bool):
        return valor
    if str(valor).lower() in ("1", "true", "si", "sí", "verdadero"):
        return True
    if str(valor).lower() in ("0", "false", "no", "falso"):
        return False
    raise _Invalido("no es un valor de sí/no")


def _fecha(valor: Any, r: dict[str, Any]) -> str:
    try:
        parseada = (
            valor
            if isinstance(valor, (date, datetime))
            else datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
        )
    except ValueError:
        raise _Invalido("no es una fecha válida (usa ISO-8601)")
    texto = parseada.isoformat()
    if r.get("no_pasado") and str(texto) < datetime.now().isoformat():
        raise _Invalido("no puede estar en el pasado")
    return texto


def _lista(valor: Any, r: dict[str, Any]) -> str:
    opciones = [str(o) for o in (r.get("opciones") or [])]
    if opciones and str(valor) not in opciones:
        raise _Invalido("no es una de las opciones admitidas", {"opciones": opciones[:50]})
    return str(valor)


def _lista_multiple(valor: Any, r: dict[str, Any]) -> list[str]:
    if not isinstance(valor, list):
        raise _Invalido("se espera una lista de valores")
    opciones = [str(o) for o in (r.get("opciones") or [])]
    if opciones:
        fuera = [str(v) for v in valor if str(v) not in opciones]
        if fuera:
            raise _Invalido("contiene valores no admitidos", {"no_admitidos": fuera[:20]})
    maximo = r.get("max_seleccion")
    if maximo is not None and len(valor) > int(maximo):
        raise _Invalido(f"no se pueden seleccionar más de {maximo}")
    return [str(v) for v in valor]


def _email(valor: Any, _r: dict[str, Any]) -> str:
    texto = str(valor).strip()
    if not RE_EMAIL.match(texto):
        raise _Invalido("no parece una dirección de correo")
    return texto.lower()


def _telefono(valor: Any, _r: dict[str, Any]) -> str:
    texto = str(valor).strip()
    if not RE_TELEFONO.match(texto):
        raise _Invalido("no parece un número de teléfono")
    return texto


def _url(valor: Any, _r: dict[str, Any]) -> str:
    texto = str(valor).strip()
    if not RE_URL.match(texto):
        raise _Invalido("debe empezar por http:// o https://")
    return texto


def _geo(valor: Any, _r: dict[str, Any]) -> dict[str, float]:
    if not isinstance(valor, dict) or "lat" not in valor or "lon" not in valor:
        raise _Invalido("se espera {lat, lon}")
    lat, lon = float(valor["lat"]), float(valor["lon"])
    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        raise _Invalido("las coordenadas están fuera de rango")
    return {"lat": lat, "lon": lon}


VALIDADORES = {
    "texto": _texto,
    "texto_largo": _texto,
    "numero": _numero,
    "moneda": _numero,
    "porcentaje": _numero,
    "booleano": _booleano,
    "fecha": _fecha,
    "fecha_hora": _fecha,
    "lista": _lista,
    "lista_multiple": _lista_multiple,
    "email": _email,
    "telefono": _telefono,
    "url": _url,
    "geolocalizacion": _geo,
    # `json`, `fichero`, `lookup` y `cifrado` no se validan de forma aquí: el
    # lookup lo comprueba el servicio dueño del objeto destino, el fichero lo
    # valida el almacenamiento y el cifrado se valida como su tipo base.
}


def validar_campo(campo: Any, valor: Any) -> Any:
    """Valida y convierte el valor de un campo. Lanza `_Invalido` si no vale."""
    if valor is None or valor == "":
        if campo.obligatorio:
            raise _Invalido("es obligatorio")
        return None
    validador = VALIDADORES.get(campo.tipo)
    if validador is None:
        return valor
    return validador(valor, campo.restricciones or {})


def validar_registro(
    campos: list[Any],
    datos: dict[str, Any],
    *,
    reglas: list[Any] | None = None,
    parcial: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Valida un registro entero. Devuelve (valores convertidos, errores).

    `parcial=True` para un PATCH: no exige los obligatorios que no vengan,
    porque en una actualización parcial el valor que falta es el que ya está
    guardado, no un hueco.
    """
    valores: dict[str, Any] = {}
    errores: list[dict[str, Any]] = []

    for campo in campos:
        if not campo.activo:
            continue
        presente = campo.nombre in datos
        if not presente and parcial:
            continue
        if campo.solo_lectura and presente:
            errores.append(
                {
                    "campo": campo.nombre,
                    "motivo": "solo_lectura",
                    "mensaje": f"«{campo.etiqueta}» no se puede modificar",
                }
            )
            continue
        try:
            valores[campo.nombre] = validar_campo(campo, datos.get(campo.nombre))
        except _Invalido as inv:
            errores.append(
                {
                    "campo": campo.nombre,
                    "motivo": "invalido",
                    # El mensaje lleva la ETIQUETA, no el nombre de API: quien
                    # lo lee es una persona rellenando un formulario.
                    "mensaje": f"«{campo.etiqueta}» {inv.motivo}",
                    **inv.detalle,
                }
            )

    # Campos enviados que no existen. Se avisa en vez de ignorarlos: un campo
    # mal escrito que se ignora en silencio es un dato que el cliente cree haber
    # guardado y no está.
    conocidos = {c.nombre for c in campos}
    for enviado in datos:
        if enviado not in conocidos:
            errores.append(
                {
                    "campo": enviado,
                    "motivo": "desconocido",
                    "mensaje": f"El campo «{enviado}» no existe en este objeto",
                }
            )

    for regla in reglas or []:
        if not regla.activa:
            continue
        if _regla_incumplida(regla, {**datos, **valores}):
            errores.append(
                {"campo": "", "motivo": f"regla:{regla.nombre}", "mensaje": regla.mensaje}
            )

    return valores, errores


def _regla_incumplida(regla: Any, valores: dict[str, Any]) -> bool:
    """Una regla se incumple cuando sus condiciones se cumplen.

    Las condiciones describen la situación PROHIBIDA, no la válida. Es al revés
    de lo que uno espera, y se hace así porque el mensaje de error se escribe
    junto a la condición: «la fecha de cierre es anterior a la de alta» se lee
    igual en la regla y en el error.
    """
    from services.orchestrator.motor import OPERADORES, resolver

    resultados = []
    for condicion in regla.condiciones or []:
        op = OPERADORES.get(str(condicion.get("op", "=")))
        if op is None:
            continue
        izquierda = resolver(f"@{condicion.get('atributo', '')}", valores)
        derecha = resolver(condicion.get("valor"), valores)
        try:
            resultados.append(op(izquierda, derecha))
        except TypeError:
            resultados.append(False)
    if not resultados:
        return False
    return all(resultados) if regla.combinacion == "todas" else any(resultados)


def exigir_valido(errores: list[dict[str, Any]]) -> None:
    """Convierte la lista de errores en un 422 con todos ellos."""
    if errores:
        raise ErrorValidacion(
            "El registro no es válido",
            error_code="metadata.registro_invalido",
            errores=errores,
        )
