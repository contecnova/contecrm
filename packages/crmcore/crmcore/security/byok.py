"""Clave aportada y revocable por el cliente — BYOK/CMEK (CRM-00.01.04.09).

Lo que compra un cliente con BYOK no es «cifrado»: eso ya lo tiene. Compra
**poder apagarlo**. Si un día decide irse, o sospecha de nosotros, o un juez se
lo ordena, revoca su clave y sus datos dejan de ser legibles para todo el mundo,
nosotros incluidos, sin depender de que nadie ejecute un borrado ni de que se
purgue una copia de seguridad. Eso se llama *crypto-shredding* y es el único
borrado que se puede demostrar en minutos en vez de en semanas.

Cómo funciona aquí, en tres piezas:

**Sobre cerrado (envelope).** El cliente aporta material de clave. No se guarda
tal cual: se envuelve con la maestra del despliegue y se guarda el sobre. Para
descifrar un campo hacen falta las dos —la del cliente y la nuestra—, así que ni
una copia de la base sin la maestra sirve, ni la maestra sin el sobre del
cliente.

**La clave efectiva se deriva, no se guarda.** `HKDF(maestra, material, propósito)`.
El propósito separa la clave que cifra credenciales de integración de la que
cifra un campo de cliente, igual que sin BYOK. Nada de esto vive en disco fuera
del sobre.

**Revocar es olvidar el material, no borrar filas.** Se marca la clave como
revocada y se borra el sobre. A partir de ahí, descifrar un campo de ese tenant
falla con un error explícito. **Es irreversible a propósito**: si se pudiera
deshacer, no sería una garantía, sería un interruptor.

Dos cosas que conviene tener claras antes de encenderlo:

*Esto no protege del proceso vivo.* Mientras el servicio corre y la clave está
activa, el material está en memoria. BYOK protege de quien lee el disco, la
copia de seguridad o la base parada; de quien ejecuta código en el proceso, no.
Para eso hace falta un HSM, y se dice en vez de sugerir lo contrario.

*Revocar rompe cosas, y esa es la idea.* Los campos cifrados de ese tenant dejan
de leerse: credenciales de integración, secretos, lo que el modelo declare
sensible. La API responde un error claro en vez de un 500, para que quien lo vea
sepa qué ha pasado y no busque una avería.

**Genérico, sin proveedor.** No hay código de AWS KMS ni de Azure Key Vault. El
material lo aporta el cliente por API o lo trae un `proveedor` externo declarado
por configuración. Enchufar un KMS concreto es escribir un proveedor, no tocar
esto.
"""

from __future__ import annotations

import base64
import hashlib
import os
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Index, String, Text, select
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from crmcore.db.base import Base, TimestampMixin
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Bytes mínimos de material que se aceptan. 32 son 256 bits: por debajo, el
# cliente cree que aporta una clave y aporta una contraseña. Se rechaza en vez
# de estirarla con un derivador, porque estirar entropía que no existe da una
# falsa sensación de fortaleza.
MINIMO_BYTES = 32

ESTADOS = ("activa", "revocada")

# Evento con el que la clave llega a todos los servicios. El material viaja
# **envuelto**, es decir cifrado con la maestra del despliegue: por el bus pasa
# lo mismo que hay en la base, ni más ni menos. Sin la maestra no sirve de nada.
CLAVE_CAMBIADA = "seguridad.clave_tenant_cambiada"


class ClaveTenant(Base, TimestampMixin):
    """El sobre con el material de clave de un tenant.

    Vive en el esquema de **cada** servicio, como `ajustes_runtime`, y se
    replica por evento. No es duplicación gratuita: cada servicio cifra y
    descifra los campos de sus propias tablas dentro de sus transacciones, y
    pedirle la clave a otro servicio en cada lectura ataría la disponibilidad de
    todo el CRM a la de uno, y añadiría un viaje de red por campo cifrado.
    """

    __tablename__ = "claves_tenant"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    # Versión de la clave. Rotar crea una nueva y deja la anterior en estado
    # activo hasta que se recifra: sin eso, rotar exigiría una ventana de parada.
    version: Mapped[int] = mapped_column(nullable=False, default=1)
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="activa")

    # El material del cliente, envuelto con la maestra del despliegue. Al
    # revocar se **vacía**: es lo que hace el borrado criptográfico irreversible
    # de verdad, en vez de dejar el material ahí con una marca que alguien puede
    # quitar con un UPDATE.
    sobre: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Huella del material, para poder comprobar que el cliente vuelve a aportar
    # la MISMA clave sin tener que guardarla. Sobrevive a la revocación: es lo
    # que permite demostrar después qué clave estaba activa.
    huella: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    # De dónde salió: `api` cuando la sube el cliente, o el nombre del proveedor
    # externo. Texto libre a propósito — el producto no conoce proveedores.
    origen: Mapped[str] = mapped_column(String(60), nullable=False, default="api")

    revocada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revocada_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    motivo_revocacion: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    # `True` cuando el cliente confirmó por escrito que entiende que es
    # irreversible. No es burocracia: sin esta confirmación, una llamada mal
    # dirigida deja ilegibles los datos de un cliente y no hay vuelta atrás.
    confirmada: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (Index("ix_claves_tenant", "tenant_id", "estado", "version"),)


def _declarar_evento() -> None:
    from crmcore.events.catalogo import TipoEvento, obtener, registrar

    if obtener(CLAVE_CAMBIADA) is not None:
        return
    registrar(
        TipoEvento(
            tipo=CLAVE_CAMBIADA,
            version=1,
            productor="core",
            descripcion=(
                "La clave propia de un tenant se ha registrado, rotado o "
                "revocado. La consumen TODOS los servicios para replicarla"
            ),
            campos=("version", "estado", "sobre", "huella", "origen", "motivo"),
            # No se publica hacia fuera: un webhook con el sobre de la clave en
            # el cuerpo es exactamente lo que este módulo existe para evitar.
            publico=False,
        )
    )


def _propagar(db: Session, fila: "ClaveTenant") -> None:
    """Lleva el alta, la rotación o la revocación al resto de servicios.

    Igual que con los ajustes: la tabla vive en el esquema de cada servicio y
    ninguno lee el de otro. Sin esto, registrar la clave desde la consola la
    dejaría solo en `tenancy` y `party` seguiría cifrando con la maestra — con
    lo que revocar no dejaría ilegible nada, que es el único modo de fallo
    inaceptable en esta funcionalidad.
    """
    from crmcore.bus.outbox import encolar

    _declarar_evento()
    encolar(
        db,
        tenant_id=fila.tenant_id,
        tipo=CLAVE_CAMBIADA,
        subject_tipo="clave_tenant",
        subject_id=str(fila.tenant_id),
        data={
            "version": fila.version,
            "estado": fila.estado,
            "sobre": fila.sobre,
            "huella": fila.huella,
            "origen": fila.origen,
            "motivo": fila.motivo_revocacion,
        },
        dedup_key=f"byok:{fila.tenant_id}:{fila.version}:{fila.estado}",
    )


async def consumir_clave(mensaje: Any) -> None:
    """Aplica en ESTE servicio el cambio de clave de un tenant.

    Idempotente y **sin reemitir**: si reemitiera, cada servicio publicaría al
    aplicar y el bus entraría en un bucle.
    """
    from crmcore.db.uow import unidad_de_trabajo

    if isinstance(mensaje, dict):
        datos = mensaje.get("data") if isinstance(mensaje.get("data"), dict) else mensaje
        bruto = mensaje.get("tenant_id") or (datos or {}).get("tenant_id")
    else:
        datos = getattr(mensaje, "data", None) or {}
        bruto = getattr(mensaje, "tenant_id", None)
    if not bruto or not datos:
        return
    tenant_id = UUID(str(bruto))

    with unidad_de_trabajo(sistema=True) as uow:
        _aplicar_local(uow.db, tenant_id, datos)


def _aplicar_local(db: Session, tenant_id: UUID, datos: dict[str, Any]) -> None:
    version = int(datos.get("version") or 1)
    estado = str(datos.get("estado") or "activa")
    fila = (
        db.execute(
            select(ClaveTenant).where(
                ClaveTenant.tenant_id == tenant_id, ClaveTenant.version == version
            )
        )
        .scalars()
        .first()
    )
    if fila is None:
        fila = ClaveTenant(tenant_id=tenant_id, version=version)
        db.add(fila)
    fila.estado = estado
    fila.sobre = str(datos.get("sobre") or "")
    fila.huella = str(datos.get("huella") or "")
    fila.origen = str(datos.get("origen") or "api")
    if estado == "revocada":
        # Al revocar se revocan TODAS las versiones: el evento se emite por la
        # que se tocó, pero dejar viva otra versión antigua haría que el dato
        # cifrado con ella siguiera legible, y la revocación sería un gesto.
        for otra in (
            db.execute(select(ClaveTenant).where(ClaveTenant.tenant_id == tenant_id))
            .scalars()
            .all()
        ):
            otra.estado = "revocada"
            otra.sobre = ""
            otra.revocada_at = datetime.now(timezone.utc)
            otra.motivo_revocacion = str(datos.get("motivo") or "")[:500]
    db.flush()


# ── Consulta ──────────────────────────────────────────────────────────────


def activa(db: Session, tenant_id: UUID) -> ClaveTenant | None:
    """La clave activa de mayor versión, o `None` si no hay BYOK para este tenant."""
    return (
        db.execute(
            select(ClaveTenant)
            .where(ClaveTenant.tenant_id == tenant_id, ClaveTenant.estado == "activa")
            .order_by(ClaveTenant.version.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )


def esta_revocada(db: Session, tenant_id: UUID) -> bool:
    """Si el tenant tuvo clave y la revocó.

    Distinguir «nunca tuvo BYOK» de «lo tuvo y lo revocó» es lo que permite
    responder con un error claro en vez de caer a la maestra y seguir
    descifrando — que sería exactamente romper la promesa que se vendió.
    """
    if activa(db, tenant_id) is not None:
        return False
    return (
        db.execute(
            select(ClaveTenant.id)
            .where(ClaveTenant.tenant_id == tenant_id, ClaveTenant.estado == "revocada")
            .limit(1)
        ).first()
        is not None
    )


def historial(db: Session, tenant_id: UUID) -> list[dict[str, Any]]:
    """Qué claves ha tenido este tenant. Nunca el material, solo la huella."""
    filas = (
        db.execute(
            select(ClaveTenant)
            .where(ClaveTenant.tenant_id == tenant_id)
            .order_by(ClaveTenant.version.desc())
        )
        .scalars()
        .all()
    )
    return [
        {
            "version": f.version,
            "estado": f.estado,
            "huella": f.huella,
            "origen": f.origen,
            "creada_at": f.created_at.isoformat() if f.created_at else None,
            "revocada_at": f.revocada_at.isoformat() if f.revocada_at else None,
            "motivo_revocacion": f.motivo_revocacion,
        }
        for f in filas
    ]


# ── Alta y rotación ───────────────────────────────────────────────────────


def _envolver(material: bytes) -> str:
    """Cifra el material del cliente con la maestra del despliegue.

    El propósito `byok` está reservado y el cifrado lo trata aparte: lo que
    envuelve a la clave del cliente no puede cifrarse con la clave del cliente.
    """
    from crmcore.security.cifrado import PROPOSITO_SOBRE, cifrar

    return cifrar(base64.b64encode(material).decode(), proposito=PROPOSITO_SOBRE)


def _desenvolver(sobre: str) -> bytes:
    from crmcore.security.cifrado import PROPOSITO_SOBRE, descifrar

    return base64.b64decode(descifrar(sobre, proposito=PROPOSITO_SOBRE))


def huella_de(material: bytes) -> str:
    """Identificador público del material, sin revelarlo.

    Es un SHA-256 de un valor de alta entropía, así que no es invertible en la
    práctica. Sirve para que el cliente compruebe que ha subido la clave que
    creía, y para dejar constancia de cuál estaba activa cuando se revocó.
    """
    return hashlib.sha256(material).hexdigest()


def registrar(
    db: Session,
    *,
    tenant_id: UUID,
    material: bytes,
    origen: str = "api",
    por: UUID | None = None,
) -> ClaveTenant:
    """Da de alta la clave del cliente, o la rota si ya tenía una.

    Rotar **no invalida la anterior**: la nueva se usa para escribir y la
    anterior sigue sirviendo para leer lo que aún no se ha recifrado. Es la
    misma decisión que con la maestra, y por el mismo motivo: sin ella, rotar
    exige una ventana de parada del tamaño de la base.
    """
    from crmcore.audit.chain import registrar as auditar

    if len(material) < MINIMO_BYTES:
        raise ErrorValidacion(
            f"El material de clave debe tener al menos {MINIMO_BYTES} bytes "
            f"({MINIMO_BYTES * 8} bits); se han recibido {len(material)}",
            error_code="byok.material_debil",
            detalle={"minimo_bytes": MINIMO_BYTES, "recibidos": len(material)},
        )
    if esta_revocada(db, tenant_id):
        # Aceptar una clave nueva después de revocar daría a entender que lo
        # revocado se recupera, y no se recupera: los datos viejos siguen
        # ilegibles. Se exige decirlo en dos pasos.
        raise Conflicto(
            "Este tenant revocó su clave. Lo cifrado con ella es ilegible para "
            "siempre; para volver a usar BYOK hay que reiniciar el cifrado del "
            "tenant explícitamente",
            error_code="byok.revocada_no_reversible",
        )

    anterior = activa(db, tenant_id)
    fila = ClaveTenant(
        tenant_id=tenant_id,
        version=(anterior.version + 1) if anterior else 1,
        estado="activa",
        sobre=_envolver(material),
        huella=huella_de(material),
        origen=origen,
    )
    db.add(fila)
    db.flush()

    auditar(
        db,
        accion="byok.clave_registrada" if anterior is None else "byok.clave_rotada",
        objeto="clave_tenant",
        objeto_id=fila.id,
        datos={"version": fila.version, "huella": fila.huella, "origen": origen},
        tenant_id=tenant_id,
    )
    _propagar(db, fila)
    logger.info("byok.registrada", tenant=str(tenant_id), version=fila.version, origen=origen)
    return fila


def generar_material() -> bytes:
    """Material nuevo, para el cliente que prefiere que lo generemos nosotros.

    Se le devuelve **una sola vez** y no se guarda en claro. Ofrecerlo no
    contradice el BYOK: lo que importa no es quién teclea los bytes, sino quién
    puede revocarlos.
    """
    return os.urandom(MINIMO_BYTES)


# ── Revocación ────────────────────────────────────────────────────────────


def revocar(
    db: Session,
    *,
    tenant_id: UUID,
    motivo: str,
    confirmado: bool,
    por: UUID | None = None,
) -> ClaveTenant:
    """Olvida el material del cliente. **Irreversible.**

    Borra el sobre de todas las versiones y las marca revocadas. A partir de
    aquí, los campos cifrados de este tenant no se pueden leer: ni por nosotros,
    ni con una copia de seguridad, ni con la maestra.

    Exige `confirmado` porque es la operación de este sistema que menos vuelta
    atrás tiene. Y exige un motivo porque dentro de un año alguien preguntará
    por qué esos datos no se leen, y la respuesta tiene que estar escrita.
    """
    from crmcore.audit.chain import registrar as auditar

    if not confirmado:
        raise ErrorValidacion(
            "Revocar la clave deja ilegibles los datos cifrados de este tenant "
            "de forma irreversible. Hay que confirmarlo explícitamente",
            error_code="byok.confirmacion_requerida",
        )
    if not motivo.strip():
        raise ErrorValidacion(
            "Hay que decir por qué se revoca: dentro de un año alguien "
            "preguntará por qué estos datos no se leen",
            error_code="byok.motivo_requerido",
        )

    filas = (
        db.execute(select(ClaveTenant).where(ClaveTenant.tenant_id == tenant_id)).scalars().all()
    )
    if not filas:
        raise NoEncontrado(
            "Este tenant no tiene clave propia que revocar", error_code="byok.sin_clave"
        )
    if all(f.estado == "revocada" for f in filas):
        raise Conflicto("La clave ya estaba revocada", error_code="byok.ya_revocada")

    ahora = datetime.now(timezone.utc)
    for fila in filas:
        # Se vacía el sobre, no se marca y se guarda: dejar el material con una
        # bandera de «revocada» convierte la garantía en un `UPDATE` de
        # distancia, y quien compra BYOK compra justo lo contrario.
        fila.sobre = ""
        fila.estado = "revocada"
        fila.revocada_at = ahora
        fila.revocada_por = por
        fila.motivo_revocacion = motivo[:500]
        fila.confirmada = True
    db.flush()

    auditar(
        db,
        accion="byok.clave_revocada",
        objeto="clave_tenant",
        objeto_id=filas[0].id,
        datos={
            "versiones": [f.version for f in filas],
            "huellas": [f.huella for f in filas],
            "motivo": motivo[:500],
        },
        tenant_id=tenant_id,
    )
    _propagar(db, filas[0])
    logger.warning(
        "byok.revocada", tenant=str(tenant_id), versiones=len(filas), motivo=motivo[:120]
    )
    return filas[0]


# ── Derivación de la clave efectiva ───────────────────────────────────────


def clave_efectiva(db: Session | None, tenant_id: UUID | None, proposito: str) -> bytes | None:
    """La clave con la que cifrar o descifrar para este tenant.

    Devuelve `None` cuando este tenant no usa BYOK, y entonces se aplica la
    derivación normal de la maestra. Lanza cuando la usó y la revocó: caer a la
    maestra en ese caso sería seguir descifrando datos que el cliente mandó
    hacer ilegibles, que es exactamente lo contrario de lo que compró.
    """
    from crmcore.config import get_settings

    if not get_settings().byok_enabled or db is None or tenant_id is None:
        return None

    fila = activa(db, tenant_id)
    if fila is None:
        if esta_revocada(db, tenant_id):
            raise ClaveRevocada(
                "La clave de cifrado de este tenant está revocada: sus datos "
                "cifrados son ilegibles de forma irreversible",
                error_code="byok.clave_revocada",
            )
        return None

    material = _desenvolver(fila.sobre)
    # Mismo esquema de derivación que sin BYOK, con el material del cliente
    # dentro: así el propósito sigue separando subsistemas y comprometer uno no
    # da acceso al otro.
    return hashlib.sha256(f"{proposito}|".encode() + material).digest()


class ClaveRevocada(Conflicto):
    """El tenant revocó su clave y lo cifrado con ella ya no se puede leer.

    Es un 409 y no un 500 a propósito: no es una avería, es el sistema
    cumpliendo lo que el cliente pidió. Quien lo vea tiene que entenderlo sin
    abrir un ticket.
    """

    code = "byok_revocada"
    title = "Clave del cliente revocada"
