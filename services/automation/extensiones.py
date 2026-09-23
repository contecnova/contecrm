"""Código del tenant: sandbox, versiones, observabilidad y firma
(CRM-00.04.02.01, .05, .06, .07).

Dejar que un cliente ejecute su código dentro del CRM es la diferencia entre un
producto configurable y uno programable, y también la forma más rápida de que una
implantación tumbe a las demás. El bucle infinito de un cliente no es un problema
suyo: es un problema de todos los que comparten ese worker.

Las decisiones:

**Los límites son del sandbox, no del código.** Pedirle al cliente que su función
no tarde más de dos segundos es pedirle que se porte bien; cortarla a los dos
segundos es que no pueda. Lo primero funciona hasta que alguien mete un `while`.

**El coste se atribuye a quien lo gasta.** Sin eso, el tiempo de cómputo de un
cliente lo paga el despliegue entero y nadie sabe de quién es la factura — que es
justo la conversación que hay que poder tener con el cliente que se pasa.

**Una versión nueva no reemplaza a la anterior: convive.** Desplegar pisando deja
sin sitio a lo que está en ejecución, y volver atrás exige tener la anterior
entera y viva.

**Los errores de una extensión son del tenant, y sus logs también.** Mezclarlos
con los del producto hace que un fallo suyo parezca nuestro, y al revés — y en la
guardia de las tres de la mañana esa diferencia es todo.

**Una extensión de terceros se firma y se revisa antes de instalarse.** Sin firma,
«instalar una extensión» es «ejecutar código de un desconocido dentro de la base
de tus clientes».
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.errors import Conflicto, ErrorValidacion, Prohibido
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Los topes del sandbox. Son del entorno y no del código: pedirle al cliente que
# su función no tarde es pedirle que se porte bien, y eso funciona hasta que
# alguien mete un bucle.
LIMITES = {
    "milisegundos": 2_000,
    "memoria_mb": 128,
    "llamadas_salientes": 5,
    "escrituras": 100,
}

# Lo que una extensión NO puede hacer, pase lo que pase. No es una lista de
# permisos: es lo que ni siquiera se le ofrece, porque ofrecerlo y comprobarlo
# después deja la comprobación como única barrera.
PROHIBIDO = {
    "leer_otro_tenant": "Rompería el aislamiento, que es lo único que no se negocia",
    "ejecutar_sql": "Se saltaría el metamodelo, los permisos y la auditoría a la vez",
    "leer_credenciales": "Las del tenant son suyas; las del despliegue no son de nadie",
    "red_sin_declarar": "Una llamada saliente no declarada es una fuga que nadie ve",
}

ESTADOS = ("borrador", "revisando", "firmada", "activa", "retirada", "rechazada")


def comprobar_limites(*, consumo: dict[str, Any]) -> dict[str, Any]:
    """Si una ejecución se ha pasado de lo que el sandbox permite.

    Se comprueba **durante y después**, no solo antes: lo que hay que cortar es
    la ejecución que ya se está pasando, y lo que hay que contar es lo que
    consumió la que terminó.
    """
    excedidos = [
        {
            "limite": clave,
            "tope": tope,
            "gastado": int(consumo.get(clave) or 0),
        }
        for clave, tope in LIMITES.items()
        if int(consumo.get(clave) or 0) > tope
    ]
    return {
        "dentro": not excedidos,
        "excedidos": excedidos,
        "que_pasa": (
            "La ejecución cabe en el sandbox."
            if not excedidos
            else "Se corta. No es un aviso: el bucle infinito de un cliente no es un "
            "problema suyo, es un problema de todos los que comparten ese worker."
        ),
    }


def exigir_permitido(*, capacidades: list[str]) -> None:
    """Rechaza una extensión que pide algo que no se ofrece.

    Se comprueba **al declararla**, no al ejecutarla. Aceptarla y bloquearla
    después dejaría la comprobación en tiempo de ejecución como única barrera, y
    esa se salta el día que alguien añade un camino nuevo.
    """
    pedidas = sorted(set(capacidades) & set(PROHIBIDO))
    if pedidas:
        raise Prohibido(
            "La extensión pide capacidades que no se ofrecen a ninguna: "
            + ", ".join(f"{c} ({PROHIBIDO[c]})" for c in pedidas),
            error_code="extension.capacidad_prohibida",
            detalle={"pedidas": pedidas},
        )


def huella_de(codigo: bytes) -> str:
    """SHA-256 del código. Es lo que se firma y lo que se compara al instalar."""
    return hashlib.sha256(codigo).hexdigest()


def publicar_version(
    *,
    clave: str,
    codigo: bytes,
    version: int,
    dependencias: dict[str, str],
    capacidades: list[str],
    versiones_vivas: list[int],
) -> dict[str, Any]:
    """Publica una versión nueva **sin pisar la anterior** (CRM-00.04.02.05).

    Conviven a propósito: desplegar pisando deja sin sitio a lo que está
    ejecutándose en ese momento, y volver atrás exige tener la anterior entera y
    viva — no un diff que alguien tenga que aplicar con prisa.

    Las **dependencias van fijadas**. Una extensión que declara «la última
    versión» de algo funciona hasta que esa librería publica un cambio, y
    entonces falla en producción sin que nadie haya tocado nada — el peor tipo de
    fallo, porque no hay ningún cambio que revisar.
    """
    exigir_permitido(capacidades=capacidades)
    if version in versiones_vivas:
        raise Conflicto(
            f"La versión {version} de «{clave}» ya existe. Las versiones no se "
            "reescriben: volver atrás exige tener la anterior entera.",
            error_code="extension.version_repetida",
        )
    sin_fijar = sorted(
        nombre
        for nombre, rango in (dependencias or {}).items()
        if not rango or any(c in str(rango) for c in ("*", "^", "~", "latest"))
    )
    if sin_fijar:
        raise ErrorValidacion(
            f"Estas dependencias no están fijadas: {sin_fijar}. Una extensión que "
            "declara «la última versión» falla el día que esa librería publique un "
            "cambio, sin que nadie haya tocado nada — y entonces no hay ningún "
            "cambio que revisar.",
            error_code="extension.dependencia_sin_fijar",
            detalle={"sin_fijar": sin_fijar},
        )

    return {
        "clave": clave,
        "version": version,
        "huella": huella_de(codigo),
        "dependencias": dict(dependencias),
        "capacidades": sorted(set(capacidades)),
        "convive_con": sorted(versiones_vivas),
        "estado": "borrador",
        "porque_convive": (
            "Desplegar pisando deja sin sitio a lo que está ejecutándose, y volver "
            "atrás exige tener la anterior viva."
        ),
    }


def revisar_firma(
    *,
    codigo: bytes,
    huella_firmada: str,
    firmante: str,
    firmantes_de_confianza: list[str],
    revisada_por: UUID | None = None,
) -> dict[str, Any]:
    """Comprueba la firma de una extensión de terceros (CRM-00.04.02.07).

    Sin firma, «instalar una extensión» es «ejecutar código de un desconocido
    dentro de la base de tus clientes». Con firma pero sin revisión es lo mismo
    con un sello: la firma dice **quién** lo escribió, no que sea seguro.

    Por eso se exigen las dos cosas, y la revisión es de una persona: automatizar
    «¿este código es seguro?» es el problema que nadie ha resuelto.
    """
    actual = huella_de(codigo)
    if actual != (huella_firmada or "").strip().lower():
        return {
            "instalable": False,
            "porque": (
                "El código no coincide con lo que se firmó. Puede ser una "
                "manipulación o un empaquetado mal hecho; en los dos casos, lo que "
                "se instalaría no es lo que alguien revisó."
            ),
        }
    if firmante not in firmantes_de_confianza:
        return {
            "instalable": False,
            "porque": (
                f"«{firmante}» no está en la lista de firmantes de confianza de este "
                "tenant. La firma dice quién lo escribió, y eso solo sirve si alguien "
                "ha decidido que ese quién le vale."
            ),
        }
    if revisada_por is None:
        return {
            "instalable": False,
            "porque": (
                "Firmada pero sin revisar. La firma dice quién lo escribió, no que "
                "sea seguro: automatizar «¿este código es seguro?» es el problema que "
                "nadie ha resuelto, así que lo mira una persona."
            ),
        }
    return {
        "instalable": True,
        "huella": actual,
        "firmante": firmante,
        "revisada_por": str(revisada_por),
        "porque": "Firma válida, firmante de confianza y revisión hecha por una persona.",
    }


def observabilidad(
    *,
    clave: str,
    ejecuciones: list[dict[str, Any]],
    coste_por_segundo: float = 0.0,
) -> dict[str, Any]:
    """Qué hace esta extensión, cuánto falla y cuánto cuesta (CRM-00.04.02.06).

    **El coste se atribuye a quien lo gasta.** Sin eso, el tiempo de cómputo de
    un cliente lo paga el despliegue entero y nadie sabe de quién es la factura —
    que es justo la conversación que hay que poder tener con el cliente que se
    pasa, y que sin números no se puede tener.

    Y los errores **se separan de los del producto**. Un fallo de la extensión de
    un cliente que aparece en el panel del producto hace que la guardia de las
    tres de la mañana empiece a mirar donde no es.
    """
    total = len(ejecuciones)
    if not total:
        return {
            "extension": clave,
            "medible": False,
            "porque": (
                "No consta ninguna ejecución. Eso no significa que la extensión vaya "
                "bien: significa que no se ha ejecutado, o que no se está midiendo."
            ),
        }

    fallidas = [e for e in ejecuciones if not e.get("ok")]
    cortadas = [e for e in ejecuciones if e.get("cortada_por_limite")]
    milisegundos = sum(int(e.get("milisegundos") or 0) for e in ejecuciones)
    lentas = sorted(ejecuciones, key=lambda e: -int(e.get("milisegundos") or 0))[:5]

    return {
        "extension": clave,
        "medible": True,
        "ejecuciones": total,
        "fallidas": len(fallidas),
        # Las cortadas van aparte de las fallidas: una que falla tiene un error
        # que arreglar, y una que se corta tiene un diseño que revisar.
        "cortadas_por_limite": len(cortadas),
        "tiempo_total_ms": milisegundos,
        "coste_atribuido": round(milisegundos / 1000 * coste_por_segundo, 4),
        "las_mas_lentas": [
            {"cuando": e.get("cuando"), "ms": e.get("milisegundos"), "entrada": e.get("entrada")}
            for e in lentas
        ],
        "errores_son_del_tenant": True,
        "porque": (
            "Los errores y el coste de una extensión son de quien la escribió. "
            "Mezclarlos con los del producto hace que un fallo suyo parezca nuestro "
            "y al revés, y en una guardia esa diferencia es todo."
        ),
        "que_mirar": (
            f"{len(cortadas)} ejecuciones cortadas por límite: no es un error del "
            "sandbox, es una extensión que pide más de lo que se le da."
            if cortadas
            else ""
        ),
    }


def resumen_de_ejecucion(
    *, clave: str, version: int, entrada: dict[str, Any], consumo: dict[str, Any]
) -> dict[str, Any]:
    """Lo que queda anotado de cada ejecución.

    Con la **entrada** dentro: una extensión que falla con un registro concreto y
    no guarda cuál obliga a reproducirlo a ciegas, y eso son horas. Lo que no se
    guarda es la salida, porque puede llevar el dato entero y duplicarlo en los
    registros es multiplicar lo que hay que proteger.
    """
    limites = comprobar_limites(consumo=consumo)
    return {
        "extension": clave,
        "version": version,
        "cuando": datetime.now(timezone.utc).isoformat(),
        "entrada": entrada,
        "consumo": dict(consumo),
        "ok": limites["dentro"],
        "cortada_por_limite": not limites["dentro"],
        "excedidos": limites["excedidos"],
        "salida_no_se_guarda": (
            "La salida puede llevar el registro entero: guardarla duplicaría el dato "
            "que hay que proteger en una tabla de logs."
        ),
    }
