"""El registro de lo que se intentó entregar y cómo acabó (CRM-06.02.01.02).

«No me llegó el aviso» es la incidencia más frecuente de un CRM y la más difícil
de contestar. Sin este registro se acaba mirando el log del servidor de correo
de otra empresa, o diciendo «nosotros lo mandamos», que no es una respuesta.

Con él se contesta con hechos: se intentó a las 09:12, el servidor devolvió
«550 mailbox unavailable», no se reintentó porque ese código es definitivo, y la
dirección de esa persona es la que es.

La tabla vive en el esquema del servicio que reparte —`identity`, que es quien
conoce a las personas y sus direcciones— y no en uno común, por lo de siempre:
ningún servicio lee el esquema de otro.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, Index, Integer, String, Text, func, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from crmcore.db.base import Base
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger

logger = get_logger(__name__)

ESTADOS = ("pendiente", "entregada", "fallida", "descartada")


class EntregaNotificacion(Base):
    """Un intento de sacar un aviso por un canal.

    Una fila **por canal y por notificación**, no una por notificación: un aviso
    que va por correo y por SMS puede entregarse por uno y fallar por el otro, y
    una sola fila obligaría a elegir cuál de las dos verdades se guarda.
    """

    __tablename__ = "entregas_notificacion"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    notificacion_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    usuario_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    canal: Mapped[str] = mapped_column(String(20), nullable=False)
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="pendiente")

    # La dirección a la que se intentó, tal como estaba en ese momento. Se
    # guarda aunque esté en la ficha del usuario: la ficha cambia, y la pregunta
    # que se hace después es «¿a qué dirección lo mandasteis?», no «¿cuál tiene
    # ahora?».
    direccion: Mapped[str] = mapped_column(
        String(320), nullable=False, default="", info={"sensibilidad": "personal"}
    )

    intentos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ultimo_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    referencia: Mapped[str] = mapped_column(String(120), nullable=False, default="")

    proximo_intento_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Lo que el proveedor cuenta DESPUÉS de entregar (CRM-06.02.01.08): abierto,
    # click, rebote, queja. Va como historial y no como estado porque los
    # webhooks llegan desordenados —un «entregado» después de un «abierto» pasa a
    # diario— y quedarse con el último dejaría la ficha contando una cosa que no
    # fue. SMTP nunca rellena esto: no sabe nada después de entregar.
    sucesos: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    entregada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # Los nombres llevan `notif` porque `entregas_webhook` ya usa
        # `ix_entregas_pendientes`. En producción viven en esquemas distintos y
        # no chocarían, pero en un despliegue pequeño —varios dominios en un
        # esquema— y en la suite sí: el índice del segundo modelo no se crea y
        # la consulta que lo necesita hace un `seq scan` sobre toda la tabla.
        Index("ix_entregas_notif_pendientes", "estado", "proximo_intento_at"),
        Index("ix_entregas_notif_aviso", "tenant_id", "notificacion_id"),
    )


def enviados_en_el_periodo(db: Session, tenant_id: UUID, canal: str) -> int:
    """Cuántos avisos se han mandado por este canal este mes.

    Se cuentan las filas, no un contador: cada entrega ya deja la suya, así que
    la cuenta es verdad por construcción. Si un día esto se queda corto, lo que
    toca es un índice, no un contador que se desincronice.
    """
    from crmcore.cuotas import inicio_del_periodo

    return int(
        db.execute(
            select(func.count())
            .select_from(EntregaNotificacion)
            .where(
                EntregaNotificacion.tenant_id == tenant_id,
                EntregaNotificacion.canal == canal,
                EntregaNotificacion.created_at >= inicio_del_periodo(),
            )
        ).scalar_one()
    )


# Qué ajuste acota cada canal. **Declaración explícita: lo que no está aquí no se
# corta.** Un canal nuevo que nadie declare pasa sin límite, que es de largo
# preferible a cortarle el aviso a un cliente por un olvido nuestro.
CUOTA_POR_CANAL = {
    "email": "cuota_correos_mes",
    "sms": "cuota_sms_mes",
}


def registrar_medidores_de_consumo() -> None:
    """Declara al panel que este módulo sabe contar correos y SMS."""
    from crmcore.consumo import registrar_medidor

    for canal, clave in CUOTA_POR_CANAL.items():
        registrar_medidor(
            canal,
            lambda db, t, c=canal, k=clave: (enviados_en_el_periodo(db, t, c), k),
        )


def registrar_intento(
    db: Session,
    *,
    tenant_id: UUID,
    notificacion_id: UUID,
    usuario_id: UUID,
    canal: str,
    direccion: str,
) -> EntregaNotificacion:
    """Abre —o recupera— la ficha de entrega de este aviso por este canal.

    **Aquí se aplica la cuota del canal**, porque es la puerta por la que pasa
    todo aviso saliente: ponerla en cada sitio que manda un correo garantiza que
    al cuarto se olvide.

    Se comprueba **antes** de abrir la ficha y sólo cuando la ficha es nueva: un
    reintento de algo ya contado no puede consumir cuota dos veces, o un canal
    con mal día se comería el mes.
    """
    from crmcore.cuotas import exigir

    fila = (
        db.execute(
            select(EntregaNotificacion).where(
                EntregaNotificacion.notificacion_id == notificacion_id,
                EntregaNotificacion.canal == canal,
            )
        )
        .scalars()
        .first()
    )
    if fila is None:
        clave = CUOTA_POR_CANAL.get(canal)
        if clave:
            exigir(
                db,
                tenant_id,
                clave=clave,
                metrica=canal,
                contar=lambda: enviados_en_el_periodo(db, tenant_id, canal),
            )
        fila = EntregaNotificacion(
            tenant_id=tenant_id,
            notificacion_id=notificacion_id,
            usuario_id=usuario_id,
            canal=canal,
            direccion=direccion[:320],
        )
        db.add(fila)
        db.flush()
    return fila


def anotar_resultado(db: Session, fila: EntregaNotificacion, resultado: Any) -> None:
    """Guarda cómo fue el intento y decide si habrá otro.

    La espera crece con el cuadrado del intento (1 min, 4, 9, 16, 25): lineal se
    queda corta con un proveedor caído una hora, y exponencial se pasa de largo
    —al quinto intento serían dieciséis horas— para un aviso que deja de tener
    valor pasada la tarde.
    """
    from crmcore.config import get_settings

    s = get_settings()
    fila.intentos += 1
    fila.referencia = resultado.referencia or fila.referencia

    if resultado.entregado:
        fila.estado = "entregada"
        fila.entregada_at = datetime.now(timezone.utc)
        fila.proximo_intento_at = None
        fila.ultimo_error = ""
        return

    fila.ultimo_error = str(resultado.detalle)[:2000]
    if not resultado.reintentar:
        # Un destinatario sin dirección o un correo rechazado como inexistente
        # no mejoran reintentando. Se descarta y se dice, en vez de dejarlo
        # girando en la cola cada cinco minutos para siempre.
        fila.estado = "descartada"
        fila.proximo_intento_at = None
        logger.info(
            "notificacion.descartada",
            canal=fila.canal,
            motivo=fila.ultimo_error[:160],
        )
        return

    if fila.intentos >= s.notificacion_max_intentos:
        fila.estado = "fallida"
        fila.proximo_intento_at = None
        logger.warning(
            "notificacion.fallida",
            canal=fila.canal,
            intentos=fila.intentos,
            error=fila.ultimo_error[:160],
        )
        return

    fila.estado = "pendiente"
    fila.proximo_intento_at = datetime.now(timezone.utc) + timedelta(
        seconds=s.notificacion_espera_base_s * (fila.intentos**2)
    )


def reintentables(db: Session, *, limite: int = 100) -> list[EntregaNotificacion]:
    """Entregas que tocan reintentar ahora.

    `SKIP LOCKED` para que varias réplicas repartan a la vez sin mandar dos
    veces el mismo aviso ni bloquearse entre ellas.
    """
    ahora = datetime.now(timezone.utc)
    return list(
        db.execute(
            select(EntregaNotificacion)
            .where(
                EntregaNotificacion.estado == "pendiente",
                EntregaNotificacion.intentos > 0,
                EntregaNotificacion.proximo_intento_at.is_not(None),
                EntregaNotificacion.proximo_intento_at <= ahora,
            )
            .order_by(EntregaNotificacion.proximo_intento_at)
            .limit(limite)
            .with_for_update(skip_locked=True)
        )
        .scalars()
        .all()
    )


def historial(db: Session, notificacion_id: UUID) -> list[dict[str, Any]]:
    """Qué se intentó con este aviso. Es la respuesta a «no me llegó»."""
    filas = (
        db.execute(
            select(EntregaNotificacion)
            .where(EntregaNotificacion.notificacion_id == notificacion_id)
            .order_by(EntregaNotificacion.canal)
        )
        .scalars()
        .all()
    )
    return [
        {
            "canal": f.canal,
            "estado": f.estado,
            "direccion": f.direccion,
            "intentos": f.intentos,
            "ultimo_error": f.ultimo_error,
            "referencia": f.referencia,
            "entregada_at": f.entregada_at.isoformat() if f.entregada_at else None,
            "proximo_intento_at": (
                f.proximo_intento_at.isoformat() if f.proximo_intento_at else None
            ),
        }
        for f in filas
    ]


# ── Qué pasó DESPUÉS de entregar (CRM-06.02.01.08) ────────────────────────

# Lo que un transporte puede decirnos después. SMTP no dice nada de esto: da por
# entregado lo que aceptó el primer servidor, y ahí se acaba su información. La
# apertura y el rebote solo los dan las APIs de los proveedores de correo, y por
# eso esto entra por un camino aparte y OPCIONAL: engancharlo ata la instalación
# a ese proveedor, y decirlo es parte de la capacidad.
SUCESOS_POSTERIORES = ("entregado", "abierto", "click", "rebote_duro", "rebote_blando", "queja")

# Cuáles obligan a dejar de escribir a esa dirección. No son opinables: un rebote
# duro es una dirección que no existe y una queja es alguien que nos ha marcado
# como spam. Seguir escribiendo a cualquiera de los dos es como se pierde la
# reputación de envío de todo el dominio, que afecta a los demás clientes.
CIERRAN_LA_DIRECCION = ("rebote_duro", "queja")


def anotar_suceso(
    db: Session,
    *,
    tenant_id: UUID,
    entrega_id: UUID | None,
    direccion: str,
    suceso: str,
    detalle: str = "",
    proveedor: str = "",
    ocurrido_at: datetime | None = None,
) -> dict[str, Any]:
    """Anota lo que el proveedor cuenta que pasó con un correo ya mandado.

    **SMTP no da esto.** Da por entregado lo que aceptó el primer servidor y ahí
    termina lo que sabe: si el buzón rebota media hora después, el CRM nunca se
    entera. Por eso esta vía existe y por eso es opcional — usarla ata la
    instalación a la API de un proveedor concreto, y esa es una decisión del
    cliente, no una que se le imponga por traer la función.

    Lo que **no** es opcional es la consecuencia: un rebote duro o una queja
    cierran la dirección. Anotarlos y seguir escribiendo sería tener la
    información y no usarla, que es peor que no tenerla.
    """
    if suceso not in SUCESOS_POSTERIORES:
        from crmcore.errors import ErrorValidacion

        raise ErrorValidacion(
            f"Suceso de entrega desconocido: «{suceso}»",
            error_code="entrega.suceso_desconocido",
            detalle={"admitidos": list(SUCESOS_POSTERIORES)},
        )

    momento = ocurrido_at or datetime.now(timezone.utc)
    fila = db.get(EntregaNotificacion, entrega_id) if entrega_id else None
    if fila is not None:
        historial = list(fila.sucesos or [])
        historial.append(
            {
                "suceso": suceso,
                "cuando": momento.isoformat(),
                "detalle": detalle[:300],
                "proveedor": proveedor,
            }
        )
        fila.sucesos = historial
        # El estado solo avanza: un «entregado» que llega después de un «abierto»
        # —pasa, porque los webhooks se desordenan— no puede retroceder la ficha.
        if suceso == "entregado" and fila.estado == "pendiente":
            fila.estado = "entregada"
        elif suceso in CIERRAN_LA_DIRECCION:
            fila.estado = "fallida"
        db.flush()

    cierra = suceso in CIERRAN_LA_DIRECCION
    if cierra:
        logger.warning(
            "notificaciones.direccion_cerrada",
            suceso=suceso,
            proveedor=proveedor,
        )
    return {
        "suceso": suceso,
        "direccion": direccion,
        "cierra_la_direccion": cierra,
        "que_hacer": (
            "Hay que dejar de escribir a esta dirección: un rebote duro es un buzón "
            "que no existe y una queja es alguien que nos ha marcado como spam. "
            "Seguir escribiendo quema la reputación del dominio, y eso lo pagan "
            "también los demás clientes."
            if cierra
            else ""
        ),
    }


def estadisticas_de_entrega(db: Session, tenant_id: UUID, *, dias: int = 30) -> dict[str, Any]:
    """Cuántos llegaron, cuántos se abrieron y cuántos rebotaron.

    **Lo que no se puede medir se dice.** Si el tenant manda por SMTP, la
    apertura y el rebote no existen: no son cero, es que nadie los cuenta. Un
    panel con un 0 % de apertura hace que alguien concluya que sus correos no
    interesan, cuando lo que pasa es que su transporte no lo mide.
    """
    from datetime import timedelta

    desde = datetime.now(timezone.utc) - timedelta(days=max(1, dias))
    filas = (
        db.execute(
            select(EntregaNotificacion).where(
                EntregaNotificacion.tenant_id == tenant_id,
                EntregaNotificacion.created_at >= desde,
            )
        )
        .scalars()
        .all()
    )
    con_sucesos = [f for f in filas if f.sucesos]
    cuenta: dict[str, int] = {}
    for fila in con_sucesos:
        for suceso in fila.sucesos or []:
            clave = str(suceso.get("suceso") or "")
            cuenta[clave] = cuenta.get(clave, 0) + 1

    mandados = len(filas)
    medible = bool(con_sucesos)
    return {
        "dias": dias,
        "mandados": mandados,
        "por_suceso": cuenta,
        "aperturas": cuenta.get("abierto", 0),
        "rebotes_duros": cuenta.get("rebote_duro", 0),
        "quejas": cuenta.get("queja", 0),
        # La diferencia que decide si este panel informa o engaña.
        "medible": medible,
        "tasa_apertura_pct": (
            round(100 * cuenta.get("abierto", 0) / mandados, 1) if medible and mandados else None
        ),
        "porque": (
            "Hay sucesos de al menos un proveedor que los reporta."
            if medible
            else "Ningún transporte de este tenant reporta lo que pasa después de "
            "entregar. La apertura y el rebote NO son cero: es que nadie los "
            "cuenta. SMTP da por entregado lo que aceptó el primer servidor y ahí "
            "acaba lo que sabe."
        ),
    }
