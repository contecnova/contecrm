"""Qué se le puede pedir a `service` desde fuera (CRM-00.03.03.03).

Hoy lo usa la telemetría de dispositivos (CRM-04.04.02.05): `integration` no
escribe en este esquema —los permisos de base de datos se lo impiden— así que
manda un comando y **aquí se decide**, con las mismas reglas que un caso abierto
a mano: taxonomía, SLA, código legible y auditoría.

La lista blanca de campos la declara este servicio, no quien manda el comando.
Sin ella, un integrador podría fijar el estado de un caso o su dueño saltándose la
máquina de estados, que es una escalada de privilegios disfrazada de
configuración.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.bus.comandos import Manejador, registrar_manejador
from crmcore.logging import get_logger
from sqlalchemy.orm import Session

logger = get_logger(__name__)

# Lo que un comando puede traer al abrir un caso. **No incluye `estado`, ni
# `owner_id`, ni `prioridad`**: el estado lo gobierna la máquina, el dueño lo
# decide el enrutamiento y la prioridad sale de la taxonomía y del SLA. Un
# aparato no puede declararse prioritario a sí mismo.
CAMPOS_CASO = frozenset(
    {
        "asunto",
        "descripcion",
        "severidad",
        "origen",
        "categoria_id",
        "cuenta_id",
        "contacto_id",
        "activo_id",
        "campos",
    }
)


def _crear_caso(
    db: Session,
    *,
    registro_id: Any = None,
    datos: dict[str, Any],
    origen: str,
    origen_id: str | None = None,
) -> None:
    """Abre un caso pedido por otro servicio.

    Si falta el asunto no se inventa uno: un caso titulado «Sin asunto» entra en
    la cola igual que los demás y nadie sabe qué hacer con él. Se descarta y se
    deja dicho por qué, que es lo que permite arreglar al que lo manda.
    """
    from crmcore.db.uow import UnidadDeTrabajo

    from services.service.servicio import abrir_caso

    asunto = str(datos.get("asunto") or "").strip()
    if not asunto:
        logger.warning("service.comando_sin_asunto", origen=origen, origen_id=origen_id)
        return

    campos = {k: v for k, v in datos.items() if k in CAMPOS_CASO and k != "asunto"}
    for clave in ("categoria_id", "cuenta_id", "contacto_id", "activo_id"):
        if campos.get(clave):
            try:
                campos[clave] = UUID(str(campos[clave]))
            except (TypeError, ValueError):
                # Un identificador ilegible no tumba el caso: se abre sin él y se
                # deja constancia. Perder el aviso de una máquina por un UUID mal
                # formado es peor que abrirlo sin colgarlo de nada.
                logger.warning("service.comando_id_ilegible", campo=clave, origen=origen)
                campos.pop(clave)
    # `activo_id` no es una columna del caso: va a los campos extendidos, que es
    # donde el metamodelo lo valida. Meterlo como columna obligaría a `service` a
    # conocer el modelo de quien lo manda.
    activo_id = campos.pop("activo_id", None)
    extra = dict(campos.pop("campos", None) or {})
    if activo_id:
        extra["activo_id"] = str(activo_id)

    # El tenant sale del contexto de la petición, que lo fija el consumidor al
    # recibir el mensaje. Deducirlo de los datos del comando permitiría que quien
    # lo manda escribiera en otro tenant.
    from crmcore.tenancy.context import contexto_actual

    tenant_id = contexto_actual().tenant_id
    if tenant_id is None:
        logger.warning("service.comando_sin_contexto", origen=origen)
        return
    uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
    caso = abrir_caso(uow, asunto=asunto, **campos, campos=extra)
    logger.info(
        "service.caso_abierto_por_comando",
        caso=str(caso.id),
        origen=origen,
        origen_id=origen_id,
    )


registrar_manejador(
    Manejador(
        objeto="caso",
        accion="crear",
        ejecutar=_crear_caso,
        campos_permitidos=CAMPOS_CASO,
    )
)


# Lo que un comando puede traer al adjuntar un resumen de conversación
# (CRM-04.02.02.06). **No incluye `estado` ni `resolucion`**: un resumen escrito
# por un modelo no cierra un caso. Se queda como anotación, visible y atribuida a
# la IA, y quien lo lea decide qué hacer con él.
CAMPOS_RESUMEN = frozenset({"resumen_id", "texto", "pendientes", "momento", "parcial"})


def _adjuntar_resumen(
    db: Session,
    *,
    registro_id: Any = None,
    datos: dict[str, Any],
    origen: str,
    origen_id: str | None = None,
) -> None:
    """Cuelga del caso el resumen que ha propuesto el servicio de inteligencia.

    Se guarda como un evento del caso, **no como su resolución**: el texto lo ha
    escrito un modelo y el caso es de quien lo atiende. Que quede en la historia
    con su origen es lo que permite, meses después, distinguir «esto lo resumió
    la IA» de «esto lo escribió el agente», que es exactamente la pregunta que se
    hace cuando el resumen resulta estar mal.

    Un resumen parcial se marca como tal también aquí: el aviso no puede quedarse
    en el servicio que lo generó, porque quien lo lee es el agente que recoge el
    caso.
    """
    from services.service.modelos import Caso

    if registro_id is None:
        logger.warning("service.resumen_sin_caso", origen=origen, origen_id=origen_id)
        return
    caso = db.get(Caso, registro_id)
    if caso is None:
        # No se crea un caso para colgar el resumen: inventar un caso a partir de
        # una conversación que ya no existe deja basura que nadie reclama.
        logger.warning("service.resumen_caso_inexistente", caso=str(registro_id), origen=origen)
        return

    texto = str(datos.get("texto") or "").strip()
    if not texto:
        logger.warning("service.resumen_vacio", caso=str(registro_id), origen=origen)
        return

    from services.service.servicio import _anotar

    _anotar(
        db,
        caso,
        "resumen_ia",
        texto=texto,
        pendientes=list(datos.get("pendientes") or []),
        momento=str(datos.get("momento") or ""),
        parcial=bool(datos.get("parcial")),
        resumen_id=str(datos.get("resumen_id") or ""),
        origen=origen,
    )
    logger.info(
        "service.resumen_adjuntado",
        caso=str(caso.id),
        origen=origen,
        parcial=bool(datos.get("parcial")),
    )


registrar_manejador(
    Manejador(
        objeto="caso",
        accion="adjuntar_resumen",
        ejecutar=_adjuntar_resumen,
        campos_permitidos=CAMPOS_RESUMEN,
    )
)
