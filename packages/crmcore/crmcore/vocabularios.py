"""Las listas cerradas que **cruzan de un servicio a otro**.

`crmcore.contratos` comprueba que el sobre de un evento lleve los campos que el
consumidor declara necesitar. Lo que no comprueba —ni puede— es que los dos
lados entiendan lo mismo por el *valor* de ese campo. Un campo declarado en los
dos sitios deja las dos mitades en verde mientras sus vocabularios se separan,
que es el mismo agujero que el módulo de contratos describe para los campos,
una capa más abajo.

Por eso lo que viaja se escribe una vez. Aquí viven esas listas; las de un solo
servicio se quedan en su servicio, que es donde se entienden.
"""

from __future__ import annotations

# Cuánto está roto. **No es la prioridad**: la severidad es del problema —qué se
# ha roto y cuánto— y la prioridad es de la respuesta —en qué orden se atiende—.
# Fundirlas hace imposible decir «esto es grave pero puede esperar», y en cuanto
# se funden alguien marca todo como crítico.
#
# Cruza por el bus en tres sitios, y por eso está aquí: `integration.telemetria`
# la manda en el comando que abre un caso, `service.servicio` la valida al
# recibirlo —si dejaran de coincidir, el aparato avisaría y **el caso no se
# abriría**— y `service.problemas` la publica en `problem.opened`.
SEVERIDADES: tuple[str, ...] = ("baja", "media", "alta", "critica")


# QUIÉN hace una llamada, en la cabecera `x-crm-tipo`. Cruza de un servicio a
# otro en toda llamada interna, y por eso está aquí.
#
# **Medido el 29-10-2026**: había tres palabras para la misma idea, en tres
# ficheros, y no coincidían. `http.interno` firmaba las llamadas del agente
# autónomo como «maquina»; `authz.visibilidad` preguntaba por «servicio» para
# saltarse la compartición entre personas; `http.reverificacion` preguntaba por
# «servicio» o «automatizacion». «maquina» no casaba con ninguna.
#
# La consecuencia no fallaba: el agente llamaba como si fuera una persona, la
# compartición le aplicaba su filtro, esa persona no posee ningún registro, y
# `GET /accounts` le devolvía **cero filas con un 200**. El modelo concluía «no
# hay cuentas» sobre un tenant con sesenta y cinco. Es el mismo agujero que ya
# se había tapado para las credenciales de integración, con otra palabra.
TIPOS_DE_PRINCIPAL: tuple[str, ...] = ("usuario", "servicio", "automatizacion", "agente")

# Los que NO son una persona. A ninguno se le aplica la compartición entre
# usuarios —no poseen registros, no están en ningún equipo y nadie les ha
# compartido nada—, y ninguno puede reautenticarse ante una acción sensible.
#
# Lo que SÍ se les sigue aplicando son las políticas de dato (ABAC): son del
# dato y no de la persona, y algo que las esquivara sería la puerta de atrás de
# todas ellas.
NO_SON_PERSONAS: frozenset[str] = frozenset({"servicio", "automatizacion", "agente"})


def es_persona(tipo: str | None) -> bool:
    """Si quien llama es una persona, a efectos de compartición y reautenticación.

    Se pregunta por aquí y no comparando con una cadena: cada comparación suelta
    es una palabra más que puede no coincidir con la que escribe el otro lado, y
    cuando no coinciden **no falla nada** — se enseña de menos, en silencio.
    """
    return str(tipo or "usuario") not in NO_SON_PERSONAS
