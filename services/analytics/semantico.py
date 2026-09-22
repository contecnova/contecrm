"""Modelo semántico y métricas certificadas (CRM-05.01.03.03).

El problema que resuelve esto no es técnico: es que **«ingresos» significa cinco
cosas distintas** en la misma empresa. El de ventas cuenta lo firmado, el de
finanzas lo facturado, el de dirección lo cobrado, y los tres llevan su cifra a la
misma reunión. Nadie miente; nadie está usando la misma definición.

Una métrica certificada es una definición **escrita, con dueño y con versión**.
De ahí las decisiones:

**La definición es un plan, no SQL.** Igual que en el motor de informes (RT-4):
así la misma métrica se puede calcular contra el almacén analítico o contra
contecintelligence sin reescribirla, y nadie mete una subconsulta a mano que solo
funciona en un sitio.

**Certificar es un acto con dueño y fecha.** Una métrica sin dueño no se puede
corregir: cuando alguien detecta que está mal, no hay a quién preguntar y acaba
creándose otra al lado, que es como se llega a cinco definiciones de ingresos.

**Cambiar una métrica certificada crea una versión nueva.** Los informes de hace
tres meses se hicieron con la definición de entonces; reescribirla en sitio haría
que un número publicado cambiara solo, y quien lo miró no se enteraría.

**Lo no certificado se marca como no certificado, y se sirve igual.** Prohibir las
métricas en borrador haría que la gente las calculara en una hoja aparte, que es
justo lo que se quiere evitar; lo que no puede pasar es que se confundan con las
buenas.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.audit import registrar
from crmcore.db.base import Base, TimestampMixin
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
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

logger = get_logger(__name__)

# Identificador admitido para claves y campos. El mismo criterio que en el motor
# de informes: lo que va a acabar nombrando una columna se valida aquí, no allí.
IDENTIFICADOR = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")

# Agregaciones que sabe expresar el plan. Cerrada: una agregación nueva necesita
# que el ejecutor sepa traducirla, y aceptarla sin eso daría una métrica que
# falla al usarse, no al definirse.
AGREGACIONES = ("suma", "cuenta", "cuenta_distinta", "media", "minimo", "maximo", "ratio")

# Estados de una métrica.
#
#   borrador     se está afinando; se sirve marcada
#   certificada  revisada, con dueño y versión
#   obsoleta     ya no se usa; se conserva para poder leer informes viejos
ESTADOS = ("borrador", "certificada", "obsoleta")


class Metrica(Base, TimestampMixin):
    """Una definición de negocio, versionada (CRM-05.01.03.03)."""

    __tablename__ = "metricas_semanticas"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(80), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    # La definición **en palabras**, para quien la lee en un panel. No es
    # decorativa: es lo único que distingue «ingresos firmados» de «ingresos
    # cobrados» para quien no va a mirar el plan.
    definicion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    objeto: Mapped[str] = mapped_column(String(60), nullable=False)
    agregacion: Mapped[str] = mapped_column(String(20), nullable=False, default="suma")
    campo: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # Con `ratio`: numerador y denominador, los dos como claves de métrica.
    numerador: Mapped[str | None] = mapped_column(String(80), nullable=True)
    denominador: Mapped[str | None] = mapped_column(String(80), nullable=True)
    filtros: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    dimensiones: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    unidad: Mapped[str] = mapped_column(String(20), nullable=False, default="")

    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="borrador")
    # Quién responde de ella. Sin dueño, cuando alguien detecta que está mal no
    # hay a quién preguntar y acaba creándose otra al lado.
    dueno_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    certificada_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    certificada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    motivo_version: Mapped[str] = mapped_column(Text, nullable=False, default="")
    vigente: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "clave", "version", name="uq_metrica_version"),
        Index("ix_metricas_vigentes", "tenant_id", "vigente", "estado"),
    )


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _vigente(db: Session, tenant_id: UUID, clave: str) -> Metrica | None:
    return (
        db.execute(
            select(Metrica)
            .where(
                Metrica.tenant_id == tenant_id,
                Metrica.clave == clave,
                Metrica.vigente.is_(True),
            )
            .order_by(Metrica.version.desc())
        )
        .scalars()
        .first()
    )


def definir(
    uow: UnidadDeTrabajo,
    *,
    clave: str,
    nombre: str,
    objeto: str,
    definicion: str = "",
    agregacion: str = "suma",
    campo: str | None = None,
    numerador: str | None = None,
    denominador: str | None = None,
    filtros: list[dict[str, Any]] | None = None,
    dimensiones: list[str] | None = None,
    unidad: str = "",
    dueno_id: UUID | None = None,
) -> tuple[Metrica, list[str]]:
    """Define una métrica **en borrador**.

    Nace sin certificar a propósito: certificar es un acto, y una métrica que
    nace certificada no la ha revisado nadie.
    """
    if not IDENTIFICADOR.match(clave):
        raise ErrorValidacion(
            "La clave de una métrica es un identificador en minúsculas: acaba "
            "nombrando una columna en el plan.",
            error_code="semantico.clave_no_valida",
        )
    if agregacion not in AGREGACIONES:
        raise ErrorValidacion(
            f"Agregación «{agregacion}» no soportada.",
            error_code="semantico.agregacion_no_valida",
            detalle={"validas": list(AGREGACIONES)},
        )
    if agregacion == "ratio" and not (numerador and denominador):
        raise ErrorValidacion(
            "Un ratio necesita numerador y denominador, y los dos tienen que ser "
            "métricas: si no, nadie puede saber qué divide a qué.",
            error_code="semantico.ratio_incompleto",
        )
    if agregacion not in ("cuenta", "ratio") and not campo:
        raise ErrorValidacion(
            f"«{agregacion}» necesita saber sobre qué campo se calcula.",
            error_code="semantico.sin_campo",
        )
    if campo and not IDENTIFICADOR.match(campo):
        raise ErrorValidacion(
            "El campo tiene que ser un identificador válido.",
            error_code="semantico.campo_no_valido",
        )
    if _vigente(uow.db, uow.tenant_id, clave) is not None:
        raise Conflicto(
            "Ya hay una métrica vigente con esa clave. Para cambiarla se crea una "
            "versión nueva, que es lo que impide que un número publicado cambie solo.",
            error_code="semantico.clave_ocupada",
        )

    avisos: list[str] = []
    if not definicion.strip():
        avisos.append(
            "Sin definición en palabras: quien la lea en un panel no podrá "
            "distinguirla de otra parecida, que es el problema que esto resuelve."
        )
    if dueno_id is None:
        avisos.append(
            "Sin dueño: cuando alguien detecte que está mal no habrá a quién "
            "preguntar, y acabará creándose otra al lado."
        )

    fila = Metrica(
        tenant_id=uow.tenant_id,
        clave=clave,
        version=1,
        nombre=nombre.strip(),
        definicion=definicion.strip(),
        objeto=objeto.strip(),
        agregacion=agregacion,
        campo=campo,
        numerador=numerador,
        denominador=denominador,
        filtros=list(filtros or []),
        dimensiones=list(dimensiones or []),
        unidad=unidad,
        dueno_id=dueno_id,
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila, avisos


def certificar(
    uow: UnidadDeTrabajo, *, clave: str, por: UUID | None = None, dueno_id: UUID | None = None
) -> Metrica:
    """Certifica la versión vigente. **Exige dueño y definición escrita.**"""
    fila = _vigente(uow.db, uow.tenant_id, clave)
    if fila is None:
        raise NoEncontrado("No hay métrica con esa clave", error_code="semantico.no_encontrada")
    if dueno_id is not None:
        fila.dueno_id = dueno_id
    if fila.dueno_id is None:
        raise ErrorValidacion(
            "Certificar exige un dueño: una métrica que nadie responde no se puede "
            "corregir cuando falle.",
            error_code="semantico.sin_dueno",
        )
    if not fila.definicion.strip():
        raise ErrorValidacion(
            "Certificar exige la definición en palabras: es lo único que distingue "
            "«ingresos firmados» de «ingresos cobrados» para quien lee el panel.",
            error_code="semantico.sin_definicion",
        )
    fila.estado = "certificada"
    fila.certificada_por = por
    fila.certificada_at = _ahora()
    uow.db.flush()
    registrar(
        uow.db,
        accion="metrica.certificada",
        objeto="metrica",
        objeto_id=fila.id,
        datos={"clave": fila.clave, "version": fila.version},
        tenant_id=uow.tenant_id,
    )
    return fila


def nueva_version(uow: UnidadDeTrabajo, *, clave: str, motivo: str, **cambios: Any) -> Metrica:
    """Crea una versión nueva y deja la anterior como no vigente.

    **Con motivo obligatorio.** Un número publicado que cambia sin explicación
    hace que se desconfíe de todos los demás, y quien lo miró hace tres meses
    tiene derecho a saber que la definición cambió — y a seguir leyendo su informe
    con la de entonces.
    """
    if not motivo.strip():
        raise ErrorValidacion(
            "Cambiar una métrica exige decir por qué: quien leyó el número de hace "
            "tres meses tiene que poder entender la diferencia.",
            error_code="semantico.motivo_obligatorio",
        )
    anterior = _vigente(uow.db, uow.tenant_id, clave)
    if anterior is None:
        raise NoEncontrado("No hay métrica con esa clave", error_code="semantico.no_encontrada")

    nueva = Metrica(
        tenant_id=uow.tenant_id,
        clave=anterior.clave,
        version=anterior.version + 1,
        nombre=cambios.get("nombre", anterior.nombre),
        definicion=cambios.get("definicion", anterior.definicion),
        objeto=cambios.get("objeto", anterior.objeto),
        agregacion=cambios.get("agregacion", anterior.agregacion),
        campo=cambios.get("campo", anterior.campo),
        numerador=cambios.get("numerador", anterior.numerador),
        denominador=cambios.get("denominador", anterior.denominador),
        filtros=list(cambios.get("filtros", anterior.filtros) or []),
        dimensiones=list(cambios.get("dimensiones", anterior.dimensiones) or []),
        unidad=cambios.get("unidad", anterior.unidad),
        dueno_id=cambios.get("dueno_id", anterior.dueno_id),
        # La versión nueva nace **en borrador** aunque la anterior estuviera
        # certificada: certificar es revisar, y lo que ha cambiado no lo ha
        # revisado nadie todavía.
        estado="borrador",
        motivo_version=motivo.strip(),
    )
    anterior.vigente = False
    uow.db.add(nueva)
    uow.db.flush()
    registrar(
        uow.db,
        accion="metrica.nueva_version",
        objeto="metrica",
        objeto_id=nueva.id,
        datos={"clave": clave, "desde": anterior.version, "hasta": nueva.version, "motivo": motivo},
        tenant_id=uow.tenant_id,
    )
    return nueva


def plan_de(
    db: Session,
    tenant_id: UUID,
    *,
    clave: str,
    dimensiones: list[str] | None = None,
    filtros: list[dict[str, Any]] | None = None,
    version: int | None = None,
) -> dict[str, Any]:
    """El plan de cálculo de una métrica (CRM-05.01.03.03).

    **Plan y no SQL**, por lo mismo que en el motor de informes: así la misma
    definición se calcula contra el almacén analítico o contra
    contecintelligence sin reescribirla.

    Se puede pedir una **versión concreta**: es lo que permite reproducir un
    informe de hace tres meses con la definición que tenía entonces, en vez de
    recalcularlo con otra y decir que es el mismo número.
    """
    consulta = select(Metrica).where(Metrica.tenant_id == tenant_id, Metrica.clave == clave)
    if version is not None:
        consulta = consulta.where(Metrica.version == version)
    else:
        consulta = consulta.where(Metrica.vigente.is_(True))
    fila = db.execute(consulta.order_by(Metrica.version.desc())).scalars().first()
    if fila is None:
        raise NoEncontrado("No hay métrica con esa clave", error_code="semantico.no_encontrada")

    pedidas = [d for d in (dimensiones or [])]
    desconocidas = sorted(set(pedidas) - set(fila.dimensiones or []))
    if desconocidas:
        raise ErrorValidacion(
            f"Esta métrica no está definida por {desconocidas}: agrupar por una "
            "dimensión que no forma parte de su definición da un número que no es "
            "esa métrica.",
            error_code="semantico.dimension_no_declarada",
            detalle={"declaradas": fila.dimensiones},
        )

    plan: dict[str, Any] = {
        "metrica": fila.clave,
        "version": fila.version,
        "objeto": fila.objeto,
        "agregacion": fila.agregacion,
        "campo": fila.campo,
        "agrupar_por": pedidas,
        "filtros": [*(fila.filtros or []), *(filtros or [])],
        "unidad": fila.unidad,
        # Lo que hay que enseñar junto al número. Sin esto, una métrica en
        # borrador se lee igual que una certificada.
        "certificada": fila.estado == "certificada",
        "definicion": fila.definicion,
        "dueno_id": str(fila.dueno_id) if fila.dueno_id else None,
        "aviso": (
            ""
            if fila.estado == "certificada"
            else "Métrica sin certificar: el número es correcto según su definición, "
            "pero esa definición no la ha revisado nadie."
        ),
    }
    if fila.agregacion == "ratio":
        plan["numerador"] = plan_de(db, tenant_id, clave=str(fila.numerador))
        plan["denominador"] = plan_de(db, tenant_id, clave=str(fila.denominador))
    return plan


def catalogo(db: Session, tenant_id: UUID, *, solo_certificadas: bool = False) -> dict[str, Any]:
    """El diccionario de métricas, con su estado y su dueño.

    Es el documento que evita la reunión de las cinco definiciones de ingresos, y
    por eso las no certificadas **también salen**: esconderlas hace que se
    calculen en una hoja aparte, que es peor.
    """
    consulta = select(Metrica).where(Metrica.tenant_id == tenant_id, Metrica.vigente.is_(True))
    if solo_certificadas:
        consulta = consulta.where(Metrica.estado == "certificada")
    filas = db.execute(consulta.order_by(Metrica.clave)).scalars().all()
    return {
        "metricas": [
            {
                "clave": f.clave,
                "nombre": f.nombre,
                "version": f.version,
                "definicion": f.definicion,
                "objeto": f.objeto,
                "agregacion": f.agregacion,
                "dimensiones": f.dimensiones,
                "unidad": f.unidad,
                "estado": f.estado,
                "certificada": f.estado == "certificada",
                "dueno_id": str(f.dueno_id) if f.dueno_id else None,
                "sin_dueno": f.dueno_id is None,
            }
            for f in filas
        ],
        "certificadas": len([f for f in filas if f.estado == "certificada"]),
        "en_borrador": len([f for f in filas if f.estado == "borrador"]),
        # Las que nadie responde: es la lista con la que se empieza a ordenar esto.
        "sin_dueno": [f.clave for f in filas if f.dueno_id is None],
    }
