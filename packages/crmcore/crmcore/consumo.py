"""Cuánta cuota lleva gastada un tenant **en este módulo**.

Lo publica cada servicio y lo suma el gateway, igual que la página de estado. No
hay un contador central que mantener entre trece esquemas: cada uno cuenta lo
suyo, que es lo que permite cuadrar el número con lo que el cliente ve.

**Y el que no contesta no es un cero.** Esa regla vive en el gateway, que es
quien compone: un cero es una afirmación falsa —«no has gastado nada»— y «no se
ha podido leer» es verdad. Un cliente que ve ceros llega al tope sin haber visto
subir el número nunca, y eso convierte la cuota en una encerrona.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from crmcore.logging import get_logger

logger = get_logger(__name__)

# Qué mide este proceso. Cada entrada devuelve `(consumido, clave_de_ajuste)`.
_MEDIDORES: dict[str, Callable[[Any, UUID], tuple[int, str]]] = {}


def registrar_medidor(nombre: str, fn: Callable[[Any, UUID], tuple[int, str]]) -> None:
    """Declara que este módulo sabe medir esta métrica.

    Registrar dos veces la misma es inocuo: en un proceso que importe varios
    servicios —las pruebas— pasaría, y fallar ahí no protegería de nada.
    """
    _MEDIDORES[nombre] = fn


def medidores_registrados() -> list[str]:
    return sorted(_MEDIDORES)


def limpiar_medidores() -> None:
    """Para las pruebas: el registro es del proceso y vive entre casos."""
    _MEDIDORES.clear()


def medido_aqui(db: Any, tenant_id: UUID) -> list[dict[str, Any]]:
    """Lo que este módulo mide para este tenant, con su tope al lado.

    **El tope va dentro**: un consumo sin su límite no dice si son muchos o
    pocos, y obliga a quien lo lee a buscarlo en otro sitio.

    Si un medidor revienta se dice **en su fila** y no se tumba el resto: una
    métrica rota no puede dejar sin panel a las otras cinco.
    """
    from crmcore.cuotas import periodo_actual, tope

    # De qué periodo se habla. Un panel de consumo sin decirlo obliga a suponer
    # que es el mes en curso, y el 1 de mes a la una de la mañana en Madrid la
    # suposición es falsa.
    periodo = periodo_actual(db)
    salida: list[dict[str, Any]] = []
    for nombre, medir in sorted(_MEDIDORES.items()):
        try:
            consumido, clave = medir(db, tenant_id)
        except Exception as exc:  # noqa: BLE001 — una métrica rota no tumba el panel
            logger.warning("consumo.medidor_roto", metrica=nombre, error=str(exc)[:200])
            salida.append(
                {
                    "metrica": nombre,
                    "legible": False,
                    "porque": "no se ha podido medir en este módulo",
                }
            )
            continue
        limite = tope(db, tenant_id, clave)
        # Y si **se está acercando**. `aviso_de_cercania` estaba escrita, probada
        # y sin llamante, así que la cuota sólo se notaba al cortar — y avisar
        # sólo al cortar convierte una cuota en una sorpresa: el cliente se
        # entera de que tenía un tope el día que deja de poder trabajar.
        #
        # El umbral es un ajuste en caliente, no una constante: lo que es «cerca»
        # para un tenant con mil registros no lo es para uno con un millón.
        from crmcore.cuotas import aviso_de_cercania

        aviso = aviso_de_cercania(db, tenant_id, clave=clave, metrica=nombre, consumido=consumido)
        salida.append(
            {
                "metrica": nombre,
                "legible": True,
                "consumido": consumido,
                "limite": limite,
                "sin_limite": limite <= 0,
                "pct": round(consumido / limite * 100, 1) if limite > 0 else None,
                "ajuste": clave,
                # `None` cuando no hay tope o queda lejos: quien lo pinta no
                # tiene que saber nada de umbrales.
                "en_aviso": aviso is not None,
                "aviso": aviso,
                "periodo": periodo,
            }
        )
    return salida


def avisar_de_los_que_se_acercan(uow: Any) -> dict[str, Any]:
    """Emite `quota.threshold.reached` por cada métrica que ha cruzado el umbral.

    **El aviso existía y sólo se veía abriendo el panel.** `aviso_de_cercania`
    calcula desde hace tiempo si un tenant se está acercando a un tope, y su
    resultado viajaba como un campo más de `medido_aqui`: aparecía si alguien
    entraba a mirar. El manual de usuario promete otra cosa —«cuando te acercas
    a uno se avisa antes, no cuando ya no cabe nada»— y el evento que lo llevaría
    está **declarado en el contrato publicado** desde el principio, de modo que
    un integrador podía suscribirse a él y no recibir nada jamás.

    Un aviso que depende de que alguien abra una pantalla no es un aviso: es un
    dato en una pantalla.

    **Se emite desde cada servicio y no desde uno central.** Los medidores se
    registran por proceso y cada servicio mide lo suyo sobre su propio esquema;
    un emisor central tendría que leer las tablas de los catorce, que es
    exactamente lo que la arquitectura no permite.

    **La misma métrica del mismo periodo no se procesa dos veces**, aunque este
    barrido la vuelva a ver cada hora mientras siga por encima del umbral: la
    clave de deduplicación lleva el periodo, así que el consumidor la descarta.
    Se paga en filas de la tabla de salida —acotadas por tenants × métricas ×
    vueltas— y se gana no tener que guardar en ninguna parte a quién se avisó
    ya, que sería otra tabla y otro sitio donde quedarse desincronizado.
    """
    from crmcore.cuotas import periodo_actual

    periodo = periodo_actual(uow.db)
    avisadas = 0
    for fila in medido_aqui(uow.db, uow.tenant_id):
        if not fila.get("en_aviso"):
            continue
        aviso = fila["aviso"]
        uow.emitir(
            "quota.threshold.reached",
            subject=("tenant", uow.tenant_id),
            data={
                "tenant_id": str(uow.tenant_id),
                "cuota": aviso["ajuste"],
                "consumido": aviso["consumido"],
                "limite": aviso["limite"],
                "pct": aviso["pct"],
                "metrica": aviso["metrica"],
                "periodo": periodo,
            },
            # Tenant + métrica + periodo: lo que hace que avisar sea una vez por
            # periodo y no una por vuelta del barrido.
            dedup_key=f"cuota:{uow.tenant_id}:{aviso['metrica']}:{periodo}",
        )
        avisadas += 1
    return {"avisadas": avisadas}
