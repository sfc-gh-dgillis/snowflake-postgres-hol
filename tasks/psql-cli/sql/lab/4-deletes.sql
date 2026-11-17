-- ========================================================================
-- Step 4 - Deletes   (Postgres)
--
-- Deletes replicate too: the rows disappear from the Snowflake target table
-- on the next apply run, and READINGS$changes keeps a record of them.
-- (UPDATE/DELETE replication requires a primary key; these tables have one.)
-- ========================================================================

SET search_path TO :"pg_schema";

SELECT COUNT(*) AS readings_before_delete FROM readings;

-- Remove all readings older than 12 hours
DELETE FROM readings WHERE ts < NOW() - INTERVAL '12 hours';

SELECT COUNT(*) AS readings_after_delete FROM readings;
