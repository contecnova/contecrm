"""Plantillas, preferencias y separación transaccional
(CRM-02.03.01.01, CRM-02.03.01.05, CRM-02.03.01.07).

Tres decisiones que deciden si el correo llega o acaba en la carpeta de basura:

**Una plantilla se compone de bloques reutilizables.** Con plantillas enteras
copiadas, cambiar el pie legal exige tocar cuarenta y siempre quedan seis con el
pie viejo — que es exactamente el que trae la dirección que ya no existe.

**Darse de baja no puede ser todo o nada.** Quien solo quiere dejar de recibir la
newsletter y se encuentra un botón que le saca de todo, incluidas las facturas,
marca el correo como basura. Y eso no se puede deshacer.

**Lo transaccional viaja por otro sitio que lo promocional.** No es una manía:
comparten reputación de dominio, así que una campaña con muchas quejas hunde la
entrega de las facturas. Y al revés, mezclarlos hace que darse de baja de la
newsletter parezca que apaga los avisos de servicio.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.db.base import Base, SoftDeleteMixin, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import (
    Boolean,
    DateTime,
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

# Tipos de bloque. Cerrado: el editor tiene que saber pintarlos y el compositor
# convertirlos a HTML, y un tipo libre deja las dos cosas adivinando.
TIPOS_BLOQUE = ("texto", "imagen", "boton", "separador", "columnas", "pie", "cabecera")
# Clases de correo. La distinción no es cosmética: decide por qué dominio sale.
CLASES = ("promocional", "transaccional")


class BloqueCorreo(Base, TimestampMixin, SoftDeleteMixin):
    """Un trozo reutilizable (CRM-02.03.01.01).

    Existe para que el pie legal, la cabecera y el bloque de baja estén **en un
    solo sitio**. Con plantillas enteras copiadas, cambiar el pie exige tocar
    cuarenta y siempre quedan seis con el viejo.
    """

    __tablename__ = "bloques_correo"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(80), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False, default="texto")
    contenido: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # Un bloque obligatorio se añade a toda plantilla promocional aunque quien la
    # monte se olvide. El de baja lo es por ley, y confiar en que alguien lo
    # arrastre es cómo se manda una campaña sin él.
    obligatorio_en_promocional: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (UniqueConstraint("tenant_id", "clave", name="uq_bloque_correo"),)


class PlantillaMarketing(Base, TimestampMixin, SoftDeleteMixin):
    """Una plantilla compuesta de bloques."""

    __tablename__ = "plantillas_marketing"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(80), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    asunto: Mapped[str] = mapped_column(String(300), nullable=False)
    preencabezado: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    clase: Mapped[str] = mapped_column(
        String(20), nullable=False, default="promocional", info={"opciones": CLASES}
    )
    # Referencias a bloques, en orden, con lo que cambia en cada uso.
    bloques: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # A qué categoría de preferencias pertenece. Es lo que permite darse de baja
    # de esto y no de todo.
    categoria: Mapped[str | None] = mapped_column(String(80), nullable=True)
    idioma: Mapped[str] = mapped_column(String(10), nullable=False, default="es")
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "clave", "idioma", name="uq_plantilla_marketing"),
        Index("ix_plantillas_clase", "tenant_id", "clase", "activa"),
    )


class CategoriaPreferencia(Base, TimestampMixin, SoftDeleteMixin):
    """De qué se puede dar de baja alguien (CRM-02.03.01.05)."""

    __tablename__ = "categorias_preferencia"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(80), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Una categoría obligatoria no se puede desactivar: los avisos de servicio y
    # las facturas no son marketing, y ofrecer darse de baja de ellos produce
    # clientes que no reciben su factura y culpan al proveedor.
    obligatoria: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Marcada de serie al dar de alta. Se declara porque el consentimiento por
    # defecto depende del país y del tipo de relación, y ponerlo en el código lo
    # convertiría en una decisión nuestra sobre datos ajenos.
    por_defecto: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    orden: Mapped[int] = mapped_column(String(4), nullable=False, default="50")
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (UniqueConstraint("tenant_id", "clave", name="uq_categoria_preferencia"),)


class Preferencia(Base, TimestampMixin):
    """Qué quiere recibir una persona."""

    __tablename__ = "preferencias_contacto"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    email: Mapped[str] = mapped_column(
        String(320), nullable=False, info={"sensibilidad": "personal"}
    )
    categoria: Mapped[str] = mapped_column(String(80), nullable=False)
    acepta: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Cómo y cuándo lo dijo. Es la prueba del consentimiento, y sin ella la
    # respuesta a «¿quién autorizó esto?» es «no consta».
    origen: Mapped[str] = mapped_column(String(40), nullable=False, default="centro")
    ip: Mapped[str | None] = mapped_column(
        String(64), nullable=True, info={"sensibilidad": "personal"}
    )
    cambiada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "email", "categoria", name="uq_preferencia"),
        Index("ix_preferencias_email", "tenant_id", "email"),
    )


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


# ── Composición (CRM-02.03.01.01) ─────────────────────────────────────────


def componer(
    db: Session, tenant_id: UUID, plantilla_clave: str, *, idioma: str = "es"
) -> dict[str, Any]:
    """Junta los bloques de una plantilla.

    Los bloques **obligatorios se añaden aunque la plantilla no los nombre**. El
    de baja lo es por ley, y confiar en que quien monta la plantilla lo arrastre
    es cómo se manda una campaña sin él — y eso no se arregla con una disculpa.
    """
    plantilla = db.execute(
        select(PlantillaMarketing).where(
            PlantillaMarketing.tenant_id == tenant_id,
            PlantillaMarketing.clave == plantilla_clave,
            PlantillaMarketing.idioma == idioma,
        )
    ).scalar_one_or_none()
    if plantilla is None:
        raise NoEncontrado(
            "La plantilla no existe en ese idioma", error_code="correo.plantilla_no_encontrada"
        )

    disponibles = {
        b.clave: b
        for b in db.execute(
            select(BloqueCorreo).where(
                BloqueCorreo.tenant_id == tenant_id, BloqueCorreo.activo.is_(True)
            )
        ).scalars()
    }
    usados: list[dict[str, Any]] = []
    faltan: list[str] = []
    for referencia in plantilla.bloques or []:
        clave = str(referencia.get("bloque") or "")
        bloque = disponibles.get(clave)
        if bloque is None:
            faltan.append(clave)
            continue
        usados.append(
            {
                "clave": clave,
                "tipo": bloque.tipo,
                "contenido": {**(bloque.contenido or {}), **(referencia.get("cambia") or {})},
            }
        )

    anadidos: list[str] = []
    if plantilla.clase == "promocional":
        ya = {u["clave"] for u in usados}
        for clave, bloque in sorted(disponibles.items()):
            if bloque.obligatorio_en_promocional and clave not in ya:
                usados.append(
                    {"clave": clave, "tipo": bloque.tipo, "contenido": bloque.contenido or {}}
                )
                anadidos.append(clave)

    return {
        "plantilla": plantilla.clave,
        "asunto": plantilla.asunto,
        "preencabezado": plantilla.preencabezado,
        "clase": plantilla.clase,
        "categoria": plantilla.categoria,
        "bloques": usados,
        # Los añadidos por obligación se dicen: quien previsualiza tiene que
        # entender por qué aparece un pie que él no puso.
        "anadidos_por_obligacion": anadidos,
        # Un bloque que falta NO se ignora: la plantilla saldría con un hueco y
        # nadie sabría de dónde salió.
        "bloques_que_faltan": faltan,
        "componible": not faltan,
    }


TOKEN = re.compile(r"\{\{\s*([a-z_][a-z0-9_.]*)\s*\}\}")


def tokens_de(texto: str) -> list[str]:
    return sorted(set(TOKEN.findall(texto or "")))


def comprobar_tokens(composicion: dict[str, Any], datos: dict[str, Any]) -> dict[str, Any]:
    """Qué tokens quedarían sin rellenar.

    Se comprueba **antes de mandar**. Un «Hola {{nombre}}» que sale sin sustituir
    no es un fallo técnico: es un correo que dice en voz alta que es automático, y
    lo reciben miles de personas a la vez.
    """
    texto = str(composicion.get("asunto", "")) + str(composicion.get("bloques", ""))
    faltan = [t for t in tokens_de(texto) if not _resolver(datos, t)]
    return {
        "tokens": tokens_de(texto),
        "sin_datos": faltan,
        "listo": not faltan,
        "aviso": ""
        if not faltan
        else (
            "Hay tokens sin dato. Un «Hola {{nombre}}» sin sustituir dice en voz "
            "alta que el correo es automático, y lo reciben todos a la vez."
        ),
    }


def _resolver(datos: dict[str, Any], camino: str) -> Any:
    actual: Any = datos
    for parte in camino.split("."):
        if not isinstance(actual, dict):
            return None
        actual = actual.get(parte)
    return actual


# ── Preferencias (CRM-02.03.01.05) ────────────────────────────────────────


def centro_de_preferencias(db: Session, tenant_id: UUID, email: str) -> dict[str, Any]:
    """Lo que esta persona recibe y lo que puede cambiar.

    Las categorías **obligatorias salen marcadas como tales y no como una casilla
    apagada**: enseñar una casilla que no se puede desmarcar se lee como un
    engaño, y decir «esto no se puede quitar porque es tu factura» se entiende.
    """
    categorias = (
        db.execute(
            select(CategoriaPreferencia)
            .where(
                CategoriaPreferencia.tenant_id == tenant_id,
                CategoriaPreferencia.activa.is_(True),
            )
            .order_by(CategoriaPreferencia.orden, CategoriaPreferencia.nombre)
        )
        .scalars()
        .all()
    )
    actuales = {
        p.categoria: p
        for p in db.execute(
            select(Preferencia).where(
                Preferencia.tenant_id == tenant_id, Preferencia.email == email
            )
        ).scalars()
    }
    return {
        "email": email,
        "categorias": [
            {
                "clave": c.clave,
                "nombre": c.nombre,
                "descripcion": c.descripcion,
                "obligatoria": c.obligatoria,
                "acepta": (
                    True
                    if c.obligatoria
                    else (actuales[c.clave].acepta if c.clave in actuales else c.por_defecto)
                ),
                "elegida_por_la_persona": c.clave in actuales,
            }
            for c in categorias
        ],
    }


def fijar_preferencias(
    uow: UnidadDeTrabajo,
    *,
    email: str,
    elecciones: dict[str, bool],
    origen: str = "centro",
    ip: str = "",
) -> dict[str, Any]:
    """Guarda lo que la persona ha elegido.

    Una categoría **obligatoria no se puede apagar**, y se dice cuál se ha
    ignorado en vez de fingir que se guardó: dejar creer que se apagó el aviso de
    facturación produce la queja de que «sigo recibiendo lo que quité».
    """
    tenant_id = uow.tenant_id
    categorias = {
        c.clave: c
        for c in uow.db.execute(
            select(CategoriaPreferencia).where(CategoriaPreferencia.tenant_id == tenant_id)
        ).scalars()
    }
    guardadas: list[str] = []
    ignoradas: list[str] = []
    desconocidas: list[str] = []

    for clave, acepta in elecciones.items():
        categoria = categorias.get(clave)
        if categoria is None:
            desconocidas.append(clave)
            continue
        if categoria.obligatoria and not acepta:
            ignoradas.append(clave)
            continue
        fila = uow.db.execute(
            select(Preferencia).where(
                Preferencia.tenant_id == tenant_id,
                Preferencia.email == email,
                Preferencia.categoria == clave,
            )
        ).scalar_one_or_none()
        if fila is None:
            fila = Preferencia(tenant_id=tenant_id, email=email, categoria=clave)
            uow.db.add(fila)
        fila.acepta = bool(acepta)
        fila.origen = origen
        fila.ip = ip or None
        fila.cambiada_at = _ahora()
        guardadas.append(clave)

    uow.db.flush()
    uow.emitir(
        "preferences.changed",
        subject=("preferencia", uow.tenant_id),
        data={
            "email": email,
            "guardadas": guardadas,
            "origen": origen,
        },
    )
    return {
        "guardadas": guardadas,
        # Lo que no se pudo cambiar se dice por su nombre: fingir que se guardó
        # produce la queja de «sigo recibiendo lo que quité».
        "obligatorias_ignoradas": ignoradas,
        "desconocidas": desconocidas,
    }


def puede_recibir(
    db: Session, tenant_id: UUID, email: str, categoria: str | None
) -> dict[str, Any]:
    """Si se le puede mandar esto a esta persona.

    Sin categoría declarada en la plantilla, **no se manda**. Una plantilla
    promocional sin categoría no se puede rechazar por categorías, así que darle
    paso equivaldría a un canal que nadie puede apagar.
    """
    if categoria is None:
        return {
            "permitido": False,
            "motivo": (
                "La plantilla no declara categoría de preferencias, así que nadie "
                "podría darse de baja de ella."
            ),
        }
    ficha = db.execute(
        select(CategoriaPreferencia).where(
            CategoriaPreferencia.tenant_id == tenant_id,
            CategoriaPreferencia.clave == categoria,
        )
    ).scalar_one_or_none()
    if ficha is None:
        return {"permitido": False, "motivo": f"La categoría «{categoria}» no existe."}
    if ficha.obligatoria:
        return {"permitido": True, "motivo": "Categoría obligatoria: no se puede rechazar."}

    fila = db.execute(
        select(Preferencia).where(
            Preferencia.tenant_id == tenant_id,
            Preferencia.email == email,
            Preferencia.categoria == categoria,
        )
    ).scalar_one_or_none()
    if fila is None:
        return {
            "permitido": ficha.por_defecto,
            "motivo": ("No ha elegido; se aplica el valor por defecto de la categoría."),
        }
    return {
        "permitido": fila.acepta,
        "motivo": "Lo eligió la persona" if fila.acepta else "Se dio de baja de esta categoría",
    }


# ── Separación transaccional / promocional (CRM-02.03.01.07) ──────────────


def remitente_para(clase: str, *, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Por qué dominio sale cada clase de correo.

    **No es una manía:** comparten reputación, así que una campaña con muchas
    quejas hunde la entrega de las facturas. Y al revés, mezclarlos hace que
    darse de baja de la newsletter parezca que apaga los avisos de servicio.

    Si no hay dominio separado configurado **se dice**, en vez de mandarlo todo
    por el mismo y callar: el día que la entrega se hunda, nadie sabrá por qué.
    """
    if clase not in CLASES:
        raise ErrorValidacion(
            f"Clase «{clase}» no válida.",
            error_code="correo.clase_no_valida",
            detalle={"validas": list(CLASES)},
        )
    config = config or {}
    promocional = str(config.get("dominio_promocional") or "")
    transaccional = str(config.get("dominio_transaccional") or "")
    separados = bool(promocional and transaccional and promocional != transaccional)
    dominio = transaccional if clase == "transaccional" else promocional
    return {
        "clase": clase,
        "dominio": dominio or None,
        "separados": separados,
        "aviso": ""
        if separados
        else (
            "Lo promocional y lo transaccional salen por el mismo dominio. "
            "Comparten reputación: una campaña con quejas hundirá la entrega de "
            "las facturas, y nadie sabrá por qué."
        ),
    }


def comprobar_envio(
    db: Session,
    tenant_id: UUID,
    *,
    email: str,
    plantilla_clave: str,
    idioma: str = "es",
    datos: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Todo lo que hay que mirar antes de mandar, en una llamada.

    Una sola comprobación y no cuatro repartidas: la que se olvida es siempre la
    misma —las preferencias— y el resultado es un correo a quien se dio de baja.

    **Y los tokens sin rellenar, que faltaban aquí.** `comprobar_tokens` estaba
    escrita, probada y sin que la llamara nadie, así que esta función —que se
    anuncia como «todo lo que hay que mirar»— dejaba pasar el caso más visible
    de todos: un «Hola {{nombre}}» que sale sin sustituir no es un fallo
    técnico, es un correo que dice en voz alta que es automático y lo reciben
    miles de personas a la vez.

    Sin `datos` no se comprueban: no hay con qué, y decir que faltan todos sería
    un falso rojo que acabaría con la comprobación desactivada.
    """
    composicion = componer(db, tenant_id, plantilla_clave, idioma=idioma)
    permiso = puede_recibir(db, tenant_id, email, composicion["categoria"])
    motivos: list[str] = []
    if not composicion["componible"]:
        motivos.append("Faltan bloques: " + ", ".join(composicion["bloques_que_faltan"]))
    if not permiso["permitido"]:
        motivos.append(permiso["motivo"])
    tokens = comprobar_tokens(composicion, datos) if datos is not None else None
    if tokens and not tokens["listo"]:
        motivos.append(
            "Hay tokens sin rellenar: " + ", ".join(tokens["sin_datos"]) + ". Saldrían "
            "tal cual en el correo."
        )
    return {
        "se_puede_mandar": not motivos,
        "motivos": motivos,
        "clase": composicion["clase"],
        "categoria": composicion["categoria"],
        "anadidos_por_obligacion": composicion["anadidos_por_obligacion"],
        "tokens": tokens,
    }
