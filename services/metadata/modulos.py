"""Módulos verticales: caracterizar el producto para un sector
(CRM-00.04.04.01 a .05, .07 a .11).

La extensión sin código (CRM-00.04.03) resuelve «falta un campo». Esto resuelve lo
otro: que el producto llegue **ya caracterizado**. Un operador logístico no
necesita un campo más — necesita envíos, trazabilidad con el transportista,
incidencias con su tipología y que su cliente vea el seguimiento sin llamar.

Un módulo es un **paquete declarativo**: objetos, campos, taxonomías, estados,
flujos, permisos, pantallas y conectores, todo en un manifiesto versionado. Que el
producto sea headless lo hace posible —las pantallas salen de la superficie
declarada, sin escribir front— pero no lo hace gratis.

**Lo que decide si esto funciona a los dos años es la actualización.** El cliente
habrá tocado lo que el módulo trajo: habrá renombrado una etiqueta, añadido un
campo a un objeto del módulo, cambiado un umbral. Una actualización que pise esos
cambios se deja de instalar, y entonces cada cliente se queda congelado en su
versión — que es exactamente cómo mueren los productos con verticales. De ahí las
cuatro decisiones del módulo:

**Espacio de nombres.** Todo lo que trae un módulo va prefijado. Sin prefijo, dos
módulos que llamen «envio» a cosas distintas se pisan, y el segundo que se instale
rompe al primero sin que nadie entienda por qué.

**El manifiesto declara qué es suyo y qué es editable.** Un campo `fijo` lo
gobierna el módulo y se actualiza; uno `editable` lo puede tocar el cliente y no
se toca nunca más. La diferencia se declara **por adelantado**, no se descubre en
el conflicto.

**Simular por defecto.** Instalar un módulo es un cambio de modelo de datos en
producción. Aplicar es una decisión aparte, y el error más caro que puede cometer
quien lo maneja es pulsar el botón creyendo que aún estaba mirando.

**Desinstalar dice qué pasa con los datos.** Un «desinstalado correctamente» que
deja doscientos mil registros huérfanos es peor que no poder desinstalar.
"""

from __future__ import annotations

import hashlib
import json
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
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

logger = get_logger(__name__)

FORMATO_MANIFIESTO = 1

# Versión del núcleo que se ofrece a los módulos. Se sube cuando cambia algo que
# un manifiesto puede usar; un módulo que pida más se rechaza al instalar en vez
# de fallar a mitad.
VERSION_NUCLEO = 1

# Secciones que puede traer un manifiesto. Cerrada a propósito: una sección
# desconocida se rechaza en vez de ignorarse, porque ignorarla instalaría un
# módulo a medias que parece completo — y el cliente descubriría lo que falta el
# día que lo necesite.
SECCIONES = (
    "objetos",
    "taxonomias",
    "estados",
    "flujos",
    "permisos",
    "plantillas",
    "pantallas",
    "conectores",
    "datos_semilla",
)

# Gobierno de cada elemento. `fijo` lo manda el módulo y se actualiza; `editable`
# lo puede tocar el cliente y no se vuelve a tocar; `semilla` se crea una vez y
# después es del cliente por completo.
GOBIERNOS = ("fijo", "editable", "semilla")

_NOMBRE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")


class ModuloInstalado(Base, TimestampMixin):
    """Un módulo vertical instalado en un tenant."""

    __tablename__ = "modulos_instalados"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(60), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[str] = mapped_column(String(30), nullable=False)
    autor: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # Huella del manifiesto instalado. Es lo que permite decir si lo que hay
    # puesto es exactamente lo que se publicó, o si alguien lo tocó por debajo.
    huella: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    # El manifiesto completo, guardado. Se guarda entero y no solo la referencia
    # porque desinstalar y actualizar necesitan saber **qué trajo esta versión**,
    # y el catálogo remoto puede haberla retirado.
    manifiesto: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="instalado")
    instalado_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    instalado_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (UniqueConstraint("tenant_id", "clave", name="uq_modulo_instalado"),)


class ElementoModulo(Base):
    """Cada cosa que un módulo puso, con quién la gobierna.

    Es la tabla que hace posible la actualización sin pisar al cliente: sin ella,
    actualizar sería reinstalar, y reinstalar borra lo que el cliente ajustó.
    """

    __tablename__ = "elementos_modulo"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    modulo: Mapped[str] = mapped_column(String(60), nullable=False)
    seccion: Mapped[str] = mapped_column(String(30), nullable=False)
    # Identificador dentro del módulo, ya prefijado.
    clave: Mapped[str] = mapped_column(String(160), nullable=False)
    gobierno: Mapped[str] = mapped_column(
        String(20), nullable=False, default="fijo", info={"opciones": GOBIERNOS}
    )
    # Lo que el módulo puso la última vez. Comparando esto con lo que hay ahora se
    # sabe si el cliente lo tocó — que es la única forma de no pisarlo.
    definicion: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    version_modulo: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    # Si el cliente lo modificó después de instalarlo. Se marca al detectarlo, no
    # se adivina en cada actualización.
    modificado_por_cliente: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Veces que se ha usado. Alimenta la telemetría (CRM-00.04.04.10): un módulo
    # con quince objetos de los que se usan dos es un módulo mal recortado.
    usos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ultimo_uso_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "modulo", "seccion", "clave", name="uq_elemento_modulo"),
        Index("ix_elementos_modulo", "tenant_id", "modulo", "seccion"),
    )


class ModuloPublicado(Base, TimestampMixin):
    """Un módulo disponible para instalar (CRM-00.04.04.08).

    El catálogo es **de la instalación**, no de cada tenant: quién puede publicar
    un módulo es una decisión de quien opera la plataforma, y dejar que cada
    tenant publique el suyo convertiría el catálogo en una vía para ejecutar
    configuración ajena en casa de otro.
    """

    __tablename__ = "modulos_publicados"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    clave: Mapped[str] = mapped_column(String(60), nullable=False)
    version: Mapped[str] = mapped_column(String(30), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    autor: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    sector: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    manifiesto: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    huella: Mapped[str] = mapped_column(String(64), nullable=False)
    # Firma de quien lo publica. Sin firma se puede instalar, pero se avisa: un
    # módulo sin firmar puede haber sido modificado por cualquiera entre quien lo
    # escribió y quien lo instala.
    firma: Mapped[str | None] = mapped_column(Text, nullable=True)
    revisado_por: Mapped[str | None] = mapped_column(String(200), nullable=True)
    revisado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retirado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    motivo_retirada: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (UniqueConstraint("clave", "version", name="uq_modulo_publicado"),)


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _huella(manifiesto: dict[str, Any]) -> str:
    copia = {k: v for k, v in manifiesto.items() if k != "firma"}
    return hashlib.sha256(json.dumps(copia, sort_keys=True, default=str).encode()).hexdigest()


# ── Espacio de nombres (CRM-00.04.04.03) ──────────────────────────────────


def prefijar(modulo: str, nombre: str) -> str:
    """El nombre real de un elemento del módulo.

    Todo lo que trae un módulo va prefijado con su clave. Sin prefijo, dos
    módulos que llamen «envio» a cosas distintas se pisan, y el segundo que se
    instale rompe al primero sin que nadie entienda por qué — y desinstalar
    cualquiera de los dos se lleva por delante lo del otro.
    """
    if nombre.startswith(f"{modulo}__"):
        return nombre
    return f"{modulo}__{nombre}"


def desprefijar(modulo: str, nombre: str) -> str:
    return nombre[len(modulo) + 2 :] if nombre.startswith(f"{modulo}__") else nombre


def _comparar_versiones(a: str, b: str) -> int:
    """Compara versiones tipo `1.4.2`. Devuelve -1, 0 o 1.

    Se comparan por número y no como texto: como texto, «1.10» es menor que
    «1.9», y una actualización se saltaría sin avisar.
    """

    def _partes(v: str) -> list[int]:
        return [int(p) for p in re.findall(r"\d+", v)] or [0]

    pa, pb = _partes(a), _partes(b)
    largo = max(len(pa), len(pb))
    pa += [0] * (largo - len(pa))
    pb += [0] * (largo - len(pb))
    return (pa > pb) - (pa < pb)


# ── Validación del manifiesto (CRM-00.04.04.01) ───────────────────────────


def validar_manifiesto(manifiesto: dict[str, Any]) -> list[str]:
    """Comprueba el manifiesto y devuelve los avisos que no lo invalidan.

    Lo que está mal **lanza**; lo que es dudoso se devuelve como aviso. La
    diferencia importa: rechazar por algo dudoso deja módulos correctos sin
    instalar, y aceptar en silencio algo dudoso deja al cliente con un módulo que
    no hace lo que promete.
    """
    if int(manifiesto.get("formato") or 0) != FORMATO_MANIFIESTO:
        raise ErrorValidacion(
            f"Formato de manifiesto no soportado: {manifiesto.get('formato')}",
            error_code="metadata.manifiesto_no_soportado",
            detalle={"soportado": FORMATO_MANIFIESTO},
        )
    clave = str(manifiesto.get("clave") or "")
    if not _NOMBRE.match(clave):
        raise ErrorValidacion(
            "La clave del módulo tiene que ser un identificador en minúsculas: "
            "va prefijando todo lo que trae y acaba en nombres de tabla y de API.",
            error_code="metadata.clave_modulo_invalida",
            detalle={"recibido": clave},
        )
    if not manifiesto.get("version"):
        raise ErrorValidacion(
            "Un módulo sin versión no se puede actualizar ni revertir.",
            error_code="metadata.modulo_sin_version",
        )

    desconocidas = sorted(set(manifiesto.get("contenido") or {}) - set(SECCIONES))
    if desconocidas:
        raise ErrorValidacion(
            f"Secciones desconocidas en el manifiesto: {', '.join(desconocidas)}. "
            "Ignorarlas instalaría un módulo a medias que parece completo.",
            error_code="metadata.seccion_desconocida",
            detalle={"conocidas": list(SECCIONES)},
        )

    avisos: list[str] = []
    contenido = manifiesto.get("contenido") or {}
    for seccion, elementos in contenido.items():
        for elemento in elementos or []:
            if not isinstance(elemento, dict) or not elemento.get("clave"):
                raise ErrorValidacion(
                    f"Un elemento de «{seccion}» no tiene clave.",
                    error_code="metadata.elemento_sin_clave",
                )
            gobierno = str(elemento.get("gobierno") or "fijo")
            if gobierno not in GOBIERNOS:
                raise ErrorValidacion(
                    f"Gobierno «{gobierno}» no válido en {seccion}.{elemento['clave']}.",
                    error_code="metadata.gobierno_no_valido",
                    detalle={"validos": list(GOBIERNOS)},
                )

    if not manifiesto.get("descripcion"):
        avisos.append(
            "El módulo no trae descripción: quien lo instale no sabrá qué hace "
            "hasta después de instalarlo."
        )
    if not contenido.get("pantallas"):
        avisos.append(
            "El módulo no declara pantallas: sus objetos existirán en la API pero "
            "no aparecerán en el front oficial."
        )
    if not manifiesto.get("firma"):
        avisos.append(
            "El módulo no está firmado: no se puede comprobar que sea el que " "escribió su autor."
        )
    return avisos


def _requisitos(manifiesto: dict[str, Any]) -> dict[str, Any]:
    return manifiesto.get("requiere") or {}


def comprobar_dependencias(db: Session, tenant_id: UUID, manifiesto: dict[str, Any]) -> list[str]:
    """Qué falta para poder instalar (CRM-00.04.04.05).

    Se comprueba **antes** y se devuelve la lista entera, no el primer fallo:
    instalar, fallar, corregir y repetir cinco veces es exactamente la
    experiencia que hace que nadie quiera instalar módulos.
    """
    faltan: list[str] = []
    requisitos = _requisitos(manifiesto)

    nucleo = int(requisitos.get("nucleo") or 0)
    if nucleo > VERSION_NUCLEO:
        faltan.append(
            f"Este módulo necesita la versión {nucleo} del núcleo y aquí hay la "
            f"{VERSION_NUCLEO}. Actualiza el producto antes de instalarlo."
        )

    instalados = {
        m.clave: m.version
        for m in db.execute(
            select(ModuloInstalado).where(
                ModuloInstalado.tenant_id == tenant_id,
                ModuloInstalado.estado == "instalado",
            )
        ).scalars()
    }
    for clave, minima in (requisitos.get("modulos") or {}).items():
        actual = instalados.get(str(clave))
        if actual is None:
            faltan.append(f"Falta el módulo «{clave}» (versión {minima} o superior).")
        elif _comparar_versiones(actual, str(minima)) < 0:
            faltan.append(
                f"El módulo «{clave}» está en la versión {actual} y hace falta al "
                f"menos la {minima}."
            )
    return faltan


# ── Instalar (CRM-00.04.04.02) ────────────────────────────────────────────


def _elementos_de(manifiesto: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    salida: list[tuple[str, dict[str, Any]]] = []
    for seccion, elementos in (manifiesto.get("contenido") or {}).items():
        for elemento in elementos or []:
            salida.append((seccion, dict(elemento)))
    return salida


def instalar(
    uow: UnidadDeTrabajo,
    manifiesto: dict[str, Any],
    *,
    aplicar: bool = False,
    por: UUID | None = None,
) -> dict[str, Any]:
    """Instala un módulo en el tenant.

    `aplicar=False` es el valor por defecto **a propósito**: instalar un módulo es
    un cambio de modelo de datos en producción, y el error más caro que puede
    cometer quien lo maneja es pulsar el botón creyendo que aún estaba mirando.
    """
    avisos = validar_manifiesto(manifiesto)
    tenant_id = uow.tenant_id
    clave = str(manifiesto["clave"])
    version = str(manifiesto["version"])

    faltan = comprobar_dependencias(uow.db, tenant_id, manifiesto)
    ya = uow.db.execute(
        select(ModuloInstalado).where(
            ModuloInstalado.tenant_id == tenant_id, ModuloInstalado.clave == clave
        )
    ).scalar_one_or_none()
    if ya is not None and ya.estado == "instalado":
        raise Conflicto(
            f"El módulo «{clave}» ya está instalado en la versión {ya.version}. "
            "Para pasar a otra versión, actualiza.",
            error_code="metadata.modulo_ya_instalado",
            detalle={"version_actual": ya.version},
        )

    elementos = _elementos_de(manifiesto)
    plan = [
        {
            "seccion": seccion,
            "clave": prefijar(clave, str(elemento["clave"])),
            "gobierno": str(elemento.get("gobierno") or "fijo"),
        }
        for seccion, elemento in elementos
    ]

    if not aplicar or faltan:
        return {
            "simulado": True,
            "modulo": clave,
            "version": version,
            "crearia": plan,
            "dependencias_que_faltan": faltan,
            "avisos": avisos,
            "se_puede_instalar": not faltan,
        }

    fila = ya or ModuloInstalado(tenant_id=tenant_id, clave=clave)
    if ya is None:
        uow.db.add(fila)
    fila.nombre = str(manifiesto.get("nombre") or clave)
    fila.version = version
    fila.autor = str(manifiesto.get("autor") or "")
    fila.manifiesto = manifiesto
    fila.huella = _huella(manifiesto)
    fila.estado = "instalado"
    fila.instalado_por = por
    fila.instalado_at = _ahora()
    uow.db.flush()

    for seccion, elemento in elementos:
        uow.db.add(
            ElementoModulo(
                tenant_id=tenant_id,
                modulo=clave,
                seccion=seccion,
                clave=prefijar(clave, str(elemento["clave"])),
                gobierno=str(elemento.get("gobierno") or "fijo"),
                definicion=elemento,
                version_modulo=version,
            )
        )
    uow.db.flush()

    registrar(
        uow.db,
        accion="metadata.modulo_instalado",
        objeto="modulo",
        objeto_id=fila.id,
        datos={"clave": clave, "version": version, "elementos": len(elementos)},
        tenant_id=tenant_id,
    )
    uow.emitir(
        "module.installed",
        subject=("modulo", fila.id),
        data={
            "modulo": clave,
            "version": version,
            "elementos": len(elementos),
            # Los conectores viajan **dentro del evento** (CRM-00.04.04.06).
            # Quien tiene que materializarlos es `integration`, y no puede leer
            # este esquema: o van aquí o alguien los vuelve a teclear en la otra
            # pantalla, que es exactamente el trabajo manual que el módulo
            # existe para quitar. Son declaración, no datos del tenant: caben.
            "conectores": [dict(e) for seccion, e in elementos if seccion == "conectores"],
        },
    )
    return {
        "simulado": False,
        "modulo": clave,
        "version": version,
        "creados": len(elementos),
        "avisos": avisos,
        "siguiente_paso": (
            "Publica el esquema de los objetos que trae el módulo para que llegue "
            "a los servicios (CRM-00.04.03.02)."
        ),
    }


# ── Actualizar sin pisar al cliente (CRM-00.04.04.04) ─────────────────────


def marcar_modificado(
    db: Session, tenant_id: UUID, *, modulo: str, seccion: str, clave: str
) -> ElementoModulo | None:
    """Anota que el cliente tocó un elemento del módulo.

    Lo llama quien edita. Se **marca al editar y no se adivina al actualizar**:
    adivinarlo obligaría a comparar estructuras enteras en cada actualización y a
    acertar con qué cuenta como cambio, y el día que se falle se pisará el trabajo
    de alguien.
    """
    fila = db.execute(
        select(ElementoModulo).where(
            ElementoModulo.tenant_id == tenant_id,
            ElementoModulo.modulo == modulo,
            ElementoModulo.seccion == seccion,
            ElementoModulo.clave == clave,
        )
    ).scalar_one_or_none()
    if fila is not None:
        fila.modificado_por_cliente = True
    return fila


def actualizar(
    uow: UnidadDeTrabajo,
    manifiesto: dict[str, Any],
    *,
    aplicar: bool = False,
    forzar_fijos: bool = False,
    por: UUID | None = None,
) -> dict[str, Any]:
    """Pasa un módulo a una versión nueva respetando lo que el cliente ajustó.

    Las tres reglas, y las tres importan por separado:

    * Lo **fijo** lo gobierna el módulo: se actualiza siempre. Si el cliente lo
      tocó, se avisa — y solo se pisa con `forzar_fijos`, porque pisarlo en
      silencio es cómo se pierde la confianza en las actualizaciones.
    * Lo **editable** que el cliente tocó **no se toca nunca**. Es suyo desde que
      lo tocó, y ese es el trato.
    * Lo **semilla** se crea una vez y ya está: actualizarlo sería reescribir
      datos que el cliente lleva un año usando.

    Lo que el módulo ya no trae **no se borra aquí**: se marca como huérfano y se
    dice. Borrarlo con la actualización se llevaría por delante los registros que
    cuelgan de él sin que nadie lo hubiera decidido.
    """
    avisos = validar_manifiesto(manifiesto)
    tenant_id = uow.tenant_id
    clave = str(manifiesto["clave"])
    version = str(manifiesto["version"])

    actual = uow.db.execute(
        select(ModuloInstalado).where(
            ModuloInstalado.tenant_id == tenant_id, ModuloInstalado.clave == clave
        )
    ).scalar_one_or_none()
    if actual is None or actual.estado != "instalado":
        raise NoEncontrado(
            f"El módulo «{clave}» no está instalado", error_code="metadata.modulo_no_instalado"
        )
    if _comparar_versiones(version, actual.version) <= 0:
        raise Conflicto(
            f"La versión {version} no es posterior a la instalada ({actual.version}). "
            "Para volver atrás, instala la versión anterior explícitamente.",
            error_code="metadata.version_no_posterior",
        )

    faltan = comprobar_dependencias(uow.db, tenant_id, manifiesto)
    puestos = {
        (e.seccion, e.clave): e
        for e in uow.db.execute(
            select(ElementoModulo).where(
                ElementoModulo.tenant_id == tenant_id, ElementoModulo.modulo == clave
            )
        ).scalars()
    }
    entrantes = {
        (seccion, prefijar(clave, str(elemento["clave"]))): elemento
        for seccion, elemento in _elementos_de(manifiesto)
    }

    nuevos, actualizados, respetados, conflictos, huerfanos = [], [], [], [], []
    for llave, elemento in entrantes.items():
        seccion, nombre = llave
        puesto = puestos.get(llave)
        gobierno = str(elemento.get("gobierno") or "fijo")
        if puesto is None:
            nuevos.append(nombre)
            continue
        if gobierno == "semilla":
            respetados.append({"clave": nombre, "motivo": "semilla: solo se crea una vez"})
            continue
        if puesto.modificado_por_cliente:
            if gobierno == "editable":
                respetados.append(
                    {"clave": nombre, "motivo": "editable y modificado por el cliente"}
                )
                continue
            conflictos.append(
                {
                    "clave": nombre,
                    "motivo": (
                        "el módulo lo gobierna pero el cliente lo modificó; "
                        "actualizarlo pisará ese cambio"
                    ),
                }
            )
            if not forzar_fijos:
                continue
        actualizados.append(nombre)

    for llave, puesto in puestos.items():
        if llave not in entrantes:
            huerfanos.append(
                {
                    "clave": puesto.clave,
                    "seccion": puesto.seccion,
                    "motivo": "la versión nueva ya no lo trae",
                }
            )

    if not aplicar or faltan:
        return {
            "simulado": True,
            "modulo": clave,
            "desde": actual.version,
            "hasta": version,
            "nuevos": nuevos,
            "actualizados": actualizados,
            "respetados": respetados,
            "conflictos": conflictos,
            "huerfanos": huerfanos,
            "dependencias_que_faltan": faltan,
            "avisos": avisos,
            "se_puede_actualizar": not faltan,
        }

    for llave, elemento in entrantes.items():
        seccion, nombre = llave
        puesto = puestos.get(llave)
        gobierno = str(elemento.get("gobierno") or "fijo")
        if puesto is None:
            uow.db.add(
                ElementoModulo(
                    tenant_id=tenant_id,
                    modulo=clave,
                    seccion=seccion,
                    clave=nombre,
                    gobierno=gobierno,
                    definicion=elemento,
                    version_modulo=version,
                )
            )
            continue
        if gobierno == "semilla":
            continue
        if puesto.modificado_por_cliente and (gobierno == "editable" or not forzar_fijos):
            continue
        puesto.definicion = elemento
        puesto.gobierno = gobierno
        puesto.version_modulo = version
        puesto.modificado_por_cliente = False

    anterior = actual.version
    actual.version = version
    actual.manifiesto = manifiesto
    actual.huella = _huella(manifiesto)
    uow.db.flush()

    registrar(
        uow.db,
        accion="metadata.modulo_actualizado",
        objeto="modulo",
        objeto_id=actual.id,
        datos={
            "clave": clave,
            "desde": anterior,
            "hasta": version,
            "respetados": len(respetados),
            "conflictos_forzados": len(conflictos) if forzar_fijos else 0,
            "huerfanos": len(huerfanos),
        },
        tenant_id=tenant_id,
    )
    # Se emite también al actualizar. Sin este evento, una versión nueva que
    # corrige el mapa de estados de un transportista se quedaría en el
    # manifiesto: el módulo diría una cosa y el seguimiento seguiría traduciendo
    # con la tabla vieja, que es peor que no haberla corregido.
    uow.emitir(
        "module.updated",
        subject=("modulo", actual.id),
        data={
            "modulo": clave,
            "version": version,
            "desde": anterior,
            "conectores": [
                dict(e) for (seccion, _), e in entrantes.items() if seccion == "conectores"
            ],
        },
    )
    return {
        "simulado": False,
        "modulo": clave,
        "desde": anterior,
        "hasta": version,
        "nuevos": len(nuevos),
        "actualizados": len(actualizados),
        "respetados": respetados,
        "huerfanos": huerfanos,
        "avisos": avisos,
    }


# ── Desinstalar (CRM-00.04.04.09) ─────────────────────────────────────────


def desinstalar(
    uow: UnidadDeTrabajo,
    clave: str,
    *,
    aplicar: bool = False,
    borrar_datos: bool = False,
    contar_registros: Any = None,
    por: UUID | None = None,
) -> dict[str, Any]:
    """Quita un módulo diciendo qué pasa con los datos.

    Un «desinstalado correctamente» que deja doscientos mil registros huérfanos es
    peor que no poder desinstalar: el cliente cree que se fue y los datos siguen
    ahí, sin pantalla que los enseñe y sin nadie que los borre cuando toque.

    Por eso **la configuración se quita y los datos no, salvo que se pida**. Y se
    dice cuántos hay: `contar_registros` lo aporta quien sabe contarlos —el
    servicio dueño de cada objeto—, porque `metadata` no guarda ningún registro de
    negocio. Si no se puede contar, se dice que no se ha podido; no se supone que
    son cero.
    """
    tenant_id = uow.tenant_id
    fila = uow.db.execute(
        select(ModuloInstalado).where(
            ModuloInstalado.tenant_id == tenant_id, ModuloInstalado.clave == clave
        )
    ).scalar_one_or_none()
    if fila is None or fila.estado != "instalado":
        raise NoEncontrado(
            f"El módulo «{clave}» no está instalado", error_code="metadata.modulo_no_instalado"
        )

    dependen = [
        m.clave
        for m in uow.db.execute(
            select(ModuloInstalado).where(
                ModuloInstalado.tenant_id == tenant_id, ModuloInstalado.estado == "instalado"
            )
        ).scalars()
        if clave in ((m.manifiesto or {}).get("requiere") or {}).get("modulos", {})
    ]

    elementos = list(
        uow.db.execute(
            select(ElementoModulo).where(
                ElementoModulo.tenant_id == tenant_id, ElementoModulo.modulo == clave
            )
        ).scalars()
    )
    objetos = [e.clave for e in elementos if e.seccion == "objetos"]

    registros: dict[str, Any] = {}
    no_contados: list[str] = []
    for objeto in objetos:
        if contar_registros is None:
            no_contados.append(objeto)
            continue
        try:
            registros[objeto] = int(contar_registros(objeto))
        except Exception:  # noqa: BLE001 — no poder contar se dice, no se supone
            no_contados.append(objeto)

    modificados = [e.clave for e in elementos if e.modificado_por_cliente]

    if not aplicar or dependen:
        return {
            "simulado": True,
            "modulo": clave,
            "quitaria": len(elementos),
            "objetos": objetos,
            "registros_por_objeto": registros,
            "no_se_han_podido_contar": no_contados,
            "modificados_por_el_cliente": modificados,
            "modulos_que_dependen": dependen,
            "se_puede_desinstalar": not dependen,
            "que_pasa_con_los_datos": (
                "Se borrarán los registros de los objetos del módulo."
                if borrar_datos
                else "Los registros se CONSERVAN y quedarán sin pantalla que los "
                "enseñe. Pídelo explícitamente si quieres borrarlos."
            ),
        }

    for elemento in elementos:
        uow.db.delete(elemento)
    fila.estado = "desinstalado"
    uow.db.flush()

    registrar(
        uow.db,
        accion="metadata.modulo_desinstalado",
        objeto="modulo",
        objeto_id=fila.id,
        datos={
            "clave": clave,
            "version": fila.version,
            "elementos": len(elementos),
            "datos_borrados": borrar_datos,
            "registros": registros,
        },
        tenant_id=tenant_id,
    )
    uow.emitir(
        "module.uninstalled",
        subject=("modulo", fila.id),
        data={"modulo": clave, "datos_borrados": borrar_datos, "objetos": objetos},
    )
    return {
        "simulado": False,
        "modulo": clave,
        "quitados": len(elementos),
        "datos_borrados": borrar_datos,
        "registros_conservados": registros if not borrar_datos else {},
    }


# ── Catálogo y firma (CRM-00.04.04.08) ────────────────────────────────────


def publicar(
    db: Session,
    manifiesto: dict[str, Any],
    *,
    sector: str = "",
    firma: str = "",
    revisado_por: str = "",
) -> ModuloPublicado:
    """Da de alta una versión de módulo en el catálogo de la instalación."""
    validar_manifiesto(manifiesto)
    clave, version = str(manifiesto["clave"]), str(manifiesto["version"])
    if db.execute(
        select(ModuloPublicado.id).where(
            ModuloPublicado.clave == clave, ModuloPublicado.version == version
        )
    ).first():
        raise Conflicto(
            f"«{clave}» {version} ya está publicado. Publica una versión nueva: "
            "reescribir una publicada dejaría a quien ya la instaló con un "
            "contenido distinto del que consta.",
            error_code="metadata.version_ya_publicada",
        )
    fila = ModuloPublicado(
        clave=clave,
        version=version,
        nombre=str(manifiesto.get("nombre") or clave),
        descripcion=str(manifiesto.get("descripcion") or ""),
        autor=str(manifiesto.get("autor") or ""),
        sector=sector,
        manifiesto=manifiesto,
        huella=_huella(manifiesto),
        firma=firma or None,
        revisado_por=revisado_por or None,
        revisado_at=_ahora() if revisado_por else None,
    )
    db.add(fila)
    db.flush()
    return fila


def catalogo(
    db: Session, *, sector: str = "", incluir_retirados: bool = False
) -> list[dict[str, Any]]:
    """Los módulos disponibles, con lo que hace falta para decidir.

    Se dice si está **firmado y revisado**, porque de eso depende si se instala a
    ciegas o no: un módulo sin firma puede haber sido modificado por cualquiera
    entre quien lo escribió y quien lo instala.
    """
    consulta = select(ModuloPublicado)
    if not incluir_retirados:
        consulta = consulta.where(ModuloPublicado.retirado.is_(False))
    if sector:
        consulta = consulta.where(ModuloPublicado.sector == sector)
    filas = (
        db.execute(consulta.order_by(ModuloPublicado.clave, ModuloPublicado.version.desc()))
        .scalars()
        .all()
    )
    return [
        {
            "clave": m.clave,
            "version": m.version,
            "nombre": m.nombre,
            "descripcion": m.descripcion,
            "autor": m.autor,
            "sector": m.sector,
            "firmado": bool(m.firma),
            "revisado": bool(m.revisado_por),
            "retirado": m.retirado,
            "requiere": (m.manifiesto or {}).get("requiere") or {},
            "aviso": (
                ""
                if m.firma
                else "Sin firma: no se puede comprobar que sea el que escribió su autor."
            ),
        }
        for m in filas
    ]


def comprobar_integridad(db: Session, tenant_id: UUID, clave: str) -> dict[str, Any]:
    """¿Lo instalado es lo que se publicó?

    Compara la huella de lo instalado con la del catálogo. Sirve para lo que
    nadie mira hasta que algo falla: saber si alguien tocó el manifiesto por
    debajo entre la publicación y la instalación.
    """
    instalado = db.execute(
        select(ModuloInstalado).where(
            ModuloInstalado.tenant_id == tenant_id, ModuloInstalado.clave == clave
        )
    ).scalar_one_or_none()
    if instalado is None:
        raise NoEncontrado("El módulo no está instalado", error_code="metadata.modulo_no_instalado")
    publicado = db.execute(
        select(ModuloPublicado).where(
            ModuloPublicado.clave == clave, ModuloPublicado.version == instalado.version
        )
    ).scalar_one_or_none()
    if publicado is None:
        return {
            "modulo": clave,
            "medible": False,
            "motivo": (
                f"La versión {instalado.version} ya no está en el catálogo: no se "
                "puede comparar. Instalado desde un fichero o retirada después."
            ),
        }
    return {
        "modulo": clave,
        "medible": True,
        "coincide": instalado.huella == publicado.huella,
        "huella_instalada": instalado.huella,
        "huella_publicada": publicado.huella,
        "firmado": bool(publicado.firma),
    }


# ── Pantallas desde la superficie (CRM-00.04.04.07) ───────────────────────


def superficie_de_modulos(db: Session, tenant_id: UUID) -> dict[str, Any]:
    """Las pantallas que aportan los módulos instalados.

    Que el producto sea headless es lo que hace esto posible: el front oficial
    pinta lo que la superficie declara, así que un módulo añade pantallas
    **declarándolas**, sin escribir front.

    Se devuelven **solo las de los módulos instalados y activos**. Servir las de
    uno desinstalado dejaría un menú con entradas que llevan a un 404, que es
    peor que no tener la entrada.
    """
    instalados = {
        m.clave: m
        for m in db.execute(
            select(ModuloInstalado).where(
                ModuloInstalado.tenant_id == tenant_id, ModuloInstalado.estado == "instalado"
            )
        ).scalars()
    }
    if not instalados:
        return {"modulos": [], "pantallas": []}

    elementos = (
        db.execute(
            select(ElementoModulo).where(
                ElementoModulo.tenant_id == tenant_id,
                ElementoModulo.modulo.in_(list(instalados)),
                ElementoModulo.seccion == "pantallas",
            )
        )
        .scalars()
        .all()
    )
    return {
        "modulos": [
            {"clave": m.clave, "nombre": m.nombre, "version": m.version}
            for m in instalados.values()
        ],
        "pantallas": [
            {
                "modulo": e.modulo,
                "clave": e.clave,
                **{k: v for k, v in (e.definicion or {}).items() if k != "clave"},
            }
            for e in sorted(elementos, key=lambda e: (e.modulo, e.clave))
        ],
    }


# ── Telemetría (CRM-00.04.04.10) ──────────────────────────────────────────


def anotar_uso(db: Session, tenant_id: UUID, *, modulo: str, seccion: str, clave: str) -> None:
    """Cuenta un uso de un elemento del módulo. No falla nunca."""
    try:
        fila = db.execute(
            select(ElementoModulo).where(
                ElementoModulo.tenant_id == tenant_id,
                ElementoModulo.modulo == modulo,
                ElementoModulo.seccion == seccion,
                ElementoModulo.clave == clave,
            )
        ).scalar_one_or_none()
        if fila is not None:
            fila.usos += 1
            fila.ultimo_uso_at = _ahora()
    except Exception:  # noqa: BLE001 — una estadística no puede tumbar una petición
        logger.warning("metadata.uso_modulo_no_anotado", modulo=modulo, clave=clave)


def telemetria(db: Session, tenant_id: UUID, clave: str) -> dict[str, Any]:
    """Qué del módulo se usa de verdad.

    Es lo que dice si un módulo está bien recortado: uno con quince objetos de los
    que se usan dos no está completo, está inflado — y cada objeto que sobra es
    una entrada de menú que el usuario tiene que aprender a ignorar.
    """
    instalado = db.execute(
        select(ModuloInstalado).where(
            ModuloInstalado.tenant_id == tenant_id, ModuloInstalado.clave == clave
        )
    ).scalar_one_or_none()
    if instalado is None:
        raise NoEncontrado("El módulo no está instalado", error_code="metadata.modulo_no_instalado")

    elementos = list(
        db.execute(
            select(ElementoModulo).where(
                ElementoModulo.tenant_id == tenant_id, ElementoModulo.modulo == clave
            )
        ).scalars()
    )
    sin_usar = [e for e in elementos if e.usos == 0]
    dias = (
        _ahora()
        - (
            instalado.instalado_at
            if instalado.instalado_at.tzinfo
            else instalado.instalado_at.replace(tzinfo=timezone.utc)
        )
    ).days
    return {
        "modulo": clave,
        "version": instalado.version,
        "instalado_hace_dias": dias,
        "elementos": len(elementos),
        "usados": len(elementos) - len(sin_usar),
        "sin_usar": [{"seccion": e.seccion, "clave": e.clave} for e in sin_usar],
        "modificados_por_el_cliente": [
            {"seccion": e.seccion, "clave": e.clave} for e in elementos if e.modificado_por_cliente
        ],
        "mas_usados": [
            {"clave": e.clave, "usos": e.usos}
            for e in sorted(elementos, key=lambda e: -e.usos)[:10]
            if e.usos
        ],
        # Se dice cuándo el dato todavía no significa nada: un módulo instalado
        # ayer con todo sin usar no está inflado, está recién puesto, y tratarlo
        # igual llevaría a recortar lo que aún nadie ha tenido tiempo de abrir.
        "concluyente": dias >= 30,
        "aviso": (
            ""
            if dias >= 30
            else f"Lleva {dias} días instalado: todavía es pronto para concluir " "qué sobra."
        ),
    }


def instalados(db: Session, tenant_id: UUID) -> list[dict[str, Any]]:
    filas = (
        db.execute(
            select(ModuloInstalado)
            .where(ModuloInstalado.tenant_id == tenant_id)
            .order_by(ModuloInstalado.clave)
        )
        .scalars()
        .all()
    )
    return [
        {
            "clave": m.clave,
            "nombre": m.nombre,
            "version": m.version,
            "autor": m.autor,
            "estado": m.estado,
            "instalado_at": m.instalado_at.isoformat() if m.instalado_at else None,
        }
        for m in filas
    ]
