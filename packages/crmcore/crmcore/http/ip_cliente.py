"""La IP de quien llama, cuando delante hay proxies (SEC-8, auditoría 13-11-2026).

Había tres copias de esto —la dependencia HTTP, el limitador y el gateway— y las
tres hacían lo mismo mal: con `TRUST_PROXY_HEADERS` activo cogían el **primer**
valor de `X-Forwarded-For`. Ese valor lo escribe el cliente: nginx no lo
sustituye, le **añade** a la derecha la IP real (`$proxy_add_x_forwarded_for`).
Así que mandar `X-Forwarded-For: <una IP permitida>` bastaba para saltarse el
límite por IP, la lista de redes de una clave de API y el acceso contextual, y
para firmar la auditoría con una dirección inventada. Y `TRUSTED_PROXIES` se
declaraba, se exigía en producción y no lo leía nadie.

La regla correcta es la de siempre:

  1. Si quien nos habla (el par TCP) **no** es un proxy de confianza, su
     dirección es la del cliente y la cabecera no se mira: la podría haber
     escrito él.
  2. Si lo es, se recorre `X-Forwarded-For` **de derecha a izquierda** y la
     primera dirección que no sea de un proxy de confianza es la del cliente.
     Lo que hay a su izquierda lo escribió el cliente y no vale nada.

`TRUSTED_PROXIES` admite IPs y redes (`10.0.0.0/8`), separadas por comas. Sin
ninguna declarada no se confía en nadie, aunque `TRUST_PROXY_HEADERS` esté
activo: en producción esa combinación ya impide arrancar.
"""

from __future__ import annotations

import ipaddress
from functools import lru_cache

Red = ipaddress.IPv4Network | ipaddress.IPv6Network


@lru_cache(maxsize=8)
def _redes(declaradas: str) -> tuple[Red, ...]:
    """Las redes de confianza, parseadas una vez por valor del ajuste."""
    redes: list[Red] = []
    for trozo in declaradas.split(","):
        trozo = trozo.strip()
        if not trozo:
            continue
        try:
            redes.append(ipaddress.ip_network(trozo, strict=False))
        except ValueError:
            # Un valor mal escrito no amplía la confianza: se ignora. El
            # arranque ya avisa si la lista queda vacía.
            continue
    return tuple(redes)


def _de_confianza(ip: str, redes: tuple[Red, ...]) -> bool:
    try:
        direccion = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(direccion in red for red in redes)


def ip_del_cliente(par: str, reenviada: str) -> str:
    """La IP del cliente a partir del par TCP y de `X-Forwarded-For`.

    `par` es quien abrió la conexión con este proceso; `reenviada`, el valor
    crudo de la cabecera (vacío si no vino).
    """
    from crmcore.config import get_settings

    s = get_settings()
    if not s.trust_proxy_headers or not reenviada:
        return par
    redes = _redes(s.trusted_proxies)
    if not redes or not _de_confianza(par, redes):
        return par
    saltos = [x.strip() for x in reenviada.split(",") if x.strip()]
    for salto in reversed(saltos):
        if not _de_confianza(salto, redes):
            return salto
    # Toda la cadena es de proxies propios: la más lejana es lo más parecido
    # al cliente que hay.
    return saltos[0] if saltos else par
