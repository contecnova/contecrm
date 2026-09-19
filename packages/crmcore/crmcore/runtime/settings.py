"""Resolución de ajustes en caliente, con caché y jerarquía.

    from crmcore.runtime import settings as rt

    tope = rt.efectivo("bulk_max_items")

`efectivo()` recorre la jerarquía de abajo arriba (usuario → BU → tenant → tier
→ global) y, si nadie lo ha fijado, cae al valor de `.env`. Nunca devuelve
`None` para una clave declarada: siempre hay un default.

**La caché y su invalidación.** Resolver esto con una consulta por lectura
pondría una consulta más en cada petición para leer un número que cambia una vez
al mes. Se cachea con TTL corto **y** se invalida por evento al escribir, porque
solo con TTL un cambio tarda hasta un minuto en verse en todas las réplicas y el
administrador cree que no se ha guardado. Con las dos cosas, el caso normal es
instantáneo y el TTL es la red por si se pierde el evento.
"""

from __future__ import annotations

import hashlib
import threading
import time
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, Index, String, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Mapped, Session, mapped_column

from crmcore.db.base import Base
from crmcore.logging import get_logger
from crmcore.runtime.keys import CLAVES, ORDEN_AMBITOS, Ambito, ambito_permitido, validar

logger = get_logger(__name__)

# Vida de la caché. Corta porque la invalidación por evento es la vía normal y
# esto es solo la red de seguridad; larga como para ahorrar la consulta en una
# ráfaga de peticiones.
TTL_CACHE_S = 30.0


class AjusteRuntime(Base):
    """Valor de un ajuste fijado en un ámbito concreto."""

    __tablename__ = "ajustes_runtime"

    clave: Mapped[str] = mapped_column(String(120), primary_key=True)
    ambito: Mapped[str] = mapped_column(String(20), primary_key=True)
    # Cadena vacía en el ámbito global, que no tiene sujeto. Se usa cadena y no
    # NULL porque NULL en una clave primaria no compara como se espera y haría
    # que el ámbito global pudiera duplicarse.
    ambito_id: Mapped[str] = mapped_column(String(80), primary_key=True, default="")
    valor: Mapped[Any] = mapped_column(JSONB, nullable=False)
    actualizado_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_ajustes_ambito", "ambito", "ambito_id"),)


_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_lock = threading.Lock()

# Proveedor de los ajustes PROPIOS del servicio. Sin esto, `efectivo()` solo
# miraba el `Settings` común, y un ajuste declarado por un servicio —el umbral
# de deduplicación, por ejemplo— resolvía a `None` cuando nadie lo había fijado
# en la base: el código lo interpretaba como «desactivado» y la deduplicación
# por identificador fiscal no se aplicaba nunca. Se descubrió con la prueba de
# duplicados, no leyendo el código.
_ajustes_servicio: Any = None


def registrar_ajustes_servicio(proveedor: Any) -> None:
    """Declara de dónde salen los ajustes propios de este servicio.

    `proveedor` es un invocable sin argumentos que devuelve el objeto de
    configuración del servicio (normalmente su `ajustes()` cacheado).
    """
    global _ajustes_servicio
    _ajustes_servicio = proveedor


def _clave_cache(ambito: str, ambito_id: str) -> str:
    return f"{ambito}:{ambito_id}"


def _valores_de_ambito(db: Session, ambito: str, ambito_id: str) -> dict[str, Any]:
    """Todos los ajustes de un ámbito, cacheados.

    Se traen TODOS los de ese ámbito de una vez y no clave a clave: son pocas
    filas y así una petición que consulta cinco ajustes hace una consulta, no
    cinco.
    """
    clave = _clave_cache(ambito, ambito_id)
    ahora = time.monotonic()
    guardado = _cache.get(clave)
    if guardado and ahora - guardado[0] < TTL_CACHE_S:
        return guardado[1]

    filas = db.execute(
        select(AjusteRuntime.clave, AjusteRuntime.valor).where(
            AjusteRuntime.ambito == ambito, AjusteRuntime.ambito_id == ambito_id
        )
    ).all()
    valores = {k: v for k, v in filas}
    with _lock:
        _cache[clave] = (ahora, valores)
    return valores


def efectivo(clave: str, db: Session | None = None, *, default: Any = None) -> Any:
    """Valor efectivo del ajuste para el contexto en curso.

    Sin sesión de base de datos devuelve el valor de `.env` sin consultar. Eso
    permite llamarlo desde código que no tiene sesión (un middleware, el
    arranque) sin abrir una conexión solo para leer un número.
    """
    from crmcore.config import get_settings
    from crmcore.tenancy.context import contexto_actual

    decl = CLAVES.get(clave)
    s = get_settings()
    por_defecto = default
    if por_defecto is None and decl and decl.campo_settings:
        por_defecto = getattr(s, decl.campo_settings, None)
        if por_defecto is None and _ajustes_servicio is not None:
            # El ajuste lo declara el servicio, no el núcleo: se busca en su
            # propia configuración antes de darlo por inexistente.
            try:
                por_defecto = getattr(_ajustes_servicio(), decl.campo_settings, None)
            except Exception:  # noqa: BLE001 — leer un default nunca debe romper la petición
                por_defecto = None

    if db is None:
        return por_defecto

    ctx = contexto_actual()
    # De más específico a más general: el primero que lo tenga fijado, gana.
    candidatos: list[tuple[str, str]] = []
    if ctx.user_id:
        candidatos.append(("usuario", str(ctx.user_id)))
    if ctx.business_unit_id:
        candidatos.append(("bu", str(ctx.business_unit_id)))
    if ctx.tenant_id:
        candidatos.append(("tenant", str(ctx.tenant_id)))
    tier = ctx.extra.get("tier")
    if tier:
        candidatos.append(("tier", str(tier)))
    candidatos.append(("global", ""))

    for ambito, ambito_id in candidatos:
        valores = _valores_de_ambito(db, ambito, ambito_id)
        if clave in valores:
            return valores[clave]
    return por_defecto


AJUSTE_CAMBIADO = "configuracion.ajuste_cambiado"


def _declarar_evento() -> None:
    """Declara el evento de cambio de ajuste en el catálogo, una sola vez.

    Se declara aquí y no en el `eventos.py` de un servicio porque el productor
    es el núcleo: lo emite cualquier servicio en el que se escriba un ajuste, y
    darle dueño a uno concreto sería mentir sobre quién lo publica.
    """
    from crmcore.events.catalogo import TipoEvento, obtener, registrar

    if obtener(AJUSTE_CAMBIADO) is not None:
        return
    registrar(
        TipoEvento(
            tipo=AJUSTE_CAMBIADO,
            version=1,
            productor="core",
            descripcion=(
                "Un ajuste en caliente ha cambiado de valor en un ámbito. "
                "Lo consumen TODOS los servicios para replicarlo en su esquema"
            ),
            campos=("clave", "ambito", "ambito_id", "valor", "quitado"),
        )
    )


def fijar(
    db: Session,
    clave: str,
    valor: Any,
    *,
    ambito: Ambito = "tenant",
    ambito_id: str = "",
    por: UUID | None = None,
) -> Any:
    """Fija un ajuste en un ámbito. Valida, audita e invalida la caché."""
    from crmcore.audit.chain import registrar
    from crmcore.errors import ErrorValidacion

    if not ambito_permitido(clave, ambito):
        decl = CLAVES.get(clave)
        raise ErrorValidacion(
            f"El ajuste «{clave}» no se puede fijar por {ambito}"
            + (f"; su ámbito más específico es «{decl.minimo_ambito}»" if decl else ""),
            error_code="ajustes.ambito_no_permitido",
        )

    convertido = validar(clave, valor)
    anterior = efectivo(clave, db)

    db.execute(
        pg_insert(AjusteRuntime)
        .values(
            clave=clave,
            ambito=ambito,
            ambito_id=ambito_id,
            valor=convertido,
            actualizado_por=por,
        )
        .on_conflict_do_update(
            index_elements=["clave", "ambito", "ambito_id"],
            set_={"valor": convertido, "actualizado_por": por, "updated_at": func.now()},
        )
    )

    # Auditar el cambio de configuración es obligatorio (CRM-00.05.04.03): la
    # mitad de los incidentes de «esto antes funcionaba» son un ajuste que
    # alguien cambió y nadie recuerda.
    registrar(
        db,
        accion="ajuste.cambiado",
        objeto="ajuste",
        objeto_id=clave,
        datos={
            "ambito": ambito,
            "ambito_id": ambito_id,
            "anterior": anterior,
            "nuevo": convertido,
            "sensible": bool(CLAVES[clave].sensible),
        },
    )
    _propagar(db, clave=clave, ambito=ambito, ambito_id=ambito_id, valor=convertido)
    invalidar(ambito, ambito_id)
    return convertido


def quitar(db: Session, clave: str, *, ambito: Ambito = "tenant", ambito_id: str = "") -> None:
    """Quita el valor de un ámbito: vuelve a heredar del de encima."""
    from sqlalchemy import delete

    db.execute(
        delete(AjusteRuntime).where(
            AjusteRuntime.clave == clave,
            AjusteRuntime.ambito == ambito,
            AjusteRuntime.ambito_id == ambito_id,
        )
    )
    _propagar(db, clave=clave, ambito=ambito, ambito_id=ambito_id, valor=None, quitado=True)
    invalidar(ambito, ambito_id)


def _propagar(
    db: Session,
    *,
    clave: str,
    ambito: str,
    ambito_id: str,
    valor: Any,
    quitado: bool = False,
) -> None:
    """Publica el cambio para que lo apliquen los demás servicios.

    **Esto faltaba, y era un fallo de los que no se ven.** La tabla
    `ajustes_runtime` vive en el esquema de CADA servicio —ninguno lee el de
    otro— así que un ajuste escrito desde la consola de administración se
    guardaba solo en el esquema de `tenancy`. `party` seguía formateando las
    fechas con el valor de `.env` para siempre, y el administrador veía su
    cambio guardado. Nadie lo llamaba avería: simplemente no pasaba nada.

    El comentario de `invalidar` decía que las réplicas se enteraban «por el
    evento `ajuste.cambiado` del bus», y ese evento **no lo emitía nadie**: solo
    existía como acción de auditoría con ese nombre.

    Va por la tabla de salida, en la misma transacción que la escritura: o se
    guarda el ajuste y sale el evento, o no pasa ninguna de las dos cosas.
    """
    from crmcore.bus.outbox import encolar
    from crmcore.tenancy.context import contexto_actual

    _declarar_evento()
    tenant_id = contexto_actual().tenant_id
    if ambito == "tenant" and ambito_id:
        # El ámbito manda sobre el contexto: un administrador de plataforma
        # puede fijar un ajuste de un tenant desde fuera de él, y el evento
        # tiene que ir marcado con el tenant afectado, no con el del que escribe.
        try:
            tenant_id = UUID(str(ambito_id))
        except ValueError:
            pass
    encolar(
        db,
        tenant_id=tenant_id,
        tipo=AJUSTE_CAMBIADO,
        subject_tipo="ajuste",
        subject_id=clave,
        data={
            "clave": clave,
            "ambito": ambito,
            "ambito_id": ambito_id,
            "valor": valor,
            "quitado": quitado,
        },
        # La clave de deduplicación sale del HECHO, no del instante: dos
        # escrituras del mismo valor en el mismo ámbito son el mismo hecho, y
        # aplicarlo dos veces es inocuo pero anotarlo dos veces confunde.
        #
        # Va resumida porque la columna son 64 caracteres y el hecho en claro
        # —clave, ámbito, sujeto y valor— se pasa enseguida: un ajuste con un
        # valor largo, como la política de sensibilidad, ocupa cientos. El
        # prefijo se deja legible para poder buscar en la cola a ojo.
        dedup_key="cfg:"
        + hashlib.sha256(f"{ambito}|{ambito_id}|{clave}|{valor!r}|{quitado}".encode()).hexdigest()[
            :56
        ],
    )


async def consumir_ajuste(mensaje: Any) -> None:
    """Aplica en ESTE servicio un ajuste cambiado en otro.

    Lo registra `crear_servicio` en todos los servicios, sin que ninguno tenga
    que acordarse: un servicio que no lo consumiera se quedaría con la
    configuración de su `.env` mientras el resto del sistema usa la del cliente,
    y esa divergencia es de las que tardan semanas en atribuirse.

    Es idempotente: escribe el valor tal cual y vacía su caché. Recibirlo dos
    veces —la entrega es at-least-once— deja el mismo estado.
    """
    # El mensaje llega como `Evento` desde NATS y como diccionario desde el bus
    # en memoria. Se admiten los dos, y del diccionario se saca `data` si lo
    # trae: tratarlo entero como el contenido dejaba el consumidor sin hacer
    # nada y sin decirlo, que es el peor resultado posible para algo que
    # replica configuración.
    if isinstance(mensaje, dict):
        datos = mensaje.get("data") if isinstance(mensaje.get("data"), dict) else mensaje
    else:
        datos = getattr(mensaje, "data", None) or {}
    clave = str(datos.get("clave") or "")
    if clave not in CLAVES:
        # Una clave que este servicio no conoce: una versión más nueva la
        # declaró. Se ignora sin ruido en vez de fallar, porque fallar llenaría
        # la cola de mensajes correctos.
        return

    ambito = str(datos.get("ambito") or "tenant")
    ambito_id = str(datos.get("ambito_id") or "")
    from crmcore.db.uow import unidad_de_trabajo

    with unidad_de_trabajo(sistema=True) as uow:
        _aplicar_local(
            uow.db,
            clave=clave,
            ambito=ambito,
            ambito_id=ambito_id,
            valor=datos.get("valor"),
            quitado=bool(datos.get("quitado")),
        )
    invalidar(ambito, ambito_id)


def _aplicar_local(
    db: Session, *, clave: str, ambito: str, ambito_id: str, valor: Any, quitado: bool
) -> None:
    """Escribe el valor recibido SIN volver a propagarlo.

    Separado de `fijar` a propósito: si el consumidor llamara a `fijar`, cada
    servicio reemitiría el evento al aplicarlo y el bus entraría en un bucle que
    crece con el número de servicios.
    """
    from sqlalchemy import delete

    if quitado:
        db.execute(
            delete(AjusteRuntime).where(
                AjusteRuntime.clave == clave,
                AjusteRuntime.ambito == ambito,
                AjusteRuntime.ambito_id == ambito_id,
            )
        )
        return
    db.execute(
        pg_insert(AjusteRuntime)
        .values(clave=clave, ambito=ambito, ambito_id=ambito_id, valor=valor)
        .on_conflict_do_update(
            index_elements=["clave", "ambito", "ambito_id"],
            set_={"valor": valor, "updated_at": func.now()},
        )
    )


def invalidar(ambito: str = "", ambito_id: str = "") -> None:
    """Invalida la caché local. Sin argumentos, la vacía entera.

    Invalida **este proceso**. Los demás —otras réplicas y otros servicios— se
    enteran por el evento `configuracion.ajuste_cambiado`, que ahora se emite de
    verdad (ver `_propagar`); y si el evento se pierde, por el TTL.
    """
    with _lock:
        if ambito:
            _cache.pop(_clave_cache(ambito, ambito_id), None)
        else:
            _cache.clear()


def _invalidar_por_tenant(tenant_id: str | None) -> None:
    """Invalidador registrado en el registro de cachés del núcleo.

    Vacía la caché ENTERA aunque se purgue un solo tenant. Es deliberado: las
    entradas se guardan por ámbito (`tenant:<id>`, `bu:<id>`, `usuario:<id>`),
    así que purgar de verdad lo de un tenant exigiría saber qué unidades y qué
    usuarios son suyos, que es información de otro servicio. Vaciar de más
    cuesta unas consultas; vaciar de menos deja dato de un cliente dado de baja
    sirviéndose desde memoria.
    """
    invalidar()


from crmcore.cache.registro import registrar as _registrar_invalidador  # noqa: E402

_registrar_invalidador("runtime.settings", _invalidar_por_tenant)


def valores_efectivos(db: Session) -> dict[str, Any]:
    """Todos los ajustes con su valor efectivo y de dónde sale.

    Es lo que pinta la consola: sin la columna «de dónde viene», un
    administrador no entiende por qué el valor que acaba de poner no se aplica
    (lo sobrescribe un ámbito más específico) y acaba abriendo un ticket.
    """
    resultado: dict[str, Any] = {}
    for clave, decl in CLAVES.items():
        valor = efectivo(clave, db)
        origen = "entorno"
        from crmcore.tenancy.context import contexto_actual

        ctx = contexto_actual()
        for ambito, ambito_id in (
            ("usuario", str(ctx.user_id or "")),
            ("bu", str(ctx.business_unit_id or "")),
            ("tenant", str(ctx.tenant_id or "")),
            ("global", ""),
        ):
            if ambito_id or ambito == "global":
                if clave in _valores_de_ambito(db, ambito, ambito_id):
                    origen = ambito
                    break
        resultado[clave] = {
            "valor": valor,
            "origen": origen,
            "tipo": decl.tipo,
            "descripcion": decl.descripcion,
            "sensible": decl.sensible,
            "minimo": decl.minimo,
            "maximo": decl.maximo,
            "opciones": list(decl.opciones),
        }
    return resultado


def _ambitos_sin_usar() -> tuple[str, ...]:  # pragma: no cover
    """Mantiene vivo el import de ORDEN_AMBITOS para las anotaciones."""
    return ORDEN_AMBITOS
