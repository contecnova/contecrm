-- ═══════════════════════════════════════════════════════════════════════════
--  Row-Level Security: el aislamiento entre tenants, en el motor
-- ═══════════════════════════════════════════════════════════════════════════
--
-- Es la garantía dura de CRM-00.01.02.01. Aunque una consulta cruda, un `text()`
-- o un descuido olvidaran el filtro de tenant, la base de datos **no devuelve
-- filas de otro tenant**.
--
-- Cómo funciona: toda tabla con columna `tenant_id` queda con RLS activada y
-- FORZADA, y una política que solo deja ver las filas cuyo `tenant_id` coincide
-- con el GUC de sesión `app.current_tenant`. Ese GUC lo fija
-- `crmcore.db.session` al empezar cada transacción, con `is_local => true` para
-- que muera con ella y no pueda filtrarse a la siguiente petición que reutilice
-- la conexión.
--
-- El GUC vacío significa **contexto de sistema** (migraciones, mantenimiento,
-- consola de plataforma) y la política es permisiva ahí. Eso es a propósito:
-- las migraciones tienen que poder tocar todas las filas. Lo que impide que ese
-- camino se use por descuido es que abrir una sesión sin tenant exige escribir
-- `sistema=True` en el código (ver `crmcore.db.session.nueva_sesion`).
--
-- ── Limitación, dicha claramente ──────────────────────────────────────────
-- Un rol SUPERUSER o con BYPASSRLS **ignora** estas políticas aunque estén en
-- FORCE. Si la aplicación conecta con un rol así, RLS está «activada» y no
-- aísla nada — que es peor que no tenerla, porque da confianza sin darla.
--   * `deploy/crear-bases.sh` crea los roles sin esos atributos.
--   * `crmcore.db.session.verificar_rol_sin_bypass()` lo comprueba al arrancar
--     y lo registra como error.
--   * `tests/integration/test_rls_aislamiento.py` lo verifica de verdad,
--     intentando leer datos de otro tenant con el rol de aplicación.
--
-- Uso: se aplica por esquema, después de las migraciones de cada servicio.
--   psql "$URL" -v esquema=tenancy -f deploy/sql/rls.sql

\set esquema :esquema

DO $$
DECLARE
  t text;
  esq text := current_setting('rls.esquema', true);
BEGIN
  IF esq IS NULL OR esq = '' THEN
    esq := :'esquema';
  END IF;

  FOR t IN
    SELECT c.relname
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
      JOIN pg_attribute a ON a.attrelid = c.oid
     WHERE n.nspname = esq
       AND c.relkind = 'r'
       AND a.attname = 'tenant_id'
       AND NOT a.attisdropped
  LOOP
    EXECUTE format('ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY', esq, t);
    -- FORCE: sin él, el DUEÑO de la tabla se salta su propia política, y el rol
    -- de migración es el dueño. Con FORCE, ni el dueño ve de más.
    EXECUTE format('ALTER TABLE %I.%I FORCE ROW LEVEL SECURITY', esq, t);
    EXECUTE format('DROP POLICY IF EXISTS aislamiento_tenant ON %I.%I', esq, t);
    EXECUTE format($pol$
      CREATE POLICY aislamiento_tenant ON %I.%I
        USING (
          tenant_id::text = current_setting('app.current_tenant', true)
          OR coalesce(current_setting('app.current_tenant', true), '') = ''
        )
        WITH CHECK (
          -- WITH CHECK aparte de USING, y esto importa: sin él se pueden LEER
          -- solo las filas propias pero INSERTAR filas con el tenant_id de otro.
          -- Una fuga de escritura es peor que una de lectura.
          tenant_id::text = current_setting('app.current_tenant', true)
          OR coalesce(current_setting('app.current_tenant', true), '') = ''
        )
    $pol$, esq, t);
    RAISE NOTICE 'RLS activada en %.%', esq, t;
  END LOOP;
END $$;
