# Manual VI — Referencia de ajustes

> **Generado** por `python scripts/gen_referencia_ajustes.py` desde los
> propios `Settings`. No se edita a mano: la explicación de cada ajuste
> vive junto a su campo en `packages/crmcore/crmcore/config_parts/`.

Cada ajuste se configura como **variable de entorno** (en `.env` o en el
entorno del proceso). Los marcados con 🔥 se pueden cambiar además
**en caliente por tenant** desde la consola de administración, sin
reiniciar: ahí el valor de `.env` es solo el punto de partida.

**180 ajustes** en total, de los cuales **60** son editables en caliente por tenant.

## Identidad del servicio y red

| Variable de entorno | Clave en caliente | Defecto | Rango | Qué hace |
|---|---|---|---|---|
| `SERVICE_NAME` | — | *(vacío)* |  | Cada proceso declara qué servicio es. Lo usan los logs, las métricas (etiqueta `service`), el bus (nombre del consumidor durable), el esquema de base de datos que le toca y el registro de servicios. No tiene default útil a propósito: un proceso que no sabe qué servicio es produce telemetría… |
| `SERVICE_VERSION` | — | `0.1.0` |  |  |
| `ENV` | — | `prod` |  | Entorno de ejecución (CRM-07.02.01.01: desarrollo, pruebas, UAT y producción son despliegues separados, distinguidos por este valor). "prod" por defecto para que un despliegue que se olvide de poner ENV pase por la verificación estricta de secretos en vez de saltársela (el error seguro es fallar… |
| `APP_NAME` | — | `contecrm` |  | Nombre del producto en textos visibles (correos, cabeceras, títulos de OpenAPI). Configurable porque la marca blanca (CRM-00.01.04.06) lo cambia. |
| `SERVICE_HOST` | — | `127.0.0.1` |  | Puerto en el que escucha este servicio. Lo leen uvicorn (arranque), el healthcheck de compose y el gateway (enrutado). Boot-only: cambiarlo en caliente no reabre el socket. |
| `SERVICE_PORT` | — | `8000` | 1–65535 |  |
| `RUTAS_SERVICIOS` | — | *(vacío)* |  | Los servicios DE ESTE DESPLIEGUE, como `nombre=url` separados por comas: `tenancy=http://tenancy:8000,party=http://party:8000`. Lo lee el gateway para enrutar —un servicio que no esté aquí no es alcanzable y responde 503 diciendo cuál falta, que es mejor que un 404 genérico— y lo lee `tenancy`… |
| `PUBLIC_BASE_URL` | — | `http://localhost:8080` |  | URL base pública del sistema, usada para componer enlaces absolutos (callbacks de OAuth, enlaces de correo, URLs firmadas). Sin esto los enlaces salen relativos y rotos en el correo. |
| `CORS_ORIGINS` | — | *(vacío)* |  | Lista separada por comas. Vacío = ningún origen de navegador permitido, que es lo correcto para un servicio interno: solo el gateway habla con él. |
| `API_PREFIX` | — | `/api/v1` |  | Prefijo de versión de la API pública. El versionado es explícito y por URI (CRM-00.02.01.05): un cambio rompedor estrena `v2` y `v1` sigue sirviéndose hasta su fecha de retirada. |
| `API_SUNSET_DATE` | — | *(vacío)* |  | Fecha de retirada de ESTA versión mayor, en ISO-8601, o vacío si no hay una anunciada. Cuando está puesta, toda respuesta lleva las cabeceras `Sunset` y `Deprecation` (CRM-00.02.01.07) para que los consumidores se enteren por el canal que ya están leyendo, sin depender de una circular. |
| `API_DOCS_ENABLED` | — | `True` |  | Documentación interactiva. Se puede apagar en producción si el operador prefiere no publicar el esquema, aunque por defecto va encendida: un sistema headless sin documentación navegable es mucho peor que uno que enseña su contrato. |

## Base de datos y aislamiento

| Variable de entorno | Clave en caliente | Defecto | Rango | Qué hace |
|---|---|---|---|---|
| `DATABASE_URL` | — | `postgresql+psycopg://contecrm:contecrm_dev_only@localhost:5432/contecrm` |  | Un servicio se conecta SIEMPRE con un rol propio, sin permisos sobre los esquemas de los demás (CRM-00.03.01.02). `deploy/crear-bases.sh` crea un rol y un esquema por servicio; esta URL apunta al suyo. El default es el de desarrollo local que levanta `docker-compose.yml`. En producción viene del… |
| `DATABASE_ADMIN_URL` | — | *(vacío)* |  | URL con el rol administrador, usada SOLO por las migraciones. Separarlas es lo que permite que el rol de la aplicación no tenga DDL: si el proceso que atiende peticiones no puede crear ni alterar tablas, una inyección no puede alterarlas tampoco. |
| `DB_SCHEMA` | — | *(vacío)* |  | Esquema propio del servicio. Vacío = se deriva de `service_name`. Explicitarlo sirve para los servicios que comparten esquema en un despliegue pequeño (un solo proceso, varios dominios). |
| `DB_POOL_SIZE` | — | `10` | 1–200 | El total de conexiones simultáneas por proceso es `pool_size + overflow`. Defaults conservadores para un servicio de API: la mayoría de peticiones retienen la conexión milisegundos. Un servicio con trabajos largos (importaciones, orquestador) sube estos valores en su `.env`. |
| `DB_MAX_OVERFLOW` | — | `10` | 0–200 |  |
| `DB_POOL_TIMEOUT_S` | — | `30` | 1–300 |  |
| `DB_POOL_RECYCLE_S` | — | `1800` | 60–86400 | Recicla conexiones antes de que un proxy o el propio Postgres las cierre por inactividad; media hora va por debajo de los timeouts habituales. |
| `DB_CONNECT_TIMEOUT_S` | — | `5` | 1–60 | Fallar rápido si Postgres no responde, en vez de bloquear el worker el tiempo por defecto del TCP del sistema (75 s o más). Un worker colgado es lo que convierte una base caída en un sistema que "se queda pensando". |
| `RLS_ENABLED` | — | `True` |  | Row-Level Security activa. Es la garantía dura de CRM-00.01.02.01: aunque una consulta olvide el filtro de tenant, el motor no devuelve filas ajenas. Va a `true` por defecto, al revés que en contecmind, donde nació apagada para no cambiar el comportamiento de un sistema ya en producción. Aquí no… |
| `TENANT_GUARD_ENABLED` | — | `True` |  | Guard de tenant en la capa ORM: segunda red, independiente de RLS, que inyecta el filtro de tenant en todo SELECT/UPDATE/DELETE de un modelo con `tenant_id`. Se puede apagar para una consulta administrativa legítima, pero apagarlo globalmente en producción deja el sistema con una sola red. |
| `DB_MIGRATE_ON_BOOT` | — | `False` |  | Aplicar migraciones al arrancar. En desarrollo es cómodo; en producción se deja en false y las aplica un paso aparte, para que dos réplicas no migren a la vez (mismo criterio que contecpos). |

## Multi-tenancy, cuotas y residencia

| Variable de entorno | Clave en caliente | Defecto | Rango | Qué hace |
|---|---|---|---|---|
| `TENANT_ROOT_DOMAIN` | — | *(vacío)* |  | Cuatro vías, por orden de confianza: el claim del token > la clave de API > la cabecera explícita > el subdominio. Las dos primeras están firmadas; las dos últimas son PISTAS de enrutado y nunca bastan por sí solas para conceder acceso. Esa distinción es la que evita que baste con cambiar una… |
| `TENANT_HEADER` | — | `X-Tenant` |  | Nombre de la cabecera que lleva el slug del tenant. Configurable porque un despliegue detrás de un proxy corporativo puede necesitar otra. |
| `TENANT_DEFAULT_ISOLATION` | — | `pool` |  | pool   = esquema compartido con discriminador (CRM-00.01.01.01) schema = un esquema por tenant                (CRM-00.01.01.02) silo   = base o clúster dedicado              (CRM-00.01.01.03) El modelo híbrido por tiers (CRM-00.01.01.04) sale de que este valor sea una propiedad DEL TENANT, no… |
| `TENANT_DEFAULT_REGION` | — | `eu` |  | Región por defecto para el pinning de datos (CRM-00.01.05.01). El valor no significa nada por sí mismo: lo interpreta el despliegue. Se guarda en el tenant para poder auditar dónde vive cada dato. |
| `QUOTA_API_CALLS_POR_MINUTO` | 🔥 `quota_api_calls_por_minuto` | `1000` | 0–10000000 | Son los topes con los que nace un tenant sin plan asignado. El plan los sobrescribe, y el operador puede subirlos por tenant desde Admin. Cero = sin límite, que es lo razonable para un despliegue on-premise de un solo cliente donde las cuotas solo estorban. |
| `QUOTA_REGISTROS` | 🔥 `quota_registros` | `0` | ≥ 0 |  |
| `QUOTA_ALMACENAMIENTO_MB` | 🔥 `quota_almacenamiento_mb` | `0` | ≥ 0 |  |
| `QUOTA_CORREOS_POR_DIA` | 🔥 `quota_correos_por_dia` | `0` | ≥ 0 |  |
| `QUOTA_WORKFLOWS_CONCURRENTES` | 🔥 `quota_workflows_concurrentes` | `100` | 0–1000000 |  |
| `QUOTA_TOKENS_IA_POR_DIA` | 🔥 `quota_tokens_ia_por_dia` | `0` | ≥ 0 |  |
| `LICENCIAS_MAXIMAS` | — | `0` | 0–1000000 | Usuarios activos que admite el plan. 0 = sin límite, que es lo razonable en un despliegue on-premise de un solo cliente. |
| `QUOTA_AVISO_PCT` | 🔥 `quota_aviso_pct` | `80` | 1–100 | Porcentaje de consumo a partir del cual se avisa al tenant de que se acerca al límite (CRM-00.01.06.06). Avisar al 100 % es avisar tarde. |
| `ONBOARDING_ENABLED` | — | `False` |  | Alta autoservicio. Apagada por defecto: un despliegue empresarial da de alta a sus tenants por API o por consola, y dejar abierto el alta pública en una instalación privada es una superficie regalada. |

## Bus de eventos, outbox y webhooks

| Variable de entorno | Clave en caliente | Defecto | Rango | Qué hace |
|---|---|---|---|---|
| `BUS_BACKEND` | — | `nats` |  | nats     JetStream: persistencia, consumidores durables, replay y reparto entre réplicas. Es el de producción. redis    Redis Streams: sirve donde ya hay Redis y no se quiere una pieza más; con grupos de consumidores da reparto y reintento. memoria  En proceso, sin red. SOLO pruebas: productor y… |
| `NATS_URL` | — | `nats://localhost:4222` |  |  |
| `REDIS_URL` | — | `redis://localhost:6379/0` |  |  |
| `BUS_PREFIX` | — | `contecrm` |  | Prefijo de todos los subjects. Aísla despliegues que compartan broker (un NATS común para pre-producción y demo, por ejemplo). |
| `OUTBOX_ENABLED` | — | `True` |  | El evento se escribe en la MISMA transacción que el cambio que lo provoca, y un relevo lo publica después. Es lo que impide el estado imposible: oportunidad ganada en la base y nadie enterado en el bus. El precio es entrega at-least-once —un evento puede publicarse dos veces si el proceso muere… |
| `OUTBOX_LOTE` | — | `100` | 1–10000 | Cuántos eventos publica el relevo por vuelta. Lotes grandes reducen viajes pero alargan el bloqueo de las filas tomadas. |
| `OUTBOX_INTERVALO_S` | — | `1.0` | 0.05–60.0 | Cada cuánto vuelve a mirar si hay pendientes cuando la última vuelta salió vacía. Con eventos esperando publica de seguido, sin esperar. |
| `OUTBOX_MAX_INTENTOS` | — | `8` | 1–100 | Intentos antes de mandar el evento a la cola de fallidos. Con backoff exponencial, 8 intentos cubren varios minutos de caída del broker. |
| `OUTBOX_BACKOFF_BASE_S` | — | `2.0` | 0.1–300.0 | Base del backoff exponencial entre intentos, en segundos. |
| `INBOX_ENABLED` | — | `True` |  | Registro de `dedup_key` ya procesadas. Es lo que convierte la entrega at-least-once en efecto exactly-once desde fuera. |
| `INBOX_RETENCION_DIAS` | — | `7` | 1–365 | Cuánto se recuerda una clave. Debe cubrir de sobra la ventana de reintentos del productor; una semana la cubre con holgura. |
| `WEBHOOKS_ENABLED` | 🔥 `webhooks_enabled` | `True` |  |  |
| `WEBHOOK_TIMEOUT_S` | 🔥 `webhook_timeout_s` | `10.0` | 0.5–120.0 |  |
| `WEBHOOK_MAX_INTENTOS` | 🔥 `webhook_max_intentos` | `6` | 1–50 |  |
| `WEBHOOK_BACKOFF_BASE_S` | — | `5.0` | 0.5–600.0 |  |
| `WEBHOOK_FIRMA_VENTANA_S` | — | `300` | 30–3600 | Ventana en la que se acepta la firma de una petición entrante, para que un mensaje capturado no se pueda reenviar más tarde (anti-replay). |
| `WEBHOOK_MAX_PAYLOAD_KB` | — | `256` | 1–10240 | Tamaño máximo del cuerpo que se entrega. Un payload gigante es casi siempre un error de diseño y además revienta al receptor. |
| `OUTBOX_ORDEN_POR_AGREGADO` | — | `True` |  | Un solo evento por agregado en cada vuelta del relevo. Sin esto, un evento que falla y se reintenta con espera deja salir antes al siguiente del mismo registro: quien lo consuma vería «actualizada» antes que «creada». El coste es que un registro muy activo avanza a un evento por vuelta. Se paga… |

## Identidad: tokens, sesiones, MFA

| Variable de entorno | Clave en caliente | Defecto | Rango | Qué hace |
|---|---|---|---|---|
| `SECRET_KEY` | — | *(secreto)* |  | Firma TODOS los tokens de acceso y refresco. Si en producción sigue valiendo el placeholder, cualquiera puede emitirse un token de administrador: el arranque lo comprueba y se niega a levantar. |
| `JWT_ALGORITHM` | — | `HS256` |  |  |
| `ACCESS_TOKEN_MINUTOS` | — | `15` | 1–1440 | Duración del token de acceso. Corta a propósito: la revocación de una sesión no puede invalidar un JWT ya emitido, así que el tiempo de vida ES la ventana de exposición. 15 minutos es el equilibrio habitual entre eso y no renovar constantemente. |
| `REFRESH_TOKEN_DIAS` | — | `14` | 1–365 | El refresco sí es revocable (está en base de datos), por eso puede durar. |
| `SESIONES_MAX_POR_USUARIO` | 🔥 `sesiones_max_por_usuario` | `0` | 0–1000 | Sesiones simultáneas por usuario. 0 = sin límite. Ponerlo a 1 es lo que exigen algunos clientes regulados. |
| `SESION_INACTIVIDAD_MINUTOS` | 🔥 `sesion_inactividad_minutos` | `480` | 5–10080 | Caducidad por inactividad, además de la absoluta del refresco. |
| `LOGIN_MAX_INTENTOS` | 🔥 `login_max_intentos` | `5` | 1–100 |  |
| `LOGIN_BLOQUEO_MINUTOS` | — | `15` | 1–1440 |  |
| `MFA_ENABLED` | — | `True` |  |  |
| `MFA_OBLIGATORIA` | 🔥 `mfa_obligatoria` | `False` |  | Exigir MFA a todo el mundo. Lo normal es exigirla por rol (se configura por tenant); esto es el interruptor global para instalaciones que la quieren obligatoria sin excepciones. |
| `TOTP_VENTANA_PASOS` | — | `1` | 0–10 | Ventana de códigos TOTP aceptados hacia atrás y adelante, para absorber relojes desajustados. Cada paso son 30 s; 1 = ±30 s. |
| `OIDC_ENABLED` | — | `False` |  |  |
| `SAML_ENABLED` | — | `False` |  |  |
| `SCIM_ENABLED` | — | `False` |  |  |
| `JIT_PROVISIONING` | — | `True` |  | Crear el usuario la primera vez que entra por el proveedor de identidad. Cómodo y estándar, pero significa que quien controle el IdP crea usuarios aquí: por eso es configurable y no un hecho. |
| `API_KEY_CADUCIDAD_DIAS` | — | *(secreto)* | 0–3650 | Caducidad por defecto de una clave de API nueva. 0 = sin caducidad, que se desaconseja y por eso no es el default. |
| `API_KEY_BYTES` | — | *(secreto)* | 16–128 | Longitud en bytes del secreto generado (se muestra en base64url una sola vez). 32 bytes = 256 bits. |
| `SUPLANTACION_ENABLED` | 🔥 `suplantacion_enabled` | `True` |  | El soporte puede entrar como un usuario del tenant, pero: con motivo escrito, con caducidad corta y dejando rastro en la auditoría. Sin las tres cosas, es un agujero con buena intención. |
| `SUPLANTACION_MAX_MINUTOS` | 🔥 `suplantacion_max_minutos` | `60` | 5–1440 |  |
| `SUPLANTACION_EXIGE_MOTIVO` | — | `True` |  |  |
| `OIDC_CACHE_TTL_S` | 🔥 `oidc_cache_ttl_s` | `300` | 10–86400 | Cuánto se cachean el documento de descubrimiento y las claves de un proveedor. Cinco minutos: lo bastante para no consultar al IdP en cada inicio de sesión, y lo bastante poco para que una rotación de claves se recoja sola sin tocar nada. |
| `SSO_MARGEN_RELOJ_S` | — | `60` | 0–600 | Margen de reloj admitido al validar la vigencia de un token. Los relojes del IdP y del servidor no van sincronizados al milisegundo, y sin margen un token recién emitido puede parecer futuro. |
| `SSO_ESTADO_TTL_S` | 🔥 `sso_estado_ttl_s` | `300` | 60–3600 | Cuánto vive un inicio de sesión a medias —el estado entre que se manda al usuario al IdP y vuelve—. Cinco minutos basta para escribir una contraseña y pasar el segundo factor; más deja la ventana abierta. |
| `SESION_COOKIE_NOMBRE` | — | `contecrm_sesion` |  | El token de acceso viaja en cookie cuando quien llama es un navegador. Es la única forma de que un XSS no se lleve la sesión: lo que está en `localStorage` lo lee cualquier script inyectado, y una cookie `HttpOnly` no. Nombre configurable porque dos despliegues de la casa en el mismo dominio se… |
| `SESION_COOKIE_SECURE` | — | `True` |  | `secure` en producción SIEMPRE: una cookie sin él viaja en claro si alguien fuerza http, y con ella va la sesión entera. Se deja configurable para poder trabajar en local sobre http, y el arranque avisa si se despliega en producción con esto apagado. |
| `SESION_COOKIE_SAMESITE` | — | `lax` |  | `lax` y no `strict`: con `strict` la vuelta del proveedor de identidad —que es una navegación desde otro dominio— llega sin cookie y el SSO no completa nunca. `lax` sigue bloqueando el envío en peticiones cruzadas de escritura, que es de lo que protege. |

## Límites, resiliencia y topes de proceso

| Variable de entorno | Clave en caliente | Defecto | Rango | Qué hace |
|---|---|---|---|---|
| `RATE_LIMIT_ENABLED` | — | `True` |  |  |
| `RATE_LIMIT_VENTANA_S` | — | `60` | 1–3600 | Ventana de conteo. Una ventana corta reacciona antes a una ráfaga; una larga tolera mejor el tráfico a golpes de un proceso por lotes. |
| `RATE_LIMIT_POR_USUARIO` | 🔥 `rate_limit_por_usuario` | `600` | 0–1000000 | Topes por dimensión. Se aplican TODOS: el más restrictivo manda. Están separados porque el abuso tiene formas distintas — un usuario con un bucle, una integración mal configurada, un tenant entero desbocado. |
| `RATE_LIMIT_POR_API_KEY` | — | *(secreto)* | 0–1000000 |  |
| `RATE_LIMIT_POR_TENANT` | 🔥 `rate_limit_por_tenant` | `6000` | 0–10000000 |  |
| `RATE_LIMIT_POR_IP` | — | `1200` | 0–1000000 |  |
| `MAX_BODY_MB` | — | `25` | 1–1024 |  |
| `BULK_MAX_ITEMS` | 🔥 `bulk_max_items` | `1000` | 1–100000 | Tope de elementos en una operación masiva (CRM-00.02.01.11). Por encima, la API obliga a usar el camino asíncrono con job id, que es el que tiene progreso, reanudación e informe parcial. |
| `COMPOSITE_MAX_OPS` | — | `25` | 1–500 | Tope de operaciones en una petición compuesta (CRM-00.02.01.13). |
| `PAGE_MAX_SIZE` | 🔥 `page_max_size` | `200` | 1–10000 | Página máxima que se puede pedir. Sin tope, un `limit=1000000` es una denegación de servicio escrita por el propio cliente sin querer. |
| `PAGE_DEFAULT_SIZE` | — | `50` | 1–1000 |  |
| `TRABAJO_MAX_ITEMS` | 🔥 `trabajo_max_items` | `100000` | 1–5000000 | Elementos que admite una operación masiva por el camino diferido. Es dos órdenes de magnitud más que el síncrono porque aquí no hay nadie esperando: el límite ya no es la paciencia de un navegador, sino lo que cabe razonablemente en el JSONB de una fila. |
| `TRABAJO_TANDA` | 🔥 `trabajo_tanda` | `200` | 1–10000 | Elementos que procesa un worker entre commit y commit. Es la unidad de reanudación: una tanda grande amortiza el viaje a la base, y una pequeña pierde menos trabajo cuando el proceso muere a mitad. |
| `TRABAJO_LOTE` | — | `5` | 1–100 | Trabajos que un worker se lleva por vuelta. |
| `TRABAJO_BLOQUEO_MIN` | — | `5` | 1–120 | Cuánto retiene un worker un trabajo antes de que otro pueda recuperarlo. Se renueva en cada tanda, así que basta con que supere lo que tarda UNA tanda, no el trabajo entero. |
| `TRABAJO_RETENCION_H` | 🔥 `trabajo_retencion_h` | `72` | 1–8760 | Cuánto se conserva un trabajo terminado. Guarda la entrada completa, que en una importación son los datos que subió el cliente: conservarla «por si acaso» pasado el plazo es justo lo que el plazo impide. |
| `TRABAJO_ESPERA_VACIO_S` | — | `2.0` | 0.1–60.0 | Espera del worker cuando no hay nada que hacer. Es la latencia máxima entre aceptar un trabajo y empezarlo. |
| `HTTP_INTERNO_TIMEOUT_S` | — | `10.0` | 0.5–300.0 | Timeout de una llamada entre servicios. Corto: encadenar tres llamadas con timeouts largos convierte un servicio lento en una caída general. |
| `HTTP_EXTERNO_TIMEOUT_S` | — | `30.0` | 1.0–600.0 | Timeout de una llamada a un sistema externo (ERP, firma, telefonía). Más largo porque no controlamos su latencia, pero acotado igual. |
| `REQUEST_TIMEOUT_S` | — | `60.0` | 1.0–900.0 | Una petición que pasa de aquí se corta y devuelve 504. Existe para que una consulta patológica no retenga una conexión del pool indefinidamente. |
| `CIRCUIT_BREAKER_ENABLED` | — | `True` |  |  |
| `CB_UMBRAL_FALLOS` | — | `5` | 1–1000 | Fallos consecutivos que abren el circuito. |
| `CB_REPOSO_S` | — | `30` | 1–3600 | Tiempo que permanece abierto antes de dejar pasar una petición de prueba. |
| `DEGRADACION_ENABLED` | — | `True` |  |  |
| `DEGRADACION_UMBRAL_POOL` | — | `0.85` | 0.1–1.0 | Uso del pool de conexiones (0..1) a partir del cual se difiere lo no crítico: recálculos, enriquecimientos, informes programados. Se difiere, no se pierde. |
| `PROCESO_MAX_PASOS` | 🔥 `proceso_max_pasos` | `1000` | 1–1000000 | Topes que impiden un proceso desbocado. Sin ellos, una automatización que se dispara a sí misma consume el sistema entero. |
| `PROCESO_MAX_PROFUNDIDAD` | — | `10` | 1–100 |  |
| `PROCESO_MAX_DURACION_H` | 🔥 `proceso_max_duracion_h` | `720` | 1–8760 |  |
| `AUTOMATIZACION_MAX_CASCADA` | 🔥 `automatizacion_max_cascada` | `5` | 1–100 | Cadena máxima de automatizaciones que se disparan unas a otras (CRM-00.03.03.06). |
| `COMENTARIO_MAX_CARACTERES` | 🔥 `comentario_max_caracteres` | `10000` | 100–1000000 | Longitud máxima de un comentario. 10.000 caracteres son unas tres páginas: de sobra para explicar un caso, y un tope que impide que alguien pegue un contrato entero en una nota y lo convierta en la fila más pesada de la tabla. |
| `COMENTARIO_MAX_MENCIONES` | 🔥 `comentario_max_menciones` | `20` | 1–500 | Menciones por comentario. Sin tope, un solo comentario puede generar un aviso para toda la empresa. |
| `CACHE_BACKEND` | — | `memoria` |  | `memoria` o `redis`. En memoria vale para desarrollo y para las pruebas; con más de una réplica deja de valer, porque cada proceso tendría la suya y una purga en uno no alcanzaría a los demás. El arranque avisa. |
| `CACHE_URL` | — | *(vacío)* |  |  |
| `CACHE_TTL_S` | — | `300` | 1–86400 | TTL por defecto de una entrada. Cinco minutos: suficiente para absorber la ráfaga de una pantalla que pide lo mismo diez veces, y lo bastante corto para que un dato cambiado desde otra vía no se quede pegado. |
| `CACHE_TTL_MAX_S` | — | `3600` | 1–604800 | Tope duro. Una entrada con un TTL enorme mantiene ocupada la memoria de lo ya invalidado por una purga, que no borra: hace inalcanzable. |
| `CACHE_TTL_GENERACION_S` | — | `5` | 0–300 | Segundos que cada proceso recuerda la generación de un tenant sin volver a preguntarla. Durante esa ventana una réplica puede seguir sirviendo lo purgado: es el precio explícito de no pagar un viaje de red por lectura. |
| `BUSQUEDA_IDIOMA` | 🔥 `busqueda_idioma` | `spanish` |  | Configuración de texto de Postgres, que decide cómo se derivan las palabras. Con la equivocada, «facturas» no encuentra «factura» y la búsqueda parece rota sin que nada falle. Va por tenant porque un cliente portugués no busca igual que uno español. |
| `BUSQUEDA_MAX_RESULTADOS` | 🔥 `busqueda_max_resultados` | `20` | 1–200 | Resultados por consulta. Más de una pantalla no se mira, y pedir mil obliga a Postgres a ordenar mil por relevancia para tirar novecientos. |
| `TRANSICIONES_PROHIBIDAS` | 🔥 `transiciones_prohibidas` |  |  | Transiciones que este tenant QUITA de las que el código admite. Solo quita: añadir un estado que el código no conoce dejaría el registro en un limbo que ningún `if` sabe manejar. {"oportunidad": {"perdida": ["abierta"]}} significa «aquí una oportunidad perdida no se reabre». Vacío por defecto:… |
| `AUTOMATIZACION_MAX_VUELTAS` | — | `200` | 1–10000 | Vueltas máximas de un `para_cada`. Una automatización que recorre una colección no puede colgar la petición que la disparó: guardar una oportunidad con seiscientas líneas dispararía seiscientas acciones y el usuario vería un formulario congelado sin saber por qué. Cuando se corta se DICE en la… |
| `AUTOMATIZACION_MAX_ANIDAMIENTO` | — | `3` | 1–10 | Anidamiento máximo de ramas y bucles. Tres niveles cubren todo lo que alguien construye en una interfaz; más que eso es un proceso, y para eso está el motor de procesos, que sabe reanudar y compensar. |

## Observabilidad y auditoría

| Variable de entorno | Clave en caliente | Defecto | Rango | Qué hace |
|---|---|---|---|---|
| `LOG_LEVEL` | — | `INFO` |  |  |
| `LOG_FORMAT` | — | `auto` |  | json en producción (lo consume el agregador), consola en desarrollo (lo lee una persona). `auto` decide por `env`. |
| `LOG_REDACT_PII` | — | *(vacío)* |  | Hashear PII (correos, IPs, user-agents) en los logs. `None` = encendido fuera de desarrollo y apagado en desarrollo, donde poder buscar un correo en el log es justo lo que se necesita para depurar. |
| `LOG_REQUEST_BODY` | — | `False` |  | Cuerpo de las peticiones en el log. Apagado: es la vía más rápida de filtrar datos personales a un sistema de logs que no está pensado para guardarlos. |
| `METRICS_ENABLED` | — | `True` |  |  |
| `METRICS_PATH` | — | `/metrics` |  |  |
| `METRICS_POR_TENANT` | — | `True` |  | Etiquetar las métricas con el tenant. Da visibilidad por cliente, que es lo que pide el catálogo, pero multiplica las series por el número de tenants: con miles de tenants hay que apagarlo o muestrear. |
| `METRICS_MAX_TENANTS` | — | `200` | 1–10000 | Tope de tenants distintos etiquetados. Pasado el tope, el resto se agrupa en `otros`. Es lo que evita que la cardinalidad tumbe a Prometheus. |
| `TRACING_ENABLED` | — | `False` |  | Apagado por defecto. Encenderlo SIN el paquete instalado impide arrancar, a propósito: arrancar en silencio sin trazas es el fallo que se descubre el día que hace falta la traza. |
| `OTEL_ENDPOINT` | — | `http://localhost:4318/v1/traces` |  | Por defecto el puerto OTLP/HTTP del colector (4318). El de gRPC es el 4317. |
| `OTEL_PROTOCOLO` | — | `http` |  | `http` no arrastra `grpcio` y atraviesa proxies corporativos sin configurar nada; `grpc` es el que piden algunos colectores. |
| `OTEL_SAMPLE_RATIO` | — | `0.1` | 0.0–1.0 | Fracción de peticiones trazadas (0..1). 1.0 en desarrollo; en producción se baja porque el coste es real y una muestra basta para ver la forma. |
| `AUDIT_ENABLED` | — | `True` |  |  |
| `AUDIT_HASH_CHAIN` | — | `True` |  | Encadenar cada apunte con el hash del anterior. Convierte el log en verificable: si alguien borra o edita una fila, la cadena se rompe y se puede demostrar. Cuesta un hash por apunte. |
| `AUDIT_RETENCION_DIAS` | 🔥 `audit_retencion_dias` | `2190` | 30–36500 | Retención antes de archivar o purgar (CRM-00.05.04.04). Seis años cubre los plazos mercantiles habituales en España. |
| `AUDIT_SIEM_URL` | — | *(vacío)* |  | Exportación a SIEM: destino syslog/HTTP. Vacío = no se exporta. |
| `SMTP_HOST` | — | *(vacío)* |  | SMTP y no la API de un proveedor: lo hablan todos —SendGrid, SES, Mailgun— y también el servidor corporativo del cliente que no quiere que su correo salga de su red. Cambiar de proveedor es cambiar estas líneas, no desplegar código. Vacío = no hay correo. Los avisos se quedan en la cola con su… |
| `SMTP_PUERTO` | — | `587` | 1–65535 |  |
| `SMTP_USUARIO` | — | *(vacío)* |  |  |
| `SMTP_CLAVE` | — | `` |  |  |
| `SMTP_TLS` | — | `starttls` |  | `starttls` es lo normal en el 587; `ssl` en el 465; `ninguno` solo tiene sentido contra un relé de la propia red, y con credenciales se rechaza. |
| `SMTP_REMITENTE` | — | *(vacío)* |  |  |
| `SMTP_TIMEOUT_S` | — | `20.0` | 1.0–300.0 |  |
| `NOTIFICACION_LOTE` | — | `100` | 1–5000 | Reparto: cuántos avisos por vuelta y cuánto se espera entre reintentos. La espera crece con el intento (1 min, 4, 9, 16…): un proveedor caído diez minutos no puede costar diez minutos de avisos perdidos, y uno caído tres días no puede costar tres días de reintentos. |
| `NOTIFICACION_MAX_INTENTOS` | — | `5` | 1–50 |  |
| `NOTIFICACION_ESPERA_BASE_S` | — | `60` | 1–3600 |  |
| `NOTIFICACION_ESPERA_VACIO_S` | — | `5.0` | 0.1–300.0 |  |
| `HEALTH_CHECK_TIMEOUT_S` | — | `3.0` | 0.1–30.0 | Tiempo máximo que puede tardar una comprobación de readiness antes de darla por fallida. Corto: un readiness lento hace que el orquestador crea que el servicio está caído. |

## Protección del dato

| Variable de entorno | Clave en caliente | Defecto | Rango | Qué hace |
|---|---|---|---|---|
| `ENCRYPTION_KEY` | — | *(secreto)* |  | Clave maestra de la que derivan las claves de cifrado de campo. Si está vacía, los campos marcados como cifrados NO se pueden escribir y el arranque avisa: preferimos un fallo visible a guardar en claro algo que el modelo declaró sensible. |
| `ENCRYPTION_KEY_PREVIA` | — | *(secreto)* |  | Clave anterior, para poder descifrar lo escrito antes de una rotación. Mantenerla mientras dura el recifrado es lo que hace la rotación posible sin ventana de caída. |
| `BYOK_ENABLED` | — | `False` |  | BYOK/CMEK (CRM-00.01.04.09): cuando está activo, la clave la aporta el tenant y se guarda cifrada con la maestra. Revocarla deja sus datos ilegibles a propósito, que es justo lo que el cliente compra. |
| `SECRETOS_BACKEND` | — | *(secreto)* |  | Backend del almacén de secretos por tenant. `db` los guarda cifrados en la base; `vault` delega en un gestor externo. Genérico a propósito: la configuración decide, no el código. |
| `SECRETOS_VAULT_URL` | — | *(vacío)* |  |  |
| `MASKING_ENABLED` | 🔥 `masking_enabled` | `True` |  | Aplicar máscara por rol en las respuestas de API y en las exportaciones. Se hace en la serialización, no en la consulta, para que el mismo dato se vea completo o enmascarado según quién pregunte sin duplicar consultas. |
| `DLP_ENABLED` | — | `True` |  |  |
| `DLP_EXPORT_FILAS_AVISO` | 🔥 `dlp_export_filas_aviso` | `5000` | 1–10000000 | Filas a partir de las cuales una exportación se considera masiva: se audita siempre y, según política, se bloquea o pide aprobación. |
| `DLP_EXPORT_FILAS_BLOQUEO` | 🔥 `dlp_export_filas_bloqueo` | `100000` | 0–100000000 |  |
| `PAPELERA_DIAS_RETENCION` | 🔥 `papelera_dias_retencion` | `30` | 1–3650 | Días que un registro borrado se conserva antes de poder destruirse. Un mes es el plazo con el que casi todos los errores humanos se detectan: quien borró algo por error lo echa en falta en la siguiente revisión mensual. |
| `TLS_EXIGIDO` | — | *(vacío)* |  | Exigir que la petición haya llegado por HTTPS. Se comprueba con el esquema real o con `X-Forwarded-Proto` cuando hay proxy de confianza. `None` = encendido fuera de desarrollo, que es lo que casi siempre se quiere y nadie se acuerda de activar. |
| `TLS_VERSION_MINIMA` | — | `1.3` |  | Versión mínima de TLS que el despliegue promete. No la aplica este proceso —la termina el proxy o el balanceador— pero SÍ se comprueba con `scripts/verificar_cifrado.py` contra el despliegue real. Declararla sin medirla sería una promesa sin respaldo. |
| `DB_SSLMODE` | — | `prefer` |  | Modo SSL de la conexión con Postgres. `require` cifra; `verify-full` además comprueba el certificado, que es lo que impide un intermediario dentro de la propia red. En producción se exige al menos `require`. |
| `BUS_TLS` | — | `False` |  | TLS hacia el bus y hacia la caché. Van aparte porque en muchas instalaciones el bus está en la misma red y la caché no, o al revés. |
| `CACHE_TLS` | — | `False` |  |  |
| `HSTS_MAX_AGE` | — | `31536000` | 0–63072000 | HSTS en segundos. 0 = no se envía. Un año es el valor que piden las listas de precarga. |
| `TRUST_PROXY_HEADERS` | — | `False` |  | Confiar en las cabeceras de proxy (X-Forwarded-For). Solo debe activarse si de verdad hay un proxy delante: si no, cualquiera falsea su IP y se salta el rate limiting y las listas de permitidos. |
| `TRUSTED_PROXIES` | — | *(vacío)* |  | Redes desde las que se aceptan esas cabeceras, separadas por comas. |
| `URL_GUARD_HOSTS_PERMITIDOS` | 🔥 `url_guard_hosts_permitidos` | *(vacío)* |  | Hosts internos que el operador admite pese a estar en rango privado, separados por comas. Existe porque hay instalaciones con el IdP o el ERP en la red interna, y negarlo obligaría a apagar el guard entero. |
| `URL_GUARD_DNS_TIMEOUT_S` | — | `3.0` | 0.1–30.0 | Plazo para resolver el DNS de una URL de salida. `getaddrinfo` no admite tiempo límite, así que se ejecuta en un hilo aparte con este plazo: un DNS que no contesta colgaría el hilo que atiende la petición. |
| `POLITICA_SENSIBILIDAD` | 🔥 `politica_sensibilidad` |  |  | `ve_hasta` es el nivel máximo que se ve EN CLARO; `enmascara`, hasta dónde se ve con los últimos caracteres. Por encima de eso, no se ve. Los valores por defecto son conservadores a propósito: un rol que no aparezca aquí no ve nada por encima de `interno`. Un rol nuevo sin configurar no puede… |
| `ABAC_MOTOR_EXTERNO_ENABLED` | — | `False` |  |  |
| `ABAC_MOTOR_EXTERNO_URL` | — | *(vacío)* |  |  |
| `ABAC_MOTOR_EXTERNO_TIMEOUT_S` | — | `2.0` | 0.1–30.0 | Corto a propósito: esto se consulta en la ruta caliente de cada decisión. Un motor lento no puede convertir cada ficha en una espera, y como no contestar significa «decide tú», agotar el plazo es seguro. |
| `DLP_ENABLED` | — | `True` |  |  |
| `DLP_MAX_REGISTROS_EXPORT` | — | `50000` | 100–10000000 | Tope duro por exportación. Alto a propósito: no es el mecanismo principal —ese es la comparación con el patrón— sino el que impide que alguien se lleve la base entera de una sola vez. |
| `DLP_MAX_EXPORTS_HORA` | — | `20` | 1–1000 | Exportaciones por hora y usuario. Quien de verdad se está llevando datos trocea para no disparar el tope por volumen. |
| `DLP_BLOQUEAR` | — | `False` |  | Si se BLOQUEA o solo se avisa. Apagado de serie, y no por descuido: bloquear una migración legítima cuesta tanto como dejar pasar una fuga, y esa decisión es del cliente. Lo que no es opcional es que quede registrado. |
| `DLP_DIAS_PATRON` | — | `14` | 1–365 | Días de historial con los que se calcula lo normal de cada usuario. Dos semanas cubren el ciclo de trabajo de casi cualquiera sin arrastrar el cierre de trimestre, que distorsionaría el patrón durante meses. |
| `DLP_FACTOR_ANOMALIA` | — | `3.0` | 1.5–100.0 | Cuántas veces su propia media tiene que superar alguien para que se avise. Tres es holgado a propósito: un umbral ajustado convierte el aviso en ruido y el ruido en «esto siempre salta», que es peor que no tener aviso. |
| `DLP_MINIMO_PARA_PATRON` | — | `5` | 2–1000 | Exportaciones mínimas en el historial para fiarse del patrón. Con dos datos, cualquier tercero parece una anomalía. |
