"""Ajustes propios del servicio de cuentas y contactos.

Se declaran aquí y se registran en el catálogo en caliente al importar el
servicio: un umbral de deduplicación es exactamente el tipo de valor que cada
instalación quiere afinar en marcha, y que jamás debe estar escrito en el código.

Los valores por defecto no son arbitrarios: están elegidos para que la detección
**avise mucho y fusione poco**. Un falso positivo que se propone y se descarta
cuesta un clic; una fusión equivocada de dos clientes cuesta reconstruir a mano
contratos, actividades y facturación.
"""

from __future__ import annotations

from functools import lru_cache

from crmcore.config import Settings
from crmcore.runtime.keys import ClaveAjuste, registrar_claves
from crmcore.runtime.settings import registrar_ajustes_servicio
from pydantic import Field


class AjustesParty(Settings):
    """Configuración del servicio `party`."""

    # ── Deduplicación (CRM-01.01.04.01, .02) ──────────────────────────────
    # Similitud a partir de la cual dos fichas se PROPONEN como duplicadas.
    # 0,82 deja pasar erratas y cambios de orden sin inundar de falsos positivos.
    dedupe_umbral_sugerencia: float = Field(0.82, ge=0.0, le=1.0)
    # Similitud a partir de la cual se consideran **el mismo** registro y se
    # bloquea el alta. Muy alto a propósito: por debajo de esto decide una
    # persona, porque equivocarse aquí crea un duplicado o pierde un cliente.
    dedupe_umbral_bloqueo: float = Field(0.97, ge=0.0, le=1.0)
    # Cuántos candidatos se devuelven al dar de alta. Más de un puñado no se
    # miran: quien está creando una ficha no revisa veinte propuestas.
    dedupe_max_candidatos: int = Field(5, ge=1, le=50)
    # Bloquear el alta cuando el identificador fiscal ya existe. Es la única
    # señal que por sí sola prueba que son la misma entidad jurídica.
    dedupe_bloquear_por_nif: bool = True
    # Tratar como duplicado probable dos cuentas con el mismo dominio de correo
    # corporativo. Fuerte, pero no prueba: una multinacional tiene varias
    # sociedades con el mismo dominio.
    dedupe_usar_dominio: bool = True
    # Por debajo de esta probabilidad, la pareja no se propone en la cola de
    # revisión. Más bajo que el umbral de bloqueo al crear a propósito: bloquear
    # un alta y **proponer que alguien mire** no piden la misma certeza.
    duplicados_umbral_propuesta: float = Field(0.72, ge=0.0, le=1.0)

    # ── Calidad del dato (CRM-01.01.04.05) ────────────────────────────────
    # Puntuación por debajo de la cual la ficha entra en la cola de excepciones.
    calidad_umbral_revision: int = Field(50, ge=0, le=100)

    # ── Actividades ───────────────────────────────────────────────────────
    # Con cuánta antelación se manda el recordatorio de una tarea con
    # vencimiento, cuando no se indica uno explícito.
    actividad_recordatorio_horas: int = Field(24, ge=0, le=720)
    # Días sin actividad tras los que una cuenta se considera dormida. Alimenta
    # los avisos de inactividad, no cambia ningún estado por su cuenta.
    cuenta_dias_sin_actividad: int = Field(90, ge=1, le=3650)

    # ── Derechos del interesado (CRM-07.03.01.03) ─────────────────────────
    # Plazo legal de respuesta. Un mes es lo que fija el RGPD; se deja
    # configurable porque otras jurisdicciones fijan otro.
    derechos_plazo_dias: int = Field(30, ge=1, le=365)
    # Con cuánta antelación avisa el sistema de que una solicitud va a vencer.
    # Avisar el día del vencimiento es avisar tarde.
    derechos_aviso_dias_antes: int = Field(7, ge=0, le=90)

    # ── Resolución de identidad (CRM-01.01.02) ────────────────────────────
    # Puntuación a partir de la cual se PROPONE una fusión de identidades.
    # Estaba escrita en `identidad.py` como `UMBRAL_PROPUESTA = 80`, y el
    # código ya leía `identidad_umbral` de los ajustes — una clave que no
    # estaba declarada, así que leerla devolvía `None` y fijarla se rechazaba.
    identidad_umbral: int = Field(80, ge=0, le=1_000)
    # Y la que haría falta para fusionar SOLA. Pide más que lo manual porque
    # una persona que une dos fichas está mirando las dos y un proceso nocturno
    # no mira nada. Estaba a fuego (`UMBRAL_AUTOMATICO = 150`) y **sin ninguna
    # forma de cambiarla**, mientras su hermana sí se leía de los ajustes: se
    # podía afinar cuándo se propone y no cuándo se fusiona, que es la
    # destructiva.
    identidad_umbral_automatico: int = Field(150, ge=0, le=1_000)


registrar_claves(
    [
        ClaveAjuste(
            clave="identidad_umbral",
            tipo="int",
            descripcion="Puntuación a partir de la cual se propone una fusión de identidades",
            minimo=0,
            maximo=1_000,
            campo_settings="identidad_umbral",
        ),
        ClaveAjuste(
            clave="identidad_umbral_automatico",
            tipo="int",
            descripcion="Puntuación a partir de la cual dos fichas se fusionarían solas",
            minimo=0,
            maximo=1_000,
            campo_settings="identidad_umbral_automatico",
            sensible=True,
        ),
        ClaveAjuste(
            clave="dedupe_umbral_sugerencia",
            tipo="float",
            descripcion="Similitud a partir de la cual se propone un duplicado",
            minimo=0.0,
            maximo=1.0,
            campo_settings="dedupe_umbral_sugerencia",
        ),
        ClaveAjuste(
            clave="dedupe_umbral_bloqueo",
            tipo="float",
            descripcion="Similitud a partir de la cual se bloquea el alta por duplicado",
            minimo=0.0,
            maximo=1.0,
            campo_settings="dedupe_umbral_bloqueo",
            sensible=True,
        ),
        ClaveAjuste(
            clave="dedupe_bloquear_por_nif",
            tipo="bool",
            descripcion="Impedir dos cuentas con el mismo identificador fiscal",
            campo_settings="dedupe_bloquear_por_nif",
            sensible=True,
        ),
        ClaveAjuste(
            clave="duplicados_umbral_propuesta",
            tipo="float",
            descripcion="Probabilidad mínima para proponer una pareja en la cola de duplicados",
            minimo=0.0,
            maximo=1.0,
            campo_settings="duplicados_umbral_propuesta",
        ),
        ClaveAjuste(
            clave="calidad_umbral_revision",
            tipo="int",
            descripcion="Puntuación por debajo de la cual la ficha entra en revisión",
            minimo=0,
            maximo=100,
            campo_settings="calidad_umbral_revision",
        ),
        ClaveAjuste(
            clave="actividad_recordatorio_horas",
            tipo="int",
            descripcion="Antelación por defecto del recordatorio de una tarea",
            minimo=0,
            maximo=720,
            campo_settings="actividad_recordatorio_horas",
        ),
        ClaveAjuste(
            clave="cuenta_dias_sin_actividad",
            tipo="int",
            descripcion="Días sin actividad tras los que una cuenta se considera dormida",
            minimo=1,
            maximo=3650,
            campo_settings="cuenta_dias_sin_actividad",
        ),
        ClaveAjuste(
            clave="derechos_plazo_dias",
            tipo="int",
            descripcion="Plazo legal para responder una solicitud de derechos",
            minimo=1,
            maximo=365,
            campo_settings="derechos_plazo_dias",
            sensible=True,
        ),
        ClaveAjuste(
            clave="derechos_aviso_dias_antes",
            tipo="int",
            descripcion="Antelación del aviso de vencimiento de una solicitud",
            minimo=0,
            maximo=90,
            campo_settings="derechos_aviso_dias_antes",
        ),
    ]
)


@lru_cache(maxsize=1)
def ajustes() -> AjustesParty:
    return AjustesParty()


# Se le dice al núcleo de dónde salen estos ajustes, para que `rt.efectivo()`
# resuelva sus valores por defecto cuando nadie los ha fijado en la base.
registrar_ajustes_servicio(ajustes)
