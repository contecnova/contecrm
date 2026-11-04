# Gates locales — lo que este repositorio usa en lugar de CI

Este proyecto **no tiene CI/CD, por decisión de proyecto**. Todo lo que en otro
repositorio comprobaría un servidor al abrir un *pull request*, aquí lo comprueba
la máquina de quien desarrolla, antes de que el cambio salga de ella.

Esa apuesta tiene una consecuencia que conviene tener presente: **los gates solo
protegen si están instalados**. En otra solución de la casa se encontró que
`.git/hooks/` solo tenía los `.sample` —o sea, que ningún gate había corrido
nunca— y en ese hueco llevaban meses un centenar de cadenas sin traducir y una
prueba de política de seguridad en rojo sin que nadie lo supiera.

Instalación, **obligatoria**:

```bash
pre-commit install    # instala los hooks de commit Y de push
```

`default_install_hook_types` en la configuración instala los dos tipos de una
vez. Sin esa línea, `pre-commit install` solo pone el de commit, y el de push
—que es el que corre la suite— no llega a existir: el gate más importante nunca
se ejecutaría.

---

## Los tres momentos

| Cuándo | Qué corre | Coste | Lo lanza |
|---|---|---|---|
| **en cada commit** | gates baratos, solo si cambian ficheros relevantes | < 5 s | `.pre-commit-config.yaml` |
| **en cada push** | los gates rápidos + la suite entera | ~1 min | `scripts/preflight.py --tests` |
| **a mano** | además, la construcción del sitio de documentación | minutos | `python scripts/preflight.py --todo` |

El criterio de reparto es el coste: lo de cada commit tiene que ser instantáneo o
se acaba puenteando con `--no-verify`, y entonces no corre **ninguno** de los
demás tampoco.

---

## El push corre lo que toca lo que ha cambiado

El nivel del push había llegado a **2 min 47 s** —medido el 11 de octubre de
2026, con la máquina a media carga— cuando la nota del propio fichero decía que
debía costar unos 37 segundos. De esos 167, **117 eran el recorrido de
aislamiento**, que construye las catorce aplicaciones y recorre sus rutas aunque
el commit sólo toque un manual.

Lo que pasa cuando un push tarda tres minutos no es que se espere: es que se
empuja con `--no-verify`, y entonces no hay red ninguna.

Así que cada gate caro declara **qué tiene que haber cambiado para que aporte
algo**, y en el nivel del push se omite lo que no mira nada de lo que cambió.
Medido, mismo commit:

| Lo que cambia el push | Antes | Ahora |
|---|--:|--:|
| Sólo manuales o scripts | 167 s | **5 s** |
| Un servicio | 167 s | **43 s** |
| El núcleo (`packages/`) | 167 s | 167 s |

El recorrido de aislamiento se acota además **a los servicios que cambiaron**,
porque está parametrizado por servicio: de 54-117 s a 14.

**Esto no quita ninguna comprobación.** El nivel completo las corre todas y es
el que cierra cada bloque; lo que cambia es cuándo. Y las dos reglas son
conservadoras a propósito:

- un gate se omite sólo si **nada** de lo que cambió está dentro de lo que mira;
- y el aislamiento se acota sólo si **todo** lo que cambió vive dentro de
  `services/<x>/`. Un cambio en `packages/` lo heredan los catorce, y acotarlo
  dejaría trece sin comprobar que no dejan ver lo de otro cliente.

Si no se sabe qué cambió —sin rama remota, recién clonado, `git` que falla— **no
se omite nada**. Una optimización que se equivoca callando es peor que no
tenerla.

Y lo omitido **se dice**, con el motivo y con dónde sí se corre. Un gate que no
corre en silencio da una falsa sensación de cobertura, que es peor que no tener
el gate.

## De la capacidad al código sí; a la prueba, todavía no

El gate del catálogo exige que toda capacidad declarada `hecho` esté **citada**
por su identificador y **documentada** en un manual. Eso hace trazable el camino
del catálogo al código. De ahí a una prueba no hay camino: la cita vale esté
donde esté, y **227 de 752** capacidades no las nombra ninguna prueba.

**Eso no dice que estén sin probar.** Comprobadas a mano dos al azar —el
aislamiento estanco por partner y el opt-out de entrenamiento— tienen pruebas de
sobra; lo que no tienen es el identificador escrito en ellas. Falta el último
tramo de la cadena, no la red.

Lo que cuesta es en una auditoría, donde la pregunta no es «¿está probado?» sino
«enséñame la prueba de **esto**». Sin el identificador en la prueba hay que
saberse el código para contestar, y quien audita no se lo sabe.

Por eso es un **tope** y no una exigencia: reescribir doscientos ficheros de
prueba de golpe sería un commit que nadie puede revisar, y la mitad de las citas
saldrían puestas a ojo. Lo que no puede es crecer — una capacidad nueva nace con
su prueba citada, y las viejas se citan cuando se las toque.

## El presupuesto: uno por nivel, y es un gate más

El preflight tiene un tope de CPU **por cada uno de sus tres niveles**. Si se
pasa, falla — aunque todo lo demás esté en verde.

| nivel | cuándo | coste medido (CPU / reloj) | tope de CPU |
|---|---|---|---|
| `rapido` | en cada commit | 22 s / 14 s | 40 s |
| `push` (`--tests`) | antes de empujar | 139 s / 72 s | 200 s |
| `completo` (`--todo`) | al cerrar un bloque | 354 s / 216 s | 500 s |

Medido el 06-10-2026 **con la máquina libre**. El margen es de alrededor de
1,4×: lo justo para que no salte por el ruido de una ejecución, y lo bastante
apretado para que saltar signifique que alguien ha añadido trabajo.

**«Con la máquina libre» no es un detalle.** El tope va por CPU y no por reloj
porque el CPU aguanta mucho mejor que otra ventana esté compilando — pero no es
inmune, y hasta el 7 de octubre de 2026 aquí ponía que sí. Medido ese día, el
mismo commit y el mismo nivel `push`:

| carga de la máquina | CPU | reloj |
|---|--:|--:|
| 7 | 146 s | 78 s |
| 61 | 252 s | 243 s |

Un 1,7 × sin haber añadido una línea: con contención suben los cambios de
contexto y se pierde la caché, y ese trabajo también se contabiliza. Así que
cuando la carga pasa del número de núcleos, el preflight **dice el número y la
carga y no falla**, y pide repetirlo con la máquina libre. Tampoco lo cuenta
como pase: un `--todo` bajo carga no apunta nada. Fallar ahí seguiría siendo
fallar por el vecino, sólo que con otra unidad.

**La carga se mira en las tres medias**, no sólo en la del minuto. Se consulta
al terminar, y un nivel completo dura diez minutos: la del minuto describe el
último tramo, no el pase. Pasó el 7 de octubre de 2026 a las 03:06 — un `--todo`
con los veinte gates en verde y todos sus tiempos inflados 3×, que es firma de
contención, salió marcado en rojo porque al acabar la del minuto había bajado de
10 mientras la de quince seguía en 19.

**Antes había un solo número —300 segundos— para los tres niveles**, y eso
rompía las dos puntas a la vez. El nivel rápido gastaba 22 segundos contra un
tope de 300: catorce veces de margen, o sea el guardián del crecimiento dormido
justo en el nivel que más se corre. Y el nivel completo gastaba 354, por encima
de su propio tope, así que **no podía salir en verde nunca**. Eso no era sólo un
rojo visible: el apunte de «aquí pasó la batería entera» se escribe *detrás* del
verde, así que no se escribía ni pasando los veinte gates, y el aviso de «van N
commits sin un pase completo» no bajaba de N por mucho que se corriera. Un aviso
que no baja nunca se aprende a ignorar, que es como se pierde el apunte entero.

**Y el mismo fallo volvió por otra rama, tres semanas después.** Medido el
29-10-2026: tres pases completos en verde el mismo día y el apunte seguía con
la fecha del anterior, con el aviso diciendo «van 46 commits sin un pase». La
causa era una tercera salida en verde —rápida de CPU pero lenta de reloj, que
es la que se toma cuando la máquina está ocupada— que devolvía cero **sin
apuntar nada**. Y como la pila local nunca se para, esa rama es la habitual.

Lo que se aprende no es la rama: es que **un arreglo no cierra la familia**.
Por eso ahora no se vigila esa salida concreta, sino **todas las salidas en
verde**, con una sola excepción que se reconoce por lo que ella misma declara
—la de la máquina apretada, donde el CPU medido no es el trabajo del preflight
y no cuenta ni como pase ni como rojo—. Validado plantando las dos cosas:
quitar el apunte de la rama del reloj, y añadir una cuarta rama verde que no
apunte.

No es una preferencia de estilo. Un preflight que tarda más deja de correrse: se
pospone «para luego», y luego se empuja sin él. Entonces el coste se paga entero
y la garantía no llega, que es el peor de los dos mundos. Un gate que no se corre
no garantiza nada.

Cuando el presupuesto salta, **lo que se arregla es el gate lento, no la
comprobación**. La primera vez que se midió, las pruebas con base de datos
tardaban 200 segundos y 195 de ellos se iban en crear y tirar un esquema de 98
tablas **por prueba** —0,36 s × 537 pruebas—. El tiempo no se iba en probar: se
iba en montar y desmontar. Pasar a aislar por **transacción** en vez de por
esquema lo dejó en 11 segundos sin quitar ni una prueba.

Lo peor de aquello no era el número, era la pendiente: cada tabla nueva del
producto encarecía todas las pruebas a la vez. Con el esquema montado una sola
vez por sesión, una tabla nueva cuesta unos milisegundos una vez.

**Lo que se mide es el reloj de pared, no la suma de los gates.** Los gates
corren en paralelo —hasta seis a la vez—, así que sumar sus tiempos mide trabajo
hecho y no tiempo esperado: decía tres minutos y medio donde quien lo lanzaba
esperaba minuto y medio. Lo que hace que un preflight deje de correrse es lo que
se tarda en volver al teclado, y eso es el reloj.

Dos gates van marcados como **exclusivos** y se turnan entre ellos: las pruebas
con base y la comprobación de migraciones levantan cada una un Postgres
embebido, y dos a la vez se quedan esperándose sin terminar nunca. El resto corre
en paralelo entre sí y con el exclusivo de turno. Por eso el informe sigue
enseñando el tiempo de cada gate —que es donde se mira cuál engorda— junto al
tiempo de reloj, que es el que se compara con la referencia del nivel.

**Cuántos a la vez lo decide la memoria libre, no los núcleos.** Con seis en
paralelo cada gate pasó de 14 a 112 segundos, y no era la CPU: son diez núcleos y
cada gate usa uno. Era la RAM. Los gates que recorren los trece servicios
construyen las trece aplicaciones y se quedan en medio giga cada uno; con la pila
de Docker levantada —que en esta máquina se lleva la mitad de los 16 GB— seis de
ellos metían el sistema a paginar. Un preflight que pagina tarda más en paralelo
que en serie, que es justo lo contrario de lo que se buscaba.

Así que se mide la memoria disponible al arrancar y se divide por lo que cuesta
un gate. Se mide en vez de fijarse porque la misma cifra no vale para una máquina
con la pila levantada y otra sin ella: un número escrito en el script sería el de
la máquina de quien lo escribió. Con la pila entera en marcha salen cinco a la
vez y 126 segundos.

## Los gates, uno a uno

| Gate | Tier | Qué garantiza |
|---|---|---|
| `entorno` | fast | El árbol instalado cumple `requirements*.txt` |
| `ruff` / `formato` | fast | Estilo, orden de imports y errores estáticos |
| `env-example` | fast | `.env.example` refleja los `Settings` reales |
| `catalogo` | fast | La matriz de trazabilidad está regenerada desde el catálogo |
| `arquitectura` | fast | Servicios desacoplados, `tenant_id` obligatorio, permisos declarados, cero valores a fuego |
| `trazabilidad` | fast | Nada se declara «hecho» sin cita en el código **y** en el manual |
| `contrato-headless` | fast | Todo servicio publica su contrato y toda ruta está documentada |
| `pruebas-sin-bd` | tests | Todo lo que no necesita infraestructura |
| `pruebas-con-bd` | tests | Aislamiento entre tenants, motor de procesos, persistencia |
| `migraciones` | tests | Ningún modelo cambiado se ha quedado sin su migración |
| `front` | tests | El front oficial tipa, cumple sus reglas de accesibilidad, pasa sus pruebas y construye |
| `docs` | todo | `mkdocs build --strict`: el manual construye y sus enlaces resuelven |

Los gates `front` y `docs` son **opcionales**: si Node o mkdocs no están
instalados, se omiten con aviso en vez de tumbar el preflight. No toda máquina
que toca el backend tiene la cadena del front montada, y negarse a correr por eso
convertiría el ciclo rápido en una instalación obligatoria. Cuando la herramienta
está, el gate corre y falla como cualquier otro.

### `entorno` va primero, y es deliberado

Todos los demás gates dan por hecho el entorno en el que corren. Si el árbol
instalado no es el que declaran los manifiestos, lo que midan es otra cosa.

En otra solución de la casa, la primera vez que se comprobó esto salieron **12 de
50** restricciones violadas y las dos dependencias de desarrollo sin instalar —y
con ellas, 1.343 pruebas que no podían ejecutarse—. El sistema que sustituía a la
CI llevaba tiempo sin poder funcionar, y ningún gate podía verlo porque todos
daban por hecho su propio entorno.

### Los gates que son pruebas normales

No todo gate es un hook, y eso es a propósito: corren con `pytest`, salen en el
resumen y no hacen falta dos mecanismos para lo mismo.

| Prueba | Invariante |
|---|---|
| `test_contratos_arquitectura.py::test_ningun_servicio_importa_modulos_de_otro` | La separación en servicios no es decorativa |
| `…::test_el_nucleo_no_importa_servicios` | La dependencia va en un solo sentido |
| `…::test_toda_tabla_de_negocio_lleva_tenant_id` | Las dos redes de aislamiento no tienen punto ciego |
| `…::test_tenant_id_es_obligatorio_donde_existe` | Una fila con tenant nulo sería visible desde todos |
| `…::test_toda_ruta_de_escritura_exige_permiso` | Ninguna escritura sin permiso **declarado en la ruta** |
| `…::test_los_errores_de_dominio_tienen_codigo_estable` | Un cliente no depende del texto en castellano |
| `…::test_no_hay_urls_ni_credenciales_escritas_en_el_codigo` | Cero valores a fuego |
| `…::test_cada_servicio_usa_la_factoria` | Nadie se salta lo transversal |
| `…::test_los_ajustes_siempre_filtran_por_ambito` | La única tabla sin `tenant_id` justificada sigue acotada |
| `test_catalogo_trazabilidad.py` | El catálogo no puede decir que algo está hecho si no lo está |
| `test_headless_contract.py` | Todo existe como servicio con contrato antes que como pantalla |
| `test_rls_aislamiento.py` | Un tenant no ve ni escribe lo de otro, con un rol sin privilegios |

---

## Cuando un gate se pone en rojo

**Primero se entiende, no se desactiva.** Los gates de este repositorio han
encontrado fallos reales en su propio código el mismo día que se escribieron:

- Una ruta de validación que exponía el esquema del tenant sin exigir permiso.
- Una tabla sin `tenant_id` que quedaba fuera de las dos redes de aislamiento.
- Y el propio detector de valores a fuego, que marcaba patrones de validación
  como si fueran URLs: se afinó el detector, porque **un gate con falsos
  positivos se acaba desactivando, que es peor que no tenerlo**.

Si un gate está mal, se arregla el gate y se explica por qué. Si una excepción es
legítima, se añade a su lista **con el motivo escrito**: las listas de
excepciones de este repositorio llevan todas su razón al lado, y hay gates que
comprueban que la lleven.

### Y antes de creerte un verde: mira si has arrancado algo

`./setup.sh arrancar` sobre una pila **ya levantada** no arrancaba nada y decía
«✓» de los catorce servicios. Los uvicorn nuevos morían en el acto —el puerto
estaba cogido—, los ficheros de pid se quedaban apuntando a esos muertos, y lo
que contestaba era la pila de antes. Cambias el código, reinicias, y sigue
corriendo lo de la víspera sin un solo error a la vista. De regalo, `parar`
después tampoco paraba nada, porque iba por esos ficheros de pid.

**Había un guardia escrito para este caso y miraba demasiado pronto**: `kill
-0` a los 0,6 s del lanzamiento, cuando uvicorn todavía está importando la
aplicación y tarda segundos en morir por el puerto. Es el mismo error que
vigila la sección de arriba, en la otra dirección: una comprobación que no
llega a ver lo que dice comprobar.

Ahora `arrancar` para lo que ya hubiera **antes** de lanzar —sólo si es
nuestro: un puerto en manos de otro producto de la casa se dice y se respeta— y
al final compara **qué pid escucha con cuál lanzó**. Es la única diferencia
observable entre «arrancado» y «ya estaba»: que el puerto conteste lo cumple
igual un proceso de ayer.

El guardián ejecuta la función del `setup.sh` de verdad, contra un proceso que
escucha, y comprueba las dos mitades — porque «liberar el puerto» se cumpliría
también matando al vecino.

### Antes de creerte un rojo: mira qué más hay corriendo

Un rojo no siempre dice algo de lo que has tocado. En esta máquina conviven
varias soluciones de la casa, y la suite de otra ocupándola entera es
suficiente para teñir ésta: pruebas que se pasan de su plazo, servidores de
pruebas que no llegan a arrancar en el tiempo que se les da.

**Medido el 04-11-2026.** Un pase completo salió con un gate en rojo y con
`pruebas-con-bd` tardando 746 s en vez de los 241 s que tarda corriendo sola
—3,1×—. La prueba acusada pasa suelta en 4,5 s. La causa estaba fuera: otra
sesión corriendo 107 ficheros de prueba de otro repositorio, con cuatro
procesos al 94 % de CPU.

El preflight ya sabía mirar la carga, pero **lo hacía después de dar el rojo**,
así que justo en el caso en que hace falta no se decía. Ahora, cuando hay rojos
y la máquina está llena, lo dice debajo de ellos — sin taparlos: un rojo sigue
siendo un rojo y sigue devolviendo 1. Lo que se añade es el dato que decide si
creérselo.

Y el umbral: era «carga por encima de los núcleos», que sólo veía la
sobresuscripción. Con 9,98 de carga sobre 10 núcleos no saltaba, y a esa carga
ya no queda nada libre para los seis gates que este pase quiere abrir a la vez.
Está en el 80 % de los núcleos.

Lo mismo por el otro lado: el gate `pantallas` se declaraba `exclusivo` «para
no competir con los otros cinco», y `exclusivo` **sólo excluye a otros gates
exclusivos**. Corría al lado de `front` —dos `vite build`, `tsc`, `eslint` y
785 pruebas— y se le agotaban los 180 s que esperaba a su servidor, cuando
corriendo solo construye y pasa sus 40 pruebas en 11,9 s. El plazo está en
420 s, que no esconde un cuelgue de verdad: lo retrasa hasta después de haber
descartado la prisa.

---

## Por qué no hay CI

Es una decisión de proyecto, igual que en el resto de soluciones de la casa. Lo
que se gana: el ciclo es local, no hay que esperar a un servidor, y el que
desarrolla ve el fallo donde puede arreglarlo. Lo que se pierde, dicho
claramente: **nada obliga** a que los gates hayan corrido antes de que un cambio
llegue al repositorio. Depende de que estén instalados.

Por eso `./setup.sh instalar` los instala, y por eso este documento está enlazado
desde la primera página del manual.

## «Cero pruebas» significa dos cosas distintas

El gate de aislamiento se acota a los servicios que cambiaron: es la
optimización que lo baja de 117 s a unos pocos cuando el cambio vive dentro de
un solo servicio. Pero `pytest` devuelve el código 5 cuando no recoge ninguna
prueba, y eso salía **en rojo**.

Pasó el 27-10-2026 con el arreglo del tablero de ventas: tocaba sólo
`services/gateway/`, ninguna prueba de aislamiento habla de `gateway`, y el
gate acabó en «4.369 deseleccionadas» y rojo — sin que el mensaje dijera por
qué, que es lo peor de un rojo.

Ahora se distinguen los dos ceros, y la diferencia importa:

- **Gate acotado que no recoge nada**: no hay nada que mirar en lo que cambió.
  Pasa, y lo dice con esas palabras.
- **Gate sin acotar que no recoge nada**: está pasando en verde sin mirar, que
  es el peor verde que hay. Sigue siendo rojo.

Comprobado en los dos sentidos: forzando la marca a falso, el mismo gate vuelve
a salir en rojo.

## El barrido de pantallas (no es un gate, y por eso hay que acordarse)

    ./setup.sh arrancar
    node frontend/scripts/barrido-pantallas.mjs

Abre las 58 pantallas contra la pila local y, de cada listado, su primera
ficha **con todas sus pestañas**. Dice dos cosas: cuáles revientan al pintar y
cuáles enseñan el dato en crudo.

## Una frase en letra de máquina

La monoespaciada es para lo que se lee carácter a carácter: un identificador,
un código, un hash, una cifra que se alinea en columna. Una frase en
castellano, no; en Lightning no hay monoespaciada en la interfaz salvo para
código.

**Lo que sí es código se reconoce por su elemento** —`code`, `pre`,
`textarea`, `input`— y no por una lista de excepciones. Los permisos
incompatibles de `/seguridad` y los alcances de OAuth de `/suite` se pasaron a
`<code>` justamente por eso, y de paso un lector de pantalla los anuncia como
lo que son.

La regla: con espacios y sin ningún dígito. Así pasan «0/61 · 0 %» y «25
vistas», que son cifras, y no pasa «sin declarar».

## El manual llama a las pantallas por su nombre de hoy

`tests/unit/test_el_manual_llama_a_las_pantallas_por_su_nombre.py` ·
`scripts/sellar_rotulos.py` · `docs/rotulos-de-menu.json`

Al renombrar una entrada del menú, el manual se queda con el nombre viejo y
nadie lo mira: el gate de manuales comprueba que **cubran** todo y que no
describan lo que ya no existe, pero una pantalla renombrada sigue existiendo,
así que pasa.

**Medido el 03-11-2026**, el día que se renombraron cinco entradas: tres citas
se habían quedado atrás —«Entornos y despliegue», «Canales de ejecución» y
«Consola de administración»—, y una en las instrucciones de cómo llevarse una
configuración a producción. Quien siga el manual busca una entrada que no
está.

**Adivinarlo por parecido no vale, y lo dijo plantar el caso malo.** La
primera versión buscaba citas que se parecieran mucho a una entrada sin ser
ninguna; devolví «Entornos y despliegue» al manual y la prueba pasó, porque
hoy se llama «Promoción entre entornos» y no se parecen en nada. **El
renombrado que cambia el nombre entero es el que más despista y era justo el
que se escapaba.**

Se hace como el contrato publicado: se **sellan** los rótulos. El sello guarda
cómo se llama hoy cada entrada; un rótulo sellado que ya no está en el menú es
un renombrado, y entonces —y sólo entonces— se mira si el manual lo nombra.
Renombrar no se bloquea: se bloquea renombrar sin arreglar el manual.

    python scripts/sellar_rotulos.py            # comprueba
    python scripts/sellar_rotulos.py --sellar   # lo vuelve a escribir

## Dos vacíos de caja grande seguidos

El vacío tiene dos formas: la de **pantalla** —tarjeta con icono grande y
texto centrado, unos 180 px— para cuando no hay nada que hacer ahí, y la de
**sección** —una línea— para un bloque de una pantalla que sí tiene más cosas.

**Medido el 03-11-2026**: `/entornos` pintaba cuatro de las grandes seguidas,
760 px de nada; `/ciclo-de-vida` tres, y su primer dato caía a 945 px. Cuatro
«no hay nada» seguidos no dicen «no tienes nada»: dicen «esto está vacío», que
es otra cosa y desanima igual.

Dos lecciones de la medición, las dos de la sonda y no del producto:

- **Contarlos por el código engaña.** `Entornos.tsx` tiene **un** `<Vacio>` en
  el fichero y pintaba cuatro, porque va dentro de un bucle por entorno. La
  regla «si un fichero tiene dos o más, todos son de sección» acertó en 30 de
  35 sitios y se saltó justo ése.
- **Contarlos por el alto y el texto cuenta de más.** La primera versión de la
  medida buscaba bloques altos con palabras de ausencia y dio por vacíos
  bloques que no lo eran. Ahora el componente se marca —`data-vacio="pantalla"`
  y `"seccion"`— y el barrido los cuenta por su marca.

Y cinco de los 35 volvieron a ser grandes a mano, porque ahí el vacío **es**
la pantalla: un listado sin filas, un módulo que no existe, «elige un área».

## Dos entradas del menú no se llaman igual

`frontend/src/pruebas/dos_entradas_no_se_llaman_igual.test.ts`

**Medido el 03-11-2026** en el menú de Administrar, que tiene veinte entradas:
«Entornos y despliegue» junto a «Entornos y despliegues» —singular y plural, a
dos filas—, «Usuarios y permisos» junto a «Usuarios y seguridad», «Consola de
administración» junto a «Consola de agente», «Canales de entrada» junto a
«Canales de ejecución». Es la queja que abrió el rediseño —«mil opciones que
muchas son inútiles»— y no eran inútiles: eran pantallas distintas con nombres
que se pisaban.

**Por qué esta regla y no «la pantalla se llama como su entrada»**, que era lo
primero que se intentó y se descartó midiendo: esa no se puede escribir sin
equivocarse. El menú abrevia a propósito —«Coste» lleva a «Coste y capacidad»,
«Estado» a «Estado del servicio»— y eso está bien; y «Procesos en curso»
llevando al «Editor de procesos» comparte la palabra «procesos» y aun así dice
lo contrario. Ninguna regla mecánica separa las dos cosas, así que la medición
rótulo-contra-título se hizo a mano —13 de 30 descuadraban, 4 de verdad— y se
arreglaron los cuatro.

Lo que sí es objetivo es comparar los rótulos **entre ellos**: misma frase
salvo el plural, una que es el principio de la otra, o mismo número de
palabras cambiando sólo la última. La longitud importa: sin ella, «Casos» y
«Bandeja de casos» saltarían, y ésos se distinguen de sobra porque «bandeja»
dice qué es.

Validado plantando las tres parejas. Y una lección de la plantación: devolver
**un solo** rótulo viejo no reproduce la confusión, porque la confusión es de
la pareja. Hay que devolver los dos.

## El castellano de las claves técnicas

`tests/unit/test_el_producto_escribe_bien_el_castellano.py`

El front pinta claves de la API delante de las personas: como rótulo de un
campo, como etiqueta de un valor, como nombre de columna. Lo hace `humanizar`,
que parte por los guiones bajos, capitaliza y consulta un diccionario de
palabras con tilde.

**Medido el 03-11-2026.** Se vio «Forma juridica distinta» en la cola de
duplicados. En vez de añadir esa palabra, se midió la familia: las claves que
el producto puede enseñar, cruzadas con **cómo escribe él mismo cada palabra
en sus propios textos**. Ésa es la autoridad y no hay que inventar nada: si el
producto escribe «dirección», un rótulo que ponga «Direccion» está mal.
Resultado: **127 palabras** añadidas al diccionario.

Las tres decisiones que costaron, y las tres se tomaron plantando el caso
malo:

- **De dónde salen las claves.** Primero sólo propiedades y enums de los
  catorce contratos: 1.586. No bastaba — `forma_juridica_distinta` no es
  ninguna de las dos, la escribe `services/party/duplicados.py` como una
  cadena suelta. Hubo que recoger también las cadenas con guion bajo de
  `services/`, saltando los nombres de índice y restricción (`ix_`, `uq_`,
  `fk_`…), que son del esquema y no se enseñan nunca.
- **De dónde sale la ortografía.** Primero sólo los ficheros de texto de la
  interfaz: 312 palabras con tilde. Tampoco bastaba — «jurídica» no aparece en
  ninguna frase de la interfaz, así que el gate **no cazaba la palabra que lo
  originó**, y eso se supo plantándola. Con los dos manuales dentro son 857, y
  entonces sí.
- **Qué se deja fuera.** 31 palabras donde la forma sin tilde también es
  correcta: `cuenta_como_caso` es «caso» y no «casó», `solo_este_tenant` es el
  demostrativo, `actua_como_id` es «actúa como». Están declaradas una a una
  **con su motivo**, porque es una lista de excepciones y no de aceptadas: así
  una palabra nueva entra vigilada.

Y una prueba del front fijaba la falta: esperaba literalmente «Forma juridica
distinta», así que iba verde con lo que en la pantalla se leía mal.

**Una pantalla muerta** se reconoce por tres cosas, y ninguna es su texto:

- una **excepción de JavaScript**;
- una respuesta **400, 404, 422 o 5xx** de la API — el front pidió mal, o el
  servidor se cayó. Ninguna pantalla sana las provoca;
- o que **la alerta sea todo lo que hay**: hay `role="alert"` visible y no hay
  ni `h1`.

**Medido el 02-11-2026**: `/menciones` y `/territorios` llevaban muertas, las
dos con un 422 por mandar `limite` a una ruta que no lo declara —el servidor
rechaza a propósito un parámetro que no mira, que es lo correcto: un filtro
ignorado en silencio es peor—. El barrido decía «ROTAS: 0» porque buscaba
**dos textos concretos**, «no se ha podido pintar» y «No se ha podido
contactar», y el de estas era otro. Un guardián que busca el texto del fallo
que ya conoce no caza el siguiente.

Lo que NO cuenta, y es la parte fina:

- **401 y 403**: son la respuesta correcta a pedir lo que no te toca, y las
  pantallas de plataforma las provocan a propósito.
- **409**: es «el estado no lo permite», una respuesta de negocio. `/cuadros`
  contesta 409 con «el CRM todavía no está registrado como fuente en
  contecintelligence, se publica desde Explotación», que es exactamente lo que
  hay que decir. Contarlo habría puesto en rojo una pantalla que funciona.
- **La alerta sola.** `/cuadros` enseña esa alerta y tiene su título, su
  selector y sus cuadros. Lo que delata a una muerta es que no haya nada más.

Validado en los dos sentidos: con el `limite` replantado, `/territorios` sale
nombrada con «422 /api/v1/territorios» y código 1, mientras `/cuadros` sigue
en verde.

**La letra fuera de la escala** es cualquier tamaño que no sea uno de los
siete —12, 13, 14, 16, 20, 24 y 32—. Hay una prueba que lee el código y vigila
las tres formas de escribir un tamaño (clase de la escala, clase arbitraria y
número suelto), y **no basta**: se le escapó un 9 px escondido tras una
constante, `fontSize={LETRA_GRAFICA}`, y lo cazó plantar el caso malo, no la
prueba. Contra una indirección sólo vale mirar lo que el navegador pinta, y
eso es esto. Los iconos no cuentan: son una ligadura dibujada.

Y por eso la línea dice **cuántos textos ha mirado**, no sólo cuántos ha
encontrado fuera: una pantalla que todavía no ha pintado nada da «ninguno
fuera» con el mismo verde que una que está bien. Con el 9 px plantado a
propósito, este barrido llegó a contestar «ninguna» mientras una sonda suelta
sobre la misma pantalla lo veía — el número de mirados es lo que distingue las
dos cosas.

**El dato en crudo** es `null`, `undefined` o `[object Object]` a la vista.
Sale cuando un valor vacío o compuesto llega a la pantalla sin pasar por el
formateador de la casa, y no revienta nada: la pantalla funciona y miente.
Medido el 02-11-2026 en la pestaña «Detalles» de un caso —«Motivo: null»,
«Padre: null», «Contacto ID: null»—, porque `String(null)` da «null». El
barrido lo busca con los límites de palabra puestos, que «anular» lleva «null»
dentro y es castellano.

Las pestañas se recorren porque el fallo estaba en «Detalles», que no se pinta
hasta que alguien la pulsa: abrir la ficha y mirar no lo veía. **Se buscan por
su rótulo** —`nav[aria-label="Secciones de la ficha"]`— y no como «cualquier
`nav` dentro de `main`»: con el selector ancho el barrido pulsaba todo botón
de todo `nav` —paginación, menús, selectores—, a 900 ms cada uno. Pasó de tres
minutos a más de quince, y cada clic dejaba el navegador donde le parecía, así
que dejó de medir lo que creía medir: con un 9 px plantado a propósito
contestaba «ninguna» mientras el mismo bucle sobre una sola pantalla lo veía.

Con el selector acotado: 58 pantallas, 5.217 textos mirados, y el 9 px
plantado sale nombrado y con código 1.

Y `CRM_SOLO=/procesos,/m/cuentas` recorta el barrido a lo que se nombre, que
es lo que permite perseguir un fallo sin esperar el recorrido entero.

**El recuento de pantallas tiene suelo, y por algo.** El 03-11-2026 el barrido
pasó de 58 destinos a 57 y siguió en verde: el patrón que saca los módulos de
`modulos.ts` exigía que `titulo:` fuera en la línea siguiente a `ruta:`, y
poner un comentario entre los dos dejó una pantalla fuera **en silencio**. Al
aflojarlo salieron **25 módulos donde antes se veían 23**: los que faltaban
eran `/m/oportunidades` —uno de los módulos centrales del CRM— y `/m/canales`,
y llevaban sin visitarse desde que se escribió el barrido.

Ahora el recorrido falla si recoge menos de 55 destinos. El suelo no persigue
el número exacto —una pantalla nueva entra sola— sino que el patrón deje de
casar, que es cuando el barrido contesta «ninguna rota» sin haber mirado.

**Por qué hace falta algo que no es un gate.** El 01-11-2026 se encontraron dos
pantallas muertas —la ficha de cualquier oportunidad con metodología activa y
`/inteligencia`— y las dos llevaban rotas quién sabe cuánto. Las dos por lo
mismo: el front da por hecha una forma que el servidor no manda, React tira el
árbol entero y la frontera de error se come la pantalla.

Nada de lo que había lo cazaba:

- **TypeScript no.** El tipo se declara en el `llamar<T>` y ya: es una promesa
  sobre datos de red, no una comprobación.
- **Las pruebas tampoco**, porque sus dobles inventan la forma. El de
  `lo_que_falta` ponía cadenas igual que el tipo, así que la suite confirmaba
  el error en vez de encontrarlo.
- **Ni el barrido de humo**, porque el servidor contesta 200.

No puede ser un gate: necesita la pila levantada y datos sembrados. Se pasa
cuando se toca el front a lo ancho, y el apartado está aquí para que no se
olvide que existe.

Validado plantando el caso malo, las dos veces: devolviendo el fallo de
`/inteligencia`, el barrido lo nombra y sale con código 1; y quitando la raya
de `escalar`, nombra `/m/casos → ficha` con el texto que enseñaba.
