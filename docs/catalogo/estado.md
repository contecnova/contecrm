# Estado del catálogo funcional

> **Generado** por `python scripts/gen_catalogo_md.py` desde
> [`catalogo.yaml`](catalogo.yaml). No se edita a mano.

Una capacidad solo se marca **hecho** cuando se cumplen las tres cosas:
el código la implementa, hay una prueba o un sitio del código que la cita
por su identificador, y está en el manual. Lo comprueba
`tests/unit/test_catalogo_trazabilidad.py`, así que este documento no
puede decir que algo está hecho si no lo está.

**555 capacidades**: 🔧 5 en-curso · ✅ 171 hecho · ⬜ 379 pendiente

## Módulo 0 — Plataforma y arquitectura transversal

216 capacidades · ✅ 112 · ⬜ 104

### 0.1 Multi-tenancy

#### CRM-00.01.01 · Modelo de aislamiento

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-00.01.01.01` | Aislamiento lógico — esquema compartido con discriminador tenant_id en toda entidad | C | 0 | core | ✅ | contecmind:app/db/tenant_guard.py + alembic/versions/0119_rls.py |
| `CRM-00.01.01.02` | Aislamiento por esquema — un esquema por tenant sobre instancia compartida | A | 0 | core | ⬜ | contecpos:deploy/crear-bases.sh (un esquema y un rol por servicio) |
| `CRM-00.01.01.03` | Aislamiento físico — base de datos o clúster dedicado por tenant | A | 0 | tenancy | ⬜ | — |
| `CRM-00.01.01.04` | Modelo híbrido por tiers (silo para enterprise, pool para SMB) con promoción entre tiers | A | 0 | tenancy | ⬜ | — |
| `CRM-00.01.01.05` | Política de bring your own database / despliegue en la infraestructura del cliente | D | 0 | tenancy | ⬜ | — |
| `CRM-00.01.01.06` | Aislamiento a nivel de cómputo: pools de workers dedicados por tenant o por tier | A | 0 | core | ⬜ | — |
| `CRM-00.01.01.07` | Aislamiento de caché: namespacing obligatorio de claves por tenant y purga selectiva | C | 0 | core | ✅ | contecmind:app/core/cache_registry.py |
| `CRM-00.01.01.08` | Aislamiento de almacenamiento de ficheros: bucket/prefijo por tenant, URLs firmadas de vida corta | C | 0 | core | ✅ | contecmind:app/core/storage.py (S3/MinIO, URLs firmadas) |
| `CRM-00.01.01.09` | Aislamiento de índices de búsqueda (índice por tenant o filtro forzado a nivel de motor) | C | 0 | core | ✅ | contecmind:app/core/search (filtro forzado por tenant) |
| `CRM-00.01.01.10` | Aislamiento de colas y streams: partición o topic por tenant para evitar bloqueo cruzado | A | 0 | core | ✅ | contecpos:packages/common/src/bus.ts (subjects por tenant) |

#### CRM-00.01.02 · Garantías de no fuga de datos (tenant safety)

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-00.01.02.01` | Row-Level Security aplicada en el motor de datos, no solo en el ORM | C | 0 | core | ✅ | contecmind:alembic/versions/0119_rls.py + deploy/sql/rls_app_role.sql |
| `CRM-00.01.02.02` | Contexto de tenant propagado por todo el stack (cabecera → token → contexto de ejecución → conexión) | C | 0 | core | ✅ | contecmind:app/services/tenant_context.py + app/db/session.py (_rls_apply_on_begin) |
| `CRM-00.01.02.03` | Prohibición estructural de consultas sin predicado de tenant (interceptor / linter / test de arquitectura) | C | 0 | core | ✅ | contecmind:tests/unit/test_tenant_scope_contract.py |
| `CRM-00.01.02.04` | Tests automatizados de cross-tenant leakage en cada pipeline local (aquí: gate de pre-push, no CI) | C | 0 | core | ✅ | contecmind:tests/unit/test_tenant_guard_contract.py |
| `CRM-00.01.02.05` | Tenant fuzzing: suite que intenta acceder a IDs de otro tenant y exige 404 (no 403) | A | 0 | core | ✅ | — |
| `CRM-00.01.02.06` | Auditoría de acceso cruzado por personal de soporte, con justificación obligatoria | C | 0 | identity | ✅ | contecmind:app/services/audit.py (justificación obligatoria) |
| `CRM-00.01.02.07` | Detección de identificadores globales enumerables; uso de ULID/UUIDv7 opacos | A | 0 | core | ✅ | — |

#### CRM-00.01.03 · Ciclo de vida del tenant

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-00.01.03.01` | Provisioning automatizado (API + autoservicio) con plantilla de datos semilla | C | 0 | tenancy | ✅ | contecmind:app/services/tenants.py + app/services/onboarding.py |
| `CRM-00.01.03.02` | Onboarding guiado por industria: preconfiguración de objetos, pipelines y flujos | A | 0 | tenancy | ⬜ | contecmind:app/services/onboarding_guide.py |
| `CRM-00.01.03.03` | Clonado de tenant (para sandbox, demo, pre-producción) | A | 0 | tenancy | ⬜ | — |
| `CRM-00.01.03.04` | Suspensión, reactivación y congelación en modo solo lectura | C | 0 | tenancy | ✅ | — |
| `CRM-00.01.03.05` | Offboarding con exportación completa verificable y certificado de destrucción | C | 0 | tenancy | ✅ | contecmind:app/services/exports.py |
| `CRM-00.01.03.06` | Fusión de tenants (M&A) y escisión de un tenant en dos | D | 0 | tenancy | ⬜ | — |
| `CRM-00.01.03.07` | Jerarquía de tenants: matriz–filial, franquiciador–franquiciado, holding | A | 0 | tenancy | ✅ | contecflow-PSA:app/models/enterprise.py (jerarquía de organizaciones) |
| `CRM-00.01.03.08` | Sub-tenants / business units con herencia configurable de configuración y datos | A | 0 | tenancy | ✅ | contecflow-PSA:app/services/organizations_service.py |
| `CRM-00.01.03.09` | Migración entre regiones con ventana de solo lectura y verificación de integridad | A | 0 | tenancy | ⬜ | — |
| `CRM-00.01.03.10` | Migración entre tiers de aislamiento sin downtime perceptible | D | 0 | tenancy | ⬜ | — |

#### CRM-00.01.04 · Configuración y metadatos por tenant

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-00.01.04.01` | Capa de configuración jerárquica: global → tier → tenant → BU → usuario | C | 0 | tenancy | ✅ | contecmind:app/services/runtime_settings*.py (7 módulos, 986 ajustes) + contecpos:packages/common/src/ajustes.ts |
| `CRM-00.01.04.02` | Versionado de la configuración con diff y rollback | A | 0 | tenancy | ⬜ | contecflow-PSA:app/services/settings_audit_service.py |
| `CRM-00.01.04.03` | Modelo de datos extensible por tenant sin afectar a los demás | C | 0 | metadata | ✅ | contecweb:app/services/custom_fields.py + contecflow-PSA:app/services/custom_fields_service.py |
| `CRM-00.01.04.04` | Feature flags por tenant, por usuario y por porcentaje de tráfico | C | 0 | tenancy | ✅ | contecmind:app/services/entitlements.py |
| `CRM-00.01.04.05` | Catálogo de planes/entitlements que activa capacidades declarativamente | C | 0 | tenancy | ✅ | contecmind:app/services/entitlements.py + contecpos:services/identidad/src/planes |
| `CRM-00.01.04.06` | Marca blanca: logo, paleta, dominio propio, plantillas de correo, dominio de envío | A | 0 | tenancy | ⬜ | contecflow-PSA:app/services/branding_service.py |
| `CRM-00.01.04.07` | Localización por tenant: idiomas, formatos, calendarios, husos, moneda funcional | C | 0 | core | ✅ | contecmind:app/services/i18n_labels.py + languages.py |
| `CRM-00.01.04.08` | Gestión de secretos y claves de integración por tenant (vault segmentado) | C | 0 | core | ✅ | contecmind:app/models/tenant_credential.py + contecweb:app/services/credentials.py |
| `CRM-00.01.04.09` | BYOK / CMEK: clave de cifrado gestionada por el cliente, con rotación y revocación | A | 0 | core | ✅ | contecmind:app/core/crypto.py + app/db/encrypted_text.py + contecflow-PSA:app/services/key_management.py |

#### CRM-00.01.05 · Residencia, soberanía y cumplimiento por tenant

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-00.01.05.01` | Pinning de región de datos por tenant (UE, EE. UU., LATAM, APAC) | A | 0 | tenancy | ⬜ | — |
| `CRM-00.01.05.02` | Residencia diferenciada por tipo de dato (transaccional vs. analítico vs. backups vs. logs) | A | 0 | tenancy | ⬜ | — |
| `CRM-00.01.05.03` | Control de subprocesadores y trazabilidad de transferencias internacionales | A | 0 | tenancy | ⬜ | contecmind:docs/COMPLIANCE.md |
| `CRM-00.01.05.04` | Modo sin salida de datos para IA: inferencia en región o modelo dedicado | A | 5 | core | ⬜ | contecmind:app/core/inference_gate.py + model_router.py |
| `CRM-00.01.05.05` | Cumplimiento verificable: ENS, ISO 27001, SOC 2 Tipo II, GDPR, sectoriales | C | 0 | docs | ✅ | contecmind:docs/COMPLIANCE.md + PENTEST_HARDENING.md |

#### CRM-00.01.06 · Cuotas, límites y equidad (noisy neighbour)

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-00.01.06.01` | Rate limiting por tenant, por API key, por usuario y por endpoint | C | 0 | gateway | ✅ | contecmind:app/core/rate_limit.py (508 líneas, por tenant/usuario/endpoint) |
| `CRM-00.01.06.02` | Cuotas de almacenamiento, registros, llamadas API, correos, workflows y tokens de IA | C | 0 | tenancy | ✅ | contecmind:app/services/entitlements.py (cuotas) + metering.py |
| `CRM-00.01.06.03` | Aislamiento de carga: bulkheads, circuit breakers y colas de prioridad por tier | A | 0 | core | ⬜ | contecmind:app/core/circuit_breaker.py |
| `CRM-00.01.06.04` | Backpressure y degradación elegante bajo saturación (diferir lo no crítico) | A | 0 | core | ⬜ | contecmind:app/core/degradation.py |
| `CRM-00.01.06.05` | Detección de tenants anómalos y throttling adaptativo automático | A | 0 | gateway | ⬜ | — |
| `CRM-00.01.06.06` | Panel de consumo por tenant con alertas de aproximación al límite | C | 0 | tenancy | ✅ | contecmind:app/services/metering.py + app/api/admin_observability.py |
| `CRM-00.01.06.07` | Medición para facturación (metering) exportable a sistema de billing | A | 0 | tenancy | ✅ | contecmind:app/services/metering.py |

### 0.2 Arquitectura headless / API-first

#### CRM-00.02.01 · Contratos de API

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-00.02.01.01` | API REST completa: todo lo que hace la UI es posible por API, sin excepciones | C | 0 | core | ✅ | — |
| `CRM-00.02.01.02` | API GraphQL para lectura compuesta y agregación en una llamada | A | 1 | gateway | ⬜ | — |
| `CRM-00.02.01.03` | gRPC / protobuf para comunicación interna y clientes de alto rendimiento | A | 0 | core | ⬜ | contecpos:packages/contracts (buf + protobuf) |
| `CRM-00.02.01.04` | Especificación OpenAPI 3.x generada desde el código, no mantenida a mano | C | 0 | core | ✅ | contecmind:scripts/dump_openapi.py |
| `CRM-00.02.01.05` | Versionado explícito (URI o cabecera) con política de deprecación publicada | C | 0 | core | ✅ | — |
| `CRM-00.02.01.06` | Compatibilidad hacia atrás garantizada; cambios rompedores solo en nueva versión mayor | C | 0 | core | ✅ | — |
| `CRM-00.02.01.07` | Sunset headers y avisos de deprecación proactivos a los consumidores | A | 0 | core | ✅ | — |
| `CRM-00.02.01.08` | Idempotencia mediante Idempotency-Key en todas las operaciones de escritura | C | 0 | core | ✅ | contecmind:app/core/idempotency.py (238 líneas) |
| `CRM-00.02.01.09` | Concurrencia optimista: ETag / If-Match / versión de registro | C | 0 | core | ✅ | — |
| `CRM-00.02.01.10` | Paginación por cursor estable, filtrado, ordenación y proyección de campos | C | 0 | core | ✅ | contecflow-PSA:app/services/pagination_service.py |
| `CRM-00.02.01.11` | Operaciones masivas: bulk create/update/upsert/delete con informe de resultados parciales | C | 0 | core | ✅ | — |
| `CRM-00.02.01.12` | API asíncrona para cargas largas: job ID, polling y callback | C | 0 | core | ✅ | — |
| `CRM-00.02.01.13` | Batch/composite requests (varias operaciones en una llamada, transaccionales o no) | A | 0 | core | ⬜ | — |
| `CRM-00.02.01.14` | Errores normalizados (RFC 9457 Problem Details) con código estable y correlación | C | 0 | core | ✅ | contecmind:app/core/errors.py + tests/unit/test_error_envelope_contract.py |
| `CRM-00.02.01.15` | Sandbox de API con datos sintéticos y consola interactiva | A | 0 | gateway | ⬜ | — |

#### CRM-00.02.02 · Eventos y notificaciones salientes

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-00.02.02.01` | Webhooks configurables por tenant, con filtros por tipo de evento y por condición | C | 0 | eventing | ✅ | contecweb:app/services/webhooks.py (528 líneas) + contecmind:app/services/webhooks.py |
| `CRM-00.02.02.02` | Firma HMAC, timestamp y protección anti-replay | C | 0 | eventing | ✅ | contecweb:app/services/webhooks.py (firma HMAC + anti-replay) |
| `CRM-00.02.02.03` | Reintentos con backoff exponencial, DLQ y reenvío manual desde consola | C | 0 | eventing | ✅ | contecmind:app/models/ingest_dlq.py + app/tasks/dlq_requeue.py |
| `CRM-00.02.02.04` | Garantía at-least-once + clave de deduplicación en el payload | C | 0 | core | ✅ | contecpos:packages/common/src/outbox.ts |
| `CRM-00.02.02.05` | Streaming de eventos (Kafka / Pub-Sub / Kinesis) con topic por tenant o partición | A | 0 | core | ✅ | contecpos:packages/common/src/bus.ts (NATS JetStream, subjects por tenant) |
| `CRM-00.02.02.06` | Change Data Capture del modelo de datos hacia el data lake del cliente | A | 5 | eventing | ⬜ | — |
| `CRM-00.02.02.07` | Catálogo de eventos documentado (AsyncAPI) con esquema versionado y registry | A | 0 | eventing | ✅ | — |
| `CRM-00.02.02.08` | Ordenación garantizada por clave de agregado (p. ej. por cuenta u oportunidad) | A | 0 | core | ⬜ | — |
| `CRM-00.02.02.09` | Replay de eventos históricos desde un punto en el tiempo | A | 0 | eventing | ✅ | — |
| `CRM-00.02.02.10` | Long-polling / SSE / WebSocket para clientes que no pueden exponer endpoint | A | 0 | gateway | ⬜ | contecweb:app/services/ws_manager.py + contecflow-PSA:app/services/ws_manager.py |

#### CRM-00.02.03 · Desacoplamiento de la presentación

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-00.02.03.01` | Cero lógica de negocio en la capa de UI; el backend es la única fuente de verdad | C | 0 | core | ✅ | — |
| `CRM-00.02.03.02` | UI de referencia sustituible y opcional (no requisito de licencia ni de despliegue) | A | 1 | core | ⬜ | — |
| `CRM-00.02.03.03` | Patrón BFF (Backend For Frontend) para web, móvil, portal y quiosco | A | 1 | gateway | ⬜ | — |
| `CRM-00.02.03.04` | SDKs mantenidos: JavaScript/TypeScript, Java, .NET, Python, PHP, Go | A | 1 | core | ⬜ | — |
| `CRM-00.02.03.05` | Componentes embebibles opcionales (web components) para incrustar en portales propios | A | 3 | core | ⬜ | — |
| `CRM-00.02.03.06` | Metadata-driven UI: la API expone layouts, campos, permisos y validaciones para que cualquier frontend renderice coherentemente | A | 0 | metadata | ⬜ | — |
| `CRM-00.02.03.07` | API de validación consultable antes de enviar (dry-run de reglas) | A | 0 | metadata | ⬜ | — |
| `CRM-00.02.03.08` | Server-driven UI: definición de formularios y vistas servida como JSON | D | 1 | metadata | ⬜ | — |
| `CRM-00.02.03.09` | Canales alternativos sin UI: e-mail-in, SMS, voz, chatbot, MCP/agentes, CLI | A | 3 | integration | ⬜ | — |
| `CRM-00.02.03.10` | Modo CRM invisible: el sistema opera embebido en ERP, portal o herramienta de terceros | D | 6 | gateway | ⬜ | — |

#### CRM-00.02.04 · Gateway y capa de acceso

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-00.02.04.01` | API Gateway con autenticación, autorización, rate limiting y enrutamiento por tenant | C | 0 | gateway | ✅ | — |
| `CRM-00.02.04.02` | Resolución de tenant por subdominio, cabecera, claim del token o clave de API | C | 0 | gateway | ✅ | contecmind:tenant_root_domain + X-Tenant-Slug (config_parts/_app.py) |
| `CRM-00.02.04.03` | mTLS para integraciones máquina-a-máquina críticas | A | 0 | gateway | ⬜ | — |
| `CRM-00.02.04.04` | IP allowlisting por tenant y por credencial | A | 0 | gateway | ⬜ | contecweb:app/services/security_rules.py |
| `CRM-00.02.04.05` | Cacheo configurable con invalidación por evento y aislamiento por tenant | A | 0 | gateway | ⬜ | contecmind:app/core/cache_registry.py |
| `CRM-00.02.04.06` | Portal de desarrollador por tenant: claves, scopes, logs de llamada, cuotas | A | 1 | gateway | ⬜ | contecflow-PSA:app/services/developer_portal_service.py + app/models/oauth_apps.py |
| `CRM-00.02.04.07` | Trazabilidad extremo a extremo: X-Request-Id / traceparent propagado y consultable | C | 0 | core | ✅ | contecmind:app/core/middleware.py (X-Request-Id) + tracing.py |

### 0.3 Orquestación de servicios y procesos

#### CRM-00.03.01 · Descomposición en servicios

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-00.03.01.01` | Servicios delimitados por capacidad de negocio (party, sales, service, marketing, billing-interface) | C | 0 | infra | ✅ | contecpos:services/* (14 servicios por capacidad) |
| `CRM-00.03.01.02` | Propiedad exclusiva de datos por servicio; prohibida la lectura directa de la BD ajena | C | 0 | infra | ✅ | contecpos:deploy/crear-bases.sh (una base y un rol por servicio) |
| `CRM-00.03.01.03` | Contratos internos versionados y verificados por contract testing (consumer-driven) | A | 0 | core | ⬜ | contecpos:packages/contracts (buf) |
| `CRM-00.03.01.04` | Service registry / catálogo interno con owner, SLO, dependencias y runbook | A | 0 | docs | ⬜ | — |
| `CRM-00.03.01.05` | Service mesh: mTLS, retries, timeouts, circuit breaking y canary a nivel de red | A | 2 | infra | ⬜ | — |
| `CRM-00.03.01.06` | Despliegue independiente por servicio, sin ventanas de release coordinadas | A | 0 | infra | ✅ | — |
| `CRM-00.03.01.07` | Strangler pattern soportado para convivir con CRM heredado durante la migración | A | 2 | integration | ⬜ | — |

#### CRM-00.03.02 · Motor de orquestación de procesos

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-00.03.02.01` | Motor de workflow persistente y duradero (reanuda tras caída, sin perder estado) | C | 0 | orchestrator | ✅ | contecmind:app/services/workflows.py + workflow_checkpoints.py + app/models/workflow_run.py |
| `CRM-00.03.02.02` | Modelado visual de procesos (BPMN 2.0 o equivalente) más definición como código | C | 1 | orchestrator | ⬜ | contecflow-PSA:app/models/bpmn_process.py + app/services/bpmn_process_service.py; contecmind:app/services/bpmn.py |
| `CRM-00.03.02.03` | Orquestación (saga orquestada con coordinador central) | A | 0 | orchestrator | ✅ | — |
| `CRM-00.03.02.04` | Coreografía por eventos para flujos de bajo acoplamiento | A | 0 | orchestrator | ✅ | contecpos:packages/common/src/bus.ts + outbox.ts |
| `CRM-00.03.02.05` | Compensaciones explícitas por paso (rollback semántico de sagas) | A | 0 | orchestrator | ✅ | — |
| `CRM-00.03.02.06` | Transactional outbox / inbox para consistencia entre BD y bus de eventos | C | 0 | core | ✅ | contecpos:packages/common/src/outbox.ts |
| `CRM-00.03.02.07` | Timers, esperas, fechas límite y escalados temporales dentro del proceso | C | 0 | orchestrator | ✅ | contecmind:app/tasks/_cron.py + app/core/scheduler.py |
| `CRM-00.03.02.08` | Sub-procesos, procesos reutilizables y llamadas entre procesos | A | 0 | orchestrator | ✅ | — |
| `CRM-00.03.02.09` | Tareas humanas: asignación, bandeja de tareas, reasignación, delegación, SLA | C | 0 | orchestrator | ✅ | contecmind:app/services/approval_engine/ (motor multi-etapa + SoD + SLA + delegación); contecweb:app/services/approvals/engine.py |
| `CRM-00.03.02.10` | Reglas de decisión declarativas (DMN / tablas de decisión) editables por negocio | C | 0 | orchestrator | ✅ | — |
| `CRM-00.03.02.11` | Instancias de proceso consultables: estado, historial, variables, punto de fallo | C | 0 | orchestrator | ✅ | — |
| `CRM-00.03.02.12` | Reintento, salto de paso y edición de variables en caliente por un administrador | A | 0 | orchestrator | ✅ | — |
| `CRM-00.03.02.13` | Migración de instancias en vuelo a una nueva versión del proceso | D | 2 | orchestrator | ⬜ | — |
| `CRM-00.03.02.14` | Simulación y pruebas de proceso con datos de ejemplo antes de publicar | A | 0 | orchestrator | ✅ | — |
| `CRM-00.03.02.15` | Multi-tenancy del motor: definiciones y aislamiento de ejecución por tenant | C | 0 | orchestrator | ✅ | — |
| `CRM-00.03.02.16` | Límites de recursión, bucles y ejecución para evitar procesos desbocados | C | 0 | orchestrator | ✅ | — |

#### CRM-00.03.03 · Automatización declarativa para negocio (low-code)

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-00.03.03.01` | Constructor de automatizaciones tipo cuando ocurre X, si Y, entonces Z | C | 0 | automation | ✅ | contecflow-PSA:app/models/automations.py + app/services/automations_service.py |
| `CRM-00.03.03.02` | Disparadores: creación, modificación de campo, eliminación, evento entrante, webhook, programado, manual | C | 0 | automation | ✅ | contecflow-PSA:app/services/automations_service.py (disparadores) |
| `CRM-00.03.03.03` | Acciones: crear/actualizar registro, notificar, llamar API externa, lanzar proceso, asignar, calcular | C | 0 | automation | ✅ | — |
| `CRM-00.03.03.04` | Ramificaciones, bucles sobre colecciones y variables de flujo | A | 0 | automation | ⬜ | — |
| `CRM-00.03.03.05` | Ejecución inmediata vs. diferida vs. programada | C | 0 | automation | ✅ | — |
| `CRM-00.03.03.06` | Gestión de orden de ejecución y prevención de bucles infinitos entre reglas | C | 0 | automation | ✅ | — |
| `CRM-00.03.03.07` | Depurador con ejecución paso a paso y log de decisiones por registro | A | 0 | automation | ✅ | — |
| `CRM-00.03.03.08` | Entorno de pruebas y despliegue de automatizaciones entre entornos | A | 0 | automation | ⬜ | — |
| `CRM-00.03.03.09` | Biblioteca de plantillas de automatización por industria | A | 1 | automation | ⬜ | — |

#### CRM-00.03.04 · Integración y conectividad

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-00.03.04.01` | Conectores nativos: ERP, facturación, firma electrónica, telefonía, mensajería | A | 2 | integration | ⬜ | contecflow-PSA:app/services/{salesforce,stripe,jira,git,m365,slack}_service.py; contecweb:app/services/supplier_api |
| `CRM-00.03.04.02` | Conector genérico HTTP/REST configurable sin código (auth, mapeo, paginación) | A | 0 | integration | ✅ | contecweb:app/connectors/api + base.py (conector HTTP genérico, verificado 2026-09-14) |
| `CRM-00.03.04.03` | Soporte SOAP, SFTP, ficheros planos, EDI y colas AMQP para entornos legacy | A | 2 | integration | ⬜ | — |
| `CRM-00.03.04.04` | Motor de transformación y mapeo de datos con funciones y validación | A | 0 | integration | ✅ | contecweb:app/services/normalization/ |
| `CRM-00.03.04.05` | Gestión de credenciales por conexión con rotación y prueba de conectividad | C | 0 | integration | ✅ | contecweb:app/services/credentials.py + contecflow-PSA:app/services/integration_credentials_service.py |
| `CRM-00.03.04.06` | Monitor de integraciones: ejecuciones, errores, reproceso, alertas | C | 0 | integration | ✅ | contecflow-PSA:app/services/integration_test_service.py |
| `CRM-00.03.04.07` | Cola de mensajes fallidos con corrección y reenvío asistido | C | 0 | integration | ✅ | contecmind:app/models/ingest_dlq.py + app/tasks/dlq_requeue.py |
| `CRM-00.03.04.08` | Sincronización bidireccional con resolución de conflictos configurable | A | 2 | integration | ⬜ | — |
| `CRM-00.03.04.09` | Modelo canónico de intercambio y adaptadores por sistema externo | A | 2 | integration | ⬜ | — |
| `CRM-00.03.04.10` | Marketplace / registro de integraciones instalables por tenant | A | 6 | integration | ⬜ | contecflow-PSA:app/models/marketplace.py + app/services/marketplace_service.py |
| `CRM-00.03.04.11` | Soporte MCP (Model Context Protocol) o equivalente para exposición a agentes de IA | D | 6 | integration | ⬜ | — |

#### CRM-00.03.05 · Workflows de negocio — aprobaciones, escalados y revisiones

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-00.03.05.01` | Editor gráfico de flujos: el lienzo de nodos y conexiones ES la definición, no un dibujo que la documenta | C | 1 | orchestrator | ⬜ | contecflow-PSA:app/models/workflow_designer.py (lienzo de nodos y versiones) |
| `CRM-00.03.05.02` | La misma definición como gráfico y como código (JSON/YAML), intercambiables sin pérdida ni segunda fuente de verdad | C | 1 | orchestrator | ⬜ | — |
| `CRM-00.03.05.03` | Validación antes de publicar: nodos inalcanzables, ciclos sin salida, ramas sin destino, tareas sin responsable posible | C | 1 | orchestrator | ⬜ | — |
| `CRM-00.03.05.04` | Simulación con datos reales antes de publicar: qué ruta seguiría, quién aprobaría y cuánto tardaría | C | 1 | orchestrator | ⬜ | contecflow-PSA:app/services/approval_engine/workflows.py (simulate_workflow) |
| `CRM-00.03.05.05` | Versionado con borrador, publicado y archivado; las instancias en vuelo terminan con su versión | C | 1 | orchestrator | ⬜ | — |
| `CRM-00.03.05.06` | Aprobaciones en cadena y en paralelo con quórum configurable: todos, mayoría, cualquiera, N de M | C | 2 | orchestrator | ⬜ | contecflow-PSA:app/services/approval_engine/requests.py (quórum y decisiones) |
| `CRM-00.03.05.07` | Resolución del aprobador por regla: jerarquía de mando, importe, unidad de negocio, rol o campo del registro | C | 2 | orchestrator | ⬜ | — |
| `CRM-00.03.05.08` | Delegación y sustitución por ausencia con vigencia, sin perder la traza de quién decidió de verdad | C | 2 | orchestrator | ⬜ | — |
| `CRM-00.03.05.09` | Escalado por tiempo, por inactividad y por jerarquía, con aviso antes de escalar y no solo después | C | 2 | orchestrator | ⬜ | contecflow-PSA:app/services/approval_engine/timeouts.py |
| `CRM-00.03.05.10` | Reaprobación automática cuando cambia lo aprobado: un descuento aprobado que sube vuelve a aprobación | C | 2 | orchestrator | ⬜ | — |
| `CRM-00.03.05.11` | Aprobación automática bajo umbral, registrada como tal: quién la habría tenido que dar y por qué no hizo falta | A | 2 | orchestrator | ⬜ | — |
| `CRM-00.03.05.12` | Decidir desde el correo o el móvil sin entrar al CRM, con enlace firmado de un solo uso y caducidad | C | 2 | orchestrator | ⬜ | — |
| `CRM-00.03.05.13` | Bandeja unificada de lo que me toca decidir, con el contexto suficiente para decidir sin abrir el registro | C | 2 | orchestrator | ⬜ | — |
| `CRM-00.03.05.14` | Vista de la instancia sobre el propio gráfico: por dónde va, qué queda y dónde falló | A | 2 | orchestrator | ⬜ | — |
| `CRM-00.03.05.15` | Plantillas de flujo por sector y caso de uso, clonables y modificables sin partir de cero | A | 2 | orchestrator | ⬜ | — |
| `CRM-00.03.05.16` | Analítica del flujo: dónde se atasca, cuánto tarda cada paso y quién es el cuello de botella | A | 2 | analytics | ⬜ | contecflow-PSA:app/services/approval_engine/analytics.py |

### 0.4 Extensibilidad y modelo de datos

#### CRM-00.04.01 · Modelo de datos configurable

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-00.04.01.01` | Objetos personalizados por tenant con ciclo de vida completo (CRUD, API, permisos, auditoría) | C | 0 | metadata | ✅ | — |
| `CRM-00.04.01.02` | Campos personalizados: texto, número, moneda, fecha, booleano, lista, lista múltiple, fórmula, lookup, geolocalización, JSON, fichero, cifrado | C | 0 | metadata | ✅ | contecweb:app/services/custom_fields.py (458 líneas) + contecflow-PSA:app/models/custom_fields.py |
| `CRM-00.04.01.03` | Relaciones: 1:1, 1:N, N:M, jerárquicas, polimórficas, maestro-detalle con cascada | C | 0 | metadata | ✅ | — |
| `CRM-00.04.01.04` | Campos calculados y rollups agregados sobre hijos | A | 1 | metadata | ⬜ | — |
| `CRM-00.04.01.05` | Registros de tipo (record types) con layouts y valores de lista distintos | A | 1 | metadata | ⬜ | contecflow-PSA:app/services/issue_type_service.py (tipos con layout propio) |
| `CRM-00.04.01.06` | Validaciones declarativas a nivel de campo, registro y transición de estado | C | 0 | metadata | ✅ | — |
| `CRM-00.04.01.07` | Máquinas de estado configurables por objeto | A | 0 | metadata | ✅ | — |
| `CRM-00.04.01.08` | Esquema expuesto vía API de metadatos (describe) para clientes headless | C | 0 | metadata | ✅ | — |
| `CRM-00.04.01.09` | Límites y gobierno del esquema (número de campos, índices, profundidad) con avisos | A | 0 | metadata | ⬜ | — |
| `CRM-00.04.01.10` | Migraciones de esquema seguras: añadir, renombrar, deprecar, backfill con progreso | A | 0 | metadata | ⬜ | — |

#### CRM-00.04.02 · Extensión por código

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-00.04.02.01` | Funciones serverless del tenant ejecutadas en sandbox aislado y con cuota | A | 6 | automation | ⬜ | — |
| `CRM-00.04.02.02` | Hooks pre/post sobre operaciones de dominio (before save, after commit) | A | 0 | core | ⬜ | — |
| `CRM-00.04.02.03` | Extensiones asíncronas suscritas a eventos, sin bloquear la transacción | A | 0 | core | ⬜ | — |
| `CRM-00.04.02.04` | Endpoints personalizados definidos por el tenant sobre el mismo gateway | D | 6 | gateway | ⬜ | — |
| `CRM-00.04.02.05` | Gestión de dependencias, versiones y rollback del código de extensión | A | 6 | automation | ⬜ | — |
| `CRM-00.04.02.06` | Observabilidad de extensiones: logs, métricas, errores y coste atribuido | A | 6 | automation | ⬜ | — |
| `CRM-00.04.02.07` | Firma y revisión de extensiones de terceros antes de su instalación | A | 6 | automation | ⬜ | — |

### 0.5 Identidad, seguridad y control de acceso

#### CRM-00.05.01 · Autenticación

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-00.05.01.01` | OAuth 2.1 / OIDC como mecanismo primario, con PKCE | C | 0 | identity | ✅ | contecmind:app/core/oidc.py + app/api/auth.py; contecweb:app/services/sso.py |
| `CRM-00.05.01.02` | SAML 2.0 para SSO empresarial | C | 0 | identity | ✅ | contecweb:app/services/saml.py + contecmind:app/services/saml.py |
| `CRM-00.05.01.03` | SSO por tenant con múltiples proveedores de identidad simultáneos | A | 0 | identity | ✅ | contecmind:app/services/oidc_mappings.py |
| `CRM-00.05.01.04` | Federación y Just-In-Time provisioning de usuarios | A | 0 | identity | ✅ | contecmind:app/services/oidc.py (JIT provisioning) |
| `CRM-00.05.01.05` | SCIM 2.0 para aprovisionamiento y desaprovisionamiento automático | A | 0 | identity | ⬜ | contecweb:app/services/scim.py (699 líneas) + contecflow-PSA:app/services/scim_service.py |
| `CRM-00.05.01.06` | MFA obligatoria configurable por rol, con TOTP, push, WebAuthn/passkeys | C | 0 | identity | ✅ | contecweb:app/services/mfa.py + contecmind:app/services/{mfa,webauthn}.py |
| `CRM-00.05.01.07` | Credenciales máquina: client credentials, service accounts, claves con scope y caducidad | C | 0 | identity | ✅ | contecflow-PSA:app/models/oauth_apps.py |
| `CRM-00.05.01.08` | Gestión de sesiones: duración, sesiones concurrentes, revocación remota | C | 0 | identity | ✅ | contecweb:app/services/sessions.py + contecflow-PSA:app/services/session_security.py |
| `CRM-00.05.01.09` | Políticas de acceso contextual: IP, dispositivo, geolocalización, horario | A | 0 | identity | ⬜ | contecweb:app/services/security_rules.py |
| `CRM-00.05.01.10` | Identidad de clientes externos (portal) separada de la de empleados (CIAM) | A | 3 | identity | ⬜ | contecweb:app/services/portal_session.py + contecflow-PSA:app/models/client_portal.py |

#### CRM-00.05.02 · Autorización

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-00.05.02.01` | RBAC con roles, perfiles y conjuntos de permisos acumulables | C | 0 | identity | ✅ | contecmind:app/services/acl.py + grc.py (matriz de permisos editable, roles custom) |
| `CRM-00.05.02.02` | Jerarquía de roles con visibilidad ascendente sobre subordinados | C | 0 | identity | ✅ | — |
| `CRM-00.05.02.03` | Permisos por objeto (CRUD) y por campo (lectura/escritura/oculto) | C | 0 | identity | ✅ | contecweb:app/services/abac.py (394) + abac_enforce.py |
| `CRM-00.05.02.04` | Reglas de compartición: por propietario, por equipo, por criterio, manual, temporal | C | 1 | identity | ✅ | contecweb:app/services/share_links.py (477 líneas) |
| `CRM-00.05.02.05` | ABAC: decisiones basadas en atributos de usuario, registro y contexto | A | 0 | identity | ✅ | contecweb:app/services/abac_policies.py (354) + contecflow-PSA:app/services/abac.py + abac_recursos.py |
| `CRM-00.05.02.06` | Motor de políticas externalizable (OPA/Cedar) evaluable también desde clientes headless | A | 0 | identity | ⬜ | — |
| `CRM-00.05.02.07` | Territorios y jerarquías de territorio que condicionan la visibilidad | A | 2 | identity | ⬜ | — |
| `CRM-00.05.02.08` | Restricción por unidad de negocio, marca, país o canal | A | 0 | identity | ⬜ | contecflow-PSA:app/services/organizations_service.py |
| `CRM-00.05.02.09` | Registros ocultos vs. registros bloqueados (visibles sin detalle) | A | 1 | identity | ⬜ | — |
| `CRM-00.05.02.10` | Acceso delegado temporal (suplantación) con consentimiento, caducidad y auditoría | A | 0 | identity | ✅ | contecweb:app/services/sesion_cedida.py (suplantación auditada) |
| `CRM-00.05.02.11` | Explicador de permisos: por qué este usuario ve este registro | D | 0 | identity | ✅ | contecmind:app/services/access_explainer.py + access_simulator.py |

#### CRM-00.05.03 · Protección del dato

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-00.05.03.01` | Cifrado en tránsito (TLS 1.3) y en reposo | C | 0 | infra | ✅ | contecmind:deploy/nginx + docs/PENTEST_HARDENING.md |
| `CRM-00.05.03.02` | Cifrado a nivel de campo para datos sensibles, con búsqueda determinista opcional | A | 0 | core | ✅ | contecmind:app/db/encrypted_text.py + app/core/crypto.py |
| `CRM-00.05.03.03` | Enmascaramiento y ofuscación por rol en respuestas de API y en exportaciones | A | 0 | core | ✅ | contecmind:app/services/pii.py + sensitive_policy.py |
| `CRM-00.05.03.04` | Tokenización de datos de pago o identificadores fiscales | A | 2 | core | ⬜ | — |
| `CRM-00.05.03.05` | Anonimización y pseudonimización para entornos no productivos | A | 0 | core | ⬜ | contecmind:app/services/pii.py |
| `CRM-00.05.03.06` | DLP: control de exportaciones masivas, alertas y bloqueo por política | A | 0 | core | ⬜ | contecweb:app/services/security_signals.py |
| `CRM-00.05.03.07` | Marca de agua e identificación de origen en exportaciones | D | 1 | core | ⬜ | contecflow-PSA:app/services/_pdf_marca.py (marca de agua) |
| `CRM-00.05.03.08` | Detección de comportamiento anómalo (descargas masivas, accesos fuera de patrón) | A | 0 | core | ⬜ | contecweb:app/services/security_signals.py + contecflow-PSA:app/services/security_observability.py |

#### CRM-00.05.04 · Auditoría y trazabilidad

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-00.05.04.01` | Audit trail inmutable de accesos, cambios, exportaciones y acciones administrativas | C | 0 | core | ✅ | contecmind:app/services/audit.py (668, hash-chain) + deploy/sql/audit_immutable.sql; contecweb:app/services/audit_chain.py |
| `CRM-00.05.04.02` | Historial de campo con valor anterior, valor nuevo, autor, origen (UI/API/automatización) y timestamp | C | 0 | core | ✅ | contecflow-PSA:app/models/task_movement_log.py (historial de campo) |
| `CRM-00.05.04.03` | Auditoría de cambios de configuración y de permisos | C | 0 | core | ✅ | contecflow-PSA:app/services/settings_audit_service.py |
| `CRM-00.05.04.04` | Retención configurable del log y exportación a SIEM | A | 0 | core | ⬜ | contecmind:scripts/audit_purge.py |
| `CRM-00.05.04.05` | Consulta y alertado sobre el audit trail desde la propia plataforma | A | 0 | core | ⬜ | contecmind:app/api/admin_audit.py |
| `CRM-00.05.04.06` | Event sourcing opcional en agregados críticos para reconstrucción de estado | D | 2 | core | ⬜ | — |

### 0.6 Observabilidad y operación

#### CRM-00.06.01 · Telemetría

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-00.06.01.01` | Logs estructurados con tenant_id, trace_id, user_id y correlación extremo a extremo | C | 0 | core | ✅ | contecmind:app/core/logging.py (structlog + redacción PII) |
| `CRM-00.06.01.02` | Métricas por tenant: latencia, throughput, tasa de error, saturación | C | 0 | core | ✅ | contecmind:app/core/metrics.py (577 líneas, Prometheus) |
| `CRM-00.06.01.03` | Trazas distribuidas (OpenTelemetry) a través de servicios y orquestaciones | A | 0 | core | ✅ | contecmind:app/core/tracing.py (OpenTelemetry) + contecpos:packages/common/src/otel.ts |
| `CRM-00.06.01.04` | SLO y error budget definidos por servicio y por tier de cliente | A | 0 | ops | ⬜ | contecmind:ops/prometheus/governance_alerts.yml |
| `CRM-00.06.01.05` | Alertado accionable con runbooks enlazados | C | 0 | ops | ✅ | contecmind:ops/alertmanager + app/services/alert_dispatch.py |
| `CRM-00.06.01.06` | Panel de salud visible por el propio tenant (status page privada) | A | 0 | tenancy | ✅ | contecmind:app/services/health_monitor.py + app/api/admin_health.py |
| `CRM-00.06.01.07` | Auditoría de rendimiento por consulta y detección de queries degradadas por tenant | A | 0 | core | ⬜ | contecmind:tests/unit/test_query_count_ratchet.py + contecflow-PSA:docs/INDEX_TUNING.md |

#### CRM-00.06.02 · Continuidad y resiliencia

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-00.06.02.01` | Backups automáticos con RPO y RTO comprometidos por tier | C | 0 | ops | ✅ | contecmind:scripts/backup.sh + restore.sh + deploy/systemd/*backup* |
| `CRM-00.06.02.02` | Point-in-time recovery a nivel de tenant, no solo de clúster | A | 0 | ops | ⬜ | — |
| `CRM-00.06.02.03` | Restauración selectiva de registros o de objetos concretos | A | 0 | ops | ⬜ | contecmind:app/api/admin_backup.py (restauración selectiva) |
| `CRM-00.06.02.04` | Papelera de reciclaje con retención y restauración en cascada de relaciones | C | 1 | core | ✅ | — |
| `CRM-00.06.02.05` | Alta disponibilidad multi-AZ y plan de recuperación multi-región | A | 0 | infra | ⬜ | — |
| `CRM-00.06.02.06` | Pruebas de DR periódicas documentadas | A | 0 | ops | ⬜ | contecmind:scripts/test_restore_integrity.sh |
| `CRM-00.06.02.07` | Modo degradado: lectura disponible aunque la escritura esté afectada | A | 0 | core | ⬜ | contecmind:app/core/degradation.py (270 líneas) |
| `CRM-00.06.02.08` | Despliegues sin downtime: blue/green, canary, rollback automático | A | 0 | infra | ⬜ | — |

## Módulo 1 — Núcleo de datos de cliente (Customer 360)

52 capacidades · 🔧 2 · ✅ 29 · ⬜ 21

### 1.1 Modelo de parties

#### CRM-01.01.01 · Cuentas / Empresas

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-01.01.01.01` | Ficha de cuenta con datos fiscales, comerciales, operativos y financieros | C | 1 | party | ✅ | contecflow-PSA:app/models/clients.py + app/services/client_service.py; contecweb:app/services/suppliers.py |
| `CRM-01.01.01.02` | Jerarquías de cuenta multinivel (grupo, matriz, filial, delegación, centro) | C | 1 | party | ✅ | contecflow-PSA:app/models/enterprise.py (jerarquía de organizaciones) |
| `CRM-01.01.01.03` | Jerarquías múltiples y simultáneas: legal, comercial, de facturación, de entrega | A | 1 | party | ✅ | — |
| `CRM-01.01.01.04` | Relaciones entre cuentas no jerárquicas (partner, competidor, proveedor, prescriptor) | A | 1 | party | ✅ | — |
| `CRM-01.01.01.05` | Múltiples direcciones tipificadas con validación y geocodificación | C | 1 | party | ✅ | — |
| `CRM-01.01.01.06` | Múltiples identificadores fiscales y validación contra registros oficiales (VIES) | A | 1 | party | ✅ | contecweb:app/services/prueba_de_identidad.py (validación contra registros) |
| `CRM-01.01.01.07` | Segmentación: sector (CNAE/SIC/NAICS), tamaño, facturación, tier, ABC, ciclo de vida | C | 1 | party | ✅ | — |
| `CRM-01.01.01.08` | Datos firmográficos enriquecidos desde proveedores externos | A | 4 | party | ⬜ | — |
| `CRM-01.01.01.09` | Cuentas personales (B2C) coexistiendo con el modelo B2B | A | 1 | party | ⬜ | contecpos:services/clientas (modelo B2C) |
| `CRM-01.01.01.10` | Equipo de cuenta con roles (owner, KAM, técnico, soporte, financiero) | C | 1 | party | ✅ | contecflow-PSA:app/services/raci_service.py (roles sobre entidad) |
| `CRM-01.01.01.11` | Plan de cuenta: objetivos, whitespace, mapa de poder, riesgos | A | 2 | party | ⬜ | — |
| `CRM-01.01.01.12` | Estado financiero embebido: riesgo, crédito disponible, deuda vencida, bloqueo | A | 2 | party | ⬜ | contecflow-PSA:app/services/{risk_scoring,profitability_service}.py |

#### CRM-01.01.02 · Contactos / Personas

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-01.01.02.01` | Ficha de contacto con múltiples canales (correo, teléfono, mensajería, redes) | C | 1 | party | ✅ | — |
| `CRM-01.01.02.02` | Relación N:M contacto–cuenta con rol, vigencia y contacto principal | A | 1 | party | ✅ | — |
| `CRM-01.01.02.03` | Mapa de relaciones e influencia entre contactos (reporting line, aliado, detractor) | A | 2 | party | ⬜ | — |
| `CRM-01.01.02.04` | Rol en el proceso de compra: decisor, prescriptor, usuario, económico, guardián | A | 2 | sales | ⬜ | — |
| `CRM-01.01.02.05` | Preferencias de contacto: canal, frecuencia, idioma, horario | C | 1 | party | ✅ | — |
| `CRM-01.01.02.06` | Consentimientos y bases legales por finalidad y canal | C | 1 | party | ✅ | contecweb:app/services/grc.py (bases legales) + contecmind:app/services/compliance.py |
| `CRM-01.01.02.07` | Detección de cambio de empresa y seguimiento del contacto a su nuevo puesto | D | 4 | party | ⬜ | — |
| `CRM-01.01.02.08` | Historial completo de interacciones unificado | C | 1 | party | ✅ | contecmind:app/services/timeline.py |

#### CRM-01.01.03 · Leads y captación

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-01.01.03.01` | Objeto lead con ciclo de vida propio y conversión a cuenta/contacto/oportunidad | C | 1 | sales | ✅ | — |
| `CRM-01.01.03.02` | Captura multicanal: formularios, web, importación, API, eventos, listas, chat | C | 1 | sales | 🔧 | contecflow-PSA:app/models/public_forms.py + app/services/public_forms_service.py |
| `CRM-01.01.03.03` | Deduplicación en el momento de la captura contra leads y contactos existentes | C | 1 | party | ✅ | — |
| `CRM-01.01.03.04` | Enrutamiento y asignación por reglas (territorio, producto, carga, skill, round-robin) | C | 1 | sales | ✅ | contecflow-PSA:app/services/service_desk/agent_group_service.py (enrutado por carga y skill) |
| `CRM-01.01.03.05` | Estados y motivos de descarte normalizados con reciclaje posterior | C | 1 | sales | ✅ | — |
| `CRM-01.01.03.06` | Trazabilidad de origen: campaña, canal, medio, término, contenido, first/last touch | C | 1 | sales | ✅ | — |
| `CRM-01.01.03.07` | SLA de primera respuesta con alertas y escalado | A | 1 | sales | ✅ | contecflow-PSA:app/services/sla_service.py |

#### CRM-01.01.04 · Calidad y gobierno del dato

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-01.01.04.01` | Detección de duplicados en tiempo real y por lotes, con reglas configurables | C | 1 | party | ✅ | — |
| `CRM-01.01.04.02` | Coincidencia difusa (fuzzy matching) con umbrales ajustables por objeto | A | 1 | party | ✅ | contecweb:app/services/normalization/ (coincidencia difusa) |
| `CRM-01.01.04.03` | Asistente de fusión con selección de campo superviviente y reparentado de relaciones | C | 1 | party | ✅ | — |
| `CRM-01.01.04.04` | Normalización automática (direcciones, teléfonos E.164, razón social, correo) | A | 1 | party | ✅ | contecweb:app/services/normalization/ |
| `CRM-01.01.04.05` | Reglas de completitud y puntuación de calidad por registro | A | 1 | party | ✅ | contecmind:app/services/quality_baseline.py + quality_sampler.py |
| `CRM-01.01.04.06` | Golden record / survivorship rules en escenarios multi-fuente | A | 2 | party | ⬜ | — |
| `CRM-01.01.04.07` | Linaje del dato: de qué sistema y en qué momento llegó cada valor | A | 2 | party | ⬜ | contecweb (linaje del dato por fuente) |
| `CRM-01.01.04.08` | Stewardship: cola de excepciones de calidad asignable a responsables | A | 2 | party | ⬜ | contecmind:app/services/gap_tasks.py (cola de excepciones asignable) |
| `CRM-01.01.04.09` | Enriquecimiento programado y detección de datos obsoletos | A | 4 | party | ⬜ | contecmind:app/services/freshness.py |
| `CRM-01.01.04.10` | Validación de correo, teléfono y dirección con estado de verificación | A | 1 | party | ✅ | — |

#### CRM-01.01.05 · Vista 360 e identidad

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-01.01.05.01` | Timeline unificado de todas las interacciones y transacciones | C | 1 | party | ✅ | contecmind:app/services/timeline.py |
| `CRM-01.01.05.02` | Resolución de identidad entre canales (correo, cookie, teléfono, ID de app, ID de ERP) | A | 4 | party | ⬜ | — |
| `CRM-01.01.05.03` | Perfil unificado consultable por API para uso en cualquier frontend o canal | C | 1 | party | ✅ | — |
| `CRM-01.01.05.04` | Composición de datos externos en la vista sin replicarlos (federación / virtualización) | A | 2 | integration | ⬜ | — |
| `CRM-01.01.05.05` | Resumen de cuenta generado por IA con puntos clave y riesgos | A | 5 | intelligence | ⬜ | contecmind:app/services/synthesis.py + holistic.py (resumen con citación) |
| `CRM-01.01.05.06` | Métricas embebidas: facturación, margen, pedidos, incidencias, NPS, morosidad | A | 2 | party | ⬜ | — |
| `CRM-01.01.05.07` | Salud del cliente (health score) y señales de churn | A | 5 | intelligence | ⬜ | contecflow-PSA:app/services/customer_health_service.py |

### 1.2 Actividades e interacciones

#### CRM-01.02.01 · Gestión de actividades

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-01.02.01.01` | Tareas, eventos, llamadas, notas y visitas con modelo común de actividad | C | 1 | party | ✅ | contecflow-PSA:app/models/activity.py + app/services/activity_service.py |
| `CRM-01.02.01.02` | Asignación, delegación, recordatorios y seguimiento de vencidas | C | 1 | party | 🔧 | — |
| `CRM-01.02.01.03` | Relación polimórfica de la actividad con cualquier objeto | C | 1 | party | ✅ | — |
| `CRM-01.02.01.04` | Registro automático de interacciones desde correo, teléfono y calendario | A | 2 | integration | ⬜ | contecmind:app/services/microsoft_drive.py + teams_* (M365); contecflow-PSA:app/services/m365_service.py |
| `CRM-01.02.01.05` | Transcripción y resumen automático de llamadas y reuniones | A | 5 | intelligence | ⬜ | contecmind:app/core/transcribe.py + app/services/audio_overview |
| `CRM-01.02.01.06` | Extracción de compromisos y próximos pasos desde la transcripción | D | 5 | intelligence | ⬜ | — |
| `CRM-01.02.01.07` | Plantillas de actividad y secuencias predefinidas por tipo de proceso | A | 2 | sales | ⬜ | — |
| `CRM-01.02.01.08` | Geolocalización y check-in de visita comercial | A | 2 | sales | ⬜ | — |

## Módulo 2 — Marketing

54 capacidades · ⬜ 54

### 2.1 Segmentación y audiencias

#### CRM-02.01.01 · Constructor de segmentos

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-02.01.01.01` | Segmentación por atributos, comportamiento, transacciones y eventos | C | 4 | marketing | ⬜ | contecweb:app/services/saved_searches.py (678, constructor de criterios) + contecflow-PSA:app/services/bi_query_builder_service.py |
| `CRM-02.01.01.02` | Condiciones anidadas con lógica booleana y operadores temporales | C | 4 | marketing | ⬜ | — |
| `CRM-02.01.01.03` | Segmentos dinámicos que se recalculan y estáticos congelados | C | 4 | marketing | ⬜ | — |
| `CRM-02.01.01.04` | Estimación de tamaño de audiencia en tiempo real antes de guardar | A | 4 | marketing | ⬜ | — |
| `CRM-02.01.01.05` | Segmentos consultables por API para activarlos en canales externos | A | 4 | marketing | ⬜ | — |
| `CRM-02.01.01.06` | Exclusiones, supresiones globales y listas negras | C | 4 | marketing | ⬜ | — |
| `CRM-02.01.01.07` | Solapamiento entre segmentos y análisis de canibalización | D | 4 | marketing | ⬜ | — |
| `CRM-02.01.01.08` | Segmentación predictiva por afinidad, propensión o valor esperado | A | 5 | intelligence | ⬜ | — |
| `CRM-02.01.01.09` | Sincronización de audiencias con plataformas publicitarias | A | 4 | marketing | ⬜ | — |

#### CRM-02.01.02 · Perfilado y scoring

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-02.01.02.01` | Lead scoring por reglas configurables (demográfico + comportamental) | C | 4 | marketing | ⬜ | contecflow-PSA:app/services/risk_scoring.py (motor de scoring por reglas) |
| `CRM-02.01.02.02` | Scoring predictivo entrenado con histórico de conversión | A | 5 | intelligence | ⬜ | contecflow-PSA:app/services/ml_trainer.py + ml_features.py |
| `CRM-02.01.02.03` | Grading de encaje con el ICP, independiente del engagement | A | 4 | marketing | ⬜ | — |
| `CRM-02.01.02.04` | Decaimiento temporal del score por inactividad | A | 4 | marketing | ⬜ | — |
| `CRM-02.01.02.05` | Umbrales que disparan MQL/SQL y traspaso automático a ventas | C | 4 | marketing | ⬜ | — |
| `CRM-02.01.02.06` | Explicabilidad del score: qué factores lo componen | A | 5 | intelligence | ⬜ | contecmind:app/services/confidence_audit.py (explicabilidad) |

### 2.2 Campañas y customer journeys

#### CRM-02.02.01 · Gestión de campañas

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-02.02.01.01` | Jerarquía de campañas (programa → campaña → táctica) con presupuesto y coste | C | 4 | marketing | ⬜ | contecflow-PSA:app/services/campaign_pdf.py + portfolio_service.py (jerarquía con presupuesto) |
| `CRM-02.02.01.02` | Objetivos, KPIs y comparativa de plan vs. real | A | 4 | marketing | ⬜ | contecflow-PSA:app/services/okr_service.py + budgets_service.py |
| `CRM-02.02.01.03` | Calendario de marketing compartido y gestión de solapamientos | A | 4 | marketing | ⬜ | — |
| `CRM-02.02.01.04` | Miembros de campaña con estados de progresión y fuente de alta | C | 4 | marketing | ⬜ | — |
| `CRM-02.02.01.05` | Cálculo de ROI, coste por lead, coste por oportunidad e influencia en pipeline | A | 4 | marketing | ⬜ | — |
| `CRM-02.02.01.06` | Modelos de atribución: first touch, last touch, lineal, en U, en W, por decaimiento, data-driven | A | 4 | marketing | ⬜ | — |
| `CRM-02.02.01.07` | Gestión de eventos y ferias: inscripciones, asistencia, seguimiento post-evento | A | 4 | marketing | ⬜ | contecflow-PSA:app/services/bookings_service.py (inscripciones y asistencia) |

#### CRM-02.02.02 · Journey builder / automatización de marketing

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-02.02.02.01` | Diseñador visual de recorridos con disparadores, esperas, ramas y objetivos | A | 4 | marketing | ⬜ | orchestrator (motor de procesos de la fase 0) |
| `CRM-02.02.02.02` | Entrada por evento, por segmento, por API o manual | A | 4 | marketing | ⬜ | — |
| `CRM-02.02.02.03` | Decisión por comportamiento (abrió, hizo clic, visitó, compró, no respondió) | A | 4 | marketing | ⬜ | — |
| `CRM-02.02.02.04` | Tests A/B y multivariante dentro del recorrido con selección automática de ganador | A | 4 | marketing | ⬜ | — |
| `CRM-02.02.02.05` | Optimización de hora y canal de envío por destinatario | A | 5 | intelligence | ⬜ | — |
| `CRM-02.02.02.06` | Reglas de fatiga y frecuencia máxima de contacto por persona | A | 4 | marketing | ⬜ | — |
| `CRM-02.02.02.07` | Salidas por conversión, por exclusión o por entrada en otro recorrido prioritario | A | 4 | marketing | ⬜ | — |
| `CRM-02.02.02.08` | Analítica por nodo del recorrido con embudo visual | A | 4 | marketing | ⬜ | — |
| `CRM-02.02.02.09` | Recorridos para B2B basados en cuenta (ABM) y no solo en persona | A | 4 | marketing | ⬜ | — |

### 2.3 Canales de ejecución

#### CRM-02.03.01 · Email marketing

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-02.03.01.01` | Editor de plantillas con bloques reutilizables y contenido dinámico | C | 4 | marketing | ⬜ | contecmind:app/services/email.py + plantillas; contecweb:app/services/email.py |
| `CRM-02.03.01.02` | Personalización con tokens, contenido condicional y recomendaciones | A | 4 | marketing | ⬜ | — |
| `CRM-02.03.01.03` | Gestión de entregabilidad: SPF, DKIM, DMARC, BIMI, IP dedicada, warm-up | A | 4 | marketing | ⬜ | — |
| `CRM-02.03.01.04` | Gestión de rebotes duros y blandos, quejas y bucles de retroalimentación | C | 4 | marketing | ⬜ | — |
| `CRM-02.03.01.05` | Preferencias de suscripción granulares y centro de preferencias alojable | C | 4 | marketing | ⬜ | — |
| `CRM-02.03.01.06` | Previsualización multi-cliente de correo y test de spam score | A | 4 | marketing | ⬜ | — |
| `CRM-02.03.01.07` | Envío transaccional separado del promocional, con dominios distintos | A | 4 | marketing | ⬜ | — |

#### CRM-02.03.02 · Otros canales

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-02.03.02.01` | SMS y RCS con gestión de consentimiento y palabras clave de baja | A | 4 | marketing | ⬜ | contecpos:services/notificaciones (SMS/WhatsApp) |
| `CRM-02.03.02.02` | WhatsApp Business: plantillas aprobadas, ventana de 24h, sesión y opt-in | A | 4 | marketing | ⬜ | contecpos:services/notificaciones + simuladores/sim-whatsapp |
| `CRM-02.03.02.03` | Notificaciones push web y móvil | A | 4 | marketing | ⬜ | contecmind:app/services/push.py + app/models/push_subscription.py |
| `CRM-02.03.02.04` | Publicidad digital: sincronización de audiencias y retargeting | A | 4 | marketing | ⬜ | — |
| `CRM-02.03.02.05` | Correo postal y telemarketing como pasos orquestados del recorrido | D | 4 | marketing | ⬜ | — |
| `CRM-02.03.02.06` | Landing pages y formularios alojados o embebidos, con pre-relleno para conocidos | A | 4 | marketing | ⬜ | contecflow-PSA:app/services/public_forms_service.py |
| `CRM-02.03.02.07` | Personalización web / contenido dinámico en el sitio del cliente vía API | D | 4 | marketing | ⬜ | — |

### 2.4 Contenido y gobierno

#### CRM-02.04.01 · Gestión de contenido

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-02.04.01.01` | Biblioteca de activos con metadatos, versiones y vigencia | A | 4 | marketing | ⬜ | contecmind:app/services/documents.py + doc_versions.py (versiones y vigencia) |
| `CRM-02.04.01.02` | Flujo de aprobación de contenidos y de campañas | A | 4 | marketing | ⬜ | contecmind:app/services/approval_engine/ |
| `CRM-02.04.01.03` | Cumplimiento por marca, país e idioma con plantillas bloqueadas | A | 4 | marketing | ⬜ | — |
| `CRM-02.04.01.04` | Generación de variantes de copy asistida por IA con revisión humana | A | 5 | intelligence | ⬜ | contecmind:app/services/transformations.py (generación con revisión humana) |

#### CRM-02.04.02 · Privacidad y consentimiento

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-02.04.02.01` | Registro de consentimiento con finalidad, canal, base legal, fecha y prueba | C | 4 | party | ⬜ | contecweb:app/services/grc.py + contecmind:app/services/compliance.py |
| `CRM-02.04.02.02` | Doble opt-in configurable y renovación periódica del consentimiento | A | 4 | marketing | ⬜ | — |
| `CRM-02.04.02.03` | Baja inmediata propagada a todos los canales y campañas en curso | C | 4 | marketing | ⬜ | — |
| `CRM-02.04.02.04` | Gestión de derechos ARCO/GDPR: acceso, rectificación, supresión, portabilidad, oposición | C | 4 | party | ⬜ | contecflow-PSA:app/services/bi_gdpr_service.py + contecmind:app/services/compliance.py |
| `CRM-02.04.02.05` | Bloqueo de tratamiento sin borrado (derecho de limitación) | A | 4 | party | ⬜ | contecmind:app/services/legal_hold.py |

## Módulo 3 — Ventas (SFA)

65 capacidades · ✅ 7 · ⬜ 58

### 3.1 Pipeline y oportunidades

#### CRM-03.01.01 · Gestión de oportunidades

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-03.01.01.01` | Oportunidad con importe, moneda, fecha de cierre, probabilidad y etapa | C | 1 | sales | ✅ | contecflow-PSA:app/models/pipeline.py (311) + app/services/pipeline_service.py |
| `CRM-03.01.01.02` | Múltiples pipelines por línea de negocio, producto, canal o región | C | 1 | sales | ✅ | contecflow-PSA:app/services/pipeline_stages_service.py |
| `CRM-03.01.01.03` | Etapas configurables con criterios de salida obligatorios y checklist | A | 1 | sales | ✅ | contecflow-PSA:app/services/pipeline_stages_service.py |
| `CRM-03.01.01.04` | Probabilidad por etapa, ajustable manualmente y por modelo predictivo | A | 2 | sales | ⬜ | — |
| `CRM-03.01.01.05` | Líneas de producto/servicio en la oportunidad con cantidad, precio y descuento | C | 1 | sales | ✅ | contecweb:app/services/catalog + contecpos:services/catalogo |
| `CRM-03.01.01.06` | Ingresos recurrentes vs. puntuales, con ARR/MRR, TCV y ACV calculados | A | 2 | sales | ⬜ | contecflow-PSA:app/services/revenue_service.py + app/models/revenue.py |
| `CRM-03.01.01.07` | Planificación de ingresos por periodos (revenue schedule) | A | 2 | sales | ⬜ | contecflow-PSA:app/services/revenue_service.py |
| `CRM-03.01.01.08` | Split de oportunidad entre varios comerciales (overlay, crédito, equipo) | A | 2 | sales | ⬜ | — |
| `CRM-03.01.01.09` | Competidores presentes, posicionamiento y motivo de pérdida estructurado | A | 1 | sales | ✅ | — |
| `CRM-03.01.01.10` | Buying group / mapa de decisión asociado a la oportunidad | A | 2 | sales | ⬜ | — |
| `CRM-03.01.01.11` | Oportunidades relacionadas: renovación, upsell, cross-sell, sustitución | A | 2 | sales | ⬜ | — |
| `CRM-03.01.01.12` | Antigüedad por etapa, estancamiento y alertas de inactividad | C | 1 | sales | ✅ | contecflow-PSA:app/models/task_movement_log.py (antigüedad por etapa) |
| `CRM-03.01.01.13` | Historial de cambios de importe y fecha (slippage tracking) | A | 2 | sales | ⬜ | — |
| `CRM-03.01.01.14` | Bloqueo de edición tras cierre y proceso de reapertura auditado | A | 1 | sales | ✅ | — |

#### CRM-03.01.02 · Metodologías de venta

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-03.01.02.01` | Soporte de metodologías configurables (MEDDIC, BANT, SPIN, Challenger, Value Selling) | A | 2 | sales | ⬜ | metadata (campos y scoring configurables de la fase 0) |
| `CRM-03.01.02.02` | Campos y scoring de metodología con indicador de calidad de la oportunidad | A | 2 | sales | ⬜ | — |
| `CRM-03.01.02.03` | Playbooks contextuales por etapa, segmento y tipo de deal | A | 2 | sales | ⬜ | — |
| `CRM-03.01.02.04` | Guía de próximos pasos recomendados con contenido asociado | A | 5 | intelligence | ⬜ | — |
| `CRM-03.01.02.05` | Mutual action plan / plan conjunto compartible con el cliente | D | 3 | sales | ⬜ | — |
| `CRM-03.01.02.06` | Revisión de deal (deal review) estructurada y trazable | A | 2 | sales | ⬜ | — |

### 3.2 Previsión y planificación comercial

#### CRM-03.02.01 · Forecasting

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-03.02.01.01` | Categorías de forecast (pipeline, best case, commit, closed) | C | 2 | sales | ⬜ | — |
| `CRM-03.02.01.02` | Previsión por jerarquía: comercial → equipo → región → compañía | C | 2 | sales | ⬜ | — |
| `CRM-03.02.01.03` | Ajustes de manager con trazabilidad del ajuste y su justificación | A | 2 | sales | ⬜ | — |
| `CRM-03.02.01.04` | Instantáneas periódicas (snapshots) y comparación entre periodos | A | 2 | sales | ⬜ | contecmind:app/services/graph_compare.py (instantáneas y comparación) |
| `CRM-03.02.01.05` | Waterfall de cambios del pipeline: entradas, salidas, deslizamientos, variación de importe | A | 2 | sales | ⬜ | — |
| `CRM-03.02.01.06` | Forecast predictivo con intervalo de confianza y comparación con el humano | A | 5 | intelligence | ⬜ | contecflow-PSA:app/services/bi_forecasting_service.py |
| `CRM-03.02.01.07` | Previsión multi-moneda con tipos de cambio históricos y dated exchange rates | A | 2 | sales | ⬜ | contecflow-PSA:app/services/exchange_rate_service.py + app/models/exchange_rates_log.py |
| `CRM-03.02.01.08` | Previsión por producto, por familia y por tipo de ingreso | A | 2 | sales | ⬜ | — |
| `CRM-03.02.01.09` | Bloqueo/cierre de periodo de forecast | A | 2 | sales | ⬜ | — |

#### CRM-03.02.02 · Territorios, cuotas y capacidad

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-03.02.02.01` | Modelo de territorios por geografía, sector, tamaño, producto o cuenta nominal | A | 2 | sales | ⬜ | — |
| `CRM-03.02.02.02` | Jerarquía de territorios con asignación automática y reglas de excepción | A | 2 | sales | ⬜ | — |
| `CRM-03.02.02.03` | Simulación y planificación de territorios antes de publicar | A | 2 | sales | ⬜ | contecflow-PSA:app/services/scenarios_service.py (simulación) |
| `CRM-03.02.02.04` | Cuotas por usuario, equipo, periodo, producto y métrica | A | 2 | sales | ⬜ | contecflow-PSA:app/services/okr_service.py |
| `CRM-03.02.02.05` | Prorrateo de cuota por altas y bajas de comerciales a mitad de periodo | A | 2 | sales | ⬜ | — |
| `CRM-03.02.02.06` | Seguimiento de consecución y ranking | A | 2 | sales | ⬜ | contecflow-PSA:app/services/performance_service.py |
| `CRM-03.02.02.07` | Planificación de capacidad y cobertura de pipeline vs. cuota | A | 2 | sales | ⬜ | contecflow-PSA:app/services/capacity_planning_service.py + capacity_service.py |

#### CRM-03.02.03 · Incentivos y comisiones (interfaz)

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-03.02.03.01` | Planes de comisión por porcentaje, escalado, acelerador y SPIFF | D | 2 | sales | ⬜ | — |
| `CRM-03.02.03.02` | Cálculo por periodo con simulación y previsión de comisión | D | 2 | sales | ⬜ | — |
| `CRM-03.02.03.03` | Aprobación, disputa y trazabilidad del pago | D | 2 | sales | ⬜ | contecmind:app/services/approval_engine/ (aprobación y disputa) |
| `CRM-03.02.03.04` | Integración con motor externo de compensación | A | 2 | integration | ⬜ | — |

### 3.3 Prospección y ejecución comercial

#### CRM-03.03.01 · Cadencias y engagement

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-03.03.01.01` | Secuencias multicanal (correo, llamada, LinkedIn, SMS, tarea manual) | A | 2 | sales | ⬜ | orchestrator + marketing (recorridos multicanal) |
| `CRM-03.03.01.02` | Cola de trabajo priorizada del comercial | A | 2 | sales | ⬜ | contecmind:app/services/task_dispatch.py (cola priorizada) |
| `CRM-03.03.01.03` | Plantillas de correo con seguimiento de apertura, clic y respuesta | A | 2 | sales | ⬜ | — |
| `CRM-03.03.01.04` | Detección de respuesta y salida automática de la secuencia | A | 2 | sales | ⬜ | — |
| `CRM-03.03.01.05` | Marcador integrado (click-to-call), grabación y registro automático | A | 3 | service | ⬜ | — |
| `CRM-03.03.01.06` | Analítica de plantillas y cadencias: tasa de respuesta y reunión generada | A | 2 | sales | ⬜ | — |
| `CRM-03.03.01.07` | Programación de reuniones con enlace de disponibilidad y round-robin | A | 2 | sales | ⬜ | contecflow-PSA:app/services/bookings_service.py + contecpos:services/agenda |

#### CRM-03.03.02 · Cotización y contratación

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-03.03.02.01` | Presupuestos con versiones, vigencia y estado | C | 2 | sales | ⬜ | contecflow-PSA:app/services/proposal_service.py; contecweb:app/services/rfq |
| `CRM-03.03.02.02` | Configuración de producto con reglas de compatibilidad y dependencias (CPQ) | A | 2 | sales | ⬜ | contecweb:app/services/bom (configuración con dependencias) |
| `CRM-03.03.02.03` | Motor de precios: listas por cliente, canal, volumen, moneda y vigencia | C | 2 | sales | ⬜ | contecpos:services/catalogo (listas de precios) + contecflow-PSA:app/services/rate_card_service.py |
| `CRM-03.03.02.04` | Descuentos con matriz de aprobación por umbral y margen mínimo | C | 2 | sales | ⬜ | contecmind:app/services/approval_engine/ (matriz de aprobación por umbral) |
| `CRM-03.03.02.05` | Cálculo de margen y rentabilidad en el propio presupuesto | A | 2 | sales | ⬜ | contecflow-PSA:app/services/profitability_service.py + cost_service.py |
| `CRM-03.03.02.06` | Generación documental (PDF) con plantillas por marca e idioma | C | 2 | sales | ⬜ | contecflow-PSA:app/services/{invoice_pdf,report_pdf,pdf_export_service}.py |
| `CRM-03.03.02.07` | Firma electrónica integrada con evidencia legal y estado | A | 2 | sales | ⬜ | contecflow-PSA:app/services/esign_service.py + esign_providers.py + signature_pdf.py |
| `CRM-03.03.02.08` | Contratos: alta, vigencia, renovación automática, preaviso, cláusulas, anexos | A | 2 | sales | ⬜ | contecweb:app/services/contracts.py (648) + contecflow-PSA:app/services/contract_service.py |
| `CRM-03.03.02.09` | Suscripciones: altas, bajas, cambios de plan, prorrateos, ciclos de facturación | A | 2 | sales | ⬜ | contecpos:services/identidad (suscripciones y planes) |
| `CRM-03.03.02.10` | Gestión de renovaciones con alertas y pipeline específico | A | 2 | sales | ⬜ | — |
| `CRM-03.03.02.11` | Traspaso de pedido a ERP con confirmación y conciliación de estado | C | 2 | integration | ⬜ | contecweb:app/services/purchase (traspaso a ERP) + contecflow-PSA:app/services/accounting_hub_service.py |
| `CRM-03.03.02.12` | Orquestación order-to-cash como saga con compensaciones | A | 2 | orchestrator | ⬜ | — |

### 3.4 Canal indirecto (PRM)

#### CRM-03.04.01 · Gestión de partners

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-03.04.01.01` | Registro y onboarding de partners con niveles y certificaciones | D | 6 | sales | ⬜ | contecweb:app/services/suppliers.py (alta y certificaciones) |
| `CRM-03.04.01.02` | Portal de partner headless: registro de oportunidades (deal registration) y protección | D | 6 | sales | ⬜ | contecweb:app/services/supplier_api + portal_session.py |
| `CRM-03.04.01.03` | Aislamiento de datos por partner dentro del tenant (visibilidad estanca) | A | 6 | identity | ⬜ | — |
| `CRM-03.04.01.04` | Fondos de marketing (MDF), solicitudes y justificación | D | 6 | marketing | ⬜ | contecflow-PSA:app/services/budgets_service.py |
| `CRM-03.04.01.05` | Precios y descuentos específicos de canal | A | 6 | sales | ⬜ | — |
| `CRM-03.04.01.06` | Rendimiento por partner, cuotas de canal y planes de negocio conjuntos | D | 6 | sales | ⬜ | — |

## Módulo 4 — Servicio y atención al cliente

62 capacidades · ⬜ 62

### 4.1 Gestión de casos

#### CRM-04.01.01 · Ciclo de vida del caso

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-04.01.01.01` | Caso con tipo, categoría, subcategoría, prioridad, severidad, origen y estado | C | 3 | service | ⬜ | contecflow-PSA:app/models/service_desk/tickets.py + app/services/service_desk/ |
| `CRM-04.01.01.02` | Taxonomía configurable con árboles de clasificación por línea de servicio | C | 3 | service | ⬜ | contecflow-PSA:app/models/service_desk/catalog.py + app/services/service_desk/catalog_service.py |
| `CRM-04.01.01.03` | Relación del caso con cuenta, contacto, producto, activo, pedido, contrato | C | 3 | service | ⬜ | contecflow-PSA:app/models/service_desk/cmdb.py + assets.py |
| `CRM-04.01.01.04` | Jerarquía de casos: padre-hijo, casos relacionados y duplicados | A | 3 | service | ⬜ | contecflow-PSA:app/models/service_desk/problems.py |
| `CRM-04.01.01.05` | Colas de trabajo, asignación automática y balanceo por carga y competencia | C | 3 | service | ⬜ | contecflow-PSA:app/services/service_desk/agent_group_service.py |
| `CRM-04.01.01.06` | Enrutamiento omnicanal con capacidad por agente y por canal | A | 3 | service | ⬜ | contecflow-PSA:app/services/service_desk/capacity_planning_service.py |
| `CRM-04.01.01.07` | Escalados automáticos por tiempo, severidad, cliente VIP o incumplimiento | C | 3 | service | ⬜ | contecflow-PSA:app/services/sla_service.py (escalados) |
| `CRM-04.01.01.08` | Casos internos, derivación a segundo/tercer nivel y a ingeniería | A | 3 | service | ⬜ | — |
| `CRM-04.01.01.09` | Motivos de cierre, resolución tipificada y validación de cierre por el cliente | C | 3 | service | ⬜ | — |
| `CRM-04.01.01.10` | Reapertura con ventana configurable y trazabilidad | A | 3 | service | ⬜ | — |
| `CRM-04.01.01.11` | Gestión de problemas e incidentes masivos (varios casos vinculados a una causa) | A | 3 | service | ⬜ | contecflow-PSA:app/models/service_desk/problems.py + app/services/service_desk/alert_correlation_service.py |
| `CRM-04.01.01.12` | Encuesta de satisfacción automática (CSAT/CES/NPS) tras el cierre | A | 3 | service | ⬜ | contecflow-PSA:app/services/nps_service.py + app/models/nps.py |

#### CRM-04.01.02 · SLA y derechos de servicio

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-04.01.02.01` | Entitlements por contrato, producto, cliente o plan | A | 3 | service | ⬜ | contecmind:app/services/entitlements.py |
| `CRM-04.01.02.02` | Definición de SLA por prioridad y por tipo de cliente | C | 3 | service | ⬜ | contecflow-PSA:app/models/service_desk/sla.py + app/services/sla_service.py |
| `CRM-04.01.02.03` | Relojes de primera respuesta, resolución y actualización periódica | C | 3 | service | ⬜ | contecflow-PSA:app/services/sla_service.py (relojes) |
| `CRM-04.01.02.04` | Calendarios laborales, festivos por país y pausas de reloj | A | 3 | service | ⬜ | contecpos:services/agenda (calendarios y festivos) |
| `CRM-04.01.02.05` | Alertas de riesgo de incumplimiento antes del vencimiento | C | 3 | service | ⬜ | — |
| `CRM-04.01.02.06` | Bolsas de horas, contadores de incidencias y consumo del entitlement | A | 3 | service | ⬜ | — |
| `CRM-04.01.02.07` | Informe de cumplimiento de SLA por periodo, cliente y equipo | C | 3 | service | ⬜ | contecflow-PSA:app/services/service_desk/analytics_service.py |
| `CRM-04.01.02.08` | Penalizaciones y créditos de servicio calculados | D | 3 | service | ⬜ | — |

### 4.2 Omnicanalidad

#### CRM-04.02.01 · Canales de entrada

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-04.02.01.01` | Email-to-case con threading, análisis de cabeceras y anti-bucle | C | 3 | service | ⬜ | contecmind:app/services/email.py + contecweb:app/services/email.py |
| `CRM-04.02.01.02` | Formulario web y portal de cliente | C | 3 | service | ⬜ | contecflow-PSA:app/models/client_portal.py + app/services/client_portal_service.py |
| `CRM-04.02.01.03` | Chat en vivo y co-browsing | A | 3 | service | ⬜ | contecflow-PSA:app/services/ws_manager.py + portal_conversation_service.py |
| `CRM-04.02.01.04` | WhatsApp, Messenger, Telegram y mensajería social | A | 3 | service | ⬜ | contecpos:services/notificaciones (WhatsApp) |
| `CRM-04.02.01.05` | Telefonía/CTI: screen pop, transferencia con contexto, IVR conectado | A | 3 | integration | ⬜ | — |
| `CRM-04.02.01.06` | Redes sociales: escucha, respuesta y conversión a caso | A | 4 | marketing | ⬜ | — |
| `CRM-04.02.01.07` | Canal de API para incrustar soporte en producto propio (in-app) | A | 3 | service | ⬜ | — |
| `CRM-04.02.01.08` | Voz y asistentes conversacionales | D | 5 | intelligence | ⬜ | contecmind:app/api/voice.py + app/core/transcribe.py |

#### CRM-04.02.02 · Experiencia unificada del agente

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-04.02.02.01` | Conversación unificada por cliente independientemente del canal | A | 3 | service | ⬜ | — |
| `CRM-04.02.02.02` | Transferencia de canal conservando el contexto | A | 3 | service | ⬜ | — |
| `CRM-04.02.02.03` | Presencia, estado y capacidad del agente | A | 3 | service | ⬜ | contecflow-PSA:app/services/service_desk/agent_group_service.py |
| `CRM-04.02.02.04` | Respuestas rápidas, macros y acciones compuestas | C | 3 | service | ⬜ | contecflow-PSA:app/services/service_desk/canned_response_service.py |
| `CRM-04.02.02.05` | Sugerencias de respuesta y de artículo generadas por IA | A | 5 | intelligence | ⬜ | contecflow-PSA:app/services/service_desk/ai_suggest_service.py; contecmind:app/services/rag.py |
| `CRM-04.02.02.06` | Resumen automático de la conversación al cerrar o al transferir | A | 5 | intelligence | ⬜ | contecmind:app/services/synthesis.py |
| `CRM-04.02.02.07` | Detección de sentimiento e intención en tiempo real | A | 5 | intelligence | ⬜ | contecflow-PSA:app/services/semantic_classifier.py |
| `CRM-04.02.02.08` | Consola embebible en cualquier frontend vía API/SDK (agente headless) | A | 3 | service | ⬜ | — |

### 4.3 Conocimiento y autoservicio

#### CRM-04.03.01 · Base de conocimiento

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-04.03.01.01` | Artículos con versiones, estados, vigencia y flujo de aprobación | C | 3 | service | ⬜ | contecmind:app/services/document_control.py (versiones + aprobación + publicación atómica) |
| `CRM-04.03.01.02` | Visibilidad por canal y por audiencia (interno, cliente, partner, público) | C | 3 | service | ⬜ | contecmind:app/services/acl.py + share_tokens.py |
| `CRM-04.03.01.03` | Multilingüe con gestión de traducciones y estado de sincronía | A | 3 | service | ⬜ | contecmind:app/services/languages.py + i18n_labels.py |
| `CRM-04.03.01.04` | Búsqueda semántica y sugerencia contextual en el caso | A | 5 | intelligence | ⬜ | contecmind:app/services/retrieval/ + search/ (búsqueda semántica híbrida) |
| `CRM-04.03.01.05` | Knowledge-Centered Service: crear artículo desde la resolución de un caso | A | 3 | service | ⬜ | contecmind:app/services/sop.py (artículo desde resolución) |
| `CRM-04.03.01.06` | Valoración, feedback y analítica de eficacia (deflexión, artículos huérfanos) | A | 3 | service | ⬜ | contecmind:app/services/quality_sampler.py + insights.py |
| `CRM-04.03.01.07` | API de conocimiento para alimentar portales, chatbots y agentes externos | A | 3 | service | ⬜ | — |

#### CRM-04.03.02 · Autoservicio

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-04.03.02.01` | Portal de cliente headless: casos, pedidos, facturas, activos, contratos | A | 3 | service | ⬜ | contecflow-PSA:app/models/client_portal.py (349) + app/services/client_portal_service.py |
| `CRM-04.03.02.02` | Chatbot/agente de IA con acceso al conocimiento y a acciones transaccionales | A | 5 | intelligence | ⬜ | contecflow-PSA:app/services/service_desk/ai_auto_resolution_service.py; contecmind:app/services/agent/ |
| `CRM-04.03.02.03` | Escalado a humano preservando el contexto completo | A | 3 | service | ⬜ | — |
| `CRM-04.03.02.04` | Comunidad, foros y preguntas frecuentes | D | 6 | service | ⬜ | — |
| `CRM-04.03.02.05` | Autenticación de clientes externos y permisos por contacto y por cuenta | A | 3 | identity | ⬜ | contecweb:app/services/portal_session.py |

### 4.4 Servicio de campo y activos

#### CRM-04.04.01 · Field service

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-04.04.01.01` | Órdenes de trabajo con líneas, materiales, tiempos y firma del cliente | D | 6 | service | ⬜ | contecflow-PSA:app/services/imputation_service.py + timesheet_service.py |
| `CRM-04.04.01.02` | Programación y optimización de rutas por competencia, zona y disponibilidad | D | 6 | service | ⬜ | contecflow-PSA:app/services/resource_analytics.py + skill_service.py |
| `CRM-04.04.01.03` | App móvil con modo offline y sincronización diferida | A | 6 | service | ⬜ | — |
| `CRM-04.04.01.04` | Gestión de repuestos, stock en furgoneta y consumos | D | 6 | service | ⬜ | contecpos:services/inventario |
| `CRM-04.04.01.05` | Mantenimiento preventivo planificado y recurrente | D | 6 | service | ⬜ | — |
| `CRM-04.04.01.06` | Partes de trabajo, fotos, checklists y evidencias | D | 6 | service | ⬜ | — |

#### CRM-04.04.02 · Activos y productos instalados

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-04.04.02.01` | Registro de activos instalados con número de serie, ubicación y estado | A | 6 | service | ⬜ | contecflow-PSA:app/models/service_desk/assets.py + cmdb.py |
| `CRM-04.04.02.02` | Jerarquía de activos y componentes | A | 6 | service | ⬜ | contecflow-PSA:app/models/cmdb.py (jerarquía de CIs) |
| `CRM-04.04.02.03` | Garantías, extensiones y cobertura | A | 6 | service | ⬜ | — |
| `CRM-04.04.02.04` | Historial de servicio por activo | A | 6 | service | ⬜ | — |
| `CRM-04.04.02.05` | Telemetría IoT: eventos de dispositivo que abren casos automáticamente | D | 6 | integration | ⬜ | — |

### 4.5 Postventa y logística inversa

#### CRM-04.05.01 · Devoluciones y reclamaciones

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-04.05.01.01` | RMA / devoluciones con autorización, motivo y disposición | D | 6 | service | ⬜ | contecpos:services/tpv (devoluciones y abonos) |
| `CRM-04.05.01.02` | Reparaciones, sustituciones y abonos | D | 6 | service | ⬜ | — |
| `CRM-04.05.01.03` | Reclamaciones formales y expedientes con plazos legales | D | 6 | service | ⬜ | contecweb:app/services/incidents.py (expedientes con plazos) |

## Módulo 5 — Analítica, inteligencia e IA

57 capacidades · ⬜ 57

### 5.1 Reporting y BI

#### CRM-05.01.01 · Motor de informes

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-05.01.01.01` | Constructor de informes por el usuario final, sin código | C | 2 | analytics | ⬜ | contecintelligence (RT-4: delegado, no se reimplementa) |
| `CRM-05.01.01.02` | Informes tabulares, agrupados, matriciales y de unión de fuentes | C | 2 | analytics | ⬜ | contecintelligence (RT-4: delegado, no se reimplementa) |
| `CRM-05.01.01.03` | Filtros dinámicos, filtros de ejecución y filtros cruzados | C | 2 | analytics | ⬜ | contecintelligence (RT-4: delegado, no se reimplementa) |
| `CRM-05.01.01.04` | Campos calculados, fórmulas de resumen y agrupaciones por periodo | A | 2 | analytics | ⬜ | contecintelligence (RT-4: delegado, no se reimplementa) |
| `CRM-05.01.01.05` | Informes históricos con instantáneas periódicas (trending) | A | 2 | analytics | ⬜ | contecintelligence (RT-4: delegado, no se reimplementa) |
| `CRM-05.01.01.06` | Programación y distribución automática por correo o a un destino externo | C | 2 | analytics | ⬜ | contecintelligence (RT-4: delegado, no se reimplementa) |
| `CRM-05.01.01.07` | Exportación a CSV, Excel y PDF con control de permisos y volumen | C | 2 | analytics | ⬜ | contecintelligence (RT-4: la consulta la resuelve él) + contecflow-PSA:app/services/bi_export_service.py (generación del fichero) |
| `CRM-05.01.01.08` | Seguridad del dato respetada en el informe (nunca expone más de lo permitido) | C | 2 | analytics | ⬜ | contecintelligence (RT-4: delegado, no se reimplementa) |
| `CRM-05.01.01.09` | API de informes para consumir resultados desde cualquier frontend | A | 2 | analytics | ⬜ | contecintelligence (RT-4: delegado, no se reimplementa) |

#### CRM-05.01.02 · Cuadros de mando

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-05.01.02.01` | Dashboards configurables por rol, equipo y usuario | C | 2 | analytics | ⬜ | contecintelligence (RT-4: delegado, no se reimplementa) |
| `CRM-05.01.02.02` | Componentes: KPI, tabla, gráfico, embudo, mapa, gauge, texto | C | 2 | analytics | ⬜ | contecintelligence (RT-4: delegado, no se reimplementa) |
| `CRM-05.01.02.03` | Filtros globales y drill-down hasta el registro | A | 2 | analytics | ⬜ | contecintelligence (RT-4: delegado, no se reimplementa) |
| `CRM-05.01.02.04` | Dashboards dinámicos que muestran los datos del usuario que los abre | A | 2 | analytics | ⬜ | contecintelligence (RT-4: delegado, no se reimplementa) |
| `CRM-05.01.02.05` | Suscripción, alertas por umbral y notificación de anomalías | A | 2 | analytics | ⬜ | contecintelligence (RT-4: delegado, no se reimplementa) |
| `CRM-05.01.02.06` | Embebido de dashboards en aplicaciones externas con SSO | A | 2 | analytics | ⬜ | contecintelligence (RT-4: delegado, no se reimplementa) |

#### CRM-05.01.04 · Explotación delegada en contecintelligence

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-05.01.04.01` | Canje en el servidor de la credencial de aplicación por un token de usuario final con tenant, sujeto, rol y alcances | C | 2 | analytics | ⬜ | contecintelligence:sdk (canje de credencial por token de usuario final) |
| `CRM-05.01.04.02` | Correspondencia entre cada tenant de contecrm y su organización en contecintelligence, creada al provisionar | C | 2 | analytics | ⬜ | contecintelligence:/api/admin/apps (mapeo de organizaciones) |
| `CRM-05.01.04.03` | Pantalla de explotación dentro de contecrm: se pregunta y se ven tablas y gráficos sin salir del CRM | C | 2 | analytics | ⬜ | — |
| `CRM-05.01.04.04` | Registro del CRM como fuente consultable, descrita en lenguaje natural y mantenida al día con el modelo | C | 2 | analytics | ⬜ | — |
| `CRM-05.01.04.05` | Propagacion de permisos y comparticion: la consulta analitica nunca devuelve mas de lo que el usuario ve en el CRM | C | 2 | analytics | ⬜ | — |
| `CRM-05.01.04.06` | Preguntas guardadas y publicadas como informe del tenant, con su programación y distribución desde el CRM | A | 2 | analytics | ⬜ | — |
| `CRM-05.01.04.07` | Auditoría de las consultas analíticas: quién preguntó qué, sobre qué datos y qué se le devolvió | A | 2 | analytics | ⬜ | — |
| `CRM-05.01.04.08` | Degradación explicada cuando contecintelligence no responde: el CRM sigue operativo y la explotación avisa | A | 2 | analytics | ⬜ | — |
| `CRM-05.01.04.10` | contecintelligence como dependencia de despliegue: la pila lo levanta, o se configura la dirección de uno ya en marcha | C | 2 | analytics | ⬜ | — |
| `CRM-05.01.04.11` | Comprobación al arrancar de que contecintelligence responde, con el fallo dicho ahí y no al abrir el primer informe | C | 2 | analytics | ⬜ | — |
| `CRM-05.01.04.12` | Salud de la integración visible: versión, latencia y último error, en el estado del propio CRM | A | 2 | analytics | ⬜ | — |
| `CRM-05.01.04.09` | Contexto del registro en curso: preguntar sobre la cuenta o la oportunidad abierta sin escribir el filtro | A | 5 | analytics | ⬜ | — |

#### CRM-05.01.03 · Analítica avanzada

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-05.01.03.01` | Almacén analítico separado del operacional (sin degradar el CRM) | A | 2 | analytics | ⬜ | contecflow-PSA:app/services/bi_etl_service.py + olap/ |
| `CRM-05.01.03.02` | Exportación continua a data warehouse del cliente (Snowflake, BigQuery, Databricks) | A | 5 | analytics | ⬜ | — |
| `CRM-05.01.03.03` | Modelo semántico documentado y métricas certificadas | A | 5 | analytics | ⬜ | contecweb (compilador de métricas con SQL verificable) |
| `CRM-05.01.03.04` | Análisis de cohortes, retención y ciclo de vida | A | 5 | analytics | ⬜ | — |
| `CRM-05.01.03.05` | Análisis de embudo multi-etapa con tiempos y tasas de conversión | A | 5 | analytics | ⬜ | — |
| `CRM-05.01.03.06` | Analítica de actividad comercial y correlación con resultados | A | 5 | analytics | ⬜ | — |
| `CRM-05.01.03.07` | Zero-copy / consulta federada contra el lake del cliente | D | 5 | analytics | ⬜ | — |

### 5.2 Inteligencia artificial

#### CRM-05.02.01 · Modelos predictivos

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-05.02.01.01` | Scoring de leads y de oportunidades con explicabilidad | A | 5 | intelligence | ⬜ | contecflow-PSA:app/services/ml_trainer.py + risk_scoring.py |
| `CRM-05.02.01.02` | Predicción de cierre, de importe y de fecha real | A | 5 | intelligence | ⬜ | contecflow-PSA:app/services/bi_forecasting_service.py |
| `CRM-05.02.01.03` | Propensión a compra, cross-sell y next best offer | A | 5 | intelligence | ⬜ | contecmind:app/services/recommendations.py |
| `CRM-05.02.01.04` | Predicción de churn y de riesgo de cuenta | A | 5 | intelligence | ⬜ | contecflow-PSA:app/services/customer_health_service.py |
| `CRM-05.02.01.05` | Detección de anomalías en pipeline, actividad y servicio | A | 5 | intelligence | ⬜ | contecflow-PSA:app/services/bi_anomaly_service.py; contecmind:app/services/drift.py |
| `CRM-05.02.01.06` | Reentrenamiento por tenant con datos propios y aislamiento del modelo | A | 5 | intelligence | ⬜ | contecflow-PSA:app/services/predictive_retraining_service.py |
| `CRM-05.02.01.07` | Gobierno de modelos: versión, métricas, drift, fecha de entrenamiento | A | 5 | intelligence | ⬜ | contecflow-PSA:app/models/ml_model.py + ai_governance.py; contecmind:app/services/evals.py + drift.py |

#### CRM-05.02.02 · IA generativa

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-05.02.02.01` | Redacción y reescritura de correos, propuestas y respuestas | A | 5 | intelligence | ⬜ | contecmind:app/services/transformations.py + prompts.py |
| `CRM-05.02.02.02` | Resumen de cuenta, de oportunidad, de caso y de hilo de conversación | A | 5 | intelligence | ⬜ | contecmind:app/services/synthesis.py + briefings.py |
| `CRM-05.02.02.03` | Respuesta sobre datos propios con RAG y citación de la fuente | A | 5 | intelligence | ⬜ | contecmind:app/services/rag.py + retrieval/ (RAG con citación de fuente) |
| `CRM-05.02.02.04` | Consulta en lenguaje natural sobre los datos del CRM | A | 5 | intelligence | ⬜ | contecflow-PSA:app/services/ask_the_data.py; contecmind:app/services/intent.py |
| `CRM-05.02.02.05` | Extracción estructurada desde correos, PDFs y transcripciones a campos del CRM | A | 5 | intelligence | ⬜ | contecmind:app/core/llm_json.py + app/services/metadata_enrichment.py |
| `CRM-05.02.02.06` | Traducción automática de contenidos e interacciones | A | 5 | intelligence | ⬜ | contecmind:app/services/languages.py |
| `CRM-05.02.02.07` | Guardrails: filtros de contenido, verificación de permisos antes de recuperar contexto | C | 5 | intelligence | ⬜ | contecmind:app/core/inference_gate.py + app/services/sensitive_policy.py |
| `CRM-05.02.02.08` | Trazabilidad de uso de IA: prompt, modelo, coste, usuario, registro afectado | A | 5 | intelligence | ⬜ | contecmind:app/services/metering.py (coste por tenant y modelo) |
| `CRM-05.02.02.09` | Opt-out de entrenamiento y garantía de no uso de datos del tenant | C | 5 | intelligence | ⬜ | contecmind:docs/COMPLIANCE.md (opt-out contractual) |
| `CRM-05.02.02.10` | Selección de modelo y región por tenant, incluido modelo propio del cliente | D | 5 | intelligence | ⬜ | contecmind:app/core/model_router.py + providers/ |

#### CRM-05.02.03 · Agentes autónomos

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-05.02.03.01` | Agentes que ejecutan procesos con herramientas definidas y permisos acotados | A | 5 | intelligence | ⬜ | contecmind:app/services/agent/ + orchestrator/ |
| `CRM-05.02.03.02` | Definición de herramientas a partir de las propias APIs del CRM | A | 5 | intelligence | ⬜ | — |
| `CRM-05.02.03.03` | Puntos de control humano (human-in-the-loop) por criticidad o importe | A | 5 | intelligence | ⬜ | contecmind:app/services/approval_engine/ (human-in-the-loop) |
| `CRM-05.02.03.04` | Límites de acción, presupuesto de tokens y kill switch por tenant | C | 5 | intelligence | ⬜ | contecmind:app/services/entitlements.py (presupuesto de tokens) + inference_gate.py |
| `CRM-05.02.03.05` | Auditoría completa de la actuación del agente y reversión de sus cambios | A | 5 | intelligence | ⬜ | contecflow-PSA:app/services/service_desk/autonomous_agent_service.py + ai_governance.py |
| `CRM-05.02.03.06` | Agente de calificación de leads, de respuesta de soporte y de actualización de datos | A | 5 | intelligence | ⬜ | — |

## Módulo 6 — Productividad y colaboración

12 capacidades · 🔧 1 · ✅ 2 · ⬜ 9

### 6.1 Integración con el puesto de trabajo

#### CRM-06.01.01 · Puesto de trabajo

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-06.01.01.01` | Sincronización bidireccional de correo y calendario (Microsoft 365, Google) | C | 2 | integration | ⬜ | contecmind:app/services/microsoft_drive.py + drive.py; contecflow-PSA:app/services/m365_service.py |
| `CRM-06.01.01.02` | Complemento en Outlook/Gmail para registrar y consultar sin salir del cliente de correo | A | 2 | integration | ⬜ | contecmind:extension/ (complemento de navegador) |
| `CRM-06.01.01.03` | Integración con Teams/Slack: notificaciones, consulta y acciones desde el chat | A | 2 | integration | ⬜ | contecmind:app/services/teams_bot/ + teams_*.py (10 módulos); contecflow-PSA:app/services/slack_service.py |
| `CRM-06.01.01.04` | Registro automático de reuniones y de asistentes | A | 2 | integration | ⬜ | — |
| `CRM-06.01.01.05` | Gestión documental: adjuntos, versiones, carpetas y enlace a SharePoint/Drive | C | 1 | core | 🔧 | contecmind:app/core/storage.py + app/services/documents.py; contecflow-PSA:app/services/s3_service.py |
| `CRM-06.01.01.06` | Generación documental desde plantillas (propuesta, contrato, acta) | A | 2 | core | ⬜ | contecmind:app/services/generated_documents.py + templates.py |

### 6.2 Colaboración y movilidad

#### CRM-06.02.01 · Colaboración

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-06.02.01.01` | Menciones, comentarios y hilos sobre registros | A | 1 | core | ✅ | contecmind:app/services/annotations.py + collaborative_corrections.py; contecflow-PSA:app/services/collaboration/ |
| `CRM-06.02.01.02` | Seguimiento de registros y notificaciones configurables por evento | C | 1 | core | ✅ | contecmind:app/services/notifications.py + app/models/notification.py |
| `CRM-06.02.01.03` | Aplicaciones móviles iOS y Android con notificaciones push | C | 3 | core | ⬜ | contecmind:app/services/push.py (web push) |
| `CRM-06.02.01.04` | Modo offline con cola de cambios y resolución de conflictos | A | 3 | core | ⬜ | — |
| `CRM-06.02.01.05` | Accesibilidad WCAG 2.2 AA en las interfaces suministradas | A | 1 | docs | ⬜ | contecflow-PSA:docs/A11Y_WCAG_AUDIT.md |
| `CRM-06.02.01.06` | Usuarios invitados externos con acceso acotado y temporal | A | 1 | identity | ⬜ | contecweb:app/services/share_links.py (acceso acotado y temporal) |

## Módulo 7 — Administración, ALM y gobierno

25 capacidades · 🔧 2 · ✅ 13 · ⬜ 10

### 7.1 Administración funcional

#### CRM-07.01.01 · Consola de administración

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-07.01.01.01` | Consola de administración completa, replicada al 100 % por API | C | 1 | core | 🔧 | contecmind:app/api/admin_*.py (52 routers, 244 rutas con gate de rol) |
| `CRM-07.01.01.02` | Gestión de usuarios, licencias, roles y desactivación con transferencia de propiedad | C | 1 | identity | ✅ | contecmind:app/services/users.py + app/api/admin_users.py |
| `CRM-07.01.01.03` | Valores de lista globales, taxonomías y catálogos maestros | C | 1 | metadata | ✅ | contecweb:app/services/custom_fields.py (valores de lista) |
| `CRM-07.01.01.04` | Plantillas de correo, de documento y de notificación | C | 1 | core | ✅ | contecmind:app/services/templates.py + email.py |
| `CRM-07.01.01.05` | Calendarios laborales, festivos y husos horarios | C | 1 | core | ✅ | contecpos:services/agenda (calendarios laborales) |
| `CRM-07.01.01.06` | Gestión de monedas, tipos de cambio y conversión histórica | A | 2 | core | ✅ | contecflow-PSA:app/services/exchange_rate_service.py + currency_rates_service.py + app/models/money.py |
| `CRM-07.01.01.07` | Duplicación y transferencia masiva de propiedad de registros | C | 1 | core | ✅ | — |
| `CRM-07.01.01.08` | Herramientas de importación/exportación masiva con validación previa y reversión | C | 1 | core | ✅ | contecmind:app/api/admin_ingest.py (importación con validación previa) |

### 7.2 Ciclo de vida de la aplicación (ALM)

#### CRM-07.02.01 · Entornos y despliegue

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-07.02.01.01` | Entornos separados: desarrollo, pruebas, UAT, producción | C | 0 | infra | ✅ | contecmind:setup.sh (perfiles dev/prodlike) + docker-compose.yml |
| `CRM-07.02.01.02` | Sandboxes con copia parcial o total de datos y anonimización opcional | A | 1 | tenancy | ⬜ | contecmind:app/services/pii.py (anonimización) |
| `CRM-07.02.01.03` | Empaquetado de cambios y despliegue promocionable entre entornos | A | 1 | metadata | ⬜ | contecmind:app/services/environment_profiles.py |
| `CRM-07.02.01.04` | Configuración como código con control de versiones (Git) y revisión | A | 1 | metadata | ⬜ | — |
| `CRM-07.02.01.05` | Pruebas automatizadas y gates de calidad para configuración y extensiones (aquí: gates locales, sin CI por decisión de proyecto) | A | 0 | infra | ✅ | contecmind:.pre-commit-config.yaml + scripts/preflight.py (gates locales, NO CI) |
| `CRM-07.02.01.06` | Detección de cambios en producción fuera del pipeline (drift) | A | 1 | metadata | ⬜ | — |
| `CRM-07.02.01.07` | Rollback de despliegues y de configuraciones | A | 1 | metadata | ⬜ | — |
| `CRM-07.02.01.08` | Gestión de releases del proveedor: ventanas, previsualización, pruebas de regresión | C | 0 | docs | ✅ | contecmind:CHANGELOG.md + tests/unit/test_changelog_frescura.py |
| `CRM-07.02.01.09` | Paquetes instalables por tenant y gestión de dependencias | A | 6 | metadata | ⬜ | contecflow-PSA:app/services/marketplace_service.py |

### 7.3 Gobierno y cumplimiento

#### CRM-07.03.01 · Gobierno del dato

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-07.03.01.01` | Políticas de retención y eliminación automática por tipo de dato | C | 0 | core | ✅ | contecmind:scripts/audit_purge.py + purge_old_conversations.py |
| `CRM-07.03.01.02` | Archivado de datos históricos con acceso consultable | A | 2 | core | ⬜ | — |
| `CRM-07.03.01.03` | Gestión de solicitudes de derechos del interesado, con flujo y plazos | C | 1 | party | 🔧 | contecflow-PSA:app/services/bi_gdpr_service.py |
| `CRM-07.03.01.04` | Registro de actividades de tratamiento (RAT) y mapa de datos personales | A | 1 | core | ⬜ | contecweb:app/services/grc.py (786) + contecmind:app/services/grc.py |
| `CRM-07.03.01.05` | Clasificación de datos por sensibilidad y etiquetado de campos | A | 0 | metadata | ✅ | contecmind:app/services/sensitive_policy.py (clasificación por sensibilidad) |
| `CRM-07.03.01.06` | Legal hold: bloqueo de eliminación por litigio | D | 1 | core | ✅ | contecmind:app/services/legal_hold.py + app/models/legal_hold.py |
| `CRM-07.03.01.07` | Informes de cumplimiento y evidencias para auditoría | A | 1 | core | ⬜ | contecmind:app/services/compliance.py + app/api/admin_compliance.py |
| `CRM-07.03.01.08` | Gestión de consentimiento de cookies y tracking cuando hay captación web | A | 4 | marketing | ⬜ | — |

## Módulo 8 — Requisitos no funcionales

12 capacidades · ✅ 8 · ⬜ 4

### 8.1 Rendimiento y escala

#### CRM-08.01.01 · Rendimiento

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-08.01.01.01` | Objetivos de latencia: p95 y p99 por tipo de operación, medidos por tenant | C | 0 | core | ✅ | contecmind:app/core/metrics.py (histogramas por endpoint y tenant) |
| `CRM-08.01.01.02` | Escalado horizontal independiente por servicio | A | 0 | infra | ⬜ | — |
| `CRM-08.01.01.03` | Volumetría soportada declarada: registros por objeto, usuarios concurrentes, eventos/s | C | 0 | docs | ✅ | — |
| `CRM-08.01.01.04` | Estrategia de particionado y archivado para objetos de alto volumen | A | 2 | core | ⬜ | contecmind:scripts/split_concurrent_indexes.py + contecflow-PSA:docs/INDEX_TUNING.md |
| `CRM-08.01.01.05` | Pruebas de carga reproducibles y publicadas | A | 0 | ops | ✅ | contecmind:scripts/load_test.py |
| `CRM-08.01.01.06` | Degradación controlada del servicio no crítico bajo pico | A | 0 | core | ⬜ | contecmind:app/core/degradation.py |

### 8.2 Compromisos de servicio

#### CRM-08.02.01 · Compromisos

| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |
|---|---|:-:|:-:|---|:-:|---|
| `CRM-08.02.01.01` | SLA de disponibilidad por tier con penalizaciones | C | 0 | docs | ✅ | — |
| `CRM-08.02.01.02` | RPO/RTO comprometidos y verificados | C | 0 | ops | ✅ | contecmind:scripts/test_restore_integrity.sh |
| `CRM-08.02.01.03` | Ventanas de mantenimiento anunciadas y, preferentemente, sin corte | C | 0 | infra | ✅ | — |
| `CRM-08.02.01.04` | Política de soporte: niveles, horarios, tiempos de respuesta y escalado | C | 0 | docs | ✅ | — |
| `CRM-08.02.01.05` | Portabilidad: exportación completa del tenant en formato abierto y documentado | C | 0 | tenancy | ✅ | contecmind:app/services/exports.py + app/api/exports.py |
| `CRM-08.02.01.06` | Reversibilidad y plan de salida contractual | A | 0 | docs | ⬜ | — |
