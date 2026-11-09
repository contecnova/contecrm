"""Motor externo de compensación (CRM-03.02.03.04).

Calcular comisiones dentro del CRM funciona hasta el primer plan de verdad:
aceleradores por tramo, topes, garantías los primeros meses, clawback si el
cliente se va antes de un año, repartos entre equipos y reglas que cambian a
mitad de año con efecto retroactivo. Eso no es un cálculo, es un producto — y hay
empresas que lo fabrican.

Lo que tiene que hacer bien el CRM no es calcular: es **dar los hechos y aceptar
el resultado sin discutirlo**. Y ahí están los tres problemas:

**Lo que se manda es el hecho, no la comisión.** Si el CRM envía un importe ya
calculado «para ayudar», acaba habiendo dos cálculos y la nómina se hace con el
que no es. Se manda qué se cerró, cuándo, de quién y con qué reparto.

**El cálculo llega de vuelta y no se recalcula aquí.** Enseñar en el CRM una
comisión distinta de la que va a cobrar es la forma más rápida de que nadie se
crea ninguna de las dos.

**Y un cierre que cambia después obliga a decirlo, no a corregirlo en silencio.**
Un importe que baja o un pedido que se anula pueden cambiar una comisión ya
pagada: eso se llama clawback y es una conversación, no un ajuste.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable
from uuid import UUID

from crmcore.db.base import Base, TimestampMixin
from crmcore.errors import Conflicto, CrmError, ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Index,
    Numeric,
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

# Qué hechos se le mandan al motor. Cerrada porque cada uno tiene su tratamiento
# allí, y mandar un tipo que no conoce hace que lo ignore en silencio — y la
# comisión sale de menos sin que nadie vea un error.
HECHOS = ("cierre", "anulacion", "modificacion_importe", "cobro", "devolucion")

# Lo que NO se manda: el importe de la comisión. Si se mandara, habría dos
# cálculos y la nómina se haría con el que no es.
NO_SE_MANDA = ("comision", "porcentaje_comision", "importe_a_pagar")

ESTADOS = ("pendiente", "enviado", "calculado", "pagado", "revertido")


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def componer_hecho(
    *,
    tipo: str,
    referencia: str,
    fecha: date,
    importe: Decimal,
    moneda: str,
    reparto: list[dict[str, Any]],
    datos: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Prepara el hecho que se manda al motor, **sin la comisión dentro**.

    El reparto sí va —es información del CRM, que es quien sabe quién vendió qué—
    y el cálculo no. Mandar un importe ya calculado «para ayudar» produce dos
    cifras, y la nómina se hace con la que no es.
    """
    if tipo not in HECHOS:
        raise ErrorValidacion(
            f"Hecho «{tipo}» desconocido",
            error_code="compensacion.hecho_invalido",
            detalle={"admitidos": list(HECHOS)},
        )
    colados = sorted(set(datos or {}) & set(NO_SE_MANDA))
    if colados:
        raise ErrorValidacion(
            f"No se manda el cálculo de la comisión: {', '.join(colados)}. Si va dentro, "
            "habrá dos cálculos y la nómina se hará con el que no es.",
            error_code="compensacion.no_se_manda_el_calculo",
        )
    suma = sum(Decimal(str(r.get("porcentaje") or 0)) for r in reparto)
    if reparto and suma != Decimal(100):
        raise ErrorValidacion(
            f"El reparto suma {suma} y tiene que sumar 100: un descuadre aquí se "
            "convierte en una nómina mal calculada.",
            error_code="compensacion.reparto_descuadrado",
        )

    return {
        "tipo": tipo,
        "referencia": referencia,
        "fecha": fecha.isoformat(),
        "importe": str(importe),
        "moneda": moneda,
        "reparto": [
            {"usuario_id": str(r.get("usuario_id")), "porcentaje": str(r.get("porcentaje"))}
            for r in reparto
        ],
        "datos": dict(datos or {}),
        "lleva_comision": False,
        "porque": (
            "El CRM manda los hechos —qué se cerró, cuándo, de quién y con qué reparto— "
            "y el motor calcula. Dos cálculos es peor que ninguno."
        ),
        "compuesto_at": _ahora().isoformat(),
    }


def recibir_calculo(
    *, referencia: str, lineas: list[dict[str, Any]], periodo: str, cerrado: bool
) -> dict[str, Any]:
    """Recoge lo que ha calculado el motor, **tal cual**.

    No se recalcula ni se redondea: enseñar en el CRM una comisión distinta de la
    que se va a cobrar es la forma más rápida de que nadie se crea ninguna de las
    dos, y de que el comercial se haga su propia hoja de cálculo — que es donde
    empieza cualquier discusión de comisiones.

    Un periodo **no cerrado** se enseña como provisional. Es lo que evita la
    conversación de «pero si el CRM decía otra cosa» a final de mes.
    """
    if not lineas:
        return {
            "referencia": referencia,
            "medible": False,
            "porque": (
                "El motor no ha devuelto ninguna línea para esta referencia. No es cero: "
                "es que no consta cálculo, y puede ser que el hecho no le llegara."
            ),
        }
    total = sum(Decimal(str(x.get("importe") or 0)) for x in lineas)
    return {
        "referencia": referencia,
        "periodo": periodo,
        "lineas": lineas,
        "total": str(total),
        "provisional": not cerrado,
        "se_recalcula_aqui": False,
        "porque": (
            "Es el número del motor, tal cual. Enseñar aquí otro distinto del que se va "
            "a cobrar hace que nadie se crea ninguno de los dos."
            + (" El periodo no está cerrado, así que esto puede cambiar." if not cerrado else "")
        ),
    }


def cambio_despues_de_pagar(
    *,
    referencia: str,
    importe_original: Decimal,
    importe_nuevo: Decimal,
    ya_pagada: bool,
    motivo: str,
) -> dict[str, Any]:
    """Qué hacer cuando un cierre cambia después de haberse pagado la comisión.

    Se llama **clawback** y es una conversación, no un ajuste automático. Quitarle
    dinero a alguien de la próxima nómina sin decírselo es lo que hace que un
    equipo comercial deje de confiar en el sistema — y con razón.

    Lo que hace el CRM es **avisar con los números delante**: qué cambió, cuánto y
    por qué. Quién decide es otra persona.
    """
    if not motivo.strip():
        raise ErrorValidacion(
            "Un cambio que afecta a una comisión pagada necesita motivo: sin él, la "
            "conversación con el comercial empieza sin nada que enseñar.",
            error_code="compensacion.cambio_sin_motivo",
        )
    diferencia = Decimal(str(importe_nuevo)) - Decimal(str(importe_original))
    if ya_pagada and diferencia < 0:
        return {
            "hay_clawback": True,
            "referencia": referencia,
            "diferencia": str(diferencia),
            "motivo": motivo.strip(),
            "se_ajusta_solo": False,
            "que_hacer": (
                "Avisar y hablarlo. Quitarle dinero a alguien de la próxima nómina sin "
                "decírselo es lo que hace que un equipo deje de confiar en el sistema — "
                "y con razón."
            ),
        }
    return {
        "hay_clawback": False,
        "referencia": referencia,
        "diferencia": str(diferencia),
        "se_ajusta_solo": False,
        "que_hacer": (
            "Se manda el hecho al motor y él recalcula en el periodo que toque."
            if diferencia
            else "No cambia nada."
        ),
    }


def conciliar(
    *, hechos_enviados: list[dict[str, Any]], calculos_recibidos: list[dict[str, Any]]
) -> dict[str, Any]:
    """Qué se mandó y no ha vuelto, que es donde está el problema de verdad.

    Un hecho que se pierde por el camino no da ningún error: simplemente esa venta
    no aparece en la comisión de nadie, y lo descubre el comercial al mirar su
    nómina. Se comprueba antes de cerrar el periodo, que es el único momento en el
    que todavía se puede arreglar sin que duela.
    """
    enviadas = {str(h.get("referencia")) for h in hechos_enviados}
    calculadas = {str(c.get("referencia")) for c in calculos_recibidos}
    sin_volver = sorted(enviadas - calculadas)
    de_mas = sorted(calculadas - enviadas)

    return {
        "enviados": len(enviadas),
        "calculados": len(calculadas),
        "sin_calculo": sin_volver,
        "calculados_sin_hecho": de_mas,
        "cuadra": not sin_volver and not de_mas,
        "que_significa": (
            "Todo lo enviado ha vuelto calculado."
            if not sin_volver and not de_mas
            else " ".join(
                filter(
                    None,
                    [
                        f"{len(sin_volver)} ventas enviadas no han vuelto con cálculo: "
                        "no dan ningún error, simplemente no aparecen en la comisión de "
                        "nadie, y lo descubre el comercial en su nómina."
                        if sin_volver
                        else "",
                        f"{len(de_mas)} cálculos que no corresponden a nada que hayamos "
                        "mandado: alguien los ha metido a mano en el motor, y eso hay "
                        "que saberlo."
                        if de_mas
                        else "",
                    ],
                )
            )
        ),
    }


def exigir_periodo_abierto(*, periodo_cerrado: bool, referencia: str) -> None:
    """No se mandan hechos a un periodo ya cerrado.

    El motor los aceptaría y los metería en el siguiente, o los descartaría según
    cómo esté configurado: las dos cosas pasan en silencio y las dos acaban en una
    comisión que no cuadra con lo que el comercial cree que vendió.
    """
    if periodo_cerrado:
        raise Conflicto(
            f"El periodo de «{referencia}» está cerrado. Mandarlo igual haría que el "
            "motor lo metiera en el siguiente o lo descartara —según cómo esté "
            "configurado—, y las dos cosas pasan en silencio.",
            error_code="compensacion.periodo_cerrado",
        )


# ══════════════════════════════════════════════════════════════════════════
# El envío de verdad (09-11-2026)
#
# Lo de arriba componía el hecho, conciliaba dos listas que traía quien llamaba
# y «recibía» un cálculo devolviéndolo: no salía nada hacia ningún motor ni se
# guardaba nada. Lo de abajo es la otra mitad:
#
# * **el motor es una conexión de integración** con dos operaciones declaradas
#   —recibir hechos y devolver el cálculo—. Cambiar de motor es declarar otras
#   dos, no escribir otro módulo;
# * **los hechos salen de donde viven**: las ventas ganadas se piden a `sales`
#   por HTTP con la identidad de quien pulsa; los cobros, las devoluciones y
#   las anulaciones se dan de alta a mano o por API con su referencia;
# * **se guarda lo enviado y lo devuelto**, hecho a hecho;
# * **y se concilia contra lo que calcula la casa** —las liquidaciones de
#   `sales`—, enseñando cada diferencia.
# ══════════════════════════════════════════════════════════════════════════

CLASE_PERFIL = "compensacion"
ESTADOS_ENVIO = ("pendiente", "enviado", "calculado", "error")


class HechoCompensacion(Base, TimestampMixin):
    """Un hecho mandado (o por mandar) al motor externo, con lo que volvió."""

    __tablename__ = "hechos_compensacion"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    conexion_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    tipo: Mapped[str] = mapped_column(String(30), nullable=False, info={"opciones": HECHOS})
    referencia: Mapped[str] = mapped_column(String(200), nullable=False)
    # De dónde salió: una oportunidad ganada de `sales`, o dado de alta a mano.
    origen: Mapped[str] = mapped_column(String(30), nullable=False, default="manual")
    origen_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    # A quién se le atribuye: es lo que convierte el hecho en dato de una persona.
    usuario_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True, info={"sensibilidad": "personal"}
    )
    fecha: Mapped[date] = mapped_column(Date, nullable=False)
    importe: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    moneda: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    estado: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pendiente", info={"opciones": ESTADOS_ENVIO}
    )
    # Lo que se mandó, tal cual, y lo que contestó el motor, tal cual.
    enviado: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    respuesta: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    enviado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # El cálculo del motor, sin tocar.
    comision_motor: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    periodo: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    provisional: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    calculado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Lo que calcula la casa para la misma referencia, y la diferencia.
    comision_casa: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    diferencia: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    conciliado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "tipo", "referencia", name="uq_hecho_compensacion"),
        Index("ix_hechos_compensacion_estado", "tenant_id", "estado"),
    )


Invocador = Callable[..., dict[str, Any]]


def _invocar(**kw: Any) -> dict[str, Any]:
    from crmcore.http.interno import invocar

    return invocar(**kw)


def _ajuste(clave: str, db: Session | None) -> Any:
    from services.integration.ajustes import valor

    return valor(clave, db)


def _decimal(valor: Any) -> Decimal | None:
    if valor is None or valor == "":
        return None
    try:
        return Decimal(str(valor).replace(",", "."))
    except (InvalidOperation, ValueError):
        return None


def declarar_perfil(db: Session, tenant_id: UUID, *, conexion_id: UUID) -> Any:
    """Marca una conexión de integración como el motor de compensación."""
    from services.integration.modelos import Conexion

    fila = db.get(Conexion, conexion_id)
    if fila is None or fila.tenant_id != tenant_id:
        raise NoEncontrado(
            "La conexión no existe", error_code="compensacion.conexion_no_encontrada"
        )
    clase = dict(fila.config or {}).get("clase")
    if clase and clase != CLASE_PERFIL:
        raise Conflicto(
            f"La conexión «{fila.nombre}» ya es de otra clase ({clase}).",
            error_code="compensacion.conexion_de_otra_clase",
        )
    fila.config = {**dict(fila.config or {}), "clase": CLASE_PERFIL}
    db.flush()
    return fila


def perfil(db: Session, tenant_id: UUID) -> Any:
    from services.integration.modelos import Conexion

    candidatos = [
        c
        for c in db.execute(
            select(Conexion).where(Conexion.tenant_id == tenant_id, Conexion.activa.is_(True))
        )
        .scalars()
        .all()
        if dict(c.config or {}).get("clase") == CLASE_PERFIL
    ]
    if not candidatos:
        raise ErrorValidacion(
            "No hay motor de compensación conectado: márcalo en Compensación externa "
            "› Motor, sobre una conexión de Integraciones.",
            error_code="compensacion.sin_motor",
        )
    if len(candidatos) > 1:
        raise ErrorValidacion(
            "Hay más de una conexión marcada como motor de compensación.",
            error_code="compensacion.motor_ambiguo",
            detalle={"perfiles": sorted(c.nombre for c in candidatos)},
        )
    return candidatos[0]


def estado_del_perfil(db: Session, tenant_id: UUID) -> dict[str, Any]:
    from services.integration.operar import operacion_declarada

    try:
        conexion = perfil(db, tenant_id)
    except ErrorValidacion as exc:
        return {"conectado": False, "porque": exc.mensaje}
    ops = {
        str(_ajuste("compensacion_op_enviar", db)): False,
        str(_ajuste("compensacion_op_calculo", db)): False,
    }
    for clave in ops:
        ops[clave] = operacion_declarada(db, conexion.id, clave)
    return {
        "conectado": True,
        "conexion_id": str(conexion.id),
        "nombre": conexion.nombre,
        "sistema": conexion.sistema,
        "operaciones": ops,
        "falta": [f"la operación «{k}»" for k, v in ops.items() if not v],
    }


# ── Recoger los hechos ────────────────────────────────────────────────────


def ventas_ganadas(
    invocar: Invocador, *, identidad: dict[str, Any], desde: date, hasta: date
) -> list[dict[str, Any]]:
    """Las oportunidades ganadas en el periodo, preguntadas a `sales`.

    Con la identidad de quien pulsa: quien no ve una venta no la manda.
    """
    salida: list[dict[str, Any]] = []
    cursor = ""
    for _ in range(50):
        parametros: dict[str, Any] = {
            "estado": "ganada",
            "fecha_cierre_real__desde": desde.isoformat(),
            "fecha_cierre_real__hasta": hasta.isoformat(),
            "limite": 200,
        }
        if cursor:
            parametros["cursor"] = cursor
        r = invocar(metodo="GET", ruta="/api/v1/opportunities", parametros=parametros, **identidad)
        if not r.get("ok"):
            datos = r.get("datos") or {}
            raise ErrorValidacion(
                f"sales no ha dado las ventas ganadas (HTTP {r.get('estado')}): "
                f"{datos.get('mensaje') or datos.get('detail') or datos}"[:500],
                error_code="compensacion.ventas_sin_respuesta",
            )
        datos = r.get("datos") or {}
        salida.extend(datos.get("items") or [])
        cursor = str(datos.get("siguiente") or "")
        if not cursor:
            break
    return salida


def registrar_hecho(
    db: Session,
    tenant_id: UUID,
    *,
    tipo: str,
    referencia: str,
    fecha: date,
    importe: Decimal,
    moneda: str,
    usuario_id: UUID | None,
    origen: str = "manual",
    origen_id: UUID | None = None,
    datos: dict[str, Any] | None = None,
) -> tuple[HechoCompensacion, str]:
    """Guarda un hecho por mandar. Devuelve el hecho y qué se hizo con él.

    Un hecho ya mandado cuyo importe cambia **no se reescribe**: se dice. Es la
    conversación del clawback, no un ajuste en silencio; el cambio se manda como
    su propio hecho (`modificacion_importe` o `devolucion`).
    """
    reparto = [{"usuario_id": str(usuario_id), "porcentaje": 100}] if usuario_id else []
    carga = componer_hecho(
        tipo=tipo,
        referencia=referencia,
        fecha=fecha,
        importe=importe,
        moneda=moneda,
        reparto=reparto,
        datos=datos,
    )
    fila = db.execute(
        select(HechoCompensacion).where(
            HechoCompensacion.tenant_id == tenant_id,
            HechoCompensacion.tipo == tipo,
            HechoCompensacion.referencia == referencia,
        )
    ).scalar_one_or_none()
    if fila is not None and fila.estado in ("enviado", "calculado"):
        if Decimal(str(fila.importe)) != Decimal(str(importe)):
            return fila, "cambio_tras_enviar"
        return fila, "ya_estaba"
    if fila is None:
        fila = HechoCompensacion(tenant_id=tenant_id, tipo=tipo, referencia=referencia)
        db.add(fila)
        que = "nuevo"
    else:
        que = "actualizado"
    fila.origen = origen
    fila.origen_id = origen_id
    fila.usuario_id = usuario_id
    fila.fecha = fecha
    fila.importe = importe
    fila.moneda = moneda
    fila.estado = "pendiente"
    fila.enviado = carga
    fila.error = None
    db.flush()
    return fila, que


def recoger_ventas(
    db: Session,
    tenant_id: UUID,
    *,
    desde: date,
    hasta: date,
    identidad: dict[str, Any],
    invocar: Invocador | None = None,
) -> dict[str, Any]:
    """Convierte las ventas ganadas del periodo en hechos `cierre` por mandar."""
    invocar = invocar or _invocar
    cuenta = {"nuevo": 0, "actualizado": 0, "ya_estaba": 0, "cambio_tras_enviar": 0}
    cambios: list[dict[str, Any]] = []
    for o in ventas_ganadas(invocar, identidad=identidad, desde=desde, hasta=hasta):
        oid = UUID(str(o.get("id")))
        fecha = date.fromisoformat(str(o.get("fecha_cierre_real") or o.get("fecha_cierre"))[:10])
        importe = _decimal(o.get("importe")) or Decimal(0)
        owner = o.get("owner_id")
        fila, que = registrar_hecho(
            db,
            tenant_id,
            tipo="cierre",
            referencia=str(oid),
            fecha=fecha,
            importe=importe,
            moneda=str(o.get("moneda") or "EUR"),
            usuario_id=UUID(str(owner)) if owner else None,
            origen="oportunidad",
            origen_id=oid,
            datos={"nombre": o.get("nombre"), "cuenta_id": o.get("cuenta_id")},
        )
        cuenta[que] += 1
        if que == "cambio_tras_enviar":
            cambios.append(
                cambio_despues_de_pagar(
                    referencia=str(oid),
                    importe_original=Decimal(str(fila.importe)),
                    importe_nuevo=importe,
                    ya_pagada=fila.estado == "calculado" and not fila.provisional,
                    motivo="El importe de la venta cambió en el CRM después de mandarla",
                )
            )
    return {**cuenta, "cambios": cambios}


# ── Mandar y traer ────────────────────────────────────────────────────────


def _aplicar_calculo(fila: HechoCompensacion, registro: dict[str, Any]) -> None:
    comision = _decimal(registro.get("comision"))
    if comision is not None:
        fila.comision_motor = comision
        fila.estado = "calculado"
        fila.calculado_at = datetime.now(timezone.utc)
    if registro.get("periodo"):
        fila.periodo = str(registro.get("periodo"))[:40]
    if "cerrado" in registro:
        fila.provisional = not bool(registro.get("cerrado"))


def enviar_pendientes(db: Session, tenant_id: UUID) -> dict[str, Any]:
    """Manda al motor los hechos pendientes, en un lote, y guarda lo que contesta.

    Si el motor contesta ya con el cálculo de alguna referencia, se guarda tal
    cual. Si falla, los hechos quedan en «error» con el motivo y se pueden
    reintentar: un envío que falla sin dejar rastro es una venta que no aparece
    en la comisión de nadie.
    """
    from services.integration import operar

    conexion = perfil(db, tenant_id)
    filas = list(
        db.execute(
            select(HechoCompensacion)
            .where(
                HechoCompensacion.tenant_id == tenant_id,
                HechoCompensacion.estado.in_(("pendiente", "error")),
            )
            .order_by(HechoCompensacion.fecha)
        )
        .scalars()
        .all()
    )
    if not filas:
        return {"enviados": 0, "calculados": 0, "errores": 0, "porque": "No hay nada pendiente."}
    ahora = datetime.now(timezone.utc)
    try:
        respuesta = operar.ejecutar(
            db,
            conexion=conexion,
            clave=str(_ajuste("compensacion_op_enviar", db)),
            parametros={"hechos": [dict(f.enviado or {}) for f in filas]},
            timeout_s=float(_ajuste("compensacion_espera_s", db)),
            codigo_error="compensacion.operacion_no_declarada",
        )
    except CrmError as exc:
        for f in filas:
            f.estado = "error"
            f.error = f"{exc.error_code}: {exc.mensaje}"[:1000]
        db.flush()
        return {"enviados": 0, "calculados": 0, "errores": len(filas), "error": exc.mensaje}
    por_ref = {
        str(r.get("referencia")): r for r in respuesta.get("registros") or [] if r.get("referencia")
    }
    calculados = 0
    for f in filas:
        f.conexion_id = conexion.id
        f.enviado_at = ahora
        f.estado = "enviado"
        f.error = None
        registro = por_ref.get(f.referencia)
        if registro:
            f.respuesta = registro
            _aplicar_calculo(f, registro)
            calculados += f.estado == "calculado"
    db.flush()
    return {"enviados": len(filas), "calculados": calculados, "errores": 0}


def traer_calculo(db: Session, tenant_id: UUID, *, desde: date, hasta: date) -> dict[str, Any]:
    """Pide al motor lo calculado en el periodo y lo guarda junto a cada hecho."""
    from services.integration import operar

    conexion = perfil(db, tenant_id)
    respuesta = operar.ejecutar(
        db,
        conexion=conexion,
        clave=str(_ajuste("compensacion_op_calculo", db)),
        parametros={"desde": desde.isoformat(), "hasta": hasta.isoformat()},
        timeout_s=float(_ajuste("compensacion_espera_s", db)),
        codigo_error="compensacion.operacion_no_declarada",
    )
    registros = [r for r in respuesta.get("registros") or [] if r.get("referencia")]
    filas = {
        f.referencia: f
        for f in db.execute(
            select(HechoCompensacion).where(HechoCompensacion.tenant_id == tenant_id)
        )
        .scalars()
        .all()
    }
    sin_hecho: list[str] = []
    for r in registros:
        fila = filas.get(str(r.get("referencia")))
        if fila is None:
            sin_hecho.append(str(r.get("referencia")))
            continue
        fila.respuesta = {**dict(fila.respuesta or {}), **r}
        _aplicar_calculo(fila, r)
    db.flush()
    enviados = [
        {"referencia": f.referencia}
        for f in filas.values()
        if f.estado in ("enviado", "calculado") and desde <= f.fecha <= hasta
    ]
    return {
        "recibidos": len(registros),
        **conciliar(hechos_enviados=enviados, calculos_recibidos=registros),
        "calculados_sin_hecho": sorted(set(sin_hecho)),
    }


def conciliar_con_la_casa(
    db: Session,
    tenant_id: UUID,
    *,
    desde: date,
    hasta: date,
    identidad: dict[str, Any],
    invocar: Invocador | None = None,
) -> dict[str, Any]:
    """Pone al lado de cada cálculo del motor lo que calcula la casa.

    La casa son las liquidaciones de `sales` que caen en el periodo: cada línea
    con su origen. Se suman por oportunidad y se comparan con lo que devolvió
    el motor para esa venta. No se corrige nada: se enseña la diferencia.
    """
    invocar = invocar or _invocar
    r = invocar(metodo="GET", ruta="/api/v1/liquidaciones", parametros={"limite": 200}, **identidad)
    if not r.get("ok"):
        raise ErrorValidacion(
            f"sales no ha dado las liquidaciones (HTTP {r.get('estado')})",
            error_code="compensacion.liquidaciones_sin_respuesta",
        )
    casa: dict[str, Decimal] = {}
    liquidaciones = 0
    for liq in (r.get("datos") or {}).get("liquidaciones") or []:
        try:
            l_desde = date.fromisoformat(str(liq.get("desde"))[:10])
            l_hasta = date.fromisoformat(str(liq.get("hasta"))[:10])
        except ValueError:
            continue
        if l_hasta < desde or l_desde > hasta:
            continue
        d = invocar(metodo="GET", ruta=f"/api/v1/liquidaciones/{liq.get('id')}", **identidad)
        if not d.get("ok"):
            continue
        liquidaciones += 1
        for linea in (d.get("datos") or {}).get("lineas") or []:
            if not linea.get("origen_id"):
                continue
            casa[str(linea["origen_id"])] = casa.get(str(linea["origen_id"]), Decimal(0)) + (
                _decimal(linea.get("importe")) or Decimal(0)
            )
    tolerancia = Decimal(str(_ajuste("compensacion_tolerancia", db)))
    ahora = datetime.now(timezone.utc)
    diferencias: list[dict[str, Any]] = []
    cuadran = 0
    filas = (
        db.execute(
            select(HechoCompensacion).where(
                HechoCompensacion.tenant_id == tenant_id,
                HechoCompensacion.fecha >= desde,
                HechoCompensacion.fecha <= hasta,
            )
        )
        .scalars()
        .all()
    )
    for f in filas:
        clave = str(f.origen_id) if f.origen_id else f.referencia
        f.comision_casa = casa.get(clave)
        f.conciliado_at = ahora
        if f.comision_motor is None or f.comision_casa is None:
            f.diferencia = None
        else:
            f.diferencia = Decimal(str(f.comision_motor)) - Decimal(str(f.comision_casa))
        if f.diferencia is not None and abs(f.diferencia) <= tolerancia:
            cuadran += 1
        else:
            diferencias.append(
                {
                    "referencia": f.referencia,
                    "tipo": f.tipo,
                    "comision_motor": str(f.comision_motor)
                    if f.comision_motor is not None
                    else None,
                    "comision_casa": str(f.comision_casa) if f.comision_casa is not None else None,
                    "diferencia": str(f.diferencia) if f.diferencia is not None else None,
                    "porque": (
                        "El motor no ha devuelto cálculo para este hecho."
                        if f.comision_motor is None
                        else (
                            "La casa no tiene liquidación con esta venta en el periodo."
                            if f.comision_casa is None
                            else "Los dos cálculos no coinciden."
                        )
                    ),
                }
            )
    db.flush()
    return {
        "hechos": len(filas),
        "liquidaciones_de_la_casa": liquidaciones,
        "cuadran": cuadran,
        "diferencias": diferencias,
        "medible": bool(filas),
        "tolerancia": str(tolerancia),
    }


def a_dict(f: HechoCompensacion) -> dict[str, Any]:
    def _s(v: Any) -> str | None:
        return str(v) if v is not None else None

    return {
        "id": str(f.id),
        "tipo": f.tipo,
        "referencia": f.referencia,
        "origen": f.origen,
        "origen_id": _s(f.origen_id),
        "usuario_id": _s(f.usuario_id),
        "fecha": f.fecha.isoformat(),
        "importe": str(f.importe),
        "moneda": f.moneda,
        "estado": f.estado,
        "enviado": f.enviado or {},
        "respuesta": f.respuesta or {},
        "enviado_at": f.enviado_at.isoformat() if f.enviado_at else None,
        "error": f.error,
        "comision_motor": _s(f.comision_motor),
        "periodo": f.periodo,
        "provisional": f.provisional,
        "comision_casa": _s(f.comision_casa),
        "diferencia": _s(f.diferencia),
        "conciliado_at": f.conciliado_at.isoformat() if f.conciliado_at else None,
    }
