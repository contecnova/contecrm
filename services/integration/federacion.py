"""Datos externos en la vista sin replicarlos, y CRM embebido
(CRM-01.01.05.04, CRM-00.02.03.10).

Hay datos que **no deben copiarse al CRM**: el saldo del cliente, su riesgo
crediticio, sus últimas facturas. No porque no quepan, sino porque copiarlos crea
una segunda verdad que envejece: la ficha dice que debe 3.000 € y la realidad son
cero desde ayer, y alguien llama a reclamar a un cliente que ya pagó.

Federar es enseñarlos **sin traerlos**: se piden cuando se miran, se marcan como
de fuera y se dice de cuándo son.

De ahí las cuatro decisiones:

**Si el sistema externo no contesta, se dice.** No se enseña un hueco ni un cero:
un saldo vacío se lee como «no debe nada». Se devuelve `disponible: false` con el
porqué, y la pantalla enseña que ese dato no se ha podido consultar.

**Hay tiempo máximo y hay caché corta.** Una ficha de cliente no puede tardar seis
segundos porque el ERP va lento; pasado el tope se corta y se dice. Y lo que se
cachea se cachea **con su edad visible**: un dato de hace diez minutos presentado
como actual es el mismo problema que copiarlo.

**Lo federado no se puede filtrar ni ordenar.** Y se dice en voz alta, porque es
la pregunta siguiente: para buscar «clientes con saldo > 1.000» habría que traer
todos los saldos, y eso es replicar con otro nombre.

**El CRM embebido lleva su contexto declarado.** Cuando el CRM vive dentro del ERP
o del portal del cliente, quien lo embebe dice qué registro está mirando y con qué
identidad; lo que se enseña sale de eso y no de una sesión que el anfitrión no
tiene.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.db.base import Base, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import (
    Boolean,
    Index,
    Integer,
    String,
    UniqueConstraint,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

logger = get_logger(__name__)

# Caché en memoria por proceso: (tenant, vista, clave) -> (datos, caducidad).
# Corta a propósito y **con la edad visible**: es para no machacar al ERP cuando
# alguien abre la misma ficha tres veces seguidas, no para ahorrarse la consulta.
_cache: dict[tuple[str, str, str], tuple[dict[str, Any], float, float]] = {}


def limpiar_cache() -> None:
    _cache.clear()


class VistaFederada(Base, TimestampMixin):
    """Un bloque de datos que se enseña sin copiarlo (CRM-01.01.05.04)."""

    __tablename__ = "vistas_federadas"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(80), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # Sobre qué objeto del CRM se enseña: cuenta, contacto, oportunidad…
    objeto: Mapped[str] = mapped_column(String(60), nullable=False)
    conexion_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    instalacion_clave: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    operacion: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    # Con qué campo del registro se llama al sistema externo.
    clave_registro: Mapped[str] = mapped_column(String(80), nullable=False, default="id")
    # Qué campos se enseñan y cómo se llaman aquí.
    campos: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Tope de espera. Una ficha no puede tardar seis segundos porque el ERP va
    # lento: pasado esto se corta y se dice que no se pudo consultar.
    timeout_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=2000)
    # Segundos de caché. Cero = siempre en vivo. La edad del dato se devuelve
    # siempre, se cachee o no.
    cache_s: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "clave", name="uq_vista_federada"),
        Index("ix_vistas_federadas", "tenant_id", "objeto", "activa"),
    )


class Embebido(Base, TimestampMixin):
    """Un anfitrión donde el CRM vive dentro de otra herramienta
    (CRM-00.02.03.10)."""

    __tablename__ = "embebidos"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(80), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # Dónde se embebe: el ERP, el portal del cliente, una herramienta de terceros.
    anfitrion: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    # Orígenes admitidos para embeber. Sin esta lista, cualquiera podría meter el
    # CRM en su página y pedirle datos con la sesión del usuario.
    origenes: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Qué le puede pedir el anfitrión: bloques declarados, no «lo que sea».
    bloques: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Cómo dice el anfitrión qué registro está mirando: {campo_externo:
    # campo_nuestro}. Sin esto, el CRM embebido enseña la pantalla de inicio en
    # vez del cliente que el usuario tiene delante, y entonces no sirve.
    contexto: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (UniqueConstraint("tenant_id", "clave", name="uq_embebido"),)


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def declarar_vista(
    uow: UnidadDeTrabajo,
    *,
    clave: str,
    objeto: str,
    campos: list[dict[str, Any]],
    nombre: str = "",
    instalacion_clave: str = "",
    operacion: str = "",
    clave_registro: str = "id",
    conexion_id: UUID | None = None,
    timeout_ms: int = 2000,
    cache_s: int = 60,
) -> tuple[VistaFederada, list[str]]:
    """Declara un bloque federado."""
    if not campos:
        raise ErrorValidacion(
            "Una vista federada sin campos no enseña nada.",
            error_code="federacion.sin_campos",
        )
    if not instalacion_clave and conexion_id is None:
        raise ErrorValidacion(
            "Hace falta decir de dónde salen los datos: una conexión o un conector " "instalado.",
            error_code="federacion.sin_origen",
        )
    avisos: list[str] = []
    if timeout_ms > 3000:
        avisos.append(
            f"Un tope de {timeout_ms} ms hace que la ficha tarde eso cuando el "
            "sistema externo va lento. Por encima de tres segundos, la gente cree "
            "que el CRM se ha colgado."
        )
    if cache_s > 900:
        avisos.append(
            f"Con {cache_s} s de caché, esto deja de ser un dato en vivo. Si puede "
            "quedarse viejo, quizá lo que toca es replicarlo y decirlo."
        )
    fila = VistaFederada(
        tenant_id=uow.tenant_id,
        clave=clave.strip(),
        nombre=nombre.strip() or clave.strip(),
        objeto=objeto.strip(),
        campos=list(campos),
        instalacion_clave=instalacion_clave,
        operacion=operacion,
        clave_registro=clave_registro,
        conexion_id=conexion_id,
        timeout_ms=timeout_ms,
        cache_s=cache_s,
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila, avisos


def componer(
    db: Session,
    tenant_id: UUID,
    *,
    objeto: str,
    registro: dict[str, Any],
    traer: Any = None,
    ahora: float | None = None,
) -> dict[str, Any]:
    """Compone los bloques federados de un registro (CRM-01.01.05.04).

    `traer` es la función que llama de verdad al sistema externo —el conector
    declarativo, normalmente—. Se pasa desde fuera para que este módulo no
    dependa del transporte, y para que en pruebas se pueda comprobar lo que
    importa: **qué se hace cuando el otro lado no contesta**.

    Y lo que se hace es decirlo: `disponible: false` con el porqué. Enseñar un
    hueco o un cero es peor que no enseñar nada — un saldo vacío se lee como «no
    debe nada».
    """
    momento = ahora if ahora is not None else time.monotonic()
    vistas = (
        db.execute(
            select(VistaFederada).where(
                VistaFederada.tenant_id == tenant_id,
                VistaFederada.objeto == objeto,
                VistaFederada.activa.is_(True),
            )
        )
        .scalars()
        .all()
    )
    bloques: list[dict[str, Any]] = []
    for vista in vistas:
        clave_valor = str(registro.get(vista.clave_registro) or "")
        if not clave_valor:
            bloques.append(
                {
                    "clave": vista.clave,
                    "nombre": vista.nombre,
                    "disponible": False,
                    "porque": (
                        f"El registro no trae «{vista.clave_registro}», que es con lo "
                        "que se consulta al sistema externo."
                    ),
                    "externo": True,
                }
            )
            continue

        entrada = _cache.get((str(tenant_id), vista.clave, clave_valor))
        if entrada is not None and entrada[1] > momento:
            datos, _, puesto_en = entrada
            bloques.append(
                {
                    "clave": vista.clave,
                    "nombre": vista.nombre,
                    "disponible": True,
                    "datos": datos,
                    "externo": True,
                    "de_cache": True,
                    # La edad, siempre. Un dato de hace diez minutos presentado
                    # como actual es el mismo problema que copiarlo.
                    "edad_s": round(momento - puesto_en, 1),
                    "consultado_at": _ahora().isoformat(),
                }
            )
            continue

        if traer is None:
            bloques.append(
                {
                    "clave": vista.clave,
                    "nombre": vista.nombre,
                    "disponible": False,
                    "porque": "No hay transporte configurado para consultar este bloque.",
                    "externo": True,
                }
            )
            continue

        try:
            crudo = traer(vista, clave_valor)
        except Exception as error:  # el transporte decide qué excepciones lanza
            logger.info("federacion.sin_respuesta", vista=vista.clave, error=str(error)[:200])
            bloques.append(
                {
                    "clave": vista.clave,
                    "nombre": vista.nombre,
                    "disponible": False,
                    # El porqué llega a la pantalla: «no se ha podido consultar» a
                    # secas manda a abrir un ticket que nadie sabe diagnosticar.
                    "porque": f"El sistema externo no ha contestado: {str(error)[:200]}",
                    "externo": True,
                }
            )
            continue

        datos = {
            str(campo.get("nombre")): (crudo or {}).get(
                str(campo.get("origen") or campo.get("nombre"))
            )
            for campo in (vista.campos or [])
        }
        if vista.cache_s > 0:
            _cache[(str(tenant_id), vista.clave, clave_valor)] = (
                datos,
                momento + vista.cache_s,
                momento,
            )
        bloques.append(
            {
                "clave": vista.clave,
                "nombre": vista.nombre,
                "disponible": True,
                "datos": datos,
                "externo": True,
                "de_cache": False,
                "edad_s": 0.0,
                "consultado_at": _ahora().isoformat(),
            }
        )

    return {
        "objeto": objeto,
        "bloques": bloques,
        "disponibles": len([b for b in bloques if b["disponible"]]),
        "no_disponibles": [b["clave"] for b in bloques if not b["disponible"]],
        # Se repite aquí porque es la pregunta siguiente de quien lo usa: no,
        # esto no se puede filtrar ni ordenar. Para eso habría que traerlo todo,
        # que es replicar con otro nombre.
        "filtrable": False,
        "aviso": (
            ""
            if all(b["disponible"] for b in bloques)
            else "Hay bloques que no se han podido consultar: la ficha está "
            "incompleta y no vacía."
        ),
    }


def declarar_embebido(
    uow: UnidadDeTrabajo,
    *,
    clave: str,
    anfitrion: str,
    origenes: list[str],
    bloques: list[str],
    contexto: dict[str, str] | None = None,
    nombre: str = "",
) -> Embebido:
    """Declara dónde puede vivir el CRM embebido (CRM-00.02.03.10).

    La lista de **orígenes es obligatoria**: sin ella, cualquiera podría meter el
    CRM en su página y pedirle datos con la sesión del usuario que lo abra. Es el
    mismo agujero que un CORS abierto, con la diferencia de que aquí lo que se
    enseña son los clientes.
    """
    if not origenes:
        raise ErrorValidacion(
            "Hace falta declarar desde qué orígenes se puede embeber: sin esa "
            "lista, cualquier página podría incrustarlo y pedir datos con la "
            "sesión de quien la abra.",
            error_code="federacion.sin_origenes",
        )
    malos = [o for o in origenes if not str(o).startswith("https://")]
    if malos:
        raise ErrorValidacion(
            f"Orígenes sin https: {malos}. Embeber por http deja la sesión al aire.",
            error_code="federacion.origen_inseguro",
        )
    if not bloques:
        raise ErrorValidacion(
            "Un embebido sin bloques declarados no enseñaría nada, o lo enseñaría "
            "todo: las dos cosas están mal.",
            error_code="federacion.sin_bloques",
        )
    fila = Embebido(
        tenant_id=uow.tenant_id,
        clave=clave.strip(),
        nombre=nombre.strip() or clave.strip(),
        anfitrion=anfitrion.strip(),
        origenes=list(origenes),
        bloques=list(bloques),
        contexto=dict(contexto or {}),
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila


def resolver_contexto(
    db: Session, tenant_id: UUID, *, clave: str, origen: str, parametros: dict[str, Any]
) -> dict[str, Any]:
    """Traduce lo que manda el anfitrión a lo que el CRM entiende.

    Se comprueba el **origen** primero: un embebido que acepta cualquier origen es
    una página de otro pidiendo datos con la sesión de tu usuario.

    Y si el anfitrión no manda el contexto declarado, se dice: el CRM embebido
    enseñando la pantalla de inicio en vez del cliente que el usuario tiene
    delante no sirve para nada, y quien lo integró tiene que poder saber qué le
    falta mandar.
    """
    fila = db.execute(
        select(Embebido).where(Embebido.tenant_id == tenant_id, Embebido.clave == clave)
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado("Ese embebido no existe", error_code="federacion.embebido_no_encontrado")
    if not fila.activo:
        return {"admitido": False, "porque": "Ese embebido está desactivado."}
    if origen not in (fila.origenes or []):
        logger.warning("federacion.origen_no_admitido", clave=clave, origen=origen)
        return {
            "admitido": False,
            # No se dice qué orígenes sí valen: sería decirle a quien prueba dónde
            # tiene que ponerse.
            "porque": "Origen no admitido para este embebido.",
        }

    traducido: dict[str, Any] = {}
    faltan: list[str] = []
    for externo, nuestro in (fila.contexto or {}).items():
        if externo in parametros:
            traducido[str(nuestro)] = parametros[externo]
        else:
            faltan.append(externo)
    return {
        "admitido": True,
        "anfitrion": fila.anfitrion,
        "contexto": traducido,
        "bloques": fila.bloques,
        "faltan_parametros": faltan,
        "completo": not faltan,
        "aviso": (
            ""
            if not faltan
            else f"El anfitrión no ha mandado {', '.join(faltan)}: el CRM no sabrá "
            "qué registro enseñar."
        ),
    }
