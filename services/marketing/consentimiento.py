"""Doble opt-in, renovación, cookies y cumplimiento de contenido
(CRM-02.04.02.02, CRM-07.03.01.08, CRM-02.04.01.03).

Lo que hace que un consentimiento valga algo no es la casilla: es **poder
demostrar dos años después** quién la marcó, cuándo, desde dónde y aceptando qué
texto. Casi todos los sistemas guardan el «sí» y tiran el resto, y entonces la
prueba que se enseña ante una reclamación es una fila que dice `acepta = true`.

Las decisiones:

**El doble opt-in es opcional y no simbólico.** Donde la ley lo exige, un alta
sin confirmar **no es un alta**: no se le escribe. Registrarla como válida y
mandar mientras tanto es peor que no tenerlo, porque da la apariencia de rigor.

**La confirmación caduca.** Un enlace que vale para siempre acaba usándose meses
después por alguien que ya no recuerda haberse apuntado.

**Un consentimiento renovable que nadie renueva se apaga solo.** Si al vencer
siguiera valiendo hasta que alguien lo revise, la caducidad sería decorativa.

**Las cookies se guardan por categoría y con la versión del texto.** Un «acepto»
sobre un aviso que después cambió no prueba nada sobre el aviso nuevo, y es
exactamente lo que se discute cuando llega una reclamación.

**Una plantilla bloqueada no se puede saltar desde la campaña.** Si el bloqueo
fuese un aviso, se ignoraría el día que hay prisa — que es justo el día en que se
manda a otro país el texto que no cumple allí.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from crmcore.audit.chain import registrar
from crmcore.db.base import Base, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

logger = get_logger(__name__)

# Categorías de cookies. Lista cerrada y con «necesarias» dentro a propósito:
# no se piden, pero tienen que constar — un panel que solo enseña lo opcional
# hace creer que no hay nada más.
CATEGORIAS_COOKIES = ("necesarias", "preferencias", "analitica", "publicidad", "terceros")

# Las que no dependen del consentimiento. Se declara aquí para que el panel no
# pueda ofrecer un interruptor que no apaga nada, que es la forma más rápida de
# que el usuario deje de creerse el panel entero.
SIN_CONSENTIMIENTO = ("necesarias",)

ESTADOS_OPTIN = ("pendiente", "confirmado", "caducado", "rechazado")


class ConfirmacionOptin(Base, TimestampMixin):
    """Un alta pendiente de confirmar (CRM-02.04.02.02)."""

    __tablename__ = "confirmaciones_optin"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    canal: Mapped[str] = mapped_column(String(20), nullable=False, default="email")
    destino: Mapped[str] = mapped_column(
        String(320), nullable=False, info={"sensibilidad": "personal"}
    )
    # El token va cifrado por su propia naturaleza: es un secreto de un solo uso.
    # Se guarda su valor porque el enlace que recibe la persona lo lleva, y
    # compararlo es lo único que demuestra que confirmó quien recibió el correo.
    token: Mapped[str] = mapped_column(String(64), nullable=False)
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="pendiente")
    # Qué texto aceptó. Sin él, la prueba es una casilla; con él, es una prueba.
    texto_aceptado: Mapped[str] = mapped_column(Text, nullable=False, default="")
    finalidad: Mapped[str] = mapped_column(String(60), nullable=False, default="comercial")
    ip_solicitud: Mapped[str | None] = mapped_column(
        String(64), nullable=True, info={"sensibilidad": "personal"}
    )
    ip_confirmacion: Mapped[str | None] = mapped_column(
        String(64), nullable=True, info={"sensibilidad": "personal"}
    )
    caduca_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_optin_pendientes", "tenant_id", "canal", "destino", "estado"),
        Index("ix_optin_token", "tenant_id", "token"),
    )


class ConsentimientoCookies(Base, TimestampMixin):
    """Lo que un visitante aceptó, por categoría (CRM-07.03.01.08)."""

    __tablename__ = "consentimientos_cookies"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    # Identificador del visitante en el navegador. No es una persona
    # identificada, y por eso se guarda aparte del contacto: mezclarlos haría
    # que una visita anónima creara una ficha, que es justo lo que no se puede
    # hacer sin consentimiento.
    visitante: Mapped[str] = mapped_column(String(80), nullable=False)
    contacto_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    # {categoria: bool}
    categorias: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # La versión del aviso que se le enseñó. Un «acepto» sobre un texto que
    # después cambió no prueba nada sobre el texto nuevo.
    version_aviso: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    ip: Mapped[str | None] = mapped_column(
        String(64), nullable=True, info={"sensibilidad": "personal"}
    )
    agente: Mapped[str | None] = mapped_column(String(300), nullable=True)
    decidido_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Cuándo hay que volver a preguntar. Sin esto, un consentimiento de hace
    # cuatro años sigue justificando el rastreo de hoy.
    caduca_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_cookies_visitante", "tenant_id", "visitante", "decidido_at"),)


class ReglaContenido(Base, TimestampMixin):
    """Qué se puede mandar por marca, país e idioma (CRM-02.04.01.03)."""

    __tablename__ = "reglas_contenido"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    marca: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    pais: Mapped[str] = mapped_column(String(2), nullable=False, default="")
    idioma: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    # Plantillas que SOLO pueden usarse tal cual: ni editar el cuerpo ni sustituir
    # los textos legales. Bloqueada de verdad, no «recomendada».
    plantillas_bloqueadas: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Texto que tiene que aparecer sí o sí: la mención legal, la dirección
    # postal, el enlace de baja. Se comprueba, no se recuerda.
    exige_textos: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    prohibe_textos: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notas: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (
        UniqueConstraint("tenant_id", "marca", "pais", "idioma", name="uq_regla_contenido"),
        Index("ix_reglas_contenido", "tenant_id", "activa"),
    )


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


# ── Doble opt-in (CRM-02.04.02.02) ────────────────────────────────────────


def pedir_confirmacion(
    uow: UnidadDeTrabajo,
    *,
    destino: str,
    canal: str = "email",
    finalidad: str = "comercial",
    texto_aceptado: str = "",
    ip: str = "",
    horas_validez: int = 72,
) -> dict[str, Any]:
    """Crea un alta **pendiente de confirmar**.

    Mientras no se confirme, no es un alta: quien pregunte si se le puede
    escribir recibe que no. Registrarla como válida «hasta que confirme» y mandar
    mientras tanto es peor que no tener doble opt-in, porque da apariencia de
    rigor a lo contrario.
    """
    destino = destino.strip().lower()
    if not destino:
        raise ErrorValidacion(
            "Hace falta el destino que tiene que confirmar",
            error_code="optin.sin_destino",
        )
    if not texto_aceptado.strip():
        raise ErrorValidacion(
            "Hace falta el texto que se le enseña. Sin él, la prueba de este "
            "consentimiento es una casilla marcada, que no prueba nada.",
            error_code="optin.sin_texto",
        )

    fila = ConfirmacionOptin(
        tenant_id=uow.tenant_id,
        canal=canal,
        destino=destino,
        token=secrets.token_urlsafe(32)[:64],
        finalidad=finalidad,
        texto_aceptado=texto_aceptado,
        ip_solicitud=ip or None,
        caduca_at=_ahora() + timedelta(hours=max(1, int(horas_validez))),
    )
    uow.db.add(fila)
    uow.db.flush()
    logger.info("marketing.optin_pedido", canal=canal, finalidad=finalidad)
    return {
        "confirmacion_id": str(fila.id),
        "token": fila.token,
        "caduca_at": fila.caduca_at.isoformat(),
        "estado": fila.estado,
        "se_le_puede_escribir": False,
        "porque": (
            "Pendiente de confirmar. Hasta que confirme no es un alta, y "
            "escribirle mientras tanto sería exactamente lo que el doble opt-in "
            "existe para impedir."
        ),
    }


def confirmar(uow: UnidadDeTrabajo, *, token: str, ip: str = "") -> dict[str, Any]:
    """Confirma un alta con su enlace.

    El enlace **caduca**: uno que vale para siempre acaba usándose meses después
    por alguien que ya no recuerda haberse apuntado, y ese consentimiento no
    sostiene nada.
    """
    fila = (
        uow.db.execute(
            select(ConfirmacionOptin).where(
                ConfirmacionOptin.tenant_id == uow.tenant_id,
                ConfirmacionOptin.token == token,
            )
        )
        .scalars()
        .first()
    )
    if fila is None:
        raise NoEncontrado("Ese enlace de confirmación no existe", error_code="optin.no_encontrado")
    if fila.estado == "confirmado":
        # Confirmar dos veces no es un error: la gente pincha el enlace otra vez.
        # Lo que no puede es mover la fecha, porque la que prueba el
        # consentimiento es la primera.
        return {"confirmacion_id": str(fila.id), "estado": "confirmado", "ya_estaba": True}
    caduca = (
        fila.caduca_at if fila.caduca_at.tzinfo else fila.caduca_at.replace(tzinfo=timezone.utc)
    )
    if caduca < _ahora():
        fila.estado = "caducado"
        uow.db.flush()
        raise Conflicto(
            "El enlace de confirmación ha caducado. Hay que volver a pedirla: un "
            "enlace eterno acaba confirmando altas que nadie recuerda haber pedido.",
            error_code="optin.caducado",
        )

    fila.estado = "confirmado"
    fila.confirmado_at = _ahora()
    fila.ip_confirmacion = ip or None
    uow.db.flush()

    # Y se traslada al consentimiento del canal, que es lo que mira el envío.
    from services.marketing.canales import fijar_consentimiento

    fijar_consentimiento(
        uow,
        canal=fila.canal,
        destino=fila.destino,
        acepta=True,
        origen="doble_optin",
        prueba=f"Confirmado el {fila.confirmado_at:%Y-%m-%d %H:%M} · {fila.texto_aceptado[:200]}",
        ip=ip,
    )
    registrar(
        uow.db,
        accion="marketing.optin_confirmado",
        objeto="confirmacion_optin",
        objeto_id=fila.id,
        datos={"canal": fila.canal, "finalidad": fila.finalidad},
        tenant_id=uow.tenant_id,
    )
    return {
        "confirmacion_id": str(fila.id),
        "estado": "confirmado",
        "ya_estaba": False,
        "se_le_puede_escribir": True,
    }


def caducar_pendientes(db: Session, tenant_id: UUID, *, ahora: datetime | None = None) -> int:
    """Marca como caducadas las confirmaciones pasadas de plazo.

    Se hace explícitamente y no al vuelo: una pendiente eterna en la tabla parece
    un alta a medio camino, y alguien acaba «ayudando» a confirmarla a mano.
    """
    momento = ahora or _ahora()
    filas = (
        db.execute(
            select(ConfirmacionOptin).where(
                ConfirmacionOptin.tenant_id == tenant_id,
                ConfirmacionOptin.estado == "pendiente",
                ConfirmacionOptin.caduca_at < momento,
            )
        )
        .scalars()
        .all()
    )
    for fila in filas:
        fila.estado = "caducado"
    db.flush()
    return len(filas)


def renovaciones_pendientes(
    db: Session, tenant_id: UUID, *, dias_aviso: int = 30, ahora: datetime | None = None
) -> dict[str, Any]:
    """Consentimientos de canal que caducan pronto o ya caducaron.

    Un consentimiento renovable **que nadie renueva se apaga**: el envío consulta
    la caducidad, así que no hace falta que alguien revise la lista para que deje
    de valer. Esta lista sirve para renovarlo antes, no para que siga valiendo
    mientras tanto.
    """
    from services.marketing.canales import ConsentimientoCanal

    momento = ahora or _ahora()
    limite = momento + timedelta(days=max(1, int(dias_aviso)))
    filas = (
        db.execute(
            select(ConsentimientoCanal).where(
                ConsentimientoCanal.tenant_id == tenant_id,
                ConsentimientoCanal.acepta.is_(True),
                ConsentimientoCanal.caduca_at.is_not(None),
                ConsentimientoCanal.caduca_at <= limite,
            )
        )
        .scalars()
        .all()
    )
    caducados = [f for f in filas if f.caduca_at and _con_tz(f.caduca_at) < momento]
    return {
        "por_caducar": [
            {"canal": f.canal, "destino": f.destino, "caduca_at": f.caduca_at.isoformat()}
            for f in filas
            if f not in caducados
        ],
        "ya_caducados": [
            {"canal": f.canal, "destino": f.destino, "caduco_at": f.caduca_at.isoformat()}
            for f in caducados
        ],
        "cuantos": len(filas),
        "que_significa": (
            "Los ya caducados NO se pueden usar: el envío lo comprueba solo. Esta "
            "lista sirve para renovarlos a tiempo, no para seguir enviando."
        ),
    }


def _con_tz(valor: datetime) -> datetime:
    return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)


# ── Cookies y rastreo (CRM-07.03.01.08) ───────────────────────────────────


def registrar_cookies(
    uow: UnidadDeTrabajo,
    *,
    visitante: str,
    categorias: dict[str, bool],
    version_aviso: str,
    ip: str = "",
    agente: str = "",
    contacto_id: UUID | None = None,
    meses_validez: int = 12,
) -> dict[str, Any]:
    """Guarda lo que un visitante aceptó, por categoría y con la versión del aviso.

    **Cada decisión es una fila nueva.** Actualizar la anterior borraría la prueba
    de lo que se aceptó cuando se puso la cookie, que es justo lo que se discute.
    """
    if not visitante.strip():
        raise ErrorValidacion(
            "Hace falta el identificador del visitante", error_code="cookies.sin_visitante"
        )
    if not version_aviso.strip():
        raise ErrorValidacion(
            "Hace falta la versión del aviso que se enseñó: un «acepto» sobre un "
            "texto que después cambió no prueba nada sobre el texto nuevo.",
            error_code="cookies.sin_version",
        )
    desconocidas = sorted(set(categorias) - set(CATEGORIAS_COOKIES))
    if desconocidas:
        raise ErrorValidacion(
            f"Categorías de cookies no reconocidas: {desconocidas}",
            error_code="cookies.categoria_desconocida",
            detalle={"admitidas": list(CATEGORIAS_COOKIES)},
        )

    # Las necesarias no se piden: se informan. Guardar un «false» sobre ellas
    # daría un panel con un interruptor que no apaga nada.
    limpias = {c: bool(v) for c, v in categorias.items() if c not in SIN_CONSENTIMIENTO}
    limpias["necesarias"] = True

    fila = ConsentimientoCookies(
        tenant_id=uow.tenant_id,
        visitante=visitante.strip(),
        contacto_id=contacto_id,
        categorias=limpias,
        version_aviso=version_aviso.strip(),
        ip=ip or None,
        agente=(agente or "")[:300] or None,
        decidido_at=_ahora(),
        caduca_at=_ahora() + timedelta(days=30 * max(1, int(meses_validez))),
    )
    uow.db.add(fila)
    uow.db.flush()
    return {
        "id": str(fila.id),
        "categorias": limpias,
        "caduca_at": fila.caduca_at.isoformat() if fila.caduca_at else None,
        "necesarias_no_se_piden": (
            "Las cookies necesarias no dependen del consentimiento y por eso no se "
            "ofrecen como interruptor: un botón que no apaga nada hace que el "
            "usuario deje de creerse el panel entero."
        ),
    }


def puede_rastrear(
    db: Session,
    tenant_id: UUID,
    *,
    visitante: str,
    categoria: str,
    version_aviso: str = "",
    ahora: datetime | None = None,
) -> dict[str, Any]:
    """Si se puede activar una categoría de rastreo para este visitante.

    Sin decisión previa la respuesta es **no**, no «todavía no ha dicho que no».
    El consentimiento tiene que ser previo: tratar el silencio como un sí es la
    infracción más común de todas.
    """
    momento = ahora or _ahora()
    if categoria in SIN_CONSENTIMIENTO:
        return {"puede": True, "porque": "Categoría necesaria: no depende del consentimiento."}

    fila = (
        db.execute(
            select(ConsentimientoCookies)
            .where(
                ConsentimientoCookies.tenant_id == tenant_id,
                ConsentimientoCookies.visitante == visitante,
            )
            .order_by(ConsentimientoCookies.decidido_at.desc())
        )
        .scalars()
        .first()
    )
    if fila is None:
        return {
            "puede": False,
            "porque": (
                "No consta ninguna decisión de este visitante. El silencio no es un "
                "sí: el consentimiento tiene que ser previo."
            ),
        }
    if fila.caduca_at and _con_tz(fila.caduca_at) < momento:
        return {
            "puede": False,
            "porque": (
                f"La decisión es del {fila.decidido_at.date()} y ha caducado. Hay que "
                "volver a preguntar."
            ),
        }
    if version_aviso and fila.version_aviso != version_aviso:
        return {
            "puede": False,
            "porque": (
                f"Aceptó la versión «{fila.version_aviso}» del aviso y ahora rige la "
                f"«{version_aviso}». Un «acepto» sobre un texto que cambió no prueba "
                "nada sobre el nuevo."
            ),
        }
    permitido = bool((fila.categorias or {}).get(categoria))
    return {
        "puede": permitido,
        "decidido_at": fila.decidido_at.isoformat(),
        "version_aviso": fila.version_aviso,
        "porque": (
            f"Aceptó «{categoria}» el {fila.decidido_at.date()}."
            if permitido
            else f"No aceptó «{categoria}»."
        ),
    }


# ── Cumplimiento del contenido (CRM-02.04.01.03) ──────────────────────────


def declarar_regla(
    uow: UnidadDeTrabajo,
    *,
    marca: str = "",
    pais: str = "",
    idioma: str = "",
    plantillas_bloqueadas: list[str] | None = None,
    exige_textos: list[str] | None = None,
    prohibe_textos: list[str] | None = None,
    notas: str = "",
) -> ReglaContenido:
    """Declara qué se puede mandar en un ámbito.

    Vacío significa **cualquiera**: una regla sin país se aplica a todos los
    países. Es lo contrario de lo que haría un filtro, y por eso se dice: así la
    regla general se escribe una vez y las excepciones se añaden encima.
    """
    fila = (
        uow.db.execute(
            select(ReglaContenido).where(
                ReglaContenido.tenant_id == uow.tenant_id,
                ReglaContenido.marca == marca,
                ReglaContenido.pais == pais,
                ReglaContenido.idioma == idioma,
            )
        )
        .scalars()
        .first()
    )
    if fila is None:
        fila = ReglaContenido(tenant_id=uow.tenant_id, marca=marca, pais=pais, idioma=idioma)
        uow.db.add(fila)
    if plantillas_bloqueadas is not None:
        fila.plantillas_bloqueadas = sorted(set(plantillas_bloqueadas))
    if exige_textos is not None:
        fila.exige_textos = list(exige_textos)
    if prohibe_textos is not None:
        fila.prohibe_textos = list(prohibe_textos)
    fila.notas = notas or fila.notas
    fila.activa = True
    uow.db.flush()
    return fila


def comprobar_contenido(
    db: Session,
    tenant_id: UUID,
    *,
    cuerpo: str,
    plantilla: str = "",
    marca: str = "",
    pais: str = "",
    idioma: str = "",
    cuerpo_de_la_plantilla: str = "",
) -> dict[str, Any]:
    """Si este contenido se puede mandar en este ámbito, y qué le falta.

    **Una plantilla bloqueada no se puede editar.** Si el bloqueo fuese un aviso,
    se ignoraría el día que hay prisa, que es justo el día en que se manda a otro
    país el texto que allí no cumple. Se compara con el cuerpo original: cambiar
    una palabra de una plantilla legal la deja de ser.

    Y los textos obligatorios se **comprueban**, no se recuerdan en una guía:
    faltar la dirección postal o el enlace de baja es lo que convierte un envío
    legítimo en spam a efectos legales.
    """
    reglas = (
        db.execute(
            select(ReglaContenido).where(
                ReglaContenido.tenant_id == tenant_id, ReglaContenido.activa.is_(True)
            )
        )
        .scalars()
        .all()
    )
    # Se aplican todas las que encajan, de la general a la concreta: el vacío es
    # comodín, así que una regla sin país vale para todos.
    aplicables = [
        r
        for r in reglas
        if (not r.marca or r.marca == marca)
        and (not r.pais or r.pais == pais)
        and (not r.idioma or r.idioma == idioma)
    ]

    faltan: list[str] = []
    prohibidos: list[str] = []
    bloqueada = False
    for regla in aplicables:
        for exigido in regla.exige_textos or []:
            if str(exigido).lower() not in cuerpo.lower():
                faltan.append(str(exigido))
        for prohibido in regla.prohibe_textos or []:
            if str(prohibido).lower() in cuerpo.lower():
                prohibidos.append(str(prohibido))
        if plantilla and plantilla in (regla.plantillas_bloqueadas or []):
            bloqueada = True

    alterada = bool(
        bloqueada and cuerpo_de_la_plantilla and cuerpo.strip() != cuerpo_de_la_plantilla.strip()
    )
    motivos: list[str] = []
    if faltan:
        motivos.append(f"Faltan textos obligatorios: {', '.join(sorted(set(faltan)))}")
    if prohibidos:
        motivos.append(f"Contiene textos prohibidos aquí: {', '.join(sorted(set(prohibidos)))}")
    if alterada:
        motivos.append(
            f"La plantilla «{plantilla}» está bloqueada para este ámbito y el cuerpo "
            "no coincide con el original: cambiar una palabra de una plantilla legal "
            "la deja de ser"
        )

    return {
        "se_puede_mandar": not motivos,
        "reglas_aplicadas": len(aplicables),
        # Que no haya reglas no es lo mismo que cumplir: se dice, para que nadie
        # lea un «se puede mandar» como una aprobación de cumplimiento.
        "comprobado": bool(aplicables),
        "aviso": (
            ""
            if aplicables
            else "No hay ninguna regla declarada para esta marca, país e idioma: "
            "esto no se ha comprobado contra nada."
        ),
        "motivos": motivos,
        "plantilla_bloqueada": bloqueada,
    }
