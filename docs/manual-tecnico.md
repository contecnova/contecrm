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
