# Manual V — Arquitectura y referencia técnica

Para quien va a tocar el código o va a evaluar si esto aguanta lo que promete.

## La forma del sistema

```
                        ┌──────────────┐
   cliente ─── HTTPS ──▶│   gateway    │  tenant · identidad · límites · rutas
                        └──────┬───────┘
                               │ HTTP con identidad FIRMADA
       ┌───────────┬───────────┼───────────┬───────────┐
       ▼           ▼           ▼           ▼           ▼
   tenancy     identity    metadata   orchestrator  automation …
       │           │           │           │           │
       └───────────┴─────┬─────┴───────────┴───────────┘
                         │
              ┌──────────┴──────────┐
              ▼                     ▼
       Postgres (un esquema      NATS JetStream
        y un rol por servicio)   (subject por tenant)
```

Ocho servicios, cada uno con **su esquema y su rol de base de datos**. Entre
ellos se hablan **por el bus**, no por HTTP: una llamada síncrona entre servicios
crea acoplamiento temporal, y entonces la caída de identidad es la caída de
ventas. La única excepción es el gateway, que por definición llama a todos.

## El bus de eventos no entregó nada durante toda la vida del proyecto

Se descubrió el 25-09-2026 y conviene que quede escrito, porque son **tres
fallos encadenados y ninguno grita**.

**1. El subject de publicar y el de suscribirse no eran hermanos.** Se publicaba
en `contecrm.<tenant>.<tipo>` —el tenant va en el subject para poder repartir por
cliente— y se suscribía a `contecrm.<tipo>`, sin ese segmento. Ningún subject
casaba con ningún patrón. Resultado medido: **757 eventos publicados y la tabla
de entrantes a CERO en los trece esquemas**.

**2. Los consumidores durables conservan el filtro con el que nacieron.**
Arreglado lo anterior, seguía sin llegar nada: JetStream no cambia el
`filter_subject` de un consumidor existente al volver a suscribirse, así que
seguían escuchando lo que ya no se publicaba. Ahora el bus lo comprueba al
suscribirse y rehace el consumidor si no coincide, dejándolo dicho en el registro.

**3. Todos los consumidores leían un campo que no existe.** Los dieciséis hacían
`getattr(mensaje, "tipo", None)` y el sobre lleva `type`. Como `getattr` con
defecto no se queja, cada manejador decidía en su primera línea que el evento no
era para él. Hoy `Evento.tipo` es un alias de `type`: el nombre de fuera es
contrato con quien nos escuche y el de dentro es el idioma de la casa.

**Por qué sobrevivió tanto.** Publicar SÍ funcionaba: la tabla de salida se
llenaba y se marcaba como publicada, así que desde dentro parecía que el evento
había salido. Y lo que dependía de recibir no fallaba — simplemente no ocurría:
la salud no aparecía en la ficha de la cuenta, los ajustes replicados se
quedaban con los de ayer, la clave del tenant no se propagaba. Ninguna de esas
cosas se lee como una avería; todas se leen como «esto todavía no está hecho».

Y **ninguna prueba cruzaba las dos mitades**: las que había comprueban que el
evento se escribe en la tabla de salida, que es la mitad fácil.
`tests/unit/test_bus_entrega.py` comprueba la otra.

## Las tres decisiones que lo ordenan todo

### 1. Lo transversal se impone, no se pide

Un servicio no monta su aplicación: llama a `crmcore.service.crear_servicio()` y
recibe una que ya trae el contexto de tenant, los límites, el formato de errores,
las métricas y el guard de aislamiento. Si cada servicio los montara, tarde o
temprano uno se dejaría el de tenant —o lo pondría en el orden que no es— y el
fallo no se vería hasta que dos clientes se vieran los datos.

Hay un gate que comprueba que ningún servicio instancia `FastAPI` directamente.

Lo mismo vale para lo que cada servicio tiene que **escuchar**. Hay tablas que
viven en el esquema de todos —`ajustes_runtime`, las claves BYOK del tenant,
`documentos_enlazados`— porque ningún servicio lee el de otro. Eso obliga a que
ciertos eventos los consuma **todo el mundo**, y `crear_servicio()` los suscribe
sin que ningún servicio tenga que acordarse:

| Evento | Qué pasaría si un servicio no lo consumiera |
|---|---|
| `configuracion.ajuste_cambiado` | Se quedaría con la configuración de su `.env` mientras el resto usa la del cliente. La divergencia tarda semanas en atribuirse |
| `seguridad.clave_tenant_cambiada` (BYOK) | Seguiría cifrando con la maestra, y revocar la clave del cliente no dejaría ilegible nada — el único modo de fallo inaceptable de BYOK |
| `documental.inventario.solicitado` | Sus documentos del corpus quedarían fuera del certificado de destrucción, y el cliente creería que ya no existen (RT-5) |

La regla que hay detrás: **cuando una garantía transversal depende de que N
servicios hagan algo, no se documenta, se suscribe en el sitio por el que pasan
todos.** Lo que se deja a que cada uno se acuerde, uno no se acuerda.

### 2. El aislamiento por tenant tiene tres capas, no una

| Capa | Qué cubre | Qué NO cubre |
|---|---|---|
| **RLS en Postgres** | Todo, incluido SQL crudo | Un rol SUPERUSER o con BYPASSRLS se la salta |
| **Guard ORM** | SELECT/UPDATE/DELETE del ORM | Sentencias Core o `text()` |
| **Filtros explícitos** | Lo que el servicio decida | Lo que se olvide |

Cada una cubre el hueco de la anterior, y ninguna sobra. La primera es la dura;
la segunda falla antes y explica mejor, y funciona en pruebas sin Postgres; la
tercera es la que hace legible el código.

**Toda tabla de negocio lleva `tenant_id`, sin excepciones no justificadas.** Es
la corrección deliberada de una limitación conocida de `contecmind`, donde 58 de
107 modelos lo tienen y el resto depende de filtros de propiedad: funciona y está
auditado, pero significa que las dos redes automáticas comparten punto ciego,
porque las dos seleccionan tablas por esa columna. Aquí la columna es
obligatoria, las cuatro excepciones están justificadas por escrito y hay un gate
que lo comprueba.

### 3. El contexto se fija en middleware ASGI puro

Y esto no es una preferencia de estilo. `BaseHTTPMiddleware` de Starlette ejecuta
la aplicación de debajo en **otra tarea de asyncio**, que hereda una *copia* del
contexto: lo que fije el middleware no lo ve el endpoint. Como lo que se fija es
el tenant, usar el middleware cómodo significaría que el aislamiento no llega a
la consulta.

Además, la fuente **autoritativa** para la base de datos no es el contextvar sino
`session.info["tenant_id"]`, que se fija al abrir la sesión. El contextvar sirve
para logs, métricas y auditoría, y para el código sin petición (trabajos de fondo
y consumidores del bus).

### 4. Ningún middleware retiene una respuesta hasta el final

Regla de mantenimiento, y está aquí porque se pagó cara: un middleware que
necesite el cuerpo de la respuesta **no puede esperar a tenerlo entero** sin
decidir antes qué hace si no termina nunca.

Un `text/event-stream` no termina: se queda abierto mandando lo que va pasando.
El middleware del `ETag` retenía el `http.response.start` hasta conocer el cuerpo
completo, para poder añadirle la cabecera —lo cual es correcto para una respuesta
normal y **imposible** para un flujo—, así que ninguna respuesta en flujo de
ningún servicio salió jamás: la petición se quedaba colgada, sin error, sin log y
sin un solo byte. El chat en vivo llevaba así desde el primer día.

Lo que se hace ahora, y lo que hay que hacer en cualquier middleware nuevo:

- **Soltar el inicio en cuanto se sepa que no se va a poder añadir nada.** Si el
  `content-type` no es JSON, el `ETag` no se puede calcular —la versión sale del
  cuerpo JSON— así que retener no aporta y puede costarlo todo.
- **Poner un tope a lo que se acumula** (`ETAG_RETENCION_MAX_BYTES`). Pasado el
  tope se suelta lo que haya y el resto va directo, sin cabecera. Una exportación
  de cien megas no vale una cabecera de treinta bytes, y multiplicada por las
  peticiones a la vez es la memoria del servicio.
- **No acumular donde no hace falta.** El middleware de idempotencia guardaba el
  cuerpo de *toda* respuesta, también de las lecturas, que nunca reservan clave.
  Ahora solo mira las escrituras.

Hay una prueba que lo vigila (`tests/unit/test_respuesta_en_flujo.py`) y comprueba
el **momento** en que sale el primer byte, no qué acaba llegando: el contenido sí
llegaba, entero y al final, así que una prueba de contenido lo habría dado por
bueno.

## El camino de una escritura

1. El **gateway** resuelve el tenant, autentica, aplica los límites y reenvía con
   la identidad firmada.
2. El **middleware de contexto** del servicio fija tenant, usuario y correlación.
3. La **dependencia de sesión** abre una sesión atada a ese tenant; de ahí salen
   el `SET app.current_tenant` y el guard ORM.
4. El **servicio** valida, escribe y, en la **misma transacción**, encola el
   evento en la tabla de salida y añade el apunte de auditoría.
5. Al cerrar, todo se confirma junto: o está el cambio, el evento y la traza, o
   no está ninguno de los tres.
6. El **relevo del outbox** publica el evento al bus, con reintentos.
7. El servicio de **eventos** lo entrega a los webhooks suscritos, firmado.

El paso 4 es el que evita el estado imposible más caro de un sistema con bus: la
oportunidad ganada en la base y nadie enterado.

### Una pantalla que lee un campo inexistente no falla: se queda vacía

Es el fallo más caro de los encontrados, porque **no se nota**. No hay error, no
hay traza, no hay 500: el campo llega `undefined`, la lista sale vacía, el reloj
dice «sin plazo» y la pantalla parece que funciona. Y como el escenario de su
prueba se escribe con la forma que la pantalla **se imagina** —no con la que
manda el servidor—, la prueba confirma la ficción.

Dos casos reales, medidos el 26-10-2026:

- La **bandeja de casos** leía `numero`, `vence_at`, `cola` y `escalado`; la API
  devuelve `codigo` y `vence_resolucion_at`. Todos los casos caían en «con
  margen», el reloj decía siempre «sin plazo» y el número salía en blanco.
- La pantalla de **inteligencia** pintaba «lo que suma» y «lo que resta» desde
  `salud.detalle`, que el servidor nunca envía. Los dos paneles salían vacíos,
  con sus rótulos puestos, en la pantalla que existe para explicar la
  puntuación. Y no era un olvido del servidor: la salud se calcula en
  inteligencia y en `party` vive una **copia** que guarda lo justo a propósito,
  porque una copia con retraso que dispara acciones manda correos de retención a
  quien renovó ayer. La pantalla enseña ahora lo que hay y dice dónde está el
  detalle.

**Lo que no sirve, medido antes de construirlo.** Un barrido que compruebe si el
nombre del campo existe «en algún sitio» del backend no caza nada: `vence_at`,
`numero`, `cola` y `escalado` aparecen los cuatro en el producto, y los cuatro
dentro del mismo servicio. Tiene que ser por endpoint, y resolver «ruta →
función → claves que devuelve» atravesando las delegaciones es un proyecto
aparte.

**Lo que sí protege** son pruebas por contrato: recorrer el endpoint por HTTP y
afirmar campo a campo lo que sale, serialización incluida. Hay cinco, las de las
pantallas que más duelen. Y un trinquete de suelo que vigila que ninguna
pantalla le pida una forma a una ruta que **nadie** toca.

> **Ese trinquete nació mintiendo.** Su primera medición dijo «0 de 23
> sin recorrer», y era falso: el barrido lee los ficheros de prueba buscando
> rutas, y se leía **a sí mismo** — su propia lista, al nombrar las rutas, las
> daba por recorridas. Se justificaba solo. Excluyéndose, la cifra real es 11
> de 23.

### El guard de tenant se quedaba con los modelos de ayer

El aislamiento entre clientes tiene dos capas: la RLS de Postgres y un guard del
ORM que inyecta `tenant_id` en cada consulta. El guard descubre **una sola vez**
qué modelos llevan `tenant_id`, y su propio código avisaba de la consecuencia:
«un modelo que se mapeara perezosamente DESPUÉS del primer SELECT quedaría fuera
del filtro para siempre, y sería una red silenciosamente incompleta».

No era una hipótesis. Medido el 26-10-2026: el barrido de aislamiento denunciaba
que `DELETE /api/v1/casos/{id}` devolvía **204 sobre el registro de otro
tenant**, y lo mismo en segmentos, conexiones, objetos de metadatos, sesiones y
una docena más. Eran modelos mapeados al importar su servicio, después de que el
guard se diera por descubierto: el primero que arrancaba quedaba cubierto y los
demás no.

En producción cada proceso importa su servicio antes de instalar el guard, así
que el caso es más difícil de alcanzar — pero no imposible: basta un módulo de
modelos que se importe en caliente. Y lo que estaría en juego es una fuga entre
clientes.

**El arreglo** es que el guard se entere: se engancha a `after_configured`, el
aviso que SQLAlchemy lanza al terminar de configurar mapeadores, y **olvida** lo
descubierto. El siguiente SELECT lo rehace. Se olvida en vez de recalcular
porque recalcular dentro de ese escuchador dispararía el descubrimiento en mitad
de la configuración, que es justo cuando la lista está a medias.

Lo vigila `test_el_guard_no_se_queda_con_los_modelos_de_ayer.py`, que mapea un
modelo nuevo a propósito y comprueba que entra solo. La prueba directa es la que
manda: el barrido de aislamiento también lo detecta, pero sólo según qué corra
antes, y un detector que depende del orden no es un guardián.

### «Todo o nada» sólo lo cumplía media aplicación

Una petición compuesta —varias operaciones en una llamada— promete una cosa: o
está todo o no está nada. El mecanismo lleva tiempo escrito y es correcto: el
router abre **una** sesión, la marca como compartida (`compartir_sesion`) y cada
sub-petición la reutiliza; si algo falla, un solo `rollback()` deshace el
conjunto.

Pero sólo **una de las dos puertas** lo miraba. `get_db` sí; `get_uow` —la que
usan las escrituras que emiten eventos, o sea casi todas— abría su propia
sesión y la **confirmaba** al acabar su sub-petición. Lo escrito por las
operaciones anteriores quedaba confirmado de verdad antes de que fallara la
siguiente, y el `rollback()` del conjunto ya no lo tocaba.

Quien mandaba «crea la cuenta y luego el contacto» y fallaba en el contacto se
quedaba con la cuenta creada **y** un error diciendo que se había deshecho todo.
Peor que no tener la función: hay que limpiar a mano lo que el sistema dice que
ya está limpio.

Nadie lo vio porque **la promesa no tenía prueba**. Había pruebas de las
referencias entre operaciones, del tope, de la petición vacía y de las redes de
origen; ninguna de lo único que hace falta que sea cierto. Ahora la hay, por
HTTP y con mutación: `test_la_peticion_compuesta_es_todo_o_nada.py`.

### El arnés devolvía al pool una conexión envenenada

Durante semanas la suite entera daba **doce fallos** repartidos por el portal de
partner, SAML, los barridos de aislamiento y las rutas sin autenticar. Once de
los doce eran inocentes.

El mecanismo, medido el 26-10-2026 con una sonda sobre la conexión:
`ROLLBACK TO SAVEPOINT x` **no borra x** —lo deja establecido— y SQLAlchemy no
lo suelta nunca después de deshacerlo, ni con `rollback()` ni con `close()`. En
producción da igual, porque la conexión muere con la petición. Pero el arnés ata
**todas** las sesiones a una sola conexión para que la prueba pueda deshacerlo
todo, así que cada petición que acaba en error deja su savepoint vivo. El
barrido de aislamiento, que recorre unas 2.400 rutas, llegaba a pilas de más de
cincuenta.

Y una pila profunda es una trampa, porque **soltar un savepoint destruye todos
los posteriores**. Basta con que una sesión de fuera confirme mientras otra de
dentro sigue abierta:

```
SAVEPOINT 54        ← sesión de fuera
SAVEPOINT 55        ← sesión anidada
RELEASE 54          ← la de fuera confirma: destruye la 55
ROLLBACK TO 55      ← la de dentro se deshace → «savepoint does not exist»
```

A partir de ahí la conexión queda inservible —`Can't reconnect until invalid
savepoint transaction is rolled back`— y, como `close()` la devolvía al pool, se
la llevaba la prueba siguiente, y la siguiente. De ahí los once inocentes.

**Lo que se arregla:** la conexión de cada prueba se `invalidate()` en vez de
devolverse, así que el veneno no viaja; y los barridos de fondo del núcleo se
pueden apagar por configuración (`TAREAS_FONDO_ENABLED`), igual que el relevo
del outbox, para que no abran sesiones en medio de un recorrido de 2.400
peticiones. Ese interruptor también sirve en producción: las tres tablas que
barren son comunes, y catorce servicios barriendo las mismas filas es el mismo
trabajo repetido trece veces.

**Lo que NO se arregla, y queda dicho:** el barrido de aislamiento sigue siendo
inestable de vez en cuando —de cero a un fallo por pasada— por la misma razón de
fondo: simular N transacciones independientes sobre una conexión no se puede
hacer del todo. Se probaron tres salidas y las tres se midieron y se
descartaron: soltar el savepoint tras deshacerlo rompe la contabilidad de
SQLAlchemy (14 fallos y 69 errores), envolver cada vuelta en un savepoint propio
empeora el solape, y compartir la sesión del arnés desactiva la RLS —es de
sistema y sin tenant— y el barrido empieza a ver fugas que no existen.

### La paleta de gráficas no se elige a ojo

Cinco series, en orden fijo y **nunca cicladas**: el color sigue a la entidad,
así que la serie 3 es la serie 3 aunque un filtro deje de enseñar la 1. Si el
color saliera del orden de llegada, filtrar repintaría lo que queda y lo que
alguien recordaba en azul aparecería en teal.

Los valores salen de **validar la paleta con el comprobador del método** —banda
de luminosidad, suelo de croma, separación bajo daltonismo, suelo de visión
normal y contraste contra la superficie— en los dos temas. El oscuro lleva pasos
propios y no es un volteo del claro: medido, con los valores del claro el
magenta se quedaba en 2,88:1 contra el panel oscuro.

**Verde, ámbar y rojo no se usan como serie.** Están reservados para el estado
—ganada, en riesgo, perdida— y en un CRM eso no es un matiz: una serie pintada
de rojo se lee como un problema aunque sea «Cataluña».

Queda un aviso conocido y aceptado: magenta y teal se separan ΔE 6,6 bajo
deuteranopía, dentro de la banda 6–8 que el método admite **sólo con
codificación secundaria**. Por eso, y no por gusto, la leyenda no es opcional con
dos o más series, los tramos apilados van separados por 2px de superficie y el
embudo lleva su valor al lado. Quitar cualquiera de las tres invalida la paleta.
Lo vigila `src/pruebas/graficas.test.ts`, que mide el contraste de los diez
tokens contra su superficie y comprueba que ningún tono de estado se cuele.

A partir de la sexta serie **no se genera un tono**: la cola se pliega en
«otras N». Un sexto color generado es indistinguible de otro bajo daltonismo y
rompe todas las comprobaciones a la vez.

> **Dos fallos que sólo aparecieron al mirar el dibujo**, y que ningún
> validador de color caza: un área de tres series mezclaba los rellenos en un
> barro —ahora el área es sólo para una serie y con más se degrada a líneas— y
> el embudo traía un eje de valor de 0 a 1,5 k que no medía nada de lo que se
> veía, con los nombres de etapa en el eje de abajo, donde «Contactado» caía
> bajo la barra de «Ganada». Por eso el procedimiento termina en «renderízalo y
> míralo» y no en «el validador dice que pasa».

### Un hecho se nombra de dos formas y las dos valen

Un evento se puede emitir con su cadena —`uow.emitir("tenant.alta_confirmada",
…)`— o con la constante que lo declara en el catálogo —`uow.emitir(
ALTA_CONFIRMADA, …)`—. **La segunda es la buena**: ata la emisión a su
declaración, no se escribe mal y es lo que hace que un recorrido de «declarado y
sin emisor» dé el arreglo por bueno.

Y hasta el 12-10-2026 **sólo funcionaba la primera**, de dos maneras a la vez:

- al volcar el evento, la constante llegaba entera a una columna de texto y
  reventaba —`expected str instance, TipoEvento found`—. La transacción del
  cambio se deshacía con ella: en el alta autoservicio, eso es la empresa que no
  se crea con la persona delante de la pantalla;
- y antes de reventar, la comprobación de contrato buscaba el tipo en un
  registro indexado por cadena, no lo encontraba y devolvía «no falta ningún
  campo». **El contrato dejaba de comprobarse justo en las emisiones escritas de
  la forma más cuidadosa.**

Lo mismo pasaba al suscribirse: `identity` escucha el alta con la constante, así
que comparaba un objeto contra una cadena y no le llegaba nada — la empresa se
creaba sin su primer administrador.

Ahora se normaliza **en la puerta** (`crmcore.events.catalogo.clave`), en los dos
sitios por los que entra un tipo: `UnidadDeTrabajo.emitir` y la suscripción del
arranque. En la puerta y no en cada sitio porque los sitios son catorce, y
«funciona donde alguien se acordó» no es una garantía.

> **Lo que lo tapó durante meses merece leerse aparte.** Las pruebas de los
> cuatro sitios comprobaban `uow._pendientes` —la lista en memoria, donde el
> objeto entra y sale igual— y construían el sobre del consumidor con la misma
> constante. Las dos mitades hablaban un idioma que no existe fuera de la
> prueba, y las dos daban verde. Ahora se comprueba la **fila escrita en la
> tabla de salida**, que es lo único que el relevo puede publicar.

El generador de este manual estaba ciego del mismo ojo: `scripts/gen_procesos.py`
sólo entendía cadenas literales, así que los cuatro sitios salían en el mapa de
eventos como «un proceso de fondo» —es decir, «no lo dispara ninguna operación»—.
El alta autoservicio aparecía documentada sin la llamada que la provoca.

## Las preguntas de verificación, respondidas

El catálogo funcional trae un anexo de preguntas para distinguir un CRM
genuinamente headless y multi-tenant de uno que solo lo declara. Aquí van
respondidas sobre este sistema, con dónde mirar.

**¿Existe alguna función que no pueda ejecutarse por API?**
No, y no puede haberla: no hay interfaz todavía, y el gate
`tests/unit/test_headless_contract.py` exige que toda ruta esté documentada y
que ninguna operación de escritura declare solo el camino feliz. Cuando llegue
la interfaz, el gate que hará falta —comparar lo que llama la UI con las rutas
públicas— está anotado como pendiente de la fase 1.

**¿La UI consume las mismas APIs públicas o endpoints privilegiados?**
Consumirá las mismas. Los servicios solo aceptan identidad propagada y firmada
por el gateway, o un token propio; no hay una vía privilegiada distinta.

**¿Cómo se propaga y se fuerza el `tenant_id`? ¿Hay RLS o solo filtrado en la
aplicación?**
Hay RLS en el motor, con `FORCE`, `USING` y `WITH CHECK`. El código está en
`crmcore/db/rls.py` y lo usan **el despliegue y la prueba**, así que lo que se
prueba es lo que se despliega. Se verifica con un rol sin privilegios en
`tests/integration/test_rls_aislamiento.py`: con superusuario, una prueba de RLS
pasa siempre y no demuestra nada.

**¿Qué pasa si un tenant importa diez millones de registros?**
El rate limiting y las cuotas lo cortan antes de tocar la base. El bus reparte
por *subject* de tenant, así que su avalancha no bloquea la entrega de los demás.
Lo que **falta** y está dicho: bulkheads y colas de prioridad por tier
(CRM-00.01.06.03), que están configurados pero no implementados.

**¿Las automatizaciones y workflows son reanudables tras una caída?**
Sí. El estado del proceso se vuelca en la base **en cada paso**, con el paso
siguiente. Si el worker muere, otro toma la instancia —con `FOR UPDATE SKIP
LOCKED` y bloqueo con caducidad— y sigue donde estaba. Hay una prueba que lo
comprueba usando un motor distinto, que es lo que de verdad pasa: no comparte
nada en memoria, solo lo que hay en la base.

**¿Cómo se compensa un proceso multi-servicio que falla a mitad?**
Con compensaciones declaradas por paso, ejecutadas en orden inverso. La prueba
`test_saga_compensa_en_orden_inverso` reproduce justo el caso del catálogo:
pedido creado en el CRM y rechazado en el ERP. Si una compensación falla, se
sigue con las demás y la instancia queda `fallida` con el detalle: parar en la
primera dejaría los pasos anteriores sin deshacer.

**¿La validación está disponible antes de enviar?**
Sí: `POST /metadata/objetos/{objeto}/validar` ejecuta **el mismo código** que al
guardar. Dos implementaciones acabarían divergiendo, y el cliente recibiría un
«válido» seguido de un error.

**¿Los webhooks garantizan orden, deduplicación y replay?**
Orden **por entidad** (el *subject* lleva tenant y tipo), no global.
Deduplicación por `dedup_key`, que deriva del hecho y no de la publicación.
Replay por ventana de tiempo desde el archivo de eventos. La entrega es
at-least-once y está dicho en el manual del integrador: deduplicar es su parte
del contrato.

**¿Se pueden desplegar cambios de configuración desde Git con revisión y
rollback?**
Parcialmente, y se dice: la configuración de entorno sí (es un fichero), y los
ajustes en caliente quedan versionados en la auditoría. La configuración como
código con promoción entre entornos (CRM-07.02.01.03 y .04) está **pendiente**.

**¿La exportación incluye metadatos, configuración, adjuntos e histórico?**
**Pendiente** (CRM-00.01.03.05). Hoy se exporta por API recurso a recurso; el
paquete de offboarding verificable no está.

**¿Los modelos de IA se entrenan con datos del tenant?**
No hay IA todavía (fase 5). El compromiso está en el catálogo como
CRM-05.02.02.09 y la arquitectura lo permite: la inferencia por región y el
modelo por tenant son ajustes, no ramas de código.

**¿El coste escala por usuario, por llamada, por registro o por evento?**
La medición está: `crm_*` en Prometheus y la tabla de consumo por tenant y
periodo, exportable. Qué se factura es una decisión comercial, no técnica.

## Mapa del código

```
packages/crmcore/crmcore/     lo transversal; ningún servicio puede saltárselo
  config.py, config_parts/    122 ajustes, uno por concepto, con su porqué
  tenancy/                    contexto, resolución, guard ORM
  db/                         sesión con RLS, base declarativa, unidad de trabajo
  bus/                        transporte (NATS/Redis/memoria) + outbox + inbox
  events/                     sobre de evento y catálogo con AsyncAPI
  http/                       middleware ASGI, Problem Details, cursor, ETag…
  authz/                      principal, RBAC, ABAC explicable
  audit/                      cadena de hash e historial de campo
  security/                   cifrado de campo con separación por propósito
  runtime/                    ajustes en caliente con jerarquía de ámbitos
  obs/                        métricas con tope de cardinalidad
  service.py                  la factoría: la única forma de crear un servicio

services/<nombre>/            un servicio: modelos, lógica, api, main
alembic/versions/<servicio>/  una cadena de migraciones por servicio
deploy/                       roles y esquemas, RLS, imagen, entrypoint
scripts/                      migrar, RLS, gates, generadores de documentación
tests/unit/                   contratos de arquitectura, motor, trazabilidad
tests/integration/            aislamiento real contra Postgres
```

## Convenciones

- **Código en inglés, comentarios y documentación en castellano.** Es la
  convención de la casa (`contecmind`, `contecweb`, `contecflow-PSA`).
- **Un comentario explica por qué, no qué.** Si dice lo que ya dice el código,
  sobra; si explica una decisión, una medición o un fallo que se evitó, se queda.
- **Cero valores a fuego.** Todo umbral es un campo de `Settings` con rango y con
  el porqué de su valor por defecto.
- **Todo error de dominio lleva `error_code`.** Hay un gate que lo exige: sin él,
  el cliente solo tiene el texto en castellano para distinguir un error de otro.
- **Nada se declara hecho sin prueba y sin manual.** Lo comprueba el gate de
  trazabilidad del catálogo.
- **Una tabla que publican todos los servicios se declara en un solo sitio.** En
  `alembic/env.py`, en la lista de modelos comunes — nunca en el módulo de
  modelos de cada servicio, que es pedir que el siguiente se acuerde. Ha fallado
  cuatro veces, siempre igual y siempre con el mismo síntoma: la tabla existía en
  unos esquemas y no en otros, y en los que no, una pantalla cualquiera daba 500
  con «relation … does not exist». Pasó con las políticas de campo (cinco
  esquemas de trece), con las políticas ABAC (nueve de trece) y con la papelera
  (seis de trece, siete pantallas rotas). El gate de migraciones lo caza en
  cuanto el modelo está en la lista, y no lo caza si no está: por eso la regla es
  dónde se declara, no acordarse de migrar.

- **«Está cargado» no es «es mío».** El registro de objetos
  (`crmcore.metamodelo`) es del **proceso**, y en producción cada servicio es un
  proceso, así que durante mucho tiempo las dos preguntas dieron lo mismo. En la
  suite caben los catorce dentro, y entonces el registro es la unión de todos:
  quien pregunte «¿guardo yo este objeto?» mirando si la clase está cargada
  recibe que sí para todos. Lo pagaban dos sitios —la cola del móvil planificaba
  aplicar una oportunidad de `sales` contra los registros de `party`, y el cuadre
  del rastro comparaba lo vivo de un servicio contra los hechos de otro, que da
  diferencia en cada campo y en esa ruta significa «alguien escribió a mano»—. La
  pregunta correcta es `es_de_este_servicio(objeto, servicio)`, que mira el dueño;
  el dueño se deriva del módulo donde está escrito el modelo y no se pide como
  parámetro, porque un parámetro más son ciento y pico sitios que ponerlo bien y
  el que se olvide se queda con el dueño en blanco, que es justo el valor que lo
  hace pasar por propio. Lo escondía la prueba: pasaba **por orden de carga**, y
  salía verde sin haber recorrido nunca la rama que decía cubrir.
- **`now()` de Postgres es la hora de inicio de la TRANSACCIÓN.** No la del
  momento, así que varias filas escritas en la misma llevan la marca idéntica.
  Un `ORDER BY` sobre esa columna empata, y el empate lo resuelve la colocación
  física de las filas — que depende de lo que haya en la tabla. Un orden que
  acierta con la tabla vacía y falla con la tabla llena. Pasó con el histórico
  de ajustes: un lote de cambios de plataforma salía **al revés** y deshacer
  revertía el cambio equivocado. **Todo orden que importe lleva detrás una
  columna única**; el `id` vale, que es un UUIDv7 y ordena por tiempo.
- **El verbo de un permiso decide quién lo alcanza por comodín.** El vocabulario
  está mezclado —461 rutas exigen `:read` y diez dicen `:leer` o `:consultar`—
  y dos roles de serie se apoyan en comodines: `solo_lectura` lleva `*:read` y
  dice de sí mismo «consulta todo». No lo consultaba: se quedaba fuera de
  `cumplimiento:leer`, que es justo lo que un auditor viene a mirar. Los
  permisos **no se renombran** —un tenant puede tener roles propios que los
  citen, y cambiarlos le quitaría accesos sin avisar—: lo que se hace es que los
  comodines cubran el vocabulario entero y que el vocabulario sea **cerrado**,
  con un guardián que clasifica cada verbo como lectura, escritura o
  privilegiado. Un verbo nuevo entra por ahí o no entra.
- **Un rol que concede un permiso que nadie exige engaña a quien lo lee.** El
  catálogo de roles es la promesa que lee quien administra: si un rol dice
  «gestiona derechos de servicio» y ninguna ruta exige ese permiso, el
  administrador que lo asigne cree haber separado una responsabilidad que sigue
  abierta. Hay guardián, y de los 53 permisos concedidos encontró 6 así — uno de
  ellos un agujero de privilegios de verdad.
- **Una prueba le pregunta el día al producto, no a la máquina.** `date.today()`
  en una prueba compara dos relojes —el de quien ejecuta y el del cliente, que es
  el que mira el producto—, y coinciden casi siempre: dejan de coincidir entre
  medianoche y las dos de la mañana en Madrid y durante trece horas en Auckland.
  Entonces fallan pruebas que no tienen nada roto, que es la forma más rápida de
  que alguien empiece a reejecutar la suite hasta que sale verde. Medido el
  07-10-2026 a la 01:24: doce en rojo a la vez, once por esto. Hay guardián.
- **De qué día es un instante no se pregunta al instante.** `momento.date()` lo
  resuelve en la zona que traiga, y lo que vuelve de un `timestamptz` viene en la
  de la conexión — ni UTC ni la del tenant: la del servidor, que es un tercer
  reloj. Un instante es absoluto; de qué día forma parte, no. Pasó con los planes
  de mantenimiento: una revisión completada reprogramaba la siguiente un día
  corrido.
- **Un cálculo relativo recibe el día, no lo busca.** `hace_menos_de_dias` y los
  demás operadores temporales de los segmentos y de la puntuación reciben el día
  del cliente (`crmcore.fechas.hoy(db)`). No tienen valor por defecto a propósito:
  caer al día de UTC acierta casi siempre y falla en el borde —las 00:30 en
  Madrid son todavía ayer en UTC—, que es exactamente donde se decide si alguien
  entra en el segmento. Hay guardián en
  `tests/unit/test_hoy_es_el_del_cliente_en_todas_partes.py`, con la lista cerrada
  de las que todavía caen a UTC y por qué.

## Lo que sabemos que falta

No está escondido: las 15 capacidades a medias están listadas con su detalle al
final del [Manual III](manual-3-funcionalidades.md), y el estado completo de las
560 en [el catálogo](catalogo/estado.md). Lo más relevante para quien evalúe hoy:

- **Idempotencia y ETag** están implementados como módulo y **no enganchados**
  ruta por ruta.
- **Trazas OpenTelemetry**: el contexto se propaga, falta el exportador.
- **Bulkheads y colas por tier**: configurados, no implementados.
- **Copias de seguridad y recuperación**: documentadas como procedimiento, sin
  automatización propia.

## Lo que está en la tabla, o sale por la API o dice por qué no

El front se construye del contrato. Una columna que no está en el esquema de
lectura **no existe** para ninguna pantalla, por mucho que esté en la base —y
no falla nada: la pantalla se ve bien, sólo que incompleta, y nadie echa de
menos un campo que nunca ha visto.

Medido el 27-10-2026 sobre los trece servicios: **136 columnas en 32 esquemas
de lectura** no salían. Lo que se perdía no eran rarezas — una actividad
llegaba sin hora de inicio ni de fin, un lead sin su campaña ni su primer
toque, una oportunidad sin el competidor que la ganó, un consentimiento sin el
texto que se aceptó y un adjunto sin decir si el antivirus lo había mirado.

Se expusieron 114. Las 22 que quedan **no salen a propósito**, y la lista es de
excepciones con su motivo, nunca de las que sí:

- **Secretos**: el hash de la contraseña, el secreto de MFA y sus códigos de
  recuperación, y el secreto con el que se firman las entregas de un webhook.
  Si salieran, cualquiera con permiso de lectura se llevaría la credencial, y
  una credencial que se ha leído sólo deja de ser peligrosa revocándola.
- **Rutas internas de almacenamiento**: fuera se da un enlace firmado de vida
  corta, no la ruta del bucket.
- **El identificador del padre** cuando el recurso se pide por él y ya viene en
  la ruta.
- **Lo que es de dentro**: la unidad de negocio del reparto interno, el puntero
  a la ficha superviviente de una fusión, el coste con el que negociamos.

La comprobación vive dentro del gate que ya construye los catorce contratos, así
que no cuesta un segundo más, y está validada quitando un campo del esquema de
salida: sin él, falla nombrándolo.
