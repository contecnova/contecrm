#!/bin/sh
# Escribe `/config.json` con lo que diga el entorno. Lo lee el front al arrancar
# (`src/lib/config.ts`) y es lo que permite que la misma imagen valga para
# cualquier instalación.
set -eu
cat > /usr/share/nginx/html/config.json <<JSON
{
  "apiBase": "${API_BASE:-}",
  "nombre": "${APP_NAME:-contecrm}",
  "idioma": "${IDIOMA:-es}",
  "acento": "${MARCA_ACENTO:-}",
  "logotipo": "${MARCA_LOGOTIPO:-}",
  "sinConexionReintentoMs": ${SIN_CONEXION_REINTENTO_MS:-15000}
}
JSON
