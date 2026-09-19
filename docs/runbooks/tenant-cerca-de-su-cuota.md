# TenantCercaDeSuCuota

## Qué significa

Un cliente lleva más del 90 % de una de sus cuotas: registros, llamadas a la
API, almacenamiento, correos o tokens de IA.

## Cuánto corre

**Es una alerta comercial antes que técnica.** Nada está roto. Lo que va a pasar
es que el cliente choque con un tope, y eso hay que hablarlo con él **antes**, no
cuando ya le esté fallando.

## Qué mirar

```bash
curl -sS localhost:8001/api/v1/tenants/<id>/consumo | jq
```

Distingue tres casos, porque llevan a tres conversaciones distintas:

- **Crecimiento normal**: usa más porque le va bien. Toca ampliar el plan.
- **Carga puntual**: una importación, una migración. Toca ampliar temporalmente.
- **Algo desbocado**: una integración en bucle. Ampliar aquí sería pagar el
  fallo de alguien.

## Qué hacer

1. Mira la serie de los últimos días. Una subida limpia es crecimiento; un
   escalón vertical es una integración.
2. Si es crecimiento, habla con quien lleve la cuenta antes de tocar nada.
3. Si hace falta margen ya, la cuota se ajusta en caliente por tenant. Queda
   auditado, y es lo correcto: bloquear a un cliente que paga por un tope
   administrativo es peor que el coste de unos registros de más.
