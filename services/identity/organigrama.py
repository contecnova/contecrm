"""Publicar la posición de una persona en la organización (CRM-00.03.05.07).

Quién manda sobre quién y quién tiene qué rol vive en `membresias`, dentro del
esquema de `identity`. Quien lo necesita para decidir **a quién le toca aprobar**
es el orquestador, y ningún servicio lee el esquema de otro: por eso se publica.

Se emite desde **todos** los sitios que tocan una membresía —alta manual, alta
JIT desde el IdP, SCIM, cambio de roles, baja—, y no solo desde el alta. Un
organigrama que se publica en el alta y no en el ascenso es peor que no tenerlo:
las aprobaciones seguirían yendo al jefe anterior, con toda la apariencia de
funcionar.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado
from crmcore.logging import get_logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.identity.modelos import Membresia, Usuario

logger = get_logger(__name__)

ORIGEN_MANUAL = "manual"
ORIGEN_SCIM = "scim"


def publicar(uow: UnidadDeTrabajo, tenant_id: UUID, usuario_id: UUID) -> None:
    """Emite la posición actual de la persona, tal como está en la base.

    Se lee de la base en vez de recibirla por parámetro **a propósito**: quien
    llama acaba de cambiar un campo y conoce ese, no los otros tres. Pasarlos a
    mano es cómo se publica un organigrama con el rol nuevo y el superior viejo.
    """
    membresia = uow.db.execute(
        select(Membresia).where(
            Membresia.tenant_id == tenant_id, Membresia.usuario_id == usuario_id
        )
    ).scalar_one_or_none()
    if membresia is None:
        return

    uow.emitir(
        "user.org.changed",
        subject=("usuario", usuario_id),
        data={
            "user_id": str(usuario_id),
            "roles": list(membresia.roles or []),
            "superior_id": str(membresia.superior_id) if membresia.superior_id else "",
            "unidad_id": str(membresia.business_unit_id) if membresia.business_unit_id else "",
            "activa": bool(membresia.activa),
            # Los atributos de ABAC viajan porque de ellos salen las reglas de
            # aprobación por territorio o por país: sin ellos, «que lo apruebe
            # el responsable de la zona» habría que resolverlo llamando a
            # identity en mitad de una transacción de otro servicio.
            "atributos": dict(membresia.atributos or {}),
        },
        # SIN `dedup_key` a propósito: la derivada lleva el momento, así que
        # cada cambio es un hecho distinto y un reenvío del mismo sigue siendo
        # el mismo. Hasta el 10-11-2026 era `org:{tenant}:{usuario}`, fija por
        # persona, y los consumidores —que deduplican por clave— aplicaban el
        # primer evento de cada persona y descartaban todos los siguientes: un
        # ascenso no llegaba nunca al organigrama replicado.
    )


# ── Fijarlo desde la pantalla (Administrar › Organigrama) ─────────────────
#
# Hasta el 10-11-2026 nada escribía `superior_id`: SCIM ignoraba el `manager`
# del directorio, el SSO no lo trae y no había pantalla. El organigrama
# replicado estaba vacío, y con él la aprobación de presupuestos no tenía a
# quién pedírsela y la revisión de accesos caía entera en el revisor por
# defecto.


def _ajuste(clave: str, db: Session) -> Any:
    from crmcore.config import get_settings
    from crmcore.runtime.settings import efectivo

    return efectivo(clave, db, default=getattr(get_settings(), clave, None))


def _membresia(db: Session, tenant_id: UUID, usuario_id: UUID) -> Membresia | None:
    return db.execute(
        select(Membresia).where(
            Membresia.tenant_id == tenant_id, Membresia.usuario_id == usuario_id
        )
    ).scalar_one_or_none()


def _mapa(db: Session, tenant_id: UUID) -> dict[UUID, UUID | None]:
    """Quién depende de quién en el tenant, en una sola consulta."""
    return {
        u: s
        for u, s in db.execute(
            select(Membresia.usuario_id, Membresia.superior_id).where(
                Membresia.tenant_id == tenant_id
            )
        ).all()
    }


def _camino_del_ciclo(
    mapa: dict[UUID, UUID | None], persona: UUID, superior: UUID | None
) -> list[UUID]:
    """Si colgar `persona` de `superior` cierra un círculo, el círculo; si no, [].

    Se sube desde el superior nuevo: si por el camino aparece la persona, el
    superior está dentro de su propio equipo. Los vistos cortan un ciclo que ya
    existiera arriba —de datos viejos o del directorio— sin colgarse.
    """
    camino: list[UUID] = []
    actual, vistos = superior, set()
    while actual is not None and actual not in vistos:
        camino.append(actual)
        if actual == persona:
            return camino
        vistos.add(actual)
        actual = mapa.get(actual)
    return []


def arbol(db: Session, tenant_id: UUID) -> dict[str, Any]:
    """Todas las personas del tenant con su superior y de dónde salió.

    El árbol lo compone la pantalla: aquí van filas planas, que es lo que sirve
    igual para pintar el árbol que para buscar a alguien.
    """
    tope = int(_ajuste("organigrama_tope_personas", db) or 5000)
    filas = db.execute(
        select(Membresia, Usuario)
        .join(Usuario, Usuario.id == Membresia.usuario_id)
        .where(Membresia.tenant_id == tenant_id)
        .order_by(Usuario.nombre, Usuario.email)
        .limit(tope + 1)
    ).all()
    return {
        "personas": [_persona(m, u) for m, u in filas[:tope]],
        "truncado": len(filas) > tope,
        "tope": tope,
        "externo_manda": bool(_ajuste("organigrama_externo_manda", db)),
    }


def _persona(m: Membresia, u: Usuario) -> dict[str, Any]:
    return {
        "usuario_id": str(m.usuario_id),
        "nombre": u.nombre or u.email,
        "email": u.email,
        "activa": bool(m.activa),
        "roles": list(m.roles or []),
        "superior_id": str(m.superior_id) if m.superior_id else None,
        "origen": m.superior_origen or "",
        "fijado_at": m.superior_fijado_at.isoformat() if m.superior_fijado_at else None,
        "fijado_por": str(m.superior_fijado_por) if m.superior_fijado_por else None,
    }


def _comprobar_superior(
    db: Session, tenant_id: UUID, persona: UUID, superior_id: UUID | None
) -> None:
    if superior_id is None:
        return
    if superior_id == persona:
        raise ErrorValidacion(
            "Una persona no puede ser su propio superior.",
            error_code="organigrama.a_si_mismo",
        )
    superior = _membresia(db, tenant_id, superior_id)
    if superior is None:
        raise NoEncontrado(
            "El superior no pertenece a esta empresa.",
            error_code="organigrama.superior_desconocido",
        )
    if not superior.activa:
        raise ErrorValidacion(
            "El superior está dado de baja: no podría aprobar nada.",
            error_code="organigrama.superior_inactivo",
        )


def _aplicar(
    uow: UnidadDeTrabajo,
    tenant_id: UUID,
    membresia: Membresia,
    superior_id: UUID | None,
    *,
    origen: str,
    por: UUID | None,
) -> None:
    from crmcore.audit import registrar

    anterior = membresia.superior_id
    origen_anterior = membresia.superior_origen or ""
    membresia.superior_id = superior_id
    membresia.superior_origen = origen if superior_id else ""
    membresia.superior_fijado_at = datetime.now(timezone.utc)
    membresia.superior_fijado_por = por
    uow.db.flush()
    registrar(
        uow.db,
        accion="organigrama.superior",
        objeto="usuario",
        objeto_id=membresia.usuario_id,
        datos={
            "anterior": str(anterior) if anterior else None,
            "nuevo": str(superior_id) if superior_id else None,
            "origen": origen,
            "origen_anterior": origen_anterior,
        },
        tenant_id=tenant_id,
    )
    publicar(uow, tenant_id, membresia.usuario_id)
    # El superior también: la cadena de mando replicada se corta en quien no
    # consta, y una raíz que nunca cambió nunca se había publicado.
    if superior_id:
        publicar(uow, tenant_id, superior_id)


def fijar_superior(
    uow: UnidadDeTrabajo,
    tenant_id: UUID,
    usuario_id: UUID,
    superior_id: UUID | None,
    *,
    por: UUID,
) -> dict[str, Any]:
    """Cuelga a una persona —con todo su equipo— de otra, o la deja de raíz."""
    membresia = _membresia(uow.db, tenant_id, usuario_id)
    if membresia is None:
        raise NoEncontrado(
            "Esa persona no pertenece a esta empresa.",
            error_code="organigrama.persona_desconocida",
        )
    _comprobar_superior(uow.db, tenant_id, usuario_id, superior_id)
    ciclo = _camino_del_ciclo(_mapa(uow.db, tenant_id), usuario_id, superior_id)
    if ciclo:
        raise Conflicto(
            "Ese superior depende, directa o indirectamente, de esta persona: "
            "colgarla de él cerraría un círculo.",
            error_code="organigrama.ciclo",
            detalle={"camino": [str(c) for c in ciclo]},
        )
    _aplicar(uow, tenant_id, membresia, superior_id, origen=ORIGEN_MANUAL, por=por)
    usuario = uow.db.get(Usuario, usuario_id)
    return _persona(membresia, usuario)


def mover_equipo(
    uow: UnidadDeTrabajo,
    tenant_id: UUID,
    de_id: UUID,
    a_id: UUID | None,
    *,
    por: UUID,
) -> dict[str, Any]:
    """Pasa a todos los que dependen directamente de `de_id` a depender de `a_id`.

    Es lo que se hace cuando un responsable se va o cambia de puesto. Se
    comprueba **todo antes de tocar nada**: si uno de ellos cerraría un círculo
    —el destino está dentro de su equipo—, no se mueve ninguno; un equipo
    movido a medias es peor que uno sin mover.
    """
    if a_id == de_id:
        raise ErrorValidacion(
            "El equipo ya depende de esa persona.", error_code="organigrama.mismo_destino"
        )
    if _membresia(uow.db, tenant_id, de_id) is None:
        raise NoEncontrado(
            "Esa persona no pertenece a esta empresa.",
            error_code="organigrama.persona_desconocida",
        )
    directos = list(
        uow.db.execute(
            select(Membresia).where(
                Membresia.tenant_id == tenant_id, Membresia.superior_id == de_id
            )
        ).scalars()
    )
    mapa = _mapa(uow.db, tenant_id)
    for m in directos:
        _comprobar_superior(uow.db, tenant_id, m.usuario_id, a_id)
        ciclo = _camino_del_ciclo(mapa, m.usuario_id, a_id)
        if ciclo:
            raise Conflicto(
                "El destino está dentro del equipo que se mueve: cerraría un círculo.",
                error_code="organigrama.ciclo",
                detalle={"camino": [str(c) for c in ciclo], "persona": str(m.usuario_id)},
            )
    for m in directos:
        _aplicar(uow, tenant_id, m, a_id, origen=ORIGEN_MANUAL, por=por)
    return {"movidas": len(directos)}


# ── Lo que manda el directorio (SCIM) ─────────────────────────────────────


def _id_del_manager(valor: Any) -> str:
    """El `manager` de la extensión de empresa (RFC 7643 §4.3), venga como venga.

    Entra ID manda el identificador a secas en `value` de la operación; Okta y
    el alta completa, un objeto `{"value": …}`.
    """
    if isinstance(valor, dict):
        valor = valor.get("value")
    return str(valor or "").strip()


def superior_desde_el_directorio(
    uow: UnidadDeTrabajo, tenant_id: UUID, membresia: Membresia, valor: Any
) -> None:
    """Aplica el superior que manda el IdP, si le toca mandar.

    Nunca falla: un IdP manda el `manager` de gente que aún no ha
    aprovisionado, y rechazar el alta entera por eso rompería el ciclo. Lo que
    no se puede aplicar se registra y se ignora.
    """
    if membresia.superior_origen == ORIGEN_MANUAL and not _ajuste(
        "organigrama_externo_manda", uow.db
    ):
        logger.info("organigrama.scim_no_pisa_lo_manual", usuario=str(membresia.usuario_id))
        return
    texto = _id_del_manager(valor)
    superior: UUID | None = None
    if texto:
        try:
            superior = UUID(texto)
            _comprobar_superior(uow.db, tenant_id, membresia.usuario_id, superior)
        except (ValueError, ErrorValidacion, NoEncontrado):
            logger.warning("organigrama.scim_manager_desconocido", manager=texto)
            return
        if _camino_del_ciclo(_mapa(uow.db, tenant_id), membresia.usuario_id, superior):
            logger.warning("organigrama.scim_cerraria_ciclo", manager=texto)
            return
    if superior == membresia.superior_id and (
        superior is None or membresia.superior_origen == ORIGEN_SCIM
    ):
        return
    _aplicar(uow, tenant_id, membresia, superior, origen=ORIGEN_SCIM, por=None)
