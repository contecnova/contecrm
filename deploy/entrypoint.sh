#!/bin/bash
# Punto de entrada único de la imagen.
#
#   entrypoint.sh servicio <nombre>   arranca un servicio con uvicorn
#   entrypoint.sh migrar <nombre>     aplica las migraciones de ese servicio
#   entrypoint.sh worker <nombre> [m]  arranca un worker de fondo del servicio
#                                     (m = módulo, por defecto `worker`)
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
  local ultimo_error=""
  for ((i = 1; i <= intentos; i++)); do
    # El error se guarda en vez de tirarse a /dev/null. Se tiraba, y el día que
    # la base estaba levantada pero al rol del servicio le faltaba la
    # contraseña, el log decía «esperando a Postgres» sesenta segundos y luego
    # «no responde» — cuando Postgres respondía perfectamente y lo que pasaba
    # era «password authentication failed for user crm_party_app». Un minuto de
    # log que describe un problema que no existe y esconde el que sí.
    if ultimo_error="$(python -c "
from sqlalchemy import create_engine, text
from crmcore.config import get_settings
create_engine(get_settings().database_url, pool_pre_ping=True).connect().execute(text('SELECT 1'))
" 2>&1)"; then
      return 0
    fi
    echo "  esperando a Postgres ($i/$intentos)…"
    sleep 2
  done
  echo "Postgres no responde tras $intentos intentos. Último error:" >&2
  # Solo la última línea: el traceback de SQLAlchemy son treinta líneas y el
  # motivo está siempre en la última.
  echo "  ${ultimo_error##*$'\n'}" >&2
  return 1
}

case "$MODO" in
  servicio)
    esperar_a_postgres
    if [[ "${APLICAR_MIGRACIONES:-false}" == "true" && "$SERVICIO" != "gateway" ]]; then
      # Solo en desarrollo. En producción las aplica un paso aparte, antes de
      # levantar nada: si dos réplicas migran a la vez, la segunda se encuentra
      # el esquema a medias.
      #
      # El gateway se excluye porque no tiene modelos propios —su estado es la
      # tabla de rutas, que viene de la configuración—, así que migrarlo sería
      # una llamada que no hace nada y que exige privilegios que no necesita.
      echo "Aplicando migraciones de ${SERVICIO}…"
      # Se llama al envoltorio, NO a `alembic` directamente. Alembic construye
      # su directorio de versiones desde `alembic.ini`, donde no hay
      # `version_locations`: buscaría en `alembic/versions/` —que está vacío,
      # porque cada servicio tiene su subcarpeta— y no encontraría ninguna
      # revisión. El resultado era silencioso y peor que un error: los
      # contenedores arrancaban «bien», sin una sola tabla creada, y el fallo
      # aparecía mucho después en la primera consulta.
      python scripts/migrar.py "$SERVICIO" upgrade head
      # Y las políticas de aislamiento, que una tabla nueva no trae puestas.
      python scripts/aplicar_rls.py "$SERVICIO"
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
    python scripts/migrar.py "$SERVICIO" upgrade head
    exec python scripts/aplicar_rls.py "$SERVICIO"
    ;;
  worker)
    esperar_a_postgres
    # Un servicio puede tener más de un worker con bucles distintos: el del
    # motor de procesos avanza instancias, el de trabajos consume lotes. El
    # tercer argumento dice cuál, y por defecto es el histórico.
    MODULO_WORKER="${3:-worker}"
    exec python -m "services.${SERVICIO}.${MODULO_WORKER}"
    ;;
  shell)
    exec python
    ;;
  *)
    echo "Modo desconocido: $MODO (usa servicio|migrar|worker|shell)" >&2
    exit 2
    ;;
esac
