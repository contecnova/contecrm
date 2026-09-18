#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════
#  Un esquema y un rol por servicio (CRM-00.03.01.02)
# ═══════════════════════════════════════════════════════════════════════════
#
# La propiedad exclusiva de datos por servicio no se sostiene con una norma en
# un documento: se sostiene con permisos. Aquí cada servicio recibe
#
#   * un esquema propio,
#   * un rol de aplicación que SOLO puede leer y escribir en ese esquema,
#   * un rol de migración que además puede hacer DDL en ese esquema.
#
# Consecuencias, que son el objetivo:
#
#   1. El servicio de ventas no puede leer la tabla de usuarios del servicio de
#      identidad aunque alguien escriba la consulta: el motor se lo deniega.
#      «No leas la base de otro servicio» deja de ser una convención.
#   2. El rol de aplicación no tiene DDL. Una inyección SQL no puede alterar el
#      esquema ni desactivar una política de seguridad.
#   3. Ningún rol de aplicación es SUPERUSER ni tiene BYPASSRLS, que es la
#      condición sin la cual Row-Level Security no aísla nada aunque esté
#      activada (ver deploy/sql/rls.sql).
#
# Uso (lo ejecuta el contenedor de Postgres al inicializarse, y también se
# puede lanzar a mano contra una base existente — es idempotente):
#
#   psql "$ADMIN_DATABASE_URL" -v pw_app="'clave'" -f deploy/crear-bases.sh
#
# En producción, las contraseñas vienen del entorno y NUNCA de este fichero.

set -euo pipefail

SERVICIOS="${CRM_SERVICIOS:-tenancy identity metadata orchestrator automation integration eventing gateway party sales}"
DB="${POSTGRES_DB:-contecrm}"
ADMIN="${POSTGRES_USER:-contecrm}"

# En desarrollo la contraseña es conocida y está bien que lo sea: el compose no
# publica Postgres fuera del loopback. En producción, `setup.sh` exige que estas
# variables vengan del entorno y se niega a arrancar con el valor de ejemplo.
PW_APP="${CRM_DB_PASSWORD_APP:-contecrm_dev_only}"
PW_MIG="${CRM_DB_PASSWORD_MIGRACION:-contecrm_dev_only}"

psql -v ON_ERROR_STOP=1 --username "$ADMIN" --dbname "$DB" <<SQL
-- Extensiones que usa el núcleo. \`pgcrypto\` para gen_random_uuid() en los
-- defaults de servidor; \`pg_trgm\` para la búsqueda difusa de duplicados
-- (CRM-01.01.04.02), que se usará en la fase 1 y conviene tener ya.
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
SQL

for SVC in $SERVICIOS; do
  ROL_APP="crm_${SVC}_app"
  ROL_MIG="crm_${SVC}_mig"
  ESQUEMA="${SVC}"

  psql -v ON_ERROR_STOP=1 --username "$ADMIN" --dbname "$DB" <<SQL
-- ── Roles ───────────────────────────────────────────────────────────────
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${ROL_APP}') THEN
    EXECUTE format('CREATE ROLE %I LOGIN PASSWORD %L', '${ROL_APP}', '${PW_APP}');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${ROL_MIG}') THEN
    EXECUTE format('CREATE ROLE %I LOGIN PASSWORD %L', '${ROL_MIG}', '${PW_MIG}');
  END IF;
END \$\$;

-- CRÍTICO: sin esto, RLS no aísla nada. Un SUPERUSER —o un rol con BYPASSRLS—
-- se salta las políticas aunque estén en FORCE, así que el sistema parecería
-- aislado y no lo estaría. Se reafirma en cada ejecución por si alguien lo
-- concedió a mano para depurar y se le olvidó quitarlo.
ALTER ROLE ${ROL_APP} NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
ALTER ROLE ${ROL_MIG} NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;

-- ── Esquema ─────────────────────────────────────────────────────────────
CREATE SCHEMA IF NOT EXISTS ${ESQUEMA} AUTHORIZATION ${ROL_MIG};

GRANT CONNECT ON DATABASE ${DB} TO ${ROL_APP}, ${ROL_MIG};
GRANT USAGE ON SCHEMA ${ESQUEMA} TO ${ROL_APP};
GRANT USAGE ON SCHEMA public TO ${ROL_APP}, ${ROL_MIG};

-- Datos sí, DDL no: el rol que atiende peticiones no puede alterar el esquema.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA ${ESQUEMA} TO ${ROL_APP};
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA ${ESQUEMA} TO ${ROL_APP};

-- Lo mismo para lo que cree el rol de migración a partir de ahora. Sin esta
-- línea, cada tabla nueva nace invisible para la aplicación y el fallo aparece
-- al desplegar, no al migrar.
ALTER DEFAULT PRIVILEGES FOR ROLE ${ROL_MIG} IN SCHEMA ${ESQUEMA}
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ${ROL_APP};
ALTER DEFAULT PRIVILEGES FOR ROLE ${ROL_MIG} IN SCHEMA ${ESQUEMA}
  GRANT USAGE, SELECT ON SEQUENCES TO ${ROL_APP};

-- Y lo que de verdad cierra la puerta: nadie más entra en este esquema.
REVOKE ALL ON SCHEMA ${ESQUEMA} FROM PUBLIC;
SQL

  echo "  ✓ ${SVC}: esquema ${ESQUEMA}, roles ${ROL_APP} (datos) y ${ROL_MIG} (DDL)"
done

echo "Listo: ${SERVICIOS// /, }"
