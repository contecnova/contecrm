"""Localización por tenant: formatos, husos y moneda (CRM-00.01.04.07).

El idioma, la zona horaria, el formato de fecha, el primer día de la semana y la
moneda funcional **ya se guardaban** como ajustes en caliente, con jerarquía
global → tier → tenant → unidad → usuario. Lo que faltaba es lo único que hace
que sirvan de algo: **aplicarlos**.

Una preferencia guardada y no aplicada es peor que no tenerla. El cliente la
configura, la ve guardada, y el sistema sigue enseñando `2026-09-19 07:00` a un
usuario mexicano que pidió `19/09/2026` en hora de Ciudad de México. Nadie lo
llama avería porque no hay error: simplemente no pasa nada.

Tres decisiones:

**Se formatea al salir, nunca se guarda formateado.** En la base, un instante es
UTC y un importe es un número con su moneda. Guardar «19/09/2026» convierte un
dato en una presentación, y el día que el cliente cambia de formato ya no se
puede recuperar. La conversión ocurre en el borde: la plantilla que se envía, el
documento que se genera, la respuesta que pide un formato humano.

**Sin dependencias nuevas.** `zoneinfo` viene en la biblioteca estándar y el
formateo de números se escribe en veinte líneas. Añadir `babel` traería el CLDR
entero —decenas de megabytes— para cinco idiomas y tres formatos de fecha que
esta instalación decide por configuración, no por lo que diga el CLDR de la
región. Si algún día hacen falta plurales o formatos de lista, es el momento de
traerlo, y se dirá.

**Una zona horaria inválida no rompe nada.** Se cae a UTC y se avisa. Un ajuste
mal escrito por un administrador no puede impedir que se envíe un correo — pero
tampoco puede pasar en silencio, porque entonces nadie lo corrige.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from crmcore.logging import get_logger

logger = get_logger(__name__)

# Cómo se escribe cada formato declarado en el catálogo de ajustes. La clave es
# lo que ve el administrador; el valor, lo que entiende `strftime`.
FORMATOS_FECHA = {
    "dd/mm/aaaa": "%d/%m/%Y",
    "mm/dd/aaaa": "%m/%d/%Y",
    "aaaa-mm-dd": "%Y-%m-%d",
}
FORMATO_FECHA_POR_DEFECTO = "dd/mm/aaaa"

# Separadores por idioma. No salen de una biblioteca de locales a propósito: son
# cinco idiomas y la regla es estable desde hace un siglo. Lo que sí cambia —qué
# formato quiere ESTE cliente— es configuración, y esa sí se consulta.
SEPARADORES = {
    "es": (".", ","),
    "ca": (".", ","),
    "pt": (".", ","),
    "fr": (" ", ","),
    "de": (".", ","),
    "en": (",", "."),
}
SEPARADORES_POR_DEFECTO = (".", ",")

# Símbolo de las monedas que esta instalación usa a diario. Una moneda que no
# esté aquí se escribe con su código ISO, que es correcto y legible: «1.234,50
# CLP» se entiende, y es preferible a un símbolo inventado.
SIMBOLOS = {
    "EUR": "€",
    "USD": "$",
    "GBP": "£",
    "CHF": "CHF",
    "MXN": "$",
    "BRL": "R$",
    "JPY": "¥",
}


class Localizacion:
    """Las preferencias resueltas para un contexto, ya listas para usar.

    Se resuelve **una vez** y se pasa: cada ajuste consultado atraviesa la
    jerarquía y su caché, y hacerlo por cada fecha de un listado de doscientas
    filas son mil consultas para aplicar la misma regla.
    """

    __slots__ = ("idioma", "zona", "formato_fecha", "moneda", "primer_dia")

    def __init__(
        self,
        *,
        idioma: str = "es",
        zona: str = "UTC",
        formato_fecha: str = FORMATO_FECHA_POR_DEFECTO,
        moneda: str = "EUR",
        primer_dia: int = 0,
    ) -> None:
        self.idioma = idioma
        self.zona = _zona(zona)
        self.formato_fecha = FORMATOS_FECHA.get(
            formato_fecha, FORMATOS_FECHA[FORMATO_FECHA_POR_DEFECTO]
        )
        self.moneda = moneda
        self.primer_dia = primer_dia

    # ── Fechas ────────────────────────────────────────────────────────────

    def fecha(self, valor: datetime | date | None) -> str:
        """Solo la fecha, en la zona del tenant.

        Convertir a la zona ANTES de recortar la hora es lo que evita el error
        clásico: un instante UTC de las 23:30 del día 18 es el día 19 en Madrid,
        y recortar primero lo fecharía un día antes. En un vencimiento de SLA o
        en una fecha de cierre, ese día importa.
        """
        if valor is None:
            return ""
        if isinstance(valor, datetime):
            valor = self._local(valor).date()
        return valor.strftime(self.formato_fecha)

    def fecha_hora(self, valor: datetime | None, *, con_segundos: bool = False) -> str:
        if valor is None:
            return ""
        patron = f"{self.formato_fecha} %H:%M:%S" if con_segundos else f"{self.formato_fecha} %H:%M"
        return self._local(valor).strftime(patron)

    def hora(self, valor: datetime | None) -> str:
        return "" if valor is None else self._local(valor).strftime("%H:%M")

    def _local(self, valor: datetime) -> datetime:
        # Un `datetime` sin zona se trata como UTC y no como hora local del
        # servidor: todo lo que esta base guarda es UTC, y asumir la del
        # servidor haría que el mismo dato se viera distinto según dónde corra
        # la réplica que atiende.
        if valor.tzinfo is None:
            valor = valor.replace(tzinfo=timezone.utc)
        return valor.astimezone(self.zona)

    # ── Números e importes ────────────────────────────────────────────────

    def numero(self, valor: Any, *, decimales: int = 2) -> str:
        if valor is None:
            return ""
        miles, decimal = SEPARADORES.get(self.idioma, SEPARADORES_POR_DEFECTO)
        try:
            cantidad = Decimal(str(valor))
        except (ArithmeticError, ValueError):
            return str(valor)
        entero, _, resto = f"{cantidad:,.{decimales}f}".partition(".")
        # Se formatea con los separadores de Python y se sustituyen después, en
        # dos pasos y con un marcador intermedio: hacerlo en uno convierte las
        # comas en puntos y los puntos en comas sobre el mismo texto, y el
        # resultado son todos los separadores iguales.
        entero = entero.replace(",", "\x00").replace("\x00", miles)
        return f"{entero}{decimal}{resto}" if resto else entero

    def importe(self, valor: Any, moneda: str | None = None, *, decimales: int = 2) -> str:
        """Importe con su símbolo, en la posición que usa el idioma.

        El símbolo va detrás en español y delante en inglés. No es un detalle
        estético: «$1,234.50» y «1.234,50 $» los lee bien cada uno de los dos, y
        el cruzado lo lee mal alguno de los dos.
        """
        if valor is None:
            return ""
        codigo = (moneda or self.moneda or "EUR").upper()
        simbolo = SIMBOLOS.get(codigo, codigo)
        texto = self.numero(valor, decimales=decimales)
        return f"{simbolo}{texto}" if self.idioma == "en" else f"{texto} {simbolo}"

    # ── Calendario ────────────────────────────────────────────────────────

    def dias_de_la_semana(self) -> list[int]:
        """Los siete días empezando por el primero que use este tenant.

        `0` es lunes, como en `datetime.weekday()`. Lo consume quien pinta un
        calendario o calcula una semana: un tenant estadounidense empieza en
        domingo, y una vista semanal que siempre empieza en lunes le descoloca
        todas las columnas.
        """
        inicio = self.primer_dia % 7
        return [(inicio + i) % 7 for i in range(7)]


def _zona(nombre: str) -> ZoneInfo:
    try:
        return ZoneInfo(nombre or "UTC")
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        # Se avisa y se sigue en UTC. Un ajuste mal escrito no puede impedir que
        # salga un correo, pero tampoco puede pasar callado: si no se ve, nadie
        # lo corrige y todo el tenant vive con las horas desplazadas.
        logger.warning("i18n.zona_desconocida", zona=str(nombre)[:60])
        return ZoneInfo("UTC")


def resolver(db: Any = None) -> Localizacion:
    """Las preferencias del contexto en curso, ya resueltas.

    Atraviesa la jerarquía de ajustes: lo que fije el usuario gana sobre lo del
    tenant, y eso sobre lo del despliegue. Sin sesión de base devuelve lo del
    `.env`, que es lo que permite llamarla desde un worker o un script sin abrir
    una conexión solo para leer cinco cadenas.
    """
    from crmcore.runtime import settings as rt

    return Localizacion(
        idioma=str(rt.efectivo("idioma", db, default="es") or "es"),
        zona=str(rt.efectivo("zona_horaria", db, default="UTC") or "UTC"),
        formato_fecha=str(
            rt.efectivo("formato_fecha", db, default=FORMATO_FECHA_POR_DEFECTO)
            or FORMATO_FECHA_POR_DEFECTO
        ),
        moneda=str(rt.efectivo("moneda_funcional", db, default="EUR") or "EUR"),
        primer_dia=int(rt.efectivo("primer_dia_semana", db, default=0) or 0),
    )


def formatear_valores(datos: dict[str, Any], loc: Localizacion) -> dict[str, Any]:
    """Convierte fechas y decimales de un diccionario a texto localizado.

    Es lo que se aplica antes de rellenar una plantilla. Sin esto, un correo
    generado desde una plantilla enseña `2026-09-19 07:00:00+00:00` en mitad de
    una frase, que es la forma más rápida de que un cliente deje de confiar en
    los avisos automáticos.

    Recorre también las estructuras anidadas: los datos de una plantilla llegan
    casi siempre como `{"oportunidad": {...}, "cuenta": {...}}`, y formatear
    solo el primer nivel dejaría sin tocar justo lo que se escribe en el cuerpo.
    """
    salida: dict[str, Any] = {}
    for clave, valor in datos.items():
        salida[clave] = _formatear(valor, loc)
    return salida


def _formatear(valor: Any, loc: Localizacion) -> Any:
    if isinstance(valor, datetime):
        return loc.fecha_hora(valor)
    if isinstance(valor, date):
        return loc.fecha(valor)
    if isinstance(valor, Decimal):
        return loc.numero(valor)
    if isinstance(valor, dict):
        return {k: _formatear(v, loc) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_formatear(v, loc) for v in valor]
    return valor
