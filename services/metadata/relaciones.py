"""Relaciones entre objetos, declaradas y con semántica (CRM-00.04.01.03).

Un modelo de datos extensible no es una lista de objetos con campos: es un
**grafo**. Sin declarar las relaciones, cada una vive escondida dentro de un
campo `lookup` y nadie puede responder a «¿qué se rompe si borro esta cuenta?»,
que es justo la pregunta que hay que contestar **antes** de borrarla.

Los seis tipos que se declaran no son etiquetas: cada uno impone reglas
distintas, y validarlas al declarar la relación es lo que evita descubrirlas
cuando ya hay cien mil registros:

  * **Referencia (1:N)** — la normal. El destino existe por su cuenta.
  * **1:1** — una referencia que además exige unicidad. Sin esa exigencia es
    una 1:N con la costumbre de tener una sola, que es otra cosa.
  * **N:M** — necesita un objeto intermedio, y ahí es donde viven los datos de
    la propia relación: el rol de un contacto en una cuenta, la fecha desde la
    que un socio lo es.
  * **Jerárquica** — origen y destino son el mismo objeto. Hay que impedir
    ciclos: un ciclo hace que consolidar importes o calcular visibilidad no
    termine nunca, y el síntoma es una petición colgada, no un error.
  * **Polimórfica** — el destino puede ser de varios tipos. Es lo que permite
    que una actividad cuelgue de una cuenta, de una oportunidad o de un caso.
  * **Maestro-detalle** — el detalle **no existe** sin su maestro: se borra con
    él, hereda su visibilidad y su propietario. Es lo que la distingue de una
    referencia, y confundirlas deja líneas de pedido huérfanas apuntando a un
    pedido que ya no está.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

# `comprobar_ciclo` vive en el núcleo: la usan varios servicios, y uno no
# puede importar de otro. Se reexporta aquí porque es donde se documenta la
# semántica de las relaciones jerárquicas.
from crmcore.datos.jerarquia import comprobar_ciclo  # noqa: F401
from crmcore.db.base import Base, TimestampMixin
from crmcore.errors import Conflicto, ErrorValidacion
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import (
    Boolean,
    Index,
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

TIPOS = {
    "referencia": "El destino existe por su cuenta; borrarlo solo desvincula",
    "maestro_detalle": "El detalle no existe sin su maestro: se borra con él",
    "jerarquica": "El objeto se relaciona consigo mismo formando un árbol",
    "polimorfica": "El destino puede ser de varios tipos distintos",
}
CARDINALIDADES = ("1:1", "1:N", "N:M")
# Qué pasa con lo que apunta cuando se borra lo apuntado.
AL_BORRAR = {
    "restringir": "No deja borrar mientras haya algo apuntando",
    "cascada": "Borra también lo que apunta",
    "desvincular": "Deja el registro y le quita la referencia",
}


class RelacionDefinida(Base, TimestampMixin):
    """Una relación declarada entre dos objetos del modelo."""

    __tablename__ = "relaciones"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)

    nombre: Mapped[str] = mapped_column(String(80), nullable=False)
    etiqueta: Mapped[str] = mapped_column(String(200), nullable=False)
    # Cómo se llama la relación vista desde el otro lado. Sin esto, la ficha del
    # destino enseña «relaciones» sin nombre y nadie sabe qué está viendo:
    # desde la cuenta se llama «contactos» y desde el contacto, «cuentas».
    nombre_inverso: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    descripcion: Mapped[str] = mapped_column(Text, nullable=False, default="")

    origen: Mapped[str] = mapped_column(String(80), nullable=False)
    # Nulo en las polimórficas, que usan `destinos`.
    destino: Mapped[str | None] = mapped_column(String(80), nullable=True)
    destinos: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )

    tipo: Mapped[str] = mapped_column(String(20), nullable=False, default="referencia")
    cardinalidad: Mapped[str] = mapped_column(
        String(5), nullable=False, default="1:N", info={"opciones": CARDINALIDADES}
    )
    al_borrar: Mapped[str] = mapped_column(String(20), nullable=False, default="restringir")
    obligatoria: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Objeto intermedio de una N:M. Ahí viven los datos de la propia relación.
    via: Mapped[str | None] = mapped_column(String(80), nullable=True)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "nombre", name="uq_relacion_nombre"),
        Index("ix_relaciones_origen", "tenant_id", "origen", "activa"),
        Index("ix_relaciones_destino", "tenant_id", "destino", "activa"),
    )


def validar(datos: dict[str, Any]) -> list[str]:
    """Todos los problemas de una relación, no el primero.

    Se devuelven todos porque quien está modelando un objeto agradece ver de una
    vez las tres cosas que no encajan, en vez de corregir una, reenviar y
    descubrir la siguiente.

    Cada regla de aquí es una que, si no se comprueba ahora, se descubre con
    datos dentro — y entonces arreglarla es una migración.
    """
    problemas: list[str] = []
    tipo = datos.get("tipo", "referencia")
    cardinalidad = datos.get("cardinalidad", "1:N")
    al_borrar = datos.get("al_borrar", "restringir")
    origen = datos.get("origen")
    destino = datos.get("destino")
    destinos = list(datos.get("destinos") or [])

    if tipo not in TIPOS:
        problemas.append(f"Tipo desconocido «{tipo}». Admitidos: {', '.join(sorted(TIPOS))}")
    if cardinalidad not in CARDINALIDADES:
        problemas.append(
            f"Cardinalidad desconocida «{cardinalidad}». Admitidas: {', '.join(CARDINALIDADES)}"
        )
    if al_borrar not in AL_BORRAR:
        problemas.append(
            f"«al_borrar» desconocido: {al_borrar}. Admitidos: {', '.join(sorted(AL_BORRAR))}"
        )
    if not origen:
        problemas.append("Falta el objeto de origen")

    if tipo == "polimorfica":
        if destino:
            problemas.append(
                "Una relación polimórfica no tiene un destino único: enumera los "
                "tipos admitidos en «destinos»"
            )
        if len(destinos) < 2:
            problemas.append(
                "Una relación polimórfica necesita al menos dos destinos posibles; "
                "con uno solo es una referencia normal"
            )
        if cardinalidad == "N:M":
            problemas.append(
                "Polimórfica y N:M a la vez no se puede resolver: la tabla "
                "intermedia tendría que apuntar a tipos distintos por fila"
            )
        if al_borrar == "cascada":
            problemas.append(
                "Una polimórfica no puede borrar en cascada: habría que cascadear "
                "sobre tipos distintos, cada uno con sus propias reglas"
            )
    elif not destino:
        problemas.append("Falta el objeto de destino")

    if tipo == "maestro_detalle":
        # Estas tres no son configurables: son lo que SIGNIFICA maestro-detalle.
        # Dejar elegirlas convertiría el tipo en una etiqueta sin efecto, y la
        # diferencia con una referencia es justo esto.
        if cardinalidad != "1:N":
            problemas.append("Una relación maestro-detalle es siempre 1:N")
        if al_borrar != "cascada":
            problemas.append(
                "Una maestro-detalle borra en cascada por definición: el detalle "
                "no existe sin su maestro"
            )
        if not datos.get("obligatoria", False):
            problemas.append(
                "Una maestro-detalle es obligatoria por definición: un detalle sin "
                "maestro es un huérfano"
            )

    if tipo == "jerarquica":
        if destino and destino != origen:
            problemas.append(
                "Una relación jerárquica va de un objeto a sí mismo; para relacionar "
                "dos objetos distintos usa una referencia"
            )
        if cardinalidad == "N:M":
            problemas.append(
                "Una jerarquía N:M no es un árbol: cada nodo tendría varios padres "
                "y consolidar por ella daría totales repetidos"
            )
        if al_borrar == "cascada":
            problemas.append(
                "Una jerarquía no borra en cascada: borrar la matriz se llevaría "
                "por delante el grupo entero sin que nadie lo haya pedido"
            )

    if cardinalidad == "N:M" and not datos.get("via"):
        problemas.append(
            "Una N:M necesita un objeto intermedio en «via»: es donde viven los "
            "datos de la propia relación, como el rol de un contacto en una cuenta"
        )
    if cardinalidad != "N:M" and datos.get("via"):
        problemas.append("«via» solo tiene sentido en una relación N:M")

    if cardinalidad == "1:1" and al_borrar == "restringir" and datos.get("obligatoria"):
        # No es un error, pero sí un callejón: se avisa.
        problemas.append(
            "Una 1:1 obligatoria que además restringe el borrado deja los dos "
            "registros atados: no se podría borrar ninguno de los dos"
        )

    return problemas


def crear(db: Session, *, tenant_id: UUID, datos: dict[str, Any]) -> RelacionDefinida:
    """Declara una relación tras validarla."""
    problemas = validar(datos)
    if problemas:
        raise ErrorValidacion(
            "La relación no es coherente",
            error_code="metadata.relacion_incoherente",
            detalle={"problemas": problemas},
        )
    ya = db.execute(
        select(RelacionDefinida).where(
            RelacionDefinida.tenant_id == tenant_id,
            RelacionDefinida.nombre == datos["nombre"],
        )
    ).scalar_one_or_none()
    if ya is not None:
        raise Conflicto(
            f"Ya hay una relación llamada «{datos['nombre']}»",
            error_code="metadata.relacion_duplicada",
        )

    fila = RelacionDefinida(tenant_id=tenant_id, **datos)
    db.add(fila)
    db.flush()
    logger.info(
        "metadata.relacion_declarada",
        nombre=fila.nombre,
        tipo=fila.tipo,
        origen=fila.origen,
        destino=fila.destino or ",".join(str(d) for d in fila.destinos),
    )
    return fila


# ── Semántica en ejecución ────────────────────────────────────────────────


@dataclass
class PasoBorrado:
    """Qué le pasaría a un objeto relacionado si se borra el origen."""

    relacion: str
    objeto: str
    efecto: str  # cascada | desvincular | impide

    def a_dict(self) -> dict[str, str]:
        return {"relacion": self.relacion, "objeto": self.objeto, "efecto": self.efecto}


def plan_de_borrado(db: Session, *, tenant_id: UUID, objeto: str) -> list[PasoBorrado]:
    """Qué arrastra, qué desvincula y qué impide borrar este objeto.

    Es la respuesta a «¿qué se rompe si borro esto?», y hay que poder darla
    **antes** de borrar. Un borrado que descubre sus consecuencias a medias deja
    el modelo en un estado que nadie sabe describir.

    Solo mira las relaciones **declaradas**. Lo que un servicio arrastre por su
    cuenta —la cascada de la papelera, una clave ajena— no sale aquí, y se dice
    en vez de fingir que esto es la lista completa.
    """
    relaciones = (
        db.execute(
            select(RelacionDefinida).where(
                RelacionDefinida.tenant_id == tenant_id,
                RelacionDefinida.activa.is_(True),
            )
        )
        .scalars()
        .all()
    )

    pasos: list[PasoBorrado] = []
    for relacion in relaciones:
        apunta_aqui = relacion.destino == objeto or objeto in (relacion.destinos or [])
        if not apunta_aqui:
            continue
        efecto = {
            "cascada": "cascada",
            "desvincular": "desvincular",
            "restringir": "impide",
        }[relacion.al_borrar]
        pasos.append(PasoBorrado(relacion=relacion.nombre, objeto=relacion.origen, efecto=efecto))

    # Lo que impide va primero: es lo que hay que resolver antes de nada, y
    # enterrarlo entre veinte cascadas hace que se lea el listado y se pase por
    # alto justo lo que bloquea.
    orden = {"impide": 0, "cascada": 1, "desvincular": 2}
    return sorted(pasos, key=lambda p: (orden[p.efecto], p.objeto))


def validar_destino(relacion: RelacionDefinida, objeto_destino: str) -> None:
    """Comprueba que el tipo de destino es uno de los admitidos.

    Solo tiene sentido en las polimórficas, y ahí es imprescindible: sin esta
    comprobación, una actividad puede acabar apuntando a un tipo que nadie
    previó, y el día que alguien recorra esas referencias se encontrará con un
    identificador que no resuelve a nada.
    """
    if relacion.tipo != "polimorfica":
        if relacion.destino and objeto_destino != relacion.destino:
            raise ErrorValidacion(
                f"La relación «{relacion.nombre}» apunta a «{relacion.destino}», "
                f"no a «{objeto_destino}»",
                error_code="metadata.destino_no_admitido",
            )
        return
    if objeto_destino not in (relacion.destinos or []):
        raise ErrorValidacion(
            f"«{objeto_destino}» no está entre los destinos admitidos de " f"«{relacion.nombre}»",
            error_code="metadata.destino_no_admitido",
            detalle={"admitidos": list(relacion.destinos or [])},
        )


def grafo(db: Session, tenant_id: UUID) -> dict[str, Any]:
    """El mapa de relaciones del tenant, para pintarlo o recorrerlo.

    Lo necesita cualquier interfaz dirigida por metadatos: sin el grafo, una
    pantalla no puede ofrecer «ver los contactos de esta cuenta» sin que alguien
    lo haya programado a mano, que es justo lo que un modelo extensible viene a
    evitar.
    """
    relaciones = (
        db.execute(
            select(RelacionDefinida)
            .where(
                RelacionDefinida.tenant_id == tenant_id,
                RelacionDefinida.activa.is_(True),
            )
            .order_by(RelacionDefinida.origen, RelacionDefinida.nombre)
        )
        .scalars()
        .all()
    )
    objetos: set[str] = set()
    aristas: list[dict[str, Any]] = []
    for r in relaciones:
        objetos.add(r.origen)
        destinos = [r.destino] if r.destino else list(r.destinos or [])
        objetos.update(str(d) for d in destinos if d)
        aristas.append(
            {
                "nombre": r.nombre,
                "etiqueta": r.etiqueta,
                "inverso": r.nombre_inverso or None,
                "origen": r.origen,
                "destinos": [str(d) for d in destinos if d],
                "tipo": r.tipo,
                "cardinalidad": r.cardinalidad,
                "al_borrar": r.al_borrar,
                "obligatoria": r.obligatoria,
                "via": r.via,
            }
        )
    return {"objetos": sorted(objetos), "relaciones": aristas}
