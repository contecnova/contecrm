"""Tipos de registro, límites del esquema y cambios seguros
(CRM-00.04.01.05, CRM-00.04.01.09, CRM-00.04.01.10).

Tres cosas del metamodelo que aparecen siempre en el mismo momento: cuando el
cliente lleva un año configurando y el esquema empieza a pesar.

**Tipos de registro**: el mismo objeto con caras distintas. Una cuenta de
empresa y una cuenta pública no comparten campos ni listas, y modelarlas como
dos objetos rompe los informes —«cuántos clientes tengo» deja de tener una
respuesta— mientras que modelarlas como uno solo llena la ficha de campos que
sobran en la mitad de los casos.

**Límites**: un esquema sin techo llega a doscientos campos por objeto y
entonces todo va lento a la vez — la ficha, el listado, la exportación y las
migraciones. El techo no está para fastidiar: está para que la conversación
ocurra antes de que el sistema vaya mal, y no después.

**Cambios seguros**: renombrar un campo en un CRM con integraciones no es
renombrar una columna. Hay clientes mandando el nombre viejo, y cortarles el
día del cambio convierte una mejora en una incidencia.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.db.base import Base
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

logger = get_logger(__name__)


class TipoRegistro(Base):
    """Una cara distinta del mismo objeto (CRM-00.04.01.05).

    Comparte tabla, identificadores e informes con el resto; cambia qué campos
    se enseñan, en qué orden y con qué valores de lista. Es la diferencia entre
    «cuántos clientes tengo» teniendo respuesta y no teniéndola.
    """

    __tablename__ = "tipos_registro"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    objeto_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("objetos.id", ondelete="CASCADE"), nullable=False
    )
    clave: Mapped[str] = mapped_column(String(60), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    # Layout propio y valores de lista acotados: {"campo": ["a", "b"]}.
    layout: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    valores_lista: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # Campos que este tipo NO usa. Se guardan los que sobran y no los que se
    # usan: así un campo nuevo aparece en todos los tipos por defecto, que es lo
    # que se quiere el 90 % de las veces, en vez de en ninguno.
    campos_ocultos: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    por_defecto: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("uq_tipo_registro", "tenant_id", "objeto_id", "clave", unique=True),)


class CambioEsquema(Base):
    """Un cambio de esquema en curso, con su compatibilidad hacia atrás.

    Renombrar de golpe rompe a quien manda el nombre viejo. Aquí el cambio pasa
    por una fase en la que **los dos nombres funcionan**, y el viejo se retira
    cuando deja de usarse —medido, no supuesto—.
    """

    __tablename__ = "cambios_esquema"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    objeto: Mapped[str] = mapped_column(String(80), nullable=False)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)  # renombrar | deprecar
    campo_origen: Mapped[str] = mapped_column(String(80), nullable=False)
    campo_destino: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # anunciado | compatible | completado
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="anunciado")
    # Veces que se ha usado el nombre viejo desde que empezó el cambio. Es el
    # dato que decide cuándo se puede retirar, en vez de una fecha inventada.
    usos_del_viejo: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ultimo_uso_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_cambios_esquema", "tenant_id", "objeto", "campo_origen"),)


# ── Límites del esquema (CRM-00.04.01.09) ─────────────────────────────────


def limites(db: Session, tenant_id: UUID, objeto_id: UUID) -> dict[str, Any]:
    """Cuánto esquema lleva este objeto y cuánto le queda.

    Se devuelve el porcentaje además del número, y no es cosmética: nadie sabe
    si 140 campos son muchos, y todo el mundo entiende «vas por el 70 %». El
    aviso llega antes del tope para que la conversación ocurra antes de que el
    sistema vaya mal, no después.
    """
    from crmcore.config import get_settings
    from crmcore.runtime import settings as rt

    from services.metadata.modelos import CampoDefinido

    s = get_settings()
    tope = int(rt.efectivo("metadata_max_campos", db) or s.metadata_max_campos)
    aviso_pct = int(rt.efectivo("metadata_aviso_pct", db) or s.metadata_aviso_pct)

    cuantos = int(
        db.execute(
            select(func.count())
            .select_from(CampoDefinido)
            .where(CampoDefinido.objeto_id == objeto_id, CampoDefinido.activo.is_(True))
        ).scalar_one()
        or 0
    )
    pct = round(cuantos / tope * 100, 1) if tope else 0.0
    return {
        "campos": cuantos,
        "tope": tope,
        "pct": pct,
        "en_aviso": pct >= aviso_pct,
        # Lo que pasa al llegar, dicho antes de llegar: un tope que sorprende es
        # un tope que se vive como un fallo del producto.
        "al_llegar": "No se podrán añadir más campos activos hasta retirar alguno",
    }


def exigir_hueco(db: Session, tenant_id: UUID, objeto_id: UUID) -> None:
    """Corta el alta de un campo si el objeto ya está lleno.

    Con el número y el tope en el error: «has llegado al límite» sin decir cuál
    obliga a buscarlo, y quien lo lee está justo en mitad de configurar algo.
    """
    estado = limites(db, tenant_id, objeto_id)
    if estado["campos"] >= estado["tope"]:
        raise Conflicto(
            f"Este objeto ya tiene {estado['campos']} campos y el tope son "
            f"{estado['tope']}. Retira o deprecar alguno antes de añadir más.",
            error_code="metadata.tope_de_campos",
            detalle=estado,
        )


# ── Tipos de registro (CRM-00.04.01.05) ───────────────────────────────────


def guardar_tipo(
    db: Session,
    *,
    tenant_id: UUID,
    objeto_id: UUID,
    clave: str,
    nombre: str,
    layout: dict[str, Any] | None = None,
    valores_lista: dict[str, Any] | None = None,
    campos_ocultos: list[str] | None = None,
    por_defecto: bool = False,
) -> TipoRegistro:
    """Crea o actualiza un tipo de registro.

    Solo puede haber **uno por defecto**: dos por defecto dejarían el alta sin
    saber cuál usar, y el que gane dependería del orden de la consulta —que
    cambia sin avisar.
    """
    if not clave.strip():
        raise ErrorValidacion("El tipo necesita una clave", error_code="tipo.sin_clave")

    fila = db.execute(
        select(TipoRegistro).where(
            TipoRegistro.tenant_id == tenant_id,
            TipoRegistro.objeto_id == objeto_id,
            TipoRegistro.clave == clave,
        )
    ).scalar_one_or_none()
    if fila is None:
        fila = TipoRegistro(tenant_id=tenant_id, objeto_id=objeto_id, clave=clave)
        db.add(fila)

    fila.nombre = nombre
    fila.layout = layout or {}
    fila.valores_lista = valores_lista or {}
    fila.campos_ocultos = list(campos_ocultos or [])
    if por_defecto:
        for otro in db.execute(
            select(TipoRegistro).where(
                TipoRegistro.tenant_id == tenant_id,
                TipoRegistro.objeto_id == objeto_id,
                TipoRegistro.por_defecto.is_(True),
            )
        ).scalars():
            otro.por_defecto = False
    fila.por_defecto = por_defecto
    db.flush()
    logger.info("metadata.tipo_registro_guardado", clave=clave, por_defecto=por_defecto)
    return fila


def describe_para_tipo(campos: list[Any], tipo: TipoRegistro | None) -> list[dict[str, Any]]:
    """Los campos tal como los ve este tipo de registro.

    Sin tipo se devuelven todos: un objeto sin tipos configurados tiene que
    seguir funcionando igual que antes de que existiera esta función.
    """
    if tipo is None:
        return [{"nombre": c.nombre, "oculto": False, "opciones": None} for c in campos]
    ocultos = set(tipo.campos_ocultos or [])
    return [
        {
            "nombre": c.nombre,
            "oculto": c.nombre in ocultos,
            # Las opciones acotadas del tipo mandan sobre las del campo: es para
            # lo que existe el tipo. Si no hay, se usan las del campo.
            "opciones": (tipo.valores_lista or {}).get(c.nombre),
        }
        for c in campos
    ]


# ── Cambios seguros de esquema (CRM-00.04.01.10) ──────────────────────────


def anunciar_renombrado(
    db: Session, *, tenant_id: UUID, objeto: str, desde: str, hasta: str
) -> CambioEsquema:
    """Empieza un renombrado: los dos nombres funcionan a la vez.

    Renombrar de golpe rompe a quien manda el nombre viejo, y en un CRM con
    integraciones eso es siempre alguien. Con la fase compatible, el cambio deja
    de ser un corte y pasa a ser una migración que el cliente hace a su ritmo.
    """
    if desde == hasta:
        raise ErrorValidacion(
            "El nombre nuevo es igual que el viejo", error_code="esquema.renombrado_vacio"
        )
    fila = CambioEsquema(
        tenant_id=tenant_id,
        objeto=objeto,
        tipo="renombrar",
        campo_origen=desde,
        campo_destino=hasta,
        estado="compatible",
    )
    db.add(fila)
    db.flush()
    logger.warning("esquema.renombrado_anunciado", objeto=objeto, desde=desde, hasta=hasta)
    return fila


def traducir_entrada(
    db: Session, tenant_id: UUID, objeto: str, datos: dict[str, Any]
) -> dict[str, Any]:
    """Acepta el nombre viejo y lo traduce al nuevo, contando cada uso.

    Contar es la parte que importa: es lo que permite decidir cuándo se puede
    retirar el viejo **midiendo** en vez de suponiendo. Sin el contador, la
    retirada se hace por fecha y el día que toca siempre hay alguien usándolo.
    """
    cambios = (
        db.execute(
            select(CambioEsquema).where(
                CambioEsquema.tenant_id == tenant_id,
                CambioEsquema.objeto == objeto,
                CambioEsquema.estado == "compatible",
            )
        )
        .scalars()
        .all()
    )
    if not cambios:
        return datos

    salida = dict(datos)
    for cambio in cambios:
        if cambio.campo_origen in salida and cambio.campo_destino:
            # Si vienen los dos, manda el NUEVO: quien ya se ha migrado no puede
            # verse pisado por un campo viejo que su cliente sigue mandando por
            # inercia.
            if cambio.campo_destino not in salida:
                salida[cambio.campo_destino] = salida[cambio.campo_origen]
            salida.pop(cambio.campo_origen, None)
            cambio.usos_del_viejo += 1
            # Con huso, como el resto del sistema: mezclar fechas con y sin él
            # revienta al compararlas, y el sitio donde revienta es justo el que
            # decide si se puede retirar el campo viejo.
            cambio.ultimo_uso_at = datetime.now(timezone.utc)
    return salida


def completar_renombrado(
    db: Session, *, tenant_id: UUID, objeto: str, desde: str, dias_sin_uso: int = 30
) -> CambioEsquema:
    """Retira el nombre viejo, si de verdad ha dejado de usarse.

    Se comprueba con el contador y no con una fecha: el día que toca siempre hay
    alguien usándolo, y cortar entonces convierte una mejora planificada en una
    incidencia con un integrador al teléfono.
    """
    from datetime import timedelta

    cambio = db.execute(
        select(CambioEsquema).where(
            CambioEsquema.tenant_id == tenant_id,
            CambioEsquema.objeto == objeto,
            CambioEsquema.campo_origen == desde,
            CambioEsquema.estado == "compatible",
        )
    ).scalar_one_or_none()
    if cambio is None:
        raise NoEncontrado(
            "No hay ningún renombrado en curso para ese campo",
            error_code="esquema.sin_renombrado",
        )

    if cambio.ultimo_uso_at is not None:
        limite = datetime.now(timezone.utc) - timedelta(days=dias_sin_uso)
        if cambio.ultimo_uso_at > limite:
            raise Conflicto(
                f"El nombre «{desde}» se ha usado {cambio.usos_del_viejo} veces y la "
                f"última hace menos de {dias_sin_uso} días. Retirarlo ahora rompería "
                "a quien lo sigue mandando.",
                error_code="esquema.viejo_todavia_en_uso",
                detalle={
                    "usos": cambio.usos_del_viejo,
                    "ultimo_uso": cambio.ultimo_uso_at.isoformat(),
                },
            )

    cambio.estado = "completado"
    db.flush()
    logger.warning("esquema.renombrado_completado", objeto=objeto, desde=desde)
    return cambio
