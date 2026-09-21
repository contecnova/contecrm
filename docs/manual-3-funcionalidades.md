# Manual III — Referencia funcional

Qué hace hoy contecrm, capacidad por capacidad, con el identificador del
[catálogo funcional](catalogo/catalogo.yaml) entre paréntesis. Ese identificador
es la clave de trazabilidad: desde él se llega al código que lo implementa y a la
prueba que lo sostiene.

> **Qué significa que algo esté aquí.** Solo se documenta lo que está
> **implementado y probado**. Lo que está a medias se dice explícitamente en
> [«Lo que está a medias»](#lo-que-esta-a-medias), y lo que no está no aparece:
> el estado completo de las 631 capacidades está en
> [el estado del catálogo](catalogo/estado.md), que es el recuento vivo.

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
- **ABAC aplicado** (CRM-00.05.02.05 y `.17` a `.21`): políticas guardadas,
  versionadas y editables, evaluadas en la ficha, en el listado y en la
  proyección. Tiene capítulo propio (§40).
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

**Ahora mismo, nada.** Todo lo que consta como hecho cumple su enunciado, tiene
prueba que lo cita y está explicado aquí; lo que no está hecho consta como
pendiente y no aparece.

Esta sección se queda, y no por costumbre: es donde va lo que se entrega a
medias, y tenerla vacía es una afirmación, no una omisión.

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
                              Location: /api/v1/party/trabajos/{id}
GET  /api/v1/party/trabajos/{id}             →  progreso (+ Retry-After: 2)
GET  /api/v1/party/trabajos/{id}/errores     →  el informe parcial completo
POST /api/v1/party/trabajos/{id}/cancelar    →  para en cuanto termine la tanda
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

---

## 30. La compartición, aplicada donde se nota

`CRM-00.05.02.04`. Las cinco vías estaban, se explicaban y se podían consultar
para un registro concreto. Lo que no pasaba es lo único que el usuario nota:
**`GET /accounts` seguía enseñándolo todo**.

Y no era un olvido que se arreglara añadiendo un `WHERE`: las reglas vivían en
el esquema de `identity` y los registros en el de `party`. Ningún servicio lee el
esquema de otro, así que el listado no podía filtrar por ellas ni aunque alguien
lo intentara. La funcionalidad estaba estructuralmente a medias.

### Las tablas se mudan a donde están los datos

Es el mismo patrón que adjuntos, comentarios y retención, y por la misma razón:
una funcionalidad transversal cuyas tablas tienen que estar donde están los
datos que gobierna. Ahora `party` guarda las reglas de `cuenta` y `contacto` en
su esquema, `sales` las de `lead` y `oportunidad` en el suyo, y el filtro se
convierte en un `WHERE` normal.

### Filtrar en SQL, no fila a fila

No es una optimización: es la diferencia entre que funcione y que no. Comprobar
registro a registro rompe la paginación —pides veinte y recibes siete, porque
trece se cayeron por el camino— y hace una consulta por fila.

El precio es que el `WHERE` solo sabe expresar lo que se traduce a SQL, y eso
obligó a una decisión incómoda que conviene entender. Una condición que no se
puede traducir —`usuario.pais`, o un operador sin equivalente— **se omite del
`AND`**, así que la regla comparte de más antes que de menos. Se eligió esa
dirección a conciencia: esconder un registro que alguien sí puede ver produce
una llamada a soporte y una decisión tomada sin un dato; enseñarlo de más
produce lo mismo que la regla ya autorizaba por otra vía. Y se registra en el
log, para que no pase inadvertido.

Lo que **nunca** se hace es inventar una traducción aproximada. `a_sql` devuelve
`None` para lo que no tiene equivalente honesto, y quien llama decide. Una
condición traducida «casi igual» produce un listado que casi acierta, y eso no
se detecta mirándolo.

### El listado y la ficha tienen que decir lo mismo

Son dos implementaciones de la misma regla —una en SQL para el listado, otra en
Python para la ficha— y divergen el día que alguien toca una. Cuando eso pasa,
el listado enseña un registro que la ficha luego niega, y el usuario deja de
fiarse de los dos.

Hay una prueba que las compara sobre los mismos datos, con las cinco vías a la
vez: propia, compartida a mano, de equipo, por regla y ninguna. Si alguna vez
divergen, falla ahí y no en producción.

### Ante la duda, no se enseña

- Sin identidad, la consulta no devuelve nada. Quien llame sin autenticar no
  debería haber llegado, y si llega no ve nada en vez de verlo todo.
- **Un error resolviendo la visibilidad filtra**, no abre. Si la tabla de reglas
  no responde, el listado sale vacío y se registra el fallo.
- Quien tiene el permiso de administrar el objeto no se filtra: un administrador
  que ve media lista no puede administrar nada, y darle una compartición sobre
  todo convertiría la auditoría en ruido. Se decide por permiso explícito y no
  por rol, para que cada tenant monte su propia jerarquía.

### El hueco que queda, dicho

**La vía por jerarquía de mando todavía no aplica en los listados de `party` y
`sales`.** `superior_id` vive en la membresía del tenant, que es de `identity`, y
ningún servicio lee el esquema de otro.

Hoy, un responsable ve en esos listados sus registros, aquellos en cuyo equipo
de cuenta está y lo que le compartan — pero no los de sus subordinados por el
solo hecho de serlo. La ficha sí lo evalúa si quien pregunta le pasa los
subordinados resueltos.

Para cerrarlo hay que replicar la jerarquía a cada servicio, como se replican
los ajustes y la clave del tenant, y es trabajo de la capacidad de jerarquía, no
de esta. Se dice aquí y está anotado también en el código, en
`crmcore/authz/visibilidad.py`, donde alguien lo va a leer antes de preguntarse
por qué su responsable no ve las cuentas de su equipo.

---

## 31. El equipo de cuenta, y dos campos que no hacían nada

`CRM-01.01.01.10`. El propietario es uno; el equipo es quien más trabaja la
cuenta. Sin esta tabla, el técnico que lleva tres años atendiendo a un cliente no
aparece en ningún sitio y su conocimiento se pierde cuando cambia el comercial.

El modelo existía con `rol`, `acceso`, `desde` y `hasta`. Faltaba la API — y,
peor, **dos de esos cuatro campos no los usaba nadie**:

- **`hasta` no caducaba nada.** Quien salió del equipo hace un año seguía viendo
  la cuenta. Una pertenencia con fecha de fin que no caduca no es temporal: es
  permanente con una fecha decorativa.
- **`acceso` no concedía escritura.** Un miembro dado de alta con acceso de
  escritura solo podía leer, y nadie entendía por qué el campo no hacía nada.

Los dos se aplican ahora, en el listado y en la ficha. Con varios roles sobre la
misma cuenta —alguien puede ser KAM y técnico— gana el acceso más amplio: las
vías de compartición suman, nunca restan.

### Decisiones

**El propietario no vive aquí.** Es `owner_id` en la cuenta. Tener dos sitios
donde vive «quién es el dueño» acaba con los dos diciendo cosas distintas. Se
puede registrar a alguien con rol `owner` para dejar constancia de que forma
parte del equipo, pero lo que decide la propiedad sigue siendo la cuenta.

**Los roles son una lista cerrada.** Con texto libre, cada comercial escribe el
suyo y a los tres meses hay «tecnico», «Técnico» y «tec.» conviviendo — y «¿qué
cuentas llevo como técnico?» deja de tener respuesta.

**Repetir el alta renueva.** Es lo que hace quien prorroga a alguien en el
equipo; obligarle a borrar y volver a crear pierde la fecha de alta original.

**El listado devuelve los no vigentes salvo que se pidan solo los de hoy.** Quien
administra el equipo necesita ver al que entra el mes que viene y al que salió
ayer, o no puede corregir una fecha mal puesta.

**Y el alta emite un evento**, porque pertenecer al equipo **da visibilidad**
sobre la cuenta: quien audite quién puede ver qué necesita ese hecho, y sin
evento solo constaría en una tabla que nadie mira.

---

## 32. Calidad del dato: identificadores, relaciones y verificación externa

Cuatro capacidades —`CRM-01.01.01.04`, `.05`, `.06` y `CRM-01.01.04.10`— que
pedían lo mismo con palabras distintas: **mandar un dato fuera y guardar qué
contestaron**. El identificador fiscal contra el registro oficial, la dirección
contra un geocodificador, el correo y el teléfono contra quien sepa decir si
existen.

Escribir cuatro clientes distintos habría sido cuatro veces el mismo código con
cuatro formas de fallar. Hay uno.

### Dos comprobaciones que no son la misma

Esta es la distinción que gobierna todo el capítulo, y confundirla es cómo un
sistema acaba bloqueando facturas porque el servicio del ministerio estaba
caído:

- **De forma**: ¿está bien construido? Es un cálculo. No necesita red, es
  instantáneo y siempre da la misma respuesta. Caza el 90 % de los errores
  reales, que son erratas de tecleo.
- **De existencia**: ¿existe esta empresa con este identificador? Solo lo sabe
  el registro oficial, hay que preguntarle y puede no contestar.

Por eso hay **tres estados y no dos**: `valido`, `invalido` y `desconocido`.
«No comprobado» no es «no válido».

### Identificadores fiscales de diez países, no de uno

Antes solo se validaba el español. Un CRM que opera en tres países y solo
comprueba uno da una falsa sensación de calidad: el maestro parece limpio porque
el 60 % de las fichas ni se comprueban.

Ahora hay algoritmo de dígito de control para España, Portugal, Francia, Italia,
Países Bajos, Bélgica, Alemania, Irlanda, Luxemburgo y Dinamarca, más la
comprobación de formato del IVA de los veintisiete. Las fórmulas están en el
código y no detrás de un servicio porque son algoritmos públicos y estables de
veinte líneas: pedirlas por red añadiría una dependencia, una latencia y un modo
de fallo a un cálculo que no los tiene.

**Lo que no se sabe validar devuelve `None`, no `False`.** Decir «inválido» de
un identificador de un país sin algoritmo bloquearía altas legítimas y dejaría
al cliente sin forma de continuar. Se guarda y queda pendiente de verificar.

Y un error que costó encontrar: la primera versión solo quitaba el prefijo de
país (`ESB12345674`) cuando **no** coincidía con el país declarado — y el caso
normal es justo el contrario. Los identificadores bien escritos en formato
intracomunitario salían inválidos, que es el peor error posible en una
validación: rechaza lo bueno, y quien lo sufre no tiene forma de continuar.
Ahora se prueban las dos lecturas y gana la que valide.

### Un verificador, ninguna integración por proveedor

El tenant declara, por tipo de dato y por país, a dónde llamar y **de qué parte
de la respuesta sale el veredicto**. Es lo que evita un cliente por proveedor:
uno devuelve `{"valid": true}`, otro `{"status": "OK"}` y otro un `200` vacío.

```json
{ "url": "https://registro.example/comprobar",
  "mapeo": { "campo": "resultado.estado", "valido": ["OK", "ACTIVO"] },
  "conservar": { "razon_social": "resultado.nombre" } }
```

Cuatro decisiones dentro:

- **Sin mapeo, un `200` se toma como válido.** Es lo que hacen la mitad de los
  servicios sencillos, y exigir configuración para ese caso los dejaría fuera.
- **Un campo declarado que no está en la respuesta no concluye nada.** O cambió
  el contrato del servicio o el mapeo está mal; afirmar «inválido» sería
  inventárselo.
- **No se conserva nada que no se haya pedido.** La respuesta de un servicio
  externo puede traer datos personales que nadie solicitó, y guardarla entera
  «por si acaso» es exactamente lo que un registro de tratamiento no puede
  justificar.
- **Un fallo del servicio no degrada el dato.** Si el registro no contesta, el
  veredicto anterior se conserva. Poner «desconocido» encima de un «válido»
  porque hoy hubo un timeout convertiría cada incidencia de red en una pérdida
  de información.

La respuesta incluye **siempre** la comprobación de forma, aunque la externa no
concluya: sin ella, un `no_concluyente` parecería que no se sabe nada del
identificador, y sí se sabe si está bien construido.

### Direcciones y geocodificación (`CRM-01.01.01.05`)

Varias direcciones por cuenta o por contacto, con tipo —fiscal, envío,
facturación, visita, postal— y una principal. La que faltaba era la
geocodificación, y sale del mismo verificador con `conservar` apuntando a las
coordenadas. Se guardan
como dos columnas y no como un tipo geográfico para no exigir PostGIS: lo que
hace falta hoy —distancias aproximadas y pintar un mapa— se resuelve con esto.

**Media coordenada no se escribe.** Una latitud sin longitud deja un punto en el
meridiano de Greenwich, que es un sitio muy concreto y casi nunca el correcto.
Y unas coordenadas que no son números se anotan y se descartan.

### Relaciones no jerárquicas

Partner, competidor, proveedor, prescriptor. **No implican pertenencia ni
consolidación**: que A sea partner de B no hace que los números de A sumen en B.
Esa es toda la diferencia con la jerarquía, y por eso son dos tablas.

- **Una sola fila, leída en las dos direcciones.** Guardar las dos obligaría a
  sincronizarlas al editar y al borrar, y el día que una se quede huérfana la
  ficha de una cuenta dice que es partner de otra que no lo dice.
- **La inversa se declara, no se deduce.** No toda relación es simétrica:
  adivinarla produce «es cliente de» donde debería decir «es proveedor de».
- **Relacionar al revés no duplica.** Las dos direcciones son la misma relación;
  crear la simétrica dejaría dos filas diciendo lo mismo y la ficha la enseñaría
  dos veces.
- **`otro` existe con etiqueta libre.** Una lista cerrada sin escape obliga a
  forzar la relación real dentro de un tipo que no es, y entonces la lista deja
  de significar nada.

---

## 33. Actividades: asignar, delegar, recordar y lo que se pasó de plazo

`CRM-01.02.01.02`. El modelo tenía `asignada_a`, `delegada_por`, `recordar_at` y
`recordatorio_enviado` desde el principio. No había operaciones que los usaran
ni **nada que mirara el reloj**, así que un recordatorio programado no avisaba
nunca y una tarea delegada desaparecía de la vista de quien la delegó.

### Delegar no es asignar

Y la diferencia no es cosmética: **quien delega sigue siendo responsable de que
se haga**. Por eso `delegada_por` se conserva, la tarea le sigue apareciendo en
sus vencidas, y el aviso de plazo incumplido le llega también a él.

Sin eso, una tarea delegada desaparece de la vista del que la delegó y nadie
vuelve a mirarla — que es exactamente lo que pasa con las tareas delegadas por
correo.

Asignar, en cambio, **borra** la marca de delegación: pasar una tarea a otra
persona no es delegarla, y dejar el rastro haría que la ficha dijera que alguien
la delegó a quien ya no la tiene.

### Los recordatorios los dispara el reloj, no el usuario

El barrido corre en el worker del servicio, cada minuto. Colgarlo de que alguien
entre en la aplicación haría que avisara justo a quien no hacía falta avisar.

- **La marca de enviado se pone ANTES de emitir.** Si se pusiera después y el
  proceso muriera entre las dos cosas, el aviso saldría otra vez en cada vuelta.
- **Mover la fecha rearma el recordatorio**, aunque ya se hubiera enviado: quien
  aplaza una tarea espera que le avisen otra vez.
- **Un recordatorio en el pasado se rechaza** al programarlo: no avisa de nada y
  deja al usuario creyendo que sí.
- **Una tarea vencida avisa una sola vez.** Un aviso diario de la misma tarea
  enseña a ignorarlos todos.

Y un fallo que encontró la propia prueba: el barrido solo hacía `commit` si
había emitido algo, así que una actividad con recordatorio y **sin asignado** se
marcaba en memoria y la marca se perdía — volvía en cada vuelta para siempre. El
`commit` va ahora por lo tocado, no por lo emitido.

### Lo que faltaba de verdad: que el aviso saliera

Los cuatro eventos —asignada, delegada, recordatorio y vencida— los traduce el
consumidor de `identity` a notificaciones, y de ahí salen por el repartidor
(§29). La prueba de punta a punta recorre el camino entero a propósito: probar
solo el barrido dejaría sin comprobar el eslabón que **ya faltó una vez**, el
consumidor que nadie había escrito.

El aviso de vencida saca los destinatarios de **dos campos distintos** —el
asignado y quien delegó—. La primera versión del consumidor solo sabía leer uno,
y quien delegó no se enteraba.

---

## 34. Los huecos que se han encontrado construyendo, y dónde están ahora

Este capítulo existe porque un hueco documentado en un comentario del código no
lo lee nadie que esté decidiendo qué se hace después. Todo lo que ha aparecido
como limitación real mientras se construía está ahora **en el catálogo, como
capacidad pendiente**, y por tanto sale en la hoja de estado junto al resto.

No es una lista de deseos: son cosas que se descubrieron al terminar otra cosa,
con el motivo por el que no se cerraron entonces.

| Capacidad | Qué falta y por qué no se hizo ya |
|---|---|
| `CRM-00.05.02.12` Replicar la jerarquía de mando | La compartición por jerarquía **no aplica en los listados** de `party` y `sales`: `superior_id` vive en la membresía, que es de `identity`, y ningún servicio lee el esquema de otro. Hoy un responsable ve lo suyo, lo de los equipos en los que está y lo que le compartan, pero no lo de sus subordinados por serlo. Cerrarlo exige replicar la jerarquía como se replican los ajustes y la clave del tenant (§30) |
| `CRM-06.02.01.07` Plantilla de notificación por canal | El repartidor **no renderiza plantillas de `tenancy`** porque son de otro servicio. El mismo texto va al correo y al SMS, recortado a 160 en el segundo. Tenerla exige replicar las plantillas a cada esquema (§29) |
| `CRM-06.02.01.08` Estadísticas de entrega del correo | SMTP no da apertura ni rebote; eso solo lo dan las APIs propietarias. Se hará como transporte aparte **para quien lo quiera**, diciendo que ata la instalación a ese proveedor (§29) |
| `CRM-01.01.01.13` Reverificación periódica | Un veredicto caduca a los 90 días y se vuelve a preguntar **cuando alguien lo pide**. Falta la cola que reverifique sola lo caducado, con su cuota: muchos registros oficiales la tienen, y un barrido sin control la agota en una mañana (§32) |
| `CRM-01.02.01.09` Recordatorios recurrentes | Hoy un recordatorio avisa una vez. Falta el que insiste —«cada día hasta que la cierres»— y la reprogramación automática de la tarea no atendida (§33) |

Y dos cosas que estaban a medias **dentro de lo entregado** y se cerraron al
verlas, en vez de anotarlas:

- `DIAS_VEREDICTO_VIGENTE` y el esquema `VerificacionEntrada` se habían
  declarado y no los usaba nadie. Era exactamente el mismo modo de fallo que
  este manual lleva media docena de capítulos señalando —un campo que existe y
  no hace nada—, así que se implementaron: un veredicto de los últimos 90 días
  no se vuelve a preguntar salvo con `forzar`, y la respuesta dice si viene de
  antes con `desde_cache`.
- El barrido de recordatorios solo confirmaba lo emitido, así que la marca de
  una actividad sin asignado se perdía y volvía en cada vuelta para siempre.

---

## 35. Ejecutar una solicitud de derechos, y poder demostrarlo

`CRM-07.03.01.03`. El registro de la solicitud con su plazo legal ya estaba.
Faltaba lo único que el interesado nota y lo único que un inspector pide:
**hacerlo y poder demostrarlo**.

Una solicitud que se registra, se tramita a mano y se marca resuelta sin
evidencia deja a la empresa exactamente igual que si no tuviera sistema: cuando
llegue la reclamación, la respuesta será «lo hicimos» sin nada detrás.

### Acceso y portabilidad comparten ejecución

El contenido es el mismo; lo que cambia es a quién se entrega y en qué formato,
y eso lo decide quien responde. Se devuelve JSON estructurado, que es lo que el
RGPD llama «de uso común y lectura mecánica».

Tres decisiones:

- **Se buscan todas las fichas de la persona, por identificador y por correo.**
  Una persona puede estar tres veces en el sistema con la misma dirección, y
  resolver la solicitud solo sobre la ficha enlazada dejaría las otras dos
  intactas — que es incumplir, aunque la solicitud figure resuelta.
- **El expediente no lleva metadatos internos.** Al interesado le interesan sus
  datos, no nuestras claves ajenas ni la versión de la fila. Incluirlas
  convierte un expediente legible en un volcado de base de datos, que cumple la
  letra y no el propósito.
- **Una persona que no está en el sistema no es un error.** La respuesta
  correcta es «no tenemos nada suyo»; fingir un error dejaría la solicitud sin
  resolver y el plazo corriendo.

**Y la respuesta dice lo que NO cubre.** `party` no puede leer el esquema de
`sales` ni el de `service`, así que esto son los datos de un servicio. La
respuesta completa exige preguntar a los demás, y el campo `alcance` lo dice en
cada llamada. Devolverlo como si fuera todo sería la forma más silenciosa de
incumplir: el interesado recibiría un expediente incompleto creyendo que es
completo.

### Suprimir es anonimizar, no borrar

Hay datos que la empresa tiene **obligación de conservar** —una factura, un
contrato— aunque el interesado pida la supresión. Lo que se hace es romper el
vínculo con la persona y conservar el hecho económico.

Borrar la fila entera rompería la contabilidad y dejaría huérfanos registros que
sí hay que guardar: sería cambiar un incumplimiento por otro. El identificador
se mantiene para que las referencias desde oportunidades y facturas sigan
apuntando a algo, y queda `anonimizado_at` para que nadie intente «arreglar» el
nombre después creyendo que se perdió por un fallo.

Los consentimientos **se revocan** además de anonimizarse: conservar un
«consintió recibir comercial» de alguien cuya ficha ya no lo identifica
permitiría seguir contándolo como base legal de un envío.

### El bloqueo legal gana sobre el derecho de supresión

Si un juzgado ha pedido conservar esos datos, no se borran. **Y eso no es un
fallo del sistema**: es la ley resolviendo un conflicto entre dos obligaciones.

Se rechaza con el motivo y la referencia del bloqueo, la solicitud queda **en
curso** —no resuelta— y la evidencia dice por qué, para que alguien conteste al
interesado explicando el conflicto. Borrar igualmente destruiría prueba;
callarlo dejaría al responsable sin saber qué contestar.

### La evidencia es una huella, no una copia

Lo que se guarda es **el hash de lo que se entregó**, no lo entregado. Guardar
el expediente sería conservar exactamente los datos que el interesado quiere que
dejemos de tener, que es lo contrario de lo que la solicitud pide.

Con la huella se puede demostrar dentro de dos años que lo entregado fue
exactamente eso y no otra cosa: `comprobar_evidencia()` lo verifica. Guardar
evidencia sin forma de comprobarla es una casilla marcada.

La supresión guarda además la huella **de lo borrado** y la lista de campos que
se vaciaron: demuestra que se borró algo concreto sin conservar precisamente lo
que se pidió borrar.

### Lo que no se automatiza, y por qué

Solo se ejecutan acceso, portabilidad y supresión. Rectificación, oposición y
limitación exigen una decisión humana —qué rectificar, qué tratamiento limitar—
y fingir que se automatizan produciría resoluciones que nadie ha revisado. Se
registran, se les cuenta el plazo y se resuelven a mano, que es lo honesto.

---

## 36. Captura de leads desde fuera: un mecanismo, no tres

`CRM-01.01.03.02` pide «formularios, web, importación, API, eventos, listas,
chat». La importación masiva y la API ya estaban. Faltaba lo que llega **desde
fuera sin credencial de usuario**: el formulario de la web, el chat, la tablet de
una feria.

Y eso es **un solo mecanismo**. Un canal de captura es una definición por tenant
que dice cómo se traduce lo que llega a un lead:

```json
{ "clave": "web", "tipo": "formulario",
  "mapeo": { "email": "correo", "nombre": "nombre_completo" },
  "fijos": { "origen": "formulario web" },
  "obligatorios": ["correo"], "campo_trampa": "apellido2", "max_por_hora": 200 }
```

El formulario de la web manda `nombre_completo`, el chat manda `visitor_name` y
la tablet de la feria manda `NOMBRE`. Con un endpoint por cada uno, cada cliente
nuevo es código nuevo. Con un mapa declarado, es una fila.

### El origen lo pone el canal, no quien rellena

`fijos` existe para eso. Si el origen o la campaña vinieran en la petición,
cualquiera que viera el HTML del formulario podría imputar sus leads a la
campaña que quisiera — y la atribución, que es para lo que sirve todo esto,
dejaría de significar nada.

Por el mismo motivo, un canal **solo puede mapear campos de contacto**. Nada de
`owner_id` ni `campana_id`: una petición pública que puede escribirlos es una
petición pública que se asigna leads.

### Tres protecciones, ninguna opcional

El endpoint es público —tiene que serlo, lo llama el navegador de un
desconocido— pero no anónimo:

- **Clave por canal.** Sin ella, la URL sería un formulario de alta de leads
  abierto a Internet, y un competidor aburrido puede llenar el CRM en una tarde.
  Se guarda **hasheada**: si la base se filtra, las claves de los formularios de
  todos los tenants no vienen en ella.
- **Trampa para robots.** Un campo que un humano nunca rellena porque no lo ve.
  Si viene con contenido se descarta **con un 200 idéntico al de un envío
  bueno**: un error le diría al robot qué tiene que cambiar para la próxima.
- **Tope por hora.** La clave viaja en el HTML de una página pública, así que
  **se filtra siempre**. Rotarla es una operación normal, no una emergencia, y
  el tope es lo que acota el daño mientras tanto.

Y un detalle que no lo parece: el mismo error para «el canal no existe», «está
apagado» y «la clave es mala». Distinguirlos convierte el endpoint en un oráculo
que dice qué canales tiene un tenant.

### Lo descartado se ve

`GET /captura/recepciones` devuelve **también lo que no se creó**, con el motivo
y con lo que llegó. Es lo que convierte «no me llegó el lead del formulario» en
una pregunta contestable: o no llegó, o llegó y se descartó por esto. Sin ello,
la respuesta es mirar el log del servidor web.

Guardar la entrada permite además recuperar a mano un lead descartado por error
—un obligatorio mal configurado— en vez de pedirle al cliente que vuelva a
rellenar el formulario.

### Dos decisiones que conviene entender

**El tenant va por identificador y no por slug** en la URL pública. Traducir un
slug exige leer la tabla de tenants, que es de `tenancy`, y ningún servicio lee
el esquema de otro; la alternativa sería una llamada entre servicios en cada
envío, que ataría la captura de leads a que `tenancy` esté en pie justo cuando
un desconocido rellena un formulario. El identificador no es un secreto: lo que
autoriza es la clave del canal.

**La URL pública no lleva el prefijo de versión.** Un cliente la pega en el HTML
de su web y no la vuelve a tocar; una URL con `/api/v1/` dentro invita a que
alguien la «actualice» a `/api/v2/` el día que exista y se le rompa el
formulario sin avisar.

### Lo que no hace, dicho

**No deduplica en el momento de la captura.** Eso lo hace el flujo de calidad
después. Meterlo aquí convertiría cada envío de formulario en una consulta de
similitud contra toda la tabla, y un formulario que tarda dos segundos es un
formulario que se abandona.

---

## 37. Documentos: dos capas que no son la misma cosa (`CRM-06.01.01.05`)

La pregunta que había que contestar antes de escribir nada era si contecrm
necesitaba un gestor documental. La respuesta es que necesita **dos cosas
distintas**, y confundirlas es lo que produce la típica gestión documental de
CRM que nadie usa: a medio camino entre un almacén de ficheros y un gestor de
verdad, peor que los dos.

**Adjunto.** Lo que cuelga de un registro. La foto de una visita, el PDF que el
cliente devolvió firmado, el pliego que se adjuntó a una oportunidad. Es del
registro, sigue su papelera y su retención, y se sube desde la ficha en dos
clics. Vive en contecrm.

**Documento del corpus.** Los contratos marco, los procedimientos, los
certificados ISO. Tienen versión, flujo de aprobación, fecha de obsolescencia,
comparación entre versiones y búsqueda en el contenido. Eso no es un campo más
en una tabla de ficheros: es un producto, y la casa ya tiene uno que lleva años
en producción, **contecmind**.

Así que el corpus se delega en contecmind, consumido de forma frontless —igual
que contecintelligence resuelve la explotación (RT-4)—, y contecrm guarda **el
enlace y el contexto**: qué registro tiene qué documento y para qué. Está
recogido en el catálogo como restricción transversal **RT-5**, con
`tests/unit/test_documental.py` como gate.

### Se activa o no, y desactivado no se pierde nada del CRM

`DMS_ENABLED` manda. Activado, contecmind es una **dependencia de despliegue**:
`docker compose --profile dms up` lo levanta con la pila, o se le da en
`DMS_BASE_URL` la dirección de uno ya en marcha. Se comprueba **al arrancar**,
no la primera vez que alguien abre la pestaña de documentos, y con
`DMS_EXIGIR_AL_ARRANCAR=true` el servicio se niega a arrancar si no lo alcanza.

Desactivado, la pestaña del corpus no existe y **los adjuntos siguen
funcionando igual**. Esto no es un detalle de implementación: que un comercial
no pudiera adjuntar la foto de una visita porque un servicio externo está caído
sería una regresión, no una integración. Las dos capas son independientes a
propósito.

Nada de esto está escrito en el código. `DMS_BASE_URL`, `DMS_CLIENT_ID`,
`DMS_CLIENT_SECRET`, `DMS_TIMEOUT_S`, `DMS_TOKEN_TTL_S`, `DMS_SCOPES` y los dos
interruptores de arranque salen del `.env` y de la configuración de la solución.

### Cada usuario ve lo que vería entrando al gestor

La integración usa la credencial de aplicación **solo para canjear un token de
usuario**. Las búsquedas y las fichas van con ese token, no con la credencial.
El rol se traduce de los permisos que la persona tiene aquí: `documento:admin`
o administrador → `admin`; `documento:escribir` o `adjunto:subir` → `writer`; el
resto → `reader`.

Buscar con la credencial de aplicación habría sido más fácil y habría enseñado
a cualquiera con acceso al CRM el corpus entero del tenant, contratos de
dirección incluidos.

**Multitenant sin confiar en el de enfrente.** Cada tenant se mapea a una
organización de contecmind (`OrganizacionDocumental`), y **sin mapeo no se
llama al gestor**. Derivar la organización del identificador del tenant habría
convertido el aislamiento en una convención, y una convención no para a nadie.

### Las dos obligaciones que cruzan la frontera

Con contecintelligence esto no aparecía porque solo lee. Aquí se escribe y se
borra, así que dos garantías de contecrm tienen que sostenerse **al otro lado**.

**El bloqueo legal alcanza a los documentos enlazados.** Un registro bajo
retención legal no deja quitar sus enlaces. Un bloqueo que solo alcanza a media
prueba no es un bloqueo.

**El certificado de destrucción dice qué queda fuera.** Al dar de baja un
tenant, contecrm certifica qué ha destruido; los documentos del corpus los
guarda contecmind y no los destruye este certificado. Callarlo dejaría al
cliente creyendo que sus contratos ya no existen.

Y aquí había un agujero que costó ver: `documentos_enlazados` vive en el
esquema de **cada** servicio y ninguno lee el de otro, así que `tenancy` —que es
quien emite el certificado— miraba su propio esquema, que está casi vacío. Los
contratos están enlazados desde `party` y `sales`. El certificado habría dicho
«0 documentos fuera» **mirando donde no había**, que es peor que no decir nada.

Se resolvió como se replican los ajustes y la clave BYOK: por el bus. Al pasar
el tenant a baja se emite `documental.inventario.solicitado`; **todos** los
servicios lo consumen —`crear_servicio` los suscribe sin que ninguno tenga que
acordarse— y contestan con lo suyo; `tenancy` guarda cada respuesta y compone el
certificado con todas. La ventana de recuperación de treinta días da tiempo de
sobra. Y lo que de verdad importa: el certificado **nombra a los servicios que
no han contestado** y distingue el cero del silencio y del error. Una lista
incompleta presentada como completa es lo único que este inventario no puede
hacer.

Quién tiene que contestar sale de `RUTAS_SERVICIOS`, que ya es la lista de
servicios del despliegue. Una lista escrita en el código se habría quedado vieja
el día que se añadiera un servicio.

### Carpetas del expediente

Los adjuntos de un registro se pueden organizar en carpetas. Cuelgan del
**registro** y no del tenant: un árbol global obliga a inventar una convención
de nombres para saber de quién es cada cosa, y a los seis meses conviven «ACME»,
«ACME 2024» y «Acme S.L.». Con el árbol por registro, «¿qué documentos tengo de
este cliente?» no depende de que alguien nombrara bien la carpeta.

Cuatro decisiones que conviene entender:

- **La ruta se guarda, y se recalcula al mover.** Sin ella, enseñar el camino de
  un documento exige subir por los padres uno a uno, y un listado de cincuenta
  hace doscientas consultas para pintar una columna. Mover una carpeta recalcula
  la rama entera; dejar la ruta vieja pondría la carpeta en un sitio y su
  contenido diría que está en otro.
- **Borrar una carpeta no borra lo de dentro.** Sube a la raíz, o a donde se
  diga, y se devuelve cuántos documentos se movieron. Quien borra una carpeta
  está ordenando, no destruyendo, y el borrado en cascada es la operación que
  más veces se lamenta.
- **Archivar mueve todas las versiones del documento.** Una carpeta es dónde
  está el documento, no dónde está una de sus versiones; dejar la v1 en un sitio
  y la v2 en otro parte el historial en dos.
- **Ninguna carpeta es obligatoria.** Sin carpeta, el adjunto está en la raíz del
  registro. Obligar a elegir carpeta al subir hace que la gente deje de adjuntar.

El árbol se devuelve **plano y ordenado por ruta**, con el nivel de cada
carpeta: quien pinta un árbol lo anida en un bucle, y devolverlo anidado obliga
a recorrerlo entero para encontrar una carpeta concreta. Hay un tope de ocho
niveles, un límite de nombre sin `/` —«2026/Q1» parecería dos carpetas— y no
puede haber dos hermanas con el mismo nombre, tampoco en la raíz: en Postgres
dos `NULL` no son iguales, así que la raíz necesita su propio índice parcial.

### Documentos que viven fuera, sin conector por proveedor

Un adjunto puede ser también **una referencia a algo que está en otro sitio**:
`externo_sistema` es una etiqueta libre y la `uri`, un enlace. No hay conector
de SharePoint ni de Drive, y no lo va a haber: mantener su API, sus permisos y
su autenticación para acabar enseñando un enlace que el navegador del usuario ya
sabe abrir no compensa, y el día que el cliente cambie de gestor habría que
volver a empezar.

El precio, dicho: en ese caso **el CRM no controla el acceso al documento**.
Quien tenga el enlace y permiso en el sistema de origen lo abre; quien no, no.
Eso es correcto para un enlace y sería inaceptable si pretendiéramos que es un
adjunto nuestro, y por eso se distinguen.

---

## 38. Nueve familias de la API que no se podían llamar

El hallazgo salió al preparar la consola de administración, y es el más gordo de
los que lleva este capítulo abierto: **buena parte de la API publicada no era
alcanzable desde fuera**. No estaba mal escrita ni mal probada; simplemente el
gateway no sabía a qué servicio mandarla, así que respondía 404.

La lista, tal como salió:

| Familia | Qué quedaba fuera |
|---|---|
| `/api/v1/sso/*` | **El inicio de sesión federado entero.** La vuelta de SAML y el callback de OIDC llegan del navegador del usuario y del proveedor de identidad, y son exactamente lo que el gateway tiene que atender |
| `/api/v1/proveedores-identidad` | Alta y comprobación de los IdP por tenant, y la publicación de los metadatos SAML |
| `/api/v1/retencion/*` | Políticas de retención, clases de dato, bloqueos legales y purga, en `party` y en `sales` |
| `/api/v1/trabajos/*` | Todos los trabajos asíncronos: seguimiento, cancelación e informe de errores |
| `/api/v1/buscar` | La búsqueda de cada servicio |
| `/api/v1/captura/canales` | Los canales de captura de leads y su rotación de clave |
| `/api/v1/tablas-decision/*` | Las tablas de decisión del motor de procesos |
| `/api/v1/claves-cifrado/*` | BYOK: generar y revocar la clave del tenant |
| `/api/v1/localizacion` | Idioma, huso y formatos del tenant |

Y, ya de paso, las carpetas del expediente que se acababan de entregar
(`/api/v1/adjuntos/carpetas/…`), porque el gateway resolvía los adjuntos por el
segmento siguiente al recurso dando por hecho que era un tipo de objeto: buscaba
uno llamado «carpetas» y no lo encontraba.

### Por qué pasó, que es lo que importa

La tabla de prefijos del gateway es **la única lista de acoplamiento del
sistema**, y se mantenía a mano. Nada comprobaba que estuviera completa. Un
servicio publicaba una familia nueva, en su propio OpenAPI salía, sus pruebas
pasaban, y desde fuera no existía. El fallo no daba ningún síntoma hasta que
alguien intentaba llamarla — y en el caso del SSO, ese alguien es un cliente
intentando entrar.

Ahora hay un gate que recorre **todas** las rutas publicadas por **todos** los
servicios y comprueba que el gateway las enruta a su dueño. Mantener la lista
deja de ser un acto de disciplina.

### Dos decisiones de diseño que hubo que tomar

**Los recursos transversales van bajo el nombre del servicio.** Retención,
búsqueda y trabajos los monta la misma fábrica en varios servicios, y
`/api/v1/trabajos/{id}` es ambiguo: el identificador no delata al dueño. La
alternativa era que el gateway preguntara a todos hasta que uno no respondiera
404, lo que dobla la latencia de cada llamada y convierte un identificador
equivocado en una ronda por toda la instalación. Van a
`/api/v1/party/trabajos/{id}` y `/api/v1/sales/retencion/…`: inequívoco, y se
lee.

**La superficie se agrega en el gateway.** `GET /api/v1/superficie` junta la de
los diez servicios en una sola lista, cada operación con su método, su ruta
pública, el permiso que exige y si es de administración. Quien la consume es un
cliente de fuera, que no conoce —ni debe conocer— cómo está repartido el sistema
por dentro. Y cuando un servicio no contesta, la respuesta **lo dice y lo
nombra**: una superficie a la que le falta un servicio sin avisar haría que la
consola escondiera media administración como si no existiera.

---

## 39. Lo que viene: front oficial, ABAC aplicado y GRC

Tres bloques nuevos en el catálogo, con identificador cada uno, y por tanto en
la hoja de estado desde ya.

### El front oficial de referencia (`CRM-07.04.*`, 56 capacidades)

contecrm es y sigue siendo **frontless**: quien quiera se hace su interfaz
entera como le dé la gana, y no pierde nada por hacerlo — toda capacidad existe
primero como servicio con contrato (RT-1). Lo que faltaba es la otra mitad de
esa frase: **una interfaz oficial completa**, la que da la solución estándar,
con la estética y el sistema de diseño de contecmind.

Va desglosado en cinco bloques: la base y el sistema de diseño, la sesión y la
seguridad del cliente, la cobertura funcional, la calidad, y la cobertura
medida. Dos capacidades son gates y no pantallas, y son las que impiden que el
front oficial se convierta en el privilegiado: **toda llamada que hace el front
tiene que existir en la superficie**, y **cero lógica de negocio en el front** —
ni cálculo de precios, ni de permisos, ni de reglas de estado.

**Tiene que cubrirlo todo, y eso se comprueba.** El front estándar es con lo que
se enseña la solución, así que una capacidad que solo existe por API es una
capacidad que nadie ve: quien mira el producto concluye que no está. Por eso la
cobertura funcional no es una lista de pantallas escrita a ojo, sino **una
capacidad por cada sección del catálogo** —las treinta que hay—, cada una
declarando con `cubre:` qué sección enseña. Un gate comprueba las dos
direcciones: que no queda ninguna sección sin pantalla declarada, y que ninguna
pantalla declara cubrir una sección que ya no existe. El día que se añada un
área nueva al catálogo, la prueba falla hasta que alguien decida cómo se enseña,
en vez de que entre sin interfaz y se descubra en una demostración.

Y el informe al revés, que es el que nadie hace: **qué capacidades ya hechas no
enseña ninguna pantalla**. Es la lista de potencia escondida en la API.

### ABAC aplicado (`CRM-00.05.02.17` a `CRM-00.05.02.21`)

Lo dicho en «Lo que está a medias»: hay motor y no hay cumplimiento. Lo que
viene es que las políticas se guarden y se versionen, que haya **un punto único
de decisión** por el que pase toda lectura y escritura de un registro —con un
gate que lo imponga, para que no vuelva a haber motor sin quien lo llame—, que
los listados se filtren con la política traducida a SQL, que una política pueda
hablar de un campo y no solo de un registro, y que exista un simulador para ver
qué vería alguien **antes** de activarla. El motor externalizable
(`CRM-00.05.02.06`, OPA/Cedar) deja de ser un adorno: es lo que permite que un
front a medida evalúe la misma política sin reimplementarla.

### GRC (`CRM-07.03.02.*`, 10 capacidades)

Riesgos, controles, evaluaciones periódicas y segregación de funciones, que es
el GRC que la casa ya sabe hacer —hay 740 líneas en contecmind y 786 en
contecweb— con dos vueltas de tuerca.

La primera: **cada control se ancla a capacidades del catálogo por su
identificador**. Eso convierte la cobertura en algo medible —«de las 631
capacidades, cuáles tienen control y cuáles no»— y hace que crezca sola con el
producto en vez de quedarse vieja. Incluye el informe al revés, que es el que
nadie hace: qué controles apuntan a capacidades que ya no existen.

La segunda: **el mapeo a los marcos es recorrible en los dos sentidos**. Un
auditor pregunta por ISO 27001 A.9 y salen las capacidades del producto que lo
sostienen y con qué evidencia; y desde una capacidad se ve a qué obligaciones
responde. Las evidencias salen del audit trail, de los certificados de
destrucción y de los propios gates, en vez de adjuntarse a mano — que es como
un GRC se queda desactualizado el segundo trimestre.

---

## 40. ABAC: del motor que nadie llamaba al que decide de verdad

RBAC responde «¿puede leer cuentas?». ABAC responde lo que de verdad pregunta un
CRM: «¿puede leer **esta** cuenta?». Los dos hacen falta, y se aplican en este
orden: el ABAC **restringe y nunca amplía**, así que «¿qué puede hacer como
máximo?» se sigue respondiendo mirando solo los roles.

Lo que había era un motor impecable —gramática cerrada de operadores, decisión
explicable, traducción de la misma condición a SQL— al que **no llamaba nadie**.
Las políticas vivían en una lista de Python, las tres de ejemplo estaban
desactivadas, y el único sitio que las evaluaba era el explicador de permisos.
El sistema sabía explicar una decisión que no tomaba. Esto es la otra mitad
(CRM-00.05.02.05, y `.17` a `.21`).

### Las políticas son datos, y se guardan donde se decide

Una política es una fila: objeto, acciones, una lista de condiciones
`{atributo, operador, valor}`, cómo se combinan y con qué prioridad. No es una
expresión que haya que interpretar, y eso no es un detalle: una cadena
interpretada sería ejecutar entrada del tenant dentro del motor de permisos, y
además no se podría explicar condición a condición, que es lo que hace útil al
explicador.

Viven en el esquema de **cada servicio**, porque la decisión se toma donde está
el dato: `party` decide sobre una cuenta y no puede leer el esquema de
`identity`. Se escriben desde administración y se replican por evento, igual
que los ajustes en caliente, la clave BYOK y el mapeo del gestor documental
(§«las tres decisiones» del manual de arquitectura). Un servicio que no
replicara seguiría decidiendo con las políticas de ayer, y en permisos esa es
la divergencia más cara: **no falla nada**, simplemente alguien ve lo que ya no
debería.

Cada cambio sube la versión y deja una copia de la anterior. Sin histórico,
«¿por qué no veía yo esto el mes pasado?» no tiene respuesta, porque la tabla
viva solo enseña el estado de hoy — y una política de acceso es exactamente el
tipo de cosa por la que se pregunta después, no antes.

### El punto único de decisión, y por qué es un cargador y no un endpoint

Tres entradas que tienen que dar **la misma** respuesta:

| Dónde | Qué hace |
|---|---|
| `exigir(...)` | La ficha y la escritura (CRM-00.05.02.18). Evalúa en Python sobre el registro y corta con 403 **con la explicación dentro** |
| `filtro(...)` | El listado (CRM-00.05.02.19). La misma condición, traducida a `WHERE` |
| `campos_ocultos(...)` | La proyección (CRM-00.05.02.20). Qué columnas se caen en este registro concreto |

Que la ficha y el listado coincidan no es una aspiración: es lo que impide el
fallo clásico de estos sistemas —un listado que enseña un registro que la ficha
luego niega, o un registro invisible en la lista y accesible por su
identificador—. Por eso la condición se escribe **una vez** y se traduce, en
vez de escribirse dos veces en dos lenguajes.

La llamada va **dentro de los cargadores compartidos** (`_cuenta`, `_lead`,
`exigir_contacto`…), no en cada endpoint. El endpoint que se olvide es el
agujero, y acordarse en cada uno es exactamente lo que no funciona. Un gate lo
sostiene: recorre el código buscando funciones que carguen por identificador un
objeto con política y respondan 404, y exige que llamen al punto de decisión.
Al escribirlo encontró **ocho** cargadores que no pasaban por ahí —la ficha de
contacto, el borrado, las dos fusiones, el consentimiento, el vínculo
contacto-cuenta y completar una actividad—. Un cargador nuevo aparece en esa
lista solo, sin que nadie actualice nada.

### La asimetría con la compartición, que hay que tener clara

Las dos cosas filtran listados y se parecen, y se comportan **al revés**:

- La **compartición** dice a quién se le ha dado acceso. Cuando una vía no se
  puede traducir, comparte de más: no aplicarla deja de enseñar algo que sí se
  podía ver.
- El **ABAC** dice a quién se le quita. Cuando una condición no se puede
  traducir —mira una columna que el modelo no tiene, o usa un operador sin
  equivalente en SQL—, **deniega**: no aplicarla enseñaría lo que no se debe.

Así que una política con un error de escritura vacía el listado en vez de
abrirlo. Es incómodo y es lo correcto; y para que ese error no llegue a
producción, la gramática se valida **al guardar**: una política con un operador
que no existe se rechaza, porque evaluada se comportaría como denegar y eso
convertiría un error de escritura en un corte de acceso silencioso el día que
alguien la activara.

Y una división que hace posible el filtrado en SQL: las condiciones sobre el
**usuario y el contexto** no dependen de la fila, así que se evalúan una vez
antes de construir la consulta —o son las cuatro de la tarde para toda la
consulta, o no lo son para ninguna fila—, y solo las condiciones sobre el
**registro** van al `WHERE`.

### Políticas por campo

Una política de alcance `campos` no esconde el registro: esconde los campos que
nombra a quien no cumple la condición. Convive con la proyección por
sensibilidad y no la sustituye, porque dicen cosas distintas: la sensibilidad
dice «el identificador fiscal es dato personal y este rol no lo ve nunca», y
esto dice «el margen de las cuentas de otra unidad de negocio no se ve». Una es
del campo y la otra del registro que se está mirando.

Se evalúa **por registro**, dentro del bucle de proyección, porque depende de
la fila. Y si evaluar falla, se esconde: como no se sabe cuáles tocaba
esconder, se esconden todos los que alguna política controla para ese objeto —
acotado, y sin enseñar nada que se estuviera negando.

### El simulador, que es lo que hace que alguien se atreva a escribir una

Una política de acceso mal escrita no da un error: corta el acceso a gente que
estaba trabajando, en silencio, y se descubre por los tickets. `POST
/politicas-acceso/simular` contesta «¿qué vería esta persona?» con los
atributos **reales** del usuario que se indique y sobre el registro que se
pase, y admite una política que **todavía no existe** — que es la forma de
comprobar qué haría antes de crearla. Por eso, además, una política se puede
guardar desactivada: que se pueda escribir sin que aplique es lo que hace que
alguien la escriba.

### Sacar el motor fuera, sin atarse a ningún producto (`CRM-00.05.02.06`)

Decidir dentro del proceso está bien mientras el único que pregunta es el CRM.
Deja de estarlo en cuanto hay más consumidores: un front a medida que quiere
saber si pintar un botón, un servicio del cliente que aplica las mismas reglas,
un motor corporativo que ya existe. Sin esto, cada uno reimplementa las reglas y
la cuarta implementación ya no dice lo mismo que las otras tres.

Dos piezas, y ninguna ata la instalación a un producto:

**Publicar** la política en un formato neutro, con la semántica **dentro del
documento** —qué pasa sin políticas, qué pasa con un operador desconocido, cómo
se combinan—. No se traduce a Rego ni a Cedar a propósito: hacerlo aquí ataría
el producto a ese dialecto, y quien use uno escribe el traductor una vez con
esta salida como entrada estable.

**Delegar** la decisión en un motor externo por HTTP, si se configura
(`ABAC_MOTOR_EXTERNO_*`). Es un transporte declarativo, como el de
notificaciones o el de verificación: dirección, plazo y contrato en la
configuración, sin cliente por producto. Con dos reglas que impiden que
delegar sea un agujero: **si no contesta, decide el motor de dentro** —que
tiene la misma política replicada—, y **el externo puede restringir más, nunca
menos**. Sin la segunda, bastaría apuntar la configuración a un servicio que
diga «sí» a todo para saltarse las políticas del tenant; con ella, el peor caso
de un motor externo hostil es que no cambie nada.

### El fallo que apareció al probarlo, y que era el peor posible

`registro.owner_id = @usuario.id` es la regla que pide casi todo despliegue. El
registro llega serializado —el identificador es una cadena— y el usuario viene
del principal, donde es un `UUID`. Comparados tal cual **nunca** son iguales.

Es decir: la política más común del sistema habría denegado siempre, en
silencio, sin error y sin traza. Ahora los identificadores se igualan antes de
comparar, y solo ellos: convertir todo a texto para comparar haría que `5 > 10`
fuera cierto, que es cambiar una regla por otra sin decirlo.

---

## 41. GRC: el que se mide sobre el producto, no sobre un documento

El registro de riesgos con su tratamiento y su residual (`CRM-07.03.02.01`), el
catálogo de controles con tipo, frecuencia y responsable (`CRM-07.03.02.02`) y
la evaluación periódica con resultado, evidencia y plan de acción
(`CRM-07.03.02.03`). Eso ya lo sabe hacer la casa —740 líneas en contecmind, 786
en contecweb— y lo que cambia aquí son dos vueltas de tuerca que solo son
posibles porque este producto tiene un catálogo funcional con identificadores
estables.

### Cada control se ancla a capacidades reales (`CRM-07.03.02.04`)

Un GRC donde los controles se escriben a mano describe un sistema **imaginado**,
y a los dos trimestres describe uno que ya no existe. Aquí un control declara
qué capacidades del catálogo cubre, por su identificador, y eso se comprueba al
guardar: un control sobre `CRM-99.99.99.99` **no se guarda**, porque contaría en
el informe de cobertura sin cubrir nada.

Para poder comprobarlo, el catálogo se lee **en ejecución** y no solo en las
pruebas: `docs/catalogo/catalogo.yaml` viaja en la imagen. No es documentación,
es dato de producto.

### El informe va en los dos sentidos (`CRM-07.03.02.05`)

El que todo el mundo hace es «qué capacidades no tienen control», agrupado por
sección para que se lea —una lista de cuatrocientos identificadores no la mira
nadie—. Y se puede medir sobre **lo entregado** o sobre el catálogo entero: lo
primero es lo que un auditor puede comprobar hoy, lo segundo es lo que queda por
cubrir cuando el resto se entregue.

El que **nadie** hace es el de vuelta: **qué controles apuntan a capacidades que
ya no existen**. Es como se detecta que un control lleva un año cubriendo algo
que se quitó del producto, y no aparece solo porque hay que ir a buscarlo.

Un detalle que parece menor y no lo es: cuando el catálogo no está disponible,
la respuesta **dice que no se ha podido medir** en vez de devolver ceros. Una
cobertura del 0 % y una cobertura que no se ha podido medir se leen igual y
significan cosas opuestas.

### Del marco normativo al código, y de vuelta (`CRM-07.03.02.07`)

Un auditor pregunta por ISO 27001 A.9 y sale qué controles responden, qué
capacidades del producto los sostienen —con su título, no solo su
identificador— y cuándo se evaluaron por última vez. Y el recorrido inverso, que
es el que sirve a quien construye: antes de tocar una capacidad se ve a qué
obligaciones está respondiendo.

### La evidencia la pone el sistema (`CRM-07.03.02.08`)

Adjuntar la prueba a mano es exactamente como un GRC se queda desactualizado el
segundo trimestre: la persona que la sacaba cambia de puesto y nadie más sabe de
dónde salía. Aquí el control declara su fuente —`audit_trail`,
`politicas_abac`, `certificados_destruccion`— y el sistema la lee al evaluar. Y
una fuente que no se sabe leer **lo dice en la propia evidencia**: devolver un
diccionario vacío parecería «no hay nada que probar».

### Tres obligaciones que impiden que esto se vuelva un archivo

**Aceptar un riesgo exige declarar el residual.** Aceptar sin decir cuánto queda
no es una decisión, es archivarlo. Y guardar el residual aparte del inherente es
lo que permite responder si el tratamiento sirvió de algo: la diferencia entre
los dos **es** el valor del control.

**Un control que no sale efectivo exige plan de acción.** Sin esa obligación, el
registro se llena de controles «parciales» que nadie arregla.

**La fecha de la próxima evaluación se calcula de la frecuencia**, no se
escribe. Una fecha a mano es la primera que se queda sin poner, y así un control
«trimestral» pasa dieciocho meses sin mirarse.

Y una vista, `/grc/pendiente`, que junta lo que no cuadra hoy: controles nunca
evaluados, fuera de plazo o no efectivos, y **riesgos que se decidió mitigar y
no tienen ningún control** — una decisión sin ejecución, que es el caso que más
veces sale en una auditoría.

### Segregación de funciones (`CRM-07.03.02.06`)

La regla más vieja del control interno: quien crea un proveedor no puede aprobar
su pago. En un CRM son pares de permisos que no deben coincidir en una persona.
Vive en `identity` porque lo que compara son **permisos efectivos**, que salen
de los roles y sus herencias.

Cuatro decisiones, todas dirigidas a que el informe siga sirviendo pasado el
primer trimestre:

- **Detecta, no impide.** Bloquear la asignación de un rol deja al administrador
  sin poder operar y sin entender por qué. Lo que hace falta es la lista de
  quién está en conflicto, para resolverlo con criterio.
- **Se calcula en vivo y no se guarda.** Una tabla de violaciones se queda vieja
  en cuanto alguien cambia de rol, y una lista de conflictos vieja es peor que
  ninguna, porque se actúa sobre ella.
- **La excepción se aprueba, con motivo y con caducidad.** Sin excepciones, el
  informe sale siempre en rojo y se deja de mirar; con excepciones eternas, el
  rojo desaparece y tampoco se mira. Una organización pequeña tiene conflictos
  inevitables porque una persona es todo el departamento; eso se aprueba, no se
  ignora.
- **Un conflicto exceptuado sigue saliendo, marcado.** Esconderlo haría que una
  excepción caducada pasara de «aprobado» a «no existe» sin que nadie lo viera.

Dos comprobaciones que evitan reglas que mienten: un mismo permiso en los dos
lados no segrega nada —prohíbe, y para eso se quita del rol—, y el comodín se
expande al comparar, porque un rol con `*:*` los tiene todos y una regla que no
lo viera daría por limpio justo al usuario más peligroso.

---

## 42. El front oficial, y la consola que se construye sola

contecrm es y sigue siendo **frontless**: toda capacidad existe primero como
servicio con contrato (RT-1) y quien quiera se hace su interfaz entera sin
perder nada. Lo que faltaba es la otra mitad de esa frase — la interfaz
**oficial**, la que da la solución estándar — y está en `frontend/`, con el
mismo stack y el mismo sistema de diseño que contecmind: React, Vite,
TypeScript y Tailwind, con los tokens `paper` / `ink` / `accent` tal cual, para
que quien use las dos soluciones no note que cambia de producto.

Lo que hay montado, capacidad a capacidad: la aplicación de referencia con el
stack de la casa (`CRM-07.04.01.01`), su sistema de diseño (`CRM-07.04.01.02`),
el marco con navegación, tema claro/oscuro y aviso permanente de suplantación
(`CRM-07.04.01.03`), los textos centralizados para que el segundo idioma no
obligue a repasar la aplicación entera (`CRM-07.04.01.05`), los estados de
carga, vacío y error homogéneos con el Problem Details traducido a lenguaje de
usuario (`CRM-07.04.01.07`), la entrada con SSO y con contraseña
(`CRM-07.04.02.01`), el cliente de API con idempotencia en las escrituras y
`ETag`/`If-Match` en las ediciones (`CRM-07.04.02.06`), la página de estado del
tenant (`CRM-07.04.03.13`) y las pruebas de todo ello (`CRM-07.04.04.01`).

Se levanta con su perfil, porque una instalación que solo consuma la API no la
necesita:

```bash
docker compose --profile app --profile consola up
```

### La consola de administración se construye del contrato (`CRM-07.01.01.01`)

Esta es la pieza que cierra la capacidad que llevaba en curso desde el
principio, y que es además `CRM-07.04.03.01`. El menú, las tablas y las acciones
de la consola **salen de `GET /api/v1/superficie`**, que el gateway agrega
juntando la de los diez servicios.

Eso convierte «la consola está replicada al 100 % por API» en algo comprobable
en vez de declarado: aquí **no hay forma de pintar una acción que no sea una
operación publicada**, porque no existe ninguna lista de acciones escrita a mano
de donde sacarla. Por construcción, no por disciplina.

Tres decisiones de esa consola que conviene entender:

- **Agrupa por recurso de la ruta, no por etiqueta.** Dos servicios pueden
  rotular parecido —«ajustes» y «configuración»— y acabarían en el mismo menú
  apuntando a sitios distintos, sin que el usuario viera la diferencia hasta
  pulsar.
- **El listado es el `GET` sin parámetros.** Con uno parametrizado habría que
  pedirle al usuario que invente un identificador para ver una tabla; un área
  que no lo tiene lo dice en vez de fingir una lista vacía.
- **Lo que el rol no concede se enseña apagado, no escondido.** Esconderlo haría
  imposible saber que esa operación existe, que es justo lo que alguien necesita
  para pedir el permiso. Y la decisión no la toma la interfaz
  (`CRM-07.04.02.05`): **lee** los permisos efectivos que le da el servidor y con
  eso decide qué ofrecer. Si decidiera ella, bastaría con abrir las herramientas
  del navegador para «concederse» una acción.

Y cuando un servicio no contesta a la superficie, **se dice y se nombra**: una
consola que callara eso escondería media administración como si no existiera.

### Lo que el front no puede hacer, y hay gate que lo impide

Dos capacidades del catálogo son gates y no pantallas, y son las que evitan que
la interfaz oficial se convierta en el cliente privilegiado — algo que no pasa
de golpe, sino una pantalla a la vez, cada una con su prisa.

Las cabeceras de seguridad del cliente (`CRM-07.04.02.04`) las pone el servidor
que sirve la aplicación y no la aplicación: CSP sin `eval` ni estilos en línea,
`nosniff`, `frame-ancestors: none` y aislamiento de origen. Una cabecera que
pone la aplicación puede quitarla la propia aplicación; una que pone el
servidor, no.

**Toda llamada del front existe como ruta publicada** (`CRM-07.04.02.07`). El
gate recorre las rutas literales del código y las compara con el OpenAPI de
todos los servicios. Cinco están exentas y se nombran con su motivo: la propia
superficie, el estado agregado, la identidad de la sesión, la entrada y el
arranque del SSO.

**Cero lógica de negocio en el front** (`CRM-07.04.02.08`). Ni cálculo de
precios, ni de descuentos, ni de puntuación de leads, ni de SLA. El gate caza lo
que tiene nombre y se dice claramente que lo que no puede cazar —una regla
escondida en un `if`— lo sostiene la revisión.

Y un tercero: **nada de negocio en el almacenamiento del navegador**
(`CRM-07.04.02.09`). Solo preferencias de quien mira, y solo en un fichero
—`lib/tema.ts`— que el gate conoce. Los comentarios se ignoran a propósito: este
front explica precisamente lo que *no* hace, y castigar la frase que documenta
una decisión correcta es la forma más rápida de que nadie vuelva a escribirla.

### La sesión en cookie, y el hueco que destapó (`CRM-07.04.02.03`)

Al escribir la pantalla de entrada apareció un problema de verdad: `identity`
devuelve los tokens **en el cuerpo**. Para una integración es lo correcto —un
servicio guarda su token donde quiera— y para un navegador es lo peor posible:
si el token llega al cliente, la aplicación tiene que guardarlo, y todos los
sitios que sobreviven a una recarga los puede leer un script inyectado. Un XSS
deja de ser un susto y pasa a ser una sesión robada.

Así que el **gateway** —lo único con lo que habla un navegador— hace de puente.
`POST /api/v1/sesion/entrar` recibe las credenciales, pide los tokens a
identidad y devuelve una cookie `HttpOnly`; **el cuerpo no lleva el token**, y
hay una prueba que lo comprueba sobre el código precisamente para que nadie lo
añada más adelante «porque no hace daño». Las cuatro propiedades de la cookie
están puestas y ninguna es decorativa: `HttpOnly` la esconde de los scripts,
`Secure` impide que viaje en claro, `SameSite=Lax` corta el envío en peticiones
cruzadas de escritura —y es `lax` y no `strict` porque con `strict` la vuelta
del proveedor de identidad llega sin cookie y el SSO no completa nunca— y
`Path=/api` la acota.

Cerrar sesión revoca en identidad además de borrar la cookie: borrar solo la
cookie dejaría el token vivo hasta caducar, y quien lo hubiera copiado seguiría
dentro. Si identidad no responde, la cookie se borra igual — dejar al usuario
dentro porque un servicio no contesta es el peor resultado posible de pulsar
«cerrar sesión».

Una cabecera `Authorization` explícita **manda sobre la cookie**. Sin esa
precedencia, una pestaña con sesión abierta cambiaría en silencio la identidad
de una llamada de API hecha desde la misma máquina.

### Lo que hay y lo que no

Hay: el marco con navegación y tema claro/oscuro, la entrada con SSO y con
contraseña, la consola de administración, la página de estado del tenant —que
enseña además los compromisos de servicio junto a lo medido
(`CRM-07.04.03.30`), porque un RPO escrito en un contrato que nadie compara con
la realidad no lo comprueba nadie—, los
estados de carga, vacío y error homogéneos con el Problem Details traducido, el
aviso de campos retenidos por permisos, el aviso permanente de suplantación, y
el cliente de API con idempotencia en las escrituras y `ETag`/`If-Match` en las
ediciones.

Y los módulos funcionales de la fase 1, uno por sección del catálogo: tenants,
planes, ajustes y localización (`CRM-07.04.03.01`), el explorador del contrato
de la API (`CRM-07.04.03.02`), procesos, instancias, tareas, tablas de decisión
y automatizaciones (`CRM-07.04.03.03`), objetos y relaciones del modelo de datos
(`CRM-07.04.03.04`), usuarios, roles, políticas de acceso, claves, sesiones y
proveedores de identidad (`CRM-07.04.03.05`), la operación y el catálogo de
eventos (`CRM-07.04.03.06`), cuentas, contactos y duplicados
(`CRM-07.04.03.07`), actividades (`CRM-07.04.03.08`), el pipeline
(`CRM-07.04.03.13`), la prospección con leads, enrutamiento y canales de captura
(`CRM-07.04.03.15`), la consola de administración (`CRM-07.04.03.26`) y el
gobierno con riesgos, controles, segregación, retención, bloqueos legales y
clases de dato (`CRM-07.04.03.28`), la previsión con el resumen del pipeline y
las oportunidades estancadas (`CRM-07.04.03.14`) y la explotación delegada en
contecintelligence (`CRM-07.04.03.22`), donde se enseña el estado del enlace y
lo consultado — los informes se abren allí, con la identidad del usuario (RT-4)—
y la colaboración sobre la ficha (`CRM-07.04.03.25`).

**La ficha de un registro sirve para cualquier objeto.** Adjuntos, comentarios y
documentos del corpus son transversales: los mismos para una cuenta, un contacto
o una oportunidad. Están en una sola ficha y no repetidos en cada módulo, que es
como se acaba con tres implementaciones del panel de adjuntos, dos de ellas sin
el aviso de fichero infectado. El tipo de objeto va en la ruta porque es el
servicio dueño del registro quien guarda lo que cuelga de él.

Los listados enlazan a la ficha **solo cuando la hay**: un enlace que lleva a una
pantalla vacía es peor que no tener enlace, porque el usuario cree que se ha
roto algo.

**Una sola pantalla para todos, no treinta escritas a mano.** No es pereza:
treinta pantallas son treinta sitios donde el mismo fallo se arregla una vez y
sigue en las otras veintinueve, y treinta sitios donde alguien olvida la
paginación, el aviso de campos retenidos o la clave de idempotencia. Lo que cada
módulo declara es **qué** se enseña; el **cómo** es uno solo. Las columnas salen
de lo que devuelve la API y los formularios del OpenAPI del servicio dueño
(`CRM-07.04.04.04`), así que un campo nuevo en el servicio aparece en el
formulario sin tocar el front.

Ese formulario **no valida reglas de negocio**: marca lo obligatorio y respeta
tipo y longitud porque eso es contrato; «el descuento no puede pasar del 30 %»
lo comprueba el servicio, y duplicarlo aquí sería tener dos versiones de la
misma regla que se separan.

Hay un tercer gate que ata las dos listas que podrían separarse: el catálogo
dice qué secciones enseña el front y `modulos.ts` dice qué pantallas hay. Una
sección declarada hecha sin módulo hace fallar la prueba, y un módulo que cubre
una sección que nadie ha declarado terminada, también. La que se queda corta es
siempre la del código, porque marcar una capacidad cuesta una línea y construir
la pantalla cuesta una tarde.

No hay todavía: marketing, servicio y atención, analítica e IA, productividad,
ALM y canal indirecto. Están catalogados en `CRM-07.04.03.*`, uno por sección, y
constan como pendientes.

La configuración del cliente —dirección de la API, nombre del producto, idioma,
color de acento y logotipo— se lee **en ejecución** de `/config.json`, que genera
el contenedor al arrancar a partir del entorno. Compilarla obligaría a
reconstruir la imagen para cambiar una URL.

**Marca blanca** (`CRM-07.04.01.04`): el acento del cliente se escribe sobre la
*misma* variable que usa el sistema de diseño, no sobre una clase aparte, así
que llega a todo lo que ya usa `bg-accent` o `text-accent` sin repasar la
aplicación. Se valida la forma antes de escribirla: una variable CSS con un
valor inventado no falla, simplemente deja de aplicarse y el acento desaparece
sin decir por qué.

### La sesión se renueva sola (`CRM-07.04.02.02`)

El token de acceso dura quince minutos a propósito: su tiempo de vida **es** la
ventana de exposición si alguien lo copia. La interfaz lo cambia por uno nuevo
cada diez, **antes** de que caduque — descubrirlo con un 401 en mitad de un
formulario pierde lo que se estaba escribiendo.

Eso obligó a guardar también el token de refresco, en una segunda cookie
acotada a la única ruta que lo canjea: una cookie de refresco que viajara en
cada petición multiplicaría por mil las ocasiones de que se filtre, y solo hace
falta en una. El refresco **rota** en cada uso, así que se guarda el nuevo;
guardar el viejo haría que el siguiente intento revocara todas las sesiones del
usuario, que es lo que pasa al presentar un refresco ya rotado. Y una sesión que
no se puede renovar **se cierra**: dejar la cookie vieja haría que la interfaz
siguiera creyéndose dentro hasta el siguiente 401.

### Accesibilidad, tamaño y pantalla pequeña

**Accesibilidad AA** (`CRM-07.04.01.06`) con comprobación automática en cada
cambio (`CRM-07.04.04.02`): `eslint-plugin-jsx-a11y` con sus reglas
recomendadas, y un gate que revisa los cuatro fallos que ninguna herramienta
perdona — el salto al contenido, el idioma del documento, que toda navegación
esté rotulada y que ningún control se quede sin nombre. Se dice claramente lo
que un gate estático **no** puede comprobar: el contraste real y el orden de
foco los mide el navegador.

**Pantalla pequeña sin aplicación aparte** (`CRM-07.04.01.08`): en móvil la
cabecera se apila en vez de encogerse —una barra con seis enlaces a 360 px o
desborda o los deja de 8 px, y las dos cosas son peores que dos líneas— y las
tablas se desplazan en horizontal. Una tabla de doce columnas apretada en 360 px
no se lee; una que se desplaza, sí, y el usuario decide qué mira.

**Presupuesto de rendimiento** (`CRM-07.04.04.03`): 120 kB comprimidos, medidos
sobre `dist/` en el preflight local. Una aplicación web crece de treinta en
treinta kilobytes, cada uno con su justificación, y un día tarda cuatro segundos
en abrir; nadie lo decide, se llega. Un tope que falla obliga a que la decisión
sea explícita: o se justifica subirlo, o se quita algo.

**Tipado estricto y tipos del contrato** (`CRM-07.04.04.04`): TypeScript en modo
estricto, sin `any` implícito y con índices comprobados, y los esquemas de los
formularios leídos del OpenAPI del servicio dueño en vez de escritos a mano.

### El recorrido, y la trazabilidad puesta delante

Hay un **recorrido guiado** por la solución (`CRM-07.04.05.04`) construido desde
el catálogo de módulos, no escrito a mano: un guion de demostración aparte se
queda viejo a la tercera pantalla que alguien añade, y el día que se enseña el
producto lo que se cuenta ya no es lo que hay. Cada paso sale de un módulo real
y lleva a la pantalla real, y lo que no aparece ahí es que no está hecho.

Y **cada pantalla dice qué capacidad del catálogo implementa**
(`CRM-07.04.05.05`), con el identificador a la vista. Desde él se llega al
enunciado, al código y a la prueba: es la trazabilidad puesta delante de quien
la mira, en vez de enterrada en un fichero que solo abre quien ya sabe que
existe.

### El tenant de demostración (`CRM-07.04.05.03`)

Enseñar la solución sobre una base vacía no enseña nada: lo que hay que ver es
cómo se relacionan los registros, no que existan. `scripts/sembrar_demo.py`
siembra un tenant con cuatro cuentas, sus contactos, tres oportunidades, dos
leads y tres actividades — y una de esas actividades está **vencida** a
propósito, porque enseñar solo actividades al día esconde justo la mitad del
sistema que se nota: los avisos y los vencimientos.

Los datos son coherentes entre sí y hay prueba que lo comprueba: los contactos
pertenecen a cuentas que se siembran, las oportunidades también, y los leads son
de empresas que **no** son clientes todavía — si coincidieran con una cuenta
existente, la demo enseñaría un duplicado y no un lead.

Se siembra **por partes**, una por servicio, y no por comodidad: en un
despliegue real un proceso no llega a todos los esquemas, y eso es el
aislamiento funcionando. Y se niega a ejecutarse en producción, que es la
condición sin la cual todo lo demás da igual: meter datos de ejemplo en la base
de un cliente no se deshace con un `DELETE`, porque los eventos ya se han
publicado, la auditoría ya lo ha registrado y los webhooks ya han salido.

### El informe que nadie hace (`CRM-07.04.05.01`, `CRM-07.04.05.02`)

Hay una pantalla de cobertura que cruza la superficie con los módulos
declarados y contesta dos preguntas. La normal —cuántas operaciones publicadas
tienen pantalla— y la de vuelta, que es la que importa: **qué sabe hacer el CRM
que ninguna pantalla enseña**, ordenado por cuánto esconde cada recurso.

Esa es la lista de potencia escondida en la API: capacidades construidas,
probadas y documentadas que quien mira el producto concluye que no están. Se
calcula **en vivo**, porque un informe de cobertura guardado se queda viejo en
cuanto alguien añade una ruta — y un informe viejo es peor que ninguno, porque
se decide sobre él.

---

## 43. El proceso antes de publicarlo: validar, guardar a medias y retirar

El motor de procesos ya ejecutaba, compensaba y reanudaba. Lo que faltaba es lo
que pasa **antes** de que una definición llegue a producción, y es donde estos
motores se rompen siempre: alguien cambia el diagrama un martes y doscientas
instancias a medias pasan a ejecutar pasos que no existían cuando empezaron.

### Dos formas de que un proceso se atasque, y solo se detectaba una

La validación ya avisaba de pasos inalcanzables: un paso que se dejó de enlazar
al reorganizar el flujo. Eso es código muerto, molesto pero inofensivo.

Lo que **no** se detectaba es lo contrario, que es lo caro: pasos desde los que
no se llega a ningún final (`CRM-00.03.05.03`). Una instancia que entra ahí **no
sale**: se queda en curso para siempre, consumiendo su temporizador, sin fallar y
sin que nadie sepa por qué. Cubre los dos casos que se escriben solos al
reorganizar un flujo — un bucle sin rama de salida, y una rama que se quedó sin
enlazar a ningún `fin`.

Se comprueba recorriendo con los **mismos enlaces** que usa la detección de
alcanzables, a propósito: si aparecieran tipos de enlace nuevos y solo se
añadieran a un lado, un bucle sin salida dejaría de detectarse justo cuando más
falta hace.

### Borrador, publicada, archivada (`CRM-00.03.05.05`)

Una definición se puede guardar como **borrador**: se valida y se puede simular,
pero nadie la puede instanciar. Sirve para dejar un proceso a medias entre
sesiones de trabajo sin arriesgarse a que un disparador lo arranque a mitad de
escribirlo.

El borrador **también se valida**, y es deliberado: descubrir que la definición
está rota el día que se publica, con prisa, es exactamente cuando peor viene. Lo
que el borrador evita es que alguien la ejecute, no que se revise. Y al publicar
se **revalida**, porque entre guardar el borrador y publicarlo pueden haber
pasado semanas y lo que valía entonces puede apuntar a una tabla de decisión que
ya no existe.

**Archivar no para nada.** Las instancias en vuelo terminan con la versión con
la que empezaron; lo que impide es que se arranquen nuevas, que es de lo que se
trata cuando un proceso se retira. Cortar una instancia a mitad dejaría su
compensación sin ejecutar, que es peor que dejarla terminar.

Y no se vuelve de archivada a publicada. Si hace falta, se publica una versión
nueva: resucitar una archivada haría que el historial dejara de explicar por qué
una instancia siguió el camino que siguió.

### El lienzo ES la definición (`CRM-00.03.05.01`, `CRM-00.03.05.02`, `CRM-00.03.02.02`)

No hay dos documentos. El JSON es la definición y el diagrama es **una lectura
de ese mismo JSON**: se escribe el proceso a mano y se abre como diagrama, o se
mueve en el lienzo y se lee como código. Las dos direcciones, y eso es lo que
hace que «intercambiables» sea cierto y no una forma de hablar.

Lo único que el lienzo añade son las **posiciones de las cajas**, y van dentro de
la propia definición bajo `grafico.posiciones`. El motor las ignora. Guardarlas
aparte obligaría a sincronizar dos documentos y, el día que se desincronizaran,
el diagrama enseñaría un proceso que no es el que se ejecuta — que es exactamente
el fallo por el que un diagrama deja de ser fiable y la gente vuelve a leer el
código.

Tres decisiones del editor:

- **Una definición escrita a mano, sin posiciones, se abre bien.** Se colocan por
  capas, según la distancia al inicio. Sin eso se podría ir del gráfico al código
  pero no al revés, y entonces no serían intercambiables.
- **La posición guardada manda sobre la automática, paso a paso.** Añadir un paso
  nuevo a un proceso ya colocado no reordena todo lo demás, que es lo que hace
  que nadie vuelva a tocar el diagrama.
- **Un paso inalcanzable se dibuja igual.** Esconderlo haría imposible arreglarlo
  desde el propio editor, que es donde se está cuando se descubre.

Las salidas de un paso se leen con la **misma lista de enlaces** que usa el
validador del servidor. Si aquí faltara una, el diagrama enseñaría un proceso con
menos caminos de los que tiene — y el que falta sería justo el que nadie revisa.

Y el editor **valida y simula sin publicar** (`CRM-00.03.05.04`). Es el punto
entero de la pantalla: un error descubierto aquí es un mensaje, y descubierto en
ejecución es un proceso a medias en producción con su compensación pendiente.

---

## 44. Automatizaciones con ramas, bucles y variables (`CRM-00.03.03.04`)

Una automatización deja de ser una lista de acciones en cuanto alguien necesita
«si el importe pasa de X avisa, y si no asigna» o «por cada línea, comprueba
stock». Eso ya se puede escribir, con tres piezas nuevas: `si`, `para_cada` y
`fijar`.

Van como **acciones de control** y no como acciones normales, porque el motor
las interpreta en vez de delegarlas en un ejecutor. Confundirlas llevaría a
buscar un «ejecutor de si» que no existe ni debe existir.

### La misma gramática de condiciones para disparar y para ramificar

La rama usa exactamente la misma que decide si la regla salta. Dos gramáticas en
el mismo motor —una para cada cosa— es garantía de que se comportarán distinto
ante el mismo dato, y nadie sabrá cuál mira qué.

### Tres topes, y ninguno es decorativo

**Las vueltas de un bucle** (`AUTOMATIZACION_MAX_VUELTAS`, 200 por defecto).
Guardar una oportunidad con seiscientas líneas dispararía seiscientas acciones y
el usuario vería un formulario congelado sin saber por qué. Y cuando se corta,
**se dice en la traza**: una iteración cortada en silencio es peor que no
tenerla, porque el resultado parcial parece completo — alguien ve
«automatización disparada» y da por hecho que recorrió las seiscientas.

**El anidamiento** (`AUTOMATIZACION_MAX_ANIDAMIENTO`, 3). Tres niveles cubren
todo lo que alguien construye en una interfaz; más que eso es un proceso, y para
eso está el motor de procesos, que sabe reanudar y compensar — cosas que una
automatización no hace ni debe intentar.

**La cascada entre reglas**, que ya estaba: una regla que dispara otra que
dispara la primera.

### Las variables no se escapan

El ámbito arranca como una **copia** de los valores del registro. Escribir sobre
el original haría que una regla contaminara a la siguiente, y el síntoma —«esta
regla funciona sola pero no cuando corre después de aquella»— es de los caros de
encontrar.

Una acción puede guardar su salida con `guardar_en`, y así encadenar «crea el
registro y luego notifica sobre él» sin volver a buscarlo. Los nombres que
empiezan por `_` están reservados, y una variable no puede llamarse como un
campo del registro: lo taparía para el resto de la regla, y el efecto no se ve
leyendo la regla.

Las variables que quedan al terminar van **a la traza**, recortadas: sin ellas
«¿por qué entró por esta rama?» no se puede contestar, y contestarlo es la única
razón de que este motor deje traza también de lo que **no** se disparó. Se
recortan porque una variable puede acabar conteniendo la respuesta entera de una
API, y la traza se consulta para entender una decisión, no para recuperar datos.

---

## 45. Campos calculados y agregados sobre hijos (`CRM-00.04.01.04`)

Dos cosas distintas que suelen contarse juntas: una **fórmula** mira el propio
registro —«importe por 1,21», «días desde el alta»— y un **rollup** mira los que
cuelgan de él —«total de las líneas», «número de contactos activos»—.

### La fórmula la escribe quien configura, no quien programa

Eso decide todo lo demás: la fórmula es **entrada del tenant**, y evaluarla con
`eval()` sería ejecutar código del cliente dentro del proceso del servidor, con
acceso a todo lo que el proceso ve. Así que hay gramática cerrada y analizador
propio, y lo que no está en la gramática no se puede escribir.

Lo que queda cerrado y por qué: atributos e índices, porque con `.__class__` se
llega al intérprete; funciones anónimas, por lo mismo; y la potencia `**`,
porque `9**9**9` cuelga el proceso sin necesidad de llegar a ningún sitio y no
hay ninguna fórmula de negocio que la necesite. Hay además un tope de partes:
mil nodos es alguien pegando algo generado, y evaluarlo en cada fila de un
listado convierte una lista en una espera.

La gramática es pequeña a propósito. Cubre lo que se pide de verdad —sumar,
concatenar, redondear, decidir entre dos valores, días entre fechas— y no
intenta ser un lenguaje. Una fórmula que necesita bucles no es un campo
calculado: es una automatización, y ahí sí hay motor con topes y traza (§44).

Tres decisiones sobre qué pasa cuando algo falta o falla:

- **Un campo vacío da vacío, no cero.** Tratarlo como cero haría que «media de
  descuento» contara los registros sin descuento, que es otra respuesta y nadie
  la ha pedido.
- **Un campo que no existe no rompe la fórmula.** Los campos opcionales están
  vacíos la mayor parte del tiempo.
- **Una fórmula rota devuelve vacío y se registra; no lanza.** Propagar el error
  convertiría una fórmula mal escrita en una ficha que no se puede abrir.

Y se valida **al guardar el campo**, no al leer el primer registro: descubrirla
rota al leer es una ficha inaccesible con la persona que la escribió ya lejos.

### El rollup se calcula en SQL y no se guarda

**En SQL**: traer las líneas para sumarlas en el proceso son N filas por cada
registro de un listado —veinte cuentas con cincuenta contactos cada una son mil
filas para pintar una columna—. Y **de golpe** para todos los padres de la
página: pedirlos uno a uno es el patrón N+1 con otro nombre, y con esto un
listado de doscientas cuentas con tres rollups son tres consultas.

**No se guarda**, y es deliberado: guardarlo obliga a recalcular cada vez que
cambia un hijo, y el día que falle un recálculo el padre queda con un número
viejo que parece bueno. Un total que miente es peor que uno que cuesta una
consulta.

El vacío **no es siempre cero**. `suma` y `cuenta` valen 0 —«ninguna línea» suma
cero— pero `maximo`, `minimo` y `media` valen vacío, porque el máximo de un
conjunto vacío no existe. Devolver cero ahí haría que un listado ordenado por
«última actividad» pusiera arriba justo a quien no tiene ninguna.

La función de agregación sale de una **lista cerrada**: dejar pasar el nombre de
una función de SQL desde la configuración del tenant es ejecutar SQL arbitrario
con otro nombre. Y el filtro lo construye el **servicio dueño** con sus propios
modelos, porque el único que sabe qué significa «activo» para un contacto es
quien tiene ese modelo delante.

Por último, una columna real **manda sobre** un rollup del mismo nombre. Al
revés, un campo de configuración podría tapar un dato del registro y el síntoma
sería una ficha que enseña un número que no está en la base.

---

## 46. Ocultos, bloqueados, y el dato que falta abriendo la puerta

Dos añadidos al ABAC (§40) que salieron juntos, y un agujero que apareció al
probarlos.

### Un registro bloqueado no es un registro escondido (`CRM-00.05.02.09`)

Hasta ahora una política de alcance `registro` hacía desaparecer lo que no se
puede ver. Eso está bien cuando la existencia misma es confidencial, y está mal
en casi todo lo demás, porque **los recuentos mienten**: la ficha de una cuenta
dice «5 oportunidades», el listado enseña 3, y quien lo ve concluye que el
sistema ha perdido dos.

Con el alcance `bloqueado`, el registro **se ve existir** con los campos que la
política deje visibles —normalmente el identificador y poco más— y sin detalle.
El recuento cuadra, se ve que hay algo que no se puede abrir, y quien lo
necesita sabe a quién pedírselo. Eso es información distinta de «no hay nada».

Una política de bloqueo **tiene que decir qué campos sí se ven**: un registro
bloqueado del que no se ve nada es un registro escondido con otro nombre.

Y un detalle de implementación que es fácil equivocar: lo bloqueado es lo que
**no** cumple la política, así que la condición se **niega**. Sin negarla se
bloquearía justo lo que se puede ver — y es el error más difícil de notar,
porque el listado sigue teniendo el mismo número de filas.

### Restringir por unidad, marca, país o canal (`CRM-00.05.02.08`)

Las cuatro dimensiones habituales vienen declaradas, con el atributo del
registro y el del usuario que tienen que coincidir. No es por comodidad:
escritas a mano, la mitad acaba comparando el campo equivocado —el `pais` del
registro contra el `pais` del usuario, cuando el del usuario es el de su oficina
y no el de su cartera— y el resultado es una política que restringe de más o de
menos sin que nadie sepa cuál.

Se devuelve la política **construida pero sin guardar**: quién la activa y con
qué alcance —esconder o bloquear— es una decisión de negocio, no algo que se
pueda dar por hecho.

### El agujero: dos ausencias no son una coincidencia

Al probar la primera restricción por unidad de negocio apareció esto. Una cuenta
sin unidad y un usuario sin unidad: `registro.business_unit_id =
@usuario.business_unit_id` con las dos vacías daba **cierto**. En SQL peor
todavía, porque `columna = NULL` se traduce a `IS NULL` y la política dejaba
pasar exactamente los registros que tampoco tenían el dato.

Es decir: **el dato que falta abría la puerta**. En una regla que restringe eso
es un agujero, y en una que comparte es un acceso que nadie concedió.

Ahora dos ausencias comparadas con `=` dan falso, en Python y en SQL, que es lo
que mantiene coherentes la ficha y el listado. Y cuando el atributo del usuario
viene vacío, la condición se traduce a «ninguno» y se registra: en una
restricción, ante la duda, no se enseña.

---

## 47. Quien se lleva los datos casi nunca entra por la puerta (`CRM-00.05.03.06`, `CRM-00.05.03.08`)

El robo de datos de un CRM casi nunca es una intrusión: es alguien de dentro,
con permiso para leer, que se lleva más de lo que le toca. **Los permisos no lo
ven** —está haciendo exactamente lo que puede hacer— así que hace falta mirar
cuánto y cuándo, no solo qué.

### El umbral se mide contra el patrón de cada uno

Cincuenta registros son una exportación normal en un tenant con doscientos
clientes y un incidente en uno con veinte mil; y dentro del mismo tenant, lo
normal de quien lleva la migración no es lo normal de un comercial. Un número
fijo produce o ruido o silencio, y las dos cosas acaban igual: «esto siempre
salta», y alguien lo apaga.

Así que se compara con **la media de esa persona**, calculada sobre su propio
historial de las últimas dos semanas. Y no se avisa cuando no hay historial
suficiente: con dos datos, cualquier tercero parece una anomalía, y un sistema
que avisa de todo el mundo el primer día se desactiva la primera semana.

Encima de eso hay dos topes duros, que son la red de arriba: registros por
exportación —para que nadie se lleve la base entera de una vez aunque lleve
meses acostumbrando al sistema— y **exportaciones por hora**, porque quien de
verdad se está llevando datos trocea para no disparar el tope por volumen.

### Bloquear es opcional; registrar, no

Bloquear una migración legítima cuesta tanto como dejar pasar una fuga, y esa
decisión es del cliente: `DLP_BLOQUEAR` viene apagado. Lo que no es opcional es
que **quede registrado**, incluso lo bloqueado — una exportación sin rastro es
la que no se puede investigar después.

Y una distinción que importa: superar un tope duro puede bloquear, pero
**salirse del patrón solo avisa**, aunque el bloqueo esté activo. Salirse de lo
habitual no es ilegítimo —el día del cierre todo el mundo exporta más— y cortarlo
pararía trabajo real.

### Se apuntan también las permitidas

Y sobre todo esas: el patrón de mañana se calcula con lo de hoy, así que apuntar
solo lo sospechoso haría que la media fuera la media de lo sospechoso.

Todo va al **audit trail**, que ya existe y ya es inalterable. No hay tabla nueva
de alertas a propósito: sería un segundo registro de lo mismo que podría
discrepar del primero, y el primero es el que tiene la cadena de hashes.

### Dónde está puesto hoy, y dónde no

Está en la **exportación de tenant**, que es la salida de datos más grande del
sistema, y se comprueba **antes** de volcar nada: comprobarlo después serviría
para el informe forense y no para impedir nada.

Lo que **no** cubre todavía, dicho: alguien paginando un listado doscientos
registros cada vez, mil veces. El tope por hora no lo ve porque un listado no es
una exportación. Cerrar eso exige contar registros servidos por usuario en la
capa de paginación, y está anotado como pendiente en vez de dado por hecho.

---

## 48. Sacar el dato del sistema sin perder el rastro

Cuatro piezas de la misma idea: el dato sale por sitios que no son un ataque —una
copia de preproducción, un CSV que alguien reenvía, un volcado al SIEM, una
consulta de soporte— y en todos hay que saber qué salió y de dónde.

### Preproducción con datos reales es la fuga que nadie llama fuga (`CRM-00.05.03.05`)

Un entorno de pruebas con datos de clientes es una copia de la base en una
máquina con menos vigilancia, más gente dentro y sin las mismas políticas. Se
anonimiza, y dos decisiones deciden si sirve:

**Es consistente.** El mismo valor da siempre el mismo sustituto dentro del mismo
entorno. Sin eso, el correo de un contacto sería distinto en la tabla de
contactos y en la de actividades, las relaciones se romperían y el entorno no
serviría para probar nada — que es como acaban reponiendo los datos reales «solo
esta vez».

**No es reversible.** El sustituto sale de un HMAC con una sal **del entorno**,
no de un cifrado: si se pudiera deshacer, el entorno seguiría conteniendo los
datos con un paso más. Y la sal es por entorno, así que juntar dos copias con
campos distintos anonimizados no devuelve el registro.

La forma se conserva —un correo sigue pareciendo un correo— porque un entorno
donde los correos son «xxx» no sirve para probar el envío de correos, que es
justo lo que se prueba ahí. Y el vacío se queda vacío: inventar un correo donde
no había cambiaría los recuentos de completitud y alguien concluiría que
preproducción tiene mejores datos que producción.

Qué se anonimiza sale de la **sensibilidad declarada en el modelo**, no de una
lista: con una lista, el campo nuevo entraría con dato real sin que nadie lo
decidiera. Y la fila se copia antes de sustituir: hacerlo sobre el objeto de
SQLAlchemy lo marcaría como sucio y el siguiente `flush` escribiría los valores
anónimos **en producción** — el peor accidente imaginable de una herramienta
cuyo propósito es proteger datos.

### De dónde salió este fichero (`CRM-00.05.03.07`)

El audit trail dice quién exportó. La marca de agua dice **de dónde salió este
fichero**, que es otra pregunta y se hace en otro momento: cuando la hoja con la
cartera aparece en el ordenador de un competidor, el audit trail de quien la
perdió no está disponible.

Va **dentro del fichero**, no en el nombre ni en una cabecera HTTP: las dos se
pierden en cuanto alguien lo reenvía, que es justo cuando hace falta. En un CSV
como comentario arriba, en un JSON Lines como primera línea, en un texto arriba y
abajo —porque el recorte de las primeras líneas al pegar un fragmento en un
correo es lo más habitual, y el del final también—.

El identificador del usuario va **resumido** y no en claro: el fichero puede
acabar en manos de cualquiera y el identificador en claro es un dato de la
plantilla del cliente. Resumido sigue sirviendo para cotejarlo con el audit
trail, que es para lo que hace falta.

Y lo que **no** es: una protección. Quien sepa que está ahí la quita. Lo que
hace es cerrar el caso más común con diferencia y dejar constancia de que el
fichero salió identificado.

### Retención del log y volcado a SIEM (`CRM-00.05.04.04`)

Un audit trail que crece para siempre acaba siendo la tabla más grande y la más
lenta de consultar, y entonces se deja de consultar. Pero borrarlo rompe la
cadena de hashes, que es lo que lo hace verificable.

Se purga **por tramos completos desde el principio**, nunca por el medio, y
**antes de borrar se apunta qué se borra y hasta dónde**, en un apunte que queda
dentro de la cadena nueva. Así quien verifique encuentra el corte explicado en
vez de un hueco que parece manipulación. El apunte va antes del borrado a
propósito: después, el primer apunte tras la purga no tendría con qué encadenarse
y la verificación fallaría en el sitio equivocado.

El volcado va en **JSON Lines con nombres neutros** y no en el formato de un
producto: escribir el de uno ata la instalación a ese uno, y el adaptador de
cualquier SIEM son veinte líneas. Viajan la secuencia y los hashes, que es lo que
permite a quien lo reciba comprobar que no falta nada por el camino. Y se
devuelve como flujo, porque un año de audit trail no cabe cómodamente en memoria.

### Preguntarle al audit trail desde aquí (`CRM-00.05.04.05`)

`GET /api/v1/grc/auditoria`, filtrable por acción, objeto, actor y fechas. Desde
la propia plataforma y no exportando a otro sitio: «¿quién tocó esta cuenta?» se
pregunta mientras se mira la cuenta, y obligar a salir a otra herramienta
significa que casi nunca se responde.

---

## 49. Engancharse al CRM sin bifurcarlo (`CRM-00.04.02.02`, `CRM-00.04.02.03`)

Un CRM al que no se le puede enganchar nada obliga a modificarlo para cada
cliente, y a los dos años hay cinco versiones del producto. Hay dos formas, y la
diferencia no es de estilo.

**Síncrono** (`antes_de` / `despues_de`): corre dentro de la transacción del
cambio. Sirve para lo que tiene que **decidir** —rechazar un guardado, completar
un campo— y por eso mismo es peligroso: lo que falle aquí tumba la operación del
usuario.

**Asíncrono** (`al_ocurrir`): corre fuera, sobre el evento ya publicado. No puede
rechazar nada porque el cambio ya pasó, y a cambio no puede romperlo.

La regla, dicha una vez: **si puede esperar, es asíncrono**. La tentación de
hacerlo todo síncrono —«así lo tengo hecho al volver»— es lo que convierte un
guardado de 80 ms en uno de dos segundos que a veces falla por algo que no tiene
nada que ver con guardar.

Tres decisiones dentro de eso:

- **Antes puede rechazar; después, no.** Un hook posterior que falla se registra
  y sigue. Propagar haría que el usuario viera un error sobre algo que **sí** se
  guardó, y la próxima vez lo volvería a intentar duplicándolo.
- **Un hook lento se avisa, no se corta.** Cortarlo a mitad dejaría la operación
  en un estado que la extensión no esperaba. Lo que hace falta es saber quién
  está frenando el guardado.
- **Una extensión asíncrona rota no para el bus.** Si se propagara, una mal
  escrita bloquearía la cola para todas las demás y el sistema se pararía entero
  por algo que es de un tenant.

Y un detalle del comodín que parece menor: `cuenta.*` casa con `cuenta.creada` y
**no** con `cuenta_borrador.creada`. El punto es parte del prefijo a propósito;
sin él, una extensión escucharía objetos que no son el suyo.

---

## 50. Que un tenant saturado no se lleve a los demás por delante

Las cuotas dicen **cuánto** puede consumir cada cliente al mes. Esto es otra
cosa: qué pasa **ahora mismo** cuando uno satura un recurso compartido y los
demás esperan detrás. Las cuotas no lo ven, porque nadie ha superado la suya —
simplemente están todos pidiendo a la vez.

Tres mecanismos, y los tres responden a la misma idea: **fallar rápido y
parcialmente es mejor que esperar y caer entero**.

### Mamparos, por tenant y no globales (`CRM-00.01.06.03`)

Cada tenant tiene un número máximo de operaciones simultáneas sobre un recurso.
**Por tenant** es la decisión que importa: un tope global protege el sistema y
no protege a los clientes entre sí, que es el problema de verdad en
multi-tenant. Con tope global, el que lanza doscientas importaciones ocupa el
cupo y los demás esperan detrás sin haber hecho nada — y lo que ven es un error
de conexión, que no dice nada y manda a buscar el fallo a la base de datos.

El cupo **se libera aunque la operación falle**. Si no, un error deja el cupo
ocupado para siempre y el tenant no puede trabajar hasta que alguien reinicie el
proceso.

### Cortacircuitos

Un recurso que falla repetidamente deja de intentarse durante un rato.
Reintentar contra algo caído no lo arregla y sí consume el hilo que lo intenta:
es como la caída de un servicio se convierte en una caída total.

Dos detalles que deciden si funciona: **un éxito borra el historial**, porque lo
que importa son los fallos *seguidos* —contar acumulados abriría el circuito de
un recurso que va bien simplemente porque lleva meses funcionando—; y al
cerrarse el circuito **queda a un fallo de reabrirse**, no a cero. Si sigue roto,
el primer intento vuelve a abrirlo en vez de tener que fallar el umbral entero
otra vez, que serían N veces el mismo *timeout* para todos los que pasen.

### Degradación por prioridad (`CRM-00.01.06.04`)

Bajo presión se difiere lo que puede esperar en vez de rechazarlo todo por
igual. Rechazar una escritura de cliente y un recálculo de previsión con el
mismo criterio es tratar como iguales dos cosas que no lo son: una la está
haciendo alguien delante de la pantalla y la otra puede esperar diez minutos sin
que nadie lo note.

Lo crítico —escrituras de usuario, autenticación— **no cae nunca**. Lo diferible
cae primero. Y la presión la declara quien la mide —el gateway con su latencia,
el worker con su cola— en vez de calcularse en un sitio central que tendría que
adivinar la saturación de todos.

### Modo solo lectura (`CRM-00.06.02.07`)

Convierte una avería de la base primaria en «no se puede guardar» en vez de en
«el CRM no funciona». La diferencia importa: con lectura, el comercial que está
delante de un cliente sigue viendo su ficha.

El mensaje **dice el motivo**, y eso no es cortesía: sin él, el usuario cree que
su cambio tenía algo malo y lo reintenta cambiándolo, que es como se pierde
trabajo durante una incidencia.

---

## 51. Tres cosas más que se notan poco y se echan de menos mucho

### Varias operaciones en una llamada (`CRM-00.02.01.13`)

Crear una cuenta, añadirle un contacto y abrirle una oportunidad son tres
llamadas y tres viajes de red. Desde un móvil con mala cobertura, tres ocasiones
de quedarse a medias — y quedarse a medias aquí es una cuenta sin contacto que
alguien limpiará a mano.

**Todo o nada, en una transacción**: si la tercera falla, las dos primeras se
deshacen. Sin esa garantía, agrupar solo ahorra latencia y añade una forma nueva
de dejar datos a medias. Y **las operaciones se refieren entre sí** con `$1.id`,
porque la segunda necesita el identificador que generó la primera y sin eso
agrupar no sirve para el caso que motiva agrupar.

Solo hacia atrás: referirse a una operación posterior o a sí misma se rechaza
**antes** de correr nada, porque descubrirlo a mitad deja la transacción abortada
y al cliente con un error que no dice cuál de sus operaciones estaba mal. Y una
referencia a un campo que no vino se deja visible en vez de sustituirse por
vacío: poner vacío crearía la fila incompleta y nadie lo notaría hasta semanas
después.

No es un lenguaje: no hay condiciones ni bucles. Una secuencia que necesita
decidir es un proceso, y para eso está el motor que sabe reanudar y compensar.

### Los eventos de un mismo registro, en orden (`CRM-00.02.02.08`)

El relevo publicaba por fecha, y eso **no** garantiza el orden por registro: si
el primer evento de una cuenta falla y se reintenta con espera, el segundo sale
antes. Quien lo consuma ve «cuenta actualizada» antes que «cuenta creada» y, si
su manejador es idempotente por identificador, se queda con el estado viejo para
siempre.

Ahora sale **un evento por agregado y vuelta**: el segundo no sale hasta que el
primero se publica o se aparta a la cola de fallidos. El coste es que un registro
muy activo avanza a un evento por vuelta, y se acepta porque el desorden no se
nota hasta que alguien investiga por qué un dato está mal — y entonces ya no se
puede reconstruir. Se puede apagar para quien prefiera el rendimiento y tenga
consumidores que no dependan del orden.

### Acceso por IP, dispositivo y horario (`CRM-00.05.01.09`)

El ABAC decide por atributos del usuario y del registro; esto añade los del
**momento**, que son los que cambian entre una sesión legítima y la misma
credencial usada por otro.

Se comprueba **en cada petición y no al entrar**: comprobarlo solo en el login
deja la sesión abierta cuando las condiciones dejan de cumplirse, y el caso que
se quiere cubrir es exactamente ese.

Y una señal que no llega **no bloquea**. Una IP ausente porque hay un proxy mal
configurado delante dejaría fuera a toda la plantilla, y eso es una caída con
otro nombre: se registra y la regla que dependía de ella no aplica. Lo que sí
bloquea es una **red mal escrita**, porque tratarla como comodín convertiría un
error de tecleo en una lista de permitidos vacía.

La franja horaria admite cruzar medianoche —de 22 a 6— porque el turno de noche
existe y escribirlo al revés es el error más común al configurar esto. Y una
lista vacía significa «no se comprueba», no «ninguno»: lo contrario es la forma
más rápida de dejar fuera a todo el mundo el día que alguien crea la regla sin
rellenarla.

---

## 52. El metamodelo cuando el cliente lleva un año configurando

Cuatro cosas que aparecen siempre en el mismo momento: cuando el esquema empieza
a pesar y ya hay integraciones enganchadas.

### Dos que ya estaban y no se habían declarado

`GET /metadata/objetos/{nombre}/describe` devuelve **campos, validaciones,
layouts y los permisos de quien pregunta** (`CRM-00.02.03.06`), que es todo lo
que necesita una interfaz para renderizar sin saber nada del CRM. Y
`POST /metadata/objetos/{nombre}/validar` ejecuta **las mismas** reglas que al
guardar sin escribir nada (`CRM-00.02.03.07`), para que un frontend enseñe los
errores antes de enviar en vez de reimplementarlos — que es como acaban
divergiendo del servidor.

Estaban construidas y sin marcar. Se declaran ahora, con su cita, en vez de
dejarlas contando como pendientes: un catálogo que no reconoce lo que hay es tan
inexacto como uno que declara lo que no hay.

### Tipos de registro (`CRM-00.04.01.05`)

El mismo objeto con caras distintas. Una cuenta de empresa y una cuenta pública
no comparten campos ni listas, y las dos alternativas son peores: modelarlas como
dos objetos rompe los informes —«cuántos clientes tengo» deja de tener una
respuesta— y modelarlas como uno solo llena la ficha de campos que sobran en la
mitad de los casos.

Un tipo guarda **los campos que NO usa**, no los que usa. Así un campo nuevo
aparece en todos los tipos por defecto, que es lo que se quiere el noventa por
ciento de las veces, en vez de en ninguno.

Y solo puede haber **uno por defecto**: dos dejarían el alta sin saber cuál usar,
y el que ganara dependería del orden de la consulta, que cambia sin avisar.

### Límites del esquema (`CRM-00.04.01.09`)

Un esquema sin techo llega a doscientos campos por objeto, y entonces van lentos
a la vez la ficha, el listado, la exportación y las migraciones. El techo no está
para fastidiar: **está para que la conversación ocurra antes de que el sistema
vaya mal**, y no después.

Se devuelve el porcentaje además del número, y no es cosmética: nadie sabe si 140
campos son muchos, y todo el mundo entiende «vas por el 70 %». El aviso llega al
80 %, con margen para replantear el modelo. Y el error de tope **dice cuál es el
tope**: «has llegado al límite» sin decir cuál obliga a buscarlo, y quien lo lee
está justo en mitad de configurar algo.

### Renombrar sin romper a nadie (`CRM-00.04.01.10`)

Renombrar un campo en un CRM con integraciones no es renombrar una columna. Hay
clientes mandando el nombre viejo, y cortarles el día del cambio convierte una
mejora en una incidencia.

El cambio pasa por una fase en la que **los dos nombres funcionan**, y cada uso
del viejo **se cuenta**. Contar es la parte que importa: es lo que permite
decidir cuándo se retira **midiendo** en vez de suponiendo. Con una fecha, el día
que toca siempre hay alguien usándolo.

Si llegan los dos a la vez, **manda el nuevo**: quien ya se ha migrado no puede
verse pisado por un campo viejo que su cliente sigue mandando por inercia.

### La lista de IP por credencial, y el agujero que tenía (`CRM-00.02.04.04`)

El acceso contextual (§51) acota a una **persona**; esto acota a una **llave**.
No es un matiz: una clave de integración vive en un servidor que no se mueve
nunca, así que su lista puede ser de una sola dirección — y eso convierte una
clave robada en una clave inútil fuera de ese servidor. La misma restricción
sobre una persona sería inservible, porque las personas se mueven.

Va en la credencial y no en el tenant, porque un tenant con veinte integraciones
en veinte sitios tendría que permitir las veinte direcciones a todas, con lo que
cada clave valdría desde donde valen todas las demás.

Y había dos agujeros en la comprobación que ya existía:

- **No entendía redes.** Comparaba cadenas, así que `10.0.0.0/8` no casaba nunca
  con `10.1.2.3`: quien declaraba una red se quedaba sin acceso y acababa
  poniendo direcciones sueltas o quitando la lista.
- **Sin IP no comprobaba nada.** Una llamada detrás de un proxy que no propaga la
  dirección —o que la suprime a propósito— se saltaba la lista **entera**. Una
  restricción que se desactiva omitiendo un dato no es una restricción.

Ahora entiende redes y, con lista declarada, la falta de dirección corta. Una
red mal escrita se ignora y se registra, pero **no** se trata como comodín:
tratarla así convertiría un error de tecleo en una lista vacía. Y la lista se
valida **al guardarla**, porque descubrir una red mal escrita en la primera
llamada deja la integración caída y a nadie mirando, ya que quien la configuró se
fue.
