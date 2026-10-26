"""Trabajos asíncronos: id, sondeo, reanudación y callback (CRM-00.02.01.12).

Un CRM tiene operaciones que no caben en una petición HTTP: importar sesenta mil
contactos, reasignar la cartera de un comercial que se va, recalcular la
puntuación de todos los leads. Resolverlas de forma síncrona tiene tres finales
conocidos y ninguno bueno: el proxy corta a los treinta segundos, el cliente
reintenta y duplica, o el navegador se queda cargando mientras la transacción
bloquea media tabla.

Aquí se aceptan, se responde **202 con un identificador** y se ejecutan en un
worker. Quien la pidió pregunta por el identificador o, si lo prefiere, deja una
URL de aviso y no pregunta.

Tres decisiones que conviene entender antes de tocar esto:

**El trabajo lleva un cursor, y por eso se reanuda.** No es un contador de
progreso para pintar una barra: es el índice del siguiente elemento pendiente, y
se guarda con commit al final de cada tanda. Si el worker muere a mitad de una
importación de cincuenta mil filas, otro la retoma en la 31.200 en vez de
empezar de cero o —peor— de volver a insertar las 31.200 primeras.

**El bloqueo caduca.** `tomado_hasta` es lo que impide que un worker muerto deje
un trabajo retenido para siempre: vivo, visible como «ejecutando» y sin avanzar
un solo elemento, que es el peor modo de fallo porque nadie lo llama avería.

**Lo que se guarda del resultado está recortado, y el recuento no.** Un fichero
con cien mil filas todas mal produciría un JSONB de decenas de megabytes que
nadie puede leer y que infla cada backup. Se guardan los primeros errores; el
total de fallidos es exacto siempre. Es la misma decisión que ya toma
`crmcore.datos.masivas.Informe`, y se toma igual para que el informe de una
operación síncrona y el de la misma operación en diferido se lean igual.

El ejecutor de cada tipo lo declara el servicio dueño, igual que con los
comandos: `crmcore` sabe llevar un trabajo, no sabe qué es «importar cuentas».
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, Index, Integer, String, Text, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from crmcore.db.base import EntidadBase
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Estados por los que pasa un trabajo. `encolado → ejecutando → completado` es
# el camino feliz; `cancelado` solo se alcanza desde los dos primeros, y
# `fallido` cuando el ejecutor revienta de una forma que no es de un elemento
# concreto (la base no responde, el tipo ya no está registrado).
ESTADOS = ("encolado", "ejecutando", "completado", "fallido", "cancelado")
ESTADOS_VIVOS = ("encolado", "ejecutando")
ESTADOS_FINALES = ("completado", "fallido", "cancelado")


# Errores que se guardan en la ficha del trabajo. Ver la cabecera: el recuento
# sigue siendo exacto por encima de este tope.
def _trabajos_errores_guardados() -> int:
    """Tope del núcleo, antes `_trabajos_errores_guardados() = 500`.

    Era una constante de módulo. Sale del `.env`, no de los ajustes en
    caliente: es un tope operativo del despliegue y «por cliente» no
    significaría nada.
    """
    from crmcore.config import get_settings

    return get_settings().trabajos_errores_guardados


class Trabajo(EntidadBase):
    """Una operación larga aceptada y pendiente de terminar.

    Vive en el esquema del servicio que la ejecuta, no en uno común: el ejecutor
    necesita escribir en las tablas de ese servicio dentro de la misma
    transacción que avanza el cursor, y eso es imposible a través de otro
    esquema al que no tiene permisos de escritura. La contrapartida es que cada
    servicio tiene su tabla `trabajos`, y quien quiera verlos todos los pide a
    cada servicio — que es exactamente lo mismo que pasa con sus registros.
    """

    __tablename__ = "trabajos"

    # Qué hay que hacer. El servicio registra un ejecutor para cada tipo; pedir
    # un tipo sin ejecutor se rechaza al encolar y no al ejecutar, para que el
    # error lo vea quien lo puede arreglar y no un log de madrugada.
    tipo: Mapped[str] = mapped_column(String(80), nullable=False)
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="encolado")

    # Parámetros de la operación. Para una operación masiva lleva los elementos;
    # para un recálculo, el filtro. Es JSONB y no una referencia a un fichero
    # porque así el trabajo es autocontenido: se puede reanudar sin depender de
    # que un temporal siga existiendo.
    entrada: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    # Progreso. `total` puede ser 0 cuando no se conoce de antemano (un
    # recálculo sobre un filtro); en ese caso el porcentaje no se publica en vez
    # de inventarse, porque una barra que llega al 90 % y se queda ahí es peor
    # que no tener barra.
    total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cursor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ok: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fallidos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    resultado: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    errores: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Aviso al terminar. Se guarda la URL ya validada contra el guard de salidas
    # (`crmcore.red.guard_url`): aceptarla sin validar convertiría este campo en
    # un SSRF con persistencia, porque el que la dispara es el worker, dentro de
    # la red interna, y no la petición del usuario.
    callback_url: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    callback_estado: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    callback_intentos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    tomado_por: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    tomado_hasta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    empezado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    terminado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Cuándo deja de poder consultarse. Un trabajo guarda la entrada completa, y
    # la entrada de una importación son los datos personales del fichero: no se
    # conservan indefinidamente porque el cliente quiso verlos una vez.
    expira_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    pedido_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    __table_args__ = (
        # Compuesto y por tenant primero: es el orden en que RLS deja la
        # consulta, y el que sirve tanto al listado del usuario como a la toma
        # de lote del worker.
        Index("ix_trabajos_tenant_estado", "tenant_id", "estado", "created_at"),
        # El worker consulta SIN filtro de tenant (corre como sistema), así que
        # necesita su propio índice: el compuesto de arriba no le vale porque no
        # aporta el primer predicado.
        Index("ix_trabajos_pendientes", "estado", "tomado_hasta"),
    )


# ── Ejecutores ────────────────────────────────────────────────────────────


@dataclass
class Tanda:
    """Lo que el ejecutor devuelve tras procesar un trozo.

    `avanzados` es cuántos elementos ha consumido del cursor, y no cuántos han
    ido bien: un elemento que falla también se consume, porque si no el trabajo
    se quedaría reintentándolo eternamente. Los que fallan se cuentan aparte.
    """

    avanzados: int
    ok: int = 0
    fallidos: int = 0
    errores: list[dict[str, Any]] = field(default_factory=list)
    # Cuando el ejecutor descubre el total al empezar (un filtro que resuelve a
    # N filas), lo publica aquí en vez de dejarlo en 0 para siempre.
    total: int | None = None
    # Datos que el ejecutor quiera dejar en la ficha: un resumen, un enlace al
    # fichero generado. Se fusiona con lo que ya hubiera.
    resultado: dict[str, Any] = field(default_factory=dict)


# Firma de un ejecutor: recibe la sesión, el trabajo y cuántos elementos como
# máximo puede procesar en esta vuelta. Devuelve la tanda.
#
# El tope lo impone el worker y no el ejecutor porque es una decisión de
# operación —cuánto puede tardar un commit— y no de negocio.
Ejecutor = Callable[[Session, Trabajo, int], Tanda]

_EJECUTORES: dict[str, Ejecutor] = {}


def registrar_ejecutor(tipo: str, fn: Ejecutor) -> None:
    """Declara qué hace un tipo de trabajo. Lo llama el servicio dueño.

    Se rechaza registrar dos veces el mismo tipo: en un proceso donde se importan
    los módulos de varios servicios —las pruebas— el segundo registro pisaría al
    primero sin avisar, y el trabajo de un servicio se ejecutaría con el ejecutor
    de otro sobre el esquema equivocado.
    """
    anterior = _EJECUTORES.get(tipo)
    if anterior is not None and anterior is not fn:
        raise RuntimeError(
            f"El tipo de trabajo «{tipo}» ya tiene ejecutor "
            f"({anterior.__module__}.{anterior.__qualname__})"
        )
    _EJECUTORES[tipo] = fn


def ejecutor_de(tipo: str) -> Ejecutor | None:
    return _EJECUTORES.get(tipo)


def tipos_registrados() -> list[str]:
    return sorted(_EJECUTORES)


# ── Alta ──────────────────────────────────────────────────────────────────


def encolar(
    db: Session,
    *,
    tenant_id: UUID,
    tipo: str,
    entrada: dict[str, Any],
    total: int = 0,
    callback_url: str = "",
    pedido_por: UUID | None = None,
    retencion_horas: int | None = None,
) -> Trabajo:
    """Acepta una operación larga y devuelve su ficha.

    No la ejecuta: la deja lista para que la coja un worker. Se hace así y no
    con una tarea en segundo plano del propio proceso web porque una tarea en
    segundo plano muere con el proceso, y un despliegue a mitad de una
    importación la perdería sin que nadie lo supiera.
    """
    if tipo not in _EJECUTORES:
        raise ErrorValidacion(
            f"No hay ejecutor para trabajos de tipo «{tipo}»",
            error_code="trabajo.tipo_desconocido",
            detalle={"conocidos": tipos_registrados()},
        )
    if callback_url:
        _validar_callback(callback_url)

    from crmcore.config import get_settings

    cfg = get_settings()
    horas = retencion_horas if retencion_horas is not None else cfg.trabajo_retencion_h
    trabajo = Trabajo(
        tenant_id=tenant_id,
        tipo=tipo,
        estado="encolado",
        entrada=entrada,
        total=total,
        callback_url=callback_url,
        pedido_por=pedido_por,
        expira_at=datetime.now(timezone.utc) + timedelta(hours=horas),
    )
    db.add(trabajo)
    db.flush()
    logger.info(
        "trabajo.encolado",
        trabajo=str(trabajo.id),
        tipo=tipo,
        total=total,
        con_callback=bool(callback_url),
    )
    return trabajo


def _validar_callback(url: str) -> None:
    """Comprueba la URL de aviso ANTES de guardarla.

    Validarla al dispararla sería tarde en el único sentido que importa: el
    trabajo ya se habría aceptado, el cliente ya se habría ido creyendo que le
    avisarían, y el fallo aparecería horas después en un log. Aquí se rechaza en
    la misma respuesta que la pide.
    """
    from crmcore.red import exigir

    # `exigir` ya lanza `ErrorValidacion` con el motivo del guard. No se
    # reenvuelve: el detalle que trae —qué IP resolvió y por qué está
    # bloqueada— es justo lo que necesita quien configura el aviso, y envolverlo
    # en otro mensaje lo perdería.
    exigir(url)


# ── Consulta ──────────────────────────────────────────────────────────────


def leer(db: Session, trabajo_id: UUID) -> Trabajo:
    trabajo = db.get(Trabajo, trabajo_id)
    if trabajo is None:
        raise NoEncontrado("Trabajo no encontrado", error_code="trabajo.no_existe")
    return trabajo


def a_dict(trabajo: Trabajo, *, con_errores: bool = False) -> dict[str, Any]:
    """Ficha para el cliente que sondea.

    `porcentaje` sale `None` cuando no se conoce el total, y no 0: son cosas
    distintas y confundirlas hace que una barra de progreso se quede clavada en
    el cero mientras el trabajo avanza bien.
    """
    porcentaje: float | None = None
    if trabajo.total > 0:
        porcentaje = round(min(trabajo.cursor, trabajo.total) * 100 / trabajo.total, 1)
    ficha: dict[str, Any] = {
        "id": str(trabajo.id),
        "tipo": trabajo.tipo,
        "estado": trabajo.estado,
        "total": trabajo.total,
        "procesados": trabajo.cursor,
        "ok": trabajo.ok,
        "fallidos": trabajo.fallidos,
        "porcentaje": porcentaje,
        "resultado": trabajo.resultado,
        "error": trabajo.error,
        # Cuántos errores hay de verdad, frente a cuántos se guardaron. Sin este
        # par, «300 errores» junto a una lista de 500 elementos recortada se lee
        # como si estuvieran todos.
        "errores_guardados": len(trabajo.errores),
        "callback_estado": trabajo.callback_estado,
        "creado_at": trabajo.created_at.isoformat() if trabajo.created_at else None,
        "empezado_at": trabajo.empezado_at.isoformat() if trabajo.empezado_at else None,
        "terminado_at": trabajo.terminado_at.isoformat() if trabajo.terminado_at else None,
        "expira_at": trabajo.expira_at.isoformat() if trabajo.expira_at else None,
    }
    if con_errores:
        ficha["errores"] = trabajo.errores
    return ficha


def cancelar(db: Session, trabajo_id: UUID, *, motivo: str = "") -> Trabajo:
    """Pide que un trabajo pare.

    Si está encolado, para en seco. Si está ejecutando, **termina la tanda en
    curso y para**: interrumpir a mitad de una tanda dejaría la mitad de sus
    elementos escritos y el cursor sin avanzar, y al reanudar se volverían a
    escribir. Lo ya procesado se queda procesado y se dice cuánto fue, que es lo
    honesto: una importación cancelada a la mitad ha metido media importación.
    """
    trabajo = leer(db, trabajo_id)
    if trabajo.estado in ESTADOS_FINALES:
        raise Conflicto(
            f"El trabajo ya está «{trabajo.estado}»",
            error_code="trabajo.ya_terminado",
        )
    trabajo.estado = "cancelado"
    trabajo.terminado_at = datetime.now(timezone.utc)
    trabajo.error = motivo or "Cancelado a petición"
    db.flush()
    logger.info("trabajo.cancelado", trabajo=str(trabajo.id), motivo=motivo[:200])
    return trabajo


# ── Ejecución ─────────────────────────────────────────────────────────────


def tomar_lote(db: Session, *, worker_id: str, lote: int) -> list[Trabajo]:
    """Toma trabajos pendientes y los bloquea para este worker.

    `SKIP LOCKED` es lo que hace que N réplicas den el trabajo de N: sin él cada
    worker esperaría al bloqueo del anterior sobre la misma fila.

    Se recogen también los que están «ejecutando» con el bloqueo caducado, que
    son los que dejó un worker al morir. Esa es toda la recuperación que hace
    falta, y es automática: no hay un procedimiento de rescate que alguien tenga
    que acordarse de lanzar.
    """
    ahora = datetime.now(timezone.utc)
    filas = (
        db.execute(
            select(Trabajo)
            .where(
                Trabajo.estado.in_(ESTADOS_VIVOS),
                or_(Trabajo.tomado_hasta.is_(None), Trabajo.tomado_hasta < ahora),
            )
            .order_by(Trabajo.created_at)
            .limit(lote)
            .with_for_update(skip_locked=True)
        )
        .scalars()
        .all()
    )
    from crmcore.config import get_settings

    caducidad = get_settings().trabajo_bloqueo_min
    for trabajo in filas:
        trabajo.tomado_por = worker_id
        trabajo.tomado_hasta = ahora + timedelta(minutes=caducidad)
    db.commit()
    return list(filas)


def avanzar(db: Session, trabajo: Trabajo, *, tanda_max: int) -> bool:
    """Procesa una tanda del trabajo y guarda el avance. Devuelve si queda más.

    Cada llamada hace **un commit**. Es lo que convierte el cursor en una
    promesa: al volver de una caída, lo confirmado en la base y lo que dice el
    cursor son lo mismo. Con un commit único al final, el cursor sería una
    intención y la reanudación duplicaría trabajo.
    """
    ejecutor = _EJECUTORES.get(trabajo.tipo)
    if ejecutor is None:
        # Pasa de verdad: un trabajo encolado por una versión que conocía el
        # tipo y recogido por una que ya no. Se falla explícito en vez de dejarlo
        # girando en la cola, donde se quedaría hasta que alguien lo mirara.
        return _fallar(db, trabajo, f"El tipo «{trabajo.tipo}» ya no tiene ejecutor")

    if trabajo.estado == "encolado":
        trabajo.estado = "ejecutando"
        trabajo.empezado_at = datetime.now(timezone.utc)

    try:
        tanda = ejecutor(db, trabajo, tanda_max)
    except Exception as exc:  # noqa: BLE001 — un ejecutor roto no tumba el worker
        db.rollback()
        # Se relee: el rollback ha dejado el objeto expirado y tocarlo sin
        # recargar dispararía otra excepción encima de la que se está tratando.
        trabajo = leer(db, trabajo.id)
        return _fallar(db, trabajo, f"{type(exc).__name__}: {exc}")

    if tanda.total is not None and tanda.total != trabajo.total:
        trabajo.total = tanda.total
    trabajo.cursor += tanda.avanzados
    trabajo.ok += tanda.ok
    trabajo.fallidos += tanda.fallidos
    if tanda.errores:
        hueco = _trabajos_errores_guardados() - len(trabajo.errores)
        if hueco > 0:
            trabajo.errores = [*trabajo.errores, *tanda.errores[:hueco]]
    if tanda.resultado:
        trabajo.resultado = {**trabajo.resultado, **tanda.resultado}

    # Cancelación pedida mientras corría: la tanda en curso ya está hecha y
    # comprometida, así que se cierra aquí y no se pide otra.
    if trabajo.estado == "cancelado":
        trabajo.tomado_por = ""
        trabajo.tomado_hasta = None
        db.commit()
        return False

    # Terminado cuando el ejecutor deja de avanzar. Es la única señal fiable:
    # `cursor >= total` no vale cuando el total no se conocía, y un ejecutor que
    # descubre a mitad que hay menos elementos de los anunciados dejaría el
    # trabajo colgado esperando a llegar a un total que no existe.
    if tanda.avanzados == 0:
        trabajo.estado = "completado"
        trabajo.terminado_at = datetime.now(timezone.utc)
        trabajo.tomado_por = ""
        trabajo.tomado_hasta = None
        # El total se cierra con lo que de verdad se procesó. Si se anunciaron
        # 1.000 y el fichero traía 998, dejar el 1.000 haría que la ficha dijera
        # «99,8 %» para siempre sobre un trabajo terminado.
        trabajo.total = trabajo.cursor
        db.commit()
        logger.info(
            "trabajo.completado",
            trabajo=str(trabajo.id),
            tipo=trabajo.tipo,
            ok=trabajo.ok,
            fallidos=trabajo.fallidos,
        )
        return False

    # Se renueva el bloqueo: una tanda que ha ido bien es prueba de que este
    # worker sigue vivo, y sin renovar, un trabajo largo perdería su bloqueo a
    # mitad y otro worker empezaría a avanzarlo en paralelo desde el mismo
    # cursor.
    from crmcore.config import get_settings

    trabajo.tomado_hasta = datetime.now(timezone.utc) + timedelta(
        minutes=get_settings().trabajo_bloqueo_min
    )
    db.commit()
    return True


def _fallar(db: Session, trabajo: Trabajo, motivo: str) -> bool:
    trabajo.estado = "fallido"
    trabajo.error = motivo[:1000]
    trabajo.terminado_at = datetime.now(timezone.utc)
    trabajo.tomado_por = ""
    trabajo.tomado_hasta = None
    db.commit()
    logger.error("trabajo.fallido", trabajo=str(trabajo.id), motivo=motivo[:300])
    return False


def soltar(db: Session, trabajo: Trabajo) -> None:
    """Libera el bloqueo sin cerrar el trabajo (apagado limpio del worker).

    Sin esto, un `SIGTERM` durante un despliegue dejaría cada trabajo en vuelo
    retenido hasta que caducara el bloqueo: minutos de parada visible por algo
    que se sabía de antemano.
    """
    if trabajo.estado in ESTADOS_VIVOS:
        trabajo.tomado_por = ""
        trabajo.tomado_hasta = None
        db.commit()


# ── Aviso al terminar ─────────────────────────────────────────────────────


def avisar(db: Session, trabajo: Trabajo) -> bool:
    """Llama a la URL de aviso del trabajo. Devuelve si lo consiguió.

    Va firmado con el mismo esquema que los webhooks —HMAC sobre cuerpo y
    momento— porque el problema es idéntico: quien recibe tiene que poder
    comprobar que el aviso viene de aquí y que no es uno viejo reenviado.

    Y sale por el transporte con guard (`crmcore.red.guard_url`): esta llamada la
    hace el worker desde la red interna, así que sin guard una URL de aviso
    apuntando a `169.254.169.254` sería un SSRF con la credencial del worker.
    """
    if not trabajo.callback_url or trabajo.callback_estado == "entregado":
        return False

    import json

    from crmcore.config import get_settings
    from crmcore.red import cliente_seguro
    from crmcore.security.firma import cabeceras_firmadas

    cfg = get_settings()
    cuerpo = json.dumps(a_dict(trabajo), ensure_ascii=False).encode()
    cabeceras = {
        "content-type": "application/json",
        **cabeceras_firmadas(cuerpo, cfg.secret_key),
    }

    trabajo.callback_intentos += 1
    try:
        with cliente_seguro(timeout=cfg.http_externo_timeout_s) as cliente:
            respuesta = cliente.post(trabajo.callback_url, content=cuerpo, headers=cabeceras)
        entregado = 200 <= respuesta.status_code < 300
        trabajo.callback_estado = "entregado" if entregado else "fallido"
        if not entregado:
            logger.warning(
                "trabajo.callback_rechazado",
                trabajo=str(trabajo.id),
                codigo=respuesta.status_code,
            )
        return entregado
    except Exception as exc:  # noqa: BLE001 — el aviso no puede tumbar el worker
        # Incluye el rechazo del guard: la URL se validó al encolar, pero entre
        # aquello y ahora el DNS ha podido cambiar para apuntar a una IP
        # interna. Que el guard vuelva a decidir en cada salto es precisamente
        # lo que cierra esa ventana.
        trabajo.callback_estado = "fallido"
        logger.warning("trabajo.callback_error", trabajo=str(trabajo.id), error=str(exc)[:200])
        return False
    finally:
        db.commit()


# ── Limpieza ──────────────────────────────────────────────────────────────


def purgar_caducados(db: Session, *, lote: int = 500) -> int:
    """Borra los trabajos terminados cuya retención venció.

    Se borran de verdad y no se marcan: la entrada de una importación son los
    datos que el cliente subió, y conservarlos «por si acaso» pasado el plazo es
    exactamente lo que el plazo existe para impedir.
    """
    ahora = datetime.now(timezone.utc)
    filas = (
        db.execute(
            select(Trabajo)
            .where(
                Trabajo.estado.in_(ESTADOS_FINALES),
                Trabajo.expira_at.is_not(None),
                Trabajo.expira_at < ahora,
            )
            .limit(lote)
        )
        .scalars()
        .all()
    )
    for trabajo in filas:
        db.delete(trabajo)
    if filas:
        db.commit()
        logger.info("trabajo.purgados", cuantos=len(filas))
    return len(filas)
