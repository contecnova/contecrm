"""Los números de campo del contrato protobuf, guardados por tenant
(CRM-00.02.01.03).

El `.proto` de un objeto **no puede estar en el repositorio**: los campos los
define cada tenant en su metamodelo, y el `contacto` de un cliente tiene ocho
campos que el de otro no tiene. Un fichero fijo sería un contrato equivocado
para todos.

Lo que sí tiene que persistir, y aquí es donde está el riesgo, es **el número de
cada campo**. En protobuf el nombre es cosmético y el número es el contrato: si
el 7 era `descuento` y mañana es `id_zona`, un cliente que aún mande el
descuento escribe una zona. No hay error, no hay log y el dato entra cambiado —
se descubre cuando alguien pregunta por qué ese cliente está en una zona que no
existe.

Por eso:

**El número se asigna una vez y se guarda.** Aunque el campo cambie de sitio,
de etiqueta o de orden.

**Lo que se borra queda reservado para siempre.** Feo de leer, y la única forma
de que su número no se reutilice.

**Y publicar un esquema incompatible se rechaza aquí**, no en la integración del
cliente seis meses después. Lo que rompe se dice entero, con qué campo y qué
pasaría.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.db.base import Base, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from crmcore.rpc.esquema import (
    CAMPOS_QUE_NO_SALEN,
    TIPO_PROTO,
    asignar_numeros,
    comprobar_compatibilidad,
    proto_de_objeto,
)
from sqlalchemy import Integer, String, UniqueConstraint, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

logger = get_logger(__name__)


class ContratoRpc(Base, TimestampMixin):
    """La asignación de números de un objeto, por tenant."""

    __tablename__ = "contratos_rpc"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    objeto: Mapped[str] = mapped_column(String(100), nullable=False)
    # Versión mayor del contrato. Sube solo cuando se acepta a propósito un
    # cambio que rompe: así el paquete pasa a ser `v2` y el cliente que iba por
    # `v1` sigue funcionando en vez de romperse un martes.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    numeros: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    tipos: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # Los que existieron y ya no. No se reutilizan jamás.
    reservados: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    nombres_reservados: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )

    __table_args__ = (UniqueConstraint("tenant_id", "objeto", "version", name="uq_contrato_rpc"),)


def _publicables(campos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Los campos que salen por el contrato, quitando los que no deben salir."""
    return [c for c in campos if str(c.get("tipo") or "") not in CAMPOS_QUE_NO_SALEN]


def _actual(db: Session, tenant_id: UUID, objeto: str, version: int) -> ContratoRpc | None:
    return db.execute(
        select(ContratoRpc).where(
            ContratoRpc.tenant_id == tenant_id,
            ContratoRpc.objeto == objeto,
            ContratoRpc.version == version,
        )
    ).scalar_one_or_none()


def sincronizar(
    uow: UnidadDeTrabajo,
    *,
    objeto: str,
    campos: list[dict[str, Any]],
    version: int = 1,
    aceptar_rotura: bool = False,
) -> dict[str, Any]:
    """Pone al día el contrato de un objeto tras un cambio de esquema.

    Se llama **al publicar el esquema**, no al servir: comprobar la
    compatibilidad cuando ya hay un cliente esperando respuesta es comprobarla
    tarde.

    `aceptar_rotura` no salta la comprobación: exige que alguien haya decidido
    a sabiendas que ese contrato rompe, y lo que hace entonces es **dejarlo
    escrito**, con qué rompe y para quién. Un parámetro que apaga una
    comprobación sin dejar rastro es una comprobación que no existe.
    """
    publicables = _publicables(campos)
    previo = _actual(uow.db, uow.tenant_id, objeto, version)
    asignados = dict(previo.numeros) if previo else {}

    asignacion = asignar_numeros(campos=publicables, asignados=asignados)
    tipos = {
        str(c.get("clave")): TIPO_PROTO[str(c.get("tipo"))]
        for c in publicables
        if str(c.get("tipo")) in TIPO_PROTO
    }

    veredicto: dict[str, Any] = {"compatible": True, "problemas": [], "campos_nuevos": []}
    if previo is not None:
        reservados_finales = sorted(set(previo.reservados or []) | set(asignacion["reservados"]))
        veredicto = comprobar_compatibilidad(
            antes={
                "numeros": dict(previo.numeros),
                "tipos": dict(previo.tipos),
                "reservados": list(previo.reservados or []),
            },
            despues={
                "numeros": asignacion["numeros"],
                "tipos": tipos,
                "reservados": reservados_finales,
            },
        )
        if not veredicto["compatible"] and not aceptar_rotura:
            raise Conflicto(
                "Este cambio de esquema rompe el contrato gRPC de «"
                f"{objeto}». Romper aquí cuesta un minuto; romper en producción "
                "cuesta la llamada del cliente que integró hace seis meses. Si es a "
                "propósito, se publica como versión nueva del contrato.",
                error_code="rpc.contrato_roto",
                detalle={"problemas": veredicto["problemas"]},
            )
    else:
        reservados_finales = list(asignacion["reservados"])

    if previo is None:
        previo = ContratoRpc(tenant_id=uow.tenant_id, objeto=objeto, version=version)
        uow.db.add(previo)

    previo.numeros = asignacion["numeros"]
    previo.tipos = tipos
    previo.reservados = reservados_finales
    previo.nombres_reservados = sorted(
        set(previo.nombres_reservados or []) | set(asignacion["nombres_reservados"])
    )
    uow.db.flush()

    if not veredicto["compatible"]:
        # Aceptada a sabiendas: queda escrita. Sin esto, «aceptar la rotura»
        # sería una casilla que alguien marcó y nadie puede volver a encontrar.
        logger.warning(
            "rpc.contrato_roto_aceptado",
            extra={"objeto": objeto, "problemas": veredicto["problemas"]},
        )

    return {
        "objeto": objeto,
        "version": version,
        "numeros": dict(previo.numeros),
        "reservados": list(previo.reservados),
        "campos_nuevos": veredicto["campos_nuevos"],
        "compatible": veredicto["compatible"],
        "problemas": veredicto["problemas"],
        "campos_que_no_salen": [
            {"clave": c.get("clave"), "porque": CAMPOS_QUE_NO_SALEN[str(c.get("tipo"))]}
            for c in campos
            if str(c.get("tipo") or "") in CAMPOS_QUE_NO_SALEN
        ],
    }


def proto(
    db: Session, tenant_id: UUID, *, objeto: str, campos: list[dict[str, Any]], version: int = 1
) -> dict[str, Any]:
    """El `.proto` que se le entrega a quien va a integrar.

    Sale de los números guardados, no de recalcularlos: recalcular al servir
    daría un fichero distinto según el orden en que vinieran los campos, y el
    integrador se encontraría con que el contrato «cambia solo».
    """
    guardado = _actual(db, tenant_id, objeto, version)
    asignados = dict(guardado.numeros) if guardado else {}
    salida = proto_de_objeto(
        objeto=objeto, campos=_publicables(campos), asignados=asignados, version=version
    )
    salida["numeros_guardados"] = bool(guardado)
    if not guardado:
        salida["aviso"] = (
            "Este contrato aún no está guardado: los números que se ven son los que "
            "se asignarían. Hasta que el esquema se publique, no son un compromiso."
        )
    return salida
