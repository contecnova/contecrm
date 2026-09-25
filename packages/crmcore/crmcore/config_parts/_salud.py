"""Cómo se mide la salud de una cuenta (CRM-05.02.01.04).

**Nada de esto es una verdad del negocio, y por eso es configuración.** Qué es un
cliente sano depende de si se vende por suscripción o por proyecto, de si la
compra es recurrente o anual, y de cuánto se habla con él normalmente. Un número
escrito en el código sería la opinión de quien lo escribió, aplicada a todos.

Los pesos de partida son los de `intelligence.salud.PESOS_POR_DEFECTO` y están
pensados para suscripción, donde manda el uso del producto. En esta instalación
el uso NO se puede medir —no hay telemetría— así que la máquina repartirá su peso
entre las señales que sí lleguen y dirá qué parte quedó sin medir. Eso es
correcto y es lo que hay que ver antes de tocar los pesos: afinarlos sobre el
papel, sin resultados delante, es adivinar.

Todo esto se edita desde Admin sin desplegar (`runtime_settings`).
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class _SaludSettings(BaseSettings):
    # ── Cada cuánto se recalcula ──────────────────────────────────────────
    # Por la noche, no en cada apertura de ficha: la salud no cambia en una
    # tarde, y recalcularla al abrir pondría una consulta pesada en el camino de
    # una pantalla que se abre cien veces al día.
    salud_recalculo_horas: int = Field(24, ge=1, le=720)

    # ── Relación: cuándo se enfría ────────────────────────────────────────
    # Días desde la última interacción a partir de los cuales la relación deja de
    # puntuar al máximo, y días a partir de los cuales puntúa cero. Entre medias
    # baja de forma lineal.
    #
    # 30 y 120 son un punto de partida de compra recurrente. En venta de proyecto
    # anual, hablar cada tres meses puede ser lo normal y 120 hundiría a clientes
    # que están bien.
    salud_relacion_dias_frescura: int = Field(30, ge=1, le=365)
    salud_relacion_dias_frio: int = Field(120, ge=2, le=1095)
    # Cuánto resta cada compromiso vencido y sin cerrar con ese cliente. No es lo
    # mismo no hablarse que haberle prometido algo y no cumplirlo.
    salud_relacion_penalizacion_vencida: int = Field(10, ge=0, le=100)

    # ── Soporte: incidencias y promesas rotas ─────────────────────────────
    # Cuánto resta cada caso abierto y cada incumplimiento de SLA. El segundo
    # pesa más a propósito: tener incidencias es normal, romper lo prometido no.
    salud_soporte_penalizacion_caso: int = Field(8, ge=0, le=100)
    salud_soporte_penalizacion_sla: int = Field(20, ge=0, le=100)
    # A partir de cuántos días un caso abierto cuenta como enquistado y penaliza
    # como si fuera dos.
    salud_soporte_dias_enquistado: int = Field(15, ge=1, le=365)

    # ── Valor: contratos y negocio ────────────────────────────────────────
    # Días antes del vencimiento a partir de los cuales un contrato sin renovación
    # automática y sin preaviso dado empieza a restar. Es el riesgo con fecha.
    salud_valor_dias_preaviso: int = Field(90, ge=1, le=730)
    salud_valor_penalizacion_vencimiento: int = Field(30, ge=0, le=100)

    # ── Bandas ────────────────────────────────────────────────────────────
    # Dónde empieza cada nivel. Son los de `intelligence.salud` y se repiten aquí
    # para poder moverlos sin desplegar.
    salud_umbral_sana: int = Field(75, ge=1, le=100)
    salud_umbral_vigilar: int = Field(55, ge=1, le=100)
    salud_umbral_riesgo: int = Field(35, ge=1, le=100)

    # ── Pesos de cada señal ───────────────────────────────────────────────
    # Los de fábrica. `uso` y `pago` se quedan porque el día que lleguen esos
    # datos tienen que pesar lo que les toca; mientras no lleguen, su peso se
    # reparte solo y la respuesta dice cuánto quedó sin medir.
    salud_peso_uso: int = Field(30, ge=0, le=100)
    salud_peso_soporte: int = Field(20, ge=0, le=100)
    salud_peso_relacion: int = Field(20, ge=0, le=100)
    salud_peso_pago: int = Field(10, ge=0, le=100)
    salud_peso_valor: int = Field(10, ge=0, le=100)
    salud_peso_patrocinador: int = Field(10, ge=0, le=100)
