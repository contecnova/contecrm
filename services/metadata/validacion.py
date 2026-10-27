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
from datetime import date, datetime, timezone
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


# Con qué precisión se conoce una fecha (CRM-00.04.01.12).
#
# **Un hito que es «marzo de 2027» no es el 1 de marzo de 2027.** Guardarlo
# como un día inventado tiene dos consecuencias que se pagan: el informe cuenta
# vencimientos el día 1 de cada mes y alguien llama al cliente preguntando por
# algo que no había prometido para ese día. Y al revés: quien escribe «Q3» y ve
# «1 de julio» aprende que el sistema se inventa cosas y deja de fiarse.
#
# La granularidad se declara en el campo, no se adivina del valor: adivinarla
# haría que el 1 de marzo escrito a propósito se leyera como «marzo».
GRANULARIDADES = ("dia", "mes", "trimestre")


def _normalizar_por_granularidad(parseada: date | datetime, granularidad: str) -> date | datetime:
    """Lleva la fecha al **primer día** de su periodo.

    Se normaliza al guardar y no sólo al pintar: si cada pantalla recortara por
    su cuenta, dos vistas del mismo dato dirían cosas distintas, y una consulta
    por rango incluiría o excluiría el registro según el día que se tecleó.
    """
    if granularidad == "mes":
        return parseada.replace(day=1)
    if granularidad == "trimestre":
        primer_mes = 3 * ((parseada.month - 1) // 3) + 1
        return parseada.replace(month=primer_mes, day=1)
    return parseada


def _fecha(valor: Any, r: dict[str, Any]) -> str:
    try:
        parseada = (
            valor
            if isinstance(valor, (date, datetime))
            else datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
        )
    except ValueError:
        raise _Invalido("no es una fecha válida (usa ISO-8601)")
    granularidad = str(r.get("granularidad") or "dia")
    if granularidad not in GRANULARIDADES:
        raise _Invalido(f"granularidad desconocida: {granularidad}")
    parseada = _normalizar_por_granularidad(parseada, granularidad)
    texto = parseada.isoformat()
    if r.get("no_pasado") and _esta_en_el_pasado(parseada):
        raise _Invalido("no puede estar en el pasado")
    return texto


def _esta_en_el_pasado(parseada: date | datetime, ahora: datetime | None = None) -> bool:
    """Si esta fecha ya pasó, comparando **instantes y no textos**.

    Comparaba `isoformat()` contra `isoformat()`, que es comparar cadenas: dos
    instantes iguales escritos con husos distintos —`…T00:00:00+02:00` y
    `…T22:00:00Z`— se ordenan por el carácter, no por el momento. Y el reloj iba
    sin huso, así que la mitad de las comparaciones mezclaba una hora local con
    una marca con desplazamiento. Una fecha del futuro podía salir «en el
    pasado», y al revés — en un campo que existe justamente para impedir lo
    segundo.

    `ahora` se recibe para poder fijarlo en una prueba, igual que `hoy` en las
    funciones puras del producto. Sin él, el instante actual en UTC.
    """
    momento = ahora or datetime.now(timezone.utc)
    if isinstance(parseada, datetime):
        # Una fecha sin huso se interpreta en UTC y no en la hora de la máquina:
        # el servidor puede estar en cualquier sitio, y eso no puede cambiar si
        # una fecha se acepta.
        con_huso = parseada if parseada.tzinfo else parseada.replace(tzinfo=timezone.utc)
        return con_huso < momento
    # Una fecha sin hora sólo está en el pasado si el día entero quedó atrás.
    return parseada < momento.date()


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


def _por_que_no_se_puede_tocar(
    campo: Any, registro: dict[str, Any], *, origen: str = ""
) -> tuple[bool, str]:
    """Si este campo está bloqueado ahora mismo, y con qué palabras decirlo.

    Tres puertas, de la más fija a la más fina (CRM-00.04.03.13):

      1. la marca de siempre: calculado o rellenado por el sistema;
      2. **por condición**, con el registro delante: el importe se edita
         mientras la oportunidad está abierta y deja de editarse al cerrarla;
      3. **por procedencia**: el valor lo manda un sistema externo, así que lo
         escribe su integración y no una persona — si lo escribiera una
         persona, la siguiente sincronización se lo pisaría y nadie entendería
         por qué «no se guarda».

    El motivo se devuelve con el bloqueo y no se deja en un código: «no se
    puede modificar» a secas manda a preguntar, y la respuesta siempre es una
    de estas tres.
    """
    from services.metadata.disenador import _cumple

    if campo.solo_lectura:
        return True, f"«{campo.etiqueta}» lo rellena el sistema y no se edita a mano"

    condiciones = list(getattr(campo, "solo_lectura_si", None) or [])
    if condiciones and all(_cumple(c, registro) for c in condiciones):
        return True, f"«{campo.etiqueta}» ya no se puede cambiar en este estado del registro"

    # Lista VACÍA significa «cualquiera», no «ninguno». Al revés, el día que se
    # añadió la columna el modelo entero habría quedado de solo lectura.
    origenes = [str(o) for o in (getattr(campo, "solo_lectura_salvo_origen", None) or [])]
    if origenes and origen not in origenes:
        quienes = ", ".join(origenes)
        return True, f"«{campo.etiqueta}» lo mantiene {quienes}: aquí se ve, no se edita"

    return False, ""


def validar_registro(
    campos: list[Any],
    datos: dict[str, Any],
    *,
    reglas: list[Any] | None = None,
    parcial: bool = False,
    origen: str = "",
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
        bloqueado, porque = _por_que_no_se_puede_tocar(campo, datos, origen=origen)
        if bloqueado and presente:
            errores.append(
                {
                    "campo": campo.nombre,
                    "motivo": "solo_lectura",
                    "mensaje": porque or f"«{campo.etiqueta}» no se puede modificar",
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
        atributo = str(condicion.get("atributo") or "").strip()
        if op is None or not atributo:
            # **No se salta: cuenta como que NO se cumple.** Saltarla dejaba que
            # el resto de condiciones decidieran solas, y una sin atributo
            # comparaba nulo con nulo —cierto—, así que una regla mal escrita
            # saltaba con cualquier registro. Es la misma trampa que tenían el
            # motor de procesos, los webhooks y las automatizaciones.
            resultados.append(False)
            continue
        izquierda = resolver(f"@{atributo}", valores)
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
