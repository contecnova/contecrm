# TablaDeSalidaAtascada

## Qué significa

Hay eventos esperando a publicarse desde hace más de cinco minutos.

Se vigila la **antigüedad del más viejo** y no cuántos hay, porque dicen cosas
distintas: mil eventos publicándose sin parar es un día normal; uno atascado
desde hace una hora es un incidente.

## Cuánto corre

Mucho, aunque no se note. Nada de lo que depende de eventos está ocurriendo: los
webhooks de los clientes no salen, los avisos no llegan, las automatizaciones no
se disparan. Y el trabajo **se acumula**: cuando se destasque, saldrá todo de
golpe.

No hay pérdida de datos — la tabla de salida está justo para eso —, así que la
prisa es por el retraso, no por el riesgo.

## Qué mirar

```bash
docker compose logs --tail 200 <svc> | grep -i "relevo\|outbox"
docker compose ps nats
```

El relevo publica con reintentos y espera creciente: si el bus está caído, lo
verás intentándolo. Si **no** hay ni un intento, el problema está en el relevo,
no en el bus.

## Qué hacer

1. Si el bus está caído, arréglalo: el relevo se pone al día solo, no hay que
   tocar nada.
2. Si el bus está bien y el relevo no intenta nada, reinicia el servicio. Es el
   caso en que un reinicio sí es la respuesta.
3. Si un evento concreto falla siempre, sácalo de en medio: está bloqueando la
   cola de su tenant. La cola de fallidos (`/eventos/fallidos`) existe para eso.
4. Cuando se destasque, **avisa a quien consuma webhooks**: van a recibir de
   golpe todo lo de la última hora.
