"""La biblioteca de plantillas de automatización, por industria (CRM-00.03.03.09).

Antes había que **teclear la plantilla en JSON** y `instalar` contestaba
«instaladas» sin crear nada. Ahora la biblioteca es esta lista, se elige de un
desplegable y crea la automatización de verdad, **apagada**.

Cada plantilla es una regla completa —disparador, condiciones y acciones— que
**valida con el motor** (`validacion.problemas_de(..., estricta=True)`), y la
prueba lo comprueba para todas: una plantilla que se instala bien y falla la
primera vez que se dispara es peor que no tenerla.

Las reglas se enganchan a lo que **de verdad publica** cada servicio: los
eventos del catálogo con los campos que llevan, y las acciones que tienen quien
las atienda (`asignar` un lead, crear una tarea). Lo que una plantilla da por
supuesto y no se puede comprobar al instalarla va en `requiere`, y se devuelve
al instalar: lo que falta no falla al instalar, falla semanas después.

**Lo que cambia de una empresa a otra no va escrito**: a quién se avisa o a
quién se asigna lo elige quien instala (`responsable_id`), y los umbrales —el
importe, los días— son datos de la regla, que se cambian desde su ficha como
cualquier otro.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

# Marca que se sustituye por la persona que elige quien instala.
RESPONSABLE = "{responsable}"


@dataclass(frozen=True, slots=True)
class Plantilla:
    clave: str
    nombre: str
    descripcion: str
    industrias: tuple[str, ...]
    regla: dict[str, Any]
    # Si hace falta elegir a alguien para instalarla (a quién se asigna).
    necesita_responsable: bool = False
    requiere: tuple[str, ...] = field(default_factory=tuple)


PLANTILLAS: tuple[Plantilla, ...] = (
    Plantilla(
        clave="oportunidad_en_la_recta_final",
        nombre="Oportunidad en la recta final",
        descripcion=(
            "Avisa cuando una oportunidad pasa a una etapa con un 70 % o más de "
            "probabilidad: es el momento en que un empujón del equipo decide el cierre."
        ),
        industrias=("venta consultiva B2B", "distribución"),
        regla={
            "disparador": "evento",
            "objetivo": "opportunity.stage.changed",
            "condiciones": [{"atributo": "probabilidad", "op": ">=", "valor": 70}],
            "acciones": [
                {
                    "tipo": "notificar",
                    "parametros": {
                        "titulo": "Una oportunidad entra en la recta final",
                        "cuerpo": "Ha pasado a una etapa con probabilidad alta de cierre.",
                        "objeto": "oportunidad",
                        "registro_id": "@oportunidad_id",
                        "usuarios": [RESPONSABLE],
                    },
                }
            ],
        },
    ),
    Plantilla(
        clave="lead_nuevo_al_responsable",
        nombre="Lead nuevo, asignado al responsable",
        descripcion=(
            "Asigna cada lead que entra a la persona elegida y se lo avisa: un lead "
            "sin dueño en la primera hora es un lead que se enfría."
        ),
        industrias=("venta consultiva B2B", "servicios profesionales"),
        necesita_responsable=True,
        regla={
            "disparador": "creacion",
            "objetivo": "lead",
            "acciones": [
                {
                    "tipo": "asignar",
                    "parametros": {
                        "objeto": "lead",
                        "registro_id": "@lead_id",
                        "usuario_id": RESPONSABLE,
                    },
                },
                {
                    "tipo": "notificar",
                    "parametros": {
                        "titulo": "Tienes un lead nuevo",
                        "cuerpo": "Te lo ha asignado una automatización al entrar.",
                        "objeto": "lead",
                        "registro_id": "@lead_id",
                        "usuarios": [RESPONSABLE],
                    },
                },
            ],
        },
        requiere=(
            "Si ya repartes los leads por territorio o por turno, esta regla los "
            "reasignaría: enciéndela sólo si no hay otro reparto.",
        ),
    ),
    Plantilla(
        clave="caso_critico_tarea_inmediata",
        nombre="Caso crítico: tarea inmediata",
        descripcion=(
            "Cuando entra un caso con prioridad crítica, crea una tarea en la cuenta "
            "y avisa: el caso crítico que espera a que alguien mire la cola es el "
            "que se convierte en baja."
        ),
        industrias=("soporte y servicio técnico", "mantenimiento"),
        regla={
            "disparador": "evento",
            "objetivo": "case.created",
            "condiciones": [{"atributo": "prioridad", "op": "=", "valor": "critica"}],
            "acciones": [
                {
                    "tipo": "crear_registro",
                    "parametros": {
                        "objeto": "actividad",
                        "tipo": "tarea",
                        "asunto": "Atender un caso crítico",
                        "cuerpo": "Abierto con prioridad crítica: hay que dar primera respuesta ya.",
                        "cuenta_id": "@cuenta_id",
                    },
                },
                {
                    "tipo": "notificar",
                    "parametros": {
                        "titulo": "Caso crítico abierto",
                        "cuerpo": "Hay una tarea creada en la cuenta para atenderlo.",
                        "objeto": "caso",
                        "registro_id": "@caso_id",
                        "usuarios": [RESPONSABLE],
                    },
                },
            ],
        },
    ),
    Plantilla(
        clave="contrato_a_punto_de_vencer",
        nombre="Contrato a punto de vencer",
        descripcion=(
            "Con el preaviso de renovación y treinta días o menos por delante, crea "
            "la tarea de preparar la renovación en la cuenta y avisa."
        ),
        industrias=("software y suscripciones", "servicios recurrentes"),
        regla={
            "disparador": "evento",
            "objetivo": "contract.renewal.due",
            "condiciones": [{"atributo": "dias_restantes", "op": "<=", "valor": 30}],
            "acciones": [
                {
                    "tipo": "crear_registro",
                    "parametros": {
                        "objeto": "actividad",
                        "tipo": "tarea",
                        "asunto": "Preparar la renovación del contrato",
                        "cuerpo": "El contrato vence en treinta días o menos.",
                        "cuenta_id": "@cuenta_id",
                    },
                },
                {
                    "tipo": "notificar",
                    "parametros": {
                        "titulo": "Un contrato vence pronto",
                        "cuerpo": "Hay una tarea para preparar la renovación.",
                        "objeto": "contrato",
                        "registro_id": "@contrato_id",
                        "usuarios": [RESPONSABLE],
                    },
                },
            ],
        },
    ),
    Plantilla(
        clave="bienvenida_a_un_cliente_nuevo",
        nombre="Bienvenida a un cliente nuevo",
        descripcion=(
            "Al dar de alta una cuenta, deja la tarea de darle la bienvenida. Corre "
            "diferida: si el alta se deshace, no queda una tarea huérfana."
        ),
        industrias=("todas",),
        regla={
            "disparador": "creacion",
            "objetivo": "cuenta",
            "momento": "diferida",
            "acciones": [
                {
                    "tipo": "crear_registro",
                    "parametros": {
                        "objeto": "actividad",
                        "tipo": "tarea",
                        "asunto": "Dar la bienvenida al cliente",
                        "cuerpo": "Llamada o correo de bienvenida y presentación del equipo.",
                        "cuenta_id": "@cuenta_id",
                    },
                }
            ],
        },
    ),
    Plantilla(
        clave="resumen_semanal_de_oportunidades",
        nombre="Recordatorio semanal de oportunidades",
        descripcion=(
            "Los lunes a las 8, en la hora de la empresa, recuerda revisar las "
            "oportunidades abiertas antes de la reunión de previsión."
        ),
        industrias=("venta consultiva B2B", "distribución"),
        necesita_responsable=True,
        regla={
            "disparador": "programada",
            "objetivo": "oportunidad",
            "programacion": "0 8 * * 1",
            "momento": "programada",
            "acciones": [
                {
                    "tipo": "notificar",
                    "parametros": {
                        "titulo": "Revisa tus oportunidades abiertas",
                        "cuerpo": "Es lunes: repasa etapas y fechas de cierre antes de la previsión.",
                        "usuarios": [RESPONSABLE],
                    },
                }
            ],
        },
    ),
)

POR_CLAVE: dict[str, Plantilla] = {p.clave: p for p in PLANTILLAS}
CLAVES: tuple[str, ...] = tuple(POR_CLAVE)


def _sustituir(valor: Any, responsable: str | None) -> Any:
    """Pone a la persona elegida donde la plantilla dice `{responsable}`.

    Sin persona elegida, las listas la pierden —se avisa a quien sigue el
    registro, que es lo que hace `notificar` sin menciones— y un valor suelto
    se queda vacío, que la validación estricta rechaza si era obligatorio.
    """
    if isinstance(valor, list):
        salida = [_sustituir(v, responsable) for v in valor]
        return [v for v in salida if v not in (None, "")]
    if isinstance(valor, dict):
        return {k: _sustituir(v, responsable) for k, v in valor.items()}
    if valor == RESPONSABLE:
        return responsable or ""
    return valor


def definicion(plantilla: Plantilla, *, responsable: str | None) -> dict[str, Any]:
    """La regla lista para guardar, con la persona puesta y APAGADA."""
    regla = _sustituir(copy.deepcopy(plantilla.regla), responsable)
    return {
        "nombre": plantilla.nombre,
        "descripcion": plantilla.descripcion,
        "disparador": regla["disparador"],
        "objetivo": regla["objetivo"],
        "campos_vigilados": list(regla.get("campos_vigilados") or []),
        "programacion": regla.get("programacion"),
        "condiciones": list(regla.get("condiciones") or []),
        "combinacion": regla.get("combinacion", "todas"),
        "acciones": list(regla["acciones"]),
        "prioridad": int(regla.get("prioridad", 100)),
        "momento": regla.get("momento", "inmediata"),
        # Apagada: una biblioteca que instala reglas encendidas empieza a mandar
        # avisos en cuanto alguien la mira por curiosidad.
        "activa": False,
    }
