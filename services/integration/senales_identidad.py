"""Las señales de identidad que ven los canales, mandadas a `party`
(CRM-01.01.05.02).

`party` resuelve quién es quién entre canales: une el correo que escribió por el
buzón, el número que llamó a la centralita y el identificador que trae el ERP.
Pero solo puede unir lo que le cuentan, y hasta el 09-11-2026 integración —que
es quien recibe a la gente por esos canales— no le contaba nada: la ruta
`POST /calidad-dato/identidades/observar` existía y no la llamaba nadie.

Las decisiones:

**Se anota aquí antes de mandarlo.** La señal se guarda en esta tabla y después
se manda. Si `party` no contesta, la entrada no se cae —el correo, la llamada o
el registro del ERP quedan registrados igual— y la señal se queda «en error»
con el motivo, para que el relevo la reintente. Mandarla al aire y olvidarla
dejaba sin unir justo a la gente que entró en el peor momento.

**Una vez por cosa vista.** La clave es el origen, la referencia (la
interacción, la llamada, el correo) y el tipo: un reenvío del proveedor no
cuenta dos veces la misma señal.

**Lo que `party` rechaza no se reintenta.** Un 4xx es una respuesta, no una
caída: reintentarlo cada vuelta llena la cola de lo que nunca va a entrar. Se
queda «rechazada» con su motivo.

**Con la identidad de quien pide, o la del sistema si no hay persona.** La
centralita y el buzón llegan con la de quien manda el aviso; el relevo y el
ERP, con la del sistema y solo el permiso que hace falta.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable
from uuid import UUID

from crmcore.db.base import Base
from crmcore.errors import CrmError
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint, func, select, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

logger = get_logger(__name__)

Invocador = Callable[..., dict[str, Any]]

RUTA_OBSERVAR = "/api/v1/calidad-dato/identidades/observar"
ESTADOS = ("pendiente", "enviada", "error", "rechazada")


class SenalSaliente(Base):
    """Una señal de identidad vista en un canal, y si `party` ya la tiene."""

    __tablename__ = "senales_identidad_salientes"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    # El vocabulario es el de `party` (email, telefono, id_erp, cookie…): si
    # manda otro, lo rechaza y queda dicho aquí.
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)
    valor: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        info={"anonimizar_en_copias": True, "sensibilidad": "personal"},
    )
    contacto_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    # Por dónde se vio: canal:correo, telefonia, buzon, integracion:<operación>.
    origen: Mapped[str] = mapped_column(String(40), nullable=False)
    # Qué se vio: la interacción, la llamada, el correo o el registro recibido.
    referencia: Mapped[str] = mapped_column(String(300), nullable=False)
    estado: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pendiente",
        server_default=text("'pendiente'"),
        info={"opciones": ESTADOS},
    )
    intentos: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    error: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))
    enviada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "origen", "referencia", "tipo", name="uq_senal_saliente"),
        Index("ix_senales_salientes_estado", "tenant_id", "estado"),
    )


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _ajuste(clave: str, db: Session | None) -> Any:
    from services.integration.ajustes import valor

    return valor(clave, db)


def _invocar(**kw: Any) -> dict[str, Any]:
    from crmcore.http.interno import invocar

    return invocar(**kw)


def identidad_del_sistema(tenant_id: Any) -> dict[str, Any]:
    """La identidad con la que se manda cuando no hay persona detrás.

    La del tenant como principal de máquina, como hace la casa en el resto de
    llamadas sin persona, y **solo** con el permiso que pide la ruta de party.
    """
    return {
        "tenant_id": tenant_id,
        "principal_id": tenant_id,
        "permisos": ["contact:write"],
        "roles": [],
        "tipo": "agente",
    }


def anotar(
    db: Session,
    tenant_id: UUID,
    *,
    tipo: str,
    valor: str,
    origen: str,
    referencia: str,
    contacto_id: UUID | None = None,
) -> SenalSaliente | None:
    """Guarda la señal para mandarla. `None` si viene vacía.

    Si ya estaba y ahora se sabe de quién es, se le pone el contacto y vuelve a
    pendiente: atribuir a posteriori es justo lo que ata la señal a alguien.
    """
    valor = (valor or "").strip()
    if not valor or not tipo:
        return None
    origen = origen[:40]
    referencia = referencia[:300]
    fila = db.execute(
        select(SenalSaliente).where(
            SenalSaliente.tenant_id == tenant_id,
            SenalSaliente.origen == origen,
            SenalSaliente.referencia == referencia,
            SenalSaliente.tipo == tipo,
        )
    ).scalar_one_or_none()
    if fila is None:
        fila = SenalSaliente(
            tenant_id=tenant_id,
            tipo=tipo,
            valor=valor[:500],
            contacto_id=contacto_id,
            origen=origen,
            referencia=referencia,
            estado="pendiente",
            intentos=0,
            error="",
        )
        db.add(fila)
    elif contacto_id and fila.contacto_id != contacto_id:
        fila.contacto_id = contacto_id
        fila.estado = "pendiente"
        fila.intentos = 0
        fila.error = ""
    db.flush()
    return fila


def enviar(
    db: Session,
    filas: list[SenalSaliente],
    *,
    identidad: dict[str, Any],
    invocar: Invocador | None = None,
) -> dict[str, int]:
    """Manda a `party` las señales que aún no tiene. **Nunca lanza.**

    Un fallo de party no puede tumbar la entrada que la vio: se anota en la
    fila y la reintenta el relevo.
    """
    invocar = invocar or _invocar
    espera = float(_ajuste("senales_identidad_espera_s", db))
    cuenta = {"enviadas": 0, "errores": 0, "rechazadas": 0}
    for fila in filas:
        if fila is None or fila.estado in ("enviada", "rechazada"):
            continue
        fila.intentos += 1
        try:
            r = invocar(
                metodo="POST",
                ruta=RUTA_OBSERVAR,
                cuerpo={
                    "tipo": fila.tipo,
                    "valor": fila.valor,
                    "contacto_id": str(fila.contacto_id) if fila.contacto_id else None,
                    "origen": fila.origen,
                },
                timeout_s=espera,
                **identidad,
            )
        except CrmError as exc:
            fila.estado = "error"
            fila.error = exc.mensaje[:1000]
            cuenta["errores"] += 1
            continue
        estado = int(r.get("estado") or 0)
        if r.get("ok"):
            fila.estado = "enviada"
            fila.error = ""
            fila.enviada_at = _ahora()
            cuenta["enviadas"] += 1
        elif 400 <= estado < 500 and estado not in (401, 403, 408, 429):
            # Lo que party no acepta no va a aceptarlo en la siguiente vuelta.
            # Sin permiso o con prisa sí puede cambiar: eso se reintenta.
            datos = r.get("datos") or {}
            fila.estado = "rechazada"
            fila.error = f"HTTP {estado}: {datos.get('mensaje') or datos.get('detail') or datos}"[
                :1000
            ]
            cuenta["rechazadas"] += 1
        else:
            fila.estado = "error"
            fila.error = f"HTTP {estado}"
            cuenta["errores"] += 1
    db.flush()
    if cuenta["errores"] or cuenta["rechazadas"]:
        logger.warning("senales_identidad.sin_entregar", **cuenta)
    return cuenta


def anotar_y_enviar(
    db: Session,
    tenant_id: UUID,
    *,
    identidad: dict[str, Any] | None,
    invocar: Invocador | None = None,
    **senal: Any,
) -> SenalSaliente | None:
    """Anota y, si hay identidad, la manda ya. Sin identidad la manda el relevo."""
    fila = anotar(db, tenant_id, **senal)
    if fila is not None and identidad is not None:
        enviar(db, [fila], identidad=identidad, invocar=invocar)
    return fila


def reenviar_pendientes(
    db: Session, tenant_id: UUID, *, invocar: Invocador | None = None
) -> dict[str, int]:
    """Lo que el relevo hace cada vuelta: mandar lo pendiente y lo que falló."""
    tope = int(_ajuste("senales_identidad_reintentos", db))
    lote = int(_ajuste("senales_identidad_lote", db))
    filas = list(
        db.execute(
            select(SenalSaliente)
            .where(
                SenalSaliente.tenant_id == tenant_id,
                SenalSaliente.estado.in_(("pendiente", "error")),
                SenalSaliente.intentos < tope,
            )
            .order_by(SenalSaliente.created_at)
            .limit(lote)
        )
        .scalars()
        .all()
    )
    if not filas:
        return {"enviadas": 0, "errores": 0, "rechazadas": 0}
    return enviar(db, filas, identidad=identidad_del_sistema(tenant_id), invocar=invocar)


def tenants_con_pendientes() -> list[UUID]:
    """Los tenants con señales por mandar, de su propia tabla."""
    from crmcore.db.session import sesion

    with sesion(sistema=True) as db:
        return [
            t
            for (t,) in db.execute(
                select(SenalSaliente.tenant_id)
                .where(SenalSaliente.estado.in_(("pendiente", "error")))
                .distinct()
            ).all()
        ]
