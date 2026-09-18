# Manual III — Referencia funcional

Qué hace hoy contecrm, capacidad por capacidad, con el identificador del
[catálogo funcional](catalogo/catalogo.yaml) entre paréntesis. Ese identificador
es la clave de trazabilidad: desde él se llega al código que lo implementa y a la
prueba que lo sostiene.

> **Qué significa que algo esté aquí.** Solo se documenta lo que está
> **implementado y probado**. Lo que está a medias se dice explícitamente en
> [«Lo que está a medias»](#lo-que-esta-a-medias), y lo que no está no aparece:
> el estado completo de las 527 capacidades está en
> [el estado del catálogo](catalogo/estado.md), donde 86 constan como hechas.

---

## 1. Multi-tenancy

### Aislamiento de datos

Toda entidad de negocio lleva `tenant_id` y **ninguna consulta puede
saltárselo** (CRM-00.01.01.01). No es una convención: hay tres capas que lo
imponen, y cada una cubre el hueco de la anterior.

1. **Row-Level Security en Postgres** (CRM-00.01.02.01). La política se aplica
   con `FORCE`, así que ni el dueño de la tabla ve de más, y cubre tanto la
   lectura (`USING`) como la escritura (`WITH CHECK`) — sin lo segundo, un
   tenant no podría leer lo ajeno pero sí insertar filas marcadas con el
   `tenant_id` de otro.
2. **Guard en la capa ORM** (CRM-00.01.02.03). Inyecta el filtro de tenant en
   todo `SELECT`, `UPDATE` y `DELETE` de un modelo con `tenant_id`.
3. **Contexto propagado** (CRM-00.01.02.02). El tenant viaja desde la cabecera o
   el token hasta el `SET app.current_tenant` de la conexión, sin que nadie
   tenga que pasarlo de función en función.

Se comprueba con un rol **sin privilegios** (CRM-00.01.02.04), que es la única
forma de que la prueba signifique algo: un superusuario ignora RLS aunque esté
en FORCE, así que una prueba ejecutada como superusuario pasa siempre.

Los identificadores son **UUIDv7 opacos** (CRM-00.01.02.07). Un identificador
secuencial invita a probar el siguiente, y entonces el aislamiento depende por
entero de que la comprobación de permisos sea perfecta en todos los endpoints.

Los eventos del bus van en un *subject* por tenant (CRM-00.01.01.10), de modo
que una avalancha de uno no bloquea la entrega de los demás.

### Ciclo de vida del tenant

- **Alta por API** con su configuración inicial (CRM-00.01.03.01).
- **Suspensión, reactivación y congelación en solo lectura**
  (CRM-00.01.03.04). El estado `solo_lectura` es el más útil de los tres: un
  impago o una migración no deberían cortar el acceso a los datos del cliente,
  solo impedir que los cambie. Todo cambio de estado que degrada el servicio
  **exige un motivo escrito**, que queda en la auditoría.
- **Jerarquía de tenants** para matriz–filial, franquicia o holding
  (CRM-00.01.03.07), y **unidades de negocio** dentro de un tenant
  (CRM-00.01.03.08). La diferencia importa: dos tenants no comparten nada y su
  aislamiento es duro; dos unidades de negocio comparten configuración y
  catálogos, y su separación es una regla de visibilidad.

### Configuración, planes y flags

La configuración es **jerárquica**: global → tier → tenant → unidad de negocio →
usuario (CRM-00.01.04.01). Cada nivel sobrescribe al anterior y lo que nadie
fije cae al valor de `.env`. Son 32 ajustes editables en caliente, con validación
al escribir y auditoría del cambio; la lista está en el
[Manual VI](manual-6-referencia-ajustes.md).

El **plan** decide qué capacidades están activas (CRM-00.01.04.05), y eso vive
como dato, no como condicionales en el código: un plan nuevo es una fila, no un
despliegue. Los **feature flags** son otra cosa y conviene no mezclarlos
(CRM-00.01.04.04): la capacidad es comercial —lo que el cliente ha contratado— y
el flag es técnico —si eso está listo para él—. El despliegue por porcentaje
reparte por *hash* del identificador, no al azar, para que a un mismo usuario le
toque siempre lo mismo.

Los **secretos de integración** se guardan cifrados por tenant
(CRM-00.01.04.08), con AES-256-GCM y claves derivadas por propósito: comprometer
un subsistema no da acceso a los secretos del otro.

### Cuotas y límites

- **Rate limiting** por tenant, usuario, clave de API e IP (CRM-00.01.06.01),
  con ventana deslizante. Se aplican todos y manda el más restrictivo, porque el
  abuso tiene formas distintas: un usuario con un bucle, una integración mal
  configurada, un tenant entero desbocado.
- **Cuotas** de registros, almacenamiento, llamadas, correos, procesos y tokens
  de IA (CRM-00.01.06.02), resueltas con la cadena ajuste → plan → entorno.
- **Panel de consumo** por tenant (CRM-00.01.06.06) y aviso al **cruzar** el
  umbral, no en cada petición por encima de él: si no, un tenant al 85 %
  generaría un aviso por llamada y el aviso dejaría de significar nada.
- **Medición para facturación** (CRM-00.01.06.07), agregada por periodo.

---

## 2. Contrato de API (headless)

Todo lo que hace el sistema existe como API antes que como pantalla
(CRM-00.02.01.01), y el contrato se genera **del código**, no se mantiene a mano
(CRM-00.02.01.04). Hay un gate que comprueba que ninguna ruta se queda sin
documentar y que ninguna operación de escritura declara solo el camino feliz.

- **Versionado explícito por URI** (CRM-00.02.01.05) con compatibilidad hacia
  atrás garantizada: un cambio rompedor estrena versión mayor y la anterior
  sigue sirviéndose (CRM-00.02.01.06). Cuando hay fecha de retirada anunciada,
  **toda respuesta** lleva las cabeceras `Sunset` y `Deprecation`
  (CRM-00.02.01.07) — es el único canal que el integrador ya está leyendo.
- **Paginación por cursor** estable (CRM-00.02.01.10). Con `offset`, insertar
  una fila entre dos páginas hace que el cliente vea un registro dos veces o se
  salte otro, sin poder notarlo.
- **Errores normalizados RFC 9457** (CRM-00.02.01.14) con `code` estable,
  `error_code` fino y `request_id`. El texto sirve cuando lo lee una persona; el
  código, cuando lo lee un programa.
- **Correlación extremo a extremo** con `X-Request-Id` y `traceparent`
  (CRM-00.02.04.07): una petición que atraviesa el gateway y dos servicios
  conserva un único hilo en los logs.

### Eventos salientes

- **Webhooks por tenant** con filtro por tipo y por contenido
  (CRM-00.02.02.01), **firmados con HMAC** y con ventana anti-replay
  (CRM-00.02.02.02).
- **Reintentos con backoff, cola de fallidos y reenvío** desde la consola
  (CRM-00.02.02.03). Un endpoint que acumula fallos se desactiva solo, y se
  avisa: seguir llamando a un endpoint muerto es tráfico y ruido.
- **Entrega at-least-once con clave de deduplicación** (CRM-00.02.02.04). La
  clave la pone el productor y sale del hecho, no de la publicación: si saliera
  de la publicación, los dos intentos serían «distintos» y el consumidor
  aplicaría el cambio dos veces.
- **Streaming sobre NATS JetStream** con *subject* por tenant
  (CRM-00.02.02.05), y **replay desde un punto en el tiempo**
  (CRM-00.02.02.09) para cuando el sistema del integrador estuvo caído.
- **Catálogo AsyncAPI** generado del registro de eventos del código
  (CRM-00.02.02.07). Una especificación mantenida a mano describe lo que alguien
  creía que el sistema publicaba el día que la escribió.

### Gateway

Única puerta de entrada (CRM-00.02.04.01): resuelve el tenant, autentica,
aplica los límites y enruta. El **tenant se resuelve** por token, clave de API,
cabecera o subdominio (CRM-00.02.04.02), y la distinción entre las dos primeras
vías —firmadas, autoritativas— y las dos últimas —pistas de enrutado— es lo que
evita que baste con cambiar una cabecera para operar sobre otro tenant.

Ningún servicio lleva lógica de negocio en la capa de presentación
(CRM-00.02.03.01): el gateway reenvía y no reinterpreta lo que dicen los
servicios.

---

## 3. Orquestación

### Servicios

Ocho servicios delimitados por capacidad (CRM-00.03.01.01), cada uno con su
esquema, su rol de base de datos **sin permisos sobre los demás**
(CRM-00.03.01.02) y su propia cadena de migraciones, de modo que ninguno espera
al otro para desplegar (CRM-00.03.01.06). La propiedad exclusiva de datos no es
una norma escrita en un documento: es una imposibilidad a nivel de permisos.

### Motor de procesos

- **Duradero** (CRM-00.03.02.01): el estado vive en la base y se vuelca en cada
  paso, así que si el worker muere, otro retoma la instancia donde estaba.
- **Sagas con coordinador** (CRM-00.03.02.03) y **compensación explícita por
  paso** (CRM-00.03.02.05). Al fallar el tercer paso se deshacen los dos
  anteriores **en orden inverso**. No es un *rollback*: un pedido enviado al ERP
  no se «desenvía», se anula, y esa anulación es una operación de negocio con
  sus propias consecuencias — por eso está declarada y no se infiere.
- **Coreografía por eventos** para lo de bajo acoplamiento (CRM-00.03.02.04).
- **Temporizadores y esperas** (CRM-00.03.02.07): mientras espera, una instancia
  no consume nada; solo tiene una fecha de despertar.
- **Subprocesos** reutilizables (CRM-00.03.02.08).
- **Tareas humanas** con bandeja, asignación por persona o por rol, delegación y
  plazo (CRM-00.03.02.09). Una espera de días por una aprobación es un estado
  normal del proceso, no un error de tiempo agotado.
- **Instancias consultables** con su historial paso a paso, incluidas la entrada
  y la salida de cada uno (CRM-00.03.02.11): sin los valores, reproducir un
  fallo obliga a adivinar con qué datos ocurrió.
- **Rescate de un proceso atascado** (CRM-00.03.02.12): reintento y corrección
  de variables en caliente, con motivo y auditoría.
- **Simulación antes de publicar** (CRM-00.03.02.14) y validación de la
  definición, que caza pasos inexistentes, rutas rotas y pasos inalcanzables.
- **Aislamiento por tenant** de definiciones y ejecución (CRM-00.03.02.15) y
  **límites** de pasos, profundidad y duración (CRM-00.03.02.16), porque un
  proceso que se llama a sí mismo consume el sistema entero.

### Automatizaciones

Reglas «cuando ocurre X, si Y, entonces Z» (CRM-00.03.03.01) con siete tipos de
disparador (CRM-00.03.03.02) y ejecución inmediata, diferida o programada
(CRM-00.03.03.05).

Dos garantías que van juntas porque una sin la otra no sirve
(CRM-00.03.03.06): **orden determinista** entre reglas —por prioridad y, a
igualdad, por antigüedad— y **corte de cascada** cuando una regla dispara otra
más allá del tope configurado.

Y un **depurador** (CRM-00.03.03.07) que registra también las veces que la regla
**no** se disparó y por qué condición. Sin eso, «¿por qué no se ha asignado este
lead?» no tiene respuesta, y es la pregunta que más se hace.

### Integraciones

Integrar un sistema externo es **configuración, no código** (CRM-00.03.04.02).
El conector declarativo se porta de `contecweb`, donde lleva en producción, con
sus cinco patrones medidos: alternativas por campo, marcadores de vacío,
expansión de sublistas, prefijo `^` para leer del objeto padre y OAuth2 con
token cacheado por tenant. Se añade paginación declarativa en cuatro estilos.

- **Mapeo y transformación** a los campos de contecrm (CRM-00.03.04.04): quien
  consume el resultado no sabe nada de la API de origen.
- **Credenciales por conexión** con rotación versionada y prueba de conectividad
  (CRM-00.03.04.05): una credencial caducada se descubre antes de que falle un
  proceso de negocio.
- **Monitor de ejecuciones** (CRM-00.03.04.06) y **cola de fallidos con reenvío**
  (CRM-00.03.04.07).

---

## 4. Modelo de datos del tenant

Cada tenant define sus propios **objetos** (CRM-00.04.01.01) y **campos**
(CRM-00.04.01.02) —19 tipos, con restricciones por tipo y clasificación de
sensibilidad— **sin que eso afecte a los demás tenants** (CRM-00.01.04.03).
Añadir un campo **no ejecuta DDL**: si lo hiciera, sería un bloqueo de esquema
que alcanzaría a todos los clientes de la instalación, y con mil tenants, una
tarde de bloqueos. El valor vive en una columna JSONB del registro y el esquema
de cada tenant es suyo.

Las **validaciones son declarativas** (CRM-00.04.01.06) y se pueden **consultar
antes de enviar**, con el mismo código que se usa al guardar. Que sea el mismo
es la única forma de que el *dry-run* signifique algo: dos implementaciones
acabarían divergiendo, y el cliente recibiría un «válido» seguido de un error.

El **describe** (CRM-00.04.01.08) devuelve campos, reglas, layouts y los
permisos de quien pregunta, que es lo que permite a cualquier frontend renderizar
sin duplicar reglas.

---

## 5. Identidad, permisos y auditoría

### Identidad

- **MFA con TOTP** y códigos de recuperación de un solo uso (CRM-00.05.01.06).
  No se activa hasta confirmar con un código válido: si se activara al generarla,
  un error al escanear dejaría al usuario fuera de su cuenta.
- **Credenciales de máquina** con ámbitos, caducidad y lista de IP
  (CRM-00.05.01.07). El secreto se enseña **una vez**.
- **Sesiones revocables** con rotación del token de refresco
  (CRM-00.05.01.08). Presentar un refresco ya rotado revoca **todas** las
  sesiones del usuario: significa que hay una copia en circulación.

### Permisos

- **RBAC** con roles heredables y conjuntos acumulables (CRM-00.05.02.01), y
  **jerarquía** con visibilidad ascendente sobre el equipo (CRM-00.05.02.02).
  Los permisos **se suman, nunca se restan**: en cuanto se mezclan concesiones y
  denegaciones con herencia, «¿por qué este usuario ve esto?» deja de tener
  respuesta.
- **ABAC** con políticas como datos (CRM-00.05.02.05), que se pueden guardar,
  versionar y **explicar**.
- **Explicador de permisos** (CRM-00.05.02.11): responde con el permiso que
  decide y la política que aplica. Existe porque «no puedo hacer X» sin
  explicación es el ticket de soporte más frecuente de cualquier CRM.
- **Suplantación auditada** (CRM-00.05.02.10) con motivo escrito, caducidad
  corta y rastro. Las tres condiciones juntas; quitar cualquiera la convierte en
  una puerta trasera con buena intención (CRM-00.01.02.06).

### Auditoría

- **Traza encadenada por hash** (CRM-00.05.04.01), una cadena por tenant, con
  huecos detectables y trigger de solo inserción.
- **Historial de campo** con valor anterior, nuevo, autor y **origen** —UI, API,
  automatización u orquestador— (CRM-00.05.04.02). Sin el origen, un cambio hecho
  por una regla automática aparece a nombre del usuario que la disparó sin querer.
- **Auditoría de configuración y permisos** (CRM-00.05.04.03): la mitad de los
  incidentes de «esto antes funcionaba» son un ajuste que alguien cambió.

### Protección del dato

**Cifrado de campo** con AES-256-GCM (CRM-00.05.03.02). GCM y no CBC porque
autentica: un valor alterado en la base no se descifra a otra cosa, falla.
Admite rotación con clave anterior, para no exigir una ventana de parada.

---

## 6. Observabilidad

- **Logs estructurados** con `tenant_id`, `trace_id`, `user_id` y servicio, sin
  que el llamante tenga que acordarse (CRM-00.06.01.01). Las credenciales se
  censuran siempre y los datos personales se hashean fuera de desarrollo.
- **Métricas por tenant** de latencia, volumen y errores (CRM-00.06.01.02), con
  **tope de cardinalidad**: pasados N tenants, el resto se agrupa. Sin ese tope,
  la etiqueta por cliente tumba a Prometheus y se pierden también las métricas
  que sí importaban.
- **Objetivos de latencia p95/p99 medidos por tenant** (CRM-08.01.01.01), con
  histogramas pensados para una API de negocio.

---

## 7. Entornos y calidad

**Entornos separados** por configuración (CRM-07.02.01.01) y **gates locales en
lugar de CI** (CRM-07.02.01.05), por decisión de proyecto. Lo que en otro
repositorio comprobaría un servidor, aquí lo comprueba la máquina de quien
desarrolla: están descritos uno a uno en [Gates locales](QUALITY_GATES.md).

---

## Lo que está a medias

Se dice aquí y no se esconde, porque una lista de capacidades que no distingue
entre «hecho» y «empezado» no sirve para decidir nada.

| Capacidad | Qué hay | Qué falta |
|---|---|---|
| `CRM-00.01.02.05` Tenant fuzzing | Varias rutas responden 404 —y no 403— ante un identificador ajeno | La suite sistemática que lo pruebe en **todas** |
| `CRM-00.01.04.07` Localización por tenant | Idioma, zona horaria y moneda guardados | Aplicarlos en formatos, calendarios y envíos |
| `CRM-00.01.04.09` BYOK / CMEK | Rotación con clave anterior | Clave aportada y revocable por el cliente |
| `CRM-00.02.01.08` Idempotencia | Módulo completo, con reserva previa y respuesta guardada | Engancharlo en cada ruta de escritura |
| `CRM-00.02.01.09` ETag / If-Match | Módulo completo y contador de versión en toda entidad | Aplicarlo recurso a recurso |
| `CRM-00.02.01.11` Operaciones masivas | Topes definidos y validados | El endpoint por recurso, con informe parcial |
| `CRM-00.02.01.12` API asíncrona | El motor de procesos cubre el trabajo largo | La API de *jobs* con id, sondeo y callback |
| `CRM-00.03.02.10` Tablas de decisión | Modelo y política de aciertos | El motor que las evalúa |
| `CRM-00.03.03.03` Acciones de automatización | Declaradas y validadas contra una lista cerrada | Los ejecutores de negocio (llegan con la fase 1) |
| `CRM-00.04.01.07` Máquinas de estado | Declarables por objeto | Forzarlas en la escritura |
| `CRM-00.05.02.03` Permisos por campo | Permisos por objeto y clasificación de sensibilidad | El filtro en la serialización |
| `CRM-00.05.03.01` Cifrado en tránsito y reposo | Cifrado de campo | TLS y cifrado de disco: son del despliegue, documentados en el Manual IV |
| `CRM-00.05.03.03` Enmascaramiento | Función lista | Aplicarla en la serialización por rol |
| `CRM-00.06.01.03` Trazas distribuidas | Contexto y `traceparent` propagados | El exportador OpenTelemetry |
| `CRM-00.06.01.06` Panel de salud del tenant | `/health/ready` y el registro de servicios | La página de estado por tenant |
