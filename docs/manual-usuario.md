# Manual de usuario

Este manual está escrito para quien **usa** contecrm: el comercial que abre una
oportunidad, el agente que contesta un caso, quien prepara una campaña y quien
administra el sistema para los demás. No hay que saber nada de la arquitectura
para leerlo; para eso está el [manual técnico](manual-tecnico.md), que es
independiente de este.

Está organizado en tres partes:

1. **Qué hace el CRM**, área por área. Un capítulo por cada área funcional, con
   lo que hay que saber para usarla y —esto es lo que suele faltar en los
   manuales— **por qué el sistema se comporta así** cuando te dice que no.
2. **Casos de uso de punta a punta**: del primer contacto al cobro, y del alta de
   una incidencia a su cierre, con las decisiones que hay que tomar por el camino.
3. **Cómo empezar de verdad**: ejemplos reproducibles con los datos de la demo,
   qué hacer cuando algo no sale, y un recorrido para cada perfil.

Una advertencia que vale para todo el manual: **el CRM dice que no bastante a
menudo**, y casi siempre por el mismo motivo. Cuando un sistema acepta cualquier
cosa, lo que acaba teniendo dentro no sirve para decidir nada: un pipeline lleno
de oportunidades sin fecha, clientes duplicados y previsiones que nadie cumple.
Cada vez que aquí veas «no deja», está explicado qué se evita con eso.

---

## Cómo se entra y cómo se busca (sección 0.5)

**Entrar.** Si tu empresa tiene inicio de sesión corporativo (SSO), entras con el
usuario de siempre y el CRM no te pide otra contraseña. Si no, entras con tu
correo y una contraseña propia, y muy probablemente con un **segundo factor**: un
código de una aplicación, una llave física o un mensaje. El segundo factor por SMS
o por correo se marca como el más débil, y el administrador puede desactivarlo —
si tu empresa lo ha hecho, es a propósito.

Cuando cambias de dispositivo o alguien cierra tu sesión desde administración, la
sesión se corta en todas partes. Es lo esperado: una sesión que sigue viva en un
portátil perdido es el problema que esa función existe para evitar.

**Y a veces te pedirá el código aunque ya hayas entrado.** Pasa en dos
situaciones y las dos tienen explicación en pantalla:

- **Ha cambiado el contexto**: entras desde un sitio nuevo, desde un equipo que
  no habías usado o después de mucho tiempo sin aparecer. No es que sospeche de
  ti: es que la forma más común de entrar en una cuenta ajena es con una sesión
  que sigue viva, y el segundo factor es lo único que lo nota. Si te dice que ha
  visto dos países en dos horas, **avisa**: eso no se arregla tecleando el código.
- **Vas a hacer algo delicado**: exportar en masa, borrar en bloque, cambiar
  permisos, restaurar datos encima de los actuales, crear una credencial de
  máquina o entrar como otra persona. El código vale un rato para todas; no te lo
  pedirá en cada una.

**Qué puedes ver.** Lo que ves no es «todo el CRM»: es lo tuyo y lo que se
comparte contigo. Hay cuatro formas de que algo llegue a tu pantalla —que seas el
propietario, que esté compartido con tu equipo, que te llegue por la jerarquía
(tus subordinados) o que una regla lo abra a más gente— y cuando algo no te
aparece, **el CRM puede decirte por qué**. No es un error: es que no te toca, y
saberlo ahorra la llamada a soporte.

**Moverse.** A la izquierda está el menú, y lo que hay dentro está agrupado:
arriba los accesos que se usan a diario —inicio, tu puesto, la consola de agente
y los casos—, debajo los **módulos**, que son las pantallas de cada área del
catálogo, y después análisis y plataforma. Cada grupo se pliega, y se queda
plegado la próxima vez que entres: si no usas los módulos del catálogo, no
tienes que verlos.

Arriba, la línea que empieza en «Inicio» dice dónde estás y permite volver: en
una ficha, el paso anterior es el listado del que salió.

**Ir a una pantalla escribiendo su nombre.** `⌘K` en Mac, `Ctrl+K` en el resto,
o el buscador de la barra de arriba. Escribes «cuentas», «previsión» o «ventas»
—vale el nombre del grupo— y las flechas y `Intro` te llevan. Con veinticinco
módulos y veinte pantallas transversales, esto es más rápido que el menú, y no
lo sustituye: el menú es para ver qué hay, el atajo para volver a algo que ya
sabes que existe.

**Claro y oscuro.** El botón de la barra de arriba cambia el tema, y la elección
se recuerda en ese navegador.

**Si operas la plataforma, de quién son los datos que ves.** En la barra de
arriba hay un selector de cliente. Ves **uno cada vez**, el tuyo salvo que
elijas otro, y mientras miras a otro el selector se pone en ámbar para que no
se te olvide. Hasta el 27-10-2026 no existía porque las listas enseñaban los
clientes mezclados sin decirlo, que es como se acaba contestando a un cliente
mirando la ficha de otro. Lo que elijas se olvida al cerrar la pestaña.

**Buscar.** Se escribe en el mismo sitio: `⌘K` o `Ctrl+K`. Arriba salen las
pantallas que casan con lo escrito y **debajo los registros**: cuentas,
contactos, oportunidades, casos y documentos, con su nombre y lo que los
distingue, y `Intro` lleva a la ficha. Respeta lo anterior: no encuentra lo que
no puedes ver. Busca por nombre, por identificador fiscal, por teléfono y por
correo — y por teléfono funciona aunque esté escrito de otra forma
(`+34 600…`, `0034600…`, `600…`), porque los que están mal escritos suelen ser
los clientes de toda la vida.

Hasta el 27-10-2026 esto estaba prometido aquí y **no funcionaba de dos formas
a la vez**: la paleta sólo buscaba pantallas —quien escribía «Acme» llegaba a
la lista de cuentas y tenía que buscar Acme otra vez dentro— y la búsqueda del
servidor devolvía cero resultados siempre, porque preguntaba a cada servicio
por una dirección que no era la suya. No daba error: devolvía «no hay nada».

---

### Si el sistema no responde, lo dice

Entrar y «el sistema no está respondiendo» son dos cosas distintas, y antes se
veían igual: si el servidor no contestaba —un reinicio, un corte de red, el
túnel caído— aparecía **el formulario de entrada**, como si sólo te faltara
escribir la contraseña. Y al escribirla, otro error que tampoco explicaba nada,
porque la contraseña no era lo que estaba mal.

Ahora, cuando no se ha podido ni preguntar quién eres, sale el aviso con lo que
dijo el servidor y un botón para reintentar. No te pide una credencial que no
va a poder comprobar.

### Si una pantalla se cae, te puedes ir a otra

Cuando una pantalla no se puede pintar, sale el aviso **en su sitio**: el menú,
la barra de arriba y el buscador siguen donde estaban, así que te vas a otra
cosa y sigues trabajando.

Hasta el 29-10-2026 no era así del todo. El aviso aparecía bien, pero **se
quedaba puesto**: cambiabas de opción y seguías viendo el mismo mensaje en
todas, y la única salida era recargar la página a mano. Se reportó yendo a
Inteligencia con su motor apagado. Ya no pasa: al cambiar de pantalla el aviso
se va solo.

### Las opciones del menú no van y vienen

El menú te enseña lo que puedes abrir, y esconde lo que no: ofrecerte algo que
al pulsarlo sólo te va a decir que no te toca es hacerte probarlo para
descubrirlo.

Para saberlo, la aplicación le pregunta al servidor qué permite cada cosa. El
problema era qué hacía cuando **una parte del servidor no contestaba** —uno de
los servicios reiniciándose, por ejemplo—: lo tomaba por «no te toca» y
escondía esas opciones. Como esa pregunta se hace una sola vez al entrar, el
menú se quedaba corto para el resto de la sesión, y cambiaba de una pantalla a
otra sin motivo visible.

Ahora distingue las tres situaciones: mientras no se sabe, no esconde nada;
cuando lo sabe todo, manda lo que diga el servidor; y de la parte que no ha
contestado **no esconde nada tampoco**, porque no es lo mismo «no te toca» que
«no se ha podido preguntar». Puedes encontrarte una opción que al abrirla avise
de que ese servicio no responde: eso es información, y es preferible a que la
opción desaparezca sin explicación.

---

## Tu espacio y el de tu empresa (sección 0.1)

Cada empresa tiene su propio espacio, con sus datos, su configuración y su marca.
Nada se comparte entre espacios, y eso no es una promesa comercial: está impuesto
por la base de datos, no por una comprobación del programa.

Lo que te afecta como usuario:

- **El idioma, el formato de fecha, la moneda y el huso horario** son los de tu
  espacio, y pueden ajustarse por persona. Si ves las fechas al revés de como las
  escribes, eso se cambia sin tocar nada más.
- **«Hoy» es hoy donde estás tú**, no donde esté el servidor. Importa más de lo
  que parece: todo lo que caduca —un presupuesto, el acceso que alguien te
  compartió, tu pertenencia a un equipo de cuenta— se mide contra ese día. Si el
  sistema usara el huso del servidor, a primera hora de la mañana todavía sería
  ayer y las cosas caducarían un día antes de lo que dice la pantalla.

  Si su empresa viene de una versión anterior a octubre de 2026 y nota fechas
  corridas un día a primera hora, dígaselo a quien administre el CRM: se arregla
  abriendo el perfil del espacio y guardando el huso horario.
- **La marca**: logo, colores y dominio propio. Si tu empresa lo ha configurado,
  los correos que salen del CRM van con su imagen y desde su dominio.
- **Los límites**: hay topes de almacenamiento, de registros y de llamadas a la
  API. Cuando te acercas a uno **se avisa antes**, no cuando ya no cabe nada. Si
  algo se bloquea por cuota, el mensaje dice cuál y cuánto queda.

  El aviso **sale solo**: no hay que entrar a mirarlo. Salta una vez por tope y
  por periodo cuando se cruza el umbral —de fábrica, el 80 %— y lleva de qué
  tope habla, cuánto se lleva gastado y cuánto queda, para que se pueda decidir
  sin abrir nada.

  > Hasta el 11 de octubre de 2026 ese aviso se calculaba pero sólo aparecía
  > dentro del panel de consumo, así que había que acordarse de ir a mirar.

---

## Lo que el CRM puede hacer sin ti (sección 0.3)

Detrás de casi todo lo que usas hay procesos que corren solos: reglas que asignan
un caso, avisos que se mandan cuando algo lleva demasiado parado, aprobaciones que
van a quien toca.

Lo que hay que saber:

- **Una automatización nunca actúa en secreto.** Todo lo que hace queda registrado
  con su nombre, y en el historial del registro se ve qué cambió una persona y qué
  cambió una regla.
- **Cuando una automatización falla, se para y se dice.** No lo intenta veinte
  veces en silencio. Si algo que esperabas no ha pasado, en la ficha se ve qué
  regla falló y por qué.
- **Las aprobaciones tienen dueño y plazo.** Una aprobación sin responsable no
  avanza sola y sin plazo se queda para siempre; por eso el sistema pide las dos
  cosas, y avisa a quien tenga que decidir.
- **Y un proceso largo se puede parar a la mitad.** Si un proceso toca varias
  cosas y una falla, lo hecho se deshace donde se puede y, donde no —un correo ya
  mandado no se desmanda—, queda marcado como **atascado** y no como
  «compensado». Es incómodo y es la verdad.

### Cuando un proceso se queda parado

En **Procesos › Instancias**, cada fila se abre. Dentro está lo que hace falta
para entenderlo y para sacarlo de ahí:

- **Por dónde va, sobre su propio diagrama.** El mismo dibujo que se ve al
  escribir el proceso, con cada caja marcada: aquí está, hecho, falló, deshecho,
  pendiente o no se pasó por aquí. Va **escrito debajo de cada caja**, no sólo en
  el color del borde. Y se dibuja sobre la versión con la que arrancó esta
  instancia, no sobre la que se publicó después: enseñarla sobre el dibujo nuevo
  señalaría pasos que este proceso no tiene.
- **Qué pasó, en orden.** El estado de cada caja dice dónde está; la lista dice
  en qué orden ocurrió. Con un bucle por medio no es lo mismo: un paso puede
  estar «hecho» por la tercera vuelta, y lo que importa es qué decidió en cada
  una.
- **Tres formas de desatascarlo, y elegir entre ellas es el trabajo:**
  **reintentar** vuelve a ejecutar lo mismo —sirve si el fallo fue pasajero, y
  si la causa sigue ahí volverá a fallar igual—; **corregir las variables**
  arregla un proceso atascado por un dato mal cargado; y **saltar el paso** es
  para cuando ese paso no se va a poder completar nunca: el servicio de un
  tercero que ya no existe, la tarea de alguien que se fue de la empresa.

  Saltar sólo ofrece **los caminos que el propio paso tiene escritos**. No se
  puede saltar a cualquier sitio, y no es una limitación: meter un pedido en la
  rama de «aprobado» sin que nadie lo aprobara dejaría el histórico diciendo que
  el proceso se siguió.

  Las tres piden **por qué**, y queda apuntado con tu nombre. Cambiar el curso de
  un proceso en marcha sin dejar escrito el motivo es una decisión que nadie
  podrá revisar después.
- **Y si es éste o es ese paso.** Debajo sale dónde se atasca el proceso en
  **todas** sus ejecuciones, no sólo en ésta, con el aviso de cuándo el dato
  todavía no es concluyente: un cuello de botella deducido de tres ejecuciones
  lleva a rediseñar un flujo que funcionaba.

### Antes de publicar un proceso

En el **editor de procesos**, dos botones que no tocan nada:

- **Validar** busca lo que no se ve leyendo el diagrama: pasos a los que no se
  llega desde el inicio, pasos desde los que no se llega a ningún final —un
  bucle sin salida, una rama que se quedó sin enlazar—, ramas que apuntan a un
  paso que no existe, condiciones mal escritas que se cumplirían siempre, y
  tareas que no dicen a quién le tocan: ésas no las ve nadie y dejan el proceso
  parado para siempre.
- **Simular** recorre el proceso con **datos de ejemplo** que tú pones, sin
  ejecutar nada de verdad. Dice por qué pasos iría ese caso, **quién lo
  aprobaría** y **cuánto tardaría**. El plazo es el que está declarado en el
  proceso, no una predicción, y si alguna tarea humana no tiene plazo puesto se
  dice: un proceso que espera a una persona sin fecha no tarda cero, tarda lo que
  tarde.

Un error descubierto aquí es un mensaje. Descubierto en marcha, es un proceso a
medias en producción.

---

## Campos, listas y pantallas a tu medida (sección 0.4)

Casi todo lo que ves se puede adaptar sin programar: añadir un campo, cambiar el
orden de una ficha, ocultar lo que no usáis, crear un objeto nuevo para algo que
solo existe en tu negocio.

Lo importante para el día a día:

- **Un campo nuevo funciona en todas partes desde el primer momento**: se puede
  buscar, filtrar, exportar, usar en una plantilla y en una automatización. No hay
  «campos de segunda».
- **El diseñador de formularios no deja guardar un diseño roto.** Si pones un
  campo obligatorio en una pestaña secundaria, el formulario no se podrá guardar y
  el usuario no verá por qué; si el mismo campo está en dos sitios, al guardar gana
  el que no tocaste. Esas dos cosas se avisan antes.
- **Esconder un campo con una condición no es protegerlo.** Si un dato no lo puede
  ver alguien, eso es un permiso, no una condición de visibilidad. El sistema lo
  dice cuando te acercas a esa confusión.
- **Y un cambio de tipo de campo con datos dentro no se aplica solo**: primero
  enseña a cuántos registros afecta y qué se perdería.

### Abrir un objeto del modelo

En **Administrar › Modelo de datos › Objetos**, cada fila se abre. Dentro está
todo lo que gobierna ese objeto:

- **Sus campos**, con el tipo, si son obligatorios, si son únicos y su
  sensibilidad. Y al lado, **cuántas veces se ha escrito cada uno**: es lo que
  contesta «¿puedo quitar este campo?». Leer mide quién mira; escribir mide si
  el campo se rellena. Los que no se han escrito nunca salen señalados, porque
  son los candidatos a retirar — sin este dato la respuesta es siempre «no lo
  sé», y así es como un modelo acaba con trescientos campos de los que nadie
  recuerda la mitad.
- **Cuánto sitio queda** antes del tope de campos, y qué pasa al llegar. Un
  tope que sólo se explica cuando se alcanza se explica tarde.
- **Las validaciones**, con el mensaje que verá quien las incumpla: es la mitad
  de la regla, y sin él no se puede juzgar si está bien escrita.
- **Los tipos de registro**, que son el mismo objeto visto de formas distintas.
- **Qué se publicó y cuándo**, con cuántos campos llevaba cada versión: es a lo
  que se vuelve cuando algo deja de encajar.

Y desde el 29-10-2026, seis cosas más que se podían hacer y no se podían mirar:

- **Qué formulario te toca, y por qué ése.** Con un diseño distinto por perfil,
  la pregunta que llega siempre es «¿por qué yo veo otra pantalla?». Aquí sale
  cuál se te aplica y el motivo — incluido el incómodo: «no hay ninguno marcado
  por defecto, así que sale el único que hay».
- **Lo que la inteligencia artificial entiende de este objeto, con el
  porcentaje delante.** Un campo que nadie ha descrito no entra en el contexto,
  y quien pregunte por él concluirá que el dato no existe. Los que faltan salen
  **por su nombre**: un porcentaje dice cuánto queda, una lista dice qué hacer
  esta tarde. Al lado, cuántos campos de este objeto salen en informes como
  dimensión o métrica, y cuántos se han dejado fuera por sensibles.
- **Qué campos ya justifican una columna de verdad**, con las escrituras que lo
  justifican. No es un botón grande a propósito: hacerlo bloquea a todas las
  empresas que comparten esa tabla, así que es la excepción y se decide con una
  medida, no con la sensación de que la lista va lenta.
- **Por qué estados pasa un registro**, y desde cuál se puede ir a cuál. Sin
  esto, cualquier estado salta a cualquier otro y el embudo que se mira cada
  lunes deja de significar nada. Los estados finales salen marcados.
- **Cuándo se puede retirar un campo renombrado.** Al renombrar, el viejo se
  queda puesto y recibiendo lo mismo, para que lo que ya llama por el nombre
  antiguo siga funcionando. Retirarlo no es cuestión de fecha: es que nadie lo
  escriba, y eso se ve aquí.
- **Llevarse esta configuración a otro entorno**, en un fichero. Lleva la
  configuración y **nunca los datos**: un paquete que arrastrara registros
  convertiría una subida a producción en una fuga, porque los datos de pruebas
  suelen ser copias a medio anonimizar de clientes reales.

Y los campos que se calculan salen **marcados** en la lista de campos: no se
teclean, y sin la marca alguien se pasa un rato buscando por qué «no se puede
rellenar».

### Campos que se calculan solos

Hay dos clases y conviene no confundirlas:

- Un **campo calculado** mira la propia ficha: «el importe con IVA», «los días
  desde el alta». Se escribe una fórmula al crear el campo —sumar, redondear,
  concatenar, decidir entre dos valores, días entre fechas— y el valor aparece en
  el listado, en la ficha y en la exportación, siempre el mismo.
- Un **agregado** mira lo que cuelga de la ficha: «cuántas cosas hay abiertas con
  este cliente», «cuándo fue la última actividad».

Tres cosas que notarás:

- **No se rellenan a mano.** Un campo calculado no se escribe: si alguien había
  guardado algo con ese nombre, lo que se ve es el cálculo.
- **Un campo vacío da vacío, no cero.** Tratarlo como cero haría que una media
  contara los registros que no tienen el dato, y esa es otra respuesta.
- **Si la fórmula está mal, el campo sale en blanco y la ficha se abre igual.** No
  se queda nadie sin poder trabajar porque una fórmula tenga una errata; quien la
  escribió lo ve al guardarla, porque entonces sí se rechaza.

---

### Exportar un listado

El botón **Exportar** está arriba de cada lista, al lado del selector de vista.
Baja lo que estás mirando a una hoja de cálculo, **con los filtros que tengas
puestos en ese momento** — exportar «todo» cuando en pantalla hay un recorte es
la forma de mandar un fichero con mucho más de lo que creías.

Sale sólo donde el sistema admite exportar: no hay botones que luego fallen. Tres cosas que importan:

- **Salen también vuestros campos propios**, no solo los que trae el producto. Lo
  que ves en la ficha es lo que llevará el fichero.
- **No sale lo que la pantalla te tapa.** Si tu perfil ve un teléfono con puntos,
  el fichero lo lleva con puntos. Una exportación no es una puerta de atrás.
- **Te puede pedir el código del segundo factor otra vez.** Exportar en masa está
  en la lista de operaciones delicadas: no es desconfianza, es que llevarse media
  base de clientes es lo que hace alguien que ya está dentro, y ahí el permiso no
  distingue. Si acabas de verificarte, no te lo vuelve a pedir.
- **Si la lista es muy larga, el fichero se corta y te lo dice.** Un fichero
  cortado en silencio es el que alguien manda creyendo que lleva todo. El aviso
  sale al bajarlo, con cuántas filas lleva: en una hoja de cálculo no cabe
  decirlo sin ensuciarla, y hace falta saberlo **antes** de abrirla, que es
  cuando todavía sirve de algo.

Cada fichero lleva además una **marca de origen** con el día y una referencia:
sirve para saber de dónde salió si aparece donde no debe. No lleva tu nombre en
claro.

---

## Usar el CRM desde fuera del CRM (sección 0.2)

Casi nada de lo que hace contecrm exige abrir su pantalla. Esto importa aunque no
seas quien programa:

- **Todo lo que ves se puede hacer también por API**, así que tu empresa puede
  meter el CRM dentro de su intranet, de su tienda o de su aplicación de campo sin
  pedir permiso a nadie ni esperar a una versión.
- **Y lo que hace la consola de administración también.** No hay acciones que solo
  existan pulsando un botón, y eso es comprobable: hay una comprobación automática
  que lo verifica en cada cambio.

Lo que te afecta en el día a día: si tu empresa ha construido su propia pantalla
para una parte —el portal del cliente, el alta desde la web, la aplicación del
técnico—, lo que pasa ahí dentro **es el mismo CRM**, con los mismos permisos y las
mismas validaciones. No hay una puerta de atrás donde las reglas no se cumplan.

---

## Saber si el sistema va bien (sección 0.6)

No hace falta ser administrador para ver si algo está pasando:

- **La página de estado** dice cómo está tu espacio ahora mismo, componente a
  componente. Un servicio que no contesta **no aparece en verde**: aparece como
  que no se sabe, que es distinto.
- **Lo que se prometió y lo que se cumplió** están uno al lado del otro. Si un mes
  no se cumplió el tiempo de respuesta, sale.
- **Y cuando algo está degradado se dice antes de que lo notes.** Lo primero que se
  pospone bajo carga son los recálculos y los informes pesados, no lo que estás
  escribiendo.

Si algo que esperabas no ha llegado —un correo, una sincronización, un informe
programado—, esa página es el primer sitio donde mirar antes de escribir a
soporte.

---

## Clientes, contactos y calidad del dato (sección 1.1)

La ficha de cuenta y la de contacto son el centro del CRM. Lo que conviene saber:

**Duplicados.** Al crear una cuenta o un contacto, el sistema avisa si se parece a
algo que ya existe, y con qué se parece: el identificador fiscal, el dominio de
correo, el nombre normalizado. Fusionar es una decisión tuya, se puede deshacer, y
**la ficha fusionada no se borra** — hay correos, documentos y sistemas externos
que apuntan a ella.

**Calidad.** Cada ficha tiene una puntuación de completitud y una lista de qué le
falta. No es decorativo: de ahí sale la cola de trabajo de calidad, donde las
excepciones tienen **responsable**, porque una lista sin dueño no la mira nadie.
Al cerrar una excepción hay que decir qué hiciste —corregido, no era un error, no
se puede arreglar— y si muchas se cierran como «no era un error», el sistema
señala que la regla está mal, no el dato.

**De dónde sale cada dato.** Si te preguntas por qué la dirección dice lo que
dice, la ficha te lo contesta: de qué sistema vino, cuándo cambió de verdad y
cuándo se confirmó por última vez. Y cuando dos sistemas dicen cosas distintas,
eso no se tira: aparece como discrepancia, porque normalmente significa que el
cliente se mudó y solo uno se enteró.

Esa respuesta depende de que alguien lo haya apuntado: la integración que trae el
maestro, el formulario que recoge el dato o la persona que lo corrige. Si de un
campo no hay nada apuntado, la ficha dice **eso** —que nadie puede explicar de
dónde sale— y no que esté al día. Y hay una acción aparte para **confirmar** que
un valor sigue siendo bueno sin cambiarlo: mueve la fecha de la última
comprobación y no la del cambio, porque confirmar no es cambiar y mezclar las dos
falsearía todos los informes de antigüedad.

**Lo que hay abierto con este cliente.** En el listado de cuentas verás cuántas
cosas siguen pendientes con cada una y cuándo fue la última actividad. Lo de «sin
actividad» no se cuenta como cero: no existe, y por eso no se cuela arriba cuando
ordenas por lo más reciente.

**Cuentas de particulares.** Un cliente que es una persona física se lleva en la
misma ficha con una marca. Los campos de empresa dejan de tener sentido y no se
exigen, y toda la ficha pasa a tratarse como dato personal.

**Estado financiero y métricas.** Si tu empresa ha conectado el ERP, en la ficha
verás crédito disponible, deuda vencida, facturación y margen — cada cosa **con la
fecha del dato**. Si ves un aviso de que la cifra es de hace tres semanas, hazle
caso: negociar con ella es negociar con un número que ya no existe.

**Cambio de empresa.** Cuando alguien cambia de trabajo, el CRM lo sospecha (un
correo que rebota, una firma nueva) y te lo propone; al confirmarlo **no se mueve
la ficha**, se crea una nueva enlazada. La historia de las reuniones y los correos
es de la cuenta antigua, y moverla dejaría a esa cuenta sin nada.

---

### De dónde sale cada dato de un cliente

Dentro de la ficha de un cliente, cuatro cosas que antes no se veían:

- **De qué grupo forma parte**, y en qué sentido: la jerarquía legal no es la
  comercial ni la de facturación, y una empresa puede depender de la matriz
  para firmar y de la delegación de aquí para que la atiendan. Se dice cuál se
  está viendo, porque si no la otra parece un error.
- **De dónde sale cada valor.** Qué sistema puso el teléfono, qué otro puso uno
  distinto y **cuál manda**. Es lo que contesta «¿por qué pone esto si el ERP
  dice otra cosa?», que hasta ahora había que preguntarle a quien montó la
  integración.
- **Qué lleva demasiado sin que nadie lo confirme**, con los días y el tope. Un
  dato viejo no se distingue de uno bueno mirándolo: el teléfono de hace cuatro
  años se ve igual que el de ayer.
- **Cómo está el cliente**, y antes del número, **si ese número sirve para
  decidir**. Una puntuación que no es fiable o que se midió hace tres meses no
  debería mover ninguna decisión, y enseñarla igual que una buena es lo que
  hace que al final nadie se crea ninguna.

### Qué ha cambiado en este registro

Al final de cada ficha hay un desplegable, **«Qué ha cambiado»**. Dentro está,
campo a campo, qué decía antes, qué dice ahora y **desde dónde se cambió**: la
pantalla, la API o una automatización.

Eso último es lo que suele zanjar la conversación. No es lo mismo que el precio
lo bajara una persona a que lo pisara la sincronización nocturna con el ERP, y
sin saberlo se acaba preguntando a quien no fue.

Se anotaba desde el primer día y no había dónde verlo. Va plegado y sólo se
pide al abrirlo, porque es para cuando hace falta, no para cada vez que se mira
una ficha.

Si sale vacío, te dice **cuál de las dos cosas es**: que este registro no se ha
tocado por ninguna vía que lo anote, o que esa parte del sistema no lleva ese
histórico. Con la lista vacía se ven igual, y no son lo mismo.

---

### Llamada, reunión, nota y correo: sólo donde hay alguien al otro lado

En la ficha de un cliente, un contacto, un proveedor, una oportunidad o un caso
tienes cuatro botones para apuntar lo que ha pasado sin salir de ahí.

Hasta el 29-10-2026 salían en **todas** las fichas, también en las que son
configuración: un plan de cuenta, un calendario laboral, una entrada de
papelera. Apuntarle una llamada a un calendario no quiere decir nada, y tener
botones que no significan nada hace dudar de los que sí.

Ahora salen en trece tipos de registro, y la regla es simple: **aquello de lo
que se habla con alguien**. Cliente, contacto, proveedor, partner, lead,
oportunidad, presupuesto, pedido, contrato, caso, orden de trabajo, devolución y
activo instalado. Si crees que falta alguno, se añade: es una lista del producto,
no una limitación técnica.

---

### Las listas largas de la ficha

Una ficha de cliente con mucho recorrido tiene cientos de cosas que enseñar, y
antes la página se hacía interminable: la línea de tiempo estiraba el alto, las
otras dos columnas se quedaban vacías debajo, y para volver a la cabecera había
que subir toda la página.

Ahora las tres columnas acaban a la misma altura y **cada recuadro se recorre
por dentro**. La línea de tiempo, los contactos, las oportunidades y los casos
tienen su propia barra dentro de su caja, así que se mira una lista sin mover
las demás ni perder de vista con quién se está. Cuántas filas se ven no es un
número fijo: es lo que quepa en su pantalla.

Cada panel lleva además **«Ver todas»**, que abre el listado completo ya
filtrado por este cliente — también los contactos, que viven dentro del módulo
de cuentas y abren directamente en su pestaña.

La misma regla vale en **todo el producto**, no sólo aquí: si una pantalla
enseña más de una lista, ninguna puede quedarse con la pantalla entera. Los
paneles de plataforma, las secciones del portal del cliente, los componentes de
un cuadro de mando, las tablas de apoyo de entornos, estado, rendimiento y
suite, y las columnas del tablero de ventas se recorren por dentro de su caja.
Antes, con cien trabajos en cola o un informe de quinientas filas, lo que iba
debajo quedaba a dos pantallas de distancia y no lo veía nadie.

Y las listas **dicen cuándo vienen recortadas**. Donde pone `20+` hay más de
veinte; donde pone `20` hay veinte. Antes las dos cosas se escribían igual, que
es como se acaba creyendo que un cliente tiene veinte casos cuando tiene
doscientos.

## Lo que pasa con cada cliente (sección 1.2)

Toda interacción —un correo, una llamada, una reunión, una nota— queda en la ficha
en un solo hilo. Lo relevante:

- **No hace falta teclearlo.** Si tienes el correo o el calendario conectados, las
  interacciones entran solas; si usas el marcador, la llamada se registra al
  colgar con su duración y su resultado.
- **Lo que sí escribes tú es qué se habló.** El sistema no inventa la nota:
  «contestada, 3 minutos» no es información comercial, y una frase automática
  parecería contenido sin serlo.
- **Lo privado no entra.** Un correo o una cita marcados como privados se saltan, y
  se cuentan aparte para que nadie crea que se sincronizó todo.

---

## Segmentos y audiencias (sección 2.1)

Un segmento es una lista de gente que cumple unas condiciones. Dos cosas que
cambian cómo se usan:

- **Un segmento se recalcula solo.** La lista de hoy no es la de la semana que
  viene, y comparar los resultados de dos envíos hechos en fechas distintas es
  comparar dos audiencias distintas. El sistema lo avisa.
- **Antes de mandar nada, el segmento te dice a cuánta gente afecta.** Ese número
  es el que hay que mirar: es lo que separa una campaña de un incidente.

Si tu empresa sincroniza audiencias con plataformas de anuncios, hay un límite
importante: **haber aceptado el boletín no es haber aceptado los anuncios**. Solo
sale quien tiene base legal para publicidad, y las listas pequeñas no salen —
porque una audiencia de veinte personas no anonimiza nada.

---

## Campañas y recorridos (sección 2.2)

Un recorrido es una secuencia: si pasa esto, espera tanto, manda aquello. Lo que
hay que tener en cuenta:

- **Se prueba en seco antes de lanzar**, y la prueba se hace **contra datos
  reales**: dice a cuánta gente afectaría hoy. Contra datos inventados, cualquier
  regla funciona.
- **Nadie entra dos veces sin querer.** El sistema controla la reentrada, que es el
  fallo clásico de los recorridos: un cliente recibiendo la misma bienvenida cada
  vez que actualiza su ficha.
- **Un cambio en el recorrido no afecta a quien ya está dentro.** Termina con la
  versión con la que entró, porque cambiarle el guion a la mitad lo deja en un
  paso que ya no existe.

---

## Cómo se manda cada cosa (sección 2.3)

Correo, SMS, WhatsApp, RCS, push, web, correo postal y telemarketing. Lo que
cambia entre ellos no es el botón:

- **El permiso es por canal.** Quien aceptó el correo no ha aceptado el SMS.
- **Cada canal tiene su forma de decir que no**: una palabra en SMS, la ventana de
  24 horas y las plantillas aprobadas en WhatsApp, el permiso del navegador en
  push. El CRM respeta la de cada uno.
- **El correo postal y el telemarketing no se pueden cancelar.** Una carta impresa
  ya está impresa: por eso la confirmación va antes, con el coste delante.
- **Y la hora de envío puede personalizarse**, pero solo cuando hay datos
  suficientes. Con dos interacciones, lo que se optimiza es el azar, y el sistema
  prefiere decírtelo a fingir que sabe.

---

## Contenido: biblioteca y aprobaciones (sección 2.4)

Todo lo que se manda al cliente sale de una pieza guardada: un texto, un folleto,
una imagen.

- **Cada activo dice para qué se puede usar y hasta cuándo.** Una foto con
  licencia para web no vale para una valla, y el folleto con los precios del año
  pasado deja de poder mandarse el día que caduca.
- **La versión nueva no borra la anterior**: lo que se mandó el martes se puede
  recuperar.
- **Y nada se publica sin que una persona lo apruebe**, con un aprobador concreto
  por paso. Rechazar exige decir qué hay que cambiar; y al aprobar se registra si
  miraste **qué cambió** respecto de la versión anterior, porque revisarlo todo
  entero cada vez es como se acaba aprobando sin leer.

**Aquí también están las supresiones**: a quién no se le puede escribir, pase lo
que pase. Van con las renovaciones de opt-in y las categorías de preferencia
porque son la misma pregunta —qué ha consentido cada persona—, y es donde se
busca cuando alguien pregunta por qué no le ha llegado un envío.

Hasta el 29-10-2026 salían **también** en Segmentación. Era la misma lista en
dos sitios, no dos listas, así que daba igual desde cuál se tocara; pero tener
el mismo registro en dos pantallas es cómo se acaba mirando la que no toca y
creyendo que falta algo. Se quedan aquí.

---

## Oportunidades y pipeline (sección 3.1)

Una oportunidad es una venta en marcha. Lo que el CRM te va a pedir y por qué:

- **Fecha e importe, siempre.** Una oportunidad sin fecha no entra en ninguna
  previsión y no la mira nadie; sin importe, no se puede priorizar. No es
  burocracia: es lo que hace que el pipeline signifique algo.
- **Las etapas van hacia adelante**, y retroceder deja constancia. Un pipeline en
  el que todo el mundo mueve etapas libremente no predice nada.
- **Lo recurrente se separa de lo puntual.** Si vendes suscripciones, el sistema
  distingue lo que se repite de lo que se cobra una vez, y calcula ARR y MRR solo
  con lo primero. Meter la implantación dentro infla el número con el que tu
  empresa se valora.
- **El calendario de ingreso.** Una venta que se cobra en doce meses no es un mes
  bueno: son doce meses decentes. Eso se reparte y aparece en la previsión de caja,
  que es distinta de la previsión de cierre.
- **El reparto entre comerciales suma 100.** Si sois dos al 60 %, no se guarda: las
  comisiones cuadrarían hacia arriba y el descuadre aparece tres meses después. El
  apoyo que no resta al titular se anota aparte, como *overlay*.
- **Quién decide.** En la oportunidad se anota el papel de cada persona del
  cliente: quién firma, quién paga, quién recomienda, quién puede bloquear. Lo que
  más te va a servir es la lista de **con quién no has hablado todavía**: un
  económico sin contactar es la razón más habitual de que un cierre seguro se caiga
  la última semana.
- **Y las oportunidades se relacionan entre sí** diciendo qué son: renovación,
  ampliación, venta cruzada o sustitución. Una renovación **no cuenta como ingreso
  nuevo**, y contarla así duplicaría el crecimiento del trimestre.

### Abrir una oportunidad

Hasta el 29-10-2026, al pinchar una fila salía un volcado de campos. Con eso
delante no se contesta «¿cómo vamos con esta venta?», que es para lo que se
abre. Ahora dentro está:

- **Qué se vende**, línea a línea, y **lo que vale**: ARR, MRR, TCV y ACV. El
  cálculo lo hace el sistema, no la pantalla, y dice **qué ha dejado fuera**:
  un «ARR 120.000» sin advertir que la implantación no cuenta es el número que
  acaba en una valoración y que nadie vuelve a mirar.
- **Quién decide**, y sobre todo **a quién no se ha visto**. Esa segunda lista
  es la que sirve.
- **Quién se lleva la comisión**, con el total repartido y un aviso en rojo si
  no cuadra. Esto **no se podía ver antes**: se declaraba el reparto y no había
  forma de comprobarlo hasta que llegaba la liquidación. Lo mismo con **de
  dónde viene esta venta y qué sale de ella** — y se dice de qué lado está,
  porque «renovación» no es lo mismo si ésta es la que se renueva o la que
  renueva a otra.
- **Qué se ha movido**: cada cambio de importe o de fecha, con cuántos días se
  deslizó y **por qué**. Si se movió sin motivo escrito, lo dice: un
  deslizamiento sin explicación no se puede discutir en un comité, y decirlo es
  lo que hace que la próxima vez se escriba.

Una venta que ha cambiado tres veces de fecha no es la misma que una que nunca
se movió, aunque hoy tengan el mismo importe y la misma etapa.

**Lo que ves por tu territorio.** Además de lo tuyo y de lo que te compartan, ves
las cuentas de los territorios que trabajas — como responsable o como miembro. Dos
cosas que conviene saber: si te acaban de añadir a un territorio, lo verás en
cuanto el mapa se vuelva a publicar, que ocurre solo al añadirte; y si te sacan,
dejas de verlo **ese mismo día**, no cuando alguien se acuerde de revisarlo.

---

### Qué está esperando una firma

En **Ventas › Pendiente de firma** está lo que de verdad se pregunta al cerrar
un trimestre: qué contratos están parados, desde cuándo y **por quién**.

Lo que lleva más tiempo esperando sale primero —un listado por fecha de
creación pone arriba lo recién mandado, que es lo único que no hay que tocar— y
cada sobre dice a quién le toca firmar, por su nombre: «2 de 3 firmado» no dice
a quién hay que llamar, que es lo único que vas a hacer con ese dato.

Y se distingue **«nadie lo ha abierto»** de «abierto y sin firmar». No es un
matiz: el primero es un correo que no llegó y se reenvía; el segundo es una
decisión que no se toma y se resuelve con una llamada. Mezclarlos hace perder
el tiempo en la mitad de los casos.

Si no hay nada esperando, lo dice así: «no hay nada en curso», no «todo
firmado». Un verde vacío se lee igual que uno ganado y no es lo mismo.

Los sobres en sí, con sus firmantes y su evidencia, están en
**Administrar › Operación › Sobres de firma**, y desde cada uno se puede
mandar, recordar, cancelar o archivar el documento firmado.

---

## Previsión y objetivos (sección 3.2)

La previsión no es la suma del pipeline. Lo que verás:

- **Categorías de previsión** —comprometido, mejor caso, pipeline— que las pone
  una persona y no la etapa. Deducirlas de la etapa hace que la previsión suba
  sola cuando alguien mueve una tarjeta.
- **Cuotas por persona, equipo y periodo**, y el avance frente a ellas.
- **El histórico de la previsión no se reescribe.** Lo que dijiste en marzo sigue
  diciendo lo que dijiste en marzo; si no, no se puede aprender nada de lo que
  falló.
- **Y las comisiones**: si tu empresa usa un motor externo, el CRM manda los hechos
  y **enseña el número que calcula ese motor**, no otro. Una cifra distinta de la
  que vas a cobrar haría que no te creyeras ninguna de las dos.

### Tu liquidación de comisión

En **Canal › Liquidaciones**, cada fila se abre. Dentro no está el total otra
vez: está **de dónde sale cada euro**, con la base sobre la que se calculó y el
porcentaje que se aplicó. Una comisión que no se puede desglosar no se la cree
nadie, y entonces se lleva en una hoja de cálculo aparte que nunca cuadra con
la del CRM.

Tres cosas que conviene mirar:

- **Si te han recortado por el tope**, sale arriba y en color. No es lo mismo
  haber vendido menos que haber llegado al techo del plan: lo primero no se
  negocia y lo segundo sí.
- **Las reversiones van marcadas.** Una línea en negativo es casi siempre una
  devolución o una baja dentro de plazo, no un error de cálculo, y se dice de
  cuál viene.
- **Si has reclamado algo**, sale con su estado. Mientras no tenga resolución
  escrita, lo dice: una reclamación que se da por hablada vuelve el trimestre
  siguiente.

**No se puede editar a mano**, y es a propósito: el valor de una liquidación es
que cada euro tiene su porqué. Si hay que corregirla se revierte y se vuelve a
liquidar, y esa corrección queda como una línea más con su explicación.

### El mapa de territorios

En **Ventas › Territorios**. Lo que se hace con un mapa de territorios no es
mirarlo: es cambiarlo sin romper el año de nadie. Publicar y ver qué pasa
significa que cientos de cuentas cambian de dueño el lunes por la mañana, y
deshacerlo no devuelve las conversaciones que ya se tuvieron.

- **Simula antes de publicar**, contra tus cuentas de verdad y sin escribir
  nada. Lo que importa del resultado no es cuántas cambian: es cuántas se
  quedarían **sin territorio** —eso no es un hueco que se rellene solo— y
  cuántas quedarían en **solape**, que es cuando dos territorios tienen la
  misma prioridad y acaba decidiendo el orden alfabético. Nadie busca un solape
  hasta que dos comerciales discuten por una cuenta.
- **Las prioridades repetidas se señalan en la lista**, que es donde se
  arreglan.
- **Las cuentas sacadas de su territorio**, con su motivo y con **cuándo dejan
  de estarlo**. Esto no se podía ver antes: se declaraba la excepción y no
  había forma de saber cuáles había. Y caducan — una cuenta sacada «hasta
  marzo» vuelve sola en marzo sin avisar a nadie, así que las que vencen en un
  mes o menos salen marcadas.
- **Las cuotas, con su prorrateo.** Quien entra el día 20 no tiene la cuota
  entera, y medirle contra ella es garantizarle que no la cumple. Al lado sale
  el objetivo del plan, el que está en la hoja de alguien: sin los dos
  delante, uno de los dos parece equivocado.

### Abrir un periodo

En **Previsión › Periodos**, cada fila se abre. Un periodo no es una línea de
una tabla: es el número que alguien lleva a un comité, y dentro está lo que
hace falta para defenderlo.

- **El total, con el aviso pegado.** Si alguna oportunidad no se ha podido
  convertir a la moneda del periodo, **no se cuenta como cero**: se dice
  cuántas son y que no están sumadas. Un total al que le faltan importes en
  silencio es peor que uno que avisa, porque nadie lo cuestiona.
- **Quién ha tocado el número y por qué.** Cada ajuste con su autor, su importe
  antes y después, y su motivo.
- **Y si esos ajustes acertaron.** Éste es el panel incómodo, y está puesto a
  propósito: compara el real con lo que se había calculado **sin tocar nada** y
  con lo ajustado. Si ajustar alejó del real, lo dice en rojo. Sin esta
  comparación nadie se entera nunca, porque al cerrar el trimestre se mira el
  real contra el objetivo, no contra lo que se habría previsto sin ajustes.
- **Cómo íbamos antes**, con las fotos congeladas del periodo y la fecha de
  cada una.
- **Cuánto se ha movido**, y aparte **cuántas ventas se han empujado más de una
  vez**. No es lo mismo: una fecha que se mueve dos trimestres seguidos no es
  un retraso, es una venta que no existe, y en el total se confunde con la que
  se retrasó una semana.
- **Por dónde entra**: el desglose por producto, familia o tipo de ingreso. Si
  algún grupo se queda fuera por un tipo de cambio que falta, se dice — si no,
  se leería como que ese grupo no vendió nada.

---

## Prospección y trabajo diario (sección 3.3)

- **Cadencias**: secuencias de correo, llamada y tarea con un ritmo definido. Se
  paran solas cuando el cliente responde — seguir la secuencia después de una
  respuesta es lo que hace que la gente bloquee al remitente.
- **Presupuestos y precios**: el precio sale del motor de tarifas y **se explica**.
  Un precio que no se puede explicar se acaba negociando a la baja delante del
  cliente.
- **El margen, si tu empresa ha cargado los costes.** Aprobar por porcentaje de
  descuento es aprobar a ciegas: un 5 % sobre algo que se compra caro pierde
  dinero. Y el coste **se congela al ofertar**: si la tarifa del proveedor sube
  después, se te avisa y la oferta no se reescribe sola.
- **El marcador**: llamar desde la ficha, y al colgar la llamada se registra sola.
  Lo que tienes que escribir tú es qué se habló.
- **El plan conjunto con el cliente**: los pasos acordados con fechas, con una
  condición — **tiene que haber pasos suyos**. Un plan donde todo es nuestro es una
  lista de seguimiento interna, y lo valioso es justo lo incómodo: que el cliente
  ponga fecha a su parte.
- **Y la revisión de oportunidad**, que pregunta lo que nadie pregunta: qué puede
  salir mal y qué falta por saber. Queda registrada para poder compararla con lo
  que pasó — si lo que se revisa al 80 % se gana la mitad de las veces, ese 80 % no
  significa 80 %.

---

## Partners y canal indirecto (sección 3.4)

Si vendes a través de terceros: registro de oportunidad para evitar que dos
partners peleen por el mismo cliente, niveles y certificaciones, precios propios de
canal, y un portal donde ellos ven **lo suyo y solo lo suyo**. El registro de
oportunidad tiene caducidad: una reserva eterna bloquea una cuenta para siempre.

---

## Casos y atención al cliente (sección 4.1)

Un caso es una petición de un cliente con un compromiso de tiempo detrás.

- **El reloj del SLA se para cuando la pelota está en el tejado del cliente**, y se
  reanuda cuando contesta. Sin eso, el indicador castiga al agente por lo que tarda
  el cliente.
- **Los calendarios laborales y los festivos cuentan.** Un caso abierto el viernes
  a las siete no lleva 60 horas de retraso el lunes a las nueve.
- **Reabrir un caso cerrado tiene plazo.** Pasado, se abre uno nuevo enlazado:
  reabrir el de hace ocho meses falsearía los indicadores del periodo en que se
  cerró, que ya están en un informe que alguien miró.
- **La cola no es una lista por orden de llegada**: se ordena por lo que está más
  cerca de incumplir, y se dice por qué está donde está.

### Abrir un caso

La bandeja dice qué atender primero; abrir el caso es otra cosa. Dentro está lo
que hace falta para atenderlo:

- **Con qué tiene que ver**: el cliente, el contacto, el producto, el activo
  instalado, el contrato y el pedido. Hasta el 29-10-2026 esto se perdía al
  abrir el caso aunque se hubiera dicho al crearlo, y había que volver a
  preguntárselo al cliente. Lo que no esté puesto no sale: una lista de guiones
  hace creer que faltan datos cuando lo que pasa es que ese caso no es de un
  pedido.
- **El reloj, con los dos plazos por separado.** Incumplir la primera respuesta
  y incumplir la resolución no son lo mismo: lo primero todavía se puede salvar
  y lo segundo hay que explicarlo. Y si el reloj está parado esperando al
  cliente, se dice con cuántas horas — un caso que lleva quince horas esperando
  una respuesta no lleva quince horas sin atenderse.
- **De qué cuelga y qué cuelga de él**, y de cuál es duplicado. Un duplicado
  que no dice de cuál lo es obliga a buscarlo, y mientras tanto se contesta dos
  veces al mismo cliente.
- **Cómo acabó.** Con el motivo, la resolución y —lo que más importa— **si está
  pendiente de que el cliente lo dé por bueno**: un caso cerrado por el agente
  y a falta del visto bueno **no está cerrado**, aunque en una lista se vea
  igual. Y si se ha reabierto, cuántas veces: un caso cerrado tres veces no es
  un caso resuelto.
- **Y todo lo que le ha pasado, en orden**, que es el rastro de las reaperturas
  y de los cambios de nivel.
- **Por qué está en esta cola.** Qué regla lo mandó aquí, con qué estrategia y
  por qué motivo — y cuántas reglas se miraron antes. No es lo mismo que
  coincidiera la primera que que no coincidiera ninguna y cayera a la cola por
  defecto: lo segundo quiere decir que no hay ninguna regla que cubra este tipo
  de caso.
- **Qué derecho lo cubre y cuánto queda**, con las horas y los casos: salen los
  dos aunque sólo uno esté limitado, porque si no no se sabe si el otro no se
  cuenta o es que nadie ha gastado. Y con la fecha de caducidad al lado: un
  derecho con doscientas horas libres que vence el viernes es tan inservible
  como uno agotado.

---

## Por dónde entran los clientes (sección 4.2)

Correo, formulario, portal, chat, redes sociales, teléfono y API. Todo cae en el
mismo hilo del mismo caso.

- **El correo no hace bucles**: una respuesta automática que contesta a otra
  respuesta automática es un clásico, y está controlado.
- **En redes sociales, lo público es distinto.** Una queja con testigos se contesta
  en el hilo diciendo que se está atendiendo, y el detalle se sigue por privado —
  pedir un número de pedido delante de todo el mundo es mala respuesta y un
  problema de privacidad a la vez. Y lo que se publica en nombre de la marca **lo
  escribe una persona**.
- **Al teléfono**, si suena y el número está en el CRM, la ficha se abre sola; si
  hay tres fichas con ese número, se enseñan las tres en vez de adivinar. Lo que el
  cliente tecleó en el IVR llega contigo: no se lo vuelvas a preguntar.
- **Y el asistente de voz** te pasa la llamada cuando no entiende, con todo lo que
  ya se habló. Hay cosas que no hace nunca: cancelar un contrato o cambiar unos
  datos bancarios por voz, que es el fraude telefónico más común que existe.

---

## Conocimiento y autoservicio (sección 4.3)

- **Artículos con vigencia y aprobación**: lo que caduca deja de proponerse.
- **Sugerencias en el caso**: mientras escribes, el CRM te pone delante casos
  parecidos ya resueltos y el artículo que los explica, **cada uno con su cita**.
  Si no se puede abrir la fuente, no se enseña: responder con un párrafo que no se
  puede comprobar es como se propagan las respuestas equivocadas.
- **Y lo parecido no siempre es lo aplicable**: se te dice en qué coincide y en qué
  no (producto, versión, contrato). Lo decides tú.

---

## Servicio de campo y activos (sección 4.4)

### El histórico del almacén móvil

En **Movimientos de almacén** está cada entrada y salida del furgón, con quién,
qué, cuánto y **por qué**. Un almacén sin histórico no se puede cuadrar: cuando
falta una pieza, la pregunta es quién se la llevó y cuándo.

Los movimientos que **dejaron la existencia en negativo** se cuentan aparte: es
la señal de que el inventario y la realidad dejaron de coincidir, y a partir de
ahí todo lo que se planifique con esas existencias se planifica sobre un número
inventado.


Órdenes de trabajo, técnicos, rutas y equipos instalados en casa del cliente.
Cuatro cosas que notarás:

- La planificación tiene en cuenta **el tiempo de desplazamiento**, no solo la
  duración del trabajo.
- Un técnico sin zonas asignadas cubre todas: es deliberado, para que nadie se
  quede sin asignar por un dato que falta.
- **La garantía dice qué cubre y qué no** — casi ninguna cubre el desplazamiento, y
  esa es la conversación incómoda que conviene tener antes de ir.
- **El siguiente mantenimiento se cuenta desde el día en que se hizo**, no desde
  el día en que tocaba. Si una revisión mensual se atrasa dos semanas, la
  siguiente es un mes después de la que se hizo — si se contara desde la fecha
  prevista, nacería ya vencida y el plan arrastraría el retraso para siempre.
  Ese día es el del cliente, no el del servidor.
- Y el histórico del equipo instalado viaja con él aunque cambie de cliente.

---

## Devoluciones y postventa (sección 4.5)

Devoluciones y sustituciones con su propio flujo, enlazadas al pedido y al activo.
Lo que se registra es qué volvió, por qué y en qué estado: sin el motivo, el mismo
producto vuelve a fallar y nadie puede demostrar que es un patrón.

---

## Informes y cuadros de mando (sección 5.1)

### Qué cuesta cada informe

En **Análisis → Ejecuciones de informe** está cada vez que se corrió uno, con
lo que tardó, cuántas filas sacó y si se cortó. Se anotaba desde el primer día
y no había dónde verlo.

Dos cosas que se enseñan a propósito: **el peor caso al lado de la media**
—porque la media esconde justo lo que molesta, el informe que tarda dos minutos
una vez al día— y **las que salieron truncadas**, que es lo que convierte un
informe en una decisión tomada con la mitad de los datos. Sin ninguna ejecución
registrada no se dice que el informe sea rápido: se dice que no consta ninguna.


- **Cualquiera puede construir un informe** sin pedirlo a nadie, y solo verá dentro
  lo que puede ver.
- **Un informe programado se manda con lo que ve quien lo recibe**, no con lo que
  veía quien lo creó.
- **Y los números dicen de cuándo son.** Un panel sin fecha de actualización se lee
  como si fuera de ahora mismo, y así es como se toman decisiones con datos de
  antes de ayer.
- Si algo no se puede calcular, el informe lo dice — **una celda vacía y un cero
  significan cosas distintas** y aquí no se confunden.

---

## Lo que hace la inteligencia artificial (sección 5.2)

Todo lo que propone la IA en contecrm cumple tres reglas:

1. **Se explica.** Una puntuación viene con los factores que la empujan hacia
   arriba y hacia abajo. Un número sin porqué se mira una vez.
2. **No actúa sola en lo que importa.** Redacta borradores, propone tareas, resume
   reuniones y sugiere respuestas — y todo eso lo confirma una persona.
3. **Dice cuándo no sabe.** Sin datos suficientes no inventa una puntuación: te
   dice que no se puede medir, que es distinto de que vaya mal.

Además: lo que se transcribe de una llamada **no es un acta** —el reconocimiento
confunde nombres y cifras—, y grabar exige haber avisado. Si algo se propone a
partir de una transcripción poco fiable, no se propone.

### Hace falta un modelo conectado, y se elige a conciencia

Nada de esto funciona hasta que tu instalación declara **a qué modelo llamar**.
Se hace en **Inteligencia → Proveedores**: la dirección, de qué familia es, qué
modelos ofrece y **para qué sirve cada uno** —redactar, resumir, extraer,
traducir, consultar, clasificar—. Lo que no se declare, no se le pide.

Dos cosas que conviene saber antes de elegir proveedor:

- **Lo que cuesta se mide, y por eso el presupuesto corta de verdad.** El coste
  por millón de tokens se declara al dar de alta el modelo, y sin él el tope
  mensual no frena nada. Con los modelos que *razonan* hay una trampa: gastan
  tokens pensando antes de contestar, y eso se factura. Desde el 29-10-2026 se
  cuentan; antes no, y una llamada medida gastaba 979 tokens pensando para
  escribir una respuesta de 40 — el coste salía veinticinco veces por debajo
  del real.
- **El «que no entrenen con lo nuestro» es una casilla con consecuencias.** Por
  defecto tu empresa lo exige, y un proveedor que no pueda garantizarlo por
  petición **no se usa**: la pantalla dice cuál se ha descartado y por qué, en
  vez de llamar igual y callárselo. Hay modelos muy buenos que sólo lo ofrecen
  por contrato, no por petición; usarlos obliga a bajar esa exigencia a
  propósito, y queda escrito quién lo hizo.

Si no hay ninguno declarado, las pantallas de IA lo dicen y mandan a
configurarlo. Hasta el 29-10-2026 venían tres de ejemplo que parecían
configurados y fallaban al primer uso; ya no.

### Cuando un campo se ve tapado, se dice

Hay campos que, según tu rol, no se ven en claro: salen con puntos
—«··············tora»—. Eso **no es un error de datos**: es la política de tu
empresa sobre qué ve cada rol.

Hasta el 29-10-2026 no se avisaba, y ahí estaba el problema: un valor con puntos
ocupa el sitio del nombre y tiene su forma, así que alguien lo copia creyendo
que es el dato. Se descubrió con Nexus, que preguntó por tres cuentas y contestó
tan tranquilo que se llamaban «··············tora», «··cosa» y
«·············elta».

Ahora la pantalla lo dice con una frase distinta de la de siempre, y por una
razón: **«no puedes ver este campo» y «este campo se ve tapado» no son lo
mismo**. El primero no viene y se ve el hueco; el segundo viene y engaña. Y
Nexus también lo recibe, así que ahora te dice que no puede ver ese nombre en
vez de leerte los puntos.

### Cómo se entra en tu empresa

En **Seguridad** está ahora, en un sitio, cómo se entra: si tu empresa obliga a
pasar por su proveedor de identidad o si la contraseña local sigue valiendo
—y si sigue valiendo, quien se va del directorio puede seguir entrando por esa
puerta—, con qué proveedor y para qué dominios de correo, si da de alta solo a
quien entra por primera vez, y si el aprovisionamiento automático está activo.

Tres cosas que conviene mirar de vez en cuando y antes no se podían:

- **Si se aceptan entradas que empiezan en el proveedor.** Vienen apagadas por
  un motivo: sin una petición nuestra a la que atarlas, una autorización robada
  se puede reenviar. Si está encendido, que sea porque alguien lo decidió.
- **Si el segundo factor se lo deja al proveedor.** Está bien —pedirlo dos
  veces enseña a saltárselo— pero hay que saber que aquí ya no se pide.
- **Quién se salta la contraseña.** Si el acceso por contraseña está cortado,
  suele haber una o dos cuentas de rescate para el día que el proveedor falle
  un sábado. Se enseñan **por su nombre**: una excepción que no se ve deja de
  ser una excepción.

Y en tus sesiones se dice cuáles **no se cerrarán en el proveedor** al salir.
Cerrar sólo aquí deja la sesión del proveedor viva, y volver a entrar no pide
credenciales: para ti, el botón de salir no habría hecho nada.

---

### Cuentas con las que hace tiempo que no se habla

En **Clientes** puedes pedir las cuentas que llevan N días sin contacto. El
corte por defecto lo decide tu empresa en la configuración, no nosotros.

Dos cosas que conviene saber: **las cuentas con las que no se ha hablado nunca
salen también** —son las que más importan, y dejarlas fuera por no tener fecha
las escondería justo en la lista que existe para encontrarlas— y la fecha que se
mira es la de la última actividad registrada, así que una llamada que nadie
apuntó no cuenta.

Nexus también sabe contestarlo: «qué cuentas llevan más de dos meses sin
contacto» te da los nombres y te dice con qué lo ha averiguado.

---

### «¿Y cuántas son?»

Hasta el 29-10-2026, a «cuántas cuentas no tienen web» Nexus contestaba que
podía enseñártelas pero no contarlas. Era verdad: los listados devolvían una
página y nunca el total, así que contar significaba ir pasando páginas.

Ahora el total se puede pedir, y **con los filtros que tengas puestos**: si
estás mirando sólo las activas, el número es el de las activas. Nexus lo usa
cuando la pregunta es de cuántas, y contesta con la cifra.

Dos cosas que conviene saber:

- **Es lo que tú ves, no lo que hay.** Si hay cuentas que tu perfil no alcanza,
  no entran en el número. Dos personas pueden ver cifras distintas de la misma
  lista, y eso es lo correcto: la otra respuesta sería contarte registros que no
  puedes abrir.
- **No sale solo, se pide.** Contar de verdad obliga a recorrer la tabla entera,
  y hacerlo en cada pantalla por un número que casi nadie mira haría todo el
  producto más lento. Para saber si hay más de lo que ves no hace falta: las
  listas ya avisan cuando vienen recortadas.

---

### Nexus

En la barra de arriba, al lado del chat, hay un icono: **Nexus**. Ahí se
escribe lo que necesitas —«qué cuentas llevan dos meses sin contacto y tienen una
oportunidad abierta»— y el CRM te contesta **enseñándote antes qué haría para
averiguarlo**.

Cómo funciona, y por qué está hecho así:

1. **Primero sale el plan, no el resultado.** El botón se llama «preparar el
   plan» porque eso es lo que hace: no toca nada todavía.
2. **Cada paso lleva su riesgo al lado.** «Lectura» sólo mira; «escritura» cambia
   algo; «destructivo» borra. Lo ves antes de autorizar, no después.
3. **Tú das el siguiente paso.** El botón va avanzando y **se para solo** en
   cuanto hay algo que necesita que una persona lo autorice. Ahí decides:
   «autorizar» o «no lo hagas».
4. **Si el agente está pensando, lo dice.** Hay agentes que deciden sobre la
   marcha: hacen una cosa, miran el resultado y entonces deciden la siguiente.
   Cuando eso pasa, la pantalla te cuenta qué ha decidido y por qué.
5. **Al final puedes deshacer** lo que haya hecho. Y antes de ofrecerte el botón
   te dice **qué no se puede deshacer**: un correo enviado no se des-envía, y
   preferimos decírtelo a que lo descubras pulsando.

Si te dice que no hay ningún agente al que preguntar, es que todavía no se ha
declarado ninguno: se hace en Administración → Agentes autónomos, eligiendo qué
puede hacer y cuándo tiene que esperarte.

**Y si sólo hay uno declarado, no te pregunta cuál.** Hasta el 29-10-2026 había
que elegirlo en un desplegable de un solo elemento, con el botón de preparar el
plan bloqueado hasta hacerlo: eso no es una decisión, es un paso obligatorio
para llegar a la que sí lo es. Ahora se elige solo y la pantalla **dice quién
responde**, que no es lo mismo que ocultarlo: el agente decide qué herramientas
usa y hasta dónde llega, así que saber cuál es forma parte de poder no fiarte de
la respuesta. En cuanto haya dos, vuelve a preguntarte.

---

## Correo, calendario y el resto de tus herramientas (sección 6.1)

El CRM se conecta con la suite que ya usas —Microsoft 365, Google o la que sea— y
lo hace igual con todas: lo que cambia es configuración, no un módulo por casa.

- **Lo autorizas tú, recurso a recurso.** Ni tu jefe ni el administrador pueden
  conectar tu buzón por ti. Y cuando lo revocas, deja de entrar nada más — lo que
  ya entró se queda, porque son actividades de la empresa.
- **No se sincroniza todo**, sino lo que tiene que ver con el CRM: por defecto,
  correos con alguien que está en el CRM y reuniones con asistentes externos. Lo
  privado nunca, y se cuenta aparte para que sepas que hubo algo que no entró.
- **Los conflictos se avisan, no se resuelven a la brava.** Si mueves una reunión
  en el móvil y otra persona la mueve en el CRM, gana lo más reciente y, si los dos
  cambiaron, lo decide una persona. Pisar el calendario de alguien es la forma más
  rápida de que desconecte esto.
- **Contactos, tareas y notas.** Los contactos suben solo los que tienen que ver
  contigo; tu agenda personal no entra. Las tareas van en los dos sentidos —cerrar
  en un sitio cierra en el otro— pero borrarlas en tu móvil **no borra** la
  actividad del CRM que otros han comentado. Y las notas y los ficheros se
  **enlazan**, no se copian: así siguen siendo tuyos y se borran donde están.
- **Reuniones en línea**: el enlace se crea cuando la reunión está confirmada, no
  al proponer la hora — si no, quedan salas abiertas de reuniones que no cuajaron.
- **Y si algo deja de llegar, se ve.** El panel de conexiones dice qué lleva sin
  sincronizar, desde cuándo y por qué; lo que no se ha medido no cuenta como bueno.

También hay complemento para el cliente de correo (ver y registrar sin salir de
él), chat corporativo conectado, documentos generados desde plantillas y firma
electrónica desde cualquier registro.

---

### Qué sabe hacer la suite que tienes conectada (sección 6.1)

En **Operación → Suite** está, además de si el correo y el calendario de cada
uno están entrando, **qué hace exactamente** la suite que tienes conectada. Era
lo que no se podía mirar: la conexión funcionaba o no funcionaba, y por qué era
cosa de abrir la base de datos.

Lo que ves ahora, y para qué sirve cada cosa:

- **Qué recursos trae y en qué sentido.** «Leer» el calendario de alguien y
  «leer y escribir» no son lo mismo, y es la línea que conviene revisar de vez
  en cuando. Un perfil de suite es configuración, no un programa: lo único que
  distingue a dos proveedores es lo que ahí se declara.
- **Cómo se reanuda.** Una sincronización que tarda puede estar avanzando o
  repitiéndose, y sin verlo no hay forma de saber cuál.
- **Si trae datos de terceros**, con el aviso del propio sistema: una agenda
  personal tiene al médico y a la familia, y subirla es tratar datos de gente
  que no es ni cliente ni usuaria.
- **Qué entra de verdad y qué no entra nunca.** La política de la empresa y la
  preferencia de cada persona, juntas — la segunda sólo puede estrechar la
  primera, nunca abrirla. Lo marcado como privado no entra en ningún caso.
- **Quién ha conectado su cuenta y con qué permisos.** Si alguno está sin
  refresco se avisa: ése dejará de entrar el día que caduque, y nadie lo sabrá
  hasta que falte el correo de la semana pasada.
- Y al lado de cada uno, **«¿se puede ya?»**: la comprobación que va antes de
  cada vuelta. Si falta una autorización lo dice con esas palabras, en vez de
  reintentar contra el límite del proveedor hasta que corta.

Debajo, tres preguntas que se hacen en un momento concreto:

| Pregunta | Cuándo se hace |
|---|---|
| **¿De quién es esta cuenta?** | Antes de atribuir una conversación. Resuelve alias y buzones compartidos, y **no adivina**: adivinar le cuelga a alguien algo que no es suyo |
| **¿Cuándo está libre?** | Antes de proponer una hora. Se lee **si está ocupado, no de qué**: el asunto puede ser «revisión médica» y para proponer una hora no hace falta |
| **¿Qué entraría de este fichero?** | Antes de importar. Formatos estándar, con el recuento delante: deshacer una importación a mano no lo hace nadie |

---

## Trabajar en equipo y desde el móvil (sección 6.2)

- **Comentarios y menciones** en los registros, con aviso a quien mencionas.
- **Invitados externos** con acceso acotado y temporal: un cliente o un partner
  puede ver una cosa concreta durante un tiempo concreto.
- **Móvil y sin cobertura.** Puedes anotar visitas sin red; se suben al recuperarla.
  Lo que hay que saber: **nada se descarta**. Si algo no se puede subir, se queda en
  la cola y se avisa —una cola que tira lo que falla convierte un problema de red en
  una pérdida de datos que descubres semanas después—. Y las notificaciones no
  llevan el dato dentro: llegan a una pantalla bloqueada que puede ver cualquiera.

### El chat de equipo

Está en la barra de arriba. Lo que lo distingue de poner un enlace a otra
herramienta es que **una conversación puede colgar de un registro**: la de
*esta* oportunidad se abre desde su ficha, con el importe y la etapa al lado.
Media conversación de un CRM ocurre fuera de él, y lo que queda dentro es una
etapa cambiada sin el porqué; a los seis meses nadie sabe por qué se bajó aquel
precio.

Lo que se puede hacer, además de escribir:

- **Buscar**, y sólo dentro de las conversaciones en las que estás. A los seis
  meses nadie recuerda en qué canal se dijo algo, que es justo lo que hace falta
  encontrar. No se busca en canales donde no estás: eso sería una puerta de
  atrás.
- **Ver quién está**, con **desde cuándo no se le ve**. No es un adorno: la
  pregunta real es si esperar respuesta o levantar el teléfono, y un punto verde
  no la contesta.
- **Ver qué decía antes** un mensaje editado. Donde pone «editado» se pulsa y
  sale la versión anterior. Lo corregido se ve corregido, no reescrito: una
  conversación en la que se puede cambiar lo dicho sin rastro no sirve para
  explicar una decisión, y explicarla es la única razón de guardarla.
- **Saber quién va a leerlo** antes de escribir. Las personas de la conversación
  salen en la cabecera.

Y dos cosas que pasan solas:

- **Lo nuevo llega sin recargar.** Un chat que hay que recargar no es un chat.
- **Y si te quedas sin conexión, al volver llega lo que te perdiste.** Hasta el
  29-10-2026 no era así: al cerrar la tapa del portátil, la conversación se
  reanudaba «desde ahora» y lo escrito durante el corte no aparecía nunca. No
  daba ningún error — simplemente faltaban mensajes, y quien miraba creía que
  nadie había escrito.

---

## Entrar: tres formas

- **Con el proveedor de tu organización**, si la tuya lo usa. Es el botón de
  arriba porque, cuando existe, es el camino normal.
- **Con tu correo y tu contraseña.** El ojo del campo te la enseña: es lo que
  evita el tercer intento a ciegas con una contraseña larga.
- **Con una passkey**, si has registrado una. Es la huella, la cara o el PIN de
  tu propio dispositivo, y es la única de las tres que **no se puede robar con
  un correo falso**: tu navegador solo la entrega a la dirección de verdad.

**Si no recuerdas la contraseña**, el enlace está al lado del campo. Te mandamos
uno para poner una nueva: vale una sola vez y caduca en media hora. Al cambiarla
se cierran todas las sesiones abiertas, a propósito — si pides recuperarla es
porque no puedes entrar o porque sospechas.

Por seguridad te decimos lo mismo exista o no ese correo. No es un despiste:
contestar distinto convertiría esa pantalla en una forma de averiguar quién
tiene cuenta aquí.

---

## Administrar el CRM (sección 7.1)

Para quien administra: usuarios, roles, permisos, listas maestras, plantillas,
calendarios laborales y ajustes.

- **Todo lo que hace la consola se puede hacer por API.** No hay acciones
  exclusivas de la pantalla, y eso es comprobable, no una promesa.
- **Los cambios de configuración se registran** con quién y cuándo.
- **Y los ajustes tienen valores sensatos por defecto**: no hace falta tocar
  ochenta cosas para empezar. Lo que se toca, se documenta solo en la referencia de
  ajustes.

### El área de cliente

Tus clientes pueden entrar a **su propia pantalla**, sin ser usuarios del CRM y
sin contraseña: piden un enlace con su correo, entran con él y desde ahí pueden

- ver sus peticiones y en qué estado están,
- **abrir una nueva**, que entra como un caso normal con su compromiso de
  respuesta y su cola —no a una bandeja aparte que alguien tenga que recordar
  mirar—, y
- **escribirle a quien les atiende**. Lo que escriben llega al mismo hilo que su
  correo, así que el agente lo ve donde ya mira y no hay que contarlo dos veces.

Sin contraseña a propósito: un cliente que entra tres veces al año no la
recuerda, y lo que acaba haciendo es reutilizar la del correo. El enlace vale
una sola vez y caduca pronto.

Lo que ve cada uno lo decide su nivel de acceso: el técnico ve lo suyo y el
responsable, lo de su empresa. Eso se decide al darle el acceso, desde el CRM.

**Y tus proveedores, lo suyo.** Si la empresa que entra es proveedora, ve además
sus papeles con nosotros —el seguro, los certificados— con la fecha en la que
caducan, y puede **mandar el renovado ella misma**. Eso es lo que convierte
perseguir certificados caducados, que es trabajo de alguien todos los meses, en
algo que se resuelve solo: el único que puede arreglarlo es el proveedor.

Un proveedor solo ve lo suyo. Los papeles de otro le responden que no le
corresponde.

### Duplicados: el sistema los busca, tú decides

Están en **Clientes → Duplicados por resolver**. Es el único sitio, y a
propósito: hasta el 28-10-2026 había además una pestaña dentro de «Cuentas y
contactos» que enseñaba las mismas parejas y no dejaba hacer nada con ellas.
Dos sitios para lo mismo, y en uno de ellos no se podía decidir.

No es un buscador: es una **cola**. El sistema
recorre tu cartera y propone parejas que podrían ser la misma empresa, cada una
con su **probabilidad** y con **qué ha coincidido** —el NIF, el dominio de
correo, el nombre—. Esa última parte es la que permite decidir sin abrir las dos
fichas: «mismo NIF» y «el nombre se parece» son dos cosas muy distintas.

De cada pareja se hace una de tres cosas:

- **Fusionar**, diciendo cuál de las dos se queda. Esa es la que conserva el
  identificador que usan tus otros sistemas, así que la eliges tú. Te avisa con
  los dos nombres delante antes de hacerlo.
- **No es un duplicado**, y se recuerda: no te la vuelve a proponer.
- **Dejarla**, si ahora no toca.

Nada se fusiona solo, ni siquiera cuando la señal es concluyente: mezclar el
histórico de dos clientes cuesta mucho de deshacer.

**No hay «borrar ésta», y no es un olvido:** borrarla tiraría su histórico —sus
casos, sus oportunidades, lo que se habló— y dejaría huérfano lo que colgaba de
ella. Fusionar hace lo que quieres: una desaparece de las listas y lo suyo pasa
a la que se queda. Y si resulta que son dos empresas distintas que se parecen,
desde ahí se abre cada ficha para cambiar lo que las distingue.

El buscador de antes sigue estando donde sirve: al dar de alta una ficha, para
avisarte mientras escribes.

### Los vocabularios: las listas que decides tú

Los motivos de pérdida, los motivos de descarte y las listas parecidas **no
vienen cerradas**. El producto trae unos cuantos para que puedas trabajar desde
el primer día, y en cuanto cambias uno la lista pasa a ser tuya entera.

- Cada valor tiene un **rótulo** —lo que se lee— y un **código** —lo que se
  guarda—. El rótulo se cambia cuando quieras; el código no, porque lo llevan
  escrito los registros que ya lo usan.
- Un valor que dejas de usar **se retira, no se borra**. Deja de ofrecerse en
  los formularios y los registros antiguos siguen enseñando su etiqueta. Si se
  borrara, tus informes de años anteriores quedarían en códigos sueltos.
- Mientras no toques nada, la pantalla te avisa de que son **los de fábrica**.
  Es la diferencia entre «esto lo eligió mi empresa» y «esto venía puesto».

Están en la pestaña correspondiente de cada módulo: los de pérdida en Pipeline,
los de descarte en Captación de leads.

### Cómo se ve una lista: tarjetas

Una lista se abre **en tarjetas**: cada registro con su nombre delante y sus
cuatro datos debajo. Todas miden lo mismo —el alto de la mayor—, aunque a unas
les falte un dato que otras sí tienen: un borde que no cuadra con el de al lado
se lee como que a esa ficha le falta algo, cuando lo que está vacío puede
estarlo a propósito. Una tabla enseña catorce columnas del mismo tamaño y no
destaca ninguna, así que para encontrar el dato por el que has entrado hay que
leerlas todas; una tarjeta se ojea.

Arriba a la derecha puedes cambiar a **tabla** —que sigue siendo lo mejor para
revisar cien filas seguidas o comparar columnas— o a **columnas**, que agrupa
por lo que separa el trabajo: la etapa de la venta, el estado del caso, la
prioridad. Lo que elijas se recuerda **para esa lista**: quien trabaja el embudo
en columnas no vuelve a la tabla cada mañana.

La única lista que se abre en tabla es la que no tiene nada que poner de
titular: un registro de auditoría o un apunte de consumo es una fecha y un
código, y en tarjeta sería una caja con un identificador dentro.

**En columnas, las tarjetas se arrastran.** Mover un registro de una columna a
otra —cambiar la etapa de una venta, el estado de un caso, el papel de una
persona en el mapa de una cuenta— es el gesto más repetido del día, y hasta el
27-10-2026 obligaba a abrir la ficha, buscar el campo y guardar. Ahora se
arrastra la tarjeta y ya está. Un tablero en el que no se puede mover nada es
una tabla girada.

Tres cosas que conviene saber:

- **Sólo se arrastra lo que se puede guardar.** Si ese campo no se puede
  cambiar después de crear el registro, la tarjeta no se coge. Dejarte cogerla
  para devolverla a su sitio sin decir por qué se lee como que algo falla.
- **Si el servidor dice que no, la tarjeta vuelve** y se enseña su motivo. Hay
  cambios que el negocio no admite —una oportunidad perdida no vuelve a
  negociación— y dejarla donde la soltaste enseñaría un embudo que no existe.
- **Sin ratón también se mueve.** Tabulando hasta la tarjeta aparece un
  selector con las columnas; es el mismo que ya lleva el embudo. Arrastrar es
  una de las formas de mover, no la forma.

**Y algunas listas llevan medidas encima.** No todo lo que el sistema sabe es
una lista: hay respuestas que son cuatro cifras y una frase que dice qué
significan —cuánto se lleva gastado de IA este mes y si queda margen, si los
avisos de anomalía han servido de algo, cuánto se ha consumido de lo
contratado—. Se enseñan arriba del listado al que pertenecen, que es donde se
preguntan: el gasto encima del consumo, la calidad de los borradores encima de
los borradores. Cuando una de esas cifras **no es concluyente** —porque nadie
ha marcado todavía qué hizo con los borradores, por ejemplo— sale en ámbar y
con el motivo, no como un cero: un cero ahí se leería como «va mal» o como «va
bien» según a quién le pregunten, y lo que pasa es que no se ha medido.

La columna de la izquierda del todo puede ser «—»: ahí se agrupa lo que no
tiene ese dato. No se puede soltar nada en ella, porque eso escribiría el guion
como si fuera un valor. Vaciar un campo se hace en la ficha, con el campo
delante.

### Añadir y editar, en general

Casi todas las pantallas que enseñan una lista permiten **dar de alta** y
**abrir cada fila** para verla, cambiarla o borrarla. Eso incluye las fichas con
diseño propio, como la de un cliente: ahí tienes **Editar** y **Eliminar**
arriba, junto a las demás acciones. Hasta el 27-10-2026 no los tenía —la
edición vivía dentro de la ficha genérica y la de cliente se quedó sin ella—,
así que un cliente no se podía cambiar desde ningún punto de su propia ficha
aunque el sistema lo admitiera y la misma pantalla estuviera avisando, al lado,
de que le faltaban cuatro campos por rellenar.

Qué campos puedes cambiar no lo decide la pantalla: son los que el sistema
admite modificar después de crear el registro, que no son los mismos que se
piden al darlo de alta. Hay cosas que se fijan al crear y no se tocan luego, y
ofrecértelas sería prometerte un cambio que acabaría en error. Lo que puedes hacer en
cada una no lo decide la pantalla: lo decide el servidor, y la pantalla se
limita a ofrecer lo que de verdad admite. Por eso no hay pantallas que ofrezcan
un botón que luego falla, ni —lo que pasaba antes— pantallas que escondan algo
que el sistema sí sabe hacer.

Las que solo se miran son las que **no tienen nada que dar de alta**: un resumen
del pipeline, una lista de contratos que vencen pronto, una cola de trabajo. Ahí
lo que se ve se calcula a partir de otra cosa, y se cambia yendo a esa otra cosa.

### Borrar: lo que se puede y lo que no

Borrar envía el registro **a la papelera**, no lo destruye: deja de listarse y
se puede recuperar desde ahí. Lo que se borra por error se descubre siempre más
tarde que el borrado.

Y **no se deja borrar lo que otros registros están usando**. Si intentas quitar
una tarifa que tienen veinte acuerdos, el sistema te dice qué depende y cuántos
son, y no lo borra: borrarlo dejaría esos veinte apuntando a una tarifa que ya
no existe, y eso no falla al borrar — falla semanas después, al abrir uno de
ellos.

Para eso está **archivar**: retira el registro de aquí en adelante, deja de
ofrecerse en los formularios, y no toca nada de lo que ya pasó. Casi siempre es
lo que se quería hacer.

---

## Cambios, entornos y vuelta atrás (sección 7.2)

### Antes de publicar un cambio del modelo, y antes de llevarlo a otro entorno

Dos cosas que ahora se ven y antes había que adivinar:

- **«¿Qué pasaría si publico esto?»** En la ficha de cada objeto del modelo.
  Dice de qué versión a cuál se va, cuántos campos se añaden, se retiran o
  cambian, **a cuántos registros afecta** y cuántos se quedarían sin rellenar.
  Quien añade un campo obligatorio a un objeto con ochenta mil registros no
  sabe que los ochenta mil se quedan a medias hasta que alguien intenta guardar
  uno viejo y no puede. Y cuando no se ha podido contar **lo dice**: «no se ha
  podido contar» y «no afecta a nadie» no son lo mismo.
- **Llevarse la configuración a otro entorno.** En «Entornos y despliegue» se
  exporta la configuración, se **simula** su instalación y sólo después se
  aplica de verdad —en otro botón y en otro color—, porque un paquete es un
  cambio de modelo de datos en producción y el error más caro es pulsar
  creyendo que aún se estaba mirando. Lo que se lleva es **configuración y
  nunca datos**: un paquete que arrastrara registros convertiría una promoción
  en una fuga, porque los datos de pruebas suelen ser copias anonimizadas a
  medias de clientes reales.


Si tu empresa trabaja con entorno de pruebas y producción:

- **Un cambio se empaqueta y se promociona**, no se repite a mano en cada sitio.
- **Se detecta lo que alguien tocó a mano en producción** (el *drift*), comparando
  contra lo que se desplegó — no contra otro entorno.
- **Volver atrás es reaplicar el paquete anterior**, no deshacer cambios uno a uno:
  deshacer falla en cuanto hay dependencias.
- Y las automatizaciones **llegan apagadas** al entorno nuevo: encender por error
  una campaña en producción al promocionar es de los errores caros.

---

## Tus derechos y los de tus clientes (sección 7.3)

- **Acceso, rectificación, supresión y portabilidad**: el CRM tiene un flujo para
  cada uno, con plazo y con prueba de lo que se hizo. En la ficha de cada
  solicitud consta de quién es, quién la lleva, por dónde entró y —cuando se
  cierra— qué se resolvió y con qué prueba: una solicitud cerrada que dice
  «resuelta» y no dice qué se hizo no sirve de evidencia ante nadie.
- **Consentimientos por canal y por finalidad**, con su fecha y su origen. Un
  consentimiento sin origen no vale para demostrar nada.
- **Datos personales marcados en el modelo**, para saber en todo momento dónde
  están — incluidos los campos que creó tu empresa.
- **De qué empresas es cada persona**: un contacto puede serlo de varias, con
  papel distinto en cada una, y en su ficha salen todas — también las que ya
  dejó, con la fecha. «Ya no trabaja ahí» es justo lo que hay que saber antes
  de llamar.
- **Auditoría encadenada**: el registro de quién hizo qué no se puede alterar sin
  que se note.
- Y **lo que se borra, se borra también donde se copió**: en el lago de datos del
  cliente, en las audiencias de las plataformas y en las proyecciones internas.

### Dos preguntas que se hacen en «Identidad y seguridad»

- **«Y éstos, ¿por qué están permitidos?»** El informe de segregación marca los
  conflictos que alguien autorizó. Justo debajo están esas autorizaciones **con
  el motivo que se escribió y hasta cuándo valen** — que es lo que el alta
  exige y lo que hasta ahora no se podía leer. Una excepción que no se puede
  leer no es un control, es papeleo. Se pueden ver también las caducadas, que
  es lo que distingue «no hay ninguna» de «todas vencieron».
- **«No puedo entrar»: ¿por dónde le toca entrar?** Se escribe el correo y dice
  si le toca SSO —con qué proveedor— o contraseña del CRM, y avisa si su
  dominio tiene el SSO forzado y por tanto no hay vía de escape. El usuario no
  puede contestarlo: él sabe su correo, no si su empresa usa Entra ID o Ping. Y
  mirarlo a ojo en la lista de dominios falla justo en los casos raros, porque
  un subdominio hereda del dominio padre y gana el más específico.

### Dónde se mira todo eso: «Plataforma y cumplimiento»

En **Administrar › Plataforma y cumplimiento** están cuatro cosas que antes solo
existían por API, es decir, que estaban hechas y no se podían ver:

- **Quién tocó qué.** El registro de accesos, cambios, exportaciones y acciones
  de administración, filtrable por acción y por objeto. Se consulta aquí y no
  exportándolo a otra herramienta: «¿quién tocó esta cuenta?» se pregunta
  mientras se mira la cuenta, y obligar a salir significa que casi nunca se
  responde. Desde ahí se puede **volcar al SIEM** de tu empresa, en un formato
  neutro que cualquiera lee.
- **Lo que se salió de lo normal.** Las exportaciones y lecturas masivas de los
  últimos treinta días, con cuántos registros salieron y si se bloquearon.
- **Qué datos personales trata cada servicio**, con los huecos por delante: un
  objeto con datos personales y sin tratamiento declarado sale señalado. Un
  registro que se presenta completo sin serlo es peor que no tenerlo, porque
  nadie vuelve a mirarlo. Y al lado, **quién puede hacer qué**, con los dos
  agujeros opuestos: permisos que alguna pantalla exige y no tiene ningún rol
  —funcionalidad muerta— y permisos concedidos que ninguna pantalla exige
  —privilegios dados por si acaso—.
- **Qué se puede recuperar.** Lo que hay en la papelera, lo primero lo que menos
  tiempo le queda antes de purgarse, con cuántos registros se llevaría por
  delante al restaurarlo.

Y tres más que se preguntan el día que algo va mal, que es el día en que nadie
se pone a buscarlas:

- **Hasta dónde se puede volver atrás.** Cuánto se perdería si el incidente
  fuera ahora, frente a lo comprometido —el dato real, no el del contrato: la
  diferencia entre los dos es lo único que se puede enseñar en una auditoría—,
  y si la retención llega hasta donde se pide. Pedir volver a hace noventa días
  cuando la retención son treinta no es un error de quien lo pide: es una
  expectativa que alguien le dio.
- **Qué va camino de dar problemas.** Las particiones que hay que crear antes
  de que hagan falta. Una que falta no se nota hasta que la escritura falla, y
  entonces ya es un incidente.
- **Tarjetas e identificadores fiscales.** Si este despliegue puede sacar del
  CRM un número sensible y quedarse sólo con una referencia. Se mira **antes**
  de ofrecer el campo: sin bóveda, guardarlo «hasta que la haya» mete el
  sistema en el alcance de PCI sin que nadie lo haya decidido.

Arriba hay un **selector de servicio**, porque cada parte del sistema guarda lo
suyo y la pregunta es la misma para todas. Lo alternativo eran setenta y ocho
pestañas diciendo lo mismo, y en setenta y ocho pestañas no se encuentra nada.

---

## La interfaz oficial (sección 7.4)

El front que viene con el producto enseña **todo** lo que el CRM hace: no hay
funcionalidad que solo exista por API. Es sustituible —se puede no desplegar y
poner el vuestro— y eso también es comprobable: ningún servicio sirve pantallas ni
depende de ellas.

Lo que encontrarás en él: listas configurables en tarjetas, tabla o columnas,
ficha con pestañas, buscador global, panel de inicio por perfil, diseñador
visual, consola de administración, paneles de estado y ayuda en contexto.

---

## Documentación (sección 7.5)

Este manual y el [manual técnico](manual-tecnico.md) son independientes y
completos. Los dos se comprueban automáticamente: no pueden describir algo que no
existe ni dejar fuera un área que sí.

---

## Cuando hay mucho volumen (sección 8.1)

Lo que notarás si tu empresa maneja millones de registros: las listas siguen
abriéndose, los procesos largos van por detrás con progreso visible, y si algo se
va a pasar de un límite se avisa **antes**. Cuando el sistema está bajo presión,
lo que se degrada primero es lo que no es crítico —un recálculo de fondo, un
informe pesado— y no lo que estás haciendo tú.

---

## Lo que se promete y lo que se cumple (sección 8.2)

Disponibilidad, tiempos de respuesta y ventanas de mantenimiento están publicados
**con lo medido al lado de lo prometido**. Si un mes no se cumplió, aparece: un
panel de compromisos que siempre está en verde no lo mira nadie.

---

## Tus proveedores (sección 9.1)

Un proveedor **es una cuenta con el rol de proveedor**, no una ficha aparte. La
misma empresa puede ser cliente de una división y proveedora de otra, y con dos
maestros distintos acabaría dos veces, con el riesgo de aplicarle las
condiciones de la ficha equivocada.

Por eso la pantalla de proveedores funciona igual que la de clientes: se da de
alta desde ahí, se abre cada uno, se edita, y cuelgan de él sus homologaciones,
sus documentos con vigencia y sus contactos. Antes solo se podía **mirar** la
lista: dar de alta uno exigía saber que era una cuenta, irse a cuentas, crearla
allí y volver.

Si tu empresa usa proveedores para dar servicio:

- **Un proveedor es una cuenta con rol**, en la misma ficha de siempre.
- **La homologación es por categoría**: uno puede valer para material de oficina y
  no para trabajos en altura, y el CRM no deja encargarle lo segundo.
- **Los papeles caducan y bloquean solos.** Si el seguro venció, no hace falta que
  nadie se acuerde.
- **Y a quién llamar cuando algo falla** está en la ficha, por función. Si no hay
  nadie de escalado, se dice — en vez de darte el teléfono del comercial a las once
  de la noche.

---

## Lo que cuesta y lo que se puede comprometer (sección 9.2)

- **La tarifa del proveedor alimenta el coste de la oferta**, y de ahí sale el
  margen.
- **La capacidad descuenta lo ya comprometido**, y avisa si con las ofertas
  abiertas no cabría todo.
- **El plazo del proveedor decide la fecha que prometes**, no al revés — y si no
  declara plazo, el CRM prefiere decir que no se puede prometer fecha a inventar
  una.
- **Y al final se compara el coste real con el ofertado**, pedido a pedido: una
  media esconde el que se fue al 40 %, que es el único que enseña algo.

---

# Parte 2 — Casos de uso de punta a punta

## Caso 1: del primer contacto al cobro

1. **Entra un lead** por el formulario de la web. El CRM lo normaliza (teléfono a
   formato internacional, razón social sin la forma jurídica) y avisa de que se
   parece a una cuenta que ya existe. Decides fusionar o seguir aparte.
2. **Se asigna solo** por territorio y carga de trabajo. En la ficha ves por qué te
   tocó a ti.
3. **Lo cualificas.** Al convertirlo se crean cuenta, contacto y oportunidad
   enlazados, y el historial del lead viaja con ellos.
4. **Trabajas la oportunidad.** Anotas quién decide y quién paga; el CRM te avisa
   de que al económico no le has llamado todavía.
5. **Preparas la oferta.** El precio sale del motor de tarifas y se explica línea a
   línea; si hay costes cargados, ves el margen. Si el descuento pasa de la
   política, se pide aprobación **antes**, no después.
6. **Plan conjunto con el cliente**: los tres pasos que faltan, con fechas, y dos
   de ellos suyos.
7. **La revisión con tu jefe** queda registrada con lo que dijisteis: probabilidad,
   fecha y qué puede salir mal.
8. **Se firma** electrónicamente desde la propia oferta, con la cadena de custodia
   guardada aquí y no solo en el proveedor.
9. **Se convierte en pedido y contrato**, con el calendario de ingreso repartido.
10. **El ERP devuelve la facturación y el cobro**, que aparecen en la ficha con su
    fecha. Si el cliente entra en deuda vencida, la siguiente oferta avisa antes de
    comprometer nada.

## Caso 2: una incidencia, de la queja al cierre

1. **Llega por WhatsApp.** Se abre un caso con el hilo completo; el cliente ya
   estaba identificado por su teléfono.
2. **Se clasifica y se prioriza** por categoría y por contrato: el SLA que aplica
   es el suyo, no uno genérico.
3. **El agente ve tres casos parecidos ya resueltos**, con la cita de dónde sale
   cada solución, y uno de ellos es de otra versión del producto — el CRM se lo
   dice.
4. **Hace falta un técnico.** Se genera la orden de trabajo, se planifica teniendo
   en cuenta el desplazamiento, y el cliente recibe la franja.
5. **El reloj se para** mientras se espera la confirmación del cliente.
6. **Se resuelve**, se pide valoración, y la solución se propone como artículo de
   conocimiento — para que el siguiente no empiece de cero.
7. **Si reabre** dentro del plazo, vuelve al mismo caso; si ya pasó, se abre uno
   nuevo enlazado y los indicadores del periodo cerrado no se tocan.

## Caso 3: una campaña que no se lleva a nadie por delante

1. **Se define el segmento** y se ve a cuánta gente afecta.
2. **Se comprueban los permisos por canal**: los que no han aceptado ese canal se
   quedan fuera y se cuentan.
3. **Se prueba en seco** contra datos reales.
4. **Se aprueba el contenido**, con legal al final para no revisar dos veces lo
   mismo.
5. **Se manda**, personalizando la hora solo para quien tiene historial suficiente.
6. **Se mide** con lo que respondió, no solo con lo que se abrió. Y las bajas se
   propagan el mismo día a las audiencias de fuera.

---

# Parte 3 — Para empezar

## Ejemplos que puedes reproducir

Los ejemplos van con los datos que carga `scripts/sembrar_demo.py`, así que se
pueden hacer mientras se leen. Si tu instalación no tiene la demo cargada, pídela
a quien la administre: es un comando.

### Ejemplo 1 — Buscar un cliente escrito de otra forma

En la demo hay una cuenta con el teléfono guardado como `+34 600 11 22 33`.
Búscala escribiendo `600112233`, sin prefijo ni espacios. Aparece.

Esto no es un detalle: el mismo número está escrito de tres maneras distintas en
cualquier CRM con cinco años de vida, y son justo los clientes antiguos los que
están mal escritos.

### Ejemplo 2 — Crear una oportunidad sin fecha

Intenta crear una oportunidad dejando la fecha de cierre vacía. No deja, y el
mensaje dice por qué: sin fecha no entra en ninguna previsión, y una oportunidad
que no entra en la previsión es una que nadie mira.

Ponle fecha y guarda. Ahora mírala en la previsión: aparece en la categoría
*pipeline*, no en *comprometido* — la categoría la pones tú, no la etapa.

### Ejemplo 3 — Un duplicado a propósito

Crea una cuenta llamada «Acme Soluciones S.L.» sabiendo que la demo ya tiene
«ACME SOLUCIONES SL». El CRM avisa antes de guardar y dice **por qué** cree que
son la misma: el nombre normalizado coincide.

Fusiónalas. Después, mira el historial: la ficha antigua no ha desaparecido, y la
fusión se puede deshacer.

### Ejemplo 4 — Pedir un descuento que no te toca

En una oferta de la demo, pon un descuento del 40 %. Al enviarla, el CRM pide
aprobación y dice **qué política** lo exige y a quién va. Si tu empresa ha cargado
los costes, verás además el margen que queda — y si es negativo, lo dice sin
rodeos.

### Ejemplo 5 — Un caso con el reloj parado

Abre un caso de la demo y márcalo como «esperando al cliente». Mira el SLA: el
reloj está parado. Vuelve a ponerlo en curso y sigue contando desde donde estaba.

Es la diferencia entre medir tu trabajo y medir la agenda del cliente.

### Ejemplo 6 — Preguntar de dónde sale un dato

Abre una cuenta de la demo que venga del ERP y mira el linaje de su dirección:
qué sistema la trajo, cuándo cambió de verdad y cuándo se confirmó por última vez.
Si hay dos sistemas que dicen cosas distintas, los dos aparecen.

### Ejemplo 7 — Un alta que se cae a mitad

Algunos procesos del CRM tocan varias cosas a la vez: reservan el material,
cobran la señal y avisan al cliente. Cuando uno de esos pasos falla —el banco
rechaza la tarjeta—, el CRM **deshace hacia atrás lo que ya había hecho**: libera
el material que había reservado. No deshace lo que no llegó a hacer.

Lo que verás en la ficha del proceso:

- **Deshecho**: lo que se ha podido revertir solo. No tienes que hacer nada.
- **Sin deshacer**: lo que ya no vuelve. Si el correo al cliente salió antes de
  que fallara el cobro, el correo no se puede «desenviar». El proceso se queda
  marcado como **atascado a propósito**, con esa lista, para que alguien decida
  qué hacer: normalmente llamar al cliente y explicarlo.

Esa lista es la parte importante. Un proceso que dijera «todo revertido» cuando
el cliente ya ha recibido un aviso te deja quedando mal sin saberlo.

Y por eso, cuando alguien configura uno de estos procesos, el CRM avisa si algo
que no se puede deshacer está colocado en medio en vez de al final.

### Ejemplo 8 — La misma pantalla con dos caras

Si tu organización ha configurado **tipos de registro**, una cuenta pública y una
privada no se rellenan igual: la pública no enseña los campos que no le aplican, y
las listas que compartes con el resto vienen recortadas a lo que tu tipo admite.

Abre una cuenta de cada tipo y compara el formulario. Si ves un campo que no tiene
sentido para ese tipo, no es que falte configuración: es que ese campo no se ha
declarado como oculto para él, y quien administra el CRM puede hacerlo sin tocar
nada más.

Si tu empresa tiene **módulos instalados** (paquetes que añaden pantallas y
listas), lo que tú ajustes de ellos queda marcado como tuyo: la próxima
actualización del módulo no te lo pisa sin avisar.

### Si tu empresa conecta el CRM con otro programa

Hay dos formas de conectarlo: la normal, que vale para casi todo, y una segunda vía
más rápida para quien mueve muchísimos datos (millones de filas). Esa segunda vía
hay que encenderla a propósito y la configura quien administra el CRM.

Lo único que te afecta a ti: si tu empresa la usa, los datos que se mandan desde el
otro programa pasan **por los mismos permisos y las mismas validaciones** que si los
escribieras tú en pantalla. No hay una puerta de atrás con menos comprobaciones.

### Por qué no te llegan los avisos por duplicado

Dentro, el CRM se avisa a sí mismo de todo lo que pasa: que se ha creado una
cuenta, que una oportunidad se ha ganado, que un caso lleva dos días sin
respuesta. Esos avisos internos pueden llegar dos veces —es normal en este tipo de
sistemas, y es el precio de que no se pierda ninguno—.

Lo que no puede pasar es que el efecto ocurra dos veces: que se te cree el cliente
por duplicado, que se sume el importe dos veces o que al cliente le llegue el
mismo correo dos veces. El CRM lleva la cuenta de lo que ya ha procesado y
descarta la repetición.

Si alguna vez ves algo duplicado de verdad, no es esto: avisa a quien administra el
CRM con la fecha y la hora, que ahí queda registrado.

### Si exportas datos, el fichero lleva tu nombre dentro

Cuando exportas en CSV, el fichero sale con dos líneas de marca —una arriba y otra
abajo— que dicen de dónde salió y quién lo pidió. No es para vigilarte: es para
que, si esa hoja aparece donde no debía, se pueda saber de qué exportación vino en
lugar de sospechar de todo el mundo.

No las borres si vas a mandarlo a alguien de fuera. Si lo abres con una hoja de
cálculo, esas dos líneas aparecen como filas sueltas al principio y al final.

### Y si tu empresa guarda tarjetas, el CRM no las tiene

Los números de tarjeta, las cuentas bancarias y los identificadores fiscales **no
se guardan en el CRM**: se guardan en un sistema aparte preparado para eso, y aquí
queda una referencia y los cuatro últimos dígitos para que reconozcas cuál es.

Si necesitas ver el número completo, el CRM te lo pedirá dos cosas: volver a
identificarte y decir para qué. Las dos quedan registradas. No es desconfianza: es
lo que hace que guardar esos datos así tenga sentido.

### Si dos personas editáis la misma ficha

Puede pasarte: abres un contrato, te vas a comer, vuelves y guardas. Mientras
tanto, un compañero lo ha cambiado.

Antes, tu guardado borraba el suyo y ninguno de los dos se enteraba. Ahora el CRM
te para y te dice que alguien lo ha cambiado mientras lo tenías abierto. Lo que
tienes que hacer:

1. **Vuelve a cargar la ficha.** No le des a guardar otra vez sin más.
2. **Mira qué cambió tu compañero.**
3. **Decide**: si lo tuyo sigue teniendo sentido, vuelve a escribirlo sobre lo
   nuevo; si no, deja lo suyo.

Es un segundo de molestia a cambio de no perder el trabajo de alguien sin saberlo.

### Si una plantilla sale con un error

Pongamos que descubres que el contrato que mandáis llevaba una cláusula mal
redactada. La pregunta inmediata es a cuántos clientes se la habéis mandado.

El CRM lo apunta: cada documento que se compone deja registrado de qué plantilla
salió y **de qué versión**. Quien administra el CRM puede preguntar por esa
versión concreta y obtener la lista. Si el documento se archivó en el gestor
documental, aparece también su enlace.

Lo apunta aunque el documento no se archive — porque los que se mandan por correo
sin guardar son justo los que después nadie encuentra.

### Resumir una carpeta entera de documentos

Puedes pedirle al CRM que resuma una carpeta del gestor documental, o que te diga
qué conceptos aparecen en ella. Tarda, así que **no se queda esperando**: te
devuelve un número de trabajo y lo consultas cuando esté.

El resumen viene con las fuentes: qué documentos se usaron y cuántos trozos de
cada uno. Si alguno de esos documentos ya no existe, se te dice en vez de
callarlo — el resumen se apoyó en algo que ha desaparecido, y eso lo tienes que
saber tú.

Solo verás resumido lo que ya podrías abrir: se consulta con tu identidad, no con
la del sistema.

### Lo que te dice el panel de consumo

Si tu plan incluye límites —correos al mes, registros, almacenamiento—, el panel
te dice cuánto llevas gastado de cada cosa y te avisa **antes** de llegar al tope,
no el día que dejas de poder trabajar.

Lo que ves ahí se cuenta de verdad sobre tus datos, no de un contador aparte: si
borras registros, el número baja. Y si alguna métrica no se puede medir en ese
momento, te lo dice en esa línea en lugar de enseñarte un cero, que es muy
distinto.

### Si el CRM te dice que algo «no puede apuntar ahí»

Algunos registros se enlazan con otros: una actividad cuelga de una cuenta, de un
contacto o de una oportunidad. Quien configura el CRM decide de qué cosas puede
colgar cada una.

Si intentas enlazar con algo que no está en esa lista, el CRM te lo dice **y te
enumera con qué sí puedes enlazarlo**. No es una limitación arbitraria: un enlace
hacia algo que no estaba previsto no da error ese día, lo da meses después,
cuando alguien abre esa ficha y el enlace no lleva a ninguna parte.

Si lo que necesitas enlazar debería estar permitido, es cosa de quien administra
el CRM: se añade a la lista y vuelve a funcionar.

---

## Qué hacer cuando algo no sale

Estos son los mensajes que más se ven, qué significan de verdad y qué hacer. Casi
ninguno es un error del sistema.

| Lo que ves | Qué pasa de verdad | Qué hacer |
| --- | --- | --- |
| **«No tienes permiso»** con una explicación debajo | El CRM te dice qué regla te lo impide, no solo que no puedes | Si te hace falta, pídeselo a quien administra citando esa regla: con eso lo resuelve en un minuto |
| **«Esta oportunidad no tiene fecha de cierre»** | No entraría en ninguna previsión | Ponle una, aunque sea aproximada; se puede cambiar |
| **«Parece un duplicado de…»** | Hay otra ficha que coincide en algo fuerte | Míralo. Fusionar se deshace; tener dos fichas del mismo cliente, no |
| **«El descuento supera la política»** | Hace falta que alguien lo apruebe | Mándalo a aprobar desde ahí mismo: va a quien corresponde con el motivo |
| **«La cuenta está bloqueada»** con un motivo | El ERP dice que hay deuda vencida | El motivo es lo que le puedes contar al cliente; si crees que está mal, se comprueba en el ERP |
| **«El dato financiero es de hace N días»** | La cifra que ves no es de hoy | Con más de dos días, confírmalo antes de comprometer algo grande |
| **«No se ha podido leer el calendario»** | No se sabe si esa persona está libre | Propón horas a mano. El CRM prefiere no proponer a proponer encima de una reunión |
| **«No se puede medir»** en un panel | No hay datos suficientes, que no es lo mismo que «cero» | Mira qué falta por conectar; el propio panel lo dice |
| **«Este canal no tiene consentimiento»** | Esa persona no aceptó ese canal concreto | Usa otro por el que sí lo tengas, o pídeselo |
| **«Hay cambios sin sincronizar»** en el móvil | Algo no ha podido subir | No se pierde: está en la cola. Si lleva días, avisa — suele ser la credencial |
| **«La sesión ha caducado»** | Es lo normal tras un tiempo sin actividad | Vuelve a entrar. Si pasa cada poco, díselo a quien administra: hay un ajuste |

Y una regla general: cuando el CRM te dice que **no sabe** algo, no lo trates como
un cero. «No se pudo medir», «no hay dato» y «no es fiable» son avisos de que la
información no está, no de que el resultado sea malo.

---

## Recorridos por perfil

### Si eres comercial

Tu día empieza en **tu panel**: lo que vence hoy, lo que lleva parado y las
oportunidades que necesitan algo. Lo que más te va a ahorrar tiempo:

1. **Conecta tu correo y tu calendario.** Las reuniones y los correos con clientes
   entran solos y dejan de ser diez minutos de tecleo al día.
2. **Usa el marcador.** La llamada se registra al colgar; tú solo escribes qué se
   habló.
3. **Rellena quién decide** en las oportunidades grandes. La lista de «con quién no
   he hablado» es lo que más cierres salva.
4. **Mira el margen antes de dar un descuento**, si tu empresa tiene los costes
   cargados.
5. Y si trabajas fuera de la oficina, **el móvil funciona sin cobertura**: lo que
   anotes se sube después.

### Si atiendes clientes

1. **Trabaja desde la cola**, no desde el correo: la cola está ordenada por lo que
   está más cerca de incumplir.
2. **Para el reloj** cuando la pelota esté en el tejado del cliente. Es lo que hace
   que tus indicadores digan la verdad.
3. **Mira las sugerencias** del caso: casos parecidos ya resueltos y el artículo
   que los explica, con su cita. Comprueba que hablan de tu misma versión.
4. **Propón como artículo** lo que resuelvas y no estuviera escrito. El siguiente
   agente empieza donde tú acabaste.

### Si haces marketing

1. **Define el segmento y mira a cuánta gente afecta** antes de nada.
2. **Prueba en seco** contra datos reales.
3. **Respeta el permiso por canal**: es por canal y por finalidad, no por persona.
4. **Aprueba el contenido** antes de publicar, y mira qué cambió respecto de la
   versión anterior.
5. **Mide por respuesta**, no por apertura. Y propaga las bajas el mismo día.

### Si administras el CRM

1. **Empieza por los perfiles y los permisos.** Casi todos los problemas de «no veo
   nada» y «veo demasiado» se resuelven aquí.
2. **Configura los calendarios laborales y los festivos** antes de activar SLAs.
3. **Declara los campos personalizados con su significado** si vais a usar la IA:
   con el 30 % descrito, entiende el 30 %.
4. **Usa entornos y paquetes** para llevar cambios a producción, y mira el drift de
   vez en cuando: lo que alguien tocó a mano un viernes aparece ahí.
5. **Revisa el panel de conexiones**: lo que lleva días sin sincronizar no da error,
   simplemente deja de traer cosas.

### Si diriges

Lo que te va a servir y lo que conviene mirar con cuidado:

- **La previsión** por categorías puestas por personas, con el histórico sin
  reescribir: se puede ver qué se dijo en marzo.
- **El crecimiento real**, que descuenta renovaciones y sustituciones. Es más bajo
  que el total y es el que significa algo.
- **La calibración de las revisiones**: si lo que se revisa al 80 % se gana la
  mitad de las veces, ese 80 % no es una probabilidad, es una impresión.
- **Y lo que el sistema dice que no sabe.** Los paneles distinguen entre «cero» y
  «no medido», y esa distinción es la que evita decisiones tomadas sobre huecos.
