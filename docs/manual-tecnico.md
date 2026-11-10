# Manual técnico

Este manual está escrito para quien **instala, configura, integra y mantiene**
contecrm. Es independiente del [manual de usuario](manual-usuario.md): no hace
falta leer aquel para entender este, ni al revés.

Lo que vas a encontrar:

1. **Qué es esto por dentro** y por qué está construido así.
2. **Cómo se despliega**, en tres escenarios reales.
3. **Cómo se configura**, y qué pasa si tocas cada cosa.
4. **Cómo se integra**: API, eventos, conectores y contratos.
5. **Cómo se opera**: copias, migraciones, observabilidad y qué mirar cuando algo
   va mal.

Una nota sobre el tono: aquí se explican también las decisiones que **no** se
tomaron y por qué. Un manual técnico que solo describe el resultado obliga al
siguiente a redescubrir los motivos, y normalmente los redescubre rompiendo algo.

---

## 1. Qué es esto por dentro

### 1.1 La forma general

contecrm es un conjunto de **servicios orquestados**, no un monolito. Cada
servicio tiene su esquema de base de datos, su API y su responsabilidad:

| Servicio | De qué es dueño |
| --- | --- |
| `gateway` | La puerta de entrada. Enruta, compone y es el único que llama a los demás por HTTP |
| `tenancy` | Tenants, planes, cuotas, marca, ciclo de vida del cliente |
| `identity` | Usuarios, roles, permisos, SSO, sesiones |
| `metadata` | El metamodelo: objetos, campos, layouts, validaciones, entornos |
| `party` | Cuentas, contactos, actividades, calidad del dato, proveedores |
| `sales` | Pipeline, oportunidades, presupuestos, precios, previsión, partners |
| `service` | Casos, SLA, conocimiento, servicio de campo, omnicanalidad |
| `marketing` | Segmentos, campañas, recorridos, canales, activos |
| `intelligence` | Scoring, salud, generación, extracción, agentes, voz |
| `analytics` | Informes, cuadros de mando, métricas |
| `integration` | Conectores, suites de productividad, telefonía, firma |
| `orchestrator` | Procesos largos, sagas, aprobaciones |
| `automation` | Reglas del tenant, extensiones, entornos de automatización |
| `eventing` | Bus, webhooks, CDC, replay |

**Ningún servicio lee el esquema de otro.** No es una convención: los permisos de
base de datos lo impiden. Lo que hace falta de otro servicio llega por dos vías:

- **Eventos**, cuando se necesita *ver* algo: cada servicio mantiene su propia
  proyección local de lo que le interesa. La salud de la cuenta se calcula en
  `intelligence` y `party` guarda una copia para poder enseñarla en la ficha.
- **Comandos**, cuando se necesita *cambiar* algo: se pide por el bus y el dueño lo
  ejecuta. Por eso hay estados que dicen «pedido» y no «hecho» — porque todavía no
  lo está.

Esto tiene un coste que conviene asumir de frente: **la consistencia es eventual
en los bordes**. A cambio, un servicio no puede tumbar a otro por una consulta mal
escrita, y cada uno se despliega y se escala por separado.

### 1.2 Multi-tenancy

Tres capas, y las tres están puestas a la vez:

1. **RLS en Postgres, en modo FORCE.** Una consulta sin tenant en contexto no
   devuelve filas, ni siquiera para el dueño de la tabla.
2. **Guardia en el ORM.** Toda consulta pasa por un filtro que exige `tenant_id`.
3. **Contexto de petición.** El tenant se resuelve al entrar y viaja con la
   petición, incluidas las tareas de fondo.

La primera es la que manda: las otras dos existen para fallar antes y con mejor
mensaje. Hay un gate que hace *fuzzing* de tenant contra todas las rutas
publicadas, y ha encontrado fugas reales.

#### Qué prueba la suite y qué no

Conviene saberlo porque se confunde, y confundirlo da una falsa tranquilidad:
**ninguna prueba de la suite ejercita la RLS**. El arnés conecta con un rol
superusuario, y Postgres se salta Row-Level Security para un superusuario pase
lo que pase, esté la política en FORCE o no. El propio arranque lo dice en cada
pasada —`arranque.rls_sin_garantia`— y es correcto que lo diga.

O sea que lo que la suite comprueba es la **segunda y la tercera** capa: el
filtro del ORM y el contexto de la petición. Que son las que se rompen más a
menudo, y las que rompió la fuga del 27-10-2026. Pero la primera, la que sigue
puesta el día que alguien escriba una consulta a mano, **sólo se puede
comprobar contra un despliegue de verdad**:

```
python scripts/de_quien_son_las_filas.py
```

Mira tres cosas, de más grave a menos: con qué rol se conecta la aplicación
—si es superusuario o puede saltarse la RLS, la política no filtra nada—, qué
tablas con `tenant_id` no tienen RLS, FORCE o política, y la que de verdad
contesta: se pone en el sitio de un cliente y **cuenta las filas ajenas que
ve**. Lo demás son indicios de que debería funcionar; esto es mirarlo.

El mismo script separa los dos problemas que desde la pantalla se confunden:
que los datos **se vean** de todos los tenants, y que estén **copiados** en
todos. Se arreglan en sitios opuestos —el primero en la sesión, el segundo
borrando— y para distinguirlos compara los nombres, no sólo cuenta tenants por
tabla: dos tenants con cuentas distintas son dos clientes, no una copia.

### 1.2.1 La misma colección en dos sitios

Pasa, y a veces está bien. La regla para decidirlo es una sola pregunta: **¿qué
pregunta contesta cada sitio?** Si las dos contestan la misma, es una sola
pantalla y la otra sobra.

Está bien cuando el segundo sitio cambia la pregunta:

- **otro corte** — la ficha de cliente enseña los casos *de esa cuenta*, el
  tablero enseña las oportunidades *como embudo*, Inicio enseña las actividades
  *de hoy*;
- **entrada, no listado** — el chat pide usuarios *para elegir a alguien*,
  Nexus pide agentes *para elegir uno*, entornos y despliegue pide entornos
  *para elegir dónde*.

Está mal cuando el segundo sitio es **la misma lista con menos poder**. El caso
que lo destapó: la cola de duplicados salía como pestaña del módulo de cuentas
—que sólo pinta filas— y como pantalla propia, que además deja fusionar
eligiendo cuál se queda, marcar que no son la misma y dejarlo para luego. Quien
entraba por la pestaña veía dieciocho parejas, no podía hacer nada y no sabía
que existía el otro sitio. La pestaña se quitó el 28-10-2026.

Medido ese día, para no decidir por impresión: de 211 pestañas declaradas en
`recursos.ts`, **una** ruta salía en dos pestañas (`/api/v1/supresiones`) y
**15** colecciones las pide además una pantalla a medida. De esas 15, casi
todas cambian la pregunta; la de duplicados era la que no.

**Resuelto el 29-10-2026.** «Supresiones» salía en «Segmentación» y en
«Contenido y gobierno»: la misma ruta, la misma lista, dos sitios desde los que
editarla. Se queda en «Contenido y gobierno», con las renovaciones de opt-in y
las categorías de preferencia, porque la pregunta que contesta es de
consentimiento —«a quién no se le puede escribir»— y no de segmentación. El
manual de funcionalidades ya la situaba ahí; era la aplicación la que no
coincidía.

Y el mismo día se cerró la otra forma de que pase, que es **dentro de un
módulo**: tres pestañas de «Cuentas» —planes de cuenta, estado financiero y
cambios de empresa— se habían añadido por duplicado sin que nada lo notara,
porque el fichero tiene dos mil líneas y las pestañas de un módulo no están
ordenadas por nada.

Ahora hay gate, en `frontend/src/pruebas/ninguna_opcion_repetida.test.ts`, y
mira las dos cosas: que un módulo no tenga dos pestañas con el mismo nombre ni
con la misma ruta, y que una ruta no salga en dos módulos. Las excepciones se
escriben **una a una con su motivo** —hoy no hay ninguna—, en vez de una lista
de permitidos, que es lo que se queda corto en cuanto alguien añade el
siguiente. Validado plantando los dos duplicados: los caza y dice cuáles son.

### 1.3 El metamodelo

Los objetos y los campos de cada tenant viven en `metadata` y se aplican en
caliente. Un campo personalizado se guarda en JSONB, con:

- **índice de expresión** creado y retirado por el propio sistema cuando se usa
  para filtrar,
- **vista SQL tipada** por tenant, para que BI lea columnas y no JSON,
- y **descripción semántica**, que es lo que permite que la IA lo use.

Publicar un esquema es explícito: mientras alguien define campos, el esquema a
medias no viaja.

### 1.4 Seguridad

- **Autenticación**: JWT propio o SSO (OIDC siempre; SAML como extra opcional
  porque `xmlsec` obliga a compilar).
- **Autorización**: permisos por operación, reglas de compartición, jerarquía de
  mando replicada, y un punto de decisión único — `crmcore.authz.decision.exigir`—
  por el que pasa **todo** cargador de registro. Hay un gate que lo comprueba.
- **Cifrado**: en tránsito siempre; en reposo, los campos marcados como sensibles,
  con clave por tenant y posibilidad de traer la propia (BYOK).
- **Auditoría encadenada**: cada entrada lleva el hash de la anterior, así que
  alterar el registro se nota.

#### El sistema de diseño en oscuro es el de contecflow

No solo la piel. Además de la paleta, la tipografía, los radios y las sombras,
son suyas las medidas del armazón, y viven como token en `index.css` para que
ninguna pantalla pueda ponerse la suya:

| Token | Valor | Antes aquí |
|---|---|---|
| `--page-pad-x/y` | 32px | 24px, escrito a mano en `Marco.tsx` |
| `--page-max-w` | 1400px | 1152px (`max-w-6xl`) |
| `--panel-w` | 222px | 288px (`w-72`) |
| `--panel-w-plegado` | 46px | no existía: el panel no se plegaba |
| `--panel-plegar` | 1280px | — |
| `--barra-h` | 48px | 56px (`h-14`) |

Y el cuerpo va a **14px**, que es lo que faltaba de verdad: sin esa línea
heredaba los 16px del navegador, y todo lo que no lleva una clase `text-*` salía
un 14 % más grande que la misma frase en contecflow.

#### El gateway publica su propio contrato (03-11-2026)

`GET /api/v1/contrato/{servicio}` hace de proxy al OpenAPI de cada servicio,
leyéndolo de la tabla de enrutado. El gateway **no se enruta a sí mismo** —eso
expondría sus rutas por un camino paralelo a esa tabla, que es la única lista
de acoplamiento del sistema—, así que `contrato/gateway` contestaba 404 y la
pantalla «Contrato de la API» salía con un error.

Ahora esa ruta devuelve su propio OpenAPI sin salir por la red. Y de paso
cerró un agujero mayor: el gate `contrato-headless` **eximía al gateway** con
este motivo escrito —«es un proxy, y su única ruta propia es el registro de
servicios»—, que dejó de ser verdad sin que nadie lo revisara. **Medido: son
39** —`/buscar`, `/superficie`, `/estado/*`, `/sesion/*`, `/integracion/*`—, y
el `return` las dejaba a todas sin comprobar. Quitada la exención, pasan.

#### Dos radios y ya (03-11-2026)

Lightning tiene **dos**: 4 px para todo —botones, campos, tarjetas,
insignias— y 8 px para lo que flota encima. Esa falta de escala ES el aspecto.
Los nombres de Tailwind se dejan todos apuntando a esos dos valores, para que
un `rounded-xl` escrito en cualquier pantalla mida lo que toca sin tocarla: un
buscar-y-reemplazar se olvida de la pantalla que nadie abrió.

Al cerrar el rediseño quedaban dos escalones fuera: `sm` valía 2 px —para
cinco casillas y dos cuadraditos de leyenda— y `3xl` valía 28 px **sin que lo
usara nadie**. Un escalón que no se usa es uno que alguien usará el día que no
mire, y entonces vuelve a haber cuatro radios. Los dos colapsan a 4 px.

Lo vigila la misma prueba que la letra: ningún `rounded-[14px]` entre
corchetes y ningún `border-radius` en píxeles que no sea 0, 4 u 8. La única
excepción, con su motivo, es el pulgar de la barra de desplazamiento del
navegador, que no es una caja del sistema.

#### La monoespaciada, sólo para lo que se lee carácter a carácter

**Medido el 03-11-2026**: 42 pantallas y 472 textos salían en Roboto Mono, y
lo que salía no era código —«sin medir», «escuchando», «conversaciones», «0
recibidos · 0 descartados», «Apertura: no hay con qué medirla todavía»—. La
monoespaciada es para un identificador, un código, un hash o una cifra que se
alinea en columna. Una frase en castellano, no; en Lightning no hay
monoespaciada en la interfaz salvo para código.

La llevaban cuatro clases base —`.badge`, `.toggle-badge`, `.btn-link` e
`.input-sm`—, y quitarla de ahí bajó poco: **el grueso eran los 141
`font-mono` escritos a mano**. El patrón que los explica es casi siempre el
mismo: el hueco de un dato que normalmente es un identificador, y cuyo
RESPALDO es una frase. Ahora la clase es condicional —`cn("…", valor &&
"font-mono")`—, así que el identificador la lleva y el «sin declarar» no.

Lo que sí se queda en monoespaciada, y se comprobó uno a uno: el JSON del
editor de procesos, los permisos incompatibles de `/seguridad`
(`quote:write ↔ aprobacion:decidir`) y los scopes de OAuth de `/suite`.

#### La escala tipográfica (02-11-2026)

Hasta el 02-11-2026 se usaban los tamaños de Tailwind
—10/11/12/14/16/18/20/24/36/48— más tres escalones añadidos, 12.5, 15 y 22.
**Medido en las 58 pantallas**, eso daba once tamaños a la vista —32, 22, 20,
18, 16, 14, 12, 11, 10, 9,6 y 9 px—, con saltos de un píxel entre 10, 11 y 12 y
una pantalla usando nueve a la vez. Entre 10 y 11 nadie puede decidir, así que
cada pantalla salía de un tamaño distinto.

Y el número no era lo peor: **el 77 % del texto estaba en 10 u 11 px** —508
usos de `text-3xs` y 458 de `text-2xs` de 1.257 en total—. Lightning no baja de
12 y su cuerpo es 13.

Ahora son **siete escalones, con nombre por su papel y ninguno por debajo de
12**:

| clase | px | para qué |
|---|---|---|
| `text-rotulo` | 12 | rótulos, metadatos, lo secundario |
| `text-dato` | 13 | el cuerpo |
| `text-titulin` | 14 | encabezado pequeño |
| `text-titulo` | 16 | encabezado de sección |
| `text-grande` | 20 | encabezado de bloque |
| `text-pagina` | 24 | el título de la pantalla |
| `text-hero` | 32 | la cifra que se mira de lejos |

El nombre dice el papel y no el tamaño: así se puede volver a ajustar la escala
sin tocar mil sitios. Y la escala va **en el tema y no en `extend`**, de modo
que `text-sm`, `text-lg` y las demás de Tailwind dejan de existir — escribir
una deja la clase sin regla.

Las celdas de tabla tienen su propio token porque dependen de la densidad:
13 px en compacto y 14 en cómodo, con 12 y 13 para una tabla de apoyo. Antes
era 11 y «menos un píxel», que daba 10 — dos tamaños por debajo del mínimo y
ninguno de los dos en la escala.

Lo vigilan dos cosas, y hacen falta las dos: una prueba que lee el código
(`la_escala_tipografica_no_se_inventa`) y la medida real en el navegador dentro
del barrido de pantallas. A la primera se le escapó un 9 px escondido tras una
constante.

El panel se pliega a raíl de iconos por debajo de 1280px, y ahí se aparta a
propósito de contecflow en una cosa: allí el raíl enseña el icono de cada
pantalla, y aquí enseña el del **área**. Los veinticinco módulos del catálogo no
traen icono, y ponerles uno sería inventarse veinticinco símbolos que nadie ha
escogido por lo que la pantalla hace; siete iconos de área, que sí están
escogidos, orientan más. El rótulo llega al pasar por encima, en el mismo panel
flotante que usan ellos.

##### La paleta, entera

A los cuatro tonos de siempre se suman las familias que contecflow distingue y
que aquí se metían en ellos. Meter dos significados en un color es lo que hace
que dos avisos distintos se vean iguales:

| Familia | Para qué |
|---|---|
| `info` | lo que informa y no pide nada — un aviso neutro no es un error |
| `purple` | lo que hace una máquina — sugerencia, detección, clasificación |
| `orange` | una severidad intermedia, entre el aviso y el peligro |
| `coral` | destructivo del que no se vuelve, distinto de un error |
| `sky`, `chart-teal`, `chart-lime`, `chart-pink` | distinguir **categorías** entre sí: con cuatro tonos semánticos la quinta serie de un gráfico repite color y dos líneas dejan de poder seguirse |
| `portal`, `portal-surface`, `portal-deep` | el lienzo del portal de cliente y proveedor, propio a propósito: quien entra ahí no es de la casa y debe notarlo |

Cada una respeta la regla del sistema: el token es el **relleno** y `*-text` es
el mismo tono movido en luminosidad hasta 4.5:1 contra `paper-lighter`. Cuatro
lo necesitaron —`coral` y `chart-pink` en oscuro, y en claro casi todas, porque
un naranja o un lima legibles sobre blanco son forzosamente marrones.

##### El tema claro también es el suyo

Me equivoqué al decir que contecflow no tenía tema claro: lo tiene, en
`[data-theme="light"]`, junto a otros cuatro (freight, alto contraste, midnight,
slate). Lo que había aquí era el claro de contecmind —los grises de
Google/NotebookLM—, así que entre los dos temas de esta aplicación había dos
casas distintas y bastaba con darle al interruptor para verlo.

Una sola desviación: su `--text-3` es `#94a3b8`, que da **2.08:1** contra
`paper-lighter`. En contecflow es explícitamente decorativo, pero aquí
`ink-faint` es el token de los pies de foto y los marcadores de posición, que
son texto y siempre en 10-12px. Sube al mismo tono hasta 4.61:1.

##### Dos gates nuevos, porque esto no se sostenía a mano

- **`frontend/scripts/contraste.mjs`.** Mide cada `*-text` contra la peor
  superficie de su tema y exige que todo relleno tenga su variante. `index.css`
  llevaba meses diciendo que de esto respondía `e2e/a11y-contraste.spec.ts`, y
  ese fichero **no existía**: un comentario que promete una comprobación que no
  está es peor que no decir nada, porque quien lo lee deja de mirar.
- **`frontend/scripts/clases-sin-regla.mjs`.** Compara las clases de color
  escritas contra el CSS construido. Tailwind solo emite lo que existe en su
  configuración, así que una clase mal escrita no da error en ningún sitio —
  pasa el `tsc`, pasa el `eslint`, construye— y el elemento sale sin color.


Paleta, tipografía (**Geist** y Roboto Mono) y radios: los de contecmind,
adoptados enteros desde `contecmind/frontend/src/index.css` el 29-09-2026, no
«inspirados en». Quien usa dos productos de la casa no debe notar que cambia de
uno a otro, y dos paletas parecidas se separan a la tercera pantalla que alguien
añade.

**Antes eran los de contecflow**, y conviene saber por qué se cambió y qué se
perdió. El motivo de traer los suyos seguía siendo cierto: DM Sans se lee con
menos esfuerzo en pantallas densas —tablas de doce columnas, listas largas— y
sus radios, algo menos redondos, evitan que una tabla con muchas cajas pequeñas
parezca un montón de pastillas. Eso es lo que se sacrifica. Se cambió porque el
catálogo declara que el sistema de diseño es idéntico al de contecmind, y entre
hacerlo cierto o matizar el enunciado se eligió hacerlo cierto.

Y se midió antes de decirlo: de los 30 tokens que los dos productos comparten,
**26 tenían valor distinto en claro y 25 en oscuro**; solo coincidían 6 nombres.
Hoy hay un gate que lo comprueba contra el fichero de contecmind y se pone rojo
si se vuelven a separar.

Sobre la tipografía hay un detalle que conviene no perder: la lista empieza por
«Google Sans Text», que es lo que pone contecmind, pero **ninguno de los dos
productos la tiene** —es propietaria de Google y el comentario de contecmind lo
dice—. Lo que los dos renderizan de verdad es Geist. Nombrarla sin cargarla
habría hecho que el navegador cayera a la del sistema mientras el fichero decía
que eran iguales, así que aquí se cargan los mismos pesos que carga contecmind,
del 300 al 800.

Tres cosas que no se copiaron a ciegas:

- **Los `-text`.** El token base es el relleno; la variante de texto es el mismo
  color subido en luminosidad hasta pasar 4.5:1 contra `paper-lighter`, que es
  la superficie más clara y por tanto el peor caso.
- **Dos tokens propios hubo que subirlos al adoptar la paleta ajena.** La
  superficie `--paper-lighter` de contecmind es más clara que la que había, y
  dejó `--coral-text` en 4.13:1 y `--chart-pink-text` en 4.14:1 — los dos por
  debajo del mínimo legible. Son tokens de gráficas, que contecmind no tiene, así
  que seguirle no los arregla: se aclaran un 9 %. Hay un gate que mide el
  contraste de los 38 tokens de texto y no deja bajar de 4.5:1.
- **Las elevaciones no se tocaron**: ya coincidían al byte con las suyas.
- **Las sombras.** Una sombra es la ausencia de luz sobre una superficie, así
  que no puede ser un valor único para toda la app: las de Material son gris
  translúcido pensado para blanco y en oscuro no se ven —una tarjeta elevada
  queda tan plana como el fondo—, y las de contecflow son negro a opacidad
  0.4-0.7 y sobre blanco son un manchón. Así que `--shadow-1..5` y
  `--shadow-accent` se declaran **dos veces**, Material en `:root` y contecflow
  en `.dark`, y `tailwind.config.js` solo los referencia. contecflow tiene tres
  niveles y aquí hacen falta cinco —hay modales sobre paneles sobre tarjetas—,
  así que se continúa su progresión.

#### Una pantalla rota no se lleva la aplicación entera

Hasta el 04-10-2026 **no había ninguna frontera de error en todo el front**. Un
`TypeError` al pintar cualquier pantalla —por ejemplo, una respuesta de la API
con una forma que esa pantalla no esperaba— dejaba el `<body>` **vacío**. No una
pantalla de error: vacío. Sin mensaje, sin menú, sin forma de volver, y sin nada
que el usuario pudiera contarle a soporte. React desmonta el árbol entero cuando
un error sube sin que nadie lo recoja, y eso es lo que pasaba.

Se descubrió montando las pruebas de pantalla: la primera dio «0 elementos
visibles» con la página entera en blanco.

La frontera va **dentro del marco**, no fuera, y es deliberado: lo que se cae es
el contenido, así que el menú, la barra y la paleta siguen ahí y el usuario puede
irse a otro sitio. Una frontera por encima del marco convertiría el mismo fallo
en la misma pantalla en blanco con otro texto. Y se remonta al cambiar de ruta,
porque si no una pantalla rota deja a quien navega atrapado en su error.

#### Las pruebas de pantalla, y qué NO comprueban

`npm --prefix frontend run pantallas` abre las 22 pantallas fijas en un navegador
de verdad y exige tres cosas: que la aplicación monte, que no se quede en blanco
y que nada se salga del ancho de la ventana. Corre en el nivel `--todo` del
preflight y tarda unos 14 segundos.

**No comprueba que cada pantalla enseñe lo que dice enseñar**, y conviene que
esto quede escrito porque un verde se lee como lo que no es: para eso hace falta
un doble que devuelva la forma correcta de cada llamada, y eso es trabajo por
pantalla que no está hecho. De las 53 capacidades de pantalla del catálogo, esto
cubre la primera condición de todas: que existan y se abran.

Tres trampas que el doble evita a propósito, las tres por avisos de contecpos,
donde un barrido llevaba 83 rutas en verde sin haber mirado una sola pantalla:

- **Se filtra por `resourceType`, no por trozos de la dirección.** Allí el doble
  interceptaba «la dirección contiene `/agenda/`», y la dirección de la propia
  pantalla también lo contiene: servía `[]` **como documento**, y la página
  entera era el texto «[]». Sin error, con texto visible y cabiendo en pantalla.
- **Se exige que la aplicación haya montado.** Allí no montaba y se quedaba en la
  pantalla de «Arrancando…», que tiene un `<h1>`, así que hasta la comprobación
  del título pasaba.
- **Se cuentan elementos con caja**, no `innerText`: el texto de un elemento con
  `display:none` cuenta, y una pantalla vacía con un menú oculto sale llena.

#### La pantalla de entrada (02-11-2026)

Hasta hoy era la **única** pantalla del CRM fuera del sistema de diseño, y lo
era a propósito: copiaba la de contecflow carácter por carácter. **Medido**:
12 colores propios, 18 bloques de estilo en línea, 13 tamaños de letra y tres
radios —10, 12 y 20 contra los 4 del sistema—.

El propio fichero dejaba la decisión pendiente: «hoy el CRM se ve como
contecmind y su puerta como contecflow, que es justo la incoherencia que el
cambio venía a quitar». Con el CRM ya en Salesforce Lightning, la puerta se
parecía todavía menos, y era la primera pantalla que ve cualquiera.

Ahora usa los tokens y las clases de la casa, y con eso gana tres cosas que no
tenía:

- **Respeta el tema.** Era oscura siempre; ahora sale clara u oscura según lo
  que cada quien tenga guardado. Comprobado en los dos.
- **Entra en el gate de contraste**, que mira los tokens de texto en claro y
  en oscuro. Un `#7689a8` escrito a mano no lo miraba nadie.
- **Entra en la escala tipográfica**: escribía rótulos a 11 px.

Medido después: 0 estilos en línea, 4 tamaños y todos de la escala, un solo
radio —4 px— y una sola familia de letra.

Un detalle donde se separa a propósito: el nombre del producto es un `h1` y no
un `span`. Se ve igual, y quien navega con lector de pantalla necesita que la
página tenga un encabezado; hay un gate que lo comprueba.

Y la regla se pone ahora que el recuento está en cero:
`una_pantalla_no_se_pinta_a_mano` prohíbe un color literal —hexadecimal, `rgb`
o `hsl`— en `paginas/` y `componentes/`. Fuera del recorrido quedan, con su
motivo, el color por objeto de `lib/navegacion.ts` —en Lightning una cuenta es
malva y un candidato naranja: eso es producto— y `embebido/`, el widget que se
inyecta en la página de otro, donde los tokens de esta aplicación no existen.

#### Nadie teclea un identificador a mano

Un campo que apunta a otro registro **se elige, no se teclea**: nadie se sabe un
UUID de memoria, así que una caja con `01a0cfbd-62b6-7a9b-…` dentro se queda
vacía o se rellena copiando de otra pantalla — y una copia mal hecha apunta a
otro registro sin avisar a nadie.

El formulario resuelve tres casos y el cuarto lo declara el modelo:

1. **El objeto declarado**: `cuenta_id` busca el recurso cuyo `objeto` es
   `cuenta` y ofrece su listado. Por eso importa declarar `objeto` en
   `modulos.ts`, aunque el recurso no tenga ficha.
2. **Las personas**: `owner_id`, `responsable_id`, `dueno_id`… no se llaman
   `usuario_id`, así que van en una lista corta de presentación.
3. **Las autorreferencias**: el `padre_id` de una campaña es otra campaña.
4. **Lo que no se adivina**, que lo dice la columna:
   `info={"referencia": "contacto"}` viaja al contrato y el front lo obedece.
   `origen_id` y `destino_id` del mapa de personas apuntan a contactos y
   `anotada_por_id` a un usuario: sin declararlo eran tres UUID a la vista.

Y lo que **pone el sistema y no una persona** no va en el formulario:
`fusionado_en_id`, `duplicado_de_id`, los identificadores del gestor documental
y de la firma, la etapa —que se mueve con su acción, que valida los criterios de
salida—, la aprobación y el modelo de una predicción. Van en la lista de
campos no editables de `crmcore.http.listados`.

Hay un gate (`test_ningun_formulario_pide_un_identificador_a_mano`) y empezó
señalando 84 campos.

#### Los campos con una lista cerrada salen como desplegable

Si el servicio valida un campo contra cinco valores, el formulario tiene que
ofrecer esos cinco. Se declara en la propia columna —`info={"opciones":
RELACIONES}`— y `montar_ficha` lo convierte en una lista cerrada en el contrato,
que el front pinta como desplegable.

Sin esto se editaba escribiéndolo a mano, y quien lo rellenaba tenía que saberse
los valores de memoria y escribirlos sin erratas: 118 campos del sistema estaban
así, validados contra una lista cerrada y ofrecidos como texto libre.

#### Qué se pinta como panel de una ficha

La ficha deriva sus paneles de la superficie, y para eso la superficie dice
ahora dos cosas más de cada operación:

- **`devuelve_lista`**: solo lo que devuelve muchos es una sub-colección. Lo que
  devuelve un objeto es una vista, y como panel salía con «Nada todavía» para
  siempre.
- **`exige_datos`**: si hace falta contestar algo por la URL, no es un panel.
  «A quién puedo contactar» exige la finalidad y el canal; «la ruta del
  técnico», el día. Pedidas sin eso responden 422, y eso en la ficha salía como
  un panel que **siempre** da error, no como una pregunta sin contestar.

Obligatorio es «sin valor por defecto», y Pydantic lo marca con su propio
centinela, no con `...`: comprobándolo mal, la primera versión de esto decía que
no había ninguna operación que exigiera datos.

Cuidado al declarar una ruta de este tipo: si devuelve un resumen en vez de una
lista, la ficha deja de enseñarla. Los papeles de un proveedor devolvían tres
montones y cuatro números, así que el panel desaparecía; ahora llevan también la
lista documento a documento, con un modelo de salida declarado —el tipo de
salida es lo que mira la superficie para saber si son muchos—.

#### El armazón de las tablas

`componentes/Rejilla.tsx`. El recuadro, la cabecera y el cuerpo de una tabla,
en un sitio. Estaba copiado **cinco veces** —la tabla genérica y cuatro
pantallas con tabla propia— y ya había empezado a separarse: dos usaban
`text-2xs` y dos `text-xs`, y las celdas tenían tonos distintos sin que nadie lo
hubiera decidido.

**Y volvió a pasar.** Medido el 03-11-2026 quedaban **tres `<table>` escritas
a mano** fuera del armazón, con tres tamaños distintos para lo mismo: la tabla
de resultados analíticos en `text-dato`, las líneas de un formulario en
`text-titulo` y la de un listado con el token de densidad —que es el único que
responde al modo cómodo—. Las tres con la cabecera en texto normal, no en las
versalitas de Lightning.

Las líneas de un formulario no cabían porque llevan un pie con las sumas, así
que `Rejilla` tiene **pie**: una tabla con totales es un caso común y sin él
cada sitio que lo necesite se vuelve a escribir entero. La tercera era la
vista de tabla de una gráfica —la alternativa para quien no puede leer el
dibujo—, que salía con otro aspecto que las demás.

Lo vigila `una_tabla_se_pinta_con_el_armazon`: ninguna `<table>` en
`paginas/` ni `componentes/`, con una sola excepción declarada —el propio
`Rejilla.tsx`—.

No sustituye a `Tabla`: `Tabla` sirve para lo que llega de la API sin estructura
conocida —elige columnas, las esconde, las recuerda— y `Rejilla` es para las
tablas de forma fija, donde eso no aporta nada y lo único que hay que compartir
es el aspecto. `Tabla` se apoya en `Rejilla`, así que una mejora del aspecto
llega a las cinco a la vez.

#### Qué objetos admiten adjuntos, comentarios y documentos

Lo declara cada servicio al montar su router (`crear_router_adjuntos({...})`) y
el gateway lo enruta por el tipo de objeto. **Y ahora lo publica la superficie**,
en `objetos`, porque no se puede deducir de la lista de operaciones: esas rutas
son `/adjuntos/{objeto}` y aparecen una sola vez, con el objeto sin resolver.

Sin publicarlo, la ficha pedía las tres para **cualquier** registro y recibía
404 en 81 de 85: tres peticiones fallidas por ficha abierta y tres pestañas que
no podían funcionar. Ahora la ficha solo ofrece las que ese objeto tiene.

Al medirlo salió el otro lado del problema: solo seis objetos admitían adjuntos,
y **un caso no era uno de ellos** — un caso de soporte sin poder colgar la foto
de la pieza rota obliga a mandarla por correo aparte, y entonces la mitad de lo
que lo explica no está en el caso. Se han abierto donde hacen falta: casos y
órdenes de trabajo, presupuestos, pedidos y contratos. De 6, 5 y 4 objetos a 11,
10 y 9.

#### La sesión del navegador

El navegador no guarda el token: lo lleva en una cookie `HttpOnly` que pone y
quita el gateway (`/sesion/entrar`, `/sesion/renovar`, `/sesion/salir`). Una
integración sigue usando `/auth/login` y recibiendo sus tokens en el cuerpo, que
es lo correcto para un servicio y lo peor posible para un navegador.

**Una cookie caducada no tumba la petición: la deja anónima.** La diferencia con
la cabecera `Authorization` es quién la manda. La cabecera la pone quien llama,
para esa llamada, así que un token caducado ahí es un error de quien llama y se
le dice. La cookie la arrastra el navegador solo, también cuando lo que se está
pidiendo es **volver a entrar**.

Tumbándola pasaba esto: la idempotencia es una dependencia global y pide el
principal en toda escritura, incluida la de entrar, así que con la sesión
caducada la pantalla de entrada respondía «el token ha caducado» a la contraseña
correcta. La única salida era borrar las cookies a mano — es decir, la sesión
expirada dejaba a la persona encerrada fuera.

Para no perder el motivo, que es lo que le dice al navegador si le toca renovar
o mandar a la pantalla de entrada, el rechazo se anota en la petición y lo
responde el proxy del gateway: cualquier llamada a la API con una sesión
expirada sigue devolviendo `auth.token_caducado`. Las rutas con las que se
**consigue** una sesión —las que declara el gateway en `rutas.py`— quedan fuera,
porque volverían a cerrar la puerta.

---

### Lecciones aprendidas por dentro

`services/sales/lecciones.py` (modelo, expediente, señales, firma y patrones) y
`services/sales/api_lecciones.py` (rutas). Tabla `sales.lecciones_oportunidad`,
una fila por oportunidad cerrada.

- **Nace** en `_cerrar` (`servicio.py`) con `al_cerrar`: obligatoria en las
  perdidas. Las cerradas antes se crean con `POST /lecciones/crear-de-las-cerradas`,
  sin obligar; se puede pedir más de una vez.
- **El expediente** se calcula al pedirlo (`GET /opportunities/{id}/expediente`
  o la ficha `GET /lecciones/{id}`). La actividad y los nombres de los decisores
  se piden a party **con la identidad de quien mira** (`ia_ficha.leer`): un
  decisor que esa persona no puede ver sale sin nombre, no con uno inventado. La
  fecha de una actividad es su `inicio_at`, después `fin_at`, `completada_at`,
  `vence_at` y `created_at`: party no guarda «realizada».
- **Al firmar** (`POST /lecciones/{id}/firmar`) el expediente se guarda en
  `hechos` y la ficha enseña ése desde entonces. La firma queda en la cadena de
  auditoría y emite `opportunity.lesson.signed`.
- **La propuesta de la IA** (`POST /lecciones/{id}/proponer`) usa la plantilla
  `leccion_oportunidad` de intelligence con el expediente como contexto, y no
  firma nada. Exige `ia:usar`.
- **Patrones** (`GET /lecciones/patrones`): desgloses planos que el front dibuja
  como cualquier medida de un módulo —ver «El front oficial»—.
- **Ajustes**: los `lecciones_*`, en Admin › Ajustes (ver abajo).
- **Datos de demostración**: `scripts/sembrar_configuracion.py --parte
  lecciones`. Firma 42 con textos que empiezan por «Demostración:».

**Consejos, avisos y resumen** (`services/sales/consejos.py`):

- `GET /opportunities/{id}/consejos`: las firmadas del mismo cliente y las
  parecidas, preguntadas a `POST /ia/indice/buscar` con `fuentes=["leccion"]`
  y la identidad de quien mira; cada candidata se recarga por
  `lecciones.leccion()`, que pasa la política de su oportunidad.
  `POST …/consejos/ia` usa la plantilla `consejos_lecciones` y descarta lo que
  no cite una lección dada.
- **El índice**: la lección se manda al firmar (`consejos.indexar`, como quien
  firma; hace falta `ia:usar`). No va por evento a propósito: el texto es
  interno y un evento lo dejaría en el bus y en los webhooks. Si no llega, la
  firma vale igual y `POST /lecciones/indexar` lo recoge.
- **Avisos** (`avisar_en`): desde `crear_oportunidad_nueva`, `cambiar_etapa`
  (si la etapa no es terminal) y `presupuestos.enviar`. Sólo consultas a la
  base, dentro de la transacción; tabla `avisos_leccion`, única por
  oportunidad, momento y clave. Emiten `opportunity.lesson.advice`, que
  identity notifica al `owner_id`.
- **Resumen**: tarea `sales.resumen_lecciones` en el relevo de sales, cada
  `lecciones_resumen_revisar_s` (3.600 s); genera sólo si el último es de hace
  `lecciones_resumen_dias` o más. Destinatarios: los superiores de la
  jerarquía replicada (`mando_replicado`) de quien tiene lecciones, o ellos
  mismos si no hay jerarquía. Emite `opportunity.lessons.summary`.
- Lecciones y avisos llevan clave ajena **en cascada** a `oportunidades`: son
  parte de la oportunidad, y sin ella la protección de integridad impedía
  borrar cualquier oportunidad cerrada.
- Los umbrales (`lecciones_*`) son `ClaveAjuste`: se cambian en Admin ›
  Ajustes por empresa. `lecciones.umbrales()` los lee una vez por expediente.

En el front es el módulo `lecciones` (`recursos.ts`, con las pestañas Avisos y
Resúmenes), su ficha a medida en `/m/lecciones/leccion/:id`
(`paginas/Leccion.tsx`) y el panel `componentes/ConsejosDeLecciones.tsx` en la
ficha de la oportunidad abierta.

### El front oficial

React, Vite, TypeScript y Tailwind, **el mismo sistema de diseño que contecmind**
y las demás soluciones de la casa: los mismos tokens de color (`paper`, `ink`,
`accent`), las mismas clases de componente (`card`, `pill`, `badge`, `btn-*`) y
los mismos iconos (Material Symbols, servidos desde el paquete npm, sin llamar a
Google). Los tokens viven en `frontend/src/index.css` y se redefinen enteros bajo
`.dark`, así que el tema oscuro no es un puñado de excepciones sino la misma
interfaz con otros valores.

El armazón son tres piezas y están en `frontend/src/componentes/`:

| Pieza | Qué resuelve |
|---|---|
| `BarraLateral` | Navegación agrupada y plegable. Los módulos salen de `lib/modulos.ts`, que es la declaración de cobertura del catálogo, no una lista aparte. |
| `BarraSuperior` | Dónde estás (miga de pan), buscar, tema y menú de usuario. |
| `Paleta` | Ir a cualquier pantalla escribiendo su nombre (`⌘K` / `Ctrl+K`). |

#### Lo que pesa abrir la aplicación

Hay dos presupuestos y vigilan cosas distintas, los dos en
`tests/unit/test_front_oficial.py`:

- **La apertura** (118 kB comprimidos): lo que el navegador descarga antes de
  pintar nada. Hoy son **88,3**.
- **El conjunto** (190 kB): la suma de todos los trozos, contando lo que se
  carga al abrir cada pantalla. Existe para que partir el paquete no sea la
  forma de esconder el crecimiento — basta con diferir lo que engorda para que
  el primer tope no se entere. Hoy son **184,8**.

El bulto de la apertura era **el diccionario de idioma entero**, que viaja ahí
porque hace falta para pintar la pantalla de acceso. Está partido: las
diecisiete secciones que sólo usan pantallas diferidas viven en
`i18n/es.pantallas.ts` y cada `lazy` **espera ese trozo antes de resolver su
componente**. En paralelo habría una ventana de milisegundos con la clave de
traducción escrita en la cabecera, que es el aspecto que tiene una interfaz
rota.

Cuáles se mueven no se eligió a ojo: se midió fichero a fichero qué sección usa
cada pantalla, y las compartidas o del marco se quedan. Si una llegara tarde se
vería la clave en crudo.

**Y partir el diccionario no baja el total, lo sube**: 184,2 → 184,8 kB, porque
un trozo de 5,5 kB comprime peor suelto que dentro del grande. Conviene saberlo
antes de intentarlo otra vez.

El árbol de navegación está en `lib/navegacion.ts` y lo leen las tres: una sola
lista, porque tres que tienen que coincidir acaban no coincidiendo y la que se
queda corta es siempre la del buscador.

Toda pantalla pone su título con `CabeceraPagina`, que es la que pinta el `<h1>`.
Hay gate que lo comprueba —y que comprueba que ninguna pantalla ponga dos.

#### Lo que una ficha ofrece sobre su registro

Dos fallos de la misma clase, los dos reportados mirando una ficha de **plan de
cuenta**: *«¿para qué sale llamada, nota, reunión y correo aquí?»*.

**Se ofrecían sobre los 52 tipos de registro que declara el front.** El campo
`objeto` de una actividad es polimórfico —puede colgar de una cuenta, un caso o
de un objeto propio del tenant— y el servidor no rechaza nada, así que la ficha
los enseñaba en todas partes: «Llamada» sobre un calendario laboral, «Correo»
sobre una entrada de papelera. Ofrecer lo que no tiene sentido no es un detalle
estético: **hace dudar de lo que sí lo tiene**.

La pregunta ya estaba contestada tres veces —`OBJETOS_ADJUNTO`,
`OBJETOS_COMENTARIO`, `OBJETOS_DOCUMENTO`, publicadas en `objetos` de la
superficie—, así que la cuarta va al mismo sitio: `OBJETOS_ACTIVIDAD`. La regla
que la separa de un gusto: **una actividad registra una interacción con una
persona**, así que va contra aquello de lo que se habla con alguien y no contra
la configuración del sistema. Quedan **13** de 52, y quien no está tiene su
motivo escrito al lado de la lista, para que el siguiente no lo añada por
simetría.

Dos matices que importan:

- **El API sigue admitiendo otros.** El modelo dice que una actividad puede
  colgar de un objeto propio del tenant, y cerrarlo rompería eso. La lista es lo
  que **el producto ofrece**, no lo que la base acepta.
- **Mientras la superficie no ha llegado, no se ofrecen** — al revés que las
  pestañas del menú. Es la regla de la casa para las acciones: un botón que
  aparece por defecto y luego resulta que no tocaba es un botón que alguien ya
  ha pulsado.

**Y la ficha abría el registro equivocado.** Reportado abriendo una fila de
«Estado financiero»: *«dice que no existe»*. La ficha resuelve qué pestaña abre
una fila **por su `objeto`**, y cuatro módulos tenían dos pestañas declarando el
mismo: gana la primera, y la segunda pide el id de su registro contra la ruta
del otro.

| Módulo | Las dos que se pisaban | Lo que pasaba |
|---|---|---|
| Cuentas | «Planes de cuenta» y «Estado financiero» | el id de un estado financiero contra `/planes-cuenta/{id}` |
| Procesos | «Canales de entrada» e «Interacciones por canal» | una interacción no es un canal |
| Procesos | «Registros recibidos» y «Ejecuciones programadas» | ni siquiera tiene ficha |
| Explotación | «Tablas del almacén» y «Fuentes federadas» | tipos distintos del mismo almacén |

Las cuatro segundas habían tomado prestado el `objeto` del recurso padre. La
forma de arreglarlo es **no declararlo**: sin `objeto`, se deriva de la ruta que
lista —que es única— y la ficha resuelve su ruta de detalle con el contrato
(`fichaDe`), que busca el `GET {base}/{id}` de verdad. Declarar un nombre nuevo
sería una segunda lista que mantener.

El `objeto` de `abre: {…}` es otra cosa y ahí repetirlo es lo correcto: dice a
qué registro lleva una fila —un documento que vence abre a **su proveedor**—.

Gates: `frontend/src/pruebas/solo_donde_hay_alguien_al_otro_lado.test.tsx` y una
prueba más en `ninguna_opcion_repetida.test.ts`, las dos validadas plantando el
caso malo.

#### Qué enseña el menú: tres estados, no dos

Lo que se ofrece en la barra, en las pestañas de un módulo y en la paleta no
sale de una lista escrita en el front: sale de `GET /api/v1/superficie`, que es
donde el servidor publica **qué permiso exige cada operación**. La alternativa
era declarar el permiso de los ciento doce recursos en `recursos.ts`, o sea una
segunda lista de permisos que se separaría de la del servidor en cuanto alguien
cambiara uno, sin que nada lo avisara.

Esa superficie la **agrega el gateway** preguntando a los diez servicios, y
cuando uno no contesta lo dice: devuelve `completa: false` y nombra a los
callados en `servicios_sin_contestar`. El front declaraba los dos campos en su
tipo y **no los leía nadie**.

Esto se decidía con un solo conjunto de rutas y la regla «si está vacío, no se
esconde nada», que mezcla tres situaciones distintas:

| Estado | Qué hace el menú | Por qué |
|---|---|---|
| La superficie no ha llegado | No esconde nada | Esconder por defecto haría que el menú apareciera a trozos al cargar, y un menú que se mueve mientras lo miras es peor que uno con una entrada de más durante medio segundo |
| Ha llegado entera | Manda ella: lo que no está, no se enseña | Es lo que evita ofrecer lo que va a contestar 403 |
| Ha llegado **incompleta** | No esconde lo del servicio que calló | De lo suyo no se sabe nada: no es que no te toque, es que no se ha podido preguntar |

El segundo y el tercero se vivían como el mismo conjunto vacío. Un servicio que
tardara en arrancar aportaba cero operaciones, así que **todas sus pestañas se
escondían con el mismo gesto con el que se esconde lo prohibido** — y como la
superficie se pide una vez al entrar, el menú se quedaba mal para toda la
sesión. Así se reportó: «vas a cuentas y contactos y luego a proveedores y
aparecen más cosas en esa pantalla de menú».

El estado vive en `lib/permisos.tsx` (`useVisibilidad`) y lo consumen las tres
pantallas que pintan menú —`BarraLateral`, `Modulo` y `Paleta`— a través de
`recursoVisible`, para que las tres contesten lo mismo: encontrar por búsqueda
lo que el menú esconde hace que el sistema parezca contradecirse.

Para saber de quién es cada pestaña, el resumen generado `lib/visibilidad.ts`
lleva ahora también el servicio (`s`). Sale de `recursos.ts` por
`scripts/gen-visibilidad.mjs` y hay gate de frescura: dos listas a mano acaban
diciendo cosas distintas y entonces no se sabe cuál manda.

Gate: `frontend/src/pruebas/el_menu_no_cambia_solo.test.tsx`. Validado plantando
la lógica anterior — cuatro de sus cinco pruebas se ponen rojas.

#### Un error en una pantalla no se queda puesto en las demás

La frontera de error (`componentes/Frontera.tsx`) va **dentro del marco**: lo
que se cae es el contenido, así que el menú y la barra siguen ahí y el usuario
puede irse a otro sitio. Y sabe olvidarse del error al cambiar de ruta,
comparando su `clave`.

Lo que fallaba el 29-10-2026 era quién se la pasaba: `App` le daba
`window.location.pathname`, que **no es reactivo**. `App` es la raíz y no se
suscribe a la navegación, así que no se volvía a pintar al navegar y la clave se
quedaba congelada en la pantalla donde se rompió. Y se realimenta solo: mientras
la frontera enseña el error, las rutas de dentro están desmontadas, así que
tampoco queda nadie escuchando la navegación. El aviso se quedaba puesto en
**todas** las pantallas hasta recargar a mano.

Lo arregla `FronteraDeRuta`, un envoltorio que llama a `useLocation` por encima
de la frontera, que es el único sitio donde se puede: hace falta que algo que no
esté dentro del árbol caído sí escuche la ruta.

Gate: `frontend/src/pruebas/el_error_no_se_queda_pegado.test.tsx`, validado
plantando la clave no reactiva.


**Piezas comunes que cambiaron el 05-11-2026**, y que valen para todas las
pantallas:

- **Elegir es un desplegable.** En `componentes/Formulario.tsx`, `Referencia`
  (un registro de otro recurso) es un campo cerrado con el nombre de lo elegido,
  una capa con buscador al abrir, teclado (flechas, Intro, Escape) y una × para
  quitarlo si no es obligatorio. `Opciones` (lista múltiple) es lo mismo con
  casillas dentro. Antes eran una lista siempre abierta y un muro de casillas.
  Las opciones se leen con `rotuloDeOpcion` («Descuento tardío», y las siglas
  como vienen). Lo vigila `pruebas/elegir_es_un_desplegable.test.tsx`.
- **Las medidas de un módulo dibujan sus desgloses.** `Medidas` (en
  `paginas/Modulo.tsx`) pinta como barras horizontales, con `Grafica`, cualquier
  campo `{categoría: número}` de una ruta de `resumen`. Antes se descartaban sin
  avisar. Para que una medida nueva salga dibujada basta con devolverla plana.
- **`Grafica` mide su sitio** (`ResizeObserver`) en vez de dibujar a 640 de
  ancho fijo: en una tarjeta de 460 px todo se escalaba al 72 % y la letra
  de 12 px se veía de 8,6. En las barras horizontales cada **fila entera** es
  la zona de puntería —y se recorre con el teclado—; la capa de franjas
  verticales de las columnas no se pinta ahí, porque tapaba a las filas.
- **`escalar`** separa las listas con «, » y escribe los códigos `snake_case`
  como texto; una palabra suelta no se toca, porque puede ser un nombre.
- **`nombreDelRegistro`** prefiere `nombre_completo` a `nombre`.
- **Las listas cerradas viajan en el contrato** (`crmcore/http/opciones.py`).
  Cada servicio publica en `components.x-opciones` los valores de las columnas
  que declaran `info={"opciones": …}` y los estados de sus máquinas de estado;
  `contratoDe` los registra y `escalar` escribe «Abierta» en vez de
  «abierta» sólo cuando el contrato dice que es una opción de ese campo. Para
  que un estado nuevo salga legible basta con declarar su lista en la columna.
- **Estados configurables** (`crmcore/datos/estados.py`). La configuración
  de cada empresa vive en el ajuste `maquinas_de_estado` (por objeto) y
  `maquina_efectiva(objeto, db)` la construye y valida contra la de fábrica
  (`construir`). El código pregunta con `con_significado(objeto, "abierto",
  db)` y `significa(...)`, nunca con el nombre de un estado. Cada servicio
  publica las suyas en `GET/PUT/DELETE /api/v1/{servicio}/estados/{objeto}`
  (`crmcore/http/estados_router.py`), y `POST {registro}/estado` mueve un
  registro a cualquier estado permitido, salvo los que tienen su camino
  (ganar, perder, convertir, descartar). La oportunidad devuelve
  `estado_significa`, `estado_nombre` y `estado_color`; la pantalla pinta
  `<campo>_nombre` cuando viene. En el front: `paginas/Estados.tsx` y
  `componentes/CambioDeEstado.tsx`, que `DatosClave` pinta en la cabecera.
- **Poner un estado por su significado**: `estado_de(objeto, significado,
  db)` devuelve el estado al que llevar un registro (el de fábrica si sigue
  activo; si no, el primero activo con ese significado). `presentar(maquina,
  estado)` da `estado_significa`, `estado_nombre` y `estado_color` para la
  respuesta. Máquina del caso en `services/service/estados.py` (significado
  `en_pausa` para el reloj; `terminales(db)` para resueltos y cerrados);
  `servicio.cambiar_estado` desvía a `cerrar_caso`/`reabrir_caso` cuando entra
  o sale de un «cerrado». `POST /casos/{id}/estado` existe para la cabecera de
  la ficha, igual que el `PUT`.
- **Máquina de la actividad** en `services/party/estados.py`, con `vivas(db)`
  y `cerradas(db)`. `POST /activities/{id}/estado` desvía a completar cuando
  el destino significa «completada». El modelo expone `estado_significa`,
  `estado_nombre` y `estado_color` como propiedades (sesión del objeto). Un
  rollup cuyo filtro depende de la empresa usa `Rollup.filtro_de(db)` en vez
  de `filtro`, que se construye al importar.
- **Motor de procesos, despertar** (`services/orchestrator/motor.py`):
  `avanzar` llama a `_despertar` cuando la instancia está en `esperando`
  (espera → `siguiente`; subproceso → mira la última hija por `padre_id`;
  evento → `si_caduca` o falla). `esperando_humano` no pasa por aquí: lo
  reanuda `responder_tarea`. Tareas: `_le_toca(tarea, principal)` en
  `api.py` decide responder y delegar.
- **Programadas por registro** (`services/automation/planificador.py:_repartir`,
  `registros_programados.py`): una programada con condiciones pide los
  registros de su objetivo a la colección que publica cada servicio en
  `GET /{servicio}/filtros` (`colecciones`), con la identidad de quien la
  activó, y encola una ejecución por registro que cumple (`origen
  programada_registro`, clave `<clave de la hora>:<id>`). Tope
  `automatizacion_programada_max_registros`. Operadores `hace_mas_de_horas` y
  `hace_menos_de_horas` en `services/orchestrator/motor.py`.
- **Presupuesto y contrato** (`services/sales/estados.py`): máquinas con
  `_CON_SU_CAMINO` en `servicio.py` para lo que tiene acción; entre dos
  estados del mismo significado no se exige el camino. Rutas `POST
  /presupuestos/{id}/estado` y `POST /contratos/{id}/estado`.
- **Aprobación de presupuestos**: `quote.approval.needed` (con
  `solicitante_id`) → `services/orchestrator/aprobacion_de_presupuestos.py`
  abre la solicitud con `aprobaciones.crear` y las etapas del ajuste
  `aprobacion_presupuesto_etapas`; si no resuelve aprobadores (cualquier
  `CrmError`) emite `approval.decided` con `estado: sin_aprobadores`.
  `services/sales/consumidores.py:consumir_aprobacion` aplica la decisión sólo
  si el presupuesto sigue en un estado que significa `en_aprobacion`. En la
  pila local de procesos no hay NATS: los eventos no cruzan de servicio.
- **Metodologías** (`services/sales/cadencias.py`): `metodologia_de` elige
  la del embudo de la oportunidad (o la general), `criterios_de` normaliza las
  dos formas en que se han escrito los criterios (`etiqueta`/`peso` y
  `pregunta`/`nombre` sin peso, que reparte por igual), `responder` marca
  criterios y recalcula. Rutas: `GET /opportunities/{id}/metodologia` y
  `PUT /metodologias/{id}/oportunidad/{oid}`. Los playbooks se buscan por la
  etapa normalizada (clave o nombre). Pantalla: `paginas/Metodologias.tsx`.
- **Segregación de funciones** (`services/identity/sod.py`,
  `api_sod.py`, prefijo `/segregacion`). Además de reglas, excepciones y
  violaciones: `GET /matriz` cruza cada regla activa con los permisos de cada
  rol (celda `a`, `b` o `ambos`, con los comodines expandidos) y cuenta las
  personas en conflicto; `POST /simular` (`usuario_id`, `roles`) devuelve las
  reglas que pasaría a incumplir **sin** guardar nada; `POST /reglas/de-serie`
  (`role:write`) carga `REGLAS_DE_SERIE` sin pisar las que ya existen — siete
  conflictos típicos escritos con permisos que exigen rutas reales (la prueba
  `test_sod.py` lo comprueba buscándolos en el código). Detecta, no bloquea:
  ninguna asignación de rol consulta estas reglas. Pantalla:
  `paginas/Segregacion.tsx`; `Seguridad.tsx` sólo enseña el recuento y enlaza.
- **Clasificación TCSEC** (`services/tenancy/tcsec.py`, `api_tcsec.py`,
  prefijo `/tcsec`, CRM-07.03.02.11). `REQUISITOS` declara cada requisito
  con su nivel y, si se mide, su comprobación (`Contexto` → `(estado,
  detalle, datos)`); las que leen de otros servicios usan
  `crmcore.http.interno.invocar` con la identidad de quien evalúa y guardan
  la respuesta en el contexto (el informe de cumplimiento de cada servicio
  sirve para la cadena y para las etiquetas). Los parámetros van en
  `parametros`, nunca pegados a la ruta: la ruta decide el servicio. Los
  ajustes se leen con `_ajuste`, que cae a `Settings` si la clave no es
  editable. Los requisitos sin comprobación se atestiguan como evaluación del
  control `TCSEC-<clave>` del GRC (se crea la primera vez, marco «TCSEC»,
  frecuencia anual). Rutas: `GET /tcsec/evaluacion`, `PUT
  /tcsec/requisitos/{clave}/atestacion` (`tenant:write`) y `GET
  /tcsec/informe` (`{fichero, contenido}` en Markdown). Ajuste:
  `tcsec_mfa_minima_pct`. Pantalla: `paginas/Tcsec.tsx`.
- **Etapas del embudo**: `PATCH /pipelines/{id}/etapas/{etapa}`,
  `PUT /pipelines/{id}/etapas/orden` y `DELETE …/etapas/{etapa}?mover_a=`,
  con `_exigir_cierres` (una final ganada y una perdida). Pantalla:
  `paginas/Embudos.tsx`.
- **Un objeto con máquina de estados no ofrece `estado` en su formulario de
  edición**: se mueve con sus acciones, que validan la transición. El estado de
  un caso, que no tiene máquina, se valida contra `ESTADOS_CASO`.
- **Insignias de dato**: además de `chip-dato--si` y `chip-dato--no` (que
  tacha: significa «no»), `chip-dato--aviso` y `chip-dato--mal` para lo que pide
  atención y lo que es malo de por sí.
- Los rótulos de los campos que son referencias pierden el «ID»: «Contacto», no
  «Contacto ID».

## 2. Cómo se despliega

### 2.1 Requisitos

- **Python 3.12**, **PostgreSQL 15 o superior** y **Redis**. Para el bus, NATS
  JetStream o Redis Streams (se elige por configuración, sin reconstruir imagen).
- Docker y Docker Compose para el camino recomendado.
- Node solo si se va a construir el front oficial.

### 2.2 Desarrollo, en una máquina

```bash
./setup.sh                      # venv, dependencias y .env a partir del ejemplo
docker compose --profile app up -d
python scripts/migrar.py --todos
python scripts/aplicar_rls.py --todos
python scripts/sembrar_demo.py  # datos de ejemplo, opcional
```

El `.env` manda. Se genera desde `.env.example`, que a su vez **se genera desde
los Settings reales**: no hay ajustes documentados que no existan ni ajustes que
existan sin documentar, y hay un gate que lo comprueba.

#### Sembrar una empresa con volumen

`sembrar_demo.py` crea cuatro cuentas: sirve para comprobar que el sistema
funciona, no para enseñarlo —esa es toda su función, y por eso sigue siendo
corto—. Sin volumen no se ve nada de lo que hace un CRM —ni
un embudo, ni una previsión, ni una cola de casos, ni un aviso de vencimiento—,
y para eso está `sembrar_empresa.py`:

```bash
python scripts/sembrar_empresa.py --slug acme --nombre "Acme, S.A." \
    --email direccion@acme.example --contrasena "…" --escala 60 --anios 10
```

`--escala` es el número de cuentas y `--anios` cuánta historia se siembra hacia
atrás —diez por defecto—; el resto de volúmenes se derivan de los dos, con un
reparto que imita el de una empresa real: tres contactos por cuenta, cuatro
actividades al año, dos oportunidades y dos casos y medio por cuenta y año. Los
datos se componen de piezas y se combinan con un generador **sembrado a partir
del slug**, así que la misma empresa da siempre los mismos datos y dos empresas
dan datos distintos.

**Por qué los años importan.** Hasta el 27-10-2026 todo se creaba hoy: las
actividades entre −90 y +45 días, los casos en los últimos 120 y las
oportunidades en ±210. Con eso no se puede enseñar ni una evolución anual, ni
un ciclo medio de venta, ni una comparación con el año pasado —y son tres de las
pantallas que más se miran—. Ahora cada fecha se reparte sobre el periodo
entero, con más peso en los años recientes porque un negocio crece, menos en
agosto porque un negocio no factura igual en agosto, y **nunca antes de aquello
de lo que cuelga**: un contacto no nace antes que su cuenta ni un caso antes que
su cliente. El eje de tiempo y las piezas que no tenía ningún sembrador —el
catálogo de productos, las campañas y el parque instalado— están en
`scripts/datos_demo.py`, que `sembrar_empresa.py` consume: un solo generador,
porque dos catálogos de empresas se separan a la primera corrección.

A escala 60 y diez años salen, medidos: 60 cuentas, 180 contactos, 2.400
actividades, 600 oportunidades con su historial de etapas, 600 ofertas —219 de
ellas pasaron por aprobación por descuento—, 160 pedidos, 1.500 casos con su
reloj de SLA, 120 máquinas instaladas, 500 órdenes de trabajo y 44 campañas
bajo 11 programas anuales. Tarda **50 segundos**.

#### Qué queda vacío después de sembrar, y por qué

Medido el 27-10-2026 sobre una empresa sembrada entera con los dos guiones:
de **452 tablas, 134 con datos**. Las 318 vacías no son 318 huecos —la mayoría
sólo existen cuando pasa algo: excepciones de calidad, bloqueos legales,
fusiones, migraciones de aislamiento— y una tabla vacía porque no ha pasado
nada no es un hueco.

El número que importa es otro: **cuántas de las vacías las lista alguna
pantalla**, porque ésas alguien las abre y las ve en blanco. Eran 25 y quedan
**9**, y las nueve por un motivo que se puede decir:

| Qué | Por qué sigue vacío |
|---|---|
| conversaciones, mensajes, notificaciones, anomalías | No se dan de alta: los produce el sistema cuando pasa algo. Sembrarlos a mano sería escribir en la tabla lo que el producto tendría que haber escrito, y entonces la demostración enseña el resultado sin el camino. |
| passkeys, dispositivos de confianza | Son de una persona y de su navegador. No hay forma de crearlos desde fuera, y eso es la protección funcionando. |
| claves de API, proveedores de identidad | El alta exige volver a verificar la identidad, y SAML está apagado en esta instalación. Salen en el informe como «rechazadas por diseño». |
| créditos de servicio | Se calculan —y el sembrado los calcula—: salen cero porque ningún contrato de esta empresa los pacta. Cero es la respuesta correcta. |

#### Comprobar lo sembrado

```bash
python scripts/sembrar_empresa.py --slug acme --tenant <uuid> --comprobar
```

Recorre lo escrito y dice si se sostiene: 21 comprobaciones repartidas por
servicio —`party` no puede mirar lo de `sales`, que es el aislamiento
funcionando— y **cada una dice cuántas filas recorrió**. Eso último no es
decoración: una consulta que no encuentra nada porque la tabla está vacía da
cero fallos y parece verde, y el recorrido fue lo que delató, tres veces, que
faltaban datos. Devuelve código 1 si algo falla.

Seis incoherencias se cazaron así, y ninguna se veía en pantalla: un contacto
nacido antes que su cuenta —uno entre 145, por el ajuste de agosto—; actividades
apuntadas en el futuro; el 76 % de los casos incumpliendo el SLA porque las
horas se sorteaban sueltas en vez de medirse contra el plazo de cada tier; dos
etapas del embudo vacías por fijar la profundidad del recorrido a tres;
310 oportunidades con dos ofertas y 235 ganadas sin pedido, porque las ofertas
se ataban a la oportunidad **por nombre** y los nombres se repiten; y los cortes
de idempotencia sin filtrar por tenant, que al sembrar la segunda empresa
encontraban las filas de la primera, decían «ya hay» y se iban sin crear nada.

Con la pila en Docker hay que ejecutarlo **por partes, una por servicio**, porque
el rol de `sales` no tiene permisos sobre el esquema de `party` —el aislamiento
funcionando— y porque las partes se pasan los identificadores de cuenta por un
fichero:

```bash
docker compose exec tenancy python scripts/sembrar_empresa.py --parte tenant --slug acme …
# imprime TENANT=<uuid>; se pasa con --tenant al resto
docker compose exec identity python scripts/sembrar_empresa.py --parte usuarios --tenant <uuid> …
docker compose exec party    python scripts/sembrar_empresa.py --parte party    --tenant <uuid> --enlaces /tmp/acme.json …
docker compose cp contecrm-dev-party-1:/tmp/acme.json .   # y copiarlo a sales y service
docker compose exec sales    python scripts/sembrar_empresa.py --parte sales    --tenant <uuid> --enlaces /tmp/acme.json …
docker compose exec service  python scripts/sembrar_empresa.py --parte service  --tenant <uuid> --enlaces /tmp/acme.json …
docker compose exec marketing python scripts/sembrar_empresa.py --parte marketing --tenant <uuid> …
```

Además de la plantilla de usuarios con roles distintos, siembra unidades de
negocio, un pipeline de siete etapas con **el historial de por dónde pasó cada
oportunidad** —sin él no hay tasa de conversión, ni ciclo medio de venta, ni
informe de dónde se atasca la venta—, el catálogo de productos y una oferta por
oportunidad con sus líneas, la aprobación por descuento cuando el producto la
exige, el pedido de las que se ganaron, una taxonomía de casos de dos niveles,
un SLA por tier de cliente, el parque instalado del cliente con sus órdenes de
trabajo asignadas a técnicos, y los programas y campañas de cada año con su
presupuesto y su consumo.

Las proporciones no son decorativas y se eligieron porque lo contrario no se
puede enseñar: se **pierde más de lo que se gana** —una demostración con el 90 %
ganado deja de creerse en cuanto alguien la mira—, el 15 % de los casos incumple
el plazo —una cola sin incumplimientos no enseña para qué sirve el SLA, y una
con el 76 % no se parece a ningún servicio—, y unas campañas se pasan del
presupuesto y otras no llegan, porque si todas gastaran lo presupuestado la
pantalla de consumo no tendría nada que decir.

El camino que se recorre es el **de verdad**: las ofertas pasan por `crear`,
`enviar` y `aceptar`, que es quien calcula los precios con el motor, decide si
el descuento necesita aprobación y numera el pedido. Insertando filas a mano
saldrían ofertas con precios que la aplicación nunca daría, y la demostración
enseñaría números que el producto no produce.

Se niega a ejecutarse con `ENV` de producción.

### 2.3 Un solo servidor

Para instalaciones pequeñas, todos los servicios en la misma máquina con
`docker compose`, un Postgres gestionado o local y un Redis. Lo que hay que
cambiar respecto de desarrollo:

- `APP_ENV=production` — activa las comprobaciones de arranque, que **se niegan a
  arrancar** con configuración insegura (sin `ENCRYPTION_KEY`, con almacenamiento
  local, con `DB_SSLMODE=prefer`). Es deliberado: una instalación insegura que
  arranca es la que se queda así.
- `SECRET_KEY` y `ENCRYPTION_KEY` propias, nunca las del ejemplo.
- Copias de seguridad configuradas **antes** de la primera carga de datos.

### 2.4 Distribuido

Cada servicio escala por separado. Lo que hay que tener en cuenta:

- **El gateway es el único que habla HTTP con los demás.** Los servicios no se
  llaman entre sí.
- **El bus necesita persistencia.** Con Redis Streams, `appendonly yes`; con NATS,
  almacenamiento de fichero en el stream.
- **Las tareas de fondo** (worker de trabajos, proyecciones, webhooks) son procesos
  aparte del mismo código: `servicio <nombre> --worker`.
- **Las migraciones se aplican una vez por servicio** y no en el arranque de cada
  réplica: `scripts/migrar.py <servicio>` en un paso previo.

### 2.5 Actualizar

1. Copia de seguridad y comprobación de que se puede restaurar (no vale una copia
   que nadie ha restaurado nunca).
2. `scripts/migrar.py --todos` y `scripts/aplicar_rls.py --todos --comprobar`.
3. Despliegue de servicios. Las migraciones están escritas para ser compatibles
   hacia atrás una versión: se puede desplegar el esquema antes que el código.
4. `scripts/preflight.py --todo` en un entorno igual al de producción antes de
   tocar producción.

---

## 3. Configuración

### 3.1 De dónde sale cada ajuste

Tres capas, de menos a más prioritaria:

1. **Valor por defecto del código**, pensado para que funcione sin tocar nada.
2. **`.env` / variables de entorno**, que es lo que decide en el despliegue.
3. **Ajustes en caliente por tenant** (`runtime_settings`), editables desde
   administración, con historial de versiones y con quién lo cambió.

La referencia completa, ajuste por ajuste, está en
[la referencia de ajustes](manual-6-referencia-ajustes.md), **generada desde el
código**. Aquí van solo los que más se tocan y qué pasa si te equivocas.

### 3.2 Los que importan

| Ajuste | Qué hace | Si lo tocas mal |
| --- | --- | --- |
| `SECRET_KEY` | Firma los tokens | Cambiarla cierra todas las sesiones. Compartirla entre entornos permite entrar en producción con un token de pruebas |
| `ENCRYPTION_KEY` | Cifra los campos sensibles | Sin ella no se pueden ni escribir. Perderla es perder esos datos: no hay puerta de atrás |
| `DATABASE_URL` / `DATABASE_ADMIN_URL` | Conexión de aplicación y de migración | La de aplicación **no** debe poder saltarse RLS. Usar la de admin para servir peticiones anula el aislamiento |
| `BUS_BACKEND` | `nats` o `redis` | Cambiarlo en caliente deja mensajes en el backend viejo: se drena antes |
| `RATE_LIMIT_*` | Topes por usuario, clave, tenant e IP | Demasiado bajo bloquea integraciones legítimas; demasiado alto deja que un tenant afecte a los demás |
| `SLO_*` | Objetivos de latencia y disponibilidad | Solo afecta a lo que se mide y a lo que se avisa, no al comportamiento |
| `GRPC_ACTIVO` | Levanta el puerto gRPC | Requiere `requirements-grpc.txt`. Apagado por defecto: una superficie abierta que nadie usa es una que nadie mira |
| `CORS_ORIGINS` | Quién puede llamar desde un navegador | Con un solo origen, atas la API a una interfaz concreta |
| `STORAGE_BACKEND` | Dónde van los adjuntos | `local` en producción hace que cada réplica vea solo los suyos |

### 3.2.1 El `.env`, y los temporales de tu editor

El `.env` lleva los secretos reales del despliegue y **no se versiona**: lo que se
versiona es `.env.example`, que documenta cada clave con valores de ejemplo.

Lo que casi nadie vigila es el fichero de al lado. Editar el `.env` con `vim` deja
un `.env.swp` en la misma carpeta, y ese fichero **lleva dentro el contenido del
buffer**. Aquí pasó: el 02-10-2026 se subió uno a un commit. Lo que expuso fue la
mitad de arriba del fichero —comentarios, puertos locales, el nombre de la
máquina— y ningún secreto, pero el mecanismo es el mismo que habría expuesto la
clave de firma si el fichero hubiera sido más grande o el swap más tardío.

Dos reglas para quien edita la configuración de un despliegue:

- **Ignora los temporales del editor**, no solo el `.env`. En este repositorio
  están en `.gitignore` desde entonces (`*.swp`, `*.swo`, `*~`); si copias el
  esquema a otro sitio, cópialo entero.
- **Si un secreto llega a un repositorio, no basta con borrarlo del commit
  siguiente**: sigue en la historia. Lo que de verdad lo cierra es **rotar la
  clave**, y por eso `SECRET_KEY` y `ENCRYPTION_KEY` admiten rotación sin
  reiniciar el servicio.

### 3.2.2 Acceso contextual y reautenticación

Dos ajustes que gobiernan quién entra y cuándo se le vuelve a pedir el factor:

| Ajuste | Qué hace | Si lo tocas mal |
| --- | --- | --- |
| `reglas_contextuales` | Desde qué redes, países, dispositivos y franja horaria se puede entrar. Es por tenant y en caliente | Una lista **vacía** dentro de una regla significa «no se comprueba esa señal», no «ninguno vale». Y si no hay localizador de IP configurado, la señal del país **no se mide** y la respuesta lo dice: darla por buena haría que la señal más útil no saltara nunca |
| `stepup_validez_minutos` | Cuánto vale el segundo factor antes de volver a pedirlo para una operación delicada | Demasiado alto convierte el step-up en decorativo: una sesión de ocho horas valdría para exportar la base entera a las seis de la tarde con el factor de las nueve |

Las operaciones que lo exigen son una **tabla de datos**, no condiciones
repartidas por el código: exportación masiva, cambio de permisos, borrado en
bloque, suplantación, credenciales de máquina, cambio de MFA, restauración y baja
del tenant. Se consultan por API, y lo que no está en la tabla no se protege — así
que añadir una operación nueva es añadirla ahí.

Una consecuencia operativa: **al superar el factor se entrega un token nuevo**. Si
tu integración guarda el token y no lo refresca al verificarse, seguirá recibiendo
«vuelve a verificarte» después de haberse verificado.

### 3.2.3 Lo que cada servicio replica, y de qué evento

Ningún servicio lee el esquema de otro — es el aislamiento funcionando—, así que
lo que necesita de fuera lo tiene **replicado**: los ajustes en caliente, la clave
del tenant, la jerarquía de mando y el **mapa de territorios**.

Esa última llegó a estar a medias y conviene conocer la forma, porque es la misma
para todas: hay un productor que emite (`territory.published` desde `sales`), un
consumidor por servicio que aplica, y una tabla local contra la que se resuelve la
visibilidad. Si falta cualquiera de las tres piezas **no hay error**: la vía
simplemente devuelve el conjunto vacío y nadie ve nada por ella.

Dos cosas que hay que respetar al tocar esto:

- **El evento tiene que llevar con qué replicar.** El de territorios llevaba la
  clave y la versión, y con eso no se puede: ni el identificador, ni de quién
  cuelga, ni quién lo trabaja. Lo que un consumidor necesita va en el contrato
  del evento (`declarar_consumo`), y el gate de contratos lo comprueba.
- **Se aplica el mapa entero, no las altas.** Replicar solo lo que se añade deja a
  quien sale de un territorio viendo su cartera para siempre.
- **El servicio que publica escribe su propia copia en la misma transacción**, no
  consumiendo su propio evento. Un servicio que se manda un mensaje para enterarse
  de lo que acaba de hacer añade un viaje por el bus, una ventana en la que su
  propia pantalla contesta con el mapa viejo, y la posibilidad de que el mapa quede
  publicado y la copia no — son dos transacciones distintas. El recorrido que
  aplica el mapa es **uno solo** (`crmcore.authz.jerarquia.aplicar_mapa`), usado por
  el que publica y por el que recibe: dos copias de ese recorrido es cómo acaban
  dos servicios resolviendo el acceso de forma distinta.

### 3.2.4 De dónde sale «hoy»

Para quien escriba código nuevo. Hay una regla y tiene guardián.

**El día de hoy se recibe, no se busca.** Veintidós funciones del producto llevan
un parámetro `hoy`, y eso es una decisión, no un descuido: una función que mira el
reloj por dentro no se puede probar sin mover el reloj de la máquina, y entonces
lo que se prueba es el reloj. Con `hoy` recibido, una prueba fija el día y
comprueba el cálculo.

Las dos mitades de esa regla:

- **Al calcular**: recibe `hoy: date` **obligatorio** y no llames a
  `date.today()` ni caigas al reloj si no viene (`hoy or _hoy()` era el día de
  UTC con otro aspecto; desde el 10-11-2026 ninguna función pura lo hace).
- **Al llamar**: pásale `fechas.hoy(db)`. Eso es el día **donde está el cliente**,
  no donde está el servidor.

Por qué importa el segundo punto: entre las 00:00 y las 02:00 en España, la fecha
en UTC es la del día anterior. Un «últimos siete días» calculado con el reloj de
la máquina se come el último día, y nadie lo nota salvo quien echa de menos un
registro. Ya costó veinticinco sitios en una revisión, y al escribir el guardián
quedaban tres más.

**Lo que el guardián no deja pasar** (`test_el_reloj_no_se_mira_a_escondidas.py`):

- `date.today()` y `datetime.utcnow()` en `services/` o en el núcleo. La única
  excepción es `crmcore/fechas.py`, que es quien resuelve la hora del tenant.
- Una función que reciba `hoy` y aun así mire el reloj por dentro: en el caso en
  que no se lo pasan sigue siendo imposible de fijar desde fuera.
- Que este apartado desaparezca del manual.

**Instantes, no textos.** Para comparar fechas, compáralas como `datetime`, nunca
sus `isoformat()`: dos instantes iguales escritos con husos distintos se ordenan
por el carácter y no por el momento. `…T21:00:00+02:00` parece mayor que
`…T20:00:00Z` y es dos horas anterior. Lo tenía la validación de «no puede estar
en el pasado», que es el campo que existe justamente para eso.

Y una fecha sin huso se interpreta **en UTC**, no en la hora de la máquina: dónde
esté el servidor no puede decidir si un dato se acepta.

### 3.3 Ajustes por tenant

Lo que cambia por cliente y no por despliegue: umbrales de calidad, plazos de
reapertura de casos, política de descuentos, frescura de los datos, pesos de la
salud de cuenta, formatos y moneda. Todo ello **con historial**: se puede ver qué
valor había en una fecha y quién lo cambió, que es lo que permite explicar por qué
un cálculo de hace tres meses dio otro número.

### 3.3.1 Historial de ajustes, jerarquía de empresas y consumo a facturación (CRM-00.01.04.02, CRM-00.01.03.07, CRM-00.01.06.07)

**Historial de ajustes.** `rt.fijar` anota cada cambio en `versiones_ajuste`
(`crmcore/runtime/versiones.py`) con el valor de antes y el de después. Rutas en
`services/tenancy/api.py`, todas sobre el tenant de quien llama:

| Ruta | Permiso | Qué hace |
| --- | --- | --- |
| `GET /api/v1/ajustes/versiones?clave=&limite=` | `tenant:read` | historial y lista de claves con cambios |
| `GET /api/v1/ajustes/versiones/diferencias?desde=&hasta=` | `tenant:read` | qué cambió entre dos momentos, colapsado por clave |
| `GET /api/v1/ajustes/versiones/comparar?a=&b=` | `tenant:read` | diferencias entrada a entrada entre dos versiones de la misma clave y ámbito |
| `POST /api/v1/ajustes/versiones/{id}/volver` | `tenant:write` | vuelve al valor de antes de ese cambio |

Volver pasa por `fijar` (se replica como cualquier cambio) con
`tipo_version="vuelta_atras"`, así que deja **un** apunte —antes dejaba dos— y
la auditoría `ajuste.vuelta_atras`. Si el valor de antes era `None` (el ámbito
no tenía valor propio) se llama a `rt.quitar` y el ámbito vuelve a heredar.
Pantalla: `/historial-de-ajustes` (Entornos y despliegue).

**Jerarquía de empresas.** Columnas nuevas en `tenants` (migración
`20261109_1600_jerarquia_y_consumo_a_facturacion`): `relacion_padre`
(`matriz_filial`, `franquicia`, `holding`), `comparte_con_padre` (`consumo`,
`indicadores`), `comparte_actualizado_at/por`. Lógica en
`services/tenancy/jerarquia.py`, rutas en `api_jerarquia.py`:

| Ruta | Quién | Qué hace |
| --- | --- | --- |
| `GET /api/v1/tenants/{id}/jerarquia` | la propia o la plataforma | árbol: su línea hacia arriba y sus descendientes (sin hermanas); la plataforma, desde la raíz |
| `PUT /api/v1/tenants/{id}/jerarquia` | plataforma | colgar de otra con su relación; rechaza ciclos; cambiar de padre borra lo compartido |
| `PUT /api/v1/tenants/{id}/jerarquia/comparticion` | **sólo la propia** (`tenant:write`) | qué deja ver a su matriz |
| `GET /api/v1/tenants/{id}/jerarquia/agregado` | la propia o la plataforma | lo compartido por cada descendiente y los totales |

El agregado no lee filas de otra empresa: a cada hija que lo ha autorizado se le
pregunta por HTTP firmado con su identidad —el consumo en `/estado/consumo` de
cada módulo, los indicadores en las rutas del ajuste `jerarquia_indicadores`
(`{nombre, ruta, campo, permiso, roles}`, sólo el permiso y los roles que pide
cada uno)— y se queda sólo con el número. A la que no comparte no se le pregunta.
La firma lleva una identidad de lectura fija (`identidad_de_lectura()`, un
UUIDv5): sin usuario la firma es anónima y cada módulo contesta 401 —medido el
09-11-2026, el corte periódico y el agregado salían con los trece módulos sin
leer—. Los totales del embudo de serie piden el rol `admin` porque un agregado
del importe exige verlo en claro (sin rol, 403 `proyeccion.campo_no_usable`).

**Consumo a facturación.** `services/tenancy/facturacion.py`, tabla
`cortes_consumo`. Un corte compone el consumo del tenant preguntando a cada
servicio de `RUTAS_SERVICIOS` (salvo el gateway); el que no contesta va a
`no_leidos` y el corte queda `completo=false`. Formato neutro, columnas
`periodo, tenant, modulo, metrica, cantidad, unidad, tope` (tope vacío = sin
límite). Se envía como un webhook de la casa: `cliente_seguro` (guard de SSRF),
firma HMAC (`crmcore.security.firma`), cabecera `x-crm-corte` para deduplicar y
las cabeceras de `facturacion_destino_cabeceras`.

| Ruta | Permiso | Qué hace |
| --- | --- | --- |
| `GET /api/v1/facturacion/destino` | `tenant:read` | si hay destino (sólo la máquina), formato, si es periódico |
| `GET /api/v1/facturacion/cortes` | `tenant:read` | cortes con su estado de envío |
| `POST /api/v1/facturacion/cortes` `{enviar}` | `tenant:write` | toma el corte ahora y, si se pide, lo manda |
| `GET /api/v1/facturacion/cortes/{id}/exportar?formato=csv\|json` | `tenant:read` | fichero y contenido |
| `POST /api/v1/facturacion/cortes/{id}/enviar` | `tenant:write` | manda o reenvía |

Estados: `abierto` (periodo en curso, lo rehace la tarea), `pendiente`,
`enviado` (con el código), `fallido` (con el porqué e intentos), `sin_destino`.
La tarea `tenancy.consumo_a_facturacion` (cada `TAREA_FACTURACION_INTERVALO_S`)
recorre los tenants activos: si `facturacion_exportar_periodicamente` está
encendido, rehace el corte del periodo en curso y manda los de periodos cerrados
hasta `facturacion_max_intentos`. El corte de un mes es el último tomado dentro
de él: lo que puede faltar del final es, como mucho, un intervalo de la tarea.
Ajustes: `facturacion_destino_url`, `facturacion_destino_cabeceras` (sensibles),
`facturacion_formato_envio` (`json`/`csv`), `facturacion_max_intentos`,
`jerarquia_indicadores`. Pantallas: `/grupo-de-empresas` y
`/consumo-a-facturacion` (Usuarios y empresa).

### 3.4 Vocabularios de negocio

Un ajuste es un número o un interruptor. Un **vocabulario** es una lista de
valores con los que el cliente cuenta su trabajo: los motivos de pérdida, los de
descarte. No son estados de protocolo —esos siguen siendo constantes, y deben
serlo— sino categorías de negocio, y por eso las decide cada empresa.

    from crmcore import vocabulario

    vocabulario.registrar("motivos_perdida", MOTIVOS_PERDIDA,
                          etiqueta="Motivos de pérdida")
    ...
    if motivo not in vocabulario.valores(uow.db, "motivos_perdida"):
        raise ErrorValidacion(...)

Cómo está montado y por qué:

- **La tabla `valores_vocabulario` es común a los trece esquemas**, como
  `ajustes_runtime`. Cada servicio guarda el suyo en el suyo porque lo valida en
  mitad de una operación, y los servicios no se llaman entre sí: hacerlo aquí
  ataría el cierre de una oportunidad a que otro proceso esté vivo.
- **Las constantes del código son los valores de fábrica, no un techo.**
  Mientras el tenant no toque nada valen esas; en cuanto añade o cambia uno, la
  lista es suya entera. Sin esa caída, una instalación nueva no podría cerrar
  una oportunidad hasta que alguien poblara la tabla.
- **Al primer cambio se materializan.** Añadir un valor copia antes los de
  fábrica a la tabla. Sin ese paso la lista quedaría con **uno solo** —el recién
  creado—, porque tener algo guardado es lo que apaga los defectos; es el fallo
  clásico de este patrón y se nota tarde, cuando ya se ha perdido el resto.
- **Se retira, no se borra.** El código de un valor lo llevan escrito los
  registros que lo usan, así que solo se puede cambiar su rótulo, su orden y si
  sigue en uso.

Las rutas las monta `crear_servicio` en `/{servicio}/vocabularios`, y solo si el
servicio declara alguno. Un servicio que no valide contra ninguna lista no gana
ni una ruta.

Para declarar uno nuevo: llamar a `vocabulario.registrar()` al importar el
módulo que lo usa —no en el arranque, para que el que valida sea el mismo que se
registra— y validar con `vocabulario.valores()`. No hace falta migración: la
tabla ya está en todos los esquemas.

### 3.5 Integridad al borrar

`crmcore.datos.integridad` se niega a borrar lo que otros registros usan, y el
borrado genérico de `montar_ficha` lo consulta antes de mandar nada a la
papelera.

Cómo sabe qué depende de qué, y por qué de dos formas:

- **La clave ajena declarada**, cuando las dos tablas viven en el mismo esquema.
- **La columna `<objeto>_id`**, que es el caso normal. Los servicios tienen
  esquemas separados, así que una oportunidad apunta a su cuenta con un
  `cuenta_id` suelto y no puede haber `FOREIGN KEY` entre ellas. Mirando solo
  las claves ajenas, la protección habría cubierto cinco relaciones de todo el
  producto. El nombre del objeto sale del registro de la papelera, donde cada
  ficha declara el suyo al montarse.

Y qué **no** cuenta como dependencia:

- Lo que tiene `ON DELETE CASCADE`, porque eso es composición y no referencia:
  las líneas de una oferta son parte de la oferta, y bloquear por ellas sería no
  dejar borrar ninguna oferta.
- Lo que está en la papelera. Si bloqueara, un registro quedaría preso para
  siempre de algo que ya nadie ve y que nadie va a ir a purgar.

Cuando bloquea responde **409 `integridad.referenciado`** diciendo qué tabla,
por qué campo y cuántos. «No se puede borrar» a secas obliga a adivinar, y quien
adivina va borrando las dependencias una a una hasta que le deja — que es el
borrado en cascada, hecho a mano y sin enterarse.

La salida es **archivar**: `POST {ficha}/archivar`, que monta `montar_ficha`
cuando el modelo tiene `activo`, `activa` o `estado`. Deja de ofrecerse de aquí
en adelante y no toca lo que ya pasó.

**Qué ofrece el PATCH genérico, y qué no** (05-11-2026). `montar_ficha` saca
los campos editables del modelo, menos tres familias:

- las de `NO_EDITABLES`: identidad, tenant, fechas de alta y baja y, desde esta
  fecha, **la auditoría** —`created_by`, `updated_by`, `created_origen`,
  `updated_origen`—, que el PATCH de diez fichas dejaba reescribir;
- las columnas marcadas `info={"calculado": True}`, que pone el sistema y no
  una persona (en la oportunidad: `etapa_desde`, `ultima_actividad_at`,
  `lead_id`). Un campo calculado nuevo se marca donde se declara;
- cualquier `*_hash`: un resumen criptográfico no se teclea.

Y **si el recurso ya tiene su PATCH o su DELETE escrito a mano, el genérico no
se registra.** Antes se registraban los dos: FastAPI atendía con el primero —el
escrito a mano, con su bloqueo y su política—, pero el contrato publicaba el
último, así que el formulario de edición ofrecía 22 campos de la oportunidad y
el servidor guardaba 10. Medido en la oportunidad, que era la única así.

**Medido y pendiente**: unos setenta campos más que mantiene el sistema siguen
saliendo editables en los PATCH genéricos —el `total` de pedidos y
presupuestos, los vencimientos de SLA de un caso, `ultima_ejecucion_at`…—.
Clasificarlos pide mirar quién escribe cada uno; los que lo escribe una persona
(`vence_at`, `inicio_at`) tienen que seguir siendo editables.

**Dónde aparece el borrado.** `montar_ficha` registra el borrado cuando el
modelo tiene borrado lógico, así que la regla «donde se puede editar se puede
borrar» se cumple dando papelera al modelo, no escribiendo rutas. Se hizo de
golpe: 67 modelos que la ficha dejaba editar y no borrar pasaron a tenerla, y
quedan **ocho** sin borrado, cada uno por un motivo:

| Qué | Por qué no se borra |
| --- | --- |
| Tenant | Se suspende. Borrar una empresa entera no es una operación de pantalla |
| Tarea humana, solicitud de aprobación | Se completan o se rechazan; borrarlas pierde la decisión y por qué se pidió |
| Conflicto de sincronización | Se resuelve eligiendo un lado |
| Evento fallido, archivo de eventos | Son el registro de lo que pasó; se reintentan o se descartan |
| Excepción de calidad | Se cierra diciendo qué se hizo. Borrarla vacía la cola sin arreglar el dato |
| Bloqueo legal | Se levanta, con quién y cuándo. Un bloqueo que se puede borrar no bloquea |
| Interacción, predicción, salud de cuenta | Son lo ocurrido o un cálculo derivado, no algo que alguien mantenga |

### 3.5.1 Quien opera la plataforma, y de quién son los datos que ve

La sesión de base de datos se ata **al tenant de la petición**, y eso es lo que
hace que el aislamiento no dependa de que nadie se despiste. Hasta el
27-10-2026 había una excepción que no estaba escrita en ninguna parte: para una
cuenta con `es_admin_plataforma` la sesión se abría con `sistema=True` —sin
filtro— en **todas** las peticiones, no sólo en las de la consola de
plataforma. El efecto medido sobre la instalación local: abriendo «Cuentas»,
97 de 100 filas eran de otro cliente; en contactos y oportunidades, 100 de 100,
de hasta ocho clientes mezclados y sin nada que lo dijera.

No lo cazaba ninguna prueba: las de aislamiento usan `es_admin_plataforma=False`
en todos sus casos, que es justo el que no tenía el problema. Lo destapó el
sembrado, al pedir las cuentas, recibir las de otro cliente y oír del servidor
—con razón— que esa cuenta no existe.

**Ahora lo decide la ruta, no quién la pide.** Cruzan tenants las operaciones
que declaran `exige_plataforma` —dar de alta un tenant, el panel de
aislamiento, la operación—, que es para lo que existen. Las de negocio, no.

**Y mirar los datos de un cliente se pide.** La cabecera
`X-CRM-Tenant-Mirado` dice cuál, y el servidor sólo la atiende si quien la
manda opera la plataforma: mandarla siendo otro no concede nada. Un valor
ilegible **no** se interpreta como «todos» — cae al tenant propio, porque lo
contrario convertiría una cabecera mal escrita en la vista global de la que se
viene. En la interfaz es un selector en la barra, con la elección guardada en
la pestaña del navegador: recargar la mantiene y cerrarla la olvida, que es lo
correcto para algo que da acceso a datos de otro. Mientras se mira a otro, el
selector va en color de aviso: es un estado del que hay que acordarse de salir.

### 3.6 El portal, y la sesión de quien entra desde fuera

El portal se diseñó **headless**: la API sirve datos para que cada cliente monte
el suyo con su marca. Eso sigue valiendo, y las rutas de administración —dar
acceso, revocarlo, emitir el enlace— las llama un empleado con su sesión.

Lo que faltaba era que **el cliente pudiera entrar él**. Todas las rutas del
portal exigían un principal del CRM y recibían el `acceso_id` por la URL, así
que quien quisiera un portal de verdad tenía que montar un intermediario que
guardase credenciales de empleado para servir a sus clientes. Eso no es un
portal: es una credencial de empleado compartida por internet.

`crmcore.http.portal_deps` añade la sesión del portal:

- **El token no lleva permisos ni roles.** Es lo que impide que sirva para el
  CRM, porque todas sus rutas exigen uno: la puerta se cierra sola en vez de
  depender de que nadie monte una ruta sin `exige_permiso`.
- **Lleva el acceso, no el contacto.** Qué se ve lo decide el nivel del acceso,
  resuelto en el servidor.
- **Un token de empleado no vale** como sesión de portal. Parece inofensivo
  —tiene más permisos, no menos— pero saltaría el filtro por nivel, que es lo
  único que decide qué ve cada contacto.
- **La cookie es otra**: en el mismo navegador puede haber las dos, un comercial
  mirando el portal de su cliente, y compartir nombre haría que una pisara a la
  otra.
- **Dura una hora** y se renueva pidiendo otro enlace. Un portal se usa a ratos,
  y un token largo en el navegador de un cliente acaba en un correo reenviado.

El canje del enlace corre con `sesion(sistema=True)` y busca por el hash **entre
todos los tenants**: quien entra todavía no tiene tenant, y pedirle además de
qué empresa es convierte el portal en un formulario con dos campos, uno de los
cuales el cliente no tiene por qué saber. Lo que acota no es el tenant, es el
secreto — el mismo patrón que el refresco de sesión del CRM.

**El chat del portal no es un chat aparte.** Lo que el cliente escribe entra por
la misma conversación omnicanal que su correo, así que aparece en la consola de
agente sin que nadie vigile una bandeja nueva, y si la conversación estaba
cerrada se reabre. Un chat de portal que solo se ve en el portal es un chat que
nadie contesta. El historial se sirve con `incluir_internos=False`, explícito y
no deducido del permiso, para que una nota interna no acabe delante del cliente
el día que alguien reutilice la función desde un sitio nuevo.

**El proveedor también entra.** La empresa del contacto va firmada en el token
(`cuenta`), y eso es lo que permite que `party` sirva lo suyo —sus papeles, sus
homologaciones, el renovado que sube él— sin preguntarle a `service` de qué
cuenta es este acceso: los servicios no se llaman entre sí. Aceptar la cuenta de
quien llama dejaría a un proveedor mirar los papeles de otro, que es la fuga más
fácil de un portal; comprobado, responde 403.

Existe porque perseguir certificados caducados es trabajo de alguien todos los
meses y el único que puede resolverlo es el proveedor: enseñárselo a él convierte
una lista de reclamaciones en algo que se arregla solo.

Ojo con el orden: las rutas `/mi/...` se declaran **antes** que las de
`/{cuenta_id}/...`, o la de parámetro se las traga y responde 403 por falta de
permiso — que despista, porque el problema no es el permiso. Hay un gate que lo
comprueba (`test_orden_de_rutas`).

Y un acceso de nivel `cuenta` o `admin` **sin cuenta se rechaza al crearlo**: el
filtro es por cuenta y sin ella el portal entra bien y sale vacío, que se lee
como «no tengo casos» y no como «el acceso está mal dado». La cuenta la pone
quien crea el acceso porque el contacto vive en otro servicio.

### 3.6.1 El cuadro incrustado fuera, y en nombre de quién se ejecuta

Mismo problema que el portal y misma forma de resolverlo, así que conviene
leerlos seguidos. La ruta del embebido exigía **sesión del CRM**, de modo que un
cuadro no se podía incrustar en la aplicación de un cliente sin repartir
credenciales de empleado entre sus usuarios. Y lo que devolvía era el
identificador del cuadro: los datos los pedía después quien miraba, con sus
propios permisos, así que el `actua_como` del enlace no acotaba nada.

**Dos puertas, porque el secreto no puede llegar al navegador.**

1. `POST /api/v1/cuadros-mando/embebidos/abrir` — la llama el **servidor** de la
   aplicación anfitriona con el secreto del enlace, y recibe un ticket corto. Se
   resuelve con `sesion(sistema=True)` y busca el enlace por el hash de su
   secreto **sin tenant**: quien incrusta el cuadro no sabe de qué organización
   es —averiguarlo es justo lo que está pidiendo—, igual que el canje del enlace
   de portal y que la validación de una clave de API.
2. `GET /api/v1/cuadros-mando/embebido` y
   `POST /api/v1/cuadros-mando/embebido/datos` — las llama la página incrustada
   con el ticket en `Authorization: Bearer`. El tenant lo fija el mecanismo de
   siempre, así que estas rutas no montan uno paralelo.

**El ticket**, como el del portal y por lo mismo:

- **No lleva permisos.** Sin ellos no pasa ninguna ruta del CRM, y la puerta se
  cierra sola en vez de depender de que nadie monte una ruta sin `exige_permiso`.
- **Los roles van bajo `alcance_roles`, no bajo `roles`.** En `roles` los
  recogería el principal del CRM y este ticket influiría en cualquier ruta que
  acote por rol. Solo los lee la dependencia del embebido.
- **Un token de empleado no vale.** Con él, el embebido se ejecutaría con el
  alcance de quien lo trajera, que es exactamente el agujero que esto cierra.
- **Dura lo que diga el enlace** (`minutos_validez`), y se renueva pidiendo otro
  desde el servidor del anfitrión.

**De dónde sale el alcance.** `analytics` no puede leer la tabla de usuarios —los
permisos de Postgres se lo impiden— así que lo pregunta:
`GET /interno/usuarios/{tenant_id}/{usuario_id}/alcance` en `identity`, detrás de
la firma interna y fuera del contrato público. Devuelve roles y permisos como un
**dato, nunca un token**: con una credencial, quien pregunta podría hacer mucho
más que ejecutar un informe acotado, y viajaría por la red interna. Hay la
variante `.../por-correo/{correo}/alcance` porque el sujeto que afirma el
anfitrión es un correo: el identificador que esa persona tiene aquí no lo conoce.

**El SSO del anfitrión se federa, no se cree.** El campo `sujeto` dice *quién*
mira; *qué puede ver* se resuelve aquí contra las membresías. Y con qué alcance
se calcula el cuadro es una decisión **declarada** en el enlace (`modo_alcance`),
no un valor por omisión escondido: `enlace` lo calcula con el de quien lo montó
—el tope que el enlace ya prometía— y `quien_mira` con el de esa persona, y
entonces sin sujeto no se sirve.

### 3.6.2 El esquema del tenant, aplicado de verdad

Replicar el esquema sirve para validar. Lo que hace falta además es **el esquema
físico**, y hasta el 05-10-2026 no lo aplicaba nadie: un campo a medida
declarado por un cliente se guardaba y se validaba, y no recibía ni índice ni
vista.

- **Sin índice**, filtrar u ordenar por ese campo recorre la tabla entera. Eso no
  da un error: da una pantalla que tarda un poco más cada mes, hasta que alguien
  dice que «el CRM va lento» y nadie sabe por dónde empezar.
- **Sin vista**, la vista tipada del tenant —`v_oportunidad_01a0cd88…`— no
  existe, mientras el motor de informes la nombra como entidad de respaldo
  cuando no hay fuente externa registrada. Ese camino moría con «Table with name
  v_oportunidad_… does not exist».

Se aplica al publicar el esquema, en el servicio **dueño de la tabla**: el
evento llega a los catorce y sólo uno puede crear ese índice. Lo resuelve un
registro objeto → tabla que apuntan solos los montadores de listado y de ficha;
un recurso con su listado escrito a mano lo declara al lado del router.

Un fallo aquí **no tumba la réplica**: validar con los campos nuevos es lo
urgente —el consultor tiene al cliente delante— y un índice que no se pudo crear
se reintenta en la publicación siguiente. Lo que no se hace es callarlo.

### 3.6.3 El móvil sin conexión

`POST /api/v1/<servicio>/movil/sincronizar`. Va por servicio, como la papelera:
la cola del móvil lleva operaciones sobre objetos de varios, y cada uno las
resuelve contra sus propios registros.

**Devuelve el plan, no escribe.** Qué se puede aplicar, qué choca y con qué
campos, y qué se queda esperando. Quien escribe es la ruta de siempre de cada
objeto, con sus permisos y sus validaciones: una segunda puerta de escritura sin
las comprobaciones de la primera es como se cuela un dato que la pantalla no
habría dejado poner.

Lo que el móvil tiene que mandar, y por qué:

| Campo | Para qué |
|---|---|
| `id_cliente` | Lo genera **el móvil** antes de mandar nada. Es lo que hace que un reintento tras un corte no cree una visita duplicada: si lo generara el servidor, habría que adivinar si la petición que no contestó llegó, y esa duda no tiene respuesta correcta |
| `version_base` | Sobre qué versión se hizo el cambio. La **cero es una versión** —la del registro que nadie ha tocado— y tratarla como «sin versión» rechazaba toda actualización sobre un registro recién creado |
| `campos` | Lo que quiere escribir |
| `campos_base` | Lo que **leyó** antes de perder la señal. Sin esto no se distingue «el otro cambió este campo» de «yo escribo encima de un valor que nadie tocó», y entonces todo cambio sobre un registro que se movió sale como conflicto — que es la forma de enseñar a pulsar «quedarme con lo mío» sin leer |

Un objeto que no es de ese servicio **se queda en la cola** y se dice; un
registro borrado no se recrea, porque recrearlo devolvería a la vida algo que
alguien borró a propósito y sin su historia.

#### Aplicar, y el front sin conexión (09-11-2026)

Con `aplicar: true` la ruta **escribe** lo que no choca y deja los conflictos.
No es una segunda puerta: escribe con `operacion_de_ficha(objeto, "actualizar")`
—la misma función del PATCH de la ficha genérica, con su esquema de campos
editables— y exige el permiso que ese PATCH registró
(`operacion_de_ficha(objeto, "permiso_actualizar")`, apuntado en
`crmcore/http/listados.py`). Cada operación va en su punto de guardado: una que no
valida queda `rechazada` con su motivo sin tirar las demás. Acciones nuevas en
el plan:

| `accion` | Qué significa |
|---|---|
| `aplicada` | Escrita; trae la `version` nueva. Sale de `cola.pendientes` |
| `conflicto` | Trae `campos`, `version_servidor` y `valores_servidor` (lo que hay ahora en esos campos) |
| `aplicar_por_su_ruta` | Una creación, o un objeto con PATCH escrito a mano: el cliente lo repite por esa ruta con `If-Match` = `version_actual` |
| `rechazada` | Sin permiso o no valida; con `porque` |

La operación admite `recurso` (`contacts`) en vez de `objeto`: se traduce con
`objeto_del_recurso`, el mismo registro que usan los informes.

El front (`frontend/src/lib/sinConexion.ts`, `frontend/public/sw.js`):

- **Service worker de red primero** para todo `GET` del mismo origen; guarda
  la aplicación (`crm-app-v1`) y las lecturas JSON de la API
  (`crm-consultado-v1`, clave con `X-CRM-Tenant-Mirado`). No guarda flujos SSE
  ni descargas. En desarrollo guarda también `/@vite/client` y
  `/@react-refresh`: cada módulo los importa y sin ellos la aplicación no
  arranca sin red; con red no cambia nada. Lo servido del caché lleva
  `X-CRM-Sin-Conexion: 1`. Al salir se borra el caché de lecturas.
- Lo que se apunta solo (un «visto») se llama con `encolable: false`: sin red
  se pierde en vez de encolarse como un cambio de la persona.
- Se encola **sólo lo que cambió** frente a la lectura guardada: un formulario
  manda el registro entero, y reenviarlo pisaría lo que otra persona cambió en
  los demás campos. El servidor, igual: escribe sólo lo que el móvil cambió
  frente a `campos_base`.
- Si el envío falla con la red ya de vuelta (la conexión aún no está, o el
  servicio contesta 5xx), se reintenta cada `sinConexionReintentoMs` de
  `config.json` (la variable de entorno SIN_CONEXION_REINTENTO_MS del
  contenedor del front, que lee `entrada.sh`; 15 s por defecto). Un 5xx no es un rechazo: lo pendiente sigue pendiente.
- **La cola** está en IndexedDB (`contecrm-sin-conexion`/`cola`), por usuario.
  `llamar()` encola un `PATCH`/`PUT` a `/api/v1/<recurso>/<uuid>` o un `POST` a
  `/api/v1/<recurso>` cuando `fetch` falla por red, y lanza
  `ErrorApi(0, "encolada_sin_conexion")`. La versión sale del `If-Match` de la
  pantalla o del `ETag` de la lectura guardada; sin ninguna, no se encola.
- **Al volver la red** (`online`, o al entrar) se agrupa por servicio —sale de
  la tabla de recursos del front (`lib/recursos.ts`)— y se llama a esta ruta con `aplicar: true`. Sin
  servicio conocido, o para las altas, se repite la petición por su ruta con
  `Idempotency-Key` = `id_cliente` e `If-Match`; un 409/412 se convierte en
  conflicto leyendo el registro. Resolver un conflicto reenvía lo elegido sobre
  `version_servidor` con `valores_servidor` como base, y ya no choca.
- Pantalla: `/sin-conexion`. Pruebas:
  `tests/unit/test_sincronizar_sin_conexion_aplica.py` (por HTTP) y
  `frontend/src/lib/sinConexion.test.ts`.

En producción `sw.js` debe servirse sin caché larga (va en la raíz, fuera de
`/assets/`).

### 3.6.4 El modo solo lectura

Se aplica en la **unidad de trabajo**, que es por donde pasan todas las
escrituras. Ruta a ruta sería «funciona donde alguien se acordó», y durante un
incidente la que falta es la que escribe.

Se entra y se sale por `POST /api/v1/estado/solo-lectura` **en el gateway**, y
eso es el punto: el modo vive en memoria de cada proceso, así que ponerlo en un
servicio suelto dejaría los otros trece escribiendo. El gateway lo reparte y
dice **a cuáles no ha llegado**: un servicio mudo sigue escribiendo, y eso hay
que saberlo ahora, no después.

La **lectura sigue funcionando**. Es lo que separa «no se puede guardar, tus
datos están ahí» de «el CRM no funciona»: con lectura, el comercial que está
delante de un cliente sigue viendo su ficha.

El **motivo es obligatorio** al entrar, y no es cortesía: sin él quien no puede
guardar cree que su cambio tenía algo malo y lo reintenta cambiándolo, que es
cómo se pierde trabajo durante una incidencia.

### 3.7 La cola de duplicados

`party/cola_duplicados.py`. El que puntúa es
`duplicados.buscar_cuentas_duplicadas`, **el mismo que protege el alta**: dos
formas de decidir si algo es un duplicado acaban discrepando, y entonces el alta
deja pasar lo que la cola marca, o al revés.

Lo que añade es el barrido sobre el maestro y la decisión. El umbral de
propuesta es un ajuste (`duplicados_umbral_propuesta`, 0,72 de fábrica) y es más
bajo que el de bloqueo al crear, a propósito: bloquear un alta y **proponer que
alguien mire** no piden la misma certeza.

Detalles que importan:

- Las parejas se guardan con los identificadores **ordenados** y con
  restricción única, porque si no la misma pareja entra dos veces —una por cada
  lado— y la cola dobla de tamaño con el mismo trabajo dentro.
- Lo decidido no se vuelve a proponer, y lo pendiente se **actualiza** en cada
  barrido, porque la probabilidad cambia cuando cambian las fichas.
- Fusionar exige `superviviente_id`. No se elige solo: la que sobrevive conserva
  el identificador que usan los sistemas de fuera.

Hoy el que puntúa es determinista —similitud de nombre, dominio, NIF—, y ahí
está a propósito: la señal es explicable («ha coincidido el dominio»), que es lo
que permite decidir. Si algún día se quiere un clasificador, el sitio donde
entra es la puntuación, dejando intactos el barrido, la cola y la decisión.

### 3.7.1 Calidad del dato sobre los registros reales (09-11-2026)

Router `services/party/api_calidad_real.py` (prefijo `/calidad-dato`):

| Ruta | Qué hace |
|---|---|
| `GET /golden/reglas/{objeto}`, `PUT`/`DELETE /golden/reglas/{objeto}/{campo}` | Reglas de supervivencia (tabla `reglas_supervivencia`; `*` = por defecto) |
| `GET /golden/candidatas` | Fichas con fusionadas o unidas |
| `POST /golden/{objeto}/{id}/componer` (`aplicar`) · `GET /golden/{objeto}/{id}` | Compone desde linaje, ficha, `fusiones.estado_previo` y uniones; guarda en `golden_records` |
| `GET`/`PUT`/`DELETE /enriquecimiento/perfiles[/{clave}]` | Perfiles sobre el conector (`perfiles_enriquecimiento`) |
| `POST /enriquecimiento/{perfil}/pedir` · `GET /enriquecimiento/propuestas` · `POST .../propuestas/{id}/aplicar|descartar` | Llama a `integraciones/conexiones/{id}/operaciones/{op}/invocar` con `interno.invocar` (tipo usuario); propuestas en `propuestas_enriquecimiento` |
| `POST /identidades/observar`, `/resolver`, `/barrer`, `/unir`, `/deshacer` · `GET /identidades/propuestas` | Identidad entre canales |
| `GET`/`PUT /umbrales-duplicado` | Ajuste `dedupe_umbral_por_objeto` (ámbito tenant) |
| `POST /direcciones/normalizar` (`aplicar`, `objeto`, `objeto_id`) | Barrido de direcciones |

Migración `alembic/versions/party/20261109_1900_calidad_del_dato_real.py`
(`9d2e4c7b1a60`). Dos oyentes `before_flush` sobre `Session`, enganchados al
importar `services.party.modelos`: `identidad._al_guardar` anota las señales
de los contactos nuevos o con correo, teléfono o canales cambiados (y borra
las de un contacto anonimizado), y `direcciones._al_guardar` normaliza la
dirección nueva o corregida. Van en el flush y no en una ruta para cubrir el
alta, el PATCH genérico, la importación y la sincronización sin conexión.
`duplicados.umbral_de(db, objeto, tipo)` resuelve el umbral del objeto y cae al
general. Ajustes nuevos de `party`: `identidad_canales_a_senal`,
`dedupe_umbral_por_objeto`, `direcciones_abreviaturas`,
`direcciones_cp_digitos`, `enriquecimiento_timeout_s`,
`enriquecimiento_max_lote`. Pruebas: `tests/unit/test_calidad_del_dato_real.py`.

### 3.8 La cola de calidad del dato

`stewardship.barrido()` recorre cuentas y contactos y abre una excepción por
cada cosa que esté mal. Existía la cola, la asignación y el cierre, y **ninguna
forma de que entrara nada**: la pantalla salía siempre vacía.

Las reglas no son nuevas: `calidad_faltan` lo escribe el alta y la edición de
cada ficha con los pesos de `normalizacion`, y el formato lo juzgan los mismos
validadores que normalizan al guardar. Un segundo criterio de «esto está bien»
acabaría contradiciendo al primero, con la cola diciendo que falta algo que la
ficha da por bueno.

Es idempotente porque `abrir` no duplica la misma regla sobre el mismo campo de
la misma ficha, así que se puede pasar cada noche. Se lanza con
`POST /calidad-dato/cola/barrido` y el sembrado lo pasa al final, después de
repartir los dueños — antes abriría cientos de «sin propietario» que el propio
sembrado resuelve un paso después.

---

## 4. Integración

### 4.1 API REST

- **OpenAPI generado desde el código**, no mantenido a mano. Cada servicio publica
  el suyo y el gateway el conjunto.
- **Versionado explícito** y política de deprecación publicada, con cabeceras
  `Sunset` y avisos proactivos a los consumidores.
- **Paginación por cursor**, idempotencia por cabecera en las escrituras, ETag y
  peticiones condicionales.
- **Errores en formato Problem Details** (RFC 7807) con un código estable por tipo
  de error — el código es el contrato, el texto puede cambiar.
- **Operaciones masivas** con el camino síncrono acotado y el asíncrono con
  identificador de trabajo, progreso e informe parcial.

### 4.2 GraphQL y BFF

Lectura compuesta en una llamada, con **coste declarado por operación** y tope: una
consulta anidada que traiga medio CRM se rechaza antes de ejecutarse, no después.
Y perfiles BFF (web, móvil, portal, quiosco) para no mandar lo mismo a todos.

### 4.3 gRPC

Opcional (`requirements-grpc.txt`, `GRPC_ACTIVO=true`). Lo que **no** es opcional
es el contrato: el `.proto` se genera desde el metamodelo y los números de campo
se guardan por tenant, porque reutilizar un número mete el valor en el campo
equivocado sin dar ningún error. Un cambio incompatible se rechaza al publicar el
esquema.

La identidad se valida con **el mismo código que HTTP**. Es la decisión más
importante de esa superficie: dos implementaciones de «¿este token vale?» divergen
siempre. Y los cinco métodos del contrato —`Get`, `List`, `Create`, `Update`,
`Watch`— los sirve **el mismo código que sirve REST**: cada llamada se despacha
contra la propia aplicación, así que pasa por la autenticación, los permisos y la
auditoría de siempre.

Dos cosas al encenderlo:

- **Con `GRPC_ACTIVO=true` y sin la librería instalada, el servicio arranca igual
  y lo escribe en el log** (`grpc.activo_sin_libreria`). Apagar el HTTP de todo el
  mundo porque falta una dependencia opcional convierte una instalación incompleta
  en una caída.
- El puerto se cierra **con gracia** al parar (`stop(grace=5)`): cortarlo en seco
  deja a medias la llamada en curso, que es siempre la del cliente que mueve
  millones de filas.

Y cómo viajan los datos, que es lo que hay que saber para integrar:

- **La clase del mensaje se construye por tenant**, desde la copia replicada del
  esquema y con los números que se publicaron — los mismos del `.proto` que se te
  entregó. No se recalculan al servir: recalcularlos daría números distintos según
  el orden de los campos, y un número reutilizado no da error, mete el valor en el
  campo equivocado.
- **Al leer, lo desconocido se descarta** (es protobuf, y es lo que permite que un
  cliente desplegado hace seis meses sobreviva a un campo nuevo). **Al escribir, un
  campo que no existe en el contrato se rechaza** con `rpc.campo_desconocido`: quien
  manda `descuneto` cree que puso un descuento, y lo que recibiría es un «todo bien»
  con la ficha sin él.
- **Un campo que no viene no vuelve a cero.** Los campos opcionales llevan presencia
  explícita; sin ella, un `Update` de dos campos pondría a cero los otros veinte.
- **Lo que el CRM devuelve y el contrato no publica se queda fuera** de la respuesta:
  identificadores internos, marcas de tiempo del sistema y los campos cifrados, que
  no salen por aquí a propósito.
- **`List` y `Watch` van en flujo, un mensaje por registro.** Mandar la página entera
  en uno solo haría que el tope de tamaño de mensaje decidiera cuántos registros
  puede tener un cliente.
- **Un objeto sin contrato publicado en ese tenant contesta
  `rpc.objeto_sin_contrato`**, no un mensaje vacío: un mensaje vacío hace creer al
  que integra que el registro no tiene datos.

### 4.4 Peticiones compuestas

Varias operaciones en una llamada y **en una transacción**, en
`POST /api/v1/<servicio>/compuesto`. Es lo que evita que un cliente móvil haga
tres viajes de red para crear una cuenta con su contacto y su oportunidad — y que
se quede a medias en el segundo.

Lo que hay que saber para integrar:

- **Va por servicio.** Una composición que cruzara servicios no podría ser una
  transacción, y prometerlo sería mentir.
- **Todo o nada.** Si una operación falla se deshacen todas, y la respuesta dice
  **cuál** falló y con qué código.
- **Las referencias van hacia atrás**: `$1.id` usa lo que devolvió la primera. A
  una posterior no se puede, y a sí misma es un ciclo; las dos se rechazan **antes**
  de ejecutar nada.
- Un campo que no vino en el resultado **se deja tal cual** en lugar de poner
  vacío, para que falle la validación del recurso y no se cree la fila con un
  hueco que nadie nota hasta semanas después.
- Hay **tope** de operaciones por llamada; por encima, el camino masivo.

### 4.4.1 Sagas: lo que cruza servicios y hay que poder deshacer

Para el técnico que integra un proceso que toca varios módulos. Base:
`/api/v1/sagas`.

Una transacción no cruza servicios: cada uno tiene su base de datos. Lo que se
hace en su lugar es declarar **antes de empezar** cómo se deshace cada paso, y
compensar hacia atrás cuando uno falla.

| Ruta | Permiso | Para qué |
|---|---|---|
| `GET /api/v1/sagas` | `proceso:read` | Listado, filtrable por `estado` y `clave` |
| `POST /api/v1/sagas` | `proceso:write` | Arrancarla, con **todos** los pasos y su compensación |
| `POST /api/v1/sagas/{id}/hecho` | `proceso:write` | Anotar que el paso `orden` salió bien |
| `POST /api/v1/sagas/{id}/fallo` | `proceso:write` | Anotar el fallo y compensar hacia atrás |
| `GET /api/v1/sagas/{id}` | `proceso:read` | Estado, pasos y lo que quedó sin deshacer |

Lo que hay que saber para integrar:

- **Los pasos se declaran enteros al arrancar.** Descubrirlos sobre la marcha deja
  una saga que no sabe deshacerse: el día que falla el cuarto, nadie sabe qué hay
  que revertir de los tres anteriores.
- **Un paso sin `compensacion` es irreversible**, y se acepta. Lo que no se acepta
  en silencio es que esté en medio: la respuesta trae `irreversibles_antes_del_final`
  y un `aviso`. Colócalo el último.
- **Se compensa hacia atrás y solo lo `hecho`.** Un paso pendiente no se compensa:
  deshacer algo que no pasó rompe más de lo que arregla.
- **`atascada` es un estado a propósito**, no un error. Significa que quedó trabajo
  hecho que no se puede deshacer; está en `sin_compensar` de la respuesta y en
  `sin_deshacer` de la ficha. Es trabajo manual pendiente: enganchad ahí vuestra
  alerta, no en el código HTTP.
- **Una saga en vuelo termina con SU versión.** `/sagas/migracion/simular` y
  `/sagas/plantillas/clonar` se retiraron el 09-11-2026 (resellado el
  contrato): miraban la tabla de sagas y no las instancias de proceso. La
  migración de instancias y las plantillas están en 4.4.1.1.
- **`GET /api/v1/sagas?estado=atascada` es la consulta que importa**: son las que
  esperan una decisión humana. Sin listado no se llega a ninguna ficha, y sin ficha
  no se llega a lo que hay que arreglar a mano — lo cazó el gate de acciones
  alcanzables, no una revisión.
- **El tenant sale de la cabecera firmada**, no del cuerpo. Una saga de otro tenant
  contesta 404, no 403: decir «prohibido» ya confirmaría que ese identificador es
  de alguien.

Cómo se ve desde fuera: la puerta de entrada encamina `/api/v1/sagas` al
`orchestrator`. Si una ruta existe en el servicio y falta ese encaminamiento,
devuelve 404 y el módulo sigue incomunicado — es exactamente lo que pasaba.

### 4.4.1.1 Motor de procesos: pasos que llaman al CRM, migración y plantillas

Base: `/api/v1/procesos` y `/api/v1/instancias` (servicio `orchestrator`).

| Ruta | Permiso | Para qué |
|---|---|---|
| `POST /api/v1/instancias` | `proceso:write` | Arrancar; guarda `lanzada_por` y la identidad con la que actuarán sus pasos |
| `POST /api/v1/procesos/definiciones/{clave}/{version}/migracion/simular` | `proceso:read` | Qué instancias en vuelo pasarían a esa versión y por qué se quedan las demás |
| `POST /api/v1/procesos/definiciones/{clave}/{version}/migracion` | `proceso:admin` | Migrarlas (cuerpo: `motivo` opcional) |
| `GET /api/v1/procesos/plantillas` | `proceso:read` | Biblioteca de plantillas de flujo, con `no_resuelve` |
| `POST /api/v1/procesos/plantillas/cargar` | `proceso:admin` | Cargar las de serie (idempotente) |
| `POST /api/v1/procesos/plantillas/{clave}/copiar` | `proceso:write` | Copiarla como borrador propio (`clave`, `nombre` nuevos) |

**Pasos «servicio».** `operacion` = `"MÉTODO /api/v1/ruta"`; la ruta admite
tramos `@variable`. `entrada` es el cuerpo (o los parámetros de un `GET`) y
`salida`, la variable donde se guarda `datos` de la respuesta. El motor
(`services/orchestrator/motor.py`, `Motor._invocar`) llama con
`crmcore.http.interno.invocar`, que resuelve el servicio de la ruta con
`crmcore.rutas_de_api.servicio_de` —la tabla del gateway— y firma las cabeceras
con la identidad guardada en la instancia:

- `instancias_proceso.lanzada_por` (UUID) y `permisos_de_lanzamiento` (JSONB
  `{"tipo","permisos","roles"}`), migración `da41584730f7`. Se toman del
  principal en `POST /api/v1/instancias`; un subproceso hereda los del padre.
  **Con ámbitos OAuth no se guarda nada** (una aplicación de terceros escribiría
  a través del proceso con los permisos de quien la autorizó). Es una foto del
  momento de arrancar.
- `tipo` viaja como `x-crm-tipo` (de serie `usuario`) para que el destino aplique
  la compartición de esa persona; `cabeceras_de` admite ahora `tipo` y `invocar`
  admite `tipo` e `idempotencia` (va como `Idempotency-Key`, derivada de
  instancia, paso e intento).
- Sin identidad → `proceso.sin_identidad`; un tramo `@x` vacío →
  `proceso.ruta_incompleta` (no se llama); 4xx/5xx → `proceso.paso_rechazado` con
  `detail`/`errores`/`error_code` del destino. Los tres los trata `_tratar_fallo`
  (reintentos, `al_fallar`, compensación). La compensación usa el mismo camino.
- Espera máxima de cada llamada: ajuste `proceso_paso_servicio_timeout_s`
  (`PROCESO_PASO_SERVICIO_TIMEOUT_S`, 30 s, editable en Admin).
- Validación al publicar (`validar_definicion(…, operaciones_con_nombre=…)`): la
  API pasa los invocadores con nombre registrados (`motor.construir_invocadores`,
  hoy vacío); lo que no es uno de ellos tiene que tener forma de ruta y un
  servicio que la atienda. También se valida la operación de cada compensación.

**Orden de lanzar desde una automatización.** `comando.proceso.lanzar` (lo emite
`automation`, acción `lanzar_proceso`) lo consume
`services/orchestrator/lanzar_desde_automatizacion.py`, grupo
`orchestrator-lanzar-proceso`. Lee `data.datos.definicion` y `data.datos.entrada`;
la instancia queda con `origen_tipo`/`origen_id` del comando. La identidad sale
de `data.datos.lanzado_por = {"principal_id", "tipo", "permisos", "roles"}` si
viene; si no, arranca sin identidad. Proceso no publicado o cuota agotada: se
registra (`lanzar_proceso.no_se_puede`) y se descarta, sin reintento.

**Migración** (`services/orchestrator/migracion.py`). Una instancia en vuelo
(`ejecutando`, `esperando`, `esperando_humano`) de la misma clave y otra versión
se migra si su `paso_actual` existe en la destino con el mismo `tipo`; se queda
si tiene tarea humana pendiente con rutas que la destino no tiene, si ya ejecutó
pasos con compensación que la destino no declara, si está `compensando` o si un
worker la tiene tomada (`tomada_hasta` futuro). Sólo a versión `publicada`.
Migrar cambia `definicion_id` y `version` y audita `proceso.instancia_migrada`
por instancia y `proceso.migracion_de_instancias` por lote.

**Plantillas** (`services/orchestrator/plantillas.py`). `plantillas_flujo` es de
la instalación (sin `tenant_id`). Las de serie son `PLANTILLAS_DE_SERIE`; cargar
añade versión nueva sólo si el contenido cambió. Copiar valida, exige clave
nueva en el tenant (409 `flujo.clave_ocupada`) y crea la definición en
`borrador`. `test_las_plantillas_de_serie_validan_y_llaman_a_rutas_que_existen_crm_00_03_05_15`
comprueba cada ruta, con su método, contra `docs/contrato-publicado.json`.

### 4.4.1.2 Automatizaciones: momento, disparadores, promoción y plantillas

`CRM-00.03.03.02`, `.05`, `.08`, `.09`, construidas el 09-11-2026: estaban
declaradas hechas y `momento`, `programacion`, cuatro de los siete disparadores,
`promocionar` e `instalar` no hacían nada.

- **Cola y planificador** (`services/automation/planificador.py`). Tabla
  `ejecuciones_pendientes` (única por `(tenant_id, clave)`, `ON CONFLICT DO
  NOTHING`): la fila se escribe en la transacción del disparo y se ejecuta en
  otra, con `SELECT … FOR UPDATE SKIP LOCKED`, marcándola `hecha` en la misma
  transacción que corre la regla. Una caída a medias deja la fila `pendiente`;
  un fallo de base se reintenta apartándola `revisar_s × intentos` y a los
  `AUTOMATIZACION_PENDIENTES_MAX_INTENTOS` queda `fallida`. Una regla apagada
  antes de su hora deja lo suyo `descartada`. La tarea `automation.planificador`
  corre en el `RelevoDeTareas` del proceso de API (`main.py`), cada
  `AUTOMATIZACION_PENDIENTES_REVISAR_S`, por tenant (`por_tenant`), hasta
  `AUTOMATIZACION_PENDIENTES_LOTE`. La tabla declara
  `info={"no_copiar_a_sandbox": …}` y `copia_sandbox` se la salta.
- **Programadas**: `services/automation/cron.py` (cinco campos, `*`, listas,
  rangos y pasos; día del mes y de la semana se combinan como en cron), en la
  zona del tenant (`zona_del_tenant`). `automatizaciones.proxima_ejecucion_at` y
  `proxima_segun` (con qué expresión se calculó: si la cambian desde la ficha se
  recalcula). Horas perdidas se colapsan en una vuelta. Clave
  `programada:<regla>:<hora>`.
- **Disparadores** (`consumidores.encajes`): la tabla `DISPARADORES`;
  `record.deleted` → `eliminacion` con `data.objeto`; y todo tipo del catálogo →
  `evento` con objetivo el tipo. Manual: `POST /automatizaciones/{id}/ejecutar`.
  Webhook: `POST /automatizaciones/{id}/secreto-webhook` (lo devuelve una vez;
  tabla `secretos_webhook_automatizacion`, cifrado con propósito
  `automatizacion_webhook`, aparte para que la copia a sandbox siga copiando las
  reglas) y `POST /automatizaciones/webhook/{tenant_id}/{id}`, público, exento en
  el gate de permisos (`recibir_webhook`), verificado con
  `crmcore.security.firma.verificar_firma` sobre los bytes recibidos; todo fallo
  contesta el mismo 401 `automatizacion.webhook_no_autorizado`.
- **Validación** (`validacion.py`): una sola para el alta, las plantillas y la
  promoción —cron que se cumple, evento del catálogo, operadores del motor; en
  modo estricto, los parámetros obligatorios de cada ejecutor—.
- **Identidad de quien activó**: `automatizaciones.activada_por_id` y
  `activada_con` (`tipo`, `permisos`, `roles`), escritos en `activar` y en el
  alta encendida, borrados al apagar o al promover. `motor.identidad_de` la pone
  en `ContextoEjecucion.lanzado_por` y `lanzar_proceso` la manda en
  `datos.lanzado_por` del comando. Sin identidad guardada no se inventa: el
  comando sale sin ella.
- **Promoción** (`entornos_auto.promover`, `POST /automatizaciones/promocionar`):
  pregunta el sandbox a `tenancy` por HTTP con la identidad de quien llama, lee
  las reglas del tenant del sandbox, casa por nombre y devuelve plan y huella
  (sha256 del plan); con la huella aplica, apaga y audita
  `automatizacion.promovida`.
- **Plantillas** (`plantillas.py`, `GET /automatizaciones/plantillas`,
  `POST /automatizaciones/plantillas/instalar` con `clave` enumerada y
  `responsable_id`): la prueba comprueba que cada una valida en estricto y que
  sus comandos tienen manejador con esos campos.
- **Migraciones**: `20261109_1123_momento_cola_y_secreto_de_webhook.py` y
  `20261109_1221_quien_activo_cada_automatizacion.py`. Pruebas:
  `test_automatizacion_momento.py`, `test_automatizacion_disparadores.py`,
  `test_automatizacion_plantillas_y_promocion.py`.

### 4.4.2 Describir un objeto por tipo de registro

`GET /api/v1/metadata/objetos/{nombre}/describe` admite `?tipo=<clave>`.

- **Sin `tipo`** se describe el objeto entero, y la respuesta trae
  `tipo_registro: ""`.
- **Con `tipo`** vienen solo los campos que ese tipo usa, y las listas recortadas
  a los valores que admite. La respuesta repite qué tipo se aplicó, para que un
  cliente que cachea descripciones sepa cuál tiene guardada.
- **Una clave que no existe da 404** (`metadata.tipo_registro_no_encontrado`), no
  la descripción completa: caerse a «todo» ante una clave mal escrita pinta un
  formulario con campos que ese tipo no usa y nadie se entera.

Si integras un frontend propio, pide la descripción **por tipo** siempre que el
registro tenga uno. Pintar el formulario con la descripción general y filtrar en
el cliente es reimplementar la regla, y es como acaba divergiendo del servidor.

### 4.4.3 Concurrencia: no pisar el cambio de otro

Para el técnico que integra escrituras. **Manda `If-Match`.**

1. Lee el registro. La respuesta trae `ETag`.
2. Edita con el verbo de modificación parcial y la cabecera `If-Match: <ese ETag>`.
3. Si contesta **409**, alguien lo cambió entre medias: relee, mira qué cambió y
   decide. **No reintentes a ciegas** — reintentar es exactamente pisar el cambio
   ajeno, que es lo que esto evita.

Detalles que importan:

- **Es opcional.** Sin `If-Match` la edición pasa como siempre: exigirlo rompería
  a quien ya integra. Pero sin él no tienes protección ninguna.
- **`If-Match: *`** vale «solo si el registro existe». Es lo que quiere quien
  actualiza algo que acaba de leer sin haberse quedado la versión.
- **El contador lo lleva la base de datos.** No lo mandes tú en el cuerpo ni lo
  calcules: sube solo en cada escritura, y es la comprobación de la propia base la
  que decide el 409.
- **Ojo con los modelos cuyo `version` es de negocio** —presupuesto, adjunto—: ahí
  `version` es la versión del documento, no la de la fila, y no sirve para
  concurrencia. Están declarados como tales.
- **Lectura**: manda `If-None-Match` con el ETag que ya tengas. Si no ha cambiado,
  contesta **304 sin cuerpo**. En una vista 360 eso es la diferencia entre
  cincuenta campos con sus relaciones y nada.

### 4.4.4 Referencias: a qué puede apuntar cada una

Si declaras una relación polimórfica, enumera sus destinos. A partir de ahí, una
escritura que apunte a un tipo que no esté en la lista se rechaza con
`metadata.destino_no_admitido`, y el error dice cuáles eran los admitidos.

- **La comprobación se hace donde se escribe**, no donde se declara: las
  relaciones viajan replicadas con el esquema del objeto, igual que sus campos.
- **Sin destinos declarados no se acota nada.** Es deliberado: si exigiera
  enumerarlos antes de saberlos, nadie declararía una relación.
- **El campo dice de qué relación es** en `restricciones.relacion`. Sin eso no se
  comprueba, y no se adivina: dos relaciones hacia el mismo objeto son dos cosas
  distintas.
- Si cambias los destinos admitidos, **vuelve a publicar el esquema**: la copia
  de cada servicio se actualiza con esa publicación, y hasta entonces sigue
  aceptando lo de antes.

### 4.5 Eventos

- **Sobre común** para todos: `id`, `type`, `version`, `tenant_id`, `occurred_at`,
  `actor`, `subject`, `data`, `trace_id`, `dedup_key`.
- **Outbox transaccional**: el evento se escribe en la misma transacción que el
  cambio, así que no hay eventos de cosas que no pasaron ni cambios sin evento.
- **Orden garantizado por clave de agregado**, deduplicación y *replay* desde un
  punto en el tiempo.
- **Contratos dirigidos por el consumidor**: quien lee declara qué campos necesita,
  y quitarlos del productor rompe el preflight de quien los quita — no la
  producción de quien los lee.
- **Webhooks** con reintentos, backoff, firma y buzón de fallidos.

### 4.5.1 Deduplicación en el consumo

Para el técnico que escribe un consumidor o que depura un evento repetido.

La entrega es **at-least-once**: el mismo hecho llega dos veces de serie, y eso no
es un fallo del bus, es su contrato. Lo que lo convierte en efecto único es el
buzón de entrada (`eventos_entrantes`).

Lo que hay que saber:

- **No hay que hacer nada en el consumidor.** La deduplicación se aplica al
  suscribir, en el arranque del servicio, a **todas** las suscripciones. Un
  consumidor que la montara por su cuenta la estaría haciendo dos veces.
- **La marca y el efecto son la misma transacción.** Si tu consumidor abre una
  unidad de trabajo, recibe la que ya hay abierta en vez de abrir otra: eso es lo
  que hace que «o las dos cosas o ninguna» sea verdad. No hagas `commit()` por tu
  cuenta dentro de un consumidor.
- **Si tu consumidor lanza una excepción, el hecho NO queda marcado** y el bus lo
  reintenta. Es lo correcto: tragarse el error dejaría el hecho por procesado sin
  procesarlo.
- **La clave la pone quien produce** (`dedup_key`). Si la escribes a mano, que
  lleve un identificador único — no `pedido:42`. La marca se guarda acotada al
  cliente, así que un choque entre dos clientes no puede pasar, pero dos hechos
  del mismo cliente con la misma clave sí se pisan, y eso sí es cosa tuya.
- **Retención**: `INBOX_RETENCION_DIAS`. El plazo tiene que cubrir de sobra la
  ventana de reintentos del productor: si se olvida una clave antes de que el
  productor deje de reintentarla, el reintento tardío pasaría como nuevo.
- **Para depurar**: la tabla `eventos_entrantes` dice qué consumidor procesó qué
  clave y cuándo. Si un evento «no ha llegado», mira ahí antes que en el bus — es
  posible que llegara y se descartara por repetido.

### 4.5.2 Tokenización: enchufar la bóveda

Para el técnico que monta la instalación. **El CRM no guarda tarjetas**: las saca
y guarda una referencia. Quien las guarda de verdad es la bóveda, y la bóveda la
pone el despliegue.

- **Sin bóveda registrada, el CRM se niega a guardar esos datos**, también
  tokenizados en falso. No es un fallo: es la decisión. Guardar el número «hasta
  que haya bóveda» mete la instalación en el alcance de PCI sin que nadie lo haya
  decidido.
- Para saber en qué estado está esta instalación:
  `GET /api/v1/<servicio>/tokenizacion` responde `hay_boveda` y los tipos
  admitidos. **Pregúntalo desde el front antes de ofrecer el campo.**
- El enchufe es `crmcore.security.tokenizacion.registrar_boveda(guardar,
  recuperar)`, con dos funciones: una que entrega el valor y devuelve un token, y
  otra que devuelve el valor a partir del token. Se registra en el arranque de la
  instalación, no en el producto: aquí no se enchufa ninguna a propósito, porque
  atarlo a un proveedor concreto es lo que no se hace.
- **Recuperar exige segundo factor reciente y motivo**, y queda en la auditoría.
  Si tu integración necesita el número a menudo, probablemente lo que necesita es
  no tenerlo: pásale el token al sistema de pagos.

### 4.5.3 Lo que sale marcado

- **Exportación**: `?formato=csv` devuelve el fichero montado y marcado arriba y
  abajo. Con `formato=json` (el de siempre) vienen las filas y la cabecera aparte,
  y ponerla queda de tu parte — si escribes un cliente propio, usa `csv`.
- **Audit trail a un SIEM**: `GET /api/v1/grc/auditoria/volcado.jsonl?desde=…&hasta=…`,
  JSON Lines en formato neutro, en flujo. Cada apunte lleva `sequence` y `hash`
  para que verifiques la cadena en destino; si falta una secuencia, falta un
  apunte. La primera línea es la marca de origen. Exige segundo factor.

### 4.5.4 Gestión documental: lo que queda apuntado y lo que va en diferido

- **Todo documento compuesto de una plantilla deja constancia** de la plantilla y
  la versión con la que se hizo, en el momento de componerlo. Se consulta con
  `GET /api/v1/plantillas-doc/{clave}/version/{version}/destinatarios`, que es la
  pregunta real: «esta cláusula está mal, ¿a quién se la mandamos?».
  Si al generar le pasas `documento_id`, queda enlazado al fichero del gestor; si
  no, la constancia existe igual — los que se mandan por correo sin archivar son
  justo los que después nadie rastrea.
- **El análisis de una rama va por trabajo**, nunca dentro de la petición:
  `POST /api/v1/documentos/analisis-de-rama` encola y devuelve `trabajo_id`; el
  estado se mira en `GET /api/v1/trabajos/{id}`. Pasa por el modelo de lenguaje y
  el de embeddings puede tardar minutos en cargar en frío — en caliente iría bien
  y daría 504 el lunes.
- **El resultado trae las citas agrupadas por documento**, con cuántos fragmentos
  salieron de cada uno y cuáles son huérfanos. Ordenadas por `relevance` y no por
  `score`: `score` cambia de significado a lo largo del recorrido de búsqueda y el
  único comparable entre resultados es el primero.
- El ejecutor del trabajo se registra al importar su módulo, y el router lo
  importa: si lo registras solo dentro de una ruta, el **worker** no lo tiene y el
  trabajo se queda encolado para siempre sin nadie que lo coja.

### 4.5.5 Cuotas, marca blanca y la firma que llega de fuera

- **Las cuotas del plan se materializan como ajustes del cliente** al darlo de
  alta. Si cambias un plan de sitio o lo editas, vuelve a aplicarlo: lo que ya
  esté puesto a mano en ese cliente **no se pisa**, y la respuesta dice qué
  cuotas se aplicaron y cuáles se respetaron.
- **El consumo se mide contando**, no con un contador incremental. Si añades una
  métrica nueva, regístrala con `crmcore.consumo.registrar_medidor` y aparece en
  el panel y en la página de estado sin tocar nada más.
- **Marca blanca**: `GET /api/v1/marca` dice qué falta y por qué; `PUT` configura
  sin activar; `POST /marca/dominio/verificacion` anota el resultado de tu
  comprobación de DNS (el detalle se guarda); `POST /marca/activar` enciende y
  contesta 409 con la lista si falta algo.
- **Chat entrante**: declara `cabecera_firma` y, si tu plataforma la manda,
  `cabecera_momento`. Con la segunda, la firma caduca según
  `WEBHOOK_FIRMA_VENTANA_S` y un mensaje capturado deja de valer. **Sin ella el
  canal es reproducible**, y la declaración te lo dice al crearlo.

### 4.6 Conectores

Un conector es **configuración, no código**: endpoints, mapeo de campos,
paginación, marcadores de vacío, OAuth2 con token cacheado. Sobre ese mismo
transporte van las suites de productividad (correo, calendario, contactos, tareas,
notas, ficheros, reuniones), la telefonía, la firma electrónica y las plataformas
publicitarias.

Escribir un módulo por proveedor convierte cada implantación en una versión del
producto; por eso no hay ninguno.

### 4.6.1 Cómo actúa el agente autónomo

Por la API del CRM, nunca por la base. Un agente que escribiera directamente se
saltaría el metamodelo, los permisos y las reglas de negocio, que es lo que hace
que un CRM tenga **una sola verdad** sobre qué se puede hacer.

Las tres piezas, y dónde están:

- **Qué puede llamar.** `services/intelligence/herramientas.py` deriva el
  catálogo del contrato publicado, cruzado con los permisos del agente. Cada
  herramienta lleva su método, su ruta, su permiso y su riesgo.
- **A quién llamar.** `crmcore.rutas_de_api.servicio_de(ruta)` — la misma tabla
  que usa el gateway para enrutar. Vivía dentro del gateway; se subió al núcleo
  el 27-10-2026 porque copiarla habría dejado dos tablas de acoplamiento que
  tienen que coincidir, y el síntoma de que dejaran de coincidir sería un
  agente llamando al servicio equivocado. La dirección de cada servicio sigue
  saliendo de `RUTAS_SERVICIOS`.
- **Con qué identidad.** `crmcore.http.interno.invocar` firma las cabeceras
  internas con la identidad del agente: su tenant, su identificador, sus
  permisos y `tipo=maquina`. Nunca con las cabeceras vacías de «soy de la
  casa», que no son acotables y no aparecen en el rastro como nadie; y nunca
  como administrador de plataforma, porque entonces un error del agente tendría
  alcance de todos los clientes.

Un 4xx del destino **no es una excepción**: vuelve como `{estado, ok, datos}` y
el modelo lo lee para corregir en el paso siguiente. Lo que sí es excepción es
no poder llamar —ruta sin dueño, servicio sin dirección, red caída—, porque eso
no es una respuesta y tratarlo como tal haría que el agente informara de un «no
hay nada» que nadie ha comprobado.

Qué hace falta en un despliegue: `RUTAS_SERVICIOS` con la dirección de cada
servicio —la misma variable que ya necesita el gateway— y nada más. Sin ella,
el invocador responde `interno.servicio_sin_direccion` diciendo cuál falta, en
vez de fallar con un error de red.

#### El bucle iterativo

`Agente.modo` decide cómo piensa: `plan_cerrado` pide todos los pasos de una vez
—es el que una persona aprueba de una vez— y `iterativo` pide uno, lo ejecuta y
vuelve a decidir con el resultado delante. El puerto es distinto en cada caso:
`agentes.registrar_planificador` para el primero y `registrar_continuador` para
el segundo, porque lo que se les manda y lo que se les pide no es lo mismo y
mezclarlos acabaría en un prompt con un `if` dentro.

El bucle vive en `agentes._pensar_siguiente`, y se entra en él desde `avanzar`
cuando no queda ningún paso `planificado`. Lo que importa de cómo está escrito:

- **La vuelta que decide no ejecuta.** Crea el paso con `_crear_paso` —el mismo
  que usa el plan cerrado, a propósito: el día que se toque la aprobación se
  toca en un sitio— y devuelve `avanzado: false` con `paso_decidido`. Lo ejecuta
  la vuelta siguiente.
- **Los tres límites se comprueban en cada vuelta**, no sólo al lanzar. El tope
  cuenta los pasos **pedidos**: contando sólo los hechos, un paso fallido dejaría
  hueco y el tope no acotaría el bucle.
- **Lo que devolvió cada paso se recorta** antes de enseñárselo al modelo
  (`ia_caracteres_resultado_paso`), y el recorte va marcado en el propio objeto.
- **Una herramienta pedida y no declarada para el agente para la ejecución**, no
  se vuelve a preguntar: reintentar es el bucle que se come el presupuesto
  pidiendo lo mismo.

El puerto `puerto._siguiente_paso` lo pide por **tool use nativo** del proveedor,
así que los argumentos los valida el propio proveedor contra el esquema de la
herramienta. Si el modelo pide varias llamadas a la vez se coge **una**: el
control humano, el tope y el apagado viven entre paso y paso.

### 4.6.2 El dialecto de cada proveedor

`services/intelligence/dialectos.py` es lo único de la casa que sabe cómo se
llama cada campo en cada familia, y está aparte para poder probarlo **sin red**:
las pruebas le dan un cuerpo de respuesta de cada familia y comprueban que sale
lo mismo.

Tres familias, en la lista cerrada del módulo: `openai_chat`, `anthropic_messages` y
`gemini_generate`. Cada una tiene su ruta por defecto —la de Gemini lleva el
modelo dentro del camino—, su forma de sacar el sistema de la lista de mensajes,
su forma de declarar herramientas y su forma de devolverlas. La función
`respuesta()` lo normaliza todo a las mismas claves —`texto`, `modelo`, los dos
contadores y `llamadas`— para que el resto del servicio no tenga que saber de
qué familia vino; si lo supiera, el `if` por familia estaría repartido por todo
el servicio.

Hasta el 28-10-2026 `ProveedorIA.formato` se guardaba y **no lo leía nadie**:
`puerto._llamar` construía siempre el cuerpo de la familia OpenAI. Era el
circuito abierto de siempre, con las dos mitades puestas y nada que las uniera.

### 4.6.3 Conectar un proveedor de verdad

Hasta el 29-10-2026 **nunca se había llamado a uno**. Los tres declarados eran
de siembra y apuntaban a `ia.ejemplo-ue.test` y compañía: dominios que no
resuelven. Al enchufar el primero real salieron cuatro cosas de golpe, y las
cuatro son del mismo tipo —lo que sólo se descubre usándolo—:

1. **El sembrador poblaba con algo que no funciona.** Tres filas verdes en la
   pantalla que al primer borrador contestaban un error de red. Una pantalla
   vacía que dice «no hay proveedor» manda a configurarlo; tres filas verdes
   mandan a buscar el fallo donde no está. Ya no se siembra ninguno.
2. **Y los sembraba mal**: sus modelos no declaraban `uso`, así que el
   enrutador los descartaba siempre. No se habrían podido elegir ni con la
   dirección buena.
3. **Al proveedor se le mandaba el nombre legible del modelo.** `elegir()`
   devolvía `nombre` —«Gemini 2.5 Flash»— donde va la `clave`, y eso viaja tal
   cual a la API; en la familia de Gemini, dentro de la URL. Respuesta: `400
   unexpected model name format`. Ahora devuelve las dos: `modelo` es la clave,
   que es lo que entiende la API, y `modelo_nombre` es lo que lee una persona
   en la pantalla de «qué modelo atendería esto». La prueba lo fija con una
   clave y un nombre **distintos**: cuando valían lo mismo, ninguna prueba se
   enteraba.
4. **Los tokens de razonamiento no se contaban.** Los modelos que razonan
   declaran aparte lo que han gastado pensando, y se factura como salida. En
   una llamada medida: 14 de entrada, 40 de respuesta y **979 de razonamiento**
   — el coste salía en la veinticincoava parte del real, y con él el
   presupuesto del tenant, que entonces no corta nunca. La suma cuadra con el
   total que declara el propio proveedor: 14 + 40 + 979 = 1033.

**Cómo se declara uno.** Es configuración de despliegue, no datos de
demostración, y no hay nada por casa en el código:

```bash
POST /api/v1/ia/proveedores
{
  "clave": "gemini",
  "nombre": "Google Gemini",
  "base_url": "https://generativelanguage.googleapis.com",
  "formato": "gemini_generate",
  "region": "ee_uu",
  "admite_opt_out": false,
  "modelos": [{"clave": "gemini-2.5-flash", "nombre": "Gemini 2.5 Flash", "uso": "redaccion"}],
  "coste_entrada_millon": "0.30",
  "coste_salida_millon": "2.50",
  "config": {"cabecera_auth": "x-goog-api-key"}
}
```

Un modelo por **cada uso** que atienda, de `USOS`: `redaccion`, `resumen`,
`extraccion`, `traduccion`, `consulta`, `embeddings`, `clasificacion`. Lo que no
declare no se le pide —los embeddings de Gemini son otro modelo, así que ese uso
se deja fuera a propósito en vez de mandarle una petición que no sabe atender.

**La credencial va en el `.env`, no en la ficha.** `IA_CREDENCIALES` es un mapa
`clave_del_proveedor=credencial`, igual que `RUTAS_SERVICIOS` y por lo mismo: es
un dato de despliegue. La ficha declara **qué cabecera** la lleva
(`config.cabecera_auth`); el valor lo pone el fichero. Un secreto guardado en la
base de datos se va con cada copia, cada volcado, cada clonado a una demo y cada
exportación de salida del tenant, y rotarlo obliga a repasar todos esos sitios.

**El opt-out es una decisión que alguien toma.** Por defecto cada tenant exige
que se pueda pedir, por petición, que no se entrene con lo enviado, y eso es lo
que un cliente asume sin preguntarlo. Hay familias que no tienen ese campo: lo
que ofrezcan será contractual. Entonces el proveedor se declara
`admite_opt_out: false` —y el enrutador lo descarta, diciendo por qué— hasta que
alguien baje `exigir_opt_out` en la política del tenant. Se hace así a propósito:
declarar `true` sin campo mandaría la petición sin él y daría por buena una
garantía que no viaja.

**Cuando el proveedor rechaza**, el error lleva ahora lo que dijo él
(`detalle.dijo`, recortado) además del código HTTP. Con el código a secas, un
`400` manda a revisar la credencial cuando lo que falla es un modelo que no
existe, un parámetro que esa familia no admite o una cuota agotada — y cada una
se arregla en un sitio distinto.

### 4.6.4 Nexus: por qué nunca había contestado

El agente autónomo estaba entero —plan, aprobación por riesgo, tope, presupuesto
y reversión— y **nunca había dado una respuesta**. Al conectar el primer
proveedor real y probarlo de punta a punta salieron cinco cosas encadenadas, y
cada una tapaba a la siguiente:

1. **Ningún agente tenía herramientas.** Se llamaba al modelo con la lista
   vacía, no podía proponer ningún paso, y `lanzar` devolvía 201 con
   `pasos: []` y el aviso en blanco: una pantalla que dice que ha ido bien y no
   ha hecho nada, pagando la llamada. Ahora un agente sin herramientas **se
   para antes de preguntar al modelo** y dice dónde se completa.
2. **El catálogo metía un campo nuestro en el esquema que sale fuera.** Cada
   parámetro lleva `in` —camino, consulta o cuerpo— porque lo necesita
   `puerto._repartir_argumentos`, pero ese esquema se manda al proveedor tal
   cual y `in` no es de JSON Schema. Dos familias lo toleran; Gemini rechaza la
   llamada entera. Se limpia en la frontera (`dialectos._esquema_hacia_fuera`),
   no en el catálogo: el dato hace falta dentro.
3. **Una lista no decía de qué.** `{"type": "array"}` sin `items` no es un
   esquema completo, y una sola herramienta mal descrita deja al agente sin
   ninguna. Ahora se toma del contrato y, si no lo dice, cadena. De paso viajan
   los `enum`: sin la lista cerrada delante, el modelo escribe un valor
   plausible y el servicio contesta 422 — un intento gastado para enterarse de
   algo que ya estaba en el contrato.
4. **El agente llamaba sin identidad.** `principal_id` venía vacío, el destino
   contestaba 401 y el modelo concluía «necesito credenciales válidas», que se
   lee como un límite del modelo y es un fallo de configuración. El sembrado
   ahora le pone la del usuario con el que siembra.
5. **Y un 401 se guardaba como paso «hecho».** El resultado llevaba dentro
   `ok: false` y el estado decía lo contrario: verde en la pantalla y verde en
   la auditoría, en la pantalla cuya promesa entera es poder ver qué ha hecho.
   Ahora el estado sale del resultado. El resultado **se conserva** —es
   información, y en modo iterativo el modelo decide el paso siguiente con ella
   delante— pero en plan cerrado la ejecución se para, porque los pasos de
   detrás se planificaron dando éste por bueno.

**Cuántas herramientas.** Derivar de los contratos de `party`, `sales` y
`service` sin acotar da **428** de lectura. No caben en una llamada ni ayudan:
cuatrocientas opciones para contestar «qué cuentas están en riesgo» hacen que el
modelo elija peor. El asistente que se siembra va acotado por `solo_rutas` a
cuentas, contactos, actividades, oportunidades, leads y casos: **31**.

Medido funcionando el 29-10-2026: objetivo «¿qué actividades están vencidas?» →
un paso, `get_api_v1_activities_vencidas`, ejecutado contra los datos reales →
conclusión «No hay actividades vencidas».

### 4.6.5 Lo que el agente leía, y lo que creía leer

Con Nexus ya planificando y ejecutando, lo que devolvía seguía estando mal. Dos
fallos más, y los dos de la misma clase: **no fallaba nada, contestaba de menos
y lo decía con seguridad.**

**Cero filas con un 200.** `http.interno` firmaba las llamadas del agente con
`x-crm-tipo: maquina`. `authz.visibilidad` preguntaba por `servicio` para
saltarse la compartición entre personas, y `http.reverificacion` por `servicio`
o `automatizacion`. Tres palabras para la misma idea, en tres ficheros, y
«maquina» no casaba con ninguna: el agente pasaba por persona, se le aplicaba el
filtro de compartición, esa persona no posee ningún registro y `GET /accounts`
le devolvía **cero filas**. El modelo concluía «no hay cuentas» sobre un tenant
con sesenta y cinco. Es el mismo agujero que ya se había tapado para las
credenciales de integración, con otra palabra.

Ahora el vocabulario vive una vez, en `crmcore.vocabularios`
(`TIPOS_DE_PRINCIPAL`, `NO_SON_PERSONAS`, `es_persona`), junto a las demás listas
cerradas que cruzan de un servicio a otro. Gate:
`tests/unit/test_quien_llama_se_dice_igual_en_los_dos_lados.py`, que además
prohíbe comparar el tipo con una cadena suelta — cada comparación suelta es una
palabra más que puede no coincidir.

**Y un valor tapado parece un dato.** Resuelto lo anterior, el agente leía las
cuentas y contestaba que se llamaban «··············tora», «··cosa» y
«·············elta». Dos cosas a la vez:

- El agente llamaba **sin ningún rol**, y el rol es lo que decide qué campos ve:
  caía al comodín de la política de sensibilidad del tenant y recibía todo
  enmascarado. Ahora un agente declara sus `roles`, igual que sus permisos, y no
  los hereda de quien lo puso en marcha.
- Y **nadie anunciaba el enmascarado**. `X-Campos-Retenidos` sólo lleva los
  campos *ocultos*, y la diferencia importa: lo retenido no viene y se ve el
  hueco; lo tapado viene, tiene la forma del dato y se cita como tal. Se añade
  `X-Campos-Enmascarados`, aparte y no sumada, y `interno.invocar` la pasa al
  resultado de la herramienta con un aviso en palabras, que es lo que lee el
  modelo. La pantalla también lo enseña ahora, con su propia frase.

**Y una clave borrada no se podía volver a usar.** `uq_agente_clave` es
`(tenant_id, clave)` y cuenta las filas de la papelera, así que declarar otra vez
un agente borrado no encontraba nada, insertaba y chocaba con un 409 que habla de
«un registro que ya existe» y que quien lo lee no puede ver. Al sembrado le
pasaba igual: lo contaba como duplicado y dejaba el tenant sin agente sin decirlo.
`declarar` mira ahora la papelera con `con_borrados(db)` y revive la fila **con
lo que se declara ahora**, no con lo que tenía — resucitar con la configuración
vieja sería devolver permisos que alguien quitó.

### 4.6.6 «Esto antes no decía esto»

Cada edición que pasa por `audit.chain.registrar_cambios` anota el campo, el
valor anterior, el nuevo, quién lo hizo y **desde dónde** —la pantalla, la API
o una automatización—. Se escribía desde el principio y **no lo devolvía
ninguna ruta**: la primera pregunta de cualquier discusión sobre un registro no
se podía contestar sin entrar en la base de datos.

`GET /api/v1/{servicio}/rastro/campos/{objeto}/{objeto_id}` lo devuelve, y la
ficha del registro lo enseña plegado, cargándolo **sólo al abrirlo**: es
trazabilidad, no contenido, y pedirlo en cada ficha abierta sería una llamada
por registro que casi nadie mira.

El **origen** va al lado de cada cambio y no en otra columna: es lo que
distingue «lo cambió alguien» de «lo pisó una sincronización todas las noches»,
y sin eso se culpa a quien pasaba por ahí.

Lo escriben hoy `party` y `sales`. En un servicio que no lo haga, esta ruta
contestaría vacío para siempre y quien la mira concluiría que el registro no se
ha tocado — así que el vacío **dice cuál de las dos cosas es**, y lo distingue
midiendo —¿tiene este servicio algún cambio de campo de algún registro?— en vez
de con una lista de servicios escrita a mano, que se quedaría vieja el día que
un sexto empiece a anotarlos.

De paso salió uno de los de siempre: `Vacio` en modo `compacto` **tiraba el
detalle**. Cuatro pantallas le pasaban una explicación —por qué no hay rastro,
por qué no hay conexiones, cuál de las dos cosas es este historial vacío— y
ninguna llegaba a quien la miraba. Un vacío sin porqué se lee como «no hay
nada», que es justo lo que esas pantallas intentaban no decir.

### 4.6.7 La pantalla que acepta la pregunta y no hace nada

El último de la serie, y el único que se vio **usándolo** y no midiendo: Nexus
aceptaba la pregunta, el botón se apagaba y ya no volvía. Sin error, sin aviso y
sin una sola petición saliendo del navegador.

`Preguntar` lleva una bandera de «sigo montado» para no pintar sobre un
componente desmontado ni seguir gastando presupuesto del agente. Estaba escrita
así:

```tsx
const vivo = useRef(true);
useEffect(() => () => void (vivo.current = false), []);
```

Sólo la limpieza. En desarrollo, **`StrictMode` monta, desmonta y vuelve a
montar**, así que el segundo montaje arrancaba con la bandera ya en `false` y se
quedaba así para siempre. A partir de ahí: el plan llegaba y no se pintaba, y el
`finally` no quitaba «trabajando», con lo que el botón se apagaba y no volvía.

Lo que hace falta es poner la bandera a `true` **al montar**, no sólo a `false`
al desmontar.

Y una lección sobre las pruebas, que es la mitad que importa: las de esta
pantalla **pasaban**. Montaban el componente a pelo, una sola vez, que es algo
que la aplicación no hace nunca. Al montarlas con `StrictMode` —como `main.tsx`—
y volver a plantar el fallo, **caen cinco**, cuatro de ellas escritas mucho
antes. Una prueba que no monta como monta el producto mide otra cosa.

### 4.6.8 El gobierno del SSO, que se escribía y no se leía

Cinco ajustes del proveedor de identidad se guardaban con un `PATCH` y **no los
devolvía nadie**: el listado daba el nombre, el tipo y los NOMBRES de las claves
de configuración, así que `forzar_sso` se veía como una palabra en una lista y
nunca su valor.

Lo que eso dejaba sin poder revisar es lo que más importa de todo esto:

| Ajuste | Qué deja sin ver |
|---|---|
| `permite_idp_initiated` | Si se aceptan aserciones que empiezan en el IdP. Vienen apagadas por un motivo: sin `InResponseTo` que atar a una petición nuestra, **una aserción robada se puede reenviar** |
| `acr_con_mfa` | Si el segundo factor se da por cumplido con lo que diga el proveedor, o sea si aquí ya no se pide |
| `forzar_sso` + `cuentas_de_rescate` | Si la contraseña local está cortada y **quiénes** se lo saltan. La capacidad exige que la excepción sea nominal y quede escrita, y una excepción que no se ve deja de ser una excepción |
| `dominios` | Qué correos atiende cada proveedor cuando una empresa tiene seis tras tres adquisiciones |

Se publican, y se enseñan los **correos** de rescate y no su recuento: «2 cuentas
de rescate» no se puede revisar. El forzado va por dos sitios —el del tenant y
el de cada proveedor— así que la pantalla enseña los dos: mirar sólo uno da por
abierta una puerta cerrada, o al revés.

**Y una sesión dice ahora si al salir se cerrará también en el proveedor**
(CRM-00.05.01.12). La correspondencia entre una sesión de aquí y la del IdP se
guardaba —es la que hace que el aviso de cierre sepa a quién aplicarse— y
tampoco la devolvía nadie. Cerrar sólo aquí deja la del proveedor viva y volver
a entrar no pide credenciales: para quien lo hace, el botón de salir no ha hecho
nada. Que no esté enlazada no es un fallo nuestro —hay proveedores que no mandan
índice de sesión— pero es una carencia que hay que poder ver, y el propio código
ya la anotaba en la auditoría sin que nadie pudiera consultarla.

**Y de paso, un 500 que llevaba ahí desde siempre.** El listado de proveedores
devolvía el modelo donde `paginar_consulta(fila_a_dict=…)` espera un
diccionario, así que reventaba **en cuanto hay un proveedor declarado**. No lo
vio nadie porque la lista estaba vacía en todas las instalaciones que se
miraron: el fallo sólo aparece en el cliente que de verdad usa SSO. Lo cazó la
primera prueba que dio uno de alta.

### 4.6.9 Nexus: una pregunta no se contesta con una línea de código

Dos cosas reportadas usándolo, no midiendo. A *«dame un listado de cuentas»*
Nexus contestaba con `get_api_v1_accounts` **escrito dos veces** y un botón.

**El paso se leía como código.** Era `porque || herramienta` y debajo
`herramienta`: cuando el modelo no explica el paso —que es casi siempre en el
modo iterativo— salía el nombre repetido. La descripción la trae la propia
declaración del agente («Listar cuentas»), derivada del contrato de la API, así
que no hay que inventarla ni mantener una segunda lista.

**Y un plan que sólo lee pedía otro clic.** El botón existe porque entre paso y
paso caben el tope, el apagado y la aprobación, y una pantalla que los disparara
todos de golpe convertiría esos tres controles en decoración. **Eso vale para lo
que escribe.** Cuando todo el plan es de lectura no hay nada que aprobar —la
aprobación va por riesgo— así que el botón sólo añadía un paso entre la pregunta
y la respuesta. Ahora arranca solo si y sólo si todos los pasos son de lectura,
y hay una prueba de que **uno que escribe no arranca**: sin ella, el arranque
automático se come la aprobación el día que alguien lo relaje.

### 4.6.10 Lo que de verdad impedía que Nexus contestara

«No contesta a nada» era cierto, y la causa no era el modelo. Tres cosas, en
orden de cuánto pesaban:

**1. Veía dos cuentas de sesenta y cinco.** `IA_CARACTERES_RESULTADO_PASO`
valía **2.000**, y una cuenta de este producto ocupa **826 caracteres** —
veintiocho campos—. El agente recibía el 4 % de la respuesta y hacía lo
correcto: decir que la lista venía cortada y no concluir. Sube a **20.000**,
que son unas veinticuatro cuentas; veinte vueltas de ese tamaño siguen cabiendo
de sobra en el contexto de los modelos de hoy, y quien despliegue con uno
pequeño lo baja — para eso es un ajuste.

**2. La pregunta del ejemplo no tenía respuesta en la API.** La pantalla sugiere
literalmente «qué cuentas llevan más de dos meses sin contacto», y no se podía:
`ultima_actividad_at` es un **rollup** —el máximo de las actividades de la
cuenta— y los filtros del listado sólo admiten columnas, así que ni se filtraba
ni se ordenaba por él. Se añade `GET /api/v1/accounts/sin-contacto?dias=N`, con
el corte sacado del ajuste del tenant cuando no se dice.

**Las que no tienen ninguna actividad entran**, y son las que más importan: una
cuenta con la que no se ha hablado nunca no es lo mismo que una de hace tres
meses, pero dejarla fuera por no tener fecha la esconde justo en el listado que
existe para encontrarla.

**3. Y el paso se leía como código**, con el nombre de la función repetido.

Medido funcionando después de las tres: «qué cuentas llevan más de dos meses sin
contacto» → un paso, `get_api_v1_accounts_sin_contacto` con `dias=60` → los
cuatro nombres, **en tres segundos**, citando la herramienta y el parámetro.

**Y el presupuesto del agente, medido.** Una pregunta de este asistente cuesta
entre 3.000 y 8.000 tokens —lee listados y decide con el resultado delante—, así
que los 200.000 de fábrica se agotan en unas treinta: una tarde de una sola
persona. Se sube el del asistente sembrado a dos millones, unas trescientas
preguntas al día. **El guardia que de verdad importa no es ése**, sino el
presupuesto en euros de la política del tenant: los tokens miden consumo y los
euros miden lo que se paga, y lo segundo es lo que alguien decide.

### 4.6.11 Los filtros que nadie podía descubrir

El contrato de `GET /accounts` declara siete parámetros —`limite`, `cursor`,
`orden`, `buscar`, `estado`, `owner_id`— y el servidor acepta filtros sobre
**treinta** columnas con **nueve** operadores: rangos, listas, «vacío» y «no
vacío». La única forma de enterarse era pedir uno mal y leer el 422, que sí los
lista. Lo paga todo el que integra.

Se vio con el asistente: a «hay contactos sin teléfono» contestó que la API no
ofrece manera de filtrar por eso. **Sí la ofrece** —`?telefono__vacio=true`— y
no tenía cómo saberlo.

**No se arregla publicándolos en el OpenAPI**, y por una razón que conviene
entender: el conjunto depende de **quién pregunta**. Por un campo que esa
persona ve enmascarado no se puede filtrar, porque filtrarlo lo reconstruye a
base de preguntar —«¿empieza por 6?», «¿y por 7?»— sin llegar a verlo nunca. Un
contrato estático diría que se puede filtrar por el teléfono y para media
plantilla sería mentira. Se contesta en caliente:

```
GET /api/v1/{servicio}/filtros            → los objetos que guarda
GET /api/v1/{servicio}/filtros/{objeto}   → por qué campos puede filtrar QUIEN pregunta
```

Devuelve también **lo que NO se puede y por qué**: sin eso, quien integra busca
un campo que ve en la respuesta y no puede usar, sin saber si es que no existe o
que no le toca.

**Y el eslabón que faltaba, que era el peor.** Con los filtros ya descubribles,
el agente pidió `telefono__vacio=true` y recibió todos los contactos. La causa
estaba en el repartidor de argumentos: lo que el contrato no nombra iba al
cuerpo si la ruta lo admitía y, si no, **se descartaba** — y un `GET` no tiene
cuerpo. La llamada salía sin acotar y devolvía la tabla entera. Es exactamente
lo que este sistema llama en otro sitio «un filtro que no filtra, peor que no
tener filtros, porque el resultado parece correcto».

Ahora, en un `GET`, lo no declarado va a la consulta. Si el nombre es inventado
el servidor contesta 422 **con la lista de los que valen**, que es una respuesta
que enseña; descartarlo en silencio era un acierto que mentía.

Medido después: «hay contactos sin teléfono» → pregunta los filtros, usa
`telefono__vacio` y contesta.

### 4.6.12 El campo que se publicaba y no llegaba nunca: `total_aprox`

El hueco lo destapó la misma conversación: a «cuántas cuentas no tienen web» el
asistente contestó que puede listarlas pero no contarlas. Y tenía razón.

`total_aprox` está **en el contrato de toda página** del CRM —en `Pagina` y en
`PaginaDeListado`—, así que un cliente generado del OpenAPI lo espera y una
pantalla puede pintarlo. **No lo rellenaba ninguna de las treinta y tres rutas
de listado**: llegaba siempre `null`. Un campo que se declara y no llega es peor
que uno que falta, porque quien integra lo da por disponible y descubre que no
cuando ya ha escrito la pantalla.

Ahora se pide: `?contar=true`.

```
GET /api/v1/accounts?estado=activa&contar=true
  → { "items": [...], "siguiente": "...", "hay_mas": true, "total_aprox": 412 }
```

**Por qué detrás de un parámetro y no siempre.** Un recuento exacto cuesta un
recorrido completo de la tabla, y casi nadie necesita el número: necesita saber
si hay más, y eso ya lo dice `hay_mas` sin coste, que es para lo que se pide una
fila de más. Hacerlo de oficio sería cobrarle ese recorrido a cada listado de
cada pantalla por un número que casi nadie mira.

Tres detalles que parecen pequeños y no lo son:

- **Se cuenta sobre la consulta ya filtrada**, con la compartición y los
  permisos aplicados. Contar sobre la tabla diría cuántas hay, no cuántas ve
  quien pregunta: otro número, y además una filtración.
- **Se cuenta antes del cursor, no después.** Con el cursor puesto, el recuento
  dice cuántas quedan de aquí en adelante. En la primera página coincide con el
  total y parece correcto; en la segunda ya miente, y nadie vuelve a mirar la
  primera. Hay prueba, y se validó plantando justamente ese fallo.
- **`paginar_consulta` era el peor de los tres caminos.** Contaba y luego armaba
  el diccionario de respuesta a mano, sin `total_aprox`: pagaba el recorrido
  completo y tiraba el número en la puerta.

Lo tienen los tres caminos por los que este sistema sirve una página —la
fábrica, `paginar_consulta` y los siete listados que arman su propia consulta—,
y un gate sobre la aplicación construida exige que el listado número treinta y
cuatro nazca sabiendo contar. La única excepción es `GET /entornos`, que no lee
una tabla: devuelve una lista cerrada en memoria y da el total **siempre**,
porque ahí no cuesta nada.

De paso cayó un vecino: `total` figuraba como «parámetro que no es un filtro» y
no lo implementaba nadie. Hay cuatro modelos con columna `total` —cotización,
pedido, presupuesto, cálculo de comisión—, así que `?total=1000` se descartaba
en silencio y el listado devolvía todas las filas con cara de estar filtrado.
Esa reserva muerta ya no está.

### 4.6.13 Lo que el tenant cambia sin escribir código, con puerta

Nueve capacidades de la familia del metamodelo estaban **publicadas y sin
puerta**: existían por API, tenían prueba y no se alcanzaban desde ninguna
pantalla. Un cliente que compra «personalizable sin desarrollo» y tiene que
llamar a la API para ver qué formulario le toca ha comprado otra cosa.

Van todas a la ficha del objeto del modelo, porque son la misma pregunta hecha
seis veces delante del mismo registro:

| Qué contesta | De dónde sale |
|---|---|
| Qué diseño le toca a esta persona y **por qué ése** | `GET /metadata/objetos/{o}/diseno` |
| Qué entiende la IA de este objeto, con su **cobertura** | `GET /metadata/objetos/{o}/semantica` |
| Qué campos salen en informes como dimensión o métrica | `GET /analitica/modelo-semantico?objeto={o}` |
| Qué campos ya justifican una columna real | `GET /metadata/objetos/{o}/candidatos-columna` |
| Por qué estados pasa el registro | `estados` del objeto |
| Cuándo se puede retirar un campo renombrado | `GET /metadata/objetos/{o}/trazabilidad` |
| Llevarse la configuración a otro entorno | `GET /metadata/paquete?objeto={o}` |

Tres decisiones que no son de estilo:

- **La cobertura va con su número, no con una frase.** «La IA entiende tus
  datos» con el 25 % de los campos descritos es la razón de la mayoría de los
  proyectos de IA decepcionantes. El panel enseña el porcentaje, los campos que
  se han dejado fuera y **los que faltan por su nombre**: un porcentaje dice
  cuánto queda, una lista dice qué hacer.
- **Lo de informes lo contesta analytics, no metadata.** Es otro servicio el
  que decide qué puede explotar; preguntárselo al de metadatos sería contestar
  por él, y el día que cambie el criterio la pantalla seguiría diciendo lo de
  antes.
- **Materializar no se ofrece como un botón grande.** Un `ALTER TABLE` en una
  tabla compartida por mil tenants los bloquea a todos. Es la excepción, se
  decide con la medida de escrituras y el umbral sale de la ruta, que es
  configuración del tenant.

**Y dos que NO se cierran, dicho aquí en vez de disimularlo.**
`CRM-00.04.03.05` —campos propios usables en condiciones, acciones y reglas de
los flujos— y `CRM-00.04.03.08` —en importación, exportación y plantillas— no
tienen ninguna ruta que lo conteste: su única constancia es un comentario
dentro de un servicio. Una pantalla que lo afirmara sería la pantalla diciendo
que sí, que es exactamente lo que este sistema no acepta como prueba.

**Hallazgo de la misma vuelta, y este es grande.** La familia `CRM-00.04.02`
—extensiones del tenant: funciones en sandbox, hooks, versiones, firma,
observabilidad— está marcada hecha y son **seis validadores sin estado**. No
hay tabla, no hay modelo, no hay migración y no hay ninguna ruta `GET`: no se
puede listar una extensión, ni instalarla, ni saber cuáles tiene un tenant.
`POST /extensiones/observabilidad` calcula estadísticas **sobre las ejecuciones
que le mandas tú**. Son calculadoras correctas que no están enchufadas a nada,
y por eso ninguna de las siete puede tener pantalla: no hay nada que enseñar.
*(Cerrado el 05-11-2026 para cinco de las siete: ver «El código del tenant,
ejecutado de verdad». Los hooks y las extensiones asíncronas, `.02` y `.03`,
siguen siendo del núcleo y se declaran en código.)*

### 4.6.14 Un proceso parado: verlo y sacarlo

Siete capacidades de la familia de procesos no se alcanzaban desde ninguna
pantalla, y **dos de ellas no eran una pantalla que faltaba: era código que
faltaba**.

**Lo que faltaba de código.** `CRM-00.03.02.12` dice tres cosas —reintento,
**salto de paso** y edición de variables en caliente— y estaban dos: la
capacidad constaba hecha citando el esquema de la edición de variables.
Saltar un paso no existía en ninguna parte. Y no es un adorno: reintentar
vuelve a ejecutar lo mismo y editar las variables corrige el dato, pero hay
pasos que **no se pueden completar nunca** —un servicio de un tercero que ya
no existe, una tarea humana de alguien que se fue— y ahí el proceso se queda
parado para siempre con todo lo que venía detrás sin hacer.

`POST /instancias/{id}/saltar-paso` lo cierra, con la condición que hace que no
sea una puerta trasera: **sólo a un destino que el propio paso declara**.
Saltar a cualquier paso dejaría meter una instancia en la rama de aprobado sin
pasar por la aprobación, y el histórico diría que el proceso se siguió. Los
destinos salen de `destinos_de`, que es la misma función que usa el recorrido
de alcanzables del validador: teniéndolo repetido, un tipo de enlace nuevo
añadido a uno de los dos haría que el salto rechazara un destino legítimo.
Exige motivo y queda auditado **con los dos extremos**, de dónde y a dónde:
sólo con el destino no se puede saber qué se saltó.

Lo segundo: `CRM-00.03.05.04` promete «qué ruta seguiría, **quién aprobaría y
cuánto tardaría**», y el simulador contestaba sólo lo primero. Ahora devuelve
`quien_aprobaria` y `horas_declaradas`, sacados de la propia definición
—`asignada_a` / `asignada_rol` / `cola` y `vence_en_horas`—, que es lo que el
motor mirará de verdad al crear la tarea. **El plazo es el declarado, no una
predicción**, y los pasos humanos sin plazo salen listados aparte: un proceso
que espera a una persona sin fecha no tarda cero, y un total que se calla eso
es un total que engaña.

**La pantalla.** Una instancia tiene ficha propia, como el objeto del modelo y
por el mismo motivo: el gráfico necesita la definición **de la versión con la
que arrancó**, no la publicada, y pintarla sobre la nueva señalaría pasos que
esa instancia no tiene. Enseña por dónde va sobre su propio diagrama —el mismo
lienzo que el editor, con el estado escrito debajo de cada caja y no sólo en
el color—, qué pasó en orden (el depurador: el estado por nodo dice dónde
está, el orden dice qué decidió en cada vuelta de un bucle), las tres
herramientas de rescate juntas —elegir entre ellas es el trabajo— y dónde se
atasca ese proceso en todas sus ejecuciones, con el «no es concluyente»
delante.

Una instancia **no se edita campo a campo**, y está declarado como excepción
con su motivo: poner a mano su estado o su paso actual es exactamente lo que
el salto controlado evita.

### 4.6.15 Las acciones de colección se deducen, no se escriben

El listado ofrecía botones para las acciones sobre la colección entera —«carga
el almacén», «recalcula»— y **se declaraban a mano**. El comentario que las
declaraba decía que no se podían deducir: «una acción de fila cuelga del
identificador y la superficie la delata sola; ésta es hermana del listado, no
hija suya».

Medido el 29-10-2026: hay **102 `POST` colgando de una colección sin ningún
parámetro en la ruta, y la lista a mano tenía cuatro**. Trece de las 102 no
piden cuerpo —son «haz ahora el trabajo que toca»— y **ninguna tenía botón en
ninguna pantalla**. Entre ellas, `POST /dispositivos-confianza/revocar-todos`,
cuyo resumen es literalmente «He perdido el portátil».

Es el caso de libro de una lista de los que sí: no falla, no avisa, y lo que
falta no se nota porque nadie echa de menos un botón que nunca ha visto.

Ahora salen del contrato. Para poder deducirlas hizo falta **un dato nuevo en
la superficie**: `exige_cuerpo`. Es otra pregunta que `exige_datos`, que mira
los parámetros de la URL, y es la que separa una acción de un formulario: una
operación que pide cuerpo y se llama en seco contesta 422, así que su botón
sería un botón que no funciona nunca.

Las **89 restantes piden cuerpo** y se quedaron fuera: necesitan que alguien
rellene algo, y un formulario inventado desde la ruta se equivoca de campos.

#### Y esa segunda mitad también hacía falta (04-11-2026)

Lo de arriba resolvió trece de ciento dos y dejó la mayoría sin alcanzar. El
motivo escrito era bueno —«un botón que siempre da 422 es peor que no tener
botón»— y la conclusión no: **lo que pide datos no sobra, pide formulario**. Y
el formulario no había que inventarlo: la ficha lo monta desde el
`requestBody` del OpenAPI desde el primer día, para las acciones de un
registro. Eran el mismo mecanismo con dos destinos y sólo uno conectado.

Medido sobre los trece contratos: de las **98** acciones de colección que caen
en una pantalla de módulo se ofrecían **14**. De las 84 descartadas, 71 rutas
distintas, y **50 no aparecían en ningún fichero del front** — ni por aquí ni
por una pantalla escrita a mano. «A qué proveedor iría este encargo»,
«Comprobar un contenido antes de mandarlo», «Qué faltaría si se generase
ahora», «Dónde duele si un proveedor falla mañana». Las otras 21 sí tienen
pantalla propia; por eso el número que importa es 50 y no 84.

Ahora la pantalla de módulo usa **el mismo componente que la ficha**. Tres
consecuencias que conviene tener escritas:

1. **`exige_datos` sigue descartando**, y por el motivo original: son
   parámetros de la URL, el formulario se saca del cuerpo, y una acción así
   saldría con el formulario vacío. Medido: de las 84, **83 son sólo cuerpo y
   una** pide además parámetro. Esa una se queda fuera a sabiendas.
2. **Un cuerpo abierto no es un cuerpo vacío.** Hay operaciones cuyo
   `requestBody` es `{"type": "object"}` sin propiedades, y a propósito: «a qué
   proveedor iría este encargo» lleva lo del sector (`bultos`, `peso_kg`,
   `destino_cp`) y «a qué territorio va esta cuenta» lleva los atributos que
   miren las reglas de cada instalación. Fijarles un modelo sería estrechar lo
   que está abierto porque tiene que estarlo. Son **10 en toda la API**, 5 de
   ellas simulaciones que alguien quiere usar. El contrato devuelve para ellas
   **un campo que es el cuerpo entero** (`cuerpoEntero`), que se edita como
   pares clave/valor; sin eso el botón mandaba `{}`, es decir, «a qué proveedor
   iría este encargo» sin encargo.
3. **Lo que no pide nada sigue costando un clic.** El contrato del servicio se
   lee por adelantado para saber qué acciones no tienen campos, y ésas se
   ejecutan al pulsar en vez de abrir un panel con un solo botón que repite el
   rótulo. Las irreversibles siguen preguntando antes.

Lo escrito a mano queda como excepción: las que llevan una frase de ayuda bajo
el botón porque el rótulo no basta.

#### El buscador iba encajado en la barra

«Queda muy encajado»: la barra medía 48 px y el buscador 40, así que le
quedaban **4 px de aire arriba y 4 abajo** siendo la caja más grande de la
barra. A 52 px son seis y seis.

El guardián fija la **relación** y no el número —aire ≥ 6 px—, y pone también
el tope por arriba: «que respire» se cumpliría con una barra de 80 px, y esta
barra está fija en todas las pantallas, así que cada píxel suyo es un píxel
menos de listado.

#### Las tres rayas no hacían nada en nueve de cada diez pantallas

Lo preguntó quien lo usa: «¿tienen sentido?». No lo tenían.

El panel lateral —el árbol de ajustes— se pinta **sólo en configuración**, y
está escrito por qué: trabajando estorba, porque lo que hace falta son las ocho
pantallas de ahora mismo y ésas caben arriba. El botón que lo pliega, en
cambio, se pintaba siempre, y en la esquina de arriba a la izquierda, que es
donde se busca la navegación principal.

Medido pulsándolo antes de tocar nada, a 1440 px:

| | `aside` | ancho del contenido | |
|---|---|---|---|
| Pantalla de trabajo | 0 → 0 | 1440 → 1440 px | no pasa nada |
| Configuración | 1 → 1 | 1440 → 1218 px | pliega el árbol |

Un botón que no hace nada es peor que no tenerlo: quien lo pulsa no concluye
«esto no sirve aquí», concluye que ha hecho mal el clic. Ahora el marco le dice
a la barra si hay panel (`conPanel={configurando}`, la misma condición con la
que monta el árbol tres líneas más abajo), y el guardián vigila los dos
sentidos — porque quitarlo de todas partes también cumpliría «no sale donde no
sirve», y dejaría sin forma de ganar los 222 px que ocupa el árbol.

#### Dos fuentes de pestañas y ninguna miraba a la otra

En la ficha de un candidato salía «Relacionado · Detalles · Actividad ·
**Comentarios · Comentarios**». Dos entradas con el mismo rótulo, una al lado
de la otra, que no se distinguen más que pulsándolas.

`Ficha.tsx` arma sus pestañas con lo que el registro puede tener —y la
conversación es una— y `PestanasDeFicha` añade la conversación por su cuenta
cuando la superficie dice que ese objeto admite comentarios. Las dos tenían
razón; lo que faltaba era que la segunda mirase si ya estaba. Se compara por
**clave** y no por rótulo: el rótulo se traduce, y dos claves distintas pueden
llamarse igual en un idioma y no en otro.

El guardián vigila los dos sentidos, porque «no repetir» se cumpliría también
no ofreciéndola nunca: con la pestaña declarada por quien llama hay **una**, y
sin declarar sigue habiendo **una**.

#### El segundo factor se podía poner y no quitar (04-11-2026)

`mfa_activo` se ponía a cierto en **un** sitio y no volvía a falso en ninguno.
Consecuencias, las tres medidas el mismo día:

1. **Ninguna pantalla daba de alta el segundo factor.** `POST
   /auth/mfa/iniciar` y `/mfa/activar` existían desde el principio y no los
   llamaba nadie, así que no había forma de configurarlo. Lo preguntó quien lo
   usa: «en ningún momento se ha dado de alta el doble factor, por lo menos
   ¿cómo lo doy de alta?».
2. **Activarlo era irreversible.** Perder el autenticador dejaba la cuenta
   inalcanzable con la contraseña correcta delante. La tabla de operaciones
   sensibles ya declaraba `cambio_mfa` —«Desactivar o reconfigurar el segundo
   factor»—: el guardia estaba escrito y la puerta no existía.
3. **La elevación de sesión no llegaba al navegador.** Las rutas que elevan
   —`/factores/comprobar`, y ahora `/mfa/activar`— devuelven un token nuevo
   porque la marca de «factor fuerte reciente» viaja dentro del token. Quien usa
   la API lo recoge; el navegador no podía, porque su sesión es una cookie que
   pone el gateway y el proxy devolvía el cuerpo sin tocarla. O sea que elevar
   la sesión servía dentro de `identity` y en ninguna otra parte.

Lo que hay ahora:

- `POST /auth/mfa/desactivar`, con `exige_reverificacion("cambio_mfa")` y
  negándose cuando el tenant exige MFA —quitarlo ahí dejaría a esa persona sin
  poder entrar, y eso se dice antes en vez de descubrirlo al día siguiente—.
- **Activar cuenta como demostrar.** Quien teclea un código válido de su
  autenticador ha probado el factor ahora mismo: `/mfa/activar` lo anota en la
  sesión y reemite el token. Sin esto quedaba un callejón sin salida: activas
  y, acto seguido, quitarlo contesta «vuelve a verificarte» sin que haya desde
  dónde.
- **El gateway refresca la cookie** cuando el servicio contesta
  `usar_este_token`. Genérico, sin lista de rutas: lo decide quien ha elevado.
- La tarjeta en **Puesto de trabajo**, que es la pantalla del acceso propio.

Y el rescate, para la cuenta que ya se quedó fuera:
`python scripts/cuenta_de_arranque.py --quitar-factor`. No da ningún poder
nuevo —quien lo ejecuta ya tiene el `.env`, o sea la contraseña— y es lo que
hace verdad otra vez la regla de que el fichero manda en cada arranque.

#### Pasar el sembrador dos veces dejaba dos copias

Su contrato es que pasarlo otra vez sea inofensivo, y se cumplía **sólo donde
la API rechaza el duplicado con un 409**. En las colecciones que no exigen
unicidad no choca nada: cada pasada añade una copia.

Medido comparando lo que declara con lo que hay, en una instalación sembrada
varias veces: **diez colecciones acumulaban**, y `claves-api` tenía 128 filas
para tres declaradas. No falla y no avisa; lo que queda es una pantalla
ilegible, y cada copia es una credencial de verdad.

Dos mecanismos, porque fallaban los dos:

- `crear(..., unico_por="campo")` mira antes de dar de alta. Se pide caso a
  caso **a propósito**: hay colecciones donde dos filas iguales son dos hechos
  distintos —dos movimientos de almacén del mismo repuesto— y volverlas
  idempotentes perdería el segundo.
- `asegurar(...)` miraba **después**: creaba y sólo buscaba al chocar, que es
  justo lo que duplica donde no hay 409. Ahora mira antes. Cuesta un listado
  por llamada y sólo cambia el resultado donde iba a duplicar.

Comprobado pasando el sembrado entero sobre una instalación ya sembrada: las
ocho colecciones medidas se quedan en el mismo número.

**Y la liberación del segundo factor pasa a un `finally`.** Estaba fuera a
propósito —«si revienta a medias, el fallo lo dice»— y era un mal cambio: lo
que queda entonces es una cuenta pidiendo un código que sólo existió dentro de
aquel proceso. Pasó dos veces el mismo día. Además se reintenta: entre el alta
del factor y el final pasan minutos, así que la ventana caduca, y el reintento
puede toparse con el freno del gateway si la pasada ha hecho muchas llamadas.

#### El sembrador no entra por una puerta sin vuelta

`sembrar_configuracion.py` perdía siete altas en cada pasada —tres políticas de
acceso y cuatro claves de API— porque esas operaciones exigen reverificación y
él entraba sólo con contraseña. Salían en el informe como «rechazadas por
diseño», que era verdad y dejaba esas pantallas vacías en toda instalación
sembrada.

Ahora se da de alta un TOTP, siembra y lo quita, dejando la cuenta como estaba.
Dos precauciones escritas en su sitio: **comprueba que la salida existe antes
de entrar** —si el despliegue no publica `/mfa/desactivar`, no activa nada y lo
dice— y **no toca el factor de quien ya lo tenía**.

#### Una respuesta con varias listas se pinta entera (04-11-2026)

El listado de un módulo saca sus filas sin que nadie se lo explique: si la
respuesta es un array, ése; si trae `items`, ése; y si trae **una sola**
propiedad que sea un array —`{partners: […]}`, `{ordenes: […]}`—, ésa. Con dos
no adivina, y hace bien: elegir mal enseñaría la lista equivocada.

Lo que faltaba por cerrar es **qué pasa entonces**, y lo que pasaba era peor
que esconder: pintaba una fila con el objeto entero, una columna por propiedad
y las filas de verdad apelotonadas dentro de una celda. Medido llamando a las
pestañas declaradas contra un servidor de verdad: **diez caían ahí**. «Entradas
sin atribuir» salía con tres columnas —«Interacciones», «Interlocutores
frecuentes», «Cuantas»— y cuatro interacciones dentro de la primera. El dato
estaba y no se podía leer.

Dos piezas, y ninguna adivina nada:

1. **`clave_lista`** en la pestaña dice cuál de las listas es su listado — el
   que lleva filtros, orden, paginación y exportación. Se declara **sólo**
   donde hace falta: las otras doscientas y pico pestañas no lo llevan.
2. **Las demás listas se pintan debajo**, cada una con su nombre, en su propia
   tabla. Declarar una sola habría perdido las otras, y varias importan: «Vencen
   pronto» trae `vencen_pronto` y `ya_vencidos`; «Transportes», cuatro
   catálogos de igual peso.

**El guardián va contra el servidor, no contra el contrato**, y eso no es una
preferencia: estas rutas devuelven `Any`, así que el OpenAPI no declara la
forma y un gate estático daría verde sin haber mirado nada — se escribió
primero así y pasaba con el caso malo plantado. Vive en
`test_las_pestanas_de_la_consola_contestan.py`, que ya abría cada pestaña una
por una: ahora además mira si lo que contesta se puede pintar como un listado.

Y un efecto que sólo se vio al sacarlos a pantalla: **el rótulo de un botón lo
escribe el `summary` del contrato, y 43 de los 2.452 llevan dentro el código de
la capacidad** — «Comprobar un contenido antes de mandarlo (CRM-02.04.01.03)».
En el OpenAPI está bien, que es donde lo lee quien integra y donde lo cita la
trazabilidad; en un botón es media mitad del rótulo diciendo algo que a quien
comprueba un contenido no le dice nada. Se quita **al rotular** (`comoRotulo`),
no en los servicios, justo para que siga estando en el contrato.

#### El botón de borrar dice lo que hace el DELETE (05-11-2026)

De las **124 operaciones DELETE** publicadas, muchas no borran: «Enviar una
cuenta a la papelera», «Revocar una clave», «Cerrar una sesión», «Dar de baja a
un usuario del tenant». Las trece fichas las rotulaban todas **«Eliminar»**, con
«Sí, eliminar» al confirmar: quien mandaba una cuenta a la papelera no sabía que
se recupera, y quien daba de baja a alguien creía que lo borraba.

Ahora `useEdicion` devuelve, además de si se puede, **qué hace**: el `summary`
de la operación DELETE que contesta a esa ruta, pasado por `comoRotulo`. Lo
usan el menú «Más» y la confirmación (`BotonesDeRegistro`, `ConfirmarBorrado`).
La operación se busca con `operacionDe` (`lib/superficie.ts`), la misma que ya
decidía el permiso, así que el rótulo y el permiso salen siempre de la misma
operación. «Eliminar» queda sólo cuando el contrato no dice nada.

**Un recurso puede callar su DELETE**, con `borrado_oculto_porque` en su
declaración de `recursos.ts` — un texto y no un sí/no, para que el siguiente
sepa que es a propósito. El único que lo usa es «Usuarios»: su DELETE desactiva
igual que «Dar de baja a un usuario», pero sin preguntar a quién pasan sus
registros, y dos botones para lo mismo es ofrecer el peor.

Y la ficha de un usuario **no abría**: el listado enlazaba cada fila y la ficha
pedía `GET /api/v1/usuarios/{usuario_id}`, que no existía — «Method Not
Allowed» y ninguna acción, «Dar de baja» incluida. La ruta existe ahora, va
**detrás** de `/usuarios/licencias` (declarada antes se quedaría con
«licencias» y contestaría 422) y lee por membresía, como el listado: `Usuario`
no lleva `tenant_id` y esa unión es lo que aísla. Las tres cosas —ficha, otro
tenant, licencias— las vigila `test_reverificacion_y_mfa_adaptativa.py`, y las
dos últimas se validaron plantando el fallo; el rótulo, en
`el_borrado_dice_lo_que_hace.test.tsx`.

#### Una fila sin ficha tiene su menú (05-11-2026)

Una ficha es algo que se lee: sin `GET /coleccion/{id}` no la hay. Dos fallos
salían de ahí, y se midieron cruzando las pestañas de `recursos.ts` con los
trece contratos:

- **Seis fichas que abrían en error.** `Modulo` enlazaba las filas de toda
  pestaña con `objeto` aunque el contrato no publicara cómo leer una (el
  respaldo `objeto ? "id"` cuando `fichaDe` no encontraba nada). Usuarios,
  productos, categorías de caso, planes preventivos, niveles de partner y
  aprobaciones de activos abrían en «No existe» o «Method Not Allowed». El
  respaldo se ha quitado: **enlaza el contrato, no `objeto`**. `objeto` sigue
  sirviendo para resolver referencias a nombres. Por lo mismo, el resultado de
  una acción sólo enlaza un `…_id` si su registro se puede leer. A usuarios sí
  se le ha dado su `GET`, porque «Dar de baja» necesita una ficha desde la que
  pulsarse.
- **Dieciséis pestañas con operaciones y sin puerta.** Revocar una clave de
  API, cerrar una sesión, quitar una política de acceso o una regla de
  enrutamiento, editar un riesgo o un control, levantar una supresión,
  desinstalar un conector… el servidor lo admitía y ninguna pantalla lo
  ofrecía. Ahora `operacionesDeRegistro` (`lib/acciones.ts`) saca del contrato,
  para la colección, las `POST` sobre el registro, el editar (`PATCH`, o `PUT`
  si es lo único) y el quitar (`DELETE`), cada una con su permiso, y la fila
  sin ficha las lleva en su menú. El formulario es el de siempre: `<Acciones>`,
  que ahora usa el método de cada operación en vez de `POST` fijo, y
  `FormularioDeEdicion`, que acepta la plantilla y el método.

Y una tercera forma de respuesta que el listado no reconocía: **un diccionario
de registros** (`{clave: {valor, origen, tipo…}, …}`). `comoFilas` lo convierte
en filas cuando son dos o más valores, todos registros y todos con la misma
forma, guardando la clave en la columna `clave`. Medido en vivo sobre las
pestañas: sólo «Ajustes» respondía así —los 91 umbrales salían como una fila de
91 columnas—; las otras siete respuestas de un solo objeto son resúmenes y
siguen pintándose como una fila.

#### Lo que se da de alta se puede cambiar (05-11-2026)

Cruzando las pestañas con los contratos: **treinta** admitían alta y ninguna
forma de cambio. Un producto no se podía renombrar ni retirar, una cola no
podía cambiar de miembros, un rol no podía cambiar de permisos.

- **Diecisiete eran un hueco y se cerraron.** Catorce con `montar_ficha`
  (productos, niveles de partner, planes preventivos, categorías de caso, roles,
  reglas de compartición, vistas federadas, sitios embebidos, delegaciones de
  firma, modelo canónico, dispositivos, proveedores de servicio y de firma,
  relaciones entre objetos). Ninguno tiene borrado lógico, así que reciben ver y
  editar y no borrar: retirar es desmarcar `activo`, que no deja referencias
  colgando. Donde un campo lo pone el sistema —la última lectura de un
  dispositivo, el resultado de probar un proveedor de firma, la última
  ejecución de un plan— queda fuera de `editable`, y en una relación sólo se
  edita lo que no cambia la forma de los datos. **Colas y tablas del almacén**
  llevan un `PATCH` por clave escrito a mano, porque su `GET /{clave}` ya
  existía y es la ruta por la que se abren.
- **Trece lo son a propósito**, y cada una lo dice en la tabla de excepciones de
  (`test_lo_que_se_crea_se_puede_cambiar.py`): históricos (movimientos de
  almacén, transferencias internacionales, consultas, mediciones), versiones
  publicadas (definiciones de proceso, SLA, plantillas de IA, modelos) y lo que
  se reescribe declarándolo otra vez por clave (residencia, guardarraíles,
  perfiles de industria).

Dos defectos más salieron al abrirlas:

- **Una ruta tapada por otra con la misma forma.** La ficha genérica de tablas
  del almacén (`/tablas/{tabla_analitica_id}`) nunca habría contestado: ya
  existía `/tablas/{tabla}`, que lee por clave. Lo vigila ahora
  `test_una_ruta_con_nombre_no_queda_tapada.py`, que pide **cada operación del
  contrato** con un identificador de ejemplo y comprueba que la contesta su
  propia ruta. Pregunta a la aplicación con su propio emparejamiento: desde
  FastAPI 0.139 cada router incluido va envuelto, y recorrer las rutas a mano
  daba cero miradas y verde.
- **Una lectura que es una lista.** `GET /colas/{clave}` devuelve lo que espera
  en la cola. La ficha lo pintaba campo a campo por posición; ahora una lista se
  enseña como tabla y la ficha no ofrece «Editar», que no tendría con qué
  rellenarse (la cola se edita en línea desde su lista). Y un parámetro con
  nombre propio que la fila no trae es su `clave`: el enlace caía al `id` y
  daba 404.

#### El portal del integrador, con sus llamadas (05-11-2026)

`CRM-00.02.04.06` tenía el cálculo del panel y ningún dato: recibía las llamadas
de quien preguntaba. Ahora:

- **El gateway apunta** cada petición hecha con clave de API (ruta, método,
  estado, duración, `X-Request-Id`) en memoria (`services/gateway/llamadas.py`)
  y las manda a identity **por lotes**: al llegar a `CLAVES_LLAMADAS_LOTE`, y
  cada `CLAVES_LLAMADAS_INTERVALO_S` aunque no haya más tráfico —una tarea que
  arranca con el gateway—, y al pararlo, lo que quede. Si identity no contesta,
  el lote se pierde **y se registra** (`gateway.llamadas_no_guardadas`, con el
  total perdido desde el arranque): reintentar sin fin haría crecer la memoria
  del gateway justo cuando el sistema ya va mal.
- **Identity las guarda** en `llamadas_clave_api` (ruta interna firmada
  `POST /claves-api/llamadas`) y purga lo anterior a `CLAVES_LLAMADAS_DIAS`.
- **Cuota mensual por clave** (`cuota_mes`, opcional): al validar la clave se
  cuentan sus llamadas del mes UTC y, gastada, contesta **429 `cuota_agotada`**
  con `Retry-After` hasta el día 1. El gateway lo devuelve tal cual, con el
  formato de error de la casa; no lo convierte en 401, que haría revisar una
  clave que está bien. La validación se cachea `CLAVES_TTL_CACHE_S`, así que la
  cuota puede pasarse en lo que dura esa caché, nunca más.
- **Pantalla**: en *Claves de API*, cada fila tiene *Qué ha hecho esta clave
  este mes…* (`POST /claves-api/{id}/panel`) y *Cambiar la cuota mensual*.
- El cálculo del panel se movió a `crmcore.portal_desarrollador`; el gateway lo
  sigue ofreciendo para quien trae sus propias llamadas.

Pruebas: `test_portal_del_integrador.py` (lote y purga, panel separado por
culpa, 429 de cuota, el 429 no llega como 401, lotes por tamaño y vaciado sin
tráfico), validadas plantando cada fallo. Al escribirla salió que la purga no
veía las filas del propio lote —la sesión de sistema no vuelca sola—: corregido.

#### Compras al proveedor: los cálculos con datos (05-11-2026)

Once capacidades de coste y de proveedor eran funciones puras a las que quien
llamaba les daba los hechos. Se pasaron a «en curso» por eso, y se cerraron
construyendo los datos:

- **Dónde:** `services/party/compras.py` (modelos y lógica) y
  `services/party/api_compras.py` (rutas bajo `/api/v1/compras`, prefijo
  enrutado a `party` en `crmcore.rutas_de_api`). En `party` porque el proveedor,
  su homologación y sus papeles viven ahí, y la comparación los lee a la vez que
  las respuestas.
- **Siete tablas** (migración `party/20261105_1023_compras_al_proveedor`):
  `peticiones_oferta`, `respuestas_oferta` (con adjudicación, entrega, coste final
  e incidencias), `capacidades_proveedor`, `reservas_capacidad`,
  `acuerdos_rappel`, `contratos_proveedor` y `alcances_proveedor`.
- **Los cálculos no se reescribieron**: `sales/coste.py` y
  `sales/proveedores_comercial.py` se movieron a `crmcore.costes` y
  `crmcore.proveedores_comercial` —son puros— y los usan ventas y party.
- **Pantallas**: siete pestañas genéricas en *Proveedores*, con
  `montar_listado` + `montar_ficha`; las acciones salen del contrato. La ficha
  del proveedor (que es la de cuenta) ahora añade las acciones de
  `/proveedores/{id}/…` cuando la cuenta tiene ese rol (`accionesDeLaCuenta`).
- **Ajustes nuevos**: `COMPRAS_DIAS_PROPIOS_ENTREGA` y
  `RIESGO_CONCENTRACION_PCT`, que eran un 2 y un 40 escritos en los cálculos.
- **Sembrador**: `--parte compras`, que se puede repetir sin duplicar.

Pruebas: `test_compras_al_proveedor.py`, de punta a punta por HTTP y validada
plantando el fallo (homologación ignorada, rappel al coste ofertado).

#### El código del tenant, ejecutado de verdad (05-11-2026)

`CRM-00.04.02.01`, `.04`, `.05`, `.06` y `.07` eran calculadoras sin ejecución.
Ahora:

- **Motor** (`services/automation/motor_js.py`). JavaScript en QuickJS
  (quickjs-ng) compilado a WASI por su proyecto y ejecutado por **wasmtime**
  (`wasmtime==50.0.1`). Se eligió frente al paquete `quickjs` de PyPI, que no
  publica desde 2023, porque es la pieza que aísla código ajeno. El binario no
  va en el repositorio (1,5 MB; el gancho corta en 512 KB): está fijado en
  `services/automation/motor_js.lock.json` (versión, URL, SHA-256), lo trae
  `scripts/traer_motor_js.py` —lo llaman `setup.sh` y la etapa de construcción
  de la imagen, que lo deja en `/opt/motor`— y se comprueba la huella al
  cargarlo: si no cuadra, `extension.motor_no_disponible` y no se ejecuta nada.
  `GET /extensiones/motor` dice si está listo y con qué topes.
- **Aislamiento.** WASI sin directorios abiertos, sin entorno y sin red. El
  envoltorio le quita `std` y `os` antes de su código, recoge `console.*`
  aparte y escribe una línea de resultado. Topes por ejecución, todos en
  ajustes: combustible (`EXTENSIONES_COMBUSTIBLE`, instrucciones de WebAssembly;
  unas 8.000 millones por segundo en un M-series), memoria
  (`EXTENSIONES_MEMORIA_MB`), reloj (`EXTENSIONES_TIEMPO_MS`), entrada, salida y
  líneas de log. **El reloj** va por épocas: un único hilo avanza la época del
  motor cada `EXTENSIONES_RELOJ_MS` (10 ms de serie) y cada ejecución pide que la corten pasadas las suyas —si
  cada una avanzara la época al pasarse, cortaría a las demás—. Los errores de
  sintaxis y ejecución salen con la línea del código del tenant, no la del
  envoltorio.
- **Datos** (`services/automation/codigo_tenant.py`, cinco tablas):
  `extensiones` (clave única por tenant, origen, permisos, versión activa),
  `versiones_extension` (inmutables: código, huella, versión de motor, firma,
  estado y revisión), `firmantes_extension` (clave pública Ed25519),
  `ejecuciones_extension` (tiempo, combustible, si se cortó y por qué, error,
  logs, entrada, acciones, coste; se purga a `EXTENSIONES_EJECUCIONES_DIAS`) y
  `endpoints_propios`.
- **Acciones.** La función devuelve `{acciones: [{metodo, ruta, cuerpo}]}` y se
  hacen con `crmcore.http.interno.invocar` con los permisos de la extensión,
  hasta `EXTENSIONES_ACCIONES_MAX`, nunca sobre `/api/v1/extensiones` ni
  `/api/v1/propios`. En `/probar` se enseñan y no se hacen.
- **Cuota** `cuota_extensiones_mes` con `crmcore.cuotas.exigir`, y el medidor
  `extensiones` en el panel de consumo. Coste atribuido:
  `EXTENSIONES_COSTE_POR_SEGUNDO`.
- **Firma.** Ed25519 sobre la huella SHA-256 (en hexadecimal) del código, con
  la clave pública de un firmante activo del tenant. Una de tercero queda
  `pendiente_revision` y sólo se activa tras la revisión de alguien distinto de
  quien la publicó.
- **Endpoints propios.** `"propios": "automation"` en `crmcore/rutas_de_api.py`;
  la ruta `/{ruta:path}` de `api_codigo.py` resuelve el endpoint por método y
  ruta, exige el permiso que declara y ejecuta en un hilo. Un fallo se
  **contesta** (502 `extension.fallo`), no se lanza: lanzarlo deshacía la
  transacción y con ella el apunte de la ejecución fallida. Exenta del gate de
  permiso en el decorador, con motivo, porque el permiso es por endpoint.

Lo que **no** hace: no hay llamadas salientes desde una extensión (no se le da
red), ni librerías de fuera, ni ejecución disparada por una automatización o
un evento; se ejecuta desde su ficha y desde sus endpoints.

#### Extraer los datos de un contacto de un texto, hasta la ficha (05-11-2026)

`POST /contacts/{id}/extraer-de-texto` (party) lee el contacto con los permisos
de quien pide y manda a `/ia/extraer` el texto pegado, los campos que se buscan
—los de `comandos.CAMPOS_CONTACTO` salvo `campos` y preferencias: tratamiento,
cargo, departamento, teléfonos, otro correo, idioma— y sus valores actuales. Lo
extraído queda **pendiente** en «IA → Campos extraídos»
(`/ia/extraidos`), cada uno con su cita y su confianza. Aceptar emite un
**comando** `actualizar` que aplica el servicio dueño.

Al seguir ese camino hasta la ficha salió la familia de comandos rota:

- **No había manejador de contacto** en party: aceptar un dato de un contacto
  no hacía nada. Ahora `_actualizar_contacto`, con la misma normalización que la
  ficha (teléfonos a E.164, correo) y sin nombre ni correo principal, que son la
  identidad y la clave canónica.
- **Aceptar mandaba todo dentro de `campos`**: un `cargo` acababa como campo
  personalizado. Ahora un campo propio va como tal y uno personalizado se nombra
  `campos.<clave>`.
- **`campos` se asignaba entero**: tocar uno borraba los demás, en party y en
  sales. `crmcore.bus.comandos.aplicar_cambios` los fusiona.
- **`updated_origen` es `VARCHAR(32)` y se escribía
  `automatizacion:<id>` (51)**: todo cambio por comando con origen reventaba —
  también las reglas que actualizan cuentas, leads y oportunidades—. Ahora va la
  categoría del origen (`origen_de_cambio`), y el identificador sigue en el
  comando. Probado de la propuesta a la ficha en un proceso
  (`test_ia_desde_la_ficha.py`).

#### El índice de conocimiento, con pgvector (05-11-2026)

`CRM-04.03.01.04` (casos parecidos) y `CRM-05.02.02.03` (respuesta con cita)
filtraban resultados que «llegaban ya buscados»: no había índice. Decidido por
el usuario: **pgvector en Postgres**, porque los vectores van en una tabla con
`tenant_id` y el RLS los aísla igual que al resto.

- **Infraestructura.** `docker-compose.yml` usa `pgvector/pgvector:0.8.6-pg16`
  fijada por huella; `deploy/crear-bases.sh` crea la extensión `vector` (exige
  superusuario); la migración de intelligence la crea con `IF NOT EXISTS` para
  la pila local y el `conftest` de pruebas también (el `pgserver` embebido trae
  pgvector 0.6). Librería `pgvector==0.5.1`.
- **Tabla** `indice_conocimiento` (`services/intelligence/indice.py`): fuente
  (`articulo`, `caso_resuelto`), referencia, título, texto (recortado a
  `IA_CARACTERES_POR_FRAGMENTO`, y lo dice), permiso de la fuente, huella del
  texto, modelo y vector sin dimensión fija. Sólo se comparan vectores del mismo
  modelo; si el texto y el modelo no cambian, no se recalcula ni se paga.
- **Vectores** del proveedor que el enrutador elija para el uso `embeddings`
  (`dialectos.peticion_incrustar`: Gemini `batchEmbedContents` y OpenAI
  `/embeddings`), con `IA_DIMENSIONES_VECTOR`.
- **Se llena solo** con `knowledge.published` y `case.closed` (consumidores de
  intelligence: leen el texto del servicio de soporte por su ruta) y, para lo
  anterior o lo que falló, con *Indexar para la IA* en la base de conocimiento
  (`POST /conocimiento/articulos/indexar-ia`, que empuja a `/ia/indice/indexar`).
  En la pila local sin Redis el bus no reparte: ahí sólo entra reindexando.
- **Consultas**: `POST /ia/indice/buscar` (recorta a lo que quien pregunta puede
  ver), `GET /ia/indice` (qué hay), `POST /sugerencias-caso/{id}` busca solo si no
  le dan resultados, `POST /casos/{id}/parecidos`, y
  `POST /conocimiento/articulos/preguntar` (busca y contesta con cita).

Lo que salió al probarlo con Gemini, corregido:

- El filtro de sugerencias comparaba el permiso **como texto** con la lista del
  agente: quien tenía `*:*` o `case:*` lo veía todo «sin permiso». Ahora se
  resuelve con `principal.tiene`.
- `sugerir_respuesta` y `conversar` leían `texto` y `fuentes` de
  `rag.responder`, que devuelve `respuesta` y `citas`: la sugerencia y el
  asistente salían **siempre vacíos**. Sólo había prueba del caso sin artículos.
- La sugerencia de respuesta buscaba artículos con un `LIKE` de la frase entera
  del asunto; ahora usa el índice, y declara los artículos con
  `knowledge:read` (antes `case:read`).

#### La IA desde la ficha (05-11-2026)

Las capacidades de `intelligence` (`/ia/generar`, `/ia/asistencia/*`,
`/ia/conversacion/*`) recibían los hechos de quien llamaba, así que ninguna
ficha podía pedirlas. Ahora cada servicio dueño del registro tiene la acción en
SU ruta —y por eso sale sola en el menú de la ficha— y reúne los hechos:

| Ruta | Servicio | Pide a intelligence |
|---|---|---|
| `POST /accounts/{id}/resumen-ia` | party (lee `/accounts/{id}/360`) | `/ia/asistencia/resumen-cuenta` |
| `POST /contacts/{id}/redactar-correo` | party | `/ia/generar` `redactar_correo` |
| `POST /opportunities/{id}/proximos-pasos-ia` | sales (señales propias) | `/ia/asistencia/proximos-pasos` |
| `POST /casos/{id}/resumen-ia` | service | `/ia/generar` `resumen_caso` |
| `POST /casos/{id}/respuesta-sugerida` | service (artículos internos) | `/ia/asistencia/respuesta-soporte` |
| `POST /conversaciones/{id}/resumen-ia` · `/intencion` · `/traducir` | service | `/ia/conversacion/resumen` · `/senal` · `/ia/generar` `traducir` |

`crmcore.ia_ficha` lee y pide **con la identidad de quien pulsa** (permisos y
roles por `invocar`): la lectura pasa por la máscara de campos y los
guardarraíles de `intelligence` comprueban sus permisos. Todas exigen `ia:usar`.
Los errores del otro lado vuelven con su estado.

Lo que salió al probarlo con Gemini, y está corregido:

- **Plantillas de serie** (`services/intelligence/plantillas_de_serie.py`): un
  tenant no tenía ninguna. La primera vez se guardan como su versión 1 con
  idioma vacío, para que sigan el del usuario o tenant en cada llamada.
- **Idioma**: un resumen sin idioma usa el de quien lo lee y, si no hay, el
  ajuste nuevo `IDIOMA_DEFECTO` (que sustituye un `"es"` escrito en i18n). La
  redacción y la traducción siguen exigiéndolo.
- **Los hechos como contexto, con su permiso**: el resumen de cuenta los mandaba
  sólo como datos de plantilla y el mínimo de contexto no le dejaba llamar
  nunca; y un fragmento sin `permiso` lo descarta el guardarraíl.
- **El resumen de conversación inventaba**: mandaba los mensajes sin permiso,
  se quitaban todos y se llamaba al modelo con la transcripción vacía. Ahora
  declaran `case:read` (o el que traigan) y sin mensajes no se llama. Tres
  pruebas pasaban por ese camino con un principal sin `case:read`; corregidas.
- **Opt-out por contrato**: Gemini no tiene campo de petición para «no
  entrenes». `config.opt_out_contrato` en el proveedor —la referencia del
  acuerdo— hace válida la garantía sin campo; sin campo ni contrato, se para.
- La IA de la conversación sale en `Conversacion.tsx` como botones; la de
  oportunidad y caso, en el menú de sus fichas propias, que hasta hoy no
  enseñaban ninguna acción del contrato. Ajustes nuevos:
  `IA_MENSAJES_PARA_RESUMEN`, `IA_ARTICULOS_POR_SUGERENCIA`.
- Paquete del front: `Consola` ya no va en la apertura (127,07 → 121,93 kB) y
  el tope por pantalla pasa de 12 a 13 kB por el crecimiento de `Modulo`,
  medido y explicado en `test_front_oficial.py`.

#### Sandboxes: la copia de un tenant a su entorno de pruebas (05-11-2026)

`CRM-07.02.01.02` tenía el plan de copia y la anonimización como cálculos
sueltos y ninguna copia. Ahora un sandbox es **un tenant hijo** con su fila en
`tenancy.sandboxes` (propósito, porcentaje, si anonimiza, quién lo pidió,
caducidad y el resultado de la copia), y la copia la hace cada servicio sobre
su esquema:

- **Orquesta `tenancy`** (`services/tenancy/sandboxes.py::copiar`, en segundo
  plano tras `POST /sandboxes/{id}/copiar`): pregunta a identity por los
  usuarios del tenant —son globales y no se traducen— y llama a la ruta interna
  firmada `POST /api/v1/{servicio}/sandbox/copiar` de los trece servicios
  (`crmcore/http/sandbox_router.py`, montada en todos por la factoría). Guarda
  por servicio lo copiado, lo que no se copió y por qué, y lo que falló; un
  servicio que no contesta sale con su nombre y el sandbox queda `con_avisos`.
- **El motor es `crmcore/datos/copia_sandbox.py`**. Todo lo que decide es
  determinista, y por eso cuadra sin que los servicios se hablen: el
  identificador nuevo es `uuid5(semilla del sandbox, original)`, así que una
  oportunidad de `sales` sigue apuntando a la copia de su cuenta de `party`; la
  muestra parcial es por cuenta (hash de su id) y se lleva lo que tiene
  `cuenta_id`; lo que no cuelga de una cuenta —catálogo, configuración— se copia
  entero. Cada tabla va en su punto de guardado: una que falla se cuenta y las
  demás siguen. Inserta por lotes de `SANDBOX_COPIA_LOTE`, recortado en tablas
  anchas para no pasar el tope de 65.535 parámetros de Postgres.
- **No se traduce** lo que apunta a algo global: una clave ajena a una tabla
  sin `tenant_id` (usuarios, manifiestos de conector) sigue apuntando al mismo.
  Sale de las claves del modelo, no de una lista.
- **No se copia** una tabla con alguna columna `info={"secreto": True}`: claves
  de API, credenciales, secretos de webhook. Sale en el resultado con su motivo.
- **Se anonimiza** lo que el modelo declara: sensibilidad `personal`,
  `especial` o `confidencial`, **y** la marca nueva
  `info={"anonimizar_en_copias": True}`, que es sólo para copias y no cambia lo
  que cada rol ve en la aplicación (la máscara por rol lee la sensibilidad).
  Lleva la marca lo que identifica a alguien en los registros de clientes:
  nombres, cargos, webs, asuntos, cuerpos, descripciones, notas, comentarios,
  claves canónicas y huellas de identidad (85 columnas). El sustituto respeta
  el tipo (`crmcore/seguridad/anonimizar.py::_sustituto`): seudónimo en texto,
  recortado al largo de la columna; otro UUID estable en identificadores; y lo
  demás —importes, números, JSON— se suprime: nulo si se admite, el neutro del
  tipo si no.

Lo que la copia **no** hace, dicho:

- Los identificadores escritos **dentro de un JSON** no se traducen.
- Las tablas comunes de `crmcore` —comentarios, adjuntos, notificaciones, el
  índice de búsqueda, la auditoría— no se copian: el motor toma los modelos de
  `services.<servicio>`. El buscador del sandbox empieza vacío.
- Una columna de texto que identifica a alguien y **no** tiene marca pasa en
  claro. Al añadir una a un registro de clientes, ponerle
  `anonimizar_en_copias` (o su sensibilidad) es parte del cambio.
- La resolución de identidad no casa en el sandbox: sus huellas van
  anonimizadas.

**El alta de un tenant desde la sesión de otro.** Al construirlo salió un fallo
que no era del sandbox: provisionar escribe filas **del tenant nuevo** (cuotas,
localización, el primer apunte de su cadena) desde la sesión de quien lo pide.
En la sesión de un tenant, el guard del ORM añadía `tenant_id = el_que_pide` a
la consulta del último apunte y dos apuntes tomaban la secuencia 1 (409 en
`ix_auditoria_tenant_secuencia`). Y **con un rol sin privilegios, el alta de
tenants desde la plataforma también fallaba**: el GUC del RLS se queda con el
tenant del administrador y el `WITH CHECK` rechazaba la fila de `auditoria` del
nuevo. La pila local no lo enseñaba porque conecta como superusuario. Lo
resuelve `crmcore.db.session.escribir_como(db, tenant_id)`: cambia el tenant de
la sesión, el GUC y el contexto mientras se escribe lo del nuevo, y lo devuelve
todo al salir. Prueba con el rol de aplicación en
`tests/integration/test_rls_aislamiento.py`.

La misma familia, cerrada en el mismo cambio: **todo lo de tenancy que escribe
para otro tenant** pasa por `escribir_como` —cambiar su estado (suspender,
reactivar, dar de baja; «Apagar» un sandbox también daba 409), propagar su
localización al editarlo, aplicarle las cuotas del plan y declarar su
aislamiento—. Antes, la localización y las cuotas cambiaban sólo el contexto,
que dice de quién es el apunte pero no lo que miran el guard y el RLS.

#### Capacidades sin pantalla: medir antes de citar (05-11-2026)

El guardián de pantallas cuenta **citas**, no alcance, así que bajar su tope
exige pulsar antes. De 194 se pasó a 122 en tres pasos, contados aparte en su
histórico: 41 que no son pantalla —gates, protocolos, aislamiento, relevos
internos y API para otros frontends— llevan ahora su motivo en el catálogo
(`sin_pantalla_porque`); 29 que sí la tenían se citaron tras recorrerlas en el
navegador; y dos que no la tenían ahora sí (quitar un módulo, en su ficha). Al
quitar las 41 del recuento, el suelo de cordura del guardián bajó de 700 a 600
capacidades miradas, con el motivo escrito al lado.

Recorriendo salió un defecto de formato: `validar_manifiesto` aceptaba
secciones en la raíz del manifiesto y `instalar` sólo lee `contenido`, así que
el módulo se instalaba vacío; la ficha leía la raíz. Ahora las dos leen
`contenido` y la validación rechaza las secciones fuera de sitio
(`metadata.seccion_fuera_de_contenido`) y el módulo vacío
(`metadata.modulo_vacio`).

Pruebas: `una_fila_sin_ficha_tiene_su_menu.test.ts` y dos casos nuevos en
`una_respuesta_con_dos_listas_se_pinta_entera.test.ts`, validadas plantando el
fallo (sin la rama del `PUT`, sin el filtro de permiso, sin codificar la clave,
sin comparar la forma).

### 4.6.16 El chat en vivo perdía lo escrito durante el corte

`CRM-06.02.02.07` promete «entrega en vivo por SSE, **con reconexión y
recuperación de lo perdido por cursor**». La reconexión funcionaba —la hace el
navegador solo— y la recuperación no existía:

- el servidor aceptaba `?desde=` y **ningún cliente lo mandaba**;
- no emitía línea `id:`, así que el `Last-Event-ID` que el navegador envía al
  reconectar **no lo honraba nadie**;
- y **ninguna prueba cubría el parámetro**.

El resultado: al cerrar la tapa del portátil, el flujo se reabría en `now()` y
todo lo escrito durante el corte no llegaba nunca. No falla y no avisa — a la
conversación le faltan mensajes y quien mira cree que nadie ha escrito.

Se arregla **usando el protocolo en vez de inventar uno**: cada evento sale con
`id: <instante>`, que es exactamente el cursor con el que se sigue leyendo, y
al volver se honra `Last-Event-ID`. El `EventSource` de siempre se recupera
solo, sin una línea de código en el cliente. `desde` sigue mandando sobre la
cabecera: quien lo pasa a mano está pidiendo una posición concreta, no una
reanudación. Y un `Last-Event-ID` ilegible se ignora en vez de tumbar el flujo:
reventar ahí sería dejar sin chat justo a quien está volviendo.

**Cómo se prueba un flujo que no termina.** No con un cliente HTTP: este
endpoint hace `db.rollback()` entre vueltas —a propósito, para no reservar una
conexión de Postgres por persona conectada— y dentro de la transacción de una
prueba ese rollback se lleva por delante el escenario, con lo que la prueba
espera para siempre unos mensajes que acaba de borrar ella misma. Se tira del
generador y se pide **la primera tanda**, que es anterior al primer rollback,
con plazo duro. Este flujo ya ha colgado dos barridos de este repositorio.

La prueba lleva **el caso malo dentro**: con cursor llega lo del corte, sin
cursor no llega nada. Afirmar sólo lo primero no distinguiría entre honrar el
cursor y mandarlo todo siempre.

Y cuatro cosas del chat que el servidor servía —con dieciocho pruebas de punta
a punta— y no alcanzaba ninguna pantalla: **buscar** (sólo en las
conversaciones propias, acotado en el servidor), **quién está** con su «visto
por última vez», **qué decía antes** un mensaje editado, y **quién hay** en la
conversación antes de escribir algo delicado.

**De paso, un punto ciego en un gate.** El trinquete que exige que toda ruta de
la que una pantalla declara la forma esté recorrida por una prueba de servidor
cortaba la ruta en la primera comilla de una f-string:
`f"/api/v1/chat/mensajes/{mensaje['id']}/versiones"` le salía como
`/api/v1/chat/mensajes/{mensaje[`. Pedía una prueba para algo probado desde
hacía meses — y un punto ciego así es peor que una regla que falta, porque
manda a escribir una prueba duplicada y sigue en rojo cuando se escribe.
Arreglado en el patrón, no vaciando las llaves de todo el fichero: eso se probó
primero y dejó fuera siete rutas que sí estaban recorridas.

### 4.6.17 El reparto de una comisión se escribía y no lo leía nadie

Dos capacidades de ventas estaban declaradas hechas, escribían su tabla y
**nadie podía leerlas**: el reparto de crédito entre comerciales
(`CRM-03.01.01.08`) y el enlace con la renovación o el upsell
(`CRM-03.01.01.11`). Las dos tablas sólo las consultaba su propio escritor,
para reemplazar filas. Ninguna ruta las devolvía.

Es el peor de los fallos silenciosos de este sistema: quien declara el reparto
se va creyendo que está hecho, y a quien le toca cobrar no puede mirarlo hasta
que llega la liquidación.

`GET /api/v1/ingresos/de/{oportunidad_id}` cierra las dos a la vez, porque se
miran juntas: delante de una venta las preguntas son «¿quién se lleva esto?» y
«¿de qué viene y qué sale de aquí?». Dos decisiones del contrato:

- **el total del crédito viene calculado y con un sí o no de si cuadra.** Un
  reparto al 60/60 cuadra hacia arriba y el descuadre lo encuentra finanzas
  tres meses después. Dejar que lo sume cada pantalla garantiza que una de
  ellas no lo sume;
- **el overlay no entra en esa suma**, y se dice por qué: es apoyo que no resta
  al titular, así que un overlay al 100 % no descuadra nada. Meterlo haría que
  un reparto correcto saliera al 150 %;
- y cada relación lleva **de qué lado está ésta**. Sin el sentido,
  «renovación» no dice si ésta es la que se renueva o la que renueva a otra, y
  en el informe de crecimiento son cosas opuestas.

**La ficha de una oportunidad**, con el mismo reparto que la del cliente —dos
pantallas que enseñan el mismo tipo de cosa lo colocan igual—. Enseña qué se
vende, lo que vale, quién decide y a quién no se ha visto, quién se lleva la
comisión, de dónde viene la venta y qué se ha movido.

**El ARR no se calcula en la pantalla.** Las líneas se mandan al servicio que
sabe qué cuenta como recurrente y se pinta lo que vuelve. Calcularlo en el
cliente dividiendo el total entre los años mete la implantación dentro —y la
métrica con la que se valora una empresa sale inflada—, además de dejar dos
sitios donde se calcula, que acaban diciendo cosas distintas. Va con **lo que
ha dejado fuera**: un «ARR 120.000» sin decir que la implantación no cuenta es
el número que acaba en una valoración y que nadie vuelve a mirar.

Tiene pantalla propia y no la ficha genérica por un motivo mecánico: tres de
sus paneles leen rutas de **otro prefijo** —`/ingresos/…`, `/forecast/…`— y la
ficha genérica descubre sus paneles por prefijo común, así que no los vería.

### 4.6.18 Un periodo de previsión es un número que alguien defiende

El módulo listaba los periodos y ahí se acababa. Y un periodo de previsión es
lo contrario de una fila: es **un número que alguien lleva a un comité**. Lo
que hace falta para defenderlo no se alcanzaba desde ninguna pantalla.

| Qué contesta | De dónde sale |
|---|---|
| Quién tocó el número y con qué motivo | `GET /forecast/periodos/{clave}/ajustes` |
| **Si esos ajustes acercaron o alejaron del real** | `GET …/acierto-ajustes` |
| Cómo íbamos hace tres semanas | `GET …/instantaneas` |
| Cuánto se ha movido, y qué se empujó dos veces | `GET …/deslizamiento` |
| Por producto, familia o tipo de ingreso | `GET …/desglose?por=` |

Tres cosas que son la diferencia entre un panel y un volcado:

- **El acierto de los ajustes es el panel incómodo, a propósito.** Un
  responsable que ajusta siempre hacia arriba y acierta **menos** que el número
  bruto está empeorando la previsión, y no se entera nadie: al cerrar el
  trimestre se compara el real con el objetivo, no con lo que se habría
  previsto sin tocar nada. Por eso la ruta devuelve **los dos errores** y no
  sólo el del número ajustado.
- **Las empujadas más de una vez van aparte.** Una fecha que se mueve dos
  trimestres seguidos no es un retraso: es una venta que no existe. Dentro del
  total de «oportunidades con cambio de fecha» se confunde con la que se movió
  una semana.
- **Lo que no se ha podido convertir no cuenta como cero**, y el aviso se pinta
  pegado al número. Un total al que le faltan importes en silencio es peor que
  uno que avisa, porque nadie lo cuestiona. Igual en el desglose: si falta una
  familia entera por un tipo de cambio que no estaba, se dice — si no, se lee
  como «esa familia no vendió nada».

Se abre **por clave** y no por identificador, como el objeto del modelo: sus
rutas hijas se dirigen por la clave del periodo.

**Y una regla de estilo que es de contrato.** En esta pantalla cada ruta se
escribe entera en su llamada, en vez de componerla de una variable `base`. No
es repetición por gusto: el gate que exige que toda ruta de la que una pantalla
declara la forma esté recorrida por una prueba de servidor **lee el código**, y
de `` `${base}/ajustes` `` no puede saber qué ruta es. Un contrato que no se
puede leer no se puede vigilar, y el gate pasó de señalar cinco rutas falsas a
señalar las cinco de verdad en cuanto se escribieron enteras.

### 4.6.19 Las excepciones de territorio caducaban sin que nadie pudiera verlas

Otra que se escribía y no leía nadie. `POST /territorios/excepciones` saca una
cuenta de su territorio por decisión, el resolutor la lee al asignar —así que
**funciona**— y ninguna ruta la devolvía. «¿Por qué esta cuenta es de Ana y no
de la zona norte?» sólo se contestaba mirando la base de datos.

Y es peor que un listado que falta, porque **caducan**: con `hasta` puesto
dejan de aplicarse ese día sin avisar a nadie. La cuenta vuelve a su territorio
de origen un lunes y quien la llevaba se entera por el pipeline. Por eso
`GET /territorios/excepciones` cuenta aparte las que vencen en treinta días o
menos, y marca cuáles no tienen fecha: sin esa distinción, un arreglo temporal
y una decisión firme se ven igual en una lista.

Por defecto sólo las vigentes. Una excepción vencida no explica nada del
reparto de hoy, y mezclarlas haría que alguien leyera el motivo de una
excepción muerta como la razón de que una cuenta esté donde está. Las vencidas
se piden con `?incluir_vencidas=true`, que hace falta para explicar un reparto
del pasado.

**La pantalla del mapa**, cuyo panel principal es el simulador. De lo que
devuelve, lo que decide no es cuántas cuentas cambian de dueño: son las que se
quedan **sin territorio** y los **solapes** —dos territorios con la misma
prioridad—, que producen una asignación dependiente del orden alfabético que
nadie busca hasta que dos comerciales discuten. Las prioridades repetidas se
señalan en la propia lista de territorios, que es donde se arreglan.

Las cuentas las manda la pantalla porque el servicio de territorios **no lee la
tabla de cuentas**: vive en otro servicio y ninguno lee el esquema de otro.

Y las cuotas van en la misma pantalla: el territorio decide de quién es una
cuenta y la cuota decide cuánto tiene que vender quien lo lleva. Mirar una sin
la otra es cómo se reparte un mapa que nadie puede cumplir. El objetivo
prorrateado sale **con el del plan al lado**: quien entra el día 20 no tiene la
cuota entera, y sin los dos números delante uno de ellos parece un error.

### 4.6.20 Una comisión que no se puede desglosar no se la cree nadie

El listado de liquidaciones enseñaba el total y el estado. Delante de una
liquidación la pregunta no es cuánto: es **por qué ese número y no otro**. Un
comercial que no puede desglosar su comisión no se la cree, y la discusión
acaba en una hoja de cálculo paralela que nadie concilia.

El servidor lo guardaba entero desde el primer día y no lo leía ninguna
pantalla: cada línea con su **base, su porcentaje y su explicación**, lo
recortado por el tope, las reversiones y las reclamaciones con su resolución.

Tres avisos que cambian la conversación, y por eso tienen prueba propia:

- **Lo recortado por el tope va arriba.** Una liquidación con techo aplicado
  parece simplemente más baja, y quien la cobra no tiene forma de saber que le
  han quitado algo: «he vendido menos» y «he llegado al techo del plan» son dos
  conversaciones distintas y sólo una se puede negociar.
- **Las reversiones se marcan.** Una línea negativa sin decir de qué
  liquidación viene se lee como un error de cálculo, y eso convierte una
  devolución legítima en una discusión.
- **Una reclamación sin resolver se dice.** Abierta y resuelta se ven igual si
  sólo sale el motivo, y sin la resolución la misma reclamación vuelve el
  trimestre siguiente.

**No se edita a mano**, y está declarado como excepción con su motivo: el
contrato sólo publica `GET` y eso no es un olvido. Una liquidación es un número
calculado con cada euro explicado, y poder cambiarlo destruiría justo lo que la
hace defendible. Corregirla se hace revirtiéndola y volviendo a liquidar, que
deja una línea de reversión con su porqué.

### 4.6.21 «¿Por qué pone esto si el ERP dice otra cosa?»

Cinco capacidades de calidad del dato estaban publicadas y no se alcanzaban, y
todas por el mismo motivo: son preguntas **por registro**, y lo que había era
el módulo de calidad —la cola y los agregados, qué hay que tocar hoy y si la
cola crece—. Las dos mitades puestas y sin tocarse.

Delante de un cliente concreto la pregunta es otra, y ahora se contesta en su
ficha:

| Qué contesta | De dónde sale |
|---|---|
| De qué grupo forma parte, y **en qué jerarquía** | `GET /accounts/{id}/jerarquia` |
| De dónde sale cada valor y **cuál fuente gana** | `GET /calidad-dato/linaje/cuenta/{id}` |
| Qué lleva demasiado sin que nadie lo confirme | `GET /calidad-dato/obsoletos/cuenta/{id}` |
| Cómo está, y **si ese número sirve para decidir** | `GET /calidad-dato/salud/{id}` |

Cuatro detalles que son la diferencia entre un panel y un volcado:

- **El «gana».** Sin él, una lista de valores distintos no dice cuál se está
  usando — y es exactamente la pregunta: por qué el teléfono dice eso y no lo
  que dice el ERP.
- **El tope, junto a los días.** «Lleva 400 días sin confirmarse» no significa
  nada hasta que se sabe que el tope son 365. Un dato viejo no se distingue de
  uno bueno mirándolo.
- **`sirve_para_actuar` antes que la puntuación.** Una salud que no es fiable o
  que se midió hace tres meses no puede mover una decisión, y pintarla igual
  que una buena es lo que hace que nadie se crea ninguna. El veredicto va
  primero y el número después.
- **Cuál jerarquía.** Son varias a la vez —legal, comercial, de facturación— y
  enseñar una sola sin decir cuál hace que la otra parezca un error.

**Y una lección de robustez que costó diez pruebas rojas de golpe.** Los
paneles leían `.length` de campos que el servidor siempre manda, y un doble de
prueba que devolvía `[]` para rutas desconocidas los dejaba `undefined`: la
excepción tumbaba **la ficha entera**, no el panel. Un campo que falta no puede
convertirse en una pantalla en blanco, así que cada lista se lee con su
`?? []`. Es el mismo principio que ya aplica el resto de la ficha —que un
servicio caído no deje sin ver los datos del cliente— llevado al campo que
falta dentro de una respuesta que sí llegó.

### 4.6.22 La ficha de un caso no devolvía sus propias relaciones

El modelo guarda con qué tiene que ver un caso —cuenta, contacto, producto,
activo, contrato y pedido (`CRM-04.01.01.03`)— y cómo se cerró —motivo
tipificado, resolución, validación del cliente y reaperturas
(`CRM-04.01.01.09`, `.10`)—. **La ruta de detalle no devolvía ninguno de los
dos.**

Y el listado de la bandeja sí manda `cuenta_id`, así que el dato llegaba a una
pantalla y no a la otra: **abrir el caso perdía de qué cliente era**, que es lo
primero que se mira al atenderlo.

Van los seis identificadores y no sólo la cuenta: un caso sobre un activo
instalado se atiende distinto que uno sobre un pedido, y sin el activo hay que
preguntárselo al cliente, que ya lo dijo al abrirlo.

**Lo que más importa de lo que ahora sale es `validacion_cliente`.** Un caso
cerrado por el agente y pendiente de que el cliente lo dé por bueno **no está
cerrado**, y en una lista se ve igual que uno que sí — con lo que un informe de
cierres dice lo que no es. Las reaperturas van con el cierre y no aparte: un
caso cerrado tres veces no es un caso resuelto, y el número al lado del motivo
es lo que hace que se lea la primera vez.

**La ficha**, con lo que decide cómo se atiende:

- **los dos incumplimientos del SLA, separados.** Incumplir la primera
  respuesta y incumplir la resolución son dos conversaciones distintas con el
  cliente, y sumarlas en un «SLA incumplido» esconde la primera, que es la que
  todavía se puede salvar;
- **el reloj parado, dicho.** Un caso que lleva quince horas esperando al
  cliente no lleva quince horas sin atenderse, y en una lista se ven igual;
- **de qué cuelga y de cuál es duplicado.** Un duplicado que no dice de cuál lo
  es obliga a buscarlo, y mientras tanto se contesta dos veces al mismo
  cliente;
- y **el historial**, que es la trazabilidad de la reapertura. Se escribía
  desde el primer día y la ficha genérica lo pintaba como un campo más.

Sólo se enlaza lo que tiene ficha: un enlace a una pantalla que no existe
parece que algo se ha roto. Y lo que no está puesto no se pinta — una lista con
cuatro guiones hace creer que faltan datos cuando lo que pasa es que ese caso
no es de un pedido.

**Y dos preguntas más que la API contestaba y no alcanzaba nadie.**

`GET /colas/explicar/{caso_id}` contesta «¿por qué me ha llegado esto a mí?»,
que es la pregunta que más se repite en un reparto automático. Sin respuesta,
la gente deja de fiarse del reparto y empieza a coger los casos a mano — que es
exactamente lo que el reparto existe para evitar. Va con **cuántas reglas se
miraron antes**: sin ese número, «ninguna coincidió y cayó a la cola por
defecto» y «coincidió la primera» se cuentan igual, y significan lo contrario —
una dice que el reparto funcionó y la otra que no hay reglas que cubran ese
caso.

`GET /entitlements/{id}/saldo` dice qué derecho cubre el caso y cuánto queda,
con **las dos bolsas aunque sólo una esté limitada**: enseñar sólo la limitada
hace que quien mira no sepa si la otra no se cuenta o es que nadie ha gastado,
y son cosas distintas delante de un cliente que pregunta. Con la caducidad al
lado del saldo, porque un derecho con doscientas horas libres que vence el
viernes es tan inservible como uno agotado y el saldo solo lo pinta holgado. El
derecho se pregunta **por el cliente del caso** y no por el caso: el derecho es
del contrato.

**Y el mismo fallo de robustez, cometido otra vez.** El panel del reparto hacía
`.map` sobre lo que llegara, y un doble que devolvía otra forma tumbaba la
ficha entera — el mismo error que dos bloques antes costó diez pruebas rojas en
la ficha de cliente. Queda escrito aquí porque la lección no es el `?? []`: es
que **asumir la forma de lo que llega convierte un campo raro en una pantalla
en blanco**, y eso no falla, no avisa y no deja traza.

### 4.6.23 «¿Cómo estaba esto el 3 de marzo?»

El historial campo a campo ya se enseñaba en la ficha. Lo que faltaba es la
otra mitad: **cómo estaba el registro entero** en un momento dado. Encadenar
cambios a mano para reconstruirlo sale mal en cuanto hay una fusión o un
borrado por medio.

Y lo que de verdad justifica el panel no es la reconstrucción: es
`GET /{servicio}/rastro/{objeto}/{id}/cuadra`. **Una reconstrucción que no
coincide con la tabla viva significa que alguien escribió sin pasar por el
rastro** —un script de corrección, una migración, un arreglo a mano un
viernes—. A partir de ahí el rastro deja de ser una prueba y nadie se entera,
porque sigue contestando con la misma seguridad. Por eso el «no cuadra» sale en
rojo y **con el campo concreto**: sin la diferencia, «no cuadra» no deja
empezar a buscar por ningún sitio.

Va plegado y se pide sólo al abrirlo. El rastro completo está encendido en muy
pocos objetos a propósito —guardar todos los hechos de todo multiplica la
escritura por algo que casi nadie consulta— y pedirlo en cada ficha sería una
llamada por registro abierto que casi siempre contestaría «aquí no hay». Un 404
en esa ruta no es un error: es que nadie lo encendió para ese objeto, y se dice
con esas palabras.

**Y dónde NO se declara, que es la mitad que suele faltar.** La pantalla de
plataforma roza esta capacidad y dice explícitamente que no la cubre: reconstruir
pide el identificador de un registro concreto y su sitio es la ficha de ese
registro. Declararla allí habría sido declarar lo que no se hace.

### 4.6.24 Un documento firmado y uno que parece firmado

El listado de sobres enseñaba el estado y la referencia. Delante de un sobre la
pregunta no es si está firmado: es **si esa firma se sostiene** el día que
alguien la discuta.

La ficha genérica no podía contestarla, y por un motivo mecánico: la evidencia
devuelve un **objeto**, y esa ficha descubre paneles entre lo que devuelve
listas — lo que devuelve un objeto salía siempre con «nada todavía».

Dentro de la evidencia, el campo que decide es **`verificable`**: sin el hash
de lo enviado y el de lo firmado la firma no se puede comprobar, y eso no se
nota mirando el estado, que pone «firmado» igual.

Tres cosas más que la pantalla pone delante:

- **el nivel eIDAS**, porque una firma simple y una cualificada valen lo mismo
  en una lista y no valen lo mismo ante un juez;
- **si cada firmante fue identificado y cómo.** Una firma sin identificación es
  una casilla marcada por alguien con acceso al correo, y en una lista se ve
  igual que una con DNI y SMS;
- y **qué dato de la prueba falta**, dicho con esa palabra. Un hueco en blanco
  se lee como «no aplica», y aquí significa que falta una pieza de la cadena.

La edición se mantiene: existía en la ficha genérica y el contrato publica
`PATCH`, así que quitarla al traerse el sobre a su propia pantalla habría sido
retirar algo que funcionaba sin que nadie lo decidiera.

### 4.6.25 Cuatro pantallas leían un campo que nadie manda

El fallo más barato de cometer y el más caro de encontrar: una pantalla lee
`fila.tipo`, el servidor manda `dinamico`, y **no pasa nada**. No hay error, no
hay traza, no hay 500. El campo llega `undefined`, el hueco sale en blanco y la
pantalla parece que funciona.

Medido el 29-10-2026 recorriendo las veintiuna rutas que una pantalla tipaba:

| Pantalla | Lo que leía | Lo que manda el servidor |
|---|---|---|
| Marketing (segmentos) | `tipo`, `miembros`, `calculado_at` | `dinamico`, `tamano`, `tamano_at` |
| Marketing (campañas) | `miembros`, `enviados`, `respuestas` | ninguno de los tres existe en la tabla |
| Conocimiento | `titulo`, `publico` | el título vive en `versiones_articulo` |
| Territorios | `criterios` | el listado no los devolvía |
| Ficha de una venta | `tipo` de la línea | `tipo_ingreso` |

La de conocimiento no se quedaba en blanco: **se caía**. `a.titulo.toLowerCase()`
sobre `undefined` tumba la pantalla entera, y sólo al escribir en el buscador.

#### Por qué ningún guardián las vio

El que ya había mira las llamadas tipadas —`llamar<Tipo>(ruta)`—. Las cuatro
usaban `llamar<unknown>(ruta)` y le ponían la forma **después**, con
`filas<Tipo>(r.datos)`: veintiuna rutas de diez pantallas por ese hueco.

Se cierra por construcción, no con una regla: `listar<T>(ruta)` y
`listarPagina<T>(ruta)` hacen la llamada y le dan forma a la vez, así que la
ruta y el tipo están en el mismo sitio. Viven en `lib/listados.ts` y no dentro
de `lib/api.ts` a propósito: una prueba que sustituye `@/lib/api` sustituye el
módulo para quien lo importa, pero una función **dentro** de `api.ts` seguiría
llamando a la `llamar` de verdad, que en una prueba sale a la red.

#### El dato que hace falta no siempre es una columna

Tres de los cinco casos son lo mismo: lo que hay que enseñar de una fila no
está en la fila.

- **los miembros de una campaña** se cuentan en `miembros_campana`: es un
  agregado, y para eso ya estaban los *rollups*. Se declara uno y el camino de
  lectura lo pega a toda la página en una consulta;
- **el título de un artículo** vive en `versiones_articulo` y cambia con cada
  versión. No es un agregado —`max(titulo)` es el título alfabéticamente mayor,
  no el de la versión publicada—, así que `montar_listado` gana `extras`: una
  función que recibe la página entera y devuelve `{id: {campo: valor}}`. Gana
  siempre la versión publicada y, si no hay ninguna, la última **diciendo que es
  un borrador**;
- **los criterios de un territorio** sí eran una columna, y el listado escrito a
  mano no la devolvía.

`extras` obliga a declarar qué campos añade (`extras_declara`), y el montaje se
cae si no se dice. No es burocracia: es lo que permite que el guardián sepa qué
devuelve ese listado.

#### El guardián nuevo

`test_la_pantalla_no_se_inventa_el_campo` resuelve, para cada ruta, **las claves
que puede devolver**, y las compara con los campos obligatorios que la pantalla
declara. Resuelve sólo por caminos exactos: el modelo de un listado genérico con
sus agregados y sus extras declarados, el esquema de salida, la proyección, el
diccionario literal del manejador, o **un salto** de delegación a una función
con nombre.

Un salto y acotado, porque la versión suelta se equivocó: buscando por el nombre
del atributo, `pagina.a_dict(…)` del listado de cuentas casó con una función
`a_dict()` de previsión y el resolutor contestó que `/accounts` devuelve
«compromiso» y «ponderado». Lo mismo con los `return` de una función auxiliar
dentro del manejador, que hicieron denunciar un contrato sano. **Una respuesta
equivocada aquí es peor que ninguna**: aprueba lo roto y manda a cambiar lo que
estaba bien.

Lo que no cae en ningún camino se cuenta y se deja fuera: 484 rutas resueltas,
120 contratos de pantalla y 26 puntos ciegos, con tope que sólo baja.

### 4.6.26 El segmento antes del envío, y el lead antes de la llamada

Siete capacidades que sólo tenían API. Dos pantallas.

#### Un segmento

Lo que se hace con un segmento no es mirarlo: es mandarle algo. Las tres
preguntas de antes de un envío no se podían contestar desde ninguna pantalla, y
ninguna de las tres cabe como panel de la ficha genérica —el recuento devuelve
un **objeto** y esa ficha sólo descubre paneles que devuelven listas, el
solapamiento cuelga del prefijo de la colección y se pide **contra otro**
segmento, y congelar cambia la naturaleza del segmento—.

- **Dinámico o foto congelada.** Un dinámico se recalcula al preguntarlo; un
  estático devuelve lo que se congeló. Los dos enseñan un número con la misma
  cara, y sobre el segundo se manda un correo creyendo que es la gente de hoy.
  Congelar es lo que permite contestar en junio «¿a quién se le mandó?» con la
  lista de marzo.
- **El bruto y los alcanzables no son el mismo número**, y el hueco se nombra:
  entre uno y otro están las supresiones. Planificar un envío a diez mil y que
  salga a siete mil sin saber por qué faltan tres mil es el caso que esto evita.
- **El solapamiento, con el porcentaje sobre cada uno de los dos.** Mil personas
  comunes es mucho si el segmento tiene mil doscientas y poco si tiene cien mil,
  y con un solo porcentaje la decisión sale al revés.

#### La puntuación de un lead

«Este lead tiene 87» no se acciona. Lo que hace que un comercial llame es saber
que descargó el comparativo y entró dos veces en la página de contratación.

Los dos ejes salen **separados y nunca sumados**: el encaje dice si es el
cliente que buscamos y el interés cuánto caso nos hace, y un director de compras
callado y un estudiante muy activo pueden dar el mismo total sin que se haga lo
mismo con los dos. El decaimiento va aparte y con su regla, porque sin él un
lead que hizo mucho y tiene poco interés parece un scoring roto — y sólo decae
el interés: el encaje sale de quién es.

**Los umbrales se escribían y no los leía nadie.** `umbral_mql_interes`,
`umbral_mql_encaje`, `umbral_sql_interes`, `umbral_sql_encaje` y los tramos de
grado se guardan al publicar el modelo y sólo los leía `calificar`: ninguna ruta
los devolvía. Así que «este lead es MQL» no se podía contrastar con nada, «qué
le falta para SQL» no se podía contestar, y un grado «B» era una letra sin
tramo. Ahora `GET /puntuacion/leads/{id}` los devuelve con la cuenta hecha, y
`GET /puntuacion/modelos` los enseña para que quien administra vea qué hace MQL
a un lead en su propio CRM.

Dos detalles que no son de presentación:

- **un umbral sin declarar es «no aplica», no cero.** `calificar` no deja pasar
  a nadie por un escalón sin umbrales, así que decir «le faltan 0» sería
  exactamente lo contrario de lo que pasa. Se dice que no es alcanzable;
- **lo que falta de interés se gana con actividad y lo que falta de encaje no.**
  No es un matiz: al que le falta encaje no se le llama más, se descarta o se
  cambia el ICP.

La puntuación no se edita, y está escrito en la excepción del gate de edición:
es un cálculo con cada punto explicado por su regla, y poder cambiarlo a mano
destruiría lo único para lo que sirve —ordenar leads comparándolos con la misma
vara—. Lo que se cambia es el modelo, que se publica por versiones.

### 4.6.27 Por dónde entran los casos, y qué se queda por el camino

Un canal de entrada es una puerta declarada: de dónde llega un mensaje y cómo
se traduce en un caso. Los tipos son una lista cerrada —correo, formulario,
chat, social, api, teléfono, portal— y `recibir()` aplica cinco filtros en
orden antes de abrir nada: trampa, anti-bucle, eco propio, tope por hora y
campos obligatorios.

**Los cinco se calculaban y se tiraban en un solo contador.** `descartados` era
un número, y un número no se puede accionar: no distingue el caso bueno —el
anti-bucle cortando un bucle de respuestas automáticas, que es exactamente para
lo que está— del caro, que es una trampa mal puesta comiéndose correos de
clientes.

Y la trampa es el peor sitio donde perder información, porque se descarta
**contestando «aceptado» a propósito**: contestar distinto le diría al robot qué
campo cambiar. Así que un canal mal configurado se come mensajes de clientes,
contesta que todo bien, y del lado de quien escribió no queda ni rastro.

`CanalServicio` gana `descartados_por`, un diccionario `{motivo: cuántos}`. Un
diccionario y no una columna por motivo: los motivos los decide `recibir`, y
añadir una columna cada vez que aparezca uno es la migración que no se hace.
Los canales anteriores arrancan con `{}` y no con el total repartido a ojo —
inventar el reparto de lo pasado sería peor que decir que no se sabe, y la
pantalla lo enseña como «sin motivo apuntado».

Se apunta en **un solo sitio**, `_descartar(canal, motivo)`, que suma el total y
el desglose a la vez. Con cinco ramas, la que se olvide de sumar una de las dos
es la que nadie echa de menos; la prueba lo fija exigiendo que el desglose sume
el total. Y la rama del tope va **antes** del `raise`: puesta después no se
ejecutaría nunca y su contador saldría siempre a cero.

La pantalla pone las defensas delante de las cifras —el tope, la dirección
propia, la trampa y los obligatorios—, porque son lo que explica el número. Un
canal de correo sin dirección propia declarada no puede cortar su propio eco, y
eso no se ve mirando cuántos entraron: se ve cuando el buzón lleva un mes
contestándose a sí mismo.

### 4.6.28 Qué se ha hecho sobre los datos de un cliente

Clonar un tenant, fusionar dos o partir uno son las operaciones más peligrosas
del producto: sacan los datos de un cliente de donde están protegidos. El
producto ya lo trataba como tal —obliga a **simular antes de ejecutar**, porque
«una operación que simula y ejecuta a la vez no es una simulación», y guarda de
cada una su plan y sus conflictos con el motivo escrito en el modelo: «es lo que
alguien tiene que leer ANTES de aprobar»—.

Y no había ninguna ruta que los listara. `OperacionTenant` se leía **por
identificador y nada más**, así que sólo podía volver a una operación quien se
hubiera guardado el id de la respuesta. Nadie podía contestar «¿qué se ha hecho
sobre este cliente?», que es la pregunta de cualquier auditoría.

`MigracionAislamiento` **sí** se listaba ya —lo monta un `montar_listado`
genérico al final de su módulo— y lo que faltaba era enseñarla: la ventana de
solo lectura es lo único de esta familia que pasa en tiempo real, y mientras
esté abierta ese cliente no puede escribir.

Así que lo nuevo es sólo el listado de `OperacionTenant`: la tabla, los campos
y las rutas de acción ya estaban.

En la pantalla, lo **simulado va aparte de lo hecho**. No es presentación: una
simulada no ha movido una sola fila, y en una lista corrida ocupa una línea
igual que una ejecutada — justo donde esa confusión sale cara. Una fallida se
queda entre las hechas con su motivo, porque saber qué se intentó es parte de
saber qué hay. Y una migración «verificada» con diferencias se señala: verificar
no es aprobar, es medir.

### 4.6.29 Un GRC que sólo lista es un archivo

El módulo genérico ya listaba riesgos y controles. Lo que convierte el GRC en
herramienta son tres cosas que **devuelven objetos** —y que por eso la ficha
genérica no sabe pintar, porque sólo descubre paneles que devuelven listas—:

**El panel, con su `medible`.** Un panel vacío en verde es el que más
tranquiliza y el que peor informa: «cumple» y «no hay nada con lo que
comprobarlo» se pintan igual y significan lo contrario. Y lo urgente sale con
su **porqué**, no con un color: «control evaluado como no efectivo» no mueve a
nadie; «está declarado y no protege: peor que no tenerlo, porque consta» sí.

**El informe de cobertura contra el catálogo entero**, por identificador. De
ahí sale además lo que nadie busca: los controles que apuntan a una capacidad
**que no existe**. Constan como cobertura y no cubren nada, que es la peor de
las dos formas de no estar cubierto, porque nadie los echa de menos.

**El mapeo a marcos, recorrible en los dos sentidos.** Un auditor pregunta por
ISO 27001 A.9 y hay que contestar qué controles responden y qué capacidades los
sostienen; quien va a tocar el código pregunta lo contrario, qué obligaciones
responde esta capacidad. Las dos salen del mismo dato.

#### El número de cabecera que nunca estuvo

Encontrado al escribir la pantalla: `panel()` pedía `cobertura_pct` a
`cobertura()`, y esa función devuelve la cifra con el nombre **`pct`**. La
cobertura del panel salía `None` **siempre** — también cuando el propio panel
decía `medible: true`, porque `medible` mira los controles y las evaluaciones y
no esto. El panel afirmaba que se podía medir y el número no estaba.

Lo que lo mantuvo escondido es fino y conviene recordarlo: el nombre equivocado
**acertaba por casualidad en el único caso que tenía prueba**. La prueba que
había comprueba el panel vacío, y ahí la respuesta correcta es justamente
`None` —«un 0 % y un *no se ha podido medir* se leen igual y significan lo
contrario»—. Así que el arreglo no es renombrar la clave: es dar la cifra
**sólo cuando hay con qué medir**, que es lo que la prueba vieja pedía y lo que
la nueva fija con datos dentro.

### 4.6.30 Una campaña: qué prometió y qué costó cada cosa

El listado enseña estado, canal y cuánta gente tiene dentro. Las cuatro
preguntas de delante de una campaña devuelven **objetos**, así que la ficha
genérica no las pinta: el consumo, el rendimiento con su plan contra el real,
el embudo y el resultado del evento.

Tres cosas que el servidor ya decía y ninguna pantalla enseñaba:

- **un objetivo sobre algo que el embudo no mide sale como «no comparable»**,
  no contra cero. `plan_vs_real` devuelve `real: null` justo para eso, y
  pintarlo como un 0 convierte un objetivo mal declarado en un fracaso
  aparente;
- **el ROI sólo cuando `roi_medible`.** Sin ingresos atribuidos no hay ROI, y
  un 0 % y un «no se sabe» se leen igual y significan lo contrario;
- **los inscritos sin marcar van delante de la tasa de asistencia.** Una tasa
  calculada ignorando a los que nadie marcó es una tasa inventada, y por eso el
  servidor manda `medible` aparte del número.

Y el gasto se parte en propio y de las tácticas: una campaña que no ha gastado
nada y cuyas tácticas se han comido el presupuesto se lee como barata si se
suman.

El embudo **se pincha**. Dice cuántos hay en cada estado, y lo que hace falta
para trabajar es quiénes: la diferencia entre «40 han hecho clic» y poder
llamarlos es toda, y la ruta de miembros ya filtraba por estado para eso.

### 4.6.30 bis Marketing que sale de verdad (09-11-2026)

- **Tablas** (migración `alembic/versions/marketing/20261109_1603_audiencias_sincronizadas_y_envios_.py`):
  `audiencias_publicitarias`, `miembros_audiencia_publicitaria`,
  `sincronizaciones_audiencia` y `envios_programados`.
- **Código**: `services/marketing/audiencias_sync.py` (sincronizar),
  `envios.py` (elegir hora y canal, programar, despachar, sucesos),
  `vista_correo.py` (datos reales, recomendaciones, montaje, spam, salida por
  clase), `api_envios.py` (rutas). En `recorridos.py`, el paso de acción con
  plantilla programa el envío, la prueba A/B aplica su ganadora y hay
  `actualizar_lienzo`; en `campanas.py`, `efecto_de_eliminacion` (Markov).
- **Rutas**: `/audiencias-publicitarias` (+`/{id}/sincronizar`),
  `/envios-programados` (+`/despachar`, `/{id}/suceso`),
  `POST /campanas/{id}/programar-envio`,
  `GET /correo/plantillas/{clave}/vista-previa`, `GET /correo/salida`,
  `GET|PUT /recorridos/{id}/lienzo`, `GET /recorridos/{id}/inscritos`,
  `GET /momento/destinatario/{id}`.
- **Por HTTP** (`crmcore.http.interno.invocar`, con la identidad de quien pide):
  `integration` (invocar la operación de la conexión), `party` (contacto,
  cuentas, `puede-contactar`) y `sales` (oportunidades, líneas, catálogo, leads
  convertidos). Ningún import entre servicios.
- **Conector**: un valor que es sólo `{{marcador}}` y apunta a una lista u objeto
  se manda tal cual (antes salía la representación de Python).
- **Envío**: `crmcore.notificaciones.smtp.TransporteSMTP` para el correo y
  `TransporteHTTP` (`canal_sms`) para SMS.
- **Lo que sale solo** (migración `20261109_1735_quien_programo_el_envio_y_quien_.py`):
  dos tareas periódicas en `services/marketing/main.py` (`_tareas()`, con
  `crmcore.tareas.Tarea`/`por_tenant` y `RelevoDeTareas`):
  `marketing.avanzar_recorridos` (`recorridos.avanzar_solos`, cada
  `recorridos_avanzar_cada_s`, como mucho `recorridos_avance_lote` personas por
  tenant) y `marketing.despachar_envios` (`envios.despachar_vencidos`, cada
  `envios_despachar_cada_s`, como mucho `envios_despacho_max_por_vuelta` envíos,
  **uno por transacción**). Los intervalos se leen al arrancar. Cada envío guarda
  quién lo programó (`programado_por_id` + `programado_con`: tipo, permisos y
  roles en foto) y cada recorrido quién lo publicó (`publicado_por_id` +
  `publicado_con`); lo automático actúa con esa identidad y sólo con esos
  permisos (`envios.invocar_como`). Sin ella, el envío se queda `programado`
  con motivo «No consta quién lo programó…» y el recorrido publicado no avanza
  solo y sale en `sin_identidad`. Filas con `FOR UPDATE SKIP LOCKED`: dos
  procesos no despachan ni mueven dos veces lo mismo. Un fallo de un tenant no
  para a los demás (`por_tenant`); un fallo de un envío queda en ese envío
  (savepoint) y no deshace los que ya salieron. A mano
  (`/envios-programados/despachar`, `/recorridos/avanzar`) actúa quien lo pide.
- **Ajustes** (`services/marketing/ajustes.py`): `audiencia_*`, `momento_*`,
  `remitente_*`, `correo_flujo_*`, `correo_url_baja`, `vista_previa_clientes`,
  `spam_*`, `recomendaciones_maximo`, `prueba_significacion`,
  `prueba_desviar_al_ganador`, `envios_despachar_cada_s`,
  `envios_despacho_max_por_vuelta`, `recorridos_avanzar_cada_s`,
  `recorridos_avance_lote`.
- **Pantallas**: `paginas/RecorridoDeMarketing.tsx`,
  `paginas/AudienciaPublicitaria.tsx`, `componentes/EnviosDeMarketing.tsx`
  (en la campaña), `componentes/VistaPreviaCorreo.tsx` (ficha de plantilla) y
  `componentes/AtribucionDeLead.tsx` (ficha del lead).

### 4.6.31 Un artículo: a quién llega, en qué idiomas y si sirve

La lista enseña título, estado y vistas. Las tres preguntas de delante de un
artículo las contesta ya el servidor y no las enseñaba nadie.

**Las traducciones dicen cuántas versiones van por detrás**, no sólo que están
desincronizadas. Es el fallo caro de una base multilingüe: se corrige el
original, las traducciones se quedan como estaban, y el cliente de otro idioma
lee el procedimiento viejo durante meses. Y el número importa: una versión por
detrás suele ser una errata, seis ya es otro artículo.

**La eficacia separa los dañinos de los huérfanos.** Un artículo dañino —muchas
vistas y votos negativos— es peor que no tener artículo, porque alguien lo está
siguiendo; uno huérfano simplemente no lo usa nadie. En una lista ordenada por
vistas los dos se ven igual, y se arreglan al revés: uno se corrige, el otro
puede que sobre.

**La deflexión va con su aviso de que es aproximada**, que lo manda el propio
servidor. Presentada como una medida es el número con el que se justifica no
contratar a nadie más en soporte.

Lo que se edita desde la ficha es lo que **es** del artículo —su clave, su
audiencia, sus canales, su fecha de revisión—, no su texto: el texto va por
versiones, que es lo que permite corregir uno publicado sin que el cliente vea
el cambio a medias.

#### El KCS va en el caso, no aquí

`POST /conocimiento/desde-caso/{caso_id}` existía y no se alcanzaba desde
ninguna pantalla. Se ha puesto en el panel de cierre de un caso y no en la
pantalla de conocimiento, porque **el momento es la capacidad**: se escribe
cuando se resuelve, con el problema fresco y por quien lo resolvió. Pedirlo
después, en una sesión dedicada, es como no pedirlo.

El cuerpo viene relleno con la resolución del caso y el aviso va **antes** de
escribir, no después de guardar: la resolución lleva casi siempre el nombre del
cliente, su configuración y a veces sus credenciales, y lo que hay que quitar
se quita mientras se escribe. El artículo nace en borrador e interno aunque
venga de un caso resuelto, y la pantalla lo dice al crearlo.

### 4.6.32 Un presupuesto, antes de mandarlo

El listado enseña número, estado y total. Lo que se decide delante de un
presupuesto es **si se manda**, y eso son tres cosas que devuelven objetos.

**«Necesita aprobación» va con sus motivos.** A secas se lee como burocracia;
con el motivo, el umbral de descuento y el margen mínimo al lado se lee como un
dato y se discute con él. El servidor ya devolvía los cuatro campos.

**El margen va pegado al descuento**, no en otra pestaña. Es la pareja que
decide: un 30 % de descuento sobre algo con 60 de margen y sobre algo con 12
son dos conversaciones distintas, y en la lista los dos son «30 %». Cuando no
hay coste en las líneas no hay margen, y se dice: un descuento sin margen al
lado no se puede valorar.

**El documento se ve antes de mandarlo.** La plantilla, la marca y el idioma
salen de la configuración, y descubrir en el correo del cliente que salió con
la marca equivocada no tiene arreglo. Se pide al pulsar y no al abrir: es la
única llamada de esta ficha que compone un documento entero.

Y la comparación con la versión anterior, que el servidor ya daba línea a línea
con el total antes y después: mandar la tercera versión sin saber qué lleva
distinto de la segunda es como se acaba regalando un descuento que nadie
aprobó. Una primera versión **lo dice** en vez de enseñar una comparación vacía,
que se leería como «no ha cambiado nada».

Lo que se edita desde la ficha es lo que acompaña al presupuesto —título,
notas, condiciones, hasta cuándo vale—, no sus líneas: el precio se renegocia
sacando una versión nueva, que es lo que deja comparar.

### 4.6.33 Qué hay desplegado en cada entorno

La configuración se promociona por paquetes —desarrollo, pruebas,
preproducción, producción— y todo eso existía por API sin verse en ningún
sitio. Así que la primera pregunta delante de una incidencia, **«¿qué hay
puesto ahí ahora mismo?»**, no la contestaba ninguna pantalla.

**El drift va con su `medible` delante.** Un entorno limpio y un entorno que no
se ha podido comparar se ven igual de bien y significan lo contrario. Dentro,
lo **tocado a mano** va separado de lo **desaparecido**: lo primero lo va a
pisar el siguiente despliegue sin avisar a quien lo cambió, lo segundo está
declarado en el paquete y ya no está en el entorno. Y lo **no comparado** se
dice, porque un «limpio» calculado sobre la mitad de los elementos no es un
limpio.

**La huella y la referencia de Git van con el despliegue.** Sin ellas «está el
paquete v7» no se contrasta con nada: la huella dice si lo que hay es
exactamente lo que se empaquetó, y la referencia dice qué commit lo generó.

**Y si se puede volver atrás se dice antes de pulsar.** Un rollback que a veces
no funciona es peor que no tenerlo, porque se cuenta con él justo el día que
hace falta.

### 4.6.34 Por qué canales se le puede escribir a alguien

Los canales estaban declarados y el consentimiento se guardaba **por canal y
por destino**, y no había ninguna pantalla que contestara la pregunta de antes
de mandar nada. Que no es una pregunta: son cinco.

- **El consentimiento no es global.** Alguien puede haber aceptado el correo y
  no el SMS, y tratarlo como una sola casilla es lo que convierte una baja en
  una denuncia.
- **En WhatsApp manda la ventana de 24 horas.** Fuera de ella sólo sale una
  plantilla **aprobada**, y el estado de aprobación lo pone el proveedor y no
  nosotros. Mandar una no aprobada **no falla**: el proveedor la descarta en
  silencio, así que se corta antes de salir y la pantalla lo dice.
- **La baja se da con una palabra y cada canal tiene la suya.** Va en la lista
  y no escondida en la ficha: quien escribe el mensaje tiene que ponerla
  dentro, y un canal sin palabra de baja declarada no puede llevar nada
  comercial.
- **El calentamiento de un dominio frena.** Cuando hay tope sale el tope; y
  `calentamiento: null` significa que ese dominio **no** está calentando, no
  que el tope sea cero — pintarlo como un cero diría «hoy no puedes mandar
  nada», que es lo contrario.

Y el «no se puede» viene con sus motivos, uno por regla. A secas deja a quien
escribe el mensaje sin saber qué arreglar.

### 4.6.35 Dónde me han mencionado

Mencionar a alguien **funcionaba**: se guardaba, se notificaba y se podía leer
abriendo el registro. Lo que faltaba era el sitio donde se ven todas, y sin él
la función no existe en la práctica — nadie abre cuarenta fichas por si acaso.

Y no se podía montar con lo que había. Los comentarios los guarda **el servicio
dueño del registro**, y la ruta existente calculaba todas las menciones de una
persona y **tiraba las de los demás tipos** para devolver sólo las del tipo
pedido. Así que ver las propias era preguntar una vez por tipo de objeto, y
saberse de memoria qué servicio guarda cuál.

Ahora cada servicio publica `GET /comentarios/mis-menciones` con las suyas, y
el **gateway las junta** —el mismo patrón que la página de estado, y por lo
mismo: en serie, tres servicios con cinco segundos de plazo son quince segundos
de espera—. La lista de servicios sale de `OBJETOS_COMENTARIO`, la misma tabla
que usa el enrutado, y no de una lista escrita a mano que se quedaría corta el
día que un servicio nuevo monte el router.

**Un servicio mudo no se calla**: sale en `sin_respuesta`. «No tienes
menciones» y «no se ha podido preguntar» se leen igual y significan lo
contrario, y con los comentarios repartidos esto pasa de verdad.

La ruta va en `_AGREGADAS_EN_EL_GATEWAY` porque el gateway no la reenvía: la de
un servicio suelto serían un tercio de las menciones presentadas como todas.

#### Y lo que llega de lo que mandamos

Las aperturas y los rebotes se guardaban y no los leía ninguna pantalla. Van en
**Canales** y no en un panel aparte, porque es donde se decide si un canal
sirve: un dominio que manda mucho y no abre nadie está cayendo en la carpeta de
basura, y eso no se ve mirando los envíos. La tasa sólo sale cuando el servidor
dice que hay con qué calcularla — con veinte envíos, un 5 % y un 100 % son el
mismo ruido.

### 4.6.36 Qué falta para cerrar, y el plan con el cliente

Tres paneles en la ficha de la oportunidad —y no una pantalla aparte, porque
es el mismo registro y la misma pregunta—.

**La puntuación de metodología va con «lo que falta» al lado, nunca sola.** Un
«62 sobre 100» es una nota: no dice qué hacer, así que no cambia nada. La
lista de criterios sin cubrir sí, y es lo que convierte la metodología en
trabajo. Se evalúa con la metodología **activa**: hacerlo con una retirada
daría una puntuación contra criterios que ya no se aplican.

**El playbook es el de su etapa, y con el porqué se eligió.** Uno genérico no
es un playbook, es una lista de buenas intenciones; y uno que aparece sin
explicación se ignora, con lo que da igual que esté.

**En el plan conjunto, lo retrasado nuestro va separado de lo retrasado del
cliente.** Es la única distinción de ese panel que cambia algo: si vamos tarde
nosotros se empuja aquí dentro, y si va tarde el cliente la conversación es con
él. Juntos son «el plan va mal», que no se acciona. Y un plan que el cliente no
ha visto no es un plan conjunto: es una lista nuestra con su nombre encima, así
que `compartido` y `visto_por_el_cliente` van delante de los pasos.

#### Los playbooks no se podían crear

Encontrado al escribir el panel, y es el caso más puro de «escrito y sin
enchufar»: la tabla `playbooks` existía, `playbook_para` la leía y elegía el
más específico —uno que nombra etapa y segmento gana a uno que sólo nombra la
etapa—, y estaba probado. Y en el producto **no entraba ni una fila**: ni POST,
ni listado, ni semilla. Sólo las pruebas escribían, construyendo el ORM a mano.

Así que la capacidad constaba hecha y el selector devolvía `None` siempre,
porque la tabla estaba siempre vacía. Ahora tiene su listado, su ficha, su alta
y su exportación —cuatro puertas—, y el prefijo está declarado en el enrutado
del gateway, sin el cual las cuatro contestaban 404.

### 4.6.37 La presión y el freno automático

Dos cosas que el sistema **hacía** y no enseñaba, las dos en la página de
estado.

**La presión.** Cuando un servicio va apretado se aplaza lo que no es crítico,
y eso explica por qué algo tarda hoy y ayer no; sin verlo, la causa se busca en
el sitio equivocado. Y lo que decide no es la media: es **el que peor va**. Con
uno ahogado y trece holgados la media sale tranquila y lo no crítico se difiere
igual, así que el peor sale al lado del número. Un servicio que no contesta no
cuenta como holgado: sale aparte, porque «nadie va apretado» y «no he podido
preguntar a tres» se leen igual.

**El freno adaptativo.** A un tenant que se sale de su patrón se le baja la
cuota —al 75 %, al 50 %, al 25 %—, y eso se anota, se evalúa y se aplica en el
proxy de **cada petición**. No había ninguna ruta que dijera a quién: un
cliente podía llevar horas a un cuarto de su cuota, con sus integraciones
reintentando más fuerte porque les llega un 429, y la única forma de enterarse
era leer los registros del gateway.

Tres cosas que el panel dice y que no son adorno:

- **el factor**, no sólo «frenado»: al 75 % y al 25 % no se hace lo mismo;
- **el motivo**, porque un freno sin explicación hace que la integración
  reintente más fuerte, que es lo contrario de lo que hace falta;
- y **cuántas ventanas se llevan observadas** de cada uno. Por debajo del
  mínimo no se evalúa a nadie, así que un tenant disparado puede no salir
  frenado todavía — y eso, sin decirlo, parece un fallo del freno.

Lo observado vive en la memoria del proceso, así que la lista es la de **ese**
gateway. Se dice en la respuesta: con varias réplicas, una lista corta no
significa que no haya nadie frenado.

### 4.6.38 El servicio de campo: el activo y la orden

Un activo instalado no es una ficha de inventario: es la máquina que hay en
casa del cliente. Tres cosas que el servidor ya daba y nadie enseñaba.

**El árbol de componentes, con su «truncado».** Una avería en una bomba no se
entiende sin saber de qué equipo es; un componente mirado solo lleva a cambiar
la pieza y no la causa. El árbol se corta a seis niveles y **lo dice**: uno
cortado sin avisar se lee como un árbol completo.

**El historial sigue la cadena de sustituciones.** Si la máquina se cambió hace
dos años, su historial empieza en la que estaba antes — la avería de hoy puede
venir de aquello, y un historial que arranca en la sustitución esconde justo el
patrón que había que ver.

**La cobertura, donde lo que decide no es sí o no: es si es concluyente.** «No
se puede determinar» y «no está cubierto» se leen igual en una pantalla, y la
diferencia es quién paga una reparación de cuatro mil euros.

**Y el contador, con la fecha de su lectura.** Sale de la ficha del activo y no
de una ruta propia, porque `leer_contador` **anota** una lectura pese al
nombre: no hay forma de consultarlo sin escribir una. La fecha va siempre al
lado — un contador sin ella se lee como el de hoy, y sobre un contador se
decide un mantenimiento.

De la orden de trabajo, dos:

**El reparto de cobertura va en tres cestas, no en dos.** Lo que paga el
cliente, lo que se le reclama al fabricante y lo que **no se sabe todavía**.
Fundir la tercera con cualquiera de las otras es facturar de más o perder una
reclamación, y las dos se descubren tarde: una en la factura y la otra cuando
la garantía ya venció.

**El parte dice si se tocó después de firmar.** Guarda una huella de su
contenido al firmarse; si ya no cuadra, alguien lo cambió después, y eso
convierte la firma del cliente en un papel sin valor. No se nota mirándolo: se
ve igual de completo. Y «firmado» y «conforme» son dos cosas: un cliente puede
firmar que estuvimos y no estar conforme con el resultado.

#### `equipos_en_la_cadena` es una lista, no un número

Lo tipé como número al escribir la pantalla, y en JavaScript una lista nunca
es menor que un entero: la comparación `> 1` habría sido **siempre verdadera**
y el aviso de cadena habría salido en todos los activos, también en los que
nunca se sustituyeron. Lo cazó la prueba de servidor al comparar contra la
forma de verdad, que es para lo que están.

### 4.6.39 Qué plantillas funcionan, y a quién le toca la reunión

**Una tasa de respuesta sin su número de envíos es ruido.** Con nueve correos,
un 33 % son tres respuestas y mañana puede ser un 11 %: ordenar plantillas por
ese porcentaje hace que la mejor sea siempre la que menos se ha usado. El
servidor marca cada una como **concluyente** o no, y la pantalla saca aparte
las que no lo son — no mezcladas, porque mezcladas el orden ya está mal.

**La apertura va con su advertencia y no manda.** Contarla depende de un píxel
que media industria bloquea, así que una apertura baja puede ser una plantilla
mala o un cliente de correo prudente. La respuesta no tiene ese problema.

**Pedir «a quién le toca» no es una consulta: avanza el round-robin.** Por eso
va con botón y no al abrir —una pantalla que lo pidiera sola repartiría
reuniones cada vez que alguien la mira— y se dice que el turno **se ha
consumido**: sin eso, alguien pulsa tres veces para «ver» y se salta a dos del
equipo.

Y un equipo sin nadie con disponibilidad **no reparte en silencio**: el
servidor contesta con su porqué, porque repartir entre cero personas deja la
reunión sin proponer y sin que nadie se entere. La pantalla enseña la
`explicacion` del error y no su título: la frase del servidor está escrita para
leerse, y el título es sólo «No encontrado».

### 4.6.40 El editor de tablas de decisión (CRM-00.03.02.10)

Pantalla propia en `frontend/src/paginas/TablaDeDecision.tsx`, montada en
`/m/procesos/tablas-decision/:clave` —la ruta que la fila del listado ya abría
por su clave— y en `/tablas-decision/nueva`. El botón «Nuevo» de la pestaña va
ahí por la propiedad `alta_en` del recurso (`frontend/src/lib/modulos.ts`), que
cualquier pestaña puede usar cuando su alta no cabe en un formulario de campos.
`validar` y `probar` van en `acciones_ocultas`: son botones del editor.

- **El estado de la pantalla guarda texto**, y `aTablaApi` lo convierte al tipo
  de cada columna al enviar (número, sí/no, lista; lo que empieza por `@` se
  manda tal cual). Con `en`, el valor se parte por comas.
- **Probar sin guardar**: `POST /api/v1/tablas-decision/probar` —
  `services/orchestrator/api_tablas_decision.py`— valida la tabla y la evalúa con
  `decision.evaluar`, que ya aceptaba un diccionario. Exige `proceso:read`. Va
  montada en `ROUTERS_APROBACIONES` para no tocar `main.py` ni `api.py`.
- El guardián `ninguna_lista_echa_a_las_demas` cuenta ahora como acotada cada
  `<Rejilla>` sin `acotada={false}`: lo hace el componente, y sin contarlo la
  salida fácil era repetir la clase a mano.

### 4.6.41 Decidir una aprobación desde el correo (CRM-00.03.05.12)

**La cadena del correo.** `aprobaciones._abrir_etapa` lo llaman tres sitios
—crear, avanzar de etapa, reaprobar— y en los tres se llama después a
`enlaces_publicos.avisar_etapa`, que, con `aprobacion_enlace_por_correo`
encendido, emite un enlace por aprobador (`emitir_enlace`: el token sólo en el
correo, en la base su hash) y el evento interno `approval.link.issued`
(`publico=False`: lleva el enlace). Identidad lo traduce en una notificación por
el canal `correo` al titular (`AVISOS` en `services/identity/notificaciones.py`,
con `solo_destinatarios`: sin titular válido no se cae a los seguidores) y el
repartidor la entrega. **Sin bus el correo no sale**: el evento se queda en
`orchestrator.eventos_salientes` hasta que el relevo lo publique. Es lo que pasa
en la pila local, que no tiene NATS.

Ojo con lo que eso implica: el texto del enlace pasa por la tabla de salida del
orquestador y por la notificación del titular en identidad. Es de un solo uso,
caduca y muere si cambia la etapa o la vuelta, que es lo que lo acota.

**La puerta pública**, `services/orchestrator/api_enlaces_publicos.py`:

| Ruta | Sin sesión | Qué hace |
|---|---|---|
| `POST /api/v1/enlace-de-aprobacion/ver` | sí | Lo mínimo para decidir; no gasta el enlace |
| `POST /api/v1/enlace-de-aprobacion/decidir` | sí | Vota como el titular, `via="correo"`; devuelve sólo `{decision, estado}` |

- El token va en el **cuerpo**, nunca en la URL de la API (acabaría en los
  registros de acceso). La página del front sí lo lleva en la suya
  (`/decidir?t=…`), que es lo que se manda por correo.
- El token no lleva el tenant. `_localizar` lee `tenant_id` y `titular_id` por
  el hash —único en toda la tabla— con una sesión `sistema=True`, y todo lo demás
  corre en una unidad de trabajo del tenant del enlace, con el titular como
  usuario del contexto.
- `_vigente` exige, además de no usado y no caducado: que la etapa del enlace
  sea la actual y esté pendiente, la solicitud pendiente, el enlace creado
  después de la última apertura de la etapa (`created_at` lo pone
  `emitir_enlace` con la hora de Python: la de la base es la del inicio de la
  transacción, anterior a la apertura), que el titular pueda decidir y no haya
  votado ya. Todo da el mismo `401 aprobacion.enlace_invalido`. Al decidir, la
  fila del enlace se bloquea (`FOR UPDATE`): dos clics a la vez no votan dos
  veces.
- **El tope por IP** lo pone el gateway (`_tope_por_ip` en
  `services/gateway/api.py`) a las rutas de `TOPES_POR_IP` en
  `crmcore/rutas_de_api.py`, con `rate_limit.exigir_tope`: mismo contador que el
  límite general (Redis si lo hay; si no, por proceso). En el servicio no
  serviría: detrás del gateway todas las peticiones llegan con su IP.
- Exentas por nombre en `test_toda_ruta_de_escritura_exige_permiso`
  (`ver_con_enlace_publico`, `decidir_con_enlace_publico`), con su motivo.

**El front**: `frontend/src/paginas/DecidirPorEnlace.tsx`, servida por
`App.tsx` antes de la comprobación de sesión y fuera del marco, como el portal.
Pide con `credentials: "omit"`: con la cookie de una sesión caducada, el gateway
contestaría «sesión caducada» a quien no necesita ninguna.

**Ajustes**: `aprobacion_enlace_por_correo`, `aprobacion_enlace_validez_horas`
(editables en caliente), `APROBACION_ENLACE_INTENTOS_POR_IP` (30),
`APROBACION_ENLACE_VENTANA_S` (3600) y `FRONT_BASE_URL` (la de la interfaz;
`PUBLIC_BASE_URL` es la de la API).

Pruebas: `tests/unit/test_decidir_desde_el_correo.py`,
`frontend/src/pruebas/decidir_por_enlace.test.tsx`.

### 4.7 CDC hacia el lago del cliente

Se manda **el hecho, no la foto**: qué cambió y de qué a qué, con secuencia para
que el receptor sepa si le falta algo. Los datos personales no salen por defecto y
lo que sale va marcado. El borrado viaja como borrado. Y la marca de progreso solo
avanza sobre lo confirmado.

---

### 4.6.42 Credenciales, sobres, encargos en el portal y reuniones en línea (CRM-00.01.04.08, CRM-06.01.02.11, CRM-00.04.05.06, CRM-06.01.03.10)

Cuatro capacidades que estaban en la API sin un botón, y lo que salió al
ponérselo.

**Credenciales de una conexión.** `GET /integraciones/conexiones/{id}/credenciales`
(`services/integration/api.py`, permiso `integracion:read`) devuelve los campos
que pide el tipo de autenticación (`conector.SECRETOS_POR_AUTH`, al lado de
`cabeceras_auth` para que no diverjan), la versión activa con `fijada_at`,
`fijada_por`, `caduca_at` y **sólo las claves** —`cifrar_dict` deja las claves en
claro; los valores no se descifran ni salen—, las anteriores y si se puede
probar. El `PUT` rechaza (422 `integracion.credencial_incompleta`) una
credencial a la que le falta un campo de su tipo y guarda `fijada_por`
(migración `20261109_1600_quien_fijo_la_credencial`, columna
`credenciales.fijada_por`). La pantalla es `componentes/CredencialesDeConexion.tsx`,
montada por `Ficha.tsx` cuando el objeto es `conexion`. Arreglado de paso:
`OperacionOut.estado_transporte` era `str` y la fila trae `{}`, así que
**declarar una operación por la API daba 500 siempre**.

**Acciones del sobre.** `SobreDeFirma.tsx` ofrece por estado `enviar` /
`recordar` / `cancelar` / `archivar-firmado`. El hallazgo: el operador real
(`main._operador_de_firma`) devuelve lo del conector, `{"registros": [...]}`, y
`firma.enviar` leía el `id` de la raíz, así que **el identificador del proveedor
no se guardaba nunca** fuera de la prueba, cuyo doble devolvía `{"id": …}`.
`firma._id_externo` lee de los dos sitios; lo usan `enviar` y
`probar_conexion`. No hay código por proveedor: cualquier proveedor que se
declare con su conexión y la operación `crear_sobre` (y las otras cuatro de
`firma.OPERACIONES`) vale.

**Encargos en el portal.** `GET /portal/mi/encargos` y
`GET /portal/mi/encargos/{id}/seguimiento` (`api_encargos.router_portal`), con
`PortalDep` y la guarda `exige_seccion_portal("encargos")`. La cuenta sale del
token del portal (`sesion.exigir_cuenta()`), nunca de la consulta; lo de otra
cuenta da 404. La sección se anuncia en `service/portal.py` (niveles `cuenta` y
`admin`) y el gateway la manda a `integration` por `SECCIONES_PORTAL` en
`crmcore/rutas_de_api.py` — hay que reiniciar el gateway y `service` al tocarlo.

**Reunión en línea.** `POST /suites/reuniones` crea la sala de verdad: elige el
perfil con `suites.perfil_de_reuniones` (el nombrado, o el único conectado con
`recursos.reuniones.endpoint`, o el que la persona autorizó), exige el
consentimiento `reuniones`/`escribir` de quien pulsa, y llama por el conector
declarativo con la credencial de la conexión del perfil
(`suites_recursos.pedir_reunion`). La forma del cuerpo es configuración del
perfil:

```json
"reuniones": {
  "endpoint": "/users/{{organizador}}/onlineMeetings",
  "incremento": "completo",
  "cuerpo": {"subject": "{{asunto}}", "startDateTime": "{{inicio}}",
             "endDateTime": "{{fin}}", "participants": {"attendees": "{{asistentes}}"}},
  "asistente": {"upn": "{{email}}"},
  "campos": {"enlace": "joinWebUrl", "id_externo": "id"}
}
```

Para Google Meet el mismo bloque apunta a `/calendars/primary/events` con
`query: {"conferenceDataVersion": "1"}`, un cuerpo con `summary`, `start.dateTime`
y `conferenceData.createRequest`, y `campos.enlace: "hangoutLink"`. El enlace
se guarda en `detalles.reunion` de la actividad **llamando a `party` por HTTP**
(`crmcore.http.interno.invocar`) con la identidad de quien pulsa: `PATCH` si se
dio `actividad_id`, `POST /activities` de tipo `reunion` si se dio
`objeto`/`objeto_id`. Si `party` falla, la sala ya existe: se devuelve el enlace
con `guardada: false` y un aviso. `GET /suites/reuniones/proveedor` dice si hay
con qué y, si no, por qué (la ficha deshabilita el botón con ese motivo). La
auditoría no guarda el enlace: es una credencial.

**Lo que falta para verlo en vivo**: declarar el perfil de la suite real
(Microsoft Graph o Google Calendar) con su `url_base` y `auth_tipo`, fijar su
credencial en la ficha de la conexión, y que cada persona conceda
`reuniones`/`escribir`. Con `oauth2_client_credentials` contra Graph hace falta
además la política de acceso a aplicaciones de Teams para el organizador; Google
no admite reuniones con credencial de aplicación sin delegación de dominio, así
que ahí va `bearer` con el token delegado. Se probó contra un doble HTTP local.

Pruebas: `tests/unit/test_integracion_cuatro_pantallas.py` (proveedores doblados
en el transporte con `httpx.MockTransport`) y
`frontend/src/pruebas/integracion_cuatro_pantallas.test.tsx`,
`frontend/src/pruebas/portal_encargos.test.tsx`.


### 4.6.43 Lote desde la tabla, duplicar, importar con reversión, traspaso y jerarquía (CRM-00.02.01.11, CRM-01.01.03.03, CRM-07.01.01.07, CRM-07.01.01.08, CRM-00.04.03.08, CRM-03.02.01.02)

Cinco capacidades declaradas hechas cuyo servidor existía a medias y no tenían
pantalla.

**Deduplicar leads al capturar.** `services/sales/dedupe_leads.py` busca por
índice —correo normalizado, teléfono sin separadores (`regexp_replace` contra
la columna cruda y confirmación normalizando), empresa canónica— y pregunta a
`party` por HTTP (`GET /data-quality/contacts/duplicates`, con identidad de
máquina y sólo `contact:read`). Correo y teléfono son concluyentes en un lead;
empresa + nombre lo son por encima de `lead_dedupe_umbral_bloqueo`. El alta
(`POST /leads`) responde `409 sales.lead_duplicado` con `candidatos`,
`contactos_consultados` y `como_continuar`; `forzar=true` crea y audita
`lead.creado_forzado`. La captura usa `lead_dedupe_captura`
(`marcar | fusionar | nada`): marca con `leads.duplicado_de_id` y
`duplicado_detalle`, o fusiona en el existente (resultado de recepción
`fusionado`, que cuenta para el tope por hora). La normalización se subió a
`crmcore/normalizacion.py`; `services/party/normalizacion.py` la reexporta.
Ajustes: `lead_dedupe_umbral_sugerencia`, `lead_dedupe_umbral_bloqueo`,
`lead_dedupe_contactos`, `lead_dedupe_espera_s`, `lead_dedupe_max_candidatos`,
`lead_dedupe_captura`. Migración `sales/20261109_1700_lead_posible_duplicado`.

En el front, `Formulario` reconoce cualquier 409 cuyo `detalle` traiga
`candidatos` (`candidatosDe`) —cuentas, contactos o leads— y, si el alta tiene
el campo `forzar`, ofrece «Es otro, crearlo igual». El alta del módulo
(`forzarTrasElAviso`) no enseña `forzar` como casilla.

**Lote desde la tabla.** `RecursoMasivo` admite `coleccion` (se monta también
`POST /<colección>/masivo`: `/accounts`, `/contacts`, `/opportunities`) y
`ficha` (toma `actualizar`/`borrar` de `montar_ficha`, registrados en
`crmcore.http.listados._OPERACIONES_DE_FICHA`; en lote, un campo que el PATCH
no admite falla la fila). La lista de operaciones admitidas va en el contrato
como `enum` del campo `operacion` —sin validar en la entrada, para conservar
el 422 que dice cuáles sí—, y por eso los routers de lote se montan **al final**
de `api.py`, después de las fichas. `Tabla` acepta `seleccion` y
`AccionesMasivas` llama al lote; borrar exige reverificación
(`stepup.requerido`).

**Duplicar.** `POST /opportunities/{id}/duplicar` copia cabecera y líneas por
`crear_oportunidad_nueva` (primera etapa, abierta) y devuelve
`oportunidad_id`. El resto de objetos se duplican en el front: «Duplicar» en
`BotonesDeRegistro` (`useDuplicar`, por la dirección `/m/<módulo>/<tipo>/<id>`)
abre `?duplicar=<id>` en el módulo, que lee la ficha y rellena el alta con
`valoresParaDuplicar` (los campos del contrato del alta, sin `forzar` ni
líneas). No se ofrece si el servidor tiene su propio `…/duplicar`.

**Traspaso.** `crmcore/http/propiedad_router.py` monta
`POST {prefijo}/transferir-propiedad` en `party-admin` (cuentas, contactos,
actividades) y en `sales-admin` (leads, oportunidades; prefijo nuevo en
`rutas_de_api`). Pantalla `/transferir-propiedad`.

**Importar y revertir.** `crmcore/datos/importaciones.py`: tabla
`importaciones` (en `party`, migración
`party/20261109_1700_importaciones_reversibles`) con la foto de antes y de
después de cada registro tocado; `importar(..., registro=[])` la rellena.
`revertir()` planifica primero y, si hay registros cambiados después, responde
`409 importacion.cambiados_despues` sin tocar nada salvo `forzar`. Rutas:
`GET /party-admin/importaciones/campos?objeto=`, `POST /party-admin/importaciones`
(simula por defecto), `GET /party-admin/importaciones`,
`POST /party-admin/importaciones/{id}/revertir`. Los campos propios se validan
también al simular. Pantalla `/importar`.

**Jerarquía.** `GET /forecast/periodos/{clave}/organigrama?fuente=territorios|mando`
(`forecast.previsión_por_organigrama`): árbol desde `territorios` +
`miembros_territorio` (el responsable cuenta) o desde `mando_replicado`, con
`compania`, `fuera_del_organigrama`, `sin_dueno` y `aviso` si la réplica está
vacía. Panel «Por jerarquía» en `PeriodoDePrevision`.

Pruebas: `tests/unit/test_dedupe_leads_al_capturar.py`,
`test_importar_y_revertir.py`, `test_party_importar_traspasar_lote_por_http.py`,
`test_sales_duplicar_jerarquia_lote_por_http.py`,
`frontend/src/pruebas/lote_duplicado_e_importar.test.tsx`.

### 4.6.44 Archivo de histórico por criterio (CRM-07.03.01.02)

`crmcore.datos.archivado` sabía archivar y consultar y no lo llamaba nadie: la
única ruta, `POST /{servicio}/volumen/archivar`, planifica sobre filas tecleadas.
Ahora `crmcore/http/volumen_router.py` monta en cada servicio, bajo
`/{servicio}/volumen/archivo`:

| Ruta | Permiso | Qué hace |
|---|---|---|
| `GET /archivo/clases` | `admin:read` | Clases de dato del servicio (`retencion.CLASES`) con sus días, el corte y las filas que movería hoy |
| `PUT /archivo/clases/{clase}` | `admin:write` | Fija los días de la clase en el ajuste `archivado_antiguedad_por_clase` del tenant (`dias: null` la devuelve al general) |
| `POST /archivo/archivar` | `admin:write` | `{clase, simular}`; simula por defecto; mueve como mucho `archivado_tope_por_pasada` filas |
| `GET /archivo` | `admin:read` | Por `clase`, `desde`/`hasta`, `registro_id` o `relacionado_con` (`jsonb_path_exists` sobre los valores de primer nivel del contenido) |
| `GET /archivo/resumen` | `admin:read` | Filas por clase y de cuándo |

El corte es `fechas.hoy(db) − días`, con el día del cliente. Ajustes nuevos
(Settings + `ClaveAjuste`): `ARCHIVADO_DIAS_POR_DEFECTO` (730),
`ARCHIVADO_ANTIGUEDAD_POR_CLASE` (`{}`), `ARCHIVADO_TOPE_POR_PASADA` (5000). Hoy
tienen tabla `filas_archivadas` `party` y `sales`; los demás contestan
`hay_archivo: false` (se mira con `to_regclass`) en vez de un 500, y
`archivar`/`desarchivar` responden 422 `archivado.sin_archivo`. Sin migración
nueva. Pruebas: `tests/unit/test_archivado_consultable.py`.

En el front, `componentes/Archivo.tsx`: `ArchivoDelServicio` en Plataforma y
cumplimiento (por el selector de servicio) y `ArchivadoDelRegistro` en la
pestaña «Relacionado» de la ficha genérica, en la de cuenta y debajo del error
de una ficha cuyo registro ya no está en la tabla viva.

### 4.6.45 Sandbox de API con datos sintéticos y consola (CRM-00.02.01.15)

`POST /integracion/sandbox` (gateway, `integracion:write`) hace ahora, en
`services/gateway/sandbox_api.py`:

1. `POST /sandboxes` a tenancy con la identidad de quien llama (necesita
   además `tenancy:write`): un tenant hijo con caducidad. No se pide la copia.
2. Para cada colección de `objetos` (vacío: `SANDBOX_API_OBJETOS`), lee el
   contrato del servicio dueño (`/api/v1/openapi.json`), resuelve el esquema
   del `POST` y genera `filas_por_objeto` cuerpos (vacío:
   `SANDBOX_API_FILAS_POR_OBJETO`): obligatorios, correos
   (`SANDBOX_API_DOMINIO_CORREO`, `example.com`) y referencias a lo ya creado,
   que se casan por el parámetro de la ruta de la ficha
   (`/accounts/{cuenta_id}` → `cuenta_id`). Se mandan al servicio con el
   tenant del sandbox, tipo `servicio` y los permisos de quien lo pidió.
3. `POST /claves-api` a identity en el tenant del sandbox, rol
   `integracion`, `dias = SANDBOX_DIAS`. Como `servicio` no pide
   reverificación: la clave no alcanza los datos de la empresa.

Devuelve `sandbox_id`, `tenant_sandbox_id`, por colección `creadas`/`pedidas`
y el primer error, y la credencial (el secreto, una sola vez). La consola
(`paginas/SandboxDeApi.tsx`, ruta `/sandbox-api`) llama con `fetch` directo,
`credentials: "omit"` y `Authorization: Bearer <clave>`, sin la cabecera de
tenant mirado. Pruebas: `tests/unit/test_sandbox_de_api.py`.

### Lo cerrado al verlo en el navegador (09-11-2026)

- `Recurso.descargas` (`frontend/src/lib/modulos.ts`, pintado por
  `componentes/Descargas.tsx` en `Modulo.tsx`): un `GET` que devuelve un
  documento y se guarda como fichero. Lo usa *Políticas de acceso* con
  `GET /api/v1/politicas-acceso/publicar` (CRM-00.05.02.06).
- «Probar un registro» en `paginas/ObjetoDelModelo.tsx` llama a
  `POST /api/v1/metadata/objetos/{nombre}/validar` (CRM-00.02.03.07).
- Login web: casilla «Recordar este equipo» → `recordar_dispositivo`; si la
  instalación no recuerda equipos (`dispositivo_confianza_dias` = 0), identity
  entra igual y lo anota (`auth.dispositivo_no_recordado`) en vez de deshacer la
  entrada con 403. Ojo: el login corre sin tenant en el contexto, así que sólo
  aplica el valor global del ajuste, no el de la empresa.
- `mfa_proveedor.verificar_en_login` audita con el `tenant_id` explícito: sin
  él, la auditoría daba 422 `auditoria.sin_tenant` en el login.
- `facturacion` → tenancy en `crmcore/rutas_de_api.py` (el gateway daba 404).
- `Cuenta.tsx` pinta `ArchivadoDelRegistro` bajo el «No existe».
- `SANDBOX_API_OBJETOS` sin `opportunities` de serie: un tenant recién creado
  no tiene embudo.

### 4.6.46 Modelos entrenados con el histórico, asistente con acciones y preguntas que se ejecutan (CRM-02.01.02.02, CRM-05.02.01.02, CRM-05.02.01.03, CRM-02.01.01.08, CRM-04.03.02.02, CRM-05.02.02.04)

**Modelos.** `services/intelligence/predictivo.py`. Lee por HTTP
(`crmcore.http.interno.invocar`) `GET /api/v1/leads`, `GET /api/v1/opportunities?estado=`
(vacío: el listado da por defecto sólo las abiertas) y, para la siguiente
oferta, `GET /api/v1/opportunities/{id}/lineas` de cada ganada. Entrenar lee con
identidad de **agente** y sólo `lead:read`/`opportunity:read`, a nombre de quien
lo pide (el modelo es del tenant entero); puntuar y segmentar leen con la
identidad de **quien pide** (`tipo=usuario`, sus permisos y roles). Sin numpy:
logística por Newton/IRLS y ridge por eliminación gaussiana (`ajustar_logistica`,
`ajustar_lineal`, `resolver`), AUC por rangos. Los rasgos se calculan con las
mismas funciones al entrenar y al puntuar (`rasgos_oportunidad`, `rasgos_lead`,
`rasgos_cuenta`), y `Historial` sólo cuenta lo cerrado antes de la fecha. Partición
por fecha (`particion`, `IA_PCT_VALIDACION`); escalado y categorías aprendidos
sólo del entrenamiento (`preparar`). `veredicto` decide la publicación.

`modelos_ml` gana `definicion` (escalas, categorías, intervalo, `origen=historico`)
y `entrenado_por`; estado nuevo `descartada`; tipo nuevo `siguiente_oferta`
(familia `recomendacion`, métricas `acierto_top`/`muestras`). Un modelo
`origen=historico` no se puntúa por `POST /ia/prediccion` (rasgos tecleados): 422
`prediccion.modelo_por_id`. Las puntuaciones se guardan en `predicciones` con
caducidad `ia_prediccion_vigencia_dias` y se reutilizan mientras el modelo sea el
mismo. Reentreno: tabla `programaciones_entreno` y tarea
`intelligence.reentreno` en `main._tareas` (cada `IA_REENTRENO_COMPROBAR_S`).

Rutas (`api_predictivo.py`): `POST /ia/predictivo/{tipo}/entrenar`
(`ia:administrar`), `GET /ia/predictivo/versiones`, `GET /ia/predictivo/programaciones`,
`PUT /ia/predictivo/{tipo}/programacion` (`ia:administrar`),
`GET /ia/predictivo/{lead|oportunidad|cuenta}/{id}?recalcular=`,
`POST /ia/predictivo/segmento` (crea en marketing `POST /segmentos` con
`cuenta.objeto_id en […]` y `POST /segmentos/{id}/congelar`).

**Asistente.** `asistencia.conversar` recupera con `indice.buscar` (artículo,
caso resuelto, lección; descarta por debajo de `ia_asistente_parecido_minimo`) y
contesta con `rag.responder`. `acciones_asistente.py`: lista cerrada `ACCIONES`
(tarea, nota, caso, lead) con ruta, permiso, campos fijos y declarados; el puerto
`_proponer_accion` (`puerto.py`) elige una o ninguna; se guarda en
`acciones_asistente` como `propuesta` con caducidad
(`IA_ASISTENTE_CADUCIDAD_HORAS`). `POST /ia/asistente/acciones/{id}`
`{confirmar, argumentos}` la ejecuta por `invocar` con la identidad de quien
preguntó y `Idempotency-Key=asistente-{id}`; sólo la confirma quien la pidió
(403), una vez (409), con los obligatorios (422). `GET /ia/asistente/acciones`.

**Preguntas a los datos.** `consulta_natural.py`, desde `POST /ia/preguntar-datos`
cuando no se manda `modelo_datos`. Esquema: `GET /api/v1/{servicio}/filtros`
(servicios en `IA_CONSULTA_SERVICIOS`), campos filtrables de los objetos más
parecidos a la pregunta (`/{servicio}/filtros/{objeto}`), valores de estado
(`/{servicio}/estados/{objeto}`) y los parámetros con valor por defecto del
listado, leídos de su OpenAPI. El plan (`rag.preguntar_a_los_datos`, prompt en
`puerto._traducir_a_plan`) se normaliza, se valida y se ejecuta paginando el
listado con los operadores de URL (`A_URL`); `contiene`/`empieza` no se
ejecutan. Tope `IA_CONSULTA_TOPE_FILAS`. La respuesta trae `consulta`
(ruta, parámetros, `por_defecto_del_listado`), `parcial` y `campos_tapados`.

**Arreglado al construirlo:** `rag.RE_CITA` no leía citas agrupadas («[1, 2]»),
que es como cita el modelo real, y descartaba respuestas bien citadas.

Ajustes nuevos (`services/intelligence/ajustes.py`, editables por tenant los que
llevan clave): `IA_AUC_MINIMO_PUBLICAR`, `IA_MEJORA_MINIMA_REGRESION_PCT`,
`IA_MINIMO_CASOS_REGRESION`, `IA_REENTRENO_DIAS`, `IA_REENTRENO_COMPROBAR_S`,
`IA_ENTRENO_TOPE_REGISTROS`, `IA_REGULARIZACION_L2`, `IA_ENTRENO_ITERACIONES`,
`IA_PROPENSION_HORIZONTE_DIAS`, `IA_CATEGORIAS_MAXIMAS`, `IA_MINIMO_POR_CATEGORIA`,
`IA_PREDICCION_VIGENCIA_DIAS`, `IA_NBO_MINIMO_CUENTAS`, `IA_NBO_TOPE_OPORTUNIDADES`,
`IA_NBO_RECOMENDACIONES`, `IA_CONSULTA_SERVICIOS`, `IA_CONSULTA_OBJETOS_DETALLADOS`,
`IA_CONSULTA_TOPE_FILAS`, `IA_CONSULTA_FILAS_DEVUELTAS`, `IA_ASISTENTE_FRAGMENTOS`,
`IA_ASISTENTE_PARECIDO_MINIMO`, `IA_ASISTENTE_CADUCIDAD_HORAS`. Migración
`alembic/versions/intelligence/20261109_1604_modelos_entrenados_con_el_historico_y_.py`.
Pruebas: `tests/unit/test_ia_predictivo_entrenado.py`,
`tests/unit/test_ia_predictivo_por_http.py`,
`frontend/src/pruebas/modelos_predictivos_y_asistente.test.tsx`.

### 4.6.47 SLA del proveedor guardado, firma desde la oportunidad, renovaciones solas y derivar desde el caso (CRM-09.01.01.08, CRM-03.03.02.07, CRM-03.03.02.10, CRM-04.01.01.08, CRM-04.05.01.02)

**SLA del proveedor** (`services/service/proveedores_sla.py`). Tabla nueva
`acuerdos_proveedor` (por `proveedor_clave`, la clave de
`integration.proveedores_servicio`) y columna `entitlements.proveedor_clave`;
migración `alembic/versions/service/20261109_1900_acuerdo_del_proveedor.py`.
`revisar()` compara cada derecho activo con proveedor —lo prometido sale de la
versión activa de su `DefinicionSLA`: primera respuesta y resolución— con
`del_proveedor()` (acuerdo guardado; resolución vacía = `plazo_horas` de
integración). Los proveedores se leen por HTTP (`GET /api/v1/proveedores-servicio`
con `crmcore.http.interno.invocar`, espera `SLA_PROVEEDOR_ESPERA_S`); si no
contesta, `integracion_respondio=false` y `proveedor_existe=null`. Rutas bajo
`/api/v1/sla-proveedores`: `GET /revision`, `GET|PUT|DELETE /acuerdos[/{clave}]`,
`PUT /entitlements/{id}/proveedor`, `POST /comparar` y
`POST /maximo-que-se-puede-prometer` (con `proveedor_clave` usa lo guardado).
La constante de una hora pasa a `SLA_PROVEEDOR_HORAS_PROPIAS`. Pantalla:
`paginas/SlaProveedores.tsx`, ruta `/sla-de-proveedores`.

**Firma desde la oportunidad** (`services/sales/firma_oportunidad.py`).
`POST /api/v1/opportunities/{id}/enviar-a-firma` crea el sobre en integración
(`POST /api/v1/firma/sobres`, `objeto_origen=oportunidad`,
`documento_id=presupuesto:<id>` o `contrato:<id>`) y lo manda si `enviar`.
`GET /api/v1/opportunities/{id}/firma` pregunta al sobre
(`/firma/sobres/{id}/evidencia`) y aplica lo mismo que el consumidor
`consumir_firma`: los dos llaman a `aplicar_estado()`, que escribe
`campos.firma_*` y, si el estado es `completado` y el embudo está en
`FIRMA_ETAPA_POR_EMBUDO` (json, `{clave embudo: clave etapa}`), mueve la etapa
con `cambiar_etapa` —con criterios de salida; si fallan, `firma_etapa_error`—.
Idempotente por sobre (`firma_etapa_aplicada`). Espera: `FIRMA_ESPERA_S`.

**Renovaciones** (`services/sales/presupuestos.py`). `revisar_renovaciones`
abre una oportunidad por contrato al llegar el preaviso, en `RENOVACION_EMBUDO`
(vacío: el embudo por defecto), con el importe del contrato y `fecha_cierre` =
fin; enlace en `contratos.oportunidad_renovacion_id` (migración
`alembic/versions/sales/20261109_1900_oportunidad_de_renovacion.py`) y
`campos.renovacion_de_contrato_id`. Apagado con
`RENOVACION_CREAR_OPORTUNIDAD=false`. Corre sola: tarea `sales.renovaciones` en
`services/sales/main.py:_tareas()`, cada `RENOVACION_REVISAR_S`, sin correr al
arrancar.

**Derivar y abono.** `paginas/Caso.tsx` (Más › Derivar) llama a
`POST /api/v1/escalado/derivar/{caso_id}`; la ficha del caso devuelve ahora
`equipo`. `componentes/ResolucionesDeDevolucion.tsx`, pintado por `Ficha.tsx`
para `devolucion`, lista `resoluciones` y llama a
`POST /api/v1/devoluciones/resoluciones/{id}/abono`. Arreglado de paso: una
línea libre de presupuesto sin precio daba 500 (`Decimal("None")`).
Pruebas: `tests/unit/test_sla_proveedor_firma_y_renovaciones.py`.

### 4.6.48 Transcripción de reuniones, variantes generadas y modo voz (CRM-01.02.01.05, CRM-01.02.01.06, CRM-02.04.01.04, CRM-04.02.01.08)

Hasta el 09-11-2026 las tres simulaban: `POST /transcripciones` recibía el
texto ya transcrito, `POST /variantes` los textos ya escritos y `/voz/*` eran
reglas sobre texto ya reconocido. Las funciones puras siguen (`transcripcion.py`,
`variantes.py`, `voz.py`) y ahora las usa esto:

**Transcripción** (`services/intelligence/reuniones.py`, rutas en
`api_reuniones.py`). El proveedor es una **conexión de `integration`** (perfil
sobre `services/integration/conector.py`): `POST /transcripciones/proveedor`
instala una plantilla (`PLANTILLAS`: `deepgram` —envío por enlace— y
`google_stt` —audio en base64 en la petición—) dando de alta la conexión y su
operación por `POST /integraciones/conexiones` y `/operaciones`, con la
identidad de quien lo pide, y fija por tenant `ia_transcripcion_conexion` y
`ia_transcripcion_envio`. La credencial se pone en la ficha de la conexión;
`url_base` admite otra dirección (un compatible, un proxy, un doble). La
respuesta se mapea a `texto`, `confianza` y `segundos`; varios registros se
juntan. `POST /transcripciones/reuniones/transcribir` (multipart: `fichero` | `enlace` |
`texto`, `objeto`, `objeto_id`, `base_para_grabar`, `participantes_avisados`)
comprueba la base para grabar ANTES de nada, sube el audio como adjunto del
registro (`POST /adjuntos/{objeto}`, multipart firmado con
`crmcore.http.interno.cabeceras_de`), pide el enlace firmado si el envío es por
enlace, invoca la operación (`/integraciones/conexiones/{id}/operaciones/{op}/invocar`),
resume y extrae con el puerto (`puerto._resumir_reunion`, uso `resumen`,
anotado en `llamadas_ia` como `resumen_reunion`), filtra con
`transcripcion.proponer_extraidos` y guarda en `transcripciones_reunion`
(`cita_literal` dice si la cita está en lo transcrito). Si el resumen falla, la
transcripción se guarda igual con estado `sin_resumen`. `GET
/transcripciones/reuniones?objeto=&objeto_id=` lista; `POST
/transcripciones/reuniones/{id}/compromisos/{n}` confirma (crea la tarea en
`POST /activities` con la identidad de quien confirma, colgada del
`objeto`/`cuenta_id`/`contacto_id` de la actividad madre, con
`detalles.transcripcion_id`) o descarta. Pantalla:
`frontend/src/componentes/TranscripcionDeReunion.tsx`, en la ficha de las
actividades `llamada`, `reunion` y `visita`.

**Variantes** (`variantes_copy.py`): `POST /variantes/generar` (base, objetivo,
canal, cuántas ≤ `IA_VARIANTES_MAXIMAS`) llama a `puerto._redactar_variantes`
(uso `redaccion`), quita repetidas y la base, marca afirmaciones y los
`{{marcadores}}` perdidos, y guarda en `variantes_copy` por lote. `GET
/variantes/generadas?objeto=&objeto_ref=`, `POST
/variantes/generadas/{id}/decidir` (de una en una, con `texto_final` y
`motivo`) y `POST /variantes/generadas/{id}/ganadora` (sólo aprobadas; desmarca
las del lote). Pantalla: `componentes/VariantesDeCopy.tsx`, en la ficha de una
plantilla de correo (`objeto=plantilla_correo`, `objeto_ref` = su clave).

**Voz**: `POST /voz/dictado` (multipart) transcribe con el mismo proveedor y no
guarda nada; con envío por enlace contesta 409 `voz.proveedor_por_enlace`
(habría que guardar la voz). El front (`paginas/Asistente.tsx`, `useVoz`) usa
`SpeechRecognition`/`webkitSpeechRecognition` si existe, si no `MediaRecorder` +
`/voz/dictado`, pregunta a `POST /ia/asistencia/conversar` y lee con
`speechSynthesis`.

**Arreglado al construirlo (crmcore, afecta a todos los servicios):**
`crmcore/http/idempotency.py` leía el cuerpo crudo de un formulario que FastAPI
ya había leído — **toda subida de fichero desde la interfaz** (que siempre manda
`Idempotency-Key`) daba 500 «Stream consumed»; ahora la huella sale del
formulario. Y `GET /adjuntos/{objeto}/enlace/{token}` pedía `DbDep`, que exige
tenant: el enlace firmado respondía 401 siempre; ahora comprueba la firma y lee
como sistema. Prueba: `tests/unit/test_adjuntos_enlace_y_formulario_por_http.py`.

Ajustes nuevos: `IA_TRANSCRIPCION_CONEXION`, `IA_TRANSCRIPCION_OPERACION`,
`IA_TRANSCRIPCION_ENVIO` (`enlace` | `contenido`), `IA_TRANSCRIPCION_MAX_MB`,
`IA_TRANSCRIPCION_CARACTERES_MODELO`, `IA_VARIANTES_MAXIMAS`, todos con clave por
tenant. Migración
`alembic/versions/intelligence/20261109_1831_transcripciones_de_reunion_y_variantes_.py`.
Pruebas: `tests/unit/test_reuniones_y_variantes_ia.py`,
`frontend/src/pruebas/reuniones_variantes_y_voz.test.tsx`. Visto en el
navegador contra un doble local del proveedor (forma Deepgram y Google) y el
modelo de verdad; falta verlo contra un proveedor de transcripción real.

### 4.6.49 Análisis sobre los datos del CRM, instantáneas programadas y consulta federada (CRM-05.01.03.04, CRM-05.01.03.05, CRM-05.01.03.06, CRM-05.01.01.05, CRM-05.01.03.07)

Pantalla `/analisis-crm` (`frontend/src/paginas/AnalisisCrm.tsx`). Servidor en
`services/analytics`:

| Ruta | Qué hace |
|---|---|
| `GET /analisis/crm/cohortes?periodo=&periodos=` | Retención de cuentas por cohorte de alta |
| `GET /analisis/crm/embudo?pipeline_id=&desde=` | Conversión y mediana de días por etapa |
| `GET /analisis/crm/actividad?desde=` | Actividades frente a ganadas por persona, con coeficiente |
| `POST /informes/{id}/programar` con `accion: instantanea` | Programa la instantánea; sin destino |
| `DELETE /informes/programaciones/{id}` | Quita una programación (no toca las instantáneas) |
| `POST /almacen/federadas/{fuente}/consultar` | Ejecuta la consulta federada por el conector |

**De dónde se leen los hechos** (`datos_crm.py`, clase `Lector`): del almacén
(`tablas_analiticas` con `objeto` = `cuenta`, `actividad` u `oportunidad`,
cargada y con las columnas de `COLUMNAS`), o si no por la API pública de
`party` y `sales` con `crmcore.http.interno.invocar` y **la identidad de quien
pregunta** (`tipo="usuario"`). El historial de etapas se pide en bloque
(`GET /opportunities/historial-etapas?pipeline_id=&created_at__desde=`, páginas
de hasta 200 de `sales`): desde el 09-11-2026 ya no es una llamada por
oportunidad, y el tope de 100 historiales (`analisis_max_historiales`) se ha
quitado; vale el mismo `analisis_max_registros` que el resto de objetos. Cada respuesta trae `procedencia` por
objeto: `fuente`, `leidos`, `recortado`, `sin_permiso`, `no_leido` y
`estado_http`.

**Ajustes** (`services/analytics/ajustes.py`, editables en Admin):
`analisis_max_registros` (2000), `analisis_minimo_correlacion` (8),
`analisis_dias_ventana` (365).

**Instantáneas programadas.** Migración
`alembic/versions/analytics/20261109_1200_instantaneas_programadas.py`: columna
`accion` (`enviar` | `instantanea`, por defecto `enviar`) en
`programaciones_informe`. `correr_programadas` —el barrido que ya corría cada
`TAREA_INFORMES_INTERVALO_S`— llama a `tomar_instantanea` cuando toca una de
instantánea. Ejecutar el informe sigue siendo de contecintelligence (RT-4): sin
el CRM registrado como fuente, la instantánea falla con su 409 y la programación
apunta el error y cuenta el fallo como un envío.

**Consulta federada.** La fuente declara en su `config`
`{"conexion_id": "<id de integration>", "operaciones": {"<objeto>": "<clave>"}}`.
Se invoca `POST /integraciones/conexiones/{id}/operaciones/{clave}/invocar` con
`parametros = {objeto, campos, filtros, limite}`, plazo `timeout_s` de la
fuente, y se recorta a `tope_filas`. Que la operación sea de lectura lo
garantiza quien la declara: integration no publica la definición de una
operación, así que analytics no puede comprobar su método.

---

### 4.6.50 La suite de verdad: avisos y consultas en el chat, reuniones registradas, referencias guardadas y el RAT pintado (CRM-06.01.01.03, CRM-06.01.01.04, CRM-06.01.03.08, CRM-06.01.03.09, CRM-06.01.03.12, CRM-06.01.03.18)

Hasta el 09-11-2026 eran funciones que componían un diccionario y no llamaban a
nadie. Lo que hay ahora, todo en `services/integration`:

- **Avisos al chat** (`colaboracion.mandar_aviso`, `POST
  /api/v1/canales-chat/{clave|id}/aviso`). POST al `url_entrante` del canal por
  `crmcore.red.cliente_seguro` (guard de SSRF), cuerpo renderizado con
  `conector._renderizar` sobre el ajuste `chat_plantilla_aviso` (`{{texto}}`,
  `{{enlace}}`, `{{objeto}}`, `{{objeto_id}}`). El enlace es
  `{chat_url_crm}/abrir/{objeto}/{id}`; la ruta del front `/abrir/:tipo/:id`
  (`paginas/AbrirRegistro.tsx`) resuelve el módulo con `moduloDeObjeto`. El
  resultado queda en `canales_chat.ultimo_aviso_at/ok/detalle`. La ruta acepta
  la clave o el id porque la ficha genérica llama a las acciones con el id.
  `canales_chat.recibe_avisos` marca a qué canales va el evento
  `automatizacion.aviso` (consumidor `colaboracion.consumir_aviso`, grupo
  `integration-avisos-chat`); **sin bus no llega**, y entonces el aviso sólo
  sale por la ruta.
- **Consulta desde el chat** (`colaboracion.contestar_consulta`). Tras la firma y
  la orden admitida, `usuario_externo` (correo) se resuelve con
  `GET /api/v1/interno/usuarios/{tenant}/por-correo/{correo}/alcance` (firma
  interna) y el registro se pide con `crmcore.http.interno.invocar` con ese
  `principal_id`, sus `roles` y sus `permisos`, `tipo=usuario`. La colección del
  objeto sale de `/{servicio}/filtros` de cada servicio (cacheada en proceso).
  Se devuelven sólo los campos de `CAMPOS_RESPUESTA` y los tapados se anuncian.
- **Reuniones** (`buzon.registrar_reuniones`, llamado por `POST
  /buzones/{id}/sincronizar`). Para buzones de calendario: `GET
  /api/v1/contacts?email__en=` y `POST /api/v1/activities` (tipo `reunion`,
  `detalles.asistentes` con `email`/`contacto_id`/`nombre`), con la identidad de
  quien sincroniza; `elementos_buzon.actividad_id` evita repetirla y un fallo
  deja `resultado=error` para reintentar. Arreglado de paso: `ocurrido_at` llega
  como texto por HTTP y se guardaba tal cual (500 al responder).
- **Referencias** (`referencias_suite.py`, `api_referencias.py`, tabla
  `referencias_suite`): `GET/POST /api/v1/referencias-suite`, `POST
  /{id}/abrir`, `DELETE /{id}` (borrado lógico). Abrir ejecuta la operación del
  ajuste `suite_op_resolver_referencia` (por defecto `resolver_referencia`) de
  la conexión del perfil de suite con `{referencia, tipo, usuario_id}` y lee
  `existe` y `tiene_acceso` del primer registro; sin perfil u operación,
  `estado=no_comprobable`. La ruta `referencias-suite` está en
  `crmcore/rutas_de_api.py`. Pantalla: `componentes/ReferenciasDeSuite.tsx` en
  `Ficha.tsx`.
- **RAT** (`tratamientos.py`): declarados `llamadas_telefonicas`,
  `hechos_compensacion` y `referencias_suite`; `Plataforma.tsx` pinta cada
  tratamiento con finalidad, base legal y plazo.

Ajustes nuevos (`services/integration/ajustes.py`, con clave en caliente):
`CHAT_PLANTILLA_AVISO`, `CHAT_ESPERA_S`, `CHAT_URL_CRM`,
`SUITE_OP_RESOLVER_REFERENCIA`. Migraciones
`alembic/versions/integration/20261109_1833_telefonia_compensacion_y_referencias_de_.py`
y `20261109_1838_ultimo_aviso_del_canal_de_chat.py`. Pruebas:
`tests/unit/test_suite_de_verdad.py` (webhook y origen como servidores HTTP de
verdad en un puerto). Visto en el navegador contra un webhook local; falta verlo
contra Teams/Slack y contra un almacenamiento real que resuelva permisos.

### 4.6.51 Telefonía, marcador y compensación externa de verdad (CRM-04.02.01.05, CRM-03.03.01.05, CRM-03.02.03.04)

Hasta el 09-11-2026, `/telefonia/*`, `/marcador/*` y `/compensacion/*` eran
funciones puras. Las rutas puras siguen (son calculadoras del contrato); lo
nuevo:

- **Tablas** (migración
  `alembic/versions/integration/20261109_1833_telefonia_compensacion_y_referencias_de_.py`):
  `llamadas_telefonicas` (única por `tenant_id, id_externo`; eventos, IVR,
  transferencias, grabación, `actividad_id`, `registro_error`) y
  `hechos_compensacion` (única por `tenant_id, tipo, referencia`; `enviado`,
  `respuesta`, `comision_motor`, `comision_casa`, `diferencia`).
- **Perfil** = una `Conexion` con `config.clase` `telefonia` o `compensacion`
  (`PUT /telefonia/perfil {conexion_id, webhook}`, `PUT /compensacion/motor
  {conexion_id}`). Las operaciones se invocan con `services/integration/operar.py`
  (busca la operación declarada, ejecuta el conector y apunta la traza en el
  monitor también si falla).
- **Telefonía** (`services/integration/telefonia.py`, `api_telefonia.py`):
  `POST /telefonia/avisos` (webhook; `integracion:write`) traduce con
  `conector.mapear` el `webhook` del perfil a `CAMPOS_AVISO` y aplica `ingerir`:
  idempotente por `id_externo`; en «entrante» identifica con `GET
  /api/v1/contacts?telefono__en=` / `movil__en` y `GET /api/v1/accounts?telefono__en=`
  (variantes del número) y lee la última actividad y el último caso, con la
  identidad de quien manda el aviso; en `colgada`/`perdida` crea la actividad
  `llamada` (`POST /api/v1/activities` + `completar`) una sola vez. `POST
  /telefonia/llamar`, `GET /telefonia/sonando` (la ficha emergente, con
  `telefonia_ficha_emergente_s` y `telefonia_sondeo_s`), `GET /telefonia/llamadas`,
  `GET /telefonia/llamadas/{llamada_telefonica_id}`, `POST
  …/{id}/transferir` y `…/{id}/resultado`.
- **Marcador** (`services/service/marcador.py`, bloque `/marcador` de
  `services/service/api.py`): `POST /marcador/llamar` pregunta a party
  (`GET /contacts/{id}` y `/consentimientos`), aplica `marcador_grabar_por_politica`
  y llama a `POST /api/v1/telefonia/llamar`; `POST /marcador/colgar` con
  `llamada_id` anota y aplica las obligaciones (`PATCH /contacts/{id}
  {no_contactar}`, `POST /activities` con `vence_at`). Los dos con `activity:write`.
- **Compensación** (`compensacion.py`, `api_compensacion.py`): `POST
  /compensacion/envios/recoger` (`GET /api/v1/opportunities?estado=ganada&fecha_cierre_real__desde…`),
  `/envios/manual`, `/envios/enviar` (operación `compensacion_op_enviar` con
  `{"hechos": [...]}`; la respuesta se casa por `referencia`), `/envios/calculo`
  (`compensacion_op_calculo` con `desde`/`hasta`), `/envios/conciliar` (suma por
  `origen_id` las líneas de `GET /api/v1/liquidaciones/{id}` del periodo) y `GET
  /compensacion/envios`. El mapeo de la operación debe dar `referencia`,
  `comision`, `periodo` y `cerrado`.
- **Ajustes** (`services/integration/ajustes.py` y `config_parts/_limits.py`):
  `telefonia_op_originar`, `telefonia_op_transferir`, `telefonia_espera_s`,
  `telefonia_ficha_emergente_s`, `telefonia_sondeo_s`, `compensacion_op_enviar`,
  `compensacion_op_calculo`, `compensacion_tolerancia`, `compensacion_espera_s`,
  `marcador_grabar_por_politica`, `marcador_espera_s`.
- **Front**: `paginas/Telefonia.tsx` (`/telefonia`), `paginas/CompensacionExterna.tsx`
  (`/compensacion-externa`), `componentes/Marcador.tsx` (ficha de contacto y de
  cuenta) y `componentes/LlamadaEntrante.tsx` (en el marco).
- **Pruebas**: `tests/unit/test_telefonia_de_verdad.py` y
  `tests/unit/test_compensacion_de_verdad.py`, con la centralita y el motor como
  servidores HTTP de verdad en un puerto.
- **Contra un proveedor real** falta conectarlo: declarar sus dos operaciones con
  su URL y su autenticación, el mapeo de su aviso, y darle una clave de API con
  `integracion:write` para `POST /telefonia/avisos`.

### 4.6.52 El tablero mueve por la acción propia del campo, y el rechazo dice sus motivos

- **Qué fallaba.** La vista «Por columnas» de Oportunidades agrupa por `etapa`
  (el nombre) y sólo dejaba arrastrar si el `PATCH` del registro admitía ese
  campo. La etapa no se edita: se mueve con `POST /opportunities/{id}/etapa`
  `{etapa_id}`, que comprueba criterios de salida y cierra si es terminal. Así
  que ninguna tarjeta se podía coger. El embudo (`Pipeline.tsx`) sí movía.
- **Cómo se resuelve, sin listas.** `Modulo.tsx` descubre del contrato las
  rutas `{ficha}/{campo}` con `POST` cuyo cuerpo lleva `{campo}_id`
  (`accionesDeCampo`). Si el campo de agrupación no es editable por `PATCH`
  pero tiene acción propia, el tablero mueve con ella y vuelve a pedir la
  lista (una etapa terminal cambia también el estado).
- **El identificador de la columna** sale de las filas que ya están en ella
  (`idDeLaColumna` en `Vistas.tsx`): sólo valen las que comparten con la
  arrastrada las demás referencias a catálogo —los pares `x_id` + `x`, como
  `pipeline_id` + `pipeline`—, para no mover a la etapa homónima de otro
  embudo. Si queda más de un candidato no se mueve y se dice por qué.
- **Los motivos del rechazo a la vista.** `Estados.Error` pinta
  `detalle.problemas` (textos u objetos con `motivo` y `producto`/`otro`/
  `campo`) como lista, además del detalle técnico plegado. Lo usa, por ejemplo,
  `presupuesto.configuracion_invalida` (CRM-03.03.02.02).
- **Pruebas**: `frontend/src/pruebas/tablero_mueve_por_su_accion.test.ts` y
  `el_error_ensena_sus_problemas.test.ts`. Visto en el navegador el
  09-11-2026: 50 tarjetas arrastrables y `POST …/etapa` 200 al soltar.

### 4.6.53 Integración cuenta lo que ve: señales de identidad, respuestas a cadencias y número erróneo (CRM-01.01.05.02, CRM-03.03.01.04, CRM-03.03.01.05)

Tres rutas de otros servicios estaban escritas y nadie las llamaba desde
integración. Ahora se llaman por HTTP (`crmcore.http.interno.invocar`), con la
identidad de quien pide o, sin persona, la del sistema (el tenant como
principal de máquina y sólo `contact:write`).

- **Señales de identidad → party** (`services/integration/senales_identidad.py`).
  Tabla `senales_identidad_salientes` (clave única tenant + origen + referencia
  + tipo; estados `pendiente`, `enviada`, `error`, `rechazada`). Se anota y se
  manda a `POST /api/v1/calidad-dato/identidades/observar`; si party no contesta
  o no deja (401/403/408/429/5xx), queda en `error` y la reintenta la tarea
  `integration.senales_identidad` (cada `TAREA_INTEGRACIONES_INTERVALO_S`); un
  4xx de validación queda `rechazada` y no se reintenta. Nunca tumba la entrada.
  Fuentes que existen en integración:
  - `canales_entrada.registrar` (`POST /canales-entrada/interacciones`): el
    interlocutor de correo y calendario como `email`, el de SMS y voz como
    `telefono`, con su contacto si viene atribuido; al atribuir a posteriori
    se vuelve a mandar con el contacto. El chat, la CLI y el agente no: el
    identificador de chat no es un tipo de party y los otros son usuarios.
  - `telefonia.ingerir`: el número de la llamada entrante, con el contacto
    reconocido.
  - `buzon.avisar_respuestas`: la dirección de quien contesta, si el correo
    tiene que ver con el CRM o le sacó de una cadencia.
  - Lo programado (`programador._aterrizar`), por ejemplo el maestro del ERP:
    sólo si la definición de la operación declara
    `"senales_identidad": {"campo": "tipo"}` (p. ej. `{"codigo": "id_erp",
    "cif": "nif"}`); las manda la tarea con la identidad del sistema.
  - **No existen en integración**: el rastreo web (cookie) y la app; no entran
    por este servicio.
- **La respuesta del buzón saca de las cadencias.** `elementos_buzon` guarda
  `remitente` (del campo `remitente` o `de` del elemento, sólo si es correo,
  `direccion` entrante —se supone si no viene— y no es el propio buzón) y
  `respuesta_cadencia` (`""`, `pendiente`, `avisada`, `error`).
  `POST /buzones/{id}/sincronizar` llama después a
  `POST /api/v1/cadencias/respuesta` `{email, tipo: "respondio"}` una vez por
  mensaje y devuelve `respuestas: {avisadas, sacadas_de_cadencias, errores}`;
  lo que falla se reintenta en la siguiente sincronización. Si sales no sacó a
  nadie y el correo no tenía relación con el CRM, se borra el remitente.
  `registrar_reuniones` recoge ahora también los correos registrados
  (`por_registrar_como_actividad`) como actividad `email` en party.
- **Número erróneo.** `POST /telefonia/llamadas/{id}/resultado` con el
  resultado del ajuste `TELEFONIA_RESULTADO_NUMERO_ERRONEO` (`numero_erroneo`)
  hace `PATCH /api/v1/contacts/{contacto}` `{estado_telefono}` con el valor de
  `TELEFONIA_ESTADO_TELEFONO_ERRONEO` (`erroneo`; party no tiene vocabulario
  cerrado para ese campo). Queda como evento `telefono_erroneo` en la llamada
  y sale en `telefono_marcado` (`marcado`, o `porque`). El marcador
  (`services/service/marcador.py`) lo pasa a `aplicadas` o `pendientes`.
- **Ajustes** (`services/integration/ajustes.py`, editables en Admin):
  `senales_identidad_espera_s`, `senales_identidad_reintentos`,
  `senales_identidad_lote`, `telefonia_resultado_numero_erroneo`,
  `telefonia_estado_telefono_erroneo`.
- **Migración**: `alembic/versions/integration/20261109_2219_senales_de_identidad_y_respuestas_del_.py`.
- **Pruebas**: `tests/unit/test_senales_y_respuestas_de_los_canales.py`.

### 4.6.54 Ficha buena y umbral del lead, dueño de la oportunidad, historial en bloque y renovación de un contrato (CRM-01.01.04.06, CRM-01.01.04.02, CRM-03.03.02.10)

- **La decisión, en el núcleo.** `crmcore/datos/supervivencia.py` tiene
  `ESTRATEGIAS`, `resolver_valor`, `validar_confianzas` y `componer_campos`
  (valores, procedencia, a revisar y fuentes con las reglas `{campo|*:
  {estrategia, confianza_por_fuente}}`). `services/party/mdm.py` la reexporta y
  `party/golden.py` compone con ella; `sales` también, sin importar a `party`.
- **Ficha buena del lead** (`services/sales/golden_leads.py`, rutas en
  `api_calidad_leads.py`, montadas antes que las de leads). Mismas rutas que
  `/calidad-dato` de party bajo `/api/v1/leads/calidad-dato`:
  `GET /golden/reglas/lead`, `PUT|DELETE /golden/reglas/lead/{campo}`
  (`lead:configurar`), `GET /golden/candidatas`,
  `POST /golden/lead/{id}/componer` `{aplicar}` (`lead:write`),
  `GET /golden/lead/{id}`. Campos: `CAMPOS` (nombre, apellidos, empresa, cargo,
  email, teléfono, web, país). Fuentes: `crm` (la ficha), el canal de cada
  `campos.capturas_fusionadas` y `duplicado` (leads con `duplicado_de_id`).
  Migración `alembic/versions/sales/20261109_2200_ficha_buena_del_lead.py`
  (`reglas_supervivencia_lead`, `golden_leads`).
- **Umbral del lead por objeto.** `GET|PUT /api/v1/leads/calidad-dato/umbrales-duplicado`
  `{por_objeto: {lead|contacto: {sugerencia, bloqueo}}}` guarda el ajuste
  `lead_dedupe_umbral_por_objeto`; lo que falta sale de
  `lead_dedupe_umbral_sugerencia`/`_bloqueo`. `dedupe_leads._ajustes` lo lee una
  vez por alta; frente a contactos, la sugerencia propia filtra lo que party
  propone (sin propia no se filtra dos veces).
- **Compensación con reparto vacío: por qué.** Medido con la identidad de
  integration (`identidad_de`: permisos y roles de quien pulsa, tipo usuario o
  agente): `GET /opportunities?estado=ganada&fecha_cierre_real__…` **sí trae
  `owner_id`**. Lo vacío era el dato: 160 de 162 ganadas del tenant de la
  plataforma sin dueño, porque nadie lo ponía al crear y una cerrada está
  bloqueada. Arreglo en sales: `crear_oportunidad_nueva` pone de dueño a quien
  crea si es una persona (`principal.tipo == "usuario"`); ajuste
  `oportunidad_dueno_quien_crea` (true). Lo histórico sin dueño sigue sin él.
- **Historial de etapas en bloque.** `GET /api/v1/opportunities/historial-etapas`
  (`opportunity:read`, antes que `/{oportunidad_id}`): página de oportunidades
  visibles (`limite` ≤ 200, `cursor`, `estado`, `pipeline_id` y los filtros
  comunes, p. ej. `created_at__desde`) con sus cambios de etapa (sin importe ni
  fecha de cierre). `analytics/datos_crm.py` `Lector.historiales` lo recorre
  hasta `analisis_max_registros`; el ajuste `analisis_max_historiales` se ha
  quitado.
- **Revisar un contrato.** `POST /api/v1/contratos/revisar-renovaciones` admite
  cuerpo opcional `{contrato_id, contrato_ids}`; con él sólo revisa esos y
  devuelve `no_revisados` `[{contrato_id, porque}]`. Botón en la ficha del
  contrato: `frontend/src/componentes/RenovacionDeContrato.tsx`.
- **Pantalla**: `CalidadDelDato.tsx` admite `lead` en ficha buena y reglas, y
  las filas «Lead frente a otro lead / a un contacto» en umbrales.
- **Pruebas**: `tests/unit/test_lead_ficha_buena_historial_y_renovacion.py`,
  `tests/unit/test_analitica_sobre_el_crm.py`.

### 4.6.56 Claves de API, sandbox, equipo de confianza, consumo y borrar sin conexión (CRM-00.02.04.06, CRM-07.02.01.02, CRM-00.05.01.20, CRM-00.01.06.07, CRM-06.02.01.04)

- **Secreto de una vez.** `ClaveApiCreada.secreto` lleva
  `json_schema_extra={"x-una-vez": True}`. `frontend/src/lib/contrato.ts`
  `camposDeUnaVez(documento, ruta, metodo)` lee las respuestas 2xx del alta y
  `Modulo.tsx` pinta `componentes/SecretoDeUnaVez.tsx` con esos campos (sólo en
  memoria; «Ya lo he copiado» lo quita). `ClaveApiOut` devuelve
  `ips_permitidas`. El alta sigue exigiendo reverificación (`stepup.requerido`);
  la pantalla genérica no tiene flujo para pedirla y enseña el error.
- **Sandbox.** `crmcore/datos/copia_sandbox.py`: `contactos_en_la_muestra`
  (contactos enlazados a una cuenta de la muestra por cualquier tabla con
  `cuenta_id` y `contacto_id`, más los sueltos por su hash) y `_entra` decide
  fila a fila: cuenta → por cuenta; `contactos` → por ese conjunto; con
  `contacto_id` y sin cuenta → por el contacto. Fuera de party el conjunto es el
  hash del contacto (subconjunto del de party). `CambioDeEstado.tsx` pide antes
  `/{servicio}/estados` (una vez por servicio) y sólo pide la máquina de los
  objetos listados: se acabó el 404 de `/tenancy/estados/sandbox`.
- **Equipo de confianza.** `factores.recordar_dispositivo` lee
  `dispositivo_confianza_dias` con `con_contexto(tenant_id=…)`, como
  `servicio._ajuste_del_tenant`.
- **Consumo.** `crmcore/consumo.py` `medido_aqui`: cada medidor en
  `db.begin_nested()`; `UndefinedTable` (SQLSTATE 42P01) → la métrica no vive en
  ese módulo y no sale; otro error → `legible: False` con el tipo. `GET
  /api/v1/tenants/{id}/consumo` junta lo de tenancy con `GET
  /api/v1/estado/consumo` de cada servicio (`cargar_destinos`, `cabeceras_de`
  con el tenant mirado, en paralelo, plazo `http_interno_timeout_s`);
  `ConsumoOut.modulo` dice de quién es la fila y un módulo que no contesta sale
  `metrica="*"`, `medido=false`.
- **Borrar sin conexión.** `sinConexion.ts` encola `DELETE` sobre
  `/api/v1/<colección>/<uuid>` como `tipo: "borrar"` (versión de `If-Match` o de
  lo leído; sin versión también) y lo manda por su ruta; 404/410 al volver
  cuenta como hecho; 409/412 → conflicto, y `resolver` lo reencola sobre la
  versión del servidor («Borrarlo igualmente» en `SinConexion.tsx`). El borrado
  de party no comprueba `If-Match` hoy. `iniciarSinConexion` pide con red el
  módulo de `paginas/SinConexion` para que el service worker lo guarde. Lo
  automático no se encola: sólo `POST` a colección, `PATCH`/`PUT`/`DELETE` a un
  registro, y `vistos` va con `encolable: false`.
- **Probar sin red con Playwright**: `context.setOffline(false)` no dispara el
  evento `online` en la página (medido: 0 eventos); hay que despacharlo a mano
  (`window.dispatchEvent(new Event("online"))`) o la cola parece no subir.
- **Pruebas**: `tests/unit/test_restos_claves_login_y_consumo.py`,
  `tests/unit/test_copia_a_sandbox.py`, `frontend/src/lib/sinConexion.test.ts`.

### 4.6.57 `If-Match` en toda escritura sobre un registro (CRM-00.02.01.09)

- **Qué fallaba (medido el 10-11-2026).** `comprobar_if_match` sólo lo llamaba
  la edición genérica de `crmcore/http/listados.py`. El borrado genérico y las
  rutas escritas a mano —el PATCH y el DELETE de cuentas y contactos en party,
  las acciones sobre un registro— no: una versión vieja borraba o pisaba el
  cambio de otro. Lo cazó el borrado del modo sin conexión, que va con su
  versión y esperaba un 409.
- **Cómo se resuelve, para la familia.** `crmcore/http/concurrencia.py`:
  `ContextoMiddleware` guarda la cabecera y los trozos de la ruta en un
  `ContextVar` (sólo en POST, PUT, PATCH y DELETE con `If-Match`), y un oyente
  `before_flush` de la sesión compara la versión de cada objeto con
  `VersionMixin` (salvo los modelos cuya versión es de negocio) que está modificado o borrado
  y cuyo `id` va en la ruta. El borrado reversible es una modificación de
  `deleted_at`, así que entra.
- **Una vez por registro y petición**: tras la primera escritura la versión ya
  ha subido, y una segunda escritura de la misma ruta daría conflicto con su
  propio cambio.
- **Sin cabecera, nada cambia**: exigirla rompería a quien integra sin mandarla.
- **Pruebas**: `tests/unit/test_if_match_en_toda_escritura.py` (por HTTP contra
  party; validada quitando la comprobación: falla).

### 4.6.58 Volver a verificarse sin salir, y lo que queda aunque la petición falle (CRM-00.05.01.18)

- **Qué faltaba (medido el 10-11-2026).** No había ruta para superar un factor
  fuerte con la sesión abierta: el TOTP sólo se comprobaba al entrar
  (`servicio.py`) y al activarlo (`/auth/mfa/activar`), y `FUERZA` da 1 a correo
  y SMS. Crear una clave de API desde la pantalla contestaba
  `stepup.requerido` y no había salida.
- **Servidor.** `POST /api/v1/auth/mfa/reverificar` (identity, `api.py`):
  `409 auth.mfa_no_activa` si no tiene la app; comprueba el bloqueo; un código
  malo pasa por `_anotar_fallo` (el mismo contador del acceso); el bueno anota
  `totp` en la sesión y devuelve `access_token` con `usar_este_token`, que la
  pasarela convierte en cookie (`_refrescar_la_cookie_si_la_sesion_ha_subido`).
  `GET /factores/nivel` dice además `tiene_app`.
- **Front.** `registrarReverificacion` en `lib/api.ts`: si una respuesta trae
  `stepup.requerido`, `llamar` pide al diálogo (`componentes/Reverificacion.tsx`,
  montado en `Marco.tsx`) y repite UNA vez con la misma `Idempotency-Key`.
  `pedirReverificacion()` para lo que no pasa por `llamar` (la descarga de
  `Exportar.tsx`).
- **Lo que queda aunque falle.** `crmcore.db.session.guardar_aunque_falle`
  escribe valores absolutos en una transacción propia, confirmada en el acto.
  Lo usan `_anotar_fallo` (intentos y bloqueo del acceso) y
  `factores.comprobar_desafio` (intentos y agotado del código por correo o SMS,
  y su apunte de auditoría). Medido en la pila local: sin esto, tres
  contraseñas malas dejaban `intentos_fallidos` en 0; con esto, 3.
- **Por qué no se ve en la suite.** El fixture `db` comparte una conexión con
  puntos de guardado anidados: el deshacer de la petición se lleva también lo
  escrito aparte. La prueba del mecanismo
  (`test_lo_escrito_aparte_queda_aunque_la_peticion_se_deshaga`) usa
  conexiones de verdad y borra lo suyo; validada vaciando la escritura: falla.
- **Pruebas**: `tests/unit/test_lo_que_queda_aunque_falle_y_reverificar.py` y
  `frontend/src/pruebas/reverificar_sin_salir.test.ts`.

### 4.6.59 Evaluación de la IA contra el modelo real (CRM-05.02.01.07)

- **Dónde**: `services/intelligence/evaluacion.py` (tablas, comprobaciones,
  ejecutores, juez, panel y programación), `evaluacion_de_serie.py` (el banco:
  50 casos de 10 funciones) y `api_evaluacion.py`. Pantalla
  `frontend/src/paginas/EvaluacionIa.tsx` en `/evaluacion-ia` (Administrar →
  Gobierno y cumplimiento).
- **Tablas** (migración `20261110_0507_evaluacion_de_la_ia`):
  `ia_evaluacion_casos` (el banco del tenant: entrada, criterios, activo,
  origen `serie|propio`, versión), `ia_evaluaciones` (cada pasada: modelos por
  uso, `versiones_prompt`, acierto global y `por_funcion`, coste, latencia,
  umbral, `bajo_umbral`, aviso) e `ia_evaluacion_resultados` (caso a caso:
  criterios con `ok`/`porque`/`juez`, salida recortada, modelo, versión del
  prompt, tokens, coste, latencia, error).
- **El banco es configuración del tenant.** `asegurar_banco` guarda los de
  serie que falten (respeta los apagados) y pone al día los de serie que el
  tenant no ha tocado (versión 1); cambiar entrada o criterios sube la versión
  y ya no se pisa.
- **Mismo camino que la función real.** Cada ejecutor llama al puerto que la
  función tiene registrado (`rag._respondedor`, `rag._traductor`,
  `generacion._generador`, `conversacion._resumidor`/`_clasificador`,
  `extraccion._extractor`, `reuniones._resumidor`, `variantes_copy._redactor`,
  `acciones_asistente._proponedor`, `agentes._planificador`) con el modelo de
  `enrutador.exigir_disponible` para su uso, y trata la salida con las mismas
  funciones: `RE_CITA`, `consulta_natural.normalizar/validar_plan/agregar` (el
  plan se ejecuta sobre las filas del caso con la gramática del listado,
  incluido su filtro por defecto), el filtro de cita literal y confianza de
  `extraccion` con `convertir`, `transcripcion.proponer_extraidos` y la cita
  literal de `reuniones`, el deduplicado y `marcar_afirmaciones` de las
  variantes, el saneado de `clasificar` y `acciones_asistente.limpiar`. Cada
  llamada se anota en el uso y el gasto de IA (`tarea=evaluacion`).
- **Criterios** (`COMPROBACIONES`): `contiene`/`no_contiene` (alternativas
  `a|b`, sin acentos), `igual`, `en`, `numero`, `grupos`, `cita`,
  `citas_validas`, `no_sabe`, `campos` (con `solo_digitos`), `ausentes`,
  `cuantos`, `elementos_contienen`, `compromiso` (dueño, texto y fecha),
  `ningun_compromiso`, `citas_literales`, `cuantas`, `marcadores`,
  `sin_afirmaciones_nuevas`, `longitud_max`, `concluyente`, `argumentos`
  (`asunto|cuerpo` = en cualquiera de los dos), `herramientas_de_la_lista`,
  `usa_herramienta`, `plan_valido` y `juez`. Uno desconocido, uno que revienta
  o un juez sin conectar **no se cumplen**; un caso sin criterios no se puede
  guardar. El juez usa el uso `clasificacion` y su coste suma al del caso.
- **Cómo corre.** `POST /ia/evaluacion/ejecutar` abre la ejecución con los
  casos fijados; la tarea `intelligence.evaluacion_avance` (cada
  `IA_EVALUACION_AVANCE_S`) pasa `ia_evaluacion_casos_por_tanda` casos de la
  ejecución en curso de cada tenant, con su fila bloqueada `SKIP LOCKED`, y la
  cierra cuando no queda ninguno. **No va por la cola de trabajos**: el estado
  ya está caso a caso (si el proceso muere, la vuelta siguiente sigue por el
  primero sin resultado), y en la pila local un worker de una versión anterior
  tomaba el trabajo y lo daba por fallido. `intelligence.evaluacion` (cada
  `IA_EVALUACION_COMPROBAR_S`) lanza la programada a los tenants con banco
  cuando pasan `ia_evaluacion_cada_horas` (0 la apaga). Una sin terminar en
  `ia_evaluacion_caducidad_horas` deja de bloquear y se da por fallida.
- **Aviso**: al cerrar, si una función queda por debajo de
  `ia_evaluacion_umbral` se emite `automatizacion.aviso` (identidad lo convierte
  en notificación) a quien la pidió y a `ia_evaluacion_avisar_a`; el texto
  queda en la ejecución y la pantalla lo enseña.
- **Rutas**: `GET /ia/evaluacion` (panel), `POST /ia/evaluacion/ejecutar`
  (202; 409 `evaluacion.en_curso`), `GET /ia/evaluacion/ejecuciones`,
  `GET /ia/evaluacion/ejecuciones/{id}`, `GET|POST /ia/evaluacion/casos`,
  `PATCH /ia/evaluacion/casos/{clave}`. Leer, `ia:usar`; lanzar y cambiar el
  banco, `ia:administrar`.
- **Ajustes**: `IA_EVALUACION_UMBRAL` (0,9), `IA_EVALUACION_CADA_HORAS` (168),
  `IA_EVALUACION_AVISAR_A`, `IA_EVALUACION_HISTORIAL` (20),
  `IA_EVALUACION_CASOS_POR_TANDA` (4), `IA_EVALUACION_CADUCIDAD_HORAS` (6),
  con clave en caliente; `IA_EVALUACION_COMPROBAR_S` (3600) e
  `IA_EVALUACION_AVANCE_S` (5), del `.env`.
- **Lo que corrigió la primera pasada** (88 % → 98 % en 50 casos con
  `gemini-2.5-flash`): `puerto._responder` pide «No lo sé.» y
  `_dice_que_no_sabe` lo reconoce sin tilde (antes el modelo escribía «No lo
  sabes.»); `extraccion.convertir` lee el punto decimal y sólo toma el punto
  como millar si agrupa de tres en tres (2904.00 salía 290400); `puerto._extraer`
  pide el formato del tipo y descarta palabras genéricas; `_resumir_reunion`
  excluye lo condicional y pone el plazo en el `cuando`; `_redactar_variantes`
  evita las palabras que marcan afirmaciones.
- **Pruebas**: `tests/unit/test_ia_evaluacion.py`, sin modelo real.

### 4.6.60 El bus en vivo en la pila local

- **Cómo se enciende.** Desde el 10-11-2026, `setup.sh arrancar` levanta solo
  un NATS con JetStream en Docker (contenedor `contecrm-nats-local`, la imagen
  del compose, puerto 4222, que se cambia con una variable de entorno del propio setup.sh) y arranca con
  `BUS_BACKEND=nats`. Sin Docker en marcha sigue con `BUS_BACKEND=memoria` y lo
  avisa: cada proceso tiene su bus y ningún evento cruza servicios. Quien fije
  `BUS_BACKEND` a mano manda.
- **Procesos colgados.** Un servicio que recibe la señal de parar suelta el
  puerto y puede quedarse esperando a hilos que no terminan; medido ese día,
  26 procesos de dos arranques anteriores seguían vivos y cogiendo trabajos de
  la cola. `arrancar` los para ahora con `rematar_colgados` (sólo los que
  tienen este repositorio como directorio de trabajo), escalando a `kill -9`.
  Para reiniciar un servicio suelto, `./setup.sh parar` y `arrancar`, no un
  `kill` a mano.
  **`127.0.0.1` y no `localhost`**: macOS resuelve `localhost` a `::1` primero,
  el contenedor escucha en IPv4 y la conexión se rechaza en bucle
  (`bus_nats.error Connection refused`).
- **Medido el 10-11-2026**: 13 conexiones, 1 stream y 156 consumidores. La
  aprobación de un presupuesto hace ida y vuelta sales → orchestrator → sales
  en 2 s.
- **Los consumidores de «todo» no recibían nada** (medido el 10-11-2026):
  `subject_patron(prefijo, "*")` daba `contecrm.*.*`, que en NATS sólo casa
  con tipos de un segmento, y todos llevan punto. Eran 30 consumidores —avisos
  de identity, reglas de automatización, webhooks, perfiles de marketing y la
  caché y las extensiones de cada servicio—. El bus en memoria lo escondía
  porque traducía a `fnmatch`, donde `*` cruza puntos. Ahora «todo» es
  `contecrm.*.>` y `bus/memoria._coincide` aplica las reglas exactas de NATS.
  Visto en vivo: los 30 con todos los eventos entregados.
- **Defecto que salió**: `aprobacion_de_presupuestos.consumir` dejaba una
  `SolicitudAprobacion` pendiente cuando `apr.crear` fallaba a mitad (sin
  aprobadores), porque el `except` confirma la misma transacción para emitir
  `approval.decided`. Ahora `crear` va en `begin_nested()`. Prueba:
  `test_orchestrator_sin_aprobadores_no_aprueba_solo`.


### 4.6.61 Todo controlado por el GRC: controles de serie, segregación, TCSEC y revisión de accesos (CRM-07.03.02.12 a CRM-07.03.02.15)

- **Dónde.** `services/tenancy/grc_serie.py` (instalar, sincronizar, medir y
  evaluar) y `api_grc_serie.py`; `services/identity/recertificacion.py` y
  `api_recertificacion.py`. Pantallas: `ControlesGrc.tsx` (`/controles-grc`),
  `RevisionAccesos.tsx` (`/revision-accesos`) y `MiRevisionDeAccesos.tsx`
  dentro de `Aprobaciones.tsx`.
- **Modelo.** `grc_controles` gana `origen` (`familia`, `segregacion`, `tcsec`,
  `recertificacion` o vacío), `referencia` (la familia, la regla o el
  requisito) y `ajustado`; tablas nuevas `grc_hallazgos` y `grc_evidencias`
  (migración tenancy `1a5333924500`). En identity, `recert_campanas` y
  `recert_revisiones` (migración `5154dbedd6f1`).
- **Rutas de tenancy.** `GET|POST /grc/de-serie`,
  `POST /grc/controles/evaluar-automaticos[?origen=]`,
  `POST /grc/controles/{codigo}/evaluar-automatico`,
  `POST /grc/controles/{codigo}/activo`, `GET /grc/controles/{codigo}`,
  `POST /grc/segregacion/sincronizar`, `GET /grc/hallazgos`,
  `GET /grc/evidencias`. `GET /grc/controles` trae `origen`, `referencia`,
  `ajustado` y `ultima_evaluacion`; la cobertura, `verificadas` y
  `pct_verificado`; el panel, `cobertura_verificada_pct` y
  `hallazgos_abiertos`.
- **Rutas de identity** (prefijo `recertificacion`, dado de alta en
  `crmcore.rutas_de_api`): `GET|POST /recertificacion/campanas`,
  `GET /recertificacion/campanas/{id}`, `POST …/{id}/cerrar`,
  `POST /recertificacion/vencidas`, `GET /recertificacion/mias`,
  `POST /recertificacion/revisiones/{id}/decision` (sólo el responsable) y
  `GET /recertificacion/resumen` (lo que lee el GRC).
- **Ningún servicio importa a otro.** Tenancy pide a identity reglas,
  conflictos, excepciones, nombres y el resumen de campañas con
  `crmcore.http.interno.invocar`, firmado con la identidad de quien evalúa; y
  a cada servicio su `/cumplimiento/informe` para la cadena de auditoría. Lo
  que no contesta se anota en la evidencia y el control **no se evalúa**.
- **Fuentes de evidencia nuevas**: `trazabilidad` (el `visto` de cada
  capacidad del catálogo —`crmcore.catalogo` lo expone ahora— y la cadena de
  los servicios desplegados que la sirven; la evidencia lleva
  `capacidades_verificadas`, que es lo que cuenta la cobertura verificada
  aunque el control salga «parcial»), `segregacion`, `tcsec` y
  `recertificacion`. `evaluar_automaticos` evalúa cada control en su
  SAVEPOINT y con una caché común: el informe de cada servicio se pide una vez.
- **La última evaluación** se ordena por fecha, alta e id: dos evaluaciones del
  mismo día salían en cualquier orden.
- **Tarea periódica** en identity: `identity.recertificacion_vencidas`, cada
  `TAREA_RECERTIFICACION_INTERVALO_S` (3.600 s), por tenant con campañas
  abiertas.
- **Ajustes** (Settings y editables en caliente): `grc_serie_frecuencia`
  (trimestral), `grc_sod_riesgo_por_nivel`, `recertificacion_plazo_dias` (14),
  `recertificacion_frecuencia` (trimestral) y `recertificacion_al_cerrar`
  (`marcar`; `retirar` quita lo no confirmado, sensible).
- **Pruebas**: `tests/unit/test_todo_controlado_por_el_grc.py`, siete, una por
  comportamiento.

### El organigrama, desde Administrar (CRM-00.03.05.07)

Medido el 10-11-2026: nada escribía `membresias.superior_id` —SCIM ignoraba el
`manager`, el SSO no lo trae y no había pantalla—, y `user.org.changed` salía
con `dedup_key=org:{tenant}:{usuario}`, fija por persona: los consumidores
(orchestrator, sales, party) deduplican por clave y aplicaban sólo el primer
evento de cada persona. Ahora:

- **Rutas** (identity, prefijo `organigrama` en `crmcore.rutas_de_api`):
  `GET /api/v1/organigrama` (`user:read`; personas con `superior_id`,
  `origen`, `fijado_at`, `fijado_por`, `truncado`, `externo_manda`),
  `PUT /api/v1/organigrama/{usuario_id}/superior` y
  `POST /api/v1/organigrama/{usuario_id}/equipo` (`user:write`). Errores:
  `organigrama.ciclo` (409, con el `camino`), `organigrama.a_si_mismo`,
  `organigrama.superior_inactivo` (422), `organigrama.superior_desconocido`,
  `organigrama.persona_desconocida` (404). Mover el equipo comprueba todos
  antes de tocar ninguno. Cada cambio queda en la auditoría
  (`organigrama.superior`).
- **Modelo**: `membresias.superior_origen` (`''`, `manual`, `scim`),
  `superior_fijado_at`, `superior_fijado_por`; migración
  `alembic/versions/identity/20261110_1200_origen_del_superior.py`.
- **SCIM**: se lee `urn:ietf:params:scim:schemas:extension:enterprise:2.0:User`
  › `manager` en el alta, el `PUT` y el `PATCH` (con `path` y sin él), se
  devuelve en la representación y se declara en `ResourceTypes`. Un `manager`
  desconocido, de baja o que cerraría un círculo se registra y se ignora, sin
  romper el aprovisionamiento.
- **Replicación**: `organigrama.publicar` emite `user.org.changed` sin
  `dedup_key` (la derivada lleva el momento: cada cambio es un hecho) y, al
  fijar un superior, publica también al superior, para que la cadena de mando
  replicada (`orchestrator.personas_org`) no se corte en él. La revisión de
  accesos lee `superior_id` en identity al lanzar la campaña.
- **Ajustes** (Settings y editables en caliente): `organigrama_externo_manda`
  (sí, sensible) y `organigrama_tope_personas` (5.000).
- **Pantalla**: `frontend/src/paginas/Organigrama.tsx`, ruta `/organigrama`.
- **Pruebas**: `tests/unit/test_el_organigrama_se_fija_desde_la_pantalla.py`,
  tres: fijar y republicar con claves distintas, el círculo (también al mover
  el equipo) y el `manager` de SCIM frente a lo ajustado a mano.

### Colecciones sin puerta: de 29 a 0 (10-11-2026)

El tope de colecciones sin puerta de
`tests/unit/test_una_coleccion_sin_puerta_no_la_abre_nadie.py` baja a **0**. Medidas 29 (no 32) al empezar.

- **Componentes nuevos** (`frontend/src/componentes/`), montados en
  `paginas/Ficha.tsx` por tipo: `RepartoYOrigenDelLead` (`lead`;
  `GET /lead-routing/leads/{id}/explicacion` y `/origen/leads/{id}/recorrido`),
  `CorreoDelContacto` (`contacto`; `GET /canales-marketing/mejor-hora?objeto_id=`
  y `GET`/`PUT /preferencias?email=`, el `PUT` con `origen: "ficha"`),
  `QuienMandaSobre` (`regla_convivencia`; `/convivencia/quien-manda?objeto=`),
  `HerramientasDeExposicion` (`exposicion_mcp`; `/agentes-ia/{clave}/herramientas`),
  `SePuedePublicar` (`activo_marketing`; `/activos-marketing/aprobaciones/estado`
  con la `version` del activo) y `CarpetaDelRegistro`, dentro del panel de
  documentos (`/documentos/{tipo}/{id}/carpeta?crear=false`,
  `/documentos/carpetas?padre=`, `/carpetas/{id}/documentos`,
  `/carpetas/{id}/permisos`, `/documentos/buscar-en-rama`).
- **Páginas**: `Aprobaciones.tsx` (`GET /documentos/organizacion`),
  `Estado.tsx` (`/estado/ui-referencia`), `PeriodoDePrevision.tsx`
  (`/forecast/waterfall?desde=&hasta=`), `Coste.tsx`
  (`/coste/fecha-prometible`), `Prospeccion.tsx` (`/agenda/huecos`),
  `Duplicados.tsx` (`/data-quality/accounts/duplicates?nombre=&nif=`),
  `componentes/VistaPreviaCorreo.tsx` (`/correo/comprobar-envio`) y
  `Portal.tsx` (`/proveedores/mi/homologaciones`).
- **`recursos.ts`**: `resumen` con `/eventos/estado` en «Catálogo de eventos»
  y con `/ia/eleccion-sin-salida` en «Consumo y coste» (si la política admite
  varias regiones o ninguna, contesta 422 y `Medidas` no la pinta);
  `objeto: "exposicion_mcp"` en «Exposiciones MCP»; `objeto: "activo_marketing"`
  en «Activos de marketing», y «Aprobaciones de activos» pasa de `objeto` a
  `abre` (la ficha pedía `/aprobacion/{id}`, que no existe: 405).
  Regenerado `lib/visibilidad.ts`.
- **Gateway**: `GET /api/v1/eventos/estado` devolvía las colas de todos los
  tenants, con su identificador, a cualquier usuario autenticado. Ahora
  devuelve `oyentes`, `en_cola` y `que_significa` del tenant de quien pregunta.
- **Declaradas sin pantalla** en la lista de excepciones del mismo gate, con
  su motivo:
  `/comentarios/{objeto_tipo}/mis-menciones`, `/contacts/contexto-de-correo`,
  `/cookies/puede-rastrear`, `/cuadros-mando/embebido`,
  `/despliegue/reintento`, `/listas-precio/calcular` y `/monedas/convertir`.
- `lib/formato.ts`: `minima`, `exposicion` y `variacion` en el diccionario de
  palabras con tilde.

### 4.6.62 Lo que se baja al abrir y lo que pesa cada pantalla (10-11-2026)

- **Medido**: apertura 138 kB comprimidos (tope 127), front entero 470 (tope
  330), `Ficha` 14,0 y `Modulo` 15,2 (tope 13 por pantalla).
- **Diferido sin tocar números**: la cola sin conexión (`main.tsx` la importa
  al vuelo), su franja y la ficha de llamada entrante; 22 bloques de textos
  que sólo usan pantallas diferidas, de `es.ts` a `es.pantallas.ts` (el
  cierre estático desde `main.tsx` decide cuáles: 48 ficheros); y en la ficha,
  diecisiete bloques de un solo tipo de registro, con `lib/diferido.tsx` —un
  componente que no pinta nada hasta que llega su código y después es el
  mismo, sin `Suspense`—.
- **Topes subidos con su motivo** en `tests/unit/test_front_oficial.py`:
  apertura 131 (queda 130: diálogo de reverificación y menú nuevo), total 490
  (la cola larga de pantallas está cerrada) y por pantalla 15 (`Modulo`, el
  motor de los listados, 14,1).

### contecintelligence en vivo: el CRM como fuente, preguntas e instantáneas (10-11-2026)

Medido con la pila local (`SIN_VECINOS=1 ./setup.sh arrancar`) y
contecintelligence en Docker (`localhost:8100`). El CRM no estaba registrado
como fuente; el alta fallaba y, detrás, todo informe fallaba también.

- **El alta, desde la pantalla**: Analítica → Preguntas publicadas, botón
  «Registrar el CRM como fuente consultable» → `POST
  /api/v1/explotacion/registrar-fuente` (202 + trabajo
  `analitica.registrar_fuente`, worker de analytics). Tarda 80–110 s: su
  `POST /api/sources` no contesta hasta leer y perfilar cada entidad.
- **Por qué fallaba (1): la lista anti-SSRF de contecintelligence.** En local
  el CRM se le daba como `host.docker.internal`, y su OUTBOUND_ALLOWED_HOSTS
  —configuración suya— sólo nombra el alias de Docker (`gateway`). Su log lo
  decía («host no permitido»); su respuesta, sólo «health_check fallo».
  `setup.sh` (función asegurar_relevo_para_ci; las variables de ese bloque son del
  script y no `Settings`) levanta ahora en la pila local un
  relevo `contecrm-relevo-ci` (nginx) en la red CONTECRM_NETWORK
  (`contecrm-dev_default` por defecto) con el alias del host de
  `CI_URL_DEL_CRM`, que reenvía al gateway de la máquina; con el relevo,
  `CI_URL_DEL_CRM` queda como en el `.env`. Imagen y plazo:
  RELEVO_CI_IMAGEN, RELEVO_CI_PLAZO_S. No se crea si el host es de
  máquina (`localhost`, `host.docker.internal`, una IP), si la red no existe
  o si ya hay un contenedor con ese alias (la pila Docker). `parar` lo quita.
  CI_URL_DEL_CRM_LOCAL sigue mandando sobre todo.
- **Por qué fallaba (2): el plazo.** `_publicar` usaba `ci_timeout_s` (10 s)
  para el alta; ahora `ci_timeout_registro_s` (300 s). El mensaje de rechazo
  nombra también OUTBOUND_ALLOWED_HOSTS.
- **Una alta a la vez** (`encolar_registro`): si hay un trabajo vivo
  (`ESTADOS_VIVOS`) del mismo tipo y tenant, se devuelve ése. Dos en paralelo
  se borraban la fuente una a otra.
- **Todo informe fallaba al ejecutarse**: `ejecutar_plan` mandaba
  `"pivote": null` y su `PlanPortable` declara `pivote: str = ""` → 422. Ahora
  no se manda ninguna clave con `None`.
- **La instantánea reventaba** (`tomar_instantanea`): leía las filas como
  diccionarios y el ejecutor las devuelve como listas (`FilasDelPlan.rows`).
  Pasa por `_en_diccionarios`, como la exportación. La prueba usaba un doble
  que devolvía diccionarios.
- **Pantalla** (`Explotacion.tsx`, `RespuestaAnalitica.tsx`): la respuesta
  `type: "aclaracion"` pinta sus `preguntas[].opciones` como botones y
  vuelve a preguntar con «pregunta (opción)»; «Guardar la pregunta» hace
  `POST /api/v1/explotacion/preguntas` (nace sin publicar).
- **Pruebas**: `tests/unit/test_explotacion_fuente.py` (plazo del alta, plan
  sin vacíos, una alta a la vez), `tests/unit/test_informes.py`
  (instantánea con filas en lista),
  `frontend/src/pruebas/la_respuesta_se_aclara_y_se_guarda.test.tsx`.
- **Medido en vivo**: «Importe total de oportunidades por etapa» → barras con
  las cinco sumas iguales a las del CRM (146 oportunidades); la instantánea
  programada a las 07:00 UTC corrió a las 07:00:03 (el error que dejó, el del
  `pivote`, es el que se arregló); «Tomar una ahora» guarda 13 filas.
- **Pendiente, de contecintelligence** (se avisa, no se toca): el filtro sobre
  una lista (`roles = '["cliente"]'`, 2 en vez de 6); «no se puede abrir la
  copia local de esta fuente» en los dos componentes del «Cuadro de
  dirección», también con la fuente rehecha.
- **Pendiente, de aquí**: `./setup.sh arrancar` no barre los
  workers huérfanos (sí `parar`): había 42 de cuatro arranques, y un alta la
  cogía uno con la configuración vieja.

### Barrido de constantes y la hora de los informes programados (10-11-2026)

**Método** (repetible): `.venv/bin/python scripts/barrido_constantes.py .`,
y `--detalle <categoría>` para la lista. Recorre por AST `services/**` y
`packages/crmcore/crmcore/**` sin pruebas, `ajustes.py`, `config_parts`,
`runtime/keys.py` ni `config.py`. Da **candidatos, no veredictos**: cada uno se
mira a mano. No es un gate.

**Medido** (589 ficheros):

| Categoría | Qué cuenta | Antes | Después |
|---|---|---|---|
| `plazo` | `timedelta(days/weeks/hours=N)` literal | 6 | 5 |
| `parametro` | defecto numérico con nombre de negocio | 165 | 162 |
| `constante_num` | `MAYUSCULAS = número` de módulo | 25 | 23 |
| `comparacion` | número no trivial en una comparación | 278 | 278 |
| `lista_str` | `MAYUSCULAS = (textos…)` de módulo | 400 | 401 |

Revisados a mano: los 6 plazos, las 25 constantes y los 165 parámetros. Las
comparaciones y las listas **no** se han recorrido una a una.

- **Lo que no es hardcodeado**, y se queda: los `limite=`/`tope=` de un listado
  (paginación; la ruta los recibe), las ventanas `dias=` de un panel que la
  petición pasa, versiones de formato y de contrato (`VERSION_SOBRE`,
  `FORMATO_MANIFIESTO`…), constantes físicas o de estándar (`RADIO_TIERRA_M`,
  `CONTRASTE_MINIMO` 4,5 de WCAG, `PARAMETROS_POSTGRES`), y márgenes técnicos
  (`MARGEN_RENOVACION` de una suscripción, `RETENCION_HORAS` de idempotencia).
- **Convertido en ajuste** (Settings + `ClaveAjuste`, editable en Admin):

| Clave | Defecto | Dónde estaba | Dónde se lee |
|---|---|---|---|
| `informes_tope_fallos_seguidos` | 3 | `correr_programadas(tope_fallos=3)` | `informes.correr_programadas`, una vez antes del bucle |
| `sla_riesgo_umbral_pct` | 80 | `Query(80)` de `GET /sla/en-riesgo` | la ruta, si no viene en la petición |
| `cuenta_dias_fiable_financiero` | 2 | constante de `cuenta_360` | `cuenta_360.puede_comprometer` |
| `cuenta_plan_dias_caducidad` | 90 | defecto de `plan_caducado` | `GET /planes-cuenta/{id}/caducado` |
| `conversacion_umbral_confianza` | 0,6 | defecto de `clasificar` y del cuerpo | `conversacion.umbrales_de_clasificar`, también la evaluación de la IA |
| `conversacion_umbral_escalado` | 0,8 | ídem | ídem |
| `tenant_baja_dias_recuperacion` | 30 | `cambiar_estado` (`timedelta(days=30)`) | `tenancy.servicio.cambiar_estado`; núcleo, ámbito mínimo `tier`, sensible |

- **Un ajuste que ya existía y un camino que no lo leía** (la familia del
  «constante con otro nombre»): `audiencia_minimo` lo leía la sincronización y
  `preparar_audiencia` tenía su `MINIMO_AUDIENCIA = 100`; el cuerpo de `POST
  /proveedores/riesgo` traía `umbral_concentracion = 40.0` y no seguía a
  `riesgo_concentracion_pct`, que sí leía compras. Los dos leen ya el ajuste.
- **Escrito y sin enchufar**: `APROBADORES_DESBLOQUEO = 2` (identity) sólo
  sale en la respuesta de `cambio_de_dispositivo`; ningún flujo exige esos
  aprobadores. Convertirlo en ajuste no cambiaría nada: se deja anotado.

**La hora de una programación de informe.** `ProgramacionInforme.hora` se
calculaba sobre UTC y la pantalla la pedía como local: «a las 7» corría a las
08:00 (invierno) o 09:00 (verano) en la Península. Ahora:

- `informes.zona_de_programacion(db)` resuelve la zona **del tenant**
  (`zona_horaria`, con usuario y unidad quitados del contexto: el barrido no
  tiene usuario y la misma programación no puede moverse según quién la creó).
- `_siguiente_ejecucion(prog, desde, zona)` cuenta días de calendario en esa
  zona y fija la hora de reloj en cada uno; `proxima_at` se guarda en UTC. El
  cambio de hora no la mueve (23 h y 25 h entre ejecuciones esos domingos).
- `programar` y `correr_programadas` la leen una vez (fuera del bucle). Sin
  migración: la columna `hora` no cambia, cambia cómo se lee. Una programación
  ya existente corre una vez más a su `proxima_at` antigua y desde ahí se
  recalcula bien.
- La API devuelve `zona` en `POST /informes/{id}/programar` y en `GET
  /informes/programaciones` (arriba y en cada línea); la pantalla
  (`AnalisisCrm.tsx`) pone «Hora (Europe/Madrid)» y «a las 7 h (Europe/Madrid)».
- Prueba: `tests/unit/test_informes.py::test_a_las_7_es_a_las_7_del_tenant_tambien_con_el_cambio_de_hora`
  (invierno, verano, las dos noches del cambio, semanal y mensual cruzándolo).
- `SuscripcionCuadro` (cuadros de mando) usa ya el mismo cálculo: ver
  «Suscripciones a paneles, «hoy» del cliente y segundo barrido» más abajo.

**Documentos desde la ficha del registro (CRM-06.01.01.06).** Medido el
10-11-2026: la generación funcionaba con datos escritos a mano, sacaba texto y
«guardarlo» era cosa de contecmind. Ahora:

- **Rutas** (integration, `services/integration/api_buzon.py`, permiso
  `adjunto:subir`): `GET /plantillas-documento/para/{objeto}`, `POST
  /plantillas-documento/desde-registro/preparar` (cada marcador con `valor`,
  `origen` —`registro`, `a_mano`, `falta`— y `campo`; `faltan`; `avisos`) y
  `POST /plantillas-documento/desde-registro/generar` (201: `adjunto` con su
  ruta de descarga y `corpus: {archivado, motivo}`). `PUT
  /plantillas-documento/{clave}/mapeo` (`integracion:write`) guarda una versión
  nueva con el mismo cuerpo.
- **Datos** (`services/integration/documento_registro.py`): se leen con
  `crmcore.http.interno.invocar` y la identidad de quien genera, de las rutas del
  ajuste `documento_fuentes` (objeto → `ruta`, `lineas`, `por_cuenta`,
  `nombre`). Todo `<tipo>_id` del registro cuyo tipo esté declarado se lee como
  relacionado; sin contacto, el primero de la cuenta. Un relacionado que no se
  puede leer —o que viene tapado— es un **aviso**; el registro, un error. El
  presupuesto se lee por `/presupuestos/{id}/documento`, que no trae coste ni
  margen (y ahora sí `contacto_id` y `oportunidad_id`).
- **Resolución de un marcador**: lo escrito a mano; el `mapeo` de la plantilla
  (`"campo"` o `{"campo", "formato"}`, formatos `auto`, `texto`, `importe`,
  `numero`, `fecha`); su propio nombre en los datos; y su nombre como campo del
  registro. Un registro entero toma su nombre. `auto` formatea con
  `crmcore.i18n.Localizacion` en el idioma de la plantilla: fecha ISO como
  fecha, decimal con `moneda` al lado como importe.
- **PDF**: `crmcore/documental/pdf.py`, el chasis de contecweb
  (`app/services/reports/pdf.py`) traído con la marca y el papel como
  parámetros. `reportlab==4.4.10` en `requirements.txt`. Marca: la de la
  plantilla, la del registro o el `nombre_producto` de la marca blanca activa
  (`GET /api/v1/marca`, con la identidad de quien genera); colores de la marca
  activa o del ajuste `documento_pdf_colores`. Ajustes: `documento_pdf_papel`,
  `documento_pdf_margen_cm`, `documento_pdf_columnas_lineas`,
  `documento_pdf_totales`, `documento_nombre_fichero`, `documento_espera_s`.
- **Guardado**: multipart a `POST /api/v1/adjuntos/{objeto}` del servicio dueño.
  Si falla, se lanza `documento.adjunto_no_guardado` y la constancia se deshace.
  Después, `POST /api/v1/documentos/{objeto}/{id}/archivar-adjunto/{adjunto}`
  (nueva en `crmcore/http/documental_router.py`, permiso `documento:enlazar`):
  sube el adjunto a contecmind (`cliente.subir_documento`, multipart a
  `/api/v1/documents`), lo coloca en la carpeta del registro y lo enlaza. Su
  fallo nunca rompe la generación; `documento_archivar_en_corpus` lo apaga.
- **Modelo y migración** `integration/20261110_0825_plantillas_con_mapeo_marca_y_pdf_`:
  `plantillas_documento.marca`, `objetos`, `mapeo`, `con_lineas`;
  `documentos_generados.adjunto_id`, `formato`.
- **Pantalla**: `frontend/src/componentes/GenerarDocumento.tsx`, en
  `Oportunidad`, `Presupuesto`, `Cuenta` y la ficha genérica (`Ficha.tsx`,
  donde recarga «Adjuntos» al terminar). Se esconde si el objeto no está en
  `documento_fuentes` o si quien mira recibe 403.
- **Pruebas**: `tests/unit/test_documento_desde_registro.py` (resolución y
  faltan; PDF guardado como adjunto con el corpus caído; sin adjunto no hay
  constancia).

**Preguntas guardadas: publicar y convertir en informe (CRM-05.01.04.06).**
`PATCH /explotacion/preguntas/{id}` (`{publicada, roles?}`; sólo su autor o
`analitica:administrar`, `fuente.compartir_pregunta`) y `GET
/explotacion/campos-publicados` (objetos y campos de
`FuenteRegistrada.campos_por_objeto`, agregados y periodos). `POST
/explotacion/preguntas/{id}/publicar` comprueba ahora los campos con
`_comprobar_campos`, igual que `POST /informes`. Pantalla: `Explotacion.tsx`,
botones en cada tarjeta. Prueba:
`tests/unit/test_explotacion_fuente.py::test_solo_su_autor_publica_una_pregunta_para_el_equipo`.

### Suscripciones a paneles, «hoy» del cliente y segundo barrido (10-11-2026)

**Suscripciones a paneles (CRM-05.01.02.05).** Medido: `SuscripcionCuadro`
guardaba `hora` y `proxima_at = ahora + 1 día` y ningún barrido la leía.

- **Modelo y migración** `analytics/20261110_1800_suscripciones_cuadro_con_canal`
  (revisión `8d2a1b3c4e56`): `canal` (`app` por defecto, de
  `crmcore.datos.seguimiento.CANALES`), `dia_semana`, `dia_mes`, `ultima_at`,
  `ultimo_error`.
- **Cálculo**: `cuadros.suscribirse` y `cuadros.correr_suscripciones` usan
  `informes._siguiente_ejecucion` con `informes.zona_de_programacion(db)` (zona
  del tenant, leída una vez fuera del bucle). `_siguiente_ejecucion` acepta
  cualquier objeto con `periodicidad`, `hora`, `dia_semana`, `dia_mes`.
- **Barrido**: tarea `analytics.suscripciones_cuadro` en el relevo de tareas de
  analytics (`main._tareas`), intervalo `tarea_informes_intervalo_s`, tenants de
  la propia tabla. A mano: `POST /api/v1/cuadros-mando/suscripciones/correr`
  (`informe:write`).
- **Entrega**: emite `dashboard.delivered` (nuevo en `events/dominio.py` y en el
  catálogo) con `usuario_id`, `titulo`, `cuerpo` y `canales: [canal]`.
  `identity.notificaciones.AVISOS["dashboard.delivered"]` lo convierte en
  `Notificacion` sólo para ese usuario (`solo_destinatarios`) y, con la regla
  nueva `solo_canales_del_evento`, sin preferencia propia sale **sólo** por el
  canal de la suscripción (`canales_por_defecto = canales del evento`); el
  repartidor de identity lo entrega. No lleva cifras: el barrido no tiene los
  roles del suscriptor.
- Cuadro borrado o desactivado → `activa = False` y `ultimo_error`.
- **API**: `POST /cuadros-mando/suscripciones` (cuerpo con `canal`,
  `dia_semana`, `dia_mes`; devuelve la suscripción con `zona`), `GET
  /cuadros-mando/suscripciones/mia?cuadro_id=`, `POST
  /cuadros-mando/suscripciones/{cuadro_id}/baja`.
- **Pantalla**: `Cuadros.tsx` (`RecibirCuadro`; canales de `GET
  /notificaciones/canales`) y `?cuadro=<id>` abre ese panel; la bandeja
  (`Notificaciones.tsx`, `PANTALLA_DE.cuadro_mando = "/cuadros?cuadro={id}"`).
- **Pruebas**: `tests/unit/test_la_suscripcion_a_un_cuadro_llega.py` (Madrid, la
  noche del 24 al 25-10-2026: sale a las 05:00 UTC y la siguiente a las 06:00
  UTC; el evento de la tabla de salida acaba en un aviso sólo por correo; cuadro
  borrado apaga la suscripción) y `frontend/src/pruebas/cuadros.test.tsx`.

**«Hoy» del cliente: el guardián en verde.**
`test_hoy_es_el_del_cliente_en_todas_partes.py` acusaba 6 sitios con sesión a
mano y 19 sin sesión (tope 15). Ahora: 0 y 2.

- Con sesión, a `fechas.hoy(db)`: `lecciones.expediente`,
  `documento_registro.reunir` y `_nombre_fichero`, `datos_crm.embudo_crm` y
  `actividad_crm`.
- Funciones puras que caían al reloj si no les pasaban el día: `hoy`/`desde`
  **obligatorio** en `plan_conjunto.estado_del_plan` y `sin_revisar`,
  `costes.preparar_peticion`, `recoger_respuestas` y
  `fecha_que_se_puede_prometer`, `proveedores_comercial.estado_del_contrato`,
  `particionado.particiones_a_crear`, `se_puede_archivar` y `archivar`,
  `sandboxes.caducados`, `activos.se_puede_usar`, `cohortes.cohortes` y
  `embudo`, `predictivo.rasgos_oportunidad` y `_extra`. Las rutas que sólo
  traían cuerpo (`/sandboxes/caducados`, `/activos-marketing/se-puede-usar`,
  `/analisis/cohortes`, `/analisis/embudo`, `/momento/comparar`) reciben `db` y
  lo ponen. Se quitan los `_hoy()` locales que quedaron sin uso.
- `baja._leeme(…, generada=)`: el día del cliente al exportar y el de la
  exportación (no el de la purga) al rehacerla. `puerto._hoy_iso` abre una
  sesión del tenant del contexto.
- **Quedan dos, con motivo** (escrito en el propio guardián, que lleva el tope a
  2): `obs/slo.py::periodo` (el
  mes del SLO es de la plataforma, en UTC) y `gateway/sandbox_api.py::_valor`
  (fecha de un dato sintético; el gateway no tiene base de datos).
  La lista de funciones que reciben el día y aun así miran el reloj baja de 3 a
  1 (`slo.periodo`). Las pruebas que preguntaban la fecha a la
  máquina (`test_ia_predictivo_entrenado`, `test_todo_controlado_por_el_grc`)
  usan `fechas.hoy()`.

**Segundo barrido: comparaciones y listas.** `scripts/barrido_constantes.py`
cuenta ahora aparte `semilla_vocabulario`: una lista que se pasa a
`vocabulario.registrar` son los valores de fábrica de un vocabulario que edita
la empresa, no un límite.

| Categoría | Al empezar | Después |
|---|---|---|
| `comparacion` | 288 | 279 |
| `lista_str` | 401 | 396 (+3 `semilla_vocabulario`) |
| `parametro` | 162 | 161 |

Convertido (Settings + `ClaveAjuste`, editable en Configuración salvo donde se
dice):

| Clave | Defecto | Era | Dónde se lee |
|---|---|---|---|
| `contrasena_minimo` (ya existía) | 12 | un 12 en `servicio.hashear_contrasena` | `hashear_contrasena`; el alta y el cambio no seguían al ajuste que sí leía el restablecer |
| `mfa_minutos_salto_imposible` | 120 | `evaluar_riesgo` | `identity.api` al entrar, con la sesión; sin ella, el `.env` |
| `mfa_dias_ausencia` | 30 | defecto de `evaluar_riesgo` | ídem |
| `territorio_excepcion_aviso_dias` | 30 | `territorios.excepciones_de` | ídem, una vez |
| `envio_umbral_rebote_duro_pct` | 2,0 | `campanas.salud_de_envio` | ídem; también sale en la respuesta |
| `envio_umbral_queja_pct` | 0,1 | ídem | ídem |
| `momento_minimo_envios_concluyente` | 500 | `momento.comparar_con_hora_fija` | la ruta `/momento/comparar` |
| `salud_cobertura_minima_pct` | 50 | `salud.medir` | ídem, una vez |
| `salud_delta_aviso_puntos` | 5 | ídem | ídem |
| `asistencia_dias_sin_contacto` | 14 | `asistencia.proximos_pasos` | ídem |
| `asistencia_dias_sin_contacto_urgente` | 30 | ídem | ídem |
| `sms_palabras_baja` | baja, stop, cancelar, unsubscribe, no | `canales.PALABRAS_BAJA` | `canales.procesar_entrante` |
| `dominios_correo_genericos` (sólo `.env`) | gmail.com… (16) | `normalizacion.DOMINIOS_GENERICOS` | `normalizacion.dominio_de`, función pura sin sesión |

Y un vocabulario nuevo, `factores_leccion` (los 14 de `lecciones.FACTORES`
como semilla): `firmar` valida contra `lecciones.factores_validos(db)`, la ficha
devuelve esos en `factores_posibles`, `_leer_borrador` recibe los válidos, el
índice de consejos ya no filtra por los de fábrica y la plantilla
`leccion_oportunidad` de intelligence recibe `{{factores}}` en vez de la lista
escrita. Pestaña «Factores de una lección» en Lecciones (`recursos.ts`).
Pruebas: `test_lecciones_aprendidas.py` (firma con un factor añadido por la
empresa), `test_restablecer_contrasena.py::test_el_alta_y_el_cambio_exigen_el_minimo_del_ajuste`.

**Lo que se queda, con su motivo** (recorridas las 279 y las 396):

- **Comparaciones**: 152 son códigos HTTP/SMTP (protocolo); 46 son formato o
  calendario (longitud de un NIF o un teléfono, partes de una ruta, latitud,
  diciembre, fin de semana); 5 son épsilon numérico. De las 76 restantes:
  definiciones de estándar (NPS 9/6, luminancia WCAG 0,03928, trimestres,
  correlación 0,4/0,7, severidad por sigmas —el umbral de disparo ya es por
  serie—, «factor resistente a phishing» = fuerza 3); mínimos de muestra de un
  cálculo estadístico (10, 20, 200 ejemplos…: bajar uno no es una decisión de
  negocio sino dar por buena una conclusión que no lo es); topes de validación
  de entrada (12 pasos de cadencia, 200 cambios, 25 actividades, motivo de 10
  letras, `timeout_ms` 3000, canario 1–25 %); y umbrales de operación de la
  plataforma (`obs/presion` 0,6/0,9, `obs/escalado` 80 %, particionado), que
  son del despliegue y no de un cliente.
- **Listas**: 71 son estados de una máquina del sistema con código detrás de
  cada uno —los de negocio que una empresa cambia ya tienen su máquina
  configurable (`crmcore.datos.estados`, `con_significado`) y no se duplican—;
  55 son protocolo (métodos HTTP, algoritmos, esquemas TLS, operadores); 63 son
  estructura (campos, columnas, lo que no se copia); y el resto, 207, son
  catálogos cerrados que el código interpreta valor a valor (tipos de
  componente, de nodo, de paso, acciones): un valor nuevo sin su rama sería un
  hueco.
- **Candidatas a vocabulario y umbrales que quedaban**: hechos en el bloque
  siguiente, «Vocabularios de la casa, cuatro umbrales y la ventana de las
  cadencias» (más abajo), con `postventa.MOTIVOS_SUSPENSION` cerrada y su
  motivo.
- **La ventana horaria de las cadencias**, que se evaluaba en UTC: arreglada
  en ese mismo bloque.

### Poblar la aplicación entera, y lo que se queda vacío a propósito (10-11-2026)

Una demostración se juzga por la pantalla que sale vacía. Recorriendo las 240
rutas de listado que declara `frontend/src/lib/recursos.ts` contra el tenant de
la plataforma salían **15 pestañas vacías** y, además, **160 de las 162
oportunidades ganadas sin dueño**, con lo que las comisiones y la compensación
externa salían sin reparto. Después de sembrar quedan **10**, y las diez por
un motivo que se puede decir.

**Cómo se puebla, en orden.** Los tres guiones de siempre, y dos pasos nuevos:

```bash
# 1. La empresa con volumen e historia (ORM, por servicio)
python scripts/sembrar_empresa.py --slug acme --email direccion@acme.example --contrasena "…"
# 2. La configuración y los catálogos (por la API)
python scripts/sembrar_configuracion.py --tenant acme --email direccion@acme.example \
    --contrasena "…" --aprobador ventas.oem@acme.example
# 3. Dueño a las oportunidades que no lo tienen (también a las cerradas)
python scripts/sembrar_empresa.py --parte duenos --slug acme --tenant <uuid>
# 4. Las pestañas que quedaban vacías y las comisiones con reparto
python scripts/sembrar_configuracion.py --tenant acme --email … --contrasena "…" \
    --aprobador ventas.oem@acme.example --parte pestanas_que_quedaban
```

- **Dueños (`--parte duenos`).** Por la API no se podía: una oportunidad
  cerrada está bloqueada, y `sembrar_duenos` se las saltaba —con razón— y
  además sólo miraba la primera página. Se rellena por el ORM y **sólo lo
  vacío**: el dueño es el de la cuenta si quien la lleva vende (rol
  `comercial` o `responsable_ventas`); si no, un comercial del organigrama
  elegido con la semilla **por cuenta**, así que todas las ventas de un
  cliente caen en la misma persona y la misma empresa da el mismo reparto en
  cada pasada. No toca `updated_at`: el dueño no es un cambio de hoy. Medido
  en la plataforma: 554 oportunidades, 438 por el dueño de su cuenta y 116 por
  semilla; la segunda pasada, cero. En Docker, `sales` no lee `identity` ni
  `party`: la parte `usuarios` con `--enlaces` escribe `comerciales` y
  `venden`, y `duenos_cuenta` se pasa en el mismo fichero; sin él se reparte
  sólo por semilla y **lo dice**. `--comprobar` añade «toda oportunidad ganada
  tiene dueño».
- **Comisiones.** Las liquidaciones salían a 0,00 € y sin líneas: el servicio
  no lee las ventas —las trae quien llama— y el sembrado no traía ninguna. Se
  siembra un plan **sobre cierre** (`cierre_<año>`, escalado marginal 2 % hasta
  100.000 € al mes y 3 % por encima) —el `directa_<año>` se devenga al cobrar
  y comisionar sobre él lo ganado sin cobrar contradiría su propia
  declaración—, se asigna a quien vende y se liquida **el último mes
  cerrado** con sus ventas ganadas como operaciones. Medido: cuatro
  liquidaciones con 37 líneas.
- **Bandeja de aprobaciones.** Es de cada persona, y quien pide no se aprueba
  a sí mismo: pedida por quien siembra no llega nunca a su bandeja, y el
  servicio rechaza la etapa. La pide la segunda persona de `--aprobador`; sin
  ella no se siembra y se dice. Y la aprobación de descuento que ya sembraba
  `las_que_siguen_vacias` se duplicaba en cada pasada —ocho copias— y tenía
  por aprobador al primero del listado de usuarios, que era la auditora, de
  solo lectura: ahora sale del organigrama y lleva `unico_por`.
- **Firma.** Los sobres van por la oportunidad (`enviar-a-firma`) y **sin
  mandar**: no hay proveedor real y mandarlo llamaría afuera, así que quedan en
  borrador. Hacía falta un proveedor que identifique por correo —el sembrado
  sólo admitía SMS, vídeo o certificado y la oportunidad no pasa
  identificación, así que **todo envío desde la ficha salía rechazado**— y una
  regla que lo elija. La firma en mano es la conformidad de dos pedidos con el
  comercial de la cuenta como testigo, con consentimiento y un trazo que pasa
  el mínimo.
- **Audiencia publicitaria.** Una conexión «Plataforma de anuncios» con sus
  tres operaciones y una audiencia sobre «Perfiles técnicos»; **no se
  sincroniza**, porque llamaría afuera, y se queda en borrador.
- **Programación de integraciones.** Dos lecturas del ERP —clientes cada día,
  pedidos cada hora— **en pausa**: la conexión sembrada apunta a un dominio de
  verdad y activarla haría que el programador lo llamase en cada vuelta.

Todo se puede repetir: cada alta mira antes si ya está (por clave, por título,
por el registro de origen o, si no hay listado, por el 409 de la base), y
medido en tres pasadas la tercera crea **cero**.

**Lo que queda vacío, y por qué:**

| Pestaña | Por qué |
|---|---|
| eventos/fallidos, marketing/papelera, encargos/estados-sin-mapear | Son listas de problemas: vacías es lo sano. Sembrarlas sería fingir una avería. |
| eventos/archivo | Se llena cuando un evento pasa su retención y se archiva; ninguno la ha pasado todavía. |
| integraciones/registros-recibidos | Llegan cuando un sistema de fuera contesta a una lectura; las lecturas están en pausa porque no hay ERP conectado. |
| dispositivos-confianza | Son de una persona y de su navegador; no se crean desde fuera. |
| proveedores-identidad | SAML y OIDC apagados en esta instalación; un proveedor falso pondría un botón de entrar que no funciona. |
| extensiones/firmantes | Dar por buena una clave pública es una decisión de seguridad de una persona; sembrarla sería enseñar a confiar en algo que nadie ha verificado. |
| aislamiento/migraciones | Planificar un cambio de aislamiento es una operación sobre un tenant de verdad, no un dato de ejemplo. |
| captura/recepciones | Ya no está vacía: el 10-11-2026 se dejaron cuatro recepciones de demostración en el canal `web-demostracion`, entradas por las dos puertas desde otra web (abajo). |

**Las dos puertas de la captura** estaban rotas el 10-11-2026 —la pública
contestaba 404 desde fuera y el formulario incrustado 401— y ya funcionan: ver
«La captura desde la web y los componentes incrustables» más abajo. Medido en
la plataforma: el formulario público y el incrustado, llamados desde otra web,
dejan cada uno su recepción `creado` y su lead.

Las cinco rutas que el recorrido da como «fallan» (`campanas/calendario`,
`creditos-servicio/cumplimiento`, `encargos/cumplimiento`, `encuestas/resumen`,
`sla/cumplimiento`) no están vacías ni rotas: exigen `desde` y la sonda no lo
manda; la pantalla sí.

### Vocabularios de la casa, cuatro umbrales y la ventana de las cadencias (10-11-2026)

**La ventana de envío de las cadencias.** `cadencias._siguiente_laborable`
comparaba 8, 9 y 19 con `momento.hour` sobre un instante en UTC: en Madrid la
ventana iba de 9 a 20 en invierno y de 10 a 21 en verano, y el día de la
semana también se miraba en UTC. Ahora:

- `cadencias.VentanaEnvio(zona, desde, hasta, reprograma)` y
  `ventana_envio(db)`, que lee `crmcore.fechas.zona_del_tenant(db)` y tres
  ajustes del núcleo (`config_parts/_limits.py` + `runtime/keys.py`):
  `cadencia_hora_desde` (8), `cadencia_hora_hasta` (19) y
  `cadencia_hora_reprograma` (9). En el núcleo y no en `services/sales/ajustes.py`
  para que la consola de **Ajustes** los liste (ver el hallazgo de abajo). Una
  ventana vacía o al revés (`desde >= hasta`) avisa en el log
  (`cadencias.ventana_invalida`) y usa la de fábrica; un `reprograma` fuera de
  la ventana se recoloca a `desde`.
- `_siguiente_laborable(momento, solo_laborable, ventana=None)` convierte a la
  zona, recoloca con `datetime.combine(dia, time(reprograma), tzinfo=zona)`
  —las 9 son las 9 de ese día, con el desfase que tenga— y devuelve UTC.
  `avanzar` lee la ventana **una vez por pasada** y suma `espera_dias` en el
  reloj local (`ahora.astimezone(zona) + timedelta(days=n)`), así que «dentro
  de tres días» que cruza el cambio de hora no se corre una hora.
- **La zona del destinatario no se usa**: ventas no la tiene. La inscripción
  guarda el correo y, como mucho, `Lead.pais` (un país puede tener varias
  zonas); la única zona por persona de la casa es `zona_horaria` del perfil de
  marketing, en otro servicio, y `avanzar` no puede llamar a otro servicio por
  cada inscripción.
- **El primer paso**, cerrado el mismo día (ver «La consola de ajustes conoce
  los de cada servicio», más abajo): `inscribir` programa
  `proximo_at = _siguiente_laborable(_ahora(), cadencia.solo_laborable,
  ventana_envio(db))`. `avanzar` sigue sin mirar la ventana al ejecutar: lo
  que ya está programado dentro de ella se ejecuta en la pasada que toque.

Prueba: `test_cadencias.py::test_la_ventana_es_la_del_reloj_del_tenant_tambien_al_cambiar_la_hora`
(Madrid, lunes 19-10 y 26-10 a las 18:30 locales con `hasta` = 18: las dos se
recolocan a las 9 locales, 07:00 y 08:00 UTC; y viernes 10:00 + 3 días cae el
lunes a las 10:00 locales).

**Cinco vocabularios nuevos** (`crmcore.vocabulario`, como `factores_leccion`):

| Vocabulario | Servicio | Era | Fijos |
|---|---|---|---|
| `roles_compra` | sales | `ingresos.ROLES_COMPRA` | `decisor`, `economico` (`grupo_de_compra`, `api.py` del decisor; `ROLES_COMPRA_FIJOS`) |
| `roles_equipo_cuenta` | party | `servicio.ROLES_EQUIPO` | — (la propiedad es `owner_id`, no el rol) |
| `relaciones_persona` | party | `cuenta_360.RELACIONES` | — (el mapa agrupa por código) |
| `funciones_contacto_proveedor` | party | `proveedores.FUNCIONES_CONTACTO` | `escalado` (`a_quien_llamo`, `FUNCION_ESCALADO`) |
| `resultados_llamada` | service | `marcador.RESULTADOS` | `hablado`, `numero_erroneo`, `pide_que_no_le_llamen`, `reprogramar` (`marcador.colgar`; `telefonia_resultado_numero_erroneo` en integration) |

- **Fijos** (`vocabulario.registrar(..., fijos=...)`, nuevo): los de fábrica que
  el código lee valor a valor. `valores()` los admite siempre; el router de
  vocabularios contesta **409 `vocabulario.valor_fijo`** a retirarlos (PATCH
  `activo=false` o DELETE) y deja cambiar rótulo y orden; cada fila y cada
  vocabulario dicen `fijo`/`fijos`. Un fijo que no esté entre los de fábrica es
  un `ValueError` al registrar.
- **Opinión en una relación nueva**: `cuenta_360._es_opinion(db, tipo)` = de
  fábrica (`RELACIONES_QUE_SON_OPINION`) o con `extra.opinion` verdadero en su
  fila del vocabulario; exige motivo igual.
- Se valida contra `vocabulario.valores(db, …)`; las columnas pierden
  `info={"opciones": …}` (era la lista cerrada del contrato, como ya pasaba con
  `motivo_perdida`). El marcador recibe `admitidos=marcador.resultados_validos(db)`
  desde `POST /marcador/colgar`; `services/service/api.py` importa `marcador`
  al arrancar porque un vocabulario que no está registrado al montar la app no
  tiene ruta (party y service montan ahora `/{servicio}/vocabularios`).
- **Front**: cinco pestañas en el módulo `modelo` (Gestor de objetos), y
  «Vocabularios de negocio» pasa a `por_servicio: ["sales", "party", "service"]`.
  `Marcador.tsx` pide `/api/v1/service/vocabularios/resultados_llamada` al
  abrir una llamada (no al pintar la ficha) y rotula los de fábrica con la
  traducción y los de la empresa con su etiqueta.
- **`superficie.rutaPermitida` casa ahora por tramos**, con `{param}` como
  comodín (como `operacionDe`). Sólo por prefijo, `/sales/vocabularios/roles_compra`
  no casaba con `/sales/vocabularios/{nombre}` y la pestaña se escondía en
  cuanto llegaba la superficie: medido en vivo, «Factores de una lección» abría
  la primera pestaña de Lecciones, y las cinco nuevas, la de Objetos.
- **Longitud**: las columnas que guardan un valor de vocabulario son
  `String(120)`, como `valores_vocabulario.valor` (ver más abajo).
- **`postventa.MOTIVOS_SUSPENSION` se queda cerrada**: no por una rama de
  código, sino porque es el control. Son los motivos que la norma reconoce
  para parar el plazo legal de una reclamación; editable, el plazo se pararía
  por «mucho trabajo».

Pruebas: `test_vocabularios.py::test_un_valor_fijo_se_renombra_pero_no_se_retira`,
`test_ingresos_y_equipo.py::test_un_rol_de_compra_inventado_se_rechaza` (y
admitido si la empresa lo añade), `test_calidad_del_dato.py::test_llamar_detractor_a_alguien_exige_motivo`
(una relación añadida con `opinion`).

**Cuatro umbrales a ajuste** (núcleo, en la consola): `transcripcion_correccion_maxima_pct`
(40, `transcripcion.calidad_de_la_extraccion`), `caso_parecido_uso_minimo_pct`
(15, `caso_semantico.aprender_de_lo_usado`), los dos en
`config_parts/_intelligence.py`; `convivencia_medida_fresca_dias` (30,
`convivencia.progreso`) y `sandbox_copia_aviso_pct` (20, `sandboxes.plan_de_copia`,
en `_tenancy.py`). Las funciones puras reciben el umbral por parámetro; sus
rutas (`/transcripciones/calidad`, `/sugerencias-caso/aprovechamiento`,
`/sandboxes/plan`) lo leen con `rt.efectivo(clave, db)` y la respuesta lo
devuelve (`maximo_pct`, `minimo_pct`, `dias_que_vale_una_medida`,
`aviso_pct`). Sin sesión,
el del `.env`.

**Hallazgo, cerrado el mismo día**: la consola de **Ajustes** (`GET/PUT
/api/v1/ajustes`, en tenancy) sólo conocía las claves del núcleo, y las que
declaran los `services/*/ajustes.py` con `registrar_claves` se rechazaban como
`ajustes.clave_desconocida`. Ver «La consola de ajustes conoce los de cada
servicio», más abajo. Las de este bloque se quedan en el núcleo.

### La captura desde la web y los componentes incrustables (10-11-2026)

**Lo que fallaba.** Ninguna vía de captura funcionaba desde fuera.
`POST /captura/{tenant}/{clave}` contestaba 404: el gateway sólo reenviaba
`/api/*` y la captura va sin prefijo de versión a propósito. Y los cuatro
componentes incrustables contestaban 401: el token de componente no lleva
`id`, `es_anonimo` lo daba por anónimo y `AutenticadoDep` lo rechazaba. No se
podía «quitarle el anónimo»: el token vive en el HTML de una página pública y
entraría en toda ruta que sólo pide estar autenticado.

**Una dependencia propia, y la guarda en la que pasa por todo.**

- `crmcore.http.deps.exige_componente(componente)` es la única puerta del
  token: comprueba que sea de componente, de ESE componente y tipo de objeto
  (`embebido.registro_del_token`), que lleve dentro los permisos de su ruta,
  y devuelve `AccesoComponente(tenant_id, objeto_id, principal)`. El tipo de
  objeto y los permisos salen de `crmcore.embebido.OBJETO_DE_COMPONENTE` y
  `PERMISOS_DE_COMPONENTE`, la misma tabla con la que el gateway emite el
  token (`emitir` rechaza ahora un objeto que no es el del componente,
  `embebido.objeto_no_corresponde`). Las cuatro rutas
  (`services/{party,service,sales}/api_embebido.py`) la usan en vez de
  `AutenticadoDep`.
- `contexto_autenticado` —la pide la dependencia global de idempotencia, así
  que pasa por TODAS las rutas— rechaza un token de componente con 401
  `embebido.ruta_no_admite_componente` si la ruta no lleva la marca
  `admite_componente` en sus dependencias (`ruta_admite_componente`, que mira
  `request.scope["route"].dependant`). Cortarlo sólo en `exige_autenticacion`
  dejaba abiertas las rutas que sólo piden `DbDep`: con un principal sin `id`
  pero con tenant, `get_db` abría sesión en su empresa. `exige_autenticacion`
  lo rechaza además por tipo, aunque algún día el token lleve `id`.
- En el gateway, `/api/v1/embebido/{componente}` (`proxy_embebido`) es la
  única ruta que lleva la marca: comprueba en la puerta que el token sea de
  ese componente y reenvía por `_proxiar`, el cuerpo común con el proxy
  general (operatividad del tenant, acceso contextual, anomalías). El proxy
  general `/api/{ruta}` no la lleva, así que un token de componente en
  `/api/v1/accounts` muere en el gateway sin llegar al servicio.

**La captura pública, por su nombre.** `captura_publica` en
`services/gateway/api.py` reenvía `POST /captura/{tenant}/{clave}` a `sales`
**sin identidad** y sólo con `content-type` y `x-captura-secreto`
(`incrustable.CABECERAS_DE_CAPTURA`), después del tope por IP
(`rutas.TOPES_POR_IP["/captura/"]`), el tamaño
(`incrustable.cuerpo_acotado`, que corta también un cuerpo por trozos sin
longitud declarada) y la operatividad y el plan del tenant. El formulario
incrustado lleva el mismo tope por IP (otro contador) y el mismo tamaño. Y la
ruta de `sales` contesta ahora siempre `{"recibido": true}`: devolvía el
`lead_id`, nulo al descartar, que le decía a un robot si había caído en la
trampa.

**El CORS de lo incrustable.** El general (`CORS_ORIGINS`, con credenciales)
contestaba con 400 la pregunta previa del navegador desde la web de un
cliente. El middleware `lo_que_se_incrusta` de `services/gateway/main.py`,
por fuera del general, atiende `/captura/*` y `/api/v1/embebido/*`: admite el
origen según `INCRUSTABLE_ORIGENES` (`*` de serie), **nunca con
credenciales**, contesta él la pregunta previa y responde 403
`incrustable.origen_no_admitido` a una web no admitida. Sin cabecera `Origin`
no mira nada: no es un navegador.

**Ajustes** (`config_parts/_limits.py`, sólo `.env`: el gateway no tiene base
de datos y un ajuste en caliente ahí se guardaría sin aplicarse):
`CAPTURA_PUBLICA_INTENTOS_POR_IP` (30), `CAPTURA_PUBLICA_VENTANA_S` (3600),
`CAPTURA_PUBLICA_MAX_BYTES` (16384), `INCRUSTABLE_ORIGENES` (`*`).

**El componente** (`frontend/src/embebido/index.ts`). `formulario-alta`
mandaba `{}` en cuanto se pintaba —cada visita dejaba una recepción
descartada— y ahora pinta su formulario con la trampa oculta y manda al
enviar. Y todo lo que viene del CRM se escapa antes del `innerHTML`: un
asunto de caso con `<img onerror>` se ejecutaba en la web del anfitrión. El
fichero que se incrusta sale de `npm run build:embebido`
(`frontend/dist-embebido/embebido.js`) y lo sirve el front en `/embebido.js`:
ver «Las tres puertas de fuera, cerradas» más abajo.

**Medido en vivo** contra la plataforma, desde una página en otro origen
(`http://127.0.0.1:18991`): el formulario público y el incrustado crean su
lead y su recepción `creado` en el canal `web-demostracion` («Formulario de
contacto de la web», trampa `web`, obligatorio `email`); `ficha-cuenta`,
`lista-casos` y `estado-pedido` se pintan con sus datos; el token de
`ficha-cuenta` contesta 401 en `/api/v1/accounts`, `/api/v1/captura/recepciones`
y `/api/v1/sdk/componentes`, y 403 en `/api/v1/embebido/lista-casos`. Se ven en
**Ventas › Candidatos › Recepciones**. Quedan cuatro recepciones
de demostración: la verificación se pasó dos veces y la segunda marcó sus dos
leads como posibles duplicados de los primeros, que también sirve para
enseñar la deduplicación al capturar.

Pruebas: `tests/unit/test_lo_que_se_incrusta_entra_por_su_puerta.py` —el token
entra en su ruta y en ninguna otra, ni en la de solo `PrincipalDep`; la ruta
del componente no atiende otro componente ni una sesión; el gateway lo deja
sólo en su componente; la captura se reenvía sin identidad, con su CORS, su
tamaño y su origen; validada quitando la guarda de `contexto_autenticado`:
fallan dos— y `frontend/src/pruebas/embebido.test.ts` (el formulario no
escribe al pintarse; lo del CRM se pinta como texto).

### Las tres puertas de fuera, cerradas: portal, token de componente y `embebido.js` (10-11-2026)

**El token de portal entraba donde no debía.** Lleva `sub` (el acceso) y
`tenant`, así que `contexto_autenticado` lo convertía en un principal con `id`
y pasaba `AutenticadoDep` en toda ruta que no pide un permiso concreto. Medido
contra la pila viva antes del arreglo: 200 en `/api/v1/superficie` y en
`/api/v1/sdk/componentes` del gateway, y el proxy general lo reenviaba a
cualquier servicio (`/api/v1/accounts` llegaba a `party`, que lo paraba sólo
porque esa ruta pide `account:read`).

- `crmcore.http.deps._PUERTA_DE_TIPO` junta los dos tipos de token que viven
  fuera del CRM con la marca que tiene que llevar la ruta:
  `componente` → `admite_componente`, `portal` → `admite_portal`. La guarda de
  `contexto_autenticado` y `exige_autenticacion` leen esa tabla;
  `_ruta_lleva_marca(request, marca)` recorre las dependencias de la ruta
  (`ruta_admite_componente` queda como atajo). Un token de portal fuera de su
  sitio da 401 `portal.ruta_no_admite_portal`.
- La marca la lleva `crmcore.http.portal_deps.contexto_portal`, que es la
  dependencia de `PortalDep`: toda ruta de `/portal/mi/*` la tiene, y
  `exige_seccion_portal` también, porque depende de ella.
- En el gateway, `/api/v1/portal/mi/{resto}` (`proxy_portal`) es la única ruta
  con la marca. Reenvía por `_proxiar` sin mirar más: quién es y qué secciones
  tiene lo comprueba el servicio con `PortalDep`. `POST /portal/sesion` y
  `POST /portal/enlace` no cambian (no llevan token de portal).

**`token_embebido` comprueba que quien lo pide ve el registro.** El comentario
lo decía y sólo se exigían los permisos: con `integracion:write` y
`party:read` se emitía un token para cualquier identificador, también uno que
no existe (medido: 200 en la pila sin arreglo). Ahora `POST
/api/v1/sdk/componentes/token` valida antes el componente y el objeto
(`embebido.validar`, sacado de `emitir`) y llama a `_exigir_que_lo_ve`: pide
la ficha del registro al servicio dueño **con la identidad firmada de quien lo
pide** (`proxy.cabeceras_de_identidad`). La ruta sale de
`crmcore.embebido.RUTA_DEL_OBJETO` (`cuenta` → `/accounts/{id}`,
`formulario` → `/captura/canales/{id}`, `pedido` → `/pedidos/{id}`) y el
servicio de `rutas.servicio_de`. 200 emite; 403 o 404 → 403
`embebido.registro_no_visible` (los dos igual, para no decir qué existe);
cualquier otra cosa, o el servicio caído → 503 `embebido.no_se_puede_comprobar`.
Cerrado por defecto. La visibilidad (permiso, compartición, unidad de negocio)
es la del servicio dueño, no se copia en el gateway.

**`embebido.js` lo sirve el front, en una ruta estable.**

- Imagen (`frontend/Dockerfile`): `npm run build && npm run build:embebido`, y
  `dist-embebido/embebido.js` se copia a la raíz que sirve nginx.
  `frontend/nginx.conf` tiene `location = /embebido.js` con
  `Cache-Control: public, max-age=3600` (sin hash, así que no puede ser
  inmutable: pasada la hora el navegador revalida con el `ETag`),
  `Access-Control-Allow-Origin: *` **sin** `Allow-Credentials`,
  `Cross-Origin-Resource-Policy: cross-origin` y `nosniff`. Un
  `<script type="module">` de otro origen se pide en modo CORS y no se ejecuta
  sin la cabecera; sin credenciales, nunca lleva la cookie de la consola.
- Pila local (`vite.config.ts`, plugin `servirEmbebido`): el servidor de
  desarrollo construye `/embebido.js` al pedirlo con la misma
  `vite.embebido.config.ts` y lo reconstruye sólo si cambia algo en
  `src/embebido/`. Mismas cabeceras salvo la caché: `no-cache` con `ETag`, para
  que un cambio se vea al recargar.
- `vite.embebido.config.ts` lleva `publicDir: false`: copiaba el `sw.js` de la
  consola a `dist-embebido/`.

Cómo se pega en la web del cliente (el token lo emite **su servidor** con una
clave de API, nunca el navegador; va en el HTML de la página):

```html
<script type="module" src="https://crm.ejemplo.com/embebido.js"></script>
<contecrm-componente
  componente="formulario-alta"
  api="https://api.crm.ejemplo.com/api/v1"
  token="…el de POST /api/v1/sdk/componentes/token…"></contecrm-componente>
```

`src` es el origen del front (en local, `http://localhost:15173/embebido.js`);
`api`, el del gateway con su prefijo. La web del cliente tiene que estar en
`INCRUSTABLE_ORIGENES` (`*` de serie). Medido: `curl` al 15173 y a un nginx con
esta configuración devuelven 200 con esas cabeceras, y 304 con `If-None-Match`.

**Medido en vivo** con un segundo gateway con este código (puerto 18091) contra
los servicios de la pila: token para una cuenta, un canal de captura y un
pedido existentes → 200; para un identificador inventado → 403
`embebido.registro_no_visible`; el token emitido se usa en
`/api/v1/embebido/ficha-cuenta` → 200. Portal con un enlace de verdad
(`/portal/enlace` + `/portal/sesion`): `/portal/mi/resumen` y `/portal/mi/casos`
→ 200; `/accounts`, `/superficie`, `/sdk/componentes` y `/auth/me` → 401
`portal.ruta_no_admite_portal`. La pila compartida sigue con el código anterior
hasta su próximo arranque.

Pruebas, en `tests/unit/test_lo_que_se_incrusta_entra_por_su_puerta.py`:
`test_el_token_de_portal_entra_en_el_portal_y_en_ninguna_otra_ruta`,
`test_el_gateway_deja_el_token_de_portal_sólo_en_el_portal` (fallaban las dos
antes del arreglo) y
`test_el_token_sólo_se_emite_para_un_registro_que_quien_lo_pide_ve` (pregunta
a `party` con el `x-crm-user` de quien lo pide; 403 para la cuenta que el
servicio no le da).

**Recepciones de captura, de primer nivel.** `Recurso.fija` (nuevo, en
`frontend/src/lib/modulos.ts`): la pestaña se pinta con su nombre en la
cabecera del listado (`CabeceraDeLista`), fuera del desplegable de objetos.
La lleva «Recepciones» en el módulo `leads`; el menú de Ventas ya tiene diez
entradas. Prueba: `frontend/src/pruebas/recepciones_de_primer_nivel.test.tsx`
(validada quitando `fija`).

**Descripciones de ruta.** Las de «Quitar una programación» (analytics) y
«Promover automatizaciones desde un sandbox» e «Instalar una plantilla de la
biblioteca» (automation) abrían contando lo que fallaba; ese porqué baja a un
comentario y `test_la_descripcion_no_es_una_nota_de_cambio.py` vuelve a verde.

### La consola de ajustes conoce los de cada servicio (10-11-2026)

**Lo que fallaba.** `crmcore.runtime.keys.CLAVES` es por proceso. La consola
vive en `tenancy`, que no puede importar el `ajustes.py` de otro servicio
(`test_ningun_servicio_importa_modulos_de_otro`), así que sólo conocía las 133
claves del núcleo. Las 166 que registran `analytics`, `integration`,
`intelligence`, `marketing`, `party`, `sales` y `service` no salían en
`GET /api/v1/ajustes` y `PUT` las rechazaba (`ajustes.clave_desconocida`).

**Cada servicio publica, la consola agrega.** Una clave sigue declarada en un
solo sitio —el `ajustes.py` de su dueño— y el valor fijado le llega por la
réplica de siempre (`configuracion.ajuste_cambiado`, que `consumir_ajuste`
aplica porque la clave es suya).

- `keys.registrar_claves` anota en `_REGISTRADAS` lo que añade el servicio;
  `claves_del_servicio()`, `a_dict()` y `de_dict()` las serializan.
  `ClaveAjuste.servicio` (nuevo, vacío en el núcleo) dice de quién es.
  `incorporar_de_otro_servicio(decl)` la mete en `CLAVES` **sin pisar nunca una
  del núcleo** ni una propia del proceso.
- `crmcore/http/ajustes_catalogo_router.py`: `GET
  /api/v1/interno/ajustes/catalogo`, montado por `crear_servicio` en todos los
  servicios, con `exige_firma_interna` y fuera del contrato (el gateway no
  enruta `interno`). Devuelve las claves propias con `por_defecto` =
  `rt.efectivo(clave)` sin sesión: el `.env` **del dueño**.
- `services/tenancy/ajustes_remotos.py`: `asegurar()` pregunta en paralelo a
  todos los de `RUTAS_SERVICIOS` (salvo tenancy y gateway), con
  `http_interno_timeout_s`, incorpora lo que llega y guarda los valores por
  defecto en un proveedor registrado con `registrar_ajustes_servicio`, que es
  por donde `efectivo()` ya buscaba el defecto de un ajuste de servicio. Se
  refresca con `ajustes_ttl_cache_s` y, si alguno no contestó, en la llamada
  siguiente; los que no contestan salen en la cabecera
  `X-Ajustes-Sin-Catalogo` del listado y en el log
  (`ajustes.catalogo_sin_respuesta`). La llaman `GET /ajustes`, `PUT
  /ajustes/{clave}` (con una clave desconocida fuerza la pregunta),
  `POST /ajustes/versiones/{id}/volver` y las dos de `/mis-preferencias`.
- `valores_efectivos` devuelve además `minimo_ambito` y `servicio` (`nucleo`
  para las del núcleo); la pantalla genérica los ofrece en **Columnas**.
- `integration` y `service` importan ahora su `ajustes.py` en `main.py`.
  `integration` sólo lo importaba dentro de funciones y publicaba **cero** de
  sus 27: lo cazó la medida en vivo (272 de 299).

**Medido en vivo** (10-11-2026, pila local con NATS): el listado da 299
claves —133 núcleo, analytics 4, integration 27, intelligence 30, marketing
37, party 26, sales 38, service 4— sin servicios que no contesten. Fijadas
desde la consola en el tenant de la plataforma: `riesgo_concentracion_pct` 40
→ 80 (party, `POST /proveedores/riesgo`: de 1 proveedor crítico a 0, en 1 s),
`margen_minimo_pct` 20 → 30 (sales, `POST /coste/margen` de una línea al 25 %:
`necesita_aprobacion` pasa a verdadero, en 0,5 s) y `sla_riesgo_horas` 4 → 7,5
→ 6 (service, `GET /casos/bandeja`: `riesgo_horas` lo sigue en 1,2 s). Un 500
en `margen_minimo_pct` da 422 `ajustes.fuera_de_rango`; el historial guarda
`antes` 20 y `despues` 30. Se dejaron como estaban quitando el valor del
tenant (`rt.quitar`), y las tres rutas volvieron a 40, 20 y 4 por la misma
réplica.

**El primer paso de una cadencia respeta la ventana.** `cadencias.inscribir` programa
el primer paso con `_siguiente_laborable` y la ventana del tenant: inscribir
un viernes a las 23:00 UTC lo deja para el lunes a las 9 locales, y una pasada
de `avanzar` en ese momento no ejecuta nada.

**Las columnas de vocabulario, a 120.** Ensanchadas en vez de limitar el
vocabulario: el tope del vocabulario es uno y común (`valores_vocabulario.valor`,
`String(120)`, y el router lo valida con `max_length=120`), mientras que cada
columna tenía el suyo. Migraciones `20261110_1010_vocabulario_cabe_entero` en
`sales` (`roles_compra.rol` 20, `leads.motivo_descarte`,
`oportunidades.motivo_perdida` y `lecciones_oportunidad.motivo` 80), `party`
(`contactos_proveedor.funcion` y `relaciones_persona.tipo` 20,
`equipo_cuenta.rol` 40) e `integration`
(`llamadas_telefonicas.resultado_comercial` 40, que además se recortaba con
`[:40]` en silencio; su `max_length` de entrada pasa a 120). Ensanchar un
`varchar` no reescribe la tabla; el `downgrade` falla si ya hay un valor más
largo, a propósito. Ninguna toca `server_default`.
`scripts/migraciones_locales.py comprobar`: los trece, «al día».

Pruebas: `tests/unit/test_la_consola_conoce_los_ajustes_de_cada_servicio.py`
(el dueño publica las suyas con su defecto y sin firma no se entra; la consola
valida, limita el ámbito y resuelve el defecto del dueño sin pisar una del
núcleo, y dice quién no contestó; todo `main.py` importa su `ajustes.py`,
validada quitando el import de `integration`) y
`test_cadencias.py::test_el_primer_paso_tambien_espera_a_la_ventana` (validada
devolviendo `proximo_at = _ahora()`). Las pruebas que inscriben y avanzan en
seguida fijan el reloj dentro de la ventana (`en_horario`): sin eso, de noche
o en fin de semana fallaban por la hora.

### 4.6.70 Deshacer el primer cambio de un ajuste vuelve a heredar (10-11-2026)

`runtime.settings.fijar` apuntaba en la versión el valor **efectivo** de antes
—el de fábrica si el ámbito no tenía uno propio—, así que deshacer el primer
cambio de una clave fijaba ese valor de fábrica en el tenant para siempre: la
clave dejaba de seguir los cambios de serie sin que nadie lo hubiera decidido.
Ahora apunta el valor **propio** del ámbito (`None` si no tenía), y
`versiones.volver_a` ya sabía que `None` es «quitar y heredar». La auditoría
sigue diciendo el efectivo. La prueba que lo cubría ponía el `None` a mano, que
es lo que escondía el fallo; ya no lo fuerza.

### 4.6.71 Usabilidad medida por tarea: antes, después y Salesforce (10-11-2026)

Las doce tareas más frecuentes de un comercial, un agente de soporte y un
responsable, hechas **por la interfaz** desde la portada y medidas con
Playwright. Se vuelve a medir en cada bloque:

    ./setup.sh arrancar
    node frontend/scripts/medir-tareas.mjs              # las doce
    node frontend/scripts/medir-tareas.mjs T02 T05      # sólo esas
    MEDIR_JSON=/ruta/medida.json node frontend/scripts/medir-tareas.mjs

Entra con las mismas variables de entorno que `barrido-pantallas.mjs`
(CRM_EMPRESA, CRM_USUARIO y CRM_CLAVE, y CRM_URL para otra instalación); son
del guion, no ajustes del producto. MEDIR_CAPTURAS es la carpeta de capturas
de lo que falla y MEDIR_DEPURAR=1 imprime las escrituras y los 409. Sale con 1
si no ha medido nada.

**Qué cuenta.** Clics (botón, enlace, pestaña u opción; entrar en un campo
para escribir no), teclas que hacen algo (Intro), campos rellenados,
pantallas distintas recorridas (la portada incluida; `?r=` cuenta como otra
lista), segundos de reloj hasta la comprobación (los de la máquina: lo que
hace esperar el sistema) y una **estimación** del tiempo de una persona con
el modelo KLM (1,2 s por clic, 0,28 s por carácter o tecla, 1,35 s de pensar
por campo y por pantalla). Errores: 400, 404, 422 y 5xx de la API y
excepciones de la página; 401, 403 y 409 no. **Hecha** quiere decir
comprobada por la API —el lead convertido con cliente, contacto y
oportunidad, el presupuesto enviado, el caso cerrado, la actividad colgando
del registro—. **Bloqueo** es lo que no se puede terminar sin saber algo que
una persona no sabe (un identificador interno) o sin salir de la ficha.

Cada tarea arranca en la aplicación de su rol (Ventas o Servicio) y busca por
el buscador de arriba, eligiendo con Intro sólo si el registro sale el
primero. Todo lo que crea lleva «UX medida» y se borra al acabar; lo que el
producto no deja borrar se archiva (un lead ya repartido y la oportunidad que
nace al convertirlo) y la aprobación de la T12 queda decidida, porque el motor
no borra aprobaciones.

**Referencia de Salesforce: estimación, no medida.** Clics de Lightning
Experience con la configuración de serie y el camino más corto conocido; no
hay una instancia de Salesforce contra la que medir.

| # | Rol | Tarea | Antes (clics · campos · pantallas · s · persona) | Después | Salesforce (est.) |
|---|---|---|---|---|---|
| T01 | Comercial | Encontrar un cliente por nombre | 2 · 1 · 2 · 2,0 s · ≈11 s (Intro abría una oportunidad con su nombre) | 1 + Intro · 1 · 2 · 2,3 s · ≈10 s | 2 |
| T02 | Comercial | Alta de un lead y convertirlo en cliente, contacto y oportunidad | **Bloqueo** tras 7 clics: convertir pedía un cliente ya existente | 6 · 3 · 4 · 5,0 s · ≈29 s | 6 |
| T03 | Comercial | Oportunidad para un cliente, con importe y cierre | 6 + Intro · 5 · 3 · 5,3 s · ≈40 s | 3 + Intro · 4 · 4 · 4,8 s · ≈33 s | 7 |
| T04 | Comercial | Mover una oportunidad de etapa | 2 + Intro · 1 · 2 · 3,5 s · ≈14 s | 2 + Intro · 1 · 2 · 3,6 s · ≈14 s | 4 |
| T05 | Comercial | Presupuesto de la oportunidad, y enviarlo | **Bloqueo** tras 15 clics: sin «Enviar»; «Enviado» del desplegable lo rechaza el servidor | 6 + Intro · 5 · 4 · 6,0 s · ≈34 s | 14 |
| T06 | Comercial | Registrar una llamada en un cliente | 3 + Intro · 2 · 2 · 2,9 s · ≈22 s | igual | 4 |
| T07 | Comercial | Registrar una reunión en una oportunidad | **Bloqueo**: la ficha no deja anotar; el alta suelta pide el identificador | 3 + Intro · 2 · 2 · 3,8 s · ≈21 s | 5 |
| T08 | Soporte | Abrir un caso para un cliente, con prioridad | 7 + Intro · 4 · 3 · 5,6 s · ≈40 s · 1 error (422) | 3 + Intro · 3 · 4 · 3,7 s · ≈31 s · 0 | 10 |
| T09 | Soporte | Responder un caso (anotar la respuesta) | **Bloqueo**: el buscador no encontraba casos y la ficha no tenía dónde anotar | 3 + Intro · 3 · 2 · 2,9 s · ≈30 s | 4 |
| T10 | Soporte | Cerrar un caso con su motivo | 7 · 3 · 3 · 4,0 s · ≈27 s | 3 + Intro · 2 · 2 · 2,8 s · ≈15 s | 6 |
| T11 | Responsable | Ver la previsión del trimestre en curso | 4 · 0 · 3 · 2,4 s · ≈9 s | 2 · 0 · 3 · 1,8 s · ≈6 s | 2 |
| T12 | Responsable | Aprobar algo pendiente | 10 · 1 · 4 · 3,9 s · ≈19 s (Administrar › Procesos) | 1 · 0 · 1 · 0,7 s · ≈3 s | 3 |

Antes: 7 de 12 terminadas y 5 bloqueos. Después: 12 de 12, cero errores.

**Qué se cambió, por fricción medida:**

- **Convertir en un paso** (T02). `frontend/src/componentes/ConvertirLead.tsx`:
  propone el cliente (crearlo con la empresa del lead, o usar el que ya se
  llama exactamente así, buscado en `/api/v1/buscar`), el contacto colgado de
  él y la oportunidad, y lo crea en orden por `POST /accounts`,
  `POST /contacts` y `POST /leads/{id}/convertir`; lo creado en un intento
  fallido se reutiliza. La ficha lo monta cuando la acción abierta es
  `convertir` de un lead.
- **Acciones a la vista** (T02, T05, T10). `Recurso.destacadas` (último tramo
  de la ruta) y la prop `destacadas` de `BotonesDeRegistro`: Candidatos
  `convertir`, Casos `cerrar`, Ofertas `enviar`. El rótulo corto sale de
  `acciones.destacada.*`. La ficha del presupuesto ofrece por fin las
  acciones del contrato (enviar, aceptar, versión siguiente).
- **Tras el alta, la ficha** (`Modulo.tsx`, `crear`): se navega al registro
  creado salvo que traiga valores de una sola vez.
- **El alta sabe de dónde se viene**: cualquier parámetro de la URL que se
  llame como un campo del alta la rellena, y es a la vez filtro de la lista.
  «Nueva oportunidad» y «Nuevo caso» desde el cliente llevan `cuenta_id`;
  «Nueva oferta» desde la oportunidad, `oportunidad_id`. El servidor deduce
  cuenta y contacto del presupuesto de la oportunidad
  (`services/sales/presupuestos.py::crear`). La pastilla del filtro enseña el
  nombre del registro, no su identificador (`Filtros.tsx`).
- **Delante, lo que importa** (`Formulario.tsx`): en un alta van delante los
  obligatorios, las columnas preferidas del recurso y lo que ya viene relleno
  (prop `delante`).
- **Apuntar en la oportunidad y el caso** (T07, T09):
  `ActividadDelRegistro.tsx` (llamada, reunión, nota, correo y lo último
  apuntado) en «Relacionado».
- **Una confirmación, no dos** (`Acciones.tsx`): lo irreversible con
  formulario se confirma al enviarlo; «Lo entiendo, sigue» queda para lo que
  se ejecuta de un clic.
- **Te toca decidir en la portada** (T12): `Inicio.tsx` pinta
  `GET /aprobaciones/bandeja?limite=6` con «Aprobar» y «Rechazar»
  (`POST /aprobaciones/{solicitud_id}/decidir`).
- **Previsiones abre por los periodos** (T11): `principal` pasa de «Ingreso
  previsto» a «Periodos» en `recursos.ts`.
- **Buscador**: los casos entran en el índice (`services/service/indexacion.py`,
  al abrir, cambiar de estado, cerrar y reabrir; ruta `/api/v1/service/buscar`;
  el gateway pregunta también a `service`; migración de datos
  `service/20261110_1200_casos_en_el_buscador` para los que ya estaban). El
  gateway pone delante el título idéntico y luego el que empieza por lo
  buscado. La relevancia pondera título (A), subtítulo (B) y cuerpo (D). Lo que
  está en la papelera no se encuentra, y vuelve al restaurarlo.
- **Fallos que salieron midiendo**: numerar contando filas repetía el número
  del último borrado (`uq_presupuesto_version`, 409 en cada alta siguiente);
  presupuestos, pedidos, contratos, devoluciones y expedientes pasan al
  contador común (`crmcore.numeracion.emitir`). En los modelos cuya versión
  es de negocio (VERSION_ES_DE_NEGOCIO en la clase) el ETag no cambia al editar y el navegador recibía 304 con el presupuesto
  de antes: esos modelos ya no contestan 304. El desplegable de categoría del
  caso pedía `limite` a una ruta que no lo admite (422): se reintenta sin él.
  Las columnas de Ofertas usaban `codigo`, que el presupuesto no tiene: ahora
  `numero`, y la fila se abre por su número.
- **Nada se sale a 390 px**: la fila de acciones de la cabecera envuelve
  (`DatosClave.tsx`) y la columna de la portada no se ensancha con un título
  largo. Medido en las ocho pantallas tocadas, a 1440 y 390: cero elementos
  fuera de su sitio.

Pruebas: `convertir_un_lead_de_una_vez.test.tsx` (crea cliente y contacto
colgado, o usa el existente sin duplicar), `formulario_usable.test.tsx`
(delante en el alta), `lo_que_no_se_deshace_no_esta_a_mano.test.tsx` (la
destacada sale a la vista y no se repite en el menú); en Python,
`test_busqueda.py` (papelera y restaurar; caso por su código),
`test_la_busqueda_global_pregunta_donde_hay_que_preguntar.py` (título
idéntico primero), `test_cotizacion.py` (borrar el último no bloquea el
siguiente; la cuenta sale de la oportunidad), `test_etag_de_ida_y_vuelta.py`
(sin 304 con versión de negocio) y
`test_lo_que_preguntan_las_pantallas_de_apoyo.py` (la bandeja de la portada
se pide y se decide por HTTP).

### 4.6.72 Las fricciones que quedaron en las tareas del día (10-11-2026)

Lo que la medida de 4.6.71 dejó apuntado como «queda» en `docs/PILA.md`
(entrada 10), arreglado y vuelto a medir con el mismo guion.

**1. El lead, sin «Más campos».** `Recurso.alta` (en `lib/modulos.ts`): campos
que van delante en el formulario además de las columnas. Candidatos declara
`alta: ["apellidos", "email"]`; `Formulario.tsx` los suma a las preferidas.

**2. La prioridad del caso es un vocabulario.** `prioridades_caso`, registrado
en `services/service/servicio.py` con los de fábrica **en su orden**
(`vocabulario.registrar(..., en_orden=True, etiquetas={...})`: es una escala) y
`media` fija (la de un caso que no dice ninguna). `crmcore.vocabulario` admite
ahora `en_orden` y `etiquetas`, y `valores_en_orden(db, nombre)` da la escala
de la empresa. La columna `casos.prioridad` declara
`info={"vocabulario": "prioridades_caso"}` y pasa a 120 caracteres (migración
`service/20261110_1500_la_prioridad_es_un_vocabulario`). Lo genérico, para
cualquier columna con `info["vocabulario"]`, en `crmcore.http.listados`: el
PATCH de la ficha la publica como texto con `x-vocabulario: servicio/nombre`
(no como `enum`: sería la lista de fábrica para siempre) y valida al guardar
contra lo que tenga la empresa (`vocabulario.valor_no_valido`, 422);
`http/opciones.py` la incluye en `x-opciones` con los de fábrica. El alta
(`AbrirCaso.prioridad`) lleva el mismo `x-vocabulario` y `abrir_caso` valida
con `vocabulario.valores`. El escalado (`operacion._aplicar_escalada`) sube por
la escala de la empresa y no por la tabla de orden que tenía escrita, que se quita. En el
front, `lib/contrato.ts` lee `x-vocabulario` (también al lado de un `anyOf`) y
lo pinta como lista; `lib/vocabularios.ts::useOpciones` pide
`/api/v1/{servicio}/vocabularios/{nombre}` una vez por sesión, con los activos,
en su orden y con su rótulo, y añade el valor actual si está retirado. Lo usan
`Formulario` y `CeldaEditable`. Pestaña **Prioridades de un caso** en Gestor de
objetos.

**3 y 4. Buscar en el servidor.** `?buscar=` en
`crmcore.http.listados.aplicar_filtros_de_la_url`, así que vale para la fábrica
y para todos los listados escritos a mano que la llaman (si la ruta declara su
propio `buscar` —cuentas, contactos—, manda el suyo). Busca palabra por palabra
(Y entre palabras, O entre campos), sin mayúsculas, con `%` y `_` literales, en
los campos que nombran el registro: `__busqueda__` del modelo o, si no,
`CAMPOS_DE_BUSQUEDA` (nombre, apellidos, empresa, asunto, título, código,
número, clave, etiqueta, correo, referencia…), y sólo los que quien pregunta ve
en claro. Un modelo sin ninguno contesta `listado.sin_busqueda` (422) en vez de
devolverlo todo. En el front, `lib/buscar.ts` (`rutaConBusqueda`, la pausa al
teclear —200 ms, la misma que la paleta— y los códigos de «no sabe buscar»): el
selector de referencias (`Formulario.tsx::Referencia`) busca en el servidor lo
que se escribe —mientras llega, filtra lo cargado— y recuerda lo elegido aunque
no esté entre las primeras filas; la lista (`Modulo.tsx`) manda `buscar=` tras
la pausa sin vaciar la tabla (el buscador vive en ella) y `Tabla` recibe la
búsqueda por la prop `busqueda` y no vuelve a filtrar. Con `listado.sin_busqueda`
o `peticion.parametro_desconocido` las dos caen a filtrar lo cargado, y la tabla
lo dice («3 de 50 cargados»); con el servidor, «N elementos con «x»».

**5. Responder un caso manda el correo.** `POST /api/v1/casos/{id}/responder`
(`case:write`; `mensaje`, `para` y `asunto` opcionales) en
`services/service/servicio.py::responder_caso`. Sin `para`, el correo del
contacto del caso (`GET /contacts/{id}` a clientes); sin ninguno,
`service.respuesta_sin_destinatario`. Manda por marketing
(`POST /api/v1/correo/enviar`, nuevo, `activity:write`:
`services/marketing/envios.py::enviar_suelto`): la clase **transaccional**
—su dominio, su remitente y su servidor, `vista_correo.salida`—, con la
plantilla de la empresa del ajuste `respuesta_caso_plantilla` (de serie
`respuesta_caso`; `{{mensaje}}`, `{{asunto}}`, `{{caso.codigo}}`,
`{{caso.asunto}}`) o, si no la tiene, la composición de serie, y lo dice
(`plantilla_de_serie`). Consta tres veces, salga o no: el envío
(`EnvioProgramado`, `origen="respuesta"`, con estado y motivo; se lee en
`GET /envios-programados?origen=respuesta&origen_id=<caso>`), la actividad de
correo en el caso (con «No ha salido: …» delante si no salió y `detalles` con
`enviado`, `para`, `motivo` y `envio_id`) y el evento `respuesta` del
historial del caso. Sólo si sale cuenta como primera respuesta. Las llamadas a
clientes y marketing van con la identidad de quien responde y sólo los permisos
que hacen falta (`crmcore.http.interno.invocar`), con
`respuesta_caso_espera_s` de espera. En la ficha, **Responder** es la destacada
del caso (`destacadas: ["responder", "cerrar"]`) y abre
`componentes/ResponderCaso.tsx`, no el formulario genérico: el genérico diría
«Hecho» aunque el correo no hubiera salido.

**6. Cuentas, a la vista en Ventas.** `Aplicacion.delante`
(`lib/aplicaciones.ts`): las pestañas que una aplicación pone primero, por su
camino; las demás siguen en el orden de sus áreas. Ventas declara
`/m/oportunidades`, `/m/leads` y `/m/cuentas`. No se mueve nada de área —Ventas
sigue en su tope de diez—. Medido a 1440 px: antes Cuentas era la decimotercera
y caía en «Más»; ahora la tercera tras Inicio y Puesto. La prueba
`el_rediseno_no_ha_escondido_nada` exige que lo declarado exista y salga
primero.

**7. El estado del presupuesto no ofrece lo que se rechaza.**
`crmcore.datos.estados.CAMINOS_PROPIOS` con `registrar_caminos` y
`camino_propio(objeto, origen, destino, db)`: los significados a los que se
llega con su acción. Ventas registra los suyos (`_CON_SU_CAMINO`) y su
`cambiar_estado` usa `camino_propio`; `GET /{servicio}/estados/{objeto}`
publica `con_su_camino` (estado → por qué), y `CambioDeEstado.tsx` no ofrece
esos destinos (salvo entre dos estados con el mismo significado). Desde
borrador, el presupuesto no ofrece nada en el desplegable —todos sus destinos
tienen acción— y **Enviar** está a la vista.

**Medido otra vez** (`node frontend/scripts/medir-tareas.mjs`, 10-11-2026):

| # | Tarea | Antes (clics · campos · pantallas · s · persona) | Después |
|---|---|---|---|
| T02 | Alta de un lead y convertirlo | 6 · 3 · 4 · 5,4 s · ≈29 s | 5 · 3 · 4 · 4,7 s · ≈27 s |
| T08 | Abrir un caso con prioridad | 3 + Intro · 3 · 4 · 3,7 s · ≈31 s | 5 + Intro · 3 · 4 · 3,8 s · ≈33 s |
| T09 | Responder un caso | 3 + Intro · 3 · 2 · 2,8 s · ≈30 s (sólo apuntaba) | sin medir: ver abajo |
| resto | T01, T03–T07, T10–T12 | | iguales (±0,4 s de reloj) |

La T08 cuesta un clic más: elegir en una lista son dos clics (abrir y elegir)
donde antes se tecleaba «alta»; a cambio no se puede escribir una prioridad que
no existe. La T09 del guion ahora pulsa **Responder**, escribe el destinatario
(`uxmedida@example.com`, dominio reservado) y el mensaje, y **Enviar
respuesta**; sólo cuenta como hecha si el envío consta **enviado**. No se ha
corrido contra el tenant de plataforma: manda un correo de verdad, y en esta
instalación el canal transaccional no tiene remitente ni servidor
(`GET /api/v1/correo/salida`), así que habría quedado «No ha salido» con ese
motivo. La respuesta enviada y la no enviada están probadas con el canal
sustituido.

Pruebas: `test_la_busqueda_de_una_lista_va_al_servidor.py` (encuentra lo que no
está en la primera página, palabra por palabra, `%` literal, 422 sin campos de
nombre); `test_la_prioridad_y_la_respuesta_del_caso.py` (escala de fábrica en
orden, prioridad de la empresa al abrir y en el escalado, `x-vocabulario` en el
contrato, el PATCH valida contra la empresa, responder manda y cuenta, lo que
no sale consta como no salido, sin destinatario no se llama a nadie);
`test_marketing_lo_que_sale_de_verdad.py` (la respuesta sale por lo
transaccional con la plantilla de la empresa, y sin canal consta fallida);
`test_estados_de_presupuesto_y_contrato.py` (lo publicado en `con_su_camino`
es exactamente lo que el servidor rechaza, destino a destino); en el front,
`lo_que_se_ofrece_sale_del_servidor.test.tsx` (el selector busca en el
servidor y cae a lo cargado, la lista de vocabulario, el desplegable de estado,
la tabla no refiltra), `formulario_usable.test.tsx` (`alta` delante) y
`el_rediseno_no_ha_escondido_nada.test.ts` (`delante`).

### 4.6.73 Colecciones sin puerta tras resellar el contrato: 55 → 0 (10-11-2026)

Resellado el contrato (`scripts/sellar_contrato.py --sellar`, de 2.409 a 3.020
operaciones), `tests/unit/test_una_coleccion_sin_puerta_no_la_abre_nadie.py`
vio 55 colecciones `GET` sin pantalla con `TOPE_SIN_PUERTA = 0`.

**21 eran del gate.** Sólo reconocía llamadas que empiezan por `/api/v1`, y el
front también escribe `` `${BASE}/golden/candidatas` `` (calidad del dato),
`` `${base}/clases` `` (archivo, trece servicios) y
`` `/api/v1/ajustes/versiones${q}` ``. `_constantes()` resuelve ahora, por
fichero, dos clases de constante y nada más:

- **raíz**: `const X = "/api/v1/…"` (o plantilla), y se sustituye en las
  plantillas que empiezan por `${X}`. Un nombre con dos valores en el mismo
  fichero no se resuelve.
- **consulta**: `const q = …` cuyos literales empiezan todos por `?` o `&` o
  están vacíos, y alguno no lo está. Se quita pegada al final. `?? ""` a secas
  no cuenta: es un identificador que puede venir vacío.

Validado una vez plantando los casos malos: dos valores para `base`, un
`${id}` con `?? ""`, una raíz que no es `/api/v1` y una «consulta» que añade
un tramo no se resuelven; quitar `const base` en `Archivo.tsx` vuelve a dejar
huérfanas las clases del archivo. La primera versión daba por consulta el
`enCurso = panel?.en_curso?.id ?? ""` de la evaluación de IA y abría una
colección que no abre nadie: de ahí la segunda condición.

**18 a pantalla**: `volumen/archivo/resumen` en `ArchivoDelServicio` (columna
«Ya archivado»), `accounts/sin-contacto?limite=10` y `extensiones/motor` como
`resumen` de sus pestañas, `ia/indice` y `ia/asistente/acciones` en
`Asistente.tsx` (`LoQueSabe`, `MisAcciones`) y `data-quality/contacts/duplicates`
en «¿Ya existe?» de Duplicados. `GET /extensiones/motor` devuelve además
`que_significa`, y `Medida` (`Modulo.tsx`) ya no dibuja como barras un objeto
de cifras con unidades distintas en el nombre (`_ms`, `_mb`, `_kb`, `_max`…):
los topes del motor salían como un reparto con el combustible aplastando al
resto y todos al «0 %». Van como cifras sueltas.

**16 declaradas en la lista de excepciones del gate**, cada una con su motivo: `/{servicio}/filtros` (trece; índice para
quien integra y para el asistente, `herramientas.py`), `service/buscar` (la
reparte el gateway), `opportunities/historial-etapas` (la lee
`analytics/datos_crm.py`) e `ia/evaluacion/ejecuciones` (la compone
`evaluacion.panel`).

Pruebas: el gate y `test_cada_capacidad_tiene_pantalla.py`;
`modelos_predictivos_y_asistente.test.tsx` (una propuesta pendiente se
confirma desde la lista con sus argumentos).

### Ventas recorrida en pantalla (10-11-2026): qué se arregló y dónde

Recorrido capacidad a capacidad desde el navegador. Lo que se tocó:

**Acciones que llevan el registro en el cuerpo.** `accionesDe` sólo veía las
operaciones con el registro en la ruta. `lib/acciones.ts › accionesPorElCuerpo`
ofrece las que lo llevan en el cuerpo, con `Accion.fijos` (los campos que pone
la pantalla y el formulario no pregunta; `Acciones.tsx` los quita del
formulario y los añade al cuerpo). La ficha de la oportunidad declara
`/ingresos/{reparto,rol-compra,relacionar,calendario}` y
`/planes-conjuntos{,/revision}`. El nombre y el permiso salen del contrato.

**Cuerpos tipados** (`api_ingresos.py`, `api_cotizacion.py`): `ParticipacionIn`
(usuario con `referencia`), `RolIn.rol` con `x-vocabulario` `roles_compra`,
`RelacionIn.tipo` y `destino_id` (referencia `oportunidad`), `PasoIn`,
`AcuerdoIn`, las seis preguntas de `RevisionIn` como campos, `Clausula`,
`CrearReglaPrecio.lista_id` (referencia `lista_precio`, que pasa a ser el
`objeto` del recurso) y `accion`, `sentido`, `periodicidad` y el tipo de
`CambioSuscripcionEntrada` como `Literal`. `Formulario.tsx › Lineas` pinta el
selector de registro en las columnas con referencia, y `contrato.ts` quita el
«ID» del título de esas columnas.

**Arreglos de servicio:**

- `ingresos.repartir_credito` hacía `select` donde quería `delete`: el reparto
  se acumulaba.
- `ingresos.metricas_de_ingreso`: el TCV de una línea recurrente sin
  `valor_total` es importe × periodos del contrato.
- `ActualizarOportunidad.motivo_cambio`: el servicio lo leía y el esquema lo
  tiraba. `servicio.recalcular_total` anota el cambio de importe que provocan
  las líneas (`anotar=False` para la copia de `duplicar`).
- `servicio.cambiar_etapa`: el mensaje de criterios incumplidos nombra los
  campos; la ficha pinta `fallo` también con la oportunidad cargada.
- `api._exigir_cierres(…, tenia=)`: se exige **conservar** la etapa final que
  había, no tenerla ya.
- `cadencias.cola_de_trabajo` añade `_leads_sin_responder` y
  `_oportunidades_paradas` (reutiliza `servicio.oportunidades_estancadas`).
- `cadencias.evaluar`: el umbral de «cualificada» es el ajuste
  `metodologia_minimo_cualificada_pct` (50 por defecto, editable en Admin), y
  devuelve `minimo_cualificada_pct`.
- `enrutamiento.atributo_del_lead`: completa `origen` → `lead.origen` y lo que
  no es columna → `lead.campos.<x>`. La prueba de reglas mete lo desconocido en
  `campos` y convierte a número lo numérico.
- `api.anotar_toque` llama a `origen.fijar_primer_y_ultimo`.
- `forecast.deslizamiento` devuelve el nombre; `api_forecast.ajustar` calcula
  el bruto si no llega (`calcular(...).por_categoria[categoria].importe`).
- `api_ingresos`: `GET /planes-conjuntos/revisiones` (listado de
  `RevisionOportunidad`, montado antes del de planes para que `/{id}` no se lo
  trague); `previsto_por_periodo` añade `meses` como filas.
- `presupuestos.crear` copia las líneas de la oportunidad si no llegan
  (`_lineas_de_la_oportunidad`); `comparar_versiones` incluye el descuento.
- `catalogo.calcular_precio`: en sentido `venta`, el coste sale de la tarifa de
  coste si alguna regla aplica (`coste_de_tarifa`); en sentido `coste`, la base
  es `producto.coste`. `GET`/`DELETE /listas-precio/{id}/reglas[/{regla_id}]`
  con `response_model=list` para que la ficha lo pinte como sub-colección.
- `api_cotizacion`: la ruta de cambios de suscripción decía
  `{suscripcion_cliente_id}` y la función `suscripcion_id` → 422 siempre.
  `presupuestos._prorrateo` usa los días reales del periodo
  (`MESES_PERIODO`), `_fin_de_periodo` suma meses de calendario y la baja
  prorratea con la `proxima_factura` de antes de borrarla.

**Pantallas:** `Oportunidad.tsx` (nombres en *Quién decide* y *Quién se lo
lleva*, enlace a la relacionada, `CategoriaDePrevision`, días en etapa,
`LasRevisiones`, formato de *Lo que se ha movido*), `PeriodoDePrevision.tsx`
(menú de acciones del periodo con `accionesDe`, selector de moneda desde
`/monedas/cambios`, nombres de categoría, importes formateados),
`Presupuesto.tsx` (qué cambió por línea, costes con céntimos),
`Embudos.tsx` (la tabla de etapas cabe a 1440 px), `lib/formato.ts ›
importeUnitario`, `recursos.ts` (columnas de *Mi cola*, `clave_lista` de
*Ingreso previsto*).

Pruebas (sólo de lo arreglado): `test_ingresos_y_equipo.py`
(TCV, reparto que reemplaza), `test_forecast.py` (motivo por la API, importe de
las líneas, nombre en el deslizamiento, bruto calculado),
`test_editor_de_embudos.py`, `test_cadencias.py` (cola),
`test_enrutamiento_leads.py`, `test_origen_leads.py`, `test_cotizacion.py`
(oferta desde oportunidad, descuento en la comparación, tarifa de coste,
reglas de la lista, baja prorrateada) y `test_ventas_por_http.py` (cambio de
suscripción por HTTP).

**Lo que quedó sin poder comprobar en local:** la previsión en otra moneda
(`CRM-03.02.01.07`) no convierte porque la réplica de `tipos_cambio` de `sales`
está vacía —los 25 eventos `catalogos.tipo_cambio_fijado` se publicaron el
04-11 y el consumidor `sales-fx` no tiene ninguno— y no hay pantalla que fije
un tipo para volver a emitirlo.


### Recorrido de marketing en el navegador (10-11-2026)

Recorridas en pantalla las capacidades `svc: marketing` hechas sin `visto`.
Lo que fallaba y cómo quedó:

- **La proyección de marketing estaba vacía de datos** (`proyeccion.py`). Los
  eventos de alta sólo traen el nombre y no hay evento de modificación: 0
  perfiles con estado, empleados, sector o cargo, y todos los segmentos a cero.
  Nuevo `resincronizar(tenant_id, principal)` con `ORIGENES` (ruta pública y
  qué columna del origen alimenta cada campo del perfil), por
  `crmcore.http.interno.invocar` como máquina —sin el filtro de compartición—
  con los permisos y roles de quien lo pide; tamaño de página en
  `Settings.marketing_resincronizar_pagina`. Un objeto leído a medias no se
  toca; los campos de `campos_tapados`/`campos_no_entregados` no se copian; alta
  y última actividad salen del origen. Rutas: `GET /segmentos/perfiles` (de
  cuándo es el dato) y `POST /segmentos/perfiles/sincronizar` (`segment:write`).
- **Constructor de segmentos** (`componentes/ConstructorDeSegmento.tsx`,
  enganchado en `Formulario.tsx` cuando el recurso es `segmento`: `definicion`
  y `excluye`). `GET /segmentos/atributos?objeto=` (sólo lo que `columnas_de`
  traduce y algo rellena: `ORIGENES[objeto]` + dueño, alta, última actividad,
  cuenta y campos propios) y `POST /segmentos/estimar` (`seg.estimar`, mismo
  `_consulta_para` y `filtrar_suprimidos` que el segmento guardado). `objeto`
  pasa a `Literal` (desplegable). `Segmento.tsx` leía `campo` en vez de
  `atributo` y los porcentajes salían con punto.
- **Acciones de fila con `DELETE`** (`Acciones.tsx`): tiraban siempre el cuerpo;
  «Levantar una supresión» exige motivo y daba 422. Ahora un `DELETE` con
  campos los manda.
- **Recorridos** (`recorridos.py`): `entrar_por_segmento` (al publicar y en
  `avanzar_solos`; `tenants_con_recorridos_pendientes` incluye los tenants con
  recorridos por segmento publicados), `entrar_por_evento` (desde
  `proyeccion.consumir`, en la misma unidad de trabajo que el perfil para los
  eventos de `EVENTOS`), y salida `otro_recorrido` al entrar en uno que otro
  declara en `excluye_si_en`. `ficha()` devuelve `evento_entrada` y
  `segmento_id`. Pantalla: el alta pide entrada, segmento o evento (los del
  catálogo con `contacto_id` o `lead_id`), «Sale en cuanto compra» y «Cede el
  paso a», y la ficha pinta `GET /recorridos/{id}/embudo`.
- **Puntuación** (`puntuacion._grado` acepta `grado` o `clave`;
  `PuntuacionDeLead.tsx` igual): panel `componentes/PuntuacionDelLead.tsx` en
  la ficha del lead. `lead.qualified` pasa a productor `marketing` con sus
  campos reales (`events/dominio.py`, Anexo B del catálogo) y `sales` lo consume
  (`consumidores.consumir_cualificacion`, cola `sales-cualificacion`): guarda
  `puntuacion` y lleva a «cualificado» al llegar a SQL si la máquina de estados
  lo deja. La siembra (`scripts/sembrar_configuracion.py`) usaba atributos que
  no existen en el ámbito (`sector`, `evento`, `paginas`) y tramos con `clave`;
  ahora `lead.<dato>` y `grado`, y «Clientes activos» filtra `estado = activa`.

Pruebas (sólo de lo arreglado): `test_segmentos_y_scoring.py` (la estimación
cuenta igual que el guardado, el constructor no ofrece lo que nadie rellena, la
puesta al día no copia lo tapado), `test_recorridos.py` (entrada por segmento
sin repetir, por evento, salida por el prioritario),
`test_la_calificacion_de_marketing_llega_a_ventas.py` y, en el front,
`un_segmento_se_puede_lanzar.test.tsx` (el doble usaba `campo`).

**Lo que quedó sin poder comprobar en local:** envíos reales (correo, SMS,
postal, telemarketing), la sincronización con plataformas de anuncios sin un
doble, y la puntuación con un modelo correcto: el modelo activo del tenant
(`b2b_automocion` v6) se sembró con los atributos rotos y no se puede borrar una
versión; hace falta publicar una nueva desde «Puntuación → Nuevo».

### Servicio recorrido en pantalla (10-11-2026): qué se arregló y dónde

**Acciones del contrato en las fichas propias.** `Articulo.tsx`, `Activo.tsx` y
`OrdenDeTrabajo.tsx` no pintaban las acciones: ahora usan `accionesDe` sobre
`/api/v1/conocimiento`, `/api/v1/activos` y `/api/v1/ordenes-trabajo` igual que
`Caso.tsx`. `Acciones.tsx` acepta `recurso` y lo pasa a `Formulario` como
`propio`, así `original_id`/`maestro_id` de una acción salen como buscador
(`Caso`, `Ficha` y `Modulo` lo pasan).

**Contrato en el front** (`lib/contrato.ts`): `resolver` conserva `referencia` y
`enum` de un campo opcional (`anyOf`), y `fichaDe` ignora la consulta de
`listar`; `Edicion.tsx` y `Ficha.tsx` también. **Tablas** (`Tabla.tsx`): una
columna de persona sale con su nombre (`usePersonas`) y una `*_id` con pantalla
con el nombre del registro (`nombres.ts › nombreEnLote`, una llamada por tipo);
los identificadores declarados en `columnas` del recurso se ven de entrada
(prop `declaradas`). Recursos nuevos: *Agentes*, *Reglas de reparto*,
*Comunidad por moderar*.

**Servicio de casos** (`services/service`):
- `servicio.abrir_caso` llama a `operacion.asignar` si no viene dueño ni cola.
- Vocabulario `motivos_cierre_caso` (`servicio.py`), exigido en `POST
  /casos/{id}/cerrar` y `/cerrar-masiva` (`exigir_motivo_de_cierre`); no en el
  cierre por cambio de estado, donde el motivo es el comentario de la transición.
- `arbol_de_caso` devuelve `maestro`, `duplicados` y `asuntos`.
- `portal.validar_cierre` + `POST /portal/mi/casos/{id}/validar-cierre`;
  `mis_casos` devuelve `validacion_cliente` y la resolución mientras está pendiente.
- `GET/DELETE /colas/reglas` (declarados ANTES de `/colas/{clave}`), `GET /agentes`,
  `POST /agentes` (capacidad canal a canal), `DELETE /agentes/{usuario_id}`.
  La consola devuelve `presencia_desde` y `configurado`.
- Tarea `service.escalado` en `main._tareas` (`tarea_escalado_intervalo_s`, 300 s).
  **Ojo al desplegar**: la primera pasada aplica las reglas a todo lo abierto que
  nunca se escaló; en el tenant de demostración fueron 1.552 eventos.
- `_calendario` cae al calendario por defecto si la clave no existe;
  `exigir_calendario` al publicar un SLA. La ficha recibe `sla.pausado_desde`.
- `en_riesgo` ordena lo salvable primero; `cumplimiento_desglosado` añade `cuenta_id`.
- Problemas: `GET/POST /problemas/{id}/casos` (lista con `response_model`, para que
  sea sub-colección), `caso_maestro_id` con `referencia: caso`, severidad con `enum`;
  `DELETE …/casos/{caso_id}` admite quitar sin motivo y lo deja escrito.
- Conocimiento: `esta_publicado`/`publicado_sql` (en revisión con versión
  publicada sigue a la vista) en `leer`, `buscar`, eficacia y portal; `leer`
  devuelve `version_publicada` y `a_la_vista`; `Publicar.audiencia` con `enum`.
- Comunidad: `abrir_hilo_portal` llamaba a `abrir_hilo` sin el acceso (500); `hilos`
  devuelve `id`.
- Campo y postventa: `CrearGarantia.cobertura` obligatoria y `Literal`,
  `Linea.tipo` `Literal`, `Resolver.tipo`/`a_cargo_de` con `enum`, suspensión de
  expediente con `MotivoDeSuspension` (`enum` de `MOTIVOS_SUSPENSION`).

**Tenancy**: `api_catalogos` llama a `crmcore.datos.calendario.propagar` al crear
un calendario y al añadir un festivo, y `POST /calendarios/{id}/propagar` lo
reenvía. Sin esto la copia de `service` estaba vacía.

**Front**: `Caso.tsx` (relaciones con nombre, árbol en dos sentidos, panel de
derecho que leía un campo inexistente, reloj parado, último cierre),
`Consola.agente.tsx` (Mi presencia), `Conversacion.tsx` (macro), `Portal.tsx`
(validar cierre, preguntar en la comunidad), `Conocimiento.tsx` (título enlaza),
`Activo.tsx` (historial leía `cuando` y la API manda `ocurrido_at`).

Pruebas: `test_casos_y_sla.py`, `test_conocimiento_y_portal.py` y
`test_comparticion_y_catalogos.py`, las que citan `crm_04_…` del 10-11-2026.

### Borrar un contacto con señales, y buscar contactos por apellido o correo (10-11-2026)

**Señales de identidad.** Todo contacto con correo o teléfono daba 409
(`integridad.referenciado`, «1 en senales_identidad»): las señales se anotan
solas al guardar y `integridad.quien_depende` las contaba como dependencia.
Ahora `Senal.contacto_id` lleva `info={"parte_de": True}` —la marca de
composición sin clave ajena de `integridad._es_composicion`— y la tabla tiene
`deleted_at` (migración `alembic/versions/party/20261110_1800_senales_siguen_a_su_contacto.py`,
`7c3a9e51d2b4`, que además deja inactivas las de contactos que ya estaban en la
papelera). `identidad._al_guardar` (el `before_flush` que ya las anotaba) hace
que sigan a su contacto por cualquier vía —ficha, borrado masivo, restaurar,
purgar—: si cambia `deleted_at` del contacto, copia el valor a sus señales con
un `UPDATE` (a la papelera, inactivas: el guard de borrados las esconde de
`resolver`, `proponer_uniones` e `identidades_de`; restaurado, vuelven con sus
`veces`); si el contacto se purga (`session.deleted`), se borran. `observar` y
`_anotar` buscan la existente con `con_borrados` para no chocar con
`uq_senal_identidad`. Lo ya unido no se toca: `uniones_identidad` no apunta por
`contacto_id`, y `resolver` deja de llevar un secundario a un principal que
está en la papelera —el secundario cuenta por sí mismo, y vuelve a sumar en el
principal si se restaura—.

**Búsqueda de contactos.** `GET /contacts?buscar=` buscaba sólo en
`clave_canonica`, que guarda las palabras ordenadas: «ZZ Contacto» no
encontraba a «ZZ Contacto» y el correo no encontraba a nadie. Ahora llama a
`crmcore.http.listados.aplicar_busqueda`, el mismo `_buscar_texto` del
`?buscar=` común (por palabras, sólo campos en claro) para un listado escrito a
mano que declara `buscar`; `Contacto.__busqueda__` = nombre, apellidos,
`clave_canonica` (sin tildes) y correo. Lo usan el panel «Meter a alguien» de
los recorridos y el selector de contactos.

Pruebas: `tests/unit/test_calidad_del_dato_real.py`
(`test_las_senales_siguen_a_su_contacto_a_la_papelera_y_de_vuelta`, que con la
marca quitada da el 409, y `test_la_busqueda_de_contactos_mira_nombre_apellidos_y_correo`).

## 5. Operación

### 5.1 Copias y restauración

- Copia lógica por tenant y copia física del clúster; las dos hacen falta.
- **Restauración probada**: hay un procedimiento para restaurar un tenant sin
  tocar a los demás, y una copia que nadie ha restaurado nunca no es una copia.
- Exportación de salida completa del tenant (datos, configuración, adjuntos e
  histórico), que es lo que hace reversible la decisión de contratar.

### 5.2 Migraciones

Una cadena por servicio en `alembic/versions/<servicio>/`. Reglas:

- **Ningún modelo cambiado se queda sin migración**: hay un gate que lo comprueba
  aplicando todo desde cero contra un Postgres efímero.
- Las migraciones **no borran datos sin decirlo**, y el `downgrade` dice la verdad:
  si no se puede revertir sin pérdida, lo pone en vez de dejar un `pass`.
- Después de migrar, **siempre** `aplicar_rls.py`: una tabla nueva nace sin
  política y una tabla con `tenant_id` sin política es un agujero que no da
  síntomas.

### 5.3 Observabilidad

- **Logs estructurados** con `trace_id` y `tenant_id` en todas las líneas.
- **Métricas** por endpoint y por tenant, con histogramas de latencia.
- **Trazas** distribuidas (OpenTelemetry, extra opcional).
- **SLO y presupuesto de error**: cuánto margen queda antes de incumplir lo
  prometido. Sin tráfico se responde «no medible» en vez de 100 %.
- **Página de estado** por tenant, compuesta por el gateway a partir de lo que
  publica cada servicio. Un servicio que no contesta **no cuenta como verde**.
- **Latencia p95/p99 por tipo de operación y por empresa** (`CRM-08.01.01.01`).
  `TiemposMiddleware` clasifica cada petición con `slo.operacion_de(método,
  plantilla de ruta)` según `SLO_OPERACIONES_REGLAS` (lista ordenada de
  `{operacion, metodos, rutas}`; gana la primera, lo demás es «otra») y suma
  uno al cubo de `SLO_LATENCIA_CUBOS_MS` en Redis
  (`slo_op:<servicio>:<tenant>:<AAAA-MM>`, campo `<operacion>|<cubo>`, 62 días
  de vida; sin Redis, en memoria del proceso y se dice). `GET
  /<servicio>/estado/slo` devuelve `operaciones` con p95/p99 interpolados por
  cubo, su objetivo (`slo_objetivos_operacion`, ajuste en caliente por tier y
  por tenant) y los `cubos`; el gateway (`GET /estado/slo`) **suma cubos** de
  los servicios con los mismos límites y recalcula —nunca promedia
  percentiles—, tomando los objetivos de `tenancy` primero. Con
  `X-CRM-Tenant-Mirado`, de la empresa mirada. Por debajo de
  `SLO_MUESTRAS_MINIMAS` se marca `pocas_muestras`.
- **Un solo `X-Request-Id` de punta a punta** (`CRM-00.02.04.07`). El gateway
  manda el suyo al servicio (antes el servicio generaba otro y el navegador
  recibía dos) y no copia el del servicio a la respuesta. El front lo lee del
  cuerpo del problema o de la cabecera (`ErrorApi.requestId`) y la pantalla de
  error lo enseña con «Copiar». El audit trail de cada servicio se consulta
  en `GET /<servicio>/cumplimiento/auditoria?request_id=…` (permiso
  `tenant:read`, empresa mirada) y el de `tenancy` en `GET
  /grc/auditoria?request_id=…`. No hay índice por `request_id`: la consulta va
  acotada por tenant y con límite.

#### MFA por rol y «entrar como» de soporte

- **`mfa_obligatoria_roles`** (`MFA_OBLIGATORIA_ROLES`, JSON; ajuste sensible por
  tenant). `servicio.mfa_exigida(db, roles, tenant_id)`: el interruptor
  `mfa_obligatoria` suma, los roles añaden. Se lee con el tenant puesto en el
  contexto (`con_contexto`), porque en el login todavía no lo hay. Se escribe
  con `PUT /factores/obligatoria-por-rol` en **identidad** (`tenant:write`), que
  valida los roles contra los de serie, los del tenant y los que llevan las
  membresías (`mfa.rol_desconocido`) y devuelve el panel de adopción con
  `exigida_sin_factor`. Se replica a los demás servicios por el bus como
  cualquier ajuste.
- **Suplantación desde el navegador.** Gateway: `POST /sesion/suplantar` reenvía
  a `POST /sesiones/suplantar` de identidad con `Authorization: Bearer <cookie
  propia>` y `X-CRM-Tenant-Mirado`; pone la de soporte en la cookie de acceso y
  su refresco en `<cookie>_suplantacion_refresco` (ruta de renovar). El refresco
  propio no se toca. `POST /sesion/renovar` renueva primero la de soporte; si
  ya no se puede, borra su cookie, renueva la propia y devuelve
  `suplantacion_terminada: true`. `POST /sesion/volver` cierra la de soporte en
  identidad (sólo si `/auth/me` dice que lo es; si no, 409
  `gateway.sin_suplantacion`) y el front llama después a `/sesion/renovar`.
  Identidad exige membresía activa del objetivo en la empresa
  (`auth.suplantacion_sin_membresia`) y `/auth/me` devuelve
  `suplantado_por_email`, `motivo_suplantacion` y `suplantacion_caduca_at`.
- **Alta del tenant en cascada.** `POST /suite/provisionar/tenant?aplicar=true`
  encola y empuja **sólo** las filas `objeto=tenant` del propio tenant
  (`suite_conector.aplicar_alta_tenant`); `GET /suite/provisionar/tenant` da el
  estado por herramienta, con `sin_alta` para las que nunca se pidieron.

#### Segundo factor por proveedor (CRM-00.05.01.22)

- **Módulo** `services/identity/mfa_proveedor.py`; rutas en
  `api_mfa_proveedor.py` bajo `/api/v1/mfa-proveedor` (prefijo en
  `crmcore/rutas_de_api.py` → identidad). Tablas `perfiles_mfa_proveedor` y
  `vinculos_mfa_proveedor` (migración
  `alembic/versions/identity/20261109_1500_segundo_factor_por_proveedor.py`).
- **Plantillas** en `services/identity/plantillas_mfa_proveedor.json`: Twilio
  Verify, Okta Verify, Duo y RSA SecurID. Son datos con la forma del perfil;
  no hay código de ningún proveedor. Marcas: `{{codigo}}`, `{{email}}`,
  `{{usuario}}` (antes de la arroba), `{{id_peticion}}`, `{{var.X}}`
  (variables del perfil), `{{persona.X}}` (vínculo de la persona) y
  `{{secreto}}` **sólo** en la autenticación (`ninguna`, `basica`, `bearer`,
  `cabecera`). `validar` rechaza al guardar una marca sin origen
  (`mfa_proveedor.marca_desconocida`), el secreto fuera de la autenticación y
  un perfil que no manda el código.
- **Secreto** cifrado con `cifrar(..., proposito="idp")`; la API devuelve
  `tiene_secreto` y nunca el valor. «Probar» devuelve la petición con secreto y
  código tapados.
- **Llamada** por `crmcore.red.cliente_seguro` (guard de SSRF; un host interno
  necesita `url_guard_hosts_permitidos`) con `http_externo_timeout_s`. Lee la
  respuesta por ruta con puntos (`respuesta.campo`) contra `respuesta.validos`;
  sin campo, vale un 2xx. Una marca sin valor (p. ej. la persona sin teléfono)
  **no llama**.
- **Login** (`servicio.autenticar` y `_verificar_segundo_factor`): TOTP propio →
  perfil activo del tenant → OTP → recuperación. Con un perfil activo y la
  persona vinculada (`mfa_proveedor.aplica_a`), a quien no tiene TOTP propio ya
  no se le corta con `auth.mfa_no_configurada`, y la MFA adaptativa también le
  pide el código. Si el proveedor no contesta, no se entra (`auth.mfa_invalida`).
  Cada verificación queda en auditoría (`mfa_proveedor.verificado` /
  `.rechazado`). Uno activo por empresa (`mfa_proveedor.ya_hay_uno_activo`).
- **Límite conocido**: la Auth API de Duo firma cada petición con HMAC; el
  transporte genérico manda la credencial tal cual, así que contra Duo directo
  hace falta una pasarela de firma delante (lo dice la nota de la plantilla).
- Pruebas: `tests/unit/test_segundo_factor_por_proveedor.py` (doble HTTP real en
  127.0.0.1) y `frontend/src/pruebas/segundo_factor_por_proveedor.test.tsx`.

### 5.4 Cuando algo va mal

Los [runbooks](runbooks/index.md) cubren los casos que saltan de verdad: servicio
caído, errores de servidor, latencia alta, tabla de salida atascada, eventos
fallando y tenant cerca de su cuota. Cada uno dice qué mirar primero y qué **no**
hacer.

Tres cosas que conviene saber antes de que pasen:

1. **La tabla de salida (outbox) atascada** no se arregla borrando filas: se mira
   por qué el publicador no avanza. Borrar pierde eventos que nadie va a echar de
   menos hasta que cuadren cifras.
2. **Un tenant que consume de más** se acota solo por las cuotas y el rate limit;
   si aun así afecta a los demás, hay mamparas por recurso.
3. **La degradación es controlada**: bajo presión se posponen recálculos e informes
   pesados antes que las escrituras de usuario.

### 5.5 El preflight

No hay CI, y eso es deliberado. En su lugar hay **dieciocho gates locales** que
corren en paralelo —hasta seis a la vez— salvo los dos
que levantan un Postgres embebido, que se turnan:

```bash
python scripts/preflight.py          # rápido
python scripts/preflight.py --todo   # todo, incluida la suite y los docs
```

Comprueban, entre otras cosas: estilo y formato, que el `.env.example` refleja los
Settings reales, que la matriz de trazabilidad está regenerada, que ningún servicio
lee el esquema de otro, que toda ruta publicada es alcanzable por el gateway, que
nada declarado «hecho» carece de cita en el código y en el manual, y que las
migraciones están al día.

**Si el preflight engorda, lo que se arregla es el gate lento — nunca se quita la
comprobación.** Un preflight que no se corre no garantiza nada, y el coste se paga
igual.

Lo que decide el rojo es el **tiempo de CPU**, no el reloj. La razón está medida:
el mismo gate de aislamiento tardó 59 s y 382 s en la misma hora, con el mismo
trabajo, porque en esa máquina estaban corriendo a la vez las pruebas de otros dos
repositorios y el indexador del sistema. Fallar ahí es fallar por el vecino, y un
rojo que no depende de lo que uno ha hecho se aprende a ignorar — que es cómo se
pierde el guardián entero. El reloj se sigue enseñando, porque es lo que uno
espera sentado; cuando se dispara sin que suba el CPU, el informe lo dice con la
carga de la máquina al lado.

Y un aviso para quien monte un entorno de pruebas: **el Postgres embebido deja su
directorio de datos al terminar**. Aquí se midió el efecto el 05-10-2026 —908
directorios y 24 GB acumulados en diez días, con Spotlight indexándolos— y por eso
la suite borra el suyo al acabar y barre los huérfanos de más de una hora al
arrancar. Si copias este esquema a otro repositorio, cópialo entero: un recolector
que solo mira los procesos vivos no ve el directorio cuyo servidor murió bien.

### 5.6 Rendimiento

- Índices de expresión para los campos personalizados que se usan al filtrar,
  creados y retirados solos.
- Particionado y archivado para los objetos de alto volumen.
- Volumetría declarada: cuántos registros por objeto, cuántos usuarios concurrentes
  y cuántos eventos por segundo se sostienen — medido, no prometido.

#### Volumen y archivo frío, en la práctica

Cada servicio publica `/<servicio>/volumen/*`, y **nada de eso escribe en la
base**: devuelve el plan, y quien ejecuta el corte es la migración del servicio,
con su revisión y su ventana. Una ruta que particionara en caliente bloquearía la
tabla durante la petición de un usuario.

Lo que se pregunta ahí, y por qué:

- **Qué tabla va camino de dar problemas.** No por tamaño: por **ritmo**. Una de
  cien millones de filas estable no molesta; una de diez que dobla cada trimestre
  es un incidente dentro de nueve meses — y esos nueve meses son el tiempo que
  hace falta para arreglarlo con calma. Sin datos de volumen **no dice que todo
  esté bien**: dice que no se puede anticipar nada.
- **Si ya falta la partición de este mes**, que no es un aviso sino un incidente
  ocurriendo. Las particiones se crean **por delante**: crearlas cuando llega la
  primera fila del mes es crearlas a las 00:00 del día 1, dentro de la transacción
  de un usuario y con un bloqueo de tabla.
- **Qué se puede mover a frío y qué lo impide.** Lo que está bajo obligación
  legal, en litigio, con una solicitud de acceso pendiente o en una investigación
  **no se toca**: moverlo sería cumplir el plazo de retención por accidente y
  romper otra obligación a la vez.
- **Si estas filas se pueden borrar de la tabla viva.** Mover a frío sin borrar no
  quita volumen; el borrado es el paso que no tiene vuelta atrás, y se comprueba
  antes y aparte.

Y una regla operativa que conviene conocer: **las purgas que no distinguen por
registro se abstienen enteras mientras haya un bloqueo legal activo** — la del
rastro de auditoría y la de los bytes de adjuntos. Conservar de más cuesta disco;
borrar la prueba equivocada no tiene arreglo.

#### La caché de respuestas

La invalidación va **por evento, no por tiempo**. Cada servicio sube la generación
del evento que recibe, y lo que dependía de él deja de encontrarse sin tocar
ninguna entrada. Importa porque una caché que solo caduca sirve una respuesta
vieja todo el plazo que le quede, y el usuario que acaba de cambiar algo ve su
propio cambio desaparecer: la queja más difícil de reproducir que existe, porque a
los cinco minutos ya no pasa.

Las políticas que **solo** caducan por tiempo se pueden listar, y conviene
mirarlas: una que se creyó invalidada por evento y no lo está es la que sirve
datos viejos sin que nadie lo sepa.

## Apéndices

### A. Comandos que se usan de verdad

```bash
python scripts/preflight.py --todo         # antes de empujar nada
python scripts/migrar.py --todos           # aplicar migraciones
python scripts/aplicar_rls.py --todos      # después de migrar, siempre
python scripts/migraciones_locales.py comprobar   # ¿falta alguna migración?
python scripts/gen_env_example.py          # regenerar .env.example
python scripts/gen_catalogo_md.py          # regenerar la matriz del catálogo
python scripts/gen_hoja_estado.py          # regenerar la hoja de estado
python scripts/sembrar_demo.py             # datos de ejemplo
python scripts/respaldar.py                # copia lógica por tenant
python scripts/verificar_cifrado.py        # comprobar que lo sensible está cifrado
```

### B. Dónde está cada cosa

| Quiero… | Está en |
| --- | --- |
| Entender una decisión de arquitectura | [Manual V — Arquitectura](manual-5-arquitectura.md) |
| Ver todos los ajustes | [Manual VI — Referencia de ajustes](manual-6-referencia-ajustes.md) |
| Saber qué está hecho y qué no | [Estado del catálogo](catalogo/estado.md) |
| Resolver una alerta | [Runbooks](runbooks/index.md) |
| Saber qué se reutiliza de otras soluciones | [Reutilización](REUTILIZACION.md) |
| Usar el CRM | [Manual de usuario](manual-usuario.md) |

### C. Lo que este producto decide no hacer

Conviene saberlo antes de proponerlo:

- **No hay CI.** Se sustituye por gates locales que corren en el preflight. Es una
  decisión del proyecto, no un olvido.
- **No hay conectores por proveedor.** Todo es configuración sobre el transporte
  declarativo.
- **No se reimplementa lo que ya existe en la casa.** Lo que hace contecintelligence
  se delega en contecintelligence.
- **Y no se toca el esquema de otro servicio**, ni siquiera para una consulta
  rápida de solo lectura. Esa consulta rápida es la que impide desplegarlos por
  separado seis meses después.
