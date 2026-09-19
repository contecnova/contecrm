# EventosFallando

## Qué significa

Los consumidores están devolviendo error al procesar eventos.

## Cuánto corre

Poco de inmediato: los eventos **se reintentan**, así que no se pierde nada al
instante. Pero lo que se reintenta sin parar acaba en la cola de fallidos, y de
ahí no sale solo.

## Qué mirar

```bash
curl -sS localhost:8007/api/v1/eventos/fallidos | jq '.[:5]'
```

Mira si es **un tipo de evento** o todos. Uno solo suele ser un cambio de forma
en el `data` del evento; todos apunta al consumidor o a su base.

## Qué hacer

1. Si es un tipo concreto y el error es de forma, mira quién lo produce: el
   contrato del Anexo B dice qué campos lleva, y quitar uno es un cambio
   incompatible que exige versión nueva.
2. Reprocesa desde la cola de fallidos cuando esté arreglado. No antes: volver a
   meterlo sin arreglarlo solo repite el fallo.
3. Si el consumidor es de notificaciones y no consume, nadie está recibiendo
   avisos — díselo a quien los espera, porque desde fuera parece que no pasa
   nada.
