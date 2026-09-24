"""Captura de leads desde fuera: formularios, chat y lo que venga.

`CRM-01.01.03.02` pide «formularios, web, importación, API, eventos, listas,
chat». La importación masiva y la API ya estaban. Lo que faltaba es lo que llega
**desde fuera sin credencial de usuario**: el formulario de la web, el chat, el
formulario de una feria en una tablet.

Y eso es un solo mecanismo, no tres. Un canal de captura es una definición por
tenant que dice **cómo se traduce lo que llega a un lead**, más las tres cosas
que hacen que un endpoint público no se convierta en un problema.

**Por qué un canal declarado y no un endpoint por integración.** El formulario
de la web manda `nombre_completo`, el chat manda `visitor_name` y la tablet de
la feria manda `NOMBRE`. Con un endpoint por cada uno, cada cliente nuevo es
código nuevo. Con un mapa declarado, es una fila.

Las tres protecciones, y ninguna es opcional:

**Clave por canal.** El endpoint es público —tiene que serlo, lo llama el
navegador de un desconocido— pero no anónimo: cada canal lleva una clave que va
en la petición. Sin ella, la URL sería un formulario de alta de leads abierto a
Internet, y un competidor aburrido puede llenar el CRM en una tarde.

**Trampa para robots.** Un campo que un humano nunca rellena porque no lo ve. Si
viene con contenido, se descarta **con un 200**: devolver un error le dice al
robot qué tiene que cambiar para la próxima.

**Tope por canal y ventana.** Aunque la clave se filtre —y se filtra, porque va
en el HTML de una página pública— el daño está acotado a lo que el tenant haya
declarado que es razonable recibir.

Lo que **no** hace, dicho: no deduplica contra los leads existentes en el
momento de la captura. Eso lo hace el flujo de calidad después, y meterlo aquí
convertiría cada envío de formulario en una consulta de similitud contra toda la
tabla — un formulario que tarda dos segundos es un formulario que se abandona.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from crmcore.db.base import Base, SoftDeleteMixin, TimestampMixin
from crmcore.errors import ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import Boolean, DateTime, Index, Integer, String, func, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

logger = get_logger(__name__)

# Campos del lead a los que un canal puede mapear. Lista cerrada: sin ella, un
# canal podría escribir `owner_id` o `campana_id` desde una petición pública, y
# eso es asignarse leads o imputarlos a la campaña de otro.
CAMPOS_DESTINO = (
    "nombre",
    "apellidos",
    "empresa",
    "cargo",
    "email",
    "telefono",
    "web",
    "pais",
    "origen",
)


class CanalCaptura(Base, TimestampMixin, SoftDeleteMixin):
    """Una entrada declarada: de dónde llega y cómo se traduce."""

    __tablename__ = "canales_captura"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    clave: Mapped[str] = mapped_column(String(80), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    # formulario | chat | lista | otro. Es descriptivo: el mecanismo es el mismo
    # y sirve para agrupar en los informes de origen.
    tipo: Mapped[str] = mapped_column(String(20), nullable=False, default="formulario")

    # El secreto que tiene que traer la petición. Se guarda **hasheado**: si la
    # base se filtra, las claves de los formularios de todos los tenants no
    # vienen en ella. Se enseña una sola vez al crear el canal.
    secreto_hash: Mapped[str] = mapped_column(String(64), nullable=False, info={"secreto": True})

    # De qué campo de entrada sale cada campo del lead: {"email": "correo"}.
    mapeo: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # Valores fijos que se ponen siempre: el origen, la campaña. Van aquí y no en
    # la petición porque vienen del canal, no de quien rellena el formulario —
    # que podría poner cualquier cosa.
    fijos: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # Campos de entrada obligatorios. Sin al menos uno de contacto, el lead no
    # sirve para nada y solo ensucia el embudo.
    obligatorios: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Nombre del campo trampa. Vacío = sin trampa, que se admite pero se avisa.
    campo_trampa: Mapped[str] = mapped_column(String(60), nullable=False, default="")

    # Tope por ventana. La clave viaja en el HTML de una página pública: se
    # filtra siempre, y esto es lo que acota el daño.
    max_por_hora: Mapped[int] = mapped_column(Integer, nullable=False, default=200)
    activo: Mapped[Boolean] = mapped_column(Boolean, nullable=False, default=True)

    recibidos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    descartados: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ultimo_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_canales_captura", "tenant_id", "clave", unique=True),)


class RecepcionCaptura(Base):
    """Cada entrada que llega, se cree o se descarte.

    Se guarda **también lo descartado**, y es lo que convierte «no me llegó el
    lead del formulario» en una pregunta contestable: o no llegó, o llegó y se
    descartó por el motivo que dice aquí. Sin esto, la respuesta es mirar el log
    del servidor web.
    """

    __tablename__ = "recepciones_captura"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    canal_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    lead_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    # creado | descartado_trampa | descartado_incompleto | descartado_tope
    resultado: Mapped[str] = mapped_column(String(30), nullable=False)
    detalle: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    # Lo que llegó, para poder recuperar un lead descartado por error. NO se
    # guarda indefinidamente: la retención lo purga como cualquier otro dato
    # personal, y por eso lleva su propia clase de dato.
    entrada: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_recepciones_canal", "tenant_id", "canal_id", "created_at"),)


# ── Alta y secreto ────────────────────────────────────────────────────────


def _hash(secreto: str) -> str:
    return hashlib.sha256(secreto.encode()).hexdigest()


def crear_canal(
    db: Session, *, tenant_id: UUID, clave: str, nombre: str, **datos: Any
) -> tuple[CanalCaptura, str]:
    """Da de alta un canal y devuelve su secreto **una sola vez**.

    El secreto se guarda hasheado: si la base se filtra, las claves de los
    formularios de todos los tenants no vienen en ella. Se enseña al crear y no
    se puede volver a consultar — se rota.
    """
    import secrets

    if not clave:
        raise ErrorValidacion("El canal necesita una clave", error_code="captura.sin_clave")

    mapeo = dict(datos.get("mapeo") or {})
    sobrantes = sorted(set(mapeo) - set(CAMPOS_DESTINO))
    if sobrantes:
        # Sin esta comprobación, un canal podría escribir `owner_id` desde una
        # petición pública: asignarse leads o imputarlos a la campaña de otro.
        raise ErrorValidacion(
            f"Un canal no puede escribir estos campos del lead: {sobrantes}",
            error_code="captura.campo_no_permitido",
            detalle={"admitidos": list(CAMPOS_DESTINO)},
        )

    secreto = secrets.token_urlsafe(32)
    canal = CanalCaptura(
        tenant_id=tenant_id,
        clave=clave,
        nombre=nombre,
        tipo=str(datos.get("tipo") or "formulario"),
        secreto_hash=_hash(secreto),
        mapeo=mapeo,
        fijos=dict(datos.get("fijos") or {}),
        obligatorios=list(datos.get("obligatorios") or []),
        campo_trampa=str(datos.get("campo_trampa") or ""),
        max_por_hora=int(datos.get("max_por_hora") or 200),
    )
    if not canal.campo_trampa:
        # Se admite, porque hay canales servidor-a-servidor donde no aplica,
        # pero se deja constancia: un formulario de navegador sin trampa recibe
        # basura desde el primer día.
        logger.warning("captura.canal_sin_trampa", clave=clave)
    db.add(canal)
    db.flush()
    return canal, secreto


def rotar_secreto(db: Session, canal_id: UUID) -> str:
    """Cambia el secreto. Lo anterior deja de valer inmediatamente."""
    import secrets

    canal = db.get(CanalCaptura, canal_id)
    if canal is None:
        raise NoEncontrado("El canal no existe", error_code="captura.canal_no_existe")
    secreto = secrets.token_urlsafe(32)
    canal.secreto_hash = _hash(secreto)
    db.flush()
    return secreto


def _canal(db: Session, tenant_id: UUID, clave: str, secreto: str) -> CanalCaptura:
    canal = db.execute(
        select(CanalCaptura).where(CanalCaptura.tenant_id == tenant_id, CanalCaptura.clave == clave)
    ).scalar_one_or_none()
    # Mismo error para «no existe», «está apagado» y «clave mala»: distinguirlos
    # convierte el endpoint en un oráculo que dice qué canales tiene un tenant.
    if (
        canal is None
        or not canal.activo
        or not hmac.compare_digest(canal.secreto_hash, _hash(secreto or ""))
    ):
        raise NoEncontrado("Canal de captura desconocido", error_code="captura.canal_no_existe")
    return canal


# ── Recepción ─────────────────────────────────────────────────────────────


def recibir(
    uow: Any, *, tenant_id: UUID, clave: str, secreto: str, entrada: dict[str, Any]
) -> dict[str, Any]:
    """Convierte lo que llega en un lead, o dice por qué no.

    Devuelve siempre la misma forma, también al descartar: quien llama es una
    página web, y una respuesta distinta por cada motivo de descarte le enseña a
    un robot qué tiene que cambiar.
    """
    db = uow.db
    canal = _canal(db, tenant_id, clave, secreto)

    if canal.campo_trampa and str(entrada.get(canal.campo_trampa) or "").strip():
        # Un humano no ve ese campo, así que no lo rellena. Se descarta con un
        # 200: un error le diría al robot qué cambiar para la próxima.
        return _anotar(db, canal, entrada, "descartado_trampa", "campo trampa relleno")

    if _pasados_de_tope(db, canal):
        return _anotar(
            db,
            canal,
            entrada,
            "descartado_tope",
            f"más de {canal.max_por_hora} en una hora",
        )

    faltan = [c for c in (canal.obligatorios or []) if not str(entrada.get(c) or "").strip()]
    if faltan:
        return _anotar(db, canal, entrada, "descartado_incompleto", f"faltan: {', '.join(faltan)}")

    datos = {campo: entrada.get(origen) for campo, origen in (canal.mapeo or {}).items()}
    datos = {k: v for k, v in datos.items() if v not in (None, "")}
    datos.update(
        {k: v for k, v in (canal.fijos or {}).items() if k in CAMPOS_DESTINO or k == "campana_id"}
    )
    if not any(datos.get(c) for c in ("email", "telefono")):
        # Un lead sin forma de contactar no sirve para nada y solo ensucia el
        # embudo y las métricas de conversión.
        return _anotar(db, canal, entrada, "descartado_incompleto", "sin correo ni teléfono")

    # Lo que no encaja en un campo del lead se conserva en `campos`: el
    # formulario de un cliente pregunta cosas que este CRM no conoce, y tirarlas
    # obligaría a mirar el correo de aviso para saber qué pidió el interesado.
    mapeados = set((canal.mapeo or {}).values()) | {canal.campo_trampa, "utm"}
    extras = {k: v for k, v in entrada.items() if k not in mapeados}

    from services.sales import servicio as svc

    lead = svc.crear_lead(
        uow,
        **datos,
        utm=dict(entrada.get("utm") or {}),
        campos=extras,
    )
    return _anotar(db, canal, entrada, "creado", "", lead_id=lead.id)


def _pasados_de_tope(db: Session, canal: CanalCaptura) -> bool:
    desde = datetime.now(timezone.utc) - timedelta(hours=1)
    recibidos = db.execute(
        select(func.count())
        .select_from(RecepcionCaptura)
        .where(
            RecepcionCaptura.canal_id == canal.id,
            RecepcionCaptura.created_at >= desde,
            RecepcionCaptura.resultado == "creado",
        )
    ).scalar_one()
    return bool(recibidos >= canal.max_por_hora)


def _anotar(
    db: Session,
    canal: CanalCaptura,
    entrada: dict[str, Any],
    resultado: str,
    detalle: str,
    lead_id: UUID | None = None,
) -> dict[str, Any]:
    db.add(
        RecepcionCaptura(
            tenant_id=canal.tenant_id,
            canal_id=canal.id,
            lead_id=lead_id,
            resultado=resultado,
            detalle=detalle[:300],
            entrada=entrada,
        )
    )
    canal.ultimo_at = datetime.now(timezone.utc)
    if resultado == "creado":
        canal.recibidos += 1
    else:
        canal.descartados += 1
        logger.info("captura.descartada", canal=canal.clave, motivo=resultado, detalle=detalle)
    db.flush()
    # Misma forma siempre: quien llama es una página web, y una respuesta
    # distinta por motivo de descarte le enseña a un robot qué cambiar.
    return {"recibido": True, "lead_id": str(lead_id) if lead_id else None}


def recepciones(
    db: Session, *, canal_id: UUID | None = None, solo_descartadas: bool = False, limite: int = 100
) -> list[dict[str, Any]]:
    """Qué ha entrado por los canales, incluido lo descartado.

    Es lo que convierte «no me llegó el lead del formulario» en una pregunta
    contestable: o no llegó, o llegó y se descartó por esto.
    """
    consulta = select(RecepcionCaptura)
    if canal_id is not None:
        consulta = consulta.where(RecepcionCaptura.canal_id == canal_id)
    if solo_descartadas:
        consulta = consulta.where(RecepcionCaptura.resultado != "creado")
    filas = (
        db.execute(consulta.order_by(RecepcionCaptura.created_at.desc()).limit(limite))
        .scalars()
        .all()
    )
    return [
        {
            "id": str(f.id),
            "canal_id": str(f.canal_id),
            "resultado": f.resultado,
            "detalle": f.detalle,
            "lead_id": str(f.lead_id) if f.lead_id else None,
            "entrada": f.entrada,
            "created_at": f.created_at.isoformat() if f.created_at else None,
        }
        for f in filas
    ]
