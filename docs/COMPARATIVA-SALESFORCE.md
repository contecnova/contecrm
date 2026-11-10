# contecrm frente a Salesforce

> **Para quién es esto.** Para quien decide una compra o la estrategia del
> producto. No es material de venta: aquí está también lo que no tenemos, y
> está delante, no al final.
>
> **Fecha de todo lo medido: 10-11-2026**, sobre el commit `9666d42`. La
> versión anterior era del 05-11-2026; desde entonces hay 56 commits.

## En cinco líneas

1. **En profundidad funcional del núcleo CRM estamos a la altura** de Sales y
   Service Cloud en sus ediciones altas, y **por delante en aislamiento,
   residencia, control interno (GRC, segregación, TCSEC, revisión de accesos)
   y motor de procesos**. Eso está medido y se puede enseñar.
2. **En usabilidad de las doce tareas diarias, igual o menos pasos en las
   doce**, pero la cifra de Salesforce es una estimación, no una medida.
3. **Donde nos ganan, nos ganan por mucho y no es funcionalidad:** ecosistema
   (miles de aplicaciones y de integradores), rodaje en producción,
   certificaciones (ISO 27001, SOC 2, ENS Alto, FedRAMP High) y apps móviles
   nativas. Nada de eso se arregla escribiendo código.
4. **Nuestra cifra más honesta no es «785 de 788 hechas»**: es «398 de 785
   con comprobación registrada» y «el bus de eventos funciona en vivo desde
   hoy». El producto está completo en catálogo y es joven en uso.
5. **Para superarlo en una venta real** hace falta, por este orden: un primer
   cliente en producción con referencia, una certificación (ENS o ISO 27001),
   apps móviles y el complemento de correo, y desbloquear la mitad documental
   (contecmind).

## Qué está medido y qué no

No es simétrico y hay que saberlo antes de leer nada:

- **Lo nuestro está medido** sobre el repositorio y la pila local, con fecha.
  Cada cifra dice cómo se cuenta y casi todas salen de un guion que se puede
  volver a pasar:

      .venv/bin/python scripts/medir_comparativa.py          # catálogo, pruebas, pantallas, vistos, API sellada
      .venv/bin/python scripts/medir_comparativa.py --api    # además, la API que publican hoy los 14 servicios

- **Lo de Salesforce no está medido.** Sale de sus páginas públicas de precios
  y de cumplimiento, consultadas el 10-11-2026 (fuentes al final), y de lo que
  se sabe del producto. No hay una instancia de Salesforce contra la que
  comparar. Donde pone «Salesforce tiene X» hay que leer «según su
  documentación pública, Salesforce tiene X»; donde no lo he podido
  comprobar en una fuente, lo digo.
- **La edición importa.** La mitad de lo que se le atribuye a Salesforce está
  sólo en las ediciones caras o se paga aparte. Lo señalo en cada área.
- **El catálogo es nuestro.** Las 788 capacidades son nuestra lista de lo que
  un CRM empresarial debe tener, no una lista de Salesforce. «Hecho» quiere
  decir que cumple el enunciado de esa lista, tiene una prueba o un sitio del
  código que lo cita y está en el manual. No quiere decir paridad con un
  producto concreto.

## Lo nuestro, en números (10-11-2026)

| | cifra | cómo se cuenta |
|---|--:|---|
| Capacidades del catálogo | **788** | entradas con `id` y `estado` en `docs/catalogo/catalogo.yaml` |
| — hechas | **785** | `estado: hecho` (C 310, A 429, D 44; hay 2 marcadas `B`, criticidad que el catálogo no define) |
| — en curso | **3** | las dos apps móviles nativas y el complemento de Outlook/Gmail (detalle abajo) |
| Hechas **con pantalla** | **679 de 680** | la regla de `tests/unit/test_cada_capacidad_tiene_pantalla.py`: el identificador aparece en un fichero del front que no es de pruebas. Fuera del recuento, 85 con motivo escrito de por qué no tienen pantalla (protocolos, garantías del servidor) y 20 cuyo entregable es el manual. La que falta: `CRM-00.04.04.06`, conectores de proveedor dentro del módulo |
| Hechas **con prueba que las nombra** | **686 de 785** (87 %) | el identificador, como `CRM-00.01.02.03` o `crm_00_01_02_03`, en un fichero de pruebas (509 leídos: `tests/**/*.py` y las pruebas del front). Las otras 99 están citadas en el código, que el gate de trazabilidad admite, pero ninguna prueba las nombra |
| Hechas **con comprobación registrada** (`visto`) | **398 de 785** (51 %) | campo `visto` del catálogo: alguien la recorrió y escribió qué vio. De ellas, 63 auditadas con mutación (`AUDITADO`) y 57 que dicen expresamente «en el navegador» |
| — comprobadas desde el 05-11 | **129** | la fecha más reciente del `visto` es del 05-11 o posterior |
| Operaciones de API publicadas hoy | **3.018** | método HTTP sobre ruta, de `app.openapi()` de los 14 servicios (`--api`) |
| — protegidas por el sello | **2.409** | `docs/contrato-publicado.json`, sellado el 09-11: un gate impide que desaparezca ninguna sin decirlo. Las 609 nuevas aún no están selladas |
| Pantallas | **91 rutas · 88 páginas** | `path="` en `frontend/src/App.tsx` y componentes de `frontend/src/paginas/` (sin pruebas). No es comparable con las 62 del 05-11, que contaban destinos del barrido |

**Cómo leer estas cifras.** La de pantalla dice que cada capacidad tiene una
pantalla que *dice* enseñarla; la de prueba, que una prueba la nombra; la de
`visto`, que alguien la ha recorrido. Son tres niveles de confianza distintos
y el honesto es el último: **la mitad del catálogo tiene una comprobación
escrita; la otra mitad, prueba y pantalla pero nadie ha anotado haberla
recorrido**. El 09-11 se encontraron 63 capacidades que constaban hechas y
simulaban; se construyeron de verdad en dos tandas el mismo día (63 → 33 → 2).
Es buena señal que se encontraran y es la razón para no fiarse de «hecho»
sin `visto`.

Por módulo:

| Módulo | hechas | con prueba que las nombra | con `visto` |
|---|--:|--:|--:|
| 0 Plataforma y arquitectura | 287 | 268 | 159 |
| 1 Datos de cliente (360) | 54 | 42 | 22 |
| 2 Marketing | 54 | 48 | 24 |
| 3 Ventas | 70 | 59 | 24 |
| 4 Servicio | 61 | 53 | 22 |
| 5 Analítica e IA | 57 | 47 | 32 |
| 6 Productividad y colaboración | 56 | 55 | 34 |
| 7 Administración, ALM y gobierno | 114 | 88 | 67 |
| 8 Requisitos no funcionales | 12 | 6 | 1 |
| 9 Proveedores, coste y capacidad | 20 | 20 | 13 |

Lo que más se vende —ventas, servicio, marketing— es lo que **menos
comprobación registrada tiene** (34 %, 36 %, 44 %). Lo más comprobado es
plataforma y gobierno. Es un riesgo de demo, no de arquitectura.

### Las doce tareas del día (manual técnico 4.6.71)

Doce tareas de comercial, soporte y responsable, hechas por la interfaz desde
la portada con Playwright (`node frontend/scripts/medir-tareas.mjs`), con la
tarea comprobada por la API al acabar.

| | antes (05-11) | ahora (10-11) | Salesforce |
|---|---|---|---|
| Tareas que se terminan | 7 de 12 | **12 de 12** | — |
| Bloqueos | 5 | **0** | — |
| Errores de API | 1 | **0** | — |
| Acciones (clics + Intro) en las doce | — | **45** | **67, estimado** |

Tarea a tarea, contando el Intro como acción: **menos acciones en 7**
(oportunidad 4 frente a 7; presupuesto y enviarlo 7 frente a 14; caso con
prioridad 4 frente a 10; aprobar desde la portada 1 frente a 3…), **las
mismas en 5** y **más en ninguna**.

**Lo que esto no dice.** La columna de Salesforce son clics de Lightning con la
configuración de serie y el camino más corto conocido, **estimados, no
medidos**. Una instalación de Salesforce bien configurada (acciones rápidas,
layouts dinámicos) puede bajar bastante. Lo defendible es: *en las doce
tareas, no exigimos más pasos que Salesforce de serie, y en la mitad menos*.
No es defendible decir «somos el doble de rápidos».

### La IA, evaluada contra el modelo real

`services/intelligence/evaluacion.py`, pantalla Administrar › Gobierno y
cumplimiento › Evaluación de la IA.

- **Banco de 50 casos de 10 funciones** (asistente con conocimiento, preguntas
  sobre los datos, resúmenes de caso y de conversación, extracción,
  compromisos de reunión, variantes de texto, clasificación, acciones del
  asistente, plan de un agente), pasados por el mismo camino que la función
  real.
- **Acierto medido el 10-11-2026 con `gemini-2.5-flash`: 88 % (44/50) antes
  de corregir, 98 % (49/50) después.** Criterios comprobables por programa
  siempre que se puede; donde no, un modelo juez, y se marca.
- Se repite programada (cada 168 h de serie) y avisa si una función baja del
  umbral (90 %).

**Lo que esto no dice.** Son **5 casos por función**: un 100 % en una función
es 5 de 5, no una tasa. El banco lo escribimos nosotros, con un solo modelo y
en un solo día. Sirve para detectar que algo se rompe; no sirve como cifra de
marketing frente a Agentforce, que tampoco publica una comparable.

### Aislamiento, residencia y control interno

| | qué hay | evidencia |
|---|---|---|
| **Aislamiento a elegir** | lógico (tenant_id + RLS), por esquema, base dedicada, híbrido por tiers con promoción entre modelos, base del cliente (BYO-DB) y pools de cómputo por tenant | `CRM-00.01.01.01` a `.10`, cinco de las diez con `visto`. `GET /aislamiento/garantias` lo mide en cada carga, en Seguridad |
| **Las tres capas, comprobadas** | 623 tablas con `tenant_id` con RLS, FORCE y política (medido el 28-10); el guard del ORM; y un servicio fuera de `dev` **se niega a arrancar** si conecta con un rol que se salta RLS | `CRM-00.01.02.04`; validado plantando el caso malo |
| **Comprobar que el tenant está donde se declaró** | se pregunta a la conexión a qué base está atada y se contrasta; redeclarar invalida la comprobación | `CRM-00.01.01.03` |
| **Residencia** | región por tenant (UE, EE. UU., LATAM, APAC…), residencia por tipo de dato (transaccional, analítico, copias, registros), subprocesadores y transferencias, y la IA obligada a la misma región | `CRM-00.01.05.01` a `.04` |
| **GRC** | un control de serie por familia del catálogo (34), anclados a sus capacidades, con evidencia automática; **785 de 785 ancladas y 398 de 785 verificadas** en el tenant de plataforma | `CRM-07.03.02.12` |
| **Segregación de funciones** | matriz reglas × roles, simulador antes de asignar, 7 reglas de serie, excepciones con motivo y caducidad; cada conflicto es un hallazgo del GRC (7 abiertos medidos en el tenant de plataforma) | `CRM-07.03.02.06`, `.13` |
| **TCSEC** | 15 requisitos de D a A1: 11 medidos sobre el sistema, 4 atestiguados por una persona con evidencia; lo no medible sale «sin medir», nunca «cumple» | `CRM-07.03.02.11`, `.14` |
| **Revisión de accesos** | campañas con plazo, cada responsable confirma o retira desde su bandeja, **retirar quita el rol en el momento** y cierra sesiones | `CRM-07.03.02.15`, recorrido el 10-11 |

**Lo que esto no dice.** El TCSEC de **la pila local sale nivel D**, porque
en `dev` se conecta como superusuario: el informe lo dice, que es lo correcto,
pero no hay todavía ninguna instalación medida que saque C2. De los 11
requisitos medidos en el tenant de plataforma, 5 efectivos y 6 inefectivos.
Y el control obligatorio por etiquetas no existe, así que **B1 no se alcanza
por diseño** y el producto lo dice. Tener las herramientas de control no es
estar certificado.

## Salesforce: ediciones y precio (10-11-2026)

Lista en dólares, por usuario y mes, facturación anual, según las páginas de
precios de Sales Cloud y Service Cloud consultadas hoy:

| Edición | Precio | Qué añade, según la página |
|---|--:|---|
| Starter Suite | 25 | registros, embudo, reparto de leads, correo |
| Pro Suite | 100 | más personalización y automatización, presupuestos y previsión |
| Core | 195 | Premier Success, Slack Business+, Tableau Next; la IA se compra aparte desde aquí |
| Advanced | 395 | más seguridad, más IA y capacidad de datos, copias y archivado, Security Center, sandbox completo |
| Max | 550 | Agentforce para ventas o servicio, Slack Enterprise+, 2,75 M de Flex Credits al año por organización |

Muchas fuentes siguen citando las ediciones como Professional, Enterprise y
Unlimited; no he comprobado cómo se corresponden con estas.

**Se paga aparte**, según sus páginas o fuentes que las citan:

- **Shield** (cifrado de plataforma, monitorización de eventos, auditoría de
  campos ampliada): porcentaje del gasto neto en Salesforce, en torno al
  **30 %** el paquete; las páginas regionales dan cifras distintas por
  componente (10–30 %).
- **Agentforce**: créditos a 500 $ por 100.000 (≈ 0,10 $ por acción) o 2 $
  por conversación; incluido en Max.
- **Marketing**: Marketing Cloud Next desde 1.500 $ por organización y mes;
  Account Engagement de 1.250 a 15.000 $ por organización y mes, con topes de
  contactos.
- Revenue Cloud (desde 200 $/usuario), Revenue Intelligence (220 $),
  Agentforce para ventas como complemento (125 $), PRM (10 $ por acceso),
  Enhanced Messaging (75 $), y omnicanal, conocimiento, field service y
  centralita «disponibles para compra» sin precio publicado.
- **Residencia en la UE con personal de la UE** (Hyperforce EU Operating
  Zone): sólo un subconjunto de productos; no he encontrado precio publicado.

**Nosotros no tenemos lista de precios publicada.** «Somos más baratos» es
probable con estas cifras, pero hoy no se puede afirmar con un número.

## Área por área

Leyenda: **gana** = nosotros por delante con evidencia; **empate** =
equivalente en lo que se puede comprobar; **pierde** = Salesforce por
delante.

### Ventas — empate en funcionalidad, pierde en rodaje

- **Salesforce**: Sales Cloud desde Pro (embudo, previsión, presupuestos),
  CPQ / Revenue Cloud aparte, Sales Planning y Maps en Max, Revenue
  Intelligence aparte. Veinte años de uso.
- **Nosotros**: 70 capacidades (embudo y metodologías, previsión por
  jerarquía con cascada, territorios, cuotas, comisiones con motor externo,
  cadencias, cotización y contrato, PRM). Presupuesto y contrato en PDF desde
  la ficha, sin un tercero. Comprobación registrada en **24 de 70**.
- **Ganamos** en lo que en Salesforce es un producto aparte: cotización con
  documento propio (allí Revenue Cloud o un tercero tipo Conga) y
  metodologías con criterios marcados en la oportunidad. **Perdemos** en
  CPQ complejo (configurador de producto con reglas de precio): lo nuestro es
  cotización, no un configurador de su nivel. Las tareas T01–T07: igual o
  menos pasos.

### Servicio — empate, con dos huecos

- **Salesforce**: casos, conocimiento, omnicanal, centralita, Field Service
  con su app móvil, mensajería; casi todo en Advanced/Max o aparte.
- **Nosotros**: 61 capacidades (casos con SLA y estados configurables,
  omnicanal, consola del agente, conocimiento con búsqueda semántica,
  portal, field service, devoluciones). Comprobación registrada en **22 de
  61**.
- **Empate** en casos, SLA y conocimiento. **Perdemos** en servicio de
  campo: tenemos el modelo y la sincronización idempotente del técnico, **no
  la app móvil sin conexión** (`CRM-04.04.01.03`, en curso). Y en canales de
  mensajería listos (WhatsApp y similares): lo nuestro va por el conector
  genérico, no hay uno empaquetado medido.

### Marketing — pierde

- **Salesforce**: Marketing Cloud y Account Engagement, productos enteros con
  su propia escala de envío, personalización y analítica, desde 1.250–1.500 $
  por organización y mes.
- **Nosotros**: 54 capacidades (segmentos, recorridos con lienzo, A/B, mejor
  hora, comprobación de spam, transaccional separado, atribución,
  consentimientos). Comprobación registrada en **24 de 54**.
- **Perdemos** en volumen probado de envío, entregabilidad y personalización
  en tiempo real: no hay una medida nuestra de envío masivo. **Ganamos** en
  coste para quien necesita marketing de CRM y no una plataforma de marketing:
  aquí viene dentro.

### Analítica — empate en lo conversacional, pierde en BI

- **Salesforce**: informes y paneles en todas las ediciones; Tableau Next
  desde Core; CRM Analytics y Data Cloud aparte.
- **Nosotros**: 34 capacidades de informes y cuadros, más contecintelligence:
  preguntas en lenguaje natural sobre los datos del CRM, con gráfico y la
  consulta usada. Medido en vivo: «importe por etapa» da las cinco sumas
  exactas de las 146 oportunidades.
- **Empate** en preguntar al dato. **Perdemos** en BI visual a escala: no
  tenemos un Tableau, y dos componentes del cuadro de dirección fallan hoy en
  contecintelligence (detalle abajo).

### IA — pierde en alcance, gana en control

- **Salesforce**: Agentforce (agentes, acciones, Prompt Builder, Einstein
  Trust Layer), incluido en Max o por créditos. Mucho más alcance y mucha más
  inversión.
- **Nosotros**: 23 capacidades (modelos predictivos entrenados, asistente con
  conocimiento y acciones, extracción, transcripción con compromisos,
  variantes de texto, agentes con permisos y presupuesto, guardias, coste por
  uso, región de la IA atada a la del tenant) y **evaluación contra el modelo
  real: 98 % en 50 casos**.
- **Ganamos** en gobierno: banco de evaluación propio del cliente, aviso si
  baja, coste visible, y la IA que no sale de la región firmada. **Perdemos**
  en todo lo demás: amplitud de agentes, acciones listas y madurez. No
  conviene competir en «más IA».

### Plataforma — gana en motor de procesos, pierde en herramientas de desarrollo

- **Salesforce**: Flow (Workflow Rules y Process Builder retirados a final de
  2025), aprobaciones clásicas pasando a Flow Approvals, Apex, objetos
  personalizados, sandboxes por edición.
- **Nosotros**: 59 capacidades de procesos (BPMN 2.0 con saga y
  compensaciones, DMN editable por negocio, migración de instancias en vuelo,
  simulación antes de publicar), aprobaciones con el lienzo como definición,
  quórum, reaprobación al cambiar lo aprobado; 53 de modelo de datos y
  extensión (código del tenant ejecutado de verdad, endpoints propios).
- **Ganamos** en profundidad del motor: migrar instancias en vuelo, simular
  con datos reales, reaprobar cuando sube un descuento ya aprobado y DMN no
  los tiene Salesforce de serie. **Perdemos** en el entorno del
  desarrollador: Apex, su IDE, sus herramientas de despliegue y, sobre todo,
  las personas que ya saben usarlo.

### Seguridad y cumplimiento — gana en producto, pierde en certificación

- **Salesforce**: ISO 27001/27017/27018, SOC 2 Tipo II, **ENS Alto**,
  FedRAMP High (Government Cloud Plus), entre muchas otras; Shield aparte
  (≈ 30 %); residencia UE con Hyperforce para un subconjunto de productos.
  Multi-tenant compartido: no hay base dedicada por cliente.
- **Nosotros**: todo lo de la sección de aislamiento; cifrado con clave del
  cliente, auditoría encadenada, DLP de exportación, segregación, TCSEC y
  revisión de accesos **sin coste aparte**.
- **Ganamos** en lo que el producto hace: aislamiento a elegir con
  comprobación, residencia por tipo de dato y control interno dentro del CRM
  (en Salesforce, segregación y revisión de accesos suelen ser un tercero).
  **Perdemos** en lo que el comprador exige por escrito: **no tenemos
  ninguna certificación**. `CRM-00.01.05.05` («cumplimiento verificable: ENS,
  ISO 27001, SOC 2…») es una capacidad de documentación, no un certificado.
  En banca, sector público o sanidad, eso decide antes que cualquier
  funcionalidad.

### Integración — empate técnico, pierde en conectores listos

- **Salesforce**: APIs REST, SOAP, Bulk y Streaming; MuleSoft aparte;
  cientos de conectores de terceros en AppExchange.
- **Nosotros**: 3.018 operaciones REST con contrato sellado, GraphQL, gRPC,
  webhooks firmados, eventos con entrega al menos una vez, CDC, sandbox de
  API, SDK, conector genérico de API con credenciales y mapeo.
- **Empate** en lo técnico; el contrato sellado es una ventaja real para
  quien integra (no se despierta con un 404). **Perdemos** en conectores
  empaquetados: la capacidad de conectores de proveedor dentro del módulo es
  la única hecha sin pantalla, y el bus de eventos entre servicios funciona en
  vivo **desde el 10-11-2026** (13 conexiones, 156 consumidores medidos).

### Móvil — pierde

- **Salesforce**: app móvil nativa con trabajo sin conexión (Briefcase),
  app de Field Service, notificaciones push.
- **Nosotros**: web adaptada a 390 px (medido: nada se sale en las pantallas
  tocadas), **modo sin conexión en el navegador** con conflictos campo a
  campo (`CRM-06.02.01.04`, visto el 09-11), y el servidor que una app
  necesita (sincronización, conflictos, push). **No hay app de iOS ni de
  Android** (`CRM-06.02.01.03`, en curso) ni complemento de Outlook/Gmail
  (`CRM-06.01.01.02`, en curso).
- **Perdemos** claramente. Para equipos comerciales de calle o técnicos de
  campo es eliminatorio.

### Ecosistema — pierde, y no se compensa con código

- **Salesforce**: AppExchange con **más de 6.000** aplicaciones listadas
  (recuentos de terceros, diciembre de 2025) y más de 7.000 apps y
  consultoras según Salesforce; Trailhead; una industria de integradores y
  administradores certificados; comunidad y referencias en todos los
  sectores.
- **Nosotros**: tres soluciones de la casa (contecmind, contecintelligence y
  las piezas reutilizadas de contecflow-PSA, contecweb y contecpos). Ningún
  partner, ningún mercado de extensiones, ningún profesional certificado
  fuera de casa. **El repositorio no registra ninguna instalación de cliente
  en producción**; si la hay, no está medida aquí.
- **Perdemos** sin matices.

### El marcador

| Área | Resultado | Lo que lo decide |
|---|---|---|
| Ventas | empate | funcionalidad equivalente; documento y cotización en casa; su CPQ complejo y su rodaje |
| Servicio | empate | sin app de campo sin conexión |
| Marketing | pierde | escala de envío sin medir; ellos son un producto entero |
| Analítica | empate / pierde | preguntar al dato sí; BI tipo Tableau no |
| IA | pierde en alcance, gana en control | evaluación propia y región; ellos, Agentforce |
| Plataforma | **gana** en procesos | instancias en vuelo, simulación, reaprobación, DMN |
| Seguridad y cumplimiento | **gana** en producto, **pierde** en certificación | aislamiento a elegir y GRC dentro; cero certificados |
| Integración | empate | contrato sellado frente a conectores listos |
| Móvil | pierde | sin apps nativas |
| Ecosistema | pierde | AppExchange, integradores, referencias |

## Lo que nos falta de verdad para superarlo

Por lo que más pesa en una venta, no por lo que más cuesta construir:

1. **Un cliente en producción que dé la cara.** Sin referencia, ningún
   comité de compra grande pasa de la demo. Ni el aislamiento ni el precio
   lo compensan. No es código.
2. **Una certificación.** ENS (Medio o Alto) para el sector público español,
   ISO 27001 para el privado. Salesforce las tiene todas; nosotros, ninguna.
   Las piezas técnicas (auditoría encadenada, GRC con evidencias, revisión de
   accesos, TCSEC) ya existen y abaratan la auditoría, pero hace falta la
   instalación de producción que se audita, y que saque C2 en su propio
   TCSEC.
3. **Apps móviles y complemento de correo.** Las tres capacidades en curso son
   las tres que un comercial nota el primer día. El servidor está; falta el
   cliente.
4. **Rodaje medido.** Que las 387 capacidades sin `visto` —sobre todo ventas,
   servicio y marketing, entre el 34 % y el 44 % comprobadas— se recorran
   antes de que lo haga un cliente. El 09-11 aparecieron 63 que simulaban.
5. **Desbloquear contecmind**: la mitad documental (aprobación de documentos,
   respuestas citando la página) es una de nuestras ventajas y hoy no se
   puede enseñar.
6. **Conectores empaquetados** para lo que todos piden (correo y calendario de
   Microsoft y Google, firma, ERP más comunes, mensajería) sobre el conector
   genérico, como configuración y no como código por proveedor.
7. **Una lista de precios publicada.** «Coste total menor» es nuestro mejor
   argumento y hoy no tiene una cifra detrás.
8. **El ecosistema**: no se gana. Se sustituye con servicio directo, con el
   contrato de API sellado y con no tener que comprar diez complementos para
   tener lo que aquí viene dentro.

## Qué traer de contecmind y contecintelligence

La decisión de **no absorberlos** está tomada y medida: son productos con su
propio ciclo. Lo que sí hay que hacer es traer las piezas que hacen al CRM más
competitivo. Estado medido en vivo el 10-11-2026 (contecmind sigue sin
responder en `:8200`; su último commit es del 01-11-2026; contecintelligence,
con sus tres contenedores en marcha):

| De dónde | Qué traer | Por qué | Estado | Dónde se ve | Qué falta |
|---|---|---|---|---|---|
| contecmind | Generación de documentos desde plantilla con datos del CRM | Salesforce lo resuelve con un tercero de pago (Conga, DocuSign Gen) | **Funciona, y no depende de contecmind.** El motor es del CRM: plantillas versionadas, marcadores, «qué faltaría», cláusulas bloqueadas y a quién se mandó cada versión. Desde la ficha sale un **PDF** con la marca y el idioma de la plantilla y queda como adjunto del registro. Medido: presupuesto (2 líneas, totales) y contrato generados y descargados (`%PDF`) | Ficha de oportunidad, presupuesto, contrato y cuenta → «Generar documento»; plantillas en Administrar → Entornos y despliegue → Operación | Word no; archivar en el corpus sólo probado con el corpus caído |
| contecmind | Firma y aprobación documental sobre el registro | Cierra oferta → contrato → firma sin salir | **No medible de punta a punta.** La firma es del CRM (sobres, proveedores por configuración, evidencia), pero el único proveedor dado de alta no tiene conexión y hay 0 sobres. La aprobación es de contecmind, que no responde | Ventas → Pendiente de firma; Automatización → Aprobar documentos dice que el gestor no responde | Conectar un proveedor real de firma (configuración); la aprobación, cuando contecmind construya |
| contecmind | Respuestas citando página y párrafo sobre los documentos de una cuenta | «¿Qué dice el contrato de este cliente sobre penalizaciones?» con la cita | **Bloqueado por contecmind.** La búsqueda en el corpus responde 422 «este tenant no tiene organización asignada en el gestor documental» | — | Que contecmind construya; después, mapear la organización y medir |
| contecintelligence | Preguntar en lenguaje natural sobre los datos del CRM | Equivalente a Einstein / Tableau Pulse | **Funciona.** El CRM se registra como fuente desde la pantalla; «importe total por etapa» devuelve las cinco sumas exactas de las 146 oportunidades; las preguntas ambiguas vuelven con opciones; se puede guardar y publicar para todos | Analítica → Preguntas publicadas | En contecintelligence: el filtro sobre una lista compara por igualdad («cuentas de cliente»: 2 donde hay 6) |
| contecintelligence | Cuadros generados desde la pregunta | Baja el coste de que dirección se haga su informe | **Funciona la pregunta → gráfico** (barras, número, línea, tabla, con «Ver como tabla» y la consulta). Las instantáneas programadas corren y se guardan. Convertir la pregunta en informe tiene botón y el informe da las sumas por etapa | Analítica → Preguntas publicadas; instantáneas en Analítica → Embudo, cohortes y actividad | En componente de un cuadro, todavía no. Los dos componentes del «Cuadro de dirección» fallan en contecintelligence («no se puede abrir la copia local de esta fuente»). La hora de la programación es UTC y se pide como local |

**Por qué contecmind sigue sin construir, y por qué no es nuestra decisión.**
Su `requirements.txt` fija `pillow>=13.0.0,<14` **para cerrar 24 CVEs**, y
`fastembed 0.8.x` sólo admite `pillow<13.0` con Python 3.12. Se resuelve en su
repositorio de dos maneras: construir sobre **Python 3.13**, donde
`fastembed` deja de acotar `pillow`, o bajar `pillow` y asumir las CVEs, que es
lo que ellos descartaron. Mientras tanto, lo que no depende de contecmind
funciona: «Archivos», con todos los documentos y el registro del que cuelga
cada uno, y «Pendiente de firma», que distingue «no hay nada en curso» de
«todo firmado».

## Qué haría yo, por orden

1. **Buscar el primer cliente de referencia y la certificación ENS a la
   vez.** Son los dos que más pesan y los dos tardan meses: cuanto antes
   empiecen, antes acaban. La instalación de ese cliente es la que se audita.
2. **Recorrer ventas, servicio y marketing hasta tener `visto` en todo lo que
   se enseña en una demo.** Es lo más barato de cerrar y lo más caro de que lo
   encuentre un cliente.
3. **Construir los tres clientes en curso**: app móvil (con el modo sin
   conexión que ya funciona en el navegador) y complemento de correo.
4. **Publicar una lista de precios** y compararla con la de arriba, con Shield
   y Agentforce sumados.
5. **No competir en ecosistema ni en «más IA».** Competir en aislamiento,
   residencia, control interno, profundidad de proceso, todo incluido y
   precio, que es donde el terreno es nuestro y está medido.

## Fuentes de Salesforce (consultadas el 10-11-2026)

- Precios de Sales Cloud: <https://www.salesforce.com/sales/pricing/>
- Precios de Service Cloud: <https://www.salesforce.com/service/pricing/>
- Shield: <https://www.salesforce.com/editions-pricing/platform/shield>,
  <https://www.salesforce.com/eu/platform/shield/pricing/>,
  <https://upperedge.com/salesforce/salesforce-shield-the-security-add-on-with-significant-cost-implications/>
- Agentforce: <https://www.salesforce.com/in/agentforce/pricing/>,
  <https://www.eesel.ai/blog/salesforce-flex-credits>
- Marketing: <https://www.salesforce.com/in/marketing/marketing-cloud-editions/pricing/>,
  <https://www.salesforce.com/marketing/b2b-automation/pricing/>
- Cumplimiento: <https://compliance.salesforce.com/en/ens>,
  <https://compliance.salesforce.com/en/iso-27001>,
  <https://compliance.salesforce.com/jp/fedramp-high>
- Residencia UE: <https://salesforce.com/eu/products/platform/hyperforce/hyperforce-eu-oz>
- Móvil sin conexión: <https://developer.salesforce.com/docs/atlas.en-us.mobile_offline.meta/dx.htm>
- AppExchange: <https://dev.to/doriansabitov/state-of-agentexchange-semiannual-analysis-52kj>,
  <https://www.salesforce.com/news/stories/salesforce-appexchange-business-builders-stats/>
- Retirada de Workflow Rules y Process Builder:
  <https://www.salesforceben.com/in-loving-memory-end-of-life-for-salesforce-workflow-rules-and-process-builder/>

Varias cifras de precio vienen de fuentes de terceros que citan a Salesforce y
no coinciden entre sí (Shield, Agentforce por usuario). Para un presupuesto
real, manda la oferta de Salesforce, no esta tabla.
