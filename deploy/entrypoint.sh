#!/bin/bash
# Punto de entrada único de la imagen.
#
#   entrypoint.sh servicio <nombre>   arranca un servicio con uvicorn
#   entrypoint.sh migrar <nombre>     aplica las migraciones de ese servicio
#   entrypoint.sh worker <nombre>     arranca su worker de fondo
#   entrypoint.sh shell               shell de Python con el entorno cargado
#
# Por qué un punto de entrada y no ocho comandos en el compose: el arranque de
# un servicio incluye decisiones (¿migra?, ¿cuántos workers?, ¿qué esquema?) y
# repetirlas ocho veces en el compose garantiza que alguna acabe divergiendo.

set -euo pipefail

MODO="${1:-servicio}"
SERVICIO="${2:-${SERVICE_NAME:-gateway}}"
export SERVICE_NAME="$SERVICIO"

modulo_del_servicio() {
  echo "services.${1}.main:app"
}

esperar_a_postgres() {
  # El `depends_on` del compose con `service_healthy` ya espera, pero fuera de
  # compose (systemd, Kubernetes sin initContainer) no hay nadie esperando, y
  # un servicio que se cae al arrancar porque la base tarda dos segundos genera
  # reinicios en bucle que parecen un fallo grave y no lo son.
  local intentos="${ESPERA_DB_INTENTOS:-30}"
  for ((i = 1; i <= intentos; i++)); do
    if python -c "
import sys
from sqlalchemy import create_engine, text
from crmcore.config import get_settings
try:
    create_engine(get_settings().database_url, pool_pre_ping=True).connect().execute(text('SELECT 1'))
except Exception:
    sys.exit(1)
" 2>/dev/null; then
      return 0
    fi
    echo "  esperando a Postgres ($i/$intentos)…"
    sleep 2
  done
  echo "Postgres no responde tras $intentos intentos" >&2
  return 1
}

case "$MODO" in
  servicio)
    esperar_a_postgres
    if [[ "${APLICAR_MIGRACIONES:-false}" == "true" ]]; then
      # Solo en desarrollo. En producción las aplica un paso aparte, antes de
      # levantar nada: si dos réplicas migran a la vez, la segunda se encuentra
      # el esquema a medias.
      echo "Aplicando migraciones de ${SERVICIO}…"
      alembic -x servicio="$SERVICIO" upgrade head
    fi
    PUERTO="${SERVICE_PORT:-8000}"
    WORKERS="${UVICORN_WORKERS:-1}"
    echo "Arrancando ${SERVICIO} en :${PUERTO} (${WORKERS} worker/s)"
    exec uvicorn "$(modulo_del_servicio "$SERVICIO")" \
      --host "${SERVICE_HOST:-0.0.0.0}" \
      --port "$PUERTO" \
      --workers "$WORKERS" \
      --no-access-log
    ;;
  migrar)
    esperar_a_postgres
    exec alembic -x servicio="$SERVICIO" upgrade head
    ;;
  worker)
    esperar_a_postgres
    exec python -m "services.${SERVICIO}.worker"
    ;;
  shell)
    exec python
    ;;
  *)
    echo "Modo desconocido: $MODO (usa servicio|migrar|worker|shell)" >&2
    exit 2
    ;;
esac
