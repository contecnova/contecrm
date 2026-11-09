"""Ajustes propios del servicio de marketing."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from crmcore.config import Settings
from crmcore.runtime.keys import ClaveAjuste, registrar_claves
from crmcore.runtime.settings import registrar_ajustes_servicio
from pydantic import Field


class AjustesMarketing(Settings):
    """Configuración del servicio `marketing`."""

    # ── Separación transaccional / promocional (CRM-02.03.01.07) ──────────
    # Dominios de envío. Van separados porque comparten reputación: una campaña
    # con muchas quejas hunde la entrega de las facturas, y mezclarlos hace que
    # darse de baja de la newsletter parezca que apaga los avisos de servicio.
    # Vacíos por defecto **a propósito**: así el sistema dice que no están
    # separados en vez de fingir que sí con un valor inventado.
    dominio_promocional: str = ""
    dominio_transaccional: str = ""

    # ── Recorridos (CRM-02.02.02) ─────────────────────────────────────────
    # Mínimo de personas por variante para declarar ganadora una prueba A/B. Con
    # menos, la diferencia que se ve es ruido y elegir por ella consolida una
    # variante peor con la confianza de haberla medido.
    prueba_minimo_por_variante: int = 100

    # ── Fondos de marketing del canal (CRM-03.04.01.04) ───────────────────
    # Plazo para justificar una acción aprobada con MDF. Sin plazo, las facturas
    # llegan contra un presupuesto que ya cerró y no las paga nadie.
    mdf_dias_para_justificar: int = Field(60, ge=1, le=365)
    # Exigir evidencia documental para justificar. Encendido: lo que se paga sin
    # factura ni material no se puede defender en una auditoría. Se puede apagar
    # en programas donde la evidencia la lleva otro sistema.
    mdf_exigir_evidencia: bool = True

    # ── Audiencias en plataformas publicitarias (CRM-02.01.01.09) ─────────
    # Por debajo de este número no se manda una audiencia: la plataforma no
    # puede anonimizar nada y el segmento se convierte en señalar a alguien.
    audiencia_minimo: int = Field(100, ge=1, le=1_000_000)
    # La finalidad del consentimiento (en `party`) que habilita subir a alguien
    # a una red de anuncios. El del boletín NO vale: aceptar correos no es
    # aceptar que tu dirección se suba a una plataforma de terceros.
    audiencia_finalidad: str = "perfilado"
    # Canal del consentimiento que se pregunta.
    audiencia_canal_consentimiento: str = "email"
    # Las operaciones que se piden a la conexión de la plataforma. Son claves de
    # operaciones declaradas en `integration`: el proveedor es configuración.
    audiencia_op_crear: str = "crear_audiencia"
    audiencia_op_anadir: str = "anadir_miembros"
    audiencia_op_quitar: str = "quitar_miembros"
    # Cuántos identificadores por llamada. Las plataformas limitan el lote.
    audiencia_lote: int = Field(1000, ge=1, le=100_000)

    # ── Mejor hora y canal (CRM-02.02.02.05) ──────────────────────────────
    # Lo que se usa cuando el historial no basta para personalizar.
    momento_hora_por_defecto: int = Field(10, ge=0, le=23)
    momento_canal_por_defecto: str = "email"
    # Entre qué canales se elige. Uno que no tenga transporte no se ofrece.
    momento_canales: str = "email,sms"

    # ── Transaccional y promocional (CRM-02.03.01.07) ─────────────────────
    # Remitente de cada clase. Su dominio TIENE que ser el de la clase: si no,
    # el correo sale por el dominio equivocado y se rechaza antes de salir.
    remitente_promocional: str = ""
    remitente_transaccional: str = ""
    # El flujo (servidor SMTP) de cada clase: host, puerto, tls, usuario, clave.
    # Vacío = el del canal de correo del tenant, y si no, el del despliegue.
    correo_flujo_promocional: dict[str, Any] = Field(default_factory=dict)
    correo_flujo_transaccional: dict[str, Any] = Field(default_factory=dict)
    # Dónde se da de baja la gente. Va en la cabecera `List-Unsubscribe` de lo
    # promocional; `{email}` se sustituye por la dirección.
    correo_url_baja: str = ""

    # ── Previsualización y spam (CRM-02.03.01.06) ─────────────────────────
    # Los clientes de correo en los que se previsualiza: ancho, si enseña las
    # imágenes de entrada y si pinta en modo oscuro.
    vista_previa_clientes: list[dict[str, Any]] = Field(
        default_factory=lambda: [
            {"clave": "escritorio", "nombre": "Escritorio", "ancho": 800, "imagenes": True},
            {"clave": "movil", "nombre": "Móvil", "ancho": 375, "imagenes": True},
            {
                "clave": "sin_imagenes",
                "nombre": "Sin imágenes (Outlook de empresa)",
                "ancho": 640,
                "imagenes": False,
            },
            {
                "clave": "oscuro",
                "nombre": "Modo oscuro",
                "ancho": 600,
                "imagenes": True,
                "oscuro": True,
            },
        ]
    )
    # A partir de cuántos puntos se considera que el correo va a basura.
    spam_umbral: float = Field(5.0, ge=0.5, le=100)
    # Lo que suma cada regla. Se puede afinar por instalación.
    spam_pesos: dict[str, float] = Field(
        default_factory=lambda: {
            "asunto_vacio": 2.0,
            "asunto_mayusculas": 1.5,
            "asunto_exclamaciones": 1.0,
            "palabras_gatillo": 0.8,
            "sin_texto": 2.5,
            "poco_texto_por_imagen": 1.5,
            "imagen_sin_alt": 0.3,
            "muchos_enlaces": 1.0,
            "enlace_a_ip": 2.0,
            "acortador": 1.2,
            "enlace_engana": 2.5,
            "enlace_sin_https": 0.5,
            "promocional_sin_baja": 3.0,
            "sin_dominio": 2.0,
            "sin_spf": 1.5,
            "sin_dkim": 1.5,
            "sin_dmarc": 1.0,
            "dmarc_none": 0.3,
            "remitente_otro_dominio": 2.0,
            "tokens_sin_rellenar": 2.0,
        }
    )
    spam_palabras: list[str] = Field(
        default_factory=lambda: [
            "gratis",
            "100% gratis",
            "gana dinero",
            "urgente",
            "oferta exclusiva",
            "haz clic aquí",
            "sin coste",
            "garantizado",
            "última oportunidad",
            "dinero fácil",
        ]
    )
    spam_acortadores: list[str] = Field(
        default_factory=lambda: ["bit.ly", "tinyurl.com", "goo.gl", "t.co", "ow.ly", "is.gd"]
    )
    # Enlaces a partir de los cuales un correo se parece a un folleto de spam.
    spam_maximo_enlaces: int = Field(15, ge=1, le=500)

    # ── Recomendaciones en la personalización (CRM-02.03.01.02) ───────────
    recomendaciones_maximo: int = Field(3, ge=1, le=20)

    # ── Prueba A/B con ganador automático (CRM-02.02.02.04) ───────────────
    # Nivel de significación con el que se declara ganadora una variante.
    prueba_significacion: float = Field(0.05, gt=0, lt=0.5)
    # Si, con ganadora declarada, el tráfico nuevo va todo a ella.
    prueba_desviar_al_ganador: bool = True

    # ── Lo que sale solo (CRM-02.02.02.05, CRM-02.02.02.01) ──────────────
    # Cada cuánto mira la tarea periódica si hay envíos a los que ya les ha
    # llegado la hora, y cuántos manda como mucho por tenant en cada vuelta (uno
    # por transacción: el resto, en la siguiente).
    envios_despachar_cada_s: int = Field(60, ge=5, le=3_600)
    envios_despacho_max_por_vuelta: int = Field(500, ge=1, le=100_000)
    # Cada cuánto se mueve a la gente por los recorridos publicados, y a cuántas
    # personas como mucho por tenant en cada vuelta.
    recorridos_avanzar_cada_s: int = Field(60, ge=5, le=3_600)
    recorridos_avance_lote: int = Field(500, ge=1, le=100_000)


registrar_claves(
    [
        ClaveAjuste(
            clave="dominio_promocional",
            tipo="str",
            descripcion="Dominio de envío de lo promocional",
            campo_settings="dominio_promocional",
        ),
        ClaveAjuste(
            clave="dominio_transaccional",
            tipo="str",
            descripcion="Dominio de envío de lo transaccional (facturas, avisos)",
            campo_settings="dominio_transaccional",
        ),
        ClaveAjuste(
            clave="mdf_dias_para_justificar",
            tipo="int",
            descripcion="Plazo para justificar una acción aprobada con fondos de marketing",
            minimo=1,
            maximo=365,
            campo_settings="mdf_dias_para_justificar",
            sensible=True,
        ),
        ClaveAjuste(
            clave="mdf_exigir_evidencia",
            tipo="bool",
            descripcion="Exigir evidencia documental para justificar un gasto de MDF",
            campo_settings="mdf_exigir_evidencia",
            sensible=True,
        ),
        ClaveAjuste(
            clave="prueba_minimo_por_variante",
            tipo="int",
            descripcion="Personas mínimas por variante para declarar ganadora una prueba A/B",
            minimo=10,
            maximo=100000,
            campo_settings="prueba_minimo_por_variante",
        ),
        ClaveAjuste(
            clave="audiencia_minimo",
            tipo="int",
            descripcion="Personas mínimas para mandar una audiencia a una plataforma publicitaria",
            minimo=1,
            maximo=1_000_000,
            campo_settings="audiencia_minimo",
            sensible=True,
        ),
        ClaveAjuste(
            clave="audiencia_finalidad",
            tipo="str",
            descripcion="Finalidad del consentimiento que habilita subir a alguien a una audiencia",
            campo_settings="audiencia_finalidad",
            sensible=True,
        ),
        ClaveAjuste(
            clave="audiencia_canal_consentimiento",
            tipo="str",
            descripcion="Canal del consentimiento que se pregunta para las audiencias",
            campo_settings="audiencia_canal_consentimiento",
        ),
        ClaveAjuste(
            clave="audiencia_op_crear",
            tipo="str",
            descripcion="Operación de la conexión que crea la audiencia en la plataforma",
            campo_settings="audiencia_op_crear",
        ),
        ClaveAjuste(
            clave="audiencia_op_anadir",
            tipo="str",
            descripcion="Operación de la conexión que añade miembros a la audiencia",
            campo_settings="audiencia_op_anadir",
        ),
        ClaveAjuste(
            clave="audiencia_op_quitar",
            tipo="str",
            descripcion="Operación de la conexión que quita miembros de la audiencia",
            campo_settings="audiencia_op_quitar",
        ),
        ClaveAjuste(
            clave="audiencia_lote",
            tipo="int",
            descripcion="Identificadores por llamada al sincronizar una audiencia",
            minimo=1,
            maximo=100_000,
            campo_settings="audiencia_lote",
        ),
        ClaveAjuste(
            clave="momento_hora_por_defecto",
            tipo="int",
            descripcion="Hora local de envío cuando el historial no basta para personalizar",
            minimo=0,
            maximo=23,
            campo_settings="momento_hora_por_defecto",
        ),
        ClaveAjuste(
            clave="momento_canal_por_defecto",
            tipo="str",
            descripcion="Canal de envío cuando el historial no dice por dónde contesta",
            campo_settings="momento_canal_por_defecto",
        ),
        ClaveAjuste(
            clave="momento_canales",
            tipo="str",
            descripcion="Canales entre los que se elige el mejor, separados por comas",
            campo_settings="momento_canales",
        ),
        ClaveAjuste(
            clave="remitente_promocional",
            tipo="str",
            descripcion="Dirección desde la que sale lo promocional",
            campo_settings="remitente_promocional",
        ),
        ClaveAjuste(
            clave="remitente_transaccional",
            tipo="str",
            descripcion="Dirección desde la que sale lo transaccional",
            campo_settings="remitente_transaccional",
        ),
        ClaveAjuste(
            clave="correo_flujo_promocional",
            tipo="json",
            descripcion="Servidor de salida de lo promocional (host, puerto, tls, usuario, clave)",
            campo_settings="correo_flujo_promocional",
            sensible=True,
        ),
        ClaveAjuste(
            clave="correo_flujo_transaccional",
            tipo="json",
            descripcion="Servidor de salida de lo transaccional (host, puerto, tls, usuario, clave)",
            campo_settings="correo_flujo_transaccional",
            sensible=True,
        ),
        ClaveAjuste(
            clave="correo_url_baja",
            tipo="str",
            descripcion="Enlace de baja de lo promocional ({email} se sustituye)",
            campo_settings="correo_url_baja",
        ),
        ClaveAjuste(
            clave="vista_previa_clientes",
            tipo="json",
            descripcion="Clientes de correo en los que se previsualiza: ancho, imágenes y modo oscuro",
            campo_settings="vista_previa_clientes",
        ),
        ClaveAjuste(
            clave="spam_umbral",
            tipo="float",
            descripcion="Puntos de spam a partir de los cuales el correo va a basura",
            minimo=0.5,
            maximo=100,
            campo_settings="spam_umbral",
        ),
        ClaveAjuste(
            clave="spam_pesos",
            tipo="json",
            descripcion="Puntos que suma cada regla de spam",
            campo_settings="spam_pesos",
        ),
        ClaveAjuste(
            clave="spam_palabras",
            tipo="json",
            descripcion="Palabras del asunto y del cuerpo que suenan a spam",
            campo_settings="spam_palabras",
        ),
        ClaveAjuste(
            clave="spam_acortadores",
            tipo="json",
            descripcion="Dominios de acortadores de enlaces",
            campo_settings="spam_acortadores",
        ),
        ClaveAjuste(
            clave="spam_maximo_enlaces",
            tipo="int",
            descripcion="Enlaces a partir de los cuales el correo se parece a un folleto",
            minimo=1,
            maximo=500,
            campo_settings="spam_maximo_enlaces",
        ),
        ClaveAjuste(
            clave="recomendaciones_maximo",
            tipo="int",
            descripcion="Recomendaciones como mucho en un correo personalizado",
            minimo=1,
            maximo=20,
            campo_settings="recomendaciones_maximo",
        ),
        ClaveAjuste(
            clave="prueba_significacion",
            tipo="float",
            descripcion="Nivel de significación para declarar ganadora una variante A/B",
            minimo=0.001,
            maximo=0.5,
            campo_settings="prueba_significacion",
        ),
        ClaveAjuste(
            clave="envios_despachar_cada_s",
            tipo="int",
            descripcion="Cada cuántos segundos se mandan solos los envíos a los que ya les toca",
            minimo_ambito="global",
            minimo=5,
            maximo=3_600,
            campo_settings="envios_despachar_cada_s",
        ),
        ClaveAjuste(
            clave="envios_despacho_max_por_vuelta",
            tipo="int",
            descripcion="Envíos que se mandan solos como mucho por tenant en cada vuelta",
            minimo_ambito="global",
            minimo=1,
            maximo=100_000,
            campo_settings="envios_despacho_max_por_vuelta",
        ),
        ClaveAjuste(
            clave="recorridos_avanzar_cada_s",
            tipo="int",
            descripcion="Cada cuántos segundos avanzan solos los recorridos publicados",
            minimo_ambito="global",
            minimo=5,
            maximo=3_600,
            campo_settings="recorridos_avanzar_cada_s",
        ),
        ClaveAjuste(
            clave="recorridos_avance_lote",
            tipo="int",
            descripcion="Personas que se mueven como mucho por tenant en cada vuelta de los recorridos",
            minimo_ambito="global",
            minimo=1,
            maximo=100_000,
            campo_settings="recorridos_avance_lote",
        ),
        ClaveAjuste(
            clave="prueba_desviar_al_ganador",
            tipo="bool",
            descripcion="Con ganadora declarada, mandar todo el tráfico nuevo a ella",
            campo_settings="prueba_desviar_al_ganador",
        ),
    ]
)


@lru_cache(maxsize=1)
def ajustes() -> AjustesMarketing:
    return AjustesMarketing()


registrar_ajustes_servicio(ajustes)


def valor(clave: str, db: Any = None) -> Any:
    """El valor efectivo de un ajuste de marketing, con su defecto de este servicio.

    El defecto se pasa explícito y no sólo por `campo_settings`: si el catálogo
    de claves se recarga sin las de marketing —las pruebas lo hacen—, `efectivo`
    devolvía `None` y una regla con peso cero se leía como «no aplica».
    """
    from crmcore.runtime.settings import efectivo

    return efectivo(clave, db, default=getattr(ajustes(), clave, None))
