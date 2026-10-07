"""El primer administrador de una empresa dada de alta sola (CRM-00.01.03.01).

`tenancy` confirma el alta y emite el hecho; aquí se crea el administrador. Por
**evento y no por llamada**: los usuarios son de este servicio y los servicios
no se llaman entre sí. Hacerlo por llamada ataría el alta a que identity esté en
pie en ese segundo exacto, que es el peor momento para que falle un alta — la
persona está mirando la pantalla y no hay a quién reintentar.

**No se inventa una contraseña.** Se crea el usuario sin ninguna y se emite un
enlace de los de siempre para que la ponga él. Mandar una contraseña generada por
correo es ponerla en un buzón y en los registros del servidor de correo, y
además nadie la cambia después.

**Es idempotente.** La entrega del bus es at-least-once, así que este hecho llega
dos veces de serie: si el usuario ya está, no se duplica ni se le reabre el
enlace. La deduplicación del inbox ya lo cubre, y aun así se comprueba aquí —
una garantía que depende de que otra capa esté bien configurada no es una
garantía.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.logging import get_logger

logger = get_logger(__name__)


async def consumir_alta_confirmada(mensaje: Any) -> None:
    """Crea el administrador de un tenant recién dado de alta."""
    from crmcore.db.uow import unidad_de_trabajo
    from crmcore.tenancy.context import con_contexto
    from sqlalchemy import select

    from services.identity import restablecer
    from services.identity import servicio as svc
    from services.identity.modelos import Usuario

    datos = getattr(mensaje, "data", None) or {}
    tenant_id = datos.get("tenant_id")
    email = str(datos.get("email") or "").strip().lower()
    nombre = str(datos.get("nombre") or "").strip()
    if not tenant_id or not email:
        # Se dice y no se lanza: un hecho mal formado que reviente el consumidor
        # lo deja reintentándose para siempre y tapa los que vienen detrás.
        logger.warning("alta.hecho_incompleto", datos=sorted(datos))
        return

    tenant = UUID(str(tenant_id))
    with con_contexto(tenant_id=tenant, origen="alta"), unidad_de_trabajo(tenant) as uow:
        ya = uow.db.execute(select(Usuario).where(Usuario.email == email)).scalar_one_or_none()
        if ya is not None:
            logger.info("alta.administrador_ya_estaba", tenant_id=str(tenant))
            return

        svc.crear_usuario(
            uow,
            email=email,
            nombre=nombre or email,
            tenant_id=tenant,
            roles=["admin"],
            via="alta_autoservicio",
        )
        # El enlace para que ponga su contraseña. Se devuelve en el log de
        # dominio igual que el resto de enlaces del producto: lo manda quien
        # integre el correo.
        token = restablecer.solicitar(uow, email=email)

    logger.info(
        "alta.administrador_creado",
        tenant_id=str(tenant),
        # El token NO va al log: es una credencial. Se deja constancia de que se
        # emitió, que es lo que hace falta para seguir el alta.
        enlace_emitido=bool(token),
    )
