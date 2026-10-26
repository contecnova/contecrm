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
#    ./setup.sh vecinos [orden]       contecintelligence y contecmind
#                                     (estado | levantar | parar)
#
#  ── contecrm no es autosuficiente, y no se le pide que lo sea ────────────
#
#  La explotación del dato la resuelve contecintelligence (RT-4) y el corpus
#  documental contecmind (RT-5). Son dependencias de despliegue, no extras:
#  arrancar solo contecrm deja pantallas que no pueden funcionar. Por eso
#  `arrancar --docker` los levanta también, con SU propio compose y no con una
#  copia de su topología aquí.
#
#  Si ya tienes uno en marcha en otro sitio, dale su dirección en CI_BASE_URL /
#  DMS_BASE_URL y arranca con SIN_VECINOS=1.
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
# LOS CATORCE, no once. Faltaban `service`, `marketing` e `intelligence`: se
# añadieron al producto después y nadie los puso aquí, así que quien seguía el
# camino documentado levantaba un CRM sin casos, sin marketing y sin IA.
SERVICIOS=(tenancy identity metadata orchestrator automation integration eventing party sales service marketing analytics intelligence gateway)

# Y LOS WORKERS, que no estaban en absoluto: `setup.sh` no mencionaba la palabra
# «worker» ni una vez, mientras el compose arrancaba seis.
#
# Es el fallo más difícil de ver que hay: un sistema sin workers **arranca,
# contesta y se ve perfecto**, y lo asíncrono se encola y no pasa nunca, sin
# error. Ya se cazó una vez por el lado de Docker —el comentario sigue en el
# `docker-compose.yml`— y nadie miró el lado nativo.
#
# Cada entrada es `servicio:modulo`, igual que en el compose: un servicio puede
# tener más de un bucle.
WORKERS=(orchestrator:worker identity:reparto_worker party:trabajos_worker sales:trabajos_worker intelligence:trabajos_worker analytics:trabajos_worker)

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
    party)        echo 8008 ;;
    sales)        echo 8009 ;;
    analytics)    echo 8010 ;;
    service)      echo 8011 ;;
    marketing)    echo 8012 ;;
    intelligence) echo 8013 ;;
    gateway)      echo "${GATEWAY_PORT:-18080}" ;;
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

# Lee un ajuste del .env sin cargarlo entero (el fichero no es un script de shell).
valor_env() {
  local v
  v=$(grep -E "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2- || true)
  v="${v%\"}"; v="${v#\"}"; v="${v%\'}"; v="${v#\'}"
  printf '%s' "$v"
}

# La cuenta con la que se entra tras arrancar: es la del .env, que se aplica en cada arranque.
mostrar_acceso() {
  local email pass tenant
  email=$(valor_env SUPERADMIN_EMAIL)
  pass=$(valor_env SUPERADMIN_PASSWORD)
  tenant=$(valor_env SUPERADMIN_TENANT)
  [[ -n "$email" ]] || return 0
  titulo "Acceso"
  info "Usuario:    $email"
  info "Contraseña: $pass"
  info "Empresa:    ${tenant:-plataforma}"
}
# Deja el daemon de Docker accesible: si está apagado intenta encenderlo según
# el sistema (Docker Desktop, OrbStack, Colima, systemd) y espera a que responda.
asegurar_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    malo "Docker no está instalado. macOS: brew install --cask docker · Linux: https://docs.docker.com/get-docker/"
    exit 1
  fi
  docker info >/dev/null 2>&1 && return 0

  aviso "El daemon de Docker no responde; intentando arrancarlo..."
  case "$(uname -s)" in
    Darwin)
      if [[ -d "/Applications/Docker.app" || -d "$HOME/Applications/Docker.app" ]]; then
        open -ga Docker
      elif [[ -d "/Applications/OrbStack.app" ]]; then
        open -ga OrbStack
      elif command -v colima >/dev/null 2>&1; then
        colima start
      fi ;;
    Linux)
      if command -v systemctl >/dev/null 2>&1; then
        systemctl start docker 2>/dev/null || sudo systemctl start docker
      fi ;;
  esac

  local esperado=0
  while ! docker info >/dev/null 2>&1; do
    if (( esperado >= 180 )); then
      malo "Docker no ha arrancado en 3 minutos. Ábrelo a mano y repite el comando."
      exit 1
    fi
    sleep 3; esperado=$((esperado + 3))
    (( esperado % 15 == 0 )) && info "Esperando al daemon de Docker (${esperado}s)..."
  done
  ok "Docker listo"
}

arrancar_docker() {
  titulo "Arrancando con Docker"
  asegurar_docker
  if ! docker compose version >/dev/null 2>&1; then
    malo "Docker Compose no está disponible."
    exit 1
  fi
  # Los volúmenes de datos son EXTERNOS a propósito: así un `down -v` no se los
  # lleva. Compose no los crea —esa es justo la protección— así que se crean
  # aquí. `docker volume create` es idempotente: si ya está, no hace nada.
  for volumen in contecrm_datos_postgres contecrm_datos_nats; do
    if ! docker volume inspect "$volumen" >/dev/null 2>&1; then
      docker volume create "$volumen" >/dev/null
      ok "Volumen de datos «${volumen}» creado"
    fi
  done

  docker compose --profile app --profile consola up -d --build
  ok "Infraestructura, servicios y consola levantados"

  # Y los servicios de la casa de los que esto DEPENDE. No son un extra: sin
  # contecintelligence no hay informes ni cuadros de mando (RT-4) y sin
  # contecmind no hay corpus documental (RT-5). Arrancar solo contecrm deja
  # pantallas que no pueden funcionar y nadie sabe por qué.
  #
  # Se hace después de contecrm porque los vecinos se enganchan a SU red, que no
  # existe hasta que contecrm está arriba.
  if [[ "${SIN_VECINOS:-}" == "1" ]]; then
    aviso "Vecinos omitidos (SIN_VECINOS=1): sin explotación del dato ni corpus"
  else
    titulo "Servicios de la casa de los que depende"
    $PY scripts/vecinos.py levantar || aviso "Algún vecino no ha subido; mira arriba qué falta"
    # Una base nueva de contecintelligence no conoce a contecrm: se le da de alta.
    titulo "Explotación (contecrm ↔ contecintelligence)"
    python3 scripts/alta_explotacion.py \
      || aviso "La explotación no quedó enlazada; repite: python3 scripts/alta_explotacion.py"
  fi

  arrancar_front

  echo
  info "Front:      http://localhost:${FRONT_PORT:-15173}   (desarrollo, recarga al guardar)"
  info "Consola:    http://localhost:${CONSOLA_PORT:-13000}   (la del contenedor)"
  info "Gateway:    http://localhost:${GATEWAY_PORT:-18080}/api/v1/docs"
  info "Logs:       docker compose logs -f gateway"
  info "Vecinos:    ./setup.sh vecinos"
  info "Parar:      ./setup.sh parar --docker"
  mostrar_acceso
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

  # Los workers, DESPUÉS de los servicios HTTP: es el servicio de cada esquema
  # quien aplica las migraciones, y dos procesos migrando a la vez es la forma
  # habitual de dejar un `alembic` a medias. Por eso el compose les pone
  # `APLICAR_MIGRACIONES: false` y aquí ya están hechas más arriba.
  for w in "${WORKERS[@]}"; do
    local svc="${w%%:*}" modulo="${w##*:}"
    SERVICE_NAME="$svc" APLICAR_MIGRACIONES=false \
      nohup .venv/bin/python -m "services.$svc.$modulo" \
        > "$VAR/log/$svc-$modulo.log" 2>&1 &
    echo $! > "$VAR/pid/$svc-$modulo.pid"
    ok "worker $svc/$modulo"
  done

  echo
  info "Esperando a que respondan…"
  # Un `sleep` fijo daba falsos «no responde» en servicios que tardan en subir.
  local intentos=0 salida_estado
  while :; do
    salida_estado=$(estado 2>&1)
    if ! grep -qE '✗|!' <<<"$salida_estado" || (( intentos >= 30 )); then break; fi
    sleep 3; intentos=$((intentos + 1))
  done
  echo "$salida_estado"
  echo

  # En Docker lo hace el entrypoint; en local no lo hacía nadie y el usuario del
  # .env no existía, así que el acceso impreso no funcionaba.
  if [[ -n "$(valor_env SUPERADMIN_EMAIL)" ]]; then
    $PY scripts/cuenta_de_arranque.py >/dev/null 2>"$VAR/log/cuenta_de_arranque.log" \
      && ok "Cuenta de acceso lista" \
      || aviso "No se pudo dejar la cuenta de acceso: mira $VAR/log/cuenta_de_arranque.log"
  fi
  # LA INTERFAZ. Esto faltaba, y dejaba el arranque local a medias: se
  # levantaban los catorce servicios, se imprimía la URL de la documentación y
  # se acababa. Quien lo ejecutaba se quedaba con una API en pie y **sin
  # pantalla**, sin que nada se lo dijera — y la línea del gateway, que lleva
  # «/api/v1/docs», se lee como «aquí está el producto» cuando es el contrato.
  #
  # La llamada estaba escrita y sólo la hacía `arrancar_docker`.
  arrancar_front

  echo
  info "Interfaz:   http://localhost:${FRONT_PORT:-15173}   ← empieza por aquí"
  info "Gateway:    http://localhost:$(puerto_de gateway)/api/v1/docs   (el contrato de la API)"
  info "Logs:       tail -f $VAR/log/<servicio>.log"
  info "Parar:      ./setup.sh parar"
  mostrar_acceso
}

# ── front de desarrollo ──────────────────────────────────────────────────────
#
# El de Vite, no el del contenedor. Se levanta con el arranque porque es el que
# se usa para trabajar, y porque arrancarlo a mano significa arrancarlo con las
# variables de la terminal de quien lo lanza: al reiniciar la máquina eso se
# pierde y `npm run dev` a secas abre otro puerto contra un gateway que no está.
arrancar_front() {
  [[ "${SIN_FRONT:-}" == "1" ]] && { aviso "Front de desarrollo omitido (SIN_FRONT=1)"; return 0; }
  command -v npm >/dev/null 2>&1 || { aviso "npm no está: sin front de desarrollo"; return 0; }
  [[ -d frontend/node_modules ]] || { aviso "Faltan dependencias del front: npm --prefix frontend install"; return 0; }

  local puerto
  puerto=$(grep -E "^FRONT_PORT=" .env 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"' || true)
  puerto="${puerto:-15173}"
  if lsof -nP -iTCP:"$puerto" -sTCP:LISTEN >/dev/null 2>&1; then
    ok "El front ya está en :$puerto"
    return 0
  fi

  mkdir -p "$VAR"/log
  # Las dos variables que el front necesita, leídas del `.env` SIN interpretarlo
  # como shell. `source .env` parece lo natural y no sirve aquí: hay valores que
  # son listas JSON —`DMS_SCOPES=["documents:read", "documents:search"]`— y el
  # shell los parte por el espacio e intenta ejecutar el segundo trozo. Da un
  # «command not found» en mitad del arranque y, peor, deja de exportar lo que
  # venía detrás.
  local valor
  for clave in FRONT_PORT GATEWAY_PORT GATEWAY_URL; do
    valor=$(grep -E "^${clave}=" .env 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"' || true)
    [[ -n "$valor" ]] && export "$clave=$valor"
  done
  nohup npm --prefix frontend run dev > "$VAR/log/front.log" 2>&1 &
  echo $! > "$VAR/pid/front.pid"

  # Se ESPERA a que escuche, y si no, se dice. Antes se imprimía «Front en
  # :15173» en cuanto se lanzaba el proceso: con un fallo de compilación o un
  # puerto ocupado, el mensaje decía que estaba y no estaba, que es peor que no
  # decir nada — se va a la URL, no carga, y se busca el problema en el sitio
  # equivocado.
  local intentos=0
  while (( intentos < 30 )); do
    if lsof -nP -iTCP:"$puerto" -sTCP:LISTEN >/dev/null 2>&1; then
      ok "Interfaz en http://localhost:$puerto"
      return 0
    fi
    sleep 1; intentos=$((intentos + 1))
  done
  malo "La interfaz no ha llegado a escuchar en :$puerto — mira $VAR/log/front.log"
  return 0
}

# ── parar ────────────────────────────────────────────────────────────────────
parar() {
  if [[ "${1:-}" == "--docker" ]]; then
    titulo "Parando Docker"
    # Los vecinos NO se paran con contecrm salvo que se pida: lo normal es que
    # los use algo más en la misma máquina, y pararlos de rebote apagaría el
    # corpus documental de otro producto de la casa sin avisar.
    if [[ "${2:-}" == "--con-vecinos" || "${3:-}" == "--con-vecinos" ]]; then
      $PY scripts/vecinos.py parar
    fi
    # El front de desarrollo es un proceso del equipo, no un contenedor.
    if [[ -f "$VAR/pid/front.pid" ]] && kill -0 "$(cat "$VAR/pid/front.pid")" 2>/dev/null; then
      kill "$(cat "$VAR/pid/front.pid")" 2>/dev/null || true
      rm -f "$VAR/pid/front.pid"
      ok "Front de desarrollo parado"
    fi
    docker compose --profile app --profile consola down
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
  for w in "${WORKERS[@]}"; do
    local pidfile="$VAR/pid/${w%%:*}-${w##*:}.pid"
    if [[ -f "$pidfile" ]] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
      kill "$(cat "$pidfile")" 2>/dev/null || true
      rm -f "$pidfile"
      ok "worker ${w%%:*}/${w##*:} parado"
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

  # LOS WORKERS SE MIRAN POR PROCESO, no con `curl`: no escuchan en ningún
  # puerto. Y se miran, que es lo que faltaba: un worker caído no se nota desde
  # fuera —el sistema arranca, contesta y se ve perfecto— mientras lo asíncrono
  # se encola y no pasa nunca, sin error.
  for w in "${WORKERS[@]}"; do
    local svc="${w%%:*}" modulo="${w##*:}"
    local pidfile="$VAR/pid/$svc-$modulo.pid"
    if [[ -f "$pidfile" ]] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
      ok "worker $svc/$modulo corriendo"
    else
      malo "worker $svc/$modulo NO corre — lo asíncrono se encolará y no pasará nunca"
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
  parar)    shift; parar "$@" ;;
  estado)   titulo "Estado"; estado ;;
  migrar)   migrar ;;
  gates)    shift; gates "$@" ;;
  demo)     demo ;;
  vecinos)  shift; $PY scripts/vecinos.py "${1:-estado}" "${@:2}" ;;

  # Los verbos de las otras soluciones de la casa, que se escriben solos.
  #
  # Cada setup.sh habla un idioma distinto —aquí «arrancar», en contecpos
  # «start», en contecintelligence «dev», en contecmind «prodlike»— y la mano
  # escribe el del repositorio anterior. Aceptarlos cuesta una línea y ahorra
  # el rato de mirar por qué no pasa nada.
  start|up|dev)    shift; if [[ "${1:-}" == "--docker" ]]; then arrancar_docker; else arrancar_local; fi ;;
  stop|down)       shift; parar "$@" ;;
  status)          titulo "Estado"; estado ;;

  ayuda|-h|--help|help|"")
    sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
    ;;

  *)
    # Antes esto imprimía la ayuda y salía con 0, así que un verbo mal escrito
    # se veía exactamente igual que uno correcto que no hiciera nada: la
    # cabecera en pantalla y el prompt de vuelta. Decirlo cuesta dos líneas.
    echo "No conozco el comando «$1»." >&2
    echo "" >&2
    sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//' >&2
    exit 1
    ;;
esac
