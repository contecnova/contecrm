"""El contrato con el proveedor y su alcance comercial
(CRM-09.01.01.07, CRM-09.01.01.09).

Vive en `sales` y no en `party` porque las dos cosas deciden **qué se puede
vender**: si un contrato vence en marzo, lo que se firme en febrero con entrega en
abril no está cubierto por nada; y si un proveedor no cubre Canarias, la oferta a
un cliente de Las Palmas es una promesa sin nadie detrás.

Las decisiones:

**Un contrato de proveedor avisa por lo que hay vendido, no por su fecha.** Un
aviso a treinta días de la renovación es lo normal y no basta: lo que importa es
si hay compromisos con clientes **más allá** de esa fecha, porque esos son los que
se quedan sin cobertura.

**El preaviso de no renovación es una fecha límite real.** Pasada, el contrato se
renueva solo aunque nadie quisiera — y eso se descubre cuando llega la factura.

**Y el alcance se declara en positivo.** Decir dónde llega un proveedor y dar por
hecho el resto es lo que hace que se le encargue algo que no puede hacer: lo que
no está declarado no se puede comprometer.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from crmcore.errors import ErrorValidacion
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Qué puede acotar el alcance de un proveedor. Cerrada porque cada eje se
# comprueba de una forma y con texto libre no se comprueba ninguno.
EJES_DE_ALCANCE = ("categoria", "geografia", "cliente", "canal")


# Cuánto antes de la fecha límite de preaviso se avisa. Un mes: menos no da
# tiempo a negociar nada y la renovación automática se convierte en la decisión.
def _acuerdo_dias_preaviso() -> int:
    """Antes `_acuerdo_dias_preaviso() = 30`.

    Era una constante de módulo. Sale del `.env`, que es donde una instalación
    puede afinarla sin tocar código.
    """
    from crmcore.config import get_settings

    return get_settings().acuerdo_dias_preaviso


def _hoy(db: Any = None) -> date:
    """El día de hoy **donde está el cliente**, si hay sesión con la que saberlo.

    Sin sesión cae a UTC, que es lo que hacía antes: no empeora nada y deja
    claro dónde falta el dato. Quien la tenga a mano está obligado a pasarla —
    hay un gate que lo mira—, porque entre medianoche y las dos de la mañana en
    Madrid la respuesta sin sesión es **la de ayer**.
    """
    from crmcore.fechas import hoy as _hoy_del_cliente

    return _hoy_del_cliente(db)


def estado_del_contrato(
    *,
    vigente_hasta: date | None,
    renovacion_automatica: bool,
    dias_preaviso: int,
    compromisos_con_clientes: list[dict[str, Any]] | None = None,
    hoy: date | None = None,
) -> dict[str, Any]:
    """Qué hay que hacer con este contrato y cuándo, **mirando lo vendido**.

    Un aviso por la fecha de renovación es lo que hace todo el mundo y llega
    tarde: lo que decide si hay un problema es si hay **compromisos con clientes
    más allá del fin del contrato**. Esos son los que se quedan sin nadie detrás,
    y son los que hay que poner encima de la mesa al negociar.

    Y la **fecha límite de preaviso** es una fecha real: pasada, el contrato se
    renueva solo aunque nadie quisiera, y eso se descubre con la factura.
    """
    momento = hoy or _hoy()
    if vigente_hasta is None:
        return {
            "estado": "sin_vigencia_declarada",
            "porque": (
                "El contrato no dice hasta cuándo vale. No es que sea indefinido: es "
                "que nadie lo ha escrito, y el día que el proveedor diga que terminó "
                "no habrá con qué discutirlo."
            ),
            "fiable": False,
        }

    dias = (vigente_hasta - momento).days
    limite_preaviso = vigente_hasta - timedelta(days=max(0, dias_preaviso))
    dias_para_preaviso = (limite_preaviso - momento).days

    descubiertos = [
        c
        for c in (compromisos_con_clientes or [])
        if isinstance(c.get("fecha"), date) and c["fecha"] > vigente_hasta
    ]

    return {
        "estado": "vencido" if dias < 0 else "vigente",
        "dias_para_vencer": dias,
        "limite_preaviso": limite_preaviso.isoformat(),
        "dias_para_el_preaviso": dias_para_preaviso,
        "hay_que_avisar_ya": 0 <= dias_para_preaviso <= _acuerdo_dias_preaviso(),
        "preaviso_pasado": dias_para_preaviso < 0 and renovacion_automatica,
        "compromisos_sin_cobertura": [
            {"referencia": c.get("referencia"), "fecha": c["fecha"].isoformat()}
            for c in descubiertos
        ],
        "porque": (
            f"Hay {len(descubiertos)} compromisos con clientes con fecha posterior al "
            "fin del contrato. Son los que se quedan sin nadie detrás, y son los que "
            "hay que poner sobre la mesa al negociar la renovación."
            if descubiertos
            else "No hay compromisos con clientes más allá del fin del contrato."
        ),
        "aviso": (
            "El plazo de preaviso ya ha pasado y la renovación es automática: este "
            "contrato se renueva solo aunque nadie lo quiera, y eso se descubre con la "
            "factura."
            if dias_para_preaviso < 0 and renovacion_automatica
            else ""
        ),
        "fiable": True,
    }


def declarar_alcance(*, alcance: dict[str, list[str]]) -> dict[str, Any]:
    """Declara qué puede servir un proveedor, **en positivo**.

    Lo que no está declarado no se puede comprometer. Al revés —declarar lo que
    NO puede y dar por hecho el resto— es lo que hace que se le encargue algo que
    no hace: la lista de exclusiones nunca está completa, porque nadie piensa en
    lo que todavía no ha pasado.
    """
    desconocidos = sorted(set(alcance) - set(EJES_DE_ALCANCE))
    if desconocidos:
        raise ErrorValidacion(
            f"Ejes de alcance desconocidos: {', '.join(desconocidos)}",
            error_code="proveedor.eje_invalido",
            detalle={"admitidos": list(EJES_DE_ALCANCE)},
        )
    vacios = sorted(eje for eje, valores in alcance.items() if not valores)
    return {
        "alcance": {eje: sorted(set(v)) for eje, v in alcance.items() if v},
        "ejes_sin_acotar": [e for e in EJES_DE_ALCANCE if e not in alcance or e in vacios],
        "porque": (
            "Un eje sin acotar significa «cualquiera», y eso es una decisión: conviene "
            "que sea deliberada y no el resultado de no haber rellenado el campo."
        ),
    }


def puede_servir(
    *, alcance: dict[str, list[str]], categoria: str, geografia: str, cliente_id: str | None = None
) -> dict[str, Any]:
    """Si este proveedor puede atender este caso concreto, y por qué no.

    El «por qué no» es lo que hace útil la respuesta: quien está montando una
    oferta necesita saber si es por la zona o por el tipo de trabajo, porque en un
    caso busca otro proveedor y en el otro cambia lo que ofrece.
    """
    motivos: list[str] = []
    categorias = alcance.get("categoria") or []
    if categorias and categoria not in categorias:
        motivos.append(f"No cubre la categoría «{categoria}»")
    geografias = alcance.get("geografia") or []
    if geografias and geografia not in geografias:
        motivos.append(
            f"No llega a «{geografia}». Encargárselo igual convierte la oferta en una "
            "promesa sin nadie detrás."
        )
    clientes = alcance.get("cliente") or []
    if clientes and cliente_id and cliente_id not in clientes:
        motivos.append(
            "Está acotado a unos clientes concretos y este no está entre ellos. Suele "
            "ser por un acuerdo de exclusividad, y saltárselo tiene consecuencias "
            "contractuales."
        )

    return {
        "puede": not motivos,
        "motivos": motivos,
        "que_hacer": (
            ""
            if not motivos
            else "Buscar otro proveedor homologado para eso, o cambiar lo que se "
            "ofrece. Comprometerlo y resolverlo después es como se incumple una fecha."
        ),
    }
