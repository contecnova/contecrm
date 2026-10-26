# Manual I — Empezar a usar la solución

Para quien acaba de clonar el repositorio y quiere verlo funcionando.

## Qué hace falta

- **Python 3.12** o superior. Nada más para el modo local.
- **Docker** solo si quieres levantarlo como en producción (ver más abajo por
  qué a veces hace falta).

## Instalación

```bash
git clone https://github.com/contecnova/contecrm.git
cd contecrm
./setup.sh instalar
```

Eso crea el entorno, instala las dependencias, genera un `.env` con **secretos
aleatorios** —nunca valores de ejemplo, que acaban llegando a producción porque
«ya venían así»— e instala los gates de git.

## Arrancar

```bash
./setup.sh arrancar
```

En unos segundos tienes los **catorce servicios y los seis workers** en pie, con
un Postgres embebido:

```
  ✓ tenancy :8001 listo          ✓ sales :8009 listo
  ✓ identity :8002 listo         ✓ service :8011 listo
  ✓ metadata :8003 listo         ✓ marketing :8012 listo
  ✓ orchestrator :8004 listo     ✓ analytics :8010 listo
  ✓ automation :8005 listo       ✓ intelligence :8013 listo
  ✓ integration :8006 listo      ✓ gateway :8080 listo
  ✓ eventing :8007 listo
  ✓ party :8008 listo
  ✓ worker orchestrator/worker corriendo
  ✓ worker identity/reparto_worker corriendo
  ✓ worker party/trabajos_worker corriendo
  ✓ worker sales/trabajos_worker corriendo
  ✓ worker intelligence/trabajos_worker corriendo
  ✓ worker analytics/trabajos_worker corriendo
```

**Los workers importan más de lo que parece.** No escuchan en ningún puerto, así
que un sistema sin ellos **arranca, contesta y se ve perfecto**: lo que no hace
es ejecutar nada de fondo. Los trabajos se encolan y no pasan nunca, **sin
error**. Por eso `./setup.sh estado` los mira por proceso y los canta aparte; si
alguno no corre, lo dice con esas palabras.

> Este documento decía «los ocho servicios», `setup.sh` arrancaba once y el
> `docker-compose.yml` veinte. Las tres listas se habían separado solas, porque
> separarse no rompía nada. Ahora hay una prueba que compara la del compose con
> la de `setup.sh` y falla cuando divergen.

La documentación interactiva de la API está en
**<http://localhost:8080/api/v1/docs>**.

### Con Docker, y por qué a veces es obligatorio

```bash
./setup.sh arrancar --docker
```

Levanta Postgres, NATS y Redis de verdad, que es lo que hay en producción. La
diferencia **no es cosmética**: el Postgres embebido corre como superusuario, y
un superusuario **se salta las políticas de Row-Level Security aunque estén en
FORCE**. Un fallo de aislamiento entre tenants solo se reproduce fielmente aquí.

Para programar, el modo local basta y es mucho más rápido.

## Quién administra la plataforma

Hay dos cosas distintas y conviene no confundirlas:

* **Administrar una empresa** — usuarios, roles, campos, procesos de esa
  empresa. Lo hace un usuario con rol `admin` dentro de su tenant.
* **Administrar contecrm** — dar de alta empresas, mirar su consumo, suspender
  una, entrar como un usuario con motivo y traza. Eso es *plataforma*, y ningún
  administrador de empresa lo ve, por muchos permisos que tenga.

La cuenta de plataforma **la dice el `.env`** y se aplica en cada arranque:

```bash
SUPERADMIN_EMAIL=plataforma@tu-dominio.com
SUPERADMIN_PASSWORD=...           # de verdad: es la cuenta con más poder
SUPERADMIN_TENANT=plataforma      # su propia empresa, para no entrar en la de un cliente
```

Al levantar, `tenancy` crea ese tenant e `identity` crea o reajusta la cuenta.
Se entra con esos tres datos —correo, contraseña y `plataforma`— en la pantalla
de acceso. Si cambias la contraseña en el fichero, cambia en el siguiente
arranque: una cuenta así no puede depender de que alguien recuerde haberla
creado.

Para ponerla a mano sin reiniciar:

```bash
docker compose exec tenancy python scripts/cuenta_de_arranque.py --parte tenant
docker compose exec identity python scripts/cuenta_de_arranque.py --parte cuenta
```

## Datos de demostración

```bash
./setup.sh demo
```

Crea un tenant `demo` con un plan, un administrador y la configuración inicial.
Imprime las credenciales al terminar.

### Una empresa con datos de verdad

`setup.sh demo` deja lo mínimo para entrar. Para ver la aplicación con volumen
—cartera, embudo, casos— y con su **configuración puesta** hay dos pasos:

```bash
# Lo que se mueve: cuentas, contactos, oportunidades, casos
python scripts/sembrar_empresa.py --slug ficosa --escala mediana \
    --email direccion@ficosa.example --contrasena '...'

# Lo que las sostiene: canales, plantillas, procesos, reglas, riesgos, roles
python scripts/sembrar_configuracion.py --tenant ficosa \
    --email direccion@ficosa.example --contrasena '...' \
    --aprobador soporte.jefe@ficosa.example
```

El segundo va **por la API y no por la base de datos**, a propósito: lo que deja
sembrado es exactamente lo que una persona podría haber creado desde el front
—pasa por las mismas validaciones, los mismos permisos y los mismos eventos— y
si un alta está rota, el sembrado se para y lo dice.

`--aprobador` es el correo de una segunda persona. Hace falta porque hay cosas
que el sistema no deja aprobar a quien las crea: publicar un artículo de
conocimiento hacia el cliente, por ejemplo.

## A qué URL ir

Al terminar `./setup.sh arrancar`, el guion las imprime. Son dos y no una, y
conviene no confundirlas:

| Qué | Dónde | Para qué |
|---|---|---|
| **La interfaz** | `http://localhost:15173` (local) · `http://localhost:13000` (Docker) | **Empieza por aquí** |
| La API | `http://localhost:18080/api/v1/docs` | El contrato, para integrar |

`http://localhost:18080/` a secas devuelve **404 a propósito**: el gateway es la
puerta de la API, no sirve la web.

> **Esto estuvo roto.** En local se levantaban los catorce servicios, se
> imprimía sólo la URL del gateway y se acababa: quien arrancaba se quedaba con
> la API en pie y **ninguna pantalla**, sin que nada se lo dijera. Y esa línea,
> que lleva `/api/v1/docs`, se lee como «aquí está el producto» cuando lo que
> enseña es el contrato. La llamada que levanta la interfaz estaba escrita y
> sólo la hacía el camino de Docker.
>
> De paso se arreglaron otras dos: el arranque decía «Front en :15173» en
> cuanto lanzaba el proceso, sin comprobar que llegara a escuchar —con un error
> de compilación el mensaje mentía—, y Vite se cambiaba de puerto en silencio
> si el suyo estaba ocupado, así que la URL anunciada no era la que funcionaba.
> Ahora espera a que responda, y si el puerto está cogido **falla y lo dice**.

Los puertos salen del `.env` (`FRONT_PORT`, `GATEWAY_PORT`, `CONSOLA_PORT`) y
todo escucha en `127.0.0.1`: desde fuera de la máquina no se llega sin un proxy
delante, a propósito.

## Primer recorrido

```bash
# 1. Entrar
TOKEN=$(curl -sX POST http://localhost:8080/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@demo.example.com","contrasena":"demo-contecrm-2026","tenant":"<id-del-tenant>"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 2. Ver quién eres y qué puedes hacer
curl -s http://localhost:8080/api/v1/auth/me -H "Authorization: Bearer $TOKEN"

# 3. Crear un objeto propio del tenant, sin tocar el esquema de nadie
curl -sX POST http://localhost:8080/api/v1/metadata/objetos \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"nombre":"proyecto_obra","etiqueta":"Proyecto de obra"}'

# 4. Preguntar si unos datos serían válidos ANTES de enviarlos
curl -sX POST http://localhost:8080/api/v1/metadata/objetos/proyecto_obra/validar \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"datos":{"importe":-5}}'
```

La cuarta llamada es la que enseña de qué va esto: el sistema responde **qué
está mal y por qué**, con los mismos errores que daría al guardar, para que
cualquier frontend pueda enseñarlos sin reimplementar las reglas.

## La portada: tu día

Lo primero que ves al entrar es **lo que tienes hoy**, en orden de urgencia:

1. **Ya se ha pasado.** Primero y en rojo, porque es lo único que no admite
   espera. Incluye lo que delegaste: quien delega sigue siendo responsable, y
   sin eso la tarea desaparece de tu vista en cuanto la pasas.
2. **Para hoy.** Lo que vence antes de medianoche, en tu zona horaria.
3. **Cierran esta semana**, y tu **embudo** dibujado por etapas, con lo que hay
   en cada una.

Dos cosas que se hacen a propósito:

**Ningún número suelto.** Cada cifra lleva su lista debajo. Una portada de
contadores obliga a buscar a qué se refieren, y entonces vuelve a ser un índice
con otra forma.

**Cuando no hay nada, se dice.** «Nada vencido. Bien.» Un hueco en blanco se lee
como «no ha cargado», y entonces nadie se fía tampoco de los bloques que sí
tienen cosas.

> Antes esta pantalla listaba enlaces a las demás y los contaba —«28 pantallas a
> tu alcance»—. Quien abre un CRM a primera hora no viene a elegir pantalla:
> viene a saber qué tiene que hacer y qué se le está pasando. Reconstruir eso a
> mano, abriendo tres pantallas y cruzándolas de cabeza, es trabajo que el
> sistema puede hacer y no hacía.

Tus **roles** ya no están aquí: viven en el menú de tu avatar, arriba a la
derecha. Son identidad —qué puedes hacer—, no trabajo del día, y ahí ocupaban el
sitio de lo que sí vence hoy. Siguen estando porque explican por qué no ves una
pantalla: sin ellos, «no me aparece» no tiene respuesta.

## Las dos entradas: trabajar y administrar

Arriba del todo del panel izquierdo hay dos pestañas, y es la primera decisión
que se toma al entrar:

**Trabajar** es el día a día: clientes, ventas, marketing, servicio y análisis,
más los accesos de cabecera —inicio, tu puesto, el chat—. Es lo que abre un
comercial o alguien de soporte, y es donde se entra por defecto.

**Administrar** es lo que se ajusta de tarde en tarde: automatizaciones,
procesos, integraciones, el modelo de datos, permisos, la consola. Es lo que
abre quien configura la instalación.

> **No son dos aplicaciones.** Es la misma sesión y los mismos permisos; lo
> único que cambia es qué se pone delante. Si no administras nada, la pestaña
> de Administrar **no aparece**: ofrecer un sitio vacío sólo sirve para que
> alguien lo pulse y descubra que no hay nada.

Antes las dos cosas colgaban del mismo menú, a la misma altura y con el mismo
peso: «Cuentas» y «Modelo de datos» una debajo de la otra. Un comercial no
configura objetos y un consultor no llama a clientes, así que los dos tenían
que leer el menú entero cada vez para encontrar lo suyo.

Una sola excepción, y está contada: **las aprobaciones** viven en
Automatización, que es de administrar, y se enseñan en Trabajar. Aprobar un
descuento no es configurar nada, y esconderlo detrás de «Administrar» es
garantizar que se quede esperando.

## Los formularios

Se generan del contrato del servicio, así que un campo nuevo aparece solo. Y
están pensados para rellenarlos de verdad:

- **Dos columnas** cuando hay sitio. Lo que necesita el ancho entero —un texto
  largo, una lista de líneas, un objeto— lo ocupa.
- **Lo imprescindible delante** y lo opcional plegado. Un alta de cuarenta
  campos, toda a la vista, no la rellena nadie.
- **La ayuda encima del campo**, que es donde sirve: «el nombre comercial con el
  que factura» ayuda a decidir qué poner, no a comprobarlo después.
- **Sin asteriscos.** Lo obligatorio y lo opcional están en grupos distintos, así
  que marcar cada campo del primero con un asterisco rojo no distingue nada.
- Un campo que apunta a otro registro **se busca**, no se teclea: `cuenta_id` es
  un cliente, no un identificador que haya que copiar a mano.
- Una lista de textos se escribe **una a una** y cada valor queda como etiqueta;
  una lista de opciones se **marca**; un objeto se edita **por pares**, con el
  JSON detrás de un interruptor para el caso raro.

> Lo de arriba son cuatro arreglos de octubre de 2026, y los cuatro se vieron
> **renderizando el formulario y mirándolo**: una sola columna a ochocientos
> píxeles de ancho, campos con más alto y más radio que un botón, la ayuda
> debajo, y las cajas de una misma fila a distinta altura cuando un campo tenía
> ayuda y el otro no — que es lo que hace que un formulario parezca descuidado,
> porque el ojo sigue la línea de las cajas y no la de los rótulos.

Lo que el formulario **no** hace es validar reglas de negocio. Marca lo
obligatorio y respeta el tipo y la longitud que declara el esquema, porque eso
es contrato; «el descuento no puede pasar del 30 %» lo comprueba el servicio, y
duplicarlo aquí sería tener dos versiones de la misma regla.

## La bandeja de casos

Los casos abiertos en tres montones, por lo que hay que hacer con ellos:

- **Fuera de plazo** — ya incumplió. Esto se explica, no se salva.
- **A punto de vencer** — todavía se puede salvar. Es el único montón que
  depende de que alguien lo toque ahora.
- **Con margen** — el resto, incluidos los que **no tienen plazo**. Esos no se
  esconden: un caso sin SLA no es tranquilo, es un caso que nadie ha
  clasificado, y esconderlo lo deja sin atender para siempre.

El corte entre «a punto de vencer» y «con margen» es un ajuste del tenant
(`SLA_RIESGO_HORAS`, 4 h de fábrica) y la pantalla dice con cuánta antelación
avisa, porque si no, ver un caso en un montón y otro parecido en el otro no
tiene explicación. En un soporte con SLA de cuatro horas conviene bajarlo; en
uno de cinco días, subirlo a un día o dos.

**El número de cada montón es el de todos, no el de los que caben en pantalla**,
y debajo se dice cuántos quedan fuera. Antes se contaba sobre la página traída:
decía «3 fuera de plazo» habiendo cincuenta.

Se entra al caso pulsando su fila entera. Una bandeja de la que no se puede
entrar a trabajar es un informe.

## Filtrar una lista

Encima de cualquier listado hay un botón **Filtrar**. Se elige un campo, una
condición y un valor:

| El campo es | Puedes pedir |
|---|---|
| una fecha | **desde**, **hasta**, es, sin valor, con valor |
| un número | **más de**, **menos de**, al menos, como mucho, es, sin valor |
| un texto | es, no es, **es alguno de** (separados por comas), sin valor, con valor |
| un sí/no | es, sin valor |

Lo puesto se ve como pastillas encima de la lista, cada una con su aspa. Están
siempre a la vista y no escondidas detrás de un panel: lo que importa más que
poder añadir el filtro siguiente es **saber qué recorte estás mirando**, porque
un filtro invisible es cómo se acaba discutiendo un número calculado sobre media
lista.

**El filtro viaja en la dirección.** Eso significa que una lista filtrada se
puede guardar en marcadores, pegar en un chat o en un correo, y al abrirla sale
igual. Y que recargar no la pierde.

**Se filtra en el servidor, no en tu navegador.** La diferencia importa cuando
hay muchas filas: el listado trae páginas, y filtrar en el navegador recortaría
sólo la página que ya se había traído — diría «3 resultados» donde hay cuarenta.

## La consola de agente

Una sola cola con todos los canales. El canal es una **etiqueta, no una
pestaña**: con una bandeja por canal, el correo se mira dos veces al día y el
chat todo el rato, y quien escribe por correo espera el doble sin que nadie lo
haya decidido.

**El orden lo decide el servidor**, no la pantalla, y son dos grupos:

1. **Lo que tiene plazo**, por lo que le queda. Lo vencido primero.
2. **Lo demás**, por lo que lleva esperando. Lo más viejo delante.

No se mezclan en un solo número a propósito. Un caso tiene minutos para vencer
y una conversación suelta no tiene plazo, sólo tiempo esperando: convertir una
cosa en la otra sería elegir un cambio de moneda a ojo y presentarlo como una
prioridad. Por eso también el reloj se rotula distinto —«vence en 20 min» frente
a «esperando 20 min»—: son un compromiso y una antigüedad, y enseñarlos igual
haría creer que significan lo mismo.

> Antes la pantalla mezclaba las dos listas pero daba a **todas** las
> conversaciones la misma urgencia, así que siempre iban al final y entre ellas
> quedaban por orden de llegada: la que llevaba tres días esperando podía salir
> detrás de la de hace cinco minutos. Y ordenar en la pantalla tenía otro
> problema: esto se publica para empotrarse, así que dos agentes con dos
> consolas distintas atendían en orden distinto.

Se entra pulsando la fila entera. Una consola de la que no se puede entrar a
trabajar es un informe.

## Cuadros de mando

Cada componente de un cuadro ejecuta su informe y se pinta. Dos cosas que
conviene saber al montarlos:

**Un gráfico elige su forma.** Al añadir un componente de tipo *gráfico* se
puede pedir `barras`, `lineas` o `area`. Antes el catálogo prometía las tres y
siempre se dibujaban barras: una serie temporal salía como un bosque de barras,
que es la forma de no ver una tendencia. Sin forma declarada siguen saliendo
barras, así que un cuadro ya montado no cambia de dibujo.

Una forma que no existe se **rechaza al guardar**, no cae a barras en silencio:
un cuadro que pide líneas y sale en barras no se nota hasta que alguien discute
una tendencia que no está dibujada.

**Un medidor enseña la meta.** Un componente de tipo *gauge* es «una métrica
contra su objetivo», y se dibujaba como una cifra suelta — perdiendo el
objetivo, que es lo único que lo distingue de un KPI. Ahora enseña la cifra, el
porcentaje, la meta y cuánto falta.

Es una barra y no una aguja a propósito: estimar ángulos no se hace bien a ojo,
y dos agujas parecidas sólo se distinguen leyendo los números. Y **pasarse se
ve**: la pista llega hasta lo conseguido, así que la marca del objetivo queda
dentro de la barra. Un medidor que recorta en el 100 % esconde que se superó la
meta, que es la noticia buena.

Un *mapa* todavía se dibuja como barras por territorio, y la pantalla lo dice:
una barra por territorio ordena y compara, mientras que un hueco con el título
puesto parece que no ha cargado.

## Las gráficas

Una respuesta analítica se dibuja según lo que **tiene que hacer quien la lee**,
y no según el nombre del tipo que trae el informe:

| El informe pide | Se dibuja | Por qué |
|---|---|---|
| `bar_chart`, `column_chart` | Barras | Comparar magnitudes |
| `line_chart`, `timeseries_line` | Líneas | Tendencia en el tiempo |
| `area_chart` | Área con **una** serie, líneas con más | Con tres, los rellenos se superponen y no se saca ninguna de las tres |
| `pie_chart`, `donut_chart` | Barra **apilada** | Ver abajo |
| `funnel_chart` | Embudo, con la caída en % | La caída entre etapas es el dato |
| `combo_chart` | Líneas | Ver abajo |
| cualquier otro | Tabla | Siempre se entiende |

Tres cosas que se hacen a propósito y conviene saber:

**Lo que se pide como tarta sale apilado.** Comparar ángulos es medir mal: dos
porciones parecidas sólo se distinguen leyendo los números, y si hay que leer
los números la tarta no estaba aportando nada. La barra apilada es lo mismo,
mejor leído.

**Nunca hay dos ejes verticales.** Dos magnitudes de escalas distintas van en
dos gráficas, o indexadas a una base común. Un eje doble deja que quien lo
dibuja elija dónde se cruzan las líneas, y entonces la gráfica dice lo que
quiera.

**Un hueco es un hueco.** Un mes sin medir no se pinta como cero: el trazo se
parte. Una línea recta sobre un mes sin dato inventa una tendencia que nadie
midió, y es el error más caro de una serie temporal.

Toda gráfica tiene al lado **«Ver como tabla»**, siempre. Es lo que la hace
legible con un lector de pantalla, lo que permite copiar un número exacto y lo
único que funciona si alguien no distingue dos colores.

## Cuánto quieres ver en pantalla

Al lado del interruptor de tema, en la barra superior, hay otro de **densidad**:

- **Compacta**, que es como viene de fábrica: unas catorce filas de una lista
  donde en cómoda caben cuatro. Es lo que quiere quien está aquí ocho horas.
- **Cómoda**: más aire, letra mayor, se lee de lejos. Es lo que hace falta en
  una demostración o en una pantalla compartida.

**Tu elección viaja contigo, no con el navegador.** Si la cambias en tu portátil
la tienes igual en el ordenador del cliente y en el del compañero cuando entras
con tu cuenta. El tema claro/oscuro sí se queda en cada navegador, y la
diferencia no es un capricho: el tema depende de la pantalla y de la luz de la
sala, la densidad depende de tu vista y de tu trabajo.

Lo mismo vale para el idioma, la zona horaria, el formato de fecha y el primer
día de la semana: son **tuyos**, los cambias tú y no hace falta que te los
cambie un administrador. Por API:

```bash
# Las que puedes cambiarte, con el valor que te aplica y de dónde sale
curl -s http://localhost:8080/api/v1/mis-preferencias -H "Authorization: Bearer $TOKEN"

# Cambiar una
curl -sX PUT http://localhost:8080/api/v1/mis-preferencias/ui_densidad \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"valor":"comoda"}'
```

## Otros comandos

| Comando | Qué hace |
|---|---|
| `./setup.sh estado` | Qué está corriendo y si responde |
| `./setup.sh parar` | Para los servicios (los datos se conservan) |
| `./setup.sh migrar` | Aplica las migraciones de los ocho servicios y RLS |
| `./setup.sh gates` | Corre los gates locales, que aquí sustituyen a la CI |
| `tail -f var/log/<servicio>.log` | Los logs de un servicio |

## Si algo no arranca

**Un servicio dice «vivo pero NO listo».** El proceso responde pero algo de lo
que depende no está. Mira su log: el `/health/ready` dice exactamente qué
comprobación falla.

**Todos fallan al conectar con la base.** Borra `var/pgdata` y vuelve a
arrancar: el Postgres local se reinicializa solo.

**Un puerto está ocupado.** Los puertos se resuelven en `setup.sh`
(`puerto_de`); cámbialos ahí o para lo que los esté usando.

## Siguientes pasos

- **Qué puede hacer cada perfil** → [Manual II](manual-2-perfiles.md)
- **Qué sabe hacer el sistema**, capacidad por capacidad → [Manual III](manual-3-funcionalidades.md)
- **Configurarlo y operarlo** → [Manual IV](manual-4-configuracion.md)
- **Cómo está construido y por qué** → [Manual V](manual-5-arquitectura.md)
- **Contribuir** → [Gates locales](QUALITY_GATES.md). Empieza por ahí: los
  gates solo protegen si los instalas.
