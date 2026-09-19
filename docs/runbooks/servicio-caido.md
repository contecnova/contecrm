# ServicioCaido

## Qué significa

Prometheus lleva dos minutos sin poder recoger métricas de ese servicio. No
significa necesariamente que el proceso esté muerto: también salta si está vivo
pero no atiende, que en la práctica es lo mismo para quien lo usa.

## Cuánto corre

**Depende de cuál sea.** El `gateway` es el único que ve el usuario: si cae, el
CRM está caído para todo el mundo. Cualquier otro deja fuera solo su parte —sin
`sales` no hay oportunidades, pero las cuentas siguen funcionando—, y eso da
margen para arreglarlo bien en vez de deprisa.

## Qué mirar

```bash
docker compose ps                      # ¿está el contenedor?
docker compose logs --tail 200 <svc>   # ¿por qué se fue?
curl -sS localhost:<puerto>/health/ready | jq   # ¿arranca pero no está listo?
```

`/health/live` y `/health/ready` dicen cosas distintas, y la diferencia es el
diagnóstico: **vivo pero no listo** casi siempre es la base de datos o el bus, no
el servicio. Si `live` responde y `ready` no, el problema está detrás.

## Qué hacer

1. Si el contenedor no está, mira por qué salió: `docker compose ps -a` da el
   código de salida. Un 137 es que lo mató el sistema por memoria.
2. Si arranca y se cae en bucle, **no lo reinicies otra vez**: los logs del
   arranque tienen el motivo, y cada reinicio los sepulta más abajo.
3. Si `ready` falla por la base de datos, comprueba Postgres antes de tocar el
   servicio: reiniciar el servicio no arregla una base caída y sí borra las
   conexiones que ya tenía.
4. Si es el gateway y hay prisa, los servicios siguen publicando su API en sus
   puertos: una integración crítica puede apuntar directamente mientras tanto.

## Qué NO hacer

Borrar el volumen de Postgres «para que arranque limpio». Es la forma más rápida
de convertir una caída de diez minutos en una restauración de copia.
