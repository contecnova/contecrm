#!/usr/bin/env bash
# Ejecuta algo con el Python del repositorio.
#
# Los ganchos de pre-commit con `language: system` heredan el PATH de git, no
# el de la terminal. Si el entorno virtual no está activado —y en un `git
# commit` desde un editor nunca lo está— `python` es el del sistema, que no
# tiene instalado `crmcore`: los gates fallaban con «No module named crmcore»
# y eso no dice «tienes el entorno sin activar», dice «tu código está roto».
#
#     scripts/con-entorno.sh python -m pytest ...
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -x "$RAIZ/.venv/bin/python" ]]; then
  export PATH="$RAIZ/.venv/bin:$PATH"
  export VIRTUAL_ENV="$RAIZ/.venv"
fi
exec "$@"
