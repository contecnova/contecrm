"""Ajustes propios del servicio de ventas."""

from __future__ import annotations

from functools import lru_cache

from crmcore.config import Settings
from crmcore.runtime.keys import ClaveAjuste, registrar_claves
from crmcore.runtime.settings import registrar_ajustes_servicio
from pydantic import Field


class AjustesSales(Settings):
    """Configuración del servicio `sales`."""

    # ── SLA de primera respuesta (CRM-01.01.03.07) ────────────────────────
    # Horas para responder a un lead nuevo. Cuatro horas laborables es el valor
    # que suele usarse: por encima de eso la probabilidad de contactar cae en
    # picado, y por debajo hace falta un equipo dedicado.
    lead_sla_primera_respuesta_horas: int = Field(4, ge=1, le=720)
    # Reasignar el lead si nadie responde dentro del SLA. Apagado por defecto:
    # reasignar automáticamente puede quitarle un lead a quien ya lo estaba
    # trabajando por teléfono sin registrarlo.
    lead_reasignar_al_incumplir_sla: bool = False
    # Enrutar el lead por reglas al darlo de alta (CRM-01.01.03.04). Encendido:
    # un lead sin dueño no sale en la lista de nadie y se pierde. Se puede
    # apagar durante una importación masiva, donde el reparto lo decide la
    # propia carga y enrutar 50.000 filas una a una sería absurdo.
    lead_enrutar_al_crear: bool = True

    # ── Trazabilidad de origen (CRM-01.01.03.06) ──────────────────────────
    # Cuánto se remonta la búsqueda de toques anónimos al identificar a un
    # visitante. 90 días vale para una venta de ciclo medio; en obra o industria
    # se queda corto, y por eso es un ajuste y no una constante.
    origen_ventana_dias: int = Field(90, ge=1, le=1825)

    # ── Ciclo del lead ────────────────────────────────────────────────────
    # Días tras los que un lead descartado vuelve a la cola de reciclaje.
    lead_dias_reciclaje: int = Field(180, ge=0, le=3650)

    # ── Oportunidades ─────────────────────────────────────────────────────
    # Exigir los criterios de salida de la etapa para poder avanzar. Es lo que
    # hace que la previsión signifique algo; se puede apagar durante la carga
    # inicial de datos históricos, que nunca los cumplen.
    exigir_criterios_salida: bool = True
    # Bloquear la edición de una oportunidad cerrada (CRM-03.01.01.14).
    bloquear_al_cerrar: bool = True
    # Exigir motivo de pérdida normalizado al cerrar como perdida. Sin esto, el
    # análisis de pérdidas es una nube de texto libre imposible de agrupar.
    exigir_motivo_perdida: bool = True
    # Días sin actividad tras los que una oportunidad se marca como estancada,
    # cuando su etapa no declara uno propio.
    dias_estancamiento_defecto: int = Field(30, ge=1, le=365)
    # Prefijo y formato del código legible de oportunidad.
    codigo_prefijo: str = "OPP"

    # ── Canal indirecto (CRM-03.04.01) ────────────────────────────────────
    # Días que protege un registro de oportunidad aprobado cuando el nivel del
    # partner no declara los suyos. Noventa días es lo habitual en software y se
    # queda muy corto en proyecto industrial: por eso es ajuste, no constante.
    partner_proteccion_dias: int = Field(90, ge=1, le=1095)
    # Con cuánta antelación se avisa de una certificación que caduca. Certificar
    # a alguien lleva semanas; avisar el mismo día no sirve de nada.
    partner_preaviso_certificacion_dias: int = Field(60, ge=1, le=365)
    # Validez del enlace de entrada al portal de partner.
    partner_enlace_validez_minutos: int = Field(30, ge=5, le=1440)

    # ── Comisiones (CRM-03.02.03) ─────────────────────────────────────────
    # Plazo para reclamar una liquidación. Pasado, la disputa se registra igual
    # pero marcada fuera de plazo: ni se pierde ni se acepta en silencio.
    comision_dias_disputa: int = Field(30, ge=1, le=365)

    # ── Cotización (CRM-03.03.02.04) ──────────────────────────────────────
    # Descuento que un comercial puede dar sin que nadie lo apruebe. Es un
    # ajuste y no una constante porque cambia con cada campaña, y un despliegue
    # por cada cambio hace que se acabe aprobando a mano «esta vez».
    descuento_libre_pct: int = Field(10, ge=0, le=100)
    # Margen por debajo del cual el presupuesto necesita aprobación aunque el
    # descuento sea pequeño: un 5 % sobre un producto de 8 puntos de margen deja
    # la venta en pérdidas, y mirar solo el porcentaje no lo ve.
    margen_minimo_pct: int = Field(20, ge=0, le=100)
    # Días de validez por defecto de un presupuesto. Sin caducidad, el precio se
    # vuelve eterno y el cliente lo saca dos años después.
    presupuesto_dias_validez: int = Field(30, ge=1, le=365)
    # Horas que se espera la confirmación del ERP antes de dar el pedido por
    # perdido en la conciliación.
    erp_espera_confirmacion_horas: int = Field(24, ge=1, le=720)


registrar_claves(
    [
        ClaveAjuste(
            clave="descuento_libre_pct",
            tipo="int",
            descripcion="Descuento que se puede dar sin aprobación",
            minimo=0,
            maximo=100,
            campo_settings="descuento_libre_pct",
        ),
        ClaveAjuste(
            clave="margen_minimo_pct",
            tipo="int",
            descripcion="Margen por debajo del cual el presupuesto necesita aprobación",
            minimo=0,
            maximo=100,
            campo_settings="margen_minimo_pct",
        ),
        ClaveAjuste(
            clave="presupuesto_dias_validez",
            tipo="int",
            descripcion="Días de validez por defecto de un presupuesto",
            minimo=1,
            maximo=365,
            campo_settings="presupuesto_dias_validez",
        ),
        ClaveAjuste(
            clave="erp_espera_confirmacion_horas",
            tipo="int",
            descripcion="Horas que se espera la confirmación del ERP antes de avisar",
            minimo=1,
            maximo=720,
            campo_settings="erp_espera_confirmacion_horas",
        ),
        ClaveAjuste(
            clave="lead_sla_primera_respuesta_horas",
            tipo="int",
            descripcion="Horas para dar la primera respuesta a un lead",
            minimo=1,
            maximo=720,
            campo_settings="lead_sla_primera_respuesta_horas",
        ),
        ClaveAjuste(
            clave="lead_reasignar_al_incumplir_sla",
            tipo="bool",
            descripcion="Reasignar automáticamente el lead si se incumple el SLA",
            campo_settings="lead_reasignar_al_incumplir_sla",
        ),
        ClaveAjuste(
            clave="lead_enrutar_al_crear",
            tipo="bool",
            descripcion="Aplicar las reglas de enrutamiento al dar de alta un lead",
            campo_settings="lead_enrutar_al_crear",
        ),
        ClaveAjuste(
            clave="origen_ventana_dias",
            tipo="int",
            descripcion="Días hacia atrás que se recuperan los toques de un visitante anónimo",
            minimo=1,
            maximo=1825,
            campo_settings="origen_ventana_dias",
        ),
        ClaveAjuste(
            clave="lead_dias_reciclaje",
            tipo="int",
            descripcion="Días tras los que un lead descartado vuelve a la cola",
            minimo=0,
            maximo=3650,
            campo_settings="lead_dias_reciclaje",
        ),
        ClaveAjuste(
            clave="exigir_criterios_salida",
            tipo="bool",
            descripcion="Exigir los criterios de la etapa para avanzar una oportunidad",
            campo_settings="exigir_criterios_salida",
            sensible=True,
        ),
        ClaveAjuste(
            clave="bloquear_al_cerrar",
            tipo="bool",
            descripcion="Bloquear la edición de una oportunidad cerrada",
            campo_settings="bloquear_al_cerrar",
            sensible=True,
        ),
        ClaveAjuste(
            clave="exigir_motivo_perdida",
            tipo="bool",
            descripcion="Exigir motivo normalizado al marcar una oportunidad como perdida",
            campo_settings="exigir_motivo_perdida",
        ),
        ClaveAjuste(
            clave="partner_proteccion_dias",
            tipo="int",
            descripcion="Días que protege un registro de oportunidad aprobado, si el nivel no dice otra cosa",
            minimo=1,
            maximo=1095,
            campo_settings="partner_proteccion_dias",
            sensible=True,
        ),
        ClaveAjuste(
            clave="partner_preaviso_certificacion_dias",
            tipo="int",
            descripcion="Antelación con la que se avisa de una certificación de partner que caduca",
            minimo=1,
            maximo=365,
            campo_settings="partner_preaviso_certificacion_dias",
        ),
        ClaveAjuste(
            clave="partner_enlace_validez_minutos",
            tipo="int",
            descripcion="Minutos que vale el enlace de entrada al portal de partner",
            minimo=5,
            maximo=1440,
            campo_settings="partner_enlace_validez_minutos",
            sensible=True,
        ),
        ClaveAjuste(
            clave="comision_dias_disputa",
            tipo="int",
            descripcion="Plazo para reclamar una liquidación de comisión",
            minimo=1,
            maximo=365,
            campo_settings="comision_dias_disputa",
            sensible=True,
        ),
        ClaveAjuste(
            clave="dias_estancamiento_defecto",
            tipo="int",
            descripcion="Días sin movimiento tras los que una oportunidad se marca estancada",
            minimo=1,
            maximo=365,
            campo_settings="dias_estancamiento_defecto",
        ),
    ]
)


@lru_cache(maxsize=1)
def ajustes() -> AjustesSales:
    return AjustesSales()


registrar_ajustes_servicio(ajustes)
