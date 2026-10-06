"""Lo que esta instalación exige cifrar hacia dentro (`CRM-00.01.05`).

`BUS_TLS` y `CACHE_TLS` existían, estaban en `.env.example`, estaban en el
manual de referencia y **no los leía nadie** (medido el 06-10-2026). Quien ponía
`BUS_TLS=true` creía haber cerrado el tramo hacia el bus, y los eventos seguían
viajando por donde dijera la URL — en claro si la URL era `redis://`.

**Lo que decide la conexión sigue siendo la URL.** Esto no la reescribe: una
URL reescrita a espaldas de quien la puso lleva a un fallo de conexión que nadie
relaciona con un ajuste de otra sección. Lo que hace es **exigir**: si se ha
declarado que ese tramo va cifrado y la URL no lo está, el arranque se niega y
lo dice. Es el mismo criterio que `TRUST_PROXY_HEADERS` con `TRUSTED_PROXIES`.

Negarse y no avisar: un aviso en el log de arranque lo lee quien mira el log de
arranque, y un tramo de bus en claro en una instalación que se creía cifrada es
exactamente de lo que nadie se entera hasta la auditoría.

Los esquemas van por **tabla y no por producto**: `rediss`, `tls`, `amqps` y los
demás son del protocolo, no de la casa que lo sirve.
"""

from __future__ import annotations

from crmcore.errors import ErrorValidacion

# Esquema de URL → si ese esquema va cifrado. Lo que no esté aquí se trata como
# desconocido y **no se da por cifrado**: dar por bueno lo que no se reconoce es
# cómo una comprobación de seguridad deja de comprobar.
ESQUEMAS_CIFRADOS = frozenset({"rediss", "tls", "nats+tls", "amqps", "https", "wss"})
ESQUEMAS_EN_CLARO = frozenset({"redis", "nats", "amqp", "http", "ws"})


def esquema_de(url: str) -> str:
    return str(url or "").split("://", 1)[0].lower()


def va_cifrada(url: str) -> bool:
    return esquema_de(url) in ESQUEMAS_CIFRADOS


def exigir(url: str, *, tramo: str, ajuste: str, exigido: bool) -> None:
    """Corta el arranque si el tramo se declaró cifrado y la URL no lo está.

    Con el ajuste apagado no se comprueba nada: declarar que un tramo va en
    claro es una decisión legítima —el bus en la misma red privada— y
    convertirla en un aviso en cada arranque enseña a ignorar los avisos.
    """
    if not exigido or not url:
        return
    if va_cifrada(url):
        return

    esquema = esquema_de(url) or "(sin esquema)"
    conocido = esquema in ESQUEMAS_EN_CLARO
    raise ErrorValidacion(
        f"{ajuste} dice que el tramo hacia {tramo} va cifrado, y su URL empieza "
        f"por «{esquema}://», que "
        + ("no lo está." if conocido else "no se reconoce como cifrado.")
        + f" Cambia la URL a un esquema cifrado ({', '.join(sorted(ESQUEMAS_CIFRADOS))}) "
        f"o pon {ajuste}=false si de verdad ese tramo va en claro.",
        error_code="red.tls_exigido_sin_cifrar",
        detalle={"tramo": tramo, "esquema": esquema},
    )
