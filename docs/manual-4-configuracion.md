# Manual IV — Configuración y operación

Para quien despliega, configura y mantiene la instalación.

## Dónde vive la configuración

Hay **dos niveles**, y la diferencia importa:

| | Variables de entorno | Ajustes en caliente |
|---|---|---|
| **Dónde** | `.env` o el entorno del proceso | Consola de administración |
| **Cuándo aplica** | Al arrancar | Al instante, sin reiniciar |
| **Alcance** | Todo el despliegue | Por tenant, unidad de negocio o usuario |
| **Cuántos** | 122 | 32 (un subconjunto) |
| **Referencia** | [Manual VI](manual-6-referencia-ajustes.md) | Manual VI, columna «clave en caliente» |

La lista completa, con el rango y la explicación de cada uno, está generada
desde el propio código en el [Manual VI](manual-6-referencia-ajustes.md). Aquí
va solo lo que hay que decidir **antes** de arrancar.

> **Cero valores a fuego.** Ningún umbral, tope ni plazo está escrito en el
> código: todos son ajustes con rango y con un comentario que explica de dónde
> sale su valor por defecto. Hay un gate que lo comprueba.

## Lo imprescindible antes de producción

`ENV=prod` activa una verificación de arranque que **se niega a levantar** el
servicio si encuentra un secreto de ejemplo. Lista los problemas todos juntos, no
de uno en uno: a quien despliega le sirve mucho más ver los cuatro que le faltan
que descubrirlos arranque tras arranque.

```bash
ENV=prod

# Firma todos los tokens. Si sigue con el valor de ejemplo, cualquiera puede
# emitirse uno de administrador.
SECRET_KEY=$(openssl rand -base64 48)

# Cifra los campos sensibles y los secretos de integración.
ENCRYPTION_KEY=$(openssl rand -base64 32)

# Un rol POR SERVICIO, sin SUPERUSER ni BYPASSRLS (ver más abajo).
DATABASE_URL=postgresql+psycopg://crm_<servicio>_app:<clave>@bd:5432/contecrm
DATABASE_ADMIN_URL=postgresql+psycopg://crm_<servicio>_mig:<clave>@bd:5432/contecrm

RLS_ENABLED=true
BUS_BACKEND=nats
NATS_URL=nats://bus:4222
```

### El rol de base de datos: la condición sin la cual RLS no aísla

Un rol **SUPERUSER** —o con **BYPASSRLS**— se salta las políticas de Row-Level
Security aunque estén en `FORCE`. Con un rol así, el aislamiento entre tenants
está «activado» y **no existe**: da confianza sin darla.

`deploy/crear-bases.sh` crea, por cada servicio:

- un **esquema** propio,
- un rol de **aplicación** que solo puede leer y escribir en él, **sin DDL** —
  así una inyección SQL no puede alterar el esquema ni desactivar una política—,
- un rol de **migración** que sí puede hacer DDL, y que es el único que se usa
  para migrar.

Ninguno de los dos es superusuario. El arranque lo comprueba y lo registra como
error si no se cumple.

## Puesta en marcha

```bash
# 1. Esquemas y roles (una vez, como administrador de la base)
psql "$ADMIN_DATABASE_URL" -f deploy/crear-bases.sh

# 2. Migraciones (paso aparte, ANTES de levantar nada)
python scripts/migrar.py --todos upgrade head

# 3. Políticas de aislamiento: SIEMPRE después de migrar
python scripts/aplicar_rls.py --todos

# 4. Servicios
docker compose --profile app up -d
```

El paso 3 no es opcional ni se puede posponer: **una tabla nueva nace sin
política**, y una tabla con `tenant_id` sin política es un agujero de
aislamiento que no da ningún síntoma hasta que dos clientes se ven los datos.
Para comprobarlo sin modificar nada:

```bash
python scripts/aplicar_rls.py --todos --comprobar
```

En producción, las migraciones van en un paso **separado del arranque**
(`APLICAR_MIGRACIONES=false`): si dos réplicas migran a la vez, la segunda se
encuentra el esquema a medias.

### Los servicios de la casa: contecintelligence y contecmind

Dos capacidades no las implementa contecrm: la **explotación** (informes,
cuadros de mando, exportaciones analíticas) la resuelve contecintelligence
(RT-4) y el **corpus documental** (contratos, procedimientos, certificados, con
versión y aprobación) lo resuelve contecmind (RT-5). Los dos se consumen de
forma frontless y los dos se activan o no.

```bash
# Con explotación y corpus documental incluidos en la pila
docker compose --profile app --profile consola up -d
python scripts/vecinos.py levantar   # contecintelligence y contecmind, con SU compose
```

| Ajuste | Para qué |
|---|---|
| `DMS_ENABLED` | Activa el corpus documental. Desactivado, la pestaña no existe |
| `DMS_BASE_URL` | Dirección del contecmind a usar. Vacío con el perfil `dms` = el de la pila |
| `DMS_CLIENT_ID` / `DMS_CLIENT_SECRET` | Credencial de aplicación. **Solo** sirve para canjear el token de cada usuario |
| `DMS_COMPROBAR_AL_ARRANCAR` | Comprueba el enlace al arrancar en vez de la primera vez que alguien abre la pestaña |
| `DMS_EXIGIR_AL_ARRANCAR` | El servicio se **niega a arrancar** si no lo alcanza. Para producción |
| `DMS_TIMEOUT_S` / `DMS_TOKEN_TTL_S` | Paciencia de cada llamada y vida del token de usuario |
| `DMS_SCOPES` | Alcances que se piden al canjear el token. **Los dos por defecto** — ver abajo |

##### `DMS_SCOPES`: por qué son dos y no uno

contecmind comprueba los alcances **en cada petición**, y separa abrir un
documento (`documents:read`) de buscar en el corpus (`documents:search`). El
valor por defecto pide los dos.

Con sólo `documents:read` el producto no falla del todo: la ficha de un
documento se abre bien y el buscador devuelve 403. Media pantalla funcionando es
el peor fallo posible de diagnosticar, así que conviene saberlo antes: si
alguien acota este ajuste, está apagando el buscador del corpus a propósito.

Y hay un techo por encima: los alcances que el administrador de contecmind
concedió a esta aplicación al darla de alta. Pedir aquí más de lo concedido no
es un error —se concede la intersección— pero tampoco sirve de nada.

#### Para que «Explotación» funcione hacen falta tres cosas

1. **`CI_URL_DEL_CRM`** — con qué dirección ve contecintelligence a este CRM. No
   es `CI_BASE_URL` al revés: desde su contenedor, `localhost` es él mismo.
   En la pila de desarrollo: `http://gateway:8000/api/v1`.
2. **`CI_URL_PUBLICA`** — la dirección de contecintelligence **para el
   navegador**. La pantalla pregunta desde el cliente con un token corto, así
   que necesita una dirección que el navegador pueda resolver.
   En desarrollo: `http://localhost:8100`.
3. **Pulsar «Registrar el CRM como fuente consultable»** en la propia pantalla.
   El servidor emite una credencial de solo lectura, lee su propia
   `/superficie` para saber qué objetos hay, mide la forma de cada listado y da
   de alta la fuente. No hay nada que rellenar.

   Va **en diferido**: la ruta responde `202` con un identificador de trabajo y
   lo ejecuta `analytics-trabajos`. No es una preferencia de estilo — el alta
   tarda unos doce segundos (recorre cuarenta y siete listados probando la forma
   de cada uno) y el gateway corta a diez, así que de forma síncrona devolvía
   **504 aunque por debajo el registro saliera bien**. Subir el plazo no lo
   arregla: ese tope protege al resto, porque una petición que se queda diez
   segundos ocupa un hueco de conexión.

   El servicio `analytics-trabajos` tiene que estar levantado. Sin él, el botón
   contesta `202` y el trabajo se queda encolado para siempre.

Y en contecintelligence, dos cosas del lado de allá: la aplicación de contecrm
necesita el alcance **`sources:write`** (con `sources:read` no puede registrarse)
y sus **orígenes** tienen que incluir el del navegador, o el preflight de CORS
tumba la pregunta antes de salir.

#### El almacén analítico no se llenaba solo

`POST /almacen/cargas` esperaba que **cada servicio empujara lo suyo**, y en toda
la vida del proyecto ninguno lo hizo. No fallaba nada: el almacén estaba vacío,
«Frescura» decía «nunca cargada» para todas las tablas y siempre, y cualquier
informe que leyera de ahí devolvía cero filas.

Ahora hay un cargador (`POST /api/v1/almacen/cargar`, y el botón **Cargar ahora**
en la pestaña de frescura) que trae las filas **por la API pública** del propio
CRM con una credencial de solo lectura. Dos consecuencias buenas: el almacén ve
exactamente lo que ve un lector —con su enmascarado por rol— y no hay trece
cargadores que escribir.

Cada tabla declara de dónde se trae (`ruta`). No se deduce del objeto: las
etiquetas de la superficie son ambiguas —`casos` etiqueta también las *colas* de
casos— y cargar la tabla equivocada es peor que no cargar.

#### Una credencial de máquina no es una persona

Las claves de API veían **cero filas** en cualquier listado con compartición. No
era un permiso: era que `filtro_visibilidad` pregunta «¿de quién es este
registro y a quién se lo han compartido?», y una credencial no posee nada ni
está en ningún equipo. Devolvía una lista vacía sin un solo error.

Un principal de tipo `servicio` representa al **tenant**, así que no se le aplica
la compartición. Lo que sí se le sigue aplicando es el **ABAC**: las políticas de
dato son del dato, y una integración que las esquivara sería la puerta de atrás
de todas ellas. Y lo que lo acota es lo que se le dio al crearla: su tenant, su
rol de solo lectura y sus alcances.

Para que eso funcione, el `tipo` del principal **viaja en las cabeceras
firmadas** (`x-crm-tipo`). No viajaba, y mientras todo lo que entraba eran
personas no se notó.

#### El canje de token con contecintelligence: DOS pasos

Levantados los dos productos de verdad por primera vez (24-09-2026), el canje
daba **401**. El cliente se había escrito contra un contrato imaginado:

| | Lo que hacía contecrm | Lo que publica contecintelligence |
|---|---|---|
| Pasos | uno | **dos**: credencial → token de aplicación → token de usuario |
| Credencial | autenticación básica en el canje | en el cuerpo de `POST /api/oauth/token` |
| Ruta | `/api/v1/tokens/exchange` | `/api/tokens/exchange` — **no hay nada bajo `/api/v1`** |
| Duración | campo `ttl` | campo `ttl_s` |

El del campo era el más silencioso de los cuatro: pydantic ignora un nombre que
no declara, así que el token habría salido con la duración por defecto del otro
lado y sin un solo aviso.

Sobrevivió porque no había ninguna prueba que recorriera el camino completo: la
única que tocaba `canjear_token` comprobaba que sin organización se niega, que
es antes de hablar con nadie. Ahora lo fija
`tests/unit/test_cliente_intelligence.py`: las dos rutas, el orden, cómo viaja
cada credencial y los nombres de los campos.

#### Cuando los vecinos no están en la misma pila

El guardia anti-SSRF (`url_guard`) rechaza cualquier URL que resuelva a IP
privada, incluida la red de Docker. Si contecintelligence o contecmind corren en
otro compose —lo normal si ya los tenías levantados—, hay que:

1. Meterlos en la red de contecrm con el nombre que espera:
   `docker network connect --alias contecintelligence contecrm-dev_default <contenedor>`
2. Declararlos en `URL_GUARD_HOSTS_PERMITIDOS=contecintelligence,contecmind`

El guard **no se apaga**: se le nombran los hosts, que es para lo que existe ese
ajuste. Y `host.docker.internal` no vale: resuelve a una IP privada y el guard
lo bloquea con razón.

Dos cosas que conviene tener claras antes de activarlo:

**Los adjuntos no dependen de esto.** Con `DMS_ENABLED=false` se sigue
adjuntando a las fichas, con versiones, carpetas y enlaces firmados. Lo que no
hay es corpus. Son dos capas distintas y a propósito.

**Cada tenant necesita su organización en contecmind.** Se mapea con
`PUT /api/v1/documentos/organizacion`, y **sin mapeo no se llama al gestor**:
es lo que impide que un fallo de configuración enseñe los documentos de un
cliente a otro.

### Sembrar datos: una parte por servicio

Cualquier script que toque varios servicios hay que ejecutarlo **donde tenga
permisos**. El rol de `tenancy` no puede leer el esquema de `identity`, así que
un sembrador que intente las dos cosas desde un sitio falla con «relation
"usuarios" does not exist» — que no es un error del script, sino el aislamiento
funcionando:

```bash
# 1. El tenant, desde el servicio que lo posee
docker compose exec tenancy python scripts/sembrar_demo.py --parte tenant

# 2. El usuario, desde el suyo
docker compose exec -e TENANT_DEMO=<id> identity \
  python scripts/sembrar_demo.py --parte usuario
```

En desarrollo local, donde el rol es superusuario, `./setup.sh demo` lo hace de
una vez. Es la misma diferencia que con RLS: lo que en local pasa
inadvertidamente, en producción está impedido.

## Operación diaria

### Umbrales: qué se afina por cliente y qué por despliegue

Un umbral escrito en el código es un umbral que nadie puede cambiar sin tocar,
desplegar y esperar. Medido el 26-10-2026: **85 constantes numéricas de módulo**
en 70 ficheros. Van saliendo por lotes, con un guardián que impide que entren
nuevas (`test_ningun_umbral_vive_en_el_codigo.py`).

Al moverlas se aplica una regla que conviene conocer, porque explica por qué
unas se pueden poner por cliente y otras no:

- **Clave en caliente** (`ajustes_runtime`, por tenant) sólo para las que se
  leen donde hay sesión de base de datos. `efectivo()` consulta, así que se lee
  **una vez por llamada y nunca dentro de un bucle** — ahí sería una consulta
  por vuelta.
- **Sólo `.env`** para las que se calculan en funciones puras. Ahí meter una
  sesión para leer un número sería pagar una consulta por llamada.

A las segundas **no se les declara clave a propósito**. Un ajuste que la consola
deja poner por tenant y que luego no se aplica es peor que no tenerlo: quien lo
pone cree que ya está.

Y en ningún caso el valor va como defecto de un argumento: eso se evalúa al
**importar**, así que congelaría el ajuste para toda la vida del proceso y
cambiarlo en el `.env` no cambiaría nada. Se resuelve dentro de la función.

> **Medido el 26-10-2026: de 85 a 0.** No queda ninguna constante numérica de
> módulo en `services` ni en `crmcore`, salvo seis que no son umbrales y están
> exentas con su motivo: el radio de la Tierra, el tamaño de un nonce de
> AES-GCM, la longitud mínima de clave, el identificador del cerrojo de
> migración, el 4.5:1 de WCAG y el ancho de la columna de deduplicación —esta
> última se movió, y al moverla se vio que cambiarla exige una migración, así
> que volvió al código—.
>
> El guardián sigue puesto: lo que vuelva a escribirse en el código cae en
> `test_ningun_umbral_nuevo_nace_en_el_codigo`.

#### Lo que ya se puede afinar

| Clave | Qué decide | Por cliente |
|---|---|---|
| `SALUD_DIAS_VIGENCIA` | Cuándo una medida de salud deja de valer para actuar | sí |
| `MDM_DIAS_FRESCURA` | Cuánto aguanta un dato maestro sin revisar | sí |
| `PROVEEDOR_DIAS_PREAVISO` | Antelación del aviso de renovación | sí |
| `STEWARDSHIP_DESCARTES_PARA_SOSPECHAR` | Descartes tras los que se sospecha de una regla | sí |
| `IDENTIFICADOR_DIAS_VEREDICTO` | Cuánto vale un veredicto fiscal | sí |
| `IA_MINIMO_SENALES` | Señales mínimas para recomendar | sí |
| `IA_MINIMO_CONTEXTO` | Caracteres mínimos para resumir | sí |
| `IA_CONFIANZA_EXTRACCION` | Cuándo se da por buena una extracción | sí |
| `IA_FACTORES_VISIBLES` | Cuántos factores explican una predicción | sí |
| `IA_CONFIANZA_TRANSCRIPCION` | Cuándo una transcripción es fiable | no |
| `IA_CONFIANZA_VOZ` | Cuándo se actúa sobre lo entendido por voz | no |
| `IA_PARECIDO_CASO` | Parecido para proponer un caso ya resuelto | no |
| `IA_CASOS_SUGERIDOS` | Cuántos casos parecidos se sugieren | no |
| `IA_MINIMO_CASOS_ENTRENO`, `IA_MINIMO_POR_CLASE` | Datos mínimos para entrenar | no |
| `IA_PCT_VALIDACION` | Qué porcentaje se reserva para validar | no |
| `IA_MINIMO_POR_RAMA` | Envíos por rama para dar una A/B por concluyente | no |
| `IA_MAX_TOKENS_RESPUESTA` | Tope de tokens de la respuesta del modelo | no |
| `IA_CARACTERES_RESULTADO_PASO` | Cuánto de un resultado ve el agente iterativo en la vuelta siguiente | no |
| `SLA_RIESGO_HORAS` | Cuándo un caso pasa a «a punto de vencer» | sí |

> **Los de IA se ponen bajos a propósito**, para proponer mucho y decidir poco:
> una sugerencia que alguien descarta cuesta un clic, un dato que se mete solo y
> está mal cuesta encontrarlo meses después. En un sector regulado conviene
> subir `IA_CONFIANZA_EXTRACCION` antes de dejar que una extracción pise lo que
> escribió una persona.

### El contrato publicado está sellado (`CRM-00.02.01.06`)

`docs/contrato-publicado.json` guarda las **2.396 operaciones** —método y
camino— que publican los catorce servicios. Un gate comprueba en cada push que
ninguna haya desaparecido.

Existe porque la compatibilidad hacia atrás es la promesa que más duele
romper y **no se rompe con un error**: se rompe en silencio, y quien se entera
es el cliente de otro, en producción, el día del despliegue.

- **Añadir no rompe nada**, así que no se vigila.
- **Quitar no se bloquea del todo: se bloquea quitar sin decirlo.** Para
  retirar algo hay dos caminos, y los dos son explícitos: anunciar la retirada
  con `API_SUNSET_DATE` y subir la versión mayor, o volver a sellar dejando
  dicho en el commit qué se fue y por qué.

Se sella con `python scripts/sellar_contrato.py --sellar`, igual que se
regenera el documento de procesos.

Lo que el sello **no** guarda son los campos. Los vigilan otros gates —el de
atributos y los contratos que leen las pantallas— y meterlos aquí haría un
fichero que nadie revisa y que cambia en cada commit.

### Los formatos los pone el tenant, no el código (`CRM-07.04.01.05`)

`GET /api/v1/localizacion` devuelve las preferencias **ya resueltas** por la
jerarquía global → tier → tenant → unidad → usuario: idioma, zona horaria,
formato de fecha, moneda funcional y primer día de la semana. Y con **un
ejemplo de cada una**, que no es decorativo — es el contrato: un cliente puede
comprobar que su formateo coincide con el del servidor sin implementar la
jerarquía.

Existe porque el CRM es headless. Si cada frontend resolviera los ajustes por
su cuenta, la web y el móvil acabarían escribiendo la misma fecha de dos
maneras.

> **Y hasta el 26-10-2026 el front no la leía.** Tenía `"es-ES"` escrito a mano
> en **dieciséis sitios de cinco ficheros**, con los formateadores creados como
> constantes de módulo: se construyen al importar, así que no podían cambiar ni
> aunque alguien quisiera. Un tenant en Portugal o en México veía sus números
> escritos como en España.
>
> Arreglado con una sola fuente que se fija con lo que dice el servidor al
> arrancar. No bloquea el arranque: si la petición falla, se monta con el
> respaldo —una pantalla en blanco por no poder leer un formato de fecha sería
> peor que una coma en otro sitio—. Y hay un guardián que recorre el árbol y
> falla si la localización vuelve a aparecer escrita a mano.
>
> Sobre la **paridad entre idiomas** que pide la misma capacidad: hoy sólo hay
> castellano, así que no hay con qué compararla. Queda dicho en vez de darse
> por comprobada.

> **Y el 30-10-2026 se encontró la otra mitad.** El guardián de entonces
> buscaba la cadena `"es-ES"` escrita a mano, y lo que quedaba no la tenía:
> eran diez pantallas llamando a `new Date(x).toLocaleDateString()` **sin
> argumentos**, que no escribe ninguna localización — coge la del navegador. El
> efecto se vio en la ficha de un presupuesto, con la interfaz en castellano:
>
> ```
> Válido hasta el 11/26/2026
> 1531.00 EUR
> ```
>
> El 26 de noviembre escrito al revés, y el importe en crudo: decimal con
> punto, sin separador de miles y con el código ISO detrás en vez del símbolo.
> Lo peor de un fallo así es que **no falla para todos**: quien tenga el
> navegador en castellano lo ve bien y no lo reporta nunca.
>
> Ahora hay `fecha()` y `fechaHora()` en `lib/formato.ts`, al lado de
> `importe()` y `escalar()`, y un guardián que recorre el árbol y no deja pasar
> una llamada a `toLocale*String()` sin argumentos.
>
> **El idioma del documento también viaja con ella.** `index.html` traía
> `lang="es"` fijo; ahora se fija con lo que responde el servidor. Eso arregla
> dos cosas —Firefox pinta el selector de fecha en el formato del tenant, y los
> lectores de pantalla leen el idioma correcto— y **no arregla una tercera**:
> Chrome usa la localización de su propia instalación para el control
> `<input type="date">` y no mira el `lang` de la página, así que quien tenga
> el navegador en inglés verá ahí `mm/dd/yyyy` por mucho que la pantalla esté
> en castellano. No se puede arreglar desde el producto, y queda escrito en vez
> de darse por resuelto.

### Filtrar un listado por rango (`CRM-00.02.01.10`)

Los filtros de la URL eran **igualdad y nada más**, así que no había forma de
pedir «lo que vence antes del viernes» ni «lo de más de 50.000». Ahora:

```
?vence_at__hasta=2026-11-02          lo que vence antes (incluido)
?vence_at__desde=2026-10-26          desde esa fecha (incluida)
?importe__mayor=50000                estrictamente mayor
?importe__menor=1000                 estrictamente menor
?estado__distinto=cerrada            todo menos ése
?estado__en=abierta,en_curso         cualquiera de la lista
?cerrada_at__vacio=1                 sin valor
?cerrada_at__no_vacio=1              con valor
?estado=abierta                      igualdad, como siempre
```

Los dos extremos a la vez acotan una ventana (`...__desde=X&...__hasta=Y`).

**No es una gramática nueva.** El motor de permisos tiene desde siempre una
lista cerrada de operadores con su traductor a SQL, y la razón está escrita en
su propio código: dos gramáticas para lo mismo es cómo se acaba con un listado
que enseña un registro que la ficha luego niega. Estos son nombres url-safe de
esa misma gramática.

Tres cosas que conviene saber:

- **Un operador que no existe se rechaza con 422** y dice cuáles valen.
  Tratarlo como igualdad —o ignorarlo— devolvería filas de más y parecería
  correcto, que es el mismo fallo que ya costó caro con los filtros que no
  filtraban.
- **Un valor mal escrito también es 422**, no 500. Antes
  `?vence_at__hasta=manzana` llegaba hasta Postgres y volvía como error interno,
  que manda a mirar los registros del servidor para descubrir una errata. Ya
  pasaba con la igualdad de siempre: el rango no lo trae, lo destapa.
- **El `+` de un desfase horario viaja como espacio** en una query: es lo que
  dice el estándar. Se admiten las tres formas —`Z`, `%2B02:00` y el espacio—
  porque rechazar una sería un error que parece de formato y es de
  codificación.

`contiene` no está: en SQL depende del tipo de la columna —un JSONB, un array,
una relación— y el traductor devuelve «no sé» a propósito en vez de inventarse
una traducción aproximada. Un filtro «casi igual» produce un listado que casi
acierta, y eso no se detecta mirándolo.

**Y valen en todos los listados.** Esto no era así hasta el 26-10-2026: la
fábrica monta 61 listados y les da los filtros comunes gratis, pero hay otros
**escritos a mano** —los que tienen filtros propios que la fábrica no sabe
expresar: «sólo las mías», «sólo las vencidas», «las de esta cuenta»—, y ésos se
quedaban sin los comunes. El resultado era que `?vence_at__hasta=…` funcionaba
en unos sitios y devolvía 422 en otros, y quien integra lo descubría probando:
el mismo producto admitía rangos o no según quién había escrito cada listado,
que no es un contrato.

Tener filtros propios es legítimo; quedarse sin los comunes no. Los veintiocho
listados a mano que hay los admiten ahora todos. La única excepción es el de
entornos, y no es deuda: devuelve una lista **cerrada** escrita en el código
—las cuatro etapas por las que pasa la configuración hasta producción— y no una
tabla, así que no hay columnas por las que filtrar.

Lo vigilan dos pruebas que van juntas a propósito: una lee el código —que cada
listado llame al filtro común y se declare de parámetros abiertos— y la otra
**recorre las rutas** y le pide a cada una un filtro inventado, esperando el
422. La primera sola no basta porque las dos mitades se separan con facilidad:
con el filtro y sin la marca, la ruta contesta 422 a los filtros que ella misma
acaba de ofrecer.

### Un parámetro que no se mira es un filtro que no filtra

FastAPI **se come en silencio** cualquier parámetro de query que la función no
declare. Eso ya costó caro: `/activities?cuenta_id=X` devolvía todas las filas
del tenant como si el filtro existiera. Se arregló en la fábrica de listados,
que monta 61 — y quedaban **29 escritos a mano** con el mismo agujero: usuarios,
roles, políticas, encargos, entornos. Ya no queda ninguno (ver arriba).

Ahora la comprobación va en la aplicación entera, igual que la idempotencia:
engancharla ruta a ruta significa que funciona en las que alguien se acordó, y
son casi trescientas. Un parámetro que la operación no mira devuelve **422** y
dice cuáles admite.

Dos clases de ruta quedan fuera, cada una con su motivo escrito al lado: los
listados de la fábrica, cuyos filtros son los nombres de las columnas y que ya
los validan ellos mismos, y las vueltas de un proveedor externo —OAuth, SAML,
una pasarela—, que traen lo que les da la gana.

### `TAREAS_FONDO_ENABLED`

Los barridos del núcleo —purgar la bandeja de entrada de eventos, la de salida y
los adjuntos huérfanos— que arranca **todo** servicio. Encendidos por defecto.

Apagarlos tiene sentido en dos sitios: en producción, porque las tres tablas son
comunes y catorce servicios barriendo las mismas filas es el mismo trabajo
repetido trece veces —se pueden dejar encendidos en un solo proceso—; y en
pruebas, porque un barrido abre su sesión cuando le toca el reloj y eso puede
caer en medio de otra cosa.

Apagarlo en **todos** los procesos deja tres tablas creciendo sin techo. Si se
apaga, que sea en trece de los catorce.

### Lo que ajusta la instalación y lo que ajusta cada persona

Hay dos niveles de configuración y conviene no mezclarlos, porque el segundo no
existía hasta el 26-10-2026 y eso tenía una consecuencia práctica.

**Las palancas de la instalación** se fijan desde la consola y exigen
`tenant:write`: topes, plazos, umbrales, interruptores. Van por
`PUT /api/v1/ajustes/{clave}` y se auditan.

**Las preferencias de cada persona** las cambia su dueño, sin permiso de
administración, por `PUT /api/v1/mis-preferencias/{clave}`. Hoy son cinco:

| Clave | Qué es | Defecto del despliegue |
|---|---|---|
| `idioma` | Idioma de la interfaz y los correos | — |
| `zona_horaria` | Zona para fechas y calendarios | — |
| `formato_fecha` | `dd/mm/aaaa`, `mm/dd/aaaa` o `aaaa-mm-dd` | — |
| `primer_dia_semana` | 0 = lunes | — |
| `ui_densidad` | `compacta` o `comoda` | `UI_DENSIDAD` |

> **Por qué hacía falta.** Las cinco estaban declaradas hasta el ámbito de
> usuario desde el principio —la jerarquía de ajustes termina en «usuario»
> precisamente para esto—, pero la única ruta que fijaba un ajuste exigía
> `tenant:write`. La cadena se cortaba un escalón antes del final: un comercial
> no va a abrir un ticket para que le cambien el formato de fecha, así que en la
> práctica la preferencia personal no existía.

**Qué cuenta como preferencia personal no es una lista escrita a mano**: es toda
clave declarada con `minimo_ambito="usuario"` y sin marcar `sensible`. Si mañana
hace falta un ajuste por usuario que deba poner un administrador —una exención,
un permiso ampliado—, se marca `sensible=True` y se queda en la consola. Una
lista de las que sí se habría quedado corta en cuanto alguien declarase la
siguiente, y además en silencio: la preferencia simplemente no se podría
guardar y nadie sabría por qué.

**El ámbito lo pone el servidor, nunca el cuerpo de la petición.** Es lo que
impide que cualquiera con una cuenta normal cambie el idioma —o la densidad— de
todo el tenant mandando `ambito: "tenant"`.

#### `UI_DENSIDAD`: el defecto de toda la instalación

`compacta` por defecto. Cabe mucho más en pantalla —unas catorce filas de una
lista donde en cómoda caben cuatro— y es lo que quiere quien trabaja aquí ocho
horas. Ponerlo a `comoda` tiene sentido en una instalación de demostración o
donde se usa en pantallas grandes y de lejos.

Es el **defecto**, no una imposición: quien quiera la otra se la pone y la suya
manda. Y el front **no guarda el defecto al arrancar**, a propósito: hacerlo le
daría a cada persona un valor propio idéntico al defecto desde el primer día, y
el día que cambiaras `UI_DENSIDAD` no le cambiaría a nadie.

#### Restablecer devuelve el de arriba; no apaga el ajuste

Quitar un ajuste de un ámbito **destapa el del ámbito de encima**, no deja un
hueco. Quitar el del tenant devuelve el global; quitar también el global
devuelve el del `.env`. Es lo que espera quien pulsa «restablecer», y es lo
contrario de lo que haría un ajuste quitado que se quedara en nulo: eso apagaría
la funcionalidad en vez de devolverla al valor de la casa.

Medido el 26-10-2026 recorriendo la escalera entera con `ui_densidad` —hacia
abajo y hacia arriba—, que es la única forma de comprobarlo con una clave de
verdad y no con una inventada para la ocasión.

#### Una clave no se puede fijar por debajo de su ámbito

De las 90 claves en caliente, **83 paran en el tenant**, 5 llegan al usuario y 2
son de la instalación entera. Intentar fijar una del tenant por usuario se
rechaza, y el error dice cuál es su ámbito más específico —un «no» sin decir qué
sí se puede deja al operador probando.

No es burocracia: el tope de tamaño de un adjunto protege el almacenamiento de
la instalación. Si cada persona pudiera levantárselo, la pantalla de Admin
seguiría enseñando el límite de la empresa mientras el disco se llena por otro
lado.

### Salud

Cada servicio expone dos endpoints que **no son lo mismo**, y confundirlos sale
caro:

- `/health/live` — «este proceso no está colgado». Si el *liveness* comprobara
  la base de datos, una caída de Postgres haría que el orquestador matara y
  recreara todos los servicios sanos, que al volver se encontrarían la base
  igual de caída pero ya sin caché ni conexiones.
- `/health/ready` — «puede atender ahora mismo», con el detalle de qué
  comprobación falla.

El gateway agrega el estado de todos en `GET /api/v1/servicios`.

### Métricas

`/metrics` en formato Prometheus, con etiqueta de tenant y **tope de
cardinalidad** (`METRICS_MAX_TENANTS`): pasado el tope, el resto se agrupa en
`otros`. Sin ese tope, una etiqueta por cliente tumba a Prometheus y se pierden
también las métricas que sí importaban.

Las que conviene vigilar:

| Métrica | Qué mirar |
|---|---|
| `crm_http_duracion_segundos` | p95 y p99 por ruta y tenant |
| `crm_outbox_antiguedad_segundos` | **La más importante**: mil eventos publicándose es normal; uno atascado desde hace una hora es un incidente |
| `crm_outbox_pendientes` | Acumulación sostenida = el bus no está entregando |
| `crm_limites_aplicados_total` | Quién está tocando techo y en qué dimensión |
| `crm_eventos_consumidos_total{resultado="error"}` | Consumidores que fallan en bucle |

### Los eventos que no salieron

Un evento que agota sus reintentos **no se pierde**: va a la cola de fallidos con
su último error.

```bash
curl -s .../api/v1/eventos/fallidos -H "Authorization: Bearer $TOKEN"
curl -sX POST .../api/v1/eventos/fallidos/<id>/reenviar -H "Authorization: Bearer $TOKEN"
```

El reenvío lo devuelve a la cola de salida en vez de publicarlo directamente:
así pasa por el mismo camino que un envío normal, sin un segundo camino que
mantener.

### Webhooks de un integrador caído

Una suscripción que acumula 20 fallos seguidos **se desactiva sola**. Cuando el
integrador vuelva:

```bash
curl -sX POST .../api/v1/webhooks/<id>/reactivar -H "Authorization: Bearer $TOKEN"
curl -sX POST .../api/v1/webhooks/<id>/replay -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{"desde":"2026-09-15T00:00:00Z"}'
```

El replay reencola los eventos archivados del periodo. La deduplicación por
`dedup_key` evita que el integrador procese dos veces lo que sí recibió.

### Procesos atascados

```bash
# Los que han fallado
curl -s ".../api/v1/instancias?estado=fallida" -H "Authorization: Bearer $TOKEN"

# Por dónde iba y con qué datos
curl -s ".../api/v1/instancias/<id>/historial" -H "Authorization: Bearer $TOKEN"
```

Si la causa fue un dato mal cargado, se corrige la variable —con motivo, y queda
auditado— y se reintenta, en vez de relanzar el proceso entero.

## Seguridad de la instalación

Tres cosas que **no** hace el software y tiene que garantizar el despliegue:

1. **Los servicios no pueden ser alcanzables desde fuera.** Solo el gateway se
   publica. La identidad que el gateway propaga va firmada, así que no se puede
   falsificar sin el secreto, pero un servicio expuesto por error en Internet
   sigue siendo una superficie que no debería existir.
2. **TLS termina antes del gateway** (proxy o balanceador). Si hay proxy, hay
   que declararlo: `TRUST_PROXY_HEADERS=true` **y** `TRUSTED_PROXIES` con sus
   redes. Activar el primero sin el segundo permite a cualquiera falsear su IP y
   saltarse el rate limiting; el arranque se niega si falta.
3. **Cifrado de disco** en la base y en las copias. El cifrado de campo protege
   frente a quien lee la base; no frente a quien tiene el disco.

### Las puertas de entrada se encienden una a una (CRM-00.05.01.01, .02, .06)

De fábrica, **esta instalación no ofrece SSO ni provisión automática**. Son
cuatro interruptores del fichero de entorno, y cada uno abre una puerta
distinta:

| Ajuste | De fábrica | Qué abre |
|---|---|---|
| `OIDC_ENABLED` | `false` | Configurar proveedores OIDC y entrar por ellos |
| `SAML_ENABLED` | `false` | Lo mismo con SAML |
| `SCIM_ENABLED` | `false` | Que un proveedor de identidad cree, modifique y **borre** usuarios solo |
| `MFA_ENABLED` | `true` | El segundo factor: inscripción, códigos y equipos recordados |

Cada interruptor cierra **todas** las puertas de lo suyo, no la primera. Con
`SAML_ENABLED=false` no se puede configurar un proveedor SAML, no se puede
empezar un inicio de sesión con uno que ya estuviera configurado —apagarlo no
borra los que ya había, que son los que importan— y tampoco entra una respuesta
del proveedor que venga de camino: un flujo empezado minutos antes se rechaza.

Qué se ve al tocarlo: `403` con `sso.protocolo_desactivado`, `scim.desactivado`
o `mfa.desactivada`, y el mensaje dice **con qué ajuste se enciende**. No es un
`404`: esconder que la puerta existe obliga a quien administra a adivinar si se
ha equivocado de dirección o si está apagada, y son dos arreglos distintos.

**Apagar el segundo factor no deja fuera a quien ya lo tenía.** Con
`MFA_ENABLED=false`, a un usuario que ya tuviera su factor configurado no se le
pide el código — pedírselo sería mandarlo a una pantalla que ese mismo
interruptor acaba de apagar. Apagar un segundo factor es renunciar a él, no
cerrarle la puerta a quien se molestó en ponerlo.

> **Hasta el 6 de octubre de 2026 estos cuatro ajustes no los leía nadie.**
> Estaban en el fichero de entorno y en el manual de referencia, y de ahí no
> pasaban: `SAML_ENABLED=false` no apagaba SAML. Si viene de una versión
> anterior, **revise los cuatro**: lo que creía apagado estaba abierto, y lo que
> dé por sentado que funciona puede estar ahora apagado de fábrica.

### Lo que se quitó: `SUPLANTACION_EXIGE_MOTIVO`

Ese ajuste ya no existe. El motivo escrito se exige **siempre** al suplantar, y
no es negociable: sin él no hay forma de revisar después si el acceso estaba
justificado, que es la mitad de lo que hace que la suplantación no sea una
puerta trasera.

Tampoco lo leía nadie, así que ponerlo a `false` no quitaba nada — mentía en los
dos sentidos. Enchufarlo habría sido ofrecer apagar una garantía de auditoría;
se quitó, que es lo que dice la verdad. Para desactivar la suplantación entera
está `suplantacion_enabled`, por tenant, que sí se aplica.

### La auditoría se puede apagar, pero no a escondidas (CRM-00.05.04)

| Ajuste | De fábrica | Qué hace al apagarlo |
|---|---|---|
| `AUDIT_ENABLED` | `true` | **No se anota nada.** Ni quién entró, ni quién cambió qué |
| `AUDIT_HASH_CHAIN` | `true` | Se anota, pero sin encadenar: ahorra un hash por apunte |

Apagar cualquiera de los dos **sale en el readiness del servicio**
(`GET /health/ready`, apartado `auditoria`). No marca el servicio como «no
listo» —no es una avería— pero no puede ser invisible: una instalación sin
auditoría tiene que ser una decisión que alguien ve en el panel, no algo que se
descubre el día que hay que demostrar quién tocó qué.

**Sin cadena no es lo mismo que rota.** La verificación
(`GET /grc/auditoria/verificar`) distingue las dos cosas y devuelve
`sin_cadena: N`: de esos apuntes se demuestra que **no falta ninguno** —el hueco
en la secuencia sigue cazando un borrado— pero no que no se hayan modificado en
su sitio. «Intacta» con tramos sin encadenar no es la misma afirmación que
«intacta» entera, y quien audita lo ve sin preguntar.

### El cuerpo de las peticiones en el log

`LOG_REQUEST_BODY` viene **apagado** y conviene dejarlo así: es la vía más
rápida de llevar datos personales a un sistema de logs que no está pensado para
guardarlos. Encendido, el cuerpo sale solo en el apunte de las peticiones
**lentas o fallidas**, que es para lo que sirve.

Lo que sale va censurado por dentro, con la misma lista que el resto del log:
las contraseñas y los secretos se tapan **siempre**, también en desarrollo; los
datos personales se sustituyen por un hash estable cuando `LOG_REDACT_PII` está
activo, que es el valor por defecto fuera de desarrollo. Un cuerpo que no se
puede analizar —binario, un formulario, uno cortado por el tope de 4 KB— **no se
suelta**: se registra su tamaño. Lo que no se puede censurar no se puede
publicar.

### Exportación del audit trail a un SIEM

Se hace **por descarga**, no por empuje: `GET /grc/siem/volcado` devuelve el
periodo pedido en JSON Lines con su marca de integridad, en formato neutro y no
en el de un producto concreto. Es como la mayoría de los SIEM recogen — ellos
consultan.

> `AUDIT_SIEM_URL` ya no existe. Prometía un destino al que el producto
> empujaría los apuntes, y el producto no empuja; además, no lo leía nadie, así
> que escribir una URL ahí no mandaba nada a ningún sitio.

### Los interruptores que se tocan durante un incidente

Tres ajustes que se apagan con el sistema ardiendo, y por eso importa que
apaguen de verdad: quien los pone a `false`, reinicia y no ve ningún cambio
acaba buscando la avería donde no está.

| Ajuste | De fábrica | Qué hace al apagarlo |
|---|---|---|
| `CIRCUIT_BREAKER_ENABLED` | `true` | Ningún recurso se corta por fallar, **y se cierran los que ya estuvieran abiertos** |
| `DEGRADACION_ENABLED` | `true` | Nada se rechaza por presión: pasa todo, incluido lo diferible |
| `INBOX_ENABLED` | `true` | Se deja de deduplicar: el mismo hecho puede procesarse dos veces |

Apagar el cortacircuitos **cierra los circuitos abiertos**, no sólo impide abrir
nuevos: se apaga para *salir* de un corte, no para prevenir el siguiente. Los
fallos se siguen contando, de modo que si vuelve a encenderlo en mitad del
incidente el circuito protege otra vez enseguida en vez de tener que fallar el
umbral entero de nuevo.

`INBOX_ENABLED=false` procesa el hecho y **no deja la marca**. Es a propósito:
marcar sin deduplicar sería lo peor de los dos mundos, porque al volver a
encenderlo habría claves de hechos que nunca se comprobaron contra ellas y esos
hechos quedarían descartados para siempre.

### Migrar al arrancar

`DB_MIGRATE_ON_BOOT` viene **apagado** y en producción se deja así: las
migraciones las aplica un paso aparte (`entrypoint.sh migrar <servicio>`).

Encendido, cada servicio aplica las suyas al arrancar, **antes de instalar sus
guardianes, suscribirse al bus o lanzar sus barridos** —los tres tocan tablas— y
bajo un **cerrojo de aviso de Postgres**: si otra réplica está migrando, ésta la
espera y luego no encuentra nada pendiente, en vez de las dos corriendo el mismo
`CREATE TABLE`. Un fallo al migrar **no arranca el servicio**: uno que corre
contra un esquema que no es el que su código espera no está degradado, contesta
mal.

> Hasta el 6 de octubre de 2026 este ajuste no lo leía nadie: encenderlo no
> migraba nada, y el servicio arrancaba contra el esquema viejo. Se notaba en la
> primera consulta, como un «relation does not exist» sin contexto.

### Cifrado hacia el bus y la caché

| Ajuste | De fábrica | Qué hace |
|---|---|---|
| `BUS_TLS` | `false` | Exige que la URL del bus use un esquema cifrado |
| `CACHE_TLS` | `false` | Lo mismo con la de la caché |

**No reescriben la URL**: la conexión la sigue decidiendo ella. Lo que hacen es
exigir. Si declara `BUS_TLS=true` y la URL empieza por `redis://`, el arranque
se niega, y el mensaje dice las dos salidas: cambiar la URL a un esquema cifrado
(`rediss://`, `tls://`, `amqps://`…) o poner el ajuste a `false` si ese tramo va
en claro a propósito — el bus en la misma red privada es una decisión legítima.

Se comprueba en los **dos transportes del bus**, Redis y NATS: cerrar sólo uno
dejaría el otro abierto con el ajuste puesto, que es peor porque parecería
hecho. Y en la caché se comprueba **antes** de su caída a memoria: una URL en
claro cuando se ha exigido cifrado no es una caché caída, es una configuración
que miente.

Un esquema que no se reconozca **no se da por cifrado**. Dar por bueno lo que no
se reconoce es cómo una comprobación de seguridad deja de comprobar.

### Dónde se guardan los secretos de las integraciones

`SECRETOS_BACKEND` sólo admite **`db`**: los secretos se guardan cifrados en la
base, con la clave maestra y la del tenant. Configurar cualquier otro valor
**corta** al cifrar o descifrar, con el nombre del que ha puesto y la lista de
los que hay.

Corta, y no cae a `db` avisando, porque la diferencia importa: hasta el 6 de
octubre de 2026 poner `vault` guardaba los secretos en la base igualmente, y
quien lo pusiera creería que las credenciales de sus integraciones están en su
gestor externo cuando están aquí. Eso no es un ajuste decorativo: es una
creencia falsa sobre dónde están los secretos del cliente.

> `SECRETOS_VAULT_URL` ya no existe: sólo tenía sentido con un backend que no
> está. Cuando lo esté, su URL vuelve con él.

#### Qué quiere decir «vault segmentado»

No es una palabra del catálogo: es que **la clave que cifra las credenciales de
integración no abre los campos de cliente**, aunque las dos salgan de la misma
maestra. Cada propósito deriva la suya, y el propósito viaja además como dato
autenticado del cifrado. Comprobado el 26-10-2026 descifrando a propósito con la
clave equivocada: falla, no devuelve otra cosa.

La consecuencia práctica es la que importa el día malo: si se filtran las
credenciales de un conector —el subsistema más expuesto, porque sale a
internet—, eso **no** da acceso a los campos sensibles de los clientes.

Dos cosas más que se miden y que no se ven mirando la tabla:

- **El mismo secreto cifrado dos veces sale distinto.** Hay un nonce por valor,
  guardado con él. Si no lo hubiera, dos filas idénticas delatarían que la
  contraseña es la misma sin descifrar nada: quién comparte credencial con
  quién, y quién la cambió cuando se pidió y quién no.
- **Un byte alterado falla.** Se usa GCM y no CBC porque autentica. Sin
  autenticación, quien pueda escribir en la tabla cambia un valor cifrado por
  otro y el sistema se conecta a donde le digan: no da error, hace algo
  distinto, y eso no aparece en ningún registro.

### Región y aislamiento de los tenants nuevos

| Ajuste | De fábrica | Qué decide |
|---|---|---|
| `TENANT_DEFAULT_REGION` | `eu` | Dónde constan los datos de los tenants que se den de alta |
| `TENANT_DEFAULT_ISOLATION` | `pool` | `pool` (esquema compartido), `schema` (uno por tenant) o `silo` (base dedicada) |

Son valores **por defecto**, no un techo: el alta puede pedir otros, que es de lo
que trata el modelo híbrido por tiers.

> Hasta el 6 de octubre de 2026 estos dos no los leía nadie, y los valores
> estaban escritos a fuego en tres sitios. En el aislamiento eso era un ajuste
> decorativo; en la región, no: el valor se guarda en el tenant **para poder
> auditar dónde vive cada dato**, así que una instalación fuera de Europa daba de
> alta a todos sus clientes diciendo que sus datos están en Europa. **Si viene de
> una versión anterior, revise la región de los tenants ya creados**: lo que
> consta puede no ser donde están.

#### Declarar el aislamiento no es tenerlo: hay que comprobarlo

Un CRM multi-tenant se vende con una frase —«sus datos están aislados»— y lo que
pasa siempre es esto: se vende una base dedicada a un cliente grande, alguien
aprovisiona con la plantilla de siempre y el tenant acaba en el pool compartido.
**Funcionar funciona igual.** Se nota el día de la auditoría, o el día de la
incidencia, y entonces ya no hay forma de explicarlo.

Por eso hay dos pasos y no uno:

| Ruta | Qué hace |
|---|---|
| `POST /api/v1/aislamiento` | **Declara** la modalidad del tenant |
| `POST /api/v1/aislamiento/{tenant_id}/comprobar` | **Contrasta** lo declarado con la conexión real |
| `GET /api/v1/aislamiento/sin-comprobar` | Los que nadie ha contrastado últimamente |

Las modalidades, de menos a más: `compartido` (filas del mismo esquema,
separadas por RLS y por el guard del ORM), `esquema`, `base`, `cluster` y
`cliente` (la base la pone él, en su infraestructura). Las cinco son legítimas y
cada una tiene su coste. **Lo que no es legítimo es cobrar una y dar otra.**

Lo que la declaración obliga a decir:

- `base`, `cluster` y `cliente` exigen **en qué base**. Sin ese dato no se puede
  comprobar después si el tenant está donde se vendió.
- `esquema` exige cuál.
- `cliente` exige marcar `infraestructura_del_cliente`. Marcarlo cambia **de
  quién es la copia de seguridad y a quién se le pide el acceso** cuando hay una
  incidencia: una base del cliente sin marcar es una base que creemos nuestra el
  día que hay que restaurarla.

Y dos cosas que la comprobación hace y conviene saber:

- **Comprueba también que el aislamiento de abajo sigue puesto.** Si aparece una
  tabla con `tenant_id` y sin RLS, lo dice. Quitar RLS «porque ya está aislado»
  deja la protección dependiendo de que el aprovisionamiento no falle nunca.
- **Cambiar la declaración invalida la comprobación anterior.** Una comprobación
  que sobrevive al cambio de lo comprobado sigue diciendo que sí, en verde,
  sobre una declaración que ya no es la misma, y quien la mire se quedará
  tranquilo.

Un tier desconocido cae a `compartido`, que es lo que de verdad tiene:
inventarle `base` sería prometer por defecto lo que más cuesta.

#### Las cabeceras de identidad son del gateway, no del que llama

Entre el gateway y los servicios la identidad viaja en cabeceras `x-crm-*`
**firmadas**. Quien llama desde fuera puede mandarlas —nada se lo impide—, y no
le sirven de nada: el gateway **no reenvía** las que entran y pone las suyas
encima. Comprobado el 26-10-2026 mandando `x-crm-tenant` de otra empresa,
`x-crm-permisos: *` y `x-crm-plataforma: 1`: lo que llega al servicio de detrás
es lo que el gateway resolvió.

La contrapartida, dicha en claro y ya escrita arriba: **los servicios internos no
pueden ser alcanzables desde fuera**. La firma lo impide sin el secreto, pero el
despliegue tiene que mantenerlos en red interna. No es opcional.

Y la resolución del tenant tiene dos clases de vía que conviene no confundir:

| Vía | Qué es |
|---|---|
| `tenant` dentro del JWT | **Autoritativa**: va firmada |
| La clave de API | **Autoritativa**: pertenece a un tenant concreto en la base |
| La cabecera `X-Tenant` | Pista de enrutado, **no concede nada** |
| El subdominio | Pista de enrutado, **no concede nada** |

Si llega una pista y además hay identidad autoritativa, tienen que coincidir. Sin
esa comprobación bastaría cambiar una cabecera para operar sobre otro tenant con
un token legítimo, que es la vía más barata que existe para saltarse el
aislamiento: no hace falta robar nada, sólo escribir otro nombre. El rechazo es
escueto a propósito — decir «ese tenant existe pero no es el tuyo» ya es decir de
más.

### El alta de un tenant: por API o por autoservicio (CRM-00.01.03.01)

`POST /tenants` exige administrador de la plataforma. Es la vía normal en un
despliegue empresarial, donde los clientes se dan de alta desde la consola.

**El alta autoservicio va apagada de fábrica** y se enciende con
`ONBOARDING_ENABLED`. Encendida, abre dos rutas **sin autenticar** —quien da de
alta su empresa todavía no tiene cuenta aquí—:

| Ruta | Qué hace |
|---|---|
| `POST /alta` | Guarda la solicitud y devuelve el token del enlace de confirmación. **No crea nada** |
| `POST /alta/confirmar` | Gasta el token, crea la empresa y emite el hecho con el que se crea su primer administrador |

Cómo está cerrada, punto por punto:

- **Nada existe hasta que alguien demuestra que ese buzón es suyo.** Pedir el
  alta no crea la empresa: crear primero dejaría el sistema lleno de empresas a
  medias con los identificadores buenos cogidos, y un identificador es
  permanente — va en subdominios y en URLs.
- **La respuesta no dice si el identificador estaba libre.** Si lo dijera, esa
  pantalla sería un comprobador de qué empresas son clientes: se prueba un
  nombre, se mira la respuesta y ya se sabe. El choque se anota en el log, para
  quien vigila la instalación. La *forma* del identificador sí se dice, porque
  no depende de lo que haya en la base y callarla deja a alguien escribiendo
  mayúsculas sin saber por qué no le llega nunca el correo.
- **El enlace vale una vez y caduca** (`ONBOARDING_ENLACE_HORAS`, 24 h por
  defecto). Uno que valiera siempre sería una credencial permanente en un buzón.
  El token se guarda **hasheado**: quien lea la base no puede confirmar un alta
  ajena.
- **El identificador se vuelve a comprobar al confirmar.** Entre pedir y
  confirmar pasan horas y puede habérselo llevado otro; fiarse de lo anotado
  daría dos empresas con el mismo subdominio.
- **Tope por IP** (`ONBOARDING_ALTAS_POR_IP_HORA`, 5 por defecto), muy por
  debajo del límite general de la API: esto crea tenants, y con el número de una
  lectura cualquiera se llenaría el sistema de empresas inventadas desde un
  portátil. Es una barrera contra el abuso casual; contra un ataque distribuido
  está el balanceador.
- **Las solicitudes se olvidan** a los `ONBOARDING_RETENCION_DIAS` (30), usadas
  o no: son correos de gente que nunca llegó a ser cliente, y eso es dato
  personal que no hay motivo para guardar.

**El primer administrador no se crea en esa llamada.** Los usuarios son del
servicio de identidad y los servicios no se llaman entre sí: al confirmar se
emite `tenant.alta_confirmada` y él lo recoge. Atar el alta a que el otro
servicio esté en pie en ese segundo exacto es el peor momento para que falle —
la persona está mirando la pantalla.

Y **no se le inventa una contraseña**: se crea la cuenta sin ninguna y se emite
un enlace de los de siempre para que la ponga él. Mandar una generada por correo
es ponerla en un buzón y en los registros del servidor de correo, y además nadie
la cambia después.

> El token de confirmación **se devuelve en la respuesta**, igual que en el
> restablecimiento de contraseña: lo manda quien integre el correo. Nunca se le
> enseña a quien pide el alta — el enlace es precisamente la prueba de que el
> buzón es suyo.

### La zona horaria de un tenant nuevo

Al dar de alta un tenant, su zona horaria, su idioma y su moneda se llevan a los
ajustes en el mismo momento. Hace falta porque los cálculos de fecha leen el
**ajuste** (`rt.efectivo("zona_horaria")`), no la ficha del tenant: el ajuste
tiene su propia cadena —usuario → unidad → tenant → global— y un usuario puede
tener el suyo.

> Hasta el 7 de octubre de 2026 esa propagación la hacía **sólo la pantalla de
> editar**. Un tenant recién creado tenía su zona en la ficha y no en los
> ajustes, así que sus fechas se calculaban en UTC hasta que alguien abriera el
> perfil y guardara — algo que en la mayoría de las implantaciones no pasa nunca.
>
> Lo que eso cambia no es cosmético. En Madrid, entre medianoche y las dos de la
> mañana, «hoy» era ayer: un presupuesto caducaba un día antes de lo que decía la
> pantalla, una compartición dejaba de dar acceso un día antes y una pertenencia
> a un equipo también. En Auckland eran trece horas al día.
>
> **Si viene de una versión anterior**, revise los tenants creados antes de esa
> fecha: abrir su perfil y guardar propaga la zona. Se nota en que las fechas del
> sistema coinciden con las del cliente a primera hora de la mañana.

### El aviso de que un tenant se acerca a un tope

Lo emite el barrido del núcleo —en todos los servicios, cada
`TAREA_PURGAS_INTERVALO_S`— como el evento **`quota.threshold.reached`**, que
estaba en el contrato publicado desde el principio. Lleva el tope del que habla,
lo consumido, el límite, el porcentaje y el periodo.

El umbral es `QUOTA_AVISO_PCT` (80 % de fábrica) y se puede cambiar en caliente
por tenant: lo que es «cerca» para uno con mil registros no lo es para uno con
un millón.

**Una vez por métrica y periodo.** El barrido vuelve a ver al tenant por encima
del umbral en cada vuelta, pero la clave de deduplicación lleva el periodo, así
que el consumidor descarta las repeticiones. Se paga en filas de la tabla de
salida y se gana no tener otra tabla con a quién se avisó ya, que es un sitio más
donde quedarse desincronizado.

Cada servicio emite lo que **él** mide: los medidores de consumo se registran por
proceso y cada uno mide sobre su propio esquema. Un emisor central tendría que
leer las tablas de los catorce.

> Hasta el 11 de octubre de 2026 este evento no lo emitía nadie. El cálculo
> existía —`aviso_de_cercania`— y viajaba como un campo más del panel de
> consumo, así que el aviso sólo existía si alguien abría la pantalla; y quien se
> hubiera suscrito al evento no recibía nada. **Si tiene integraciones escuchando
> cuotas, revíselas**: ahora empezarán a recibir.

## Copias de seguridad

Lo que hay que copiar, y por qué:

| Qué | Por qué |
|---|---|
| Postgres (todos los esquemas) | Es el sistema entero: datos, configuración, auditoría y estado de los procesos |
| Volumen de NATS | Los eventos aún no entregados |
| Almacén de ficheros (S3 o disco) | Los adjuntos no están en la base: una copia de Postgres no los trae |
| `.env` / gestor de secretos | Sin `ENCRYPTION_KEY` **los datos cifrados no se recuperan**, por muy buena que sea la copia de la base |

Ese último punto es el que más veces se descubre tarde: una copia de la base sin
la clave de cifrado es una copia de la que no se puede restaurar lo sensible. Por
eso el script **no** copia la clave, y lo dice en el manifiesto: una copia de la
base junto a la clave que la descifra es un solo fichero que lo entrega todo.

### Hacerlas y, sobre todo, verificarlas (CRM-00.06.02.01)

```bash
python scripts/respaldar.py copiar    --destino /var/backups/contecrm
python scripts/respaldar.py verificar /var/backups/contecrm/2026-09-19T03-00
python scripts/respaldar.py listar    --destino /var/backups/contecrm
```

**Una copia que no se ha restaurado nunca no es una copia: es un fichero.** Por
eso `verificar` no comprueba el hash y se queda ahí — eso solo demuestra que el
fichero no se ha estropeado. Lo **restaura de verdad** sobre una base efímera,
cuenta las tablas, cuenta filas y **mide cuánto ha tardado**. Ese número es el
RTO real de esta copia y de esta máquina; un RTO escrito en un contrato sin
haberlo medido nunca es una cifra inventada.

`listar` dice cuántos minutos hace de la última copia, que es el **RPO actual**:
los datos que se perderían si la base se fuera ahora mismo.

Al escribir esto, el propio verificador tenía un fallo que lo hacía inútil:
aceptaba el código de salida de `pg_restore` sin mirarlo, así que con una opción
mal escrita el restore no hacía nada y la verificación lo daba por bueno. Ahora
el código de salida se informa pero **no decide**: lo que decide es que haya
tablas y que tengan filas.

## Compromisos de servicio: RPO, RTO y disponibilidad (CRM-08.02.01.01, CRM-08.02.01.02)

Están en la **configuración**, no en un documento: un compromiso que solo vive en
un PDF no lo comprueba nadie. Aquí los lee el sistema y los publica la API, así
que el número que se le enseña al cliente es el mismo que se vigila.

| Tier | RPO | RTO | Disponibilidad | Parada al mes |
|---|---|---|---|---|
| Estándar | 24 h | 8 h | 99,5 % | 3 h 39 min |
| Premium | 4 h | 2 h | 99,9 % | 43 min |
| Enterprise | 15 min | 30 min | 99,95 % | 21 min |

Los valores por defecto son **deliberadamente conservadores**. Un RPO de quince
minutos exige archivado continuo del WAL: si esa infraestructura no está montada,
el número es una promesa que se incumple el día que hace falta. Subirlos es una
decisión de negocio con coste, y así es como debe tomarse.

Lo mismo con la disponibilidad: prometer 99,99 % son cuatro minutos de parada al
mes, y eso exige multi-región activo-activo. Sin eso montado, el número es falso.

## Alertas y qué hacer con ellas (CRM-00.06.01.05)

Las reglas están en `ops/prometheus/alertas.yml` y **cada una enlaza su
runbook** (`docs/runbooks/`). No es una convención: hay un gate
(`tests/unit/test_alertas_con_runbook.py`) que falla si una alerta apunta a un
runbook que no existe, si un runbook queda huérfano, si a una alerta le falta la
gravedad o el `for`, o si vigila una métrica que el código no publica — que es el
fallo más silencioso de todos, porque parece que hay cobertura y no la hay.

Una alerta sin instrucciones despierta a alguien a las tres de la mañana para que
averigüe desde cero qué significa. Lo que pasa después, siempre, es que se
silencia — y una alerta silenciada deja el sistema peor que si no existiera,
porque ahora además hay quien cree que está cubierto.

Los runbooks siguen todos la misma estructura, y el orden es parte del gate:
**qué significa** (quien lo abre de madrugada no tiene contexto), **cuánto
corre**, **qué mirar** y **qué hacer**. Diagnóstico antes que acción: la mitad de
los incidentes se empeoran actuando sobre el síntoma equivocado.

Dos rutas de aviso y no cinco: lo crítico despierta a alguien, lo demás espera a
la mañana. Una escala de cinco niveles obliga a decidir en cada alerta cuál es, y
ante la duda se acaba poniendo el intermedio, que ni despierta ni se revisa.

## Volumetría: qué aguanta esto (CRM-08.01.01.03, CRM-08.01.01.05)

Medida, no estimada (`docs/volumetria.json`):

```bash
python scripts/medir_volumetria.py --cuentas 50000
```

Sobre 20.000 cuentas, en un portátil arm64 con Postgres embebido:

| Qué | Medido |
|---|---|
| Alta de cuentas por lotes | 23.000 /s |
| Indexado para búsqueda | 970 /s |
| Búsqueda de texto (mediana / p95) | 2,8 / 3,3 ms |
| Listado paginado con filtro (mediana / p95) | 3,1 / 3,6 ms |
| Tamaño de la base | 31 MB |

**Son un suelo comparable entre versiones, no una promesa de capacidad.** No hay
red, ni concurrencia real, ni el coste del gateway. Sirven para responder «¿esto
ha empeorado?», que es la pregunta que se puede contestar con honestidad sin un
entorno de carga dedicado.

Y la medición ya sirvió para encontrar algo: la búsqueda tardaba **81 ms** en vez
de 2,8. No era el índice —se comprobó con `EXPLAIN` que sí se usaba—, eran las
**estadísticas sin actualizar** tras la carga masiva: el planificador creía que
la tabla estaba vacía. Treinta veces más lento por eso. Ahora la importación
masiva hace `ANALYZE` al terminar, porque autovacuum acabaría haciéndolo pero
puede tardar minutos — los mismos minutos en los que quien acaba de importar
concluye que el sistema no aguanta su volumen.

## Ventanas de mantenimiento (CRM-08.02.01.03)

El estado `solo_lectura` de un tenant existe justo para esto: permite mantener
—una migración larga, una reindexación— sin cortar el servicio. Quien consulta
sigue trabajando; quien escribe recibe un 409 que **dice qué pasa y hasta
cuándo**, en vez de un error genérico.

Se pone y se quita por API, con motivo obligatorio, y queda auditado:

```bash
curl -X POST .../api/v1/tenants/<id>/estado \
  -d '{"nuevo":"solo_lectura","motivo":"Migración del índice, hasta las 06:00"}'
```

Lo normal es que no haga falta cortar nada: las migraciones son por servicio y se
aplican por separado, y los despliegues no exigen parar la pila entera.

## Rotar la clave de cifrado

```bash
ENCRYPTION_KEY_PREVIA=<la que había>
ENCRYPTION_KEY=<la nueva>
```

Con las dos puestas, lo escrito con la anterior se sigue descifrando mientras se
recifra. Sin esa convivencia, rotar exigiría una ventana de parada.

## Política de soporte y gestión de versiones (CRM-08.02.01.04, CRM-07.02.01.08)

Lo que un cliente tiene derecho a esperar, escrito antes de que lo pregunte.

### Niveles y tiempos de respuesta

| Gravedad | Qué es | Respuesta | Horario |
|---|---|---|---|
| **Crítica** | El servicio no está disponible, o hay riesgo de pérdida de datos | 1 h | 24×7 |
| **Alta** | Una función principal no funciona y no hay forma de rodearla | 4 h laborables | Horario laboral |
| **Media** | Algo falla pero hay manera de seguir trabajando | 1 día laborable | Horario laboral |
| **Baja** | Consulta, mejora, cosmética | 3 días laborables | Horario laboral |

«Respuesta» es **respuesta**, no resolución. Prometer un plazo de resolución para
un fallo que aún no se ha diagnosticado es prometer lo que no se sabe: lo honesto
es comprometerse a que alguien lo esté mirando, y a decir qué se sabe y cuándo se
volverá a informar.

La gravedad la propone quien abre el caso y la confirma quien lo atiende. Si no
coinciden, manda la más alta hasta que se aclare: discutir la gravedad de algo
que está caído es la peor forma de empezar.

### Escalado

Si no hay respuesta en el plazo, el caso sube solo: responsable de soporte →
responsable técnico → dirección. El escalado es **automático por tiempo**, no
por insistencia del cliente — depender de que alguien se queje fuerte premia a
quien más ruido hace, no a quien peor lo está pasando.

### Versiones del proveedor

| | Qué |
|---|---|
| **Cadencia** | Una versión menor al mes; correcciones cuando hagan falta |
| **Aviso** | 15 días naturales antes de una versión menor; inmediato para una corrección de seguridad |
| **Previsualización** | La versión está disponible en el entorno de pruebas del cliente **antes** de llegar a producción |
| **Compatibilidad** | La API `v1` no rompe. Un campo se puede añadir; quitarlo o cambiarle el tipo exige `v2` conviviendo con `v1` |
| **Retirada** | Un endpoint deprecado sigue vivo **12 meses** y responde con la cabecera `Sunset` |
| **Vuelta atrás** | Toda versión se puede revertir. Una migración que no se pueda revertir sin pérdida se anuncia como tal, aparte |

La previsualización no es un extra: es lo que convierte «hemos actualizado y se
ha roto algo» en «lo vimos en pruebas la semana pasada». Sin ella, cada versión
del proveedor es un riesgo que asume el cliente sin poder medirlo.

## Cumplimiento: qué se puede demostrar y qué no (CRM-00.01.05.05)

Esta tabla es deliberadamente incómoda. Un cuadro de cumplimiento donde todo está
en verde no lo cree nadie, y con razón.

| Marco | Qué aporta el producto | Qué **no** aporta |
|---|---|---|
| **RGPD** | Base legal y consentimiento por finalidad y canal, derechos del interesado con plazos, retención configurable, borrado y exportación, registro de tratamientos, cifrado de campo, auditoría inmutable | El RAT completo y el análisis de impacto son del responsable del tratamiento, no del software |
| **ENS** | Trazabilidad, control de acceso, cifrado, copias verificadas, segregación por tenant | La categorización del sistema y la declaración de aplicabilidad son de la organización que lo despliega |
| **ISO 27001** | Controles técnicos: acceso, registro, cifrado, copias, gestión de vulnerabilidades por dependencias fijadas | El SGSI —políticas, formación, auditoría interna— no es un producto |
| **SOC 2 Tipo II** | Evidencia técnica: auditoría encadenada, control de cambios por migraciones, alertas con runbook | El informe lo emite un auditor sobre un periodo observado; el producto aporta las evidencias |

La diferencia entre **cumplir** y **poder demostrar que se cumple** es donde se
caen la mayoría de los proyectos. Aquí se ha construido pensando en lo segundo:
la cadena de auditoría se verifica sola, las copias se restauran de verdad, las
alertas llevan instrucciones y el catálogo dice el estado real de cada capacidad
con una prueba que lo respalda.

Lo que ninguna de esas cuatro cosas da es una certificación. La certificación la
obtiene la organización que despliega, con este producto dentro de su alcance.

## Conectores como manifiestos, y catálogo instalable (`CRM-00.03.04.01`, `CRM-00.03.04.10`, `CRM-07.02.01.09`)

«Conectores nativos para ERP, facturación, firma, telefonía y mensajería» suele
significar un módulo de código por cada casa. Eso es lo que hace que la lista de
integraciones envejezca: cada proveedor cambia su API y hay que desplegar para
seguirle.

Aquí un conector **es un manifiesto**: declara qué operaciones tiene, qué
credenciales pide, a qué dominios llama y cómo mapea sus campos. El motor es el
declarativo de siempre. Añadir un ERP nuevo no es escribir código, es publicar un
documento.

**Se valida al publicarlo.** Un mapeo con un campo mal escrito falla dentro de un
proceso nocturno tres semanas después, y el error que aparece no se parece a la
causa. Y se valida **todo de golpe**: quien escribe un manifiesto de veinte
operaciones no puede descubrir los errores de uno en uno.

**Se versiona, y lo instalado no cambia solo.** Un tenant con la versión 3 sigue
con la 3 aunque se publique la 4: actualizar automáticamente cambiaría una
integración de producción sin que nadie lo decida, y eso es que algo que
funcionaba deja de funcionar un martes sin ningún despliegue de por medio.
Publicar una versión nueva **exige decir qué cambia**, porque quien decide si
actualiza no puede hacerlo a ciegas.

**Lo que pide se enseña antes de instalar**: credenciales y dominios. Instalar y
descubrir después que hace falta un certificado que tarda dos semanas es el final
de esa integración; y descubrir a dónde manda los datos mirando el tráfico llega
tarde.

Instalar devuelve **qué credenciales faltan** en vez de fallar —instalar y
configurar son dos momentos distintos— pero no da la integración por operativa: la
pantalla puede decir «esta no va a funcionar todavía» sin tener que probarla.

Retirar una versión **no rompe lo instalado**, y dice a cuántos tenants afecta. Y
desinstalar **deja los datos ya traídos**: son de la empresa, no del conector que
los trajo.

## Transportes heredados: SOAP, SFTP, ficheros planos, EDI y AMQP (`CRM-00.03.04.03`)

El conector declarativo resolvió las integraciones modernas, que son HTTP con
JSON. Lo que queda es lo que paga las facturas: el ERP que solo habla SOAP, el
mayorista que deja un fichero en un SFTP a las 3:00, el operador logístico que
manda EDIFACT y la fábrica que publica en una cola.

**Ficheros planos sin adivinar el formato.** Separador, columnas y anchos se
declaran. Detectarlo automáticamente funciona el 95 % de las veces, y el 5 %
restante son cargas que entran mal **sin fallar**, que es la peor forma de fallar
que hay. Una línea rota no tumba el fichero: se cuenta y se sigue, porque un
fichero de 50.000 pedidos no se descarta entero por uno malo.

**EDI se parte, no se interpreta.** Se devuelven los segmentos con sus elementos;
traducir aquí un ORDERS a un pedido metería el vocabulario de un sector en el
núcleo. Esa traducción es del adaptador canónico, que existe para eso. Y si el fin
de segmento declarado **no aparece** en el mensaje, se avisa: sin eso, el mensaje
entero sale como un único segmento con un nombre absurdo y sin ningún error.

**SOAP sin generar código por servicio.** El sobre y el cuerpo se declaran; un
WSDL completo obligaría a generar un cliente por cada servicio, que es justo lo
que este proyecto evita. Dos comprobaciones que no son opcionales: el **Fault**
—que llega con HTTP 200 en muchísimos servicios, y sin mirarlo un error se procesa
como cero filas—, y que la respuesta **sea un sobre SOAP**: una página de error de
un proxy es XML perfectamente formado y pasaría por respuesta vacía.

**SFTP no acepta cualquier host.** Sin la huella declarada, la conexión se
rechaza: aceptar la clave que venga es abrir la puerta a que alguien se ponga en
medio del canal por el que viaja el maestro de clientes. Lo comprueban **las
tres** operaciones —listar, descargar y archivar— desde el 04-10-2026: hasta
entonces archivar aceptaba la clave que viniera, así que listar y descargar
exigían la huella y mover el fichero ya procesado se la saltaba.

Y el fichero **no se borra al leerlo**: se archiva después, porque media
integración heredada se pierde cuando el proceso falla tras borrar el origen y
el mayorista no lo vuelve a mandar.

### Un fichero a medio escribir no se procesa nunca

Se rechaza y se vuelve a intentar. Nunca se procesa lo que se haya alcanzado a
leer: un fichero de movimientos truncado a la mitad importado como si estuviera
entero es peor que no importarlo, porque **parece que fue bien** y no se
descubre hasta que alguien cuadra las cuentas.

Se mira de dos formas, y las dos hacen falta porque no valen lo mismo:

- **El nombre lo dice** (`.part`, `.tmp`, o subir con otro nombre y renombrar al
  acabar). Es la única fiable de verdad, pero depende de que quien escribe lo
  haga así: es un **acuerdo con el cliente**, no una capacidad nuestra. Los
  patrones se configuran en `SFTP_PATRON_EN_CURSO`.
- **El tamaño cambia entre dos miradas**, separadas por
  `SFTP_ESPERA_ESTABILIDAD_S`. Funciona contra cualquier servidor y no necesita
  acuerdo, pero **falla si quien escribe pausa más que la espera** — por eso la
  espera se configura y por eso no se usa sola.

Y se vuelve a mirar **después** de leer: si el fichero ha cambiado mientras se
leía, o lo leído no cuadra con el tamaño, se descarta entero y se empieza de
cero en la pasada siguiente.

Los intentos se cuentan. A partir de `SFTP_INTENTOS_PARA_AVISAR` se avisa como
error, porque un fichero que nunca termina de escribirse se reintentaría cada
pasada para siempre sin que nadie lo supiera. El contador lo guarda quien hace
la pasada: en memoria se pierde al reiniciar, y entonces un fichero atascado
desde hace tres días vuelve a empezar de cero y el aviso no salta nunca.

**Lo que falta, dicho claro:** no hay todavía ningún barrido que ejecute estos
transportes. Medido el 04-10-2026, los cinco —SOAP, SFTP, ficheros, EDI y
AMQP— están registrados y **nadie los ejecuta**: el registro solo se escribe y
se lista. La pieza que recoge de un SFTP respetando todo lo de arriba existe y
está probada (`recoger_de_sftp`); lo que falta es decidir cada cuánto se pasa,
con qué configuración y dónde van los resultados.

**AMQP publica persistente por defecto** y confirma **tras procesar**: confirmar al
recibir perdería el mensaje en un fallo posterior sin que nadie se enterara.

## Exposición a agentes de IA (`CRM-00.03.04.11`)

Un agente que puede leer y escribir en el CRM es útil y peligroso por lo mismo:
hace en un segundo lo que una persona tardaría una tarde.

**El agente tiene su propio principal.** Actuar «en nombre de» heredando permisos
convierte cualquier fallo del agente en un fallo con los permisos del jefe. El
catálogo de herramientas que ve cada agente sale de cruzar lo publicado con lo que
**su** principal puede: enseñarle todo y fallar al invocar le hace gastar llamadas
—y dinero— en lo que no puede hacer, y peor, intentar rodearlo.

**Lo que escribe pasa por donde pasa lo de una persona.** Las herramientas de
escritura emiten un **comando** al servicio dueño, que aplica sus reglas. La
respuesta dice «pedido», no «hecho». Y una herramienta de escritura puede exigir
**confirmación humana**: el agente prepara y alguien firma.

**Cuota e interruptor.** Un agente sin cuota es una factura sorpresa; un agente sin
interruptor obliga a revocar roles mientras sigue llamando. El orden de las
comprobaciones es interruptor, permiso, cuota y parámetros — la cuota antes de
validar porque un agente en bucle manda miles de llamadas y validar cada una
cuesta más que rechazarla.

Y todo queda contado. Los **rechazos** importan tanto como las ejecuciones: muchos
por permisos significan que lo publicado y lo que el agente puede no coinciden, y
eso se arregla configurando, no reintentando.

## Canales sin interfaz y registro automático de interacciones (`CRM-00.02.03.09`, `CRM-01.02.01.04`)

Un CRM headless tiene que poder usarse **sin abrirlo**: se contesta un correo, se
cuelga una llamada, se cierra una reunión, y eso queda registrado sin que nadie
teclee. Si registrarlo cuesta un minuto por interacción, no se registra — y un CRM
sin interacciones es una agenda cara.

**Todos los canales entran por el mismo sitio.** Correo, SMS, voz, chat, CLI,
calendario o un agente: cambia el sobre, no el camino. Un camino por canal acaba
con cuatro sitios donde se crea una actividad y solo uno aplicando las reglas.

**Idempotencia por el identificador del canal.** El proveedor de correo reintenta,
la centralita reenvía el CDR y el calendario manda el mismo evento cada vez que
alguien lo toca; sin esto, una reunión sale cuatro veces en la ficha.

**Lo que no se puede atribuir se queda visible.** Un correo de una dirección
desconocida es un contacto que falta, no basura: se guarda sin atribuir y se
cuenta —con los interlocutores más frecuentes primero, que es por donde hay que
empezar—. Descartarlo hace que la ficha del cliente parezca tranquila cuando lo
que pasa es que escribe desde otro correo.

**Registrar no es leer.** Se guarda que hubo una llamada o un correo, con quién y
cuándo; el contenido **solo si el canal lo declara**. Volcar el buzón dentro del
CRM multiplica el dato personal y la superficie que hay que proteger para algo que
casi nadie vuelve a leer.

Lo que se crea con ello —actividad, caso o lead— lo crea el servicio dueño por
comando, y solo si se pudo atribuir: una actividad colgando de nadie no la ve
nadie.

## Datos externos sin replicar, y CRM embebido (`CRM-01.01.05.04`, `CRM-00.02.03.10`)

Hay datos que no deben copiarse: el saldo del cliente, su riesgo, sus facturas. No
porque no quepan, sino porque copiarlos crea una segunda verdad que envejece — la
ficha dice que debe 3.000 € y la realidad son cero desde ayer, y alguien llama a
reclamar a quien ya pagó.

**Si el sistema externo no contesta, se dice.** `disponible: false` con el porqué,
nunca un hueco ni un cero: un saldo vacío se lee como «no debe nada». Y el porqué
llega hasta la pantalla, porque «no se ha podido consultar» a secas manda a abrir
un ticket que nadie sabe diagnosticar.

**Tiempo máximo y caché corta, con la edad visible.** Una ficha no puede tardar
seis segundos porque el ERP va lento. Y un dato de hace diez minutos presentado
como actual es el mismo problema que copiarlo: por eso cada bloque dice si viene
de caché y cuántos segundos tiene.

**Lo federado no se puede filtrar ni ordenar**, y se dice en voz alta: para buscar
«clientes con saldo > 1.000» habría que traer todos los saldos, y eso es replicar
con otro nombre.

Para el **CRM embebido** dentro del ERP o del portal, la lista de orígenes es
obligatoria y en https: sin ella, cualquier página podría incrustarlo y pedir
datos con la sesión de quien la abra. Un origen no admitido se rechaza **sin decir
cuáles valen** — decirlo sería indicarle a quien prueba dónde ponerse. Y si el
anfitrión no manda el contexto declarado, se dice qué falta: un CRM embebido que
enseña la pantalla de inicio en vez del cliente que el usuario tiene delante no
sirve para nada.

## Convivencia con el CRM heredado: strangler (`CRM-00.03.01.07`)

Nadie apaga su CRM un viernes y enciende otro el lunes. La migración dura meses y
durante esos meses los dos sistemas están vivos. Lo único que evita el caos es que
**en todo momento se sepa quién manda sobre cada objeto**.

**El dueño se declara por objeto y por criterio**, no por sistema entero: «las
cuentas ya son nuestras, los pedidos siguen siendo del viejo» es la situación
normal durante meses, y «los clientes nuevos aquí, los antiguos allí» es como se
migra de verdad. Se usa la gramática de condiciones de siempre.

**Sin ninguna regla declarada manda el heredado.** Es el valor seguro: equivocarse
hacia el viejo produce un dato que hay que traer; hacia el nuevo, dos verdades. Y
se devuelve siempre **el porqué**, porque «¿por qué este pedido no me deja
editarlo?» es la pregunta de cada día, y sin respuesta la gente lo edita en el
sistema viejo por si acaso — que es como se duplica todo.

**Doble escritura solo con un dueño declarado.** Si nadie manda, cuando los dos
cambien el mismo dato se decidirá por orden de llegada, que es perder información
sin que nadie se entere.

**Se mide lo que queda.** Un strangler sin medida no termina: se queda años «en
migración» porque nadie sabe cuánto falta. Los números los trae quien migra —
contarlos en el sistema viejo exigiría leer su base de datos, que es justo lo que
este patrón evita—, y la **edad de la medida va delante**: una de hace tres meses
presentada como actual hace creer que va bien. Los objetos con regla y sin ninguna
medida se señalan aparte: son los que hacen que la migración no acabe nunca.

Y dar un objeto por migrado **con registros aún en el viejo** exige forzarlo con
motivo: cerrarlo dejaría fuera lo que queda allí, y nadie volvería a mirarlo
porque ya constaría migrado.

## Un campo que se edita hasta cierto punto (`CRM-00.04.03.13`)

`solo_lectura` era una marca fija: o el campo se puede tocar siempre, o no se
puede tocar nunca. Con eso hay que elegir entre dejar que alguien cambie lo ya
firmado o impedir que nadie corrija una errata antes de firmar. Ahora hay tres
puertas, de la más fija a la más fina, y la primera que cierra manda:

1. **La marca de siempre.** El campo lo rellena el sistema —calculado, de una
   fórmula— y no se edita a mano desde ningún sitio.
2. **Por condición**, con el registro delante: *el importe se edita mientras la
   oportunidad está abierta y deja de editarse al cerrarla*. Se declara con el
   mismo lenguaje que las condiciones de visibilidad del diseñador
   (`{campo, operador, valor}`) porque es la misma pregunta, y tienen que
   cumplirse **todas**: con «cualquiera», un campo se cerraría en cuanto una
   condición suelta se diera y nadie entendería por qué.
3. **Por procedencia**: *el NIF lo mantiene el ERP*. Lo escribe la integración
   que lo trae y no una persona — si lo tocara una persona, la siguiente
   sincronización le pisaría el cambio y lo que vería es que «no se guarda»,
   sin ningún error que lo explique. Eso es peor que un rechazo: parece que el
   sistema pierde datos.

**Una lista de procedencias vacía significa «cualquiera», no «ninguna».** Es la
trampa de la columna nueva: el día que se añade, todos los campos la tienen
vacía, y con la lectura contraria la propia migración habría dejado el modelo
entero de solo lectura para todo el mundo.

El motivo viaja **con** el bloqueo: «no se puede modificar» a secas manda a
preguntar, y la respuesta siempre es una de las tres. Y la pantalla lo consulta
en la misma llamada que la visibilidad, porque es la misma pregunta —«¿qué
puedo hacer con este registro delante?»— y partirla en dos obligaría a pedir
dos veces y a quedarse a medias si una falla. Quien decide sigue siendo la
validación al guardar; lo que hace la pantalla es no ofrecer lo que el servidor
va a rechazar.

## Fechas que no son un día (`CRM-00.04.01.12`)

Un hito que es «marzo de 2027» no es el 1 de marzo de 2027, y guardarlo como un
día inventado se paga dos veces: el informe cuenta vencimientos el día 1 de cada
mes y alguien llama al cliente preguntando por algo que no había prometido para
ese día; y quien escribe «Q3» y ve «1 de julio» aprende que el sistema se
inventa cosas y deja de fiarse de lo que lee.

Un campo de fecha declara su granularidad —`dia`, `mes` o `trimestre`— en sus
restricciones, y el valor se normaliza al **primer día de su periodo**. Dos
decisiones que importan:

- **Se declara en el campo, no se adivina del valor.** Adivinarla haría que un
  1 de marzo escrito a propósito se leyera como «marzo».
- **Se normaliza al guardar, no al pintar.** Si cada pantalla recortara por su
  cuenta, dos vistas del mismo dato dirían cosas distintas, y una consulta por
  rango incluiría o excluiría el registro según el día que se tecleó.

Una granularidad desconocida se rechaza: guardarla sin comprobar dejaría un
campo que dice «por semanas» y se comporta como si fuera por días.

## El código que la gente dice por teléfono (`CRM-00.04.01.11`)

Un identificador opaco es lo correcto para la máquina —no se adivina, no se
enumera, no se agota— y **no sirve para lo que la gente hace con él**: decirlo
por teléfono, escribirlo en un correo, buscarlo en la hoja de cálculo que le
mandó el cliente. Por eso al lado va un código de negocio: corto, legible y
correlativo.

**Lo que había contaba filas, y sólo para oportunidades.** Contar falla de tres
maneras, y las tres pasan:

- si se borra un registro, el siguiente **repite** número — y ese número puede
  estar impreso en una oferta;
- si dos altas entran a la vez piden el mismo, y la restricción única convierte
  el alta en un error que el usuario no entiende;
- si alguien carga histórico con códigos propios, el recuento no tiene nada que
  ver con el último emitido.

Ahora hay un contador de verdad, por objeto, **bajo cerrojo de fila**, y guarda
el último emitido (no el siguiente: así un contador recién creado vale cero y no
hay que decidir en dos sitios si el primero es el 0 o el 1).

**El patrón es configuración.** `OPP-2026-00123` es una convención, no una ley:
hay clientes que numeran por delegación, otros sin año y otros que arrastran el
formato del sistema del que vienen — y tiene que seguir siendo el mismo para que
sus referencias de veinte años no se queden huérfanas. Se declaran el patrón
(`{objeto}`, `{anio}`, `{anio_corto}`, `{mes}`, `{secuencia}`), el relleno y
cuándo reinicia.

**Lo que no se deja hacer, que es lo importante:**

- un patrón **sin `{secuencia}`** daría el mismo código a todos los registros, y
  lo que se vería es «no se puede crear», no «falta el número»;
- reiniciar cada año **sin el año en el patrón** repite los códigos el 1 de
  enero; y llevar el año **sin reiniciar** saca el año nuevo con el número
  viejo, que no es lo que nadie espera;
- **bajar el contador** repetiría códigos ya emitidos. Es la única forma de
  hacer daño desde esa pantalla, y está cerrada.

Todo eso se comprueba **al guardar la numeración**, no al emitir: descubrirlo al
emitir es descubrirlo con un registro a medio crear y delante de quien no la
escribió.

Para llegar de otro sistema está `empezar_en`: el último código ya emitido. Sin
él, el primer registro del CRM repetiría uno que el cliente tiene impreso en un
albarán. Y un objeto sin numeración declarada **no es un error**: devuelve nada
y el alta sigue. Que reventara obligaría a declarar numeración para todo antes
de poder dar de alta la primera cosa.

## Workers dedicados por cliente (`CRM-00.01.01.06`)

Se vende cómputo aislado: que el trabajo pesado de un cliente no caiga en los
mismos procesos que el de todos los demás. **Y hasta hoy era sólo un campo.**
`pool_computo` estaba en la migración, en el modelo, en el parámetro con el que
se declara el aislamiento y en la respuesta de la API — se podía declarar, se
veía en pantalla, y el barrido de tareas recorría todos los tenants igual.

Ahora un proceso arrancado con `POOL_COMPUTO=acme` sólo atiende a los tenants
cuyo pool es `acme`.

**Cómo llega el dato.** El pool manda en `aislamiento_tenants`, que es de
`tenancy`. El barrido corre **dentro de cada servicio** y no puede leer el
esquema de otro, así que el valor viaja por el camino que ya llega a los
catorce: los ajustes en caliente. Declarar el aislamiento escribe también el
ajuste `pool_computo` en el ámbito del tenant, y a partir de ahí cada servicio
lo tiene en el suyo.

**Dos vacíos, y los dos significan «todos».** No es dejadez, es la decisión:

- un proceso **sin** `POOL_COMPUTO` atiende a todos. Al revés, el día que
  alguien despliegue sin definir la variable los barridos de todos los tenants
  dejarían de correr y nadie se enteraría hasta que una tabla creciera sin
  techo;
- un tenant **sin pool declarado** lo atiende cualquiera, que es lo que pasa
  hoy con todos los que nadie ha movido del común.

Y si el pool de un tenant no se puede resolver —la réplica aún no ha llegado,
no hay sesión— **se atiende igual, y queda aviso en el registro**. Saltárselo
por no saber convertiría un retraso de la réplica en trabajo que no se hace y
que nadie reclama.

La salida del barrido dice **cuántos se saltaron por ser de otro pool**. Sin
ese número, un proceso mal configurado barre cero tenants y su salida es
idéntica a la de un sistema sin trabajo pendiente.

## Cuando un campo personalizado merece una columna de verdad (`CRM-00.04.03.11`)

Materializar **no es la norma, es la excepción**, y la excepción se decide con
una medida: hay un informe que dice qué campos la justifican por volumen de
escrituras. Sin ese número, cada cliente que note su lista lenta pediría
columna y acabaríamos con el `ALTER TABLE` de siempre disfrazado de
optimización — y un `ALTER TABLE` en una tabla que comparten mil tenants los
bloquea a todos.

Lo que faltaba era **hacerlo**. Estaba descrito paso a paso en la respuesta del
informe y se ejecutaba a mano en una migración; la marca de «ya materializado»
no la ponía nadie, así que un campo ya convertido seguía saliendo como
candidato para siempre.

Ahora es un trabajo reanudable —un despliegue a mitad del relleno no puede
dejar media columna puesta y a nadie mirando— con cuatro pasos **en un orden
que es la capacidad misma**:

1. **La columna se añade *nullable*.** En PostgreSQL moderno es instantáneo y
   no reescribe la tabla. Con `NOT NULL` o con `DEFAULT` sí la reescribe, y ahí
   es donde se bloquea a los demás.
2. **Se rellena por lotes**, cada uno en su transacción. De una vez sería un
   `UPDATE` de millones de filas: bloqueo largo y un `rollback` de horas si algo
   falla a la mitad.
3. **Se indexa al final**, y sólo sobre las filas de ese tenant: mantener el
   índice durante el relleno lo hace más lento y más grande.
4. **Y sólo entonces se marca.** Marcarlo antes haría que las consultas
   empezaran a leer una columna a medio rellenar, y las listas saldrían
   incompletas **sin que fallara nada** — que es peor que fallar.

Dos decisiones más que deciden si esto funciona de verdad:

- **La expresión del campo prefiere la columna en un solo sitio**: el único
  lugar donde se construye la expresión de un campo personalizado. Así todo lo
  que filtra y todo lo que ordena lo hereda sin tocar nada más. Si hubiera que
  cambiarlo listado por listado, materializar sería una promesa que se cumple
  en unos sitios sí y en otros no, y nadie sabría en cuáles.
- **Va con `COALESCE`.** La columna es de la tabla, que es común a todos los
  tenants, y sólo se rellena la del que lo pidió. Sin el respaldo, los demás
  leerían nulo en un campo que sí tienen — y eso no falla: simplemente deja de
  encontrar registros.

La columna se llama `c_<campo>`: un campo personalizado llamado `estado` o
`nombre` chocaría con la columna real del objeto, y el filtro del personalizado
acabaría filtrando por el del sistema sin avisar a nadie.
