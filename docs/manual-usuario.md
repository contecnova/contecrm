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

**Moverse: trabajas dentro de una aplicación.** Arriba, debajo de la barra de
búsqueda, está la **barra de la aplicación**: a la izquierda su nombre —Ventas,
Servicio, Marketing o Analítica— y a su derecha **sus** pestañas. La que estás
mirando va subrayada en azul. Las que no caben se recogen en **Más**, y la
activa nunca se esconde ahí.

Hasta el 01-11-2026 esto era un menú lateral con 29 entradas en el que «Cuentas
y contactos» y «Contrato de la API» estaban a la misma altura, y detrás 211
pestañas repartidas en 25 módulos. Para mirar tus oportunidades había que leer
cincuenta y nueve rótulos. Ahora ves las de tu aplicación y ya está.

**Cambiar de aplicación, o ver qué hay.** Pulsa el nombre de la aplicación
—«Ventas ▾»— y se abre el **lanzador**: las cuatro aplicaciones, cuántas
pantallas tiene cada una, y debajo la lista completa de todas. **Pulsar una
aplicación te lleva a ella**, a su primera pantalla, estés donde estés; y desde
la lista de abajo se va a cualquier pantalla directamente. contecrm recuerda en
cuál estabas.

**Inicio y Puesto son pestaña de todas**, porque no son de un dominio: son por
donde se empieza el día. Las aprobaciones también, por lo mismo — se aprueba un
descuento, un contrato y un gasto desde el mismo sitio.

**La configuración está detrás del engranaje**, arriba a la derecha. Es otra
puerta a propósito: lo que se ajusta de tarde en tarde no tiene por qué estar
compitiendo por sitio con lo que usas cada día. Ahí sí hay un árbol a la
izquierda —y el botón de las tres rayas, arriba, para plegarlo cuando quieras
más sitio; trabajando no sale, porque no hay nada que plegar—, porque ahí lo
que se hace es recorrer una lista larga buscando un
ajuste. El mismo botón te devuelve al trabajo.

> El engranaje **sólo sale si tienes algo que configurar**. Si no lo ves, no es
> que falte: es que tu perfil no abre ninguna de esas pantallas.

**El árbol de la configuración tiene cinco temas**, y son los del árbol de
Setup de Salesforce, por lo mismo que el resto: quien ya usa un CRM sabe en
cuál mirar sin leerlos todos.

| tema | qué hay dentro |
|---|---|
| **Usuarios y empresa** | las personas, lo que pueden hacer y bajo qué empresa: Empresas y unidades, Usuarios y permisos, Identidad y seguridad, Administración, Aplicaciones conectadas |
| **Herramientas de plataforma** | lo que se modela y lo que se publica: Gestor de objetos, Contrato de la API |
| **Automatización** | Procesos y orquestación, y el Editor de procesos |
| **Entornos y despliegue** | Operación, Promoción entre entornos, Despliegues y desvíos, Ciclo de vida del cliente, Estado |
| **Gobierno y cumplimiento** | Riesgos y controles, Plataforma y cumplimiento, Panel de cumplimiento, Segregación de funciones, Controles del GRC, Revisión de accesos, Clasificación TCSEC |

Hasta el 03-11-2026 eran dos: «Automatización», con dos entradas, y
«Configuración», con dieciocho —entre ellas «Ayuda» y «Estado», que no ajustan
nada—. Un desplegable con dieciocho enlaces dentro es la lista de antes con un
título encima: agrupar no sirve de nada si un grupo se queda con el 90 %.
Ahora ninguno pasa de diez, que es lo que se lee de un vistazo, y hay una
prueba que lo impide.

**La ayuda está en la interrogación**, al lado del engranaje — donde la pone
Salesforce. Dentro hay tres cosas, y las tres hablan **del producto**, no de tu
cliente ni de tus ajustes:

- **Ayuda**, cómo se usa esto.
- **Recorrido guiado**, la visita por lo que hay.
- **Cobertura**, qué sabe hacer el producto y qué tiene pantalla.

Estaban dentro de la configuración, en la misma rama que «Usuarios y
permisos». Quien busca ayuda no entra a configurar para encontrarla, y quien
configura se las topaba en medio.

Arriba, la línea de la barra dice dónde estás y permite volver: en una ficha, el
paso anterior es el listado del que salió. **En una ficha no pone «Inicio»**: la
barra tiene el sitio que tiene, y «Inicio» sale en todas las pantallas, así que
no distingue ninguna; a la portada se vuelve con el logo de la esquina.

**Lo último que has abierto, al pinchar el buscador.** Con la caja vacía, lo
primero que sale es **«Visto hace poco»**: los registros que has abierto, del
más reciente al más antiguo y uno por registro —abrir diez veces la misma
cuenta no la repite diez veces—. Es lo que hace Salesforce y por el mismo
motivo: lo que más se busca es aquello en lo que se estaba.

Es tuyo y va contigo: está guardado en el servidor, no en el navegador, así
que lo ves igual desde otro ordenador.

**El buscador encuentra registros, no sólo pantallas.** Escribe el nombre de
un cliente, de una oportunidad o de un caso y sale, por debajo de las
pantallas que casen. **Escribir más no encuentra menos**: el último trozo de
lo que tecleas busca por principio de palabra, así que «Venta 9» encuentra
«Venta 924762» igual que «Venta».

**Ir a una pantalla escribiendo su nombre.** `⌘K` en Mac, `Ctrl+K` en el resto,
o el buscador de la barra de arriba. Escribes «cuentas», «previsión» o «ventas»
—vale el nombre del grupo— y las flechas y `Intro` te llevan. Con veinticinco
módulos y veinte pantallas transversales, esto es más rápido que el menú, y no
lo sustituye: el menú es para ver qué hay, el atajo para volver a algo que ya
sabes que existe.

**Claro y oscuro.** El botón de la barra de arriba cambia el tema, y la elección
se recuerda en ese navegador.

**La letra de máquina, sólo donde toca.** Los códigos, los identificadores y
las cifras que se comparan en columna se escriben con letra monoespaciada,
porque se leen carácter a carácter. Las frases, no. Hasta el 03-11-2026 salían
así cosas como «sin medir» o «Apertura: no hay con qué medirla todavía», que
parecían un código y no lo eran.

**Cuando una sección está vacía, lo dice en una línea.** Antes cada bloque sin
datos ocupaba una tarjeta entera con su dibujo, y una pantalla con tres o
cuatro seguidos era una pantalla de «aquí no hay nada» repetido. La tarjeta
grande se reserva para cuando lo vacío es la pantalla entera.

**Cada entrada del menú dice qué hace.** Hasta el 03-11-2026 había parejas
que obligaban a entrar en las dos para saber cuál era cuál: «Entornos y
despliegue» junto a «Entornos y despliegues», «Usuarios y permisos» junto a
«Usuarios y seguridad», «Consola de administración» junto a «Consola de
agente». Ahora cada una se llama por la pregunta que contesta: **Promoción
entre entornos** (llevarse una configuración de desarrollo a producción),
**Despliegues y desvíos** (qué hay desplegado en cada entorno y qué se ha
tocado a mano), **Identidad y seguridad**, **Administración**.

Y el **Editor de procesos** se llamaba «Procesos en curso», que es lo
contrario: los procesos en curso son las instancias en marcha, y ésas están
en «Procesos y orquestación».

**Las colas largas se trabajan por tandas.** En «Duplicados por resolver»
salen veinte parejas y un botón que dice **cuántas quedan**: «Ver 20 más ·
Viendo 20 de 100». Antes salían las cien de golpe, que son veinticuatro
pantallas de desplazamiento para una cola donde se decide de una en una. Una
cola así no se trabaja: se abandona.

**El producto escribe en castellano.** Los nombres de campo que vienen del
sistema —`forma_juridica_distinta`, `fecha_revision`— se escriben como se leen,
con sus tildes y sus eñes. Si ves «Direccion», «Tamano» o «Forma juridica», es
un fallo: avísanos.

**La pantalla de entrada se ve como el resto.** Hasta el 02-11-2026 era la
única con otra cara —otra paleta, otras formas— y salía oscura aunque tuvieras
el tema claro. Ahora respeta tu tema.

**El tamaño de la letra.** Desde el 02-11-2026 el producto escribe con siete
tamaños y **ninguno por debajo de 12 px**. Antes usaba once —con 10 y 11 px en
tres de cada cuatro textos— y había pantallas con nueve tamaños distintos a la
vez. Si ves una letra que no se lee, es un fallo: avísanos.

**Compacto o cómodo.** En tu perfil eliges la densidad. En compacto caben más
filas; en cómodo la tabla respira. Las dos escriben con la misma letra legible:
lo que cambia es el aire, no el tamaño del texto.

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

Una espera, un subproceso o un evento ya no dejan el proceso parado para
siempre: al llegar su hora, sigue.

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

Para **seguir con un proceso guardado**, elige su versión en «Abrir una versión
guardada»: se carga en el diagrama, y si es un borrador sale «Publicar la versión
N»; si está publicada, «Archivar la versión N» —deja de arrancar procesos
nuevos, y los que van en marcha terminan con ella—.

### Pasos que hacen cosas en el CRM

Un paso de tipo **servicio** crea o cambia registros: en su `operacion` se
escribe la petición como la haría la pantalla —por ejemplo `POST
/api/v1/opportunities` o `PATCH /api/v1/casos/@caso_id`—, en `entrada` lo que se
manda (puede usar `@variables` del proceso) y en `salida` el nombre de la
variable donde guardar lo que conteste. El ejemplo del editor trae uno.

- Actúa **con tus permisos**, los de quien arranca el proceso: no puede hacer
  nada que tú no pudieras hacer a mano, y en el historial del registro queda a
  tu nombre.
- **Validar** avisa si la operación no tiene esa forma o si la ruta no existe.
- Si el CRM rechaza la petición (un campo que falta, un permiso que no tienes),
  el paso falla con ese mensaje y lo ves en el historial de la instancia, en
  **Administrar › Automatización › Procesos y orquestación**, pestaña
  **Instancias**.
- Si el proceso lo lanza una **automatización** y la regla no dice quién la
  activó, el proceso arranca igual pero sus pasos de servicio fallan diciendo
  que **no se sabe con qué permisos actuar**: no se inventan.

### Pasar lo que está en marcha a una versión nueva

Cuando publicas una versión que corrige algo, lo que ya estaba en marcha sigue
con la suya. Para moverlo: **Administrar › Automatización › Editor de
procesos**, abre la versión **publicada** en «Abrir una versión guardada» y
pulsa **Migrar las instancias en vuelo a esta versión**.

1. Primero se **enseña sin tocar nada**: qué instancias pasarían (de qué
   versión vienen y en qué paso están) y cuáles **se quedan**, cada una con su
   motivo —está en un paso que la versión nueva no tiene, tiene una tarea
   pendiente con respuestas que ya no existen, está deshaciendo pasos…—.
2. Si te parece bien, **Migrar N a la versión X**. Las que se quedan terminan
   con su versión, como empezaron.

Hace falta permiso de administración de procesos, y cada instancia movida queda
apuntada en la auditoría con la versión de la que salió.

### Empezar desde una plantilla

Al final del **Editor de procesos** está la sección **Plantillas de flujo**:
procesos de ejemplo por sector —aprobación de descuento comercial, alta de
cliente con revisión de riesgo, devolución y abono, alta de proveedor, escalado
de caso urgente—, cada uno con la lista de **lo que no resuelve** (qué datos
necesita al arrancar, qué rol tendrás que cambiar).

1. Si la biblioteca está vacía, **Cargar las de serie** (hace falta permiso de
   administración de procesos).
2. Escribe la **clave** que tendrá tu copia y pulsa **Copiar como borrador**.
3. La copia se abre en el editor como **borrador tuyo**: ajústala, **Validar**,
   y **Publicar** cuando esté lista. Hasta entonces no la ejecuta nadie, y si
   la plantilla cambia más adelante, tu copia no.

### Lo que me toca aprobar

En **Administrar › Automatización › Procesos y orquestación**, la vista **«Me toca
decidir»**: lo vencido primero, con lo que hace falta para decidir. Abre una
fila para aprobar, rechazar o pedir cambios. En la aprobación ves quién decidió
cada etapa y, si alguien lo hizo por otro, en nombre de quién.

### Decidir desde el correo, sin entrar

Cuando te toca decidir, te llega un **correo con un enlace**. Lo abres desde el
ordenador o el móvil y ves qué se pide, en qué etapa y con qué datos; debajo,
**Aprobar**, **Pedir cambios** (escribe cuáles: sin comentario no se puede) o
**Rechazar**. No hace falta entrar al CRM ni tener la sesión abierta.

- El enlace **sirve una vez** y **caduca** (tres días de serie). Abrirlo no
  decide nada: sólo cuenta lo que pulses.
- Deja de servir también si la aprobación ya no espera tu decisión: otro la
  resolvió, ya votaste desde el CRM, pasó a la etapa siguiente o lo que se
  pedía cambió y hay que volver a aprobarlo —entonces te llega un correo nuevo—.
  En todos esos casos la página dice lo mismo, «este enlace ya no sirve», y lo
  tienes en tu bandeja del CRM si aún te toca.
- La decisión queda **a tu nombre**, apuntada como hecha desde el correo.
- **No lo reenvíes**: quien lo abra decide por ti.

Si no te ha llegado o caducó, quien administra procesos puede mandarte otro:
**Administrar › Automatización › Procesos y orquestación**, pestaña **Enlaces de
decisión**, botón **Nuevo**: la aprobación, el aprobador y, si se quiere, cuántas
horas vale. Sale por correo y la misma pestaña enseña a quién representa cada
enlace, cuándo caduca y si ya se usó.

### Tablas de decisión: la política, escrita como una tabla

Una tabla de decisión responde preguntas como «¿quién aprueba este descuento?»
o «¿qué tipo de IVA se aplica?» con reglas que se cambian sin tocar el proceso
que las usa.

**Administrar › Automatización › Procesos y orquestación**, pestaña **Tablas de
decisión**. Pulsa una fila para editarla, o **Nuevo** para empezar una.

1. **La tabla**: el nombre —la clave sale de él y es como la llaman los
   procesos; después no se cambia— y qué pasa **si casan varias reglas**: gana
   la primera, sólo puede casar una, gana la de más prioridad, varias si dicen
   lo mismo, o se acumulan todas.
2. **Columnas de entrada**: lo que se compara. La **expresión** dice de dónde
   sale el valor, por ejemplo `@oportunidad.importe`, y el **tipo** cómo se
   compara (número, texto, sí/no…).
3. **Columnas de salida**: lo que devuelve la tabla, por ejemplo «Aprobador».
4. **Reglas**: una fila por regla. En cada casilla de entrada, **+ condición**
   para poner una comparación (=, ≥, «está en»…); **+ y además** añade otra en la
   misma casilla, para un tramo («≥ 1000» y «< 5000»). Una casilla vacía es
   «cualquiera». En las casillas de salida, lo que sale si la regla casa. Las
   flechas suben o bajan la regla: con «gana la primera», el orden decide.
5. **Validar** dice si la tabla está bien formada y avisa de los **huecos**
   (valores que ninguna regla cubre), los **solapes** y las reglas que **nunca
   casarán** porque otra anterior las tapa.
6. **Probar**: escribe unos datos y pulsa **Probar con estos datos**. Se ve qué
   sale, qué regla acertó y, de cada una de las demás, en qué condición falló.
   Prueba la tabla tal como está en pantalla, **sin guardarla**.
7. **Guardar**. Desde ese momento, los procesos que la usan deciden con ella.

---

### Automatizaciones: cuándo corren y qué las dispara

En **Administrar › Automatización › Procesos y orquestación**, el selector de
vistas lleva tres vistas de automatizaciones:

- **Automatizaciones**: las reglas. Arriba, **«Instalar una plantilla de la
  biblioteca»** y **«Promover automatizaciones desde un sandbox»**; al abrir una,
  en **Más**: «Activar o desactivar una regla», «Ejecutar ahora sobre un
  registro», «Generar el secreto del webhook que la dispara» y «Probar una regla
  sin ejecutarla».
- **Plantillas de automatización**: la biblioteca por industria, con cuáles ya
  tienes instaladas.
- **Cola de automatizaciones**: lo diferido y lo programado, con su hora y su
  estado (pendiente, hecha, fallida o descartada).

**Condiciones con campos propios.** Al dar de alta una regla (**Nuevo**), en
**Más campos › Condiciones** pulsa **«Añadir una condición»**: cada fila es
campo, operador y valor. Con el **Objetivo** escrito, el desplegable **«Campo
propio…»** ofrece los campos que tu empresa ha añadido a ese objeto y, al
elegir uno, rellena el campo como `campos.<nombre>`. Los campos de serie
(`importe`, `estado`) se escriben en la caja de al lado.

**Cuándo corre (el «momento»).** *Inmediata* corre en el instante del disparo.
*Diferida* corre después de que se confirme lo que la disparó —si el alta se
deshace, no corre— y, si el administrador lo ha configurado, tras unos segundos
de espera (`AUTOMATIZACION_DIFERIDA_ESPERA_S`). *Programada* corre a la hora de
su horario (`programacion`, una expresión cron como «0 8 * * 1», los lunes a las
8), en la zona horaria de la empresa. Si el servicio estuvo parado y se saltó
varias horas, corre una vez al volver, no tantas como se perdió. Al encender una
programada, su ficha enseña cuándo correrá (`Próxima ejecución`).

**Una programada con condiciones recorre sus registros.** Si tiene condiciones
—«lead nuevo, sin dueño y creado hace más de 48 horas»— al llegar su hora mira
los registros de su objeto y corre **una vez por cada uno que cumple**: cada
aviso dice de qué lead es. Sin condiciones es de calendario —«los lunes, recuerda
revisar las oportunidades»— y corre una vez. Recorre los registros con los
permisos de quien la encendió; si no consta quién fue, en la cola sale «fallida»
con el remedio: apágala y vuélvela a encender. Para la antigüedad de una fecha
están los operadores «hace más de N horas» y «hace menos de N horas».

**Qué la dispara.** Creación y modificación, como siempre; **eliminación**,
cuando se borra un registro de ese objeto; **evento**, cualquier evento del
catálogo (por ejemplo `contract.renewal.due`, un contrato a punto de vencer);
**programada**, su propio horario; **manual**, con «Ejecutar ahora sobre un
registro» (pide el registro y los datos que miran sus condiciones; si está
apagada no corre); y **webhook**, cuando otro sistema llama a su dirección con el
cuerpo firmado. Para eso: «Generar el secreto del webhook que la dispara» enseña
**una sola vez** la dirección y el secreto; quien llama firma con HMAC-SHA256
`<momento>.<cuerpo>` en `X-Contecrm-Firma` y pone el momento en
`X-Contecrm-Momento`, igual que los webhooks que manda el CRM. Generarlo otra vez
invalida el anterior.

**Quién la activó.** Al encenderla queda guardado quién lo hizo y con qué
permisos: un proceso que lance la regla actúa con esa identidad. Si se apaga y la
enciende otra persona, pasa a ser esa.

**Plantillas.** «Instalar una plantilla de la biblioteca» se elige de una lista
(oportunidad en la recta final, lead nuevo al responsable, caso crítico, contrato
a punto de vencer, bienvenida a un cliente nuevo, recordatorio semanal). Las que
reparten trabajo piden **Responsable**. Llega **apagada**; si ya tienes una con
ese nombre no la pisa: instálala con otro nombre.

**Promover desde un sandbox.** Elige el sandbox y pulsa: es la **prueba en
seco**, que dice qué pasaría con cada automatización —crear, actualizar, sin
cambios, cuáles se apagarían— y da una **huella**. Para aplicarlo, vuelve a
abrirla con el mismo sandbox y pega la huella en «Más campos». Si algo cambió
entre medias, no se aplica nada. Lo que llega, llega apagado y queda en la
auditoría con el sandbox del que vino.

### Código propio: extensiones y endpoints

Cuando una regla no basta —un descuento por tramos que cambia cada trimestre,
un cálculo que viene de vuestro ERP—, en **Procesos y orquestación →
Extensiones** se escribe una función en JavaScript. Corre aislada: no ve
ficheros, ni la red, ni los datos de nadie más, y si tarda o gasta demasiado se
corta.

1. **Nuevo**: una clave (`descuento-por-volumen`), un nombre y, si la función
   tiene que crear o cambiar registros, con qué permisos — nunca más de los
   tuyos.
2. **Publicar una versión nueva del código** (en la ficha, panel *Versiones*):
   el código define `function main(entrada) { … }` y devuelve lo que quieras.
   Publicar **no** la pone en marcha: la anterior sigue funcionando.
3. **Probar la extensión con una entrada**: la ejecuta con los datos que le
   des y enseña lo que devuelve, sus `console.log` y lo que tardó. Si la
   función pide crear o cambiar registros, en la prueba **se enseñan y no se
   hacen**.
4. **Activar una versión**: desde ese momento se ejecuta ésa. Si algo va mal,
   **Volver a la versión anterior** —con el motivo— activa la anterior entera.
5. **Cómo va esta extensión**: cuántas veces se ha ejecutado, cuántas fallaron,
   cuántas se cortaron por tardar o gastar demasiado, las más lentas y lo que
   cuestan. En el panel *Las últimas ejecuciones* está cada una con su error.

Si la función tiene que cambiar datos, no los cambia ella: devuelve
`{acciones: [{metodo: "POST", ruta: "/api/v1/activities", cuerpo: {…}}]}` y el
CRM las hace con los permisos de la extensión.

**Endpoints propios.** En la pestaña del mismo nombre, un método y una ruta —por
ejemplo `POST precios/descuento`— hacen que el CRM conteste en
`/api/v1/propios/precios/descuento` con lo que devuelva la extensión. Se entra
con las mismas credenciales que el resto de la API y se puede exigir un permiso.
Si la extensión devuelve `{estado: 201, cuerpo: {…}}`, se contesta eso.

**Extensiones de otros.** Si una extensión viene de un proveedor, se da de alta
con origen *tercero*. Antes, en **Firmantes de confianza**, se pone la clave
pública del proveedor. Cada versión llega firmada; si la firma no corresponde
al código, no se acepta. Y no se puede activar hasta que la revise **otra
persona** que no sea quien la publicó, con una nota de qué ha mirado.

Hay un número de ejecuciones al mes por empresa; si se acaba, el CRM lo dice
con ese nombre y en qué ajuste se sube.

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

En **Administrar › Gestor de objetos › Objetos**, cada fila se abre. Dentro está
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
- **Probar un registro**, abajo del todo: rellena los campos y pulsa **Probar un
  registro**. Contesta lo mismo que contestaría al guardar —«Pasaría» o los
  problemas, cada uno en su campo— sin guardar nada. Marca «Como un cambio» para
  probar una edición, que no exige los obligatorios que no rellenes.

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

### Inicio

Va directo al contenido: no hay saludo. A la izquierda, lo ancho, está tu
trabajo —**lo que cierra esta semana** y **tu embudo**, con el importe por
etapa—; a la derecha, lo estrecho, lo que reclama atención: **lo vencido** y
**lo de hoy**.

El porcentaje que acompaña a cada etapa del embudo es **su peso sobre el
total**: «Negociación, 555 k · 38 %» quiere decir que el 38 % de lo que tienes
abierto está en negociación. No es la caída desde la primera etapa, porque un
embudo medido en dinero no siempre decrece.

> **Si eres comercial y no veías tu embudo**, era un fallo de permisos: el rol
> `comercial` no podía leer la definición del proceso de venta, así que el
> gráfico no se pintaba nunca —y sí se pintaba, vacío, para quien opera la
> plataforma y no vende nada. Arreglado el 01-11-2026.

---

### Las cosas se llaman como en Salesforce

Si vienes de Salesforce, el vocabulario es el suyo a propósito:

| aquí | lo que es |
|---|---|
| **Cuentas** | las empresas con las que trabajas |
| **Contactos** | las personas de esas empresas |
| **Candidatos** | lo que en inglés son los *leads* |
| **Oportunidades** | las ventas en curso |
| **Casos** | lo que atiende soporte |
| **Campañas**, **Segmentos** | marketing |
| **Informes**, **Paneles** | análisis |
| **Previsiones** | lo que se espera cerrar |
| **Socios** | el canal indirecto |
| **Configuración** | todo lo que se ajusta, detrás del engranaje |
| **Usuarios y empresa**, **Herramientas de plataforma**, **Entornos y despliegue** | los temas del árbol de configuración, como el Setup de allí |
| **Aplicaciones conectadas** | qué herramientas de la casa están enganchadas a este cliente |
| **Iniciador de aplicaciones** | el botón del nombre de la aplicación |

No es por copiar: es que un nombre propio obliga a aprender el producto antes
de poder usarlo, y eso no lo gana nadie. Las pantallas que **no existen en
Salesforce** —«Postventa», «Gobierno de la IA», «Contrato de la API»— conservan
su nombre: inventarles uno ajeno sería peor, porque además sería falso.

---

### Si la portada te sale vacía

Inicio contesta **«qué tengo yo hoy»**: tus actividades, tus oportunidades que
cierran esta semana, tu embudo. Si no tienes nada asignado todavía —es lo que
pasa con la cuenta de operación de la plataforma, que no lleva ventas— las
cuatro cajas salen vacías a la vez, y eso se lee como si el producto no
tuviera datos.

No es eso, y ahora lo dice: sale un aviso arriba explicando que no tienes nada
asignado, con un enlace a las oportunidades del equipo. El trabajo está; lo que
no hay es trabajo **tuyo**.

Si eres administrador y quieres que alguien vea su portada con datos, asígnale
cuentas y oportunidades: el campo es **Responsable**.

---

### Archivos: dónde está ese documento

**«Archivos»** está en la barra de Ventas. Es la lista de **todos** los
documentos del CRM, con un buscador por nombre de fichero. Hasta el
03-11-2026 un adjunto sólo se veía desde la ficha del registro al que
acompaña, así que para encontrar uno había que acordarse antes de a qué
cliente pertenece — que es justo lo que no se recuerda.

Lo que hay que saber para leerla:

- **Cada fichero dice de qué cuelga**, con el nombre del registro y el enlace
  para ir allí: «pliego.txt» no dice nada, «pliego.txt de Talleres Ibéricos»
  sí. Debajo, de qué clase de registro es —una cuenta y una oportunidad suya
  son dos fichas distintas—.
- **Si el registro ya no está, lo dice** en vez de enlazarlo: el enlace
  llevaría a una ficha que no existe. Y si no se ha podido mirar, dice eso
  otro: no es lo mismo, y afirmar que algo se ha borrado cuando sigue ahí
  sería peor que no decir nada.
- **De cada documento sale la versión vigente**, no todas: un documento de
  nueve versiones ocuparía nueve líneas y escondería los demás. Las versiones
  se ven desde su ficha.
- **Si algún servicio no contesta, sale un aviso arriba.** Los documentos los
  guarda cada módulo por su cuenta: una lista corta y una lista incompleta se
  leen igual, y aquí no pueden.
- **Un fichero marcado como infectado no se puede abrir** desde aquí. El
  servidor ya se niega a entregarlo; ofrecer el enlace sería ofrecer un error.
- **Se busca por el nombre del fichero**, no por su contenido ni por el
  cliente.

---

### Dar de alta donde el registro lleva un código

Casi todo se da de alta con el botón **«Nuevo»** del listado. Hay cosas que
además **llevan un código que lo eliges tú** —un riesgo, un control, una regla
de segregación, una política de acceso—: el formulario te pide ese código el
primero, y con él se guarda.

Dos consecuencias que conviene conocer:

- **El código identifica el registro.** Dar de alta con un código que ya
  existe no crea otro: actualiza el que hay. Es a propósito —así se puede
  reescribir un control sin duplicarlo— y conviene saberlo antes de reutilizar
  un código.
- **Algunas de estas altas piden volver a verificar tu identidad.** Cambiar
  roles, permisos o políticas de acceso, crear una clave de API, exportar en
  masa o borrar en bloque lo exigen. No hace falta salir: se abre un recuadro
  **«Confirma que eres tú»**, escribes el código de 6 cifras de tu app de
  autenticación y la operación sigue sola. Vale unos minutos para las
  siguientes. Si no tienes la app activada, el recuadro te lo dice y te lleva a
  **Puesto** para activarla. Un código equivocado cuenta como intento fallido,
  igual que al entrar.

Hasta el 04-11-2026 esas cuatro no se podían dar de alta desde el producto,
aunque el sistema las admitía.

---

### Cuando algo no se guarda

Si al guardar falta algo o un valor no vale, **el aviso sale en el campo**, en
rojo y justo debajo de su etiqueta: «Falta este campo», «Tiene que ser un
número», «No puede pasar de 120 caracteres». Arriba sigue saliendo el aviso
general, y el **«Detalle técnico»** lleva la respuesta cruda del servidor para
quien la necesite.

Hasta el 04-11-2026 sólo salía el aviso de arriba —«Los datos enviados no son
válidos»— y había que adivinar cuál de los campos era.

Dos cosas que conviene saber:

- **Los campos obligatorios van delante** y el resto detrás de «Más campos
  (N)». Al **editar** no hay obligatorios —se manda sólo lo que cambias—, así
  que delante van los campos principales del registro y el resto detrás.
- **Lo que dejes en blanco no borra lo que había.** Guardar con un campo vacío
  que no has tocado deja el valor que tenía.

---

### Escribir en un registro

Toda ficha que admite conversación —un caso, una cuenta, una oportunidad, un
presupuesto, una orden de trabajo— lleva una pestaña **«Comentarios»** al
final, al lado de «Relacionado» y «Detalles». Ahí se escribe: una nota de lo
que se ha hablado, una pregunta a un compañero, el resultado de una llamada.
Con `Intro` se manda.

Cada mensaje se lee como lo que es: **quién lo escribió, cuándo, y qué dijo**.
Los internos —los que no ve el cliente— van marcados, y los editados también.

Mencionando a alguien con `@` le llega un aviso, y la mención le sale en **«Mis
menciones»**, en la arroba de la barra de arriba.

Hasta el 03-11-2026 esa pestaña sólo estaba en las fichas genéricas: en un
caso, en una cuenta o en una oportunidad **no había dónde escribir**, aunque
el sistema guardara comentarios desde el primer día.

---

### Seguir un registro, y saber qué sigues

En la ficha de cualquier registro, arriba a la derecha, hay un botón
**«Seguir»**. Lo que sigues es lo que te avisa cuando cambia, por los canales
que tengas elegidos. Al seguirlo pone **«Siguiendo»**, y se deja de seguir
pulsándolo otra vez.

**Si eres el responsable del registro no dejas de serlo**: al dejar de
seguirlo lo que pasa es que dejan de llegarte los avisos, y el registro sigue
saliendo a tu nombre. El botón lo dice debajo, para que no parezca que no te
ha hecho caso.

**Lo que sigues está en la barra de arriba**, en el icono de la campana
encendida, al lado de la arroba de tus menciones. Ahí sale cada registro **con
su nombre y su enlace**, lo que esté silenciado marcado, y de lo que eres
responsable también. Si alguno se borró, la fila lo dice en vez de
desaparecer: una lista más corta sin explicación hace pensar que se ha perdido
algo.

Hasta el 03-11-2026 el botón no existía: se podía ver lo que uno seguía —en
una pestaña de administración, sin los nombres— y no se podía seguir nada.

---

### La ficha de un registro

Al abrir cualquier registro, lo primero es el **panel de datos clave**: qué es
—CUENTA, OPORTUNIDAD, CASO—, cómo se llama, y debajo hasta cinco campos que
importan de ese objeto, sin entrar en ninguna pestaña. Son los mismos campos
que salen como columnas en su listado: si el producto decide que de una
oportunidad importan el importe y la etapa, importan en los dos sitios.

**Si el registro tiene etapas, salen como un recorrido**, no como una palabra
suelta: lo ya pasado en azul claro, dónde estás en azul oscuro, y lo que queda
en gris. Una etapa dice dónde estás; un recorrido dice además cuánto queda y
qué viene después.

En una **oportunidad** los pasos son los del pipeline que tenga asignada, con
las etapas que tu empresa haya configurado. No es una lista escrita en el
programa: si Administración añade una etapa, aparece aquí.

**Arriba del todo está de dónde viene**: el listado del que salió y su
identificador corto, para volver de un clic y para pegarlo en una incidencia.

**Cada dato sale una sola vez.** Las insignias pegadas al nombre y la fila de
datos de debajo no repiten el mismo campo; si el estado es uno de los datos
clave, no sale además como etiqueta.

**Los importes llevan la moneda del registro**, no la de tu navegador: una
oportunidad en dólares se escribe en dólares.

**Las fechas llevan el año entero.** Antes salían como `07/12/16`, y una fecha
de vencimiento con el año en dos cifras es ambigua de verdad.

**Los campos del sistema se leen.** `created_at`, `updated_by` y compañía salían
en inglés —«Created at», «Updated by»—; ahora son «Creado», «Modificado por».
Y el sufijo `_at`, que el modelo usa para marcar una fecha, ya no se enseña:
donde ponía «Vence at» pone «Vence».

**Editar, eliminar y lo demás están arriba a la derecha**, dentro del panel de
datos clave: «Editar», y un «Más» con todo lo que el servidor permita hacer con
ese registro. Están ahí mires la pestaña que mires. Antes colgaban debajo de
las pestañas y sólo dentro de una de ellas, así que para editar desde otra
había que volver.

#### Las cuatro pestañas

Debajo del panel están las pestañas del registro, y cada una contesta una
pregunta distinta:

- **Relacionado** — lo que cuelga de él: sus líneas, su equipo, sus
  direcciones, sus adjuntos y los documentos enlazados. Cada lista lleva su
  nombre y **cuántos hay entre paréntesis**, así que se sabe si hay algo sin
  abrirla. Se pliegan y se despliegan.
- **Detalles** — todos sus campos, en dos columnas, con el rótulo encima del
  valor. Debajo, lo que el servidor no te ha devuelto, qué ha cambiado campo a
  campo y cómo estaba el registro entero en una fecha.
- **Actividad** — apuntarle una llamada, una reunión, una nota o un correo, y
  preguntarle a la IA sobre ese registro. **Sólo sale donde tiene sentido**: lo
  dice el servidor, no una lista escrita en la pantalla. No hay nadie al otro
  lado de un calendario laboral.
- **Comentarios** — la conversación sobre el registro.

**Se abre por «Relacionado» cuando hay algo que enseñar**, que es lo que se
busca casi siempre al abrir un registro; si de ese objeto no cuelga nada, se
abre por «Detalles». En cuanto pulsas una pestaña, manda la que pulsaste.

**Las catorce fichas se abren igual.** Cuenta, proveedor, oportunidad,
presupuesto, caso, orden de trabajo, activo, campaña, segmento, artículo,
sobre de firma, liquidación, objeto del modelo e instancia de proceso: todas
con la línea de «de dónde viene», el panel de cabecera con sus botones a la
derecha y las pestañas debajo. Antes eran dos cabeceras distintas según la
pantalla, y quien usaba las dos creía que eran dos productos.

Las que son un registro del catálogo llevan **«Relacionado» y «Detalles»**:
«Relacionado» es lo que esa pantalla ya enseñaba —el 360 del cliente, las
líneas de la oportunidad, el reloj del caso— y «Detalles» son sus campos.
Hasta el 02-11-2026 ahí no había forma de leerlos: para ver el teléfono o la
web de una cuenta había que pulsar «Editar».

**Un hueco se escribe con una raya.** Donde no hay valor pone «—», nunca la
palabra `null`. Si lo ves en algún sitio, es un fallo.

---

### Las listas: ordenar, elegir columnas y cambiar de vista

**Vistas guardadas.** Arriba del listado, en grande, está la vista que estás
mirando. De entrada pone **«Todo»**, que es la lista completa. Filtra, ordena y
elige columnas como quieras, y después abre ese desplegable y pulsa **Guardar
esta vista…**: le pones nombre y a partir de ahí la tienes ahí para siempre.

- **Se guardan en el servidor**, no en tu navegador: las tienes igual desde
  otro ordenador.
- Al guardarla decides **si la ve sólo quien la guarda o todo el equipo**. Para
  compartirla hace falta permiso; para guardarte una tuya, no — es tan tuyo
  como ordenar una columna.
- **La vista de otra persona no la ves.** El nombre de una vista ya cuenta lo
  que alguien está mirando.
- Cada vista **recuerda sus columnas y su orden**. Las mismas cuentas vistas
  como «Mi cartera» y como «En riesgo» no se miran igual.
- Si marcas una como la de entrada, es la que se abre al llegar — salvo que
  llegues por un enlace que ya trae un filtro dentro: ése manda.

Encima, en pequeño, está **qué objeto** estás mirando (Cuentas, Contactos,
Visitas…). Se cambia de tarde en tarde, así que va discreto; la vista, que se
cambia cada día, es lo grande.


Casi todo en contecrm es una lista: cuentas, oportunidades, casos, órdenes de
trabajo. Todas funcionan igual, a propósito — lo que aprendas en una te sirve en
las demás.

**Ordenar: pulsa la cabecera de la columna.** Una vez, de menor a mayor. Otra
vez, de mayor a menor. A la tercera vuelve al orden con el que llegó, que
normalmente es lo más reciente primero y no siempre querrás perderlo. La flecha
de al lado dice cómo está ordenada.

Ordena por lo que el dato **es**, no por cómo se escribe:

- Los importes se ordenan como números: 900 va antes que 1.000, no después.
- Las fechas se ordenan como fechas.
- Los nombres se ordenan con el alfabeto de tu idioma: «Ávila» va donde le toca
  y no detrás de «Zamora».
- **Lo que está vacío se queda al final**, ordenes hacia arriba o hacia abajo.
  Si ordenas por «fecha de cierre» de más reciente a más antigua, lo que quieres
  arriba es la más reciente, no los cincuenta registros sin fecha.

contecrm recuerda por qué columna ordenaste **en cada pestaña por separado**:
el orden que te va bien en Casos no es el que te va bien en Cuentas.

**Los rótulos están escritos en castellano.** Un nombre de columna de base de
datos no admite tildes ni eñes —se llama `direccion`, `telefono`, `tamano`— y
hasta el 01-11-2026 salía así a la pantalla: «Direccion», «Tamano», «Sector
codigo», «Owner id». Ahora se escriben bien, y lo mismo vale para los **valores**
que llegan como identificador: un caso en `esperando_cliente` se lee «Esperando
cliente». Si ves alguno mal escrito, es un fallo y se arregla.

**Cambiar un dato sin salir de la lista.** Al pasar por encima de una celda
aparece un lápiz: se pulsa, se cambia y se guarda con **Intro** o saliendo del
campo. `Esc` cancela. Para corregir un estado o un importe ya no hace falta
abrir la ficha, buscar «Editar», cambiar, guardar y volver.

Sólo salen con lápiz los campos que el servidor deja cambiar, y el control es
el que les toca: una lista cerrada sale como desplegable y una fecha como
calendario. La primera columna no se edita ahí —lleva el enlace que abre el
registro, y dos acciones distintas a tres píxeles una de otra se pulsan mal.

Si el servidor rechaza el cambio, **el valor vuelve al anterior y la celda lo
dice**. Un cambio que parece guardado y no lo está es peor que uno que falla a
la vista.

**Cada fila tiene su menú.** Al final de la línea hay un `⌄` con **Abrir** y
**Editar**. «Editar» lleva la ficha ya abierta en modo edición, no a la ficha
para que busques el botón: si lo que querías era cambiar un dato, ya estás
dentro.

**Buscar dentro de la lista.** Arriba a la derecha hay una caja que filtra lo
que tienes delante según escribes, mirando todas las columnas. El recuento te
dice sobre cuántos ha buscado —«4 de 50 cargados»— y eso importa: busca en lo
que se ha traído, no en toda la base. Para buscar en todo, usa **Filtrar**, que
pregunta al servidor.

**Cuántos y en qué orden.** Debajo de los controles pone «50 elementos ·
Ordenado por Nombre, de menor a mayor». Con cincuenta filas delante, «¿por qué
sale esto primero?» es la pregunta inmediata.

**Las columnas las eliges tú.** El botón **Columnas** dice cuántas se ven de
cuántas hay. Las que no tienen dato en ninguna de las filas que estás mirando no
se ofrecen: una columna vacía es ruido. Tu elección se recuerda por pestaña.

**Dos formas de mirar: tabla y tarjetas.** La lista se abre en **tabla**, que es
la que deja ver más registros de una vez y la única que se puede ordenar. Si
prefieres tarjetas, el selector está arriba a la derecha y contecrm lo recuerda
para esa pestaña: no tendrás que volver a elegirlo.

**La lista se recorre con la página**, hasta abajo. Antes se cortaba dentro de
una caja con su propia barra de desplazamiento, y quedaban hueco en blanco
debajo y filas que no se veían.

**Nuevo** está arriba de la lista, a la izquierda, junto al recuento de filas. El
formulario de alta se abre justo debajo, sobre la propia lista.

> **Si la lista está vacía** no verás el botón «Nuevo» arriba: lo ofrece el
> propio recuadro que te dice que no hay nada, para que no haya dos botones
> iguales a diez centímetros uno de otro.

---

### Los botones de arriba de una lista

Encima de cada lista, al lado de **Nuevo**, salen las cosas que se hacen sobre
la lista entera y no sobre una ficha concreta: simular un cambio antes de
publicarlo, comprobar algo sin guardarlo, lanzar un recálculo, declarar una
regla.

- **No están escritos uno a uno**: la pantalla pregunta al sistema qué admite
  esa lista y ofrece lo que haya. Si mañana se añade algo, aparece solo.
- **Algunos piden datos antes.** «A qué proveedor iría este encargo» necesita
  que le digas el encargo. Al pulsarlo se abre un formulario corto; el que no
  necesita nada se hace al primer clic.
- **Sólo ves lo que tu perfil puede hacer.** Un botón que luego dice que no
  tienes permiso es peor que no tenerlo.
- **Lo que no se deshace pregunta antes**, y después te dice qué contestó el
  sistema. Una acción que no responde nada deja sin saber si pasó algo.

Hasta el 04-11-2026 aquí sólo salían las que no pedían ningún dato. El resto
existían y no había forma de llegar a ellas desde ninguna pantalla: eran **50**,
entre ellas comprobar un contenido antes de mandarlo o ver dónde duele si un
proveedor falla mañana.

### Mover una oportunidad de etapa

El camino de etapas que sale debajo del nombre —Cualificación, Análisis
técnico, Oferta presentada…— **se pulsa**. Un clic en la etapa a la que quieres
llevarla y se mueve; no hace falta entrar a editar.

La etapa en la que estás no se puede pulsar, porque no haría nada. Y si el
sistema no deja el movimiento —criterios de salida sin cumplir, una etapa ya
cerrada— te lo dice en vez de quedarse callado.

**El historial guarda cada movimiento**, con cuánto se deslizó la fecha y
cuánto cambió el importe. Si se movió sin motivo escrito, el historial lo dice:
una etapa que cambió y nadie puede explicar por qué es la que no se sostiene en
un comité.

### Que no te pida el código cada vez en tu equipo

Al entrar con el código, marca **Recordar este equipo**. Si tu empresa lo
permite, las siguientes veces desde ese navegador no te lo pedirá; te lo volverá
a pedir desde otro equipo, o si cambia algo de la entrada (la red, el país, mucho
tiempo sin entrar). Si tu empresa no lo permite, entras igual y no se recuerda.

### Poner y quitar tu segundo factor

Está en **Puesto de trabajo**, que es la pantalla de tu propio acceso —no en
«Seguridad», que es la vista de quien administra la empresa—.

1. Pulsa **Activar el segundo factor**. Sale un código largo: apúntalo en tu
   autenticador (Google Authenticator, 1Password, el que uses) o abre el enlace
   desde el móvil, que lo mete solo.
2. **Guarda los códigos de recuperación.** Se enseñan una sola vez. Con uno de
   ellos entras el día que pierdas el móvil.
3. Escribe el número de seis cifras que te dé el autenticador y confirma. A
   partir de ahí, al entrar se te pedirá ese número además de la contraseña.

Para quitarlo o cambiar de autenticador, el mismo sitio: **Quitar el segundo
factor**. Hace falta haberte verificado hace poco —si acabas de activarlo o de
entrar con tu código, vale—; si no, el sistema te lo dirá y basta con volver a
entrar con el código. Si tu empresa exige segundo factor, no se puede quitar: te
lo dice en vez de dejarte sin poder entrar.

Hasta el 04-11-2026 esto **no se podía hacer desde ninguna pantalla**: el
sistema sabía activarlo por API y nadie lo llamaba, y quitarlo no existía en
absoluto — quien lo activaba se quedaba sin vuelta atrás.

### Cuando una pantalla enseña más de una tabla

Algunas pantallas contestan a más de una pregunta a la vez, y entonces verás la
lista principal arriba —la que puedes filtrar, ordenar y exportar— y debajo las
demás, cada una con su título.

«Vencen pronto» es el ejemplo claro: arriba lo que está a punto de vencer, que
es sobre lo que hay que actuar, y debajo lo que ya venció. Son dos listas
porque son dos cosas distintas, y mezclarlas haría perder de vista la urgente.

Hasta el 04-11-2026 esas pantallas enseñaban **una sola fila** con todo metido
dentro de una celda. No faltaba el dato: no se podía leer.

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

### Cómo estaba un registro en un momento dado

En la ficha de cualquier registro, además de «qué ha cambiado» hay un apartado
plegado que reconstruye **cómo estaba entero** en una fecha. No sale abierto a
propósito: sólo unos pocos tipos de registro guardan ese rastro completo
—guardarlo de todo multiplicaría el trabajo del sistema por algo que casi nadie
consulta— y para los demás dirá que no está encendido.

Lo que de verdad hay que mirar ahí es **si la reconstrucción cuadra**. Si no
cuadra, significa que alguien cambió el dato por fuera del sistema —un arreglo
a mano, una migración— y desde ese momento el rastro ya no sirve como prueba,
aunque siga contestando con la misma seguridad. Cuando pasa, se dice en rojo y
con el campo concreto que no coincide.

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

### El calendario: tu mes de un vistazo

«Calendario» está en la barra de Ventas, al lado de «Actividades». Es la misma
materia vista de otra forma: allí la lista, aquí los días unos al lado de
otros. Hasta el 03-11-2026 sólo estaba la lista, y la pregunta de una agenda
—«¿qué tengo el jueves?», «¿qué semana tengo cargada?»— no se contestaba
leyendo una lista ordenada por fecha.

Lo que hay que saber para leerlo bien:

- **No todo lo que sale ese día pasa ese día.** Una reunión o una visita
  **empiezan**; una tarea o una llamada por devolver **vencen**. Cuando en el
  mes hay de las dos clases, las que sólo vencen llevan un reloj. Si todas son
  de la misma clase el reloj no sale: una marca que llevan todas no distingue
  nada.
- **Se piden las seis semanas que se ven**, no el mes. Los días de los bordes
  —el final del mes anterior y el principio del siguiente— traen lo suyo. Si
  sólo se pidiera el mes, esas casillas saldrían vacías con la misma cara que
  un día sin nada, y «no hay» y «no se ha mirado» no pueden leerse igual en
  algo que se usa para decidir que hay hueco.
- **Si el mes no cabe entero, lo dice.** Sale un aviso con cuántas se están
  enseñando. Acotar con «Sólo las mías» suele bastar para verlo completo.
- **Un día cargado se abre abajo**, con todo lo de ese día, pulsando el «+n»
  de su casilla. En la casilla caben tres.
- **Lo completado sale tachado**, para que un día lleno no parezca pendiente.

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


### Programar el envío de una campaña

**Marketing → Campañas → la campaña → Programar el envío.** Eliges la plantilla
y pulsas «Programar a la mejor hora». Cada persona queda programada a su hora y
por su canal; la tabla «Envíos programados» dice por qué (su historial, lo que
pidió o el valor por defecto) y, al despachar, por qué dominio, remitente y
servidor salió. «Por dónde sale cada clase» enseña si lo promocional y lo
transaccional van separados.

**Sale solo, a su hora.** No hace falta pulsar «Despachar»: cada minuto (ajuste
`envios_despachar_cada_s`) se manda lo que ya toca, **en tu nombre y con tus
permisos de cuando lo programaste**. Si en la tabla un envío sigue «programado»
con el motivo «No consta quién lo programó», es de antes del 09-11-2026: vuelve
a programarlo (o despáchalo a mano) y saldrá. Lo mismo con los recorridos: al
«Publicar» quedan a tu nombre y avanzan solos; uno publicado antes de esa fecha
no avanza solo hasta que alguien lo vuelve a publicar.

### Dibujar un recorrido

**Marketing → Campañas → Recorridos → Nuevo.** Pones la clave y el nombre (y
«Por cuenta» si es B2B) y se abre el lienzo: añades nodos por tipo, eliges sus
salidas a la derecha, los colocas con las flechas, «Guardar el lienzo» y
«Publicar». Debajo, el resultado de cada prueba A/B con su ganadora, «Meter a
alguien» y «Quién está dentro».

### Ver un correo como le llegará a alguien

**Marketing → Contenido y gobierno → Plantillas → la plantilla.** En «Vista
previa con datos reales» buscas un contacto y eliges el cliente de correo
(escritorio, móvil, sin imágenes, modo oscuro). A la derecha, la puntuación de
spam regla a regla, las recomendaciones y por dónde sale.

### Atribución de un lead

**Ventas → Leads → el lead → Atribución de la venta.** Eliges el modelo; el
importe sale de su oportunidad si se convirtió.

### Audiencias publicitarias

**Marketing → Segmentos → Audiencias publicitarias → Nuevo.** Eliges el
segmento y la plataforma (una conexión de Integraciones) y «Dar de alta»; luego
«Sincronizar». El historial dice en cada vuelta altas, bajas y quién se quedó
fuera por falta de consentimiento o por supresión.
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

### Si la pantalla dice que el gestor documental no responde

Las aprobaciones de contenido se apoyan en el gestor documental, que es una
pieza aparte. Cuando no contesta, la pantalla **te lo dice con esas palabras y
con la dirección a la que ha llamado**, en vez de salir vacía. La diferencia
importa: una lista vacía te hace pensar que no hay nada pendiente de aprobar, y
lo que pasa es que no se ha podido preguntar.

No es nada que puedas arreglar desde el CRM, y tampoco significa que hayas
perdido nada: lo que esté en curso sigue ahí y aparecerá en cuanto el gestor
vuelva. Pásale el aviso a quien lleve la instalación — la dirección que sale en
el mensaje es justo lo que necesita.

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

### Lo que falta para cerrar, y qué hacer en cada etapa

En la ficha de una oportunidad, **«Qué falta para poder cerrar»** es la lista de
preguntas de la metodología de su embudo (MEDDIC, BANT…). Marca las que ya
tienes contestadas: la puntuación sube y el «siguiente paso» pasa a la
siguiente que más pesa. Debajo salen **los pasos de la etapa** en la que está.
Las preguntas y los pasos los define tu administrador en **Administrar ›
Plataforma › Metodologías y playbooks**.

### Cambiar el estado de una oportunidad o de un lead

En la cabecera de la ficha, debajo del nombre, está el **estado actual**. Pulsa
encima y elige a cuál pasar: sólo salen los que tu empresa permite desde el
estado en que está. Si ese paso pide motivo, te lo pide ahí mismo.

Para **ganar o perder** una oportunidad, muévela a la etapa final; para
**convertir o descartar** un lead, usa sus botones. Hacen más cosas que cambiar
el estado (la lección aprendida, el bloqueo, la cuenta nueva).

En un **caso de soporte** es igual: el estado de la cabecera es un desplegable.
Si lo pasas a un estado de pausa —«Esperando cliente»— el reloj del SLA se
para; al cerrarlo te pide el motivo, y al volver a trabajar uno cerrado te pide
por qué y cuenta como reapertura.

Y en una **actividad**: el desplegable de la cabecera la empieza, la completa,
la cancela (te pide por qué) o la retoma.

En un **presupuesto**, el desplegable sirve para marcar que el cliente lo
rechazó (te pide el motivo) y para los estados propios de tu empresa;
enviar, aceptar y hacer otra versión siguen en sus botones. En un
**contrato**, para suspenderlo, terminarlo (ambos con motivo) o reactivarlo.

**Si tu presupuesto se queda «En aprobación»**: lo aprueba quien diga tu
empresa —de serie, tu responsable— desde Automatización › Procesos y orquestación › Aprobaciones.
Cuando lo aprueba, pulsa «Enviar» otra vez. Si lo rechaza, o si no hay nadie
que pueda aprobarlo, vuelve a borrador y arriba de la ficha pone por qué.

Quién decide qué estados hay, cómo se llaman y a cuáles se puede pasar: el
administrador, en **Administrar › Plataforma › Estados de los objetos**. Y
las etapas del embudo —cuántas hay, su probabilidad y qué hace falta para salir
de cada una—, en **Administrar › Plataforma › Embudos y etapas**.

### Por qué se perdió (o se ganó): las lecciones aprendidas

Dónde: **Ventas › Lecciones aprendidas**. Y dentro de cualquier oportunidad
cerrada, el panel **«Por qué se perdió»** (o «se ganó»), con el botón para abrir
su lección.

1. Arriba ves **lo que se repite**: los factores que más pesan en las perdidas y
   en las ganadas, y en qué etapa se pierde. Cada gráfica tiene «Ver como
   tabla», y debajo, siempre, el detalle de una barra: la primera, hasta que
   pasas por encima de otra.
2. Debajo, la lista. Es como la de oportunidades: **Filtrar** (por resultado,
   estado o motivo), buscar, elegir columnas y exportar. Para ver lo que te toca
   firmar, filtra por estado «pendiente».
3. Al abrir una lección ves **en qué se apartó de las ganadas**, con el número,
   y debajo todo lo que pasó: etapas y días, presupuestos y descuentos, quién
   decidía y con qué postura, la competencia y la actividad.
4. **Si es tuya y está sin firmar**: pulsa **«Proponer con IA»** para tener un
   borrador hecho con el expediente, corrígelo y pulsa **«Firmar la lección»**.
   En una perdida, «Qué pasó» y «Qué haríamos distinto» son obligatorios.

Una lección firmada **no se cambia**: es lo que se sabía al firmarla. Si algo
estaba mal, se dice en la siguiente.

**Los factores los decide tu empresa.** En **Ventas › Lecciones aprendidas**,
pestaña **«Factores de una lección»**, están los que se pueden marcar al firmar
(precio, descuento tardío, competidor…). Quien administra puede añadir los
suyos —por ejemplo separar «condiciones de pago» de «precio»— o desactivar los
que no use; desactivar no borra, y las lecciones que ya lo llevan lo siguen
enseñando. La propuesta de la IA elige entre los de tu empresa.

**En una oportunidad abierta**, el panel **«Lo que dicen las lecciones»**
enseña:

- los **avisos** que han salido al crearla, al cambiar de etapa o al mandar el
  presupuesto;
- las lecciones del **mismo cliente** y las **parecidas** de otros, con cuánto
  se parecen. Pincha una para ver su expediente entero;
- con **«Qué hacer y qué no, con IA»**, consejos concretos, cada uno con la
  lección de la que sale.

Los avisos también te llegan como notificación si la oportunidad es tuya. Y
en **Ventas › Lecciones aprendidas**, el selector de arriba a la izquierda
lleva a **Avisos** y a **Resúmenes**, el resumen periódico para quien dirige.

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

### Mandar a firmar desde la oportunidad

En **Ventas › Oportunidades**, abre la oportunidad y baja a la tarjeta **«La
firma»**. Pulsa **«Enviar a firma»**, elige qué se firma —por defecto, el último
presupuesto vivo—, escribe el nombre y el correo de cada firmante y pulsa
**«Crear el sobre»**. Con «Mandarlo ya» marcado sale al proveedor; sin marcar,
queda preparado.

La tarjeta dice en qué está la firma (con un enlace al sobre) y, **antes de
mandar**, a qué etapa pasará la oportunidad cuando se firme. Si dice que sólo se
marcará, es que su embudo no tiene etapa para una firma completada: se
configura en **Administrar › Usuarios y empresa › Administración**, ajuste
`firma_etapa_por_embudo`. Si la firma se completa y la etapa no puede moverse
—faltan datos que la etapa exige—, la tarjeta dice por qué.

### Las renovaciones se abren solas

Cuando un contrato llega a su preaviso, aparece sola una oportunidad
**«Renovación CTR-…»** en el embudo de renovaciones (o en el de por defecto),
con el importe del contrato y su vencimiento como fecha de cierre. Se trabaja
como cualquier otra oportunidad, en **Ventas › Oportunidades**.

Para no esperar a la revisión periódica, abre el contrato (**Ventas ›
Contratos** y pulsa en él) y, en el bloque **Renovación**, pulsa **Revisar
este contrato**. Sólo se revisa ése: si ha llegado su preaviso, se abre la
oportunidad y sale el enlace **abrirla en el embudo**; si no, te dice que
todavía no toca o por qué no se ha revisado.

Las oportunidades que das de alta tú quedan a tu nombre si no eliges otro
dueño. Así cuentan en tus objetivos y en tus comisiones.

### Si una firma se sostiene, o sólo lo parece

Al abrir un sobre, lo primero que sale no es si está firmado: es **si esa firma
se puede verificar**. Hacen falta las dos huellas —la de lo que se mandó y la
de lo que se firmó— y si falta alguna, la firma no se puede comprobar aunque el
estado ponga «firmado». Es la diferencia entre un documento firmado y uno que
lo parece, y no se nota mirando el estado.

Lo demás que hay dentro, por el mismo motivo:

- **El nivel de firma** (simple, avanzada, cualificada). En una lista valen lo
  mismo; ante un juez, no.
- **Cómo se identificó a cada firmante.** Una firma sin identificación es una
  casilla marcada por alguien con acceso a ese correo.
- **Qué pieza de la prueba falta**, dicho con esa palabra. Un hueco en blanco
  se lee como «aquí no aplica», y lo que significa es que falta un eslabón.

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
- **Por jerarquía**: comercial, equipo, región y compañía. En el panel **Por
  jerarquía** eliges de dónde sale el organigrama —**los territorios** o **la
  jerarquía de mando**— y sale el árbol con lo que suma cada rama. El total de
  la compañía va arriba y aparte: lo que no cuelga de ninguna rama sale debajo
  con el nombre de quien lo lleva, y lo que no es de nadie, con su importe. Si
  la jerarquía de mando sale vacía, el panel lo dice: no es que nadie tenga a
  nadie a su cargo, es que no ha llegado ningún cambio de organigrama.

---

## Candidatos y trabajo diario (sección 3.3)

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
  Lo que tienes que escribir tú es qué se habló. Si eliges **Número erróneo**
  (**Clientes › Contactos ›** el contacto **› Llamar**, y al colgar **Cómo fue ›
  Número erróneo › Anotar y cerrar**), el teléfono de la ficha queda marcado como
  erróneo y debajo lo dice; si no se pudo —la llamada no era de un contacto o no
  puedes editar su ficha—, dice qué falta para que lo hagas a mano.
- **Si contesta al correo, sale de la cadencia.** Con tu buzón conectado no
  tienes que hacer nada: el correo que te llega de alguien que está en una
  cadencia lo saca de ella, una sola vez, aunque no sea todavía un contacto.
- **El plan conjunto con el cliente**: los pasos acordados con fechas, con una
  condición — **tiene que haber pasos suyos**. Un plan donde todo es nuestro es una
  lista de seguimiento interna, y lo valioso es justo lo incómodo: que el cliente
  ponga fecha a su parte.
- **Y la revisión de oportunidad**, que pregunta lo que nadie pregunta: qué puede
  salir mal y qué falta por saber. Queda registrada para poder compararla con lo
  que pasó — si lo que se revisa al 80 % se gana la mitad de las veces, ese 80 % no
  significa 80 %.

### Un candidato que ya existe

**Ventas › Candidatos › Nuevo.** Si lo que escribes se parece a un candidato
que ya está —el mismo correo, el mismo teléfono aunque lo escribas con otros
espacios, o la misma persona en la misma empresa— o a un contacto que ya es
cliente, al pulsar **Guardar** el formulario no se cierra: enseña con quién
coincide y en qué, con un enlace a cada uno. Si es el mismo, ábrelo y trabaja
sobre ése. Si de verdad es otro —dos personas que comparten la centralita—,
pulsa **Es otro, crearlo igual**: se crea y queda apuntado que lo decidiste tú.

Los que entran solos por un formulario de la web o por el chat no te
preguntan: según cómo lo haya dejado tu administrador, el nuevo entra
señalado como **posible duplicado** —en su ficha, en «Detalles», dice de qué
y por qué— o lo que llega se añade al candidato que ya existía. No se pierde
nada de lo que llegó.

### El formulario de contacto de tu web

Los candidatos que deja la gente en el formulario de tu web entran solos en
**Ventas › Candidatos**. Para ver **todo** lo que ha llegado, también lo que
se descartó y por qué: **Ventas › Candidatos ›** el botón **Recepciones**,
arriba a la derecha de la lista, al lado del título. Cada fila dice si se creó el candidato, si se marcó como posible
duplicado o por qué se descartó —«faltan: email», «sin correo ni teléfono», un
robot que rellenó el campo oculto, o que se pasó el tope por hora del canal—,
con lo que llegó. Si alguien te dice «rellené el formulario y no me habéis
llamado», ahí está la respuesta.

Hay dos formas de poner el formulario en la web, y las dos las prepara quien
administra las integraciones:

- **Un formulario propio** de la web, con la dirección pública del canal y su
  clave (**Ventas › Candidatos › CANDIDATOS › Canales de captura**; la clave se
  enseña una sola vez al crear el canal, y si se pierde se rota).
- **El formulario ya hecho del CRM**, que se pega en la página con una línea y
  un token del canal. Pide nombre, apellidos, empresa, correo, teléfono y
  mensaje; sin correo ni teléfono no deja enviar, porque sin forma de contestar
  el candidato no serviría. Lo que se pega en la web es esto (quien mantiene la
  web pone las dos direcciones del CRM y el token, que pide su servidor):

  ```html
  <script type="module" src="https://<dirección del CRM>/embebido.js"></script>
  <contecrm-componente componente="formulario-alta"
    api="https://<dirección de la API>/api/v1" token="…"></contecrm-componente>
  ```

  El token sólo se puede pedir para un canal que quien lo pide puede ver en el
  CRM; si no, el CRM contesta que no puede ver ese registro.

A quien rellena el formulario se le contesta siempre lo mismo, «Recibido», se
haya creado o descartado: un mensaje distinto le enseñaría a un robot qué
cambiar.

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

### Reparar, sustituir o abonar, y anotar el abono

En **Servicio › Postventa**, abre la devolución. Se resuelve con **«Reparar,
sustituir o abonar»**, en las acciones de la cabecera. Un abono queda
«solicitado» hasta que quien factura lo emite: cuando conteste, en la tarjeta
**«Resoluciones»** pulsa **«Anotar lo que contestó quien factura»** y elige
**«Abono emitido»** con su referencia, o **«Abono rechazado»** con el motivo.

### Derivar un caso a otro nivel

En **Servicio › Casos**, abre el caso y pulsa **Más › Derivar**. Elige la cola
destino, escribe qué se espera del siguiente nivel y marca **«Interno»** si el
cliente no debe verlo. El caso sigue siendo el mismo y su reloj no se reinicia.

### Lo que prometemos frente a lo que sostiene el proveedor

En **Servicio › SLA de proveedores**: arriba, qué derechos prometen lo que su
proveedor no sostiene. En «Quién da cada derecho» eliges el proveedor de cada
derecho de servicio, y en «Lo que sostiene cada proveedor» guardas su acuerdo
(**«Añadir acuerdo»**: respuesta, resolución, disponibilidad y cobertura).

---

## Informes y cuadros de mando (sección 5.1)

### Si los paneles salen en rojo

Las preguntas sobre los datos las resuelve **contecintelligence**, y para eso
este CRM tiene que estar dado de alta allí como fuente. Mientras no lo esté,
los cuadros salen con un aviso rojo que dice exactamente eso y dónde se
arregla: **Analítica → Preguntas publicadas**, botón «Registrar el CRM como
fuente consultable».

El alta no es inmediata: se encola y la pantalla se queda esperando hasta dos
minutos (medido el 10-11-2026: contecintelligence tarda unos dos minutos en
leer y perfilar las entidades). Si falla, **dice por qué y con qué dirección**
tiene que alcanzarnos contecintelligence —por ejemplo «La fuente no responde
(health_check fallo). La dirección con la que tiene que alcanzar este CRM es
`http://gateway:8000/api/v1`»—. Hay dos cosas que mirar, por este orden: que
desde contecintelligence se llegue a esa dirección, y que **su** lista de salida
(`OUTBOUND_ALLOWED_HOSTS`, en su configuración) admita ese nombre. La dirección
la pone `CI_URL_DEL_CRM` en el `.env`; en la instalación local,
`./setup.sh arrancar` presenta el CRM con ese mismo nombre, así que no hay que
tocar nada más.

**Mientras tanto el CRM entero sigue funcionando**: fichas, procesos, casos y
automatizaciones. Lo único que no se puede es preguntar y pintar cuadros, y la
propia pantalla lo enumera para que nadie dé por caído lo que no lo está.

### Preguntar en lenguaje natural

**Analítica → Preguntas publicadas**: escribe la pregunta en la caja (por
ejemplo «Importe total de oportunidades por etapa») y pulsa **Preguntar**. La
respuesta sale **ya dibujada** —barras, líneas, un número grande o una tabla,
según lo que se haya preguntado—, con **Ver como tabla** arriba a la derecha y
**Cómo se ha calculado** debajo, con la consulta que se usó.

- **Si la pregunta es ambigua**, no se adivina: sale el motivo y unas opciones
  como botones («Cuentas de cliente», «Cuentas contables»…). Pulsa la que
  quieres y se vuelve a preguntar con la pregunta de antes precisada.
- **Guardar la pregunta**, debajo de la respuesta, la deja en «Mis preguntas sin
  publicar» para no volver a escribirla.
- **Publicar para el equipo**, en la tarjeta de una pregunta tuya, la pasa a
  «Preguntas publicadas» y la ve todo el equipo; **Dejar de publicar** la
  devuelve a las tuyas. Sólo la puede publicar quien la guardó (o quien
  administra la explotación).
- **Convertir en informe**, en la misma tarjeta, abre debajo cuatro preguntas:
  **Sobre qué** (oportunidad, cuenta…), **Agrupar por** (por ejemplo «etapa»;
  si es una fecha, también **Por periodo**), **Qué calcular** (suma, media,
  cuántos hay…) y **De qué campo**. **Crear el informe** lo deja como informe
  del CRM, que se puede programar y mandar; la tarjeta pasa a llevar la marca
  «Es informe». Sólo salen los objetos y campos que el CRM publica para
  preguntar: si la lista sale vacía, primero hay que registrar el CRM como
  fuente.
- Ve sólo lo que tú ves en las fichas: la pregunta viaja con tu identidad.

### Que un panel te llegue solo

**Analítica → Paneles**, elige el panel en el desplegable de arriba a la
derecha. Debajo del título está la franja para recibirlo:

1. **Cada**: cada día, cada semana o cada mes (la semanal sale el lunes y la
   mensual el día 1).
2. **Hora (Europe/Madrid)**: la hora de reloj **de tu empresa**, la que sale
   entre paréntesis. «A las 8» es a las 8 también la semana del cambio de hora.
3. **Por**: la bandeja del CRM (la campana de arriba), correo, notificación del
   móvil, SMS o webhook. Las opciones las da el servidor.
4. Pulsa **Recibirlo**. Debajo queda escrito «Te llega cada semana a las 8 h
   (Europe/Madrid) por correo. La próxima: …». **Guardar** cambia lo elegido y
   **Dejar de recibirlo** lo para.

Lo que llega es el aviso con el nombre del panel; al pulsarlo se abre ese
panel. **Las cifras se calculan al abrirlo, con tus permisos**: no viajan
dentro del correo, para que nunca lleguen a un buzón cifras que tú no podrías
ver. Te suscribes tú, y sólo a ti: no se puede apuntar a otra persona. Si el
panel se borra, la suscripción se apaga y lo dice debajo, en rojo.

---

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

### Embudo, cohortes y actividad

**Analítica → Embudo, cohortes y actividad.** Todo sale de los datos del CRM, con
lo que tú puedes ver:

- **Embudo de ventas**: elige el embudo en el desplegable de arriba a la
  derecha. La gráfica dice cuántas oportunidades llegaron a cada etapa y la
  tabla de al lado, qué parte pasó de la anterior, cuántas se quedaron y los
  días que suelen tardar. Encima, en una frase, dónde se pierden más.
- **Retención por cohorte**: elige *Semana*, *Mes* o *Trimestre*. Cada fila son
  las cuentas dadas de alta en ese periodo; cada columna (+0, +1…), qué parte
  tuvo actividad después. «…» es un periodo que aún no ha terminado y un número
  suelto, una cohorte demasiado pequeña para dar porcentaje.
- **Actividad frente a resultados**: actividades y oportunidades ganadas por
  persona. Si no hay bastantes personas para que el número signifique algo, lo
  dice en vez de darlo.
- **Instantáneas programadas**: elige el informe, la frecuencia y la hora y
  pulsa **Programar la instantánea**; **Tomar una ahora** guarda la de hoy. A la
  derecha, la tendencia. **Quitar** deja de tomarlas sin borrar las tomadas.
  La hora es la de la **zona horaria de la empresa**, y la pantalla la dice al
  lado («Hora (Europe/Madrid)»): «7» es a las 7 de allí, también el domingo
  del cambio de hora. La zona es la de la ficha de la empresa (su ajuste
  `zona_horaria`).
- **Consulta al lake del cliente**: elige la fuente y el objeto, los campos si
  no los quieres todos y cuántas filas, y pulsa **Consultar**. El tope lo pone
  la fuente; si hay más, se dice.

Debajo de cada análisis, unas etiquetas dicen **de dónde salieron los datos**
(del almacén o de la aplicación), cuántos se leyeron y si se recortó. En
amarillo, lo que conviene mirar: recortado, sin permiso o que no se pudo leer.

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

### Pedírselo desde la ficha

Cada ficha que tiene algo que pedirle a la IA lo enseña **arriba, en la banda
«Con IA»**, entre la cabecera y las pestañas —no hace falta abrir «Más»—:

- **Cuenta**: resumir la cuenta, con puntos clave y riesgos y el dato en que se
  apoya cada uno.
- **Contacto**: redactar un correo en su idioma, y sacar sus datos de una firma
  o un correo pegados (se aceptan en **IA → Campos extraídos**).
- **Oportunidad**: qué hacer ahora, con el porqué de cada paso.
- **Caso**: casos resueltos y artículos parecidos, resumir el caso y sugerir una
  respuesta con los artículos que la sostienen.
- **Conversación**: qué quiere el cliente y cómo está, resumirla y traducir su
  último mensaje.

Nada de esto se guarda ni se manda solo: es un borrador para ti. Necesitas el
permiso de usar la IA, y lo que no puedes ver en el registro tampoco se le pasa
al modelo.

**Y en el menú de la izquierda**, dos entradas que antes sólo estaban dentro de
otra pantalla: *Automatización → Extensiones y código propio* y *Entornos y
despliegue → Entornos de pruebas (sandboxes)* (hasta el 10-11-2026 estaba en
Usuarios y empresa).

### Rellenar un contacto desde una firma

En un **contacto**, *Más → Sacar con IA los datos de este contacto de un texto*:
pega una firma o un correo y la IA propone cargo, departamento, teléfonos, otro
correo e idioma. No cambia nada todavía: en **IA → Campos extraídos**
ves cada propuesta con la frase de la que sale y el valor que hay ahora, y la
aceptas o la rechazas. Al aceptar, el contacto se actualiza con las mismas
reglas que si lo editaras tú. El nombre y el correo principal no se tocan así.

### Lo que ya pasó y cómo se arregló

- En un **caso**, *Más → Casos resueltos y artículos parecidos* busca por lo que
  significa el problema, no por palabras exactas. Cada sugerencia trae su cita
  para abrirla; lo poco parecido no se enseña, y un caso parecido que sigue
  abierto tampoco: no es una solución, es otro con el mismo problema.
- En **Conocimiento**, *Preguntar a la base de conocimiento* contesta sólo con
  lo que dicen los artículos, citándolos. Si ninguno lo trata, no contesta.
- Los artículos que se publican y los casos que se cierran con su resolución
  entran solos. *Indexar para la IA* recoge lo de antes; lo que no ha cambiado
  no se vuelve a procesar.

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

### Modelos predictivos

**Analítica → Modelos predictivos.** Una tarjeta por modelo: probabilidad de
convertir un lead, probabilidad de ganar una oportunidad, importe previsto,
fecha real de cierre, propensión a comprar y siguiente mejor oferta.

1. Pulsa **«Entrenar ahora»** en la tarjeta. El CRM lee tu histórico —lo
   ganado, lo perdido, lo convertido, lo descartado—, aprende con lo antiguo y
   se mide con lo más reciente, que no ha visto.
2. Debajo sale el resultado: **publicada** (empieza a puntuar) o **no
   publicada**, con el número que lo decide —el AUC, o cuánto mejora a «decir
   siempre la mediana»— y el mínimo que exige tu empresa. Si no hay bastantes
   datos, no entrena y te dice cuántos hay y cuántos hacen falta.
3. Marca **«Reentrenar solo cada N días»** para que se repita sola; la tarjeta
   dice cuándo toca y qué salió la última vez.
4. En **«Segmento por propensión»** eliges el criterio —propensión, valor
   esperado o probabilidad de convertir—, el mínimo y cuántos como mucho, y
   pulsas **«Crear el segmento»**: aparece en Marketing → Segmentos, congelado
   ese día. Necesitas poder crear segmentos.
5. En **«Versiones»** están todas, también las no publicadas; pasa el ratón por
   una fila para leer el porqué.

**En la ficha.** La de un lead, una oportunidad abierta o una cuenta enseña
**«Predicción con el histórico»**: el número, lo que lo sube y lo que lo baja,
y con qué modelo se calculó. En la oportunidad, también el importe previsto con
su horquilla y la fecha real prevista al lado de la declarada. Si no hay modelo
publicado, dice por qué. **«Recalcular»** lo vuelve a calcular con los datos de
ahora.

Los mínimos —el AUC para publicar, la mejora sobre la mediana, cada cuántos
días se reentrena, la ventana de la propensión— se cambian en **Administrar →
Usuarios y empresa → Administración**, en los ajustes de la IA (`ia_…`).

### Evaluación de la IA: cuánto acierta, medido

**Administrar → Gobierno y cumplimiento → Evaluación de la IA.** Aquí se ve si
la IA funciona, con un número por función y no con una impresión: el asistente
con conocimiento, las preguntas sobre los datos, los resúmenes de casos y de
conversaciones, la extracción de datos de un texto, los compromisos de una
reunión, las variantes de copy, el sentimiento y la intención, las acciones que
propone el asistente y el plan de un agente.

1. Pulsa **«Evaluar ahora»** (arriba a la derecha). Se pasa el banco de casos
   contra el modelo de verdad que usa tu empresa, por el mismo camino que usan
   las funciones; tarda unos minutos y el botón dice por cuál va
   («Evaluando… 24 de 50»). La primera vez, los casos de serie se guardan como
   tuyos. Cuesta llamadas al modelo: se apuntan en el gasto de IA como
   cualquier otra.
2. **«Última evaluación»** dice cuántos casos acertó, cuándo, con qué modelo,
   cuánto costó y cuánto tardó cada caso de media. Si alguna función ha bajado
   del umbral, sale el aviso en amarillo —y te llega también como notificación
   si la pediste tú o si estás en la lista de avisos—.
3. **«Acierto por función»**: una tarjeta por función con su porcentaje (verde
   si llega al umbral, amarillo si se queda cerca, rojo si no), cuántos casos,
   el acierto de la evaluación anterior para comparar y la versión del prompt.
   Si una función tiene casos que decide **un modelo juez** —lo que un programa
   no puede comprobar, como «¿se inventa algo que no está en el historial?»—,
   la tarjeta lo dice.
4. **«Tendencia del acierto»** dibuja el acierto global de las últimas
   evaluaciones (con dos o más). **«Ver la tabla»** da los números.
5. **«Casos que fallan»**: cada caso fallado con su función y **el porqué**
   —«total: "29040.0" y es "2904"», «no cita el fragmento [2]», «propone como
   compromiso algo que nadie prometió»—; lo marcado **juez** lo decidió el
   modelo juez.
6. **«Banco de casos»**: desmarca **Activo** en un caso que no aplique a tu
   empresa y deja de evaluarse (no vuelve aunque el producto lo traiga).

Se evalúa sola cada semana. El umbral (90 % de serie), cada cuántas horas
(0 la apaga) y a quién más se avisa se cambian en **Administrar → Usuarios y
empresa → Administración**, en los ajustes `ia_evaluacion_…`.

### Asistente IA

**Analítica → Asistente IA.** Dos cajas:

- **Conocimiento y acciones.** Pregunta lo que sea —«¿qué aprendimos de las
  ventas perdidas por precio?»— y contesta con lo que la casa sabe (artículos,
  casos resueltos, lecciones), con cada afirmación numerada y la fuente
  enlazada debajo. Si no lo encuentra, lo dice. Si le pides que haga algo
  —«crea una tarea para llamar mañana a…»— te enseña **lo que propone**: la
  acción, sus datos (que puedes corregir) y a dónde va. **No se hace nada** hasta
  que pulsas **«Confirmar y hacerlo»**, y se hace con tu usuario y tus permisos;
  **«Descartar»** la tira. Puede crear tareas y notas, abrir casos y capturar
  leads; nada más.
- **Pregunta a los datos.** «¿Cuántas oportunidades ganadas hay de más de
  50.000 €?» o «importe total por estado». Te dice cómo lo ha entendido, la
  respuesta, **la consulta que se ha hecho** —la puedes copiar y repetir— y, si
  es el caso, que es parcial o que el listado filtraba algo por defecto (las
  oportunidades, por ejemplo, enseñan sólo las abiertas si no se dice otra
  cosa).
- **Modo voz.** Marca **«Modo voz»** debajo de la pregunta y pulsa
  **«Hablar»**: dicta la pregunta y, al terminar, se pregunta sola y la
  respuesta se lee en voz alta (**«Dejar de leer»** la corta). Si tu navegador
  no reconoce voz, aparece **«Terminar y preguntar»**: se graba, lo transcribe
  el proveedor de la empresa y no se guarda la grabación. Lo que el asistente
  proponga hacer se confirma igual, a mano.

### Transcribir y resumir una llamada o reunión

**Actividades → abre la llamada, reunión o visita → bloque «Transcripción y
resumen»**, encima de las pestañas:

1. En **«Qué transcribir»** elige *Fichero de audio* (la grabación queda como
   documento de la actividad), *Enlace a la grabación* o *Texto ya transcrito*.
2. Elige la **base para grabar** y marca **«Se avisó a todos los participantes
   de que se grababa»**: sin eso no se manda nada a ningún sitio.
3. Pulsa **«Transcribir y resumir»**. Sale el resumen, la confianza de la
   transcripción y los **compromisos y próximos pasos**, cada uno con quién,
   cuándo y la frase en que se apoya (si esa frase no está tal cual en lo
   transcrito, te lo dice).
4. En cada compromiso corrige el asunto y la fecha si hace falta y pulsa
   **«Confirmar y crear la tarea»** —se crea con tu usuario, colgada de la
   cuenta de la reunión, y aparece **«Abrir la tarea»**— o **«Descartar»**.

Si dice que **no hay proveedor de transcripción**, quien administra la IA lo
instala desde ese mismo bloque: elige la plantilla del proveedor, pulsa
**«Instalar»** y pone su clave en **Integraciones → la conexión creada →
Credenciales**. El texto pegado se resume sin proveedor.

### Variantes de un asunto con IA

**Marketing → Contenido y gobierno → Plantillas → abre una plantilla → bloque
«Variantes con IA».** El texto base es el asunto; escribe el **objetivo**, elige
el canal y cuántas, y pulsa **«Generar variantes»**. Cada una sale como
*Propuesta*: corrígela si quieres y pulsa **«Aprobar»**, o escribe el motivo y
**«Rechazar»**. De las aprobadas, **«Elegir como ganadora»** marca la que se usa.
Lo marcado en «Comprobar antes de aprobar» —cifras, garantías, superlativos, un
`{{marcador}}` que se ha perdido— es lo que hay que leer despacio.

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
- **El correo que entra hace su trabajo solo.** Si tiene que ver con el CRM queda
  en la ficha como actividad de correo, igual que la reunión queda como reunión;
  si quien escribe estaba en una cadencia, sale de ella; y su dirección ayuda a
  reconocerle cuando llegue por otro canal (lo ves en **Clientes › Duplicados ›
  Calidad del dato**, bloque «La misma persona en cada canal»).

También hay chat corporativo conectado —avisos y consultas desde Teams o Slack—,
documentos generados desde plantillas y firma electrónica desde cualquier
registro.

**Lo que todavía no hay**, para que nadie lo busque: complemento para Outlook o
Gmail, ni aplicación de móvil para iOS o Android. El CRM ya sirve lo que esas
piezas necesitarían —el contexto de quién te escribe, la sincronización que no
pierde lo que anotaste sin cobertura—, pero las aplicaciones en sí no existen.
Desde el móvil se entra por el navegador.

---

### Qué sabe hacer la suite que tienes conectada (sección 6.1)

En **Usuarios y empresa → Aplicaciones conectadas** está, además de si el
correo y el calendario de cada uno están entrando, **qué hace exactamente** la
suite que tienes conectada. Era
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

### Vincular una nota, un fichero o una conversación de la suite a una ficha

Abre la ficha de cualquier registro (un contacto, una oportunidad, un caso…) y
baja hasta **De la suite** › **Vincular**. Elige **Qué es** (nota, fichero o
conversación), pega el **enlace o identificador en el origen**, ponle un
**nombre** y, si la empresa tiene una suite conectada, el **perfil de suite** que
sabe abrirlo. **Guardar el vínculo**.

En el CRM queda sólo el enlace: el contenido sigue en su sitio. Al pulsar
**Abrir** se pregunta al origen si existe y si tú puedes verlo, y la línea dice
«disponible» (con **Ir al origen**), «no tienes acceso» o «ya no está». Si el
perfil no sabe comprobarlo, lo dice: **no se puede comprobar**, y el origen
decidirá al abrir el enlace. **Quitar el vínculo** sólo lo quita del CRM.

### Las reuniones del calendario entran solas

Si tu calendario está conectado (Usuarios y empresa › Aplicaciones conectadas),
cada cita con alguien de fuera aparece como actividad **Reunión**, con sus
asistentes: los que son contactos van ligados a su ficha y los que no, con su
correo — son los que faltan por dar de alta.

### Avisos y consultas en el chat del equipo

En **Administrar › Operación › Canales de chat** se conecta un canal con su
dirección de webhook. Marca **Recibe avisos** para que le lleguen los avisos de
las automatizaciones. Desde la ficha del canal, **Qué se puede hacer con esto ›
Mandar un aviso al canal de chat** manda uno a mano; la ficha enseña después si
llegó (**Último aviso ok**). Para que los avisos lleven el enlace al registro,
el administrador pone la dirección pública del CRM en el ajuste
**chat_url_crm**.

Cuando alguien pregunta desde el chat por un registro, se contesta con lo que
**esa persona** puede ver en el CRM, identificada por su correo. Si su correo no
es el de nadie del CRM, no se contesta con datos.

### Generar un documento desde la ficha

Una oferta, un contrato o una carta se generan **desde el registro**, sin
copiar datos a mano:

1. Abre la ficha: **Ventas → Oportunidades → (una oportunidad)**; en el mismo
   módulo, pestaña **Ofertas → (un presupuesto)** o **Contratos → (uno)**; o
   **Clientes → Cuentas → (una cuenta)**. En la oportunidad, el presupuesto y
   el contrato, pestaña **Relacionado** (en el contrato, debajo de
   **Adjuntos**); en la cuenta, la columna de la derecha.
2. Despliega **Generar documento**, elige la **Plantilla** y pulsa **Rellenar
   con este registro**. Cada dato sale ya escrito, con «de contacto», «de
   registro.importe»… al lado para que sepas de dónde viene.
3. Lo que el registro no sabe sale marcado **Falta**, y arriba lo dice: «Faltan
   2: contacto, oportunidad». Escríbelo en su casilla (sale marcado **A mano**).
   Puedes corregir también lo que vino rellenado.
4. **Generar el PDF**. Sale con la marca y el idioma de la plantilla, y con las
   líneas y los totales si el registro los tiene. Queda **guardado como adjunto
   del registro**: el enlace aparece debajo y en el panel **Adjuntos**.
5. Debajo se dice si se ha archivado también en el corpus documental. Si no ha
   podido («Este tenant no tiene organización asignada en el gestor
   documental», por ejemplo), el PDF está guardado igual.

De qué campo sale cada dato de la plantilla lo decide quien la administra:
**Administrar → Entornos y despliegue → Operación**, pestaña **Plantillas de
documento**, **Nuevo**, y en **Más campos** el **Mapeo** (por ejemplo
`{"cliente": "cuenta.nombre"}`), los **Objetos** para los que sirve, la
**Marca** y si lleva la tabla de **líneas**. Cada cambio guarda una versión
nueva de la plantilla.

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

### Calidad del dato: la ficha buena, el proveedor y la misma persona

Se entra por **Clientes › Duplicados** y el botón **Calidad del dato** de
arriba a la derecha (o directamente en `/calidad-del-dato`). Hay cinco bloques:

1. **Ficha buena (golden record)**: la lista enseña las fichas que tienen otra
   versión fusionada o unida. Pulsa **Componer** en una y verás, campo a
   campo, el valor que gana, de qué fuente sale, con qué regla y lo que dicen
   las demás. Los campos con «!» tienen fuentes que no coinciden. Si estás de
   acuerdo, pulsa **Aplicar a la ficha**. Salen también los **leads** con
   capturas fusionadas en ellos o con otro lead marcado como su duplicado; en
   ellos, la fuente de cada captura es su canal (por ejemplo «feria»).
2. **Reglas de supervivencia**: elige el objeto (Cuentas, Contactos o Leads), el campo (o «*» para todos),
   la estrategia y la confianza de cada fuente, una por línea (`erp=90`), y
   pulsa **Guardar la regla**. Para cambiar una, púlsala en la lista; **Quitar**
   la devuelve a la regla por defecto.
3. **La misma persona en cada canal**: salen las parejas de contactos que
   comparten correo, teléfono u otro identificador. Pulsa **Unir** y la
   primera queda como principal; no se borra ninguna ficha. Además de lo que
   tiene cada ficha, cuentan lo que llega por los canales: quien escribe por un
   canal de entrada o al buzón, el número que llama a la centralita y, si tu
   administrador lo ha declarado, los códigos que trae el ERP.
4. **Proveedor de datos**: declara el proveedor (clave, nombre, conexión de
   Integraciones, operación, parámetros y qué campo va a cada campo), elige
   una ficha en **Pedir para** y pulsa **Pedir**. En **Propuestas por revisar**
   marca los campos que quieres —vienen marcados los huecos— y pulsa
   **Aplicar lo marcado**, o **Descartar**.
5. **Cuánto tienen que parecerse dos fichas** y **Direcciones normalizadas**:
   escribe el umbral propio de cada objeto (vacío = el general) y pulsa
   **Guardar los umbrales**. Las filas **Lead frente a otro lead** y **Lead
   frente a un contacto** son las del alta de leads; no tienen «Proponer»; en direcciones, **Ver qué cambiaría** y, si te
   convence, **Aplicar**.

### Duplicados: el sistema los busca, tú decides

Están en **Clientes → Duplicados**. Es el único sitio, y a
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
  escrito los registros que ya lo usan. El código admite hasta 120 caracteres, y
  cabe entero en todos los sitios donde se usa.
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
- **La etapa de una oportunidad también se arrastra.** Ventas › Oportunidades
  › botón «Por columnas» (arriba a la derecha de la lista): soltar una tarjeta
  en otra columna la mueve de etapa con los mismos controles que el embudo
  —criterios de salida, y cierre si la etapa es la final—. Hasta el 09-11-2026
  esta vista no dejaba coger ninguna. Si hay dos embudos con una etapa que se
  llama igual, va a la de su embudo; si no se puede saber cuál es, no se mueve
  y te dice que lo hagas desde la ficha.
- **Si el servidor dice que no, la tarjeta vuelve** y se enseña su motivo.
  Cuando un rechazo trae varios motivos concretos —por ejemplo, un
  presupuesto con dos productos que no se venden juntos— el aviso los lista
  a la vista, uno por línea, con qué choca con qué. Hay
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

### Llevarse la política de acceso a otro motor

En *Usuarios y permisos → Políticas de acceso*, **Descargar en formato neutro**
baja `politica-de-acceso.json`: todas las políticas del tenant con la semántica
dentro, para cargarlas en OPA, Cedar o el motor del cliente. Debajo del botón
dice qué se ha bajado.

### Qué ha hecho una clave de API

En *Usuarios y permisos → Claves de API*, el menú de cada fila tiene **Qué ha
hecho esta clave este mes, y qué ha fallado**: cuántas llamadas lleva, cuánto le
queda de la cuota y los últimos errores. Los errores vienen **separados por
culpa**: los 4xx son de la integración —una petición que no cuadra—, los 5xx
nuestros; si hay de los segundos, no hace falta revisar la integración.

Una clave puede tener **cuota mensual** (al crearla, o con *Cambiar la cuota
mensual*). Al gastarla, la integración recibe «cuota agotada» —no «clave no
válida»— hasta el día 1 o hasta que se amplíe.

**Al crear una clave** (*Usuarios y permisos → Claves de API → Nuevo →
Guardar*) sale arriba un recuadro **«Cópialo ahora: no se volverá a enseñar»**
con el secreto y un botón **Copiar**. Cópialo y pulsa **Ya lo he copiado**: no
se guarda en ninguna parte y no vuelve a salir —ni al recargar ni en la lista—;
si se pierde, se crea otra. Crear una clave pide haber verificado tu identidad
con el segundo factor hace poco. La lista dice también **desde qué IP** se
admite cada clave (columna *Ips permitidas*, en *Columnas*).

### Comprar a un proveedor, de la petición a la evaluación

En *Proveedores* están las pestañas de compras. El recorrido normal:

1. **Peticiones de oferta → Nuevo.** Categoría (la que decide la homologación),
   a qué proveedores se pide, fecha límite, cantidad y, si hay, la oportunidad que
   la motiva y para cuándo hace falta.
2. **En la ficha de la petición**, *Anotar lo que ha contestado un proveedor*
   por cada respuesta. *Quién ha contestado, y sobre todo quién no* dice a quién
   llamar; *Comparar…* enseña todas las opciones con su motivo de descarte —no
   homologado, papeles vencidos, llega tarde— y cuál se elegiría.
3. **En la respuesta elegida**, *Adjudicar a este proveedor*. Si tiene capacidad
   declarada para el periodo se descuenta, y si no cabe se niega salvo que lo
   fuerces diciendo por qué. Queda fijada la fecha comprometida.
4. **Cuando entrega**, *Anotar que se entregó, y lo que costó*; y si algo falla,
   *Anotar una incidencia*. Con eso, en la ficha del proveedor, *Cómo va este
   proveedor…* da el porcentaje en plazo, las incidencias y el desvío de coste.

*Capacidad*, *Rappels*, *Contratos de proveedor* y *Alcance* se rellenan una vez
por proveedor y periodo, y cada ficha contesta su pregunta: cuánto queda, qué se
recuperará con lo comprado, qué hay que hacer con el contrato mirando lo
comprometido, y si puede servir un caso concreto.

### Añadir y editar, en general

Casi todas las pantallas que enseñan una lista permiten **dar de alta** y
**abrir cada fila** para verla, cambiarla o borrarla. Eso incluye las fichas con
diseño propio, como la de un cliente: ahí tienes **Editar** arriba y, en
«Más», las demás acciones y la de quitar el registro. Esa última **dice lo que
hace**, porque no siempre es borrar: en un cliente es «Enviar una cuenta a la
papelera» —se recupera desde la papelera—, en una clave de API es «Revocar», y
en una persona es «Dar de baja», que corta su acceso y te pregunta a quién pasan
sus registros. Sólo pone «Eliminar» cuando de verdad es eso.

**Lo que no tiene ficha se hace desde su fila.** Hay listas cuyas filas no se
abren —una clave de API, una sesión, un ajuste, una supresión— porque no hay
nada más que ver de ellas que lo que ya enseña la fila. Lo que se puede hacer
con ellas está en el menú del final de cada fila: *Revocar una clave*, *Cerrar
una sesión*, *Levantar una supresión*, *Editar*. Al elegirlo, el formulario sale
encima de la lista y dice sobre qué fila vas a actuar —«Sobre “Cuadro de mando
de dirección”»—, para que con cincuenta parecidas no haya duda.

**Lo que das de alta lo puedes corregir.** Productos, roles, reglas de
compartición, colas, niveles del programa de partners, planes preventivos,
categorías de caso, proveedores, dispositivos y el resto de catálogos se abren
y tienen **Editar**. Para retirar uno, desmarca *Activo*: no se borra, porque
lo que se hizo con él antes lo sigue nombrando. Hay cosas que no se editan a
propósito: los históricos (movimientos de almacén, transferencias), las
versiones publicadas (un SLA, una definición de proceso: se publica otra) y lo
que se declara por clave (residencia, guardarraíles: se declara de nuevo).

Hasta el 27-10-2026 la ficha de un cliente no tenía ninguna de las dos cosas —la
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

### Varios registros a la vez

En **Clientes › Cuentas**, **Contactos**, **Ventas › Candidatos** y
**Oportunidades**, la lista en vista de tabla lleva una casilla en cada fila y
otra en la cabecera para elegir todas las que se ven. En cuanto eliges una
aparece encima **Con los elegidos**:

- **Actualizar un campo**: eliges el campo en el desplegable, escribes el valor
  y pulsas **Aplicar a N**.
- **Borrar**: confirma y los manda a la papelera. Pide confirmar que eres tú
  con el código de tu app, como exportar en masa: sale el recuadro y, al
  confirmarlo, sigue solo.

Al terminar te dice cuántos se han hecho y, de los que no, **cuál era y por
qué** —por ejemplo, uno que otro registro está usando y no se puede borrar—.

### Duplicar un registro

En la ficha, menú **Más › Duplicar**: se abre el alta de su lista con los
datos de ése, y el nombre con «(copia)» detrás. Revisa y **Guardar**. Si la
copia se parece demasiado al original, te avisará como cualquier alta, y
**Es otro, crearlo igual** la crea. En una oportunidad la opción es **Duplicar
la oportunidad con sus líneas**: copia también lo que se ofertó, y la copia
empieza en la primera etapa; el resultado trae el enlace para abrirla.

### Importar cuentas o contactos

**Administrar › Usuarios y empresa › Importar datos.**

1. Elige qué importas —cuentas o contactos— y sube el CSV. Vale el de Excel
   en español, con `;`.
2. En **A qué campo va cada columna**, cada columna del fichero con su primera
   fila y un desplegable. Lo que se llama igual que un campo ya viene puesto;
   los campos propios de tu empresa salen con «(propio)». Lo que dejes en «No
   importar» no se manda.
3. **Simular**: no escribe nada y te dice fila a fila qué haría —crear,
   completar, omitir porque ya existe— y por qué falla la que falla.
4. **Importar**. Si marcas «Completar las que ya existan», las que ya están se
   rellenan donde tengan huecos, sin pisar lo que tienen.

Abajo, **Importaciones hechas**: cada una con su fichero, quién y cuándo. **Revertir**
te dice primero cuántos se mandarían a la papelera y cuántos volverían a como
estaban; escribe el motivo y **Revertir la importación**. Si alguno se ha
tocado después de importarlo, te lo avisa y no revierte nada salvo que
marques «Revertirlos igualmente».

### Traspasar la cartera de una persona

**Administrar › Usuarios y empresa › Traspasar cartera.** Elige **De** y **A**,
pulsa **Simular el traspaso** y verás cuántas cuentas, contactos,
actividades, candidatos y oportunidades pasarían. Escribe el motivo y pulsa
**Traspasar N registros**. Si cambias la pareja después de simular, vuelve a
simular: sólo se confirma lo que se ha visto.

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
- **Llevarse la configuración a otro entorno.** En «Promoción entre entornos» se
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

### Un entorno de pruebas con tus datos: los sandboxes

En **Empresas → Sandboxes** se crea un entorno de pruebas que es una copia de tu
empresa. Sirve para probar una migración, formar a alguien o reproducir un
problema sin tocar lo de verdad.

1. **Crear**: le das un nombre, el propósito (desarrollo, pruebas, formación,
   migración o soporte) y qué porcentaje de tus clientes quieres copiar —el
   porcentaje limita las cuentas y también los **contactos**: van los de las
   cuentas copiadas y, de los que no tienen cuenta, la misma proporción—. El
   propósito decide cuándo caduca. Por defecto los datos se **anonimizan**; si no
   quieres anonimizar, tienes que escribir por qué, y queda escrito con tu nombre.
2. **Copiar los datos**: la copia no empieza sola, porque tarda y conviene
   revisar antes el plan. Al pedirla, el sandbox pasa a *copiando* y al terminar
   a *listo* o *con avisos*.
3. **Mirar el resultado**: la ficha del sandbox dice, servicio a servicio,
   cuántas filas se copiaron, qué no se copió y por qué, y si algo falló.

Qué encontrarás dentro:

- Los nombres, correos, teléfonos, asuntos y textos de tus clientes salen
  **cambiados** por otros que no se pueden deshacer. El mismo dato original da
  siempre el mismo sustituto, así que lo que estaba relacionado sigue
  relacionado.
- Los importes y números que son confidenciales salen **vacíos** o a cero: un
  número inventado parecería de verdad.
- Las claves de API, las credenciales de conexiones y los secretos de webhook
  **no se copian nunca**: desde un sandbox dispararían contra producción.
- Los comentarios, los adjuntos y el buscador **empiezan vacíos**.
- Las personas de tu equipo entran en el sandbox con su usuario de siempre.

Con **Apagar** el sandbox deja de dejar entrar, con el motivo que escribas.

### Probar la API en un sandbox con datos inventados

Para quien escribe una integración: en **Administrar › Entornos y despliegue ›
Probar la API**.

1. En **Crear un sandbox**, ponle nombre y, si quieres, qué colecciones llenar
   (`accounts, contacts…`; vacío, las de serie) y cuántas filas. Pulsa **Crear
   el sandbox**. Se crea un entorno aparte con datos **inventados** —no copias
   de tus clientes— y una **clave de API** que sólo abre ese entorno. La tabla
   dice cuántas filas se crearon de cada cosa y qué falló.
2. La clave se enseña **una vez**: cópiala si la vas a usar fuera. Ya queda
   puesta en la consola de abajo.
3. En **Consola**, elige el servicio, el método y una ruta del contrato (o
   escríbela, rellenando los `{parámetros}`), escribe el cuerpo si hace falta y
   pulsa **Enviar**. Sale el código de respuesta, lo que tardó y el cuerpo.

Las llamadas de la consola van con la clave del sandbox, no con tu sesión: lo que
borres o rompas ahí no toca los datos de tu empresa. El sandbox caduca solo y se
apaga desde **Empresas → Sandboxes**.

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

### Segregación de funciones: quién no debería poder hacer las dos cosas

En **Administrar › Gobierno y cumplimiento › Segregación de funciones**. Una regla dice qué
dos grupos de permisos no deben coincidir en la misma persona: quien calcula
las comisiones no las aprueba, quien da de alta usuarios no les asigna roles.

- **Para empezar**, pulsa **«Cargar las reglas de serie»**: trae siete reglas
  habituales. Las que ya tengas no se tocan.
- **La tabla de reglas contra roles** dice, para cada regla, qué roles dan el
  lado A, cuáles el B, y cuáles **los dos (A+B, en rojo)**. Si un rol da los
  dos, cualquiera que lo tenga está en conflicto: eso se arregla en el rol.
  La columna «Personas en conflicto» dice a cuántas afecta hoy.
- **Para crear una regla**, «Nueva regla»; para cambiarla, pulsa su nombre en
  la tabla. Eliges los permisos de cada lado en los desplegables, la gravedad
  y si está activa.
- **«Quién está en conflicto hoy»** lista cada persona con la regla que
  incumple y por qué permisos. Si el conflicto es inevitable —en una empresa
  pequeña una persona es todo el departamento—, **«Aprobar una excepción»**
  pide el motivo y hasta cuándo vale. El conflicto sigue saliendo, marcado.
- **«Antes de dar un rol»**: elige la persona y los roles que le darías, y
  «Comprobar» te dice qué reglas pasaría a incumplir. No cambia nada.
- **«Excepciones aprobadas»**, abajo, con el motivo y la fecha; marca «Ver
  también las caducadas» para distinguir «no hay ninguna» de «todas vencieron».

### Clasificación TCSEC: en qué nivel de confianza está la instalación

En **Administrar › Gobierno y cumplimiento › Clasificación TCSEC**. Arriba,
la escala de niveles (D, C1, C2, B1, B2, B3, A1) con el que alcanza tu
instalación y cuántos requisitos faltan para el siguiente. Debajo, cada nivel
con sus requisitos:

- **Cumple / No cumple**: lo que se ha medido ahora mismo sobre el sistema, con
  la cifra que lo explica (por ejemplo, cuántas personas no tienen segundo
  factor).
- **Sin medir**: no se pudo comprobar —un servicio no contestó—. No cuenta
  como cumplido.
- **No implementado**: el producto no lo hace; se dice para que nadie lo dé
  por hecho.
- **Atestiguar**: en los requisitos que no se pueden medir (canales
  encubiertos, control de cambios, recuperación, verificación formal), elige
  el resultado y escribe la evidencia —qué se revisó y dónde está la
  prueba—. Vale un año.

**«Volver a medir»** repite la medida; **«Descargar el informe»** baja el
resultado en un documento para la auditoría.

### Controles del GRC: que todo lo que hay tenga su control

En **Administrar › Gobierno y cumplimiento › Controles del GRC**.

1. **«Instalar los de serie»** crea un control por cada familia del catálogo,
   uno por regla de segregación, uno por requisito TCSEC y el de la revisión de
   accesos. Se puede repetir: trae lo nuevo y no toca lo que hayas cambiado.
2. **«Evaluar los automáticos»** los evalúa todos con la evidencia que pone el
   sistema. Lo que no se ha podido medir no se evalúa y dice por qué.
3. Arriba, dos coberturas: **anclada** (lo que tiene control) y **verificada**
   (lo que una evaluación en plazo dio por bueno). La que dice cómo estás es la
   segunda.
4. Pulsa un control para ver su última evaluación con la evidencia, sus
   hallazgos y sus evidencias con caducidad; **«Evaluar ahora»** lo evalúa
   solo a él e **«Ir a la regla / al requisito / a las campañas»** te lleva a
   su origen. La casilla **Activo** lo desactiva (queda como ajustado).
5. **«Traer la segregación»** pone al día los controles de segregación: cada
   conflicto sin excepción es un hallazgo, y cada excepción aprobada una
   evidencia hasta su caducidad.

Desde **Segregación de funciones**, cada regla enseña su control; desde
**Clasificación TCSEC**, cada requisito el suyo, y **«Dejar la medida en el
GRC»** guarda lo medido como evidencia.

### Revisión de accesos: cada responsable confirma o retira lo de su gente

En **Administrar › Gobierno y cumplimiento › Revisión de accesos**.

1. Escribe el **nombre** de la campaña, el **plazo en días** (vacío: el de la
   empresa) y el **revisor por defecto** para quien no tiene superior, y pulsa
   **«Lanzar»**. A cada responsable le llega un aviso.
2. En la tabla ves el avance de cada campaña y cuántas revisiones están
   **fuera de plazo**. **«Marcar y avisar lo vencido»** lo hace sin esperar a
   la tarea periódica; **«Cerrar»** termina la campaña.
3. Pulsa una campaña para verla por responsable.

**Si eres responsable**: abre **Aprobar documentos** (tu bandeja de
aprobaciones, o el aviso de la campana). En **«Revisión de accesos de tu
gente»**, para cada rol de cada persona pulsa **«Confirmar»**, o **«Retirar»**,
escribe por qué y **«Retirar el acceso»**: se le quita en ese momento.

### Dos preguntas que se hacen en «Identidad y seguridad»

- **«¿Hay alguien con permisos incompatibles?»** Sale el recuento, y el enlace
  a **Segregación de funciones**, donde se ve quién y por qué (apartado
  anterior).
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
  —privilegios dados por si acaso—. Debajo, **cada tratamiento** en una tabla:
  el dato, para qué se trata, con qué base legal y cuánto se guarda. En el
  servicio **integration** están los de la suite (consentimientos, buzones,
  suscripciones y lo vinculado por referencia), las llamadas y la compensación.
- **Qué se puede recuperar.** Lo que hay en la papelera, lo primero lo que menos
  tiempo le queda antes de purgarse, con cuántos registros se llevaría por
  delante al restaurarlo.
- **El archivo de histórico**, por servicio (el selector de arriba): cada clase
  de dato con **a partir de cuántos días se archiva** —cámbialo en la casilla y
  pulsa el disquete—, la fecha de corte y cuántas filas movería hoy. **Simular**
  dice cuántas sin mover nada; **Archivar** las saca de la tabla viva y las deja
  en el archivo con su identificador. Debajo, **Consultar lo archivado** busca
  por el identificador de un registro (vacío, lo último archivado). Y en la
  ficha de un registro, pestaña **Relacionado**, **Archivado de este registro**
  enseña lo suyo archivado y lo **devuelve a la tabla viva** si hay que seguir
  trabajándolo.

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

Desde el 10-11-2026 vale también para **borrar** y para cualquier ficha, no
sólo las de las listas genéricas: si alguien cambió una cuenta o un contacto
mientras la tenías abierta, el CRM no deja que tu borrado o tu guardado se
lleve su cambio por delante sin avisarte. Con el modo sin conexión pasa lo
mismo: lo que borraste sin red y otro cambió entretanto aparece en
Sin conexión como conflicto, para que elijas.

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

En la ficha de tu empresa (*Usuarios y empresa → Empresas y unidades*, abrir la
empresa → pestaña *Relacionado* → *Consumo del periodo frente a los topes*) cada
línea dice además **de qué módulo** es —registros en
contactos y cuentas, correos en avisos…—, porque el límite se aplica módulo a
módulo. Un módulo que no contesta sale con la métrica «\*» y el motivo, nunca
como cero.

### Mandar el consumo a facturación

**Administrar › Usuarios y empresa › Consumo para facturación.** Pulsa **Tomar
el corte ahora** para ver lo que lleva gastado tu empresa en cada módulo, o
**Tomar y enviar** para mandarlo además a vuestro sistema de facturación. En
cada corte, **CSV** o **JSON** lo descargan, y **Enviar** (o **Reenviar**) lo
manda otra vez. La columna «Envío» dice cómo fue: enviado, falló (con el
porqué) o sin destino. Si un corte dice «Incompleto», algún módulo no contestó
al tomarlo: tómalo otra vez antes de cobrar con él. El destino y si se manda
solo cada mes los configura quien administra, en los ajustes que empiezan por
`facturacion_`.

### Decir quién depende de quién

**Administrar › Usuarios y empresa › Organigrama.** A la izquierda está el
árbol; escribe en **Buscar a una persona** si es largo. Pulsa una persona y, a
la derecha, elige en **Depende de** su superior y pulsa **Guardar superior**:
se mueve con todo su equipo. «Nadie (raíz)» la deja sin superior. En **Su
equipo directo**, elige a quién pasar todo su equipo en **Pasar todo su equipo
directo a** y pulsa **Mover el equipo**. En la lista no salen las personas de
su propio equipo, porque formarían un círculo. La etiqueta **Del directorio**
dice que el superior lo manda el directorio de tu empresa, y **Ajustado a
mano** que se cambió aquí; el texto de arriba dice si el directorio pisará lo
ajustado a mano. Un presupuesto que necesita aprobación va al superior de
quien lo envía, y la revisión de accesos de cada persona, a su superior: sin
superior, nadie puede aprobar sus presupuestos.

### Tu grupo de empresas

**Administrar › Usuarios y empresa › Grupo de empresas.** Ves de qué empresa
cuelga la tuya y cuáles cuelgan de ella, con su relación. En **Qué ve mi matriz
de esta empresa** marca **Consumo** o **Indicadores** y pulsa **Guardar lo que
comparto**: sólo tú decides eso, y la matriz sólo ve cifras sumadas, nunca tus
registros. En **Lo que veo de mis empresas hijas** ves lo que cada una te
comparte; las que no comparten nada salen como «No compartido». Si eres de la
plataforma, **Colgar una empresa de otra** pone la matriz y la relación.

### Cambiar un ajuste

**Administrar › Usuarios y empresa › Empresas y unidades**, y en el selector de
arriba (**EMPRESAS Y UNIDADES · …**) elige **Ajustes**. Salen todos los
ajustes de la instalación —unos trescientos—, también los de cada parte del
producto: el preaviso de un contrato de proveedor, el margen mínimo de una
oferta, las horas de aviso del SLA, la telefonía, las lecciones aprendidas.
Escribe parte de la clave en **Buscar en esta lista** (por ejemplo
`preaviso`), despliega la fila con la flecha de la derecha y pulsa **Editar**:
pon el **Valor** y pulsa **Guardar cambios**. En **Más campos** eliges el
ámbito —toda la instalación, tu empresa, una unidad o una persona— cuando el
ajuste lo admite.

- **Origen** te dice de dónde sale el valor que se aplica: «entorno» es el de
  fábrica; «tenant», el que ha puesto tu empresa.
- Con **Columnas** puedes añadir el servicio (qué parte del producto lo lee),
  el mínimo y el máximo que admite y el ámbito más bajo en el que se puede
  fijar.
- Un valor fuera de sus límites no se guarda y el aviso dice cuáles son.
- El cambio se aplica en un segundo, sin reiniciar nada, y queda en el
  historial (abajo).

Hasta el 10-11-2026 los ajustes propios de cada parte del producto no salían
aquí y sólo se podían cambiar en la instalación.

### Ver y deshacer un cambio de configuración

**Administrar › Entornos y despliegue › Historial de la configuración.** Elige un
ajuste en el desplegable (salen los que tienen cambios) y verás cada cambio con
el valor de antes y el de después. Para comparar dos versiones, marca sus dos
casillas y pulsa **Comparar las dos elegidas**. Para ver qué cambió entre dos
fechas, rellena **Desde** (y si quieres **Hasta**) y pulsa **Ver qué cambió**.
**Volver a antes** pone el valor que había antes de ese cambio, para toda la
empresa, y queda en el historial como «Vuelta atrás».

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

### Si un dato sale en blanco, díselo a quien administra

Un hueco en blanco en una pantalla no siempre es «no hay nada». A veces es que
la pantalla está pidiendo un dato con un nombre que el sistema no usa, y
entonces **el hueco sale vacío aunque el dato esté**. No da error ni aviso: se
ve como si ese cliente, esa campaña o ese artículo no tuviera ese dato.

Cómo distinguirlo sin saber nada de por dentro: si el hueco sale vacío en
**todos** los registros de una lista —todos los segmentos «nunca calculados»,
todos los territorios con «0 criterios», todos los artículos sin título— no es
que falten los datos. Es la pantalla.

Lo que se arregló el 29 de octubre de 2026, por si te suena:

- en **Marketing**, el tamaño de cada segmento salía vacío y su fecha decía
  siempre «nunca calculado», que es justo lo que no puede pasar: un recuento sin
  fecha se lee como el de hoy y sobre eso se decide un envío a catorce mil
  personas. Ahora sale el número con su fecha, y si el segmento es una foto
  congelada lo dice;
- en **Marketing**, cada campaña enseñaba tres cifras vacías. Ahora enseña
  cuántas personas tiene dentro, y los envíos y las respuestas se miran en el
  embudo de la campaña, que es donde se cuentan;
- en **Conocimiento**, la lista de artículos salía sin títulos, y al escribir en
  el buscador la pantalla se quedaba en blanco del todo. Ahora cada artículo
  sale con su título, y si lo que se enseña es un borrador y no lo publicado, lo
  dice: citarle a un cliente un texto que no ha aprobado nadie es el error que
  esa marca evita;
- en **Territorios**, todos decían «0 criterios», incluido el que reparte media
  cartera.

### Antes de mandar algo a un segmento

Abre el segmento y mira tres cosas, en este orden:

1. **Si pone «foto congelada»**, el número que ves no es de ahora: es el de
   cuando se congeló. Sirve para contestar en junio «¿a quién se le mandó en
   marzo?», y no sirve para decidir un envío de hoy.
2. **El número grande son los alcanzables**, no todos. Debajo pone cuántos hay
   en bruto y cuántos se caen por supresión —bajas, rebotes duros, listas
   negras—. Si planificas sobre el bruto, el envío sale más corto y parece que
   algo ha fallado.
3. **Mide el solapamiento contra el otro segmento al que vayas a lanzar esta
   semana.** La pregunta no es cuánta gente comparten: es a cuánta le van a
   llegar las dos cosas. Por eso sale el porcentaje **sobre cada uno de los
   dos**: mil personas comunes es mucho si tu segmento tiene mil doscientas y
   poco si tiene cien mil.

Congelar es definitivo en un sentido: el segmento deja de recalcularse. Se hace
**antes** del envío, no después.

### Por qué este lead tiene esta puntuación

El número solo no sirve. Lo que decide a quién llamas primero son los dos ejes
por separado:

- el **interés** es cuánto caso nos está haciendo, y se gana con actividad;
- el **encaje** es si es el cliente que buscamos, y **no** se gana con
  actividad: sale de quién es.

Un director de compras de una empresa objetivo que lleva dos meses callado y un
estudiante muy activo pueden dar el mismo total, y no se hace lo mismo con los
dos. Por eso nunca verás los dos sumados.

Debajo de cada eje está **qué regla sumó cada punto**: «descargó el
comparativo», «sector objetivo». Eso es lo que se dice por teléfono.

Y arriba, **qué le falta para el escalón siguiente**. Si lo que le falta es
interés, se gana insistiendo. Si lo que le falta es encaje, no: ese lead no va a
llegar por mucho que se le llame, y lo que hay que revisar es a quién se está
atrayendo.

Si ves un aviso de que se calculó con una versión anterior del modelo, no
compares ese número con el de otro lead: no están medidos con la misma vara.

### Si sospechas que se están perdiendo correos de clientes

Abre **Canales de entrada**. Cada canal dice cuántos mensajes ha recibido,
cuántos ha descartado y —esto es lo que importa— **por qué**:

- **respuestas automáticas** y **eco propio** son el canal haciendo su trabajo:
  está cortando contestadores y sus propias respuestas rebotando. Que haya
  muchos es normal;
- **pasados de tope** significa que llegó más de lo que el canal admite por
  hora. Si pasa a menudo, sube el tope: lo que sobra se está rechazando;
- **incompletos** son mensajes a los que les faltaba un campo que ese canal
  exige. Si son muchos, suele ser que el formulario de fuera cambió;
- **por la trampa** es el que hay que mirar. La trampa es un campo oculto que
  los robots rellenan y las personas no. Si es el motivo que más descarta, el
  canal te lo señala: **revisa ese campo**, porque un descarte por trampa
  responde «recibido» a propósito —para no decirle al robot qué cambiar— y si
  está mal puesto se está comiendo mensajes de clientes sin que ellos lo sepan
  ni tú te enteres.

Si un canal pone «sin motivo apuntado», son descartes anteriores a que se
empezara a guardar el porqué. No se reparten a ojo: se dicen como lo que son.

Y si un canal de correo avisa de que no declara su dirección propia, ponla: sin
ella no puede distinguir sus propias respuestas de las de un cliente, y el buzón
puede acabar contestándose a sí mismo.

### Antes de clonar, fusionar o partir un cliente

Las tres sacan los datos de un cliente de donde están protegidos, así que el
CRM obliga a **simular primero**. La simulación no mueve nada: dice qué bloques
saldrían, cuántas filas y qué no se copia nunca.

En **Ciclo de vida del cliente** está todo lo que se ha simulado y todo lo que
se ha hecho, en secciones distintas y a propósito: una simulación no ha movido
nada, y mezclada con las ejecutadas se lee como si sí. Si una salió mal, se
queda entre las hechas con el motivo: saber qué se intentó es parte de saber
qué hay.

Dos cosas que conviene mirar antes de aprobar nada:

- **los avisos del plan.** Si la copia no va anonimizada, lo dice ahí. A un
  entorno que no es producción entran el consultor externo, el becario y el
  proveedor que está integrando algo;
- **los conflictos.** Una operación con conflictos sin resolver no es una
  operación lista.

### Si un cliente no puede escribir

Mira arriba del todo en **Ciclo de vida del cliente**. Cambiar la modalidad de
aislamiento de un cliente abre una **ventana de solo lectura** sobre sus datos,
y mientras esté abierta ese cliente no puede guardar nada. La pantalla avisa
cuando hay alguna abierta, y dice desde cuándo y cuántos minutos estaban
previstos.

Una migración que pone «verificada» con diferencias no está bien: está
**medida**. Las diferencias son filas que no cuadran entre el origen y el
destino, y cerrar la ventana con diferencias sin explicar es dar por bueno algo
que no se ha comprobado.

### El panel de gobierno, y cuándo no creértelo

En **Gobierno y cumplimiento** hay cuatro cifras arriba. La importante es la
primera, la cobertura, y lo primero que hay que mirar es **si hay número**.

Si pone «sin medir», no significa que esté mal: significa que todavía no hay
controles declarados ni evaluaciones con las que comprobar nada. Un panel vacío
en verde es el que más tranquiliza y el que peor informa, así que aquí no sale
verde: sale diciendo por qué no se puede medir.

Debajo, **lo que no cuadra hoy**, y cada línea trae su porqué. No es adorno: un
control evaluado como «no efectivo» está declarado y no protege, que es peor
que no tenerlo, porque consta como que alguien se ocupa.

Y en el informe de cobertura, si aparece el aviso de **controles que apuntan a
una capacidad que no existe**, míralo antes que nada. Ese control suma en la
cobertura y no vigila nada: es la única forma de estar descubierto sin que lo
parezca.

### Leer una campaña sin engañarte

Abre la campaña y mira en este orden:

1. **El gasto, partido.** Lo que ha gastado ella y lo que han gastado sus
   tácticas van separados. Sumados, una campaña que no ha gastado nada y cuyas
   tácticas se han comido el presupuesto parece barata.
2. **Lo que prometió, al lado de lo que va.** 400 clics es bueno si prometía
   300 y malo si prometía 2.000. Si un objetivo sale como «el embudo no mide
   esto», no es que vaya a cero: es que se declaró un objetivo sobre algo que
   nadie está contando, y eso se arregla en la campaña, no corriendo más.
3. **El ROI, si lo hay.** Si pone «no se puede medir» es que no hay ingresos
   atribuidos a esta campaña todavía. No es un cero: es que falta el dato.
4. **Los estados del embudo se pinchan.** Pincha «clicado» y salen quiénes son,
   con de dónde entró cada uno. Un contacto metido a mano y uno que entró por
   el segmento no se tratan igual.

Y si es una feria o un evento: mira primero **los inscritos sin marcar**. Si
quedan muchos, la tasa de asistencia no sale, y hace bien: una tasa calculada
ignorando a los que nadie marcó es una tasa inventada.

### Cuando resuelvas un caso, escribe el artículo ahí mismo

En el panel de cierre de un caso resuelto hay un enlace para escribir el
artículo. Úsalo **en ese momento**, no te lo apuntes para después: con el
problema fresco sale en cinco minutos, y en una sesión dedicada la semana que
viene no sale nunca. Por eso las bases de conocimiento se quedan vacías aunque
todo el mundo sepa cómo se arregla cada cosa.

El texto viene copiado de tu resolución. **Repásalo antes de guardar**: la
resolución casi siempre lleva el nombre del cliente, su configuración y a veces
sus credenciales. El artículo nace en borrador e interno, así que no se publica
solo; pero lo que escribas ahí es lo que alguien acabará publicando.

### Mirar un artículo y saber qué hacer con él

Tres cosas, y cada una pide algo distinto:

- **«Este artículo está entre los dañinos».** No significa que no se use:
  significa que lo ve mucha gente y la mayoría dice que no sirve. Alguien lo
  está siguiendo. Corregirlo va antes que escribir uno nuevo.
- **«Nadie lo usa ni lo cita».** Puede que sobre, o puede que no se encuentre.
  No es lo mismo que el anterior y no se arregla igual.
- **Las traducciones con «N versiones por detrás».** Una suele ser una errata;
  seis ya es otro artículo, y durante ese tiempo el cliente de ese idioma ha
  estado leyendo el procedimiento viejo.

Y la deflexión: el porcentaje dice **aproximada** porque lo es. No se sabe
quién habría abierto un caso si no hubiera encontrado el artículo, así que
sirve para ver una tendencia y no para justificar una plantilla.

### Antes de mandar un presupuesto

Cuatro cosas, en la ficha del presupuesto:

1. **Si pide aprobación, lee el motivo.** No es un trámite: dice qué regla se
   ha pasado y de cuánto, con el umbral y el margen mínimo al lado. Con eso se
   discute; sin eso sólo se espera.
2. **Mira el margen, no sólo el descuento.** Un 30 % de descuento sobre algo
   que deja 60 de margen y sobre algo que deja 12 son dos cosas distintas, y en
   la lista las dos ponen «30 %». Si el margen pone «sin calcular» es que las
   líneas no llevan coste: entonces el descuento no se puede valorar.
3. **Mira qué cambió respecto de la versión anterior.** Sale línea a línea, con
   el total antes y después. Mandar la tercera versión sin saber qué lleva
   distinto de la segunda es como se acaba regalando un descuento que nadie
   aprobó.
4. **Mira el documento.** Dice con qué plantilla, qué marca y qué idioma va a
   salir. Descubrirlo en el correo del cliente no tiene arreglo.

Y si cambias el precio, saca una **versión nueva**: no se edita el presupuesto
encima. Es lo que permite comparar y lo que deja constancia de lo que se ofreció
en cada momento.

### Cuando algo va mal en un entorno

Antes de tocar nada, abre **Entornos y despliegues** y mira ese entorno:

- **qué paquete hay puesto y desde dónde vino.** Si en producción hay un v7
  que llegó desde preproducción, lo que se probó allí es lo que está aquí;
- **la huella y el commit.** Dicen si lo que hay es exactamente lo que se
  empaquetó, y de qué cambio salió;
- **si alguien lo ha tocado a mano.** Es la causa más frecuente de «en
  preproducción funcionaba»: un campo cambiado a mano encima del paquete. Y
  ojo, porque el siguiente despliegue lo va a pisar sin avisar a quien lo
  cambió;
- **qué estaba declarado y ya no está.** Eso no lo pisa nadie: alguien lo
  borró.

Si pone que **no se ha podido medir** si lo han tocado a mano, no lo leas como
«está bien»: es que no se sabe. Y si dice que **no se puede volver atrás**,
tenlo en cuenta antes de desplegar encima: no habrá marcha atrás.

### Antes de escribir a alguien por un canal

En **Canales y consentimiento** pones el canal y el destino —el correo, el
teléfono— y te dice si se le puede escribir y, si no, **por qué no**.

Cuatro cosas que conviene saber:

- el permiso es **por canal y por destino**. Que alguien acepte el boletín no
  significa que acepte los SMS, y tratarlo como una sola casilla es como una
  baja acaba en una reclamación;
- en **WhatsApp**, si han pasado más de 24 horas desde que esa persona te
  escribió, sólo puedes mandar una plantilla aprobada. Si mandas otra no falla
  nada: el proveedor la tira y nadie se entera;
- la **palabra de baja** de cada canal sale en la lista. Tiene que ir dentro
  del mensaje;
- si el dominio está **calentando**, sale el tope de hoy. Pasarse quema la IP, y
  una IP quemada deja semanas sin que llegue nada por ese dominio: ni las
  campañas ni las facturas, que comparten reputación.

Si un canal aparece **sin forma de baja declarada**, por ahí no se puede mandar
nada comercial hasta que alguien la configure.

### Si alguien te menciona, lo verás en «Mis menciones»

Arriba, al lado del chat. Salen las de todo el CRM: las de una cuenta, las de
una oportunidad y las de un caso, juntas y lo más reciente primero. Desde cada
una se abre el registro, que es lo que se quiere hacer con ella.

Las **internas** van marcadas. Son las que el cliente no ve, y conviene saberlo
antes de contestar.

Y si sale un aviso de que **algún servicio no ha contestado**, la lista puede
estar incompleta: no lo leas como «no me han mencionado».

### Trabajar sin conexión

Si se va la red, sigues viendo lo que ya habías abierto y puedes seguir
editando registros y dando de alta. Arriba sale una franja amarilla:
**«Sin conexión: ves lo último que se consultó…»**. Al guardar, el aviso dice
que **se ha guardado en este dispositivo y se enviará al volver la red**: no es
un error.

Cuando vuelve la red se envía solo. Para ver qué queda pendiente: tu nombre,
arriba a la derecha → **Sin conexión** (o **Ver** en la franja).

- **Pendiente de enviar**: lo que aún no ha subido. Lo que el servidor rechazó
  se queda aquí con su motivo hasta que pulses **Descartar**.
- **Conflictos por resolver**: otra persona cambió el mismo campo mientras
  estabas sin red. Sale **lo tuyo** y **lo que hay en el servidor**; elige uno
  en cada campo y pulsa **Aplicar lo elegido**, o **Quedarme con lo del
  servidor** para olvidar tu cambio. Nada se elige solo.
- **Borrar sin red** también se guarda y se envía al volver: en la ficha,
  **Más → Borrar**. Si otra persona cambió ese registro entre medias, en
  **Sin conexión** eliges **Borrarlo igualmente** o **Quedarme con lo del
  servidor**.

Puedes editar sin red un registro aunque no hubieras abierto su formulario
antes: basta con haber abierto su ficha con red.

Al cerrar sesión se borra lo consultado de este dispositivo.

### Saber si una venta se puede cerrar

En la ficha de la oportunidad, el panel **«Qué falta para poder cerrar»** no te
da una nota: te da la lista de lo que no está. Un 62 sobre 100 no dice qué
hacer; «no hay criterio de decisión declarado» sí.

Debajo sale el **playbook de esa etapa**, con el porqué se eligió ése. Si no
sale ninguno, es que nadie ha escrito uno para esa etapa todavía: se crean en
Ventas → Playbooks.

Y el panel **«El plan con el cliente»** separa tres cosas a propósito:

- **lo retrasado nuestro**: eso se empuja aquí dentro;
- **lo retrasado del cliente**: esa conversación es con él, y mezclarla con la
  anterior es como se acaba echando la culpa al sitio equivocado;
- **lo retrasado de los dos**.

Si pone que el plan **no se ha compartido**, no es un plan conjunto: es una
lista nuestra con el nombre del cliente encima. Y si avisa de que la fecha
objetivo ya no se sostiene, es que con lo que queda por hacer no da tiempo.

### Si hoy va lento y ayer no

Mira **Estado** y baja hasta «Cuánto se está aplazando». Cuando un servicio va
apretado, el sistema aplaza lo que no es urgente para que lo importante siga
pasando. Si ahí sale un servicio como «el que peor va», ésa es la causa — y no
lo que estuvieras mirando.

Ojo con una cosa: lo que se aplaza lo decide el que peor está, no la media. Con
un servicio ahogado y trece bien, la media parece tranquila y aun así se está
difiriendo trabajo.

Y si pone que **no se ha podido medir la presión**, no es que esté todo
holgado: es que no se sabe.

### Si un cliente dice que su integración recibe errores 429

Mira en **Estado** el panel «A quién le ha bajado la cuota el freno
automático». Si ese cliente sale ahí, el sistema le ha reducido la cuota
porque se salió de su patrón de uso, y dice **cuánto** —al 75 %, al 50 % o al
25 %— y **por qué**. El freno se suelta solo; no hay que quitarlo a mano.

Si sale pero **sin frenar**, con «N de M ventanas observadas», es que todavía
no hay suficiente historia para evaluarlo: no es que el freno no funcione.

### Antes de ir a reparar algo

Abre el **activo** y mira tres cosas:

- **si lo paga la garantía.** Si pone «no se puede determinar», no es que no
  esté cubierto: es que nadie ha registrado la garantía todavía. Averiguarlo
  antes de la reparación cuesta una llamada; después, una discusión;
- **de qué forma parte.** Una bomba que falla puede ser la bomba o puede ser el
  equipo. Si el árbol avisa de que hay más componentes por debajo, hay más de
  lo que ves;
- **qué le ha pasado.** Si el historial dice que sigue una cadena de
  sustituciones, lo que ves incluye lo que le pasó a la máquina anterior — y
  eso suele ser justo el patrón que explica la avería de hoy.

Y mira **de cuándo es la lectura del contador**. Si no tiene fecha, no se sabe
si ese número es de hoy o del año pasado, y sobre un contador se decide cuándo
toca el próximo mantenimiento.

### Cerrar una orden de trabajo sin problemas después

Dos cosas en la ficha de la orden:

- **las líneas sin decidir quién las paga.** Ni se facturan ni se reclaman
  hasta que alguien lo diga. Dejarlas así es facturar de menos hoy o perder la
  reclamación cuando la garantía venza;
- **el parte.** Si sale el aviso de que se tocó **después de firmar**, la firma
  del cliente no vale: el texto que firmó ya no es el que hay. Y «firmado» no
  es «conforme»: un cliente puede firmar que estuvimos y no estar de acuerdo
  con el resultado.

### Elegir una plantilla de correo que funcione

En **Candidatos** salen primero las plantillas de las que se puede decir algo,
con su porcentaje **y el número de envíos al lado**. Mira siempre los dos: con
nueve correos, un 33 % son tres respuestas y mañana puede ser un 11 %.

Las que se han usado poco van aparte, en su propia lista. No es que sean malas:
es que todavía no se sabe.

Y la **apertura** no decide. Depende de un píxel que media industria bloquea,
así que una apertura baja puede ser la plantilla o puede ser el cliente de
correo de quien la recibe. La respuesta sí decide.

### Repartir una reunión entre el equipo

El botón «A quién le toca» **consume el turno**: al siguiente le tocará a otro.
No lo pulses para mirar, porque te saltas a alguien.

Si el equipo no tiene a nadie con disponibilidad declarada, te lo dice en vez
de repartir igualmente: una reunión asignada a nadie se queda sin proponer y
sin que nadie se entere.

---

### Exigir segundo factor a unos roles y no a otros

**Administrar › Identidad y seguridad › «Quién no tiene segundo factor» › «A
quién se le exige».** Elige un rol en el desplegable «Añadir un rol…» —se
pueden poner varios— y pulsa **Guardar**. A quien lleve alguno de esos roles se
le pedirá el código al entrar con contraseña; quien aún no lo tenga configurado
no podrá entrar hasta hacerlo. Por eso, al guardar, la pantalla dice en rojo
cuántas personas se quedarían fuera, y en la lista de abajo las marca con «se
le exige»: habla con ellas antes. Para quitar un rol, pulsa la × de su
etiqueta y guarda. Cumplen una aplicación de códigos (TOTP) o una passkey; el
SMS y el correo cuentan si tu empresa los tiene encendidos. No hay
notificación push.

### Entrar con el código de Okta Verify, Twilio Verify, Duo o RSA

**Administrar › Identidad y seguridad › «Segundo factor con el proveedor de la
empresa».**

1. En el desplegable «Empezar desde una plantilla…» elige tu proveedor (o «En
   blanco» si es otro). El formulario sale relleno; lee la nota de arriba.
2. Completa las variables (por ejemplo, el dominio o el identificador del
   servicio), escribe el **Secreto** —el token o la clave del proveedor; se
   guarda cifrado y no se vuelve a enseñar— y marca **Activo** si quieres que
   el login lo use ya. Pulsa **Guardar el perfil**.
3. Si el perfil pide datos de cada persona (el teléfono en Twilio, los
   identificadores en Okta), en «Quién es cada persona en el proveedor» elige
   a la persona, rellena sus datos y pulsa **Guardar sus datos**.
4. En «Probar un código» elige a una persona, escribe el código que le da su
   aplicación y pulsa **Probar un código**. Verás si el proveedor lo da por
   bueno y la petición enviada, con el secreto y el código tapados.

Con el perfil activo, al entrar se pide el código y vale el del proveedor. El
código propio (TOTP) y los de recuperación siguen valiendo. Si el proveedor
no responde, no se entra: avisa a quien administra.

### Entrar como otra persona para resolver un ticket (personal de plataforma)

1. Elige la empresa en el selector de la barra superior.
2. **Administrar › Plataforma y cumplimiento › «Entrar como otra persona, por
   soporte».** Elige a la persona en el desplegable y escribe el motivo —por
   ejemplo, el número de ticket y qué no le funciona—.
3. Pulsa **Entrar como esta persona**. Si hace rato que no usas tu segundo
   factor, la pantalla te pide que te verifiques primero.
4. Arriba de todas las pantallas verás «Estás dentro como … por soporte:
   «motivo»». Ves lo que esa persona ve.
5. Al terminar, pulsa **Salir y volver a mi sesión** en esa misma franja. Si te
   olvidas, la sesión de soporte caduca sola y vuelves a la tuya.

El acceso queda en **Plataforma y cumplimiento › Quién tocó qué**, eligiendo
«identity» o «Todos los servicios», con tu motivo.

### Si te sale un error, copia su identificador

Debajo de cada mensaje de error hay un **«Identificador de la petición»** con
un botón **Copiar**. Pégalo cuando escribas a soporte. Quien administra lo
pega en **Plataforma y cumplimiento › Quién tocó qué**, en el campo
«Identificador de petición», y ve lo que esa petición escribió, en cualquier
servicio.

### Cuánto tarda cada tipo de operación

**Estado › «Cuánto tarda cada tipo de operación».** Para lectura, escritura,
búsqueda y exportación, el percentil 95 y el 99 de este mes frente a su
objetivo, en verde si se cumple y en rojo si no. El 95 dice cuánto espera casi
todo el mundo; el 99, cuánto espera el que peor lo pasa. Junto a las
peticiones, «pocas para fiarse» avisa cuando el número es demasiado pequeño
para sacar conclusiones. El desplegable «Servicio» enseña uno solo.

### Dar de alta a tu empresa en las herramientas de la suite

**Administrar › Aplicaciones conectadas › «Alta de la empresa en las
herramientas» › Dar de alta en las herramientas.** Debajo sale cada
herramienta con su estado —dada de alta, ha fallado (se reintentará) o
apartada— y el último error. Si una ha fallado, el error dice por qué; se
reintenta sola, o desde la cuarentena si se aparta.

### Fijar o rotar la clave de una integración

**Administrar › Procesos y orquestación › Integraciones › (la conexión) ›
Fijar credenciales** (o **Rotar credenciales** si ya tenía). Pide los campos
que necesita esa conexión —un token, un usuario y una contraseña, o el
identificador y el secreto de cliente— y, si quieres, cuándo caduca. Al
guardar se crea una versión nueva y la anterior se desactiva. Lo que escribes
no se vuelve a enseñar nunca: la ficha dice qué versión hay, cuándo se fijó y
quién. **Probar la conexión**, al lado, dice si responde.

### Mandar un contrato a firmar, recordarlo o cancelarlo

**Operación › Sobres de firma › (el sobre)**. Arriba, «Qué hacer con el sobre»
ofrece lo que toca según su estado: **Enviar a firmar** (pide confirmar, porque
al cliente le llega un correo), **Recordar a quien le toca**, **Cancelar el
sobre** (con el motivo) o, cuando está completado, **Archivar el firmado**.
Debajo sale lo que contestó: hasta cuándo vale, a quién se recordó.

### Ver tus envíos desde el portal (para el cliente)

En **tu área de cliente**, «Vuestros envíos y encargos» lista los de tu
empresa con su referencia y si van con retraso. **Ver por dónde va** abre los
pasos y las incidencias.

### Crear una reunión en línea

En la ficha de una **actividad de reunión**, o en la de una **cuenta** («Lo que
ha pasado»), pulsa **Crear reunión en línea**, añade los asistentes y **Crear la
sala**. Se crea en la suite de tu empresa (Teams o Meet, la que esté conectada)
y el enlace **Entrar en la reunión** queda en la actividad. Si el botón sale
apagado, debajo dice por qué: normalmente, que no hay suite conectada o que no
has autorizado las reuniones en **Consentimiento de suite**.

### Llamar a un contacto o a una cuenta

En la ficha de un **contacto** (bloque **Llamar**) o en la de una **cuenta**
(«Lo que ha pasado» › **Llamar**), elige el número, marca **La persona consiente
que se grabe** si te lo ha dicho y pulsa **Llamar**: la centralita de tu empresa
marca. Si la persona pidió no ser llamada, el CRM no llama y te dice por qué.
Al colgar, la llamada queda sola como actividad en la ficha, con su duración;
tú sólo eliges **Cómo fue**, escribes **Qué se habló** y pulsas **Anotar y
cerrar**. Con «Pide que no le llamen» la ficha queda marcada como «no
contactar»; con «Reprogramar» pon la fecha y se crea la siguiente llamada.

### Atender una llamada que entra

Cuando te entra una llamada, abajo a la derecha sale **Llamada entrante** con
quién es (o las fichas que comparten ese número), **lo que ya dijo en el IVR**
—no se lo vuelvas a preguntar— y lo último que le pasó. **Abrir su ficha** te
lleva a ella. Para pasarla, **Transferir**, escribe a quién y un resumen y pulsa
**Transferir con el resumen**: quien la recibe lo lee. Al colgar se registra
sola.

### Conectar la centralita y ver las llamadas (administración)

**Servicio › Telefonía.** En **Perfil de telefonía** elige la **Conexión** de
Integraciones de tu centralita —con las operaciones `originar_llamada` y
`transferir_llamada` declaradas— y ajusta **Cómo se lee el aviso de la
centralita**; pulsa **Guardar el perfil**. Debajo dice qué falta. La centralita
manda sus avisos a `POST /api/v1/telefonia/avisos` con una clave de API. En
**Llamadas** se ve cada una: quién, cómo terminó, cuánto duró, el IVR,
**Escuchar** la grabación y **Ver actividad**.

### Mandar los hechos al motor de comisiones (administración)

**Ventas › Compensación externa.** En **Motor**, elige la conexión del motor
(con `enviar_hechos` y `leer_calculo`) y pulsa **Usar como motor**. En
**Periodo**, pon las fechas y pulsa, en orden, **Recoger las ventas ganadas**,
**Mandar lo pendiente**, **Traer el cálculo** y **Conciliar con la casa**. Los
cobros, devoluciones y anulaciones se dan de alta en **Cobro, devolución o
anulación**. En **Hechos** se ve cada uno con lo que calculó el motor, lo que
calcula la casa y la **Diferencia** en rojo cuando no cuadra.

### Lo que estaba en la API y ahora se ve

- **Por qué un lead cayó donde cayó.** **Ventas › Candidatos**, abre el lead y
  pulsa **Ver** en «Por qué cayó aquí y cómo llegó»: a la izquierda las reglas
  de reparto que se evaluaron (cuál ganó y por qué no encajó cada una), a la
  derecha sus toques en orden.
- **Qué quiere recibir un contacto.** **Ventas › Cuentas**, abre el contacto:
  en «Lo que quiere recibir» marca o desmarca cada categoría si te lo pide por
  teléfono (las obligatorias no se pueden quitar y lo dicen). Al lado, a qué
  hora suele abrir.
- **La carpeta del registro en el gestor.** En la ficha, pestaña
  **Relacionado › Documentos**, pulsa **Ver la carpeta de este registro en el
  gestor**: entra en sus subcarpetas pulsándolas, vuelve con el camino de
  arriba y busca sólo dentro con **Buscar sólo dentro de esta carpeta**.
- **Quién manda sobre un objeto durante una migración.** **Procesos y
  orquestación**, abre una regla de convivencia: arriba sale quién manda hoy y
  si se escribe aquí.
- **Qué ve un agente de fuera.** **Analítica › Gobierno de la IA**, vista
  **Exposiciones MCP**, abre una: arriba, sus herramientas.
- **Si un activo de marketing se puede publicar.** **Marketing › Segmentos**,
  vista **Activos de marketing** (o **Aprobaciones de activos**), abre el
  activo: «¿Se puede publicar ya?».
- **Qué ha cambiado en la previsión.** **Ventas › Previsiones**, abre un
  periodo y, en «Qué ha cambiado entre dos fotos», elige **Desde la foto** y
  **Hasta la foto**.
- **Qué fecha prometer.** **Ventas › Coste**: escribe el plazo del proveedor
  (y, si quieres, los días propios) y pulsa **Ver qué fecha se puede
  prometer**.
- **Mis huecos.** **Ventas › Plantillas y reuniones**, **Ver mis huecos**.
- **¿Ya existe esta empresa?** **Clientes › Duplicados**, escribe el nombre
  (y el NIF) y pulsa **Comprobar**.
- **¿Se le puede mandar este correo?** Abre una plantilla de correo y, en
  «Vista previa con datos reales», elige un contacto: debajo dice si se le
  puede mandar y, si no, por qué.
- **Administración**: en **Aprobar documentos** se ve a qué organización del
  gestor está mapeada la empresa; en **Estado**, si la instalación necesita
  esta interfaz; en **Operación**, vista **Catálogo de eventos**, quién escucha
  el flujo de eventos; en **Gobierno de la IA**, vista **Consumo y coste**, qué
  modelo atendería sin sacar el dato de la región.
- **Si eres proveedor**, en tu portal, «Tus papeles con nosotros» dice ahora
  también para qué estás homologado y hasta cuándo.

### Las listas de tu empresa: roles, relaciones, funciones y resultados de llamada (administración)

Cinco listas que antes venían cerradas con el producto ahora las decide tu
empresa:

| Lista | Dónde se usa |
|---|---|
| **Roles en la compra** | el papel de cada persona en una oportunidad (decisor, económico, prescriptor…) |
| **Roles en el equipo de cuenta** | quién lleva una cuenta y como qué (KAM, técnico, soporte…) |
| **Relaciones entre personas** | el mapa de influencia de una cuenta (reporta a, aliado, detractor…) |
| **Funciones de contacto de proveedor** | para qué se llama a cada contacto de un proveedor |
| **Resultados de una llamada** | lo que eliges al colgar en el marcador |

**Dónde**: **Administrar › Herramientas de plataforma › Gestor de objetos**, y
en el desplegable de pestañas que hay junto al título, la lista que quieras.
Con **Nuevo** añades un valor (un código en minúsculas y sin espacios, su
rótulo y su orden); abriendo uno le cambias el rótulo o el orden, o lo
retiras. Retirar no borra: lo que ya lo usa lo sigue enseñando. La pestaña
**Vocabularios de negocio** dice, servicio a servicio, cuáles siguen con los
valores de fábrica y cuáles ya son de tu empresa.

**Los marcados como «fijo» no se pueden retirar**, sólo renombrar: el CRM hace
algo con ellos. «Decisor» y «económico» son los que mide la cobertura de una
compra; «escalado» es a quien se llama cuando un proveedor falla; y en las
llamadas, «hablado» pide la nota, «pide que no le llamen» marca la ficha como
«no contactar» (es una obligación legal), «número erróneo» marca el teléfono y
«reprogramar» crea la siguiente llamada. Si lo intentas, te lo dice.

**Una relación nueva que sea una opinión sobre alguien** —«hostil», por
ejemplo— márcala con `{"opinion": true}` en su campo *extra*: así, como
«aliado» y «detractor», exigirá el motivo al anotarla.

### La hora a la que escriben las cadencias (administración)

Una cadencia que pide días laborables no toca a nadie de noche ni en fin de
semana. Desde el 10-11-2026 **las horas son las del reloj de tu empresa** (la
zona horaria de sus ajustes), también cuando cambia la hora en octubre y en
marzo; antes se miraban en hora universal y en España la ventana se corría una
o dos horas. Se cambian en **Ajustes**: `cadencia_hora_desde` (8: antes no se
escribe), `cadencia_hora_hasta` (19: desde esa hora pasa al día siguiente) y
`cadencia_hora_reprograma` (9: a qué hora se recoloca lo que caía fuera). Vale
también para el **primer** toque: si inscribes a alguien un viernes por la
noche, el primer correo sale el lunes a las 9, no esa misma noche.

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
