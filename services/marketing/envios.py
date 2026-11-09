"""Envíos programados por destinatario: su hora, su canal y su clase
(CRM-02.02.02.05, CRM-02.03.01.07).

Hasta el 09-11-2026 lo de «mejor hora y canal» eran funciones puras que
recibían un historial tecleado (`/momento/*`), y la única que leía datos de
verdad —`mejor-hora`— no la llamaba nadie. Ni el envío de una campaña ni un paso
de recorrido decidían nada: la campaña no tenía envío y el recorrido emitía un
evento que no consumía nadie.

Aquí se programa **cada destinatario a su hora y por su canal**, con su
historial real:

* las respuestas que ha dado a envíos anteriores (clic, respuesta) —que ahora se
  guardan por envío, cosa que antes no existía y por eso `mejor_hora` admitía
  que «nunca sería concluyente»—, y su paso por campañas;
* **lo que dijo la persona manda** sobre lo que dice el historial: su canal y su
  horario preferidos, si constan en su perfil;
* **sin historial suficiente se usa el valor por defecto**, que es un ajuste, y
  se dice cuántos van así: si casi todos van a la hora general, la
  personalización no está haciendo nada y conviene saberlo;
* la hora es **la suya**: se calcula en su zona, o en la del tenant.

Y cada envío **sale por su clase** (CRM-02.03.01.07): lo promocional por su
dominio, su remitente y su servidor; lo transaccional por los suyos. Si el
remitente de la clase no es de su dominio, no sale: compartir reputación es
justo lo que la separación existe para evitar.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from crmcore.db.base import Base, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import DateTime, Index, Integer, String, Text, func, select, text, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from services.marketing import momento as mom

logger = get_logger(__name__)

ORIGENES = ("campana", "recorrido")
ESTADOS = ("programado", "enviado", "fallido", "omitido")
SUCESOS = ("abierto", "clic", "respondido")


class EnvioProgramado(Base, TimestampMixin):
    """Un mensaje a una persona, con la hora y el canal elegidos y por qué."""

    __tablename__ = "envios_programados"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    origen: Mapped[str] = mapped_column(String(20), nullable=False, info={"opciones": ORIGENES})
    origen_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    nodo: Mapped[str | None] = mapped_column(String(80), nullable=True)
    objeto: Mapped[str] = mapped_column(String(20), nullable=False, default="contacto")
    objeto_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    direccion: Mapped[str | None] = mapped_column(
        String(320), nullable=True, info={"sensibilidad": "personal"}
    )
    canal: Mapped[str] = mapped_column(String(20), nullable=False, default="email")
    plantilla: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    idioma: Mapped[str] = mapped_column(String(10), nullable=False, default="es")
    clase: Mapped[str] = mapped_column(String(20), nullable=False, default="promocional")
    programado_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    hora_local: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    zona: Mapped[str] = mapped_column(String(60), nullable=False, default="UTC")
    # Cómo se eligieron la hora y el canal: del historial, de lo que dijo la
    # persona o por defecto, con las muestras y la frase que lo explica.
    eleccion: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    estado: Mapped[str] = mapped_column(
        String(20), nullable=False, default="programado", info={"opciones": ESTADOS}
    )
    motivo: Mapped[str | None] = mapped_column(Text, nullable=True)
    dominio: Mapped[str | None] = mapped_column(String(253), nullable=True)
    remitente: Mapped[str | None] = mapped_column(String(320), nullable=True)
    flujo: Mapped[str | None] = mapped_column(String(300), nullable=True)
    enviado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    abierto_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    clic_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    respondido_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Quién lo programó y con qué permisos y roles, en foto al programarlo. El
    # despacho automático actúa con esta identidad —con ella pide a `sales` las
    # recomendaciones—: lo que sale solo actúa como quien lo lanzó. Sin ella no
    # sale: se queda programado con el motivo dicho, en vez de inventar una.
    programado_por_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True, info={"calculado": True}
    )
    programado_con: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
        info={"calculado": True},
    )

    __table_args__ = (
        Index("ix_envios_pendientes", "tenant_id", "estado", "programado_at"),
        Index("ix_envios_origen", "tenant_id", "origen", "origen_id"),
    )


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


SIN_IDENTIDAD = "No consta quién lo programó: sin eso no sale solo. Vuelve a programarlo."


# ── Con qué identidad actúa lo que sale solo ─────────────────────────────


def foto(principal: Any) -> dict[str, Any] | None:
    """La identidad de quien lanza algo, con sus permisos y roles de ese momento.

    Es lo que se guarda al programar un envío o publicar un recorrido, y con lo
    que actúa después lo que corre solo (como `activada_por_id` en
    `automation`). `None` si no hay nadie: mejor decirlo que inventarlo.
    """
    if principal is None or getattr(principal, "id", None) is None:
        return None
    return {
        "principal_id": str(principal.id),
        "tipo": str(getattr(principal, "tipo", "") or "usuario"),
        "permisos": sorted(getattr(principal, "permisos", ()) or ()),
        "roles": sorted(getattr(principal, "roles", ()) or ()),
    }


def guardar_foto(identidad: dict[str, Any] | None) -> tuple[UUID | None, dict[str, Any]]:
    """La foto partida en sus dos columnas: el id y el resto."""
    if not identidad or not identidad.get("principal_id"):
        return None, {}
    return UUID(str(identidad["principal_id"])), {
        "tipo": str(identidad.get("tipo") or "usuario"),
        "permisos": list(identidad.get("permisos") or []),
        "roles": list(identidad.get("roles") or []),
    }


def leer_foto(por_id: UUID | None, con: dict[str, Any] | None) -> dict[str, Any] | None:
    """Las dos columnas vueltas a juntar; `None` si no consta quién."""
    if por_id is None:
        return None
    con = con or {}
    return {
        "principal_id": str(por_id),
        "tipo": str(con.get("tipo") or "usuario"),
        "permisos": list(con.get("permisos") or []),
        "roles": list(con.get("roles") or []),
    }


def invocar_como(identidad: dict[str, Any]) -> Any:
    """Un `invocar` que llama con ESTA identidad y sólo con los permisos que tenía.

    Quien llama pide los permisos que la ruta necesita; se le dan sólo los que
    la foto cubre (con comodines, igual que la comprobación de verdad). Si la
    persona no podía leer oportunidades, el despacho automático tampoco: la
    recomendación sale vacía y lo dice, y el correo sale igual.
    """
    from crmcore.authz.principal import Principal

    quien = Principal(
        id=UUID(str(identidad["principal_id"])),
        tipo=str(identidad.get("tipo") or "usuario"),
        permisos=frozenset(identidad.get("permisos") or ()),
        roles=frozenset(identidad.get("roles") or ()),
    )

    def _llamar(**kw: Any) -> dict[str, Any]:
        from crmcore.http.interno import invocar

        kw["principal_id"] = quien.id
        kw["permisos"] = [p for p in (kw.get("permisos") or []) if quien.tiene(p)]
        kw["roles"] = sorted(quien.roles)
        return invocar(**kw)

    return _llamar


def _con_tz(v: datetime | None) -> datetime | None:
    if v is None:
        return None
    return v if v.tzinfo else v.replace(tzinfo=timezone.utc)


def _ajuste(clave: str, db: Session | None) -> Any:
    from services.marketing.ajustes import valor

    return valor(clave, db)


def canales_disponibles(db: Session) -> list[str]:
    crudo = str(_ajuste("momento_canales", db) or "email")
    return [c.strip() for c in crudo.split(",") if c.strip() in mom.CANALES] or ["email"]


# ── El historial real ────────────────────────────────────────────────────


def historial(db: Session, tenant_id: UUID, objeto_id: UUID) -> list[dict[str, Any]]:
    """Las respuestas que ha dado esta persona, de los dos sitios donde constan.

    De sus envíos (clic y respuesta, por canal) y de su paso por campañas. La
    apertura no cuenta, como decide `momento`: abrir no significa nada.
    """
    from services.marketing.campanas import Campana, MiembroCampana

    salida: list[dict[str, Any]] = []
    for envio in db.execute(
        select(EnvioProgramado).where(
            EnvioProgramado.tenant_id == tenant_id, EnvioProgramado.objeto_id == objeto_id
        )
    ).scalars():
        if envio.clic_at:
            salida.append(
                {"canal": envio.canal, "resultado": "clic", "cuando": _con_tz(envio.clic_at)}
            )
        if envio.respondido_at:
            salida.append(
                {
                    "canal": envio.canal,
                    "resultado": "respondido",
                    "cuando": _con_tz(envio.respondido_at),
                }
            )
    traduce = {"clicado": "clic", "respondido": "respondido", "convertido": "conversion"}
    for estado, cuando, canal in db.execute(
        select(MiembroCampana.estado, MiembroCampana.estado_at, Campana.canal)
        .join(Campana, Campana.id == MiembroCampana.campana_id)
        .where(
            MiembroCampana.tenant_id == tenant_id,
            MiembroCampana.objeto_id == objeto_id,
            MiembroCampana.estado.in_(tuple(traduce)),
        )
    ).all():
        salida.append({"canal": canal, "resultado": traduce[estado], "cuando": _con_tz(cuando)})
    return salida


def _zona(perfil: Any, db: Session) -> ZoneInfo:
    from crmcore.fechas import zona_del_tenant

    nombre = str(((perfil.campos or {}) if perfil else {}).get("zona_horaria") or "")
    if nombre:
        try:
            return ZoneInfo(nombre)
        except Exception:  # noqa: BLE001 — una zona mal escrita cae a la del tenant
            pass
    return zona_del_tenant(db)


def _siguiente(hora: int, zona: ZoneInfo, ahora: datetime) -> datetime:
    local = ahora.astimezone(zona)
    candidato = local.replace(hour=hora, minute=0, second=0, microsecond=0)
    if candidato <= local:
        candidato += timedelta(days=1)
    return candidato.astimezone(timezone.utc)


def _direccion(perfil: Any, canal: str) -> str:
    if perfil is None:
        return ""
    if canal == "email":
        return str(perfil.email or "").strip()
    if canal in ("sms", "whatsapp", "llamada"):
        return str(perfil.telefono or "").strip()
    return ""


def elegir(
    db: Session,
    tenant_id: UUID,
    objeto_id: UUID,
    *,
    perfil: Any,
    canales: list[str] | None = None,
    ahora: datetime | None = None,
    inmediato: bool = False,
) -> dict[str, Any]:
    """La hora y el canal de esta persona, con el porqué."""
    momento = ahora or _ahora()
    zona = _zona(perfil, db)
    permitidos = canales or canales_disponibles(db)
    campos = (perfil.campos or {}) if perfil is not None else {}
    eventos = historial(db, tenant_id, objeto_id)
    # El historial, pasado a SU hora local: la franja se mide en su reloj.
    locales = [{**e, "cuando": e["cuando"].astimezone(zona)} for e in eventos if e.get("cuando")]

    # Canal. Lo que dijo la persona manda sobre lo que dice el historial.
    dicho = str(campos.get("canal_preferido") or "")
    vetados = [c for c in mom.CANALES if c not in permitidos]
    if dicho in permitidos and _direccion(perfil, dicho):
        canal, por_canal = dicho, "lo_dijo"
        porque_canal = f"Pidió que se le escriba por {dicho}."
    else:
        estimado = mom.canal_preferido(interacciones=locales, prohibidos=vetados)
        if (
            estimado.get("canal")
            and estimado.get("medible")
            and _direccion(perfil, estimado["canal"])
        ):
            canal, por_canal = str(estimado["canal"]), "historial"
            porque_canal = str(estimado["porque"])
        else:
            canal = str(_ajuste("momento_canal_por_defecto", db) or "email")
            por_canal = "por_defecto"
            porque_canal = "Sin historial suficiente: el canal por defecto."
            if not _direccion(perfil, canal):
                otro = next((c for c in permitidos if _direccion(perfil, c)), canal)
                if otro != canal:
                    porque_canal = f"Sin historial y sin {canal}: va por {otro}."
                canal = otro

    # Hora.
    if inmediato:
        return {
            "canal": canal,
            "programado_at": momento,
            "hora_local": momento.astimezone(zona).hour,
            "zona": str(zona.key),
            "eleccion": {
                "canal": por_canal,
                "hora": "inmediato",
                "muestras": len(eventos),
                "porque": f"{porque_canal} Sale en cuanto se despache.",
            },
        }
    horario = str(campos.get("horario_preferido") or "")
    if horario[:2].isdigit():
        hora, por_hora = int(horario[:2]) % 24, "lo_dijo"
        porque_hora = f"Pidió que se le escriba hacia las {hora}:00."
    else:
        franja = mom.franja_preferida(interacciones=locales, huso_del_destinatario=str(zona.key))
        if franja.get("personalizable"):
            hora, por_hora = int(str(franja["hora_local"])[:2]), "historial"
            porque_hora = str(franja["porque"])
        else:
            hora = int(_ajuste("momento_hora_por_defecto", db) or 10)
            por_hora = "por_defecto"
            porque_hora = str(franja["porque"]) + f" Va a la hora general ({hora}:00)."
    return {
        "canal": canal,
        "programado_at": _siguiente(hora, zona, momento),
        "hora_local": hora,
        "zona": str(zona.key),
        "eleccion": {
            "canal": por_canal,
            "hora": por_hora,
            "muestras": len(eventos),
            "porque": f"{porque_canal} {porque_hora}",
        },
    }


# ── Programar ─────────────────────────────────────────────────────────────


def programar(
    uow: UnidadDeTrabajo,
    *,
    origen: str,
    origen_id: UUID,
    destinatarios: list[UUID],
    plantilla: str,
    idioma: str = "es",
    clase: str = "",
    nodo: str | None = None,
    objeto: str = "contacto",
    inmediato: bool = False,
    ahora: datetime | None = None,
    por: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Programa un mensaje por persona, cada uno a su hora y por su canal.

    Quien no se puede alcanzar —sin dirección, suprimido— queda **omitido con su
    motivo**, no se cae de la lista: contarlo como enviado inflaría el embudo, y
    hacerlo desaparecer esconde por qué el envío salió más pequeño.

    `por` es la foto de quien lo programa (`foto`): con ella sale solo, a su
    hora. Sin ella se programa igual, pero el despacho automático no lo manda.
    """
    from services.marketing.correo import componer
    from services.marketing.modelos import PerfilMarketing
    from services.marketing.segmentos import filtrar_suprimidos
    from services.marketing.vista_correo import clase_de

    if origen not in ORIGENES:
        raise ErrorValidacion(f"Origen «{origen}» no válido.", error_code="envio.origen_no_valido")
    db = uow.db
    tenant_id = uow.tenant_id
    if not clase:
        clase = clase_de(componer(db, tenant_id, plantilla, idioma=idioma).get("clase") or "")
    perfiles = {
        p.objeto_id: p
        for p in db.execute(
            select(PerfilMarketing).where(
                PerfilMarketing.tenant_id == tenant_id,
                PerfilMarketing.objeto_id.in_(destinatarios or [nuevo_id()]),
            )
        ).scalars()
    }
    alcanzables, _ = filtrar_suprimidos(db, tenant_id, objeto, destinatarios)
    alcanzables_set = set(alcanzables)
    canales = canales_disponibles(db)
    por_id, por_con = guardar_foto(por)
    filas: list[EnvioProgramado] = []
    for objeto_id in destinatarios:
        perfil = perfiles.get(objeto_id)
        e = elegir(
            db,
            tenant_id,
            objeto_id,
            perfil=perfil,
            canales=canales,
            ahora=ahora,
            inmediato=inmediato,
        )
        fila = EnvioProgramado(
            tenant_id=tenant_id,
            origen=origen,
            origen_id=origen_id,
            nodo=nodo,
            objeto=objeto,
            objeto_id=objeto_id,
            canal=e["canal"],
            direccion=_direccion(perfil, e["canal"]) or None,
            plantilla=plantilla,
            idioma=idioma,
            clase=clase,
            programado_at=e["programado_at"],
            hora_local=e["hora_local"],
            zona=e["zona"],
            eleccion=e["eleccion"],
            programado_por_id=por_id,
            programado_con=por_con,
        )
        # Lo transaccional no se suprime por una baja de marketing: la factura
        # tiene que llegar. Lo promocional, sí.
        if clase == "promocional" and e["canal"] == "email" and objeto_id not in alcanzables_set:
            fila.estado = "omitido"
            fila.motivo = "sin_direccion" if not fila.direccion else "suprimido"
        elif not fila.direccion:
            fila.estado = "omitido"
            fila.motivo = "sin_direccion"
        db.add(fila)
        filas.append(fila)
    db.flush()
    return _resumen(filas)


def _resumen(filas: list[EnvioProgramado]) -> dict[str, Any]:
    # Todo lo que no se omitió: lo ya enviado o fallido también se programó, y
    # contarlo como omitido —como pasaba tras despachar— decía lo contrario.
    programados = [f for f in filas if f.estado != "omitido"]
    general = sum(1 for f in programados if (f.eleccion or {}).get("hora") == "por_defecto")
    return {
        "envios": len(filas),
        "programados": len(programados),
        "omitidos": len(filas) - len(programados),
        "a_la_hora_general": general,
        "personalizados": len(programados) - general,
        "que_significa": (
            f"{general} de {len(programados)} van a la hora general."
            + (
                " La personalización casi no está haciendo nada: falta historial."
                if programados and general / len(programados) > 0.8
                else ""
            )
        ),
    }


def programar_campana(
    uow: UnidadDeTrabajo,
    campana_id: UUID,
    *,
    plantilla: str,
    idioma: str = "es",
    inmediato: bool = False,
    por: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from services.marketing.campanas import Campana, MiembroCampana

    campana = uow.db.get(Campana, campana_id)
    if campana is None or campana.tenant_id != uow.tenant_id:
        raise NoEncontrado("La campaña no existe", error_code="campana.no_encontrada")
    ya = set(
        uow.db.execute(
            select(EnvioProgramado.objeto_id).where(
                EnvioProgramado.tenant_id == uow.tenant_id,
                EnvioProgramado.origen == "campana",
                EnvioProgramado.origen_id == campana_id,
                EnvioProgramado.plantilla == plantilla,
            )
        ).scalars()
    )
    miembros = [
        oid
        for oid in uow.db.execute(
            select(MiembroCampana.objeto_id).where(
                MiembroCampana.tenant_id == uow.tenant_id,
                MiembroCampana.campana_id == campana_id,
                MiembroCampana.estado.notin_(("excluido", "baja")),
            )
        ).scalars()
        if oid not in ya
    ]
    resumen = programar(
        uow,
        origen="campana",
        origen_id=campana_id,
        destinatarios=miembros,
        plantilla=plantilla,
        idioma=idioma,
        inmediato=inmediato,
        por=por,
    )
    resumen["ya_programados_antes"] = len(ya)
    return resumen


# ── Despachar ─────────────────────────────────────────────────────────────


def _mandar_correo(
    db: Session,
    tenant_id: UUID,
    envio: EnvioProgramado,
    asunto: str,
    cuerpo_html: str,
) -> tuple[bool, str, dict[str, Any]]:
    """Por el transporte SMTP de la casa, con el dominio, remitente y flujo de la clase."""
    from email.message import EmailMessage

    from crmcore.config import get_settings
    from crmcore.notificaciones.smtp import TransporteSMTP

    from services.marketing.vista_correo import salida, texto_plano

    sale = salida(db, tenant_id, envio.clase)
    if not sale["puede_salir"]:
        return False, " ".join(sale["problemas"]), sale
    config = sale["_config"]
    nombre = str(config.get("remitente_nombre") or "")
    correo = EmailMessage()
    correo["Subject"] = asunto
    correo["From"] = f"{nombre} <{sale['remitente']}>" if nombre else str(sale["remitente"])
    correo["To"] = str(envio.direccion)
    correo["X-Clase-Correo"] = envio.clase
    if envio.clase == "promocional":
        url = str(_ajuste("correo_url_baja", db) or "")
        if url:
            correo["List-Unsubscribe"] = f"<{url.replace('{email}', str(envio.direccion))}>"
            correo["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    else:
        # Lo transaccional no lleva baja de marketing, y se dice que es
        # automático para que no conteste un «fuera de la oficina».
        correo["Auto-Submitted"] = "auto-generated"
    correo.set_content(texto_plano(cuerpo_html) or asunto)
    correo.add_alternative(cuerpo_html, subtype="html")
    try:
        TransporteSMTP()._enviar(correo, str(sale["flujo"]["host"]), config, get_settings())
    except Exception as exc:  # noqa: BLE001 — el fallo se guarda en el envío
        return False, f"{type(exc).__name__}: {exc}"[:500], sale
    return True, "", sale


def despachar(
    uow: UnidadDeTrabajo,
    *,
    principal_id: Any = None,
    ahora: datetime | None = None,
    limite: int = 200,
    origen: str = "",
    origen_id: UUID | None = None,
    forzar: bool = False,
    automatico: bool = False,
) -> dict[str, Any]:
    """Manda lo que ya toca. Con `forzar`, lo programado de ese origen aunque no toque.

    **A mano** (el botón, la ruta) actúa quien lo pide: `principal_id`.
    **Solo** (`automatico`, la tarea periódica) cada envío actúa con la foto de
    quien lo programó, con sus permisos de entonces y no con más. El que no la
    tiene no sale: se queda programado con el motivo dicho (`SIN_IDENTIDAD`).

    Las filas se cogen con `FOR UPDATE SKIP LOCKED`: dos procesos despachando a
    la vez se reparten la cola en vez de mandar dos veces lo mismo. Y lo que
    reviente con un envío se queda en ese envío —fallido, con su motivo—: no
    deshace los que ya salieron, que volverían a salir en la vuelta siguiente.
    """
    db = uow.db
    tenant_id = uow.tenant_id
    momento = ahora or _ahora()
    filtros = [EnvioProgramado.tenant_id == tenant_id, EnvioProgramado.estado == "programado"]
    if origen:
        filtros.append(EnvioProgramado.origen == origen)
    if origen_id:
        filtros.append(EnvioProgramado.origen_id == origen_id)
    if not forzar:
        filtros.append(EnvioProgramado.programado_at <= momento)

    sin_identidad = 0
    if automatico:
        # Se dicen una vez, con su motivo, y no se vuelven a coger: si entraran
        # en el lote, cien envíos sin identidad taparían para siempre a los que sí
        # pueden salir detrás de ellos.
        sin_identidad = int(
            db.execute(
                update(EnvioProgramado)
                .where(
                    *filtros,
                    EnvioProgramado.programado_por_id.is_(None),
                    EnvioProgramado.motivo.is_distinct_from(SIN_IDENTIDAD),
                )
                .values(motivo=SIN_IDENTIDAD)
                .execution_options(synchronize_session=False)
            ).rowcount
            or 0
        )
        filtros.append(EnvioProgramado.programado_por_id.isnot(None))

    pendientes = list(
        db.execute(
            select(EnvioProgramado)
            .where(*filtros)
            .order_by(EnvioProgramado.programado_at)
            .limit(limite)
            .with_for_update(skip_locked=True)
        ).scalars()
    )

    recomendaciones: dict[Any, dict[str, Any]] = {}
    enviados = fallidos = 0
    for envio in pendientes:
        identidad = leer_foto(envio.programado_por_id, envio.programado_con) if automatico else None
        try:
            with db.begin_nested():
                ok = _despachar_uno(
                    db,
                    tenant_id,
                    envio,
                    principal_id=identidad["principal_id"] if identidad else principal_id,
                    llamar=invocar_como(identidad) if identidad else None,
                    recomendaciones=recomendaciones,
                )
        except Exception as exc:  # noqa: BLE001 — el fallo se queda en su envío
            logger.warning("envios.despacho_fallido", envio=str(envio.id), error=str(exc)[:200])
            envio.estado = "fallido"
            envio.motivo = f"{type(exc).__name__}: {exc}"[:500]
            ok = False
        if ok:
            enviados += 1
        else:
            fallidos += 1
    db.flush()
    return {
        "revisados": len(pendientes),
        "enviados": enviados,
        "fallidos": fallidos,
        "sin_identidad": sin_identidad,
    }


def _despachar_uno(
    db: Session,
    tenant_id: UUID,
    envio: EnvioProgramado,
    *,
    principal_id: Any,
    llamar: Any,
    recomendaciones: dict[Any, dict[str, Any]],
) -> bool:
    """Monta y manda un envío. Devuelve si salió; si no, deja el motivo en él."""
    from crmcore.notificaciones.base import Destino, Mensaje
    from crmcore.notificaciones.http import TransporteHTTP
    from crmcore.runtime import settings as rt

    from services.marketing.campanas import anotar_envio
    from services.marketing.correo import componer
    from services.marketing.modelos import PerfilMarketing
    from services.marketing.vista_correo import montar, recomendar

    perfil = db.execute(
        select(PerfilMarketing).where(
            PerfilMarketing.tenant_id == tenant_id, PerfilMarketing.objeto_id == envio.objeto_id
        )
    ).scalar_one_or_none()
    datos: dict[str, Any] = {}
    if perfil is not None:
        datos = {
            "nombre": perfil.nombre,
            "email": perfil.email,
            "cargo": perfil.cargo,
            "contacto": {"nombre": perfil.nombre, "email": perfil.email, "cargo": perfil.cargo},
            **(perfil.campos or {}),
        }
        # La recomendación depende de quién la pide: con otros permisos, otra
        # respuesta. Por eso se guarda por identidad y cuenta.
        clave = (str(principal_id), perfil.cuenta_id)
        if clave not in recomendaciones:
            try:
                recomendaciones[clave] = recomendar(
                    db,
                    tenant_id,
                    cuenta_id=perfil.cuenta_id,
                    principal_id=principal_id,
                    invocar=llamar,
                )
            except Exception as exc:  # noqa: BLE001 — sin recomendación el correo sale igual
                recomendaciones[clave] = {"productos": [], "porque": str(exc)[:200]}
        datos["recomendaciones"] = recomendaciones[clave]
        for i, p in enumerate(datos["recomendaciones"].get("productos") or [], start=1):
            datos[f"recomendacion_{i}"] = p
    try:
        montado = montar(componer(db, tenant_id, envio.plantilla, idioma=envio.idioma), datos)
    except NoEncontrado as exc:
        envio.estado, envio.motivo = "fallido", str(exc.mensaje)
        return False
    if montado["sin_dato"]:
        # Un «Te esperamos en {{evento.nombre}}» sin dato sale diciendo en
        # voz alta que es automático. No sale, y se dice qué faltaba.
        envio.estado = "fallido"
        envio.motivo = "Campos sin dato: " + ", ".join(montado["sin_dato"]) + "."
        return False
    if envio.canal == "email":
        ok, error, sale = _mandar_correo(db, tenant_id, envio, montado["asunto"], montado["html"])
        envio.dominio = sale.get("dominio")
        envio.remitente = sale.get("remitente")
        envio.flujo = f"{sale['flujo']['origen']}:{sale['flujo']['host'] or '-'}"
    else:
        config = dict(rt.efectivo(f"canal_{envio.canal}", db, default={}) or {})
        r = TransporteHTTP(envio.canal).entregar(
            Destino(usuario_id=envio.objeto_id, direccion=str(envio.direccion or "")),
            Mensaje(titulo=montado["asunto"], cuerpo=montado["asunto"]),
            config,
        )
        ok, error = bool(r.entregado), str(getattr(r, "detalle", "") or "")
        envio.flujo = f"http:{config.get('url') or '-'}"
    if not ok:
        envio.estado, envio.motivo = "fallido", error
        return False
    envio.estado, envio.enviado_at, envio.motivo = "enviado", _ahora(), None
    anotar_envio(
        db,
        tenant_id,
        objeto_id=envio.objeto_id,
        canal=envio.canal,
        transaccional=envio.clase == "transaccional",
    )
    return True


# ── Lo que sale solo ──────────────────────────────────────────────────────


def tenants_con_envios_vencidos() -> list[UUID]:
    """Los tenants con algún envío al que ya le ha llegado la hora.

    De la propia tabla: la lista de tenants es de otro servicio. Un tenant sin
    nada vencido no cuesta ni una consulta más.
    """
    from crmcore.db.session import sesion

    with sesion(sistema=True) as s:
        filas = s.execute(
            select(EnvioProgramado.tenant_id)
            .where(
                EnvioProgramado.estado == "programado",
                EnvioProgramado.programado_at <= _ahora(),
            )
            .distinct()
        ).all()
    return sorted({t for (t,) in filas}, key=str)


def despachar_vencidos(tenant_id: UUID) -> dict[str, Any]:
    """La vuelta de la tarea periódica por un tenant: manda lo que ya toca.

    **Un envío por transacción.** Con un lote entero en una sola, el error del
    envío ciento cincuenta deshacía el «enviado» de los ciento cuarenta y nueve
    que ya habían salido, y la vuelta siguiente los volvía a mandar. Como mucho
    `envios_despacho_max_por_vuelta`: el resto, en la siguiente.
    """
    from crmcore.db.uow import unidad_de_trabajo
    from crmcore.tenancy.context import con_contexto

    total = {"revisados": 0, "enviados": 0, "fallidos": 0, "sin_identidad": 0}
    with con_contexto(tenant_id=tenant_id, origen="tareas"):
        with unidad_de_trabajo(tenant_id) as uow:
            maximo = int(_ajuste("envios_despacho_max_por_vuelta", uow.db) or 1)
        for _ in range(maximo):
            with unidad_de_trabajo(tenant_id) as uow:
                r = despachar(uow, automatico=True, limite=1)
            for k in total:
                total[k] += int(r.get(k) or 0)
            if not r["revisados"]:
                break
    if total["revisados"] or total["sin_identidad"]:
        logger.info("envios.despachados_solos", tenant=str(tenant_id), **total)
    return total


# ── Lo que hizo con él ───────────────────────────────────────────────────


def anotar_suceso(uow: UnidadDeTrabajo, envio_id: UUID, *, que: str) -> dict[str, Any]:
    """Abrió, hizo clic o respondió. Alimenta el historial y los recorridos."""
    from services.marketing.recorridos import anotar_comportamiento

    if que not in SUCESOS:
        raise ErrorValidacion(
            f"Suceso «{que}» no válido.",
            error_code="envio.suceso_no_valido",
            detalle={"validos": list(SUCESOS)},
        )
    envio = uow.db.get(EnvioProgramado, envio_id)
    if envio is None or envio.tenant_id != uow.tenant_id:
        raise NoEncontrado("Ese envío no existe", error_code="envio.no_existe")
    setattr(envio, f"{que}_at", _ahora())
    uow.db.flush()
    comportamiento = {"abierto": "abrio", "clic": "clico", "respondido": "respondio"}[que]
    anotado = anotar_comportamiento(uow, objeto_id=envio.objeto_id, que=comportamiento)
    return {"envio_id": str(envio.id), "que": que, "recorridos": anotado["anotado_en"]}


def listado(
    db: Session, tenant_id: UUID, *, origen: str, origen_id: UUID, limite: int = 200
) -> dict[str, Any]:
    filas = list(
        db.execute(
            select(EnvioProgramado)
            .where(
                EnvioProgramado.tenant_id == tenant_id,
                EnvioProgramado.origen == origen,
                EnvioProgramado.origen_id == origen_id,
            )
            .order_by(EnvioProgramado.programado_at)
            .limit(limite)
        ).scalars()
    )
    cuenta = dict(
        db.execute(
            select(EnvioProgramado.estado, func.count())
            .where(
                EnvioProgramado.tenant_id == tenant_id,
                EnvioProgramado.origen == origen,
                EnvioProgramado.origen_id == origen_id,
            )
            .group_by(EnvioProgramado.estado)
        ).all()
    )
    return {
        "por_estado": {str(k): int(v) for k, v in cuenta.items()},
        **_resumen(filas),
        "envios": [
            {
                "id": str(f.id),
                "objeto_id": str(f.objeto_id),
                "nodo": f.nodo,
                "canal": f.canal,
                "clase": f.clase,
                "plantilla": f.plantilla,
                "programado_at": f.programado_at,
                "hora_local": f.hora_local,
                "zona": f.zona,
                "como_hora": (f.eleccion or {}).get("hora"),
                "como_canal": (f.eleccion or {}).get("canal"),
                "porque": (f.eleccion or {}).get("porque"),
                "estado": f.estado,
                "motivo": f.motivo,
                "dominio": f.dominio,
                "remitente": f.remitente,
                "flujo": f.flujo,
                # Con quién sale solo; vacío = no sale solo (ver `motivo`).
                "programado_por_id": str(f.programado_por_id) if f.programado_por_id else None,
                "enviado_at": f.enviado_at,
                "clic_at": f.clic_at,
            }
            for f in filas
        ],
    }
