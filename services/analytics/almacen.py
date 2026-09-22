"""Almacén analítico separado, exportación continua y consulta federada
(CRM-05.01.03.01, .02, .07).

La primera regla de la analítica en un CRM es que **no puede degradar el CRM**.
Una consulta de dirección que recorre tres años de oportunidades bloquea la misma
tabla en la que un comercial está guardando la suya, y lo que se nota es que el
CRM «va lento por las mañanas» — que es cuando se sacan los informes.

De ahí las decisiones:

**El almacén analítico es otro sitio.** Se alimenta por cargas declaradas, no
consultando el operacional en vivo. Y **no lee esquemas ajenos**: cada servicio
entrega sus filas por el mismo camino que cualquier otro dato que cruza un
servicio, porque si la analítica pudiera leer el esquema de ventas, la regla que
sostiene todo el sistema dejaría de ser cierta el día que alguien la aprovechara.

**Lo que se sirve dice de cuándo es.** Un panel que enseña datos de anoche
presentados como de ahora hace que alguien llame a un cliente con una cifra que ya
no existe. Cada tabla analítica lleva su frescura y cada consulta la devuelve.

**Exportar al almacén del cliente es suyo, no nuestro.** Se declara el destino y
lo que sale; el formato es genérico —tabular, con su esquema— y no hay código por
proveedor. Lo que sí hay es **marca de agua**: desde qué instante se exportó por
última vez, para poder seguir por donde se quedó sin repetir ni saltarse nada.

**Y una exportación que falla no avanza la marca.** Avanzarla antes de confirmar
es cómo se pierde un día entero de cambios sin que nadie lo note: el sistema
siguiente cree que ya lo tiene.

**La consulta federada no copia nada, y por eso no promete lo mismo.** Se declara
contra qué lake se pregunta y qué se puede preguntar; lo que no se puede es
cruzarla con las tablas del CRM en la misma consulta sin traer una de las dos, y
eso se dice en vez de dejar que alguien lo descubra con una consulta que no
termina.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.db.base import Base, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
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

# Cómo se carga una tabla analítica.
#
#   completa      se vacía y se vuelve a llenar; sirve para maestros pequeños
#   incremental   solo lo cambiado desde la marca de agua
ESTRATEGIAS = ("completa", "incremental")

# Estado de una carga.
ESTADOS_CARGA = ("en_curso", "ok", "fallida", "parcial")


class TablaAnalitica(Base, TimestampMixin):
    """Una tabla del almacén analítico (CRM-05.01.03.01).

    Es **una copia declarada y fechada**, no una vista del operacional. Eso es lo
    que permite que una consulta larga no toque la tabla donde alguien está
    guardando su oportunidad.
    """

    __tablename__ = "tablas_analiticas"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(80), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # Qué servicio entrega estas filas. No se leen de su esquema: las manda él.
    servicio: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    objeto: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    estrategia: Mapped[str] = mapped_column(String(20), nullable=False, default="incremental")
    # Columnas declaradas: [{nombre, tipo}]. Sirven para validar lo que llega y
    # para publicar el esquema a quien consulte.
    columnas: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Cada cuánto debería cargarse. Es lo que permite decir que una tabla está
    # obsoleta sin esperar a que alguien lo note en un panel.
    frecuencia_min: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    # Hasta dónde se ha traído. La marca de agua es lo que permite seguir por
    # donde se quedó sin repetir ni saltarse nada.
    marca_agua: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ultima_carga_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    filas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "clave", name="uq_tabla_analitica"),
        Index("ix_tablas_analiticas", "tenant_id", "activa", "ultima_carga_at"),
    )


class FilaAnalitica(Base):
    """Una fila del almacén.

    En JSONB y no en columnas: el almacén tiene que poder recibir una tabla nueva
    sin una migración, porque si añadir una métrica exige desplegar, no se añade.
    Lo que sí se exige es que las columnas estén declaradas — recibir cualquier
    cosa daría un almacén que nadie sabe consultar.
    """

    __tablename__ = "filas_analiticas"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    tabla_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tablas_analiticas.id", ondelete="CASCADE"), nullable=False
    )
    # Clave del registro en su servicio de origen: es lo que hace idempotente la
    # carga incremental. Sin ella, cargar dos veces duplica las filas y todos los
    # recuentos salen al doble.
    clave_origen: Mapped[str] = mapped_column(String(200), nullable=False)
    datos: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # Cuándo cambió en el origen, no cuándo se cargó aquí. Es lo que mueve la
    # marca de agua y lo que permite decir la frescura de verdad.
    ocurrido_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cargado_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "tabla_id", "clave_origen", name="uq_fila_analitica"),
        Index("ix_filas_analiticas", "tenant_id", "tabla_id", "ocurrido_at"),
    )


class CargaAnalitica(Base):
    """Cada ejecución de carga, con lo que trajo y lo que falló."""

    __tablename__ = "cargas_analiticas"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    tabla_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="en_curso")
    recibidas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    aplicadas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    descartadas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    desde: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    hasta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_cargas_analiticas", "tenant_id", "tabla_id", "created_at"),)


class DestinoExportacion(Base, TimestampMixin):
    """A dónde se exporta de forma continua (CRM-05.01.03.02).

    El tipo es informativo —`snowflake`, `bigquery`, `databricks`, `s3`— y **no
    cambia el comportamiento**: lo que cambia es la configuración. Si el tipo
    decidiera algo, volveríamos a tener código por proveedor.
    """

    __tablename__ = "destinos_exportacion"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(80), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    tipo: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # Qué tablas salen. Vacío = ninguna: exportar «todo» por defecto saca datos
    # personales a un sitio que quizá no está preparado para tenerlos.
    tablas: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Marca de agua por tabla: {clave_tabla: iso8601}. Es lo que permite seguir
    # por donde se quedó.
    marcas: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    ultimo_envio_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ultimo_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (UniqueConstraint("tenant_id", "clave", name="uq_destino_exportacion"),)


class FuenteFederada(Base, TimestampMixin):
    """Un lake del cliente contra el que se pregunta sin copiar
    (CRM-05.01.03.07)."""

    __tablename__ = "fuentes_federadas"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(80), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    tipo: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # Qué se puede preguntar: tablas o vistas declaradas. Sin lista, una consulta
    # federada puede leer el lake entero del cliente con nuestra credencial.
    objetos: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Tope de filas y de tiempo: una consulta federada mal hecha no se cancela
    # sola y se lleva por delante el presupuesto del lake, que lo paga el cliente.
    tope_filas: Mapped[int] = mapped_column(Integer, nullable=False, default=100_000)
    timeout_s: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (UniqueConstraint("tenant_id", "clave", name="uq_fuente_federada"),)


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _con_tz(valor: datetime | None) -> datetime | None:
    if valor is None:
        return None
    return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)


def _tabla(db: Session, tenant_id: UUID, clave: str) -> TablaAnalitica:
    fila = db.execute(
        select(TablaAnalitica).where(
            TablaAnalitica.tenant_id == tenant_id, TablaAnalitica.clave == clave
        )
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado(
            f"No hay tabla analítica «{clave}»", error_code="almacen.tabla_no_encontrada"
        )
    return fila


# ── Almacén analítico (CRM-05.01.03.01) ───────────────────────────────────


def declarar_tabla(
    uow: UnidadDeTrabajo,
    *,
    clave: str,
    columnas: list[dict[str, Any]],
    servicio: str = "",
    objeto: str = "",
    nombre: str = "",
    estrategia: str = "incremental",
    frecuencia_min: int = 60,
) -> TablaAnalitica:
    """Declara una tabla del almacén.

    Las columnas son obligatorias: un almacén que acepta cualquier forma acaba
    siendo un montón de JSON que nadie sabe consultar, y entonces se consulta el
    operacional otra vez.
    """
    if estrategia not in ESTRATEGIAS:
        raise ErrorValidacion(
            f"Estrategia «{estrategia}» no válida.",
            error_code="almacen.estrategia_no_valida",
            detalle={"validas": list(ESTRATEGIAS)},
        )
    if not columnas:
        raise ErrorValidacion(
            "Una tabla analítica sin columnas declaradas no se puede consultar ni " "validar.",
            error_code="almacen.sin_columnas",
        )
    fila = TablaAnalitica(
        tenant_id=uow.tenant_id,
        clave=clave.strip(),
        nombre=nombre.strip() or clave.strip(),
        servicio=servicio,
        objeto=objeto,
        estrategia=estrategia,
        columnas=list(columnas),
        frecuencia_min=max(1, int(frecuencia_min)),
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila


def cargar(
    uow: UnidadDeTrabajo,
    *,
    tabla: str,
    filas: list[dict[str, Any]],
    hasta: datetime | None = None,
    completa: bool = False,
) -> dict[str, Any]:
    """Aplica una tanda de filas al almacén (CRM-05.01.03.01).

    Las filas **las entrega el servicio dueño**: aquí no se lee su esquema. Cada
    una trae su `clave_origen`, que es lo que hace la carga idempotente — sin
    ella, repetir una carga duplica las filas y todos los recuentos salen al
    doble.

    Lo que no encaja con las columnas declaradas **se descarta y se cuenta**, no
    se guarda a medias: una fila con la mitad de los campos produce un informe
    que suma mal sin que nadie sepa por qué.

    La **marca de agua solo avanza si la carga termina bien**. Avanzarla antes es
    cómo se pierde un día entero de cambios: la siguiente carga cree que ya los
    tiene.
    """
    ficha = _tabla(uow.db, uow.tenant_id, tabla)
    carga = CargaAnalitica(
        tenant_id=uow.tenant_id,
        tabla_id=ficha.id,
        desde=ficha.marca_agua,
        hasta=hasta,
        recibidas=len(filas),
    )
    uow.db.add(carga)
    uow.db.flush()

    declaradas = {str(c.get("nombre")) for c in (ficha.columnas or [])}
    obligatorias = {str(c.get("nombre")) for c in (ficha.columnas or []) if c.get("obligatoria")}

    if completa or ficha.estrategia == "completa":
        # Vaciar y volver a llenar. Se hace dentro de la misma transacción: si la
        # carga falla a mitad, la tabla no se queda vacía, que es peor que
        # quedarse vieja.
        uow.db.execute(
            FilaAnalitica.__table__.delete().where(
                FilaAnalitica.tenant_id == uow.tenant_id, FilaAnalitica.tabla_id == ficha.id
            )
        )

    aplicadas = 0
    descartadas: list[dict[str, Any]] = []
    maximo: datetime | None = None
    for cruda in filas:
        clave_origen = str(cruda.get("clave_origen") or cruda.get("id") or "").strip()
        if not clave_origen:
            descartadas.append({"porque": "sin clave_origen: la carga no sería idempotente"})
            continue
        datos = {k: v for k, v in cruda.items() if k in declaradas}
        faltan = sorted(obligatorias - {k for k, v in datos.items() if v is not None})
        if faltan:
            descartadas.append(
                {"clave_origen": clave_origen, "porque": f"faltan campos: {', '.join(faltan)}"}
            )
            continue
        ocurrido = cruda.get("ocurrido_at")
        ocurrido_at = _con_tz(datetime.fromisoformat(str(ocurrido)) if ocurrido else None)
        if ocurrido_at and (maximo is None or ocurrido_at > maximo):
            maximo = ocurrido_at

        existente = uow.db.execute(
            select(FilaAnalitica).where(
                FilaAnalitica.tenant_id == uow.tenant_id,
                FilaAnalitica.tabla_id == ficha.id,
                FilaAnalitica.clave_origen == clave_origen,
            )
        ).scalar_one_or_none()
        if existente is None:
            uow.db.add(
                FilaAnalitica(
                    tenant_id=uow.tenant_id,
                    tabla_id=ficha.id,
                    clave_origen=clave_origen,
                    datos=datos,
                    ocurrido_at=ocurrido_at,
                )
            )
        else:
            existente.datos = datos
            existente.ocurrido_at = ocurrido_at or existente.ocurrido_at
            existente.cargado_at = _ahora()
        aplicadas += 1

    uow.db.flush()
    total = (
        uow.db.execute(
            select(func.count())
            .select_from(FilaAnalitica)
            .where(FilaAnalitica.tenant_id == uow.tenant_id, FilaAnalitica.tabla_id == ficha.id)
        )
    ).scalar_one()

    carga.aplicadas = aplicadas
    carga.descartadas = len(descartadas)
    carga.estado = "ok" if not descartadas else "parcial"
    ficha.ultima_carga_at = _ahora()
    ficha.filas = int(total)
    # Solo avanza con lo efectivamente aplicado, y nunca hacia atrás.
    if maximo and (ficha.marca_agua is None or maximo > (_con_tz(ficha.marca_agua) or maximo)):
        ficha.marca_agua = maximo
    elif hasta and aplicadas and not maximo:
        ficha.marca_agua = _con_tz(hasta)
    uow.db.flush()

    return {
        "tabla": tabla,
        "recibidas": len(filas),
        "aplicadas": aplicadas,
        "descartadas": descartadas,
        "filas_totales": int(total),
        "marca_agua": ficha.marca_agua.isoformat() if ficha.marca_agua else None,
        # «ok» no es que no fallara: es que no quedó nada fuera. Lo descartado es
        # dato que el informe no va a contar.
        "completa": not descartadas,
    }


def frescura(db: Session, tenant_id: UUID, *, ahora: datetime | None = None) -> dict[str, Any]:
    """De cuándo son los datos de cada tabla (CRM-05.01.03.01).

    Es lo que evita el problema de siempre: un panel que enseña datos de anoche
    presentados como de ahora, y alguien llamando a un cliente con una cifra que
    ya no existe.
    """
    momento = ahora or _ahora()
    filas = (
        db.execute(
            select(TablaAnalitica).where(
                TablaAnalitica.tenant_id == tenant_id, TablaAnalitica.activa.is_(True)
            )
        )
        .scalars()
        .all()
    )
    salida = []
    for fila in filas:
        ultima = _con_tz(fila.ultima_carga_at)
        edad_min = (momento - ultima).total_seconds() / 60 if ultima else None
        salida.append(
            {
                "clave": fila.clave,
                "filas": fila.filas,
                "ultima_carga_at": ultima.isoformat() if ultima else None,
                "edad_min": round(edad_min, 1) if edad_min is not None else None,
                "frecuencia_min": fila.frecuencia_min,
                # Obsoleta con el doble de su frecuencia: una carga perdida es
                # normal, dos seguidas ya no.
                "obsoleta": edad_min is None or edad_min > fila.frecuencia_min * 2,
                "nunca_cargada": ultima is None,
            }
        )
    obsoletas = [s for s in salida if s["obsoleta"]]
    return {
        "en_fecha": momento.isoformat(),
        "tablas": salida,
        "obsoletas": [s["clave"] for s in obsoletas],
        # Si alguna tabla está obsoleta, los paneles que la usan no son de fiar, y
        # eso tiene que poder verse de un vistazo.
        "fiable": not obsoletas,
    }


def leer(
    db: Session,
    tenant_id: UUID,
    *,
    tabla: str,
    limite: int = 1000,
    ahora: datetime | None = None,
) -> dict[str, Any]:
    """Lee del almacén, **diciendo siempre de cuándo son los datos**."""
    ficha = _tabla(db, tenant_id, tabla)
    filas = (
        db.execute(
            select(FilaAnalitica)
            .where(FilaAnalitica.tenant_id == tenant_id, FilaAnalitica.tabla_id == ficha.id)
            .order_by(FilaAnalitica.ocurrido_at.desc())
            .limit(limite)
        )
        .scalars()
        .all()
    )
    momento = ahora or _ahora()
    ultima = _con_tz(ficha.ultima_carga_at)
    edad = (momento - ultima).total_seconds() / 60 if ultima else None
    return {
        "tabla": tabla,
        "columnas": ficha.columnas,
        "filas": [f.datos for f in filas],
        "cuantas": len(filas),
        "datos_de": ultima.isoformat() if ultima else None,
        "edad_min": round(edad, 1) if edad is not None else None,
        "obsoleta": edad is None or edad > ficha.frecuencia_min * 2,
    }


# ── Exportación continua (CRM-05.01.03.02) ────────────────────────────────


def declarar_destino(
    uow: UnidadDeTrabajo,
    *,
    clave: str,
    tipo: str,
    tablas: list[str],
    config: dict[str, Any] | None = None,
    nombre: str = "",
) -> tuple[DestinoExportacion, list[str]]:
    """Declara a dónde se exporta.

    La lista de tablas es obligatoria. Exportar «todo» por defecto saca datos
    personales a un sitio que quizá no está preparado para tenerlos, y eso no se
    deshace.
    """
    if not tablas:
        raise ErrorValidacion(
            "Hay que decir qué tablas salen: exportar todo por defecto saca datos "
            "personales a un sitio que quizá no está preparado para tenerlos.",
            error_code="almacen.destino_sin_tablas",
        )
    conocidas = {
        t.clave
        for t in uow.db.execute(
            select(TablaAnalitica).where(TablaAnalitica.tenant_id == uow.tenant_id)
        ).scalars()
    }
    desconocidas = sorted(set(tablas) - conocidas)
    if desconocidas:
        raise ErrorValidacion(
            f"Estas tablas no existen en el almacén: {desconocidas}.",
            error_code="almacen.tabla_desconocida",
            detalle={"conocidas": sorted(conocidas)},
        )
    avisos: list[str] = []
    if not (config or {}).get("credencial"):
        avisos.append(
            "Sin credencial declarada: la exportación quedará configurada pero no "
            "podrá enviar nada."
        )
    fila = DestinoExportacion(
        tenant_id=uow.tenant_id,
        clave=clave.strip(),
        nombre=nombre.strip() or clave.strip(),
        tipo=tipo.strip(),
        tablas=list(tablas),
        config=dict(config or {}),
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila, avisos


def preparar_envio(
    db: Session, tenant_id: UUID, *, destino: str, tope: int = 10_000
) -> dict[str, Any]:
    """Qué hay que mandar a ese destino desde su última marca.

    **Prepara, no envía.** El envío lo hace quien sabe hablar con ese almacén; lo
    que este módulo garantiza es qué sale y desde dónde, que es lo que decide si
    se pierde o se duplica un día de datos.
    """
    fila = db.execute(
        select(DestinoExportacion).where(
            DestinoExportacion.tenant_id == tenant_id, DestinoExportacion.clave == destino
        )
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado("Ese destino no existe", error_code="almacen.destino_no_encontrado")

    lotes = []
    for clave in fila.tablas or []:
        ficha = _tabla(db, tenant_id, str(clave))
        marca = (fila.marcas or {}).get(str(clave))
        desde = _con_tz(datetime.fromisoformat(str(marca))) if marca else None
        consulta = select(FilaAnalitica).where(
            FilaAnalitica.tenant_id == tenant_id, FilaAnalitica.tabla_id == ficha.id
        )
        if desde is not None:
            consulta = consulta.where(FilaAnalitica.cargado_at > desde)
        filas = db.execute(consulta.order_by(FilaAnalitica.cargado_at).limit(tope)).scalars().all()
        lotes.append(
            {
                "tabla": str(clave),
                "columnas": ficha.columnas,
                "desde": desde.isoformat() if desde else None,
                "filas": [f.datos for f in filas],
                "cuantas": len(filas),
                # Hasta dónde llegaría la marca si el envío va bien. No se guarda
                # todavía: avanzarla antes de confirmar pierde datos en silencio.
                "hasta_propuesto": (_con_tz(filas[-1].cargado_at).isoformat() if filas else None),
                # Con el lote lleno queda más: quien envía tiene que volver a
                # llamar, y si no lo sabe se deja la mitad sin mandar creyendo que
                # terminó.
                "hay_mas": len(filas) == tope,
            }
        )
    return {
        "destino": destino,
        "tipo": fila.tipo,
        "lotes": lotes,
        "total": sum(line["cuantas"] for line in lotes),
        "hay_mas": any(line["hay_mas"] for line in lotes),
    }


def confirmar_envio(
    uow: UnidadDeTrabajo, *, destino: str, marcas: dict[str, str], error: str = ""
) -> DestinoExportacion:
    """Avanza las marcas **después** de que el envío se confirme.

    Si hubo error, no se avanza nada y se guarda por qué: un destino que avanza
    la marca tras un fallo se salta ese tramo para siempre, y nadie lo nota hasta
    que faltan datos en el informe del cliente.
    """
    fila = uow.db.execute(
        select(DestinoExportacion).where(
            DestinoExportacion.tenant_id == uow.tenant_id, DestinoExportacion.clave == destino
        )
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado("Ese destino no existe", error_code="almacen.destino_no_encontrado")
    if error:
        fila.ultimo_error = error
        uow.db.flush()
        return fila
    fila.marcas = {**(fila.marcas or {}), **{k: str(v) for k, v in marcas.items()}}
    fila.ultimo_envio_at = _ahora()
    fila.ultimo_error = None
    uow.db.flush()
    return fila


def retraso_exportacion(
    db: Session, tenant_id: UUID, *, ahora: datetime | None = None
) -> dict[str, Any]:
    """Cuánto lleva cada destino sin recibir, y si hay error pendiente."""
    momento = ahora or _ahora()
    filas = (
        db.execute(
            select(DestinoExportacion).where(
                DestinoExportacion.tenant_id == tenant_id,
                DestinoExportacion.activo.is_(True),
            )
        )
        .scalars()
        .all()
    )
    return {
        "destinos": [
            {
                "clave": f.clave,
                "tipo": f.tipo,
                "ultimo_envio_at": (
                    _con_tz(f.ultimo_envio_at).isoformat() if f.ultimo_envio_at else None
                ),
                "horas_sin_enviar": (
                    round(
                        (momento - (_con_tz(f.ultimo_envio_at) or momento)).total_seconds() / 3600,
                        1,
                    )
                    if f.ultimo_envio_at
                    else None
                ),
                "nunca_enviado": f.ultimo_envio_at is None,
                "con_error": bool(f.ultimo_error),
                "error": f.ultimo_error,
            }
            for f in filas
        ],
        "con_error": len([f for f in filas if f.ultimo_error]),
    }


# ── Consulta federada al lake del cliente (CRM-05.01.03.07) ───────────────


def declarar_fuente_federada(
    uow: UnidadDeTrabajo,
    *,
    clave: str,
    tipo: str,
    objetos: list[str],
    config: dict[str, Any] | None = None,
    nombre: str = "",
    tope_filas: int = 100_000,
    timeout_s: int = 60,
) -> FuenteFederada:
    """Declara un lake contra el que se puede preguntar sin copiar nada.

    La lista de objetos es obligatoria: sin ella, una consulta federada puede leer
    el lake entero del cliente con nuestra credencial, y eso es exactamente lo que
    nadie autorizó al conectar la cuenta.
    """
    if not objetos:
        raise ErrorValidacion(
            "Hay que declarar qué tablas o vistas se pueden consultar: sin lista, "
            "una consulta federada puede leer el lake entero con nuestra credencial.",
            error_code="almacen.federada_sin_objetos",
        )
    fila = FuenteFederada(
        tenant_id=uow.tenant_id,
        clave=clave.strip(),
        nombre=nombre.strip() or clave.strip(),
        tipo=tipo.strip(),
        objetos=list(objetos),
        config=dict(config or {}),
        tope_filas=max(1, int(tope_filas)),
        timeout_s=max(1, int(timeout_s)),
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila


def plan_federado(
    db: Session,
    tenant_id: UUID,
    *,
    fuente: str,
    objeto: str,
    campos: list[str] | None = None,
    filtros: list[dict[str, Any]] | None = None,
    limite: int | None = None,
) -> dict[str, Any]:
    """Prepara una consulta contra el lake, **como plan y no como SQL**.

    Mismo criterio que el motor de informes (RT-4): aquí no se construye SQL. Se
    devuelve un plan que traduce quien habla con ese lake.

    Y se dice lo que **no** se puede hacer: cruzar esto con las tablas del CRM en
    la misma consulta exigiría traer una de las dos, que es copiar con otro
    nombre. Dejar que alguien lo descubra con una consulta que no termina es peor
    que decirlo aquí.
    """
    fila = db.execute(
        select(FuenteFederada).where(
            FuenteFederada.tenant_id == tenant_id, FuenteFederada.clave == fuente
        )
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado(
            "Esa fuente federada no existe", error_code="almacen.federada_no_encontrada"
        )
    if not fila.activa:
        raise Conflicto(
            "Esa fuente federada está desactivada", error_code="almacen.federada_inactiva"
        )
    if objeto not in (fila.objetos or []):
        raise ErrorValidacion(
            f"«{objeto}» no está entre los objetos declarados de esta fuente.",
            error_code="almacen.objeto_no_declarado",
            detalle={"declarados": fila.objetos},
        )
    tope = min(int(limite or fila.tope_filas), fila.tope_filas)
    return {
        "fuente": fuente,
        "tipo": fila.tipo,
        "objeto": objeto,
        "campos": list(campos or []),
        "filtros": list(filtros or []),
        "limite": tope,
        "timeout_s": fila.timeout_s,
        # Se devuelve el tope aplicado aunque el que preguntó pidiera más: un
        # resultado recortado en silencio se lee como un resultado completo.
        "recortado": bool(limite and limite > fila.tope_filas),
        "cruzable_con_el_crm": False,
        "aviso": (
            "Esta consulta no se puede cruzar con tablas del CRM en la misma "
            "ejecución: habría que traer una de las dos, que es copiar con otro "
            "nombre. Para cruzarlas, carga lo que necesites en el almacén analítico."
        ),
    }
