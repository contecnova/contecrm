# Resumen del catálogo

> **Generado** por `python scripts/gen_catalogo_md.py`. No se edita a mano.

## Por módulo

| Módulo | Capacidades | Hecho | En curso | Pendiente |
|---|--:|--:|--:|--:|
| 0 — Plataforma y arquitectura transversal | 200 | 84 | 16 | 100 |
| 1 — Núcleo de datos de cliente (Customer 360) | 52 | 23 | 7 | 22 |
| 2 — Marketing | 54 | 0 | 0 | 54 |
| 3 — Ventas (SFA) | 65 | 7 | 0 | 58 |
| 4 — Servicio y atención al cliente | 62 | 0 | 0 | 62 |
| 5 — Analítica, inteligencia e IA | 45 | 0 | 0 | 45 |
| 6 — Productividad y colaboración | 12 | 0 | 2 | 10 |
| 7 — Administración, ALM y gobierno | 25 | 9 | 2 | 14 |
| 8 — Requisitos no funcionales | 12 | 1 | 0 | 11 |

## Por criticidad

| Criticidad | Total | Hecho |
|---|--:|--:|
| C — Core | 175 | 90 |
| A — Avanzado | 313 | 33 |
| D — Diferencial | 39 | 1 |

## Por fase

| Fase | Alcance | Capacidades | Hecho |
|---|---|--:|--:|
| 0 · Cimientos | Módulo 0 completo | 180 | 86 |
| 1 · Núcleo | Módulo 1 + Ventas básica (3.1) + administración (7.1) | 73 | 37 |
| 2 · Proceso comercial | Forecasting, territorios, cotización, contratos, order-to-cash | 94 | 1 |
| 3 · Servicio | Casos, SLA, omnicanalidad, conocimiento, portal | 47 | 0 |
| 4 · Marketing | Segmentación, journeys, canales, atribución | 55 | 0 |
| 5 · Inteligencia | Analítica avanzada, predictivos, IA generativa y agentes | 48 | 0 |
| 6 · Ecosistema | PRM, field service, marketplace de extensiones, MCP | 30 | 0 |

## Reutilización

**291 de 527** capacidades tienen una implementación de referencia en otra solución de la casa. El inventario medido está en [REUTILIZACION.md](../REUTILIZACION.md).

| Origen | Capacidades |
|---|--:|
| contecmind | 130 |
| contecflow-PSA | 98 |
| contecweb | 38 |
| contecpos | 20 |
| contecweb (linaje del dato por fuente) | 1 |
| orchestrator (motor de procesos de la fase 0) | 1 |
| metadata (campos y scoring configurables de la fase 0) | 1 |
| orchestrator + marketing (recorridos multicanal) | 1 |
| contecweb (compilador de métricas con SQL verificable) | 1 |
