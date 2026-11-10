"""El golden record sobre los registros reales, guardado con su procedencia
(CRM-01.01.04.06).

Medido el 09-11-2026: `POST /calidad-dato/golden` componía la ficha buena con
lo que se tecleara en el cuerpo y **no guardaba nada**. Las reglas de
supervivencia se escribían en cada llamada y se olvidaban en la siguiente, y
los valores que competían no salían de ningún sitio del CRM: nadie le pasaba lo
que dijo el ERP ni lo que traía la ficha fusionada.

Ahora:

- **Las reglas se guardan**, por objeto y campo, con la confianza de cada
  fuente. El campo `*` es la regla por defecto del objeto. Son configuración: un
  tenant decide que el NIF lo sabe el ERP y el móvil quien habló ayer.
- **Los candidatos salen del CRM**: el linaje anotado de la ficha (lo que dijo
  cada sistema y cuándo cambió), el valor que tiene hoy, el de cada ficha
  **fusionada** en ella (su foto de antes de fundirse) y, en contactos, el de
  cada ficha **unida** por identidad. Es justo donde hay varias versiones de la
  misma verdad.
- **El resultado se guarda** con la procedencia de cada valor —qué fuente ganó,
  con qué regla y por qué— y lo que queda por revisar. Componer no escribe en la
  ficha; **aplicar** sí, y deja el ganador marcado en el linaje y el antes en la
  auditoría.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.audit.chain import registrar
from crmcore.authz.decision import exigir
from crmcore.datos import supervivencia
from crmcore.db.base import Base, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from sqlalchemy import Boolean, DateTime, Index, String, Text, UniqueConstraint, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from services.party import mdm

OBJETOS = ("cuenta", "contacto")

# Columnas que no compiten: son de la fila, no del cliente.
_PROPIAS = frozenset(
    {
        "id",
        "tenant_id",
        "version",
        "clave_canonica",
        "nombre_completo",
        "estado",
        "estado_email",
        "estado_telefono",
        "created_by",
        "updated_by",
        "deleted_by",
    }
)


class ReglaSupervivencia(Base, TimestampMixin):
    """Qué valor sobrevive en un campo, y cuánto se fía de cada fuente."""

    __tablename__ = "reglas_supervivencia"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    objeto: Mapped[str] = mapped_column(String(40), nullable=False)
    # `*` es la regla por defecto del objeto.
    campo: Mapped[str] = mapped_column(String(80), nullable=False)
    estrategia: Mapped[str] = mapped_column(
        String(30), nullable=False, default="mayor_confianza", info={"opciones": mdm.ESTRATEGIAS}
    )
    confianza_por_fuente: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    activa: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    nota: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")

    __table_args__ = (
        UniqueConstraint("tenant_id", "objeto", "campo", name="uq_regla_supervivencia"),
    )


class GoldenRecord(Base, TimestampMixin):
    """La ficha buena compuesta, con de dónde sale cada valor."""

    __tablename__ = "golden_records"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    objeto: Mapped[str] = mapped_column(String(40), nullable=False)
    objeto_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    valores: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
        info={"anonimizar_en_copias": True},
    )
    # {campo: {fuente, regla, porque, candidatos}}
    procedencia: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
        info={"anonimizar_en_copias": True},
    )
    a_revisar: Mapped[list[Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
        info={"anonimizar_en_copias": True},
    )
    # De qué se compuso: {fuente: cuántos valores aportó}.
    fuentes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    aplicado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    aplicados: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    compuesto_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "objeto", "objeto_id", name="uq_golden_record"),
        Index("ix_golden_records_objeto", "tenant_id", "objeto"),
    )


def _modelo(objeto: str) -> Any:
    from services.party.modelos import Contacto, Cuenta

    if objeto not in OBJETOS:
        raise ErrorValidacion(
            f"El golden record se compone para {', '.join(OBJETOS)}.",
            error_code="golden.objeto_no_soportado",
            detalle={"admitidos": list(OBJETOS)},
        )
    return Cuenta if objeto == "cuenta" else Contacto


def campos_componibles(objeto: str) -> list[str]:
    """Los campos de texto del cliente: los que pueden decir cosas distintas."""
    modelo = _modelo(objeto)
    salida = []
    for columna in modelo.__table__.columns:
        nombre = columna.name
        if nombre in _PROPIAS or nombre.endswith(("_id", "_at", "_origen")):
            continue
        if isinstance(columna.type, (String, Text)) and not isinstance(columna.type, JSONB):
            salida.append(nombre)
    return salida


# ── Reglas ────────────────────────────────────────────────────────────────


def _regla_a_dict(r: ReglaSupervivencia) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "objeto": r.objeto,
        "campo": r.campo,
        "estrategia": r.estrategia,
        "confianza_por_fuente": dict(r.confianza_por_fuente or {}),
        "activa": r.activa,
        "nota": r.nota,
    }


def reglas(db: Session, tenant_id: UUID, objeto: str) -> dict[str, Any]:
    _modelo(objeto)
    filas = db.execute(
        select(ReglaSupervivencia)
        .where(ReglaSupervivencia.tenant_id == tenant_id, ReglaSupervivencia.objeto == objeto)
        .order_by(ReglaSupervivencia.campo)
    ).scalars()
    return {
        "objeto": objeto,
        "reglas": [_regla_a_dict(r) for r in filas],
        "campos": campos_componibles(objeto),
        "estrategias": list(mdm.ESTRATEGIAS),
    }


def guardar_regla(
    uow: UnidadDeTrabajo,
    *,
    objeto: str,
    campo: str,
    estrategia: str,
    confianza_por_fuente: dict[str, int] | None = None,
    activa: bool = True,
    nota: str = "",
) -> dict[str, Any]:
    _modelo(objeto)
    if estrategia not in mdm.ESTRATEGIAS:
        raise ErrorValidacion(
            f"Estrategia «{estrategia}» desconocida",
            error_code="mdm.estrategia_invalida",
            detalle={"admitidas": list(mdm.ESTRATEGIAS)},
        )
    if campo != "*" and campo not in campos_componibles(objeto):
        raise ErrorValidacion(
            f"«{campo}» no es un campo que se componga en {objeto}.",
            error_code="golden.campo_no_componible",
            detalle={"admitidos": ["*", *campos_componibles(objeto)]},
        )
    confianzas = supervivencia.validar_confianzas(confianza_por_fuente)
    fila = uow.db.execute(
        select(ReglaSupervivencia).where(
            ReglaSupervivencia.tenant_id == uow.tenant_id,
            ReglaSupervivencia.objeto == objeto,
            ReglaSupervivencia.campo == campo,
        )
    ).scalar_one_or_none()
    if fila is None:
        fila = ReglaSupervivencia(tenant_id=uow.tenant_id, objeto=objeto, campo=campo)
        uow.db.add(fila)
    fila.estrategia = estrategia
    fila.confianza_por_fuente = confianzas
    fila.activa = activa
    fila.nota = nota.strip()
    uow.db.flush()
    registrar(
        uow.db,
        accion="golden.regla_guardada",
        objeto=objeto,
        objeto_id=fila.id,
        datos=_regla_a_dict(fila),
        tenant_id=uow.tenant_id,
    )
    return _regla_a_dict(fila)


def borrar_regla(uow: UnidadDeTrabajo, regla_id: UUID) -> None:
    fila = uow.db.get(ReglaSupervivencia, regla_id)
    if fila is None or fila.tenant_id != uow.tenant_id:
        raise NoEncontrado("Esa regla no existe", error_code="golden.regla_no_encontrada")
    uow.db.delete(fila)
    uow.db.flush()


# ── Candidatos ────────────────────────────────────────────────────────────


def _texto(valor: Any) -> str:
    return "" if valor is None else str(valor).strip()


def _aware(momento: Any) -> datetime | None:
    if isinstance(momento, str):
        try:
            momento = datetime.fromisoformat(momento)
        except ValueError:
            return None
    if isinstance(momento, datetime):
        return momento if momento.tzinfo else momento.replace(tzinfo=timezone.utc)
    return None


def candidatos(db: Session, tenant_id: UUID, *, objeto: str, objeto_id: UUID) -> dict[str, Any]:
    """Lo que dice cada fuente de cada campo de esta ficha."""
    from services.party.identidad import Union
    from services.party.modelos import Fusion

    modelo = _modelo(objeto)
    fila = db.get(modelo, objeto_id)
    if fila is None or fila.tenant_id != tenant_id:
        raise NoEncontrado(
            f"No hay ningún {objeto} con ese identificador",
            error_code="golden.ficha_no_encontrada",
        )
    exigir(db, objeto=objeto, accion="read", registro=fila)
    campos = campos_componibles(objeto)
    por_campo: dict[str, list[dict[str, Any]]] = {c: [] for c in campos}

    def _anadir(campo: str, candidato: dict[str, Any]) -> None:
        if campo not in por_campo or not _texto(candidato.get("valor")):
            return
        # La misma fuente con el mismo valor no compite consigo misma.
        for ya in por_campo[campo]:
            if ya["fuente"] == candidato["fuente"] and _texto(ya["valor"]) == _texto(
                candidato["valor"]
            ):
                return
        por_campo[campo].append(candidato)

    # 1. Lo que dijo cada sistema, anotado en el linaje.
    ids = [objeto_id]
    fusiones = list(
        db.execute(
            select(Fusion).where(
                Fusion.tenant_id == tenant_id,
                Fusion.objeto == objeto,
                Fusion.superviviente_id == objeto_id,
                Fusion.deshecha_at.is_(None),
            )
        ).scalars()
    )
    ids += [f.absorbido_id for f in fusiones]
    for linaje in db.execute(
        select(mdm.LinajeValor).where(
            mdm.LinajeValor.tenant_id == tenant_id,
            mdm.LinajeValor.objeto == objeto,
            mdm.LinajeValor.objeto_id.in_(ids),
        )
    ).scalars():
        _anadir(
            linaje.campo,
            {
                "fuente": linaje.fuente,
                "valor": linaje.valor,
                "cambiado_at": _aware(linaje.cambiado_at),
                "recibido_at": _aware(linaje.recibido_at),
                "origen": "linaje",
            },
        )

    # 2. Lo que tiene hoy la ficha. Si el linaje ya dice de qué fuente viene
    # ese mismo valor, no se repite como «crm».
    for campo in campos:
        valor = getattr(fila, campo, None)
        if _texto(valor) and not any(_texto(c["valor"]) == _texto(valor) for c in por_campo[campo]):
            _anadir(
                campo,
                {
                    "fuente": "crm",
                    "valor": valor,
                    "cambiado_at": _aware(fila.updated_at),
                    "recibido_at": _aware(fila.updated_at),
                    "origen": "ficha",
                },
            )

    # 3. La foto de cada ficha fusionada en esta, de antes de fundirse.
    for fusion in fusiones:
        previo = dict(fusion.estado_previo or {})
        for campo in campos:
            _anadir(
                campo,
                {
                    "fuente": "fusionada",
                    "valor": previo.get(campo),
                    "cambiado_at": _aware(previo.get("updated_at")),
                    "recibido_at": _aware(fusion.created_at),
                    "origen": f"fusion:{fusion.absorbido_id}",
                },
            )

    # 4. En contactos, cada ficha unida por identidad entre canales.
    unidos = 0
    if objeto == "contacto":
        for union in db.execute(
            select(Union).where(
                Union.tenant_id == tenant_id,
                Union.principal_id == objeto_id,
                Union.deshecha_at.is_(None),
            )
        ).scalars():
            otro = db.get(modelo, union.secundario_id)
            if otro is None:
                continue
            unidos += 1
            for campo in campos:
                _anadir(
                    campo,
                    {
                        "fuente": "identidad",
                        "valor": getattr(otro, campo, None),
                        "cambiado_at": _aware(otro.updated_at),
                        "recibido_at": _aware(otro.updated_at),
                        "origen": f"union:{otro.id}",
                    },
                )

    return {
        "fila": fila,
        "campos": {c: v for c, v in por_campo.items() if v},
        "fusionadas": len(fusiones),
        "unidas": unidos,
    }


def _reglas_efectivas(
    db: Session, tenant_id: UUID, objeto: str
) -> tuple[dict[str, ReglaSupervivencia], ReglaSupervivencia | None]:
    filas = {
        r.campo: r
        for r in db.execute(
            select(ReglaSupervivencia).where(
                ReglaSupervivencia.tenant_id == tenant_id,
                ReglaSupervivencia.objeto == objeto,
                ReglaSupervivencia.activa.is_(True),
            )
        ).scalars()
    }
    return filas, filas.get("*")


def componer(
    uow: UnidadDeTrabajo,
    *,
    objeto: str,
    objeto_id: UUID,
    aplicar: bool = False,
    por: UUID | None = None,
) -> dict[str, Any]:
    """Compone, guarda y —si se pide— aplica la ficha buena de este registro."""
    assert uow.tenant_id is not None
    datos = candidatos(uow.db, uow.tenant_id, objeto=objeto, objeto_id=objeto_id)
    fila = datos["fila"]
    if aplicar:
        exigir(uow.db, objeto=objeto, accion="write", registro=fila)
    por_campo, _ = _reglas_efectivas(uow.db, uow.tenant_id, objeto)
    # La decisión es la del núcleo, la misma que la ficha buena del lead.
    compuesto = supervivencia.componer_campos(
        datos["campos"],
        reglas={
            campo: {"estrategia": r.estrategia, "confianza_por_fuente": r.confianza_por_fuente}
            for campo, r in por_campo.items()
        },
    )
    valores: dict[str, Any] = compuesto["valores"]
    procedencia: dict[str, Any] = compuesto["procedencia"]
    a_revisar: list[dict[str, Any]] = compuesto["a_revisar"]
    fuentes: dict[str, int] = compuesto["fuentes"]

    golden = uow.db.execute(
        select(GoldenRecord).where(
            GoldenRecord.tenant_id == uow.tenant_id,
            GoldenRecord.objeto == objeto,
            GoldenRecord.objeto_id == objeto_id,
        )
    ).scalar_one_or_none()
    if golden is None:
        golden = GoldenRecord(tenant_id=uow.tenant_id, objeto=objeto, objeto_id=objeto_id)
        uow.db.add(golden)
    golden.valores = valores
    golden.procedencia = procedencia
    golden.a_revisar = a_revisar
    golden.fuentes = fuentes
    golden.compuesto_por = por
    golden.aplicado_at = None
    golden.aplicados = []

    aplicados: list[dict[str, Any]] = []
    if aplicar:
        for campo, valor in valores.items():
            if valor is None or _texto(getattr(fila, campo, None)) == _texto(valor):
                continue
            aplicados.append(
                {
                    "campo": campo,
                    "antes": getattr(fila, campo, None),
                    "despues": valor,
                    "fuente": procedencia[campo]["fuente"],
                }
            )
            setattr(fila, campo, valor)
        # El ganador queda marcado en el linaje: la próxima vez que alguien
        # pregunte «¿por qué pone esto aquí?», la respuesta es esta.
        for campo, origen in procedencia.items():
            if not origen["fuente"] or valores.get(campo) is None:
                continue
            for linaje in uow.db.execute(
                select(mdm.LinajeValor).where(
                    mdm.LinajeValor.tenant_id == uow.tenant_id,
                    mdm.LinajeValor.objeto == objeto,
                    mdm.LinajeValor.objeto_id == objeto_id,
                    mdm.LinajeValor.campo == campo,
                )
            ).scalars():
                linaje.gana = linaje.fuente == origen["fuente"]
        golden.aplicado_at = datetime.now(timezone.utc)
        golden.aplicados = aplicados
        registrar(
            uow.db,
            accion="golden.aplicado",
            objeto=objeto,
            objeto_id=objeto_id,
            datos={"cambios": aplicados},
            tenant_id=uow.tenant_id,
        )
    uow.db.flush()
    return {
        **a_dict(golden),
        "fusionadas": datos["fusionadas"],
        "unidas": datos["unidas"],
    }


def a_dict(g: GoldenRecord) -> dict[str, Any]:
    return {
        "id": str(g.id),
        "objeto": g.objeto,
        "objeto_id": str(g.objeto_id),
        "valores": dict(g.valores or {}),
        "procedencia": dict(g.procedencia or {}),
        "a_revisar": list(g.a_revisar or []),
        "fuentes": dict(g.fuentes or {}),
        "limpio": not g.a_revisar,
        "compuesto_at": (g.updated_at or g.created_at).isoformat() if g.created_at else None,
        "aplicado_at": g.aplicado_at.isoformat() if g.aplicado_at else None,
        "aplicados": list(g.aplicados or []),
    }


def guardado(db: Session, tenant_id: UUID, *, objeto: str, objeto_id: UUID) -> dict[str, Any]:
    _modelo(objeto)
    g = db.execute(
        select(GoldenRecord).where(
            GoldenRecord.tenant_id == tenant_id,
            GoldenRecord.objeto == objeto,
            GoldenRecord.objeto_id == objeto_id,
        )
    ).scalar_one_or_none()
    if g is None:
        raise NoEncontrado(
            "Esta ficha todavía no tiene golden record compuesto.",
            error_code="golden.sin_componer",
        )
    return a_dict(g)


def con_varias_versiones(db: Session, tenant_id: UUID, *, limite: int = 50) -> list[dict[str, Any]]:
    """Las fichas donde hay más de una versión de la verdad: fusionadas o unidas.

    Es por donde se empieza: componer una ficha con una sola fuente devuelve lo
    que ya tiene.
    """
    from services.party.identidad import Union
    from services.party.modelos import Contacto, Cuenta, Fusion

    salida: dict[tuple[str, UUID], dict[str, Any]] = {}
    for f in db.execute(
        select(Fusion)
        .where(Fusion.tenant_id == tenant_id, Fusion.deshecha_at.is_(None))
        .order_by(Fusion.created_at.desc())
        .limit(limite)
    ).scalars():
        clave = (f.objeto, f.superviviente_id)
        entrada = salida.setdefault(
            clave,
            {
                "objeto": f.objeto,
                "objeto_id": str(f.superviviente_id),
                "fusionadas": 0,
                "unidas": 0,
            },
        )
        entrada["fusionadas"] += 1
    for u in db.execute(
        select(Union)
        .where(Union.tenant_id == tenant_id, Union.deshecha_at.is_(None))
        .order_by(Union.created_at.desc())
        .limit(limite)
    ).scalars():
        clave = ("contacto", u.principal_id)
        entrada = salida.setdefault(
            clave,
            {"objeto": "contacto", "objeto_id": str(u.principal_id), "fusionadas": 0, "unidas": 0},
        )
        entrada["unidas"] += 1
    for (objeto, objeto_id), entrada in salida.items():
        modelo = Cuenta if objeto == "cuenta" else Contacto
        fila = db.get(modelo, objeto_id)
        entrada["nombre"] = (
            getattr(fila, "nombre", None)
            if objeto == "cuenta"
            else getattr(fila, "nombre_completo", None)
        ) or ""
        g = db.execute(
            select(GoldenRecord.updated_at, GoldenRecord.aplicado_at).where(
                GoldenRecord.tenant_id == tenant_id,
                GoldenRecord.objeto == objeto,
                GoldenRecord.objeto_id == objeto_id,
            )
        ).first()
        entrada["compuesto_at"] = g[0].isoformat() if g and g[0] else None
        entrada["aplicado_at"] = g[1].isoformat() if g and g[1] else None
    return list(salida.values())[:limite]
