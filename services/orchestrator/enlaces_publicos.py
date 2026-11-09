"""Decidir una aprobación desde el correo, sin entrar al CRM (CRM-00.03.05.12).

El enlace ya existía —un token de un solo uso con su hash en la base— y no
servía para lo que dice su nombre: para canjearlo hacía falta una sesión con
permiso de decidir, buscada en el tenant de esa sesión, y no se mandaba ningún
correo. O sea, para decidir «sin entrar» había que entrar.

Aquí está lo que faltaba, en tres piezas:

  * **El envío.** Al abrirse una etapa, cada aprobador recibe su enlace por
    correo —si el ajuste `aprobacion_enlace_por_correo` está encendido—, y desde
    la ficha se puede pedir uno a mano. El correo lo manda identidad, que es
    quien sabe el buzón: aquí se emite un evento interno con el enlace.
  * **La puerta pública.** Ver lo mínimo de la aprobación y decidir, sin sesión.
    El token no lleva el tenant dentro: su hash es único en toda la tabla, así
    que se localiza con una lectura de sistema —sólo esa— y lo demás corre ya
    dentro del tenant del enlace, como cualquier otra petición.
  * **El mismo error para todo.** Inexistente, usado, caducado, de una etapa
    que ya se cerró o de una vuelta anterior: «ese enlace no sirve», sin más.
    Distinguirlos le diría a quien prueba tokens que ése existió.

Lo que NO hace, dicho por delante: el límite de intentos por IP no vive aquí
sino en el gateway, que es el único que ve la IP de verdad —detrás de él, todas
las peticiones llegan desde la suya—. Ver `crmcore.rutas_de_api.TOPES_POR_IP`.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import NoAutenticado
from crmcore.logging import get_logger
from sqlalchemy import select

from services.orchestrator import aprobaciones as apr

logger = get_logger(__name__)

# Cuántos datos del contexto se enseñan en la página pública y en el correo.
# Es el contexto «para decidir sin abrir otra pantalla» (CRM-00.03.05.13), pero
# en una página sin sesión se recorta: lo justo para saber qué se firma.
_MAXIMO_DATOS = 12
_MAXIMO_TEXTO = 300


def _invalido() -> NoAutenticado:
    return NoAutenticado(
        "Ese enlace no sirve: puede haberse usado ya o haber caducado.",
        error_code="aprobacion.enlace_invalido",
    )


def url_del_enlace(token: str) -> str:
    from crmcore.config import get_settings

    base = str(get_settings().front_base_url or "").rstrip("/")
    return f"{base}/decidir?t={token}"


def _datos_visibles(contexto: dict[str, Any] | None) -> dict[str, Any]:
    """El contexto sin lo interno y sin estructuras: valores que se leen."""
    salida: dict[str, Any] = {}
    for clave, valor in (contexto or {}).items():
        if str(clave).startswith("_"):
            continue
        if isinstance(valor, (dict, list)):
            continue
        if isinstance(valor, str):
            valor = valor[:_MAXIMO_TEXTO]
        salida[str(clave)] = valor
        if len(salida) >= _MAXIMO_DATOS:
            break
    return salida


# ── El envío ──────────────────────────────────────────────────────────────


def enviar_enlace(
    uow: UnidadDeTrabajo,
    solicitud: apr.SolicitudAprobacion,
    etapa: apr.EtapaAprobacion,
    titular_id: UUID,
    *,
    validez_horas: int,
) -> tuple[str, str]:
    """Emite el enlace de un aprobador y encola su correo. Devuelve (token, url)."""
    _, token = apr.emitir_enlace(
        uow, etapa_id=etapa.id, titular_id=titular_id, validez_horas=validez_horas
    )
    url = url_del_enlace(token)
    datos = _datos_visibles(solicitud.contexto)
    lineas = [f"{clave}: {valor}" for clave, valor in datos.items()]
    titulo = f"Te toca decidir: {solicitud.titulo or solicitud.politica}"
    cuerpo = "\n".join(
        [
            f"Etapa «{etapa.nombre}» de la aprobación «{solicitud.titulo or solicitud.politica}».",
            *lineas,
            "",
            "Puedes aprobar, rechazar o pedir cambios sin entrar al CRM desde este enlace:",
            url,
            "",
            f"Sirve una sola vez y caduca en {validez_horas} horas. "
            "No lo reenvíes: decide en tu nombre.",
        ]
    )
    uow.emitir(
        "approval.link.issued",
        subject=("aprobacion", solicitud.id),
        data={
            "objeto_tipo": "aprobacion",
            "objeto_id": str(solicitud.id),
            "titular_id": str(titular_id),
            "titulo": titulo,
            "cuerpo": cuerpo,
            "canales": ["correo"],
        },
    )
    return token, url


def avisar_etapa(
    uow: UnidadDeTrabajo,
    solicitud: apr.SolicitudAprobacion,
    etapa: apr.EtapaAprobacion,
) -> int:
    """Al abrirse una etapa, un enlace por aprobador. Devuelve cuántos salieron.

    Apagado por el ajuste no sale ninguno —el enlace se pide entonces desde la
    ficha—. Los ajustes se leen UNA vez por etapa, no una por aprobador.
    """
    from crmcore.runtime.settings import efectivo

    if not bool(efectivo("aprobacion_enlace_por_correo", uow.db)):
        return 0
    horas = int(efectivo("aprobacion_enlace_validez_horas", uow.db))
    enviados = 0
    for aprobador in etapa.aprobadores or []:
        try:
            titular = UUID(str(aprobador))
        except ValueError:
            logger.warning("aprobacion.enlace.aprobador_invalido", valor=str(aprobador)[:60])
            continue
        enviar_enlace(uow, solicitud, etapa, titular, validez_horas=horas)
        enviados += 1
    return enviados


# ── La puerta pública ─────────────────────────────────────────────────────


def _localizar(token: str) -> tuple[UUID, UUID] | None:
    """(tenant, titular) del enlace, leyendo por su hash. Sin nada más.

    Es la única lectura sin tenant de todo esto, y lee dos columnas de una fila
    que se localiza por un valor que sólo conoce quien tiene el token.
    """
    from crmcore.db.session import sesion

    if not token or len(token) > 200:
        return None
    with sesion(sistema=True) as db:
        fila = db.execute(
            select(apr.EnlaceDecision.tenant_id, apr.EnlaceDecision.titular_id).where(
                apr.EnlaceDecision.hash_token == apr._hash(token)
            )
        ).first()
    return (fila[0], fila[1]) if fila else None


def _vigente(
    uow: UnidadDeTrabajo, token: str, *, bloquear: bool = False
) -> tuple[apr.EnlaceDecision, apr.SolicitudAprobacion, apr.EtapaAprobacion]:
    """El enlace, si todavía sirve para decidir. Si no, el error de siempre.

    Además de un solo uso y caducidad, que ya comprobaba el canje, aquí se exige
    que la etapa del enlace **siga siendo la que se vota**: un enlace de la
    primera etapa no puede votar en la segunda aunque el titular esté en las
    dos, ni uno de antes de una reaprobación puede firmar lo que cambió después
    de mandarlo.
    """
    consulta = select(apr.EnlaceDecision).where(
        apr.EnlaceDecision.tenant_id == uow.tenant_id,
        apr.EnlaceDecision.hash_token == apr._hash(token),
    )
    if bloquear:
        # Dos clics seguidos —o el escáner del correo y la persona— no pueden
        # canjear el mismo enlace dos veces: el segundo espera y ya lo ve usado.
        consulta = consulta.with_for_update()
    fila = uow.db.execute(consulta).scalar_one_or_none()
    ahora = apr._ahora()
    if fila is None or fila.usado_at is not None or apr._con_tz(fila.caduca_at) < ahora:
        raise _invalido()
    etapa = uow.db.get(apr.EtapaAprobacion, fila.etapa_id)
    solicitud = uow.db.get(apr.SolicitudAprobacion, etapa.solicitud_id) if etapa else None
    if (
        etapa is None
        or solicitud is None
        or solicitud.estado != "pendiente"
        or solicitud.etapa_actual != etapa.orden
        or etapa.estado != "pendiente"
    ):
        raise _invalido()
    abierta = apr._con_tz(etapa.abierta_at)
    creado = apr._con_tz(fila.created_at)
    if abierta and creado and creado < abierta:
        raise _invalido()
    titular = apr.puede_decidir(
        uow.db, uow.tenant_id, etapa, fila.titular_id, politica=solicitud.politica
    )
    if titular is None:
        raise _invalido()
    ya = uow.db.execute(
        select(apr.DecisionAprobacion.id).where(
            apr.DecisionAprobacion.etapa_id == etapa.id,
            apr.DecisionAprobacion.titular_id == titular,
            apr.DecisionAprobacion.vuelta == etapa.vuelta,
        )
    ).first()
    if ya is not None:
        raise _invalido()
    return fila, solicitud, etapa


def ver(token: str) -> dict[str, Any]:
    """Lo mínimo para decidir. Ni identificadores ni quién más vota."""
    from crmcore.db.uow import unidad_de_trabajo
    from crmcore.tenancy.context import con_contexto

    propio = _localizar(token)
    if propio is None:
        raise _invalido()
    tenant_id, titular_id = propio
    with (
        con_contexto(tenant_id=tenant_id, user_id=titular_id, origen="correo"),
        unidad_de_trabajo(tenant_id) as uow,
    ):
        fila, solicitud, etapa = _vigente(uow, token)
        return {
            "titulo": solicitud.titulo or solicitud.politica,
            "objeto": solicitud.objeto,
            "etapa": etapa.nombre,
            "datos": _datos_visibles(solicitud.contexto),
            "caduca_at": apr._con_tz(fila.caduca_at).isoformat(),  # type: ignore[union-attr]
            "decisiones": list(apr.DECISIONES),
        }


def decidir(token: str, *, decision: str, comentario: str = "") -> dict[str, Any]:
    """Canjea el enlace y decide como su titular, con `via="correo"`."""
    from crmcore.db.uow import unidad_de_trabajo
    from crmcore.tenancy.context import con_contexto

    propio = _localizar(token)
    if propio is None:
        raise _invalido()
    tenant_id, titular_id = propio
    with (
        con_contexto(tenant_id=tenant_id, user_id=titular_id, origen="correo"),
        unidad_de_trabajo(tenant_id) as uow,
    ):
        _vigente(uow, token, bloquear=True)
        resultado = apr.decidir_con_enlace(
            uow, token, decision=decision, comentario=comentario, via="correo"
        )
        # Sólo el desenlace: el estado entero lleva quién más vota y qué dijo,
        # y eso no es de quien tiene el enlace.
        return {"decision": decision, "estado": resultado.get("estado")}
