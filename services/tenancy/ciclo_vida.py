"""Onboarding por industria, clonado, fusión y escisión de tenants
(CRM-00.01.03.02, .03, .06, CRM-00.01.07.13).

Las cuatro operaciones de este módulo son las que más miedo dan de un producto
multi-tenant, y todas fallan igual: **a medias y en silencio**. Un clonado que
copia nueve tablas de diez deja una demo que funciona hasta que alguien abre la
pantalla que falta; una fusión que se para a la mitad deja dos clientes viéndose
los datos.

Las decisiones:

**Se simula antes de hacer.** Las cuatro dicen primero qué van a mover y qué no
saben mover. Descubrirlo después es descubrirlo con los datos ya movidos.

**Un clon nace marcado como clon.** Si no, a las dos semanas alguien manda una
campaña de verdad desde la copia de demostración. Y sus integraciones nacen
apagadas por lo mismo: un sandbox que sincroniza con el ERP de producción no es
un sandbox.

**Fusionar no es copiar: es decidir qué gana.** Dos clientes que se fusionan
traen dos catálogos de productos, dos pipelines y el mismo cliente dado de alta
dos veces. Aquí se prepara y se cuenta lo que choca; resolver cada choque es de
quien conoce el negocio.

**Escindir exige decir qué se lleva cada uno**, y lo que no se asigna se queda
donde estaba. Repartir «lo que no se dijo» por la mitad es cómo se pierden
carteras enteras.

**Y una baja en cascada dice cuál ha quedado abierta.** Cerrar en tres
herramientas y dar el certificado sin comprobar la tercera es firmar que se
destruyó algo que sigue ahí.
"""

from __future__ import annotations

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

# Para qué se clona. El uso decide qué se copia: una demo no necesita el
# histórico de tres años y un preproducción no puede vivir sin él.
USOS_CLON = ("demo", "sandbox", "preproduccion", "formacion")

# Qué se puede llevar un clon. Lista cerrada porque cada grupo tiene su riesgo:
# copiar los usuarios de verdad a una demo manda correos a gente real.
BLOQUES = (
    "configuracion",  # metamodelo, pipelines, plantillas, reglas
    "catalogo",  # productos, precios, territorios
    "datos",  # cuentas, contactos, oportunidades
    "actividad",  # actividades, casos, historial
    "usuarios",  # personas y sus permisos
    "integraciones",  # conexiones y credenciales
)

# Lo que NUNCA se copia, con el motivo. No es una lista de exclusiones técnicas:
# es la diferencia entre un sandbox y un incidente.
NUNCA_SE_COPIA = {
    "credenciales": "Copiarlas da acceso al sistema real desde una copia de pruebas",
    "claves_de_cifrado": "La clave del tenant es suya: compartirla une dos tenants para siempre",
    "consentimientos": "Un consentimiento se dio a una empresa concreta y no viaja con una copia",
    "supresiones": "Se copian SIEMPRE al revés: la baja tiene que respetarse también en el clon",
    "auditoria": "La cadena de auditoría es de quien la generó y su integridad no sobrevive a una copia",
}

ESTADOS = ("simulada", "en_curso", "terminada", "fallida", "revertida")


class OperacionTenant(Base, TimestampMixin):
    """Un clonado, una fusión o una escisión, con lo que movió y lo que no."""

    __tablename__ = "operaciones_tenant"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)
    origen_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    destino_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    uso: Mapped[str] = mapped_column(
        String(20), nullable=False, default="", info={"opciones": USOS_CLON}
    )
    bloques: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="simulada")
    # Qué se movería y qué no se sabe mover. Va aquí y no en un log porque es lo
    # que alguien tiene que leer ANTES de aprobar.
    plan: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    conflictos: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    resultado: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    motivo_fin: Mapped[str] = mapped_column(Text, nullable=False, default="")
    terminada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_operaciones_tenant", "tenant_id", "tipo", "estado"),)


class PerfilIndustria(Base, TimestampMixin):
    """Una preconfiguración por sector (CRM-00.01.03.02)."""

    __tablename__ = "perfiles_industria"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    clave: Mapped[str] = mapped_column(String(60), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Lo que trae: objetos del metamodelo, pipelines, flujos, plantillas. Es
    # datos y no código porque una industria nueva no puede ser un despliegue.
    contenido: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # Qué NO trae, dicho por su nombre. Un perfil que promete «todo lo de tu
    # sector» y deja fuera la mitad hace que el cliente descubra los huecos
    # cuando ya ha metido datos.
    no_incluye: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("clave", "version", name="uq_perfil_industria"),
        Index("ix_perfiles_industria", "clave", "activo"),
    )


class AplicacionPerfil(Base):
    """Qué perfil se le aplicó a un tenant y qué quedó fuera."""

    __tablename__ = "aplicaciones_perfil"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    perfil: Mapped[str] = mapped_column(String(60), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    aplicado: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    saltado: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("ix_aplicaciones_perfil", "tenant_id", "perfil"),)


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


# ── Onboarding por industria (CRM-00.01.03.02) ────────────────────────────


def guardar_perfil(
    db: Session,
    *,
    clave: str,
    nombre: str,
    contenido: dict[str, Any],
    descripcion: str = "",
    no_incluye: list[str] | None = None,
) -> PerfilIndustria:
    """Guarda una versión nueva de un perfil de industria.

    Es **datos y no código**: una industria nueva no puede ser un despliegue del
    producto, porque entonces el comercial que la vende depende de una versión.
    """
    if not contenido:
        raise ErrorValidacion("Un perfil vacío no preconfigura nada", error_code="perfil.vacio")
    anteriores = (
        db.execute(select(PerfilIndustria).where(PerfilIndustria.clave == clave)).scalars().all()
    )
    for fila in anteriores:
        fila.activo = False
    nuevo = PerfilIndustria(
        clave=clave,
        nombre=nombre,
        descripcion=descripcion,
        contenido=contenido,
        no_incluye=list(no_incluye or []),
        version=max((f.version for f in anteriores), default=0) + 1,
        activo=True,
    )
    db.add(nuevo)
    db.flush()
    return nuevo


def simular_perfil(db: Session, tenant_id: UUID, *, clave: str) -> dict[str, Any]:
    """Qué traería este perfil y qué chocaría con lo que ya hay.

    Aplicar un perfil sobre un tenant que ya trabaja es el caso que rompe: el
    cliente lleva tres semanas y alguien decide «ponerle la plantilla del
    sector». Lo que ya existe **no se pisa**, y se dice cuánto se va a saltar.
    """
    perfil = _perfil(db, clave)
    contenido = perfil.contenido or {}
    resumen = {k: len(v) if isinstance(v, (list, dict)) else 1 for k, v in contenido.items()}
    return {
        "perfil": perfil.clave,
        "version": perfil.version,
        "traeria": resumen,
        # Lo que el perfil NO trae, dicho antes de empezar y no cuando el cliente
        # busca la pantalla que no está.
        "no_incluye": perfil.no_incluye,
        "que_pasa_con_lo_que_ya_hay": (
            "Nada se pisa: lo que ya exista con la misma clave se salta y se "
            "cuenta. Pisar la configuración de un tenant que ya trabaja es la "
            "forma más rápida de perder tres semanas de trabajo suyo."
        ),
    }


def aplicar_perfil(
    uow: UnidadDeTrabajo,
    *,
    tenant_id: UUID,
    clave: str,
    existentes: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Aplica el perfil **sin pisar lo que ya hay** (CRM-00.01.03.02).

    `existentes` lo aporta quien llama —cada servicio sabe lo suyo— y es lo que
    permite saltarse lo que ya está. Sin ese dato, aplicar un perfil sobre un
    tenant en marcha duplicaría pipelines y plantillas.
    """
    perfil = _perfil(uow.db, clave)
    ya = {k: set(v) for k, v in (existentes or {}).items()}

    aplicado: dict[str, list[str]] = {}
    saltado: list[dict[str, str]] = []
    for bloque, elementos in (perfil.contenido or {}).items():
        claves = list(elementos) if isinstance(elementos, (list, dict)) else []
        for elemento in claves:
            nombre = str(elemento if isinstance(elemento, str) else elemento.get("clave", ""))
            if not nombre:
                continue
            if nombre in ya.get(bloque, set()):
                saltado.append(
                    {"bloque": bloque, "clave": nombre, "porque": "ya existe en el tenant"}
                )
                continue
            aplicado.setdefault(bloque, []).append(nombre)

    fila = AplicacionPerfil(
        tenant_id=tenant_id,
        perfil=perfil.clave,
        version=perfil.version,
        aplicado=aplicado,
        saltado=saltado,
    )
    uow.db.add(fila)
    uow.db.flush()
    registrar(
        uow.db,
        accion="tenant.perfil_aplicado",
        objeto="tenant",
        objeto_id=tenant_id,
        datos={"perfil": clave, "version": perfil.version, "saltados": len(saltado)},
        tenant_id=tenant_id,
    )
    return {
        "perfil": perfil.clave,
        "version": perfil.version,
        "aplicado": aplicado,
        "saltado": saltado,
        "no_incluye": perfil.no_incluye,
        "que_falta_por_configurar": (
            "Lo que el perfil no trae sigue sin configurar: no se ha creado nada "
            "por defecto para rellenar ese hueco, porque un valor inventado es "
            "peor que un hueco visible."
        ),
    }


def _perfil(db: Session, clave: str) -> PerfilIndustria:
    fila = (
        db.execute(
            select(PerfilIndustria)
            .where(PerfilIndustria.clave == clave, PerfilIndustria.activo.is_(True))
            .order_by(PerfilIndustria.version.desc())
        )
        .scalars()
        .first()
    )
    if fila is None:
        raise NoEncontrado(
            f"No hay perfil de industria activo con la clave «{clave}»",
            error_code="perfil.no_encontrado",
        )
    return fila


# ── Clonado (CRM-00.01.03.03) ─────────────────────────────────────────────


def simular_clonado(
    uow: UnidadDeTrabajo,
    *,
    origen_id: UUID,
    uso: str,
    bloques: list[str],
    recuentos: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Qué se llevaría el clon, y qué no se lleva nunca.

    Se simula primero porque el clonado falla a medias y en silencio: copia nueve
    tablas de diez y deja una demo que funciona hasta que alguien abre la pantalla
    que falta.
    """
    if uso not in USOS_CLON:
        raise ErrorValidacion(
            f"Uso de clon desconocido: «{uso}»",
            error_code="clon.uso_invalido",
            detalle={"admitidos": list(USOS_CLON)},
        )
    desconocidos = sorted(set(bloques) - set(BLOQUES))
    if desconocidos:
        raise ErrorValidacion(
            f"Bloques desconocidos: {desconocidos}",
            error_code="clon.bloque_invalido",
            detalle={"admitidos": list(BLOQUES)},
        )
    if not bloques:
        raise ErrorValidacion("Un clon sin bloques no copia nada", error_code="clon.sin_bloques")

    avisos: list[str] = []
    if "usuarios" in bloques and uso in ("demo", "formacion"):
        avisos.append(
            "Copiar los usuarios a una demo manda correos a gente real en cuanto "
            "alguien pruebe una campaña. Normalmente se quiere «configuracion» sin "
            "«usuarios»."
        )
    if "integraciones" in bloques:
        avisos.append(
            "Las integraciones se copian APAGADAS: un sandbox que sincroniza con "
            "el ERP de producción no es un sandbox."
        )

    fila = OperacionTenant(
        tenant_id=origen_id,
        tipo="clonado",
        origen_id=origen_id,
        uso=uso,
        bloques=sorted(set(bloques)),
        estado="simulada",
        plan={"recuentos": dict(recuentos or {}), "avisos": avisos},
    )
    uow.db.add(fila)
    uow.db.flush()
    return {
        "operacion_id": str(fila.id),
        "uso": uso,
        "bloques": fila.bloques,
        "recuentos": dict(recuentos or {}),
        # Lo que nunca viaja, con el motivo de cada uno: no es una lista de
        # exclusiones técnicas, es la diferencia entre un sandbox y un incidente.
        "nunca_se_copia": NUNCA_SE_COPIA,
        "avisos": avisos,
    }


def ejecutar_clonado(
    uow: UnidadDeTrabajo,
    *,
    operacion_id: UUID,
    destino_id: UUID,
    copiado: dict[str, int],
) -> dict[str, Any]:
    """Cierra un clonado y deja el destino **marcado como copia**.

    Si no se marca, a las dos semanas alguien manda una campaña de verdad desde
    la copia de demostración — y eso no se arregla explicándolo después.
    """
    fila = _operacion(uow.db, operacion_id, "clonado")
    if fila.estado != "simulada":
        raise Conflicto(f"La operación está en «{fila.estado}»", error_code="clon.estado_invalido")
    esperado = (fila.plan or {}).get("recuentos") or {}
    faltan = [
        {"bloque": b, "esperado": n, "copiado": int(copiado.get(b, 0))}
        for b, n in esperado.items()
        if int(copiado.get(b, 0)) != int(n)
    ]

    fila.destino_id = destino_id
    fila.resultado = {"copiado": dict(copiado), "diferencias": faltan}
    fila.estado = "terminada" if not faltan else "fallida"
    fila.terminada_at = _ahora()
    fila.motivo_fin = (
        "" if not faltan else "El clon no tiene lo mismo que el origen en todos los bloques"
    )
    uow.db.flush()
    registrar(
        uow.db,
        accion="tenant.clonado",
        objeto="tenant",
        objeto_id=destino_id,
        datos={"origen": str(fila.origen_id), "uso": fila.uso, "diferencias": len(faltan)},
        tenant_id=fila.tenant_id,
    )
    return {
        "operacion_id": str(fila.id),
        "estado": fila.estado,
        "diferencias": faltan,
        "completo": not faltan,
        # El destino nace marcado, y esto es lo que hay que aplicarle: se
        # devuelve para que quien cree el tenant no dependa de acordarse.
        "marcar_el_destino_como": {
            "es_copia": True,
            "origen": str(fila.origen_id),
            "uso": fila.uso,
            "integraciones": "apagadas",
        },
        "porque": (
            "Un clon sin marcar acaba mandando una campaña de verdad, y un sandbox "
            "que sincroniza con producción no es un sandbox."
        ),
    }


# ── Fusión y escisión (CRM-00.01.03.06) ───────────────────────────────────


def simular_fusion(
    uow: UnidadDeTrabajo,
    *,
    absorbido_id: UUID,
    superviviente_id: UUID,
    choques: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Qué chocaría al fusionar dos tenants.

    Fusionar **no es copiar: es decidir qué gana**. Dos empresas que se fusionan
    traen dos catálogos de productos, dos pipelines y el mismo cliente dado de
    alta dos veces. Aquí se cuenta lo que choca; resolver cada choque es de quien
    conoce el negocio, y automatizarlo produce un catálogo que no es de ninguno
    de los dos.
    """
    if absorbido_id == superviviente_id:
        raise ErrorValidacion(
            "No se puede fusionar un tenant consigo mismo", error_code="fusion.mismo_tenant"
        )
    detalle = [
        {"bloque": bloque, "claves": sorted(set(claves)), "cuantos": len(set(claves))}
        for bloque, claves in sorted((choques or {}).items())
        if claves
    ]
    fila = OperacionTenant(
        tenant_id=superviviente_id,
        tipo="fusion",
        origen_id=absorbido_id,
        destino_id=superviviente_id,
        estado="simulada",
        conflictos=detalle,
        plan={"choques": sum(c["cuantos"] for c in detalle)},
    )
    uow.db.add(fila)
    uow.db.flush()
    return {
        "operacion_id": str(fila.id),
        "choques": detalle,
        "total_choques": sum(c["cuantos"] for c in detalle),
        "se_puede_ejecutar": not detalle,
        "que_significa": (
            "No hay choques: se puede fusionar."
            if not detalle
            else "Hay choques sin resolver. Resolverlos automáticamente produciría "
            "un catálogo que no es de ninguna de las dos empresas, y nadie sabría "
            "cuál era el suyo."
        ),
        "lo_que_no_se_fusiona": {
            "auditoria": "Cada cadena es de quien la generó; unirlas rompe su integridad",
            "consentimientos": "Se dieron a una empresa concreta y no viajan con una fusión",
            "supresiones": "Se unen las DOS listas: una baja sigue siendo una baja",
        },
    }


def simular_escision(
    uow: UnidadDeTrabajo,
    *,
    origen_id: UUID,
    reparto: dict[str, str],
    inventario: list[str],
) -> dict[str, Any]:
    """Qué se lleva cada uno al partir un tenant en dos.

    **Lo que no se asigna se queda donde estaba.** Repartir «lo que no se dijo»
    por la mitad, o dárselo al nuevo, es cómo se pierden carteras enteras: nadie
    revisa una lista de tres mil cuentas antes de aprobar.
    """
    sin_asignar = [c for c in inventario if c not in reparto]
    por_destino: dict[str, int] = {}
    for destino in reparto.values():
        por_destino[destino] = por_destino.get(destino, 0) + 1

    fila = OperacionTenant(
        tenant_id=origen_id,
        tipo="escision",
        origen_id=origen_id,
        estado="simulada",
        plan={"reparto": por_destino, "sin_asignar": len(sin_asignar)},
    )
    uow.db.add(fila)
    uow.db.flush()
    return {
        "operacion_id": str(fila.id),
        "por_destino": por_destino,
        "sin_asignar": sin_asignar[:100],
        "cuantos_sin_asignar": len(sin_asignar),
        "se_quedan_en_el_origen": True,
        "porque": (
            "Lo que no se asigna se queda donde estaba. Repartirlo por la mitad o "
            "dárselo al nuevo es cómo se pierden carteras enteras: nadie revisa "
            "tres mil cuentas antes de aprobar."
        ),
    }


def _operacion(db: Session, operacion_id: UUID, tipo: str) -> OperacionTenant:
    fila = db.get(OperacionTenant, operacion_id)
    if fila is None or fila.tipo != tipo:
        raise NoEncontrado(
            f"No hay ninguna operación de tipo «{tipo}» con ese identificador",
            error_code="tenant.operacion_no_encontrada",
        )
    return fila


# ── Baja en cascada con certificado único (CRM-00.01.07.13) ───────────────


def certificado_de_baja(
    db: Session,
    tenant_id: UUID,
    *,
    cierres: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Un solo certificado para las tres herramientas de la suite.

    `cierres` trae lo que ha contestado cada una. La regla es la que hace que el
    certificado valga algo: **o se cierra en todas o se dice cuál ha quedado
    abierta**. Firmar que se destruyó todo sin comprobar la tercera es firmar
    sobre algo que sigue ahí, y eso es peor que no dar certificado.
    """
    esperadas = sorted(cierres)
    cerradas = [h for h, d in cierres.items() if d.get("cerrado")]
    abiertas = [
        {
            "herramienta": h,
            "porque": str(d.get("porque") or "no ha contestado"),
        }
        for h, d in sorted(cierres.items())
        if not d.get("cerrado")
    ]
    completo = bool(esperadas) and not abiertas
    return {
        "tenant_id": str(tenant_id),
        "generado_at": _ahora().isoformat(),
        "herramientas": esperadas,
        "cerradas": sorted(cerradas),
        "abiertas": abiertas,
        "completo": completo,
        "certificado": (
            "Los datos del tenant se han destruido en todas las herramientas de la " "suite."
            if completo
            else "NO se puede certificar la destrucción: hay herramientas donde el "
            "dato sigue. Lo que se firma aquí es lo que consta, y consta que no."
        ),
        "que_hacer": (
            ""
            if completo
            else "Cerrar donde falta y volver a pedir el certificado. Firmarlo "
            "ahora sería declarar destruido algo que sigue ahí."
        ),
    }
