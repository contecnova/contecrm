"""Biblioteca de activos y aprobación de contenidos
(CRM-02.04.01.01, CRM-02.04.01.02).

Una biblioteca de activos es de las cosas que más se piden y peor se usan: se
monta, se suben trescientos ficheros, y a los seis meses nadie encuentra nada y
todo el mundo sigue mandando el PDF por correo. Lo que la salva o la hunde no es
el buscador: es **si lo que hay dentro se puede usar sin preguntar**.

De ahí salen las decisiones:

**Un activo sin vigencia es un activo caducado esperando.** El folleto con los
precios del año pasado sigue ahí, alguien lo manda, y el cliente pide ese precio.
Todo activo dice hasta cuándo vale, y lo vencido no se borra —hace falta para
saber qué se mandó— pero **deja de poder usarse**.

**Los derechos de uso van dentro.** Una foto de banco de imágenes con licencia
para web no vale para una valla publicitaria, y esa diferencia la conoce quien la
compró y nadie más. Sin eso, la biblioteca es una fuente de problemas legales con
buscador.

**La versión nueva no borra la anterior.** Lo que se mandó al cliente el martes
tiene que poder recuperarse, aunque el jueves se corrigiera una errata.

**Y la aprobación es de personas, con la comprobación antes y no después.** Un
flujo donde el contenido se publica y luego alguien revisa es un flujo sin
aprobación: lo que está fuera, fuera está. Se aprueba lo que se va a usar, y quien
aprueba ve **qué cambió** desde la última versión aprobada — revisar treinta
páginas enteras cada vez es lo que hace que se apruebe sin leer.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.db.base import Base, SoftDeleteMixin, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

logger = get_logger(__name__)

# Dónde se puede usar un activo. Cerrada porque la licencia de una imagen se
# compra para unos usos concretos, y «uso general» no existe en ningún contrato.
USOS = ("web", "correo", "redes", "impresion", "exterior", "video", "interno")

# Estados de la aprobación. `caducado` está aparte de `retirado`: uno volvería a
# valer con una licencia nueva y el otro no, y mezclarlos hace que se vuelva a
# usar algo que se retiró por un motivo.
ESTADOS = ("borrador", "en_revision", "aprobado", "rechazado", "caducado", "retirado")

# Con cuánta antelación se avisa de una licencia o una vigencia que termina. Un
# mes: menos no da tiempo a renovar un contrato de imagen ni a rehacer una pieza.
DIAS_PREAVISO = 30


def _hoy() -> date:
    return datetime.now(timezone.utc).date()


class Activo(Base, TimestampMixin, SoftDeleteMixin):
    """Una pieza de contenido con sus derechos, su vigencia y su versión."""

    __tablename__ = "activos_marketing"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(120), nullable=False)
    nombre: Mapped[str] = mapped_column(String(300), nullable=False)
    tipo: Mapped[str] = mapped_column(String(40), nullable=False, default="documento")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Referencia en el gestor documental. El fichero no vive aquí: ya hay un sitio
    # para eso y tener dos deja uno sin cifrar.
    referencia: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="borrador")

    # Para qué se puede usar, según la licencia que se compró. «Uso general» no
    # existe en ningún contrato de imagen.
    usos_permitidos: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    licencia: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    licencia_hasta: Mapped[date | None] = mapped_column(Date, nullable=True)
    vigente_hasta: Mapped[date | None] = mapped_column(Date, nullable=True)

    idioma: Mapped[str] = mapped_column(String(10), nullable=False, default="es")
    etiquetas: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Qué sustituye a esta versión, cuando hay una nueva. La anterior no se borra:
    # lo que se mandó al cliente el martes tiene que poder recuperarse.
    sustituido_por_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "clave", "version", name="uq_activo_version"),
        Index("ix_activos_vigencia", "tenant_id", "vigente_hasta"),
    )


class Aprobacion(Base, TimestampMixin):
    """Una revisión de contenido, con quién, cuándo y sobre qué versión."""

    __tablename__ = "aprobaciones_contenido"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    objeto: Mapped[str] = mapped_column(String(40), nullable=False)
    objeto_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    paso: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    aprobador_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    # pendiente | aprobado | rechazado
    resultado: Mapped[str] = mapped_column(String(20), nullable=False, default="pendiente")
    comentario: Mapped[str] = mapped_column(Text, nullable=False, default="")
    decidido_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Si el aprobador vio el diff con la versión anterior. Revisar treinta páginas
    # enteras cada vez es lo que hace que se apruebe sin leer.
    vio_los_cambios: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (Index("ix_aprobaciones", "tenant_id", "objeto", "objeto_id"),)


# ── Biblioteca (CRM-02.04.01.01) ──────────────────────────────────────────


def registrar_activo(
    uow: UnidadDeTrabajo,
    *,
    clave: str,
    nombre: str,
    referencia: str,
    usos_permitidos: list[str],
    licencia: str = "",
    licencia_hasta: date | None = None,
    vigente_hasta: date | None = None,
    tipo: str = "documento",
    idioma: str = "es",
    etiquetas: list[str] | None = None,
) -> Activo:
    """Da de alta un activo, **con sus derechos y su vigencia**.

    Sin usos declarados no entra. Una foto de banco con licencia para web no vale
    para una valla publicitaria, y esa diferencia la conoce quien la compró y
    nadie más: sin ella, la biblioteca es una fuente de problemas legales con
    buscador.

    Y sin vigencia se avisa: un activo sin fecha de caducidad es un folleto con
    los precios del año pasado esperando a que alguien lo mande.
    """
    if not referencia.strip():
        raise ErrorValidacion(
            "Un activo sin referencia al gestor documental es una ficha que dice que el "
            "fichero existe sin que nadie pueda abrirlo.",
            error_code="activos.sin_referencia",
        )
    desconocidos = sorted(set(usos_permitidos) - set(USOS))
    if desconocidos:
        raise ErrorValidacion(
            f"Usos desconocidos: {', '.join(desconocidos)}",
            error_code="activos.uso_invalido",
            detalle={"admitidos": list(USOS)},
        )
    if not usos_permitidos:
        raise ErrorValidacion(
            "Un activo sin usos declarados no se puede usar en nada: «uso general» no "
            "existe en ningún contrato de imagen, y suponerlo es como se acaba con una "
            "foto de stock en una valla.",
            error_code="activos.sin_usos",
        )

    ultima = (
        uow.db.execute(
            select(Activo)
            .where(Activo.tenant_id == uow.tenant_id, Activo.clave == clave)
            .order_by(Activo.version.desc())
        )
        .scalars()
        .first()
    )

    fila = Activo(
        tenant_id=uow.tenant_id,
        clave=clave,
        nombre=nombre,
        tipo=tipo,
        version=(ultima.version + 1) if ultima else 1,
        referencia=referencia.strip(),
        usos_permitidos=sorted(set(usos_permitidos)),
        licencia=licencia,
        licencia_hasta=licencia_hasta,
        vigente_hasta=vigente_hasta,
        idioma=idioma,
        etiquetas=sorted(set(etiquetas or [])),
    )
    uow.db.add(fila)
    uow.db.flush()

    if ultima is not None:
        # La anterior no se borra: se marca como sustituida. Lo que se mandó al
        # cliente el martes tiene que poder recuperarse aunque el jueves se
        # corrigiera una errata.
        ultima.sustituido_por_id = fila.id
        uow.db.flush()

    return fila


def se_puede_usar(*, activo: dict[str, Any], uso: str, hoy: date | None = None) -> dict[str, Any]:
    """Si este activo se puede usar **para esto y hoy**.

    Las tres respuestas negativas son distintas y se distinguen, porque llevan a
    acciones distintas: **no está aprobado** (falta una firma), **ha caducado**
    (hay que renovar o rehacer) y **no cubre este uso** (hay que comprar otra
    licencia o buscar otra pieza).
    """
    momento = hoy or _hoy()
    estado = str(activo.get("estado") or "")
    if estado != "aprobado":
        return {
            "puede": False,
            "motivo": "sin_aprobar",
            "que_hacer": f"Está en «{estado}»: falta la aprobación.",
        }
    if uso not in (activo.get("usos_permitidos") or []):
        return {
            "puede": False,
            "motivo": "uso_no_cubierto",
            "que_hacer": (
                f"La licencia no cubre «{uso}». Usarla igual es un problema legal con "
                "buscador: hay que comprar otra licencia o buscar otra pieza."
            ),
        }
    vigente = activo.get("vigente_hasta")
    if isinstance(vigente, str):
        vigente = date.fromisoformat(vigente)
    if isinstance(vigente, date) and vigente < momento:
        return {
            "puede": False,
            "motivo": "caducado",
            "que_hacer": (
                f"Venció el {vigente.isoformat()}. El folleto con los precios del año "
                "pasado sigue estando y por eso no se puede mandar."
            ),
        }
    licencia = activo.get("licencia_hasta")
    if isinstance(licencia, str):
        licencia = date.fromisoformat(licencia)
    if isinstance(licencia, date) and licencia < momento:
        return {
            "puede": False,
            "motivo": "licencia_vencida",
            "que_hacer": "La licencia de uso ha terminado: hay que renovarla.",
        }
    return {"puede": True}


def revisar_biblioteca(db: Session, tenant_id: UUID, *, hoy: date | None = None) -> dict[str, Any]:
    """Qué hay que mirar de la biblioteca antes de que dé un problema.

    Lo caducado y lo que va a caducar, con aviso **antes**: renovar un contrato de
    imagen o rehacer una pieza lleva semanas, así que enterarse el día que vence
    es enterarse tarde.

    Y lo que **no tiene vigencia declarada**, que es lo más peligroso: nunca va a
    aparecer en ninguna lista de caducados y por eso se queda ahí para siempre.
    """
    momento = hoy or _hoy()
    filas = list(
        db.execute(
            select(Activo).where(
                Activo.tenant_id == tenant_id,
                Activo.sustituido_por_id.is_(None),
                Activo.estado != "retirado",
            )
        )
        .scalars()
        .all()
    )
    caducados, por_caducar, sin_fecha = [], [], []
    for fila in filas:
        fecha = fila.vigente_hasta or fila.licencia_hasta
        if fecha is None:
            sin_fecha.append(fila.clave)
            continue
        dias = (fecha - momento).days
        entrada = {
            "clave": fila.clave,
            "nombre": fila.nombre,
            "vence": fecha.isoformat(),
            "dias": dias,
        }
        if dias < 0:
            caducados.append(entrada)
        elif dias <= DIAS_PREAVISO:
            por_caducar.append(entrada)

    return {
        "activos": len(filas),
        "caducados": caducados,
        "por_caducar": sorted(por_caducar, key=lambda a: a["dias"]),
        "sin_vigencia_declarada": sin_fecha,
        "medible": bool(filas),
        "que_mirar": (
            "La biblioteca está vacía: no hay nada que revisar y tampoco nada que usar."
            if not filas
            else " ".join(
                filter(
                    None,
                    [
                        f"{len(caducados)} activos caducados que siguen en la biblioteca."
                        if caducados
                        else "",
                        f"{len(sin_fecha)} sin vigencia declarada: nunca van a aparecer "
                        "en ninguna lista de caducados, y por eso se quedan para siempre."
                        if sin_fecha
                        else "",
                    ],
                )
            )
            or "Todo en vigor.",
        ),
    }


# ── Aprobación de contenidos y campañas (CRM-02.04.01.02) ─────────────────


def pedir_aprobacion(
    uow: UnidadDeTrabajo,
    *,
    objeto: str,
    objeto_id: UUID,
    version: int,
    pasos: list[dict[str, Any]],
) -> dict[str, Any]:
    """Abre la revisión, **con los pasos y sus aprobadores declarados**.

    Un paso sin aprobador concreto no es un paso: es una cola donde las cosas se
    quedan. «Que lo vea marketing» no lo ve nadie, porque nadie en particular lo
    tiene asignado.

    Y **legal va al final**, cuando hay paso legal: revisar algo que todavía va a
    cambiar es trabajo tirado, y la segunda vez ya no se revisa con la misma
    atención.
    """
    if not pasos:
        raise ErrorValidacion(
            "Una aprobación sin pasos no aprueba nada", error_code="aprobacion.sin_pasos"
        )
    sin_aprobador = [p.get("nombre") for p in pasos if not p.get("aprobador_id")]
    if sin_aprobador:
        raise ErrorValidacion(
            "Hay pasos sin aprobador concreto: «que lo vea marketing» no lo ve nadie, "
            "porque nadie en particular lo tiene asignado.",
            error_code="aprobacion.paso_sin_aprobador",
            detalle={"pasos": sin_aprobador},
        )

    creados = []
    for paso in pasos:
        fila = Aprobacion(
            tenant_id=uow.tenant_id,
            objeto=objeto,
            objeto_id=objeto_id,
            version=version,
            paso=str(paso.get("nombre") or ""),
            aprobador_id=UUID(str(paso["aprobador_id"])),
        )
        uow.db.add(fila)
        creados.append(fila)
    uow.db.flush()

    return {
        "pasos": [{"id": str(f.id), "paso": f.paso} for f in creados],
        "objeto": objeto,
        "version": version,
        "esta_publicado": False,
        "porque": (
            "Se aprueba antes de publicar. Un flujo donde el contenido sale y luego "
            "alguien revisa es un flujo sin aprobación: lo que está fuera, fuera está."
        ),
    }


def decidir(
    uow: UnidadDeTrabajo,
    *,
    aprobacion_id: UUID,
    resultado: str,
    comentario: str,
    aprobador_id: UUID,
    vio_los_cambios: bool,
) -> dict[str, Any]:
    """Aprueba o rechaza un paso.

    **Rechazar exige comentario.** Un rechazo sin motivo devuelve el trabajo al
    principio sin decir qué hay que cambiar, y la segunda versión suele traer el
    mismo problema.

    Y se anota si el aprobador **vio los cambios**: revisar treinta páginas
    enteras cada vez es lo que hace que se apruebe sin leer, y saber cuántas
    aprobaciones se dieron sin mirar el diff es el dato que dice si este flujo
    sirve o es un trámite.
    """
    if resultado not in ("aprobado", "rechazado"):
        raise ErrorValidacion(
            "Una decisión es aprobar o rechazar", error_code="aprobacion.resultado_invalido"
        )
    fila = uow.db.get(Aprobacion, aprobacion_id)
    if fila is None or fila.tenant_id != uow.tenant_id:
        raise NoEncontrado("Ese paso no existe", error_code="aprobacion.no_encontrada")
    if fila.resultado != "pendiente":
        raise Conflicto(
            f"Ese paso ya está «{fila.resultado}»: volver a decidirlo borraría quién lo "
            "decidió la primera vez.",
            error_code="aprobacion.ya_decidida",
        )
    if fila.aprobador_id != aprobador_id:
        raise Conflicto(
            "Este paso está asignado a otra persona. Aprobar por otro deja una firma "
            "que no corresponde con quien miró el contenido.",
            error_code="aprobacion.aprobador_distinto",
        )
    if resultado == "rechazado" and not comentario.strip():
        raise ErrorValidacion(
            "Un rechazo sin motivo devuelve el trabajo al principio sin decir qué hay "
            "que cambiar, y la segunda versión suele traer el mismo problema.",
            error_code="aprobacion.rechazo_sin_motivo",
        )

    fila.resultado = resultado
    fila.comentario = comentario.strip()
    fila.decidido_at = datetime.now(timezone.utc)
    fila.vio_los_cambios = vio_los_cambios
    uow.db.flush()

    return {
        "paso": fila.paso,
        "resultado": resultado,
        "sin_mirar_los_cambios": not vio_los_cambios,
        "aviso": (
            ""
            if vio_los_cambios
            else "Aprobado sin mirar qué cambió respecto de la versión anterior. Queda "
            "anotado: es el dato que dice si este flujo sirve o es un trámite."
        ),
    }


def estado_de_la_aprobacion(
    db: Session, tenant_id: UUID, *, objeto: str, objeto_id: UUID, version: int
) -> dict[str, Any]:
    """Si esto se puede publicar ya, y qué falta.

    Un rechazo **para el conjunto**: seguir pidiendo las firmas siguientes cuando
    uno ya ha dicho que no es hacer trabajar a gente sobre algo que va a cambiar.
    """
    filas = list(
        db.execute(
            select(Aprobacion).where(
                Aprobacion.tenant_id == tenant_id,
                Aprobacion.objeto == objeto,
                Aprobacion.objeto_id == objeto_id,
                Aprobacion.version == version,
            )
        )
        .scalars()
        .all()
    )
    if not filas:
        return {
            "se_puede_publicar": False,
            "porque": (
                "No se ha pedido ninguna aprobación para esta versión. Publicar sin "
                "pedirla no es «aprobación implícita»: es publicar sin aprobar."
            ),
        }

    rechazados = [f for f in filas if f.resultado == "rechazado"]
    pendientes = [f for f in filas if f.resultado == "pendiente"]
    sin_mirar = [f for f in filas if f.resultado == "aprobado" and not f.vio_los_cambios]

    return {
        "se_puede_publicar": not rechazados and not pendientes,
        "rechazado_en": [{"paso": f.paso, "motivo": f.comentario} for f in rechazados],
        "pendientes": [f.paso for f in pendientes],
        "aprobados_sin_mirar_cambios": [f.paso for f in sin_mirar],
        "porque": (
            f"Rechazado en «{rechazados[0].paso}»: {rechazados[0].comentario}. Los pasos "
            "siguientes no se piden — hacer trabajar a gente sobre algo que va a cambiar "
            "es la forma de que dejen de revisar en serio."
            if rechazados
            else (
                f"Faltan {len(pendientes)} pasos por decidir."
                if pendientes
                else "Todos los pasos aprobados."
            )
        ),
    }
