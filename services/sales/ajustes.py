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

    # ── Deduplicar al capturar (CRM-01.01.03.03) ──────────────────────────
    # Parecido de empresa + nombre (0 a 1) a partir del cual un lead existente
    # se propone como candidato, y a partir del cual bloquea el alta. El correo
    # y el teléfono bloquean siempre: quien deja los suyos en un formulario
    # deja los suyos, no los de una centralita.
    lead_dedupe_umbral_sugerencia: float = Field(0.85, ge=0.0, le=1.0)
    lead_dedupe_umbral_bloqueo: float = Field(0.97, ge=0.0, le=1.0)
    # Preguntar también a los contactos del maestro (`party`, por HTTP). Si no
    # contesta, el alta sigue y se dice que no se miró.
    lead_dedupe_contactos: bool = True
    # Cuánto se espera esa respuesta. Corto a propósito: el formulario de la
    # web espera detrás, y uno que tarda se abandona.
    lead_dedupe_espera_s: float = Field(2.0, ge=0.2, le=30.0)
    lead_dedupe_max_candidatos: int = Field(5, ge=1, le=50)
    # Qué hace la captura automática con un duplicado concluyente, donde no hay
    # nadie a quien preguntar: `marcar` lo crea señalado, `fusionar` lo anota
    # en el que ya había, `nada` lo deja pasar.
    lead_dedupe_captura: str = Field("marcar", pattern="^(marcar|fusionar|nada)$")

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

    # ── Lecciones aprendidas ──────────────────────────────────────────────
    # Cuántas oportunidades ganadas del mismo embudo hacen falta para comparar
    # una perdida con ellas («aquí tardó el doble que las ganadas»). Con menos,
    # la comparación no dice nada y se calla en vez de inventar una referencia.
    lecciones_minimo_comparables: int = Field(5, ge=1, le=1_000)
    # Hasta cuántas actividades de la oportunidad se traen al expediente.
    lecciones_actividades_max: int = Field(200, ge=1, le=5_000)
    # Cuántas veces lo de las ganadas tiene que tardar una etapa para que sea
    # una señal: «149 días en Cualificación; las ganadas, 20».
    lecciones_factor_lento: float = Field(2.0, ge=1.1, le=20.0)
    # Puntos de descuento por encima de la mediana de las ganadas a partir de
    # los cuales el precio es una señal. Por debajo es ruido de negociación.
    lecciones_descuento_margen_pp: float = Field(5.0, ge=0.0, le=100.0)
    # Días sin contacto antes de cerrar a partir de los cuales el seguimiento
    # fue flojo.
    lecciones_dias_sin_contacto: int = Field(14, ge=1, le=365)
    # Cuántas lecciones se traen como consejo a una oportunidad abierta, por
    # cada camino (del mismo cliente, parecidas por significado).
    lecciones_consejos_max: int = Field(5, ge=1, le=50)
    # Parecido mínimo, de 0 a 1, para que una lección de otro cliente cuente
    # como «parecida». Por debajo, el índice siempre devuelve algo, y algo
    # que no se parece es peor que nada: se lee como un consejo.
    #
    # Medido el 08-11-2026 con `gemini-embedding-001` sobre 42 lecciones: las
    # del mismo tipo de venta dan entre 0,66 y 0,75, y las de otro tipo entre
    # 0,59 y 0,61. Con 0,75 no pasaba casi ninguna; 0,65 separa los dos
    # grupos. Depende del modelo de vectores: si se cambia, se vuelve a medir.
    lecciones_parecido_minimo: float = Field(0.65, ge=0.0, le=1.0)
    # Cada cuántos días sale el resumen de lecciones para quien dirige.
    lecciones_resumen_dias: int = Field(7, ge=1, le=90)
    # Cada cuántos segundos se mira si toca un resumen. Mirar a menudo y
    # generarlo sólo cuando toca es lo que lo hace inmune a los reinicios: un
    # reloj de siete días se reiniciaría con cada despliegue y no saldría nunca.
    lecciones_resumen_revisar_s: int = Field(3_600, ge=60, le=86_400)

    # ── Firma desde la oportunidad (CRM-03.03.02.07) ──────────────────────
    # A qué etapa lleva una firma completada, por embudo: {clave del embudo:
    # clave de la etapa}. Un embudo que no está aquí sólo marca la firma —un
    # sobre firmado dice que está firmado, no que el negocio esté ganado—, y
    # es lo que había: moverla es una decisión de quien gobierna el embudo.
    firma_etapa_por_embudo: dict[str, str] = Field(default_factory=dict)
    # Cuánto se espera a `integration` al crear el sobre o leer su estado.
    firma_espera_s: float = Field(10.0, ge=0.5, le=60.0)

    # ── Renovaciones (CRM-03.03.02.10) ────────────────────────────────────
    # Cada cuántos segundos se revisan los contratos que vencen. Mirar a menudo
    # y actuar sólo cuando toca lo hace inmune a los reinicios.
    renovacion_revisar_s: int = Field(3_600, ge=60, le=86_400)
    # Crear una oportunidad de renovación al llegar el preaviso. Apagado, el
    # preaviso sólo avisa, como antes.
    renovacion_crear_oportunidad: bool = True
    # En qué embudo nace (su clave). Vacío: el embudo por defecto.
    renovacion_embudo: str = ""


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
            clave="lead_dedupe_umbral_sugerencia",
            tipo="float",
            descripcion="Parecido (0 a 1) desde el que un lead existente se propone como duplicado",
            minimo=0,
            maximo=1,
            campo_settings="lead_dedupe_umbral_sugerencia",
        ),
        ClaveAjuste(
            clave="lead_dedupe_umbral_bloqueo",
            tipo="float",
            descripcion="Parecido (0 a 1) desde el que un duplicado de lead bloquea el alta",
            minimo=0,
            maximo=1,
            campo_settings="lead_dedupe_umbral_bloqueo",
        ),
        ClaveAjuste(
            clave="lead_dedupe_contactos",
            tipo="bool",
            descripcion="Buscar también entre los contactos del maestro al dar de alta un lead",
            campo_settings="lead_dedupe_contactos",
        ),
        ClaveAjuste(
            clave="lead_dedupe_espera_s",
            tipo="float",
            descripcion="Segundos que se espera a los contactos al deduplicar un lead",
            minimo=0.2,
            maximo=30,
            campo_settings="lead_dedupe_espera_s",
        ),
        ClaveAjuste(
            clave="lead_dedupe_max_candidatos",
            tipo="int",
            descripcion="Candidatos a duplicado que se enseñan al dar de alta un lead",
            minimo=1,
            maximo=50,
            campo_settings="lead_dedupe_max_candidatos",
        ),
        ClaveAjuste(
            clave="lead_dedupe_captura",
            tipo="str",
            descripcion="Qué hace la captura automática con un lead duplicado",
            opciones=("marcar", "fusionar", "nada"),
            campo_settings="lead_dedupe_captura",
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
        # Las lecciones aprendidas, todas en caliente: dónde empieza una señal
        # es una decisión de negocio de cada empresa, no del código.
        ClaveAjuste(
            clave="lecciones_minimo_comparables",
            tipo="int",
            descripcion="Ganadas del mismo embudo que hacen falta para comparar una lección",
            minimo=1,
            maximo=1_000,
            campo_settings="lecciones_minimo_comparables",
        ),
        ClaveAjuste(
            clave="lecciones_actividades_max",
            tipo="int",
            descripcion="Actividades de la oportunidad que se traen al expediente",
            minimo=1,
            maximo=5_000,
            campo_settings="lecciones_actividades_max",
        ),
        ClaveAjuste(
            clave="lecciones_factor_lento",
            tipo="float",
            descripcion="Veces lo de las ganadas para que el tiempo en una etapa sea señal",
            minimo=1.1,
            maximo=20,
            campo_settings="lecciones_factor_lento",
        ),
        ClaveAjuste(
            clave="lecciones_descuento_margen_pp",
            tipo="float",
            descripcion="Puntos de descuento sobre la mediana de las ganadas que son señal",
            minimo=0,
            maximo=100,
            campo_settings="lecciones_descuento_margen_pp",
        ),
        ClaveAjuste(
            clave="lecciones_dias_sin_contacto",
            tipo="int",
            descripcion="Días sin contacto antes de cerrar que cuentan como seguimiento flojo",
            minimo=1,
            maximo=365,
            campo_settings="lecciones_dias_sin_contacto",
        ),
        ClaveAjuste(
            clave="lecciones_consejos_max",
            tipo="int",
            descripcion="Lecciones que se traen como consejo a una oportunidad abierta",
            minimo=1,
            maximo=50,
            campo_settings="lecciones_consejos_max",
        ),
        ClaveAjuste(
            clave="lecciones_parecido_minimo",
            tipo="float",
            descripcion="Parecido mínimo (0 a 1) para que una lección cuente como parecida",
            minimo=0,
            maximo=1,
            campo_settings="lecciones_parecido_minimo",
        ),
        ClaveAjuste(
            clave="lecciones_resumen_dias",
            tipo="int",
            descripcion="Cada cuántos días sale el resumen de lecciones",
            minimo=1,
            maximo=90,
            campo_settings="lecciones_resumen_dias",
        ),
        ClaveAjuste(
            clave="firma_etapa_por_embudo",
            tipo="json",
            descripcion=(
                "A qué etapa lleva una firma completada, por embudo: "
                "{clave del embudo: clave de la etapa}. Sin embudo, sólo se marca"
            ),
            campo_settings="firma_etapa_por_embudo",
        ),
        ClaveAjuste(
            clave="firma_espera_s",
            tipo="float",
            descripcion="Segundos que se espera a integración al crear o leer el sobre de firma",
            minimo=0.5,
            maximo=60,
            campo_settings="firma_espera_s",
        ),
        ClaveAjuste(
            clave="renovacion_crear_oportunidad",
            tipo="bool",
            descripcion="Crear una oportunidad de renovación al llegar el preaviso del contrato",
            campo_settings="renovacion_crear_oportunidad",
        ),
        ClaveAjuste(
            clave="renovacion_embudo",
            tipo="str",
            descripcion="Clave del embudo donde nacen las renovaciones (vacío: el de por defecto)",
            campo_settings="renovacion_embudo",
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
