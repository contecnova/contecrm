"""Configuración como código: empaquetar, promocionar, detectar drift y volver
atrás (CRM-07.02.01.03, .04, .06, .07).

Un CRM configurable acaba siempre igual: alguien toca producción un viernes
porque «es un cambio pequeño», y a los tres meses nadie sabe qué hay configurado
ni por qué. El entorno de pruebas dice una cosa y producción otra, y la diferencia
no está escrita en ninguna parte.

Lo que arregla eso no es prohibir tocar producción —se va a tocar igual— sino
**verlo**: que un cambio hecho fuera del camino aparezca en una lista al día
siguiente, con su autor y su hora.

Las decisiones:

**El paquete lleva de dónde sale y contra qué se probó.** Un artefacto sin origen
es un artefacto que nadie se atreve a promocionar, y el que no se atreve lo aplica
a mano — que es volver al principio.

**Promocionar comprueba antes de aplicar.** Lo que en pruebas era un campo nuevo
puede ser en producción un campo que ya existe con otro tipo. Aplicar y descubrirlo
a la mitad deja el entorno peor que antes.

**El drift se mide contra el paquete desplegado, no contra el entorno anterior.**
Comparar dos entornos dice en qué se diferencian; comparar contra lo desplegado
dice **qué tocó alguien a mano**, que es la pregunta.

**Y volver atrás es aplicar el paquete anterior, no deshacer cambios.** Deshacer
uno a uno falla en cuanto hay dependencias entre ellos; reaplicar el estado
conocido funciona siempre — y por eso los paquetes se guardan enteros.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.audit.chain import registrar
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
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

logger = get_logger(__name__)

# Los entornos por los que pasa un cambio. Lista cerrada y **ordenada**: promover
# de desarrollo a producción saltándose pruebas es exactamente lo que este
# módulo existe para impedir, y con texto libre no se puede impedir nada.
ENTORNOS = ("desarrollo", "pruebas", "preproduccion", "produccion")
ORDEN = {e: i for i, e in enumerate(ENTORNOS)}

# Qué puede llevar un paquete. Cerrada porque cada tipo tiene su forma de
# aplicarse y de compararse: un campo se compara por tipo y obligatoriedad, una
# automatización por sus acciones.
CONTENIDOS = (
    "objetos",
    "campos",
    "vistas",
    "pipelines",
    "automatizaciones",
    "plantillas",
    "reglas_comparticion",
    "ajustes",
)


class PaqueteConfiguracion(Base, TimestampMixin):
    """Un conjunto de cambios de configuración, con su origen y su huella."""

    __tablename__ = "paquetes_configuracion"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # De dónde sale. Un artefacto sin origen es uno que nadie se atreve a
    # promocionar, y el que no se atreve lo aplica a mano.
    origen_entorno: Mapped[str] = mapped_column(
        String(20), nullable=False, default="desarrollo", info={"opciones": ENTORNOS}
    )
    # La referencia de control de versiones, cuando la configuración vive en Git
    # (CRM-07.02.01.04). Vacío es legítimo —hay tenants que configuran desde la
    # consola— y por eso no se exige; lo que no se admite es inventársela.
    referencia_git: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    contenido: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # Huella del contenido: es lo que permite decir «lo que hay desplegado es
    # exactamente este paquete» sin guardar dos copias.
    huella: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    notas: Mapped[str] = mapped_column(Text, nullable=False, default="")
    creado_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "nombre", "version", name="uq_paquete_version"),
        Index("ix_paquetes", "tenant_id", "nombre"),
    )


class DespliegueConfiguracion(Base):
    """Qué paquete está aplicado en qué entorno, y desde cuándo."""

    __tablename__ = "despliegues_configuracion"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    entorno: Mapped[str] = mapped_column(String(20), nullable=False, info={"opciones": ENTORNOS})
    paquete_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    huella: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    vigente: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # El que estaba antes. Volver atrás es reaplicar este, no deshacer cambios
    # uno a uno — deshacer falla en cuanto hay dependencias entre ellos.
    anterior_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    desplegado_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    desplegado_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    motivo: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (Index("ix_despliegues", "tenant_id", "entorno", "vigente"),)


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def huella_de(contenido: dict[str, Any]) -> str:
    """SHA-256 del contenido, con las claves ordenadas.

    Ordenadas porque si no, el mismo paquete daría huellas distintas según cómo
    se serializara — y entonces el drift saltaría cada día sin que nadie hubiera
    tocado nada, que es la forma más rápida de que se deje de mirar.
    """
    serializado = json.dumps(contenido, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(serializado.encode()).hexdigest()


def empaquetar(
    uow: UnidadDeTrabajo,
    *,
    nombre: str,
    contenido: dict[str, Any],
    origen_entorno: str = "desarrollo",
    referencia_git: str = "",
    notas: str = "",
    por: UUID | None = None,
) -> PaqueteConfiguracion:
    """Congela un conjunto de cambios de configuración (CRM-07.02.01.03).

    Cada empaquetado es una **versión nueva**. Sobrescribir la anterior dejaría
    sin sitio al que está desplegado en producción, y volver atrás exigiría
    reconstruirlo de memoria.
    """
    if origen_entorno not in ENTORNOS:
        raise ErrorValidacion(
            f"Entorno desconocido: «{origen_entorno}»",
            error_code="entornos.entorno_invalido",
            detalle={"admitidos": list(ENTORNOS)},
        )
    desconocidos = sorted(set(contenido) - set(CONTENIDOS))
    if desconocidos:
        raise ErrorValidacion(
            f"El paquete lleva cosas que no se saben aplicar: {desconocidos}. "
            "Aceptarlas dejaría un paquete que se despliega a medias y nadie sabe "
            "qué parte quedó fuera.",
            error_code="entornos.contenido_desconocido",
            detalle={"admitidos": list(CONTENIDOS)},
        )
    if not contenido:
        raise ErrorValidacion(
            "Un paquete vacío no lleva nada que promocionar",
            error_code="entornos.paquete_vacio",
        )

    anteriores = (
        uow.db.execute(
            select(PaqueteConfiguracion).where(
                PaqueteConfiguracion.tenant_id == uow.tenant_id,
                PaqueteConfiguracion.nombre == nombre,
            )
        )
        .scalars()
        .all()
    )
    fila = PaqueteConfiguracion(
        tenant_id=uow.tenant_id,
        nombre=nombre,
        version=max((p.version for p in anteriores), default=0) + 1,
        origen_entorno=origen_entorno,
        referencia_git=referencia_git,
        contenido=contenido,
        huella=huella_de(contenido),
        notas=notas,
        creado_por=por,
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila


def simular_promocion(
    db: Session,
    tenant_id: UUID,
    *,
    paquete_id: UUID,
    hacia: str,
    estado_actual: dict[str, Any],
) -> dict[str, Any]:
    """Qué pasaría al aplicar este paquete, **sin aplicarlo** (CRM-07.02.01.03).

    Lo que en pruebas era un campo nuevo puede ser en producción un campo que ya
    existe con otro tipo. Aplicar y descubrirlo a la mitad deja el entorno peor
    que antes: con la mitad del paquete dentro y sin forma de saber cuál.

    `estado_actual` lo aporta quien sabe —cada servicio conoce lo suyo— porque
    este módulo no lee el metamodelo de los demás.
    """
    paquete = _paquete(db, tenant_id, paquete_id)
    if hacia not in ENTORNOS:
        raise ErrorValidacion(
            f"Entorno desconocido: «{hacia}»", error_code="entornos.entorno_invalido"
        )
    if ORDEN[hacia] < ORDEN[paquete.origen_entorno]:
        # Promover hacia atrás no es un error: se hace para reproducir un
        # problema de producción en pruebas. Pero se dice, porque el caso normal
        # es que alguien se haya equivocado de entorno.
        logger.info(
            "entornos.promocion_hacia_atras",
            desde=paquete.origen_entorno,
            hacia=hacia,
        )

    nuevos: list[str] = []
    cambian: list[dict[str, Any]] = []
    chocan: list[dict[str, Any]] = []

    for tipo, elementos in (paquete.contenido or {}).items():
        existentes = {
            str(e.get("clave")): e for e in (estado_actual.get(tipo) or []) if isinstance(e, dict)
        }
        for elemento in elementos or []:
            if not isinstance(elemento, dict):
                continue
            clave = str(elemento.get("clave") or "")
            if not clave:
                continue
            actual = existentes.get(clave)
            if actual is None:
                nuevos.append(f"{tipo}.{clave}")
                continue
            diferencias = sorted(
                campo
                for campo, valor in elemento.items()
                if campo != "clave" and actual.get(campo) != valor
            )
            if not diferencias:
                continue
            # Un cambio de tipo no es un cambio más: puede perder datos, y eso no
            # se puede aplicar sin que alguien lo mire.
            if "tipo" in diferencias:
                chocan.append(
                    {
                        "elemento": f"{tipo}.{clave}",
                        "porque": (
                            f"Ya existe con tipo «{actual.get('tipo')}» y el paquete lo "
                            f"quiere «{elemento.get('tipo')}»: cambiar el tipo de un "
                            "campo con datos dentro puede perderlos."
                        ),
                    }
                )
                continue
            cambian.append({"elemento": f"{tipo}.{clave}", "campos": diferencias})

    return {
        "paquete": paquete.nombre,
        "version": paquete.version,
        "hacia": hacia,
        "nuevos": sorted(nuevos),
        "cambian": cambian,
        # Lo que no se puede aplicar sin que una persona decida.
        "chocan": chocan,
        "se_puede_aplicar": not chocan,
        "que_significa": (
            f"Se aplicarían {len(nuevos)} elementos nuevos y {len(cambian)} cambios."
            if not chocan
            else "Hay choques que no se pueden resolver solos. Aplicar ahora dejaría "
            "el entorno con medio paquete dentro y sin forma de saber cuál."
        ),
    }


def desplegar(
    uow: UnidadDeTrabajo,
    *,
    paquete_id: UUID,
    entorno: str,
    motivo: str = "",
    por: UUID | None = None,
) -> dict[str, Any]:
    """Marca un paquete como el que está aplicado en un entorno.

    Aplicar los cambios es de cada servicio; lo que se guarda aquí es **cuál
    está puesto**, que es lo que permite medir el drift después y volver atrás
    sin reconstruir nada de memoria.
    """
    paquete = _paquete(uow.db, uow.tenant_id, paquete_id)
    if entorno not in ENTORNOS:
        raise ErrorValidacion(
            f"Entorno desconocido: «{entorno}»", error_code="entornos.entorno_invalido"
        )

    vigente = _vigente(uow.db, uow.tenant_id, entorno)
    if vigente is not None:
        vigente.vigente = False

    fila = DespliegueConfiguracion(
        tenant_id=uow.tenant_id,
        entorno=entorno,
        paquete_id=paquete.id,
        huella=paquete.huella,
        anterior_id=vigente.paquete_id if vigente is not None else None,
        desplegado_por=por,
        motivo=motivo,
    )
    uow.db.add(fila)
    uow.db.flush()
    registrar(
        uow.db,
        accion="configuracion.desplegada",
        objeto="paquete_configuracion",
        objeto_id=paquete.id,
        datos={"entorno": entorno, "version": paquete.version},
        motivo=motivo or None,
        tenant_id=uow.tenant_id,
    )
    return {
        "entorno": entorno,
        "paquete": paquete.nombre,
        "version": paquete.version,
        "se_puede_volver_atras": fila.anterior_id is not None,
        "porque": (
            "Queda guardado cuál está puesto: es lo que permite medir después qué se "
            "tocó a mano y volver al anterior sin reconstruirlo de memoria."
        ),
    }


def medir_drift(
    db: Session,
    tenant_id: UUID,
    *,
    entorno: str,
    estado_actual: dict[str, Any],
) -> dict[str, Any]:
    """Qué se ha tocado fuera del pipeline (CRM-07.02.01.06).

    Se compara contra **el paquete desplegado**, no contra otro entorno. Comparar
    dos entornos dice en qué se diferencian —que puede ser legítimo, porque uno
    va por delante—; comparar contra lo desplegado dice **qué tocó alguien a
    mano**, que es la pregunta que importa.

    Y no se juzga: tocar producción un viernes a veces es lo correcto. Lo que no
    puede pasar es que no conste.
    """
    vigente = _vigente(db, tenant_id, entorno)
    if vigente is None:
        return {
            "entorno": entorno,
            "medible": False,
            "porque": (
                "No consta ningún paquete desplegado en este entorno: no hay contra "
                "qué comparar. Eso no significa que no se haya tocado — significa que "
                "no se sabe."
            ),
        }

    paquete = db.get(PaqueteConfiguracion, vigente.paquete_id)
    esperado = (paquete.contenido if paquete else {}) or {}
    fuera: list[dict[str, Any]] = []
    faltan: list[str] = []

    for tipo in CONTENIDOS:
        declarados = {
            str(e.get("clave")): e for e in (esperado.get(tipo) or []) if isinstance(e, dict)
        }
        actuales = {
            str(e.get("clave")): e for e in (estado_actual.get(tipo) or []) if isinstance(e, dict)
        }
        for clave, actual in actuales.items():
            declarado = declarados.get(clave)
            if declarado is None:
                fuera.append(
                    {"elemento": f"{tipo}.{clave}", "que_paso": "existe y no está en el paquete"}
                )
                continue
            diferencias = sorted(
                campo
                for campo, valor in actual.items()
                if campo != "clave" and declarado.get(campo) != valor
            )
            if diferencias:
                fuera.append(
                    {
                        "elemento": f"{tipo}.{clave}",
                        "que_paso": "cambiado a mano",
                        "campos": diferencias,
                    }
                )
        for clave in declarados:
            if clave not in actuales:
                faltan.append(f"{tipo}.{clave}")

    return {
        "entorno": entorno,
        "paquete": paquete.nombre if paquete else "",
        "version": paquete.version if paquete else 0,
        "medible": True,
        "tocado_a_mano": fuera,
        # Lo que el paquete traía y ya no está: alguien lo borró, y eso es drift
        # igual aunque no lo parezca.
        "desaparecido": sorted(faltan),
        "limpio": not fuera and not faltan,
        "que_significa": (
            "Lo que hay es exactamente lo que se desplegó."
            if not fuera and not faltan
            else "Hay configuración tocada fuera del pipeline. No es necesariamente "
            "un error —a veces tocar producción es lo correcto— pero tiene que "
            "constar, y el siguiente despliegue la pisará sin avisar."
        ),
    }


def volver_atras(
    uow: UnidadDeTrabajo, *, entorno: str, motivo: str, por: UUID | None = None
) -> dict[str, Any]:
    """Reaplica el paquete anterior (CRM-07.02.01.07).

    **Reaplicar y no deshacer.** Deshacer cambio a cambio falla en cuanto hay
    dependencias entre ellos —un campo que se creó y una vista que lo usa— y deja
    el entorno en un estado que no ha existido nunca. Volver al paquete anterior
    devuelve un estado que sí existió y que además estaba probado.
    """
    if not motivo.strip():
        raise ErrorValidacion(
            "Volver atrás exige decir por qué: es lo que evita que el siguiente "
            "despliegue repita el mismo fallo.",
            error_code="entornos.reversion_sin_motivo",
        )
    vigente = _vigente(uow.db, uow.tenant_id, entorno)
    if vigente is None or vigente.anterior_id is None:
        raise Conflicto(
            "No hay despliegue anterior al que volver en este entorno.",
            error_code="entornos.sin_anterior",
        )
    return {
        **desplegar(
            uow,
            paquete_id=vigente.anterior_id,
            entorno=entorno,
            motivo=f"Vuelta atrás: {motivo}",
            por=por,
        ),
        "es_vuelta_atras": True,
        "porque": (
            "Se reaplica el paquete anterior entero. Deshacer cambio a cambio "
            "dejaría el entorno en un estado que no ha existido nunca."
        ),
    }


def _paquete(db: Session, tenant_id: UUID, paquete_id: UUID) -> PaqueteConfiguracion:
    fila = db.get(PaqueteConfiguracion, paquete_id)
    if fila is None or fila.tenant_id != tenant_id:
        raise NoEncontrado("Ese paquete no existe", error_code="entornos.paquete_no_existe")
    return fila


def _vigente(db: Session, tenant_id: UUID, entorno: str) -> DespliegueConfiguracion | None:
    return (
        db.execute(
            select(DespliegueConfiguracion)
            .where(
                DespliegueConfiguracion.tenant_id == tenant_id,
                DespliegueConfiguracion.entorno == entorno,
                DespliegueConfiguracion.vigente.is_(True),
            )
            .order_by(DespliegueConfiguracion.desplegado_at.desc())
        )
        .scalars()
        .first()
    )
