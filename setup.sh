#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════
#  contecrm — instalación y arranque
#  Compatible: macOS y Linux
#
#  Uso:
#    ./setup.sh instalar              prepara el entorno (una vez)
#    ./setup.sh arrancar              levanta todo en local, sin Docker
#    ./setup.sh arrancar --docker     levanta todo con Docker (como producción)
#    ./setup.sh parar                 para lo que haya levantado
#    ./setup.sh estado                qué está corriendo y si responde
#    ./setup.sh migrar                aplica las migraciones de los 8 servicios
#    ./setup.sh gates                 corre los gates locales (sustituyen a la CI)
#    ./setup.sh demo                  siembra un tenant de demostración
#
#  ── Dos formas de levantarlo, y las dos son legítimas ────────────────────
#
#  SIN Docker (`arrancar`): Python en la máquina y Postgres embebido. Arranca en
#  segundos y recarga al guardar. Es lo que se usa para programar.
#
#  CON Docker (`arrancar --docker`): Postgres y NATS de verdad, que es lo que hay
#  en producción. Es lo que se usa para reproducir un fallo que «solo pasa en el
#  servidor» y para probar el aislamiento entre tenants.
#
#  La diferencia importa y no es cosmética: el Postgres embebido corre como
#  superusuario, y un superusuario **se salta las políticas de RLS aunque estén
#  en FORCE**. Un fallo de aislamiento solo se reproduce con Docker.
# ═══════════════════════════════════════════════════════════════════════════

set -euo pipefail
cd "$(dirname "$0")"

VERDE='\033[0;32m'; ROJO='\033[0;31m'; AMARILLO='\033[0;33m'; GRIS='\033[0;90m'; FIN='\033[0m'
ok()    { echo -e "  ${VERDE}✓${FIN} $*"; }
malo()  { echo -e "  ${ROJO}✗${FIN} $*"; }
aviso() { echo -e "  ${AMARILLO}!${FIN} $*"; }
info()  { echo -e "  ${GRIS}·${FIN} $*"; }
titulo(){ echo -e "\n${VERDE}── $* ${FIN}"; }

PY=".venv/bin/python"
PIP=".venv/bin/pip"
VAR="var"                 # pid, logs y datos locales; está en .gitignore
SERVICIOS=(tenancy identity metadata orchestrator automation integration eventing gateway)

# Puertos locales. El gateway es el único que hace falta conocer: los demás
# están detrás de él y se publican solo para poder llamarlos al depurar.
#
# Se resuelven con una función y no con un array asociativo porque **macOS trae
# bash 3.2**, que no los tiene: `declare -A` falla con «unbound variable» y el
# script no arranca. Es el tipo de cosa que solo se descubre ejecutándolo.
puerto_de() {
  case "$1" in
    tenancy)      echo 8001 ;;
    identity)     echo 8002 ;;
    metadata)     echo 8003 ;;
    orchestrator) echo 8004 ;;
    automation)   echo 8005 ;;
    integration)  echo 8006 ;;
    eventing)     echo 8007 ;;
    gateway)      echo "${GATEWAY_PORT:-8080}" ;;
    *)            echo 0 ;;
  esac
}

# ── Comprobaciones previas ───────────────────────────────────────────────────
comprobar_python() {
  if ! command -v python3 >/dev/null 2>&1; then
    malo "No hay python3. Instálalo (3.12 o superior) y vuelve a intentarlo."
    exit 1
  fi
  local version
  version=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
  if [[ $(echo "$version < 3.12" | bc -l 2>/dev/null || echo 0) == 1 ]]; then
    malo "Python $version. Hace falta 3.12 o superior."
    exit 1
  fi
  ok "Python $version"
}

# ── instalar ─────────────────────────────────────────────────────────────────
instalar() {
  titulo "Preparando el entorno"
  comprobar_python

  if [[ ! -d .venv ]]; then
    python3 -m venv .venv
    ok "Entorno virtual creado"
  else
    info "Entorno virtual ya existía"
  fi

  $PIP -q install --upgrade pip
  $PIP -q install -r requirements.txt -r requirements-dev.txt
  $PIP -q install -e packages/crmcore
  ok "Dependencias instaladas"

  if [[ ! -f .env ]]; then
    cp .env.example .env
    # Secretos de desarrollo generados al azar. Nunca valores fijos: un secreto
    # de ejemplo que funciona acaba llegando a producción porque «ya venía así».
    local clave cifrado
    clave=$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')
    cifrado=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
    python3 - "$clave" "$cifrado" <<'PY'
import pathlib, sys, re
clave, cifrado = sys.argv[1], sys.argv[2]
p = pathlib.Path(".env"); t = p.read_text()
t = re.sub(r"^ENV=.*$", "ENV=dev", t, flags=re.M)
t = re.sub(r"^SECRET_KEY=.*$", f"SECRET_KEY={clave}", t, flags=re.M)
t = re.sub(r"^ENCRYPTION_KEY=.*$", f"ENCRYPTION_KEY={cifrado}", t, flags=re.M)
t = re.sub(r"^BUS_BACKEND=.*$", "BUS_BACKEND=memoria", t, flags=re.M)
p.write_text(t)
PY
    ok ".env creado con secretos generados al azar"
  else
    info ".env ya existía (no se toca)"
  fi

  if command -v git >/dev/null 2>&1 && [[ -d .git ]]; then
    # Los gates solo protegen si están instalados. En otra solución de la casa
    # se descubrió que .git/hooks solo tenía los .sample: ningún gate había
    # corrido nunca, y en ese hueco entraron fallos que llevaban meses.
    .venv/bin/pre-commit install >/dev/null 2>&1 && ok "Gates de git instalados (commit y push)" \
      || aviso "No se han podido instalar los gates de git"
  fi

  mkdir -p "$VAR"/{log,pid,pgdata}
  titulo "Listo"
  echo "  ./setup.sh arrancar     para levantarlo"
  echo "  ./setup.sh gates        para comprobar que todo está en verde"
}

# ── Postgres local ───────────────────────────────────────────────────────────
postgres_local_uri() {
  # El arranque de Postgres vive en `scripts/postgres_local.py` y no aquí: lo
  # usan también los gates, y duplicarlo en dos sitios garantiza que uno de los
  # dos acabe desfasado.
  $PY scripts/postgres_local.py url
}

# ── arrancar ─────────────────────────────────────────────────────────────────
arrancar_docker() {
  titulo "Arrancando con Docker"
  if ! docker compose version >/dev/null 2>&1; then
    malo "Docker Compose no está disponible."
    exit 1
  fi
  docker compose --profile app up -d --build
  ok "Infraestructura y servicios levantados"
  echo
  info "Gateway:    http://localhost:8080/api/v1/docs"
  info "Logs:       docker compose logs -f gateway"
  info "Parar:      ./setup.sh parar --docker"
}

arrancar_local() {
  titulo "Arrancando en local (sin Docker)"
  [[ -d .venv ]] || { malo "Falta el entorno. Ejecuta primero: ./setup.sh instalar"; exit 1; }

  mkdir -p "$VAR"/{log,pid}
  info "Levantando Postgres embebido…"
  local uri
  uri=$(postgres_local_uri)
  ok "Postgres en $VAR/pgdata"

  export DATABASE_URL="$uri"
  export DATABASE_ADMIN_URL="$uri"
  export BUS_BACKEND="${BUS_BACKEND:-memoria}"
  export ENV=dev

  info "Aplicando migraciones…"
  $PY scripts/migrar.py --todos upgrade head >/dev/null
  $PY scripts/aplicar_rls.py --todos >/dev/null
  ok "Esquemas al día y RLS aplicada"

  local rutas=""
  for s in "${SERVICIOS[@]}"; do
    [[ "$s" == "gateway" ]] && continue
    rutas+="${s}=http://127.0.0.1:$(puerto_de "$s"),"
  done
  export RUTAS_SERVICIOS="${rutas%,}"

  for s in "${SERVICIOS[@]}"; do
    local puerto
    puerto=$(puerto_de "$s")
    SERVICE_NAME="$s" SERVICE_PORT="$puerto" \
      nohup .venv/bin/uvicorn "services.$s.main:app" \
        --host 127.0.0.1 --port "$puerto" --no-access-log \
        > "$VAR/log/$s.log" 2>&1 &
    echo $! > "$VAR/pid/$s.pid"
    ok "$s en :$puerto"
  done

  echo
  info "Esperando a que respondan…"
  sleep 3
  estado
  echo
  info "Gateway:    http://localhost:$(puerto_de gateway)/api/v1/docs"
  info "Logs:       tail -f $VAR/log/<servicio>.log"
  info "Parar:      ./setup.sh parar"
}

# ── parar ────────────────────────────────────────────────────────────────────
parar() {
  if [[ "${1:-}" == "--docker" ]]; then
    titulo "Parando Docker"
    docker compose --profile app down
    ok "Parado (los datos se conservan; usa 'docker compose down -v' para borrarlos)"
    return
  fi
  titulo "Parando los servicios locales"
  local parados=0
  for s in "${SERVICIOS[@]}"; do
    local pidfile="$VAR/pid/$s.pid"
    if [[ -f "$pidfile" ]] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
      kill "$(cat "$pidfile")" 2>/dev/null || true
      rm -f "$pidfile"
      ok "$s parado"
      parados=$((parados + 1))
    fi
  done
  [[ $parados -eq 0 ]] && info "No había nada corriendo"
  # El Postgres embebido se queda vivo a propósito: arrancarlo cuesta segundos y
  # los datos locales siguen ahí para la próxima.
  info "El Postgres local sigue levantado (borra $VAR/pgdata para empezar de cero)"
}

# ── estado ───────────────────────────────────────────────────────────────────
estado() {
  for s in "${SERVICIOS[@]}"; do
    local puerto
    puerto=$(puerto_de "$s")
    if curl -fsS --max-time 2 "http://127.0.0.1:$puerto/health/ready" >/dev/null 2>&1; then
      ok "$s :$puerto listo"
    elif curl -fsS --max-time 2 "http://127.0.0.1:$puerto/health/live" >/dev/null 2>&1; then
      # Vivo pero no listo es un estado distinto y útil: el proceso responde y
      # algo de lo que depende (base, bus) no está.
      aviso "$s :$puerto vivo pero NO listo — mira $VAR/log/$s.log"
    else
      malo "$s :$puerto no responde"
    fi
  done
}

# ── resto de comandos ────────────────────────────────────────────────────────
migrar() {
  titulo "Migrando"
  $PY scripts/migrar.py --todos upgrade head
  $PY scripts/aplicar_rls.py --todos
}

gates() {
  titulo "Gates locales (este repositorio no tiene CI, por decisión de proyecto)"
  $PY scripts/preflight.py "${@}"
}

demo() {
  titulo "Sembrando datos de demostración"
  $PY scripts/sembrar_demo.py
}

case "${1:-ayuda}" in
  instalar) instalar ;;
  arrancar)
    if [[ "${2:-}" == "--docker" ]]; then arrancar_docker; else arrancar_local; fi ;;
  parar)    parar "${2:-}" ;;
  estado)   titulo "Estado"; estado ;;
  migrar)   migrar ;;
  gates)    shift; gates "$@" ;;
  demo)     demo ;;
  *)
    sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
    ;;
esac
