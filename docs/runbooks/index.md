# Runbooks

Qué hacer cuando salta cada alerta. Uno por alerta, y **ninguna alerta sin el
suyo**: una alerta sin instrucciones despierta a alguien a las tres de la mañana
para que averigüe desde cero qué significa, y lo que pasa después —siempre— es
que se silencia.

Hay un gate (`tests/unit/test_alertas_con_runbook.py`) que falla si una alerta
enlaza un runbook que no existe, o si hay un runbook que ninguna alerta usa.

Cada uno sigue la misma estructura, y el orden importa: primero **qué significa**
—porque quien lo abre a las tres de la mañana no tiene contexto—, luego **cuánto
corre**, después **qué mirar** y por último **qué hacer**. Diagnóstico antes que
acción: la mitad de los incidentes se empeoran actuando sobre el síntoma
equivocado.

| Alerta | Gravedad | Runbook |
|---|---|---|
| `ServicioCaido` | crítica | [servicio-caido](servicio-caido.md) |
| `ErroresDeServidor` | crítica | [errores-de-servidor](errores-de-servidor.md) |
| `TablaDeSalidaAtascada` | crítica | [tabla-de-salida-atascada](tabla-de-salida-atascada.md) |
| `LatenciaAlta` | aviso | [latencia-alta](latencia-alta.md) |
| `EventosFallando` | aviso | [eventos-fallando](eventos-fallando.md) |
| `TenantCercaDeSuCuota` | aviso | [tenant-cerca-de-su-cuota](tenant-cerca-de-su-cuota.md) |
| `DemasiadosRechazosPorLimite` | aviso | [demasiados-rechazos-por-limite](demasiados-rechazos-por-limite.md) |
| `ExplotacionNoDisponible` | aviso | [explotacion-no-disponible](explotacion-no-disponible.md) |
