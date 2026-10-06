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
un 14 % más grande que la misma frase en contecflow. Los tamaños de Tailwind
—10/11/12/14/16/18/20/24/36/48— ya coincidían uno a uno con su escala; solo
faltaban dos escalones suyos que Tailwind no tiene, 12.5px para los enlaces del
menú y 22px para los títulos de pantalla.

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

#### La pantalla de entrada es la de contecflow, exacta

Es la **única** pantalla del CRM que se sale del sistema de diseño, y se sale a
propósito: se ve antes de entrar, no tiene marco alrededor y es la que comparten
las dos soluciones de la casa. Por eso sus valores van escritos —`#080c14` de
fondo, la tarjeta de 400 px con radio 20, los campos de 44 de alto— y no
traducidos a los tokens de este producto, que son otros y darían otra pantalla.

Su tipografía **ya no es la de contecflow**: al adoptar el sistema de diseño de
contecmind dejó de cargarse DM Sans, y una fuente que se nombra y no está no es
«exacta», es la del sistema. Queda pendiente decidir si esta pantalla entera
pasa también a contecmind: hoy el CRM se ve como contecmind y su puerta como
contecflow, que es justo la incoherencia que el cambio venía a quitar.

Un detalle donde se separa a propósito: el nombre del producto es un `h1` y no
un `span`. Se ve igual, y quien navega con lector de pantalla necesita que la
página tenga un encabezado; hay un gate que lo comprueba.

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

El árbol de navegación está en `lib/navegacion.ts` y lo leen las tres: una sola
lista, porque tres que tienen que coincidir acaban no coincidiendo y la que se
queda corta es siempre la del buscador.

Toda pantalla pone su título con `CabeceraPagina`, que es la que pinta el `<h1>`.
Hay gate que lo comprueba —y que comprueba que ninguna pantalla ponga dos.

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
funciona, no para enseñarlo. Sin volumen no se ve nada de lo que hace un CRM —ni
un embudo, ni una previsión, ni una cola de casos, ni un aviso de vencimiento—,
y para eso está `sembrar_empresa.py`:

```bash
python scripts/sembrar_empresa.py --slug acme --nombre "Acme, S.A." \
    --email direccion@acme.example --contrasena "…" --escala 60
```

`--escala` es el número de cuentas; el resto de volúmenes se derivan de él, con
un reparto que imita el de una empresa real: tres contactos por cuenta, cuatro
actividades, dos oportunidades y dos casos y medio. Los datos se componen de
piezas y se combinan con un generador **sembrado a partir del slug**, así que la
misma empresa da siempre los mismos datos y dos empresas dan datos distintos.

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
```

Además de la plantilla de usuarios con roles distintos, siembra unidades de
negocio, un pipeline de siete etapas con una de cada cuatro oportunidades ya
cerrada —sin histórico no hay tasa de conversión ni ciclo medio de venta—, una
taxonomía de casos de dos niveles, un SLA por tier de cliente y una cola de casos
donde **uno de cada siete incumple el plazo**: una cola sin incumplimientos no
enseña para qué sirve el SLA.

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

- **Al calcular**: recibe `hoy: date | None = None` y no llames a `date.today()`.
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
| `POST /api/v1/sagas/migracion/simular` | `proceso:read` | Qué pasa con lo que está en vuelo al publicar otra versión |
| `POST /api/v1/sagas/plantillas/clonar` | `proceso:write` | Copiar una plantilla de flujo por sector |

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
- **La migración no migra**: simula. Las instancias en vuelo terminan con SU
  versión de proceso, siempre. `se_pueden_migrar_todas: false` significa que hay
  instancias paradas en un paso que la versión nueva no tiene, y esas hay que
  decidirlas una a una.
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

### 4.7 CDC hacia el lago del cliente

Se manda **el hecho, no la foto**: qué cambió y de qué a qué, con secuencia para
que el receptor sepa si le falta algo. Los datos personales no salen por defecto y
lo que sale va marcado. El borrado viaja como borrado. Y la marca de progreso solo
avanza sobre lo confirmado.

---

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

---

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
