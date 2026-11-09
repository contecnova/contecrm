"""Lo que el asistente puede HACER, de una lista cerrada, y sólo confirmado
(CRM-04.03.02.02).

**Lo que había, medido el 09-11-2026.** `POST /ia/asistencia/conversar`
devolvía «acciones propuestas» que eran las que el llamante le pasaba y cuyo
nombre aparecía en el texto, y no ejecutaba ninguna. Un asistente
«transaccional» que no podía hacer nada.

Ahora el asistente propone **una** acción de esta lista, con sus argumentos, y
se ejecuta cuando la persona la confirma:

- **Lista cerrada.** Lo que el modelo puede pedir está escrito aquí, con su
  ruta, su permiso y sus campos. Un modelo al que se le deja elegir cualquier
  ruta de la API acaba borrando algo por una frase mal entendida.
- **Con la identidad de quien pregunta.** Se ejecuta por la API del CRM con sus
  permisos y su compartición: el servicio de destino aplica sus reglas como si
  lo hubiera pulsado él. Si no puede, el destino dice que no, y se enseña.
- **Confirmación explícita.** Lo propuesto se guarda y no pasa nada hasta que
  la persona lo confirma —puede corregir los argumentos antes—. Una acción
  propuesta caduca: confirmar mañana algo que se propuso con el contexto de
  ayer es actuar a ciegas.
- **Sólo con los argumentos declarados.** Lo que el modelo añada de más se
  tira; un campo obligatorio que falte se pide en vez de inventarlo.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from crmcore.audit import registrar
from crmcore.db.base import Base, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado, Prohibido
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import DateTime, Index, Integer, String, Text, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

logger = get_logger(__name__)

# La lista cerrada. Cada acción: qué hace, a qué ruta va, qué permiso exige,
# qué va fijo y qué campos puede rellenar el modelo (y cuáles son obligatorios).
ACCIONES: dict[str, dict[str, Any]] = {
    "crear_tarea": {
        "nombre": "Crear una tarea",
        "metodo": "POST",
        "ruta": "/api/v1/activities",
        "permiso": "activity:write",
        "fijos": {"tipo": "tarea"},
        "campos": {
            "asunto": {"tipo": "texto", "obligatorio": True},
            "cuerpo": {"tipo": "texto"},
            "vence_at": {"tipo": "fecha_hora"},
            "objeto": {"tipo": "texto", "opciones": ["cuenta", "contacto", "oportunidad", "caso"]},
            "objeto_id": {"tipo": "uuid"},
        },
    },
    "registrar_nota": {
        "nombre": "Registrar una nota",
        "metodo": "POST",
        "ruta": "/api/v1/activities",
        "permiso": "activity:write",
        "fijos": {"tipo": "nota"},
        "campos": {
            "asunto": {"tipo": "texto", "obligatorio": True},
            "cuerpo": {"tipo": "texto"},
            "objeto": {"tipo": "texto", "opciones": ["cuenta", "contacto", "oportunidad", "caso"]},
            "objeto_id": {"tipo": "uuid"},
        },
    },
    "abrir_caso": {
        "nombre": "Abrir un caso",
        "metodo": "POST",
        "ruta": "/api/v1/casos",
        "permiso": "case:write",
        "fijos": {},
        "campos": {
            "asunto": {"tipo": "texto", "obligatorio": True},
            "descripcion": {"tipo": "texto"},
            "prioridad": {"tipo": "texto"},
            "cuenta_id": {"tipo": "uuid"},
        },
    },
    "capturar_lead": {
        "nombre": "Capturar un lead",
        "metodo": "POST",
        "ruta": "/api/v1/leads",
        "permiso": "lead:write",
        "fijos": {},
        "campos": {
            "empresa": {"tipo": "texto", "obligatorio": True},
            "nombre": {"tipo": "texto"},
            "apellidos": {"tipo": "texto"},
            "email": {"tipo": "texto"},
            "telefono": {"tipo": "texto"},
        },
    },
}

ESTADOS = ("propuesta", "ejecutada", "fallida", "descartada")


class AccionAsistente(Base, TimestampMixin):
    """Una acción que el asistente propuso, y lo que pasó con ella."""

    __tablename__ = "acciones_asistente"
    __table_args__ = (Index("ix_acciones_asistente", "tenant_id", "usuario_id", "estado"),)

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    usuario_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    pregunta: Mapped[str] = mapped_column(Text, nullable=False, default="")
    accion: Mapped[str] = mapped_column(
        String(40), nullable=False, info={"opciones": tuple(ACCIONES)}
    )
    argumentos: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    porque: Mapped[str] = mapped_column(Text, nullable=False, default="")
    estado: Mapped[str] = mapped_column(
        String(20), nullable=False, default="propuesta", info={"opciones": ESTADOS}
    )
    caduca_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ejecutada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Lo que contestó el destino: su código y el registro creado. Es lo que
    # permite ir a ver lo que se hizo en nombre de quien confirmó.
    codigo_respuesta: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resultado: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )


_proponedor: Callable[..., dict[str, Any]] | None = None
_ejecutor: Callable[..., dict[str, Any]] | None = None


def registrar_proponedor(fn: Callable[..., dict[str, Any]] | None) -> None:
    global _proponedor
    _proponedor = fn


def registrar_ejecutor(fn: Callable[..., dict[str, Any]] | None) -> None:
    """Las pruebas sustituyen la llamada HTTP por un doble."""
    global _ejecutor
    _ejecutor = fn


def disponibles(principal: Any) -> list[dict[str, Any]]:
    """Las acciones que ESTA persona puede pedir. Las demás no se le ofrecen al modelo."""
    tiene = getattr(principal, "tiene", None)
    return [
        {"clave": k, "nombre": v["nombre"], "campos": v["campos"]}
        for k, v in ACCIONES.items()
        if callable(tiene) and tiene(v["permiso"])
    ]


def limpiar(clave: str, argumentos: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Sólo los campos declarados, sin vacíos; y los obligatorios que faltan."""
    campos = ACCIONES[clave]["campos"]
    limpios = {
        k: v for k, v in (argumentos or {}).items() if k in campos and v not in (None, "", [])
    }
    for k, v in list(limpios.items()):
        definicion = campos[k]
        opciones = definicion.get("opciones")
        if opciones and str(v) not in opciones:
            limpios.pop(k)
        elif definicion.get("tipo") == "uuid":
            try:
                limpios[k] = str(UUID(str(v)))
            except ValueError:
                # Un identificador inventado por el modelo («la cuenta de
                # Plásticos Ebro») no es un identificador: fuera.
                limpios.pop(k)
    if "objeto" in limpios and "objeto_id" not in limpios:
        # Colgar algo «de una cuenta» sin decir cuál no cuelga de nada.
        limpios.pop("objeto")
    faltan = [k for k, d in campos.items() if d.get("obligatorio") and k not in limpios]
    return limpios, faltan


def proponer(
    uow: UnidadDeTrabajo, *, pregunta: str, respuesta: str, principal: Any
) -> dict[str, Any] | None:
    """Pide al modelo si hace falta una acción de la lista, y la guarda propuesta."""
    from services.intelligence import enrutador, uso
    from services.intelligence.ajustes import ajustes

    ofrecidas = disponibles(principal)
    if not ofrecidas or _proponedor is None:
        return None
    elegido = enrutador.exigir_disponible(uow.db, uow.tenant_id, uso="consulta")
    inicio = datetime.now(timezone.utc)
    salida = _proponedor(
        proveedor=elegido["elegido"],
        modelo=elegido.get("modelo", ""),
        pregunta=pregunta,
        respuesta=respuesta,
        acciones=ofrecidas,
        opt_out=bool(elegido.get("opt_out")),
    )
    clave = str(salida.get("accion") or "")
    uso.anotar(
        uow,
        tarea="asistente_accion",
        proveedor=str(elegido.get("elegido") or ""),
        modelo=str(salida.get("modelo") or elegido.get("modelo") or ""),
        region=str(elegido.get("region") or ""),
        usuario_id=getattr(principal, "id", None),
        prompt=pregunta,
        tokens_entrada=int(salida.get("tokens_entrada") or 0),
        tokens_salida=int(salida.get("tokens_salida") or 0),
        coste=enrutador.coste_estimado(
            uow.db,
            proveedor=str(elegido.get("elegido") or ""),
            tokens_entrada=int(salida.get("tokens_entrada") or 0),
            tokens_salida=int(salida.get("tokens_salida") or 0),
        ),
        duracion_ms=int((datetime.now(timezone.utc) - inicio).total_seconds() * 1000),
        resultado="aceptada" if clave else "sin_respuesta",
        opt_out=bool(elegido.get("opt_out")),
    )
    if clave not in {a["clave"] for a in ofrecidas}:
        # Ninguna, o una que no está en la lista o que esta persona no puede:
        # no se propone nada. Inventarse una acción no es un acierto a medias.
        return None
    argumentos, faltan = limpiar(clave, dict(salida.get("argumentos") or {}))
    fila = AccionAsistente(
        tenant_id=uow.tenant_id,
        usuario_id=principal.id,
        pregunta=pregunta[:4000],
        accion=clave,
        argumentos=argumentos,
        porque=str(salida.get("porque") or "")[:2000],
        caduca_at=datetime.now(timezone.utc)
        + timedelta(hours=int(ajustes().ia_asistente_caducidad_horas)),
    )
    uow.db.add(fila)
    uow.db.flush()
    return _a_dict(fila, faltan=faltan)


def _a_dict(fila: AccionAsistente, faltan: list[str] | None = None) -> dict[str, Any]:
    definicion = ACCIONES.get(fila.accion, {})
    return {
        "id": str(fila.id),
        "accion": fila.accion,
        "nombre": definicion.get("nombre", fila.accion),
        "argumentos": fila.argumentos,
        "campos": definicion.get("campos", {}),
        "fijos": definicion.get("fijos", {}),
        "ruta": f"{definicion.get('metodo', '')} {definicion.get('ruta', '')}",
        "porque": fila.porque,
        "estado": fila.estado,
        "faltan": faltan if faltan is not None else limpiar(fila.accion, fila.argumentos)[1],
        "caduca_at": fila.caduca_at.isoformat() if fila.caduca_at else None,
        "codigo_respuesta": fila.codigo_respuesta,
        "resultado": fila.resultado,
    }


def ejecutar(
    uow: UnidadDeTrabajo,
    *,
    accion_id: UUID,
    principal: Any,
    confirmar: bool,
    argumentos: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Ejecuta lo propuesto, si lo confirma quien lo pidió. O lo descarta."""
    fila = uow.db.execute(
        select(AccionAsistente).where(
            AccionAsistente.id == accion_id, AccionAsistente.tenant_id == uow.tenant_id
        )
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado("Esa acción no existe", error_code="asistente.accion_no_encontrada")
    if fila.usuario_id != principal.id:
        # Confirma quien la pidió: la propuesta salió de SU pregunta y de lo
        # que ÉL puede hacer.
        raise Prohibido(
            "Sólo puede confirmarla quien hizo la pregunta.", error_code="asistente.no_es_tuya"
        )
    if fila.estado != "propuesta":
        raise Conflicto(
            f"Esta acción ya está {fila.estado}.",
            error_code="asistente.ya_decidida",
            detalle={"estado": fila.estado},
        )
    caduca = (
        fila.caduca_at if fila.caduca_at.tzinfo else fila.caduca_at.replace(tzinfo=timezone.utc)
    )
    if caduca < datetime.now(timezone.utc):
        raise Conflicto(
            "La propuesta ha caducado: vuelve a preguntar, con el contexto de ahora.",
            error_code="asistente.caducada",
        )
    if not confirmar:
        fila.estado = "descartada"
        uow.db.flush()
        return _a_dict(fila)

    definicion = ACCIONES[fila.accion]
    limpios, faltan = limpiar(fila.accion, {**fila.argumentos, **(argumentos or {})})
    if faltan:
        raise ErrorValidacion(
            "Faltan datos para hacerlo: " + ", ".join(faltan),
            error_code="asistente.faltan_datos",
            detalle={"faltan": faltan},
        )
    if not principal.tiene(definicion["permiso"]):
        raise Prohibido(
            f"No tienes «{definicion['permiso']}», que es lo que exige esta acción.",
            error_code="asistente.sin_permiso",
        )
    cuerpo = {**limpios, **definicion["fijos"]}
    if _ejecutor is not None:
        r = _ejecutor(metodo=definicion["metodo"], ruta=definicion["ruta"], cuerpo=cuerpo)
    else:
        from crmcore.http.interno import invocar

        from services.intelligence.predictivo import identidad_de

        r = invocar(
            metodo=definicion["metodo"],
            ruta=definicion["ruta"],
            cuerpo=cuerpo,
            idempotencia=f"asistente-{fila.id}",
            **identidad_de(principal),
        )
    codigo = int(r.get("estado") or 0)
    datos = r.get("datos") if isinstance(r.get("datos"), dict) else {"respuesta": r.get("datos")}
    fila.argumentos = limpios
    fila.codigo_respuesta = codigo
    fila.resultado = {
        "id": str((datos or {}).get("id") or ""),
        "detalle": str((datos or {}).get("detail") or "")[:500],
    }
    fila.estado = "ejecutada" if 200 <= codigo < 300 else "fallida"
    fila.ejecutada_at = datetime.now(timezone.utc)
    uow.db.flush()
    registrar(
        uow.db,
        accion="asistente.accion_ejecutada",
        objeto="accion_asistente",
        objeto_id=fila.id,
        datos={"accion": fila.accion, "codigo": codigo, "creado": fila.resultado.get("id")},
        tenant_id=uow.tenant_id,
    )
    return _a_dict(fila)


def mias(db: Any, tenant_id: UUID, usuario_id: UUID, limite: int = 20) -> list[dict[str, Any]]:
    filas = (
        db.execute(
            select(AccionAsistente)
            .where(AccionAsistente.tenant_id == tenant_id, AccionAsistente.usuario_id == usuario_id)
            .order_by(AccionAsistente.created_at.desc())
            .limit(limite)
        )
        .scalars()
        .all()
    )
    return [_a_dict(f) for f in filas]
