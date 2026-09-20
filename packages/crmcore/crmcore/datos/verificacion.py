"""Verificar un dato contra algo de fuera, sin atarse a nadie.

Cuatro capacidades del catálogo piden lo mismo con palabras distintas:

  * `CRM-01.01.01.06` — el identificador fiscal, contra el registro oficial.
  * `CRM-01.01.01.05` — la dirección, contra un geocodificador.
  * `CRM-01.01.04.10` — el correo y el teléfono, contra quien sepa decir si
    existen.
  * `CRM-01.01.04.11` — el enriquecimiento con fuentes externas.

Las cuatro son la misma operación: **mandar un dato a un sitio configurado y
guardar qué contestó**. Escribir cuatro clientes distintos —uno para VIES, otro
para un geocodificador, otro para un validador de correo— sería cuatro veces el
mismo código con cuatro formas de fallar y cuatro contratos que mantener.

**No hay código de ningún proveedor.** El tenant declara, por tipo de dato y por
país, a dónde llamar y **de qué parte de la respuesta sale el veredicto**. Es el
mismo patrón que el conector de integraciones y que el canal de notificación por
HTTP, que ya llevan en producción. Enchufar VIES, un geocodificador o el
validador de correo de la casa es configuración, no despliegue.

Tres decisiones que hacen que esto sea utilizable y no un `requests.get`:

**«No comprobado» no es «no válido».** Son tres estados y no dos: `valido`,
`invalido` y `desconocido`. Confundir los dos últimos es cómo un sistema acaba
bloqueando facturas porque el servicio del ministerio estaba caído.

**El veredicto se guarda con su fecha y su detalle.** Un NIF verificado hace
tres años no es un NIF verificado. Sin la fecha, el estado es una opinión sin
caducidad.

**Ante un fallo del servicio, no se degrada el dato.** Si el verificador no
contesta, el estado anterior se conserva y se anota el intento. Poner
`desconocido` encima de un `valido` porque hoy hubo un timeout convertiría cada
incidencia de red en una pérdida de información.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from crmcore.logging import get_logger

logger = get_logger(__name__)

# Los tres estados posibles. `desconocido` es el valor por defecto de todo lo
# que nunca se ha comprobado, y también el de lo que no se ha podido comprobar:
# desde fuera son la misma situación —no lo sabemos— y separarlos obligaría a
# quien consume a tratar dos casos que no puede distinguir.
ESTADOS = ("valido", "invalido", "desconocido")

# Tipos de dato verificables. Lista cerrada para que la configuración de un
# tenant no pueda inventarse un tipo que nadie consulta, que es como se acaba
# con reglas configuradas y muertas.
TIPOS = ("fiscal", "direccion", "correo", "telefono")


@dataclass
class Veredicto:
    """Lo que dijo el verificador, listo para guardar."""

    estado: str = "desconocido"
    detalle: str = ""
    # Lo que devuelva el servicio y se quiera conservar: las coordenadas de un
    # geocodificador, la razón social que devuelve el registro fiscal. Se guarda
    # en bruto porque el valor de esto es poder comparar después lo que dijimos
    # con lo que dijo él.
    datos: dict[str, Any] = field(default_factory=dict)
    momento: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    # `True` cuando no se pudo consultar: la red falló, no hay verificador
    # configurado, el servicio devolvió un error. Quien guarde el resultado NO
    # debe pisar el estado anterior con esto.
    no_concluyente: bool = True

    def a_dict(self) -> dict[str, Any]:
        return {
            "estado": self.estado,
            "detalle": self.detalle,
            "datos": self.datos,
            "momento": self.momento.isoformat(),
            "no_concluyente": self.no_concluyente,
        }


def configuracion(db: Any, tipo: str, pais: str = "") -> dict[str, Any]:
    """La configuración del verificador para este tipo de dato y este país.

    Se busca primero la específica del país y luego la general, porque el
    registro fiscal es distinto en cada país pero el validador de correo es el
    mismo para todos. Sin esa jerarquía, configurar un país obligaría a repetir
    la configuración de los demás.
    """
    from crmcore.runtime import settings as rt

    conocidas = _claves_conocidas()
    for clave in (f"verificador_{tipo}_{pais.lower()}", f"verificador_{tipo}"):
        if clave not in conocidas:
            continue
        valor = rt.efectivo(clave, db, default={})
        if isinstance(valor, dict) and valor.get("url"):
            return dict(valor)
    return {}


def _claves_conocidas() -> set[str]:
    """Las claves de ajuste de verificador que el catálogo declara.

    Se comprueba antes de preguntar para no consultar un ajuste inexistente, que
    devolvería el valor por defecto y haría creer que no hay configuración
    cuando lo que hay es una clave mal escrita —el fallo más frustrante de
    configurar algo, porque no da ningún error—.

    Sale del catálogo y no de una lista aquí: una lista paralela se desincroniza
    el día que alguien añade un verificador nuevo.
    """
    from crmcore.runtime.keys import CLAVES

    return {c for c in CLAVES if c.startswith("verificador_")}


def verificar(
    db: Any,
    *,
    tipo: str,
    valor: str,
    pais: str = "",
    extra: dict[str, Any] | None = None,
) -> Veredicto:
    """Pregunta al verificador configurado. Nunca lanza.

    Devuelve un veredicto `no_concluyente` cuando no hay nada configurado o el
    servicio no contesta. Que no lance es parte del contrato: verificar es una
    mejora del dato, y un alta de cliente no puede fallar porque un servicio
    externo esté caído.
    """
    if tipo not in TIPOS:
        raise ValueError(f"Tipo de verificación desconocido: «{tipo}». Conocidos: {TIPOS}")

    config = configuracion(db, tipo, pais)
    if not config:
        return Veredicto(detalle="no hay verificador configurado para este tipo y país")

    from crmcore.config import get_settings
    from crmcore.red import cliente_seguro

    cuerpo = _componer(config, valor, pais, extra or {})
    metodo = str(config.get("metodo") or "POST").upper()
    s = get_settings()
    try:
        with cliente_seguro(timeout=s.http_externo_timeout_s) as cliente:
            if metodo == "GET":
                respuesta = cliente.get(
                    _sustituir_texto(
                        str(config["url"]), {**(extra or {}), "valor": valor, "pais": pais}
                    ),
                    headers=_cabeceras(config),
                )
            else:
                respuesta = cliente.request(
                    metodo,
                    str(config["url"]),
                    content=cuerpo,
                    headers={"content-type": "application/json", **_cabeceras(config)},
                )
    except Exception as exc:  # noqa: BLE001 — verificar no puede tumbar un alta
        logger.warning("verificacion.fallo", tipo=tipo, pais=pais, error=str(exc)[:200])
        return Veredicto(detalle=f"el verificador no respondió: {type(exc).__name__}")

    if respuesta.status_code >= 400:
        return Veredicto(detalle=f"el verificador respondió {respuesta.status_code}")

    try:
        datos = respuesta.json()
    except Exception:  # noqa: BLE001 — hay servicios que devuelven texto
        return Veredicto(detalle="el verificador no devolvió JSON")

    return _interpretar(config, datos if isinstance(datos, dict) else {"respuesta": datos})


def _interpretar(config: dict[str, Any], datos: dict[str, Any]) -> Veredicto:
    """Saca el veredicto de la respuesta, con el mapeo que declara el tenant.

    El mapeo es lo que evita un cliente por proveedor: uno devuelve
    `{"valid": true}`, otro `{"status": "OK"}` y otro un `200` vacío. Se declara
    de dónde sale el veredicto y qué valor significa «válido».

    Sin mapeo, un `200` se toma como válido. Es lo que hacen la mitad de los
    servicios sencillos, y exigir configuración para ese caso los dejaría fuera.
    """
    mapeo = config.get("mapeo") or {}
    campo = str(mapeo.get("campo") or "")
    if not campo:
        return Veredicto(
            estado="valido",
            detalle="el verificador respondió correctamente",
            datos=_recoger(config, datos),
            no_concluyente=False,
        )

    crudo = _leer(datos, campo)
    if crudo is None:
        # El campo declarado no está en la respuesta: o cambió el contrato del
        # servicio o el mapeo está mal. En ninguno de los dos casos se puede
        # concluir nada, y afirmar «inválido» sería inventárselo.
        logger.warning("verificacion.campo_ausente", campo=campo)
        return Veredicto(detalle=f"la respuesta no trae «{campo}»")

    validos = mapeo.get("valido")
    invalidos = mapeo.get("invalido")
    if validos is not None and _coincide(crudo, validos):
        estado = "valido"
    elif invalidos is not None and _coincide(crudo, invalidos):
        estado = "invalido"
    elif validos is None and invalidos is None:
        # Sin listas declaradas se interpreta como booleano, que es el caso más
        # común: `{"valid": true}`.
        estado = "valido" if bool(crudo) else "invalido"
    else:
        return Veredicto(detalle=f"«{crudo!r}» no encaja en el mapeo declarado")

    return Veredicto(
        estado=estado,
        detalle=str(mapeo.get("detalle_campo") and _leer(datos, str(mapeo["detalle_campo"])) or ""),
        datos=_recoger(config, datos),
        no_concluyente=False,
    )


def _coincide(valor: Any, esperado: Any) -> bool:
    if isinstance(esperado, list):
        return any(str(valor).lower() == str(e).lower() for e in esperado)
    return str(valor).lower() == str(esperado).lower()


def _recoger(config: dict[str, Any], datos: dict[str, Any]) -> dict[str, Any]:
    """Los campos de la respuesta que el tenant quiere conservar.

    Sin `conservar` no se guarda nada: la respuesta de un servicio externo puede
    traer datos personales que nadie pidió, y guardarla entera «por si acaso» es
    exactamente lo que un registro de tratamiento no puede justificar.
    """
    salida: dict[str, Any] = {}
    for destino, origen in (config.get("conservar") or {}).items():
        valor = _leer(datos, str(origen))
        if valor is not None:
            salida[str(destino)] = valor
    return salida


def _leer(datos: dict[str, Any], ruta: str) -> Any:
    actual: Any = datos
    for parte in ruta.split("."):
        if isinstance(actual, dict):
            actual = actual.get(parte)
        elif isinstance(actual, list) and parte.isdigit():
            indice = int(parte)
            actual = actual[indice] if indice < len(actual) else None
        else:
            return None
        if actual is None:
            return None
    return actual


def _cabeceras(config: dict[str, Any]) -> dict[str, str]:
    return {str(k): str(v) for k, v in (config.get("cabeceras") or {}).items()}


def _componer(config: dict[str, Any], valor: str, pais: str, extra: dict[str, Any]) -> bytes:
    plantilla = config.get("cuerpo")
    valores = {**extra, "valor": valor, "pais": pais}
    if not plantilla:
        return json.dumps(valores, ensure_ascii=False).encode()
    return json.dumps(_sustituir(plantilla, valores), ensure_ascii=False).encode()


def _sustituir(estructura: Any, valores: dict[str, Any]) -> Any:
    if isinstance(estructura, dict):
        return {k: _sustituir(v, valores) for k, v in estructura.items()}
    if isinstance(estructura, list):
        return [_sustituir(v, valores) for v in estructura]
    if isinstance(estructura, str):
        return _sustituir_texto(estructura, valores)
    return estructura


def _sustituir_texto(texto: str, valores: dict[str, Any]) -> str:
    """`{{clave}}` y nada más. Una plantilla es dato del tenant, no código."""
    import re

    return re.sub(
        r"\{\{\s*(\w+)\s*\}\}",
        lambda m: str(valores.get(m.group(1), m.group(0))),
        texto,
    )
