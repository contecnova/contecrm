# DemasiadosRechazosPorLimite

## Qué significa

Se están devolviendo 429 de forma sostenida: alguien pide más de lo que su
límite permite.

## Cuánto corre

Medio. El sistema se está protegiendo —que es para lo que está el límite—, pero
alguien no está pudiendo trabajar.

## Qué mirar

La etiqueta `dimension` dice por qué se rechaza: por tenant, por usuario o por
dirección IP. Y eso ya separa los dos casos:

- **Un cliente se ha desbocado**: una integración reintentando en bucle, un
  script sin espera entre llamadas.
- **El límite se ha quedado corto**: el cliente creció y nadie revisó su tope.

## Qué hacer

1. Si es una integración en bucle, avisa al integrador antes de subir nada:
   subirle el límite a un bucle solo hace el bucle más rápido.
2. Si el uso es legítimo, sube el límite de ese tenant en caliente. Es
   configuración, no despliegue.
3. Si llega de una sola IP y no corresponde a ningún cliente, es tráfico que no
   debería estar ahí: eso se corta en el proxy, no en la aplicación.
