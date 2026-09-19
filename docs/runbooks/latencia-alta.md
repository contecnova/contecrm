# LatenciaAlta

## Qué significa

El percentil 95 pasa de dos segundos: una de cada veinte peticiones tarda más de
eso.

Se mide el percentil 95 y no la media porque **la media lo esconde**: con noventa
peticiones de 50 ms y diez de diez segundos, la media da un segundo y parece
aceptable, mientras diez personas están mirando una pantalla parada.

## Cuánto corre

Poco, salvo que suba. Es un aviso: el sistema funciona, va lento. Lo que importa
es la tendencia — si el percentil sube sin parar, acaba en tiempos agotados, y
eso ya es una caída.

## Qué mirar

1. **¿Una ruta o todas?** Una sola suele ser una consulta sin índice o un
   listado que se ha hecho grande. Todas apunta a la base, al pool o a la
   máquina.
2. **¿Un tenant o todos?** Uno solo suele ser volumen: alguien que acaba de
   importar doscientos mil registros.
3. `crm_http_duracion_segundos` por `ruta` lo separa en un minuto.

## Qué hacer

1. Si es una ruta concreta, mira el plan de la consulta que hace. Casi siempre es
   un filtro nuevo sobre una columna sin índice.
2. Si es el pool: `DB_POOL_SIZE` y `DB_MAX_OVERFLOW`. Subirlos sin mirar la base
   solo mueve la cola de sitio.
3. Si es un tenant que está importando, no hay nada que arreglar: la importación
   masiva compite con el uso normal, y para eso está la degradación
   (`DEGRADACION_ENABLED`), que difiere lo no crítico.
