"""Idempotencia de escrituras mediante `Idempotency-Key` (CRM-00.02.01.08).

El problema real: un cliente manda `POST /opportunities`, la red se corta antes
de que llegue la respuesta, y el cliente reintenta. Sin idempotencia hay dos
oportunidades. Con ella, el segundo intento devuelve **la respuesta del primero**,
byte por byte, y no ejecuta nada.

Tres decisiones que hacen que esto funcione de verdad:

**Se guarda la respuesta, no solo la clave.** Devolver 409 al reintento obligaría
al cliente a averiguar si la primera vez funcionó. Devolver la respuesta
original le da exactamente lo que habría recibido si la red no hubiera fallado.

**Se comprueba el hash del cuerpo.** Si alguien reutiliza una clave con un cuerpo
distinto, es un error del cliente, no un reintento: se responde 409 y se dice.
Sin esta comprobación, reciclar una clave devolvería la respuesta de otra
operación como si fuera la suya.

**Se reserva la clave ANTES de ejecutar.** La fila se inserta al empezar, con
estado «en curso». Dos peticiones simultáneas con la misma clave: una inserta y
ejecuta, la otra choca con la clave primaria y espera o responde 409 «en curso».
Si se guardara al final, las dos ejecutarían.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy import DateTime, Integer, String, Text, delete, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Mapped, Session, mapped_column

from crmcore.db.base import Base
from crmcore.errors import Conflicto
from crmcore.http.deps import PrincipalDep
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Cuánto se recuerda una clave. Debe cubrir de sobra el tiempo durante el que un
# cliente razonable reintenta; 24 h cubre incluso un proceso por lotes que se
# retoma al día siguiente.
RETENCION_HORAS = 24


class ClaveIdempotencia(Base):
    __tablename__ = "claves_idempotencia"

    clave: Mapped[str] = mapped_column(String(200), primary_key=True)
    # Forma parte de la primaria: dos tenants pueden usar la misma clave sin
    # pisarse, y una clave de un tenant nunca devuelve la respuesta de otro.
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    metodo: Mapped[str] = mapped_column(String(10), nullable=False)
    ruta: Mapped[str] = mapped_column(String(400), nullable=False)
    hash_cuerpo: Mapped[str] = mapped_column(String(64), nullable=False)
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="en_curso")
    respuesta_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    respuesta_cuerpo: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


def hash_cuerpo(cuerpo: bytes) -> str:
    return hashlib.sha256(cuerpo).hexdigest()


def reservar(
    db: Session,
    *,
    clave: str,
    tenant_id: UUID,
    metodo: str,
    ruta: str,
    cuerpo: bytes,
) -> ClaveIdempotencia | None:
    """Reserva la clave. Devuelve `None` si es nueva; la fila previa si repetida.

    `None` significa «sigue, eres el primero». Una fila significa «esto ya pasó»:
    el llamante decide si devuelve la respuesta guardada o espera.
    """
    h = hash_cuerpo(cuerpo)
    # `RETURNING` y no `rowcount`. Con psycopg 3, el `rowcount` de un
    # `ON CONFLICT DO NOTHING` vuelve como **-1** —no 0, no 1— y `-1` es
    # verdadero en Python: `if res.rowcount:` daba SIEMPRE «la he insertado yo»,
    # así que esta función no detectó nunca un duplicado. El módulo llevaba así
    # desde que se escribió y no se veía porque no estaba enganchado a ninguna
    # ruta: la primera vez que se conectó de verdad, apareció.
    #
    # Con `RETURNING`, una inserción que no ocurre no devuelve filas. No hay
    # ambigüedad que depender del driver.
    insertada = (
        db.execute(
            pg_insert(ClaveIdempotencia)
            .values(
                clave=clave,
                tenant_id=tenant_id,
                metodo=metodo,
                ruta=ruta,
                hash_cuerpo=h,
                estado="en_curso",
            )
            .on_conflict_do_nothing(index_elements=["clave", "tenant_id"])
            .returning(ClaveIdempotencia.clave)
        ).first()
        is not None
    )
    if insertada:
        return None

    previa = db.get(ClaveIdempotencia, {"clave": clave, "tenant_id": tenant_id})
    if previa is None:  # pragma: no cover — carrera improbable con la purga
        return None

    if previa.hash_cuerpo != h:
        raise Conflicto(
            "Esa clave de idempotencia ya se usó con un cuerpo distinto. Usa una "
            "clave nueva para una operación nueva.",
            error_code="idempotencia.cuerpo_distinto",
        )
    if previa.metodo != metodo or previa.ruta != ruta:
        raise Conflicto(
            "Esa clave de idempotencia ya se usó en otra operación",
            error_code="idempotencia.operacion_distinta",
        )
    return previa


def completar(
    db: Session,
    *,
    clave: str,
    tenant_id: UUID,
    status: int,
    cuerpo: dict[str, Any] | None,
) -> None:
    """Guarda la respuesta para que el reintento la reciba igual."""
    fila = db.get(ClaveIdempotencia, {"clave": clave, "tenant_id": tenant_id})
    if fila is None:  # pragma: no cover
        return
    fila.estado = "completada"
    fila.respuesta_status = status
    fila.respuesta_cuerpo = cuerpo


def fallar(db: Session, *, clave: str, tenant_id: UUID, error: str) -> None:
    """Libera la clave cuando la operación falló.

    Se **borra**, no se marca como fallida: si la operación no llegó a ocurrir,
    el cliente tiene todo el derecho a reintentar con la misma clave. Dejarla
    bloqueada le obligaría a inventar una clave nueva para reintentar algo que
    nunca pasó.
    """
    db.execute(
        delete(ClaveIdempotencia).where(
            ClaveIdempotencia.clave == clave,
            ClaveIdempotencia.tenant_id == tenant_id,
        )
    )
    logger.info("idempotencia.liberada_por_fallo", error=error[:200])


def purgar(db: Session, *, horas: int = RETENCION_HORAS) -> int:
    limite = datetime.now(timezone.utc) - timedelta(hours=horas)
    res = db.execute(delete(ClaveIdempotencia).where(ClaveIdempotencia.created_at < limite))
    return int(res.rowcount or 0)


class RespuestaRepetida(Exception):
    """La operación ya se hizo: se devuelve lo mismo que la primera vez.

    Es una excepción y no un `return` porque se lanza desde una dependencia, y
    una dependencia no puede responder: lo que puede es cortar. Un manejador la
    traduce en la respuesta guardada.
    """

    def __init__(self, status: int, cuerpo: Any) -> None:
        self.status = status or 200
        self.cuerpo = cuerpo
        super().__init__("respuesta idempotente repetida")


async def dependencia(request: Request, principal: "PrincipalDep") -> None:
    """Reserva la clave de idempotencia, si la petición trae una.

    **Es una dependencia y no un middleware**, y la diferencia importa: el
    middleware corre antes de la autenticación, así que allí el tenant todavía
    no se conoce. Usar la pista de la cabecera sin verificar habría parecido que
    funcionaba y habría sido una fuga — quien mintiera sobre su tenant podría
    recibir la respuesta guardada de otro cliente, con su contenido dentro.

    Se monta **global** en `crear_servicio`, no ruta a ruta. Son más de cien
    rutas de escritura: engancharlo una a una significa que funciona en las que
    alguien se acordó, y el integrador descubre cuáles son reintentando un
    cobro. Un contrato de API que vale «en casi todas partes» no es un contrato.

    Sin cabecera no hace nada. Exigirla siempre rompería a todo cliente que hoy
    funciona, y decidir si una operación se puede reintentar es de quien llama.

    El tipo de `request` **tiene que ser `Request`**, no `Any`: FastAPI resuelve
    las dependencias por anotación, y con `Any` lo toma por un parámetro de
    consulta obligatorio — toda escritura empezaría a responder 422 pidiendo un
    campo llamado «request».

    Y depende del **principal**, no del contexto. Las dependencias globales
    corren ANTES que las de ruta, así que al leer el contexto directamente el
    tenant todavía era `None` y la idempotencia no hacía nada — en silencio, que
    es lo peor: parecía montada. Pidiendo el principal, FastAPI resuelve primero
    la autenticación y el tenant llega verificado.
    """
    if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
        return

    clave = (request.headers.get("idempotency-key") or "").strip()
    if not clave or len(clave) > 200:
        # Una clave absurdamente larga se ignora en vez de rechazarse: el
        # objetivo es no romper a quien manda basura en una cabecera opcional.
        return

    tenant_id = principal.tenant_id
    if tenant_id is None:
        # Sin identidad verificada no hay dónde guardar la clave sin cruzarla
        # con la de otro cliente. Se sigue sin idempotencia antes que eso.
        return

    cuerpo = await request.body()

    from crmcore.db.session import nueva_sesion

    db = nueva_sesion(tenant_id)
    try:
        previa = reservar(
            db,
            clave=clave,
            tenant_id=tenant_id,
            metodo=request.method,
            ruta=request.url.path,
            cuerpo=cuerpo,
        )
        # Se confirma SIEMPRE, también cuando es nueva: es lo que hace que un
        # reintento simultáneo vea la reserva en vez de repetir el trabajo.
        db.commit()
    except Conflicto:
        db.rollback()
        raise
    except Exception as exc:  # noqa: BLE001
        # Un fallo de la tabla auxiliar no puede impedir una escritura legítima:
        # se degrada a «sin idempotencia», que es peor que tenerla pero mucho
        # mejor que rechazar la operación.
        db.rollback()
        logger.error("idempotencia.fallo_al_reservar", error=str(exc)[:200])
        return
    finally:
        db.close()

    if previa is not None:
        if previa.estado == "completada":
            raise RespuestaRepetida(previa.respuesta_status or 200, previa.respuesta_cuerpo)
        # En curso: otra petición con la misma clave se está ejecutando ahora.
        # Se responde 409 en vez de esperar — esperar convierte un reintento en
        # dos conexiones abiertas durante el mismo trabajo lento.
        raise Conflicto(
            "Esa operación ya se está ejecutando con la misma clave",
            error_code="idempotencia.en_curso",
        )

    # Se deja la reserva para que el middleware guarde la respuesta al terminar.
    # Una dependencia no ve el cuerpo de la respuesta; el middleware sí.
    request.scope.setdefault("state", {})["idempotencia"] = {
        "clave": clave,
        "tenant_id": tenant_id,
    }
