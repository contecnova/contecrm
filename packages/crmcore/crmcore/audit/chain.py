"""Traza de auditoría encadenada y verificable (CRM-00.05.04.01).

Cada apunte lleva el hash del anterior del mismo tenant. Eso da dos propiedades
que un log normal no tiene:

  * **Detección de manipulación.** Cambiar un apunte cambia su hash y rompe el
    enlace con el siguiente. `verificar()` recorre la cadena y dice exactamente
    en qué secuencia se rompió.
  * **Detección de borrado.** La secuencia es un entero consecutivo con índice
    único: un hueco se ve sin recalcular nada.

Lo que **no** da, y conviene decirlo: quien tenga permiso de escritura en la
tabla puede reescribir la cadena entera desde el punto que altere. Contra eso
está el trigger de solo-inserción (`deploy/sql/auditoria_inmutable.sql`), que
impide UPDATE y DELETE incluso al dueño de la tabla, y el anclaje periódico del
último hash en un almacenamiento externo. Esto último es lo único que protege
frente a alguien con acceso total a la base, y por eso la operación de anclaje
se documenta en el manual de operación en vez de dejarse implícita.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from crmcore.audit.modelos import ApunteAuditoria, CambioCampo
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Hash del apunte cero: el ancla de la cadena de cada tenant.
HASH_GENESIS = "0" * 64

# Lo que se guarda en el hueco del hash cuando la cadena está apagada
# (`AUDIT_HASH_CHAIN=false`). Un valor reconocible y no un vacío: con cadena
# vacía, `verificar` no podría distinguir «aquí no se encadenó a propósito» de
# «aquí alguien borró el hash», y la segunda lectura es una acusación.
SIN_CADENA = "sin-cadena".ljust(64, "-")

# Acciones que exigen justificación escrita. La lista es corta a propósito: si
# todo exigiera motivo, el campo se rellenaría con «.» y dejaría de significar
# nada.
EXIGEN_MOTIVO: frozenset[str] = frozenset(
    {
        "soporte.acceso_tenant",
        "datos.exportacion_masiva",
        "datos.restauracion",
        "usuario.suplantacion",
        "auditoria.purga",
        "tenant.offboarding",
    }
)


def _en_utc(momento: datetime) -> str:
    """El instante, siempre en UTC y en texto.

    Normalizar la zona es obligatorio, y costó descubrirlo: Postgres devuelve un
    `timestamptz` con el **desfase de la sesión** —`+02:00` en un servidor
    español—, no en UTC. El mismo instante daba dos textos distintos según si el
    apunte se acababa de escribir o se había releído de la base, así que el hash
    recalculado no coincidía nunca y el verificador declaraba rota una cadena
    intacta. Eso es peor que no verificar: es que nadie se crea el verificador.
    """
    return momento.astimezone(timezone.utc).isoformat()


def _hash_apunte(datos: dict[str, Any], hash_previo: str) -> str:
    """Hash del contenido más el enlace al anterior.

    `sort_keys` es obligatorio: sin él, dos serializaciones del mismo contenido
    en distinto orden dan hashes distintos y la verificación fallaría con la
    cadena intacta.
    """
    material = json.dumps(datos, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(f"{hash_previo}{material}".encode()).hexdigest()


def registrar(
    db: Session,
    *,
    accion: str,
    objeto: str,
    objeto_id: Any = None,
    datos: dict[str, Any] | None = None,
    motivo: str | None = None,
    tenant_id: UUID | None = None,
) -> ApunteAuditoria | None:
    """Añade un apunte a la cadena del tenant, o nada si está apagada.

    Se llama DENTRO de la transacción del cambio: si la operación se revierte,
    el apunte también. Un log que registra lo que no llegó a pasar es peor que
    no tenerlo, porque lleva a conclusiones falsas durante una investigación.
    """
    from crmcore.config import get_settings
    from crmcore.errors import ErrorValidacion
    from crmcore.tenancy.context import contexto_actual

    # `AUDIT_ENABLED` existía, estaba documentado y **no lo leía nadie**
    # (medido el 06-10-2026): ponerlo a `false` no apagaba nada. Ahora apaga, y
    # que esté apagado NO es invisible: el readiness del servicio lo dice, que
    # es lo único que convierte «sin auditoría» en una decisión y no en un
    # descubrimiento a los seis meses.
    #
    # Devuelve `None`, y se puede: ninguno de los 313 sitios que llaman aquí usa
    # el apunte que esto devolvía. Medido antes de cambiar la firma.
    s = get_settings()
    if not s.audit_enabled:
        return None

    ctx = contexto_actual()
    tenant_id = tenant_id or ctx.tenant_id
    if tenant_id is None:
        raise ErrorValidacion(
            "Un apunte de auditoría necesita tenant",
            error_code="auditoria.sin_tenant",
        )
    if accion in EXIGEN_MOTIVO and not (motivo or "").strip():
        raise ErrorValidacion(
            f"La acción «{accion}» exige una justificación escrita",
            error_code="auditoria.motivo_requerido",
        )

    # `FOR UPDATE` sobre el último apunte serializa a los concurrentes: dos
    # apuntes simultáneos del mismo tenant no pueden tomar la misma secuencia ni
    # encadenarse los dos al mismo previo. El índice único es la segunda red.
    ultimo = db.execute(
        select(ApunteAuditoria)
        .where(ApunteAuditoria.tenant_id == tenant_id)
        .order_by(ApunteAuditoria.secuencia.desc())
        .limit(1)
        .with_for_update()
    ).scalar_one_or_none()

    secuencia = (ultimo.secuencia + 1) if ultimo else 1
    hash_previo = ultimo.hash if ultimo else HASH_GENESIS
    momento = datetime.now(timezone.utc)

    contenido = {
        "secuencia": secuencia,
        "tenant_id": str(tenant_id),
        "accion": accion,
        "objeto": objeto,
        "objeto_id": str(objeto_id) if objeto_id else None,
        "actor_id": str(ctx.user_id) if ctx.user_id else None,
        "actor_real_id": str(ctx.actor_real_id) if ctx.actor_real_id else None,
        "origen": ctx.origen,
        "datos": datos or {},
        "motivo": motivo,
        # Se fija aquí y no con `now()` del servidor porque el hash tiene que
        # calcularse sobre el mismo valor que se guarda, y el del servidor no se
        # conoce hasta después del INSERT.
        "momento": _en_utc(momento),
    }

    apunte = ApunteAuditoria(
        secuencia=secuencia,
        tenant_id=tenant_id,
        accion=accion,
        objeto=objeto,
        objeto_id=str(objeto_id) if objeto_id else None,
        actor_id=ctx.user_id,
        actor_tipo="usuario" if ctx.user_id else "sistema",
        actor_real_id=ctx.actor_real_id,
        origen=ctx.origen,
        ip=str(ctx.extra.get("ip") or "") or None,
        request_id=ctx.request_id or None,
        datos=datos or {},
        motivo=motivo,
        hash_previo=hash_previo,
        # Con `AUDIT_HASH_CHAIN=false` se guarda el apunte pero no se encadena.
        # Lo que NO se quita es el `FOR UPDATE` ni la secuencia: sin el cerrojo,
        # dos apuntes simultáneos del mismo tenant tomarían la misma secuencia y
        # reventaría el índice único. Lo que ahorra el interruptor es un hash por
        # apunte, que es exactamente lo que dice que cuesta — y la secuencia
        # sigue cazando un borrado, que es la segunda red.
        hash=_hash_apunte(contenido, hash_previo) if s.audit_hash_chain else SIN_CADENA,
        # El MISMO instante que entró en el hash. Antes el hash llevaba un
        # `momento` que no se guardaba en ninguna parte —la columna la rellenaba
        # `now()` del servidor, con otro valor—, así que el contenido de un
        # apunte no se podía recalcular y `verificar` no podía detectar que
        # alguien lo hubiera editado. Comprobaba los enlaces y la secuencia, que
        # cazan un borrado o una inserción, pero no una modificación en su sitio.
        created_at=momento,
    )
    db.add(apunte)
    # Se vuelca aquí, y no es opcional. La sesión va con `autoflush=False`, así
    # que sin este flush la consulta del apunte anterior —la de arriba— no vería
    # los que se hayan añadido antes en esta misma transacción: dos apuntes
    # tomarían la MISMA secuencia y el índice único reventaría al confirmar, con
    # un error de clave duplicada a kilómetros del sitio que lo causó.
    #
    # Pasa en cuanto una operación audita dos veces, que es lo normal: una
    # fusión de cuentas anota el hecho y el deshacer, un bloqueo legal se pone y
    # se levanta, una baja de usuario audita la desactivación y el corte de
    # sesiones.
    db.flush()
    return apunte


def registrar_cambios(
    db: Session,
    *,
    objeto: str,
    objeto_id: Any,
    anterior: dict[str, Any],
    nuevo: dict[str, Any],
    ignorar: set[str] | None = None,
    tenant_id: Any = None,
) -> list[CambioCampo]:
    """Anota campo a campo lo que cambió (CRM-00.05.04.02).

    Solo escribe los campos que de verdad cambiaron: registrar los cincuenta
    campos de una cuenta cada vez que alguien corrige un teléfono haría el
    historial ilegible, que es la forma habitual de que estos historiales
    acaben sin usarse.
    """
    from crmcore.tenancy.context import contexto_actual

    ctx = contexto_actual()
    # El tenant se puede pasar a mano. Antes salía solo del contexto ambiental,
    # y eso hacía que cualquier camino sin contexto —un proceso por lotes, un
    # ejecutor de trabajos, un consumidor de eventos— escribiera un historial
    # con `tenant_id` nulo y reventara contra la restricción al hacer commit:
    # lejos de la llamada y con un mensaje del motor, no del dominio.
    tenant = tenant_id or ctx.tenant_id
    if tenant is None:
        from crmcore.errors import ErrorInterno

        raise ErrorInterno(
            "No se puede anotar el historial de campos sin saber de qué tenant "
            "es: ni se ha pasado y ni hay contexto.",
            error_code="auditoria.sin_tenant",
            detalle={"objeto": objeto},
        )

    # `updated_at` y `version` cambian en toda escritura y no son información:
    # su sitio es la traza de auditoría, no el historial de campo.
    ignorar = (ignorar or set()) | {"updated_at", "version", "updated_by", "updated_origen"}
    filas: list[CambioCampo] = []
    for campo, valor_nuevo in nuevo.items():
        if campo in ignorar:
            continue
        valor_anterior = anterior.get(campo)
        if valor_anterior == valor_nuevo:
            continue
        fila = CambioCampo(
            tenant_id=tenant,
            objeto=objeto,
            objeto_id=str(objeto_id),
            campo=campo,
            valor_anterior=None if valor_anterior is None else str(valor_anterior),
            valor_nuevo=None if valor_nuevo is None else str(valor_nuevo),
            actor_id=ctx.user_id,
            origen=ctx.origen,
        )
        db.add(fila)
        filas.append(fila)
    return filas


def _contenido_de(apunte: ApunteAuditoria) -> dict[str, Any]:
    """Reconstruye, desde la fila guardada, lo que se firmó al escribirla.

    Tiene que dar **exactamente** el mismo diccionario que construyó
    `registrar`: cualquier campo de más, de menos o con otro nombre haría que la
    verificación fallara con la cadena intacta, que es la peor forma de fallar
    —la que hace que nadie se crea el verificador—.
    """
    return {
        "secuencia": apunte.secuencia,
        "tenant_id": str(apunte.tenant_id),
        "accion": apunte.accion,
        "objeto": apunte.objeto,
        "objeto_id": apunte.objeto_id,
        "actor_id": str(apunte.actor_id) if apunte.actor_id else None,
        "actor_real_id": str(apunte.actor_real_id) if apunte.actor_real_id else None,
        "origen": apunte.origen,
        "datos": apunte.datos or {},
        "motivo": apunte.motivo,
        "momento": _en_utc(apunte.created_at),
    }


def verificar(db: Session, tenant_id: UUID, *, desde: int = 1) -> dict[str, Any]:
    """Recorre la cadena de un tenant y dice si está intacta.

    Devuelve un informe en vez de un booleano: en una auditoría real la pregunta
    no es «¿está bien?» sino «¿dónde se rompió y cuántos apuntes hay?».
    """
    apuntes = (
        db.execute(
            select(ApunteAuditoria)
            .where(
                ApunteAuditoria.tenant_id == tenant_id,
                ApunteAuditoria.secuencia >= desde,
            )
            .order_by(ApunteAuditoria.secuencia)
        )
        .scalars()
        .all()
    )
    if not apuntes:
        return {"intacta": True, "apuntes": 0, "rota_en": None, "sin_cadena": 0}

    esperado_previo = HASH_GENESIS if desde == 1 else apuntes[0].hash_previo
    esperada_secuencia = apuntes[0].secuencia
    sin_cadena = 0

    for apunte in apuntes:
        if apunte.secuencia != esperada_secuencia:
            return {
                "intacta": False,
                "apuntes": len(apuntes),
                "sin_cadena": sin_cadena,
                "rota_en": apunte.secuencia,
                "motivo": (f"falta el apunte {esperada_secuencia}: se ha borrado una fila"),
            }
        if apunte.hash_previo != esperado_previo:
            return {
                "intacta": False,
                "apuntes": len(apuntes),
                "sin_cadena": sin_cadena,
                "rota_en": apunte.secuencia,
                "motivo": "el enlace con el apunte anterior no coincide",
            }
        # Se **recalcula** el hash desde el contenido guardado. Comprobar solo
        # los enlaces caza un borrado o una inserción, pero no una modificación
        # en su sitio: alguien que cambie el motivo o el actor de un apunte
        # dejaría la cadena aparentemente intacta. En un despliegue real el
        # trigger `auditoria_solo_insercion` impide el UPDATE, pero la cadena
        # existe justo para lo que el trigger no alcanza —un acceso directo a la
        # base, una copia de seguridad manipulada—, y sin esta comprobación no
        # servía para eso.
        # Un tramo escrito con la cadena apagada no es una cadena rota: no hay
        # hash que recalcular porque nunca se calculó. Se cuenta y se sigue —el
        # informe lo dice— porque decir «manipulado» de lo que sólo está sin
        # encadenar es una acusación falsa, y quien audita no tiene forma de
        # distinguirlas desde fuera.
        #
        # Lo que NO se afloja es la secuencia: un borrado dentro del tramo sin
        # cadena lo sigue cazando la comprobación de arriba.
        if apunte.hash == SIN_CADENA:
            sin_cadena += 1
            esperado_previo = apunte.hash
            esperada_secuencia += 1
            continue
        if _hash_apunte(_contenido_de(apunte), apunte.hash_previo) != apunte.hash:
            return {
                "intacta": False,
                "apuntes": len(apuntes),
                "sin_cadena": sin_cadena,
                "rota_en": apunte.secuencia,
                "motivo": "el contenido del apunte no corresponde a su hash: se ha alterado",
            }
        esperado_previo = apunte.hash
        esperada_secuencia += 1

    return {
        "intacta": True,
        "apuntes": len(apuntes),
        "rota_en": None,
        # «Intacta» con tramos sin encadenar NO es la misma afirmación que
        # «intacta» entera, y quien audita necesita verlo sin preguntar: de esos
        # apuntes se demuestra que no falta ninguno, pero no que no se hayan
        # modificado en su sitio.
        "sin_cadena": sin_cadena,
        "ultimo_hash": apuntes[-1].hash,
        "ultima_secuencia": apuntes[-1].secuencia,
    }


def ultimo_hash(db: Session, tenant_id: UUID) -> str:
    """Último hash de la cadena. Es lo que se ancla fuera periódicamente."""
    fila = db.execute(
        select(ApunteAuditoria.hash, func.max(ApunteAuditoria.secuencia))
        .where(ApunteAuditoria.tenant_id == tenant_id)
        .group_by(ApunteAuditoria.hash)
        .order_by(func.max(ApunteAuditoria.secuencia).desc())
        .limit(1)
    ).first()
    return fila[0] if fila else HASH_GENESIS
