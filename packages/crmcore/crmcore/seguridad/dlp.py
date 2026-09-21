"""Control de fuga de datos y comportamiento anómalo
(CRM-00.05.03.06, CRM-00.05.03.08).

El robo de datos de un CRM casi nunca es una intrusión: es alguien de dentro,
con permiso para leer, que se lleva más de lo que le toca. Los permisos no lo
ven —está haciendo exactamente lo que puede hacer— y por eso hace falta mirar
**cuánto** y **cuándo**, no solo **qué**.

Dos decisiones que separan esto de una alarma que nadie mira:

**El umbral se mide contra el patrón de cada uno, no contra un número.**
Cincuenta registros son una exportación normal en un tenant con doscientos
clientes y un incidente en uno con veinte mil; y dentro del mismo tenant, lo
normal de quien lleva la migración no es lo normal de un comercial. Un número
fijo produce o ruido o silencio, y las dos cosas acaban en «esto siempre salta».

**Bloquear es opcional y avisar no.** Bloquear una migración legítima cuesta
tanto como dejar pasar una fuga, y esa decisión es del cliente. Lo que no es
opcional es que quede registrado: una exportación masiva sin rastro es la que no
se puede investigar después.

El patrón sale del **audit trail**, que ya existe y ya es inalterable. No hay
tabla nueva de «actividad de usuario» a propósito: sería un segundo registro de
lo mismo que podría discrepar del primero, y el primero es el que tiene la
cadena de hashes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from crmcore.audit.modelos import ApunteAuditoria
from crmcore.errors import Prohibido
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Acciones que sacan datos del sistema. Se nombran porque no toda escritura en
# el audit trail es una salida de datos: cambiar el nombre de una cuenta queda
# registrado y no se lleva nada.
ACCIONES_DE_SALIDA = frozenset(
    {
        "datos.exportados",
        "adjunto.descargado",
        "informe.exportado",
        "tenant.exportacion",
    }
)

# La acción con la que se apunta cada salida de datos.
ACCION_EXPORTACION = "datos.exportados"


@dataclass(slots=True)
class Veredicto:
    """Qué se ha decidido sobre una exportación, y por qué.

    Lleva el porqué siempre, incluso cuando permite: es lo que convierte el
    registro en algo investigable meses después, cuando quien lo mire no tenga
    ni el contexto ni a la persona delante.
    """

    permitido: bool
    motivo: str = ""
    anomalia: bool = False
    # Lo medido, para poder revisar la decisión sin reconstruirla.
    registros: int = 0
    media_propia: float | None = None
    exportaciones_ultima_hora: int = 0


def comprobar_exportacion(
    db: Session,
    *,
    tenant_id: UUID,
    usuario_id: UUID | None,
    registros: int,
    objeto: str,
    ip: str = "",
) -> Veredicto:
    """Decide si esta exportación pasa, y deja constancia pase lo que pase.

    Se llama **antes** de servir los datos. Comprobarlo después serviría para el
    informe forense y no para impedir nada, que es la mitad de lo que se pide.
    """
    from crmcore.config import get_settings

    s = get_settings()
    if not s.dlp_enabled:
        return Veredicto(permitido=True, motivo="control desactivado", registros=registros)

    ultima_hora = _exportaciones_desde(
        db, tenant_id, usuario_id, datetime.now(timezone.utc) - timedelta(hours=1)
    )
    media = _media_por_exportacion(db, tenant_id, usuario_id, dias=s.dlp_dias_patron)

    veredicto = Veredicto(
        permitido=True,
        registros=registros,
        media_propia=media,
        exportaciones_ultima_hora=ultima_hora,
    )

    if registros > s.dlp_max_registros_export:
        veredicto.permitido = not s.dlp_bloquear
        veredicto.anomalia = True
        veredicto.motivo = (
            f"{registros} registros en una exportación, sobre el tope de "
            f"{s.dlp_max_registros_export}"
        )
    elif ultima_hora >= s.dlp_max_exports_hora:
        # Quien de verdad se está llevando datos trocea para no disparar el tope
        # por volumen: contar exportaciones es lo que ve ese caso.
        veredicto.permitido = not s.dlp_bloquear
        veredicto.anomalia = True
        veredicto.motivo = (
            f"{ultima_hora} exportaciones en la última hora, sobre el tope de "
            f"{s.dlp_max_exports_hora}"
        )
    elif media is not None and registros > media * s.dlp_factor_anomalia:
        # Sale de su patrón. Esto AVISA pero no bloquea aunque el bloqueo esté
        # activo: salirse de lo habitual no es ilegítimo —el día del cierre
        # todo el mundo exporta más— y cortarlo pararía trabajo real.
        veredicto.anomalia = True
        veredicto.motivo = (
            f"{registros} registros frente a una media propia de {media:.0f}: "
            f"{registros / media:.1f} veces lo habitual"
        )

    _registrar(
        db,
        tenant_id=tenant_id,
        usuario_id=usuario_id,
        objeto=objeto,
        ip=ip,
        veredicto=veredicto,
    )
    if not veredicto.permitido:
        raise Prohibido(
            "Una política de protección de datos impide esta exportación",
            error_code="dlp.bloqueada",
            detalle={"motivo": veredicto.motivo, "registros": registros},
        )
    return veredicto


def _exportaciones_desde(
    db: Session, tenant_id: UUID, usuario_id: UUID | None, desde: datetime
) -> int:
    return int(
        db.execute(
            select(func.count())
            .select_from(ApunteAuditoria)
            .where(
                ApunteAuditoria.tenant_id == tenant_id,
                ApunteAuditoria.actor_id == usuario_id,
                ApunteAuditoria.accion.in_(ACCIONES_DE_SALIDA),
                ApunteAuditoria.created_at >= desde,
            )
        ).scalar_one()
        or 0
    )


def _media_por_exportacion(
    db: Session, tenant_id: UUID, usuario_id: UUID | None, *, dias: int
) -> float | None:
    """Cuántos registros se lleva esta persona en una exportación, de media.

    Devuelve `None` cuando no hay historial suficiente, y quien llama **no
    avisa** en ese caso: con dos datos cualquier tercero parece una anomalía, y
    el primer día de alguien sería siempre una alerta. Un sistema que avisa de
    todo el mundo el primer día es uno que se desactiva la primera semana.
    """
    from crmcore.config import get_settings

    desde = datetime.now(timezone.utc) - timedelta(days=dias)
    filas = (
        db.execute(
            select(ApunteAuditoria.datos).where(
                ApunteAuditoria.tenant_id == tenant_id,
                ApunteAuditoria.actor_id == usuario_id,
                ApunteAuditoria.accion == ACCION_EXPORTACION,
                ApunteAuditoria.created_at >= desde,
            )
        )
        .scalars()
        .all()
    )
    cantidades = [
        int(d.get("registros", 0)) for d in filas if isinstance(d, dict) and d.get("registros")
    ]
    if len(cantidades) < get_settings().dlp_minimo_para_patron:
        return None
    return sum(cantidades) / len(cantidades)


def _registrar(
    db: Session,
    *,
    tenant_id: UUID,
    usuario_id: UUID | None,
    objeto: str,
    ip: str,
    veredicto: Veredicto,
) -> None:
    """Apunta la exportación en el audit trail, permitida o no.

    También las permitidas, y sobre todo esas: el patrón de mañana se calcula
    con lo de hoy, y apuntar solo lo sospechoso haría que la media fuera la
    media de lo sospechoso.
    """
    from crmcore.audit import registrar

    registrar(
        db,
        accion=ACCION_EXPORTACION,
        objeto=objeto,
        objeto_id=None,
        datos={
            "registros": veredicto.registros,
            "permitido": veredicto.permitido,
            "anomalia": veredicto.anomalia,
            "motivo": veredicto.motivo,
            "media_propia": veredicto.media_propia,
            "exportaciones_ultima_hora": veredicto.exportaciones_ultima_hora,
            "ip": ip,
            # El actor lo pone la cadena desde el contexto; aquí se apunta
            # además dentro del dato para poder calcular el patrón sin depender
            # de que el contexto estuviera bien puesto en cada llamada.
            "usuario_id": str(usuario_id) if usuario_id else None,
        },
        tenant_id=tenant_id,
    )
    if veredicto.anomalia:
        logger.warning(
            "dlp.anomalia",
            usuario=str(usuario_id),
            objeto=objeto,
            registros=veredicto.registros,
            motivo=veredicto.motivo,
            bloqueada=not veredicto.permitido,
        )


def anomalias(db: Session, tenant_id: UUID, *, dias: int = 7) -> list[dict[str, Any]]:
    """Lo que se ha salido del patrón en los últimos días.

    Se calcula leyendo el audit trail, no una tabla aparte de alertas: una tabla
    de alertas es un segundo registro de lo mismo que puede discrepar del
    primero, y el primero es el que tiene la cadena de hashes.
    """
    desde = datetime.now(timezone.utc) - timedelta(days=dias)
    filas = (
        db.execute(
            select(ApunteAuditoria)
            .where(
                ApunteAuditoria.tenant_id == tenant_id,
                ApunteAuditoria.accion == ACCION_EXPORTACION,
                ApunteAuditoria.created_at >= desde,
            )
            .order_by(ApunteAuditoria.created_at.desc())
        )
        .scalars()
        .all()
    )
    return [
        {
            "cuando": f.created_at.isoformat(),
            "usuario_id": str(f.actor_id) if f.actor_id else None,
            "objeto": f.objeto,
            "registros": (f.datos or {}).get("registros"),
            "motivo": (f.datos or {}).get("motivo"),
            "bloqueada": not (f.datos or {}).get("permitido", True),
            "ip": (f.datos or {}).get("ip"),
        }
        for f in filas
        if (f.datos or {}).get("anomalia")
    ]
