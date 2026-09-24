"""Conectores como manifiestos, y marketplace instalable por tenant
(CRM-00.03.04.01, CRM-00.03.04.10, CRM-07.02.01.09).

«Conectores nativos para ERP, facturación, firma, telefonía y mensajería» suele
significar un módulo de Python por cada casa: uno para SAP, otro para Holded, otro
para Odoo. Eso es lo que hace que la lista de integraciones envejezca — cada
proveedor cambia su API y hay que desplegar para seguirle.

Aquí un conector **es un manifiesto**: un documento que declara qué operaciones
tiene, qué parámetros pide, qué credenciales necesita y cómo mapea sus campos. El
motor es el mismo de siempre. Añadir SAP no es escribir código: es publicar un
manifiesto y probarlo.

De ahí las decisiones:

**El manifiesto se valida al publicarlo, no al ejecutarlo.** Un mapeo con un campo
mal escrito falla dentro de un proceso nocturno tres semanas después, y el error
que aparece no se parece a la causa.

**Se versiona, y lo instalado no cambia solo.** Un tenant que tiene instalada la
versión 3 sigue con la 3 aunque se publique la 4: una actualización automática
cambiaría el comportamiento de una integración en producción sin que nadie lo
decida. Actualizar es un acto, y dice qué cambia.

**Lo que pide un manifiesto se enseña antes de instalar.** Credenciales, permisos
y a qué dominios va a llamar. Instalar algo que resulta que manda datos a un sitio
que nadie esperaba se descubre con el tráfico, y para entonces ya ha salido.

**El catálogo es del proveedor del CRM; lo instalado es del tenant.** Un manifiesto
publicado no hace nada hasta que alguien lo instala y le pone credenciales. Y
desinstalar deja los datos ya traídos: borrarlos convertiría una prueba de una
integración en una pérdida de información.
"""

from __future__ import annotations

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
    DateTime,
    ForeignKey,
    Index,
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

# Categorías del catálogo. Sirven para buscar, no para decidir nada: el
# comportamiento sale siempre del manifiesto.
CATEGORIAS = (
    "erp",
    "facturacion",
    "firma",
    "telefonia",
    "mensajeria",
    "logistica",
    "marketing",
    "productividad",
    "otros",
)

# Estados de un manifiesto en el catálogo.
#
#   borrador   se está preparando; no se puede instalar
#   publicado  instalable
#   retirado   no se instala más; lo ya instalado sigue funcionando
ESTADOS = ("borrador", "publicado", "retirado")

# Estados de una instalación en un tenant.
ESTADOS_INSTALACION = ("instalada", "pausada", "desinstalada", "error")


class Manifiesto(Base, TimestampMixin):
    """Un conector declarado, con versión (CRM-00.03.04.01)."""

    __tablename__ = "manifiestos_conector"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    # Sin `tenant_id`: el catálogo es del proveedor del CRM y es el mismo para
    # todos. Lo que es de cada tenant es la instalación, que sí lo lleva.
    clave: Mapped[str] = mapped_column(String(80), nullable=False)
    version: Mapped[str] = mapped_column(String(20), nullable=False, default="1")
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    categoria: Mapped[str] = mapped_column(
        String(30), nullable=False, default="otros", info={"opciones": CATEGORIAS}
    )
    descripcion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    protocolo: Mapped[str] = mapped_column(String(20), nullable=False, default="rest")

    # Qué sabe hacer: [{clave, nombre, metodo, ruta, mapeo, parametros}]. Es lo
    # que ejecuta el motor declarativo; aquí solo se guarda y se valida.
    operaciones: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Qué credenciales pide: [{clave, tipo, obligatoria, ayuda}]. Se enseña antes
    # de instalar, porque instalar y descubrir después que hace falta un
    # certificado que tarda dos semanas es el final de la integración.
    credenciales: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # A qué dominios va a llamar. Declararlo permite enseñarlo antes y, sobre
    # todo, que alguien pueda decir que no.
    dominios: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    config_defecto: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="borrador")
    publicado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Qué cambia respecto a la versión anterior. Obligatorio al publicar una
    # versión nueva: sin esto, actualizar es un salto a ciegas.
    notas_version: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (
        UniqueConstraint("clave", "version", name="uq_manifiesto_version"),
        Index("ix_manifiestos_catalogo", "estado", "categoria"),
    )


class Instalacion(Base, TimestampMixin):
    """Un manifiesto instalado en un tenant (CRM-00.03.04.10)."""

    __tablename__ = "instalaciones_conector"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    manifiesto_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("manifiestos_conector.id", ondelete="RESTRICT"),
        nullable=False,
    )
    clave: Mapped[str] = mapped_column(String(80), nullable=False)
    # La versión instalada se copia aquí: es lo que permite saber con qué está
    # funcionando este tenant sin depender de cuál sea la última publicada.
    version: Mapped[str] = mapped_column(String(20), nullable=False)
    conexion_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="instalada")
    motivo_estado: Mapped[str] = mapped_column(Text, nullable=False, default="")
    instalada_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    instalada_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    desinstalada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Credenciales que faltan por rellenar. Se guarda calculado al instalar para
    # que la lista de integraciones pueda decir «esta no va a funcionar» sin
    # tener que probarla.
    credenciales_pendientes: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "clave", name="uq_instalacion_clave"),
        Index("ix_instalaciones_estado", "tenant_id", "estado"),
    )


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def validar(manifiesto: dict[str, Any]) -> list[str]:
    """Comprueba un manifiesto y devuelve **todo** lo que está mal.

    Todo de golpe y no el primer error: quien escribe un manifiesto de veinte
    operaciones no puede descubrirlos de uno en uno.
    """
    from services.integration.transportes_legado import PROTOCOLOS

    problemas: list[str] = []
    if not str(manifiesto.get("clave") or "").strip():
        problemas.append("Falta la clave del conector.")
    protocolo = str(manifiesto.get("protocolo") or "rest")
    if protocolo != "rest" and protocolo not in PROTOCOLOS:
        problemas.append(
            f"Protocolo «{protocolo}» desconocido: los admitidos son rest y {list(PROTOCOLOS)}."
        )
    operaciones = manifiesto.get("operaciones") or []
    if not operaciones:
        problemas.append("Un conector sin operaciones no puede hacer nada.")
    claves = set()
    for i, operacion in enumerate(operaciones, 1):
        clave = str(operacion.get("clave") or "")
        if not clave:
            problemas.append(f"La operación {i} no tiene clave.")
        elif clave in claves:
            problemas.append(f"La operación «{clave}» está repetida.")
        claves.add(clave)
        if protocolo == "rest" and not operacion.get("ruta"):
            problemas.append(f"La operación «{clave or i}» no dice a qué ruta llama.")
        mapeo = operacion.get("mapeo") or {}
        if not isinstance(mapeo, dict):
            problemas.append(f"El mapeo de «{clave or i}» tiene que ser un diccionario.")
    for i, credencial in enumerate(manifiesto.get("credenciales") or [], 1):
        if not str(credencial.get("clave") or ""):
            problemas.append(f"La credencial {i} no tiene clave.")
    if not manifiesto.get("dominios") and protocolo == "rest":
        problemas.append(
            "No se declara a qué dominios llama: sin eso, nadie puede revisar a "
            "dónde van los datos antes de instalarlo."
        )
    return problemas


def publicar(
    uow: UnidadDeTrabajo,
    *,
    clave: str,
    nombre: str,
    version: str,
    operaciones: list[dict[str, Any]],
    categoria: str = "otros",
    descripcion: str = "",
    protocolo: str = "rest",
    credenciales: list[dict[str, Any]] | None = None,
    dominios: list[str] | None = None,
    config_defecto: dict[str, Any] | None = None,
    notas_version: str = "",
) -> Manifiesto:
    """Publica una versión del conector en el catálogo (CRM-00.03.04.01).

    Se valida **ahora**: un mapeo mal escrito descubierto dentro de un proceso
    nocturno tres semanas después produce un error que no se parece a la causa.

    Una versión nueva de algo ya publicado exige **notas**: sin ellas, quien tenga
    que decidir si actualiza su integración de producción está saltando a ciegas.
    """
    if categoria not in CATEGORIAS:
        raise ErrorValidacion(
            f"Categoría «{categoria}» no válida.",
            error_code="manifiestos.categoria_no_valida",
            detalle={"validas": list(CATEGORIAS)},
        )
    problemas = validar(
        {
            "clave": clave,
            "protocolo": protocolo,
            "operaciones": operaciones,
            "credenciales": credenciales,
            "dominios": dominios,
        }
    )
    if problemas:
        raise ErrorValidacion(
            "El manifiesto tiene problemas que harían fallar la integración en " "ejecución.",
            error_code="manifiestos.invalido",
            detalle={"problemas": problemas},
        )

    anteriores = (
        uow.db.execute(select(Manifiesto).where(Manifiesto.clave == clave.strip())).scalars().all()
    )
    if anteriores and not notas_version.strip():
        raise ErrorValidacion(
            "Publicar una versión nueva exige decir qué cambia: quien decida "
            "actualizar su integración de producción no puede hacerlo a ciegas.",
            error_code="manifiestos.sin_notas",
        )
    if any(m.version == version for m in anteriores):
        raise Conflicto(
            "Esa versión ya está publicada. Las versiones no se reescriben: los "
            "tenants que la tienen instalada dejarían de estar donde creen.",
            error_code="manifiestos.version_duplicada",
        )

    fila = Manifiesto(
        clave=clave.strip(),
        version=version.strip(),
        nombre=nombre.strip(),
        categoria=categoria,
        descripcion=descripcion,
        protocolo=protocolo,
        operaciones=list(operaciones),
        credenciales=list(credenciales or []),
        dominios=list(dominios or []),
        config_defecto=dict(config_defecto or {}),
        estado="publicado",
        publicado_at=_ahora(),
        notas_version=notas_version.strip(),
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila


def catalogo(
    db: Session, *, categoria: str = "", incluir_retirados: bool = False
) -> dict[str, Any]:
    """El catálogo: **la última versión publicada de cada conector**.

    Enseñar todas las versiones convierte el catálogo en un historial y hace que
    alguien instale la 2 teniendo la 5 delante.
    """
    consulta = select(Manifiesto)
    if not incluir_retirados:
        consulta = consulta.where(Manifiesto.estado == "publicado")
    if categoria:
        consulta = consulta.where(Manifiesto.categoria == categoria)
    filas = db.execute(consulta.order_by(Manifiesto.clave, Manifiesto.publicado_at)).scalars().all()

    ultimos: dict[str, Manifiesto] = {}
    versiones: dict[str, int] = {}
    for fila in filas:
        ultimos[fila.clave] = fila
        versiones[fila.clave] = versiones.get(fila.clave, 0) + 1
    return {
        "conectores": [
            {
                "clave": m.clave,
                "nombre": m.nombre,
                "categoria": m.categoria,
                "version": m.version,
                "versiones_publicadas": versiones[m.clave],
                "descripcion": m.descripcion,
                "protocolo": m.protocolo,
                "operaciones": [o.get("clave") for o in (m.operaciones or [])],
                # Lo que va a pedir y a dónde va a llamar, **antes** de instalar.
                "credenciales": m.credenciales,
                "dominios": m.dominios,
                "estado": m.estado,
            }
            for m in sorted(ultimos.values(), key=lambda m: (m.categoria, m.nombre))
        ],
        "cuantos": len(ultimos),
    }


def instalar(
    uow: UnidadDeTrabajo,
    *,
    clave: str,
    version: str = "",
    config: dict[str, Any] | None = None,
    credenciales_puestas: list[str] | None = None,
    por: UUID | None = None,
) -> tuple[Instalacion, dict[str, Any]]:
    """Instala un conector en este tenant (CRM-00.03.04.10).

    Devuelve **qué credenciales faltan** en vez de fallar: instalar y configurar
    son dos momentos distintos, y a veces la credencial la tiene otra persona. Lo
    que no se hace es dar la integración por operativa: la instalación queda con
    su lista de pendientes, y la pantalla puede decir «esta no va a funcionar
    todavía» sin tener que probarla.
    """
    consulta = select(Manifiesto).where(Manifiesto.clave == clave.strip())
    if version:
        consulta = consulta.where(Manifiesto.version == version)
    else:
        consulta = consulta.where(Manifiesto.estado == "publicado")
    candidatos = uow.db.execute(consulta.order_by(Manifiesto.publicado_at.desc())).scalars().all()
    if not candidatos:
        raise NoEncontrado(
            f"No hay conector «{clave}» publicado",
            error_code="manifiestos.no_encontrado",
        )
    manifiesto = candidatos[0]
    if manifiesto.estado == "retirado":
        raise Conflicto(
            "Ese conector está retirado: no se instala más. Lo ya instalado sigue "
            "funcionando, pero esto sería empezar por algo que se va a ir.",
            error_code="manifiestos.retirado",
        )

    ya = uow.db.execute(
        select(Instalacion).where(
            Instalacion.tenant_id == uow.tenant_id, Instalacion.clave == manifiesto.clave
        )
    ).scalar_one_or_none()
    if ya is not None and ya.estado != "desinstalada":
        raise Conflicto(
            "Ese conector ya está instalado en este tenant",
            error_code="manifiestos.ya_instalado",
            detalle={"instalacion_id": str(ya.id), "version": ya.version},
        )

    puestas = set(credenciales_puestas or [])
    pendientes = [
        str(c.get("clave"))
        for c in (manifiesto.credenciales or [])
        if c.get("obligatoria", True) and str(c.get("clave")) not in puestas
    ]

    fila = ya or Instalacion(
        tenant_id=uow.tenant_id, clave=manifiesto.clave, version=manifiesto.version
    )
    fila.manifiesto_id = manifiesto.id
    fila.version = manifiesto.version
    fila.config = {**(manifiesto.config_defecto or {}), **(config or {})}
    fila.estado = "instalada"
    fila.motivo_estado = ""
    fila.instalada_por = por
    fila.instalada_at = _ahora()
    fila.desinstalada_at = None
    fila.credenciales_pendientes = pendientes
    if ya is None:
        uow.db.add(fila)
    uow.db.flush()
    registrar(
        uow.db,
        accion="conector.instalado",
        objeto="instalacion_conector",
        objeto_id=fila.id,
        datos={
            "clave": manifiesto.clave,
            "version": manifiesto.version,
            "dominios": manifiesto.dominios,
            "credenciales_pendientes": pendientes,
        },
        tenant_id=uow.tenant_id,
    )
    uow.emitir(
        "connector.installed",
        subject=("instalacion_conector", fila.id),
        data={"clave": manifiesto.clave, "version": manifiesto.version},
    )
    return fila, {
        "credenciales_pendientes": pendientes,
        "operativa": not pendientes,
        "dominios": manifiesto.dominios,
        "aviso": (
            ""
            if not pendientes
            else "Faltan credenciales: la integración está instalada pero no va a "
            "funcionar hasta que se pongan."
        ),
    }


def actualizaciones(db: Session, tenant_id: UUID) -> dict[str, Any]:
    """Qué instalaciones tienen una versión más nueva disponible, y qué cambia.

    **No se actualiza solo.** Cambiar el comportamiento de una integración en
    producción sin que nadie lo decida es cómo un proceso que funcionaba deja de
    funcionar un martes sin ningún despliegue de por medio.
    """
    instaladas = (
        db.execute(
            select(Instalacion).where(
                Instalacion.tenant_id == tenant_id, Instalacion.estado == "instalada"
            )
        )
        .scalars()
        .all()
    )
    salida = []
    for instalacion in instaladas:
        publicadas = (
            db.execute(
                select(Manifiesto)
                .where(Manifiesto.clave == instalacion.clave, Manifiesto.estado == "publicado")
                .order_by(Manifiesto.publicado_at.desc())
            )
            .scalars()
            .all()
        )
        if not publicadas:
            salida.append(
                {
                    "clave": instalacion.clave,
                    "version_instalada": instalacion.version,
                    "hay_actualizacion": False,
                    # Un conector retirado del catálogo con instalaciones vivas es
                    # algo que hay que ver: sigue funcionando, pero ya nadie lo
                    # mantiene.
                    "retirado_del_catalogo": True,
                }
            )
            continue
        ultima = publicadas[0]
        salida.append(
            {
                "clave": instalacion.clave,
                "version_instalada": instalacion.version,
                "ultima_version": ultima.version,
                "hay_actualizacion": ultima.version != instalacion.version,
                "que_cambia": ultima.notas_version if ultima.version != instalacion.version else "",
                "retirado_del_catalogo": False,
            }
        )
    return {
        "instalaciones": salida,
        "con_actualizacion": len([s for s in salida if s.get("hay_actualizacion")]),
        "retirados": len([s for s in salida if s.get("retirado_del_catalogo")]),
    }


def actualizar(
    uow: UnidadDeTrabajo, *, clave: str, a_version: str = "", por: UUID | None = None
) -> dict[str, Any]:
    """Sube una instalación a otra versión, **diciendo qué cambia**."""
    instalacion = uow.db.execute(
        select(Instalacion).where(
            Instalacion.tenant_id == uow.tenant_id, Instalacion.clave == clave
        )
    ).scalar_one_or_none()
    if instalacion is None or instalacion.estado == "desinstalada":
        raise NoEncontrado("Ese conector no está instalado", error_code="manifiestos.no_instalado")
    consulta = select(Manifiesto).where(Manifiesto.clave == clave, Manifiesto.estado == "publicado")
    if a_version:
        consulta = consulta.where(Manifiesto.version == a_version)
    destino = uow.db.execute(consulta.order_by(Manifiesto.publicado_at.desc())).scalars().first()
    if destino is None:
        raise NoEncontrado(
            "No hay ninguna versión publicada a la que subir",
            error_code="manifiestos.sin_version",
        )
    if destino.version == instalacion.version:
        return {"actualizado": False, "porque": "Ya está en esa versión."}

    desde = instalacion.version
    instalacion.version = destino.version
    instalacion.manifiesto_id = destino.id
    uow.db.flush()
    registrar(
        uow.db,
        accion="conector.actualizado",
        objeto="instalacion_conector",
        objeto_id=instalacion.id,
        datos={"desde": desde, "hasta": destino.version, "notas": destino.notas_version},
        tenant_id=uow.tenant_id,
    )
    return {
        "actualizado": True,
        "desde": desde,
        "hasta": destino.version,
        "que_cambia": destino.notas_version,
    }


def desinstalar(uow: UnidadDeTrabajo, *, clave: str, motivo: str = "") -> Instalacion:
    """Desinstala el conector. **Los datos ya traídos se quedan.**

    Borrarlos convertiría probar una integración en perder información: lo que
    entró es de la empresa, no del conector que lo trajo.
    """
    instalacion = uow.db.execute(
        select(Instalacion).where(
            Instalacion.tenant_id == uow.tenant_id, Instalacion.clave == clave
        )
    ).scalar_one_or_none()
    if instalacion is None:
        raise NoEncontrado("Ese conector no está instalado", error_code="manifiestos.no_instalado")
    instalacion.estado = "desinstalada"
    instalacion.motivo_estado = motivo.strip()
    instalacion.desinstalada_at = _ahora()
    uow.db.flush()
    registrar(
        uow.db,
        accion="conector.desinstalado",
        objeto="instalacion_conector",
        objeto_id=instalacion.id,
        datos={"clave": clave, "motivo": motivo},
        tenant_id=uow.tenant_id,
    )
    return instalacion


def retirar(uow: UnidadDeTrabajo, *, clave: str, version: str, motivo: str) -> dict[str, Any]:
    """Retira una versión del catálogo. Lo instalado **sigue funcionando**.

    Retirar y romper a quien lo tiene puesto son cosas distintas. Se devuelve a
    cuántos tenants afecta, que es lo que hay que mirar antes de retirar nada.
    """
    if not motivo.strip():
        raise ErrorValidacion(
            "Retirar una versión exige motivo: quien la tenga instalada preguntará.",
            error_code="manifiestos.motivo_obligatorio",
        )
    fila = uow.db.execute(
        select(Manifiesto).where(Manifiesto.clave == clave, Manifiesto.version == version)
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado("Esa versión no existe", error_code="manifiestos.no_encontrado")
    fila.estado = "retirado"
    afectados = (
        uow.db.execute(
            select(func.count())
            .select_from(Instalacion)
            .where(Instalacion.clave == clave, Instalacion.version == version)
        )
    ).scalar_one()
    uow.db.flush()
    return {
        "clave": clave,
        "version": version,
        "instalaciones_afectadas": int(afectados),
        "siguen_funcionando": True,
        "motivo": motivo.strip(),
    }
