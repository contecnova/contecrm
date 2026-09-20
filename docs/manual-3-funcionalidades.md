# Manual III — Referencia funcional

Qué hace hoy contecrm, capacidad por capacidad, con el identificador del
[catálogo funcional](catalogo/catalogo.yaml) entre paréntesis. Ese identificador
es la clave de trazabilidad: desde él se llega al código que lo implementa y a la
prueba que lo sostiene.

> **Qué significa que algo esté aquí.** Solo se documenta lo que está
> **implementado y probado**. Lo que está a medias se dice explícitamente en
> [«Lo que está a medias»](#lo-que-esta-a-medias), y lo que no está no aparece:
> el estado completo de las 555 capacidades está en
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
| `CRM-00.05.02.04` Reglas de compartición | Las cinco vías (propietario, jerarquía, equipo, criterio y manual con caducidad), el explicador y su API | **Aplicarlas en los listados**: hoy devuelven el veredicto y la explicación de un registro, pero `party` y `sales` todavía no filtran sus consultas con ellas |
| `CRM-06.01.01.05` Gestión documental | Subida, versionado, deduplicación por contenido, enlaces firmados y registro de descargas | Carpetas, y el enlace a SharePoint/Drive |
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

### Es una dependencia de despliegue, no una integración opcional

Sin `contecintelligence` no hay explotación. Así que **la pila lo levanta con
ella, o se le da la dirección de uno ya en marcha y alcanzable**
(CRM-05.01.04.10), y eso se comprueba **al arrancar** (CRM-05.01.04.11), no la
primera vez que alguien abre un informe: un fallo descubierto ahí aparece
delante de un usuario, días después de desplegar y lejos de quien puede
arreglarlo.

En la práctica:

```bash
# Levantarlo con la pila
docker compose --profile app --profile bi up

# O usar uno que ya está en marcha, que es lo normal en una instalación
# con varias soluciones de la casa
CI_BASE_URL=http://10.0.0.20:8000 docker compose --profile app up
```

Va en su propio perfil (`bi`) por eso último: quien ya tiene un
`contecintelligence` no debería levantar un segundo, con su base y su
mantenimiento, para acabar teniendo dos modelos semánticos del mismo negocio.

Arrancar en producción **falla** si la explotación está activa y falta la
dirección o la credencial, con el motivo dicho entero. Y si esta instalación de
verdad no va a usar informes, se apaga con `CI_ENABLED=false`: lo que no vale es
tenerla encendida y sin configurar.

Lo que **no** hace es impedir que el CRM arranque si `contecintelligence` no
responde. El CRM operativo no puede depender de la herramienta de consulta:
atar el alta de un cliente a que el motor analítico esté vivo sería convertir
una herramienta en una dependencia crítica. Se avisa bien alto, la explotación
queda degradada y `GET /analitica/estado` lo dice — que es lo que una pantalla
mira antes de ofrecer informes, porque enseñar el botón y que falle al pulsarlo
es peor que decir de entrada que no están disponibles. Quien prefiera lo
contrario lo enciende con `CI_OBLIGATORIO_PARA_ARRANCAR`.

### El servicio `analytics`

Es la puerta, y **no calcula nada**. Guarda a qué organización de
`contecintelligence` corresponde cada tenant —el mapeo es suyo, y es el control
que impide que un token diga pertenecer a un cliente cualquiera—, canja el token
corto, registra qué se ha preguntado y dice si la integración está viva.

Los informes **no pasan por él**: los pide el navegador directamente con ese
token. Eso es lo que hace que la explotación sea frontless de verdad y no un
proxy que reimplementa media API ajena — y de paso, que la carga de una consulta
pesada no atraviese el CRM.

El rol que se manda sale de los permisos que la persona tiene aquí, y se traduce
**a la baja**: ante la duda, el rol que menos ve. Equivocarse hacia arriba en una
herramienta que responde con tablas enteras es enseñar de una vez lo que en el
CRM se ve ficha a ficha.

Queda declarado en el catálogo como el grupo **CRM-05.01.04**, de la fase 2 —
junto con el resto de la explotación, que es cuando el CRM tiene datos que
merezca la pena explotar.

---

## 18. Buscar, sin ver lo de otro

El índice de búsqueda es la tercera vía silenciosa por la que un cliente acaba
viendo el dato de otro, después de la caché y del almacén de ficheros. Y es la
peor de las tres, porque un buscador **está hecho para encontrar**: una fuga aquí
no espera a que alguien acierte con un identificador — le sirve al primero que
teclee «acuerdo marco» los contratos de todos los clientes.

Hay dos formas válidas de evitarlo (CRM-00.01.01.09): **un índice por tenant** o
**un filtro por tenant que imponga el motor**. Lo que no vale es un índice
compartido donde el filtro lo ponga quien consulta: basta una consulta escrita
deprisa para que falte, y el resultado no da error — devuelve de más.

Aquí se hace con la búsqueda de texto de Postgres, y el aislamiento sale de donde
ya está: la tabla del índice lleva `tenant_id`, **RLS la cubre como a cualquier
otra**, el filtro va explícito en cada consulta, y la firma obliga a pasar el
tenant. Tres redes, y ninguna depende de que quien escribe la consulta se
acuerde.

**Por qué Postgres y no un motor aparte.** Un buscador dedicado es otra pieza que
desplegar, vigilar, respaldar y aislar — y el aislamiento habría que construirlo
entero, porque estos motores no traen RLS. Con el volumen de un CRM mediano, el
texto completo de Postgres llega de sobra. El día que no llegue, el protocolo
está ahí para meter otro backend sin tocar a quien lo llama; lo que no se hace es
escribirlo hoy «por si acaso», porque un backend sin usuarios es un backend sin
probar.

Tres detalles que se notan al usarlo:

- **Se indexa al escribir, no de noche.** Quien acaba de crear una cuenta la
  busca a los diez segundos, y un índice con un día de retraso se percibe —con
  razón— como que la búsqueda no funciona. Editar reindexa: si no, sigue
  encontrándose el nombre viejo, que es peor que no encontrar nada.
- **Se acepta lo que la gente escribe de verdad**: comillas para una frase,
  `-palabra` para excluir. Y un paréntesis suelto no revienta — devolver un
  error de sintaxis a quien solo estaba buscando un cliente no tiene sentido.
- **Lo que se borra sale del índice.** Si no, sigue apareciendo y al pincharlo da
  un 404, que es peor que no encontrarlo porque confirma que existe.

La **búsqueda global** —la que mira en todo el CRM a la vez— la compone el
gateway preguntando a cada servicio y ordenando por relevancia. Así ningún
servicio necesita leer el esquema de otro, y el aislamiento de cada índice sigue
siendo el de sus datos. Un servicio que no responda **no hace fallar la
búsqueda**: se devuelve lo que haya y se dice cuáles faltan, porque media
respuesta útil vale más que un error — y ocultar que falta la mitad sería peor
que las dos cosas.

---

## 19. Reintentar sin duplicar, y no pisarse al editar

Dos garantías del contrato de API que estaban escritas y **sin enganchar**, que
es la peor situación posible: el módulo existe, la documentación las promete, y
en la práctica funcionan donde alguien se acordó. Un contrato que vale «en casi
todas partes» no es un contrato — el integrador descubre dónde no vale
reintentando un cobro.

### Idempotencia (CRM-00.02.01.08)

Cualquier escritura acepta la cabecera `Idempotency-Key`. Con ella, repetir la
petición **no repite el trabajo**: se devuelve la misma respuesta de la primera
vez, con el mismo código, y una cabecera `Idempotency-Replayed: true` para que el
cliente pueda distinguir «se ha hecho ahora» de «ya estaba hecho». Esa diferencia
importa al conciliar, y sin la marca es indistinguible.

Se aplica a **todas** las rutas de escritura sin tocar ninguna. Son más de cien:
engancharlo una a una significa que funciona en las que alguien recordó.

Está partido en dos mitades, y la separación **no es un capricho**: el middleware
corre antes de la autenticación, así que ahí todavía no se sabe qué tenant es.
Usar la pista de la cabecera sin verificar habría parecido que funcionaba y
habría sido una fuga — quien mintiera sobre su tenant podría recibir la respuesta
guardada de otro cliente, con su contenido dentro. Así que la clave la reserva
una **dependencia** que depende del principal ya autenticado, y el middleware
solo **captura la respuesta**, que es lo que una dependencia no ve.

Tres decisiones que se notan al usarlo:

- **Sin cabecera no hace nada.** Exigirla siempre rompería a todo cliente que hoy
  funciona, y decidir si una operación se puede reintentar es de quien llama.
- **La misma clave con otro cuerpo se rechaza** con un 409. Es casi siempre un
  error del cliente —reutilizar la clave de una operación para otra—, y
  aceptarlo devolvería la respuesta equivocada.
- **Una operación fallida libera la clave.** Si se guardara el error, el cliente
  que reintenta tras arreglar su problema recibiría para siempre el fallo de la
  primera vez.

Al conectarlo apareció que el módulo **nunca había funcionado**: comprobaba si
había insertado mirando `rowcount`, y con psycopg 3 un `ON CONFLICT DO NOTHING`
devuelve **-1**, que en Python es verdadero. Con eso, la función daba siempre
«la he insertado yo» y no detectaba un duplicado jamás. Llevaba así desde que se
escribió, invisible porque no estaba enganchada a ninguna ruta. Ahora usa
`RETURNING`, que no depende de cómo cuente el driver.

### ETag y If-Match (CRM-00.02.01.09)

Toda respuesta que lleve un campo `version` sale con su cabecera `ETag`. Esa
mitad es automática porque **es mecánica**: si hay versión, el ETag sale de ahí y
no hay decisión que tomar. Dejarlo en cada endpoint daría un recurso que unas
veces devuelve `ETag` y otras no, y un cliente no puede usar `If-Match` contra
eso.

La otra mitad —comprobar el `If-Match` que llega— **no puede ser automática**:
hace falta el objeto cargado para saber su versión actual, y eso solo lo sabe el
endpoint. Se llama con una línea, y un gate vigila que no se olvide.

El ETag es **débil** (`W/"7"`) a propósito: identifica la versión lógica del
registro, no el byte exacto de la representación. Dos peticiones con distinta
proyección de campos son la misma versión del mismo recurso.

Un `If-Match` desfasado responde **409**, no 412: lo que ha pasado es un
conflicto de edición —alguien guardó entre tu lectura y tu escritura—, y el
cliente necesita releer y reintentar, no concluir que su petición era inválida.

---

## 20. Qué campos ve cada quien

El permiso por objeto dice si alguien puede leer cuentas. Este dice **qué
columnas** de una cuenta ve, y en qué estado (CRM-00.05.02.03). Sin ello, dar
acceso de lectura al maestro de clientes es darlo todo —el teléfono del
contacto, la facturación, el identificador fiscal— y la única alternativa
práctica acaba siendo no dar acceso, que es peor para todos.

### Se deriva de la sensibilidad, no de una lista de campos

Cada columna declara la suya **en el modelo**, junto a su definición:

```python
email: Mapped[str | None] = mapped_column(
    String(320), nullable=True, info={"sensibilidad": "personal"}
)
```

Vive ahí para que quien añada una columna sensible vea en la línea de al lado
que sus vecinas la declaran. Una lista campo a campo en otro fichero tendría que
mantenerse a mano y se quedaría desfasada al primer campo nuevo — que entraría
**visible para todos** sin que nadie lo decidiera.

Los cinco niveles van de menos a más: `publico`, `interno`, `confidencial`,
`personal`, `especial` (CRM-07.03.01.05). El orden es lo que permite decir «este
rol ve hasta confidencial» en vez de enumerar niveles.

Un campo sin declarar entra como **`interno`**, no como público. Equivocarse
hacia la discreción se corrige con una línea de configuración; al revés se
corrige con una notificación de brecha.

### Y la política dice qué hace cada rol con cada nivel

| Rol | Ve en claro hasta | Enmascara hasta | Por encima |
|---|---|---|---|
| `usuario` | interno | confidencial | no lo ve |
| `comercial` | confidencial | personal | no lo ve |
| `responsable_ventas` | personal | especial | — |
| `admin` | especial | — | — |

Con **varios roles gana el más permisivo**, igual que con los permisos: los
roles suman, y que añadir un rol quitara visibilidad sería incomprensible para
quien lo administra. Y un rol que la política no menciona no ve nada por encima
de `interno`: un rol nuevo sin configurar no puede nacer viendo los datos
personales de todos los clientes.

El **administrador de plataforma no queda exento**. Su acceso a datos de un
tenant ya está auditado con motivo, y eximirle aquí convertiría ese privilegio en
«ve todo siempre», que es justo lo que la auditoría intenta acotar. Lo que tiene
es el rol con la política más amplia, no una puerta aparte.

### Enmascarar y ocultar no son lo mismo

**Enmascarado** (CRM-00.05.03.03) deja los últimos caracteres: `·····7890`.
Identificable por quien ya conoce el dato —para confirmar que la ficha es la
correcta— e inútil para quien no. Un campo **vacío no se enmascara**: «····»
donde no hay nada hace creer que hay algo escondido.

**Oculto** significa que el campo **no viene** en la respuesta, y la respuesta lo
anuncia en la cabecera `X-Campos-Retenidos`. Devolverlo como `null` sería
indistinguible de un campo sin rellenar, y esa diferencia cambia lo que hace
quien lo recibe: rellenarlo, o pedir permiso.

### Excepciones, y dónde viven

La clasificación por niveles acierta en el 95 %; el 5 % restante son decisiones
que un cliente concreto necesita tomar. Para eso hay excepciones por campo, que
mandan sobre la política en los dos sentidos: pueden ocultar algo que por su
nivel se vería, y abrir algo que por su nivel se ocultaría.

Viven **en el esquema del servicio dueño del dato**, como la papelera o la
retención: una tabla central no la podría consultar el servicio que serializa,
porque los permisos de base de datos se lo impiden.

### También en los filtros, el orden y los agregados

Proyectar solo la salida deja una puerta que no se ve. Quien no puede leer la
facturación de una cuenta la reconstruye entera si se le deja **ordenar** por
ella: basta pedir la lista ascendente y descendente y comparar. Con un **filtro
de rango** lo hace por búsqueda binaria, en una docena de peticiones. Y un
**agregado** es todavía más directo: la suma de una etapa con una sola
oportunidad **es** el importe de esa oportunidad.

Así que la regla es: para **usar** un campo —ordenar, filtrar, agregar— hay que
poder verlo **en claro**. Enmascarado no basta, porque quien ve `·····7890` no
lee el número pero sí lo adivina si puede filtrar por él.

La comprobación vive en el punto central de ordenación, no en cada listado: hay
uno por recurso y el que se olvide es justo el que se explota. Y hay un gate que
falla si un listado ordena sin pasar la proyección — los argumentos son
opcionales en la firma para no romper a quien ya llamaba, y el gate es lo que
impide que esa compatibilidad se convierta en la puerta de atrás.

El error dice **que no se puede**, no por qué. Responder «no puedes ordenar por
facturación porque es confidencial» confirma que el campo existe y que tiene
valor, que es la mitad de lo que quería averiguar quien lo intenta. La razón
completa va al log, donde la ve el operador.

La llamada es explícita en cada endpoint que devuelve datos personales, no magia
en la serialización, y hay un gate que comprueba que no falta. Es deliberado:
enmascarar el campo equivocado en silencio es peor que una llamada olvidada,
porque la llamada olvidada la caza el gate y el enmascarado equivocado no lo caza
nadie hasta que un cliente enseña una pantalla con puntos donde debería haber un
teléfono.

---

## 21. Máquinas de estado, forzadas al escribir

Un campo `estado` sin máquina es una cadena de texto con nombres bonitos
(CRM-00.04.01.07). Funciona mientras todo el mundo use la interfaz; el día que
alguien escribe por API —una integración, una importación, un script de
migración— aparecen oportunidades «ganadas» que nunca pasaron por negociación, y
los informes de conversión dejan de significar nada **sin que nada haya
fallado**.

### La máquina se declara en el código, y eso es deliberado

El código tiene un `if estado == "ganada"` en quince sitios: la lista de estados
posibles **es** parte del programa. Si un tenant pudiera inventarse un estado, la
mitad de esas comparaciones dejarían de acertar y el registro se quedaría en un
limbo que nadie programó.

Lo que un tenant **sí** puede es **restringir**. Quitar una transición que el
código admite es seguro —el código sabe manejar los dos estados, simplemente no
se va a llegar de uno al otro— y es lo que de verdad piden: «aquí una
oportunidad perdida no se reabre». Esa asimetría es la que hace la máquina
configurable sin hacerla frágil. Y cuando una transición está bloqueada por
configuración, el error lo dice: sin eso, quien administra el tenant no sabe si
tiene que cambiar un ajuste o pedir un cambio de producto.

Los objetos **propios del tenant** son el caso distinto: no tienen código
detrás, así que ahí la declaración de metadatos **es** la máquina entera y sí
define los estados.

### Qué codifica una máquina: lo legítimo, no lo ideal

La primera versión de la máquina de leads exigía pasar por «cualificado» antes de
convertir, y las pruebas lo cazaron: **un lead que llega de una feria con el
pedido firmado se convierte en el momento**. Obligar a marcarlo antes como
contactado y cualificado no mejora el dato — produce dos clics de mentira y un
histórico que afirma un seguimiento que no existió.

Forzar el proceso ideal es la forma más rápida de que la gente lo falsee, y
entonces el dato deja de servir para lo que se recogía. La máquina impide lo
imposible —convertir dos veces el mismo lead, reabrir un tenant archivado cuyos
datos ya se destruyeron—, no lo poco ortodoxo.

### Detalles que se notan

- **Los estados finales se declaran**, no se deducen de «no tiene salidas».
  Deducirlos hacía la validación circular: cualquier destino pasaba a ser estado
  válido por el hecho de ser destino, así que una errata en un nombre creaba un
  estado nuevo en vez de fallar.
- **Un estado inventado se distingue de uno prohibido.** Casi siempre es una
  errata o una integración desactualizada, y decir «desconocido» ahorra media
  hora buscando un permiso que no falta.
- **Algunas transiciones exigen motivo** —perder, cancelar, suspender, reabrir—
  porque son las que alguien preguntará meses después, y la respuesta se pierde
  con quien la tomó.
- **Cada transición se audita en el motor**, no en cada sitio que la provoca.
  Una transición sin apunte es un cambio que nadie puede explicar, y son justo
  los que se preguntan. Un cambio al mismo estado no se anota: llenaría el
  historial de ruido y escondería los que sí importan.

El motor es compartido: `tenancy` tenía su propia tabla de transiciones con su
comprobación a mano, y al pasarla al motor ganó lo que le faltaba —restricción
por tenant, auditoría automática y el mismo mensaje de error que el resto del
sistema— sin cambiar una sola de sus reglas.

---

## 22. Las automatizaciones, ejecutándose de verdad

Las reglas se guardaban, se validaban contra una lista cerrada de acciones y se
podían simular. Lo que no pasaba es que hicieran nada: el motor llamaba a unos
ejecutores que **nadie inyectaba**, y la función que dispara las reglas **no la
llamaba nadie** (CRM-00.03.03.03).

### Piden, no escriben

Una automatización que crea una tarea o asigna un lead está pidiendo escribir en
el esquema de otro servicio, y los permisos de base de datos lo impiden — a
propósito, porque es lo que mantiene la propiedad exclusiva del dato. Así que
los ejecutores **emiten comandos** y el servicio dueño los atiende.

Un **comando** no es un evento con otro nombre: un evento dice lo que ha pasado
y no espera nada; un comando pide que pase algo, tiene destinatario único, y
perderlo significa que el trabajo no se hizo. Van por la tabla de salida como
los eventos, así que si la transacción se deshace la orden no sale — lo
contrario daría el caso de una regla creando una tarea por un registro que al
final no se guardó.

La única acción que se ejecuta en el sitio es **llamar a una API externa**: no
hay otro servicio dueño de «internet». Va por el guard de SSRF y con plazo
corto, porque corre dentro de la petición que disparó la regla.

### Lo que un comando puede tocar lo decide el dueño del objeto

Y esta es la parte que importa. Cada servicio declara **qué campos** admite por
comando:

| Objeto | Una regla puede | No puede |
|---|---|---|
| Actividad | crearla entera | — |
| Cuenta | ciclo de vida, clasificación, tier, sector | nombre, NIF, propietario |
| Lead | puntuación, origen, campaña | **estado** |
| Oportunidad | probabilidad, fecha de cierre, descripción | **estado**, importe |

Sin esa lista blanca, quien puede editar reglas podría hacer **por regla lo que
no puede hacer por API**: fijar el propietario de cualquier registro, o cambiar
un estado saltándose la máquina que exige motivo. Sería una escalada de
privilegios disfrazada de configuración. Y la declara el dueño, no quien manda
el comando — por la misma razón por la que un banco no deja que el ordenante
decida qué campos de la cuenta de destino se modifican.

Los campos descartados se registran con nombre. Ignorarlos en silencio haría que
una regla mal configurada «funcionara» sin hacer lo que su autor cree.

### Se disparan con los eventos de dominio

No con una llamada de `party` a `automation`, y por tres razones: ataría sus
despliegues, una caída del motor de reglas impediría dar de alta clientes, y una
automatización no debe retrasar la operación que la dispara — quien guarda una
cuenta espera a que se guarde su cuenta. Con eventos, además, si el motor está
caído las reglas se ejecutan al volver en vez de perderse.

El precio, dicho: entre que se guarda el registro y se ejecuta la regla pasa
alrededor de un segundo. Para «asigna este lead» es irrelevante; lo que tenga
que estar hecho antes de responder al usuario no es una automatización, es una
regla de negocio del propio servicio.

### Lo que no se puede ejecutar entero, no se ofrece

`enviar_correo` estaba en la lista de acciones admitidas y **no había con qué
enviar**. Una regla que lo usara se habría guardado, validado y ejecutado «bien»
sin que saliera ningún correo. Está fuera de la lista hasta que exista el
repartidor de notificaciones, y hay un gate que comprueba que toda acción
declarada tiene ejecutor — declarar una sin él es peor que no declararla.

Y una regla que emita un evento que no está en el catálogo se rechaza: nadie lo
consumiría, así que la regla parecería funcionar sin hacer nada.

---

## 23. Workflows de negocio: aprobaciones, escalados y revisiones (requisito, fases 1–2)

> **Estado honesto: nada de esta sección está construido todavía.** Las dieciséis
> capacidades del grupo `CRM-00.03.05` están en `pendiente`, doce de ellas
> críticas. Esto es el requisito escrito y razonado, no una descripción de
> funcionamiento. Lo que sí existe hoy es el motor sobre el que se van a montar,
> descrito en [Motor de procesos](#motor-de-procesos).

En un CRM el workflow no es una utilidad más. Es donde vive la política de la
empresa: quién puede firmar un descuento, a partir de qué importe hace falta una
segunda firma, qué pasa cuando el que tiene que firmar está de vacaciones y qué
pasa cuando nadie firma en tres días. Si eso no se puede definir sin abrir un
editor de código, la política acaba viviendo en la cabeza de tres personas y en
un hilo de correo.

### Qué se hace distinto respecto a contecflow

En `contecflow-PSA` la pieza existe y funciona, pero está **repartida en tres
sitios que no son el mismo**:

| Pieza | Dónde vive en contecflow | Qué ejecuta |
| --- | --- | --- |
| Motor de procesos | `app/services/bpmn_process_service.py` | Procesos BPMN |
| Motor de aprobaciones | `app/services/approval_engine/` | Aprobaciones, quórum, plazos |
| Diseñador visual | `app/models/workflow_designer.py` | Lienzos, versiones |

Son tres motores con tres modelos de estado, tres sitios donde mirar cuando algo
se queda parado y tres sitios donde arreglarlo. Una aprobación atascada no
aparece en la vista de instancias del proceso, porque el proceso no sabe que
existe.

En contecrm hay **un solo motor**. Una aprobación es un proceso duradero como
cualquier otro: una tarea humana (`CRM-00.03.02.09`) con un temporizador
(`CRM-00.03.02.07`) y una ruta de compensación. Eso no es una decisión estética:

- La bandeja de tareas humanas ya existe, con asignación por rol, delegación y
  plazo. Una aprobación entra ahí sin inventar una bandeja paralela.
- El rescate de instancias atascadas (`CRM-00.03.02.12`) sirve igual para una
  aprobación colgada. No hay que escribir un segundo rescate.
- La vista de instancia con entrada y salida de cada paso
  (`CRM-00.03.02.11`) ya responde «¿por dónde va esto?» sin una consulta
  distinta para las aprobaciones.
- Los límites por tenant (`CRM-00.03.02.16`) se aplican solos.

Lo que sí se porta de contecflow es lo que allí está bien resuelto y no depende
de su arquitectura: el cálculo de quórum y delegación de
`approval_engine/requests.py`, los plazos de `timeouts.py`, la simulación de
`workflows.py` y el modelo de versiones borrador/publicado/archivado de
`workflow_designer.py`. Está anotado capacidad a capacidad en el campo
`reutiliza` del catálogo, para que no se reescriba por descuido.

### El lienzo **es** la definición

`CRM-00.03.05.01` y `CRM-00.03.05.02` dicen la misma cosa desde dos lados, y es
la decisión que más consecuencias tiene.

Lo habitual es tener una definición en JSON y, al lado, un dibujo que la
documenta. En cuanto alguien toca el JSON, el dibujo miente, y como el dibujo es
lo que mira negocio, negocio trabaja sobre algo falso.

Aquí el gráfico y el texto son **dos vistas de la misma estructura**. Se edita
arrastrando nodos o se edita el YAML, y no hay conversión con pérdida entre una
y otra: la posición de los nodos se guarda como metadato del nodo, no como un
fichero de dibujo aparte. Un cambio en el YAML mueve el gráfico y al revés.

El coste de esta decisión, dicho por delante: obliga a que **todo** lo
expresable en el motor sea expresable en el lienzo. No se puede añadir un tipo
de paso que solo se configure por código, porque entonces el gráfico volvería a
mentir. Es una restricción permanente sobre el motor, no una tarea que se
termina.

### Validar y simular antes de publicar, no después

`CRM-00.03.05.03` valida la estructura: nodos a los que no llega ninguna ruta,
ciclos sin condición de salida, ramas que no apuntan a nada, tareas humanas cuya
regla de asignación no puede resolver a nadie en este tenant. Es la clase de
error que, sin validación previa, se descubre con una instancia real parada y un
cliente esperando.

`CRM-00.03.05.04` va más allá y es lo que de verdad cambia cómo se trabaja:
**simular con datos reales**. Se elige una oportunidad concreta que ya existe y
el sistema dice qué ruta habría seguido, quién habría tenido que aprobar y
cuánto habría tardado con los plazos configurados —sin ejecutar nada, sin
notificar a nadie, sin tocar el registro.

Quien define la política puede así responder «¿y si subo el umbral a 15.000?»
probándolo contra las últimas doscientas oportunidades, en vez de publicándolo y
esperando a ver qué pasa.

### Versionado: las instancias en vuelo no cambian de reglas

`CRM-00.03.05.05`. Borrador, publicado, archivado. Y la regla que importa: una
instancia que empezó con la versión 3 **termina con la versión 3**, aunque se
publique la 4 mientras corre.

Lo contrario —que todas las instancias salten a la versión nueva— parece más
limpio y es indefendible: alguien aprobó un paso bajo unas condiciones y el paso
siguiente se evaluaría con otras. Cuando alguien pregunte por qué se aprobó
aquello, la definición que se le enseñe tiene que ser la que estuvo vigente.

### Aprobaciones: quién, cuántos y qué pasa si no contestan

- **Cadena y paralelo con quórum configurable** (`CRM-00.03.05.06`): todos,
  mayoría, cualquiera, N de M. Cuatro modos porque los cuatro se usan; ofrecer
  solo «todos» obliga a modelar el resto con ramas y el gráfico se vuelve
  ilegible.
- **Aprobador resuelto por regla** (`CRM-00.03.05.07`): jerarquía de mando,
  importe, unidad de negocio, rol, o un campo del propio registro. Nunca una
  persona escrita a mano en la definición: el día que esa persona se va, todos
  los flujos que la nombran se rompen a la vez.
- **Delegación y sustitución por ausencia** (`CRM-00.03.05.08`) con vigencia. Y
  la traza guarda **quién decidió de verdad**, no el nombre del titular. Una
  aprobación firmada por un sustituto es válida; una aprobación que parece
  firmada por quien no estaba, no.
- **Escalado** (`CRM-00.03.05.09`) por tiempo, por inactividad y por jerarquía,
  **con aviso antes de escalar**. Escalar sin avisar convierte al sistema en
  algo contra lo que se trabaja: la gente descubre que su decisión se le ha
  quitado. Con aviso, el escalado es una consecuencia anunciada.
- **Reaprobación al cambiar lo aprobado** (`CRM-00.03.05.10`). Un descuento del
  10 % aprobado que se edita al 25 % vuelve a aprobación. Sin esto, la
  aprobación es un trámite que se hace pronto y se esquiva después, y todo el
  control es teatro.
- **Aprobación automática bajo umbral** (`CRM-00.03.05.11`), **registrada como
  tal**: consta quién habría tenido que aprobarlo y por qué no hizo falta. Un
  hueco en la traza y una aprobación automática se parecen demasiado como para
  no distinguirlos explícitamente.

### Decidir donde está la gente

`CRM-00.03.05.12`: aprobar o rechazar desde el correo o el móvil, sin entrar al
CRM, con **enlace firmado de un solo uso y con caducidad**. Un comercial de
visita no abre el CRM para desbloquear un descuento; si la única forma de
decidir es entrar, la decisión se retrasa hasta la noche.

Firmado y de un solo uso porque el enlace viaja por correo: sin firma, cualquiera
que lo reenvíe aprueba; sin un solo uso, el mismo enlace vale para la siguiente
vez que se pida lo mismo.

`CRM-00.03.05.13` es la otra mitad: una **bandeja única** de todo lo que me toca
decidir, con el contexto suficiente en la propia bandeja —importe, margen,
cliente, qué se pide y por qué— para decidir sin abrir el registro. Una bandeja
que obliga a abrir cada elemento no ahorra nada.

### Ver la instancia sobre el gráfico, y medir el flujo

`CRM-00.03.05.14`: el estado de una instancia se enseña **sobre el mismo lienzo**
que se dibujó, con el camino recorrido marcado, el nodo actual y lo que queda.
Es la consecuencia natural de que el lienzo sea la definición: si lo fuera solo a
medias, haría falta una segunda pantalla que contase lo mismo de otra forma.

`CRM-00.03.05.16`, en `analytics` y por tanto resuelto vía contecintelligence
([sección 17](#17-explotación-y-reporting-contecintelligence-sin-salir-del-crm)):
dónde se atasca el flujo, cuánto tarda cada paso y quién es el cuello de
botella. Sin esta medida, los plazos se ajustan por intuición.

Y `CRM-00.03.05.15`, plantillas por sector clonables: nadie debería empezar un
flujo de aprobación de descuentos desde un lienzo vacío.

### Qué falta, y qué ya está

Una dependencia real y una que no lo es, dichas ahora para no descubrirlas a
mitad:

1. `CRM-00.03.05.12` (decidir desde el correo) **no se puede entregar** hasta que
   exista el repartidor de notificaciones, el mismo que falta para
   `enviar_correo` en las automatizaciones. Ambas cosas se destraban a la vez, y
   hasta entonces la capacidad se queda en `pendiente` aunque el resto del grupo
   avance.
2. La resolución de aprobador por jerarquía (`CRM-00.03.05.07`) **no bloquea
   nada**: la jerarquía de mando ya existe. Es `superior_id` en la membresía del
   tenant (`services/identity/modelos.py`), que es de donde sale la visibilidad
   ascendente de `CRM-00.05.02.02`, y está en la membresía y no en el usuario
   porque la misma persona puede ser responsable en un tenant y colaborador en
   otro. La detección de ciclos está en `crmcore/datos/jerarquia.py`.

---

## 24. Muchos registros de una vez, y lo que tarda más que una petición

Dos capacidades que se entregan juntas porque la una sin la otra deja media
promesa: **operaciones masivas** (`CRM-00.02.01.11`) y **API asíncrona**
(`CRM-00.02.01.12`).

### El informe parcial es el producto

Un lote de diez mil filas con noventa mal no es un fallo: es un martes. Lo que
no puede pasar es que esas noventa impidan escribir las 9.910 buenas, ni que el
informe diga una cosa y la base tenga otra.

```
POST /api/v1/cuentas/masivo
{ "operacion": "upsert", "elementos": [ … ] }

207 Multi-Status
{ "total": 10000, "creados": 8110, "actualizados": 1800, "borrados": 0,
  "omitidos": 0, "fallidos": 90,
  "errores": [ { "fila": 412, "motivo": "…", "codigo": "party.nif_invalido" }, … ],
  "errores_no_mostrados": 0 }
```

Tres decisiones dentro de esa respuesta:

- **Un punto de guardado por elemento.** Sin él, la fila 4.000 que viola una
  restricción aborta la transacción entera de Postgres y las 3.999 anteriores
  desaparecen, mientras el informe sigue diciendo que se crearon. Un `SAVEPOINT`
  por fila cuesta, y es exactamente lo que se paga por que el informe no mienta.
- **La fila es la del fichero, no la del trozo.** Quien va a corregir está
  mirando su hoja de cálculo; decirle «fila 12 de la tanda 3» le hace corregir
  la línea equivocada.
- **207 también cuando todo va bien.** El cliente lee el informe siempre igual y
  no tiene que tratar dos formas distintas de éxito.

### Lo masivo no puede hacer más que lo individual

Es la regla que gobierna todo este capítulo, y la que decidió qué NO se ofrece.

Cada operación en lote valida con el **mismo esquema Pydantic** y llama a la
**misma función de servicio** que el alta de una en una. Escribir directo en la
tabla —que es como se suele hacer, porque es más rápido— se salta la detección
de duplicados, la normalización del teléfono, el recálculo de calidad, la
auditoría, el índice de búsqueda y el evento de dominio. El resultado es un
maestro con diez mil fichas que ninguna pantalla habría dejado guardar, y un
buscador que no las encuentra.

De ahí salen tres ausencias deliberadas:

| Recurso | Ofrece | No ofrece, y por qué |
|---|---|---|
| Cuentas | crear, actualizar, upsert, borrar | — |
| Contactos | crear | **upsert**: no hay clave fiable para una persona (el correo se comparte, cambia de empresa y se reutiliza). **borrar**: la API no tiene `DELETE /contactos/{id}`; ofrecerlo en lote daría al camino masivo una puerta que el individual no tiene |
| Leads | crear | **upsert**: un lead duplicado se detecta, no se pisa. El de la feria de marzo y el del formulario de octubre son dos intenciones de compra y valen como dos |
| Oportunidades | crear, actualizar | **borrar**: una oportunidad se cierra como perdida. Su valor está en que consten las que no salieron |

El upsert de cuenta busca **primero por identificador fiscal y después por
nombre**, en ese orden porque un NIF identifica y un nombre solo se parece. Al
revés, dos sociedades del mismo grupo con nombre casi igual se fundirían sin que
nadie lo pidiera.

Y los permisos son literalmente los de las rutas individuales. Hay un gate que
lo comprueba leyendo los `exige_permiso(...)` del propio `api.py`, para que no
envejezca: si mañana alguien inventa aquí un permiso que ninguna ruta usa, la
suite falla.

### Pasado el tope, se cambia de camino

Hasta `BULK_MAX_ITEMS` (1.000 por defecto) el lote se ejecuta en la petición.
Por encima se responde **413** —no 429— con la ruta exacta del camino que sí lo
acepta:

```
413 Content Too Large
{ "error_code": "masivo.lote_excesivo",
  "detalle": { "maximo": 1000, "recibidos": 50000,
               "alternativa": "POST /cuentas/masivo?modo=asincrono" } }
```

El 413 y el 429 no son intercambiables, y la diferencia es operativa: un 429 le
dice al cliente **espera y reintenta**, y reintentar el mismo lote de cincuenta
mil dentro de un minuto volverá a fallar, para siempre. Esto se corrigió también
en el middleware de tamaño de cuerpo, que devolvía un 422 por lo mismo.

### El trabajo asíncrono: id, sondeo, reanudación y aviso

```
POST /api/v1/cuentas/masivo?modo=asincrono   →  202 Accepted
                                                Location: /trabajos/{id}
GET  /api/v1/trabajos/{id}                   →  progreso (+ Retry-After: 2)
GET  /api/v1/trabajos/{id}/errores           →  el informe parcial completo
POST /api/v1/trabajos/{id}/cancelar          →  para en cuanto termine la tanda
```

**El cursor es lo que hace que esto sea un trabajo y no una barra de progreso.**
No es un contador para pintar un porcentaje: es el índice del siguiente elemento
pendiente, y se confirma con commit al final de cada tanda, en la **misma
transacción** que las filas que esa tanda escribió. Si el worker muere a mitad de
una importación de cincuenta mil, otro la retoma en la 31.200 — sin repetir las
31.200 primeras ni saltarse ninguna. Los eventos de dominio van en ese mismo
commit, así que o avanza el cursor y salen los eventos, o no avanza ninguno.

Y los eventos de una fila que falla **se descartan con ella**: un
`account.created` de una cuenta cuyo punto de guardado se deshizo es un evento
que ningún consumidor podrá resolver.

Lo demás, en corto:

- **`Retry-After` mientras no ha terminado.** Sin él cada cliente elige su
  intervalo, y el que elige 200 ms convierte una importación en una denegación
  de servicio contra su propio CRM.
- **`porcentaje: null` cuando no se sabe el total**, no `0`. Son cosas distintas,
  y confundirlas deja una barra clavada en el cero mientras el trabajo avanza.
- **Cancelar termina la tanda en curso.** Interrumpirla a mitad dejaría sus
  filas escritas y el cursor sin avanzar, y al reanudar se volverían a escribir.
  Una importación cancelada a la mitad ha metido media importación, y eso se
  dice.
- **Los errores se recortan a 500 guardados; el recuento es exacto siempre.** La
  respuesta de `/errores` dice `recortado: true` cuando lo está, porque un
  fichero con mil errores del que se guardaron quinientos parece un fichero con
  quinientos, y se corrige a medias.
- **Bloqueo con caducidad.** Un worker muerto no retiene un trabajo: otro lo
  recupera cuando el bloqueo vence, y en un apagado limpio lo suelta al recibir
  `SIGTERM` en vez de dejarlo esperando a que caduque.
- **La URL de aviso se valida al aceptar el trabajo**, no al dispararlo. La
  llamada la hace el worker desde la red interna, así que sin el guard de
  salidas este campo sería un SSRF con persistencia; y validarla tarde dejaría
  al cliente irse creyendo que le avisarían. El aviso va firmado con **el mismo
  HMAC que los webhooks** — una sola implementación, en
  `crmcore/security/firma.py`, para que quien ya verifica webhooks no tenga que
  escribir una segunda comprobación.
- **Retención.** Un trabajo terminado se borra a las 72 horas
  (`TRABAJO_RETENCION_H`). Guarda la entrada completa, que en una importación son
  los datos que subió el cliente: conservarla «por si acaso» pasado el plazo es
  justo lo que el plazo impide. Un trabajo **vivo** nunca se purga, aunque haya
  caducado.

### La tabla vive en el esquema de cada servicio

No hay un servicio de trabajos. El ejecutor escribe en las tablas de su servicio
dentro de la misma transacción que avanza el cursor, y eso es imposible desde
otro esquema sobre el que no tiene permisos de escritura — ni debería tenerlos.
Así que cada servicio tiene su tabla `trabajos` y su worker
(`python -m services.party.trabajos_worker`), y quien quiera verlos todos los
pide a cada servicio, igual que hace con sus registros.

### Un agujero de despliegue que salió al escribir esto

**El worker del motor de procesos no lo arrancaba nadie.** Existía
(`services/orchestrator/worker.py`), estaba probado y estaba documentado en el
Manual V, y no había un solo contenedor que lo ejecutara. En esa pila, ningún
temporizador de proceso habría vencido nunca, y el síntoma —«las esperas no
saltan»— habría mandado a buscar el fallo al motor, que estaba bien.

Ahora el compose levanta los tres: `orchestrator-worker`, `party-trabajos` y
`sales-trabajos`. Con el healthcheck **desactivado**, que es el detalle que
importa: el de la plantilla comprueba `/health/live` con `curl`, y un worker no
escucha en ningún puerto — se habría quedado `unhealthy` para siempre y
`restart: unless-stopped` lo habría reiniciado en bucle. Y sin aplicar
migraciones, porque las aplica el servicio HTTP del mismo esquema: dos procesos
migrando a la vez es la forma habitual de dejar un `alembic` a medias.

---

## 25. Tablas de decisión: la política de negocio como dato

`CRM-00.03.02.10`. El modelo ya estaba; lo que faltaba era todo lo que hace que
una tabla de decisión sirva para algo más que sustituir un `if` por un JSON.

Una tabla dice cosas como «si el descuento pasa del 25 %, aprueba el director».
La diferencia con escribir esa condición dentro del proceso no es técnica: la
condición del proceso la cambia quien publica el proceso, y **la política de
aprobaciones cambia cada trimestre sin que el flujo cambie**.

### Cinco políticas de aciertos, y por qué hay que declarar una

Sin declararla, dos reglas que casan a la vez dan un resultado que depende del
orden de lectura de la base — y por tanto puede cambiar entre dos ejecuciones
idénticas sin que nadie haya tocado nada.

| Política | Qué hace | Cuándo |
|---|---|---|
| `unica` | Exactamente una debe casar; si casan dos, **error** | Quién aprueba, qué tipo impositivo se aplica: donde una ambigüedad no es aceptable |
| `primera` | Gana la primera por orden de la tabla | Lo habitual: las reglas se leen como una escalera |
| `prioridad` | Gana la de mayor prioridad declarada | Cuando el orden de lectura no es el de importancia |
| `cualquiera` | Pueden casar varias, pero **deben coincidir** en la salida | Varias razones para la misma decisión |
| `todas` | Acumula las salidas de todas las que casen | Etiquetar, avisar a varios |

Con `prioridad`, a igual prioridad gana siempre la primera escrita. El desempate
estable es el punto: sin él, dos ejecuciones idénticas pueden dar cosas
distintas.

### La explicación, no solo el resultado

Una tabla que devuelve «director» y no dice por qué es tan opaca como el `if`
que venía a sustituir. Evaluar devuelve las entradas resueltas, qué reglas
casaron y —lo que de verdad se pregunta— **en qué condición falló cada una que
no casó**:

```json
{ "salidas": { "aprobador": "comercial" }, "por_defecto": true,
  "entradas": { "importe": 1000, "descuento": 5 },
  "reglas": [
    { "nombre": "descuento alto", "caso": false,
      "fallo_en": { "entrada": "descuento", "operador": ">",
                    "esperado": 25, "encontrado": 5 } } ] }
```

`por_defecto: true` dice que no casó nada y se usó el valor por defecto de la
columna. «No casó nada» y «casó la regla que da ese valor» son cosas distintas,
y en una auditoría la diferencia importa.

### El análisis: huecos, solapes y reglas muertas

Es lo que separa una tabla de decisión de una lista de `if`. Antes de publicar
—`POST /tablas-decision/validar`, sin guardar nada— se busca:

- **Huecos**: tramos que ninguna regla cubre. Si además no hay valor por defecto
  ni una regla que case siempre, se marca `sin_red_de_seguridad`: ese hueco deja
  la decisión sin respuesta, y se descubre normalmente con un expediente parado.
- **Solapes**: pares de reglas que pueden casar a la vez. Bajo `unica` es un
  error en cuanto pase.
- **Reglas inalcanzables**: bajo `primera`, la que casa siempre que casaría otra
  anterior es código muerto.

**Lo que el análisis NO hace, dicho por delante:** no es un demostrador. Razona
sobre intervalos numéricos y sobre igualdades de texto —de lo que están hechas
casi todas las tablas reales— y se declara **indeciso** sobre lo demás
(`contiene`, `en` con listas variables, condiciones que comparan contra otra
variable del contexto) en vez de afirmar una cobertura que no puede demostrar.
El informe trae esos casos con nombre y apellidos en `indecidibles`. Un
analizador que dice «completa» cuando no lo sabe es peor que no tenerlo.

También es conservador con los bordes: `<= 1000` y `> 1000` se declaran
solapadas aunque solo se toquen en el punto exacto. Un falso positivo se
descarta mirando; un falso negativo se descubre en producción.

### El paso `tabla` en el motor de procesos

```yaml
quien_aprueba:
  tipo: tabla
  tabla: aprobacion_descuento
  segun: aprobador          # por qué salida se enruta
  rutas:
    director: pedir_firma_direccion
    comercial: continuar
```

Las salidas quedan en las variables de la instancia, y **la explicación
completa** queda en `_quien_aprueba_explicacion`. Sin eso, dentro de seis meses
nadie podrá decir por qué aquel expediente fue al director: la tabla ya habrá
cambiado.

Dos negativas deliberadas: una salida sin ruta **falla** en vez de seguir recto
—casi siempre es que alguien añadió un valor a la tabla y no la rama que le
toca, y seguir recto lo escondería—, y una tabla desactivada no se evalúa
devolviendo su valor por defecto, porque eso haría que un proceso siguiera
funcionando «bien» con la política equivocada.

Y la validación de la definición rechaza publicar un paso de tabla sin tabla, o
con rutas y sin `segun`: sin `segun` el paso no sabría con qué comparar las
rutas y elegiría siempre la rama de escape.

---

## 26. Trazas distribuidas: del pico de latencia a la línea de log

`CRM-00.06.01.03`. El contexto de traza ya viajaba —el middleware leía
`traceparent`, lo propagaba y lo metía en cada línea de log—. Lo que faltaba era
el **exportador**: mandar los tramos a un colector para ver dónde se fue el
tiempo entre cinco servicios, que es la pregunta que los logs no contestan.

### Encenderlas sin el paquete impide arrancar

Es la decisión central y conviene entenderla antes que nada. OpenTelemetry es un
extra opcional (`requirements-otel.txt`): el SDK y el exportador suman unos
veinte megabytes y varias dependencias transitivas, y la mayoría de
instalaciones no tienen colector.

Pero si se pone `TRACING_ENABLED=true` **sin** el paquete, el servicio no
arranca y dice las dos salidas: instalarlo o apagarlo. Lo contrario —arrancar
con las trazas apagadas en silencio porque falta una dependencia— es el fallo
que se descubre el día que hace falta la traza y no está. `TRACING_ENABLED=true`
es una promesa; si no se puede cumplir, hay que decirlo cuando se hace.

Apagadas, el coste es cero: no hay un solo `import opentelemetry` en el camino
caliente. `span()` devuelve un contexto vacío. Una biblioteca de observabilidad
que penaliza a quien no la usa acaba desactivada por otro motivo.

### Qué se traza

- **La petición HTTP**, que es la unidad que el usuario percibe.
- **Cada paso de un proceso**, con la clave del proceso, la instancia y el paso.
  Una orquestación que tarda dos días no sucede dentro de la llamada que la
  arrancó, y es donde se pierde el tiempo de verdad.
- **Toda salida de red**, porque se inyecta en el guard de salidas
  (`crmcore.red`), que es por donde pasan todas las llamadas del servidor
  incluidas las redirecciones. Esa es la mitad que suele faltar: sin ella cada
  servicio traza su trozo y acabamos con cinco trazas de un salto en vez de una
  de cinco.

### Tres decisiones dentro

**El muestreo respeta a quien empezó la traza** (`ParentBased`). Volver a
muestrear por nuestra cuenta produciría trazas con agujeros —el tramo del
servicio A está y el del B no—, que es peor que no tener traza, porque parece un
fallo del sistema.

**Un `traceparent` puesto a mano no se pisa.** Reenviar una petición conservando
su traza original es un caso legítimo.

**El tracer sale del proveedor que construimos**, no del global de
OpenTelemetry. El global solo se puede fijar una vez por proceso y los intentos
siguientes se ignoran con un aviso; tomándolo del nuestro, los tramos van
siempre al colector configurado aunque otra biblioteca haya fijado el global
antes. Se fija el global igualmente, como mejor esfuerzo, para que una
biblioteca auto-instrumentada emita al mismo sitio.

### La pila de observabilidad, y un hueco que salió al montarla

El perfil `ops` levanta ahora **Tempo** además de Prometheus y Grafana, con los
dos receptores OTLP (HTTP en 4318, gRPC en 4317) publicados en `localhost` para
poder trazar un servicio que se ejecute fuera de compose — que es como se depura
de verdad: el servicio en el IDE y el resto de la pila en contenedores.

```
docker compose --profile app --profile ops up
```

Quien ya tenga colector apunta `OTEL_ENDPOINT` al suyo y no levanta este.

Y el hueco: **el compose montaba `./ops/grafana` como directorio de provisión y
el directorio no existía**. Grafana arrancaba sin ninguna fuente de datos y
había que darlas de alta a mano en cada entorno. Ahora se provisionan
Prometheus y Tempo, enlazadas entre sí: se ve un pico de latencia, se salta a la
traza que lo explica y de ahí al servicio, sin cambiar de pantalla ni copiar
identificadores a mano.

---

## 27. El fuzzing entre tenants, y las tres fugas que encontró

`CRM-00.01.02.05`. Había pruebas de aislamiento, pero eran las rutas que alguien
eligió probar. Eso deja el punto ciego donde más duele: la ruta nueva que nadie
se acordó de añadir a la lista.

La suite (`tests/unit/test_fuzzing_tenant.py`) no tiene lista. Levanta cada
servicio con su factoría de producción, saca de su OpenAPI **todas** las rutas
con un identificador, crea una fila de ese objeto para el tenant A y la pide
como tenant B, con permisos de administrador para que lo que se compruebe sea el
aislamiento y no la autorización. Exige **404**.

Por qué 404 y no 403: un 403 confirma que el registro existe. Enumerando
identificadores, un competidor con cuenta en el mismo sistema puede averiguar
cuántos clientes tiene otro y, con los códigos secuenciales que usan muchos CRM,
hasta su ritmo de altas.

Lo que hace que la suite no se degrade: una ruta cuyo objeto no se puede resolver
**no se ignora en silencio**, se lista y hace fallar la prueba. El día que
alguien añada `/expedientes/{expediente_id}` sin un modelo `Expediente`, la
prueba lo dice en vez de dejar de cubrirlo. Y hay un suelo de cobertura para que
renombrar un parámetro no desactive media suite sin que se note.

### Fuga 1 — el filtro de tenant, envenenado por la caché de sentencias

La más grave encontrada en este proyecto.

El guard del ORM inyecta `with_loader_criteria(modelo, lambda cls: ...)`.
SQLAlchemy compila esos lambdas una vez y los cachea por su objeto de código:
analiza sus **variables de cierre** y las convierte en parámetros ligados, de
modo que el valor viaja en cada ejecución. Un **argumento por defecto** no es
una variable de cierre, no se analiza, y su valor queda horneado en la expresión
cacheada.

El guard usaba `lambda cls, tid=tenant_id: cls.tenant_id == tid`. Consecuencia:
**el primer tenant que consultaba en el proceso fijaba el filtro para todos los
demás, y el segundo veía las filas del primero.**

No se había visto porque cada prueba monta un motor nuevo —y con él una caché de
sentencias nueva— y casi todas usan un solo tenant. En un proceso de API, que
vive días y atiende a muchos tenants, habría filtrado desde el primer minuto.
Las pruebas de regresión (`test_guard_tenant_cache.py`) hacen siempre lo mismo:
consultar con un tenant y después con otro **en el mismo proceso**, con tres
tenants, con `select`, con `get`, con `update` y cruzando modelos distintos.

### Fuga 2 — el worker ejecutaba con una sesión de sistema

El worker de trabajos toma el lote con una sesión de sistema, que es correcto:
hay que mirar los trabajos de todos los tenants para saber cuál toca. Pero
**ejecutaba el trabajo en esa misma sesión**, y una sesión de sistema aparta al
guard a propósito; RLS con `app.current_tenant` vacío tampoco filtra. La red era
exactamente ninguna.

Un trabajo de operación masiva del tenant B con el identificador de una cuenta
del tenant A la habría actualizado. Ahora cada trabajo se ejecuta en una sesión
atada a **su** tenant, y ese identificador sencillamente no existe. La misma
corrección se aplicó al worker del motor de procesos, donde no había fuga
demostrable pero la red tampoco estaba puesta.

Y de paso: **el guard se instalaba solo en la factoría de servicio**, que un
worker nunca llama. Ahora lo instala el propio fabricante de sesiones, así que
cubre API, workers, scripts y pruebas sin que nadie tenga que acordarse.

### Fuga 3 — el subrecurso que respondía 200 donde el recurso responde 404

`GET /accounts/{id}` devolvía 404 para un identificador ajeno y
`GET /accounts/{id}/timeline` devolvía 200 con lista vacía. No filtraba datos
—el guard ya vacía la lista— pero es la misma incoherencia en seis rutas
(timeline, consentimientos, historial de etapas, líneas, explicación de
enrutamiento, historial de instancia, festivos), y es por donde se cuela una
fuga el día que uno de esos subrecursos incluya algo que no cuelgue de una tabla
con `tenant_id`. Todas comprueban ahora el padre primero.

### Y un 500 que la suite destapó de camino

Enmascarar el `id` producía `·······e9be` donde el contrato declara un UUID, y
la respuesta reventaba antes de llegar al cliente. Le pasaba a **toda cuenta de
servicio**: el rol `integracion` no estaba en `politica_sensibilidad`, caía al
comodín —que enmascara hasta `interno`— y se enmascaraba todo, enteros y listas
incluidos. Ninguna integración podía leer una ficha.

Tres correcciones: los campos estructurales (`id`, `tenant_id`, `version`,
fechas y autoría) nunca se enmascaran, porque son metadato del registro y no su
contenido; **solo se enmascara lo que es texto**, porque sobre un número o una
lista el enmascarado produce algo que ya no encaja en su tipo; y los roles de
sistema que faltaban están ahora en la política.

Para un campo numérico de verdad sensible, lo que corresponde es declararlo
`oculto` en la columna y que su esquema lo admita ausente — una decisión
explícita de quien define el objeto, no un efecto lateral de que su rol no
estuviera en una tabla.

---

## 28. Lo que el cliente configura y ahora sí se aplica

Cuatro capacidades que cierran la fase 0, y las cuatro comparten el mismo modo
de fallo: **un ajuste configurado y no aplicado**. El cliente lo configura, lo ve
guardado, y no pasa nada. Nadie lo llama avería porque no hay error.

### Localización por tenant (`CRM-00.01.04.07`)

El idioma, la zona horaria, el formato de fecha, el primer día de la semana y la
moneda funcional ya se guardaban con su jerarquía global → tier → tenant →
unidad → usuario. Faltaba aplicarlos.

Ahora `crmcore.i18n` resuelve las preferencias del contexto y formatea al
**salir**, nunca al guardar: en la base un instante es UTC y un importe es un
número. Guardar «19/09/2026» convierte un dato en una presentación, y el día que
el cliente cambie de formato ya no se puede recuperar.

Tres detalles que importan más de lo que parecen:

- **La fecha se calcula en la zona, no recortando la cadena.** Un instante UTC
  de las 23:30 del día 18 es el 19 en Madrid y el 18 en Nueva York. En un
  vencimiento de SLA, ese día decide si se incumplió.
- **Sin dependencias nuevas.** `zoneinfo` es estándar y el formateo de números
  son veinte líneas. Traer `babel` significaba el CLDR entero —decenas de
  megabytes— para cinco idiomas y tres formatos que aquí decide la
  configuración, no la región.
- **Una zona inválida cae a UTC y avisa.** Un ajuste mal escrito por un
  administrador no puede impedir que salga un correo, pero tampoco puede pasar
  callado, porque entonces nadie lo corrige.

Se aplica en los envíos (el render de plantillas, con el idioma de la plantilla
mandando sobre el del contexto) y se publica en `GET /api/v1/localizacion`, con
**ejemplos que son el contrato**: un frontend comprueba con ellos que su
formateo coincide con el del servidor sin reimplementar la jerarquía.

#### Y un agujero que salió al montarlo: los ajustes no salían de su servicio

`ajustes_runtime` vive en el esquema de **cada** servicio y ninguno lee el de
otro. Un ajuste escrito desde la consola se guardaba solo en el esquema de
`tenancy`, y `party` seguía formateando con el valor de `.env` para siempre.

Peor: el comentario del código decía que las réplicas se enteraban «por el
evento `ajuste.cambiado` del bus». **Ese evento no lo emitía nadie** — solo
existía como acción de auditoría con ese nombre. Ahora se emite de verdad por la
tabla de salida, en la misma transacción que la escritura, y todo servicio lo
consume sin que ninguno tenga que acordarse: lo registra la factoría.

### BYOK / CMEK (`CRM-00.01.04.09`)

Lo que compra un cliente con BYOK no es cifrado —eso ya lo tiene—: compra
**poder apagarlo**. Revoca su clave y sus datos dejan de ser legibles para todo
el mundo, nosotros incluidos, sin depender de que nadie ejecute un borrado ni de
que se purgue una copia de seguridad.

- **Sobre cerrado.** El material del cliente se envuelve con la maestra del
  despliegue. Para descifrar hacen falta las dos: ni una copia de la base sin la
  maestra sirve, ni la maestra sin el sobre.
- **Revocar borra el sobre**, no lo marca. Dejar el material con una bandera
  convierte la garantía en un `UPDATE` de distancia. Y se revocan **todas** las
  versiones: dejar viva una antigua haría que lo cifrado con ella siguiera
  legible y la revocación sería un gesto.
- **Irreversible a propósito.** Exige confirmación explícita y un motivo
  escrito, porque dentro de un año alguien preguntará por qué esos datos no se
  leen. Y no se puede registrar una clave nueva después: aceptarla daría a
  entender que lo revocado se recupera.
- **Ninguna ruta devuelve el material.** Ni a un administrador de plataforma.
  Una API que puede leer la clave del cliente convierte todo el BYOK en
  decoración. Hay una prueba que lo comprueba **sobre el árbol del código**, para
  impedir que alguien escriba esa ruta, no solo que hoy no exista.
- **Genérico.** No hay código de ningún proveedor. El material lo aporta el
  cliente por API o lo trae un gestor externo; enchufar un KMS concreto es
  escribir un proveedor, no tocar esto.

Dicho por delante y sin adornos: **esto no protege del proceso vivo.** Mientras
el servicio corre y la clave está activa, el material está en memoria. BYOK
protege de quien lee el disco, la copia de seguridad o la base parada. Para lo
otro hace falta un HSM.

La clave se replica a todos los servicios por evento, igual que los ajustes y
por la misma razón: si un servicio no la tuviera, seguiría cifrando con la
maestra y revocar no dejaría ilegible nada — el único modo de fallo inaceptable
de esta funcionalidad.

### Cifrado en tránsito y en reposo (`CRM-00.05.03.01`)

`HSTS_MAX_AGE` estaba configurado, documentado, y **no salía en ninguna
respuesta**. Ahora hay un middleware que aplica HSTS y las tres cabeceras
mínimas, y que **rechaza HTTP en claro** cuando el despliegue lo declara.

Se responde 403 y no se redirige, que es la diferencia que importa: una
redirección a HTTPS llega después de que la credencial ya haya viajado en claro,
así que arregla la petición siguiente y no la que importa. La cabecera
`X-Forwarded-Proto` solo se cree si hay proxy de confianza declarado — sin esa
condición, cualquiera la manda y se salta la comprobación entera.

En producción, el arranque **se niega** con la base en claro (`DB_SSLMODE` por
debajo de `require`), sin `ENCRYPTION_KEY`, con HSTS a cero, con `TLS_EXIGIDO`
apagado o con el almacén de adjuntos sin SSL. No es «menos seguro»: es un
despliegue donde cualquiera con acceso a la red lee y modifica los datos de
todos los clientes, y eso no se nota nunca desde dentro.

Y como una garantía declarada y no medida es una frase en un documento,
`scripts/verificar_cifrado.py` la **mide contra el despliegue real**: negocia TLS
y comprueba la versión, comprueba que **rechaza** las versiones viejas —que
negocie 1.3 con un cliente moderno no dice nada si sigue aceptando 1.0 con uno
antiguo, porque el atacante elige el cliente—, comprueba las cabeceras, que HTTP
en claro no se atiende, y le pregunta a la propia conexión de Postgres si está
cifrada.

Lo que ese script **no** comprueba, y lo dice él mismo: el cifrado del disco y
el de las copias. Eso lo da la infraestructura, y su verificación es una lista
del Manual de operación firmada por quien despliega. Afirmar aquí que están
cifrados sería inventárselo.

### Página de estado privada del tenant (`CRM-00.06.01.06`)

`GET /api/v1/estado`. Cuando algo va lento, la primera pregunta del cliente es
«¿somos nosotros o sois vosotros?», y sin respuesta abre un ticket, espera y
desconfía.

Dice, con **sus** datos: si la base responde, cuántos eventos suyos esperan a
salir, si sus webhooks están fallando o desactivados, si está tocando sus
límites —la causa más frecuente de lentitud percibida sin avería— y si su clave
de cifrado está revocada, que es la única forma de que quien vea errores de
descifrado entienda que no es una avería sino una decisión suya.

- **Se calcula en vivo.** Una página cacheada cinco minutos enseña «todo bien»
  mientras el cliente mira una pantalla que no carga, y eso destruye más
  confianza que no tener página.
- **Degradado y caído se distinguen.** Meterlo todo en «con incidencias» obliga
  a llamar igual para saber cuál de las dos cosas está pasando.
- **Solo lo suyo.** Ni cuántos tenants hay, ni cómo van los demás, ni qué
  versión corre cada réplica. Una página de estado que filtra la forma de la
  plataforma es un mapa para quien quiera atacarla, y hay una prueba que busca
  esas filtraciones en la respuesta.

**Se compone, no se calcula en un sitio**, y esto lo decidió el gate de
arquitectura: la primera versión la calculaba entera en `tenancy` consultando de
paso las suscripciones de `eventing`, y el gate la paró con razón — ningún
servicio lee las tablas de otro. Ahora cada servicio registra sus componentes y
publica su página, el gateway pregunta a todos **en paralelo** —en serie, diez
servicios con cinco segundos de plazo son cincuenta segundos de espera justo
cuando algo va mal— y devuelve una sola vista. Un servicio que no responde sale
como caído, sin filtrar el mensaje del error, que lleva host y puerto.

---

## 29. El repartidor de notificaciones, y los dos silencios que tapaba

`CRM-06.02.01.02`. Las notificaciones se creaban, se agrupaban, respetaban la
franja de silencio y se leían en la bandeja. **No salía ninguna del sistema.**

Y al montar el repartidor aparecieron dos silencios más, los dos de la misma
familia: código que decía hacer algo y no lo hacía.

- El ejecutor de automatizaciones emitía `automatizacion.aviso` y su comentario
  decía que «el consumidor de identidad ya sabe traducir esto». **No existía.**
  La acción `notificar` de una regla se guardaba, se validaba, se simulaba, se
  ejecutaba sin error y no producía ningún aviso — el mismo modo de fallo por el
  que `enviar_correo` se había retirado, solo que en este no se había visto.
- `enviar_correo` volvía a la lista de acciones. Ahora sí hay con qué enviar, y
  lo que la sostiene no es una línea en el manual sino el gate que exige que
  toda acción declarada tenga ejecutor, más la prueba de que el evento que emite
  lo recoge alguien.

### Dos transportes, ningún proveedor

Es la decisión que gobierna el módulo entero. No hay código de Twilio, ni de
SendGrid, ni de Firebase. Hay dos transportes y los dos son estándares:

- **SMTP** para el correo. Lo hablan todos los proveedores y también el servidor
  corporativo del cliente que no quiere que su correo salga de su red. Cambiar
  de proveedor son cuatro líneas del `.env`, no un despliegue.
- **HTTP declarativo** para SMS, push y lo que venga. El tenant declara URL,
  método, cabeceras y una plantilla de cuerpo en un ajuste en caliente; el
  sistema la rellena y la manda firmada, por el guard de salidas. Es el mismo
  patrón que el conector de integraciones, que ya lleva en producción en
  `contecweb`.

Con un conector por proveedor, cada cliente con un proveedor distinto es una
versión del producto que hay que mantener, probar y desplegar. Con esto es una
fila de configuración. Hay una prueba que busca nombres de proveedor en el
transporte HTTP, para que eso siga siendo verdad.

El precio del SMTP, dicho: no hay estadísticas de apertura ni de rebote, que sí
dan las APIs propietarias. Cuando haga falta se añadirá un transporte aparte
para quien lo quiera, y se dirá que ata la instalación a ese proveedor.

### Todo intento queda registrado

«No me llegó el aviso» es la incidencia más frecuente de un CRM y la más difícil
de contestar. Sin registro se acaba mirando el log del servidor de correo de
otra empresa, o diciendo «nosotros lo mandamos», que no es una respuesta.

Con `entregas_notificacion` se contesta con hechos: se intentó a las 09:12, el
servidor devolvió «550 mailbox unavailable», no se reintentó porque ese código
es definitivo, y la dirección a la que se mandó fue esa. **La dirección se
guarda aunque esté en la ficha del usuario**, porque la ficha cambia y la
pregunta que se hace después es «¿a qué dirección lo mandasteis?», no «¿cuál
tiene ahora?».

Una fila **por canal**, no una por notificación: un aviso que va por correo y
por SMS puede entregarse por uno y fallar por el otro, y una sola fila obligaría
a elegir cuál de las dos verdades se guarda.

### Reintentar, y saber cuándo no

- **La espera crece con el cuadrado del intento** (1, 4, 9, 16, 25 minutos).
  Lineal se queda corta con un proveedor caído una hora; exponencial se pasa de
  largo —al quinto intento serían dieciséis horas— para un aviso que deja de
  tener valor pasada la tarde.
- **Lo definitivo no se reintenta.** Un destinatario sin teléfono, un `550` de
  buzón inexistente: repetirlo cada cinco minutos llena la cola de algo que
  nunca va a salir. Se marca `descartada` y se dice por qué.
- **A quien ya no está en el tenant no se le manda.** No es un detalle: es lo
  que impide que alguien que se fue de la empresa siga recibiendo movimientos de
  clientes en su correo personal.

### Lo que este repartidor NO hace, y por qué

**No decide a quién avisar.** Quién sigue qué, qué canales quiere y si es de
noche para él ya lo resolvió `crmcore.datos.seguimiento` al crear la
notificación. Mezclarlo aquí habría hecho imposible probar una cosa sin la otra.

**No renderiza plantillas de `tenancy`.** La primera versión lo hacía, y es
acoplamiento entre servicios: las plantillas son de `tenancy` y ningún servicio
lee el esquema de otro. La consecuencia honesta es que **hoy no hay plantilla
por canal** —el mismo texto va al correo y al SMS, recortado a 160 caracteres en
el segundo—. Tenerla exigiría replicar las plantillas a cada esquema como se
hace con los ajustes, y es una capacidad aparte que todavía no está. Decirlo es
mejor que fingir que existe.

**No fuerza el canal salvo cuando se le pide.** `enviar_correo` añade el correo
a lo que el destinatario ya quería, sin quitárselo: sigue viéndolo en la bandeja
además de recibirlo. Y saltarse la preferencia es para el aviso que **tiene** que
salir —una confirmación de pedido, un enlace de aprobación—, no para el de
movimiento, que es justo lo que la preferencia existe para acotar. Abusar de eso
es cómo un sistema de avisos se gana que lo filtren.

El worker es un proceso aparte (`identity-reparto` en el compose), por lo mismo
que los trabajos asíncronos: una tarea en segundo plano muere con el proceso, y
un despliegue a mitad de un lote perdería esos avisos sin que nadie lo supiera.
