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

## Copias de seguridad

Lo que hay que copiar, y por qué:

| Qué | Por qué |
|---|---|
| Postgres (todos los esquemas) | Es el sistema entero: datos, configuración, auditoría y estado de los procesos |
| Volumen de NATS | Los eventos aún no entregados |
| `.env` / gestor de secretos | Sin `ENCRYPTION_KEY` **los datos cifrados no se recuperan**, por muy buena que sea la copia de la base |

Ese último punto es el que más veces se descubre tarde: una copia de la base sin
la clave de cifrado es una copia de la que no se puede restaurar lo sensible.

## Rotar la clave de cifrado

```bash
ENCRYPTION_KEY_PREVIA=<la que había>
ENCRYPTION_KEY=<la nueva>
```

Con las dos puestas, lo escrito con la anterior se sigue descifrando mientras se
recifra. Sin esa convivencia, rotar exigiría una ventana de parada.
