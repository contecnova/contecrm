"""Guardarraíles: qué contexto se puede recuperar y qué se puede mandar
(CRM-05.02.02.07).

El agujero de la IA en un CRM no es que el modelo diga tonterías: es que **le
enseñes a alguien lo que no puede ver**. Un resumen de cuenta generado con
documentos que el usuario no tenía permiso para abrir es una fuga, y encima una
elegante: sale redactada, sin citar la fuente y sin que nadie pueda reconstruir de
dónde salió.

De ahí las tres decisiones:

**Los permisos se comprueban ANTES de recuperar el contexto, no después de
generar.** Filtrar la respuesta ya redactada es imposible: el modelo ya mezcló lo
que podía con lo que no, y quitar una frase no quita lo que esa frase implicaba.

**Lo sensible no sale del tenant salvo que se declare.** Datos de salud, datos
bancarios, datos de menores: si el metamodelo los marca, por defecto **no viajan**
al proveedor. Que viajen tiene que ser una decisión escrita, no el comportamiento
por omisión.

**Lo que se bloquea se dice, con qué y por qué.** Una respuesta más corta sin
explicación se lee como que no había información. Aquí se devuelve qué se quitó y
cuánto, para que quien pregunte sepa que su respuesta está incompleta **y por qué**.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.db.base import Base, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import ErrorValidacion, Prohibido
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

logger = get_logger(__name__)

# Sensibilidades que el metamodelo ya usa. Se reutilizan tal cual: una escala
# propia de la IA haría que un campo marcado personal allí no lo pareciera aquí.
SENSIBILIDADES = ("publico", "interno", "confidencial", "personal", "especial")

# Lo que no sale del tenant salvo declaración expresa.
NO_SALEN_POR_DEFECTO = ("personal", "especial")

# Patrones que se tapan antes de enviar. Son los cuatro que aparecen en un CRM
# real dentro de texto libre —notas, correos, descripciones— donde ningún campo
# los declara: por eso hace falta mirar el texto y no solo el esquema.
PATRONES: dict[str, re.Pattern[str]] = {
    "iban": re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b"),
    "tarjeta": re.compile(r"\b(?:\d[ -]?){13,19}\b"),
    "nif": re.compile(r"\b\d{8}[A-Z]\b|\b[A-Z]\d{7}[0-9A-J]\b"),
    "email": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b"),
}


class ReglaGuardia(Base, TimestampMixin):
    """Qué se filtra antes de mandar nada a un modelo (CRM-05.02.02.07)."""

    __tablename__ = "reglas_guardia_ia"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(80), nullable=False)
    # Qué sensibilidades pueden salir del tenant. Vacío = las de por defecto, que
    # dejan fuera lo personal y lo especial.
    sensibilidades_permitidas: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Qué patrones se tapan en el texto libre antes de enviarlo.
    patrones_a_tapar: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Tapar y seguir, o cortar. Tapar es lo razonable casi siempre: cortar deja
    # al usuario sin respuesta por un IBAN que ni siquiera necesitaba.
    cortar_si_aparece: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    max_caracteres: Mapped[int] = mapped_column(Integer, nullable=False, default=100_000)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (UniqueConstraint("tenant_id", "clave", name="uq_regla_guardia_ia"),)


def reglas_declaradas(db: Session, tenant_id: UUID) -> dict[str, Any]:
    """Qué se tapa antes de mandar un dato a un modelo, y qué no sale nunca.

    Existía `GET /ia/guardias/bloqueos` —cuántas veces ha saltado cada uno— y
    **no existía forma de leer la regla**. Se veía que algo había cortado mil
    peticiones y no qué dice: ni qué sensibilidades deja pasar, ni qué patrones
    tapa, ni si corta o sólo enmascara. La ruta que las crea dice que «que
    salgan tiene que ser una decisión escrita, no el comportamiento por
    omisión», y una decisión escrita que no se puede leer no se revisa nunca.

    Sin ninguna regla declarada **no se dice «todo bien»**: se dice que manda
    el comportamiento por defecto, que es no dejar salir lo personal ni lo
    especial. Un vacío en silencio aquí se lee como «no hay restricciones», que
    es exactamente lo contrario de lo que pasa.
    """
    filas = (
        db.execute(
            select(ReglaGuardia)
            .where(ReglaGuardia.tenant_id == tenant_id)
            .order_by(ReglaGuardia.clave)
        )
        .scalars()
        .all()
    )
    return {
        "reglas": [
            {
                "clave": f.clave,
                "sensibilidades_permitidas": list(f.sensibilidades_permitidas or []),
                "patrones_a_tapar": list(f.patrones_a_tapar or []),
                # Cortar y tapar no son lo mismo y se confunden: tapar deja
                # pasar la petición con el dato enmascarado, cortar la rechaza
                # entera. Quien revisa esto necesita saber cuál de las dos.
                "corta": f.cortar_si_aparece,
                "max_caracteres": f.max_caracteres,
                "activa": f.activa,
            }
            for f in filas
        ],
        "cuantas": len(filas),
        "que_significa": (
            "No hay ninguna regla declarada: manda el comportamiento por "
            "defecto, que es que lo personal y lo especial NO salen."
            if not filas
            else "Cada regla dice qué deja pasar y qué tapa. Lo que no nombra "
            "ninguna sigue sin salir."
        ),
    }


class BloqueoIA(Base):
    """Cada vez que un guardarraíl paró algo, y qué paró."""

    __tablename__ = "bloqueos_ia"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    usuario_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    tarea: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    # permiso | sensibilidad | patron | tamano
    motivo: Mapped[str] = mapped_column(String(30), nullable=False)
    detalle: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (Index("ix_bloqueos_ia", "tenant_id", "created_at"),)


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def regla(db: Session, tenant_id: UUID, clave: str = "por_defecto") -> ReglaGuardia | None:
    return db.execute(
        select(ReglaGuardia).where(ReglaGuardia.tenant_id == tenant_id, ReglaGuardia.clave == clave)
    ).scalar_one_or_none()


def declarar_regla(
    uow: UnidadDeTrabajo,
    *,
    clave: str = "por_defecto",
    sensibilidades_permitidas: list[str] | None = None,
    patrones_a_tapar: list[str] | None = None,
    cortar_si_aparece: bool = False,
    max_caracteres: int = 100_000,
) -> tuple[ReglaGuardia, list[str]]:
    """Declara qué puede salir hacia el modelo."""
    for sensibilidad in sensibilidades_permitidas or []:
        if sensibilidad not in SENSIBILIDADES:
            raise ErrorValidacion(
                f"Sensibilidad «{sensibilidad}» no reconocida.",
                error_code="guardias.sensibilidad_no_valida",
                detalle={"validas": list(SENSIBILIDADES)},
            )
    desconocidos = sorted(set(patrones_a_tapar or []) - set(PATRONES))
    if desconocidos:
        raise ErrorValidacion(
            f"Patrones no reconocidos: {desconocidos}.",
            error_code="guardias.patron_no_valido",
            detalle={"validos": sorted(PATRONES)},
        )
    avisos: list[str] = []
    permitidas = set(sensibilidades_permitidas or [])
    if permitidas & set(NO_SALEN_POR_DEFECTO):
        avisos.append(
            "Se está autorizando que salgan datos personales o de categoría "
            "especial hacia el modelo. Es una decisión legítima, pero tiene que "
            "estar respaldada por la base legal y por el contrato con el proveedor."
        )
    fila = regla(uow.db, uow.tenant_id, clave)
    if fila is None:
        fila = ReglaGuardia(tenant_id=uow.tenant_id, clave=clave)
        uow.db.add(fila)
    fila.sensibilidades_permitidas = list(sensibilidades_permitidas or [])
    fila.patrones_a_tapar = list(patrones_a_tapar or sorted(PATRONES))
    fila.cortar_si_aparece = cortar_si_aparece
    fila.max_caracteres = max(1000, int(max_caracteres))
    uow.db.flush()
    return fila, avisos


def filtrar_contexto(
    db: Session,
    tenant_id: UUID,
    *,
    fragmentos: list[dict[str, Any]],
    principal: Any = None,
    clave_regla: str = "por_defecto",
) -> dict[str, Any]:
    """Quita del contexto lo que quien pregunta no puede ver (CRM-05.02.02.07).

    **Antes de generar, no después.** Filtrar una respuesta ya redactada es
    imposible: el modelo ya mezcló lo que podía con lo que no, y quitar una frase
    no quita lo que esa frase implicaba.

    Cada fragmento declara su `permiso` y su `sensibilidad`. Un fragmento **sin
    permiso declarado se descarta**: ante la duda no se enseña, porque el coste de
    equivocarse hacia el otro lado es enseñar a alguien lo que no podía ver.

    Y se devuelve **qué se quitó y por qué**: una respuesta más corta sin
    explicación se lee como que no había información.
    """
    ficha = regla(db, tenant_id, clave_regla)
    permitidas = set(
        (ficha.sensibilidades_permitidas if ficha else None)
        or [s for s in SENSIBILIDADES if s not in NO_SALEN_POR_DEFECTO]
    )
    patrones = list((ficha.patrones_a_tapar if ficha else None) or sorted(PATRONES))
    tope = ficha.max_caracteres if ficha else 100_000

    admitidos: list[dict[str, Any]] = []
    quitados: list[dict[str, Any]] = []
    tapados: dict[str, int] = {}
    caracteres = 0

    for fragmento in fragmentos:
        permiso = str(fragmento.get("permiso") or "")
        etiqueta = str(fragmento.get("fuente") or fragmento.get("id") or "(sin id)")
        if not permiso:
            quitados.append(
                {
                    "fuente": etiqueta,
                    "porque": (
                        "no declara qué permiso hace falta para verlo: ante la duda no " "se enseña"
                    ),
                }
            )
            continue
        tiene = getattr(principal, "tiene", None)
        if not (callable(tiene) and tiene(permiso)):
            quitados.append({"fuente": etiqueta, "porque": f"quien pregunta no tiene «{permiso}»"})
            continue
        sensibilidad = str(fragmento.get("sensibilidad") or "interno")
        if sensibilidad not in permitidas:
            quitados.append(
                {
                    "fuente": etiqueta,
                    "porque": (
                        f"está marcado como «{sensibilidad}» y este tenant no autoriza "
                        "mandarlo al modelo"
                    ),
                }
            )
            continue

        texto = str(fragmento.get("texto") or "")
        for nombre in patrones:
            patron = PATRONES.get(nombre)
            if patron is None:
                continue
            texto, cuantos = patron.subn(f"[{nombre} oculto]", texto)
            if cuantos:
                tapados[nombre] = tapados.get(nombre, 0) + cuantos

        if caracteres + len(texto) > tope:
            quitados.append(
                {
                    "fuente": etiqueta,
                    "porque": f"el contexto ya llegaba al tope de {tope} caracteres",
                }
            )
            continue
        caracteres += len(texto)
        admitidos.append({**fragmento, "texto": texto})

    if ficha is not None and ficha.cortar_si_aparece and tapados:
        raise Prohibido(
            "El contexto contiene datos que esta regla no deja salir: "
            + ", ".join(sorted(tapados)),
            error_code="guardias.patron_prohibido",
            detalle={"patrones": tapados},
        )

    return {
        "fragmentos": admitidos,
        "quitados": quitados,
        "tapados": tapados,
        "caracteres": caracteres,
        # Que se hayan quitado cosas no es un fallo, pero la respuesta va a ser
        # peor y quien la lea tiene que saberlo.
        "completo": not quitados,
        "aviso": (
            ""
            if not quitados
            else f"Se han dejado fuera {len(quitados)} fragmentos: la respuesta será "
            "más pobre de lo que podría, y no porque no hubiera información."
        ),
    }


def anotar_bloqueo(
    uow: UnidadDeTrabajo,
    *,
    motivo: str,
    tarea: str = "",
    usuario_id: UUID | None = None,
    detalle: dict[str, Any] | None = None,
) -> BloqueoIA:
    """Deja constancia de que un guardarraíl paró algo.

    Se cuenta porque un guardarraíl que salta mil veces al día no está
    protegiendo: está estorbando, y hay que mirar la regla. Y uno que no salta
    nunca tampoco protege: hay que comprobar que mira lo que cree que mira.
    """
    fila = BloqueoIA(
        tenant_id=uow.tenant_id,
        usuario_id=usuario_id,
        tarea=tarea,
        motivo=motivo,
        detalle=detalle or {},
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila


def resumen_bloqueos(db: Session, tenant_id: UUID, *, dias: int = 7) -> dict[str, Any]:
    """Cuántas veces y por qué han saltado los guardarraíles."""
    from datetime import timedelta

    desde = _ahora() - timedelta(days=dias)
    filas = (
        db.execute(
            select(BloqueoIA).where(BloqueoIA.tenant_id == tenant_id, BloqueoIA.created_at >= desde)
        )
        .scalars()
        .all()
    )
    por_motivo: dict[str, int] = {}
    for fila in filas:
        por_motivo[fila.motivo] = por_motivo.get(fila.motivo, 0) + 1
    return {
        "dias": dias,
        "bloqueos": len(filas),
        "por_motivo": por_motivo,
        # Las dos lecturas que importan, y son opuestas.
        "estorba": len(filas) > 100 * dias,
        "nunca_salta": len(filas) == 0,
    }
