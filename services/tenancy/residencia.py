"""Dónde viven los datos de cada tenant, y quién los toca
(CRM-00.01.05.01, .02, .03, CRM-00.01.03.09).

«Sus datos se quedan en Europa» es la frase que cierra contratos y la que más
veces se incumple sin que nadie lo sepa. No por mala fe: los datos
transaccionales sí se quedan, y luego los registros van a un servicio de
observabilidad en otro continente, las copias a un almacenamiento replicado y el
modelo de IA a una API que ni siquiera se preguntó dónde está.

Las decisiones:

**La residencia se declara por TIPO de dato, no por tenant.** Es la diferencia
entre la frase que se firma y lo que pasa: casi siempre lo transaccional está
bien y lo que se escapa son los registros, las copias y la analítica.

**Lo no declarado no se da por bueno.** Un tipo de dato sin región declarada sale
como hueco, no como «europeo por defecto». El defecto silencioso es exactamente
cómo se incumple sin enterarse.

**Los subprocesadores se declaran con lo que hace falta para el contrato**: qué
trata, dónde y con qué garantía si sale del EEE. Una lista de nombres no sirve
para contestar a un cliente que pregunta por el artículo 28.

**Una transferencia internacional sin garantía se marca**, no se bloquea. Bloquear
el envío desde aquí sería fingir un control que no existe —el dato ya ha salido
por otra vía mil veces—; lo que sí se puede es que conste y que alguien lo vea.

**Y cambiar de región tiene ventana de solo lectura y verificación**, como el
cambio de aislamiento y por el mismo motivo: «migrado» no puede significar «el
script terminó sin error».
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.audit.chain import registrar
from crmcore.db.base import Base, SoftDeleteMixin, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from crmcore.regiones import REGIONES as REGIONES_DE_DATOS
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

# Las regiones que el despliegue sabe distinguir. Viene de `crmcore` porque la
# política de IA promete lo mismo sobre la misma lista, y cuando eran dos había
# clientes —los de `latam` y `apac`— que podían firmar su residencia y no podían
# declarar su política. Ver `crmcore/regiones.py`.
REGIONES = REGIONES_DE_DATOS

# Los tipos de dato que se ubican por separado. Esta lista ES la capacidad: lo
# transaccional casi siempre está bien, y lo que se escapa son los otros cuatro.
TIPOS_DATO = (
    "transaccional",  # el CRM en sí
    "analitico",  # el almacén y los cuadros de mando
    "copias",  # las copias de seguridad y las exportaciones
    "registros",  # logs, trazas y métricas
    "ia",  # lo que se manda a un modelo
    "adjuntos",  # el corpus documental
)

# Qué ampara una salida del EEE. Lista cerrada: es el campo que mira un DPO, y
# «contrato firmado» no es ninguna de estas cosas.
GARANTIAS = (
    "decision_adecuacion",
    "clausulas_tipo",
    "normas_corporativas",
    "consentimiento_explicito",
    "sin_garantia",
)


class ResidenciaDato(Base, TimestampMixin, SoftDeleteMixin):
    """Dónde vive cada tipo de dato de un tenant."""

    __tablename__ = "residencia_datos"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    tipo_dato: Mapped[str] = mapped_column(String(20), nullable=False)
    region: Mapped[str] = mapped_column(String(20), nullable=False)
    # Quién lo guarda de verdad. Sin esto, «UE» no dice si es un centro propio o
    # el de un tercero, que es justo lo que pregunta un cliente grande.
    proveedor: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    notas: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (
        UniqueConstraint("tenant_id", "tipo_dato", name="uq_residencia_tipo"),
        Index("ix_residencia_region", "tenant_id", "region"),
    )


class Subprocesador(Base, TimestampMixin, SoftDeleteMixin):
    """Un tercero que trata datos del tenant (CRM-00.01.05.03)."""

    __tablename__ = "subprocesadores"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(80), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    # Qué trata y para qué. Una lista de nombres no sirve para contestar a un
    # cliente que pregunta por el artículo 28.
    trata: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    finalidad: Mapped[str] = mapped_column(Text, nullable=False, default="")
    region: Mapped[str] = mapped_column(String(20), nullable=False, default="ue")
    # Si el dato sale del EEE, qué lo ampara.
    garantia: Mapped[str] = mapped_column(String(40), nullable=False, default="sin_garantia")
    referencia_garantia: Mapped[str] = mapped_column(Text, nullable=False, default="")
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Cuándo se le comunicó al cliente. Un subprocesador nuevo del que el cliente
    # no se ha enterado es un incumplimiento del contrato, no un detalle.
    comunicado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "clave", name="uq_subprocesador"),
        Index("ix_subprocesadores", "tenant_id", "activo"),
    )


class TransferenciaInternacional(Base, SoftDeleteMixin):
    """Una salida de datos fuera de la región del tenant, anotada."""

    __tablename__ = "transferencias_internacionales"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    subprocesador: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    tipo_dato: Mapped[str] = mapped_column(String(20), nullable=False, default="transaccional")
    desde_region: Mapped[str] = mapped_column(String(20), nullable=False, default="ue")
    hacia_region: Mapped[str] = mapped_column(String(20), nullable=False, default="ee_uu")
    garantia: Mapped[str] = mapped_column(String(40), nullable=False, default="sin_garantia")
    motivo: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_transferencias", "tenant_id", "created_at"),
        Index("ix_transferencias_garantia", "tenant_id", "garantia"),
    )


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def fijar_residencia(
    uow: UnidadDeTrabajo,
    *,
    tenant_id: UUID,
    tipo_dato: str,
    region: str,
    proveedor: str = "",
    notas: str = "",
) -> ResidenciaDato:
    """Declara dónde vive un tipo de dato de este tenant."""
    if tipo_dato not in TIPOS_DATO:
        raise ErrorValidacion(
            f"Tipo de dato desconocido: «{tipo_dato}»",
            error_code="residencia.tipo_invalido",
            detalle={"admitidos": list(TIPOS_DATO)},
        )
    if region not in REGIONES:
        raise ErrorValidacion(
            f"Región desconocida: «{region}»",
            error_code="residencia.region_invalida",
            detalle={"admitidas": list(REGIONES)},
        )
    fila = (
        uow.db.execute(
            select(ResidenciaDato).where(
                ResidenciaDato.tenant_id == tenant_id,
                ResidenciaDato.tipo_dato == tipo_dato,
            )
        )
        .scalars()
        .first()
    )
    if fila is None:
        fila = ResidenciaDato(tenant_id=tenant_id, tipo_dato=tipo_dato)
        uow.db.add(fila)
    fila.region = region
    fila.proveedor = proveedor or fila.proveedor
    fila.notas = notas or fila.notas
    uow.db.flush()
    return fila


def mapa(db: Session, tenant_id: UUID, *, region_contratada: str = "") -> dict[str, Any]:
    """Dónde está cada tipo de dato, y qué **no está declarado**
    (CRM-00.01.05.01, .02).

    Lo no declarado sale como hueco y no como «europeo por defecto». El defecto
    silencioso es exactamente cómo se incumple una promesa de residencia sin
    enterarse: lo transaccional se queda donde se dijo y los registros se van a
    otro continente porque nadie preguntó.
    """
    filas = (
        db.execute(select(ResidenciaDato).where(ResidenciaDato.tenant_id == tenant_id))
        .scalars()
        .all()
    )
    por_tipo = {f.tipo_dato: f for f in filas}
    sin_declarar = [t for t in TIPOS_DATO if t not in por_tipo]
    fuera = []
    if region_contratada:
        fuera = [
            {"tipo_dato": f.tipo_dato, "region": f.region, "proveedor": f.proveedor}
            for f in filas
            if f.region != region_contratada
        ]

    return {
        "tenant_id": str(tenant_id),
        "region_contratada": region_contratada or None,
        "por_tipo": [
            {
                "tipo_dato": f.tipo_dato,
                "region": f.region,
                "proveedor": f.proveedor,
            }
            for f in sorted(filas, key=lambda f: f.tipo_dato)
        ],
        # Los dos huecos que de verdad importan.
        "sin_declarar": sin_declarar,
        "fuera_de_la_region_contratada": fuera,
        "completo": not sin_declarar,
        "cumple_lo_contratado": bool(region_contratada) and not fuera and not sin_declarar,
        "que_significa": (
            "Todos los tipos de dato están declarados y en la región contratada."
            if region_contratada and not fuera and not sin_declarar
            else "Hay tipos de dato sin declarar: no se puede afirmar que se cumpla "
            "la residencia contratada. Un tipo sin declarar no es un tipo que esté "
            "en la región: es uno que nadie ha mirado."
            if sin_declarar
            else "Hay datos fuera de la región contratada. Puede ser legítimo —con "
            "su garantía— pero tiene que constar y el cliente tiene que saberlo."
        ),
    }


def declarar_subprocesador(
    uow: UnidadDeTrabajo,
    *,
    tenant_id: UUID,
    clave: str,
    nombre: str,
    trata: list[str],
    finalidad: str,
    region: str = "ue",
    garantia: str = "sin_garantia",
    referencia_garantia: str = "",
) -> Subprocesador:
    """Da de alta un tercero que trata datos del tenant.

    Exige **qué trata y para qué**: una lista de nombres no sirve para contestar
    a un cliente que pregunta por el artículo 28, que es exactamente para lo que
    se pide esta lista.
    """
    if region not in REGIONES:
        raise ErrorValidacion(
            f"Región desconocida: «{region}»", error_code="residencia.region_invalida"
        )
    if garantia not in GARANTIAS:
        raise ErrorValidacion(
            f"Garantía desconocida: «{garantia}». «Contrato firmado» no es ninguna "
            "de las que reconoce el RGPD.",
            error_code="residencia.garantia_invalida",
            detalle={"admitidas": list(GARANTIAS)},
        )
    if not trata:
        raise ErrorValidacion(
            "Hay que decir qué datos trata: un subprocesador sin eso es un nombre "
            "en una lista, y no contesta a lo que pregunta un cliente.",
            error_code="residencia.subprocesador_sin_datos",
        )
    if not finalidad.strip():
        raise ErrorValidacion(
            "Hay que decir para qué los trata", error_code="residencia.subprocesador_sin_finalidad"
        )
    desconocidos = sorted(set(trata) - set(TIPOS_DATO))
    if desconocidos:
        raise ErrorValidacion(
            f"Tipos de dato no reconocidos: {desconocidos}",
            error_code="residencia.tipo_invalido",
            detalle={"admitidos": list(TIPOS_DATO)},
        )

    fila = (
        uow.db.execute(
            select(Subprocesador).where(
                Subprocesador.tenant_id == tenant_id, Subprocesador.clave == clave
            )
        )
        .scalars()
        .first()
    )
    if fila is None:
        fila = Subprocesador(tenant_id=tenant_id, clave=clave)
        uow.db.add(fila)
    fila.nombre = nombre
    fila.trata = sorted(set(trata))
    fila.finalidad = finalidad
    fila.region = region
    fila.garantia = garantia
    fila.referencia_garantia = referencia_garantia
    fila.activo = True
    uow.db.flush()
    registrar(
        uow.db,
        accion="residencia.subprocesador_declarado",
        objeto="subprocesador",
        objeto_id=fila.id,
        datos={"clave": clave, "region": region, "garantia": garantia},
        tenant_id=tenant_id,
    )
    return fila


def anotar_transferencia(
    uow: UnidadDeTrabajo,
    *,
    tenant_id: UUID,
    tipo_dato: str,
    hacia_region: str,
    desde_region: str = "ue",
    subprocesador: str = "",
    motivo: str = "",
) -> dict[str, Any]:
    """Deja constancia de que un dato ha salido de su región.

    **No bloquea.** Bloquear el envío desde aquí sería fingir un control que no
    existe: el dato sale por el conector, por el correo o por el modelo de IA, y
    esta tabla no está en medio de ninguno de los tres. Lo que sí se puede es que
    conste, que se vea cuál no tiene garantía y que alguien lo arregle.
    """
    garantia = "sin_garantia"
    if subprocesador:
        ficha = (
            uow.db.execute(
                select(Subprocesador).where(
                    Subprocesador.tenant_id == tenant_id, Subprocesador.clave == subprocesador
                )
            )
            .scalars()
            .first()
        )
        if ficha is not None:
            garantia = ficha.garantia

    fila = TransferenciaInternacional(
        tenant_id=tenant_id,
        subprocesador=subprocesador,
        tipo_dato=tipo_dato,
        desde_region=desde_region,
        hacia_region=hacia_region,
        garantia=garantia,
        motivo=motivo,
    )
    uow.db.add(fila)
    uow.db.flush()
    if garantia == "sin_garantia":
        logger.warning(
            "residencia.transferencia_sin_garantia",
            tenant=str(tenant_id),
            hacia=hacia_region,
            subprocesador=subprocesador,
        )
    return {
        "id": str(fila.id),
        "hacia": hacia_region,
        "garantia": garantia,
        "amparada": garantia != "sin_garantia",
        "porque": (
            f"Amparada por «{garantia}»."
            if garantia != "sin_garantia"
            else "SIN garantía declarada. Esto no se ha bloqueado —el dato sale por "
            "el conector, no por aquí— pero queda anotado para que alguien lo "
            "arregle o lo pare donde sí se puede."
        ),
    }


def informe_de_transferencias(db: Session, tenant_id: UUID, *, dias: int = 90) -> dict[str, Any]:
    """Qué ha salido, hacia dónde y con qué amparo.

    Es lo que se le enseña a un cliente que pregunta, y lo que hace falta para
    que la lista de subprocesadores no sea un documento que se escribió una vez.
    """
    from datetime import timedelta

    desde = _ahora() - timedelta(days=max(1, dias))
    filas = (
        db.execute(
            select(TransferenciaInternacional).where(
                TransferenciaInternacional.tenant_id == tenant_id,
                TransferenciaInternacional.created_at >= desde,
            )
        )
        .scalars()
        .all()
    )
    sin_garantia = [f for f in filas if f.garantia == "sin_garantia"]
    activos = (
        db.execute(
            select(Subprocesador).where(
                Subprocesador.tenant_id == tenant_id, Subprocesador.activo.is_(True)
            )
        )
        .scalars()
        .all()
    )
    sin_comunicar = [s.clave for s in activos if s.comunicado_at is None]

    por_destino: dict[str, int] = {}
    for fila in filas:
        por_destino[fila.hacia_region] = por_destino.get(fila.hacia_region, 0) + 1

    return {
        "dias": dias,
        "transferencias": len(filas),
        "por_destino": por_destino,
        "sin_garantia": len(sin_garantia),
        "detalle_sin_garantia": [
            {
                "tipo_dato": f.tipo_dato,
                "hacia": f.hacia_region,
                "subprocesador": f.subprocesador,
                "cuando": f.created_at.isoformat(),
            }
            for f in sin_garantia[:20]
        ],
        "subprocesadores_activos": len(activos),
        # Un subprocesador nuevo del que el cliente no se ha enterado es un
        # incumplimiento del contrato, no un detalle administrativo.
        "sin_comunicar_al_cliente": sin_comunicar,
        "medible": bool(filas) or bool(activos),
        "porque": (
            "No consta ninguna transferencia ni ningún subprocesador. Eso no "
            "significa que no los haya: significa que no se ha anotado ninguno."
            if not filas and not activos
            else "Lo que consta es lo que se ha anotado: las salidas que no pasan "
            "por un punto que anote no aparecen aquí."
        ),
    }


def comunicar_subprocesador(uow: UnidadDeTrabajo, *, tenant_id: UUID, clave: str) -> Subprocesador:
    """Marca que se le ha comunicado al cliente."""
    fila = (
        uow.db.execute(
            select(Subprocesador).where(
                Subprocesador.tenant_id == tenant_id, Subprocesador.clave == clave
            )
        )
        .scalars()
        .first()
    )
    if fila is None:
        raise NoEncontrado(
            "Ese subprocesador no existe", error_code="residencia.subprocesador_no_existe"
        )
    fila.comunicado_at = _ahora()
    uow.db.flush()
    return fila
