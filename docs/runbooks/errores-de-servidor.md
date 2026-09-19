# ErroresDeServidor

## Qué significa

Más del 5 % de las peticiones a ese servicio devuelven 5xx. Uno de cada veinte
usuarios está viendo un error.

El umbral es del 5 % y no del 1 % a propósito: por debajo de eso, el ruido normal
de un despliegue dispararía la alerta cada semana, y una alerta que salta cada
semana sin que pase nada deja de leerse.

## Cuánto corre

Mucho. A diferencia de la latencia, esto es trabajo que **no se está haciendo**:
altas que no se guardan, correos que no salen.

## Qué mirar

```bash
# Qué rutas fallan y con qué código
docker compose logs --tail 500 <svc> | grep -E '"status": 5' | head -40
```

Los logs llevan `request_id`: con uno solo se sigue la petición entera, incluidos
los servicios por los que pasó. Es mucho más rápido que leer por encima
quinientas líneas.

Mira si **empezó con un despliegue**. La coincidencia temporal con un cambio es
la pista más fiable que hay, y descartarla cuesta un minuto.

## Qué hacer

1. Si empezó con un despliegue, **vuelve a la versión anterior** antes de
   investigar. Diagnosticar con el sistema roto es más lento y más caro.
2. Si es una sola ruta, acótala: un fallo en `/accounts` no obliga a tocar el
   servicio entero.
3. Si son todas y `ready` está bien, mira la base: un `too many connections` o
   un bloqueo dan exactamente este perfil.
4. Si es un solo tenant, mira su configuración en caliente: un ajuste con un
   valor imposible falla solo para él.
