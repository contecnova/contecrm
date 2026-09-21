"""Políticas de acceso contextual: IP, dispositivo y horario (CRM-00.05.01.09).

El ABAC ya decide por atributos del usuario y del registro. Esto añade los del
**momento**: desde dónde entra, con qué, y a qué hora. Son los que cambian entre
una sesión legítima y la misma credencial usada por otro.

Lo importante no es la lista de señales, es qué se hace con ellas. Dos
decisiones:

**Se comprueba en cada petición, no al entrar.** Comprobarlo solo en el login
deja la sesión abierta cuando las condiciones dejan de cumplirse — y el caso que
se quiere cubrir es exactamente ese: la credencial que sigue viva y se usa desde
otro sitio.

**Ante una señal que no se puede leer, no se bloquea.** Una IP que no llega
porque hay un proxy mal configurado delante dejaría fuera a toda la plantilla, y
eso es una caída con otro nombre. Lo que falta se registra y la regla que
dependía de ello **no aplica**: en acceso contextual, la señal ausente no es
motivo de bloqueo, es motivo de aviso.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from datetime import datetime, time, timezone

from crmcore.errors import Prohibido
from crmcore.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Contexto:
    """Lo que se sabe de esta petición. Todo opcional: puede no llegar."""

    ip: str = ""
    dispositivo: str = ""
    pais: str = ""
    momento: datetime | None = None

    def hora_local(self, huso_offset_h: int = 0) -> time:
        base = self.momento or datetime.now(timezone.utc)
        hora = (base.hour + huso_offset_h) % 24
        return time(hour=hora, minute=base.minute)


@dataclass(frozen=True, slots=True)
class ReglaContextual:
    """Una condición sobre el contexto de la petición.

    `redes` son CIDR; `paises`, códigos ISO; `horario`, dos horas en el huso del
    tenant. Vacío significa «no se comprueba», no «ninguno»: una regla que
    bloquea porque la lista está vacía es la forma más rápida de dejar fuera a
    todo el mundo el día que alguien la crea sin rellenarla.
    """

    nombre: str
    redes: tuple[str, ...] = ()
    paises: tuple[str, ...] = ()
    desde_hora: int | None = None
    hasta_hora: int | None = None
    dispositivos: tuple[str, ...] = ()
    huso_offset_h: int = 0
    activa: bool = True


def evaluar(regla: ReglaContextual, contexto: Contexto) -> tuple[bool, str]:
    """Si esta petición cumple la regla, y por qué no si no la cumple."""
    if not regla.activa:
        return True, ""

    if regla.redes:
        if not contexto.ip:
            # Señal ausente: se avisa y NO se bloquea. Una IP que no llega
            # porque hay un proxy mal configurado delante dejaría fuera a toda
            # la plantilla, y eso es una caída con otro nombre.
            logger.warning("acceso.sin_ip", regla=regla.nombre)
        elif not _en_alguna_red(contexto.ip, regla.redes):
            return False, f"la dirección {contexto.ip} no está en las redes permitidas"

    if regla.paises:
        if not contexto.pais:
            logger.warning("acceso.sin_pais", regla=regla.nombre)
        elif contexto.pais.upper() not in {p.upper() for p in regla.paises}:
            return False, f"el país {contexto.pais} no está permitido"

    if regla.dispositivos:
        if not contexto.dispositivo:
            logger.warning("acceso.sin_dispositivo", regla=regla.nombre)
        elif contexto.dispositivo not in regla.dispositivos:
            return False, f"el dispositivo «{contexto.dispositivo}» no está autorizado"

    if regla.desde_hora is not None and regla.hasta_hora is not None:
        hora = contexto.hora_local(regla.huso_offset_h).hour
        # Se admite la franja que cruza medianoche —de 22 a 6— porque el turno
        # de noche existe y escribirlo al revés es el error más común al
        # configurar esto.
        dentro = (
            regla.desde_hora <= hora < regla.hasta_hora
            if regla.desde_hora <= regla.hasta_hora
            else hora >= regla.desde_hora or hora < regla.hasta_hora
        )
        if not dentro:
            return False, f"son las {hora}:00 y el acceso está limitado a esa franja"

    return True, ""


def exigir(reglas: list[ReglaContextual], contexto: Contexto) -> None:
    """Todas las reglas activas tienen que cumplirse.

    Conjunción y no disyunción, igual que en el ABAC: con disyunción, añadir una
    regla permisiva anularía en silencio a una restrictiva ya existente, y nadie
    revisa las reglas viejas al crear una nueva.
    """
    for regla in reglas:
        cumple, motivo = evaluar(regla, contexto)
        if not cumple:
            logger.warning(
                "acceso.contextual_denegado",
                regla=regla.nombre,
                motivo=motivo,
                ip=contexto.ip,
            )
            raise Prohibido(
                "Una política de acceso lo impide desde aquí o a esta hora",
                error_code="acceso.contexto",
                detalle={"regla": regla.nombre, "porque": motivo},
            )


def _en_alguna_red(ip: str, redes: tuple[str, ...]) -> bool:
    """Si la IP cae en alguna de las redes declaradas.

    Una red mal escrita **no** deja pasar: se ignora esa entrada y se registra.
    Tratarla como comodín convertiría un error de tecleo en una lista de
    permitidos vacía, que deja entrar a cualquiera.
    """
    try:
        direccion = ipaddress.ip_address(ip)
    except ValueError:
        logger.warning("acceso.ip_ilegible", ip=ip[:40])
        return False
    for red in redes:
        try:
            if direccion in ipaddress.ip_network(red, strict=False):
                return True
        except ValueError:
            logger.error("acceso.red_mal_escrita", red=red[:40])
    return False
