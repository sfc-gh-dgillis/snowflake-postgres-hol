-- ========================================================================
-- preflight.sql   (Postgres)
--
-- Checks that the source tables can be mirrored before CREATE_MIRROR runs:
--   * ordinary (relkind r) or partitioned (p) tables, and LOGGED
--     (relpersistence p); UNLOGGED tables produce no WAL to replicate
--   * a PRIMARY KEY; without one a table is mirrored insert-only
--   * column types that map cleanly to Snowflake (all of these do:
--     integer -> INT, text -> STRING, numeric(10,2) -> DECIMAL(10,2),
--     timestamp -> TIMESTAMP)
-- ========================================================================

\echo
\echo '== Table eligibility'
SELECT n.nspname AS schema_name,
       c.relname AS table_name,
       c.relkind,
       c.relpersistence,
       EXISTS (
         SELECT 1 FROM pg_index i
         WHERE i.indrelid = c.oid AND i.indisprimary
       ) AS has_primary_key
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = :'pg_schema'
  AND c.relname IN ('devices', 'sensors', 'readings')
ORDER BY c.relname;

\echo
\echo '== Column types'
SELECT table_name, column_name, data_type, numeric_precision, numeric_scale
FROM information_schema.columns
WHERE table_schema = :'pg_schema'
  AND table_name IN ('devices', 'sensors', 'readings')
ORDER BY table_name, ordinal_position;

-- Fail fast if a table is missing, unlogged, or lacks a primary key
SELECT COUNT(*) = 3 AS tables_ok
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = :'pg_schema'
  AND c.relname IN ('devices', 'sensors', 'readings')
  AND c.relkind IN ('r', 'p')
  AND c.relpersistence = 'p'
  AND EXISTS (SELECT 1 FROM pg_index i WHERE i.indrelid = c.oid AND i.indisprimary)
\gset

\if :tables_ok
\echo '✓ devices, sensors and readings are eligible for mirroring'
\else
DO $$ BEGIN
    RAISE EXCEPTION 'A source table is missing, UNLOGGED, or has no primary key. Run task demo-up first.';
END $$;
\endif
