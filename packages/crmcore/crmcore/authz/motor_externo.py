"""Evaluar las políticas fuera de contecrm (CRM-00.05.02.06).

El motor de `abac.py` decide dentro del proceso. Eso está bien mientras el
único que pregunta es el CRM, y deja de estarlo en cuanto hay más de un
consumidor: un front a medida que quiere saber si pintar un botón, un servicio
del cliente que aplica las mismas reglas, un motor de decisión corporativo que
ya existe. Sin esto, cada uno reimplementa las reglas y la cuarta
implementación ya no dice lo mismo que las otras tres.

Dos piezas, y ninguna ata la instalación a un producto concreto:

  * **Publicar** la política en un formato neutro, para que quien quiera la
    cargue en su motor —OPA, Cedar, el suyo— sin leer nuestra base.
  * **Delegar** la decisión en un motor externo por HTTP, si se configura. Es
    un transporte declarativo, como el de notificaciones o el de verificación:
    la dirección, el tiempo de espera y el mapeo salen de la configuración, no
    hay un cliente por producto y no lo va a haber.

**Delegar no puede convertirse en un agujero.** Si el motor externo no
contesta, no se abre el acceso: se decide con el motor de dentro, que es el que
tiene la misma política replicada. Y si contesta que no, se deniega aunque el
de dentro dijera que sí — el externo puede restringir más, nunca menos, que es
la misma regla que gobierna el ABAC entero.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.authz.abac import Decision, Politica
from crmcore.logging import get_logger

logger = get_logger(__name__)


def publicar(politicas: list[Politica], *, tenant: str = "") -> dict[str, Any]:
    """La política en un formato neutro, listo para cargar en otro motor.

    No es OPA ni Cedar: es la política tal cual, con su gramática cerrada
    documentada, porque traducirla a un dialecto concreto aquí ataría el
    producto a ese dialecto. Quien use Rego o Cedar escribe la traducción una
    vez —son treinta líneas— y esta salida es su entrada estable.
    """
    return {
        "formato": "contecrm.abac/1",
        "tenant": tenant,
        # La semántica va DENTRO del documento, no en la documentación: quien
        # escriba el traductor la necesita delante, y una nota en un manual
        # aparte es una nota que no se lee.
        "semantica": {
            "combinacion_entre_politicas": "todas",
            "efecto": "restringir",
            "sin_politicas": "permitir",
            "operador_desconocido": "denegar",
            "prefijo_referencia_atributo": "@",
        },
        "politicas": [
            {
                "nombre": p.nombre,
                "objeto": p.objeto,
                "acciones": sorted(p.acciones),
                "combinacion": p.combinacion,
                "prioridad": p.prioridad,
                "descripcion": p.descripcion,
                "condiciones": [
                    {"atributo": c.atributo, "operador": c.operador, "valor": c.valor}
                    for c in p.condiciones
                ],
            }
            for p in sorted(politicas, key=lambda p: p.prioridad)
        ],
    }


def configurado() -> bool:
    from crmcore.config import get_settings

    s = get_settings()
    return bool(s.abac_motor_externo_url and s.abac_motor_externo_enabled)


def consultar(
    *, objeto: str, accion: str, ambito: dict[str, Any], tenant_id: UUID | None = None
) -> Decision | None:
    """Pregunta al motor externo. `None` si no hay o si no contesta.

    Devolver `None` y no una decisión permisiva es lo que impide que apagar el
    motor externo —o que se caiga— abra el acceso: quien llama sigue con el
    motor de dentro.
    """
    if not configurado():
        return None

    from crmcore.config import get_settings
    from crmcore.red import cliente_seguro

    s = get_settings()
    try:
        with cliente_seguro(timeout=s.abac_motor_externo_timeout_s) as cliente:
            respuesta = cliente.post(
                s.abac_motor_externo_url,
                json={
                    "tenant": str(tenant_id) if tenant_id else "",
                    "objeto": objeto,
                    "accion": accion,
                    "ambito": ambito,
                },
            )
        if respuesta.status_code != 200:
            raise RuntimeError(f"respondió {respuesta.status_code}")
        cuerpo = respuesta.json()
    except Exception as exc:  # noqa: BLE001 — sin motor externo se decide dentro
        logger.error("abac.motor_externo_no_responde", error=str(exc)[:300])
        return None

    if "permitido" not in cuerpo:
        # Una respuesta que no dice lo único que se le preguntó no se
        # interpreta: se ignora. Interpretarla como permitir sería convertir un
        # motor mal configurado en una autorización.
        logger.error("abac.motor_externo_sin_veredicto", cuerpo=str(cuerpo)[:200])
        return None

    return Decision(
        permitido=bool(cuerpo["permitido"]),
        razones=[str(r) for r in (cuerpo.get("razones") or [])] or ["motor externo"],
        politica_decisiva=str(cuerpo.get("politica") or "motor externo"),
    )


def combinar(interna: Decision, externa: Decision | None) -> Decision:
    """La decisión final: el externo puede restringir más, nunca menos.

    Si el externo permitiera lo que el interno deniega, bastaría con apuntar la
    configuración a un servicio que diga «sí» a todo para saltarse las políticas
    del tenant. Con esta regla, el peor caso de un motor externo hostil es que
    no cambie nada.
    """
    if externa is None:
        return interna
    if not interna.permitido:
        return interna
    if not externa.permitido:
        return Decision(
            permitido=False,
            razones=[*interna.razones, *externa.razones],
            politica_decisiva=externa.politica_decisiva,
        )
    return Decision(
        permitido=True,
        razones=[*interna.razones, *externa.razones],
        politica_decisiva=interna.politica_decisiva or externa.politica_decisiva,
    )
