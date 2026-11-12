-- ========================================================================
-- mirror_objects.sql   (Postgres)
--
-- What CREATE_MIRROR set up inside Postgres. You never ran CREATE EXTENSION:
-- the managed mirror provisions all of this for you.
--   * extensions: snowflake_cdc (change capture) and pg_lake (Iceberg writer)
--   * a publication and a logical replication slot named after the mirror
--   * per-table change log tables (Iceberg, written through pg_lake) in the
--     snowflake_cdc_logs schema; Snowflake reads them as <table>$changes
-- ========================================================================

\echo
\echo '== Extensions installed on the instance'
SELECT extname, extversion FROM pg_extension ORDER BY extname;

\echo
\echo '== Publication that drives logical replication'
SELECT pubname, pubinsert, pubupdate, pubdelete, pubtruncate
FROM pg_publication WHERE pubname = :'mirror_name';

SELECT schemaname, tablename FROM pg_publication_tables
WHERE pubname = :'mirror_name' ORDER BY schemaname, tablename;

\echo
\echo '== Replication slot (the durable decoding cursor) and how far behind it is'
SELECT slot_name, plugin, slot_type, active,
       pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), confirmed_flush_lsn)) AS unconfirmed_wal
FROM pg_replication_slots WHERE slot_name = :'mirror_name';

\echo
\echo '== Change log tables written through pg_lake'
SELECT c.relname AS change_log_table, c.relkind
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'snowflake_cdc_logs' AND c.relkind IN ('r', 'p', 'f')
ORDER BY c.relname;

SELECT to_regclass('snowflake_cdc.snapshot_status') IS NOT NULL AS has_snapshot_status \gset
\if :has_snapshot_status
\echo
\echo '== Per-table snapshot state (the view behind LIST_MIRRORED_TABLES)'
SELECT schema_name, table_name, snapshot_state, reason, last_snapshot_error
FROM snowflake_cdc.snapshot_status
WHERE publication_name = :'mirror_name'
ORDER BY schema_name, table_name;
\endif
