"""Lista de IP por credencial, no solo por usuario (CRM-00.02.04.04).

El acceso contextual acota **a una persona**: desde dónde entra alguien. Esto
acota **a una llave**: desde dónde puede usarse esta clave de API concreta.

La diferencia no es de matiz. Una clave de integración vive en un servidor que
no se mueve nunca, así que su lista de IP puede ser de una sola dirección — y
eso convierte una clave robada en una clave inútil fuera de ese servidor. La
misma restricción aplicada a la persona sería inservible, porque las personas
se mueven.

Y por eso la lista es **de la credencial y no del tenant**: un tenant con veinte
integraciones en veinte sitios tendría que permitir las veinte direcciones a
todas, con lo que cada clave valdría desde donde valen todas las demás.
"""

from __future__ import annotations

import ipaddress
from typing import Any

from crmcore.errors import Prohibido
from crmcore.logging import get_logger

logger = get_logger(__name__)


def comprobar(ip: str, permitidas: list[str] | None, *, credencial: str = "") -> None:
    """Corta si la IP no está en la lista de esta credencial.

    Lista vacía o ausente significa **sin restricción**, no «ninguna». Es la
    decisión contraria a la de las políticas ABAC, y el motivo es distinto: aquí
    la lista la rellena quien crea la clave, y una clave recién creada sin lista
    tiene que funcionar o nadie podría empezar a usarla.
    """
    if not permitidas:
        return

    if not ip:
        # Sin IP no se puede comprobar. Aquí SÍ se corta, al revés que en el
        # acceso contextual de personas: una credencial de máquina con lista
        # declarada se usa desde un sitio conocido, y si la dirección no llega
        # es que algo está delante haciendo de intermediario — que es
        # exactamente contra lo que protege la lista.
        logger.error("credencial.sin_ip", credencial=credencial[:16])
        raise Prohibido(
            "Esta credencial exige una dirección de origen conocida y no ha llegado ninguna",
            error_code="credencial.sin_ip",
        )

    try:
        direccion = ipaddress.ip_address(ip)
    except ValueError:
        logger.error("credencial.ip_ilegible", ip=ip[:40])
        raise Prohibido(
            "La dirección de origen no se ha podido leer", error_code="credencial.ip_ilegible"
        ) from None

    for red in permitidas:
        try:
            if direccion in ipaddress.ip_network(red, strict=False):
                return
        except ValueError:
            # Una entrada mal escrita se ignora y se registra; no se trata como
            # comodín. Tratarla así convertiría un error de tecleo en una lista
            # vacía, que deja entrar a cualquiera con la clave.
            logger.error("credencial.red_mal_escrita", red=str(red)[:40])

    logger.warning("credencial.ip_no_permitida", ip=ip, credencial=credencial[:16])
    raise Prohibido(
        f"La dirección {ip} no está entre las permitidas para esta credencial",
        error_code="credencial.ip_no_permitida",
    )


def validar_lista(redes: list[str]) -> list[str]:
    """Comprueba la lista AL GUARDARLA y devuelve los problemas.

    Al guardarla y no al usarla: una red mal escrita descubierta en la primera
    llamada deja la integración caída y a nadie mirando, porque quien la
    configuró ya se fue.
    """
    problemas: list[str] = []
    for red in redes:
        try:
            ipaddress.ip_network(red, strict=False)
        except ValueError:
            problemas.append(f"«{red}» no es una dirección ni una red válida")
    # Avisar de `0.0.0.0/0` es más útil que prohibirlo: hay despliegues donde es
    # legítimo durante una migración, y prohibirlo llevaría a desactivar la
    # lista entera —que es peor—.
    if any(r.strip() in ("0.0.0.0/0", "::/0") for r in redes):
        problemas.append(
            "La lista incluye «toda internet», con lo que no restringe nada: "
            "déjala vacía si es lo que quieres, para que se vea"
        )
    return problemas


def estado(permitidas: list[str] | None) -> dict[str, Any]:
    """Qué protege esta lista, para enseñarlo en la ficha de la credencial."""
    if not permitidas:
        return {"restringida": False, "aviso": "Esta clave funciona desde cualquier sitio"}
    return {"restringida": True, "redes": list(permitidas), "aviso": ""}
