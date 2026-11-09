"""Cuándo corre una automatización: ahora, después o a su hora (CRM-00.03.03.05).

`momento` —inmediata, diferida o programada— se guardaba en cada regla y **no lo
leía nadie**: todo corría en el instante del disparo, dentro de la transacción
de quien lo provocó. Y `programacion`, el horario de las programadas, tampoco:
una regla «los lunes a las 8» no corría nunca.

Aquí está lo que lo hace verdad, en tres piezas:

  * `despachar()` decide, para cada regla que encaja con un disparo, si se
    ejecuta ya o se **encola** con su hora;
  * `programar()` mira el reloj de las reglas cuyo disparador es el propio
    horario y encola la vuelta que toca;
  * `ejecutar_pendientes()` atiende la cola cuando llega la hora.

**Diferida** significa que corre fuera de la transacción del disparo: la fila
de la cola se escribe en esa transacción —si el disparo se deshace, no queda
nada que ejecutar— y se ejecuta en otra, después. Así una regla que manda un
correo no lo manda por un registro que acabó deshaciéndose.

**Programada** significa que corre a la hora de su `programacion`, en la zona
del tenant: si la dispara un evento, espera a la siguiente hora del horario;
si su disparador es el propio horario, corre en cada vuelta del reloj.

**No se pierde nada si el proceso cae**, porque la cola es una tabla y no una
lista en memoria: la ejecución y la marca de «hecha» van en la misma
transacción, así que una caída a medias deja la fila pendiente y la siguiente
vuelta la recoge. Y **no se ejecuta dos veces**: cada entrada lleva una clave
única —el evento y la regla, o la regla y su hora— y la segunda choca.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from crmcore.errors import ErrorValidacion
from crmcore.fechas import ahora_utc, zona_del_tenant
from crmcore.logging import get_logger
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from services.automation import cron, motor
from services.automation import ejecutores as ejecutores_mod
from services.automation.modelos import Automatizacion, EjecucionAutomatizacion, EjecucionPendiente

logger = get_logger(__name__)


def _ajuste(clave: str, db: Session | None = None) -> int:
    """Un ajuste del planificador, con el valor efectivo del tenant en curso."""
    from crmcore.runtime import settings as rt

    return int(rt.efectivo(clave, db))


def _congelar(valores: dict[str, Any]) -> dict[str, Any]:
    """Los valores, convertidos a JSON de verdad para guardarlos en la cola.

    Un evento puede traer fechas o identificadores como objetos; guardarlos tal
    cual reventaría al escribir la fila, y la transacción del disparo con ella.
    """
    return json.loads(json.dumps(valores or {}, default=str))


def cuando_toca(regla: Automatizacion, ahora: datetime, db: Session | None = None) -> datetime:
    """A qué hora corre esta regla si se dispara ahora.

    Inmediata: ahora. Diferida: tras la espera configurada. Programada: en la
    siguiente hora de su horario, en la zona del tenant.
    """
    if regla.momento == "programada":
        return cron.leer(regla.programacion).siguiente(ahora, zona_del_tenant(db))
    if regla.momento == "diferida":
        return ahora + timedelta(seconds=_ajuste("automatizacion_diferida_espera_s", db))
    return ahora


def encolar(
    db: Session,
    regla: Automatizacion,
    *,
    origen: str,
    clave: str,
    objeto: str,
    registro_id: str | None,
    valores: dict[str, Any],
    ejecutar_at: datetime,
    estado: str = "pendiente",
) -> bool:
    """Deja la ejecución en la cola. Devuelve si ENTRÓ ahora, no si ya estaba.

    Se lee de `RETURNING` y no de `rowcount`: con el `ON CONFLICT` el contador
    salía 1 también al chocar, y un reenvío de webhook pasaba por nuevo.

    `ON CONFLICT DO NOTHING` sobre la clave: un evento que llega dos veces, o
    dos planificadores que miran el mismo minuto, no la encolan dos veces. Va
    en la sesión de quien llama, así que entra o no con su transacción.
    """
    resultado = db.execute(
        insert(EjecucionPendiente)
        .values(
            tenant_id=regla.tenant_id,
            automatizacion_id=regla.id,
            origen=origen,
            clave=clave[:200],
            objeto=objeto[:120],
            registro_id=registro_id,
            valores=_congelar(valores),
            ejecutar_at=ejecutar_at,
            estado=estado,
            intentos=0,
        )
        .on_conflict_do_nothing(index_elements=["tenant_id", "clave"])
        .returning(EjecucionPendiente.id)
    )
    return resultado.scalar_one_or_none() is not None


def _traza_de_fallo(
    db: Session, regla: Automatizacion, *, objeto: str, registro_id: str | None, error: str
) -> EjecucionAutomatizacion:
    """Una traza «fallida» cuando ni siquiera se puede encolar.

    Pasa con una programada cuyo horario se rompió desde la ficha. Callarlo
    sería una regla que deja de correr sin que nadie sepa por qué; la traza es
    donde alguien mira cuando pregunta.
    """
    traza = EjecucionAutomatizacion(
        tenant_id=regla.tenant_id,
        automatizacion_id=regla.id,
        objeto=objeto,
        registro_id=registro_id,
        resultado="fallida",
        error=error[:2000],
    )
    regla.fallos += 1
    db.add(traza)
    return traza


def ejecutar_o_encolar(
    uow: Any,
    regla: Automatizacion,
    *,
    origen: str,
    clave: str,
    objeto: str,
    registro_id: str | None,
    valores: dict[str, Any],
    ejecutores: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Una regla concreta: ahora si es inmediata, a la cola si no."""
    if regla.momento == "inmediata" and origen == "webhook":
        # Un webhook firmado se puede reenviar tal cual dentro de su ventana, y
        # una regla inmediata lo ejecutaba dos veces. Su clave se apunta en la
        # cola, ya hecha y en la misma transacción: si ya estaba, es un reenvío.
        if not encolar(
            uow.db,
            regla,
            origen=origen,
            clave=clave,
            objeto=objeto,
            registro_id=registro_id,
            valores=valores,
            ejecutar_at=ahora_utc(),
            estado="hecha",
        ):
            return {"ejecutada": False, "duplicada": True}
    if regla.momento == "inmediata":
        traza = motor.ejecutar(
            uow.db,
            regla,
            valores=valores,
            objeto=objeto,
            registro_id=registro_id,
            ejecutores=ejecutores if ejecutores is not None else ejecutores_mod.construir(uow),
        )
        uow.db.flush()
        return {"ejecutada": True, "resultado": traza.resultado, "ejecucion_id": str(traza.id)}
    try:
        cuando = cuando_toca(regla, ahora_utc(), uow.db)
    except ErrorValidacion as exc:
        traza = _traza_de_fallo(
            uow.db, regla, objeto=objeto, registro_id=registro_id, error=exc.mensaje
        )
        uow.db.flush()
        return {"ejecutada": False, "resultado": "fallida", "error": exc.mensaje}
    encolar(
        uow.db,
        regla,
        origen=origen,
        clave=clave,
        objeto=objeto,
        registro_id=registro_id,
        valores=valores,
        ejecutar_at=cuando,
    )
    return {"ejecutada": False, "encolada": True, "ejecutar_at": cuando.isoformat()}


def despachar(
    uow: Any,
    *,
    tenant_id: UUID,
    disparador: str,
    objetivo: str,
    valores: dict[str, Any],
    registro_id: str | None,
    clave_disparo: str,
    origen: str,
    campos_cambiados: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Todas las reglas que encajan con un disparo, cada una en su momento.

    En el orden de siempre —prioridad y antigüedad—: las inmediatas corren en
    ese orden aquí mismo y las demás entran en la cola con su hora, que es la
    que manda después.
    """
    reglas = motor.aplicables(
        uow.db,
        tenant_id=tenant_id,
        disparador=disparador,
        objetivo=objetivo,
        campos_cambiados=campos_cambiados,
    )
    if not reglas:
        return []
    ejecutores = ejecutores_mod.construir(uow)
    return [
        {
            "regla": regla.nombre,
            **ejecutar_o_encolar(
                uow,
                regla,
                origen=origen,
                clave=f"{clave_disparo}:{regla.id}",
                objeto=objetivo,
                registro_id=registro_id,
                valores=valores,
                ejecutores=ejecutores,
            ),
        }
        for regla in reglas
    ]


# ── El reloj de las programadas ───────────────────────────────────────────


def anotar_activacion(regla: Automatizacion, principal: Any) -> None:
    """Guarda quién la encendió y con qué permisos, o lo borra al apagarla.

    Es la identidad con la que actúa lo que la regla lance (ver
    `motor.identidad_de`). Se pisa en cada activación: si otra persona la
    vuelve a encender, es esa quien ha decidido que actúe.
    """
    if not regla.activa or principal is None or getattr(principal, "id", None) is None:
        regla.activada_por_id = None
        regla.activada_con = {}
        return
    regla.activada_por_id = principal.id
    regla.activada_con = {
        "tipo": str(getattr(principal, "tipo", "") or "usuario"),
        "permisos": sorted(getattr(principal, "permisos", ()) or ()),
        "roles": sorted(getattr(principal, "roles", ()) or ()),
    }


def recalcular_proxima(regla: Automatizacion, db: Session | None = None) -> None:
    """Pone la próxima hora de una programada, o la quita si no le toca.

    Se llama al crear y al encender: la ficha enseña cuándo correrá, y es lo
    primero que alguien mira para saber si ha escrito bien el horario.
    """
    if regla.disparador != "programada" or not regla.activa:
        regla.proxima_ejecucion_at = None
        regla.proxima_segun = None
        return
    regla.proxima_ejecucion_at = cron.leer(regla.programacion).siguiente(
        ahora_utc(), zona_del_tenant(db)
    )
    regla.proxima_segun = regla.programacion


def programar(uow: Any) -> dict[str, Any]:
    """Encola la vuelta de cada regla programada a la que le ha llegado la hora.

    **Si el proceso estuvo parado y se saltó varias horas, corre una vez, no
    tantas como se perdieron.** Un resumen diario que estuvo tres días sin
    servicio no tiene que mandar tres resúmenes iguales al volver; tiene que
    mandar el de hoy. La vuelta que corre lleva la hora que le tocaba.
    """
    db = uow.db
    ahora = ahora_utc()
    zona = zona_del_tenant(db)
    reglas = (
        db.execute(
            select(Automatizacion).where(
                Automatizacion.tenant_id == uow.tenant_id,
                Automatizacion.activa.is_(True),
                Automatizacion.disparador == "programada",
                Automatizacion.deleted_at.is_(None),
            )
        )
        .scalars()
        .all()
    )
    encoladas, recalculadas, rotas = 0, 0, []
    for regla in reglas:
        try:
            expresion = cron.leer(regla.programacion)
        except ErrorValidacion as exc:
            # Se apunta UNA vez, cuando cambia el horario roto, y no en cada
            # vuelta: diez segundos de trazas iguales taparían todo lo demás.
            if regla.proxima_segun != f"!{regla.programacion}":
                _traza_de_fallo(
                    db, regla, objeto=regla.objetivo, registro_id=None, error=exc.mensaje
                )
                regla.proxima_ejecucion_at = None
                regla.proxima_segun = f"!{regla.programacion}"[:120]
            rotas.append(regla.nombre)
            continue
        if regla.proxima_ejecucion_at is None or regla.proxima_segun != regla.programacion:
            regla.proxima_ejecucion_at = expresion.siguiente(ahora, zona)
            regla.proxima_segun = regla.programacion
            recalculadas += 1
            continue
        if regla.proxima_ejecucion_at > ahora:
            continue
        toca = regla.proxima_ejecucion_at
        if encolar(
            db,
            regla,
            origen="programada",
            clave=f"programada:{regla.id}:{toca.isoformat()}",
            objeto=regla.objetivo,
            registro_id=None,
            valores={"_programada_para": toca.isoformat()},
            ejecutar_at=toca,
        ):
            encoladas += 1
        regla.proxima_ejecucion_at = expresion.siguiente(ahora, zona)
    return {"encoladas": encoladas, "recalculadas": recalculadas, "horarios_rotos": rotas}


# ── La cola ───────────────────────────────────────────────────────────────


def _atender_una(tenant_id: UUID) -> tuple[str, UUID | None]:
    """Atiende la primera pendiente a la que le ha llegado la hora.

    En su propia transacción: ejecutar la regla y marcar la fila como hecha son
    una sola cosa. `SKIP LOCKED` deja que dos procesos atiendan la misma cola
    sin pisarse ni esperarse.
    """
    from crmcore.db.uow import unidad_de_trabajo
    from crmcore.tenancy.context import con_contexto

    with (
        con_contexto(tenant_id=tenant_id, origen="automatizacion"),
        unidad_de_trabajo(tenant_id) as uow,
    ):
        fila = (
            uow.db.execute(
                select(EjecucionPendiente)
                .where(
                    EjecucionPendiente.tenant_id == tenant_id,
                    EjecucionPendiente.estado == "pendiente",
                    EjecucionPendiente.ejecutar_at <= ahora_utc(),
                )
                .order_by(EjecucionPendiente.ejecutar_at, EjecucionPendiente.created_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            .scalars()
            .first()
        )
        if fila is None:
            return "vacia", None
        identificador = fila.id
        try:
            regla = uow.db.get(Automatizacion, fila.automatizacion_id)
            if regla is None or regla.deleted_at is not None or not regla.activa:
                # Apagarla es como se para una regla que hace daño. Si lo que
                # tenía en cola corriera igual, apagarla no pararía nada hasta
                # que se vaciara la cola.
                fila.estado = "descartada"
                fila.error = "La regla se apagó o se borró antes de que le llegara la hora"
            else:
                traza = motor.ejecutar(
                    uow.db,
                    regla,
                    valores=dict(fila.valores or {}),
                    objeto=fila.objeto,
                    registro_id=fila.registro_id,
                    ejecutores=ejecutores_mod.construir(uow),
                )
                uow.db.flush()
                fila.estado = "hecha"
                fila.ejecucion_id = traza.id
            fila.intentos += 1
            fila.terminada_at = ahora_utc()
        except Exception as exc:
            # Se deja que la transacción se deshaga entera —nada a medias— y se
            # cuenta el intento aparte, fuera de ella.
            raise _FalloDeEjecucion(identificador, exc) from exc
    return "atendida", identificador


class _FalloDeEjecucion(Exception):
    def __init__(self, identificador: UUID, causa: Exception) -> None:
        super().__init__(str(causa))
        self.identificador = identificador
        self.causa = causa


def _apuntar_fallo(tenant_id: UUID, identificador: UUID, error: str) -> None:
    from crmcore.db.uow import unidad_de_trabajo
    from crmcore.tenancy.context import con_contexto

    with (
        con_contexto(tenant_id=tenant_id, origen="automatizacion"),
        unidad_de_trabajo(tenant_id) as uow,
    ):
        fila = uow.db.get(EjecucionPendiente, identificador)
        if fila is None:
            return
        fila.intentos += 1
        fila.error = error[:2000]
        if fila.intentos >= _ajuste("automatizacion_pendientes_max_intentos", uow.db):
            fila.estado = "fallida"
            fila.terminada_at = ahora_utc()
            return
        # Se aparta un rato, más cuanto más falla: reintentarla en el acto
        # gastaría todos los intentos en un segundo contra la misma avería, y
        # dejaría esperando al resto de la cola.
        fila.ejecutar_at = ahora_utc() + timedelta(
            seconds=_ajuste("automatizacion_pendientes_revisar_s", uow.db) * fila.intentos
        )


def ejecutar_pendientes(tenant_id: UUID) -> dict[str, Any]:
    """Atiende la cola de un tenant, hasta el lote de cada vuelta."""
    from crmcore.db.session import sesion

    with sesion(tenant_id) as db:
        lote = _ajuste("automatizacion_pendientes_lote", db)
    atendidas, fallos = 0, []
    for _ in range(lote):
        try:
            estado, _id = _atender_una(tenant_id)
        except _FalloDeEjecucion as fallo:
            _apuntar_fallo(
                tenant_id, fallo.identificador, f"{type(fallo.causa).__name__}: {fallo.causa}"
            )
            fallos.append({"pendiente": str(fallo.identificador), "error": str(fallo.causa)[:200]})
            continue
        if estado == "vacia":
            break
        atendidas += 1
    return {"atendidas": atendidas, "fallos": fallos}


def tenants_con_trabajo() -> list[UUID]:
    """Los tenants con algo que hacer: cola vencida o programadas activas.

    De las propias tablas del servicio: la lista de tenants es de otro servicio
    y no se lee desde aquí. Uno sin nada pendiente no cuesta ni una consulta.
    """
    from crmcore.db.session import sesion

    ahora = ahora_utc()
    with sesion(sistema=True) as db:
        cola = db.execute(
            select(EjecucionPendiente.tenant_id)
            .where(
                EjecucionPendiente.estado == "pendiente",
                EjecucionPendiente.ejecutar_at <= ahora,
            )
            .distinct()
        ).all()
        reloj = db.execute(
            select(Automatizacion.tenant_id)
            .where(
                Automatizacion.activa.is_(True),
                Automatizacion.disparador == "programada",
                Automatizacion.deleted_at.is_(None),
                or_(
                    Automatizacion.proxima_ejecucion_at.is_(None),
                    Automatizacion.proxima_ejecucion_at <= ahora,
                    Automatizacion.proxima_segun.is_distinct_from(Automatizacion.programacion),
                ),
            )
            .distinct()
        ).all()
    return sorted({t for (t,) in cola} | {t for (t,) in reloj}, key=str)


def una_vuelta(tenant_id: UUID) -> dict[str, Any]:
    """Lo que hace el planificador por un tenant: el reloj y luego la cola.

    En ese orden, para que lo que el reloj encola en esta vuelta corra ya en
    ella y no espere a la siguiente.
    """
    from crmcore.db.uow import unidad_de_trabajo
    from crmcore.tenancy.context import con_contexto

    with (
        con_contexto(tenant_id=tenant_id, origen="automatizacion"),
        unidad_de_trabajo(tenant_id) as uow,
    ):
        reloj = programar(uow)
    return {**reloj, **ejecutar_pendientes(tenant_id)}


def tareas() -> list[Any]:
    """La tarea periódica del servicio, para el relevo de tareas."""
    from crmcore.config import get_settings
    from crmcore.tareas import Tarea, por_tenant

    return [
        Tarea(
            "automation.planificador",
            float(get_settings().automatizacion_pendientes_revisar_s),
            por_tenant(tenants_con_trabajo, una_vuelta),
            # Al arrancar SÍ: lo que se quedó en la cola mientras el servicio
            # estaba parado es lo primero que hay que hacer.
            al_arrancar=True,
        )
    ]
