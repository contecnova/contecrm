# Manual III — Referencia funcional

Qué hace hoy contecrm, capacidad por capacidad, con el identificador del
[catálogo funcional](catalogo/catalogo.yaml) entre paréntesis. Ese identificador
es la clave de trazabilidad: desde él se llega al código que lo implementa y a la
prueba que lo sostiene.

> **Qué significa que algo esté aquí.** Solo se documenta lo que está
> **implementado y probado**. Lo que está a medias se dice explícitamente en
> [«Lo que está a medias»](#lo-que-esta-a-medias), y lo que no está no aparece:
> el estado completo de las 536 capacidades está en
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
| `CRM-00.05.02.04` Reglas de compartición | Las cinco vías (propietario, jerarquía, equipo, criterio y manual con caducidad), el explicador y su API | **Aplicarlas en los listados**: hoy devuelven el veredicto y la explicación de un registro, pero `party` y `sales` todavía no filtran sus consultas con ellas |
| `CRM-06.01.01.05` Gestión documental | Subida, versionado, deduplicación por contenido, enlaces firmados y registro de descargas | Carpetas, y el enlace a SharePoint/Drive |
| `CRM-06.02.01.02` Seguimiento y notificaciones | Suscripciones, preferencias por tipo y canal, agrupación, franja de silencio y la bandeja de la aplicación | El repartidor que entrega por correo, push y SMS: hoy las notificaciones se crean y se leen en la bandeja, pero nada sale del sistema |
| `CRM-07.01.01.01` Consola de administración | `GET /api/v1/superficie` en **todos** los servicios: cada operación con su método, ruta, permiso y si es de administración | La consola en sí. Lo que ya está garantizado es que no podrá hacer nada que no sea una de esas llamadas |
| `CRM-01.01.01.04` Relaciones no jerárquicas | Modelo y tabla: partner, competidor, proveedor, prescriptor, separados de la jerarquía | La API para crearlas y consultarlas |
| `CRM-01.01.01.05` Direcciones tipificadas | Varias por cuenta o contacto, con tipo y principal, y su API | Validación postal y geocodificación |
| `CRM-01.01.01.06` Identificadores fiscales | Varios por cuenta y validación del NIF/CIF español | El resto de países y la comprobación contra VIES |
| `CRM-01.01.01.10` Equipo de cuenta | Modelo con roles (owner, KAM, técnico, soporte, financiero) y nivel de acceso | Su API, y que pertenecer al equipo cuente como vía de compartición en los listados |
| `CRM-01.01.03.02` Captura multicanal de leads | Alta por API e importación masiva con validación previa | Formularios web, listas y chat |
| `CRM-01.01.04.10` Validación de contacto | Normalización de teléfono, formato de correo y puntuación de calidad | El estado de verificación real —rebote de correo, SMS— y la validación de dirección |
| `CRM-01.02.01.02` Gestión de actividades | Actividades con propietario, vencimiento y cierre | Delegación, recordatorios y la vista de vencidas |
| `CRM-07.03.01.03` Derechos del interesado | Registro de la solicitud con el plazo legal calculado al recibirla, y su API | La ejecución (exportar o borrar los datos) y la evidencia de haberlo hecho |

---

## 8. Cuentas, contactos y actividades (fase 1)

### Cuentas

La ficha de cuenta (CRM-01.01.01.01) reúne lo fiscal, lo comercial y lo
operativo, y admite **varios identificadores fiscales** (CRM-01.01.01.06): un
grupo con filiales en varios países tiene uno por país, y una sola columna
obliga a elegir cuál se guarda — normalmente el del país de quien dio de alta la
ficha.

Los **papeles no son excluyentes**: la misma empresa puede ser cliente de una
división y proveedor de otra. Por eso son una lista y no un campo `tipo`; con un
solo tipo habría que duplicarla.

**Jerarquías multinivel** (CRM-01.01.01.02) y, sobre todo, **varias a la vez**
(CRM-01.01.01.03): legal, comercial, de facturación y de entrega. No coinciden,
y modelarlas como una sola obliga a elegir cuál se pierde — la que se pierde
acaba viviendo en una hoja de cálculo. Enlazar dos cuentas comprueba que no se
forme un ciclo: un ciclo haría que consolidar importes no terminara nunca, y el
síntoma sería una petición colgada, no un error.

La **segmentación** (CRM-01.01.01.07) guarda el código de sector **con su
esquema** —CNAE, NAICS o SIC—, porque un número sin decir de qué tabla es no se
puede cruzar con nada.

### Contactos

Ficha con múltiples canales (CRM-01.01.02.01) y **relación N:M con las cuentas**
(CRM-01.01.02.02): una persona puede serlo de varias empresas, con papel
distinto en cada una. El vínculo tiene **vigencia**: cuando alguien cambia de
trabajo no se borra, se cierra — así el histórico de la cuenta sigue teniendo
sentido (quién firmó aquel contrato) y el contacto conserva su recorrido.

Las **preferencias de contacto** (CRM-01.01.02.05) incluyen canal, idioma,
horario y frecuencia máxima. No es cortesía: en muchos países forma parte del
cumplimiento y en todos evita quemar al contacto.

Los **consentimientos** (CRM-01.01.02.06) se guardan por finalidad y canal, con
su base legal y **con la prueba**: de dónde vino, cuándo y con qué texto. Cada
cambio es una fila nueva, nunca una actualización — la historia completa es lo
que demuestra que en el momento del envío había permiso, y sobrescribir deja al
sistema sin defensa justo cuando hace falta.

Hay una llamada específica para lo que marketing tiene que preguntar antes de
cada envío: **¿se puede contactar hoy por este canal y esta finalidad?**. Mira,
en este orden, el interruptor global de la ficha, la caducidad y el último
apunte.

### Calidad del dato

Es la parte donde un fallo silencioso hace más daño, y por eso la regla está
escrita en el código: **una clave canónica igual es un candidato, no una
prueba**.

- **Normalización** (CRM-01.01.04.04): razón social sin forma jurídica,
  teléfonos a E.164, dominios sin `www`. Con dos límites deliberados: un país
  desconocido **no** recibe prefijo inventado —un número formalmente válido que
  llama a otro sitio es peor que uno sin normalizar— y el correo **no** pierde
  las etiquetas ni los puntos, porque esa equivalencia solo vale en algunos
  proveedores y junta buzones reales en un dominio corporativo.
- **Detección de duplicados** (CRM-01.01.04.01) en el momento de la captura
  (CRM-01.01.03.03) y por lotes, con **coincidencia difusa**
  (CRM-01.01.04.02) que combina parecido de caracteres y solapamiento de
  palabras: una errata y un cambio de orden fallan en medidas distintas.
- Solo **el identificador fiscal** (en cuentas) y **el correo** (en contactos)
  bloquean un alta. El resto se propone, con **por qué** se propone: «mismo NIF»
  y «nombre parecido» llevan a decisiones distintas.
- **Fusión** (CRM-01.01.04.03) con selección de campo superviviente y
  reparentado de todo lo que colgaba. La ficha absorbida **no se borra**: hay
  documentos y sistemas externos que guardan su identificador. Y se puede
  deshacer, con un aviso honesto: se restauran los campos, **no** las relaciones
  —al reparentar se pierde de cuál venía cada una, y repartirlas a ojo sería
  peor que dejarlas juntas.
- **Puntuación de completitud** por registro (CRM-01.01.04.05), que devuelve el
  número **y qué falta**: «45» no dice qué hacer y «45, falta NIF y dirección»
  sí.

### Vista 360 y actividades

El **timeline unificado** (CRM-01.01.05.01) reúne el **historial completo de
interacciones** de una cuenta o un contacto (CRM-01.01.02.08), y el **perfil
consultable por API** (CRM-01.01.05.03) es lo que consume cualquier frontend. Declaran
explícitamente qué métricas **todavía no** están disponibles, para que un
consumidor distinga «no hay datos» de «este CRM no lo tiene aún».

Las **actividades** (CRM-01.02.01.01) son un solo modelo para tarea, llamada,
reunión, nota y visita — no cinco tablas—, precisamente para que el timeline
pueda ordenarlas sin una unión que crece con cada tipo nuevo. Se cuelgan de
cualquier objeto, incluidos los propios del tenant (CRM-01.02.01.03).

---

## 9. Leads y oportunidades (fase 1)

### Leads

El lead tiene **ciclo de vida propio** (CRM-01.01.03.01) y no entra en el
maestro de clientes hasta que se cualifica: meter ahí la basura de captación
—formularios a medias, correos de prueba— hace que el maestro deje de ser fiable
justo para lo que se usa, que es facturar y decidir.

El **SLA de primera respuesta** (CRM-01.01.03.07) corre **desde que entra el
lead**, no desde que se asigna. Contarlo desde la asignación permitiría cumplirlo
siempre sin más que asignar tarde. La primera respuesta es idempotente: la
primera es la que cuenta, y sobrescribirla maquillaría el incumplimiento.

Los **motivos de descarte** son de lista cerrada (CRM-01.01.03.05) porque lo que
se quiere es contar: «sin presupuesto» y «fuera de perfil» llevan a acciones
distintas y en texto libre no se pueden agrupar. Y todo descarte programa su
**reciclaje**: un «ahora no» no es un no para siempre.

Al **convertir**, el lead se conserva apuntando a la cuenta, el contacto y la
oportunidad que generó. Sin esa traza, «¿de dónde salió este cliente?» no tiene
respuesta y la atribución es una estimación.

### Oportunidades

La oportunidad (CRM-03.01.01.01) lleva importe, moneda, fecha de cierre,
probabilidad y etapa. El importe es **decimal exacto**, nunca coma flotante: un
importe en `float` acumula error y acaba dando un total que no cuadra con la
suma de sus líneas. Y expone el **ponderado** —importe por probabilidad— además
del bruto, no en su lugar: el bruto dice cuánto hay sobre la mesa y el ponderado
cuánto se espera cerrar, y confundirlos es el origen de la mitad de las
discusiones sobre una previsión.

- **Varios pipelines** (CRM-03.01.01.02): la venta de proyecto no tiene las
  mismas etapas que la de mantenimiento, y forzar una sola deja la mitad de las
  oportunidades en una etapa que no significa nada para ellas.
- **Criterios de salida por etapa** (CRM-03.01.01.03). Son lo que distingue un
  pipeline útil de una lista de colores: sin ellos una oportunidad llega a
  «negociación» sin importe ni fecha, y el pipeline suma números que nadie se
  cree. Se pueden saltar para cargar históricos, y queda constancia.
- **Líneas de producto** (CRM-03.01.01.05) con cantidad, precio y descuento. La
  descripción y el precio se **copian** del catálogo: si mañana sube el precio,
  esta oportunidad tiene que seguir diciendo lo que se ofreció. El importe de la
  cabecera sigue a las líneas, porque uno que no cuadra con ellas deja el
  pipeline sin credibilidad.
- **Competidores con posicionamiento** (CRM-03.01.01.09): saber que se perdió
  contra X es útil; saber que se perdió **por precio** y no por producto es lo
  que cambia la estrategia.
- **Antigüedad y estancamiento** (CRM-03.01.01.12) con umbral **por etapa**:
  tres semanas en «negociación» puede ser normal y en «primer contacto» no.
- **Bloqueo tras el cierre** (CRM-03.01.01.14). Una oportunidad cerrada no se
  edita: sus números ya están en un informe que alguien ha mirado y quizá en una
  comisión pagada. Reabrirla es explícito, exige motivo, queda auditado y
  **emite su propio evento**, para que quien consumió el cierre —la previsión,
  las comisiones, el pedido que se creó— pueda deshacerlo.

El historial de cambios de etapa guarda el **importe y la fecha de cierre en el
momento de cada cambio**: sin eso no se puede medir el deslizamiento, que es el
dato que explica por qué el trimestre no salió como se dijo.

### Derechos del interesado

Las solicitudes (CRM-07.03.01.03) se registran con su **plazo legal calculado al
recibirlas**, no al empezar a tramitarlas: el reloj corre desde que llegan, y
contar desde que alguien las mira sería incumplir sin enterarse.

---

## 10. Administración del tenant (fase 1)

Lo transversal: lo que no es de ventas ni de clientes, pero sin lo cual ninguno
de los dos funciona bien.

### Papelera de reciclaje

Borrar una cuenta con diez años de historia es casi siempre un error humano, y
es irreversible. Aquí **no se borra: se marca** (CRM-00.06.02.04), y la purga
definitiva la hace una tarea pasado el plazo de retención.

Lo que hace que esto valga de algo es la **cascada**: al borrar una cuenta se
marcan también sus actividades, y al restaurarla vuelven **exactamente las que
se fueron**, ni una más. La entrada de papelera guarda la lista de lo que
arrastró; sin ella, restaurar traería también lo que ya estaba borrado por otro
motivo, y la ficha volvería con datos que nadie esperaba.

Qué cuelga de qué se declara en **un solo sitio** por servicio
(`services/party/administracion.py`). Una tabla nueva que cuelgue de la cuenta y
no esté en esa lista sobreviviría al borrado y quedaría huérfana: visible en
listados, apuntando a algo que ya no está.

### Transferencia masiva e importación

La **transferencia de propiedad** (CRM-07.01.01.07) mueve de golpe todo lo de
una persona a otra: es lo que se ejecuta cuando alguien se va de la empresa, y
hacerlo a mano garantiza que algo se queda sin dueño.

La **importación** (CRM-07.01.01.08) **simula por defecto**. Primero valida
todas las filas y enseña qué va a pasar —cuántas altas, cuántas
actualizaciones, qué errores y en qué fila—, y solo después, con una segunda
llamada explícita, escribe. Una importación que empieza a escribir y falla a la
mitad deja un maestro de clientes en un estado que nadie sabe describir.

Se devuelven como mucho 200 errores. No es pereza: un informe con 40.000
errores no lo lee nadie y sí revienta el navegador. Con los doscientos primeros
se ve el patrón, que es lo que hay que corregir.

### Usuarios, licencias y bajas

La gestión de usuarios (CRM-07.01.01.02) cubre el alta, los roles, el recuento
de **licencias** contra el tope del plan y la baja.

Dar de baja a alguien desactiva su membresía, **corta sus sesiones** —no espera
a que caduquen— y **avisa de lo que hay que transferir**. La transferencia en sí
la hace cada servicio sobre sus objetos: el maestro de cuentas no es de
identidad, y sus permisos de base de datos se lo impiden. Esa separación es a
propósito: es la misma que evita que un fallo en identidad pueda escribir en la
base de clientes.

### Compartición: quién ve qué

El permiso dice si alguien puede leer cuentas; la **compartición**
(CRM-00.05.02.04) dice **cuáles**. Cinco vías que solo **suman**, nunca restan:
propietario, jerarquía de mando, equipo de la cuenta, criterio («todas las del
País Vasco con el equipo de Bilbao») y compartición manual con caducidad.

Que solo sumen es lo que permite responder a «¿por qué ve esto?» con una lista
de motivos —«es suyo **y además** se lo compartieron»— en vez de con «ejecuta el
motor y mira qué sale». Y la caducidad es lo que impide que
«compártemelo para revisar la propuesta» se convierta en un acceso permanente.

Las condiciones usan **la misma gramática que las políticas de permisos y que
las reglas de enrutamiento**: `{atributo, operador, valor}`. Una sola sintaxis
en todo el producto, para que quien aprende a escribir una condición sepa
escribirlas todas.

### Plantillas

Las plantillas de correo, documento y notificación (CRM-07.01.01.04) se
versionan y tienen **idioma**: un tenant que opera en tres países necesita la
misma plantilla en tres idiomas, y tenerlas como tres plantillas sueltas hace
que se desincronicen en cuanto alguien cambia una.

La sustitución es de texto y **nada más**: sin condicionales, bucles ni
expresiones. Una plantilla es dato del tenant, y un motor con lógica sería
ejecutar código del cliente dentro del servidor de correo. Para lo que necesita
lógica está la automatización, que sí está acotada y auditada.

Lo que falta se queda **visible** (`{{nombre}}`) en vez de vaciarse: un hueco en
blanco pasa desapercibido y se manda; un `{{nombre}}` en mitad del texto se ve.
Y `POST /plantillas/{id}/previsualizar` dice qué variables quedarían sin
resolver **antes** del envío, que es cuando todavía se puede arreglar.

### Calendarios laborales

Un SLA de «4 horas» tiene que significar cuatro horas **laborables**
(CRM-07.01.01.05). Contando horas de reloj, un aviso entrado el viernes a las
18:00 se incumple el sábado a las 22:00, cuando no había nadie.

El horario se declara **por día de la semana y con varios tramos**, porque la
jornada partida existe y es lo normal en varios sectores: con un solo intervalo
por día, la hora de comer contaría como laborable. Los festivos pueden ser de
fecha fija o **anuales** (Navidad sí, Semana Santa no), y los anuales se
comparan por día y mes sin el año.

`GET /calendarios/{id}/vencimiento?horas=4` calcula el vencimiento saltando
noches, fines de semana y festivos. Se expone para que cualquier servicio lo use
en vez de reimplementarlo, que es como acaban existiendo tres calendarios que no
coinciden.

### Monedas y tipos de cambio

Los tipos de cambio se guardan **con fecha y con histórico**, no solo el último
(CRM-07.01.01.06). Una oportunidad cerrada en marzo tiene que seguir valiendo lo
que valía en marzo: convertirla siempre al cambio de hoy hace que el histórico
de ventas se mueva solo y que dos informes del mismo trimestre den números
distintos según cuándo se sacaron.

La conversión usa el tipo **más reciente que no sea posterior** a la fecha
pedida, nunca el más cercano: un cambio publicado al día siguiente no existía
cuando se cerró la operación. Si falta el par directo se calcula con el inverso,
que es exacto: quien carga EUR→USD rara vez carga también USD→EUR.

La carga es genérica: `PUT /monedas/cambios` con un `origen` libre. Cualquier
fuente —el BCE, un proveedor de pago, un fichero del ERP— entra por ahí. No hay
un conector por proveedor, y no lo habrá.

### Valores de lista globales

Las listas maestras (CRM-07.01.01.03) —sectores, países, motivos de pérdida— se
definen una vez y las usan varios campos. Sin esto, cada campo de tipo lista
guardaría sus propias opciones y cambiar «motivo de pérdida» obligaría a
tocarlas todas.

Un valor **se desactiva, no se borra**: los registros históricos que lo usan
tienen que seguir enseñando su etiqueta. Un valor borrado convierte el histórico
en códigos sin significado.

### Adjuntos y gestión documental

Los ficheros van al **almacén** (`crmcore.almacen`), no a la base: un `bytea` de
25 MB por adjunto infla los backups y convierte cada `pg_dump` en una hora. El
almacén es local o S3 —vale cualquier compatible, porque lo que se configura es
el endpoint y no el proveedor—, y en producción el arranque **avisa** si se
dejó en local: cada réplica vería solo sus ficheros y un redespliegue los
perdería.

Subir un fichero con el mismo nombre **crea una versión nueva** y la anterior
sigue accesible. En un CRM el «contrato_final_v2.pdf» existe precisamente
porque el sistema no versionaba.

La deduplicación es por contenido (SHA-256) y, a diferencia de la de cuentas
—donde la clave canónica es un *candidato* y nunca una prueba—, aquí es
**exacta**: dos ficheros con el mismo hash son el mismo fichero. Nunca cruza
tenants, aunque el hash coincida: compartir el objeto haría que borrarlo en un
cliente afectara al otro.

Las extensiones se controlan con **lista blanca, no negra**. Una lista negra
siempre se queda corta —basta una extensión nueva— y lo que está en juego es
ejecutar algo en el navegador de quien descargue. Por lo mismo, la descarga
sale siempre como `attachment` con `nosniff`: servir en línea un fichero subido
por un usuario es servir su HTML desde el dominio del CRM, con la sesión de
quien lo abre.

Cada descarga queda registrada. Es lo primero que pide una investigación de
fuga de datos y no se puede reconstruir después.

Los **enlaces firmados** existen para los `<img src>` y para los enlaces de un
correo, donde no se pueden poner cabeceras. Caducan pronto y llevan el usuario
dentro, así que reenviar el enlace no borra el rastro de quién lo pidió.

### Seguir registros y recibir avisos

«Avísame cuando cambie esto» (CRM-06.02.01.02) es lo que hace que un CRM se use:
sin ello la gente entra a mirar si ha pasado algo y, como casi nunca ha pasado,
deja de entrar.

Los avisos **se agrupan**: una oportunidad que cambia cinco veces en diez
minutos genera **una** notificación. Sin agrupar, la bandeja se convierte en
ruido y se silencia entera — que es la forma de perder el canal para siempre,
incluido lo que sí importaba.

Las preferencias son por **tipo de evento × canal**, y la del tipo exacto gana
sobre la genérica `*`. Así se puede decir «nada de correo salvo los casos
escalados», que es la petición habitual y con la genérica ganando sería
inexpresable. La franja de silencio **retiene**, no descarta: lo que pasó de
noche sigue habiendo pasado, y lo urgente la atraviesa.

Al propietario de un registro no se le desuscribe: **se le silencia**. No puede
dejar de ser responsable de lo suyo, pero sí dejar de recibir avisos; borrar la
suscripción haría que volviera sola al siguiente cambio y el usuario viviría un
bucle de «ya he dicho que no».

Los servicios **no escriben** en la bandeja: emiten sus eventos y el consumidor
de identidad los traduce. `party` no puede insertar en el esquema de `identity`
—el rol de base de datos no se lo permite—, y eso además hace que notificar no
pueda tumbar la operación que lo provocó.

### La superficie de administración

«La consola está replicada al 100 % por API» (CRM-07.01.01.01) es una promesa
que se incumple sola: basta que alguien añada una pantalla con una acción que
solo la consola sabe hacer.

Por eso **cada servicio publica `GET /api/v1/superficie`**: todas sus
operaciones con método, ruta, permiso exigido y si son de administración. La
consola se construye leyendo eso, así que no puede existir una acción de consola
que no sea una llamada de esa lista — por construcción, no por disciplina. Se
monta sola en `crear_servicio`, como la salud: si dependiera de que cada
servicio se acuerde, faltaría justo en el que menos se mira.

---

## 11. Enrutamiento de leads (fase 1)

Un lead que entra y se queda sin dueño es un lead perdido: no sale en la lista
de nadie. El enrutamiento (CRM-01.01.03.04) decide quién lo atiende en el
momento en que entra, y deja escrito **por qué**.

Las reglas se evalúan por prioridad y gana **la primera que encaja**, no la
mejor. Con un sistema de puntos, «¿por qué ganó esta?» no tiene respuesta corta,
y un reparto que no se puede explicar se desactiva en la primera discusión.

Cuatro estrategias de reparto: por turnos (*round robin*), al de menos carga, al
primero disponible y a uno fijo. El turno vive **en la fila de la regla**, no en
memoria del proceso: con el contador en memoria, dos réplicas del servicio
empezarían las dos en cero y le darían todo al primer candidato. Y el desempate
por carga es por el orden declarado, no al azar, para que dos ejecuciones
iguales den el mismo resultado.

Tres decisiones que evitan fallos concretos:

- **Una regla sin condiciones válidas no encaja con nada.** Lo contrario
  —tratarla como comodín— haría que una errata en su única condición convirtiera
  una regla específica en la que se lleva todos los leads.
- **Una regla que encaja pero no tiene a quién asignar no bloquea a las
  siguientes.** Es lo que pasa en agosto con un equipo de vacaciones.
- **Siempre hay traza, incluso cuando no se asigna.** Lo que ninguna regla
  reclama va a la cola `sin_asignar` con la lista de reglas evaluadas y el
  motivo por el que cada una no encajó. Silenciarlo es como se acumulan leads
  que nadie ve.

Las reglas se validan **al guardarlas**, no al aplicarlas: cuando entra un lead
no hay nadie delante a quien devolverle un error, y lo único que cabe allí es
descartar la regla y seguir. `POST /lead-routing/reglas/probar` simula el
reparto sobre un lead inventado sin escribir nada ni mover el turno real.

Una asignación explícita manda sobre las reglas: si el comercial da de alta su
propio contacto, sabe algo que las reglas no saben.

---

## 12. Colaboración sobre el registro (fase 1)

### Comentarios, hilos y menciones

La conversación sobre un cliente ocurre igualmente: en el correo, en el chat o
de viva voz. Si ocurre fuera del CRM se pierde, y con ella el motivo por el que
se hizo el descuento, quién dijo que llamaría y qué respondió el cliente.
Traerla dentro (CRM-06.02.01.01) es lo que convierte la ficha en algo que
explica el caso y no en un formulario.

**Las menciones se extraen del texto**, que se escribe
`@[Nombre](identificador)`. No se mandan en una lista aparte porque habría dos
fuentes de verdad: en cuanto alguien edite el texto quitando una mención,
seguiría notificando a quien ya no aparece. Y el formato lleva identificador
además del nombre porque guardar solo el nombre rompería las menciones antiguas
al renombrar a alguien, y guardar solo el identificador dejaría el texto
ilegible.

**Mencionar a alguien lo suscribe** al registro: nombrar a un compañero para que
se entere y que luego no se entere de la respuesta sería absurdo. Desde ahí
puede silenciarlo como cualquier otro seguimiento. Los mencionados **se suman** a
quien ya seguía el registro, no lo sustituyen: avisar solo a los nombrados
dejaría fuera al responsable del caso.

Una mención a alguien de baja **no genera aviso**, y el descarte queda
registrado con su motivo — porque «¿por qué no le llegó?» es la pregunta que
viene detrás. Es un detalle portado de `contecmind`, junto con la consulta única
que evita un `SELECT` por mención.

Los hilos se agrupan: una conversación leída como lista plana de mensajes
ordenados por fecha no se entiende en cuanto hay dos temas a la vez, que es
siempre. Un hilo se puede dar por **resuelto**, para que la ficha no acumule
preguntas abiertas que ya nadie va a contestar.

Un comentario **interno** no sale nunca hacia el cliente: ni al portal, ni en un
correo automático, ni en una exportación. El filtro vive en el módulo y no en
quien llama, porque la decisión de qué ve un externo no puede depender de que
cada sitio se acuerde.

Un comentario **no se borra: se marca**, y su texto deja de devolverse. Marcarlo
y seguir mandando el cuerpo sería un borrado de mentira —cualquiera que mire la
respuesta de la API lo lee igual—, y borrarlo de verdad dejaría las respuestas
colgando de la nada. Editar deja marca: alguien contestó a lo que ponía antes, y
sin la marca esa respuesta parece no venir a cuento.

### Trazabilidad de origen

«¿Qué campaña trajo a este cliente?» se contesta mal casi siempre por el mismo
motivo: se guarda **un** origen, el de la última visita, porque es el que llega
en la petición donde se envió el formulario. Con eso, todo el mérito se lo lleva
la búsqueda de marca —la última visita antes de convertir suele ser «buscó
nuestro nombre»— y las campañas que de verdad descubrieron al cliente parecen no
servir para nada.

Por eso se guardan **todos los toques** (CRM-01.01.03.06) y se conservan aparte
el primero y el último. El primero explica cómo llegó; el último, qué lo cerró.

Los toques anónimos se enlazan con el lead **en el momento de identificarlo**, a
través de un identificador de visitante propio. Es el único momento en que el
recorrido anterior se puede recuperar: un minuto después se ha perdido, porque
nadie vuelve a mirar los toques huérfanos. La ventana hacia atrás es un ajuste
(`origen_ventana_dias`, 90 días por defecto): en obra o industria, entre la
primera visita y el formulario pasan meses.

El **primer toque es inmutable**. Un toque posterior no lo reescribe por mucho
que llegue con mejor información, y el `origen` del lead sale de él: la pregunta
es de dónde salió el cliente, no qué fue lo último que hizo.

`GET /origen/campanas` da las dos cifras por campaña —leads por primer toque y
por último—, y esa es la gracia: enseñarlas juntas es lo que hace visible que la
marca se lleva los cierres mientras otra campaña trajo a la gente. **No es un
modelo de atribución**: no reparte el mérito, lo cuenta desde dos puntos de
vista. Los modelos —lineal, en U, en W, por decaimiento— son CRM-02.02.01.06 y
llegan con marketing en la fase 4; lo que se hace ahora es guardar el dato con
la forma que van a necesitar, porque sin el recorrido completo no habría nada
que repartir.

Nada de esto es por proveedor: los parámetros son los `utm_*`, que son un
estándar de hecho, y los identificadores de clic van en un diccionario abierto.
No hay una lista de redes conocidas que ampliar cada vez que aparece una nueva.

---

## 13. Aislamiento fuera de la base, y la baja del cliente

Todo lo anterior descansa en que Postgres, con RLS, no deja que un tenant vea
las filas de otro. Pero **ni la caché ni el almacén de ficheros pasan por RLS**,
y son las dos vías más silenciosas por las que un cliente acaba viendo el dato
de otro.

### Caché con el tenant dentro de la clave

Basta una clave construida sin el tenant —`cuenta:{id}`, `ajustes:activos`—
para que la respuesta del primero que pregunte se le sirva al siguiente, sin
error, sin log y sin forma de notarlo hasta que alguien lo cuenta.

Por eso (CRM-00.01.01.07) **quien llama no construye claves**: pide un espacio
de nombres y unas partes, y la clave la fabrica el módulo con el tenant delante.
Saltarse el aislamiento no es difícil: es que no hay forma de expresarlo. Sin
tenant, la llamada **falla** en vez de caer a una clave global «por si acaso» —
un fallo al escribir el código sale infinitamente más barato que un dato cruzado
en producción. Para lo que de verdad es de la plataforma —el catálogo de
eventos, la tabla de países— hay una llamada distinta y ruidosa, `global_=True`,
que obliga a haberlo decidido.

**La purga de un tenant es O(1).** La clave lleva un número de generación; purgar
es incrementarlo, y todas las entradas anteriores dejan de ser alcanzables de
golpe. Recorrer el espacio de claves buscando un prefijo sería O(N) sobre la
instancia entera y, con `KEYS`, además bloquearía a Redis: un cliente dándose de
baja congelaría el sistema para todos los demás. De ahí la otra regla —**toda
entrada caduca**—, porque lo que la purga deja inalcanzable sigue ocupando
memoria hasta que el TTL lo recoja.

Y como cada módulo puede tener además su propia caché en proceso, hay un
**registro de invalidadores** (traído de `contecmind`, donde nació para romper
una dependencia circular): purgar un tenant llama a todos. Sin él, la purga
vaciaba la caché compartida mientras cada réplica seguía sirviendo sus ajustes
desde memoria.

### Ficheros bajo el prefijo del tenant

En el almacén (CRM-00.01.01.08) toda clave se construye con el tenant delante,
así que los ficheros de cada cliente viven bajo su propio prefijo y se pueden
borrar todos de golpe. Sin ese prefijo obligatorio, dar de baja a un cliente
exigiría recorrer la tabla de adjuntos, y lo que no estuviera en ella —un
huérfano, el resto de una migración— se quedaría ahí para siempre.

### Irse con los datos, y que conste que se borraron

La exportación (CRM-08.02.01.05) y la baja (CRM-00.01.03.05) son **la misma
máquina**, y están juntas por eso: la exportación que se entrega a quien se va es
la misma que puede pedir cuando no se va. Separarlas haría que la de la baja —la
que de verdad importa— se ejercitara una vez al año, y lo que no se ejercita no
funciona.

El formato es **JSON Lines**: una fila por línea, un fichero por objeto, un
manifiesto con el recuento y el SHA-256 de cada uno, y un `LEEME.md` que explica
cómo comprobarlo y cómo leerlo sin tener este producto delante. Un volcado en
formato propietario no es portabilidad: es un rehén con otro nombre. Y no un
JSON único, porque un millón de cuentas en un solo array no se puede leer sin
cargarlo entero en memoria, ni al generarlo ni al abrirlo.

El orden de la baja es **exportar, verificar, entregar, esperar, destruir**, y
las tres condiciones que bloquean la destrucción no son opcionales:

1. El tenant tiene que estar **en baja**. Destruir los datos de uno activo no es
   mantenimiento, es un incidente.
2. Tiene que haber pasado la **ventana de recuperación** de treinta días. Es la
   que convierte un error administrativo en algo reparable.
3. Tiene que existir una exportación **verificada**, no solo completa.
   «Completa» significa que se escribió; «verificada», que se ha **releído del
   almacén** y los hashes cuadran. Un fallo de escritura silencioso —disco lleno,
   objeto truncado— solo se ve leyendo de vuelta, y es justo antes de destruir
   los originales cuando hay que saberlo.

Lo que destruye este módulo es lo que no vive en la base: la caché y el almacén.
Las filas las borra cada servicio en su esquema, porque los permisos de base de
datos impiden —a propósito— que uno escriba en el de otro.

El **certificado de destrucción** recoge las dos partes, va encadenado por hash
como el registro de auditoría y **sobrevive al tenant**: es lo único que queda
cuando ya no queda nada. Un cliente que pregunta dos años después «¿seguís
teniendo mis datos?» necesita una respuesta que no sea «creemos que no».

---

## 14. Entrar con el proveedor de identidad de la empresa

Nadie quiere una contraseña más. En una empresa mediana, el CRM es el sistema
número once, y la única forma de que las bajas de personal se apliquen de verdad
es que el CRM no tenga su propia lista de usuarios que alguien tenga que
acordarse de actualizar.

### OIDC con PKCE

El mecanismo primario (CRM-00.05.01.01) es el flujo de código con **PKCE
siempre**, incluso habiendo secreto de cliente: OAuth 2.1 lo exige para todos
los clientes y no solo para los públicos. Sin PKCE, quien intercepte el código
de autorización —en el log de un proxy, en el historial del navegador, en una
cabecera `Referer`— puede canjearlo. Con él hace falta además el verificador,
que no sale nunca de este servidor. El método `plain` no se ofrece: convierte
PKCE en un adorno, porque reto y verificador serían el mismo valor.

El `estado` y el `nonce` son cosas distintas y hacen falta las dos: el estado
ata la respuesta a la petición que la inició, y el nonce ata el token de
identidad a ese mismo flujo.

El **estado del flujo va a la base de datos, no a la caché**. Entre la ida y la
vuelta pasan minutos y la vuelta la puede atender otra réplica; con la caché en
memoria, el inicio de sesión fallaría siempre y solo en producción. Y es de **un
solo uso**: se borra al consumirlo, porque si no, quien capture la respuesta la
reenvía y entra. El `state` se guarda **hasheado**, porque viaja en la URL y
acaba en logs.

Tres controles que, si fallan, no se notan —y por eso están portados tal cual de
`contecmind`, donde ya pasaron por auditoría:

- **Una clave que no case con el `kid` del token no se sustituye por la primera
  de la lista.** Hacerlo enmascara una rotación de claves o una configuración
  cruzada entre tenants, y deja pasar un token firmado con otra clave. Si no
  encaja ninguna, se refresca el JWKS una vez; y se distingue «el proveedor no
  devuelve ninguna clave» de «ninguna sirve», porque en el primer caso el
  problema es el IdP y con un mensaje genérico el operador busca donde no es.
- **Solo algoritmos asimétricos**, cruzados con los que el propio proveedor
  anuncia. Admitir uno simétrico permitiría firmar el token con la clave pública
  del IdP —que es pública— haciéndola pasar por secreto compartido.
- **El emisor sale del documento de descubrimiento**, no de la URL configurada:
  es el que el proveedor dice ser, que es contra el que hay que comparar. Y se
  exigen `exp`, `iat`, `iss`, `aud` y `sub`; sin `sub`, el token no identifica a
  nadie.

Las cachés de descubrimiento y de claves son **por proveedor**, no por proceso:
con una sola caché global, el segundo tenant se validaría contra las claves del
primero.

### SAML 2.0

Para el SSO empresarial que todavía va por SAML (CRM-00.05.01.02). Lo importante
es lo que **no** se hace: **no se valida la firma XML a mano**. Comprobar bien
una firma XML —canonicalización, referencias, transformaciones, envoltura— es un
campo de minas conocido, y una implementación propia que funciona con las
aserciones de prueba es exactamente por donde se cuela una falsificada. Lo hace
`python3-saml`.

Esa librería necesita `libxmlsec1` compilada en el sistema, así que es un
**extra opcional** (`requirements-saml.txt`): ponerla en las dependencias
obligaría a compilarla en todas las instalaciones, incluidas las que usan OIDC o
no usan SSO. Sin ella, estos endpoints responden 503 diciendo exactamente qué
falta y cómo instalarlo.

Se exige **aserción firmada** (`wantAssertionsSigned`), y hay pruebas que
comprueban que se rechaza la sin firmar, la firmada con otra clave y la
manipulada después de firmar. El host contra el que se valida el destinatario
sale de **nuestra** URL configurada y no de las cabeceras de la petición: `Host`
y `X-Forwarded-Host` las pone quien llama.

### Varios proveedores a la vez, y altas automáticas

Un tenant puede tener **varios proveedores simultáneos** (CRM-00.05.01.03) —dos
correos tras una fusión, empleados por Entra ID y partners por Google—, y el
dominio del correo decide a cuál va cada quien. Preguntárselo al usuario sería
una pregunta que nadie sabe contestar.

El **alta automática** (CRM-00.05.01.04) crea el usuario la primera vez que
entra, **sin contraseña local**: es lo que hace que forzar SSO sea de verdad,
porque sin credencial propia no hay forma de saltarse el IdP corporativo.

Los **roles se recalculan en cada entrada** a partir de los grupos del
proveedor. Si solo se asignaran al crear el usuario, quien cambia de
departamento conservaría los permisos antiguos para siempre. El mapeo gobierna
únicamente los roles que él mismo concede: los que un administrador puso a mano
en el CRM no se tocan. Y un grupo sin correspondencia **no da rol** — lo
contrario convertiría crear un grupo en el IdP en conceder acceso al CRM.

### Todas las salidas del servidor, con guard

La URL del proveedor la escribe el cliente, igual que la de un webhook o la de
un ERP en el conector. Sin guard, configurar un IdP en `169.254.169.254` es una
forma cómoda de leer los metadatos del proveedor de nube, y apuntarlo a
`postgres:5432` permite escanear la red interna desde dentro — con la salida en
el cuerpo de la respuesta que el propio CRM guarda para depurar.

Por eso **toda salida HTTP pasa por `crmcore.red`**: esquemas admitidos,
credenciales embebidas rechazadas, rangos privados y de metadatos bloqueados, y
un host que no resuelve **falla cerrado**. El transporte revalida **cada
salto**, no solo el primero —el conector sigue redirecciones, así que un 302
hacia dentro sería el agujero de vuelta—, y **fija la IP validada** conservando
el nombre para el TLS, lo que cierra la ventana del *DNS rebinding*. Un gate de
arquitectura falla si aparece un cliente HTTP construido a mano fuera de ahí.

Hay un escape configurado para las instalaciones con el IdP o el ERP en la red
interna, porque negarlo obligaría a apagar el guard entero.

---

## 15. Cuánto se guarda cada cosa, y cuándo no se puede borrar

### Retención con borrado automático

Guardar todo para siempre no es prudencia: es incumplimiento. El RGPD exige no
conservar datos personales más de lo necesario, y una base que solo crece acaba
costando más en copias de seguridad que en servidores.

La retención (CRM-07.03.01.01) se declara **por clase de dato**, y cada servicio
declara las suyas con su modelo y su campo de fecha. Ese campo importa: **no
siempre es la fecha de creación**. Una actividad se retiene desde que se
completó, porque contar desde la creación borraría una tarea abierta de hace
tres años que sigue siendo lo único pendiente de ese cliente.

Tres decisiones que protegen del error caro:

- **No decidir no puede significar destruir.** Todas las clases se declaran con
  cero días, que significa «indefinidamente». El plazo lo fija el tenant, que es
  quien conoce su obligación: los plazos de un fabricante de automoción no son
  los de una agencia de marketing, y acertar por él sería destruir datos ajenos
  con una suposición.
- **Simula por defecto**, como la importación masiva. Lo que enseña cuántas
  filas se va a llevar por delante hay que poder verlo antes, no después.
- **Se comprueba al declarar la clase**, no al purgar, que el modelo tiene los
  campos que dice usar. Descubrirlo al purgar sería un error en mitad de una
  tarea nocturna, con la mitad de las clases ya procesadas, nadie delante y la
  clase rota sin purgar en silencio hasta que alguien mire los logs.

Cada purga queda **auditada con su recuento**: el día que faltan diez mil filas,
la pregunta es si las borró la retención o alguien, y sin el apunte no hay
respuesta.

### Bloqueo legal

Va junto a la retención porque separarlos es un problema legal (CRM-07.03.01.06):
una purga que no consulta los bloqueos borra, puntualmente y sin que nadie se
entere, justo la prueba que un juzgado acaba de pedir.

El ámbito va de lo general a lo concreto: sin objeto cubre todo lo del servicio;
con objeto, ese tipo; con objeto e identificador, ese registro — que es el caso
real, la cuenta y el histórico del cliente con el que hay pleito.

Poner y levantar un bloqueo **exigen motivo escrito**, y la fila no se borra al
levantarlo. Un bloqueo puede durar años y sobrevivir a quien lo puso: «¿por qué
no se puede borrar esto?» es una pregunta que alguien hará cuando esa persona ya
no esté, y «¿desde cuándo y hasta cuándo estuvo bloqueado?» hay que poder
contestarla después.

La purga por retención **se abstiene entera** ante un bloqueo que cubra su clase.
Afinar cuál de cien mil registros cubre el bloqueo cuesta más que esperar a que
se levante, y equivocarse en esa criba borra justo lo que había que conservar.
La papelera, en cambio, lo consulta **registro a registro**: un bloqueo sobre la
cuenta de un cliente con pleito no debe impedir purgar el resto, que puede ser
el 99 %.

Los bloqueos y las políticas viven **en el esquema del servicio que guarda el
dato**, no en una tabla central. Los permisos de base de datos impiden —a
propósito— que un servicio escriba en el esquema de otro, así que un bloqueo
central no lo podría consultar la purga de `party`. Uno que cubra todo el tenant
se pone en cada servicio, igual que con la papelera.

---

## 16. Relaciones entre objetos del modelo

Un modelo de datos extensible no es una lista de objetos con campos: es un
**grafo**. Sin declarar las relaciones (CRM-00.04.01.03), cada una vive escondida
dentro de un campo de tipo referencia y nadie puede responder a «¿qué se rompe si
borro esta cuenta?» — que es justo la pregunta que hay que contestar **antes** de
borrarla.

Los tipos no son etiquetas. Cada uno impone reglas, y validarlas al declarar la
relación es lo que evita descubrirlas cuando ya hay cien mil registros, momento
en el que corregirlas deja de ser configuración y pasa a ser una migración:

- **Maestro-detalle** es siempre 1:N, obligatoria y en cascada. No son opciones:
  es lo que la palabra significa. El detalle **no existe** sin su maestro —se
  borra con él y hereda su visibilidad—, y confundirla con una referencia deja
  líneas de pedido huérfanas apuntando a un pedido que ya no está.
- **Jerárquica** va de un objeto a sí mismo, nunca es N:M —cada nodo tendría
  varios padres y consolidar daría totales repetidos— y **no borra en cascada**,
  porque borrar la matriz se llevaría el grupo entero sin que nadie lo haya
  pedido.
- **Polimórfica** necesita al menos dos destinos (con uno es una referencia
  normal), no puede ser N:M —la tabla intermedia tendría que apuntar a tipos
  distintos por fila— y no cascadea, porque habría que hacerlo sobre tipos
  distintos, cada uno con sus reglas.
- **N:M** necesita un objeto intermedio, y ahí es donde viven los datos de la
  propia relación: el rol de un contacto en una cuenta, la fecha desde la que un
  socio lo es.

La validación devuelve **todos** los problemas, no el primero: quien modela un
objeto agradece ver de una vez las tres cosas que no encajan en vez de corregir
una, reenviar y descubrir la siguiente.

`GET /metadata/objetos/{objeto}/plan-de-borrado` dice qué arrastra, qué
desvincula y qué impide borrar, con **lo que impide primero** — enterrarlo entre
veinte cascadas hace que se lea el listado y se pase por alto justo lo que
bloquea. Solo mira las relaciones declaradas, y se dice: lo que un servicio
arrastre por su cuenta no sale ahí.

La comprobación de ciclos vive aquí y la usa `party` para la jerarquía de
cuentas, pasándole cómo subir por los padres. Tenerla escrita dos veces
garantizaría que un día una de las dos se corrigiera y la otra no.

---

## 17. Explotación y reporting: contecintelligence, sin salir del CRM

**Es un requisito, no una opción** (restricción transversal RT-4). Informes,
cuadros de mando, consultas analíticas y preguntas en lenguaje natural **no se
reimplementan aquí**: los resuelve `contecintelligence`, consumido de forma
frontless. contecrm pone la pantalla y el contexto; las consultas las responde su
API delegada. El usuario no sale nunca de contecrm.

### Por qué así

Un motor de informes serio —constructor sin código, uniones entre fuentes,
filtros cruzados, campos calculados, instantáneas históricas, respeto de la
seguridad del dato en cada fila— es un producto entero. Ya existe uno en casa,
con su modelo semántico, su chat, sus visualizaciones y su API pensada
explícitamente para integrarse en otra aplicación. Escribir un segundo motor aquí
no daría nada que no exista y garantizaría dos verdades distintas: el mismo dato
respondería una cosa en el CRM y otra en el panel de dirección.

Y la decisión se incumple sola si no se vigila. No hace falta mala fe: basta que
alguien necesite «un informe rápido» y escriba un generador de SQL en un rincón.
Por eso RT-4 tiene **gate**: `tests/unit/test_explotacion_delegada.py` comprueba
que la restricción sigue declarada, que cada capacidad de informes y de cuadros
de mando dice que se delega —sin esa marca, quien la coja para implementarla lee
un enunciado que pide construir un motor—, y que no aparece ningún módulo con
pinta de motor propio ni SQL compuesto por interpolación de texto.

### Cómo se conecta

`contecintelligence` publica su contrato y define dos pasos deliberadamente
separados, y esa separación es la parte que importa:

1. **En el servidor de contecrm**, la credencial de aplicación se canja por un
   **token de usuario final** que nombra el tenant, la persona, su rol y sus
   alcances, y dura minutos (CRM-05.01.04.01). La credencial de aplicación puede
   representar a *todos* los tenants: si bajara al navegador sería la llave de
   todos.
2. **En la pantalla**, ese token corto es el único que viaja
   (CRM-05.01.04.03).

Cada tenant de contecrm se corresponde con una organización de
`contecintelligence`, creada al provisionar (CRM-05.01.04.02). Quién pertenece a
qué **lo dice el servidor**, no el navegador: si lo dijera un identificador en la
URL, el aislamiento valdría lo que valga el JavaScript de esa pantalla.

### Lo que no se delega

**La política de acceso sigue siendo del CRM.** Una consulta analítica no puede
devolver más de lo que ese usuario ve en la ficha (CRM-05.01.04.05): los
permisos, las reglas de compartición y el enmascaramiento por sensibilidad se
propagan en el token y en la descripción de la fuente. Una explotación que ve
más que la aplicación es una fuga con otro nombre.

**Y el CRM no depende de ella para operar** (CRM-05.01.04.08). Si
`contecintelligence` no responde, la pantalla de explotación lo dice y el resto
del CRM sigue funcionando. Atar el alta de un cliente a que el motor analítico
esté vivo sería convertir una herramienta de consulta en una dependencia crítica.

Queda declarado en el catálogo como el grupo **CRM-05.01.04**, de la fase 2 —
junto con el resto de la explotación, que es cuando el CRM tiene datos que
merezca la pena explotar.
