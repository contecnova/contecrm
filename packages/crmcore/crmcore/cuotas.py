"""Cuotas por módulo: el tope, el consumo y quién corta.

**Por módulo y no en un tope global**, que es lo que se decidió el 28-09-2026:
cada servicio guarda lo suyo en su esquema y cuenta lo suyo. Tres motivos, y el
tercero es el que lo decidió:

- el alta **no depende de una lectura entre servicios**, que sería cara y se
  caería con el vecino;
- no hay contador global que mantener sincronizado entre trece esquemas;
- y sobre todo, **el mensaje puede decir QUÉ se ha agotado**. Con un tope global,
  «has llegado al límite» no dice si sobran contactos, correos o ficheros.

**Se cuenta, no se lleva contador.** Los adjuntos ya tienen su tamaño, las
entregas su fila y los registros su tabla: sumarlos es verdad por construcción.
Un contador aparte se desincroniza el primer día que algo desaparece por otra
vía —una purga, una baja, un borrado en cascada— y entonces el cliente paga por
lo que no tiene, o se le deja pasar del tope. El día que contar se quede corto,
lo que toca **no es un contador**: es un índice, o un resumen recalculable que se
pueda comprobar contra las filas.

**Y la omisión abre, nunca cierra.** Sin tope declarado, o con tope 0, se deja
pasar. Un despliegue que no ha configurado cuotas no puede quedarse sin poder
trabajar porque a alguien se le olvidara declararlas, y un fallo al declarar una
ruta tiene que dejar pasar de más, no cortar de menos.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.errors import CuotaAgotada
from crmcore.logging import get_logger

logger = get_logger(__name__)


def periodo_actual(db: Any = None) -> str:
    """El mes en curso **donde está el cliente**, como lo nombra la medición.

    Con sesión se resuelve su zona. Sin ella cae a UTC, que es lo que hacía
    antes: el 1 de mes a la una de la mañana en Madrid, en UTC todavía es el mes
    anterior — y entonces el panel dice que lleva gastado lo del mes pasado y el
    cliente no entiende por qué su cuota «no se ha renovado».
    """
    from crmcore.fechas import hoy

    return hoy(db).strftime("%Y-%m")


def inicio_del_periodo() -> datetime:
    ahora = datetime.now(timezone.utc)
    return ahora.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def tope(db: Any, tenant_id: UUID, clave: str) -> int:
    """El tope de este tenant para esta cuota. 0 o sin declarar es sin límite.

    **Se resuelve para el tenant que se pasa, no para el contexto ambiente.**
    Casi siempre coinciden —quien escribe es quien está dentro— pero no siempre:
    un trabajo de sistema actuando en nombre de otro leería la cuota equivocada,
    y eso es cortar a quien no tocaba o dejar pasar a quien sí. Lo cazó la prueba
    de que lo de un tenant no cuenta contra otro.
    """
    from crmcore.runtime import settings as rt
    from crmcore.tenancy.context import con_contexto, contexto_actual

    if contexto_actual().tenant_id == tenant_id:
        return int(rt.efectivo(clave, db) or 0)
    with con_contexto(tenant_id=tenant_id, origen="cuota"):
        return int(rt.efectivo(clave, db) or 0)


def exigir(
    db: Any,
    tenant_id: UUID,
    *,
    clave: str,
    metrica: str,
    contar: Callable[[], int],
    entrantes: int = 1,
    unidad: str = "",
    escala: int = 1,
) -> None:
    """Corta si lo que se quiere añadir no cabe en lo que le queda al tenant.

    `contar` se llama **solo si hay tope**: sin límite declarado no se paga ni la
    consulta, que es el caso de la mayoría de los despliegues.

    `escala` es cuántas unidades de conteo vale una del ajuste. El almacenamiento
    se configura en MB y se cuenta en bytes, y **la comparación va en la unidad
    fina**: redondear el consumo a MB enteros dejaba pasar dos ficheros de 700 KB
    con un tope de 1 MB, porque los dos contaban como 0. La cazó la prueba del
    borde, que es justo para lo que está.
    """
    maximo = tope(db, tenant_id, clave)
    if maximo <= 0:
        return

    consumido = contar()
    if consumido + entrantes > maximo * escala:
        sufijo = f" {unidad}" if unidad else ""
        # Con decimal cuando hay escala, o el mensaje dice «0 MB de 1 MB» y
        # rechaza: cierto —son 0,66— y absurdo de leer para quien lo recibe.
        en_unidades = round(consumido / escala, 1) if escala > 1 else consumido
        raise CuotaAgotada(
            f"Se ha agotado la cuota de {metrica}: "
            f"{en_unidades}{sufijo} de {maximo}{sufijo} este periodo",
            error_code=f"cuota.{metrica}",
            detalle={
                "metrica": metrica,
                "consumido": en_unidades,
                "limite": maximo,
                "pidiendo": entrantes,
                # Qué ajuste hay que tocar para subirlo: sin esto, quien recibe
                # el error tiene que buscar a qué clave corresponde «correos».
                "ajuste": clave,
            },
        )


def aviso_de_cercania(
    db: Any, tenant_id: UUID, *, clave: str, metrica: str, consumido: int
) -> dict[str, Any] | None:
    """Si este tenant se está acercando al tope, para enseñarlo antes de cortar.

    Avisar sólo al cortar convierte una cuota en una sorpresa. Devuelve `None`
    cuando no hay tope o queda lejos: quien lo llama no tiene que saber nada de
    umbrales.
    """
    from crmcore.runtime import settings as rt

    maximo = tope(db, tenant_id, clave)
    if maximo <= 0:
        return None
    pct = consumido / maximo * 100
    umbral = int(rt.efectivo("quota_aviso_pct", db) or 80)
    if pct < umbral:
        return None
    return {
        "metrica": metrica,
        "consumido": consumido,
        "limite": maximo,
        "pct": round(pct, 1),
        "ajuste": clave,
    }
