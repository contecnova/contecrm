"""Entornos de pruebas con datos del cliente (CRM-07.02.01.02).

Un entorno de pruebas sin datos parecidos a los de verdad no sirve: las pruebas
pasan, y luego en producción falla el cliente que tiene ocho direcciones, la
oportunidad de tres años o el nombre con una comilla. Por eso se pide copiar
producción a pruebas.

Y ahí está el problema: **copiar producción a pruebas es sacar los datos
personales de tus clientes de donde están protegidos y ponerlos donde entra todo
el mundo**. A pruebas tienen acceso el consultor externo, el becario y el proveedor
que está integrando algo; no tienen las mismas reglas, ni el mismo cifrado, ni el
mismo control de acceso. La mayoría de las filtraciones de un CRM no salen de
producción: salen de una copia.

Las decisiones:

**La anonimización no es opcional cuando el destino no es producción.** Se puede
desactivar, sí — pidiéndolo expresamente, con un motivo y dejándolo escrito. Que
sea una casilla marcada por defecto es lo que hace que nadie la mire.

**Se anonimiza de forma consistente.** Si «Ana Pérez» se convierte en «Laura Gómez»
en una tabla y en otra cosa en otra, el entorno deja de servir para probar nada que
cruce datos. El mismo valor original da siempre el mismo valor falso dentro del
mismo entorno, y distinto entre entornos.

**Una copia parcial es mejor que una completa.** No por espacio: por riesgo. Con el
5 % de los clientes se prueba igual de bien y hay veinte veces menos que proteger.

**Y un sandbox caduca.** El que se creó para una migración hace año y medio sigue
ahí con los datos de entonces, sin actualizaciones de seguridad y sin que nadie
recuerde quién tiene acceso.
"""

from __future__ import annotations

import hashlib
from datetime import date, timedelta
from typing import Any
from uuid import UUID

from crmcore.errors import ErrorValidacion, Prohibido
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Para qué se crea un entorno. De aquí sale cuánto puede durar y qué se puede
# copiar: un sandbox de formación no necesita datos reales de nadie.
PROPOSITOS = {
    "desarrollo": 90,
    "pruebas": 60,
    "formacion": 180,
    "migracion": 30,
    "soporte": 15,
}

# Qué se hace con cada tipo de dato personal al copiar. `tal_cual` existe para
# poder decir que no se usa, y para que cuando se use quede escrito quién lo pidió.
TRATOS = ("anonimizar", "seudonimizar", "vaciar", "tal_cual")

# Campos que no se copian nunca, ni siquiera anonimizados. No es exceso de celo:
# un token válido en un entorno de pruebas es una puerta abierta a producción.
NUNCA_SE_COPIAN = {
    "credenciales": "Un token copiado a pruebas es una puerta abierta a producción",
    "claves_api": "Lo mismo, y además suelen tener más permisos de los que parece",
    "secretos_de_webhook": "Permiten falsificar eventos contra el sistema del cliente",
    "tokens_de_suite": "Darían acceso al correo real de personas reales desde pruebas",
    "firmas_electronicas": "Son prueba legal: una copia en pruebas la debilita",
}


def _hoy(db: Any = None) -> date:
    """El día de hoy **donde está el cliente**, si hay sesión con la que saberlo.

    Sin sesión cae a UTC, que es lo que hacía antes: no empeora nada y deja
    claro dónde falta el dato. Quien la tenga a mano está obligado a pasarla —
    hay un gate que lo mira—, porque entre medianoche y las dos de la mañana en
    Madrid la respuesta sin sesión es **la de ayer**.
    """
    from crmcore.fechas import hoy as _hoy_del_cliente

    return _hoy_del_cliente(db)


def _falsear(valor: str, semilla: str) -> str:
    """Valor falso **estable dentro del entorno y distinto entre entornos**.

    Estable, porque si «Ana Pérez» sale distinta en dos tablas el entorno no sirve
    para probar nada que cruce datos. Y distinta entre entornos, porque si fuera
    igual en todos, cruzando dos entornos se podría deshacer la anonimización.
    """
    return hashlib.sha256(f"{semilla}:{valor}".encode()).hexdigest()[:16]


def plan_de_copia(
    *,
    proposito: str,
    porcentaje: int,
    anonimizar: bool,
    motivo_sin_anonimizar: str = "",
    pedido_por: UUID | None = None,
) -> dict[str, Any]:
    """Prepara la copia a un entorno que no es producción.

    **Copiar sin anonimizar exige pedirlo y explicarlo.** Que sea una casilla
    marcada por defecto es lo que hace que nadie la mire: a pruebas entran el
    consultor externo, el becario y el proveedor que está integrando algo, y no hay
    ni el mismo cifrado ni el mismo control de acceso.

    Y se recomienda copia **parcial**, no por espacio sino por riesgo: con el 5 %
    de los clientes se prueba igual de bien y hay veinte veces menos que proteger.
    """
    if proposito not in PROPOSITOS:
        raise ErrorValidacion(
            f"Propósito «{proposito}» desconocido",
            error_code="sandbox.proposito_invalido",
            detalle={"admitidos": sorted(PROPOSITOS)},
        )
    if not 1 <= porcentaje <= 100:
        raise ErrorValidacion(
            "El porcentaje de copia va de 1 a 100", error_code="sandbox.porcentaje_invalido"
        )
    if not anonimizar:
        if not motivo_sin_anonimizar.strip() or pedido_por is None:
            raise Prohibido(
                "Copiar datos personales sin anonimizar a un entorno que no es "
                "producción exige pedirlo expresamente, con un motivo y con nombre. La "
                "mayoría de las filtraciones de un CRM no salen de producción: salen de "
                "una copia.",
                error_code="sandbox.sin_anonimizar_sin_motivo",
            )
        logger.warning(
            "sandbox.copia_sin_anonimizar",
            extra={"proposito": proposito, "pedido_por": str(pedido_por)},
        )

    return {
        "proposito": proposito,
        "porcentaje": porcentaje,
        "anonimiza": anonimizar,
        "caduca_en_dias": PROPOSITOS[proposito],
        "no_se_copian": [{"que": k, "porque": v} for k, v in NUNCA_SE_COPIAN.items()],
        "aviso": (
            ""
            if porcentaje <= 20
            else f"Se va a copiar el {porcentaje} % de los datos. Con el 5 % se prueba "
            "igual de bien y hay veinte veces menos que proteger: la copia parcial no es "
            "por espacio, es por riesgo."
        ),
        "queda_escrito": not anonimizar,
    }


def anonimizar_fila(
    *, fila: dict[str, Any], reglas: dict[str, str], semilla: str
) -> dict[str, Any]:
    """Aplica la anonimización a una fila, campo a campo.

    **Consistente dentro del entorno**: el mismo valor original da siempre el mismo
    valor falso, así que una búsqueda por cliente sigue devolviendo sus
    oportunidades y sus casos. Sin eso, el entorno no sirve para probar nada que
    cruce datos, que es casi todo lo que se prueba.

    Y un campo con regla desconocida **no se copia tal cual**: se vacía. El
    silencio por defecto tiene que ser el seguro, no el cómodo.
    """
    salida: dict[str, Any] = {}
    avisos: list[str] = []
    for campo, valor in fila.items():
        regla = reglas.get(campo)
        if regla is None:
            salida[campo] = valor
            continue
        if regla not in TRATOS:
            salida[campo] = None
            avisos.append(
                f"«{campo}» tiene una regla desconocida («{regla}») y se ha vaciado: por "
                "defecto se protege, no se copia."
            )
            continue
        if valor in (None, ""):
            salida[campo] = valor
        elif regla == "vaciar":
            salida[campo] = None
        elif regla == "tal_cual":
            salida[campo] = valor
        else:
            salida[campo] = _falsear(str(valor), semilla)

    return {"fila": salida, "avisos": avisos}


def comprobar_reglas(*, campos_personales: list[str], reglas: dict[str, str]) -> dict[str, Any]:
    """Comprueba que toda columna personal tiene decidido qué hacer con ella.

    Es la comprobación que evita el fallo típico: se anonimizan los nombres y los
    correos —los que se ven— y se olvidan el teléfono de contacto de una tabla
    secundaria, el campo personalizado que alguien creó y el texto libre de una
    nota, donde está el nombre completo del cliente escrito a mano.
    """
    sin_regla = sorted(c for c in campos_personales if c not in reglas)
    tal_cual = sorted(c for c, r in reglas.items() if r == "tal_cual")
    return {
        "valido": not sin_regla,
        "sin_regla": sin_regla,
        "se_copian_tal_cual": tal_cual,
        "porque": (
            f"{len(sin_regla)} columnas personales no dicen qué hacer con ellas. Es el "
            "fallo típico: se anonimiza lo que se ve —nombres y correos— y se olvidan el "
            "teléfono de una tabla secundaria y el nombre escrito a mano en una nota."
            if sin_regla
            else "Todas las columnas personales tienen decidido su tratamiento."
        ),
        "aviso": (
            ""
            if not tal_cual
            else f"{len(tal_cual)} columnas se copian tal cual. Queda escrito: con el "
            "tiempo, nadie recuerda qué había en ese entorno."
        ),
    }


def caducados(*, sandboxes: list[dict[str, Any]], hoy: date | None = None) -> dict[str, Any]:
    """Qué entornos hay que refrescar o apagar.

    El sandbox que se creó para una migración hace año y medio sigue ahí con los
    datos de entonces, sin actualizaciones y sin que nadie recuerde quién tiene
    acceso. No es una molestia de orden: es una copia de datos de clientes viviendo
    en un sitio del que ya nadie se acuerda.
    """
    momento = hoy or _hoy()
    vencidos, por_vencer = [], []
    for caja in sandboxes:
        creado = caja.get("creado")
        if isinstance(creado, str):
            creado = date.fromisoformat(creado)
        if not isinstance(creado, date):
            continue
        dias_max = PROPOSITOS.get(str(caja.get("proposito")), 60)
        vence = creado + timedelta(days=dias_max)
        entrada = {
            "nombre": caja.get("nombre"),
            "proposito": caja.get("proposito"),
            "vence": vence.isoformat(),
            "con_datos_reales": bool(caja.get("con_datos_reales")),
        }
        if vence < momento:
            vencidos.append({**entrada, "dias_vencido": (momento - vence).days})
        elif (vence - momento).days <= 7:
            por_vencer.append(entrada)

    con_datos = [v for v in vencidos if v["con_datos_reales"]]
    return {
        "vencidos": vencidos,
        "por_vencer": por_vencer,
        "urgentes": con_datos,
        "que_hacer": (
            "No hay entornos vencidos."
            if not vencidos
            else (
                f"{len(con_datos)} entornos vencidos tienen datos reales sin anonimizar. "
                "Eso es una copia de datos de clientes en un sitio del que ya nadie se "
                "acuerda: se refresca o se apaga, y hoy."
                if con_datos
                else f"{len(vencidos)} entornos vencidos: refrescar o apagar."
            )
        ),
    }
