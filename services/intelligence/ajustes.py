"""Ajustes propios del servicio de inteligencia.

Todos estos eran constantes de módulo, y todos son la misma clase de decisión:
**a partir de qué confianza nos fiamos de lo que dice un modelo**. Es justo lo
que cambia entre instalaciones y entre clientes de la misma instalación.

Un modelo de transcripción bueno en castellano peninsular no lo es con acento
chileno y ruido de taller; un cliente con poco volumen no puede esperar a tener
doscientos casos para entrenar; y en un sector regulado conviene exigir más
confianza antes de dejar que una extracción pise lo que escribió una persona.

Los valores por defecto están elegidos para **proponer mucho y decidir poco**:
una sugerencia que alguien descarta cuesta un clic, un dato que se mete solo y
está mal cuesta encontrarlo meses después.
"""

from __future__ import annotations

from functools import lru_cache

from crmcore.config import Settings
from crmcore.runtime.keys import ClaveAjuste, registrar_claves
from crmcore.runtime.settings import registrar_ajustes_servicio
from pydantic import Field


class AjustesIntelligence(Settings):
    """Configuración del servicio `intelligence`."""

    # ── Lo que hace falta para opinar ─────────────────────────────────────
    # Señales mínimas para dar una recomendación de siguiente mejor acción.
    # Con menos, la recomendación es el orden por defecto con otro nombre: no
    # se está recomendando nada, se está enseñando lo primero que había.
    ia_minimo_senales: int = Field(3, ge=1, le=50)

    # Caracteres mínimos de contexto para resumir o reescribir. Por debajo, el
    # modelo rellena con lo que le parece, que es exactamente lo que no se le
    # pide: resumir cuatro palabras es inventarse el resto.
    ia_minimo_contexto: int = Field(120, ge=1, le=10_000)

    # ── Cuánta confianza basta ────────────────────────────────────────────
    # Para dar por buena una extracción de campos de un texto.
    ia_confianza_extraccion: float = Field(0.5, ge=0.0, le=1.0)
    # Para dar una transcripción por fiable. Más alto que la extracción porque
    # una palabra mal oída en una llamada se cita después como si se hubiera
    # dicho.
    ia_confianza_transcripcion: float = Field(0.75, ge=0.0, le=1.0)
    # Para actuar sobre lo que se ha entendido por voz.
    ia_confianza_voz: float = Field(0.7, ge=0.0, le=1.0)
    # Parecido mínimo para proponer un caso como «ya resuelto antes».
    ia_parecido_caso: float = Field(0.7, ge=0.0, le=1.0)

    # ── Cuánto se enseña ──────────────────────────────────────────────────
    # Casos parecidos que se sugieren. Más de un puñado no se miran.
    ia_casos_sugeridos: int = Field(5, ge=1, le=50)
    # Factores de una predicción que se enseñan. Una explicación con veinte
    # factores no explica nada: se lee la lista y se cierra.
    ia_factores_visibles: int = Field(5, ge=1, le=50)

    # ── Cuándo hay datos suficientes ──────────────────────────────────────
    # Casos mínimos para entrenar un clasificador, y por clase. Un modelo
    # entrenado con treinta casos acierta en los treinta y falla fuera.
    ia_minimo_casos_entreno: int = Field(200, ge=10, le=1_000_000)
    ia_minimo_por_clase: int = Field(30, ge=1, le=100_000)
    # Qué porcentaje se reserva para validar. Sin reservar nada, la precisión
    # que se mide es la de memorizar.
    ia_pct_validacion: int = Field(25, ge=5, le=50)

    # Envíos mínimos por rama para dar una prueba A/B por concluyente. 500 es
    # lo que hace falta para que una diferencia del 1 % no sea casualidad;
    # bajarlo produce ganadores que no ganan.
    ia_minimo_por_rama: int = Field(500, ge=1, le=1_000_000)


# ── Cuáles se pueden afinar POR CLIENTE y cuáles no ───────────────────────
#
# Sólo llevan clave en caliente las que se leen donde hay sesión. Las demás
# —el parecido de un caso, la confianza de una transcripción o de la voz, los
# mínimos para entrenar y los envíos por rama de una prueba A/B— se calculan en
# funciones puras, sin base de datos: son cálculo, no consulta, y meterles una
# sesión para leer un número sería pagar una consulta por llamada.
#
# Ésas salen del `.env` y valen para todo el despliegue. **No se les declara
# clave a propósito**: un ajuste que la consola deja poner por tenant y que
# luego no se aplica es peor que no tenerlo — quien lo pone cree que ya está.
registrar_claves(
    [
        ClaveAjuste(
            clave="ia_minimo_senales",
            tipo="int",
            descripcion="Señales mínimas para dar una recomendación",
            minimo=1,
            maximo=50,
            campo_settings="ia_minimo_senales",
        ),
        ClaveAjuste(
            clave="ia_minimo_contexto",
            tipo="int",
            descripcion="Caracteres mínimos de contexto para resumir o reescribir",
            minimo=1,
            maximo=10_000,
            campo_settings="ia_minimo_contexto",
        ),
        ClaveAjuste(
            clave="ia_confianza_extraccion",
            tipo="float",
            descripcion="Confianza mínima para dar por buena una extracción",
            minimo=0.0,
            maximo=1.0,
            campo_settings="ia_confianza_extraccion",
        ),
        ClaveAjuste(
            clave="ia_factores_visibles",
            tipo="int",
            descripcion="Cuántos factores de una predicción se enseñan",
            minimo=1,
            maximo=50,
            campo_settings="ia_factores_visibles",
        ),
    ]
)


@lru_cache(maxsize=1)
def ajustes() -> AjustesIntelligence:
    return AjustesIntelligence()


registrar_ajustes_servicio(ajustes)
