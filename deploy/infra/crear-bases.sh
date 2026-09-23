#!/bin/bash
# Una base por solución, dentro de la misma instancia.
#
# Se comparte el servidor, no la base: contecrm aísla sus servicios por esquema
# —`identity`, `party`, `sales`…— y contecmind puede tener esquemas con esos
# mismos nombres. En una sola base se pisarían, y el aislamiento por esquema de
# contecrm dejaría de significar nada.
#
# La extensión `vector` se crea en la base de contecintelligence, que es la que
# la usa. No en todas: una extensión que nadie usa es superficie que mantener.
set -euo pipefail

ADMIN="${POSTGRES_USER:-contec}"

crear() {
  local base="$1" con_vector="${2:-no}"
  if psql -U "$ADMIN" -tAc "SELECT 1 FROM pg_database WHERE datname='${base}'" | grep -q 1; then
    echo "  = ${base}: ya existe"
  else
    psql -U "$ADMIN" -c "CREATE DATABASE ${base}"
    echo "  + ${base}: creada"
  fi
  if [[ "$con_vector" == "vector" ]]; then
    psql -U "$ADMIN" -d "$base" -c "CREATE EXTENSION IF NOT EXISTS vector"
    echo "    · extensión vector"
  fi
}

echo "Bases de las soluciones de la casa:"
crear contecrm
crear contecmind
crear conte vector
