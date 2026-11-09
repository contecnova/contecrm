"""Enriquecimiento firmográfico por el conector de la casa (CRM-01.01.01.08).

Medido el 09-11-2026: `planificar` y `aplicar` calculaban sobre lo que se
tecleara —«lo actual», «lo del proveedor»— y nadie le preguntaba nada a ningún
proveedor. La capacidad constaba hecha y no enriquecía una sola ficha.

Ahora hay **perfiles**: cada uno dice qué conexión y qué operación del conector
de `integration` se llama, con qué campos de la ficha se rellenan sus
parámetros y qué campo de la respuesta va a qué campo del CRM. Ningún proveedor
tiene código aquí: uno de datos de empresa, un registro mercantil o un servicio
propio son una conexión y una operación declaradas allí.

El recorrido es **pedir, revisar y aplicar**:

- **Pedir** llama al proveedor —por HTTP, con la identidad de quien pide— y
  guarda lo que contestó como **propuesta**, separando lo que rellena un hueco
  de lo que contradice a la ficha. No escribe en la ficha.
- **Revisar** es mirar esa propuesta: un proveedor sabe de muchas empresas y no
  conoce a ninguna.
- **Aplicar** escribe los campos elegidos —por defecto, sólo los huecos—, anota
  en el linaje que el valor viene de ese perfil y con qué confianza, y deja el
  antes en la auditoría. Lo que escribió una persona no se pisa salvo que se
  elija expresamente.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.audit.chain import registrar
from crmcore.authz.decision import exigir
from crmcore.db.base import Base, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorDependencia, ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.runtime import settings as rt
from sqlalchemy import Boolean, DateTime, Index, Integer, Numeric, String, UniqueConstraint, select
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from services.party import golden, mdm

ESTADOS = ("pendiente", "aplicada", "descartada", "sin_datos")


class PerfilEnriquecimiento(Base, TimestampMixin):
    """Un proveedor de datos, declarado sobre el conector de la casa."""

    __tablename__ = "perfiles_enriquecimiento"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(60), nullable=False)
    nombre: Mapped[str] = mapped_column(String(150), nullable=False)
    objeto: Mapped[str] = mapped_column(String(40), nullable=False, default="cuenta")
    conexion_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    operacion: Mapped[str] = mapped_column(String(80), nullable=False)
    # {parámetro de la operación: campo de la ficha}
    parametros: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sql_text("'{}'::jsonb")
    )
    # {campo de la ficha: campo del registro devuelto}
    mapeo: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sql_text("'{}'::jsonb")
    )
    confianza: Mapped[int] = mapped_column(Integer, nullable=False, default=40)
    coste_por_consulta: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False, default=0)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (UniqueConstraint("tenant_id", "clave", name="uq_perfil_enriquecimiento"),)


class PropuestaEnriquecimiento(Base, TimestampMixin):
    """Lo que contestó el proveedor de una ficha, esperando a que alguien lo mire."""

    __tablename__ = "propuestas_enriquecimiento"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    perfil_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    perfil_clave: Mapped[str] = mapped_column(String(60), nullable=False)
    objeto: Mapped[str] = mapped_column(String(40), nullable=False)
    objeto_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    # [{campo, actual, propuesto, tipo: hueco|discrepancia|igual}]
    campos: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, info={"anonimizar_en_copias": True}
    )
    estado: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pendiente", info={"opciones": ESTADOS}
    )
    consultado_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    pedido_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    decidido_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    decidido_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    aplicados: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)

    __table_args__ = (
        Index("ix_propuestas_enriquecimiento", "tenant_id", "estado", "objeto", "objeto_id"),
    )


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def perfil_a_dict(p: PerfilEnriquecimiento) -> dict[str, Any]:
    return {
        "id": str(p.id),
        "clave": p.clave,
        "nombre": p.nombre,
        "objeto": p.objeto,
        "conexion_id": str(p.conexion_id),
        "operacion": p.operacion,
        "parametros": dict(p.parametros or {}),
        "mapeo": dict(p.mapeo or {}),
        "confianza": p.confianza,
        "coste_por_consulta": float(p.coste_por_consulta or 0),
        "activo": p.activo,
    }


def propuesta_a_dict(p: PropuestaEnriquecimiento) -> dict[str, Any]:
    return {
        "id": str(p.id),
        "perfil": p.perfil_clave,
        "objeto": p.objeto,
        "objeto_id": str(p.objeto_id),
        "campos": list(p.campos or []),
        "huecos": sum(1 for c in p.campos or [] if c.get("tipo") == "hueco"),
        "discrepancias": sum(1 for c in p.campos or [] if c.get("tipo") == "discrepancia"),
        "estado": p.estado,
        "consultado_at": p.consultado_at.isoformat(),
        "decidido_at": p.decidido_at.isoformat() if p.decidido_at else None,
        "aplicados": list(p.aplicados or []),
    }


def perfiles(db: Session, tenant_id: UUID) -> list[dict[str, Any]]:
    return [
        perfil_a_dict(p)
        for p in db.execute(
            select(PerfilEnriquecimiento)
            .where(PerfilEnriquecimiento.tenant_id == tenant_id)
            .order_by(PerfilEnriquecimiento.clave)
        ).scalars()
    ]


def guardar_perfil(uow: UnidadDeTrabajo, **datos: Any) -> dict[str, Any]:
    objeto = str(datos.get("objeto") or "cuenta")
    componibles = golden.campos_componibles(objeto)
    for campo in dict(datos.get("mapeo") or {}):
        if campo not in componibles:
            raise ErrorValidacion(
                f"«{campo}» no es un campo de {objeto} que se pueda enriquecer.",
                error_code="enriquecimiento.campo_no_valido",
                detalle={"admitidos": componibles},
            )
    if not datos.get("mapeo"):
        raise ErrorValidacion(
            "Un perfil sin mapeo no rellena nada: di qué campo de la respuesta va a "
            "qué campo de la ficha.",
            error_code="enriquecimiento.sin_mapeo",
        )
    fila = uow.db.execute(
        select(PerfilEnriquecimiento).where(
            PerfilEnriquecimiento.tenant_id == uow.tenant_id,
            PerfilEnriquecimiento.clave == datos["clave"],
        )
    ).scalar_one_or_none()
    if fila is None:
        fila = PerfilEnriquecimiento(tenant_id=uow.tenant_id, clave=datos["clave"])
        uow.db.add(fila)
    for campo in (
        "nombre",
        "objeto",
        "conexion_id",
        "operacion",
        "parametros",
        "mapeo",
        "confianza",
        "coste_por_consulta",
        "activo",
    ):
        if campo in datos:
            setattr(fila, campo, datos[campo])
    uow.db.flush()
    return perfil_a_dict(fila)


def borrar_perfil(uow: UnidadDeTrabajo, clave: str) -> None:
    fila = _perfil(uow.db, uow.tenant_id, clave)
    uow.db.delete(fila)
    uow.db.flush()


def _perfil(db: Session, tenant_id: UUID | None, clave: str) -> PerfilEnriquecimiento:
    fila = db.execute(
        select(PerfilEnriquecimiento).where(
            PerfilEnriquecimiento.tenant_id == tenant_id, PerfilEnriquecimiento.clave == clave
        )
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado(
            "Ese perfil de enriquecimiento no existe",
            error_code="enriquecimiento.perfil_no_encontrado",
        )
    return fila


def _valor_de(registro: dict[str, Any], ruta: str) -> Any:
    actual: Any = registro
    for trozo in str(ruta).split("."):
        if not isinstance(actual, dict):
            return None
        actual = actual.get(trozo)
    return actual


def pedir(
    uow: UnidadDeTrabajo, principal: Any, *, perfil: str, objeto_ids: list[UUID]
) -> dict[str, Any]:
    """Pregunta al proveedor por estas fichas y guarda lo que contesta como propuesta."""
    from crmcore.http.interno import invocar

    from services.party.ajustes import ajustes

    fila = _perfil(uow.db, uow.tenant_id, perfil)
    if not fila.activo:
        raise Conflicto(
            "Ese perfil está desactivado.", error_code="enriquecimiento.perfil_inactivo"
        )
    tope = int(
        rt.efectivo("enriquecimiento_max_lote", uow.db) or ajustes().enriquecimiento_max_lote
    )
    if len(objeto_ids) > tope:
        raise ErrorValidacion(
            f"Se piden {len(objeto_ids)} fichas y el tope por vez es {tope}: cada una "
            "es una consulta que se paga.",
            error_code="enriquecimiento.lote_grande",
            detalle={"tope": tope},
        )
    plazo = float(
        rt.efectivo("enriquecimiento_timeout_s", uow.db) or ajustes().enriquecimiento_timeout_s
    )
    modelo = golden._modelo(fila.objeto)
    resultados: list[dict[str, Any]] = []
    for objeto_id in objeto_ids:
        ficha = uow.db.get(modelo, objeto_id)
        if ficha is None or ficha.tenant_id != uow.tenant_id:
            resultados.append({"objeto_id": str(objeto_id), "error": "no_encontrada"})
            continue
        exigir(uow.db, objeto=fila.objeto, accion="read", registro=ficha)
        parametros = {
            param: getattr(ficha, campo, None) for param, campo in (fila.parametros or {}).items()
        }
        respuesta = invocar(
            metodo="POST",
            ruta=(
                f"/api/v1/integraciones/conexiones/{fila.conexion_id}"
                f"/operaciones/{fila.operacion}/invocar"
            ),
            cuerpo={"parametros": parametros},
            tenant_id=principal.tenant_id,
            principal_id=principal.id,
            permisos=sorted(getattr(principal, "permisos", None) or []),
            roles=sorted(getattr(principal, "roles", None) or []),
            tipo="usuario",
            timeout_s=plazo,
        )
        if not respuesta.get("ok"):
            datos = respuesta.get("datos") or {}
            if len(objeto_ids) == 1:
                raise ErrorDependencia(
                    "El proveedor no ha contestado: "
                    + str(datos.get("detail") or datos.get("title") or "")[:300],
                    error_code="enriquecimiento.proveedor_fallo",
                    detalle={"estado_http": respuesta.get("estado"), "perfil": perfil},
                )
            resultados.append(
                {
                    "objeto_id": str(objeto_id),
                    "error": "proveedor",
                    "estado_http": respuesta.get("estado"),
                }
            )
            continue
        registros = [
            r
            for r in ((respuesta.get("datos") or {}).get("registros") or [])
            if isinstance(r, dict)
        ]
        registro = registros[0] if registros else {}
        campos: list[dict[str, Any]] = []
        for campo, ruta in (fila.mapeo or {}).items():
            propuesto = _valor_de(registro, str(ruta or campo))
            if propuesto in (None, ""):
                continue
            actual = getattr(ficha, campo, None)
            if actual in (None, ""):
                tipo = "hueco"
            elif str(actual).strip() == str(propuesto).strip():
                tipo = "igual"
            else:
                tipo = "discrepancia"
            campos.append({"campo": campo, "actual": actual, "propuesto": propuesto, "tipo": tipo})
        propuesta = PropuestaEnriquecimiento(
            tenant_id=uow.tenant_id,
            perfil_id=fila.id,
            perfil_clave=fila.clave,
            objeto=fila.objeto,
            objeto_id=objeto_id,
            campos=campos,
            estado="pendiente" if any(c["tipo"] != "igual" for c in campos) else "sin_datos",
            consultado_at=_ahora(),
            pedido_por=principal.id,
        )
        uow.db.add(propuesta)
        uow.db.flush()
        # La consulta queda en el linaje aunque no se aplique: es lo que dice
        # «cuándo se preguntó al proveedor por última vez» (CRM-01.01.01.08).
        for c in campos:
            mdm.anotar_linaje(
                uow,
                objeto=fila.objeto,
                objeto_id=objeto_id,
                campo=c["campo"],
                fuente=fila.clave,
                valor=c["propuesto"],
                confianza=fila.confianza,
                gana=False,
            )
        resultados.append(propuesta_a_dict(propuesta))
    return {
        "perfil": fila.clave,
        "pedidas": len(objeto_ids),
        "coste_estimado": float(fila.coste_por_consulta or 0) * len(objeto_ids),
        "resultados": resultados,
    }


def propuestas(
    db: Session, tenant_id: UUID, *, estado: str | None = "pendiente", limite: int = 100
) -> list[dict[str, Any]]:
    consulta = select(PropuestaEnriquecimiento).where(
        PropuestaEnriquecimiento.tenant_id == tenant_id
    )
    if estado:
        consulta = consulta.where(PropuestaEnriquecimiento.estado == estado)
    return [
        propuesta_a_dict(p)
        for p in db.execute(
            consulta.order_by(PropuestaEnriquecimiento.consultado_at.desc()).limit(limite)
        ).scalars()
    ]


def _propuesta(db: Session, tenant_id: UUID | None, propuesta_id: UUID) -> PropuestaEnriquecimiento:
    fila = db.get(PropuestaEnriquecimiento, propuesta_id)
    if fila is None or fila.tenant_id != tenant_id:
        raise NoEncontrado(
            "Esa propuesta no existe", error_code="enriquecimiento.propuesta_no_encontrada"
        )
    return fila


def aplicar(
    uow: UnidadDeTrabajo,
    *,
    propuesta_id: UUID,
    campos: list[str] | None = None,
    por: UUID | None = None,
) -> dict[str, Any]:
    """Escribe en la ficha lo elegido. Sin elegir, sólo los huecos."""
    propuesta = _propuesta(uow.db, uow.tenant_id, propuesta_id)
    if propuesta.estado != "pendiente":
        raise Conflicto(
            f"Esa propuesta ya está {propuesta.estado}.",
            error_code="enriquecimiento.ya_decidida",
        )
    modelo = golden._modelo(propuesta.objeto)
    ficha = uow.db.get(modelo, propuesta.objeto_id)
    if ficha is None:
        raise NoEncontrado(
            "La ficha ya no existe", error_code="enriquecimiento.ficha_no_encontrada"
        )
    exigir(uow.db, objeto=propuesta.objeto, accion="write", registro=ficha)
    perfil = uow.db.get(PerfilEnriquecimiento, propuesta.perfil_id)
    confianza = perfil.confianza if perfil is not None else 40
    elegidos = (
        set(campos)
        if campos is not None
        else {c["campo"] for c in propuesta.campos or [] if c.get("tipo") == "hueco"}
    )
    aplicados: list[dict[str, Any]] = []
    for c in propuesta.campos or []:
        if c["campo"] not in elegidos or c.get("tipo") == "igual":
            continue
        antes = getattr(ficha, c["campo"], None)
        setattr(ficha, c["campo"], c["propuesto"])
        aplicados.append({"campo": c["campo"], "antes": antes, "despues": c["propuesto"]})
        mdm.anotar_linaje(
            uow,
            objeto=propuesta.objeto,
            objeto_id=propuesta.objeto_id,
            campo=c["campo"],
            fuente=propuesta.perfil_clave,
            valor=c["propuesto"],
            confianza=confianza,
            gana=True,
        )
    propuesta.estado = "aplicada"
    propuesta.decidido_por = por
    propuesta.decidido_at = _ahora()
    propuesta.aplicados = aplicados
    uow.db.flush()
    registrar(
        uow.db,
        accion="enriquecimiento.aplicado",
        objeto=propuesta.objeto,
        objeto_id=propuesta.objeto_id,
        datos={"perfil": propuesta.perfil_clave, "cambios": aplicados},
        tenant_id=uow.tenant_id,
    )
    return propuesta_a_dict(propuesta)


def descartar(
    uow: UnidadDeTrabajo, *, propuesta_id: UUID, por: UUID | None = None
) -> dict[str, Any]:
    propuesta = _propuesta(uow.db, uow.tenant_id, propuesta_id)
    if propuesta.estado != "pendiente":
        raise Conflicto(
            f"Esa propuesta ya está {propuesta.estado}.",
            error_code="enriquecimiento.ya_decidida",
        )
    propuesta.estado = "descartada"
    propuesta.decidido_por = por
    propuesta.decidido_at = _ahora()
    uow.db.flush()
    return propuesta_a_dict(propuesta)
