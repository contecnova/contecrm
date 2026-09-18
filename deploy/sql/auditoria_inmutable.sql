-- ═══════════════════════════════════════════════════════════════════════════
--  La traza de auditoría, de solo inserción
-- ═══════════════════════════════════════════════════════════════════════════
--
-- La cadena de hash detecta la manipulación **a posteriori**. Esto la impide
-- **a priori**: un trigger que rechaza todo UPDATE y todo DELETE sobre la tabla
-- de auditoría, incluso al dueño.
--
-- Las dos cosas juntas cubren cada una el hueco de la otra:
--   * el trigger impide alterar la traza desde la aplicación,
--   * la cadena detecta que alguien la alteró saltándose el trigger (por
--     ejemplo, desactivándolo con permisos de administrador de la base).
--
-- Lo único que no cubre ninguna de las dos es un administrador de base de datos
-- con acceso total y tiempo: puede desactivar el trigger, reescribir la traza y
-- recalcular todos los hashes. Contra eso solo vale anclar periódicamente el
-- último hash fuera de la base (almacenamiento WORM, otro sistema, un tercero),
-- que es una operación documentada en el manual de operación.
--
-- Uso:  psql "$URL" -v esquema=tenancy -f deploy/sql/auditoria_inmutable.sql

\set esquema :esquema

CREATE OR REPLACE FUNCTION public.auditoria_solo_insercion()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  RAISE EXCEPTION
    'La traza de auditoría es de solo inserción: % no está permitido sobre %',
    TG_OP, TG_TABLE_NAME
    USING HINT = 'Para cumplir la retención usa la purga documentada, que borra '
                 'por bloques completos y deja constancia del propio borrado.';
END $$;

DO $$
DECLARE esq text := :'esquema';
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = esq AND c.relname = 'auditoria'
  ) THEN
    EXECUTE format('DROP TRIGGER IF EXISTS trg_auditoria_inmutable ON %I.auditoria', esq);
    EXECUTE format($t$
      CREATE TRIGGER trg_auditoria_inmutable
        BEFORE UPDATE OR DELETE ON %I.auditoria
        FOR EACH ROW EXECUTE FUNCTION public.auditoria_solo_insercion()
    $t$, esq);
    RAISE NOTICE 'Traza de auditoría de %.auditoria protegida contra UPDATE y DELETE', esq;
  END IF;
END $$;
