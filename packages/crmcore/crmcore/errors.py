"""Errores de dominio y su traducción a *Problem Details* (RFC 9457).

Toda respuesta de error del sistema —de cualquier servicio— tiene la misma
forma (CRM-00.02.01.14):

    {
      "type":     "https://contecrm.dev/errores/validacion",
      "title":    "Datos no válidos",
      "status":   422,
      "detail":   "El campo «importe» no puede ser negativo",
      "instance": "/api/v1/opportunities/opp_0192...",
      "code":     "validacion",
      "error_code": "opportunity.importe_negativo",
      "request_id": "01JB...",
      "errors":   [{"campo": "importe", "motivo": "min", "limite": 0}]
    }

Las tres piezas que la hacen útil para un cliente headless:

  * `code` es la clase ancha y estable (validacion, no_encontrado, conflicto…).
    Un cliente puede ramificar por ella y no se romperá nunca.
  * `error_code` es el identificador fino (`opportunity.importe_negativo`), que
    es lo que permite a un frontend enseñar un mensaje traducido SIN parsear el
    texto en castellano que viene en `detail`.
  * `request_id` cierra el círculo del soporte: el usuario lo ve, lo pega en un
    ticket y con eso se localiza la traza exacta.

Escribir el mensaje en `detail` y el identificador en `error_code` a la vez es
deliberado: el texto sirve cuando alguien lo lee, el código sirve cuando lo lee
un programa, y el sistema no puede saber cuál de los dos va a pasar.
"""

from __future__ import annotations

from typing import Any

# Espacio de nombres de los `type`. Es una URI, no una URL que haya que servir:
# RFC 9457 no exige que resuelva. Aun así se documenta cada una en el manual.
BASE_TIPO = "https://contecrm.dev/errores"


class CrmError(Exception):
    """Error de dominio. Todo lo que el sistema devuelve como 4xx/5xx propio.

    `status_code` y `code` son atributos de clase porque son propiedades del
    TIPO de error, no de la ocurrencia: un `NoEncontrado` siempre es 404.
    """

    status_code: int = 500
    code: str = "error_interno"
    title: str = "Error interno"

    def __init__(
        self,
        mensaje: str,
        *,
        error_code: str | None = None,
        detalle: dict[str, Any] | None = None,
        errores: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.error_code = error_code or self.code
        self.detalle = detalle or {}
        # Lista de problemas por campo, para que un formulario pueda señalar
        # los cinco campos mal de una vez en lugar de uno por intento.
        self.errores = errores or []

    def a_problema(self, instancia: str = "", request_id: str = "") -> dict[str, Any]:
        """Serializa como Problem Details."""
        problema: dict[str, Any] = {
            "type": f"{BASE_TIPO}/{self.code}",
            "title": self.title,
            "status": self.status_code,
            "detail": self.mensaje,
            "code": self.code,
            "error_code": self.error_code,
        }
        if instancia:
            problema["instance"] = instancia
        if request_id:
            problema["request_id"] = request_id
        if self.detalle:
            problema["detalle"] = self.detalle
        if self.errores:
            problema["errors"] = self.errores
        return problema


# ── 4xx ───────────────────────────────────────────────────────────────────


class ErrorValidacion(CrmError):
    status_code = 422
    code = "validacion"
    title = "Datos no válidos"


class NoEncontrado(CrmError):
    status_code = 404
    code = "no_encontrado"
    title = "No encontrado"


class Conflicto(CrmError):
    status_code = 409
    code = "conflicto"
    title = "Conflicto con el estado actual"


class ConflictoDeVersion(Conflicto):
    """El registro cambió entre que el cliente lo leyó y lo quiso escribir.

    Es la respuesta al `If-Match` con ETag caducado (CRM-00.02.01.09). Se separa
    de `Conflicto` porque el cliente tiene una acción clara y distinta: releer,
    reconciliar y reintentar, en vez de avisar a una persona.
    """

    code = "conflicto_de_version"
    title = "El registro ha cambiado"


class NoAutenticado(CrmError):
    status_code = 401
    code = "no_autenticado"
    title = "Autenticación requerida"


class Prohibido(CrmError):
    status_code = 403
    code = "prohibido"
    title = "Sin permiso"


class LimiteExcedido(CrmError):
    """Rate limit o cuota. Lleva `reintentar_en_s` para que el cliente no
    tenga que adivinar cuánto esperar (se copia a la cabecera `Retry-After`)."""

    status_code = 429
    code = "limite_excedido"
    title = "Demasiadas peticiones"

    def __init__(self, mensaje: str, *, reintentar_en_s: int = 60, **kwargs: Any) -> None:
        super().__init__(mensaje, **kwargs)
        self.reintentar_en_s = reintentar_en_s
        self.detalle.setdefault("reintentar_en_s", reintentar_en_s)


class CuotaAgotada(LimiteExcedido):
    """Cuota contratada agotada (registros, almacenamiento, tokens de IA).

    Distinto de un rate limit aunque comparta el 403/429: el rate limit se pasa
    esperando, la cuota se pasa ampliando el plan. Un cliente que reintenta en
    bucle ante una cuota agotada nunca va a pasar, así que merece un código
    propio que se lo diga.
    """

    code = "cuota_agotada"
    title = "Cuota agotada"


class TenantSuspendido(CrmError):
    status_code = 403
    code = "tenant_suspendido"
    title = "Tenant suspendido"


class SoloLectura(CrmError):
    """El tenant está congelado en solo lectura (CRM-00.01.03.04), o el sistema
    está en modo degradado y ha diferido las escrituras (CRM-00.06.02.07)."""

    status_code = 409
    code = "solo_lectura"
    title = "Sistema en solo lectura"


# ── 5xx y dependencias ────────────────────────────────────────────────────


class ErrorInterno(CrmError):
    status_code = 500
    code = "error_interno"
    title = "Error interno"


class ErrorDependencia(CrmError):
    """Un sistema del que dependemos ha fallado: otro servicio, el ERP, el bus."""

    status_code = 502
    code = "error_dependencia"
    title = "Error en un sistema dependiente"


class PeticionMalFormada(ErrorDependencia):
    """La petición que NOSOTROS mandamos fue rechazada por el otro extremo.

    Se separa de `ErrorDependencia` porque el fallo es determinista: reintentar
    lo mismo falla igual. Por eso NO debe contar para el circuit breaker — un
    error de configuración abriría el circuito y taparía la causa real detrás
    de un «circuito abierto» en todas las llamadas siguientes.
    """

    code = "peticion_mal_formada"
    title = "Petición rechazada por el sistema externo"


class NoDisponible(CrmError):
    status_code = 503
    code = "no_disponible"
    title = "Servicio no disponible"


class TiempoAgotado(CrmError):
    status_code = 504
    code = "tiempo_agotado"
    title = "Tiempo de espera agotado"


# Mapa de código a clase, para reconstruir el error de dominio a partir de la
# respuesta de otro servicio. Es lo que permite que un fallo de validación en el
# servicio de metadatos llegue al cliente como un 422 y no convertido en un 502
# genérico que no dice nada.
POR_CODIGO: dict[str, type[CrmError]] = {
    cls.code: cls
    for cls in (
        ErrorValidacion,
        NoEncontrado,
        Conflicto,
        ConflictoDeVersion,
        NoAutenticado,
        Prohibido,
        LimiteExcedido,
        CuotaAgotada,
        TenantSuspendido,
        SoloLectura,
        ErrorInterno,
        ErrorDependencia,
        PeticionMalFormada,
        NoDisponible,
        TiempoAgotado,
    )
}


def desde_problema(problema: dict[str, Any]) -> CrmError:
    """Reconstruye el error de dominio desde un Problem Details recibido."""
    cls = POR_CODIGO.get(str(problema.get("code", "")), ErrorDependencia)
    return cls(
        str(problema.get("detail") or problema.get("title") or "Error"),
        error_code=problema.get("error_code"),
        detalle=problema.get("detalle") or {},
        errores=problema.get("errors") or [],
    )
