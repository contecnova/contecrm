# Manual III — Referencia funcional

Qué hace hoy contecrm, capacidad por capacidad, con el identificador del
[catálogo funcional](catalogo/catalogo.yaml) entre paréntesis. Ese identificador
es la clave de trazabilidad: desde él se llega al código que lo implementa y a la
prueba que lo sostiene.

> **Qué significa que algo esté aquí.** Solo se documenta lo que está
> **implementado y probado**; lo que no está, no aparece. El recuento vivo —cuánto
> hay hecho, cuánto queda y en qué estado está cada capacidad— es
> [el estado del catálogo](catalogo/estado.md), que se regenera desde el propio
> catálogo y no se escribe a mano. Aquí no hay cifras de progreso a propósito:
> una cifra escrita en un texto se queda vieja el día siguiente.

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
lead?» no tiene respuesta, y es la pregunta que más se hace. La traza guarda
además **con qué variables acabó** la ejecución, en su propia columna.

> **Hasta el 26-10-2026, una regla que SÍ cumplía sus condiciones no llegaba a
> terminar.** Las variables finales se metían dentro de `decisiones` —que es
> una lista, una entrada por condición— con un desempaquetado de diccionario, y
> eso revienta con «'list' object is not a mapping». O sea que sólo pasaban las
> ejecuciones que **no** se disparaban; en cuanto una condición se cumplía, la
> automatización fallaba al final.
>
> Salió al escribir la prueba de que una regla por debajo del tope de cascada
> sí se ejecuta. Arreglado con una columna propia y su migración.

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

#### Llevar la configuración de un entorno a otro (CRM-00.04.03.10)

`GET /api/v1/metadata/paquete` exporta el esquema; `POST .../paquete/instalar`
lo instala en otro. Tres cosas que conviene saber antes de usarlo:

- **Lleva configuración y nunca datos.** Un paquete que arrastrara registros
  convertiría una promoción a producción en una fuga: los datos de pruebas
  suelen ser copias anonimizadas a medias de clientes reales.
- **Simula por defecto.** Instalar de verdad hay que pedirlo (`simular: false`).
  Un paquete es un cambio de modelo de datos en producción, y el error más caro
  de quien lo maneja es pulsar el botón creyendo que todavía estaba mirando.
- **Lo que ya existe con otro tipo no se pisa**: se informa y se deja fuera.
  Sobrescribir lo que alguien ajustó en producción con lo de un entorno de
  pruebas es la forma habitual de perder dos semanas de trabajo de un consultor.

Instalar **no publica**: el cambio queda puesto y no llega al resto de servicios
hasta que alguien lo decide.

#### Antes de publicar, qué se rompe (CRM-00.04.03.09)

`POST /api/v1/metadata/objetos/{nombre}/previsualizar` compara el esquema de
ahora con **la última publicación** y dice qué se añade, qué se retira y qué
cambia. Lo que de verdad evita una tarde mala:

- cuántos registros se quedan **sin rellenar** un campo que pasa a obligatorio;
- qué campo **cambia de tipo** — los valores ya guardados no se convierten, así
  que dejan de validar, y eso no falla al publicar: falla la próxima vez que
  alguien guarda un registro viejo;
- y cuándo **no ha podido contar**. «No se ha podido contar» y «no afecta a
  nadie» son cosas distintas, y la diferencia es justo la que importa aquí.

#### Cuándo un campo a medida merece una columna de verdad (CRM-00.04.03.11)

`GET /api/v1/metadata/objetos/{nombre}/candidatos-columna` dice qué campos lo justifican, con su
número de escrituras y el umbral aplicado. **Se decide con una medida y no con
una intuición**: sin número, cada cliente que note su lista lenta pediría
columna, y acabaríamos con el `ALTER TABLE` de siempre disfrazado de
optimización — y un `ALTER TABLE` en una tabla compartida por mil tenants los
bloquea a todos.

El camino normal es el JSONB con índice de expresión; esto es la excepción. La
respuesta lleva dentro el orden en que se hace: se añade la columna nullable (no
bloquea), se rellena por lotes desde el JSONB, se crea el índice y **sólo
entonces** se empieza a leer de ella. Al revés, la columna se lee vacía mientras
se rellena y las listas salen incompletas sin que falle nada.

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

> **Auditada entera el 26-10-2026**, recorriendo las rutas, y sin hallazgos. La
> propiedad que se fijó es la que justifica el subsistema: **el listado y la
> ficha dicen lo mismo**. Son dos caminos distintos —la ficha evalúa la política
> en Python sobre el registro y el listado traduce la misma condición a SQL— y
> el fallo clásico de estos sistemas es que discrepen: un registro invisible en
> la lista y accesible por su identificador, o al revés.
>
> Se comprobó con una política puesta: la cuenta tapada desaparece del listado y
> su ficha contesta 403 **con la política que decide dentro**. Y se comprobó que
> el ABAC se aplica también a quien administra, que es justo a quien se le pone.
> Validado plantando el caso malo: haciendo que el listado deje de filtrar, caen
> las dos pruebas.
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

**Nada.** Todo lo que consta como hecho cumple su enunciado, tiene prueba que lo
cita y está explicado aquí; lo que no está hecho consta como pendiente y no
aparece en este manual.

Esta sección existía con seis capacidades dentro, y la mitad de ellas eran texto
viejo: estaban terminadas y nadie había quitado la fila. Las otras cuatro
faltaban de verdad —el SLO no lo alimentaba nadie, la restauración selectiva no
tenía ni una ruta que llegara hasta ella, el RAT salía vacío porque ningún
servicio declaraba sus tratamientos, y el informe de cumplimiento no se podía
pedir— y se han terminado. La sección se queda escrita, y vacía, porque el día
que algo vuelva a quedarse a medias tiene que haber un sitio donde decirlo.

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
- Y **dos formas jurídicas distintas no son un duplicado concluyente**. La clave
  de comparación quita la forma jurídica —y tiene que quitarla, para que «García
  SL» y «García, S.L.» se reconozcan—, lo que deja «García SL» y «García SA» con
  la misma clave. Son dos entidades, con dos NIF y dos contabilidades, y
  fusionarlas es caro de deshacer. No se descartan: bajan de bloqueo a
  sugerencia y se dice por qué, porque también pasa que una de las dos esté mal
  escrita.
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
`contecintelligence`, **creada al provisionar y sin que nadie tenga que
acordarse** (CRM-05.01.04.02): dar de alta un cliente emite el aviso de alta y la
correspondencia se crea con él. Antes había que asignarla a mano desde una
pantalla de plataforma, así que un cliente nuevo funcionaba hasta que alguien le
preguntaba algo a la explotación del dato — y entonces salía «este tenant no
tiene organización asignada», meses después y con el cliente delante.

**La organización lleva el identificador del tenant, no su nombre comercial**, y
conviene entender por qué, porque parece al revés:

- El identificador **no se puede cambiar**. Va en subdominios, en URLs y en lo
  que los integradores ya tienen guardado, así que el producto no deja
  editarlo. Eso es justo lo que hace falta al otro lado: `contecintelligence`
  solo acepta nombrar organizaciones que tenga dadas de alta, y el nombre que le
  demos hoy tiene que seguir valiendo dentro de dos años.
- El nombre comercial **sí se corrige**: existe una pantalla para arreglarle una
  errata. Si la organización llevara ese nombre, cada corrección dejaría la
  correspondencia apuntando a algo que allí ya no se llama así, y allí no
  podemos renombrar nada.

De ahí sale la respuesta a la pregunta que siempre aparece: **cambiar el nombre
del cliente no cambia nada en `contecintelligence`, y no hace falta que lo
cambie.** No es un cabo suelto: es que la correspondencia se apoya en lo que no
se mueve. Si algún día se quisiera que allí se viera el nombre bonito, eso es un
campo de presentación suyo y no la clave que las une.

La correspondencia nace **pendiente**, no activa. Que exista aquí no significa
que al otro lado la conozcan, y darla por buena sin verificarla haría que el
primer fallo apareciera como «no hay datos» en vez de «falta darla de alta».

Quién pertenece a qué **lo dice el servidor**, no el navegador: si lo dijera un
identificador en la URL, el aislamiento valdría lo que valga el JavaScript de esa
pantalla.

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
docker compose --profile app up -d && python scripts/vecinos.py levantar

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

Y no solo en **qué filas** se ven: también en **qué campos**. Cinco listados
escritos a mano —leads, cuentas, contactos, oportunidades y tenants— serializaban
con su esquema de salida sin pasar por la proyección, mientras su ficha sí pasaba:
un rol que no puede ver datos personales los veía en el listado y no en la ficha
de la misma fila. No daba ningún error. Enseñaba el teléfono. Hay un guardián que
lo mira: un listado que construye su página tiene que pasar por la proyección.

Son dos implementaciones de la misma regla —una en SQL para el listado, otra en
Python para la ficha— y divergen el día que alguien toca una. Cuando eso pasa,
el listado enseña un registro que la ficha luego niega, y el usuario deja de
fiarse de los dos.

Hay una prueba que las compara sobre los mismos datos, con las cinco vías a la
vez: propia, compartida a mano, de equipo, por regla y ninguna. Si alguna vez
divergen, falla ahí y no en producción.

### Y toda colección se puede exportar

A una hoja de cálculo, con **los mismos filtros de la URL** que el listado. Dos
reglas, y las dos cambian lo que sale:

- **Las columnas incluyen los campos propios del tenant.** Sin eso la exportación
  trae lo que traía el producto de fábrica y no lo que el cliente ve en su ficha:
  una diferencia que solo nota quien conoce el dato, y la nota cuando ya ha
  mandado el fichero. Un campo dado de baja no sale: la columna existiría vacía y
  se leería como «no hay dato» en vez de «ya no se usa».
- **No sale en claro lo que la pantalla no enseña.** Pasa por la misma proyección
  que el listado —la sensibilidad por rol, las excepciones y las políticas que
  dependen de la propia fila—, y lo que la proyección quita no aparece en el
  fichero. Un CSV que enseña el teléfono que la ficha tapa es la vía más fácil de
  saltarse la protección, y la más silenciosa.

Y si se llega al tope de filas **se dice**: un fichero cortado en silencio es el
que alguien manda creyendo que lleva todo.

Cada exportación lleva además su **marca de origen** (`CRM-00.05.03.07`), y va
dentro del fichero —no en el nombre ni en una cabecera HTTP, que se pierden al
reenviarlo—. El audit trail dice **quién** exportó; la marca dice **de dónde salió
este fichero**, que es otra pregunta y se hace en otro momento: cuando la hoja con
la cartera de clientes aparece en el ordenador de un competidor, el audit trail de
quien la perdió no está disponible. El identificador de quien exporta va
**resumido**: el fichero puede acabar en cualquier mano y eso es un dato de la
plantilla del cliente. En la exportación completa de un tenant la marca es la
primera línea del JSON Lines, que cualquier lector procesa sin enterarse — y el
manifiesto sigue contando **registros**, no líneas, porque es lo que se compara
con la tabla de origen al recibirla.

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
- **Una tarea vencida avisa una sola vez**, salvo que se pida lo contrario. Un
  aviso diario de la misma tarea enseña a ignorarlos todos.

#### El aviso que insiste, y la tarea que se mueve sola (`CRM-01.02.01.09`)

Lo anterior vale para la mayoría de las tareas y no vale para la que de verdad
importa: esa hay que volver a ponerla delante. Un recordatorio puede pedir
**insistir** cada tantos minutos, y entonces se rearma solo hasta que la tarea se
cierra o se agota el tope.

El tope es **obligatorio**. Sin él, un aviso sigue sonando cuando el proyecto
lleva dos años cerrado, y lo único que se consigue es que la gente aprenda a
cerrar avisos sin leerlos — con lo que deja de servir también el que sí
importaba. Por eso insistir es una decisión de quien crea la tarea y no el
comportamiento por defecto.

Cada aviso dice **cuál de cuántos es**. El tercero llega igual que el primero, y
sin ese dato quien lo recibe no sabe si están insistiendo o si el sistema se ha
atascado. La deduplicación del bus lleva ese número dentro: sin él, el segundo
recordatorio de la misma tarea se descartaría por repetido, que es exactamente lo
contrario de insistir.

Y una tarea que nadie atiende puede **reprogramarse sola**, empujando su
vencimiento. Con dos condiciones que no son negociables:

- **Primero se avisa de que venció y después se mueve.** Moverla en silencio
  haría que la tarea no constara vencida nunca, que es la forma más limpia de que
  no se haga y no lo sepa nadie.
- **Queda escrito quién la movió y cuántas veces lleva.** Una tarea que va por la
  cuarta reprogramación no es una tarea con fecha nueva: es una tarea que nadie
  va a hacer, y eso tiene que verse. También aquí el tope es obligatorio.

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
`python scripts/vecinos.py levantar` lo levanta con SU propio compose —el que
mantienen sus autores, con Qdrant, Redis y MinIO incluidos— o se le da en
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

`DMS_SCOPES` lleva **los dos** alcances (`documents:read` y `documents:search`) y
no es comodidad: contecmind los comprueba en cada petición y separa abrir un
documento de buscar en el corpus. Con solo el primero, la ficha de un documento
funciona y el buscador contesta 403 — que es el fallo que peor se diagnostica,
porque media pantalla va bien.

### Lo que se le manda a contecintelligence: el vocabulario, no solo las rutas

Al registrar el CRM como fuente se manda, por cada listado, **qué es** y **qué es
cada campo**, en las palabras del negocio. No es documentación: es lo único que
permite que una pregunta escrita como se habla encuentre la tabla que toca.

Sin eso —que es como estuvo— las tablas se llamaban como el recurso en la URL:
`accounts`, `contacts`, `proveedores`, `presupuestos`. Mitad en inglés y mitad en
castellano, porque una API real se ha ido escribiendo por partes. Cuarenta y
siete tablas y quinientas treinta y ocho columnas, **ninguna con descripción**.
Preguntando «¿cuántas cuentas hay?» contestaba **7, contando `proveedores`**, con
su tarjeta de indicador y su SQL debajo. La respuesta llegaba con la cara de ser
correcta, así que nadie la iba a comprobar. Hay 64.

El vocabulario no se escribe a mano en la integración: el resumen de cada listado
y la descripción de cada campo ya están en el contrato que publica cada servicio,
puestos por quien escribió la ruta. Se leen de ahí, así que un módulo nuevo llega
con su vocabulario el día que se publica y nadie tiene que acordarse.

Con eso, la misma pregunta contesta 64 con `SELECT count(*) FROM accounts`, que
es **exactamente** lo que la API devuelve a esa persona. En la base hay 65: la
que falta no la ve ese usuario, y la respuesta respeta sus permisos porque los
datos se leen por la API del CRM y no por debajo.

**Y la huella del registro mira lo que se registra.** Miraba solo el modelo
semántico —los campos personalizados de cinco objetos— y lo que se publica son
los listados con su ruta y su vocabulario. O sea que un módulo nuevo, o un
resumen mejorado, no movían la huella: el registro se quedaba viejo diciendo «sin
cambios», y en un tenant sin campos propios —el caso normal— la huella no
cambiaba nunca.

### El árbol de carpetas del corpus

El corpus de contecmind se organiza en **áreas** y, dentro de cada una, en un
árbol de carpetas. contecrm lo recorre con la identidad del usuario, así que el
árbol que ve alguien es el que vería entrando al gestor: **una carpeta denegada
no aparece, ni ella ni lo que cuelga de ella**. Un árbol con huecos no es una
lista incompleta ni un fallo de paginación — es el permiso. Y una rama sin
documentos visibles devuelve cero resultados y no un error: distinguir «vacía»
de «todo denegado» con un código propio ya sería decirle a quien pregunta que
ahí hay algo que no puede ver.

**El área se elige por su NOMBRE, no por su identificador** (`DMS_AREA_NOMBRE`),
y se resuelve al vuelo contra la lista de áreas que ese usuario puede leer. El
identificador de un área es de un tenant, y el fichero de configuración es el
mismo para los tres del despliegue: fijarlo habría apuntado al área de uno y
dejado a los otros dos mirando a un área que no existe o, peor, a una ajena. Un
nombre además sobrevive a copiar la configuración a otra instalación.

Con una sola área visible no hay nada que configurar; con varias y ninguna
elegida, se dice que hay que elegir y se enseñan los nombres. Repartir los
documentos del CRM en el área que tocara ese día sería peor que no guardarlos.

**Cada registro tiene su carpeta**, según la plantilla configurada
(`DMS_CARPETA_PLANTILLA`, `{objeto}/{registro}` de partida). Es configuración
porque la organización del corpus es de cada casa: unos quieren `Clientes/ACME`
y otros `2026/Clientes/ACME`. Se resuelve **una vez** y el identificador se
guarda en el enlace, así que si alguien mueve o renombra esa carpeta en el
gestor el CRM sigue apuntando a la misma y no crea otra al lado con el nombre
nuevo. El nombre que se enseña se pregunta, nunca se copia: una ruta guardada
enseñaría «Clientes / ACME» un mes después de que la renombraran y nadie lo
notaría.

Al traer un documento del corpus desde la ficha de un registro, el servidor
resuelve esa carpeta y coloca allí el documento. Se hace en el servidor y no en
el navegador porque son dos llamadas al gestor —resolver y mover— y partirlas
dejaría el enlace creado y el documento sin colocar en cuanto una fallara a
medias. **Y si colocar falla, se enlaza igual**: el enlace es del CRM y vale por
sí solo. Que no se pueda registrar un contrato en una cuenta porque el corpus
está en mantenimiento sería exactamente la dependencia que este diseño evita.

**Los permisos efectivos de una carpeta son para su ficha, no para un listado.**
El listado de documentos ya viene filtrado, así que preguntarlos por fila sería
pedir dos veces lo mismo y convertir una pantalla de cincuenta filas en
cincuenta llamadas de red. El motivo que da el gestor es un **código** —`area`,
`no_area`, `grant_here`, `grant_above`, `doc_allow`, `doc_deny`— y no una frase:
el gestor no traduce, y una frase suya llegaría en castellano a los otros cinco
idiomas. La traduce el front.

**Resumir una rama o sacar sus conceptos pasa por el modelo de lenguaje**, y eso
tiene su propio plazo (`DMS_TIMEOUT_ANALISIS_S`, minutos) y **solo se pide desde
un trabajo de fondo**. En contecmind el modelo de embeddings puede tardar varios
minutos en cargar en frío, así que una llamada síncrona funcionaría en caliente
y daría 504 el lunes por la mañana: un plazo que depende de si el modelo está
cargado no es un plazo.

Las citas que devuelve son de **fragmento**, no de documento, así que varias
pueden salir del mismo fichero. Se agrupan por documento antes de enseñarlas
—pintarlas tal cual da el mismo documento repetido cuatro veces, que parece un
fallo— ordenando por `relevance` y no por `score`: `score` cambia de significado
a lo largo del recorrido de la búsqueda y el único comparable entre resultados
es `relevance`. Las citas huérfanas —cuyo documento ya no está— se **marcan y no
se esconden**: esconderlas haría que el resumen pareciera tener menos fundamento
del que tenía cuando se generó.

### Aprobar un documento del corpus

Un contrato marco no se publica porque alguien lo suba: se publica cuando quien
manda dice que sí. Ese recorrido —quórum, segregación de funciones, en qué orden
firma cada uno— **es de contecmind y no se reimplementa aquí**. Lo que sí es de
aquí es **quién aprueba**, porque los aprobadores son personas del CRM.

Los aprobadores se eligen **al pedir la aprobación**, no al configurar el flujo:
quién tiene que firmar un contrato depende del contrato, no del tipo de
documento. Sin flujo elegido se resuelve el que toque. Si el flujo elegido exige
aprobadores y no se dan, el gestor contesta 422, así que la pantalla los pide
antes de dejar enviar mirando `exige_aprobadores` de la lista de flujos.

**contecrm no calcula si alguien puede decidir ni si puede pedir**: las dos
respuestas vienen dadas por el gestor. Calcularlas aquí obligaría a copiar sus
reglas, y la copia se desincroniza el día que cambie una — enseñando botones
que dan 403, que es peor que no enseñarlos.

**Aprobar no siempre acaba en «publicado».** Si el reindexado del fichero falla,
la versión queda aprobada, sigue publicada la anterior y la publicación se
puede reintentar. Eso es correcto y se enseña así: una pantalla que dé por
hecho «publicado» pintará como roto algo que funciona.

Las decisiones son tres —aprobar, rechazar y **delegar**—, y delegar lleva en
quién. Una decisión que no sea una de las tres se para aquí, antes de salir a
la red, porque el 422 del gestor llegaría en su idioma y sin decir cuáles valen.

La bandeja de pendientes es **de quien pregunta**: va con su token, igual que
todo lo demás del corpus, así que nadie ve lo que espera la firma de otro.

**Si no hay corpus, la pantalla lo dice en una frase, no en rojo.** Son tres
situaciones distintas y se distinguen: apagado en este despliegue —no hay
documentos que aprobar y los adjuntos de los registros siguen funcionando—,
encendido pero sin respuesta —con la dirección y el error, para no tener que
abrir los registros del servidor para saber si es la URL, la red o que está
parado—, y en marcha. Cuando no responde ni se pide la bandeja: preguntarle a
un gestor caído solo cambia una explicación clara por el primer error que
salga, y el que salía mandaba a configurar una organización cuando lo que
pasaba era que contecmind no estaba levantado.

**Junto a la aprobación se dice el estado real del documento en el gestor**: si
está indexado y si se indexó con avisos —figuras, tablas o pies que se cayeron
por el camino—. «Indexado» a secas cuando falta la mitad de las tablas hace
creer que la búsqueda lo encuentra todo. Ese estado se pregunta al abrirlo y no
se copia en el enlace, porque un estado copiado envejece sin avisar.

**Dónde está.** Se llega por dos sitios y los dos enseñan lo mismo. En
Automatización → *Aprobar documentos* está la bandeja: lo que espera tu
decisión, con el porqué y, si delegas, en quién. Y en la ficha de un registro,
bajo la pestaña Documentos, cada documento enlazado despliega su aprobación —su
estado y, si te toca, pedirla—. Está cerrado de entrada a propósito: cada
documento abierto es una llamada al gestor, y una ficha con doce contratos haría
doce al abrir la pestaña.

El aviso por correo lo manda el CRM y no el gestor, y no es un reparto
caprichoso: contecmind **no conoce el correo** de una persona del CRM —no tiene
ficha suya, por diseño—, así que el único que puede avisar es quien sabe a
quién.

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

Se partía de un motor de evaluación **que no llamaba nadie**, que es la forma más
silenciosa de no tener control de acceso: el código existe, las pruebas del motor
pasan y ningún registro está protegido. Lo que se construyó encima fue que las
políticas se guarden y se versionen, que haya **un punto único de decisión** por
el que pase toda lectura y escritura de un registro —con un gate que lo imponga,
para que no vuelva a haber motor sin quien lo llame—, que
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

> **Auditado entero el 26-10-2026**, las diez capacidades recorridas por HTTP, y
> **sin un solo hallazgo**. Conviene que conste: es la primera familia que sale
> entera limpia, y una auditoría que siempre encuentra algo acaba no
> significando nada. Lo que se le preguntó es lo que pregunta un auditor —
> enséñame el registro, los controles, la última evaluación, qué no está
> cubierto, quién puede hacer qué— y lo que se comprobó es la respuesta que sale
> por HTTP, no lo que dice el código.
>
> Dos de las reglas se validaron **plantando el caso malo**: quitando la
> obligación del residual al aceptar un riesgo, y quitando la detección de
> controles que apuntan a capacidades retiradas. Cae una prueba cada vez.

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
primero es lo que un auditor puede comprobar hoy; lo segundo mide contra el
alcance completo, incluido lo que todavía no se ha entregado.

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

**Y las pestañas se abren de verdad, no sólo existen.** Desde el 26-10-2026 hay
un barrido que abre **las 110 pestañas de los 19 módulos** contra el servicio
dueño de cada una, como las abre quien entra. Cubre el hueco que quedaba entre
los dos gates que ya había —uno comprueba que la ruta exista en el contrato,
otro que los listados de cada servicio no revienten—: una ruta puede existir y
pasar el barrido genérico y aun así contestar **403** porque el permiso que
exige no es el que el módulo supone, **422** porque pide un parámetro que la
pestaña no manda, o **404** porque el servicio declarado no es el que la
publica. Las tres se ven igual desde dentro: una pestaña con su rótulo y un
error.

Medido: las 110 contestan, en quince segundos. Que no saliera ninguna rota no
es motivo para no tenerlo — lo barato es mantenerlo, y lo caro es la pestaña que
se rompe el día que alguien cambia un permiso.

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

**Y es por tenant, no por despliegue.** `config.json` da la marca de la
instalación y sirve para la pantalla de entrada, donde todavía no se sabe de
qué tenant es quien mira. En cuanto hay sesión, encima se aplica la del tenant:
nombre, logotipo, favicon y colores, que es como los guarda el servidor.

> Hasta el 26-10-2026 no se aplicaba. El servidor la tenía guardada y la ruta
> devolvía sólo el **diagnóstico** —qué falta para poder activarla, el aviso de
> contraste— y no los valores, así que el front no tenía de dónde leerla: dos
> tenants en la misma instalación compartían la marca del fichero de
> despliegue. Es el mismo circuito abierto que la localización, encontrado el
> mismo día: la mitad del servidor existe y la del cliente no la lee.
>
> Los valores se mandan **sólo cuando la marca está activa**. Una marca a medias
> pisando la del despliegue es justo lo que ese diagnóstico existe para evitar:
> si se anuncia y el correo sale con el dominio del fabricante, la conversación
> que sigue no es sobre el correo.

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
y lleva a la pantalla real: si algo no aparece en el recorrido, es que no existe
como módulo instalado.

Y **cada pantalla dice qué capacidad del catálogo implementa**
(`CRM-07.04.05.05`), con el identificador a la vista. Desde él se llega al
enunciado, al código y a la prueba: es la trazabilidad puesta delante de quien
la mira, en vez de enterrada en un fichero que solo abre quien ya sabe que
existe.

### El modelo de datos se podía listar y no abrir

La familia de «extender sin código» —`CRM-00.04.01` y `CRM-00.04.03`— estaba
publicada entera y **sin puerta**: el módulo listaba los objetos y ahí se
acababa, porque la fila no abría. Y como los paneles de una ficha se
construyen a partir de los `GET` que devuelven lista, los campos de un objeto,
sus validaciones, sus tipos de registro, sus límites y la trazabilidad del
esquema no se alcanzaban desde ninguna pantalla. Lo que se puede hacer por API
—añadir un campo, publicarlo, renombrarlo, materializarlo— no se podía ni
mirar.

**No bastaba con marcar la fila como abrible**, y conviene decir por qué:
las rutas hijas de un objeto se dirigen por su **nombre**
(`/objetos/{nombre}/describe`) mientras que el objeto se abre por su
**identificador**. La ficha genérica pasa el identificador a todas, así que
cada panel habría salido en 404 — peor que no tenerlos, porque un panel en
error se lee como un sistema roto y un panel ausente, como algo que no existe.
La pantalla propia abre por identificador, lee el nombre y con él pide lo
demás, y hay prueba que recorre las cinco rutas y lo fija.

El panel que manda es el de los campos **con sus escrituras al lado**: es lo
que contesta la única pregunta que se hace de verdad delante de un modelo de
datos, que es si un campo se puede quitar.

### Lo que destapó el nivel completo sobre la pantalla nueva

La pantalla de «Plataforma y cumplimiento» declaraba la forma de nueve
respuestas y **ninguna prueba de servidor las pedía**. El gate que lo mira
—`test_ninguna_pantalla_pide_una_forma_a_una_ruta_que_nadie_toca`— lo cazó en
el nivel completo, al día siguiente de escribirla: es el circuito abierto de
siempre, con las dos mitades existiendo y nadie recorriendo lo que las une.

Las nueve se recorren ahora, **y por servicio**: siete de ellas las publica
cada uno de los trece con su propio prefijo, y comprobarlas en uno solo daría
verde con doce sin mirar.

Al escribirlo salieron dos cosas más:

- **`/restauracion/rpo` cambiaba de forma.** Sin copia de la que medir
  devolvía dos campos y con ella seis: faltaban `se_perderia_min`,
  `rpo_comprometido_min` y `dentro`. Una respuesta que cambia de forma según el
  caso obliga a cada cliente a adivinar cuál le ha tocado, y el que no lo haga
  enseña un hueco sin explicación justo en la pantalla que se mira el día del
  incidente. Ahora van a nulo, que es la respuesta: «no se sabe» no es «cero»,
  y es lo que dice `medible`.
- **Y la prueba componía las rutas con una f-string**, así que el gate seguía
  sin encontrarlas y la pantalla seguía contando como infractora aunque la
  prueba la recorriera. Van escritas enteras, con `{servicio}` dentro.

Y una excepción que sobraba: `/contacts/{id}/cuentas` estaba declarada como
subcolección «que se lee por otra puerta», y ahora tiene la suya. El gate de
colecciones legibles exige que una excepción que deja de hacer falta se retire,
y por eso salió en rojo el mismo día.

### Lo que destapó sembrar una empresa de verdad

Sembrar una empresa entera con `sembrar_empresa.py` y `sembrar_configuracion.py`
—312 registros de configuración por la API, pasando por las mismas
validaciones, los mismos permisos y los mismos eventos que una persona— dejó un
informe de 30 altas rechazadas. **Ocho eran el producto defendiéndose** y tres
defectos de verdad:

- **`POST /automatizaciones` respondía 500 siempre que no se le daba horario**,
  que es el caso normal porque la mayoría se disparan por evento. El contrato
  declaraba `programacion` como objeto y la columna es una expresión cron que
  admite nulo: reventaba al serializar la respuesta, **con la fila ya escrita**.
  Ninguna prueba en rojo, porque todas las que creaban una le ponían horario.
- **`POST /data-subject-requests` respondía 500 siempre.** El mapeador devolvía
  ocho de los catorce campos que declara su contrato, y uno de los que faltaban
  era obligatorio. Los otros cinco llevaban meses saliendo vacíos: de quién es
  la solicitud, quién la lleva, por dónde entró y —lo que pide el regulador—
  qué se resolvió y con qué prueba.
- **`GET /contacts/{id}/cuentas` no existía.** La relación contacto–cuenta es
  N:M: se podía crear el vínculo y se podía cerrar, y no se podía leer. Dos
  consecuencias, y la segunda no la vio nadie: nadie podía contestar «¿de qué
  empresas es esta persona?», y la ficha del contacto no pintaba su panel de
  cuentas —los paneles se construyen a partir de los `GET` que devuelven
  lista—, lo que se lee como «no está en ninguna cuenta».

Y el informe del sembrador ahora **separa lo que la API rechaza por diseño**
—reverificación por operación sensible, publicar exige otro aprobador, SAML
apagado en esta instalación, una oportunidad cerrada que está bloqueada a
propósito— de lo que está roto. Mezclarlo tiene un coste medido: quien lee
treinta persigue treinta, encuentra ocho que no llevan a ninguna parte, y a la
tercera deja de leer la lista.

#### El barrido que faltaba

Los dos 500 compartían forma, y ninguno lo cazaba el barrido de escrituras que
ya había: ése manda `{}` y recibe un 422 correcto, así que **la petición no
llega a ejecutarse** y no puede ver si la respuesta serializa.

El nuevo manda un **cuerpo válido mínimo compuesto a partir del propio
contrato** —nada escrito a mano que se quede viejo— y marca sólo el 500: un
409, un 422 o un 502 son respuestas previstas, la ruta ha hecho su trabajo y
dice qué pasa. Trece servicios en 19 segundos, en el nivel completo. Validado
revirtiendo uno de los arreglos: falla y dice la ruta, el cuerpo y el error.

Casi siempre lo que caza es el contrato de la **respuesta**: un campo que el
modelo declara obligatorio y el mapeador no pone. La fila se escribe y quien la
creó ve un error del sistema.

### El panel que responde 422 siempre

Hay una forma de romper una pantalla que no ve nada: llamar a una ruta sin un
parámetro que el servidor exige. El tipo de la respuesta es correcto, la ruta
existe, el permiso es el bueno y el front compila; sólo se ve **pidiéndola**.

Pasó el mismo día en que se puso el panel de particiones de «Plataforma»:
llamaba a `/volumen/particiones-a-crear` sin `ultima_existente` —cuál es la
última partición que ya hay, que sólo lo sabe quien administra la base—, así
que el panel salía en error para los catorce servicios. Ahora se pregunta, con
el primero del mes en curso de partida.

Y hay gate: `test_la_pantalla_manda_lo_que_el_servidor_exige` cruza las rutas
que el front escribe con los parámetros obligatorios de los catorce OpenAPI.
Corre en cada empujón aunque cueste doce segundos, porque lo que caza no lo ve
nada más.

Dos cosas que merece la pena contar de él. La primera, que **su primera versión
señaló dos pestañas que funcionan**: las que llevan `periodo: true` no escriben
`desde` y `hasta` en la ruta porque se los pone la pantalla de módulo en cada
petición. Mirarlo antes de creérselo es lo que separa un gate de un ruido. Y la
segunda, que está validado plantando el caso malo: quitándole el parámetro al
panel, falla y dice el fichero y el parámetro que falta.

### El botón que faltaba: exportar un listado (`CRM-05.01.01.07`)

El caso más limpio de «escrito y sin enchufar» de todo el producto. El servidor
publica `GET {colección}/exportar` en **setenta** colecciones, y lo hace bien:
aplica los filtros de la URL, incluye las columnas propias del tenant, pasa por
la misma proyección por rol que el listado —un CSV que enseña el teléfono que la
ficha tapa es la vía más fácil de saltarse la protección, y la más silenciosa—,
pone la marca de origen y exige reverificación por exportación masiva. El manual
de usuario lo describe entero desde hace meses.

Y no había **un solo botón** en todo el front.

El que se ha puesto se decide desde la superficie y no desde una lista escrita a
mano: una lista se queda corta en la colección setenta y uno, que es justo la
que alguien querrá exportar. Con él ganan puerta 54 colecciones —las otras 16
exportaciones siguen huérfanas porque su listado tampoco se enseña en ninguna
parte, y se cerrarán cuando lo tenga—.

Dos cosas que se arreglaron de paso, y las dos salieron de leer lo que el
manual promete:

- **el recorte no se decía en `csv`.** En `json` venía en el cuerpo desde el
  principio; en el formato que se baja la gente, en ninguna parte. Ahora va en
  una cabecera —`X-Exportacion-Truncada`—, porque en una hoja no cabe decirlo
  sin ensuciarla y hace falta saberlo antes de abrirla. Hay prueba que planta el
  caso malo: una cabecera que siempre vale «0» no avisa de nada y lo parece;
- **y el paso de verificación se explica.** Un 401 pintado como «no autorizado»
  se lee como que falta un permiso, que lleva a pedirle a un administrador algo
  que no arregla nada. Se distingue además «vuelve a verificarte» de «no tienes
  segundo factor configurado», que para quien está delante son dos cosas muy
  distintas.

### Lo publicado que no tenía botón: «Plataforma y cumplimiento»

Medido el 27-10-2026 cruzando el contrato publicado con el front: de 871
colecciones `GET` publicadas, **477 no aparecían en ninguna pantalla**. Y 327
formas distintas, de las cuales veinte eran **la misma ruta repetida en los
catorce servicios** —papelera, rastro, cumplimiento, restauración, volumen,
tokenización, retención—: 170 rutas que son la misma pregunta hecha a trece
sitios.

Eso descarta la solución evidente. Una pestaña por servicio y por familia son
setenta y ocho pestañas que dicen lo mismo, y en setenta y ocho pestañas no se
encuentra nada. La pantalla lleva **un selector de servicio arriba** y debajo
cuatro preguntas, que no cambian: quién tocó qué, qué se salió de lo normal,
qué datos personales trata esto y qué se puede recuperar.

Lo que cubre, con su identificador: el audit trail inmutable
(`CRM-00.05.04.01`), la auditoría de cambios de configuración y de permisos
(`CRM-00.05.04.03`), su volcado a un SIEM (`CRM-00.05.04.04`), su consulta
desde la propia plataforma (`CRM-00.05.04.05`), el control de exportaciones
masivas (`CRM-00.05.03.06`), el registro de actividades de tratamiento
(`CRM-07.03.01.04`), el informe de cumplimiento (`CRM-07.03.01.07`), la matriz
de permisos (`CRM-07.03.02.09`) y la restauración selectiva
(`CRM-00.06.02.03`). El recuento de capacidades sin pantalla declarada baja de
426 a 413 en dos pasos del mismo bloque, que es lo que el trinquete exige.

Un segundo grupo de paneles cubre las otras cinco preguntas que también se
repiten servicio a servicio: el RPO real frente al comprometido y la ventana de
retención (`/restauracion/rpo`, `/restauracion/ventana`, `CRM-00.06.02.02`),
las particiones que faltan por crear (`/volumen/particiones-a-crear`) y si hay
bóveda para tokenizar (`/tokenizacion`, `CRM-00.05.03.04`). Con eso, las rutas
de colección sin puerta bajan de 426 a 374 —medidas sobre rutas únicas; la
primera versión de la sonda mezclaba el total por ocurrencias con los
pendientes por rutas únicas, y ese número no se podía comparar con nada—.

Lo que **no** declara, aunque lo roce: `CRM-00.05.04.06` —reconstruir un
agregado desde sus eventos—, porque reconstruir pide el identificador de un
registro concreto y su sitio es la ficha de ese registro. Declararlo aquí sería
declarar lo que no se hace, que es justo lo que esa traza existe para impedir.

### El sistema de demostración poblado (`CRM-07.04.05.06`)

Un tenant de muestra con cuatro cuentas sirve para comprobar que una pantalla
pinta; no sirve para enseñar el producto, porque casi toda pantalla sale vacía o
con tres filas. Lo que hace falta es **una empresa que lleva diez años usando el
CRM**, y es lo que siembra `scripts/sembrar_empresa.py --anios 10`.

El mecanismo es uno solo, y eso fue una corrección: se había escrito un
sembrador nuevo antes de ver que `sembrar_empresa.py` ya era el de volumen. Dos
sembradores paralelos son el defecto, no la solución. Ahora
`scripts/datos_demo.py` aporta **sólo lo que no había** —el eje de diez años, el
catálogo de productos, las campañas y el parque instalado— y `sembrar_empresa.py`
lo consume.

Lo que antes no existía y ahora sí: fechas repartidas sobre el periodo —antes
todo se creaba hoy—, el historial de por dónde pasó cada oportunidad, una oferta
con sus líneas por oportunidad, la aprobación por descuento cuando el producto
la exige, el pedido de las que se ganaron, los programas y campañas de cada año
con su presupuesto y su consumo, y los técnicos, el parque instalado y las
órdenes de trabajo del servicio de campo —tres familias que no tenían una sola
fila—.

Las proporciones imitan a un negocio y no a un folleto: se pierde más de lo que
se gana, el 15 % de los casos incumple el plazo, unas campañas se pasan del
presupuesto y otras no llegan. Una demostración donde todo sale bien deja de
creerse en cuanto alguien la mira.

**Y se comprueba.** `--comprobar` recorre lo sembrado con 21 comprobaciones
repartidas por servicio y cada una dice **cuántas filas recorrió**: una consulta
que no encuentra nada porque la tabla está vacía da cero fallos y parece verde.
Seis incoherencias se cazaron así y ninguna se veía en pantalla —entre ellas, un
contacto nacido antes que su cuenta (uno entre 145), el 76 % de los casos
incumpliendo el SLA por sortear horas sueltas en vez de medir contra el plazo de
cada tier, y 235 ventas ganadas sin pedido porque las ofertas se ataban a su
oportunidad por nombre y los nombres se repiten—. El comprobador se validó
plantando tres casos malos y verificando que los caza.

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

> **Y una condición mal escrita ya no se toma siempre.** Hasta el 26-10-2026, una
> condición de decisión sin `atributo` —o escrita con las claves cambiadas, que
> es la errata que se comete de memoria— se evaluaba a **cierto**: el motor
> resolvía `@` a nulo, el valor por defecto también era nulo, y el `=` daba
> cierto. Resultado: la decisión se iba **siempre por la primera rama**, sin
> error, sin traza, y con el `si_no` que su autor escribió al lado sin usarse
> jamás. El validador lo daba por bueno.
>
> Arreglado por las dos mitades, que es lo que hace falta aquí: el validador lo
> **rechaza** diciendo por qué, y el motor devuelve falso ante una condición así
> —para que las definiciones **ya guardadas** dejen de tomar la rama a ciegas—.
> Falso es lo correcto porque el autor ya ha escrito a dónde ir cuando la
> condición no se cumple: es el `si_no`.
>
> Salió escribiendo la prueba de la familia con la forma equivocada de la
> condición, y viendo que un importe de diez se iba por la rama de «grande».
>
> **Y no estaba en un sitio: estaba en cuatro.** Las cuatro vías que evalúan
> condiciones escritas por el cliente comparten la misma tabla de operadores y
> el mismo resolvedor, así que compartían el agujero:
>
> | Dónde | Qué hacía una condición mal escrita |
> |---|---|
> | Motor de procesos | ir siempre por la primera rama |
> | Webhooks | entregar **todo** a quien pidió filtrar |
> | Automatizaciones | dispararse con cualquier registro |
> | Reglas de validación | saltar con cualquier cosa, o saltarse y dejar decidir a las demás |
>
> Ninguna falla: las cuatro devuelven algo plausible. Arregladas las cuatro, y
> con un gate que recorre el árbol buscando el patrón —resolver un `@atributo` y
> compararlo con la tabla de operadores— para que una quinta vía no nazca con
> lo mismo.
>
> De paso apareció que el **simulador tenía su propia copia** de la evaluación:
> al arreglar el motor, sólo se arregló una de las dos, y un simulador que no
> decide igual que el motor es peor que no tener simulador. Ahora hay una sola
> implementación y el gate lo vigila.

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
rota al leer es una ficha inaccesible con la persona que la escribió ya lejos. Un
campo de tipo fórmula que no trae fórmula **no se guarda**: el campo existiría y
no calcularía nada, que es la peor de las tres situaciones posibles.

Se evalúa en **todas las lecturas** —el listado, la ficha y la exportación— y en
el mismo sitio, que es lo que impide que una de las tres lo enseñe y las otras no.
Y lo calculado **pisa** cualquier valor que hubiera guardado con ese nombre: un
campo calculado no se escribe, se calcula, y un valor viejo ahí dentro sería el
que se enseñara sin que nadie supiera de dónde salió.

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

Las dos cosas —la forma conservada y la sal por entorno— **se pedían por una ruta
que no existía**: la copia se anonimizaba con un sustituto de dieciséis caracteres
hexadecimales para todo, así que un correo anonimizado no era un correo y ninguna
pantalla con validación funcionaba en pruebas. La pieza que conserva la forma
estaba escrita al lado y no la llamaba nadie.

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

La sirve **cada servicio**, porque una composición que cruzara servicios no
podría ser una transacción y prometerlo sería mentir. Cada operación se despacha
contra la propia aplicación, así que pasa por la autenticación, los permisos, la
validación y la auditoría igual que si hubiera llegado sola: ejecutarlas por
dentro habría sido más rápido y habría creado un camino sin controles.

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

Se comprueba **en la puerta y en cada petición**. Las reglas son un ajuste del
tenant y viajan al gateway con el mismo dato y la misma caché que su
operatividad: pedirlas aparte sería doblar el tráfico interno por lo mismo.

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

---

## 53. Cuatro cosas de plataforma que se notan cuando ya es tarde

### «Hoy» es el del cliente, no el del servidor (`CRM-00.01.04.07`)

**Para el usuario.** Los días que quedan de una garantía, los plazos que vencen y
el mes del presupuesto se cuentan **en la zona horaria del cliente**, la que tiene
configurada en su perfil.

**Para mantenimiento.** `crmcore.fechas.hoy(db)` resuelve el huso por el mismo
ajuste que usa el formateo, con la cadena de siempre —usuario → unidad → tenant →
global—. Sin zona configurada cae a UTC, y no se adivina: un valor inventado
escondería el problema en vez de dejarlo igual.

Y el huso del perfil **llega al ajuste**: al editar un tenant se propagan zona,
idioma y moneda. Antes eran dos sitios que no se hablaban.

> **Se descubrió por accidente, y ése es el detalle que más dice.** Una tanda de
> pruebas cruzó la medianoche y empezó a fallar; repetida a la una de la mañana,
> siguió fallando. A las once de la noche del mismo día habría pasado en verde,
> que es lo que llevaba pasando.
>
> Lo que había debajo eran dos cosas. **Veinticinco sitios calculaban la fecha en
> UTC**, así que entre medianoche y las dos de la mañana en Madrid —y durante
> **trece horas** en Auckland— «hoy» era ayer para el servidor y hoy para el
> cliente. Y **`Tenant.zona_horaria` no lo leía nadie**: el cliente configuraba su
> huso en el perfil y era un campo de sólo escritura.
>
> Quedan por convertir los sitios que no tienen sesión a mano. Los tres módulos
> donde se veía —garantías, fondos MDF y protección de partners— ya usan el huso
> del tenant.

### Las cuotas: por módulo, contadas de las filas y abriendo por omisión

**Para el usuario.** Un plan puede acotar cuánto ocupa un cliente, cuántos
correos manda, cuántos procesos lanza y cuántos registros guarda. Al pasarse, la
operación se rechaza **diciendo qué se ha agotado, cuánto llevaba y qué ajuste
hay que tocar** — no un «has llegado al límite» que obliga a preguntar.

**Para mantenimiento**, tres decisiones que conviene entender antes de tocarlas:

- **Por módulo, no un tope global.** Cada servicio guarda lo suyo en su esquema y
  cuenta lo suyo. Así el alta no depende de una lectura entre servicios —cara y
  que se cae con el vecino— y, sobre todo, **el mensaje puede decir qué se
  agotó**: con un tope global, «has llegado al límite» no distingue contactos de
  correos.
- **Se cuenta, no se lleva contador.** Los adjuntos ya tienen su tamaño, las
  entregas su fila y los registros su tabla. Un contador aparte se desincroniza
  el primer día que algo desaparece por otra vía —una purga, una fusión, una
  baja— y entonces el cliente paga por lo que no tiene. El día que contar se
  quede corto, lo que toca **no es un contador**: es un índice, o un resumen
  recalculable que se pueda comprobar contra las filas.
- **La omisión abre, nunca cierra.** Sin tope declarado, o con tope 0, se deja
  pasar. Un despliegue que no ha configurado cuotas no puede quedarse sin poder
  trabajar por un olvido, y un fallo al declarar tiene que dejar pasar de más.

Dónde se aplica cada una, que es lo que hay que saber para cambiarlas:

| cuota | dónde corta | ajuste |
| --- | --- | --- |
| almacenamiento | al subir un fichero | `cuota_almacenamiento_mb` |
| correos y SMS | al abrir la ficha de entrega del aviso | `cuota_correos_mes`, `cuota_sms_mes` |
| procesos | al arrancar una instancia, **sólo las de primer nivel** | `cuota_workflows_mes` |
| registros | al volcar la sesión, **sólo los modelos declarados** | `cuota_registros` |

**Un subproceso no consume cuota propia**: es parte de la misma ejecución, y
contarlo aparte haría que un proceso con diez subprocesos gastara once — un
número que el cliente no podría cuadrar con lo que ve en su pantalla. **Y un
reintento de un aviso ya contado tampoco**: si lo hiciera, un canal con mal día
se comería el mes.

**Qué cuenta como «registro» es explícito y corto.** Cuentas, contactos y
actividades son lo que un cliente entiende por suyos; una fila de auditoría, una
entrega de aviso o un apunte de consumo no lo son, y contarlos le agotaría la
cuota con nuestro propio ruido.

> **Tres de las seis del catálogo ya se aplicaban y no lo sabíamos.** Antes de
> escribir nada se midió: el rate limiting está enchufado en un middleware desde
> siempre, el gasto de IA corta el mes agotado, y el tamaño de fichero se
> comprobaba. Medir antes de implementar ahorró tres implementaciones — y una de
> ellas estuve a punto de darla por muerta porque el módulo sólo lo nombraba un
> fichero de pruebas.

### El plan cierra módulos, y la omisión abre

**Para el usuario.** Un módulo que no está en el plan contratado se rechaza desde
la API, no sólo se oculta del menú. Hasta ahora bastaba con saberse la URL para
usar algo que no se había pagado: la pantalla obedecía y el servidor no.

**Para mantenimiento.** Se cierra **por módulo**, que es como se vende, y lo
comprueba el gateway —que ya sabe a qué servicio va cada ruta—, con el mismo dato
cacheado que la operatividad: una sola llamada interna para las dos cosas.

Dos reglas que conviene no invertir:

- **Sólo se cierra lo que el plan niega explícitamente.** Un módulo que el plan
  no menciona pasa. Si cerrara por omisión, un plan vacío —el de cualquier
  instalación recién montada— dejaría al cliente sin producto, y a un plan al que
  se le olvida una línea le cortaría un módulo que sí pagó.
- **Hay módulos que no se cierran nunca**, con el motivo escrito al lado:
  `gateway` es la puerta, `identity` es entrar, `tenancy` es donde se ve y se
  cambia el propio plan, y `docs` es el manual. Cerrar cualquiera de ellos deja
  al cliente **sin salida para arreglar la situación**.

Y el orden importa: primero la suspensión, después el plan. Un tenant suspendido
tiene que enterarse de que está suspendido, no de que no ha contratado marketing.

> **`exigir_capacidad` llevaba escrita en `tenancy` desde el principio y no la
> llamaba nadie**, como la suspensión y como los seis barridos. El plan se podía
> configurar entero y no cerraba nada.

### El panel de consumo: suma por módulo, y lo que no se lee no vale cero

**Para el usuario.** `GET /estado/consumo` en el gateway dice cuánta cuota lleva
gastada el tenant, **sumando todos los módulos y diciendo de dónde sale cada
parte**. Sin el desglose, un total no se puede cuadrar con lo que se ve en cada
pantalla.

**Y si un servicio no contesta, se dice.** Nunca un cero:

> Un cero es una afirmación falsa —«no has gastado nada»—. Un cliente que ve
> ceros llega al tope **sin haber visto subir el número nunca**, y eso convierte
> la cuota en una encerrona. «No se ha podido leer» es verdad y se puede mirar.

La respuesta lleva `completo: false` y la lista de lo no leído **arriba, no
enterrado en una fila**: un total al que le falta un módulo no es un total, y
quien lo mire tiene que saberlo antes de tomar una decisión con él. Lo mismo si
un módulo contesta pero una de sus métricas no se pudo medir.

**Para mantenimiento.** Cada servicio publica lo suyo en `/estado/consumo` y el
gateway compone, igual que con la página de estado — en paralelo, porque en
serie diez servicios con cinco segundos de plazo son cincuenta segundos de espera
justo cuando algo va mal.

**Los topes no se suman.** Las cuotas son por módulo: 100 en `party` y 100 en
`sales` no son 200, son dos topes distintos y cada uno corta por su lado. Sumarlos
daría un límite que no existe en ninguna parte, así que se enseñan al lado, uno
por módulo.

### Las tareas periódicas, y por qué no había ninguna

**Para el usuario.** Hay cosas que pasan solas cada tanto: los recordatorios
vencidos se emiten, los informes programados se ejecutan y se mandan, y los
estados caducados de SSO, SAML y MFA se tiran para que sus tablas no crezcan sin
techo. Todo eso ocurre sin que nadie pulse nada.

**Para mantenimiento.** Cada servicio que tiene barridos arranca un **relevo de
tareas** con su lista, y cada tarea lleva su propio intervalo, configurable
(`tarea_recordatorios_intervalo_s`, `tarea_informes_intervalo_s`,
`tarea_reverificaciones_intervalo_s`, `tarea_purgas_intervalo_s`). Tres reglas,
y las tres nacen de averías reales:

- **Se aísla por tenant y se sigue.** Un fallo en el tenant 40 no puede parar a
  los 200 siguientes, y el que falla deja **su identificador y su motivo** en el
  registro — no un contador, que no sirve para arreglar nada.
- **A los tres fallos seguidos deja de ser un fallo y pasa a ser una avería**,
  y sale en la **página de estado**, no sólo en el log. Un barrido que falla
  siempre en el mismo sitio y sigue en verde es otra avería silenciosa.
- **Late aunque no haya nada que barrer.** Si sólo se registrara al trabajar,
  una tarea parada y una sin trabajo se verían igual desde fuera.

> **Esto no existía, y se vio el 28-09-2026.** Había **seis** funciones
> escritas, probadas y **sin nadie que las llamara**: los recordatorios vencidos
> no se emitían nunca, los informes programados no salían —la ruta
> `POST /informes/correr-programadas` existía y no la disparaba nadie— y tres
> tablas de caducados crecían para siempre.
>
> El peor era el recordatorio: un comercial lo pone en una actividad, lo ve
> guardado con su fecha, **y no le llega nunca**. Sin error, porque no hay error.
> Y `purgar_estados` lo decía en su propia documentación —«La ejecuta una tarea
> periódica»— cuando no había ninguna.
>
> **No faltaban seis cosas: faltaba una.** contecrm tenía workers de cola —que
> consumen lo que se les encola— y nada que hiciera «cada N minutos, barre
> esto». Seis arreglos habrían sido seis sitios donde volver a olvidarse.
>
> Hay una prueba que impide la séptima: si alguien escribe otra función con
> pinta de barrido y **no la llama nadie** en producción, el gate cae y dice
> cuál. Que una prueba unitaria la llame no cuenta — eso es exactamente lo que
> pasaba con las seis.


### Los webhooks salientes: quién reparte, y quién recoge lo que falló

**Para el usuario.** Se crea una suscripción con una URL, los tipos de evento que
interesan y, si hace falta, condiciones sobre el contenido —«oportunidad ganada
de más de 10.000»—. Cada entrega va **firmada con HMAC** y con la clave de
deduplicación en cabecera, para que el receptor descarte un duplicado sin
parsear el cuerpo. Lo que falla se reintenta con espera creciente, y un endpoint
con veinte fallos seguidos se desactiva solo: seguir llamando a algo que ya no
existe es tráfico, ruido y una cola que no se vacía nunca.

**Para mantenimiento.** Dos piezas, y las dos tienen que estar enchufadas:

- un **consumidor del bus** (`eventing-webhooks`, patrón ancho) que casa el
  evento con las suscripciones del tenant y entrega;
- un **relevo de reintentos** que arranca con el servicio y recorre las entregas
  cuyo `proximo_intento_at` ya ha llegado. Su intervalo es configuración
  (`webhook_reintento_intervalo_s`), no una constante.

> **Se vio funcionar el 28-09-2026, y hasta ese día no salía un solo webhook.**
> El reparto estaba entero —firma, reintentos, desactivación del endpoint
> muerto— con sus pruebas unitarias en verde, y **no lo importaba nadie**: el
> servicio declaraba sus rutas y ningún consumidor. Un `grep` del módulo en todo
> el árbol daba una sola coincidencia, un fichero de pruebas.
>
> Para el cliente era el fallo más difícil de ver que existe: crea su
> suscripción, la ve en el listado, mira su historial de entregas, lo ve vacío
> **y cree que todavía no ha pasado nada**. No hay error que buscar, porque no
> hay error.
>
> Y la descripción del propio servicio prometía «reintentos con backoff» y
> «desactivación automática de endpoints muertos». Es el mismo patrón que la
> suspensión de tenants el mismo día: no un guardián apagado, sino **un guardián
> que nunca se encendió y que se contaba como encendido**. Por eso las pruebas
> de esto son del camino —un evento entra por el bus y tiene que salir un POST—
> y no de la función: la función siempre estuvo bien.

### Recibir eventos sin exponer un endpoint (`CRM-00.02.02.10`)

Los webhooks exigen una dirección pública y estable. Eso deja fuera a media
integración real: un navegador, una aplicación móvil, un servicio dentro de una
red cerrada, un cuaderno de análisis. Todos pueden **llamar** al CRM y ninguno
puede recibir una llamada.

Se resuelve con **SSE** y no con WebSocket, por algo práctico: el flujo va en un
solo sentido —el CRM cuenta lo que pasa— y SSE es HTTP normal, así que atraviesa
proxies corporativos, se reconecta solo y se depura con `curl`. Un WebSocket para
empujar en un sentido es un protocolo más que mantener y una cosa más que un
proxy puede romper.

Dos detalles que evitan los fallos de siempre. **Se reanuda** desde el último
identificador recibido: sin eso, cada corte de red —que en un móvil es cada
túnel— pierde los eventos de ese hueco y el cliente no sabe cuántos ni cuáles. Y
**hay latido**, porque un flujo sin datos durante minutos lo cierra cualquier
intermediario por inactividad y el cliente cree que el servidor se ha caído
cuando lo que pasa es que no pasa nada.

El flujo vive **en el gateway**, que es la única puerta pública, y lo alimenta el
mismo servicio que ya reparte los eventos por webhook: son el mismo evento por
dos transportes, y separarlos haría que uno de los dos se quedara atrás. El aviso
al gateway **no rompe el reparto**: si no está declarado en la configuración o no
contesta, lo que no puede pasar es que se caiga la entrega que sí importa.

Y lo que **no** es: la garantía de entrega. Eso son el bus y su tabla de salida.
Esto es un puente para que una reconexión corta no pierda nada, con cola acotada
— y cuando lo pedido ya se ha caído de la cola, **se avisa del hueco** en vez de
saltar a lo nuevo. Un cliente que cree haberlo recibido todo y no lo ha recibido
toma decisiones sobre datos incompletos.

### Cachear con invalidación por evento (`CRM-00.02.04.05`)

La generación la sube **el propio bus**: cada servicio invalida con cada evento
que recibe. No se mira antes si alguien cacheaba ese evento — subir una
generación que nadie consulta cuesta una operación, y no subirla cuando sí la
consultaban sirve datos viejos. De las dos equivocaciones, esta es la barata.

Cachear es fácil; invalidar es el problema. Con caducidad por tiempo, la
respuesta vieja se sirve durante todo el plazo que le quede y el usuario que
acaba de cambiar algo **ve su propio cambio desaparecer** — la queja más difícil
de reproducir que existe, porque a los cinco minutos ya no pasa.

La invalidación va por **evento**, apoyada en las generaciones que la caché ya
tenía: la clave lleva dentro la generación de cada evento que la invalida, y
cuando ese evento pasa se sube el contador. Todas las claves viejas dejan de
encontrarse de golpe, sin recorrer nada y con cualquier backend. Es la diferencia
con llevar un índice de claves, que hay que mantener, puede desincronizarse y
recorrerlo en la ruta caliente de un evento es justo lo que no se puede hacer.

La caducidad se queda como red de seguridad de lo que nadie invalidó. Y se puede
preguntar **qué políticas solo caducan**: una caché que se creyó invalidada por
evento y solo caduca es la que sirve datos viejos sin que nadie entienda por qué.

### La consulta que se está degradando (`CRM-00.06.01.07`)

Una consulta que tarda 20 ms con mil filas y 4 segundos con un millón no falla
nunca: va empeorando. Nadie abre una incidencia por eso — se abre por «el CRM va
lento», meses después, cuando ya hay veinte consultas candidatas y ninguna
evidencia de cuál empezó.

Lo que se mide no es el tiempo medio, que sube despacio y no dice nada, sino el
**tiempo contra el volumen**. Una consulta sana tarda parecido con mil filas y
con cien mil porque usa índice; una que no lo usa tarda proporcionalmente más.
Esa proporción se ve mucho antes de que el tiempo absoluto moleste.

Se agrupa por **forma** y no por texto —dos consultas iguales con parámetros
distintos son la misma— y las listas de `IN` se colapsan, porque si no la misma
consulta con 3 y con 300 identificadores serían dos formas y la que se repite
quedaría repartida entre cientos de filas del informe.

El informe ordena por **tiempo total** y no por media: una consulta de 2 ms que
corre cien mil veces cuesta más que una de 900 ms que corre dos, y es la que hay
que arreglar primero. El informe por media señala siempre la segunda.

### Versionar la configuración (`CRM-00.01.04.02`)

Los ajustes en caliente son lo más fácil de cambiar del sistema y lo más difícil
de deshacer: alguien toca un umbral un viernes, el lunes algo va mal, y no hay
forma de saber qué valía antes. El propio mecanismo que los hace cómodos —se
aplican al instante, sin despliegue— es el que borra la evidencia.

Ahora cada cambio guarda **el valor anterior y el nuevo**, y se anota desde
`fijar` y no desde quien llame: un histórico que depende de que alguien se
acuerde de anotar tiene huecos justo donde importa. Si anotar falla, **no se
propaga**: perder el apunte es malo y perder el cambio que alguien estaba
haciendo es peor.

Se guarda el anterior y no solo el nuevo porque con el nuevo deshacer exige
reconstruir el histórico hacia atrás; con el anterior delante, volver es copiar
un valor. El diff se colapsa por clave —«qué cambió el viernes» es la pregunta
real— y **no saca lo que acabó igual que empezó**: quien subió un umbral y lo
bajó esa misma tarde no cambió nada, y sacarlo manda a investigar un cambio que
no existe.

Y volver atrás es **un cambio más**, registrado como tal, que se aplica por el
camino normal para que se replique a todos los servicios. Escribir la tabla
directamente dejaría al resto del sistema con el valor deshecho hasta el
siguiente reinicio, que es el fallo que la réplica por evento vino a cerrar.

## Aprovisionamiento automático con SCIM 2.0 (`CRM-00.05.01.05`)

SSO resuelve **quién entra**. No resuelve **quién deja de entrar**. Un empleado
que se va desaparece del directorio corporativo, pero su usuario del CRM sigue
ahí: con sus asignaciones, sus registros y —si alguna vez tuvo contraseña local
o una clave de API— con una puerta abierta. SCIM es el canal por el que el
directorio da esas bajas, y aquí está montado con la baja como camino principal.

Se reutiliza `contecweb:app/services/scim.py` y
`contecflow-PSA:app/services/scim_service.py`: de ahí salen el sobre
`ListResponse`, el formato de error del RFC 7644 y, sobre todo, el catálogo de
rarezas de proveedor, que es lo caro de descubrir.

### Por qué la baja pesa más que el alta

Un alta que falla se ve el primer día: la persona nueva no puede entrar y llama.
Una baja que falla no la ve **nadie**. Alguien que se fue hace ocho meses
conserva el acceso, y eso aparece en una auditoría o en un incidente, nunca
antes. Por eso:

- **`DELETE` no borra.** Desactiva la membresía en ese tenant y **corta las
  sesiones en el acto**. Borrar dejaría huérfano todo lo que esa persona creó y
  el historial de auditoría pasaría a apuntar a un identificador inexistente.
  Marcar la membresía sin revocar las sesiones dejaría al que se va operando
  hasta que le caducara el token, que es justo el rato que importa.
- **La baja es por tenant, no global.** `active` sale de la membresía y no del
  usuario. Es lo que permite que un consultor que trabaja para tres clientes
  tenga una sola identidad: mirar el usuario aquí lo echaría de todos.
- **Volver es reactivar, no dar de alta otra vez.** Un alta nueva sería una
  identidad distinta y perdería su historial.

### Las dos rarezas que hay que soportar sí o sí

Ninguna es opcional, porque las mandan los dos proveedores mayoritarios:

1. **`active` como cadena.** Entra ID manda `"value": "False"` —texto, con
   mayúscula— en lugar del booleano del RFC. Leído con `bool()` de Python eso es
   **cierto**: la baja se convertiría en «sigue activo». Es el fallo más caro
   posible en este módulo, y por eso `active` se lee booleano, texto o número, y
   un valor que no se entiende **se rechaza** en vez de darse por activo: por
   defecto a «sí» sería convertir una baja ilegible en un alta silenciosa.
2. **`PATCH` sin `path`.** Okta manda `{"op": "replace", "value": {"active":
   false}}`, con el atributo dentro del valor. Mirando solo `path`, la operación
   se ignora en silencio y se responde 200 — peor que fallar.

Ninguna se corrige detectando el proveedor: se aceptan **siempre las dos
formas**, porque las dos son lecturas defendibles del RFC y porque detectar por
proveedor obliga a tocar el producto cada vez que aparece uno nuevo.

### Lo que el directorio **no** puede hacer

Un IdP manda los grupos que tiene él, que no son los roles de aquí. Aceptarlos
por el nombre dejaría la matriz de permisos en manos de quien administre el
directorio corporativo: bastaría crear un grupo llamado «Administradores» para
tenerlos. Los grupos entrantes **se cruzan con los roles reales del tenant** y lo
que no case se ignora.

Los atributos de directorio que aquí no tienen sitio —departamento, oficina,
manager— también se ignoran, y a propósito: fallar por ellos pararía el ciclo de
sincronización entero, **incluidas las bajas**.

### Detalles que evitan una llamada a soporte

- El **alta no pone contraseña local**. Si la pusiera, existiría una vía de
  entrada que el IdP no controla, y la baja en el directorio no la cerraría.
- **Repetir un alta da 409 con el identificador dentro.** Es el caso más común
  en producción —el alta salió bien y la respuesta se perdió—, y devolver el id
  deja al IdP reconciliar solo, sin intervención.
- La **búsqueda por `userName` ignora mayúsculas**: los IdP no normalizan el
  correo antes de preguntar, y un fallo ahí significa crear un duplicado en cada
  ciclo.
- **La página tiene tope duro.** Un `count` desmedido de un IdP mal configurado
  se llevaría por delante el servicio de identidad, que es el que no puede caer.
- `ServiceProviderConfig` **declara solo lo implementado**. Declarar `bulk` o
  `sort` sin tenerlos haría que el IdP los intentara y se llevara un error a
  mitad de un ciclo.
- Los errores salen en el **sobre SCIM** con su `scimType`. Con el
  problema+json del resto del sistema, el cliente lo registra como fallo opaco,
  reintenta cada hora y nadie averigua por qué la sincronización no avanza.

El tenant sale **de la clave de API**, nunca del cuerpo ni de la URL: es lo que
hace imposible que el cliente SCIM de una organización toque los usuarios de
otra.

## Contratos internos verificados por el consumidor (`CRM-00.03.01.03`)

Entre servicios no hay llamadas directas ni lecturas cruzadas de base —el gate
de arquitectura lo impide—, así que **el único contrato que puede romperse en
silencio es el sobre de un evento**. El catálogo de eventos ya dice lo que cada
productor *declara* publicar, y eso no basta: el productor no sabe qué campos
lee cada consumidor, así que puede quitar uno creyendo que no lo usa nadie. El
daño no se ve al desplegar —el productor sigue verde— sino en el consumidor,
días después, sin relación aparente con el cambio.

Aquí **cada consumidor declara qué campos necesita y para qué**. El motivo va en
la declaración, no en un comentario, porque es lo único que le dice a quien se
plantea quitar el campo si puede. Se reutiliza la idea de
`contecpos:packages/contracts` (buf), traducida al evento.

Se verifican tres cosas, y cada una tapa un agujero distinto:

1. **Estático**, en el preflight: que el evento tenga productor, que el productor
   declare todos los campos que el consumo pide y que la versión alcance. Rompe
   antes de salir.
2. **En ejecución**, al emitir: que lo que se publica de verdad lleve los campos
   prometidos. Sin esto, productor y consumidor pueden declarar lo mismo y que
   la declaración sea falsa —el campo está en el catálogo y nunca en el `data`—.
   Se comprueba **dentro de la transacción**, para que el error la deshaga y no
   quede un cambio hecho con un evento que nadie podrá interpretar; comprobarlo
   en el relevo llegaría tarde. Esto ya encontró un defecto real: la
   reactivación por SCIM emitía `user.provisioned` sin `email`.
3. **Observado**: qué campos se han visto salir de verdad. La cobertura se cuenta
   sobre eso y no sobre lo declarado, porque un 100 % de campos declarados sin
   una sola emisión observada sería un informe que dice que todo va bien sin
   haber mirado.

Un consumo marcado **opcional** no rompe: es lo que permite añadir campos sin
coordinar despliegues. Y declarar un consumo del propio evento se rechaza: un
servicio no necesita un contrato consigo mismo, y contarlo infla la cobertura
sin proteger de nada.

Lo que **no** hace: deducir el contrato leyendo el código. Un contrato deducido
es una foto de lo que hay, no un acuerdo, y no sirve para impedir el cambio que
lo rompe.

Se consulta en `GET /estado/contratos` de cada servicio. La estrictez al emitir
se apaga con `CONTRATOS_EMISION_ESTRICTA=false` para el único caso legítimo: un
despliegue en el que un productor antiguo convive con un contrato nuevo.

## Objetivos de servicio y presupuesto de error (`CRM-00.06.01.04`)

Un SLO sirve para convertir «esto va lento» en una cuenta. Aquí se declara por
servicio y por *tier* —disponibilidad y latencia p95— y de ahí sale el
presupuesto de error, con tres decisiones que cambian cómo se lee:

- **Lo lento cuenta aparte de lo fallido.** Una respuesta que llega en cuatro
  segundos es un error para quien la espera, aunque devuelva 200. Contar solo
  los 5xx da un 99,99 % con la pantalla inservible.
- **Sin tráfico no se dice que va bien.** «100 % disponible» sin peticiones es
  mentir con la verdad: un servicio que nadie ha usado no ha demostrado nada, y
  así se marca —`medible: false`— en vez de enseñar un verde vacío.
- **El presupuesto se dice en minutos.** «Te queda el 37 % del presupuesto» no le
  dice nada a nadie; «te quedan 16 minutos de caída este mes» se entiende a la
  primera y sirve para decidir si se despliega o se arregla.

Cuando el presupuesto se agota, la respuesta lo dice con todas las letras: toca
arreglar antes que seguir sacando.

**Y se ve en la página de estado**, debajo de los componentes. Hasta el
27-10-2026 no se veía en ninguna parte: la página decía en su propia cabecera
que lo enseñaba y leía una sola ruta —la de los componentes—, así que el
objetivo por servicio, el presupuesto en minutos, el consumo sobre lo
contratado, si las promesas entre servicios se están cumpliendo y qué consultas
van más lentas de lo que deberían estaban calculados, servidos y sin pantalla.
Lo que no se mide va **delante y aparte** de lo que cumple: un servicio sin
medición no está en verde, está sin mirar, y contarlo con los que cumplen es
cómo un panel acaba diciendo que todo va bien sobre media flota.

### De dónde salen los números

Lo cuenta **el propio tránsito**, no una sonda aparte. Cada petición que atiende
un servicio se apunta al pasar por el middleware de tiempos, y se apunta ahí y no
en cada endpoint porque el presupuesto tiene que contar **todas** las peticiones:
engancharlo ruta a ruta significa contar las que alguien se acordó de enganchar,
que son justo las que menos fallan.

Un 4xx no gasta presupuesto. Es un error de quien llama —una integración que
manda mal los datos—, y contarlo haría que el equipo se quedara sin margen por
culpa de un cliente mal programado.

**Los contadores viven fuera del proceso**, en el mismo Redis que ya sostiene los
límites de tasa. En memoria sobrevivirían hasta el siguiente despliegue y, con
tres réplicas, cada una tendría su propia verdad: un presupuesto mensual que se
reinicia al desplegar dice siempre que queda margen, que es lo que uno quiere oír
y exactamente por lo que no serviría. Si no hay Redis se cuenta en memoria y la
respuesta **lo dice**, porque un número calculado sobre una ventana de dos horas
no es el presupuesto del mes.

### Por qué se cuenta por tenant y el tier se aplica al leer

Cada servicio sabe de qué tenant es cada petición, pero **no** qué tier ha
contratado: eso vive en `tenancy` y ningún servicio lee el esquema de otro. Así
que se cuenta por tenant, que es lo fino, y el tier se aplica al leer, que es
donde sí se sabe. Lo fino se puede agregar; lo agregado no se puede desglosar.

La lentitud se cuenta **contra los tres umbrales a la vez**. La misma respuesta
de 1,5 s es normal en estándar y es una falta en enterprise, y esa es exactamente
la diferencia que el cliente está pagando. Decidirlo al escribir obligaría a
saber el tier donde no se sabe, y recalcularlo después sería imposible porque los
milisegundos de cada petición ya no están.

La vista completa la compone el gateway en `GET /api/v1/estado/slo`: pregunta el
tier una vez a `tenancy`, se lo pasa a todos los servicios y junta los
presupuestos. Y **dice lo que no ha podido consultar**: un servicio que no
responde y desaparece de la lista deja una página que enseña margen de sobra
precisamente cuando algo va mal.

## Restauración selectiva (`CRM-00.06.02.03`)

Restaurar la copia entera para recuperar veinte registros borrados por error
sacrifica todo lo que se hizo desde entonces. La restauración selectiva lee una
exportación, deja **previsualizar** qué cambiaría y escribe solo lo elegido.

Las tres reglas que la hacen usable:

- **Se ve antes de escribir.** Quien restaura casi nunca sabe qué va a
  sobrescribir, y descubrirlo después es cambiar un problema por otro. La
  previsualización dice, registro a registro, qué campos difieren.
- **No se pisa lo modificado después del punto de restauración.** Es trabajo que
  alguien hizo a sabiendas; sobrescribirlo sin avisar cambia un problema
  conocido por otro peor. Se salta y se dice, y forzarlo es una decisión
  explícita que queda escrita en la auditoría.
- **Nunca entre tenants.** Sería la peor fuga posible: datos de un cliente
  escritos en la base de otro, con un rastro que dice que fue una recuperación
  legítima. Se rechaza de plano, y al recrear un registro borrado se comprueba
  sobre lo exportado, porque ahí no hay fila viva con la que contrastar.
- **Un registro que ya no está se vuelve a crear.** Es el caso más común de
  todos —alguien borró lo que no tocaba— y saltárselo dejaría la recuperación
  sirviendo solo para el caso raro: el registro que sigue existiendo con los
  campos mal. La auditoría distingue lo recreado de lo sobrescrito, porque una
  cosa devolvió algo que no estaba y la otra pisó algo que sí.

Cada servicio publica la suya en `/{servicio}/restauracion`, y los objetos que
se pueden restaurar **se leen del propio modelo**: una lista escrita a mano se
queda corta al primer modelo nuevo, y ese sería justo el que no se puede
recuperar el día que alguien lo borre. Los catálogos de instalación quedan fuera,
porque restaurarlos «para un tenant» no significa nada.

## Registro de tratamiento e informes de cumplimiento (`CRM-07.03.01.04`, `CRM-07.03.01.07`)

El RAT que exige el RGPD se hace casi siempre en una hoja de cálculo, a mano, y
describe el sistema que alguien recordaba el día que lo escribió. A los seis
meses describe otro sistema.

Aquí **sale del propio modelo**: cada columna declara su sensibilidad y de ahí se
compone el mapa de datos personales sin que nadie lo transcriba. Cuando alguien
añade un campo con datos personales, el mapa lo recoge solo; con la hoja de
cálculo, ese campo no existe para el RAT hasta que alguien se acuerda — y nadie
se acuerda.

Lo que no se puede derivar —finalidad, base legal, plazo, destinatarios— sí se
declara, porque son decisiones y no datos técnicos, pero se declara **junto al
objeto** y no en un documento aparte que se queda viejo.

Y lo que falta **se dice**, que es la parte que hace que esto valga:

- un objeto con campos personales y sin tratamiento declarado sale como hueco;
- un tratamiento declarado sobre un objeto que ya no tiene datos personales
  también sale — suele significar que el objeto cambió y el RAT no;
- las **categorías especiales** del artículo 9 se señalan aparte, porque su
  régimen legal es distinto y un RAT que las mezcla esconde justo lo que un
  auditor mira primero.

Un RAT que presenta como completo lo que no lo está es peor que no tenerlo,
porque nadie vuelve a mirarlo.

### Dos comprobaciones que impiden que se quede viejo

El mecanismo era correcto y el registro salía **vacío**, porque ningún servicio
había declarado sus tratamientos y casi ningún campo personal estaba marcado como
tal. Un RAT correcto por dentro y vacío por fuera es exactamente el papel que
nadie lee. Ahora hay veinticinco actividades declaradas, el mapa recoge los
campos personales de todos los servicios —correos, teléfonos, apellidos,
direcciones, NIF y las IP, que también lo son— y dos gates lo sostienen:

- **Una columna que parece dato personal y no declara su sensibilidad rompe el
  preflight.** Sin esto, el registro es correcto el día que se escribe y mentira
  un mes después: alguien añade un `email_facturacion`, nadie lo marca, y el RAT
  que se le enseña a un auditor dice que ese dato no existe. Las excepciones
  —`direccion` cuando significa «entrante o saliente», un `manifiesto` que
  contiene «nif» por casualidad— se justifican una a una, con su motivo escrito.
- **Un objeto con datos personales y sin tratamiento declarado también rompe el
  preflight.** Marcar un campo y no decir para qué se trata deja el registro a
  medias: el auditor ve que el dato existe y no ve por qué.

### La finalidad la decide el cliente, no el fabricante

La misma tabla de contactos se trata **por contrato** en una empresa y **por
interés legítimo** en otra. El responsable del tratamiento es quien responde ante
la autoridad —el cliente— y no quien escribe el software, así que lo declarado en
el código es el punto de partida y cada tenant puede cambiar finalidad, base
legal, plazo y responsable desde la configuración, con el mismo historial de
versiones que cualquier otro ajuste.

El registro dice, campo a campo, **qué ha decidido el cliente y qué venía puesto
de fábrica**. Sin esa distinción, un responsable cree haber revisado lo que solo
viene de serie.

La base legal es una **lista cerrada** —las seis del artículo 6—: con texto libre
acaban conviviendo «legítimo interés», «interes legitimo» e «interés legítimo
(ver contrato)» como tres bases distintas en el mismo registro, que es justo el
campo que un auditor mira primero.

Las dos cosas se piden en `/{servicio}/cumplimiento/rat` y
`/{servicio}/cumplimiento/informe`. Cada servicio publica lo suyo porque ninguno
lee el esquema de otro, y por tanto ninguno puede hablar de los datos de otro: el
registro completo de una instalación es la unión de los doce.

El **informe de cumplimiento** se compone de lo que ya existe —cobertura de
controles GRC, verificación de la cadena de auditoría, políticas activas,
certificados de destrucción— en vez de mantener un informe aparte. Un informe que
se rellena a mano dice lo que alguien quería que dijera; este dice lo que hay.
Cuando un apartado no se puede leer **se dice**: un apartado ausente se lee como
«no aplica», y la diferencia entre eso y «no se ha podido comprobar» es justo la
que importa en una auditoría.

Los apartados los **aporta cada servicio dueño del dato**, no el núcleo. Si el
núcleo importara `tenancy` para leer la cobertura de controles, pasaría a
depender de un servicio y se acabó el despliegue independiente. Invertido, cada
servicio aporta lo suyo y el núcleo no conoce a ninguno.

## SSO que se sostiene en una empresa de verdad (`CRM-00.05.01.11` a `.15`)

Que el SSO funcione en la demo y que se sostenga en una empresa con seis
dominios, tres filiales y un departamento de sistemas que rota certificados son
dos cosas distintas. Esto es lo segundo.

### El correo decide el proveedor, y el subdominio hereda (`CRM-00.05.01.14`)

Preguntarle al usuario cuál es su proveedor es una pregunta que no sabe
contestar: él sabe su correo, no si su empresa usa Entra ID o Ping. El dominio lo
resuelve sin preguntar nada.

Un proveedor lleva **varios dominios**, no uno. Las empresas los acumulan
—adquisiciones, marcas, el de siempre y el nuevo— y con uno solo cada dominio
extra obliga a duplicar el proveedor entero: la misma configuración, el mismo
certificado y el mismo mapeo de roles, mantenidos por separado hasta que
divergen.

El **subdominio hereda del padre**: `ventas.ejemplo.com` va al proveedor de
`ejemplo.com`. Si no, cada filial obligaría a una fila nueva y el día que falte
una, esa gente no puede entrar. Y gana **el más específico**: si alguien
configura `ventas.ejemplo.com` aparte, es porque quiere otra cosa para esa gente.

### Forzar SSO, con una salida de emergencia que se ve (`CRM-00.05.01.13`)

Con una contraseña local viva, el SSO es una comodidad y no un control: quien se
va del directorio sigue entrando por la otra puerta, y esa puerta no la mira
nadie. Forzar el SSO es lo que hace que la baja en el directorio corte el acceso
de verdad.

La comprobación va **después** de validar la contraseña y la membresía. Si fuera
antes, el mensaje «esta organización exige SSO» le diría a quien prueba correos
al azar cuáles existen y en qué tenant.

**Y vale para las tres puertas, no para la principal.** Hasta el 04-10-2026
solo la contraseña lo comprobaba:

- **La passkey entraba.** Es la que más importa, porque una passkey es una
  credencial **local**: vive en el dispositivo y en nuestra base, no en el
  directorio del cliente. Quien causaba baja perdía el SSO y conservaba su
  passkey, así que seguía entrando — que es exactamente lo único que forzar el
  SSO viene a impedir. Que una passkey sea más fuerte que una contraseña no
  cambia nada: lo que se exige aquí no es fortaleza, es que la baja corte.
- **El restablecimiento dejaba poner una contraseña nueva**, que el inicio de
  sesión iba a rechazar siempre. Menos grave y más absurdo: el usuario acaba
  convencido de que escribe mal la contraseña que acaba de elegir. «Sin
  contraseña local» tiene que valer también para la puerta que las crea.

Forzar el SSO vale lo que valga la puerta más floja, así que hay una prueba que
recorre las tres y falla si alguna deja de comprobarlo.

**La excepción de rescate es nominal y queda escrita.** Sin ninguna, un IdP mal
configurado —o un certificado caducado un sábado— deja al cliente fuera de su
propio CRM sin forma de arreglarlo, y la salida acaba siendo tocar la base de
datos a mano. Se permite, con nombre y apellidos en la configuración y con un
apunte de auditoría en cada uso: una excepción que no se ve deja de ser una
excepción y pasa a ser la puerta de siempre.

También se puede preguntar **antes** de poner una contraseña si a ese correo se
le va a admitir: dejar ponerla y después no aceptarla al entrar es un camino que
acaba en un ticket.

### Certificados: dos a la vez, y aviso antes (`CRM-00.05.01.15`)

Un certificado de IdP que caduca no avisa. Un sábado por la noche deja de validar
toda aserción y el lunes nadie de la empresa puede entrar.

Los certificados son **una lista**, no uno solo, porque una rotación bien hecha
tiene los dos válidos a la vez: el IdP empieza a firmar con el nuevo cuando le
toca y, mientras, las aserciones firmadas con el viejo siguen valiendo.
Sustituir uno por otro convierte la rotación en una ventana de caída para todo el
tenant, coordinada al minuto con un departamento que no es el nuestro.

Retirar el **último vigente** se niega: quitarlo dejaría al tenant sin poder
validar nada, y eso se descubriría cuando alguien intentara entrar. Que falle
ahí, con el administrador delante, es la diferencia entre un mensaje y una caída.

Un proveedor **sin certificados declarados** no sale «en verde»: sale aparte. No
es uno del que se sepa que está bien, es uno del que no se sabe nada, y la
diferencia importa justo el día que caduca.

### Aserciones que empiezan en el IdP (`CRM-00.05.01.11`)

En el SSO que empieza aquí, nuestra petición lleva un identificador y la
respuesta tiene que citarlo (`InResponseTo`): eso ata la aserción a una petición
concreta e impide reenviarla. En el que empieza en el IdP **no hay petición**,
así que no hay nada que citar, y una aserción interceptada —en un proxy, en un
registro de servidor, en el historial del navegador— vale otra vez hasta que
caduque.

Lo único que lo cierra es **recordar las que ya se han usado**. Por eso eso es
obligatorio y no una opción, y por eso el flujo entero va **apagado de fábrica**:
activarlo tiene que ser la decisión de alguien que sepa que está aceptando
aserciones que él no ha pedido. Una aserción sin identificador se rechaza:
aceptar «porque no se puede comprobar» es no tener la comprobación.

Y las dos vías se cierran distinto, en el punto de retorno:

- **Si la aserción cita una petición**, esa petición tiene que constar como
  emitida por nosotros y **se gasta al usarla**, igual que el `state` de OIDC.
  Una respuesta que cita algo que nunca pedimos no entra, y la misma respuesta
  dos veces solo entra la primera.
- **Si no cita ninguna**, empieza en el IdP: se mira el interruptor del tenant y
  se apunta la aserción para que no valga otra vez.

Una advertencia para quien mantenga esto. La librería que valida la firma
—`python3-saml`— **solo compara el `InResponseTo` si se le pasa el identificador
de la petición**; sin él, no lo mira. Y el ajuste que parecía cubrirlo,
`rejectUnsolicitedResponsesWithInResponseTo`, **no está implementado en la
versión 1.16.0** que se usa: pedirlo no hace nada. Una defensa que parece puesta
y no lo está es peor que no tenerla, porque nadie la vuelve a mirar.

### Cierre de sesión único (`CRM-00.05.01.12`)

Cuando la persona sale del IdP, lo que llega es **su** identificador de sesión
(`SessionIndex` en SAML, `sid` en OIDC), que no se parece en nada al nuestro. Sin
la correspondencia guardada, el aviso llega y no hay a quién aplicárselo: cerrar
sesión en el IdP deja el CRM abierto, que es exactamente lo que el usuario cree
que acaba de evitar.

Se admite cerrar **por sesión o por sujeto**, porque los proveedores hacen las dos
cosas: unos mandan la sesión concreta y otros dicen «esta persona ha salido de
todo». Por sujeto cierra todas las suyas, que es lo que el usuario ha pedido al
pulsar salir.

Y al revés: cuando la salida empieza aquí, se cierra la sesión local y se
devuelve a quién hay que avisar. Cerrar solo aquí deja la sesión del IdP viva, y
volver a entrar no pide credenciales: para el usuario, el botón de salir no ha
hecho nada.

Que **no hubiera nada que cerrar no es un error**: el proveedor puede avisar de
una sesión que aquí ya había caducado, y devolver error haría que reintentara en
bucle. Una sesión que no vino de un IdP se marca como tal, para que nadie busque
un fallo de propagación que no existe.

## Segundo factor: SMS, correo, reverificación y equipos de confianza (`CRM-00.05.01.17`, `.18`, `.20`, `.24`, `.25`)

### Códigos por SMS y correo, con lo que los hace seguros (`CRM-00.05.01.17`)

**No hay código de ningún proveedor de SMS.** El tenant declara URL, cabeceras y
plantilla sobre el transporte genérico, y con eso funciona Twilio, Vonage o la
pasarela del operador local. Con un conector por casa, cada cliente con un
proveedor distinto sería una versión del producto.

**El SMS es el factor más débil y se dice.** Se intercepta con un cambio de SIM
que no depende de nadie de aquí. Está apagado de fábrica, se marca como débil en
el panel de adopción y una política puede prohibirlo sin quitar la MFA.
Ofrecerlo callando eso sería vender una seguridad que no da.

Lo que hace seguro un OTP **no es el código**: seis dígitos son un millón de
combinaciones que, sin tope de intentos, se agotan a fuerza bruta en minutos. Lo
seguro es el conjunto, y cada pieza está porque quitar cualquiera deja el resto
sin valor:

- **caduca pronto** y vale **una sola vez**;
- los **intentos están contados**, y agotarlos invalida el desafío entero;
- el **reenvío tiene espera**, porque si no, «reenviar código» es un amplificador
  de SMS a costa del cliente: un bucle en el navegador y la factura del mes;
- el código **nunca vuelve en la respuesta** — devolverlo «para pruebas» es el
  atajo que acaba en producción — ni se escribe en la auditoría, que si no
  convertiría el registro que sirve para investigar en el sitio donde se
  encuentran credenciales;
- la dirección se enseña **recortada** («\*\*\*34»), porque esa pantalla se ve
  antes de estar autenticado del todo y enseñarla entera convertiría el login en
  una forma de leer el teléfono de cualquiera con solo saber su correo;
- y la comparación es en **tiempo constante**: comparar cadenas sale antes cuanto
  más se diferencian, y ese tiempo se mide desde fuera.

Si el envío falla, **se dice**. Tragárselo dejaría al usuario esperando un código
que no va a llegar con el sistema diciendo que todo fue bien. Y que no haya
dirección **no es un error del sistema**: es un dato que falta, y decirlo así
evita que soporte busque un fallo de envío que no existe.

### Reautenticación reforzada (`CRM-00.05.01.18`)

Una sesión dura horas porque tener que renovarla cada cuarto de hora haría el
producto inusable. Pero una exportación de toda la base a las seis de la tarde no
puede apoyarse en un factor que se superó a las nueve de la mañana.

Por eso el step-up pregunta **cuándo** fue el último factor fuerte, no **si** el
usuario tiene MFA configurada. La sesión guarda los factores superados con su
marca de tiempo, y las operaciones sensibles exigen uno reciente.

La lista de operaciones sensibles es **una tabla de datos**, no `if` repartidos:
lo que hace que una operación nueva quede cubierta es añadirla ahí, y lo que hace
que se vea lo que **no** está cubierto es poder leerla entera de una vez. Hoy:
exportación masiva, cambio de permisos, borrado en bloque, suplantación, claves
de máquina, cambio de MFA, restauración y baja del tenant.

Y se aplica **en todas**, también en las que ocurren fuera del servicio de
identidad. La mitad de esas ocho —exportar, borrar en bloque, restaurar— pasan en
otro servicio, y la fila que dice cuándo se superó el último factor vive en el
esquema de identidad, que ningún otro servicio puede leer. Lo que lo resuelve es
propagar **la marca y no la tabla**: el instante del último factor fuerte viaja
dentro del token y en las cabeceras firmadas, igual que los permisos. Firmada,
porque una cabecera suelta la pondría cualquiera que alcanzara la red interna y
bastaría con decir «me acabo de verificar».

De ahí sale una consecuencia práctica: **al superar el factor se entrega un token
nuevo**. El que se tenía se emitió antes de verificarse y sigue diciendo que no
hay factor, así que elevar el nivel sin cambiar de token serviría dentro de
identidad y no serviría fuera.

Dos excepciones, y las dos deliberadas. **Una credencial de máquina no teclea un
código**: tratarla como a una persona dejaría los procesos automáticos parados
para siempre y sin nadie a quien pedirle nada; lo que la protege es la credencial,
su ámbito y el registro de lo que hace. Y **una marca ilegible no vale como
verificación**: dejarla pasar convertiría un error de formato en una puerta
abierta.

Dos detalles que importan en la pantalla: sin sesión **no se deja pasar**
—dejarlo pasar «porque no se puede comprobar» es como no tener la comprobación—,
y la respuesta distingue «no tienes factor» de «vuelve a verificarte», porque
para quien está delante son dos cosas muy distintas. El front puede consultar el
nivel de la sesión **antes** de que el usuario rellene un formulario entero.

### Equipos de confianza (`CRM-00.05.01.20`)

Recordar un equipo es la razón número uno por la que la gente pide que le quiten
la MFA, así que se puede. Tres cosas lo hacen aceptable y no un agujero:

- **caduca** — la confianza no es para siempre; si lo fuera, el segundo factor se
  pediría una vez en la vida del portátil;
- **se revoca en remoto**, uno a uno o todos de golpe. El botón que de verdad se
  usa es «he perdido el portátil», porque uno a uno no sirve cuando lo que ha
  pasado es que ya no se sabe cuáles había;
- es **por usuario**, no por equipo: un ordenador compartido no hereda la
  confianza de quien lo usó antes.

Va **desactivado de fábrica**: recordar un equipo es renunciar al segundo factor
en ese equipo, y eso lo decide el cliente. El equipo solo se recuerda si en esa
misma entrada se ha demostrado el factor —recordarlo sin haberlo pasado sería una
forma de no tener MFA nunca—, y **nunca salta la contraseña**: ahorra el factor,
no la credencial, y confundir las dos cosas convierte un portátil robado en una
sesión abierta.

### Delegar el factor al IdP (`CRM-00.05.01.24`)

Pedir el segundo factor dos veces —una en el IdP corporativo y otra aquí— es la
queja más repetida de cualquier despliegue de SSO, y lo que consigue de verdad es
que el cliente pida que se quite la MFA del CRM.

Se acepta el factor del proveedor, pero **no se da por hecho**: solo si el
proveedor declara qué valores de `acr`/`amr` cuentan. Sin esa lista se pide el
factor aquí, porque cualquier IdP puede mandar un `amr` que diga lo que sea, y
creérselo sin acuerdo previo convierte la MFA en una casilla que rellena el otro
lado. SAML trae el contexto en otro sitio y se admite con el mismo nombre, para
que la configuración sea una sola y no una por protocolo.

### Panel de adopción (`CRM-00.05.01.25`)

Un panel que solo diga «78 % de adopción» no sirve para nada: lo que hace falta
es **la lista de los que faltan**, porque el trabajo es hablar con ellos.

Se separa por **fuerza del factor**, porque «tiene MFA» mete en el mismo saco una
passkey y un SMS, que es precisamente la distinción que alguien va a querer hacer
cuando decida apretar. Y con cero usuarios el porcentaje **no es 100**: es que no
hay nada que medir, y decir 100 sería un verde que nadie se ha ganado.

## Previsión de ventas (`CRM-03.02.01`, `CRM-03.01.01.04` y `CRM-03.01.01.13`)

La previsión es el entregable que más se mira y el que peor envejece. Todo lo que
hay aquí sale de una idea: **un número de previsión solo vale si se puede
explicar**. Un total sin desglose no se discute —se cree o no se cree— y uno que
cambia cada vez que se consulta no se puede ni comparar consigo mismo.

### Categorías: datos, no una lista en el código (`CRM-03.02.01.01`)

«Pipeline, best case, commit, cerrado» es lo habitual, pero hay quien mete
«upside» en medio y quien lo llama todo de otra manera. Con la lista escrita en
el código, cada organización es una versión del producto; como tabla, es
configuración del tenant. Se siembran las cuatro de serie la primera vez, para
que se pueda empezar sin configurar nada y renombrarlas después.

Lo que sí es del sistema es el **significado operativo**, y va en dos banderas
explícitas y no deducido del nombre: si cuenta como compromiso y si es terminal.
Deducirlo de la palabra «commit» se rompería en cuanto alguien la traduzca.

Una categoría que no existe **se rechaza**. Aceptar cualquier texto haría que una
errata creara una categoría fantasma que no sale en ningún informe y cuyo importe
desaparece del total sin que nadie lo eche en falta: el peor tipo de error de
datos, el que resta en silencio.

### Multi-moneda con el cambio del día, no el de hoy (`CRM-03.02.01.07`)

Una oportunidad cerrada en marzo tiene que seguir valiendo lo que valía en marzo.
Convertirla siempre al cambio actual hace que el histórico de ventas se mueva
solo y que dos informes del mismo trimestre den números distintos según cuándo se
sacaron.

Los tipos de cambio **se administran en `tenancy` y se leen en todos los
servicios**. Estaban solo en `tenancy`, y al montar la previsión apareció el
problema: `sales` no puede leer el esquema de otro servicio —lo impide el gate de
arquitectura, y con razón—. Las salidas eran tres: llamar a `tenancy` por HTTP
por cada línea de un forecast de diez mil oportunidades, saltarse la regla, o que
la tabla viva en el esquema de cada servicio y se replique por evento. Se eligió
la tercera, que es la misma que ya usan los ajustes en caliente y las claves de
tenant. El precio es una copia por servicio; lo que compra es que una previsión
no dependa de que otro servicio esté en pie.

Lo que **no se ha podido convertir sale aparte y no se cuenta como cero**. Un
total al que le faltan importes en silencio es peor que uno que avisa, porque
nadie lo cuestiona. El aviso va pegado al número, no en un campo que nadie mira.

### Por jerarquía, y el agujero que se ve (`CRM-03.02.01.02`)

La jerarquía llega **resuelta** —nodo → comerciales— porque el organigrama vive
en `identity`. Tiene además la ventaja de que la misma llamada sirve para agrupar
por territorio, por canal o por lo que el cliente use, sin tocar nada.

El total de la compañía se calcula **aparte y no sumando los nodos**. Una
oportunidad cuyo dueño no esté en ninguna rama —alguien recién incorporado, un
registro huérfano tras una baja— desaparecería de la suma sin que nadie lo
notara, y el agujero se descubre al final del trimestre. Si la resta no da cero,
se dice y se cuantifica.

### Desglose por líneas (`CRM-03.02.01.08`)

Por producto, familia o tipo de ingreso, calculado sobre **las líneas** y no
sobre la cabecera. Es lo único que permite que una oportunidad con software y
servicios cuente en las dos familias por su parte correspondiente; repartir la
cabecera a ojo daría un desglose que suma bien y reparte mal, que es peor que no
tenerlo.

La familia se **copia en la línea**, igual que la descripción y el precio: si se
leyera del catálogo al hacer el informe, recategorizar un producto reescribiría
la previsión de trimestres ya cerrados.

### Ajustes del responsable, con nombre y motivo (`CRM-03.02.01.03`)

Los managers ajustan siempre, porque saben cosas que no están en el CRM: que un
cliente ha cambiado de director de compras, que el competidor ha bajado el
precio. **El problema nunca fue que ajusten**: es que el ajuste se hacía en una
hoja aparte y nadie sabía después quién quitó doscientos mil euros ni por qué.

Aquí el ajuste es un registro con autor y **motivo obligatorio**, y se guarda el
número bruto al lado del ajustado. El bruto no es redundante: sin él no se puede
medir si los ajustes de alguien acertaron, que es la única forma de saber si
conviene hacerle caso el trimestre que viene. Esa medición está —«¿el ajuste
acercó al número real?»— y cuando no hay nada cerrado todavía **dice que no es
medible** en vez de devolver un cero que parecería un acierto perfecto.

### Instantáneas y *waterfall* (`CRM-03.02.01.04`, `CRM-03.02.01.05`)

Sin fotos no hay *waterfall*: «qué ha cambiado desde el lunes» no se puede
contestar mirando solo el estado de hoy, y reconstruirlo desde el historial de
cambios es caro y frágil. La foto guarda **el estado de cada oportunidad, no una
referencia**: si apuntara a la oportunidad, la foto cambiaría con ella y dejaría
de ser una foto — el fallo clásico de los «históricos» hechos con *joins*.

La diferencia entre dos totales no explica nada. «Hemos bajado 300.000» no dice
si es porque se ha perdido una operación grande, porque tres se han ido al
trimestre siguiente o porque han bajado los importes. Se separan cinco causas
porque cada una lleva a una conversación distinta: **entradas, salidas, ganadas,
perdidas, deslizadas y variación de importe**.

Y **salir de la foto no es lo mismo que perderse**: puede haberse ido a otro
trimestre. Mezclarlo inflaría la tasa de pérdida y llevaría a revisar un problema
que no existe. Dos fotos en monedas distintas no se comparan: restar euros de
dólares daría un *waterfall* precioso y falso.

### Cierre de periodo (`CRM-03.02.01.09`)

Cerrar es lo que hace que un número signifique algo. Mientras el periodo está
abierto, el commit del trimestre cambia cada vez que alguien toca una
oportunidad, y comparar dos informes de fechas distintas es comparar dos cosas
que no son la misma. Cerrado, el número queda y lo que pase después se ve como
variación, que es la información útil.

La foto se toma **dentro** del cierre y no se deja para después: un cierre sin
foto es un número que ya no se puede reconstruir. Y cerrar **impide tocar** las
oportunidades cuyo cierre cae dentro; sin eso, cerrar sería un gesto decorativo y
al trimestre siguiente nadie entendería por qué la foto no cuadra con el detalle.

Reabrir es un acto explícito, **motivado y contado**. Si fuera gratis, «cerrado»
dejaría de significar nada. El contador de reaperturas está para que se vea
cuántas veces ha pasado, que es la señal de que el proceso de cierre no se está
respetando.

### Deslizamiento (`CRM-03.01.01.13`)

`CambioEtapa` solo anotaba cuando la oportunidad se movía de etapa, y el
deslizamiento **casi nunca va acompañado de un cambio de etapa**: lo normal es que
la fecha se empuje dos semanas sin tocar nada más. Sin registrarlo, el dato que
explica por qué el trimestre no salió como se dijo sencillamente no existía.

Se guardan **los dos valores**, el de antes y el de después: con solo el nuevo,
reconstruir el anterior obliga a recorrer el historial hacia atrás y a acertar con
el orden; con los dos delante, el deslizamiento es una resta.

Y se cuenta **el número de veces**, no solo los días. Una oportunidad empujada
cuatro veces dos semanas cada una no es lo mismo que otra movida dos meses de
golpe, aunque el total coincida: la primera es un problema de calificación y la
segunda, un cliente que cambió de plan.

### Probabilidad manual (`CRM-03.01.01.04`)

La probabilidad sigue a la etapa salvo que alguien la haya fijado a mano. Antes
eso se **deducía** comparando con la probabilidad de la etapa de origen, y la
heurística fallaba por los dos lados: un ajuste manual que coincidiera con el
valor de la etapa se perdía al avanzar, y uno que no coincidiera se arrastraba
para siempre por todas las etapas siguientes. Ahora es una bandera explícita, que
es lo que era desde el principio.

Importa porque si el ajuste se pisa, el comercial deja de ajustar a la tercera
vez y el dato se convierte en decorativo — y con él, el ponderado del pipeline.

## Extensión sin código, de punta a punta (`CRM-00.04.03`)

Definir un campo por configuración ya se podía: el metamodelo (`CRM-00.04.01`)
guarda la definición, la valida y la publica en el `describe`. Lo que no se podía
era **usarlo**. Y esa es la diferencia que decide si una implantación necesita
desarrollo o no.

La promesa es concreta: un consultor añade un campo en casa del cliente y ese
campo **llega solo** a la base de datos, a la API, a los filtros, a los flujos y
a los informes. Cada eslabón que falte la convierte en media verdad — el campo
existe, pero no se puede filtrar, o no sale en el informe — y devuelve al cliente
al mismo sitio: pedir desarrollo.

### Por qué el esquema es dato y no `ALTER TABLE`

Añadir una columna es un DDL, y con mil tenants en la misma tabla el campo que
añade uno **bloquea a los novecientos noventa y nueve restantes**. Por eso los
campos del tenant viven en una columna JSONB y la definición en el servicio de
metadatos.

Lo que se pierde así —tipado e índices— se recupera de forma explícita: índices
de expresión declarados por campo y una vista tipada por tenant. Y cuando el
volumen justifique una columna real, existe el camino (`CRM-00.04.03.11`), pero
como excepción medida.

### El esquema se replica, no se consulta

`party` no puede leer el esquema de `metadata`, y preguntárselo por HTTP en cada
escritura pondría el alta de una cuenta a depender de que otro servicio esté en
pie, además de duplicar la latencia. Se replica por evento, igual que los ajustes
en caliente, las claves de tenant y los tipos de cambio.

Viaja **la lista entera de campos, no el delta**. Un delta obliga a que el
consumidor tenga el estado anterior correcto, y con entrega *at-least-once* sin
orden garantizado eso no se puede afirmar: un evento perdido dejaría la réplica
desalineada para siempre y nadie lo vería hasta que alguien no pudiera guardar.
Por lo mismo, cada publicación lleva **versión**, y un evento viejo reenviado se
descarta en vez de devolver campos que ya se habían quitado.

### Publicar es un acto, configurar no (`CRM-00.04.03.02`)

Mientras alguien define campos, el esquema a medias **no viaja**. Si viajara, el
cliente vería su formulario cambiar mientras el consultor todavía está pensando,
y una validación a medio escribir rechazaría altas buenas. Se publica cuando se
decide, y a partir de ahí cada servicio valida, filtra e indexa por esos campos.

**Un campo que no está definido se rechaza.** Aceptarlo convertiría una errata
—`fecha_visita` escrito `fecha_vista`— en un dato que se guarda, no sale en
ningún formulario y no lo encuentra nadie; al año, la mitad del JSONB sería
basura que nadie se atreve a borrar porque no se sabe quién la puso. El error
dice además **qué campos sí existen**: sin eso, quien lo recibe prueba a ciegas.

Otras tres decisiones del validador:

- **Se normaliza al escribir, no al leer.** Si cada lector convirtiera por su
  cuenta, dos lectores acabarían discrepando —uno leyendo `"10"` y otro `10`— y
  el filtro no encontraría lo que la ficha enseña.
- **En una actualización solo se miran los campos que llegan.** Exigir los
  obligatorios que no vienen rechazaría un cambio de teléfono por un campo que el
  registro ya tiene relleno. Y lo que llega **se fusiona**, no reemplaza: mandar
  solo el campo que cambia es lo natural desde un formulario, y reemplazar
  borraría los demás en silencio.
- **Un campo deprecado se lee pero no se escribe.** Es lo que permite retirarlo
  sin romper de golpe una integración que aún lo manda: se ignora el valor y se
  avisa, en vez de cortarle el alta.

### Filtro, orden e índice (`CRM-00.04.03.03`)

El casteo al tipo declarado es lo que separa un filtro que funciona de uno que
miente: sin él, JSONB compara **texto**, y `"9" > "10"` es cierto. Un filtro
«importe mayor que 10» que devuelve el de 9 es peor que no tener filtro, porque
quien lo usa se lo cree.

La gramática de operadores está **cerrada**. Una abierta sobre JSONB acaba siendo
SQL interpolado, y ahí es donde entra la inyección.

Los índices son **parciales por tenant**, y ese es el punto: un índice global
sobre una expresión JSONB indexaría las filas de los mil tenants para servir las
consultas de uno, y crecería con todos ellos. Parcial, cada tenant paga solo lo
suyo y el índice no existe para quien no lo pidió. Y un índice que sobra **se
retira**: no falla nada, solo hace más lenta cada escritura de la tabla para
siempre, que es la forma más cara de no enterarse.

### La vista tipada, que es lo que lo hace explotable (`CRM-00.04.03.04`)

Cada tenant tiene una vista que proyecta **cada campo personalizado como columna
tipada**. Es lo que permite que Power BI, Metabase o un `SELECT` de alguien de
sistemas lean los campos de la implantación sin saber que por debajo hay JSONB y
sin que nadie recuerde castear.

Sin ella, «el campo está en la base de datos» es cierto y a la vez inútil: está,
pero en un formato que ninguna herramienta de informes entiende sola.

Es una **vista y no una tabla materializada** a propósito: una materializada se
queda vieja, y un informe que enseña el dato de ayer presentándolo como el de hoy
es peor que uno que tarda un segundo más.

### Los campos llegan a los flujos (`CRM-00.04.03.05`)

El motor de condiciones ya sabía resolver rutas con puntos (`@campos.obra`). Lo
que faltaba era que **el dato llegara**: `automation` no lee el esquema de
`party`, así que si los campos propios no viajan en el evento, para el flujo no
existen. Ahora viajan, y el consumo está declarado en el contract testing
(`CRM-00.03.01.03`) para que quitarlos del evento rompa el preflight en vez de
dejar de disparar una automatización que el cliente configuró.

### Previsualizar antes de publicar (`CRM-00.04.03.09`)

Quien añade un campo obligatorio a un objeto con ochenta mil registros no sabe
que los ochenta mil se quedan sin rellenar — y no lo sabe hasta que alguien
intenta guardar uno viejo y no puede. La previsualización lo dice antes: qué se
añade, qué se retira, qué cambia de tipo, a cuántos registros afecta y cuántos se
quedarían sin el dato obligatorio.

Cuando no se puede contar, **se dice**. «No se ha podido contar» y «no afecta a
nadie» son cosas distintas, y la diferencia es justo la que importa antes de
publicar.

### Paquetes entre entornos (`CRM-00.04.03.10`)

Se configura en pruebas y después hay que repetirlo en producción, a menudo de
memoria. Con paquetes, el esquema se exporta y se instala.

Lo que se lleva es **la configuración, nunca los datos**: un paquete que
arrastrara registros convertiría una promoción a producción en una fuga, porque
los datos de pruebas suelen ser copias anonimizadas a medias de clientes reales.

**Simular es el valor por defecto.** Un paquete es un cambio de modelo de datos
en producción, y el error más caro que puede cometer quien lo maneja es pulsar el
botón creyendo que todavía estaba mirando. Y lo que ya existe con otro tipo **no
se pisa**: sobrescribir la configuración que alguien ajustó en producción con la
de un entorno de pruebas es la forma habitual de perder dos semanas de trabajo de
un consultor. Instalar deja la configuración puesta pero **no la publica**: eso es
un paso aparte y deliberado.

### Saber si un campo se usa (`CRM-00.04.03.12`)

El uso se cuenta **al escribir y no al leer**: leer mide quién mira, escribir mide
si el campo se rellena, que es la pregunta de quien se plantea retirarlo. Un
campo vacío no cuenta — contarlo haría que todo campo pareciera usado y la
métrica no serviría para decidir nada.

Sin esto, la respuesta a «¿puedo quitar este campo?» es siempre «no lo sé», y por
si acaso no se quita nada: es como un modelo de datos acaba con trescientos
campos de los que nadie recuerda la mitad.

El contador vive en el esquema de **cada servicio**, porque quien ve pasar las
escrituras es el servicio dueño del dato: `metadata` define el campo y no lo
guarda nunca.

### Materializar a columna real (`CRM-00.04.03.11`)

No es la norma, es la excepción, y se decide **con una medida**: sin número, cada
cliente que note su lista lenta pediría columna y acabaríamos con el `ALTER
TABLE` de siempre disfrazado de optimización.

El orden importa: se añade la columna nullable (que no bloquea), se rellena por
lotes desde el JSONB, se crea el índice y **solo entonces** se empieza a leer de
ella. Al revés, la columna se lee vacía mientras se rellena y las listas salen
incompletas sin que falle nada.

### Informes sin modelar aparte (`CRM-00.04.03.06`)

La explotación la resuelve contecintelligence de forma frontless (RT-4), pero
para ofrecer un campo como dimensión o como métrica hace falta **saber que existe
y de qué tipo es** — y los campos que un cliente añade en su implantación no
están en ningún esquema que contecintelligence pueda leer.

El modelo semántico es el puente: publica, por tenant, qué objetos hay, qué
campos propios tienen, **qué papel analítico** juega cada uno y en qué vista SQL
están ya proyectados como columnas tipadas. Con eso, un campo nuevo aparece como
dimensión sin que nadie modele nada aparte — que es la diferencia entre «se puede
informar» y «se puede informar después de que alguien lo configure».

El papel va **explícito y no deducido por el consumidor**: si cada herramienta
decidiera por su cuenta, una acabaría ofreciendo «sumar» sobre un código postal,
que es un número que no se suma.

Va el modelo, **nunca el dato**: mandar valores convertiría una descripción de
esquema en una copia del CRM fuera de su sitio. Y los campos **personales y de
categoría especial se dejan fuera, diciendo cuáles**: acabarían en un cuadro de
mando que alguien comparte por correo, y el enmascaramiento por rol de la API no
llega hasta ahí. Omitirlos en silencio haría que alguien buscara un campo que
existe, no lo encontrara y concluyera que el sistema no lo tiene.

### Importación, exportación y plantillas (`CRM-00.04.03.08`)

La exportación trae los campos propios **por su nombre, igual que los de serie**:
quien exporta no tiene por qué saber cuáles vienen con el producto y cuáles añadió
su consultor, y obligarle a distinguirlos sería trasladarle una decisión de
implementación nuestra. Sin esto, la exportación es incompleta de una forma que
solo nota quien conoce el dato — y lo nota demasiado tarde, cuando ya ha mandado
el fichero. Las columnas salen en **orden estable**, porque una exportación cuyo
orden cambia entre dos descargas rompe cualquier hoja de cálculo que la consuma.

La importación hace el camino inverso: las columnas del fichero que corresponden
a campos propios se recogen y se validan contra el esquema publicado. Ignorarlas
dejaría fuera precisamente los campos que el cliente añadió porque le importaban,
y el importador que «funciona» sería el que pierde la mitad del fichero.

## Gobierno único de la suite (`CRM-00.01.07`)

contecrm ya depende de contecmind para el corpus documental (RT-5) y de
contecintelligence para la explotación (RT-4). Hasta ahora, el tenant, los
usuarios y la organización se configuraban **tres veces, a mano, en tres
sitios**, y ese es el sitio por donde se rompe:

- alguien entra en el CRM y no en el gestor documental, y lo descubre el día que
  abre un contrato;
- alguien se va de la empresa, se le da de baja aquí, y conserva el acceso a los
  informes durante meses;
- un departamento se reorganiza en una herramienta y no en las otras, y los
  permisos que cuelgan de él dejan de coincidir sin que nadie lo haya cambiado a
  propósito.

La regla de la que sale todo lo demás: **contecrm es la fuente, las demás son
réplicas.** De ahí la identidad única de tenant (`CRM-00.01.07.01`): un mismo
identificador y unos mismos datos en las tres herramientas. Un único punto de administración, empuje automático y reconciliación
que enseñe lo que ha divergido.

### La baja pesa más que el alta, y va primero (`CRM-00.01.07.03`)

Un alta que tarda es una molestia: la persona llama y alguien lo mira. **Una baja
que tarda es una puerta abierta que no ve nadie.** Por eso el desaprovisionamiento
tiene prioridad sobre todo lo demás en la cola, por eso su fallo se marca como
grave en la cuarentena, y por eso el panel saca las bajas sin aplicar aparte del
resto: es lo único que hay que mirar con prisa.

Un detalle que parece menor y no lo es: **la baja se encola aunque el rol del
usuario ya no esté mapeado.** Negarse a dar de baja a alguien porque su rol
desapareció del mapeo sería el peor fallo posible — exactamente el caso en que
hay que echarlo.

### El orden se garantiza por sujeto, no en general (`CRM-00.01.07.10`)

Dos cambios sobre personas distintas pueden aplicarse en cualquier orden; dos
sobre la misma, no. Aplicar el alta después de la baja —que es lo que pasa con
reintentos y entrega *at-least-once*— deja dentro al que se fue, y el sistema
diría que todo fue bien.

La cola guarda **el estado que se quiere, no el historial de intenciones**:
encolar tres cambios seguidos de la misma persona reemplaza la fila en vez de
añadir otra. Aplicarlos los tres sería aplicar dos estados intermedios que ya no
interesan a nadie, y el último podría llegar primero. Y reencolar algo que ya está
igual allí **no gasta una llamada**: empujar lo mismo otra vez cuenta como
modificación en la auditoría de la otra herramienta, y eso es ruido que después
nadie sabe interpretar.

### Un empuje que falla en silencio es peor que no tener empuje (`CRM-00.01.07.02`)

Porque entonces nadie mira. De ahí que se guarden **dos huellas por objeto**: la
deseada y la aplicada. Con solo un sello de tiempo, un empuje que falló y otro
que nunca se intentó se parecen demasiado.

Lo que falla se reintenta con **espera creciente** —una herramienta caída diez
minutos no puede costar diez minutos de martilleo— y tras agotar los intentos va
a **cuarentena**: ni se reintenta para siempre, que esconde el problema en un log
que nadie mira, ni se abandona a la primera, que convierte un fallo de red en
trabajo manual. La cuarentena enseña **qué se mandó**, porque sin eso quien lo
mira tiene que adivinar si el problema es el dato o la herramienta.

Y una herramienta desactivada **no gasta intentos**: si los gastara, el objeto
acabaría en cuarentena por algo que no tiene nada que ver con él.

**Para el usuario: la cuarentena se ve y se reintenta desde la consola.** Cada
fila apartada sale con la herramienta, lo que se mandó, cuántos intentos lleva y
el último error, y con su botón de volver a intentarlo. Las bajas van marcadas,
porque son las únicas cuyo retraso deja un acceso abierto y en una lista larga se
pierden entre las demás.

> **Se vio funcionar el 28-09-2026**, y hasta ese día la consola decía «hay 3
> elementos en cuarentena» y ahí se acababa: ni cuáles, ni con qué se mandaron,
> ni forma de reintentarlos, **aunque las dos rutas llevaban en el servidor desde
> el primer día**. Además, el listado no devolvía el identificador de la fila
> apartada, que es justo lo que la ruta de reintento necesita: existía y era
> inalcanzable. Un aviso sin salida enseña a quien lo lee a dejar de mirarlo, que
> es lo contrario de para lo que se apartó.

### El mapeo de roles es dato (`CRM-00.01.07.04`)

El mismo usuario es «director comercial» aquí, «editor» en el gestor documental y
«analista» en el de informes. Programarlo obligaría a tocar el producto cada vez
que un cliente inventa un rol, que es todas las semanas.

**Un rol sin mapear no concede nada.** Si concediera el rol básico, crear un rol
nuevo en el CRM daría acceso a las otras herramientas sin que nadie lo hubiera
decidido. Y un usuario sin rol mapeado **no se crea allí**: una cuenta sin rol no
sirve para nada y encima hay que acordarse de darla de baja.

Cuando encajan varios roles gana **el de mayor precedencia declarada**, no el
primero: un usuario con dos roles no puede recibir un permiso distinto según el
orden en que estén guardados sus roles.

### La organización se define una vez (`CRM-00.01.07.05`)

Áreas y departamentos salen del árbol de unidades del tenant y se replican a cada
herramienta con su propia forma. Definirlo en tres sitios garantiza que a los tres
meses son tres árboles distintos.

Va **plano y con el padre dentro**, no anidado: un árbol anidado obliga a cada
consumidor a recorrerlo, y la mitad de las herramientas quieren la lista.

### Reconciliación: tres divergencias, tres conversaciones (`CRM-00.01.07.07`)

- **Falta allí** — el empuje no llegó. Es el caso benigno: se reencola.
- **Sobra allí** — hay alguien que aquí ya no está. Es el peligroso: suele ser
  una baja que no se aplicó, y es literalmente un acceso que sigue abierto. El
  aviso va pegado al resultado porque es lo que hay que mirar primero.
- **Difiere** — alguien lo cambió en la otra herramienta. **No se pisa sin
  decirlo**: puede ser un ajuste deliberado del administrador de allí, y
  sobrescribirlo en silencio es cómo se pierde la confianza en el empuje
  automático. Repararlo exige pedirlo explícitamente.

Y cuando el conector **no sabe leer** el estado remoto, se dice. «No se ha podido
comprobar» y «está todo bien» son cosas distintas, y confundirlas es precisamente
por lo que nadie se fía de los paneles de sincronización.

**Para mantenimiento: por qué no se puede comprobar, hay tres motivos y se
distinguen.** Que la herramienta no declare `_listados`, que conteste un error, o
que la llamada reviente. El mensaje dice cuál de los tres ha sido, y si sólo se
pudo leer parte, `motivos_ilegibles` explica lo que faltó — una reconciliación
que leyó la mitad se leería como completa sin eso.

> **Se vio funcionar el 28-09-2026, y se encontraron dos fallos que llevaban
> tiempo.** La lectura del estado remoto **no entraba con usuario y contraseña**:
> sólo miraba un token escrito a mano en la configuración. Una herramienta que
> emite tokens de quince minutos —contecmind, la primera para la que se escribió
> esto— no tiene ninguno, así que escribir funcionaba y **leer no**: la
> reconciliación quedaba apagada para siempre, y de la forma más difícil de ver,
> porque el panel decía exactamente lo que tenía que decir.
>
> Y el motivo que daba era el equivocado: decía «declara `_listados` en su
> mapeo» con `_listados` ya declarado y un 401 por debajo. Ir a poner lo que ya
> está puesto es la peor forma de perder una tarde, porque quien la pierde acaba
> concluyendo que el panel miente.

### Simular antes de aplicar (`CRM-00.01.07.11`)

El error caro aquí no es el técnico: es **desactivar a media plantilla** en el
gestor documental por un mapeo de roles mal escrito, y enterarse cuando llaman.
La simulación dice, herramienta a herramienta, qué se crearía, qué cambiaría y
qué se desactivaría.

### Conectores: lo genérico es el suelo (`CRM-00.01.07.08`)

Una herramienta cualquiera se conecta declarando **dirección, credencial y el
mapeo de campos y de roles**. No hace falta escribir código, y por tanto un
cliente con una herramienta que no conocemos no obliga a tocar el producto.

Los conectores nativos —contecmind, contecintelligence— van **encima y heredan el
transporte**: solo cambian lo que de verdad es distinto, que son sus rutas.
Reescribir el transporte entero por producto es lo que hace que mantener cinco
conectores sea imposible. Y siempre hay conector: un tipo desconocido cae en el
genérico en vez de quedarse sin transporte.

**Y valores constantes de la conexión, que no son un dato del objeto.** El
mapeo de campos renombra —lo que aquí es `nombre` allí es `name`— pero no puede
inventarse una clave que no viene en el origen, y algunas herramientas exigen
justo eso. El caso real: dar de alta una organización en contecmind pide
`app_id`, que dice **qué aplicación la nombra**; eso no es un campo del tenant,
es de la conexión. Sin poder declararlo, el alta salía sin él y se comía un 422,
y la única salida habría sido un conector propio para contecmind con ese campo
escrito dentro — que es exactamente lo que este diseño evita.

Los campos fijos se escriben **con el nombre de allí**, porque son suyos: no
pasan por el mapeo, o se traduciría dos veces. Y **se aplican al enviar, no al
encolar**: si fueran parte de la carga guardada, el valor quedaría congelado con
la fila y el camino real sería este —montas la integración, el alta falla porque
falta el campo, lo configuras, y la cola sigue fallando para siempre porque lo
pendiente lleva la carga vieja—. Quien lo mirara concluiría que configurarlo no
sirve de nada. Aplicándolos al enviar, corregir la configuración arregla también
lo que ya estaba encolado. Y **no pisan el dato del objeto**
si el objeto ya lo trae: un valor por conexión es un valor por defecto, no una
imposición. Tampoco van con las credenciales aunque se configuren a la vez —
aquéllas se cifran y no se vuelven a enseñar, y un `app_id` que nadie puede
mirar es un valor imposible de comprobar el día que el alta empiece a fallar.

**La credencial puede ser un token o una cuenta, y casi siempre tiene que ser
una cuenta.** Un token escrito en la configuración vale para herramientas con
credenciales de larga vida, y para las demás es una trampa: **contecmind emite
tokens de quince minutos**, así que un token guardado funciona el cuarto de hora
en que alguien monta la integración —justo cuando la prueba y la da por buena— y
después falla para siempre con un error de autenticación que parece una
credencial mal escrita. Quien lo mire buscará donde no es.

Por eso una herramienta puede llevar **usuario, contraseña y ruta de entrada**:
el conector entra cuando hace falta y renueva cuando el token vence. **Un 401 se
reintenta una vez tras renovar; un 403 no se reintenta nunca**, porque ahí el
token vale y lo que no vale es lo que esa credencial puede hacer — reintentarlo
convertiría un permiso mal configurado en un bucle de peticiones contra la otra
herramienta, con el error de verdad enterrado bajo el ruido. El token se comparte
entre todas las llamadas de esa herramienta: un alta en cascada de doscientas
personas no puede ser doscientas entradas.

La cuenta con la que entra la crea **quien configura la integración**, y en
contecmind necesita ser administradora del tenant. Para dar de alta usuarios y
departamentos basta con eso; **dar de alta una ORGANIZACIÓN exige además rol
cross-tenant**, y es coherente: crear una organización nueva no es algo que
pueda hacer el administrador de otra. Verificado contra su API: con una cuenta
de tenant el alta de usuario sale y la de organización contesta «only a
cross-tenant admin can provision». No sirve el token delegado de
la aplicación: ese se obtiene con la credencial de la aplicación y un nombre de
usuario cualquiera, así que con él se podrían dar de alta y de baja personas.
Pedir documentos en nombre de alguien y gobernar quién existe son dos cosas
distintas y llevan credenciales distintas.

La dirección pasa por el **guard de salidas**, igual que un webhook o un IdP:
aquí viajan datos de personas y una credencial de administración, y una dirección
apuntando a la red interna convertiría el empuje en una forma de hablar con lo
que no se alcanza desde fuera. Las credenciales se guardan **cifradas**: en claro
serían la llave de administración de otra herramienta en una tabla que consulta
media aplicación.

El transporte **nunca lanza hacia arriba**: devuelve el resultado y la cola decide.
Una excepción que subiera desde un envío detendría el proceso de todos los demás
objetos del lote por culpa de uno.

### Auditoría transversal (`CRM-00.01.07.12`)

Un solo registro que dice quién cambió qué y **en qué herramienta acabó
aplicándose**. Sin él, contestar «¿por qué este usuario sigue entrando en el
gestor documental?» obliga a mirar tres registros de auditoría distintos y a
cruzarlos de memoria.

## Casos y SLA (`CRM-04.01.01`, `CRM-04.01.02`)

Con este bloque nace el servicio `service`, el pilar de atención al cliente. Lo
que gobierna todo lo demás: **un SLA que no se puede explicar no se puede
exigir**.

### Severidad y prioridad son dos campos (`CRM-04.01.01.01`)

La **severidad** es del problema —qué está roto y cuánto—. La **prioridad** es de
la respuesta —en qué orden se atiende—. Fundirlas en un solo campo, que es lo
habitual, hace imposible decir «esto es grave pero puede esperar a mañana» y
«esto es menor pero es para el cliente que renueva el viernes». Y en cuanto se
funden, alguien empieza a marcar todo como crítico y el campo deja de significar
nada.

**Y la severidad es cuatro valores, los mismos en todas partes.** `baja`,
`media`, `alta` y `critica`. Se dice aquí porque hasta el 28-10-2026 no era
verdad del todo: la del caso sí era lista cerrada, la del problema era texto
libre —«Alta», «ALTA» y «muy alta» se guardaban las tres y contaban como tres
severidades distintas al agrupar— y la telemetría mantenía su propia copia de la
lista para mandarla en el comando que abre un caso. Esa copia coincidía, pero el
día que hubiera dejado de coincidir el aparato habría avisado, el comando habría
salido, el que lo recibe lo habría rechazado por severidad no válida y **el caso
no se habría abierto**: la alarma existiendo y la atención no. Es una lista
sola, de las que cruzan de un servicio a otro, y los tres sitios la leen de ahí.

El caso lleva **código legible** (`CAS-2026-00042`): es lo que el cliente escribe
en el asunto de un correo y lo que se dice por teléfono. Sin él, la referencia
acaba siendo un identificador opaco que nadie transcribe bien.

### La taxonomía es un árbol (`CRM-04.01.01.02`)

Un árbol y no dos campos fijos —categoría y subcategoría— porque cada línea de
servicio clasifica a su profundidad: soporte de software llega a tres niveles y
mantenimiento de instalaciones a cinco. Con dos campos, el tercer nivel acaba
concatenado dentro del segundo y los informes dejan de poder agrupar.

**Solo las hojas clasifican.** Dejar elegir un nodo intermedio convierte
«software» en un cajón donde acaba la mitad de los casos, y entonces la taxonomía
no sirve para lo único que sirve: agrupar. La hoja puede **sugerir** prioridad,
que propone y no impone: quien atiende sabe cosas que la taxonomía no.

Y se guarda **la ruta hasta la raíz**, no solo la hoja: «cuántos casos de
software» no se puede contestar si solo consta «error de licencia» sin saber de
qué cuelga.

### Con qué se relaciona (`CRM-04.01.01.03`)

Cuenta, contacto, producto, activo, contrato y pedido van como **identificadores
opacos y no como claves foráneas**: cuenta y contacto viven en `party`, y ningún
servicio lee el esquema de otro. La integridad se apoya en el evento de borrado,
no en la base de datos.

### Jerarquía e incidencias masivas (`CRM-04.01.01.04`, `CRM-04.01.01.11`)

Cien casos que son la misma caída se cuelgan de un **maestro**: se investiga una
vez y se cierran juntos. Cerrarlos uno a uno no solo es trabajo — es que la
respuesta que recibe cada cliente acaba siendo distinta.

Un maestro **no cuelga de otro maestro**: la cadena se aplana a propósito, porque
una cadena deja algo que nadie sabe cerrar.

Un **duplicado no se borra**, se marca. El cliente que lo abrió tiene derecho a
ver su caso y su respuesta; borrarlo hace que su referencia deje de existir, y
quien pregunta por ella recibe un «no existe» que suena a que nadie le atendió.

### Cierre tipificado y reapertura con ventana (`CRM-04.01.01.09`, `CRM-04.01.01.10`)

El **motivo de cierre es obligatorio**. Sin él, el informe de cierres dice cuántos
se cerraron y no por qué, que es la única parte útil: «resuelto», «no era un
problema» y «el cliente no contestó» llevan a tres decisiones distintas.

La reapertura tiene **ventana**. Pasada, no se reabre: se abre uno nuevo enlazado.
Reabrir un caso de hace ocho meses falsea todos los indicadores del periodo en
que se cerró —tiempo de resolución, cumplimiento de SLA, casos cerrados— y esos
números ya están en un informe que alguien miró. El plazo es un ajuste en
caliente, no una constante.

### El SLA se versiona (`CRM-04.01.02.02`)

Cambiar el SLA **no reescribe el pasado**. Cada publicación es una versión nueva,
y el caso guarda con cuál se abrió. Un contrato renegociado no puede convertir en
incumplidos casos que se atendieron a tiempo con las reglas de entonces, ni al
revés — y esa es exactamente la trampa del SLA guardado como una fila que se
edita.

Gana **lo más específico**: un SLA nominal para una cuenta manda sobre el del
tier, y el del tier sobre el general. Cogiendo el primero que encaje, un cliente
con contrato especial recibiría el trato estándar, que es justo el que paga por no
tener. Ante dos igual de específicas gana la **versión más alta**, porque publicar
una versión nueva es la forma de decir «a partir de ahora, esta».

Un caso **sin SLA aplicable se dice** en la respuesta del alta: un caso sin
compromiso no es un caso cumplido, y si no se dice ahí nadie lo mira hasta el
informe de fin de mes, donde sale como «sin datos».

### Los relojes y las pausas (`CRM-04.01.02.03`, `CRM-04.01.02.04`)

Los plazos son en **horas laborables**. Es lo que hace que un aviso entrado el
viernes a las 18:00 no se incumpla el sábado a las 22:00, cuando no había nadie.

Esto obligó a mover los calendarios laborales al núcleo: `service` no puede leer
el esquema de `tenancy`, y un reloj que preguntara por HTTP cada vez que avanza
pondría el vencimiento de un caso a depender de que otro servicio esté en pie.
Se replican por evento, como los ajustes en caliente y los tipos de cambio; se
administran en un sitio y se leen en todos. Si un tenant no tiene calendario, el
plazo se cuenta en horas de reloj **y se avisa**: no es lo mismo, y dejar que
parezca lo mismo es cómo un SLA de «4 horas» acaba venciendo un domingo de
madrugada sin que nadie lo entienda.

Los vencimientos se **guardan calculados**, no se recalculan al consultar. Es la
otra cara del SLA versionado: recalcular haría que cambiar la definición
reescribiera el pasado.

Entrar en «esperando cliente» **para el reloj**, y salir lo reanuda **desplazando
el vencimiento** por el tiempo parado. Si no se desplazara, parar el reloj sería
decorativo: el caso se marcaría incumplido por una espera que era del cliente. Y
la pausa **se acumula**: un caso que entra y sale cuatro veces perdería tres de
las cuatro esperas si solo se guardara la última, y el tiempo de resolución
saldría peor de lo que fue — lo que acaba en una discusión con el cliente que no
se puede ganar sin el dato.

**Solo la primera respuesta cuenta como primera.** Registrar cada respuesta como
tal haría que el indicador midiera la última, que es el número que siempre sale
bien.

Y los dos incumplimientos se marcan **por separado**: incumplir la primera
respuesta y incumplir la resolución son dos conversaciones distintas con el
cliente.

### Avisar antes, no después (`CRM-04.01.02.05`)

Avisar **cuando ya se ha incumplido** no sirve para nada: el incumplimiento ya
está. Lo único que cambia algo es avisar antes, y por eso el umbral es parte del
SLA y no una constante.

La lista de casos en riesgo se ordena por **lo que queda**, no por prioridad: un
caso crítico con seis horas por delante puede esperar a uno medio que vence en
diez minutos. Y lo **ya incumplido se marca aparte**: mezclarlo haría que la lista
de «en riesgo» se llenara de cosas sin remedio y dejara de mirarse.

El informe de cumplimiento cuenta **la primera respuesta y la resolución por
separado**: un porcentaje único esconde que se contesta rápido y se resuelve
tarde, que es el patrón más común y el que más queja genera. Sin casos con
compromiso no dice 100 %, dice que no es medible.

## Colas, escalado, derechos y satisfacción (`CRM-04.01.01.05` a `.12`, `CRM-04.01.02.01`, `.06`, `.07`, `.08`, `CRM-04.02.02.03`)

El bloque anterior dio el caso y su reloj. Este da la operación: quién lo coge,
qué pasa cuando va mal, a qué tiene derecho el cliente y qué opina al final.

### Presencia y capacidad del agente (`CRM-04.02.02.03`)

**`ausente` y `no_molestar` no son lo mismo**: el primero es «no está» y el
segundo «está pero no puede». Fundirlos hace que un supervisor no pueda saber si
le falta gente o le falta capacidad, que son dos problemas con soluciones
opuestas. Se guarda **desde cuándo**: «lleva cuarenta minutos en no molestar» es
una conversación distinta de «acaba de ponerse».

La capacidad es **por canal** y no un número único: alguien puede llevar tres
chats a la vez y una sola llamada. Con un número único, o se infradotan los chats
o se satura el teléfono. Y un canal **sin tope declarado es sin límite, no cero**:
un agente al que nadie configuró la capacidad tiene que poder trabajar, y tratarlo
como saturado dejaría la cola llena sin que nadie entendiera por qué.

### Asignación y colas (`CRM-04.01.01.05`, `CRM-04.01.01.06`)

Las reglas tienen **la misma forma que las de leads** —condiciones en el formato
de ABAC, prioridad ascendente, gana la primera que encaja—. No es por ahorrar
líneas: es para que el operador aprenda una sola sintaxis de condición en todo el
producto.

Lo que cambia respecto a un lead es que **un caso tiene reloj**. Un lead sin
asignar es una oportunidad que se enfría; un caso sin asignar está consumiendo un
SLA que alguien va a incumplir. Por eso la asignación mira la **capacidad** y no
solo el turno: repartir a quien ya tiene doce casos abiertos no es repartir, es
esconder la cola. Saltarse la capacidad convierte el reparto en un reparto formal
—el caso figura asignado, nadie lo mira y el SLA corre igual—, que es peor que
dejarlo en cola, porque en cola al menos se ve.

La estrategia **ponderada reparte por hueco libre** y no por carga absoluta: con
carga absoluta, quien tiene capacidad 20 y lleva 5 casos parece más ocupado que
quien tiene capacidad 5 y lleva 4, y el reparto acaba saturando justo al que menos
cabe.

La **cola no es redundante** con la asignación automática: es el sitio donde cae
lo que no se ha podido asignar. Sin ella, un caso que ninguna regla sabe repartir
se queda sin dueño y sin lista, que es el único estado del que nadie se entera.
Se ordena por **lo que vence antes**, no por prioridad: la pregunta de quien coge
de una cola es «qué se me va a incumplir primero», y por prioridad un caso medio a
punto de vencer queda debajo de uno crítico con dos días. Los casos **sin SLA se
marcan**: si no, quedan al final y parecen los menos urgentes cuando son los que
nadie ha medido.

Al coger de la cola **se comprueba que siga libre**: dos agentes mirando la misma
cola pulsan a la vez, y sin eso el segundo se queda con el caso del primero sin
que ninguno lo sepa.

Y toda asignación deja escrito **por qué**, con las reglas descartadas dentro. Se
distingue «la regla no encaja» de «encajaba pero no había nadie con hueco»: son
dos problemas distintos y confundirlos lleva a reescribir una regla que estaba
bien.

### Escalado (`CRM-04.01.01.07`)

Se decide por **lo que queda, no por lo que ha pasado**: escalar cuando el SLA ya
se ha incumplido llega tarde por definición. El disparador normal es el porcentaje
consumido; escalar al incumplir es una opción aparte, y sirve para que alguien con
autoridad hable con el cliente antes de que llame él, no para llegar a tiempo.

Los disparadores van **declarados por separado** —porcentaje, severidad, cliente
VIP, incumplimiento— y no como una condición genérica, porque son los cuatro que
se usan de verdad y tenerlos explícitos es lo que permite explicarle al cliente
por qué se escaló su caso.

Un caso **no se escala dos veces por la misma regla**: si se escalara en cada
pasada, el responsable recibiría el mismo aviso cada cinco minutos y dejaría de
leerlos, que es la forma habitual de que un escalado deje de servir. Y cambiar de
cola **suelta al dueño**: si no, el caso figura en la cola nueva y sigue asignado
al de antes, y los dos equipos creen que lo lleva el otro.

### Derivación a otro nivel (`CRM-04.01.01.08`)

El motivo es obligatorio. Una derivación sin motivo obliga a quien la recibe a
leerse el caso entero para averiguar qué se espera de él, y eso es lo que hace que
las derivaciones reboten.

**El caso sigue siendo del cliente.** Derivar no crea un caso nuevo ni reinicia el
reloj: el cliente no tiene por qué esperar otra vez desde cero porque nosotros
hayamos movido su problema de mesa. Lo interno se marca para que no se le enseñe
al cliente, no para que cuente distinto.

### Derechos de servicio (`CRM-04.01.02.01`, `CRM-04.01.02.06`)

Gana el **más específico**: contrato sobre producto, producto sobre cuenta y
cuenta sobre plan. Al revés, un cliente con un contrato de soporte negociado
aparte recibiría lo que le da su plan comercial — que es justo lo que pagó por
mejorar.

**Sin límite no es cero.** Cero significa «no tienes derecho a ninguno» y nulo «no
se cuentan». Se devuelven **las dos bolsas** —casos y horas— aunque solo una esté
limitada: enseñar solo la limitada hace que quien mira no sepa si la otra no se
cuenta o es que nadie ha gastado. Y se avisa de la **caducidad** además del saldo:
un derecho con 200 horas libres que vence el viernes es tan inservible como uno
agotado, y en las hojas de cálculo eso se descubre siempre tarde.

El consumo **se anota siempre, aunque esté agotado**. Negarse a imputar haría que
el trabajo ya hecho no se registrara, que es la peor combinación: se ha gastado y
no consta. Qué pasa al agotar lo **decide el contrato** —avisar, bloquear o
facturar el exceso—, porque las tres son legítimas y elegir por el cliente
significaría cortarle el soporte a quien pagaba por el exceso.

Y es **una fila por apunte, no un contador**: con un contador, un cliente que
discute la factura no puede ver *qué* consumió, y la única respuesta posible es
«el sistema dice que 40 horas».

### Satisfacción (`CRM-04.01.01.12`)

Se guarda **la invitación y no solo la respuesta**. Guardando solo las respuestas,
el CSAT lo calculan los que contestan —los muy contentos y los muy enfadados—: sin
saber a cuántos se preguntó, el número no significa nada y siempre sale bien o
siempre sale mal. Por eso la **tasa de respuesta va junto al número**, no aparte:
un CSAT de 4,8 sobre el 3 % de los clientes no es un CSAT de 4,8, y enseñarlos
separados hace que el primero se cite y el segundo no.

La encuesta **no se manda dos veces**: recibir la misma cada vez que alguien toca
el caso es la forma más rápida de que el cliente la marque como correo no deseado,
y entonces se pierden todas las siguientes. El token se devuelve una vez y se
guarda hasheado, para que quien lea la tabla no pueda contestar por el cliente. Y
la respuesta marca al **detractor** en el evento: un NPS de 2 avisado tres semanas
después, en el informe mensual, ya no sirve para recuperar a ese cliente.

### Cumplimiento por cliente y créditos (`CRM-04.01.02.07`, `CRM-04.01.02.08`)

El total global esconde lo único accionable: un 94 % de cumplimiento puede ser
«todo va bien» o «va bien con todos menos con el cliente grande». Solo el desglose
distingue esas dos situaciones, y son opuestas. Se ordena por **el peor primero**:
la lista existe para actuar, y ordenarla alfabéticamente obliga a buscar el
problema en vez de enseñarlo.

La escala de penalización es **dato** —tramos de cumplimiento y crédito—, porque
cada contrato tiene la suya y escribirla en el código haría que un cliente con una
escala distinta fuera una versión del producto.

El crédito **se propone, no se aplica**. Descontar dinero de una factura
automáticamente por un incumplimiento que puede tener explicación —una parada
acordada, un dato que faltaba del cliente— convertiría cada incidencia en una
reclamación. Lo que sí hace el sistema es no dejar que se olvide. Y un crédito ya
decidido **no se recalcula**: cambiaría un importe que el cliente ya ha visto en su
factura.

El motivo de la decisión es obligatorio **en los dos sentidos**. Rechazar sin
explicación deja al comercial que atiende a ese cliente sin nada que decirle, y
aprobar sin explicación hace imposible saber después si fue una decisión o un
descuido.

## Omnicanal: correo, formulario, chat, mensajería y API (`CRM-04.02.01`, `CRM-04.02.02`, `CRM-04.03.02.03`)

Reutiliza el patrón de captura de leads: **un canal declarado con su clave, su
mapeo y su tope**, no un endpoint por integración. El formulario de la web manda
`nombre_completo`, el chat manda `visitor_name` y WhatsApp manda `profile.name`;
con un endpoint por cada uno, cada cliente nuevo es código nuevo. Con un mapa
declarado, es una fila.

Por eso **WhatsApp, Messenger y Telegram entran por el mismo canal declarativo
que el formulario** (`CRM-04.02.01.04`), igual que el canal de API para empotrar
soporte en el producto del cliente (`CRM-04.02.01.07`). Lo que cambia entre ellos
—el nombre de los campos, cómo viene el remitente— es configuración.

Los **valores fijos van en el canal y no en la petición**: si vinieran en la
petición, quien escribe podría abrir todos sus casos como críticos.

### La conversación es del cliente, no del canal (`CRM-04.02.02.01`)

Quien escribe por correo el lunes, llama el martes y abre un chat el miércoles
está teniendo **una** conversación. Tres hilos separados hacen que el agente
pregunte tres veces lo mismo, que es lo que más enfada de un servicio de atención
— y lo que el cliente resume como «no os enteráis de nada».

Todo mensaje entra por **una sola tabla**, con su canal, su dirección y su
identificador externo. Con una tabla por canal, «la conversación de este cliente»
sería una unión de cinco consultas que nadie mantiene al día, y la mitad de las
funciones acabarían soportando solo dos canales.

El historial va **ordenado por tiempo y no agrupado por canal**: agrupar
reproduce exactamente el problema que esto viene a resolver. Incluye las notas
internas porque **es la vista del agente** —son justo lo que le ahorra releerse el
caso—, y quien lo pinte en un portal de cliente tiene que pedirlas fuera
explícitamente. Ese parámetro no se deduce del permiso a propósito: deducirlo
pondría una nota interna delante del cliente el día que alguien reutilizara la
función desde un sitio nuevo.

### Email-to-case: el hilo y el anti-bucle (`CRM-04.02.01.01`)

El bucle clásico: nuestra respuesta automática dispara el «estoy de vacaciones»
del cliente, que abre un caso, que dispara nuestra respuesta automática, y así
toda la noche. Se corta mirando las cabeceras estándar —`Auto-Submitted`,
`Precedence`, `X-Auto-Response-Suppress`, `List-Id`— y comprobando que el
remitente no sea **nuestra propia dirección**, que es el buzón contestándose a sí
mismo.

El **anti-bucle va antes del tope**: un bucle de respuestas automáticas agota el
tope en minutos y dejaría fuera a los clientes de verdad.

El hilo sale de `In-Reply-To` y, si falta, de la **última** referencia de
`References` — la más cercana. Coger la primera colgaría toda la conversación del
mensaje original y perdería las ramas.

Y un reintento de la pasarela **no abre un caso duplicado**: el identificador
externo lo hace idempotente. Igual de importante, se abre **un caso por
conversación y no uno por mensaje**: si no, seis correos serían seis casos y el
cliente recibiría seis respuestas distintas de seis personas.

### Formulario, portal y chat: las tres protecciones (`CRM-04.02.01.02`, `CRM-04.02.01.03`)

El **chat en vivo** entra por el mismo canal declarado que el formulario, y por
eso comparte las tres protecciones. Son las mismas que en la captura de leads y
por los mismos motivos. **Clave por
canal** —el endpoint es público, tiene que serlo, pero no anónimo—. **Trampa**,
que descarta con un 200 porque devolver un error le dice al robot qué cambiar
para la próxima. Y **tope por canal y ventana**, porque la clave viaja en el HTML
de una página pública y se filtra siempre.

Una clave equivocada y un canal inexistente dan **el mismo error**: distinguirlos
convertiría el endpoint en un comprobador de qué canales tiene cada tenant. Y al
crear un canal público sin trampa se avisa: se admite —hay formularios detrás de
autenticación donde sobra— pero uno público sin ella se llena de basura en una
tarde.

### Transferir de canal (`CRM-04.02.02.02`)

Cambiar de canal **no abre una conversación nueva**. Si la abriera, pasar de chat
a correo haría perder todo lo hablado y el cliente tendría que explicarse otra vez
— que es exactamente lo que se siente como «me habéis pasado con otro y no sabe
nada». El canal actual cambia; el historial de canales vive en los mensajes, así
que una transferencia no borra por dónde empezó, que es lo que el cliente
recuerda.

### Primera respuesta y notas internas

Una respuesta **no interna** marca la primera respuesta del caso. El indicador
tiene que medir cuándo contestó una persona al cliente, y una nota interna no es
contestar: si contaran, el tiempo de primera respuesta saldría siempre magnífico
y no mediría nada.

### Macros que escriben y hacen (`CRM-04.02.02.04`)

Una macro puede contestar, cambiar el estado, poner una categoría y cerrar, todo
de una vez. Que sea **una sola acción** es el punto: partida en cuatro clics, la
mitad de las veces se queda a medias y el caso acaba contestado pero sin
clasificar.

Si quedan **variables sin resolver no se manda**, salvo que se fuerce. Es la
diferencia entre una macro que ahorra tiempo y una que manda «Hola
{contacto.nombre}» a un cliente — el error más visible y más barato de evitar que
hay en un servicio de atención.

Y una acción que no se puede aplicar **no se ignora en silencio**: ignorarla haría
que la macro pareciera funcionar y el caso quedara a medias sin que nadie lo
notara.

### Escalar del bot a una persona (`CRM-04.03.02.03`)

Lo que se traspasa es **el contexto completo**, no un aviso. Escalar diciendo solo
«el cliente quiere hablar con alguien» obliga a la persona a leerse la
conversación entera mientras el cliente espera, y eso hace que el cliente repita
todo lo que acaba de contarle al bot — la peor experiencia posible, porque acaba
de invertir cinco minutos en ello.

El contexto va **en la respuesta** y no solo en un evento: quien recoge la
conversación la abre ahí mismo y tiene que verlo sin buscar. El motivo es
obligatorio.

### Consola de agente embebible (`CRM-04.02.02.08`)

Todo lo que necesita una consola —presencia, capacidad, mis casos ordenados por
vencimiento, mis conversaciones y las macros— **en una sola llamada**. Una consola
que abre seis peticiones para pintar una pantalla tarda lo que tarde la más
lenta, y el agente lo ve como un producto lento aunque cinco vayan rápido.

Devuelve **datos y no pantallas**: es lo que permite empotrarla en el front
oficial, en el portal del cliente o en el producto del propio cliente sin
reimplementar nada. Las macros van ordenadas **por uso**: la que se usa cuarenta
veces al día tiene que estar la primera, y alfabéticamente obliga a buscarla cada
vez.

## Conocimiento y portal de cliente (`CRM-04.03.01`, `CRM-04.03.02`, `CRM-00.05.01.10`)

### Por qué fracasa una base de conocimiento (`CRM-04.03.01.01`)

Casi nunca por falta de artículos: es porque **nadie sabe cuáles siguen siendo
verdad**. A los dos años hay ochocientos, la mitad describe una versión que ya no
existe, y como nadie se atreve a borrar nada, quien busca encuentra tres
respuestas contradictorias y deja de buscar.

De ahí que un artículo tenga **versiones y estado**, no solo texto. Cada cambio
es una versión nueva: editar sobre lo publicado hace que un texto a medias esté
en el portal del cliente mientras alguien lo escribe, y deja sin forma de volver a
lo anterior. Y mientras se revisa la nueva, **el cliente sigue viendo la versión
buena**.

Al publicar hacia el cliente hay dos comprobaciones que no son formalismo:

- **Aprobación de alguien distinto del autor.** Quien escribe un artículo no es
  quien mejor detecta que lleva dentro el nombre de un cliente.
- **Fecha de revisión obligatoria.** Sin ella nadie vuelve a mirarlo, y es el que
  sigue apareciendo tres años después describiendo una versión que ya no existe.

Para lo interno no se exigen: exigirlas ahí haría que nadie documentara nada, que
es peor.

Retirar **no borra**. Borrar rompe los enlaces que alguien pegó en un correo hace
dos años, y quien los sigue recibe un «no existe» que parece un error del sistema.
Marcado como obsoleto se sigue pudiendo abrir con un aviso, y apuntando al que lo
sustituye — que es lo que la persona buscaba de verdad.

### La audiencia se declara y se filtra en el servidor (`CRM-04.03.01.02`)

Un artículo nace **en borrador y con audiencia interna**, y las dos cosas son
deliberadas: el fallo caro —publicar hacia fuera un procedimiento interno con
nombres de clientes dentro— ocurre siempre por omisión, nunca por decisión.

El filtro por audiencia se aplica **dentro de la función de búsqueda**, no por un
parámetro de quien llama: si dependiera del llamante, bastaría una ruta nueva que
se olvidara de pasarlo para que el portal público sirviera los procedimientos
internos.

Un artículo fuera de la audiencia devuelve **404 y no 403**: un 403 confirma que
existe, y con eso se puede recorrer el catálogo interno preguntando por
identificadores.

### Traducciones que dicen si están al día (`CRM-04.03.01.03`)

Cada traducción se ata a su original y guarda **contra qué versión se tradujo**.
Una traducción que se quedó en la versión 2 mientras el original va por la 5 es
peor que no tenerla, porque el cliente que la lee cree que está leyendo lo
vigente. «Desincronizada» se dice explícitamente en vez de dejar que se note: una
traducción vieja no falla, simplemente miente.

### Conocimiento desde el caso (`CRM-04.03.01.05`)

El momento importa: se escribe **cuando se resuelve**, con el problema fresco y
por quien lo resolvió. Pedirlo después, en una sesión dedicada, es como no
pedirlo — el conocimiento se pierde entre el caso cerrado y la reunión del
viernes. Por eso no se puede documentar un caso sin resolver: el artículo saldría
de una solución que aún no se sabe si funciona.

Nace **en borrador e interno** aunque venga de un caso resuelto: el texto de una
resolución lleva casi siempre el nombre del cliente, su configuración y a veces
sus credenciales. Publicarlo directo hacia fuera sería la fuga más tonta posible.

Y se registra **qué artículo resolvió qué caso**: es la métrica que de verdad dice
si sirve. Un artículo muy valorado que nadie usa en un caso es un artículo bonito.

### Medir qué sirve y qué estorba (`CRM-04.03.01.06`)

Un voto **por votante**, no uno por pulsación: sin eso el mismo visitante puede
votar cien veces y la métrica deja de significar nada — y el primero que lo
descubra decidirá qué artículos parecen buenos. Se guarda el comentario, que es lo
único que dice **por qué** no sirve; el pulgar abajo solo dice que no.

Tres listas, para tres decisiones distintas:

- **Dañinos** — muchas visitas y pulgar abajo. Es **peor que no tenerlos**: el
  cliente pierde el tiempo y *además* se queda sin llamar.
- **Huérfanos** — publicados y sin visitas. O no se encuentran o no hacían falta;
  en los dos casos ocupan sitio en los resultados de búsqueda.
- **Caducados** — pasada su fecha de revisión.

La deflexión se da como **aproximada** a propósito: no se puede distinguir a quien
leyó y le sirvió de quien leyó y se rindió, y presentarlo como exacto sería
inventarse un número que después alguien cita en una reunión.

Un artículo caducado **se marca en la búsqueda** en vez de esconderse: ocultarlo
dejaría al cliente sin respuesta, y enseñarlo sin avisar le daría una que puede
estar vieja.

### La misma API para portales, chatbots y agentes (`CRM-04.03.01.07`)

No hay una API de conocimiento por consumidor: es una, y se le pasa la audiencia
que le corresponde. Un chatbot público recibe lo público; el del portal de
partners, lo de partners. Con una API por consumidor, la tercera se olvidaría del
filtro.

### El portal de cliente cambia todas las reglas (`CRM-04.03.02.01`)

**La identidad del cliente no es la del empleado** (`CRM-04.03.02.05`,
`CRM-00.05.01.10`). Un contacto no tiene roles del CRM, no cuenta para licencias y
su ciclo de vida lo manda la relación comercial, no el directorio corporativo.
Reutilizar la tabla de usuarios parece que ahorra trabajo y lo que hace es dejar
abierta la puerta a que un contacto acabe con permisos de empleado porque alguien
le asignó un rol por comodidad.

Se entra por **enlace de un solo uso**, que evita gestionar contraseñas de gente
que entra tres veces al año y las olvida siempre. El token se guarda hasheado y
caduca pronto: un enlace de acceso viaja por correo, y el correo se reenvía — sin
caducidad, el que alguien reenvió hace seis meses sigue abriendo la cuenta de su
empresa. Pedir enlace para un correo desconocido **responde igual** que para uno
conocido: distinguirlos convertiría el portal en un comprobador de qué correos son
clientes nuestros, que es exactamente la lista que quiere un competidor.

Revocar el acceso **invalida los enlaces vivos en el acto**: si no, alguien a quien
acaban de retirar el acceso sigue entrando con el correo que recibió esta mañana,
y en la lista figura como revocado.

**Tres niveles y no dos**, porque el caso real es exactamente ese: el técnico que
solo ve lo suyo, el responsable que ve lo de su empresa y el que además da de alta
a sus compañeros sin llamarnos. El acceso nace en el más bajo: eso impide que
quien abrió una incidencia acabe viendo las facturas de su empresa porque alguien
creó el acceso deprisa.

**Y el portal enseña las secciones que el acceso concede, todas.** Hasta el
27-10-2026 enseñaba dos —pedir algo y hablar con quien atiende— mientras la API
servía ocho: lo que la empresa tiene instalado, sus contratos, sus pedidos, los
artículos que ese cliente puede leer, los hilos de la comunidad y quién más de
su empresa tiene acceso. Estaban servidas, filtradas por nivel y probadas, y no
había forma de verlas. Ahora el portal pinta exactamente lo que el servidor
declara en `secciones` —que lo declara justo para eso— y **no pide lo que no
concede**: una llamada que va a dar 403 no comprueba nada, sólo ensucia el
registro. Una sección que el servidor conceda y el portal no sepa pintar no se
inventa: no se enseña, porque un recuadro con su rótulo y nada dentro se lee
como «no tenéis nada». Y lo que no se puede leer se dice, en vez de salir vacío:
callarlo deja al cliente creyendo que no tiene contratos cuando lo que pasa es
que su acceso está mal dado.

**El filtro va en el servidor y por el nivel del acceso.** Filtrar en el cliente
funciona hasta que alguien mira la respuesta de la API, y entonces el portal deja
de ser un portal para ser una copia del CRM con un filtro de pantalla. Un nivel de
cuenta **sin cuenta asignada no ve nada**: enseñar todo «porque tiene nivel de
cuenta» sería el peor fallo posible aquí. Y declarar secciones concretas **se
interseca** con las del nivel en vez de sustituirlas, porque si mandaran las
declaradas, declarar una sección sería una forma de saltarse el nivel.

Al abrir un caso desde el portal, el contacto y la cuenta los pone **el acceso**,
no la petición: aceptarlos de quien llama permitiría abrir casos en nombre de otra
empresa, que es la fuga más fácil de un portal.

La portada devuelve **datos y no pantallas**, lo que permite que el cliente monte
su propio portal con su marca sin que nosotros hagamos uno por cliente. Y dice qué
secciones puede abrir, para que no pinte botones que después dan 403: un botón que
falla al pulsarlo es peor que uno que no está.

### Comunidad (`CRM-04.03.02.04`)

Un hilo nace **en moderación**. Un foro de soporte sin moderación previa acaba con
un cliente publicando su clave de licencia, la configuración de su red o el nombre
de su proveedor — y eso, una vez público, ya no se retira del todo. Lo que está en
moderación **no se sirve** salvo que se pida explícitamente.

La respuesta del fabricante **se marca**. En un foro de soporte, la diferencia
entre «lo dice el fabricante» y «lo dice otro cliente» es toda, y sin marcarla el
cliente aplica el consejo de cualquiera creyendo que es oficial.

La **respuesta aceptada** es lo que separa un foro útil de un archivo de
conversaciones: sin ella, quien llega el mes que viene tiene que leerse los treinta
mensajes para saber cuál funcionó — y la mitad de las veces se rinde y abre un
caso.

Rechazar un hilo exige motivo: el cliente que lo escribió tiene derecho a saber por
qué no se publica. Y un hilo **solo se convierte en artículo si tiene respuesta
aceptada**: convertir uno sin resolver crea un artículo que describe un problema y
no su solución, que es lo peor que puede haber en una base de conocimiento porque
parece una respuesta y no lo es.

## Segmentos y puntuación de leads (`CRM-02.01.01`, `CRM-02.01.02`)

Con este bloque nace el servicio `marketing`.

### La proyección: por qué marketing tiene su propia copia

`marketing` no puede leer el esquema de `party` ni el de `sales`, y las otras dos
salidas eran peores: pedirle a `party` cien mil contactos por HTTP cada vez que
alguien calcula el tamaño de un segmento, o saltarse la regla. Así que existe
`PerfilMarketing`, una proyección local que se rellena **por evento** — el mismo
patrón que los ajustes en caliente, los tipos de cambio, los calendarios y el
esquema del tenant.

Se replica **lo que sirve para segmentar**, no la ficha entera: copiar la ficha
completa convertiría esta tabla en una segunda base de clientes, con su propia
deriva y su propio problema de borrado.

El precio se dice en voz alta: **un segmento se calcula sobre lo replicado**, así
que un contacto creado hace dos segundos puede no estar todavía. Para marketing
es aceptable —una campaña no se lanza en el mismo segundo en que entra un lead— y
a cambio el cálculo no depende de que otro servicio esté en pie. Por eso se
guarda y se enseña cuándo se sincronizó.

Y lo que el evento no trae, **aquí no existe**: un atributo que el productor no
publica sale nulo, y el segmento que dependa de él no encontrará a nadie. Es
preferible a rellenarlo con un valor por defecto, que daría un segmento que parece
funcionar y selecciona mal.

Los perfiles se **fusionan, no se reemplazan**: cada evento trae lo suyo —el de
alta trae el correo, el de asignación trae el dueño— y reemplazar dejaría el
perfil con solo lo del último. Un borrado en origen **marca de baja y no borra**:
un segmento congelado tiene que poder seguir explicando a quién incluía.

### Un segmento es una definición, no una lista (`CRM-02.01.01.01`, `CRM-02.01.01.03`)

Guardar la lista parece más rápido y es lo que hace que a la semana esté
desfasada sin que nadie lo sepa. La lista se calcula cuando se pide.

Hacen falta **los dos tipos y por motivos opuestos**: el dinámico, para que
«clientes activos» signifique lo que significa hoy; el estático, para que «a quién
se le mandó la campaña de marzo» siga siendo cierto en junio. Se congela **antes
de un envío**, no después.

La definición se **valida y se traduce a SQL al crear**: descubrir que un segmento
no se puede calcular el día del envío es descubrirlo tarde. Y si alguna condición
no se puede traducir, **se lanza en vez de omitirla**: omitirla daría un segmento
más grande que el pedido, y el error se descubriría al recibir la queja de alguien
a quien no había que escribir. Un segmento que casi acierta no se detecta
mirándolo.

### Condiciones anidadas y tiempo relativo (`CRM-02.01.01.02`)

«(sector = construcción o sector = obra pública) y no ha comprado en 12 meses» es
la consulta normal en marketing. Con una lista plana solo se puede expresar «todo
y» o «todo o», y entonces el segmento se parte en tres que nadie mantiene iguales.

Se reutiliza la gramática de condiciones de las políticas de acceso y del
enrutamiento de leads: los mismos operadores. No es por ahorrar código — es para
que quien aprende a escribir una condición la sepa escribir en todos los sitios.

El `no` **niega exactamente una condición**: «no de varias cosas» es ambiguo —
¿ninguna, o no todas?— y obligar a envolverlas primero deja escrito cuál de las
dos se quería. Y hay **tope de anidamiento**, porque una definición sin fin haría
que la evaluación no terminara y el síntoma sería una petición que no responde.

Los operadores temporales son **relativos y se evalúan al consultar**. Guardada la
fecha calculada, «leads recientes» seguiría devolviendo los mismos de hace medio
año.

La **misma definición** decide sobre uno concreto —«¿este lead entra en el
recorrido?»— y sobre todos —el listado—. Dos gramáticas para lo mismo es cómo se
acaba con un recorrido que admite a alguien que el segmento no lista.

### El tamaño y la API de audiencias (`CRM-02.01.01.04`, `CRM-02.01.01.05`)

Un número sin fecha se lee como actual aunque sea de hace tres semanas, y sobre
eso se decide un envío. Se devuelven **el bruto, los alcanzables y cuántos caen
por supresión**: enseñar solo el total haría que alguien planificara un envío a
diez mil y saliera a siete mil sin saber por qué faltan tres mil.

Quien no tiene dirección **no cuenta como alcanzable**: contarlo infla la
audiencia y después el envío sale más pequeño de lo prometido, sin explicación.

La lista de miembros es además la **API con la que se activan audiencias en
canales externos** (`CRM-02.01.01.05`): una plataforma publicitaria pide el
segmento y recibe los identificadores, ya restadas las exclusiones y las
supresiones. Que el filtrado ocurra aquí y no en el consumidor es lo que impide
que una integración nueva se olvide de las supresiones y acabe anunciándole a
quien pidió no ser contactado.

### Las supresiones se aplican siempre (`CRM-02.01.01.06`)

Es una tabla aparte y se aplica **por encima de cualquier segmento**. Si fuera una
condición más, bastaría con que alguien montara un segmento sin acordarse de
ponerla para escribirle a quien pidió que no se le escribiera — y eso, además de
una multa, es la clase de error que el cliente cuenta a los demás.

Se suprime **por dirección y no por identificador**: la misma persona puede estar
en tres fichas duplicadas, y suprimir una sola dejaría que las otras dos le
siguieran escribiendo.

Un segmento **congelado también respeta las supresiones**: la baja pudo llegar
después de congelarlo, que es exactamente el caso que la supresión existe para
impedir.

El **ámbito** permite la baja selectiva —«no quiero la newsletter pero sí los
avisos de servicio»—, que es lo que evita que alguien se dé de baja de todo por no
poder darse de baja de una cosa. Una **queja por spam es permanente**: deshacerla
con un clic convierte la protección en una casilla. Y levantar cualquier otra
exige motivo escrito, porque es volver a escribir a alguien que había dicho que no.

### Solapamiento (`CRM-02.01.01.07`)

La pregunta real no es de estadística: es «si lanzo las dos campañas esta semana,
¿a cuánta gente le van a llegar las dos?». Por eso se devuelve el número **y el
porcentaje sobre cada uno**: mil personas comunes es mucho si uno de los segmentos
tiene mil doscientos y poco si tiene cien mil.

### Puntuación: dos ejes y no uno (`CRM-02.01.02.01`, `CRM-02.01.02.03`)

El error clásico del *lead scoring* es tener **un solo número**. Un estudiante que
abre diez correos suma lo mismo que un director de compras que abrió uno, ventas
recibe los dos como «lead caliente», y a la tercera vez que le pasan uno que no
compra deja de fiarse de la lista. A partir de ahí el scoring está puesto y no
sirve para nada — peor que no tenerlo, porque nadie lo revisa.

- **Encaje**: ¿es el cliente que buscamos? Sector, tamaño, país, cargo.
- **Interés**: ¿nos está haciendo caso? Visitas, descargas, respuestas.

El **grado** (A, B, C) sale del encaje y es independiente del interés. Los tramos
se ordenan de mayor a menor y gana el primero que alcanza: con el orden al revés,
un encaje de 95 caería en el tramo de 0 y todo el mundo sería «C».

### Decaimiento (`CRM-02.01.02.04`)

Solo decae **el interés**. El encaje no: que alguien sea director de compras de
una empresa de quinientas personas no deja de ser cierto porque lleve dos meses
sin abrir un correo.

Y el interés **nunca baja del mínimo declarado**: si bajara a cero, un lead que
fue muy activo hace un año quedaría indistinguible de uno que no ha hecho nada
nunca, y esos dos merecen tratos distintos.

El decaimiento **se enseña aparte** en la explicación: sin él, quien mira no
entiende por qué un lead que hizo muchas cosas tiene poco interés, y concluye que
el scoring está roto.

### Umbrales y traspaso a ventas (`CRM-02.01.02.05`)

Para pasar a MQL se exigen **los dos ejes**. Con uno solo, o pasan estudiantes muy
activos o directores que no han mostrado ningún interés. Un umbral sin declarar se
trata como «no aplica» y no como cero — cero dejaría pasar a todo el mundo.

El cambio de calificación se emite **solo cuando cambia**: emitirlo en cada
recálculo llenaría la cola de eventos idénticos y haría que la regla «avisa a
ventas cuando pase a MQL» disparara cada hora sobre el mismo lead. Y el evento
lleva **los motivos dentro**: «lead caliente» sin el porqué obliga al comercial a
abrir la ficha antes de llamar, y la mitad de las veces no la abre.

El modelo se **versiona**, como los SLA y el esquema del tenant: editar en
caliente hace que las puntuaciones de ayer y las de hoy no sean comparables sin
que nadie lo sepa — el lead que ayer tenía 80 y hoy tiene 40 no ha hecho nada
distinto. Publicar una versión nueva **no repuntúa a nadie por sí solo**, así que
hay una lista de los que se han quedado atrás: dejar la mitad de la base con el
modelo viejo hace que dos leads iguales salgan distintos, y entonces la lista deja
de servir para ordenar por prioridad, que es lo único para lo que se usa.

## Campañas, atribución y presión de contacto (`CRM-02.02.01`, `CRM-02.02.02.06`, `CRM-02.03.01.04`)

Marketing se mide de tres maneras y las tres tienen que cuadrar entre sí: **cuánto
costó**, **qué pasó** y **cuánto trajo**. Cuando viven en tres sitios distintos —y
viven, casi siempre en tres hojas de cálculo— la conversación de final de
trimestre empieza con tres números que no coinciden y acaba sin decidir nada.

### Los miembros de una campaña se pueden listar (`CRM-02.02.01.04`)

`GET /campanas/{id}/miembros`, con filtro por estado. Devuelve quién está, en qué
estado y **de dónde salió**: sin la fuente de alta no se distingue a quien se
importó de quien entró por un formulario, y eso es lo que decide si se le puede
escribir.

Se filtra por estado porque es lo que se hace con esto: la lista entera de una
campaña de veinte mil no la mira nadie; los que abrieron y no respondieron, sí.

> **Faltaba, y se vio el 28-09-2026 al ejercitar la familia.** Se podían añadir
> miembros y cambiarles el estado, y **no había forma de listarlos**: el embudo
> dice *cuántos* hay en cada estado y no *quiénes*. Para quien lleva la campaña,
> la diferencia entre «40 han hecho clic» y poder llamarlos es toda. Los datos
> estaban guardados y no llegaba ninguna puerta.

### La jerarquía es real, no una etiqueta (`CRM-02.02.01.01`)

Programa → campaña → táctica, y se comprueba: una táctica no puede tener debajo un
programa. Sin la comprobación, el árbol se desordena en dos semanas y el consumo
de presupuesto deja de poder subir.

El presupuesto se declara arriba y **el gasto se imputa abajo**, donde ocurre, y
sube al consultarlo — no al escribirlo. Sumarlo hacia arriba al escribir obligaría
a recalcularlo todo cada vez que alguien mueve una táctica de campaña, y el primer
fallo dejaría dos totales distintos sin forma de saber cuál es bueno.

Si lo repartido abajo **supera lo asignado arriba, se dice**: no es un fallo, es
un aviso de planificación, pero enseñarlo evita la sorpresa de octubre.

Un **evento o feria es una campaña**, no una tabla aparte (`CRM-02.02.01.07`):
tiene presupuesto, miembros y resultados, y separarlo obligaría a duplicar la
atribución y el ROI solo para él.

### El calendario: lo que se solapa no son las fechas (`CRM-02.02.01.03`)

Es **la audiencia y el canal**. Dos campañas la misma semana a públicos distintos
no molestan a nadie; dos al mismo público por el mismo canal sí, y esa es la que
hay que ver antes de programar la tercera.

Y se dice cuántas campañas en curso **no tienen fechas**: quedan fuera del
calendario, y quien lo mira creería que no hay nada más en marcha.

### Miembros y embudo (`CRM-02.02.01.04`)

Repetir el alta **no reinicia el estado**: quien ya está en «clicado» no puede
volver a «objetivo» porque alguien recargó el segmento — el embudo se quedaría a
cero cada vez que se refresca la audiencia.

El embudo **no retrocede**. Que alguien abra un correo después de haber respondido
no lo devuelve a «abierto»: el embudo mide hasta dónde llegó cada uno, y permitir
el retroceso haría que las tasas de conversión bajaran solas con el tiempo sin que
nadie hubiera hecho nada peor.

Y se cuenta **acumulado**, no por estado actual: quien respondió también abrió, y
contar solo el actual daría «5 abiertos y 40 respondidos», que no se sostiene y
hace que nadie se crea el resto del informe.

En eventos, **inscribirse y aparecer no es lo mismo**, y la diferencia es el dato
que decide si el evento salió bien. Se dice además cuántos **no se marcaron**: sin
eso, una asistencia baja podría ser que no vino nadie o que nadie pasó lista, y
son dos problemas opuestos.

### La atribución es un modelo, no una verdad (`CRM-02.02.01.06`)

First touch y last touch dan **respuestas opuestas sobre los mismos datos**, y las
dos son defendibles: el primero premia a quien trajo al desconocido y el segundo a
quien cerró. Por eso se calculan varios modelos sobre los mismos toques y se
enseñan juntos — elegir uno y presentarlo como «el ROI» es lo que hace que nadie
se crea los informes de marketing.

Están los seis habituales: primer toque, último toque, lineal, en U, en W y por
decaimiento. El decaimiento lleva **semivida configurable**: sin ella no hay
decaimiento, hay una constante disfrazada.

La **ventana** existe porque un toque de hace tres años no trajo esta venta. Sin
ella, la primera campaña que hizo la empresa se lleva el crédito de todo lo que
pase después — el resultado favorito de quien la lanzó y el motivo por el que
nadie se fía del informe.

Los toques **sin campaña no se descartan**: se agrupan como «(sin campaña)».
Descartarlos repartiría todo el crédito entre las campañas y haría que el tráfico
directo y el boca a boca parecieran no existir. Y **sin toques no se atribuye a
nadie**: repartirlo «a la campaña más reciente» inventaría un origen que no
consta.

Los toques se replican desde `sales` por la misma razón que el perfil: `marketing`
no puede leer su esquema, y la atribución recorre todos los toques de un lead —
hacerlo por HTTP, por cada oportunidad de un informe trimestral, serían decenas de
miles de llamadas.

### ROI que dice cuándo no sabe (`CRM-02.02.01.05`, `CRM-02.02.01.02`)

Los ingresos atribuidos llegan **de fuera**: los calcula quien conoce las
oportunidades, que es `sales`. Se piden como parámetro en vez de inventarse un
número, y si no llegan **se dice que el ROI no es medible** en vez de devolver
cero — que se leería como «no trajo nada».

El plan se compara con lo real por objetivo declarado, que es la otra mitad de la
pregunta: un coste por lead bueno con la mitad de los leads previstos no es una
campaña que fue bien.

### Presión de contacto (`CRM-02.02.02.06`)

Se **cuenta aunque las reglas estén apagadas**. Saber a cuánta gente le hemos
escrito cuatro veces esta semana es la diferencia entre una campaña y una
denuncia, y ese dato solo existe si se cuenta desde el principio: cuando alguien
pregunta, ya es tarde para empezar a contar.

Hay **dos límites y no uno**: un tope semanal no impide mandar los tres el mismo
martes por la mañana, que es exactamente lo que el destinatario percibe como
acoso.

Las comunicaciones **transaccionales no cuentan**: un aviso de servicio, una
factura o la respuesta a un caso no son marketing, y contarlas haría que un
cliente con muchas incidencias dejara de recibir la información que ha pedido.

Y la comprobación **devuelve la decisión en vez de lanzar**: hay envíos legítimos
que justifican saltarse el tope —el aviso de fin de contrato— y esa decisión tiene
que quedar en quien envía.

### Rebotes y quejas (`CRM-02.03.01.04`)

**Un duro suprime al instante**: la dirección no existe, y seguir escribiéndole es
lo que hunde la reputación de envío del dominio — y con ella la entrega de todos
los correos, incluidos los que sí importan.

**Una queja suprime y es permanente**: alguien ha pulsado «esto es spam».

**Los blandos se acumulan.** Uno aislado es normal —el buzón estaba lleno—; varios
seguidos son una dirección muerta. Sin el histórico hay que elegir entre suprimir
al primer fallo, perdiendo contactos buenos, o no suprimir nunca y hundir la
reputación.

Las tasas se enseñan **con el umbral del sector al lado**: una tasa de queja del
0,3 % suena a poco y es el triple de lo que los proveedores toleran antes de
empezar a mandar a la carpeta de spam. Un número sin referencia no dice si hay que
hacer algo.

## Módulos verticales: caracterizar el producto para un sector (`CRM-00.04.04`)

La extensión sin código (`CRM-00.04.03`) resuelve «falta un campo». Esto resuelve
lo otro: que el producto llegue **ya caracterizado**. Un operador logístico no
necesita un campo más — necesita expediciones, trazabilidad con el transportista,
incidencias con su tipología y que su cliente vea el seguimiento sin llamar.

Un módulo es un **paquete declarativo y versionado**: objetos, campos, taxonomías,
estados, flujos, permisos, plantillas, pantallas, conectores y datos semilla. Que
el producto sea headless es lo que lo hace posible —las pantallas salen de la
superficie declarada, sin escribir front— pero no lo hace gratis.

### Lo que decide si esto funciona a los dos años (`CRM-00.04.04.04`)

**La actualización.** El cliente habrá tocado lo que el módulo trajo: habrá
renombrado una etiqueta, añadido un campo, cambiado un umbral. Una actualización
que pise esos cambios **se deja de instalar**, y entonces cada cliente se queda
congelado en su versión — que es exactamente cómo mueren los productos con
verticales.

Por eso cada elemento declara **quién lo gobierna**, y se declara por adelantado,
no se descubre en el conflicto:

- **Fijo** — lo gobierna el módulo y se actualiza. Si el cliente lo tocó, se
  avisa, y solo se pisa pidiéndolo: pisarlo en silencio es cómo se pierde la
  confianza en las actualizaciones.
- **Editable** — el cliente lo puede tocar, y desde que lo toca **es suyo**. No se
  vuelve a tocar nunca. Ese es el trato.
- **Semilla** — se crea una vez y ya está. Actualizarlo sería reescribir datos que
  el cliente lleva un año usando.

Y lo que la versión nueva **ya no trae no se borra**: se marca como huérfano y se
dice. Borrarlo con la actualización se llevaría por delante los registros que
cuelgan de él sin que nadie lo hubiera decidido.

### Espacio de nombres (`CRM-00.04.04.03`)

Todo lo que trae un módulo va **prefijado con su clave**. Sin prefijo, dos módulos
que llamen «envío» a cosas distintas se pisan: el segundo que se instale rompe al
primero sin que nadie entienda por qué, y desinstalar cualquiera de los dos se
lleva por delante lo del otro.

Las versiones se comparan **por número y no como texto**: como texto, «1.10» es
menor que «1.9» y una actualización se saltaría sin avisar.

### Instalar es una decisión (`CRM-00.04.04.02`)

**Simular es el valor por defecto.** Instalar un módulo es un cambio de modelo de
datos en producción, y el error más caro que puede cometer quien lo maneja es
pulsar el botón creyendo que todavía estaba mirando.

La simulación dice qué se crearía, qué dependencias faltan y qué avisos hay. Y las
dependencias se comprueban **todas juntas y antes**: instalar, fallar, corregir y
repetir cinco veces es exactamente la experiencia que hace que nadie quiera
instalar módulos.

### Qué rechaza y qué solo avisa (`CRM-00.04.04.01`, `CRM-00.04.04.05`)

Lo que está mal **lanza**; lo dudoso **avisa**. La diferencia importa: rechazar por
algo dudoso deja módulos correctos sin instalar, y aceptar en silencio algo dudoso
deja al cliente con un módulo que no hace lo que promete.

Una **sección desconocida se rechaza**: ignorarla instalaría un módulo a medias que
parece completo, y el cliente descubriría lo que falta el día que lo necesite. Un
módulo **sin descripción** o **sin pantallas** se instala, pero avisando — el
segundo significa que sus objetos existirán en la API y no aparecerán en el front.

Un módulo que pida una versión del núcleo que no existe se **rechaza al instalar**,
no falla a mitad.

### Desinstalar dice qué pasa con los datos (`CRM-00.04.04.09`)

Un «desinstalado correctamente» que deja doscientos mil registros huérfanos es
**peor que no poder desinstalar**: el cliente cree que se fue y los datos siguen
ahí, sin pantalla que los enseñe y sin nadie que los borre cuando toque.

Por eso la configuración se quita y **los datos se conservan salvo que se pida lo
contrario**, y se dice cuántos hay por objeto. Cuando no se pueden contar **se dice
que no se han podido contar**, no se supone que son cero. Y no se desinstala si
otro módulo depende de este.

### El catálogo y la firma (`CRM-00.04.04.08`)

El catálogo es **de la instalación, no de cada tenant**: quién puede publicar un
módulo es una decisión de quien opera la plataforma, y dejar que cada tenant
publique el suyo convertiría el catálogo en una vía para ejecutar configuración
ajena en casa de otro.

Una versión publicada **no se reescribe**: hacerlo dejaría a quien ya la instaló
con un contenido distinto del que consta. Y el catálogo dice si cada módulo está
**firmado y revisado**, porque de eso depende si se instala a ciegas: uno sin firma
puede haber sido modificado por cualquiera entre quien lo escribió y quien lo
instala.

La comprobación de integridad compara la huella instalada con la publicada. Cuando
esa versión ya no está en el catálogo **se dice que no se puede comparar**, en vez
de darlo por bueno.

### Las pantallas salen de la superficie (`CRM-00.04.04.07`)

El front oficial pinta lo que la superficie declara, así que un módulo añade
pantallas **declarándolas**. Solo se sirven las de los módulos instalados y
activos: servir las de uno desinstalado dejaría un menú con entradas que llevan a
un 404, que es peor que no tener la entrada.

### Telemetría: saber qué sobra (`CRM-00.04.04.10`)

Un módulo con quince objetos de los que se usan dos no está completo, **está
inflado** — y cada objeto que sobra es una entrada de menú que el usuario tiene
que aprender a ignorar.

Se cuenta el uso por elemento y se dice cuáles no se han tocado nunca. Y se dice
también **cuándo el dato todavía no es concluyente**: un módulo instalado ayer con
todo sin usar no está inflado, está recién puesto, y tratarlo igual llevaría a
recortar lo que aún nadie ha tenido tiempo de abrir.

### Un módulo de ejemplo completo (`CRM-00.04.04.11`)

En `docs/modulos/logistica.json` hay un módulo de operador logístico entero:
expediciones con referencia externa y transportista, taxonomía de incidencias de
envío, máquina de estados con sus transiciones, un flujo de aviso, permisos,
plantilla de correo, dos pantallas —una interna y otra para el portal del
cliente—, un conector con su mapa de estados del transportista y un SLA semilla.

Está en el repositorio y **se valida en las pruebas**: un ejemplo que no valida no
sirve de plantilla para escribir los demás.

## Seguir lo que se le encarga a un tercero (`CRM-00.04.05`)

Un operador logístico sigue envíos. Un instalador sigue instalaciones. Una
aseguradora sigue peritajes. Los tres necesitan lo mismo: una referencia externa,
un estado que cambia solo, unos hitos con fecha, unas incidencias y una prueba de
que se hizo.

**Por eso el modelo es genérico y no de paquetería.** Un objeto «envío» con bultos
y código postal deja fuera al instalador y al perito; un «encargo seguido» sirve a
los tres, y el módulo vertical le pone el vocabulario de su sector. Con un modelo
por sector, cada cliente nuevo sería una versión del producto.

### El encargo seguido (`CRM-00.04.05.01`)

Se crea con `POST /encargos`. Nace con **referencia propia** —la del proveedor
llega después, y hasta entonces el encargo tiene que poder nombrarse—, con el
plazo prometido que declare el proveedor y con su primer hito.

Cuelga de lo que lo originó (`objeto_origen`, `objeto_origen_id`) con
identificadores opacos: el pedido vive en `sales` y el caso en `service`, y
ningún servicio lee el esquema de otro.

### El mapa de estados lo declara el conector (`CRM-00.04.05.02`)

GLS dice `ENTREGADO`, otro dice `DELIVERED` y un tercero manda un número.
Traducirlo en el código significa tocar el producto por cada transportista;
declararlo significa una fila:

```json
{"ENTREGADO": "completado", "EN_REPARTO": "en_entrega", "INCIDENCIA": "incidencia"}
```

Los estados del sistema están cerrados a propósito —`creado`, `aceptado`,
`recogido`, `en_curso`, `en_entrega`, `completado`, `incidencia`, `devuelto`,
`cancelado`—: con estados libres, dos transportistas reportarían «en_ruta» y
«EN_RUTA» y ningún informe podría agruparlos.

**Un estado que no está en el mapa no se adivina.** Suponer que es «en curso»
haría que un envío devuelto siguiera contando como en camino, y nadie lo mira
hasta que el cliente pregunta. Se guarda sin aplicar y sale en
`GET /encargos/estados-sin-mapear`, que es la lista a mirar al integrar un
proveedor nuevo: cada entrada es un evento que se guardó y no hizo nada.

### La ingesta: una puerta para el webhook y para el sondeo (`CRM-00.04.05.03`)

`POST /encargos/eventos` es la misma puerta para las dos vías. Un transportista
que empuja webhooks y otro al que hay que sondear tienen que acabar en el mismo
hito, o cada informe dependería de cómo se enteró el sistema.

**Es idempotente** por el identificador del evento del proveedor: las pasarelas
reintentan, y sin esto un reintento duplicaría el hito y el cliente vería dos
veces «salió de almacén».

**Y es ordenada por encargo**: un evento anterior al estado actual se guarda pero
no se aplica. Guardarlo importa —es la prueba de lo que dijo el proveedor y
cuándo— y no aplicarlo también, porque un paquete que retrocede en la pantalla es
una llamada al servicio de atención.

Cada hito guarda **cuándo ocurrió según el proveedor** y **cuándo nos enteramos**.
La diferencia entre las dos es la latencia de la integración, y sin las dos no se
puede saber si un retraso fue del transportista o nuestro.

### Incidencias con tipología y enlace al caso (`CRM-00.04.05.04`)

El tipo sale del árbol que trae el módulo vertical (`retraso/aduana`,
`dano/embalaje`). El **responsable** —proveedor, nuestro, cliente, tercero o sin
determinar— se declara porque decide dos cosas distintas: si se le reclama al
proveedor y si cuenta en su cumplimiento. «Sin determinar» es el valor de partida
a propósito: forzar a elegir en caliente hace que se marque lo primero, y ese dato
después se usa para negociar contratos.

La incidencia **se enlaza al caso de soporte, no lo duplica**: el cliente escribe
al soporte, no a la integración, y tener dos hilos sobre el mismo problema es cómo
se le acaba contestando dos cosas distintas.

### El cliente ve su seguimiento, no el nuestro (`CRM-00.04.05.06`)

`GET /encargos/{id}/seguimiento` devuelve estado, hitos, plazo, si vamos tarde y
las incidencias abiertas. **El coste, el proveedor alternativo, la regla que lo
eligió y las notas internas no salen**, y eso lo decide el servidor: si dependiera
del front, bastaría una pantalla nueva que se olvidara de filtrar para enseñarle
al cliente lo que nos cuesta su envío.

Tampoco salen los hitos no aplicados, ni **de quién fue la culpa** de una
incidencia: esa conversación se tiene hablando, no leyendo en una pantalla que la
culpa fue suya.

Un encargo de otra cuenta da **404 y no 403**: un 403 confirma que ese encargo
existe, y con eso se puede recorrer la base preguntando por referencias.

### Varios proveedores, elegidos por regla y con alternativa (`CRM-00.04.05.07`)

Las reglas usan la **misma gramática** que el reparto de leads y la asignación de
casos: una sola en todo el producto, y un resultado que se puede explicar. Gana la
primera que encaja, y `POST /proveedores-servicio/simular` dice **cuál ganó** sin
crear nada: una elección que no se puede explicar no se puede corregir.

Cada regla lleva sus **alternativos**. Sin ellos, una caída del transportista
habitual para la operación entera y la única salida es cambiarlos a mano uno a
uno.

Si no encaja ninguna regla se usa el primer proveedor activo **y se dice**:
elegir en silencio haría que un encargo saliera por un transportista que nadie
decidió, y eso solo se descubre en la factura.

### Conciliar lo facturado con lo entregado (`CRM-00.04.05.08`)

`POST /encargos/conciliar` recibe las líneas de la factura del proveedor y
devuelve **tres listas separadas**, porque llevan a tres acciones distintas:

* lo facturado de más, que **se reclama**,
* lo facturado sin constar entregado, que **se investiga**,
* lo entregado y no facturado, que **se provisiona** — nadie quiere la sorpresa de
  una factura de hace cuatro meses.

Y una cuarta: las referencias que el proveedor factura y aquí no constan. No es un
error de cálculo: o falta un encargo o la referencia está mal, y las dos exigen
que alguien mire.

### Cumplimiento por proveedor (`CRM-00.04.05.09`)

`GET /encargos/cumplimiento` da plazo prometido contra real, incidencias por mil,
encargos mudos y coste medio. Es la tabla con la que se renegocia un contrato, y
por eso cuenta **solo lo que es suyo**: una incidencia cuya culpa fue del cliente o
nuestra no cuenta contra el proveedor. Meterlas todas en el mismo saco hace que el
número no se pueda defender en una reunión, y entonces no se usa.

Un proveedor sin encargos completados con plazo sale como **no medible**, no con
un 100 %. Recién contratado, no ha demostrado nada, y ese 100 % de cero envíos es
el número con el que se firma un contrato que después no se cumple.

### El encargo mudo: el fallo que no da error (`CRM-00.04.05.10`)

**El fallo más caro de una integración de seguimiento no es el error: es el
silencio.** Un envío del que el transportista no dice nada durante cuatro días
parece que va bien —en la pantalla pone «en tránsito»— y no va bien. Nadie lo mira
hasta que el cliente llama, y para entonces se ha perdido la semana de margen que
había para arreglarlo.

`POST /encargos/revisar-silencios` marca los que llevan demasiado callados y emite
`order.tracked.silent`. Es un evento y no un informe porque el silencio hay que
empujarlo: nadie entra a mirar una lista de encargos que parecen ir bien.

El plazo es **por proveedor**: uno que reporta cada hora y otro que reporta una vez
al día no pueden medirse con la misma vara, y usar una sola llenaría la lista de
falsos avisos hasta que nadie la mire. Un encargo terminado no se marca: un envío
entregado hace un mes no tiene por qué seguir dando noticias. Y si no hay encargos
abiertos se dice que **no es medible**, no que todo va bien: un verde vacío se lee
igual que uno ganado.

### El conector viene dentro del módulo (`CRM-00.04.04.06`)

Un módulo vertical declara sus conectores y `integration` los convierte en
proveedores. La declaración viaja **dentro del evento** `module.installed` —y de
`module.updated`, que se emite por esto— porque `integration` no puede leer el
esquema de `metadata`: si no llegara, habría que teclear el transportista otra vez
en la otra pantalla, que es justo el trabajo manual que el módulo existe para
quitar. Son declaración, no datos del tenant: un mapa de estados y un plazo caben
en un evento.

Tres reglas, y las tres están probadas:

* **Lo que el cliente cambió a mano no se pisa.** Un proveedor creado por una
  persona no se lo queda el módulo, y perder un plazo ajustado a una ruta concreta
  se nota semanas después, cuando los informes empiezan a decir que todo llega
  tarde.
* **Dos módulos que declaran el mismo transportista no se pisan**: gana el que ya
  estaba. Instalar un módulo no puede cambiar el comportamiento de otro sin que
  nadie lo pidiera.
* **Desinstalar desactiva, no borra.** Los encargos en vuelo siguen apuntando al
  proveedor, y borrar la ficha dejaría sin nombre ni mapa de estados a envíos que
  todavía están en la calle.

## Aprobaciones: quién decide y qué pasa si no decide nadie (`CRM-00.03.05`)

Una aprobación no es una tarea con un botón. Es una pregunta con cuatro partes
que se equivocan por separado: **a quién le toca**, **cuántos hacen falta**, **qué
pasa si nadie contesta** —que es lo que ocurre de verdad la mayoría de las veces—
y **qué pasa si lo aprobado cambia después**.

Todo lo que decide es dato del tenant, no código: la política de aprobaciones
cambia cada trimestre, y un `if` en el producto la convierte en una versión nueva
por cliente.

### El organigrama, replicado (`CRM-00.03.05.07`)

Quién manda sobre quién vive en `membresias`, dentro de `identity`, y el
orquestador no lee el esquema de otro servicio. Llega por el evento
`user.org.changed`, que se emite desde **las siete vías** que tocan una
membresía: alta manual, alta JIT por OIDC, alta JIT por SAML, `PUT` de SCIM,
`PATCH` de SCIM, reactivación y baja. Un organigrama que se publicara solo en el
alta sería peor que no tenerlo: las aprobaciones seguirían yendo al jefe anterior
con toda la apariencia de funcionar.

El aprobador se resuelve por cinco orígenes —`jerarquia`, `rol`, `usuario`,
`campo` y `unidad`— y **ninguno por defecto**. Tres reglas que están probadas:

* **A quien no consta, no se le asigna nada.** Si el organigrama no conoce a una
  persona, resolver falla y lo dice. Un aprobador elegido por defecto es una firma
  que alguien pone sin que le correspondiera, y eso se descubre en una auditoría.
* **Una etapa sin aprobadores no se salta**, se para. Saltarla haría que una
  cadena mal configurada aprobara sola y en silencio.
* **Quien pide no se aprueba a sí mismo** aunque la regla le señale. Es la
  separación de funciones más básica y la que más veces se cuela, porque el
  responsable de zona suele ser también el dueño de la cuenta.

Un jefe de baja **se salta y se sube un escalón más**, que es lo que haría una
persona; y un ciclo en la jerarquía da una cadena corta y rara en vez de tumbar el
proceso.

### Quórum: todos, mayoría, cualquiera, N de M (`CRM-00.03.05.06`)

Las etapas van en cadena y dentro de cada una el voto es en paralelo. Los
aprobadores **se congelan al abrir la etapa**: si se recalcularan a cada consulta,
una reorganización a mitad de una aprobación cambiaría a quién le tocaba mientras
está decidiendo.

**Cuando el quórum ya no puede salir, se cierra sin esperar al resto.** Con
«todos» y un voto en contra ya está decidido: seguir pidiendo firmas es hacer
perder el tiempo a gente con algo que no puede aprobarse, y encima retrasa el
rechazo a quien lo pidió.

Y un `n_de_m` imposible —tres de dos— **se caza al crear la solicitud**, no seis
semanas después, cuando alguien pregunta por qué aquello sigue parado.

### Delegación con vigencia (`CRM-00.03.05.08`)

La vigencia es obligatoria: una delegación sin fecha de fin es una cesión
permanente que nadie recuerda haber hecho, y en la práctica se queda. Se puede
acotar a una política, porque delegar las vacaciones no es delegar la firma de los
contratos.

Cada voto guarda **el titular y quien firmó de verdad**. Perder esa diferencia
convierte la delegación en un agujero de responsabilidad.

### Escalado que avisa antes (`CRM-00.03.05.09`)

`POST /aprobaciones/revisar-plazos` avisa a las etapas que se acercan al plazo
—por defecto, al 70 %— y escala las vencidas. **Primero se avisa y después se
escala**: un escalado que llega sin aviso previo se vive como un castigo, y la
reacción es discutirlo en vez de decidir.

Al escalar, el superior **se añade**, no sustituye. Quitar al titular le quitaría
la decisión a quien todavía puede tomarla, y borraría el rastro de a quién le
tocaba. Si no hay nadie por encima se marca igual para no reintentarlo cada
minuto, y queda escrito en el registro: una etapa vencida sin a quién escalar
necesita que alguien la mire, y callarlo la deja parada para siempre.

### Reaprobación cuando cambia lo aprobado (`CRM-00.03.05.10`)

Un descuento del 10 % aprobado que alguien sube al 30 % está aprobado por el papel
y no por la persona. Se guarda una **huella de los campos vigilados**, y cuando no
coincide la aprobación vuelve a empezar **desde la primera etapa**.

Solo de los campos vigilados, no del registro entero: si entrara todo, un cambio
en la descripción obligaría a volver a aprobar un importe que nadie ha tocado, y a
la tercera vez la gente aprueba sin mirar, que es peor que no tener reaprobación.

Los votos anteriores **no se borran**: son la prueba de que aquella versión sí se
aprobó. Cada reapertura abre una **vuelta** nueva, y los votos solo cuentan en la
suya. Sin ese número, un descuento reabierto se aprobaría solo con las firmas de
lo que ya no es — que es un fallo silencioso, no un error.

### Aprobación automática bajo umbral (`CRM-00.03.05.11`)

Se comprueba **después** de resolver los aprobadores, a propósito: así queda
escrito a quién le habría tocado firmar y por qué no hizo falta. Sin ese nombre,
«aprobación automática» es una decisión sin responsable, y la primera pregunta de
cualquier auditoría es de quién era la firma.

### Decidir desde el correo o el móvil (`CRM-00.03.05.12`)

Enlace firmado, de un solo uso y con caducidad. En la base queda **el hash y no el
token**: quien lea esa tabla —una copia de seguridad, un volcado de soporte— no
puede aprobar en nombre de nadie.

Un token inexistente, usado o caducado dan **el mismo error**: distinguirlos le
diría a quien prueba si ese enlace existió, y con eso ya se sabe que hay una
aprobación en marcha sobre algo. Y el enlace se marca usado **antes** de decidir:
si decidir falla hay que pedir otro, que es molesto y mucho mejor que dejar vivo
un enlace que ya ha viajado por un correo reenviable.

### La bandeja de lo que me toca (`CRM-00.03.05.13`)

`GET /aprobaciones/bandeja` trae el contexto dentro y en una sola llamada. Una
bandeja que solo dice «tienes 14 cosas» obliga a abrir catorce pantallas, y lo que
pasa entonces es que se aprueba en bloque sin mirar.

Lo vencido primero y después lo que lleva más esperando. Lo que toca **por
delegación** sale marcado y con el nombre del titular: si no se distinguiera, el
suplente no sabría que está firmando por otro.

### Por dónde va una instancia, sobre su gráfico (`CRM-00.03.05.14`)

`GET /analitica-procesos/instancias/{id}/grafico` devuelve cada nodo con su estado
—`recorrido`, `actual`, `fallido`, `compensado`, `pendiente`, `no_recorrido`— para
que el lienzo lo pinte encima. No devuelve colores ni posiciones: eso es del
front, y si viniera de aquí, cambiar la paleta sería un despliegue del backend.

Se pinta **la versión con la que arrancó la instancia**, no la publicada: una
instancia en vuelo termina con su versión, y enseñarla sobre el gráfico nuevo
señalaría nodos que no tiene. Un nodo sin ejecutar en una instancia terminada sale
como `no_recorrido` y no como `pendiente`: «pendiente» haría pensar que alguien
tiene que ejecutarlo todavía, cuando el proceso ya terminó por otro camino.

### Dónde se atasca un proceso (`CRM-00.03.05.16`)

`GET /analitica-procesos/{clave}` da tiempo por paso, fallos, reintentos y ciclo
completo. Tres decisiones sobre cómo se mide:

* **El paso humano se cuenta desde que se creó la tarea hasta que alguien
  respondió**, no lo que tardó el motor. Medir el motor da milisegundos en todos
  los pasos y esconde los tres días que esperó la firma.
* **La mediana va junto a la media.** Un proceso con una instancia de treinta días
  y cien de una hora tiene una media que no describe a ninguna, y con solo la
  media se optimiza el paso equivocado.
* **Con menos de diez ejecuciones se dice que no es concluyente.** Y a nadie se le
  señala con menos de tres tareas: publicar ese número es señalar a una persona
  por una casualidad.

### Lo que todavía no está

Las **plantillas de flujo por sector** (`CRM-00.03.05.15`) no están. Van con los
módulos verticales —un manifiesto ya trae su sección de `flujos`—, y ponerlas
aquí como una lista aparte habría creado dos sitios donde vive un flujo de
ejemplo.

## Cotización: del catálogo al pedido (`CRM-03.03.02`)

La oportunidad ya llevaba líneas con `producto_id`, pero ese identificador no
apuntaba a nada: el comercial escribía la descripción y el precio a mano. Eso
funciona en una demostración y se rompe en el segundo cliente, porque nadie puede
responder «¿qué le cobramos a este por esto?» sin abrir presupuestos antiguos.

### El precio no es un campo: es el resultado de unas reglas (`CRM-03.03.02.03`)

El precio de catálogo es el punto de partida; encima van las listas por cliente,
por canal, por volumen, por moneda y por vigencia. Con un campo `precio` en el
producto, cada acuerdo comercial acaba siendo un producto duplicado —«CAJA-10
ACME»— y a los dos años el catálogo tiene tres mil referencias y doscientas
reales.

`GET /listas-precio/calcular` devuelve el precio **y qué reglas lo produjeron, en
orden**. Un precio que no se puede explicar se discute con el cliente delante, y
entonces se acaba dando el descuento igual.

Cuatro decisiones del motor:

* **Cuando dos listas encajan gana la de prioridad más baja**, declarada. Si el
  desempate fuera implícito, el precio dependería del orden de inserción en la
  base y cambiaría al restaurar una copia.
* **Una regla puede ser exclusiva** y cortar el paso a las siguientes. Hace falta
  para los precios cerrados por contrato: sin ella, una promoción posterior
  bajaría un precio ya pactado y nadie lo vería hasta la factura.
* **El precio nunca baja de cero.** Una regla mal escrita que lo dejara en
  negativo produciría un abono en vez de una venta, y eso llega a contabilidad
  antes de que nadie lo mire.
* **Cuando no se aplicó ninguna regla se dice** (`de_catalogo`): es la diferencia
  entre «le cobramos su tarifa» y «le cobramos la de catálogo porque no tiene
  tarifa».

El motor está portado de la forma del de contecpos
(`services/catalogo/src/pricing/pricing.engine.ts`): reglas ordenadas por
prioridad, acciones tipadas y rastro de lo aplicado. Cambia el lenguaje de
condiciones —allí JSON-logic, aquí la misma gramática que ya usan el reparto de
leads, la asignación de casos, los segmentos y la elección de transportista—
porque dos gramáticas en el mismo producto obligarían a aprender las dos para
configurar una implantación.

### Qué va con qué (`CRM-03.03.02.02`)

Las relaciones entre productos —`requiere`, `excluye`, `incluye`, `sugiere`— son
reglas del cliente, y meterlas en el código convierte cada implantación en una
rama del producto.

`POST /productos/comprobar-configuracion` devuelve **problemas y sugerencias por
separado**, y no bloquea por las segundas: una regla `sugiere` que impidiera
guardar convertiría una recomendación comercial en un obstáculo, y lo que se hace
entonces es borrarla del catálogo. Lo que falta por `requiere` sale con el motivo
escrito en la regla, porque un «no se puede» sin motivo hace que quien está con el
cliente delante lo salte por otro camino.

### Un presupuesto no se edita: se versiona (`CRM-03.03.02.01`)

La versión 2 es otro documento, no la 1 corregida. Editar en sitio hace imposible
responder a «esto no es lo que me mandaste», que es la conversación que de verdad
ocurre. La anterior queda `sustituido`, no borrada: sigue siendo lo que el cliente
tiene en su correo.

Copiar una versión **no recalcula los precios**. Si lo hiciera, cambiar una coma
del título movería el precio porque las tarifas habrían cambiado entre medias, y
nadie entendería por qué.

`GET /presupuestos/{id}/cambios` calcula la diferencia al pedirla y no la guarda:
una diferencia guardada se queda desfasada en cuanto alguien corrige una línea, y
entonces miente con toda la apariencia de ser un dato.

Un presupuesto lleva **fecha de caducidad**. Sin ella el precio se vuelve eterno y
el cliente lo saca dos años después; y `POST /presupuestos/caducar-vencidos` los
marca, porque uno que sigue diciendo «enviado» seis meses más tarde aparece en el
pipeline como negocio vivo y la previsión lo cuenta.

### El descuento se decide contra el margen (`CRM-03.03.02.04`, `CRM-03.03.02.05`)

Un 20 % sobre un producto con 60 puntos de margen y un 20 % sobre uno con 12 son
cosas distintas, y una matriz que solo mire el porcentaje aprueba la segunda sin
que nadie se entere. La política mira **las dos cosas**, y además el suelo propio
del producto, que existe porque el general no le vale.

**Cuando el margen no se sabe, no se deja pasar.** Se exige aprobación y se dice
que es por eso. Tratar «no lo sé» como «está bien» es cómo se firma un presupuesto
que pierde dinero. Por el mismo motivo, el margen del presupuesto solo se calcula
si se conoce el coste de **todas** las líneas: con una sola sin coste saldría
inflado y se usaría para aprobar un descuento que no se puede dar.

El control está **en el servidor y no en la pantalla**: si dependiera del front,
bastaría una integración que llamara a la API para saltarse la matriz entera. Los
dos umbrales son ajustes en caliente (`descuento_libre_pct`, `margen_minimo_pct`),
no constantes: la política cambia con cada campaña, y un despliegue por cada
cambio hace que se acabe aprobando a mano «esta vez».

Cuando hace falta aprobación, el presupuesto se para y emite
`quote.approval.needed` **con los motivos dentro**, para que quien abra la
aprobación —el motor del capítulo anterior— no tenga que recalcular la matriz para
explicarla.

### El documento (`CRM-03.03.02.06`)

`GET /presupuestos/{id}/documento` devuelve **datos y no un PDF**. La maquetación,
la marca y el idioma son del generador documental, común a toda la suite; generar
el binario aquí metería tipografías y plantillas dentro del servicio de ventas y
obligaría a desplegarlo para cambiar un logotipo.

Lleva la marca y el idioma **del propio presupuesto**, no los del tenant: un grupo
con tres marcas manda ofertas con la que corresponda y quien la compone no tiene
que adivinarlo.

**El coste y el margen no salen**, y el descuento solo se enseña si lo hay: una
columna de ceros invita a pedir descuento a quien no lo había pedido. Las dos
cosas se deciden en el servidor y no en la plantilla, porque enseñarle al cliente
lo que nos cuesta su pedido es el error más caro que se puede cometer al componer
una oferta.

### Aceptar: nace el pedido

Se comprueba la vigencia —aceptar un presupuesto caducado sin decir nada es cómo
se sirve a precio de hace un año— y se comprueba que **haya cuenta**. Un
presupuesto se puede preparar para un posible cliente que todavía no es cuenta; un
pedido no: sin cuenta no hay a quién facturar, y dejarlo pasar convierte el
problema en un rechazo del ERP dos días después, con el pedido ya prometido.

### Contratos y renovaciones (`CRM-03.03.02.08`, `CRM-03.03.02.10`)

**El preaviso es la fecha que importa**, no el vencimiento: el día que vence ya es
tarde para no renovar, y quien quería negociar se encuentra con otro año firmado.
Por eso `contract.renewal.due` se emite en el preaviso, y solo una vez: sin esa
marca el aviso se mandaría cada noche hasta que alguien lo silenciara apagando la
alerta entera.

Los contratos **sin** renovación automática también avisan. Son los que se
olvidan: nadie los renueva y el cliente se va sin que nadie lo haya decidido.

Un contrato renovado queda `renovado` y no `terminado`. La diferencia dice si el
cliente sigue con nosotros, y mezclarlas hace que la tasa de bajas cuente como
pérdidas las renovaciones. La fecha se calcula sumando **meses**, no días: un
contrato que vence el 31 de enero y se renueva doce meses no puede convertirse en
el 3 de marzo.

### Suscripciones (`CRM-03.03.02.09`)

El prorrateo se calcula **por días reales del periodo**, no por treintavos: un
cambio a mitad de febrero con treintavos cobra de menos, y es la diferencia que el
cliente encuentra cuando revisa la factura.

El histórico de cambios es **append-only**, con el antes y el después. Sin él,
responder «¿desde cuándo paga esto?» exige mirar facturas y el ARR de hace seis
meses no se puede reconstruir.

En el recurrente, **las pausadas no cuentan**: una suscripción pausada no factura,
y contarla infla el MRR con dinero que no entra. Se dicen aparte, porque es la
cifra que avisa de una fuga antes de que se convierta en baja.

### El traspaso al ERP no se cierra al enviar (`CRM-03.03.02.11`)

`POST /pedidos/{id}/enviar-erp` deja el pedido **esperando confirmación**. No se
da por bueno porque la llamada no diera error: el ERP puede aceptar el mensaje y
rechazar el pedido después, y un traspaso que se cierra al enviar es cómo se
descubre en el cierre de mes que faltan pedidos.

La llamada la hace `integration` con su conector declarativo; aquí solo se emite
`order.submitted` **con las líneas dentro**, con clave de deduplicación por
pedido. Pedirlas después ataría el traspaso a que `sales` esté en pie en ese
instante, y sin la clave un reintento del relevo crearía dos pedidos en el ERP del
cliente.

`GET /pedidos/conciliacion-erp` es el mismo problema que el encargo mudo del
seguimiento externo, y se resuelve igual: **el silencio no es una confirmación**.
Un pedido enviado del que nadie contesta parece en curso, y detrás casi siempre
hay un mensaje perdido. Los rechazados salen también: un pedido rechazado por el
ERP que nadie mira es una venta cerrada que no se sirve.

### Lo que todavía no está

**Enviar a firma** (`CRM-03.03.02.07`) y la **orquestación order-to-cash como saga
con compensaciones** (`CRM-03.03.02.12`). La primera va con el bloque de firma
electrónica, que está entero pendiente; la segunda encima de él, porque una saga
que no puede compensar la firma no compensa el ciclo entero.

## Firma electrónica (`CRM-06.01.02`)

Un sobre de firma es un objeto con una vida larga y un final legal. Lo que decide
si sirve no es mandarlo: es poder demostrar, dos años después y ante quien lo
discuta, **qué se firmó, quién lo firmó y cuándo**.

### El proveedor es configuración, no código (`CRM-06.01.02.02`)

Sobre el mismo transporte declarativo que usa cualquier otra integración:
dirección, credencial cifrada y mapeo. **No hay un conector por producto ni una
lista de proveedores en el código.** Un conector por casa —DocuSign, Signaturit,
Viafirma— convierte cada cliente con otro proveedor en una versión del producto, y
la lista en el código convierte cada alta en un despliegue.

Cada proveedor declara **qué niveles sabe hacer** y **cómo sabe identificar**.
Mandarle un contrato que exige firma cualificada a quien no la hace produce una
firma que parece válida y no lo es; se para al crear el sobre, no en el juzgado.

Los estados se traducen con un mapa declarado, igual que en el seguimiento de
encargos. Un estado que no está en el mapa **no se adivina**: suponer que el
«completed» de un proveedor nuevo significa firmado haría dar por firmado un sobre
que fue rechazado, y con eso se factura.

### Varios proveedores a la vez, elegidos por regla (`CRM-06.01.02.12`)

Un grupo con filial portuguesa firma allí con otro proveedor, y un contrato de
cien mil no va por el mismo sitio que un albarán. Un solo proveedor por tenant
obliga a elegir el peor denominador común.

Las reglas usan la gramática de siempre y `POST /firma/simular` dice **qué regla
ganó** sin crear nada: una elección que no se puede explicar no se puede corregir,
y aquí decide con qué validez legal sale un contrato.

Una regla puede **subir** el nivel pedido, nunca bajarlo. Dejar que lo rebaje
convierte la política en una sugerencia.

Un proveedor se puede poner **en retirada** (`solo_en_curso`): deja de recibir
sobres nuevos y los que tiene en vuelo terminan con él. Es lo que permite cambiar
de proveedor sin que los contratos a medio firmar se queden huérfanos.

### El nivel decide la identificación (`CRM-06.01.02.05`, `CRM-06.01.02.08`)

| Nivel | Identificaciones que admite |
|---|---|
| simple | correo, SMS, vídeo, certificado, DNI electrónico |
| avanzada | SMS, vídeo, certificado, DNI electrónico |
| cualificada | certificado, DNI electrónico |

Pedir «avanzada» y verificar por correo es decir que es avanzada sin serlo: el
correo demuestra acceso a un buzón, no identidad. Y sin certificado cualificado no
es cualificada, por mucho que el proveedor lo llame así en su folleto. Eso solo se
descubre cuando alguien impugna la firma — el único momento en que la firma
importaba.

Quien recibe **copia** no pasa por esa comprobación: no firma, y exigirle
certificado sería pedir un trámite para leer un correo.

### Sobres, firmantes y orden (`CRM-06.01.02.01`)

Crear **no manda**. Separarlo es a propósito: mandar un contrato a firmar es
irreversible de cara al cliente —le llega un correo— y el error más caro que puede
cometer quien lo maneja es pulsar creyendo que aún estaba montándolo.

Con **orden estricto**, solo le llega al siguiente cuando firma el anterior. Es lo
que hace que un contrato lo firme el cliente *después* del nuestro, que es el orden
que pide quien redacta contratos. Sin orden, les llega a todos a la vez.

Un sobre que solo lleva copias no se manda: no lo firmaría nadie.

**Y mandar manda de verdad.** Hasta el 26-10-2026 no: `enviar` marcaba el sobre
como «enviado», emitía el evento y **no llamaba al proveedor**. El puerto del
proveedor sólo lo usaba la prueba de credenciales, así que al proveedor no le
llegaba nada: el cliente no recibía ningún correo y el CRM decía que estaba
mandado. No fallaba nada — el sobre se quedaba en «enviado» esperando a un
firmante que nunca supo que tenía algo que firmar.

Ahora el envío llama al proveedor con los firmantes, el documento y el nivel, y:

- **guarda el identificador que devuelve el proveedor**. Sin él, consultar el
  estado, descargar lo firmado o cancelarlo no tienen a qué referirse;
- **anota la llamada**, salga bien o mal, con su duración;
- y si el proveedor no lo acepta, el sobre **se queda en borrador** con el motivo
  anotado. Marcar como enviado lo que nunca salió es exactamente el fallo que se
  estaba arreglando.

> Lo cazó recorrer la familia entera. El gate de «escrito y sin enchufar» no lo
> veía, y conviene saber por qué: el puerto **sí** tenía un llamante —la prueba
> de conexión—, así que el recuento lo daba por enchufado. Contar llamantes no
> distingue «lo llama alguien» de «lo llama quien tiene que llamarlo».

### Plantillas con anclajes (`CRM-06.01.02.06`)

Dónde va cada firma y qué rellena cada uno, de dos formas: por página y
coordenadas, o por **anclaje de texto** (`/firma_cliente/`). El anclaje existe
porque las coordenadas se rompen en cuanto el contrato gana un párrafo, y eso pasa
siempre. La plantilla puede subir el nivel exigido, como las reglas y por lo mismo.

### La evidencia se guarda aquí (`CRM-06.01.02.04`)

La cadena de custodia es `append-only` y vive en el CRM, **no solo en el
proveedor**: el día que se cambia de proveedor —o que cierra— se perdería la
prueba de todo lo firmado con él, y eso se descubre justo cuando hace falta.

Cada apunte guarda **cuándo ocurrió según el proveedor** y **cuándo nos
enteramos**. La diferencia es la latencia de la integración, y sin las dos no se
puede defender una fecha.

La ingesta es **idempotente** por el identificador del evento: sin eso la custodia
tendría el mismo acceso dos veces, que es exactamente lo que un perito mira para
decidir si la evidencia es fiable. Y la evidencia **se guarda aunque el estado no
se entienda**: perder un acceso porque no supimos traducir su nombre deja un hueco
que después no se puede rellenar.

Se guardan **dos huellas**: la de lo que se mandó y la de lo que volvió. El
expediente sale marcado como `verificable` solo cuando están las dos, porque sin
ellas «esto no es lo que yo firmé» no se puede contestar.

### El firmado vuelve al expediente (`CRM-06.01.02.07`)

El documento firmado es **otro documento**, no una versión del original: el
original tiene que seguir existiendo tal como salió, porque es la mitad de la
prueba de que lo firmado es lo que se mandó.

Se enlaza al registro que originó el sobre, y **el certificado se enlaza aparte,
con su propio rol**: es el documento que se lleva a un juzgado, y mezclarlo con el
contrato hace que nadie lo encuentre cuando hace falta.

No se archiva el firmado de un sobre que sigue abierto: es cómo se acaba con un
contrato a medio firmar en el expediente, con toda la apariencia de estar cerrado.
Y si el sobre no colgaba de ningún registro, se dice (`sin_origen`): un firmado que
no aparece en ninguna ficha existe en el corpus y nadie lo echa de menos hasta que
hace falta.

### Recordatorios, cancelación y caducidad (`CRM-06.01.02.03`)

El recordatorio tiene un **mínimo entre envíos**. Sin él, un botón pulsado tres
veces manda tres correos en un minuto, y el resultado no es que firme antes: es
que marque el remitente como no deseado y deje de recibir los siguientes.

Cancelar **exige motivo**: al cliente le llegó un correo que va a dejar de
funcionar, y sin motivo nadie sabe por qué — la pregunta llega por teléfono.

Un **rechazo cierra el sobre**. El documento ya no se puede completar, y seguir
mandando recordatorios a los demás es hacerles perder el tiempo con algo muerto.

Caducar es un paso explícito, porque un sobre que sigue diciendo «en curso» tres
meses después aparece en el panel como negocio vivo esperando una firma que ya no
va a llegar.

### El panel (`CRM-06.01.02.10`)

Ordenado por **antigüedad y no por fecha de creación**: lo que lleva más esperando
es lo que hay que empujar, y una lista por fecha entierra lo viejo debajo de lo
nuevo, que es al revés de lo que hace falta.

Dice **a quién se espera** en cada sobre —sin el nombre, el panel dice que algo
está parado y no qué hacer— y distingue **el que nadie ha abierto** del abierto y
no firmado: el primero es un correo que no llegó y el segundo una decisión que no
se toma, y se persiguen de forma distinta.

### Lo que todavía no está

Enviar a firma un presupuesto desde la oportunidad y que el estado del sobre la
mueva —`CRM-03.03.02.07`, que consta pendiente en el catálogo—. El motor ya emite
los eventos necesarios; lo que queda es que `sales` los escuche.

Lo demás de este capítulo se cerró después: llamar al proveedor sin un módulo por
casa, probar la conexión antes de mandar un contrato, el registro de llamadas con
su coste, el cambio de proveedor y la firma presencial en tableta están explicados
en «Lo que faltaba de la firma electrónica», al final de este manual.

## Motor de informes (`CRM-05.01.01`) y cuadros de mando (`CRM-05.01.02.01`)

**Aquí no se ejecuta SQL contra el dato.** La restricción RT-4 dice que la
explotación la resuelve contecintelligence, y la de arquitectura dice que ningún
servicio lee el esquema de otro. Lo que vive aquí es lo que no puede vivir allí:
la definición del informe —que es del tenant y tiene que sobrevivir a un cambio de
motor analítico—, el sobre de seguridad, el plan ya compilado, la programación y
la distribución, y el histórico de instantáneas.

**El plan no es SQL: es una estructura de datos.** La primera versión de este
módulo compilaba a SQL y estaba mal por dos motivos, los dos reales y los dos
cazados por un gate: escribir SQL aquí es un segundo motor de explotación —lo que
RT-4 dice que no se haga—, y obligaba a **interpolar los nombres de campo**. Los
valores iban como parámetros, pero un campo llamado `importe"; DROP TABLE x; --`
se habría salido de sus comillas. Ahora los nombres van como nombres, se
comprueban contra un patrón estricto, y quien ejecute el plan los resuelve contra
su propio modelo.

Quién ejecuta el plan **se registra** (`registrar_ejecutor`), no se importa. Es la
misma inversión que usa el núcleo con los apartados de cumplimiento, y por lo
mismo: si este módulo importara al ejecutor, el motor de informes quedaría atado a
un producto concreto y cambiarlo sería reescribirlo.

### El constructor y sus tipos (`CRM-05.01.01.01`, `CRM-05.01.01.02`)

Cuatro tipos —tabular, agrupado, matricial y de unión— con columnas,
agrupaciones (con periodo: día, semana, mes, trimestre, año), métricas y orden.

La validación **separa lo que rechaza de lo que solo avisa**, igual que los
módulos verticales: rechazar por un aviso deja a alguien sin poder guardar un
borrador a medias, y aceptar en silencio lo grave produce un informe que falla al
ejecutarse delante del cliente. Se rechaza un agregado inventado, un operador que
no existe, un agrupado sin agrupaciones o un matricial sin pivote; se avisa de que
un informe no enseña nada o agrupa sin calcular.

Los agregados y los operadores son **listas cerradas**, por la misma razón que en
ABAC: una definición es dato del tenant y no puede convertirse en SQL arbitrario.

### Filtros (`CRM-05.01.01.03`)

Los fijos van en la definición; los de **ejecución** los rellena quien lo abre. En
los dos casos **los valores van como parámetros y nunca interpolados**: un filtro
es un dato que escribe un usuario, y concatenarlo es una inyección esperando a que
alguien lo pruebe.

### Campos calculados (`CRM-05.01.01.04`)

Una **operación entre dos columnas** —suma, resta, producto, división—, no SQL
libre. Se limita a propósito: un campo calculado que aceptara una expresión libre
sería SQL arbitrario escrito por un usuario final sobre la base de producción, y
la comodidad de poder escribir un `CASE WHEN` no compensa eso.

La división sale del plan marcada con `proteger_division`, para que quien la
ejecute se guarde del cero: en SQL, dividir por cero revienta la consulta entera,
y en un informe eso es una pantalla en blanco en vez de una fila rara.

**Quien los aplica es el motor que ejecuta el plan.** El plan viaja entero, pero
cada ejecutor aplica lo que su esquema declara y lo que no declara lo ignora sin
error: es un cuerpo JSON, y un campo desconocido no es un fallo para nadie.
Durante un tiempo el motor conectado no aplicaba los campos calculados ni el
pivote —los ejecutaba sin ellos, con su tabla y su cara de informe correcto— y
el resultado salía marcado como incompleto para no mentir. Ya los aplica, así
que ese aviso se retiró: **lo obligó la prueba que compara el plan con el
esquema del ejecutor**, que se queja tanto cuando falta una declaración como
cuando sobra un aviso que ya no es cierto.

**El orden de las cabeceras es el del ejecutor, no el que parezca natural aquí**:
agrupaciones, pivote, métricas, calculados y, solo si no hay agrupaciones, las
columnas sueltas al final. El pivote va con las agrupaciones porque para él es
una agrupación más; los calculados van después de las métricas porque uno puede
referirse al alias de una métrica y no al revés. Si los dos órdenes se separan
no salta ningún error: sale una tabla donde cada cabecera nombra la columna de
al lado. Números bien calculados, mal etiquetados, y nadie lo ve leyendo la
pantalla.

Por eso se mide: **si vienen más columnas de las que este lado sabe nombrar, se
dice**. Las filas son listas, así que su anchura es el único dato fiable de
cuántas han venido. Ese aviso es el que protege el día que el motor aprende algo
nuevo —como pasó al desplegarse los campos calculados— y aquí todavía no se ha
nombrado.

**Las filas viajan como listas y los nombres aparte.** Una fila en lista pesa
la mitad, y un informe de cincuenta mil se nota. La exportación lo daba por
sentado al revés —pedía diccionarios— así que descargar un informe en CSV era un
error del servidor y un informe programado fallaba cada noche hasta desactivarse
solo a los tres intentos. Ahora la exportación recibe las columnas, y un valor
que llegue sin cabecera sale nombrado (`columna_3`) en vez de perderse: es un
dato que el motor ha devuelto, y tirarlo es peor que enseñarlo con un nombre
provisional.

Y se puede pedir desde la pantalla, que es lo que faltaba para que alguien lo
notara: cada componente de un cuadro tiene su descarga en CSV. Se pide al
servidor y no se compone con lo que ya está pintado, porque lo pintado puede
venir recortado por el tope del componente —y un fichero que sale por correo con
menos filas de las que hay es justo el fallo que todo esto evita—.

No se supone: se mide. Las filas son listas, así que su anchura dice cuántas
columnas han venido de verdad. Si son las mismas que el informe sabe nombrar y
había campos calculados, es que no se aplicaron, y el resultado sale marcado
`incompleto` con el motivo escrito —que la pantalla enseña bajo la cifra, no en
el JSON—. Y si vienen más columnas de las que se saben nombrar, el aviso cambia:
significa que el motor ya los aplica y quien se ha quedado corto es esta parte.

### La seguridad se resuelve al compilar (`CRM-05.01.01.08`)

Un informe que trae la facturación y la esconde en la pantalla **ya la ha sacado
de la base**: la respuesta de la API la ve cualquiera que abra las herramientas
del navegador.

Un campo que quien lo pide no puede usar **se quita del informe y se dice cuál**
(`campos_retirados`), en vez de fallar. Fallar deja a media plantilla sin poder
abrir los informes de la empresa; quitarlo en silencio hace que dos personas vean
cifras distintas del mismo informe y ninguna sepa por qué.

Un informe marcado `solo_mios` lleva el filtro por dueño puesto **por el
servidor**. Si viniera del cliente, bastaría quitarlo de la petición para ver los
datos de todos, que es exactamente lo que ese informe quería impedir.

Y el registro de cada ejecución guarda **qué campos se retiraron**: es la prueba
de que el informe no enseñó más de lo permitido, y lo que permite auditarlo sin
volver a ejecutarlo.

### Ejecutar (`CRM-05.01.01.09`)

Si no hay motor analítico conectado **se dice**, en vez de devolver una tabla
vacía: un informe vacío se lee como «no hay datos» y manda a buscar el problema al
sitio equivocado. El intento queda registrado igualmente, porque si no nadie
sabría que alguien lo abrió y no pudo.

Se pide **una fila más que el tope** —es lo que permite decir «hay más» sin contar
la tabla entera, que en un informe grande cuesta más que el propio informe— y si
se cortó, se dice: un informe truncado en silencio se lee como el total, y con eso
se toman decisiones.

Un informe que no es del rol de quien pregunta da **404 y no 403**: un 403
confirma que ese informe existe y de qué va su nombre.

### Exportar (`CRM-05.01.01.07`)

CSV se genera aquí porque es texto y no necesita nada. **Excel y PDF no**: se
devuelve el encargo para el generador documental, común a toda la suite. Meter una
librería de PDF en el servicio de explotación obligaría a desplegarlo para cambiar
una tipografía, y acabaría habiendo dos maquetaciones distintas del mismo dato.

### Programación y distribución (`CRM-05.01.01.06`)

Diaria, semanal o mensual, a destinatarios o a un destino externo, y **al menos
uno de los dos**: una programación sin destino no manda el informe a ninguna
parte.

**Un informe programado que falla avisa** (`report.failed`), y a los tres fallos
seguidos se desactiva y se dice. Un informe que deja de llegar no se echa de menos
—la gente supone que no había nada que contar— y eso convierte un fallo en un
punto ciego de semanas; pero seguir intentándolo cada día contra un informe roto
llena la bandeja de todo el mundo con el mismo error.

`omitir_si_vacio` viene **apagado** por defecto, por lo mismo: el silencio se lee
como «no pasa nada» en vez de como «no se ejecutó».

### Instantáneas y tendencia (`CRM-05.01.01.05`)

Es la única forma de contestar «¿cómo íbamos en marzo?»: el dato operativo ya
cambió —una oportunidad cerrada se recategoriza, un importe se corrige— y
recalcular marzo con los datos de hoy da un número que nunca existió.

Se guardan **los resúmenes, no las filas**: guardar el detalle entero convertiría
la tabla en una copia del CRM que crece sin fin y que nadie purga. Dos
instantáneas el mismo día no crean dos puntos, se sustituye la del día: con dos,
cualquier gráfico de tendencia saldría con un pico que no ocurrió.

Y con menos de dos puntos **no se dice que hay tendencia**: una sola instantánea
es una foto, y llamarla tendencia hace que alguien saque una conclusión de un
punto.

### Cuadros de mando (`CRM-05.01.02.01`)

Un cuadro es una colección de componentes, y cada uno apunta a un informe y dice
**cómo se pinta**. El «cómo» va en el cuadro y no en el informe porque el mismo
informe se enseña como tabla en un sitio y como gráfico en otro, y duplicar la
definición para cambiar el dibujo es cómo se acaba con dos informes que dicen
cosas distintas.

Se ve por rol, por equipo o por ser el propietario. **Un cuadro sin roles ni
equipos es de todos**: exigir declarar el público de cada uno haría que el primero
que alguien crea no lo vea nadie, y la conclusión sería que los cuadros no
funcionan.

Solo puede haber **un cuadro por defecto por rol**: con dos, cuál se abre
dependería del orden de la consulta, y eso cambia al restaurar una copia.

## Explotación delegada en contecintelligence (`CRM-05.01.04`)

La restricción RT-4 dice que la explotación no se reimplementa aquí. Esta sección
es la puerta: el canje del token, la correspondencia de organizaciones, la
descripción del CRM para que se le pueda preguntar, la auditoría de lo que se
pregunta y —lo que cierra el círculo— el **ejecutor** que el motor de informes
tenía registrado y vacío.

Antes de este bloque, toda la sección estaba construida y **sin una sola prueba**.
Escribirlas destapó dos defectos reales, los dos contados abajo.

### El canje ocurre en el servidor (`CRM-05.01.04.01`)

La credencial de aplicación puede representar a *todos* los tenants: si bajara al
navegador sería la llave de todos. Lo que baja es un token que nombra una
organización, una persona y unos alcances, y que dura minutos.

### Una organización por tenant (`CRM-05.01.04.02`)

La organización sale de la correspondencia guardada, **nunca de lo que mande el
cliente**: contecintelligence solo acepta nombrar organizaciones mapeadas, y ese
control se pierde si el nombre viaja desde el navegador.

### Los permisos viajan con la pregunta (`CRM-05.01.04.05`)

El rol que se manda es el que corresponde a lo que la persona ve **aquí**, y la
traducción es **a la baja**: ante la duda se manda el rol que menos ve.
Equivocarse hacia arriba en una herramienta que responde con tablas enteras es
enseñar de una vez lo que en el CRM se ve ficha a ficha.

Un plan sin token **no sale**. Sin él la consulta se haría con la credencial de
aplicación, que puede verlo todo: eso es una fuga con otro nombre.

**Un defecto que encontraron estas pruebas.** El filtro que retira del informe los
campos marcados como personales leía la clave `clave` de la definición del campo,
y la clave canónica del metamodelo es `nombre`. Nunca coincidía: el filtro existía
y no filtraba nada, así que un campo personal habría salido en el informe. La
prueba que lo cubría pasaba porque cometía el mismo error al declarar el campo.
Corregidos los dos.

### El CRM descrito para poder preguntarle (`CRM-05.01.04.04`)

Sobre el modelo semántico que ya existía, con la etiqueta de cada campo y su papel
analítico. **Va la descripción y ni una fila**: mandar datos convertiría una
descripción del esquema en una copia del CRM fuera de su sitio, y el propio
paquete lo dice (`sin_datos`) para que se vea al leerlo.

El registro **se rehace cuando cambia el esquema, no cada noche**. Uno que se
refresca por reloj está desfasado justo después de que alguien añada un campo —que
es cuando lo va a buscar—, y uno que se refresca en cada consulta paga el coste en
la pregunta de todo el mundo. Y no se reenvía si nada ha cambiado: lo decide una
huella.

Un tenant que **nunca** se registró no se registra solo por un cambio de esquema:
registrarlo es una decisión de implantación, y hacerlo automáticamente mandaría a
contecintelligence tenants que nadie quería allí.

### Preguntas guardadas y publicadas (`CRM-05.01.04.06`)

Una pregunta nace **sin publicar**: una pregunta a medio afinar que aparece en la
lista de todos se usa como si estuviera bien, y su autor ni se entera.

`POST /explotacion/preguntas/{id}/publicar` la convierte en un **informe del
tenant**, con su programación y su distribución. Es lo que cierra el círculo: se
pregunta en lenguaje natural hasta dar con la respuesta buena, y entonces esa
respuesta se congela. Sin este paso, lo que funciona vive en la cabeza de quien
supo preguntar, y cuando se va se va con él.

Se publica desde una **definición estructurada**, no desde el texto de la
pregunta: una pregunta en lenguaje natural puede dar dos consultas distintas en dos
días —el modelo cambia—, y un informe programado que cambia solo de significado es
peor que no tenerlo.

### Auditoría de lo que se pregunta (`CRM-05.01.04.07`)

La explotación es la vía por la que más dato sale de un CRM de una sola vez. Sin
este registro, «¿quién sacó la lista de clientes antes de irse?» no tiene
respuesta — y esa es la pregunta que se hace después. Se guarda la pregunta y el
**recuento** de lo devuelto, no las filas: copiarlas duplicaría el dato personal y
multiplicaría la superficie que hay que proteger.

### Cuando no responde, se dice qué sí funciona (`CRM-05.01.04.08`)

«Servicio no disponible» deja a quien lo lee sin saber si su CRM está roto. No lo
está: lo que no funciona es **preguntar**, y el CRM entero sigue operativo.
`GET /explotacion/diagnostico` devuelve las dos mitades —lo que falla, con su
motivo concreto, y lo que sigue funcionando—, y la pantalla las enseña **en la
misma tarjeta**: quien lee un aviso en rojo cierra la pantalla, y si la
tranquilidad está más abajo no la lee nadie.

**El segundo defecto que encontraron estas pruebas.** La comprobación de «el plan
no trae token» iba después de leer la configuración, así que en un despliegue sin
contecintelligence configurado el error que salía era «falta configurar», mandando
a arreglar lo que no estaba roto. Ahora se comprueba antes: que falte el token es
un error nuestro, no del despliegue.

### La pantalla (`CRM-05.01.04.03`)

`/explotacion` en el front oficial. No calcula nada, no agrega nada y no
interpreta los datos: pide, enseña y guarda la pregunta. Separa **mis preguntas
sin publicar** de **las publicadas**, por lo mismo que el servidor las distingue.

### Comprobación al arrancar y salud visible (`CRM-05.01.04.11`, `CRM-05.01.04.12`)

La comprobación va **al arranque**, para que el fallo le llegue a quien despliega y
no a quien abre el primer informe tres días después. No impide arrancar salvo que
se pida (`CI_OBLIGATORIO_PARA_ARRANCAR`): el CRM operativo no puede depender del
motor analítico.

El estado —versión, latencia y último error— se guarda **en memoria del proceso** a
propósito: es información de *este* proceso sobre *su* conectividad, y compartirla
entre réplicas diría que la integración va bien en una réplica que no puede
llegar. Y `/health/ready` lee lo último conocido sin volver a preguntar: una
comprobación de salud que hace una llamada de red a otro sistema convierte la
lentitud de ese sistema en la nuestra y, si el orquestador la usa para reiniciar,
en un reinicio en cascada.

Aquí es también donde se **conecta el ejecutor** del motor de informes. Por eso un
despliegue sin contecintelligence deja los informes definibles y no ejecutables,
que es exactamente lo que se le dice a quien los abra.

## Cuadros de mando completos (`CRM-05.01.02`)

El cuadro y su permiso ya estaban; faltaba lo que hace que sirva: los tipos de
componente, los filtros que valen para todo el cuadro, el camino hasta el
registro, las alertas y el embebido.

### El catálogo de componentes es cerrado (`CRM-05.01.02.02`)

Siete tipos —KPI, tabla, gráfico, embudo, mapa, gauge y texto— y **cada uno
declara qué necesita**. Se publica en `GET /cuadros-mando/componentes` para que la
pantalla de montaje ofrezca lo que existe: dos listas que tienen que coincidir
acaban no coincidiendo, y la que se queda corta es siempre la del front.

La validación ocurre **al guardar, no al pintar**. Un componente mal configurado
que solo falla al abrirse se descubre delante de alguien, y lo que se ve es un
hueco sin explicación. Dos ejemplos de por qué cada tipo declara lo suyo:

* un **embudo** exige `orden`, porque sus etapas no se ordenan solas: alfabético
  daría «Cierre, Negociación, Propuesta» y el embudo saldría al revés;
* un **gauge** exige `objetivo`, porque un gauge sin objetivo es un KPI con una
  aguja, y la aguja solo significa algo contra una meta.

Lo que solo es un consejo **avisa y deja guardar**: un KPI sin comparación no dice
si va bien o mal, pero impedirlo dejaría a alguien sin poder montar el cuadro a
trozos.

### Filtros globales y drill-down (`CRM-05.01.02.03`)

El filtro es **del cuadro**, no de cada componente. Si cada uno llevara el suyo,
cambiar el trimestre exigiría tocar ocho sitios y siempre quedaría uno sin
cambiar — y nadie se daría cuenta, porque un número plausible no se cuestiona.

Un componente puede declararse **inmune** (`ignora_filtros`), y hace falta para
los que enseñan contexto («total del año pasado»), que dejarían de decir lo que
dicen si les llegara el filtro del trimestre. Se declara, no se adivina, y la
pantalla lo enseña: si no, quien cambia el trimestre y ve una cifra que no se
mueve concluye que el filtro no funciona.

El drill-down baja **hasta el registro**, no hasta otra agregación, y se lleva los
filtros del cuadro **más el del punto pulsado**: sin lo segundo, pulsar en la
barra de marzo llevaría a la lista del año entero. Un cuadro del que no se puede
bajar al detalle obliga a rehacer la consulta a mano en otra pantalla, y ahí ya no
coinciden los números — y entonces se deja de creer al cuadro.

### Dashboards que enseñan lo del que los abre (`CRM-05.01.02.04`)

Es el mismo mecanismo `solo_mios` del informe: el filtro por dueño **lo pone el
servidor**. Si viniera del cliente, bastaría quitarlo de la petición para ver los
datos de todos. Con eso, un cuadro sirve para los treinta comerciales en vez de
hacer falta treinta cuadros.

### Alertas por umbral y anomalías (`CRM-05.01.02.05`)

**Una alerta que se dispara siempre deja de leerse.** Por eso hay dos frenos:

* **histéresis** — un margen para volver al verde. Una alerta que se apaga en el
  mismo punto en que se enciende manda un aviso por cada oscilación;
* **silencio mínimo** entre avisos de la misma alerta.

Sin ellos, un indicador que baila alrededor del umbral manda cuarenta correos en
una tarde y al día siguiente la regla está desactivada — que es la forma más común
de perder una alerta buena.

La comparación `cambia_mas_de` detecta anomalías por salto, y **no se dispara la
primera vez**: sin valor anterior no hay salto que medir, y decir que sí lo hay
dispararía la alerta siempre al principio.

Lo que **no se ha podido medir** sale aparte (`no_medibles`) y no cuenta como
verde. Dar por bueno lo que no se ha medido es la forma más silenciosa de perder
una alerta.

Y uno se suscribe **a sí mismo**: suscribir a otro convierte un cuadro en correo
no deseado que el receptor no sabe cómo parar, y lo que hace es marcarlo como
basura — y con él, todo lo que mande el CRM.

### Embebido en aplicaciones externas (`CRM-05.01.02.06`)

**Sin dominios no se crea.** Vacío no significa «desde cualquier sitio»: significa
que no se sirve, porque un cuadro embebible desde cualquier parte es un cuadro
público, y lo normal es que traiga cifras de negocio.

La comprobación del dominio es por coincidencia exacta o de subdominio, **nunca
«contiene»**: con «contiene», `micrm.com.ataque.net` pasaría por `micrm.com`.

El enlace **declara a qué persona representa** y se dice cuál. El secreto se
devuelve una vez y en la base queda su hash; revocar no borra, porque el uso
queda en el histórico.

**Ese «actúa como» acota de verdad** (cerrado el 05-10-2026; hasta esa fecha
este párrafo prometía más de lo que había). Lo que el cuadro enseña se calcula
ejecutando sus informes con el alcance de esa persona, no con el de quien tiene
el navegador abierto. Antes se guardaba, se devolvía al resolver el enlace y no
lo aplicaba nadie: un cuadro montado por un comercial y abierto por un director
enseñaba los datos del director.

**Cómo se incrusta, en dos pasos.** El secreto del enlace **no llega al
navegador**: si llegara, cualquiera que abriese las herramientas del
desarrollador se llevaría una credencial de larga vida a ese cuadro.

1. El **servidor** de la aplicación anfitriona llama a
   `POST /api/v1/cuadros-mando/embebidos/abrir` con el secreto, y recibe un
   **ticket corto**. No hace falta ninguna sesión del CRM: lo que autentica es
   el secreto, que se entregó justo para esto.
2. La **página incrustada** lleva ese ticket en `Authorization: Bearer` y pide
   lo que pinta a `GET /api/v1/cuadros-mando/embebido` y los datos de cada
   componente a `POST /api/v1/cuadros-mando/embebido/datos`. El ticket dura
   minutos, sirve solo para ese cuadro y **no lleva permisos**, así que no vale
   para ninguna otra ruta del CRM.

Los datos van **componente a componente** y no de golpe: un cuadro de ocho
servido entero tardaría lo que el más lento, y lo que se vería mientras tanto es
una página en blanco.

**El «con SSO» del enunciado**: la aplicación anfitriona ya autenticó a su
usuario con su propio SSO, y lo dice en el campo `sujeto` al pedir el ticket.
Ese correo **se resuelve aquí** contra las membresías de verdad — lo que el
anfitrión afirma es *quién* mira, no *qué* puede ver—, y quien no tenga acceso a
la organización no abre el cuadro aunque el enlace sea válido.

**Con qué alcance se calcula, se declara al crear el enlace** (`modo_alcance`), y
las dos respuestas son legítimas:

| Modo | Qué enseña | Para qué sirve |
|---|---|---|
| `enlace` (de serie) | Lo mismo a todo el que lo abra, con el alcance de quien lo montó | El panel colgado en una intranet. El tope es lo que ve quien lo creó, nunca más |
| `quien_mira` | Lo que vería esa persona entrando ella | Un cuadro personal dentro de otra aplicación. **Sin sujeto no se sirve**: servirlo con el del enlace sería enseñarle a alguien lo que no le toca por un campo que se olvidaron de mandar |

El consumo del embebido queda marcado como `embebido` en el histórico de
ejecuciones: sin eso, el de un panel colgado en una intranet se mezcla con el de
la gente trabajando, y es el primer sitio donde mirar cuando el motor analítico
se queda corto.

Un secreto inexistente, revocado o de otro dominio dan **el mismo error**:
distinguirlos le diría a quien prueba si ese cuadro existe y desde dónde se sirve.

## Las pantallas que faltaban

### Casos, con el reloj del SLA (`CRM-07.04.03.17`)

El reloj se **pinta** en la pantalla y se **calcula** en el servidor: si lo
calculara el navegador, dos equipos con la hora mal darían dos incumplimientos
distintos del mismo caso.

La bandeja separa **lo que ya incumplió** de **lo que va a incumplir**. Son dos
trabajos distintos: lo primero hay que explicarlo y lo segundo todavía se puede
salvar. Una bandeja que los mezcla hace que se atienda por orden de llegada, que
es el único orden que garantiza incumplir los dos.

### Consola de agente (`CRM-07.04.03.18`)

El punto de la omnicanalidad no es tener cinco bandejas bonitas: es **una sola
cola**. Con una bandeja por canal, el correo se mira dos veces al día y el chat
todo el rato, y quien escribe por correo espera el doble sin que nadie lo haya
decidido. Por eso el canal es una etiqueta y no una pestaña, y lo que se enseña no
es cuándo llegó la conversación sino **cuánto lleva esperando esa persona**.

### Conocimiento (`CRM-07.04.03.19`)

**Lo publicado se distingue de lo que está en revisión, y el estado va al lado del
título.** Un artículo a medias que se lee como bueno se copia y se pega en una
respuesta a un cliente, y ahí ya no hay quien lo recoja. Se marca también lo que
el cliente ve en el portal: escribir para dentro y escribir para fuera no es lo
mismo, y confundirlo es cómo se publica el procedimiento interno de descuentos.

### Segmentación y campañas (`CRM-07.04.03.09`, `CRM-07.04.03.10`)

El recuento de un segmento lleva **siempre su fecha**. Un número sin fecha se lee
como el de ahora, y quien va a mandar un correo a 14.000 personas merece saber si
ese 14.000 es de hoy o de hace tres semanas.

Una campaña enseña **su estado antes que sus cifras**: las de una campaña en
borrador son cero y se leen como un fracaso, y las de una pausada son las de
cuando se paró y se leen como las de hoy.

## Cadencias y el trabajo diario del comercial (`CRM-03.03.01`)

Una cadencia es una secuencia de toques con esperas entre medias. Lo que decide si
funciona **no es el diseño de la secuencia**: es qué pasa cuando el cliente
contesta, que es lo que la mayoría de las herramientas resuelve mal y por eso la
gente acaba mandando un quinto correo a alguien que ya respondió que sí.

### Responder saca del recorrido, siempre (`CRM-03.03.01.04`)

Es la regla que hace que una cadencia sea aceptable y no acoso. `POST
/cadencias/respuesta` es **una sola puerta para todos los canales**: con una por
canal, el que se olvide de registrar la llamada deja a alguien recibiendo el
siguiente correo después de haber contestado.

Y cuando la cadencia lo declara, saca **también a los compañeros de la misma
cuenta**. En B2B contesta uno y se siguen persiguiendo sus tres compañeros, y el
que contestó lo ve. Se puede apagar, porque hay ventas donde cada persona decide
por su cuenta y sacarlas a todas sería perder tres conversaciones por una
respuesta.

Nadie puede estar en **dos cadencias a la vez**: dos secuencias sobre la misma
persona es la forma más rápida de que pida la baja, y ocurre sin querer cuando dos
comerciales importan la misma lista.

### La secuencia (`CRM-03.03.01.01`)

Cinco canales —correo, llamada, mensaje, social y tarea— con su espera. Los pasos
de **correo se ejecutan solos**; los demás salen marcados como manuales y crean
trabajo para una persona. Mandar un correo no es lo mismo que llamar, y una
herramienta que finge que sí acaba con cadencias de cinco correos que nadie llamó.

Lo que **rechaza** y lo que solo **avisa** van separados: un correo sin plantilla o
un canal inventado se rechazan; dos toques el mismo día, doce pasos o una cadencia
de solo correo avisan. No son errores, pero son las tres cosas que convierten una
cadencia en bajas.

Y los toques respetan el horario: un correo automático a las tres de la mañana
dice «esto lo manda una máquina» más alto que cualquier firma, y el sábado dice
además «y no le importas».

### Una cola, no tres (`CRM-03.03.01.02`)

Un comercial con tres listas —tareas, cadencias, leads— trabaja la que tiene
delante, no la que importa. `GET /mi-cola` las junta.

Cada entrada dice **por qué está ahí**, con nombre y no con un número: «toca el
paso 2 de "Prospección fría", con 4 días de retraso». Una prioridad sin
explicación se ignora, porque si no se dice por qué algo está arriba la gente baja
hasta encontrar lo que reconoce.

Una cola vacía se dice **vacía**, que es distinto de haberla terminado.

### Lo que se mide de una plantilla es la respuesta (`CRM-03.03.01.03`, `CRM-03.03.01.06`)

**La apertura la falsean los filtros de correo que cargan las imágenes por su
cuenta**, y optimizar por aperturas lleva a asuntos que se abren y no se contestan
— que es el peor sitio al que llegar, porque parece que va bien.

Por eso la apertura sale como dato crudo y **sin tasa**, con su advertencia al
lado: darle un porcentaje junto al de respuesta invita a compararlos. La tasa que
sí se da es la de respuesta y la de reunión generada.

Con menos de **treinta envíos no se da ninguna tasa**: con cinco envíos y una
respuesta, el 20 % que saldría no describe nada y se usa para descartar una
plantilla que nunca se probó.

### Reuniones sobre huecos reales (`CRM-03.03.01.07`)

La disponibilidad se declara por tramos, con **duración, margen entre reuniones y
antelación mínima**. El margen existe porque sin él se encadenan reuniones sin
respirar y la tercera empieza tarde; la antelación, porque proponer un hueco
dentro de diez minutos produce la reunión a la que nadie llega.

Los huecos se **contrastan con el calendario** que traiga quien llama, y cada uno
dice si se contrastó. Una disponibilidad calculada sin mirar el calendario produce
la reunión que hay que mover, y moverla cuesta más que no haberla propuesto.

El reparto round-robin va por **quién lleva más tiempo sin recibir una**, no por
orden alfabético ni por identificador: los dos dan siempre la misma persona
primero, y el reparto deja de repartir.

## Metodología de venta (`CRM-03.01.02.01`, `CRM-03.01.02.02`, `CRM-03.01.02.03`)

MEDDIC, BANT, SPIN, Challenger o una propia. Con una familia conocida y sin
criterios se usan **los de serie**: un tenant que elige MEDDIC espera MEDDIC, no
una pantalla en blanco donde teclearlo.

**Se dice lo que falta, no lo que hay.** Un indicador que sube al rellenar campos
premia rellenar campos; el que sirve devuelve una lista de cosas que hacer, y por
eso `lo_que_falta` va antes que la puntuación y sale **ordenado por peso**: lo
primero de la lista es lo que más mueve la aguja, que es la única forma de que una
lista de seis cosas se empiece.

Con la mitad de los criterios sin contestar, la oportunidad sale como **no
cualificada**. La puntuación entonces no dice si el negocio va bien: dice que no se
ha cualificado, y son cosas distintas. La puntuación existe para ordenar un
pipeline, no para felicitar a nadie.

El **playbook** que se ofrece es el más específico que encaje: uno que nombra etapa
y segmento manda sobre uno que solo nombra la etapa. Con el orden al revés, el
genérico taparía siempre al que alguien escribió para su caso. Y dice **por qué**
se eligió ese, porque un playbook que aparece sin explicación se cierra sin leerlo.

### Dónde está el resto de esta sección

El **marcador integrado** —click-to-call, grabación y registro automático— tiene
su propio capítulo más abajo, junto con la telefonía y la voz. La **guía de
próximos pasos con contenido**, el **plan conjunto con el cliente** y la
**revisión de oportunidad** también: la primera con lo de inteligencia y las otras
dos en el capítulo de plan conjunto y revisión.

## Recorridos de cliente (`CRM-02.02.02`)

Un recorrido es un proceso con una diferencia: lo ejecutan miles de personas a la
vez y **cada una va por su sitio**. Eso es lo que hace que no viva en el motor de
procesos: un proceso tiene una instancia por expediente, un recorrido tiene una
por contacto y decenas de miles vivas, y meterlas en el motor convertiría cada
envío masivo en cien mil instancias duraderas con su compensación.

### El lienzo es la definición (`CRM-02.02.02.01`)

Como en el motor de procesos: nodos con su tipo, sus salidas y sus posiciones
dentro del mismo documento. Con el dibujo aparte, el día que se desincronizaran el
diagrama enseñaría un recorrido que no es el que se ejecuta.

Se valida **antes de publicar y no al ejecutar**: un recorrido roto descubierto en
ejecución son diez mil personas paradas a mitad de camino, y sacarlas de ahí cuesta
más que el error. Se rechaza un destino que no existe, una decisión sin ramas, una
prueba cuyos pesos no suman cien y —esta es la que importa— **una decisión por
comportamiento sin plazo**: nadie «no ha abierto» hasta que se decide cuándo se
deja de esperar.

Se avisa, sin impedir, de los nodos a los que no llega nadie y de que no haya
salidas declaradas.

Al publicar, **quien está dentro sigue con su versión**. Cambiar el recorrido bajo
los pies de quien ya recibió tres correos produce saltos que nadie puede explicar
después, y son justo los que se descubren por una queja.

### Entrar (`CRM-02.02.02.02`)

Cuatro comprobaciones, ninguna opcional: que esté publicado, que no esté ya dentro
—quien recorrió la bienvenida no la necesita otra vez—, que no esté en un recorrido
**excluyente** —sin eso, quien pasa de captación a cliente recibe las dos cosas a
la vez— y que se le pueda escribir.

Y cuando no se puede, **se dice por qué exactamente**: «suprimido» y «sin
dirección» son cosas distintas, y llamar suprimido a quien no tiene correo manda a
buscar una baja que no existe. Esa distinción salió al escribir las pruebas: el
filtro de marketing devuelve los dos casos juntos, y pasarlos tal cual habría
convertido dos problemas en uno mal etiquetado.

En B2B se puede limitar a **uno por cuenta**: cuatro personas de la misma empresa
recibiendo la misma secuencia es cuatro veces el mismo mensaje en la misma
reunión.

### Salir es lo que más importa (`CRM-02.02.02.07`)

Las salidas se declaran **arriba, valen para todos los nodos y se comprueban antes
de cada paso**. Un recorrido del que no se sale a tiempo manda la oferta de
bienvenida a quien ya compró; comprobarlo solo al entrar lo dejaría recibiéndola
hasta el final.

Hay además un **tope de días**: sin él la gente se queda dentro años, recibiendo un
paso que alguien añadió al final sin pensar en ellos.

### Decisiones por comportamiento (`CRM-02.02.02.03`)

«Abrió», «hizo clic», «visitó», «compró» y «no respondió» son eventos que ocurren
fuera, y la rama se resuelve cuando llegan o cuando vence la espera.

Un comportamiento se anota **en todos los recorridos donde esté la persona a la
vez**: el mismo clic resuelve la rama de los tres, y anotarlo en uno solo dejaría a
los otros dos esperando algo que ya ocurrió. Y si estaba esperando, **se despierta
ya**: esperar al plazo cuando la respuesta ya está es hacer esperar cinco días a
quien contestó en cinco minutos.

### Pruebas A/B (`CRM-02.02.02.04`)

El reparto es **estable por persona**, calculado desde su identificador y no al
azar. Con `random`, reintentar un paso movería a alguien de la rama A a la B y su
historial diría dos cosas distintas.

Y **con pocos datos no se declara ganadora**. Con treinta personas por rama la
diferencia que se ve es ruido, y elegir por ella es peor que no probar: consolida
una variante peor con la confianza de haberla medido.

### Supresión y fatiga se heredan, no se reinventan

Antes de cada acción se comprueban las dos. Lo que se salta sale en `omitidos` y
**no cuenta como enviado**: contarlo inflaría el embudo con correos que nadie
recibió.

Un suprimido a mitad **no para el recorrido**: se salta el envío y se sigue.
Pararlo dejaría a la persona atascada en un nodo para siempre, y volver a meterla
después sería imposible sin tocar la base a mano.

### Analítica por nodo (`CRM-02.02.02.08`)

Se cuenta **gente distinta por nodo**, no pasos: un bucle haría que un nodo tuviera
más pasos que personas y el embudo saldría al revés. Y la caída se dice entre nodos
**consecutivos del camino**, no contra el total: contra el total, un nodo al que
solo llega una rama parece un desastre cuando está funcionando.

Si el recorrido tiene ramas **se avisa**, porque entonces el camino principal es
una aproximación y fingir que hay uno solo daría un embudo que no describe a nadie.

### Recorridos por cuenta (`CRM-02.02.02.09`)

El mismo mecanismo de `por_cuenta` de la entrada: en B2B el sujeto es la empresa y
no la persona, y tratarlo al revés multiplica el mensaje por el número de contactos
que tenga.

## Plantillas y preferencias de correo (`CRM-02.03.01`)

### Bloques reutilizables (`CRM-02.03.01.01`)

El pie legal, la cabecera y el bloque de baja viven **en un solo sitio**. Con
plantillas enteras copiadas, cambiar el pie exige tocar cuarenta y siempre quedan
seis con el viejo — que es exactamente el que trae la dirección que ya no existe.

Los bloques marcados como obligatorios **se añaden a toda plantilla promocional
aunque quien la monte se olvide**, y se dice cuáles se añadieron: quien
previsualiza tiene que entender por qué aparece un pie que él no puso. El de baja
lo es por ley, y confiar en que alguien lo arrastre es cómo se manda una campaña
sin él.

Un bloque que falta **no se ignora**: la plantilla saldría con un hueco y nadie
sabría de dónde salió.

Y los tokens se comprueban antes de mandar: un «Hola {{nombre}}» sin sustituir no
es un fallo técnico, es un correo que dice en voz alta que es automático y lo
reciben miles de personas a la vez.

### Darse de baja no puede ser todo o nada (`CRM-02.03.01.05`)

Quien solo quiere dejar de recibir la newsletter y se encuentra un botón que le
saca de todo, incluidas las facturas, marca el correo como basura. Y eso no se
puede deshacer.

Por eso hay **categorías**. Las obligatorias —avisos de servicio, facturación— no
se pueden apagar, y salen **marcadas como tales y no como una casilla apagada**:
enseñar una casilla que no se puede desmarcar se lee como un engaño, y decir «esto
no se puede quitar porque es tu factura» se entiende.

Si alguien intenta apagar una obligatoria **se dice cuál se ha ignorado** en vez de
fingir que se guardó: dejar creer que se apagó el aviso de facturación produce la
queja de «sigo recibiendo lo que quité».

Una plantilla promocional **sin categoría no se manda**: no se podría rechazar por
categorías, así que darle paso equivaldría a un canal que nadie puede apagar.

Y la comprobación previa al envío junta bloques y preferencias **en una sola
llamada**: la que se olvida es siempre la misma —las preferencias— y el resultado
es un correo a quien se dio de baja.

### Transaccional y promocional por dominios distintos (`CRM-02.03.01.07`)

No es una manía: **comparten reputación de dominio**, así que una campaña con
muchas quejas hunde la entrega de las facturas. Y al revés, mezclarlos hace que
darse de baja de la newsletter parezca que apaga los avisos de servicio.

Los dos dominios son ajustes (`dominio_promocional`, `dominio_transaccional`) y
están **vacíos por defecto a propósito**: así el sistema dice que no están
separados en vez de fingir que sí con un valor inventado. Si no lo están, se avisa
— porque el día que la entrega se hunda, nadie sabrá por qué.

### Lo que todavía no está

De los recorridos, la **optimización de hora y canal por destinatario**
(`CRM-02.02.02.05`), que es de fase 5 y consta como pendiente en el catálogo.

## Canales de ejecución y entregabilidad (`CRM-02.03.02`, `CRM-02.03.01`)

**Un canal es configuración, no un módulo por proveedor.** Twilio, MessageBird o el
agregador del cliente son la misma cosa con otra dirección y otra credencial,
sobre el transporte declarativo que ya existe. Un módulo por casa convierte cada
implantación con otro proveedor en una versión del producto.

Lo que sí es propio de cada canal se declara, porque tratarlos igual produce el
mensaje que no se puede parar:

| Canal | Cómo se da de baja |
|---|---|
| correo | enlace en el pie |
| SMS y RCS | palabra clave de respuesta |
| WhatsApp | botón de la plantilla y bloqueo del proveedor |
| push | permiso del navegador o del dispositivo (`CRM-02.03.02.03`) |

Las **notificaciones push** (`CRM-02.03.02.03`) entran por el mismo sitio que los
demás: su destino es el token del dispositivo, su baja es el permiso del navegador
—que se revoca fuera de aquí— y por eso tienen hora de silencio como el SMS. Un
push a las tres de la mañana vibra en la mesilla igual que un mensaje.

### El consentimiento es por canal (`CRM-02.03.02.01`)

Quien aceptó el correo **no ha aceptado el SMS**, y mandarle uno «porque ya nos dio
permiso» es exactamente lo que sanciona un regulador. Cada consentimiento guarda
además **su prueba** —de dónde salió—, porque sin ella la respuesta a «¿quién
autorizó esto?» es «no consta», que ante un regulador equivale a «nadie».

La baja se reconoce por **la primera palabra, sin acentos ni mayúsculas**. Quien
escribe «BAJA» desde el móvil manda tantas variantes como teclados hay, y exigir
una exacta deja sin efecto una baja que la persona sí pidió — que es lo que acaba
en denuncia.

Y hay **horas de silencio** por canal: un SMS a las once de la noche despierta a
alguien, y el coste de eso no es una baja, es una queja. El correo no las tiene,
porque a las tres de la mañana espera en la bandeja sin molestar a nadie.

### WhatsApp: la ventana y las plantillas (`CRM-02.03.02.02`)

Fuera de la ventana de 24 horas solo vale una **plantilla aprobada**. Mandar texto
libre fuera de ella **no da error**: el proveedor lo descarta y el mensaje no llega
nunca, que es peor que un error porque nadie se entera. Por eso el estado de la
plantilla se comprueba antes, y una no aprobada se para aquí.

Quien escribe **abre la ventana**: el que te habla autoriza a contestarle sin
plantilla, y eso se anota en el mismo sitio que la baja.

### Una sola comprobación antes de mandar

`GET /canales-marketing/comprobar` mira cinco cosas de una vez: canal activo,
consentimiento **de ese canal**, hora de silencio, ventana de WhatsApp y plantilla
aprobada. Repartidas por el código, la que se olvida es siempre la del
consentimiento.

### Landings y formularios (`CRM-02.03.02.06`)

**Recoger un teléfono no autoriza a mandar SMS.** El consentimiento se pide aparte
y por canal, y si la landing no lo declaraba se ignora **y se dice**: dar por
consentido lo que solo se ha escrito en una casilla es justo la práctica que
sanciona un regulador, y si no se avisara, quien monta la landing creería que está
recogiendo un permiso que no recoge.

El pre-rellenado devuelve **solo los campos que la landing pide**, no la ficha
entera: pre-rellenar con datos que no estaba pidiendo le enseña a quien lo abre —o
a quien recibió el enlace reenviado— lo que sabemos de otra persona.

### Personalización (`CRM-02.03.01.02`)

Tokens con **valor por defecto** (`{{nombre|cliente}}`), que es la diferencia entre
«Hola cliente» y «Hola », que es lo que se manda cuando el dato falta y nadie lo
previó. Y condicionales de «si existe», nada más: darle a una plantilla un lenguaje
con condiciones convierte cada campaña en código sin revisar.

### Entregabilidad (`CRM-02.03.01.03`)

**Un dominio sin SPF, sin DKIM o sin DMARC no rebota: llega a basura.** Y eso no
aparece en ningún informe de rebotes — aparece como una campaña que nadie abrió,
que es el diagnóstico equivocado y lleva a reescribir el asunto en vez de arreglar
el DNS.

DMARC en `none` se señala aparte: detecta pero no bloquea, así que sirve para medir
y no para proteger.

El **calentamiento** pone un tope por día. Una IP nueva que manda cien mil el
primer día se quema, y quemarla cuesta semanas.

### Revisión antes de enviar (`CRM-02.03.01.06`)

Es una **ayuda, no un veredicto**: nunca bloquea. Un sistema que bloquea por una
palabra acaba con la gente escribiendo «gr4tis», que es peor para el filtro y para
quien lee. Señala las palabras que marcan los filtros, el asunto demasiado largo
—en el móvil se corta sobre los 40 y lo que importa suele estar al final—, los
tokens sin sustituir y el dominio sin autenticar.

### Las pantallas (`CRM-07.04.03.11`, `CRM-07.04.03.12`)

Dos módulos en el front oficial: **canales de ejecución** —canales, landings y
dominios de envío, con su estado de autenticación a la vista— y **contenido y
gobierno** —plantillas, bloques, categorías de preferencia y supresiones—.

Van separados a propósito: lo primero lo toca quien monta la campaña y lo segundo
quien responde de lo que se manda. Juntarlos en una sola pantalla hace que el
consentimiento se vea como un detalle de configuración del canal, y es al revés.

### Lo que no está, y por qué

La **optimización de hora de envío por destinatario** (`CRM-02.02.02.05`) **sigue
pendiente**, y esto se descubrió construyéndola: la única señal de apertura que
existe hoy es el estado del miembro de campaña, y una persona está **una sola vez
en cada campaña**. Diez aperturas son diez campañas, así que para la mayoría de los
contactos nunca habrá datos suficientes. La función existe y devuelve la hora
cuando los hay —en UTC y diciéndolo—, pero llamar «hecha» a la capacidad sería
prometer una optimización que casi nunca se va a poder hacer. Hace falta telemetría
de apertura por envío, que hoy no se guarda.

Quedan también la **publicidad digital y el retargeting** (`CRM-02.03.02.04`), el
**correo postal y el telemarketing como pasos del recorrido** (`CRM-02.03.02.05`) y
la **personalización web** (`CRM-02.03.02.07`).

## Territorios, cuotas y capacidad (`CRM-03.02.02`)

Un territorio decide **de quién es un cliente**, y por eso es la pieza que más
discusiones provoca de todo un CRM: cuando dos comerciales creen que una cuenta es
suya, el problema no es técnico.

### La asignación se calcula y se explica (`CRM-03.02.02.01`, `CRM-03.02.02.02`)

Con asignación manual, el territorio existe en una hoja de cálculo y el CRM dice
otra cosa; con reglas, el CRM **es** la hoja de cálculo.

Un territorio se recorta por geografía, sector, tamaño, producto, canal o cuenta
nominal, con la gramática de condiciones de siempre, y cuelga de otro en jerarquía
—quien lleva el padre ve lo de los hijos—. Cuando dos encajan gana **la prioridad
más baja, declarada**: con desempate por orden de inserción, el dueño de una cuenta
cambiaría al restaurar una copia de seguridad.

`POST /territorios/resolver` devuelve **siempre el porqué**. Sin él, «¿por qué esta
cuenta es de Norte?» no tiene respuesta, y esa es justo la pregunta que abre la
discusión — que no se cierra con un número, se cierra con una regla.

Una cuenta que no encaja en ningún sitio **se dice**, no se asigna al primero
disponible: una cuenta sin dueño es un problema que hay que ver, y rellenarlo solo
lo esconde.

Un territorio nace **en borrador** y no asigna nada hasta publicarse. Es lo que
permite montar el mapa entero —con sus solapes y sus huecos— antes de que mueva
una sola cuenta.

### Quién lo trabaja, y por qué se vuelve a publicar al cambiarlo

Un territorio tiene un **responsable** y puede tener **miembros**, y los dos
cuentan a la hora de ver sus cuentas: tener al responsable fuera de esa lista
obligaría a cada pantalla a acordarse de sumarlo, que es la clase de cosa que una
de ellas olvida.

Lo que no es obvio: **añadir o quitar a alguien vuelve a publicar el mapa**. El
acceso por territorio no lo resuelve el servicio que guarda el territorio, sino
cada servicio contra **su propia copia replicada** —igual que la jerarquía de
mando y los ajustes en caliente—, y esa copia solo cambia cuando llega el evento.
Añadir un miembro sin republicar lo dejaría apuntado en el maestro y sin efecto en
ninguna pantalla: peor que no poder añadirlo, porque parece hecho.

Y se publica **también al quitar**, que es la mitad que más importa: quien deja un
territorio tiene que dejar de ver sus cuentas ese día. Un alta que se propaga y
una baja que no es la forma más silenciosa de que alguien siga viendo la cartera
de la que ya no se ocupa.

Si el territorio sigue en borrador no se emite nada: publicarlo es una decisión
que se toma una vez, y adelantarla al añadir un miembro haría que un mapa a medio
montar empezara a asignar cuentas.

### Las excepciones son parte del modelo (`CRM-03.02.02.02`)

Siempre hay una cuenta nominal que lleva el director aunque esté en la zona de
otro. Si no se puede declarar, alguien la reasigna a mano y el siguiente recálculo
se la quita — y entonces nadie vuelve a fiarse del recálculo.

La excepción **manda sobre cualquier regla**: es el punto entero de que exista. Y
el **motivo es obligatorio**, porque una excepción sin motivo es indistinguible de
un error y dos años después nadie se atreve a quitarla.

### Simular antes de publicar (`CRM-03.02.02.03`)

**Publicar y ver qué pasa** significa que doscientas cuentas cambian de dueño el
lunes por la mañana, y deshacerlo no devuelve las conversaciones que ya se
tuvieron.

La simulación dice tres cosas: qué cambia de dueño, qué se queda **sin
territorio** y qué queda en **solape** —dos territorios con la misma prioridad—.
El solape es el error que produce una asignación dependiente del orden alfabético,
y nadie lo busca hasta que dos comerciales discuten.

### La cuota se prorratea por días (`CRM-03.02.02.04`, `CRM-03.02.02.05`)

Un comercial que entra el 20 de febrero no tiene el mes entero, y darle la cuota
completa hace que su primer periodo sea imposible y el del equipo, injusto: alguien
tendrá que cubrir lo que él no podía hacer.

Se devuelven **los dos números** —el del plan y el efectivo— porque el objetivo
anual sigue siendo el primero, y además el **hueco**: lo que nadie cubre si la
cuota se prorratea y no se reparte. Ese es el número que se olvida.

### Consecución y ranking (`CRM-03.02.02.06`)

El ranking sale **por porcentaje y no por importe**: por importe, quien lleva la
cuenta grande gana siempre y el ranking deja de decir nada sobre quién trabaja
bien.

Lo logrado **lo trae quien llama**. Vive en las oportunidades, y calcularlo desde
aquí sería recalcular el forecast con otro criterio — y dos números distintos de lo
mismo es peor que uno solo.

### Cobertura de pipeline (`CRM-03.02.02.07`)

Se mide contra la cuota que **queda**, no contra la del periodo. A mitad de
trimestre, comparar el pipeline con la cuota entera dice que todo el mundo va mal
incluso cuando van bien, y a fuerza de decirlo deja de mirarse.

La cobertura mínima —tres veces lo que falta— es un ajuste y **no una ley**: un
equipo que cierra el 50 % necesita dos y uno que cierra el 15 % necesita casi
siete. Se devuelve el valor usado para que quien lo lea sepa contra qué se compara.
Y quien ya cumplió sale como `ya_cumplida`, no como «cobertura infinita»: no
necesita más pipeline, que es distinto de tener muchísimo.

## Plantillas de actividad, visitas y recurrencias (`CRM-01.02.01.07` a `CRM-01.02.01.09`)

### Plantillas (`CRM-01.02.01.07`)

Es lo que convierte «hay que hacer una implantación» en catorce tareas con fechas.
Sin ellas, cada persona inventa su lista y la mitad se olvida de lo mismo.

Los desfases se cuentan **desde la fecha de arranque**, no desde hoy: una
implantación que empieza el mes que viene tiene sus tareas colgando de esa fecha, y
calcularlas desde hoy las pone todas vencidas antes de empezar.

Y se devuelve **cuántas cayeron en quien la lanzó** por no decir de quién eran. Sin
ese número, una plantilla mal repartida parece bien repartida, y la implantación
acaba siendo la lista de tareas de una sola persona.

### Visitas con check-in (`CRM-01.02.01.08`)

Un check-in demuestra que se estuvo, no que se dijo que se iba. La diferencia
importa cuando el cliente dice que nadie fue.

**La distancia se calcula en el servidor**: un check-in cuya distancia la manda el
móvil se falsifica cambiando un número.

Estar lejos **no bloquea**: se marca. Hay polígonos donde el GPS falla cien metros
y direcciones mal geocodificadas, y rechazar el check-in deja sin registrar una
visita que sí ocurrió — que es peor que registrarla con un aviso. Si la precisión
que informa el dispositivo es peor que el tope, se dice: una distancia de 300 m con
una precisión de ±800 m no significa nada.

Y una visita de dos minutos se **señala**, no se rechaza: puede ser un error al
pulsar y puede ser que no le recibieran, y son cosas distintas.

### Recurrencias (`CRM-01.02.01.09`)

Una tarea recurrente que no se reprograma sola se convierte en una lista de tareas
vencidas, y una lista de vencidas es una lista que se deja de mirar.

Hace falta **un final** —fecha o número de repeticiones—: una recurrencia sin fin
sigue creando tareas cuando el proyecto lleva dos años cerrado, y quien las recibe
no sabe ni por qué.

Con `una_a_una`, **la siguiente no se crea hasta que se cierra la anterior**. Crear
las 52 de golpe llena la bandeja de tareas de dentro de un año, y lo que hace la
gente entonces es dejar de mirar la bandeja. Las que esperan salen aparte del
informe: no son un fallo, y confundirlas con uno lleva a apagar el `una_a_una`.

Los meses se suman **como meses**: una revisión mensual el día 31 cae el último día
del mes siguiente, no el 3 del otro.

Esto es la **actividad que vuelve** —una revisión trimestral, un seguimiento
mensual—, que es distinto del **aviso que insiste** sobre una misma tarea y de la
**tarea que se empuja sola** cuando nadie la atiende. Las tres se explican en
«Los recordatorios los dispara el reloj, no el usuario» (§33); confundirlas lleva
a crear cincuenta y dos tareas para conseguir que suene un aviso tres veces.

## Canal indirecto: PRM (`CRM-03.04.01`)

Vender por canal no es vender con más gente: es vender con gente **que no trabaja
aquí y que a veces compite entre sí**. Todo lo que sigue sale de esa frase.

### Alta, niveles y certificaciones (`CRM-03.04.01.01`)

El nivel de un partner no es una etiqueta: es un contrato. «Oro» significa un
descuento mayor, una protección más larga y unos requisitos que hay que **seguir**
cumpliendo. Por eso los niveles son filas configurables y no una lista en el
código: los de un fabricante de maquinaria no se parecen a los de una editorial de
software, y con tres niveles fijos el primer cliente pide el cuarto.

Los requisitos se guardan **medidos** —facturación mínima, certificaciones
exigidas—, no descritos. Un requisito en prosa no se comprueba nunca y el nivel
acaba asignándose a dedo.

Un partner **nace en alta, no activo**. Uno que entra activo entra al portal y
registra oportunidades antes de haber firmado nada; y cuando se revise el
programa, nadie sabrá cuáles completaron el alta. Se puede **forzar la activación
con motivo**: hay altas que se cierran con un trámite pendiente por decisión
comercial, y sin esa puerta lo que se hace es marcar el trámite como hecho sin
hacerlo — y entonces la lista de pendientes deja de decir la verdad.

Las certificaciones **caducan de verdad**, y son de una persona, no de una
empresa: si esa persona se va, el partner deja de cumplir aunque el logotipo siga.
El preaviso es un ajuste porque certificar a alguien lleva semanas y avisar el
mismo día no sirve de nada.

Y la facturación **la trae quien llama**: vive en los pedidos y en el ERP.
Mientras no se pasa, el nivel sale como **no concluyente** en vez de incumplido —
dar cero por bueno bajaría de nivel a quien factura.

### Portal de partner y registro de oportunidades (`CRM-03.04.01.02`)

El registro de oportunidad es lo único que sostiene un canal. Un partner invierte
semanas en un cliente; si el fabricante —o el partner de al lado— puede entrar
detrás y cerrarlo, deja de traer negocio y pasa a esperar el suyo.

El cliente final se identifica por **NIF, dominio o cuenta**, nunca por el nombre:
«Talleres García SL», «Talleres Garcia» y «T. García» son la misma empresa y tres
registros distintos, y con tres registros la protección no protege de nada.

**Aprobar es fijar una fecha.** Una protección «mientras trabaje el cliente» no se
puede comprobar y acaba discutiéndose por correo. Los días salen del nivel del
partner y, si no lo declara, del ajuste del programa. **Rechazar exige motivo**:
sin él, el partner no sabe si fue por conflicto, por territorio o porque el cliente
ya era nuestro, y lo que aprende es a no registrar.

Cuando dos partners van al mismo cliente, el segundo registro **se guarda igual**,
marcado en conflicto. Tirarlo dejaría al fabricante sin saber que dos partners van
al mismo sitio, que es justo lo que tiene que saber. Y al segundo **no se le dice
de quién es el otro registro**: para un competidor que también es partner, el
nombre es la información que estaba buscando. Al propio partner sí se le dice que
ya lo tenía él — es su dato, y no decírselo le hace registrar lo mismo cada
semana.

La caducidad de la protección es **explícita y auditada**, no un cálculo al vuelo:
el partner tiene derecho a ver qué día se le cayó y por qué.

El portal tiene su propia identidad, como el de cliente: quien entra no es un
empleado, no cuenta para licencias y su ciclo de vida lo manda el acuerdo de canal.
El enlace es de un solo uso, y a un correo que no tiene acceso se le responde
**igual que a uno que sí**: distinguirlos convertiría el portal en un comprobador
de qué empresas son partners nuestros.

### Aislamiento entre partners (`CRM-03.04.01.03`)

La RLS aísla tenants; esto aísla **dentro** de un tenant. Dos partners del mismo
fabricante comparten tablas y hasta clientes finales, y sin embargo lo que uno
registra no puede existir para el otro.

Tres decisiones, y las tres son lo contrario de lo cómodo:

El compartimento vive **en el token**, no en un parámetro de la petición. Si el
filtro saliera de un identificador que manda el cliente, colarse sería cambiar un
número en la URL.

Un registro **sin** compartimento no se ve desde dentro de uno. La tentación es
dejar que el partner vea «lo general»; lo general es la cartera directa del
fabricante, que es justo lo que no puede ver.

Cruzar el compartimento devuelve **404, no 403**. Un 403 confirma que ese registro
existe, y entre competidores la existencia ya es la información: saber que hay una
oportunidad registrada en ese cliente le dice que vaya a por ella.

El mecanismo es genérico: se llama `partner` porque es el primer uso, pero sirve
igual para una franquicia, un concesionario o un despacho colaborador.

### Fondos de marketing — MDF (`CRM-03.04.01.04`)

Dinero del fabricante que gasta el partner. Quien decide no es quien paga, quien
justifica no trabaja aquí, y el ejercicio se cierra pase lo que pase.

**Lo comprometido cuenta como gastado.** Es el error clásico: un fondo que solo
descuenta lo ya pagado enseña saldo disponible cuando está todo aprobado y
pendiente de factura. Se sobrecompromete, y en noviembre alguien tiene que decirle
a un partner que su campaña aprobada no se paga. Aprobar por encima del saldo se
rechaza: ese es el momento exacto en que el fondo se rompe.

**Se puede pedir aunque no haya saldo.** Impedirlo escondería la demanda real, y
el fabricante necesita saber cuánto se le está pidiendo de más para decidir si
amplía el fondo.

**Justificar tiene fecha**, y el plazo nunca se pasa del cierre del fondo:
justificar en marzo contra un presupuesto que cerró en diciembre no lo cobra nadie.
Vencido, el dinero vuelve al fondo de forma explícita y auditada. Fuera de plazo
se admite justificar, **marcándolo**: no dejar hace que la factura llegue por
correo y alguien la meta a mano sin plazo ninguno.

**Lo aceptado es lo menor de lo aprobado y lo justificado.** Se aprueba una campaña
de 10.000 y se justifican 6.000: se pagan 6.000 y vuelven 4.000 al fondo. Pagar lo
aprobado sin mirar la justificación es regalar dinero; no devolver el resto es
perderlo.

Y el retorno **se declara, no se supone**: junto a los leads se da la **cobertura
de la medición**, porque un retorno estupendo calculado sobre el 10 % del gasto no
es el retorno del fondo.

### Precios y descuentos de canal (`CRM-03.04.01.05`)

No hay un motor nuevo. El de precios ya sabe de canal, listas, vigencias y
prioridades; aquí solo se declara **qué canal y qué lista** le tocan a este partner
y **cuánto puede descontar por su cuenta**. Duplicarlo habría dado dos precios
distintos para el mismo producto, que es peor que no tener precios de canal.

Se devuelve el **precio suelo**: por debajo de ahí hace falta aprobación. Sin ese
número, el tope existe en el acuerdo y no existe en la pantalla, y entonces se
descubre al firmar. Y sin acuerdo no se dice que el tope es cero: se dice que **no
hay acuerdo**, que lleva a otra conversación con el partner.

### Rendimiento y planes conjuntos (`CRM-03.04.01.06`)

Lo cerrado lo trae quien llama, igual que en las cuotas de venta directa. El número
propio del canal es la **conversión**: un partner que registra treinta clientes y
cierra uno no está trabajando, está bloqueando treinta clientes a los demás, y eso
no se ve en el importe.

La cuota de canal **es la misma cuota** de ventas, con el mismo prorrateo y el
mismo ranking. Con una tabla aparte, el primer informe que mezclara canal y venta
directa habría tenido que sumar dos números calculados de dos maneras.

Los objetivos del plan conjunto se guardan con su métrica y su número. Un plan
escrito en prosa —«crecer en el sector sanitario»— no se puede revisar en el
trimestre siguiente, y no revisarlo es lo que le pasa a casi todos. Un objetivo sin
dato sale como **no medible**, no como incumplido.

## Incentivos y comisiones (`CRM-03.02.03`)

La comisión es lo único del CRM que la gente comprueba a mano, con una hoja de
cálculo propia, todos los meses. Y tienen razón en hacerlo: es su sueldo. Un motor
que no se pueda cuadrar con esa hoja no se usa, se discute.

### Planes: porcentaje, escalado, acelerador y SPIFF (`CRM-03.02.03.01`)

El plan nace **en borrador** y no liquida hasta activarse; una vez activo ya no se
modifica —se cierra y se crea el siguiente—, porque cambiarlo en caliente haría que
dos liquidaciones del mismo periodo salieran distintas según cuándo se calcularan.

**El escalado declara si es marginal o retroactivo.** Es la ambigüedad que más
disputas causa: al pasar de tramo, ¿se cobra el porcentaje nuevo solo por lo que
excede, o por todo lo vendido? Las dos formas existen, ninguna es «la obvia», y la
diferencia en la nómina es enorme. Aquí hay que decirlo, y se dice en cada tramo.

El tramo se decide por **lo acumulado del periodo**, no por la operación suelta. Si
se mirara operación a operación, un pedido grande pagaría al tipo alto y diez
pequeños al bajo por el mismo total, y el comercial aprendería a agrupar pedidos en
vez de a vender.

Antes de activar, el plan **se revisa**: huecos, solapes y mezcla de modos. Un hueco
entre 50.000 y 60.000 no da error en ningún sitio: **da cero**. Quien venda 55.000
cobrará menos que quien vendió 49.000 y nadie sabrá por qué hasta que lo reclame.

El SPIFF tiene ventana y condición, y **la condición se valida al guardarla**: un
operador mal escrito no falla, deja de premiar en silencio — y no protesta nadie
porque nadie sabía que le tocaba.

El acelerador necesita cuota. **Sin ella no se evalúa y se dice**: aplicarlo sobre
una cuota supuesta de cero lo dispararía siempre.

### Cálculo, simulación y previsión (`CRM-03.02.03.02`)

Simular y liquidar son **la misma función**. Una simulación calculada por otro
camino acaba no coincidiendo con la nómina, que es exactamente lo que nadie
perdona.

Las operaciones las trae quien llama: lo vendido vive en oportunidades y pedidos, y
recalcularlo aquí daría un segundo número del mismo negocio. Las que no traen el
dato sobre el que comisiona el plan salen aparte como `sin_base`: tratarlas como
cero las haría desaparecer del desglose, y el que falta en la lista es siempre el
que más protesta.

En la previsión, el pipeline entra **ponderado por su probabilidad** y se devuelven
los dos números por separado —lo devengado y lo previsto—. Mezclarlos da una cifra
que parece ganada y no lo está, y esa cifra se acaba gastando.

### Aprobación, disputa y trazabilidad del pago (`CRM-03.02.03.03`)

La aprobación la resuelve **el motor del orquestador**, el mismo que aprueba todo lo
demás: montar una segunda cadena aquí daría dos sitios donde mirar quién aprobó qué.

**La disputa es parte del proceso, no una incidencia.** Mientras esté abierta, el
pago no sale; sin ese freno lo que pasa es que se paga, luego se corrige en la
siguiente y nadie entiende su nómina. Hay plazo, y pasado el plazo la disputa **se
registra igual, marcada fuera de plazo**: ni se pierde —el dato es real— ni se
acepta en silencio.

El ajuste de una disputa aceptada entra como **línea nueva**, nunca editando la
original: corregir en sitio deja un número que ya no coincide con lo que se comunicó
y sin nada que explique la diferencia.

Una comisión que se cae —el pedido se anuló, el cliente devolvió— se **revierte con
una línea negativa que apunta a la original**. Una reversión invisible es la forma
más rápida de que alguien vea su nómina, no la reconozca y deje de fiarse del resto.

**Pagar exige referencia** —nómina, remesa o factura—. «Pagada» sin dónde mirarlo no
se puede comprobar, y es lo primero que se pregunta cuando alguien dice que no lo ha
cobrado.

Y lo liquidado es **una foto, no una vista**: se guarda el plan aplicado junto a la
liquidación. Quien cobró en marzo tiene derecho a que marzo siga diciendo lo mismo
en junio.

El mismo motor liquida a un partner del canal (`CRM-03.04.01.06`): un segundo motor
para el rappel habría dado dos formas de calcular lo mismo.

## Canal indirecto en la interfaz (`CRM-07.04.03.16`)

La pantalla del canal pone **los registros de oportunidad por delante de los
niveles**: los niveles se tocan una vez al año y los registros son lo que hay que
decidir hoy, sobre todo cuando traen conflicto entre dos partners. Junto a ellos,
los fondos de marketing con su saldo y las liquidaciones con su desglose, que es lo
que el partner pregunta cuando llama.

## Servicio de campo (`CRM-04.04.01`)

El trabajo de campo tiene una particularidad que lo cambia todo: **quien ejecuta
no está delante de un ordenador**. Está subido a una máquina, a veces sin
cobertura, y con el cliente mirándole. Un sistema que le estorbe no se usa: se
apunta en una libreta y se pasa el viernes — y entonces el CRM no tiene nada.

De ahí salen las cuatro decisiones que se repiten en todo el módulo: al técnico
**se le marca, no se le bloquea**; lo que se planifica **se explica**; lo que no
se puede medir **se dice**; y el móvil trabaja sin red.

### Órdenes con líneas, materiales, tiempos y firma (`CRM-04.04.01.01`)

Una orden nace en borrador y **devuelve qué no se podrá hacer** con lo que le
falta: sin coordenadas no entra en la optimización de ruta, sin competencias
declaradas le puede tocar a cualquiera. Son avisos, no bloqueos: quien crea la
orden muchas veces no tiene ese dato, y exigírselo hace que no la cree.

Cada línea —material, tiempo, desplazamiento— se apunta con su **cobertura de
garantía calculada en ese momento**, no al facturar. El técnico tiene que poder
decirle al cliente ahí mismo si eso lo paga él.

Y por eso **facturable y cubierto son dos campos**, no uno: una línea puede ser
facturable y estar cubierta —la paga el fabricante, no el cliente—, y con un solo
campo la reclamación al fabricante no se puede sacar. La orden devuelve **tres
cestas**: lo que paga el cliente, lo que se reclama y lo que **no se sabe**.
Fundir la tercera con cualquiera de las otras dos es facturar mal o perder una
reclamación.

La firma guarda **la huella de lo firmado**. Una conformidad que no dice sobre qué
se dio no sirve de nada el día que se discute lo que se hizo, y el parte se puede
editar después: con la huella, editarlo se nota. Se admite firmar **no conforme
con motivo** — obligar a que el cliente firme conforme para poder cerrar hace que
firme el técnico por él, y entonces ninguna firma vale nada.

### Programación y rutas (`CRM-04.04.01.02`)

Las competencias se guardan **con nivel**: «sabe de frigorífico» y «está
certificado en gas fluorado» no son lo mismo, y mandar al primero a un trabajo que
exige lo segundo es un viaje perdido y, a veces, una sanción.

Al pedir candidatos se devuelve también **por qué se descarta a cada uno**. Es la
mitad del valor: cuando el planificador dice «nadie disponible», hace falta saber
si es por competencia, por zona o porque están todos de baja — son tres decisiones
distintas. Un técnico **sin zonas declaradas cubre todas**: un dato que falta no
puede dejar a alguien sin trabajo sin que nadie sepa por qué.

Asignar a quien no tiene las competencias **se puede forzar con motivo**. En un
día malo, mandar al que casi puede es mejor que no mandar a nadie, pero tiene que
quedar escrito que se hizo a sabiendas. El solape de citas **avisa y no bloquea**:
en campo, dos citas solapadas son a veces un trabajo de diez minutos metido entre
dos, y prohibirlo obliga a planificar fuera del sistema.

La ruta usa la **heurística del más cercano** desde la base del técnico. No es el
óptimo del viajante y no se presenta como tal: para seis u ocho visitas la
diferencia es pequeña, y una heurística que se explica en una frase se puede
corregir a mano — que es lo que va a pasar igualmente. El tiempo de viaje sale de
la **distancia en línea recta** y una velocidad media configurable, y se declara
así (`estimacion: "linea_recta"`) para que nadie lo confunda con una ruta real.

Lo que no tiene coordenadas **va al final y se dice**; sin la base del técnico, la
ruta no se declara optimizada, porque el primer viaje del día no se estaría
contando y la jornada parecería media hora más corta.

### App móvil con modo offline (`CRM-04.04.01.03`)

Trabajar sin red obliga a tres cosas, y ninguna es opcional.

**Identificadores generados en el dispositivo.** El móvil crea el `id_cliente`
antes de tener cobertura. Reenviar el lote —porque se cortó a mitad— no vuelve a
aplicar nada. Sin esto, el técnico que sincroniza dos veces consume la pieza dos
veces.

**El reloj del móvil se guarda, pero no manda.** Va mal: zona horaria equivocada,
hora cambiada a mano. Se guarda `capturado_at` tal cual junto al `recibido_at` del
servidor, porque aun mintiendo es el único que sabe cuándo se hizo el trabajo — y
el trabajo consta hecho cuando dijo el móvil, no cuando llegó la red.

**Los conflictos se devuelven, no se resuelven.** Si alguien tocó la orden en la
oficina mientras el técnico trabajaba sin red, ni se pisa lo del servidor ni se
tira lo del técnico: se devuelve el conflicto y lo decide una persona. Elegir
automáticamente significa perder trabajo de alguien en silencio, y en campo eso es
media jornada.

Y un cambio que no se puede aplicar **no tumba el lote**: el técnico trajo seis
horas de trabajo, y perder las cinco buenas por una mala es exactamente lo que
hace que se deje de sincronizar. La respuesta dice, por cada cambio, si quedó
aplicado, duplicado, en conflicto o rechazado — y `todo_aplicado` solo es cierto
cuando no queda nada pendiente de decidir.

### Repuestos y stock de furgoneta (`CRM-04.04.01.04`)

El vocabulario de movimientos es el mismo que el del inventario de contecpos
—carga, consumo, devolución, ajuste, merma— en vez de uno nuevo: dos formas de
decir lo mismo se pagan el día que hay que cuadrar con el almacén central.

**No se bloquea por falta de stock.** Si el técnico dice que ha montado la pieza,
la pieza está montada: lo que está mal es el stock. Se registra el consumo, el
saldo queda en negativo y se marca — y esa es exactamente la lista que hay que
revisar. Impedirlo hace que la pieza se monte y no se apunte, y entonces se
pierden el stock **y** el histórico.

El ajuste **fija** el saldo en vez de sumarlo, que es lo que se hace al recontar la
furgoneta, y exige motivo: un inventario que se ajusta sin explicación es una
opinión. Y la lista de reposición dice **cuántas referencias no tienen mínimo
puesto**: con el mínimo a cero nunca se pide nada, la lista sale vacía y parece que
todo está bien.

### Mantenimiento preventivo (`CRM-04.04.01.05`)

Va **por fecha y por uso**, lo que antes llegue. Un plan que solo sabe de fechas
revisa una máquina parada y deja pasar la que trabaja a tres turnos.

Se dice **por cuál de las dos** vence, porque cambia la conversación con el
cliente: una es «toca la revisión anual» y la otra es «esta máquina ha trabajado el
doble de lo previsto». Un plan que mide por uso y cuyo activo no tiene lectura
sale como **no concluyente** — callarlo haría creer que está al día.

Se genera **una orden por plan a la vez**: un plan mensual desatendido seis meses
generaría seis órdenes idénticas, y lo que se hace entonces es cerrarlas todas sin
mirar. Y al cerrarla, el plan se reprograma **desde que se hizo**, no desde que
tocaba: si no, la siguiente nace vencida y el plan arrastra el retraso para
siempre.

### Partes, checklists y evidencias (`CRM-04.04.01.06`)

Un checklist con ítems **obligatorios sin responder no cierra**, salvo que se
fuerce: uno que se puede dejar a medias se deja a medias, y entonces no vale ni
como control ni como prueba.

Las fotos se guardan como **referencias al gestor documental**, no como binarios:
cinco fotos por visita y veinte visitas diarias convierten el esquema del servicio
en un almacén de imágenes sin retención ni antivirus.

Al completar, el parte se escribe **en el historial del activo en ese momento**
(`CRM-04.04.02.04`), y una vez firmado queda bloqueado: lo que se firmó tiene que
seguir diciendo lo mismo. Para corregir, se abre una orden nueva.

## Activos instalados (`CRM-04.04.02`)

Un activo instalado es **la máquina que el cliente tiene puesta**, no el producto
que se le vendió. La diferencia parece de matiz y es la que decide si una llamada
se puede atender: el producto dice qué se compró; el activo dice qué hay en esa
nave, con qué número de serie, desde cuándo y quién lo ha tocado.

### Registro e identificación (`CRM-04.04.02.01`)

**El número de serie identifica, y por eso no se repite.** Dos activos vivos con
la misma serie significan que alguien sustituyó una máquina y no lo registró; si
el sistema lo admite en silencio, el historial de la nueva arrastra averías de la
vieja y la garantía se calcula sobre la fecha equivocada. La serie sí se puede
reutilizar cuando el anterior está retirado, que es el caso legítimo.

Dar de alta **sin** serie se permite y se avisa: un técnico que da de alta una
máquina desde casa del cliente no siempre la tiene a mano, y bloquearle el alta
hace que no la dé.

El contador de uso —horas, ciclos, kilómetros— es lo que permite el preventivo por
uso. Una lectura que **baja** se acepta y se marca: puede ser un cambio de placa o
un error de lectura, y las dos cosas hay que verlas; rechazarla haría que el
técnico no anotara nada, que es peor que las otras dos.

Retirar exige motivo: sin él, el parque instalado mengua sin que nadie sepa si se
cambió, se perdió o se dio de baja el cliente.

### Jerarquía de activos y componentes (`CRM-04.04.02.02`)

Los componentes **se mueven**: un compresor sale de una máquina y entra en otra. Si
al moverlo se pierde de dónde venía, el análisis de fiabilidad —«este modelo de
compresor falla a los dos años»— deja de poder hacerse, que es una de las dos
razones para tener activos. El movimiento se anota en los dos: en el componente y
en el equipo que lo perdió.

Un ciclo se rechaza **al crearlo**, no al recorrer el árbol: si no, el fallo
aparece en un sitio que no tiene nada que ver. Y el recorrido lleva tope de
profundidad, porque un ciclo colado por una carga directa a la base colgaría la
consulta.

### Garantías y cobertura (`CRM-04.04.02.03`)

La cobertura se guarda **por concepto** —piezas, mano de obra, desplazamiento—
porque eso es lo que se discute en la puerta del cliente: casi ninguna garantía
cubre el viaje, y la conversación siempre es esa. Una garantía que no declara qué
cubre no se guarda.

**Sin garantía registrada no se dice que no hay cobertura: se dice que no se
sabe.** Son cosas distintas — una manda factura al cliente y la otra manda mirar
el contrato—, y un `false` por ausencia de datos factura a quien sí tenía
cobertura. Esa factura llega antes que la corrección.

El **tope de uso** corta antes que la fecha: dos años **o** cuatro mil horas, lo
que antes pase. Sin él, una máquina a triple turno sale cubierta el doble de lo
pactado. Y cuando dos garantías cubren lo mismo gana la más específica —contrato
sobre extensión sobre fabricante— y, con empate, la que dura más: declarado, no por
orden de inserción, que cambiaría al restaurar una copia.

### Historial por activo (`CRM-04.04.02.04`)

El historial es **append-only y se escribe en el momento**. Si se reconstruyera
consultando las órdenes de trabajo, editar una orden reescribiría el pasado del
activo y borrarla lo borraría. Lo que pasó, pasó — aunque después se corrija la
orden que lo originó.

Al sustituir un equipo, los dos quedan **enlazados** y el historial recorre la
cadena hacia atrás: la pregunta real del técnico no es «¿qué le pasó a esta
máquina?», es «¿esto ya había fallado antes?», y la respuesta suele estar en el
equipo anterior. Lo que viene de él sale **marcado**, porque contarlo como propio
inflaría su tasa de avería.

Las garantías **no se heredan** en una sustitución salvo que se pida: heredarlas en
silencio daría cobertura a una máquina que nadie aseguró, y quien pague la
reparación lo descubrirá al reclamar al fabricante.

## Postventa y logística inversa (`CRM-04.05.01`)

Lo que devuelve un cliente es la parte del negocio que peor se lleva, y siempre
por lo mismo: **el material vuelve y nadie sabe dónde está, ni quién autorizó qué,
ni qué se le prometió**.

### Devoluciones con autorización (`CRM-04.05.01.01`)

Una devolución se **autoriza**, y la autorización tiene número. Sin RMA, el
paquete llega al almacén sin remite reconocible y se queda en una estantería hasta
que alguien pregunta; con RMA, el almacén sabe qué espera, de quién y por qué.

El motivo es obligatorio y **normalizado**: «no me gusta», «llegó roto» y «no es
lo que pedí» llevan a disposiciones distintas del material, y en texto libre no se
pueden agrupar ni al cabo de un año.

Sin fecha de compra **no se dice que esté fuera de plazo**: se dice que no se sabe.
Darlo por fuera rechaza devoluciones legítimas por un dato que falta en nuestro
sistema, no en el del cliente. Y fuera de la ventana **se puede autorizar con
motivo**, quedando marcado como excepción: es una decisión comercial legítima y
frecuente, pero si pasa en silencio la ventana no significa nada y nadie puede
medir cuánto se está regalando.

Al recibir se anota **lo que ha llegado de verdad** y se devuelven las diferencias
con lo autorizado. Es el dato que se pierde siempre: se autorizan tres unidades,
llegan dos, y la tercera aparece meses después en un descuadre de inventario que
nadie sabe explicar.

**La disposición es obligatoria al cerrar.** Reacondicionar, reparar, chatarra o
devolver al proveedor: es lo único que impide que el material desaparezca del
mundo. Una devolución cerrada sin disposición es una pieza que consta devuelta y
que nadie ha vuelto a ver. Si lo devuelto era un activo instalado y se va a
chatarra o al proveedor, **se retira del parque del cliente**; si no, el CRM
seguiría contando una máquina que está en nuestro almacén o destruida.

Una serie que no consta como activo instalado **se avisa, no se bloquea**: puede
ser material que nunca se dio de alta, y puede ser una serie que no es nuestra.

### Reparaciones, sustituciones y abonos (`CRM-04.05.01.02`)

**El abono lo emite quien factura, no el CRM.** Aquí se registra la decisión, el
abono queda en `solicitado` y se espera la confirmación del ERP, igual que con los
pedidos. Un CRM que se inventa un abono deja dos contabilidades y la que se mira
es la otra; y la devolución **no se cierra con un abono pendiente**, porque
cerrarla dejaría al cliente esperando un dinero que nadie ha emitido.

Un abono rechazado guarda **por qué**: sin eso, alguien lo vuelve a mandar igual y
vuelve a rebotar.

Resolver dos veces la misma línea —repararla y abonarla— se avisa: es un error de
tramitación que acaba en la factura del cliente, y aquí todavía se puede deshacer.
Y «a cargo de» va aparte del importe: cliente, garantía o cortesía es lo que
decide si esto va a una factura o a una reclamación al fabricante.

### Reclamaciones con plazos legales (`CRM-04.05.01.03`)

Un plazo de ley no es un SLA comercial: no se amplía porque haya mucho trabajo, y
el que vence sin contestar se pierde.

El plazo cuenta **desde que entró la reclamación**, no desde que se grabó en el
sistema. Esa diferencia es el tiempo que estuvo en un cajón, y se la come la
empresa, no el cliente — por eso se guardan las dos fechas y se avisa de los días
ya consumidos.

Se declara si es en días **naturales o hábiles**, porque la diferencia son
semanas. Sin calendario laboral configurado se cuentan naturales **y se dice**:
dejar que parezca lo mismo es cómo un plazo de «diez días hábiles» vence en
Navidad sin que nadie lo entienda.

**La suspensión exige un motivo tipificado** —subsanación, prueba pericial,
traslado a un tercero, acuerdo con el cliente—. Con texto libre, el plazo se
suspendería por «mucho trabajo» y dejaría de ser un plazo. Al reanudar, el
vencimiento **se desplaza** lo que estuvo parado: dejarlo donde estaba haría que
una suspensión legítima de una semana se comiera el plazo de respuesta.

Al responder se calcula y se guarda **si se llegó a tiempo**, en ese momento y no
después: el vencimiento puede desplazarse por una suspensión posterior, y entonces
un incumplimiento se convertiría en cumplimiento sin que nadie lo decidiera. Y se
dice si es **demostrable**: sin acuse de recibo, «contestamos en plazo» es nuestra
palabra contra la suya.

La lista de vencimientos separa **los que vencen pronto de los ya vencidos**:
mezclarlos hace leer el incumplimiento como una cola de trabajo, y ya no se puede
evitar, solo explicar.

## Problemas e incidentes masivos (`CRM-04.01.01.11`)

El caso maestro ya permitía colgar cien llamadas de una caída y cerrarlas juntas.
Lo que faltaba es lo que viene después: **la caída se arregla y la causa sigue
ahí**.

**Problema e incidente son cosas distintas.** El incidente es «está caído ahora»;
el problema es «se cae cada tres semanas». Fundirlos hace que, al restablecer el
servicio, se cierre también la investigación — y la siguiente caída empieza de
cero con la misma gente buscando lo mismo.

**Un apaño se declara apaño.** El apaño y la solución definitiva son dos campos, y
el problema **no se resuelve con el primero**: cerrarlo con «reiniciamos el
servicio» lo hace desaparecer de la lista y volver dentro de tres semanas con otro
nombre. Con causa identificada y apaño, el problema pasa a **error conocido**, que
es lo que permite que quien coge la llamada 101 sepa qué contestar.

**La correlación propone, no agrupa.** Mira coincidencias —misma categoría, misma
línea, misma ventana de tiempo— y sugiere. Agrupar automáticamente cien casos que
no eran lo mismo le da a cien clientes una respuesta que no tiene que ver con su
problema, y eso no se deshace: ya la han leído. La coincidencia es deliberadamente
tosca, porque una más lista acierta más y se explica peor.

Desvincular un caso **exige motivo**: casi siempre significa que era otra cosa, y
eso es información sobre la causa. Los desvinculados siguen viéndose en el
impacto — si no, nadie sabría que la correlación se equivocó veinte veces.

Y las comunicaciones se registran **con su alcance**: en un incidente grande, «ya
avisamos» sin fecha ni destinatarios es lo mismo que no haber avisado, y es lo
primero que pregunta un cliente grande al día siguiente.

## Telemetría de dispositivo (`CRM-04.04.02.05`)

Un equipo que avisa antes de romperse es la promesa de todo el IoT industrial, y
donde casi siempre se estrella es en el volumen: una máquina manda una lectura cada
diez segundos, mil máquinas son ocho millones de lecturas al día, y un CRM que abra
un caso por cada una deja de servir para atender clientes en una tarde.

**No se guarda todo**: solo lo que cruza un umbral. Guardar la serie completa
convierte el CRM en una base de datos de series temporales que no es y contra la
que no puede competir.

**El caso lo abre `service`, no el módulo de integración.** `integration` no
escribe en el esquema de atención: manda un **comando** por el bus y el dueño del
objeto decide, aplicando su taxonomía, su SLA y su enrutamiento. Por eso la
respuesta dice que el caso está **pedido**, no creado: lo crea el otro servicio y
puede rechazarlo.

**Un aparato que se vuelve loco no abre mil casos.** Cada regla tiene ventana de
silencio y repeticiones: un pico de un segundo no es una avería, y superado el
primer aviso lo siguiente se agrupa y se cuenta. Sin eso, la primera avería real de
una flota tumba la cola de soporte y alguien apaga la regla entera.

**Dejar de recibir es una señal.** Un sensor averiado no dispara ninguna alerta
porque no manda nada, y así lleva tres días sin que nadie lo mire. Se detecta
comparando con la cadencia declarada, y los que **nunca** dieron señal salen
aparte: un aparato roto y uno sin instalar no son lo mismo. Los que no declaran
cadencia no se cuentan como sanos: se cuentan aparte, y el informe deja de ser
concluyente.

Las condiciones se validan **al guardar la regla**: un operador mal escrito no
falla, deja de disparar en silencio — y de una regla que no salta nunca nadie
sospecha, porque «no ha habido averías».

## Prueba de entrega y documentos del proveedor (`CRM-00.04.05.05`)

El albarán firmado, la foto de la entrega o el POD del transportista **se enlazan
al encargo, no se copian** (RT-5): el documento vive en el corpus documental, con
su retención, su antivirus y sus permisos. Guardar aquí el binario daría dos copias
que divergen, y la del CRM sin política de borrado.

Importa por una razón concreta: cuando el cliente dice que no le llegó, lo que se
enseña es eso. Por eso hay una lista de **entregados sin prueba archivada**, que
hay que mirar *antes* de que llame — luego ya no se puede pedir al transportista,
porque casi todos la conservan unas semanas y después la borran.

## Modelo canónico y sincronización bidireccional (`CRM-00.03.04.09`, `CRM-00.03.04.08`)

Con dos sistemas conectados hace falta un mapeo; con seis hacen falta quince, y ahí
es donde las integraciones dejan de mantenerse.

**El modelo canónico es el idioma común**: cada sistema traduce solo a él y desde
él, y las traducciones pasan de N×(N−1) a 2N. Y **es del tenant, no del código**:
cada empresa llama a las cosas a su manera, y un canónico fijo obliga a meter lo
propio en un `extra` que nadie mapea, que es donde acaba el dato que importa.

Un mapeo a un campo que no existe **se rechaza al guardarlo**: un campo mal escrito
no falla, deja de sincronizarse en silencio y se descubre meses después con los
datos ya divergidos. Lo que el sistema externo manda y no está mapeado se devuelve
**aparte**: es la lista con la que se descubre que el cliente añadió un campo nuevo
en su ERP y nadie se enteró.

La sincronización bidireccional añade el problema de verdad: **los dos lados
cambian a la vez**.

La política de conflicto se declara **por campo si hace falta**. «Gana el último»
no vale para todo: el correo que corrigió el comercial no puede perder contra una
carga masiva del ERP de las 3:00. Las cuatro —gana el nuestro, gana el suyo, gana
el más reciente, páralo y que lo mire alguien— cubren los casos reales, y ninguna
es el valor por defecto sensato para todos los campos.

**Sin marca de tiempo comparable no se decide por tiempo.** Muchos sistemas no la
dan, o la dan en su zona horaria sin decirlo; aplicar «gana el más reciente» sobre
una fecha que no se puede comparar es echarlo a suertes y presentarlo como una
regla. Se para y se deja para revisión.

**Un eco no es un cambio.** Lo que acabamos de escribir allí nos vuelve como
novedad suya; sin detectarlo, los dos sistemas se rebotan el mismo dato para
siempre, cada rebote con su llamada de API y su registro de auditoría. Se guarda la
huella de lo último escrito y lo que vuelve igual se ignora, diciéndolo.

Un campo que cambió **en un solo lado no es un conflicto**: es un hueco, y se
propaga. Y el mismo conflicto repetido **se cuenta, no se duplica**: uno que vuelve
cada hora significa que alguien escribe en los dos lados a la vez, y eso se arregla
cambiando la política, no resolviéndolo cien veces.

Mientras hay un conflicto abierto, el vínculo queda **parado**: seguir
sincronizando lo demás dejaría el registro mitad de uno y mitad de otro, que es
peor que tenerlo parado y visible.

## Campo y postventa en la interfaz (`CRM-07.04.03.20`, `CRM-07.04.03.21`)

En la pantalla de campo, el **preventivo va por delante de los repuestos**: los
vencimientos se miran cada semana y los repuestos solo cuando falta uno. Junto a
ellos, los aparatos que han dejado de dar señal, que es la avería que no se ve.

En postventa, los expedientes salen **ordenados por vencimiento** y los ya vencidos
en su propia lista: un plazo legal no es una cola de trabajo, es una fecha que se
pasa. Y los problemas enseñan `solo_apano` como columna, para que se vea de un
vistazo cuáles están tapados y no resueltos.

## Analítica avanzada (`CRM-05.01.03`)

### Almacén analítico separado (`CRM-05.01.03.01`)

La primera regla de la analítica en un CRM es que **no puede degradar el CRM**.
Una consulta de dirección que recorre tres años de oportunidades bloquea la misma
tabla en la que un comercial está guardando la suya, y lo que se nota es que «el
CRM va lento por las mañanas» — que es cuando se sacan los informes.

El almacén es **otro sitio**, y se alimenta por cargas declaradas: cada servicio
entrega sus filas, nadie lee el esquema de nadie. Las columnas se declaran, y lo
que no encaja **se descarta y se cuenta** en vez de entrar a medias: una fila con
la mitad de los campos produce un informe que suma mal sin que nadie sepa por qué.

Cada fila trae su **clave de origen**, y eso es lo que hace la carga idempotente.
Sin ella, repetir una carga duplica las filas y todos los recuentos salen al
doble.

Y todo lo que se sirve **dice de cuándo es**. Una tabla se marca obsoleta al doble
de su frecuencia declarada —una carga perdida es normal, dos seguidas ya no— y el
informe de frescura dice si los paneles son de fiar. Una tabla que no se ha
cargado nunca no pasa por fresca.

### Exportación continua al almacén del cliente (`CRM-05.01.03.02`)

El destino se declara con su tipo, y el tipo **no cambia el comportamiento**: lo
que cambia es la configuración. Si el tipo decidiera algo, volveríamos a tener
código por proveedor.

La lista de tablas que salen es **obligatoria**: exportar «todo» por defecto saca
datos personales a un sitio que quizá no está preparado para tenerlos, y eso no se
deshace.

Se **prepara, no se envía**: el envío lo hace quien sabe hablar con ese almacén.
Lo que este módulo garantiza es qué sale y desde dónde — y la **marca de agua solo
avanza cuando el envío se confirma**. Avanzarla antes es cómo se pierde un día
entero de cambios sin que nadie lo note: el sistema siguiente cree que ya lo tiene.
Con error no se avanza nada y se guarda el porqué.

Cuando el lote sale lleno **se dice que hay más**: quien envía tiene que volver a
llamar, y si no lo sabe deja la mitad sin mandar creyendo que terminó.

### Modelo semántico y métricas certificadas (`CRM-05.01.03.03`)

Lo que esto resuelve no es técnico: es que **«ingresos» significa cinco cosas
distintas** en la misma empresa. El de ventas cuenta lo firmado, el de finanzas lo
facturado, el de dirección lo cobrado, y los tres llevan su cifra a la misma
reunión. Nadie miente; nadie usa la misma definición.

Una métrica es un **plan, no SQL** —igual que en el motor de informes—, con su
definición **en palabras**, que es lo único que distingue «ingresos firmados» de
«ingresos cobrados» para quien lee el panel y no va a mirar el plan.

Nace **en borrador**: una métrica que nace certificada no la ha revisado nadie.
Certificar **exige dueño**, porque una métrica que nadie responde no se puede
corregir cuando falla — y entonces alguien crea otra al lado, que es como se llega
a las cinco definiciones.

Cambiarla crea una **versión nueva, con motivo**, y la anterior queda consultable:
los informes de hace tres meses se hicieron con la definición de entonces, y
reescribirla en sitio haría que un número publicado cambiara solo. Se puede pedir
el plan de una versión concreta, que es lo que permite reproducir aquel informe en
vez de recalcularlo con otra definición y decir que es el mismo número.

Agrupar por una dimensión que no forma parte de la definición **se rechaza**: da
un número que no es esa métrica. Y las no certificadas **se sirven igual, marcadas**:
prohibirlas haría que se calcularan en una hoja aparte, que es justo lo que se
quiere evitar.

### Cohortes y retención (`CRM-05.01.03.04`)

Un periodo que **aún no ha terminado** no cuenta como caída: la cohorte de este
mes no ha tenido tiempo de volver, y marcarla al 0 % la pinta como un desastre que
no ha pasado. Sale como `inmaduro`.

Una cohorte **pequeña no da porcentaje**: con tres clientes, uno que se va es un
−33 % que se lee como un desplome. Se devuelve el recuento y se dice que no es
significativa — y los dos motivos para no dar porcentaje se distinguen, porque uno
se arregla esperando y el otro no se arregla.

La retención se mide **contra la propia cohorte**, no contra el total: si no, una
cohorte grande parecería mejor que una pequeña aunque se comportaran igual. Y los
sujetos sin fecha de alta se cuentan aparte: meterlos en la primera cohorte sería
inventarse su origen.

### Embudo multi-etapa (`CRM-05.01.03.05`)

**Lo abierto no cuenta como perdido.** Una oportunidad que está en la etapa 3 no ha
fallado en la 4: todavía no ha llegado. Contarla como caída hunde la tasa de las
etapas finales y hace parecer que el equipo cierra peor de lo que cierra.

El tiempo entre etapas es la **mediana, no la media**: un solo negocio de dos años
mueve la media de todo el trimestre y hace irreconocible el dato. Y se devuelve la
**mayor caída**, porque la pregunta que sigue a «¿cómo va el embudo?» es siempre
«¿dónde se atasca?».

### Actividad y resultados (`CRM-05.01.03.06`)

Se devuelve la correlación **con el aviso de que no es causa, junto al número**:
quien lee el panel no va a leer la documentación. El comercial que cierra más hace
más llamadas porque tiene más clientes interesados; exigir el mismo número de
llamadas al resto infla la actividad sin mover los cierres, y un CRM que presenta
esta cifra como una instrucción hace daño real.

Con **pocos sujetos no se calcula**: con cinco comerciales, un valor atípico da
0,9 o −0,3 según quién esté de vacaciones. Y si no hay variación, **no hay
correlación**: devolver cero se leería como «no influye», que es otra cosa.

Lo accionable son los **atípicos**: quien hace mucho y cierra poco necesita ayuda
con la cualificación, no con el teléfono.

### Consulta federada contra el lake del cliente (`CRM-05.01.03.07`)

Se declara contra qué lake se pregunta y **qué objetos** se pueden consultar: sin
esa lista, una consulta federada puede leer el lake entero del cliente con nuestra
credencial, que es lo que nadie autorizó al conectar la cuenta.

Se devuelve un **plan, no SQL** (RT-4), con tope de filas y de tiempo — una
consulta federada mal hecha no se cancela sola y se lleva por delante el
presupuesto del lake, que lo paga el cliente. Si el tope recorta, **se dice**: un
resultado recortado en silencio se lee como completo.

Y se dice lo que **no** se puede hacer: cruzarlo con tablas del CRM en la misma
consulta exigiría traer una de las dos, que es copiar con otro nombre. Dejar que
alguien lo descubra con una consulta que no termina es peor que decirlo.

## Explotación en contexto y despliegue de BI (`CRM-05.01.04.09`, `CRM-05.01.04.10`)

Preguntar «¿cómo va esta cuenta?» desde la ficha abierta tiene que acotar solo.
Sin eso, la explotación en contexto no se usa: nadie copia un UUID a mano.

El filtro **se añade, no se sugiere** —si el otro lado pudiera ignorarlo, la
respuesta traería datos de todas las cuentas mientras el usuario cree que pregunta
por una— y **se devuelve visible**, porque un número que parece de toda la empresa
y es de una cuenta se lleva a una reunión y allí no cuadra con nada. El objeto se
valida contra el modelo publicado: preguntar en el contexto de algo que la fuente
no conoce daría un filtro ignorado en silencio.

Sobre el despliegue: contecintelligence es una **dependencia**, no un extra. La
pila lo levanta con el perfil `bi`, o se apunta con `CI_BASE_URL` a uno ya en
marcha —lo normal en una instalación con varias soluciones de la casa—. Las dos
valen; lo que no vale es no saber cuál está en uso, porque entonces nadie sabe a
quién reiniciar cuando los informes dejan de salir. El estado dice en qué modo
está, y avisa si en producción apunta al servicio del compose sin haberlo
levantado.

## Resolución de identidad entre canales (`CRM-01.01.05.02`)

La misma persona llega como correo, como teléfono, como cookie y como referencia
del ERP. Sin resolverlo, el CRM tiene cuatro fichas de una persona y ninguna sabe
lo que hicieron las otras — que es justo lo que deja las interacciones entrantes
sin atribuir.

Y resolver identidades es peligroso por lo que se rompe al hacerlo mal: **unir dos
personas distintas es peor que no unirlas**, porque alguien ve el historial de otro
cliente y eso no se deshace aunque se deshaga la unión.

**Hay señales fuertes y débiles.** Un NIF o un identificador de ERP identifican; un
fijo de oficina lo comparte media planta. Cada tipo declara su peso, y el criterio
es simple: pesa lo que no comparten dos personas distintas. **El nombre no une
nada** — «García» hay miles—, y se guarda solo para poder explicar una propuesta.

**Una señal compartida pesa menos, no más.** Un teléfono que aparece en cinco
fichas no identifica a ninguna: su peso se reparte. Sin esto, la centralita de una
empresa uniría a toda su plantilla.

**Dos candidatos casi empatados no resuelven.** Elegir uno sería jugársela a cara o
cruz con el historial de un cliente. Y por debajo del umbral **se propone, no se
afirma**.

**Nada se une solo.** Las propuestas se revisan; y una unión automática, si algún
día se activa, pide una puntuación mucho más alta que una manual — quien une a mano
está mirando las dos fichas y un proceso nocturno no mira nada.

**Unir es reversible y deja rastro**: qué señales lo justificaron y quién lo
aprobó. Deshacer **exige motivo**, porque si la regla vuelve a proponer el mismo
par, ese texto es lo único que explica por qué estaba mal.

Las señales se guardan **con huella y pista, no en claro**: una tabla de
identidades es un índice de todos los correos y teléfonos del CRM, y para saber de
cuál se habla basta con «termina en 4321».

## IA generativa (`CRM-05.02.02`)

La IA en un CRM es útil por lo mismo que es peligrosa: hace en un segundo lo que
una persona tardaría una tarde, y con los datos de clientes delante. Todo este
módulo está construido alrededor de esa frase, y vive en un servicio propio
—`intelligence`— para que apagarlo no toque nada más.

### Qué modelo, dónde y con qué límite (`CRM-05.02.02.10`, `CRM-05.02.02.09`)

La primera pregunta de un comité de compras no es qué sabe hacer: es **dónde se
procesan mis datos y quién los usa después**.

El modelo se elige **por tenant**: una empresa exige que todo se quede en la UE,
otra tiene su propio modelo en su infraestructura y una tercera quiere el más
barato. Los tres son el mismo producto con configuración distinta. Un proveedor
declarado **solo para un tenant** es su modelo, en su casa, y gana siempre.

**La región es una condición, no una preferencia.** Si el tenant declara que sus
datos no salen de la UE y el modelo está fuera, **no se llama**. Llamar igual y
anotarlo en una traza es contarle después a alguien que sus datos ya salieron.

**Y las regiones son las mismas que firma su residencia.** Hasta el 28-10-2026
eran dos listas distintas, y eso tenía dos consecuencias. Un cliente podía
firmar residencia en **LATAM o APAC** y la política de IA no sabía escribir esas
regiones: le contestaba «región no reconocida». Justo el cliente que más
necesita el modo «el dato no sale de aquí» era el único que no podía pedirlo. Y
al revés, un tenant podía admitir la región **«otra»**, que en un proveedor
significa *no consta dónde está*: el modo sin salida de datos elegía entonces un
proveedor de paradero desconocido y lo anunciaba como «la misma región del
tenant». Ahora la lista se escribe una vez: **«otra» describe a un proveedor y
no se puede prometer**, y lo que el cliente firma es exactamente lo que la IA
puede cumplir.

**El opt-out de entrenamiento se exige por defecto y viaja en cada petición.** No
basta con haberlo firmado: la garantía que se le da al cliente es técnica. Si el
proveedor configurado no lo admite, se descarta — y se dice cuál de las
condiciones lo impide, porque un «no disponible» a secas manda a revisar la
conexión cuando el problema es el contrato.

**Sin presupuesto no hay llamada**, y se comprueba antes: comprobarlo después es
descubrir que ya se gastó, y la factura llega igual. Sin tope declarado no se dice
que quede mucho: se dice que **no hay tope**, que es lo que alguien tiene que
decidir.

Y hay **interruptor por tenant**: corta toda la IA sin borrar configuración,
porque el día que algo va mal lo que se quiere es parar ahora y decidir después.

#### Tres familias, no veinte conectores

Cada proveedor declara su **formato**, que es cómo habla: `openai_chat`,
`anthropic_messages` o `gemini_generate`. Azure, groq, mistral, deepseek,
together y los demás clones hablan el primero, así que declararlos uno a uno
sería la lista escrita a mano que se queda corta en cuanto aparece el séptimo.
Lo que se declara es el dialecto y la dirección; la credencial, la versión de la
API y cualquier otra cabecera que exija el proveedor son configuración suya.

El formato **se valida al declararlo**, igual que la región: hasta el 28-10-2026
era texto libre, así que «openai» o «Anthropic» se guardaban perfectamente y la
llamada salía en el dialecto equivocado meses después.

Dos cosas que cambian entre familias y se notan en la respuesta, no en la
llamada, así que se dicen en vez de simularse:

- **El modo JSON** existe en dos de las tres. En la familia Anthropic el JSON se
  pide por el texto del sistema y puede venir envuelto, y el servidor lo avisa.
- **El opt-out** tiene un campo estándar sólo en la familia OpenAI (`store`). Un
  proveedor de otra familia que diga admitirlo **tiene que declarar en qué campo
  se pide**; si no lo declara, la llamada se para. Mandarla sin el campo sería
  dar por buena una garantía que no viaja.

### Guardarraíles (`CRM-05.02.02.07`)

El agujero de la IA en un CRM no es que el modelo diga tonterías: es que **le
enseñe a alguien lo que no puede ver**. Un resumen construido con documentos que
el usuario no podía abrir es una fuga elegante: sale redactada, sin fuente, y
nadie puede reconstruir de dónde salió.

**Los permisos se comprueban antes de recuperar el contexto**, no después de
generar: filtrar una respuesta ya redactada es imposible, porque el modelo ya
mezcló lo que podía con lo que no y quitar una frase no quita lo que implicaba. Un
fragmento **sin permiso declarado se descarta**: ante la duda no se enseña.

**Lo personal y lo especial no salen salvo declaración expresa**, y autorizarlo
avisa de que hace falta base legal y contrato. Además se **tapan patrones en el
texto libre** —IBAN, tarjeta, NIF, correo—, porque en una nota escrita a mano no
hay ningún campo que los declare.

Y lo que se quita **se dice**: una respuesta más corta sin explicación se lee como
que no había información. Los bloqueos se cuentan, con las dos lecturas que
importan y son opuestas: uno que salta mil veces al día estorba; uno que no salta
nunca tampoco protege.

### Redacción, resumen y traducción (`CRM-05.02.02.01`, `CRM-05.02.02.02`, `CRM-05.02.02.06`)

**La plantilla del prompt es un objeto versionado**, no una cadena en el código:
el día que los textos salgan raros, la primera pregunta será qué cambió, y
cambiarla exige decir por qué.

**Nada se escribe solo.** Lo generado es un **borrador**: alguien lo lee, lo
corrige y lo manda. Un correo enviado automáticamente con un dato inventado no se
puede retirar, y el modelo inventa —poco, pero inventa—.

**El idioma se decide, no se adivina**: contestar en castellano a un cliente
francés es el error más frecuente y el más caro de los baratos. Sin idioma
declarado, no se genera.

**Sin contexto suficiente no se llama al modelo.** Resumiría igual, y lo que sale
es plausible y vacío: cuesta dinero y engaña, que es la peor combinación.

Y se anota qué hizo la persona con el borrador —aceptar, editar o tirar—, porque
sin eso se sabe lo que cuesta la IA y no lo que vale. Lo descartado **no se
conserva**: es un texto sobre un cliente que nadie ha validado, y esos textos
acaban leyéndose como si fueran datos.

### Respuesta con citación y consulta en lenguaje natural (`CRM-05.02.02.03`, `CRM-05.02.02.04`)

Una respuesta sobre los datos del cliente **sin decir de dónde sale** no vale:
quien la lee no puede comprobarla, y cuando alguna esté mal no habrá forma de
saber si el fallo fue del dato o del modelo.

Por eso, **sin citas comprobables la respuesta no se presenta como buena**, aunque
el párrafo sea perfecto — un párrafo perfecto sin fuente es justo lo que escribe un
modelo cuando no encontró nada. Y **se comprueba que lo citado existía**: una cita
a un fragmento que no se pasó es una referencia inventada con la misma forma que
una buena.

Que el modelo diga **que no lo sabe es un acierto**, no un fallo: es la respuesta
más difícil de conseguir y la única que hace que las demás se puedan creer. Y «no
hay datos» se distingue de «no puedes verlos», porque solo uno se arregla pidiendo
permiso.

Para preguntar en lenguaje natural, **el modelo no toca la base de datos**:
traduce la pregunta a un **plan** —el mismo formato que compila el motor de
informes— y ese plan lo ejecuta quien tiene el dato, con los permisos de quien
pregunta. Y **el mismo formato quiere decir la misma gramática**: hasta el
28-10-2026 había dos listas de operadores, la del que propone y la del que
ejecuta, y no coincidían. El plan aceptaba «entre», que no lo ejecuta nadie —la
pregunta daba un plan válido y un número que no era el pedido—, y no podía
expresar «empieza», «vacío» ni «no vacío», que sí se ejecutan. Ahora la
gramática está escrita una vez y manda **lo que se puede ejecutar**: proponer
algo que nadie sabe hacer no es una funcionalidad a medias, es una respuesta
equivocada con buena presentación. Dejar que escriba SQL sería darle a un generador de texto acceso a
cualquier tabla, y ningún filtro posterior arregla eso. El plan **se valida contra
el modelo publicado** antes de devolverlo, y se devuelve **cómo entendió la
pregunta** en una frase: es lo que permite ver que preguntaste por «este
trimestre» y filtró por «este año» antes de llevarte el número a una reunión.

### Extracción estructurada (`CRM-05.02.02.05`)

Sacar campos de un correo o de un PDF es lo que más tiempo ahorra, y lo que más
daño hace si se aplica solo: un importe mal leído entra en una oportunidad, sale
en el forecast y llega a una reunión.

**Se propone, no se escribe**, y cada campo viene con su **cita literal** del
texto: sin ella no se puede comprobar, y comprobar es más rápido que buscarlo a
mano — que es todo el ahorro que esto promete. Una cita que no aparece en el texto
se descarta: es una referencia inventada.

**Lo que ya tiene valor no se pisa**: queda en **conflicto** y decide una persona.
El dato que estaba lo puso alguien, y una máquina no tiene autoridad para
corregirlo en silencio. Por eso los conflictos salen primero en la lista: son los
únicos donde equivocarse borra algo que ya existía.

**El esquema manda**: si el destino es una fecha y el modelo devuelve «el martes»,
la propuesta se marca como no convertible en vez de guardar basura con buena cara.
Y aceptar **pide** el cambio al servicio dueño por comando: escribir desde aquí
saltaría el metamodelo y las reglas de negocio para la IA y para nadie más.

### Trazabilidad y coste (`CRM-05.02.02.08`)

Cuando alguien pregunte «¿por qué el CRM escribió esto?» —a veces con un abogado
delante— la respuesta tiene que existir: qué tarea, con qué modelo, en qué región,
con qué plantilla y versión, quién lo pidió y de qué fuentes salió.

**El prompt se guarda por huella, no por texto**: guardarlo duplicaría dentro del
registro de auditoría todos los datos personales del CRM, y sin la retención de su
tabla de origen. Con la plantilla versionada y la huella se puede reproducir sin
duplicar.

**El coste va por llamada**, porque una factura mensual no dice quién gastó. Y
**lo que salió mal también se registra**: un módulo que solo apunta los aciertos da
una tasa de éxito del 100 %.

La llamada nace **pendiente**, no aceptada: marcarla aceptada al generarla
inflaría la tasa de descarte hasta dejarla sin significado, y ese es precisamente
el número con el que se decide si esto sirve. El consumo enseña las tres cifras
juntas —coste, descarte y bloqueos—, porque enseñar solo el coste hace que se
discuta el precio de algo cuyo valor nadie ha medido.

### El aviso de que se acabó el presupuesto, y el de que hay un borrador

**Para el usuario.** Cuando el gasto de IA del mes llega al tope que tiene puesto
su empresa, la IA deja de responder. Hasta ahora eso era todo lo que se veía: la
función desaparecía sin explicación, normalmente a mitad de mes y a mitad de
trabajo. Ahora el sistema **lo anuncia en el momento en que se cruza el tope**,
para que quien administra pueda subirlo o avisar antes de que nadie se choque
contra la pared.

Y cada borrador que deja la IA se anuncia igual, para que llegue a quien lo tiene
que revisar en vez de quedarse esperando a que alguien entre a mirar si hay algo
nuevo.

**Para quien administra.** El tope mensual se pone en la política de IA del
tenant (`presupuesto_mes`). Dos cosas que conviene saber:

- **Un tope de cero significa cero**, es decir, la IA queda parada. Antes se
  leía como «este tenant no tiene tope» y la IA seguía gastando sin límite:
  exactamente lo contrario de lo que se acababa de pedir. Para no tener tope, se
  deja **vacío**, que es cosa distinta de poner un 0.
- **El aviso sale una vez por mes, no una por llamada.** Una vez agotado, todas
  las llamadas siguientes siguen por encima del tope; repetir el aviso en cada
  una es cómo se deja de leer los avisos. El mes va dentro de la clave de
  deduplicación, así que el mes siguiente vuelve a avisar.

**Para mantenimiento.** Son `ai.budget.exhausted` y `ai.proposal.created`,
declarados en el Anexo B desde el principio. **No los emitía nadie**: quien se
suscribiera no recibía nada y lo habría descubierto esperando.

El de presupuesto se emite en `anotar_gasto`, donde se apunta el gasto, y **no**
en `exigir_presupuesto`, que es donde se nota. Ése lanza, y lo que se escriba
justo antes se deshace con la transacción: el aviso se perdería justo en el
momento en que hace falta. El de la propuesta lleva el identificador y la tarea,
**no el texto**: un borrador sobre la ficha de un cliente no tiene por qué viajar
por el bus hasta los catorce servicios para que uno lo muestre.

### El puerto hacia el modelo

Todo lo anterior funciona **sin saber que existe HTTP**. Lo único que habla con un
proveedor es un módulo pequeño y aparte, que traduce al formato declarado. Eso es
lo que hace que cambiar de proveedor sea configuración y no un módulo nuevo, y lo
que permite probar de verdad lo que importa: qué se manda y qué se hace con lo que
vuelve.

---

## Modelos predictivos (`CRM-05.02.01`)

Un predictor que siempre contesta algo es el que deja de usarse a los dos meses.
La primera vez que un comercial comprueba una puntuación y no se sostiene, deja
de comprobar las demás y vuelve a su intuición — con razón, porque él estuvo en
la reunión y el modelo no. Todo este capítulo está construido alrededor de eso:
**el sistema tiene que saber cuándo no sabe, y decirlo.**

### Gobierno de modelos (`CRM-05.02.01.07`, `CRM-05.02.01.06`)

Cada versión de modelo se registra con sus variables, sus métricas, el periodo de
datos con el que se entrenó y cuántos ejemplos vio. Y **no se activa sin
métricas**: sin ellas no se puede decir si la versión nueva mejora o empeora, y
entonces cada reentrenamiento es un salto de fe con las puntuaciones de todo el
mundo dentro.

Al activar se devuelve **la comparación con la versión que estaba**. Activar algo
peor es una decisión legítima —a veces se prefiere un modelo más simple— pero
tiene que verse; sin la comparación, un modelo peor se queda meses en producción
dando peores números sin que nadie lo note.

Cada tenant entrena **con sus propios datos** (`CRM-05.02.01.06`). No hay una
puerta trasera de «modelo global»: la tabla exige `tenant_id`, así que un modelo
no puede nacer sin dueño y colarse en el cliente de al lado.

Un modelo **caduca**. Entrenado con el mercado del año pasado sigue contestando
tan seguro como el primer día, así que pasada su vigencia deja de puntuar y se
dice por qué. Y la **deriva se mide contra lo que pasó de verdad**, no contra el
conjunto de entrenamiento: lo segundo solo demuestra que el modelo se acuerda de
lo que vio.

**Y desde el 28-10-2026 se puede mirar.** Hasta entonces había ruta para anotar
una medición y ninguna para verlas: se medía la deriva y no se miraba, que es lo
contrario de para lo que se mide. Está en la pestaña «Deriva de los modelos»,
con cada medición al lado de **su referencia y su caída** —un AUC de 0,71 no
dice nada solo y dice mucho junto al 0,86 con el que se entrenó— y con **cuántos
casos** se midió. Sin ninguna medición no se dice que el modelo acierte: se dice
que nadie lo ha comprobado, que es otra cosa. Por debajo de cien muestras la medición se marca como **no
concluyente**, porque treinta casos no dicen si el modelo se ha estropeado y
reentrenar por ruido es cómo se empeora un modelo que iba bien.

### Scoring con explicabilidad (`CRM-05.02.01.01`, `CRM-05.02.01.03`)

Cada puntuación viene con **los factores que la sostienen, ordenados por cuánto
empujaron, y en los dos sentidos**: lo que suma y lo que resta. «Esto puntúa 78
porque han abierto tres presupuestos y porque llevan dos semanas sin contestar»
es accionable; «esto puntúa 78» es un número de colores. Un scoring que solo
enseñara lo bueno convertiría a todos los leads en buenos leads.

Si al puntuar faltan variables que el modelo esperaba, **se puntúa y se avisa**:
en la ficha, una puntuación incompleta se ve igual de rotunda que una completa, y
quien la lea tiene que saber que es menos fiable.

La propensión y la siguiente mejor oferta (`CRM-05.02.01.03`) salen del mismo
mecanismo, con su modelo y sus variables: no hay dos motores de scoring, porque
dos motores acaban dando dos respuestas distintas a la misma pregunta.

### Predicción de cierre, importe y fecha (`CRM-05.02.01.02`)

Las predicciones se guardan **con caducidad**. Una probabilidad de cierre
calculada hace tres meses, con la oportunidad ya en otra etapa, es peor que
ninguna: nadie mira la fecha de un número que aparece en una ficha. Pasado el
plazo no se devuelve, y se dice que ha caducado en vez de callar.

Cuando se sabe qué pasó de verdad, se anota. Es lo que permite medir **el acierto
sobre lo ya cerrado** — y solo sobre eso: medir incluyendo lo que sigue abierto
daría un acierto altísimo, porque lo abierto no ha tenido tiempo de desmentir
nada. Con menos de veinte resultados conocidos, el acierto se declara **no
medible**.

### Forecast predictivo (`CRM-03.02.01.06`)

El forecast del modelo **no sustituye al del comercial: se pone al lado**.
Sustituirlo hace que el comercial deje de comprometerse con su número, y el
compromiso es la mitad del valor de un forecast — un modelo no puede llamar al
cliente para que firme antes de fin de mes.

Se devuelven los dos, la diferencia y de dónde viene cada euro. La banda se
calcula de forma explicable (lo que está por encima del 70 % y lo que está por
encima del 30 %) y **se dice que no es un intervalo estadístico**, para que nadie
la presente como tal. Y se declara **qué parte del pipeline no se ha podido
puntuar**: un forecast predictivo calculado sobre la mitad de las oportunidades
parece bajo y no lo es, y sin ese aviso alguien concluye que el trimestre va mal.

### Salud de cuenta y churn (`CRM-05.02.01.04`)

La salud se compone de **señales con nombre** —uso, soporte, relación, pago,
valor y patrocinador—, cada una con su peso configurable por tenant: en una
empresa de suscripción manda el uso del producto y en una de proyectos manda el
margen.

**Una señal sin dato no puntúa cero: no puntúa.** Contar «sin datos de uso» como
uso nulo hundiría a todos los clientes de quien todavía no ha conectado la
telemetría, y esa lista de críticos no la mira nadie dos veces. Se reparte el peso
entre las señales que sí han llegado y se dice cuánto del total quedó sin medir;
por debajo de la mitad, la medida se marca como **no fiable**.

Las cuentas poco fiables **no desaparecen** de la lista de riesgo: se cuentan
aparte. Si desaparecieran, una instalación a la que le falta la mitad de las
señales vería una lista corta y creería que va bien.

Y **riesgo no es churn confirmado**. La respuesta lo dice con esas palabras a
propósito, para que la lista no acabe usándose como una baja anticipada en una
reunión de dirección.

### Anomalías (`CRM-05.02.01.05`)

Un detector mal calibrado es peor que ninguno: avisa treinta veces, las treinta
son normales, y a la trigésimo primera —la que importaba— ya nadie abre el correo.

Por eso **sin línea base no hay anomalía**: por debajo del mínimo de
observaciones configurado se devuelve «no medible» con cuántas faltan, en vez de
un aviso que parece un hallazgo. Cada aviso lleva **su normalidad al lado**: «17
cuando lo habitual son 40±6» se entiende sin saber estadística; «z = 3,8» no.

Se avisa **en los dos sentidos**: un detector que solo mira hacia abajo deja pasar
el mes en que alguien cargó el pipeline por duplicado. Y **no se inventa la
causa**: se dice lo que se ve, y la explicación la pone quien conoce el negocio.

Cada aviso se puede marcar como acertado o falso. Es lo único que permite saber
después si el detector sirve: con menos de diez revisiones, la utilidad se declara
**no concluyente**, porque tocar los umbrales a ciegas es cómo se acaba con un
detector que no avisa de nada.

## Señales sobre la conversación (`CRM-04.02.02.06`, `CRM-04.02.02.07`)

Estas dos cosas se usan en caliente, con el cliente al otro lado, y por eso son
las más fáciles de estropear.

### Resumen al cerrar o al transferir (`CRM-04.02.02.06`)

Un resumen que se inventa un compromiso hace que el agente que recoge el caso
prometa algo que nadie dijo. Por eso **lo que quedó pendiente va en su propio
campo**: es lo que el siguiente agente lee primero y lo que más se inventa un
modelo, así que se revisa aparte en vez de tener que releer el resumen buscando
compromisos.

El resumen **se propone; no se escribe**. El caso vive en el servicio de soporte,
y este servicio no escribe en su esquema: se manda un comando y el estado que se
devuelve es **«pedido»**, no «hecho», porque el otro lado todavía puede
rechazarlo. Al llegar, se cuelga del caso como una anotación con su origen —nunca
como su resolución—, que es lo que permite meses después distinguir «esto lo
resumió la IA» de «esto lo escribió el agente».

Se guarda **sobre cuántos mensajes se hizo**: un resumen de cuarenta mensajes
hecho con los cinco últimos es un resumen del final, y quien lo lea sin saberlo
creerá que tiene toda la conversación. Lo que va al modelo pasa por los mismos
guardarraíles que cualquier otro contexto, porque una conversación de soporte
lleva datos personales por definición.

**Y los resúmenes se pueden leer.** Hasta el 28-10-2026 se escribían y ninguna ruta los devolvía: se generaban, se pagaban al proveedor de IA y se quedaban en una tabla sin puerta. Están en la pestaña «Resúmenes de conversación», con **los pendientes aparte** —lo que el siguiente agente lee primero y lo que más se inventa un modelo— y con **de cuántos mensajes salió y cuántos se usaron**: un resumen hecho con veinte de doscientos no es el mismo documento, y sin esos dos números los dos se leen igual.

### Sentimiento e intención (`CRM-04.02.02.07`)

Un «cliente enfadado» que salta cada vez que alguien escribe en mayúsculas enseña
al supervisor a ignorar el aviso justo antes del día que importa.

La clasificación viene **con confianza y con umbral**: por debajo del umbral la
respuesta es «no concluyente», no «neutro». Un neutro falso entra en las medias
del día y las aplana, y entonces el panel dice que todo va bien porque el
clasificador no se atrevía a decir nada. En la evolución de la conversación, las
no concluyentes no entran en la media pero **sí se cuentan**: si desaparecieran,
una conversación que el clasificador no entiende parecería una conversación
tranquila.

Las etiquetas son **listas cerradas**. Si el modelo devuelve «regulero», no
aparece una categoría nueva en el informe: la lista es cerrada precisamente para
que los paneles cuadren.

Y **nada se escala solo**. La señal devuelve `sugiere_escalar` con su porqué y las
palabras del cliente en las que se apoya; quién escala y cuándo lo decide una
regla del cliente con su umbral, y queda registrado. El campo
`escalado_automatico` va siempre a falso, dicho explícitamente, para que nadie
tenga que deducirlo del JSON.

---

## Consentimiento, derechos y cumplimiento (`CRM-02.04.02`, `CRM-07.03`)

Todo este capítulo existe para lo mismo: **poder demostrar algo dos años
después**. Lo que hace que un consentimiento valga no es la casilla, es saber
quién la marcó, cuándo, desde dónde y aceptando qué texto. Casi todos los
sistemas guardan el «sí» y tiran el resto, y entonces la prueba que se enseña
ante una reclamación es una fila que dice `acepta = true`.

### El registro de consentimiento (`CRM-02.04.02.01`)

Ya existía por finalidad y canal, con su base legal y su prueba, y **cada cambio
como una fila nueva**: la historia de consentimientos de una persona es lo que
demuestra que en el momento del envío había permiso. Lo que se le ha añadido es
lo que lo hace exigible —el doble opt-in, la caducidad y la propagación de la
baja—, porque un registro impecable que nadie consulta antes de enviar no ha
impedido nunca un solo correo.

### Limitación de tratamiento (`CRM-02.04.02.05`)

Es el derecho que casi nadie implementa y el que más problemas evita. Alguien
discute la exactitud de sus datos o se opone a un tratamiento, y mientras se
resuelve **no se pueden usar** — pero tampoco borrar, porque si al final tenía
razón hay que poder rectificarlos.

Lo que suele hacerse en su lugar es anotar «no contactar» en un campo de texto, y
eso dura hasta la siguiente importación.

- **Es una fila, no una casilla en la ficha.** Con su motivo, su fecha y quién la
  puso: eso sobrevive a una importación y se puede auditar.
- **Sin detalle se limita todo lo limitable.** Es lo que pide quien invoca el
  artículo 18 sin entrar en detalle; interpretar la lista vacía como «ninguno»
  registraría una limitación que no limita nada.
- **Se dice lo que NO para.** La ley permite seguir tratando para defender
  reclamaciones y para cumplir obligaciones legales. Prometer un bloqueo total
  sería prometer lo que el sistema no puede dar y la ley no pide.
- **Levantarla exige motivo.** Una limitación que desaparece sin rastro es peor
  que no haberla puesto: nadie puede decir desde cuándo se volvió a tratar.

Y sobre todo: **se avisa a quien envía**. La limitación que se queda en el
servicio que la anotó no limita nada, porque quien manda los correos es
`marketing` y no puede leer ese esquema. Viaja por evento con **las direcciones**
dentro, porque allí se suprime por dirección y no por identificador: la misma
persona suele estar en tres fichas duplicadas, y bloquear solo la que ejerció el
derecho deja que las otras dos le sigan escribiendo.

#### La baja se propaga a todos los canales y a lo que está en curso (`CRM-02.04.02.03`)

No sirve de nada dar de baja el correo si la campaña que ya está corriendo sigue
escribiendo. La supresión se aplica **por encima de cualquier segmento y de
cualquier recorrido**: si fuese una condición más, bastaría con que alguien
montara un segmento sin acordarse de ponerla.

Al levantarla no se quita cualquier supresión: una queja por spam o un rebote
duro no los levanta el fin de una limitación. Solo se retira la que puso la
propia limitación — si no, volver a escribir a quien nos denunció sería un efecto
colateral de otro trámite.

### Los seis derechos, ejecutados (`CRM-02.04.02.04`)

El registro de la solicitud con su plazo legal ya estaba, y también el acceso y
la supresión. Faltaban tres, y los tres son decisiones que **una persona tiene
que tomar** antes de que el sistema las ejecute:

- **Rectificación.** Qué campo y con qué valor no se deduce de una solicitud en
  prosa. Se guarda **lo que había antes**: sin el valor anterior, una
  rectificación es indistinguible de una edición cualquiera, y lo que hay que
  demostrar es justo que se corrigió lo que el interesado señaló. Solo campos de
  la persona: cambiar importes o estados desde aquí sería usar un derecho para
  saltarse las reglas de negocio.
- **Portabilidad.** Mismo contenido que el acceso, porque son los mismos datos,
  pero se dice **qué queda fuera**: cubre lo que el interesado aportó, no lo que
  la empresa dedujo sobre él. Entregar un scoring interno como «sus datos» regala
  el trabajo propio y da por bueno ante el interesado un juicio que nunca pidió.
- **Oposición.** Se traduce en una limitación de verdad, no en una nota.

### Doble opt-in y renovación (`CRM-02.04.02.02`)

Un alta sin confirmar **no es un alta**: quien pregunte si se le puede escribir
recibe que no. Registrarla como válida y mandar mientras tanto es peor que no
tener doble opt-in, porque da apariencia de rigor a lo contrario.

- **El enlace caduca.** Uno que vale para siempre acaba usándose meses después
  por alguien que ya no recuerda haberse apuntado.
- **Confirmar dos veces no falla pero no mueve la fecha.** La gente pincha el
  enlace otra vez; la fecha que prueba el consentimiento es la primera.
- **Hace falta el texto que se enseñó.** Sin él la prueba es una casilla marcada.
- **Lo caducado deja de valer solo.** El envío consulta la caducidad, así que la
  lista de renovaciones sirve para renovar a tiempo, no para seguir enviando
  mientras alguien la revisa.

### Cookies y rastreo (`CRM-07.03.01.08`)

Por **categoría** y con la **versión del aviso**: un «acepto» sobre un texto que
después cambió no prueba nada sobre el texto nuevo, y es exactamente lo que se
discute cuando llega una reclamación. Cada decisión es una fila nueva, porque
actualizar la anterior borraría la prueba de lo que se aceptó cuando se puso la
cookie.

**Sin decisión previa la respuesta es no.** El silencio no es un sí: tratarlo
como tal es la infracción más común de todas. Y las cookies necesarias no se
ofrecen como interruptor, porque un botón que no apaga nada hace que el usuario
deje de creerse el panel entero.

### Cumplimiento del contenido (`CRM-02.04.01.03`)

Reglas por marca, país e idioma, donde el campo vacío es **comodín**: así la
regla general se escribe una vez y las excepciones se añaden encima.

**Una plantilla bloqueada no se puede editar.** Si el bloqueo fuese un aviso, se
ignoraría el día que hay prisa — justo el día en que se manda a otro país el
texto que allí no cumple. Se compara con el cuerpo original: cambiar una palabra
de una plantilla legal la deja de ser.

Y que no haya reglas declaradas **no es cumplir**: la respuesta lo dice, para que
nadie lea un «se puede mandar» como una aprobación.

### Archivado consultable (`CRM-07.03.01.02`)

Entre tenerlo todo en las tablas vivas y purgarlo hay un hueco donde cae casi
todo el dato viejo de un CRM. No se puede borrar y tenerlo delante hace lento
todo lo demás; lo que suele pasar es que se sube la retención a «nunca» y las
tablas crecen hasta que alguien, un viernes, borra a mano lo que le parece viejo.

- **Archivar no es borrar, y el archivo se consulta.** Si el dato archivado no se
  pudiera leer, esto sería una purga con otro nombre — y la primera vez que
  alguien lo necesitara y no estuviera, nadie volvería a archivar nada.
- **La fila archivada conserva su identificador**, que es lo que permite que una
  solicitud de acceso la encuentre. Con un identificador nuevo, el expediente
  saldría incompleto sin que nadie se diera cuenta.
- **Se simula por defecto**, como la purga: lo que va a mover diez mil filas hay
  que poder verlo antes.
- **Un bloqueo legal no impide archivar.** Lo que prohíbe es destruir, y esto no
  destruye. Se deja anotado que lo había, para que quien audite vea que se tuvo
  en cuenta.

Cada servicio archiva lo suyo, en su propio esquema: un archivo común obligaría a
que un servicio leyera datos de otro.

### Matriz de permisos (`CRM-07.03.02.09`)

«¿Quién puede borrar una cuenta?» se contesta casi siempre leyendo código, y se
contesta mal: alguien mira la pantalla de roles, ve que «comercial» no tiene el
permiso y dice que nadie — sin saber que hay un rol con `*:*` y tres personas
dentro.

Esto sale de las **rutas montadas** cruzadas con los **permisos de los roles**,
no de un inventario: lo que un inventario dice y lo que la ruta exige dejan de
coincidir el día que alguien cambia una y no el otro, y ese es el día en que la
auditoría deja de valer.

Los comodines **se expanden**, porque el asterisco es donde se esconden los
privilegios que nadie contó. Y se enseñan los dos huecos, que son opuestos: un
permiso que una ruta exige y ningún rol tiene es funcionalidad muerta; uno
concedido que ninguna ruta exige es un privilegio que alguien dio por si acaso.
El primero es un fallo de configuración, el segundo un riesgo.

El ABAC se enseña **al lado y no mezclado**: tener el permiso no significa poder
sobre todos los registros. Presentar solo el RBAC haría creer que un comercial ve
todas las cuentas; presentar solo lo efectivo escondería lo que pasaría si mañana
se quita una política.

### Panel de GRC (`CRM-07.03.02.10`)

Las piezas ya estaban —cobertura, vencimientos, riesgos sin control— y cada una
en su pantalla. El problema de tenerlas separadas es el de siempre: hay que abrir
cuatro sitios para saber si se está bien, así que no se abre ninguno.

Se ordena **por urgencia y no por fecha**, porque una lista por fecha entierra lo
grave debajo de lo viejo: primero el riesgo alto sin ningún control, después el
control evaluado como no efectivo —declarado y sin proteger, que es peor que no
tenerlo porque consta—, después los que se pasaron de plazo y al final los que
nunca se evaluaron.

Y dice qué **no se ha podido medir**. Un panel en verde porque no hay nada
declarado es el que más tranquiliza y el que peor informa: sin controles ni
evaluaciones, no dice que se cumpla — dice que no hay nada con lo que
comprobarlo.

---

## Agentes de IA (`CRM-05.02.03`)

Un agente es una automatización que decide sola qué paso dar. Eso es lo que lo
hace útil y lo que lo hace peligroso, y las dos cosas salen de la misma
propiedad: **nadie escribió de antemano lo que va a hacer**. Así que todo este
capítulo está construido alrededor de poder contestar, meses después, «¿por qué
el CRM hizo esto?» y, sobre todo, «¿cómo lo deshago?».

### Las herramientas son la API (`CRM-05.02.03.02`)

Lo que un agente puede hacer se define casi siempre a mano: alguien escribe
quince herramientas, las mantiene un tiempo y luego el CRM crece por otro lado. A
los seis meses el agente sabe hacer lo que alguien recordó declarar.

Aquí se derivan del contrato que cada servicio ya publica —el mismo que consume
un integrador—, así que una ruta nueva es una herramienta nueva sin que nadie la
transcriba, y una retirada deja de existir para el agente el mismo día.

- **Solo lo que su principal puede.** Un agente que hereda los permisos del jefe
  convierte cualquier error suyo en un error con los permisos del jefe.
- **Lo destructivo no entra por defecto.** Una herramienta de borrado disponible
  «porque la API la tiene» es la que acaba usándose por una instrucción mal
  entendida.
- **Se dice lo que ha quedado fuera, y en dos listas distintas**: lo que no puede
  y lo que no se le ha querido dar. Confundirlas lleva a conceder permisos que no
  hacían falta.

### El plan se guarda antes de ejecutarlo (`CRM-05.02.03.01`)

Lanzar un agente **no ejecuta nada**: planifica, guarda el plan y deja esperando
lo que necesita aprobación. Sin plan previo, la auditoría es una lista de cosas
que pasaron y no hay forma de ver dónde se torció: si el primer paso ya iba mal,
los cuatro siguientes son consecuencia y no decisiones.

Después se avanza **un paso por llamada**. Uno y no todos, porque entre paso y
paso es donde caben el apagado, el tope y la aprobación; un bucle que los ejecuta
todos de golpe convierte esos tres controles en decoración.

Si un paso falla, la ejecución para. Seguir con los siguientes pasos de un plan
cuyo tercer paso falló es ejecutar un plan que ya no tiene sentido.

Y lo que el modelo pide y no se le va a dar **se dice**: la herramienta que el
agente no tiene se descarta —intentarla daría un 403 del otro lado y un paso
fallido que parece un error del sistema— y el plan que supera el tope se recorta
avisando, porque uno de cuarenta pasos cortado en el diez deja treinta a medias y
nadie sabe cuáles.

#### Plan cerrado o bucle: dos problemas, no dos gustos

Un plan cerrado se escribe entero antes de empezar, y por eso es el que una
persona puede aprobar de una vez: tiene el plan delante y dice que sí sabiendo a
qué. Lo que no puede es expresar un objetivo cuya segunda mitad dependa de la
primera. *«Qué cuentas están en riesgo y, de cada una, mira su facturación»* se
escribiría sobre cuentas que todavía no se sabe cuáles son.

Para eso está el modo **iterativo**: el agente pide **un** paso, lo ejecuta y
vuelve a decidir con el resultado del anterior delante. Se declara por agente
(`modo`), y los que ya estaban siguen en `plan_cerrado`, que es como decidían
ayer.

Lo que **no** cambia al iterar, que es lo único que hace el bucle aceptable:

- **Cada paso se guarda antes de ejecutarse.** La vuelta que decide no ejecuta;
  lo ejecuta la siguiente. Entre las dos es donde caben el apagado y la
  aprobación.
- **Pasa por el mismo control de aprobación.** Un paso de escritura decidido
  sobre la marcha espera a una persona igual que uno planificado.
- **Cuenta para el tope de acciones**, y el tope cuenta los pasos **pedidos**, no
  sólo los hechos: si contara sólo los hechos, un paso fallido dejaría sitio para
  otro y el tope no acotaría nada.
- **El presupuesto se mira en cada vuelta.** Un bucle con el presupuesto
  comprobado una sola vez al principio es un bucle sin presupuesto: donde se
  gasta es en cada vuelta.

Dos cosas más, porque se notan en el resultado y no en la llamada. Lo que
devolvió un paso se le enseña al modelo **recortado** —un listado de doscientas
filas entra entero en la petición, y en la quinta vuelta la petición es ese
listado cinco veces—, y el recorte **se dice**, para que no concluya que no había
más. Y cuando el modelo no llama a ninguna herramienta se para y se guarda **su**
motivo: «no queda ningún paso» no distingue entre cumplido y rendido.

### Control humano (`CRM-05.02.03.03`)

Por **riesgo de la herramienta** o por **importe**, y el umbral es configurable.
Un control humano que depende de que el modelo pida permiso no es un control, así
que la decisión se toma fuera del modelo.

Dos detalles que deciden si sirve:

- **`aprobacion_por_riesgo` vacío no es «ninguno»**: es el valor por defecto, que
  incluye lo destructivo. Leerlo como «ninguno» haría que declarar un agente sin
  pensar quitara justo el control que más falta hace.
- **Un importe ilegible se trata como si superara el umbral.** Al revés —dejarlo
  pasar— haría que un dato mal formado se saltara el control.

### Tres límites, tres problemas distintos (`CRM-05.02.03.04`)

- **Cuántas acciones por ejecución** acota un bucle: el agente que se llama a sí
  mismo cuarenta veces.
- **Cuántos tokens por periodo** acota una factura: el agente que funciona y
  cuesta lo que nadie previó.
- **El interruptor de apagado** acota un incidente: el agente que hay que parar
  ahora mismo.

Tener solo uno de los tres deja fuera dos de los tres problemas. Y apagar
**detiene también sus ejecuciones en vuelo**: un agente que sigue terminando lo
que empezó no está apagado. Por encima de todo eso sigue estando el apagado de
toda la IA del tenant, porque cuando algo va mal de verdad no hay tiempo de
decidir cuál de los seis agentes era.

### Auditoría y reversión (`CRM-05.02.03.05`)

El plan y lo ejecutado se enseñan **juntos**: ver solo lo que pasó no dice dónde
se torció, y ver solo el plan no dice qué llegó a hacerse. Cada paso guarda por
qué el agente creyó que hacía falta, que es lo que se lee cuando alguien pregunta
por qué el CRM hizo algo.

La reversión va **en orden inverso**, porque los pasos se apoyan unos en otros:
deshacer el primero antes que el tercero deja el tercero apuntando a algo que ya
no está. Cada paso de escritura guarda **cómo deshacerse antes de ejecutarse**;
calcularlo después obligaría a saber qué había antes, y para entonces ya se
cambió.

Y lo que no tiene vuelta atrás **no se toca y se dice**. Un correo enviado no se
«des-envía»: fingir que la reversión es total sería peor que no tenerla, porque
alguien confiaría.

#### Dónde se ve: «Nexus»

Todo lo anterior estaba construido y **no se veía desde ninguna parte**: el
agente era una fila en un listado de administración con un botón de apagar. La
pantalla **Nexus** es su puerta, y está ordenada por lo que
permite desconfiar de ella:

1. Se elige el agente y se escribe lo que se necesita. Ese botón **devuelve el
   plan**, no el resultado, y lo dice antes de pulsarlo.
2. El plan se lee paso a paso, con el **riesgo de cada paso al lado** —lectura,
   escritura, destructivo— y con el porqué que escribió el agente.
3. «Dar el siguiente paso» va avanzando y **se detiene sola** en cuanto hace
   falta una persona. Lo que espera autorización se autoriza o se rechaza ahí
   mismo.
4. Cuando el agente **piensa** en vez de ejecutar —modo iterativo— la pantalla lo
   dice, en lugar de parecer que el botón no ha hecho nada.
5. Al terminar se lee la conclusión y **por qué paró**. Y antes de ofrecer
   deshacer se dice **qué no se va a deshacer**.

Si no hay ningún agente declarado, la pantalla dice dónde se declara: un agente
es configuración, y quien abre esto no tiene por qué saberlo.

### Los agentes concretos son configuración (`CRM-05.02.03.06`)

Calificar leads, contestar soporte y actualizar datos son el mismo mecanismo con
otras herramientas y otros umbrales. Escribir un agente por caso llevaría a tener
tantos agentes como implantaciones, y entonces ninguno estaría revisado.

## Lo que la IA le sugiere a una persona (`CRM-04.02.02.05`, `CRM-04.03.02.02`, `CRM-01.01.05.05`, `CRM-03.01.02.04`)

Todo esto acaba delante de alguien que está en mitad de otra cosa. Eso cambia lo
que hay que cuidar: no es la calidad media de la sugerencia, es **qué pasa con la
mala**. Una sugerencia mala que parece buena se manda tal cual, porque quien la
lee está ocupado.

- **Sugerencia de respuesta y de artículo** (`CRM-04.02.02.05`). Si no hay con
  qué contestar, **no contesta**: un agente con el cliente esperando manda lo que
  le den, y el que responde de la respuesta es él. Los artículos van aparte del
  texto, porque muchas veces lo que necesita no es el párrafo sino el enlace que
  puede leer y juzgar.
- **Asistente conversacional con acciones** (`CRM-04.03.02.02`). Contesta citando
  o no contesta, y la parte transaccional **no se ejecuta ahí**: devuelve qué
  acción propone para que la ejecute el agente, con su tope, su aprobación y su
  reversión. Un chatbot que escribe directamente en el CRM es un chatbot sin
  ninguno de esos cuatro controles.
- **Resumen de cuenta** (`CRM-01.01.05.05`). Separa **lo que consta de lo que
  interpreta**: los hechos son del CRM y el texto es una lectura sobre esos
  hechos. Un riesgo inventado en un resumen de cuenta acaba en una reunión con el
  cliente.
- **Próximos pasos recomendados** (`CRM-03.01.02.04`). Salen de señales del
  propio negocio y por eso cada paso lleva el dato que lo justifica. Con menos de
  tres señales **no se recomienda nada**: lo que saldría es el orden por defecto
  del producto disfrazado de consejo, que es peor que callar porque parece que
  alguien lo pensó. El contenido se adjunta solo si encaja con el paso —adjuntar
  «lo más reciente» a cualquier recomendación es lo que hace que el comercial
  deje de mirar lo que se le adjunta.

---

## Correo, calendario y chat (`CRM-06.01.01`)

Un CRM sin las conversaciones es una agenda cara, y la conversación está en el
correo de cada comercial. Conectarlo tiene dos formas de salir mal, y las dos son
peores que no conectarlo: **volcar el buzón entero dentro del CRM**, que
multiplica el dato personal y la superficie que hay que proteger para algo que
casi nadie vuelve a leer; y **sincronizar en los dos sentidos sin regla de
conflicto**, que hace que una reunión movida en el móvil vuelva sola a la hora
vieja.

### Sincronización bidireccional (`CRM-06.01.01.01`, `CRM-06.01.01.04`)

**Nada de un conector por casa.** Los dos grandes proveedores de correo son la
misma cosa con otras direcciones y otro formato de token: lo que cambia es
configuración —endpoints, campos, cómo se pagina y cómo se pide el incremento— y
eso se declara. Un módulo por proveedor convierte cada implantación nueva en una
versión del producto.

- **Se sincroniza lo que tiene que ver con el CRM, no todo.** Por defecto, los
  correos con alguien que está en el CRM y las reuniones con asistentes externos.
  Lo que no entra no hay que protegerlo.
- **Lo privado no entra nunca**, y se cuenta aparte: si desapareciera sin más,
  nadie sabría que hubo algo que no se trajo.
- **El CRM no gana los conflictos por ser el CRM.** Cuando los dos lados
  cambiaron desde la última sincronización, se marca y lo resuelve una persona.
  Pisar el calendario de alguien es la forma más rápida de que desconecte esto.
- **Idempotencia por identificador del proveedor.** El calendario reenvía el
  mismo evento cada vez que alguien lo toca; sin esto, una reunión aparece cuatro
  veces en la ficha.
- **La marca de incremento solo avanza sobre lo confirmado.** Si avanzara con un
  fallo dentro, el hueco no se recuperaría nunca y nadie lo notaría hasta que
  faltara una reunión.

El panel cuenta lo que **no** está entrando —buzones sin credencial, en error y
conflictos sin resolver—, porque uno que solo cuente lo sincronizado enseña un
número que sube mientras tres llevan una semana desconectados. Y un buzón sin
credencial no está roto: está esperando a que la persona autorice, que es otra
cosa.

### El complemento del cliente de correo (`CRM-06.01.01.02`)

El complemento es una pieza de Outlook o de Gmail; lo que el CRM tiene que dar es
**el contexto**, y acotado: sin una respuesta pequeña y rápida, el panel carga
medio CRM en trescientos píxeles y la gente lo desinstala.

Lo sirve `party`, no `integration`: resolver una dirección a un contacto exige
leer los contactos, y ningún servicio lee el esquema de otro. Devuelve **también
a quién no conoce**, que es la lista de contactos que faltan por dar de alta — y
registrar el correo de alguien que no está en el CRM es justo el caso en que
registrar vale la pena.

### Chat corporativo (`CRM-06.01.01.03`)

Se vende como notificaciones y se usa para otra cosa: lo que ahorra tiempo es no
tener que abrir el CRM para contestar «¿en qué está esto?». Si solo manda avisos,
a las dos semanas el canal está silenciado.

- **Un canal declarado, no un módulo por casa.** Un endpoint, un formato y una
  firma: eso es configuración.
- **Un mensaje entrante se comprueba antes de creerlo.** Cualquiera que sepa la
  URL puede mandar un POST; sin firma verificada, «actuar desde el chat» es
  «actuar desde internet». Se compara en tiempo constante, porque una comparación
  normal filtra el secreto a quien sepa medir.
- **Sin declarar órdenes, el canal solo consulta.** Es lo menos que puede hacer y
  lo que menos daño hace si alguien se equivoca al declararlo. Y una orden no
  admitida se explica en vez de fallar, para que nadie conceda todas «para que
  funcione».
- **Lo que escribe pasa por comandos** al servicio dueño, como cualquier otra
  automatización: venir de un chat no da permisos distintos, así que el estado
  que se devuelve es «pedido».
- **Y el aviso lleva enlace.** Un mensaje que dice «oportunidad ganada» sin decir
  cuál obliga a buscarla, y a la tercera vez se deja de mirar el canal.

### Generación documental (`CRM-06.01.01.06`)

El documento que se le manda a un cliente se hace casi siempre copiando el del
cliente anterior. Eso funciona hasta que alguien no borra un nombre.

- **Lo que no se puede rellenar se dice antes de generar.** Un documento con
  `{{importe}}` sin sustituir llega al cliente igual que uno bueno: nadie relee un
  contrato de doce páginas antes de mandarlo.
- **Las cláusulas bloqueadas se comprueban DESPUÉS de sustituir.** El caso real no
  es que alguien borre la cláusula: es un marcador dentro de ella que la rompe al
  rellenarse.
- **Cada cambio es una versión nueva.** Cuando una cláusula resulta estar mal, la
  pregunta no es cuál está mal: es **a quién se le mandó**, y sin versiones la
  respuesta es «no consta».
- **El documento se enlaza al corpus, no se guarda aquí.** Dos copias del mismo
  contrato divergen, y la del CRM sería la que no tiene ni política de borrado ni
  antivirus.

## Lo que faltaba de la firma electrónica (`CRM-06.01.02`)

### Firma presencial en tableta (`CRM-06.01.02.09`)

Es la firma de toda la vida: el cliente está delante y firma con el dedo. Casi
todas las implementaciones guardan una imagen de la rúbrica y la llaman firma;
eso no sostiene nada, porque una imagen se copia y se pega en otro documento.

- **El trazo es dato biométrico del artículo 9.** Velocidad, presión y tiempos
  identifican a una persona: va cifrado, declarado en el registro de tratamiento
  y **exige consentimiento explícito**. La firma se puede hacer igual sin
  capturarlo.
- **Lo que ata la firma al documento es la huella, no la imagen.** Si el
  documento cambia una coma, deja de cuadrar y se ve. Es la única pregunta que
  importa cuando alguien dice «yo no firmé eso».
- **Se guarda quién sostenía la tableta.** En presencial la identificación la
  hace una persona mirando un documento; sin constancia de quién fue, esto es una
  rúbrica.
- **Un trazo de tres puntos no es una firma.** Un toque accidental produce una
  rúbrica que el sistema daría por válida, y eso es peor que no capturar nada.
- **El trazo no sale en los listados**: devolverlo en una consulta de rutina
  reparte biometría por los registros de acceso, las cachés y los navegadores.

### Llamar al proveedor sin un módulo por casa (`CRM-06.01.02.11`, `CRM-06.01.02.15`)

Un proveedor de firma es una API más: endpoints, credencial y mapeo de campos. Se
declaran **cinco operaciones** —crear sobre, consultar estado, descargar firmado,
descargar certificado y cancelar— y eso es el contrato: quien añade un proveedor
sabe exactamente qué tiene que mapear.

Cada llamada queda registrada con su operación, su código, su duración y su
coste, **también cuando falla**: un registro que solo guarda lo que salió bien
sirve para la factura y no sirve para depurar, que es para lo que se mira a las
dos de la mañana.

**Y ahora se puede leer.** Hasta el 28-10-2026 la tabla se escribía y ninguna
ruta la devolvía, así que el registro «para conciliar la factura» no conciliaba
nada. Está en «Pendiente de firma», al final, con dos cosas que no son adorno:

- **el gasto sumado**, porque conciliar una factura con doscientos importes en
  pantalla es volver a sumarlos a mano;
- **las que fallaron aparte, con su gasto**. Un proveedor que cobra por intento
  hace que el importe y el número de sobres no cuadren, y esa diferencia es lo
  primero que se busca en una factura que no sale.

Sin ninguna llamada registrada **no se dice «cero gasto»**: se dice que no
consta ninguna. Un cero ahí se leería como «el proveedor no ha cobrado nada».

### Probar antes de mandar un contrato (`CRM-06.01.02.14`)

Descubrir que la credencial estaba mal cuando ya hay un contrato a medias es caro
de arreglar: el cliente recibió un correo que no lleva a ninguna parte.

La prueba **en vacío** crea un sobre y lo cancela. Solo consultar no vale: hay
proveedores donde leer funciona con una credencial que no puede escribir, y
entonces la prueba pasa y el primer envío falla.

### Cambiar de proveedor sin perder lo enviado (`CRM-06.01.02.13`)

Los sobres en vuelo **terminan con el suyo**: el enlace que tiene el cliente en su
correo apunta al proveedor viejo, y moverlo de sitio no lo cambia.

Lo que se devuelve al migrar es cuántos quedan y cuál es el más antiguo, porque
eso es lo que decide **cuándo se puede apagar la credencial vieja** — la pregunta
que nadie sabe contestar cuando llega el momento.

---

## Aislamiento, residencia y migración de tenants (`CRM-00.01.01`, `CRM-00.01.05`)

Un CRM multi-tenant se vende con una frase: «sus datos están aislados». Lo que
significa esa frase cambia mucho —y lo que cuesta, también—, así que aquí se
declara con precisión y, sobre todo, **se comprueba**.

Lo que pasa siempre: se vende una base dedicada a un cliente grande, alguien
aprovisiona con la plantilla de siempre y el tenant acaba en el pool compartido.
Nadie lo nota, porque funcionar funciona igual. Se nota el día de la auditoría, o
el día de la incidencia, y entonces ya no hay forma de explicarlo.

### Cinco modalidades, y ninguna es la mala (`CRM-00.01.01.02` a `.05`)

`compartido` —filas separadas por RLS y por el guard del ORM—, `esquema`, `base`,
`cluster` y `cliente` (`CRM-00.01.01.05`), esta última cuando la base la pone él
en su propia infraestructura: marcarlo es lo que cambia de quién es la copia de
seguridad y a quién se le pide el acceso cuando hay una incidencia. Las cinco
son legítimas y cada una tiene su coste. **Lo que no es legítimo es cobrar una y
dar otra.**

Declarar exige lo que hace falta para comprobar después: una base dedicada sin
decir cuál no se acepta, porque sin ese dato la comprobación no se puede hacer y
la declaración se queda en una promesa comercial dentro de una tabla.

### La comprobación es lo que justifica todo esto (`CRM-00.01.01.02`, `.03`)

Se le pregunta a la propia conexión a qué base y a qué esquema está atada, y se
contrasta con lo declarado. Y se comprueba además que **el aislamiento de abajo
sigue puesto**: una tabla con `tenant_id` y sin RLS activa es un agujero, y
quitarlo «porque ya está aislado» deja la protección dependiendo de que el
aprovisionamiento no falle nunca.

Cambiar la declaración **invalida la comprobación anterior**: seguía diciendo que
sí sobre una declaración que ya no es la misma.

Los que no cuadran salen aparte y primero, y no como recordatorio: son una
promesa incumplida en vigor. Y los que nadie ha contrastado en mucho tiempo
también, porque una comprobación de hace ocho meses no dice nada de hoy — entre
medias ha habido despliegues, restauraciones y un cambio de plantilla.

### El cómputo también se aísla (`CRM-00.01.01.06`)

De nada sirve una base dedicada si la importación de cincuenta mil filas de otro
cliente deja sin workers al que paga por no esperar. Cada tenant declara su pool.

### Migrar de modalidad (`CRM-00.01.01.04`, `CRM-00.01.03.10`)

- **Se planifica antes de tocar nada**, porque lo que hay que poder enseñar al
  cliente es la ventana: cuánto tiempo va a poder leer y no escribir. Prometer
  «sin corte» es prometer lo que no se puede; lo que se puede es que el corte sea
  corto, anunciado y reversible.
- **Bajar de aislamiento no es simétrico a subir.** Mueve los datos a un sitio
  donde conviven con los de otros clientes, y eso se dice con esas palabras: no
  es un cambio de configuración, es un cambio de lo que se prometió.
- **Dos migraciones a la vez se rechazan**: dejarían dos copias y ninguna forma
  de saber cuál manda.
- **Se verifica tabla a tabla antes de cerrar.** Sin eso, «migrado» significa «el
  script terminó sin error», que no es lo mismo: una tabla que falló al copiarse
  y se saltó en silencio deja un tenant con la mitad de sus datos y la migración
  marcada como buena. Las filas **de más** también cuentan: copiar algo dos veces
  es tan malo como que falte.
- **Se guarda lo que de verdad duró**, no lo que se prometió. Guardar solo lo
  prometido haría que la siguiente estimación se hiciera sobre un número
  inventado.
- Y al terminar, el aislamiento queda **por comprobar**: la comprobación anterior
  era sobre el sitio viejo.

El mismo mecanismo sirve para **cambiar de región** (`CRM-00.01.03.09`): ventana
de solo lectura anunciada, copia, verificación tabla a tabla y cierre solo si
cuadra. Que el destino esté en otro continente no cambia el procedimiento —cambia
lo que hay que decirle al cliente antes y lo que hay que declarar después en la
residencia.

## Residencia de datos y subprocesadores (`CRM-00.01.05`)

«Sus datos se quedan en Europa» es la frase que cierra contratos y la que más
veces se incumple sin que nadie lo sepa. No por mala fe: los datos
transaccionales sí se quedan, y luego los registros van a un servicio de
observabilidad en otro continente, las copias a un almacenamiento replicado y lo
que se manda a un modelo de IA a una API que ni siquiera se preguntó dónde está.

### Por tipo de dato, no por tenant (`CRM-00.01.05.01`, `.02`)

Seis tipos se ubican por separado (`CRM-00.01.05.02`): transaccional, analítico,
copias, registros, IA y adjuntos. **Esa lista es la capacidad**: lo transaccional casi siempre está
bien, y lo que se escapa son los otros cinco.

**Lo no declarado no se da por bueno.** Un tipo sin región sale como hueco y no
como «europeo por defecto», porque el defecto silencioso es exactamente cómo se
incumple sin enterarse: un tipo sin declarar no es un tipo que esté en la región,
es uno que nadie ha mirado.

### Subprocesadores (`CRM-00.01.05.03`)

Se declaran con **qué tratan y para qué**, no solo con su nombre: una lista de
nombres no sirve para contestar a un cliente que pregunta por el artículo 28, que
es exactamente para lo que se pide esta lista. La garantía es una lista cerrada
—las que reconoce el RGPD—, y «contrato firmado» no es ninguna de ellas.

Un subprocesador **sin comunicar al cliente** sale en el informe: es un
incumplimiento del contrato, no un detalle administrativo.

### Las transferencias se anotan, no se bloquean

Bloquear una salida desde aquí sería fingir un control que no existe: el dato sale
por el conector, por el correo o por el modelo de IA, y esta tabla no está en
medio de ninguno de los tres. Lo que sí se puede es que conste, que se vea cuál
no tiene garantía y que alguien lo arregle donde sí se puede.

Y el informe lo dice claro: **lo que consta es lo que se ha anotado**. Que no
aparezca ninguna transferencia no significa que no las haya.

---

## Ciclo de vida del tenant: onboarding, clonado, fusión y baja (`CRM-00.01.03`)

Las cuatro operaciones de este capítulo son las que más miedo dan de un producto
multi-tenant, y todas fallan igual: **a medias y en silencio**. Un clonado que
copia nueve tablas de diez deja una demo que funciona hasta que alguien abre la
pantalla que falta; una fusión que se para a la mitad deja a dos clientes
viéndose los datos.

Por eso las cuatro **se simulan antes de hacerse**: dicen primero qué van a mover
y qué no saben mover. Descubrirlo después es descubrirlo con los datos ya movidos.

### Onboarding por industria (`CRM-00.01.03.02`)

Un perfil trae objetos, pipelines, flujos y plantillas, y es **datos y no
código**: una industria nueva no puede ser un despliegue del producto, porque
entonces el comercial que la vende depende de una versión.

- **Nada se pisa.** Lo que ya existe con la misma clave se salta y se cuenta:
  aplicar un perfil sobre un tenant que lleva tres semanas trabajando es el caso
  que rompe, y pisar su configuración es la forma más rápida de perder su trabajo.
- **El perfil dice lo que NO trae.** Uno que promete «todo lo de tu sector» y
  deja fuera la mitad hace que el cliente descubra los huecos cuando ya ha metido
  datos. Y lo que no trae se queda sin configurar: un valor inventado por defecto
  es peor que un hueco visible.

### Clonado (`CRM-00.01.03.03`)

- **Hay cosas que no se copian nunca**, y cada una con su motivo: credenciales
  —copiarlas da acceso al sistema real desde una copia de pruebas—, claves de
  cifrado, consentimientos y la cadena de auditoría. Las supresiones se copian
  **siempre**, al revés que todo lo demás: una baja tiene que respetarse también
  en el clon.
- **El destino nace marcado como copia y con las integraciones apagadas.** Si no
  se marca, a las dos semanas alguien manda una campaña de verdad desde la copia
  de demostración; y un sandbox que sincroniza con el ERP de producción no es un
  sandbox.
- **Un clon incompleto no se da por bueno**: se comparan los recuentos y, si no
  cuadran, la operación queda fallida.

### Fusión y escisión (`CRM-00.01.03.06`)

**Fusionar no es copiar: es decidir qué gana.** Dos empresas que se fusionan
traen dos catálogos de productos, dos pipelines y el mismo cliente dado de alta
dos veces. Aquí se cuenta lo que choca; resolver cada choque es de quien conoce el
negocio, porque automatizarlo produce un catálogo que no es de ninguna de las dos
y nadie sabe cuál era el suyo.

Al escindir, **lo que no se asigna se queda donde estaba**. Repartir «lo que no se
dijo» por la mitad, o dárselo al nuevo, es cómo se pierden carteras enteras: nadie
revisa una lista de tres mil cuentas antes de aprobar.

### Baja en cascada con certificado único (`CRM-00.01.07.13`)

O se cierra en todas las herramientas conectadas **o se dice cuál ha quedado
abierta**. Firmar que se destruyó todo sin comprobar la última es firmar sobre
algo que sigue ahí, y eso es peor que no dar certificado.

**Para el usuario.** Son dos pasos y en este orden: `POST /suite/cerrar` pide la
baja en todas las herramientas —va con prioridad de baja, la máxima— y después
`GET /suite/certificado-de-cierre` dice si se puede firmar. Entre medias hay que
aplicar la cola: **encolar no es cerrar**, y el certificado no firma hasta que
consta aplicada en cada una.

**Para mantenimiento.** El certificado lee el estado real de la fila de
sincronización de cada herramienta, no un registro aparte, porque el estado que
vale es el que decide si se volverá a intentar. Tres respuestas posibles por
herramienta: no se ha pedido la baja, está pedida y sin aplicar (con el último
error), o cerrada. Las dos primeras impiden firmar.

> **Se vio funcionar el 28-09-2026, y hasta ese día no existía.** El alta en
> cascada llevaba desde el principio; la baja, no. Cerrar un cliente en el CRM no
> le decía nada a las demás herramientas y su gente seguía entrando en el gestor
> documental con el contrato terminado. La función que compone el certificado
> estaba escrita y probada, y **no la llamaba nadie**: ni ruta, ni consumidor.
> Una capacidad que consta hecha y no se puede ejercer no se descubre hasta que
> hace falta, y aquí hacía falta el día de una auditoría.

## Marca blanca (`CRM-00.01.04.06`)

Poner un logo es fácil. Lo que cuesta es que no se escape la marca del fabricante
por ningún sitio, y se escapa siempre por los mismos **cuatro puntos**: el
remitente de los correos, el dominio de los enlaces, el pie de las plantillas y el
título de la pestaña del navegador. Con uno solo mal, el cliente descubre a su
proveedor delante de su propio cliente.

- **Guardar y activar van separados.** Se configura por partes, en varias
  sesiones, y activar a medias es lo que hace que el primer correo salga con el
  dominio de origen. No se activa hasta que los cuatro puntos están cubiertos.
- **Cambiar un dominio lo deja sin verificar.** Arrastrar la marca de verificado
  haría que los correos salieran por un dominio que nadie ha comprobado.
- **El contraste se calcula, no se estima.** Una paleta corporativa preciosa con
  texto gris sobre blanco deja media aplicación ilegible, y quien la eligió no lo
  ve porque la mira en su pantalla buena.

## Tenants anómalos y throttling adaptativo (`CRM-00.01.06.05`)

El límite fijo protege del abuso y no protege de lo que de verdad tumba un
sistema multi-tenant: **un cliente que hace lo de siempre, pero diez veces más**.
Su importación nocturna se vuelve diurna y el resto empieza a esperar sin que
nadie haya pasado de su límite.

- **Se compara con lo suyo, no con un número global.** Un cliente grande haciendo
  mil peticiones por minuto es normal; uno pequeño haciendo cien no lo es. Un
  umbral único castiga al grande y deja pasar al pequeño.
- **Sin historia no se frena.** Antes del mínimo de observación se mira y se
  dice, pero no se actúa: frenar por ruido es frenar a quien está trabajando.
- **El freno es gradual, temporal y se suelta solo.** Se ralentiza, no se corta:
  cortar a un cliente porque su importación va rápida convierte un problema de
  reparto en una incidencia. Y un freno que hay que quitar a mano se queda puesto.
- **Y se le dice al frenado que está frenado**, con qué cuota y hasta cuándo. Un
  `429` sin explicación hace que la integración reintente más fuerte, que es
  exactamente lo contrario de lo que hace falta.

Se mide **en la puerta**, que es el único paso obligado de toda la API pública:
repartirlo por los servicios garantiza que al catorceavo se olvide. Y la petición
que destapa la anomalía **pasa**: cortarla castiga a quien llegó primero, y la
siguiente ya encuentra el freno puesto.

## La jerarquía de mando, replicada (`CRM-00.05.02.12`, `CRM-00.05.02.07`)

Esto cierra un hueco que este mismo manual llevaba tiempo declarando: **la
compartición por jerarquía no aplicaba en los listados** de `party` ni de `sales`.
Un responsable veía lo suyo, lo de los equipos de cuenta en los que estaba y lo
que le compartieran, pero no lo de sus subordinados por serlo. El motivo era
correcto —`superior_id` vive en la membresía, que es de `identity`— y la solución
es la misma que ya se usa para los ajustes en caliente y la clave del tenant:
**replicar**.

- **Se replica lo mínimo**: quién depende de quién y quién está en qué
  territorio. Ni nombres ni correos: una réplica es otra copia de dato personal
  que hay que proteger.
- **El vacío también se aplica.** Alguien que deja de depender de nadie tiene que
  dejar de contarse como subordinado ese mismo día; ignorar el nulo dejaría a su
  antiguo jefe viendo su cartera para siempre.
- **Los ciclos se cortan y la profundidad se acota.** «A depende de B y B depende
  de A» pasa de verdad —dos cambios de organigrama el mismo día— y sin cortarlo el
  cálculo no termina nunca, con todo el mundo esperando a que cargue un listado.
- **Una réplica vieja se nota.** Cada fila lleva cuándo se actualizó y hay una
  consulta que lo dice. El retraso es molesto —un jefe que acaba de heredar un
  equipo no lo ve todavía— y es el lado correcto en el que equivocarse: lo grave
  sería que alguien que ya no manda siguiera viendo.

Los **territorios** condicionan la visibilidad por el mismo camino, con una regla
que se equivoca fácil: **heredan hacia abajo y no hacia arriba**. Quien lleva
«Europa» ve lo de «España»; quien lleva «España» no ve lo del resto de Europa. Al
revés se nota tarde: cuando alguien pregunta por qué un comercial veía la cartera
entera. Y salir de un territorio **quita visibilidad por su propio camino**, sin
esperar a que llegue un alta que lo sustituya.

El territorio se asigna a la **cuenta**, no a la oportunidad: una empresa está en
una zona y sus negocios van detrás. Filtrar por un territorio en la oportunidad
habría sido más cómodo y habría dejado fuera exactamente las oportunidades que
importan.

## SSO compartido por la suite (`CRM-00.01.07.09`)

El proveedor de identidad se configura **una vez** y lo usan todas las
herramientas conectadas. Repetir la configuración en cada una es cómo se acaba
con tres certificados distintos, dos caducados y nadie sabiendo cuál es el bueno.

Lo que se publica es el **estado real y no la intención**: una herramienta que
dice estar conectada y tiene otro certificado no comparte el SSO, tiene el suyo —
y el día que el cliente rote el certificado se cae solo esa, sin que nadie
entienda por qué.

**Para el usuario.** `GET /proveedores-identidad/suite` lo dice de una vez: qué
proveedor hay, qué herramientas comparten de verdad, cuáles no y por qué. Un
tenant **con proveedor y sin ninguna herramienta declarada no sale en verde**: no
hay con quién compartirlo todavía, que no es lo mismo que estar completo.

**Para mantenimiento.** El cableado se declara en la configuración del **proveedor**:

```json
"herramientas": { "gestor-documental": { "conectada": true, "huella_certificado": "…" } }
```

Y se declara ahí, y no en la conexión de aprovisionamiento, porque son dos hechos
distintos: que empujemos usuarios a una herramienta no dice nada de contra quién
autentica, y una puede estar conectada para lo primero y no para lo segundo.

La huella se calcula ordenando los certificados del proveedor, para que durante
una rotación —cuando conviven el viejo y el nuevo— no parezca que cada
herramienta tiene uno distinto justo el día en que hay que mirarlo.

Y **los nombres salen de esa configuración, no del producto**. Antes eran tres
nombres de la casa escritos en el código, lo que dejaba fuera a la cuarta el día
que existiera y a cualquier herramienta que no fuera nuestra desde el primer día.

> **La ruta va declarada antes que la ficha `/{proveedor_id}`**, o no se alcanza
> nunca: la petición acabaría buscando un proveedor llamado «suite». Hay una
> prueba que lo fija, porque el mismo día ocho rutas del producto resultaron
> inalcanzables exactamente por esto.

> **Se vio funcionar el 28-09-2026**, y al ejercerla se encontró que la
> comprobación entera existía desde el principio **sin ruta, sin consumidor y sin
> prueba**: la capacidad constaba hecha y no había forma de ejercerla. De camino
> apareció que comparar dos listas vacías daba «completo», así que un tenant sin
> ninguna herramienta conectada salía en verde.

## IA sin salida de datos (`CRM-00.01.05.04`)

Es el modo que piden los clientes que no pueden mandar nada fuera. Lo que hacen
casi todos los productos es ofrecer una casilla «no usar IA», que no es lo mismo:
el cliente quiere la función, lo que no quiere es la salida.

Tres condiciones, y las tres tienen que cumplirse: que el proveedor esté **en la
región del tenant** —no en «una región europea», porque un modelo en otro país de
la UE sigue siendo una transferencia que no es lo que se pidió—, que **garantice
que no entrena** con lo que recibe —un modelo que aprende saca los datos por el
peso, no por la red— **o que sea del propio cliente**, que es la única opción que
no depende de la promesa de nadie.

Si no hay ninguno que cumpla, **no se llama a ninguno**. Usar el de fuera «porque
es mejor» sería incumplir exactamente lo que se le prometió.

La región sale de la **política del tenant** cuando admite una sola. Si admite
varias, el sistema **pregunta cuál** en vez de quedarse con la primera: elegir por
el cliente en qué país se queda su dato es exactamente el supuesto que este modo
existe para no hacer, y una región por omisión en el código es la que se acaba
usando el día que nadie mira.

---

## Los huecos que este manual declaraba, cerrados

Todo lo de este capítulo estaba escrito como pendiente en la tabla «Lo que falta
y por qué no se hizo ya». No son mejoras: son promesas que el producto tenía
apuntadas contra sí mismo.

### Plantilla de notificación por canal (`CRM-06.02.01.07`)

El repartidor no renderizaba plantillas porque son de `tenancy` y ningún servicio
lee el esquema de otro, así que el mismo texto iba al correo y al SMS, recortado
a 160 caracteres en el segundo. Lo sufría el destinatario: un aviso pensado para
correo llegaba al móvil cortado a mitad de frase.

Se **replican** al esquema del que reparte, igual que la jerarquía de mando y los
ajustes en caliente. Eso es lo que permite tener plantilla **por canal**, que es
el punto: la de SMS no es la de correo con menos letras, es otra —dice lo
imprescindible y pone un enlace—.

- **Si no hay plantilla, el aviso sale igual.** El mecanismo existe para que se
  vea mejor, no para que el aviso dependa de que alguien la haya creado.
- **Una plantilla a la que le falta un dato no se manda a medias.** «Hola
  {{nombre}}» llegando así es peor que un texto genérico, porque el genérico no
  parece roto y quien lo recibe deduce que el sistema está mal cuidado.
- **El idioma cae hacia atrás con orden**: el del destinatario, el del tenant, el
  de la instalación. «La primera que haya» manda un aviso en alemán a quien pidió
  español.

### Estadísticas de entrega del correo (`CRM-06.02.01.08`)

SMTP da por entregado lo que aceptó el primer servidor y ahí acaba lo que sabe:
si el buzón rebota media hora después, el CRM nunca se entera. La apertura y el
rebote solo los dan las APIs de los proveedores, y por eso esto entra por un
camino **aparte y opcional** — engancharlo ata la instalación a ese proveedor, y
decirlo es parte de la capacidad.

Lo que **no** es opcional es la consecuencia: un rebote duro o una queja **cierran
la dirección**. Anotarlos y seguir escribiendo sería tener la información y no
usarla, que es peor que no tenerla — y quema la reputación del dominio, que la
pagan también los demás clientes.

Y el panel dice cuándo **no puede medir**. Un 0 % de apertura hace que alguien
concluya que sus correos no interesan, cuando lo que pasa es que su transporte no
lo mide: la apertura no es cero, es que nadie la cuenta.

### Reverificación periódica con cuota (`CRM-01.01.01.13`)

Un veredicto caducaba a los noventa días y se volvía a preguntar **cuando alguien
lo pedía**. Ahora hay barrido, y lo que lo hace utilizable es el **tope**: muchos
registros oficiales tienen cuota diaria, y un barrido sin control la agota en una
mañana dejando sin verificar las altas del día — que son las que alguien está
esperando.

- **Los más viejos primero.** Un veredicto de hace dos años es el que más
  probablemente ya no es cierto.
- **Si el registro no contesta, se para.** Seguir con los cuarenta y nueve
  siguientes gasta la cuota en fallos y marca todo el lote como no concluyente
  por un corte que puede durar un minuto.
- **Y se dice cuántos quedan.** Sin ese número nadie sabe si el barrido va al día
  o lleva tres semanas sin alcanzar la cola. Que tarde varios días en ponerse al
  corriente es lo correcto: un veredicto caducado no es una urgencia y una cuota
  agotada sí.

### La firma mueve la oportunidad (`CRM-03.03.02.07`)

El motor de firma ya emitía el evento con el registro de origen dentro; lo que
faltaba era que `sales` lo escuchara. Sin eso, el comercial firmaba el
presupuesto y entraba a mover la oportunidad a mano — el trabajo que la
integración existía para quitar, y el que se olvida.

**Solo se mueve lo que el sobre demuestra.** Un sobre completado dice que está
firmado, no que el negocio esté ganado: puede faltar el pedido, el pago o la
aprobación interna. Se marca la firma y la etapa la sigue gobernando quien la
gobierna; forzar «ganada» desde aquí se saltaría el motivo de cierre, la
aprobación de descuento y el forecast.

## Segundo factor: ciclo de vida, riesgo y sin contraseña (`CRM-00.05.01`)

### MFA adaptativa (`CRM-00.05.01.21`)

Se vende como comodidad y su valor real es otro: pedir el factor **cuando el
contexto cambia** detecta el robo de sesión, que es lo que la MFA de siempre no
ve — una vez dentro, ya estás dentro.

Cada motivo se dice **con palabras**. «Por seguridad» no explica nada, y al
tercer aviso así la gente teclea el código sin mirar, que es exactamente la
costumbre que un atacante necesita.

El **salto imposible** —dos países en dos horas— va aparte: o hay un avión que no
existe o hay dos personas, y eso no se resuelve pidiendo un código. Se pide el
factor **y** se avisa de que hay que mirar las sesiones abiertas, porque si uno
de los dos accesos no era la persona, el otro sigue vivo.

Se evalúa **al entrar**, contra lo que ya se sabe de esa persona: desde qué IPs ha
entrado, desde qué equipos, cuánto hace de la última vez. La primera entrada no es
sospechosa —no hay con qué comparar, y tratarla como riesgo pediría el factor a
todo el mundo el día del alta, que es cuando menos configurado lo tiene—. Y el
factor se pide **solo si hay factor que pedir**: a quien no tiene ninguno no se le
puede exigir uno ahí, y negarle la entrada por algo que no puede resolver lo deja
fuera sin salida.

**El país es un puerto, no una dependencia.** Saber de qué país es una IP exige
una base de datos de geolocalización, y atar el producto a un proveedor concreto
para esto no se hace: quien lo despliegue enchufa el suyo. Lo importante es lo que
pasa si no hay ninguno — y es que **se dice**: la respuesta lleva «el país no se
ha podido medir», en vez de darlo por conocido. Dar por conocido lo que no se ha
mirado haría que la señal más útil de las seis no saltara jamás, y sin que nadie
lo supiera.

### Inscripción, respaldo y cambio de dispositivo (`CRM-00.05.01.19`)

**Un solo factor no es tener MFA: es tener un único punto de fallo.** Quien solo
tiene el móvil y lo pierde se queda fuera, y entonces alguien de soporte lo
desbloquea por teléfono — que es la puerta de atrás por la que se entra de verdad.
Por eso el plan pide siempre un segundo método, y lo dice así en vez de dejarlo
como una recomendación que nadie sigue.

El cambio de móvil tiene dos caminos y ninguno es «llama a soporte»: **con
respaldo** se hace solo, y **sin respaldo** hace falta desbloqueo con dos
aprobadores. No es burocracia: sin el factor viejo, lo único que demuestra quién
es esa persona es que otras respondan por ella, y una sola firma convierte una
llamada convincente en un acceso.

### Entrada sin contraseña, con passkeys (`CRM-00.05.01.23`)

Solo con un factor **resistente a phishing** —una llave FIDO2 o el biométrico del
dispositivo, atados al dominio—. Con un código por SMS como método único se quita
la contraseña y se queda lo más débil de los dos: el SMS se intercepta y se pide
por teléfono, y ya no hay nada detrás.

Y exige respaldo, porque sin contraseña no hay red debajo: perder la llave deja a
la persona fuera del todo.

**Cómo funciona una passkey aquí.** El dispositivo guarda una pareja de claves y
el navegador solo entrega la suya al dominio que la creó: por eso no se puede
teclear en una página falsa, que es la diferencia de fondo con una contraseña.
El servidor guarda la **pública** y un contador; con eso comprueba una firma, y
con eso no puede suplantar a nadie — una base de datos filtrada no da acceso a
ninguna cuenta.

Tres reglas sostienen eso, y las tres están probadas:

- **El reto lo elige el servidor y vale una sola vez.** Si valiera dos, una
  firma capturada se podría reproducir, que es justo el ataque del que protege.
- **El contador solo sube.** Es la única señal que delata un autenticador
  clonado: dos copias de la misma llave acaban firmando con un contador que
  retrocede.
- **El reto de registrar no sirve para entrar**, y al revés.

La llave se registra desde la propia cuenta, con un nombre —«el iPhone», «la del
cajón»—, porque sin nombre revocar una de tres es elegir a ciegas. Y al revocarla
se borra: una credencial revocada que sigue guardada invita a restaurarla, y
restaurar una credencial es lo que no puede pasar.

El dominio y los orígenes válidos **no se escriben en el código**: salen de
`public_base_url` y de `cors_origins`, que ya dicen dónde vive esto. Solo hay que
declararlos cuando el front y la API están en dominios distintos.

### Recuperar el acceso (`CRM-00.05.01.26`)

> **Auditada entera el 26-10-2026** —esta y el resto de la familia de
> autenticación: credenciales de máquina, sesiones, segundo factor y
> federación— recorriendo el código que decide, y **sin hallazgos**. Las cinco
> reglas de abajo están comprobadas una a una, y la del uso único validada
> plantando el caso malo: quitando el consumo del enlace, cae la prueba.

Olvidar la contraseña era un billete de ida: la única salida era que alguien de
dentro la cambiara a mano, y eso produce contraseñas dictadas por teléfono y
administradores que acaban poniendo la misma para todos.

Ahora se pide un enlace desde la propia pantalla de entrada. Las reglas:

- **La respuesta es la misma exista o no el correo.** Distinguirlas convertiría
  esa pantalla en un comprobador de qué correos tienen cuenta aquí, que es
  exactamente la lista que quiere quien va a intentar entrar.
- **El token se guarda hasheado**, por la misma razón que no se guarda la
  contraseña: quien lea la base no puede usar los enlaces pendientes.
- **Vale una vez y caduca en media hora.** Un enlace de recuperación viaja por
  correo, y el correo se reenvía, se archiva y se queda en el portátil que
  alguien vende dos años después.
- **Al usarlo se cierran todas las sesiones.** Quien pide restablecer no puede
  entrar, o sospecha: dejar abiertas las que había es dejar dentro justo a quien
  lo motivó.
- Y la longitud mínima **se comprueba en el servidor**, no solo en el
  formulario: una comprobación que solo vive en el navegador no comprueba nada.

El enlace se **emite** aquí y se **entrega** fuera: el correo lo manda cada
instalación con su propio canal, y por eso el token sale en la respuesta de la
API para quien la integre, nunca para quien lo pide.

### Conectores de SSO y de MFA sin un módulo por casa (`CRM-00.05.01.16`, `CRM-00.05.01.22`)

Lo que cambia entre proveedores son las direcciones y los nombres de los campos:
eso es configuración. Un conector por casa convierte cada implantación nueva en
una versión del producto que hay que mantener diez años.

Lo que **sí** cambia de verdad, y por eso se declara, es qué campo trae el correo
y cómo llaman a los grupos: equivocarse ahí no da un error, da un usuario sin
permisos que nadie entiende. Y un perfil desconocido **no cae al genérico en
silencio** — caer al genérico produce exactamente ese usuario fantasma.

**Un solo vocabulario, y el perfil gobierna la entrada** (cerrado el
05-10-2026). Hasta esa fecha había tres nombres para lo mismo: el perfil decía
`campo_email`, la configuración de SAML leía `attr_email`, y el camino de OIDC
pedía `email` escrito en el código. O sea que declarar que el correo viene en
`mail` no cambiaba nada en OIDC, y en SAML solo si además se escribía con el
otro nombre. Ahora hay uno solo —`campo_email`, `campo_nombre`, `campo_grupos`—
y el antiguo se sigue leyendo, para que ningún proveedor ya configurado deje de
entrar el día del despliegue. Cuando falta el correo se dice **qué campo se
esperaba y cuáles llegaron**, que es la diferencia entre arreglarlo en un minuto
y pasar una tarde mirando el IdP.

**El perfil de un proveedor concreto se lee, no se pega.** El catálogo pide
perfiles para los proveedores del mercado por encima del genérico. Pegar aquí
sus nombres de campo son hechos de productos ajenos que caducan sin avisar, y un
perfil con el campo equivocado es **peor** que no tenerlo. Así que:

- `POST /api/v1/idp/perfiles/descubrir` construye el perfil leyendo el
  `/.well-known/openid-configuration` del propio emisor: sus direcciones, sus
  alcances y los campos que ofrece. Vale para cualquier proveedor, también para
  uno que no existiera cuando se escribió esto.
- `GET /api/v1/idp/{id}/comprobar-perfil` contrasta lo declarado con lo que ese
  proveedor publica de verdad, y dice qué campo declarado **no ofrece**.
- El campo del que no publique ningún nombre conocido sale **vacío y se dice**.
  Proponer uno «porque suele ser» es adivinar, y aquí adivinar sale como un
  usuario que entra sin identidad utilizable o sin permisos.

En SAML no hay nada equivalente que publicar, así que se dice que no es
comprobable sin una entrada de verdad — y en la primera se dirá qué atributo
declarado no llegó, con la lista de los que sí.

### El calentamiento de una IP frena de verdad (`CRM-02.03.01.03`)

Una IP de envío nueva no puede mandar cien mil correos el primer día: se quema.
Y quemarla cuesta **semanas** en las que no llega nada por ese dominio — ni las
campañas ni las facturas, que comparten reputación.

El tope del día se calcula con la progresión del calentamiento y **se aplica
antes de mandar**, no sólo se enseña. Hasta el 05-10-2026 salía en la pantalla
con su aviso y no frenaba ni un correo.

- Un dominio que **no está calentando** no frena nada: el tope es de la IP
  nueva, y aplicarlo a una asentada pararía campañas que llevan años saliendo.
- **Sin decir el dominio no se inventa un tope**: suponerlo frenaría envíos por
  una IP que no es la que se va a usar.
- Y se devuelve cuánto queda, no sólo si se puede: avisar al cortar convierte el
  tope en una sorpresa a mitad de campaña.

Lo mismo con la autenticación del dominio. Uno sin SPF, sin DKIM o sin DMARC
**no rebota**: llega a la carpeta de basura, y eso no aparece en el informe de
rebotes. Por eso se comprueba y se dice qué le falta a cada uno.

### El pedido que sale al ERP, y vuelve (`CRM-03.03.02.11`)

Aceptar un presupuesto crea el pedido y lo deja **esperando confirmación**. No
se da por bueno porque la llamada no diera error: el ERP puede aceptar el
mensaje y rechazar el pedido después, y un traspaso que se cierra al enviar es
cómo se descubre en el cierre de mes que faltan pedidos.

La llamada **no la hace ventas**. Ventas emite el pedido y lo manda
`integration` con el mismo conector declarativo que lee un maestro de clientes:
un ERP es una API más —endpoints, credencial y mapeo de campos— y un módulo por
producto convierte cada implantación en una versión del producto. Llamar al ERP
desde la transacción de ventas ataría aceptar un presupuesto a que el ERP del
cliente esté en pie.

Qué operación lo atiende **se declara** (`INTEGRACION_OPERACION_PEDIDOS`): la
clave la pone quien declara la conexión, y en un cliente será `pedido.crear` y
en otro `sales_order`. Un nombre fijo obligaría a todos a llamarla igual, que es
pedirle al cliente que se adapte a nuestro vocabulario interno.

Lo que el ERP conteste **vuelve a ventas**, porque el estado del pedido es suyo:
su referencia —la que el cliente cita por teléfono para reclamar— o su rechazo.
Si el ERP no devuelve referencia, se deja vacía: una referencia inventada manda
a buscar algo que no existe.

Un despliegue **sin ERP declarado no es un fallo**. La mayoría no tiene ninguno:
se anota y se sigue, en vez de llenar el registro de errores por una integración
que nadie ha pedido — y entonces los errores de verdad no se ven.

### El mantenimiento preventivo sale solo (`CRM-07.04.03.20`)

Un plan mensual existe precisamente para que nadie tenga que acordarse. Si la
orden sólo saliera cuando alguien entra en la pantalla y pulsa, el plan sería
una anotación y la máquina se revisaría cuando se rompe.

Y el síntoma sería el peor: **no hay error**. El panel enseña los planes, las
fechas de vencimiento salen bien calculadas, y no hay órdenes.

**Una por plan a la vez.** Un plan desatendido seis meses generaría seis órdenes
idénticas, y lo que se hace con seis órdenes idénticas es cerrarlas todas sin
mirar — incluida la que había que atender.

### Lo que un aviso por push NO lleva (`CRM-02.03.02.03`)

Un push llega a una **pantalla bloqueada** que ve cualquiera que coja el
teléfono, y pasa por los servidores de push de un tercero por el camino. Así que
lleva **qué ha pasado y dónde mirarlo**, nunca el dato: ni el nombre del
cliente, ni el importe, ni el asunto completo. El dato lo enseña la aplicación
después de identificar a quien la abre.

Hasta el 05-10-2026 esto estaba decidido y no ocurría: la función que compone el
push sin datos dentro no la llamaba nadie, y los avisos salían con el cuerpo
entero. El título se corta a 60 caracteres, que es lo que cabe sin truncarse a
media palabra.

Por los demás canales el aviso sigue llevando lo suyo: vaciar el cuerpo en el
correo dejaría avisos en blanco, que es el fallo contrario.

### De una queja en redes a un caso (`CRM-04.02.01.06`)

Clasificar una mención decide **si abre caso**, y lo que no hace es convertir
cada mención en uno: un «gracias por el envío rápido» no necesita un expediente
con SLA, y meterlo en la cola hace que el agente aprenda a cerrar sin leer.

Lo que sí abre caso **lo abre de verdad**, por una orden al servicio dueño de
los casos. Antes esa decisión era un campo en la respuesta y nadie la ejecutaba:
una queja pública clasificada como caso y sin caso detrás es peor que no
clasificarla, porque el panel dice que se detectó y la cola de soporte no la
tiene.

Y la **severidad sale del tipo**: una crisis no entra en la cola como una queja
más. Meterlas igual es lo que hace que la crisis espere su turno.

Del autor de la mención se guarda **lo justo** para poder contestarle y
encontrar el hilo. Un perfil público sigue siendo dato personal: traerse su
biografía, su foto y su historial «por contexto» crea la ficha de alguien que
nunca nos dio nada, y esa ficha hay que protegerla, conservarla y borrarla como
cualquier otra.

## Invitados externos con acceso acotado (`CRM-06.02.01.06`)

Un cliente, un partner o un auditor que necesita entrar un mes. Tres cosas lo
hacen aceptable y ninguna es opcional:

- **Caduca siempre y con tope.** Un invitado sin fecha es un usuario más, y el
  día que alguien revisa la lista de accesos aparecen quince personas que nadie
  recuerda haber invitado. Renovar es una decisión que hay que tomar otra vez.
- **Los permisos son los que se le den y nada más.** Heredar un rol —«como un
  comercial pero de fuera»— da acceso a todo lo que ese rol gane el mes que
  viene, y nadie vuelve a mirar la invitación.
- **Hace falta decir para qué.** Sin motivo, la revisión anual consiste en mirar
  una lista de correos ajenos sin poder decidir sobre ninguno.

---

## Superficie de API para integradores (`CRM-00.02`)

Todo este capítulo existe por la misma queja, que es la que se oye en cada
integración: **«para pintar una pantalla tengo que hacer siete llamadas»**. Y por
su gemela, que se oye después: «llevo tres días peleando con las credenciales».

### Lectura compuesta y perfiles por cliente (`CRM-00.02.01.02`, `CRM-00.02.03.03`)

**La composición se declara, no se abre.** Un GraphQL abierto contra el modelo
entero es una forma elegante de dejar que cualquiera monte una consulta que tumba
la base. Aquí las composiciones se declaran y se les pone **coste máximo**, que no
es el número de campos: es cuántas llamadas internas cuesta servirla. Sin tope,
«dame la cuenta con sus contactos y las oportunidades de cada uno» es una consulta
que hace mil peticiones — y se calcula **antes** de ejecutarla, porque calcularlo
después es descubrir que costaba mil cuando ya se han hecho las mil.

**Los permisos se comprueban parte a parte.** Una composición no puede enseñar lo
que sus partes no enseñarían: quien puede leer cuentas y no oportunidades recibe
la cuenta y **se le dice que falta la otra parte**. Devolverla entera sería
convertir la comodidad en una vía de escalada; devolverla recortada en silencio
haría que el integrador creyera que ese cliente no tiene oportunidades.

El perfil —web, móvil, portal, quiosco— es lo que evita mandarle al móvil quince
campos para pintar tres, que es la razón por la que las aplicaciones móviles de
CRM van lentas.

### Sandbox con datos sintéticos (`CRM-00.02.01.15`)

**Generados, no copiados.** Copiar datos de producción a un entorno de pruebas es
cómo se filtra una base de clientes entera por un sitio que no tiene las mismas
protecciones, y es lo que casi todo el mundo hace porque es más cómodo y los datos
«parecen más reales».

Los sintéticos tienen otra ventaja que nadie cuenta: **se pueden romper**. Un
integrador puede borrar, duplicar y estropear a gusto, que es exactamente lo que
hay que poder hacer en un entorno de pruebas. Y caducan: uno eterno acumula
credenciales que nadie recuerda y acaba siendo la puerta más vieja del sistema.

### mTLS por integración (`CRM-00.02.04.03`)

**Por integración y no globalmente.** Obligarlo a todos deja fuera a quien se
integra con un script de cuatro líneas; no ofrecerlo deja sin nada a quien mueve
dinero por esa API.

Se compara **la huella y no la cadena**: un certificado firmado por la misma
autoridad no es el mismo certificado, y aceptar cualquiera de la cadena convierte
el mTLS en una comprobación de que existe una autoridad.

### Portal de desarrollador (`CRM-00.02.04.06`)

Enseña **lo que de verdad pasó**, no lo que el contrato promete: sus llamadas, su
cuota y sus últimos errores con hora y código. Un portal que solo documenta es una
web bonita que no resuelve la llamada de las tres de la mañana.

Y los errores van **separados por culpa**: los suyos —4xx— y los nuestros —5xx—.
Mezclarlos hace que un integrador pase una tarde revisando su código por una caída
nuestra, o al revés.

### Endpoints propios del tenant (`CRM-00.04.02.04`)

Son una **composición con nombre suyo**, no una puerta aparte: heredan el mismo
límite de tasa, la misma auditoría, la misma comprobación de permisos y el mismo
presupuesto de error. Un camino que no pasa por donde pasan los demás es un camino
donde los controles se ponen otra vez, peor y más tarde.

Viven bajo `/api/v1/x/` y no pueden pisar una ruta del producto: dejar que un
tenant declare `/api/v1/accounts` haría que el día que se publique la nuestra, una
de las dos deje de funcionar.

### SDK y componentes embebibles (`CRM-00.02.03.04`, `CRM-00.02.03.05`)

**El SDK se genera del contrato.** Uno escrito a mano se queda viejo siempre:
alguien lo escribe con cariño para tres lenguajes y a los cuatro meses la API
tiene dos endpoints que el SDK no conoce — y el integrador no se entera de que
existen.

Lo que **no** se genera es lo que cuesta de verdad, y por eso se declara en el
plan: el reintento con espera creciente —sin él, la mitad de los integradores
reintenta sin esperar y convierte una caída de diez segundos en una avalancha—, la
paginación resuelta como iterador —el error más repetido de toda integración es
pedir la primera página y creer que son todos—, los errores del producto como
excepciones con nombre, el idioma de los mensajes y la clave de idempotencia al
reintentar, que es lo que evita el cobro duplicado.

Un **componente embebible** no usa la sesión del CRM sino un token acotado al
registro que enseña: uno con la sesión dentro de una web pública deja entrar a
quien pase por ahí, basta con abrir las herramientas del navegador. Y su contrato
es tan público como el de la API, porque se incrusta en páginas que no son
nuestras.

## Tokenización de datos de pago (`CRM-00.05.03.04`)

Cifrar un número de tarjeta lo protege de quien lea la base. **Tokenizarlo lo saca
de la base**, que es otra cosa: lo que queda en el CRM es una referencia sin valor.
La diferencia importa el día de la auditoría — un sistema que cifra tarjetas sigue
dentro del alcance de PCI; uno que no las tiene, no.

- **Sin bóveda no se tokeniza en falso.** Guardar el número «hasta que haya
  bóveda» mete el sistema en el alcance sin que nadie lo haya decidido.
- **La pista es solo para reconocer.** De una tarjeta se guardan los cuatro
  últimos y va marcada como lo que es; de un NIF no se guarda nada visible, porque
  con la letra y dos dígitos se adivina el resto.
- **Detokenizar cuesta a propósito**: exige motivo y deja rastro. Si el ORM lo
  resolviera solo al leer, el dato volvería a estar en los registros, en las cachés
  y en las respuestas de la API, y la tokenización no habría servido de nada.
- **Y se busca lo que se cuela por texto libre.** El caso real no es que alguien
  decida guardar tarjetas: es un integrador que manda el número en un campo de
  notas. Se comprueba con Luhn para no dar la alarma con cualquier número largo —
  un aviso que salta con todo se ignora a la semana.

Esa última comprobación corre **en el camino de escritura de los campos del
tenant**, que es por donde pasan todos: hacerlo en cada servicio por su cuenta
sería «funciona en los que alguien se acordó». Y **no avisa: corta**. Un campo de
notas con una tarjeta dentro mete al sistema en el alcance igual que una columna
dedicada, y el día que se descubre lleva meses ahí.

El mensaje cambia según haya bóveda o no, porque lo que tiene que hacer quien lo
lee es distinto: **con bóveda** es un paso que falta —tokenízalo y guarda la
referencia—; **sin bóveda** es que ese dato no puede entrar aquí de ninguna forma,
y va en el sistema de pagos.

## Rastro completo de agregados críticos (`CRM-00.05.04.06`)

La pregunta que resuelve llega siempre tarde: **«¿cómo estaba esto el 3 de
marzo?»**. El historial de campos dice qué cambió; no dice cómo era el conjunto, y
reconstruirlo encadenando cambios sale mal en cuanto hay una fusión o un borrado
por medio.

- **Opcional y por agregado, con motivo escrito.** Encenderlo en todo multiplica
  la escritura por algo que nadie va a consultar de la mayoría; y dentro de dos
  años alguien mirará por qué esa tabla ocupa lo que ocupa.
- **El estado vivo sigue siendo la verdad para trabajar.** Reconstruir para pintar
  una ficha haría lento lo que se usa mil veces al día para servir lo que se
  pregunta una vez al año.
- **Un hecho no se corrige: se compensa**, y los dos quedan. Si se pudiera editar,
  la reconstrucción de marzo saldría como si nunca se hubiera equivocado nadie.
- **Y una reconstrucción que no cuadra con la tabla viva se dice.** Es la única
  forma de detectar lo que de verdad pasa: un script de corrección, una migración o
  un arreglo a mano un viernes. A partir de ahí el rastro deja de ser una prueba, y
  en silencio.

Se pregunta **por servicio**, igual que la papelera: los hechos de un objeto viven
en el esquema del servicio que lo guarda. Y lo primero que contesta es **qué
agregados lo tienen encendido**, con el motivo de cada uno — sin esa lista nadie
sabe de qué puede preguntar. Preguntar por uno apagado **se dice**: un rastro vacío
contestaría lo mismo que si todo fuera bien y nadie hubiera tocado ese registro,
que es la respuesta que más confunde de las tres.

Hoy está encendido en la **oportunidad**, que es el objeto por el que se pregunta
cómo estaba en una fecha concreta: lo piden la revisión de previsión, una auditoría
de comisiones y cualquier discusión sobre por qué se cerró así. Cada cambio de
estado deja su hecho, y lo deja **la propia transición**: anotarlo en cada sitio
donde se cambia un estado es dejarlo fuera del que se olvide, y una reconstrucción
a la que le falta un hecho no es una prueba de nada — es peor que no tenerla,
porque lo parece.

---

## Configuración como código: paquetes, promoción, drift y vuelta atrás (`CRM-07.02.01`)

Un CRM configurable acaba siempre igual: alguien toca producción un viernes
porque «es un cambio pequeño», y a los tres meses nadie sabe qué hay configurado
ni por qué. El entorno de pruebas dice una cosa y producción otra, y la diferencia
no está escrita en ninguna parte.

Lo que arregla eso no es prohibir tocar producción —se va a tocar igual— sino
**verlo**: que un cambio hecho fuera del camino aparezca en una lista al día
siguiente, con su autor y su hora.

- **La configuración puede vivir en Git** (`CRM-07.02.01.04`): el paquete guarda
  su referencia cuando la hay. Vacío es legítimo —hay tenants que configuran desde
  la consola y no tienen repositorio— y por eso no se exige; lo que no se admite
  es inventársela, porque una referencia que no existe hace perder media mañana a
  quien la busque.
- **El paquete lleva de dónde sale** (`CRM-07.02.01.03`), y cada empaquetado es
  una versión nueva.
  Sobrescribir la anterior dejaría sin sitio al que está desplegado en producción,
  y volver atrás exigiría reconstruirlo de memoria.
- **La huella se calcula con las claves ordenadas.** Si no, el mismo paquete daría
  huellas distintas según cómo se serializara y el drift saltaría cada día sin que
  nadie hubiera tocado nada — que es la forma más rápida de que se deje de mirar.
- **Promocionar comprueba antes de aplicar.** Lo que en pruebas era un campo nuevo
  puede ser en producción uno que ya existe con otro tipo; aplicar y descubrirlo a
  la mitad deja el entorno con medio paquete dentro y sin forma de saber cuál.
  Un cambio de tipo con datos dentro **no se aplica solo**: puede perderlos.
- **Se puede preguntar de qué commit sale lo que hay puesto**
  (`CRM-07.02.01.04`). `GET /entornos/{entorno}/desplegado` devuelve el
  paquete, su versión, su huella, la **referencia de repositorio**, quién lo
  desplegó, cuándo y con qué motivo.

  Hasta el 26-10-2026 no se podía. El paquete guardaba `referencia_git` desde
  el principio —es la mitad de «configuración como código con control de
  versiones»— y **ninguna ruta la devolvía**: se escribía al empaquetar y no se
  leía en ningún sitio, así que la pregunta que justifica el campo no se podía
  contestar desde el producto. Un campo que se escribe y no se lee no existe
  para quien lo necesita.

  Un paquete sin referencia **lo dice**: hay tenants que configuran desde la
  consola, y eso no es un fallo — es que no hay un commit al que volver, sólo
  el paquete anterior. Y «no consta nada desplegado» no es «está vacío»: lo que
  haya puesto se puso fuera del camino.
- **El drift se mide contra el paquete desplegado** (`CRM-07.02.01.06`)**, no
  contra otro entorno.**
  Comparar dos entornos dice en qué se diferencian, que puede ser legítimo porque
  uno va por delante; comparar contra lo desplegado dice **qué tocó alguien a
  mano**, que es la pregunta. Y lo que el paquete traía y ya no está también es
  drift, aunque no lo parezca.
- **Volver atrás es reaplicar el paquete anterior** (`CRM-07.02.01.07`)**, no
  deshacer cambios.** Deshacer
  uno a uno falla en cuanto hay dependencias —un campo que se creó y una vista que
  lo usa— y deja el entorno en un estado que no ha existido nunca.

Y no se juzga el drift: tocar producción un viernes a veces es lo correcto. Lo que
no puede pasar es que no conste, porque el siguiente despliegue lo pisará sin
avisar.

**Y lo que no se ha comparado se dice.** Hay dos formas de pedir el desvío: la
completa (`POST`), donde quien pregunta manda el estado actual de los ocho tipos
de contenido, y la rápida (`GET`), que lee lo que el propio CRM tiene guardado y
**solo sabe leer los campos de un objeto**. La rápida devuelve `comparado` y
`no_comparado`, y de lo segundo no dice nada: ni que está bien ni que está mal.

Hasta el 26-10-2026 decía que estaba borrado. La vista rápida comparaba los ocho
tipos contra un estado que solo tenía campos, así que una vista o una plantilla
del paquete salían como desaparecidas en un entorno que nadie había tocado — y
encima montaba ese estado con una forma que la comparación no sabe leer, con lo
que **también los campos** salían como desaparecidos. Un «limpio» que tapa siete
tipos sin mirar es peor que no medir, y un informe lleno de desvíos inventados es
la forma más rápida de que se deje de mirar.

## Probar y promocionar automatizaciones (`CRM-00.03.03.08`, `CRM-00.03.03.09`)

Se piden por ruta: la prueba en seco, la promoción y la instalación de una
plantilla por industria. Durante un tiempo estuvieron escritas y sin puerta, que
es como no tenerlas — y mientras tanto la única forma de probar una regla seguía
siendo activarla.

Una automatización se escribe en producción porque es donde están los datos de
verdad, y se prueba **activándola**. Eso funciona hasta el día en que la regla que
debía avisar a una persona manda cuatro mil correos.

- **La prueba en seco va contra datos reales.** Contra datos inventados la regla
  siempre funciona: los casos raros que la rompen son los que tiene el cliente, no
  los que a uno se le ocurren.
- **Y dice a cuántos habría afectado.** Es el número que para una mano: nadie
  activa una regla cuando ve «afectaría a 19.480 registros», y casi todo el mundo
  la activa si solo ve «la regla es válida». Con la muestra al lado, porque el
  número asusta y la muestra es lo que hace decir «espera, ese no debería estar
  ahí».
- **No se promociona a producción lo que no se ha probado en seco.** La prueba
  cuesta un minuto; la regla que manda cuatro mil correos cuesta una semana de
  explicaciones.
- **Se copia la definición, no el estado.** Lo que ya procesó en pruebas no lo ha
  procesado en producción: copiarlo haría que se saltara justo los registros que
  tiene que tocar.
- **Y llega apagada.** Una automatización que se enciende sola al promocionarse
  empieza a actuar en el momento en que alguien pulsa «desplegar», que no es el
  momento en que alguien ha decidido que actúe. Lo mismo con las plantillas por
  industria: una biblioteca que instala reglas activas empieza a mandar correos en
  cuanto alguien la mira por curiosidad.

## Sagas con compensación (`CRM-03.03.02.12`)

Un pedido que se cobra toca cuatro servicios y ninguna base de datos los abarca a
todos. No hay transacción que valga: o se orquesta con compensaciones, o el día
que falla el tercer paso queda un pedido confirmado, un stock reservado y un cobro
que no existe — y alguien lo arregla a mano leyendo logs.

- **Cada paso declara cómo se deshace antes de ejecutarse.** Calcularlo cuando
  falle el tercero obliga a saber qué había antes del primero, y para entonces ya
  se cambió.
- **Compensar no es deshacer: es hacer lo contrario.** Un cobro no se borra, se
  devuelve; un pedido no desaparece, se cancela. Lo primero pierde el rastro de
  que pasó, y lo que pasó tiene consecuencias contables aunque uno se arrepienta.
- **Se compensa hacia atrás**, porque los pasos se apoyan unos en otros.
- **Lo que no se puede compensar se declara así desde el principio**, y eso cambia
  el orden: lo irreversible va al final, cuando ya no puede fallar nada detrás. Un
  correo al cliente en el paso dos deja una saga que, al compensarse, ha avisado a
  alguien de algo que no ha pasado — y el sistema avisa de esa colocación al
  arrancar.
- **Y una saga con algo sin compensar queda ATASCADA, no compensada.** Decir que
  está compensada haría que nadie se fiara de esa palabra: alguien tiene que
  decidir qué se hace con lo que quedó hecho.

### Instancias en vuelo (`CRM-00.03.02.13`)

Las que están corriendo **terminan con su versión**. Cambiarles el guion a la
mitad las deja en un paso que en la versión nueva no existe, y entonces ni avanzan
ni se pueden cancelar sin dejar cosas a medias.

Lo que sí se puede es decir **cuántas hay y en qué paso**, porque de eso depende
si la versión nueva puede esperar a que terminen o hay que resolverlas una a una.

### Plantillas de flujo por sector (`CRM-00.03.05.15`)

**Se clonan, no se heredan.** Si heredaran, mejorar la plantilla cambiaría los
procesos que ya están corriendo en veinte clientes — incluido uno que la ajustó
hace seis meses y no espera que le cambie nada.

Y el clon necesita nombre propio: si se queda con el de la plantilla, nadie sabe
después cuál es el suyo y cuál el de fábrica. Se devuelve además **lo que la
plantilla no resuelve**, porque una que promete el proceso entero y deja fuera la
aprobación hace que el cliente lo descubra en producción.

## Formularios y vistas servidos como datos (`CRM-00.02.03.08`, `CRM-00.04.03.01`)

Si el formulario vive en el código del front, cada cambio de cada cliente es un
despliegue del producto, y a los seis meses hay cuatro versiones del front y
ninguna está bien. Servirlo como datos lo arregla y trae su propio problema: **el
front deja de saber qué va a recibir**.

- **El contrato es cerrado.** Los tipos de componente son una lista: un front que
  recibe uno que no conoce solo puede no pintar nada o pintar una caja de texto que
  guarda basura en un campo numérico. Y un tipo del metamodelo sin componente
  asignado **no cae a texto**: caer a texto deja escribir «mañana» en un campo de
  fecha, y eso se descubre meses después al intentar ordenar por esa columna.
- **Cada vista dice con qué versión del contrato se hizo**, para que un front
  viejo pueda decir «no sé pintar esto» en vez de pintarlo mal.
- **Los permisos se resuelven al servir, no al pintar.** Mandar el formulario
  completo y esconder lo que no toca deja el dato viajando hasta el navegador:
  basta con abrir las herramientas de desarrollo. Y se dice cuántos campos se han
  quitado, porque si no el usuario cree que su ficha tiene doce campos cuando tiene
  veinte.
- **La validación viaja pero no sustituye a la del servidor.** Se manda para que
  nadie descubra el error después de rellenar veinte campos; la que protege el dato
  es la del servidor, porque lo que llega por la API no pasa por ningún formulario.

El diseñador comprueba antes de publicar las tres cosas que se rompen siempre al
arrastrar campos y que **no dan error al guardar**: un obligatorio escondido en una
pestaña secundaria —el formulario no se puede guardar y el usuario no ve por qué,
porque el error sale abajo y el campo está en otra pantalla—, un campo en una
sección que no existe —desaparece y nadie lo echa de menos— y un formulario sin
ningún campo obligatorio, que es la forma más silenciosa de llenar el CRM de
fichas vacías.

## El diseñador visual, completo (`CRM-00.04.03.01`)

Servir el formulario como datos es la mitad. La otra mitad es que alguien pueda
**componerlo sin escribir nada**: arrastrar campos, hacer secciones y pestañas y
poner condiciones de visibilidad. Y lo que separa un diseñador de un editor de
JSON con ratón es que **diga que no** cuando el diseño está mal.

Los tres fallos que se cometen siempre no dan error al guardar, y se descubren
semanas después, cuando un usuario dice «es que ese campo no está»:

- **Un campo que no existe en el esquema.** Se guarda, no se pinta, y nadie
  relaciona la pantalla vacía con el diseño que se tocó hace un mes.
- **El mismo campo en dos secciones.** Se pinta dos veces: el usuario escribe en
  uno y al guardar gana el otro, el que no tocó. Por eso arrastrar **quita de
  donde estaba** — un «añadir» sin «quitar» es exactamente este fallo.
- **Un obligatorio que no está en ninguna sección.** No se puede rellenar, y el
  alta falla sin que el usuario vea dónde está el problema.

Se devuelven **todos** los problemas de una vez. Descubrirlos de uno en uno, con
un intento de guardar entre cada dos, es lo que hace que la gente deje de usar el
diseñador y pida los cambios por correo.

Y lo que más se confunde: **una condición de visibilidad no es un permiso**.
Esconder el margen a los comerciales con una condición no se lo esconde — el dato
sigue viajando en la API y basta con abrir las herramientas del navegador. Lo que
no se puede ver es un permiso; la condición solo quita ruido de la pantalla. Se
avisa explícitamente cuando un campo tiene las dos cosas, para que nadie se quede
con la impresión equivocada.

Las condiciones **se evalúan en el servidor**, con el registro delante, y el
formulario servido ya viene sin lo que no toca pintar. Si las evaluara el front,
el dato del campo escondido habría viajado igualmente. Se dice además **cuántos**
campos se han escondido y por qué: sin eso, el usuario cree que su ficha tiene
ocho campos cuando tiene catorce y llama preguntando dónde se mete un dato que sí
existe.

En las **listas** hay otras dos que no dan error: una columna sobre un campo que
no existe sale vacía en todas las filas —y se lee como «ningún cliente tiene ese
dato»— y ordenar por un texto largo o un JSON obliga a recorrer la tabla entera
en cada carga: con mil filas no se nota y con un millón la lista deja de abrirse,
sin que nadie relacione una cosa con la otra.

Un detalle de operación: **solo puede haber un diseño por defecto**. Con dos,
cuál sale depende del orden en que la base devuelva las filas, y eso cambia sin
que nadie toque nada. Y al preguntar qué diseño le toca a alguien se contesta
también **por qué ese**, porque la pregunta que llega a soporte es siempre «¿por
qué yo veo otra pantalla?».

## gRPC y protobuf: el contrato binario (`CRM-00.02.01.03`)

El puerto lo levanta el arranque del servicio cuando `GRPC_ACTIVO` lo pide, y los
cinco métodos del contrato los sirve **el mismo código que sirve REST**: cada uno
despacha contra la propia aplicación. Si no fueran los mismos, habría dos sitios
donde se aplican las reglas de negocio y solo uno al día.

Con el ajuste encendido y sin la librería instalada, el servicio **arranca igual y
lo dice**: apagar el HTTP de todo el mundo porque falta una dependencia opcional
convierte una instalación incompleta en una caída.

Para el cliente que mueve millones de filas, HTTP y JSON son caros: el JSON ocupa
el triple y no hay forma decente de mantener un flujo abierto sin sondear. gRPC
resuelve las dos cosas, y trae una trampa que hay que mirar de frente.

**El `.proto` se genera, no se escribe.** Es la misma regla que ya se aplica al
OpenAPI: un contrato mantenido a mano al lado de la API dice algo distinto en
cuanto alguien añade un campo, y el que se queda viejo es siempre el que menos
gente mira. Además, aquí no podría estar en el repositorio aunque se quisiera:
los campos los define **cada tenant** en su metamodelo, y el `contacto` de un
cliente tiene ocho campos que el de otro no tiene. Un fichero fijo sería un
contrato equivocado para todos.

**Y el número de campo es el contrato; el nombre es cosmético.** Esta es la
trampa, y es silenciosa: si el campo 7 era `descuento` (un entero) y mañana pasa
a ser `id_zona` (otro entero), un cliente que aún mande un descuento **escribe
una zona**. El mensaje se decodifica sin quejarse, no hay error, no hay log, y se
descubre cuando alguien pregunta por qué ese cliente está en una zona que no
existe. Por eso:

- Los números **se asignan una vez y se guardan** por tenant y objeto. Reordenar
  los campos no cambia ninguno.
- Lo que se borra **queda reservado para siempre**. Es feo de leer en el `.proto`
  y es la única forma de que ese número no se reutilice.
- Y publicar un esquema que rompe el contrato **se rechaza al publicar**, no en
  la integración del cliente seis meses después. Se dice qué rompe, con qué campo
  y qué pasaría: un tipo cambiado, un número movido, un campo quitado sin
  reservar o uno que pasa de singular a repetido.

Dos decisiones de tipos que importan. Los **importes viajan como cadena**, igual
que en el JSON de la API: `double` no representa 0,1 y en dinero eso se convierte
en céntimos que no cuadran. Y un tipo sin correspondencia **no cae a `string`**,
por lo mismo que un tipo sin componente no cae a caja de texto.

Los campos **cifrados no salen por gRPC**. No es un olvido: lo que se guarda
cifrado se descifra para quien tiene permiso y por el camino que ya se auditó, no
por una superficie nueva. Quien publica el esquema ve en la respuesta qué campos
no salen y por qué — no el integrador tres semanas después.

Los mensajes llevan **presencia explícita** en los campos opcionales. Sin ella,
en proto3 un cero y un «no lo mando» son el mismo byte: ninguno. En un `Update`
eso significa que mandar tres campos borra los otros veinte, y el cliente nunca
pretendió eso. Por el mismo motivo, un campo que **no está en el contrato es un
error** y no se ignora: protobuf descarta lo desconocido por diseño, que está
bien al leer y es malísimo al escribir — quien manda `descuneto` cree que puso un
descuento y recibiría un «todo bien» con la ficha sin él.

**El transporte es opcional; el contrato no.** `grpcio` trae una extensión en C
que tarda en instalarse y que la inmensa mayoría de las instalaciones no van a
usar nunca, así que va en `requirements-grpc.txt` —igual que SAML— y el puerto
solo se levanta con `GRPC_ACTIVO=true`. Sin la librería no hay un hueco callado:
se dice qué instalar. El `.proto` y la comprobación de compatibilidad funcionan
siempre.

Y la decisión que más importa: **la misma identidad, los mismos permisos y el
mismo tenant que HTTP**. Una segunda puerta que valide el token con su propio
código es la puerta por la que se entra — las dos implementaciones divergen, la
que menos gente mira se queda atrás, y el día que se endurece algo se endurece en
una sola. Aquí el token lo valida literalmente la misma función que usa REST. Los
topes del flujo (elementos, segundos, tamaño de mensaje) son configuración,
porque un `Watch` retiene una conexión mientras dura y un cliente que lo abre y
se va de vacaciones la deja ocupada hasta que alguien mira por qué el pool está
lleno.

## La interfaz de referencia es opcional, y se mide (`CRM-00.02.03.02`)

«Somos headless y la interfaz es opcional» lo dice todo el mundo y casi nunca es
verdad. No porque se mienta, sino porque **se erosiona**: alguien monta un
estático, otro pone una redirección a `/app`, un tercero deja el CORS abierto
solo al origen de la consola, y al año la API oficialmente headless necesita su
front para funcionar del todo.

Aquí eso no es una declaración: es una **comprobación** que corre en el preflight
y mira la aplicación montada de verdad, buscando cuatro cosas concretas:

- **Ficheros estáticos servidos desde el servicio.** Hacen que el front viaje
  dentro del backend: desplegar la API pasa a desplegar la interfaz, y
  sustituirla deja de ser una opción de despliegue.
- **Redirecciones a rutas del front.** Un 307 hacia `/app/...` es el backend
  dando por hecho que existe una pantalla que en otra instalación no está.
- **Respuestas en HTML donde debería ir JSON.** Un integrador que recibe una
  página de error no puede leerla, y lo que le enseña a su usuario es el código
  de estado a secas.
- **Un CORS con un único origen.** Si solo se admite el de la consola, cualquier
  otra interfaz —la del cliente, un portal, un quiosco— queda fuera por
  configuración, por muy headless que sea la API.

La consola oficial se despliega en su propio contenedor, en el perfil `consola`
de `docker-compose.yml`, que **no está en el arranque por defecto**. No apagarla
no quita ninguna operación: todo lo que hace es una llamada de la superficie
publicada (`/superficie`), que es de donde ella misma las saca. No hay ningún
camino privado, no es requisito de licencia, y lo que se pierde sin ella son las
pantallas que trae hechas. Nada más.

## Código del tenant: sandbox, versiones y firma (`CRM-00.04.02.01`, `CRM-00.04.02.05`, `CRM-00.04.02.06`, `CRM-00.04.02.07`)

Las cuatro comprobaciones —límites, capacidades, versión y firma— y la
observabilidad se piden por ruta. Estaban escritas y no las alcanzaba nada: el
producto tenía todo lo que hace aceptable ejecutar código ajeno, sin forma de
usarlo.

Dejar que un cliente ejecute su código dentro del CRM es la diferencia entre un
producto configurable y uno programable, y también la forma más rápida de que una
implantación tumbe a las demás: **el bucle infinito de un cliente no es un
problema suyo**, es un problema de todos los que comparten ese worker.

- **Los límites son del sandbox, no del código.** Pedirle al cliente que su
  función no tarde más de dos segundos es pedirle que se porte bien; cortarla a
  los dos segundos es que no pueda. Se comprueba durante y después: lo que hay
  que cortar es la ejecución que ya se está pasando, y lo que hay que contar es
  lo que consumió la que terminó.
- **Lo prohibido no se ofrece.** Leer otro tenant, ejecutar SQL, leer
  credenciales o salir a la red sin declararlo no son permisos que se
  comprueban: son cosas que no se le ofrecen a ninguna extensión. Y se rechaza
  **al declararla**, no al ejecutarla — aceptarla y bloquearla después deja la
  comprobación en tiempo de ejecución como única barrera, y esa se salta el día
  que alguien añade un camino nuevo.
- **Una versión nueva no reemplaza a la anterior: convive.** Desplegar pisando
  deja sin sitio a lo que está ejecutándose en ese momento, y volver atrás exige
  tener la anterior entera y viva, no un diff que alguien aplique con prisa.
- **Las dependencias van fijadas.** Una extensión que declara «la última
  versión» de una librería funciona hasta que esa librería publique un cambio, y
  entonces falla en producción sin que nadie haya tocado nada: el peor tipo de
  fallo, porque no hay ningún cambio que revisar.
- **El coste se atribuye a quien lo gasta.** Sin eso, el tiempo de cómputo de un
  cliente lo paga el despliegue entero y nadie sabe de quién es la factura — que
  es justo la conversación que hay que poder tener con el cliente que se pasa, y
  que sin números no se puede tener. Las ejecuciones cortadas por límite se
  cuentan **aparte** de las fallidas: una que falla tiene un error que arreglar y
  una que se corta tiene un diseño que revisar.
- **Los errores de una extensión son del tenant, y sus logs también.**
  Mezclarlos con los del producto hace que un fallo suyo parezca nuestro y al
  revés, y en la guardia de las tres de la mañana esa diferencia es todo.
- **Y una extensión de terceros se firma y se revisa.** Sin firma, «instalar una
  extensión» es «ejecutar código de un desconocido dentro de la base de tus
  clientes». Con firma pero sin revisión es lo mismo con un sello: la firma dice
  **quién** lo escribió, no que sea seguro. Se exigen las dos cosas y la revisión
  la hace una persona, porque automatizar «¿este código es seguro?» es el
  problema que nadie ha resuelto.

De cada ejecución queda la **entrada** y no la salida: una extensión que falla
con un registro concreto y no guarda cuál obliga a reproducirlo a ciegas, y eso
son horas; la salida, en cambio, puede llevar el registro entero y guardarla
duplicaría en una tabla de logs el dato que hay que proteger.

Y cuando no consta ninguna ejecución se dice **«no medible»**, no «va bien»: que
no haya datos significa que no se ha ejecutado o que no se está midiendo, y las
dos cosas son distintas de que funcione.

## Móvil y modo sin conexión (`CRM-06.02.01.03`, `CRM-06.02.01.04`)

Las aplicaciones móviles de CRM fallan casi siempre por lo mismo, y no es la
interfaz: es que **el servidor no está pensado para un cliente que se
desconecta**. Un comercial en una nave sin cobertura anota tres visitas, y cuando
vuelve la señal el CRM tiene que decidir qué hacer con lo que él escribió hace
dos horas y con lo que otra persona cambió mientras tanto.

- **Nada se sincroniza sin identificador del cliente.** El móvil lo genera antes
  de mandar, y por eso un reintento después de un corte no crea una visita
  duplicada. Dejar que lo genere el servidor obliga a adivinar si la petición que
  no contestó llegó o no, y esa duda no tiene respuesta correcta.
- **Una actualización dice sobre qué versión se hizo.** Sin eso no se puede
  detectar un conflicto: se aplicaría encima de lo que haya y el cambio de la
  otra persona desaparecería sin rastro.
- **El conflicto se detecta, no se evita** — y se distingue el choque de verdad
  (los dos tocaron **el mismo campo**) del que no lo es. Tratar como conflicto
  que uno cambiara el teléfono y otro la dirección enseña a la gente a pulsar
  «quedarme con lo mío», que es como se pierde el trabajo del otro igualmente.
- **Cuando lo hay, se guardan las dos versiones.** Descartar una para «no
  molestar al usuario» es descartar trabajo de alguien: que lo decida una persona
  cuesta un minuto y reconstruir lo perdido cuesta una mañana, si es que se
  puede. Y lo que se descarta **se devuelve**, porque descartarlo en silencio es
  lo que hace que nadie pueda recuperarlo después.
- **No se llama fusión a elegir uno.** Si los dos tocaron el mismo campo, la
  estrategia de fusión falla en vez de quedarse con uno y decir que fusionó.
- **La cola no descarta nada.** Una cola que tira lo que falla convierte un
  problema de red en una pérdida silenciosa de datos: el comercial cree que anotó
  la visita y no está, y lo descubre el día que alguien pregunta por ese cliente.
  Lo que lleva demasiado tiempo **se avisa**, que es distinto de tirarlo.
- **Y la notificación push no lleva el dato dentro.** Llega a una pantalla
  bloqueada que puede ver cualquiera que coja el teléfono y pasa por servidores
  de terceros: lleva qué ha pasado y dónde mirarlo, no el nombre del cliente ni
  el importe. El dato lo enseña la aplicación después de identificar a quien la
  abre.

## Change Data Capture hacia el lago del cliente (`CRM-00.02.02.06`)

Declarar el flujo, componer un cambio y avanzar la marca se piden por ruta. Lo
que antes estaba resuelto y sin puerta era precisamente lo que impide los tres
fallos de siempre.

Un cliente grande quiere sus datos del CRM en su propio lago para cruzarlos con
los del ERP y con los de producción. Lo que pide suena simple —«mándanos los
cambios»— y tiene tres formas de salir mal: el volcado completo cada noche, que
funciona con cien mil filas y deja de funcionar con diez millones justo cuando ya
dependen de él; mandar el cambio sin decir qué cambió; y mandarlo todo.

- **Se manda el hecho, no la foto.** Qué se creó, qué cambió y de qué a qué. Un
  flujo que solo dice «esta fila es ahora así» obliga al otro lado a comparar
  contra lo que tenía, y si se perdió un mensaje ya no puede: se queda con una
  foto que no sabe de cuándo es. La **secuencia** es lo que le permite saber que
  le falta algo; sin ella, un mensaje perdido no se nota, simplemente hay un dato
  viejo.
- **Se declara qué sale, campo a campo, y lo personal no sale por defecto.** Es
  lo contrario de lo cómodo —mandarlo todo y que el cliente filtre— y es lo
  correcto: lo que sale ya no vuelve, y una vez está en su lago está bajo sus
  reglas, sus permisos y sus copias. Lo que sí sale marcado como personal **viaja
  marcado**, porque el equipo de datos del cliente no va a adivinar cuál de esas
  cuarenta columnas es un correo. Y si sale sin seudonimizar, se avisa de que eso
  hay que declararlo en el registro de tratamiento como transferencia.
- **Se dice también lo que NO sale, con el motivo.** Sin esa lista, el cliente
  pide un campo y nadie sabe si es que no existe o que se decidió no mandarlo.
- **El borrado viaja como borrado**, con su identificador y sin datos, y diciendo
  qué hacer en el destino. Un CDC que omite las bajas deja un lago que crece para
  siempre con clientes que ya ejercieron su derecho de supresión, y el
  incumplimiento pasa a estar en casa del cliente sin que él lo sepa.
- **Y la marca de progreso se para en el primer fallo.** Avanzar hasta el último
  confirmado dejaría el hueco de los que fallaron en medio, y ese hueco no se
  detecta: el lago simplemente tiene un dato viejo, y se descubre cuando alguien
  cuadra cifras a fin de mes y no le salen.

## Suites de productividad: el perfil y el permiso (`CRM-06.01.03.01`, `CRM-06.01.03.02`, `CRM-06.01.03.03`, `CRM-06.01.03.04`, `CRM-06.01.03.05`)

Outlook, Gmail, Teams, OneNote, Drive. Que el CRM hable con lo que la gente ya
usa es razonable y es donde más integraciones se pudren, siempre por el mismo
sitio: alguien escribe un módulo para Microsoft, luego otro para Google, y a
partir de ahí **cada implantación nueva es una versión del producto**. Cuando el
tercer cliente pide algo raro hay tres módulos que mantener y ninguno se parece.

Aquí un proveedor es un **perfil declarado** —qué recursos ofrece, en qué
endpoint, con qué campos, cómo pide el incremento y qué límites tiene— y se
guarda como una conexión más, con el mismo conector declarativo y la misma
bóveda de credenciales que el resto de integraciones. Añadir uno es escribir
configuración.

El perfil incompleto **se rechaza**, con todos los problemas de una vez. Sin
correspondencia de campos no sustituye a nada: el dato llegaría y no se sabría
dónde ponerlo. Y si declara alcances de recursos que no va a usar, también se
rechaza — pedir permiso para algo que el CRM no lee es justo por lo que a muchas
integraciones no las dejan entrar en una empresa grande. Cuando un recurso no
admite incremento se avisa: traerlo entero cada vuelta funciona con cien
elementos y deja de funcionar con cien mil, y para entonces ya hay gente
dependiendo de ello.

Antes de conectar nada se puede preguntar **qué sabe hacer** un perfil, con el
dato de terceros marcado. Quien va a autorizar tiene derecho a saber que
sincronizar sus contactos sube al CRM el teléfono de su médico, y esa frase tiene
que poder ponerse en la pantalla del permiso.

**El consentimiento es del dueño del buzón, y solo suyo.** Un administrador puede
declarar el perfil y pedirlo; autorizarlo por otra persona, no — un administrador
que conecta el correo de su equipo entero desde una pantalla es exactamente lo
que hace que una integración acabe discutiéndose en el comité de empresa, y con
razón, porque a esa gente no le ha preguntado nadie. Se concede **recurso a
recurso**, que es lo que permite contestar después qué se autorizó: «conectó su
Microsoft 365» no es una respuesta cuando alguien pregunta si el CRM lee sus
correos.

Se comprueba **antes de cada sincronización**, no al conectar. Comprobarlo solo
al conectar deja seguir leyendo el buzón de alguien que revocó ayer, y eso no es
un fallo técnico: es leer el correo de una persona que dijo que no. Revocar, por
cierto, **no borra lo ya sincronizado** y se dice explícitamente: lo que entró
son actividades del CRM que otra gente ha usado; borrarlas es otra decisión y se
pide aparte.

De la **credencial** importa una cosa que nadie mira hasta que pasa: una
credencial con caducidad y **sin token de refresco** es una bomba de relojería —
funciona meses y un martes deja de entrar el correo de veinte personas a la vez.
Se dice ahora. Y cuando no consta caducidad no se responde que no caduca: se
responde que no se sabe.

El **incremento** lo pide cada proveedor a su manera —un token de delta, un
`historyId`, una fecha— y la marca se guarda tal cual: traducirla a un formato
común sería inventar un estándar que se rompe con el primer proveedor que cambie
de forma. Lo que sí es nuestro es la regla: **la marca solo avanza si no ha
fallado nada**. Avanzar con un fallo dentro deja un hueco que no se recupera
nunca y que nadie nota, porque no falta una pantalla: falta una reunión.

Y las **suscripciones a cambios caducan todas**. La que no se renueva deja de
llegar sin dar ningún error: el CRM se queda quieto y el usuario cree que no ha
pasado nada en su buzón. Por eso se renuevan con margen —renovar justo al caducar
deja que un reintento fallido la mate— y las que no declaran caducidad se avisan
aparte, porque son las que se mueren sin que nadie lo vea venir. Si no se puede
renovar, **se cae al sondeo** y se marca: seguir sondeando es degradarse, y
quedarse esperando avisos que ya no llegan es pararse en silencio. El usuario
tiene derecho a saber por qué su cita tarda diez minutos en aparecer.

Una última: no se admiten **dos suscripciones al mismo recurso** desde perfiles
distintos. Con dos, cada cambio entra dos veces y la ficha del cliente acaba con
la misma reunión duplicada — y nadie sospecha del segundo perfil, que alguien
configuró hace meses para probar.

## Contactos, tareas, notas, ficheros y reuniones (`CRM-06.01.03.06`, `CRM-06.01.03.07`, `CRM-06.01.03.08`, `CRM-06.01.03.09`, `CRM-06.01.03.10`)

Correo y calendario ya estaban. Esto es el resto de lo que la gente usa todos los
días y que, si no está, obliga a trabajar en dos sitios — que es como un CRM se
deja de usar sin que nadie lo decida. Cada recurso tiene su trampa, y ninguna es
técnica.

**Contactos.** No se le sube a nadie el CRM entero: se suben los que tienen
relación con esa persona. Llenarle la agenda de cuarenta mil desconocidos hace
que lo primero que haga sea desconectar la integración, y entonces se pierde
también lo que sí servía. Y solo van los campos declarados: un contacto del móvil
se sincroniza con el coche, con el reloj y con lo que tenga, así que las notas
internas de la ficha no pintan nada ahí.

En el otro sentido, **casi nada entra**. Entra lo que ya está en el CRM —para
actualizarlo— y lo que la persona marca expresamente. Lo demás es su vida
privada: su médico, su hermana, tres antiguos compañeros. Subirlo es tratar datos
personales de gente que no es ni cliente ni usuaria, sin base legal y sin
habérselo preguntado a nadie.

La regla de quién gana se declara **por campo**, no por objeto: el teléfono lo
sabe mejor el móvil de quien acaba de hablar con el cliente y el cargo lo sabe
mejor el CRM, donde lo actualiza quien lleva la cuenta; una regla única obliga a
elegir entre dos verdades. Y un **vacío del proveedor no borra**: casi siempre
significa «no lo tengo», no «bórralo», y borrar un teléfono bueno porque el otro
lado no lo trae es de lo que peor sienta.

**Tareas.** Lo que la gente espera es que cerrarla en un sitio la cierre en el
otro; es la única razón por la que alguien usa esto, y cerrar gana sobre abrir:
reabrir la tarea de quien acaba de marcarla como hecha es la forma más rápida de
que desconecte. Lo que no espera —y lo que hace desconfiar de la integración para
siempre— es que borrarla en su móvil haga desaparecer del CRM una actividad que
otras tres personas han comentado, así que **un borrado en el proveedor no borra
aquí**: se desvincula y se avisa. Si se ha tocado en los dos lados desde la
última vuelta es conflicto y decide una persona. Y la **asignación no viaja**: el
gestor de tareas personal no tiene ni idea de quién lleva esa cuenta, y dejarle
decidir eso reasignaría trabajo sin que nadie lo hubiera pedido.

**Notas.** Van **por referencia**, nunca copiadas. Una copia queda vieja el mismo
día —quien escribe sigue escribiendo en el cuaderno— y duplica el dato: si la
nota lleva lo que contó el cliente en una reunión, ahora hay dos sitios que
proteger y dos que borrar. Además, la copia se haría con las credenciales de
quien la vinculó, así que la vería gente que en el cuaderno no tiene acceso. El
permiso lo resuelve el proveedor con la identidad de quien mira, y se distingue
**«no tienes acceso» de «ya no existe»**: es la diferencia entre pedirle el
permiso a un compañero y buscar media hora algo que alguien borró hace un mes.

**Ficheros.** Igual, y con un motivo más: copiar rompe la promesa de «bórralo y
desaparece». Si el cliente borra el contrato en su Drive porque se lo han pedido
y el CRM guarda una copia, el documento que tenía que desaparecer sigue ahí. Los
permisos se resuelven en el origen — mantener aquí una segunda lista de quién
puede ver qué garantiza que se quede desfasada. Y un enlace que no se puede abrir
**lo dice en la ficha**, no al pulsarlo: quien prepara una reunión mirando la
ficha necesita saber que ese contrato no está antes de sentarse delante del
cliente.

**Reuniones en línea.** La sala se crea con el proveedor que tenga el tenant y
**no antes de que la reunión esté confirmada**: crearla al proponer la hora deja
salas abiertas de todas las que no cuajaron, siguen en el calendario de quien
aceptó, y alguien acaba entrando a una vacía convencido de que le han dado
plantón. Si el perfil no declara proveedor de reuniones, no se inventa uno:
mandar a la gente a la sala de otro producto es justo lo que el cliente no
quiere.

Y el enlace **es una credencial**: quien lo tiene entra, sin identificarse. Va en
la cita y en la ficha; no va en una notificación push —llega a una pantalla
bloqueada que ve cualquiera que coja el teléfono— ni en una página pública.

## Operar las suites: lo que se degrada en silencio (`CRM-06.01.03.11`, `CRM-06.01.03.12`, `CRM-06.01.03.13`, `CRM-06.01.03.14`, `CRM-06.01.03.15`)

Conectar es la parte fácil. Lo que decide si la integración sigue viva a los seis
meses son cosas que **no fallan: se degradan**. Una suscripción que caduca, un
proveedor que corta la cuota, un buzón que lleva una semana sin credencial. Nada
de eso pinta un error rojo en ningún sitio: el CRM se queda quieto y la gente
deja de fiarse sin saber muy bien por qué.

**Disponibilidad real.** Antes de proponer una hora se lee el calendario, y si el
calendario **no se puede leer no se propone nada**. Es el error clásico de las
herramientas de agenda: no se sabe y se propone igualmente «porque no consta
nada», y se cita a alguien encima de la reunión que ya tenía. La respuesta
incómoda y cierta —«no puedo ver su agenda»— vale más que la cómoda y falsa. Del
calendario ajeno se lee **que está ocupado, no de qué**: el asunto de una cita
puede ser «revisión médica», y para proponer una hora no hace ninguna falta. Y
cuando no hay ningún hueco se dice, en vez de enseñar una lista vacía que se lee
como un fallo.

**Chat.** Un hilo corporativo tiene la negociación, el precio y el comentario que
alguien hizo sobre un compañero. Copiarlo al CRM mete todo eso donde lo ve gente
que no estaba en la conversación, y donde se queda aunque en el chat se borre.
Va por referencia, con un resumen escrito por una persona si hace falta. Y lo que
el canal no deja exportar **no se reconstruye a trozos**: una conversación
incompleta que parece completa es peor que un enlace.

**Importar y exportar en formatos estándar.** EML, mbox, vCard, iCalendar y CSV,
**sin pasar por ninguna suite**. Es la puerta de salida, y no es un detalle de
cortesía: un CRM cuyos datos solo pueden salir por la API de un fabricante tiene
al cliente atado, y eso se descubre el día que quiere irse, cuando ya no hay
tiempo de construir nada. El paquete dice además **qué no lleva dentro** —las
notas y los ficheros están enlazados, no copiados—, porque sin esa lista el
cliente cree que se lo lleva todo y encuentra el hueco cuando ya ha apagado lo
otro. Al importar se enseña primero y se ejecuta después: deshacer a mano una
importación de diez mil filas no lo hace nadie, se queda.

**Reglas de qué entra.** Las pone el tenant y las afina cada persona, con una
regla por encima: **la del usuario solo puede estrechar, nunca ensanchar**. Si
pudiera ensanchar, la política de la empresa sería una sugerencia: bastaría con
que alguien marcara «traerlo todo» para que entrara su buzón entero. Y lo que
nunca entra —marcado como privado, carpetas personales, borradores— no es una
casilla, porque una casilla acaba desmarcada. De lo que se queda fuera se dice
**por qué**: sin el motivo, el usuario ve que no se sincroniza nada y no sabe si
es que no hay nada.

**Límites del proveedor.** Cuando corta, se le hace caso: si manda `Retry-After`,
se espera eso. Reintentar antes gasta cuota para que vuelva a decir que no y de
paso parece un ataque — y lo que hace un proveedor entonces es bloquear la
aplicación entera, a todos los clientes, no solo al que se pasó. Hay respuestas
que **no se reintentan nunca**: un 403 no se arregla insistiendo, falta un
permiso y lo que hay que hacer es decirlo. Cuando no dice cuánto esperar, la
espera crece pero **con tope**: sin él, el sexto intento espera una hora y la
integración parece muerta. Y la primera carga de un buzón con quince años de
correo se reparte, porque se comería la cuota del tenant entero y entonces el
proveedor corta a todos los demás: se usa la mitad y se deja la otra mitad para
quien no acaba de conectar nada.

## Salud, baja, identidad y diagnóstico de las suites (`CRM-06.01.03.16`, `CRM-06.01.03.17`, `CRM-06.01.03.18`, `CRM-06.01.03.19`, `CRM-06.01.03.20`)

**El panel de salud** dice qué lleva sin sincronizar, desde cuándo y por qué, por
conexión. Y la regla que lo hace útil: **lo que no se ha medido no está en
verde**. Un panel que solo cuenta lo sincronizado enseña un número que sube
mientras tres buzones llevan una semana parados — el número es verdad y la
impresión es falsa. Sin ninguna conexión no se responde «todo bien», se responde
que esto está sin usar. Una parada sin motivo anotado lo dice también, porque sin
motivo nadie sabrá qué mirar. Y las conexiones que van por sondeo salen aparte:
sus cambios entran con retraso y no al instante, y el usuario tiene derecho a
saber por qué su cita tarda diez minutos en aparecer.

**La baja.** Conviene tener escrito qué pasa antes de que haga falta. **Las
actividades se quedan y la copia de su agenda se va**: las primeras son el
registro de la empresa —quién habló con qué cliente y cuándo— y borrarlas dejaría
a la compañía sin su propia historia comercial; la segunda era suya y ya no hay
motivo para tenerla. Se destruyen el token y el refresco, porque un token vivo de
alguien que se fue es un acceso que nadie vigila. Se conserva el rastro de que
hubo consentimiento y de cuándo se revocó, porque borrarlo es borrar la prueba de
que se hizo bien. Y la suscripción **se borra también en el proveedor**: quitarla
solo de este lado deja al proveedor mandando avisos de un buzón que ya nadie
atiende, y al CRM con permiso para leerlo. Si la persona tenía acceso a un buzón
compartido, darla de baja **no** desconecta ese buzón: es del equipo.

**El registro de tratamiento** del dato que entra de la suite está declarado como
el del resto: finalidad, base legal, plazo y destinatarios, incluido el del propio
consentimiento — que también es un tratamiento, y cuya conservación es lo que
permite acreditar que se pidió.

**La identidad.** Los alias son el fallo típico: la misma persona manda desde
`j.perez@` y desde `juan.perez@`, y si cada uno se resuelve a un usuario distinto,
la misma conversación aparece dos veces en la ficha atribuida a dos comerciales.
Un buzón compartido, en cambio, **no tiene dueño**: `info@` o `ventas@` es del
equipo, y atribuirlo a quien lo conectó le pone en su nombre correos que no
escribió — cosa que acaba en la comisión de alguien. Y cuando una dirección está
declarada en dos usuarios no se elige: se dice que es ambigua, porque elegir haría
que la misma conversación se atribuyera a uno u otro según el día.

**Dónde se preguntan las dos cosas del momento malo.** En la pantalla de
**Suite**, al final, hay dos recuadros que contestan lo que uno se pregunta
justo cuando algo falla:

- *«Esto no conecta: ¿qué falta exactamente?»* — se pega el código que devuelve
  el proveedor, su mensaje tal cual, y los alcances que tiene y los que hacen
  falta. Los alcances se escriben **separados por comas, como los lista la
  pantalla de consentimiento del proveedor**: pedirlos en otro formato sería
  pedirle al consultor que haga de traductor para poder usar la herramienta.
- *«Antes de desconectar: qué se queda y qué se va»* — con el motivo elegido
  (revocó el permiso, se va de la empresa, se acaba el contrato) y **las dos
  mitades a la vez**. Enseñar sólo lo que desaparece asusta y entonces nadie
  desconecta; enseñar sólo lo que se queda engaña.

Las dos las contestaba el servidor desde el primer día y no había dónde
hacerlas.

**El diagnóstico.** «Error de autenticación» es el mensaje que atasca una
implantación una semana: el consultor no sabe si es la contraseña, el permiso, el
inquilino o el reloj, así que lo prueba todo y acaba pidiendo permisos de
administrador global «para descartar» — que es exactamente como una integración
termina con más permisos de los que nadie puede justificar. Aquí se dice qué
alcance concreto falta; o que la credencial caducó y hace falta volver a
autorizar, que es otra cosa; o que es una política del inquilino del cliente que
no se arregla desde el CRM; o que el proveedor cortó por cuota, que no es un fallo
de configuración. Y lo que dijo el proveedor se enseña tal cual. Los alcances se
comprueban además **antes de llamar**: hacerlo esperando el 403 gasta una petición
de la cuota del tenant para averiguar algo que ya se sabía.

## Golden record y linaje del dato (`CRM-01.01.04.06`, `CRM-01.01.04.07`)

Cuando el mismo cliente llega del ERP, del formulario web y de un fichero de
marketing, alguien tiene que decidir qué dirección es la buena. Lo que casi todos
los CRM hacen es lo cómodo: **gana el último que escribió**. Y eso produce fichas
que cambian solas los martes por la noche, cuando pasa el proceso del ERP, sin
que nadie entienda por qué.

**La regla es por campo y está declarada.** El NIF lo sabe mejor el ERP; el móvil
lo sabe mejor quien acaba de hablar con el cliente. Una regla única para toda la
ficha obliga a elegir entre dos verdades y se equivoca en la mitad. Hay cinco
formas de resolver —la fuente más fiable, la que cambió después, la más completa,
rellenar solo huecos, o que lo decida una persona— y cada una se equivoca de una
manera distinta, por eso están declaradas y no se improvisan.

**Lo que escribe una persona no lo pisa ningún proceso.** Quien corrige un
teléfono a mano está diciendo que el otro estaba mal.

**Y «más reciente» no es cuándo llegó el mensaje, sino cuándo cambió el valor.**
Esta es la trampa que estropea casi todas las integraciones: un ERP que reenvía
el maestro entero cada noche trae mil valores «nuevos» que son idénticos a los de
ayer, y con la fecha de llegada como criterio pisan lo que un comercial corrigió
esta mañana. Cuando una fuente no dice cuándo cambió el valor, se avisa: no es lo
mismo y tratarlo igual es lo que provoca el problema.

**Lo que pierde no se tira: se anota como discrepancia.** Si el ERP dice una
dirección y el formulario dice otra, probablemente el cliente se mudó y solo uno
se enteró — eso es información, y quedarse con una y olvidar la otra la convierte
en un misterio.

**Y un golden record sin linaje no se puede auditar.** La pregunta que llega
siempre es «¿por qué pone esto aquí?»; sin saber de qué sistema vino y cuándo, la
única respuesta honesta es «no lo sé», y esa es la que hace que alguien se abra
una hoja de cálculo al lado del CRM. Por eso se guarda de cada valor la fuente,
**cuándo cambió** y **cuándo llegó el último mensaje que lo confirmaba**, que son
dos fechas distintas: confirmar no es cambiar, y moverlas juntas haría que un dato
recién comprobado pareciera recién actualizado y falsearía todos los informes de
antigüedad.

Con eso se puede decir qué valores llevan demasiado sin confirmarse, con el plazo
**por campo** —un NIF no caduca y un cargo caduca en cuanto ascienden a esa
persona—. Y un campo del que no hay linaje **no cuenta como fresco**: no se ha
verificado nunca, que es distinto de estar al día.

El linaje **se apunta**, y lo apunta quien integra: el conector que trae el
maestro, el formulario que recoge un dato, la persona que lo corrige. Y se puede
**confirmar** sin cambiar nada: es lo que saca un valor de la cola de obsoletos
cuando alguien ha comprobado que sigue siendo bueno, sin inventarse que ha
cambiado.

Los plazos de frescura se pueden revisar antes de ponerlos en marcha. Un plazo de
**cero días** significa «siempre obsoleto», y lo que produce es una cola con todo
dentro — que nadie mira, que es peor que no tenerla. Y uno de diez años es una
forma de decir que ese campo no caduca sin escribirlo: se señala para que sea una
decisión y no un número puesto a ojo.

Del **enriquecimiento** se dice cuándo toca volver a consultar a la fuente
externa, que no es lo mismo que la antigüedad de la ficha: volver a pagar por un
dato de hace una semana es tirar presupuesto, y dejar uno de hace tres años es
trabajar con un cargo que ya no existe. Y si **nunca** se ha consultado se dice
así, no «hace mucho»: la decisión que se toma con cada uno es distinta.

## La cola de calidad y el enriquecimiento (`CRM-01.01.04.08`, `CRM-01.01.04.09`, `CRM-01.01.01.08`)

Medir la calidad del dato es fácil y por sí solo no sirve de nada: el informe que
dice «el 38 % de las cuentas no tiene sector» lo mira todo el mundo la primera
semana y nadie la segunda. Lo que arregla el dato es que **alguien concreto tenga
una cola con su nombre**.

- **Una excepción sin responsable es una estadística.** Se asigna, y las que no
  tienen a nadie se cuentan aparte: son las que no se van a hacer. Sin ese número,
  el panel enseña una cola pequeña y sana que en realidad es una vigilada y otra
  abandonada.
- **La misma regla sobre la misma ficha es una excepción, no diez.** Sin eso, el
  proceso nocturno abre otra cada noche y a la semana hay tres mil que son siete.
- **Cerrar exige decir qué se hizo**: corregido, no era un error, no se puede
  arreglar o ya no aplica. Un botón de «cerrar» a secas convierte la cola en un
  vertedero: se vacía y el dato sigue mal. Las dos respuestas que no arreglan nada
  exigen motivo, porque son las que hay que poder revisar dentro de seis meses.
- **Y «no era un error» se aprende.** Si la misma regla genera cien excepciones
  que cien personas descartan, la rota es la regla — y hay una vista que lo dice,
  porque en cuanto la mitad de la cola no es un problema se deja de abrir la cola
  entera.

Del **enriquecimiento** con fuentes externas importan dos cosas. Una, que
**cuesta dinero por llamada**: un botón de «enriquecer todo» sobre cuarenta mil
cuentas es una factura que nadie aprobó, así que se dice el coste antes y se
prioriza lo que importa — enriquecer cuentas inactivas de hace cinco años gasta el
presupuesto en fichas que nadie va a abrir. Y dos, que **no pisa lo que escribió
una persona**: un proveedor de datos sabe de muchas empresas y no conoce a
ninguna; quien acaba de hablar con el cliente sí. Rellena huecos, y lo que dice
distinto de lo que hay sale como discrepancia para la cola — puede que el dato del
CRM esté viejo, y esa es justo la conversación que interesa tener.

## Cuentas personales, plan de cuenta y estado financiero (`CRM-01.01.01.09`, `CRM-01.01.01.11`, `CRM-01.01.01.12`)

**Cuentas personales (B2C).** La tentación es crear un modelo aparte para el
particular. Con dos modelos, cada informe se escribe dos veces, la deduplicación
va por un lado y los permisos por otro, y a los seis meses uno de los dos está
peor mantenido. Es la misma cuenta con una marca — y con tres consecuencias
serias: **la ficha entera pasa a ser dato personal** (el nombre de la cuenta es el
nombre de alguien y su dirección es su domicilio, así que los derechos de acceso y
supresión aplican a la cuenta y no solo al contacto), los campos de empresa dejan
de significar nada y **no se pueden exigir** —pedirle el CNAE a un particular es
lo que hace que el comercial escriba cualquier cosa para poder guardar—, y el
identificador fiscal es el suyo, que también es dato personal.

**Plan de cuenta.** Objetivos, hueco por cubrir, mapa de poder y riesgos. Lo que
lo hace útil o inútil es una sola cosa: si el hueco se **calcula** contra lo que
ya se le factura o si lo teclea el comercial. Tecleado sale lo que él tiene en la
cabeza; calculado aparece lo que nadie había mirado. Y cada objetivo necesita
**fecha y responsable**: uno sin las dos cosas es una frase, y un plan de frases
se revisa una vez, en la reunión en la que se escribió. Por eso también se avisa
cuando un plan lleva demasiado sin revisarse — en la reunión de seguimiento se
enseña igual y nadie mira la fecha.

**Estado financiero.** Riesgo, crédito disponible, deuda vencida y bloqueo. No es
del CRM: es del ERP, y aquí vive una **proyección con la fecha del origen**, no la
de llegada. La diferencia importa el día que se bloquea una oferta: con un dato de
hace tres semanas el bloqueo es una suposición, y hay que decirlo — un comercial
deja de creerse un bloqueo que se basa en algo tan viejo. Las tres respuestas a
«¿se le puede vender más?» son **sí**, **no** y **no se sabe**, y la tercera no se
redondea a la primera: dejar pasar la oferta y descubrir el impago después es
exactamente lo que este dato existe para evitar. Un límite de crédito que no
consta no es un límite infinito, es un dato que falta. Y un bloqueo **sin motivo
no se guarda**: el comercial que se encuentra la oferta parada tiene que poder
decirle al cliente algo que no sea «el sistema no me deja».

## Mapa de influencia y cambio de empresa (`CRM-01.01.02.03`, `CRM-01.01.02.07`)

**El mapa de poder** dice quién reporta a quién, quién es aliado y quién
detractor. Dos cosas lo hacen honesto. Una: «aliado» y «detractor» son
**valoraciones sobre una persona identificada** y exigen motivo — sin el porqué es
un rumor guardado en una base de datos, y si algún día esa persona ejerce su
derecho de acceso, lo que sale es eso. «Reporta a», en cambio, es un hecho y no
necesita justificación.

Y dos: lo que de verdad aporta un mapa antes de una reunión es **con quién no se
ha hablado nunca**. Un mapa que solo enseña a los conocidos confirma lo que el
comercial ya sabía; el valor está en el decisor con el que nadie ha hablado, y eso
sale en una lista aparte.

**El cambio de empresa** empieza siempre por un indicio: un correo que rebota, una
respuesta automática de baja, la persona que aparece firmando desde otro dominio.
Ninguno es concluyente —un rebote puede ser un buzón lleno y una respuesta
automática puede ser una baja de tres meses—, así que **se abre una sospecha, no
se cambia la ficha**: cambiarla dejaría a un cliente activo marcado como que se
fue, y a nadie llamándole.

Y al confirmarlo, **no se mueve el contacto a la cuenta nueva**. Es lo cómodo y
reescribe la historia: los correos, las reuniones y lo que se habló son de la
cuenta antigua, y al moverlos esa cuenta pasa a no haber hablado nunca con nadie
— justo cuando alguien intenta entender por qué se perdió. Se crea la ficha nueva,
se enlazan las dos, y lo que queda es una razón para llamar: alguien que acaba de
llegar a otra empresa y ya conocía el producto es la oportunidad más barata que
hay, y dura pocas semanas.

Descartar un indicio también exige motivo. Sin él, el mismo rebote vuelve a abrir
la sospecha la semana que viene: dos veces es tolerable, y a la quinta se deja de
mirar la cola.

## El proveedor como parte: homologación, papeles y riesgo (`CRM-09.01.01.01`, `CRM-09.01.01.02`, `CRM-09.01.01.03`, `CRM-09.01.01.04`, `CRM-09.01.01.05`, `CRM-09.01.01.06`, `CRM-09.01.01.10`)

Un CRM que solo mira al cliente cuenta media historia. En muchos negocios **quien
da el servicio es un proveedor**, y lo que se le promete al cliente depende de lo
que sostenga él: si no está homologado, si su seguro venció el mes pasado o si es
el único que puede servir esa zona, eso decide lo que se puede vender — y no se
puede decidir en el momento de firmar.

**Un proveedor es una cuenta con rol, no un maestro aparte.** Ya existe el modelo
de partes, con su deduplicación, su jerarquía, sus direcciones y sus permisos. Uno
en paralelo duplicaría las cuatro cosas, y la misma empresa que es cliente de una
división y proveedor de otra estaría dos veces, con el riesgo de que se le
apliquen las condiciones de la ficha equivocada. El rol **se suma**, no sustituye.

**La homologación es por categoría.** «Proveedor homologado» a secas no significa
nada: homologado ¿para qué? Uno puede valer para material de oficina y no para
trabajos en altura, y tratarlo igual es como se contrata a quien no debe. No se
homologa **con salvedades** —nadie vuelve a mirar la salvedad, y el día que pasa
algo la salvedad era justo eso— ni **sin fecha de fin**, porque una homologación
eterna es una que nadie revisa y a los cinco años nadie sabe si esa empresa sigue
teniendo los medios que tenía. Al preguntar se distingue **«no está homologado» de
«se le caducó»**: la primera exige empezar el proceso y la segunda solo papel
nuevo, y confundirlas hace que se descarte a un proveedor que valdría mañana.
Y una categoría **rechazada** no se rehomologa sin mirar el motivo: rechazada no es
caducada.

**Los papeles caducan y bloquean solos.** Un certificado vencido que hay que mirar
a mano no se mira: se descubre el día que el cliente pregunta quién hizo el
trabajo y con qué seguro. Cada documento lleva su vigencia, su preaviso —renovar un
seguro lleva semanas, así que avisar el mismo día que vence es no avisar— y si
bloquea o no, porque no todo bloquea: el certificado de calidad es deseable y el
seguro de responsabilidad civil no lo es. El fichero **no se guarda aquí**, se
referencia en el gestor documental que ya existe y ya cifra: dos sitios donde
viven documentos dejan uno sin cifrar, y será el que nadie recuerda. Y si de un
proveedor no consta ningún documento se dice — eso no es que esté todo en regla, es
que no se ha pedido nada.

**El riesgo se mide por dependencia, no por opinión.** Lo que hace daño no es un
proveedor malo: un proveedor malo se cambia. Lo que hace daño es un proveedor bueno
del que sale el 60 % de lo que se sirve y que **no tiene alternativa homologada**,
porque el día que tiene un incendio no hay nada que decidir, solo que contar. Por
eso lo que se mide es la concentración y la alternativa; y sin volumen registrado
se responde que no es medible, porque sin números se puede opinar y eso es otra
cosa.

**La evaluación va con hechos.** Una encuesta anual mide la relación con el
comercial del proveedor, que es legítimo y no es el servicio. El plazo cumplido y
las incidencias sí lo miden, y son números que ya están en el sistema: no hay que
pedirle a nadie que rellene nada. Y si no hay entregas **no se puntúa** — un
proveedor al que no se le ha encargado nada no es bueno ni malo, es uno del que no
se sabe.

**Los contactos van por función**, porque la pregunta real es «¿a quién llamo
cuando esto falla a las once de la noche?». Si no hay nadie de escalado **se dice**,
en vez de devolver el comercial: su teléfono a esa hora no es una respuesta, es
media hora perdida antes de descubrir que no hay nadie. Y un contacto de escalado
sin teléfono fuera de horario se marca, porque es justo el dato que falta cuando
hace falta.

**Y la baja no es borrar una fila.** No se da de baja a quien tiene trabajo
comprometido con clientes: quitarlo del maestro no cancela lo vendido, hace que el
día de la entrega nadie sepa quién tenía que ir. Si además es el único homologado
para lo suyo, la baja **deja un hueco desde el primer día**, y eso hay que decirlo
antes porque homologar a otro lleva semanas.

## El contrato del proveedor y lo que sostiene (`CRM-09.01.01.07`, `CRM-09.01.01.08`, `CRM-09.01.01.09`)

Estas tres viven en ventas y en servicio, no en el maestro, porque deciden **qué se
puede vender**.

**El contrato avisa por lo vendido, no por su fecha.** Un aviso a treinta días de
la renovación es lo normal y llega tarde: lo que importa es si hay compromisos con
clientes **más allá del fin del contrato**, porque esos son los que se quedan sin
nadie detrás — y son los que hay que poner encima de la mesa al negociar. La fecha
límite de preaviso es además una fecha real: pasada, un contrato con renovación
automática se renueva solo aunque nadie lo quisiera, y eso se descubre con la
factura. Un contrato sin vigencia declarada no es indefinido: es que nadie lo ha
escrito, y el día que el proveedor diga que terminó no habrá con qué discutirlo.

**El alcance se declara en positivo.** Qué categorías, qué geografías, qué clientes.
Declarar lo que NO puede hacer y dar por hecho el resto es lo que hace que se le
encargue algo que no hace: la lista de exclusiones nunca está completa, porque
nadie piensa en lo que todavía no ha pasado. Y cuando no puede servir un caso se
dice **por qué**: en un caso se busca otro proveedor y en el otro se cambia lo que
se ofrece.

Las tres cosas —el estado del contrato, el alcance declarado y si puede servir un
caso concreto— se preguntan **antes de comprometer nada**, que es cuando todavía
sirven de algo. Encargar fuera de alcance no falla en el momento: falla en la
entrega, con la oferta ya firmada.

**Y el acuerdo de servicio del proveedor se compara con el que se le promete al
cliente.** Comercial promete cuatro horas de respuesta porque es lo que pide el
pliego, y el proveedor que va a ir tiene contratadas ocho. Nadie miente: es que los
dos documentos están en sitios distintos y los firma gente distinta, y **nadie los
compara**. Aquí se comparan antes de firmar, y con una corrección que se olvida
siempre: **los tiempos se suman**. Si el proveedor responde en cuatro horas y hacen
falta dos para coordinar y desplazar, lo que se puede prometer son seis —prometer
las cuatro suyas es prometer un tiempo que solo existiría si nosotros no
hiciéramos nada—. Lo que el proveedor **no declara no se da por bueno**: no es que
lo tenga bien, es que no lo ha dicho, y firmarlo así es firmar sin saber. Y se
puede preguntar al revés —qué es lo máximo que se puede prometer con este proveedor
detrás—, que es más barato que descubrirlo en la revisión legal y mucho más que
descubrirlo en la primera incidencia.

## Lo que nos cuesta: tarifas, margen y comparación (`CRM-09.02.01.01`, `CRM-09.02.01.02`, `CRM-09.02.01.03`, `CRM-09.02.01.04`, `CRM-09.02.01.05`)

Un CRM sabe poner precio a lo que se vende y, si no sabe lo que cuesta, **no puede
decir el margen** — que es lo único que un responsable aprueba o rechaza de
verdad. Aprobar por porcentaje de descuento es aprobar a ciegas: un 5 % sobre algo
que se compra caro pierde dinero y un 30 % sobre algo que se compra bien no.

Y el margen se dice **también línea a línea**. Un total sano tapa una línea
vendida por debajo de coste: la aprobación sale por el total, nadie mira dentro, y
lo que se descubre meses después es que el producto que más se vende pierde dinero
en cada unidad. Las líneas en pérdidas salen nombradas, no contadas.

Y al pedir ofertas, lo que hay que mirar es **quién no ha contestado**. Es lo que
casi nunca se enseña: si tres de cinco no han contestado, la comparación no es
entre cinco opciones sino entre dos, y decidir sin saberlo es creer que se ha
comparado el mercado cuando se ha comparado lo que llegó. Se dice también quién
llegó fuera de plazo, porque una oferta buena recibida tarde no es una opción: es
la conversación de por qué se eligió otra.

**La tarifa de coste va en el mismo motor de precios**, con el sentido cambiado.
Un motor paralelo para costes acabaría con dos formas de escalar por volumen y dos
maneras de resolver la vigencia, y una de las dos se quedaría atrás. Las listas de
coste y las de venta no se mezclan nunca: si se mezclaran, una tarifa de proveedor
podría entrar en el precio y el cliente vería lo que nos cuesta.

**Sin coste no hay margen cero: hay margen desconocido.** Un margen en blanco se
lee como «no hay margen» o como «no importa» según quien mire, y las dos lecturas
son peores que la verdad. Y una oferta con costes incompletos no tiene «un margen
aproximado»: enseñar la media de lo que sí se sabe es la forma elegante de mentir
en una hoja de aprobación, así que se dice cuántas líneas no se pueden medir y
cuáles.

**El coste se congela al ofertar.** Si la oferta recalculara el coste cada vez que
se abre, el margen que alguien aprobó en septiembre habría desaparecido en octubre
sin que nadie tocara nada, y la aprobación pasaría a referirse a unos números que
ya no existen. Cuando la tarifa cambia **se avisa y no se reescribe**: reescribir
sería lo cómodo y es lo peor, porque el comercial la manda creyendo que lleva los
números que aprobó su jefe.

**Comparar proveedores no es comparar precios.** El más barato que llega dos
semanas tarde no es la opción barata: es un incumplimiento con descuento. Y el que
no está homologado no es una opción, por mucho que su número sea el mejor. Se
devuelven **todas** con su motivo de descarte, porque quien decide necesita poder
explicar por qué no eligió la más barata, normalmente a alguien que solo ha visto
esa columna.

**La petición de oferta va ligada a la oportunidad** que la motiva: una suelta no
se cierra nunca —nadie sabe si aquello se ganó o se perdió— y acaba en una lista
de cosas abiertas que nadie limpia. Con fecha límite real, porque sin ella la
respuesta llega cuando el cliente ya ha decidido y el precio que se le dio se puso
a ojo. Y al recogerlas se dice **quién no ha contestado**: si tres de cinco no
responden, la comparación no es entre cinco opciones, y decidir sin saberlo es
creer que se ha comparado el mercado.

## Capacidad, plazo, reparto y coste real (`CRM-09.02.01.06`, `CRM-09.02.01.07`, `CRM-09.02.01.08`, `CRM-09.02.01.09`, `CRM-09.02.01.10`)

**La capacidad descuenta lo ya comprometido.** Una cuota que solo mira lo
contratado deja vender tres veces lo mismo, y eso se descubre en la semana de la
entrega, cuando ya no hay margen para nada. Se enseña aparte lo que está **en
ofertas abiertas**: todavía no es un compromiso, pero si se ganan todas tampoco
cabe — y esa conversación es mejor tenerla antes de mandar la cuarta oferta que
después. Reservar por encima de lo disponible se puede, y entonces **queda dicho
que se forzó**: dejarlo pasar «porque ya se arreglará» convierte un problema de
planificación en una llamada al cliente el día de la entrega.

**El plazo del proveedor decide la fecha que se promete**, y no al revés. Prometer
primero y buscar después quién lo cumpla es exactamente el orden que produce los
retrasos, y deja al comercial en una posición imposible. Al plazo del proveedor se
le suma el nuestro —coordinar, preparar, entregar—, porque prometer solo el suyo
es prometer un plazo que existiría si nosotros no hiciéramos nada. Y si el
proveedor no declara plazo **no se inventa una fecha**: se dice que todavía no se
puede prometer, que es incómodo y es verdad.

**El reparto entre proveedores sigue una regla declarada** —menor coste, más
capacidad libre, menor plazo o el acuerdo que haya—. Sin regla reparte quien monta
la oferta, y cada uno lo hace de una manera: normalmente con el de siempre, que es
como se llega a depender de un proveedor sin que nadie lo haya decidido. Si no
cabe entero se dice **cuánto falta**, en vez de repartir lo que hay y dejar el
resto sin asignar sin avisar.

**El rappel estimado no es dinero.** Depende de llegar al tramo, y si el año se
tuerce no se llega: se marca como estimado hasta que el periodo se cierra. Y se
imputa **al periodo, no a las ofertas que lo generaron** — repartirlo hacia atrás
haría que una oferta pareciera rentable por algo que todavía no ha pasado.

**Y el margen de verdad se sabe cuando llega la factura del proveedor.** Casi
nadie vuelve a mirarlo, y por eso las empresas descubren que un tipo de trabajo
pierde dinero después de haberlo vendido veinte veces. Se compara **pedido a
pedido**, porque una media del 3 % esconde diez pedidos clavados y uno que se fue
al 40 %, y ese es el único que enseña algo. Lo que todavía no se ha facturado **no
cuenta como acertado**: contarlo por su coste previsto es lo que hace que estos
informes mientan siempre en la misma dirección. Se pide además **dónde** se fue la
diferencia —«el coste subió» no sirve de nada; «subió en el transporte de las
entregas fuera de la península» cambia la próxima oferta—. Y de un proveedor con
menos de tres pedidos medidos **no se concluye**: dos desviaciones seguidas pueden
ser dos casualidades, y colgarle la etiqueta de impreciso por eso es injusto y
hace que nadie se crea el informe. Con datos suficientes, en cambio, la
conversación cambia: un proveedor que siempre acaba costando un 15 % más no es
caro, es **impreciso**, y eso es peor — sus ofertas no sirven para decidir.

## Modelos entrenados con el histórico (`CRM-02.01.02.02`, `CRM-02.01.02.06`, `CRM-02.01.01.08`)

Un modelo entrenado con el histórico de conversión es lo más útil y lo más
peligroso que hay en un CRM, por una razón que casi nunca se dice en voz alta:
**aprende lo que hizo el equipo comercial, no lo que funciona**. Si durante tres
años solo se llamó a las empresas grandes de Madrid, el modelo concluirá que esas
convierten — tendrá razón en los datos y estará equivocado en el mundo. Por eso,
antes de entrenar, se dice qué sesgo trae el histórico que hay.

**Se exige tamaño y equilibrio.** Con cuarenta casos y tres ganados no sale un
modelo: sale una superstición con decimales, y decirlo antes es lo único que evita
que alguien tome decisiones con ella durante un año. Un modelo que casi no ha
visto perder aprende a decir que sí.

**Se prueba contra un periodo que no ha visto**, y la separación es por fecha, no
al azar: repartir aleatoriamente mete casos posteriores en el entrenamiento, el
modelo ve cómo acabó lo que tiene que predecir y el acierto sale magnífico y
completamente inútil — en producción no existe el futuro. La separación **se pide
y se devuelve**: qué casos entrenan, cuáles comprueban y por qué fecha se cortó.
Un caso **sin fecha de cierre la para** y se dice cuántos son, porque sin fecha no
hay más remedio que repartir al azar, que es justo lo que se está evitando. Y con
menos de dos casos no se parte nada: uno de los dos lados se quedaría vacío, y un
modelo comprobado contra cero casos da un número que no significa nada.

**Y se compara con la regla tonta.** Si solo se gana el 15 %, decir «todos
pierden» acierta el 85 % de las veces: un modelo con un 86 % suena bien y no
aporta nada, y con ese número se justifica un proyecto entero. Es la comparación
que nadie hace y la que decide si el modelo sirve. Se enseñan además los **falsos
negativos**, que son los que duelen: las oportunidades que el modelo descartó y se
ganaron son las que nadie habría llamado.

**Los porqués van siempre**, ordenados por cuánto empujaron, y con los que
**restan** también: un panel que solo cuenta lo que suma hace pensar que la
puntuación es baja por falta de datos cuando puede ser por algo concreto que se
puede arreglar. Una puntuación sin explicación se mira una vez, no coincide con lo
que el comercial sabe de su cliente y a partir de ahí no se mira más — y hace
bien, porque él estuvo en la reunión y el modelo no.

**Lo que no puede entrar en el modelo no entra**: sexo, edad, nacionalidad, y el
código postal como sustituto de todo lo anterior. Un modelo que decide a quién se
llama con esas variables es discriminación con un informe bonito delante, y se
rechaza **al declararlo**, no al usarlo.

De ahí sale también la **segmentación predictiva**: un segmento definido por
propensión en lugar de por filtros, con la advertencia que lo hace honesto —
**cambia solo**. La lista de hoy no es la de la semana que viene, y comparar los
resultados de dos ejecuciones es comparar dos audiencias distintas creyendo que
son la misma. Y un modelo **no avisa cuando deja de valer**: sigue dando números
con la misma seguridad, así que se vigila si el mix de casos se ha movido desde
que se entrenó.

## Transcripción, resumen y compromisos (`CRM-01.02.01.05`, `CRM-01.02.01.06`)

Lo que hace que un comercial no registre una reunión no es la pereza: es que
escribirla cuesta diez minutos que no tiene. Transcribir y resumir se los ahorra,
y por eso es de lo que más se usa cuando funciona. Los problemas que trae no son
técnicos:

**Grabar a alguien sin decírselo es ilegal en media Europa y una ruptura de
confianza en la otra media.** El permiso es la primera comprobación, antes de
mandar nada a transcribir — el cliente que se entera después no vuelve a hablar
con soltura delante de nadie.

**Una transcripción no es un acta.** El modelo confunde nombres, se pierde con dos
personas hablando a la vez y traduce mal las cifras: se guarda con su nivel de
confianza, y por debajo de ese nivel no se propone ningún dato a partir de ella.
La **atribución de quién dijo qué** es lo menos fiable de todo y se marca como
tal: en una llamada a tres, poner una frase en boca de quien no la dijo puede
cambiar una negociación.

**Y un compromiso extraído es una propuesta, no una tarea.** «Te mando la oferta
el jueves» y «si me la mandas el jueves, la miro» se parecen mucho en un texto y
significan lo contrario. Crear la tarea directamente llena la agenda de
compromisos que nadie adquirió, y entonces se deja de mirar la agenda. Un
compromiso **sin dueño tampoco se propone**: asignárselo al comercial por defecto
le llena la lista de cosas que dijo el cliente.

Se guarda **lo que propuso el modelo y lo que quedó**, porque de las correcciones
es de donde se sabe si esto sirve. Y el número que decide si se sigue usando es
cuánto hay que corregir: por encima del 40 % no ahorra tiempo, lo cambia de sitio
—de escribir a revisar, que cansa más—. Transcribir, además, cuesta dinero por
minuto: una biblioteca de tres años de llamadas es una factura, no un botón, y se
dice antes.

## Variantes de texto y hora de envío (`CRM-02.04.01.04`, `CRM-02.02.02.05`)

Generar cinco versiones de un asunto es de lo más barato que hace un modelo y de
lo que más se agradece: la sexta variante a mano un viernes por la tarde no la
escribe nadie, y por eso se manda siempre la primera que salió. Lo que hay que
resolver no es generar, es qué pasa con lo generado.

**Nada sale sin que una persona lo apruebe**, y no hay aprobación en bloque sin
leer: el texto lleva el nombre de la empresa y quien lo firma tiene que haberlo
leído. Permitir el atajo «por comodidad» lo convertiría en la única forma que se
usa. **Las afirmaciones comprobables se marcan** —«un 40 % más rápido», «el mejor
del mercado», «garantizado»—: un modelo las escribe con la misma naturalidad con
la que escribe «buenos días», y el revisor que lee deprisa no distingue lo uno de
lo otro.

**La ganadora se elige con datos o no se elige.** Con doscientos envíos por rama,
la diferencia entre un 4,1 % y un 4,4 % es ruido: declararla ganadora convierte el
azar en una decisión de marca que luego se repite dos años porque «los datos lo
decían». Y se mide cuánto se reescribe de lo propuesto: si es casi todo, el modelo
da un punto de partida —que también vale— pero no es lo que se vendió.

De la **hora y el canal** por destinatario, lo importante es cuándo *no* se puede
personalizar: con pocas interacciones, lo que se optimiza es el ruido. Concluir
que alguien prefiere las tardes porque abrió dos correos por la tarde es echar una
moneda dos veces y creerse el resultado, así que por debajo del mínimo se usa la
hora del segmento y se dice. El canal se mide **por respuesta, no por apertura**:
abrir un correo no significa nada, y optimizar por aperturas lleva a escribir más
a quien los abre y nunca contesta. Lo que la persona pidió manda sobre lo que dice
el modelo — si dijo que no se le llame, eso no es una preferencia estimada, es una
instrucción. La franja es **la suya**, que es el fallo más tonto y el más
frecuente: la campaña «a las nueve» llega a las tres de la mañana a quien está en
otro huso. Y se dice cuántos envíos van a la hora general: si es el 90 %, la
personalización no está haciendo nada, y conviene saberlo antes de contarlo como
una mejora.

## Sugerencia semántica en el caso y campos explicados (`CRM-04.03.01.04`, `CRM-00.04.03.07`)

Un agente con un caso abierto no quiere buscar: quiere que le pongan delante los
tres casos parecidos que ya se resolvieron y el artículo que los explica. Eso
ahorra la llamada al compañero veterano, que es el cuello de botella real de
cualquier servicio. La búsqueda por palabras se queda corta aquí —el cliente
escribe «no me va el correo» y el artículo dice «configuración IMAP»— y la
semántica trae sus propios problemas:

- **Un resultado sin cita no vale.** Sin poder abrir la fuente, el agente tiene
  que creerse un párrafo generado y responder con él; cuando esté mal, y alguno
  estará mal, no habrá forma de saber si falló el dato o el modelo.
- **Lo parecido no es lo aplicable.** Dos casos pueden hablar de lo mismo y ser de
  productos, versiones o contratos distintos: se enseña en qué coinciden y en qué
  no, y lo decide el agente.
- **No se sugiere lo que no se ha resuelto.** Un caso parecido que sigue abierto
  no es una solución: es otro que tiene el mismo problema.
- **Los permisos se aplican antes de indexar**, no al filtrar resultados. Filtrar
  después ya ha metido en el índice el contenido de casos que ese agente no puede
  ver, y basta con que un fragmento salga en un resumen. Lo que se descarta por
  permiso ni siquiera dice de qué iba — decir «hay un caso parecido que no puedes
  ver» ya filtra información sobre otro cliente.
- **Y al modelo no se le manda el nombre de quien tiene el problema**: para
  encontrar casos parecidos hace falta el problema, no la ficha. El recorte lo
  hace el servidor y no la pantalla que llama —si lo decidiera cada pantalla,
  bastaría con que una lo decidiera mal—, y la respuesta lleva **lo que salió y
  contra qué se comparó**, para que no haya que creérselo.

Nada de esto funciona si los campos del tenant no significan nada. Un tenant crea
`cmp_2`, de tipo lista, con valores `A`, `B` y `C`: para el CRM es perfecto y para
cualquier cosa que tenga que **razonar** es basura. Por eso los campos
personalizados se describen, y se exige que la descripción **diga algo más que la
etiqueta** —«Segmento: segmento» es la forma más común de rellenarlo y deja el
catálogo igual de inútil, con la diferencia de que ahora parece completo—. Los
valores de una lista se explican uno a uno: saber que `C` significa «cliente en
revisión de crédito» cambia lo que se puede preguntar.

**Un campo no se explota hasta que alguien lo decide.** Los campos nacen fuera del
contexto y sólo entran cuando se describen y se marcan como explotables: un campo
que acaba en un contexto de inferencia porque sí es exactamente lo que no se
quiere, y el valor por defecto es el que decide eso en la práctica.

**Y lo sensible no sale aunque se marque explotable.** Qué es sensible no se
declara al describir el campo: sale de la clasificación que el campo ya tiene
—`confidencial`, `personal` o `especial`—, que es la misma de la que salen el
enmascaramiento por rol y el mapa de datos personales. Si se pudiera declarar
aparte, bastaría con decir «esto no es sensible» sobre un campo clasificado como
dato de salud para que saliera; y con dos sitios donde marcarlo, tarde o temprano
dicen cosas distintas y no se sabe cuál manda.

Y se publica la **cobertura**: con el 30 % de
los campos descritos, la IA entiende el 30 %, y la distancia entre eso y lo que la
gente cree que compró es la razón de la mayoría de los proyectos de IA
decepcionantes.

## La salud del cliente donde se ve (`CRM-01.01.05.07`)

La salud se calcula en el servicio de inteligencia, que es donde están las señales
y los pesos. Pero quien tiene al cliente delante abre **la ficha de la cuenta**, y
un número que solo existe en otro servicio no lo ve nadie — con lo cual no cambia
ninguna conversación, que era todo el objetivo. Como ningún servicio lee el
esquema de otro, llega por evento y se guarda una copia local.

De ahí salen tres decisiones:

**La copia lleva su fecha.** Un 42 en rojo de hace tres meses no es una alerta: es
un recuerdo, y llamar por él molesta a un cliente cuyo problema ya se resolvió.

**La fiabilidad viaja dentro del evento.** Si se quedara en el otro lado, aquí se
pintaría un número calculado con la mitad de las señales sin saberlo — y eso es lo
que hace que la lista de clientes en riesgo deje de mirarse.

**Y una medida vieja no pisa a la buena.** Los eventos llegan desordenados, y una
reentrega antigua haría que la ficha volviera a decir «en riesgo» un mes después
de que se arreglara.

Las tres respuestas posibles son distintas y ninguna se redondea a otra: hay
medida fiable, hay medida que no vale para actuar, y **no hay medida** — que no es
«va bien», es que nadie lo ha calculado, normalmente porque faltan las señales. La
lista de cuentas en riesgo deja fuera las poco fiables y las caducadas y las
cuenta aparte: una lista donde la mitad son falsos positivos se abre dos veces y
no se abre más, y entonces se pierden también los que sí lo estaban. Y desde esta
copia **no se dispara nada automático**: llegaría con retraso y mandaría correos
de retención a quien renovó ayer.

## Ingresos recurrentes, calendario y reparto (`CRM-03.01.01.06`, `CRM-03.01.01.07`, `CRM-03.01.01.08`)

Una oportunidad con un importe y una fecha vale para un negocio de venta puntual.
En cuanto hay suscripciones, servicios recurrentes o entregas por fases, ese
número **deja de significar nada**: 120.000 puede ser un pedido que se factura el
mes que viene o un contrato de tres años, y sumarlos en el mismo forecast produce
una previsión que nadie cumple y que nadie sabe por qué no cumple.

**Lo recurrente y lo puntual se separan siempre.** Y el ARR no es el importe
dividido por los años: un contrato de dos años con la implantación cobrada aparte
tiene un ARR que no se parece a su valor total, y mezclarlos infla la métrica con
la que se valora la empresa. Cada línea dice de qué tipo es, y lo que no es
recurrente no entra en el ARR por mucho que se repita todos los años.

**El calendario de ingreso es lo que usa la previsión de caja.** Una oportunidad
grande que se cobra en doce meses no es un mes bueno: son doce meses decentes, y
la diferencia decide si alguien contrata a un comercial más o si se para una
inversión. Es distinto del forecast por fecha de cierre y hacen falta los dos —
una cosa dice cuándo se firma y la otra cuándo entra el dinero, y confundirlos hace
que un trimestre «excelente» no se note en caja hasta el siguiente. El redondeo se
ajusta en el último periodo: si sobrara un céntimo, la suma del calendario no
cuadraría con el importe y ese descuadre aparecería en un informe seis meses
después sin que nadie supiera de dónde sale.

**Y el crédito entre comerciales suma 100 o no se guarda.** Es la regla más tonta
y la que más se salta: con repartos al 60/60 las comisiones cuadran hacia arriba y
el descuadre lo encuentra finanzas tres meses después, cuando ya se ha pagado. El
**overlay** es otra cosa —apoyo que se reconoce sin quitarle nada al titular— y
por eso puede sumar lo que sea; mezclarlo con el crédito es justo lo que hace que
la gente invente porcentajes para que cuadre.

## Grupo de compra y oportunidades relacionadas (`CRM-03.01.01.10`, `CRM-03.01.01.11`, `CRM-01.01.02.04`)

**El grupo de compra no es una lista de contactos.** Lo que hace falta saber es
quién decide, quién aprueba el gasto, quién recomienda, quién lo va a usar y quién
controla el acceso a los demás. Con texto libre, «interlocutor» acaba siendo el
80 % de los contactos y no dice nada, así que los papeles son una lista cerrada.

Lo que de verdad aporta el mapa **es lo que falta**: una oportunidad sin decisor
identificado no está avanzada por mucho que el presupuesto esté mandado, y un
económico con el que nadie ha hablado es la razón más habitual de que un cierre
«seguro» se caiga en la última semana. Y decir que alguien está en contra **exige
motivo**: es una etiqueta que otro comercial leerá dentro de seis meses y aplicará
sin poder contrastarla, y además es una valoración sobre una persona identificada.

**Una oportunidad relacionada dice de qué tipo es la relación** —renovación,
upsell, cruzada, sustitución o ampliación—, y eso cambia el informe: una
renovación que sustituye a un contrato **no es ingreso nuevo**, y contarla como tal
duplica el crecimiento del trimestre. Es de los errores que más tarda en
descubrirse, precisamente porque el número sale bien; la corrección llega cuando
alguien cruza con facturación.

## Plan conjunto y revisión de oportunidad (`CRM-03.01.02.05`, `CRM-03.01.02.06`)

Dos prácticas que funcionan y que casi ningún CRM soporta, con lo cual acaban en
una hoja de cálculo compartida por correo — y ahí mueren.

**El plan conjunto** es una lista de pasos con fechas que acuerdan las dos partes.
Su valor está casi entero en una cosa: **obliga al cliente a comprometerse con
fechas**. Un cliente que no quiere poner fecha a su propia parte está diciendo algo
importante, y lo dice antes de que se haya invertido un trimestre. Por eso se
exige que haya pasos suyos: un plan donde todos los pasos son nuestros es una lista
de seguimiento interna con otro nombre, y el cliente ni la mira. Cada paso lleva
fecha y responsable, porque sin ellas es una lista de buenas intenciones que se
enseña en la reunión y no se mira entre reuniones.

Al mirar cómo va, lo importante es **de quién es lo que se retrasa**. Si es
nuestro, se aprieta dentro; si es del cliente, la fecha de cierre que hay en el
CRM es una ilusión — y eso es lo que hay que contar antes de que llegue el final
del trimestre, no después. Un paso **conjunto** retrasado va en su propio grupo y
no en el del cliente: depende de los dos, así que ni se arregla apretando dentro
ni esperando fuera, y meterlo entre los del cliente es la lectura cómoda — la que
deja de apretar. Y si el cliente no ha visto el plan, se dice: un plan «conjunto»
que solo hemos leído nosotros es nuestro plan.

**La revisión de oportunidad** es la conversación en la que un jefe pregunta por
qué esto va a cerrar. Sin estructura se convierte en «¿cómo lo ves?» y en un
número que sube porque el comercial es optimista — no porque mienta, sino porque
está metido dentro. Se exigen las preguntas incómodas, que son las que la gente se
salta: **qué puede salir mal** y **qué falta por saber**. Y los acuerdos llevan
dueño y fecha: «hay que hablar con el director financiero» sin quién ni cuándo es
la misma reunión repetida dentro de dos semanas.

Lo que justifica guardarlas es poder **compararlas con lo que pasó**. Si todo lo
que se revisa al 80 % se gana la mitad de las veces, el 80 % no significa 80 %:
significa «me gusta este caso», y el forecast construido con eso no cuadra nunca.
El resultado de cada revisión se anota **al cerrar la oportunidad**, que es el
único momento en que se sabe: pedirlo aparte significa que no lo pide nadie, y
entonces la comparación no se puede hacer por mucho archivo que haya.
Con menos de diez revisiones cerradas no se concluye: llamar optimista a un equipo
con seis casos es injusto y le quita credibilidad al ejercicio entero. Y se revisan
las grandes y las avanzadas, no todas: revisar cien oportunidades pequeñas al mes
es lo que convierte las revisiones en un trámite que nadie prepara.

## Métricas del cliente y motor de compensación (`CRM-01.01.05.06`, `CRM-03.02.03.04`)

**Las métricas del cliente** —facturación, margen, pedidos, incidencias, NPS y
morosidad— no son del CRM: viven en el ERP, en el sistema de soporte y en la
herramienta de encuestas. Y precisamente por eso hay que traerlas, porque un
gestor que para preparar una reunión tiene que abrir tres sistemas acaba
preparándola con lo que recuerda.

Todas las decisiones van sobre lo mismo: **una copia con retraso puede hacer más
daño que no tener el dato**. Cada métrica lleva de cuándo es y de dónde viene —un
margen sin fecha se lee como el de hoy, y si es de hace un trimestre el gestor
negocia con un número que ya no existe—. Lo que no ha llegado **no vale cero**:
«cero incidencias» y «no tenemos el dato de incidencias» se pintan igual en un
panel y significan lo contrario, uno es un cliente tranquilo y el otro una
integración caída. Un dato más viejo no pisa al bueno. Y **no se calcula nada
encima**: sumar el margen de dos fuentes o derivar un ratio produce un número que
no existe en ningún sistema, y cuando finanzas pregunte de dónde sale la respuesta
será «lo calcula el CRM», que es la peor posible. Hay además una vista de si las
métricas siguen llegando, porque el fallo aquí es silencioso: la integración se
cae, los paneles siguen enseñando los últimos números y nadie lo nota hasta que
alguien comenta que un cliente «lleva mucho sin facturar».

**Del motor de compensación**, lo que tiene que hacer bien el CRM no es calcular:
es dar los hechos y aceptar el resultado. Calcular comisiones dentro funciona
hasta el primer plan de verdad —aceleradores por tramo, topes, garantías,
clawback, repartos entre equipos, reglas que cambian a mitad de año con efecto
retroactivo—; eso no es un cálculo, es un producto, y hay empresas que lo fabrican.

- **Se manda el hecho, no la comisión.** Si el CRM envía un importe ya calculado
  «para ayudar», acaba habiendo dos cálculos y la nómina se hace con el que no es.
  El reparto sí va, porque el CRM es quien sabe quién vendió qué, y también tiene
  que sumar 100.
- **El cálculo llega de vuelta y no se recalcula aquí.** Enseñar una comisión
  distinta de la que se va a cobrar es la forma más rápida de que nadie se crea
  ninguna de las dos, y de que el comercial se haga su propia hoja de cálculo —
  que es donde empieza cualquier discusión de comisiones.
- **Un cierre que cambia después obliga a decirlo, no a corregirlo en silencio.**
  Se llama clawback y es una conversación: quitarle dinero a alguien de la próxima
  nómina sin avisar es lo que hace que un equipo deje de confiar en el sistema, y
  con razón.
- **Y lo que se mandó y no ha vuelto se comprueba antes de cerrar el periodo.** Un
  hecho perdido por el camino no da ningún error: esa venta simplemente no aparece
  en la comisión de nadie, y lo descubre el comercial al mirar su nómina.

## Audiencias publicitarias, retargeting y canales offline (`CRM-02.01.01.09`, `CRM-02.03.02.04`, `CRM-02.03.02.05`)

Sincronizar una audiencia con una plataforma de anuncios es de las cosas más
fáciles de hacer y de las que más problemas legales dan, porque lo que se manda es
**una lista de personas a un tercero que la usa para perfilar**. Y casi siempre se
hace sin mirar nada: se filtra un segmento, se pulsa «sincronizar», y a partir de
ahí esa lista vive fuera, se actualiza sola y nadie sabe quién está dentro.

- **Sin base legal para publicidad no sale nadie**, y no vale el consentimiento
  del boletín: aceptar correos comerciales no es aceptar que tu dirección se suba
  a una red de anuncios. Se comprueba **persona a persona**, porque un segmento
  «clientes activos» tiene dentro gente que nunca aceptó publicidad y mandarlo
  entero porque el segmento parece inocuo es exactamente como pasa.
- **Lo que sale va troceado**, nunca en claro. No es una formalidad: es la
  diferencia entre mandar una lista de correos y mandar identificadores que solo
  sirven para cruzar.
- **Una baja aquí es una baja allí, y el mismo día.** Es el punto donde todas
  estas integraciones fallan: darse de baja en el CRM y seguir viendo anuncios es
  lo que la gente denuncia, y con razón, así que la baja no espera al ciclo normal.
- **Las audiencias pequeñas no se mandan.** Con veinte personas la plataforma no
  puede anonimizar nada y el segmento se convierte en señalar a alguien con el
  dedo.
- **Y en retargeting no se persigue a quien ya compró** —es la queja más habitual
  de cualquier campaña y da imagen de no saber con quién se habla— ni a quien se
  dio de baja: un anuncio no es un correo, pero para la persona es la misma
  empresa siguiéndole después de haberle dicho que no.

**El canal offline** —correo postal y telemarketing— es un paso del recorrido como
los demás con una diferencia que lo cambia todo: **no se puede cancelar**. Una
carta impresa ya está impresa y una llamada hecha no se deshace, así que la
comprobación va antes del lanzamiento y el recorrido tiene que poder pararse en el
paso anterior. Cuesta además dinero por unidad y mucho: mandar diez mil cartas por
error no es un incidente, es una factura. Quien está en una lista de exclusión no
entra —llamar a alguien que está en Robinson es una sanción, no un descuido—. Y al
medir resultados se dice lo que no se puede saber: **una carta no tiene apertura
ni clic**, lo único medible es lo que vuelve, y fingir métricas de digital en un
canal que no las tiene hace que las comparaciones entre canales no valgan nada.

**En la personalización web**, un visitante que no se ha identificado no es «uno
cualquiera» al que enseñarle algo: es alguien de quien no se sabe nada, y se le
sirve lo genérico — adivinar por IP o por el dispositivo produce personalizaciones
que dan entre risa y susto. La regla que se aplica **se devuelve**, porque cuando
el cliente pregunte por qué a su director le salió el bloque de «pymes» la
respuesta no puede ser «lo decide el algoritmo». Y lo que rompe una
personalización no es una regla mal escrita: son **dos reglas que encajan a la vez
sin prioridad declarada**, y entonces el contenido depende del orden en que
lleguen de la base, cambia solo y nadie puede reproducirlo.

## Biblioteca de activos y aprobación de contenidos (`CRM-02.04.01.01`, `CRM-02.04.01.02`)

Una biblioteca de activos se monta, se suben trescientos ficheros y a los seis
meses nadie encuentra nada y todo el mundo sigue mandando el PDF por correo. Lo
que la salva o la hunde no es el buscador: es **si lo que hay dentro se puede usar
sin preguntar**.

- **Un activo sin vigencia es un activo caducado esperando.** El folleto con los
  precios del año pasado sigue ahí, alguien lo manda y el cliente pide ese precio.
  Lo vencido no se borra —hace falta para saber qué se mandó— pero deja de poder
  usarse.
- **Los derechos de uso van dentro.** Una foto de banco con licencia para web no
  vale para una valla, y esa diferencia la conoce quien la compró y nadie más:
  sin ella la biblioteca es una fuente de problemas legales con buscador. «Uso
  general» no existe en ningún contrato.
- **La versión nueva no borra la anterior.** Lo que se mandó al cliente el martes
  tiene que poder recuperarse aunque el jueves se corrigiera una errata.
- **Y lo que no declara vigencia es lo más peligroso**: nunca aparecerá en ninguna
  lista de caducados, así que se queda ahí para siempre. Sale en su propia lista.

Al preguntar si algo se puede usar, las tres respuestas negativas son distintas y
llevan a acciones distintas: **no está aprobado** (falta una firma), **ha
caducado** (hay que renovar o rehacer) y **no cubre este uso** (hay que comprar
otra licencia o buscar otra pieza).

**La aprobación** es de personas y va **antes de publicar**: un flujo donde el
contenido sale y luego alguien revisa es un flujo sin aprobación, porque lo que
está fuera, fuera está. Cada paso tiene un aprobador concreto —«que lo vea
marketing» no lo ve nadie, porque nadie en particular lo tiene asignado—, rechazar
exige comentario —un rechazo sin motivo devuelve el trabajo al principio y la
segunda versión suele traer el mismo problema— y nadie aprueba en nombre de otro,
que dejaría una firma que no corresponde con quien miró el contenido. Un rechazo
**para el conjunto**: seguir pidiendo las firmas siguientes es hacer trabajar a
gente sobre algo que va a cambiar. Y se anota si el aprobador **vio qué cambió**,
porque revisar treinta páginas enteras cada vez es lo que hace que se apruebe sin
leer, y ese número dice si el flujo sirve o es un trámite.

## Redes sociales (`CRM-04.02.01.06`)

Una queja en público no es un caso más: es un caso **con testigos**. Y ahí está
todo lo que hace distinto este canal, porque recoger mensajes, abrir un caso y
contestar ya lo hace la omnicanalidad.

- **No todo lo que menciona a la marca es un caso.** Un «gracias por el envío
  rápido» no necesita un expediente con SLA, y meterlo en la cola hace que el
  agente aprenda a cerrar sin leer — y entonces se dejan de mirar todos, incluidos
  los cuatro que sí eran una queja.
- **Lo público se contesta en público y lo demás en privado.** Contestar un
  problema concreto en un hilo abierto obliga al cliente a dar datos suyos delante
  de todo el mundo; no contestar nada en público deja la queja sola en el hilo,
  que es lo que la gente lee.
- **El tiempo se mide en minutos.** Una respuesta a las veinticuatro horas es
  normal en correo y en una red social es una captura de pantalla circulando con
  el reloj al lado. Y las menciones **sin contestar** se cuentan aparte: una media
  de treinta minutos calculada solo sobre las contestadas esconde las cinco que
  nadie ha mirado.
- **Lo que se publica en nombre de la marca lo escribe una persona.** Una
  respuesta automática a una queja pública convierte a un cliente enfadado en un
  hilo viral, y la frase «entendemos tu frustración» generada por una máquina se
  reconoce a la primera.
- **La crisis se detecta por cambio de ritmo, no por un número fijo.** Veinte
  menciones a la hora son normales para una marca grande y un incendio para una
  pequeña; un umbral fijo solo funciona para el tamaño con el que se escribió. Con
  menos de seis horas de historial no se concluye: un pico un martes puede ser un
  anuncio que salió bien.
- **Y del perfil se guarda lo justo.** Un perfil público sigue siendo dato
  personal, y traerse su biografía y su historial «por contexto» es crear la ficha
  de alguien que nunca nos dio nada — y esa ficha hay que protegerla, conservarla
  y borrarla como cualquier otra.

## Telefonía, marcador y voz (`CRM-04.02.01.05`, `CRM-03.03.01.05`, `CRM-04.02.01.08`)

Lo que se le pide a una integración de telefonía es que **cuando suene el teléfono
ya esté la ficha abierta**. Suena a comodidad y no lo es: son quince segundos por
llamada buscando quién llama, multiplicados por doscientas llamadas al día, y
sobre todo es el cliente contando otra vez lo mismo.

Se identifica por el número **y se dice con qué confianza**: una ficha, varias o
ninguna, y abrir la primera de tres «porque suele ser esa» hace que el agente
salude por el nombre equivocado, que es peor que no saludar por ninguno. La
comparación es por el final del número, porque el mismo teléfono aparece como
`+34600…`, `0034600…` y `600…` según quién lo escribiera — y comparar
literalmente hace que el aviso no salte justo con los clientes de toda la vida,
que son los que están mal escritos. Lo que el cliente **ya tecleó en el IVR viaja
con la llamada**: volver a pedírselo al descolgar es la forma más rápida de que se
enfade antes de empezar. La **transferencia lleva contexto o no es una
transferencia** —pasar la llamada sin lo hablado obliga al cliente a empezar de
cero, que es literalmente la queja número uno de cualquier servicio—. Y la llamada
se registra pase lo que pase: una perdida es un cliente que lo intentó, y si no
consta, el panel enseña un servicio impecable construido solo con las que se
atendieron.

**Del marcador**, lo difícil no es lanzar la llamada: es lo que pasa al colgar. La
actividad se crea **sola** con lo que el sistema sabe, porque pedirle al comercial
que anote cada llamada es pedirle el 20 % de su día —no lo hace, y entonces el CRM
dice que ese cliente lleva tres meses sin contacto cuando se habló el martes—. Lo
que **no se inventa** es qué se dijo: «contestada, 3 minutos» no es información
comercial, y rellenar la nota con una frase genérica es peor que dejarla vacía,
porque parece que hay contenido. Grabar exige avisar siempre —no es configurable— y
una llamada que no se puede grabar **se hace igual sin grabar**: bloquearla
convertiría una cuestión de privacidad en un cliente que no puede hablar con
nadie. Y el marcado automático tiene un tope de abandono que no se negocia: marcar
a más gente de la que hay para atender produce llamadas que suenan y cuelgan, está
regulado, y además es lo que hace que el número acabe marcado como spam en el
teléfono de todo el mundo — que no se arregla pagando una multa.

**El asistente de voz** es la funcionalidad que mejor demo tiene y la que peor sale
en producción, siempre por lo mismo: en una demo el que habla colabora. Aquí **la
confianza decide, no el texto** —un reconocimiento flojo puede significar lo
contrario, «no quiero cancelar» y «quiero cancelar» se parecen mucho a bajo
volumen— y a la tercera se pasa a una persona, porque pedirlo otra vez solo
confirma que se está hablando con una máquina que no funciona. **Lo irreversible
no lo hace una voz**: cancelar un contrato, devolver un cobro o cambiar unos datos
bancarios por teléfono es la clase de decisión que solo se toma porque es fácil de
programar, y el cambio de datos bancarios es el fraude telefónico más común que
existe. Se avisa de que es una máquina —la gente habla más corto y más claro
cuando lo sabe, así que el sistema funciona mejor, y descubrirlo a los tres
minutos sienta francamente mal—, y **avisar de que se graba no es consentimiento
para entrenar**: son dos permisos distintos y confundirlos es lo más frecuente en
cualquier proyecto de voz. El traspaso a una persona lleva todo lo hablado, porque
si el asistente estuvo tres minutos preguntando y la persona empieza de cero, lo
que hizo fue perder tres minutos del cliente; y viaja **en la misma respuesta**
que dice que hay que pasar la llamada, no en una segunda petición que la
implantación con prisa se salta. Los dos permisos —grabar y entrenar— se
contestan también juntos, que es donde se confunden: se lee que avisar de la
grabación no habilita a entrenar antes de que el audio esté dentro de un modelo
del que ya no se puede sacar. Y se mide por lo que importa:
**resueltas sin persona y sin que el cliente vuelva a llamar en 48 horas** — una
llamada que el asistente «resolvió» y que el cliente repite al día siguiente no se
resolvió, se aplazó, y encima con el cliente ya molesto.

## Los dos manuales completos (`CRM-07.05.01.01`, `CRM-07.05.01.02`, `CRM-07.05.01.03`, `CRM-07.05.01.04`, `CRM-07.05.01.05`, `CRM-07.05.01.06`, `CRM-07.05.02.01`, `CRM-07.05.02.02`, `CRM-07.05.02.03`, `CRM-07.05.02.04`, `CRM-07.05.02.05`, `CRM-07.05.02.06`)

Además de este manual por audiencias, hay **dos documentos independientes y
completos**, cada uno pensado para leerse entero de principio a fin:

- El **[manual de usuario](manual-usuario.md)**, escrito para quien usa el CRM: un
  capítulo por área funcional, casos de uso de punta a punta —del primer contacto
  al cobro, del alta de una incidencia a su cierre—, ejemplos reproducibles con los
  datos de la demo, una guía de qué hacer cuando algo no sale, y un recorrido por
  perfil.
- El **[manual técnico](manual-tecnico.md)**, para quien lo instala, lo configura,
  lo integra y lo mantiene: arquitectura y las decisiones detrás, despliegue en
  tres escenarios, configuración ajuste a ajuste con qué pasa si se toca,
  integración —API, eventos, conectores y contratos— y operación.

Lo que los hace distintos de la documentación habitual de producto es que **se
comprueban solos**. Un manual que nadie verifica se queda viejo en tres meses y
entonces miente, que es peor que no tenerlo: el lector se fía. Los gates no
comprueban que estén bien escritos —eso no lo puede comprobar una máquina— sino
las dos formas de quedarse viejo que sí son detectables:

- **El manual de usuario deja de cubrir un área.** El día que se añade una sección
  funcional nueva al catálogo, el gate falla hasta que alguien escriba su capítulo,
  en vez de que el área entre sin documentar y nadie se entere hasta que un cliente
  pregunte.
- **El manual técnico describe algo que ya no existe**: un ajuste renombrado, un
  script borrado, un servicio que se quitó. Eso es peor que una omisión — alguien
  lo intenta, no funciona, y deja de fiarse del resto del documento.

Y una decisión sobre las cifras: en el texto de los manuales no hay números de
progreso. Una cifra escrita a mano se queda vieja al día siguiente; el recuento
vivo está en [el estado del catálogo](catalogo/estado.md), que se regenera.

## Recuperación a un punto en el tiempo y pruebas de DR (`CRM-00.06.02.02`, `CRM-00.06.02.06`)

Restaurar el clúster entero para arreglar lo que rompió un cliente es la opción que
existe en todas partes y que **no se usa nunca**: implica tirar abajo a los demás
por un error de uno. Lo que hace falta es volver atrás **un solo tenant** hasta un
momento concreto.

Y ahí hay una complicación que conviene mirar de frente: **el tiempo no es el mismo
para todos los datos**. Restaurar las tablas del tenant a las 10:00 no deshace los
eventos que salieron entre las 10:00 y ahora — el webhook ya llegó al ERP del
cliente, el correo ya se mandó, la audiencia ya se subió a la plataforma de
anuncios. Por eso la restauración **dice qué salió fuera en ese tramo**: nada de
eso se puede deshacer y, si no se dice, nadie lo tiene en cuenta.

- **Se restaura sobre una copia, no encima.** Se levanta el estado de ese momento
  en paralelo, alguien lo mira y entonces se decide qué se trae. Restaurar
  directamente sobre lo vivo convierte un error en dos.
- **Hay cosas que no se restauran nunca**: la auditoría —restaurarla borraría el
  rastro del propio incidente—, los eventos ya publicados y las claves de cifrado.
- **Y el momento se comprueba al pedirlo.** Pedir volver a hace seis meses cuando
  la retención son treinta días falla ahora, no a mitad del proceso.

**Las pruebas de recuperación** no son un trámite: son lo único que distingue una
copia de un fichero grande. Se cronometran y se guarda el resultado, porque el RTO
que se promete en un contrato casi siempre es más bajo que el real — se calculó
contando la restauración y no lo que tarda alguien en darse cuenta, en decidir y en
encontrar la copia. Si hay **cualquier diferencia** entre lo restaurado y lo
esperado, la prueba no pasa: una copia que restaura el 99 % es una copia que pierde
datos. Y sin ninguna prueba no se dice que las copias estén bien: se dice que nadie
ha comprobado que sirvan.

El **RPO real** —cuánto se perdería ahora mismo— se puede mirar en cualquier
momento, y sin ninguna copia no es cero: es todo.

## Catálogo de servicios, malla, zonas y despliegue (`CRM-00.03.01.04`, `CRM-00.03.01.05`, `CRM-00.06.02.05`, `CRM-00.06.02.08`)

Cuatro cosas que se documentan en una wiki, se quedan viejas y hacen daño justo
cuando hacen falta: a las tres de la mañana, con un servicio caído y alguien
buscando a quién llamar. Aquí se declaran en el código y se comprueban.

**El catálogo de servicios** dice de cada uno quién es su dueño, qué promete, de
qué depende y qué runbook abrir. Un servicio sin dueño declarado es uno que en una
guardia nadie sabe de quién es. Y se detectan las **dependencias circulares**, que
producen un arranque que nunca termina y una guardia en la que todos los servicios
están «esperando al otro».

**De la malla**, lo que importa no es la tecnología: es **qué se puede
reintentar**. Un reintento automático sobre un `POST` que crea algo produce dos
pedidos, y el cliente lo ve antes que nosotros. Con clave de idempotencia sí se
reintenta, porque el servidor reconoce que es la misma petición — por eso el CRM la
exige en las escrituras que importan.

**Tener réplicas no es alta disponibilidad.** Lo que decide si el sistema aguanta
es si la promoción está probada y si lo que queda en pie tiene capacidad para todo
el tráfico: dos zonas al 60 % de uso cada una no sobreviven a perder una, y eso se
sabe sumando, no esperando. Un plan sin simulacro es una suposición cara: nadie
sabe cuánto tarda de verdad una promoción hasta que la ha hecho con el reloj
delante.

**Y un despliegue sin corte solo lo es si la vuelta atrás también lo es.** Un
canario que no se revierte en un minuto no es un canario: es un despliegue con
público, y cuando algo va mal lo que se hace es esperar a ver si se arregla. La
migración tiene que ser compatible hacia atrás una versión, porque durante el
despliegue hay dos versiones hablando con la misma base — no es un riesgo teórico,
pasa en el minuto dos. Los umbrales para abortar se fijan **antes**: decidiéndolo
en caliente siempre parece que «todavía no es para tanto», y media hora después ya
hay clientes afectados.

## Degradación controlada bajo presión (`CRM-08.01.01.06`)

El mecanismo para aplazar lo que no es crítico cuando el sistema está saturado
existía desde el principio: lo crítico pasa siempre, lo normal por debajo del 90 %
de presión y lo diferible por debajo del 60 %.

Lo que faltaba era **que alguien midiera la presión**. Sin nadie que la declarara,
valía cero para siempre, todo pasaba siempre, y la degradación controlada era un
mecanismo que existía en el código y no se activaba jamás — el peor tipo de
función: la que da confianza sin hacer nada.

Ahora se mide en cada petición, con tres señales y una regla:

- **La latencia contra el objetivo**, que es la que nota el usuario.
- **El pool de conexiones**, que es la que avisa antes: cuando se agota, las
  peticiones no van lentas, fallan de golpe.
- **La cola de trabajos**, que es el aviso más temprano y el que menos se mira.
- **Y manda la peor, no la media.** Promediarlas suaviza justo la que está dando el
  problema: con el pool al 95 % y lo demás bien, la media sale tranquila y el
  sistema está a punto de caer.

La presión **sube de golpe y baja despacio**. Si bajara igual de rápido el sistema
oscilaría —admite, se satura, rechaza, se alivia, admite— y media petición fallando
sin patrón es peor para el usuario que una degradación estable. Y lo que no se
puede medir **no cuenta como cero**: un proceso que solo mide latencia y da presión
baja mientras su cola crece está tranquilizando sobre algo que no ha mirado.

Cada servicio publica qué se está aplazando y por qué, y el gateway junta las de
todos — la presión de uno solo no dice nada, porque lo que se aplaza depende del
que esté peor. Un servicio que no contesta **no cuenta como tranquilo**: suele ser
justo el que está peor.

## Particionado, archivado y escalado (`CRM-08.01.01.04`, `CRM-08.01.01.02`)

Hay tres o cuatro tablas que crecen sin parar —actividades, eventos, auditoría— y
el resto se queda en unos cientos de miles de filas para siempre. Con las primeras
pasa siempre lo mismo y en el mismo orden: las consultas se ponen lentas, los
índices dejan de caber en memoria, el mantenimiento tarda más que su ventana, y al
final una consulta que iba bien durante dos años deja de ir en una semana sin que
nadie haya cambiado nada.

- **Se particiona por tiempo, no por tenant.** Por tenant parece natural y es un
  error caro: con dos mil tenants salen dos mil particiones, el planificador tarda
  más en decidir que en ejecutar, y el tenant grande sigue teniendo su partición
  enorme. Por mes, las consultas normales tocan una o dos.
- **Las particiones se crean por delante.** Crearlas cuando llega la primera fila
  del mes significa crearlas a las 00:00 del día 1, dentro de la transacción de un
  usuario y con un bloqueo de tabla: un incidente con fecha conocida.
- **Lo viejo se archiva, no se borra.** Un CRM al que alguien pregunta por una
  llamada de hace tres años y contesta que no existe deja de ser el registro de la
  empresa. Se mueve a frío, se sigue consultando y se dice dónde está.
- **Y lo retenido no se toca**: lo que está bajo obligación legal, en un litigio o
  con una solicitud de acceso pendiente. Moverlo a frío sería cumplir el plazo de
  retención por accidente y romper otra obligación a la vez — y la que se rompe
  suele ser la cara.

El aviso útil sobre el volumen no es «esta tabla es grande»: es **a qué ritmo
crece**. Una de cien millones de filas estable no molesta a nadie; una de diez que
dobla cada trimestre es un incidente dentro de nueve meses, y esos nueve meses son
justo el tiempo que hace falta para arreglarlo con calma. Y sin datos de volumen
**no se dice que todo esté bien**: se dice que no se puede anticipar nada, que es
una respuesta distinta.

Todo esto se consulta **por servicio** —las tablas que crecen están repartidas por
catorce esquemas y cada uno sabe de las suyas— y **nada de ello escribe en la
base**: devuelve el plan, y quien ejecuta el corte es la migración del servicio,
con su revisión y su ventana. Una ruta que particionara en caliente bloquearía la
tabla durante la petición de un usuario, que es justo el incidente que esto existe
para evitar.

Dos cosas más que se preguntan aquí. **Si falta ya la partición del mes en curso**,
que no es un aviso sino un incidente ocurriendo. Y **si estas filas se pueden
borrar de la tabla viva**: mover a frío sin borrar no quita volumen, el borrado es
el paso que no tiene vuelta atrás, y se comprueba antes y aparte — el proceso de
limpieza corre de noche, y lo que borra por error se descubre semanas después,
cuando alguien lo pide para un juicio. Por lo mismo, **las purgas que no distinguen
por registro se abstienen enteras** mientras haya un bloqueo legal activo:
conservar de más cuesta disco y borrar la prueba equivocada no tiene arreglo.

Y lo archivado **se puede devolver a la tabla viva**: el archivo se consulta pero
no se trabaja, y cuando una cuenta que se fue vuelve, lo que se quiere no es leer
su historia sino poder seguir escribiendo en ella.

**Del escalado horizontal**, dos cosas. La primera: cada servicio tiene un límite
que **no es la CPU** —el gateway lo tiene en las conexiones salientes, los de datos
en el pool de Postgres, el de inteligencia en la cuota del proveedor—, y añadir
réplicas por encima de ese límite **empeora**: más réplicas son más conexiones
peleando por el mismo pool. La segunda: un servicio solo se puede replicar si no
guarda nada en su proceso. Un contador en memoria con tres réplicas cuenta un
tercio — aquí pasó con el presupuesto de error—, una caché en memoria caduca
distinto en cada una, y un planificador sin elección de líder manda el correo tres
veces.

Y al decidir qué escalar: **no el que se nota, sino el que tarda**. Si el gateway
va lento porque `party` va lento, poner más gateways solo hace que esperen más
peticiones a la vez. Cuando nadie está cerca de su límite, la respuesta honesta es
que el problema no es de capacidad — más incómoda y ahorra una factura.

## Entornos de pruebas con datos del cliente (`CRM-07.02.01.02`)

Un entorno de pruebas sin datos parecidos a los de verdad no sirve: las pruebas
pasan y luego en producción falla el cliente que tiene ocho direcciones o el nombre
con una comilla. Por eso se pide copiar producción a pruebas.

Y ahí está el problema: **copiar producción a pruebas es sacar los datos personales
de tus clientes de donde están protegidos y ponerlos donde entra todo el mundo**. A
pruebas acceden el consultor externo, el becario y el proveedor que está integrando
algo; no hay ni el mismo cifrado ni el mismo control de acceso. La mayoría de las
filtraciones de un CRM no salen de producción: salen de una copia.

- **La anonimización no es opcional cuando el destino no es producción.** Se puede
  desactivar pidiéndolo expresamente, con un motivo y con nombre — que sea una
  casilla marcada por defecto es lo que hace que nadie la mire.
- **Se anonimiza de forma consistente**: el mismo valor original da siempre el
  mismo valor falso dentro del entorno, y distinto entre entornos. Sin lo primero,
  el entorno no sirve para probar nada que cruce datos; sin lo segundo, cruzando
  dos entornos se podría deshacer la anonimización.
- **Una columna sin regla se vacía**, no se copia: el silencio por defecto tiene
  que ser el seguro.
- **Hay cosas que no se copian nunca**: tokens, claves de API y secretos de
  webhook. Un token válido en pruebas es una puerta abierta a producción.
- **Se recomienda copia parcial**, y no por espacio: con el 5 % de los clientes se
  prueba igual de bien y hay veinte veces menos que proteger.
- **Y un sandbox caduca.** El que se creó para una migración hace año y medio sigue
  ahí con los datos de entonces, sin actualizaciones y sin que nadie recuerde quién
  tiene acceso.

## Las pantallas que faltaban del front oficial (`CRM-07.04.03.23`, `CRM-07.04.03.24`, `CRM-07.04.03.27`, `CRM-07.04.03.29`, `CRM-07.04.03.31`, `CRM-07.04.03.32`, `CRM-07.04.03.33`, `CRM-00.01.07.06`)

El front de referencia tiene que enseñar **todo** lo que el sistema hace: una
capacidad que solo existe por API es una capacidad que nadie ve, y quien mira el
producto concluye que no está. Estas son las que faltaban, y cada una está escrita
alrededor de la decisión que la hace útil o inútil:

- **Inteligencia artificial.** La puntuación va con sus factores, y con los que
  **restan** también — un panel que solo cuenta lo que suma hace pensar que la
  puntuación es baja por falta de datos. Sin contribuciones no se pinta un número:
  se dice que no se puede explicar.
- **Puesto de trabajo.** Lo que enseña no es «está conectado»: es **si está
  entrando algo y desde cuándo no**. Y lo que no se ha medido sale **con su
  nombre**, no sólo contado: quien lee «1 conexión sin medir» no sabe cuál, que
  es lo primero que hace falta para arreglarlo. Lo no medido no cuenta como
  verde, y lo que va por sondeo se dice — sus cambios entran con retraso.
- **Entornos y cambios (ALM).** El desvío se mide contra el paquete desplegado, no
  contra otro entorno, y **lo que desapareció también es desvío**: un panel que
  solo enseña lo añadido deja fuera el caso más incómodo. Encima del desvío se
  dice **qué hay puesto y de qué commit sale**, porque las dos cosas se piensan
  a la vez: un informe de desvío sin decir contra qué se compara se queda sin
  referencia. Y se dice también **qué no se ha comparado**, que es lo que
  distingue un «limpio» de un «no se ha mirado».
- **Rendimiento.** Contesta la pregunta que llega de verdad —«¿por qué mi lista
  tarda?»— juntando tres cosas que normalmente están en tres sitios: cuánto hay,
  cuánto cabe y **qué se está aplazando ahora mismo**. Dice **qué servicio está
  peor** y **cuáles no han contestado**: un servicio que no contesta no cuenta
  como tranquilo, suele ser el que está peor. Hasta el 26-10-2026 sólo se pintaba
  el resumen —«el sistema está bajo presión»— sin decir de quién, que es lo único
  accionable; el servidor mandaba las dos cosas desde el principio.
- **Proveedores.** Lo vencido no se pinta igual que lo que va a vencer —uno está
  pasando y lo otro es una tarea de esta semana— y «no consta» no se pinta como
  «está bien».
- **Coste y capacidad.** Un margen desconocido no se pinta como cero, lo que está
  en pérdidas se ve a la primera, y la capacidad enseña lo que hay en ofertas
  abiertas.
- **Ayuda en producto.** Se abre por el capítulo de la pantalla en la que estás, no
  por el índice: mandar al índice es mandar a buscar, y quien está atascado no
  busca, se rinde y escribe a soporte. El mapa de pantalla a capítulo es explícito
  y no una convención sobre la ruta — una convención se rompe en silencio el día
  que alguien renombra algo, y entonces la ayuda lleva al sitio equivocado, que es
  peor que no llevar a ninguno.
- **Gobierno de la suite.** Enseña primero **las bajas sin aplicar**, que es lo
  único que hay que mirar con prisa: una baja que no llegó a otra herramienta es un
  acceso que sigue abierto, y eso no se ve hasta una auditoría. Con una advertencia
  escrita en la propia pantalla: esto no es un panel de control remoto, cada
  herramienta manda en lo suyo.

Al construirlas apareció un hueco que no se veía desde ningún sitio: **el motor de
configuración como código no tenía API**. Empaquetar, simular una promoción,
desplegar, medir el desvío y volver atrás solo se podía hacer desde el código, así
que la promesa de que todo se hace por API tenía un agujero justo en la parte que
más falta hace automatizar. Ahora está publicado.

## Accesibilidad comprobada (`CRM-06.02.01.05`)

La interfaz que viene con el producto cumple WCAG 2.2 nivel AA, y eso **se
comprueba en cada cambio** en vez de auditarse una vez: la accesibilidad se rompe
al mes siguiente de arreglarla si nadie la vuelve a mirar.

El linter de accesibilidad caza lo que se ve en una etiqueta suelta —una imagen sin
texto alternativo, un `onClick` sobre un `div`— y está en modo **error**, porque un
aviso que no rompe nada se acumula. Y cinco comprobaciones propias cazan lo que
solo se ve mirando la pantalla entera: que toda pantalla tenga un encabezado de
primer nivel, que todo campo tenga etiqueta, que **lo que cambia al pulsar se
anuncie**, que las cabeceras de tabla digan a qué se refieren y que **el color
nunca vaya solo**.

Esas cinco no son hipotéticas: al escribirlas encontraron fallos reales en
pantallas que ya estaban en producción — tres cambiaban su contenido al pulsar un
botón sin anunciarlo, y la lista de un módulo se recargaba en silencio.

Y hay una página, [Accesibilidad](ACCESIBILIDAD.md), que dice también **qué no
cumple**: el reflujo a 320 píxeles en tablas anchas y el foco parcialmente tapado
por la cabecera en pantallas cortas. Una página de accesibilidad que solo dice
«cumplimos» no le sirve a nadie para decidir, y es lo primero que pide un pliego.

## Reversibilidad y plan de salida (`CRM-08.02.01.06`)

Hay un documento que dice **cómo se sale de contecrm**: qué se lleva el cliente, en
qué formato, cuánto tarda y qué deja de funcionar — [Reversibilidad y plan de
salida](SALIDA.md).

Está escrito por una razón práctica: **un cliente que no sabe cómo salir no acaba
de entrar**. En cualquier compra mediana alguien pregunta esto antes de firmar, y
que la respuesta esté escrita y sea comprobable vale más que cualquier argumento.

Lo que se lleva es todo lo suyo —datos, configuración, adjuntos, actividades,
auditoría con su cadena de hashes e histórico— en formatos que no son nuestros:
CSV, JSON, EML, vCard, iCalendar. Lo que no se puede llevar se dice y se explica:
las contraseñas no existen en claro, la clave de cifrado gestionada por nosotros no
se entrega —los datos salen descifrados— y los modelos no viajan, aunque sí las
señales con las que se entrenan.

Se dice también **qué deja de funcionar** al cortar: webhooks, CDC, audiencias
publicitarias —donde hay que retirar las listas o seguirá viendo anuncios gente que
se dio de baja—, enlaces compartidos y firmas a medias.

Y dos prácticas del sector que aquí no existen: **no se cobra por exportar**
—cobrar por salir es una barrera con otro nombre— y **no hay formatos propios**.
La recomendación es pedir la exportación una vez durante la implantación, que es el
único momento en el que comprobar el plan de salida no cuesta nada y en el que
descubrir que falta algo tiene arreglo.

## Chat interno (`CRM-06.02.02.01` a `CRM-06.02.02.09`)

Media conversación de un CRM ocurre fuera de él. Se habla de una oportunidad en
otra herramienta, se decide bajar un precio, y lo que queda dentro es una etapa
cambiada sin el porqué. Seis meses después, cuando hay que renovar, nadie sabe
por qué se dio aquel ocho por ciento.

### Lo que lo distingue de poner un enlace a Teams

Una conversación puede **colgar de un registro** (`CRM-06.02.02.02`). No es «un
canal donde además pegamos enlaces»: es la conversación de *esta* oportunidad,
que se abre desde su ficha con el botón **Hablar de esto** y se lee con el
importe y la etapa al lado. Un chat genérico obliga a copiar el enlace y a que
quien lo recibe cambie de aplicación, y ese salto es justo donde se pierde el
contexto.

Hay **una sola conversación por registro**, garantizada por un índice único: dos
serían dos sitios donde mirar lo que se dijo de la misma oportunidad, que es
peor que ninguno.

La conversación **no se crea al abrir la ficha**, sino al pulsar el botón. Si se
creara sola, la lista se llenaría de conversaciones vacías de cada registro que
alguien haya mirado, y una lista así deja de mirarse.

### Canales, grupos y directos

Tres tipos y no más (`CRM-06.02.02.01`), porque cada uno tiene reglas distintas
de quién entra y quién ve, y un cuarto tipo «otro» sería un tipo sin reglas, es
decir, sin permisos:

| Tipo | Quién entra | Tiene clave |
|---|---|---|
| `canal` | se entra y se sale; `#ventas` | sí, es lo que lo nombra siempre igual |
| `grupo` | lista fija con nombre | no |
| `directo` | dos personas, sin invitados | no |

**Un directo con alguien con quien ya se habló devuelve el que hay.** Abrir uno
nuevo al lado del que tiene el histórico es cómo se acaban teniendo tres
conversaciones con la misma persona y buscando en las tres.

**A un directo no se añade gente.** Lo que se quiere entonces es un grupo, y un
grupo nuevo no arrastra lo que ya se dijo en privado — que es exactamente lo que
no debe arrastrar.

### Quién lee qué

Quien no está en la conversación no la lee, y la respuesta es **404 y no 403**:
decir «existe pero no puedes» sobre un canal privado confirma que ese canal
existe, y el nombre de un canal —`due-diligence`, `salida-de-javier`— ya es
información.

Por lo mismo, el listado devuelve **solo las conversaciones propias** y la
búsqueda (`CRM-06.02.02.08`) busca solo dentro de ellas. Una búsqueda global
encontraría texto de canales en los que no se está, que es una fuga por la
puerta de atrás.

### Hilos, reacciones y correcciones

Un mensaje puede responder a otro (`CRM-06.02.02.03`). Sin hilos, una
conversación con dos temas a la vez es ilegible; con hilos de verdad —no
«citas»— cada tema se sigue por separado. En la pantalla el hilo se abre **al
lado** y no sustituye a la conversación: entrar en un hilo y perder de vista lo
demás obliga a salir y volver, que es lo que un hilo existe para evitar.

Las reacciones salen de una **lista corta y cerrada** (👍 👎 ✅ ❓ 🎉 👀). Con
emoji libre, la misma reacción se escribe de cinco maneras y contar «cuántos lo
han aprobado» deja de ser posible. Son un interruptor: pulsar dos veces el mismo
emoji lo quita.

**Editar guarda lo que decía antes.** En una conversación donde se decide algo,
saber qué decía es justo lo que hace falta cuando alguien lo discute. El mensaje
enseña cuántas veces se corrigió y el texto anterior se consulta aparte —no se
pinta en cada mensaje— porque el histórico es para cuando se necesita, no ruido
permanente.

**Solo edita un mensaje quien lo escribió.** Que un administrador pueda
reescribir lo que dijo otro convierte el histórico en algo que no se puede
citar, y la única razón de tener histórico es poder citarlo.

### Menciones

Las menciones (`CRM-06.02.02.04`) avisan por el **mismo camino que todo lo
demás**: `crmcore.datos.seguimiento`. Así respetan las preferencias por canal de
cada quien y aparecen en la misma bandeja que el resto de avisos. Un chat con su
propio sistema de notificaciones obliga a configurar dos veces y a mirar en dos
sitios, y lo que pasa es que se mira en ninguno.

**Solo se avisa a quien está dentro** de la conversación: mencionar a alguien
que no puede leerla le mandaría a una pantalla que le dirá que no existe.

### Leídos y no leídos

Cada miembro guarda **hasta cuándo** ha leído (`CRM-06.02.02.05`), no el último
mensaje leído. Con el identificador, un mensaje que llega desordenado —o uno
borrado— deja el contador en un número que no se corresponde con nada.

### Presencia

El estado (`CRM-06.02.02.06`) va con **texto libre corto**: «en un cliente hasta
las 5» vale más que el color, porque responde a la pregunta de verdad, que es si
esperar o llamar.

### Entrega en vivo

Por SSE (`CRM-06.02.02.07`), leyendo **por cursor contra la base** y no de una
cola en memoria. El gateway tiene una cola en proceso para su empuje de eventos
y aquí no sirve: con dos réplicas de `identity`, un mensaje escrito en la
primera nunca llegaría a quien escucha en la segunda, y ese fallo solo aparece
al escalar —con dos personas hablando y una que no recibe nada—. Leer por cursor
cuesta una consulta cada pocos segundos y funciona con las réplicas que haga
falta, sin bus y sin estado compartido.

La sesión de base de datos **se cierra entre vueltas**: mantenerla abierta
reservaría una conexión por persona conectada, y con cincuenta personas con el
chat abierto eso agota el pool sin que nadie esté haciendo nada.

Lleva latido: un flujo sin datos durante minutos lo cierra cualquier
intermediario por inactividad, y el cliente cree que el servidor se ha caído
cuando lo que pasa es que no pasa nada. El latido va cada
`CHAT_SSE_LATIDO_S` segundos de reloj, no cada N vueltas: lo que hace falta
—que ningún intermediario dé el flujo por muerto— se mide en tiempo, y contar
vueltas lo ataba a la espera entre consultas.

**El flujo saluda al abrirse**, antes de la primera consulta, con una línea
`retry:` y un comentario SSE. No es un adorno: para el cliente un flujo no
existe hasta su primer byte —el servidor no manda las cabeceras de la respuesta
hasta el primer trozo del cuerpo— así que un flujo que se abre en silencio es,
visto desde fuera, un servidor que no contesta. El saludo es un comentario y
ningún cliente lo procesa como mensaje, pero abre la respuesta. La línea
`retry:` (`CHAT_SSE_REINTENTO_MS`) es además la única forma de decirle a un
`EventSource` cuánto esperar antes de reconectar.

Dicho sin adornos: **esto no funcionó nunca hasta que se ejecutó**. Dos cosas
distintas lo impedían, ninguna visible leyendo el código. La primera, el
middleware que añade el `ETag` retenía la respuesta entera —el inicio incluido—
hasta conocer el último trozo, y el cuerpo de un flujo no termina; afectaba a
**toda** respuesta en flujo de **todos** los servicios, no solo al chat.
La segunda, el gateway reenviaba acumulando la respuesta con un plazo de diez
segundos, que en un flujo abierto es un 504 garantizado. Las dos están cerradas
con su prueba (`tests/unit/test_respuesta_en_flujo.py` y
`tests/unit/test_gateway_flujo.py`), y las dos comprueban el **momento** en que
sale el primer byte, no solo qué acaba llegando: el contenido llegaba entero al
final, así que una prueba de contenido las habría dado por buenas.

### Borrado y retención (`CRM-06.02.02.09`)

Un mensaje se manda a la papelera con `DELETE /chat/mensajes/{id}` y se saca de
ella con `POST /chat/mensajes/{id}/recuperar`. Lo hace **quien lo escribió o
quien administra la conversación**: lo primero es evidente, y lo segundo hace
falta porque el caso que justifica todo esto es que alguien pegue en un canal
algo que no debía estar ahí —una credencial, el dato personal de un cliente— y
entonces no se puede esperar a que el autor se conecte.

**Deja lápida.** El mensaje no desaparece del hilo: se queda su hueco, sin
cuerpo y sin adjuntos. Uno que se esfuma deja su respuesta colgando de nada, y
quien lee la conversación una semana después no entiende el hilo ni sabe que
falta algo. Lo que se va es lo que se quería quitar.

Y se cierran las **dos puertas de atrás**: la búsqueda no encuentra un mensaje
borrado por su texto, y el histórico de ediciones de un borrado no se enseña. Sin
eso, la papelera no serviría de nada justo en el caso que la justifica.

El plazo lo fija la empresa en `/identity/retencion/politicas`, y pasado el
plazo la purga lo borra **de la tabla**: una papelera que guarda para siempre no
es una papelera. La purga **simula por defecto** —lo que se va a llevar por
delante hay que poder verlo antes, no después— y se abstiene entera si hay un
bloqueo legal activo.

> **Esto no existía hasta el 26-10-2026, y este manual decía que sí.** El modelo
> del mensaje llevaba las columnas de borrado desde el principio y su propio
> comentario apuntaba a la capacidad, pero no había ruta que borrara, ninguna
> que recuperara, `identity` no declaraba ninguna clase de retención ni
> publicaba el router, y las tablas de política y de bloqueo legal ya estaban
> creadas en su esquema esperando a que alguien las usara. Escrito y sin
> enchufar, contado como hecho y documentado como hecho. Salió auditando la
> familia entera y recorriendo sus rutas, no leyendo el código.

### Lo que no hay, dicho claro

**No hay llamadas, vídeo ni grabaciones.** Eso es una herramienta de
comunicaciones, no un CRM, y hacerlo a medias sería peor que no hacerlo: la
mitad de una videollamada es una videollamada que no funciona. Quien necesite
eso seguirá teniendo su herramienta, y lo que aporta contecrm —la conversación
pegada al registro— no se lo da ninguna.

## Sagas con compensación, alcanzables (`CRM-00.03.02.03`, `CRM-00.03.02.05`, `CRM-00.03.02.13`, `CRM-00.03.05.15`, `CRM-03.03.02.12`)

Un proceso que cruza servicios —reservar el stock, cobrar, avisar al cliente— no
se puede meter en una transacción: cada paso lo ejecuta un servicio distinto, con
su propia base de datos. Lo que se hace en su lugar es declarar, **antes de
empezar**, cómo se deshace cada paso. Si el tercero falla, se deshacen el segundo
y el primero, en ese orden.

Esto estaba entero y escrito, y **no lo alcanzaba ninguna ruta**: el motor de
procesos anunciaba en su propia descripción «sagas con compensación» y no había
forma de arrancar una. Ahora hay seis puertas, todas bajo `/api/v1/sagas`.

### Arrancar una saga

`POST /api/v1/sagas` con la clave del proceso y **todos los pasos declarados de
antemano**, cada uno con su compensación. Un paso sin compensación se acepta, pero
se marca como irreversible — y si no es el último, la respuesta lo avisa:

> Los pasos [2] no se pueden deshacer y no son los últimos: si algo falla después,
> la saga se compensará entera menos eso. Lo irreversible va al final, cuando ya
> no puede fallar nada detrás.

Ese es el accidente que evita: un correo al cliente en el paso dos deja una saga
que, al compensarse, ha avisado a alguien de algo que al final no ha pasado.

### Avanzar y fallar

`POST /api/v1/sagas/{id}/hecho` anota que un paso salió bien. Sin esa llamada los
pasos se quedan pendientes para siempre y la compensación no sabría hasta dónde
deshacer.

`POST /api/v1/sagas/{id}/fallo` anota el fallo y **compensa hacia atrás, y solo lo
que se hizo**. Compensar un paso que no llegó a ejecutarse es deshacer algo que no
pasó: una devolución de un cobro que nunca se hizo sale del banco igual.

Lo que no se puede deshacer **se dice y se deja**. La saga queda en `atascada`, a
propósito, con la lista de lo que hay que resolver a mano. Llamarla «compensada»
cuando se mandó un correo que no vuelve es lo que hace que nadie se fíe de esa
palabra.

### El listado y la ficha

`GET /api/v1/sagas` lista las sagas del tenant, filtrables por estado y por
clave. `estado=atascada` es la consulta que importa: las que dejaron trabajo sin
deshacer y esperan a que alguien decida.

`GET /api/v1/sagas/{id}` devuelve el estado, los pasos con el suyo, y `sin_deshacer`:
los pasos que quedaron sin compensar. Eso es trabajo manual pendiente, y una ficha
que no lo destaca lo deja sin reclamar.

### Publicar una versión nueva con cosas en vuelo

`POST /api/v1/sagas/migracion/simular` **no ejecuta nada**: dice cuántas instancias
hay en vuelo, de qué versión, y cuáles están en un paso que la versión nueva ya no
tiene. Una saga de alta de cliente puede durar semanas; publicar sin mirar es
cambiarle los pasos a procesos que ya están a mitad, y lo que estaba a mitad es lo
que nadie reclama.

Las que están corriendo **terminan con su versión**. La nueva se aplica a las que
empiecen a partir de ahora.

### Plantillas de flujo

`POST /api/v1/sagas/plantillas/clonar` copia una plantilla por sector para que el
cliente la modifique. **Se copia y no se hereda**: si heredara, mejorar la
plantilla cambiaría los procesos que ya corren en otros veinte clientes — incluido
uno que la ajustó hace seis meses. Y la respuesta trae `no_resuelve`: lo que la
plantilla deja fuera, dicho antes de empezar y no en producción.

### Lo que hace falta para llamarlas

Todas piden permiso: `proceso:write` las cuatro que escriben, `proceso:read` la
ficha y la simulación. Una saga mueve dinero y stock en varios servicios; la ruta
que se quedara sin permiso sería la que nadie mira.

## El tipo de registro y el gobierno de los módulos, enchufados (`CRM-00.04.01.05`, `CRM-00.04.04.03`, `CRM-00.04.04.10`)

Tres piezas que estaban escritas, probadas y que **no llamaba nadie**. Las tres
contestaban exactamente lo mismo que contestarían si estuvieran bien, que es lo
que las hacía difíciles de ver.

### El mismo objeto con caras distintas

Un tipo de registro es la misma cuenta con otra cara: una pública y una privada
no comparten campos ni listas, pero sí comparten tabla e informes — modelarlas
como dos objetos distintos rompe «cuántos clientes tengo».

Eso estaba resuelto y **la descripción del objeto no lo aplicaba**: el formulario
de «cuenta pública» se pintaba con los campos de la privada y con la lista de
opciones entera. El usuario elegía un valor que su tipo no admite y lo descubría
al guardar, si es que lo descubría.

Ahora `GET /api/v1/metadata/objetos/{nombre}/describe?tipo=publica` devuelve el
objeto **tal como lo ve ese tipo**: sin los campos que no usa y con sus listas
recortadas. Y una clave que no existe da error en vez de caerse a describirlo
todo: devolver el objeto entero ante una clave mal escrita pinta un formulario
con campos de más y nadie se entera.

### Lo que el cliente toca no se pisa al actualizar

Un módulo se actualiza, y el cliente ha ajustado cosas suyas por el camino. Para
eso existía la marca «modificado por el cliente»: lo tocado se respeta, o al
menos sale como conflicto antes de pisarlo.

**Nadie ponía esa marca.** Con lo cual no había conflictos, no había nada
respetado, y una actualización pisaba el trabajo del cliente — con el informe de
la actualización saliendo limpio, que es lo peor de todo.

Ahora se marca **al editar**, desde todas las vías que tocan un objeto o una
lista del módulo: añadir un campo, deprecarlo, crear una regla, guardar un tipo
de registro, renombrar un campo, retirarlo, y añadir o desactivar un valor de
lista. Enganchar una sola habría dicho la verdad en un camino y mentido en los
otros seis.

Se marca al editar y **no se adivina al actualizar**: adivinarlo obligaría a
comparar estructuras enteras y a acertar con qué cuenta como cambio, y el día que
se fallara se pisaría el trabajo de alguien.

### Qué del módulo se usa de verdad

La telemetría responde a «¿sobra la mitad de este módulo?». Contaba **cero usos
siempre**, así que todo salía en «sin usar» y la respuesta era siempre la misma, y
siempre equivocada. Ahora cada vez que se describe o se edita un elemento del
módulo se cuenta.

Un módulo recién instalado con todo sin usar no está inflado, está recién puesto:
por eso la respuesta sigue diciendo cuándo el dato **todavía no es concluyente**.

### El prefijo no se le enseña a nadie

Todo lo que trae un módulo va prefijado con su clave para que dos módulos no se
pisen. Ese prefijo es técnico: una entrada de menú que pone
«facturacion__envios» lo deja asomando por donde no debe. La superficie de
pantallas y la telemetría devuelven ahora también el nombre corto, sin quitar la
clave larga, que es la que identifica.

## El transporte gRPC, que estaba encendido y no funcionaba (`CRM-00.02.01.03`)

El ajuste se leía, el servidor se levantaba, el contrato `.proto` se generaba y se
le entregaba al integrador. Lo que no había era **la conversión entre los bytes
del protocolo y el CRM**, en ninguna de las dos direcciones.

El servidor declaraba `bytes` como lector y como escritor de mensajes. Eso no es
«sin conversión»: es que el manejador recibía bytes crudos donde esperaba un
mensaje —se quedaba con el cuerpo vacío, y **un alta por gRPC creaba un registro
sin datos**— y la respuesta ni siquiera llegaba a serializarse.

Las dos piezas que faltaban llevaban tiempo escritas y probadas, sin que las
llamara nadie: la que construye la clase del mensaje desde el mismo esquema del
que sale el `.proto`, y la que lo rellena.

### Los números del contrato ahora viajan con el esquema

Un contrato protobuf no se identifica por el nombre de sus campos sino por su
**número**. Esos números se asignan al publicar el esquema y se guardan, pero no
salían con el evento que replica el esquema a los demás servicios: cada uno los
habría recalculado al servir, y le habrían salido otros.

Eso no da error. El mensaje se decodifica igual, el valor entra en el campo
equivocado, y nadie se entera hasta que alguien pregunta por qué ese cliente tiene
una zona que no existe.

### Y un listado devolvía el sobre, no las cartas

El manejador de `List` buscaba una clave que no existe en ninguna respuesta del
CRM, así que devolvía la página entera —con su cursor y su total— como si fuera un
único registro, en vez de los N que contiene.

## Ningún consumidor deduplicaba (`CRM-00.03.01.06`, `CRM-00.02.02.04`)

El producto lo promete por escrito en dos sitios. La unidad de trabajo, en su
primera página: «el precio es entrega **at-least-once**, y por eso todo consumidor
deduplica». El buzón de entrada, en la suya: «si el consumidor no deduplica, un
reintento del productor crea la cuenta dos veces, suma el importe dos veces o
manda el correo dos veces — y esos tres fallos son visibles para el cliente
final».

**Y no deduplicaba ninguno.** La tabla estaba creada, el barrido que la purga
estaba registrado en los catorce servicios —barriendo una tabla **siempre
vacía**, que es por lo que nadie lo notó— y la única función que escribe en ella
no la llamaba nadie. La garantía estaba documentada dos veces y no existía
ninguna.

Y había un segundo defecto debajo del primero: esa función miraba `rowcount` para
saber si había insertado, y en ese `INSERT ... ON CONFLICT DO NOTHING` **vale -1
tanto si insertó como si no**. Como `bool(-1)` es verdadero, decía «es nuevo»
siempre, también ante un duplicado. Aunque alguien la hubiera llamado, no habría
deduplicado nada.

### Por qué la marca va en la misma transacción que el efecto

Las dos alternativas fáciles están mal, y cada una por un motivo distinto:

- **Marcar antes, por separado**: si algo falla después, el evento queda marcado
  sin haberse procesado y el reintento lo descarta. El hecho se pierde para
  siempre y nadie lo reclama.
- **Marcar después, por separado**: no cubre el caso real. El bus reclama lo que
  lleva mucho sin confirmar, así que la segunda entrega entra mientras la primera
  todavía está dentro — y las dos hacen el efecto.

Así que el guardián y el consumidor **comparten transacción**: o se escriben las
dos cosas, o no se escribe ninguna.

### Se envuelve una vez, no catorce

La deduplicación se aplica al suscribir, en el arranque del servicio, y no dentro
de cada consumidor. Son catorce sitios donde acordarse, y «funciona donde alguien
se acordó» no es una garantía. Hay un recorrido que comprueba que **toda**
suscripción pasa por ahí.

### La marca va acotada al cliente

La clave de deduplicación la pone quien produce el evento. Las automáticas ya
llevan el cliente dentro, y las escritas a mano llevan hoy todas un identificador
único —comprobado una a una—, así que el choque entre dos clientes no es
alcanzable ahora mismo. Pero es una trampa puesta: el primero que escriba
`pedido:42`, que es la forma natural de escribirla, haría que el alta de un
cliente descartara la del otro, en silencio. La marca se guarda con el cliente
delante para que eso no pueda pasar.

### Un mensaje sin sobre reconocible se procesa igual

Y se deja dicho en el registro. Dejar de procesarlo convertiría un problema de
formato en un hecho perdido, que es mucho peor que procesarlo dos veces.

### Una sola copia de la invalidación de caché

Había dos recorridos para lo mismo: el del módulo de la caché, que no llamaba
nadie, y una copia suelta en el arranque del servicio que leía el tipo del evento
de otra forma. Dos copias es cómo acaban dos sitios resolviendo distinto lo
mismo. Se queda la del módulo, que es la que entiende las dos formas.

## Tokenizar, y marcar lo que sale (`CRM-00.05.03.04`, `CRM-00.05.03.07`, `CRM-00.05.04.04`)

Tres capacidades de seguridad resueltas por dentro y sin puerta por fuera.

### Sacar de la base lo que no debe estar dentro

Cifrar un número de tarjeta lo protege de quien lea la base. **Tokenizarlo lo
saca de la base**, que es otra cosa: lo que queda en el CRM es una referencia sin
valor, y el número vive donde sabe guardarlo quien tiene el certificado para
hacerlo. La diferencia importa el día de la auditoría — un sistema que cifra
tarjetas sigue dentro del alcance de PCI; uno que no las tiene, no.

El módulo estaba entero —tipos admitidos, pista que se conserva de cada uno,
rechazo a tokenizar en falso sin bóveda, rastro al recuperar— y **no había forma
de pedirlo**. Lo único que llegaba a ejecutarse era el detector de números
colados por texto libre, que avisa de que este despliegue no tiene bóveda: un
aviso sobre una capacidad que, además, no se podía usar.

Ahora, en `/api/v1/<servicio>/tokenizacion`:

- **Se pregunta antes de ofrecer el campo.** Una pantalla que ofrece guardar la
  tarjeta en un despliegue sin bóveda promete algo que va a fallar al guardar, con
  el cliente delante.
- **Sin bóveda no se tokeniza en falso.** Guardar el número «hasta que haya
  bóveda» mete el sistema en el alcance de PCI sin que nadie lo haya decidido.
- **Queda una pista**: los cuatro últimos de una tarjeta, nada de un identificador
  fiscal —con la letra y dos dígitos se adivina el resto—. Es para que una persona
  reconozca lo suyo, no para operar.
- **Recuperar es una operación sensible**: permiso propio, segundo factor
  reciente, motivo obligatorio y rastro en la auditoría con quién y para qué. Si
  fuera transparente, el número volvería a estar en todas partes y tokenizarlo no
  habría servido de nada. Tiene que costar pedirlo.

La bóveda la enchufa el despliegue. Aquí no se enchufa ninguna a propósito: atar
el producto a un proveedor concreto es justo lo que no se hace, y el dato no vive
aquí.

### La marca de lo que sale, puesta y no encargada

Una exportación lleva una marca de origen: de dónde salió ese fichero y quién lo
pidió. No es el audit trail —que dice quién exportó—, es otra pregunta y se hace
en otro momento: cuando la hoja con la cartera aparece en el ordenador de un
competidor.

La exportación devolvía las filas y la cabecera de la marca **por separado**, y
ponerla quedaba de parte de quien escribiera el cliente. Pedirle a cada uno que se
acuerde es pedirle al próximo que se olvide — y el que se olvida produce un
fichero idéntico al bueno salvo en lo único que importa.

Con `?formato=csv`, la exportación devuelve **el fichero ya montado y ya
marcado**, con la marca arriba y abajo: recortar las primeras líneas al pegar un
fragmento en un correo es lo más habitual, y recortar el final también. Y se monta
con el módulo estándar, no a mano: a mano, el primer nombre de empresa con una
coma dentro desplaza todo lo que viene detrás, el fichero se abre igual y los
datos están cambiados de sitio.

### El volcado al SIEM

Quien tiene un SIEM quiere los eventos de seguridad en él, no en otra pantalla
más. El volcado estaba escrito —formato neutro, en flujo para que un año de audit
trail no se cargue entero en memoria— y **sin ruta**.

`GET /api/v1/grc/auditoria/volcado.jsonl` lo sirve en JSON Lines, con la marca de
origen como primera línea y, en cada apunte, su **secuencia y su hash**: es lo que
permite a quien lo recibe comprobar que no falta nada por el camino.

Llevarse el audit trail entero cuenta como exportación masiva y exige segundo
factor. Que lo pida un SIEM no lo hace menos sensible: lo hace más frecuente.

## El cambio perdido: el ETag se emitía y no lo miraba nadie (`CRM-00.02.01.09`)

Dos personas abren la misma ficha. Las dos editan. La segunda en guardar **pisa
el cambio de la primera, y ninguna de las dos se entera**. No da error, no deja
rastro, y se descubre semanas después cuando alguien pregunta por qué el dato que
escribió no está.

El producto tenía las tres piezas para evitarlo y ninguna encajaba con la
siguiente:

- El **ETag** salía en cada respuesta versionada. Bien hecho y con sus pruebas.
- La **comprobación** del `If-Match` estaba escrita y probada… y no la llamaba
  ninguna ruta.
- El **contador de versión** existía como columna en todas las entidades, con su
  documentación explicando que es lo que hay detrás del ETag — y **se quedaba en 1
  toda la vida del registro**, porque la línea que lo activa no la declaraba
  ningún modelo.

Lo tercero es lo que hacía inútiles a las otras dos: con el contador parado, el
ETag de un registro es constante, así que el `If-Match` del cliente habría
cuadrado siempre y la protección habría sido decorativa. Peor que no tenerla,
porque parecía puesta.

Y la documentación del middleware afirmaba que existía un guardián que exigía
usar la comprobación. **No existía.** Una referencia a un guardián que no está
hace que el siguiente que la lea dé por cubierto lo que no lo está.

### Lo que hace ahora

- El contador **sube de verdad** en cada edición, y es la base de datos la que lo
  comprueba: si otro escribió entre medias, la actualización no toca ninguna fila
  y se contesta **409**, con un mensaje que dice qué hacer — releer, mirar qué
  cambió y decidir, no reintentar.
- La ficha genérica **aplica las dos mitades**: `If-Match` al editar e
  `If-None-Match` al leer.
- Mandar `If-Match` es **opcional**: exigirlo rompería a todo el que ya integra
  sin mandarlo. Quien lo manda queda protegido; quien no, se comporta como hasta
  ahora, y eso está en el contrato publicado.

### Los que se quedan fuera, y por qué

Hay modelos cuyo `version` **no es la revisión de la fila**: la versión del
presupuesto que se le manda al cliente, la del fichero que se vuelve a subir. Ésos
se declaran como tales y se quedan fuera del contador automático — incrementarlo
en cada edición cambiaría un dato que alguien de fuera entiende. Van como
excepciones con su motivo, no como una lista de los que sí: una lista de los que
sí se queda corta al primer modelo nuevo, y el que falte se queda sin protección
sin que nadie lo note.

### Y de paso, el cuerpo que no hacía falta

`If-None-Match` ahorra la ficha entera en las lecturas repetidas: cincuenta campos
y sus relaciones, cada vez que alguien vuelve a la pestaña. Se comprueba **antes**
de proyectar, que es donde está el trabajo — hacerlo solo al final ahorraría el
tráfico pero no el enmascarado ni las consultas.

## «¿A quién le mandamos la cláusula mala?» (`CRM-06.01.01.05`, `CRM-06.01.01.06`)

Es la pregunta que se hace el día que alguien descubre que una cláusula de una
plantilla estaba mal. El producto tenía la respuesta montada: una tabla con qué
documento se generó, de qué plantilla y **de qué versión**, y una consulta que la
lee por versión — porque la cláusula mala está en una versión concreta y lo que
hay que saber es quién recibió ésa.

Lo que no tenía era **quien escribiera en la tabla**. La función que compone el
documento decía en su primera línea que dejaba constancia, y no la dejaba: la
única que escribe ahí no la llamaba nadie. Así que la tabla estaba siempre vacía
y la consulta contestaba «a nadie» con toda tranquilidad. Un registro vacío no da
error: contesta exactamente lo mismo que si de verdad no se hubiera mandado a
nadie.

La constancia se deja **al generar y no al archivar**. Hay documentos que se
componen y acaban en un correo sin pasar nunca por el gestor documental, y son
justo los que después nadie puede rastrear. Si el documento se archiva, su
identificador se apunta también; si no, el hueco es un dato, no una falta.

## El análisis de una rama del corpus (`CRM-06.01.01.05`)

Resumir una carpeta entera del gestor documental —o sacar los conceptos que
aparecen en ella— estaba escrito, con su plazo propio medido en minutos, porque
pasa por el modelo de lenguaje y el de embeddings puede tardar en cargar en frío.
Tenía hasta una nota diciendo que **solo se llama desde un trabajo de fondo**.

No había trabajo de fondo. Ni ruta. Era una capacidad que no se podía pedir de
ninguna forma.

Ahora `POST /api/v1/documentos/analisis-de-rama` **encola** el análisis y
devuelve la ficha del trabajo. Hacerlo dentro de la petición daría un 504 con el
trabajo hecho y tirado — y lo peor es que funcionaría en pruebas, con el modelo
caliente, para fallar el lunes por la mañana.

Tres decisiones que importan:

- **Una rama por tanda.** Cada análisis puede tardar minutos; una tanda que se
  come veinte es un commit de media hora que, si el worker se cae, se repite
  entero.
- **Las citas vuelven agrupadas por documento.** Las del gestor son de
  *fragmento*: varias salen del mismo fichero, y pintarlas tal cual da una lista
  con el mismo documento repetido cuatro veces, que parece un fallo y no lo es.
  Las huérfanas —cuyo documento ya no está— se marcan y no se esconden: un
  resumen apoyado en algo que ha desaparecido es información.
- **Una rama que falla no para las demás**, y se consume igual: si no, el trabajo
  se quedaría reintentando la misma eternamente.

Lo resuelve el gestor **con un token del usuario**, así que cada uno analiza lo
que vería entrando al gestor, no el corpus entero del cliente.

## El plan no acotaba nada, y el panel enseñaba ceros (`CRM-00.01.04.05`, `CRM-00.01.06.07`)

Un plan comercial declara sus topes en datos: 5.000 correos al mes, 10.000
registros. **Y no los aplicaba nadie.** Lo que corta de verdad lee los ajustes
del cliente, y los ajustes no sabían del plan; el único resolutor que sí lo
miraba lo usaban dos pantallas, y ninguna de las dos corta nada. Se podía vender
un plan con límites y no se cumplía ninguno.

Ahora, al dar de alta al cliente, **las cuotas del plan se escriben como ajustes
suyos**. Se materializan en vez de que cada lector consulte el plan porque el
plan vive en un solo servicio y los trece no lo leen —ni deben—, mientras que los
ajustes ya se replican a todos.

**Lo negociado a mano no se pisa.** Un cliente al que se le subió el tope por una
negociación no puede perderlo porque alguien le reasigne el mismo plan: el ajuste
propio manda, y eso se respeta aquí en vez de confiar en que nadie vuelva a
pulsar el botón. Las que se respetan se dicen, para que quien reasigna no crea
que ha dejado al cliente con los topes del plan.

### El panel de consumo

Enseñaba **cero de todo, siempre**, con los topes bien puestos al lado — que es
lo que lo hacía creíble: «has usado 0 de 5.000 correos» el mes que mandaste
cuatro mil. Leía una tabla de contadores que sólo escribía una función sin
llamantes.

Ahora sale de lo que se mide de verdad, que es de donde sale la cuota que corta:
se cuentan las filas. Un contador aparte se desincroniza el primer día que algo
se borra por otra vía —una purga, una fusión, una baja— y entonces el cliente ve
una cuota agotada que no se corresponde con lo que tiene.

Una métrica que no se puede medir **se dice en su fila** y no tumba el panel. Y
«no se ha podido medir» no es «cero», que es justo la confusión que había.

Lo mismo con el componente de estado de la plataforma: leía esa misma tabla, así
que **no podía avisar de una cuota agotada ni queriendo**.

## La marca blanca no tenía ni una ruta (`CRM-00.01.04.06`)

Poner un logo es fácil; lo que cuesta es que no se escape la marca del fabricante
por ningún sitio. Se escapa siempre por los mismos cuatro: el remitente de los
correos, el dominio de los enlaces, el pie de las plantillas y el título de la
pestaña. Con uno solo mal, el cliente descubre a su proveedor delante de su
propio cliente.

Todo eso estaba resuelto —incluido el contraste de los colores, porque una paleta
corporativa preciosa con texto gris sobre blanco deja media aplicación ilegible—
y **era inalcanzable desde fuera**. No faltaba una pieza: faltaban todas las
puertas.

Ahora, en `/api/v1/marca`: ver qué falta y por qué, configurar (**sin activar**,
porque se configura por partes y activar a medias es lo que hace que el primer
correo salga con el dominio del fabricante), anotar la verificación del dominio
—la comprobación de DNS la hace quien sabe hacerla; aquí se guarda el resultado y
el detalle, porque «lo verificamos en su momento» no es una respuesta cuando un
año después los correos rebotan— y activar, solo si está completa.

## La firma del chat entrante no caducaba (`CRM-06.01.01.03`)

Una orden que llega de un espacio de chat viene firmada, y se comprobaba con un
HMAC propio: una **tercera** implementación del mismo cálculo. La que menos se
mira es la que se queda corta, y ésta no miraba el instante — así que un mensaje
capturado una vez valía para siempre. Quien pudiera repetir una orden podía
repetirla mil veces, y lo que hay al otro lado son cambios en el CRM.

Ahora se usa la verificación del núcleo, que tiene ventana anti-reenvío y es la
que se publica en el manual del integrador. El instante **no se exige**: cada
plataforma manda su cabecera con otro nombre y hay quien no la manda. Cuando no
viene, el canal queda marcado como **reproducible al declararlo** — que es el
momento en que alguien puede hacer algo, no un silencio que se descubre tarde.

## Las ocho pantallas que no tenían prueba de contenido (`CRM-07.04.03`)

Que una pantalla **monte** no dice nada: monta igual con la tabla vacía. Lo que
importa es que lo que trae el servidor llegue a una fila, y eso no se ve mirando
el código — se ve cuando alguien abre la pantalla.

De veintisiete, diecinueve ya lo comprobaban. Las ocho restantes estaban
nombradas como exentas, cada una con su motivo: «vive de un flujo de eventos»,
«depende de qué recurso se abra», «no pide nada a la API». Esos motivos explican
por qué eran **más difíciles**, no por qué eran imposibles — y una lista de
exenciones que nadie vuelve a mirar acaba siendo la lista de lo que no se prueba.

Ahora las nueve tienen su escenario, cada una con el testigo que de verdad
recorre su camino:

- **Inicio** enseña los roles de quien ha entrado: son los que deciden qué ve.
- **Recorrido** enseña los módulos del catálogo que lleva dentro; si dejara de
  llegar a la pantalla, quedaría una lista de encabezados vacíos.
- **Ayuda** lleva **al capítulo de la pantalla en la que estás**. Con el mapa
  roto seguiría pintando un botón, y el botón llevaría al índice general: mandar
  a buscar a quien está atascado.
- **Entrar** dice por qué no se ha podido entrar. Un formulario que se traga el
  motivo deja a la persona probando la misma contraseña.
- **Consola** enseña las áreas que declara la superficie del servidor.
- **Ficha** titula con el registro que ha cargado. Antes era un identificador de
  treinta y seis caracteres, y la ficha no decía cuál se estaba mirando.
- **Chat** enseña las conversaciones que le llegan. La exención confundía dos
  cosas: lo que no se puede probar fácil es el flujo de mensajes nuevos, no la
  pantalla.
- **Portal** pinta tras el canje del enlace del correo.
- **Procesos** ofrece con qué editar: un editor sin editor monta igual.

Las cuatro mutaciones plantadas —quitar los roles, quitar los módulos, mandar al
índice en vez de al capítulo, dejar las áreas sin nombre— las caza su escenario.

## A qué puede apuntar una referencia (`CRM-00.04.01.03`)

Una relación polimórfica dice que una actividad puede colgar de una cuenta, de un
contacto o de una oportunidad. Lo que **no** puede es colgar de cualquier cosa.

Sin esa comprobación, una referencia acaba apuntando a un tipo que nadie previó.
Y no falla al escribir —el valor cabe— sino meses después, cuando alguien recorre
esas referencias y se encuentra un identificador que no resuelve a nada.

La regla estaba escrita y **no la llamaba nadie**: fue la última de las noventa y
dos funciones que la sonda llegó a marcar, y aguantó más que ninguna porque su
motivo era estructural. Vivía en el servicio que **declara** las relaciones, y
quien **escribe** los valores son los otros doce, que no leen ese esquema. Una
regla que vive donde se declara y no donde se aplica es una regla apagada.

Ahora:

- La regla vive en el núcleo, que es por donde pasan todas las escrituras de
  campos propios.
- Las relaciones del objeto **viajan replicadas con su esquema**, por el mismo
  camino que sus campos: un diccionario por relación con lo justo para decidir
  —cómo se llama, de qué tipo es y a qué admite apuntar—. Mandar el resto sería
  replicar decisiones que sólo sabe aplicar quien las declara.
- El servicio que declara las relaciones sigue comprobándolas, usando **la misma**
  regla. Dos implementaciones divergen, y la que menos se mira es la que se queda
  corta.

Dos decisiones que importan:

- **Sin destino declarado se admite cualquiera.** Vacío es «sin acotar», no «no
  admite ninguno»: obligar a enumerar los destinos antes de saberlos haría que
  nadie declarara una relación.
- **La relación de un campo no se adivina por parecido.** Dos relaciones hacia el
  mismo objeto son dos cosas distintas —«cuenta que lo paga» y «cuenta que lo
  usa»— y elegir la que coincida acertaría casi siempre, que es la peor clase de
  casi.

Y el error dice **a qué sí podía apuntar**: «destino no admitido» a secas obliga a
ir a buscar la definición para saber qué poner.

## La cola llevaba a una pantalla que no existía (`CRM-04.02.02.01`, `.02`, `CRM-04.02.01.03`)

La consola de agente enseña una sola cola con los casos y las conversaciones de
todos los canales, y cada fila enlaza al registro. La de una conversación
apuntaba a `/m/conversaciones/conversacion/{id}`, y ese módulo **no existe**:
quien pulsaba una conversación de la cola llegaba a «no existe».

Detrás había tres operaciones publicadas y probadas desde hacía meses sin un
solo botón que las llamara: responder (o dejar una nota interna), cambiar de
canal y escalar a una persona.

Ahora hay pantalla, y lo que decide su forma es el problema que la omnicanalidad
viene a resolver:

- **El hilo es el del cliente, no el de esta conversación.** Se pide por
  contacto o por identidad externa, y trae todo lo hablado por cualquier canal.
  Quien escribió el lunes por correo, llamó el martes y abrió un chat hoy está
  teniendo **una** conversación; enseñar sólo los mensajes de este hilo es lo
  que hace que se le pregunte tres veces lo mismo.
- **No agrupado por canal.** Agrupar reproduce el problema. El canal va como
  etiqueta en cada mensaje.
- **La nota interna se dice con palabras**, no sólo con un color: es lo único
  que la separa de una respuesta que sale hacia el cliente. Y no cuenta como
  primera respuesta —eso lo decide el servidor—, porque si contara el indicador
  de «cuándo contestó una persona» saldría magnífico sin medir nada.
- **Cambiar de canal no abre una conversación nueva.** Si la abriera, pasar de
  chat a correo perdería lo hablado y el cliente tendría que explicarse otra
  vez. Se dice en la propia pantalla para que nadie abra una «por si acaso».
- **Escalar reusa como motivo lo que ya se había escrito.** Pedirlo en otra caja
  obliga a escribirlo dos veces.
- **Sin `case:write` el hilo se lee y no hay caja de respuesta.** Quien decide
  sigue siendo el servidor; esconder lo que va a dar 403 sólo evita hacerle
  perder el tiempo a quien lo pulsa.

Una conversación que no está ligada a ningún cliente no tiene historial que
traer: el extremo responde 422 si no se le da contacto ni identidad, y la
pantalla lo dice en vez de enseñar un error.

## Lo que un menú dice que enseña, y lo que su pantalla pide (`CRM-07.04.05.01`)

El informe de cobertura del front cuenta un recurso como enseñado en cuanto una
entrada de menú lo declara. **Nadie comprobaba esa declaración**, y declarar es
gratis mientras que callar sale caro: la lista se había llenado de recursos que
la pantalla no pedía nunca, y el informe —que es el que se mira para decidir qué
falta— daba por cubierto lo que no existía.

Medido el 27-10-2026: de 45 recursos declarados, **30 no los pedía ningún
fichero del front**. Entre ellos `aprobaciones` (once operaciones; la pantalla
de aprobaciones pide `documentos`, que es otra cosa), `aislamiento` y
`residencia` (31 operaciones que sólo tenían puerta por API) y
`aprobaciones-documentales`, que ni siquiera existe como recurso: cero
operaciones con ese nombre.

Quedan en 18, y el resto están en su sitio:

| Dónde | Qué se ve ahora |
|---|---|
| Tenants y unidades | Aislamiento, sus migraciones, residencia, subprocesadores y transferencias internacionales (`tenant:read`) |
| Procesos y orquestación | Las aprobaciones del motor, con «revisar plazos» (`aprobacion:read`) |
| Operación | Encargos a proveedor con entregados sin prueba, cumplimiento y estados sin mapear, más «revisar silencios» y «conciliar»; plantillas de documento; firma presencial |
| Casos | Créditos de servicio y cumplimiento de SLA (`case:read`) |
| Campañas | Recorridos |
| Contenido y gobierno | Activos de marketing |

Cada uno con el permiso que exige su operación, y no al revés: una pestaña que
sólo sirve para enseñar un 403 es peor que no tenerla.

La comprobación que lo sostiene es deliberadamente tonta —que el literal de la
ruta aparezca en algún fichero del front que no sea la propia navegación ni el
informe— y vive dentro del gate de pantallas que ya existía, sin sumar una
entrada nueva al preflight. No demuestra que la pantalla lo enseñe bien;
demuestra que lo pide, que es la mitad que faltaba.

## Identidad y seguridad: cuatro preguntas que no son una tabla (`CRM-00.05.01.15`, `.17`, `.25`, `CRM-00.05.02.11`, `CRM-07.03.02.06`)

El módulo genérico «Identidad y acceso» ya lista lo que es una colección:
usuarios, roles, políticas, claves de API, sesiones, dispositivos de confianza
y proveedores de identidad. Lo que no puede listar es lo que **no es una
tabla**, y resulta ser justo lo que un administrador necesita saber. Las cuatro
tenían su extremo publicado y ninguna tenía puerta.

**Quién no tiene segundo factor.** Un panel que diga «78 %» no sirve: el trabajo
es hablar con los que faltan, así que lo que se enseña es la lista, con su
correo y sus roles. El porcentaje va con el **N al lado** — un 78 % sobre nueve
personas no es lo mismo que sobre novecientas, y sin el N se leen igual. Avisa
además de dos cosas que cambian cómo se lee ese número: si el segundo factor no
es obligatorio en el tenant, y si hay canales débiles activos (SMS, correo), que
cuentan como factor y se interceptan sin tocar el dispositivo.

**Qué certificado del proveedor de identidad caduca.** Ordenados por urgencia y
no por proveedor: primero los caducados, luego los que caducan pronto. Un
certificado de IdP que caduca no avisa — un sábado por la noche deja de validar
toda aserción y el lunes no entra nadie de la empresa.

**Quién tiene hoy permisos incompatibles.** Se calcula en vivo y no se guarda:
una lista de conflictos vieja es peor que ninguna, porque se actúa sobre ella.
Los que tienen excepción vigente **salen igual, marcados**; esconderlos haría
que una excepción caducada pasara de «aprobado» a «no existe» sin que nadie lo
viera.

**Por qué esta persona puede hacer esto.** Sin el explicador, la respuesta se
busca leyendo roles, políticas y reglas de compartición a la vez, y se contesta
mal.

Lo que la pantalla **no** declara, aunque lo roce: la MFA obligatoria
configurable por rol (`CRM-00.05.01.06`). Aquí se ve si está puesta; no se
configura, y declarar lo que no se hace es justo lo que la traza existe para
impedir.

## Dos listas escritas a mano que se quedaban cortas

**Lo que un menú dice que lleva, lo tiene que pedir esa pantalla.** La primera
versión de esa comprobación medía flojo: pedía que el recurso lo pidiera *algún*
fichero del front, no *la pantalla a la que lleva el menú*. Con la regla floja
salían 18 reclamos falsos; con la buena, **35 de 46**. Y la diferencia no es
contable: esa lista es la que contesta «¿dónde veo esto?», así que un reclamo en
la entrada equivocada manda a quien busca los recorridos a Marketing, donde no
están, en vez de a Campañas, donde sí.

Se quitaron los 35 en el mismo commit. Dieciséis sobraban —el recurso se enseña
en un módulo genérico, que ya lo declara por su cuenta— y diecinueve no se
enseñaban en ninguna parte, así que vuelven al informe de cobertura como lo que
son: potencia escondida en la API. No hay tope que mantener: o la pantalla lo
pide, o el reclamo sobra.

**El barrido de pantallas se leía de una lista a mano.** Y la red que lo
protegía era «que haya al menos 22», así que una pantalla nueva no entraba y
nadie se enteraba: veintidós seguían siendo veintidós. Pasó con «Identidad y
seguridad» el mismo día de añadirla. Ahora la lista se lee del propio enrutador,
descartando las rutas con parámetro —una ficha no se abre sin un registro
delante— y las redirecciones.

**Y las pantallas no se comprobaban en absoluto.** El pase completo devolvía 23
pantallas «rotas» que eran un navegador sin instalar: veintitrés rojos idénticos,
ninguno del código. Veintitrés fallos que no significan nada son la forma más
rápida de que alguien deje de mirar ese gate, y el día que una pantalla se rompa
de verdad estará ahí, en la lista, con las otras veintidós. Ahora se para antes
con un mensaje que dice qué instalar.

## La IA publicaba 71 operaciones y la pantalla enseñaba la salud de una cuenta (`CRM-05.02.01.04`, `.05`, `.07`, `CRM-05.02.02.07`, `.09`, `.10`, `CRM-05.02.03.01`, `.03`, `.04`)

`/api/v1/ia` publica setenta y una operaciones. La única pantalla de
inteligencia que había contesta una pregunta legítima —qué sabe la IA de esta
cuenta y por qué— y ninguna de las que hace quien **responde** de la IA:

- **Quién presta el servicio, en qué región y a qué coste**, y si el proveedor
  es propio del cliente. Es la primera pregunta de quien firma la factura y de
  quien tiene que decir dónde acaban los datos. Ahí mismo se ve el *opt-out* de
  entrenamiento por proveedor: un *opt-out* que consta en un contrato y no en
  la pantalla no lo comprueba nadie.
- **Qué modelos hay**, con su versión, su estado, sus métricas, cuándo se
  entrenaron, con qué ventana de datos y con qué vigencia; se activa una
  versión y se calcula la deriva.
- **Qué agentes autónomos están sueltos.** Un agente que nadie ve es un proceso
  con permisos corriendo solo. Se ven sus herramientas, sus permisos acotados,
  su máximo de acciones, su presupuesto de tokens al día y desde qué importe o
  qué nivel de riesgo pide aprobación humana. Se apagan desde su ficha, y el
  apagado deja su motivo escrito. Sus herramientas se pueden generar **desde el
  contrato** —de las propias operaciones publicadas— en vez de escribirlas a
  mano.
- **Y cuando actúa, actúa como un usuario más.** El agente no escribe en la
  base: llama a la misma API que usa cualquier pantalla, **con su propia
  identidad y sus propios permisos**, que normalmente son menos que los de
  quien lo puso en marcha. Eso tiene tres consecuencias que se notan: lo que no
  puede hacer una persona con esos permisos tampoco lo puede hacer el agente;
  todo lo que hace aparece en el rastro de auditoría a nombre del agente y no
  de «el sistema»; y un error suyo tiene el alcance de sus permisos, no el de
  la plataforma. Los pasos se ejecutan **de uno en uno**, porque entre paso y
  paso es donde caben el apagado, el tope de acciones y la aprobación humana.
  Si un paso falla, la ejecución se para: seguir con los siguientes de un plan
  cuyo tercer paso falló es ejecutar un plan que ya no tiene sentido.
- **Qué bloquearon las guardias.** Una guardia sin registro es una promesa:
  nadie puede decir si ha actuado alguna vez.
- **Cuánto cuesta**, con la tasa de descarte —cuánto de lo que se paga se
  tira— y la curva por día, que es donde se ve el salto del martes que nadie
  pidió.
- **Qué cuentas marca el modelo en riesgo**, que es la lista sobre la que se
  trabaja.

Y lo que **no** se ha fingido: transcripciones, variantes, voz y sugerencias de
caso son extremos de análisis —un `POST` que devuelve un cálculo—, no listados.
Su sitio es dentro de la actividad, del caso o de la campaña; una pestaña que
pida un JSON a mano no es una pantalla, es una calculadora en la que el usuario
tiene que ser el modelo. Tampoco se declara la trazabilidad por registro
(`CRM-05.02.02.08`): su extremo cuelga de un registro y su sitio es la ficha,
que todavía no lo pinta.

**Una asimetría más, la misma de siempre.** Las anomalías tenían la acción
«decir si el aviso valía» y no tenían forma de abrir el aviso. Ahora publican su
ficha con el valor, lo esperado, la desviación y la explicación, que es lo que
hace falta para contestar si era real sin contestar a ojo — y una respuesta dada
a ojo no mide el detector: mide a quien la dio.

## Qué capacidad merece pantalla, y cuál no (`CRM-07.04.05.02`)

El recuento de «capacidades que ninguna pantalla enseña» mezclaba dos cosas muy
distintas: lo que falta por construir y lo que **no se construye nunca porque no
es una pantalla**. En la misma lista estaban «el diseñador visual de
formularios» y «gRPC para comunicación interna», y eso hace que el número no
sirva para decidir nada.

La regla es estrecha a propósito: una capacidad sale del recuento **sólo si no
hay nada que una persona pueda ver ni hacer** sobre ella — es un protocolo, una
garantía del servidor o una propiedad de la arquitectura. Si un administrador
podría querer ver su estado, es pantalla y se queda dentro. Por eso siguen
contando el *sandbox* de API, el portal de desarrollador, la lista blanca de IP
o el depurador de automatizaciones: todos tienen algo que mirar.

Las veintinueve primeras marcadas así son las de siempre: GraphQL y gRPC,
idempotencia, ETag, paginación por cursor, Problem Details, la firma HMAC de los
webhooks, la entrega al menos una vez, el CDC hacia el lago del cliente, la
ordenación por agregado, el patrón BFF, los SDK, mTLS, el *service mesh*, el
*outbox* transaccional y las garantías del motor de procesos.

**Marcar es la salida barata, así que cuesta.** El motivo va escrito capacidad a
capacidad en el catálogo, **se publica en la hoja de estado** —cualquiera lo
lee— y hay una comprobación que exige que sea una frase y que no repita el
enunciado de la capacidad, que sería no haber pensado nada. Sin eso, el camino
rápido para bajar el número sería marcarlo todo.

Y la consola de administración declara lo que pinta sólo ella: las claves de
cifrado del cliente, los *flags*, las plantillas, los calendarios, las monedas,
las reglas de compartición y los buzones. Aparecen porque el servidor etiqueta
esas operaciones como de administración y la consola se construye de ahí; si una
desapareciera del servidor, dejaría de pintarse y el recuento por capacidad lo
diría.

## Diez columnas que existían y la API no devolvía (`CRM-01.01.01.07`, `.09`, `CRM-01.01.02.01`, `.05`, `CRM-01.01.04.10`)

Al ir a declarar qué enseña la pantalla de cuentas y contactos apareció otra
cosa: el modelo tiene columnas que **el esquema de salida no incluye**, así que
la pantalla no puede enseñarlas por mucho que existan. No es un olvido
inofensivo — son justo las que cierran una capacidad:

| Objeto | No salía | Qué se perdía |
|---|---|---|
| Cuenta | `clasificacion_abc` | La segmentación que se vende son seis cosas y llegaban cuatro. El ABC estaba incluso en el esquema de alta: se podía escribir y no leer |
| Cuenta | `es_personal` | Una cuenta B2C no se distinguía de una B2B en ninguna pantalla |
| Contacto | `frecuencia_maxima`, `horario_preferido` | «Respetar la preferencia del contacto» era media promesa: el canal y el idioma sí, cuántas veces y a qué horas no |
| Contacto | `estado_email`, `estado_telefono` | No se podía distinguir una dirección verificada de una escrita. Un correo sin verificar que se lee como bueno es una campaña que rebota entera |
| Contacto | `email_secundario`, `canales` | Los canales alternativos declarados no llegaban a ninguna parte |

Es el mismo patrón que la tabla de recursos del paquete o la acción sin ficha:
las dos mitades existen y nadie las junta. La diferencia aquí es que el síntoma
es invisible — la pantalla sale bien, sólo que incompleta, y nadie echa de menos
un campo que nunca ha visto.

## Y veintinueve columnas más, en actividades, leads y oportunidades

Medido el mismo día sobre los trece servicios: **136 columnas en 32 esquemas de
lectura** que existen en la tabla y no salen por la API. No todas son un fallo
—`hash_contrasena`, `mfa_secreto` y el secreto de un webhook **no deben salir
nunca**—, pero las de los objetos que se trabajan a diario sí:

- **Una actividad llegaba a la pantalla sin hora.** `inicio_at` y `fin_at` no
  salían, así que de una visita del martes a las diez sólo se veía que vencía
  el martes, que es otra cosa. Con ellas van el recordatorio —cuándo avisa,
  cuántos avisos van y cuántos caben— y las reprogramaciones, que son la señal
  de que algo se está evitando.
- **Un lead sin su procedencia ni su pulso.** No salían la campaña, los
  parámetros UTM, el país ni la web, así que de qué campaña salió un lead no se
  podía ver en ninguna pantalla — justo lo que se pregunta al repartir
  presupuesto. Tampoco cuándo se asignó ni cuándo fue el primer y el último
  toque: sin eso, un lead de hace tres semanas sin tocar no se distingue de uno
  de ayer. Y faltaba la nota del descarte: el motivo normalizado dice «precio»,
  la nota dice cuál era el precio del otro.
- **Una oportunidad sin contra quién se perdió.** No salían el competidor que
  ganó ni la nota de pérdida, así que el informe de pérdidas decía «precio»
  cincuenta veces sin decir contra quién. Tampoco la probabilidad puesta a mano
  —saber si la cifra es la de la etapa o la que puso alguien es lo que separa
  una previsión creída de una inventada—, ni la categoría de previsión, ni
  desde cuándo lleva parada en su etapa, ni el importe en la moneda de la casa,
  que es lo que permite sumar un pipeline con cuatro monedas sin que cada
  pantalla invente el cambio.

## Cerrar el objetivo de un periodo (`CRM-03.02.02.08`)

El objetivo de un trimestre se discute, se negocia y en algún momento se da por
bueno. A partir de ahí, **los informes de consecución, las comisiones y las
revisiones se calculan contra ese número**. Si el número puede cambiar después
—y cambia siempre, porque alguien reimporta la hoja o corrige una celda— nadie
puede decir contra qué se midió a nadie, y el informe del mes pasado deja de
cuadrar sin que haya constancia de por qué.

El problema es de confianza, no de permisos, y por eso el cierre tiene cuatro
decisiones escritas:

- **Qué se congela.** El **objetivo**, no la consecución: lo vendido sigue
  entrando. Congelar la consecución sería congelar la realidad.
- **Quién puede.** `forecast:congelar`, aparte de `forecast:write`. Fijar una
  cuota es trabajo de todos los días y cerrar el periodo no: quien pueda cerrar
  y reabrir puede cambiar contra qué se mide a la gente. Lo tiene el
  responsable de ventas, no el comercial.
- **Qué pasa con lo ya cargado.** Lo cargado se queda; lo que se rechaza es el
  cambio, **con nombres y fechas**: «el objetivo de 2026-T3 se congeló el 14 de
  julio (plan aprobado en comité)». Un «no se puede modificar» a secas manda a
  preguntar a quien no sabe, y lo que hace falta es saber a quién pedir la
  reapertura. La comprobación vive en el servicio y no en la ruta, porque la
  carga masiva desde una hoja entra por otro camino — y dejarla en la ruta la
  dejaría fuera justo por donde se recargan las cuotas.
- **Cómo se descongela.** Con **motivo obligatorio**. Permitir una reapertura
  sin motivo convierte el cierre en un trámite de dos clics, que es no tener
  cierre.

Y es **una fila por congelación, no un interruptor**: descongelar y volver a
cerrar es legítimo —se revisa el plan a mitad de año— y con un booleano el
segundo cierre pisaría al primero, de modo que «¿cuándo se cerró y por qué se
reabrió?» no tendría respuesta.

Cerrar un trimestre no cierra los demás: si cerrara el año entero, cerrar el
tercer trimestre impediría planificar el cuarto, que es justo cuando se hace.

## El mapeo copiaba valores, y nada más (`CRM-00.03.04.04`)

El conector genérico traducía los campos de una API ajena a los nuestros: de
dónde sale cada uno, con alternativas y marcadores de vacío. Y ahí se acababa.
Lo que pasa en toda integración de verdad es que el valor **no sirve tal cual**
— el código viene con espacios, el país en minúsculas, el importe como texto
con coma decimal, la fecha con el formato del otro lado, la referencia con un
prefijo que aquí sobra.

Sin transformaciones hay dos salidas y las dos son malas: escribir un conector
a medida por cliente —que es justo lo que el conector genérico existe para
evitar— o meter los datos sucios y arreglarlos después, cuando ya han disparado
automatizaciones.

Ahora son tres pasos:

1. **Mapear**, como antes.
2. **Transformar**: `recortar`, `mayusculas`, `minusculas`, `quitar_prefijo`,
   `quitar_sufijo`, `numero`, `booleano`, `fecha`, `defecto` y `mapa`.
3. **Validar**: qué campos son obligatorios y qué valores se admiten.

**Es una lista cerrada, nunca una expresión.** Una expresión arbitraria en la
configuración de una integración es código de un usuario final corriendo en el
servidor, con los permisos del servicio y sin revisión — la misma decisión que
en las acciones de las automatizaciones, y por el mismo motivo.

Cuatro detalles que deciden si esto sirve:

- **El valor por defecto se aplica también al hueco.** Si sólo corriera sobre
  lo que viene, no serviría para nada: es la transformación más pedida y el
  caso es justo que el campo falte.
- **La fecha no se adivina.** Con el formato del otro lado se convierte; sin
  él, ISO. Elegir entre `%d/%m` y `%m/%d` por sorteo mete una fecha equivocada
  que nadie revisa — el 3 de abril y el 4 de marzo son los dos válidos.
- **Un código que no está en la tabla se deja como viene**, y entonces lo
  rechaza la validación si el campo tiene lista cerrada. Es mejor que inventar
  un estado que aquí no significa nada y que nadie volverá a mirar.
- **Lo que no cumple ni se cuela ni se tira en silencio**: se aparta con su
  motivo y sale en el resultado. Colarlo mete datos sucios; tirarlo callando
  deja una importación que dice «200 registros» y guarda 180 sin que nadie
  pregunte, y el hueco se descubre semanas después.

Y una función mal escrita —`mayuscuals`— se caza **al publicar el conector**,
no en la primera importación de un cliente, donde ya hay registros a medio
traducir y nadie sabe cuáles. Lo mismo con una regla que valide un campo que el
mapeo no produce: rechazaría todos los registros y el motivo señalaría a un
campo que no existe.
