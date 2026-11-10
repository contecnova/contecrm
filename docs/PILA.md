# La pila: lo que queda por hacer

> **Qué es esto.** La lista única de lo pendiente en contecrm, en el orden en
> que se construye. Se trabaja siempre desde aquí: lo que se pide entra aquí,
> lo que se termina sale de aquí con su commit, y lo que se descubre a medias
> se apunta aquí en vez de quedarse en una conversación.
>
> Cada entrada dice **lo medido** —qué hay hoy, comprobado— y **lo que falta**.
> El orden lo decide el valor: primero lo que se ve y se usa cada día, después
> lo que abre ventas, al final lo que depende de otros.

Última revisión: 09-11-2026.

## En curso

### 1. Los estados se leen como texto, no como código

- **Pedido**: 08-11-2026 («los estados salen en crudo»). Decidido por
  formulario: declarar las listas, no adivinarlas en la pantalla.
- **Hecho**: cada servicio publica en su contrato (`components.x-opciones`)
  las listas de sus columnas y los estados de sus máquinas; la pantalla las usa
  para escribir «Abierta» en vez de «abierta». Primera familia declarada:
  presupuestos, contratos, suscripciones, pedidos, lecciones, actividades
  (estado y prioridad) y casos (estado y prioridad). Los casos no validaban su
  estado —aceptaban cualquier texto— y ahora sí.
- **Falta**: el resto de familias. Medido: de 208 campos de estado, tipo o
  motivo en los contratos, 12 declaraban su lista antes de empezar.
- **Abierto a propósito**: el `tipo` de actividad y el de caso entran también
  por plantillas y no son una lista cerrada hoy. Se resuelve con la entrada 2
  (que los defina el administrador).

## Siguientes, por orden

### 2. Todo configurable por el administrador: metodologías, embudos, etapas y estados

- **Pedido**: 09-11-2026 — «no veo dónde definir las metodologías ni los
  estados, cómo se llaman, qué tipos hay o cuántos hay, por ejemplo en
  oportunidades o en el embudo; debería ser todo superconfigurable,
  absolutamente todo, por administradores».
- **Medido**:
  - Embudos (`pipelines`) y etapas: se crean por API —con criterios de
    salida por etapa—, pero en pantalla sólo hay una tabla genérica
    («Procesos de venta», dentro de Oportunidades). No hay un editor de
    embudo: ordenar etapas, probabilidad, criterios, colores.
  - Metodologías: sólo se listan; no se pueden crear ni editar.
  - Estados: están escritos en el código (máquinas de lead y oportunidad, y
    tuplas en el resto). El tenant sólo puede **quitar** transiciones; no
    puede renombrar, añadir, ordenar ni decir cuántos hay.
- **Decidido por formulario (09-11-2026)**:
  - Estados: **todo** configurable por objeto —añadir, renombrar, ordenar,
    color, cuáles son finales y a cuáles se puede pasar desde cada uno—. El
    producto sigue sabiendo qué significa cada final (ganado, perdido,
    cerrado) para la previsión, las comisiones y el SLA.
  - Metodologías: **preguntas por etapa** (MEDDIC, BANT…) con puntuación,
    **pasos y playbook por etapa**, y **varias metodologías por embudo**.
- **Se construye en este orden**: (a) estados y transiciones como
  configuración del tenant, con los de fábrica como punto de partida; (b) el
  editor de embudos y etapas; (c) las metodologías; (d) todo ello en una
  sección de Administrar.
- **(c) hecho el 09-11-2026**: Administrar › Plataforma › Metodologías y
  playbooks —MEDDIC, BANT, SPIN, Challenger o propia, por embudo; pregunta,
  peso y desde qué etapa; pasos por etapa— y los criterios se marcan desde la
  ficha de la oportunidad.
- **(b) hecho el 09-11-2026**: Administrar › Plataforma › Embudos y etapas —
  crear embudos; nombre, probabilidad, color, estancamiento, final y ganada,
  criterios de salida, orden y quitar etapas moviendo sus oportunidades—.
- **(a) hecho el 09-11-2026** para lead y oportunidad: Administrar ›
  Plataforma › Estados de los objetos, el desplegable de estado en la cabecera
  de la ficha y el código preguntando por el significado. Falta extenderlo a
  los objetos que hoy guardan su estado en una tupla —casos, presupuestos,
  pedidos…—, dándoles máquina; con eso se cierra también la entrada 1.
- **Caso, hecho el 09-11-2026**: máquina configurable, el SLA para el reloj
  por significado («en pausa») y cerrar/reabrir desde el estado pasan por su
  camino. Medido: de más de 50 tuplas de estados, la mayoría son del sistema
  (trabajos, sagas, firmas, cargas) y no se configuran; las de negocio que
  quedan son actividad, presupuesto y contrato.
- **Actividad, hecho el 09-11-2026**: máquina configurable; vencidas,
  recordatorios, abiertas de la cuenta y salud del cliente por significado.
- **Presupuesto y contrato, hecho el 09-11-2026** (con estados propios,
  decidido por formulario). De paso, la aprobación del presupuesto, que no se
  podía resolver: ahora la abre orchestrator y sales aplica lo decidido.
  **Pendiente de ver en vivo**: el viaje por el bus, porque la pila local de
  procesos corre sin NATS. Con esto queda cerrada la entrada 2(a); la
  entrada 1 (listas legibles) queda cubierta para los objetos de negocio.

### 3. Las gráficas se leen al pasar el ratón — hecho el 09-11-2026

La forma de barras horizontales tenía encima la capa de puntería de las
columnas, en franjas verticales, y el ratón caía en la franja equivocada o en
ninguna; y la gráfica se dibujaba a 640 de ancho fijo, con lo que en una
tarjeta la letra se veía de 8,6 px. Ahora cada fila es su zona —también con el
teclado—, se resalta la señalada con su emergente y la gráfica mide su sitio.

Y el 09-11-2026, pedido al verlo: el detalle de debajo de cada gráfica sale
**siempre** —con la primera barra mientras no se señala ninguna, y con la
señalada al pasar—. Sólo al pasar, la tarjeta crecía y encogía con el ratón.

### 4. Un GRC mucho más potente — hecho el 09-11-2026

- **Pedido**: 09-11-2026 — «el GRC debe ser mucho más potente, pudiendo llegar
  a tener un DEM o TCSEC como los que tiene Infor en sus herramientas».
- **Medido**: hoy hay riesgos, controles, cobertura del catálogo y
  segregación de funciones (CRM-07.03).
- **Aclarado por formulario (09-11-2026)**: «DEM» es la **matriz de
  segregación de funciones** —reglas de conflicto entre permisos y roles, con
  detección y mitigación—. De TCSEC, las tres partes: **clasificar la
  instalación por nivel** (D, C1, C2, B1…), **los controles exigidos por
  nivel** con sus evidencias y su comprobación automática donde se pueda, y
  **un informe exportable para auditoría**.
- **Hecho el 09-11-2026, la matriz de segregación**: pantalla en Administrar ›
  Gobierno y cumplimiento › Segregación de funciones con la matriz de reglas
  contra roles, el editor de reglas, quién está en conflicto con su excepción,
  el simulador «qué pasa si le doy este rol» y siete reglas de serie. Quitados
  los dos trozos que contestaban lo mismo (Seguridad y la pestaña de
  Cumplimiento); el de Seguridad no marcaba nunca la excepción.
- **Hecho el 09-11-2026, TCSEC**: pantalla en Administrar › Gobierno y
  cumplimiento › Clasificación TCSEC (CRM-07.03.02.11) con 15 requisitos de C1
  a A1 —11 medidos sobre el sistema, 4 atestiguados en el GRC—, el nivel
  alcanzado y el informe descargable. La pila local sale en D porque conecta
  como SUPERUSER.
- **Queda abierto, y se dice en la pantalla**: el control obligatorio de
  escritura por etiquetas (no copiar un dato a un nivel más bajo) no existe;
  sin él no hay B1. Construirlo es un bloque propio; sólo si se pide.

### 5. Las 41 capacidades críticas, alcanzables desde una pantalla

Declaradas hechas y con prueba; lo que no está medido es que un usuario llegue
a ellas. Se recorren una a una, como se hizo con lecciones.

- **Recorrido hecho el 09-11-2026** en el navegador (procesos, automatizaciones
  y aprobaciones). Arreglado ya: crear aprobaciones desde el formulario, la
  bandeja, versiones en el editor, quién decidió, reaprobación falsa, las
  esperas que no despertaban, tareas que respondía o delegaba cualquiera,
  ramas y bucles que no se guardaban.
- **Declaradas hechas y sin construir; decidido por formulario construirlas
  todas** (09-11-2026):
  - [x] Pasos «servicio» que llaman al CRM, **con los permisos de quien lanzó
    el proceso** — hecho el 09-11-2026: «MÉTODO /api/v1/ruta», visto crear una
    actividad desde el worker real. Una automatización lanza procesos con los
    de quien la activó; las que ya estaban encendidas no tienen esa identidad
    hasta que alguien las vuelva a encender.
  - [x] Editor de tablas de decisión — hecho el 09-11-2026: columnas, rejilla
    de reglas, validar, probar sin guardar y guardar; la fila y «Nuevo» de la
    pestaña llevan a él.
  - [x] Migrar instancias en vuelo a otra versión — hecho el 09-11-2026, desde
    el Editor de procesos, simulando antes.
  - [x] Plantillas de flujo por sector, que se copian a un borrador — hecho el
    09-11-2026 (cinco).
  - [x] Automatizaciones diferidas y programadas — hecho el 09-11-2026 (cola
    con planificador).
  - [x] Disparadores de borrado, webhook, programado, manual y evento — hecho
    el 09-11-2026. Borrado y evento, probados sólo llamando al consumidor: la
    pila local no tiene bus.
  - [x] Promover automatizaciones entre entornos — hecho el 09-11-2026: en seco
    contra un sandbox real; aplicarlo, probado en unitaria.
  - [x] Biblioteca de plantillas de automatización que se instalan — hecho el
    09-11-2026 (seis).
  - [x] Decidir una aprobación desde el correo: página pública de un solo uso
    y el correo con el enlace — hecho el 09-11-2026 (`/decidir?t=…`, tope por IP
    en el gateway). En la pila local el correo no llega: el bus no lo entrega a
    identidad.

### 6. Las 82 capacidades sin pantalla (quedan 2)

El tope del guardián (`TOPE_SIN_PANTALLA`) está en 82. Bajan por familias.

- **09-11-2026, medidas las 21 críticas (C)**: 6 se alcanzaban sin
  declararlas, 9 necesitan pantalla y 6 no están hechas del todo (MFA por rol
  y push, deduplicar leads al capturar, reunión en línea de verdad, duplicar
  registros, revertir una importación, p99 por operación).
- **Hecho**: 4 comprobadas en el navegador y declaradas (82 → 78). Y la
  familia que salió al comprobarlas: un resumen que es una LISTA no se pintaba
  —los casos en riesgo de SLA no se vieron nunca—; ahora sale como lista con
  su rótulo (4 de los 40 resúmenes lo eran).
- **Hecho el 09-11-2026, las 21 críticas** (82 → 63): las 9 pantallas que
  faltaban y las 6 que no estaban hechas (decidido por formulario construirlas
  todas): MFA por rol (sin push: TOTP y passkeys), «Entrar como» de soporte,
  identificador de petición, latencia p95/p99 por operación, alta en las
  herramientas, credenciales de la conexión, encargos en el portal, acciones
  del sobre de firma, reunión en línea, deduplicar leads, duplicar y
  traspasar, importar con reversión, lote desde la tabla y previsión por
  jerarquía. Arreglados de paso: el login no leía los ajustes de la empresa,
  el identificador de petición no era el mismo de punta a punta, la auditoría
  sólo enseñaba la de un servicio, el sobre no guardaba el id del proveedor y
  declarar una operación de conexión daba 500.
- **Sin ver en vivo**: la reunión contra Teams/Meet y la firma contra un
  proveedor real (no hay ninguno conectado en local), y lo que cruza el bus.
- **09-11-2026, medidas las 63 que quedan (A y D)**: ~19 se alcanzan (varias
  sólo en parte), 11 necesitan pantalla y ~34 **constan hechas y sólo
  simulan** —calculan sobre datos tecleados, devuelven un plan sin ejecutarlo
  o no guardan—. Decidido por formulario **construirlas todas**:
  - [x] IA: modelos predictivos entrenados con el histórico (scoring, cierre,
    importe, fecha, propensión, siguiente oferta, segmentación).
  - [x] IA: transcripción y resumen de llamadas y reuniones, con compromisos.
  - [x] IA: asistente que busca en el conocimiento y ejecuta acciones; preguntas
    en lenguaje natural que se ejecutan.
  - [x] IA: variantes de copy generadas, con revisión; asistente de voz.
  - [x] Marketing: audiencias a plataformas publicitarias.
  - [x] Marketing: mejor hora y canal aplicados al envío y a los recorridos.
  - [x] Marketing: recomendaciones en la personalización; previsualización en
    varios clientes y spam score real.
  - [x] Marketing: transaccional por su dominio, separado del promocional.
  - [x] Telefonía/CTI y marcador sobre la telefonía del tenant.
  - [x] Analítica de cohortes, embudo y actividad con datos del CRM;
    instantáneas programadas; consulta al lake del cliente.
  - [x] Suite: avisos y consultas en Teams/Slack, reuniones y asistentes
    registrados, notas/ficheros/chats por referencia guardados.
  - [x] Compensación externa y SLA de proveedor frente al prometido.
  - [x] Historial de configuración con diff y vuelta atrás; jerarquía de
    empresas completa; consumo exportable a facturación.
  - [x] Calidad del dato: golden record, enriquecimiento externo, identidad
    entre canales, umbral por objeto, direcciones.
  - [x] Archivado consultable y modo sin conexión.
  - [x] Sandbox de API con datos sintéticos y consola; MFA por proveedor.
  - [x] Las 11 pantallas que faltan y declarar las ~19 alcanzables.
- **Hecho el 09-11-2026, segunda tanda (33 → 2)**: todo lo anterior construido
  y visto en el navegador. Quedan sin pantalla declarada las renovaciones
  (CRM-03.03.02.10: verlas abriría oportunidades sobre contratos reales; está
  en pruebas) y CRM-00.04.04.06, que necesita el bus.
- **Pendiente de lo de la segunda tanda**:
  - [ ] Probar contra proveedores reales: transcripción, centralita, motor de
    compensación, Teams/Slack, enriquecimiento. Todo está probado contra dobles
    locales; falta la credencial de cada uno en Integraciones y, para la
    transcripción por enlace, un `PUBLIC_BASE_URL` público.
  - [x] Integration debe mandar a party las señales de identidad de otros
    canales (`POST /calidad-dato/identidades/observar`) y la respuesta que
    detecta el buzón a las cadencias.
  - [x] Golden record y umbral por objeto para leads (hoy cuentas y contactos).
  - [x] Sin conexión: formularios que no se abrieron con red, borrar sin red.
  - [x] `numero_erroneo` de la telefonía no marca el teléfono de la ficha.
  - [x] Al recoger ventas para la compensación, el reparto sale vacío: la lista
    de oportunidades no trae `owner_id` con esa identidad. Sin investigar.
  - [x] El embudo de la analítica se limita a 100 historiales; un listado en
    bloque en sales quitaría el tope.
- **Cerrado el 10-11-2026** (lo pendiente de la segunda tanda):
  - Señales de identidad desde correo, calendario, SMS, voz, telefonía,
    buzón y ERP; el rastreo web y la app no existen en integration.
  - La respuesta detectada en el buzón saca de las cadencias, una vez por
    mensaje, y queda como actividad.
  - Ficha buena y umbral por objeto para leads; embudo de la analítica sin
    tope de 100; renovaciones vistas y declaradas (queda 1 sin pantalla,
    CRM-00.04.04.06, que necesita el bus).
  - El reparto vacío de compensación no era de código: 160 de 162 ganadas no
    tienen dueño. Desde ahora quien crea una oportunidad queda como dueño; las
    antiguas, al poblar (entrada 10).
  - Restos de la primera tanda: el secreto de una clave se enseña una vez,
    `ips_permitidas`, el sandbox, el equipo de confianza del tenant, el consumo
    legible y borrar sin conexión.
  - **Arreglado al medir**: `If-Match` sólo lo respetaba la edición genérica
    (ahora toda escritura sobre un registro); **el bloqueo por intentos
    fallidos no actuaba nunca** (el error deshacía el contador); no había forma
    de volver a verificarse sin salir (ruta y diálogo común nuevos); los
    ajustes de la analítica habían dejado de registrarse.
- **Arreglado de paso en la segunda tanda**: toda subida de fichero desde la
  pantalla daba 500 (la idempotencia releía un cuerpo multipart ya leído); los
  enlaces firmados a adjuntos daban 401 siempre; tras borrar un caso nadie
  podía abrir otro (el código salía de contar casos sin los borrados); una
  línea libre de presupuesto sin precio daba 500; la vista «Por columnas» de
  Oportunidades no dejaba arrastrar (la etapa tiene su propia acción); el
  rechazo de una combinación de productos no decía cuáles chocaban.
- **Arreglado al medir (09-11-2026)**: el inicio de sesión web no mandaba nunca
  el código del segundo factor —con él exigido, nadie entraba—; el consumo de
  un tenant lo leía cualquiera con sesión, también el de otra empresa; la ruta
  de identidades de un contacto daba 500 siempre.

### 7. Lo que el PATCH genérico ofrece y escribe el sistema

De 357 campos, 34 se cerraron el 08-11-2026 (hashes, sellos, contadores,
derivados). Quedan 323 que el código también escribe pero corrige una persona
—estado, notas, plazos—; se revisan por familia sólo si aparece un caso real.

### 10. El objetivo completo, medido el 09-11-2026

- **Pedido**: 09-11-2026 — «rediseño completo que se compare con Salesforce y
  lo supere; la IA clave y funcionando a la perfección; todas las
  funcionalidades con sentido en el front; flujos, avisos e información
  cruzada increíblemente potentes; recoger lo interesante de contecmind y
  contecintelligence; nunca mentir, todo completo, medir, nada hardcodeado,
  ultra configurable, la mejor experiencia de usuario».
- **Por orden**:
  - [x] **El bus en vivo** (10-11-2026): NATS en Docker, 156 consumidores, la
    aprobación de presupuestos hace ida y vuelta en 2 s; arreglada la
    aprobación a medias que quedaba pendiente. Pendiente: el tenant de
    plataforma no tiene organigrama ni etapas de aprobación (nadie puede
    aprobar un presupuesto ahí), y CRM-00.04.04.06 sin ver. Era: Levantar
    uno con JetStream (hay Docker) y recorrer todo lo que cruza servicios
    —aprobación de presupuestos, firma que mueve la etapa, avisos de
    automatización al chat, CRM-00.04.04.06—, arreglando lo que falle.
  - [ ] **Evaluación de la IA.** No existe ningún conjunto de evaluación (sólo
    métricas de los modelos predictivos): «funciona a la perfección» no se
    puede afirmar. Banco de casos con su respuesta buena —asistente,
    preguntas sobre los datos, resúmenes, extracción, compromisos de
    reuniones— pasado contra el modelo real, con el acierto a la vista y un
    aviso si baja; y corregir hasta que acierte.
  - [x] **Todo bajo el GRC** (entrada 11), hecho el 10-11-2026.
  - [ ] **Lo que queda fuera del front**: 32 colecciones publicadas sin
    pantalla que las abra (`TOPE_SIN_PUERTA`) y 91 capacidades que ninguna
    prueba nombra (`TOPE_SIN_PRUEBA_QUE_LAS_NOMBRE`).
  - [x] **contecintelligence** (10-11-2026): el CRM registrado como fuente;
    preguntas en lenguaje natural, cuadros desde la pregunta e instantáneas
    programadas funcionan en vivo. Pendiente aquí: la hora de una programación
    se guarda en UTC y se pide como local; publicar una pregunta para todos no
    tiene botón; la generación desde plantilla no rellena los datos del
    registro ni saca PDF. En contecintelligence (avisar, no tocar): «cuentas de
    cliente» da 2 donde hay 6 y los componentes del cuadro de dirección no
    abren su fuente. contecmind sigue caído (entrada 9): firma documental y
    respuestas que citan página sin ver.
  - [x] **Colecciones sin pantalla** (10-11-2026): de 29 a 0; 22 en pantalla y 7
    declaradas con su motivo. Cerrada de paso una fuga: el estado de las colas
    de eventos enseñaba las de todos los tenants.
  - [x] **Organigrama** (10-11-2026): Administrar › Usuarios y empresa ›
    Organigrama; SCIM ya lo trae; la réplica sólo aplicaba el primer cambio de
    cada persona.
  - [ ] Era: **contecintelligence y contecmind**: registrar el CRM como fuente en
    contecintelligence (las instantáneas y las preguntas que pasan por él no
    se han visto en vivo) y medir una a una las cinco piezas que la
    comparativa dice traer. contecmind sigue caído por la entrada 9.
  - [x] **Barrido de constantes** (10-11-2026, `scripts/barrido_constantes.py`):
    20 umbrales de negocio pasan a ajuste, tres ajustes que existían ya se leen
    y lo que queda va con su motivo. Segundo bloque (10-11-2026): la ventana
    de las cadencias en la hora del tenant y con un ajuste por tramo; cinco
    vocabularios editables en Gestor de objetos, con valores fijos que el
    código lee uno a uno (los motivos de suspensión se quedan cerrados: son
    los de la norma); cuatro umbrales más a ajuste. Cerrado después, el mismo
    día: el primer paso de una cadencia respeta la ventana; la consola de
    Ajustes lista y fija las 166 claves de los `ajustes.py` de los servicios
    (cada uno las publica y tenancy las agrega; medido en vivo con party,
    sales y service); y las columnas que guardan un valor de vocabulario
    pasan a 120 caracteres.
  - [x] **El bus entregaba nada a los consumidores de «todo»** (10-11-2026):
    `contecrm.*.*` no casa con tipos con punto; 30 consumidores (avisos,
    reglas, webhooks, perfiles, cachés y extensiones de cada servicio) no
    recibían nada en NATS. El bus en memoria lo escondía. Ahora `contecrm.*.>`
    y el de memoria con las reglas de NATS.
  - Era: **Barrido de constantes** en el código entero: hoy no está medido, y
    sin medirlo no se puede decir «nada hardcodeado».
  - [ ] **El rediseño pantalla por pantalla**, con medidas de usabilidad
    (clics y tiempo por tarea frecuente), no sólo a ojo.
    - **Medido el 10-11-2026** (`frontend/scripts/medir-tareas.mjs`, tabla en
      el manual técnico 4.6.71): 12 tareas de comercial, soporte y
      responsable. Antes 7 de 12 terminadas y 5 bloqueos; después 12 de 12, y
      las doce en clics iguales o por debajo de la estimación de Salesforce
      (estimación, no medida).
    - [x] **Arreglado el 10-11-2026** (manual técnico 4.6.72): el lead sin
      «Más campos» para apellidos y correo; la prioridad del caso, un
      vocabulario de la empresa; el selector de referencias y el buscador de
      cada lista buscan en el servidor (`?buscar=`); responder un caso manda
      el correo por el canal transaccional, con su plantilla, y consta salga o
      no; Cuentas, tercera pestaña de Ventas; el desplegable de estado no
      ofrece lo que tiene su acción. Vuelto a medir: T02 de 6 a 5 clics, T08
      de 3 a 5 (elegir en una lista son dos), el resto igual. La T09 nueva
      (enviar de verdad) no se ha corrido contra el tenant de plataforma: su
      canal transaccional no tiene remitente ni servidor.
    - **Queda**: un contacto con correo o teléfono y un lead ya repartido no
      se pueden borrar (sólo archivar) y lo archivado sigue en el buscador; la
      bandeja de aprobaciones es un punto ciego del guardián de contratos (su
      forma no se resuelve en estático, aunque la fija una prueba HTTP).
  - [ ] **Rehacer la comparativa con Salesforce** capacidad por capacidad con
    lo construido desde el 05-11; el lado de Salesforce no está medido.
  - [ ] **Poblar todo**: 213 de 235 pestañas con datos; 16 vacías (unas con
    razón —fallidos, papelera, pendientes— y otras sin datos de ejemplo:
    audiencias publicitarias, sobres de firma, registros recibidos,
    programación de integraciones, proveedores de identidad…).

### 11. Todo lo que hay en la aplicación, controlado por el GRC

- **Pedido**: 09-11-2026 — «revisar que todo lo que hay en la aplicación esté
  controlado por GRC; desarrollar algo como el TCSEC y el DEM de Infor para
  controlar accesos, todo ello enlazado con el GRC».
- **Medido el 09-11-2026** en el tenant de plataforma:
  - Cobertura: **0 de 781 capacidades hechas tienen control**. Hay 6
    controles y 6 riesgos, y ninguno anclado a una capacidad hecha.
  - Segregación de funciones (el DEM, hecho hoy): **no está enlazada con el
    GRC**; sus reglas y conflictos no generan ni riesgos ni controles ni
    evidencias.
  - TCSEC (hecho hoy): sólo los 4 requisitos manuales pasan por el GRC; los 11
    medidos no dejan evidencia en él.
  - **No hay revisión periódica de accesos** (recertificación: cada
    responsable confirma o retira lo que tiene su gente).
- **A construir**:
  - [x] Controles de serie anclados a las capacidades, por familia, con su
    evidencia automática (el audit trail, los gates, los certificados), hasta
    que la cobertura mida de verdad lo que hay —con el informe de los dos
    sentidos que ya existe—.
  - [x] La segregación como control del GRC: cada regla es un control
    preventivo, cada conflicto sin excepción un hallazgo con su riesgo, cada
    excepción aprobada una evidencia con caducidad.
  - [x] TCSEC entero en el GRC: los 15 requisitos como controles, los
    medidos con su evidencia automática al evaluarse.
  - [x] Revisión de accesos: campañas periódicas por responsable, con
    confirmar o retirar y la retirada aplicada de verdad en identity; el
    resultado, evidencia del control de accesos.
  - [x] Todo en Administrar › Gobierno y cumplimiento, enlazado en los dos
    sentidos (del control a la regla o el requisito, y de vuelta).
- **Hecho el 10-11-2026**: 785 de 785 capacidades ancladas a un control de serie
  y 398 verificadas con evidencia (antes 0); segregación y TCSEC dentro del
  GRC; revisión de accesos con retirada real. Quitada la pestaña genérica
  «Controles», que enseñaba lo mismo que la pantalla nueva.
- **Pendiente**:
  - [x] **El organigrama no se puede fijar desde ninguna pantalla** (sólo llega
    por SCIM o SSO). Sin él no hay quién apruebe un presupuesto en el tenant de
    plataforma y la revisión de accesos cae entera en el revisor por defecto.
    Hace falta una pantalla para decir quién depende de quién.

## Dependen de otros

### 8. Apps móviles y complemento de correo

CRM-04.04.01.03, CRM-06.01.01.02 y CRM-06.02.01.03 están `en-curso`: existe
el servidor que necesitan; no hay ninguna app ni complemento.

### 9. contecmind no construye su imagen

`pillow>=13` (cierra 24 CVE) choca con `fastembed`, que en Python 3.12 exige
`pillow<13`. Se decide en su repositorio; mientras, la parte documental de
contecrm está degradada.

## Del usuario

- Rotar la clave de la API de Google.
- Revisar `exigir_opt_out` en el tenant de plataforma.
