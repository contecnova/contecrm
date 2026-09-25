# ExplotacionNoDisponible

## Qué significa

El servicio de explotación no responde, o `contecintelligence` no es alcanzable
desde él. Los informes, los cuadros de mando y las preguntas en lenguaje natural
no funcionan.

## Cuánto corre

Poco. **El CRM operativo sigue funcionando**, y eso es a propósito (RT-4): la
explotación está desacoplada para que la herramienta de consulta no pueda tumbar
el sistema con el que se trabaja. Es un aviso, no una emergencia.

## Qué mirar

```bash
curl -sS localhost:8010/api/v1/analitica/estado?comprobar=true | jq
```

Devuelve si `contecintelligence` responde, cuánto tardó, qué versión tiene y cuál
fue el último error. Con eso se distingue lo que hay que distinguir:

- **No alcanzable**: está caído, o la dirección de `CI_BASE_URL` no es la buena.
- **Alcanzable y el canje falla**: la credencial (`CI_CLIENT_ID` /
  `CI_CLIENT_SECRET`) está mal o ha caducado.
- **Canje bien y consultas mal**: el tenant no tiene organización asignada.

## Qué hacer

1. Si no es alcanzable, comprueba que `contecintelligence` está en marcha y que
   la dirección configurada llega hasta él. Con la pila propia:
   `python scripts/vecinos.py estado`.
2. Si es la credencial, renuévala en `contecintelligence` y actualiza el `.env`.
   La credencial **no** se pone en la base: es del despliegue.
3. Si el tenant no tiene organización, asígnala:
   `PUT /api/v1/analitica/organizaciones`. Es una operación de plataforma.
4. Mientras tanto, díselo a quien esperaba un informe. La pantalla ya avisa, pero
   quien lo pidió por correo no lo ve.
