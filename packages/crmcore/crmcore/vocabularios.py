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
