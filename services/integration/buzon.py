"""Correo y calendario en los dos sentidos (CRM-06.01.01.01, .02, .04).

Un CRM sin las conversaciones es una agenda cara, y la conversación está en el
correo de cada comercial. Conectarlo tiene dos formas de salir mal, y las dos son
peores que no conectarlo:

  * **volcar el buzón entero dentro del CRM**, que multiplica el dato personal y
    la superficie que hay que proteger para algo que casi nadie vuelve a leer;
  * **y sincronizar en los dos sentidos sin regla de conflicto**, que hace que
    una reunión movida en el móvil vuelva sola a la hora vieja.

Las decisiones:

**Nada de un conector por casa.** Microsoft y Google son la misma cosa con otras
direcciones y otro formato de token: lo que cambia es configuración —endpoints,
campos, cómo se pagina y cómo se pide el incremento—, y eso se declara. Un módulo
por proveedor convierte cada implantación nueva en una versión del producto.

**Se sincroniza lo que tiene que ver con el CRM, no todo.** Por defecto, los
correos con alguien que está en el CRM y las reuniones con asistentes externos.
El resto ni se descarga: lo que no entra no hay que protegerlo.

**Lo privado no entra nunca.** Un correo o una cita marcados como privados se
saltan, y se cuentan aparte para que nadie crea que se sincronizó todo.

**El CRM no gana los conflictos por ser el CRM.** Gana **lo más reciente**, y
cuando los dos cambiaron después de la última sincronización se marca y se deja a
una persona. Pisar el calendario de alguien es la forma más rápida de que
desconecte la integración.

**El panel del complemento de correo lo sirve `party`, no este servicio.**
Resolver una dirección a un contacto exige leer los contactos, y este servicio no
lee el esquema de aquel. Aquí vive el buzón; quién es esa gente lo contesta quien
la tiene.

**Una sincronización que falla a medias no se da por buena.** La marca de agua
solo avanza sobre lo confirmado; si no, el hueco no se recupera nunca y nadie lo
nota hasta que falta una reunión.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from crmcore.db.base import Base, SoftDeleteMixin, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import CrmError, ErrorValidacion, NoEncontrado
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

# Qué se sincroniza. Lista cerrada porque cada una tiene su forma de leerse y su
# regla de conflicto, y «todo» no es una opción que nadie pueda sostener.
AMBITOS = ("correo", "calendario")

# Qué se trae por defecto. No es una preferencia: es la diferencia entre una
# integración que se puede explicar a un comité de empresa y una que no.
CRITERIOS = (
    "con_contacto_del_crm",  # hay alguien del CRM en la conversación
    "con_externos",  # la reunión tiene asistentes de fuera
    "marcado_por_el_usuario",  # la persona lo marca para registrar
    "todo",  # se trae todo: hay que pedirlo expresamente
)

ESTADOS = ("conectado", "sin_credencial", "error", "pausado")


class Buzon(Base, TimestampMixin, SoftDeleteMixin):
    """El correo o el calendario de una persona, conectado al CRM."""

    __tablename__ = "buzones"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    usuario_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    # La clave del perfil declarado, no el nombre de una casa: quien añade un
    # proveedor nuevo escribe configuración, no un módulo.
    perfil: Mapped[str] = mapped_column(String(60), nullable=False)
    ambito: Mapped[str] = mapped_column(
        String(20), nullable=False, default="correo", info={"opciones": AMBITOS}
    )
    direccion: Mapped[str] = mapped_column(
        String(320), nullable=False, info={"sensibilidad": "personal"}
    )
    criterio: Mapped[str] = mapped_column(
        String(40), nullable=False, default="con_contacto_del_crm", info={"opciones": CRITERIOS}
    )
    # Hacia dónde va: leer del proveedor, escribir en él, o las dos.
    entrante: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    saliente: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="sin_credencial")
    motivo: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # El testigo de incremento que da el proveedor. Se guarda tal cual: cada uno
    # usa el suyo —un delta token, un historyId, una fecha— y traducirlo sería
    # inventar un formato común que no aporta nada.
    marca_incremento: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sincronizado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "usuario_id", "ambito", "direccion", name="uq_buzon"),
        Index("ix_buzones_estado", "tenant_id", "estado"),
    )


class ElementoSincronizado(Base):
    """Un correo o una cita que ya se trató, con lo que se hizo con él."""

    __tablename__ = "elementos_buzon"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    buzon_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    # El identificador del proveedor. Es lo que hace la sincronización idempotente:
    # sin él, una reunión aparece cuatro veces en la ficha porque el calendario
    # reenvía el evento cada vez que alguien lo toca.
    externo_id: Mapped[str] = mapped_column(String(300), nullable=False)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False, default="correo")
    asunto: Mapped[str] = mapped_column(
        Text, nullable=False, default="", info={"anonimizar_en_copias": True}
    )
    ocurrido_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # registrado | saltado_privado | saltado_sin_relacion | conflicto | error
    resultado: Mapped[str] = mapped_column(String(30), nullable=False, default="registrado")
    porque: Mapped[str] = mapped_column(Text, nullable=False, default="")
    actividad_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    # Cuándo cambió en el proveedor y cuándo en el CRM. Las dos hacen falta para
    # decidir un conflicto, y guardarlas después es guardarlas tarde.
    version_externa: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    asistentes: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Quién lo mandó, si es un correo que entra. Es lo que dice que alguien ha
    # contestado y lo que saca de las cadencias (CRM-03.03.01.04).
    remitente: Mapped[str] = mapped_column(
        String(320),
        nullable=False,
        default="",
        server_default=text("''"),
        info={"sensibilidad": "personal", "anonimizar_en_copias": True},
    )
    # «» no aplica (saliente, cita o sin remitente) · pendiente · avisada ·
    # error. Una sola vez por mensaje: «avisada» no se vuelve a mandar.
    respuesta_cadencia: Mapped[str] = mapped_column(
        String(20), nullable=False, default="", server_default=text("''")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "buzon_id", "externo_id", name="uq_elemento_buzon"),
        Index("ix_elementos_buzon", "tenant_id", "buzon_id", "ocurrido_at"),
    )


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def conectar(
    uow: UnidadDeTrabajo,
    *,
    usuario_id: UUID,
    perfil: str,
    direccion: str,
    ambito: str = "correo",
    criterio: str = "con_contacto_del_crm",
    entrante: bool = True,
    saliente: bool = False,
) -> Buzon:
    """Da de alta el buzón o el calendario de una persona.

    Nace **sin credencial**: conectar es declarar la intención, y autorizar es
    otra cosa que hace la persona. Darlo por conectado antes de que autorice haría
    que el panel dijera que todo va bien mientras no entra nada.
    """
    if ambito not in AMBITOS:
        raise ErrorValidacion(
            f"Ámbito «{ambito}» no reconocido",
            error_code="buzon.ambito_invalido",
            detalle={"validos": list(AMBITOS)},
        )
    if criterio not in CRITERIOS:
        raise ErrorValidacion(
            f"Criterio «{criterio}» no reconocido",
            error_code="buzon.criterio_invalido",
            detalle={"validos": list(CRITERIOS)},
        )
    if not entrante and not saliente:
        raise ErrorValidacion(
            "Un buzón que ni lee ni escribe no sincroniza nada",
            error_code="buzon.sin_sentido",
        )

    direccion = direccion.strip().lower()
    fila = (
        uow.db.execute(
            select(Buzon).where(
                Buzon.tenant_id == uow.tenant_id,
                Buzon.usuario_id == usuario_id,
                Buzon.ambito == ambito,
                Buzon.direccion == direccion,
            )
        )
        .scalars()
        .first()
    )
    if fila is None:
        fila = Buzon(
            tenant_id=uow.tenant_id,
            usuario_id=usuario_id,
            ambito=ambito,
            direccion=direccion,
        )
        uow.db.add(fila)
    fila.perfil = perfil
    fila.criterio = criterio
    fila.entrante = entrante
    fila.saliente = saliente
    uow.db.flush()
    return fila


def marcar_autorizado(uow: UnidadDeTrabajo, *, buzon_id: UUID) -> Buzon:
    """La persona ha autorizado el acceso. Antes de esto no entra nada."""
    fila = uow.db.get(Buzon, buzon_id)
    if fila is None or fila.tenant_id != uow.tenant_id:
        raise NoEncontrado("Ese buzón no existe", error_code="buzon.no_encontrado")
    fila.estado = "conectado"
    fila.motivo = ""
    uow.db.flush()
    return fila


def pausar(uow: UnidadDeTrabajo, *, buzon_id: UUID, motivo: str) -> Buzon:
    """Deja de sincronizar sin perder lo ya registrado ni la marca de incremento.

    Hace falta porque la alternativa real es que alguien revoque el acceso desde
    el proveedor, y entonces el CRM no sabe si está pausado o roto.
    """
    fila = uow.db.get(Buzon, buzon_id)
    if fila is None or fila.tenant_id != uow.tenant_id:
        raise NoEncontrado("Ese buzón no existe", error_code="buzon.no_encontrado")
    fila.estado = "pausado"
    fila.motivo = motivo
    uow.db.flush()
    return fila


def _instante(valor: Any) -> datetime | None:
    """La fecha del elemento, venga como objeto o como texto ISO.

    Por HTTP llega siempre como texto: se guardaba la cadena tal cual en una
    columna de fecha y la respuesta reventaba al formatearla (500 en cada
    sincronización por la API, medido el 09-11-2026).
    """
    if valor is None or isinstance(valor, datetime):
        return valor
    try:
        return datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    except ValueError:
        return None


def _relevante(elemento: dict[str, Any], criterio: str, conocidas: set[str]) -> tuple[bool, str]:
    """Si este elemento tiene que ver con el CRM, y por qué.

    Devuelve también el motivo del NO: sin él, el usuario ve que «no se sincroniza
    nada» y no sabe si es que no hay nada o que el criterio lo deja fuera.
    """
    if criterio == "todo":
        return True, "El buzón está configurado para traerlo todo"
    if criterio == "marcado_por_el_usuario":
        if elemento.get("marcado"):
            return True, "Lo marcó la persona"
        return False, "No lo marcó la persona, y este buzón solo trae lo marcado"

    direcciones = {str(d).strip().lower() for d in (elemento.get("participantes") or []) if d}
    if criterio == "con_contacto_del_crm":
        coincide = direcciones & conocidas
        if coincide:
            return True, f"Participa {sorted(coincide)[0]}, que está en el CRM"
        return False, (
            "Ninguno de los participantes está en el CRM. No es basura: puede ser "
            "un contacto que falta por dar de alta."
        )

    externos = [d for d in direcciones if d not in conocidas]
    if externos:
        return True, "Tiene asistentes de fuera"
    return False, "Solo asistentes internos: no es una interacción con un cliente"


def _remitente_entrante(elemento: dict[str, Any], buzon: Buzon) -> str:
    """Quién manda este correo, si entra. Vacío si sale, si es una cita o si
    el proveedor no lo dice: no se adivina por los participantes, porque
    tomar al destinatario por remitente sacaría de la cadencia a quien no ha
    contestado."""
    if buzon.ambito != "correo":
        return ""
    if str(elemento.get("direccion") or "entrante") != "entrante":
        return ""
    de = elemento.get("remitente") or elemento.get("de") or ""
    if isinstance(de, dict):
        de = de.get("email") or de.get("correo") or ""
    de = str(de).strip().lower()
    if not de or de == buzon.direccion:
        return ""
    return de


def sincronizar(
    uow: UnidadDeTrabajo,
    *,
    buzon_id: UUID,
    elementos: list[dict[str, Any]],
    marca_nueva: str = "",
    direcciones_conocidas: list[str] | None = None,
) -> dict[str, Any]:
    """Procesa lo que ha traído el proveedor (CRM-06.01.01.01, .04).

    Los elementos llegan ya leídos: quien habla con el proveedor es el conector
    declarativo, y aquí se decide **qué se queda y qué se hace con ello**. Así lo
    que se prueba es la decisión, que es donde están los fallos que importan.

    La marca de incremento **solo avanza si no ha fallado nada**. Si avanzara con
    un fallo dentro, el hueco no se recuperaría nunca y nadie lo notaría hasta que
    faltara una reunión.
    """
    buzon = uow.db.get(Buzon, buzon_id)
    if buzon is None or buzon.tenant_id != uow.tenant_id:
        raise NoEncontrado("Ese buzón no existe", error_code="buzon.no_encontrado")
    if buzon.estado != "conectado":
        raise ErrorValidacion(
            f"El buzón está en «{buzon.estado}»: {buzon.motivo or 'sin autorizar'}",
            error_code="buzon.no_conectado",
        )

    conocidas = {str(d).strip().lower() for d in (direcciones_conocidas or [])}
    cuenta = {
        "registrados": 0,
        "privados": 0,
        "sin_relacion": 0,
        "repetidos": 0,
        "conflictos": 0,
        "errores": 0,
    }
    nuevos: list[ElementoSincronizado] = []

    for elemento in elementos:
        externo_id = str(elemento.get("id") or "")
        if not externo_id:
            cuenta["errores"] += 1
            continue

        ya = (
            uow.db.execute(
                select(ElementoSincronizado).where(
                    ElementoSincronizado.tenant_id == uow.tenant_id,
                    ElementoSincronizado.buzon_id == buzon.id,
                    ElementoSincronizado.externo_id == externo_id,
                )
            )
            .scalars()
            .first()
        )
        if ya is not None:
            version = str(elemento.get("version") or "")
            if version and version != ya.version_externa:
                # Cambió en el proveedor. Si el CRM no lo tocó, se actualiza; si
                # lo tocó, es conflicto y decide una persona: pisar el calendario
                # de alguien es la forma más rápida de que desconecte esto.
                if ya.actividad_id is not None and elemento.get("tocado_en_el_crm"):
                    ya.resultado = "conflicto"
                    ya.porque = (
                        "Cambió en el proveedor y en el CRM desde la última "
                        "sincronización: lo resuelve una persona."
                    )
                    cuenta["conflictos"] += 1
                else:
                    ya.version_externa = version
                    ya.asunto = str(elemento.get("asunto") or ya.asunto)
                    cuenta["registrados"] += 1
            else:
                cuenta["repetidos"] += 1
            continue

        if elemento.get("privado"):
            # Lo privado no entra nunca, y se cuenta: si desapareciera sin más,
            # nadie sabría que hubo algo que no se trajo.
            uow.db.add(
                ElementoSincronizado(
                    tenant_id=uow.tenant_id,
                    buzon_id=buzon.id,
                    externo_id=externo_id,
                    tipo=buzon.ambito,
                    resultado="saltado_privado",
                    porque="Marcado como privado en el proveedor",
                )
            )
            cuenta["privados"] += 1
            continue

        entra, porque = _relevante(elemento, buzon.criterio, conocidas)
        remitente = _remitente_entrante(elemento, buzon)
        fila = ElementoSincronizado(
            tenant_id=uow.tenant_id,
            buzon_id=buzon.id,
            externo_id=externo_id,
            tipo=buzon.ambito,
            asunto=str(elemento.get("asunto") or "")[:500],
            ocurrido_at=_instante(elemento.get("ocurrido_at")),
            version_externa=str(elemento.get("version") or ""),
            asistentes=list(elemento.get("participantes") or []),
            resultado="registrado" if entra else "saltado_sin_relacion",
            porque=porque,
            remitente=remitente,
            # Que conteste alguien saca de la cadencia aunque el correo no se
            # registre como actividad: el que no está en el CRM puede ser un
            # lead en plena secuencia.
            respuesta_cadencia="pendiente" if remitente else "",
        )
        uow.db.add(fila)
        nuevos.append(fila)
        if entra:
            cuenta["registrados"] += 1
        else:
            cuenta["sin_relacion"] += 1

    uow.db.flush()
    avanzada = False
    if marca_nueva and cuenta["errores"] == 0:
        buzon.marca_incremento = marca_nueva
        avanzada = True
    buzon.sincronizado_at = _ahora()
    uow.db.flush()

    return {
        "buzon_id": str(buzon.id),
        **cuenta,
        "marca_avanzada": avanzada,
        # Si no avanza, la próxima vuelta repite el tramo: es lo correcto, pero
        # hay que decirlo o alguien lo lee como que no ha pasado nada.
        "aviso": (
            ""
            if avanzada or not marca_nueva
            else "La marca de incremento NO ha avanzado porque algo falló: la "
            "próxima sincronización repetirá este tramo. Es a propósito — avanzar "
            "con un fallo dentro deja un hueco que no se recupera."
        ),
        # Lo que hay que convertir en actividad con sus asistentes
        # (CRM-06.01.01.04). Se devuelve en vez de crearse aquí: la actividad es
        # de `party` y este servicio no escribe en su esquema.
        "por_registrar_como_actividad": [
            {
                "externo_id": f.externo_id,
                "asunto": f.asunto,
                "asistentes": f.asistentes,
                "ocurrido_at": f.ocurrido_at.isoformat() if f.ocurrido_at else None,
            }
            for f in nuevos
            if f.resultado == "registrado"
        ],
    }


def panel(db: Session, tenant_id: UUID, *, horas: int = 24) -> dict[str, Any]:
    """Cómo va la sincronización, y sobre todo qué no está entrando.

    Un panel que solo cuente lo sincronizado enseña un número que sube mientras
    tres buzones llevan una semana sin credencial.
    """
    desde = _ahora() - timedelta(hours=max(1, horas))
    buzones = db.execute(select(Buzon).where(Buzon.tenant_id == tenant_id)).scalars().all()
    por_estado: dict[str, int] = {}
    for fila in buzones:
        por_estado[fila.estado] = por_estado.get(fila.estado, 0) + 1

    recientes = (
        db.execute(
            select(ElementoSincronizado.resultado, func.count(ElementoSincronizado.id))
            .where(
                ElementoSincronizado.tenant_id == tenant_id,
                ElementoSincronizado.created_at >= desde,
            )
            .group_by(ElementoSincronizado.resultado)
        )
    ).all()
    return {
        "buzones": len(buzones),
        "por_estado": por_estado,
        "ultimas_horas": {r: n for r, n in recientes},
        # Los tres números que de verdad se miran, y ninguno es «lo sincronizado».
        "sin_credencial": por_estado.get("sin_credencial", 0),
        "en_error": por_estado.get("error", 0),
        "conflictos_sin_resolver": next((n for r, n in recientes if r == "conflicto"), 0),
        "que_significa": (
            "Un buzón sin credencial no está roto: está esperando a que la persona "
            "autorice. Uno en error sí lo está, y lleva sin traer nada desde que "
            "falló."
        ),
    }


# ── Las reuniones del calendario, registradas de verdad (CRM-06.01.01.04) ──
#
# Hasta el 09-11-2026 `sincronizar` devolvía `por_registrar_como_actividad` y
# no lo usaba nadie: la reunión quedaba en esta tabla y en la ficha del cliente
# no aparecía nunca. Ahora se crea la actividad en `party` con sus asistentes
# vinculados a los contactos que son, preguntando por HTTP con la identidad de
# quien sincroniza.


def _correo_de(asistente: Any) -> str:
    if isinstance(asistente, dict):
        return str(asistente.get("email") or asistente.get("correo") or "").strip().lower()
    return str(asistente or "").strip().lower()


def _invocar(**kw: Any) -> dict[str, Any]:
    from crmcore.http.interno import invocar

    return invocar(**kw)


def contactos_por_correo(
    invocar: Any, *, identidad: dict[str, Any], correos: list[str]
) -> dict[str, dict[str, Any]]:
    """Qué contacto del CRM es cada dirección. Las que no casan no salen."""
    if not correos:
        return {}
    r = invocar(
        metodo="GET",
        ruta="/api/v1/contacts",
        parametros={"email__en": ",".join(sorted(set(correos))), "limite": 200},
        **identidad,
    )
    if not r.get("ok"):
        raise ErrorValidacion(
            f"party no ha dicho quiénes son los asistentes (HTTP {r.get('estado')})",
            error_code="buzon.asistentes_sin_respuesta",
        )
    salida: dict[str, dict[str, Any]] = {}
    for c in (r.get("datos") or {}).get("items") or []:
        correo = str(c.get("email") or "").strip().lower()
        if correo:
            salida[correo] = {"id": str(c.get("id")), "nombre": c.get("nombre_completo")}
    return salida


def registrar_reuniones(
    uow: UnidadDeTrabajo,
    *,
    buzon_id: UUID,
    identidad: dict[str, Any],
    invocar: Any = None,
) -> dict[str, Any]:
    """Convierte en actividad `reunion` cada cita registrada que aún no la tiene.

    Cada asistente va con su contacto si lo es; los que no están en el CRM se
    quedan con su dirección (son los contactos que faltan por dar de alta). Una
    cita que `party` no acepta queda en «error» con el motivo y se reintenta en
    la siguiente vuelta: la actividad no se da por creada si no lo está.
    """
    invocar = invocar or _invocar
    buzon = uow.db.get(Buzon, buzon_id)
    if buzon is None or buzon.tenant_id != uow.tenant_id:
        raise NoEncontrado("Ese buzón no existe", error_code="buzon.no_encontrado")
    # Un correo registrado es una actividad `email`, igual que una cita es una
    # `reunion`: `por_registrar_como_actividad` lo devolvía para los dos y solo
    # se recogían las citas (medido el 09-11-2026).
    es_cita = buzon.ambito == "calendario"
    pendientes = (
        uow.db.execute(
            select(ElementoSincronizado).where(
                ElementoSincronizado.tenant_id == uow.tenant_id,
                ElementoSincronizado.buzon_id == buzon.id,
                ElementoSincronizado.resultado.in_(("registrado", "error")),
                ElementoSincronizado.actividad_id.is_(None),
            )
        )
        .scalars()
        .all()
    )
    creadas, errores = 0, 0
    detalle: list[dict[str, Any]] = []
    for e in pendientes:
        correos = [c for c in (_correo_de(a) for a in e.asistentes or []) if c]
        if e.remitente and e.remitente not in correos:
            correos.insert(0, e.remitente)
        try:
            conocidos = contactos_por_correo(invocar, identidad=identidad, correos=correos)
            asistentes = [
                {
                    "email": c,
                    "contacto_id": (conocidos.get(c) or {}).get("id"),
                    "nombre": (conocidos.get(c) or {}).get("nombre"),
                }
                for c in correos
            ]
            principal_id = next((a["contacto_id"] for a in asistentes if a["contacto_id"]), None)
            r = invocar(
                metodo="POST",
                ruta="/api/v1/activities",
                cuerpo={
                    "tipo": "reunion" if es_cita else "email",
                    "asunto": (e.asunto or ("Reunión" if es_cita else "Correo"))[:300],
                    "objeto": "contacto" if principal_id else None,
                    "objeto_id": principal_id,
                    "contacto_id": principal_id,
                    "asignada_a": str(buzon.usuario_id),
                    "inicio_at": e.ocurrido_at.isoformat() if e.ocurrido_at else None,
                    "detalles": {
                        "asistentes": asistentes,
                        "origen": "calendario" if es_cita else "correo",
                        "remitente": e.remitente or None,
                        "externo_id": e.externo_id,
                        "buzon_id": str(buzon.id),
                    },
                },
                **identidad,
            )
            if not r.get("ok"):
                datos = r.get("datos") or {}
                raise ErrorValidacion(
                    f"party no ha aceptado la {'reunión' if es_cita else 'actividad del correo'} "
                    f"(HTTP {r.get('estado')}): "
                    f"{datos.get('mensaje') or datos.get('detail') or datos}"[:400],
                    error_code="buzon.reunion_rechazada",
                )
            e.actividad_id = UUID(str((r.get("datos") or {}).get("id")))
            e.resultado = "registrado"
            creadas += 1
            detalle.append(
                {
                    "externo_id": e.externo_id,
                    "actividad_id": str(e.actividad_id),
                    "asistentes_en_el_crm": sum(1 for a in asistentes if a["contacto_id"]),
                    "asistentes": len(asistentes),
                }
            )
        except CrmError as exc:
            # También si party no contesta: la cita queda en «error» y se
            # reintenta en la siguiente vuelta, nunca se da por registrada.
            e.resultado = "error"
            e.porque = exc.mensaje[:1000]
            errores += 1
    uow.db.flush()
    return {"creadas": creadas, "errores": errores, "reuniones": detalle}


# ── La respuesta que detecta el buzón saca de las cadencias (CRM-03.03.01.04) ──
#
# Hasta el 09-11-2026 la sincronización del buzón no avisaba a nadie: alguien
# contestaba al correo de la cadencia y recibía el siguiente igual. La regla de
# sales —«responder saca del recorrido, siempre»— tiene una sola puerta
# (`POST /cadencias/respuesta`) y el buzón no llamaba.


def avisar_respuestas(
    uow: UnidadDeTrabajo,
    *,
    buzon_id: UUID,
    identidad: dict[str, Any],
    invocar: Any = None,
) -> dict[str, Any]:
    """Cada correo entrante con remitente avisa a las cadencias, una vez.

    Se avisa por todos, no solo por los que casan con un contacto: quien está
    en una cadencia puede ser un lead que aún no es contacto. Sales contesta
    cuántas inscripciones sacó; si ninguna y el correo no tenía que ver con el
    CRM, el remitente se borra —no hay por qué guardar la dirección de quien no
    es nadie aquí—. Lo que falla se queda en «error» y se reintenta en la
    siguiente sincronización.
    """
    from services.integration import senales_identidad as sen

    invocar = invocar or _invocar
    pendientes = (
        uow.db.execute(
            select(ElementoSincronizado).where(
                ElementoSincronizado.tenant_id == uow.tenant_id,
                ElementoSincronizado.buzon_id == buzon_id,
                ElementoSincronizado.respuesta_cadencia.in_(("pendiente", "error")),
            )
        )
        .scalars()
        .all()
    )
    avisadas, sacadas, errores = 0, 0, 0
    for e in pendientes:
        try:
            r = invocar(
                metodo="POST",
                ruta="/api/v1/cadencias/respuesta",
                cuerpo={"email": e.remitente, "tipo": "respondio"},
                **identidad,
            )
        except CrmError as exc:
            r = {"ok": False, "estado": 0, "datos": {"mensaje": exc.mensaje}}
        if not r.get("ok"):
            e.respuesta_cadencia = "error"
            datos = r.get("datos") or {}
            e.porque = (
                f"Las cadencias no han recibido la respuesta (HTTP {r.get('estado')}): "
                f"{datos.get('mensaje') or datos.get('detail') or ''}"
            )[:1000]
            errores += 1
            continue
        e.respuesta_cadencia = "avisada"
        avisadas += 1
        n = int((r.get("datos") or {}).get("sacadas") or 0)
        sacadas += n
        if e.resultado == "registrado" or n:
            # Quien escribe es una señal de identidad para party
            # (CRM-01.01.05.02). Nunca tumba la sincronización.
            sen.anotar_y_enviar(
                uow.db,
                uow.tenant_id,
                identidad=identidad,
                invocar=invocar,
                tipo="email",
                valor=e.remitente,
                origen="buzon",
                referencia=f"{buzon_id}:{e.externo_id}",
            )
        else:
            e.remitente = ""
    uow.db.flush()
    return {"avisadas": avisadas, "sacadas_de_cadencias": sacadas, "errores": errores}
