"""Expresiones cron de cinco campos, para las automatizaciones programadas
(CRM-00.03.03.05).

`programacion` se guardaba como texto y no la leía nadie: una regla «todos los
lunes a las ocho» no corría nunca. Para que corra hace falta saber **cuándo toca
la siguiente vez**, y eso es todo lo que hace este módulo.

Por qué escrito aquí y no con una biblioteca: lo que se necesita son los cinco
campos clásicos —minuto, hora, día del mes, mes y día de la semana— con `*`,
listas, rangos y pasos. Son sesenta líneas y no cambian; una dependencia nueva
para esto es una dependencia más que actualizar y que auditar.

**La hora es la del tenant, no la del servidor.** «A las ocho» es a las ocho de
quien lo escribe. Se calcula en su zona y se guarda en UTC, así que el cambio de
hora de marzo y de octubre no adelanta ni retrasa la regla: sigue saliendo a las
ocho de su reloj.

Día del mes y día de la semana se combinan como en cron: si los dos están
acotados, basta con que se cumpla uno («el 1 o cualquier lunes»). Es raro y
contraintuitivo, pero es lo que entiende cualquiera que ya escriba cron, y
cambiarlo sería que la misma expresión hiciera aquí otra cosa.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from crmcore.errors import ErrorValidacion

# (nombre, mínimo, máximo) de cada campo, en orden.
_CAMPOS = (
    ("minuto", 0, 59),
    ("hora", 0, 23),
    ("día del mes", 1, 31),
    ("mes", 1, 12),
    ("día de la semana", 0, 7),
)


def _campo(texto: str, nombre: str, minimo: int, maximo: int) -> frozenset[int]:
    valores: set[int] = set()
    for parte in texto.split(","):
        paso = 1
        if "/" in parte:
            parte, paso_txt = parte.split("/", 1)
            if not paso_txt.isdigit() or int(paso_txt) < 1:
                raise ValueError(f"paso «{paso_txt}» no válido en el {nombre}")
            paso = int(paso_txt)
        if parte == "*":
            desde, hasta = minimo, maximo
        elif "-" in parte:
            a, b = parte.split("-", 1)
            if not (a.isdigit() and b.isdigit()):
                raise ValueError(f"rango «{parte}» no válido en el {nombre}")
            desde, hasta = int(a), int(b)
        elif parte.isdigit():
            desde = hasta = int(parte)
            # «5/15» es «del 5 en adelante, de quince en quince», como en cron.
            if paso > 1:
                hasta = maximo
        else:
            raise ValueError(f"«{parte}» no es un valor del {nombre}")
        if desde < minimo or hasta > maximo or desde > hasta:
            raise ValueError(f"el {nombre} va de {minimo} a {maximo}: «{parte}» se sale")
        valores.update(range(desde, hasta + 1, paso))
    return frozenset(valores)


class Cron:
    """Una expresión ya leída. Se construye con `leer()`."""

    def __init__(self, expresion: str) -> None:
        partes = expresion.split()
        if len(partes) != 5:
            raise ValueError(
                f"tiene {len(partes)} campos y son cinco: minuto, hora, día del mes, mes y "
                "día de la semana (por ejemplo «0 8 * * 1», los lunes a las 8)"
            )
        self.expresion = expresion
        conjuntos = [
            _campo(p, nombre, mi, ma) for p, (nombre, mi, ma) in zip(partes, _CAMPOS, strict=True)
        ]
        self.minutos, self.horas, self.dias, self.meses, semana = conjuntos
        # El domingo vale 0 y 7, como en cron. Python cuenta el lunes como 0.
        self.semana = frozenset(7 if d == 0 else d for d in semana)
        self._dia_acotado = partes[2] != "*"
        self._semana_acotada = partes[4] != "*"

    def _dia_vale(self, dia: datetime) -> bool:
        if dia.month not in self.meses:
            return False
        del_mes = dia.day in self.dias
        de_la_semana = (dia.isoweekday()) in self.semana
        if self._dia_acotado and self._semana_acotada:
            return del_mes or de_la_semana
        if self._dia_acotado:
            return del_mes
        if self._semana_acotada:
            return de_la_semana
        return True

    def siguiente(self, despues_de: datetime, zona: ZoneInfo | None = None) -> datetime:
        """El primer instante que cumple la expresión, estrictamente después de
        `despues_de`. Devuelve UTC.

        Recorre días y no minutos: en el peor caso —«el 29 de febrero»— son unos
        pocos miles de vueltas y no medio millón. El tope de ocho años cubre
        cualquier expresión que se pueda cumplir; una que no se cumple nunca
        («el 31 de febrero») se dice en vez de colgar el planificador.
        """
        zona = zona or ZoneInfo("UTC")
        local = despues_de.astimezone(zona).replace(second=0, microsecond=0, tzinfo=None)
        local += timedelta(minutes=1)
        dia = local.replace(hour=0, minute=0)
        for _ in range(366 * 8):
            if self._dia_vale(dia):
                for hora in sorted(self.horas):
                    for minuto in sorted(self.minutos):
                        candidato = dia.replace(hour=hora, minute=minuto)
                        if candidato < local:
                            continue
                        absoluto = candidato.replace(tzinfo=zona).astimezone(timezone.utc)
                        # Una hora que no existe —la que se salta el cambio de
                        # marzo— vuelve convertida a otra; se acepta igual, pero
                        # nunca por detrás del punto de partida.
                        if absoluto > despues_de.astimezone(timezone.utc):
                            return absoluto
            dia += timedelta(days=1)
        raise ValueError("la expresión no se cumple nunca (¿un 31 de febrero?)")


def leer(expresion: str | None) -> Cron:
    """Lee la expresión o explica por qué no vale, con un error de validación."""
    texto = (expresion or "").strip()
    if not texto:
        raise ErrorValidacion(
            "Una automatización programada necesita su horario en «programacion»: "
            "una expresión cron, por ejemplo «0 8 * * 1» para los lunes a las 8",
            error_code="automatizacion.sin_programacion",
        )
    try:
        cron = Cron(texto)
        # Se comprueba que se cumple alguna vez: «0 0 31 2 *» se lee bien y no
        # correría nunca, que es lo mismo que no tener horario.
        cron.siguiente(datetime.now(timezone.utc))
    except ValueError as exc:
        raise ErrorValidacion(
            f"El horario «{texto}» no es una expresión cron válida: {exc}",
            error_code="automatizacion.programacion_no_valida",
        ) from None
    return cron
