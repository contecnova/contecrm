"""Canales de ejecución: SMS, WhatsApp, push, landings y entregabilidad
(CRM-02.03.02.01, CRM-02.03.02.02, CRM-02.03.02.03, CRM-02.03.02.06,
CRM-02.03.01.02, CRM-02.03.01.03, CRM-02.03.01.06, CRM-02.02.02.05).

**Un canal es configuración, no un módulo por proveedor.** Sobre el transporte
declarativo que ya existe: Twilio, MessageBird o el agregador del cliente son la
misma cosa con otra dirección y otra credencial. Un módulo por casa convierte cada
implantación con otro proveedor en una versión del producto.

Lo que sí es propio de cada canal, y por eso se declara:

**Cada canal tiene su forma de decir que no.** En SMS es una palabra —«BAJA»—, en
WhatsApp es la ventana de 24 horas y la plantilla aprobada, en push es el permiso
del navegador. Tratarlos igual produce el mensaje que no se puede parar.

**El consentimiento es por canal, no por persona.** Alguien que acepta el correo
no ha aceptado el SMS, y mandarle uno «porque ya nos dio permiso» es exactamente
lo que sanciona un regulador.

**La entregabilidad se mide antes de mandar, no después.** Un dominio sin SPF,
sin DKIM o sin DMARC no rebota: llega a basura, y eso no aparece en ningún
informe de rebotes — aparece como una campaña que nadie abrió.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from crmcore.db.base import Base, SoftDeleteMixin, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
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

# Los canales que el producto sabe ejecutar. Cerrado porque cada uno tiene reglas
# distintas de consentimiento y de baja, y uno libre acabaría como un correo mal
# etiquetado.
CANALES = ("email", "sms", "whatsapp", "push", "rcs")

# Cómo se da de baja alguien en cada canal. No es cosmético: en SMS la ley exige
# que baste responder una palabra, y en WhatsApp la baja la gestiona el propio
# proveedor.
BAJAS_POR_CANAL: dict[str, str] = {
    "email": "enlace en el pie",
    "sms": "palabra clave de respuesta",
    "rcs": "palabra clave de respuesta",
    "whatsapp": "botón de la plantilla y bloqueo del proveedor",
    "push": "permiso del navegador o del dispositivo",
}
# Palabras que cuentan como baja en SMS. Se comparan sin acentos ni mayúsculas.
PALABRAS_BAJA = ("baja", "stop", "cancelar", "unsubscribe", "no")


class Canal(Base, TimestampMixin, SoftDeleteMixin):
    """Un canal configurado (CRM-02.03.02.01, .02, .03)."""

    __tablename__ = "canales_marketing"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(60), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)
    # La conexión declarativa por la que se manda. No hay código por proveedor.
    conexion_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    # El remitente: número corto, número largo, identificador de WhatsApp.
    remitente: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Horas en las que NO se manda. Un SMS a las once de la noche despierta a
    # alguien, y el coste de eso no es una baja: es una queja.
    silencio_desde: Mapped[int] = mapped_column(Integer, nullable=False, default=21)
    silencio_hasta: Mapped[int] = mapped_column(Integer, nullable=False, default=9)
    coste_mensaje: Mapped[str | None] = mapped_column(String(20), nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "clave", name="uq_canal_marketing"),
        Index("ix_canales_tipo", "tenant_id", "tipo", "activo"),
    )


class ConsentimientoCanal(Base, TimestampMixin):
    """Quién aceptó qué, en qué canal (CRM-02.03.02.01, .02).

    **Por canal y no por persona.** Alguien que acepta el correo no ha aceptado
    el SMS, y mandarle uno «porque ya nos dio permiso» es exactamente lo que
    sanciona un regulador.
    """

    __tablename__ = "consentimientos_canal"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    canal: Mapped[str] = mapped_column(String(20), nullable=False)
    # La dirección en ese canal: correo, teléfono, token de push.
    destino: Mapped[str] = mapped_column(String(320), nullable=False)
    acepta: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Cómo lo dijo. Es la prueba, y sin ella «¿quién autorizó esto?» no tiene
    # respuesta.
    origen: Mapped[str] = mapped_column(String(40), nullable=False, default="formulario")
    prueba: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip: Mapped[str | None] = mapped_column(
        String(64), nullable=True, info={"sensibilidad": "personal"}
    )
    cambiado_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Hasta cuándo vale. Vacío = no caduca.
    #
    # Existía en el código que lo consulta y NO existía en la tabla: la lista de
    # renovaciones pendientes preguntaba por `caduca_at` y reventaba con
    # `AttributeError`, así que esa pantalla nunca funcionó. Y lo que decía su
    # documentación —«el envío consulta la caducidad»— era falso: sin columna no
    # se consultaba nada, y un consentimiento con fecha de caducidad seguía
    # valiendo para siempre.
    caduca_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    # Para WhatsApp: cuándo escribió por última vez. De ahí sale la ventana de 24
    # horas, fuera de la cual solo se puede mandar una plantilla aprobada.
    ultimo_mensaje_entrante_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "canal", "destino", name="uq_consentimiento_canal"),
        Index("ix_consentimientos_destino", "tenant_id", "destino"),
    )


class PlantillaCanal(Base, TimestampMixin):
    """Una plantilla de un canal que las exige aprobadas (CRM-02.03.02.02)."""

    __tablename__ = "plantillas_canal"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    canal: Mapped[str] = mapped_column(String(20), nullable=False)
    clave: Mapped[str] = mapped_column(String(80), nullable=False)
    idioma: Mapped[str] = mapped_column(String(10), nullable=False, default="es")
    cuerpo: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # pendiente | aprobada | rechazada. Lo decide el proveedor, no nosotros:
    # mandar una plantilla no aprobada por WhatsApp no falla, se descarta en
    # silencio y el mensaje no llega nunca.
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="pendiente")
    motivo_rechazo: Mapped[str | None] = mapped_column(Text, nullable=True)
    referencia_externa: Mapped[str | None] = mapped_column(String(200), nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "canal", "clave", "idioma", name="uq_plantilla_canal"),
    )


class Landing(Base, TimestampMixin, SoftDeleteMixin):
    """Una página de aterrizaje con su formulario (CRM-02.03.02.06)."""

    __tablename__ = "landings"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(80), nullable=False)
    titulo: Mapped[str] = mapped_column(String(300), nullable=False)
    # Los campos del formulario, con lo que se pre-rellena para quien ya conoce.
    campos: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Qué canales pide consentimiento la página. Sin declararlo, un formulario
    # que recoge el teléfono no autoriza a mandar SMS: recoger no es consentir.
    pide_consentimiento: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    canal_captura: Mapped[str | None] = mapped_column(String(80), nullable=True)
    visitas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    envios: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (UniqueConstraint("tenant_id", "clave", name="uq_landing_clave"),)


class DominioEnvio(Base, TimestampMixin, SoftDeleteMixin):
    """Un dominio de envío y su estado de autenticación (CRM-02.03.01.03)."""

    __tablename__ = "dominios_envio"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    dominio: Mapped[str] = mapped_column(String(253), nullable=False)
    # promocional | transaccional
    uso: Mapped[str] = mapped_column(String(20), nullable=False, default="promocional")
    spf: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    dkim: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # none | quarantine | reject. Vacío = sin registro DMARC.
    dmarc: Mapped[str | None] = mapped_column(String(20), nullable=True)
    bimi: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ip_dedicada: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Calentamiento: desde cuándo y cuántos se pueden mandar hoy. Una IP nueva
    # que manda cien mil el primer día se quema, y quemarla cuesta semanas.
    calentamiento_desde: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    comprobado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("tenant_id", "dominio", name="uq_dominio_envio"),)


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _con_tz(v: datetime | None) -> datetime | None:
    if v is None:
        return None
    return v if v.tzinfo else v.replace(tzinfo=timezone.utc)


# ── Consentimiento por canal (CRM-02.03.02.01, .02) ───────────────────────


def fijar_consentimiento(
    uow: UnidadDeTrabajo,
    *,
    canal: str,
    destino: str,
    acepta: bool,
    origen: str = "formulario",
    prueba: str = "",
    ip: str = "",
    caduca_at: datetime | None = None,
) -> ConsentimientoCanal:
    """Anota que alguien acepta —o deja de aceptar— un canal.

    El consentimiento es **por canal**: quien aceptó el correo no ha aceptado el
    SMS. Y se guarda la **prueba** —de dónde salió—, porque sin ella la respuesta
    a «¿quién autorizó esto?» es «no consta», que ante un regulador equivale a
    «nadie».
    """
    if canal not in CANALES:
        raise ErrorValidacion(
            f"Canal «{canal}» no válido.",
            error_code="canal.no_valido",
            detalle={"validos": list(CANALES)},
        )
    destino = destino.strip().lower()
    if not destino:
        raise ErrorValidacion(
            "Hace falta el destino (correo, teléfono o token).",
            error_code="canal.sin_destino",
        )
    fila = uow.db.execute(
        select(ConsentimientoCanal).where(
            ConsentimientoCanal.tenant_id == uow.tenant_id,
            ConsentimientoCanal.canal == canal,
            ConsentimientoCanal.destino == destino,
        )
    ).scalar_one_or_none()
    if fila is None:
        fila = ConsentimientoCanal(tenant_id=uow.tenant_id, canal=canal, destino=destino)
        uow.db.add(fila)
    fila.acepta = acepta
    fila.caduca_at = caduca_at
    fila.origen = origen
    fila.prueba = prueba or None
    fila.ip = ip or None
    fila.cambiado_at = _ahora()
    uow.db.flush()
    return fila


def _sin_tildes(texto: str) -> str:
    import unicodedata

    return "".join(
        c
        for c in unicodedata.normalize("NFD", texto.strip().lower())
        if unicodedata.category(c) != "Mn"
    )


def es_palabra_de_baja(texto: str) -> bool:
    """Si un mensaje entrante pide la baja.

    Se compara **la primera palabra sin acentos ni mayúsculas**: quien escribe
    «BAJA» desde el móvil manda tantas variantes como teclados hay, y exigir una
    exacta deja sin efecto una baja que la persona sí pidió — que es lo que
    acaba en denuncia.
    """
    primera = _sin_tildes(texto).split()[:1]
    return bool(primera) and primera[0] in PALABRAS_BAJA


def procesar_entrante(
    uow: UnidadDeTrabajo, *, canal: str, destino: str, texto: str
) -> dict[str, Any]:
    """Procesa un mensaje que llega del destinatario.

    Dos cosas a la vez, y las dos importan: si es una **baja**, se aplica; y en
    cualquier caso **abre la ventana de 24 horas** de WhatsApp, porque el que
    escribe autoriza a contestarle sin plantilla.
    """
    destino = destino.strip().lower()
    baja = es_palabra_de_baja(texto)
    fila = uow.db.execute(
        select(ConsentimientoCanal).where(
            ConsentimientoCanal.tenant_id == uow.tenant_id,
            ConsentimientoCanal.canal == canal,
            ConsentimientoCanal.destino == destino,
        )
    ).scalar_one_or_none()
    if fila is None:
        fila = ConsentimientoCanal(
            tenant_id=uow.tenant_id, canal=canal, destino=destino, acepta=not baja
        )
        uow.db.add(fila)
    fila.ultimo_mensaje_entrante_at = _ahora()
    if baja:
        fila.acepta = False
        fila.origen = "respuesta"
        fila.prueba = texto[:500]
        fila.cambiado_at = _ahora()
    uow.db.flush()

    if baja:
        uow.emitir(
            "channel.optout",
            subject=("consentimiento", fila.id),
            data={"canal": canal, "destino": destino, "texto": texto[:200]},
        )
    return {"baja": baja, "ventana_abierta": True, "canal": canal}


def ventana_abierta(fila: ConsentimientoCanal | None, *, horas: int = 24) -> bool:
    """Si se le puede escribir libremente por WhatsApp.

    Fuera de la ventana solo vale una **plantilla aprobada**. Mandar texto libre
    fuera de ella no da error: el proveedor lo descarta y el mensaje no llega
    nunca, que es peor que un error porque nadie se entera.
    """
    if fila is None or fila.ultimo_mensaje_entrante_at is None:
        return False
    return (_ahora() - _con_tz(fila.ultimo_mensaje_entrante_at)) < timedelta(hours=horas)


# ── Se puede mandar o no (CRM-02.03.02.01, .02, .03) ──────────────────────


def comprobar_envio(
    db: Session,
    tenant_id: UUID,
    *,
    canal_clave: str,
    destino: str,
    plantilla: str = "",
    ahora: datetime | None = None,
    dominio: str = "",
    enviados_hoy: int = 0,
) -> dict[str, Any]:
    """Todo lo que hay que mirar antes de mandar por un canal, en una llamada.

    Seis comprobaciones y ninguna opcional: el canal activo, el consentimiento
    **de ese canal**, la hora de silencio, la ventana de WhatsApp, la plantilla
    aprobada y **el tope de calentamiento del dominio**. Repartidas por el
    código, la que se olvida es siempre la del consentimiento.

    La sexta se añadió el 05-10-2026 al auditar la entregabilidad: el tope diario
    de una IP en calentamiento se calculaba, salía en la pantalla con su aviso
    —«hoy como mucho N envíos»— y **no lo aplicaba nadie**. Una IP nueva que
    manda cien mil el primer día se quema, y quemarla cuesta semanas en las que
    no llega nada, ni las campañas ni las facturas.

    `enviados_hoy` lo pone quien manda, porque es quien lleva la cuenta de la
    tanda. Cero —el valor de serie— significa que empieza ahora.
    """
    momento = _con_tz(ahora) or _ahora()
    canal = db.execute(
        select(Canal).where(Canal.tenant_id == tenant_id, Canal.clave == canal_clave)
    ).scalar_one_or_none()
    if canal is None:
        raise NoEncontrado("El canal no existe", error_code="canal.no_encontrado")

    motivos: list[str] = []
    if not canal.activo:
        motivos.append(f"El canal «{canal.clave}» está desactivado.")

    destino_norm = destino.strip().lower()
    consentimiento = db.execute(
        select(ConsentimientoCanal).where(
            ConsentimientoCanal.tenant_id == tenant_id,
            ConsentimientoCanal.canal == canal.tipo,
            ConsentimientoCanal.destino == destino_norm,
        )
    ).scalar_one_or_none()
    if consentimiento is None or not consentimiento.acepta:
        motivos.append(
            f"No consta consentimiento para «{canal.tipo}». Haberlo dado para otro "
            "canal no vale: aceptar el correo no es aceptar el SMS."
        )
    elif consentimiento.caduca_at and (_con_tz(consentimiento.caduca_at) or _ahora()) < _ahora():
        # Un consentimiento caducado no vale, y hasta ahora valía: la columna no
        # existía, así que nadie la miraba. Se comprueba aquí, en el envío, y no
        # en una revisión periódica: si dependiera de que alguien repase la lista,
        # la caducidad sería decorativa.
        motivos.append(
            f"El consentimiento para «{canal.tipo}» caducó el "
            f"{consentimiento.caduca_at.date()}. Hay que volver a pedirlo."
        )

    # Horas de silencio. Un SMS a las once de la noche despierta a alguien, y el
    # coste de eso no es una baja: es una queja.
    hora = momento.hour
    desde, hasta = canal.silencio_desde, canal.silencio_hasta
    en_silencio = (hora >= desde or hora < hasta) if desde > hasta else (desde <= hora < hasta)
    if en_silencio and canal.tipo in ("sms", "whatsapp", "push", "rcs"):
        motivos.append(f"Son las {hora}:00 y el canal calla de {desde}:00 a {hasta}:00.")

    necesita_plantilla = False
    if canal.tipo == "whatsapp" and not ventana_abierta(consentimiento):
        necesita_plantilla = True
        if not plantilla:
            motivos.append(
                "Fuera de la ventana de 24 horas solo se puede mandar una "
                "plantilla aprobada, y no se ha indicado ninguna."
            )

    if plantilla:
        ficha = db.execute(
            select(PlantillaCanal).where(
                PlantillaCanal.tenant_id == tenant_id,
                PlantillaCanal.canal == canal.tipo,
                PlantillaCanal.clave == plantilla,
            )
        ).scalar_one_or_none()
        if ficha is None:
            motivos.append(f"La plantilla «{plantilla}» no existe para ese canal.")
        elif ficha.estado != "aprobada":
            # Mandar una no aprobada no falla: el proveedor la descarta y el
            # mensaje no llega nunca, que es peor porque nadie se entera.
            motivos.append(
                f"La plantilla «{plantilla}» está «{ficha.estado}». El proveedor "
                "la descartaría sin avisar y el mensaje no llegaría."
            )

    # EL TOPE DE CALENTAMIENTO. Se mira al final porque es el único que depende
    # de cuánto se lleva mandado hoy, no de quién recibe.
    calentamiento: dict[str, Any] | None = None
    if dominio:
        estado = estado_dominio(db, tenant_id, dominio)
        if estado.get("calentando"):
            calentamiento = {
                "dia": estado["dia_de_calentamiento"],
                "tope_hoy": estado["tope_hoy"],
                "enviados_hoy": enviados_hoy,
            }
            if enviados_hoy >= int(estado["tope_hoy"] or 0):
                motivos.append(
                    f"La IP está en calentamiento: hoy el tope son "
                    f"{estado['tope_hoy']} envíos y ya van {enviados_hoy}. Pasarse "
                    "quema la IP, y quemarla cuesta semanas en las que no llega "
                    "nada — ni las campañas ni las facturas."
                )

    return {
        "se_puede_mandar": not motivos,
        "motivos": motivos,
        "canal": canal.tipo,
        "necesita_plantilla": necesita_plantilla,
        "ventana_abierta": ventana_abierta(consentimiento),
        "como_se_da_de_baja": BAJAS_POR_CANAL.get(canal.tipo, ""),
        # `None` cuando el dominio no está calentando o no se ha dicho cuál es:
        # quien lo pinta no tiene que saber nada de la progresión.
        "calentamiento": calentamiento,
    }


# ── Mejor hora de envío (CRM-02.02.02.05) ─────────────────────────────────


def mejor_hora(
    db: Session, tenant_id: UUID, objeto_id: UUID, *, minimo: int = 10
) -> dict[str, Any]:
    """A qué hora abre esta persona, si se sabe.

    Se mira **cuándo pasó a «abierto» como miembro de campaña**, que es el único
    sitio donde ese dato existe de verdad. Inventar una tabla nueva de aperturas
    daría dos números distintos de la misma cosa en cuanto una de las dos se
    dejara de alimentar.

    **Con pocos datos no se recomienda nada.** Con tres aperturas, la hora que
    salga es la de tres correos y no un hábito, y mandar a esa hora «porque el
    sistema lo dice» es superstición con una cifra al lado.

    Sin datos se devuelve `None` y el llamante usa su hora por defecto: no saber
    es un resultado válido y decirlo es mejor que adivinar.

    **Límite conocido y dicho en el manual:** una persona está una sola vez en
    cada campaña, así que diez aperturas son diez campañas. Para la mayoría de los
    contactos esto nunca será concluyente, y por eso la capacidad de optimizar la
    hora de envío (CRM-02.02.02.05) sigue **pendiente**: hace falta telemetría de
    apertura por envío, que hoy no se guarda. Lo que hay aquí es lo que se puede
    decir con los datos que existen, no una promesa.
    """
    from services.marketing.campanas import MiembroCampana

    filas = (
        db.execute(
            select(MiembroCampana.estado_at).where(
                MiembroCampana.tenant_id == tenant_id,
                MiembroCampana.objeto_id == objeto_id,
                MiembroCampana.estado.in_(("abierto", "clicado", "respondido")),
            )
        )
        .scalars()
        .all()
    )
    if len(filas) < minimo:
        return {
            "hora": None,
            "muestras": len(filas),
            "concluyente": False,
            "aviso": (
                f"Solo {len(filas)} aperturas. Hacen falta {minimo} para hablar de "
                "un hábito; con menos, la hora que salga es la de esos correos."
            ),
        }

    por_hora: dict[int, int] = {}
    for fila in filas:
        # Se convierte a UTC explícitamente. El controlador devuelve la marca en
        # la zona de la conexión, así que sin esto la «mejor hora» salía desplazada
        # por la zona del servidor: la misma persona daría las 10 en un despliegue
        # y las 11 en otro, y el correo se mandaría a la hora equivocada sin que
        # nada fallara.
        h = _con_tz(fila).astimezone(timezone.utc).hour
        por_hora[h] = por_hora.get(h, 0) + 1
    mejor = max(por_hora, key=lambda h: por_hora[h])
    return {
        "hora": mejor,
        # Se dice la zona. Una hora sin zona se interpreta como local y se manda
        # con una o dos horas de desfase.
        "zona": "UTC",
        "muestras": len(filas),
        "concluyente": True,
        "reparto": dict(sorted(por_hora.items())),
        "aviso": (
            "La hora es UTC y sale de cuándo abrió, no de su zona horaria: para "
            "acertar de verdad hace falta saber dónde está."
        ),
    }


# ── Entregabilidad (CRM-02.03.01.03) ──────────────────────────────────────

# Cuántos correos se pueden mandar cada día de calentamiento. La progresión es
# la que recomiendan los proveedores grandes; va como tabla y no como fórmula
# porque no es una curva, son escalones acordados con quien recibe.
CALENTAMIENTO = [50, 100, 500, 1000, 5000, 10000, 20000, 50000, 100000]


def estado_dominio(db: Session, tenant_id: UUID, dominio: str) -> dict[str, Any]:
    """Si un dominio está listo para mandar, y qué le falta.

    **Un dominio sin SPF, sin DKIM o sin DMARC no rebota: llega a basura.** Y eso
    no aparece en ningún informe de rebotes — aparece como una campaña que nadie
    abrió, que es el diagnóstico equivocado.
    """
    fila = db.execute(
        select(DominioEnvio).where(
            DominioEnvio.tenant_id == tenant_id, DominioEnvio.dominio == dominio
        )
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado("Ese dominio no está configurado", error_code="dominio.no_encontrado")

    falta: list[str] = []
    if not fila.spf:
        falta.append("SPF: sin él, muchos receptores ya lo tratan como sospechoso.")
    if not fila.dkim:
        falta.append("DKIM: sin firma, cualquiera puede mandar en tu nombre.")
    if not fila.dmarc:
        falta.append(
            "DMARC: sin política publicada, SPF y DKIM no protegen de la "
            "suplantación, solo la detectan."
        )
    elif fila.dmarc == "none":
        falta.append(
            "DMARC está en «none»: detecta pero no bloquea. Sirve para medir, no " "para proteger."
        )

    tope = None
    dia = None
    if fila.calentamiento_desde:
        dia = (_ahora() - _con_tz(fila.calentamiento_desde)).days
        tope = CALENTAMIENTO[dia] if dia < len(CALENTAMIENTO) else None

    return {
        "dominio": fila.dominio,
        "uso": fila.uso,
        "listo": not falta,
        "le_falta": falta,
        "bimi": fila.bimi,
        "ip_dedicada": fila.ip_dedicada,
        "calentando": tope is not None,
        "dia_de_calentamiento": dia,
        "tope_hoy": tope,
        "aviso_calentamiento": (
            f"En calentamiento: hoy como mucho {tope} envíos. Una IP nueva que "
            "manda cien mil el primer día se quema, y quemarla cuesta semanas."
            if tope is not None
            else ""
        ),
    }


# ── Personalización (CRM-02.03.01.02) ─────────────────────────────────────

CONDICIONAL = re.compile(r"\{%\s*si\s+([a-z_][a-z0-9_.]*)\s*%\}(.*?)\{%\s*fin\s*%\}", re.S)
TOKEN = re.compile(r"\{\{\s*([a-z_][a-z0-9_.]*)(?:\s*\|\s*([^}]+))?\s*\}\}")


def personalizar(texto: str, datos: dict[str, Any]) -> dict[str, Any]:
    """Sustituye tokens y resuelve bloques condicionales.

    Los tokens admiten **valor por defecto** (`{{nombre|cliente}}`), y esa es la
    diferencia entre «Hola cliente» y «Hola », que es lo que se manda cuando el
    dato falta y nadie lo previó.

    Los condicionales son solo «si existe». No hay `si igual a` ni expresiones:
    una plantilla es contenido que escribe marketing, y darle un lenguaje con
    condiciones convierte cada campaña en código sin revisar.
    """
    usados: list[str] = []
    sin_dato: list[str] = []

    def _bloque(m: re.Match[str]) -> str:
        campo = m.group(1)
        usados.append(campo)
        return m.group(2) if _leer(datos, campo) else ""

    salida = CONDICIONAL.sub(_bloque, texto or "")

    def _token(m: re.Match[str]) -> str:
        campo, por_defecto = m.group(1), (m.group(2) or "").strip()
        usados.append(campo)
        valor = _leer(datos, campo)
        if valor in (None, ""):
            if por_defecto:
                return por_defecto
            sin_dato.append(campo)
            return ""
        return str(valor)

    salida = TOKEN.sub(_token, salida)
    return {
        "texto": salida,
        "tokens": sorted(set(usados)),
        # Los que se quedaron vacíos SIN valor por defecto. Es la lista que hay
        # que mirar antes de mandar: los que tienen defecto no son un problema.
        "sin_dato": sorted(set(sin_dato)),
        "listo": not sin_dato,
    }


def _leer(datos: dict[str, Any], camino: str) -> Any:
    actual: Any = datos
    for parte in camino.split("."):
        if not isinstance(actual, dict):
            return None
        actual = actual.get(parte)
    return actual


# ── Previsualización y revisión (CRM-02.03.01.06) ─────────────────────────

# Lo que dispara los filtros de spam. Va como lista declarada y no como modelo:
# un modelo entrenado aquí envejecería sin que nadie lo notara, y esto es una
# ayuda para quien escribe, no un veredicto.
SENALES_SPAM = {
    "gratis": "«gratis» en el asunto es la palabra más marcada de todas",
    "urgente": "«urgente» en un correo comercial dispara filtros",
    "oferta limitada": "las prisas fabricadas se marcan",
    "haz clic aquí": "los filtros penalizan el enlace sin contexto",
    "100%": "las promesas absolutas se marcan",
    "!!!": "varios signos de exclamación seguidos",
}


def revisar_antes_de_mandar(
    asunto: str, cuerpo: str, *, dominio_listo: bool = True
) -> dict[str, Any]:
    """Lo que conviene mirar antes de darle a enviar (CRM-02.03.01.06).

    Es una **ayuda, no un veredicto**: quien escribe decide. Un sistema que
    bloquea por una palabra acaba con la gente escribiendo «gr4tis», que es peor
    para el filtro y para quien lee.

    Se revisa el asunto por longitud porque un asunto de noventa caracteres se
    corta en el móvil justo donde estaba lo que importaba.
    """
    avisos: list[dict[str, str]] = []
    texto = f"{asunto} {cuerpo}".lower()
    for senal, porque in SENALES_SPAM.items():
        if senal in texto:
            avisos.append({"senal": senal, "porque": porque})

    if len(asunto) > 60:
        avisos.append(
            {
                "senal": "asunto largo",
                "porque": (
                    f"{len(asunto)} caracteres: en el móvil se corta sobre los 40, "
                    "y lo que importa suele estar al final."
                ),
            }
        )
    if not asunto.strip():
        avisos.append({"senal": "sin asunto", "porque": "Un correo sin asunto casi nunca se abre."})
    if "{{" in cuerpo or "{{" in asunto:
        avisos.append(
            {
                "senal": "token sin sustituir",
                "porque": "Queda un {{token}} sin rellenar: se mandaría tal cual.",
            }
        )
    if not dominio_listo:
        avisos.append(
            {
                "senal": "dominio sin autenticar",
                "porque": (
                    "El dominio no tiene SPF, DKIM o DMARC completos. No rebotará: "
                    "llegará a basura, y eso no sale en el informe de rebotes."
                ),
            }
        )

    return {
        "avisos": avisos,
        "cuantos": len(avisos),
        # Nunca bloquea. Un sistema que bloquea por una palabra acaba con la
        # gente escribiendo «gr4tis», que es peor para el filtro y para quien lee.
        "bloquea": False,
        "resumen": "Nada que señalar" if not avisos else f"{len(avisos)} cosas que mirar",
    }


# ── Landings (CRM-02.03.02.06) ────────────────────────────────────────────


def registrar_envio_landing(
    uow: UnidadDeTrabajo,
    landing_clave: str,
    *,
    datos: dict[str, Any],
    consentimientos: dict[str, bool] | None = None,
    ip: str = "",
) -> dict[str, Any]:
    """Recoge un envío de formulario.

    **Recoger un teléfono no autoriza a mandar SMS.** El consentimiento se pide
    aparte y por canal, y si la landing no lo declara no se da ninguno: dar por
    consentido lo que solo se ha escrito en una casilla es exactamente la práctica
    que sanciona un regulador.
    """
    tenant_id = uow.tenant_id
    landing = uow.db.execute(
        select(Landing).where(Landing.tenant_id == tenant_id, Landing.clave == landing_clave)
    ).scalar_one_or_none()
    if landing is None:
        raise NoEncontrado("Esa landing no existe", error_code="landing.no_encontrada")
    if not landing.activa:
        raise Conflicto("Esa landing está desactivada", error_code="landing.desactivada")

    obligatorios = [
        str(c.get("clave"))
        for c in (landing.campos or [])
        if c.get("obligatorio") and not datos.get(str(c.get("clave")))
    ]
    if obligatorios:
        raise ErrorValidacion(
            "Faltan campos obligatorios.",
            error_code="landing.campos_obligatorios",
            detalle={"faltan": obligatorios},
        )

    dados: list[str] = []
    ignorados: list[str] = []
    for canal, acepta in (consentimientos or {}).items():
        if canal not in (landing.pide_consentimiento or []):
            # La landing no pedía este canal: aceptarlo aquí sería dar por bueno
            # un consentimiento que nadie enseñó a la persona.
            ignorados.append(canal)
            continue
        destino = str(datos.get("email" if canal == "email" else "telefono") or "")
        if not destino:
            continue
        fijar_consentimiento(
            uow,
            canal=canal,
            destino=destino,
            acepta=bool(acepta),
            origen=f"landing:{landing.clave}",
            prueba=f"Formulario «{landing.titulo}»",
            ip=ip,
        )
        dados.append(canal)

    landing.envios += 1
    uow.db.flush()
    return {
        "landing": landing.clave,
        "consentimientos_guardados": dados,
        # Se dice lo que se ignoró: si no, quien monta la landing cree que está
        # recogiendo un permiso que no recoge.
        "consentimientos_ignorados": ignorados,
        "canal_captura": landing.canal_captura,
    }


def prerelleno(db: Session, tenant_id: UUID, landing_clave: str, destino: str) -> dict[str, Any]:
    """Qué se le puede pre-rellenar a quien ya conocemos.

    Se devuelven **solo los campos que la landing pide**, no la ficha entera:
    pre-rellenar un formulario con datos que no estaba pidiendo le enseña a quien
    lo abre —o a quien recibió el enlace reenviado— lo que sabemos de otra
    persona.
    """
    landing = db.execute(
        select(Landing).where(Landing.tenant_id == tenant_id, Landing.clave == landing_clave)
    ).scalar_one_or_none()
    if landing is None:
        raise NoEncontrado("Esa landing no existe", error_code="landing.no_encontrada")

    from services.marketing.modelos import PerfilMarketing

    perfil = db.execute(
        select(PerfilMarketing).where(
            PerfilMarketing.tenant_id == tenant_id,
            PerfilMarketing.email == destino.strip().lower(),
        )
    ).scalar_one_or_none()
    if perfil is None:
        return {"conocido": False, "valores": {}}

    pedidos = {str(c.get("clave")) for c in (landing.campos or [])}
    posibles = {
        "email": perfil.email,
        "nombre": perfil.nombre,
        "telefono": perfil.telefono,
        "pais": perfil.pais,
        "sector": perfil.sector,
        "cargo": perfil.cargo,
    }
    return {
        "conocido": True,
        "valores": {k: v for k, v in posibles.items() if k in pedidos and v},
    }
