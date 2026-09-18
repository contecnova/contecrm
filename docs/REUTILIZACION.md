# Qué se reutiliza de las otras soluciones de la casa

`contecrm` no parte de cero. Cuatro soluciones en producción —`contecmind`,
`contecweb`, `contecflow-PSA` y `contecpos`— ya tienen resuelto, medido y
endurecido buena parte de lo que el catálogo funcional pide, sobre todo el
Módulo 0 (plataforma) y trozos grandes de los módulos 1, 3, 4, 5 y 7.

Este documento es el inventario **medido** (rutas y líneas reales, contadas el
2026-09-18), no una lista de buenas intenciones. Cada entrada del catálogo que
tiene precedente lo lleva anotado en el campo `reutiliza` de
[`docs/catalogo/catalogo.yaml`](catalogo/catalogo.yaml), así que el origen no se
pierde nunca: se puede ir de una capacidad a la implementación de referencia.

> **Regla de la casa:** antes de escribir un módulo nuevo, se busca en las otras
> cuatro soluciones. Si existe, se porta y se mejora; no se reinventa. Y si algo
> de ellas es útil aquí aunque el catálogo no lo pidiera, entra igual — el
> catálogo es un suelo, no un techo.

---

## 1. De dónde sale cada cosa

### `contecpos` — el patrón de "servicios orquestados, no monolito"

Es el precedente arquitectónico directo, y por eso `contecrm` copia su forma:

| Pieza | Dónde | Qué aporta a contecrm |
|---|---|---|
| 14 servicios por capacidad | `services/{identidad,clientas,catalogo,agenda,…}` | La descomposición por capacidad de negocio (CRM-00.03.01.01) |
| Una base y un rol por servicio | `deploy/crear-bases.sh` | Propiedad exclusiva de datos **impuesta por permisos**, no por convención (CRM-00.03.01.02) |
| Bus con backends intercambiables | `packages/common/src/bus.ts` | NATS JetStream en producción, bus en memoria en pruebas, sin cambiar el código de negocio (CRM-00.02.02.05) |
| Transactional outbox | `packages/common/src/outbox.ts` | Consistencia entre BD y bus, entrega at-least-once (CRM-00.03.02.06) |
| Plantilla de servicio | `services/_template/` | Que dar de alta un servicio nuevo sea copiar una carpeta, no improvisar |
| Perfiles de compose | `docker-compose.yml` (`app`, `web`, `sim`, `ops`) | Levantar solo infraestructura, o infra + servicios, o todo |
| Contratos versionados | `packages/contracts/` (buf + protobuf) | Contract testing entre servicios (CRM-00.03.01.03) |

### `contecmind` — la plataforma multi-tenant endurecida

Es de donde sale casi todo el Módulo 0 de seguridad, aislamiento y operación:

| Pieza | Dónde | Líneas |
|---|---|---|
| RLS en el motor + rol sin BYPASSRLS | `alembic/versions/0119_rls.py`, `deploy/sql/rls_app_role.sql` | — |
| Guard ORM de tenant (segunda red) | `app/db/tenant_guard.py` | 160 |
| GUC de tenant por transacción | `app/db/session.py` (`_rls_apply_on_begin`) | — |
| Contexto de tenant | `app/services/tenant_context.py` | 260 |
| Ajustes en caliente por tenant (986 ajustes) | `app/services/runtime_settings*.py` (7 módulos) | 1.084 solo el catálogo de claves |
| Configuración por dominios | `app/config_parts/_*.py` (10 mixins) | — |
| Auditoría con cadena de hash verificable | `app/services/audit.py`, `deploy/sql/audit_immutable.sql` | 668 |
| Rate limiting por tenant/usuario/endpoint | `app/core/rate_limit.py` | 508 |
| Idempotencia | `app/core/idempotency.py` | 238 |
| Circuit breaker y degradación | `app/core/circuit_breaker.py`, `degradation.py` | 326 + 270 |
| Métricas Prometheus por tenant | `app/core/metrics.py` | 577 |
| Trazas OpenTelemetry | `app/core/tracing.py` | 147 |
| Logging estructurado con redacción de PII | `app/core/logging.py` | — |
| Cifrado de campo y cripto | `app/db/encrypted_text.py`, `app/core/crypto.py` | 83 + 252 |
| Entitlements y planes | `app/services/entitlements.py` | 204 |
| Medición para facturación | `app/services/metering.py` | 301 |
| Motor de aprobaciones multi-etapa (SoD, SLA, delegación) | `app/services/approval_engine/` | — |
| Explicador y simulador de permisos | `app/services/access_explainer.py`, `access_simulator.py` | — |
| Legal hold | `app/services/legal_hold.py` | — |
| Gates locales en lugar de CI | `.pre-commit-config.yaml`, `scripts/preflight.py`, `check_docs_coverage.py` | — |
| Manual por audiencias + mkdocs | `docs/manual-1..6`, `mkdocs.yml` | — |
| Backup, restore y verificación de integridad | `scripts/backup.sh`, `restore.sh`, `test_restore_integrity.sh` | — |

### `contecweb` — identidad, ABAC, conectores y contratos

| Pieza | Dónde | Líneas |
|---|---|---|
| SCIM 2.0 | `app/services/scim.py` | 699 |
| SAML 2.0 y SSO | `app/services/saml.py`, `sso.py` | 236 + 330 |
| MFA (TOTP, retos) | `app/services/mfa.py`, `mfa_challenges.py` | 419 |
| Sesiones y suplantación auditada | `app/services/sessions.py`, `sesion_cedida.py` | 392 |
| ABAC (motor + políticas + enforcement) | `app/services/abac.py`, `abac_policies.py`, `abac_enforce.py` | 394 + 354 + 136 |
| Campos personalizados | `app/services/custom_fields.py` | 458 |
| Webhooks con firma y reintentos | `app/services/webhooks.py` | 528 |
| Conector HTTP/REST genérico **(verificado 2026-09-14)** | `app/connectors/api/`, `base.py` | — |
| Normalización y coincidencia difusa | `app/services/normalization/` | — |
| Contratos | `app/services/contracts.py` | 648 |
| GRC | `app/services/grc.py` | 786 |
| Enlaces compartidos con caducidad | `app/services/share_links.py` | 477 |
| Búsquedas guardadas (constructor de criterios) | `app/services/saved_searches.py` | 678 |
| Numeración documental | `app/services/numbering.py` | 394 |
| Cadena de auditoría | `app/services/audit_chain.py` | 364 |

### `contecflow-PSA` — el CRM que ya existe a medias

Es la que más funcionalidad de **negocio** aporta, y buena parte no estaba en el
catálogo original pero entra igual porque ya está hecha y encaja:

| Pieza | Dónde | Qué cubre del catálogo |
|---|---|---|
| Pipeline de oportunidades y etapas | `app/models/pipeline.py` (311), `app/services/pipeline_service.py`, `pipeline_stages_service.py` | CRM-03.01.01 completo |
| Clientes y organizaciones jerárquicas | `app/models/clients.py`, `enterprise.py` (473), `app/services/organizations_service.py` | CRM-01.01.01 |
| Actividades | `app/models/activity.py`, `app/services/activity_service.py` | CRM-01.02.01 |
| Service desk completo (tickets, SLA, colas, CMDB, activos, problemas, cambios, catálogo, conocimiento) | `app/models/service_desk/` (13 módulos), `app/services/service_desk/` (30+) | Módulo 4 casi entero |
| Motor de SLA con relojes y escalados | `app/services/sla_service.py` | CRM-04.01.02 |
| Suite BI (report builder, dashboards, OLAP, ETL, embebido, alertas inteligentes, anomalías, versionado de datos, GDPR) | `app/services/bi_*.py` (25 módulos), `olap/` | Módulo 5.1 casi entero |
| Automatizaciones declarativas | `app/models/automations.py`, `app/services/automations_service.py` | CRM-00.03.03 |
| Procesos BPMN | `app/models/bpmn_process.py`, `app/services/bpmn_process_service.py` | CRM-00.03.02.02 |
| Firma electrónica con evidencia | `app/services/esign_service.py`, `esign_providers.py`, `signature_pdf.py` | CRM-03.03.02.07 |
| Propuestas, contratos y PDF de marca | `app/services/proposal_service.py`, `contract_service.py`, `_pdf_marca.py` | CRM-03.03.02 |
| Portal de cliente | `app/models/client_portal.py` (349), `app/services/client_portal_service.py`, `portal_conversation_service.py` | CRM-04.03.02.01 |
| Formularios públicos | `app/models/public_forms.py`, `app/services/public_forms_service.py` | CRM-01.01.03.02 |
| NPS / encuestas | `app/models/nps.py`, `app/services/nps_service.py` | CRM-04.01.01.12 |
| Moneda y tipos de cambio con histórico | `app/models/money.py`, `exchange_rates_log.py`, `app/services/exchange_rate_service.py` | CRM-07.01.01.06, CRM-03.02.01.07 |
| Revenue, rentabilidad y costes | `app/services/revenue_service.py`, `profitability_service.py`, `cost_service.py` | CRM-03.01.01.06 |
| Marketplace de extensiones | `app/models/marketplace.py`, `app/services/marketplace_service.py` | CRM-00.03.04.10 |
| Portal de desarrollador y apps OAuth | `app/services/developer_portal_service.py`, `app/models/oauth_apps.py` | CRM-00.02.04.06 |
| Conectores de terceros | `salesforce_service.py`, `stripe_service.py`, `jira_service.py`, `m365_service.py`, `slack_service.py`, `git_service.py` | CRM-00.03.04.01 |
| ML (features, entrenamiento, reentrenamiento, gobierno de modelos) | `app/services/ml_*.py`, `predictive_retraining_service.py`, `app/models/ml_model.py`, `ai_governance.py` | Módulo 5.2 |
| Capacidad, skills y planificación de recursos | `capacity_planning_service.py`, `skill_service.py`, `resource_analytics.py` | CRM-03.02.02.07, CRM-04.01.01.06 |
| WebSockets y notificaciones en tiempo real | `app/services/ws_manager.py`, `realtime_notifications.py` | CRM-00.02.02.10 |

---

## 2. Lo que entra aunque el catálogo no lo pidiera

El catálogo funcional es un suelo. Estas capacidades ya existen en la casa, son
útiles en un CRM y se incorporan al alcance aunque no aparecieran en la lista
original. Están dadas de alta en el catálogo con su propio ID para que no vivan
fuera de la trazabilidad:

| Capacidad | De dónde | Por qué entra |
|---|---|---|
| Motor de aprobaciones unificado (multi-etapa, SoD, SLA, delegación) | contecmind `approval_engine/` | El catálogo lo pide troceado en cuatro sitios (descuentos, contenidos, comisiones, human-in-the-loop). Un solo motor los cubre todos |
| Explicador y simulador de permisos | contecmind `access_explainer.py` | El catálogo lo pedía como D (CRM-00.05.02.11); ya está hecho, así que pasa a estar disponible desde la fase 0 |
| Auditoría con cadena de hash y anclaje WORM | contecmind + contecweb | Convierte CRM-00.05.04.01 de "log de auditoría" en "log **verificable**" |
| Gobierno de modelos de IA y evaluaciones | contecmind `evals.py`, `drift.py`; contecflow `ai_governance.py` | Hace auditable el Módulo 5 desde el principio |
| Numeración documental configurable | contecweb `numbering.py` | Presupuestos, pedidos y contratos lo necesitan y no estaba en el catálogo |
| Búsquedas guardadas y alertas sobre criterios | contecweb `saved_searches.py`, contecmind `search_alerts.py` | Es el 80 % del constructor de segmentos (CRM-02.01.01) y sirve además a ventas y servicio |
| Detección de contradicciones y frescura del dato | contecmind `contradiction_scanner.py`, `freshness.py` | Calidad de dato (CRM-01.01.04) con más alcance del que pedía el catálogo |
| Cola de excepciones asignable (stewardship) | contecmind `gap_tasks.py` | CRM-01.01.04.08 sin escribir nada nuevo |
| OKR y presupuestos | contecflow `okr_service.py`, `budgets_service.py` | Cuotas comerciales y objetivos de campaña salen de aquí |
| Escenarios y simulación | contecflow `scenarios_service.py` | Planificación de territorios y de capacidad |

---

## 3. Lo que NO se reutiliza, y por qué

Ser honesto con esto vale tanto como el inventario:

- **El monolito como forma.** `contecmind`, `contecweb` y `contecflow-PSA` son
  monolitos FastAPI de un solo despliegue. Aquí la decisión es la de `contecpos`:
  servicios orquestados. Se porta el **contenido** de sus módulos, no su
  empaquetado.
- **Las verticales.** El dominio de `contecpos` (salones, reservas, TPV,
  VeriFactu) y el de `contecmind` (RAG documental) no son CRM. Se reutiliza su
  plataforma, no su negocio.
- **`app/config.py` con 986 ajustes en un solo `Settings`.** El patrón de
  mixins por dominio sí se porta; el tamaño no. Aquí cada servicio tiene su
  `Settings` propio y comparte solo los mixins transversales.
- **Código con deuda conocida y documentada.** Donde la solución de origen anota
  una limitación (por ejemplo, que el guard ORM de `contecmind` no cubre los
  modelos sin columna `tenant_id`), aquí se corrige de raíz en vez de heredarla:
  en `contecrm` **toda** tabla de negocio lleva `tenant_id`, sin excepciones, y
  hay un gate que lo exige.

---

## 4. Cómo se porta una pieza

1. Se localiza en la solución de origen y se lee entera, incluidos los
   comentarios de auditoría (suelen documentar por qué está así y qué se
   intentó antes).
2. Se adapta a `crmcore`: nombres en inglés para el código, comentarios en
   castellano, configuración a `Settings` + ajustes en caliente, **cero
   constantes de comportamiento**.
3. Se le añade `tenant_id` si no lo tenía, y su prueba de aislamiento.
4. Se anota en `catalogo.yaml` (`reutiliza:`) y se marca `estado: hecho` solo
   cuando hay prueba que cite el ID y documentación en el manual.
