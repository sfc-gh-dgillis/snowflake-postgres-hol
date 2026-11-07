-- ========================================================================
-- drop_lab_tables.sql   (Postgres, existing-mode teardown)
--
-- Drops ONLY the tables this lab created (marked 'Created by
-- snowflake-postgres-hol'), children first, and without CASCADE so that
-- anything else depending on them makes the drop fail instead of
-- silently disappearing. Run only after the mirror has been dropped.
-- ========================================================================

SELECT set_config('lab.pg_schema', :'pg_schema', false) AS lab_schema;

DO $$
DECLARE
    lab_table TEXT;
BEGIN
    FOREACH lab_table IN ARRAY ARRAY['maintenance_events', 'readings', 'sensors', 'devices'] LOOP
        IF EXISTS (
            SELECT 1
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = current_setting('lab.pg_schema')
              AND c.relname = lab_table
              AND obj_description(c.oid, 'pg_class') = 'Created by snowflake-postgres-hol'
        ) THEN
            EXECUTE format('DROP TABLE %I.%I', current_setting('lab.pg_schema'), lab_table);
            RAISE NOTICE 'Dropped %.%', current_setting('lab.pg_schema'), lab_table;
        END IF;
    END LOOP;
END $$;
