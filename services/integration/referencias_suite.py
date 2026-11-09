"""Notas, ficheros y conversaciones de la suite, vinculados por referencia
(CRM-06.01.03.08, .09, .12).

Hasta el 09-11-2026, `vincular_nota`, `vincular_fichero` y
`vincular_conversacion` devolvían un diccionario y no lo guardaba nadie: la
ficha no podía enseñar ninguna nota vinculada porque no había ninguna. Aquí se
guardan **la referencia y nada más** —ni el contenido de la nota ni el fichero
ni los mensajes—, ligadas al registro del CRM, y los permisos se resuelven en
el origen cada vez que alguien la abre.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.db.base import Base, SoftDeleteMixin, TimestampMixin
from crmcore.errors import CrmError, ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from sqlalchemy import DateTime, Index, String, Text, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

TIPOS = ("nota", "fichero", "conversacion")


class ReferenciaSuite(Base, TimestampMixin, SoftDeleteMixin):
    """Un elemento de la suite colgado de un registro del CRM, sin copiarlo."""

    __tablename__ = "referencias_suite"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False, info={"opciones": TIPOS})
    objeto: Mapped[str] = mapped_column(String(60), nullable=False)
    objeto_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    # La conexión (perfil de suite) que sabe abrirla, y el identificador o
    # enlace en el origen. El contenido NO se guarda.
    conexion_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    referencia: Mapped[str] = mapped_column(Text, nullable=False)
    # El nombre de una nota o de un fichero suele llevar el de una persona
    # («Acta reunión con Ana Pérez»): es dato personal y así consta en el RAT.
    nombre: Mapped[str] = mapped_column(
        String(300), nullable=False, default="", info={"sensibilidad": "personal"}
    )
    # Lo que se exporta de una conversación según el canal (formato, desde,
    # hasta); vacío para notas y ficheros.
    detalle: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    creado_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    # La última vez que se comprobó en el origen, y qué dijo.
    comprobada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ultimo_estado: Mapped[str] = mapped_column(String(30), nullable=False, default="")

    __table_args__ = (Index("ix_referencias_suite_objeto", "tenant_id", "objeto", "objeto_id"),)


def _ajuste(clave: str, db: Session) -> Any:
    from services.integration.ajustes import valor

    return valor(clave, db)


def _verdad(valor: Any) -> bool:
    if isinstance(valor, str):
        return valor.strip().lower() in ("true", "1", "si", "sí", "yes")
    return bool(valor)


def vincular(
    db: Session,
    tenant_id: UUID,
    *,
    tipo: str,
    objeto: str,
    objeto_id: UUID,
    referencia: str,
    nombre: str,
    perfil: str = "",
    exportable: bool = False,
    resumen: str = "",
    por: UUID | None = None,
) -> ReferenciaSuite:
    """Guarda la referencia ligada al registro, con las reglas de cada tipo.

    Las decisiones son las de siempre (`vincular_nota`, `vincular_fichero`,
    `vincular_conversacion`): sin referencia no hay enlace, y el contenido no
    se copia. Lo nuevo es que ahora queda guardada.
    """
    from services.integration import suites_operacion as sop
    from services.integration import suites_recursos as sur

    if tipo not in TIPOS:
        raise ErrorValidacion(
            f"Tipo «{tipo}» desconocido",
            error_code="suite.referencia_tipo",
            detalle={"tipos": list(TIPOS)},
        )
    conexion_id = None
    if perfil:
        from services.integration.modelos import Conexion
        from services.integration.suites import perfil as perfil_suite

        perfil_suite(db, tenant_id, perfil)  # existe y es de suite, o NoEncontrado
        conexion_id = db.execute(
            select(Conexion.id).where(Conexion.tenant_id == tenant_id, Conexion.nombre == perfil)
        ).scalar_one()
    detalle: dict[str, Any] = {}
    if tipo == "nota":
        sur.vincular_nota(
            objeto=objeto,
            objeto_id=objeto_id,
            proveedor=perfil,
            referencia=referencia,
            titulo=nombre,
        )
    elif tipo == "fichero":
        sur.vincular_fichero(
            objeto=objeto,
            objeto_id=objeto_id,
            proveedor=perfil,
            referencia=referencia,
            nombre=nombre,
        )
    else:
        hilo = sop.vincular_conversacion(
            objeto=objeto,
            objeto_id=objeto_id,
            proveedor=perfil,
            referencia=referencia,
            exportable=exportable,
            resumen=resumen,
        )
        detalle = {
            "exportable": exportable,
            "resumen": hilo["resumen"],
            "aviso": hilo["aviso"],
        }
    fila = ReferenciaSuite(
        tenant_id=tenant_id,
        tipo=tipo,
        objeto=objeto,
        objeto_id=objeto_id,
        conexion_id=conexion_id,
        referencia=referencia.strip(),
        nombre=nombre.strip()[:300],
        detalle=detalle,
        creado_por=por,
    )
    db.add(fila)
    db.flush()
    return fila


def de_registro(
    db: Session, tenant_id: UUID, *, objeto: str, objeto_id: UUID
) -> list[ReferenciaSuite]:
    return list(
        db.execute(
            select(ReferenciaSuite)
            .where(
                ReferenciaSuite.tenant_id == tenant_id,
                ReferenciaSuite.objeto == objeto,
                ReferenciaSuite.objeto_id == objeto_id,
                ReferenciaSuite.deleted_at.is_(None),
            )
            .order_by(ReferenciaSuite.created_at.desc())
        )
        .scalars()
        .all()
    )


def abrir(
    db: Session, tenant_id: UUID, *, referencia_id: UUID, usuario_id: UUID | None
) -> dict[str, Any]:
    """Abre la referencia **preguntando al origen** si existe y si esta persona puede.

    Sin operación declarada en el perfil no se dice «accesible»: se dice que no
    se puede comprobar, y el enlace se da para que el origen decida al abrirlo.
    """
    from services.integration import operar
    from services.integration import suites_recursos as sur
    from services.integration.modelos import Conexion

    fila = db.get(ReferenciaSuite, referencia_id)
    if fila is None or fila.tenant_id != tenant_id or fila.deleted_at is not None:
        raise NoEncontrado("La referencia no existe", error_code="suite.referencia_no_encontrada")
    clave = str(_ajuste("suite_op_resolver_referencia", db))
    conexion = db.get(Conexion, fila.conexion_id) if fila.conexion_id else None
    base = {**a_dict(fila), "operacion": clave}
    if conexion is None or not operar.operacion_declarada(db, conexion.id, clave):
        fila.ultimo_estado = "no_comprobable"
        fila.comprobada_at = datetime.now(timezone.utc)
        db.flush()
        return {
            **base,
            "estado": "no_comprobable",
            "ver": None,
            "que_decir": (
                "No se puede comprobar en el origen: "
                + (
                    "la referencia no tiene perfil de suite."
                    if conexion is None
                    else f"el perfil «{conexion.nombre}» no declara la operación «{clave}»."
                )
                + " El enlace se abre y el origen decide si puedes verlo."
            ),
        }
    try:
        respuesta = operar.ejecutar(
            db,
            conexion=conexion,
            clave=clave,
            parametros={
                "referencia": fila.referencia,
                "tipo": fila.tipo,
                "usuario_id": str(usuario_id) if usuario_id else "",
            },
            codigo_error="suite.operacion_no_declarada",
        )
    except CrmError as exc:
        fila.ultimo_estado = "error"
        fila.comprobada_at = datetime.now(timezone.utc)
        db.flush()
        return {
            **base,
            "estado": "error",
            "ver": None,
            "que_decir": f"El origen no ha contestado: {exc.mensaje}"[:500],
        }
    r = operar.primer_registro(respuesta)
    existe = _verdad(r.get("existe", True))
    acceso = _verdad(r.get("tiene_acceso", False))
    if fila.tipo == "fichero":
        veredicto = sur.estado_del_enlace(existe=existe, tiene_acceso=acceso, nombre=fila.nombre)
        estado = veredicto["estado"]
        ver = estado == "disponible"
    else:
        veredicto = sur.resolver_nota(
            referencia=fila.referencia, tiene_acceso=acceso, existe=existe
        )
        ver = bool(veredicto["ver"])
        estado = "disponible" if ver else str(veredicto["motivo"])
    fila.ultimo_estado = estado
    fila.comprobada_at = datetime.now(timezone.utc)
    db.flush()
    return {
        **base,
        "estado": estado,
        "ver": ver,
        "que_decir": veredicto.get("que_decir", ""),
        "url": str(r.get("url") or fila.referencia) if ver else None,
    }


def a_dict(f: ReferenciaSuite) -> dict[str, Any]:
    return {
        "id": str(f.id),
        "tipo": f.tipo,
        "objeto": f.objeto,
        "objeto_id": str(f.objeto_id),
        "referencia": f.referencia,
        "nombre": f.nombre,
        "conexion_id": str(f.conexion_id) if f.conexion_id else None,
        "detalle": f.detalle or {},
        "creado_por": str(f.creado_por) if f.creado_por else None,
        "created_at": f.created_at.isoformat() if f.created_at else None,
        "comprobada_at": f.comprobada_at.isoformat() if f.comprobada_at else None,
        "ultimo_estado": f.ultimo_estado,
    }
