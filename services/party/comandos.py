"""Qué puede pedirle una automatización a `party` (CRM-00.03.03.03).

Aquí se declara **qué campos deja tocar** cada acción, y esa lista blanca es la
parte importante: sin ella, una automatización podría fijar el `owner_id` de
cualquier cuenta o su estado de ciclo de vida saltándose las reglas que el
servicio aplica a todo el mundo. Sería una escalada de privilegios disfrazada de
configuración — quien puede editar reglas podría hacer por regla lo que no puede
hacer por API.

La lista la declara **el dueño del objeto**, no quien manda el comando. Es la
misma razón por la que un banco no deja que el ordenante decida qué campos de la
cuenta de destino se modifican.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.bus.comandos import Manejador, registrar_manejador
from crmcore.logging import get_logger
from sqlalchemy.orm import Session

logger = get_logger(__name__)

# Campos que una automatización puede escribir en una actividad. Es el objeto
# que más sentido tiene crear por regla —«cuando entre una cuenta grande, crea
# una tarea de bienvenida»— y el que menos daño hace si una regla se desboca:
# una actividad de más se borra, un cliente mal etiquetado se propaga.
CAMPOS_ACTIVIDAD = frozenset(
    {"tipo", "asunto", "cuerpo", "objeto", "objeto_id", "cuenta_id", "contacto_id", "vence_at"}
)
# En una cuenta, solo lo que es clasificación. Nada de identidad —nombre, NIF—
# ni de propiedad: eso lo cambia una persona, con su auditoría y su motivo.
CAMPOS_CUENTA = frozenset({"ciclo_vida", "clasificacion_abc", "tier", "sector_codigo", "campos"})
# Lo que se puede cambiar de un contacto por comando: lo que sale de una firma o
# de un correo y una persona ha aceptado (la extracción con IA, una regla).
# NO el nombre ni el correo principal: son su identidad, de ellos sale la clave
# canónica y la detección de duplicados, y cambiarlos tiene su propio camino.
CAMPOS_CONTACTO = frozenset(
    {
        "tratamiento",
        "cargo",
        "departamento",
        "telefono",
        "movil",
        "email_secundario",
        "idioma",
        "canal_preferido",
        "horario_preferido",
        "campos",
    }
)


def _crear_actividad(
    db: Session,
    *,
    registro_id: Any = None,
    datos: dict[str, Any],
    origen: str,
    origen_id: str | None = None,
) -> None:
    from crmcore.audit.chain import registrar
    from crmcore.tenancy.context import contexto_actual

    from services.party.modelos import Actividad

    tenant_id = contexto_actual().tenant_id
    if not datos.get("asunto"):
        # Sin asunto, la tarea sale en la lista de alguien como una fila en
        # blanco. Se rechaza aquí y no en el emisor porque el dueño del objeto
        # es quien sabe qué hace inservible a una actividad.
        logger.warning("party.comando_actividad_sin_asunto", origen=origen)
        return

    actividad = Actividad(tenant_id=tenant_id, **datos)
    db.add(actividad)
    db.flush()
    registrar(
        db,
        accion="actividad.creada_por_automatizacion",
        objeto="actividad",
        objeto_id=actividad.id,
        datos={"origen": origen, "origen_id": origen_id},
        tenant_id=tenant_id,
    )


def _actualizar_cuenta(
    db: Session,
    *,
    registro_id: Any = None,
    datos: dict[str, Any],
    origen: str,
    origen_id: str | None = None,
) -> None:
    from crmcore.audit.chain import registrar_cambios
    from crmcore.tenancy.context import contexto_actual

    from services.party.modelos import Cuenta

    if not registro_id or not datos:
        return
    cuenta = db.get(Cuenta, UUID(str(registro_id)))
    if cuenta is None or cuenta.deleted_at is not None:
        # Una regla que apunta a algo borrado no es un error: entre que se
        # encoló el comando y se ejecutó, alguien pudo borrarlo.
        logger.info("party.comando_sobre_registro_ausente", registro=str(registro_id))
        return

    anterior = cuenta.a_dict()
    from crmcore.bus.comandos import aplicar_cambios, origen_de_cambio

    aplicar_cambios(cuenta, datos)
    # El historial de campo distingue quién lo cambió: sin `origen`, un dato
    # modificado por una regla parece modificado por la última persona que tocó
    # la ficha, y la conversación con el cliente se atasca ahí.
    cuenta.updated_origen = origen_de_cambio(origen)
    registrar_cambios(
        db, objeto="cuenta", objeto_id=cuenta.id, anterior=anterior, nuevo=cuenta.a_dict()
    )
    db.flush()
    _ = contexto_actual()


def _actualizar_contacto(
    db: Session,
    *,
    registro_id: Any = None,
    datos: dict[str, Any],
    origen: str,
    origen_id: str | None = None,
) -> None:
    """Cambia un contacto por comando, con la MISMA normalización que la ficha.

    Un teléfono que entra por aquí sin normalizar no lo encuentra la búsqueda
    por teléfono ni la detección de duplicados, que comparan la forma normal.
    """
    from crmcore.audit.chain import registrar_cambios
    from crmcore.bus.comandos import aplicar_cambios, origen_de_cambio

    from services.party import normalizacion as norm
    from services.party.modelos import Contacto

    if not registro_id or not datos:
        return
    contacto = db.get(Contacto, UUID(str(registro_id)))
    if contacto is None or contacto.deleted_at is not None:
        logger.info("party.comando_sobre_registro_ausente", registro=str(registro_id))
        return
    cambios = dict(datos)
    for campo in ("telefono", "movil"):
        if campo in cambios:
            cambios[campo] = norm.normalizar_telefono(cambios[campo]) or None
    if "email_secundario" in cambios:
        cambios["email_secundario"] = norm.normalizar_email(cambios["email_secundario"]) or None
    anterior = contacto.a_dict()
    aplicar_cambios(contacto, cambios)
    contacto.updated_origen = origen_de_cambio(origen)
    registrar_cambios(
        db,
        objeto="contacto",
        objeto_id=contacto.id,
        anterior=anterior,
        nuevo=contacto.a_dict(),
        # El del contacto, no el del contexto: un comando puede ejecutarse sin
        # contexto de petición, y el historial no puede quedarse sin dueño.
        tenant_id=contacto.tenant_id,
    )
    db.flush()


registrar_manejador(
    Manejador(
        objeto="actividad",
        accion="crear",
        ejecutar=_crear_actividad,
        campos_permitidos=CAMPOS_ACTIVIDAD,
    )
)
registrar_manejador(
    Manejador(
        objeto="cuenta",
        accion="actualizar",
        ejecutar=_actualizar_cuenta,
        campos_permitidos=CAMPOS_CUENTA,
    )
)

registrar_manejador(
    Manejador(
        objeto="contacto",
        accion="actualizar",
        ejecutar=_actualizar_contacto,
        campos_permitidos=CAMPOS_CONTACTO,
    )
)
