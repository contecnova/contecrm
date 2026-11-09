"""Versionado de la configuración, con diff y vuelta atrás (CRM-00.01.04.02).

Los ajustes en caliente son lo más fácil de cambiar del sistema y lo más difícil
de deshacer: alguien toca un umbral un viernes, el lunes algo va mal, y no hay
forma de saber qué valía antes ni quién lo cambió. El propio mecanismo que los
hace cómodos —se aplican al instante, sin despliegue— es el que borra la
evidencia.

Aquí cada cambio deja **el valor anterior y el nuevo**, con quién y cuándo. Tres
decisiones:

**Se guarda el anterior, no solo el nuevo.** Con solo el nuevo, deshacer exige
reconstruir el histórico hacia atrás y confiar en que no falte ningún apunte. Con
el anterior delante, volver es copiar un valor.

**El diff es entre dos momentos, no entre dos apuntes.** «Qué cambió el viernes»
es la pregunta real, y responderla con una lista de apuntes sueltos obliga a
reconstruirla a mano.

**Volver atrás es un cambio más, no un borrado.** Queda registrado como lo que
es —alguien deshizo aquello— en vez de hacer desaparecer el apunte original, que
dejaría el histórico contando una historia que no pasó.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, Index, String, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from crmcore.db.base import Base
from crmcore.errors import NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger

logger = get_logger(__name__)


class VersionAjuste(Base):
    """Un cambio de configuración, con su antes y su después."""

    __tablename__ = "versiones_ajuste"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    clave: Mapped[str] = mapped_column(String(120), nullable=False)
    ambito: Mapped[str] = mapped_column(String(20), nullable=False)
    ambito_id: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    valor_anterior: Mapped[Any] = mapped_column(JSONB, nullable=True)
    valor_nuevo: Mapped[Any] = mapped_column(JSONB, nullable=True)
    # `cambio` o `vuelta_atras`. Se distingue porque deshacer es una decisión
    # distinta de cambiar, y quien lee el histórico necesita verla.
    tipo: Mapped[str] = mapped_column(String(20), nullable=False, default="cambio")
    por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    motivo: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_versiones_ajuste", "tenant_id", "clave", "created_at"),)


def anotar(
    db: Session,
    *,
    tenant_id: UUID,
    clave: str,
    ambito: str,
    ambito_id: str,
    valor_anterior: Any,
    valor_nuevo: Any,
    por: UUID | None = None,
    motivo: str = "",
    tipo: str = "cambio",
) -> VersionAjuste:
    """Registra un cambio de ajuste. Se llama desde `fijar`, no a mano.

    Desde `fijar` para que no haya forma de cambiar un ajuste sin dejar rastro:
    un histórico que depende de que alguien se acuerde de anotar es un histórico
    con huecos justo donde importa.
    """
    fila = VersionAjuste(
        tenant_id=tenant_id,
        clave=clave,
        ambito=ambito,
        ambito_id=ambito_id,
        valor_anterior=valor_anterior,
        valor_nuevo=valor_nuevo,
        por=por,
        motivo=motivo,
        tipo=tipo,
    )
    db.add(fila)
    db.flush()
    return fila


def historial(
    db: Session, tenant_id: UUID, *, clave: str = "", limite: int = 100
) -> list[dict[str, Any]]:
    """Los cambios, del más reciente al más antiguo.

    **Se desempata por `id`, y no es cosmético.** `created_at` lo rellena
    `now()` de Postgres, que devuelve LA HORA DE INICIO DE LA TRANSACCIÓN: dos
    cambios hechos en la misma —un lote de ajustes de plataforma es justo eso—
    llevan la marca idéntica. Con el empate sin resolver, el orden lo decide la
    colocación física de las filas, que depende de lo que haya en la tabla.

    Medido el 12-10-2026 con la suite entera en un proceso: el histórico salía
    AL REVÉS, el apunte más reciente era el último, y `volver_a` deshacía el
    cambio equivocado — intentaba fijar el valor anterior del PRIMER cambio, que
    es `None`, y la validación lo rechazaba.

    El `id` es un UUIDv7: lleva el instante dentro, así que ordena por tiempo y
    con la resolución que a `created_at` le falta. No hace falta columna nueva.
    """
    consulta = select(VersionAjuste).where(VersionAjuste.tenant_id == tenant_id)
    if clave:
        consulta = consulta.where(VersionAjuste.clave == clave)
    filas = (
        db.execute(
            consulta.order_by(VersionAjuste.created_at.desc(), VersionAjuste.id.desc()).limit(
                limite
            )
        )
        .scalars()
        .all()
    )
    return [_a_dict(f) for f in filas]


def diff(
    db: Session, tenant_id: UUID, *, desde: datetime, hasta: datetime | None = None
) -> list[dict[str, Any]]:
    """Qué cambió entre dos momentos, con el valor de antes y el de ahora.

    Se colapsa por clave y ámbito: si alguien tocó el mismo ajuste cinco veces
    esa tarde, lo que interesa es de dónde salió y dónde acabó, no las cinco
    escalas. Las cinco siguen en el historial para quien las necesite.
    """
    limite = hasta or datetime.now(timezone.utc)
    filas = (
        db.execute(
            select(VersionAjuste)
            .where(
                VersionAjuste.tenant_id == tenant_id,
                VersionAjuste.created_at >= desde,
                VersionAjuste.created_at <= limite,
            )
            # Mismo desempate que en `historial`, y por el mismo motivo: con
            # varios cambios en una transacción, `created_at` empata y el
            # colapso por clave se quedaría con el primero que saliera en vez
            # de con el último.
            .order_by(VersionAjuste.created_at, VersionAjuste.id)
        )
        .scalars()
        .all()
    )

    por_clave: dict[tuple[str, str, str], dict[str, Any]] = {}
    for fila in filas:
        clave = (fila.clave, fila.ambito, fila.ambito_id)
        if clave not in por_clave:
            por_clave[clave] = {
                "clave": fila.clave,
                "ambito": fila.ambito,
                "ambito_id": fila.ambito_id,
                "antes": fila.valor_anterior,
                "cambios": 0,
                "quien": [],
            }
        entrada = por_clave[clave]
        entrada["despues"] = fila.valor_nuevo
        entrada["cambios"] += 1
        if fila.por and str(fila.por) not in entrada["quien"]:
            entrada["quien"].append(str(fila.por))

    # Lo que acabó igual que empezó NO sale: alguien que subió un umbral y lo
    # bajó en la misma tarde no cambió nada, y sacarlo en el diff manda a
    # investigar un cambio que no existe.
    return [e for e in por_clave.values() if e["antes"] != e.get("despues")]


def volver_a(
    db: Session, version_id: UUID, *, tenant_id: UUID, por: UUID | None = None
) -> dict[str, Any]:
    """Deshace un cambio: pone el valor que había antes de ese apunte.

    Se aplica por el camino normal —`fijar`— para que se replique a todos los
    servicios igual que cualquier otro cambio. Escribir la tabla directamente
    dejaría al resto del sistema con el valor deshecho hasta el siguiente
    reinicio, que es el fallo que la réplica por evento vino a cerrar.

    **Queda UN apunte, el de vuelta atrás.** `fijar` anota la versión por su
    cuenta, así que se le pasa el tipo y el motivo; antes se anotaba aquí otra
    vez detrás y el histórico enseñaba dos cambios por cada deshacer (medido el
    09-11-2026 al darle pantalla).

    Si antes de ese cambio el ámbito **no tenía valor propio** (`None`), volver
    no es fijar `None` —ningún ajuste lo admite—: es quitar el valor del ámbito,
    que vuelve a heredar del de encima. Era lo que pasaba al deshacer el primer
    cambio de una clave: la validación rechazaba el `None` y no había forma de
    volver al estado de partida.
    """
    from crmcore.audit.chain import registrar
    from crmcore.runtime import settings as rt

    fila = db.get(VersionAjuste, version_id)
    if fila is None or fila.tenant_id != tenant_id:
        raise NoEncontrado("Esa versión no existe", error_code="ajuste.version_no_existe")

    motivo = f"Vuelta atrás del cambio del {fila.created_at.date().isoformat()}"
    if fila.valor_anterior is None:
        rt.quitar(db, fila.clave, ambito=fila.ambito, ambito_id=fila.ambito_id)  # type: ignore[arg-type]
        anotar(
            db,
            tenant_id=tenant_id,
            clave=fila.clave,
            ambito=fila.ambito,
            ambito_id=fila.ambito_id,
            valor_anterior=fila.valor_nuevo,
            valor_nuevo=None,
            por=por,
            motivo=motivo,
            tipo="vuelta_atras",
        )
    else:
        rt.fijar(
            db,
            fila.clave,
            fila.valor_anterior,
            ambito=fila.ambito,  # type: ignore[arg-type]
            ambito_id=fila.ambito_id,
            por=por,
            motivo=motivo,
            tipo_version="vuelta_atras",
        )
    # Deshacer es una decisión distinta de cambiar, y la auditoría la dice con
    # su nombre y con qué versión se deshizo: «ajuste.cambiado» a secas no
    # permite saber, meses después, que aquello fue volver atrás.
    registrar(
        db,
        accion="ajuste.vuelta_atras",
        objeto="ajuste",
        objeto_id=fila.clave,
        datos={
            "version": str(version_id),
            "ambito": fila.ambito,
            "ambito_id": fila.ambito_id,
            "de": fila.valor_nuevo,
            "a": fila.valor_anterior,
        },
        tenant_id=tenant_id,
    )
    logger.warning(
        "ajuste.vuelta_atras", clave=fila.clave, ambito=fila.ambito, version=str(version_id)
    )
    return {
        "clave": fila.clave,
        "valor": fila.valor_anterior,
        "heredado": fila.valor_anterior is None,
    }


def comparar(db: Session, tenant_id: UUID, a: UUID, b: UUID) -> dict[str, Any]:
    """Las diferencias entre dos versiones de un ajuste, campo a campo.

    Se compara lo que quedó puesto en cada una (`valor_nuevo`). Con valores
    sencillos es «antes X, después Y»; con un ajuste estructurado —una lista de
    reglas, un diccionario de umbrales— se dice QUÉ entrada cambió, que es lo
    que no se ve mirando dos JSON enteros uno al lado del otro.

    Las dos versiones tienen que ser de la misma clave y del mismo ámbito:
    comparar el idioma de un usuario con el de la empresa es comparar dos cosas
    que no se sustituyen la una a la otra.
    """
    from crmcore.errors import ErrorValidacion

    filas = [db.get(VersionAjuste, x) for x in (a, b)]
    if any(f is None or f.tenant_id != tenant_id for f in filas):
        raise NoEncontrado("Esa versión no existe", error_code="ajuste.version_no_existe")
    va, vb = filas  # type: ignore[misc]
    assert va is not None and vb is not None
    if (va.clave, va.ambito, va.ambito_id) != (vb.clave, vb.ambito, vb.ambito_id):
        raise ErrorValidacion(
            "Sólo se comparan versiones del mismo ajuste en el mismo ámbito",
            error_code="ajuste.versiones_no_comparables",
        )
    # La más antigua a la izquierda, se pidan en el orden que se pidan.
    if (vb.created_at, vb.id) < (va.created_at, va.id):
        va, vb = vb, va
    return {
        "clave": va.clave,
        "ambito": va.ambito,
        "ambito_id": va.ambito_id,
        "desde": _a_dict(va),
        "hasta": _a_dict(vb),
        "cambios": diferencias(va.valor_nuevo, vb.valor_nuevo),
    }


def diferencias(antes: Any, despues: Any, ruta: str = "") -> list[dict[str, Any]]:
    """Lo que cambió entre dos valores, con la ruta de cada cambio.

    Recursivo sobre diccionarios; una lista se compara entera porque sus
    posiciones no tienen nombre y emparejarlas por índice inventaría cambios
    cuando sólo se ha insertado un elemento.
    """
    if isinstance(antes, dict) and isinstance(despues, dict):
        salida: list[dict[str, Any]] = []
        for clave in sorted(set(antes) | set(despues), key=str):
            sub = f"{ruta}.{clave}" if ruta else str(clave)
            if clave not in antes:
                salida.append(
                    {"ruta": sub, "tipo": "anadido", "antes": None, "despues": despues[clave]}
                )
            elif clave not in despues:
                salida.append(
                    {"ruta": sub, "tipo": "quitado", "antes": antes[clave], "despues": None}
                )
            else:
                salida.extend(diferencias(antes[clave], despues[clave], sub))
        return salida
    if antes == despues:
        return []
    return [{"ruta": ruta, "tipo": "cambiado", "antes": antes, "despues": despues}]


def claves_con_historial(db: Session, tenant_id: UUID) -> list[dict[str, Any]]:
    """Qué ajustes tienen cambios guardados, con cuántos y el último.

    Es la entrada de la pantalla: sin esto, para ver el historial de un ajuste
    había que saber de antemano que alguien lo había tocado.
    """
    filas = db.execute(
        select(
            VersionAjuste.clave,
            func.count(VersionAjuste.id),
            func.max(VersionAjuste.created_at),
        )
        .where(VersionAjuste.tenant_id == tenant_id)
        .group_by(VersionAjuste.clave)
        .order_by(func.max(VersionAjuste.created_at).desc())
    ).all()
    return [
        {"clave": clave, "cambios": int(n), "ultimo": ultimo.isoformat()}
        for clave, n, ultimo in filas
    ]


def _a_dict(fila: VersionAjuste) -> dict[str, Any]:
    return {
        "id": str(fila.id),
        "clave": fila.clave,
        "ambito": fila.ambito,
        "ambito_id": fila.ambito_id,
        "antes": fila.valor_anterior,
        "despues": fila.valor_nuevo,
        "tipo": fila.tipo,
        "por": str(fila.por) if fila.por else None,
        "motivo": fila.motivo,
        "cuando": fila.created_at.isoformat(),
    }
