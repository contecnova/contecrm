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

Paleta, tipografía (**DM Sans** y Geist Mono), radios y sombras: adoptados
enteros desde `contecflow-PSA/frontend/src/index.css`, no «inspirados en». Quien
usa dos productos de la casa no debe notar que cambia de uno a otro, y dos
paletas parecidas se separan a la tercera pantalla que alguien añade.

En claro siguen los de contecmind: contecflow no tiene tema claro, así que no
hay nada que copiar, y quitarlo dejaría sin producto a quien trabaja con luz.

Dos cosas que no se copiaron a ciegas:

- **Los `-text`.** El token base es el relleno; la variante de texto es el mismo
  color subido en luminosidad hasta 4.6:1 contra `paper-lighter` (#1e2d45), que
  es la superficie más clara y por tanto el peor caso. Con los valores de
  contecflow tal cual, el texto tenue daba 3.90:1 y el acento 4.32:1 — los dos
  por debajo. Suben a #8696b2 y #5994f7.
- **Las sombras.** Una sombra es la ausencia de luz sobre una superficie, así
  que no puede ser un valor único para toda la app: las de Material son gris
  translúcido pensado para blanco y en oscuro no se ven —una tarjeta elevada
  queda tan plana como el fondo—, y las de contecflow son negro a opacidad
  0.4-0.7 y sobre blanco son un manchón. Así que `--shadow-1..5` y
  `--shadow-accent` se declaran **dos veces**, Material en `:root` y contecflow
  en `.dark`, y `tailwind.config.js` solo los referencia. contecflow tiene tres
  niveles y aquí hacen falta cinco —hay modales sobre paneles sobre tarjetas—,
  así que se continúa su progresión.

#### La pantalla de entrada es la de contecflow, exacta

Es la **única** pantalla del CRM que se sale del sistema de diseño, y se sale a
propósito: se ve antes de entrar, no tiene marco alrededor y es la que comparten
las dos soluciones de la casa. Por eso sus valores van escritos —la tipografía
DM Sans, `#080c14` de fondo, la tarjeta de 400 px con radio 20, los campos de 44
de alto— y no traducidos a los tokens de este producto, que son otros y darían
otra pantalla.

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
siempre.

### 4.4 Eventos

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

### 4.5 Conectores

Un conector es **configuración, no código**: endpoints, mapeo de campos,
paginación, marcadores de vacío, OAuth2 con token cacheado. Sobre ese mismo
transporte van las suites de productividad (correo, calendario, contactos, tareas,
notas, ficheros, reuniones), la telefonía, la firma electrónica y las plataformas
publicitarias.

Escribir un módulo por proveedor convierte cada implantación en una versión del
producto; por eso no hay ninguno.

### 4.6 CDC hacia el lago del cliente

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

No hay CI, y eso es deliberado. En su lugar hay **catorce gates locales** que
corren en menos de tres minutos:

```bash
python scripts/preflight.py          # rápido
python scripts/preflight.py --todo   # todo, incluida la suite y los docs
```

Comprueban, entre otras cosas: estilo y formato, que el `.env.example` refleja los
Settings reales, que la matriz de trazabilidad está regenerada, que ningún servicio
lee el esquema de otro, que toda ruta publicada es alcanzable por el gateway, que
nada declarado «hecho» carece de cita en el código y en el manual, y que las
migraciones están al día.

**Si el preflight tarda más de tres minutos, lo que se arregla es el gate lento —
nunca se quita la comprobación.** Un preflight que no se corre no garantiza nada,
y el coste se paga igual.

### 5.6 Rendimiento

- Índices de expresión para los campos personalizados que se usan al filtrar,
  creados y retirados solos.
- Particionado y archivado para los objetos de alto volumen.
- Volumetría declarada: cuántos registros por objeto, cuántos usuarios concurrentes
  y cuántos eventos por segundo se sostienen — medido, no prometido.

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
