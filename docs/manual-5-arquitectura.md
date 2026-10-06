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
