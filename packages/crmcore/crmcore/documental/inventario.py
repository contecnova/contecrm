"""Inventario del corpus enlazado, servicio por servicio (RT-5).

Existe por un agujero concreto en el **certificado de destrucción**. Al dar de
baja un tenant, contecrm certifica qué ha destruido; los documentos del corpus
no los destruye él —los guarda contecmind— así que tiene que decir cuáles
quedan fuera. El problema es dónde están los enlaces: la tabla
`documentos_enlazados` vive en el esquema de **cada** servicio, y ninguno lee el
del otro. `tenancy`, que es quien emite el certificado, solo ve los suyos, que
son casi ninguno: los contratos están enlazados desde `party` y `sales`.

Un certificado que dijera «fuera de este certificado: 0 documentos» porque miró
donde no había sería peor que no decir nada. Así que el inventario se pide por
el bus, igual que se replican los ajustes o la clave del tenant:

  1. Al pasar el tenant a baja, `tenancy` emite la **solicitud**.
  2. **Todos** los servicios la consumen —`crear_servicio` los suscribe sin que
     ninguno tenga que acordarse— y contestan con lo que tienen en su esquema.
  3. `tenancy` guarda cada respuesta y compone el certificado con todas.

La ventana de recuperación de 30 días da tiempo de sobra a que las respuestas
lleguen, y `destruir()` dice qué servicios no han contestado en vez de dar por
cerrada una lista que no lo está.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog
from sqlalchemy.orm import Session

logger = structlog.get_logger(__name__)

INVENTARIO_SOLICITADO = "documental.inventario.solicitado"
INVENTARIO_REPORTADO = "documental.inventario.reportado"


def declarar_eventos() -> None:
    """Declara los dos tipos en el catálogo, una sola vez.

    El productor es «core» y no un servicio: la solicitud la emite quien lleve
    las bajas y la respuesta la emite cualquiera. Ponerle dueño a uno concreto
    sería mentir sobre quién publica.
    """
    from crmcore.events.catalogo import TipoEvento, obtener, registrar

    if obtener(INVENTARIO_SOLICITADO) is None:
        registrar(
            TipoEvento(
                tipo=INVENTARIO_SOLICITADO,
                version=1,
                productor="core",
                descripcion=(
                    "Se pide a todos los servicios el inventario de documentos del "
                    "corpus que tienen enlazados a un tenant, para el certificado "
                    "de destrucción"
                ),
                campos=("tenant_id", "motivo"),
            )
        )
    if obtener(INVENTARIO_REPORTADO) is None:
        registrar(
            TipoEvento(
                tipo=INVENTARIO_REPORTADO,
                version=1,
                productor="core",
                descripcion=(
                    "Un servicio contesta con los documentos del corpus que tiene "
                    "enlazados a un tenant. Lo consume quien emite el certificado"
                ),
                campos=("tenant_id", "servicio", "documentos", "total"),
            )
        )


def solicitar_inventario(db: Session, *, tenant_id: UUID, motivo: str = "baja") -> None:
    """Pide el inventario a todos los servicios. Va por la tabla de salida.

    En la misma transacción que el cambio de estado: o el tenant queda en baja y
    la petición sale, o no pasa ninguna de las dos cosas. Una baja registrada
    cuya petición se perdió daría un certificado incompleto sin que nadie lo
    notara.
    """
    from crmcore.bus.outbox import encolar

    declarar_eventos()
    encolar(
        db,
        tenant_id=tenant_id,
        tipo=INVENTARIO_SOLICITADO,
        subject_tipo="tenant",
        subject_id=tenant_id,
        data={"tenant_id": str(tenant_id), "motivo": motivo},
        # El hecho es «se pidió el inventario de este tenant por este motivo».
        # Pedirlo dos veces es inocuo —la respuesta se escribe por clave— pero
        # deduplicar evita que un reintento del relevo despierte a todos los
        # servicios otra vez.
        dedup_key=f"invdoc:{tenant_id}:{motivo}"[:64],
    )


def _datos_de(mensaje: Any) -> dict[str, Any]:
    """El mensaje llega como `Evento` desde NATS y como dict desde el bus local."""
    if isinstance(mensaje, dict):
        datos = mensaje.get("data")
        return datos if isinstance(datos, dict) else mensaje
    return getattr(mensaje, "data", None) or {}


async def consumir_solicitud(mensaje: Any) -> None:
    """Contesta con lo que ESTE servicio tiene enlazado del tenant.

    Lo registra `crear_servicio` en todos, igual que la réplica de ajustes: un
    servicio que no lo consumiera dejaría sus documentos fuera del inventario y
    el certificado diría menos de lo que hay, que es justo el fallo que esto
    viene a cerrar.

    Contesta **siempre**, aunque no tenga nada y aunque ni siquiera tenga la
    tabla: el silencio y el cero se distinguen, y el que emite el certificado
    necesita saber cuál de los dos es.
    """
    from crmcore.bus.outbox import encolar
    from crmcore.config import get_settings
    from crmcore.db.uow import unidad_de_trabajo

    datos = _datos_de(mensaje)
    try:
        tenant_id = UUID(str(datos.get("tenant_id")))
    except (TypeError, ValueError):
        logger.error("documental.inventario_solicitud_sin_tenant", datos=str(datos)[:200])
        return

    servicio = get_settings().service_name or "desconocido"
    with unidad_de_trabajo(sistema=True) as uow:
        documentos, nota = _inventariar(uow.db, tenant_id)
        declarar_eventos()
        encolar(
            uow.db,
            tenant_id=tenant_id,
            tipo=INVENTARIO_REPORTADO,
            subject_tipo="tenant",
            subject_id=tenant_id,
            data={
                "tenant_id": str(tenant_id),
                "servicio": servicio,
                "documentos": documentos,
                "total": len(documentos),
                "nota": nota,
            },
            # Un servicio, un tenant, una respuesta: si se pide dos veces, la
            # segunda sustituye a la primera en vez de duplicarla.
            dedup_key=f"invdoc-rep:{servicio}:{tenant_id}"[:64],
        )
    logger.info(
        "documental.inventario_reportado",
        servicio=servicio,
        tenant=str(tenant_id),
        documentos=len(documentos),
    )


def _inventariar(db: Session, tenant_id: UUID) -> tuple[list[dict[str, Any]], str]:
    """Lee los enlaces del esquema propio. Nunca lanza.

    Un servicio sin la tabla —porque no enlaza documentos— no es un error: es la
    respuesta «no tengo nada», y se dice con la nota para que no se confunda con
    un fallo. Que una consulta rota impidiera contestar dejaría al que emite el
    certificado esperando para siempre.
    """
    from crmcore.documental.enlaces import inventario_para_certificado

    try:
        return inventario_para_certificado(db, tenant_id), ""
    except Exception as exc:  # noqa: BLE001 — contestar importa más que el detalle
        db.rollback()
        logger.warning("documental.inventario_no_legible", error=str(exc)[:200])
        return [], f"no se pudo leer el inventario: {str(exc)[:160]}"


from crmcore.contratos import Consumo, declarar_consumo  # noqa: E402

# El evento se declara también al importar, y no solo la primera vez que alguien
# lo emite. Con la declaración perezosa, el gate de contratos podía correr sin
# que el productor existiera todavía y acusar al consumidor de esperar un evento
# que nadie publica. Las declaraciones son idempotentes, así que no cuesta nada.
declarar_eventos()


# Contrato dirigido por el consumidor (CRM-00.03.01.03): lo que este
# consumidor lee de verdad, para que el productor no lo quite creyendo que
# no lo usa nadie. El daño de quitarlo no se ve en el productor.
declarar_consumo(
    Consumo(
        consumidor="todos-los-servicios",
        evento=INVENTARIO_SOLICITADO,
        campos=("tenant_id",),
        motivo=(
            "Saber de qué tenant hay que listar los documentos; sin él la respuesta "
            "sería de todos los tenants, que es justo lo que no puede pasar"
        ),
    )
)
