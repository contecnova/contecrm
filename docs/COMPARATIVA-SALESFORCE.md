# Dónde ganamos y dónde nos ganan

> **Para quién es esto.** Para decidir dónde invertir el próximo trimestre: qué
> hueco cuesta caro dejar abierto y qué ventaja conviene defender. No es
> material de venta — aquí se dice también lo que no tenemos.

## Qué está medido y qué no

Esto no es simétrico y conviene saberlo antes de leer nada:

- **Lo nuestro está medido** sobre el código de este repositorio, con la fecha
  al lado. Cada cifra dice cómo se cuenta para que se pueda volver a contar.
- **Lo de Salesforce no.** Sale de conocimiento del producto, no de una
  instalación que yo haya abierto y recorrido. Donde digo «Salesforce tiene X»
  hay que leer «hasta donde sé, Salesforce tiene X». No he comparado versiones
  ni ediciones, y la edición importa: la mitad de lo que se le atribuye está
  sólo en Enterprise o Unlimited, o se paga aparte.

Dicho eso, para decidir sirve igual: lo que decide no es el empate exacto en
una casilla, sino dónde hay un hueco que cuesta caro y dónde hay una ventaja
que no nos pueden copiar barato.

## Lo que tenemos, en números (05-11-2026)

| | contecrm | cómo se cuenta |
|---|--:|---|
| Capacidades de catálogo | **778** | entradas con ID en `docs/catalogo/catalogo.yaml`, todas en estado `hecho` |
| — de ellas, core | 311 | criticidad `C`: sin eso no hay CRM empresarial |
| — avanzadas | 423 | criticidad `A`: diferencial de líderes de mercado |
| — diferenciales | 44 | criticidad `D`: alto valor en sectores concretos |
| Operaciones de API publicadas | **2.452** | método HTTP sobre ruta montada, en los 13 servicios |
| Pantallas | **62** | destinos de navegación que el barrido abre una por una |
| Pestañas de listado | **211** | declaradas en `recursos.ts` |

Y las dos soluciones de la casa que ya están enganchadas:

| | qué es | tamaño medido |
|---|---|---|
| **contecmind** | gestor documental que además contesta citando el párrafo, la página o el segundo de vídeo | 610 operaciones de API, 9.426 pruebas, 69 pantallas (21-10-2026) |
| **contecintelligence** | analítica conversacional sobre fuentes heterogéneas | integrado por API; el CRM se registra como fuente consultable |

## Lo que pediste mirar primero: automatismos, aprobaciones y avisos

Es donde un CRM se gana o se pierde en una evaluación seria, así que va con
detalle. **41 capacidades declaradas**, repartidas así:

### Motor de procesos — 16 capacidades

Modelado visual BPMN 2.0 **y la misma definición como código**, orquestación
con saga y coordinador, coreografía por eventos, compensaciones explícitas por
paso, outbox/inbox transaccional, temporizadores y escalados, subprocesos
reutilizables, tareas humanas con bandeja y SLA, tablas de decisión DMN
editables por negocio, instancias consultables con su punto de fallo, reintento
y edición de variables en caliente, **migración de instancias en vuelo a una
versión nueva**, simulación con datos de ejemplo antes de publicar, aislamiento
por tenant y topes contra procesos desbocados.

### Automatizaciones declarativas — 9 capacidades

Constructor «cuando ocurre X, si Y, entonces Z»; disparadores por creación,
cambio de campo, borrado, evento entrante, webhook y programación; acciones
sobre registro, aviso, llamada externa, lanzar proceso y asignar; ramas, bucles
sobre colecciones y variables; inmediato, diferido y programado; **orden de
ejecución y prevención de bucles infinitos entre reglas**; depurador paso a
paso con log de decisiones por registro; promoción entre entornos; biblioteca
de plantillas por industria.

### Aprobaciones — 16 capacidades

Editor gráfico donde **el lienzo ES la definición** (no un dibujo que luego
alguien traduce), la misma definición como gráfico y como YAML intercambiables
sin pérdida, validación antes de publicar (nodos inalcanzables, ciclos sin
salida), **simulación con datos reales diciendo qué ruta seguiría y quién
aprobaría**, versionado con instancias en vuelo terminando con su versión,
cadena y paralelo con quórum configurable, resolución del aprobador por
jerarquía/importe/unidad/rol, delegación por ausencia sin perder la traza,
escalado por tiempo e inactividad **con aviso antes de escalar**, reaprobación
automática cuando cambia lo aprobado, aprobación automática bajo umbral
**registrada como tal**, decidir desde el correo con enlace firmado de un solo
uso, bandeja unificada, vista de la instancia sobre el propio gráfico, y
analítica del flujo: dónde se atasca y quién es el cuello de botella.

### Avisos — 36 capacidades

Repartidas por todo el producto: consumo con alerta de aproximación al límite,
deprecación proactiva de API, monitor de integraciones con reproceso, aviso
antes de escalar, caducidad de certificados del IdP, y las de negocio.

### Frente a Salesforce, en esta área concreta

| Capacidad | Salesforce | Nosotros | Quién gana |
|---|---|---|---|
| Automatización declarativa | Flow Builder, muy maduro y con enorme base instalada | Constructor X/Y/Z con depurador paso a paso | **Salesforce**, por madurez y ecosistema |
| Modelado de procesos largos | Flow Orchestration (reciente) | BPMN 2.0 + saga + compensaciones | **Nosotros**, en profundidad de motor |
| Instancias en vuelo al cambiar la definición | limitado | migración explícita de instancias en vuelo | **Nosotros** |
| Simulación antes de publicar | limitada | ruta, aprobador y plazos con datos reales | **Nosotros** |
| Aprobaciones | Approval Processes, sólidas pero rígidas | quórum configurable, reaprobación al cambiar lo aprobado, analítica del flujo | **Nosotros** en flexibilidad; Salesforce en rodaje |
| Aprobar desde el correo | sí | sí, con enlace firmado de un solo uso | empate |
| Reglas de decisión para negocio | sin DMN nativo | tablas DMN editables por negocio | **Nosotros** |
| Bots y asistentes | Einstein Bots, Agentforce | asistente propio + contecintelligence | **Salesforce** |

**Lo que de verdad nos hace competitivos aquí no es tener la lista: es que tres
de esas capacidades son las que más duelen cuando faltan** — migrar instancias
en vuelo, simular antes de publicar y reaprobar cuando cambia lo aprobado. Un
descuento aprobado que sube de importe y no vuelve a aprobarse es un agujero de
control interno, y es exactamente la pregunta que hace un auditor.

## Dónde nos gana Salesforce

Sin adornos, porque es lo que hay que saber para venderlo y para decidir:

1. **El ecosistema.** AppExchange, miles de integraciones listas, una industria
   de partners e integradores, y un mercado de profesionales certificados. Esto
   no se compensa con funcionalidad: se compensa con servicio y con precio.
2. **La amplitud de nubes.** CPQ, Field Service, Marketing Cloud, Commerce,
   Tableau, MuleSoft, Slack. Tenemos piezas de varias, no las nubes enteras.
3. **El rodaje.** Veinte años de casos límite resueltos en producción de
   decenas de miles de clientes. Nuestro catálogo está completo y nuestra
   experiencia de campo no.
4. **Móvil y fuera de línea.** Su aplicación móvil con trabajo sin conexión es
   un producto en sí. Nosotros respondemos en el navegador.
5. **IA embebida en todo** (Einstein / Agentforce), entrenada con un volumen de
   datos que no tenemos.
6. **Certificaciones y referencias.** En un comité de compra grande, eso pesa.

## Dónde les ganamos

También sin adornos, y con la evidencia al lado:

1. **Aislamiento de datos a elegir.** Lógico, por esquema, físico por cliente e
   híbrido por tiers **con promoción entre modelos y comprobación de que el
   tenant está donde se declaró** (`CRM-00.01.01.01` a `.04`). Salesforce es
   multi-tenant y punto. Para banca, sanidad o defensa esto decide la venta.
2. **Residencia del dato por tipo de dato**, con subprocesadores declarados y
   transferencias internacionales anotadas (`CRM-00.01.05`).
3. **Contrato de API sellado.** 2.452 operaciones publicadas con un gate que
   impide que desaparezca ninguna. Quien integra no se despierta con un 404.
4. **Profundidad del motor de procesos**, como está arriba.
5. **Precio y coste total.** No es una funcionalidad, es la razón número uno
   por la que alguien escucha una alternativa.
6. **El documental de verdad.** contecmind no es «adjuntar ficheros»: es
   versionado, reserva de edición, auditoría encadenada y respuestas que citan
   la página exacta. Salesforce Files no juega en eso.
7. **Un producto en castellano, con el dominio en castellano.** Los rótulos,
   los errores y el manual están escritos para quien trabaja aquí.
8. **Disciplina de honestidad en la interfaz.** Es raro listarlo como ventaja y
   lo es: no decimos «todo bien» cuando no se ha medido, y cada pantalla
   distingue «no hay nada» de «no he podido preguntar». Quien ha sufrido un
   panel que miente lo valora en la primera demo.

## Qué traer de contecmind y contecintelligence

La decisión de **no absorberlos** está tomada y medida: son productos con su
propio ciclo y su propia base instalada. Lo que sí hay que hacer es traer las
piezas que hacen al CRM más competitivo:

| De dónde | Qué traer | Por qué | Estado, medido en vivo el 10-11-2026 | Dónde se ve | Qué falta |
|---|---|---|---|---|---|
| contecmind | Generación de documentos desde plantilla con datos del CRM | Salesforce lo resuelve con un tercero de pago (Conga, DocuSign Gen). Nosotros lo tenemos en casa. | **A medias, y no depende de contecmind.** El motor es del CRM: plantillas versionadas, marcadores, «qué faltaría», cláusulas bloqueadas y a quién se mandó cada versión. Generado en vivo: la oferta sale con los tres datos y, si falta uno, 409 diciendo cuál. | Administrar → Entornos y despliegue → Operación, pestaña «Plantillas de documento»: «Componer el documento» y «Qué faltaría si se generase ahora» | Los datos **no salen del registro**: hay que escribirlos a mano en el formulario (`objeto`/`objeto_id` sólo se anotan). Falta rellenarlos desde la ficha y un botón en ella; sale texto, no PDF/Word, y archivarlo es del corpus (contecmind). Es construcción de tamaño medio: se avisa antes de hacerla. |
| contecmind | Firma y aprobación documental sobre el registro del CRM | Cierra el ciclo oferta → contrato → firma sin salir | **No medible de punta a punta.** Firma: el módulo es del CRM (sobres, proveedores por configuración, evidencia), pero el único proveedor dado de alta no tiene conexión ni se ha probado nunca, y hay 0 sobres. Aprobación: es de contecmind, que no construye su imagen (no responde en `:8200`) y el tenant no tiene organización en el gestor. No se intentó. | Ventas → Pendiente de firma (sobres y proveedores); Automatización → Aprobar documentos abre diciendo que el gestor no responde en `:8200` y que la empresa no está mapeada (medido) | Conectar un proveedor real de firma (configuración, no código) para medir el envío; la aprobación y «archivar firmado», cuando contecmind construya. |
| contecmind | Respuestas citando página y párrafo sobre los documentos de una cuenta | «¿Qué dice el contrato de este cliente sobre penalizaciones?» contestado con la cita | **Bloqueado por contecmind.** La búsqueda en el corpus responde 422 «este tenant no tiene organización asignada en el gestor documental» y el gestor no responde. No se intentó. | — | Que contecmind construya; después, mapear la organización y medir. |
| contecintelligence | Preguntar en lenguaje natural sobre los datos del CRM | Es el equivalente a Einstein/Tableau Pulse y ya está enganchado | **Funciona.** El CRM no estaba registrado como fuente: ahora se registra desde la pantalla (arreglados el alta y su plazo). «Importe total de oportunidades por etapa» devuelve las cinco sumas exactas de las 146 oportunidades. Una pregunta ambigua vuelve con opciones, que ahora se pulsan, y una respuesta se puede guardar. | Analítica → Preguntas publicadas | En contecintelligence: el filtro sobre una lista compara por igualdad («cuentas de cliente»: 2 donde hay 6). Aquí: publicar una pregunta para todos no tiene botón. |
| contecintelligence | Cuadros generados desde la pregunta, no desde un constructor | Baja el coste de que dirección se haga su propio informe | **Funciona la pregunta → gráfico**: la respuesta llega con su forma (barras, número, línea, tabla) y se dibuja, con «Ver como tabla» y la consulta usada. Las instantáneas programadas corren a su hora y se guardan (arreglados dos defectos que hacían fallar todo informe). | Analítica → Preguntas publicadas; instantáneas en Analítica → Embudo, cohortes y actividad | Convertir la pregunta en informe o en componente de un cuadro pide la definición estructurada y no hay botón. Los dos componentes del «Cuadro de dirección» fallan en contecintelligence («no se puede abrir la copia local de esta fuente»). La hora de la programación es UTC y se pide como local. |

**Pendiente real, y conviene entender por qué lo es.** contecmind no construye
su imagen, y no es un descuido: su `requirements.txt` fija `pillow>=13.0.0,<14`
**para cerrar 24 CVEs**, y `fastembed 0.8.x` sólo admite `pillow<13.0` cuando
se construye con Python 3.12 — su restricción lleva el marcador
`python_version < "3.13"`. Es una decisión de seguridad contra una restricción
de una dependencia suya, y se resuelve de dos maneras, las dos en su
repositorio:

1. construir sobre **Python 3.13**, donde `fastembed` deja de acotar `pillow`;
2. o bajar `pillow` y asumir las CVEs, que es justo lo que ellos descartaron.

**No es nuestra decisión** y no se toma desde aquí. Mientras tanto, en esta
instalación la mitad documental está degradada: «Aprobaciones de documentos»
abre diciendo exactamente eso y la dirección a la que llamó, en vez de salir
vacía. Lo que no depende de contecmind sí funciona —comprobado el 05-11-2026—:
«Archivos», con todos los documentos del CRM y el registro del que cuelga cada
uno, y «Pendiente de firma», que distingue «no hay nada en curso» de «todo
firmado».

## Qué haría yo, por orden

1. **Verificar que las 41 capacidades críticas se alcanzan desde la pantalla.**
   Están declaradas `hecho` y con prueba; lo que no está medido es que un
   usuario llegue a ellas. Hoy mismo han aparecido defectos de ese tipo en
   capacidades también declaradas hechas. Es el riesgo más barato de cerrar y
   el más caro de que te lo encuentre un cliente en una demo.
2. **Desbloquear contecmind**, porque la mitad documental es una de nuestras
   ventajas y ahora mismo no se puede enseñar.
3. **No competir en ecosistema.** Competir en aislamiento, residencia,
   profundidad de proceso y precio, que es donde el terreno es nuestro.
