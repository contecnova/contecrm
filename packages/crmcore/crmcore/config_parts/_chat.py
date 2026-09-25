"""El flujo en vivo del chat (CRM-06.02.02.07).

Los tres números de aquí deciden si una persona ve un mensaje al segundo o al
minuto, y ninguno es una verdad: dependen de cuánta gente tenga el chat abierto
—cada uno es una consulta cada `espera`— y de lo paciente que sea el proxy que
haya delante.

El **primer latido** merece explicación aparte. Un flujo SSE no existe para el
cliente hasta que llega su primer byte: uvicorn no manda las cabeceras de la
respuesta hasta el primer trozo del cuerpo, así que un flujo que no dice nada al
abrirse es, visto desde fuera, un servidor que no contesta. El de aquí callaba
hasta dieciocho segundos —seis vueltas de tres—, que es más de lo que aguanta un
`EventSource`, un nginx o un `curl` normal. Por eso se saluda de entrada, y el
saludo es un comentario SSE: no es un evento, así que ningún cliente lo procesa
como mensaje, pero abre la respuesta.

Todo esto se edita desde Admin sin desplegar (`runtime_settings`).
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class _ChatSettings(BaseSettings):
    # Cada cuánto se pregunta a la base por mensajes nuevos. Es también el
    # retraso máximo con el que se ve un mensaje. Bajarlo da más inmediatez y
    # cuesta una consulta por persona conectada y vuelta.
    chat_sse_espera_s: float = Field(3.0, ge=0.5, le=30.0)

    # Cada cuánto se manda un latido cuando no hay nada que contar. Va en
    # segundos y no en «vueltas» porque lo que hace falta —que ningún
    # intermediario dé el flujo por muerto— se mide en tiempo, y contar vueltas
    # lo ataba a la espera: subir la espera alargaba el silencio sin querer.
    #
    # 15 s deja margen de sobra frente al plazo habitual de un proxy (30-60 s).
    chat_sse_latido_s: float = Field(15.0, ge=1.0, le=300.0)

    # Cuánto le decimos al navegador que espere antes de reconectar si el flujo
    # se corta. Viaja en la línea `retry:` del propio flujo, que es la única
    # forma de decírselo a un `EventSource`.
    chat_sse_reintento_ms: int = Field(3000, ge=500, le=60000)
